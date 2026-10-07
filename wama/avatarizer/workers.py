"""
WAMA Avatarizer - Celery Worker

Pipeline recommandé :
  1. (mode pipeline) Appel microservice TTS → WAV temporaire
  2. Résolution de l'image avatar (galerie partagée ou upload utilisateur)
  3. MuseTalk v1.5 : synchronisation labiale audio → vidéo
  4. (optionnel, mode qualité) CodeFormer : amélioration faciale
  5. Sauvegarde dans media/avatarizer/{user_id}/output/

Prérequis (voir setup_avatarizer.sh) :
  wama/common/backends/vendor/musetalk/    ← git clone TMElyralab/MuseTalk
  wama/common/backends/vendor/codeformer/  ← git clone sczhou/CodeFormer
  AI-models/models/lipsync/musetalk/    ← checkpoints MuseTalk
  AI-models/models/lipsync/codeformer/ ← checkpoints CodeFormer (via symlinks weights/)
"""

import os
import sys
import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings

from .models import AvatarJob
from wama.common.services.resource_governor import vram_reservation
from wama.common.utils.console_utils import push_console_line

# Backends hors process (contrat commun BaseModelBackend) — le worker orchestre, ils executent.
# Le MODÈLE porte son moteur ; le backend s'en dérive (2026-09-07). Résolution PARESSEUSE et
# mémoïsée : les deux singletons étaient instanciés À L'IMPORT du module, depuis des classes
# importées par chemin. Le job ne porte pas de version MuseTalk — le backend exécute la v1.5
# (`--version v15`, `musetalkV15/`), d'où la clé de catalogue employée plus bas.
_backends_resolus: dict = {}

#: Le modèle catalogue de l'avatar 3D (moteur `talkinghead`) — déclaré dans `model_config`.
TALKINGHEAD_KEY = 'avatarizer:talkinghead'


def _backend(catalog_key: str):
    """Instance (singleton) du backend que le catalogue désigne pour `catalog_key`."""
    if catalog_key not in _backends_resolus:
        from wama.common.backends.manager import backend_for_key
        classe = backend_for_key(catalog_key)
        if classe is None:
            raise RuntimeError(f"{catalog_key} : aucun backend résolu depuis le catalogue "
                               "(ligne absente, ou sans moteur déclaré)")
        _backends_resolus[catalog_key] = classe()
    return _backends_resolus[catalog_key]

logger = logging.getLogger(__name__)


# Client du microservice TTS : brique COMMUNE (`common/tts/service_client.py`, 2026-08-28 —
# ce fichier portait le 2ᵉ des 4 exemplaires du même POST /tts, sans détection du 503
# « loading » : un service en démarrage sortait en RuntimeError au lieu d'un retry).
from wama.common.tts.service_client import TTSServiceLoadingError, tts_via_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _console(user_id: int, message: str, level: str = 'info') -> None:
    try:
        push_console_line(user_id=user_id, line=message, app='avatarizer', level=level)
    except Exception:
        pass


def _call_tts_service(job: AvatarJob) -> str:
    """Synthétise `job.text_content` via la brique commune, renvoie un WAV temporaire.

    La voix est résolue par la brique COMMUNE `common.tts.voice_refs.speaker_wav_for`
    (ua_ médiathèque / cv_ voix personnalisée / presets), qui ne rend un fichier que si le
    MOTEUR clone — la même règle que le synthesizer, tenue à un seul endroit (13/09).
    Jusqu'au 2026-09-12 elle vivait dans le synthesizer et ce docstring l'appelait « la brique
    CENTRALISÉE du synthesizer » — une brique partagée par deux apps qui vit dans l'une d'elles
    n'est pas centralisée, elle est mal rangée. Le bloc manuel qui vivait ici avant elle ne
    couvrait que `cv_*` : les voix de la médiathèque étaient silencieusement ignorées."""
    from wama.common.tts.voice_refs import speaker_wav_for
    speaker_wav = speaker_wav_for(job.tts_model, job.voice_preset, user=job.user,
                                  language=job.language or '')
    return tts_via_service(
        job.text_content, job.tts_model,
        language=job.language, voice_preset=job.voice_preset,
        speaker_wav=speaker_wav,
    )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

