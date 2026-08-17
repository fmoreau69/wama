"""
Compat torchaudio 2.x → shims soundfile — BRIQUE COMMUNE (extraite le 2026-08-17).

torchcodec est cassé sur ce poste (mémoire [[reference_torchcodec_broken]]) et torchaudio 2.x
a retiré `AudioMetaData`/`torchaudio.backend.common` : plusieurs briques audio patchaient donc
torchaudio À L'IDENTIQUE chacune de leur côté — `enhancer/utils/audio_enhancer.py`
(ResembleEnhance + DeepFilterNet : info/load/save + stub backend.common) et le service TTS
(Coqui lit ses références via torchaudio.load). Deux copies = seuil de brique.

Idempotent (marqueur sur les shims) ; n'échoue JAMAIS (un patch de compat ne doit pas casser
un chargement) ; portée = LE PROCESS (torchaudio est global — c'est la nature du patch).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MARKER = "_wama_soundfile_shim"


def patch_torchaudio_soundfile(*, stub_backend_common: bool = False,
                               patch_info: bool = False,
                               patch_save: bool = False) -> bool:
    """Remplace `torchaudio.load` (toujours) — et sur demande `info`/`save` + le stub
    `torchaudio.backend.common.AudioMetaData` — par des implémentations soundfile.

    Retourne True si le patch est posé (ou l'était déjà), False s'il a échoué.
    """
    try:
        import sys
        import types
        from collections import namedtuple

        import soundfile as sf
        import torch as _torch
        import torchaudio

        # ── AudioMetaData (retiré en 2.x) ─────────────────────────────────
        AudioMetaData = getattr(torchaudio, 'AudioMetaData', None)
        if AudioMetaData is None:
            AudioMetaData = namedtuple(
                'AudioMetaData',
                ['sample_rate', 'num_frames', 'num_channels', 'bits_per_sample', 'encoding']
            )

        if stub_backend_common and 'torchaudio.backend.common' not in sys.modules:
            backend_mod = types.ModuleType('torchaudio.backend')
            common_mod = types.ModuleType('torchaudio.backend.common')
            common_mod.AudioMetaData = AudioMetaData
            sys.modules['torchaudio.backend'] = backend_mod
            sys.modules['torchaudio.backend.common'] = common_mod
            torchaudio.backend = backend_mod

        _AudioMetaData = AudioMetaData  # capture for closures

        if patch_info and (not hasattr(torchaudio, 'info')
                           or not getattr(torchaudio.info, _MARKER, False)):
            def _info_shim(path, **kwargs):
                with sf.SoundFile(path) as f:
                    return _AudioMetaData(
                        sample_rate=f.samplerate,
                        num_frames=f.frames,
                        num_channels=f.channels,
                        bits_per_sample=16,
                        encoding='PCM_S',
                    )
            setattr(_info_shim, _MARKER, True)
            torchaudio.info = _info_shim

        if not getattr(torchaudio.load, _MARKER, False):
            def _load_shim(path, frame_offset=0, num_frames=-1, normalize=True,
                           channels_first=True, format=None, buffer_size=4096,
                           backend=None, **kwargs):
                read_kwargs = dict(start=frame_offset, dtype='float32', always_2d=True)
                if num_frames != -1:
                    read_kwargs['frames'] = num_frames
                data, sr = sf.read(str(path), **read_kwargs)
                t = _torch.from_numpy(data.T if channels_first else data)
                return t, sr
            setattr(_load_shim, _MARKER, True)
            torchaudio.load = _load_shim

        if patch_save and not getattr(getattr(torchaudio, 'save', None), _MARKER, False):
            def _save_shim(path, src, sample_rate, channels_first=True, **kwargs):
                import numpy as np
                arr = src.numpy() if not isinstance(src, np.ndarray) else src
                if channels_first:
                    arr = arr.T  # [C, T] → [T, C]
                sf.write(str(path), arr, sample_rate)
            setattr(_save_shim, _MARKER, True)
            torchaudio.save = _save_shim

        logger.debug("torchaudio compat (shims soundfile) appliqué")
        return True
    except Exception as e:
        logger.warning("torchaudio compat non appliqué : %s", e)
        return False
