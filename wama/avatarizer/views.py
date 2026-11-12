"""
WAMA Avatarizer - Views
Interface de génération d'avatars animés
"""

import os
import logging
import tempfile
from pathlib import Path

from django.conf import settings
from django.shortcuts import render
from django.views import View
from django.http import JsonResponse
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError

import json
from .models import AvatarJob, BatchAvatarJob, BatchAvatarJobItem
from .params import PARAMS_JSON as _AVATAR_PARAMS_JSON, VOICE_SETTINGS

#: Les noms de réglages DÉCLARÉS — lus au schéma, pour reconnaître ce qu'une ligne de lot poste.
_SETTING_NAMES = {p['name'] for p in _AVATAR_PARAMS_JSON}
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.tts.constants import tts_catalog_key
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.input_match import input_labels
from wama.common.utils.queue_manipulation import make_queue_manipulation_views
from wama.common.tts.ui_meta import tts_engine_choices, tts_input_match_meta
from wama.common.utils.scoping import visible_or_404
from wama.common.utils.user_settings import (new_element_settings, read_panel_settings,
                                              save_panel_settings)

logger = logging.getLogger(__name__)

# Lazy import of the Celery task (avoids importing heavy libs at Gunicorn startup)
_generate_avatar = None


def _ensure_workers_imported():
    global _generate_avatar
    if _generate_avatar is None:
        from .workers import generate_avatar as ga
        _generate_avatar = ga


def _get_user(request):
    if request.user.is_authenticated:
        return request.user
    return get_or_create_anonymous_user()


def _animation_model_or_auto(value) -> str:
    """La CLÉ de `value` si elle nomme un modèle d'animation du catalogue, sinon « auto ». Le
    domaine est celui que DÉCLARE le schéma (`params.py`) : un seul inventaire pour ce que le
    select propose et ce que la création accepte. Le select poste une clé entière depuis la route
    F4b ⑤ (2026-10-07) ; un identifiant nu d'avant (assistant, lot) est lu dans l'espace de
    l'avatarizer, comme `AvatarJob.save` le normalise."""
    from wama.common.utils.auto_model import AUTO, is_auto
    from wama.common.utils.model_keys import catalog_key
    value = catalog_key((value or '').strip(), 'avatarizer')
    if not value or is_auto(value):
        return AUTO
    from wama.common.utils.param_schema import catalog_options
    field = next((p for p in _AVATAR_PARAMS_JSON if p['name'] == 'animation_model'), {})
    # LA lecture commune du domaine déclaré (2026-10-07) — elle vivait ici, recopiée.
    return value if value in {v for v, _ in catalog_options(field)} else AUTO


def _gallery_images():
    """Avatars de la galerie PARTAGÉE — `[{'name', 'url'}]`, lus à la médiathèque.

    ⚠ Parcourait `media/avatarizer/gallery/` à la main jusqu'au 2026-09-12, comme deux autres
    sites Python et deux gabarits : six endroits pour neuf images, et aucun droit. La galerie
    est désormais un `SystemAsset` — le modèle qui la décrit mot pour mot (« asset générique
    partagé par tous, géré par les admins ») et qui existait depuis le début.

    ⚠ Rend des DICTS et non des noms : l'URL vient de la médiathèque au lieu d'être composée
    dans le gabarit. Le jour où le domicile des assets bouge (chiffrement), rien à retoucher.
    La CLÉ reste le nom de fichier — `AvatarJob.avatar_gallery_name` le stocke.
    """
    from wama.media_library.services import gallery_entries
    return gallery_entries()


