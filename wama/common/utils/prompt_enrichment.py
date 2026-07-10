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

**Skills (2026-07-08)** : les consignes (system prompt) viennent des SKILLS déclarés par app
([[prompt_skills]], fichiers `common/prompt_skills/<app>-<domain>.md`) — `_SYSTEM` ci-dessous
n'est plus que l'ultime fallback si aucun fichier n'existe. Deux règles restent DANS LE CODE
(mécanisme, pas skill) : la clause de langue d'émission et la préservation verbatim des
mots-clés forcés par l'utilisateur (`glossary`).

`enrich_on_demand()` : variante EXPLICITE (bouton ✨ des apps) — ne dépend PAS de
l'interrupteur maître `WAMA_PROMPT_ENRICH` (le clic EST la demande), mêmes skills, même cache.
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
                      timeout: int = 60, skill_name: str = None, skill_text: str = None,
                      max_input_chars: int = _MAX_INPUT_CHARS) -> str:
    """
    Étoffe un prompt génératif. Retourne l'enrichi, ou `prompt` inchangé si rien à faire / erreur.

    `language` : langue dans laquelle émettre l'enrichi (= langue du prompt après routing —
    pivot si traduit, sinon langue d'entrée). `glossary` : termes à préserver tels quels
    (mots-clés forcés par l'utilisateur). `skill_name`/`skill_text` : consignes du skill d'app
    ([[prompt_skills]]) — repli sur `_SYSTEM` générique si absents.
    """
    text = (prompt or '').strip()
    if not text or len(text) > max_input_chars:
        return prompt  # vide ou déjà détaillé → pas d'appel LLM

    if model is None:
        try:
            from django.conf import settings
            model = getattr(settings, 'WAMA_PROMPT_ENRICH_MODEL', None)
        except Exception:
            model = None

    gloss = list(glossary or [])
    ckey = _cache_key(text, language, gloss, f"{model or 'default'}|{skill_name or 'builtin'}")
    cached = _cache_get(ckey)
    if cached is not None:
        if console:
            console(f"✨ Prompt enrichi ({len(text)}→{len(cached)} caractères, depuis le cache).")
        return cached

    lang_clause = f" in {language}" if language and language != 'en' else ""
    if skill_text:
        # Skill d'app = system prompt ; la clause de langue est une règle du MÉCANISME (ajoutée ici).
        system = skill_text + (f"\n- Emit the enriched prompt{lang_clause}." if lang_clause else "")
    else:
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


def enrich_on_demand(prompt: str, *, app: str = None, domain: str = None,
                     language: str = 'en', model: str = None, glossary=None,
                     timeout: int = 60) -> str:
    """
    Enrichissement EXPLICITE (bouton ✨) : le clic vaut demande → pas d'interrupteur maître.
    Résout le skill de l'app ([[prompt_skills]]) puis passe par le même chemin (cache compris).
    Plafond d'entrée relevé (l'utilisateur peut vouloir étoffer un prompt déjà long).
    Lève RuntimeError si l'enrichissement n'a rien produit (l'appelant informe l'utilisateur).
    """
    from .prompt_skills import resolve_skill
    name, text = resolve_skill(app=app, domain=domain, kind='generative')
    enriched = enrich_generative(prompt, language=language, model=model, glossary=glossary,
                                 timeout=timeout, skill_name=name, skill_text=text,
                                 max_input_chars=2000)
    if not enriched or enriched == (prompt or '').strip() or enriched == prompt:
        raise RuntimeError("Enrichissement indisponible (LLM local injoignable ou réponse vide)")
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
