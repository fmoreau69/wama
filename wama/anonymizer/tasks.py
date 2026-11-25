import os
import logging
from celery import shared_task
from django.db import close_old_connections
from django.core.cache import cache
from django.contrib.auth import get_user_model
from .models import Media
from wama.common.backends import anonymize
from .utils.yolo_utils import get_model_path
from wama.common.app_registry import normalize_types
from wama.common.utils.media_paths import get_app_media_path
from .utils.media_utils import sane_classes
from .utils.sam3_manager import check_sam3_installed, validate_sam3_prompt
from wama.common.utils.console_utils import push_console_line

# Couverture multi-modèles : seule `needs_parallel_detection` survit au retrait du second
# pipeline (2026-08-13) — elle ne fait que consulter la couverture, elle n'orchestre plus rien.
from .parallel_detection import needs_parallel_detection

logger = logging.getLogger(__name__)


def anonymizer_eta_key_size(media):
    """Clé + taille ETA — PARTAGÉE entre record_run (fin de tâche) et estimate
    (endpoint progress) : même clé des deux côtés ou l'EMA n'apprend jamais."""
    from .utils.yolo_utils import catalogue_id_for
    engine = ('sam3' if media.target_mode == 'description'
              else (catalogue_id_for(media.model_to_use) or 'auto'))
    is_video = (media.media_type == 'video' or
                normalize_types([media.file_ext]) == ['video'])
    if is_video:
        return (f'anonymizer:vid:{engine}', float(media.duration_inSec or 1.0), 'video_sec')
    mpx = (media.width or 0) * (media.height or 0) / 1_000_000.0 or 1.0
    return (f'anonymizer:img:{engine}', mpx, 'megapixel')


def anonymizer_blur_eta_key_size(media):
    """Clé + taille ETA du FLOUTAGE (process à part depuis le 2026-10-04) : décoder, flouter,
    réencoder — le coût suit la durée de la vidéo ou la surface de l'image, pas le détecteur."""
    is_video = (media.media_type == 'video' or
                normalize_types([media.file_ext]) == ['video'])
    if is_video:
        return ('anonymizer:blur:vid', float(media.duration_inSec or 1.0), 'video_sec')
    mpx = (media.width or 0) * (media.height or 0) / 1_000_000.0 or 1.0
    return ('anonymizer:blur:img', mpx, 'megapixel')


def blur_eta(media):
    """ETA déclarée du process `blur` (`ProcessSpec.eta`) : APPRISE seulement (a priori nul) — une
    clé de PROCESS n'a pas d'a priori de domaine, ceux de l'estimateur décrivent des modèles
    (6 s par seconde de vidéo produite : faux d'un ordre de grandeur pour un floutage)."""
    return (*anonymizer_blur_eta_key_size(media), True, 0.0)


def qualify_eta(media):
    """ETA déclarée du process `qualify` : APPRISE seulement, comme `blur_eta` — même taille
    (durée de la vidéo, surface de l'image) ; la profondeur a sa propre clé, son modèle domine le
    coût, et sa résidence est laissée au gouverneur (None)."""
    _, size, unit = anonymizer_blur_eta_key_size(media)
    kind = 'vid' if unit == 'video_sec' else 'img'
    if getattr(media, 'qualify_depth', False):
        return (f'anonymizer:qualify:depth:{kind}', size, unit, None, 0.0)
    return (f'anonymizer:qualify:{kind}', size, unit, True, 0.0)


def _record_output(media, written):
    """Pose sur le média le fichier que le moteur a RÉELLEMENT écrit (2026-09-27).

    Avant : `_resolve_output_rel` DEVINAIT la sortie par `glob('<entrée>_blurred*')`, trié par
    ordre ALPHABÉTIQUE — donc des cards dupliquées (même entrée) se voyaient attribuer le même
    fichier, et un média passé de YOLO à SAM3 pouvait garder la sortie de l'autre moteur.
    La sortie précédente de CETTE card — et l'original que la brique de sortie en gardait — part
    si elle n'est plus la même (moteur ou format changé) ; un fichier qu'une autre card désigne
    encore est laissé (`output_process.drop_previous_outputs`).
    """
    from django.conf import settings
    from wama.common.services.output_process import drop_previous_outputs
    rel = ''
    if written and os.path.exists(written):
        rel = os.path.relpath(written, settings.MEDIA_ROOT).replace(chr(92), '/')
    drop_previous_outputs(media, 'output_file', keep=[written] if rel else [])
    media.output_file.name = rel



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
        push_console_line(user_id, message, level=level, app='anonymizer')
    except Exception:
        pass


def _output(media, ctx):
    """GLU du process `output` : format et qualité de sortie, par la glu COMMUNE
    (`output_process.output_step`) — le fichier flouté d'origine est gardé tant que la sortie le
    transforme. « Original » est le format du fichier DÉPOSÉ, que le floutage écrit lui-même
    (`detections.rewrite_media`, 2026-10-28) : rien à convertir. La résolution propre à l'app
    (`_output_format_for` et sa valeur `input`, « Format du fichier source ») est retirée le même
    jour — l'anonymizer suit la règle de toutes les apps."""
    from wama.common.services.output_process import output_step
    video = normalize_types([media.file_ext]) == ['video']
    return output_step('output_file', domain='video' if video else 'image', app_id='anonymizer',
                       console=lambda item, message: _console(item.user_id, message))(media, ctx)


# ----------------------------------------------------------------------
# Tâche principale pour traiter un média
# ----------------------------------------------------------------------
@shared_task(bind=True)
def process_single_media(self, media_id, force_individual=False, process=None):
    """
    Traite un média unique en DB — avec SES réglages, et eux seuls — par le squelette COMMUN
    (`run_item_task`, marche P6 du 2026-10-03) : garde de redélivrance après crash, ingestion
    d'une source distante, statuts canoniques, durée max, chrono, ETA, console, notifications,
    ligne d'exécution, révision. L'app ne garde que ses GLUS (`_detect`, `_blur`, `_output`) et
    ce qui lui est propre : le verrou de dédoublonnage (deux tâches pour un même média) et l'arrêt demandé par
    l'utilisateur.

    Depuis le 2026-09-27 un média NAÎT avec les réglages de son auteur (brique `user_settings`,
    `ROADMAP §23.2quater`) : la tâche ne lit plus que ses colonnes.

    force_individual : conservé pour les appelants existants ; il n'a plus d'effet.
    process : lancement BORNÉ à ce process du pipeline (⚠ argument de tâche nouveau : workers à
    relancer).
    """
    from wama.common.services.output_process import forget_lost_generation
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE

    # Dedup: check if another task already owns this media
    owner_key = f"anon_task_owner:media:{media_id}"
    current_owner = cache.get(owner_key)
    my_task_id = self.request.id

    if current_owner and current_owner != my_task_id:
        logger.info(f"[Dedup] Skipping media {media_id}: already owned by task {current_owner}")
        return {"skipped": True, "media_id": media_id, "reason": "duplicate"}

    # Claim ownership
    cache.set(owner_key, my_task_id, timeout=7200)
    cache.set(f"anon_lock:media:{media_id}", True, timeout=7200)

    try:
        # Vérifie si un stop a été demandé (avant tout traitement).
        user_id = Media.objects.filter(pk=media_id).values_list('user_id', flat=True).first()
        if user_id is not None and cache.get(f"stop_process_{user_id}", False):
            cache.delete(f"stop_process_{user_id}")
            return {"stopped": media_id}

        # « En cours » est posé par TOUS les lanceurs (`begin_processing`), y compris celui de
        # la file entière (`item_views.start_queue`) : la tâche ne bascule rien avant la garde
        # anti-re-livraison du squelette — sans quoi un message re-livré PÉRIMÉ remettait en
        # cours, pour toujours, un média terminé (2026-10-03).
        # La card porte un PIPELINE de trois process (`function_specs.PIPELINE`) : `detect`
        # (`_detect`, les détections du média), `blur` (`_blur`, le floutage depuis elles) puis
        # `output` (`_output`, format et qualité). Un lancement ne rejoue que ce qui n'est plus à
        # jour : changer l'intensité du flou ne redétecte pas, changer le format ne re-floute
        # pas. La sortie repart du fichier que le floutage a laissé : s'il n'est plus là, le
        # floutage rejoue (un document de détections disparu, lui, se voit à sa ligne).
        known = Media.objects.filter(pk=media_id).first()
        if known is not None:
            forget_lost_generation(known, 'output_file', 'blur')
            # Une description qui demande des attributs active la qualification AVANT que le
            # lancement ne choisisse ses étapes (2026-11-25) — comprise ici si la détection va
            # jouer et qu'elle ne l'a jamais été : un texte libre qualifie dès le premier ▶.
            # Jamais bloquant.
            try:
                plan = None
                if (known.target_mode == 'description'
                        and not (known.sam3_prompt_processed or '').strip()
                        and 'detect' in [spec.key for spec in
                                         PIPELINE.steps_to_run(known, only=process)]):
                    plan = understood_plan(known, understand_description(known, known.user))
                switch_requested_qualification(known, plan)
            except Exception:
                logger.warning("[anonymizer] média %s : qualification demandée non lue",
                               media_id, exc_info=True)
        run_item_task(self, app_id='anonymizer', model=Media, item_id=media_id,
                      pipeline=PIPELINE,
                      processes={'detect': _detect, 'qualify': _qualify, 'blur': _blur,
                                 'output': _output,
                                 'ocr': _ocr, 'detect_text': _detect_personal_data,
                                 'occult_text': _occult_text},
                      notify_label='Anonymizer', only=process,
                      progress_fn=lambda item, pct, msg: set_media_progress(item.pk, pct))
    finally:
        # Release dedup locks — succès, échec, arrêt : dans tous les cas.
        cache.delete(f"anon_lock:media:{media_id}")
        cache.delete(f"anon_task_owner:media:{media_id}")
    return {"processed": media_id}


