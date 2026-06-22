"""
PromptPipeline commune (ROADMAP §16.6) — UN point d'entrée pour tout prompt utilisateur de WAMA.

Au lieu d'une fonction de traduction dédiée par app (glu), chaque app appelle
`process_prompt(prompt, kind=..., model_capabilities=..., ...)` et la pipeline applique la chaîne :
  détection langue → routing+traduction si besoin → [enrichissement selon KIND] → [RAG] → [fichiers réf.].

Le **KIND** déclare la nature du prompt (l'enrichissement diffère) :
- 'generative' : prompt de génération (SDXL/Flux/Qwen-image…) → traduire selon les capacités du modèle.
- 'concept'    : concept(s) pour un modèle text-promptable EN (SAM3) → forcer l'anglais.
- 'intent'     : intention pour un LLM (assistant) → généralement direct (LLM multilingue).
- 'text'       : texte générique.

v0 = détection langue + routing ([[lang_routing]]) + traduction ([[translator]]). Les hooks
enrichissement / RAG / compréhension de fichiers de référence sont prévus (no-op pour l'instant).
Fail-safe : toute erreur → prompt original (aucune régression).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PROMPT_KINDS = ('generative', 'concept', 'intent', 'text')


def _user_lang(user):
    return getattr(getattr(user, 'profile', None), 'preferred_language', None) or 'en'


def process_prompt(prompt, *, kind='generative', model_capabilities=None, model_type=None,
                   user=None, input_lang=None, glossary=None, console=None, timeout=120):
    """
    Traite un prompt selon les métadonnées (KIND + capacités du modèle cible).

    Retourne {'prompt': traité, 'original': prompt, 'translated': bool, 'routing': dict|None,
              'reason': str}. `console` : callback(msg) optionnel pour l'avis (transparence).
    """
    result = {'prompt': prompt, 'original': prompt, 'translated': False,
              'routing': None, 'reason': 'direct'}
    if not prompt or not str(prompt).strip():
        return result

    try:
        from .lang_routing import routing_for_model, resolve_language_routing
        from .translator import TranslatorService

        lang = input_lang or _user_lang(user)
        # 'concept' : le modèle attend des concepts en ANGLAIS (SAM3) → forcer EN-only.
        if kind == 'concept':
            routing = resolve_language_routing(['en'], input_lang=lang,
                                               has_text_input=True, has_text_output=False)
        else:
            routing = routing_for_model(model_capabilities, model_type, input_lang=lang,
                                        has_text_input=True, has_text_output=False)
        result['routing'] = routing
        result['reason'] = routing.get('reason', 'direct')

        if routing.get('input_translate'):
            tr = TranslatorService().translate_input(routing, prompt, lang,
                                                     glossary=glossary, timeout=timeout)
            if tr.get('ok') and tr.get('text'):
                result['prompt'] = tr['text']
                result['translated'] = True
                if console:
                    console(f"[prompt:{kind}] traduit {lang}→{routing['input_pivot']}")

        # ── Hooks futurs (§16.6), pilotés par KIND/metadata — no-op pour l'instant ──
        # if kind == 'generative':  result['prompt'] = enrich_generative(result['prompt'], ...)
        # result['prompt'] = apply_rag(result['prompt'], user, ...)
        # result['prompt'] = comprehend_reference_files(result['prompt'], ...)
    except Exception as e:
        result['reason'] = f"pipeline ignorée ({e})"
        logger.debug(f"[prompt_pipeline] {e}")

    return result
