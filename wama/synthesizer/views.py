"""
WAMA Synthesizer - Views
Interface de synthèse vocale
"""

import os
import logging
from pathlib import Path
from django.conf import settings
from django.shortcuts import render
from django.views import View
from django.views.generic import TemplateView
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.cache import cache
from wama.common.utils.param_schema import sampling_options
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str, iri_to_uri
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile


import json
from .models import VoiceSynthesis, BatchSynthesis, BatchSynthesisItem
from .params import PARAMS_JSON as _SYNTH_PARAMS_JSON, user_setting_key
from wama.common.tts.constants import DEFAULT_TTS_MODEL, tts_catalog_key
from wama.common.utils.auto_model import read_quality_intent
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.input_match import input_labels as _input_labels
from wama.common.utils.media_paths import received_inputs
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.queue_duplication import safe_delete_file, release_card_file

logger = logging.getLogger(__name__)

# Lazy import for Celery task (avoids importing heavy TTS libs at Gunicorn startup)
synthesize_voice = None

def _ensure_workers_imported():
    """Lazy import of synthesize_voice Celery task."""
    global synthesize_voice
    if synthesize_voice is None:
        from .workers import synthesize_voice as sv
        synthesize_voice = sv


def _wrap_synthesis_in_batch(synthesis):
    """Un lot d'un élément — par le service unique de l'app (`services.wrap_in_batch`)."""
    from .services import wrap_in_batch
    return wrap_in_batch(synthesis)