def _ingested_metadata(inst, save_path, fname):
    """Métadonnées relevées sur le fichier téléchargé (mêmes champs que l'upload) — déclaré à
    l'ingestion commune (`source_ingest.ensure_local_input`, `derive=`)."""
    from wama.anonymizer.views import add_media_to_db, new_media_settings
    add_media_to_db(inst, save_path)
    inst.file_ext = os.path.splitext(save_path)[1].lstrip('.').lower()
    fields = ['file_ext', 'width', 'height', 'fps',
              'duration_inSec', 'duration_inMinSec', 'media_type']
    if inst.media_type == 'document':
        # Un document reçu par URL finit de naître comme un document DÉPOSÉ (2026-11-10) : les
        # réglages de son domaine, et ce que le FICHIER propose (l'OCR d'un scan,
        # `Param.default_from`), qui n'était pas là à la création.
        from wama.common.utils.user_settings import inputs_by_port
        app = inst._meta.app_label
        columns = new_media_settings(inst.user, model=type(inst), app=app, nature='document',
                                     inputs=inputs_by_port(app, save_path))
        for name, value in columns.items():
            setattr(inst, name, value)
        fields += [name for name in columns if name not in fields]
    return fields


def _catalogue_key(value):
    """La clé de catalogue d'un modèle désigné par sa clé, son identifiant, son fichier ou son
    chemin — None s'il n'est pas au catalogue (on ne nomme pas ce qu'on ignore). La lecture est
    celle de la brique de l'app (`catalogue_key_for`) : elle recomposait `anonymizer:<id>` ici,
    ce qui serait FAUX pour une clé d'une autre source depuis le select par tâche (2026-10-07)."""
    from .utils.yolo_utils import catalogue_key_for
    try:
        return catalogue_key_for(os.path.basename(str(value))) or catalogue_key_for(value) or None
    except Exception:
        return None


#: La clé de catalogue de SAM3 — le détecteur d'une description sous « auto », et le suivi d'un
#: objet désigné d'un clic (`TRACKING_MODEL_KEY`).
SAM3_KEY = 'anonymizer:sam3'


def _serves_mode(model_key: str, media) -> bool:
    """Le modèle sert-il le MODE de la card ? La règle que borne le menu (`app_modes.
    mode_model_filter` → `model_selector.matches_inputs`), relue au lancement : un modèle que le
    menu n'offrirait pas dans ce mode ne s'y lance pas."""
    from wama.common.utils.app_modes import element_domain_or_first, mode_model_filter
    from wama.model_manager.models import AIModel
    from wama.model_manager.services.model_selector import matches_inputs
    model = AIModel.objects.filter(model_key=model_key).first()
    if model is None:
        return False
    rule = mode_model_filter('anonymizer', element_domain_or_first(media), media.target_mode)
    return matches_inputs(model, rule.get('available_inputs'), consumes=rule.get('consumes'))


def _routed_description(prompt, precision_level, user):
    """« auto » en mode DESCRIPTION (2026-11-24, `ROADMAP §17quater` A.2) : le ROUTEUR commun
    (`detection_ensemble.route_concepts`). Un concept qu'un détecteur DÉDIÉ installé couvre
    (« face », « license plate ») va à la couverture de l'app — rappel mesuré, curseur, ensemble
    par classe, comme en mode Classes ; le reste à SAM3, qui ne reçoit que cette part. Rend
    `{'models', 'plan'}`, ou None quand la description ne porte aucun concept (le chemin d'avant
    le dit). Ce que personne ne cherchera est DIT ; rien ne l'est en silence."""
    from wama.common.backends.detection_base import prompt_concepts
    from wama.common.services.detection_ensemble import route_concepts
    concepts = prompt_concepts(prompt)
    if not concepts:
        return None
    open_key = SAM3_KEY if check_sam3_installed() else ''
    route = route_concepts(concepts, open_model_key=open_key,
                           cover=lambda wanted: needs_parallel_detection(wanted, precision_level))
    sam3_part = next((m for m in route['models'] if m.get('model_key') == SAM3_KEY), None)
    if sam3_part is not None:
        valid, error = validate_sam3_prompt(sam3_part['prompt'])
        if not valid:
            route['models'].remove(sam3_part)
            route['unrouted'] = prompt_concepts(sam3_part['prompt'])
            _console(user.id, f"SAM3 ne peut pas chercher « {sam3_part['prompt']} » : {error}",
                     'warning')
    for step in route['plan']:
        _console(user.id, f"Description — « {_said_step(step)} » : "
                          f"{', '.join(step['by']) or 'aucun détecteur'}")
    if route['unrouted']:
        _console(user.id, "Aucun détecteur ne cherchera : " + ', '.join(route['unrouted'])
                 + (" — SAM3 n'est pas installé." if not open_key else ""), 'warning')
    if not route['models']:
        raise ValueError("Aucun détecteur ne sait chercher : " + ', '.join(concepts)
                         + " — installez SAM3 ou un détecteur qui les porte.")
    return route


def _said_step(step) -> str:
    """Un pas du plan dit en clair : son rang, le concept, les attributs qu'on mesurera après lui,
    l'objet auquel il appartient (« nearest face (small) of person (red) »)."""
    def said(part):
        attrs = part.get('attrs') or {}
        return part['concept'] + (f" ({', '.join(attrs.values())})" if attrs else '')
    return ((f"{step['rank']} " if step.get('rank') else '') + said(step)
            + (f" of {said(step['of'])}" if step.get('of') else ''))


def description_plan(media) -> list:
    """Ce que le système a COMPRIS de la description d'un média, et QUI cherchera chaque concept —
    `[{'concept', 'by': [noms de modèles], 'attrs'?}]`, ou `[]` tant que rien n'a été compris
    (aucun texte traité gardé : le lancement ou ✨ le poseront). Le MÊME routeur que le lancement
    (`_routed_description` → `route_concepts`), lu sans LLM ni console : la modale et la page le
    montrent (2026-11-24, décision de Fabien : « les réglages le reflètent »). Sous un modèle
    désigné, c'est lui qui cherche tout. `attrs` : ce que la qualification mesurera pour ce
    concept (« red car » cherché par un détecteur à classes, 2026-11-25)."""
    from wama.common.utils import card_chips
    plan = understood_plan(media)
    names = card_chips.catalog_names([k for step in plan for k in step['by']])
    return [{**step, 'by': [names.get(k) or k for k in step['by']]} for step in plan]