class IndexView(View):
    """Page principale de l'Avatarizer."""

    def get(self, request):
        user = _get_user(request)
        jobs = AvatarJob.objects.filter(user=user).order_by('-id')

        # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
        from wama.common.utils.process_control import reconcile_queue_of
        reconcile_queue_of(AvatarJob, user)

        from wama.common.utils.voice_options import voice_groups_json

        # Tri / filtre de la file (brique COMMUNE) — porte sur la liste de LOTS, qui est
        # l'unité affichée par la toolbar partagée.
        batches_list = _get_batches_list(user)
        from wama.common.utils.queue_view import apply_queue_sort_filter
        # `name_of` reçoit l'ENTRÉE de lot. Un AvatarJob n'a pas de champ de nom :
        # son identité lisible est l'avatar utilisé (galerie ou fichier téléversé).
        #
        # ⚠ Appel NU, comme les 11 autres sites (mesuré le 2026-08-27 : l'avatarizer était le
        # seul des 12 à l'envelopper). Le `try/except` qui l'entourait retombait sur
        # `q_sort, q_filter = '', ''` en ne journalisant qu'en `debug` : la file serait alors
        # apparue non triée, la toolbar sans sélection, et RIEN ne l'aurait dit. Une brique
        # COMMUNE qui casse doit casser VISIBLEMENT partout de la même façon — l'étouffer
        # ici la rendrait muette dans la seule app où elle n'est pas couverte par les autres.
        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list, name_of=_batch_display_name)

        context = {
            'jobs': jobs,
            'q_sort': q_sort,
            'q_filter': q_filter,
            'batches_list': batches_list,
            # Même inventaire que le synthesizer, et pour cause : c'est le MÊME parc, requis
            # par capacité et non par app (route F4b, 2026-09-01). L'avatarizer n'a jamais
            # possédé de moteur TTS — il les empruntait déjà via une constante partagée.
            'tts_models': tts_engine_choices(),
            'languages': AvatarJob.LANGUAGE_CHOICES,
            'media_url': settings.MEDIA_URL,
            'params_json': json.dumps(_AVATAR_PARAMS_JSON),
            # Valeurs du VOLET généré (contexte 'panel') : les réglages que l'utilisateur a
            # employés en dernier (mémorisés au dépôt, `create`), sous les défauts du schéma.
            'panel_values_json': json.dumps(
                read_panel_settings(user, 'avatarizer', _AVATAR_PARAMS_JSON)),
            # Groupes de voix (brique commune, per-user) pour le select GÉNÉRÉ de la modale
            # (options_source='voices') — remplace les optgroups hardcodés du template.
            # Le repli fail-safe vit DANS la brique depuis le 2026-09-23 (l'aide locale qui
            # l'enveloppait ici en était la copie ; le synthesizer appelait déjà celle-là).
            'voice_groups_json': voice_groups_json(user),
            # Appariement ENTRÉE↔MODÈLE du volet TTS (brique commune WamaInputMatch) : une voix
            # CLONÉE désactive les moteurs sans clonage. Meta lue du catalogue par la brique TTS
            # COMMUNE — l'avatarizer ne possède aucun de ces modèles, il lit ceux du domaine.
            # Aucune table d'exceptions à passer : les valeurs d'option répondent en IDENTITÉ
            # aux clés `synthesizer:<valeur>` (mesuré 2026-08-28, 7/7).
            'input_match_meta': json.dumps(tts_input_match_meta()),
            'input_labels': json.dumps(input_labels()),
        }
        return render(request, 'avatarizer/index.html', context)


def new_avatar_settings(user, model=None, app='avatarizer', post=None, inputs=None) -> dict:
    """Les colonnes de réglage d'un job NAISSANT, par la cascade COMMUNE (défauts du schéma ←
    réglages retenus de l'auteur ← ce qui est posté, `user_settings.new_element_settings`,
    2026-10-18). La voix ne s'applique qu'à un job porteur de texte (`show_if="text_content"`).
    Le moteur de voix est rendu en clé de catalogue (un réglage retenu avant le 2026-09-29 peut
    porter le nom COURT) ; les autres règles propres — modèle d'animation validé, amélioration
    dérivée — restent chez l'appelant. `model`/`app` : une jumelle de bac à sable passe les siens.
    Avant, cinq réglages relus avec leurs défauts recopiés dans la vue, et une ligne de lot
    écrivait les siens en dur."""
    values = new_element_settings(user, app, _AVATAR_PARAMS_JSON, model or AvatarJob, post=post,
                                  inputs=inputs)
    if values.get('tts_model'):
        values['tts_model'] = tts_catalog_key(values['tts_model'])
    return values


def _remember_settings(user, post, spoke):
    """Ce que le dépôt a posté devient la mémoire du suivant (`save_panel_settings`) — la voix
    seulement quand elle a servi (`spoke` : un job porteur de texte)."""
    if not spoke:
        post = {k: v for k, v in post.items() if k not in VOICE_SETTINGS}
    save_panel_settings(user, 'avatarizer', _AVATAR_PARAMS_JSON, post)


