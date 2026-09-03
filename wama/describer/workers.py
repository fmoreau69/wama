"""
WAMA Describer — Celery Workers

Tâche principale : describe_content (nom de module HISTORIQUE `workers.py` conservé —
le nom de tâche Celery `wama.describer.workers.describe_content` est un jumeau par
CHAÎNE : routes, revokes et messages en vol le portent).

Squelette (gardes, progress, chrono, statuts, ETA, console, notifications) = brique
COMMUNE `common/utils/task_skeleton.run_item_task` (marche A2, route §10.3 — portage
2026-09-03). Ce fichier ne porte plus que la GLU du describer : détection/normalisation
de la nature d'entrée, routage nature → backend (contrat commun « texte », déclaré dans
`backends/__init__.ROUTES`), puis enrichissements OPTIONNELS demandés par l'utilisateur
(résumé LLM, vérification de cohérence).
"""

import logging

from celery import shared_task

from .models import Description

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def describe_content(self, description_id: int):
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(self, app_id='describer', model=Description, item_id=description_id,
                  process=_describe, ingest_derive=_derive_detected_type,
                  notify_label='Describer')


def _derive_detected_type(inst, path, fname):
    """Hook `derive` de l'ingest URL (WAMA_INGEST) : renseigne detected_type au téléchargement."""
    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
    from .views import detect_type_from_extension
    inst.detected_type = detect_type_from_extension(ext)
    return ['detected_type']


def _describe(item, ctx):
    """GLU describer (contrat task_skeleton) : nature normalisée, options effectives lues
    des COLONNES (modèle événementiel §23.2quater), backend au contrat commun « texte »,
    enrichissements optionnels. Une exception = FAILURE (le squelette gère statut/console/
    notification)."""
    from importlib import import_module

    from wama.common.utils.param_schema import effective_settings
    from wama.common.utils.preview_utils import publish_partial_text
    from .backends import NATURE_FIELD, ROUTES
    from .params import PARAMS_JSON

    ctx.progress(5)

    input_path = item.input_file.path

    # Nature d'entrée — valeurs HISTORIQUES ('text'/'pdf' en base d'avant le 2026-08-30)
    # normalisées À LA LECTURE, jamais par migration (elles sont gitignorées).
    from .utils.content_analyzer import normalize_detected_type
    nature = normalize_detected_type(getattr(item, NATURE_FIELD, '') or item.content_type)
    if nature == 'auto':
        from .utils.content_analyzer import detect_content_type
        nature = detect_content_type(input_path)
        item.detected_type = nature
        item.save(update_fields=['detected_type'])

    ctx.console(f"Content type: {nature}")
    ctx.progress(10)

    chemin = ROUTES.get(nature)
    if not chemin:
        raise ValueError(f"Type de contenu non supporté : {nature}")

    # Valeurs EFFECTIVES : défauts du schéma ← colonnes POSÉES (la tâche lit les colonnes).
    posees = {p['name']: getattr(item, p['name'])
              for p in PARAMS_JSON if hasattr(item, p.get('name', ''))}
    opts = effective_settings(PARAMS_JSON, posees=posees)

    # Backend au contrat commun « texte » — résolution par la nature, import RELATIF AU
    # PAQUET (même geste que le corps composé de la jumelle : backends/ se copie tel quel).
    mod, fonc = chemin.rsplit('.', 1)
    backend = getattr(import_module('.' + mod, __package__), fonc)

    result = backend(
        input_path,
        options=opts,
        progress_callback=ctx.progress,
        partial_callback=lambda t: publish_partial_text('describer', item.id, t),
        console=ctx.console,
    )

    ctx.progress(90)
    ctx.console("Sauvegarde du résultat…")
    fields = {'result_text': result}

    # ── Enrichissements OPTIONNELS (toggles utilisateur — usages Ollama DEMANDÉS, hors
    # garde WAMA_GPU_SAFE_MODE qui ne couvre que la cascade vision AUTOMATIQUE) ──────────
    output_style = opts.get('output_style') or 'detailed'
    output_language = opts.get('output_language') or 'fr'

    # Résumé LLM (skip si format compte-rendu — il EST déjà le résumé)
    if opts.get('generate_summary') and result and output_style != 'meeting':
        try:
            ctx.console("Génération du résumé LLM (Ollama)…")
            from wama.common.utils.llm_utils import generate_structured_summary, get_describer_model
            _sum_model = get_describer_model(nature, output_style)
            ctx.console(f"Modèle résumé : {_sum_model}")
            summary_data = generate_structured_summary(
                result,
                content_hint=nature,
                language=output_language,
                model=_sum_model,
            )
            fields['summary'] = summary_data['summary']
            ctx.console("Résumé LLM généré ✓")
        except Exception as llm_err:
            ctx.console(f"Avertissement: résumé LLM échoué ({llm_err})")

    # Vérification de cohérence (toujours le modèle lourd — analyse soignée)
    if opts.get('verify_coherence') and result:
        try:
            ctx.console("Vérification de cohérence (Ollama)…")
            from wama.common.utils.llm_utils import verify_text_coherence, get_describer_model
            _coh_model = get_describer_model(nature, 'scientific')  # heavy tier
            ctx.console(f"Modèle cohérence : {_coh_model}")
            coherence = verify_text_coherence(
                result,
                content_hint=nature,
                language=output_language,
                model=_coh_model,
            )
            fields['coherence_score'] = coherence['score']
            fields['coherence_notes'] = '\n'.join(coherence['notes'])
            fields['coherence_suggestion'] = coherence['suggestion']
            ctx.console(f"Cohérence vérifiée — score: {coherence['score']}/100 ✓")
        except Exception as coh_err:
            ctx.console(f"Avertissement: vérification cohérence échouée ({coh_err})")

    # Seeding ETA : clé par type de contenu (driver de coût dominant), unité selon le média.
    eta = None
    try:
        from .eta import eta_size_unit
        _size, _unit = eta_size_unit(nature, item)
        eta = (f'describer:{nature}', _size, _unit)
    except Exception:
        pass

    return {'fields': fields, 'eta': eta,
            'label': item.filename or f"description #{item.id}"}
