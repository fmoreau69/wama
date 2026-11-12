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
from django.http import JsonResponse
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

from wama.common.utils.queue_manipulation import make_queue_manipulation_views
from wama.common.utils.scoping import visible_or_404
from .models import GenerationBatch, GenerationBatchItem, ImageGeneration
from .utils.model_config import (
    DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL, DEFAULT_I2V_MODEL, get_model_defaults,
)
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


def _qm_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


# Champs remis à zéro par TOUTE duplication de génération — élément (⧉ de la fabrique commune)
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


def _generation_domain(gen):
    """Le DOMAINE d'une génération (image / vidéo) — sa NATURE : ce qui peut cohabiter dans un lot.
    UNE déclaration, deux lectures par la fabrique commune : le domaine du lot (`_batch_domain`,
    `batch_extra`) et `group_key` (2026-10-16 — sans lui, une arrivée mêlant images et vidéos
    formait UN lot au domaine du premier élément, donc dans le mauvais onglet ; la fabrique le
    prescrit : « une app qui fige une nature sur le lot passe le `group_key` jumeau »).
    Lu dans la déclaration commune (`app_modes.element_domain`, 2026-10-21) : le schéma que la
    spec de détail choisit pour l'élément désigne son domaine."""
    from wama.common.utils.app_modes import element_domain_or_first
    return element_domain_or_first(gen)


def _batch_domain(gen):
    """Champs du BATCH dérivés de la génération — l'imager scope sa file par onglet.
    Passé en `batch_extra` aux briques communes (auto_wrap_orphans, fabrique de
    manipulation) : c'est ce qui évite qu'une vidéo isolée atterrisse dans l'onglet Images."""
    return {'domain': _generation_domain(gen)}