def create(request):
    """POST : Crée un AvatarJob avec les paramètres fournis."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)

    user = _get_user(request)
    # Le mode n'est PLUS un choix d'UI : il se DÉRIVE des entrées fournies (2026-08-28,
    # précédent imager txt2img/img2vid — décision de MOTEUR, pas de switch ; doctrine
    # MODES_QUEUE_UX §2bis). Règle UNIQUE, partagée avec la ligne de batch et tool_api :
    # une entrée AUDIO (fichier/URL — matériau explicite) prime, sinon le texte déclenche
    # le pipeline TTS→animation. Un `mode` encore posté n'est plus l'autorité.
    text_content = request.POST.get('text_content', '').strip()
    # Les deux PORTS (audio, image d'avatar) reçoivent un fichier téléversé ou DÉSIGNÉ
    # (médiathèque, arbre) — brique `received_inputs` (2026-09-28) : une désignation se POINTE.
    from wama.common.utils.media_paths import received_inputs
    audio_received = received_inputs(request, user, 'avatarizer', field='audio_input')
    audio_file = audio_received[0] if audio_received else None
    if audio_received.refusal and not audio_file:
        return JsonResponse({'error': audio_received.refusal}, status=400)
    source_url = request.POST.get('source_url', '').strip()
    mode = 'standalone' if (audio_file or source_url) else 'pipeline'
    if mode == 'pipeline' and not text_content:
        return JsonResponse(
            {'error': "Fournissez un texte à dire, un fichier audio ou une URL."}, status=400)

    # Réglages : la cascade COMMUNE (défauts du schéma ← réglages retenus de l'auteur ← le POST).
    # Le texte n'est posé qu'en pipeline : c'est lui qui rend la voix applicable (l'audio fourni
    # d'un job autonome prime, son texte éventuel ne sert pas).
    posted = request.POST.copy()
    if mode == 'pipeline':
        posted['text_content'] = text_content
    else:
        posted.pop('text_content', None)
    from wama.common.utils.user_settings import inputs_by_port
    job = AvatarJob(user=user, mode=mode, **new_avatar_settings(
        user, post=posted, inputs=inputs_by_port('avatarizer', audio_file)))

    # --- Standalone : fichier audio OU URL (WAMA_INGEST → téléchargé par le worker) ---
    if mode == 'standalone':
        if audio_file:
            from wama.common.app_registry import VOICE_SAMPLE_EXTENSIONS
            validator = FileExtensionValidator(allowed_extensions=VOICE_SAMPLE_EXTENSIONS)
            try:
                validator(audio_file)
            except ValidationError as e:
                return JsonResponse({'error': str(e)}, status=400)
            job.audio_input = audio_file.value
        else:
            job.source_url = source_url

    # --- Source de l'avatar ---
    # La card v4 poste toujours un FICHIER (joint ou désigné — un avatar système de la médiathèque
    # est pointé comme les autres, 2026-09-29).
    # Un NOM posté (`avatar_gallery_name`, ou `avatar_source='gallery'`) se résout parmi les
    # avatars que l'utilisateur voit et se DÉSIGNE (`designate_named_avatar`) : le job reçoit le
    # fichier, comme depuis la card — aucun job neuf ne stocke plus un nom (2026-09-29).
    avatar_name = request.POST.get('avatar_gallery_name', '').strip()
    by_name = request.POST.get('avatar_source') == 'gallery' or (
        avatar_name and not request.POST.get('avatar_source'))
    if by_name:
        if not avatar_name:
            return JsonResponse({'error': 'Choisissez un avatar.'}, status=400)
        from wama.common.utils.media_paths import InputRefused
        from .system_assets import designate_named_avatar
        try:
            avatar_file = designate_named_avatar(avatar_name, user)
        except InputRefused as e:
            return JsonResponse({'error': str(e)}, status=400)
    else:
        avatar_received = received_inputs(request, user, 'avatarizer', field='avatar_upload')
        avatar_file = avatar_received[0] if avatar_received else None
        if not avatar_file:
            return JsonResponse({'error': avatar_received.refusal
                                 or "Importez un avatar : une photo ou un objet 3D (.glb)."},
                                status=400)
    from .models import AVATAR_FILE_EXTENSIONS
    validator = FileExtensionValidator(allowed_extensions=AVATAR_FILE_EXTENSIONS)
    try:
        validator(avatar_file)
    except ValidationError as e:
        return JsonResponse({'error': str(e)}, status=400)
    # Le fichier doit convenir à au moins un modèle de l'app qui le consomme — jugé DÈS L'AJOUT
    # sur ses ATTRIBUTS mesurés (2026-09-30) : un GLB non riggé est refusé ici, avec sa raison,
    # plutôt qu'au lancement. Une photo n'a pas d'exigence d'attribut : rien n'est jugé.
    from wama.common.utils.input_match import app_attribute_verdict, work_token_for
    from wama.media_library.natures import INCOMPATIBLE
    token = work_token_for(avatar_file.name)
    if token:
        with avatar_file.readable_path() as readable:
            state, reason = app_attribute_verdict('avatarizer', token, readable)
        if state == INCOMPATIBLE:
            return JsonResponse({'error': f"Cet objet 3D ne peut pas servir d'avatar parlant ({reason}) : "
                                          "il faut un avatar riggé portant les 52 formes ARKit du visage."},
                                status=400)
    job.avatar_source = 'upload'
    job.avatar_upload = avatar_file.value

    # --- Modèle d'animation (2026-10-03) : « auto » ou un modèle `lip-sync` de l'app ---
    # Validé contre le CATALOGUE (la même liste que sert le select) ; une valeur inconnue vaut
    # « auto » — jamais une valeur brute au worker. Pas mémorisé comme dernier réglage : un
    # modèle nommé ne convient qu'à UNE nature d'avatar, et le suivant peut en changer.
    job.animation_model = _animation_model_or_auto(job.animation_model)

    # quality_mode DÉRIVÉ (`_derive_quality_mode`). (`use_enhancer` et `bbox_shift` viennent de la
    # cascade, coercés et bornés par le schéma.)
    _derive_quality_mode(job)

    job.save()
    # Provenance des ports réellement employés (rien pour un téléversement).
    for received, field in ((audio_file if mode == 'standalone' else None, 'audio_input'),
                            (avatar_file, 'avatar_upload')):
        if received:
            received.record(job, field)
    # Ce que le dépôt a posté se retient pour le suivant — la voix seulement si elle a servi.
    _remember_settings(user, request.POST, spoke=mode == 'pipeline')
    # Clé `id` — contrat COMMUN des vues qui créent un élément (trou #24 de la route). Cette vue
    # et `duplicate` étaient les DEUX seules de l'app à écrire `job_id` : `start`/`stop` (l. 218,
    # 221) émettaient déjà `id`. L'app était donc incohérente avec elle-même, et la normalisation
    # la rend cohérente en interne autant que conforme au contrat.
    return JsonResponse({'id': job.id, 'status': 'created'})


# ▶ de la card, ▶ et 🗑 de la file : fabrique COMMUNE (`item_views.make_item_views`, ROUTE §11
# #39, 2026-10-29) — la même déclaration que lit l'outil `start_avatarizer`. « Tout lancer »
# relance tout ce qui n'est ni en cours ni réussi : la règle du bouton, que l'outil de
# l'assistant ne suivait pas (il ne lançait que l'attente). « Tout effacer » ne refuse plus la
# file entière quand un job tourne : il garde celui-là, la règle commune.
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(work_model=AvatarJob, app_id='avatarizer',
                      task_for=lambda job: _task_for(job), get_user=_get_user,
                      reset_on_start={'progress': 0, 'error_message': ''},
                      pending={}, pending_exclude={'status__in': ['RUNNING', 'SUCCESS']},
                      batch_model=BatchAvatarJob)
start = _iv['start']
start_all = _iv['start_all']
clear_all = _iv['clear_all']
# ⏹ ⬇ 🗑 ⧉ ⚙ d'une card : la fabrique COMMUNE (2026-11-02, ROUTE §11 #42 ④), qui lit ce que l'app
# déclare à sa fabrique de lot — dont son nettoyage (`_forget_job` : le dossier du job) et LA
# fonction de réglage d'un job (`_apply_job_settings`), désormais celle du lot aussi.
stop = _iv['stop']
update_settings = _iv['update_settings']
delete = _iv['delete']
duplicate = _iv['duplicate']
download = _iv['download']


def _decorate_card(job, preloaded=False):
    """Les PROCESS de la card et son état MONTRÉ (`ROUTE §10.6` 5.1) — par la brique commune
    (`process_pipeline.decorate`). Une card texte montre « Voix → Animation » ; une card qui
    apporte son audio n'a qu'un process, la bande ne se rend pas."""
    from wama.common.services.process_pipeline import decorate
    decorate(job, preloaded=preloaded)
    return job


def _progress_extra(job):
    """Les clés PROPRES que le JS de l'avatarizer lit : la vidéo, puis les réglages montrés."""
    return {
        'video_url': (settings.MEDIA_URL + job.output_video.name
                      if job.status == 'SUCCESS' and job.output_video else None),
        'mode': job.mode,
        'avatar_name': job.avatar_label,
        'tts_model': job.get_tts_model_display(),
        'language': job.language,
        'voice_preset': job.voice_preset,
        'quality_mode': job.quality_mode,
        'quality_mode_label': job.get_quality_mode_display(),
        'bbox_shift': job.bbox_shift,
        'use_enhancer': job.use_enhancer,
        'text_preview': (job.text_content or '')[:80],
    }


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que ses clés propres. L'ETA est celle de ses PROCESS
# (`function_specs.PIPELINE`, 2026-10-05).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=AvatarJob, app_id='avatarizer', extra=_progress_extra)
progress, global_progress = _pv['progress'], _pv['global_progress']



