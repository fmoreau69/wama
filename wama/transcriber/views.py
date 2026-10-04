import os
import io
import json
import re
import logging
import zipfile
import shutil
import platform
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest, HttpResponse
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.core.cache import cache
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.utils.http import content_disposition_header

import datetime
from .models import Transcript, BatchTranscript, BatchTranscriptItem
from .utils.speakers import normalize_speaker_label, normalize_segments_speakers, unique_speakers, display_speaker
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.input_match import input_labels as _input_labels
from wama.accounts.permissions import app_access
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.queue_duplication import duplicate_instance, release_card_files
from wama.common.utils.scoping import visible_or_404

logger = logging.getLogger(__name__)


# Sonde média + formatage durée : brique commune (extraction A5-18, 2026-07-06).
from wama.common.utils.media_probe import format_duration as _format_duration


def _describe_audio(transcript: Transcript) -> None:
    """Renseigne durée/propriétés du média sur le Transcript (sonde commune media_probe)."""
    from wama.common.utils.media_probe import probe_audio
    info = probe_audio(transcript.audio.path)
    if not info:
        return
    transcript.duration_seconds = info['duration']
    transcript.duration_display = info['duration_display']
    transcript.properties = info['properties']
    transcript.save(update_fields=['duration_seconds', 'duration_display', 'properties'])


def _reset_for_relaunch(t):
    """Remise à zéro avant (re)lancement — appliquée SOUS le verrou anti-race
    (begin_processing). Reset UNIQUE pour start / start_all / batch_start
    (avant 2026-07-06 : 3 copies divergentes, batch_start ne purgeait rien).

    ⚠ Depuis le 2026-10-03 la card porte un PIPELINE (`function_specs.PIPELINE`) : un lancement
    ne rejoue que ce qui n'est plus à jour. Le résultat d'un process s'efface donc QUAND CE
    PROCESS EST REJOUÉ (dans sa glu, `workers._transcribe_step` ou `_import_step`), plus ici —
    sinon changer le type de résumé effacerait la transcription qu'on voulait justement garder.
    Une card à RÉSULTAT EXISTANT joue le même pipeline (process `import`) ; ses segments ne sont
    jamais effacés avant le ré-import : ce sont les ANCRES horodatées sur lesquelles son texte se
    ré-ancre (`workers._anchor_words_for`)."""
    t.progress = 0


# ── Les SIX vues de lot : fabrique COMMUNE (`batch_views.make_batch_views`, portage 2026-09-23,
# 3ᵉ app réelle — ROUTE §11 #36). Spécificités du transcriber DÉCLARÉES en kwargs : la tâche
# se choisit PAR élément (`task_for` : avec ou sans pré-traitement), remise à zéro sous verrou
# (`_reset_for_relaunch` + cache de progression à 0), cache `transcriber_progress_<id>` lu par
# `batch_status` et purgé à la suppression avec les sorties TXT/SRT (`_cleanup_output_files`),
# libellé d'une ligne = nom du fichier ou queue de l'URL, remise à zéro COMPLÈTE à la
# duplication (texte, langue, segments, enrichissements). `batch_download` vient AUSSI de la
# fabrique depuis le 2026-10-02 : le format se choisit au téléchargement (`export_binding=
# 'late'`), la fabrique lit les formats DÉCLARÉS au catalogue et le rendu ENREGISTRÉ
# (`build_transcript_bytes`, `apps.py`) — la vue locale recopiait les deux en dur. Seule la
# souche de chaque entrée reste dite ici (`_zip_entry_stem`).
from wama.common.utils.batch_views import (DEFAULT_RESET, apply_item_settings, make_batch_views,
                                           read_settings_payload)
from wama.transcriber.params import PARAMS_JSON as _SCHEMA

#: Réglages d'un transcript écrits par la modale et le volet (schéma `params.py`) ; `temperature`
#: et `max_tokens` sont hors schéma depuis leur retrait des réglages, gardés pour un client qui
#: les posterait encore (JSON déjà typé).
SETTINGS_FIELDS = ('backend', 'hotwords', 'preprocess_audio', 'level_speech', 'vad_mode',
                   'language_mode',
                   'enable_diarization', 'diarization_model',
                   'generate_summary', 'summary_type', 'verify_coherence',
                   'temperature', 'max_tokens')

def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _task_for(t):
    """LA tâche d'un transcript — unique source pour la fabrique de lots, `start` et `start_all`
    (qui recopiaient chacun le choix pré-traitement, jusqu'au 2026-09-23). Une card qui porte un
    RÉSULTAT EXISTANT (port `work_result`) joue la MÊME tâche : c'est le pipeline qui retient le
    process `import` à la place de `transcribe` — et son réglage de pré-traitement n'est pas
    touché (aucun audio n'est écouté pour transcrire)."""
    from .workers import transcribe, transcribe_without_preprocessing
    return transcribe if (t.preprocess_audio or t.work_result) else transcribe_without_preprocessing


def _reset_and_clear_progress(t):
    _reset_for_relaunch(t)
    cache.set(f"transcriber_progress_{t.id}", 0, timeout=3600)


def _label_of(t):
    return t.filename if t.audio else ((t.source_url or '').split('/')[-1] or t.source_url)


def _zip_entry_stem(t):
    """Souche d'une transcription RENDUE dans un ZIP de lot : la souche commune de la sortie
    (`_output_stem`) pour un fichier, sinon la queue de l'URL ; l'extension vient du rendu."""
    if t.audio:
        return _output_stem(t)
    return os.path.splitext((t.source_url or '').split('/')[-1])[0] or f'transcript_{t.id}'


def _forget_transcript(t):
    _cleanup_output_files(t, t.user_id)
    cache.delete(f"transcriber_progress_{t.id}")


_bv = make_batch_views(
    work_model=Transcript, batch_model=BatchTranscript, get_user=_get_user,
    task_for=_task_for,
    output_fields=('segments_json', 'key_points', 'action_items', 'coherence_score'),
    params_fields=SETTINGS_FIELDS, schema=_SCHEMA,
    item_model=BatchTranscriptItem, fk_name='transcript',
    reset_on_start=_reset_and_clear_progress,
    reset_on_duplicate={**DEFAULT_RESET, 'language': '', 'text': '', 'used_backend': '',
                        'properties': '', 'duration_seconds': 0, 'duration_display': '',
                        'summary': '', 'coherence_notes': '', 'coherence_suggestion': ''},
    progress_of=lambda t: cache.get(f"transcriber_progress_{t.id}", t.progress or 0),
    item_label=_label_of,
    on_delete=_forget_transcript,
    output_name=_zip_entry_stem,
)
batch_start = _bv['batch_start']
batch_update_settings = _bv['batch_update']      # nom de vue de l'URLconf (`batch/<pk>/update/`)
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_download = _bv['batch_download']
batch_status = _bv['batch_status']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


def _wrap_transcript_in_batch(transcript):
    """Wrap a standalone Transcript in a new BatchTranscript-of-1 (brique commune)."""
    from wama.common.utils.batch_common import wrap_in_batch
    return wrap_in_batch(transcript, batch_model=BatchTranscript,
                         item_model=BatchTranscriptItem, fk_name='transcript')


# Manipulation directe de la file (CARD_DESIGN §3bis) — vues GÉNÉRÉES par la brique
# commune queue_manipulation (extraction 2026-07-06 ; transcriber était la seule impl).
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

_qm = make_queue_manipulation_views(
    work_model=Transcript, batch_model=BatchTranscript,
    item_model=BatchTranscriptItem, fk_name='transcript',
    get_user=lambda r: r.user if r.user.is_authenticated else get_or_create_anonymous_user(),
)
remove_from_batch = _qm['remove_from_batch']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
consolidate = _qm['consolidate']


def consolidate_transcripts_into_batches(ids, user):
    """Regroupe des Transcript importés ENSEMBLE en UN of-N — helper PUBLIC (filemanager)."""
    from wama.common.utils.batch_common import (
        consolidate_into_batch, delete_singleton_batches, load_in_import_order,
    )
    items = load_in_import_order(Transcript, ids, user)
    if len(items) < 2:
        return None
    return consolidate_into_batch(
        items,
        create_batch=lambda total: BatchTranscript.objects.create(user=user, total=total),
        link_item=lambda batch, t, idx: BatchTranscriptItem.objects.create(
            batch=batch, transcript=t, row_index=idx),
        unwrap_singletons=lambda i: delete_singleton_batches(
            BatchTranscript, 'transcript', user, i))