def _video_seconds(job) -> float:
    """La durée de la vidéo d'une card : mesurée, sinon ~ texte / 15 (mode pipeline)."""
    duration = float(job.duration_seconds or 0)
    if not duration and job.mode == 'pipeline' and job.text_content:
        duration = len(job.text_content) / 15.0
    return duration


def avatarizer_eta_key_size(job, duration: float = None, avatar_3d: bool = None):
    """(clé, taille, unité) de l'ETA de l'ANIMATION — temps ∝ durée vidéo. Un rendu TalkingHead
    n'a pas le coût d'un lip-sync : clé à part, sinon il fausse l'ETA apprise de MuseTalk. UN
    lieu, partagé par la glu (durée mesurée, moteur TIRÉ) et la déclaration du process
    (`ProcessSpec.eta` : durée connue, sinon ~ texte / 15 ; avatar 3D lu sur la NATURE du fichier,
    `input_match.work_token_for`, la brique du tirage) — ROUTE §11 #37.

    ⚠ La clé d'une photo ne dépend plus de la qualité (2026-10-05) : depuis que l'amélioration
    faciale est un process à part (« Visage », qui apprend `avatarizer:codeformer`), l'animation
    seule apprend sous `avatarizer:fast` — la vue estimait encore une photo « qualité » sous
    `avatarizer:quality`, une clé que plus rien n'apprenait."""
    if avatar_3d is None:
        from .function_specs import is_3d_avatar
        avatar_3d = is_3d_avatar(job)
    if duration is None:
        duration = _video_seconds(job)
    key = 'avatarizer:talkinghead' if avatar_3d else 'avatarizer:fast'
    return key, duration, 'video_sec'


def enhance_eta_key_size(job, duration: float = None):
    """(clé, taille, unité) de l'ETA du process « Visage » : l'amélioration faciale (CodeFormer),
    ∝ durée vidéo ; None quand elle n'est pas demandée (le process ne fait que rendre la vidéo
    animée)."""
    duration = _video_seconds(job) if duration is None else duration
    return ('avatarizer:codeformer', duration, 'video_sec') if job.use_enhancer else None


def speak_eta_key_size(job, tts_model: str = None):
    """(clé, taille, unité) de l'ETA du process « Voix » : celle du service TTS commun, sous le
    modèle employé (`tts_model`, tiré au lancement) ou demandé."""
    from wama.common.tts.service_client import tts_eta_key_size
    return tts_eta_key_size(job.text_content, tts_model or job.tts_model)


@shared_task(bind=True, max_retries=60, default_retry_delay=10)
def generate_avatar(self, job_id: int, process: str = None):
    """Tâche Celery (queue gpu) : génère une vidéo avatar animée — par le squelette COMMUN
    (`run_item_task`, marche P6 du 2026-10-03) et le PIPELINE de l'app (`function_specs.PIPELINE`) :

      • `speak`   (mode pipeline) : synthèse audio via le service TTS ;
      • `animate` : résolution de l'avatar, MuseTalk ou TalkingHead ;
      • `enhance` (photo) : CodeFormer si demandé, sinon la vidéo animée telle quelle.

    Un lancement ne rejoue que ce qui n'est plus à jour (changer l'avatar ne re-synthétise pas la
    voix, demander l'amélioration faciale ne réanime pas) ; `process` le borne à UN process."""
    from wama.common.services.output_process import forget_lost_generation
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    # « Visage » repart de la vidéo que l'animation a laissée : si elle n'est plus là, on réanime.
    known = AvatarJob.objects.filter(pk=job_id).first()
    if known is not None and known.output_video:
        forget_lost_generation(known, 'output_video', 'animate')
    if not (getattr(self.request, 'retries', 0) or 0):
        # « En cours » est posé par les LANCEURS (`begin_processing`). Un créateur qui envoie la
        # tâche seule (l'outil de l'assistant) laissait sinon l'élément « en attente » pendant son
        # traitement — geste gardé de l'ancienne tâche, à la PREMIÈRE livraison seulement (une
        # re-livraison ne doit pas remettre en cours ce que l'utilisateur a arrêté).
        AvatarJob.objects.filter(pk=job_id).exclude(status='RUNNING').update(
            status='RUNNING', task_id=self.request.id or '')
    run_item_task(self, app_id='avatarizer', model=AvatarJob, item_id=job_id,
                  pipeline=PIPELINE, processes=PROCESSES, notify_label='Avatarizer', only=process)