def understood_plan(media, understood: str = None) -> list:
    """`description_plan` sous les CLÉS de catalogue — ce que lisent la modale (noms en plus) et
    le lancement (`switch_requested_qualification`). `understood` : la description que le
    lancement vient de comprendre (`understand_description`), sinon celle que la card garde."""
    from wama.common.backends.detection_base import prompt_concepts
    from wama.common.services.detection_ensemble import route_concepts
    from .utils.yolo_utils import catalogue_key_for
    if media.target_mode != 'description':
        return []
    concepts = prompt_concepts(understood or getattr(media, 'sam3_prompt_processed', '') or '')
    if not concepts:
        # Rien de compris encore : une description faite des seuls termes PROPOSÉS (la palette,
        # le défaut) se comprend par la déclaration, sans LLM (`app_metadata.vocabulary_concepts`).
        from wama.common.utils.app_metadata import vocabulary_concepts
        known, rest = vocabulary_concepts('anonymizer', 'sam3_prompt', media.sam3_prompt)
        concepts = known if not str(rest or '').strip() else []
    if not concepts:
        return []
    designated = catalogue_key_for(media.model_to_use)
    if designated:
        return [{'concept': c, 'by': [designated]} for c in concepts]
    return route_concepts(
        concepts, open_model_key=SAM3_KEY if check_sam3_installed() else '',
        cover=lambda wanted: needs_parallel_detection(wanted, media.precision_level))['plan']


def _requested_qualification():
    """Les réglages de l'anonymizer pour chaque mesure (`measures_of`) : l'interrupteur que son
    process `qualify` DÉCLARE (`ProcessSpec.toggle`), et la profondeur quand elle est demandée."""
    from .function_specs import PIPELINE
    return ((PIPELINE.spec('qualify').toggle, 'attributes'), ('qualify_depth', 'depth'))


def switch_requested_qualification(media, plan=None) -> list:
    """La DEMANDE règle la qualification (2026-11-25, `ROADMAP §17quater` B ; décision de Fabien
    du 2026-11-24 : « ce que le système a compris doit être montré […] et les réglages le
    refléter ») : un pas du plan qui demande une MESURE (`detection_attributes.measures_of` :
    attributs qu'un détecteur à classes cherchera, ceux de l'objet auquel il appartient, un rang)
    ACTIVE la qualification, et sa profondeur pour un plan ou un rang de distance — écrit sur la
    card, dit à la console. Rend les réglages activés (`[]` : rien à changer). `plan` : celui du
    lancement ; sinon ce que la card a déjà compris, lu sans LLM (`understood_plan`). Rien n'est
    jamais DÉSACTIVÉ ici : c'est un choix de l'utilisateur."""
    from wama.common.utils.detection_attributes import measures_of
    steps = [step for step in (understood_plan(media) if plan is None else plan)
             if measures_of(step)]
    if not steps:
        return []
    needed = set().union(*(measures_of(step) for step in steps))
    switched = [name for name, need in _requested_qualification()
                if not getattr(media, name, False) and need in needed]
    if switched:
        for name in switched:
            setattr(media, name, True)
        type(media).objects.filter(pk=media.pk).update(**{name: True for name in switched})
        said = ', '.join(f"« {_said_step(step)} »" for step in steps)
        _console(media.user_id, f"La description demande {said} : la qualification est activée"
                                + (" avec la profondeur" if 'qualify_depth' in switched else '')
                                + '.', 'info')
    return switched


def understand_description(media, user) -> str:
    """La description de la card COMPRISE par la pipeline de prompts commune (concepts anglais).
    La route de l'imager (`effective_prompt`) : ce qui a déjà été compris (gardé au dernier
    lancement, posé par ✨, édité par l'utilisateur) part tel quel, sans seconde passe LLM ; sinon
    la pipeline le comprend ici, et ce qu'elle a compris est GARDÉ pour être montré
    (`keep_processed_prompt`, 2026-11-24). Appelée par la détection, et au départ de la tâche
    quand la détection va jouer : la qualification qu'une description demande est alors réglée
    avant que le lancement ne choisisse ses étapes (2026-11-25)."""
    from wama.common.utils.app_metadata import (effective_prompt, keep_processed_prompt,
                                                process_prompt_for)
    already = bool((getattr(media, 'sam3_prompt_processed', '') or '').strip())
    understood = process_prompt_for('anonymizer', 'sam3_prompt',
                                    effective_prompt(media, 'sam3_prompt'),
                                    instance=media, user=user, full=True,
                                    enrich=False if already else None,
                                    console=lambda m: _console(user.id, f"[SAM3] {m}"))
    if not already:
        keep_processed_prompt(media, 'sam3_prompt', understood)
    return understood.get('prompt') or media.sam3_prompt