def _auto_wrap_orphans(user):
    """Range les Transcript pas encore en batch (appelé au chargement de page) —
    brique COMMUNE, stratégie par défaut (orphelin → batch-of-1). L'of-N ne se fait
    plus qu'à l'import GROUPÉ (cf. auto_wrap_orphans : l'ancien wrap_group indexé sur
    l'ACCUMULATION fusionnait des envois individuels espacés — constat Fabien 14/08).

    Staging supprimé (2026-06-29) : les DRAFT sont rendus dans la file comme cards
    BROUILLON (config via inspecteur, lancement via Lancer).
    """
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(user, work_model=Transcript, batch_model=BatchTranscript,
                      item_model=BatchTranscriptItem, fk_name='transcript')


def _input_match_meta():
    """Meta brique COMMUNE sur le DOMAINE du select (tâche `transcription`) : ses clés sont les
    clés de catalogue entières, donc les valeurs mêmes des options (route F4b ⑦, 2026-09-30 —
    elle était re-clée par nom de moteur tant que le select listait des moteurs) + pseudo-choix
    'auto' (intersection des requis)."""
    from wama.common.utils.input_match import auto_entry, input_match_meta
    meta = input_match_meta(task='transcription')
    if meta:
        meta['auto'] = auto_entry(meta)
    return meta


class IndexView(View):
    def get(self, request):
        from wama.common.utils.batch_common import without_heavy_fields
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Lazily wrap any orphan transcripts into a batch-of-1
        _auto_wrap_orphans(user)

        # Réconcilie les tâches RUNNING orphelines (worker mort/crash machine) — brique
        # COMMUNE. Un item RUNNING dont le worker propriétaire a redémarré sans elle est
        # un zombie (figé à son dernier %, anime un ETA fantôme → fausse impression de
        # traitement en cours). Il repasse en échec RELANÇABLE.
        # Un seul inspect() par chargement, uniquement s'il y a des RUNNING. Ne bascule
        # que sur PREUVE POSITIVE de mort — un worker muet (pool solo occupé par CETTE
        # tâche) ne conclut rien : ne touche JAMAIS une tâche vivante (cf. process_control).
        try:
            from wama.common.utils.process_control import reconcile_orphaned_running
            # Sans les segments (`without_heavy_fields`) : la réconciliation ne lit que statut et tâche.
            running = list(without_heavy_fields(Transcript.objects.filter(user=user, status='RUNNING')))
            n = reconcile_orphaned_running(running, error_field='error_message')
            if n:
                logger.info(f"[transcriber] {n} tâche(s) RUNNING orpheline(s) réconciliée(s) → échec relançable")
        except Exception as exc:
            logger.debug(f"[transcriber] reconcile_orphaned_running ignoré: {exc}")

        # Agrégats de file — brique COMMUNE (contrat toolbar) + enrichissements transcriber.
        from wama.common.utils.batch_common import build_batches_list

        def _extra(batch, items, transcripts):
            # Méta COMMUNES aux filles (affichées sur la card mère) : valeur si partagée, sinon None ("Mixte").
            def _common(attr):
                vals = {getattr(t, attr) for t in transcripts}
                return vals.pop() if len(vals) == 1 else None
            success_count = sum(1 for t in transcripts if t.status == 'SUCCESS')
            return {
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'common_backend': _common('backend'),
                'common_language': _common('language'),
                'common_diarization': _common('enable_diarization'),
                # ETA agrégée de la card mère (brique _batch_card.html)
                'eta_ids': ','.join(str(t.id) for t in transcripts),
            }

        batches_list = build_batches_list(user, batch_model=BatchTranscript,
                                          work_attr='transcript', order_by='-id',
                                          extra=_extra)

        # Chips générés — MÊME point d'attache que card_html, sinon la card du chargement
        # diverge de celle que l'endpoint renvoie ensuite (leçon describer).
        # Les lignes d'exécution de TOUTES les cards de la page en une requête (bande des process).
        from wama.common.services.process_pipeline import preload
        _shown = [_it.transcript for _b in batches_list for _it in _b['items']
                  if getattr(_it, 'transcript', None)]
        preload(_shown)
        for _t in _shown:
            _decorate_card(_t, preloaded=True)
        queue_count = sum(len(b['items']) for b in batches_list)

        # ── Tri + filtrage de la file — brique COMMUNE (extraite d'ici le 2026-07-03) ──
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _name(b):
            if b['obj'].total == 1 and b['items'] and b['items'][0].transcript:
                t = b['items'][0].transcript
                return (t.filename or t.title or '').lower()
            return f"batch {b['obj'].id:08d}"
        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list, name_of=_name)

        # Staging supprimé (2026-06-29) : les DRAFT apparaissent dans la file (via _auto_wrap_orphans)
        # comme cards BROUILLON — plus de zone « à valider » séparée.

        # Backfill duration for existing transcripts that were stored without it
        # Sans les champs LOURDS (segments) : ni ce rattrapage ni la barre de progression globale
        # ne les lisent — chargés ici, ils coûtaient une seconde fois 0,4 s par page (2026-10-02).
        all_transcripts = without_heavy_fields(Transcript.objects.filter(user=user))
        for t in all_transcripts:
            if not t.duration_display and t.audio:
                _describe_audio(t)

        # Valeurs du volet = réglages utilisateur, DÉRIVÉS du schéma (brique commune, même forme
        # que l'imager depuis le 2026-09-26) — plus de liste de champs écrite ici.
        import json
        from wama.transcriber.params import PARAMS_JSON
        panel_values = _user_panel_values(user)

        # Les modèles du select arrivent du CATALOGUE par la brique commune (WamaParams, source
        # `catalog`) — l'ancien endpoint `/transcriber/backends/` et son JS sont retirés (F4b ⑦).
        return render(request, 'transcriber/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'q_sort': q_sort,
            'q_filter': q_filter,
            'transcripts': all_transcripts,  # kept for global progress bar
            'params_json': json.dumps(PARAMS_JSON),
            'panel_values_json': json.dumps(panel_values),
            # Appariement entrée↔modèles (brique commune input_match) : meta sur les clés de
            # catalogue, les valeurs mêmes du select ; 'auto' = intersection des requis.
            'input_match_meta': json.dumps(_input_match_meta()),
            'input_labels': json.dumps(_input_labels()),
        })


@require_POST
@app_access('transcriber')
def upload(request):
    # Un fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique commune `received_inputs`
    # (2026-09-28) : une désignation arrive par cette même vue, avec le même état du volet, et
    # se POINTE au lieu d'être recopiée.
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'transcriber')
    if not received:
        return JsonResponse({'error': received.refusal or 'Aucun fichier reçu'}, status=400)
    file = received[0]
    from wama.common.app_registry import accepts_file
    if not accepts_file('transcriber', file.name):
        return JsonResponse({'error': f'Format non pris en charge : {os.path.splitext(file.name)[1] or file.name}'},
                            status=400)

    # L'état COMPLET du volet voyage avec le dépôt — lu PAR LE SCHÉMA (`schema_model_kwargs`,
    # comme le converter) et gardé comme préférence (comme l'imager) : un réglage ajouté à
    # `params.py` est pris ici sans toucher la vue.
    settings_values = _deposit_settings(user, request.POST)

    from ..common.utils.video_utils import is_video_file, extract_audio_from_video

    # Common transcript fields
    # status='DRAFT' → l'élément arrive en zone de staging (« à valider »), PAS
    # directement en file d'attente : l'utilisateur règle les paramètres puis
    # clique « Ajouter » / « Lancer ». Voir WAMA_APP_CONVENTIONS §8.X (staging).
    transcript_fields = {'user': user, 'status': 'DRAFT', **settings_values}

    # Vérifier si c'est une vidéo
    if is_video_file(file.name):
        try:
            # Sauvegarder temporairement la vidéo
            import tempfile
            from django.core.files.base import ContentFile

            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.name)[1]) as temp_video:
                for chunk in file.chunks():
                    temp_video.write(chunk)
                temp_video_path = temp_video.name

            # Extraire l'audio
            audio_path = extract_audio_from_video(temp_video_path)

            # Lire le fichier audio
            with open(audio_path, 'rb') as audio_file:
                audio_content = audio_file.read()

            # Créer un ContentFile pour Django
            audio_name = os.path.splitext(file.name)[0] + '_audio.wav'
            audio_django_file = ContentFile(audio_content, name=audio_name)

            # Créer le transcript avec l'audio extrait
            t = Transcript.objects.create(
                audio=audio_django_file,
                **transcript_fields
            )
            # L'audio EXTRAIT est un fichier neuf ; sa source reste la vidéo désignée.
            file.record(t, 'audio')

            # Nettoyer les fichiers temporaires
            try:
                os.remove(temp_video_path)
                os.remove(audio_path)
            except OSError:
                pass

        except Exception as e:
            return JsonResponse({
                'error': f'Erreur lors de l\'extraction audio de la vidéo: {str(e)}'
            }, status=500)
    else:
        # Fichier audio normal — téléversé, ou DÉSIGNÉ (le chemin : pointage).
        t = Transcript.objects.create(
            audio=file.value,
            **transcript_fields
        )
        file.record(t, 'audio')

    _describe_audio(t)
    # L'élément reste DRAFT (brouillon) ; il est enveloppé en batch par `_auto_wrap_orphans`
    # au rendu de la file (IndexView) et apparaît comme card BROUILLON. Staging supprimé (2026-06-29).
    return JsonResponse({
        'id': t.id,
        'audio_url': t.audio.url,
        'audio_label': os.path.basename(smart_str(t.audio.name)),
        'status': t.status,
        'staged': True,
        'properties': t.properties,
        'duration_display': t.duration_display,
        'preprocess_audio': t.preprocess_audio,
        'backend': t.backend,
        'hotwords': t.hotwords,
    })


