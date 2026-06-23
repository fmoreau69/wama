"""
Enrichissement de prompt génératif (ROADMAP §16.6, hook « A » de la PromptPipeline).

« Upsampling » : un prompt court (« un chat ») est étoffé en un prompt riche et détaillé
(sujet PRÉSERVÉ + détails visuels / lumière / composition / style) pour de meilleures images.

Garde-fous RESSOURCES (préoccupation récurrente de l'utilisateur — pas de cascade) :
- **OFF par défaut** : ne fait quoi que ce soit que si `settings.WAMA_PROMPT_ENRICH` est vrai
  (interrupteur maître global) ET si le champ est marqué `enrich=True` en métadonnée.
- **Une seule passe LLM locale légère** (`llm_chat`, modèle « fast »), `think=False`, `num_ctx`
  plafonné → empreinte VRAM contenue.
- **Garde de longueur** : un prompt déjà détaillé (> seuil) n'est PAS ré-enrichi (zéro appel).
- **Cache** (Django cache) : un prompt identique n'est enrichi qu'une fois.
- **Fail-safe** : toute erreur / réponse vide → prompt d'origine (aucune régression).

S'applique UNIQUEMENT au KIND 'generative' (cf. prompt_pipeline). On n'enrichit jamais un
concept de segmentation (SAM3) ni une intention d'assistant : ce serait du bruit / hallucination.
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

# Au-delà de ce seuil, le prompt est jugé déjà détaillé → pas d'enrichissement (économie).
_MAX_INPUT_CHARS = 320
# Plafond de génération (l'enrichi reste un paragraphe) + fenêtre KV plafonnée (VRAM).
_NUM_PREDICT = 400
_NUM_CTX = 8192

_SYSTEM = (
    "You are an expert prompt engineer for text-to-image generation. "
    "Expand the user's short prompt into a single rich, detailed image-generation prompt. "
    "Add concrete visual detail: subject specifics, setting, lighting, composition, style, mood, "
    "and quality terms.\n"
    "Rules:\n"
    "- PRESERVE the user's core subject and intent exactly. Never introduce a different subject.\n"
    "- Keep it to ONE concise paragraph: no lists, no line breaks, no headings.\n"
    "- Output ONLY the enriched prompt{lang_clause}, with no preamble, no quotes, no explanation."
)


def enrichment_enabled() -> bool:
    """Interrupteur maître global (OFF par défaut → coût ressources nul tant que non activé)."""
    try:
        from django.conf import settings
        return bool(getattr(settings, 'WAMA_PROMPT_ENRICH', False))
    except Exception:
        return False


def enrich_generative(prompt: str, *, language: str = 'en', model: str = None,
                      provider: str = 'ollama', glossary=None, console=None,
                      timeout: int = 60) -> str:
    """
    Étoffe un prompt génératif. Retourne l'enrichi, ou `prompt` inchangé si rien à faire / erreur.

    `language` : langue dans laquelle émettre l'enrichi (= langue du prompt après routing —
    pivot si traduit, sinon langue d'entrée). `glossary` : termes à préserver tels quels.
    """
    text = (prompt or '').strip()
    if not text or len(text) > _MAX_INPUT_CHARS:
        return prompt  # vide ou déjà détaillé → pas d'appel LLM

    if model is None:
        try:
            from django.conf import settings
            model = getattr(settings, 'WAMA_PROMPT_ENRICH_MODEL', None)
        except Exception:
            model = None

    gloss = list(glossary or [])
    ckey = _cache_key(text, language, gloss, model or 'default')
    cached = _cache_get(ckey)
    if cached is not None:
        if console:
            console(f"✨ Prompt enrichi ({len(text)}→{len(cached)} caractères, depuis le cache).")
        return cached

    lang_clause = f" in {language}" if language and language != 'en' else ""
    system = _SYSTEM.format(lang_clause=lang_clause)
    user = text
    if gloss:
        user += ("\n\n(Keep these terms verbatim, do not alter: " + ", ".join(gloss) + ".)")

    try:
        from wama.common.utils.llm_utils import llm_chat
        out, err = llm_chat(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            provider=provider, model=model,
            num_predict=_NUM_PREDICT, num_ctx=_NUM_CTX, think=False, timeout=timeout,
        )
    except Exception as e:
        logger.debug(f"[prompt_enrichment] {e}")
        return prompt

    if err or not out:
        return prompt
    enriched = _clean(out)
    # Garde-fou anti-dégénérescence : l'enrichi doit ajouter du détail, pas raccourcir/effondrer.
    if not enriched or len(enriched) < len(text):
        return prompt
    _cache_set(ckey, enriched)
    if console:
        console(f"✨ Prompt enrichi ({len(text)}→{len(enriched)} caractères) pour une meilleure génération.")
    return enriched


# ── interne ────────────────────────────────────────────────────────────────────
def _clean(text: str) -> str:
    """Retire les <think>…</think>, guillemets enveloppants et espaces parasites."""
    import re
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    if len(text) >= 2 and text[0] in '"“«' and text[-1] in '"”»':
        text = text[1:-1].strip()
    return text


def _cache_key(text, language, glossary, model):
    h = hashlib.sha256(
        f"{language}|{model}|{','.join(sorted(glossary))}|{text}".encode('utf-8')
    ).hexdigest()
    return f"wama:enrich:{h}"


def _cache_get(key):
    try:
        from django.core.cache import cache
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key, value, ttl=604800):  # 7 j
    try:
        from django.core.cache import cache
        cache.set(key, value, ttl)
    except Exception:
        pass
