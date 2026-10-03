"""
WAMA Imager - Celery Tasks

Image generation using pluggable backends.
Supports Diffusers (Python 3.12+) and ImaginAiry (legacy) with automatic fallback.
"""

from celery import shared_task
from django.utils import timezone
from django.conf import settings
import os
import logging

from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)


def _console(user_id: int, message: str, level: str = None) -> None:
    """Push console message to user."""
    try:
        if level is None:
            msg_lower = message.lower()
            if any(w in msg_lower for w in ['error', 'failed', '\u2717', 'erreur']):
                level = 'error'
            elif any(w in msg_lower for w in ['warning', 'attention']):
                level = 'warning'
            elif any(w in msg_lower for w in ['[debug]', '[parallel']):
                level = 'debug'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='imager')
    except Exception:
        pass


# `enrich_prompt_at_ingest_task` (propre à imager) SUPPRIMÉE le 31/07 : remplacée par la tâche
# GÉNÉRIQUE `common.tasks.enrich_prompt_at_ingest_task`, branchée par déclaration.


def _image_backend_for(model_key: str):
    """`(instance, None)` du backend qui exécute `model_key`, ou `(None, raison)`.

    Le MODÈLE porte son moteur, la CLASSE s'en dérive par le catalogue (`backend_for_key`,
    route F4b, 2026-09-29). Jusque-là seuls `qwen-image*`/`flux2-klein*` passaient par la
    résolution — une liste de PRÉFIXES : un modèle d'une autre source (installé par le model
    manager) n'avait aucun chemin. Règle unique désormais :
      • la classe résolue est un backend GÉNÉRIQUE du manager d'app → son instance PARTAGÉE
        (pipeline gardé chaud entre tâches, repli diffusers/imaginairy) — comme avant ;
      • une autre classe (backend DÉDIÉ : Qwen, FLUX.2 Klein, Supra2…) → instanciée ;
      • rien de résolu : générique pour un modèle de l'imager (comportement historique),
        ARRÊT dit pour un modèle d'une autre source — jamais un repli muet.
    """
    from wama.common.backends.manager import backend_for_key
    from .backends import get_backend
    from .backends.manager import is_generic_backend
    backend_class = backend_for_key(model_key)
    if backend_class is None and not model_key.startswith('imager:'):
        return None, (f"Modèle « {model_key} » : aucun backend résolu depuis le catalogue "
                      f"(moteur non déclaré, ou sans backend)")
    if backend_class is None or is_generic_backend(backend_class):
        backend = get_backend()
        if backend is None:
            return None, "No image generation backend available. Install 'diffusers' or 'imaginairy'."
        return backend, None
    if not backend_class.is_available():
        return None, (f"{backend_class.__name__} indisponible pour « {model_key} » "
                      f"(CUDA/VRAM ou dépendances manquantes).")
    return backend_class(), None