@require_POST
def upload_youtube(request):
    """
    Télécharge l'audio depuis YouTube et crée une transcription.
    """
    youtube_url = request.POST.get('youtube_url', '').strip()
    if not youtube_url:
        return JsonResponse({
            'error': 'URL YouTube manquante'
        }, status=400)

    # Valider l'URL YouTube
    import re
    youtube_regex = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
    if not re.match(youtube_regex, youtube_url):
        return JsonResponse({
            'error': 'URL YouTube invalide'
        }, status=400)

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    settings_values = _deposit_settings(user, request.POST)

    try:
        from ..common.utils.video_utils import download_youtube_audio
        from django.core.files.base import ContentFile
        import tempfile

        # Créer un dossier temporaire pour le téléchargement
        temp_dir = tempfile.mkdtemp()

        # Télécharger l'audio
        audio_path, video_title = download_youtube_audio(youtube_url, temp_dir)

        # Lire le fichier audio
        with open(audio_path, 'rb') as audio_file:
            audio_content = audio_file.read()

        # Créer un ContentFile pour Django
        audio_name = f"{video_title[:100]}_youtube.wav"  # Limiter la longueur du nom
        audio_django_file = ContentFile(audio_content, name=audio_name)

        # Créer le transcript en STAGING (DRAFT) — comme l'upload de fichier :
        # l'élément arrive en zone « À valider », pas directement en file.
        t = Transcript.objects.create(
            user=user,
            audio=audio_django_file,
            status='DRAFT',
            **settings_values,
        )

        # Nettoyer le dossier temporaire
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass

        _describe_audio(t)
        # Pas de _wrap_transcript_in_batch : reste en staging jusqu'à validation.

        return JsonResponse({
            'id': t.id,
            'audio_url': t.audio.url,
            'audio_label': os.path.basename(smart_str(t.audio.name)),
            'status': t.status,
            'staged': True,
            'properties': t.properties,
            'duration_display': t.duration_display,
            'preprocess_audio': t.preprocess_audio,
            'video_title': video_title,
        })

    except Exception as e:
        return JsonResponse({
            'error': f'Erreur lors du téléchargement YouTube: {str(e)}'
        }, status=500)


@require_POST
def start(request, pk: int):
    """
    Démarre ou relance la transcription d'un fichier audio.
    Utilise les paramètres individuels du transcript (backend, preprocess_audio, etc.).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Anti-race (pattern AGENTS.md) : select_for_update + revoke — brique commune.
    from wama.common.utils.process_control import begin_processing
    t, err = begin_processing(Transcript, pk, user=user, reset=_reset_for_relaunch)
    if err == 'not_found':
        return JsonResponse({'error': 'Not found'}, status=404)
    if err == 'already_running':
        return JsonResponse({'error': 'Transcription déjà en cours'}, status=409)

    cache.set(f"transcriber_progress_{t.id}", 0, timeout=3600)

    task = _task_for(t).delay(t.id)

    t.task_id = task.id
    t.save(update_fields=['task_id'])

    return JsonResponse({
        'task_id': task.id,
        'status': 'RUNNING',
    })


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE. C'est aussi le résumé ou la
# cohérence « à la demande » sur une transcription déjà faite, ou REPRISE d'un document.
def _pipeline_model(t):
    from wama.transcriber.backends.manager import catalogue_value
    return catalogue_value(t.backend) or 'auto'


start_process = make_process_start_view(
    work_model=Transcript, task_for=_task_for, reset_on_start=_reset_and_clear_progress,
    model_key=_pipeline_model)


@require_POST
def stop(request, pk: int):
    """
    Stoppe la transcription en cours (révoque la tâche Celery) et remet l'item dans un état relançable
    (bouton de cycle ▶/⏹/↻). Brique commune : wama.common.utils.process_control.stop_instance.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)

    if t.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': t.id, 'status': t.status})  # rien à stopper

    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(t)   # → FAILURE (relançable), task_id vidé
    # Purge le cache de progression : sinon une valeur périmée (ex. 20 %) « colle » au prochain run/poll.
    from django.core.cache import cache
    cache.delete(f"transcriber_progress_{t.id}")
    cache.delete(f"transcriber_status_msg_{t.id}")
    return JsonResponse({'id': t.id, 'status': new_status})


# ---------------------------------------------------------------------------
# Staging (« à valider ») — DRAFT → file d'attente
# ---------------------------------------------------------------------------

# _apply_panel_settings SUPPRIMÉ 2026-09-26 : aucun appelant (mesuré, dépôt entier), et une
# 3ᵉ liste de champs du volet écrite à la main — le dépôt lit le schéma (`_deposit_settings`).

# _launch_transcript SUPPRIMÉ 2026-07-06 : code mort (aucun appelant) qui dupliquait le
# lancement sans anti-race — start/start_all/batch_start passent par begin_processing (commun).


# Staging (vues stage_commit/commit_all/clear/update_all) SUPPRIMÉ 2026-06-29 : les DRAFT sont des
# cards BROUILLON dans la file (config via inspecteur, lancement via la vue `start` qui gère DRAFT).


# ---------------------------------------------------------------------------
# Éditeur de correction manuelle (/edit/<id>/) — voir TRANSCRIBER_CORRECTION.md
# ---------------------------------------------------------------------------

def _backfill_speakers(target, source):
    """Reporte les locuteurs de `source` (ASR diarisé) vers `target` (version corrigée)
    PAR RECOUVREMENT TEMPOREL, uniquement si `target` n'a aucun locuteur et `source` en a.

    Cas typique : re-transcription diarisée alors qu'une correction antérieure (sans
    locuteurs, segmentation différente) existe → on restaure la diarisation sans perdre
    les corrections de texte. `source` est supposée triée par temps (segments ASR ordonnés).
    """
    if not target or not source:
        return target
    if any((s.get('speaker_id') or '').strip() for s in target):
        return target  # la correction a déjà des locuteurs → ne pas écraser
    src = [(float(s.get('start_time', 0) or 0), float(s.get('end_time', 0) or 0),
            (s.get('speaker_id') or '')) for s in source]
    if not any(spk for _, _, spk in src):
        return target  # l'ASR n'a pas de locuteurs non plus → rien à reporter
    for seg in target:
        st = float(seg.get('start_time', 0) or 0)
        en = float(seg.get('end_time', 0) or st)
        best_spk, best_ov = '', 0.0
        for a, b, spk in src:
            if a > en:
                break              # src triée → plus aucun recouvrement possible
            if b < st or not spk:
                continue
            ov = min(en, b) - max(st, a)
            if ov > best_ov:
                best_ov, best_spk = ov, spk
        if best_spk:
            seg['speaker_id'] = best_spk
    return target


