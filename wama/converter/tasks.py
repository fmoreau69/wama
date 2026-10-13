"""
WAMA Converter — Celery Tasks

Tâche principale : convert_media_task
Routing : CPU-bound → queue 'default' (pas de GPU requis — mais les options cross-app
(upscale, audio_enhance) peuvent charger des modèles GPU depuis cette tâche, d'où la garde
anti-boucle-de-crash du squelette commun).

Squelette (gardes, progress, chrono, statuts, ETA, console, notifications) = brique COMMUNE
`common/utils/task_skeleton.run_item_task` (marche A2, route §10.3). Ce fichier ne porte plus
que la GLU du converter : routage de format, presets qualité, nommage de sortie, quick-convert
in-place atomique.

Depuis le 2026-10-13 la card porte un PIPELINE (`function_specs.PIPELINE` : conversion,
post-traitement IA) : une glu par process. Quand un post-traitement suit, la conversion BRUTE est
gardée (`converted_file`) et le post-traitement en repart — il se rejoue seul sans reconvertir.
"""
import logging
import os
from pathlib import Path

from celery import shared_task

from .models import ConversionJob

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def convert_media_task(self, job_id: int, process: str = None):
    """`process` : lancement borné à ce process du pipeline (▶ de la bande — ⚠ argument de tâche
    du 2026-10-13 : workers à relancer)."""
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    run_item_task(self, app_id='converter', model=ConversionJob, item_id=job_id,
                  pipeline=PIPELINE, processes=PROCESSES,
                  notify_label='Converter', only=process)


def _derive_media_type(inst, path, fname):
    """Hook `derive` de l'ingest URL (WAMA_INGEST) : renseigne media_type au téléchargement."""
    if inst.media_type:
        return []
    from .utils.format_router import detect_media_type
    inst.media_type = detect_media_type(fname) or ''
    return ['media_type']


def _final_place(job):
    """Où va la sortie FINALE de la card : `(dossier relatif à MEDIA_ROOT, dossier, nom, en place)`.

      - dest_dir set (quick convert in-place) → next to the source, keep the original stem, add a
        numeric suffix on collision.
      - otherwise → the user's home, users/<user>/converter/output/, named after the card."""
    from django.conf import settings
    in_place = bool(job.dest_dir)
    if in_place:
        rel_dir = job.dest_dir if job.dest_dir.endswith('/') else job.dest_dir + '/'
        out_dir = settings.MEDIA_ROOT / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        return rel_dir, out_dir, _build_inplace_name(out_dir, job.input_filename,
                                                     job.output_format), True
    # Le domicile de l'utilisateur, décidé par la brique (`app_media_dir`) et nulle part
    # ailleurs. ⚠ Cette ligne composait `f"converter/{job.user_id}/output/"` à la main et a
    # survécu à la bascule du 2026-09-12 : chaque conversion recréait `media/converter/` et
    # y enregistrait sa sortie (jobs 27 et 31, relancés le 14/09 — relevé le 2026-09-22).
    # Aucune des trois gardes ne la voyait : ni `MEDIA_ROOT` sur la ligne, ni fichier listé,
    # ni `upload_to` — c'est le NOM enregistré (`'output_file': …`) qui partait faux.
    from wama.common.utils.media_paths import app_media_dir
    rel_dir = app_media_dir('converter', job.user_id, 'output') + '/'
    out_dir = settings.MEDIA_ROOT / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    return rel_dir, out_dir, _build_output_name(job.input_filename, job.output_format,
                                                item_id=job.id), False


def _reserved_temp(output_format: str) -> str:
    """Un nom temporaire à la bonne extension (ffmpeg/Pillow choisissent le muxer d'après elle),
    réservé puis libéré : le backend crée lui-même le fichier."""
    import tempfile as _tf
    _fd, path = _tf.mkstemp(prefix='wama_conv_', suffix=f'.{output_format.lower()}')
    os.close(_fd)
    os.unlink(path)
    return path


