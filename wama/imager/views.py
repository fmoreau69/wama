"""
WAMA Imager - Views
Image generation using Diffusers with multi-modal support:
- txt2img: Text to image (standard)
- file2img: Batch from prompt file (txt/json/yaml)
- describe2img: Auto-prompt from reference image via BLIP
- style2img: Style transfer from reference image
- img2img: Image to image transformation
"""

from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.cache import cache
from django.utils import timezone
from django.conf import settings
from django.db.models import Q
import os
import json
import logging
from pathlib import Path

from wama.accounts.permissions import app_access
from wama.common.utils.scoping import owned_or_404, visible_or_404
from .models import ImageGeneration, UserSettings
from wama.model_manager.services import get_registry_models
from .utils.model_config import (
    DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, DEFAULT_I2V_MODEL, get_model_defaults,
)
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


@app_access('imager')
def index(request):
    """Main page showing generation queue"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Réconcilie les items RUNNING orphelins (worker mort / crash machine) — brique
    # COMMUNE, preuve positive de mort uniquement. Sans elle, une génération dont le
    # worker est mort sans acquitter reste une card RUNNING zombie indéfiniment
    # (vécu 29/07/2026 : génération #42, kernel panic WSL2).
    try:
        from wama.common.utils.process_control import reconcile_orphaned_running
        running = list(ImageGeneration.objects.filter(user=user, status='RUNNING'))
        n = reconcile_orphaned_running(running, error_field='error_message')
        if n:
            logger.info(f"[imager] {n} tâche(s) RUNNING orpheline(s) réconciliée(s) → échec relançable")
    except Exception as exc:
        logger.debug(f"[imager] reconcile_orphaned_running ignoré: {exc}")

    # NOTE PARTAGE (PROFILES_PERMISSIONS §7) : le mixin `ScopedVisibility` est en place sur le
    # modèle, mais imager n'est PAS porté — c'est l'app la moins avancée de la grille mesurée
    # (56 %, dernière sur 10 au 31/07) et elle n'a pas besoin du partage : elle crée ses cards
    # par prompt. Passer cette seule vue en `visible_to()` rendait une card partagée VISIBLE
    # dans la file puis 404 au moindre clic (10 autres sites filtrent encore `user=user`) —
    # une porte à moitié ouverte, pire qu'une porte fermée. On reste donc propriétaire-seul
    # jusqu'au portage complet des chemins de LECTURE.
    # Le filtre `parent_generation__isnull=True` (« top-level ») est RETIRÉ avec le self-FK :
    # il n'y a plus de hiérarchie parent/enfant, tout item appartient à un GenerationBatch.
    generations = ImageGeneration.objects.filter(user=user).order_by('-created_at')

    # Réglages user — brique commune (A5-22) : clés + défauts uniques (USER_SETTINGS_DEFAULTS,
    # DÉRIVÉS du schéma params.py). Remplace le modèle Django `UserSettings` (5 colonnes), qui
    # n'était écrit par personne : son seul écrivain, la vue `update_settings`, n'était appelée
    # depuis AUCUN JS/template — et son défaut codé en dur 'stable-diffusion-v1-5' empêchait le
    # volet d'afficher « Auto » (donc de proposer le tirage VRAM-aware commun).
    # Le modèle lui-même est retiré au palier suivant, une fois la bascule vérifiée.
    from wama.common.utils.user_settings import get_user_app_settings
    from wama.imager.params import (
        IMAGE_PARAMS, USER_SETTINGS_DEFAULTS, VIDEO_PARAMS, panel_values_by_name,
    )
    panel_settings = get_user_app_settings(user, 'imager', USER_SETTINGS_DEFAULTS)

    # Get available models from backend system (fast method - no heavy imports)
    try:
        from .backends import get_models_choices_fast, get_models_with_info_fast, get_backend_info_fast

        # Use fast methods to avoid slow torch/diffusers imports during page load
        models_choices = get_models_choices_fast()
        models_info = get_models_with_info_fast()  # Full info with descriptions
        # Verrou n°1 (étape 1) — ENRICHIR la liste backend avec les métadonnées du registre
        # AIModel (capacités, statut téléchargé, description/VRAM canoniques) SANS jamais
        # masquer un modèle chargeable. La bascule « registre = source de la LISTE » viendra
        # quand le catalogue sera complet + chargeur générique + pipeline de téléchargement
        # (sinon on masquerait les modèles que le registre ne connaît pas encore).
        try:
            from wama.model_manager.services import get_registry_models
            _, _reg_info = get_registry_models('imager')
            _reg = {d['id']: d for d in _reg_info}
            for d in models_info:
                r = _reg.get(d.get('id'))
                if r:
                    d['capabilities'] = r.get('capabilities') or {}
                    d['downloaded'] = r.get('downloaded')
                    if r.get('description'):
                        d['description'] = r['description']
                    if r.get('vram'):
                        d['vram'] = r['vram']
        except Exception:
            pass  # registre indispo → liste backend inchangée
        backend_info = get_backend_info_fast()

        backend_name = backend_info['backend_name']
        backend_available = backend_info['backend_available']
        available_backends = backend_info['available_backends']
    except ImportError:
        # Fallback to default models if backend system not available
        models_choices = [
            ('hunyuan-image-2.1', 'HunyuanDiT Image 2.1'),
            ('stable-diffusion-xl', 'Stable Diffusion XL'),
            ('stable-diffusion-v1-5', 'Stable Diffusion 1.5'),
        ]
        models_info = [
            {'id': 'hunyuan-image-2.1', 'name': 'HunyuanDiT Image 2.1', 'description': 'Modèle image haute qualité', 'vram': '12GB'},
            {'id': 'stable-diffusion-xl', 'name': 'Stable Diffusion XL', 'description': 'Modèle SDXL 1024px', 'vram': '8GB'},
            {'id': 'stable-diffusion-v1-5', 'name': 'Stable Diffusion 1.5', 'description': 'Modèle classique', 'vram': '4GB'},
        ]
        backend_name = "Unknown"
        backend_available = False
        available_backends = {}

    # Generation mode choices for UI - Images
    # Modes sourcés depuis le schéma COMMUN (app_modes) = source unique de vérité (métadonnée-driven).
    # Mêmes valeurs qu'avant (txt2img/img2img/style2img/file2img/describe2img) → radios + JS inchangés ;
    # seuls libellés/ordre/icônes viennent du schéma. Repli sur l'ancienne liste si le schéma manque.
    from wama.common.utils.app_modes import get_domain as _get_domain
    _img_modes = _get_domain('imager', 'image').get('modes', [])
    if _img_modes:
        image_modes = [(m['id'], m['label'], 'fas ' + m.get('icon', 'fa-circle')) for m in _img_modes]
    else:
        image_modes = [
            ('txt2img', 'Text to Image', 'fas fa-keyboard'),
            ('file2img', 'File (Batch)', 'fas fa-file-alt'),
            ('describe2img', 'Describe', 'fas fa-search-plus'),
            ('style2img', 'Style Transfer', 'fas fa-palette'),
            ('img2img', 'Img2Img', 'fas fa-exchange-alt'),
        ]

    # Generation mode choices for UI - Videos
    video_modes = [
        ('txt2vid', 'Text to Video', 'fas fa-keyboard'),
        ('img2vid', 'Image to Video', 'fas fa-image'),
    ]

    # Modèles vidéo — servis par la brique COMMUNE, filtrés sur la capacité déclarée au
    # manifeste puis ingérée au catalogue. Aucun filtre par type ici : l'app ne fait que
    # nommer la capacité qu'elle veut. La liste littérale qui vivait à cet endroit portait
    # une Nᵉ copie des VRAM et proposait encore `cogvideox-5b`, retiré du parc le 28/07.
    # `requires=['video']` = la MODALITÉ, pas la tâche : la liste doit contenir les modèles
    # image→vidéo (cogvideox-5b-i2v) autant que les texte→vidéo. Le tirage, lui, demande la
    # tâche précise ('t2v' ou 'i2v') plus bas.
    video_models, video_models_info = get_registry_models('imager', modality='video')

    # ── Card d'entrée commune (une instance PAR DOMAINE) ─────────────────────────
    # Groupes du <select> modèle : la catégorie ('logo') vient des CAPACITÉS catalogue
    # (optgroup, jamais un onglet) ; méta d'appariement entrée↔modèle pour
    # wama-input-match (inputs_required/optional déclarés au manifeste → catalogue).
    from wama.imager.params import (
        IMAGE_GROUPS_JSON, IMAGE_PARAMS_JSON, VIDEO_GROUPS_JSON, VIDEO_PARAMS_JSON,
    )

    def _mz(d):
        return {'id': d.get('id'), 'name': d.get('name') or d.get('id'),
                'vram': d.get('vram') or '', 'description': d.get('description') or ''}

    def _cat(d):
        return d.get('category') or (d.get('capabilities') or {}).get('category')

    _logo_models = [d for d in models_info if _cat(d) == 'logo']
    _plain_image = [d for d in models_info if _cat(d) != 'logo']
    image_model_groups = [{'label': 'Images', 'models': [_mz(d) for d in _plain_image]}]
    if _logo_models:
        image_model_groups.append({'label': 'Logos', 'models': [_mz(d) for d in _logo_models]})
    video_model_groups = [{'label': 'Vidéos', 'models': [_mz(d) for d in video_models_info]}]

    input_match_meta = {}
    for d in list(models_info) + list(video_models_info):
        _caps = d.get('capabilities') or {}
        input_match_meta[d['id']] = {
            'label': d.get('name') or d['id'],
            'inputs_required': _caps.get('inputs_required') or [],
            'inputs_optional': _caps.get('inputs_optional') or [],
        }
    from wama.common.utils.app_modes import INPUT_TYPES as _INPUT_TYPES
    input_labels = {k: (v.get('label') or k) for k, v in _INPUT_TYPES.items()}

    # ── File bâtie sur les BATCHS (contrat commun) ───────────────────────────────
    # Tout est batch ; une génération isolée est auto-enveloppée dans son batch-of-1
    # (c'est aussi ce qui la rend PARTAGEABLE — le batch est l'unité de partage).
    from wama.common.utils.batch_common import auto_wrap_orphans, build_batches_list
    from wama.common.utils.queue_view import apply_queue_sort_filter
    from wama.imager.models import GenerationBatch, GenerationBatchItem

    def _wrap_by_domain(orphans):
        """Batch-of-1 par orphelin, en portant le DOMAINE (la file de l'imager est
        scopée par onglet) — le défaut commun ne connaît pas ce champ d'app."""
        made = []
        for g in orphans:
            try:
                b = GenerationBatch.objects.create(
                    user=g.user, total=1,
                    domain='video' if g.is_video_generation else 'image')
                GenerationBatchItem.objects.create(batch=b, generation=g, row_index=0)
                made.append(b)
            except Exception:
                pass
        return made

    auto_wrap_orphans(user, work_model=ImageGeneration, batch_model=GenerationBatch,
                      item_model=GenerationBatchItem, fk_name='generation',
                      wrap_group=_wrap_by_domain)

    batches_all = build_batches_list(user, batch_model=GenerationBatch,
                                     work_attr='generation')
    for _b in batches_all:                       # chips schéma-driven sur chaque card
        for _it in _b['items']:
            if _it.generation:
                _decorate_card(_it.generation)

    image_batches = [b for b in batches_all if b['obj'].domain != 'video']
    video_batches = [b for b in batches_all if b['obj'].domain == 'video']

    def _name(b):
        first = next((i.generation for i in b['items'] if i.generation), None)
        return (first.prompt or '') if first else ''

    image_batches, q_sort, q_filter = apply_queue_sort_filter(request, image_batches, name_of=_name)
    video_batches, _vs, _vf = apply_queue_sort_filter(request, video_batches, name_of=_name)

    # Listes à plat conservées pour les compteurs d'onglet et la barre globale.
    image_generations = [i.generation for b in image_batches for i in b['items'] if i.generation]
    video_generations = [i.generation for b in video_batches for i in b['items'] if i.generation]

    context = {
        'generations': generations,
        'image_generations': image_generations,
        'video_generations': video_generations,
        # Valeurs du VOLET pour WamaParams.render(..., {context:'panel', values}) : ré-indexées
        # par NOM de param (ce que render attend), une surface par domaine. Le stockage, lui,
        # reste clé par dom_id — cf. params.panel_values_by_name.
        'image_panel_values_json': json.dumps(panel_values_by_name(panel_settings, IMAGE_PARAMS)),
        'video_panel_values_json': json.dumps(panel_values_by_name(panel_settings, VIDEO_PARAMS)),
        'models_choices': models_choices,
        'models_info': models_info,  # Model info with descriptions for tooltips
        'video_models': video_models,
        'video_models_info': video_models_info,  # Video model info with descriptions
        'backend_name': backend_name,
        'backend_available': backend_available,
        'available_backends': available_backends,
        'image_modes': image_modes,
        'video_modes': video_modes,
        'generation_modes': image_modes,  # Keep for backward compatibility
        # Card d'entrée commune (une par domaine) — groupes du select + appariement.
        'image_model_groups': image_model_groups,
        'video_model_groups': video_model_groups,
        'input_match_meta': json.dumps(input_match_meta),
        'input_labels': json.dumps(input_labels),
        'model_groups_json': json.dumps({'image': image_model_groups,
                                         'video': video_model_groups}),
        # Modales ⚙ schéma-driven (params.py = source unique) — WamaParams les génère.
        # File par BATCHS (brique commune) + état de la toolbar (tri/filtre en session).
        'image_batches': image_batches,
        'video_batches': video_batches,
        'q_sort': q_sort,
        'q_filter': q_filter,
        'image_params_json': json.dumps(IMAGE_PARAMS_JSON),
        'video_params_json': json.dumps(VIDEO_PARAMS_JSON),
        'image_groups_json': json.dumps(IMAGE_GROUPS_JSON),
        'video_groups_json': json.dumps(VIDEO_GROUPS_JSON),
    }

    return render(request, 'imager/index.html', context)


