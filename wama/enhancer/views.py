import os
import logging
from django.shortcuts import render
from wama.accounts.permissions import app_access
from wama.common.utils.input_match import input_labels as _input_labels
from django.views import View
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.core.cache import cache
from PIL import Image

import datetime
from .models import (Enhancement, AudioEnhancement,
                     BatchEnhancement, BatchEnhancementItem,
                     BatchAudioEnhancement, BatchAudioEnhancementItem)
from ..accounts.views import get_or_create_anonymous_user
from ..common.utils.console_utils import get_console_lines
from ..common.utils.video_utils import get_media_info

logger = logging.getLogger(__name__)


# Curseur POSTÉ (chantier C) : lecteur COMMUN — None quand il n'est pas posté (la colonne reste
# vide, la cascade retombe sur le réglage d'app puis 50). Était une copie locale, comme chez
# imager et composer (revérification 21/09).
from wama.common.utils.auto_model import posted_quality_intent as _intent_posted  # noqa: E402


def _factor_posted(source, default=None):
    """Facteur d'agrandissement POSTÉ (×2 / ×4), `default` sinon — le BESOIN que « auto »
    filtre avant de classer."""
    raw = source.get('upscale_factor') if hasattr(source, 'get') else None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return value if value in (2, 4) else default


def _wrap_enhancement_in_batch(enhancement):
    """Wrap a standalone Enhancement in a new BatchEnhancement-of-1."""
    batch = BatchEnhancement.objects.create(user=enhancement.user, total=1)
    BatchEnhancementItem.objects.create(batch=batch, enhancement=enhancement, row_index=0)
    return batch


def _enhancement_nature(e):
    """Nature d'une amélioration (image / vidéo) — ce qui peut cohabiter dans un lot.

    DEUX consommateurs, une seule déclaration, toutes deux par la fabrique commune (`group_key`) :
    le regroupement à l'arrivée (`consolidate_arrival`) et la fusion par drag&drop (`merge`).
    Écrite en lambda jusqu'au 2026-09-04, donc impartageable."""
    return e.media_type or 'image'


def _auto_wrap_orphans(user):
    """Range les Enhancement (médias) pas encore en batch — brique COMMUNE, stratégie
    par défaut (orphelin → batch-of-1). Le regroupement par nature ne se fait plus
    qu'à l'ARRIVÉE (`queue_manipulation.consolidate_arrival`, constat Fabien 14/08)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(
        user, work_model=Enhancement, batch_model=BatchEnhancement,
        item_model=BatchEnhancementItem, fk_name='enhancement',
    )


def _wrap_audio_in_batch(audio_enhancement):
    """Wrap a standalone AudioEnhancement in a new BatchAudioEnhancement-of-1."""
    batch = BatchAudioEnhancement.objects.create(user=audio_enhancement.user, total=1)
    BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=audio_enhancement, row_index=0)
    return batch


def _auto_wrap_audio_orphans(user):
    """Range les AudioEnhancement pas encore en batch — brique COMMUNE, stratégie par
    défaut (orphelin → batch-of-1) ; l'of-N ne se fait plus qu'à l'ARRIVÉE
    (cf. auto_wrap_orphans, constat Fabien 14/08). Le scope user=user est porté par
    la brique : on n'enrôle jamais la card partagée d'autrui."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(
        user, work_model=AudioEnhancement, batch_model=BatchAudioEnhancement,
        item_model=BatchAudioEnhancementItem, fk_name='audio_enhancement',
    )


