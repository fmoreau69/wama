"""
Phonon (Gradium) — synthèse vocale 24 kHz sur le PROCESSEUR, en flux (2026-10-28, Fabien :
« mesure-le contre Kokoro […] on l'ajoute par la route à l'assistant et au synthesizer s'il est
bon »). Construit sur Pocket TTS (Kyutai) et le codec Mimi ; 40 M de paramètres, poids quantifiés
en 8 bits (`model.q8.gguf`, 74,6 Mo). Runtime : `ptts` (Rust, sans PyTorch), librairie installée par
la route (`manifests/libraries/ptts.json`).

CE QUE CE MODULE DÉCLARE : la ligne du catalogue et ses FICHIERS — le modèle français à un commit
figé, et quatre voix françaises du catalogue public de Gradium, rangées sous leur prénom dans
`voices/` (`ptts` y trouve une voix par son nom de fichier, sans consulter son catalogue en ligne).
Le pilote `files` les installe avec la clé Hugging Face de la personne (dépôt à accès contrôlé :
conditions acceptées sur le Hub) ; `ptts` lit ce dossier LOCAL et ne télécharge rien.

⚠ Licence des poids : CC BY-NC 4.0 (usage non commercial — celui d'un laboratoire public). Le
runtime est MIT / Apache-2.0.
"""
from pathlib import Path

HF_REPO = 'gradium/phonon-40m-fr'
#: Commit du dépôt au 2026-10-28.
HF_REVISION = 'd91086970206b88efd2c88ca971d0628b5968f0f'
VOICES_REPO = 'gradium/phonon-voices'
VOICES_REVISION = '0ee17205f254b5abc43b266c8a0f215565c352f7'
MODEL_KEY = f'huggingface:{HF_REPO}'


def _model_file(name, size, sha256):
    return {'path': name, 'size': size, 'sha256': sha256,
            'origin': {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION, 'file': name}}


def _voice(name, voice_id, sha256):
    return {'path': f'voices/{name}.safetensors', 'size': 256136, 'sha256': sha256,
            'origin': {'source': 'huggingface', 'repo': VOICES_REPO, 'revision': VOICES_REVISION,
                       'file': f'voices/{voice_id}.safetensors'}}


#: Tailles et empreintes MESURÉES le 2026-10-28 sur les fichiers que sert le Hub (les empreintes
#: LFS publiées, recalculées ; `config.json` et les deux tokenizers, hors LFS, calculées).
PHONON_FILES = [
    _model_file('config.json', 4634, '57a441f60dfa379692f31e6c47ecbddabb92b602c2b35fc39a897e6d315b6e60'),
    _model_file('tokenizer.json', 277749, 'a5e8c6060bf927ed367314f21355148fdf4acff6fadb94e49c86bc7182449433'),
    _model_file('tokenizer.model', 65303, '6ff32b815a8325c2989b1b140794cb18ec4ffabda8fc80df955fa336cd58b162'),
    _model_file('model.q8.gguf', 74553568, 'e56a68900c0b3883a81e66f2506167f2e48ba7bdd3ce36b5195e24009d484dcb'),
    _model_file('default-voice.safetensors', 256136,
                'a8c97074fdb4044fc8da2873bdccd8b2a64beeedab859d241d5fc11c0c400aad'),
    # Deux voix de femme, deux d'homme (catalogue `voices.jsonl` du dépôt des voix, locale fr-fr).
    _voice('Noemie', 'FXxJ9mANRq6BCTX5', '9f575447f6908727214c2a855e0e33a7c316e9360a0d8b66c6ccaa8f6e15dade'),
    _voice('Tiphaine', '0fvH6XAKvA748v2v', '5646677e9cf4a517e8cc316f94a34e18fa987e224925d916d6fe13396579b95b'),
    _voice('Augustin', 'Tek4tJXiX6_yvXq7', '0106f9a0d53685471695a76827f7912e6c890f21fea10b5e5160379da38ffe5b'),
    _voice('Lucien', 'LIv4NaG8ay4Mhqtd', '4f7f904c976c0b493e9d42654dc81d4f9e686b986fbb3a7d511a7dcc41c7dea6'),
]


def model_folder() -> Path:
    from django.conf import settings
    return Path(settings.MODEL_PATHS['speech']['phonon'])


def model_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(model_folder(), PHONON_FILES)
