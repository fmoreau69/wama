"""Smart Turn (pipecat-ai) — le contrat `end-of-turn` sur ONNX Runtime.

L'écoute de l'assistant le consulte après une pause courte (`common/tts/end_of_turn.py`) ; il tourne
dans le service vocal, sur le processeur. Jusqu'au 2026-11-08, le service le chargeait lui-même
(`_turn_session`, un dict de sessions ONNX par chemin, et `_turn_features` pour l'extracteur) :
hors de l'enveloppe du gouverneur et du déchargement commun. Ce backend est ce chargement, au
contrat — la même recette, celle de l'éditeur (`inference.py` du dépôt pipecat-ai/smart-turn).

Ses poids sont DÉCLARÉS à côté de l'écoute (`end_of_turn.TURN_FILES`) et installés par la route ;
leur dossier se lit par la lecture commune des modèles de parole (`tts_base.speech_folder`), la même
dans Django et dans le service. Absent, il le DIT : la librairie ne télécharge rien.
"""
from __future__ import annotations

import gc
import logging
from typing import Optional

from .end_of_turn_base import EndOfTurnBackend
from .tts_base import TTS_SERVICE

logger = logging.getLogger(__name__)


class SmartTurnBackend(EndOfTurnBackend):
    """La fin de tour d'une phrase, jugée sur le son seul (intonation, fin de mot)."""

    #: Moteur piloté (contrat commun) : ONNX Runtime, partagé avec d'autres tâches — c'est le
    #: contrat `end-of-turn` qui borne ce backend à la sienne.
    ENGINE = 'onnxruntime'
    #: Modèles servis : clé = dernier segment de la clé de catalogue. ⚠ En LITTÉRAL : l'inventaire
    #: lit les clés par AST.
    SUPPORTED_MODELS = {
        'pipecat-ai/smart-turn-v3': {'model_key': 'huggingface:pipecat-ai/smart-turn-v3'},
    }
    REQUIRED_PACKAGES = ['onnxruntime', 'transformers']
    PIP_PACKAGES = ['onnxruntime-gpu', 'transformers']
    name = 'smart-turn'
    display_name = 'Smart Turn v3.2'
    description = "Fin de tour de parole : la personne a-t-elle fini sa phrase ? (processeur)"

    #: Ce que la recette écoute : les 8 DERNIÈRES secondes, complétées de silence au début.
    window_seconds = 8

    #: Le PROCESSUS qui le charge, pour tous (`BaseModelBackend.SERVED_BY`) : le service de voix,
    #: comme ses moteurs (`tts_base.TTS_SERVICE`) — le gouverneur cherche ses résidents là, pas dans
    #: le processus qui demande l'avis (`resource_governor.served_resident_gb`).
    SERVED_BY = TTS_SERVICE

    #: Le processeur, déclaré : la variante int8 est faite pour lui, et la carte reste à la voix.
    #: L'enveloppe du gouverneur ne publie rien.
    device = 'cpu'
    recommended_vram_gb = 0

    def __init__(self):
        super().__init__()
        self._session = None
        self._extractor = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._loaded:
            return True
        from wama.common.tts.end_of_turn import MODEL_KEY, model_path
        path = model_path()
        if not path.is_file():
            raise RuntimeError(f"Smart Turn absent ({path}) — il s'installe par le model manager "
                               f"(ligne « {MODEL_KEY} »).")
        import onnxruntime as ort
        from transformers import WhisperFeatureExtractor

        from wama.common.utils.onnx_utils import onnx_providers
        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(str(path), sess_options=options,
                                             providers=onnx_providers(cpu_only=True))
        self._extractor = WhisperFeatureExtractor(chunk_length=self.window_seconds)
        self._loaded, self._current_model = True, MODEL_KEY
        logger.info('[SmartTurn] chargé (processeur)')
        return True

    def unload(self) -> None:
        self._session = None
        self._extractor = None
        gc.collect()
        self._loaded, self._current_model = False, None

    def turn_end_probability(self, audio) -> float:
        if not self._loaded:
            raise RuntimeError("SmartTurnBackend : modèle non chargé (`load()` d'abord)")
        import numpy as np
        size = self.window_seconds * self.sample_rate
        wave = np.asarray(audio, dtype=np.float32)[-size:]
        if len(wave) < size:
            wave = np.pad(wave, (size - len(wave), 0))
        features = self._extractor(wave, sampling_rate=self.sample_rate, return_tensors="np",
                                   padding="max_length", max_length=size, truncation=True,
                                   do_normalize=True)
        inputs = features.input_features.squeeze(0).astype(np.float32)[None, ...]
        outputs = self._session.run(None, {"input_features": inputs})
        return float(outputs[0].reshape(-1)[0])