@require_http_methods(["POST"])
@app_access('imager')
def create_generation(request):
    """Create a new image generation task (routes to appropriate handler based on mode)"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Get generation mode
        generation_mode = request.POST.get('generation_mode', 'txt2img')

        # Route to appropriate handler
        if generation_mode == 'file2img':
            return handle_file2img(request, user)
        elif generation_mode == 'describe2img':
            return handle_describe2img(request, user)
        elif generation_mode in ('style2img', 'img2img'):
            return handle_img2img(request, user, generation_mode)
        elif generation_mode == 'txt2vid':
            return handle_txt2vid(request, user)
        elif generation_mode == 'img2vid':
            return handle_img2vid(request, user)
        else:
            # Default: txt2img mode
            return handle_txt2img(request, user)

    except Exception as e:
        logger.error(f"Error creating generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def handle_txt2img(request, user):
    """Handle standard text-to-image generation"""
    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return JsonResponse({'error': 'Prompt is required'}, status=400)

    negative_prompt = request.POST.get('negative_prompt', '').strip()
    # Défauts SOURCÉS depuis la déclaration du modèle (model_config), jamais en dur ici :
    # 512x512 / 30 étapes / guidance 7.5 sont les valeurs de l'ère SD 1.5 et dégradent tout
    # modèle 1024 px en rectified flow (Qwen, FLUX).
    # On ENREGISTRE le choix (ou 'auto') — le tirage a lieu au LANCEMENT de la tâche, où la
    # VRAM libre est celle du moment (cf. utils/auto_model.py). Résoudre ici serait périmé.
    model = request.POST.get('model') or 'auto'
    _def = get_model_defaults(model)
    width = int(request.POST.get('width', _def['width']))
    height = int(request.POST.get('height', _def['height']))
    steps = int(request.POST.get('steps', _def['steps']))
    guidance_scale = float(request.POST.get('guidance_scale', _def['guidance_scale']))
    seed = request.POST.get('seed')
    if seed:
        seed = int(seed)
    else:
        seed = None
    num_images = int(request.POST.get('num_images', 1))
    upscale = request.POST.get('upscale', 'false').lower() == 'true'

    # Create generation object
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='txt2img',
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        num_images=num_images,
        upscale=upscale,
        output_format=request.POST.get('output_format', 'original'),
        output_quality=request.POST.get('output_quality', 'balanced'),
        status='PENDING'
    )

    logger.info(f"Created txt2img generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'message': 'Generation created successfully'
    })


def handle_file2img(request, user):
    """Handle batch generation from prompt file (txt/json/yaml)"""
    from .utils.prompt_parser import parse_prompt_file, validate_prompt_config

    # `batch_file` = nom de champ du contrat WamaBatchImport ; `prompt_file` = nom historique
    # posté par la card. UNE seule implémentation de création sert les deux entrées.
    prompt_file = request.FILES.get('prompt_file') or request.FILES.get('batch_file')
    if not prompt_file:
        return JsonResponse({'error': 'No prompt file provided'}, status=400)

    # Default parameters for batch
    # Défauts SOURCÉS depuis la déclaration du modèle (model_config), jamais en dur ici :
    # 512x512 / 30 étapes / guidance 7.5 sont les valeurs de l'ère SD 1.5 et dégradent tout
    # modèle 1024 px en rectified flow (Qwen, FLUX).
    # On ENREGISTRE le choix (ou 'auto') — le tirage a lieu au LANCEMENT de la tâche, où la
    # VRAM libre est celle du moment (cf. utils/auto_model.py). Résoudre ici serait périmé.
    model = request.POST.get('model') or 'auto'
    _def = get_model_defaults(model)
    width = int(request.POST.get('width', _def['width']))
    height = int(request.POST.get('height', _def['height']))
    steps = int(request.POST.get('steps', _def['steps']))
    guidance_scale = float(request.POST.get('guidance_scale', _def['guidance_scale']))

    # Save file temporarily to parse it
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(prompt_file.name).suffix) as tmp:
        for chunk in prompt_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        # Parse prompts from file
        prompts = parse_prompt_file(tmp_path)

        if not prompts:
            return JsonResponse({'error': 'No valid prompts found in file'}, status=400)

        # ── Batch COMMUN (GenerationBatch), plus de parent/enfants par self-FK ────────
        # Avant : un ImageGeneration « conteneur » en status SUCCESS + N enfants relies par
        # `parent_generation`. Ce mecanisme etait DOUBLE par GenerationBatch depuis `9922f65`
        # sans avoir ete retire — juxtaposition, pas remplacement. Effet concret : le conteneur
        # n'etant pas un vrai travail, `auto_wrap_orphans` l'enveloppait dans un batch-of-1 et
        # il occupait une card fantome dans la file (2 en base au moment du portage).
        # Le batch est aussi l'unite de PARTAGE : passer par lui rend le lot partageable, ce que
        # le self-FK ne permettait pas.
        from wama.common.utils.batch_common import consolidate_into_batch
        from wama.imager.models import GenerationBatch, GenerationBatchItem

        generations = [
            ImageGeneration.objects.create(
                user=user,
                generation_mode='txt2img',
                prompt=v.get('prompt', ''),
                negative_prompt=v.get('negative_prompt', ''),
                model=v.get('model', model),
                width=v.get('width', width),
                height=v.get('height', height),
                steps=v.get('steps', steps),
                guidance_scale=v.get('guidance_scale', guidance_scale),
                seed=v.get('seed'),
                num_images=v.get('num_images', 1),
                status='PENDING',
            )
            for v in (validate_prompt_config(p) for p in prompts)
        ]

        def _create_batch(total):
            b = GenerationBatch.objects.create(user=user, domain='image', total=total)
            # Le fichier de prompts vit sur le BATCH (champ prevu pour, models.py:445) et non
            # sur un faux item : il est partage par les lignes et nettoye par BatchMixin.
            b.batch_file.save(prompt_file.name, prompt_file)
            return b

        batch = consolidate_into_batch(
            generations,
            create_batch=_create_batch,
            link_item=lambda b, g, idx: GenerationBatchItem.objects.create(
                batch=b, generation=g, row_index=idx),
        )

        logger.info(f"Created generation batch #{batch.id} with {len(generations)} items "
                    f"for user {user.username}")

        return JsonResponse({
            'success': True,
            'batch_id': batch.id,
            'children_ids': [g.id for g in generations],
            'count': len(generations),
            'message': f'Created {len(generations)} generation(s) from file'
        })

    finally:
        # Clean up temp file
        os.unlink(tmp_path)


def handle_describe2img(request, user):
    """Handle describe-to-image: auto-generate prompt from reference image using BLIP"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'No reference image provided'}, status=400)

    # Défauts SOURCÉS depuis la déclaration du modèle (model_config), jamais en dur ici :
    # 512x512 / 30 étapes / guidance 7.5 sont les valeurs de l'ère SD 1.5 et dégradent tout
    # modèle 1024 px en rectified flow (Qwen, FLUX).
    # On ENREGISTRE le choix (ou 'auto') — le tirage a lieu au LANCEMENT de la tâche, où la
    # VRAM libre est celle du moment (cf. utils/auto_model.py). Résoudre ici serait périmé.
    model = request.POST.get('model') or 'auto'
    _def = get_model_defaults(model)
    width = int(request.POST.get('width', _def['width']))
    height = int(request.POST.get('height', _def['height']))
    steps = int(request.POST.get('steps', _def['steps']))
    guidance_scale = float(request.POST.get('guidance_scale', _def['guidance_scale']))
    prompt_style = request.POST.get('prompt_style', 'detailed')

    # Create generation with placeholder prompt
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='describe2img',
        prompt='[Generating prompt from image...]',
        model=model,
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        status='PENDING'
    )
    generation.reference_image.save(reference_image.name, reference_image)

    # Generate auto-prompt from image
    try:
        from .utils.auto_prompt import generate_prompt_from_image

        auto_prompt = generate_prompt_from_image(
            generation.reference_image.path,
            style=prompt_style
        )

        generation.prompt = auto_prompt
        generation.auto_prompt = auto_prompt
        generation.save()

        logger.info(f"Created describe2img generation #{generation.id} with auto-prompt for user {user.username}")

        return JsonResponse({
            'success': True,
            'generation_id': generation.id,
            'auto_prompt': auto_prompt,
            'message': 'Generation created with auto-generated prompt'
        })

    except Exception as e:
        logger.error(f"Error generating auto-prompt: {e}")
        # Keep the generation but mark error
        generation.prompt = f"[Auto-prompt failed: {str(e)}]"
        generation.status = 'FAILURE'
        generation.error_message = str(e)
        generation.save()

        return JsonResponse({
            'error': f'Failed to generate prompt from image: {str(e)}',
            'generation_id': generation.id
        }, status=500)


