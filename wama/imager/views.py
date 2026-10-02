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
from django.utils.http import content_disposition_header
import os
import json
import logging
from pathlib import Path

from wama.accounts.permissions import app_access
from wama.common.utils.queue_manipulation import make_queue_manipulation_views
from wama.common.utils.scoping import owned_or_404, visible_or_404
from .models import GenerationBatch, GenerationBatchItem, ImageGeneration
from .utils.model_config import (
    DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, DEFAULT_I2V_MODEL, get_model_defaults,
)
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


def _qm_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


# Champs remis à zéro par TOUTE duplication de génération — élément (`duplicate_generation`)
# comme lot (`batch_duplicate`). Une seule liste : deux copies auraient divergé au premier
# champ de sortie ajouté, et le doublon d'un lot serait reparti avec les images de l'original.
_RESET_DUPLICATION = {
    'status': 'PENDING',
    'progress': 0,
    'task_id': '',
    'error_message': '',
    'generated_images': [],
    'completed_at': None,
}


def _batch_domain(gen):
    """Champs du BATCH dérivés de la génération — l'imager scope sa file par onglet.
    Passé en `batch_extra` aux briques communes (auto_wrap_orphans, fabrique de
    manipulation) : c'est ce qui évite qu'une vidéo isolée atterrisse dans l'onglet Images."""
    return {'domain': 'video' if gen.is_video_generation else 'image'}


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

    # NOTE PARTAGE — ⚠ PÉRIMÉE jusqu'au 2026-10-02, corrigée ce jour-là À LA MESURE : elle disait
    # l'imager « propriétaire-seul » parce que « 10 autres sites filtrent encore `user=user` ». Ces
    # chemins de LECTURE sont portés depuis (`progress`, `download`, `card_html`, réglages, enfants
    # de lot passent par `visible_or_404`), et la FILE est bâtie plus bas sur `build_batches_list`,
    # qui lit `visible_to` sur `GenerationBatch` : une card partagée y apparaît déjà chez le
    # destinataire (mesuré par `ReceivedCardsAppearInTheQueueTest`, vert sur l'imager). La liste
    # ci-dessous ne sert qu'au contexte ; elle reste celle du PROPRIÉTAIRE.
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

    # ⚠ LISTE DE MODÈLES : plus rien ici (route F4b, 2026-09-29). La page construisait la liste
    # depuis `DiffusersBackend.SUPPORTED_MODELS`, l'ENRICHISSAIT du catalogue « sans jamais
    # masquer » (« Verrou n°1 »), en tirait des groupes Images/Logos/Vidéos pour un remplissage
    # JS propre à l'imager — et un repli de trois modèles en dur. Les deux selects déclarent
    # désormais `options_source: "catalog"` (params.py) : le catalogue EST la liste, bornée par
    # la tâche, et un modèle installé depuis le model manager y entre sans code.

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

    # ── Card d'entrée commune (une instance PAR DOMAINE) ─────────────────────────
    from wama.imager.params import (
        IMAGE_GROUPS_JSON, IMAGE_PARAMS_JSON, VIDEO_GROUPS_JSON, VIDEO_PARAMS_JSON,
    )

    # Meta d'appariement : brique COMMUNE (common/utils/input_match.py), en mode TÂCHE (route F4b,
    # 2026-09-29) — les MÊMES domaines que les options des deux selects (params.py), donc les
    # MÊMES clés entières. Par `source='imager'` elle rendait des ids nus et ignorait tout
    # modèle d'une autre source : `WamaInputMatch` n'aurait rien apparié, sans le dire.
    from wama.common.utils.input_match import (
        auto_entry, input_labels as _im_labels, input_match_meta as _im_meta,
    )
    input_match_meta = {**_im_meta(task='text-to-image,image-to-image'),
                        **_im_meta(task='text-to-video,image-to-video')}
    input_labels = _im_labels()
    # Pseudo-modèle « Auto » : il n'est PAS au catalogue, donc sans cette union il n'accepte
    # RIEN — et une entrée fournie le désactivait, alors que c'est justement le cas où il sert
    # (mesuré au navigateur le 2026-08-24 : déposer une image de référence grisait « Auto »
    # dans les DEUX domaines, forçant un choix manuel de moteur). Même politique que le
    # composer (`views.py::_input_match_meta`) : l'auto accepte ce qu'accepte AU MOINS UN
    # candidat, la résolution au lancement (`utils/auto_model.py`) restreignant ensuite.
    # ⚠ Union GLOBALE et non par domaine : l'imager n'expose qu'UN id `auto`, partagé par ses
    # deux selects (ceux du VOLET depuis le 2026-09-28 : `#model`/`#panel_video_model` — la card
    # d'entrée n'en porte plus, CARD_DESIGN §11.11 Étape 3 (c)). Une union par domaine supposerait deux
    # ids distincts — à faire le jour où une entrée serait acceptée par un modèle vidéo et par
    # aucun modèle image (aucun cas aujourd'hui : `work_image` est accepté des deux côtés).
    # Brique `auto_entry` (même politique que l'union locale qu'elle remplace, le 2026-09-29).
    if input_match_meta:
        input_match_meta['auto'] = auto_entry(input_match_meta)

    # ── File bâtie sur les BATCHS (contrat commun) ───────────────────────────────
    # Tout est batch ; une génération isolée est auto-enveloppée dans son batch-of-1
    # (c'est aussi ce qui la rend PARTAGEABLE — le batch est l'unité de partage).
    from wama.common.utils.batch_common import auto_wrap_orphans, build_batches_list
    from wama.common.utils.queue_view import apply_queue_sort_filter
    from wama.imager.models import GenerationBatch, GenerationBatchItem

    # `batch_extra` porte le DOMAINE sur le batch créé (la file de l'imager est scopée par
    # onglet). Remplace un `wrap_group` maison qui ne faisait que réimplémenter la boucle par
    # défaut du commun pour poser ce seul champ — même mécanisme que converter, qui pose
    # `media_type` de la même façon.
    auto_wrap_orphans(user, work_model=ImageGeneration, batch_model=GenerationBatch,
                      item_model=GenerationBatchItem, fk_name='generation',
                      batch_extra=_batch_domain)

    from wama.common.utils.card_chips import common_chips_for_items
    from wama.imager.params import IMAGE_PARAMS_JSON, VIDEO_PARAMS_JSON
    batches_all = build_batches_list(
        user, batch_model=GenerationBatch, work_attr='generation',
        # Réglages COMMUNS aux filles (slot meta_template — porté le 31/08) : imager a
        # DEUX schémas, celui du DOMAINE du lot s'applique (fabrique scopée par onglet).
        extra=lambda b, items, gens: {
            'common_chips': common_chips_for_items(
                gens, VIDEO_PARAMS_JSON if getattr(b, 'domain', '') == 'video'
                else IMAGE_PARAMS_JSON)})
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
        'image_modes': image_modes,
        'video_modes': video_modes,
        'generation_modes': image_modes,  # Keep for backward compatibility
        # Méta d'appariement de la card d'entrée (les OPTIONS des selects de modèle viennent du
        # catalogue par WamaParams — route F4b, plus de groupes construits ici).
        'input_match_meta': json.dumps(input_match_meta),
        'input_labels': json.dumps(input_labels),
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

        # Réglages user — écriture À LA CRÉATION (patron transcriber, brique A5-22) : les
        # valeurs du volet voyagent avec le POST de la card, on les persiste ICI, au point de
        # routage unique. Il n'existe aucun endpoint « enregistrer le volet » dans les apps
        # portées. Sans cette écriture, get_user_app_settings ne rend que les défauts et le
        # volet oublie tout réglage au rechargement.
        from wama.common.utils.user_settings import save_user_app_settings
        from .params import IMAGE_PARAMS, VIDEO_PARAMS, panel_prefs_from_post
        _params = VIDEO_PARAMS if generation_mode in ('txt2vid', 'img2vid') else IMAGE_PARAMS
        _prefs = panel_prefs_from_post(request.POST, _params)
        if _prefs:
            save_user_app_settings(user, 'imager', _prefs)

        # Route to appropriate handler
        if generation_mode == 'file2img':
            response = handle_file2img(request, user)
        elif generation_mode == 'describe2img':
            response = handle_describe2img(request, user)
        elif generation_mode in ('style2img', 'img2img'):
            response = handle_img2img(request, user, generation_mode)
        elif generation_mode == 'txt2vid':
            response = handle_txt2vid(request, user)
        elif generation_mode == 'img2vid':
            response = handle_img2vid(request, user)
        else:
            # Default: txt2img mode
            response = handle_txt2img(request, user)
        _apply_posted_output(response, request.POST, _params)
        return response

    except Exception as e:
        logger.error(f"Error creating generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


def _apply_posted_output(response, post, params):
    """Le FORMAT DE SORTIE posté au dépôt, appliqué à ce que le dépôt a créé — pour TOUS les modes.

    Seul `handle_txt2img` le lisait : les cinq autres routes (lot, description, img2img, les deux
    vidéo) créaient la génération sans lui, et le choix fait sur la card tombait (relevé le
    2026-09-23, question de Fabien sur la sortie vidéo). Lu ici, au point de routage UNIQUE, par
    la coercition du SCHÉMA — les champs de la brique commune, pas une liste recopiée.
    """
    if getattr(response, 'status_code', 500) != 200:
        return
    from wama.common.utils.output_formats import OUTPUT_PARAM_NAMES
    from wama.common.utils.param_schema import coerce_schema_values
    output_params = [p for p in params if p.name in OUTPUT_PARAM_NAMES]
    allowed = {p.name: {str(c[0]) for c in (p.choices or [])} for p in output_params}
    # Une valeur hors des choix du DOMAINE est ignorée (un « webp » d'image posté pour une vidéo).
    values = {k: v for k, v in coerce_schema_values(output_params, post).items()
              if str(v) in allowed.get(k, ())}
    if not values:
        return
    try:
        payload = json.loads(response.content or b'{}')
    except ValueError:
        return
    ids = payload.get('children_ids') or ([payload['generation_id']]
                                          if payload.get('generation_id') else [])
    if ids:
        ImageGeneration.objects.filter(pk__in=ids).update(**values)


# Curseur POSTÉ (chantier C) : lecteur COMMUN — None quand il n'est pas posté. La copie locale
# (identique chez composer et enhancer) est remontée dans la brique le 2026-09-21.
from wama.common.utils.auto_model import posted_quality_intent as _intent_posted  # noqa: E402


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
    # L'agrandissement de sortie (`output_upscale`) arrive avec les autres réglages de SORTIE,
    # par `_apply_posted_output` (brique commune) — plus un booléen lu ici.

    # Create generation object
    generation = ImageGeneration.objects.create(
        user=user,
        generation_mode='txt2img',
        prompt=prompt,
        negative_prompt=negative_prompt,
        model=model,
        quality_intent=_intent_posted(request.POST),
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        num_images=num_images,
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


def creer_lot_de_prompts(chemin, nom_fichier, user, *, domain='image', reglages=None,
                         app_label='imager'):
    """Crée le LOT depuis un fichier de prompts déjà sur disque — cœur SANS `request`.

    Extrait de `handle_file2img` le 2026-09-10, quand une TROISIÈME entrée s'est présentée :
    le gestionnaire de fichiers (« Envoyer vers Imager » d'un .txt). Les deux premières — la
    card historique et la barre de détection commune — étaient déjà réconciliées derrière
    `handle_file2img` ; la troisième ne pouvait pas l'être, parce que ce point d'entrée lit
    `request.FILES`. Elle avait donc sa propre voie : un `ImageGeneration` PLACEHOLDER en
    `file2img`, portant le fichier dans le champ `prompt_file`, avec la promesse — écrite dans
    `filemanager/views.py` — que « le batch sera créé quand l'utilisateur ouvrira l'Imager ».
    Personne ne le créait. Mesuré avant le portage : **0 génération avec `prompt_file` rempli**.

    C'est le motif que la doctrine nomme : la divergence de nommage (`prompt_file` vs
    `batch_file`) était la trace d'une brique absente. Le lot est un GESTE commun — décision
    Fabien 05/09, « le LOT n'a pas de port, c'est le GESTE qui le crée » — et il n'a donc pas
    à exister en deux implémentations selon la porte d'entrée.

    Args:
        chemin        : fichier de prompts sur disque (str | Path).
        nom_fichier   : nom d'origine, conservé sur `batch_file` du lot.
        reglages      : dict optionnel (model/width/height/steps/guidance_scale + vidéo).
        app_label     : re-cible une JUMELLE de bac à sable (`imager_01`) — contrat
                        `importer_for()`, identique à celui de `import_to_imager`.
    Returns:
        (batch, generations) — ou (None, []) si le fichier ne contient aucun prompt valide.

    ⚠ Les modèles se résolvent PAR `app_label`, jamais par import direct. Ma première version
    importait `ImageGeneration`/`GenerationBatch` en dur : elle créait donc le lot dans l'app
    RÉELLE même appelée pour la jumelle, et `imager_01.send_to` est sorti rouge avec le seul
    symptôme possible — « requête acceptée (200) mais AUCUN élément n'apparaît ». Le code
    d'origine résolvait dynamiquement (`django_apps.get_model(app_label, …)`) précisément pour
    ça ; l'extraction avait perdu ce contrat en route.
    """
    from django.apps import apps as django_apps

    from .utils.prompt_parser import parse_prompt_file, validate_prompt_config
    from wama.common.utils.batch_common import consolidate_into_batch

    ImageGeneration = django_apps.get_model(app_label, 'ImageGeneration')
    GenerationBatch = django_apps.get_model(app_label, 'GenerationBatch')
    GenerationBatchItem = django_apps.get_model(app_label, 'GenerationBatchItem')

    r = dict(reglages or {})
    model = r.get('model') or 'auto'
    _def = get_model_defaults(model)
    # Le curseur rapide/qualité (chantier C) n'existe que sur le modèle RÉEL : une jumelle bac à
    # sable régénérée avant ce champ n'en a pas — on ne pose la clé que si la colonne existe.
    _has_intent = any(getattr(f, 'name', None) == 'quality_intent'
                      for f in ImageGeneration._meta.get_fields())
    width = int(r.get('width', _def['width']))
    height = int(r.get('height', _def['height']))
    steps = int(r.get('steps', _def['steps']))
    guidance_scale = float(r.get('guidance_scale', _def['guidance_scale']))
    domain = 'video' if domain == 'video' else 'image'
    mode = 'txt2vid' if domain == 'video' else 'txt2img'
    video_kwargs = {}
    if domain == 'video':
        video_kwargs = {
            'video_duration': float(r.get('video_duration', 5.0)),
            'video_fps': int(r.get('video_fps', 16)),
            'video_resolution': r.get('video_resolution', '480p'),
        }

    prompts = parse_prompt_file(str(chemin))
    if not prompts:
        return None, []

    generations = [
        ImageGeneration.objects.create(
            user=user,
            generation_mode=mode,
            prompt=v.get('prompt', ''),
            negative_prompt=v.get('negative_prompt', ''),
            model=v.get('model', model),
            **({'quality_intent': _intent_posted(
                {'quality_intent': v.get('quality_intent', r.get('quality_intent'))})}
               if _has_intent else {}),
            width=v.get('width', width),
            height=v.get('height', height),
            steps=v.get('steps', steps),
            guidance_scale=v.get('guidance_scale', guidance_scale),
            seed=v.get('seed'),
            num_images=v.get('num_images', 1),
            status='PENDING',
            **video_kwargs,
        )
        for v in (validate_prompt_config(p) for p in prompts)
    ]

    def _create_batch(total):
        b = GenerationBatch.objects.create(user=user, domain=domain, total=total)
        # Le fichier de prompts vit sur le BATCH (champ prévu pour, models.py:445) et non sur
        # un faux item : il est partagé par les lignes et nettoyé par BatchMixin.
        from django.core.files import File
        with open(chemin, 'rb') as fh:
            b.batch_file.save(nom_fichier, File(fh))
        return b

    batch = consolidate_into_batch(
        generations,
        create_batch=_create_batch,
        link_item=lambda b, g, idx: GenerationBatchItem.objects.create(
            batch=b, generation=g, row_index=idx),
    )
    return batch, generations


def handle_file2img(request, user):
    """Handle batch generation from prompt file (txt/json/yaml) — ADAPTATEUR de requête.

    Ne fait plus que lire la requête et déléguer à `creer_lot_de_prompts` (le cœur commun).
    """
    # `batch_file` = nom de champ du contrat WamaBatchImport ; `prompt_file` = nom historique
    # posté par la card. UNE seule implémentation de création sert les deux entrées.
    prompt_file = request.FILES.get('prompt_file') or request.FILES.get('batch_file')
    if not prompt_file:
        return JsonResponse({'error': 'No prompt file provided'}, status=400)
    from wama.common.utils.batch_parsers import batch_file_refusal
    refusal = batch_file_refusal(prompt_file.name, extra=('json', 'yaml', 'yml'))
    if refusal:
        return JsonResponse({'error': refusal}, status=400)

    # Défauts SOURCÉS depuis la déclaration du modèle (model_config), jamais en dur : 512x512 /
    # 30 étapes / guidance 7.5 sont les valeurs de l'ère SD 1.5 et dégradent tout modèle 1024 px
    # en rectified flow (Qwen, FLUX). On ENREGISTRE le choix (ou 'auto') — le tirage a lieu au
    # LANCEMENT, où la VRAM libre est celle du moment. Résoudre ici serait périmé.
    #
    # DOMAINE du lot (2026-09-08, décision Fabien : « je ne vois pas de raison de ne pas
    # permettre de fichier batch dans le domaine vidéo »). Il est DÉCLARÉ par l'appelant (card
    # vidéo, studio) ; les réglages vidéo suivent le patron de `handle_text_to_video`.
    reglages = {k: request.POST[k] for k in
                ('model', 'quality_intent', 'width', 'height', 'steps', 'guidance_scale',
                 'video_duration', 'video_fps', 'video_resolution')
                if request.POST.get(k) not in (None, '')}
    domain = request.POST.get('domain') or 'image'

    # Save file temporarily to parse it
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(prompt_file.name).suffix) as tmp:
        for chunk in prompt_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        batch, generations = creer_lot_de_prompts(
            tmp_path, prompt_file.name, user, domain=domain, reglages=reglages)
        if batch is None:
            return JsonResponse({'error': 'No valid prompts found in file'}, status=400)

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


def _reference_image(request, user):
    """L'image de RÉFÉRENCE reçue par le port — téléversée ou DÉSIGNÉE (médiathèque, arbre),
    brique `received_inputs` (2026-09-28) : une désignation se POINTE. Rend `(reçue, refus)`."""
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'imager', field='reference_image',
                               subfolder='input/references')
    return (received[0] if received else None), received.refusal