# Card = partial serveur unique, rafraîchi par le polling — fabrique commune (`make_card_view`,
# 2026-11-02), qui donne au gabarit les clés de la file. `media_url`, passé ici, n'était plus lu.
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=AvatarJob, template='avatarizer/_avatar_card.html',
                           decorate=lambda job: _decorate_card(job))


def console_content(request):
    """GET : contenu de la console applicative (brique commune Redis)."""
    user = _get_user(request)
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


@require_POST
def extract_text(request):
    """
    POST : Extrait le texte d'un fichier (TXT, PDF, DOCX, CSV, MD).

    Accepte soit :
      - 'file'       : fichier uploadé (multipart, depuis l'explorateur Windows)
      - 'media_path' : chemin relatif depuis MEDIA_ROOT (fichier déjà sur le serveur / filemanager)
    """
    ALLOWED_EXTS = {'txt', 'md', 'pdf', 'docx', 'csv'}

    try:
        from wama.synthesizer.utils.text_extractor import extract_text_from_file
    except ImportError as e:
        return JsonResponse({'error': f'Module text_extractor indisponible : {e}'}, status=500)

    try:
        media_path = request.POST.get('media_path', '').strip()

        if media_path:
            # Fichier déjà sur le serveur (depuis filemanager)
            # La désignation commune : confinement, existence ET lisibilité pour ce compte
            # (`designated_source`, 2026-11-06 — le confinement seul lisait le fichier d'autrui).
            from wama.common.utils.media_paths import InputRefused, designated_source
            try:
                target, _ = designated_source(media_path, request.user)
            except InputRefused:
                return JsonResponse({'error': 'Fichier introuvable ou accès refusé.'}, status=403)
            target = Path(target)
            ext = target.suffix.lstrip('.').lower()
            if ext not in ALLOWED_EXTS:
                return JsonResponse({'error': f'Format non supporté : .{ext}'}, status=400)
            text = extract_text_from_file(str(target))

        else:
            # Upload direct (depuis l'explorateur Windows)
            upload = request.FILES.get('file')
            if not upload:
                return JsonResponse({'error': 'Aucun fichier fourni.'}, status=400)
            ext = upload.name.rsplit('.', 1)[-1].lower() if '.' in upload.name else ''
            if ext not in ALLOWED_EXTS:
                return JsonResponse({'error': f'Format non supporté : .{ext}'}, status=400)

            with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
                for chunk in upload.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            try:
                text = extract_text_from_file(tmp_path)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return JsonResponse({'text': text})

    except Exception as e:
        logger.error(f'[avatarizer] extract_text error: {e}', exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def gallery_list(request):
    """GET : Retourne la liste des avatars disponibles dans la galerie partagée.

    Contrat inchangé — `{'images': [{'name', 'url'}]}` — mais l'URL vient désormais de la
    médiathèque, comme pour la page.

    ⚠ Cassé du 2026-09-12 au 2026-09-22 : `_gallery_images()` rend des DICTS depuis le passage
    de la galerie en `SystemAsset`, et cette vue concaténait encore `MEDIA_URL +
    'avatarizer/gallery/' + name` → `TypeError` à chaque appel sur la galerie réelle (9
    entrées). Personne ne l'a vu : la PAGE ne passe pas par ici (elle reçoit `gallery_images`
    dans son contexte), et aucun gabarit ni JS n'appelle cet endpoint. *Un endpoint sans
    appelant ne se signale jamais — il faut le tester pour savoir qu'il est mort.*
    """
    return JsonResponse({'images': _gallery_images()})


def api_avatar_gallery(request):
    """GET : les avatars que l'utilisateur peut NOMMER (`system_assets.nameable_avatars`), sous la
    forme des sources d'options communes (`{'groups': …}`, comme `/common/api/voices/`) — la
    source `avatar_gallery` de `WamaParams` (registre `OPTION_SOURCES`). Le nœud Avatarizer du
    Studio la lit depuis le 2026-10-12 ; la vue du Studio en recopiait la liste."""
    from .system_assets import nameable_avatars
    names = nameable_avatars(_get_user(request))
    return JsonResponse({'groups': [{'group': '', 'options': [[n, n] for n in names]}]})


# ---------------------------------------------------------------------------
# Batch — import par fichier (format à balises unifié) + groupes
# ---------------------------------------------------------------------------

def _avatar_nature(job: AvatarJob) -> str:
    """Nature d'un job = son mode (pipeline / standalone)."""
    return job.mode or 'pipeline'


def _auto_wrap_orphans(user) -> None:
    """Range les jobs sans lot, chacun dans son lot d'un — brique COMMUNE (`auto_wrap_orphans`),
    qui ne casse pas la page sur un orphelin défectueux et lit les éléments sans leurs champs
    lourds. Une boucle écrite ici jusqu'au 2026-11-02, sans l'un ni l'autre."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(user, work_model=AvatarJob, batch_model=BatchAvatarJob,
                      item_model=BatchAvatarJobItem, fk_name='job')


def _batch_display_name(entry) -> str:
    """Nom lisible d'un lot, pour le tri alphabétique de la toolbar commune.

    Un AvatarJob n'a pas de champ de nom : son identité visible est l'avatar employé
    (image de la galerie, ou fichier téléversé). On prend celui du premier job du lot.
    """
    items = entry.get('items') or []
    # `items` = lignes de LIAISON (BatchAvatarJobItem) ; la FK métier est `job`.
    job = next((getattr(it, 'job', None) for it in items if getattr(it, 'job', None)), None)
    return job.avatar_label if job is not None else ''


def _get_batches_list(user):
    """Agrégats de file via la brique COMMUNE `build_batches_list`.

    Cette fonction recalculait à la main ce que la brique produit déjà (items ordonnés,
    compteurs SUCCESS/RUNNING/FAILURE, `has_success`), mais avec un vocabulaire à elle :
    `total`/`done_count` au lieu des clés du contrat commun. La toolbar et la card de lot
    partagées lisent le contrat commun — c'est ce décalage de noms qui empêchait
    l'avatarizer de les réutiliser telles quelles.

    `has_output` : un lot n'est « réussi » que si au moins un job a produit une VIDÉO —
    un SUCCESS sans fichier ne doit pas activer le téléchargement du lot.
    """
    _auto_wrap_orphans(user)
    from wama.common.utils.batch_common import build_batches_list
    from wama.common.utils.card_chips import common_chips_for_items
    from wama.avatarizer.params import PARAMS_JSON as _AVA_PARAMS_JSON
    batches = build_batches_list(
        user,
        batch_model=BatchAvatarJob,
        work_attr='job',
        order_by='-created_at',
        has_output=lambda job: bool(job.output_video),
        # Réglages COMMUNS aux filles de la card mère (slot meta_template — porté 31/08).
        extra=lambda b, items, jobs: {
            'common_chips': common_chips_for_items(jobs, _AVA_PARAMS_JSON)},
    )
    # (« batchs d'abord » RETIRÉ le 2026-08-26 : règle abandonnée le 2026-06-29 au profit du tri
    # de la barre commune — `apply_queue_sort_filter` (seul appelant, views.py:99) trie TOUJOURS,
    # défaut `recent`, donc ce tri était écrasé juste après. 4ᵉ exemplaire de ce que `c9408354`
    # a retiré d'enhancer ×2 et de synthesizer ; « batchs d'abord » n'est plus qu'une OPTION de la
    # barre (`batches_first`). Ne pas trier en dur avant l'appel.)
    # Les lignes d'exécution de TOUTES les cards de la page sont lues en une requête.
    from wama.common.services.process_pipeline import decorate_cards
    decorate_cards([link.job for b in batches for link in b['items']], _decorate_card)
    return batches


def batch_template(request):
    """GET : gabarit de fichier batch, par la brique commune (`batch_template_response`) — les
    deux syntaxes structurées que le lecteur accepte (pas de positionnel), et les deux modes de
    l'app en notes. Écrit à la main jusqu'au 2026-11-02."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'avatarizer', ['texte', 'avatar', 'voix', 'langue'],
        {'texte': 'Bonjour et bienvenue sur WAMA.', 'avatar': 'avatar1.png',
         'voix': 'default', 'langue': 'fr'},
        label='Avatarizer (une vidéo par ligne)', positional=False,
        notes=('Pipeline (texte → voix → avatar) : -p "texte à dire" -r nom_avatar.png '
               '[--voice default] [--language fr] [--tts coqui-xtts] [--quality fast] [-o sortie.mp4]',
               'Standalone (audio déjà prêt) : -i chemin/audio.wav -r nom_avatar.png [--quality quality]',
               "-r / avatar = nom d'un avatar de la médiathèque. Une ligne = un job."))


