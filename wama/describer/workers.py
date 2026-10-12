"""
WAMA Describer — Celery Workers

Tâche principale : describe_content (nom de module HISTORIQUE `workers.py` conservé —
le nom de tâche Celery `wama.describer.workers.describe_content` est un jumeau par
CHAÎNE : routes, revokes et messages en vol le portent).

Squelette (gardes, progress, chrono, statuts, ETA, console, notifications) = brique
COMMUNE `common/utils/task_skeleton.run_item_task` (marche A2, route §10.3 — portage
2026-09-03). Depuis le 2026-10-13 la card porte un PIPELINE (`function_specs.PIPELINE` :
transcription, images-clés, description, résumé, cohérence) : ce fichier ne porte plus que la
GLU de chaque process — le squelette joue ceux qu'un lancement retient, tient une ligne
d'exécution par process, et un optionnel en échec ne fait plus échouer la card.
"""

import logging

from celery import shared_task

from .models import Description

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def describe_content(self, description_id: int, process: str = None):
    """Description d'une card, process par process. `process` : lancement borné à ce process du
    pipeline (▶ de la bande — ⚠ argument de tâche du 2026-10-13 : workers à relancer)."""
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    _settle_nature(description_id)
    run_item_task(self, app_id='describer', model=Description, item_id=description_id,
                  pipeline=PIPELINE, processes=PROCESSES, ingest_derive=_derive_detected_type,
                  notify_label='Describer', only=process)


def _derive_detected_type(inst, path, fname):
    """Hook `derive` de l'ingest URL (WAMA_INGEST) : renseigne detected_type au téléchargement."""
    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
    from .views import detect_type_from_extension
    inst.detected_type = detect_type_from_extension(ext)
    return ['detected_type']


def _settle_nature(description_id: int) -> None:
    """La nature d'une card déposée en « auto » est DÉTECTÉE avant que le squelette ne choisisse
    les process — c'est elle qui dit si la transcription et les images-clés ont lieu. Une card
    dont le fichier n'est pas encore là (source URL) la reçoit à l'ingestion (`_derive_detected_type`)."""
    from .function_specs import nature_of
    d = Description.objects.filter(pk=description_id).only(
        'detected_type', 'content_type', 'input_file').first()
    if d is None or nature_of(d) != 'auto' or not d.input_file:
        return
    from .utils.content_analyzer import detect_content_type
    try:
        nature = detect_content_type(d.input_file.path)
    except Exception:
        return
    Description.objects.filter(pk=description_id).update(detected_type=nature)


def _options(item) -> dict:
    """Valeurs EFFECTIVES de la card : défauts du schéma ← colonnes POSÉES (modèle événementiel
    §23.2quater — la tâche lit les colonnes)."""
    from wama.common.utils.param_schema import effective_settings
    from .params import PARAMS_JSON
    posees = {p['name']: getattr(item, p['name'])
              for p in PARAMS_JSON if hasattr(item, p.get('name', ''))}
    return effective_settings(PARAMS_JSON, posees=posees)


def _fingerprint(value) -> str:
    """Empreinte d'une sortie qui n'est pas un fichier — ce qui périme l'aval quand elle change."""
    import json
    from wama.common.services.revisions import text_fingerprint
    return text_fingerprint(value if isinstance(value, str)
                            else json.dumps(value, ensure_ascii=False, sort_keys=True))


def asr_key(item) -> str:
    """Le modèle de transcription de CE lancement : celui de la card, ou le tirage « auto » de la
    brique commune — domaine, politique « Whisper d'abord » et curseur lus au schéma
    (`params.py`), comme la prévision du select."""
    from wama.common.utils.auto_model import resolve_model_choice
    from wama.transcriber.backends.manager import DEFAULT_MODEL_KEY
    return resolve_model_choice(item.asr_model, app_id='describer', item=item,
                                fallback=DEFAULT_MODEL_KEY) or DEFAULT_MODEL_KEY