def handle_describe2img(request, user):
    """Handle describe-to-image: auto-generate prompt from reference image using BLIP"""
    reference_image, refusal = _reference_image(request, user)
    if not reference_image:
        return JsonResponse({'error': refusal or 'No reference image provided'}, status=400)

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
        quality_intent=_intent_posted(request.POST),
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        status='PENDING'
    )
    reference_image.assign(generation, 'reference_image')

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
    """Handle img2img and style2img: image-to-image transformation.

    Référence par FICHIER ou par URL (WAMA_INGEST, contrat composer 307b9fb) : un fichier
    joint PRIME ; sinon `source_url` est téléchargée EN TÊTE DE TÂCHE par ensure_local_input.
    """
    reference_image, refusal = _reference_image(request, user)
    source_url = request.POST.get('source_url', '').strip()
    if not reference_image and not source_url:
        return JsonResponse({'error': refusal or 'No reference image provided'}, status=400)

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
        quality_intent=_intent_posted(request.POST),
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        num_images=num_images,
        image_strength=image_strength,
        source_url=source_url,
        status='PENDING'
    )
    if reference_image:
        reference_image.assign(generation, 'reference_image')

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
        quality_intent=_intent_posted(request.POST),
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
    """Handle image-to-video generation.

    Référence par FICHIER ou par URL (WAMA_INGEST) — même contrat que handle_img2img.
    """
    reference_image, refusal = _reference_image(request, user)
    source_url = request.POST.get('source_url', '').strip()
    if not reference_image and not source_url:
        return JsonResponse({'error': refusal or 'Reference image is required'}, status=400)

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
        quality_intent=_intent_posted(request.POST),
        video_duration=video_duration,
        video_fps=video_fps,
        video_resolution=video_resolution,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        source_url=source_url,
        status='PENDING'
    )
    if reference_image:
        reference_image.assign(generation, 'reference_image')

    logger.info(f"Created img2vid generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'generation_id': generation.id,
        'message': 'Image-to-video generation created successfully'
    })