def handle_img2img(request, user, mode):
    """Handle img2img and style2img: image-to-image transformation"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'No reference image provided'}, status=400)

    prompt = request.POST.get('prompt', '').strip()
    negative_prompt = request.POST.get('negative_prompt', '').strip()
    # Défauts SOURCÉS depuis la déclaration du modèle (model_config), jamais en dur ici :
    # 512x512 / 30 étapes / guidance 7.5 sont les valeurs de l'ère SD 1.5 et dégradent tout
    # modèle 1024 px en rectified flow (Qwen, FLUX).
    # On ENREGISTRE le choix (ou 'auto') — le tirage a lieu au LANCEMENT de la tâche, où la
    # VRAM libre est celle du moment (cf. utils/auto_model.py). Résoudre ici serait périmé.
    model = request.POST.get('model') or 'auto'
    _def = get_model_defaults(model)
    width = int(request.POST.get('width', _def['width']))
    height = int(request.POST.get('height', _def['height']))
    steps = int(request.POST.get('steps', _def['steps']))
    guidance_scale = float(request.POST.get('guidance_scale', _def['guidance_scale']))
    image_strength = float(request.POST.get('image_strength', 0.75))
    seed = request.POST.get('seed')
    if seed:
        seed = int(seed)
    else:
        seed = None
    num_images = int(request.POST.get('num_images', 1))

    # For style2img mode, if no prompt is provided, generate one
    if mode == 'style2img' and not prompt:
        prompt = "in the style of the reference image"

    # Create generation
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode=mode,
        prompt=prompt or '[No prompt - pure img2img]',
        negative_prompt=negative_prompt,
        model=model,
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        num_images=num_images,
        image_strength=image_strength,
        status='PENDING'
    )
    generation.reference_image.save(reference_image.name, reference_image)

    logger.info(f"Created {mode} generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'mode': mode,
        'message': f'{mode} generation created successfully'
    })


def handle_txt2vid(request, user):
    """Handle text-to-video generation"""
    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return JsonResponse({'error': 'Prompt is required'}, status=400)

    negative_prompt = request.POST.get('negative_prompt', '').strip()
    model = request.POST.get('model') or 'auto'
    video_duration = float(request.POST.get('video_duration', 5.0))
    video_fps = int(request.POST.get('video_fps', 16))
    video_resolution = request.POST.get('video_resolution', '480p')
    steps = int(request.POST.get('steps', 50))
    guidance_scale = float(request.POST.get('guidance_scale', 5.0))
    seed = request.POST.get('seed')
    if seed:
        seed = int(seed)
    else:
        seed = None

    # Create generation object
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='txt2vid',
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        video_duration=video_duration,
        video_fps=video_fps,
        video_resolution=video_resolution,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        status='PENDING'
    )

    logger.info(f"Created txt2vid generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'message': 'Video generation created successfully'
    })


def handle_img2vid(request, user):
    """Handle image-to-video generation"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'Reference image is required'}, status=400)

    prompt = request.POST.get('prompt', '').strip()
    negative_prompt = request.POST.get('negative_prompt', '').strip()
    model = request.POST.get('model') or 'auto'
    video_duration = float(request.POST.get('video_duration', 5.0))
    video_fps = int(request.POST.get('video_fps', 16))
    video_resolution = request.POST.get('video_resolution', '480p')
    steps = int(request.POST.get('steps', 50))
    guidance_scale = float(request.POST.get('guidance_scale', 5.0))
    seed = request.POST.get('seed')
    if seed:
        seed = int(seed)
    else:
        seed = None

    # Create generation object
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='img2vid',
        prompt=prompt or 'animate this image',
        negative_prompt=negative_prompt,
        model=model,
        video_duration=video_duration,
        video_fps=video_fps,
        video_resolution=video_resolution,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        status='PENDING'
    )
    generation.reference_image.save(reference_image.name, reference_image)

    logger.info(f"Created img2vid generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'message': 'Image-to-video generation created successfully'
    })


