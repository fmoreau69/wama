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
import logging
import threading
from pathlib import Path

import numpy as np

from .tts_base import TTSBackend, ai_models_dir, write_wav_int16

logger = logging.getLogger(__name__)

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
    """`MODEL_PATHS['speech']['phonon']` — et, sans Django (le service vocal), le même dossier
    sous `AI-models` (`tts_base.ai_models_dir`)."""
    try:
        from django.conf import settings
        return Path(settings.MODEL_PATHS['speech']['phonon'])
    except Exception:
        return ai_models_dir() / 'models' / 'speech' / 'phonon'


def model_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(model_folder(), PHONON_FILES)


#: Les voix DU MOTEUR (2026-10-28) : la valeur que porte le réglage de voix, son libellé, sa langue
#: et son genre — lues par le catalogue (`apply_engine_flags` → capacité `voices`), d'où la source
#: commune des voix les propose sous ce seul moteur. Le nom de fichier (`voices/<nom>.safetensors`)
#: est le nom que `ptts` donne à la voix.
VOICES = (
    {'value': 'phonon_noemie', 'label': 'Noémie', 'file': 'Noemie', 'language': 'fr', 'gender': 'female'},
    {'value': 'phonon_tiphaine', 'label': 'Tiphaine', 'file': 'Tiphaine', 'language': 'fr',
     'gender': 'female'},
    {'value': 'phonon_augustin', 'label': 'Augustin', 'file': 'Augustin', 'language': 'fr',
     'gender': 'male'},
    {'value': 'phonon_lucien', 'label': 'Lucien', 'file': 'Lucien', 'language': 'fr', 'gender': 'male'},
)
#: Les préréglages COMMUNS (`constants.VOICE_PRESET_CHOICES`) dits par ce moteur : la voix par
#: défaut, et celles que demande une surface qui ne connaît que le genre (l'assistant : `male_1`).
_PRESETS = {'default': 'Noemie', 'female_1': 'Noemie', 'female_2': 'Tiphaine',
            'male_1': 'Augustin', 'male_2': 'Lucien'}


def voice_file(voice_preset: str) -> str:
    """Le nom `ptts` de la voix que désigne `voice_preset` — la sienne (`phonon_…`), un préréglage
    commun, sinon la voix par défaut (une voix d'un autre moteur ne se dit pas ici)."""
    preset = (voice_preset or 'default').strip()
    for voice in VOICES:
        if voice['value'] == preset:
            return voice['file']
    return _PRESETS.get(preset, _PRESETS['default'])