def _auto_wrap_orphans(user):
    """Range les VoiceSynthesis pas encore en lot — brique COMMUNE (`auto_wrap_orphans`, orphelin →
    lot d'un), avec le nom de sortie de la liaison (`services.batch_link_extra`). Écrite à la main
    ici jusqu'au 2026-10-16 ; `consolidate` vient de la fabrique (`_qm`, plus bas)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    from .services import batch_link_extra
    auto_wrap_orphans(user, work_model=VoiceSynthesis, batch_model=BatchSynthesis,
                      item_model=BatchSynthesisItem, fk_name='synthesis',
                      item_extra=batch_link_extra)


def synthesis_panel_values(user, app='synthesizer') -> dict:
    """Les valeurs du VOLET de l'auteur, par NOM de param : ses derniers choix mémorisés, les
    défauts du schéma pour le reste (brique commune `read_panel_settings`). C'est ce que la page
    affiche et ce que la card poste ; une synthèse créée SANS volet (import du gestionnaire de
    fichiers, « Envoyer vers ») le reçoit tel quel en `params` de `create_synthesis`.
    `app` : une jumelle de bac à sable passe le sien. Ce qui se retient, et sous quelle clé, est
    déclaré dans `params.py` (`user_setting_key`)."""
    from wama.common.utils.user_settings import read_panel_settings
    return read_panel_settings(user, app, _SYNTH_PARAMS_JSON, key=user_setting_key)


def new_synthesis_settings(user, model=None, app='synthesizer', post=None, inputs=None) -> dict:
    """Les colonnes de réglage d'une synthèse NAISSANTE, par la cascade COMMUNE (défauts du
    schéma ← réglages retenus de l'auteur ← ce qui est posté, `user_settings.new_element_settings`,
    2026-10-18). Le résultat se passe en `params` au chemin unique de l'app
    (`services.create_synthesis`), dont le contrat ne change pas : `params` = les réglages donnés.
    `model`/`app` : une jumelle de bac à sable passe les siens."""
    from wama.common.utils.user_settings import new_element_settings
    return new_element_settings(user, app, _SYNTH_PARAMS_JSON, model or VoiceSynthesis, inputs=inputs,
                                post=post, key=user_setting_key)


def synthesis_params(user, post, model=None, app='synthesizer', inputs=None) -> dict:
    """Les `params` d'une synthèse NAISSANTE pour `create_synthesis` : la cascade commune, plus ce
    que `post` porte hors schéma (réglages Higgs, titre). Le dépôt de la card et l'outil de
    l'assistant (`tool_api.synthesize_text`, 2026-10-29) ; `model`/`app` : une jumelle passe les
    siens."""
    posted = post.dict() if hasattr(post, 'dict') else dict(post)
    return {**posted, **new_synthesis_settings(user, model=model, app=app, post=posted, inputs=inputs)}


#: Le champ de chaque PORT fichier d'une synthèse (des données : ils gardent leur nom) — lu par la
#: brique des lignes de lot (`batch_parsers.line_file_inputs`, 2026-11-06).
_LINE_FIELDS = {'reference_voice': 'voice_reference'}


def _deposit_params(user, post, work_file=None):
    """Les `params` d'un DÉPÔT (fichier, texte, lot) pour `create_synthesis` (`synthesis_params`).
    Ce qui a été posté devient la mémoire du volet (`save_panel_settings`) — le dépôt d'un FICHIER
    ne la tenait pas, seul celui d'un texte le faisait. `work_file` : le fichier reçu, qui propose
    ses réglages sous son port (`inputs_by_port`)."""
    from wama.common.utils.user_settings import inputs_by_port, save_panel_settings
    posted = post.dict() if hasattr(post, 'dict') else dict(post)
    params = synthesis_params(user, posted, inputs=inputs_by_port('synthesizer', work_file))
    save_panel_settings(user, 'synthesizer', _SYNTH_PARAMS_JSON, posted, key=user_setting_key)
    return params


class IndexView(View):
    """Page principale du synthesizer."""

    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Lazily migrate any orphan VoiceSynthesis into a batch-of-1
        _auto_wrap_orphans(user)

        # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
        from wama.common.utils.process_control import reconcile_queue_of
        reconcile_queue_of(VoiceSynthesis, user)

        # File — briques COMMUNES build_batches_list (contrat _batch_card) +
        # tri/filtre persistés session (contrat _queue_toolbar).
        from wama.common.utils.batch_common import build_batches_list
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _extra(batch, items, works):
            from wama.common.utils.card_chips import common_chips_for_items as _ccfi
            from wama.synthesizer.params import PARAMS_JSON as _SYN_PARAMS_JSON
            done = sum(1 for w in works if w.status == 'SUCCESS')
            first_s = works[0] if works else None
            return {
                'success_pct': int(done / batch.total * 100) if batch.total > 0 else 0,
                # (l'ETA agrégée de la card mère, `eta_ids`, vient de `build_batches_list` —
                # elle était posée ici en LISTE, que `wama-eta.js` ne découpe pas : lot sans ETA)
                'first_tts_model': first_s.tts_model if first_s else DEFAULT_TTS_MODEL,
                'first_language': first_s.language if first_s else 'fr',
                'first_voice_preset': first_s.voice_preset if first_s else 'default',
                'first_speed': first_s.speed if first_s else 1.0,
                'first_pitch': first_s.pitch if first_s else 1.0,
                # Réglages COMMUNS aux filles (slot meta_template — porté le 31/08).
                'common_chips': _ccfi(works, _SYN_PARAMS_JSON),
            }

        batches_list = build_batches_list(
            user, batch_model=BatchSynthesis, work_attr='synthesis', extra=_extra)

        # Chips de card GÉNÉRÉS du schéma (brique card_chips) — même décoration que card_html.
        # Les lignes d'exécution de TOUTES les cards de la page sont lues en une requête.
        from wama.common.services.process_pipeline import decorate_cards
        decorate_cards([link.synthesis for b in batches_list for link in b['items']],
                       _decorate_synthesis)

        # Multi-item batches first, then single-item batches
        # (« batchs d'abord » RETIRÉ le 2026-08-24 — écrasé par `apply_queue_sort_filter`
        #  juste en dessous ; la règle a été abandonnée le 2026-06-29.)

        queue_count = sum(len(b['items']) for b in batches_list)

        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list,
            name_of=lambda b: str(b['obj']))

        # Voix : UN seul inventaire, celui de la brique commune (défaut + références de la
        # MÉDIATHÈQUE + mes voix + celles qu'on m'a PARTAGÉES + Bark). La page n'en rend plus
        # le markup : elle passe les groupes au champ GÉNÉRÉ du schéma (2026-09-23) — même
        # geste que l'avatarizer. Les deux listes d'avant (`custom_voices` = mes UserAsset
        # seuls, `voice_refs_groups`) disaient une partie de ce que `get_voice_groups` dit en
        # entier, et la partie manquante était celle des voix partagées.
        from wama.common.tts.voice_refs import needs_voice_download
        from wama.common.utils.voice_options import voice_groups_json

        # Téléchargement automatique en fond si des voix manquent (une seule fois par heure)
        if needs_voice_download():
            _dl_flag = 'voice_refs_download_triggered'
            if not cache.get(_dl_flag):
                cache.set(_dl_flag, True, timeout=3600)
                try:
                    from .workers import download_voice_refs_task
                    download_voice_refs_task.delay()
                    logger.info("[Synthesizer] Téléchargement des voix de référence lancé en arrière-plan")
                except Exception as exc:
                    logger.warning(f"[Synthesizer] Impossible de lancer le téléchargement des voix : {exc}")

        context = {
            'batches_list': batches_list,
            'queue_count': queue_count,
            # Groupes de voix du champ généré (brique commune) — `optionsResolver` du gabarit.
            'voice_groups_json': voice_groups_json(user),
            # Le VOLET est GÉNÉRÉ du schéma (2026-10-11) : plus de pré-rendu des moteurs ni des
            # langues ici — le select de modèle se peuple par le CATALOGUE (`options_source`),
            # la langue par ses `choices`. Ses VALEURS sont les derniers choix mémorisés, lus par
            # la brique commune sous leurs clés historiques (`preferred_*`, écrites à la création
            # d'une synthèse), les défauts du schéma pour le reste.
            'params_json': json.dumps(_SYNTH_PARAMS_JSON),
            'panel_values_json': json.dumps(synthesis_panel_values(user)),
            # Appariement entrée↔modèles (brique commune input_match) : une voix CLONÉE
            # choisie grise les moteurs sans clonage — cf. INPUT_MODEL_MATCHING.md.
            'input_match_meta': json.dumps(self._input_match_meta()),
            'input_labels': json.dumps(_input_labels()),
            'q_sort': q_sort,
            'q_filter': q_filter,
        }
        return render(request, 'synthesizer/index.html', context)

    #: Les deux metas d'UI des moteurs TTS ont DÉMÉNAGÉ dans `common/tts/ui_meta.py` au 2ᵉ
    #: consommateur (avatarizer, pipeline dérivé du 2026-08-28) — remplacées ici par un appel,
    #: jamais recopiées là-bas. `ENGINE_CATALOG_KEYS` reste PASSÉ : c'est le point d'accroche
    #: déclaré d'un futur id divergent (`backends/base.py`), et le substrat ne doit pas le
    #: connaître. ⚠ Il y est traité comme un jeu d'EXCEPTIONS, plus comme l'inventaire des
    #: moteurs : ses entrées privaient de descriptif tout moteur qui n'y figurait pas, alors
    #: que le select en proposait 7 et que les 7 étaient au catalogue (mesuré 28/08 ; trois
    #: d'entre eux ont été retirés le même jour — `REMOVAL_LEDGER` R32 — mais la règle tient
    #: sans eux : une table d'exceptions ne remplace jamais l'inventaire).
    @staticmethod
    def _input_match_meta():
        from wama.common.tts.ui_meta import tts_input_match_meta
        from .utils.model_config import ENGINE_CATALOG_KEYS
        return tts_input_match_meta(ENGINE_CATALOG_KEYS)


def _card_created_response(synthesis, **extra):
    """La réponse commune des deux vues de la card (fichier déposé, texte saisi)."""
    return JsonResponse({
        'id': synthesis.id,
        'text_file_url': synthesis.text_file.url,
        'text_file_label': os.path.basename(smart_str(synthesis.text_file.name)),
        'status': synthesis.status,
        'word_count': synthesis.word_count,
        'duration_display': synthesis.duration_display,
        'properties': synthesis.properties or 'En attente',
        'options': {
            'model': synthesis.get_tts_model_display(),
            'language': synthesis.get_language_display(),
            'voice': synthesis.get_voice_preset_display(),
        },
        **extra,
    })


@require_POST
def upload(request):
    """La card reçoit un FICHIER DE TRAVAIL (téléversé, ou désigné : médiathèque, arbre) — et,
    s'il y en a une, la VOIX DE RÉFÉRENCE. La création est LE chemin unique de l'app
    (`services.create_synthesis`), le même que l'outil du Studio et de l'assistant."""
    from .services import SynthesisRefused, create_synthesis
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    received = received_inputs(request, user, 'synthesizer')
    if not received:
        return JsonResponse({'error': received.refusal or 'Aucun fichier fourni'}, status=400)
    voice = received_inputs(request, user, 'synthesizer', field='voice_reference')
    if not voice and voice.refusal:
        # Une voix désignée et REFUSÉE (fichier d'un autre) faisait naître la card avec la voix
        # par défaut, sans un mot (2026-10-13) : l'ajout est refusé avec son motif.
        return JsonResponse({'error': voice.refusal}, status=400)
    try:
        synthesis = create_synthesis(user, work_file=received[0],
                                     reference_voice=voice[0] if voice else None,
                                     params=_deposit_params(user, request.POST, received[0]))
    except (SynthesisRefused, ValueError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return _card_created_response(synthesis)


@require_POST
def upload_text(request):
    """La card reçoit le TEXTE saisi (le port `prompt`) — même chemin unique que `upload`."""
    from .services import SynthesisRefused, create_synthesis
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    voice = received_inputs(request, user, 'synthesizer', field='voice_reference')
    if not voice and voice.refusal:
        return JsonResponse({'error': voice.refusal}, status=400)
    try:
        synthesis = create_synthesis(user, prompt=request.POST.get('text_content', ''),
                                     title=request.POST.get('title', ''),
                                     reference_voice=voice[0] if voice else None,
                                     params=_deposit_params(user, request.POST))
    except (SynthesisRefused, ValueError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return _card_created_response(synthesis, success=True)


def _reset_synthesis_for_relaunch(s):
    """Reset partagé (start / start_all / batch_start) pour begin_processing."""
    s.progress = 0
    s.error_message = ''
    # ⚠ L'ancien audio n'est plus retiré au clic (2026-10-03) : un lancement ne rejoue que ce qui
    # n'est plus à jour, et un format changé ne rejoue que la sortie — depuis l'audio que la
    # synthèse a laissé. C'est la glu de la synthèse qui le remplace quand elle rejoue.


def _queue_panel(request, user):
    """Ce que « tout lancer » POSTE — « démarrer tout vaut appliquer à tout » : le volet, lu par le
    lecteur dérivé du schéma, les deux réglages hors schéma du même payload, et la voix de
    référence téléversée ou DÉSIGNÉE (médiathèque, arbre), POINTÉE par toutes les synthèses au lieu
    d'une copie par ligne. Une voix refusée lève : rien n'est lancé."""
    from wama.common.utils.batch_views import read_settings_payload
    names = [p['name'] for p in _SYNTH_PARAMS_JSON]
    data = read_settings_payload(request, _SYNTH_PARAMS_JSON, names)
    for extra in ('multi_speaker', 'scene_description'):
        if extra in request.POST:
            data[extra] = request.POST[extra]
    voice = received_inputs(request, user, 'synthesizer', field='voice_reference')
    if not voice and voice.refusal:
        raise ValueError(voice.refusal)
    if voice:
        data['voice_reference'] = voice[0].value
    return data


def _replace_voice(synthesis, data):
    """La voix postée remplace celle de la synthèse ; l'ancienne est LIBÉRÉE (brique commune)."""
    if data.get('voice_reference'):
        release_card_file(synthesis, 'voice_reference')
        synthesis.voice_reference = data['voice_reference']