def _detection_kwargs(media, user, ensure_model=None):
    """Ce que le détecteur reçoit, et les modèles qu'il emploiera (clés de catalogue) : choix du
    ou des modèles par la couverture des classes demandées, ou SAM3 pour une description.

    `ensure_model` : `ctx.ensure_model` de la glu — le modèle DÉSIGNÉ sur la card s'installe par
    la route AVANT qu'on lise ses classes ou son chemin (2026-11-06) ; la couverture, elle, ne
    retient que des modèles installés (`model_coverage`)."""
    precision_level = media.precision_level
    use_segmentation = media.use_segmentation
    # Mode DESCRIPTION (`app_modes`) : SAM3 sous « auto » ; un autre modèle qui lit une
    # description, DÉSIGNÉ sur la card (LocateAnything, 2026-11-19), passe par l'ensemble commun
    # des détecteurs (`detection_ensemble`, son backend tiré du catalogue) — plus bas.
    use_sam3 = media.target_mode == 'description'
    sam3_prompt = media.sam3_prompt

    # SAM3 = concepts EN → pipeline commune (§16.6) ; KIND déclaré dans app_metadata.
    # Bug d'origine : « Floute les visages » (FR) → 0 masque. process_prompt_for est fail-safe.
    if use_sam3 and sam3_prompt and sam3_prompt.strip():
        sam3_prompt = understand_description(media, user)

    _console(user.id, f"[DEBUG] SAM3 settings: use_sam3={use_sam3}, prompt='{sam3_prompt[:30] if sam3_prompt else ''}'")

    kwargs = {
        # Le fichier de la card, là où il EST : un `FileField` est un pointeur (`media_paths.
        # reference_or_copy`) — une entrée désignée vit dans `temp/` ou la médiathèque, pas dans
        # `anonymizer/input/`. Jusqu'au 2026-10-05 le chemin était RECONSTRUIT dans ce dossier
        # (`get_input_media_path`, R104) : toute card pointée échouait (« Input file not found »).
        'media_path': media.file.path,
        'file_ext': media.file_ext,
        # Assaini : un vieux chemin de sauvegarde a injecté le BOOLÉEN sérialisé 'false'
        # dans des listes de classes (médias 220/221/225 constatés le 2026-08-17) — une
        # classe est un nom, jamais true/false/none/vide.
        'classes2blur': sane_classes(media.classes2blur),
        'detection_threshold': media.detection_threshold,
        # La DÉCIMATION d'une vidéo (2026-11-19) : 0 = « auto », chaque détecteur sa cadence
        # déclarée (`DetectionBackend.decimation_for`).
        'detection_decimation': getattr(media, 'detection_decimation', 0) or 0,
        'precision_level': precision_level,
        'use_segmentation': use_segmentation,
        # SAM3 parameters
        'use_sam3': use_sam3,
        'sam3_prompt': sam3_prompt,
        'user_id': user.id,  # For console logging
    }

    # ======================================================================
    # PARALLEL DETECTION: Check if multiple models are needed
    # ======================================================================
    # Determine user's specified model (if any)
    # Clé de catalogue, identifiant ou chemin d'avant, ou « auto » → '' (`catalogue_key_for`).
    from wama.common.utils.model_keys import model_id
    from .utils.yolo_utils import catalogue_key_for, model_path_for
    designated = catalogue_key_for(media.model_to_use)
    if use_sam3 and designated and designated != SAM3_KEY and not _serves_mode(designated, media):
        # Un modèle resté d'un autre mode (une liste de classes) ne lit pas de description : la
        # card le garde, SAM3 tourne, et la console le dit.
        _console(user.id, f"{designated} ne lit pas de description : SAM3 la détecte.", 'warning')
        designated = ''
    if use_sam3 and designated and designated != SAM3_KEY:
        # Un modèle à DESCRIPTION désigné (2026-11-19) : l'ensemble commun le sert par SON
        # backend, la description traitée en concepts (`sam3_prompt`) pour demande. Refusé en le
        # disant quand rien ne le sert — jamais un repli muet sur SAM3.
        from wama.common.backends.manager import backend_for_key
        if backend_for_key(designated) is None:
            raise ValueError(f"Aucun moteur ne sait lancer {designated} pour anonymiser. "
                             "Choisissez « auto » ou un autre modèle dans les réglages.")
        if ensure_model is not None:
            ensure_model(designated)
        kwargs['use_sam3'] = False
        kwargs['models'] = [{'model_key': designated, 'path': None, 'name': designated,
                             'classes': None}]
        _console(user.id, f"Description : {designated} — « {sam3_prompt or ''} »")
        return kwargs, [designated]
    if use_sam3 and not designated:
        routed = _routed_description(sam3_prompt, precision_level, user)
        if routed is not None:
            kwargs['use_sam3'] = False
            kwargs['models'] = routed['models']
            kwargs['plan'] = routed['plan']
            return kwargs, [m['model_key'] for m in routed['models'] if m.get('model_key')]
    user_specified_key = '' if use_sam3 else designated
    if user_specified_key:
        # Le select liste par TÂCHE (route F4b ⑤, 2026-10-07) : un modèle de détection d'une
        # autre source peut y entrer. Le lancement refuse ce que rien ne sert, avec la raison —
        # jamais un repli silencieux sur un autre modèle que celui qui a été demandé.
        from wama.common.backends.manager import backend_for_key
        if backend_for_key(user_specified_key) is None:
            raise ValueError(f"Aucun moteur ne sait lancer {user_specified_key} pour anonymiser. "
                             "Choisissez « auto » ou un autre modèle dans les réglages.")
        # Absent : la route l'installe, la tâche attend (`model_readiness`) — avant toute lecture
        # du modèle (ses classes, son chemin), jamais un téléchargement au premier usage.
        if ensure_model is not None:
            ensure_model(user_specified_key)
    # L'IDENTIFIANT garde la console et les chemins historiques (`model_path_for` lit les deux).
    user_specified_model = model_id(user_specified_key)

    # Check if specialty classes (face, plate) are requested
    # These often require dedicated models even if user has a default COCO model
    specialty_classes_set = {'face', 'plate', 'license_plate', 'license plate'}
    specialty_classes_requested = any(
        c.lower() in specialty_classes_set for c in kwargs['classes2blur']
    )

    # Le modèle DÉSIGNÉ sur la card couvre-t-il les classes demandées ? Alors c'est LUI qui tourne,
    # même quand la couverture en aurait réuni plusieurs. Jusqu'au 2026-10-15, une demande
    # « visage » ou « plaque » consultait la couverture quel que soit le modèle de la card, et
    # quand elle retenait un ENSEMBLE (yolov9c + yolov9e pour « visage »), il remplaçait le choix
    # en silence — relevé en comparant quatre détecteurs sur le lot #685 : douze cards, quatre
    # modèles demandés, un seul et même ensemble exécuté. Le choix n'était respecté que si la
    # couverture rendait UN modèle.
    # La question se pose comme la page (cases grisées, `views._class_coverage_meta`) et la
    # couverture la posent (2026-11-07) : les classes du modèle au CATALOGUE, lues dans ses poids
    # par la découverte de son moteur, YOLO ou non, et l'appariement commun (`classes_couvertes`,
    # alias compris). La lecture précédente ouvrait le fichier par YOLO et comparait les mots
    # tels quels : la case `plate` ne trouvait jamais `license_plate`, et EgoBlur ou RT-DETR, qui
    # ne s'ouvrent pas par YOLO, ne rendaient aucune classe — un détecteur de plaques désigné était
    # toujours remplacé par la couverture, la card nommant un autre modèle que celui qui tournait.
    user_covers = False
    if user_specified_model and specialty_classes_requested:
        from wama.common.services.model_coverage import classes_couvertes
        from wama.model_manager.models import AIModel
        designated = AIModel.objects.filter(model_key=user_specified_key).first()
        requested = set(kwargs['classes2blur'])
        user_covers = (designated is not None and bool(requested)
                       and classes_couvertes(designated, requested) == requested)

    # La couverture est consultée hors SAM3, quand la card ne désigne aucun modèle, ou quand le
    # modèle désigné ne couvre pas les classes spéciales demandées (un modèle COCO ne voit pas
    # les visages).
    should_check_parallel = not use_sam3 and (
        not user_specified_model or (specialty_classes_requested and not user_covers))

    # Debug: Log parallel detection decision
    logger.info(f"[ParallelCheck] use_sam3={use_sam3}, user_specified_model={user_specified_model}")
    logger.info(f"[ParallelCheck] specialty_classes_requested={specialty_classes_requested}, should_check_parallel={should_check_parallel}")
    logger.info(f"[ParallelCheck] classes2blur={kwargs['classes2blur']}, precision_level={precision_level}")
    _console(user.id, f"[Parallel Check] SAM3={use_sam3}, user_model={user_specified_model}, specialty={specialty_classes_requested}")

    if should_check_parallel:
        parallel_info = needs_parallel_detection(kwargs['classes2blur'], precision_level)

        logger.info(f"[ParallelCheck] parallel_info: parallel={parallel_info.get('parallel')}, "
                    f"models={len(parallel_info.get('models', []))}, coverage={parallel_info.get('coverage')}")
        _console(user.id, f"[Parallel Check] parallel={parallel_info.get('parallel')}, "
                          f"models={len(parallel_info.get('models', []))}")

        if parallel_info.get('unsupported_classes'):
            _console(user.id, f"[Parallel Check] Unsupported classes: {parallel_info['unsupported_classes']}")

        if parallel_info['parallel'] and len(parallel_info['models']) > 1:
            # ── MULTI-MODÈLES : UNE SEULE TÂCHE (2026-08-13) ──────────────────────────
            # Auparavant : une chaîne Celery `detect_with_model` × N + `merge_and_blur`,
            # avec les masques sérialisés en base64 dans Redis. Ce second pipeline avait
            # PERDU l'interpolation, le format de sortie, le statut RUNNING, l'ETA, la
            # notification et l'annulation — et décodait la vidéo N+1 fois.
            # Désormais on reste dans CETTE tâche : `Anonymize` sait charger N modèles et
            # unir leurs zones frame par frame. Tout ce qui suit (statut, ETA, format,
            # notification, verrous) s'applique donc au multi-modèles comme au reste.
            _console(user.id, f"[Multi] {len(parallel_info['models'])} modèles retenus")
            for m in parallel_info['models']:
                _console(user.id, f"  - {m['id']} : {m['classes']}")
            kwargs['models'] = [
                {'path': m['path'], 'name': m.get('name'), 'classes': m.get('classes'),
                 'model_key': m.get('model_key')}
                for m in parallel_info['models']
            ]

        elif not parallel_info['parallel'] and len(parallel_info['models']) == 1:
            # UN modèle retenu par la couverture. Un modèle désigné qui couvre les classes n'arrive
            # plus ici (`user_covers`, plus haut) : celui-ci ne remplace qu'un modèle désigné qui ne
            # les couvre pas, ou l'« auto ».
            selected = parallel_info['models'][0]
            from .utils.yolo_utils import get_model_path as _gmp
            # La couverture rend déjà le chemin disque du catalogue : le re-résoudre depuis
            # l'identifiant rouvrirait une seconde route (et échouerait pour un modèle rangé hors
            # de l'arborescence historique). `_gmp` reste le repli.
            kwargs['model_path'] = selected.get('path') or _gmp(selected['id'])
            kwargs['model_key'] = selected.get('model_key')
            _console(user.id, f"Auto-selected model: {selected['id']} for classes {selected['classes']}")
            logger.info(f"[ModelSelection] Using ModelSelector result: {selected['id']} (overriding user default)")

    # ======================================================================
    # SINGLE MODEL PATH: Standard processing (existing flow)
    # ======================================================================
    # Model selection (only if not already set by parallel check above).
    # `models` (multi-modèles) court-circuite : la couverture a déjà tranché, refaire une
    # sélection mono-modèle ici ne servirait à rien et brouillerait la trace console.
    if 'model_path' not in kwargs and 'models' not in kwargs:
        # Le modèle de la card s'il en porte un ; sinon la COUVERTURE des classes, brique commune
        # (`model_coverage`, par `needs_parallel_detection`) — seule source : le catalogue.
        # L'ancien sélecteur mono-modèle qui vivait ici (scan à côté du catalogue, modèle deviné
        # par son NOM de fichier, puis `yolov8m_faces&plates_720p.pt` écrit en dur) est RETIRÉ le
        # 2026-10-12 (`REMOVAL_LEDGER R117`, décision de Fabien) : rien ne couvre → on s'arrête
        # en nommant ce qui manque, jamais un autre modèle que celui qui convient.
        if user_specified_model:
            kwargs['model_path'] = model_path_for(user_specified_model)
            kwargs['model_key'] = user_specified_key
            _console(user.id, f"Using media-specific model: {user_specified_model}")
        else:
            # Hors SAM3, la couverture a déjà parlé ci-dessus ; avec SAM3, c'est son REPLI YOLO
            # qu'on prépare — par la même couverture.
            cover = (parallel_info if should_check_parallel
                     else needs_parallel_detection(kwargs['classes2blur'], precision_level))
            chosen = cover.get('models') or []
            if len(chosen) == 1:
                kwargs['model_path'] = chosen[0].get('path')
                kwargs['model_key'] = chosen[0].get('model_key')
            elif chosen:
                kwargs['models'] = [{'path': m['path'], 'name': m.get('name'),
                                     'classes': m.get('classes'), 'model_key': m.get('model_key')}
                                    for m in chosen]
            elif not use_sam3:
                missing = cover.get('unsupported_classes') or kwargs['classes2blur']
                if not missing:
                    raise ValueError("Aucune classe à flouter : choisissez au moins une classe "
                                     "dans les réglages de l'élément.")
                raise ValueError(f"Aucun modèle installé ne détecte : {', '.join(missing)} — "
                                 "installez un détecteur qui les porte, ou retirez-les des "
                                 "classes à flouter.")

    # Les modèles EMPLOYÉS, en clés de catalogue, pour la ligne d'exécution — ce que le réglage
    # ne dit pas quand il est resté « auto ». SAM3 n'est pas nommé : `detect_media` peut se
    # replier sur YOLO sans le rendre, et une ligne ne nomme pas un modèle qui n'a pas tourné.
    used_models = []
    if not use_sam3:
        chosen = kwargs.get('models') or [{'path': kwargs.get('model_path'),
                                           'model_key': kwargs.get('model_key')}]
        used_models = [key for key in (m.get('model_key') or _catalogue_key(m.get('path'))
                                       for m in chosen if m.get('model_key') or m.get('path'))
                       if key]
    return kwargs, used_models