def _speak(job, ctx):
    """Process `speak` : le texte de la card → son audio (service TTS). L'audio généré est un
    ARTEFACT du job (l'entrée de l'animation), pas un temporaire : persisté dans `audio_input`,
    il se vérifie, s'écoute et se reprend. Rejoué, il REMPLACE l'ancien (garde de partage : un
    job dupliqué partage son fichier). Un service TTS qui charge encore fait re-livrer la tâche."""
    _console(job.user_id, f"Démarrage génération avatar #{job.id}", 'info')
    ctx.progress(10)
    tmp_audio_path = None
    try:
        # Choix AUTOMATIQUE du moteur TTS (brique commune `auto_model`, 2026-09-02) :
        # résolu AU LANCEMENT, sur le domaine que le schéma déclare pour les options
        # (`params.py` — le parc TTS par capacité, l'avatarizer n'en possède aucun).
        # Le modèle tiré n'est PAS écrit dans le réglage (contrat du squelette : « auto » reste
        # « auto », et un réglage surveillé qui changerait pendant son propre process se
        # périmerait lui-même) : il est dit dans la console et gardé sur la ligne d'exécution.
        from wama.common.utils.auto_model import is_auto, read_quality_intent, resolve_model_choice
        requested = job.tts_model
        tts_model = requested
        if is_auto(requested):
            quality = read_quality_intent(getattr(job, 'quality_intent', None))
            # Voix clonée ⇒ le tirage exige `supports_cloning` (même règle que le synthesizer).
            from wama.common.tts.voice_refs import is_cloned_voice
            exigences = ['supports_cloning'] if is_cloned_voice(job.voice_preset) else None
            tts_model = resolve_model_choice(
                requested, app_id='avatarizer', quality_intent=quality, requires=exigences,
                fallback=AvatarJob._meta.get_field('tts_model').get_default())
            _console(job.user_id,
                     f"Choix automatique du moteur TTS → {tts_model} "
                     f"(capacités + VRAM libre au lancement, curseur qualité {quality}/100)", 'info')
        _console(job.user_id, "Synthèse audio via service TTS…", 'info')
        job.tts_model = tts_model                  # le temps de l'appel : la brique lit le job
        try:
            tmp_audio_path = _call_tts_service(job)
        finally:
            job.tts_model = requested
        ctx.progress(80)
        from django.core.files import File
        from wama.common.utils.queue_duplication import safe_delete_file
        if job.audio_input:
            safe_delete_file(job, 'audio_input')
        with open(tmp_audio_path, 'rb') as fh:
            job.audio_input.save(f"tts_job{job.id}.wav", File(fh), save=True)
        _console(job.user_id, "Audio TTS généré.", 'info')
        return {'fields': {'audio_input': job.audio_input.name}, 'label': 'audio de la voix',
                'console_success': "Audio TTS généré ✓",
                'models': [tts_model] if tts_model else None,
                'eta': speak_eta_key_size(job, tts_model),
                'output_ref': job.audio_input.name}
    except TTSServiceLoadingError as e:
        # Service TTS en démarrage — rendre le worker GPU et revenir (politique du squelette
        # commun : 60 × 10 s, puis échec dit).
        from wama.common.utils.task_skeleton import ServiceNotReady
        raise ServiceNotReady(
            "Service TTS en chargement", countdown=10, max_attempts=60,
            gave_up="Service TTS non disponible après 10 minutes d'attente (60 tentatives)") from e
    except Exception:
        ctx.reset_progress()
        raise
    finally:
        if tmp_audio_path and os.path.exists(tmp_audio_path):
            try:
                os.unlink(tmp_audio_path)
            except Exception:
                pass