def _editor_segments(t: Transcript):
    """Segments pour l'éditeur : version corrigée si dispo, sinon l'originale ASR.

    Les libellés de locuteurs sont normalisés vers la forme canonique « SPEAKER_NN »
    (les backends émettent « 0 » ou « SPEAKER_00 » selon le moteur — cf. utils/speakers).
    """
    from .utils.speakers import normalize_segments_speakers, normalize_speaker_label
    import copy
    if t.corrected_segments_json:
        segs = normalize_segments_speakers(copy.deepcopy(t.corrected_segments_json))
        # Si la correction n'a pas de locuteurs mais l'ASR brut en a → on les reporte.
        if t.segments_json:
            _backfill_speakers(segs, normalize_segments_speakers(copy.deepcopy(t.segments_json)))
        return segs
    if t.segments_json:
        return normalize_segments_speakers(copy.deepcopy(t.segments_json))
    return [
        {'speaker_id': normalize_speaker_label(s.speaker_id), 'start_time': s.start_time,
         'end_time': s.end_time, 'text': s.text, 'confidence': s.confidence}
        for s in t.segments.order_by('order')
    ]


def _rebuild_segments_from(t: Transcript, segs):
    """Reconstruit les lignes TranscriptSegment depuis les segments corrigés
    (pour que SRT/aperçus reflètent la correction). Appelé à la finalisation."""
    from .models import TranscriptSegment
    TranscriptSegment.objects.filter(transcript=t).delete()
    rows = []
    for i, s in enumerate(segs):
        rows.append(TranscriptSegment(
            transcript=t,
            speaker_id=s.get('speaker_id', '') or '',
            start_time=float(s.get('start_time', 0) or 0),
            end_time=float(s.get('end_time', 0) or 0),
            text=(s.get('text') or '').strip(),
            confidence=s.get('confidence'),
            order=i,
        ))
    if rows:
        TranscriptSegment.objects.bulk_create(rows)


def edit(request, pk: int):
    """Page éditeur de correction (forme d'onde + transcript synchronisé éditable)."""
    import json as _json
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    if t.status != 'SUCCESS':
        from django.contrib import messages
        messages.warning(request, "La correction n'est disponible qu'après une transcription réussie.")
        return redirect('transcriber:index')

    segments = _editor_segments(t)

    # Démarre le calcul de l'enveloppe de forme d'onde si pas encore fait (asynchrone).
    if t.waveform_status in ('none', 'failed') and t.audio:
        Transcript.objects.filter(pk=t.id).update(waveform_status='pending')
        try:
            from .workers import compute_waveform_peaks
            compute_waveform_peaks.delay(t.id)
        except Exception:
            pass

    # Génération ASR brute la plus récente (pour proposer de mettre à jour la
    # correction si l'utilisateur a relancé la transcription depuis sa correction).
    latest = t.segments_json or []
    has_newer = bool(t.corrected_segments_json and latest)
    return render(request, 'transcriber/edit.html', {
        'transcript': t,
        'audio_url': t.audio.url if t.audio else '',
        'segments_json': _json.dumps(segments, ensure_ascii=False),
        'latest_json': _json.dumps(latest, ensure_ascii=False),
        'is_corrected': bool(t.corrected_segments_json),
        'has_newer_generation': has_newer,
        'correction_status': t.correction_status,
        'speaker_map_json': _json.dumps(t.speaker_map or {}, ensure_ascii=False),
    })


def waveform_peaks(request, pk: int):
    """Renvoie l'enveloppe de forme d'onde (peaks) calculée en asynchrone.

    {"status": "ready", "duration": float, "peaks": [int...]} si prête,
    sinon {"status": "pending"|"failed"}. Lance le calcul si pas encore démarré.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    from .utils.waveform import read_peaks
    if t.waveform_status == 'ready':
        data = read_peaks(t)
        if data:
            return JsonResponse({'status': 'ready', 'duration': data.get('duration', 0),
                                 'peaks': data.get('peaks', [])})
        t.waveform_status = 'none'  # fichier disparu → recalcul
    if t.waveform_status in ('none', 'failed') and t.audio:
        Transcript.objects.filter(pk=pk).update(waveform_status='pending')
        try:
            from .workers import compute_waveform_peaks
            compute_waveform_peaks.delay(t.id)
        except Exception:
            pass
        return JsonResponse({'status': 'pending'})
    return JsonResponse({'status': t.waveform_status or 'none'})


@require_POST
def save_realtime(request):
    """Sauvegarde une transcription temps réel (bouton Speak) comme card de la file.

    L'audio enregistré au micro est sauvé dans input/, et le texte live devient le
    résultat provisoire (status SUCCESS). La card est re-transcriptible via le pipeline
    complet (bouton Démarrer/Re-transcrire). Homogène avec une transcription par fichier.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    audio = request.FILES.get('audio')
    text = (request.POST.get('text') or '').strip()
    language = request.POST.get('language', 'fr') or 'fr'
    if not audio:
        return JsonResponse({'error': 'Aucun audio reçu'}, status=400)

    import time as _time
    from django.utils import timezone
    t = Transcript(
        user=user,
        status='SUCCESS',
        is_realtime=True,
        used_backend='temps réel',
        text=text,
        language=language,
        enable_diarization=True,
        finished_at=timezone.now(),
    )
    ext = '.webm'
    name = audio.name or ''
    if '.' in name:
        ext = '.' + name.rsplit('.', 1)[-1]
    t.audio.save(f"realtime_{int(_time.time())}{ext}", audio, save=False)
    t.save()

    # Propriétés audio (codec/kHz/canaux) + durée, comme un import normal.
    try:
        _describe_audio(t)
    except Exception:
        pass
    _wrap_transcript_in_batch(t)  # apparaît comme une card simple dans la file
    return JsonResponse({'ok': True, 'id': t.id})


@require_POST
def suggest_speakers(request, pk: int):
    """Propose des noms d'intervenants via LLM (présentations dans l'audio).

    Renvoie {"suggestions": {"SPEAKER_00": "Nom", ...}} — l'utilisateur valide ensuite
    dans l'onglet Intervenants avant d'appliquer (rien n'est enregistré ici).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    segs = _editor_segments(t)  # libellés déjà normalisés (SPEAKER_NN)
    if not segs:
        return JsonResponse({'suggestions': {}})
    try:
        from wama.common.utils.llm_utils import suggest_speaker_names
        lang = 'fr' if (t.language or 'fr').lower().startswith('fr') else 'en'
        suggestions = suggest_speaker_names(segs, language=lang)
    except Exception as e:
        logger.warning(f"[Transcriber] suggest_speakers failed: {e}")
        suggestions = {}
    return JsonResponse({'suggestions': suggestions})


@require_POST
def save_meta(request, pk: int):
    """Enregistre l'avant-propos (titre, date) et le renommage des locuteurs (speaker_map).

    Corps JSON : {"title": "...", "meeting_date": "YYYY-MM-DD"|null, "speaker_map": {"SPEAKER_00": "Nom", ...}}
    Le speaker_map est appliqué à l'affichage et à l'export sans toucher les segments bruts.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    update_fields = []
    if 'title' in data:
        t.title = (data.get('title') or '')[:300]
        update_fields.append('title')
    if 'meeting_date' in data:
        md = data.get('meeting_date') or None
        if md:
            try:
                t.meeting_date = datetime.datetime.strptime(md, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                t.meeting_date = None
        else:
            t.meeting_date = None
        update_fields.append('meeting_date')
    if 'speaker_map' in data:
        sm = data.get('speaker_map') or {}
        # Normalise les clés (libellés canoniques) et ignore les noms vides.
        clean = {}
        if isinstance(sm, dict):
            for k, v in sm.items():
                name = (v or '').strip()
                if name:
                    clean[normalize_speaker_label(k)] = name
        t.speaker_map = clean or None
        update_fields.append('speaker_map')

    if update_fields:
        t.save(update_fields=update_fields)
    return JsonResponse({
        'ok': True,
        'title': t.title,
        'meeting_date': t.meeting_date.isoformat() if t.meeting_date else None,
        'speaker_map': t.speaker_map or {},
    })


@require_POST
def retime_segments(request, pk: int):
    """Outil « Bornes » de l'éditeur : déplace une jonction ou coupe une section, ENTRE deux mots.

    Le calcul est la brique commune (`word_anchoring.move_boundary` / `split_turn`) ; cette vue ne
    fournit que la RÉFÉRENCE — les mots de la sortie ASR (`segments_json`, immuable), sur lesquels
    le texte d'une section corrigée se réancre avant la coupe. Rien n'est écrit ici : l'éditeur
    remplace ses sections et son auto-save enregistre, comme pour toute autre modification.

    Corps : `{op: 'move'|'split', segments: [gauche, droite] | [section], time: secondes}`, ou
    `{op: 'replace', segments: [sections touchées], start, end, words, speaker_id}` — le geste des
    modes d'écriture : la plage retranscrite remplace ce qui s'y disait, ou remplit un blanc
    (`word_anchoring.replace_span`).
    """
    import json as _json
    from wama.common.services.word_anchoring import move_boundary, replace_span, split_turn
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    try:
        data = _json.loads(request.body or '{}')
        op, segs = data.get('op'), data.get('segments') or []
        if op == 'replace':
            start, end = float(data.get('start')), float(data.get('end'))
            words = [w for w in data.get('words') or [] if isinstance(w, dict)]
        else:
            at = float(data.get('time'))
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'reason': 'payload invalide'}, status=400)
    if not all(isinstance(s, dict) for s in segs):
        return JsonResponse({'ok': False, 'reason': 'payload invalide'}, status=400)
    reference = [w for s in (t.segments_json or []) if isinstance(s, dict)
                 for w in (s.get('words') or []) if isinstance(w, dict)]
    if op == 'replace':
        return JsonResponse({'ok': True, 'segments': replace_span(
            segs, start, end, words, reference,
            new_turn={'speaker_id': str(data.get('speaker_id') or '')})})
    if op == 'move' and len(segs) == 2:
        result = move_boundary(segs[0], segs[1], at, reference)
        refused = "la borne ne peut pas se poser là (chaque section garde au moins un mot)"
    elif op == 'split' and len(segs) == 1:
        result = split_turn(segs[0], at, reference)
        refused = "impossible de couper ici (il faut au moins un mot de chaque côté)"
    else:
        return JsonResponse({'ok': False, 'reason': 'opération inconnue'}, status=400)
    if result is None:
        return JsonResponse({'ok': False, 'reason': refused})
    return JsonResponse({'ok': True, 'segments': list(result)})


