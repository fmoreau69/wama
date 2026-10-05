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


def _rappel_rag(prompt, user, *, k=3, semantic=False):
    """
    Rend `(extraits, sources)` tirés des fragments RAG visibles par `user`. Best-effort ABSOLU.

    Rend `([], [])` sur la moindre difficulté : un contexte manquant dégrade la réponse, une
    exception ici casserait la génération elle-même. Même précaution que le reste de la pipeline.

    ⚠ `semantic=False` PAR DÉFAUT — motif RÉVISÉ le 2026-08-21, après le réindex.

    L'ancienne justification invoquait deux raisons, dont l'une est devenue FAUSSE : « les 939
    fragments n'ont pas encore de vecteur ». Ils en ont désormais **939/939**. La laisser en place
    aurait fait lire au suivant une raison caduque et en tirer une mauvaise conclusion — c'est
    exactement la dérive que ce projet combat, et elle a été signalée par l'instance assistant.

    Le motif qui SUBSISTE est le seul vrai : la latence, **là où elle se voit**. Un rappel
    sémantique embarque la requête, donc charge `bge-m3`. Ici, ce coût s'ajouterait à **chaque
    génération**, en plein chemin navigateur — mesuré ~5 s sans résidence, ~300 ms avec. C'est
    l'inverse de `tool_api.memory_recall`, passé en hybride le même jour : là-bas l'outil n'est
    appelé que si le LLM le décide et un tour LLM suit, donc l'attente s'y noie.

    À rebasculer si un jour ce hook sert un chemin non interactif (traitement par lot, tâche de
    fond), pas « quand ce sera prêt » : c'est prêt.
    """
    try:
        from ..memory import recall

        hits = recall(prompt, user=user, include_memory=False, semantic=semantic, k=k)
    except Exception:
        logger.debug('[prompt_pipeline] rappel RAG indisponible', exc_info=True)
        return [], []

    extraits, sources = [], []
    for h in hits:
        obj = h.obj
        # La source est CITÉE avec l'extrait : un contexte injecté sans provenance est
        # invérifiable par l'utilisateur, et c'est exactement ce qu'on reproche aux RAG opaques.
        sources.append(getattr(obj, 'source_id', '') or '')
        extraits.append(f"[{getattr(obj, 'source_id', '?')}] {obj.content}")
    return extraits, sources


#: Ce que dit au modèle le bloc replié, selon la LECTURE de la référence : un contexte de
#: contenu se reprend, une mise en page se reproduit sans que son texte soit repris.
_REFERENCE_BLOCKS = {
    'content': '[Reference context]',
    'form': ('[Layout reference — reproduce this LAYOUT and visual STYLE; '
             'never reuse its text]'),
}


def _fold_references(result, reference_files, reading, language, console, timeout):
    """Comprend les fichiers de référence et replie le bloc dans `result['prompt']` (en place)."""
    from .reference_comprehension import comprehend_files
    ctx = comprehend_files(reference_files, language=language or 'en', console=console,
                           timeout=timeout, reading=reading)
    if ctx:
        head = _REFERENCE_BLOCKS.get(reading, _REFERENCE_BLOCKS['content'])
        base = str(result['prompt'] or '').strip()
        result['prompt'] = f"{base}\n\n{head}\n{ctx}" if base else f"{head}\n{ctx}"
        result['reference_context'] = True