def imager_eta_key_size(generation, model: str = None) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA d'une génération — image : pas × nombre d'images ; vidéo :
    durée produite. Clé par IDENTIFIANT de modèle (pas par clé de catalogue) : l'historique appris
    avant la route F4b reste le même, et un modèle d'une autre source a la sienne. UN lieu,
    partagé par la glu (modèle TIRÉ) et la vue de progression (le réglage : « auto » y est sa
    propre famille d'estimation) — ROUTE §11 #37."""
    from wama.common.utils.model_keys import model_id
    model = model or model_id(generation.model)
    if generation.is_video_generation:
        return (f'imager:vid:{model}', float(getattr(generation, 'video_duration', 0) or 0),
                'video_sec')
    steps = (int(getattr(generation, 'steps', 0) or 0)
             * int(getattr(generation, 'num_images', 1) or 1))
    return f'imager:img:{model}', max(steps, 1), 'step'


def _declared_model_key(generation):
    """La clé de catalogue du modèle que la card DÉSIGNE, ou None sous « auto » (le tirage se
    fait dans la glu, après l'ingestion) — ce que le squelette lit pour prévenir d'un
    téléchargement de poids et pour la durée max posée sur le modèle."""
    from wama.imager.utils.auto_model import AUTO
    if (generation.model or AUTO).strip() in ('', AUTO):
        return None
    from wama.common.utils.model_keys import catalog_key
    return catalog_key(generation.model, 'imager')


def _own_file(generation, path) -> bool:
    """Ce fichier est-il une sortie de CETTE génération (nom `gen<id>_…`, brique de nommage) ?
    Garde de tout retrait fait ici : une image rangée ailleurs depuis n'est jamais touchée."""
    return os.path.basename(str(path)).startswith(f'gen{generation.id}_')


def _absolute(path) -> str:
    path = str(path)
    return path if os.path.isabs(path) else os.path.join(settings.MEDIA_ROOT, path)


def _relative(path) -> str:
    return os.path.relpath(str(path), settings.MEDIA_ROOT).replace(os.sep, '/')


def _rendered_files(generation) -> list:
    """Les rendus que la card porte aujourd'hui, en chemins absolus (images, ou la vidéo)."""
    if generation.is_video_generation:
        return [generation.output_video.path] if generation.output_video else []
    return [_absolute(p) for p in (generation.generated_images or [])]


def _output_sources(generation) -> list:
    """Ce dont le process `output` REPART : les fichiers d'origine gardés par la brique de sortie
    quand il y en a (le rendu a été transformé), sinon les rendus eux-mêmes (ils SONT l'original)."""
    kept = [_absolute(p) for p in (getattr(generation, 'native_outputs', None) or [])]
    return kept or _rendered_files(generation)


def _drop_previous_outputs(generation, keep) -> None:
    """Une génération REJOUÉE remplace tout : les originaux gardés et les rendus de la fois
    d'avant que celle-ci n'a pas réécrits sont retirés (un `.webp` d'un ancien réglage)."""
    kept = {os.path.abspath(str(p)) for p in keep}
    previous = [_absolute(p) for p in (getattr(generation, 'native_outputs', None) or [])]
    for path in previous + _rendered_files(generation):
        if os.path.abspath(path) not in kept and _own_file(generation, path) and os.path.isfile(path):
            os.remove(path)


def _files_fingerprint(paths) -> str:
    """Empreinte de ce que la génération a écrit — DÉCLARÉE à la ligne d'exécution plutôt que lue
    d'un chemin : le process `output` déplace le fichier d'origine, un chemin se perdrait."""
    from wama.common.services.revisions import text_fingerprint
    from wama.common.utils.provenance import sha256_of
    return text_fingerprint('|'.join(sha256_of(str(p)) or f'size:{os.path.getsize(str(p))}'
                                     for p in paths))


def _run_generation(task, generation_id, glue, process=None):
    """Les deux tâches de l'imager passent par le squelette COMMUN (`run_item_task`, marche P6
    du 2026-10-03) : garde de redélivrance après crash, ingestion d'une URL de référence,
    statuts canoniques, durée max, chrono, console, notifications, ligne d'exécution, révision.
    L'app garde ses deux gardes propres (une génération déjà terminée, une tâche fantôme
    re-livrée après une remise à zéro) et ses GLUS.

    La card porte un PIPELINE de deux process (`function_specs.PIPELINE`) : `generate` (la glu
    `glue`, image ou vidéo) puis `output` (`_render_output`, commune aux deux). Un lancement ne
    rejoue que ce qui n'est plus à jour : changer le format ne regénère pas. `process` borne le
    lancement à UN process."""
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    from .models import ImageGeneration

    logger.info(f"[Imager] === Task received for generation #{generation_id} ===")
    try:
        generation = ImageGeneration.objects.get(id=generation_id)
    except ImageGeneration.DoesNotExist:
        logger.error(f"[Imager] Generation #{generation_id} introuvable")
        return {'error': 'not_found', 'generation_id': generation_id}

    # Check if already completed - skip if SUCCESS or FAILURE
    if generation.status in ('SUCCESS', 'FAILURE'):
        logger.warning(f"[Imager] Generation #{generation_id} already has status {generation.status}, skipping")
        return {'skipped': True, 'reason': f'already_{generation.status.lower()}', 'generation_id': generation_id}

    # Guard against stale re-queued tasks: if the task_id in DB is empty or doesn't
    # match this task's ID, this is a ghost task (e.g. re-queued after force_reset +
    # server restart). Skip to avoid overwriting a fresh dispatch.
    current_task_id = task.request.id
    if current_task_id and generation.task_id and generation.task_id != current_task_id:
        logger.warning(
            f"[Imager] Generation #{generation_id}: task_id mismatch "
            f"(DB={generation.task_id}, this={current_task_id}) — stale re-queued task, skipping"
        )
        return {'skipped': True, 'reason': 'stale_task', 'generation_id': generation_id}

    if not (getattr(task.request, 'retries', 0) or 0):
        # « En cours » est posé par les lanceurs (`begin_processing`). L'outil de l'assistant
        # envoie la tâche PUIS écrit le statut : c'est ici qu'une génération encore « en
        # attente » passe en cours — à la première livraison seulement.
        ImageGeneration.objects.filter(pk=generation_id, status='PENDING').update(status='RUNNING')

    # La sortie repart des fichiers que la génération a laissés. S'ils ne sont plus là (retirés
    # par l'utilisateur, rangés ailleurs), une génération « à jour » ne sert plus à rien : sa
    # ligne est oubliée, et ce lancement la rejoue.
    sources = _output_sources(generation)
    if not sources or not all(os.path.isfile(p) for p in sources):
        from wama.common.services import process_runs
        process_runs.safely(
            lambda: process_runs.lines(generation).filter(node_id='generate').delete())

    run_item_task(task, app_id='imager', model=ImageGeneration, item_id=generation_id,
                  pipeline=PIPELINE, processes={'generate': glue, 'output': _render_output},
                  notify_label='Imager', model_key=_declared_model_key, only=process)
    return {'generation_id': generation_id}


def _render_output(generation, ctx):
    """Process `output` (image ET vidéo) : les réglages de SORTIE de la card — agrandissement
    (image), format, qualité — appliqués à ce que le modèle a écrit, par la brique commune qui
    GARDE le fichier d'origine (`output_formats.render_outputs`). Rejoué seul après un changement
    de format, il repart de l'original : rien n'est regénéré. Un agrandissement DEMANDÉ qui
    échoue arrête la card en le disant ; une conversion ratée garde le format d'origine."""
    from wama.common.utils.output_formats import NATIVE_FIELD, render_outputs
    video = generation.is_video_generation
    tag = '[Imager Video]' if video else '[Imager]'
    try:
        sources = _output_sources(generation)
        if not sources or not all(os.path.isfile(p) for p in sources):
            raise RuntimeError("fichier d'origine introuvable — relancer la génération")
        ctx.progress(10)
        try:
            finals, natives = render_outputs(
                sources, generation, domain='video' if video else 'image', app_id='imager',
                console=lambda m: _console(generation.user_id, f"{tag} {m}"),
                previous=[p for p in _rendered_files(generation) if _own_file(generation, p)])
        except Exception as out_err:
            raise RuntimeError(f"Réglages de sortie : {out_err}") from out_err
        fields = {NATIVE_FIELD: [_relative(p) for p in natives], 'completed_at': timezone.now()}
        if video:
            fields['output_video'] = _relative(finals[0])
        else:
            fields['generated_images'] = finals
        names = ', '.join(os.path.basename(p) for p in finals)
        return {
            'fields': fields,
            'label': (generation.prompt or '')[:50] or f"génération #{generation.id}",
            'console_success': f"{tag} \u2713 Sortie de #{generation.id} : {names}",
            'output_ref': _relative(finals[0]),
        }
    except Exception:
        _fail_stamp(generation, ctx)
        raise


def _fail_stamp(generation, ctx):
    """Un échec de la glu : l'heure de fin est posée, la barre revient à zéro — le statut, le
    message, la console et la notification sont l'affaire du squelette."""
    from .models import ImageGeneration
    ImageGeneration.objects.filter(pk=generation.pk).update(completed_at=timezone.now())
    ctx.reset_progress()


@shared_task(bind=True)
def generate_image_task(self, generation_id, process=None):
    """
    Celery task to generate images using the available backend — through the common skeleton
    (`_run_generation`) ; the work itself is the glue `_generate_image`, then `_render_output`.
    `process` : launch bounded to this process (⚠ new task argument : workers to relaunch).
    """
    return _run_generation(self, generation_id, _generate_image, process)


def _generate_image(generation, ctx):
    """La GLU de la génération d'IMAGES : tirage « auto », backend résolu par le catalogue,
    chargement, génération, enregistrement, réglages de sortie. Toute erreur LÈVE."""
    generation_id = generation.id
    try:
        # Tirage « auto » AU LANCEMENT (pas au dépôt) : le choix dépend de la VRAM libre, qui
        # a pu changer pendant l'attente en file. APRÈS l'ingestion d'une URL (faite par le
        # squelette) : la présence d'une référence peut orienter le choix du modèle.
        from wama.imager.utils.auto_model import AUTO, resolve_auto_model
        if (generation.model or AUTO).strip() in ('', AUTO):
            # Le modèle tiré vaut pour CE lancement (en mémoire) et se lit sur la ligne
            # d'exécution ; il n'est plus ÉCRIT dans le réglage : « auto » reste « auto », et un
            # réglage surveillé qui changerait pendant son propre process se périmerait lui-même.
            generation.model = resolve_auto_model(generation)
            from wama.common.utils.auto_model import quality_intent_of
            _console(generation.user_id,
                     f"[Imager] 🧠 Auto → {generation.model} (capacités + VRAM libre au lancement, "
                     f"curseur qualité {quality_intent_of(generation, 'imager')}/100)")

        user_id = generation.user.id
        _console(user_id, f"[Imager] Starting generation #{generation_id}: {generation.prompt[:50]}...")
        logger.info(f"Starting image generation #{generation_id}")

        # Import backend system
        try:
            from .backends import get_available_backends
            from wama.common.backends.image_generation_base import GenerationParams
        except ImportError as e:
            error_msg = f"Backend system not available: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Check available backends
        available = get_available_backends()
        _console(user_id, f"[Imager] Available backends: {available}")
        logger.info(f"Available backends: {available}")

        # La valeur stockée est une CLÉ de catalogue (`imager:…`, `huggingface:…`, route F4b) ;
        # une valeur nue d'avant la migration est lue dans l'espace de l'imager (`model_keys`).
        from wama.common.utils.model_keys import catalog_key, model_id
        model_key = catalog_key(generation.model, 'imager')
        backend_model = model_id(model_key)          # ce que les backends connaissent
        backend, error_msg = _image_backend_for(model_key)
        if backend is None:
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        _console(user_id, f"[Imager] Using backend: {backend.display_name}")
        logger.info(f"Using backend: {backend.name} ({backend.display_name})")

        # Create output directory (user-specific path)
        from wama.common.utils.media_paths import app_media_dir
        output_dir = os.path.join(settings.MEDIA_ROOT,
                                  app_media_dir('imager', generation.user.id, 'output'), 'image')
        os.makedirs(output_dir, exist_ok=True)

        ctx.progress(10)
        _console(user_id, f"[Imager] Loading model: {model_key}")
        # Premier lancement d'un modèle jamais téléchargé : le DIRE (brique commune, 2026-09-08).
        # Sans elle, l'utilisateur voit une tâche figée le temps de récupérer des dizaines de Go.
        from wama.common.utils.model_readiness import warn_if_weights_missing
        warn_if_weights_missing(model_key, console=lambda m: _console(user_id, f"[Imager] {m}"))

        # Load the model — le backend reçoit l'identifiant qu'il connaît (sa clé de
        # SUPPORTED_MODELS / de déclaration), jamais la clé de catalogue.
        logger.info(f"[Imager] >>> Calling backend.load({backend_model})...")
        import time as _time
        _load_start = _time.time()
        if not backend.load(backend_model):
            error_msg = f"Failed to load model: {model_key}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        logger.info(f"[Imager] <<< backend.load() completed successfully")
        _load_seconds = _time.time() - _load_start  # >2s ⇒ chargement à froid (seeding ETA)
        _console(user_id, f"[Imager] Model loaded on {backend.device}")

        ctx.progress(20)

        # Log generation mode
        mode_desc = generation.generation_mode or 'txt2img'
        if mode_desc in ('img2img', 'style2img') and generation.reference_image:
            _console(user_id, f"[Imager] {mode_desc}: Generating {generation.num_images} image(s) on {backend.device} (strength={generation.image_strength:.0%})...")
        else:
            _console(user_id, f"[Imager] Generating {generation.num_images} image(s) on {backend.device}...")

        # Get reference image path if applicable
        reference_image_path = None
        if generation.reference_image:
            reference_image_path = generation.reference_image.path
            _console(user_id, f"[Imager] Using reference image: {os.path.basename(reference_image_path)}")

        # Pipeline de prompt commune (§16.6) — KIND déclaré dans app_metadata.PROMPT_TARGETS.
        # `effective_prompt` : le prompt enrichi à l'ingestion (`prompt_processed`) prime sur ce
        # que l'utilisateur a tapé, qu'on ne touche jamais. `enrich` reste None (= suivre la
        # déclaration) car si l'enrichissement d'ingestion n'a pas eu lieu (lancement immédiat,
        # broker indisponible, préférence changée), c'est ICI qu'il se rattrape — la traduction,
        # elle, se fait toujours ici : elle dépend du modèle cible, encore modifiable après dépôt.
        from wama.common.utils.app_metadata import effective_prompt, process_prompt_for
        _cons = lambda m: _console(user_id, f"[Imager] {m}")
        _already = bool((getattr(generation, 'prompt_processed', '') or '').strip())
        _prompt = process_prompt_for('imager', 'prompt',
                                     effective_prompt(generation, 'prompt'),
                                     instance=generation, user=generation.user, console=_cons,
                                     enrich=False if _already else None,
                                     glossary=list(getattr(generation, 'prompt_keywords', None) or []) or None)
        _negative = process_prompt_for('imager', 'negative_prompt', generation.negative_prompt,
                                       instance=generation, user=generation.user)

        # Create generation parameters with multi-modal support
        params = GenerationParams(
            prompt=_prompt,
            negative_prompt=_negative,
            model=backend_model,
            width=generation.width,
            height=generation.height,
            steps=generation.steps,
            guidance_scale=generation.guidance_scale,
            seed=generation.seed,
            num_images=generation.num_images,
            # Multi-modal parameters
            generation_mode=generation.generation_mode or 'txt2img',
            reference_image=reference_image_path,
            image_strength=generation.image_strength,
        )

        # Progress callback
        def progress_callback(progress: int):
            # Map 0-100 progress to 20-90 range
            mapped_progress = 20 + int(progress * 0.7)
            ctx.progress(mapped_progress)

        # Generate images
        logger.info(f"[Imager] >>> Calling backend.generate() with {generation.num_images} image(s), model={model_key}")
        logger.info(f"[Imager]     size={generation.width}x{generation.height}, steps={generation.steps}, guidance={generation.guidance_scale}")

        import time
        gen_start = time.time()
        result = backend.generate(params, progress_callback)
        gen_duration = time.time() - gen_start

        logger.info(f"[Imager] <<< backend.generate() completed in {gen_duration:.2f}s, success={result.success}")

        if not result.success:
            error_msg = result.error or "Unknown generation error"
            logger.error(f"Generation failed: {error_msg}")
            raise RuntimeError(error_msg)

        ctx.progress(90)
        _console(user_id, f"[Imager] Saving {len(result.images)} image(s)...")

        # Save generated images
        # Include model name in filename for easy identification
        # Brique COMMUNE de nommage (2026-08-25). L'imager était la SEULE app à gérer déjà
        # l'index multi-sorties (`num_images` va de 1 à 4) : le portage aligne la FORME, il
        # n'ajoute aucune capacité. ⚠ L'index disparaît quand il n'y a qu'une image — un `_1`
        # sur une sortie unique n'apprend rien et fait croire à une suite.
        from wama.common.utils.output_naming import compose_output_name
        generated_paths = []
        for i, img in enumerate(result.images):
            try:
                filename = compose_output_name(
                    app='imager', model=backend_model, item_id=generation.id, ext='.png',
                    index=i + 1, total=len(result.images))
                output_path = os.path.join(output_dir, filename)
                img.save(output_path)
                generated_paths.append(output_path)
                logger.info(f"Saved image {i+1}/{len(result.images)}: {output_path}")
            except Exception as save_error:
                logger.error(f"Error saving image {i+1}: {save_error}")

        if not generated_paths:
            error_msg = "Failed to save any generated images"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # Les réglages de SORTIE (agrandissement, format) sont le process suivant, `output`
        # (`_render_output`) : ici la glu rend ce que le MODÈLE a écrit, rien d'autre.
        _drop_previous_outputs(generation, keep=generated_paths)

        logger.info(f"Successfully generated {len(generated_paths)} image(s) for generation #{generation_id}")

        # Seeding ETA : diffusion image → temps ∝ steps × nb images (clé par modèle) ;
        # chargement séparé (singleton keep_loaded) enregistré seulement à froid (>2s).
        # Enregistré ICI (pas par le `eta` du squelette) : la mesure est celle du calcul SEUL,
        # le chargement à part — le squelette ne connaît que la durée du process entier.
        try:
            from wama.model_manager.services.eta_estimator import record_run
            _key, _size, _unit = imager_eta_key_size(generation, model=backend_model)
            record_run(_key, size=_size, unit=_unit,
                       process_seconds=gen_duration,
                       load_seconds=(_load_seconds if _load_seconds and _load_seconds >= 2 else None),
                       user=generation.user)
        except Exception:
            pass

        # Le statut, la progression à 100 et la durée de traitement sont posés par le squelette
        # (la durée est désormais celle de la TÂCHE, chargement compris, comme pour la vidéo).
        from wama.common.utils.output_formats import NATIVE_FIELD
        return {
            'fields': {'generated_images': generated_paths, NATIVE_FIELD: []},
            'label': (generation.prompt or '')[:50] or f"génération #{generation_id}",
            'console_success': (f"[Imager] \u2713 Generated {len(generated_paths)} image(s) for "
                                f"#{generation_id} (seed: {result.seed_used})"),
            'models': [model_key],
            'output_fingerprint': _files_fingerprint(generated_paths),
        }
    except Exception:
        _fail_stamp(generation, ctx)
        raise


def _segment_count(wanted_frames: int, segment_frames: int, overlap: int = 1) -> int:
    """Passages nécessaires pour `wanted_frames` quand chacun en produit `segment_frames` —
    les `overlap` premières images d'un segment prolongé REPRENNENT la fin du précédent (1 pour
    un départ d'image, `continuation_frames` pour une continuation) : elles ne comptent pas,
    chaque prolongation n'apporte que `segment_frames - overlap` images neuves."""
    fresh = segment_frames - max(1, int(overlap))
    if wanted_frames <= segment_frames or fresh < 1:
        return 1
    return 1 + -(-(wanted_frames - segment_frames) // fresh)


def _frame_to_pil(frame):
    """Une image de sortie (PIL, ou tableau numpy HxWx3 en [0,1] ou [0,255]) → PIL RGB."""
    from PIL import Image
    if isinstance(frame, Image.Image):
        return frame.convert('RGB')
    import numpy as np
    arr = np.asarray(frame)
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0, 1) * 255).round().astype(np.uint8) if arr.max() <= 1.0 \
            else np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr).convert('RGB')