@require_POST
def write_cursor(request, pk: int):
    """Modes d'écriture de l'éditeur : pose le curseur (`{mode, t, wanted}`) que suit la boucle
    commune, et la lance si besoin. `{enabled: false}` l'arrête et oublie ce qui a été transcrit
    (un nouveau passage retranscrit). Rien n'est écrit sur la card."""
    import json as _json
    from wama.common.services.playhead_follow import post_cursor
    from .workers import WRITE_MODES, WRITE_TTL, live_write_task, write_channel
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    try:
        body = _json.loads(request.body or '{}')
    except ValueError:
        return JsonResponse({'ok': False, 'reason': 'payload invalide'}, status=400)
    channel = write_channel(t.pk)
    spawn = lambda: live_write_task.delay(t.pk)  # noqa: E731
    if not body.get('enabled', True):
        cache.delete(channel.key('done'))
        return JsonResponse({'ok': True, **post_cursor(channel, None, spawn)})
    mode = body.get('mode')
    try:
        at = max(0.0, float(body.get('t', 0.0)))
        wanted = [[float(a), float(b)] for a, b in (body.get('wanted') or [])[:50]]
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'reason': 'payload invalide'}, status=400)
    if mode not in WRITE_MODES:
        return JsonResponse({'ok': False, 'reason': 'mode inconnu'}, status=400)
    cache.touch(channel.key('results'), WRITE_TTL)
    return JsonResponse({'ok': True, **post_cursor(
        channel, {'mode': mode, 't': at, 'wanted': wanted}, spawn)})


def write_results(request, pk: int):
    """Résultats des modes d'écriture depuis l'index `since` (`since=-1` : seulement l'index
    courant — une page qui s'ouvre ne rejoue pas les résultats d'une session précédente)."""
    from .workers import write_channel
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    channel = write_channel(t.pk)
    results = cache.get(channel.key('results')) or []
    try:
        since = int(request.GET.get('since', -1))
    except ValueError:
        since = -1
    return JsonResponse({'next': len(results), 'running': channel.is_running(),
                         'results': results[since:] if since >= 0 else []})


@require_POST
def save_correction(request, pk: int):
    """Auto-save de la correction (segments corrigés). status: draft | done."""
    import json as _json
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)
    try:
        data = _json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'payload invalide'}, status=400)

    segs = data.get('segments') or []
    status = data.get('status', 'draft')
    status = status if status in ('draft', 'done') else 'draft'

    t.corrected_segments_json = segs
    t.correction_status = status
    # Le texte de travail (téléchargements TXT) reflète la correction.
    t.text = ' '.join((s.get('text') or '').strip() for s in segs).strip()
    t.save(update_fields=['corrected_segments_json', 'correction_status', 'text'])

    # À la finalisation, on reconstruit les lignes de segments (SRT/aperçus cohérents).
    if status == 'done':
        _rebuild_segments_from(t, segs)
        # ── Signal d'exécution (RunOutcome, §16.7) ────────────────────────────────────────
        # LE gisement le plus riche de WAMA : `segments_json` (sortie ASR) et `segs` (version
        # humaine) forment une paire sortie→vérité, c'est-à-dire la SEULE vérité terrain du
        # dépôt. Elle était produite puis jetée à chaque correction.
        # Uniquement à la FINALISATION : `save_correction` est aussi un auto-save de brouillon,
        # et journaliser chaque frappe noierait le signal sous des états intermédiaires.
        # On enregistre l'AMPLEUR, pas un verdict : une transcription très corrigée peut l'avoir
        # été pour du style. C'est l'agrégation qui interprétera, avec le nombre pour elle.
        try:
            from wama.common.services.run_outcome import (
                correction_magnitude, is_real_correction, record,
            )
            mesure = correction_magnitude(t.segments_json, segs)
            # ⚠ Seulement si quelque chose a VRAIMENT changé : l'éditeur enregistre une
            # « correction » même quand l'utilisateur n'a rien touché (3 des 6 transcripts
            # corrigés du dépôt portent un texte identique à l'ASR). Sans ce garde-fou, le
            # signal le plus précieux se remplirait de non-événements.
            if is_real_correction(mesure):
                # La clé posée par le worker (`model_key`), à défaut le MOTEUR réellement
                # utilisé. Jusqu'au 2026-09-23 on cherchait `model_used`/`asr_model`/`model_name`
                # — trois champs qui n'ont jamais existé — puis `backend`, le RÉGLAGE, qui vaut
                # souvent « auto » : le signal était attribué à `transcriber:auto`.
                produced_by = t.model_key or (f'transcriber:{t.used_backend}'
                                              if t.used_backend else '')
                record('transcriber', t, 'corrige',
                       model_keys=[produced_by] if produced_by else None, detail=mesure)
        except Exception:
            pass

    return JsonResponse({'status': 'saved', 'correction_status': t.correction_status})


def _decorate_card(t, preloaded=False):
    """Attache les chips GÉNÉRÉS d'un transcript (CARD_DESIGN §11.4).

    Portage au commun : la card listait ses réglages à la main (une ligne + une condition par
    réglage). Ils viennent désormais du SCHÉMA (`transcriber/params.py`, chip=True) via la
    brique commune — même source pour tous les designs de card, donc aucune divergence possible.
    Le schéma existait déjà : ce portage n'a ajouté aucun mécanisme, seulement des déclarations.

    Deux spécificités du transcriber, conservées (rien ne devait être perdu) :
      • le chip montre le modèle EFFECTIF — la clé de catalogue que le worker a enregistrée
        (`model_key`, route F4b ⑦ : libellé du catalogue), pas le réglage demandé ;
      • si le modèle demandé n'a pas tourné, le repli est signalé par le variant du chip et
        son title.
    """
    from wama.common.utils.card_chips import chips_by_section
    from wama.transcriber.params import PARAMS_JSON

    # `values=` (brique, 31/08) : le modèle EFFECTIF prime sur le réglage.
    t.chips = chips_by_section(t, PARAMS_JSON, values={'backend': t.model_key or t.backend})

    asked = t.backend and t.backend != 'auto'
    fallback = bool(t.model_key and asked and t.model_key != t.backend)
    for chip in t.chips.get('settings', []):
        if chip.get('icon') == 'fa-microchip':
            if fallback:
                chip['variant'] = 'warn'
                chip['title'] = f"Demandé : {t.backend} — a tourné : {t.model_key}"
            elif not asked:
                # Tant qu'aucun modèle n'a tourné, « auto » (le libellé complet du choix est trop
                # long pour la colonne) ; une fois le run fait, le modèle RETENU.
                chip['label'] = f"{chip.get('label')} (auto)" if t.model_key else 'auto'
            break
    _pipeline_view(t, preloaded=preloaded)
    return t