# ▶ de la card, ▶ et 🗑 de la file : fabrique COMMUNE (`item_views.make_item_views`, ROUTE §11
# #39, 2026-10-29) — la même déclaration que lit l'outil `start_synthesizer`. « Tout lancer »
# relance tout ce qui ne tourne pas, avec le volet posté (la fonction de réglage d'une synthèse,
# celle de sa route d'élément et des lots), la voix remplacée sous le verrou seulement.
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(
    work_model=VoiceSynthesis, app_id='synthesizer', task_for=lambda s: _task_for(s),
    reset_on_start=_reset_synthesis_for_relaunch, pending={},
    queue_settings=_queue_panel,
    apply_settings=lambda s, data: _apply_synthesis_settings(
        s, {k: v for k, v in data.items() if k != 'voice_reference'}),
    on_queue_settings=_replace_voice, batch_model=BatchSynthesis,
    settings_file='voice_reference')
start = _iv['start']
start_all = _iv['start_all']
clear_all = _iv['clear_all']
# ⏹ ⬇ 🗑 ⧉ ⚙ d'une card : la fabrique COMMUNE (2026-11-02, ROUTE §11 #42 ④), qui lit ce que l'app
# déclare à sa fabrique de lot. Spécificité déclarée : la ⚙ reçoit la voix de référence,
# téléversée ou désignée (`settings_file`) — refusée, rien n'est écrit ; reçue, l'ancienne est
# libérée.
stop = _iv['stop']
download = _iv['download']
delete = _iv['delete']
duplicate = _iv['duplicate']
update_settings = _iv['update_settings']