def _partial_frames(media):
    """L'aperçu « pendant » d'une VIDÉO (une image n'a qu'une frame), si la card le demande
    (`show_preview`) — brique commune `preview_utils.PartialFrames`."""
    if normalize_types([media.file_ext]) != ['video'] or not media.show_preview:
        return None
    from wama.common.utils.preview_utils import PartialFrames
    folder = os.path.join(get_app_media_path('anonymizer', media.user_id, 'output'), 'partials')
    return PartialFrames('anonymizer', media.id, folder)


def _drawn(media, image, found):
    """La vue « Détection » d'une frame : ce que la card demande d'afficher (`show_boxes`,
    `show_labels`, `show_conf`) — ces réglages pilotaient une fenêtre OpenCV côté serveur
    (`track(show=…)`), que personne ne voyait ; ils pilotent désormais l'aperçu."""
    from wama.common.utils.detections import draw
    return draw(image, found, **media.draw_options())


def _segmentation_note(media, doc):
    """Ce qui empêche la SEGMENTATION demandée, dit en clair — ou '' quand elle a eu lieu ou
    n'était pas demandée. Demandée : le curseur au-delà de son seuil, ou le réglage explicite.

    Né de la card #1026 (2026-10-05) : curseur à 50, des visages en RECTANGLES, et rien ne le
    disait. Le seul modèle qui segmente les visages au catalogue n'était pas INSTALLÉ ; la
    couverture retombait sur un détecteur sans un mot. On nomme ce qui manque, et où l'obtenir."""
    from wama.common.services.model_coverage import segmentation_for_intent
    wanted = bool(media.use_segmentation) or segmentation_for_intent(media.precision_level)
    if not wanted or doc.get('engine') != 'yolo':
        return ''
    if any(d.get('polygons') for f in doc.get('frames') or [] for d in f['d']):
        return ''
    if not doc.get('frames'):
        return ''
    from wama.common.services.model_coverage import formes_equivalentes
    from wama.model_manager.models import AIModel
    asked = set()
    for name in doc.get('classes') or []:
        asked |= formes_equivalentes(name)
    missing = []
    for key, caps in (AIModel.objects.filter(source='anonymizer', is_available=False)
                      .values_list('model_key', 'capabilities')):
        caps = caps or {}
        covered = {c.lower() for c in (caps.get('classes') or [])}
        if caps.get('task') == 'segment' and covered & asked:
            missing.append(key.split(':')[-1])
    if missing:
        return ("Segmentation demandée, mais aucun modèle de segmentation INSTALLÉ ne couvre "
                f"{', '.join(sorted(doc.get('classes') or []))} : contours rectangulaires. À "
                f"installer depuis le Model Manager : {', '.join(sorted(missing))}.")
    return ("Segmentation demandée, mais aucun modèle du catalogue ne segmente "
            f"{', '.join(sorted(doc.get('classes') or []))} : contours rectangulaires.")


def _detect(media, ctx):
    """GLU du process `detect` (« Détection », 2026-10-04) : choix du ou des modèles, détection
    (YOLO ou SAM3), document `detections` écrit dans la sortie de l'app et posé sur la card
    (`detections_file`). Rien n'est flouté ici : c'est le process suivant, qui le relit.

    Pendant une vidéo, l'aperçu montre la frame courante avec ses détections dessinées."""
    from wama.common.services.output_process import drop_previous_outputs
    from wama.common.utils import detections
    if not media.file:
        raise ValueError("Média sans fichier (ni URL rapatriée) : rien à traiter.")
    user = media.user
    kwargs, used_models = _detection_kwargs(media, user, ensure_model=ctx.ensure_model)
    # Une description comprise À CE lancement (texte libre, jamais compris avant) qui demande des
    # attributs : la qualification est activée maintenant, mais les étapes de ce lancement sont
    # choisies (`steps_to_run`, au départ de la tâche) — elle aura lieu au suivant. Comprise
    # avant (✨, lancement passé), le départ de la tâche l'a déjà activée (`process_single_media`).
    if switch_requested_qualification(media, kwargs.get('plan') or []):
        _console(user.id, "Ce lancement ne qualifie pas encore les objets : tous ceux des concepts "
                          "demandés seront floutés. ▶ qualifie puis floute de nouveau, sans "
                          "redétecter.", 'warning')
    # Un modèle employé absent (désigné sur la card — déjà demandé ci-dessus, avant d'être lu —,
    # ou SAM3) : la route l'installe, la tâche attend — jamais un téléchargement par la librairie
    # au chargement, ni un repli muet.
    for key in used_models + ([SAM3_KEY] if kwargs.get('use_sam3') else []):
        ctx.ensure_model(key)
    _console(user.id, f"Détection — média {media.id}…")
    ctx.progress(2)

    frames = _partial_frames(media)

    def on_frame(index, image, found):
        if frames is not None and frames.due():
            frames.publish({'detection': ('Détection', _drawn(media, image, found))}, index=index)

    kwargs['on_frame'] = on_frame
    kwargs['progress'] = lambda done, total: ctx.progress(min(99, int(done * 100 / max(total, 1))))
    try:
        doc = detect_media(**kwargs)
    finally:
        if frames is not None:
            frames.close()
    # Ce que le routeur a COMPRIS de la description — concept par concept, qui l'a cherché — gardé
    # avec ce qui a été trouvé : la page et la card le relisent (`route_concepts`, 2026-11-24).
    if kwargs.get('plan'):
        doc['plan'] = kwargs['plan']

    rel, target = ctx.output_place('.json', nature='detections', source_name=kwargs['media_path'],
                                   model=doc.get('tag') or doc.get('engine') or 'yolo')
    detections.write(target, doc)
    # Le document d'avant part s'il n'a plus le même nom (moteur changé) ; l'original que garde
    # la SORTIE n'est pas le sien : il reste (`natives=False`).
    drop_previous_outputs(media, 'detections_file', keep=[target], natives=False)
    media.detections_file.name = rel
    found = detections.count(doc)
    shown = len(doc.get('frames') or [])
    _console(user.id, f"Détection : {found} objet(s) sur {shown} image(s)"
             + ("" if found else " — rien ne sera flouté"), 'info' if found else 'warning')
    note = _segmentation_note(media, doc)
    if note:
        _console(user.id, note, 'warning')
    return {
        'fields': {'detections_file': rel},
        'output_ref': rel,
        'eta': anonymizer_eta_key_size(media),
        'label': os.path.basename(getattr(media.file, 'name', '') or '') or f"média #{media.id}",
        'console_success': f"Détection : {found} objet(s) ✔",
        'models': used_models or None,
    }