def _decorate_media_card(e, preloaded=False):
    """Chips de card générés du SCHÉMA (card_chips) — remplace les badges hand-built.
    Point d'attache UNIQUE : IndexView (par `decorate_cards`) ET card_html."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.enhancer.params import MEDIA_PARAMS_JSON
    e.chips = chips_by_section(e, MEDIA_PARAMS_JSON)
    from wama.common.services.process_pipeline import decorate
    decorate(e, preloaded=preloaded)   # « Amélioration → Sortie » et l'état MONTRÉ (`ROUTE §10.6` 5.1)
    return e


def _decorate_audio_card(ae, preloaded=False):
    from wama.common.utils.card_chips import chips_by_section
    from wama.enhancer.params import AUDIO_PARAMS_JSON
    ae.chips = chips_by_section(ae, AUDIO_PARAMS_JSON)
    from wama.common.services.process_pipeline import decorate
    decorate(ae, preloaded=preloaded)
    return ae


def _input_match_meta_enhancer():
    """Meta de la brique COMMUNE, indexée par les VALEURS d'option des deux selects : le select
    MÉDIA porte des clés entières, tirées par TÂCHE (route F4b ⑤, 2026-10-06 — le mode `task`
    de la brique, qui sinon resterait muet sur un modèle d'une autre source, Swin2SR) ; le select
    AUDIO garde ses identifiants nus de la source `enhancer`."""
    from wama.common.utils.input_match import input_match_meta
    from wama.enhancer.utils.auto_model import MEDIA_SPEC
    return {**input_match_meta('enhancer'), **input_match_meta(task=MEDIA_SPEC['task'])}


class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Lazily wrap any orphan enhancements into batches-of-1
        _auto_wrap_orphans(user)
        _auto_wrap_audio_orphans(user)

        # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
        from wama.common.utils.process_control import reconcile_queue_of
        reconcile_queue_of(Enhancement, user)
        reconcile_queue_of(AudioEnhancement, user)

        # Files par domaine — brique COMMUNE build_batches_list (contrat _batch_card)
        # + tri/filtre persistés session (contrat _queue_toolbar).
        from wama.common.utils.batch_common import build_batches_list
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _make_extra(schema):
            # `schema` par FILE (media vs audio) : les réglages COMMUNS aux filles de la
            # card mère (slot meta_template, porté le 31/08) se dérivent du bon schéma.
            from wama.common.utils.card_chips import common_chips_for_items

            def _extra(batch, items, works):
                done = sum(1 for w in works if w.status == 'SUCCESS')
                return {
                    'success_pct': int(done / batch.total * 100) if batch.total > 0 else 0,
                    # (l'ETA agrégée de la card mère, `eta_ids`, vient de `build_batches_list`)
                    'common_chips': common_chips_for_items(works, schema),
                }
            return _extra

        from wama.enhancer.params import AUDIO_PARAMS_JSON, MEDIA_PARAMS_JSON
        batches_list = build_batches_list(
            user, batch_model=BatchEnhancement, work_attr='enhancement',
            extra=_make_extra(MEDIA_PARAMS_JSON))
        audio_batches_list = build_batches_list(
            user, batch_model=BatchAudioEnhancement, work_attr='audio_enhancement',
            extra=_make_extra(AUDIO_PARAMS_JSON))
        # Chips + process de card : les lignes d'exécution de TOUTES les cards d'une file sont
        # lues en une requête (`decorate_cards`, comme les neuf autres apps) — une file par domaine.
        from wama.common.services.process_pipeline import decorate_cards
        decorate_cards([link.enhancement for b in batches_list for link in b['items']],
                       _decorate_media_card)
        decorate_cards([link.audio_enhancement for b in audio_batches_list for link in b['items']],
                       _decorate_audio_card)

        # (« batchs d'abord » RETIRÉ le 2026-08-24 : règle abandonnée le 2026-06-29 au profit du
        # tri de la barre commune — `apply_queue_sort_filter` ci-dessous trie TOUJOURS, défaut
        # `recent`, et s'applique aux DEUX listes. Ces deux tris étaient donc écrasés juste après.)

        def _name_of(b):
            return (b['obj'].name or '') if hasattr(b['obj'], 'name') else str(b['obj'])

        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list, name_of=_name_of)
        audio_batches_list, _, _ = apply_queue_sort_filter(
            request, audio_batches_list, name_of=_name_of)

        # Le volet reprend les réglages MÉMORISÉS de l'utilisateur — brique commune (2026-09-29,
        # `ROADMAP §23.3bis`). La table `UserSettings` propre à l'enhancer n'était jamais ÉCRITE
        # (seulement `get_or_create`) : ses « défauts » étaient ceux du modèle, pour tout le monde.
        from wama.common.utils.user_settings import read_panel_settings
        from wama.enhancer.params import AUDIO_PARAMS, MEDIA_PARAMS
        panel = read_panel_settings(user, 'enhancer', MEDIA_PARAMS)
        # Le volet AUDIO retient aussi les siens depuis le 2026-10-28 (même brique, même clé de
        # volet : ses `dom_id` sont distincts de ceux du domaine image/vidéo).
        audio_panel = read_panel_settings(user, 'enhancer', AUDIO_PARAMS)
        # Le volet parle en CLÉS de catalogue (route F4b ⑤, 2026-10-06) : une préférence
        # mémorisée avant la bascule (identifiant nu) est lue dans l'espace de l'enhancer.
        from wama.common.utils.model_keys import catalog_key
        panel['ai_model'] = catalog_key(panel.get('ai_model') or 'auto', 'enhancer')
        audio_panel['engine'] = catalog_key(audio_panel.get('engine') or 'auto', 'enhancer')

        import json as _json
        from wama.enhancer.params import MEDIA_PARAMS_JSON, AUDIO_PARAMS_JSON
        queue_count = sum(len(b['items']) for b in batches_list) +                       sum(len(b['items']) for b in audio_batches_list)

        return render(request, 'enhancer/index.html', {
            'batches_list': batches_list,
            'audio_batches_list': audio_batches_list,
            'queue_count': queue_count,
            'q_sort': q_sort,
            'q_filter': q_filter,
            # Valeurs du VOLET GÉNÉRÉ (domaine image/vidéo, 2026-10-11) — par NOM de param, ce
            # qu'attend `WamaParams.render`. Plus de pré-rendu des options (modèle, moteur audio,
            # formats) : le volet les reçoit du schéma et du catalogue, comme la modale.
            'panel_values_json': _json.dumps(panel).replace('<', '\\u003c'),
            'audio_panel_values_json': _json.dumps(audio_panel).replace('<', '\\u003c'),
            # Schémas déclaratifs par domaine → inspecteur contextuel (WamaInspector.initFromSchema).
            'media_params_json': _json.dumps(MEDIA_PARAMS_JSON),
            'audio_params_json': _json.dumps(AUDIO_PARAMS_JSON),
            # Appariement entrée↔modèles (brique commune input_match) : clés catalogue =
            # valeurs d'option depuis l'alignement 18/08 (artefact _fp16 retiré à la
            # découverte ; moteurs audio déjà alignés).
            'input_match_meta': _json.dumps(_input_match_meta_enhancer()),
            'input_labels': _json.dumps(_input_labels()),
        })


def new_enhancement_settings(user, model=None, app='enhancer', post=None, inputs=None):
    """Les colonnes de réglage d'une amélioration (image/vidéo) NAISSANTE, par la cascade COMMUNE
    (défauts du schéma ← réglages mémorisés au volet ← ce que le dépôt poste,
    `user_settings.new_element_settings`, 2026-10-18 — six défauts y étaient recopiés à la main).
    Règle propre gardée : le facteur d'agrandissement vaut ×2 ou ×4, ×4 sinon (`_factor_posted`).
    Le dépôt de la card, le lot et l'import du gestionnaire de fichiers (« Envoyer vers », sans
    volet donc sans POST) passent ici ; `model`/`app` : une jumelle de bac à sable passe les siens."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.enhancer.params import MEDIA_PARAMS_JSON
    values = new_element_settings(user, app, MEDIA_PARAMS_JSON, model or Enhancement, post=post,
                                  inputs=inputs,
                                  empty_is_value=SETTINGS_EMPTY_IS_VALUE)
    if 'upscale_factor' in values:
        values['upscale_factor'] = _factor_posted(values, 4)
    return values