def _pipeline_view(t, preloaded=False):
    """Les PROCESS de la card et son état MONTRÉ (`ROUTE §10.6` 5.1) — par la brique commune
    (`process_pipeline.decorate`). Une card à RÉSULTAT EXISTANT montre « Import » à la place de
    « Transcription ». Le modèle est passé tel que la card le demande, « auto » compris : les
    process se montrent AVANT le premier lancement — c'est là que leurs cases à cocher servent."""
    from wama.common.services.process_pipeline import decorate
    from wama.transcriber.backends.manager import catalogue_value
    from . import function_specs  # noqa: F401 — c'est cet import qui INSCRIT le pipeline de l'app
    return decorate(t, catalogue_value(t.backend) or 'auto', preloaded=preloaded)


def card_html(request, pk: int):
    """Card RENDUE serveur — source UNIQUE du markup (partial _transcript_card.html ;
    CARD_DESIGN « partial server-side + update JS en place, PAS de rebuild », audit A2-9/10).
    Consommée par refreshCard() côté JS aux transitions d'état (start/échec)."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = visible_or_404(Transcript, user, pk=pk)   # LECTURE : le sien OU reçu (2026-10-02)
    from wama.common.utils.batch_common import is_batch_child
    _decorate_card(t)
    html = render_to_string('transcriber/_transcript_card.html',
                            {'elem': t, 'in_batch': is_batch_child(t)}, request=request)
    return HttpResponse(html)


def _eta_triplet(t):
    """Le triplet d'ETA, celui que le worker apprend (`workers.transcriber_eta_key_size`) —
    chargement mesuré à part, modèle réputé NON chargé."""
    from .workers import transcriber_eta_key_size
    triplet = transcriber_eta_key_size(t)
    return (*triplet, False) if triplet else None


def _pipeline_model(t):
    """Le modèle passé à la bande des process — celui que la card demande, « auto » compris
    (`_pipeline_view`)."""
    from wama.transcriber.backends.manager import catalogue_value
    return catalogue_value(t.backend) or 'auto'


def _progress_extra(t):
    """Les clés PROPRES que le JS du transcriber lit : texte partiel et action en cours pendant le
    traitement, propriétés du fichier, puis le résultat et ses enrichissements."""
    from wama.common.utils.preview_utils import get_partial_text
    data = {
        'partial_text': get_partial_text('transcriber', t.id),
        'status_message': cache.get(f"transcriber_status_msg_{t.id}", ''),
        'properties': t.properties,          # codec • kHz • canaux → MAJ de la ligne de card
        'duration_display': t.duration_display,
    }
    if t.status == 'SUCCESS':
        data.update({
            'processing_seconds': t.processing_seconds or 0,
            'processing_display': t.processing_display,
            'text': t.text or '',
            'summary': t.summary or '',
            'summary_type': t.summary_type or 'structured',
            'key_points': t.key_points or [],
            'action_items': t.action_items or [],
            'coherence_score': t.coherence_score,
            'coherence_notes': t.coherence_notes or '',
            'coherence_suggestion': t.coherence_suggestion or '',
        })
    return data


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que son triplet d'ETA, ses clés propres et le modèle de sa bande
# de process.
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=Transcript, app_id='transcriber', eta_for=_eta_triplet,
                          extra=_progress_extra, pipeline_model=_pipeline_model)
progress, global_progress = _pv['progress'], _pv['global_progress']


def _output_stem(t: Transcript) -> str:
    """Souche du nom de sortie — BRIQUE COMMUNE (`compose_output_name`), portée le 2026-09-11.

    Le transcriber composait `{souche}_{backend}` à la main. La convention commune existe
    depuis le 2026-08-25 et il ne l'avait jamais adoptée : mesuré ce jour, **6 apps sur 10**
    l'utilisaient, et les 4 restantes — anonymizer, describer, reader, transcriber — chacune
    la sienne. Aucun critère de grille ne le mesurait, d'où quinze jours d'invisibilité.

    Ce que l'adoption apporte ici, et que Fabien a nommé : le nom porte le PROCESS **et** le
    MODÈLE, *« ce qui permettra aussi la comparaison des résultats / benchmark interne de
    différents modèles »*. Plus l'identifiant de card, qui garantit l'unicité quand deux
    transcriptions du même fichier coexistent.

    ⚠ Aucun fichier n'est renommé sur le disque : le transcriber ne STOCKE pas de sortie, il
    la génère au téléchargement. Le changement porte sur le nom proposé à l'utilisateur.

    ⚠ On rend une SOUCHE, sans extension : le transcriber est la seule app à produire le même
    résultat en quatre formats (txt/srt/pdf/docx), et ce sont les appelants qui ajoutent
    l'extension. La brique, elle, rend toujours un nom COMPLET — elle la déduit de la source.
    On la retire donc ici, explicitement, plutôt que d'amputer la source avant l'appel : un
    `entretien.v2.m4a` y perdrait son `.v2`.
    """

    from wama.common.utils.output_naming import compose_output_name
    nom = compose_output_name(app='transcriber', model=t.used_backend or '',
                              source_name=t.filename, item_id=t.id)
    return os.path.splitext(nom)[0]


def _srt_ts(s):
    """Seconds → SRT timestamp HH:MM:SS,mmm."""
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def build_transcript_bytes(t: Transcript, fmt: str):
    """Return (ext, bytes) for a transcript in `fmt` (txt/srt/pdf/docx), or None.

    Shared by single download and batch ZIP so format options stay in sync.
    """
    fmt = (fmt or 'txt').lower()
    if not t.text:
        return None
    if fmt == 'srt':
        from .models import TranscriptSegment
        segments = TranscriptSegment.objects.filter(transcript=t).order_by('order')
        srt_lines = []
        if segments.exists():
            for i, seg in enumerate(segments, 1):
                speaker = f'[{display_speaker(seg.speaker_id, t.speaker_map)}] ' if seg.speaker_id else ''
                srt_lines += [str(i), f"{_srt_ts(seg.start_time)} --> {_srt_ts(seg.end_time)}",
                              speaker + seg.text, '']
        else:
            srt_lines = ['1', '00:00:00,000 --> 99:59:59,000', t.text, '']
        return ('srt', '\n'.join(srt_lines).encode('utf-8'))
    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_transcript_pdf
            return ('pdf', generate_transcript_pdf(t))
        except Exception as e:
            logger.warning(f"[Transcriber] PDF skipped for {t.id}: {e}")
            return None
    if fmt == 'txt':
        try:
            from wama.common.utils.document_export import generate_transcript_txt
            return ('txt', generate_transcript_txt(t))
        except Exception:
            return ('txt', (t.text or '').encode('utf-8'))
    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_transcript_docx
            return ('docx', generate_transcript_docx(t))
        except Exception as e:
            logger.warning(f"[Transcriber] DOCX skipped for {t.id}: {e}")
            return None
    return ('txt', t.text.encode('utf-8'))


def download(request, pk: int):
    """Download transcript in requested format: txt (default), srt, pdf, docx."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # LECTURE → accès nommé : un transcript PARTAGÉ est téléchargeable, pas modifiable
    # (PROFILES_PERMISSIONS §7).
    t = visible_or_404(Transcript, user, pk=pk)
    if not t.text:
        return HttpResponseBadRequest('No transcript yet')

    fmt = request.GET.get('format', 'txt').lower()
    stem = _output_stem(t)

    if fmt == 'srt':
        # Delegate to existing SRT logic (preserving download_srt for backward compat)
        from wama.common.utils.media_paths import get_app_media_path
        disk_path = get_app_media_path('transcriber', user.id, 'output') / f"{stem}.srt"
        if disk_path.exists():
            return FileResponse(open(disk_path, 'rb'), as_attachment=True,
                                filename=f"{stem}.srt", content_type='text/plain; charset=utf-8')
        # Generate on the fly from segments
        from .models import TranscriptSegment
        segments = TranscriptSegment.objects.filter(transcript=t).order_by('order')
        srt_lines = []
        if segments.exists():
            for i, seg in enumerate(segments, 1):
                def _srt_ts(s):
                    h, rem = divmod(int(s), 3600)
                    m, sec = divmod(rem, 60)
                    ms = int((s - int(s)) * 1000)
                    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
                speaker = f'[{display_speaker(seg.speaker_id, t.speaker_map)}] ' if seg.speaker_id else ''
                srt_lines += [str(i), f"{_srt_ts(seg.start_time)} --> {_srt_ts(seg.end_time)}", speaker + seg.text, '']
        else:
            srt_lines = ['1', '00:00:00,000 --> 99:59:59,000', t.text, '']
        buf = io.BytesIO('\n'.join(srt_lines).encode('utf-8'))
        buf.seek(0)
        return FileResponse(buf, as_attachment=True, filename=f"{stem}.srt",
                            content_type='text/plain; charset=utf-8')

    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_transcript_pdf
            pdf_bytes = generate_transcript_pdf(t)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = content_disposition_header(True, f"{stem}.pdf")
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Transcriber] PDF generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur PDF : {e}')

    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_transcript_docx
            docx_bytes = generate_transcript_docx(t)
            response = HttpResponse(
                docx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            response['Content-Disposition'] = content_disposition_header(True, f"{stem}.docx")
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Transcriber] DOCX generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur DOCX : {e}')

    # Default: txt mis en forme (avant-propos titre/date/intervenants + compactage par locuteur)
    try:
        from wama.common.utils.document_export import generate_transcript_txt
        txt_bytes = generate_transcript_txt(t)
    except Exception as e:
        logger.warning(f"[Transcriber] TXT formaté indisponible ({e}), repli sur texte brut")
        txt_bytes = (t.text or '').encode('utf-8')
    buf = io.BytesIO(txt_bytes)
    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename=f"{stem}.txt",
                        content_type='text/plain; charset=utf-8')