#: Le champ du PORT de l'audio d'un job (une donnée : il garde son nom) — lu par la brique des lignes
#: de lot (`batch_parsers.line_file_inputs`, 2026-11-06).
_LINE_FIELDS = {'work_audio': 'audio_input'}


def _parse_avatar_batch_from_request(request):
    """Le fichier batch posté → (lignes de job, avertissements) : la réception COMMUNE
    (`parse_batch_file_from_request` : extension, fichier temporaire, nettoyage — recopiée ici
    jusqu'au 2026-11-02), puis le lecteur de l'avatarizer, qui n'accepte que les syntaxes
    structurées."""
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    return parse_batch_file_from_request(request, parser=_parse_avatar_batch_file)


def _parse_avatar_batch_file(path):
    """Un fichier batch de l'avatarizer (CSV à en-têtes ou balises) → (lignes, avertissements)."""
    from wama.common.utils.batch_parsers import (
        extract_batch_file_text, is_structured_batch_text, parse_unified_batch,
    )
    if not is_structured_batch_text(extract_batch_file_text(path)):
        raise ValueError(
            'Format attendu : CSV à en-têtes ou balises (-p/-i/-r…). Voir le modèle.'
        )
    items, warnings = parse_unified_batch(path)

    rows, extra = [], []
    for it in items:
        row = _unified_item_to_avatar_row(it)
        if row.get('error'):
            extra.append(f"Ligne {it.get('line_num')} : {row['error']}, ignorée")
            continue
        rows.append(row)
    if not rows:
        extra.append('Aucune ligne valide')
    return rows, warnings + extra