class PhononBackend(TTSBackend):
    """Phonon 40m (français) par `ptts`, sur le processeur. Le contrat commun
    (`TTSBackend.synthesize`) lui donne les PAUSES et le LEXIQUE : il reçoit du texte, donc les
    termes qui ont une orthographe à dire arrivent déjà réécrits (« 8 Go » → « 8 gigaoctets »)."""

    #: Moteur piloté (contrat commun) — `composition.runtime.engine` de sa ligne.
    ENGINE = 'phonon'
    engine = 'phonon'
    description = ("Phonon 40m (Gradium, sur Pocket TTS de Kyutai) — synthèse française 24 kHz sur "
                   "le processeur, sans PyTorch ; quatre voix.")

    supports_cloning = False
    #: Il rend l'audio pendant qu'il le calcule (`TTS.stream`, `process_stream`) — le service le
    #: diffuse à la voix de l'assistant depuis le 2026-10-28 (`/tts/stream`).
    supports_streaming = True
    supports_timestamps = False
    #: Il TIRE : température 0,3 (le défaut de `ptts`), graine lue — même graine, même son (mesuré
    #: le 2026-10-28) ; à 0 il tire encore (deux graines, deux sons) : pas de minimum qui le fige.
    default_temperature = 0.3
    reads_seed = True
    default_top_p = None
    #: Le TEMPS RÉEL (voix de l'assistant, aperçus) : gardé chaud par le service. 0,5 s de
    #: chargement, 140 Mo de mémoire, aucune VRAM.
    keep_resident = True
    #: Premier son, MESURÉ le 2026-10-28 EN FLUX (`/tts/stream`, la voix de l'assistant) : 0,13 à
    #: 0,16 s sur cinq phrases et deux voix. Rendu en un fichier (le synthesizer, l'avatar), il est
    #: le temps de la synthèse entière : 1,1 s de médiane sur dix phrases.
    first_audio_s = 0.15
    #: Niveau de sortie, FIXE (2026-10-28) : un flux ne peut pas se normaliser à sa crête, qu'il ne
    #: connaît qu'à la fin. Crêtes brutes mesurées : 0,41 à 0,66 (dix phrases, deux voix) — ×1,5
    #: les porte sous 1 sans écrêter, et le fichier reçoit le même gain : un réglage, un niveau.
    OUTPUT_GAIN = 1.5
    recommended_vram_gb = 0
    VOICES = VOICES

    REQUIRED_PACKAGES = ['ptts']
    PIP_PACKAGES = ['ptts']

    def __init__(self):
        super().__init__()
        self._tts = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._tts is not None

    def load(self, model: str | None = None) -> bool:
        if self._tts is not None:
            return True
        folder = model_folder()
        if not (folder / 'config.json').is_file():
            raise RuntimeError(f"Phonon : modèle absent ({folder}) — l'installer d'abord par le "
                               f"catalogue ({MODEL_KEY}).")
        import ptts
        # Un dossier LOCAL : `ptts` n'y télécharge rien (ni poids, ni voix tant qu'on ne lui
        # demande que les siennes — `voice_file` ne rend qu'une voix installée).
        self._tts = ptts.TTS(str(folder), lang='fr', quant='q8')
        self.loaded_model = self._current_model = 'phonon-40m-fr'
        logger.info("[Phonon] chargé : %s (%s)", folder, ', '.join(self._tts.voices))
        return True

    def unload(self) -> None:
        self._tts = None
        self.loaded_model = self._current_model = None

    def _call(self, language: str, voice_preset: str, options: dict | None) -> dict:
        """Les arguments de `ptts` pour une demande — voix, température, graine."""
        if self._tts is None:
            self.load()
        if language and language != 'fr':
            logger.warning("[Phonon] langue %s demandée : ce modèle ne parle que le français", language)
        kwargs = {'options': options or {}}
        call = {'voice': voice_file(voice_preset)}
        temperature = self.sampling_temperature(kwargs)
        if temperature is not None:
            call['temperature'] = temperature
        seed = self.sampling_seed(kwargs)
        if seed is not None:
            call['seed'] = seed
        return call

    def _level(self, pcm) -> np.ndarray:
        return (np.asarray(pcm, dtype=np.float32) * self.OUTPUT_GAIN).clip(-1.0, 1.0)

    def process(self, text: str = "", language: str = "fr", voice_preset: str = "default",
                options: dict | None = None, **_ignored) -> str:
        """Dit `text` d'un trait (le contrat commun le découpe là où il respire)."""
        call = self._call(language, voice_preset, options)
        with self._lock:
            pcm = self._tts.synth(text, **call)
        if pcm is None or not len(pcm):
            raise RuntimeError("Phonon : aucun audio généré")
        return write_wav_int16(self._level(pcm), self._tts.sample_rate, normalize=False)

    def process_stream(self, text: str = "", language: str = "fr", voice_preset: str = "default",
                       options: dict | None = None, **_ignored):
        """Dit `text` en FLUX : les morceaux du décodeur, au fil du calcul (`TTS.stream`). Le verrou
        du moteur est tenu jusqu'au dernier morceau — ou jusqu'à l'abandon du flux, qui arrête le
        calcul (`AudioStream.close`)."""
        call = self._call(language, voice_preset, options)

        def chunks():
            with self._lock:
                stream = self._tts.stream(text, **call)
                try:
                    produced = False
                    for chunk in stream:
                        if len(chunk):
                            produced = True
                            yield self._level(chunk)
                    if not produced:
                        raise RuntimeError("Phonon : aucun audio généré")
                finally:
                    stream.close()
        return self._tts.sample_rate, chunks()
