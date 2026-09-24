"""
Aligneur acoustique wav2vec2 (CTC) — premier moteur du contrat `ForcedAlignmentBackend`.

Principe : un modèle wav2vec2 fine-tuné en CTC donne, pour chaque trame de 20 ms, la probabilité
de chaque lettre de son alphabet. Connaissant les lettres prononcées (le texte), l'alignement
forcé cherche le chemin le plus probable qui les émet DANS L'ORDRE (`torchaudio.functional.
forced_align`, Viterbi CTC) : chaque lettre reçoit ses trames, chaque mot l'intervalle de ses
lettres. Rien n'est transcrit — un mot absent du texte ne peut pas apparaître.

Choix du modèle (2026-09-23, ROADMAP de l'alignement, `TRANSCRIBER_CORRECTION §10`) :
`jonatasgrosman/wav2vec2-large-xlsr-53-french`, Apache-2.0, servi par `transformers` et
`torchaudio` DÉJÀ au venv — aucune librairie nouvelle. Écartés : Qwen3-ForcedAligner (sa lib
`qwen-asr` déplace accelerate et nccl, et ajoute trois paquets), MMS_FA (CC-BY-NC).

Le modèle vient du CATALOGUE : l'appelant le choisit par capacité (`task='alignment'`, langue)
et passe son dépôt à `load()`. Ce backend ne connaît ni la langue ni le dépôt par défaut — une
valeur écrite ici serait une seconde source de vérité à côté de `model_config`.
"""

import logging
import unicodedata
from typing import List, Optional

from wama.common.backends.forced_alignment_base import AlignedWord, ForcedAlignmentBackend

logger = logging.getLogger(__name__)