def _animate(job, ctx):
    """Process `animate` : l'avatar + l'audio → la vidéo (MuseTalk ou TalkingHead). L'audio vient
    du process `speak` ou de la card (mode standalone — une URL est rapatriée par le squelette
    avant cette glue, `WAMA_INGEST`). L'amélioration faciale est le process suivant (`_enhance`)."""
    import time as _time
    job_id = job.id
    try:
        if not job.audio_input:
            raise ValueError("Mode Standalone : aucun fichier audio (ni URL) fourni.")
        audio_path = job.audio_input.path
        ctx.progress(5)

        # ------------------------------------------------------------------
        # Résoudre l'image avatar
        # ------------------------------------------------------------------
        if job.avatar_source == 'gallery':
            if not job.avatar_gallery_name:
                raise ValueError("Galerie : aucun avatar sélectionné.")
            # La galerie est un `SystemAsset` depuis le 2026-09-12 : on ne compose plus son
            # chemin, on le DEMANDE. La clé reste le nom stocké dans `avatar_gallery_name`.
            from wama.media_library.services import gallery_path
            image_path = gallery_path(job.avatar_gallery_name)
            if not image_path or not os.path.exists(image_path):
                raise FileNotFoundError(f"Avatar introuvable : {job.avatar_gallery_name}")
        else:
            if not job.avatar_upload:
                raise ValueError("Upload : aucune image avatar fournie.")
            image_path = job.avatar_upload.path

        ctx.progress(12)

        # ── Le MODÈLE D'ANIMATION se TIRE parmi ceux de l'avatarizer (2026-09-30) ──────────
        # Brique commune `resolve_model_choice` : les ENTRÉES fournies décident (une photo ne
        # laisse que MuseTalk, un GLB que TalkingHead — `available_inputs`/`consumes`), le
        # catalogue fait le reste (VRAM, backend présent). Plus d'aiguillage par extension ici :
        # un 3ᵉ modèle photo (SoulX-FlashHead…) entrera dans le même tirage sans toucher au worker.
        from wama.avatarizer.utils.model_config import ANIMATION_FALLBACK, ANIMATION_SPEC
        from wama.common.utils.auto_model import resolve_model_choice
        from wama.common.utils.input_match import input_attribute_verdict, work_token_for
        from wama.model_manager.models import AIModel
        avatar_token = work_token_for(image_path)
        if avatar_token not in ANIMATION_FALLBACK:
            raise ValueError("Avatar : une photo (JPG, PNG, WebP) ou un objet 3D riggé (.glb) est attendu.")
        available = ['work_audio', avatar_token] + (['prompt'] if (job.text_content or '').strip() else [])
        # Le job porte son CHOIX depuis le 2026-10-03 (`animation_model`) : « auto » tire comme
        # avant, un modèle NOMMÉ est pris tel quel — `resolve_model_choice` le rend sans juger.
        from wama.common.utils.auto_model import is_auto
        from wama.common.utils.model_keys import catalog_key
        # Clé de catalogue (route F4b ⑤) ; un identifiant nu d'avant se lit dans l'espace de l'app.
        requested = catalog_key((job.animation_model or '').strip(), 'avatarizer')
        named = bool(requested) and not is_auto(requested)
        model_id = resolve_model_choice(
            requested, spec=ANIMATION_SPEC,
            available_inputs=available, consumes=[avatar_token],
            fallback=ANIMATION_FALLBACK[avatar_token])
        model_key = model_id if ':' in model_id else f'avatarizer:{model_id}'
        chosen = AIModel.objects.filter(model_key=model_key).first()
        if named:
            # Un modèle NOMMÉ doit ANIMER l'avatar fourni : MuseTalk ne sait rien d'un GLB,
            # TalkingHead rien d'une photo. Refus AVANT tout calcul, avec la raison et l'issue —
            # jamais un repli silencieux sur un autre modèle que celui qui a été demandé.
            from wama.model_manager.services.model_selector import matches_inputs
            if chosen is None:
                raise ValueError(f"Modèle d'animation inconnu du catalogue : {requested}.")
            if not matches_inputs(chosen, task='lip-sync', consumes=[avatar_token]):
                nature = "un avatar 3D (.glb)" if avatar_token == 'work_object3d' else "une photo"
                raise ValueError(
                    f"{chosen.name} n'anime pas {nature}. Choisissez « auto » dans les réglages "
                    "de l'élément, ou le modèle qui accepte cet avatar.")
        row = {'capabilities': chosen.capabilities, 'composition': chosen.composition} if chosen else {}
        engine = ((row.get('composition') or {}).get('runtime') or {}).get('engine') or ''
        avatar_3d = engine == 'talkinghead'
        _console(job.user_id, f"Modèle d'animation → {model_key} "
                              + ("(choisi dans les réglages)" if named
                                 else "(choisi d'après l'avatar fourni)"), 'info')

        # Le fichier a le bon RÔLE ; encore faut-il les ATTRIBUTS que le modèle exige (un objet 3D
        # doit être riggé, au visage ARKit). Jugé sur le FICHIER, avant tout rendu : un maillage
        # TripoSR est refusé avec sa raison. Sans exigence déclarée (MuseTalk), rien n'est jugé.
        from wama.media_library.natures import INCOMPATIBLE, WARNING
        state, reason = input_attribute_verdict(row.get('capabilities'), avatar_token, image_path)
        if state == INCOMPATIBLE:
            raise ValueError(
                f"Cet objet 3D ne peut pas servir d'avatar parlant ({reason}). Il faut un "
                "avatar riggé portant les 52 formes ARKit du visage (ex. un export MPFB).")
        if state == WARNING:
            _console(job.user_id, f"Avatar : {reason} — la bouche sera moins précise.", 'warning')

        # Sortie de l'app : le livrable, et RIEN d'autre (règle `MEDIA_STORAGE_TIERING.md` —
        # `media/` ne contient que `<app>/<user>/input|output/` et `users/`).
        from wama.common.utils.media_paths import app_media_dir
        sortie_app = Path(settings.MEDIA_ROOT) / app_media_dir('avatarizer', job.user_id, 'output')
        sortie_app.mkdir(parents=True, exist_ok=True)

        # L'animation REJOUE : la vidéo d'avant (et l'animée gardée sous une améliorée) part.
        from wama.common.services.output_process import drop_previous_outputs
        drop_previous_outputs(job, 'output_video')

        # Le travail se fait HORS de `media/` (2026-08-25). Avant, MuseTalk et CodeFormer
        # écrivaient dans `output/job_<id>/` : la vidéo finissait dans un sous-dossier `v15/`
        # (ou pire, DANS `codeformer_out/final_results/`), et les frames intermédiaires
        # restaient — 1715,7 Mo pour un job, 99,6 % du média de l'app.
        from wama.common.utils.work_dir import work_dir
        import shutil as _shutil

        # ------------------------------------------------------------------
        # Animation — TalkingHead (avatar 3D) ou MuseTalk (photo)
        # ------------------------------------------------------------------
        ctx.progress(25)
        _t_render = _time.time()

        with work_dir(f'avatarizer_job{job_id}') as travail:
            if avatar_3d:
                # Les lèvres viennent des MOTS. Un texte (pipeline TTS) les donne ; un AUDIO seul
                # passe par la transcription — le sens inverse du TTS, par la brique commune qui
                # délègue au backend Whisper du transcriber (mots DATÉS : timings mesurés).
                words, lang = None, (job.language or 'fr')
                if not (job.text_content or '').strip():
                    _console(job.user_id, "Avatar 3D : transcription de l'audio (mots datés)…", 'info')
                    from wama.common.utils.whisper_utils import transcribe_audio
                    heard = transcribe_audio(audio_path, language=(job.language or None),
                                             word_timestamps=True)
                    words = [w for seg in heard.segments for w in (seg.words or [])]
                    if not words:
                        raise ValueError("Avatar 3D : aucune parole reconnue dans l'audio — "
                                         "fournissez le texte dit.")
                    # La langue ENTENDUE choisit le module de visèmes (le job n'a pas de texte à dire).
                    lang = heard.language or lang
                    _console(job.user_id, f"Transcription : {len(words)} mots ({lang}).", 'info')
                _console(job.user_id, "Avatar 3D : rendu TalkingHead image par image…", 'info')
                # Aperçu « PENDANT » (2026-10-06) : la dernière image rendue, toutes les ~2 s, par
                # la brique commune (`PartialFrames`, comme l'enhancer vidéo). MuseTalk, lancé
                # d'un bloc en sous-processus, ne montre rien avant la fin.
                frames = _partial_frames(job, sortie_app)
                try:
                    animated_video = _backend(model_key).process(
                        avatar_path=image_path, audio_path=audio_path,
                        output_path=str(travail / 'talkinghead.mp4'),
                        text=job.text_content, words=words, language=lang,
                        progress=lambda f: ctx.progress(25 + int(f * 55)),
                        on_frame=lambda jpeg, index: _publish_frame(frames, jpeg, index))
                finally:
                    frames.close()         # la face SORTIE prend le relais ; le JPEG partiel part
                _console(job.user_id, "Rendu TalkingHead terminé.", 'info')
            else:
                _console(job.user_id, "MuseTalk : synchronisation labiale en cours…", 'info')
                animated_video = _backend(model_key).process(
                    image_path=image_path,
                    audio_path=audio_path,
                    output_dir=str(travail),
                    bbox_shift=job.bbox_shift,
                )
                _console(job.user_id, "MuseTalk terminé.", 'info')

            ctx.progress(82 if avatar_3d else 78)
            if job.use_enhancer and avatar_3d:
                # CodeFormer restaure un visage PHOTO ; sur un rendu 3D il n'a rien à réparer.
                _console(job.user_id, "CodeFormer ignoré : sans objet sur un avatar 3D.", 'info')

            # ⚠ SORTIR le livrable AVANT la fin du bloc — après, `travail` n'existe plus.
            # Brique COMMUNE de nommage : famille FICHIER, la source étant l'AUDIO (c'est lui
            # que l'utilisateur reconnaît ; l'avatar n'est qu'un paramètre de rendu).
            # L'identifiant de job reste porté : `output/` est PLAT, et deux jobs partant du
            # même audio produiraient sinon le même nom — Django en renommerait un et le lien
            # affiché deviendrait faux.
            from wama.common.utils.output_naming import compose_output_name
            cible = sortie_app / compose_output_name(
                app='avatarizer', model=model_key.split(':', 1)[-1],
                source_name=audio_path, item_id=job_id, ext='.mp4')
            _shutil.move(str(animated_video), str(cible))

        ctx.progress(95)

        # ------------------------------------------------------------------
        # Le résultat
        # ------------------------------------------------------------------
        rel_path = os.path.relpath(cible, settings.MEDIA_ROOT).replace('\\', '/')
        fields = {'output_video': rel_path}

        # Durée du média (= durée audio) : métadonnée + taille pour le seeding ETA.
        _dur = 0.0
        try:
            import soundfile as _sf
            _info = _sf.info(audio_path)
            _dur = float(_info.frames) / float(_info.samplerate) if _info.samplerate else 0.0
        except Exception:
            _dur = 0.0
        if _dur > 0:
            fields['duration_seconds'] = _dur

        # Seeding ETA : la durée est celle de CE process (l'animation seule — l'amélioration
        # faciale apprend la sienne, `_enhance`) : clé du moteur, jamais celle de la qualité.
        from wama.common.services.output_process import generated
        return generated(
            [str(cible)],
            fields=fields,
            eta=(avatarizer_eta_key_size(job, duration=_dur, avatar_3d=avatar_3d)
                 if _dur > 0 else None),
            label=getattr(job, 'name', '') or f"avatar #{job_id}",
            console_success=f"Vidéo animée : {os.path.basename(str(cible))}",
            models=[model_key])
    except Exception:
        ctx.reset_progress()
        raise