@require_http_methods(["POST"])
def generate_auto_prompt(request):
    """Generate prompt from uploaded image using BLIP (AJAX endpoint)"""
    reference_image, refusal = _reference_image(request, _qm_user(request))
    if not reference_image:
        return JsonResponse({'error': refusal or 'No image provided'}, status=400)

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
    # Le FORMAT reste un contrat (2026-09-30) : `parse_prompt_file` lisait une image comme du texte.
    from wama.common.utils.batch_parsers import batch_file_refusal
    refusal = batch_file_refusal(batch_file.name, extra=('json', 'yaml', 'yml'))
    if refusal:
        return JsonResponse({'error': refusal}, status=400)

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
        from wama.common.utils.batch_common import batch_elements
        children = batch_elements(batch, ImageGeneration)   # brique : ordre des lignes garanti

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


# ── Trois vues de lot par la fabrique COMMUNE (`batch_views.make_batch_views`, portage
# 2026-09-23, 7ᵉ app réelle — ROUTE §11 #36 ; les routes passent de `<int:batch_id>` à
# `<int:pk>`, dernière graphie déviante). Spécificités DÉCLARÉES en kwargs : ▶ de lot ne lance
# que les PENDING (contrat WamaBatchImport, comme le composer) ; la tâche se choisit PAR
# élément (image ou vidéo, `is_video_generation`) ; le cache de progression s'oublie au
# démarrage et à la suppression (`_forget_progress`) ; les fichiers de la génération — ses
# trois champs fichier ET ses images (`generated_images`, liste de chemins déclarée à la
# rétention) — sont LIBÉRÉS par la fabrique (`release_card_files`), rien n'est effacé ; le lot
# copié garde son `domain` (l'onglet). `batch_update` (un schéma PAR élément, image ou vidéo) et
# `get_batch_children` (lecture PARTAGÉE) restent locaux, assumés, lus par `batch_elements`.
from wama.common.utils.batch_views import make_batch_views


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _task_for(gen):
    from .tasks import generate_image_task, generate_video_task
    return generate_video_task if gen.is_video_generation else generate_image_task