def _unified_item_to_avatar_row(it: dict) -> dict:
    """Mappe un item unifié → champs AvatarJob. {'error': msg} si invalide."""
    opts = it.get('options') or {}
    reference = it.get('reference')
    if not reference:
        return {'error': 'avatar de référence (-r) manquant'}

    prompt = it.get('prompt')
    audio = it.get('input')
    # Règle UNIQUE de dérivation du mode (2026-08-28), partagée avec `create` et
    # tool_api : l'AUDIO (matériau explicite) prime, sinon le texte → pipeline TTS.
    if audio:
        mode = 'standalone'
    elif prompt:
        mode = 'pipeline'
    else:
        return {'error': 'ni texte (-p) ni audio (-i) fourni'}

    # Les RÉGLAGES que la ligne porte, sous leur nom de schéma — ceux qu'elle tait viennent de la
    # cascade commune à la création du job (`new_avatar_settings`), comme pour un dépôt. Les
    # défauts écrits ici (« fr », « default », bbox 0…) sont retirés le 2026-10-18.
    # --quality reste accepté (compat des fichiers batch existants) mais n'est plus
    # qu'un ALIAS de l'amélioration CodeFormer (2026-08-03) — le mode UI est mort.
    row = {
        'mode': mode,
        'text_content': prompt if mode == 'pipeline' else '',
        'audio_path': audio or '',
        'avatar_gallery_name': reference,
        'output': it.get('output', ''),
        'line_num': it.get('line_num'),
    }
    if opts.get('tts') or opts.get('model'):
        row['tts_model'] = tts_catalog_key(opts.get('tts') or opts.get('model'))
    for name, option in (('language', 'language'), ('voice_preset', 'voice'), ('bbox_shift', 'bbox')):
        if opts.get(option) not in (None, ''):
            row[name] = opts[option]
    if 'enhancer' in opts or 'quality' in opts:
        row['use_enhancer'] = (str(opts.get('enhancer', '')).lower() in ('1', 'true', 'yes')
                               or opts.get('quality') == 'quality')
    return row


