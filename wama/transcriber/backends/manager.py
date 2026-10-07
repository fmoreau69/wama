"""
Transcriber Backend Manager

Manages transcription backend registration, availability checking, and selection.

DEPUIS LE 2026-09-30 (route F4b, étape ⑦ — décision de Fabien) la valeur du select « Modèle de
transcription » est une CLÉ DE CATALOGUE (`transcriber:qwen3-asr-1.7b`, `albert:whisper-large-v3`),
et le moteur se RÉSOUT par le lien commun modèle ↔ moteur (`backend_for_key`) : la table par
sous-chaîne (« qwen » → qwen_asr, « whisper » → whisper) n'existait que parce que les options
n'étaient pas les clés du catalogue — elle est tombée avec lui. Les anciens NOMS DE MOTEUR se
lisent encore (valeurs d'avant la migration 0027, appels d'outils, fichiers de lot) par une
correspondance DÉCLARÉE : `LEGACY_ENGINE_MODELS`.
"""

import logging
import sys
from typing import Dict, List, Optional, Type

from wama.common.backends.speech_to_text_base import SpeechToTextBackend

logger = logging.getLogger(__name__)

#: Anciens NOMS DE MOTEUR stockés avant le grain modèle → le modèle que chacun chargeait par
#: DÉFAUT (mesuré le 2026-09-30 dans les backends) : Whisper large-v3, `QwenASRBackend.DEFAULT_MODEL`
#: = 1.7B, `NemoASRBackend.DEFAULT_MODEL` = Parakeet TDT 0.6B v3. Une DONNÉE de compatibilité
#: (valeurs stockées, fichiers de lot, appels d'outils), pas une table de traduction d'options :
#: les options SONT des clés. Recopiée telle quelle par la migration 0027 (qui ne doit pas dépendre
#: du code courant). ⚠ Le JS d'avant associait `qwen_asr` au 0.6B : c'était faux.
LEGACY_ENGINE_MODELS = {
    'whisper': 'transcriber:whisper',
    'vibevoice': 'transcriber:vibevoice-asr',
    'qwen_asr': 'transcriber:qwen3-asr-1.7b',
    'nemo': 'transcriber:parakeet-tdt-0.6b-v3',
}

#: Repli du tirage « auto » quand le catalogue ne propose rien (première installation).
DEFAULT_MODEL_KEY = 'transcriber:whisper'

# La politique « Whisper d'abord » et l'entrée que la card fournit (un audio) se DÉCLARENT au
# schéma (`params.py`, `options_resolution` du select) depuis le 2026-10-01 : le lancement et la
# PRÉVISION du select les lisent au même endroit. Elles vivaient ici, lues par le seul lancement.


def catalogue_value(value) -> str:
    """La valeur du select dans l'ESPACE DES CLÉS : `auto` et le vide inchangés, un ancien nom de
    moteur → son modèle par défaut, un identifiant nu → clé du transcriber, une clé → telle quelle."""
    from wama.common.utils.model_keys import catalog_key
    v = (value or '').strip()
    if v in LEGACY_ENGINE_MODELS:
        return LEGACY_ENGINE_MODELS[v]
    return catalog_key(v, 'transcriber')


def is_auto_value(value) -> bool:
    from wama.common.utils.auto_model import is_auto
    return is_auto(value)


def resolve_auto_key(item=None, user=None) -> str:
    """Le modèle que « auto » retient MAINTENANT — une clé de catalogue. Brique COMMUNE : même
    domaine que les options (`transcriber/params.py`), curseur de l'élément, distants que le
    profil ouvre au tirage automatique (`options_cloud`), politique Whisper d'abord et entrée
    fournie (`options_resolution`) — tout lu au schéma, comme la prévision du select."""
    from wama.common.utils.auto_model import resolve_model_choice
    return resolve_model_choice('auto', app_id='transcriber', item=item, user=user,
                                fallback=DEFAULT_MODEL_KEY) or DEFAULT_MODEL_KEY


