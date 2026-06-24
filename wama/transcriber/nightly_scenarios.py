"""
Scénarios de test nocturne du Transcriber — GABARIT de référence.

Montre comment une app déclare un vrai scénario `model_loaded` : charger le backend ASR,
vérifier `is_loaded`, puis décharger (téardown). Le runner sérialise et libère la VRAM
autour ; ici on charge/décharge proprement. Voir wama/common/services/nightly_tests.py.

Les imports lourds (backends/torch) sont faits DANS le callable `run`, pas au niveau module,
pour ne rien charger au démarrage de Django (ready() ne fait qu'enregistrer).
"""
from wama.common.services.nightly_tests import register, SkipScenario


def _run_asr_load(ctx):
    """Charge le backend ASR (whisper de préférence), vérifie is_loaded, puis décharge."""
    from wama.transcriber.backends.manager import get_backend, get_available_backends

    available = get_available_backends()
    names = list(available)  # robuste : list OU dict {name: dispo}
    if not names:
        raise SkipScenario("aucun backend ASR disponible")

    name = "whisper" if "whisper" in names else names[0]
    backend = get_backend(name)
    if backend is None:
        return False, f"backend '{name}' introuvable"

    try:
        loaded = bool(backend.load())
        is_loaded = bool(getattr(backend, "is_loaded", loaded))
        if not is_loaded:
            return False, f"backend '{name}' : load() n'a pas abouti"
        return True, f"backend ASR '{name}' chargé (is_loaded=True)"
    finally:
        try:
            backend.unload()
        except Exception:
            pass


def register_scenarios():
    register(
        id="transcriber.asr_load",
        app="transcriber",
        stage="model_loaded",
        description="Charge le backend ASR puis le décharge (smoke chargement modèle)",
        run=_run_asr_load,
        vram_gb=3.0,        # Whisper large-v3 ~ ordre de grandeur (info de planification)
        timeout_s=600,
    )