def index(request):
    """Main page showing generation queue"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
    from wama.common.utils.process_control import reconcile_queue_of
    reconcile_queue_of(ImageGeneration, user)

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

    # Réglages user — brique commune (A5-22) : le volet de chaque DOMAINE lu par
    # `read_panel_settings` (clé commune `<domaine>.<nom>`, 2026-11-12). Remplace le modèle Django `UserSettings` (5 colonnes), qui
    # n'était écrit par personne : son seul écrivain, la vue `update_settings`, n'était appelée
    # depuis AUCUN JS/template — et son défaut codé en dur 'stable-diffusion-v1-5' empêchait le
    # volet d'afficher « Auto » (donc de proposer le tirage VRAM-aware commun).
    # Le modèle lui-même est retiré au palier suivant, une fois la bascule vérifiée.
    from wama.common.utils.user_settings import read_panel_settings
    from wama.imager.params import IMAGE_PARAMS, VIDEO_PARAMS

    # ⚠ LISTE DE MODÈLES : plus rien ici (route F4b, 2026-09-29). La page construisait la liste
    # depuis `DiffusersBackend.SUPPORTED_MODELS`, l'ENRICHISSAIT du catalogue « sans jamais
    # masquer » (« Verrou n°1 »), en tirait des groupes Images/Logos/Vidéos pour un remplissage
    # JS propre à l'imager — et un repli de trois modèles en dur. Les deux selects déclarent
    # désormais `options_source: "catalog"` (params.py) : le catalogue EST la liste, bornée par
    # la tâche, et un modèle installé depuis le model manager y entre sans code.

    # Les listes de modes de la page (`image_modes`, `video_modes`, `generation_modes`) sont
    # RETIRÉES le 2026-11-01 : aucun gabarit ni script ne les lisait plus depuis le retrait des
    # switches de mode (2026-08-23), et la déclaration n'ayant plus de modes, c'est leur liste de
    # REPLI, écrite ici, qui partait au contexte (`REMOVAL_LEDGER`).

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

    from wama.common.utils.app_modes import domain_schema
    from wama.common.utils.card_chips import common_chips_for_items
    batches_all = build_batches_list(
        user, batch_model=GenerationBatch, work_attr='generation',
        # Réglages COMMUNS aux filles (slot meta_template — porté le 31/08) : imager a
        # DEUX schémas, celui du DOMAINE du lot s'applique (fabrique scopée par onglet).
        extra=lambda b, items, gens: {
            'common_chips': common_chips_for_items(
                gens, domain_schema('imager', getattr(b, 'domain', '') or 'image'))})
    # Chips schéma-driven sur chaque card ; les lignes d'exécution de TOUTES les cards de la page
    # sont lues en une requête (bande des process).
    from wama.common.services.process_pipeline import decorate_cards
    decorate_cards([_it.generation for _b in batches_all for _it in _b['items']], _decorate_card)

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
        'image_panel_values_json': json.dumps(
            read_panel_settings(user, 'imager', IMAGE_PARAMS, domain='image')),
        'video_panel_values_json': json.dumps(
            read_panel_settings(user, 'imager', VIDEO_PARAMS, domain='video')),
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
def create_generation(request):
    """Create a new image generation task (routes to appropriate handler based on mode)"""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        # Get generation mode
        generation_mode = request.POST.get('generation_mode', 'txt2img')

        # Réglages user — écriture À LA CRÉATION (patron transcriber, brique A5-22) : les
        # valeurs du volet voyagent avec le POST de la card, on les persiste ICI, au point de
        # routage unique — par l'écrivain COMMUN du volet (`save_panel_settings`, 2026-10-18 : un
        # réglage remis à son défaut retire la préférence, au lieu de la figer).
        from wama.common.utils.user_settings import save_panel_settings
        save_panel_settings(user, 'imager', _born_schema(generation_mode), request.POST)

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
        return response

    except Exception as e:
        logger.error(f"Error creating generation: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


from wama.common.utils.user_settings import inputs_by_port  # noqa: E402


def _born_schema(mode, model=None):
    """Le schéma d'une génération NAISSANTE de ce mode : celui du domaine que la spec de détail
    choisit pour un élément de ce mode (`app_modes.element_domain`, sur l'élément pas encore
    sauvé). Avant l'élément comme après, une seule règle (2026-11-01) — la vue testait le mode
    contre sa propre liste `VIDEO_MODES`."""
    from wama.common.utils.app_modes import element_schema
    return element_schema((model or ImageGeneration)(generation_mode=mode))


def new_generation_settings(user, mode, post=None, model=None, app='imager', inputs=None) -> dict:
    """Les colonnes de réglage d'une génération NAISSANTE, quel que soit son mode, par la cascade
    COMMUNE (`user_settings.new_element_settings`, 2026-10-18) sur le schéma de son DOMAINE
    (`_born_schema`) : défauts du schéma ← défauts DÉCLARÉS du modèle choisi
    (`get_model_defaults`, en préréglage — 512×512 / 30 étapes / 7.5 sont les valeurs de l'ère
    SD 1.5) ← réglages retenus de l'auteur ← ce qui est posté. Avant, chacun des six modes lisait
    le POST champ par champ, avec ses défauts écrits dans la vue (la vidéo : 5 s, 16 i/s, 480p,
    50 étapes, guidance 5 — le schéma en déclarait d'autres), et le format de sortie se posait
    après coup (`_apply_posted_output`, retiré). Largeur et hauteur ne sont pas des réglages du
    schéma : l'appelant les lit (POST, sinon défauts du modèle). `model`/`app` : une jumelle de
    bac à sable passe les siens."""
    from wama.common.utils.user_settings import new_element_settings
    item_model = model or ImageGeneration
    schema = _born_schema(mode, item_model)
    # Une graine postée VIDE est un choix (un tirage neuf) : la règle COMMUNE des réglages de tirage
    # (`param_schema.EMPTY_IS_NONE_TYPES`, 2026-10-22) — elle était déclarée ici.
    kwargs = dict(post=post, inputs=inputs)
    # Le MODÈLE est lui-même un réglage : on le lit par la cascade, puis ses défauts déclarés
    # deviennent le préréglage de la cascade complète.
    chosen = new_element_settings(user, app, schema, item_model, **kwargs).get('model') or 'auto'
    preset = {k: v for k, v in get_model_defaults(chosen).items()
              if k in ('steps', 'guidance_scale')}
    values = new_element_settings(user, app, schema, item_model, preset=preset, **kwargs)
    if 'negative_prompt' in values:
        values['negative_prompt'] = str(values['negative_prompt'] or '').strip()
    return values


def _dimensions(post, model):
    """Largeur et hauteur d'une génération d'IMAGE : postées, sinon les défauts déclarés du modèle."""
    defaults = get_model_defaults(model or 'auto')
    return {'width': int((post or {}).get('width') or defaults['width']),
            'height': int((post or {}).get('height') or defaults['height'])}


def handle_txt2img(request, user):
    """Handle standard text-to-image generation"""
    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return JsonResponse({'error': 'Prompt is required'}, status=400)

    # Réglages : la cascade COMMUNE (`new_generation_settings`) — sortie et agrandissement compris.
    # On ENREGISTRE le choix du modèle (ou 'auto') — le tirage a lieu au LANCEMENT de la tâche, où
    # la VRAM libre est celle du moment (cf. utils/auto_model.py). Résoudre ici serait périmé.
    settings_values = new_generation_settings(user, 'txt2img', request.POST)

    # Create generation object
    generation = ImageGeneration.objects.create(
        **settings_values,
        **_dimensions(request.POST, settings_values.get('model')),
        user=user,
        generation_mode='txt2img',
        prompt=prompt,
        status='PENDING'
    )

    logger.info(f"Created txt2img generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'id': generation.id,      # le contrat COMMUN d'une vue d'ajout (`addToQueue`)
        'generation_id': generation.id,
        'message': 'Generation created successfully'
    })


#: Le champ de chaque PORT fichier d'une génération : l'image de travail ET l'image de référence se
#: rangent dans `reference_image` (la card les poste sous ce nom, `input_card.js`) — lu par la brique
#: des lignes de lot (`batch_parsers.line_file_inputs`, 2026-11-06).
_LINE_FIELDS = {'reference_image': 'reference_image', 'work_image': 'reference_image'}


def creer_lot_de_prompts(chemin, nom_fichier, user, *, domain='image', reglages=None,
                         app_label='imager', warnings=None):
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
        warnings      : liste où dire chaque ligne écartée et pourquoi (une image refusée).
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
    warnings = warnings if warnings is not None else []
    # Le domaine reçu (card, studio) est l'un des DÉCLARÉS, sinon le premier — jamais un nom en dur.
    from wama.common.utils.app_modes import get_domains
    declared = [d['id'] for d in get_domains(app_label)]
    domain = domain if domain in declared else declared[0]
    # Le WORKFLOW d'une ligne sans image : celui du moteur pour ce domaine (règle de la card,
    # `input_card.js` `deriveMode`).
    mode = 'txt2vid' if domain == 'video' else 'txt2img'
    # Chaque génération du lot naît par la cascade COMMUNE (`new_generation_settings`) ; une ligne
    # surcharge ce qu'elle précise. Les colonnes que le modèle de l'app (ou d'une jumelle) n'a pas
    # sont écartées par la brique — la garde `_has_intent` écrite ici n'a plus d'objet.
    bases = {}

    def base_for(line_mode):
        """Les réglages de naissance d'une ligne, au schéma de SON mode (une image guidée lit sa
        force) — calculés une fois par mode."""
        if line_mode not in bases:
            base = new_generation_settings(user, line_mode, post=r, model=ImageGeneration,
                                           app=app_label)
            if domain == 'image':
                base.update(_dimensions(r, base.get('model')))
            bases[line_mode] = base
        return bases[line_mode]

    prompts = parse_prompt_file(str(chemin))
    if not prompts:
        return None, []

    # L'IMAGE d'une ligne (`-r`, 2026-11-06) se reçoit comme sur la card, par la brique commune des
    # lignes de lot : un chemin se désigne, une URL devient la source téléchargée (`WAMA_INGEST`).
    # Elle était lue (`style_reference`) puis PERDUE. Jugée AVANT de créer quoi que ce soit : une
    # image refusée écarte sa ligne, avec son motif. Une ligne qui porte une image suit le mode de
    # la card quand une image et une consigne sont données (`input_card.js` `deriveMode`).
    from wama.common.utils.batch_parsers import (attach_line_inputs, line_file_inputs,
                                                 line_file_ports)
    lines = []
    for n, p in enumerate(prompts, start=1):
        try:
            files = (line_file_ports(app_label, {'reference': p['reference'], 'line_num': n})
                     if p.get('reference') else {})
            received, remote = line_file_inputs(user, app_label, files, _LINE_FIELDS,
                                                model=ImageGeneration)
        except ValueError as exc:        # `InputRefused` compris : une désignation refusée
            warnings.append(f"Ligne {n} : {exc} — ignorée")
            continue
        guided = 'img2vid' if domain == 'video' else 'img2img'
        lines.append((validate_prompt_config(p), received, remote, guided if files else mode))
    if not lines:
        return None, []

    columns = {f.name for f in ImageGeneration._meta.concrete_fields}
    generations = []
    for v, received, remote, line_mode in lines:
        generation = ImageGeneration.objects.create(
            **{**base_for(line_mode),
               **{k: val for k, val in v.items() if k in columns and k != 'prompt'}},
            user=user,
            generation_mode=line_mode,
            prompt=v.get('prompt', ''),
            status='PENDING',
        )
        attach_line_inputs(generation, received, remote)
        generations.append(generation)

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

    # Les réglages du lot : tout ce que le dépôt poste, lu par la cascade COMMUNE dans le cœur
    # (`creer_lot_de_prompts` → `new_generation_settings`) — plus une liste de clés recopiée ici.
    #
    # DOMAINE du lot (2026-09-08, décision Fabien : « je ne vois pas de raison de ne pas
    # permettre de fichier batch dans le domaine vidéo »). Il est DÉCLARÉ par l'appelant (card
    # vidéo, studio) ; les réglages vidéo suivent le schéma vidéo.
    reglages = request.POST.dict()
    domain = request.POST.get('domain') or 'image'

    # Save file temporarily to parse it
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(prompt_file.name).suffix) as tmp:
        for chunk in prompt_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    warnings = []
    try:
        batch, generations = creer_lot_de_prompts(
            tmp_path, prompt_file.name, user, domain=domain, reglages=reglages, warnings=warnings)
        if batch is None:
            return JsonResponse({'error': 'No valid prompts found in file', 'warnings': warnings},
                                status=400)

        logger.info(f"Created generation batch #{batch.id} with {len(generations)} items "
                    f"for user {user.username}")

        return JsonResponse({
            'success': True,
            'batch_id': batch.id,
            'children_ids': [g.id for g in generations],
            'count': len(generations),
            'warnings': warnings,
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

    # Réglages : la cascade COMMUNE (`new_generation_settings`).
    settings_values = new_generation_settings(user, 'describe2img', request.POST,
                                              inputs=inputs_by_port('imager', reference_image))
    prompt_style = request.POST.get('prompt_style', 'detailed')

    # Create generation with placeholder prompt
    generation = ImageGeneration.objects.create(
        **settings_values,
        **_dimensions(request.POST, settings_values.get('model')),
        user=user,
        generation_mode='describe2img',
        prompt='[Generating prompt from image...]',
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
            'id': generation.id,      # le contrat COMMUN d'une vue d'ajout (`addToQueue`)
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
    # Réglages : la cascade COMMUNE (`new_generation_settings`) — la force de l'image comprise.
    settings_values = new_generation_settings(user, mode, request.POST,
                                              inputs=inputs_by_port('imager', reference_image))

    # For style2img mode, if no prompt is provided, generate one
    if mode == 'style2img' and not prompt:
        prompt = "in the style of the reference image"

    # Create generation
    generation = ImageGeneration.objects.create(
        **settings_values,
        **_dimensions(request.POST, settings_values.get('model')),
        user=user,
        generation_mode=mode,
        prompt=prompt or '[No prompt - pure img2img]',
        source_url=source_url,
        status='PENDING'
    )
    if reference_image:
        reference_image.assign(generation, 'reference_image')

    logger.info(f"Created {mode} generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'id': generation.id,      # le contrat COMMUN d'une vue d'ajout (`addToQueue`)
        'generation_id': generation.id,
        'mode': mode,
        'message': f'{mode} generation created successfully'
    })


def handle_txt2vid(request, user):
    """Handle text-to-video generation"""
    prompt = request.POST.get('prompt', '').strip()
    if not prompt:
        return JsonResponse({'error': 'Prompt is required'}, status=400)

    # Réglages : la cascade COMMUNE (`new_generation_settings`, schéma VIDÉO). La résolution fixe
    # les dimensions (`ImageGeneration.save`).
    settings_values = new_generation_settings(user, 'txt2vid', request.POST)

    # Create generation object
    generation = ImageGeneration.objects.create(
        **settings_values,
        user=user,
        generation_mode='txt2vid',
        prompt=prompt,
        status='PENDING'
    )

    logger.info(f"Created txt2vid generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'id': generation.id,      # le contrat COMMUN d'une vue d'ajout (`addToQueue`)
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
    # Réglages : la cascade COMMUNE (`new_generation_settings`, schéma VIDÉO).
    settings_values = new_generation_settings(user, 'img2vid', request.POST,
                                              inputs=inputs_by_port('imager', reference_image))

    # Create generation object
    generation = ImageGeneration.objects.create(
        **settings_values,
        user=user,
        generation_mode='img2vid',
        prompt=prompt or 'animate this image',
        source_url=source_url,
        status='PENDING'
    )
    if reference_image:
        reference_image.assign(generation, 'reference_image')

    logger.info(f"Created img2vid generation #{generation.id} for user {user.username}")

    return JsonResponse({
        'success': True,
        'id': generation.id,      # le contrat COMMUN d'une vue d'ajout (`addToQueue`)
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
    (brique commune build_batch_template — jamais de contenu en dur, A5-23), servi par
    `batch_template_response` (le nom de fichier commun, 2026-11-02)."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'imager', ['prompt', 'modele', 'steps', 'seed'],
        {'prompt': 'un phare dans la brume, photographie argentique',
         'modele': 'auto', 'steps': 30, 'seed': ''},
        label='Imager (un prompt par ligne)')


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
# copié garde son `domain` (l'onglet). `batch_update` vient AUSSI de la fabrique depuis le
# 2026-10-02 : le schéma se choisit PAR élément (`schema=` callable, image ou vidéo) et les
# réglages sont posés par `_apply_generation_settings`, LA fonction de la route d'un élément.
# Seule `get_batch_children` (lecture PARTAGÉE) reste locale, lue par `batch_elements`.
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
    # Résolus à l'APPEL : les deux fonctions sont définies plus bas dans ce module.
    schema=lambda gen: _schema_for(gen),
    apply_settings=lambda gen, data: _apply_generation_settings(gen, data),
)
batch_start = _bv['batch_start']
batch_update = _bv['batch_update']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']
# Le ZIP de LOT (2026-10-17) : l'imager n'en avait pas — un écrivain qui lisait un NOM de champ ne
# savait pas servir ses images (une liste de chemins) ; l'écrivain commun lit ses sorties DÉCLARÉES.
batch_download = _bv['batch_download']


# ▶ de la card (et ↻ « relancer », le même geste), ▶ et 🗑 de la file : fabrique COMMUNE
# (`item_views.make_item_views`, ROUTE §11 #39, 2026-10-29) — la même déclaration que lit l'outil
# `start_imager` : la tâche image OU vidéo de la génération (`_task_for`). « Relancer » était une
# seconde vue au corps identique ; la file se retire par le geste commun, qui purge le cache de
# progression (`_forget_progress`) et libère images et vidéo.
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(work_model=ImageGeneration, app_id='imager',
                      task_for=lambda gen: _task_for(gen), get_user=_get_user,
                      reset_on_start=_reset_and_forget_progress,
                      on_delete=lambda gen: _forget_progress(gen), batch_model=GenerationBatch)
start = _iv['start']
start_all = _iv['start_all']
clear_all = _iv['clear_all']
# ⏹ ⬇ 🗑 ⧉ ⚙ d'une card : la fabrique COMMUNE (2026-11-02, ROUTE §11 #42 ④), qui lit ce que l'app
# déclare à sa fabrique de lot — le schéma du DOMAINE de chaque génération, LA fonction de
# réglage, le domaine figé sur le lot (`batch_extra` : la copie seule naît dans l'onglet de sa
# nature) et les sorties DÉCLARÉES (une image servie telle quelle, plusieurs en ZIP, la vidéo).
# Le ⏹ était « forcer la réinitialisation » (`force_reset`, retiré le 2026-11-02, R205).
stop = _iv['stop']
download = _iv['download']
delete = _iv['delete']
duplicate = _iv['duplicate']
update_settings = _iv['update_settings']


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — refaire la sortie seule
# (format, agrandissement) sans regénérer, ou regénérer sans attendre qu'un réglage ait changé.
start_process = make_process_start_view(
    work_model=ImageGeneration, task_for=_task_for, reset_on_start=_reset_and_forget_progress)


def _progress_extra(generation):
    """Les clés PROPRES que le JS de l'imager lit : les sorties et leur nature."""
    data = {
        'generated_images': generation.generated_images,
        'duration': generation.duration_display,
        'output_type': generation.output_type,
        'is_video': generation.is_video_generation,
    }
    if generation.output_video:
        data['output_video_url'] = generation.output_video.url
    return data


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que ses clés propres. Ses deux barres de domaine (image, vidéo)
# se DÉDUISENT de la spec de détail depuis le 2026-11-01 (`app_modes.domain_filters`) : la vue
# les écrivait avec sa propre liste de modes vidéo. L'ETA est celle de ses PROCESS
# (`function_specs.PIPELINE`, 2026-10-05).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=ImageGeneration, app_id='imager', extra=_progress_extra)
progress, global_progress = _pv['progress'], _pv['global_progress']



