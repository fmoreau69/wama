"""
DeepFilterNet 3 — la ligne du catalogue et ses FICHIERS, déclarés à côté de son moteur
(`audio_enhancer.DeepFilterNetBackend`) — patron de Phonon (`phonon_backend.PHONON_FILES`).

Module LÉGER à dessein : la découverte du catalogue le lit, et le module du moteur, lui, applique
au chargement le correctif de torchaudio (`audio_enhancer._patch_torchaudio_compat`), donc importe
torch — ce que la découverte n'a pas à payer.

La route installe ces fichiers (pilote `files`, ligne `enhancer:deepfilternet`) ; le moteur ne
lit que ce dossier et ne télécharge rien (2026-11-02). Avant, `init_df("DeepFilterNet3")` tirait
au premier usage l'archive de la BRANCHE `main` du dépôt (`df/enhance.py:270`) : hors catalogue,
jamais désinstallable. La version officielle n'est publiée qu'en ARCHIVE dans l'arbre du dépôt —
aucune version GitHub ne porte de poids, aucun miroir du Hub n'a ces octets (mesuré le
2026-10-31). L'origine est donc l'archive figée au COMMIT qui l'a modifiée en dernier
(2023-05-23, « models: Fix zip structure »), et chaque fichier un MEMBRE de cette archive.
"""
from pathlib import Path

DEEPFILTERNET_KEY = 'enhancer:deepfilternet'
DEEPFILTERNET_REPO = 'Rikorose/DeepFilterNet'
DEEPFILTERNET_REVISION = '82b0c7ad33fc756284104053817d1e855d8d8386'
#: L'archive au commit : 7 986 207 o, empreinte MESURÉE le 2026-11-02.
DEEPFILTERNET_ARCHIVE = 'models/DeepFilterNet3.zip'
DEEPFILTERNET_ARCHIVE_SHA256 = '49c52edc8947ae1f9bf50d81530beaf3a2c3245aeaf34b6f31ff535cd22284d2'


def _member(path, size, sha256):
    return {'path': path, 'size': size, 'sha256': sha256,
            'origin': {'source': 'github', 'repo': DEEPFILTERNET_REPO,
                       'revision': DEEPFILTERNET_REVISION, 'file': DEEPFILTERNET_ARCHIVE,
                       'archive_sha256': DEEPFILTERNET_ARCHIVE_SHA256, 'member': path}}


#: Tailles et empreintes MESURÉES le 2026-11-02 sur les membres de l'archive — identiques, octet
#: pour octet, aux fichiers que la librairie avait posés elle-même.
DEEPFILTERNET_FILES = [
    _member('DeepFilterNet3/config.ini', 2067,
            '415eb925d44990d938fb739f514aa3662c1ec0ea836cff044fa1291b82cb4290'),
    _member('DeepFilterNet3/checkpoints/model_120.ckpt.best', 8714073,
            '23b92884f63ccf54bb026014604625ab231657b6480df65db4095c4c171e6003'),
]


def deepfilternet_folder() -> Path:
    """`MODEL_PATHS['speech']['deepfilternet']` — et, sans Django, le même dossier sous
    `AI-models` (`tts_base.ai_models_dir`), jamais le `$HOME` (AGENTS.md)."""
    try:
        from django.conf import settings
        return Path(settings.MODEL_PATHS['speech']['deepfilternet'])
    except Exception:
        from .tts_base import ai_models_dir
        return ai_models_dir() / 'models' / 'speech' / 'deepfilternet'


def deepfilternet_model_dir() -> Path:
    """Le dossier que lit la librairie (`config.ini` + `checkpoints/`), DÉRIVÉ des fichiers
    déclarés — jamais un second nom écrit à côté."""
    return deepfilternet_folder() / Path(DEEPFILTERNET_FILES[0]['path']).parent


def deepfilternet_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(deepfilternet_folder(), DEEPFILTERNET_FILES)