def _decorate_synthesis(s, preloaded=False):
    """Chips de card générés du SCHÉMA (params.py chip=True) — brique commune card_chips ; et
    les PROCESS de la card (« Synthèse → Sortie ») avec son état MONTRÉ, par la brique commune
    (`process_pipeline.decorate`, `ROUTE §10.6` 5.1)."""
    from wama.common.services.process_pipeline import decorate
    from wama.common.utils.card_chips import chips_by_section
    from wama.synthesizer.params import PARAMS_JSON
    s.chips = chips_by_section(s, PARAMS_JSON)
    decorate(s, preloaded=preloaded)
    return s


# Card d'une synthèse rendue par le serveur, que la boucle de suivi redemande en fin de tâche :
# fabrique commune (`make_card_view`, 2026-11-02) — elle porte désormais `card_label`, le nom de
# sortie de la ligne de lot que la FILE lui donne et que ce rendu-ci perdait.
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=VoiceSynthesis, template='synthesizer/_synthesis_card.html',
                           decorate=lambda s: _decorate_synthesis(s))


def _progress_extra(synthesis):
    """Les clés PROPRES que le JS du synthesizer lit."""
    return {'audio_url': iri_to_uri(synthesis.audio_output.url) if synthesis.audio_output else None,
            'duration_display': synthesis.duration_display}


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que ses clés propres. L'ETA est celle de ses PROCESS
# (`function_specs.PIPELINE`, 2026-10-05).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=VoiceSynthesis, app_id='synthesizer',
                          extra=_progress_extra)
progress, global_progress = _pv['progress'], _pv['global_progress']



# ⚠ Les vues « Custom Voices » (liste, ajout, suppression — `/custom-voices/…`) sont RETIRÉES
# le 2026-09-30 (REMOVAL_LEDGER R89) : les voix d'un utilisateur s'ajoutent, s'écoutent et se
# suppriment dans la MÉDIATHÈQUE — sa page ou la fenêtre commune, que tout champ de voix ouvre
# (`WamaParams`, `options_source: 'voices'`). La liste et la suppression n'avaient plus aucun
# appelant ; l'ajout doublait `media_library.api_upload`.


