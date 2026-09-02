"""
WAMA Avatarizer - Celery Worker

Pipeline recommandé :
  1. (mode pipeline) Appel microservice TTS → WAV temporaire
  2. Résolution de l'image avatar (galerie partagée ou upload utilisateur)
  3. MuseTalk v1.5 : synchronisation labiale audio → vidéo
  4. (optionnel, mode qualité) CodeFormer : amélioration faciale
  5. Sauvegarde dans media/avatarizer/{user_id}/output/

Prérequis (voir setup_avatarizer.sh) :
  wama/avatarizer/musetalk/     ← git clone TMElyralab/MuseTalk
  wama/avatarizer/codeformer/   ← git clone sczhou/CodeFormer
  AI-models/models/lipsync/musetalk/    ← checkpoints MuseTalk
  AI-models/models/lipsync/codeformer/ ← checkpoints CodeFormer (via symlinks weights/)
"""

import os
import sys
import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections

from .models import AvatarJob
from wama.common.services.resource_governor import vram_reservation
from wama.avatarizer.backends.codeformer_backend import CodeFormerBackend
from wama.avatarizer.backends.musetalk_backend import MuseTalkBackend

# Backends hors process (contrat commun BaseModelBackend) — le worker orchestre, ils executent.
_musetalk_backend = MuseTalkBackend()
_codeformer_backend = CodeFormerBackend()
from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)


# Client du microservice TTS : brique COMMUNE (`common/tts/service_client.py`, 2026-08-28 —
# ce fichier portait le 2ᵉ des 4 exemplaires du même POST /tts, sans détection du 503
# « loading » : un service en démarrage sortait en RuntimeError au lieu d'un retry).
from wama.common.tts.service_client import TTSServiceLoadingError, tts_via_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_progress(job: AvatarJob, value: int) -> None:
    cache.set(f"avatarizer_progress_{job.id}", value, timeout=3600)
    AvatarJob.objects.filter(pk=job.id).update(progress=value)


def _console(user_id: int, message: str, level: str = 'info') -> None:
    try:
        push_console_line(user_id=user_id, line=message, app='avatarizer', level=level)
    except Exception:
        pass


def _call_tts_service(job: AvatarJob) -> str:
    """Synthétise `job.text_content` via la brique commune, renvoie un WAV temporaire.

    La voix est résolue par la brique CENTRALISÉE du synthesizer (`resolve_speaker_wav` :
    ua_ médiathèque / cv_ legacy / presets) — le bloc manuel qui vivait ici ne couvrait
    que `cv_*` : les voix de la médiathèque étaient silencieusement ignorées."""
    from wama.synthesizer.utils.voice_utils import resolve_speaker_wav
    speaker_wav = resolve_speaker_wav(job.voice_preset, user=job.user)
    return tts_via_service(
        job.text_content, job.tts_model,
        language=job.language, voice_preset=job.voice_preset,
        speaker_wav=speaker_wav,
    )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=60, default_retry_delay=10)
