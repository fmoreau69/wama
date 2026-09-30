"""
Transcriber Backend Manager

Manages transcription backend registration, availability checking, and selection.
"""

import logging
from typing import Dict, List, Optional, Type

from wama.common.backends.speech_to_text_base import SpeechToTextBackend

logger = logging.getLogger(__name__)


class TranscriberBackendManager:
    """
    Manager for transcription backends.

    Handles backend registration, availability checking, and priority-based selection.
    """

    # Priority order for auto-selection (first available wins).
    # Whisper d'abord : meilleure qualité FR, plus léger (~10 GB vs 16 GB pour
    # VibeVoice), et la diarisation est assurée par pyannote (backend-agnostique).
    # VibeVoice reste sélectionnable explicitement (diarisation native). qwen_asr
    # en dernier : is_available()=True dès transformers installé, mais nécessite
    # un téléchargement explicite + son intérêt (context biasing) est opt-in.
    BACKEND_PRIORITY = [
        'whisper',     # Défaut fiable : faster-whisper large-v3 + pyannote
        'vibevoice',   # Option : diarisation native (16 GB VRAM)
        'qwen_asr',    # Option : context biasing (hotwords), une fois le modèle dispo
    ]

    _backends: Dict[str, Type[SpeechToTextBackend]] = {}
    _instances: Dict[str, SpeechToTextBackend] = {}
    _availability_cache: Dict[str, bool] = {}
    # True si un check a échoué sur EXCEPTION (vs False propre) → cache « incomplet »,
    # à ré-évaluer au prochain appel. Couvre les indispos transitoires au démarrage
    # (ex. course d'imports accelerate qui casse VibeVoice le temps que ça se stabilise).
    _availability_incomplete: bool = False
    _instance: Optional['TranscriberBackendManager'] = None

    @classmethod
    def get_instance(cls) -> 'TranscriberBackendManager':
        """Get singleton instance of the manager."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_backends()
        return cls._instance

    def _register_backends(self) -> None:
        """Register all available backends."""
        # Import backends
        try:
            from wama.common.backends.whisper_backend import WhisperBackend
            self._backends['whisper'] = WhisperBackend
            logger.debug("[TranscriberManager] Registered: whisper")
        except ImportError as e:
            logger.warning(f"[TranscriberManager] Could not import WhisperBackend: {e}")

        try:
            from wama.common.backends.vibevoice_backend import VibeVoiceBackend
            self._backends['vibevoice'] = VibeVoiceBackend
            logger.debug("[TranscriberManager] Registered: vibevoice")
        except ImportError as e:
            logger.warning(f"[TranscriberManager] Could not import VibeVoiceBackend: {e}")

        try:
            from wama.common.backends.qwen_asr_backend import QwenASRBackend
            self._backends['qwen_asr'] = QwenASRBackend
            logger.debug("[TranscriberManager] Registered: qwen_asr")
        except ImportError as e:
            logger.warning(f"[TranscriberManager] Could not import QwenASRBackend: {e}")

        try:
            from wama.common.backends.nemo_asr_backend import NemoASRBackend
            self._backends['nemo'] = NemoASRBackend
            logger.debug("[TranscriberManager] Registered: nemo")
        except ImportError as e:
            logger.warning(f"[TranscriberManager] Could not import NemoASRBackend: {e}")

        logger.info(f"[TranscriberManager] Registered backends: {list(self._backends.keys())}")

    def check_availability(self, force: bool = False) -> Dict[str, bool]:
        """
        Check which backends are available.

        Args:
            force: If True, recheck even if cached.

        Returns:
            Dict mapping backend name to availability status.
        """
        # Cache réutilisé seulement s'il est COMPLET (aucun check n'a planté sur exception).
        if not force and self._availability_cache and not self._availability_incomplete:
            return self._availability_cache.copy()

        self._availability_cache = {}
        self._availability_incomplete = False
        for name, backend_class in self._backends.items():
            try:
                available = backend_class.is_available()
                self._availability_cache[name] = available
                status = "available" if available else "not available"
                logger.info(f"[TranscriberManager] {name}: {status}")
            except Exception as e:
                # Échec sur exception (≠ False propre) : probablement transitoire
                # (course d'imports au démarrage). On ne verrouille PAS ce négatif →
                # le cache est marqué incomplet pour forcer une ré-évaluation ensuite.
                self._availability_cache[name] = False
                self._availability_incomplete = True
                logger.warning(f"[TranscriberManager] Error checking {name}: {e} (sera re-testé)")

        return self._availability_cache.copy()

    def get_available_backends(self) -> List[str]:
        """
        Get list of available backend names.

        Returns:
            List of available backend names.
        """
        availability = self.check_availability()
        return [name for name, available in availability.items() if available]

    def get_backend(self, name: str = None, user=None) -> SpeechToTextBackend:
        """
        Get a backend instance.

        Args:
            name: Backend name. If None or 'auto', select best available.
            user: whose rights and key a REMOTE model is called with (`_remote_backend`).

        Returns:
            Backend instance.

        Raises:
            RuntimeError: If no backend is available.
        """
        # Auto-select if no name provided
        if name is None or name == 'auto':
            return self._get_best_backend()

        # Un modèle DISTANT du catalogue passe AVANT tout repli : lui substituer un moteur local
        # serait une réponse fausse — `albert:whisper-large-v3` contient « whisper ».
        remote = self._remote_backend(name, user)
        if remote is not None:
            return remote

        # Un nom de MODÈLE du catalogue (`qwen3-asr-1.7b`, `transcriber:vibevoice-asr`) désigne
        # son moteur par la même table que le catalogue (`_backend_for_model_key`). Sans cette
        # traduction, l'essai de l'assistant du 2026-09-28 aurait transcrit en WHISPER, sans une
        # erreur, une demande faite pour Qwen3-ASR : un nom inconnu retombait sur le meilleur
        # moteur disponible. *Un repli silencieux sur une demande explicite est une réponse fausse.*
        if name not in self._backends:
            translated = self._backend_for_model_key(name)
            if translated in self._backends:
                logger.info(f"[TranscriberManager] '{name}' is a catalogue model → backend '{translated}'")
                name = translated
        if name not in self._backends:
            logger.warning(f"[TranscriberManager] Unknown backend: {name}")
            return self._get_best_backend()

        availability = self.check_availability()
        if not availability.get(name, False):
            # L'utilisateur a demandé CE moteur explicitement : avant de replier,
            # forcer un re-test (l'indispo peut être une race d'import transitoire au
            # démarrage, déjà résorbée au moment où la tâche tourne).
            logger.info(f"[TranscriberManager] {name} marqué indisponible — re-test forcé")
            availability = self.check_availability(force=True)
        if not availability.get(name, False):
            logger.warning(f"[TranscriberManager] Backend not available: {name}")
            return self._get_best_backend()

        # Return cached instance or create new one
        if name not in self._instances:
            self._instances[name] = self._backends[name]()
        return self._instances[name]

    def _remote_backend(self, name: str, user) -> Optional[SpeechToTextBackend]:
        """Le backend d'un modèle DISTANT du catalogue, autorisé pour `user` — None si `name`
        n'en désigne pas un.

        Le moteur se résout par le lien COMMUN (`backend_for_model` : `composition.runtime.engine`
        du modèle ↔ `ENGINE` du backend), jamais par le nom ; la clé passe par la garde commune
        (`cloud_access`). Un refus ou un moteur introuvable LÈVE : on ne remplace pas un modèle
        distant demandé par un local — la mesure et la confidentialité en dépendraient.
        """
        if not self._is_remote_key(name):
            return None
        from wama.common.backends.manager import backend_for_model
        from wama.model_manager.models import AIModel, EXECUTION_CLOUD
        from wama.model_manager.services.cloud_models import CloudAccessRefused, cloud_access
        row = AIModel.objects.filter(model_key=name, execution=EXECUTION_CLOUD,
                                     is_available=True).first()
        if row is None:
            raise RuntimeError(f"Modèle distant « {name} » absent du catalogue ou retiré par "
                               "son fournisseur.")
        cls = backend_for_model(row)
        if cls is None or not issubclass(cls, SpeechToTextBackend):
            raise RuntimeError(f"Aucun backend de transcription ne sait appeler « {name} ».")
        source, model_id = name.split(':', 1)
        try:
            api_key = cloud_access(user, source, model_id)
        except CloudAccessRefused as e:
            raise RuntimeError(str(e)) from e
        instance = self._instances.get(name) or cls()
        instance.catalogue_key = name
        instance.authorize(api_key)
        self._instances[name] = instance
        return instance

    @staticmethod
    def _is_remote_key(model_key: str) -> bool:
        """`<source>:<id>` dont la source est un fournisseur distant (`external_sources`, `llm`)."""
        from wama.common import external_sources
        prefix = (model_key or '').split(':', 1)[0] if ':' in (model_key or '') else ''
        source = external_sources.by_key().get(prefix)
        return source is not None and source.kind == 'llm'

    # Map model_key du catalogue AIModel → nom de backend interne.
    # (le catalogue nomme finement : whisper-large-v3, vibevoice-asr, qwen3-asr-0.6b…)
    @classmethod
    def _backend_for_model_key(cls, model_key: str) -> Optional[str]:
        # Un modèle DISTANT n'a pas de moteur local, même s'il en porte le nom.
        if cls._is_remote_key(model_key):
            return None
        mk = (model_key or '').lower()
        if 'vibevoice' in mk:
            return 'vibevoice'
        if 'qwen' in mk:
            return 'qwen_asr'
        if 'whisper' in mk:
            return 'whisper'
        if 'canary' in mk or 'parakeet' in mk:
            return 'nemo'
        return None

    @staticmethod
    def model_for_request(backend, requested: str) -> Optional[str]:
        """`model_id` du catalogue que la demande `requested` désigne pour `backend` — quand c'est
        l'un des modèles que ce backend SERT (`SUPPORTED_MODELS`), sinon None (nom de moteur,
        `auto`, inconnu : le backend charge son défaut).

        POURQUOI (2026-09-28) : le worker appelait `backend.load()` SANS dire quel modèle. Un
        moteur qui en sert plusieurs (Qwen3-ASR 0.6B / 1.7B, NeMo canary / parakeet) chargeait
        donc toujours son défaut — demander le 0.6B donnait le 1.7B, sans un mot."""
        if not requested:
            return None
        # Un modèle distant : le backend a été résolu POUR lui, il n'a pas de liste à consulter.
        if getattr(backend, 'catalogue_key', '') == requested:
            return requested.split(':', 1)[-1]
        model_id = requested.split(':', 1)[-1].strip().lower()
        served = getattr(backend, 'SUPPORTED_MODELS', None) or {}
        return model_id if model_id in served else None

    @classmethod
    def honours(cls, backend, requested: str) -> bool:
        """Le backend retenu est-il celui que la demande désignait (nom de moteur OU modèle du
        catalogue) ? Faux = un vrai repli, à dire à l'utilisateur. Comparer les noms seuls
        disait « indisponible — repli » pour `transcriber:qwen3-asr-1.7b` servi… par Qwen3-ASR."""
        if not requested:
            return True
        if getattr(backend, 'catalogue_key', '') == requested:
            return True
        return backend.name == requested or cls._backend_for_model_key(requested) == backend.name

    @classmethod
    def catalogue_key_for(cls, backend_name: str, loaded_model: str = '') -> str:
        """Clé catalogue du modèle EFFECTIVEMENT utilisé — l'inverse de `_backend_for_model_key`.

        Le moteur (`whisper`, `qwen_asr`…) ne suffit pas quand le catalogue en porte plusieurs
        variantes (`qwen3-asr-0.6b` / `-1.7b`) : le modèle CHARGÉ tranche (`_current_model`
        du contrat `speech_to_text_base`, lu AVANT `unload()`, qui le remet à None). Une mesure
        attribuée au mauvais modèle fausserait son indice interne — on préfère alors la clé du
        moteur, qui ne prétend pas savoir la variante.
        """
        try:
            from wama.model_manager.models import AIModel
            keys = [k for k in AIModel.objects.filter(source='transcriber')
                    .values_list('model_key', flat=True)
                    if cls._backend_for_model_key(k) == backend_name]
        except Exception:
            keys = []
        if len(keys) == 1:
            return keys[0]
        loaded = (loaded_model or '').lower().rsplit('/', 1)[-1]
        matching = [k for k in keys if k.split(':', 1)[-1].lower() == loaded]
        if len(matching) == 1:
            return matching[0]
        return f'transcriber:{backend_name}' if backend_name else ''

    def _select_backend_via_model_manager(self, availability: Dict[str, bool]) -> Optional[str]:
        """
        Choix VRAM-aware du backend via la brique commune `select_model()`
        (keep_loaded + budget VRAM + priorité whisper-first préservée).

        Renvoie un nom de backend DISPONIBLE, ou None → l'appelant retombe alors
        sur la sélection statique BACKEND_PRIORITY (aucune régression si le
        catalogue AIModel est vide ou le model_manager indisponible).
        """
        try:
            from wama.model_manager.services import select_model
        except Exception:
            return None
        try:
            # availability_probe : ne retenir qu'un modèle dont le backend est
            # réellement importable/disponible ici (au-delà du is_downloaded catalogue).
            def _probe(m):
                bname = self._backend_for_model_key(m.model_key)
                return bool(bname) and availability.get(bname, False)

            chosen = select_model(
                source='transcriber',
                prefer_loaded=True,          # keep_loaded : réutilise un backend déjà chargé
                downloaded_only=False,       # la dispo runtime prime (availability_probe)
                priority=['whisper', 'vibevoice', 'qwen'],  # même politique whisper-first
                availability_probe=_probe,
            )
            if chosen is None:
                return None
            bname = self._backend_for_model_key(chosen.model_key)
            if bname and availability.get(bname, False):
                logger.info(f"[TranscriberManager] select_model → {chosen.model_key} → backend '{bname}'")
                return bname
        except Exception as e:
            logger.debug(f"[TranscriberManager] select_model indisponible ({e}) → priorité statique")
        return None

    def _get_best_backend(self) -> SpeechToTextBackend:
        """
        Get the best available backend.

        1) Tente un choix VRAM-aware centralisé via `select_model()` (model_manager).
        2) À défaut (catalogue vide / model_manager KO), retombe sur la priorité
           statique BACKEND_PRIORITY — comportement historique, aucune régression.

        Returns:
            Best available backend instance.

        Raises:
            RuntimeError: If no backend is available.
        """
        availability = self.check_availability()

        # 1) Choix centralisé VRAM-aware (brique commune). None → fallback statique.
        mm_choice = self._select_backend_via_model_manager(availability)
        if mm_choice:
            if mm_choice not in self._instances:
                self._instances[mm_choice] = self._backends[mm_choice]()
            return self._instances[mm_choice]

        # 2) Fallback : priorité statique historique.
        for backend_name in self.BACKEND_PRIORITY:
            if backend_name in self._backends and availability.get(backend_name, False):
                if backend_name not in self._instances:
                    self._instances[backend_name] = self._backends[backend_name]()
                logger.info(f"[TranscriberManager] Auto-selected: {backend_name}")
                return self._instances[backend_name]

        # Try any available backend not in priority list
        for name, available in availability.items():
            if available:
                if name not in self._instances:
                    self._instances[name] = self._backends[name]()
                logger.info(f"[TranscriberManager] Fallback to: {name}")
                return self._instances[name]

        raise RuntimeError(
            "No transcription backend available. "
            "Install faster-whisper (pip install faster-whisper) "
            "or transformers+soundfile for Qwen3-ASR."
        )

    def get_backends_info(self) -> List[Dict]:
        """
        Get information about all registered backends.

        Returns:
            List of backend info dicts.
        """
        availability = self.check_availability()
        result = []

        for name, backend_class in self._backends.items():
            info = {
                'name': name,
                'display_name': backend_class.display_name,
                'description': getattr(backend_class, 'description', ''),
                'description_long': getattr(backend_class, 'description_long', ''),
                'available': availability.get(name, False),
                'supports_diarization': backend_class.supports_diarization,
                'supports_timestamps': backend_class.supports_timestamps,
                'supports_hotwords': backend_class.supports_hotwords,
                'min_vram_gb': backend_class.min_vram_gb,
                'recommended_vram_gb': backend_class.recommended_vram_gb,
            }
            result.append(info)

        return result

    def unload_all(self) -> None:
        """Unload all loaded backend instances."""
        for name, instance in self._instances.items():
            try:
                if instance.is_loaded:
                    instance.unload()
                    logger.info(f"[TranscriberManager] Unloaded: {name}")
            except Exception as e:
                logger.warning(f"[TranscriberManager] Error unloading {name}: {e}")

        self._instances.clear()


# Module-level convenience functions

def backend_choice_values() -> List[str]:
    """Domaine SERVEUR du select « Moteur de transcription » (`transcriber/params.py`, déclaré
    `options_domain`) : les moteurs ENREGISTRÉS, puis les clés de catalogue qu'ils servent
    (`transcriber:qwen3-asr-1.7b`) — `get_backend` traduit les secondes vers leur moteur.

    POURQUOI (essai de l'assistant du 2026-09-28) : le schéma ne rend en statique que « auto »,
    les moteurs arrivent par le navigateur ; la porte des outils prenait ce préfixe pour le
    domaine entier et refusait à l'assistant TOUT moteur explicite. Enregistrés, pas seulement
    disponibles : la disponibilité se juge au lancement, où un moteur absent est remplacé par
    le meilleur disponible (journalisé)."""
    manager = TranscriberBackendManager.get_instance()
    values = list(manager._backends)
    try:
        from wama.model_manager.models import AIModel
        for key in AIModel.objects.filter(source='transcriber').values_list('model_key', flat=True):
            if manager._backend_for_model_key(key) in manager._backends:
                values.append(key)
        # Les modèles DISTANTS de transcription (2026-09-30) : le domaine dit ce qui EXISTE ; qui
        # a le droit de l'appeler se juge au lancement (`_remote_backend`, garde `cloud_access`).
        values += [row.model_key for row in remote_transcription_models()]
    except Exception as e:
        logger.debug(f"[TranscriberManager] catalogue unreadable for the choice domain: {e}")
    return values


def remote_transcription_models() -> list:
    """Lignes DISTANTES du catalogue, de tâche transcription, qu'un backend sait appeler."""
    from wama.common.backends.manager import backend_for_model
    from wama.model_manager.models import AIModel, EXECUTION_CLOUD
    kept = []
    for row in AIModel.objects.filter(execution=EXECUTION_CLOUD, is_available=True,
                                      capabilities__task='transcription').order_by('model_key'):
        cls = backend_for_model(row)
        if cls is not None and issubclass(cls, SpeechToTextBackend):
            kept.append(row)
    return kept


def get_backend(name: str = None, user=None) -> SpeechToTextBackend:
    """
    Get a transcription backend instance.

    Args:
        name: Backend name ('whisper', 'vibevoice', 'auto', or None), or a catalogue model key.
        user: whose rights and key a remote model is called with.

    Returns:
        Backend instance.
    """
    return TranscriberBackendManager.get_instance().get_backend(name, user=user)


def get_available_backends() -> List[str]:
    """
    Get list of available backend names.

    Returns:
        List of available backend names.
    """
    return TranscriberBackendManager.get_instance().get_available_backends()


def get_backends_info() -> List[Dict]:
    """
    Get information about all backends.

    Returns:
        List of backend info dicts.
    """
    return TranscriberBackendManager.get_instance().get_backends_info()