@require_POST
def batch_preview(request):
    """POST : Aperçu d'un fichier batch (sans création)."""
    try:
        rows, warnings = _parse_avatar_batch_from_request(request)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    preview = [
        {
            'mode': r['mode'],
            'avatar': r['avatar_gallery_name'],
            'text': (r['text_content'] or r['audio_path'])[:60],
            'language': r.get('language', ''),
        }
        for r in rows
    ]
    # Un avatar que l'utilisateur ne voit pas se dit AVANT la création (2026-09-29) : sinon le job
    # naît puis échoue au lancement sur « Avatar introuvable ».
    from wama.media_library.services import resolve_visible_asset
    from .system_assets import AVATAR_NATURES      # photo OU objet 3D (2026-09-30)
    user = _get_user(request)
    for r in rows:
        name = r['avatar_gallery_name']
        if name and not any(resolve_visible_asset(user, n, name) for n in AVATAR_NATURES):
            warnings.append(f"Ligne {r.get('line_num') or '?'} : avatar introuvable dans la "
                            f"médiathèque — {r['avatar_gallery_name']}")
    return JsonResponse({'items': preview, 'warnings': warnings, 'count': len(rows)})


@require_POST
def batch_create(request):
    """POST : Crée N AvatarJob depuis un fichier batch, groupés par nature (mode)."""
    user = _get_user(request)
    try:
        rows, warnings = _parse_avatar_batch_from_request(request)
    except ValueError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    def _make_job(row):
        # L'AUDIO d'une ligne autonome (`-i`) se reçoit comme sur la card, par la brique commune des
        # lignes de lot (2026-11-06) : un chemin se DÉSIGNE (confinement, existence, droit de
        # LECTURE — ce lot ne vérifiait que le confinement : l'audio d'un autre compte passait),
        # une URL va à la source téléchargée (`WAMA_INGEST`). Refusé : la ligne est écartée, avec
        # son motif — elle partait sans audio.
        from wama.common.utils.batch_parsers import (attach_line_inputs, line_file_inputs,
                                                     line_file_ports)
        received, remote = {}, {}
        if row['mode'] == 'standalone' and row['audio_path']:
            try:
                files = line_file_ports('avatarizer', {'input': row['audio_path'],
                                                       'line_num': row.get('line_num')})
                received, remote = line_file_inputs(user, 'avatarizer', files, _LINE_FIELDS,
                                                    model=AvatarJob)
            except ValueError as exc:    # `InputRefused` compris : une désignation refusée
                warnings.append(f"Ligne {row.get('line_num') or '?'} : {exc} — ignorée")
                return None
        # L'avatar NOMMÉ par la ligne est désigné comme depuis la card (les siens, les partagés, le
        # système — 2026-09-29) ; introuvable, le nom est gardé et l'aperçu du lot l'a signalé.
        from wama.common.utils.media_paths import InputRefused
        from .system_assets import designate_named_avatar
        try:
            avatar = designate_named_avatar(row['avatar_gallery_name'], user)
        except InputRefused:
            avatar = None
        # La ligne POSTE ses réglages comme un dépôt : la cascade commune fait le reste.
        values = new_avatar_settings(user, post={k: v for k, v in row.items() if k in _SETTING_NAMES})
        values['animation_model'] = _animation_model_or_auto(values.get('animation_model'))
        job = AvatarJob(
            **values,
            user=user,
            mode=row['mode'],
            avatar_source='upload' if avatar else 'gallery',
            avatar_gallery_name='' if avatar else row['avatar_gallery_name'],
        )
        _derive_quality_mode(job)
        if avatar:
            job.avatar_upload = avatar.value
        job.save()
        if avatar:
            avatar.record(job, 'avatar_upload')
        attach_line_inputs(job, received, remote)
        return job

    jobs = [job for job in (_make_job(r) for r in rows) if job]

    # Rangés à l'ARRIVÉE par la déclaration de la fabrique (`group_key`, un lot par nature) —
    # le regroupement écrit ici à la main est retiré le 2026-10-16.
    from wama.common.utils.queue_manipulation import consolidate_arrival
    batches = consolidate_arrival(AvatarJob, [j.id for j in jobs], user)

    return JsonResponse({
        'status': 'created',
        'jobs': len(jobs),
        'batches': len(batches),
        'warnings': warnings,
    })


# Manipulation directe de file (brique commune) : consolidate / reorder /
# move_to_batch / remove_from_batch. Remplace le consolidate maison (regroupement
# global par nature) par le contrat uniforme sur ids selectionnes.
_qm = make_queue_manipulation_views(
    work_model=AvatarJob, batch_model=BatchAvatarJob,
    item_model=BatchAvatarJobItem, fk_name='job',
    group_key=_avatar_nature,           # l'arrivée (`consolidate_arrival`) ET le glisser-déposer
    get_user=_get_user,
)

consolidate = _qm['consolidate']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
remove_from_batch = _qm['remove_from_batch']