def _upstream_detections(media, process_key):
    """Le document de détections que le process LIT : la sortie du plus proche amont qui en rend
    (`AppPipeline.upstream_output` — la qualification quand elle a lieu, sinon la détection),
    jamais le champ seul (`output_of`, 2026-10-21)."""
    from django.conf import settings
    from wama.common.utils import detections
    from .function_specs import PIPELINE
    rel = PIPELINE.upstream_output(media, process_key, 'detections')
    if not rel:
        raise RuntimeError("aucune détection — relancer la détection.")
    try:
        return detections.read(os.path.join(settings.MEDIA_ROOT, rel))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"détections illisibles ({exc}) — relancer la détection.") from exc


def _qualify(media, ctx):
    """GLU du process `qualify` (« Qualification », 2026-11-24, `ROADMAP §17quater` B) : chaque
    objet détecté reçoit sa couleur majoritaire et sa taille, et son plan quand la profondeur est
    demandée — la brique commune `detection_attributes` ; le modèle de profondeur est installé
    par la route (`ctx.ensure_model`) et lu par le moteur commun (`depth_engine`). Rien n'est
    flouté : le floutage relit ce document."""
    from wama.common.utils import detection_attributes, detections
    from wama.common.services.output_process import drop_previous_outputs
    if not media.file:
        raise ValueError("Média sans fichier (ni URL rapatriée) : rien à qualifier.")
    try:
        doc = _upstream_detections(media, 'qualify')
    except RuntimeError as exc:
        raise RuntimeError(f"Qualification : {exc}") from exc
    user = media.user
    depth = None
    if media.qualify_depth:
        from wama.common.backends import depth_engine
        key = depth_engine.DEFAULT_DEPTH_MODEL
        ctx.ensure_model(f'huggingface:{key}')
        depth = lambda image: depth_engine.estimate_depth(image, model_key=key)[0]   # noqa: E731
        doc['depth_metric'] = bool(depth_engine.depth_model_spec(key)['metric_scale'])
    video = doc.get('media') == 'video'
    frame_numbers = [frame['i'] for frame in doc.get('frames') or []]
    _console(user.id, f"Qualification — {len(frame_numbers)} image(s) à qualifier…")
    ctx.progress(2)
    total = max(len(frame_numbers), 1)

    def frames():
        for done, item in enumerate(detection_attributes.iter_frames(
                media.file.path, frame_numbers, media='video' if video else 'image')):
            ctx.progress(min(99, int((done + 1) * 100 / total)))
            yield item

    # Une vidéo : la profondeur une image par seconde (le plan d'un objet suivi se reprend sur sa
    # piste) ; une image : sur elle.
    step = max(1, int(round(float(doc.get('fps') or 0)))) if video else 1
    qualified = detection_attributes.qualify(doc, frames(), depth=depth, depth_every=step)
    rel, target = ctx.output_place('.json', nature='detections', source_name=media.file.path,
                                   model='qualified')
    detections.write(target, qualified)
    drop_previous_outputs(media, 'qualified_file', keep=[target], natives=False)
    media.qualified_file.name = rel
    said = ', '.join(f"{name} : {', '.join(getattr(detections, prop)(qualified)) or '—'}"
                     for name, prop in (('couleurs', 'colors'), ('tailles', 'sizes'),
                                        ('plans', 'planes'))
                     if name != 'plans' or depth is not None)
    _console(user.id, f"Qualification — {said}")
    return {
        'fields': {'qualified_file': rel},
        'output_ref': rel,
        'label': os.path.basename(getattr(media.file, 'name', '') or '') or f"média #{media.id}",
        'console_success': "Qualification ✔",
        'models': [f'huggingface:{depth_engine.DEFAULT_DEPTH_MODEL}'] if depth is not None else None,
    }


#: « Ce qu'on floute » sur les ATTRIBUTS d'une qualification : réglage → attribut écarté.
SKIPPED_ATTRIBUTES = {'blur_skip_colors': 'color', 'blur_skip_sizes': 'size',
                      'blur_skip_planes': 'plane'}


def _blur(media, ctx):
    """GLU du process `blur` (« Floutage », 2026-10-04) : le média réécrit depuis son document de
    détections — intensité, contour progressif, agrandissement de la zone, interpolation des
    trous d'une piste. Aucun modèle n'est chargé : changer un réglage de flou ne redétecte pas.

    Pendant une vidéo, l'aperçu offre DEUX vues de la frame courante — détections dessinées,
    frame floutée — entre lesquelles l'inspecteur bascule (variantes de `preview_utils`)."""
    from wama.common.utils import detections
    from wama.common.utils.blur_utils import blur_detections
    from wama.common.utils.detection_attributes import measures_of
    if not media.file:
        raise ValueError("Média sans fichier (ni URL rapatriée) : rien à traiter.")
    # Le plus proche amont qui rend des détections : la QUALIFICATION quand elle a lieu, sinon la
    # détection (`upstream_output`, 2026-11-24).
    try:
        doc = _upstream_detections(media, 'blur')
    except RuntimeError as exc:
        raise RuntimeError(f"Floutage : {exc}") from exc
    # Les corrections humaines (page de correction, chantier SURFACES) : une couche à part,
    # réappliquée ici à chaque floutage — une détection relancée ne les perd pas.
    doc = detections.apply_corrections(doc, media.detection_corrections)
    # La DEMANDE (le `plan` du document, 2026-11-25) : attributs (« red car » cherché par un
    # détecteur à classes), relation (« face of red person »), rang (« nearest car ») — ne restent
    # que les objets qui y répondent ; rien n'est écarté sans preuve (non qualifié : il reste).
    asked = list(dict.fromkeys(detections.common_label(step['concept'])
                               for step in doc.get('plan') or () if measures_of(step)))
    if asked and not doc.get('qualified'):
        _console(media.user_id, "Floutage : objets non qualifiés — tous les "
                                + ', '.join(f"« {label} »" for label in asked)
                                + " sont floutés.", 'warning')
    doc = detections.within_request(doc)
    # « Ce qu'on floute » (2026-11-19) : les libellés décochés restent nets — choisis parmi ce que
    # la détection a trouvé, sans la refaire. Une zone ajoutée à la main suit sa classe.
    skipped = list(getattr(media, 'blur_skip_labels', None) or [])
    doc = detections.without_labels(doc, skipped)
    # …et les ATTRIBUTS décochés d'une qualification (2026-11-24) — un objet non qualifié, ou qui
    # ne porte pas l'attribut, reste flouté.
    by_attribute = {attr: list(getattr(media, name, None) or [])
                    for name, attr in SKIPPED_ATTRIBUTES.items()}
    doc = detections.without_attributes(doc, by_attribute)
    skipped += [value for values in by_attribute.values() for value in values]
    user = media.user
    if skipped:
        _console(user.id, f"Floutage : laissé net — {', '.join(skipped)}", 'info')
    source = media.file.path   # le fichier de la card, pointé ou non (cf. `_detect`, R104)
    video = doc.get('media') == 'video'
    frames_map = detections.by_frame(
        doc, interpolate=video and media.interpolate_detections,
        max_gap=detections.max_gap_for(doc.get('fps'), media.max_interpolation_frames),
        max_extrapolation=media.max_extrapolation_frames if video else 0)
    # Le RENDU (2026-11-25, C) : flou, pixellisation, masque plein ; et l'inversion — tout sauf la
    # sélection, les images sans objet comprises (`paint_empty`).
    invert = bool(getattr(media, 'blur_invert', False))
    settings_ = {'blur_ratio': media.blur_ratio, 'rounded_edges': media.rounded_edges,
                 'progressive_blur': media.progressive_blur,
                 'roi_enlargement': media.roi_enlargement,
                 'mode': getattr(media, 'blur_mode', None) or 'blur', 'invert': invert}

    def blur_frame(image, found):
        return blur_detections(image, found, **settings_)

    _rel, target = ctx.output_place('', source_name=source,
                                    model=doc.get('tag') or doc.get('engine') or 'yolo')
    preview = _partial_frames(media)

    def on_frame(index, original, painted, found):
        if preview is not None and preview.due():
            preview.publish({'detection': ('Détection', _drawn(media, original, found)),
                             'blur': ('Floutage', painted)}, index=index)

    _console(user.id, f"Floutage — média {media.id}…")
    ctx.progress(2)
    try:
        written = detections.rewrite_media(
            source, frames_map, blur_frame, target, on_frame=on_frame, paint_empty=invert,
            progress=lambda done, total: ctx.progress(min(99, int(done * 100 / max(total, 1)))))
    finally:
        if preview is not None:
            preview.close()

    # La sortie RÉELLEMENT écrite, posée sur le média (l'ancienne part si elle n'est plus la
    # même). Le format et la qualité de sortie sont le process suivant, `output` (`_output`).
    try:
        media.refresh_from_db(fields=['output_file'])
    except media.__class__.DoesNotExist:
        raise RuntimeError("Le média a été supprimé pendant son traitement.")
    _record_output(media, written)
    if not media.output_file.name:
        raise RuntimeError("Le floutage n'a écrit aucun fichier.")
    from wama.common.services.output_process import generated
    return generated(
        [written],
        fields={'output_file': media.output_file.name},
        eta=anonymizer_blur_eta_key_size(media),
        label=os.path.basename(getattr(media.file, 'name', '') or '') or f"média #{media.id}",
        console_success=f"Floutage ✔ ({detections.count(doc)} objet(s))")