from wama.common.utils.user_settings import inputs_by_port  # noqa: E402


def _deposit_settings(user, post, inputs=None):
    """Réglages d'un DÉPÔT (`new_enhancement_settings`). Ce qui a été posté devient la mémoire
    du volet (`save_panel_settings`) : l'élément suivant et la page rechargée partent des
    derniers réglages employés. `inputs` : le fichier reçu, sous son port (`inputs_by_port`)."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.enhancer.params import MEDIA_PARAMS_JSON
    values = new_enhancement_settings(user, post=post, inputs=inputs)
    save_panel_settings(user, 'enhancer', MEDIA_PARAMS_JSON, post)
    return values


# ── Domaine AUDIO : le MÊME modèle que le domaine image/vidéo (portage du 2026-10-28) ─────────
# Jusque-là le dépôt audio créait l'élément sur les défauts du modèle, le volet ne s'appliquait
# qu'au LANCEMENT (chaque ▶ reprenait le volet), rien n'était retenu, et quatre vues recopiaient
# chacune leur liste de réglages (fiche d'élément, ▶, « Tout démarrer », ▶ de lot).

def new_audio_settings(user, model=None, app='enhancer', post=None, inputs=None):
    """Les colonnes de réglage d'une amélioration AUDIO naissante, par la cascade COMMUNE
    (défauts du schéma ← réglages retenus au volet ← ce que le dépôt poste). Le dépôt de la card,
    le lot, « Envoyer vers » et l'outil de l'assistant passent ici ; `model`/`app` : une jumelle
    de bac à sable passe les siens."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.enhancer.params import AUDIO_PARAMS_JSON
    return new_element_settings(user, app, AUDIO_PARAMS_JSON, model or AudioEnhancement, post=post,
                                inputs=inputs,
                                empty_is_value=SETTINGS_EMPTY_IS_VALUE)


