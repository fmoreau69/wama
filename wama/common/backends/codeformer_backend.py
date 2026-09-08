"""
CodeFormer Backend — restauration de visage (option qualite superieure)

Backend hors process : le modele tourne dans un SOUS-PROCESSUS (script du depot vendore),
pas dans l'interpreteur Celery — load()/unload() ne retiennent donc rien en memoire ;
la VRAM est declaree au gouverneur pour la duree de process() (vram_reservation).
Code deplace verbatim depuis workers.py (port F4, 2026-07-31) : le worker orchestre,
le backend execute.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from wama.common.backends.base import BaseModelBackend
from wama.common.services.resource_governor import vram_reservation

# ── Étape 2 (2026-09-06) : plus d'import du `model_config` de l'app ──────────────────────
# Ces valeurs venaient de `wama.avatarizer.utils.model_config`, ce qui interdisait au backend
# de rejoindre le substrat transversal (le commun ne peut pas importer une app). Elles sont
# maintenant lues à leur SOURCE, et chacune n'a que la portée qu'elle mérite :
#
#   • le dossier de POIDS vient de `settings.MODEL_PATHS` — déjà commun, l'app ne faisait
#     que le ré-exporter ;
#   • la VRAM et la liste des sous-dossiers sont des DÉCLARATIONS : elles descendent sur la
#     classe, à côté d'`ENGINE` (la VRAM y avait déjà sa place, `recommended_vram_gb`) ;
#   • ⚠ le dossier de CODE VENDORISÉ reste app-local, et c'est irréductible : MuseTalk et
#     CodeFormer sont vendorisés SOUS `wama/avatarizer/`, et le backend en a besoin pour le
#     `PYTHONPATH` du sous-processus. Il est donc DÉCLARÉ (une chaîne, résolue tardivement)
#     plutôt qu'importé — le jour où le code vendorisé déménage, une seule ligne change.
#     *Le blocage d'avatarizer n'était pas `model_config`, c'était l'emplacement du vendor.*
from pathlib import Path as _Path

from django.conf import settings


CODEFORMER_MODELS_DIR = _Path(settings.MODEL_PATHS.get('lipsync', {}).get(
    'codeformer', settings.AI_MODELS_DIR / 'models' / 'lipsync' / 'codeformer'))
#: Sous-dossiers de poids attendus — déclaration, pas configuration d'app.
CODEFORMER_WEIGHTS_SUBDIRS = ['CodeFormer', 'facelib', 'realesrgan']
CODEFORMER_VRAM_GB = 3.0
#: Le MOTEUR vendorisé se trouve sous la racine DÉCLARÉE (`settings.BACKEND_VENDOR_DIR`),
#: dans le dossier qui porte son nom — celui d'`ENGINE`. Plus aucun paquet Python n'est
#: résolu pour localiser un dossier jamais importé (2026-09-07).
CODEFORMER_DIR = _Path(settings.BACKEND_VENDOR_DIR) / 'codeformer'

logger = logging.getLogger(__name__)


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

    # ⚠ Les intermédiaires NE VONT PLUS dans `output_dir` (2026-08-25). CodeFormer y déversait
    # `cropped_faces/`, `restored_faces/` et `final_results/` — 687 PNG chacune, jamais
    # nettoyées : `job_11` pesait 1715,7 Mo pour une vidéo de 0,70 Mo, soit 99,6 % du média de
    # l'app. Ils vivent désormais dans un dossier de travail jetable (brique commune), et SEUL
    # le livrable est remonté dans `output_dir`.
    from wama.common.utils.work_dir import work_dir

    with work_dir('avatarizer_codeformer') as travail:
        produit = _codeformer_dans(video_path, travail)
        if produit is None:
            return video_path
        # Sortir le livrable AVANT la fin du bloc — après, le dossier n'existe plus.
        final = Path(output_dir) / Path(produit).name
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produit), str(final))
        return str(final)


def _codeformer_dans(video_path: str, travail: Path):
    """Lance CodeFormer dans `travail`. Rend le chemin de la vidéo produite, ou None si échec.

    Séparé de `_run_codeformer` pour que la gestion du dossier jetable reste lisible : ici on ne
    s'occupe QUE du sous-processus et de la localisation de son résultat.
    """
    cf_out = travail / 'codeformer_out'
    cf_out.mkdir(parents=True, exist_ok=True)

    try:
        # Même raison que MuseTalk : sous-processus GPU, empreinte déclarée le temps de l'appel.
        with vram_reservation(f"avatarizer.codeformer:{os.getpid()}", CODEFORMER_VRAM_GB):
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
        return None

    if result.returncode != 0:
        logger.warning(f"[avatarizer] CodeFormer échoué — on garde la vidéo MuseTalk.\n{result.stderr[-300:]}")
        return None

    # CodeFormer écrit dans results/final_results/ ou directement dans -o
    video_name = Path(video_path).name
    for candidate in [
        cf_out / 'final_results' / video_name,
        cf_out / video_name,
    ]:
        if candidate.exists():
            return candidate

    mp4_files = sorted(cf_out.rglob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True)
    return mp4_files[0] if mp4_files else None


class CodeFormerBackend(BaseModelBackend):
    """Contrat commun autour du sous-processus CodeFormer (inference_codeformer.py vendore)."""

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'codeformer'
    # ⚠ `realesrgan` RETIRÉ le 2026-09-04 (constat Fabien « codeformer est installé ») :
    # ce n'est pas un paquet pip requis ici. Le code vendorisé importe `RealESRGANer` depuis
    # **basicsr** (`basicsr.utils.realesrgan_utils`), et l'upscaler d'arrière-plan est de
    # toute façon OPTIONNEL (`--bg_upsampler` vaut 'None' par défaut). Sur-déclarer un
    # paquet, c'est se griser soi-même : le backend était annoncé « moteur non installé »
    # alors qu'il fonctionne — un faux négatif du même genre que les critères de grille
    # recalés ce jour.
    REQUIRED_PACKAGES = ['basicsr', 'facexlib']
    recommended_vram_gb = CODEFORMER_VRAM_GB
    description = "CodeFormer — restauration/nettete du visage apres MuseTalk (use_enhancer)."
    _warm = False

    @classmethod
    def is_available(cls) -> bool:
        return (CODEFORMER_DIR / 'inference_codeformer.py').exists()

    def load(self, model=None) -> bool:
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        self._warm = False

    def process(self, *args, **kwargs):
        return _run_codeformer(*args, **kwargs)
