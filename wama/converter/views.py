"""
WAMA Converter — Views

Endpoints:
  GET  /converter/                  IndexView (queue)
  POST /converter/upload/           upload (create ConversionJob)
  POST /converter/<pk>/start/       start conversion task
  GET  /converter/<pk>/status/      job status JSON
  GET  /converter/<pk>/download/    download output file
  POST /converter/<pk>/delete/      delete job
  POST /converter/<pk>/duplicate/   duplicate job
  POST /converter/start-all/        start all PENDING jobs
  POST /converter/clear-all/        clear all jobs
  POST /converter/quick/            quick conversion (from filemanager / other apps)
"""

import logging
from pathlib import Path

from django.shortcuts import render, get_object_or_404

from django.views import View
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST
from django.core.cache import cache
from django.db import transaction

from .models import ConversionJob, ConversionProfile, ConversionBatch
from .utils.format_router import (SUPPORTED_CONVERSIONS, detect_media_type, get_output_formats,
                                  output_format_for, remember_output_format)
from ..accounts.views import get_or_create_anonymous_user
# Le chemin d'un fichier d'app se COMPOSE (`get_relative_media_path`), il ne
# s'écrit pas — préalable au domicile unique par utilisateur (2026-09-11).
from wama.common.utils.media_paths import get_relative_media_path

logger = logging.getLogger(__name__)


# ⚠ `_is_app_owned` vivait ici jusqu'au 2026-09-22 : la règle « ne supprimer que les fichiers
# du dossier de l'app, jamais ceux qu'on ne fait que RÉFÉRENCER » (envoi depuis le gestionnaire
# de fichiers, conversion rapide). Elle était JUSTE — mais n'existait que pour cette app, et les
# 10 autres détruisaient un fichier référencé. Elle vit désormais dans la brique commune
# (`queue_duplication.owns_file`, appelée par `safe_delete_file`), pour tout le parc.