def _cleanup_output_files(t: Transcript, user_id: int) -> None:
    """Remove output TXT/SRT files for a transcript."""
    if t.used_backend:
        try:
            from wama.common.utils.media_paths import get_app_media_path
            output_dir = get_app_media_path('transcriber', user_id, 'output')
            stem = _output_stem(t)
            for ext in ('.txt', '.srt'):
                path = output_dir / f"{stem}{ext}"
                if path.exists():
                    path.unlink()
        except Exception:
            pass


@require_POST
def enrich(request, pk: int):
    """Lance l'enrichissement LLM (résumé, points clés, actions) sur un transcript déjà transcrit."""
    import json
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)

    if not t.text:
        return JsonResponse({'error': 'Pas de texte transcrit'}, status=400)

    try:
        data = json.loads(request.body)
    except Exception:
        data = {}
    summary_type = data.get('summary_type', t.summary_type or 'structured')

    from .workers import enrich_transcript
    task = enrich_transcript.delay(t.id, summary_type)
    return JsonResponse({'ok': True, 'task_id': task.id, 'summary_type': summary_type})


@require_POST
def delete(request, pk: int):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    t = get_object_or_404(Transcript, pk=pk, user=user)
    # Lot de l'élément, relevé AVANT la suppression — brique commune (`batch_common`).
    from wama.common.utils.batch_common import batch_snapshot, batch_state
    snapshot = batch_snapshot(t)
    # Output files are unique to this transcript — always delete
    _cleanup_output_files(t, user.id)
    # Files may be shared (duplicate, batch reference) — only deleted when no other row holds them
    release_card_files(t)
    t.delete()  # signal post_delete (batch_sync) : recale total / supprime le batch vidé
    cache.delete(f"transcriber_progress_{pk}")
    return JsonResponse({'deleted': pk, 'batch': batch_state(snapshot, Transcript)})


@require_POST
def duplicate(request, pk: int):
    """Duplicate a Transcript sharing the same audio file, resetting all results."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import duplicable_or_404
    t = duplicable_or_404(Transcript, user, pk=pk)
    new_t = duplicate_instance(
        t,
        for_user=user,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'properties': '',
            'language': '',
            'text': '',
            'used_backend': '',
            'summary': '',
            'coherence_notes': '',
            'coherence_suggestion': '',
        },
        clear_fields=['segments_json', 'key_points', 'action_items', 'coherence_score'],
    )
    # Élément d'un VRAI batch (>1) → la copie reste dans ce batch (élément frère).
    # Élément autonome (batch-of-1) → la copie est un AUTRE élément autonome
    # (pas de regroupement surprise en batch-de-2).
    orig_item = BatchTranscriptItem.objects.filter(transcript=t).select_related('batch').first()
    if orig_item and orig_item.batch.total > 1:
        from django.db.models import Max
        batch = orig_item.batch
        next_idx = (batch.items.aggregate(m=Max('row_index'))['m'] or 0) + 1
        BatchTranscriptItem.objects.create(batch=batch, transcript=new_t, row_index=next_idx)
        batch.total = batch.items.count()
        batch.save(update_fields=['total'])
    else:
        _wrap_transcript_in_batch(new_t)
    return JsonResponse({'duplicated': new_t.id})


def console_content(request):
    """Retourne un flux textuel des logs en cours pour affichage console (via Redis/Cache + logs Celery)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})


@require_POST
def start_all(request):
    """
    Démarre toutes les transcriptions non terminées.
    Respecte les paramètres individuels de chaque transcript (la tâche : `_task_for`).
    """
    from wama.common.utils.process_control import begin_processing

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    qs = Transcript.objects.filter(user=user).exclude(status='SUCCESS')
    started = []
    for t in qs:
        # Anti-race par item (brique commune) : skip si déjà RUNNING/supprimé entre-temps.
        t, err = begin_processing(Transcript, t.pk, user=user, reset=_reset_for_relaunch)
        if err:
            continue
        cache.set(f"transcriber_progress_{t.id}", 0, timeout=3600)

        task = _task_for(t).delay(t.id)

        t.task_id = task.id
        t.save(update_fields=['task_id'])
        started.append(t.id)

    return JsonResponse({
        'started_ids': started,
        'count': len(started),
    })