@require_http_methods(["POST"])
def generate_auto_prompt(request):
    """Generate prompt from uploaded image using BLIP (AJAX endpoint)"""
    reference_image = request.FILES.get('reference_image')
    if not reference_image:
        return JsonResponse({'error': 'No image provided'}, status=400)

    prompt_style = request.POST.get('prompt_style', 'detailed')

    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(reference_image.name).suffix) as tmp:
        for chunk in reference_image.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        from .utils.auto_prompt import generate_prompt_from_image

        auto_prompt = generate_prompt_from_image(tmp_path, style=prompt_style)

        return JsonResponse({
            'success': True,
            'prompt': auto_prompt
        })

    except Exception as e:
        logger.error(f"Error generating auto-prompt: {e}")
        return JsonResponse({'error': str(e)}, status=500)

    finally:
        os.unlink(tmp_path)


@require_http_methods(["POST"])
def batch_preview(request):
    """Aperçu d'un fichier de prompts (contrat WamaBatchImport) : parse SANS créer.

    Réponse : {'count', 'items': [{'filename', 'path'}], 'warnings'} — patron composer
    (batch de PROMPTS, pas de médias) ; la detect bar affiche `filename`, `path` en title.
    """
    batch_file = request.FILES.get('batch_file')
    if not batch_file:
        return JsonResponse({'error': 'Aucun fichier batch fourni'}, status=400)

    from .utils.prompt_parser import parse_prompt_file, validate_prompt_config

    import tempfile
    suffix = Path(batch_file.name).suffix or '.txt'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in batch_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        prompts = parse_prompt_file(tmp_path)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    stem = Path(batch_file.name).stem
    items, warnings = [], []
    for i, p in enumerate(prompts, 1):
        v = validate_prompt_config(p)
        texte = (v.get('prompt') or '').strip()
        if not texte:
            warnings.append(f"Ligne {i} : prompt vide, ignorée.")
            continue
        # Noms de sortie indexés sur le nom du FICHIER batch (décision projet, cf.
        # batch_parsers.apply_indexed_output_names) — cohérent avec les autres apps.
        items.append({'filename': f"{stem}_{i:02d}", 'path': texte})

    return JsonResponse({'count': len(items), 'items': items, 'warnings': warnings})