def process_prompt(prompt, *, kind='generative', model_capabilities=None, model_type=None,
                   user=None, input_lang=None, glossary=None, enrich=False,
                   reference_files=None, console=None, timeout=120,
                   app=None, domain=None, rag=False, rag_k=3, rag_semantic=False,
                   prompt_contract=None, reference_reading='content'):
    """
    Traite un prompt selon les métadonnées (KIND + capacités du modèle cible).

    `enrich` : si True ET kind='generative', tente l'enrichissement (« upsampling »). Reste
    sans effet tant que `settings.WAMA_PROMPT_ENRICH` est faux (interrupteur maître, OFF par
    défaut → coût ressources nul) — cf. [[prompt_enrichment]].

    `app`/`domain` : sélection du SKILL de consignes d'enrichissement ([[prompt_skills]],
    résolution `<app>-<domain>` → `<app>` → défaut). `domain` replie sur `model_type`.

    `prompt_contract` : contrat de SORTIE déclaré par le modèle CIBLE (`AIModel.prompt_contract`,
    porté par son manifeste — doctrine 2026-08-26 : le skill d'app = la méthode, le modèle = son
    contrat). Ajouté au system prompt d'enrichissement, il PRIME sur les règles de longueur/format
    du skill. Data-gated : None (aucun modèle ne déclare) = comportement d'avant, à l'octet.

    `reference_files` : chemin(s) de fichier(s) de référence fournis par l'utilisateur. S'ils
    existent, ils sont compris (image/doc/texte) et repliés dans le prompt comme contexte de
    grounding (cf. [[reference_comprehension]]). Data-gated : aucun coût si la liste est vide.
    `reference_reading` : `content` (ce que la référence dit) ou `form` (comment elle est faite —
    la référence de MISE EN PAGE, 2026-10-01), déclaré par la cible (`PROMPT_TARGETS`). Une
    consigne VIDE accompagnée d'une référence est traitée quand même : « fais comme ce document »
    se dit aussi sans un mot.

    `rag` : si True ET `user` fourni, ajoute au prompt des extraits des documents de
    l'utilisateur (fragments `RagChunk` visibles par lui — cf. `WAMA_MEMORY.md`). OPT-IN et
    data-gated : sans rappel, le prompt sort inchangé. `rag_semantic=False` par défaut — voir
    `_rappel_rag` pour le pourquoi (coût GPU sur le chemin interactif + vecteurs pas encore
    calculés).

    Retourne {'prompt': traité, 'original': prompt, 'translated': bool, 'enriched': bool,
              'reference_context': bool, 'rag': bool, 'rag_sources': list,
              'routing': dict|None, 'reason': str}.
    `console` : callback(msg) optionnel (transparence).
    """
    result = {'prompt': prompt, 'original': prompt, 'translated': False, 'enriched': False,
              'reference_context': False, 'rag': False, 'rag_sources': [],
              'routing': None, 'reason': 'direct'}
    if not prompt or not str(prompt).strip():
        # Rien à traduire ni à enrichir — mais une référence jointe se lit quand même.
        if reference_files and kind in ('generative', 'intent'):
            _fold_references(result, reference_files, reference_reading,
                             input_lang or _user_lang(user), console, timeout)
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
            # `user` transmis : la préférence utilisateur pilote (le réglage plateforme n'est
            # plus qu'un kill switch). Sans utilisateur résolu, seul le kill switch décide.
            if enrichment_enabled(user):
                from .prompt_skills import resolve_skill
                sk_name, sk_text = resolve_skill(app=app, domain=domain or model_type, kind=kind)
                enr_lang = routing.get('input_pivot') if result['translated'] else lang
                enriched = enrich_generative(result['prompt'], language=enr_lang or 'en',
                                             glossary=glossary, console=console, timeout=timeout,
                                             skill_name=sk_name, skill_text=sk_text,
                                             contract=prompt_contract)
                if enriched and enriched != result['prompt']:
                    result['prompt'] = enriched
                    result['enriched'] = True

        # ── Hook A bis : ADAPTATION « concept » — la phrase devient des CONCEPTS ──
        # ⚠⚠ CE HOOK MANQUAIT, et c'est ce qui rendait l'anonymisation SAM3 vide (mesuré le
        # 2026-09-23). Le skill `anonymizer-detection.md` existait depuis des semaines, il était
        # RÉSOLU par `resolve_skill`… et jamais appliqué : Hook A ci-dessus est gardé par
        # `kind == 'generative'`, donc un target `concept` ne pouvait PAS l'atteindre, même en
        # déclarant `enrich: True`. Le prompt partait donc tel quel au modèle de segmentation —
        # « Detect faces and license plates. » → 0 masque, aucune erreur, image inchangée.
        #
        # DEUX différences assumées avec l'enrichissement génératif :
        #   • `allow_shorter=True` : adapter un concept, c'est RACCOURCIR (voir `enrich_generative`) ;
        #   • PAS d'interrupteur maître `WAMA_PROMPT_ENRICH`. L'enrichissement génératif est un
        #     confort qu'on peut couper ; l'adaptation en concepts est ce SANS QUOI le modèle ne
        #     trouve rien. La couper rendrait la détection muette au lieu d'économiser.
        # Sans skill résolu, on ne fait RIEN (jamais le system prompt génératif sur un concept).
        if kind == 'concept' and enrich:
            from .prompt_enrichment import enrich_generative
            from .prompt_skills import resolve_skill
            sk_name, sk_text = resolve_skill(app=app, domain=domain or model_type, kind=kind)
            if sk_text:
                # `console` n'est PAS transmis : le message générique d'`enrich_generative`
                # dit « prompt enrichi … pour une meilleure génération », ce qui décrit
                # l'inverse de ce qui se passe ici (on réduit, et il s'agit de détection).
                adapted = enrich_generative(result['prompt'], language='en', glossary=glossary,
                                            timeout=timeout,
                                            skill_name=sk_name, skill_text=sk_text,
                                            allow_shorter=True)
                if adapted and adapted != result['prompt']:
                    if console:
                        console(f"🎯 Concepts de détection : « {adapted} » "
                                f"(le modèle n'ancre qu'un groupe nominal par concept).")
                    result['prompt'] = adapted
                    result['enriched'] = True

        # ── Hook : compréhension des fichiers de référence (§10.B) ──
        # Data-gated : ne fait rien si aucun fichier fourni (no-op tant qu'aucune app ne déclare
        # `reference_field` dans PROMPT_TARGETS). Replie un contexte de grounding dans le prompt.
        if reference_files and kind in ('generative', 'intent'):
            ref_lang = (routing.get('input_pivot') if result['translated'] else lang) or 'en'
            _fold_references(result, reference_files, reference_reading, ref_lang, console, timeout)

        # ── Hook B : RAG — contexte tiré de ce que l'utilisateur POSSÈDE (WAMA_MEMORY.md) ──
        # OPT-IN (`rag=True`) et data-gated : sans rappel, le prompt sort INCHANGÉ. Aucune app ne
        # l'active à ce jour — le brancher ne change donc rien tant qu'un appelant ne le demande.
        #
        # ⚠ Le commentaire précédent annonçait ChromaDB : PÉRIMÉ. Le substrat est Postgres +
        # pgvector (`common/memory/`), décidé le 2026-08-20 — cf. WAMA_MEMORY.md §7.
        if rag and user is not None and kind in ('generative', 'intent'):
            extraits, sources = _rappel_rag(result['prompt'], user, k=rag_k,
                                            semantic=rag_semantic)
            if extraits:
                result['prompt'] = (f"{result['prompt']}\n\n[Contexte — vos documents]\n"
                                    + "\n\n".join(extraits))
                result['rag'] = True
                result['rag_sources'] = sources
                if console:
                    console(f"📚 {len(extraits)} extrait(s) de vos documents ajouté(s) au contexte.")
    except Exception as e:
        result['reason'] = f"pipeline ignorée ({e})"
        logger.debug(f"[prompt_pipeline] {e}")

    return result
