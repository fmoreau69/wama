"""
Les moteurs de restauration audio (`audio_enhancer` : Resemble Enhance, DeepFilterNet 3) — leurs
lignes du catalogue et leurs FICHIERS, déclarés à côté des moteurs — patron de Phonon
(`phonon_backend.PHONON_FILES`) et de Bark (`bark_backend.BARK_FILES`).

Module LÉGER à dessein : la découverte du catalogue le lit, et le module des moteurs, lui, applique
au chargement le correctif de torchaudio (`audio_enhancer._patch_torchaudio_compat`), donc importe
torch — ce que la découverte n'a pas à payer.

La route installe ces fichiers (pilote `files`) ; les moteurs ne lisent que leur dossier et ne
téléchargent rien. Né le 2026-11-02 pour DeepFilterNet 3 (`deepfilternet_files.py`, R203), étendu
le même jour à Resemble Enhance (R208) et renommé pour porter les deux — un seul lieu de déclaration
pour les moteurs d'un même module.
"""
from pathlib import Path

DEEPFILTERNET_KEY = 'enhancer:deepfilternet'
RESEMBLE_KEY = 'enhancer:resemble'

# ── DeepFilterNet 3 ──────────────────────────────────────────────────────────────────────────
# Avant, `init_df("DeepFilterNet3")` tirait au premier usage l'archive de la BRANCHE `main` du dépôt
# (`df/enhance.py:270`) : hors catalogue, jamais désinstallable. La version officielle n'est publiée
# qu'en ARCHIVE dans l'arbre du dépôt — aucune version GitHub ne porte de poids, aucun miroir du Hub
# n'a ces octets (mesuré le 2026-10-31). L'origine est donc l'archive figée au COMMIT qui l'a
# modifiée en dernier (2023-05-23, « models: Fix zip structure »), et chaque fichier un MEMBRE de
# cette archive.
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

# ── Resemble Enhance ─────────────────────────────────────────────────────────────────────────
# Avant, `resemble_enhance.enhancer.inference.load_enhancer(run_dir=None)` appelait `download()`
# (`enhancer/download.py`) à CHAQUE premier chargement d'un processus : `git clone` du dépôt du Hub
# DANS le paquet installé (`site-packages/resemble_enhance/model_repo`), puis `git pull` et
# `git lfs pull` les fois suivantes — dépôt entier (trois vidéos de démonstration comprises), hors
# catalogue, jamais désinstallable, et suivant la BRANCHE. Le moteur ne lit que deux fichiers
# (`HParams.load(run_dir)`, `run_dir/ds/G/default/mp_rank_00_model_states.pt`) ; le débruiteur est
# un sous-module de l'améliorateur (`hparams.yaml` ne nomme aucun `denoiser_run_dir`), ses poids
# sont dans le même point de contrôle.
RESEMBLE_REPO = 'ResembleAI/resemble-enhance'
#: Le dernier commit du dépôt (2023-12-21) — celui du clone que la librairie avait posé.
RESEMBLE_REVISION = '4e3510ce4a8391159f665903544c5150bee7b2cb'
#: Tailles et empreintes PUBLIÉES par le Hub à ce commit (LFS pour le point de contrôle) — et
#: MESURÉES le 2026-11-02 sur le clone local : identiques.
RESEMBLE_FILES = [
    {'path': f'enhancer_stage2/{name}', 'size': size, 'sha256': sha256,
     'origin': {'source': 'huggingface', 'repo': RESEMBLE_REPO, 'revision': RESEMBLE_REVISION,
                'file': f'enhancer_stage2/{name}'}}
    for name, size, sha256 in (
        ('hparams.yaml', 717, '80c3f15bc5a5b2cacf2c698699a0f6599d62911c0d53e1d6dee895c0d7cbaeac'),
        ('ds/G/default/mp_rank_00_model_states.pt', 713176232,
         'f9d035f318de3e6d919bc70cf7ad7d32b4fe92ec5cbe0b30029a27f5db07d9d6'),
    )
]

#: Clé du catalogue → (clé de `MODEL_PATHS['speech']`, nom du dossier sans Django, fichiers).
#: Le PREMIER fichier déclaré est celui du dossier que lit la librairie.
AUDIO_ENGINE_FILES = {
    DEEPFILTERNET_KEY: ('deepfilternet', 'deepfilternet', DEEPFILTERNET_FILES),
    RESEMBLE_KEY: ('resemble_enhance', 'resemble-enhance', RESEMBLE_FILES),
}


def engine_folder(key: str) -> Path:
    """`MODEL_PATHS['speech'][…]` du moteur — et, sans Django, le même dossier sous `AI-models`
    (`tts_base.ai_models_dir`), jamais le `$HOME` (AGENTS.md)."""
    from .tts_base import speech_folder
    setting, dirname, _files = AUDIO_ENGINE_FILES[key]
    return speech_folder(setting, dirname)


def engine_files(key: str) -> list:
    return AUDIO_ENGINE_FILES[key][2]


def engine_model_dir(key: str) -> Path:
    """Le dossier que lit la librairie, DÉRIVÉ des fichiers déclarés (celui du premier) — jamais un
    second nom écrit à côté."""
    return engine_folder(key) / Path(engine_files(key)[0]['path']).parent


def engine_installed(key: str) -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(engine_folder(key), engine_files(key))