# ── ETA par process (`ProcessSpec.eta`) ───────────────────────────────────────────────────────
# Une clé de PROCESS n'a pas d'a priori de domaine : estimée apprise seulement, sauf `describe`,
# qui garde la clé par nature d'avant le pipeline (`describer:<nature>`, son historique appris).

def _duration(item) -> float:
    return float(getattr(item, 'duration_seconds', 0) or 0)


def transcribe_eta(item):
    return ('describer:transcribe', _duration(item), 'audio_sec', True, 0.0) if _duration(item) else None


def frames_eta(item):
    return ('describer:frames', _duration(item), 'video_sec', True, 0.0) if _duration(item) else None


def describe_eta(item):
    from .eta import eta_size_unit
    from .function_specs import nature_of
    nature = nature_of(item)
    size, unit = eta_size_unit(nature, item)
    return f'describer:{nature}', size, unit, True


def summarize_eta(item):
    return 'describer:summarize', 1.0, 'item', True, 0.0


def coherence_eta(item):
    return 'describer:coherence', 1.0, 'item', True, 0.0


# ── LES GLUES : une par process (contrat `task_skeleton`) ─────────────────────────────────────

def _transcribe_step(item, ctx):
    """Process `transcribe` : le texte parlé de l'audio, ou de la piste son d'une vidéo. Un audio
    qu'aucun modèle ne transcrit fait échouer la card ; une vidéo sans piste son lisible se décrit
    sans le son, comme avant le pipeline."""
    from .function_specs import nature_of
    key = asr_key(item)
    ctx.progress(5)
    if nature_of(item) == 'video':
        from .backends.video_backend import has_audio, transcribe_track
        if not has_audio(item.input_file.path):
            ctx.console("Vidéo sans piste son : rien à transcrire.")
            return {'fields': {'transcript': ''}, 'label': 'sans piste son',
                    'output_fingerprint': _fingerprint('')}
        text = transcribe_track(item.input_file.path, key, ctx.console, user=item.user)
    else:
        from .backends.audio_backend import transcribe_speech
        text = transcribe_speech(item.input_file.path, key, user=item.user, console=ctx.console,
                                 duration=_duration(item))
    words = len((text or '').split())
    ctx.console(f"{words} mots transcrits")
    return {'fields': {'transcript': text or ''}, 'label': f'{words} mots', 'models': [key],
            'output_fingerprint': _fingerprint(text or ''),
            'eta': transcribe_eta(item) and transcribe_eta(item)[:3]}


def _frames_step(item, ctx):
    """Process `frames` : les légendes des images-clés de la vidéo."""
    from .backends.model_choice import BLIP, catalog_key_of, vision_for
    from .backends.video_backend import caption_frames
    opts = _options(item)
    captions = caption_frames(item.input_file.path, opts, progress_callback=ctx.progress,
                              console=ctx.console)
    chosen = vision_for(opts)
    return {'fields': {'frame_captions': captions}, 'label': f'{len(captions)} images',
            'models': [catalog_key_of(chosen or BLIP)],
            'output_fingerprint': _fingerprint(captions),
            'eta': frames_eta(item) and frames_eta(item)[:3]}