def _audio_deposit_settings(user, post, inputs=None):
    """Réglages d'un DÉPÔT audio (`new_audio_settings`) ; ce qui a été posté devient la mémoire du
    volet audio (`save_panel_settings`), comme au domaine image/vidéo. `inputs` : le fichier
    reçu, sous son port (`inputs_by_port`)."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.enhancer.params import AUDIO_PARAMS_JSON
    values = new_audio_settings(user, post=post, inputs=inputs)
    save_panel_settings(user, 'enhancer', AUDIO_PARAMS_JSON, post or {})
    return values


def _apply_audio_settings(ae, data):
    """LES réglages d'une amélioration audio, posés sans sauver — la route de l'élément, « Tout
    démarrer » et le ▶ de lot passent ici. Les colonnes par la brique COMMUNE (valeur hors choix
    ignorée) ; le curseur à part : clé ABSENTE = inchangé, posée vide = curseur effacé."""
    from wama.common.utils.batch_views import apply_item_settings
    from wama.enhancer.params import AUDIO_PARAMS
    apply_item_settings(ae, {k: v for k, v in (data or {}).items() if v not in (None, '')},
                        params_fields=tuple(p.name for p in AUDIO_PARAMS
                                            if p.name != 'quality_intent'))
    if 'quality_intent' in (data or {}):
        ae.quality_intent = _intent_posted(data)


@require_POST
@app_access('enhancer')
def upload(request):
    """Upload and analyze image/video file, or download from URL."""
    print("=== ENHANCER UPLOAD CALLED ===")  # DEBUG
    logger.info("=== UPLOAD START ===")

    # Check for URL upload first
    media_url = request.POST.get('media_url', '').strip()
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # Un fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique `received_inputs` : une
    # désignation se POINTE au lieu d'être recopiée, avec le même état du volet.
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'enhancer')
    file = received[0] if received else None

    if not file and not media_url:
        logger.error("Upload failed: No file or URL provided")
        if received.refusal:
            return JsonResponse({'error': received.refusal}, status=400)
        return HttpResponseBadRequest('Missing file or URL')

    logger.info(f"Upload by user: {user.username} (ID: {user.id})")

    # URL : la SOURCE est enregistrée, le récepteur commun la télécharge dès la création, HORS
    # de la requête (`source_ingest`, 2026-10-13) — même geste que `batch_create`. Une nature
    # connue d'avance hors image/vidéo est refusée ici ; inconnue, le `derive` la pose à l'arrivée.
    if media_url and not file:
        from urllib.parse import unquote, urlparse
        from wama.common.utils.app_modes import surface_file_nature
        from wama.common.utils.url_ingest import url_nature
        nature = url_nature(media_url)
        url_path = unquote(urlparse(media_url).path)
        if os.path.splitext(url_path)[1]:
            # Un fichier nommé : la même lecture que le dépôt (domaine, `extension_natures`).
            nature = surface_file_nature('enhancer', 'enhancer', url_path)
            if not nature:
                return JsonResponse({'error': 'Format non supporté'}, status=400)
        elif nature and nature not in ('image', 'video'):
            return JsonResponse({'error': 'Format non supporté'}, status=400)
        enhancement = Enhancement.objects.create(
            user=user, media_type=nature, source_url=media_url,
            **_deposit_settings(user, request.POST),
        )
        try:
            _wrap_enhancement_in_batch(enhancement)
        except Exception:
            pass
        return JsonResponse({'id': enhancement.id, 'media_type': enhancement.media_type,
                             'source_url': media_url, 'status': enhancement.status})

    # La nature du fichier, lue à la déclaration du domaine que cette porte sert (`app_modes`) —
    # deux listes d'extensions vivaient ici, qui refusaient `.m4v`, `.avif`… que la zone offrait.
    from wama.common.utils.app_modes import surface_file_nature
    file_ext = os.path.splitext(file.name)[1].lower()
    logger.info(f"File: {file.name} (extension: {file_ext}, size: {file.size} bytes)")

    media_type = surface_file_nature('enhancer', 'enhancer', file.name)
    if not media_type:
        logger.error(f"Unsupported format: {file_ext}")
        return JsonResponse({'error': 'Format non supporté'}, status=400)

    logger.info(f"Detected media type: {media_type}")

    # Create enhancement record
    enhancement = Enhancement.objects.create(
        user=user,
        media_type=media_type,
        input_file=file.value,
        **_deposit_settings(user, request.POST, inputs_by_port('enhancer', file)),
    )
    file.record(enhancement, 'input_file')
    logger.info(f"Created Enhancement ID: {enhancement.id}")

    # Wrap in batch-of-1
    try:
        _wrap_enhancement_in_batch(enhancement)
    except Exception:
        pass

    # Analyze file
    try:
        _analyze_media(enhancement)
        logger.info(f"Media analyzed: {enhancement.width}x{enhancement.height}")
    except Exception as e:
        logger.warning(f"Could not analyze media: {e}")

    return JsonResponse({
        'id': enhancement.id,
        'media_type': enhancement.media_type,
        'input_url': enhancement.input_file.url,
        'input_filename': enhancement.get_input_filename(),
        'width': enhancement.width,
        'height': enhancement.height,
        'file_size': enhancement.file_size,
        'status': enhancement.status,
    })


def _analyze_media(enhancement: Enhancement):
    """Analyze media file to extract dimensions and metadata using common utility."""
    file_path = enhancement.input_file.path
    logger.info(f"[_analyze_media] Starting analysis for: {file_path}")

    try:
        info = get_media_info(file_path)
        logger.info(f"[_analyze_media] get_media_info returned: {info}")
        enhancement.width = info['width']
        enhancement.height = info['height']
        enhancement.duration = info['duration']
        enhancement.file_size = info['file_size']
        enhancement.save(update_fields=['width', 'height', 'duration', 'file_size'])
        logger.info(f"[_analyze_media] Saved: {enhancement.width}x{enhancement.height}")
    except Exception as e:
        logger.error(f"[_analyze_media] FAILED for {file_path}: {e}", exc_info=True)


def _queue_panel(request, _user):
    """Le volet que « tout lancer » POSTE (JSON, ou formulaire) — « démarrer tout vaut appliquer
    à tout » ; rien de posté = chaque élément garde ses réglages."""
    import json
    try:
        data = json.loads(request.body) if request.body else {}
    except ValueError:
        data = request.POST.dict()
    return data or None


# ▶ de la card, ▶ et 🗑 de la file — DEUX files, deux déclarations : fabrique COMMUNE
# (`item_views.make_item_views`, ROUTE §11 #39, 2026-10-29), la même que lisent les outils
# `start_enhancer` et `start_audio_enhancer`. Le ▶ de la card lance avec les réglages STOCKÉS
# (corps vide, modèle événementiel) ; « tout lancer » relance TOUTE la file avec le volet posté,
# par la fonction de réglage d'un élément — celle de sa route `update_settings` et de ses lots.
# Et les autres gestes d'une card, ⏹ ⬇ 🗑 ⧉ ⚙, d'un domaine comme de l'autre (2026-11-01, ROUTE
# §11 #42 ④) : la fabrique les lit à la déclaration de chaque fabrique de lot plus bas (remise à
# zéro de la copie, nom du résultat, cache purgé, schéma et fonction de réglage). L'app les
# écrivait deux fois — cinq vues `audio_*` et leurs cinq jumelles image / vidéo —, et le ⧉ audio
# ne rejoignait jamais le lot de l'original.
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(work_model=Enhancement, app_id='enhancer',
                      task_for=lambda e: _media_task(e),
                      reset_on_start={'progress': 0, 'error_message': ''}, pending={},
                      queue_settings=_queue_panel,
                      apply_settings=lambda e, data: _apply_enhancement_settings(e, data),
                      batch_model=BatchEnhancement)
start = app_access('enhancer')(_iv['start'])
start_all = app_access('enhancer')(_iv['start_all'])
clear_all = _iv['clear_all']
stop, delete, duplicate = _iv['stop'], _iv['delete'], _iv['duplicate']
download, update_settings = _iv['download'], _iv['update_settings']
_aiv = make_item_views(work_model=AudioEnhancement, app_id='audio_enhancer',
                       task_for=lambda a: _audio_task(a),
                       reset_on_start={'progress': 0, 'error_message': ''}, pending={},
                       queue_settings=_queue_panel,
                       apply_settings=lambda a, data: _apply_audio_settings(a, data),
                       batch_model=BatchAudioEnhancement)
audio_start = app_access('enhancer')(_aiv['start'])
audio_start_all = app_access('enhancer')(_aiv['start_all'])
audio_clear_all = _aiv['clear_all']
audio_stop, audio_delete, audio_duplicate = _aiv['stop'], _aiv['delete'], _aiv['duplicate']
audio_download, audio_update = _aiv['download'], _aiv['update_settings']


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03), pour ses DEUX files (média, audio). L'ETA est celle de ses PROCESS
# (`function_specs.PIPELINE`, 2026-10-05).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=Enhancement, app_id='enhancer')
progress, global_progress = _pv['progress'], _pv['global_progress']
_apv = make_progress_views(work_model=AudioEnhancement, app_id='audio_enhancer')
audio_progress, audio_global_progress = _apv['progress'], _apv['global_progress']


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


#: Réglages pour lesquels une valeur postée VIDE est une valeur (curseur effacé) — lus par la
#: route d'un élément ET par la fabrique de lots : une seule déclaration pour les deux.
SETTINGS_EMPTY_IS_VALUE = ('quality_intent',)


def _apply_enhancement_settings(e, data):
    """Applique les réglages d'un Enhancement (sans save). Les colonnes simples passent par la
    brique COMMUNE (valeur hors choix ignorée) ; restent ici le facteur (×2/×4) et le curseur,
    propres à l'enhancer."""
    from wama.common.utils.batch_views import apply_item_settings
    from wama.enhancer.params import MEDIA_PARAMS
    # Les colonnes simples = le schéma MÉDIA, moins les deux réglages traités ci-dessous. Lues du
    # schéma (2026-10-16) : la liste écrite ici en recopiait les noms (`check_redundancy`), et un
    # réglage ajouté au schéma n'était pas appliqué tant qu'on ne l'y recopiait pas.
    apply_item_settings(e, {k: v for k, v in data.items() if v not in (None, '')},
                        params_fields=tuple(p.name for p in MEDIA_PARAMS
                                            if p.name not in ('upscale_factor', 'quality_intent')))
    # Curseur + facteur (chantier C) : clé ABSENTE = inchangé ; posée vide = curseur effacé
    # (la cascade retombe sur le réglage d'app, puis 50).
    e.upscale_factor = _factor_posted(data, e.upscale_factor)
    if 'quality_intent' in data:
        e.quality_intent = _intent_posted(data)