@require_http_methods(["POST"])
def import_batch(request):
    """Création depuis la detect bar commune (contrat WamaBatchImport).

    Délègue à `handle_file2img` — UNE seule implémentation de création de batch, quelle que
    soit l'entrée (card historique ou barre de détection commune).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    return handle_file2img(request, user)


def batch_template(request):
    """Gabarit batch téléchargeable, GÉNÉRÉ depuis la déclaration des champs
    (brique commune build_batch_template — jamais de contenu en dur, A5-23)."""
    from wama.common.utils.batch_parsers import build_batch_template
    text = build_batch_template(
        ['prompt', 'modele', 'steps', 'seed'],
        {'prompt': 'un phare dans la brume, photographie argentique',
         'modele': 'auto', 'steps': 30, 'seed': ''},
        app_label='Imager (un prompt par ligne)')
    resp = HttpResponse(text, content_type='text/plain; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="imager_batch_template.txt"'
    return resp


def get_batch_children(request, batch_id):
    """Items d'un GenerationBatch (contrat commun, plus le self-FK `parent_generation`)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        from wama.imager.models import GenerationBatch

        batch = visible_or_404(GenerationBatch, user, id=batch_id)   # LECTURE
        children = [it.generation for it in
                    batch.items.select_related('generation').order_by('row_index')
                    if it.generation]

        children_data = [{
            'id': c.id,
            'prompt': c.prompt[:100] + ('...' if len(c.prompt) > 100 else ''),
            'status': c.status,
            'progress': c.progress,
            'generated_images': c.generated_images,
        } for c in children]

        return JsonResponse({
            'batch_id': batch.id,
            'count': len(children),
            'children': children_data
        })

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error getting batch children: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_batch(request, batch_id):
    """Démarre tous les items PENDING d'un GenerationBatch (contrat commun)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        from wama.imager.models import GenerationBatch

        # Porte désormais sur le BATCH COMMUN, plus sur le self-FK `parent_generation`
        # (retiré : il doublait GenerationBatch et n'offrait ni UI ni partage).
        # MUTATION (démarrage) → `owned_or_404` : un batch partagé n'est jamais lançable par
        # son destinataire. Le partage est en LECTURE SEULE par construction (scoping.py).
        batch = owned_or_404(GenerationBatch, user, id=batch_id)
        pending = [it.generation for it in batch.items.select_related('generation')
                   if it.generation and it.generation.status == 'PENDING']

        if not pending:
            return JsonResponse({'error': 'No pending children to start'}, status=400)

        from .tasks import generate_image_task, generate_video_task
        from wama.common.utils.process_control import begin_processing

        started_count = 0
        for gen in pending:
            # Anti-race PAR ITEM (brique commune, patron transcriber start_all) : sans ça, deux
            # clics sur « Démarrer le batch » dispatchaient DEUX tâches GPU pour chaque item.
            gen, err = begin_processing(
                ImageGeneration, gen.pk, user=user,
                reset={'progress': 0, 'error_message': ''},
            )
            if err:
                continue
            cache.delete(f"imager_progress_{gen.id}")
            # Un batch vidéo existe (domain='video') → dispatcher la bonne tâche, comme
            # start_all_generations. L'ancien code forçait generate_image_task.
            task = (generate_video_task if gen.is_video_generation
                    else generate_image_task).delay(gen.id)
            gen.task_id = task.id
            gen.save(update_fields=['task_id'])
            started_count += 1

        logger.info(f"Started {started_count} item(s) of generation batch #{batch_id}")

        return JsonResponse({
            'success': True,
            'started': started_count,
            'message': f'Started {started_count} generation(s)'
        })

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error starting batch: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_generation(request, generation_id):
    """Start a specific generation task"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Anti-race COMMUN (atomic + select_for_update + revoke) — audit 2026-07-11
        from wama.common.utils.process_control import begin_processing
        generation, err = begin_processing(
            ImageGeneration, generation_id, user=user,
            reset={'progress': 0, 'error_message': ''},
        )
        if err == 'not_found':
            return JsonResponse({'error': 'Generation not found'}, status=404)
        if err == 'already_running':
            return JsonResponse({'error': 'Generation already running'}, status=400)
        cache.delete(f"imager_progress_{generation_id}")

        # Import tasks - use video task for video modes
        from .tasks import generate_image_task, generate_video_task

        # Start appropriate Celery task based on mode
        if generation.is_video_generation:
            task = generate_video_task.delay(generation.id)
        else:
            task = generate_image_task.delay(generation.id)

        generation.task_id = task.id
        generation.save(update_fields=['task_id'])

        logger.info(f"Started generation #{generation.id}, task_id: {task.id}")

        return JsonResponse({
            'success': True,
            'task_id': task.id,
            'message': 'Generation started'
        })

    except Exception as e:
        logger.error(f"Error starting generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def restart_generation(request, generation_id):
    """Restart a completed or failed generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Anti-race COMMUN, comme start_generation. Le heuristique maison qui précédait
        # (« relance autorisée si RUNNING depuis > 30 min, ou > 2 h en vidéo ») a été RETIRÉ :
        #  • il DOUBLAIT `reconcile_orphaned_running`, déjà appelé à l'index (views.py:44), qui
        #    traite les RUNNING zombies par PREUVE POSITIVE DE MORT au lieu d'un délai ;
        #  • il était plus FAIBLE : une génération légitimement longue (vidéo > 2 h) devenait
        #    relançable et partait une 2e fois sur le GPU — le scénario exact des kernel panics
        #    WSL2 du 2026-07-29, causés par l'imager non câblé ;
        #  • l'échappatoire reste entière et explicite : `force_reset_generation` (⏹ du bouton
        #    de cycle, queue.js:12), que le message d'erreur d'origine désignait déjà.
        from wama.common.utils.process_control import begin_processing
        generation, err = begin_processing(
            ImageGeneration, generation_id, user=user,
            reset={'progress': 0, 'error_message': ''},
        )
        if err == 'not_found':
            return JsonResponse({'error': 'Generation not found'}, status=404)
        if err == 'already_running':
            return JsonResponse({
                'error': "Cette génération tourne déjà. Si elle semble bloquée, utilisez ⏹ "
                         "(réinitialisation forcée).",
            }, status=400)

        # Clear progress cache to avoid showing old values
        cache.delete(f"imager_progress_{generation_id}")

        # Import tasks - use video task for video modes
        from .tasks import generate_image_task, generate_video_task

        # Start appropriate Celery task based on mode
        if generation.is_video_generation:
            task = generate_video_task.delay(generation.id)
        else:
            task = generate_image_task.delay(generation.id)

        generation.task_id = task.id
        generation.save(update_fields=['task_id'])

        logger.info(f"Restarted generation #{generation.id}, task_id: {task.id}")

        return JsonResponse({
            'success': True,
            'task_id': task.id,
            'message': 'Generation restarted'
        })

    except Exception as e:
        logger.error(f"Error restarting generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def start_all_generations(request):
    """Start all pending generations"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        pending = ImageGeneration.objects.filter(user=user, status='PENDING')

        if not pending.exists():
            return JsonResponse({'error': 'No pending generations'}, status=400)

        from .tasks import generate_image_task, generate_video_task
        from wama.common.utils.process_control import begin_processing

        started_count = 0
        for generation in pending:
            # Anti-race PAR ITEM (brique commune, patron transcriber start_all) : le QuerySet est
            # une photo, et deux « Démarrer tout » concurrents dispatchaient deux tâches GPU pour
            # le même item. `begin_processing` re-lit sous verrou et saute ce qui tourne déjà.
            generation, err = begin_processing(
                ImageGeneration, generation.pk, user=user,
                reset={'progress': 0, 'error_message': ''},
            )
            if err:
                continue
            cache.delete(f"imager_progress_{generation.id}")

            if generation.is_video_generation:
                task = generate_video_task.delay(generation.id)
            else:
                task = generate_image_task.delay(generation.id)

            generation.task_id = task.id
            generation.save(update_fields=['task_id'])
            started_count += 1
            logger.info(f"Started generation #{generation.id}, task_id: {task.id}")

        return JsonResponse({
            'success': True,
            'started': started_count,
            'message': f'Started {started_count} generation(s)'
        })

    except Exception as e:
        logger.error(f"Error starting all generations: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def progress(request, generation_id):
    """Get progress for a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # LECTURE → accès nommé `visible_or_404` : le propriétaire OU un destinataire du
        # partage (unité/projet/public). Cf. common/utils/scoping.py — lecture/mutation.
        generation = visible_or_404(ImageGeneration, user, id=generation_id)

        # Get progress from cache (more real-time) or fallback to DB
        cached_progress = cache.get(f"imager_progress_{generation_id}")
        progress_value = cached_progress if cached_progress is not None else generation.progress

        data = {
            'id': generation.id,
            'status': generation.status,
            'progress': progress_value,
            'error_message': generation.error_message,
            'generated_images': generation.generated_images,
            'duration': generation.duration_display,
            'output_type': generation.output_type,
            'is_video': generation.is_video_generation,
        }

        # Include video URL if available
        if generation.output_video:
            data['output_video_url'] = generation.output_video.url

        # Seed ETA (chargement séparé → model_loaded=False inclut le coût à froid) :
        # image = steps × nb images, vidéo = durée produite. Clé par domaine+modèle.
        if generation.status in ('PENDING', 'RUNNING'):
            try:
                from wama.model_manager.services.eta_estimator import estimate
                if generation.is_video_generation:
                    data['estimated_seconds'] = estimate(
                        f'imager:vid:{generation.model}',
                        size=float(getattr(generation, 'video_duration', 0) or 0),
                        unit='video_sec', model_loaded=False)
                else:
                    _steps = int(getattr(generation, 'steps', 0) or 0) * int(getattr(generation, 'num_images', 1) or 1)
                    data['estimated_seconds'] = estimate(
                        f'imager:img:{generation.model}', size=max(_steps, 1),
                        unit='step', model_loaded=False)
            except Exception:
                pass

        return JsonResponse(data)

    # Un refus d'accès doit rester un 404 : sans ça l'`except Exception` ci-dessous le
    # transformait en 500 AVEC le message de la base dans le corps de la réponse.
    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error getting progress: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def global_progress(request):
    """Get overall progress split by image and video generations."""
    from django.db.models import Count, Case, When, IntegerField, Avg

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    VIDEO_MODES = ['txt2vid', 'img2vid']

    def _aggregate(qs):
        stats = qs.aggregate(
            total=Count('id'),
            pending=Count(Case(When(status='PENDING', then=1), output_field=IntegerField())),
            running=Count(Case(When(status='RUNNING', then=1), output_field=IntegerField())),
            success=Count(Case(When(status='SUCCESS', then=1), output_field=IntegerField())),
            failure=Count(Case(When(status='FAILURE', then=1), output_field=IntegerField())),
            avg_progress=Avg('progress'),
        )
        return {
            'total': stats['total'] or 0,
            'pending': stats['pending'] or 0,
            'running': stats['running'] or 0,
            'success': stats['success'] or 0,
            'failure': stats['failure'] or 0,
            'overall_progress': int(stats['avg_progress'] or 0),
        }

    try:
        base_qs = ImageGeneration.objects.filter(user=user)
        image_stats = _aggregate(base_qs.exclude(generation_mode__in=VIDEO_MODES))
        video_stats = _aggregate(base_qs.filter(generation_mode__in=VIDEO_MODES))

        return JsonResponse({
            # Legacy top-level keys (image stats, backward compat)
            **image_stats,
            # Split stats
            'image': image_stats,
            'video': video_stats,
        })

    except Exception as e:
        logger.error(f"Error getting global progress: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def download(request, generation_id):
    """Download generated images or video"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = visible_or_404(ImageGeneration, user, id=generation_id)   # LECTURE

        # Handle video download
        if generation.is_video_generation:
            if not generation.output_video:
                return HttpResponse("No video generated yet", status=404)

            video_path = generation.output_video.path
            if os.path.exists(video_path):
                return FileResponse(
                    open(video_path, 'rb'),
                    as_attachment=True,
                    filename=f"video_{generation.id}.mp4",
                    content_type='video/mp4'
                )
            return HttpResponse("Video file not found", status=404)

        # Handle image download
        if not generation.generated_images:
            return HttpResponse("No images generated yet", status=404)

        # If single image, return it directly
        if len(generation.generated_images) == 1:
            image_path = generation.generated_images[0]
            if os.path.exists(image_path):
                return FileResponse(open(image_path, 'rb'),
                                  as_attachment=True,
                                  filename=os.path.basename(image_path))

        # Multiple images - create zip
        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for image_path in generation.generated_images:
                if os.path.exists(image_path):
                    zip_file.write(image_path, os.path.basename(image_path))

        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="generation_{generation.id}.zip"'
        return response

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error downloading: {str(e)}")
        return HttpResponse(f"Error: {str(e)}", status=500)


@require_http_methods(["POST"])
def delete_generation(request, generation_id):
    """Delete a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = owned_or_404(ImageGeneration, user, id=generation_id)   # MUTATION

        # Sorties : `generated_images` est une LISTE de chemins (pas un FileField), donc
        # suppression directe — elle n'est jamais partagée (vidée à la duplication).
        for image_path in generation.generated_images:
            if os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception as e:
                    logger.warning(f"Failed to delete image {image_path}: {str(e)}")

        # FileFields → `safe_delete_file` : `duplicate_instance` PARTAGE les fichiers (il ne
        # les copie pas), donc supprimer le fichier d'une ligne casserait ses doublons. La
        # brique ne l'efface que si plus aucune autre ligne ne le référence.
        #   • reference_image / prompt_file : PARTAGÉS (non listés dans `clear_fields`) — ils
        #     n'étaient tout simplement JAMAIS supprimés, donc laissés à fuir sur le disque ;
        #   • output_video : vidé à la duplication aujourd'hui, mais on passe quand même par
        #     la brique — un `os.remove` brut redeviendrait faux au premier changement de
        #     `clear_fields`, sans que rien ne le signale.
        from wama.common.utils.queue_duplication import safe_delete_file
        for _champ in ('output_video', 'reference_image', 'prompt_file'):
            try:
                safe_delete_file(generation, _champ)
            except Exception as e:
                logger.warning(f"safe_delete_file({_champ}) a échoué : {e}")

        # Revoke Celery task if still queued/running
        if generation.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(generation.task_id).revoke(terminate=False)
            except Exception:
                pass

        generation.delete()
        logger.info(f"Deleted generation #{generation_id}")

        return JsonResponse({'success': True, 'message': 'Generation deleted'})

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error deleting generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def _schema_for(gen):
    """Schéma du DOMAINE de la génération (image | vidéo) — params.py est la source
    unique : vues de réglages, chips de card et modale ⚙ lisent le même objet."""
    from wama.imager.params import IMAGE_PARAMS_JSON, VIDEO_PARAMS_JSON
    return VIDEO_PARAMS_JSON if gen.is_video_generation else IMAGE_PARAMS_JSON


def _decorate_card(gen):
    """Chips schéma-driven du partial _generation_card (miroir anonymizer _decorate_card) :
    le schéma (params.py, chip=True) est la SOURCE, la card n'invente rien."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.imager.params import IMAGE_PARAMS_JSON, VIDEO_PARAMS_JSON
    gen.chips = chips_by_section(
        gen, VIDEO_PARAMS_JSON if gen.is_video_generation else IMAGE_PARAMS_JSON)
    return gen


def card_html(request, generation_id):
    """Partial d'UNE card (contrat card_html/refreshCard) — même rendu que la boucle de file,
    consommé par queue.js sur transition de statut (remplace le repaint DOM manuel)."""
    from django.template.loader import render_to_string
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    generation = visible_or_404(ImageGeneration, user, id=generation_id)   # LECTURE
    _decorate_card(generation)
    domain = 'video' if generation.is_video_generation else 'image'
    html = render_to_string('imager/_generation_card.html',
                            {'gen': generation, 'domain': domain}, request=request)
    return JsonResponse({'html': html, 'status': generation.status})


@require_http_methods(["POST"])
def batch_update(request, batch_id):
    """Applique des réglages à tous les items NON-RUNNING d'un batch (modale contexte 'batch').

    Comme la modale item : la coercition vient du SCHÉMA (params.py) — pas de liste de
    champs réécrite ici, qui serait une Nᵉ copie (le reader la maintient encore à la main).
    """
    from wama.common.utils.param_schema import coerce_schema_values
    from wama.imager.models import GenerationBatch

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batch = owned_or_404(GenerationBatch, user, pk=batch_id)   # MUTATION

    updated = 0
    for item in batch.items.select_related('generation').all():
        gen = item.generation
        if not gen or gen.status == 'RUNNING':
            continue
        values = coerce_schema_values(_schema_for(gen), request.POST)
        if not values:
            continue
        for field, value in values.items():
            setattr(gen, field, value)
        gen.save()
        updated += 1

    return JsonResponse({'success': True, 'updated': updated})


@require_http_methods(["POST"])
def duplicate_generation(request, generation_id):
    """Duplicate a generation (share reference_image, reset outputs)"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # `owned_or_404` : la duplication ne modifie pas la source, mais elle CRÉE un objet à
    # partir d'elle et partage son fichier de référence. Tant qu'`ObjectGrant` n'existe pas,
    # on s'en tient à la règle simple — le partage donne à VOIR, rien d'autre.
    generation = owned_or_404(ImageGeneration, user, id=generation_id)
    from wama.common.utils.queue_duplication import duplicate_instance
    new_gen = duplicate_instance(
        generation,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'error_message': '',
            'generated_images': [],
            'completed_at': None,
        },
        clear_fields=['output_video'],
    )
    return JsonResponse({'duplicated': new_gen.id})


@require_http_methods(["POST"])
def clear_all(request):
    """Clear all generations for the user"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generations = ImageGeneration.objects.filter(user=user)

        # Révocation Celery + fichiers. Même règle que `delete_generation` : les FileFields
        # passent par `safe_delete_file` (partage possible entre doublons), la liste de
        # chemins `generated_images` se supprime directement.
        from celery.result import AsyncResult
        from wama.common.utils.queue_duplication import safe_delete_file
        for generation in generations:
            if generation.task_id:
                try:
                    AsyncResult(generation.task_id).revoke(terminate=False)
                except Exception:
                    pass
            for image_path in generation.generated_images:
                if os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete image {image_path}: {str(e)}")
            for _champ in ('output_video', 'reference_image', 'prompt_file'):
                try:
                    safe_delete_file(generation, _champ)
                except Exception as e:
                    logger.warning(f"safe_delete_file({_champ}) a échoué : {e}")

        count = generations.count()
        generations.delete()
        logger.info(f"Cleared {count} generations for user {user.username}")

        return JsonResponse({'success': True, 'deleted': count})

    except Exception as e:
        logger.error(f"Error clearing all generations: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def download_all(request):
    """Download all generated images as a zip file"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generations = ImageGeneration.objects.filter(user=user, status='SUCCESS')

        if not generations.exists():
            return HttpResponse("No completed generations to download", status=404)

        import zipfile
        from io import BytesIO

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for generation in generations:
                for image_path in generation.generated_images:
                    if os.path.exists(image_path):
                        # Create a subfolder per generation
                        folder_name = f"generation_{generation.id}"
                        arcname = f"{folder_name}/{os.path.basename(image_path)}"
                        zip_file.write(image_path, arcname)

        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="imager_all_images.zip"'
        return response

    except Exception as e:
        logger.error(f"Error downloading all images: {str(e)}")
        return HttpResponse(f"Error: {str(e)}", status=500)


def console(request):
    """Console page for monitoring logs"""
    return render(request, 'imager/console.html')


def console_content(request):
    """Return console logs as JSON"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Get recent generations with their logs
        generations = ImageGeneration.objects.filter(user=user).order_by('-updated_at')[:10]

        logs = []
        for gen in generations:
            status_icon = {
                'PENDING': '⏳',
                'RUNNING': '🔄',
                'SUCCESS': '✅',
                'FAILURE': '❌',
            }.get(gen.status, '❓')

            log_line = f"{status_icon} [Gen #{gen.id}] {gen.status} - {gen.progress}% - {gen.prompt[:50]}..."
            logs.append(log_line)

            if gen.error_message:
                logs.append(f"   ❌ Error: {gen.error_message}")

        return JsonResponse({'output': logs})

    except Exception as e:
        logger.error(f"Error getting console content: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def about(request):
    """About page"""
    return render(request, 'imager/about.html')


def help_page(request):
    """Help page"""
    return render(request, 'imager/help.html')


# RETIRÉ 2026-08-06 — `update_settings` était le SEUL écrivain du modèle `UserSettings`, et
# n'était appelé depuis aucun JS ni template (0 occurrence de `update-settings` dans l'app).
# Les réglages utilisateur passent désormais par la brique commune
# `common/utils/user_settings.py`, écrits À LA CRÉATION (patron transcriber) : garder cet
# endpoint aurait maintenu un second chemin d'écriture contradictoire.


def get_generation_settings(request, generation_id):
    """Get settings for a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = visible_or_404(ImageGeneration, user, id=generation_id)   # LECTURE

        # Valeurs DÉRIVÉES DU SCHÉMA (params.py = source unique) : le dict écrit à la main
        # était une 2ᵉ copie du schéma, qui dérivait à chaque champ ajouté.
        schema = _schema_for(generation)
        data = {p['name']: getattr(generation, p['name'], None) for p in schema}
        data.update({
            'id': generation.id,
            'generation_mode': generation.generation_mode,
            'status': generation.status,
            # Champ prompt à DEUX ÉTATS ([[wama-prompt-enrich]]) : `prompt` reste ce que
            # l'utilisateur a tapé, `prompt_processed` ce qui part au modèle. L'UI affiche le
            # second et permet de revenir au premier — d'où l'envoi des deux.
            'prompt': generation.prompt,
            'prompt_processed': generation.prompt_processed or '',
            'prompt_keywords': generation.prompt_keywords or [],
            'prompt_trace': generation.prompt_trace or {},
            'auto_prompt': generation.auto_prompt or '',
            # HORS schéma (widgets d'app) : résolution image à présets + aperçu de référence.
            'width': generation.width,
            'height': generation.height,
            'reference_image_url': generation.reference_image.url if generation.reference_image else None,
        })

        return JsonResponse(data)

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error getting generation settings: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def save_generation_settings(request, generation_id):
    """Save settings for a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = owned_or_404(ImageGeneration, user, id=generation_id)   # MUTATION

        # Don't allow editing while running
        if generation.status == 'RUNNING':
            return JsonResponse({'error': 'Cannot edit a running generation'}, status=400)

        # Update fields from POST data
        if 'prompt' in request.POST:
            prompt = request.POST.get('prompt', '').strip()
            if not prompt:
                return JsonResponse({'error': 'Prompt is required'}, status=400)
            # Champ à DEUX ÉTATS : l'arbitrage « dans quel champ écrire » est une brique
            # COMMUNE (`apply_prompt_state`) — il était réimplémenté ici le 30/07, ce qui
            # aurait obligé chaque app à le recopier.
            from wama.common.utils.app_metadata import apply_prompt_state
            apply_prompt_state(generation, 'prompt', prompt,
                               request.POST.get('prompt_state'))

        # Reste des champs : coercition PAR LE SCHÉMA (types + bornes déclarés dans
        # params.py). Les 13 blocs `if ... int()/float()` qui vivaient ici étaient une
        # 3ᵉ copie du schéma — chaque champ ajouté demandait de les éditer aussi.
        from wama.common.utils.param_schema import coerce_schema_values
        for field, value in coerce_schema_values(_schema_for(generation), request.POST).items():
            setattr(generation, field, value)

        # Seed VIDE = aléatoire : la coercition ignore les champs vides, il faut donc
        # remettre None explicitement (sinon l'ancienne graine survivrait).
        if request.POST.get('seed', None) == '':
            generation.seed = None

        # HORS schéma : résolution image (widget à présets par modèle).
        for _f in ('width', 'height'):
            if request.POST.get(_f):
                setattr(generation, _f, int(request.POST[_f]))

        generation.save()

        logger.info(f"Updated settings for generation #{generation.id}")

        return JsonResponse({
            'success': True,
            'message': 'Settings saved successfully'
        })

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error saving generation settings: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def api_model_resolutions(request):
    """
    API endpoint to get recommended resolutions for a model.

    GET /imager/api/model-resolutions/?model=hunyuan-image-2.1

    Returns:
        {
            "model": "hunyuan-image-2.1",
            "config": {
                "min_size": 1024,
                "max_size": 2048,
                "default": "2048x2048",
                "vram_warning": "...",
            },
            "resolutions": [
                {"key": "2048x2048", "width": 2048, "height": 2048, "label": "...", "ratio": "1:1"},
                ...
            ]
        }
    """
    from .models import (
        get_model_resolution_config,
        get_recommended_resolutions,
        IMAGE_RESOLUTION_PRESETS
    )

    model_name = request.GET.get('model', DEFAULT_IMAGE_MODEL)

    config = get_model_resolution_config(model_name)
    resolutions = get_recommended_resolutions(model_name)

    # Pull model-specific defaults (guidance, steps) from backend
    default_guidance_scale = 7.5
    default_steps = 30
    try:
        from .backends.diffusers_backend import DiffusersBackend
        model_info = DiffusersBackend.SUPPORTED_MODELS.get(model_name, {})
        if isinstance(model_info, dict):
            default_guidance_scale = model_info.get('default_guidance_scale', 7.5)
            default_steps = model_info.get('default_steps', 30)
    except Exception:
        pass

    return JsonResponse({
        'model': model_name,
        'config': config,
        'resolutions': resolutions,
        'all_presets': IMAGE_RESOLUTION_PRESETS,
        # Flattened for JS compatibility
        'recommended': [r['key'] for r in resolutions],
        'default': config.get('default', '512x512'),
        'vram_warning': config.get('vram_warning', ''),
        'default_guidance_scale': default_guidance_scale,
        'default_steps': default_steps,
    })


@require_http_methods(["GET"])
def api_all_resolutions(request):
    """
    API endpoint to get all available resolution presets.

    GET /imager/api/resolutions/

    Returns all resolution presets grouped by ratio.
    """
    from .models import IMAGE_RESOLUTION_PRESETS

    # Group by ratio
    by_ratio = {}
    for key, preset in IMAGE_RESOLUTION_PRESETS.items():
        ratio = preset['ratio']
        if ratio not in by_ratio:
            by_ratio[ratio] = []
        by_ratio[ratio].append({'key': key, **preset})

    return JsonResponse({
        'presets': IMAGE_RESOLUTION_PRESETS,
        'by_ratio': by_ratio,
    })


@require_http_methods(["POST"])
def force_reset_generation(request, generation_id):
    """
    Force reset a stuck generation's status to FAILURE.
    This allows the user to restart a generation that got stuck in RUNNING state.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = owned_or_404(ImageGeneration, user, id=generation_id)   # MUTATION

        old_status = generation.status
        old_task_id = generation.task_id

        # Revoke the Celery task so it won't be picked up / re-executed after restart
        if old_task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(old_task_id).revoke(terminate=True, signal='SIGTERM')
                logger.info(f"Revoked Celery task {old_task_id} for generation #{generation.id}")
            except Exception as e:
                logger.warning(f"Could not revoke task {old_task_id}: {e}")

        # Reset status to FAILURE and clear task_id
        generation.status = 'FAILURE'
        generation.progress = 0
        generation.task_id = ''
        generation.error_message = f"Génération réinitialisée manuellement (ancien statut: {old_status})"
        generation.save()

        # Clear progress cache
        cache.delete(f"imager_progress_{generation_id}")

        logger.info(f"Force reset generation #{generation.id} from {old_status} to FAILURE")

        return JsonResponse({
            'success': True,
            'old_status': old_status,
            'new_status': 'FAILURE',
            'message': 'Generation reset to FAILURE. You can now restart it.'
        })

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error force resetting generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