# ----------------------------------------------------------------------
# Domaine DOCUMENT (2026-11-02, ROADMAP §16.4bis) — trois glus, la forme d'origine gardée
# ----------------------------------------------------------------------
def _document_eta(media, process):
    """Clé + taille ETA d'un process du DOCUMENT : APPRISE seulement (a priori nul, la règle de
    `blur_eta`), à la taille du fichier — un coût qui suit le volume à lire, sans ouvrir le fichier
    à chaque relecture de la barre."""
    try:
        size = max(os.path.getsize(media.file.path) / 1_000_000.0, 0.01)
    except (OSError, ValueError):
        size = 1.0
    return (f'anonymizer:{process}:doc', size, 'mb', True, 0.0)   # l'unité du converter


def ocr_eta(media):
    return _document_eta(media, 'ocr')


def detect_text_eta(media):
    return _document_eta(media, 'detect_text')


def occult_text_eta(media):
    return _document_eta(media, 'occult_text')


def _ocr(media, ctx):
    """GLU du process `ocr` : le process COMMUN « OCR des scans et des images » (`ocr_process`) —
    les pages sans couche texte et les images des pages natives, leurs lignes rangées sur la card
    (`ocr_file`)."""
    from wama.common.services.ocr_process import ocr_step
    return ocr_step('file', 'ocr_file')(media, ctx)


def _detect_personal_data(media, ctx):
    """GLU du process `detect_text` : les données personnelles du document, par la brique de
    confidentialité (`common/privacy` : Presidio orchestre les motifs et les détecteurs installés,
    service :8003 ou moteur dans ce process) sur la couche texte commune, les lignes de l'OCR
    comprises (`read_ocr_file`) — le document `detections` en forme texte (`span`), posé sur la
    card comme celui d'une image. Un détecteur qui n'a pas pu se charger est NOMMÉ."""
    from wama.common.privacy.service_client import detect_file
    from wama.common.services.ocr_process import read_ocr_file
    from wama.common.services.output_process import drop_previous_outputs
    from wama.common.utils import detections
    if not media.file:
        raise ValueError("Document sans fichier (ni URL rapatriée) : rien à traiter.")
    user = media.user
    _console(user.id, f"Détection des données personnelles — document {media.id}…")
    ctx.progress(5)
    from wama.common.privacy.service_client import PrivacyServiceLoading
    try:
        doc = detect_file(media.file.path, ocr=read_ocr_file(media, 'ocr_file'))
    except PrivacyServiceLoading as e:
        # Le service démarre (ses détecteurs se chargent) : la tâche rend son worker et revient —
        # la politique du squelette commun, celle du service de voix (60 × 10 s, puis échec dit).
        from wama.common.utils.task_skeleton import ServiceNotReady
        raise ServiceNotReady(
            "Service de confidentialité en chargement", countdown=10, max_attempts=60,
            gave_up="Service de confidentialité non disponible après 10 minutes d'attente "
                    "(60 tentatives)") from e
    rel, target = ctx.output_place('.json', nature='detections', source_name=media.file.path,
                                   model='presidio')
    detections.write(target, doc)
    drop_previous_outputs(media, 'detections_file', keep=[target], natives=False)
    media.detections_file.name = rel
    found = detections.count(doc)
    missing = list(doc.get('unavailable') or [])
    if missing:
        _console(user.id, "Détecteur(s) indisponible(s), la détection s'est faite sans eux : "
                          + ', '.join(missing), 'warning')
    _console(user.id, f"Détection : {found} passage(s) à occulter"
             + ("" if found else " — rien ne sera occulté"), 'info' if found else 'warning')
    return {
        'fields': {'detections_file': rel},
        'output_ref': rel,
        'label': f"{found} passage(s)" + (f", sans {', '.join(missing)}" if missing else ''),
        'console_success': f"Détection : {found} passage(s) ✔",
        'models': list(doc.get('models') or []) or None,
    }


def _occult_text(media, ctx):
    """GLU du process `occult_text` : le document réécrit SUR PLACE, chaque passage détecté (les
    corrections humaines réappliquées, comme au floutage) remplacé par son libellé, sa forme
    gardée ; sur un scan, les pixels du passage effacés (`privacy.occult_file`, le MÊME OCR qu'à
    la détection). Le fichier produit est relu : un passage qui y reste est DIT, jamais tu."""
    from wama.common.privacy.service_client import occult_file
    from wama.common.services.ocr_process import read_ocr_file
    from wama.common.utils import detections
    if not media.detections_file:
        raise RuntimeError("Occultation : aucune détection — relancer la détection.")
    try:
        doc = detections.read(media.detections_file.path)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Occultation : détections illisibles ({exc}) — relancer la "
                           "détection.") from exc
    doc = detections.apply_corrections(doc, media.detection_corrections)
    source = media.file.path
    _rel, target = ctx.output_place(os.path.splitext(source)[1], source_name=source,
                                    model='presidio')
    ctx.progress(10)
    report = occult_file(source, target, doc, ocr=read_ocr_file(media, 'ocr_file'))
    try:
        media.refresh_from_db(fields=['output_file'])
    except media.__class__.DoesNotExist:
        raise RuntimeError("Le média a été supprimé pendant son traitement.")
    _record_output(media, report['path'])
    if not media.output_file.name:
        raise RuntimeError("L'occultation n'a écrit aucun fichier.")
    remaining = report.get('remaining') or []
    if remaining:
        _console(media.user.id, f"⚠ {len(remaining)} passage(s) encore lisible(s) dans le "
                                f"document produit : " + ', '.join(remaining[:5])
                 + ('…' if len(remaining) > 5 else ''), 'warning')
    return {
        'fields': {'output_file': media.output_file.name},
        'output_ref': media.output_file.name,
        'label': (f"⚠ {len(remaining)} passage(s) encore lisible(s)" if remaining
                  else f"{detections.count(doc)} passage(s) occulté(s)"),
        'console_success': "Occultation ✔",
    }