def console_content(request):
    """
    Récupère le contenu de la console.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


def _apply_synthesis_settings(synthesis, data):
    """LES réglages d'une synthèse, posés sans sauver — la route d'un élément (`update_settings`)
    ET la fabrique des vues de lot passent ici. Jusqu'au 2026-10-02 le lot avait sa propre vue
    (`batch_update_settings`) : JSON seul, cinq champs relus à la main, et `speed`/`pitch`
    remis à 1.0 dès qu'ils n'étaient pas postés. Rend `None` : tout l'élément est sauvé (les
    métadonnées dérivées — durée estimée — sont recalculées ici, sans sauver)."""
    from wama.common.utils.batch_views import apply_item_settings
    if data.get('tts_model'):
        # Nom court saisi (fichier batch, outil) → clé de catalogue, comme à la création.
        data = {**data, 'tts_model': tts_catalog_key(str(data['tts_model']))}
    apply_item_settings(synthesis, data, params_fields=[p['name'] for p in _SYNTH_PARAMS_JSON])
    # Hors schéma, lus dans le MÊME payload.
    if 'emotion_intensity' in data:
        synthesis.emotion_intensity = float(data['emotion_intensity'])
    if 'multi_speaker' in data:
        synthesis.multi_speaker = str(data['multi_speaker']).lower() in ('1', 'true', 'on')
    if 'scene_description' in data:
        synthesis.scene_description = data['scene_description']
    synthesis.update_metadata(save=False)
    return None


@require_POST
def import_individual_from_path(request):
    """
    Create a single VoiceSynthesis from a file already on the server (server_path relative to MEDIA_ROOT).
    Used when a batch file from FileManager is chosen for individual synthesis instead.
    """
    server_path = request.POST.get('server_path', '').strip()
    if not server_path:
        return JsonResponse({'error': 'server_path requis'}, status=400)

    # 🔴 Confinement (05/09), puis DROIT DE LECTURE (30/09) : ce site pointait `server_path` après
    # le seul confinement dans MEDIA_ROOT — le fichier d'un AUTRE utilisateur passait. `designate`
    # porte les trois gardes communes (confinement, existence, `readable_by`) ; la création est le
    # chemin unique de l'app (`services.create_synthesis`).
    from wama.common.utils.media_paths import InputRefused, designate
    from .services import SynthesisRefused, create_synthesis
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    try:
        received = designate(server_path, user, 'synthesizer')
    except InputRefused as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    try:
        synthesis = create_synthesis(user, work_file=received,
                                     params=_deposit_params(user, request.POST, received))
    except (SynthesisRefused, ValueError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'success': True, 'id': synthesis.id})


# ============= BATCH SYNTHESIS =============

def batch_template(request):
    """Gabarit de fichier batch, par la brique commune (`batch_template_response`) : ses
    colonnes dans l'ordre de son format positionnel (`utils/batch_parser.py`), que le lecteur
    accepte aussi en tableur et en balises. Écrit à la main jusqu'au 2026-11-02, sous le nom
    `batch_template.txt` — le seul gabarit sans le nom de son app."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'synthesizer', ['sortie', 'texte', 'voix', 'vitesse'],
        {'sortie': 'consigne_1.wav',
         'texte': 'Bonjour, veuillez vous installer confortablement dans le simulateur.',
         'voix': 'default', 'vitesse': '1.0'},
        label='Synthesizer (un texte à dire par ligne)',
        notes=('Les colonnes voix et vitesse sont optionnelles (défauts du volet).',))


@require_POST
def batch_preview(request):
    """
    Parse a batch file and return the task list for preview (no DB entries created).
    """
    import tempfile

    batch_file = request.FILES.get('batch_file')
    if not batch_file:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)

    ext = os.path.splitext(batch_file.name)[1][1:].lower()
    if ext not in ('txt', 'pdf', 'docx', 'csv', 'md'):
        return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)

    # Les défauts de LIGNE (voix, vitesse) : ceux du lot s'il les poste, sinon la cascade commune —
    # l'aperçu montre ce que la création fera.
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    base = new_synthesis_settings(user, post=request.POST.dict())
    default_voice = request.POST.get('default_voice') or base.get('voice_preset')
    try:
        default_speed = float(request.POST.get('default_speed') or base.get('speed'))
    except (ValueError, TypeError):
        default_speed = base.get('speed')

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            for chunk in batch_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        from .utils.batch_parser import parse_batch_file
        tasks, warnings = parse_batch_file(
            tmp_path, default_voice=default_voice, default_speed=default_speed,
            source_name=batch_file.name,
        )
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return JsonResponse({
        'tasks': tasks,
        'warnings': warnings,
        'count': len(tasks),
    })


