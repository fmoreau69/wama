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
                   user=None, input_lang=None, glossary=None, enrich=False,
                   reference_files=None, console=None, timeout=120):
    """
    Traite un prompt selon les métadonnées (KIND + capacités du modèle cible).

    `enrich` : si True ET kind='generative', tente l'enrichissement (« upsampling »). Reste
    sans effet tant que `settings.WAMA_PROMPT_ENRICH` est faux (interrupteur maître, OFF par
    défaut → coût ressources nul) — cf. [[prompt_enrichment]].

    `reference_files` : chemin(s) de fichier(s) de référence fournis par l'utilisateur. S'ils
    existent, ils sont compris (image/doc/texte) et repliés dans le prompt comme contexte de
    grounding (cf. [[reference_comprehension]]). Data-gated : aucun coût si la liste est vide.

    Retourne {'prompt': traité, 'original': prompt, 'translated': bool, 'enriched': bool,
              'reference_context': bool, 'routing': dict|None, 'reason': str}.
    `console` : callback(msg) optionnel (transparence).
    """
    result = {'prompt': prompt, 'original': prompt, 'translated': False, 'enriched': False,
              'reference_context': False, 'routing': None, 'reason': 'direct'}
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
                    pivot = routing['input_pivot']
                    why = ("ce modèle attend des concepts en anglais" if kind == 'concept'
                           else f"ce modèle ne gère pas « {lang} »")
                    console(f"🌐 Prompt traduit {lang}→{pivot} ({why}) — "
                            f"la génération utilise la version traduite.")

        # ── Hook A : enrichissement génératif (§16.6), piloté par KIND + flag metadata ──
        # OFF par défaut (interrupteur maître `WAMA_PROMPT_ENRICH`) → aucun coût ressources
        # tant que non activé. Enrichi dans la langue du prompt APRÈS routing (pivot si traduit,
        # sinon langue d'entrée que le modèle gère).
        if kind == 'generative' and enrich:
            from .prompt_enrichment import enrich_generative, enrichment_enabled
            if enrichment_enabled():
                enr_lang = routing.get('input_pivot') if result['translated'] else lang
                enriched = enrich_generative(result['prompt'], language=enr_lang or 'en',
                                             glossary=glossary, console=console, timeout=timeout)
                if enriched and enriched != result['prompt']:
                    result['prompt'] = enriched
                    result['enriched'] = True

        # ── Hook : compréhension des fichiers de référence (§10.B) ──
        # Data-gated : ne fait rien si aucun fichier fourni (no-op tant qu'aucune app ne déclare
        # `reference_field` dans PROMPT_TARGETS). Replie un contexte de grounding dans le prompt.
        if reference_files and kind in ('generative', 'intent'):
            from .reference_comprehension import comprehend_files
            ref_lang = (routing.get('input_pivot') if result['translated'] else lang) or 'en'
            ctx = comprehend_files(reference_files, language=ref_lang, console=console, timeout=timeout)
            if ctx:
                result['prompt'] = f"{result['prompt']}\n\n[Reference context]\n{ctx}"
                result['reference_context'] = True

        # ── Hook futur (§16.6 / §8c) : RAG — récupération de contexte depuis le store ChromaDB
        # (embeddings bge-m3). No-op tant que la fondation wama/rag/ + l'indexation n'existent pas.
        # result['prompt'] = apply_rag(result['prompt'], user, ...)
    except Exception as e:
        result['reason'] = f"pipeline ignorée ({e})"
        logger.debug(f"[prompt_pipeline] {e}")

    return result
