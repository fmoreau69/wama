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
import shutil
import logging
import tempfile
import subprocess
from pathlib import Path

import yaml
import requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections

from .models import AvatarJob
from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)

# Répertoires des librairies (clonées dans l'app)
APP_DIR        = Path(__file__).parent
MUSETALK_DIR   = APP_DIR / 'musetalk'
CODEFORMER_DIR = APP_DIR / 'codeformer'

# Checkpoints dans AI-models/ (organisés par type, pas par application)
MUSETALK_MODELS_DIR   = settings.BASE_DIR / 'AI-models' / 'models' / 'lipsync' / 'musetalk'
CODEFORMER_MODELS_DIR = settings.BASE_DIR / 'AI-models' / 'models' / 'lipsync' / 'codeformer'

# Sous-dossiers weights/ de CodeFormer redirigés vers AI-models/ via symlinks
CODEFORMER_WEIGHTS_SUBDIRS = ['CodeFormer', 'facelib', 'realesrgan']

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


def _build_musetalk_env() -> dict:
    """Construit les variables d'environnement pour le subprocess MuseTalk."""
    env = os.environ.copy()
    # Ajouter musetalk/ au PYTHONPATH pour ses imports internes
    existing = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f"{MUSETALK_DIR}:{existing}" if existing else str(MUSETALK_DIR)
    # Pointer vers les checkpoints si disponibles
    if MUSETALK_MODELS_DIR.exists():
        env['MUSETALK_MODELS_DIR'] = str(MUSETALK_MODELS_DIR)
    return env