@require_POST
def batch_create(request):
    """
    Parse batch file, create BatchSynthesis + VoiceSynthesis entries.
    Returns batch_id and list of synthesis IDs.
    Accepts either a `batch_file` upload or a `server_path` (relative to MEDIA_ROOT)
    for files already on the server (e.g. imported from FileManager).
    """
    import tempfile
    import datetime
    from django.conf import settings as django_settings

    batch_file = request.FILES.get('batch_file')
    server_path = request.POST.get('server_path', '').strip()

    if not batch_file and not server_path:
        return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)

    # Chaque ligne naît par la cascade commune d'un dépôt (`_deposit_params`) ; la voix et la
    # vitesse de la cascade sont les défauts de LIGNE du parseur, qu'une ligne peut surcharger.
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    base_params = _deposit_params(user, request.POST)
    default_voice = base_params.get('voice_preset')
    default_speed = base_params.get('speed')

    tmp_path = None
    try:
        if server_path:
            # File already on server (e.g. imported from FileManager) — parse directly
            # Même garde de confinement qu'`import_individual_from_path` (05/09, jumeau).
            # + DROIT DE LECTURE (30/09, comme l'import individuel) : le fichier d'un autre passait.
            from wama.common.utils.media_paths import (OutsideMediaRoot, readable_by,
                                                       resolve_under_media_root)
            try:
                abs_path, server_path = resolve_under_media_root(server_path)
            except OutsideMediaRoot:
                return JsonResponse({'error': 'Chemin non autorisé'}, status=403)
            except FileNotFoundError:
                return JsonResponse({'error': 'Fichier introuvable sur le serveur'}, status=404)
            if not readable_by(server_path, user):
                return JsonResponse({'error': 'Chemin non autorisé'}, status=403)
            ext = abs_path.suffix[1:].lower()
            if ext not in ('txt', 'pdf', 'docx', 'csv', 'md'):
                return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)
            from .utils.batch_parser import parse_batch_file
            tasks, warnings = parse_batch_file(
                str(abs_path), default_voice=default_voice, default_speed=default_speed,
                source_name=os.path.basename(server_path),
            )
        else:
            ext = os.path.splitext(batch_file.name)[1][1:].lower()
            if ext not in ('txt', 'pdf', 'docx', 'csv', 'md'):
                return JsonResponse({'error': f'Format non supporté : {ext}'}, status=400)
            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
                for chunk in batch_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            from .utils.batch_parser import parse_batch_file
            tasks, warnings = parse_batch_file(
                tmp_path, default_voice=default_voice, default_speed=default_speed,
                source_name=batch_file.name,
            )
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # La VOIX À IMITER d'une ligne (`-r`, 2026-11-06) se reçoit comme sur la card, par la brique
    # commune des lignes de lot : un chemin se désigne, une URL devient la source téléchargée
    # (`WAMA_INGEST`). Elle était lue puis PERDUE. Jugée AVANT de créer quoi que ce soit : une voix
    # refusée écarte sa ligne, avec son motif.
    from wama.common.utils.batch_parsers import attach_line_inputs, line_file_inputs, line_file_ports
    lines = []
    for task in tasks:
        try:
            files = (line_file_ports('synthesizer', {'reference': task['voice_reference'],
                                                     'line_num': task.get('line_num')})
                     if task.get('voice_reference') else {})
            lines.append((task, *line_file_inputs(user, 'synthesizer', files, _LINE_FIELDS,
                                                  model=VoiceSynthesis)))
        except ValueError as exc:        # `InputRefused` compris : une désignation refusée
            warnings.append(f"Ligne {task.get('line_num') or '?'} : {exc} — ignorée")
    if not lines:
        return JsonResponse({'error': 'Aucune tâche valide trouvée dans le fichier',
                             'warnings': warnings}, status=400)

    # Save the batch file reference
    if batch_file:
        batch_file.seek(0)
    batch = BatchSynthesis.objects.create(
        user=user,
        total=len(lines),
        batch_file=batch_file if batch_file else None,
    )

    # Chaque LIGNE est une synthèse créée par le chemin unique de l'app (`services.create_synthesis`)
    # — ses réglages sont ceux du volet, surchargés par la ligne (voix, vitesse).
    from .services import create_synthesis
    created_ids = []
    for i, (task, received, remote) in enumerate(lines):
        synthesis = create_synthesis(
            user, prompt=task['text'], title=os.path.splitext(task['output_filename'])[0],
            params={**base_params, 'voice_preset': task['voice'], 'speed': task['speed']},
            reference_voice=received.get('voice_reference'), wrap=False)
        attach_line_inputs(synthesis, {}, remote)
        BatchSynthesisItem.objects.create(
            batch=batch,
            synthesis=synthesis,
            output_filename=task['output_filename'],
            row_index=i,
        )
        created_ids.append(synthesis.id)

    return JsonResponse({
        'batch_id': batch.id,
        'synthesis_ids': created_ids,
        'total': len(lines),
        'warnings': warnings,
    })


