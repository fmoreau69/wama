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
    # VRAM de planification : lue sur la CLASSE backend, désormais rattachée au contrat commun
    # (`BaseModelBackend`) — même source que ce que le gouverneur réserve au chargement. Un
    # chiffre recopié ici dériverait du réel : c'est ce type d'écart (16 déclarés vs 38 réels
    # sur qwen-image) qui a fait paniquer le noyau WSL2 le 29/07/2026.
    try:
        from wama.transcriber.backends.whisper_backend import WhisperBackend
        vram_gb = float(WhisperBackend.recommended_vram_gb or 0) or 10.0
    except Exception:
        vram_gb = 10.0

    register(
        id="transcriber.asr_load",
        app="transcriber",
        stage="model_loaded",
        description="Charge le backend ASR puis le décharge (smoke chargement modèle)",
        run=_run_asr_load,
        vram_gb=vram_gb,
        timeout_s=600,
    )
