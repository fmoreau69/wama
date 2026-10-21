"""
Backend Bark (Suno) — TTS expressif à presets, sans clonage libre.

Le mapping preset → locuteur Bark vit ICI (vocabulaire du moteur), la résolution
preset → fichier WAV de référence reste dans le service (politique média).
"""
from __future__ import annotations

import logging

import numpy as np

from wama.common.tts.constants import BARK_LANG_DEFAULTS

from .tts_base import CATALOG_KEYS, TTSBackend, speech_dir, write_wav_int16

logger = logging.getLogger(__name__)

#: Les poids que `preload_models()` lit (forme ORIGINALE suno, suffixes `_2` : les petits modèles
#: sont écartés, `load`) — DÉCLARÉS le 2026-10-18 pour que la ROUTE les installe (pilote `files`) :
#: la librairie les tirait elle-même au premier chargement. Taille et empreinte PUBLIÉES par le Hub
#: (LFS) au commit figé ci-dessous.
BARK_REPO = 'suno/bark'
BARK_REVISION = '70a8a7d34168586dc5d028fa9666aceade177992'
#: Sous-dossiers du dossier du moteur : là où la librairie lisait ses poids quand le backend posait
#: `XDG_CACHE_HOME` = ce dossier (`<XDG>/suno/bark_v0`, `<XDG>/torch/hub/checkpoints`) — gardés
#: tels quels, les fichiers déjà sur disque restent à leur place.
BARK_CHECKPOINTS = 'suno/bark_v0'
ENCODEC_CHECKPOINTS = 'torch/hub/checkpoints'
#: Le codec audio qu'`preload_models()` charge en dernier (`EncodecModel.encodec_model_24khz()`),
#: tiré par `torch.hub` du serveur de ses auteurs — DÉCLARÉ le 2026-10-19, origine
#: `external_sources['encodec']`. Le nom porte le début de l'empreinte (convention torch.hub,
#: vérifiée par la librairie à la lecture).
ENCODEC_CHECKPOINT = 'encodec_24khz-d7cc33bc.th'
BARK_FILES = [
    {'path': f'{BARK_CHECKPOINTS}/{name}', 'size': size, 'sha256': sha256,
     'origin': {'source': 'huggingface', 'repo': BARK_REPO, 'revision': BARK_REVISION, 'file': name}}
    for name, size, sha256 in (
        ('text_2.pt', 5353258741, 'ccdedd35373bc3a16845f1f1452c5c96926f5cbccab01e824f7f15add2c16a35'),
        ('coarse_2.pt', 3934534533, '286abc253d4d7f4d148325df07585f7ca4fca36ce40577a1ddd744a8b35e4388'),
        ('fine_2.pt', 3741740229, '799c87afab4b01537094c63ea231f2c42c9c07aeb16773690540ad251a6d8fab'),
    )
] + [
    {'path': f'{ENCODEC_CHECKPOINTS}/{ENCODEC_CHECKPOINT}', 'size': 93171529,
     'sha256': 'd7cc33bcf1aad7f2dad9836f36431530744abeace3ca033005e3290ed4fa47bf',
     'origin': {'source': 'encodec', 'file': ENCODEC_CHECKPOINT}},
]


def bark_weights_dir():
    """Le dossier d'installation de Bark (celui du moteur) : ses trois poids sous
    `BARK_CHECKPOINTS`, le codec sous `ENCODEC_CHECKPOINTS`."""
    return speech_dir('bark')


def bark_speaker_for(voice_preset: str, language: str) -> str:
    """Preset UI → prompt locuteur Bark (`v2/<lang>_speaker_<n>`)."""
    if voice_preset.startswith("bark_v2_"):
        parts = voice_preset.replace("bark_v2_", "").split("_")
        if len(parts) == 2:
            return f"v2/{parts[0]}_speaker_{parts[1]}"
    return BARK_LANG_DEFAULTS.get(language, "v2/en_speaker_0")


class BarkBackend(TTSBackend):
    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'bark'
    engine = "bark"
    description = "Bark (Suno) — TTS expressif (rires, hésitations, bruitages)."

    supports_cloning = False   # presets de locuteurs, pas de clonage libre (aligné sur le catalogue)
    #: Il TIRE ses deux étages (texte → jetons sémantiques, puis forme d'onde) : 0,7, le défaut
    #: de `bark.generate_audio` pour `text_temp` comme pour `waveform_temp`. La card règle les deux.
    default_temperature = 0.7

    REQUIRED_PACKAGES = ['bark', 'scipy']
    # ⚠ `pip install bark` installe un paquet HOMONYME sans rapport — l'installation
    # passe par le dépôt Suno (même précédent que vibevoice) : rien d'automatique.
    PIP_PACKAGES = []

    recommended_vram_gb = 5.0

    def __init__(self):
        super().__init__()
        self._funcs = None   # {"generate_audio": ..., "SAMPLE_RATE": ...}

    @property
    def is_loaded(self) -> bool:
        return self._funcs is not None

    def load(self, model: str | None = None) -> bool:
        if self._funcs is not None:
            return True

        # Les poids LÀ OÙ LA ROUTE LES INSTALLE (`BARK_FILES`), dits à la librairie par SES
        # attributs — jamais par l'environnement. Jusqu'au 2026-10-19, `load` posait
        # `XDG_CACHE_HOME` : une variable GÉNÉRIQUE, lue par toute librairie qui suit XDG (le
        # codec de torch.hub compris), mutée pour tout le processus du service de voix.
        from bark import SAMPLE_RATE, generate_audio, preload_models
        from bark import generation
        from encodec import EncodecModel

        root = bark_weights_dir()
        generation.CACHE_DIR = str(root / BARK_CHECKPOINTS)
        generation.USE_SMALL_MODELS = False
        # Le codec depuis son fichier déclaré : `preload_models` garde un modèle déjà présent
        # (`models['codec']`) et ne le tire plus par torch.hub.
        codec = EncodecModel.encodec_model_24khz(repository=root / ENCODEC_CHECKPOINTS)
        codec.set_target_bandwidth(6.0)
        generation.models['codec'] = codec

        logger.info(f"[Bark] préchargement des modèles depuis {root}…")
        preload_models()

        self._funcs = {"generate_audio": generate_audio, "SAMPLE_RATE": SAMPLE_RATE}
        self.loaded_model = "bark"
        self._current_model = CATALOG_KEYS['bark']
        return True

    def unload(self) -> None:
        if self._funcs is None:
            return
        logger.info("[Bark] déchargement")
        self._funcs = None
        self.loaded_model = None
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def process(self, text: str = "", language: str = "fr",
                voice_preset: str = "default", **_ignored) -> str:
        speaker = bark_speaker_for(voice_preset, language)
        temperature = self.sampling_temperature(_ignored)
        audio_array = self._funcs["generate_audio"](text, history_prompt=speaker,
                                                    text_temp=temperature,
                                                    waveform_temp=temperature)
        return write_wav_int16(np.asarray(audio_array, dtype=np.float32),
                               self._funcs["SAMPLE_RATE"])