# ── Six vues de lot par la fabrique COMMUNE (`batch_views.make_batch_views`, portage
# 2026-09-23, 8ᵉ app réelle — ROUTE §11 #36). Spécificités DÉCLARÉES : la tâche s'importe
# paresseusement (`_ensure_workers_imported`, comme `start`) ; la remise à zéro du ▶ est celle de
# `start` (`_reset_synthesis_for_relaunch`) plus le cache de progression posé à 0 ; la progression
# se lit dans ce cache ; le nom de chaque fichier de l'archive ET le libellé de `batch_status`
# viennent de la LIGNE de liaison (`batch_link.output_filename`), que la duplication recopie
# (`item_extra`) ; le lot copié PARTAGE le fichier de lot (`batch_extra`, sans copie physique —
# `safe_delete_file` juge les références) ; `properties` vidé à la duplication.
# ⚠ Retiré, mesuré : la clé `audio_url` des lignes de `batch_status` — 0 lecteur (aucun gabarit
# ni JS du synthesizer n'appelle `batch_status`), la forme COMMUNE des lignes fait foi.
# Les réglages de lot viennent de la fabrique depuis le 2026-10-02 : elle appelle
# `_apply_synthesis_settings`, la fonction de la route d'élément (la vue locale
# `batch_update_settings` réécrivait cinq champs à côté). `batch_list` n'est pas une vue de
# lot : elle lit par `batch_elements`.
from wama.common.utils.batch_views import make_batch_views


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _task_for(_synthesis):
    _ensure_workers_imported()
    return synthesize_voice


def _reset_and_seed_progress(s):
    _reset_synthesis_for_relaunch(s)
    cache.set(f"synthesizer_progress_{s.id}", 0, timeout=3600)


from wama.common.utils.process_views import make_process_start_view  # noqa: E402


# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — refaire la sortie seule
# (format, qualité) sans re-synthétiser, ou re-synthétiser sans attendre qu'un réglage change.
start_process = make_process_start_view(
    work_model=VoiceSynthesis, task_for=_task_for, reset_on_start=_reset_and_seed_progress)


def _shared_batch_file(batch):
    return ({'batch_file': batch.batch_file.name}
            if batch.batch_file and batch.batch_file.name else {})


def _line_name(s):
    """Le nom de sortie que porte la LIGNE de lot de la synthèse (`batch_link`, posé par
    `batch_elements` et par les gestes d'une card), `''` sans ligne."""
    return getattr(getattr(s, 'batch_link', None), 'output_filename', '') or ''


def _zip_name(batch):
    import datetime
    return f"batch_{batch.pk}_{datetime.date.today()}.zip"


_bv = make_batch_views(
    work_model=VoiceSynthesis, batch_model=BatchSynthesis, get_user=_get_user,
    task_for=_task_for, reset_on_start=_reset_and_seed_progress,
    output_fields=('audio_output',),
    output_field='audio_output',
    item_model=BatchSynthesisItem, fk_name='synthesis',
    reset_on_duplicate={'status': 'PENDING', 'progress': 0, 'task_id': '', 'properties': '',
                        'error_message': ''},
    item_extra=lambda copy, original: {'output_filename': _line_name(original)
                                       or batch_link_extra(copy)['output_filename']},
    batch_extra=_shared_batch_file,
    progress_of=lambda s: cache.get(f"synthesizer_progress_{s.id}", s.progress or 0),
    item_label=_line_name,
    output_name=_line_name,
    zip_name=_zip_name,
    on_delete=lambda s: cache.delete(f"synthesizer_progress_{s.id}"),
    schema=_SYNTH_PARAMS_JSON,
    apply_settings=lambda synthesis, data: _apply_synthesis_settings(synthesis, data),
)
batch_start = _bv['batch_start']
batch_status = _bv['batch_status']
batch_download = _bv['batch_download']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_update = _bv['batch_update']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


def batch_list(request):
    """List the current user's batches with status counts."""
    from wama.common.utils.batch_common import batch_elements
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batches = BatchSynthesis.objects.filter(user=user).prefetch_related('items__synthesis')

    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for s in batch_elements(batch, VoiceSynthesis):   # brique : lit le lot PRÉCHARGÉ, 0 requête
            k = s.status.lower()
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


# ============= VOICE PREVIEW =============