def _partial_frames(job, output_dir):
    """L'aperçu « pendant » du rendu : brique commune `PartialFrames` (JPEG sous la sortie de
    l'app, URL versionnée, retiré en fin de rendu), au plus une image toutes les 2 s."""
    from wama.common.utils.preview_utils import PartialFrames
    return PartialFrames('avatarizer', job.id, Path(output_dir) / 'partials')


def _publish_frame(frames, jpeg, index):
    """Publie l'image rendue si la cadence le permet. Un aperçu raté ne fait JAMAIS échouer le
    rendu : il est best-effort (le rendu attend ce rappel, une exception le romprait)."""
    try:
        if frames.due():
            frames.publish({'animation': ('Animation', jpeg)}, index=index)
    except Exception as exc:
        logger.debug('[avatarizer] aperçu pendant non publié : %s', exc)


def _codeformer(job, animated_copy, ctx):
    """L'amélioration faciale d'une vidéo animée (CodeFormer), jouée sur la COPIE que la brique
    de sortie lui tend ; rend le chemin de la vidéo améliorée, rangée dans la sortie de l'app."""
    import shutil as _shutil
    import time as _time
    from wama.common.utils.output_naming import compose_output_name
    from wama.common.utils.work_dir import work_dir
    _console(job.user_id, "CodeFormer : amélioration faciale en cours…", 'info')
    ctx.progress(20)
    started = _time.time()
    with work_dir(f'avatarizer_face{job.id}') as travail:
        enhanced = _backend('avatarizer:codeformer').process(animated_copy, str(travail))
        target = Path(animated_copy).parent / compose_output_name(
            app='avatarizer', model='codeformer',
            source_name=job.audio_input.name if job.audio_input else animated_copy,
            item_id=job.id, ext='.mp4')
        _shutil.move(str(enhanced), str(target))
    if os.path.abspath(str(target)) != os.path.abspath(str(animated_copy)) \
            and os.path.isfile(animated_copy):
        os.remove(animated_copy)
    _console(job.user_id, f"CodeFormer terminé ({_time.time() - started:.0f} s).", 'info')
    return str(target)


def _enhance(job, ctx):
    """Process `enhance` (« Visage ») : par la glu COMMUNE du process de sortie
    (`output_process.output_step`) avec la transformation de l'app — demandée, la vidéo animée
    est gardée à côté (`native_outputs`) et l'améliorée devient le rendu ; retirée, la vidéo
    animée reprend sa place sans rien recalculer."""
    from wama.common.services.output_process import output_step
    step = output_step('output_video', domain='video', app_id='avatarizer',
                       console=lambda item, message: _console(item.user_id, message),
                       transform=lambda item: bool(item.use_enhancer), apply=_codeformer,
                       what='Amélioration faciale')
    result = step(job, ctx)
    duration = float(job.duration_seconds or 0)
    if job.use_enhancer and duration > 0:
        result['eta'] = enhance_eta_key_size(job, duration)
        result['models'] = ['avatarizer:codeformer']
    return result


#: La glu de chaque process du pipeline (`function_specs.PIPELINE`).
PROCESSES = {'speak': _speak, 'animate': _animate, 'enhance': _enhance}
