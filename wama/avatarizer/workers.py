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
import tempfile
import subprocess
from pathlib import Path

import requests
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


# TTS microservice
TTS_SERVICE_URL = getattr(settings, 'TTS_SERVICE_URL', 'http://localhost:8001')
TTS_TIMEOUT = 300


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
    """Appelle le microservice TTS et renvoie le chemin d'un WAV temporaire."""
    # Résolution du fichier WAV pour le clonage vocal (voix personnalisées cv_*)
    speaker_wav = None
    if job.voice_preset.startswith('cv_'):
        try:
            from wama.synthesizer.models import CustomVoice
            cv = CustomVoice.objects.get(pk=int(job.voice_preset[3:]))
            speaker_wav = cv.audio.path
        except Exception:
            pass  # Fallback : le service TTS utilisera sa voix par défaut

    payload = {
        'text': job.text_content,
        'model': job.tts_model,
        'language': job.language,
        'voice_preset': job.voice_preset,
        'speaker_wav': speaker_wav,
        'multi_speaker': False,
        'scene_description': '',
        'options': {},
    }
    try:
        resp = requests.post(
            f"{TTS_SERVICE_URL}/tts",
            json=payload,
            timeout=(5, TTS_TIMEOUT),
        )
        resp.raise_for_status()
    except requests.ConnectionError:
        raise RuntimeError(f"Service TTS inaccessible à {TTS_SERVICE_URL}")
    except requests.Timeout:
        raise RuntimeError(f"Service TTS : délai dépassé après {TTS_TIMEOUT}s")
    except requests.HTTPError as e:
        detail = ""
        try:
            detail_raw = e.response.json().get("detail", "")
            detail = str(detail_raw)
        except Exception:
            detail = e.response.text[:200] if e.response else ""
        raise RuntimeError(f"Erreur service TTS : {detail or str(e)}")

    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@shared_task(bind=True)
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
            _console(job.user_id, "Synthèse audio via service TTS…", 'info')
            tmp_audio_path = _call_tts_service(job)
            audio_path = tmp_audio_path
            _console(job.user_id, "Audio TTS généré.", 'info')
        else:
            if not job.audio_input:
                raise ValueError("Mode Standalone : aucun fichier audio fourni.")
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

        # Répertoire de sortie pour ce job
        job_output_dir = (
            Path(settings.MEDIA_ROOT) / 'avatarizer' / str(job.user_id) / 'output' / f"job_{job_id}"
        )
        job_output_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # Étape 3 : MuseTalk — synchronisation labiale
        # ------------------------------------------------------------------
        _console(job.user_id, "MuseTalk : synchronisation labiale en cours…", 'info')
        _set_progress(job, 40)

        musetalk_video = _musetalk_backend.process(
            image_path=image_path,
            audio_path=audio_path,
            output_dir=str(job_output_dir),
            bbox_shift=job.bbox_shift,
        )

        _set_progress(job, 80)
        _console(job.user_id, "MuseTalk terminé.", 'info')

        # ------------------------------------------------------------------
        # Étape 4 (optionnelle) : CodeFormer — amélioration faciale
        # ------------------------------------------------------------------
        final_video = musetalk_video
        if job.use_enhancer:
            _console(job.user_id, "CodeFormer : amélioration faciale en cours…", 'info')
            _set_progress(job, 85)
            final_video = _codeformer_backend.process(musetalk_video, str(job_output_dir))
            _console(job.user_id, "CodeFormer terminé.", 'info')

        _set_progress(job, 95)

        # ------------------------------------------------------------------
        # Étape 5 : sauvegarder le résultat
        # ------------------------------------------------------------------
        rel_path = os.path.relpath(final_video, settings.MEDIA_ROOT)
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