# ── Les CINQ vues de lot de l'avatarizer : fabrique COMMUNE (`batch_views.make_batch_views`,
# portage 2026-09-23, 4ᵉ app réelle — ROUTE §11 #36). Spécificités DÉCLARÉES en kwargs :
# réglages = le SCHÉMA + l'héritage du mode pipeline (`mode`, `tts_model`, `language`,
# `voice_preset` — TTS relève du synthesizer, standalone-only 2026-07-15) ; `quality_mode`
# DÉRIVÉ de `use_enhancer` après application (`after_update` — le mode UI est mort le 03/08) ;
# trois champs fichier (`audio_input`, `avatar_upload`, `output_video`), la vidéo vidée à la
# duplication et servie au téléchargement (mono-format MP4, nom `batch_avatarizer_<id>.zip`) ;
# un lot PARTAGÉ se télécharge (`visible_or_404`, jamais pour écrire) ; cache de progression
# purgé à la suppression ; tâche importée paresseusement (`_ensure_workers_imported`).
# ▶ de lot = l'idiome mesuré : tout ce qui ne tourne pas se (re)lance.
from wama.common.utils.batch_views import apply_item_settings, make_batch_views
from wama.avatarizer.params import PARAMS_JSON as _SCHEMA

SETTINGS_FIELDS = tuple(dict.fromkeys(
    [p['name'] for p in _SCHEMA] + ['mode', 'tts_model', 'language', 'voice_preset']))


def _task_for(job):
    _ensure_workers_imported()
    return _generate_avatar


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — refaire la voix seule, ou
# l'animation seule sur la voix déjà synthétisée.
start_process = make_process_start_view(
    work_model=AvatarJob, task_for=_task_for,
    reset_on_start={'progress': 0, 'error_message': ''})


def _derive_quality_mode(job):
    """`quality_mode` DÉRIVÉ de `use_enhancer` (2026-08-03 : le backend ne lit que lui, le champ ne
    sert plus qu'aux clés ETA et aux données existantes) — LA règle de tous les gestes : création,
    ⚙ d'élément et de lot, ligne de lot, outil de l'assistant (elle était écrite cinq fois)."""
    job.quality_mode = 'quality' if job.use_enhancer else 'fast'
    return ['quality_mode']


#: Les réglages de la VOIX : un job « pipeline » les porte (la relance regénère l'audio depuis son
#: texte), un job standalone apporte son audio — ils n'y ont pas de sens.
_TTS_SETTINGS = ('text_content', 'tts_model', 'quality_intent', 'language', 'voice_preset',
                 'tts_temperature', 'tts_seed', 'tts_top_p')


def _apply_job_settings(job, data):
    """LES réglages d'un job, posés sans sauver — la ⚙ d'une card ET celle de son lot (la fabrique
    de lot l'appelle pour les deux). Jusqu'au 2026-11-02 le lot posait toute la liste
    `SETTINGS_FIELDS`, la voix comprise sur un job standalone, et un texte vide : la règle n'était
    écrite que dans la vue de la card. `quality_mode` se dérive après (`after_update`)."""
    data = dict(data)
    if not str(data.get('text_content') or '').strip():
        data.pop('text_content', None)        # un texte vide ne remplace pas le texte existant
    fields = [n for n in SETTINGS_FIELDS if job.mode == 'pipeline' or n not in _TTS_SETTINGS]
    return apply_item_settings(job, data, params_fields=fields)


def _forget_job(job):
    """Ce qu'aucune brique ne connaît d'un job qu'on retire : son cache de progression, et le
    DOSSIER de job que l'animation écrit (`workers.py`, `job_<id>/`) — la card désigne ses
    fichiers, jamais ce dossier. Relevé le 2026-08-25 : 13 dossiers `job_*` orphelins contre 4
    rattachés, dont un de 1715,7 Mo. Jusqu'au 2026-11-02 seule la 🗑 d'une card le purgeait :
    « tout effacer » et la 🗑 d'un lot le laissaient sur le disque."""
    from wama.common.utils.media_paths import app_media_dir
    from wama.common.utils.work_dir import purge_job_dir
    cache.delete(f"avatarizer_progress_{job.id}")
    freed = purge_job_dir(
        Path(settings.MEDIA_ROOT) / app_media_dir('avatarizer', job.user_id, 'output'), job.pk)
    if freed:
        logger.info("[avatarizer] job_%s : %.1f Mo de fichiers de job libérés", job.pk, freed / 1048576)


_bv = make_batch_views(
    work_model=AvatarJob, batch_model=BatchAvatarJob, get_user=_get_user,
    task_for=_task_for,
    output_field='output_video',
    schema=_SCHEMA, apply_settings=_apply_job_settings, after_update=_derive_quality_mode,
    item_model=BatchAvatarJobItem, fk_name='job',
    read_lookup=lambda user, pk: visible_or_404(BatchAvatarJob, user, pk=pk),
    zip_name=lambda b: f"batch_avatarizer_{b.id}.zip",
    on_delete=_forget_job,
)
batch_update = _bv['batch_update']
batch_start = _bv['batch_start']
batch_duplicate = _bv['batch_duplicate']
batch_download = _bv['batch_download']
batch_delete = _bv['batch_delete']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']