# ===========================================================================
# Batch Enhancement Views (image/video only)
# ===========================================================================

def batch_template(request):
    """Gabarit de fichier batch du domaine image / vidéo, par la brique commune
    (`batch_template_response`) : une source par ligne, les formats que le domaine déclare.
    Écrit à la main jusqu'au 2026-11-02."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'enhancer', ['source'], {'source': 'https://example.com/photo.jpg'},
        label='Enhancer (une URL ou un chemin image/vidéo par ligne)', domain='image_video')


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.app_modes import surface_file_nature
    from wama.common.utils.batch_parsers import batch_media_list_preview_response

    def _enrich(item):
        # Même lecture que le dépôt et `tasks._derive` (`surface_file_nature`), défaut différent
        # ('media' ici) : c'est la POLITIQUE qui diffère, pas la classification.
        item['detected_type'] = surface_file_nature('enhancer', 'enhancer', item['filename']) or 'media'

    return batch_media_list_preview_response(request, item_enricher=_enrich)


@require_POST
def batch_create(request):
    """Parse batch file (URLs/paths), create BatchEnhancement + Enhancement entries."""
    from wama.common.utils.app_modes import surface_file_nature
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # Chaque fille naît par la cascade COMMUNE d'un dépôt (2026-10-18) : elle lisait quatre
    # réglages dans le POST, avec leur défaut écrit ici, et le format de sortie jamais.
    settings_values = _deposit_settings(user, request.POST)

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    # parse_batch_file_from_request a consommé FILES['batch_file'] : on le re-lit
    # pour l'archiver sur le batch (NameError avant 2026-08-03).
    batch_file = request.FILES.get('batch_file')
    if batch_file:
        batch_file.seek(0)
    batch = BatchEnhancement.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path
        # La lecture du dépôt (`surface_file_nature`) ; une ligne sans nature lisible reste une
        # image, comme avant.
        media_type = surface_file_nature('enhancer', 'enhancer', fname) or 'image'

        enhancement = Enhancement.objects.create(
            **settings_values,
            user=user,
            source_url=url_or_path,
            media_type=media_type,
        )
        BatchEnhancementItem.objects.create(batch=batch, enhancement=enhancement, row_index=i)
        created_ids.append(enhancement.id)

    return JsonResponse({
        'batch_id': batch.id,
        'enhancement_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List current user's batches with status counts."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batches = BatchEnhancement.objects.filter(user=user).prefetch_related('items__enhancement')

    from wama.common.utils.batch_common import batch_elements
    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for e in batch_elements(batch, Enhancement):     # lit le cache du prefetch, 0 requête
            k = e.status.lower()
            counts[k] = counts.get(k, 0) + 1

        total = batch.total
        if total > 0 and counts['success'] == total:
            status = 'SUCCESS'
        elif counts['running'] > 0:
            status = 'RUNNING'
        elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
            status = 'FAILURE'
        else:
            status = 'PENDING'

        data.append({
            'id': batch.id,
            'created_at': batch.created_at.strftime('%d/%m/%Y %H:%M'),
            'total': total,
            'status': status,
            'counts': counts,
        })

    return JsonResponse({'batches': data})


# ── Vues de lot MÉDIA : fabrique COMMUNE (`batch_views.make_batch_views`, portage 2026-09-23,
# 6ᵉ app réelle — ROUTE §11 #36 ; l'enhancer a DEUX files, donc deux fabriques). Spécificités
# DÉCLARÉES en kwargs : remise à zéro + cache de progression `enhancer_progress_<id>` à 0 sous le
# verrou, libellé = nom d'entrée ou URL, nom de chaque entrée du ZIP = `get_output_filename()`,
# dimensions/poids/durée de sortie remis à 0 à la duplication, cache purgé à la suppression.
# `batch_update` vient AUSSI de la fabrique depuis le 2026-10-02 : elle lit les réglages postés
# selon le schéma et les pose par `_apply_enhancement_settings` — LA fonction que la route d'un
# élément appelle aussi (`apply_settings`). La vue locale ne faisait que refaire sa boucle.
from wama.common.utils.batch_views import DEFAULT_RESET, make_batch_views
from wama.enhancer.params import MEDIA_PARAMS_JSON as _MEDIA_SCHEMA


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _media_task(e):
    from .tasks import enhance_media
    return enhance_media


def _reset_media_and_clear_progress(e):
    e.progress = 0
    e.error_message = ''
    cache.set(f"enhancer_progress_{e.id}", 0, timeout=3600)


# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — refaire la sortie seule
# (format, qualité) sans relancer l'amélioration. Le lancement lit les réglages STOCKÉS.
from wama.common.utils.process_views import make_process_start_view  # noqa: E402

start_process = make_process_start_view(
    work_model=Enhancement, task_for=_media_task,
    reset_on_start=_reset_media_and_clear_progress)


_bv = make_batch_views(
    work_model=Enhancement, batch_model=BatchEnhancement, get_user=_get_user,
    task_for=_media_task,
    output_fields=('output_file',),
    output_name=lambda e: e.get_output_filename(),
    zip_name=lambda b: f"batch_enhancer_{b.id}_{datetime.date.today()}.zip",
    item_model=BatchEnhancementItem, fk_name='enhancement',
    reset_on_start=_reset_media_and_clear_progress,
    reset_on_duplicate={**DEFAULT_RESET, 'output_width': 0, 'output_height': 0,
                        'output_file_size': 0, 'processing_time': 0},
    progress_of=lambda e: cache.get(f"enhancer_progress_{e.id}", e.progress or 0),
    item_label=lambda e: e.get_input_filename() or e.source_url,
    on_delete=lambda e: cache.delete(f"enhancer_progress_{e.id}"),
    schema=_MEDIA_SCHEMA, empty_is_value=SETTINGS_EMPTY_IS_VALUE,
    apply_settings=_apply_enhancement_settings,
)
batch_start = _bv['batch_start']
batch_update = _bv['batch_update']
batch_status = _bv['batch_status']
batch_download = _bv['batch_download']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


# ===========================================================================
# Audio Enhancement Views
# ===========================================================================

# Ce que prend la porte audio : la déclaration du domaine (`app_modes.surface_file_nature`),
# comme la porte image/vidéo. Une copie locale de la liste omettait `.aif`/`.aiff` — un 400
# « Format audio non supporté » sur un fichier que la dropzone (`audio/*`) laissait choisir ;
# divergence MUETTE : un sous-ensemble ne lève rien, il refuse. Décodage vérifié avant
# d'élargir — soundfile (vers qui torchaudio est patché) écrit et relit l'AIFF.
def _takes_audio(name) -> bool:
    from wama.common.utils.app_modes import surface_file_nature
    return bool(surface_file_nature('enhancer', 'audio_enhancer', name))


@require_POST
def audio_upload(request):
    """Upload an audio file for speech enhancement, or register from file_path."""
    import json as _json
    from pathlib import Path as _Path
    from django.conf import settings as _settings
    from django.core.files import File as _File

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # --- Option A: file_path from filemanager (server-side path) ---
    file_path = None
    try:
        body = _json.loads(request.body)
        file_path = body.get('file_path', '').strip()
    except Exception:
        pass

    if file_path:
        from wama.common.utils.media_paths import OutsideMediaRoot, resolve_under_media_root
        try:
            src, _ = resolve_under_media_root(file_path)
        except (OutsideMediaRoot, FileNotFoundError):
            return JsonResponse({'error': 'Fichier introuvable ou accès refusé'}, status=400)
        if not _takes_audio(src.name):
            return JsonResponse({'error': f'Format audio non supporté : {src.suffix}'}, status=400)

        try:
            with open(str(src), 'rb') as f:
                django_file = _File(f, name=src.name)
                ae = AudioEnhancement.objects.create(
                    user=user,
                    input_file=django_file,
                    file_size=src.stat().st_size,
                    # Naissance COMMUNE (2026-10-28) : défauts ← volet retenu ← ce qui est posté.
                    **_audio_deposit_settings(user, {k: v for k, v in body.items()
                                                     if k != 'file_path'}),
                )
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

        _wrap_audio_in_batch(ae)
        return JsonResponse({
            'id': ae.id,
            'input_filename': ae.get_input_filename(),
            'file_size': ae.file_size,
            'duration': ae.duration,
            'status': ae.status,
        })

    # --- Option B: fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique `received_inputs`,
    # comme la vue `upload` de la même app. ⚠ Jusqu'au 2026-09-30 cette vue ne lisait que
    # `request.FILES['file']` : la désignation (28/09 — la tuile Médiathèque et le glisser depuis
    # l'arbre POINTENT au lieu de recopier) tombait en « Bad Request » sur la card AUDIO, en v3
    # comme en v4. Trouvé par le geste `enhancer.tree_drop`, le premier à mesurer cette card.
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'enhancer')
    if not received:
        return JsonResponse({'error': received.refusal or 'Aucun fichier fourni'}, status=400)
    file = received[0]

    ext = os.path.splitext(file.name)[1].lower()
    if not _takes_audio(file.name):
        return JsonResponse({'error': f'Format audio non supporté : {ext}'}, status=400)

    try:
        ae = AudioEnhancement.objects.create(
            user=user,
            input_file=file.value,
            file_size=getattr(file.value, 'size', 0) or 0,
            # Naissance COMMUNE (2026-10-28) : défauts ← volet retenu ← ce que le dépôt poste ;
            # ce qui est posté devient la mémoire du volet audio.
            **_audio_deposit_settings(user, request.POST, inputs_by_port('enhancer', file)),
        )
        file.record(ae, 'input_file')
        if not ae.file_size:
            try:
                ae.file_size = ae.input_file.size
                ae.save(update_fields=['file_size'])
            except Exception:
                pass
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    # Attempt to get duration via ffprobe
    try:
        from ..common.utils.video_utils import get_media_info
        info = get_media_info(ae.input_file.path)
        ae.duration = info.get('duration', 0)
        ae.file_size = info.get('file_size', ae.file_size)
        ae.save(update_fields=['duration', 'file_size'])
    except Exception:
        pass

    _wrap_audio_in_batch(ae)
    return JsonResponse({
        'id': ae.id,
        'input_filename': ae.get_input_filename(),
        'file_size': ae.file_size,
        'duration': ae.duration,
        'status': ae.status,
    })


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
audio_download_all = _apv['download_all']


# ===========================================================================
# Audio Batch Views
# ===========================================================================

def audio_batch_template(request):
    """Gabarit de fichier batch du domaine audio, par la brique commune
    (`batch_template_response`) : une source par ligne, les formats que le domaine DÉCLARE (la
    liste était recopiée ici). Écrit à la main jusqu'au 2026-11-02."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'audio_enhancer', ['source'], {'source': 'https://example.com/voice.wav'},
        label='Enhancer audio (une URL ou un chemin audio par ligne)',
        app='enhancer', domain='audio')


