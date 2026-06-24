"""
Scénarios de test nocturne de l'Enhancer audio.

Suit le gabarit du transcriber (cf. wama/transcriber/nightly_scenarios.py). Cible `model_loaded`
sur DeepFilterNet (léger, MIT, <1 Go VRAM) : charge le modèle, vérifie, décharge.
Imports lourds DANS le callable `run` uniquement.
"""
from wama.common.services.nightly_tests import register, SkipScenario


def _run_deepfilternet_load(ctx):
    """Charge DeepFilterNet (débruitage temps réel) puis le décharge."""
    from wama.enhancer.utils.audio_enhancer import (
        DeepFilterNetBackend, get_deepfilternet_backend,
    )

    if not DeepFilterNetBackend.is_available():
        raise SkipScenario("DeepFilterNet (paquet 'df') non installé")

    backend = get_deepfilternet_backend()
    try:
        backend._ensure_loaded()
        loaded = backend._model is not None
        return loaded, "DeepFilterNet chargé" if loaded else "échec du chargement"
    finally:
        try:
            backend.unload()
        except Exception:
            pass


def register_scenarios():
    register(
        id="enhancer.deepfilternet_load",
        app="enhancer",
        stage="model_loaded",
        description="Charge DeepFilterNet (débruitage) puis le décharge",
        run=_run_deepfilternet_load,
        vram_gb=1.0,
        timeout_s=300,
    )