def _extend_by_segments(run, params, first_frames, wanted_frames, seed, work_dir,
                        on_segment=None, overlap: int = 1):
    """PROLONGE une vidéo au-delà du plafond d'UN passage du modèle (2026-09-23, décision de
    Fabien : « dépasser 5 s en informant l'utilisateur que c'est extrapolé »).

    Chaque segment est un passage IMAGE→VIDÉO qui repart de la DERNIÈRE image du précédent,
    avec le même prompt ; sa première image (qui la reprend) est retirée à la jointure. C'est
    une extrapolation : le modèle ne voit que la dernière image, pas le mouvement — la
    continuité n'est pas garantie, et c'est ce que l'écran dit en rouge.

    `run(params, callback)` exécute un passage (le moteur de la tâche). Un segment en échec
    ARRÊTE la prolongation en gardant ce qui est fait : une vidéo plus courte vaut mieux
    qu'aucune. Rend la liste d'images, tronquée à `wanted_frames`.

    `overlap > 1` = CONTINUATION (2026-09-23) : le segment suivant est conditionné par les
    `overlap` DERNIÈRES images (`params.reference_frames`, LTX) — il voit le mouvement, et ses
    `overlap` premières images, qui les reprennent, sont retirées à la jointure.
    """
    import dataclasses
    frames = list(first_frames)
    index = 0
    while len(frames) < wanted_frames:
        index += 1
        continuation = overlap > 1 and hasattr(params, 'reference_frames')
        ref_path = os.path.join(work_dir, f'.segment_{index}_start.png')
        _frame_to_pil(frames[-1]).save(ref_path)
        changes = {'reference_image': ref_path}
        if continuation:
            changes['reference_frames'] = [_frame_to_pil(f) for f in frames[-overlap:]]
        if hasattr(params, 'generation_mode'):
            changes['generation_mode'] = 'img2vid'
        if seed is not None and hasattr(params, 'seed'):
            changes['seed'] = int(seed) + index      # un tirage neuf par segment, reproductible
        callback = on_segment(index) if on_segment else None
        try:
            result = run(dataclasses.replace(params, **changes), callback)
        finally:
            try:
                os.unlink(ref_path)
            except OSError:
                pass
        if not result.success or not len(result.video_frames):
            logger.warning(f"[Imager Video] segment {index} en échec ({result.error}) — "
                           f"prolongation arrêtée à {len(frames)} images")
            break
        frames.extend(list(result.video_frames)[overlap if continuation else 1:])
    return frames[:wanted_frames]