@require_POST
def audio_batch_preview(request):
    """Parse a batch file (one audio URL/path per line) and return the list for preview — the
    COMMON helper of the image/video batch (2026-10-28 : the file's reading was copied here)."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def audio_batch_create(request):
    """Parse batch file, create BatchAudioEnhancement + AudioEnhancement entries — the batch file
    is read by the COMMON helper, as the image/video batch does (2026-10-28)."""
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    batch_file = request.FILES.get('batch_file')  # re-lu après parsing (NameError avant 2026-08-03)
    if batch_file:
        batch_file.seek(0)
    batch = BatchAudioEnhancement.objects.create(user=user, total=len(items), batch_file=batch_file)

    # Chaque fille naît par la cascade COMMUNE d'un dépôt (2026-10-28) : elle naissait sur les
    # défauts du modèle, et le ▶ du lot devait lui reposter le volet.
    settings_values = _audio_deposit_settings(user, request.POST)
    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        ae = AudioEnhancement.objects.create(**settings_values, user=user, source_url=url_or_path)
        BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=ae, row_index=i)
        created_ids.append(ae.id)

    return JsonResponse({'batch_id': batch.id, 'audio_ids': created_ids, 'total': len(items), 'warnings': warnings})


# ── Vues de lot AUDIO : la seconde fabrique de l'enhancer (mêmes briques, autre file).
# ▶ de lot PORTE des réglages (moteur, mode, force du débruitage, qualité, curseur) postés en
# JSON avec le démarrage : `start_reset_for` fabrique la remise à zéro depuis la requête —
# sous le verrou, comme avant. Cache `audio_enhancer_progress_<id>`, ZIP `audio_batch_<id>_<date>`.
def _audio_task(ae):
    from .tasks import enhance_audio
    return enhance_audio


audio_start_process = make_process_start_view(
    work_model=AudioEnhancement, task_for=_audio_task,
    reset_on_start={'progress': 0, 'error_message': ''})


def _audio_reset_for(request):
    import json as _json
    try:
        data = _json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    def _reset(ae):
        ae.progress = 0
        ae.error_message = ''
        # Un ▶ de lot qui POSTE des réglages les pose par la fonction unique du domaine ; sans
        # corps (les filles sont nées complètes depuis le 2026-10-28), il lance tel quel.
        _apply_audio_settings(ae, data)
    return _reset


from wama.enhancer.params import AUDIO_PARAMS_JSON as _AUDIO_SCHEMA  # noqa: E402

# Le schéma et LA fonction de réglage du domaine (2026-10-28) : la fabrique en tire les réglages de
# LOT (`batch_update` — le ⚙ de la card mère audio était rendu sans que rien ne l'écoute), la
# promotion d'une fille au lot et le réalignement, comme au domaine image/vidéo.
_abv = make_batch_views(
    work_model=AudioEnhancement, batch_model=BatchAudioEnhancement, get_user=_get_user,
    task_for=_audio_task, start_reset_for=_audio_reset_for,
    output_fields=('output_file',),
    output_name=lambda ae: ae.get_output_filename(),
    zip_name=lambda b: f"audio_batch_{b.id}_{datetime.date.today()}.zip",
    item_model=BatchAudioEnhancementItem, fk_name='audio_enhancement',
    reset_on_duplicate={**DEFAULT_RESET, 'processing_time': 0},
    progress_of=lambda ae: cache.get(f"audio_enhancer_progress_{ae.id}", ae.progress or 0),
    item_label=lambda ae: ae.get_input_filename() or ae.source_url,
    on_delete=lambda ae: cache.delete(f"audio_enhancer_progress_{ae.id}"),
    schema=_AUDIO_SCHEMA, empty_is_value=SETTINGS_EMPTY_IS_VALUE,
    apply_settings=_apply_audio_settings,
)
audio_batch_start = _abv['batch_start']
audio_batch_update = _abv['batch_update']
audio_batch_status = _abv['batch_status']
audio_batch_download = _abv['batch_download']
audio_batch_delete = _abv['batch_delete']
audio_batch_duplicate = _abv['batch_duplicate']
audio_batch_promote = _abv['batch_promote']
audio_batch_realign = _abv['batch_realign']


def console_content(request):
    """
    Retourne le contenu de la console (logs Celery + cache).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Récupère les logs depuis le cache et Celery
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})