def _schema_for(gen):
    """Schéma du DOMAINE de la génération (image | vidéo), celui que le domaine nomme
    (`app_modes.element_schema`) : vues de réglages, chips de card et modale ⚙ lisent le même objet."""
    from wama.common.utils.app_modes import element_schema
    return element_schema(gen)


def _apply_generation_settings(generation, data):
    """LES réglages d'une génération, posés sans sauver — appelée par la route d'un élément
    (`update_settings`) ET par la fabrique de lots (`apply_settings`), pour que les deux ne
    puissent plus diverger. Jusqu'au 2026-10-02 le lot réécrivait ces règles à côté : il posait
    les valeurs coercées par un `setattr` brut, sans le refus d'une valeur hors des choix, sans
    l'arbitrage des deux états du prompt, sans la graine vidée.

    `data` = les réglages lus par le lecteur commun selon le schéma du domaine. Rend les champs
    touchés, ou `None` quand tout l'élément doit être sauvé (prompt à deux états). Lève
    `ValueError` pour un réglage refusé."""
    from wama.common.utils.batch_views import apply_item_settings
    names = [p['name'] for p in _schema_for(generation)]
    whole = False
    if 'prompt' in data:
        prompt = str(data.get('prompt') or '').strip()
        if not prompt:
            raise ValueError('Prompt is required')
        # Champ à DEUX ÉTATS : l'arbitrage « dans quel champ écrire » est une brique COMMUNE
        # (`apply_prompt_state`) — il était réimplémenté ici le 30/07, ce qui aurait obligé
        # chaque app à le recopier.
        from wama.common.utils.app_metadata import apply_prompt_state
        apply_prompt_state(generation, 'prompt', prompt, data.get('prompt_state'))
        whole = True

    # Graine VIDE = un tirage neuf : le lecteur commun la rend `None` (type `seed`, 2026-10-22),
    # posée comme toute valeur — elle était remise à la main ici.
    touched = apply_item_settings(
        generation, {k: v for k, v in data.items() if k != 'prompt'},
        params_fields=[n for n in names if n != 'prompt'])

    # HORS schéma : résolution image (widget à présets par modèle).
    for name in ('width', 'height'):
        if data.get(name):
            setattr(generation, name, int(data[name]))
            touched.append(name)
    return None if whole else touched