def _report_effective_video_settings(user_id, generation, backend, params, export_fps,
                                     total_frames=None, overlap: int = 1):
    """Dit à l'utilisateur ce qui sera RÉELLEMENT généré, et chaque réglage que le modèle ignore.

    Relevé le 2026-09-23 (génération #48, FastWan) : la console annonçait « 241 frames, 15.1 s
    @ 16 fps, 30 steps, guidage 5 » — les valeurs DEMANDÉES — puis le modèle en faisait 121 à
    24 i/s en 3 pas sans guidage, et le bilan final redisait « Duration: 15.0s ». Chaque réglage
    ignoré l'était silencieusement ou en DEBUG. Ce relevé est posé APRÈS la résolution propre à
    chaque moteur : il lit les paramètres effectifs, pas le formulaire.
    """
    try:
        total = int(total_frames or params.num_frames)
        effective_s = total / float(export_fps or 1)
        requested_s = float(generation.video_duration or 0)
        _console(user_id, f"[Imager Video] Effectif : {total} images à {export_fps} i/s "
                          f"= {effective_s:.1f} s, {params.width}×{params.height}")
        if total > params.num_frames:
            n = _segment_count(total, params.num_frames, overlap)
            limit_s = params.num_frames / float(export_fps)
            if overlap > 1:
                _console(user_id, f"[Imager Video] Au-delà de {limit_s:.1f} s (un passage du "
                                  f"modèle), la vidéo est CONTINUÉE en {n} segments : chacun "
                                  f"reprend les {overlap} dernières images du précédent "
                                  f"(mouvement continu, dérive possible sur la durée)")
            else:
                _console(user_id, f"[Imager Video] ⚠ Au-delà de {limit_s:.1f} s (un passage du "
                                  f"modèle), la vidéo est PROLONGÉE en {n} segments, chacun "
                                  f"repartant de la dernière image : fonctionnement EXTRAPOLÉ, "
                                  f"continuité non garantie", level='warning')
        if requested_s and abs(effective_s - requested_s) >= 0.5:
            _console(user_id, f"[Imager Video] ⚠ Durée : {effective_s:.1f} s au lieu des "
                              f"{requested_s:.0f} s demandées — limite du modèle "
                              f"{generation.model}", level='warning')
        if generation.video_fps and int(generation.video_fps) != int(export_fps):
            _console(user_id, f"[Imager Video] Cadence : {export_fps} i/s imposés par le modèle "
                              f"(réglage {generation.video_fps} i/s sans effet)", level='warning')
        requested_w, requested_h = generation.get_video_resolution()
        if (params.width, params.height) != (requested_w, requested_h):
            _console(user_id, f"[Imager Video] Résolution : {params.width}×{params.height} "
                              f"(demandé {requested_w}×{requested_h})", level='warning')
        from wama.common.utils.model_declarations import declaration_for
        from wama.common.utils.model_keys import model_id
        native = (declaration_for(generation.model, 'imager') or {}).get('resolution')
        if native:
            nw, _, nh = str(native).partition('x')
            if nw.isdigit() and nh.isdigit() and params.width * params.height < int(nw) * int(nh):
                _console(user_id, f"[Imager Video] ⚠ Résolution native du modèle : {native} — "
                                  f"en dessous, la qualité baisse", level='warning')
        profile = (getattr(backend, 'MODEL_PROFILES', None) or {}).get(model_id(generation.model)) or {}
        if profile.get('dmd_timesteps'):
            _console(user_id, f"[Imager Video] Modèle distillé : {len(profile['dmd_timesteps'])} "
                              f"pas et guidage {profile.get('guidance_scale', 1.0)} imposés — "
                              f"Steps, Guidance et prompt négatif sans effet", level='warning')
    except Exception as exc:                 # un relevé d'information ne fait jamais échouer
        logger.debug(f"[Imager Video] relevé des réglages effectifs impossible : {exc}")