# ----------------------------------------------------------------------
# Fonction pour lancer le traitement du média
# ----------------------------------------------------------------------
def detect_media(**kwargs):
    """Les DÉTECTIONS d'un média, en document `detections` (`common/utils/detections`) : SAM3
    quand la card décrit en texte ce qu'il faut flouter (et que SAM3 est là, et le prompt
    valide), sinon le détecteur YOLO (un ou plusieurs modèles). Rien n'est écrit ni flouté :
    la tâche range le document, le process « Floutage » le relit (2026-10-04)."""
    use_sam3 = kwargs.get('use_sam3', False)
    sam3_prompt = kwargs.get('sam3_prompt', '')
    user_id = kwargs.get('user_id')
    source_dir = get_app_media_path('anonymizer', user_id, 'input') if user_id else None
    dest_dir = get_app_media_path('anonymizer', user_id, 'output') if user_id else None

    if use_sam3 and sam3_prompt and sam3_prompt.strip():
        reason = None
        if not check_sam3_installed():
            reason = "SAM3 not installed"
        else:
            is_valid, error = validate_sam3_prompt(sam3_prompt)
            if not is_valid:
                reason = f"Invalid SAM3 prompt: {error}"
        if reason is None:
            try:
                # Le MODÈLE porte son moteur ; le backend s'en dérive (2026-09-07).
                from wama.common.backends.manager import backend_for_key
                SAM3Processor = backend_for_key(SAM3_KEY)
                if SAM3Processor is None:
                    raise ImportError("anonymizer:sam3 : aucun backend résolu depuis le "
                                      "catalogue (ligne absente, ou sans moteur déclaré)")
                if user_id:
                    _console(user_id, f"Using SAM3 with prompt: {sam3_prompt[:50]}...")
                processor = SAM3Processor(source_dir=source_dir, destination_dir=dest_dir)
                processor.load_model('auto')
                _last_pct = [0]

                def _sam3_progress(pct):
                    if user_id and (pct - _last_pct[0] >= 10 or pct >= 100):
                        _last_pct[0] = pct
                        _console(user_id, f"SAM3 progress: {pct}%")
                return processor.detect(progress_callback=_sam3_progress, **kwargs)
            except Exception as e:
                reason = f"SAM3 error: {e}"
        if user_id:
            _console(user_id, f"Warning: {reason}. Falling back to YOLO.")
        if not kwargs.get('models') and not kwargs.get('model_path'):
            # Le repli se prépare par la couverture commune (R117) : rien ne la couvre, on le dit.
            raise ValueError(f"{reason} — et aucun détecteur installé ne couvre "
                             f"{', '.join(kwargs.get('classes2blur') or []) or 'ces classes'} "
                             "pour le repli.")

    if user_id:
        _console(user_id, f"Détecteurs pour les classes : {kwargs.get('classes2blur', [])}")
    # L'ENSEMBLE (2026-10-10) : les modèles ultralytics passent ensemble par `Anonymize`, chaque
    # autre modèle (EgoBlur, RT-DETR…) par SON backend, et les documents se réunissent.
    from wama.common.services.detection_ensemble import detect_with_models
    models = kwargs.pop('models', None) or [{'path': kwargs.get('model_path'),
                                             'model_key': kwargs.get('model_key'),
                                             'classes': None}]
    return detect_with_models(models, source_dir=source_dir, destination_dir=dest_dir, **kwargs)


# ----------------------------------------------------------------------
# Arrêt d'un traitement utilisateur
# ----------------------------------------------------------------------
def stop_process(user_id):
    """
    Demande l'arrêt d'un traitement utilisateur en cours.
    Le flag sera vérifié dans la boucle de process_single_media.
    """
    cache.set(f"stop_process_{user_id}", True, timeout=60)
    print(f"Process stop demandé pour user {user_id}")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def set_media_progress(media_id: int, percent: int) -> None:
    """Persist media progress in cache and DB (clamped 0..100)."""
    try:
        pct = max(0, min(100, int(percent)))
        cache.set(f"media_progress_{media_id}", pct, timeout=3600)
        Media.objects.filter(pk=media_id).update(blur_progress=pct)
    except Exception:
        # best effort only
        pass


# ── Suivre un objet DÉSIGNÉ sur la page de correction (2026-11-16) ───────────────────────────
# Décision de Fabien : un clic sur un objet NON détecté le suit sur toute la séquence — sur le
# patron de l'écriture à la lecture du transcriber. Mécanique = la boucle COMMUNE
# `playhead_follow` ; enchaînement des tranches = `common/services/object_tracking` ; ce qui est
# propre ici : le moteur (SAM3 et son module de suivi), le média de la card, la cession aux
# traitements de la file. ⚠ Le serveur N'ÉCRIT PAS les corrections : il dépose des PROPOSITIONS
# en cache, la page les accepte ou les refuse et son enregistrement en fait une version.

#: La clé de catalogue du moteur de suivi — le SAM3 que la détection par description charge déjà.
TRACKING_MODEL_KEY = SAM3_KEY


def track_channel(media_id):
    from wama.common.services.playhead_follow import Channel
    return Channel('anonymizer_track', media_id)


@shared_task(bind=True)
def live_track_task(self, media_id: int):
    """La boucle de suivi : suit le curseur de la page (`{'targets': [{id, i, point}]}`) et suit,
    tranche par tranche, chaque objet désigné — vers l'avant puis vers l'arrière. Chaque tranche
    dépose un résultat `{'target', 'frames': [{i, box}], 'done'}`. Tâche du module `tasks` : file
    GPU. Cède la place dès qu'un média de la file a la main."""
    from wama.common.backends.manager import backend_for_key
    from wama.common.models import JOB_AWAITING_RESOURCES, JOB_RUNNING
    from wama.common.services import object_tracking as tracking
    from wama.common.services.playhead_follow import append_result, follow

    close_old_connections()
    try:
        media = Media.objects.get(pk=media_id)
    except Media.DoesNotExist:
        return {'ok': False, 'error': f'Media {media_id} introuvable'}
    channel = track_channel(media.pk)
    state = {'engine': None}

    def start():
        if not check_sam3_installed():
            raise RuntimeError("SAM3 n'est pas installé : le suivi d'un objet désigné en a besoin")
        Engine = backend_for_key(TRACKING_MODEL_KEY)
        if Engine is None or not getattr(Engine, 'supports_object_tracking', False):
            raise RuntimeError(f"{TRACKING_MODEL_KEY} : aucun moteur de suivi résolu")
        engine = Engine()
        engine.load_model('tracker')
        state['engine'] = engine
        _console(media.user_id, "Suivi d'objet : SAM3 chargé (libéré après 90 s sans demande)")

    def should_yield():
        busy = (Media.objects.filter(status__in=(JOB_RUNNING, JOB_AWAITING_RESOURCES))
                .exclude(pk=media.pk).exists())
        if busy:
            _console(media.user_id, "Un traitement attend : le suivi d'objet s'interrompt "
                                    "(désignez l'objet de nouveau ensuite)", level='warning')
        return busy

    def step(cursor):
        progress = cache.get(channel.key('progress')) or {}
        for target in cursor.get('targets') or []:
            mine = progress.setdefault(target['id'], {})
            planned = tracking.next_slice(mine, target)
            if planned is None:
                continue
            direction, frame, designation = planned
            window = state['engine'].TRACK_WINDOW
            found = state['engine'].track_object(
                media.file.path, frame, count=window,
                reverse=direction == tracking.BACKWARD, **designation)
            frames = tracking.advance(mine, direction, found, window)
            cache.set(channel.key('progress'), progress, TRACK_TTL)
            append_result(channel, {'target': target['id'], 'frames': frames,
                                    'done': tracking.finished(mine, target)}, TRACK_TTL)
            return True
        return False

    try:
        reason = follow(channel, self.request.id, step, on_start=start, should_yield=should_yield)
        if reason not in ('cooldown', 'already_running'):
            _console(media.user_id, "Suivi d'objet arrêté — SAM3 libéré")
        return {'ok': True, 'reason': reason}
    except Exception as exc:
        _console(media.user_id, f"Suivi d'objet interrompu ({exc})", level='warning')
        append_result(channel, {'error': str(exc)[:300]}, TRACK_TTL)
        return {'ok': False, 'error': str(exc)}
    finally:
        if state['engine'] is not None:
            try:
                state['engine'].unload()
            except Exception:
                pass


#: Durée de vie des propositions et de l'avancement d'un suivi.
TRACK_TTL = 3600