def _decorate_card(gen, preloaded=False):
    """Chips schéma-driven du partial _generation_card (miroir anonymizer _decorate_card) :
    le schéma (params.py, chip=True) est la SOURCE, la card n'invente rien. Et les PROCESS de la
    card (« Génération → Sortie ») avec son état MONTRÉ, par la brique commune
    (`process_pipeline.decorate`, `ROUTE §10.6` 5.1)."""
    from wama.common.services.process_pipeline import decorate
    from wama.common.utils.card_chips import chips_by_section
    gen.chips = chips_by_section(gen, _schema_for(gen))
    decorate(gen, preloaded=preloaded)
    return gen


# Partial d'UNE card (contrat card_html/refreshCard), consommé par queue.js sur transition de
# statut : fabrique commune (`make_card_view`, 2026-11-02), qui pose aussi le `domain` de la
# génération (la même lecture que `_generation_domain`) ; route au format commun `<int:pk>`.
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=ImageGeneration, template='imager/_generation_card.html',
                           decorate=lambda gen: _decorate_card(gen))


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
    group_key=_generation_domain,       # jumeau de `batch_extra` : la nature figée sur le lot
)
remove_from_batch = _qm['remove_from_batch']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
consolidate = _qm['consolidate']


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


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


def _reference_size(generation):
    """`[L, H]` de l'image d'entrée quand elle GUIDE l'image produite (`REFERENCE_GUIDED_MODES`),
    sinon None. L'en-tête seul est lu."""
    from .tasks import REFERENCE_GUIDED_MODES
    if not generation.reference_image or generation.generation_mode not in REFERENCE_GUIDED_MODES:
        return None
    try:
        from PIL import Image
        with Image.open(generation.reference_image.path) as ref:
            return list(ref.size)
    except Exception:
        return None


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
            # Le DOMAINE de l'élément (2026-11-01) : la modale le lit au lieu de le redéduire du
            # mode avec sa propre liste.
            'domain': _generation_domain(generation),
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
            # Guidée par une image, la sortie en suit le RATIO (`tasks._output_size`) : la modale
            # propose sa taille et le dit.
            'reference_size': _reference_size(generation),
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
        return update_settings(request, pk)      # la ⚙ de la fabrique commune
    return get_generation_settings(request, pk)


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
    # `ref=LxH` : la card est guidée par une image — sa taille entre en tête des choix.
    ref_w, _, ref_h = (request.GET.get('ref') or '').partition('x')
    reference_size = (int(ref_w), int(ref_h)) if ref_w.isdigit() and ref_h.isdigit() else None
    resolutions = get_recommended_resolutions(model_key, reference_size)

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


# `force_reset_generation` (`force-reset/<id>/`, l'ancien ⏹ de l'imager) RETIRÉE le 2026-11-02
# (REMOVAL_LEDGER R205) : le ⏹ est le geste commun (`stop`), qui n'arrête que ce qui attend ou
# tourne — l'ancienne vue remettait en échec une génération de TOUT statut, réussie comprise.