def _forget_progress(gen):
    cache.delete(f"imager_progress_{gen.id}")


def _reset_and_forget_progress(gen):
    gen.progress = 0
    gen.error_message = ''
    _forget_progress(gen)


_bv = make_batch_views(
    work_model=ImageGeneration, batch_model=GenerationBatch, get_user=_get_user,
    task_for=_task_for, start_only_pending=True,
    output_fields=('output_video',),
    item_model=GenerationBatchItem, fk_name='generation',
    reset_on_start=_reset_and_forget_progress,
    reset_on_duplicate=_RESET_DUPLICATION,
    batch_extra=lambda lot: {'domain': lot.domain},
    on_delete=_forget_progress,
)
batch_start = _bv['batch_start']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']


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
                from wama.common.utils.model_keys import model_id as _model_id
                # Même clé que l'apprentissage (`tasks.py`, record_run) : par IDENTIFIANT.
                _mid = _model_id(generation.model)
                if generation.is_video_generation:
                    data['estimated_seconds'] = estimate(
                        f'imager:vid:{_mid}',
                        size=float(getattr(generation, 'video_duration', 0) or 0),
                        unit='video_sec', model_loaded=False)
                else:
                    _steps = int(getattr(generation, 'steps', 0) or 0) * int(getattr(generation, 'num_images', 1) or 1)
                    data['estimated_seconds'] = estimate(
                        f'imager:img:{_mid}', size=max(_steps, 1),
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
        response['Content-Disposition'] = content_disposition_header(True, f"generation_{generation.id}.zip")
        return response

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error downloading: {str(e)}")
        return HttpResponse(f"Error: {str(e)}", status=500)


def _purger_generation(generation):
    """Fichiers et tâche Celery d'UNE génération, puis la ligne — le retrait de « Supprimer »
    comme de « Tout effacer » (le lot passe par la fabrique, qui fait le même geste).

    Les fichiers sont LIBÉRÉS par la brique, à l'échelle de la card (`release_card_files`,
    2026-10-01) : ses champs fichier ET ses images (`generated_images`, liste de chemins
    déclarée à la rétention). Jusque-là les images étaient effacées ici par un `os.remove`,
    sans règle de propriété ni de partage, pendant que la vidéo était libérée — le reste que
    la décision D34 de `MEDIA_STORAGE_TIERING` avait laissé. `duplicate_instance` PARTAGE les
    fichiers d'entrée : la brique ne libère que ce que plus aucune ligne ne désigne.
    """
    _forget_progress(generation)
    from wama.common.utils.queue_duplication import release_card_files
    release_card_files(generation)

    # Revoke Celery task if still queued/running
    if generation.task_id:
        try:
            from celery.result import AsyncResult
            AsyncResult(generation.task_id).revoke(terminate=False)
        except Exception:
            pass

    generation.delete()


@require_http_methods(["POST"])
def delete_generation(request, generation_id):
    """Delete a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = owned_or_404(ImageGeneration, user, id=generation_id)   # MUTATION
        # Lot de l'élément, relevé AVANT la purge — brique commune (`batch_common`).
        from wama.common.utils.batch_common import batch_snapshot, batch_state
        snapshot = batch_snapshot(generation)
        _purger_generation(generation)
        logger.info(f"Deleted generation #{generation_id}")

        return JsonResponse({'success': True, 'message': 'Generation deleted',
                             'batch': batch_state(snapshot, ImageGeneration)})

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
    consommé par queue.js sur transition de statut (remplace le repaint DOM manuel).

    ⚠ Répond du HTML, comme les 9 autres vues `card_html` (2026-09-15). L'imager était seul à
    répondre `{'html', 'status'}` en JSON : une brique commune qui rend une card sans
    rechargement de la page ne pouvait donc pas le servir sans une lecture à part pour lui —
    et `status` n'avait aucun lecteur (`queue.js` ne lisait que `html`)."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from wama.common.utils.batch_common import is_batch_child
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    generation = visible_or_404(ImageGeneration, user, id=generation_id)   # LECTURE
    _decorate_card(generation)
    domain = 'video' if generation.is_video_generation else 'image'
    html = render_to_string('imager/_generation_card.html',
                            {'elem': generation, 'domain': domain,
                             'in_batch': is_batch_child(generation)}, request=request)
    return HttpResponse(html)


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

    from wama.common.utils.batch_common import batch_elements
    updated = 0
    for gen in batch_elements(batch, ImageGeneration):     # brique : ordre des lignes garanti
        if gen.status == 'RUNNING':
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
    # `duplicable_or_404` (2026-10-01, `WAMA_COLLABORATION §3bis`) : dupliquer ne modifie pas la
    # source — on duplique tout ce qu'on peut VOIR ; la copie d'une card reçue est À SOI
    # (propriétaire, privée, fichiers copiés chez soi : `duplicate_instance(for_user=…)`).
    from wama.common.utils.scoping import duplicable_or_404
    generation = duplicable_or_404(ImageGeneration, user, id=generation_id)
    from wama.common.utils.queue_duplication import duplicate_instance
    new_gen = duplicate_instance(generation, reset_fields=_RESET_DUPLICATION,
                                 clear_fields=['output_video'], for_user=user)
    return JsonResponse({'duplicated': new_gen.id})


# ── Manipulation directe de la file (fabrique COMMUNE, patron des 8 autres apps) ──────────
# Sortir un élément de son batch, réordonner, déplacer vers un autre batch, consolider.
# `batch_extra` porte le DOMAINE sur le batch créé par `remove_from_batch` — sans lui, une
# vidéo isolée de son batch repartirait avec le défaut du modèle ('image') et changerait
# d'onglet. Converter fait exactement pareil avec `media_type` (variante FK-directe).
_qm = make_queue_manipulation_views(
    work_model=ImageGeneration, batch_model=GenerationBatch,
    item_model=GenerationBatchItem, fk_name='generation',
    get_user=_qm_user,
    batch_extra=_batch_domain,
)
remove_from_batch = _qm['remove_from_batch']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
consolidate = _qm['consolidate']


@require_http_methods(["POST"])
def clear_all(request):
    """Clear all generations for the user"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # La MÊME suppression que `delete_generation`, N fois (fichiers libérés, tâche révoquée,
        # ligne) — elle était recopiée ici, et la copie effaçait les images à la main.
        generations = list(ImageGeneration.objects.filter(user=user))
        for generation in generations:
            _purger_generation(generation)
        count = len(generations)
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


@require_http_methods(["GET", "POST"])
def generation_settings(request, pk):
    """Réglages d'UN élément à l'adresse conventionnelle `settings/<pk>/` (2026-09-29) : GET les
    LIT (`get_generation_settings`), POST les ENREGISTRE (`update_settings`). Les deux vues
    vivaient à deux adresses, l'écriture sous `save/` — le seul écart au chemin de la convention."""
    if request.method == 'POST':
        return update_settings(request, pk)
    return get_generation_settings(request, pk)


@require_http_methods(["POST"])
def update_settings(request, pk):
    """Save settings for a specific generation"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        generation = owned_or_404(ImageGeneration, user, id=pk)   # MUTATION

        # Don't allow editing while running
        if generation.status == 'RUNNING':
            return JsonResponse({'error': 'Cannot edit a running generation'}, status=400)

        # JSON (inspecteur) OU FormData (modale ⚙) par le lecteur COMMUN — la vue lisait
        # `request.POST` seul (contrat générique `tests_item_settings_contract`, 2026-09-26).
        # Il coerce aussi PAR LE SCHÉMA (types + bornes de params.py) : les 13 blocs
        # `if ... int()/float()` qui vivaient ici en étaient une 3ᵉ copie.
        from wama.common.utils.batch_views import apply_item_settings, read_settings_payload
        schema = _schema_for(generation)
        names = [p['name'] for p in schema]
        data = read_settings_payload(request, schema, names, empty_is_value=('seed',))

        if 'prompt' in data:
            prompt = str(data.get('prompt') or '').strip()
            if not prompt:
                return JsonResponse({'error': 'Prompt is required'}, status=400)
            # Champ à DEUX ÉTATS : l'arbitrage « dans quel champ écrire » est une brique
            # COMMUNE (`apply_prompt_state`) — il était réimplémenté ici le 30/07, ce qui
            # aurait obligé chaque app à le recopier.
            from wama.common.utils.app_metadata import apply_prompt_state
            apply_prompt_state(generation, 'prompt', prompt, data.get('prompt_state'))

        # Seed VIDE = aléatoire : remis à None explicitement (sinon l'ancienne graine survivrait).
        seed_cleared = data.get('seed', None) == ''
        apply_item_settings(generation, {k: v for k, v in data.items() if k != 'prompt'},
                            params_fields=[n for n in names if n != 'seed' or not seed_cleared])
        if seed_cleared:
            generation.seed = None

        # HORS schéma : résolution image (widget à présets par modèle).
        for _f in ('width', 'height'):
            if data.get(_f):
                setattr(generation, _f, int(data[_f]))

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
                "fixed": false,
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

    # La valeur du select est une CLÉ de catalogue (route F4b) : tailles, pas et guidage se
    # lisent sur les CAPACITÉS du catalogue (2026-09-30), donc pour un modèle de n'importe quelle
    # source — Supra2-IMG recevait jusque-là la configuration par défaut (256-1024, 30 pas).
    from wama.common.utils.model_keys import catalog_key, model_id as _model_id
    from .models import _catalog_caps
    model_key = catalog_key(request.GET.get('model') or DEFAULT_IMAGE_MODEL, 'imager')
    model_name = _model_id(model_key)

    config = get_model_resolution_config(model_key)
    resolutions = get_recommended_resolutions(model_key)

    # Pas et guidage RECOMMANDÉS (capacités canoniques `recommended_steps` / `_guidance`), puis
    # la déclaration d'app, puis les valeurs historiques.
    caps = _catalog_caps(model_key)
    default_guidance_scale = caps.get('recommended_guidance')
    default_steps = caps.get('recommended_steps')
    if default_guidance_scale is None or default_steps is None:
        try:
            from wama.common.utils.model_declarations import declaration_for
            model_info = declaration_for(model_key) or {}
            if default_guidance_scale is None:
                default_guidance_scale = model_info.get('default_guidance_scale', 7.5)
            if default_steps is None:
                default_steps = model_info.get('default_steps', 30)
        except Exception:
            default_guidance_scale = 7.5 if default_guidance_scale is None else default_guidance_scale
            default_steps = 30 if default_steps is None else default_steps

    return JsonResponse({
        'model': model_name,
        'config': config,
        'resolutions': resolutions,
        'all_presets': IMAGE_RESOLUTION_PRESETS,
        # Flattened for JS compatibility
        'recommended': [r['key'] for r in resolutions],
        'default': config.get('default', '512x512'),
        # Une résolution FIXE se DIT (le volet grise les autres tailles) ; l'ancien
        # `vram_warning` de la table n'a plus de source — la VRAM se lit dans l'aide du modèle.
        'fixed': config.get('fixed', False),
        'vram_warning': '',
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
