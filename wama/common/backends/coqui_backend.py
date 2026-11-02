"""
Backend Coqui TTS (XTTS v2).

Le backend reste keyé par `COQUI_MODEL_MAPPING` — il ne connaît aucun identifiant
`tts_models/...` en dur — bien que la table n'ait plus qu'une entrée depuis le retrait
des trois moteurs EN-only (R32) : un second modèle Coqui se brancherait sans y toucher.
XTTS v2 exige un audio de référence (clonage).

Poids : DÉCLARÉS ici (`COQUI_FILES`, dépôt du Hub `coqui/XTTS-v2` figé à un commit), installés par
la route et lus par DOSSIER (2026-11-02). Avant, `TTS(<nom>)` passait par le gestionnaire de la
librairie : il tirait le modèle s'il manquait et, à CHAQUE chargement de XTTS, relisait le
`config.json` distant pour retirer tout le modèle s'il avait changé (`TTS/utils/manage.py:424-428`).
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from wama.common.tts.constants import COQUI_MODEL_MAPPING

from .tts_base import CATALOG_KEYS, TTSBackend, _device, project_root

logger = logging.getLogger(__name__)

#: VRAM a-priori par modèle UI (repli si la mesure du contrat est non concluante).
_VRAM_GB = {'coqui-xtts': 2.5}

XTTS_REPO = 'coqui/XTTS-v2'
XTTS_REVISION = '6c2b0d75eae4b7047358e3b6bd9325f857d43f77'


def _model_dir_name(model_id: str) -> str:
    """Le dossier où la librairie rangeait le modèle sous `<TTS_HOME>/tts` (son nom complet,
    `/` → `--`, `TTS/utils/manage.py`) — gardé : les fichiers déjà sur disque restent à leur place."""
    return 'tts/' + model_id.replace('/', '--')


#: Les fichiers que `Xtts.load_checkpoint(checkpoint_dir=…)` lit (`model.pth`, `vocab.json`,
#: `speakers_xtts.pth`, et le `config.json` du dossier). Tailles et empreintes PUBLIÉES par le Hub
#: au commit (blob git des petits fichiers, LFS des poids) — et MESURÉES le 2026-11-02 sur les
#: fichiers en place : identiques. `hash.md5` ne servait que le gestionnaire de la librairie.
COQUI_FILES = {
    'coqui-xtts': [
        {'path': f"{_model_dir_name(COQUI_MODEL_MAPPING['coqui-xtts'])}/{name}", 'size': size,
         'sha256': sha256,
         'origin': {'source': 'huggingface', 'repo': XTTS_REPO, 'revision': XTTS_REVISION,
                    'file': name}}
        for name, size, sha256 in (
            ('config.json', 4368,
             'ef262b1454dd2a77e1461b0b2cd53e19b8a7624cc131b837d36df67356bc75e8'),
            ('model.pth', 1867929118,
             'c7ea20001c6a0a841c77e252d8409f6a74fb423e79b3206a0771ba5989776187'),
            ('speakers_xtts.pth', 7754818,
             'f0f6137c19a4eab0cbbe4c99b5babacf68b1746e50da90807708c10e645b943b'),
            ('vocab.json', 361219,
             '928260878a59da8a72a2a5b7687fea29d5106137669d90945430fe17e415304a'),
        )
    ],
}


def coqui_folder() -> Path:
    """`MODEL_PATHS['speech']['coqui']` — et, hors Django (le service de voix, où Coqui tourne),
    le même dossier sous `AI-models` : jamais le `$HOME`."""
    try:
        from django.conf import settings
        return Path(settings.MODEL_PATHS['speech']['coqui'])
    except Exception:
        from .tts_base import ai_models_dir
        return ai_models_dir() / 'models' / 'speech' / 'coqui'


def coqui_model_dir(model: str) -> Path:
    """Le dossier du modèle, DÉRIVÉ de ses fichiers déclarés."""
    return coqui_folder() / Path(COQUI_FILES[model][0]['path']).parent


def coqui_installed(model: str) -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(coqui_folder(), COQUI_FILES[model])


class CoquiBackend(TTSBackend):
    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'coqui'
    engine = "coqui"
    description = "Coqui TTS — XTTS v2 (clonage multilingue) et moteurs EN légers."

    supports_cloning = True    # XTTS = clonage par speaker_wav (aligné sur le catalogue)
    #: XTTS TIRE : 0,75, la valeur de son `config.json` (`xtts_v2/config.json`, lue par
    #: `Xtts.synthesize`) ; `tts_to_file` transmet le réglage à `Xtts.inference` (2026-10-21).
    #: Le seul modèle de ce moteur au catalogue est XTTS v2.
    default_temperature = 0.75
    #: 0,85, la valeur du même `config.json` (`"top_p": 0.85`) ; la graine se pose sur torch avant
    #: la synthèse (2026-10-22).
    default_top_p = 0.85
    reads_seed = True

    REQUIRED_PACKAGES = ['TTS', 'soundfile']
    # `pip install TTS` est le paquet idiap/coqui-ai-TTS maintenu — nom pip = nom d'import.

    recommended_vram_gb = 2.5

    def __init__(self):
        super().__init__()
        self._tts = None

    @property
    def is_loaded(self) -> bool:
        return self._tts is not None

    def load(self, model: str | None = None) -> bool:
        model = model or 'coqui-xtts'
        if self._tts is not None and self.loaded_model == model:
            return True

        # Les fichiers DÉCLARÉS, installés par la route. Absents, on le DIT : la glu demande le
        # modèle à la route avant (synthesizer, avatarizer : `ctx.ensure_model`).
        if model not in COQUI_FILES:
            raise ValueError(f"[Coqui] modèle non déclaré : {model!r}")
        if not coqui_installed(model):
            raise RuntimeError(
                f"Coqui {model} n'est pas installé ({coqui_model_dir(model)}) — il s'installe par "
                f"le model manager (modèle « {CATALOG_KEYS.get(model, model)} »).")

        # torchaudio.load → soundfile : torchcodec est cassé sur ce poste et Coqui lit
        # ses références via torchaudio — BRIQUE COMMUNE (partagée avec l'enhancer).
        from wama.common.utils.torchaudio_compat import patch_torchaudio_soundfile
        patch_torchaudio_soundfile()

        from TTS.api import TTS
        from TTS.utils.synthesizer import Synthesizer

        full_id = COQUI_MODEL_MAPPING.get(model, model)
        logger.info(f"[Coqui] chargement {full_id} sur {_device()}")
        # LE MÊME chargement que `TTS(full_id)` (`TTS/api.py:230-249` : un modèle à plus de deux
        # fichiers se lit par DOSSIER, `Synthesizer(model_dir=…)`), SANS le gestionnaire qui
        # télécharge. ⚠ Pas `TTS(model_path=…)` : il passe par `Synthesizer._load_tts`, qui lit
        # `audio.sample_rate` (22 050 Hz pour XTTS) au lieu d'`audio.output_sample_rate` (24 000) —
        # le son sortirait à la mauvaise fréquence.
        tts = TTS(progress_bar=False)
        tts.model_name = full_id
        tts.synthesizer = Synthesizer(
            tts_checkpoint=None, tts_config_path=None, tts_speakers_file=None,
            tts_languages_file=None, vocoder_checkpoint=None, vocoder_config=None,
            encoder_checkpoint=tts.encoder_path, encoder_config=tts.encoder_config_path,
            model_dir=str(coqui_model_dir(model)), use_cuda=False)
        self._tts = tts.to(_device())
        self.loaded_model = model
        self._current_model = CATALOG_KEYS.get(model, model)
        self.recommended_vram_gb = _VRAM_GB.get(model, 2.5)
        return True

    def unload(self) -> None:
        if self._tts is None:
            return
        logger.info(f"[Coqui] déchargement {self.loaded_model}")
        del self._tts
        self._tts = None
        self.loaded_model = None
        self._current_model = None
        self._empty_cuda_cache()

    def process(self, text: str = "", model: str | None = None, language: str = "fr",
                speaker_wav: str | None = None, **_ignored) -> str:
        """Génère un WAV temporaire. XTTS v2 exige `speaker_wav` (résolu par l'appelant)."""
        kwargs = {"text": text}

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                          dir=str(project_root() / "logs"))
        kwargs["file_path"] = tmp.name
        tmp.close()

        if (model or self.loaded_model) == "coqui-xtts":
            kwargs["language"] = language
            if speaker_wav and os.path.exists(speaker_wav):
                kwargs["speaker_wav"] = speaker_wav
            else:
                raise ValueError("XTTS v2 requires a speaker_wav reference audio file")
            # La température de la card, sinon 0,75 ; à 0, le choix le plus probable.
            temperature = self.sampling_temperature(_ignored)
            self.sampling_seed(_ignored)
            kwargs.update({"temperature": temperature, "do_sample": True,
                           "top_p": self.sampling_top_p(_ignored)}
                          if self.samples(temperature) else {"do_sample": False})

        self._tts.tts_to_file(**kwargs)
        return tmp.name

    # ------------------------------------------------------------------

    @staticmethod
    def _empty_cuda_cache():
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

