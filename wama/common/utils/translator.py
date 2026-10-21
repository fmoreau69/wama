"""
TranslatorService (ROADMAP §10.B) — exécute une décision de routing langue ([[lang_routing]]).

Traduit du texte via **translategemma** (Ollama, installé) avec :
- **passthrough** si langue source == cible (zéro appel) ;
- **cache** (Django cache) pour ne pas retraduire ;
- **glossaire do-not-translate** (termes métier Lescot) injecté en consigne ;
- **découpage** par paragraphes (translategemma : fenêtre de traduction effective ~2K tokens).

PAS de MT en chaîne : le routing ne déclenche une traduction QUE quand le modèle cible ne gère
pas la langue (cf. [[lang_routing]]). Le service est l'ACTEUR ; lang_routing est le DÉCIDEUR.

NB : vit en `common/utils` pour l'instant (réutilisé par plusieurs apps) ; graduera en app
`wama/translator/` quand il faudra modèles/vues/tool_api/glossaire éditable.

LE MODÈLE EST UNE CLÉ DE CATALOGUE (2026-10-16, l'app Translator — décision de Fabien : réutiliser
la brique plutôt qu'un serveur externe). Elle était figée sur `translategemma:12b` : une app dont
le réglage « Modèle » vient du catalogue (route F4b) doit pouvoir en désigner un autre, local ou
distant. Une clé `ollama:*` garde la voie locale d'origine (résidence pilotée par le gouverneur) ;
toute autre passe par `llm_utils.chat_with_catalog_model`, avec la clé et la garde cloud de
`user`. `auto` se TIRE avant (`auto_model.resolve_model_choice`) : il n'est pas une clé.
`on_chunk(texte traduit jusqu'ici)` : appelé après chaque morceau — l'aperçu « pendant »
(`preview_utils.publish_partial_text`) d'un long texte qui se traduit.
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

_CHUNK_CHARS = 4000  # ~ sous la fenêtre de traduction effective de translategemma (~2K tokens)


#: Le modèle de traduction par défaut — celui des deux consommateurs d'avant le 2026-10-16.
DEFAULT_MODEL = 'ollama:translategemma:12b'
#: Repère « pas de réglage » : la température stable de `llm_utils` (lue à l'appel, ce module
#: s'importe sans Django).
_STEADY = object()
#: Version de la consigne de `_translate_chunk`, inscrite dans la clé de cache : la changer à
#: chaque réécriture de la consigne. 2 = langues nommées par code ISO 639-1, source détectée.
PROMPT_VERSION = 2


class TranslatorService:
    def __init__(self, model: str = DEFAULT_MODEL, glossary=None, use_cache: bool = True,
                 user=None, temperature=_STEADY):
        from wama.common.utils.model_keys import catalog_key
        # Un nom Ollama nu (`translategemma:12b`, la forme d'avant) reste accepté.
        self.model = catalog_key(model or DEFAULT_MODEL, 'ollama')
        self.glossary = list(glossary or [])
        self.use_cache = use_cache
        self.user = user
        # `STEADY_TEMPERATURE` pour la traduction de prompts (sans réglage) ; une app dont la card
        # porte le réglage passe la sienne, None = celle du modèle (2026-10-21).
        self.temperature = temperature

    # ── public ───────────────────────────────────────────────────────────────
    def translate(self, text: str, source_lang: str, target_lang: str, glossary=None,
                  timeout: int = 120, on_chunk=None):
        """Traduit `text` de source_lang → target_lang. Retourne {'ok', 'text'|'error', 'cached'}."""
        text = text or ''
        if not text.strip() or not target_lang or source_lang == target_lang:
            return {'ok': True, 'text': text, 'cached': False}  # passthrough

        gloss = list(self.glossary) + list(glossary or [])
        # Une température RÉGLÉE entre dans la clé (deux températures ne rendent pas la même
        # traduction) ; sans réglage, la clé d'avant — le cache existant reste valable.
        tagged = self.model if self.temperature is _STEADY else f"{self.model}@t={self.temperature}"
        ckey = self._cache_key(text, source_lang, target_lang, gloss, tagged)
        if self.use_cache:
            cached = self._cache_get(ckey)
            if cached is not None:
                return {'ok': True, 'text': cached, 'cached': True}

        chunks = self._chunk(text)
        out = []
        for ch in chunks:
            res = self._translate_chunk(ch, source_lang, target_lang, gloss, timeout)
            if not res['ok']:
                return res
            out.append(res['text'])
            if on_chunk is not None:
                on_chunk('\n\n'.join(out))
        translated = '\n\n'.join(out)
        if self.use_cache:
            self._cache_set(ckey, translated)
        return {'ok': True, 'text': translated, 'cached': False}

    def translate_input(self, routing, text, input_lang, **kw):
        """Traduit l'entrée AVANT le run si la décision l'exige ([[lang_routing]])."""
        if not routing.get('input_translate'):
            return {'ok': True, 'text': text, 'cached': False, 'applied': False}
        r = self.translate(text, input_lang, routing['input_pivot'], **kw)
        r['applied'] = r.get('ok', False)
        return r

    def translate_output(self, routing, text, output_lang, **kw):
        """Traduit la sortie APRÈS le run si la décision l'exige ([[lang_routing]])."""
        if not routing.get('output_translate'):
            return {'ok': True, 'text': text, 'cached': False, 'applied': False}
        r = self.translate(text, routing['output_source'], output_lang, **kw)
        r['applied'] = r.get('ok', False)
        return r

    # ── interne ──────────────────────────────────────────────────────────────
    def _translate_chunk(self, text, source_lang, target_lang, glossary, timeout):
        from wama.common.utils.llm_utils import STEADY_TEMPERATURE, llm_chat
        temperature = STEADY_TEMPERATURE if self.temperature is _STEADY else self.temperature
        gloss_line = ""
        if glossary:
            gloss_line = ("\nNe traduis PAS ces termes (garde-les tels quels) : "
                          + ", ".join(glossary) + ".")
        # Les langues se nomment par leur CODE ISO 639-1, et dit comme tel ; une source inconnue
        # (« auto », la valeur par défaut du Translator) se fait DÉTECTER. Mesuré le 2026-10-16 sur
        # translategemma, 3 textes × 3 cibles : « de « auto » vers « en » » rendait le texte source
        # INCHANGÉ, « vers « en » » ratait 4 cas sur 9 (texte inchangé, ou en néerlandais) ; la
        # forme ci-dessous, 9 sur 9.
        if (source_lang or 'auto') == 'auto':
            direction = (f"dans la langue de code ISO 639-1 « {target_lang} » (détecte toi-même "
                         "la langue d'origine)")
        else:
            direction = (f"de la langue de code ISO 639-1 « {source_lang} » vers la langue de "
                         f"code « {target_lang} »")
        prompt = (
            f"Traduis le texte suivant {direction}.\n"
            f"Rends UNIQUEMENT la traduction, sans commentaire ni guillemets.{gloss_line}\n\n"
            f"{text}"
        )
        from wama.common.utils.model_keys import split_key
        source, model_id = split_key(self.model)
        messages = [{"role": "user", "content": prompt}]
        if source == 'ollama':
            # keep_alive piloté par le gouverneur : '0' en mode dépannage GPU (décharge Ollama
            # sitôt la réponse — la traduction précède souvent une génération GPU lourde), None
            # sinon (défaut Ollama, comportement nominal).
            from wama.common.services.resource_governor import pipeline_keep_alive
            out, err = llm_chat(messages=messages, provider='ollama', model=model_id,
                                num_predict=1500, think=False, timeout=timeout,
                                keep_alive=pipeline_keep_alive(), temperature=temperature)
        else:
            from wama.common.utils.llm_utils import chat_with_catalog_model
            out, err = chat_with_catalog_model(self.model, messages, user=self.user,
                                               think=False, timeout=timeout,
                                               temperature=temperature)
        if err or not out:
            return {'ok': False, 'error': err or 'réponse vide', 'cached': False}
        return {'ok': True, 'text': out.strip(), 'cached': False}

    @staticmethod
    def _chunk(text):
        if len(text) <= _CHUNK_CHARS:
            return [text]
        chunks, cur = [], ""
        for para in text.split('\n\n'):
            if cur and len(cur) + len(para) + 2 > _CHUNK_CHARS:
                chunks.append(cur)
                cur = para
            else:
                cur = (cur + '\n\n' + para) if cur else para
        if cur:
            chunks.append(cur)
        return chunks

    @staticmethod
    def _cache_key(text, src, tgt, glossary, model=DEFAULT_MODEL):
        # Le MODÈLE fait partie de la clé : deux modèles ne rendent pas la même traduction. La
        # CONSIGNE aussi, par sa version : une consigne corrigée ne doit pas resservir 30 jours ce
        # que l'ancienne rendait de faux (2026-10-16, « auto » rendu non traduit).
        h = hashlib.sha256(f"{PROMPT_VERSION}|{model}|{src}|{tgt}|{','.join(sorted(glossary))}|"
                           f"{text}".encode('utf-8')).hexdigest()
        return f"wama:translate:{h}"

    @staticmethod
    def _cache_get(key):
        try:
            from django.core.cache import cache
            return cache.get(key)
        except Exception:
            return None

    @staticmethod
    def _cache_set(key, value, ttl=2592000):  # 30 j
        try:
            from django.core.cache import cache
            cache.set(key, value, ttl)
        except Exception:
            pass