def _auto_wrap_orphans(user):
    """Range les jobs de file sans lot, chacun dans un lot d'un DE SA NATURE — brique COMMUNE
    (`auto_wrap_orphans`, forme à FK directe depuis le 2026-11-02 : la boucle était écrite ici).
    Les jobs éphémères d'une conversion rapide n'entrent jamais dans un lot (`scope`)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    from .models import ConversionBatch
    auto_wrap_orphans(user, work_model=ConversionJob, batch_model=ConversionBatch,
                      batch_extra=lambda job: {'media_type': job.media_type},
                      scope={'ephemeral': False})


def _converter_nature(job):
    """Nature d'un job de conversion — ce qui peut cohabiter dans un lot.

    DEUX consommateurs, une seule déclaration : le regroupement à l'import
    (`group_into_batches_by_nature`) et la fusion par drag&drop (`group_key` de la fabrique
    de manipulation de file). Le lot PORTE cette nature (`ConversionBatch.media_type`) et son
    format de sortie en découle — un lot mixte enverrait tout au mauvais format."""
    return job.media_type


class IndexView(View):
    def get(self, request):
        import json
        # Visiteur sans compte (2026-10-04) : la page garde un `AnonymousUser` (en-tête de
        # visiteur), et la file est celle de SON identité de session (`accounts/visitors.py`,
        # posée par l'intergiciel) — le compte `anonymous` partagé, vide, tant qu'il n'a rien fait.
        user = (request.user if request.user.is_authenticated
                else getattr(request, 'wama_visitor', None) or get_or_create_anonymous_user())
        # Tout job de file appartient à un batch (batch-of-1 si fichier seul) —
        # wrap paresseux des éventuels orphelins (ex. upload direct).
        _auto_wrap_orphans(user)

        # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
        from wama.common.utils.process_control import reconcile_queue_of
        reconcile_queue_of(ConversionJob, user)

        # La FILE par la brique COMMUNE (`build_batches_list`, forme à FK directe depuis le
        # 2026-11-02) : lots visibles (reçus compris, réduits à ce qui est partagé), rangement du
        # destinataire, compteurs, ETA de lot, évaluation, référence, identité. Le converter la
        # construisait ici à la main (lot par lot, depuis les jobs), sans les attentes de
        # ressources, les périmés, l'évaluation ni la référence du lot. Les jobs éphémères d'une
        # conversion rapide n'ont jamais de lot : ils n'y sont pas.
        from wama.common.app_registry import MEDIA_CATEGORY_LABELS as _nature_labels
        from wama.common.utils.batch_common import build_batches_list
        from wama.common.utils.card_chips import common_chips_for_items
        from wama.converter.models import ConversionBatch
        from wama.converter.params import PARAMS_JSON as _PARAMS_JSON

        def _entry_extra(batch, _items, jobs):
            for j in jobs:
                _decorate_job(j)  # chips du SCHÉMA (card_chips) — même décoration que card_html
            return {
                'media_label': _nature_labels.get(batch.media_type, ''),
                # Réglages COMMUNS aux filles (slot meta_template — porté le 31/08). Les
                # réglages du converter vivent en JSON : même assiette que _decorate_job.
                'common_chips': common_chips_for_items(
                    jobs, _PARAMS_JSON,
                    values_of=lambda j: {**(j.options or {}), **(j.cross_app_options or {})}),
            }

        batches_list = build_batches_list(user, batch_model=ConversionBatch, work_attr=None,
                                          order_by='-created_at', extra=_entry_extra)
        # Les PROCESS de chaque card (pipeline, 2026-10-13) — les lignes d'exécution de la page
        # lues en UNE requête (`decorate_cards`), après les chips posés ci-dessus.
        from wama.common.services.process_pipeline import decorate_cards
        decorate_cards([j for b in batches_list for j in b['items']])

        # Tri + filtrage de la file — brique COMMUNE (toolbar _queue_toolbar), alignée sur
        # reader/composer/transcriber/describer (2026-07-10, Converter n'avait ni l'un ni l'autre).
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _name(b):
            return b['items'][0].input_filename if b['items'] else ''

        batches_list, q_sort, q_filter = apply_queue_sort_filter(request, batches_list, name_of=_name)

        # Build JS-safe dict: { image: { input: ['.jpg',…], output: ['jpg',…] }, … }
        formats_for_js = {
            media_type: {
                'input':  spec['input'],
                'output': spec['output'],
            }
            for media_type, spec in SUPPORTED_CONVERSIONS.items()
        }

        from wama.converter.params import GROUPS_JSON as CONVERTER_GROUPS_JSON
        from wama.converter.params import PARAMS_JSON as CONVERTER_PARAMS_JSON
        from wama.converter.params import _ENGINE_BY_TYPE as _ENGINE_HELP_BY_TYPE
        # Contexte NETTOYÉ le 31/08 (audit B6/B7, REMOVAL_LEDGER) : 'jobs', 'profiles' et
        # 'supported_formats' n'étaient consommés par AUCUN gabarit (grep) — la liste de
        # profils vient de profile_list en AJAX, le gabarit itère batches_list, et le front
        # lit supported_formats_json.
        return render(request, 'converter/index.html', {
            'batches_list':         batches_list,
            'supported_formats_json': json.dumps(formats_for_js),
            'params_json':          json.dumps(CONVERTER_PARAMS_JSON),  # schéma modale per-job (WamaParams)
            'groups_json':          json.dumps(CONVERTER_GROUPS_JSON),  # groupes 2 colonnes (mécanisme imager, commun)
            'engine_help_json':     json.dumps(_ENGINE_HELP_BY_TYPE),   # descriptif moteur par TYPE (modale)
            'q_sort':               q_sort,
            'q_filter':             q_filter,
            # Visiteur sans compte : ce que la page lui DIT de son essai (durée, limites).
            'visitor_trial':        _visitor_trial(request),
        })


def _visitor_trial(request):
    """Les bornes de l'essai sans compte, pour l'encart de la page — None pour un membre."""
    if request.user.is_authenticated:
        return None
    from wama.accounts import visitors
    return {'ttl_hours': int(visitors.ttl().total_seconds() // 3600),
            'max_mb': visitors.max_upload_bytes() // (1024 * 1024),
            'max_items': visitors.max_items()}


# `last_output_format` vivait ici jusqu'au 2026-10-18 : il a rejoint la table des formats
# (`format_router`), dans la cascade `output_format_for` que lisent toutes les voies de création.


def apply_birth_settings(job, media_type, options=None, inputs=None) -> list:
    """MODÈLE ÉVÉNEMENTIEL (Fabien, 02/09, ROADMAP §23.2quater) : l'élément naît COMPLET —
    les défauts applicables du schéma sont ÉCRITS en base à la création, le POST de la
    zone de composition par-dessus (le geste de l'utilisateur prime). Les chips d'une card
    fraîche sont donc pleines (demande du 31/08) ET le preset reste opérant : il n'arbitre
    plus au lancement, il ÉCRIT au clic (§23.2quater — l'ancienne règle « ne stocker que
    l'explicite » du §23.2bis est REMPLACÉE par ce modèle).

    La cascade est la cascade COMMUNE (`user_settings.new_element_settings`, 2026-10-18) :
    défauts du schéma applicables à la nature ← réglages retenus de l'auteur (ceux que le
    schéma déclare au volet) ← `options`, ce que le dépôt poste, coercé par le schéma. La
    nature (détectée) et le format (retenu PAR NATURE, `format_router.output_format_for`)
    n'en sortent jamais : l'appelant les pose. Écrit par l'écrivain de l'app
    (`poser_reglages` : types des colonnes). Posé sans sauver ; rend les champs touchés.
    Toutes les voies de création passent ici — le dépôt, le lot, la conversion rapide, l'outil
    de l'assistant et l'import du gestionnaire de fichiers ; une jumelle de bac à sable aussi
    (l'app et le modèle sont ceux du job)."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.converter.params import PARAMS_JSON as _SCH
    birth = new_element_settings(job.user, job._meta.app_label, _SCH, type(job), post=options,
                                 inputs=inputs,
                                 context={'media_type': media_type})
    for name in ('media_type', 'output_format'):
        birth.pop(name, None)
    return job.poser_reglages(birth)


@login_required
@require_POST
def upload(request):
    """Accept a file upload and create a ConversionJob (PENDING)."""
    user        = request.user
    output_fmt  = request.POST.get('output_format', '').strip().lower()

    # Note : l'import par URL depuis la card d'entrée NE passe PAS par ici. Il
    # réutilise le formalisme batch commun (URL = batch d'1 ligne → batch_preview
    # → batch_create, qui télécharge via upload_media_from_url et consolide). Voir
    # WamaBatchImport.ingestText (JS) câblé dans converter/index.html.

    # Un fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique `received_inputs` : une
    # désignation se POINTE au lieu d'être recopiée, avec le même état du volet.
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'converter')
    if not received:
        return JsonResponse({'error': received.refusal or 'Aucun fichier fourni'}, status=400)
    file_obj = received[0]

    media_type = detect_media_type(file_obj.name)
    if media_type is None:
        return JsonResponse({'error': f"Format d'entrée non supporté : {file_obj.name}"}, status=400)

    # Le format AUTOMATIQUE selon la nature (`format_router.output_format_for`, la règle de toutes
    # les voies) : le choix posté, sinon le dernier format employé pour cette nature, sinon le
    # défaut de la nature. Un choix posté qui n'est pas offert est refusé, jamais remplacé.
    chosen = output_fmt
    try:
        output_fmt = output_format_for(user, media_type, chosen)
    except ValueError as refusal:
        return JsonResponse({'error': str(refusal)}, status=400)

    # Options : la LISTE et le TYPAGE viennent du schéma (`converter/params.py`), lus par la
    # cascade commune (`apply_birth_settings`) — `channels=1` (mono) n'est pas un booléen,
    # `flip_h` est un interrupteur, `resize_w` un nombre borné. Ce que le dépôt poste devient
    # la mémoire du volet (le geste du transcriber).
    from wama.common.utils.user_settings import save_panel_settings
    from wama.converter.params import PARAMS_JSON as _SCH
    save_panel_settings(user, 'converter', _SCH, request.POST)

    job = ConversionJob.objects.create(
        user=user,
        input_file=file_obj.value,
        input_filename=file_obj.name,
        media_type=media_type,
        output_format=output_fmt,
        status='PENDING',
    )
    file_obj.record(job, 'input_file')
    from wama.common.utils.user_settings import inputs_by_port
    touched = apply_birth_settings(job, media_type, request.POST,
                                   inputs=inputs_by_port('converter', file_obj))
    if touched:
        job.save(update_fields=touched)

    # Un format CHOISI devient le défaut du prochain élément de cette nature ; un format résolu
    # automatiquement ne se retient pas (il en découle déjà).
    if chosen:
        remember_output_format(user, media_type, output_fmt)

    # Clé `id` — contrat COMMUN des vues d'upload (trou #24 de la route). Le converter était la
    # graphie divergente (`job_id`) : régénérer l'app aurait fait renvoyer `id` à une vue dont le
    # JS lisait `job_id`, donc `undefined` → aucune card, SANS erreur console. C'est exactement
    # le défaut qui a rendu converter_01 inerte le 2026-08-22. On TRADUIT (et on remplace) au
    # lieu d'émettre les deux graphies : juxtaposer aurait figé la divergence dans le contrat.
    return JsonResponse({
        'success':    True,
        'id':         job.id,
        'media_type': media_type,
        'filename':   file_obj.name,
        'output_fmt': output_fmt,
    })


def _reset_for_relaunch(job):
    """Remise à zéro avant (re)lancement, SOUS le verrou — ni la sortie ni la conversion brute :
    le résultat d'un process s'efface quand CE process est rejoué (sa glu le remplace)."""
    job.error_message = ''
    job.progress = 0


# Les fichiers que la card PRODUIT (la sortie, la conversion brute qu'un post-traitement
# reprend) : à la duplication, ce que les process ont écrit, la brique le vide elle-même
# (`AppPipeline.produced_fields`, 2026-10-21) — élément et lot.


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — le post-traitement relancé
# seul repart de la conversion brute gardée.
start_process = login_required(make_process_start_view(
    work_model=ConversionJob, task_for=lambda job: _task_for(job),
    get_user=lambda request: request.user, reset_on_start=_reset_for_relaunch))

# ▶ de la card, ▶ et 🗑 de la file : fabrique COMMUNE (`item_views.make_item_views`, ROUTE §11
# #39, 2026-10-29) — la même déclaration que lit l'outil `start_converter`. L'ancienne sortie
# n'est pas effacée au clic (pipeline, 2026-10-13) : la glu qui la réécrit la remplace. Un job
# importé par lot ou par fichier NAÎT sans format : le ▶ le refuse en le disant (job #27,
# 2026-09-14, « format vidéo non supporté : » lu comme un rejet de codec), « tout lancer » le
# saute — la règle de `batch_start`. La file est celle de la barre (sans les jobs éphémères).
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(
    work_model=ConversionJob, app_id='converter', task_for=lambda job: _task_for(job),
    get_user=lambda request: request.user, reset_on_start=_reset_for_relaunch,
    startable=lambda job: bool(job.output_format),
    unstartable_message="Format de sortie non défini — le choisir dans ⚙ Paramètres avant de lancer.",
    queryset=lambda user: ConversionJob.objects.filter(user=user, ephemeral=False),
    batch_model=ConversionBatch, item_empty_is_value=('output_format',))
start = login_required(_iv['start'])
start_all = login_required(_iv['start_all'])
clear_all = login_required(_iv['clear_all'])
# ⬇ 🗑 ⧉ ⚙ d'une card (⏹ : `cancel`, plus bas) : la fabrique COMMUNE (2026-11-02, ROUTE §11 #42
# ④), qui lit ce que l'app déclare à sa fabrique de lot — dont son lot à FK directe et la nature
# figée sur le lot (`batch_extra` : la copie seule naît dans un lot de sa nature). Spécificité
# déclarée : un format de sortie VIDE vaut « Automatique » sur la card (au lot, « ne pas toucher »).
update_settings = login_required(_iv['update_settings'])
download = login_required(_iv['download'])
delete = login_required(_iv['delete'])
duplicate = login_required(_iv['duplicate'])


def _progress_extra(job):
    """Les clés PROPRES que le JS du converter lit."""
    return {
        'output_ready': bool(job.status == 'SUCCESS' and job.output_file),
        'output_filename': job.output_filename,
        'input_filename': job.input_filename,
        'media_type': job.media_type,
        'output_format': job.output_format,
        # Options moteur + cross-app FUSIONNÉES pour le préremplissage de la modale (le JS
        # est générique, ids disjoints par construction) ; update_settings re-scinde au save.
        'options': {**(job.cross_app_options or {}), **(job.options or {})},
        # Temps réel persisté (ProcessingTimeMixin) — affiché sur la card terminée sans reload.
        'processing_display': job.processing_display,
    }


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que ses clés propres et sa file (les jobs éphémères n'y sont
# pas). Plus de triplet d'ETA de vue depuis le pipeline (2026-10-13) : la card s'estime à la
# SOMME de ses process, chacun déclarant le sien (`ProcessSpec.eta`, `tasks.*_eta`).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(
    work_model=ConversionJob, get_user=lambda request: request.user, app_id='converter',
    extra=_progress_extra,
    queryset=lambda user: ConversionJob.objects.filter(user=user, ephemeral=False))
status = login_required(_pv['progress'])
global_progress = login_required(_pv['global_progress'])


def _apply_job_settings(job, data) -> list:
    """LES réglages d'une conversion, posés sans sauver — rend les champs touchés.

    La route d'un élément (`update_settings`) ET la fabrique des vues de lot (`apply_settings`)
    passent ici : jusqu'au 2026-10-02 la vue de lot réécrivait ces règles à côté (lecture brute
    de `request.POST`, sa propre validation du format, son propre étalement du geste de
    qualité) — deux codes pour une seule règle. Un réglage refusé lève `ValueError` : la route
    d'élément répond 400, la fabrique répond 400 sans écrire AUCUNE fille du lot.

    `data` : `output_format`, puis les options — le blob `options_json` (le JS du converter,
    où une valeur VIDE remet la colonne à « non réglé ») OU les réglages postés à plat (modale
    de lot, inspecteur : seul le POSÉ arrive, `read_settings_payload` a retiré les vides —
    « ne pas toucher », jamais « effacer »).
    """
    import json as _json
    touched = []
    output_fmt = str(data.get('output_format') or '').strip().lower()
    if output_fmt or 'output_format' in data:
        # Présent et vide = « Automatique » : la cascade de toutes les voies
        # (`format_router.output_format_for`) ; un format qui n'est pas offert lève.
        job.output_format = output_format_for(job.user, job.media_type, output_fmt)
        touched.append('output_format')

    new_opts = data.get('options_json')
    if not new_opts:
        # À plat : tout ce qui n'est pas le format — `poser_reglages` ne retient que les
        # colonnes de réglage du modèle, le geste de qualité est lu juste dessous.
        new_opts = {k: v for k, v in data.items()
                    if k not in ('output_format', 'media_type', 'options_json')}
    elif not isinstance(new_opts, dict):
        try:
            new_opts = _json.loads(new_opts)
        except ValueError as exc:
            raise ValueError(f"options_json invalide : {exc}")
        if not isinstance(new_opts, dict):
            raise ValueError("options_json invalide : options_json must be an object")
    if not new_opts:
        return touched

    # ── MODÈLE ÉVÉNEMENTIEL (Fabien, 02/09) : le preset est un GESTE D'ÉCRITURE ──
    # Un preset = un profil GÉNÉRAL commun à tous (un profil = propre à l'utilisateur) :
    # choisir « web » ÉCRIT ses valeurs dans les colonnes, séance tenante — l'utilisateur VOIT
    # l'effet réel, peut le retoucher, puis l'enregistrer en profil. La colonne `quality_preset`
    # devient une TRACE (dernier preset appliqué), plus un facteur au lancement. Ordre du POST :
    # les valeurs du preset d'abord, les réglages individuels du même envoi par-dessus (le
    # geste fin prime).
    # Le CURSEUR commun (chantier C, 20/09) est le même geste d'écriture : sa valeur s'ÉTALE en
    # réglages d'encodage interpolés (`values_for_intent`), sa trace est `quality_intent` + le
    # preset le plus proche. Un preset par clé (filemanager, tool_api) reste accepté et pose la
    # trace du curseur à sa position.
    touched += _apply_quality_gesture(job, new_opts)
    spread = _quality_spread(job, new_opts)
    if spread:
        new_opts = {**spread, **{k: v for k, v in new_opts.items()
                                 if k not in ('quality_preset', 'quality_intent')}}
    # Un réglage = une COLONNE depuis le 2026-09-01 : plus de split à faire ici (le modèle sait
    # à quelle famille appartient chaque nom), et plus de JSON à écrire. `poser_reglages`
    # coerce selon le type du champ et rend les champs touchés.
    return touched + [f for f in job.poser_reglages(new_opts) if f not in touched]


def _apply_quality_gesture(job, values: dict) -> list:
    """Pose les TRACES du geste de qualité sur `job` — `quality_intent` (curseur commun) et
    `quality_preset` (clé la plus proche) — et rend les champs touchés. Le curseur prime sur une
    clé de preset envoyée en même temps ; une clé seule pose aussi la position du curseur."""
    from wama.common.utils.auto_model import read_quality_intent
    from .utils.quality_presets import (PRESET_CHOICES, intent_for_preset, preset_for_intent)
    touched = []
    raw = values.get('quality_intent')
    preset = (values.get('quality_preset') or '').strip().lower()
    if raw not in (None, ''):
        job.quality_intent = read_quality_intent(raw)
        job.quality_preset = preset_for_intent(job.quality_intent)
        touched += ['quality_intent', 'quality_preset']
    elif preset in PRESET_CHOICES:
        job.quality_preset = preset
        touched.append('quality_preset')
        position = intent_for_preset(preset)
        if position is not None:
            job.quality_intent = position
            touched.append('quality_intent')
    return touched


def _quality_spread(job, values: dict) -> dict:
    """Les réglages d'encodage que le geste de qualité ÉCRIT (`values_for_intent` pour le
    curseur, la table pour une clé de preset) — `{}` si aucun geste dans `values`."""
    from .utils.quality_presets import PRESET_CHOICES, preset_values, values_for_intent
    raw = values.get('quality_intent')
    preset = (values.get('quality_preset') or '').strip().lower()
    if raw not in (None, ''):
        return values_for_intent(job.media_type, raw)
    if preset in PRESET_CHOICES:
        return preset_values(job.media_type, preset)
    return {}


@require_GET
def api_presets(request):
    """La table des préréglages, SERVIE au client — jamais recopiée (une copie divergerait).

    Consommateur : la modale de conversion rapide du Filemanager (question Fabien 02/09 :
    « faut-il afficher les paramètres correspondants au preset ? ») — elle affiche sous le
    select l'effet RÉEL du preset choisi pour le type du fichier, sans devenir un
    formulaire : la rapidité est sa raison d'être, l'app reste le lieu du réglage fin.
    """
    from .utils.quality_presets import _PRESETS
    return JsonResponse({'presets': _PRESETS})


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = login_required(_pv['download_all'])


# ────────────────────────────────────────────────────────────────────────────
# Batch import — fichier batch d'URLs (la consolidation multi-fichiers est celle de la fabrique,
# `consolidate` plus bas, depuis le 2026-10-16)
# ────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def batch_preview(request):
    """Aperçu d'un fichier batch d'URLs/chemins (détection style synthesizer)."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response

    def _enrich(item):
        mt = detect_media_type(item.get('filename', ''))
        item['detected_type'] = mt or 'inconnu'

    return batch_media_list_preview_response(request, item_enricher=_enrich)


@login_required
@require_POST
def batch_create(request):
    """Crée des jobs depuis un fichier batch d'URLs/chemins.

    URL distante → la SOURCE est enregistrée et téléchargée dès la création, HORS de la
    requête, par le récepteur commun (`source_ingest`, 2026-10-13 — le converter était la seule
    app à télécharger dans la requête : un lot d'URL tenait la requête ouverte, et une vidéo
    longue dépassait la coupure de 120 s) ; chemin local (sous MEDIA_ROOT) → pointé ou copié.
    Chaque source → un ConversionJob PENDING, au format AUTOMATIQUE de sa nature
    (`format_router.output_format_for`) — il naissait sans format, à régler ensuite par lot.
    Consolidation par nature. Les lignes en échec sont ignorées et reportées dans `warnings`.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    from wama.common.utils.media_paths import reference_or_copy

    user = request.user
    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    job_ids = []
    for item in items:
        src = (item.get('path') or '').strip()
        if not src:
            continue
        try:
            if src.startswith(('http://', 'https://')):
                # Nature connue AVANT le téléchargement (extension, plateforme : la table commune
                # `url_ingest.url_nature`) ; inconnue (une page sans extension), c'est le `derive`
                # déclaré qui la pose à l'arrivée du fichier. Le nom aussi arrive avec le fichier
                # (`name_field` de la spec), d'où un `input_filename` vide ici.
                from wama.common.utils.url_ingest import url_nature
                from .utils.format_router import SUPPORTED_CONVERSIONS
                nature = url_nature(src)
                if nature and nature not in SUPPORTED_CONVERSIONS:
                    warnings.append(f'Type non supporté : {src}')
                    continue
                media_type = detect_media_type((item.get('filename') or '').strip()) or nature
                # Le format suit la nature dès qu'elle est connue ; sinon, c'est le `derive`
                # de l'arrivée du fichier qui le pose avec elle (`tasks._derive_media_type`).
                job = ConversionJob.objects.create(
                    user=user, input_filename='', media_type=media_type or '',
                    source_url=src, status='PENDING',
                    output_format=output_format_for(user, media_type) if media_type else '',
                )
                # Né complet par la cascade commune, comme un fichier déposé (2026-10-18 : les
                # filles de lot naissaient sans réglages). Nature encore inconnue : seuls les
                # réglages qui n'en dépendent pas s'appliquent ; la tâche lit les autres.
                touched = apply_birth_settings(job, media_type or '', request.POST)
                if touched:
                    job.save(update_fields=touched)
                job_ids.append(job.id)
                continue

            # La désignation commune (`designated_source`, 2026-11-06) : le confinement seul
            # copiait chez moi le fichier de n'importe quel compte cité dans une ligne `-i`.
            from wama.common.utils.media_paths import InputRefused, designated_source
            from wama.common.utils.provenance import kind_of
            try:
                abs_src, src_rel = designated_source(src, user)
            except InputRefused:
                warnings.append(f'Introuvable ou inaccessible : {src}')
                continue
            # Une ligne `-i` qui désigne un fichier DÉJÀ dans l'arbre de l'utilisateur est
            # POINTÉE, plus recopiée (2026-09-23) : la brique décide, le site ne sait rien.
            dpath, rel = reference_or_copy(abs_src, 'converter', user.id, 'input')
            fname = dpath.name
            origin = {'kind': kind_of(src_rel), 'ref': src_rel, 'source_path': abs_src}

            media_type = detect_media_type(fname)
            if media_type is None:
                warnings.append(f'Type non supporté : {fname}')
                continue

            job = ConversionJob.objects.create(
                user=user, input_filename=fname, media_type=media_type,
                output_format=output_format_for(user, media_type), status='PENDING',
            )
            job.input_file.name = rel
            job.save(update_fields=['input_file', *apply_birth_settings(job, media_type, request.POST)])
            job_ids.append(job.id)
            # Provenance : la copie se souvient de sa ligne de lot (brique commune).
            from wama.common.utils.provenance import record_origin
            record_origin(rel, **origin)
        except Exception as e:
            warnings.append(f'{src} : {e}')

    # Rangés à l'ARRIVÉE par la déclaration de la fabrique (un lot par nature — 2026-10-16).
    from wama.common.utils.queue_manipulation import consolidate_arrival
    batches = consolidate_arrival(ConversionJob, job_ids, user)
    return JsonResponse({
        'success': True,
        'count': len(job_ids),
        'batches': len(batches),
        'warnings': warnings,
    })


# ────────────────────────────────────────────────────────────────────────────
# Batch actions (groupe) — démarrer / régler / supprimer
# ────────────────────────────────────────────────────────────────────────────

# ── Quatre vues de lot par la fabrique COMMUNE (`batch_views.make_batch_views`, portage
# 2026-09-23, 10ᵉ et dernière app réelle — ROUTE §11 #36) ; seule app à FK DIRECTE
# (`ConversionJob.batch` + `batch_row_index`), la forme que `tests_batch_views` mesure en premier.
# Spécificités DÉCLARÉES : ▶ de lot ne lance que les PENDING qui ONT un format de sortie
# (`start_only_pending` + `startable` — un job sans format se règle par la modale de lot, il n'est
# ni lancé ni compté) ; la tâche s'importe paresseusement ; la copie de lot garde `media_type`
# (le lot est HOMOGÈNE par nature) ; les fichiers d'un job sont libérés par la fabrique
# (`release_card_files`, propriété et partage jugés) ; `@login_required` gardé, comme sur toutes les vues
# de l'app. `batch_update` vient de la fabrique depuis le 2026-10-02 : elle lit le POSTÉ selon le
# schéma et appelle `_apply_job_settings`, la fonction de la route d'élément — un format refusé
# = 400 et aucune fille écrite.
from wama.common.utils.batch_views import make_batch_views
from wama.converter.params import PARAMS_JSON as _BATCH_SCHEMA


def _task_for(_job):
    from .tasks import convert_media_task
    return convert_media_task


_bv = make_batch_views(
    work_model=ConversionJob, batch_model=ConversionBatch, get_user=lambda request: request.user,
    task_for=_task_for, start_only_pending=True, startable=lambda job: bool(job.output_format),
    batch_attr='batch', row_field='batch_row_index',
    batch_extra=lambda lot: {'media_type': lot.media_type},
    zip_name=lambda lot: f'converter_batch_{lot.id}.zip',
    schema=_BATCH_SCHEMA, apply_settings=_apply_job_settings,
)
batch_start = login_required(_bv['batch_start'])
batch_delete = login_required(_bv['batch_delete'])
batch_duplicate = login_required(_bv['batch_duplicate'])
batch_download = login_required(_bv['batch_download'])
batch_update = login_required(_bv['batch_update'])
batch_promote = login_required(_bv['batch_promote'])
batch_realign = login_required(_bv['batch_realign'])


# ────────────────────────────────────────────────────────────────────────────
# Conversion profiles — save / list / delete
# ────────────────────────────────────────────────────────────────────────────

@login_required
def profile_list(request):
    """Return user's profiles, optionally filtered by media_type."""
    media_type = request.GET.get('media_type', '').strip()
    qs = ConversionProfile.objects.filter(user=request.user)
    if media_type:
        qs = qs.filter(media_type=media_type)
    return JsonResponse({
        'profiles': [
            {
                'id':            p.id,
                'name':          p.name,
                'description':   p.description,
                'media_type':    p.media_type,
                'output_format': p.output_format,
                'options':       p.options or {},
            }
            for p in qs
        ],
    })


@login_required
@require_POST
def profile_save(request):
    """Create or update a profile by name (per user)."""
    import json as _json

    name          = (request.POST.get('name') or '').strip()
    description   = (request.POST.get('description') or '').strip()
    media_type    = (request.POST.get('media_type') or '').strip()
    output_format = (request.POST.get('output_format') or '').strip().lower()
    options_json  = request.POST.get('options_json') or '{}'

    if not name:
        return JsonResponse({'error': 'Nom du profil requis'}, status=400)
    if media_type not in SUPPORTED_CONVERSIONS:
        return JsonResponse({'error': f"Type de média invalide : {media_type}"}, status=400)
    if output_format not in get_output_formats(media_type):
        return JsonResponse({'error': f"Format de sortie invalide : {output_format}"}, status=400)

    try:
        options = _json.loads(options_json)
        if not isinstance(options, dict):
            raise ValueError("options must be an object")
    except (ValueError, _json.JSONDecodeError) as exc:
        return JsonResponse({'error': f"options_json invalide : {exc}"}, status=400)

    profile, created = ConversionProfile.objects.update_or_create(
        user=request.user,
        name=name,
        defaults={
            'description':   description,
            'media_type':    media_type,
            'output_format': output_format,
            'options':       options,
        },
    )
    return JsonResponse({
        'success':       True,
        'created':       created,
        'id':            profile.id,
        'name':          profile.name,
        'media_type':    profile.media_type,
        'output_format': profile.output_format,
        'options':       profile.options or {},
    })


@login_required
@require_POST
def profile_delete(request, pk):
    """Delete a profile."""
    profile = get_object_or_404(ConversionProfile, pk=pk, user=request.user)
    profile.delete()
    return JsonResponse({'success': True})


@login_required
@require_POST
def cancel(request, pk):
    """⏹ d'une conversion — le nom de la route du converter (`<pk>/cancel/`, que le générateur
    connaît), le geste de la fabrique commune (`_iv['stop']`, 2026-11-02) : la card s'arrête en
    échec « Interrompu par l'utilisateur », relançable — elle revenait en attente sans le dire.

    Spécificité : une conversion RAPIDE (éphémère, lancée du gestionnaire de fichiers, jamais en
    file) n'a pas de card à relancer — elle est révoquée puis retirée. La sortie atomique garantit
    qu'aucun fichier partiel ne reste à côté de la source."""
    from wama.common.utils.scoping import editable_or_404
    job = editable_or_404(ConversionJob, request.user, pk=pk)
    if not job.ephemeral:
        return _iv['stop'](request, pk)
    if job.task_id:
        try:
            from celery import current_app
            current_app.control.revoke(job.task_id, terminate=True, signal='SIGTERM')
        except Exception:
            pass
    job.delete()
    return JsonResponse({'success': True, 'id': pk, 'deleted': pk})


@login_required
@require_POST
def dismiss(request, pk):
    """Delete an ephemeral quick-convert job row WITHOUT touching files.

    Called by the Filemanager once the in-place result has been delivered.
    The output file lives in the user's media tree, so we must never delete it
    here — only the tracking row is removed. Refuses non-ephemeral jobs.
    """
    job = get_object_or_404(ConversionJob, pk=pk, user=request.user, ephemeral=True)
    job.delete()  # FileField files are NOT deleted by .delete(); row only
    return JsonResponse({'success': True})


@login_required
@require_POST
def quick_convert(request):
    """
    Convert / enqueue from a server file path — called from the Filemanager.

    "Conversion rapide" (on-the-fly) : crée un job ÉPHÉMÈRE, écrit le résultat
    À CÔTÉ de la source (in-place), démarre tout de suite, n'apparaît JAMAIS
    dans la file, et la ligne est supprimée (dismiss) après livraison — le
    fichier reste. output_format : absent = automatique selon la nature ;
    quality_preset (web/balanced/max).

    NB : "Envoyer vers Converter" (mode file d'attente) passe désormais par le
    flux d'import STANDARD (filemanager api_import_to_app → import_to_converter),
    qui COPIE le fichier dans converter/<user>/input comme toutes les apps.

    POST params:
        file_path      : chemin absolu ou relatif à MEDIA_ROOT du fichier source
        output_format  : format cible (absent : automatique selon la nature)
        quality_preset : 'web' | 'balanced' | 'max' (défaut 'balanced')
    """
    from .tasks import convert_media_task
    from .utils.quality_presets import DEFAULT_PRESET, PRESET_CHOICES

    file_path_str = request.POST.get('file_path', '').strip()
    output_fmt    = (request.POST.get('output_format', '') or '').strip().lower()
    preset        = (request.POST.get('quality_preset', '') or '').strip().lower()
    if preset not in PRESET_CHOICES:
        preset = DEFAULT_PRESET

    if not file_path_str:
        return JsonResponse({'error': 'Chemin de fichier manquant'}, status=400)

    # La désignation commune (`designated_source`, 2026-11-06) — et, parce que la conversion
    # rapide ÉCRIT sa sortie à côté de la source (`dest_dir`), la source doit être dans l'arbre de
    # CE compte : le confinement seul convertissait le fichier d'autrui dans SON dossier.
    from wama.common.utils.media_paths import InputRefused, designated_source, in_user_home
    try:
        abs_path, rel = designated_source(file_path_str, request.user)
    except InputRefused:
        return JsonResponse({'error': 'Fichier source introuvable ou inaccessible'}, status=404)
    if not in_user_home(rel, request.user.id):
        return JsonResponse({'error': "La conversion rapide n'agit que sur vos propres fichiers"},
                            status=403)
    abs_path, rel_path = Path(abs_path), Path(rel)

    media_type = detect_media_type(abs_path.name)
    if media_type is None:
        return JsonResponse({'error': f"Type de fichier non supporté : {abs_path.suffix}"}, status=400)

    # La règle de toutes les voies : le format demandé (refusé s'il n'est pas offert), sinon
    # le format automatique de la nature (`format_router.output_format_for`).
    chosen = output_fmt
    try:
        output_fmt = output_format_for(request.user, media_type, chosen)
    except ValueError as refusal:
        return JsonResponse({'error': str(refusal)}, status=400)
    if chosen:
        remember_output_format(request.user, media_type, output_fmt)

    # ── Quick convert : ephemeral + in-place + preset ─────────────────────────
    dest_dir = str(rel_path.parent).replace('\\', '/')  # source folder, relative to MEDIA_ROOT
    job = ConversionJob.objects.create(
        user=request.user,
        input_file=str(rel_path),
        input_filename=abs_path.name,
        media_type=media_type,
        output_format=output_fmt,
        ephemeral=True,
        dest_dir=dest_dir,
        quality_preset=preset,
        status='RUNNING',
    )
    # MODÈLE ÉVÉNEMENTIEL (02/09) : la tâche lit les COLONNES — le job naît complet par la
    # cascade commune (2026-10-18), puis le preset du menu contextuel Filemanager s'ÉTALE
    # par-dessus (sinon il serait une trace inerte) ; et il pose la position du curseur commun
    # (trace, chantier C).
    from wama.common.utils.user_settings import inputs_by_port
    champs = apply_birth_settings(job, media_type, inputs=inputs_by_port('converter', str(abs_path)))
    if preset:
        from .utils.quality_presets import preset_values
        champs += [f for f in job.poser_reglages(preset_values(media_type, preset)) if f not in champs]
        champs += [f for f in _apply_quality_gesture(job, {'quality_preset': preset}) if f not in champs]
    if champs:
        job.save(update_fields=champs)
    task = convert_media_task.delay(job.id)
    job.task_id = task.id
    job.save(update_fields=['task_id'])
    return JsonResponse({'success': True, 'id': job.id, 'task_id': task.id})   # contrat commun


# ═══════════════════════════════════════════════════════════════════════════
# Vues standard communes (port schéma-driven 2026-07-26)
# ═══════════════════════════════════════════════════════════════════════════

def _decorate_job(job):
    """Chips de card générés du SCHÉMA (params.py chip=True) — brique commune card_chips.
    Point d'attache UNIQUE : IndexView ET card_html (leçon describer).
    `values` : les réglages vivent dans les JSON (options + cross_app_options), pas en
    colonnes — sans lui, tout chip hors-colonne rendait RIEN (getattr → None → filtré ;
    mesuré 31/08 en chippant quality/upscale). Même assiette que la property `gear_data`."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.converter.params import PARAMS_JSON
    valeurs = {**(job.options or {}), **(job.cross_app_options or {})}
    # Legacy : le neutre de rotation était "0" (option « Aucune ») jusqu'au 31/08 ; les jobs
    # enregistrés avant portent encore cette valeur, qui ne correspond plus à aucune option
    # → chip « 0 » sur des cards sans rotation (R6, audit 31/08). Normalisée À LA LECTURE —
    # pas de migration de données pour un neutre.
    if str(valeurs.get('rotation', '')) in ('0', ''):
        valeurs.pop('rotation', None)
    job.chips = chips_by_section(job, PARAMS_JSON, values=valeurs)
    # ── Alias NORMALISÉ `elem` (2026-09-09, adoption de `common/_queue_entry.html`) ──────
    # La brique itère les LIAISONS d'un lot et atteint l'élément métier par `item.elem` —
    # alias que `build_batches_list` pose sur chaque liaison (`_it.elem = getattr(_it,
    # work_attr)`). Le converter n'a PAS de modèle de liaison : sa FK est directe
    # (job→batch), donc la liaison et l'élément COÏNCIDENT et l'alias pointe sur le job
    # lui-même. Ce n'est pas un contournement : c'est la même équation, avec un terme égal.
    # Posé ICI parce que `_decorate_job` est le point de décoration UNIQUE des deux chemins
    # de rendu (la file, et l'endpoint card_html) — le poser dans la vue d'index aurait
    # laissé le second sans alias.
    job.elem = job
    return job


def _decorate_card(job):
    """Ce que la card d'un job porte au rendu : les chips du schéma (`_decorate_job`), puis ses
    PROCESS et son état MONTRÉ (pipeline, 2026-10-13 — `ROUTE §10.6` 5.1)."""
    from wama.common.services.process_pipeline import decorate
    decorate(_decorate_job(job))
    return job


# Card = partial serveur UNIQUE : le JS remplace la card par ce rendu — fabrique commune
# (`make_card_view`, 2026-11-02). Une lecture : une card reçue se rafraîchit aussi.
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=ConversionJob, template='converter/_job_card.html',
                           decorate=_decorate_card)


def console_content(request):
    """Lignes de console de l'app (brique commune console_utils)."""
    from wama.common.utils.console_utils import get_console_lines
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    return JsonResponse({'lines': get_console_lines(user.id)})


def batch_template(request):
    """Gabarit de fichier batch téléchargeable (une source par ligne).

    GÉNÉRÉ depuis la déclaration du champ (brique commune `build_batch_template`, A5-23),
    comme transcriber/imager/composer. Le gabarit écrit à la main qu'il remplace n'avait
    AUCUNE ligne vive : ses cinq exemples étaient tous commentés. Téléchargé puis redéposé
    tel quel — le geste le plus naturel — il ne produisait donc rien, et le repli silencieux
    de la barre (`batch-import.js`, aperçu à 0 élément) ne le disait pas. Mesuré 2026-08-27.
    Servi par `batch_template_response` (2026-11-02), avec les formats que l'app déclare.
    """
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'converter', ['source'], {'source': 'https://example.com/photo.png'},
        label='Converter (une URL ou un chemin par ligne — image, vidéo, audio, document)')