def _run_musetalk(image_path: str, audio_path: str, output_dir: str, bbox_shift: int = 0) -> str:
    """
    Exécute MuseTalk via subprocess.

    MuseTalk écrit ses résultats dans <result_dir>/v15/*.mp4.
    On passe --result_dir pointant vers le dossier du job pour éviter tout
    déplacement de fichier et pour que les runs concurrents ne se mélangent pas.

    Retourne le chemin de la vidéo MP4 générée.
    """
    if not MUSETALK_DIR.exists():
        raise RuntimeError(
            f"MuseTalk introuvable dans {MUSETALK_DIR}.\n"
            "Lancez d'abord : bash wama/avatarizer/setup_avatarizer.sh"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Config YAML minimal (output_vid_dir ignoré par inference.py ; on utilise --result_dir)
    config = {
        'task_0': {
            'video_path': str(Path(image_path).resolve()),
            'audio_path': str(Path(audio_path).resolve()),
            'bbox_shift': int(bbox_shift),
        }
    }
    config_path = output_dir / 'musetalk_config.yaml'
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"[avatarizer] MuseTalk config : {config_path}")

    result = subprocess.run(
        [
            sys.executable, '-W', 'ignore::UserWarning',
            '-m', 'scripts.inference',
            '--inference_config', str(config_path),
            '--version', 'v15',
            '--unet_model_path', './models/musetalkV15/unet.pth',
            '--unet_config', './models/musetalkV15/musetalk.json',
            '--result_dir', str(output_dir),   # MuseTalk écrit dans <output_dir>/v15/
        ],
        cwd=str(MUSETALK_DIR),
        env=_build_musetalk_env(),
        capture_output=True,
        text=True,
        timeout=600,
    )

    # Toujours capturer la sortie pour le diagnostic
    musetalk_output = ((result.stdout or '') + (result.stderr or '')).strip()

    if result.returncode != 0:
        raise RuntimeError(
            f"MuseTalk a échoué (code {result.returncode}) :\n{musetalk_output[-3000:]}"
        )

    # MuseTalk écrit dans <output_dir>/v15/<image_stem>_<audio_stem>.mp4
    # (inference.py utilise output_basename = f"{input_basename}_{audio_basename}")
    v15_dir = output_dir / 'v15'
    if v15_dir.exists():
        # Exclure les fichiers temp_ (vidéo sans audio, supprimés normalement)
        mp4_files = sorted(
            [p for p in v15_dir.glob('*.mp4') if not p.name.startswith('temp_')],
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if mp4_files:
            return str(mp4_files[0])

    # Fallback : MP4 directement dans output_dir
    mp4_files = sorted(
        output_dir.glob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if mp4_files:
        return str(mp4_files[0])

    # Rien trouvé — analyser la sortie pour un message utilisateur clair
    if 'NO FACE DETECTED' in musetalk_output or 'division by zero' in musetalk_output:
        raise RuntimeError(
            "Aucun visage détecté dans l'image avatar.\n"
            "MuseTalk requiert une photo de face avec un visage bien visible et centré.\n"
            "Conseil : utilisez un portrait frontal, sans lunettes de soleil ni masque."
        )
    diagnostic = musetalk_output[-2000:] if musetalk_output else "(aucune sortie capturée)"
    raise RuntimeError(
        f"MuseTalk n'a produit aucun fichier MP4.\n"
        f"Sortie MuseTalk :\n{diagnostic}"
    )


def _ensure_codeformer_weights_in_ai_models() -> None:
    """
    Redirige codeformer/weights/<subdir>/ vers AI-models/models/lipsync/codeformer/<subdir>/
    via des symlinks, en déplaçant les fichiers déjà téléchargés si nécessaire.

    Appelé une seule fois au premier lancement de CodeFormer — idempotent.
    """
    weights_dir = CODEFORMER_DIR / 'weights'
    if not weights_dir.exists():
        return

    CODEFORMER_MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for subdir in CODEFORMER_WEIGHTS_SUBDIRS:
        src = weights_dir / subdir          # ex: codeformer/weights/CodeFormer/
        dst = CODEFORMER_MODELS_DIR / subdir  # ex: AI-models/.../codeformer/CodeFormer/
        dst.mkdir(parents=True, exist_ok=True)

        if src.is_symlink():
            continue  # déjà redirigé

        if src.is_dir():
            # Déplacer les .pth existants vers AI-models/
            for f in src.iterdir():
                if f.name.startswith('.'):
                    continue  # .gitkeep etc.
                target = dst / f.name
                if not target.exists():
                    shutil.move(str(f), str(target))
                    logger.info(f"[avatarizer] CodeFormer weights déplacé : {f.name} → AI-models/")
            # Supprimer le répertoire vide et créer un symlink
            try:
                src.rmdir()
            except OSError:
                # Non vide (gitkeep) — supprimer les gitkeep puis réessayer
                for f in src.iterdir():
                    f.unlink()
                src.rmdir()
            src.symlink_to(dst.resolve())
            logger.info(f"[avatarizer] CodeFormer weights symlink créé : {src} → {dst}")
        else:
            src.symlink_to(dst.resolve())


def _run_codeformer(video_path: str, output_dir: str) -> str:
    """
    Améliore la qualité faciale de la vidéo avec CodeFormer.
    Si CodeFormer n'est pas installé ou échoue, renvoie le chemin d'origine.
    """
    if not CODEFORMER_DIR.exists():
        logger.warning(f"[avatarizer] CodeFormer absent ({CODEFORMER_DIR}) — amélioration ignorée.")
        return video_path

    _ensure_codeformer_weights_in_ai_models()

    cf_out = Path(output_dir) / 'codeformer_out'
    cf_out.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                sys.executable, 'inference_codeformer.py',
                '-i', str(Path(video_path).resolve()),
                '-o', str(cf_out.resolve()),
                '--face_upsample',
                '-w', '0.7',   # fidelity weight : 0 = amélioration max, 1 = fidélité max
                '-s', '2',     # upscale ×2
            ],
            cwd=str(CODEFORMER_DIR),
            capture_output=True,
            text=True,
            timeout=1800,   # 30 min — chargement modèle + traitement vidéo longue
        )
    except subprocess.TimeoutExpired:
        logger.warning("[avatarizer] CodeFormer timeout (30 min) — on garde la vidéo MuseTalk.")
        return video_path

    if result.returncode != 0:
        logger.warning(f"[avatarizer] CodeFormer échoué — on garde la vidéo MuseTalk.\n{result.stderr[-300:]}")
        return video_path

    # CodeFormer écrit dans results/final_results/ ou directement dans -o
    video_name = Path(video_path).name
    for candidate in [
        cf_out / 'final_results' / video_name,
        cf_out / video_name,
    ]:
        if candidate.exists():
            return str(candidate)

    mp4_files = sorted(cf_out.rglob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(mp4_files[0]) if mp4_files else video_path


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

    job.status = 'RUNNING'
    job.task_id = self.request.id
    job.save(update_fields=['status', 'task_id'])
    _set_progress(job, 5)
    _console(job.user_id, f"Démarrage génération avatar #{job_id}", 'info')

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

        musetalk_video = _run_musetalk(
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
            final_video = _run_codeformer(musetalk_video, str(job_output_dir))
            _console(job.user_id, "CodeFormer terminé.", 'info')

        _set_progress(job, 95)

        # ------------------------------------------------------------------
        # Étape 5 : sauvegarder le résultat
        # ------------------------------------------------------------------
        rel_path = os.path.relpath(final_video, settings.MEDIA_ROOT)
        job.output_video.name = rel_path
        job.status = 'SUCCESS'
        job.save(update_fields=['output_video', 'status'])
        _set_progress(job, 100)
        _console(job.user_id, f"Vidéo générée : {os.path.basename(final_video)}", 'info')

    except Exception as e:
        logger.error(f"[avatarizer] Job #{job_id} échoué : {e}", exc_info=True)
        _console(job.user_id, f"Erreur : {e}", 'error')
        AvatarJob.objects.filter(pk=job_id).update(
            status='FAILURE',
            error_message=str(e),
        )
        _set_progress(job, 0)
    finally:
        if tmp_audio_path and os.path.exists(tmp_audio_path):
            try:
                os.unlink(tmp_audio_path)
            except Exception:
                pass
