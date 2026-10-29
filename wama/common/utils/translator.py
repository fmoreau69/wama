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
import re

logger = logging.getLogger(__name__)

#: Une balise de mise en forme de `document_text` (`<t1>`, `</t1>`) — la même forme, sans
#: importer la brique (ce module s'importe sans les librairies de documents).
_MARKUP = re.compile(r'</?t\d+>', re.IGNORECASE)

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
        # Un texte BALISÉ de sa mise en forme (`document_text`, `<t1>…</t1>` autour d'un passage
        # en gras, en italique…) : la consigne ne s'ajoute qu'à lui — celle d'un texte nu, et donc
        # son cache, ne changent pas (2026-10-29).
        markup_line = ""
        if _MARKUP.search(text):
            markup_line = ("\nLe texte porte des balises <t1>…</t1>, <t2>…</t2>… autour de "
                           "passages mis en forme : garde chacune, à l'identique, autour des mots "
                           "qui traduisent ce passage ; n'en ajoute ni n'en retire aucune.")
        prompt = (
            f"Traduis le texte suivant {direction}.\n"
            f"Rends UNIQUEMENT la traduction, sans commentaire ni guillemets.{gloss_line}"
            f"{markup_line}\n\n"
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


# ── L'API ÉTROITE de la brique (2026-10-28) ──────────────────────────────────────────────────
# Ce qu'une app appelle — et ce que le rôle `codegen` voit quand le modèle requis est un
# spécialiste de la traduction (`run_codegen.BRICKS_BY_TRIGGER`). Deux fonctions à signature
# explicite (le rôle juge ses appels par elle), qui LÈVENT avec le motif : une traduction ratée
# fait échouer l'élément en le disant, jamais un texte rendu à moitié.

def glossary_terms(glossary) -> list:
    """Les termes d'un glossaire : une liste telle quelle, un TEXTE un terme par ligne (la forme
    du champ « Glossaire » d'une card). Sans cette lecture, un texte passé tel quel devenait une
    liste de CARACTÈRES à ne pas traduire."""
    if isinstance(glossary, str):
        return [line.strip() for line in glossary.splitlines() if line.strip()]
    return [str(term).strip() for term in glossary or [] if str(term).strip()]


def translate_text(text: str, source_language: str, target_language: str, *,
                   model: str = DEFAULT_MODEL, user=None, glossary=None, on_chunk=None,
                   timeout: int = 120) -> str:
    """La traduction de `text`. `model` : une clé de catalogue (vide = `DEFAULT_MODEL`) ;
    `source_language` « auto » ou vide : la langue d'origine se détecte ; `glossary` : les termes
    à garder tels quels (liste, ou texte un terme par ligne) ; `on_chunk(texte traduit jusqu'ici)`
    après chaque morceau."""
    result = TranslatorService(model=model or DEFAULT_MODEL, user=user).translate(
        text or '', source_language, target_language, glossary=glossary_terms(glossary),
        timeout=timeout, on_chunk=on_chunk)
    if not result.get('ok'):
        raise RuntimeError(f"Traduction impossible : {result.get('error') or 'réponse vide'}")
    return result['text']


def _keep_final_stop(source: str, translated: str) -> str:
    """La traduction sans le point final que la source n'avait pas : le modèle en ajoute à une
    étiquette de figure ou à un titre (« Moyenne spatiale. », mesuré le 2026-10-29). Une
    ponctuation finale de la source, des points de suspension, restent."""
    if _MARKUP.sub('', source).rstrip().endswith(('.', '…', ':', ';', '!', '?')):
        return translated
    match = re.search(r'(?<!\.)\.((?:\s*</t\d+>)*\s*)$', translated, re.IGNORECASE)
    return translated[:match.start()] + match.group(1) if match else translated


def _runaway(source: str, translated: str) -> bool:
    """Une « traduction » sans commune mesure avec un passage COURT : le modèle a commenté ou
    inventé au lieu de traduire (une étiquette de figure rendue en paragraphe). Le passage garde
    alors son texte d'origine — un mot non traduit vaut mieux qu'un pavé à sa place."""
    bare, out = _MARKUP.sub('', source).strip(), _MARKUP.sub('', translated).strip()
    return len(bare) <= 40 and len(out) > 3 * len(bare) + 20


def translate_document(path, out_path, source_language: str, target_language: str, *,
                       model: str = DEFAULT_MODEL, user=None, glossary=None, on_chunk=None,
                       progress_callback=None, timeout: int = 120) -> str:
    """Le document `path` TRADUIT dans `out_path`, sa forme d'origine conservée (même format :
    TXT, MD, DOCX, PDF à texte natif) — chaque bloc traduit et réécrit à sa place par la couche
    texte commune (`document_text`, unité `block`). Rend `out_path`.

    `on_chunk(texte traduit jusqu'ici)` : l'aperçu « pendant » ; `progress_callback(pourcent)`
    après chaque bloc. Un document sans texte (PDF scanné) LÈVE : c'est l'OCR qu'il lui faut.

    Chaque bloc part BALISÉ de sa mise en forme (`markup=True` : un mot en gras, en italique, en
    exposant garde la sienne dans la traduction) ; l'aperçu, lui, est le texte nu."""
    from wama.common.utils.document_text import read_segments, strip_markup, write_replacements
    service = TranslatorService(model=model or DEFAULT_MODEL, user=user)
    glossary = glossary_terms(glossary)
    segments = read_segments(path, unit='block', markup=True)
    # Moins de deux lettres (la lettre d'un axe, une variable, une unité d'un caractère) : rien à
    # traduire — envoyé seul au modèle, « R » revenait en paragraphe (mesuré le 2026-10-29).
    todo = [i for i, segment in enumerate(segments)
            if sum(c.isalpha() for c in strip_markup(segment)) >= 2]
    if not todo:
        raise ValueError("Rien à traduire : le document n'a pas de texte lisible (PDF scanné ?)")
    replacements, done = {}, []
    for count, index in enumerate(todo, 1):
        segment = segments[index]
        core = segment.strip()
        start = len(segment) - len(segment.lstrip())
        relay = (None if on_chunk is None
                 else lambda partial: on_chunk('\n\n'.join(done + [strip_markup(partial)])))
        result = service.translate(core, source_language, target_language, glossary=glossary,
                                   timeout=timeout, on_chunk=relay)
        if not result.get('ok'):
            raise RuntimeError(f"Traduction impossible : {result.get('error') or 'réponse vide'}")
        translated = _keep_final_stop(core, result['text'])
        if _runaway(core, translated):
            translated = core
        replacements[index] = [(start, start + len(core), translated)]
        done.append(strip_markup(translated))
        if on_chunk is not None:
            on_chunk('\n\n'.join(done))
        if progress_callback is not None:
            progress_callback(count * 100 // len(todo))
    return write_replacements(path, out_path, replacements, unit='block', markup=True)