class Wav2Vec2AlignerBackend(ForcedAlignmentBackend):
    """Alignement forcé CTC sur un modèle wav2vec2 (lettres → trames → mots)."""

    #: Moteur piloté (contrat commun). `transformers` est partagé par plusieurs backends :
    #: `SUPPORTED_MODELS` tranche (clés = `model_id` du catalogue, cf. `QwenASRBackend`).
    ENGINE = 'transformers'
    SUPPORTED_MODELS = {'wav2vec2-fr-aligner': {}}

    name = "wav2vec2_aligner"
    display_name = "wav2vec2 (alignement forcé)"
    description = "Aligne un texte connu sur l'audio, mot à mot — ne transcrit pas."
    description_long = (
        "Alignement forcé acoustique : à partir d'un texte déjà écrit (une transcription reprise, "
        "une correction) et de l'audio, donne l'heure de début et de fin de chaque mot. Modèle "
        "wav2vec2 CTC ; ne produit aucun texte. Sert à resynchroniser les passages qu'une "
        "correction a modifiés, là où la transcription automatique n'a pas d'heure fiable."
    )

    #: Horodatage au MOT — c'est tout ce qu'il produit.
    supports_timestamps = True

    REQUIRED_PACKAGES = ['transformers', 'torchaudio']

    # Repli du gouverneur si la mesure autour de load() n'est pas concluante : ~315 M
    # paramètres en demi-précision + les activations d'une fenêtre d'une minute.
    recommended_vram_gb = 2

    #: Une minute : l'attention coûte le carré du nombre de trames (3 000 à 50 trames/s).
    max_audio_seconds = 60.0

    def __init__(self):
        self._model = None
        self._processor = None
        self._device = None
        self._current_model = None
        self._letters = {}          # lettre → id de jeton
        self._blank = 0

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    # ── Cycle de vie ─────────────────────────────────────────────────────────
    def load(self, model_name: str = None) -> bool:
        """Charge le dépôt `model_name` (dépôt HuggingFace, lu au catalogue par l'appelant)."""
        if not model_name:
            raise ValueError("wav2vec2_aligner : le dépôt du modèle vient du catalogue, "
                             "il n'y a pas de modèle par défaut")
        if self._model is not None and self._current_model == model_name:
            return True
        if self._model is not None:
            self.unload()

        import torch
        from django.conf import settings
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        # `cache_dir=` seul — jamais de mutation de HF_HUB_CACHE (AGENTS.md §modèles).
        cache_dir = str(settings.MODEL_PATHS.get('speech', {}).get('alignment') or '') or None
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        dtype = torch.float16 if self._device == 'cuda' else torch.float32
        logger.info(f"[wav2vec2_aligner] Chargement {model_name} sur {self._device}"
                    + (f" → {cache_dir}" if cache_dir else ""))
        self._processor = Wav2Vec2Processor.from_pretrained(model_name, cache_dir=cache_dir)
        self._model = Wav2Vec2ForCTC.from_pretrained(
            model_name, cache_dir=cache_dir, dtype=dtype).to(self._device).eval()

        tokenizer = self._processor.tokenizer
        self._blank = tokenizer.pad_token_id
        specials = set(tokenizer.all_special_tokens) | {tokenizer.word_delimiter_token}
        self._letters = {tok: idx for tok, idx in tokenizer.get_vocab().items()
                         if len(tok) == 1 and tok not in specials}
        self._current_model = model_name
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = self._processor = None
        self._current_model = None
        try:
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[wav2vec2_aligner] Modèle déchargé ✓")

    # ── Métier ───────────────────────────────────────────────────────────────
    def spell(self, word: str) -> List[int]:
        """Les jetons du modèle pour `word` : ses lettres connues, minuscules ; une lettre
        accentuée absente de l'alphabet retombe sur sa base (« ñ » → « n »). Le reste (chiffres,
        ponctuation) ne se prononce pas lettre à lettre : ignoré."""
        ids = []
        for char in (word or '').lower():
            if char not in self._letters:
                char = unicodedata.normalize('NFD', char)[0]
            if char in self._letters:
                ids.append(self._letters[char])
        return ids

    def align(self, waveform, words: List[str]) -> List[Optional[AlignedWord]]:
        import torch

        if self._model is None:
            raise RuntimeError("wav2vec2_aligner : modèle non chargé")
        spelled = [self.spell(w) for w in words]
        if not any(spelled):
            return [None] * len(words)
        inputs = self._processor(waveform, sampling_rate=self.sample_rate, return_tensors='pt')
        values = inputs.input_values.to(self._device, dtype=self._model.dtype)
        with torch.inference_mode():
            logits = self._model(values).logits
        emission = torch.log_softmax(logits.float(), dim=-1).cpu()
        seconds_per_frame = len(waveform) / emission.shape[1] / self.sample_rate
        return align_emission(emission, spelled, self._blank, seconds_per_frame)


def align_emission(emission, spelled: List[List[int]], blank: int,
                   seconds_per_frame: float) -> List[Optional[AlignedWord]]:
    """Le cœur, sans modèle : `emission` (1, trames, alphabet) en log-probabilités, `spelled` les
    jetons de chaque mot. Rend l'heure de chaque mot (None pour un mot sans jeton).

    Séparé de la classe pour être testé sur une émission FABRIQUÉE — le chemin de Viterbi ne
    dépend que de la matrice, pas du réseau qui l'a produite.
    """
    import torch
    from torchaudio.functional import forced_align, merge_tokens

    targets = [i for ids in spelled for i in ids]
    # CTC : une lettre par trame au moins, plus un blanc entre deux lettres identiques.
    needed = len(targets) + sum(1 for a, b in zip(targets, targets[1:]) if a == b)
    if emission.shape[1] < needed:
        raise ValueError(f"fenêtre trop courte : {emission.shape[1]} trames pour {needed} lettres")
    path, scores = forced_align(emission, torch.tensor([targets], dtype=torch.int32), blank=blank)
    spans = merge_tokens(path[0], scores[0].exp())

    out, k = [], 0
    for ids in spelled:
        if not ids:
            out.append(None)
            continue
        mine = spans[k:k + len(ids)]
        k += len(ids)
        frames = sum(len(s) for s in mine)
        out.append(AlignedWord(
            start=round(mine[0].start * seconds_per_frame, 3),
            end=round(mine[-1].end * seconds_per_frame, 3),
            score=round(sum(s.score * len(s) for s in mine) / frames, 4) if frames else None,
        ))
    return out