@shared_task(bind=True)
def generate_video_task(self, generation_id, process=None):
    """
    Celery task to generate videos (txt2vid, img2vid) — through the common skeleton
    (`_run_generation`) ; the work itself is the glue `_generate_video`, then `_render_output`.
    `process` : launch bounded to this process (⚠ new task argument : workers to relaunch).
    """
    return _run_generation(self, generation_id, _generate_video, process)


def _generate_video(generation, ctx):
    """La GLU de la génération de VIDÉOS : tirage « auto », backend résolu par le catalogue,
    limites natives du modèle, génération (prolongée par segments au besoin), export, format de
    sortie. Toute erreur LÈVE."""
    import time

    task_start_time = time.time()
    generation_id = generation.id
    try:
        # Tirage « auto » AU LANCEMENT (pas au dépôt) : le choix dépend de la VRAM libre, qui
        # a pu changer pendant l'attente en file. APRÈS l'ingestion d'une URL (faite par le
        # squelette) : la présence d'une référence peut orienter le choix du modèle.
        from wama.imager.utils.auto_model import AUTO, resolve_auto_model
        if (generation.model or AUTO).strip() in ('', AUTO):
            # Le modèle tiré vaut pour CE lancement (en mémoire) et se lit sur la ligne
            # d'exécution ; il n'est plus ÉCRIT dans le réglage : « auto » reste « auto », et un
            # réglage surveillé qui changerait pendant son propre process se périmerait lui-même.
            generation.model = resolve_auto_model(generation)
            from wama.common.utils.auto_model import quality_intent_of
            _console(generation.user_id,
                     f"[Imager] 🧠 Auto → {generation.model} (capacités + VRAM libre au lancement, "
                     f"curseur qualité {quality_intent_of(generation, 'imager')}/100)")

        user_id = generation.user.id
        mode_label = "Text-to-Video" if generation.generation_mode == 'txt2vid' else "Image-to-Video"

        _console(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        _console(user_id, f"[Imager Video] Starting {mode_label} generation #{generation_id}")
        _console(user_id, f"[Imager Video] Model: {generation.model}")
        _console(user_id, f"[Imager Video] Prompt: {generation.prompt[:80]}{'...' if len(generation.prompt) > 80 else ''}")
        logger.info(f"Starting video generation #{generation_id} ({mode_label})")

        # Pipeline de prompt commune (§16.6) — manquait côté vidéo (comblé 2026-07-08 avec les
        # skills). Variables LOCALES pour la TRADUCTION (dépend du modèle cible, donc calculée
        # ici) ; l'ENRICHISSEMENT, lui, est persisté à l'ingestion dans `prompt_processed` et
        # `effective_prompt` le reprend — cf. le commentaire de la tâche image.
        from wama.common.utils.app_metadata import effective_prompt, process_prompt_for
        _cons = lambda m: _console(user_id, f"[Imager Video] {m}")
        _already = bool((getattr(generation, 'prompt_processed', '') or '').strip())
        _prompt = process_prompt_for('imager', 'prompt',
                                     effective_prompt(generation, 'prompt'),
                                     instance=generation, user=generation.user, console=_cons,
                                     enrich=False if _already else None,
                                     glossary=list(getattr(generation, 'prompt_keywords', None) or []) or None)
        _negative = process_prompt_for('imager', 'negative_prompt', generation.negative_prompt,
                                       instance=generation, user=generation.user, console=_cons)

        # Clé de CATALOGUE (résolution) et IDENTIFIANT (ce que le backend connaît, et la
        # politique de cadence par famille ci-dessous) — route F4b, 2026-09-29 : la valeur
        # stockée est une clé entière, une valeur nue d'avant la migration se lit dans l'imager.
        from wama.common.utils.model_keys import catalog_key, model_id
        model_key = catalog_key(generation.model, 'imager')
        model_name = model_id(model_key)
        backend_type = None

        if model_name.startswith('hunyuan-'):
            backend_type = 'hunyuan'
        elif model_name.startswith('cogvideox-'):
            backend_type = 'cogvideox'
        elif model_name.startswith('ltx-'):
            backend_type = 'ltx'
        elif model_name.startswith('mochi-'):
            backend_type = 'mochi'
        else:
            backend_type = 'wan'  # Default to Wan

        # Le MODÈLE porte son moteur ; la CLASSE s'en dérive par le catalogue (les 5 backends
        # vidéo pilotent tous `diffusers` — `SUPPORTED_MODELS` les départage), et la classe de
        # PARAMÈTRES est DÉCLARÉE par le backend (`PARAMS`) : plus aucun import par chemin
        # (2026-09-07, 5 branches → 1). `backend_type` (préfixe de nom) ne sert plus qu'à la
        # POLITIQUE de cadence/résolution par famille, plus bas — c'est une décision d'app.
        # ⚠ Un modèle absent du catalogue ne se devine plus « par défaut » (l'ancien `else`
        # envoyait tout inconnu vers Wan) : il s'arrête en le DISANT. Wan et HunyuanVideo n'ont
        # plus ni déclaration ni poids sur disque depuis janvier ; leurs branches étaient mortes.
        from wama.common.backends.manager import backend_for_key
        backend_class = backend_for_key(model_key)
        params_class = getattr(backend_class, 'PARAMS', None)
        if backend_class is None or params_class is None:
            error_msg = (f"Modèle vidéo « {model_key} » : aucun backend résolu depuis le catalogue "
                         f"({model_key} absent, sans moteur déclaré, ou backend sans PARAMS)")
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        _console(user_id, f"[Imager Video] Backend résolu par le catalogue : {backend_class.__name__}")
        if not backend_class.is_available():
            error_msg = (f"{backend_class.__name__} indisponible pour « {model_name} » "
                         f"(CUDA/VRAM ou dépendances manquantes).")
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        _console(user_id, f"[Imager Video] ✓ {backend_class.__name__} disponible")

        # Create output directory (user-specific path)
        from wama.common.utils.media_paths import app_media_dir
        output_dir = os.path.join(settings.MEDIA_ROOT,
                                  app_media_dir('imager', generation.user.id, 'output'), 'video')
        os.makedirs(output_dir, exist_ok=True)
        _console(user_id, f"[Imager Video] Output dir: {output_dir}")

        ctx.progress(5)

        # Initialize backend
        backend = backend_class()
        _console(user_id, f"[Imager Video] Loading model: {model_key}")
        # ⚠ Un avertissement EN DUR vivait ici (« ~5-10GB on first run »), affiché à CHAQUE
        # lancement — donc même quand les poids étaient déjà là, et avec un volume inventé.
        # Remplacé par la brique commune (2026-09-08) : elle ne parle QUE si le catalogue dit
        # `is_downloaded=False`, et elle annonce la taille RÉELLE quand elle la connaît.
        # *Un avertissement permanent n'avertit plus de rien.*
        from wama.common.utils.model_readiness import warn_if_weights_missing
        warn_if_weights_missing(model_key,
                                console=lambda m: _console(user_id, f"[Imager Video] ⏳ {m}"))

        model_load_start = time.time()

        # Progress callback during load — maps backend stage (0-100) to task progress (5-18%)
        def _load_stage_cb(label: str, stage_pct: int):
            mapped = 5 + int(stage_pct * 0.13)  # 5% + up to 13% during load → max 18%
            ctx.progress(mapped)
            _console(user_id, f"[Imager Video] {label}")

        # Load the model (pass stage callback for progress reporting)
        load_kwargs = {}
        if hasattr(backend, 'load') and 'stage_callback' in backend.load.__code__.co_varnames:
            load_kwargs['stage_callback'] = _load_stage_cb

        if not backend.load(model_name, **load_kwargs):
            error_msg = f"Failed to load video model: {model_key}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        model_load_time = time.time() - model_load_start
        _console(user_id, f"[Imager Video] ✓ Model loaded in {model_load_time:.1f}s")

        ctx.progress(20)

        # Get resolution from generation
        width, height = generation.get_video_resolution()

        # Calculate frames
        num_frames = generation.calculate_video_frames()
        estimated_duration = num_frames / generation.video_fps

        _console(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        _console(user_id, f"[Imager Video] Parameters (demandés — l'effectif suit) :")
        _console(user_id, f"[Imager Video]   Resolution: {width}x{height}")
        _console(user_id, f"[Imager Video]   Frames: {num_frames} ({estimated_duration:.1f}s @ {generation.video_fps}fps)")
        _console(user_id, f"[Imager Video]   Steps: {generation.steps}")
        _console(user_id, f"[Imager Video]   Guidance: {generation.guidance_scale}")
        _console(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Get reference image path if applicable
        reference_image_path = None
        if generation.reference_image and generation.generation_mode == 'img2vid':
            reference_image_path = generation.reference_image.path
            _console(user_id, f"[Imager Video] Reference image: {os.path.basename(reference_image_path)}")

        # Capacités NATIVES du modèle (cadence, plafond d'images, résolution, prolongation),
        # tirées de SA déclaration — la même lecture que l'écran (`cap_from`). Les constantes
        # par moteur (8 / 24 / 30 i/s, 720×480, 848×480) écrites ici jusqu'au 2026-09-23
        # doublaient la déclaration et avaient DIVERGÉ d'elle (CogVideoX déclarait 24 i/s).
        from wama.common.utils.model_capabilities import (derive_inputs_from_tasks,
                                                          video_caps_from_declaration)
        from wama.common.utils.model_declarations import declaration_for
        _decl = declaration_for(model_key) or {}
        _tokens = derive_inputs_from_tasks(str(_decl.get('tasks') or '').lower(),
                                           is_video=True)['tokens']
        vcaps = video_caps_from_declaration(_decl, _tokens)

        def _native_size(default):
            w, _, h = str(vcaps.get('native_resolution') or '').partition('x')
            return (int(w), int(h)) if w.isdigit() and h.isdigit() else default

        # Create video generation parameters (different structure per backend)
        # export_fps = FPS used when writing the MP4 — must match the model's native FPS
        # so that playback duration == intended duration.
        if backend_type == 'hunyuan':
            export_fps = generation.video_fps
            params = params_class(
                prompt=_prompt,
                negative_prompt=_negative,
                model=model_name,
                width=width,
                height=height,
                num_frames=num_frames,
                num_inference_steps=generation.steps,
                cfg_scale=generation.guidance_scale,
                seed=generation.seed,
                fps=export_fps,
                reference_image=reference_image_path,
            )
        elif backend_type == 'cogvideox':
            # CogVideoX native fps = 8. Frames must satisfy 4k+1 constraint.
            # Use the requested duration to compute the correct frame count.
            COGVIDEOX_FPS = int(vcaps.get('fps') or 8)       # déclarée : 8 i/s
            export_fps = COGVIDEOX_FPS
            cog_w, cog_h = _native_size((720, 480))           # résolution d'entraînement
            raw_cogvideox = int(generation.video_duration * COGVIDEOX_FPS)
            k = max(1, round((raw_cogvideox - 1) / 4))
            cogvideox_frames = 4 * k + 1  # e.g. 5s→41f, 6s→49f, 8s→65f
            _console(user_id, f"[Imager Video] CogVideoX: {cogvideox_frames} frames à {COGVIDEOX_FPS}fps = {cogvideox_frames / COGVIDEOX_FPS:.1f}s")
            params = params_class(
                prompt=_prompt,
                negative_prompt=_negative,
                model=model_name,
                width=cog_w,
                height=cog_h,
                num_frames=cogvideox_frames,
                num_inference_steps=generation.steps,
                guidance_scale=generation.guidance_scale,
                seed=generation.seed,
                fps=COGVIDEOX_FPS,
                reference_image=reference_image_path,
            )
        elif backend_type == 'ltx':
            # LTX-Video native fps = 24. Frames must be 8n+1.
            LTX_FPS = int(vcaps.get('fps') or 24)            # déclarée : 24 i/s
            export_fps = LTX_FPS
            ltx_width = (width // 32) * 32
            ltx_height = (height // 32) * 32

            # FP8 variant: cap resolution + frames to avoid CUDA driver OOM.
            # The FP8 transformer uses ~12.5GB, leaving ~11GB for computation.
            # At 1280×720 × 361 frames the attention tensors exceed this budget.
            # Safe ceiling (empirical): ≤ 768×432, ≤ 161 frames (~6.7s).
            if model_name == 'ltx-video-13b-0.9.8-distilled-fp8':
                LTX_FP8_MAX_W, LTX_FP8_MAX_H, LTX_FP8_MAX_FRAMES = 768, 432, 161
                if ltx_width > LTX_FP8_MAX_W or ltx_height > LTX_FP8_MAX_H:
                    scale = min(LTX_FP8_MAX_W / ltx_width, LTX_FP8_MAX_H / ltx_height)
                    ltx_width  = ((int(ltx_width  * scale)) // 32) * 32
                    ltx_height = ((int(ltx_height * scale)) // 32) * 32
                    _console(user_id,
                        f"[Imager Video] FP8: résolution réduite à {ltx_width}×{ltx_height} "
                        f"(max {LTX_FP8_MAX_W}×{LTX_FP8_MAX_H} pour ce modèle)", level='warning')

            raw_ltx = int(generation.video_duration * LTX_FPS)
            ltx_frames = ((raw_ltx - 1) // 8) * 8 + 1  # 8n+1
            ltx_frames = max(9, ltx_frames)  # minimum 9 frames

            # Le plafond d'images de la variante fp8 (161) est DÉCLARÉ (`max_frames`) et appliqué
            # plus bas, avec les autres moteurs — il n'est plus codé ici.

            _console(user_id, f"[Imager Video] LTX-Video: {ltx_frames} frames à {LTX_FPS}fps = {ltx_frames / LTX_FPS:.1f}s")
            params = params_class(
                prompt=_prompt,
                negative_prompt=_negative or "worst quality, inconsistent motion, blurry, jittery, distorted",
                model=model_name,
                width=ltx_width,
                height=ltx_height,
                num_frames=ltx_frames,
                num_inference_steps=generation.steps,
                guidance_scale=generation.guidance_scale,
                seed=generation.seed,
                fps=LTX_FPS,
                reference_image=reference_image_path,
            )
        elif backend_type == 'mochi':
            # Mochi native fps = 30 ; le plafond (84 images) est DÉCLARÉ (`max_frames`) et
            # appliqué plus bas, avec les autres moteurs.
            MOCHI_FPS = int(vcaps.get('fps') or 30)          # déclarée : 30 i/s
            export_fps = MOCHI_FPS
            mochi_w, mochi_h = _native_size((848, 480))
            raw_mochi = int(generation.video_duration * MOCHI_FPS)
            mochi_frames = max(1, raw_mochi)
            _console(user_id, f"[Imager Video] Mochi: {mochi_frames} frames à {MOCHI_FPS}fps = {mochi_frames / MOCHI_FPS:.1f}s")
            params = params_class(
                prompt=_prompt,
                negative_prompt=_negative,
                model=model_name,
                width=mochi_w,
                height=mochi_h,
                num_frames=mochi_frames,
                num_inference_steps=generation.steps,
                guidance_scale=generation.guidance_scale,
                seed=generation.seed,
                fps=MOCHI_FPS,
            )
        else:
            # Wan backend — cadence et durée maximale DÉCLARÉES par le modèle quand il les porte
            # (FastWan 2.2 : 24 i/s natifs, 121 images) ; sinon les réglages de la génération.
            # La grille de résolution (multiple de 16 ou 32 selon le VAE) est alignée par le
            # backend, qui seul connaît son pipeline.
            from wama.common.utils.model_declarations import declaration_for
            wan_declaration = declaration_for(model_key) or {}
            export_fps = int(wan_declaration.get('fps') or generation.video_fps)
            if wan_declaration.get('fps'):
                raw_wan = int(generation.video_duration * export_fps)
                num_frames = 4 * max(1, round((raw_wan - 1) / 4)) + 1
            params = params_class(
                prompt=_prompt,
                negative_prompt=_negative,
                model=model_name,
                width=width,
                height=height,
                num_frames=num_frames,
                fps=export_fps,
                guidance_scale=generation.guidance_scale,
                num_inference_steps=generation.steps,
                seed=generation.seed,
                generation_mode=generation.generation_mode,
                reference_image=reference_image_path,
            )

        # ── Limites NATIVES du modèle (déclaration → capacités, 2026-09-23) ──────────────
        # Un seul fait pour l'écran et la tâche : `max_frames` borne UN passage. Au-delà, soit
        # le modèle déclare la prolongation par segments (image→vidéo enchaînés, extrapolé),
        # soit la durée est ramenée au plafond — et c'est DIT.
        wanted_frames = params.num_frames
        native_max = vcaps.get('max_frames')
        extend = False
        if native_max and wanted_frames > native_max:
            params.num_frames = int(native_max)
            extend = (vcaps.get('duration_extension') in ('segments', 'continuation')
                      and hasattr(params, 'reference_image'))
            if not extend:
                wanted_frames = params.num_frames
        # Continuation : les dernières images conditionnent le passage suivant ; départ d'image :
        # une seule. Le nombre vient de la DÉCLARATION du modèle (`continuation_frames`).
        overlap = (int(vcaps.get('continuation_frames') or 1)
                   if vcaps.get('duration_extension') == 'continuation'
                   and hasattr(params, 'reference_frames') else 1)
        _report_effective_video_settings(user_id, generation, backend, params, export_fps,
                                         total_frames=wanted_frames, overlap=overlap)

        last_progress_log = 0

        # Progress callback with console updates
        def progress_callback(progress: int):
            nonlocal last_progress_log
            # Map 0-100 progress to 20-85 range (save 15% for export)
            mapped_progress = 20 + int(progress * 0.65)
            ctx.progress(mapped_progress)

            # Log every 10%
            if progress >= last_progress_log + 10:
                elapsed = time.time() - generation_start
                _console(user_id, f"[Imager Video] Generation: {progress}% (elapsed: {elapsed:.0f}s)")
                last_progress_log = progress

        # Generate video
        _console(user_id, f"[Imager Video] ⏳ Starting video generation... This may take 5-30 minutes.")
        logger.info(f"Generating video with {num_frames} frames at {width}x{height}")

        generation_start = time.time()

        # Call the appropriate generation method based on backend
        def _run(run_params, callback):
            if backend_type in ('hunyuan', 'cogvideox', 'ltx', 'mochi'):
                return backend.generate(run_params, callback)       # .generate()
            return backend.generate_video(run_params, callback)     # Wan : .generate_video()

        n_segments = _segment_count(wanted_frames, params.num_frames, overlap) if extend else 1

        def _segment_progress(index):
            return lambda p: progress_callback(int((index * 100 + p) / n_segments))

        result = _run(params, _segment_progress(0) if extend else progress_callback)
        video_frames = result.video_frames
        seed_used = result.seed_used
        if result.success and extend:
            def _on_segment(index):
                how = (f"reprend les {overlap} dernières images" if overlap > 1
                       else "repart de la dernière image — extrapolé")
                _console(user_id, f"[Imager Video] ↪ Segment {index + 1}/{n_segments} ({how})")
                return _segment_progress(index)
            video_frames = _extend_by_segments(
                _run, params, video_frames, wanted_frames, seed_used, output_dir,
                on_segment=_on_segment, overlap=overlap)

        generation_time = time.time() - generation_start

        if not result.success:
            error_msg = result.error or "Unknown video generation error"
            logger.error(f"Video generation failed: {error_msg}")
            raise RuntimeError(error_msg)

        _console(user_id, f"[Imager Video] ✓ Generation complete in {generation_time:.1f}s")
        _console(user_id, f"[Imager Video] Seed used: {seed_used}")

        ctx.progress(85)
        _console(user_id, f"[Imager Video] Exporting {len(video_frames)} frames to MP4...")

        # Export video to MP4
        # Include model name in filename for easy identification
        from wama.common.utils.output_naming import compose_output_name
        video_filename = compose_output_name(app='imager', model=model_name,
                                             item_id=generation.id, ext='.mp4')
        video_path = os.path.join(output_dir, video_filename)

        export_start = time.time()
        if not backend.export_video(video_frames, video_path, fps=export_fps):
            error_msg = "Failed to export video to MP4"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        export_time = time.time() - export_start
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024) if os.path.exists(video_path) else 0
        _console(user_id, f"[Imager Video] ✓ Exported in {export_time:.1f}s ({file_size_mb:.1f} MB)")

        # Format et qualité de sortie : le process suivant, `output` (`_render_output`).
        _drop_previous_outputs(generation, keep=[video_path])

        # Save video path relative to MEDIA_ROOT for FileField
        relative_video_path = os.path.relpath(video_path, settings.MEDIA_ROOT).replace(os.sep, '/')

        # Seeding ETA : génération vidéo → temps ∝ durée produite (clé par modèle) ;
        # chargement séparé (model_load_time) enregistré seulement à froid (>2s). Enregistré
        # ICI : calcul et chargement sont mesurés à part, le squelette ne connaît que le total.
        try:
            from wama.model_manager.services.eta_estimator import record_run
            _key, _size, _unit = imager_eta_key_size(generation, model=model_name)
            record_run(_key, size=_size, unit=_unit,
                       process_seconds=generation_time + export_time,
                       load_seconds=(model_load_time if model_load_time and model_load_time >= 2 else None),
                       user=generation.user)
        except Exception:
            pass

        total_time = time.time() - task_start_time
        _console(user_id, f"[Imager Video] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        _console(user_id, f"[Imager Video]   Duration: {len(video_frames) / float(export_fps or 1):.1f}s "
                          f"({len(video_frames)} frames @ {export_fps} fps)")
        _console(user_id, f"[Imager Video]   Seed: {seed_used}")
        _console(user_id, f"[Imager Video]   Total time: {total_time:.1f}s")
        logger.info(f"Successfully generated video for generation #{generation_id}")

        # Le statut, la progression à 100 et la durée de traitement (celle de la TÂCHE :
        # chargement + génération + export) sont posés par le squelette.
        from wama.common.utils.output_formats import NATIVE_FIELD
        return {
            'fields': {'output_video': relative_video_path, NATIVE_FIELD: []},
            'label': (generation.prompt or '')[:50] or f"vidéo #{generation_id}",
            'console_success': f"[Imager Video] ✓ SUCCESS! Generation #{generation_id}",
            'models': [model_key],
            'output_fingerprint': _files_fingerprint([video_path]),
        }
    except Exception:
        _fail_stamp(generation, ctx)
        raise
