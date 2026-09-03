"""
Backend Audio8 TTS (0.6B) — le moteur « transformers-remote-code » : le snapshot
EMBARQUE son code de modèle (`modeling_arktts.py`, architecture ArkttsModel) et se
charge par `trust_remote_code=True` avec NOTRE transformers (contrainte du dépôt :
>=4.57,<5 — le venv est en 4.57.6, mesuré avant d'écrire ; torch>=2.5 ✓).

B2 (série « backends des modèles installés sans backend », 2026-09-03) — 2ᵉ adaptateur
du motif « backend DÉCLARÉ » après Kokoro-ONNX : rien du modèle n'est codé ici, le
snapshot est résolu depuis le CATALOGUE (extra_info['path'], posé par l'installeur)
avec un repli disque Django-free sur le chemin conventionnel (le service TTS
n'initialise pas Django). Aucun paquet pip : tout le runtime est déjà dans le venv —
c'est précisément ce qui met Audio8 en tête de la liste des « CONNUS » (handoff
16868d89), quand chatterbox exige des pins qui détruiraient le venv partagé.

⚠ CLONAGE NON PROMIS (supports_cloning=False, délibéré) : l'API zero-shot d'Audio8
exige le TRANSCRIT EXACT de l'audio de référence (`reference_text`) — une donnée que
le flux de voix WAMA (ua_/cv_, un WAV sans texte) ne porte pas. Promettre le clonage
ferait passer une voix ignorée pour un choix honoré ; le jour où la médiathèque
portera le transcript, le flag et `reference_*` s'activent ensemble.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .base import TTSBackend, ai_models_dir, write_wav_int16

logger = logging.getLogger(__name__)

#: Identité du modèle au catalogue (clé du balayage générique des snapshots HF).
CATALOG_KEY = 'huggingface:Audio8/Audio8-TTS-Preview-0.6b'
FAMILY_DIR = 'Audio8-TTS-Preview-0.6b'
SNAPSHOT_DIRNAME = 'models--Audio8--Audio8-TTS-Preview-0.6b'

#: Langues annoncées par le dépôt (11 « recommandées », fr comprise). Le moteur infère
#: la langue du TEXTE — le paramètre `language` de WAMA ne se transmet pas, il sert
#: seulement au filtrage UI via cette liste.
LANGUAGES = ['en', 'fr', 'de', 'es', 'it', 'nl', 'pl', 'ja', 'ko', 'zh-cn']


def _declared_path() -> Path | None:
    """Chemin du dépôt DÉCLARÉ au catalogue (extra_info['path'], posé par l'installeur) —
    repli disque conventionnel quand Django n'est pas là (service TTS)."""
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=CATALOG_KEY).first()
        chemin = (row.extra_info or {}).get('path') if row else ''
        if chemin and Path(chemin).is_dir():
            return Path(chemin)
    except Exception:
        pass
    repli = ai_models_dir() / 'models' / 'speech' / FAMILY_DIR / SNAPSHOT_DIRNAME
    return repli if repli.is_dir() else None


def _snapshot_dir() -> Path | None:
    """Dernier snapshot HF du dépôt (le from_pretrained veut le dossier de RÉVISION)."""
    depot = _declared_path()
    if depot is None:
        return None
    racine = depot / 'snapshots'
    if not racine.is_dir():
        return None
    revs = sorted((d for d in racine.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime)
    return revs[-1] if revs else None


class Audio8Backend(TTSBackend):
    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'transformers-remote-code'
    engine = "transformers-remote-code"
    description = ("Audio8 TTS Preview 0.6B — multilingue (11 langues dont le français), "
                   "codec 44,1 kHz embarqué, code de modèle fourni par le dépôt "
                   "(trust_remote_code).")

    supports_cloning = False        # cf. docstring : il faudrait le transcript de la référence
    keep_resident = False
    supports_timestamps = False

    #: Tout le runtime est déjà dans le venv (transformers/torch/soundfile) — aucun pip.
    REQUIRED_PACKAGES = ['transformers', 'torch']

    recommended_vram_gb = 3.1       # estimée des poids (catalogue, vram_estimated)

    def __init__(self):
        super().__init__()
        self._model = None
        self._processor = None
        self._device = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, model: str | None = None) -> bool:
        if self._model is not None:
            return True
        snapshot = _snapshot_dir()
        if snapshot is None:
            raise RuntimeError(
                f"Audio8 : snapshot absent ({FAMILY_DIR}) — installer "
                f"{CATALOG_KEY.split(':', 1)[1]} d'abord (prospection → installer).")

        import torch
        from transformers import AutoModel, AutoProcessor
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        dtype = torch.bfloat16 if self._device == 'cuda' else torch.float32
        # Chemin LOCAL du snapshot : aucun téléchargement, donc aucun HF_HUB_CACHE à
        # détourner (la checklist « path d'abord, env vars ensuite » vise les téléchargements).
        # trust_remote_code exécute le code DU snapshot — installé par notre chaîne, relu
        # à l'installation ; c'est l'architecture même de ce moteur.
        self._processor = AutoProcessor.from_pretrained(str(snapshot), trust_remote_code=True)
        self._model = (AutoModel.from_pretrained(str(snapshot), trust_remote_code=True,
                                                 dtype=dtype)
                       .eval().to(self._device))
        self.loaded_model = "audio8-tts"
        self._current_model = CATALOG_KEY.split(':', 1)[1]
        logger.info("[Audio8] chargé depuis %s (%s, %s)", snapshot.name, self._device, dtype)
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._processor = None
        self.loaded_model = None
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def process(self, text: str = "", language: str = "fr",
                voice_preset: str = "default", speaker_wav: str | None = None,
                **_ignored) -> str:
        import torch
        if self._model is None:
            self.load()
        if speaker_wav:
            # Une seule fois par appel, dans la console de l'item via le service : le
            # clonage n'est pas promis (supports_cloning=False) — on le DIT plutôt que
            # d'ignorer en silence (règle « un filtre qui s'absente ne lève pas »).
            logger.info("[Audio8] voix de référence ignorée : le clonage exige son "
                        "transcript, non porté par le flux de voix WAMA")
        entrees = self._processor(text=[text], return_tensors="pt")
        entrees = {k: v.to(self._device) for k, v in entrees.items()}
        with torch.inference_mode():
            sortie = self._model.generate(
                **entrees,
                max_new_tokens=2048,       # ~95 s d'audio au codec 21,5 trames/s — le
                temperature=0.8,           # découpage en segments du worker borne l'entrée
                top_p=0.95, top_k=50,
                do_sample=True,
                return_dict_in_generate=True,
            )
            ondes, longueurs = self._model.decode_audio(sortie.codes)
        audio = ondes[0, : int(longueurs[0])].float().cpu().numpy()
        if audio.size == 0:
            raise RuntimeError("Audio8 : aucun audio généré")
        return write_wav_int16(np.asarray(audio, dtype=np.float32),
                               int(self._model.config.codec_sample_rate))