@require_POST
def clear_all(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    transcripts = Transcript.objects.filter(user=user)
    cleared = []
    for transcript in transcripts:
        cleared.append(transcript.id)
        _cleanup_output_files(transcript, user.id)
        # Les fichiers peuvent être PARTAGÉS (dupliqué / import filemanager / référence d'un lot) :
        # même règle que delete() (avant 2026-07-06 : unlink inconditionnel → cassait les doublons).
        release_card_files(transcript)
        cache.delete(f"transcriber_progress_{transcript.id}")
        transcript.delete()  # signal post_delete (batch_sync) : recale total / purge le batch vidé
    return JsonResponse({'cleared_ids': cleared, 'count': len(cleared)})


def download_all(request):
    """Download all ready transcripts as a ZIP in the requested format (txt/srt/pdf/docx)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    transcripts = Transcript.objects.filter(user=user).exclude(text='')
    if not transcripts.exists():
        return HttpResponseBadRequest('No transcripts ready')
    fmt = request.GET.get('format', 'txt').lower()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for transcript in transcripts:
            stem = _output_stem(transcript)
            try:
                result = build_transcript_bytes(transcript, fmt)
            except Exception as e:
                logger.warning(f"[Transcriber] download_all: {fmt} failed for #{transcript.pk} ({e}); falling back to txt")
                result = None
            if result:
                ext, data = result
            else:
                ext, data = 'txt', (transcript.text or '').encode('utf-8')
            archive.writestr(f"{stem}.{ext}", data)
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f"transcripts_{fmt}.zip")


# =============================================================================
# BATCH VIEWS
# =============================================================================

def batch_template(request):
    """Template batch téléchargeable, GÉNÉRÉ depuis la déclaration des champs
    (brique commune build_batch_template — plus de contenu en dur, A5-23)."""
    from django.http import HttpResponse
    from wama.common.utils.batch_parsers import build_batch_template
    text = build_batch_template(
        ['fichier'],
        {'fichier': 'https://example.com/audio.mp3'},
        app_label='Transcriber (une URL ou chemin audio/vidéo par ligne)')
    response = HttpResponse(text, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_transcriber_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchTranscript + Transcript entries.
    Returns batch_id and list of transcript IDs.
    Files are not downloaded yet — download happens when each task starts.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    backend = request.POST.get('backend', 'auto')
    hotwords = request.POST.get('hotwords', '')
    preprocess_audio = str(request.POST.get('preprocess_audio', '')).lower() in ('1', 'true', 'on')

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
    batch = BatchTranscript.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        # Create a Transcript with source_url, no audio file yet
        t = Transcript.objects.create(
            user=user,
            source_url=url_or_path,
            audio='',  # empty — will be populated when task downloads the file
            backend=backend,
            hotwords=hotwords,
            preprocess_audio=preprocess_audio,
        )
        BatchTranscriptItem.objects.create(batch=batch, transcript=t, row_index=i)
        created_ids.append(t.id)

    return JsonResponse({
        'batch_id': batch.id,
        'transcript_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List the current user's batches with status counts."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batches = BatchTranscript.objects.filter(user=user).prefetch_related('items__transcript')

    from wama.common.utils.batch_common import batch_elements
    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for t in batch_elements(batch, Transcript):     # lit le cache du prefetch, 0 requête
            k = t.status.lower()
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


@require_POST
def set_preprocessing_preference(request):
    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            payload = {}
    enabled = payload.get('enabled')
    if enabled is None:
        enabled = str(request.POST.get('enabled', '')).lower() in ('1', 'true', 'on')
    else:
        enabled = bool(enabled)
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.user_settings import save_user_app_settings
    save_user_app_settings(user, 'transcriber', {'preprocessing_enabled': enabled})
    return JsonResponse({'enabled': enabled})


# toggle_preprocessing / preprocessing_status SUPPRIMÉES 2026-07-06 (A5-22) : routes mortes
# (seul set_preprocessing est câblé, index.html:81) aux défauts DIVERGENTS (timeout=None,
# défaut True vs décision projet OFF). Réglage servi par get_user_transcriber_settings.



# =============================================================================
# NEW: VibeVoice-related views
# =============================================================================

# `get_backends` (liste de MOTEURS servie à `loadBackendsAsync`) est RETIRÉ le 2026-09-30 (route
# F4b ⑦) : les options du select viennent du catalogue par l'endpoint commun
# (`model_manager.api_model_options`, source `catalog` de WamaParams). Registre : REMOVAL_LEDGER.

def get_segments(request, pk: int):
    """
    Get transcript segments with speaker and timestamp info.

    Returns:
        JSON with segments array containing speaker_id, start_time, end_time, text.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)

    # Try to get segments from database first
    from .models import TranscriptSegment
    segments = TranscriptSegment.objects.filter(transcript=t).order_by('order')

    if segments.exists():
        segments_data = [
            {
                'id': seg.id,
                'speaker_id': seg.speaker_id,
                'start_time': seg.start_time,
                'end_time': seg.end_time,
                'text': seg.text,
                'confidence': seg.confidence,
                'time_range': seg.format_time_range(),
            }
            for seg in segments
        ]
    elif t.segments_json:
        # Fallback to JSON backup
        segments_data = t.segments_json
    else:
        segments_data = []

    # Get unique speakers
    speakers = list(set(s.get('speaker_id', '') for s in segments_data if s.get('speaker_id')))

    return JsonResponse({
        'id': t.id,
        'has_segments': len(segments_data) > 0,
        'segment_count': len(segments_data),
        'speaker_count': len(speakers),
        'speakers': speakers,
        'segments': segments_data,
        'backend': t.used_backend,
    })


def download_srt(request, pk: int):
    """
    Download transcript as SRT subtitle file.

    Returns:
        SRT file with speaker labels and timestamps.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import visible_or_404
    t = visible_or_404(Transcript, user, pk=pk)

    stem = _output_stem(t)

    # Serve saved file from disk if it exists
    from wama.common.utils.media_paths import get_app_media_path
    disk_path = get_app_media_path('transcriber', user.id, 'output') / f"{stem}.srt"
    if disk_path.exists():
        return FileResponse(
            open(disk_path, 'rb'),
            as_attachment=True,
            filename=f"{stem}.srt",
            content_type='text/plain; charset=utf-8'
        )

    # Fallback: generate on the fly
    from .models import TranscriptSegment

    segments = TranscriptSegment.objects.filter(transcript=t).order_by('order')

    if not segments.exists():
        if not t.text:
            return HttpResponseBadRequest('No transcript content')
        srt_content = f"1\n00:00:00,000 --> 00:00:00,000\n{t.text}\n\n"
    else:
        srt_content = ""
        for i, seg in enumerate(segments, 1):
            srt_content += seg.to_srt_entry(i)

    buffer = io.BytesIO(srt_content.encode('utf-8'))
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{stem}.srt",
        content_type='text/plain; charset=utf-8'
    )


@require_POST
def update_settings(request, pk: int):
    """Réglages d'UN transcript — même lecture (coercition par le schéma) et même affectation
    que `batch_update_settings` de la fabrique : `read_settings_payload` + `apply_item_settings`.
    L'ancien `_apply_transcript_settings` typait à la main (`bool`, `float`, `int`) ce que le
    schéma déclare. Corps JSON attendu : backend, hotwords, enable_diarization, preprocess_audio,
    generate_summary, summary_type, verify_coherence (clés absentes = inchangées)."""
    user = _get_user(request)
    from wama.common.utils.scoping import editable_or_404
    t = editable_or_404(Transcript, user, pk=pk)

    data = read_settings_payload(request, _SCHEMA, SETTINGS_FIELDS)
    touched = apply_item_settings(t, data, params_fields=SETTINGS_FIELDS)
    if touched:
        t.save(update_fields=touched)

    return JsonResponse({
        'id': t.id,
        'backend': t.backend,
        'hotwords': t.hotwords,
        'enable_diarization': t.enable_diarization,
        'diarization_model': t.diarization_model,
        'temperature': t.temperature,
        'max_tokens': t.max_tokens,
        'preprocess_audio': t.preprocess_audio,
        'level_speech': t.level_speech,
        'vad_mode': t.vad_mode,
        'language_mode': t.language_mode,
        'generate_summary': t.generate_summary,
        'summary_type': t.summary_type,
        'verify_coherence': t.verify_coherence,
    })


# ── Réglages UTILISATEUR du volet — DÉRIVÉS du schéma (2026-09-26) ────────────────────────
# Ici vivaient trois listes écrites à la main (défauts, noms JSON acceptés, correspondance
# nom↔clé) plus une quatrième dans la page et une cinquième dans l'upload : un réglage ajouté à
# `params.py` n'était lu par AUCUNE (le filtre de parole n'apparaissait donc que dans la
# modale). La clé de stockage est déclarée dans `params.py` (`user_setting_key`) ; lire, garder
# et les deux routes JSON sont la brique COMMUNE `user_settings` (2026-09-27, partagée avec
# l'anonymizer — ces fonctions étaient recopiées d'une app à l'autre).
from wama.transcriber.params import user_setting_key  # noqa: E402
from wama.common.utils.user_settings import (  # noqa: E402
    make_panel_settings_views, read_panel_settings, save_panel_settings,
)

get_user_transcriber_settings, save_user_transcriber_settings = make_panel_settings_views(
    'transcriber', _SCHEMA, key=user_setting_key)


def _user_panel_values(user):
    """Les réglages utilisateur, par NOM de param — ce que le volet rend et ce que l'API sert.
    Le modèle est lu dans l'ESPACE DES CLÉS (route F4b ⑦) : une préférence gardée avant le
    2026-09-30 porte un nom de moteur (`whisper`), que le select ne propose plus."""
    from wama.transcriber.backends.manager import catalogue_value
    values = read_panel_settings(user, 'transcriber', _SCHEMA, key=user_setting_key)
    if 'backend' in values:
        values['backend'] = catalogue_value(values['backend']) or 'auto'
    return values


def _save_user_panel_values(user, data):
    """Garde comme préférences les réglages du volet présents dans `data` (brique commune)."""
    return save_panel_settings(user, 'transcriber', _SCHEMA, data, key=user_setting_key)


def _deposit_settings(user, post):
    """Les réglages d'un DÉPÔT (fichier, lien) : ce que le volet poste est gardé comme
    préférences, puis l'élément naît par la cascade COMMUNE (défauts ← réglages de l'auteur ←
    POST, `user_settings.new_element_settings`, 2026-09-27) — avant, un champ absent du POST
    prenait le défaut du modèle et non la préférence de l'auteur."""
    from wama.common.utils.user_settings import new_element_settings
    _save_user_panel_values(user, post)
    return new_element_settings(user, 'transcriber', _SCHEMA, Transcript, post=post,
                                key=user_setting_key)


