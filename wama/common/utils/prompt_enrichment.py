"""
Enrichissement de prompt génératif (ROADMAP §16.6, hook « A » de la PromptPipeline).

« Upsampling » : un prompt court (« un chat ») est étoffé en un prompt riche et détaillé
(sujet PRÉSERVÉ + détails visuels / lumière / composition / style) pour de meilleures images.

Garde-fous RESSOURCES (préoccupation récurrente de l'utilisateur — pas de cascade) :
- **OFF par défaut** : ne fait quoi que ce soit que si `settings.WAMA_PROMPT_ENRICH` est vrai
  (interrupteur maître global) ET si le champ est marqué `enrich=True` en métadonnée.
- **Une seule passe LLM locale** (`llm_chat`, défaut `qwen3.5:9b`), `think=False`, `num_ctx`
  plafonné, `keep_alive=0` → empreinte VRAM contenue ET non résidente.
  Le 9b est un choix MESURÉ (bench 2026-07-29, 4 prompts × 2 modèles + 3 tirages de contrôle) :
  `qwen3.5:4b` est ~0,4 s plus rapide et 3,2 Go plus léger mais viole la clause de langue
  d'émission 3/3 sur prompt court (répond en anglais) et dérive le sujet
  (« navette autonome » → « voiture autonome »), soit les 2 règles centrales. Ne pas basculer.
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
# Résidence VRAM par défaut = NULLE : sur le chemin critique (pipeline au lancement de tâche),
# l'enrichissement PRÉCÈDE immédiatement un gros chargement GPU (diffusion) ; sans ça Ollama
# garde les poids 5 min par défaut → ~6,6 Go squattés PENDANT la génération.
_KEEP_ALIVE = '0'
# À l'INGESTION en revanche, rien ne charge le GPU juste après et les prompts arrivent en série
# (batch) : décharger entre chaque ferait repayer ~12 s de chargement par item. Résidence courte.
KEEP_ALIVE_INGEST = '60s'

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


def enrichment_enabled(user=None) -> bool:
    """
    L'enrichissement automatique est-il actif pour cet utilisateur ?

    Deux étages, dans cet ordre :
    1. `settings.WAMA_PROMPT_ENRICH` = **kill switch plateforme** (env `=0` → OFF pour tout le
       monde, quoi que disent les profils). Sert aux incidents ressources / au debug.
    2. `user.profile.prompt_enrich` = **préférence utilisateur** (défaut True). C'est le vrai
       interrupteur : l'utilisateur n'a pas à connaître la chaîne derrière son prompt, mais il
       peut la couper.

    `user=None` (tâche sans utilisateur résolu, appel hors requête) → le kill switch seul décide.
    """
    try:
        from django.conf import settings
        if not bool(getattr(settings, 'WAMA_PROMPT_ENRICH', True)):
            return False
    except Exception:
        return False

    if user is None:
        return True
    pref = getattr(getattr(user, 'profile', None), 'prompt_enrich', None)
    return True if pref is None else bool(pref)


def build_system(skill_text: str = None, *, language: str = 'en', contract: str = None) -> str:
    """
    System prompt d'enrichissement : skill d'app (ou `_SYSTEM` générique) + clause de langue
    (règle du MÉCANISME, jamais dans les fichiers de skill) + contrat de sortie du modèle cible.

    Factorisé hors de `enrich_generative` pour être PROUVABLE sans appel LLM (l'assemblage est
    la seule logique ; le reste est du transport). Le contrat PRIME sur le skill : MusicGen veut
    30-80 mots là où MiniMax-Music3 veut 250-450 sectionnés — même app, contrats opposés.
    """
    lang_clause = f" in {language}" if language and language != 'en' else ""
    if skill_text:
        system = skill_text + (f"\n- Emit the enriched prompt{lang_clause}." if lang_clause else "")
    else:
        system = _SYSTEM.format(lang_clause=lang_clause)
    if contract:
        system += ("\n\nOutput contract of the TARGET model — it OVERRIDES any conflicting "
                   "length, structure or format rule above:\n" + contract.strip())
    return system


def enrich_generative(prompt: str, *, language: str = 'en', model: str = None,
                      provider: str = 'ollama', glossary=None, console=None,
                      timeout: int = 60, skill_name: str = None, skill_text: str = None,
                      max_input_chars: int = _MAX_INPUT_CHARS,
                      keep_alive: str = _KEEP_ALIVE, contract: str = None) -> str:
    """
    Étoffe un prompt génératif. Retourne l'enrichi, ou `prompt` inchangé si rien à faire / erreur.

    `language` : langue dans laquelle émettre l'enrichi (= langue du prompt après routing —
    pivot si traduit, sinon langue d'entrée). `glossary` : termes à préserver tels quels
    (mots-clés forcés par l'utilisateur). `skill_name`/`skill_text` : consignes du skill d'app
    ([[prompt_skills]]) — repli sur `_SYSTEM` générique si absents.
    `contract` : contrat de SORTIE du modèle CIBLE (`AIModel.prompt_contract`, déclaré par son
    manifeste) — ajouté au system prompt, il PRIME sur les règles de longueur/format du skill
    (doctrine 2026-08-26 : skill d'app = la méthode, modèle = son contrat).
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
    # Le contrat entre dans la clé : deux modèles cibles aux contrats différents ne doivent
    # jamais se servir mutuellement leur enrichi en cache (la clé est hachée, la longueur importe peu).
    ckey = _cache_key(text, language, gloss,
                      f"{model or 'default'}|{skill_name or 'builtin'}|{contract or ''}")
    cached = _cache_get(ckey)
    if cached is not None:
        if console:
            console(f"✨ Prompt enrichi ({len(text)}→{len(cached)} caractères, depuis le cache).")
        return cached

    system = build_system(skill_text, language=language, contract=contract)
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
            keep_alive=keep_alive,
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
                     timeout: int = 60, keep_alive: str = _KEEP_ALIVE,
                     contract: str = None) -> str:
    """
    Enrichissement EXPLICITE (bouton ✨) : le clic vaut demande → pas d'interrupteur maître.
    Résout le skill de l'app ([[prompt_skills]]) puis passe par le même chemin (cache compris).
    Plafond d'entrée relevé (l'utilisateur peut vouloir étoffer un prompt déjà long).
    Lève RuntimeError si l'enrichissement n'a rien produit (l'appelant informe l'utilisateur).
    `contract` : contrat de sortie du modèle cible si la vue le connaît (cf. `enrich_generative`).
    """
    from .prompt_skills import resolve_skill
    name, text = resolve_skill(app=app, domain=domain, kind='generative')
    enriched = enrich_generative(prompt, language=language, model=model, glossary=glossary,
                                 timeout=timeout, skill_name=name, skill_text=text,
                                 max_input_chars=2000, keep_alive=keep_alive,
                                 contract=contract)
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