def _describe_step(item, ctx):
    """Process `describe` : le backend de la nature (contrat commun « texte », `backends.ROUTES`)
    rédige la description — à partir de ce que la transcription et les images-clés ont rendu,
    qu'il reprend sans les refaire."""
    from wama.common.utils.preview_utils import publish_partial_text
    from .function_specs import HEARD, nature_of

    ctx.progress(5)
    nature = nature_of(item)
    ctx.console(f"Content type: {nature}")
    ctx.progress(10)

    # Backend au contrat commun « texte » — résolution par la nature (porte COMMUNE, import
    # RELATIF AU PAQUET : la jumelle résout ses copies de backends/). Une nature sans route lève.
    from wama.common.backends.manager import route_for_nature
    backend = route_for_nature(__package__, nature)

    opts = _options(item)
    if nature in HEARD:
        opts['transcript'] = item.transcript or ''
    if nature == 'video':
        opts['frame_captions'] = list(item.frame_captions or [])

    result = backend(
        item.input_file.path,
        options=opts,
        progress_callback=ctx.progress,
        partial_callback=lambda t: publish_partial_text('describer', item.id, t),
        console=ctx.console,
    )
    # Le modèle DÉSIGNÉ est celui qui a rédigé (jamais remplacé en silence) ; sous « auto », le
    # backend le tire lui-même et ne le rend pas — la ligne ne nomme alors aucun modèle plutôt
    # que d'en deviner un.
    from wama.common.utils.auto_model import is_auto
    designated = opts.get('vision_model' if nature == 'image' else 'llm_model')
    eta = describe_eta(item)
    return {'fields': {'result_text': result},
            'models': [] if is_auto(designated) else [designated],
            'output_fingerprint': _fingerprint(result or ''),
            'eta': eta[:3],
            'label': item.filename or f"description #{item.id}"}


def _summarize_step(item, ctx):
    """Process `summarize` (optionnel) : un résumé structuré de la description. Son échec se lit
    sur SA ligne ; avant le pipeline, c'était un avertissement sous une card « terminée »."""
    if not (item.result_text or '').strip():
        return {'label': 'rien à résumer'}
    from wama.common.utils.llm_utils import generate_structured_summary
    from .backends.model_choice import catalog_key_of, llm_for
    from .function_specs import nature_of
    opts = _options(item)
    nature = nature_of(item)
    model, provider = llm_for(opts, nature, opts.get('output_style') or 'detailed')
    ctx.console(f"Génération du résumé LLM — modèle : {model}")
    data = generate_structured_summary(item.result_text, content_hint=nature,
                                       language=opts.get('output_language') or 'fr',
                                       model=model, provider=provider)
    ctx.console("Résumé LLM généré ✓")
    return {'fields': {'summary': data['summary']}, 'label': 'résumé',
            'models': [catalog_key_of(model)], 'output_fingerprint': _fingerprint(data['summary']),
            'eta': summarize_eta(item)[:3]}


def _coherence_step(item, ctx):
    """Process `coherence` (optionnel) : score, remarques et version proposée — toujours le modèle
    lourd sous « auto » (analyse soignée)."""
    if not (item.result_text or '').strip():
        return {'label': 'rien à vérifier'}
    from wama.common.utils.llm_utils import verify_text_coherence
    from .backends.model_choice import catalog_key_of, llm_for
    from .function_specs import nature_of
    opts = _options(item)
    nature = nature_of(item)
    model, provider = llm_for(opts, nature, 'scientific')   # heavy tier sous « auto »
    ctx.console(f"Vérification de cohérence — modèle : {model}")
    coherence = verify_text_coherence(item.result_text, content_hint=nature,
                                      language=opts.get('output_language') or 'fr',
                                      model=model, provider=provider)
    ctx.console(f"Cohérence vérifiée — score: {coherence['score']}/100 ✓")
    notes = '\n'.join(coherence['notes'])
    return {'fields': {'coherence_score': coherence['score'], 'coherence_notes': notes,
                       'coherence_suggestion': coherence['suggestion']},
            'label': f"cohérence {coherence['score']}/100", 'models': [catalog_key_of(model)],
            'output_fingerprint': _fingerprint([coherence['score'], notes, coherence['suggestion']]),
            'eta': coherence_eta(item)[:3]}


#: La glu de chaque process du pipeline (`function_specs.PIPELINE`).
PROCESSES = {'transcribe': _transcribe_step, 'frames': _frames_step, 'describe': _describe_step,
             'summarize': _summarize_step, 'coherence': _coherence_step}