def _convert(job, ctx):
    """Process `convert` (glu, contrat task_skeleton) : résout chemins et options, dispatche au
    backend du type de média. Sans post-traitement, la conversion EST la sortie (déplacée
    atomiquement in-place) ; avec, elle est gardée BRUTE (`converted_file`) dans le domicile de
    l'app, et le process `enhance` en tire la sortie. Une exception = FAILURE (le squelette gère
    statut/console/notification) ; le fichier temporaire in-place est nettoyé ICI (le squelette
    ne connaît pas les artefacts de la glu)."""
    from django.conf import settings
    from wama.common.utils.queue_duplication import safe_delete_file
    from .function_specs import enhances

    # Format ABSENT ≠ format non supporté (2026-09-14) : un job né d'un import sans format
    # descendait jusqu'au backend, qui répondait « Format vidéo non supporté : » (format vide) —
    # un faux rejet de codec. Toutes les voies de lancement passent ici : on le dit tel quel.
    if not job.output_format:
        raise ValueError("Format de sortie non défini pour ce job — le choisir dans "
                         "⚙ Paramètres, puis relancer.")

    ctx.console(f"Conversion démarrée : {job.input_filename} → .{job.output_format}")
    input_path = job.input_file.path
    then_enhance = enhances(job)

    if then_enhance:
        # La conversion BRUTE : un fichier de travail de la card, dans le domicile de l'app —
        # jamais à côté de la source de l'utilisateur, même en conversion rapide.
        from wama.common.utils.media_paths import app_media_dir
        from wama.common.utils.output_naming import compose_output_name
        output_rel_dir = app_media_dir('converter', job.user_id, 'output') + '/'
        output_dir = settings.MEDIA_ROOT / output_rel_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_name = compose_output_name(app='converter', source_name=job.input_filename,
                                          item_id=job.id, nature='raw',
                                          ext=job.output_format.lower())
        in_place = False
    else:
        output_rel_dir, output_dir, output_name, in_place = _final_place(job)

    final_output_path = str(output_dir / output_name)
    # Atomic output for in-place quick convert: the backend writes a temp file, moved to the
    # final location only on success — cancelling/erroring never leaves a partial/corrupt file
    # next to the user's source.
    output_path = _reserved_temp(job.output_format) if in_place else final_output_path

    # ── MODÈLE ÉVÉNEMENTIEL (Fabien, 02/09, ROADMAP §23.2quater) : la tâche lit LES
    # COLONNES, point. Le preset n'est PLUS un facteur au lancement — c'est un GESTE
    # D'ÉCRITURE (choisir « web » écrit 80 dans la colonne au clic, `views.update_settings` /
    # `batch_update` / `quick_convert` étalent `preset_values` à ce moment-là) ; la colonne
    # `quality_preset` n'est qu'une TRACE. Les défauts du schéma restent ici en REPLI SEUL
    # (jobs d'avant la bascule, ou nés incomplets) : ils ne peuvent plus rien écraser
    # puisque tout geste écrit. L'ancienne cascade au lancement (défauts ← preset ← posé,
    # 01/09) est REMPLACÉE — ses tests ont été recalés le même jour.
    from wama.common.utils.param_schema import effective_settings
    from .params import PARAMS_JSON
    eff_opts = effective_settings(
        PARAMS_JSON,
        posees=job.options,
        contexte={'media_type': job.media_type})

    # Aperçu « PENDANT » (brique commune, 2026-08-13) : hors in-place, ffmpeg écrit la sortie
    # progressivement sous MEDIA — l'URL partielle est lisible PENDANT la conversion pour les
    # formats à décodage en flux : tout l'AUDIO (mp3/wav/ogg…), et la VIDÉO en conteneur
    # streamable (webm/mkv/ts — un mp4/mov partiel est illisible, `moov` écrit à la FIN).
    # Documents/images/archives : partiel structurellement illisible, et conversions courtes.
    # Best-effort ; retirée en fin de glu (les deux issues).
    _streamable = (job.media_type == 'audio'
                   or (job.media_type == 'video'
                       and (job.output_format or '').lower() in ('webm', 'mkv', 'ts')))
    if not in_place and not then_enhance and _streamable:
        from wama.common.utils.preview_utils import publish_partial
        publish_partial('converter', job.pk, settings.MEDIA_URL + output_rel_dir + output_name)

    # Un VISITEUR sans compte n'a pas de post-traitement IA : le converter lui est ouvert parce
    # qu'il ne prend aucune ressource GPU (décision du 2026-08-30), et ces options chargent un
    # modèle (`function_specs.enhances` : le process n'a pas lieu). Dit dans la console de
    # l'élément, jamais ignoré en silence.
    if not then_enhance and getattr(job, 'ai_postprocess_requested', False):
        ctx.console("Post-traitement IA non appliqué : il demande un compte "
                    "(l'essai sans compte ne prend aucune ressource GPU).")

    try:
        # Le backend de la NATURE, par les ROUTES que l'app déclare (porte commune, contrat
        # « fichier » des cinq backends, B1 02/09). Jusqu'au 2026-10-05 cette glu les CONTOURNAIT
        # par un `if/elif` écrit à la main : les ROUTES ne servaient qu'au manifeste et à la
        # jumelle. La qualité d'image voyage dans `options` (le schéma la pose toujours pour une
        # image, défaut 85 — le repli `90` de l'ancien appel n'était jamais pris).
        from wama.common.backends.manager import route_for_nature
        convert = route_for_nature(__package__, job.media_type)
        convert(input_path, output_path, job.output_format, options=eff_opts,
                progress_callback=lambda p: ctx.progress(int(p)))
    except Exception:
        # Remove the in-place temp file so no partial output lingers.
        if in_place:
            try:
                if os.path.exists(output_path):
                    os.unlink(output_path)
            except Exception:
                pass
        _clear_during(job)
        raise

    # L'ancien rendu de CE process est remplacé (règle d'une relance — `safe_delete_file` : le
    # fichier de la card seulement, et seulement si rien d'autre ne le partage). Jusqu'au
    # pipeline, le lanceur l'effaçait au CLIC (`views.start`) : relancer le seul post-traitement
    # aurait emporté la conversion qu'il reprend.
    rel_path = f"{output_rel_dir}{output_name}"
    for name in (('converted_file',) if then_enhance else ('output_file', 'converted_file')):
        previous = getattr(job, name, None)
        if previous and previous.name != rel_path:
            safe_delete_file(job, name)
    fields = ({'converted_file': rel_path} if then_enhance
              else {'output_file': rel_path, 'converted_file': None})

    # In-place: move the temp result to its final location next to the source.
    if in_place:
        import shutil as _sh
        _sh.move(output_path, final_output_path)

    _clear_during(job)

    return {
        'fields': fields,
        'output_ref': rel_path,
        'eta': converter_eta_key_size(job, size_bytes=os.path.getsize(input_path)),
        'label': output_name,
    }