@require_POST
def voice_preview(request):
    """Aperçu de la voix : les premiers mots du texte, rendus par LA chaîne de la synthèse.

    Depuis le 2026-09-28 (CARD_DESIGN §11.11 Étape 3, note sur l'aperçu) : même nettoyage du
    texte (`text_for_speech`), même tirage « auto », même voix, mêmes segments par moteur, même
    assemblage et même vitesse/hauteur que le worker (`utils/speech_render`) — l'aperçu fait donc
    entendre ce que la synthèse produira. Il remplace une chaîne à part (préparation en cache +
    flux SSE de WAV en base64 recollés par le navigateur, en-têtes compris).

    Le résultat est un FICHIER servi par URL, rangé comme les aperçus « pendant » des autres apps
    (`output/partials/`, nom fixe réécrit à chaque aperçu), et la réponse a la forme d'un aperçu
    commun (`url`, `mime_type`, `name`, `peaks`) : la page le rend par `renderInlinePreview` —
    lecteur `WamaAudioPlayer`, onde dessinée des pics serveur, comme le transcriber.
    """
    from wama.common.services.resource_governor import release_in_progress
    from wama.common.tts.service_client import TTSServiceLoadingError
    from wama.common.tts.voice_refs import speaker_wav_for
    from wama.common.utils.media_paths import get_app_media_path
    from wama.common.utils.tts_text import text_for_speech
    from wama.common.utils.waveform import compute_peaks
    from .utils.speech_render import preview_text, render_speech, resolve_tts_model

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    text = preview_text(text_for_speech(request.POST.get('text_content', '')))
    if not text:
        return JsonResponse({'error': 'Le texte ne peut pas être vide'}, status=400)
    # Les réglages de l'aperçu sont ceux que la synthèse aurait — la cascade COMMUNE (défauts du
    # schéma ← réglages retenus ← le POST), sans rien mémoriser (2026-10-18 : vitesse, hauteur,
    # voix et langue avaient chacune leur défaut écrit ici). Un nombre illisible est refusé par la
    # porte commune, il n'est pas remplacé par un défaut en silence.
    from wama.common.utils.param_schema import describe_refusals, schema_refusals
    refusals = schema_refusals(_SYNTH_PARAMS_JSON, request.POST)
    if refusals:
        return JsonResponse({'error': describe_refusals(refusals)}, status=400)
    chosen = new_synthesis_settings(user, post=request.POST.dict())
    # Fenêtre de libération de la carte (B1) : pas de voix — même garde que la vocalisation.
    if release_in_progress():
        return JsonResponse({'error': 'La carte graphique se libère : réessayez dans un instant.',
                             'busy': True}, status=503)

    default_model = VoiceSynthesis._meta.get_field('tts_model').get_default()
    voice_preset, language = chosen.get('voice_preset'), chosen.get('language')
    speed, pitch = chosen.get('speed'), chosen.get('pitch')
    try:
        model = resolve_tts_model(chosen.get('tts_model') or default_model, voice_preset,
                                  chosen.get('quality_intent'), fallback=default_model)
        speaker_wav = speaker_wav_for(model, voice_preset, user, language=language)
        folder = Path(get_app_media_path('synthesizer', user.id, 'output')) / 'partials'
        folder.mkdir(parents=True, exist_ok=True)
        # Les PAUSES du volet (2026-10-18) viennent de la même cascade que le reste : l'aperçu
        # fait entendre ce que la synthèse rendra.
        final = render_speech(
            text, str(folder / 'voice_preview.wav'),
            model=model, language=language, voice_preset=voice_preset, speaker_wav=speaker_wav,
            multi_speaker=request.POST.get('multi_speaker') == '1',
            scene_description=request.POST.get('scene_description', ''),
            speed=speed, pitch=pitch, read_timeout=60,
            sentence_pause=chosen.get('sentence_pause'),
            clause_pause=chosen.get('clause_pause'), sampling=sampling_options(chosen),
            user=user)
    except TTSServiceLoadingError:
        return JsonResponse({'error': 'Le service de synthèse vocale démarre : réessayez dans '
                                      'quelques secondes.', 'busy': True}, status=503)
    except (RuntimeError, ValueError) as exc:
        # La brique commune uniformise connexion/HTTP/délai en RuntimeError ; un moteur sans
        # backend enregistré lève ValueError. Un aperçu ne réessaie pas : il le dit, vite.
        return JsonResponse({'error': str(exc)}, status=502)

    import time
    rel = os.path.relpath(final, settings.MEDIA_ROOT).replace('\\', '/')
    peaks, duration = compute_peaks(final, buckets=400, dtype='uint8', with_duration=True)
    label = dict(VoiceSynthesis._meta.get_field('tts_model').flatchoices).get(model, model)
    return JsonResponse({
        # `?v=` : le nom est fixe, le navigateur ne doit pas resservir l'aperçu précédent.
        'url': f'{settings.MEDIA_URL}{rel}?v={int(time.time() * 1000)}',
        'mime_type': 'audio/wav',
        # Légende du lecteur commun (renderInlinePreview) : le moteur RÉEL, « auto » résolu.
        'name': f'Aperçu — {label} · {len(text.split())} mots',
        'peaks': peaks or [],
        'duration': duration,
        'model': model,
        'model_label': label,
        'word_count': len(text.split()),
    })


# ── Manipulation directe de la file (fabrique COMMUNE, variante liaison) ──────
# BatchSynthesisItem est le modèle de liaison (synthesis OneToOne, row_index). Toutes les vues,
# `consolidate` compris depuis le 2026-10-16 (le consolidate local est retiré).
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

from .services import batch_link_extra  # noqa: E402

_qm = make_queue_manipulation_views(
    work_model=VoiceSynthesis, batch_model=BatchSynthesis,
    item_model=BatchSynthesisItem, fk_name='synthesis',
    get_user=lambda r: r.user if r.user.is_authenticated else get_or_create_anonymous_user(),
    # Le nom de sortie de la liaison, déclaré UNE fois (2026-10-16) : la fusion, le déplacement
    # et le regroupement à l'arrivée créaient des liaisons sans lui.
    item_extra=batch_link_extra,
)
remove_from_batch = _qm['remove_from_batch']
reorder           = _qm['reorder']
reorder_queue     = _qm['reorder_queue']
merge             = _qm['merge']
move_to_batch     = _qm['move_to_batch']
consolidate       = _qm['consolidate']