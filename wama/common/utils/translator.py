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
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

_CHUNK_CHARS = 4000  # ~ sous la fenêtre de traduction effective de translategemma (~2K tokens)


class TranslatorService:
    def __init__(self, model: str = 'translategemma:12b', glossary=None, use_cache: bool = True):
        self.model = model
        self.glossary = list(glossary or [])
        self.use_cache = use_cache

    # ── public ───────────────────────────────────────────────────────────────
    def translate(self, text: str, source_lang: str, target_lang: str, glossary=None,
                  timeout: int = 120):
        """Traduit `text` de source_lang → target_lang. Retourne {'ok', 'text'|'error', 'cached'}."""
        text = text or ''
        if not text.strip() or not target_lang or source_lang == target_lang:
            return {'ok': True, 'text': text, 'cached': False}  # passthrough

        gloss = list(self.glossary) + list(glossary or [])
        ckey = self._cache_key(text, source_lang, target_lang, gloss)
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
        from wama.common.utils.llm_utils import llm_chat
        gloss_line = ""
        if glossary:
            gloss_line = ("\nNe traduis PAS ces termes (garde-les tels quels) : "
                          + ", ".join(glossary) + ".")
        prompt = (
            f"Traduis le texte suivant de « {source_lang} » vers « {target_lang} ».\n"
            f"Rends UNIQUEMENT la traduction, sans commentaire ni guillemets.{gloss_line}\n\n"
            f"{text}"
        )
        out, err = llm_chat(messages=[{"role": "user", "content": prompt}],
                            provider='ollama', model=self.model,
                            num_predict=1500, think=False, timeout=timeout)
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
    def _cache_key(text, src, tgt, glossary):
        h = hashlib.sha256(f"{src}|{tgt}|{','.join(sorted(glossary))}|{text}".encode('utf-8')).hexdigest()
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