def _enhance(job, ctx):
    """Process `enhance` (glu) : le post-traitement IA demandé, appliqué à une COPIE de la
    conversion brute (`converted_file`) — la brute reste, le process se rejoue seul. La sortie
    finale va où la conversion serait allée sans lui (in-place compris, atomique)."""
    import shutil as _sh

    from wama.common.utils.queue_duplication import safe_delete_file
    from .utils.cross_app import apply_cross_app_options

    if not job.converted_file:
        raise RuntimeError("Conversion brute absente — relancer la conversion.")
    source = job.converted_file.path
    work = _reserved_temp(job.output_format)
    _sh.copy2(source, work)
    try:
        # `cross_app` parle de 90 à 98 % (il suivait la conversion dans la même étape) : ramené
        # à l'étendue de CE process.
        apply_cross_app_options(job, work, ctx.console,
                                lambda p: ctx.progress(max(0, min(99, int((p - 90) * 12)))))
        output_rel_dir, output_dir, output_name, _ = _final_place(job)
        rel_path = f"{output_rel_dir}{output_name}"
        if job.output_file and job.output_file.name != rel_path:
            safe_delete_file(job, 'output_file')
        _sh.move(work, str(output_dir / output_name))
    finally:
        if os.path.exists(work):
            os.unlink(work)
    _clear_during(job)
    return {'fields': {'output_file': rel_path}, 'output_ref': rel_path,
            'eta': enhance_eta(job)[:3], 'label': output_name}


# ── ETA par process (`ProcessSpec.eta`) — `convert` garde sa clé par type de conversion (son
# historique appris) ; le post-traitement est estimé appris seulement, par nature.

def convert_eta(job):
    return (*converter_eta_key_size(job), True)


def enhance_eta(job):
    try:
        size = (job.input_file.size or 0) if job.input_file else 0
    except OSError:                       # fichier d'entrée absent : la taille ne se lit pas
        size = 0
    return f'converter:enhance:{job.media_type}', max(size / 1e6, 0.01), 'mb', True, 0.0


#: La glu de chaque process du pipeline (`function_specs.PIPELINE`).
PROCESSES = {'convert': _convert, 'enhance': _enhance}


def converter_eta_key_size(job, size_bytes=None) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA d'une conversion — temps ∝ taille d'entrée (Mo), clé par type
    de conversion (ffmpeg, aucun modèle). UN lieu, partagé par la glu (taille lue sur le fichier
    local) et la vue de progression (taille du champ) — ROUTE §11 #37."""
    if size_bytes is None:
        size_bytes = job.input_file.size or 0
    return f'converter:{job.media_type}:{job.output_format}', max(size_bytes / 1e6, 0.01), 'mb'


def _clear_during(job):
    """Fin du « pendant » (succès OU échec) : la face SORTIE prend le relais. Best-effort."""
    try:
        from wama.common.utils.preview_utils import clear_partial
        clear_partial('converter', job.pk)
    except Exception:
        pass


def _build_output_name(input_filename: str, output_format: str, item_id=None) -> str:
    """`<stem>_converted[_<id>].<format>` — brique COMMUNE de nommage (2026-08-25).

    ⚠ L'HORODATAGE a disparu. Il assurait l'unicité, mais muettement : deux conversions du
    même fichier donnaient `rapport_1756134012.pdf` et `rapport_1756134139.pdf`, deux noms
    que rien ne rattachait à leur card. L'identifiant de card dit la même chose en la
    désignant — et c'est la même règle que les autres apps.
    ⚠ Il le faut ICI et pas ailleurs : l'entrée du converter peut venir d'un dossier MONTÉ,
    où la souche n'est pas rendue unique par le stockage Django.
    """
    from wama.common.utils.output_naming import compose_output_name
    return compose_output_name(app='converter', source_name=input_filename,
                               item_id=item_id, ext=output_format.lower())


def _build_inplace_name(output_dir, input_filename: str, output_format: str) -> str:
    """Keep the original stem (no timestamp) for in-place quick convert.

    Adds ' (N)' before the extension if a file with that name already exists,
    so the source is never overwritten and successive conversions don't clash.
    """
    stem = Path(input_filename).stem
    ext = output_format.lower()
    candidate = f"{stem}.{ext}"
    if not (Path(output_dir) / candidate).exists():
        return candidate
    n = 1
    while True:
        candidate = f"{stem} ({n}).{ext}"
        if not (Path(output_dir) / candidate).exists():
            return candidate
        n += 1