# ── Manipulation directe de la file (fabrique COMMUNE, variante FK-directe) ──
# ConversionJob porte lui-même batch + batch_row_index (pas de modèle de liaison).
# `consolidate` compris depuis le 2026-10-16 : la fabrique range PAR NATURE (`group_key`), le lot
# portant la sienne (`batch_extra`). Le consolidate local, son champ historique `job_ids` et le
# helper `consolidate_jobs_into_batches` sont retirés.
from wama.common.utils.queue_manipulation import make_queue_manipulation_views_direct

_qm = make_queue_manipulation_views_direct(
    work_model=ConversionJob,
    batch_model=ConversionBatch,
    get_user=lambda r: r.user if r.user.is_authenticated else get_or_create_anonymous_user(),
    batch_extra=lambda job: {'media_type': job.media_type},
    # Un lot de conversion = UNE nature (le lot porte `media_type`, et le format de sortie en
    # découle). `batch_extra` la posait à la création ; `group_key` la DÉFEND ensuite — sans
    # lui, glisser une vidéo dans un lot d'images passait, et tout le lot repartait au mauvais
    # format. La même fonction range aussi l'arrivée (`consolidate_arrival`), pas une seconde règle.
    group_key=_converter_nature,
)
remove_from_batch = _qm['remove_from_batch']
reorder           = _qm['reorder']
reorder_queue     = _qm['reorder_queue']
merge             = _qm['merge']
move_to_batch     = _qm['move_to_batch']
consolidate       = _qm['consolidate']