class TranscriberBackendManager:
    """
    Manager for transcription backends.

    Handles backend registration, availability checking, and resolution of a catalogue model
    to the backend that runs it.
    """

    # Priority order of the STATIC fallback (catalogue empty or unreadable) — the automatic draw
    # itself goes through the common brick (`resolve_auto_key`, same whisper-first policy).
    # Whisper d'abord : meilleure qualité FR, plus léger (~10 GB vs 16 GB pour VibeVoice), et la
    # diarisation est assurée par pyannote (backend-agnostique).
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
        The backend that runs `name` — a catalogue key (`transcriber:qwen3-asr-1.7b`,
        `albert:whisper-large-v3`), an old engine name (`whisper`, `qwen_asr`…), or `auto`/None.

        Args:
            name: what the card asks for.
            user: whose rights and key a REMOTE model is called with (`_remote_backend`).

        Raises:
            RuntimeError: nothing serves `name` (never a silent substitute for an explicit model),
                          or no backend at all is available.
        """
        if name is None or is_auto_value(name):
            return self._get_best_backend(user=user)
        # Un NOM DE MOTEUR enregistré (smoke nocturne, aligneur, ancienne valeur) : ce moteur.
        if name in self._backends:
            return self._engine_instance(name, user=user)
        key = catalogue_value(name)
        # Un modèle DISTANT passe AVANT tout repli : lui substituer un moteur local serait une
        # réponse fausse — et, pour la confidentialité, l'inverse d'une réponse fausse ne vaut pas mieux.
        if self._is_remote_key(key):
            return self._remote_backend(key, user)
        engine = self._backend_for_model_key(key)
        if engine is None:
            raise RuntimeError(
                f"« {key} » : aucun backend de transcription ne sert ce modèle (absent du "
                "catalogue, moteur non déclaré, ou poids installés sans backend).")
        return self._engine_instance(engine, user=user)

    def _engine_instance(self, engine: str, user=None, fallback: bool = True) -> SpeechToTextBackend:
        """L'instance du moteur `engine`, s'il est disponible — sinon, `fallback`, le meilleur
        disponible (repli TRANSPARENT : le worker le dit, `honours`)."""
        availability = self.check_availability()
        if not availability.get(engine, False):
            # Demandé explicitement : avant de replier, forcer un re-test (l'indispo peut être une
            # race d'import transitoire au démarrage, déjà résorbée au moment où la tâche tourne).
            logger.info(f"[TranscriberManager] {engine} marqué indisponible — re-test forcé")
            availability = self.check_availability(force=True)
        if not availability.get(engine, False):
            if not fallback:
                return None
            logger.warning(f"[TranscriberManager] Backend not available: {engine}")
            return self._get_best_backend(user=user)
        if engine not in self._instances:
            self._instances[engine] = self._backends[engine]()
        return self._instances[engine]

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

    @classmethod
    def _backend_for_model_key(cls, value: str) -> Optional[str]:
        """NOM du moteur enregistré qui exécute `value` (clé, identifiant nu ou ancien nom de
        moteur), ou None. Résolu par le CATALOGUE (`backend_for_key`) — plus par sous-chaîne."""
        if value in LEGACY_ENGINE_MODELS:
            return value
        key = catalogue_value(value)
        if not key or is_auto_value(key) or cls._is_remote_key(key):
            return None
        try:
            from wama.common.backends.manager import backend_for_key
            klass = backend_for_key(key)
        except Exception as e:
            logger.debug(f"[TranscriberManager] {key} : résolution impossible ({e})")
            return None
        if klass is None:
            return None
        backends = cls.get_instance()._backends
        for name, registered in backends.items():
            if registered is klass:
                return name
        # Un backend de transcription VALIDÉ par la chaîne d'intégration (2026-10-01 : FrWhisper,
        # Kyutai) vit dans `common/backends/` sans figurer à `_register_backends` : sans ceci, le
        # catalogue le résolvait et la card répondait « aucun backend ne sert ce modèle ». Le
        # gestionnaire ADOPTE ce que le catalogue lui désigne — il ne connaît pas ses producteurs.
        if (isinstance(klass, type) and issubclass(klass, SpeechToTextBackend)
                and klass.name and klass.name not in backends):
            backends[klass.name] = klass
            logger.info(f"[TranscriberManager] Adopted: {klass.name} ({key})")
            return klass.name
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
        owner = backend if isinstance(backend, type) else type(backend)
        # La liste vit sur la CLASSE (NeMo, Qwen) ou au niveau du MODULE (backends écrits par la
        # chaîne d'intégration, comme ceux de l'imager) : la même double lecture que l'inventaire
        # (`backend_inventory`). La casse du catalogue (`aihpi/FrWhisper`) ne décide pas.
        served = (getattr(owner, 'SUPPORTED_MODELS', None)
                  or getattr(sys.modules.get(owner.__module__), 'SUPPORTED_MODELS', None) or {})
        return next((declared for declared in served if str(declared).lower() == model_id), None)

    @classmethod
    def honours(cls, backend, requested: str) -> bool:
        """Le backend retenu est-il celui que la demande désignait (nom de moteur OU modèle du
        catalogue) ? Faux = un vrai repli, à dire à l'utilisateur. Comparer les noms seuls
        disait « indisponible — repli » pour `transcriber:qwen3-asr-1.7b` servi… par Qwen3-ASR."""
        if not requested or is_auto_value(requested):
            return True
        if getattr(backend, 'catalogue_key', '') == requested:
            return True
        return backend.name == requested or cls._backend_for_model_key(requested) == backend.name

    @classmethod
    def catalogue_key_for(cls, backend_name: str, loaded_model: str = '', requested: str = '') -> str:
        """Clé catalogue du modèle EFFECTIVEMENT utilisé par un moteur LOCAL.

        Le moteur (`whisper`, `qwen_asr`…) ne suffit pas quand le catalogue en porte plusieurs
        variantes (`qwen3-asr-0.6b` / `-1.7b`) : le modèle CHARGÉ tranche (`_current_model`
        du contrat `speech_to_text_base`, lu AVANT `unload()`, qui le remet à None). Une mesure
        attribuée au mauvais modèle fausserait son indice interne — on préfère alors la clé du
        moteur, qui ne prétend pas savoir la variante.

        `requested` : la demande de la card. Un modèle installé par la PROSPECTION
        (`huggingface:linagora/…`, `huggingface:aihpi/FrWhisper`) n'est pas rangé sous la source
        `transcriber` ; sans elle, ses mesures partaient sous la clé du moteur (`transcriber:nemo`)
        — 2026-10-01. Elle n'est retenue que si ce moteur la sert, et le modèle chargé tranche
        toujours.
        """
        try:
            from wama.model_manager.models import AIModel
            keys = [k for k in AIModel.objects.filter(source='transcriber')
                    .values_list('model_key', flat=True)
                    if cls._backend_for_model_key(k) == backend_name]
        except Exception:
            keys = []
        wanted = catalogue_value(requested) if requested else ''
        if (wanted and wanted not in keys and not is_auto_value(wanted)
                and cls._backend_for_model_key(wanted) == backend_name):
            keys.append(wanted)
        if len(keys) == 1:
            return keys[0]
        loaded = (loaded_model or '').lower().rsplit('/', 1)[-1]
        matching = [k for k in keys if k.split(':', 1)[-1].lower().rsplit('/', 1)[-1] == loaded]
        if len(matching) == 1:
            return matching[0]
        return f'transcriber:{backend_name}' if backend_name else ''

    def _get_best_backend(self, user=None) -> SpeechToTextBackend:
        """
        The best available backend, for callers that hold no card (the worker draws « auto » itself,
        with the card's cursor — `resolve_auto_key(item=…)`).

        1) The COMMON draw (`resolve_auto_key`) → its catalogue key → its backend.
        2) Failing that (empty catalogue, unresolvable draw, engine unavailable), the historical
           static priority `BACKEND_PRIORITY` — no regression.

        Raises:
            RuntimeError: If no backend is available.
        """
        try:
            key = resolve_auto_key(user=user)
            if self._is_remote_key(key):
                return self._remote_backend(key, user)
            engine = self._backend_for_model_key(key)
            instance = self._engine_instance(engine, fallback=False) if engine else None
            if instance is not None:
                logger.info(f"[TranscriberManager] auto → {key} → backend '{engine}'")
                return instance
        except Exception as e:
            logger.debug(f"[TranscriberManager] tirage commun indisponible ({e}) → priorité statique")

        availability = self.check_availability()
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

# `backend_choice_values` et `remote_transcription_models` RETIRÉES le 2026-10-07 (REMOVAL_LEDGER) :
# le domaine de porte (`options_domain`) du select n'existe plus — règle UNIQUE de toutes les
# apps, sans annonce à l'outil ; l'assistant découvre les modèles par `list_ai_models`.


_ENGINE_NAME_CACHE: Dict[str, tuple] = {}


def engine_name_for(value) -> str:
    """Le NOM du moteur qui exécute `value` (`whisper`, `qwen_asr`, `albert`…) — la clé sous
    laquelle l'estimation de durée apprend (`make_key('transcriber', backend.name)`), '' si aucun.

    Lu à chaque rafraîchissement de la progression d'une card : un ancien nom et un distant se
    lisent sans résolution, le reste est mémorisé une minute (une résolution relit l'inventaire)."""
    import time
    v = (value or '').strip()
    if not v or is_auto_value(v):
        return ''
    if v in LEGACY_ENGINE_MODELS:
        return v
    key = catalogue_value(v)
    back = {k: name for name, k in LEGACY_ENGINE_MODELS.items()}
    if key in back:
        return back[key]
    if TranscriberBackendManager._is_remote_key(key):
        return key.split(':', 1)[0]
    now = time.monotonic()
    hit = _ENGINE_NAME_CACHE.get(key)
    if hit is None or now - hit[0] > 60:
        hit = _ENGINE_NAME_CACHE[key] = (now, TranscriberBackendManager._backend_for_model_key(key) or '')
    return hit[1]


def filters_speech(value) -> bool:
    """Le moteur qui exécute `value` (clé de catalogue ou ancien nom) honore-t-il le filtre de
    parole (`supports_vad_filter`) ? Lu sur la CLASSE, sans instancier ni appeler le fournisseur
    — pour qui pose des configurations (`asr_eval_corpus`) sans rien exécuter."""
    key = catalogue_value(value)
    manager = TranscriberBackendManager.get_instance()
    cls = manager._backends.get(engine_name_for(key))
    if cls is None and TranscriberBackendManager._is_remote_key(key):
        from wama.common.backends.manager import backend_for_model
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=key).first()
        cls = backend_for_model(row) if row is not None else None
    return bool(cls is not None and getattr(cls, 'supports_vad_filter', False))


def get_backend(name: str = None, user=None) -> SpeechToTextBackend:
    """
    Get a transcription backend instance.

    Args:
        name: a catalogue model key, an old engine name ('whisper', 'qwen_asr'…), 'auto' or None.
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