# ═══════════════════════════════════════════════════════════════════════════
# Vues standard communes (port schéma-driven 2026-07-26) — LES DEUX DOMAINES
# ═══════════════════════════════════════════════════════════════════════════

def _req_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


# Card de chaque domaine = partial serveur UNIQUE, par la fabrique commune (`make_card_view`,
# 2026-11-02) ; la décoration est celle de l'IndexView (chips du schéma, process).
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=Enhancement, template='enhancer/_enhancement_card.html',
                           decorate=lambda e: _decorate_media_card(e))
audio_card_html = make_card_view(work_model=AudioEnhancement, template='enhancer/_audio_card.html',
                                 decorate=lambda ae: _decorate_audio_card(ae))


# ── Manipulation directe de la file (fabrique COMMUNE, variante liaison) ──────
# Les deux domaines ont un MODÈLE DE LIAISON (BatchEnhancementItem /
# BatchAudioEnhancementItem) → fabrique standard, `consolidate` compris (2026-10-16).
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

_qm_media = make_queue_manipulation_views(
    work_model=Enhancement, batch_model=BatchEnhancement,
    item_model=BatchEnhancementItem, fk_name='enhancement', get_user=_req_user,
    group_key=_enhancement_nature,      # l'arrivée (`consolidate_arrival`) ET le glisser-déposer
)
remove_from_batch = _qm_media['remove_from_batch']
reorder           = _qm_media['reorder']
reorder_queue     = _qm_media['reorder_queue']
merge             = _qm_media['merge']
move_to_batch     = _qm_media['move_to_batch']

_qm_audio = make_queue_manipulation_views(
    work_model=AudioEnhancement, batch_model=BatchAudioEnhancement,
    item_model=BatchAudioEnhancementItem, fk_name='audio_enhancement', get_user=_req_user,
)
audio_remove_from_batch = _qm_audio['remove_from_batch']
audio_reorder           = _qm_audio['reorder']
audio_reorder_queue     = _qm_audio['reorder_queue']
audio_merge             = _qm_audio['merge']
audio_move_to_batch     = _qm_audio['move_to_batch']
# `consolidate` des deux files (2026-10-16) : la fabrique range PAR NATURE à l'arrivée
# (`consolidate_arrival`) — les deux versions locales et leurs helpers sont retirés.
consolidate             = _qm_media['consolidate']
audio_consolidate       = _qm_audio['consolidate']