def generate_avatar(self, job_id: int):
    """
    Tâche Celery (queue gpu) : génère une vidéo avatar animée.

    Pipeline :
      1. (mode pipeline) Synthèse audio via microservice TTS
      2. Résolution de l'image avatar
      3. MuseTalk : synchronisation labiale
      4. (optionnel, use_enhancer=True) CodeFormer : amélioration faciale
      5. Sauvegarde du résultat
    """
    close_old_connections()

    try:
        job = AvatarJob.objects.get(id=job_id)
    except AvatarJob.DoesNotExist:
        logger.error(f"[avatarizer] AvatarJob #{job_id} introuvable")
        return

    # Garde anti-boucle-de-crash (brique COMMUNE) : message `redelivered` = worker mort
    # sans acquitter (freeze/panic machine) → ne PAS rejouer l'exécution qui l'a tué.
    from wama.common.utils.process_control import refuse_crash_redelivery
    if refuse_crash_redelivery(self, job, error_field='error_message'):
        logger.warning(f"[avatarizer] AvatarJob #{job_id}: reprise après crash refusée — relancer manuellement.")
        return

    job.status = 'RUNNING'
    job.task_id = self.request.id
    job.save(update_fields=['status', 'task_id'])
    _set_progress(job, 5)
    _console(job.user_id, f"Démarrage génération avatar #{job_id}", 'info')

    import time as _time
    _t0 = _time.time()  # chrono pour le seeding ETA

    tmp_audio_path = None
    try:
        # ------------------------------------------------------------------
        # Étape 1 : obtenir l'audio
        # ------------------------------------------------------------------
        if job.mode == 'pipeline':
            _set_progress(job, 10)
            # Choix AUTOMATIQUE du moteur TTS (brique commune `auto_model`, 2026-09-02) :
            # résolu AU LANCEMENT, sur le domaine que le schéma déclare pour les options
            # (`params.py` — le parc TTS par capacité, l'avatarizer n'en possède aucun).
            from wama.common.utils.auto_model import is_auto, read_quality_intent, resolve_model_choice
            if is_auto(job.tts_model):
                quality = read_quality_intent(getattr(job, 'quality_intent', None))
                job.tts_model = resolve_model_choice(
                    job.tts_model, app_id='avatarizer', quality_intent=quality,
                    fallback=AvatarJob._meta.get_field('tts_model').get_default())
                job.save(update_fields=['tts_model'])
                _console(job.user_id,
                         f"Choix automatique du moteur TTS → {job.get_tts_model_display()} "
                         f"(capacités + VRAM libre au lancement, curseur qualité {quality}/100)", 'info')
            _console(job.user_id, "Synthèse audio via service TTS…", 'info')
            tmp_audio_path = _call_tts_service(job)
            # L'audio généré est un ARTEFACT du job (l'entrée de l'étage animation), pas un
            # temporaire : persisté dans `audio_input`, il se vérifie, s'écoute et se rejoue.
            # Un re-run REGÉNÈRE (texte/voix ont pu changer) — l'ancien fichier est retiré
            # d'abord, via la garde de partage (un job dupliqué partage son fichier).
            from django.core.files import File
            from wama.common.utils.queue_duplication import safe_delete_file
            if job.audio_input:
                safe_delete_file(job, 'audio_input')
            with open(tmp_audio_path, 'rb') as fh:
                job.audio_input.save(f"tts_job{job_id}.wav", File(fh), save=True)
            audio_path = job.audio_input.path
            _console(job.user_id, "Audio TTS généré.", 'info')
        else:
            # Import par URL : télécharger l'audio si pas encore de fichier local
            # (mécanisme commun déclaratif ensure_local_input, spec WAMA_INGEST du modèle).
            from wama.common.utils.source_ingest import ensure_local_input
            ensure_local_input(job, console=lambda m: _console(job.user_id, m, 'info'))
            if not job.audio_input:
                raise ValueError("Mode Standalone : aucun fichier audio (ni URL) fourni.")
            audio_path = job.audio_input.path

        _set_progress(job, 20)

        # ------------------------------------------------------------------
        # Étape 2 : résoudre l'image avatar
        # ------------------------------------------------------------------
        if job.avatar_source == 'gallery':
            if not job.avatar_gallery_name:
                raise ValueError("Galerie : aucun avatar sélectionné.")
            gallery_dir = Path(settings.MEDIA_ROOT) / 'avatarizer' / 'gallery'
            image_path = str(gallery_dir / job.avatar_gallery_name)
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Avatar introuvable : {job.avatar_gallery_name}")
        else:
            if not job.avatar_upload:
                raise ValueError("Upload : aucune image avatar fournie.")
            image_path = job.avatar_upload.path

        _set_progress(job, 30)

        # Sortie de l'app : le livrable, et RIEN d'autre (règle `MEDIA_STORAGE_TIERING.md` —
        # `media/` ne contient que `<app>/<user>/input|output/` et `users/`).
        sortie_app = Path(settings.MEDIA_ROOT) / 'avatarizer' / str(job.user_id) / 'output'
        sortie_app.mkdir(parents=True, exist_ok=True)

        # Le travail se fait HORS de `media/` (2026-08-25). Avant, MuseTalk et CodeFormer
        # écrivaient dans `output/job_<id>/` : la vidéo finissait dans un sous-dossier `v15/`
        # (ou pire, DANS `codeformer_out/final_results/`), et les frames intermédiaires
        # restaient — 1715,7 Mo pour un job, 99,6 % du média de l'app.
        from wama.common.utils.work_dir import work_dir
        import shutil as _shutil

        # ------------------------------------------------------------------
        # Étape 3 : MuseTalk — synchronisation labiale
        # ------------------------------------------------------------------
        _console(job.user_id, "MuseTalk : synchronisation labiale en cours…", 'info')
        _set_progress(job, 40)

        with work_dir(f'avatarizer_job{job_id}') as travail:
            musetalk_video = _musetalk_backend.process(
                image_path=image_path,
                audio_path=audio_path,
                output_dir=str(travail),
                bbox_shift=job.bbox_shift,
            )

            _set_progress(job, 80)
            _console(job.user_id, "MuseTalk terminé.", 'info')

            # --------------------------------------------------------------
            # Étape 4 (optionnelle) : CodeFormer — amélioration faciale
            # --------------------------------------------------------------
            final_video = musetalk_video
            if job.use_enhancer:
                _console(job.user_id, "CodeFormer : amélioration faciale en cours…", 'info')
                _set_progress(job, 85)
                final_video = _codeformer_backend.process(musetalk_video, str(travail))
                _console(job.user_id, "CodeFormer terminé.", 'info')

            # ⚠ SORTIR le livrable AVANT la fin du bloc — après, `travail` n'existe plus.
            # Brique COMMUNE de nommage : famille FICHIER, la source étant l'AUDIO (c'est lui
            # que l'utilisateur reconnaît ; l'avatar n'est qu'un paramètre de rendu).
            # L'identifiant de job reste porté : `output/` est PLAT, et deux jobs partant du
            # même audio produiraient sinon le même nom — Django en renommerait un et le lien
            # affiché deviendrait faux.
            from wama.common.utils.output_naming import compose_output_name
            cible = sortie_app / compose_output_name(
                app='avatarizer', model=('codeformer' if job.use_enhancer else 'musetalk'),
                source_name=audio_path, item_id=job_id, ext='.mp4')
            _shutil.move(str(final_video), str(cible))

        _set_progress(job, 95)

        # ------------------------------------------------------------------
        # Étape 5 : sauvegarder le résultat
        # ------------------------------------------------------------------
        rel_path = os.path.relpath(cible, settings.MEDIA_ROOT)
        job.output_video.name = rel_path
        job.status = 'SUCCESS'

        # Durée du média (= durée audio) : métadonnée + taille pour le seeding ETA.
        _dur = 0.0
        try:
            import soundfile as _sf
            _info = _sf.info(audio_path)
            _dur = float(_info.frames) / float(_info.samplerate) if _info.samplerate else 0.0
        except Exception:
            _dur = 0.0
        if _dur > 0:
            job.duration_seconds = _dur
            job.save(update_fields=['output_video', 'status', 'duration_seconds'])
        else:
            job.save(update_fields=['output_video', 'status'])

        _set_progress(job, 100)
        _console(job.user_id, f"Vidéo générée : {os.path.basename(final_video)}", 'info')

        # Seeding ETA : lip-sync → temps ∝ durée vidéo ; clé par qualité (CodeFormer ≫ rapide)
        try:
            from wama.model_manager.services.eta_estimator import record_run
            record_run(f'avatarizer:{job.quality_mode}', size=_dur, unit='video_sec',
                       process_seconds=_time.time() - _t0, load_seconds=None)
        except Exception:
            pass
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(job, 'user', None), 'Avatarizer',
                       getattr(job, 'name', '') or f"avatar #{job_id}", True)
        except Exception:
            pass

    except TTSServiceLoadingError as e:
        # Service TTS en démarrage — libérer le worker GPU et réessayer (même politique
        # que synthesize_voice : 60 × 10 s, puis échec franc).
        retry_num = self.request.retries + 1
        wait_msg = f"Service TTS en chargement, nouvelle tentative dans 10s ({retry_num}/60)..."
        logger.info(f"[avatarizer] Job #{job_id}: {wait_msg}")
        AvatarJob.objects.filter(pk=job_id).update(error_message=wait_msg)
        _console(job.user_id, wait_msg, 'warning')
        try:
            raise self.retry(exc=e, countdown=10)
        except self.MaxRetriesExceededError:
            AvatarJob.objects.filter(pk=job_id).update(
                status='FAILURE',
                error_message="Service TTS non disponible après 10 minutes d'attente (60 tentatives)",
            )
            _set_progress(job, 0)
            _console(job.user_id, "Erreur : service TTS non disponible après 10 minutes", 'error')

    except Exception as e:
        logger.error(f"[avatarizer] Job #{job_id} échoué : {e}", exc_info=True)
        _console(job.user_id, f"Erreur : {e}", 'error')
        AvatarJob.objects.filter(pk=job_id).update(
            status='FAILURE',
            error_message=str(e),
        )
        _set_progress(job, 0)
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(job, 'user', None), 'Avatarizer',
                       getattr(job, 'name', '') or f"avatar #{job_id}", False, detail=str(e))
        except Exception:
            pass
    finally:
        if tmp_audio_path and os.path.exists(tmp_audio_path):
            try:
                os.unlink(tmp_audio_path)
            except Exception:
                pass
