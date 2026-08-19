"""
Model Registry - Unified model discovery across all WAMA apps and external sources.
"""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from .model_quality import (
    indice_qualite as _indice_qualite,
    params_actifs_b as _params_actifs,
    params_en_milliards as _params_b,
)
from enum import Enum

logger = logging.getLogger(__name__)


#: SPÉCIALISATION déclarée d'un modèle Ollama : préfixe de famille → domaine de spécialité.
#: Troisième axe, distinct des deux autres (2026-08-19) : `ModelType` dit ce qu'un modèle EST,
#: `capabilities`/`ModelTask` ce qu'il SAIT FAIRE, et ceci ce POUR QUOI il est fait. Ollama ne
#: l'expose pas — `translategemma:12b` rend `completion, vision`, exactement comme un
#: généraliste : un spécialiste entrait donc dans le pool généraliste de `select_model()`
#: (et son absence des benchmarks tiers y rendait l'étage de mesure inerte).
#: Déclaration HUMAINE, jamais devinée ; un modèle spécialisé n'est retenu que si l'appelant
#: demande sa spécialité (`select_model(specialisation='translation')`).
SPECIALISATIONS_OLLAMA = {
    'translategemma': 'translation',   # Google, variante Gemma dédiée à la traduction
}


def _check_hf_model_downloaded(cache_dir: Path, hf_id: str) -> bool:
    """
    Check if a HuggingFace model is downloaded in the cache directory.

    HuggingFace cache structure: models--<org>--<model>/snapshots/<hash>/
    """
    if not cache_dir or not hf_id:
        return False

    try:
        cache_dir = Path(cache_dir)
        if not cache_dir.exists():
            return False

        # Convert hf_id to cache folder name (e.g., "Wan-AI/Wan2.2-T2V" -> "models--Wan-AI--Wan2.2-T2V")
        folder_name = f"models--{hf_id.replace('/', '--')}"
        model_path = cache_dir / folder_name

        # Simple check: if the model folder exists, consider it downloaded
        if model_path.exists() and model_path.is_dir():
            # Verify it has some content (snapshots or blobs)
            snapshots = model_path / "snapshots"
            blobs = model_path / "blobs"
            if snapshots.exists() or blobs.exists():
                return True

        # Scan cache dir for matching folders (handles nested/varied structures)
        try:
            for path in cache_dir.iterdir():
                if path.is_dir() and folder_name in path.name:
                    return True
        except (PermissionError, OSError):
            pass

    except Exception as e:
        logger.debug(f"Error checking HF model {hf_id}: {e}")

    return False


# Taxonomie UNIQUE : celle du modele Django. Elle etait REDECLAREE ici a l'identique, et les deux
# copies ont derive trois fois — 'music'/'ocr', puis 'composer'/'reader', puis 'embedding' (ecrit
# en base sans figurer dans aucune des deux). Les commentaires << alignees sur l'enum de decouverte >>
# cote models.py traitaient le symptome ; la cause etait le doublon. Reexporte pour que les imports
# existants (`from .model_registry import ModelType, ModelSource`) restent valides.
from ..models import ModelType, ModelSource  # noqa: F401,E402


# (idem ModelType : la source vient de models.py, plus de copie ici.)


@dataclass
class ModelInfo:
    """Unified model information structure."""
    id: str
    name: str
    model_type: ModelType
    source: ModelSource
    description: str = ""
    description_short: str = ""   # une ligne pour l'aide sous le sélecteur (sinon dérivé du long)
    hf_id: Optional[str] = None
    vram_gb: float = 0
    ram_gb: float = 0
    #: Indice de qualité a priori (cf. `model_quality.py`). None = inconnu, PAS zéro : le tri
    #: doit pouvoir distinguer « pas mesuré » de « mauvais ».
    quality_index: Optional[float] = None
    is_loaded: bool = False
    is_downloaded: bool = False
    backend_ref: Optional[str] = None
    extra_info: Dict = field(default_factory=dict)
    # Format policy fields
    format: str = ""  # Current format: 'pt', 'safetensors', 'onnx', 'bin', etc.
    preferred_format: str = ""  # Recommended format per policy
    can_convert_to: List[str] = field(default_factory=list)  # Available conversions
    capabilities: Dict = field(default_factory=dict)  # cloning/languages/classes/task… (cf. AIModel.capabilities)


class ModelRegistry:
    """Central registry for all WAMA models."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._models: Dict[str, ModelInfo] = {}
        self._initialized = True

    def discover_all_models(self) -> Dict[str, ModelInfo]:
        """Discover models from all sources."""
        self._models.clear()

        logger.info("[ModelRegistry] Starting model discovery...")

        # Ollama D'ABORD : c'est un listing EXTERNE, sans dépendance sur les autres.
        # Les apps dont un moteur est SERVI par Ollama (reader/glm-ocr) s'appuient sur
        # sa présence pour se dire téléchargées — l'inverse n'est jamais vrai.
        self._discover_ollama_models()

        self._discover_imager_models()
        self._discover_describer_models()
        self._discover_anonymizer_models()
        self._discover_transcriber_models()
        self._discover_synthesizer_models()
        self._discover_enhancer_models()
        self._discover_avatarizer_models()
        self._discover_composer_models()
        self._discover_reader_models()
        self._discover_depth_models()

        self._overlay_residency()

        # Log summary
        formats_found = {}
        preferred_formats_found = {}
        for model in self._models.values():
            fmt = model.format or 'EMPTY'
            pref = model.preferred_format or 'EMPTY'
            formats_found[fmt] = formats_found.get(fmt, 0) + 1
            preferred_formats_found[pref] = preferred_formats_found.get(pref, 0) + 1

        logger.info(
            f"[ModelRegistry] Discovery complete. Total: {len(self._models)} models. "
            f"Formats: {formats_found}. Preferred: {preferred_formats_found}"
        )

        return self._models

    @staticmethod
    def refresh_ollama_residency() -> int:
        """
        DÉCLARE au gouverneur les modèles résidents dans l'OLLAMA HÔTE (`/api/ps`), et
        retire ceux qui n'y sont plus. Retourne le nombre de résidents déclarés.

        TROU COMBLÉ LE 2026-08-19 (question Fabien : « le LLM est resté chargé mais je vois
        *No idle models detected* »). Le gouverneur ne connaissait la résidence que par les
        enveloppes de `BaseModelBackend` (in-process) et `vram_reservation` (sous-process) :
        Ollama, service SÉPARÉ, n'y a jamais eu de ligne. `AIModel.is_loaded` disait vrai
        (il vient d'ici, `/api/ps`) mais `resident_models()`/`idle_models()` — donc la vue
        « modèles inactifs » et le nettoyeur — étaient AVEUGLES à plusieurs Go occupés.

        Owner `ollama-host#ollama:<nom>` : le préfixe identifie le détenteur (le service),
        le suffixe porte la clé catalogue (cf. `model_key_of`) pour que le modèle apparaisse
        nommément dans `resident_models()`. Réservation RAFRAÎCHIE à chaque passage — donc
        jamais périmée par le TTL tant que le sync tourne, et retirée dès qu'Ollama a
        déchargé (`OLLAMA_KEEP_ALIVE`, 5 min par défaut).
        """
        from wama.common.services.resource_governor import (OWNER_MODEL_SEP,
                                                            release_reservation,
                                                            reservations, reserve_vram)
        prefixe = f"ollama-host{OWNER_MODEL_SEP}"
        try:
            charges = ModelRegistry._ollama_charges()
        except Exception:
            return 0
        vivants = set()
        for nom, go in charges.items():
            if not nom:
                continue
            owner = f"{prefixe}ollama:{nom}"
            vivants.add(owner)
            reserve_vram(owner, float(go or 0))
        # Ollama a déchargé (keep_alive écoulé) → la ligne doit disparaître TOUT DE SUITE :
        # laisser expirer au TTL ferait croire le GPU occupé pendant une heure.
        for owner in reservations():
            if owner.startswith(prefixe) and owner not in vivants:
                release_reservation(owner)
        return len(vivants)

    def _overlay_residency(self):
        """Rabat la résidence RÉELLE (registre VRAM partagé) sur `is_loaded`.

        EN UN SEUL ENDROIT, après toutes les découvertes, et non dans chacune des
        douze `_discover_*` : sur ces douze, neuf ne calculaient pas `is_loaded` du
        tout (valeur par défaut False) et deux le déduisaient d'un singleton du
        process COURANT — or la découverte tourne dans le worker gunicorn tandis que
        les modèles sont chargés par les workers Celery et le service TTS. Le
        compteur « Loaded » du model_manager ne pouvait donc qu'afficher 0.

        On n'écrase jamais un `is_loaded` déjà vrai : Ollama le tient d'une source
        inter-process légitime (`/api/ps`) et n'apparaît pas au registre VRAM.
        """
        try:
            # Déclarer d'abord la résidence Ollama (service séparé) : sans ce passage, le
            # registre partagé ignore plusieurs Go réellement occupés (2026-08-19).
            self.refresh_ollama_residency()
            from wama.common.services.resource_governor import resident_models
            residents = resident_models()
        except Exception as e:
            logger.debug(f"[ModelRegistry] résidence indisponible : {e}")
            return
        if not residents:
            return
        touches = 0
        for model in self._models.values():
            cle = f"{model.source.value}:{model.id}"
            if cle in residents and not model.is_loaded:
                model.is_loaded = True
                touches += 1
        if touches:
            logger.info(f"[ModelRegistry] résidence réelle : {touches} modèle(s) chargé(s)")

    def get_models_by_type(self, model_type: ModelType) -> List[ModelInfo]:
        """Get all models of a specific type."""
        return [m for m in self._models.values() if m.model_type == model_type]

    def get_loaded_models(self) -> List[ModelInfo]:
        """Get all currently loaded models."""
        return [m for m in self._models.values() if m.is_loaded]

    def _discover_imager_models(self):
        """Discover Imager app models (HunyuanImage, SD, CogVideoX, LTX, Mochi, QwenImage)."""
        try:
            from wama.imager.utils.model_config import (
                IMAGER_MODELS, HUNYUAN_MODELS,
                COGVIDEOX_MODELS, LTX_MODELS, MOCHI_MODELS,
                QWEN_IMAGE_MODELS, LOGO_MODELS,
                HUNYUAN_DIR, STABLE_DIFFUSION_DIR,
                COGVIDEOX_DIR, LTX_DIR, MOCHI_DIR,
                QWEN_IMAGE_DIR, FLUX_DIR, LOGO_DIR,
                get_model_info,
            )
            from django.conf import settings

            # Check for loaded backends
            loaded_model = None
            try:
                from wama.imager.backends.manager import get_manager
                manager = get_manager()
                if hasattr(manager, '_instances') and manager._instances:
                    for backend in manager._instances.values():
                        if hasattr(backend, '_current_model') and backend._current_model:
                            loaded_model = backend._current_model
                            break
            except Exception:
                pass

            # HuggingFace cache directory (fallback check only)
            hf_cache = settings.MODEL_PATHS.get('cache', {}).get('huggingface')

            for model_id, config in IMAGER_MODELS.items():
                is_loaded = model_id == loaded_model
                hf_id = config.get('hf_id')

                # Determine cache directory using centralized get_model_info()
                try:
                    model_info = get_model_info(model_id)
                    cache_dir = Path(model_info['cache_dir'])
                except Exception:
                    cache_dir = Path(STABLE_DIFFUSION_DIR)

                # Check if model is downloaded
                is_downloaded = _check_hf_model_downloaded(cache_dir, hf_id)

                # Also check main HF cache if not found
                if not is_downloaded and hf_cache:
                    is_downloaded = _check_hf_model_downloaded(Path(hf_cache), hf_id)

                name = config.get('description', model_id)

                # Detect format from HuggingFace cache directory
                model_format = ''
                if is_downloaded and hf_id:
                    # Try to detect format from the model's specific cache folder
                    hf_folder_name = f"models--{hf_id.replace('/', '--')}"
                    specific_cache = cache_dir / hf_folder_name
                    if specific_cache.exists():
                        model_format = self._detect_model_format(str(specific_cache))
                        logger.debug(f"[ModelRegistry] {model_id}: Detected format from specific cache: {model_format}")
                    # Fallback to parent directory
                    if not model_format:
                        model_format = self._detect_model_format(str(cache_dir))
                        if model_format:
                            logger.debug(f"[ModelRegistry] {model_id}: Detected format from parent dir: {model_format}")
                    # Default for diffusion models if nothing found
                    if not model_format:
                        model_format = 'safetensors'  # Most HF models use safetensors now
                        logger.debug(f"[ModelRegistry] {model_id}: Using default format: safetensors")
                else:
                    # For non-downloaded models, we assume safetensors as that's the HuggingFace standard
                    model_format = 'safetensors'
                    logger.debug(f"[ModelRegistry] {model_id}: Not downloaded, assuming format: safetensors")

                # Get preferred format for diffusion models
                preferred = self._get_preferred_format(ModelType.DIFFUSION)
                convert_options = self._get_conversion_options(model_format, ModelType.DIFFUSION)

                # Get VRAM from config
                vram_gb = config.get('vram_gb', 0)
                if not vram_gb:
                    vram_gb = config.get('vram', 0)  # Alternative key name

                logger.info(
                    f"[ModelRegistry] Discovered imager model: {model_id}, "
                    f"format={model_format or 'EMPTY'}, preferred={preferred or 'EMPTY'}, "
                    f"vram_gb={vram_gb}, downloaded={is_downloaded}"
                )

                # Capacités : LUES sur le manifeste (`type` + `mode`), jamais devinées.
                # ⚠️ Une version précédente reniflait le NOM du modèle
                # (`any(k in model_id for k in ('video','cogvideo','ltx','mochi','wan'))`) :
                # tout nouveau modèle vidéo au nom imprévu était classé « image », et surtout
                # la distinction t2v/i2v — pourtant DÉCLARÉE au manifeste — était perdue, si
                # bien qu'aucun filtrage par capacité n'était possible en aval.
                _img_type = (config.get('type') or '').lower()
                _is_video = _img_type == 'video'
                # Vocabulaire du manifeste : 't2i' | 't2v' | 'i2v' | 't2v+i2v' | 'edit' | 'i2i'
                # ('i2i' = image de référence acceptée pour une sortie image — SD img2img ;
                # 'edit' = modèle DÉDIÉ à l'édition, la tâche canonique devient image-to-image).
                # Quelques entrées historiques écrivent encore les libellés longs.
                _mode = (config.get('mode') or '').lower()
                for _long, _short in (('text-to-image', 't2i'), ('text-to-video', 't2v'),
                                      ('image-to-video', 'i2v'), ('image-to-image', 'edit')):
                    _mode = _mode.replace(_long, _short)
                _tasks = {t for t in ('t2i', 't2v', 'i2v', 'edit', 'i2i') if t in _mode}
                if not _tasks:                      # mode absent → déduit de la modalité
                    _tasks = {'t2v'} if _is_video else {'t2i'}
                # Traduction en vocabulaire CANONIQUE (`CANONICAL_CAPABILITIES`) : `task` au
                # format HF + entrées consommées en ids d'`INPUT_TYPES`. Le `mode` du manifeste
                # est un raccourci d'app ; il ne doit pas fuiter tel quel dans le catalogue.
                if _is_video:
                    _task = 'image-to-video' if _tasks == {'i2v'} else 'text-to-video'
                elif 'edit' in _tasks:
                    _task = 'image-to-image'
                else:
                    _task = 'text-to-image'
                _inputs_required = ['prompt']
                _inputs_optional = []
                if _tasks & {'i2v', 'edit', 'i2i'}:
                    # L'image est OBLIGATOIRE si le modèle ne sait faire que ça, OPTIONNELLE
                    # s'il sait aussi partir d'un simple prompt (LTX = t2v+i2v, SD = t2i+i2i).
                    (_inputs_required if _tasks <= {'i2v', 'edit', 'i2i'} else _inputs_optional
                     ).append('work_image')
                self._models[f"imager:{model_id}"] = ModelInfo(
                    id=f"imager:{model_id}",
                    name=name,
                    model_type=ModelType.DIFFUSION,
                    source=ModelSource.WAMA_IMAGER,
                    # Deux champs SÉPARÉS (format transcriber) : court sous le select,
                    # long autonome en overlay ⓘ (cf. model_config 'description_long').
                    description=config.get('description_long') or config.get('description', ''),
                    description_short=config.get('description', ''),
                    hf_id=hf_id,
                    vram_gb=vram_gb,
                    is_loaded=is_loaded,
                    is_downloaded=is_downloaded,
                    backend_ref='imager',
                    format=model_format,
                    preferred_format=preferred,
                    can_convert_to=convert_options,
                    capabilities={
                        'modalities': ['video'] if _is_video else ['image'],
                        'task': _task,
                        # Entrées consommées, en ids d'INPUT_TYPES — c'est ce qui permet
                        # l'appariement entrée↔modèle (`matches_inputs`) SANS drapeau ad hoc :
                        # un modèle image→vidéo EXIGE une image de travail, un modèle
                        # texte→vidéo ne l'exige pas, un modèle qui sait faire les deux la
                        # déclare OPTIONNELLE. La distinction t2v/i2v tombe donc du vocabulaire
                        # canonique, sans inventer de clé.
                        'inputs_required': _inputs_required,
                        'inputs_optional': _inputs_optional,
                        # Catégorie de spécialisation déclarée au manifeste (ex. 'logo') —
                        # sert au groupement du <select> (optgroup), jamais à un onglet.
                        **({'category': config['category']} if config.get('category') else {}),
                    },
                )
        except ImportError as e:
            logger.debug(f"Could not import Imager models: {e}")

    def _discover_describer_models(self):
        """Discover Describer app models (BLIP, Whisper)."""
        try:
            from wama.describer.utils.model_config import DESCRIBER_MODELS
            from django.conf import settings

            # Check if BLIP is loaded (backend sous contrat depuis 2026-08-17 —
            # l'ancien état de module _blip_model n'existe plus)
            blip_loaded = False
            try:
                from wama.describer.backends import get_blip
                blip_loaded = get_blip().is_loaded
            except Exception:
                pass

            # Get all possible model directories
            model_paths = settings.MODEL_PATHS

            for model_id, config in DESCRIBER_MODELS.items():
                model_type = ModelType.VLM
                if config.get('type') == 'summarization':
                    model_type = ModelType.SUMMARIZATION
                elif config.get('type') == 'speech-to-text':
                    model_type = ModelType.SPEECH

                is_loaded = model_id == 'blip' and blip_loaded
                hf_id = config.get('model_id')
                source_type = config.get('source', 'huggingface')

                # Check if model is downloaded
                is_downloaded = False
                model_format = ''
                cache_dirs = []

                # Special handling for Whisper (uses .pt files, not HuggingFace format)
                if 'whisper' in model_id.lower() or source_type == 'openai':
                    whisper_dir = model_paths.get('speech', {}).get('whisper')
                    if whisper_dir:
                        whisper_path = Path(whisper_dir)
                        if whisper_path.exists():
                            # Check for any .pt files (base.pt, small.pt, etc.)
                            pt_files = list(whisper_path.glob('*.pt'))
                            is_downloaded = len(pt_files) > 0
                            if is_downloaded:
                                model_format = 'pt'
                else:
                    # HuggingFace models (BLIP)
                    if 'blip' in model_id.lower():
                        blip_dir = model_paths.get('vlm', {}).get('blip')
                        if blip_dir:
                            cache_dirs.append(Path(blip_dir))

                    # Add generic directories as fallback
                    vlm_root = model_paths.get('vlm', {}).get('root')
                    if vlm_root:
                        cache_dirs.append(Path(vlm_root))
                    hf_cache = model_paths.get('cache', {}).get('huggingface')
                    if hf_cache:
                        cache_dirs.append(Path(hf_cache))

                    # Check if model is downloaded in any of the directories
                    for cache_dir in cache_dirs:
                        if cache_dir and cache_dir.exists():
                            if _check_hf_model_downloaded(cache_dir, hf_id):
                                is_downloaded = True
                                break

                # Detect format (for HF models it's typically safetensors or bin)
                if is_downloaded and not model_format:
                    # Try specific HF cache folder first
                    if hf_id:
                        hf_folder_name = f"models--{hf_id.replace('/', '--')}"
                        for cache_dir in cache_dirs:
                            specific_cache = cache_dir / hf_folder_name
                            if specific_cache.exists():
                                model_format = self._detect_model_format(str(specific_cache))
                                if model_format:
                                    break
                    # Fallback to scanning cache directories
                    if not model_format and cache_dirs:
                        for cache_dir in cache_dirs:
                            if cache_dir and cache_dir.exists():
                                model_format = self._detect_model_format(str(cache_dir))
                                if model_format:
                                    break

                # Default based on model type if not found (even for non-downloaded models)
                if not model_format:
                    if model_type == ModelType.SPEECH:
                        model_format = 'pt'  # Whisper-style models
                    else:
                        model_format = 'safetensors'  # Default for HF models

                # Get preferred format based on model type
                preferred = self._get_preferred_format(model_type)
                logger.debug(f"[ModelRegistry] Describer {model_id}: format={model_format}, preferred={preferred}")
                convert_options = self._get_conversion_options(model_format, model_type)

                self._models[f"describer:{model_id}"] = ModelInfo(
                    id=f"describer:{model_id}",
                    name=config.get('model_id', model_id),
                    model_type=model_type,
                    source=ModelSource.WAMA_DESCRIBER,
                    # Court/long séparés (format transcriber), cf. model_config 'description_long'.
                    description=config.get('description_long') or config.get('description', ''),
                    description_short=config.get('description', ''),
                    hf_id=hf_id,
                    vram_gb=config.get('size_gb', 2),
                    is_loaded=is_loaded,
                    is_downloaded=is_downloaded,
                    backend_ref='describer',
                    format=model_format,
                    preferred_format=preferred,
                    can_convert_to=convert_options,
                    # Capacités CANONIQUES : modalité d'entrée déduite du type de modèle.
                    # `task` + `inputs_required` complètent le tronc commun (2026-07-31) :
                    # sans eux, l'appariement entrée↔modèle (INPUT_MODEL_MATCHING.md) n'avait
                    # rien à comparer pour cette app et ne pouvait griser aucun moteur.
                    # Un décrypteur de texte (LLM) travaille sur le prompt, pas sur un fichier.
                    capabilities={
                        'modalities': (
                            ['image'] if model_type in (ModelType.VLM, ModelType.VISION)
                            else ['audio'] if model_type == ModelType.SPEECH
                            else ['text']),
                        'task': (
                            'captioning' if model_type in (ModelType.VLM, ModelType.VISION)
                            else 'transcription' if model_type == ModelType.SPEECH
                            else 'text-generation'),
                        'inputs_required': (
                            ['prompt'] if model_type not in (
                                ModelType.VLM, ModelType.VISION, ModelType.SPEECH)
                            else ['work_file']),
                    },
                )
        except ImportError as e:
            logger.debug(f"Could not import Describer models: {e}")

    def _discover_anonymizer_models(self):
        """Discover Anonymizer app models (YOLO, SAM3)."""
        try:
            from wama.anonymizer.utils.model_config import list_available_yolo_models

            yolo_models = list_available_yolo_models()
            for model_type, models in yolo_models.items():
                for model in models:
                    model_name = model['name']
                    specialty = model.get('specialty', '')
                    desc = f"YOLO {model_type}"
                    if specialty:
                        desc += f" ({specialty})"

                    # Size in MB to GB
                    size_gb = model.get('size', 0) / (1024 * 1024 * 1024)

                    # Detect format from path
                    model_path = model.get('path', '')
                    model_format = self._detect_model_format(model_path) if model_path else ''

                    # Default format for YOLO models
                    if not model_format:
                        model_format = 'pt'  # YOLO models are typically .pt files

                    # Get preferred format for vision models
                    preferred = self._get_preferred_format(ModelType.VISION)
                    logger.debug(f"[ModelRegistry] YOLO {model_name}: format={model_format}, preferred={preferred}")
                    convert_options = self._get_conversion_options(model_format, ModelType.VISION)

                    # Build model identifier matching the Anonymizer's model_selector format
                    # Format: {type}/{specialty}/{name} or {type}/{name}
                    if specialty:
                        model_id = f"{model_type}/{specialty}/{model_name}"
                    else:
                        model_id = f"{model_type}/{model_name}"

                    # Extra info with all details needed by Anonymizer's model_selector
                    extra_info = {
                        'path': model_path,
                        'yolo_type': model_type,  # detect, segment, pose, etc.
                        'specialty': specialty or None,  # faces, plates, faces&plates, or None
                        'size_bytes': model.get('size', 0),
                        'model_id': model_id,  # Anonymizer-style model identifier
                    }

                    # Try to get class list for the model (cached for performance)
                    class_list = self._get_yolo_model_classes(model_path, specialty)
                    if class_list:
                        extra_info['class_list'] = class_list

                    self._models[f"anonymizer:yolo:{model_name}"] = ModelInfo(
                        id=f"anonymizer:yolo:{model_name}",
                        name=model_name,
                        model_type=ModelType.VISION,
                        source=ModelSource.WAMA_ANONYMIZER,
                        description=desc,
                        vram_gb=round(size_gb * 2, 1),  # Estimate VRAM as 2x model size
                        is_downloaded=True,
                        extra_info=extra_info,
                        backend_ref='anonymizer',
                        format=model_format,
                        preferred_format=preferred,
                        can_convert_to=convert_options,
                        # Capacités : tâche YOLO + classes détectables (→ sélection par classe,
                        # filtrage UI : ne proposer qu'un modèle gérant les classes demandées).
                        # `inputs_required` : YOLO travaille sur le média déposé (image/vidéo),
                        # jamais sur un prompt — c'est ce qui l'oppose à SAM3 ci-dessous.
                        capabilities={'task': model_type, 'classes': class_list or [],
                                      'modalities': ['image', 'video'],
                                      'inputs_required': ['work_file']},
                    )

            # Add SAM3 if available
            try:
                from wama.anonymizer.utils.sam3_manager import get_sam3_status
                # Description = source unique dans le model_config de l'app (R9) — plus de hardcode.
                from wama.anonymizer.utils.model_config import REGISTRY_MODEL_DESCRIPTIONS as _ANON_DESC
                status = get_sam3_status()

                # SAM3 uses safetensors/pt format
                preferred = self._get_preferred_format(ModelType.VISION)

                self._models["anonymizer:sam3"] = ModelInfo(
                    id="anonymizer:sam3",
                    name="SAM3 (Segment Anything)",
                    model_type=ModelType.VISION,
                    source=ModelSource.WAMA_ANONYMIZER,
                    description=_ANON_DESC.get('sam3', {}).get('long', ''),
                    description_short=_ANON_DESC.get('sam3', {}).get('short', ''),
                    vram_gb=3.0,
                    is_downloaded=status.get('models_cached', False),
                    extra_info=status,
                    backend_ref='anonymizer',
                    format='safetensors',
                    preferred_format=preferred,
                    can_convert_to=['onnx'],
                    # SAM3 : segmentation pilotée par prompt texte (open-vocabulary) — il exige
                    # DONC le média ET le prompt, là où YOLO se contente du média. C'est
                    # exactement la distinction que l'appariement doit rendre visible dans l'UI
                    # (INPUT_MODEL_MATCHING.md), au lieu de la laisser échouer au lancement.
                    capabilities={'task': 'segment', 'text_promptable': True,
                                  'modalities': ['image', 'video'],
                                  'inputs_required': ['work_file', 'prompt']},
                )
            except Exception:
                pass

        except ImportError as e:
            logger.debug(f"Could not import Anonymizer models: {e}")

    def _discover_depth_models(self):
        """Modèles de profondeur monoculaire (task=depth-estimation) déposés par `pull_model`
        dans `models/vision/depth-pro/`.

        Scan FILESYSTEM volontaire : la découverte reste dans la couche model_manager et n'importe
        AUCUNE app. Le consommateur est le lab cam_analyzer (re-calage plan de sol, §[E]) — importer
        une app lab depuis le core serait une inversion de couche. `is_downloaded` se dérive donc de
        la présence réelle des poids, pas d'un statut d'app.
        """
        try:
            from django.conf import settings
            from pathlib import Path
            depth_cfg = (settings.MODEL_PATHS.get('vision', {}) or {}).get('depth')
            if not depth_cfg:
                return
            depth_root = Path(depth_cfg)
            cached = depth_root.exists() and any(depth_root.rglob('*.safetensors'))
            # Candidat retenu §[E] : Apple Depth Pro (métrique + focale estimée, natif transformers).
            # Retenu vs DA3 (2026-08-05) car intégration `AutoModelForDepthEstimation` sans package
            # custom, et l'intrinsèque estimé sert directement le re-calage du plan de sol. Une seule
            # entrée connue ; en ajouter d'autres = une ligne ModelInfo de plus ici.
            self._models['huggingface:depthpro'] = ModelInfo(
                id='huggingface:depthpro',
                name='Apple Depth Pro',
                model_type=ModelType.VISION,
                source=ModelSource.HUGGINGFACE,
                description='Profondeur monoculaire métrique + focale estimée, natif transformers '
                            '(Apache-2.0). Candidat cam_analyzer (re-calage du plan de sol, §[E]).',
                hf_id='apple/DepthPro-hf',
                vram_gb=8.0,
                is_downloaded=cached,
                # Vocabulaire canonique (model_capabilities) : tâche + entrées + modalités, comme
                # SAM3/YOLO — pas de flag ad hoc, pour que select_model/matches_inputs filtrent.
                capabilities={'task': 'depth-estimation', 'modalities': ['image', 'video'],
                              'inputs_required': ['work_file']},
            )
        except Exception as e:
            logger.debug(f"Could not discover depth models: {e}")

    def _discover_transcriber_models(self):
        """Discover Transcriber app models (Whisper, VibeVoice, Qwen3-ASR)."""
        try:
            from wama.transcriber.utils.model_config import (
                TRANSCRIBER_MODELS, WHISPER_DIR, VIBEVOICE_DIR, QWEN_ASR_DIR,
            )
            # Descriptions = SOURCE UNIQUE : les CLASSES backend (contrat BaseModelBackend,
            # attributs `description`/`description_long` — c'est ce que l'app AFFICHE via
            # get_backends_info/WamaModelHelp). Le catalogue en devient le MIROIR (R10).
            # Modules backend LÉGERS (libs lourdes lazy dans load()) — import sûr au sync.
            # NB : ne PAS instancier TranscriberBackendManager ici (registration paresseuse
            # → 0 backend) ; on importe les classes directement.
            from wama.transcriber.backends.whisper_backend import WhisperBackend
            from wama.transcriber.backends.vibevoice_backend import VibeVoiceBackend
            from wama.transcriber.backends.qwen_asr_backend import QwenASRBackend

            preferred = self._get_preferred_format(ModelType.SPEECH)
            whisper_dir = Path(WHISPER_DIR)
            vibevoice_dir = Path(VIBEVOICE_DIR)
            qwen_asr_dir = Path(QWEN_ASR_DIR)

            for model_id, config in TRANSCRIBER_MODELS.items():
                hf_id = config.get('hf_model_id', '')
                size_gb = config.get('size_gb', 0.5)
                vram_gb = config.get('vram_gb', size_gb)

                # Descriptions : COURT + LONG séparés, depuis la classe backend (= ce qui
                # s'affiche). Qwen = 2 modèles pour UN moteur → le COURT par-modèle vient de
                # la config (différencie 0.6B/1.7B), le LONG (paragraphe moteur) de la classe.
                if model_id.startswith('vibevoice-'):
                    _cls = VibeVoiceBackend
                elif model_id.startswith('qwen3-asr-'):
                    _cls = QwenASRBackend
                else:
                    _cls = WhisperBackend
                description_short = config.get('description') or _cls.description
                description_long = getattr(_cls, 'description_long', '') or description_short

                if model_id.startswith('vibevoice-'):
                    # HuggingFace hub format in vibevoice/
                    is_downloaded = _check_hf_model_downloaded(vibevoice_dir, hf_id)
                    name = "VibeVoice ASR"
                    fmt = 'safetensors'
                    extra = {'hf_id': hf_id, 'path': str(vibevoice_dir)}

                elif model_id.startswith('qwen3-asr-'):
                    # HuggingFace hub format in qwen_asr/
                    is_downloaded = _check_hf_model_downloaded(qwen_asr_dir, hf_id)
                    name = hf_id.split('/')[-1]   # "Qwen3-ASR-0.6B" / "Qwen3-ASR-1.7B"
                    fmt = 'safetensors'
                    extra = {'hf_id': hf_id, 'path': str(qwen_asr_dir)}

                else:
                    # Whisper : plusieurs formats possibles sur disque. On CONSTATE le
                    # contenu (helper robuste) au lieu de DEVINER les noms de dossiers.
                    # La variante réelle vient du hf_model_id ('openai/whisper-large-v3'
                    # → 'large-v3'), car model_id peut être abrégé ('large').
                    short_id = config.get('model_id', model_id.replace('whisper-', ''))
                    variant = (hf_id.split('/')[-1].replace('whisper-', '') if hf_id else short_id)
                    pt_file = whisper_dir / f"{short_id}.pt"          # openai-whisper .pt
                    pt_file_v = whisper_dir / f"{variant}.pt"
                    ct2_dir = whisper_dir / short_id                  # CTranslate2 direct
                    ct2_dir_v = whisper_dir / variant
                    # faster-whisper (Systran) et openai HF, via le helper robuste (gère
                    # models--org--name/snapshots, scan tolérant) — corrige le faux négatif
                    # 'faster-whisper-large' vs réel 'faster-whisper-large-v3'.
                    hf_ok = (
                        _check_hf_model_downloaded(whisper_dir, f"Systran/faster-whisper-{variant}")
                        or _check_hf_model_downloaded(whisper_dir, hf_id)
                    )
                    is_downloaded = (
                        pt_file.exists() or pt_file_v.exists()
                        or (ct2_dir.exists() and ct2_dir.is_dir())
                        or (ct2_dir_v.exists() and ct2_dir_v.is_dir())
                        or hf_ok
                    )
                    name = f"Whisper {short_id.capitalize()}"
                    fmt = 'pt'
                    path = (str(pt_file) if pt_file.exists()
                            else str(pt_file_v) if pt_file_v.exists()
                            else str(whisper_dir / f"models--Systran--faster-whisper-{variant}") if hf_ok
                            else str(ct2_dir_v) if ct2_dir_v.exists()
                            else str(ct2_dir))
                    extra = {'hf_id': hf_id, 'path': path if is_downloaded else ''}

                # Capacités CANONIQUES. ⚠️ DOIVENT rester alignées sur les attributs de classe
                # backend (`*Backend.supports_*`) — source déclarative de référence. diarisation
                # NATIVE (vibevoice) vs pyannote post-traitement (whisper/qwen ; le flag reste
                # False = pas de diar. NATIVE, mais l'app la fournit via pyannote). hotwords :
                # les 3 backends l'exposent (whisper = param NATIF faster-whisper, cf.
                # WhisperBackend.supports_hotwords=True). languages ['*'] = multilingue.
                # `task`/`modalities`/`inputs_required` complètent le tronc commun (2026-07-31) :
                # un ASR consomme la piste audio du média de travail, jamais un prompt.
                caps = {'languages': ['*'], 'supports_timestamps': True, 'supports_hotwords': True,
                        'task': 'transcription', 'modalities': ['audio'],
                        'inputs_required': ['work_audio']}
                if model_id.startswith('vibevoice'):
                    caps.update({'supports_diarization': True})
                else:  # whisper / qwen3-asr — diarisation via pyannote (post-traitement)
                    caps.update({'supports_diarization': False})

                self._models[f"transcriber:{model_id}"] = ModelInfo(
                    id=f"transcriber:{model_id}",
                    name=name,
                    model_type=ModelType.SPEECH,
                    source=ModelSource.WAMA_TRANSCRIBER,
                    description=description_long,
                    description_short=description_short,
                    vram_gb=vram_gb,
                    is_downloaded=is_downloaded,
                    backend_ref='transcriber',
                    format=fmt,
                    preferred_format=preferred,
                    can_convert_to=[],
                    extra_info=extra,
                    capabilities=caps,
                )
                logger.debug(f"[ModelRegistry] Transcriber {model_id}: downloaded={is_downloaded}")

        except ImportError as e:
            logger.debug(f"Could not import Transcriber models: {e}")

    def _discover_synthesizer_models(self):
        """Discover Synthesizer app models (Coqui, Bark, Higgs Audio, Kokoro)."""
        try:
            from django.conf import settings
            # Descriptions = source unique dans le model_config de l'app (R9) — plus de hardcode ici.
            from wama.synthesizer.utils.model_config import REGISTRY_MODEL_DESCRIPTIONS as _SYNTH_DESC

            def _tts_caps(**caps):
                """Complète les capacités d'un moteur TTS avec le tronc CANONIQUE.

                `supports_cloning` était déjà déclaré par les 4 moteurs, mais dans un
                vocabulaire propre à l'app : rien ne le reliait à l'appariement
                entrée↔modèle. C'est exactement `inputs_optional: ['reference_voice']`
                (INPUT_MODEL_MATCHING.md) — une voix de référence ACCEPTÉE, jamais exigée
                (sans elle le moteur parle avec sa voix par défaut). Le drapeau d'app est
                conservé : le traduire ici évite de le dupliquer à 4 endroits.
                """
                caps.setdefault('task', 'text-to-speech')
                caps.setdefault('modalities', ['audio'])
                caps.setdefault('inputs_required', ['prompt'])
                if caps.get('supports_cloning'):
                    caps.setdefault('inputs_optional', ['reference_voice'])
                return caps

            # Get preferred format for speech models
            preferred = self._get_preferred_format(ModelType.SPEECH)

            # Get speech models directory
            speech_dir = settings.MODEL_PATHS.get('speech', {}).get('root')
            if not speech_dir:
                speech_dir = getattr(settings, 'AI_MODELS_DIR', Path('.')) / 'models' / 'speech'
            speech_dir = Path(speech_dir)

            # Check for Coqui XTTS v2
            coqui_downloaded = False
            coqui_format = 'pth'
            coqui_paths = [
                speech_dir / 'coqui' / 'tts' / 'tts_models--multilingual--multi-dataset--xtts_v2' / 'model.pth',
                speech_dir / 'coqui' / 'XTTS-v2' / 'model.pth',
                speech_dir / 'coqui' / 'xtts_v2' / 'model.pth',
            ]
            coqui_model_path = None
            for cpath in coqui_paths:
                if cpath.exists():
                    coqui_downloaded = True
                    coqui_model_path = cpath
                    coqui_format = cpath.suffix.lstrip('.') or 'pth'
                    logger.debug(f"[ModelRegistry] Found Coqui XTTS at: {cpath}")
                    break

            self._models["synthesizer:coqui-xtts"] = ModelInfo(
                id="synthesizer:coqui-xtts",
                name="Coqui XTTS v2",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description=_SYNTH_DESC.get('coqui-xtts', {}).get('long', ''),
                description_short=_SYNTH_DESC.get('coqui-xtts', {}).get('short', ''),
                vram_gb=2.0,
                ram_gb=4.0,
                is_downloaded=coqui_downloaded,
                backend_ref='synthesizer',
                format=coqui_format,
                preferred_format=preferred,
                can_convert_to=['onnx', 'safetensors'],
                extra_info={'path': str(coqui_model_path) if coqui_model_path else ''},
                capabilities=_tts_caps(
                    supports_cloning=True,  # XTTS = clonage de voix par speaker_wav
                    languages=['fr', 'en', 'es', 'it', 'pt', 'de', 'nl', 'pl', 'ru',
                               'cs', 'ar', 'zh-cn', 'ja', 'ko', 'tr', 'hu', 'hi'],
                ),
            )

            # Check for Bark TTS
            bark_downloaded = False
            bark_format = 'pt'
            bark_paths = [
                speech_dir / 'bark' / 'suno' / 'bark_v0' / 'fine_2.pt',
                speech_dir / 'bark' / 'suno' / 'bark_v0' / 'coarse_2.pt',
                speech_dir / 'bark' / 'fine_2.pt',
            ]
            bark_model_path = None
            for bpath in bark_paths:
                if bpath.exists():
                    bark_downloaded = True
                    bark_model_path = bpath.parent  # Store the directory
                    bark_format = bpath.suffix.lstrip('.') or 'pt'
                    logger.debug(f"[ModelRegistry] Found Bark at: {bpath.parent}")
                    break

            self._models["synthesizer:bark"] = ModelInfo(
                id="synthesizer:bark",
                name="Bark TTS",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description=_SYNTH_DESC.get('bark', {}).get('long', ''),
                description_short=_SYNTH_DESC.get('bark', {}).get('short', ''),
                vram_gb=4.0,
                ram_gb=8.0,
                is_downloaded=bark_downloaded,
                backend_ref='synthesizer',
                format=bark_format,
                preferred_format=preferred,
                can_convert_to=['onnx', 'safetensors'],
                extra_info={'path': str(bark_model_path) if bark_model_path else ''},
                capabilities=_tts_caps(
                    supports_cloning=False,  # Bark = presets de locuteurs, pas de clonage libre
                    languages=['en', 'de', 'es', 'fr', 'hi', 'it', 'ja', 'ko',
                               'pl', 'pt', 'ru', 'tr', 'zh-cn'],
                ),
            )

            # Check for Higgs Audio v2
            higgs_dir = settings.MODEL_PATHS.get('speech', {}).get('higgs', speech_dir / 'higgs')
            higgs_dir = Path(higgs_dir)
            higgs_downloaded = _check_hf_model_downloaded(
                higgs_dir, 'bosonai/higgs-audio-v2-generation-3B-base')

            self._models["synthesizer:higgs-audio"] = ModelInfo(
                id="synthesizer:higgs-audio",
                name="Higgs Audio v2",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description=_SYNTH_DESC.get('higgs-audio', {}).get('long', ''),
                description_short=_SYNTH_DESC.get('higgs-audio', {}).get('short', ''),
                vram_gb=24.0,
                ram_gb=8.0,
                is_downloaded=higgs_downloaded,
                backend_ref='synthesizer',
                format='safetensors',
                preferred_format=preferred,
                can_convert_to=[],
                extra_info={'hf_id': 'bosonai/higgs-audio-v2-generation-3B-base',
                            'path': str(higgs_dir)},
                capabilities=_tts_caps(
                    supports_cloning=True,  # Higgs = clonage multi-locuteurs
                    languages=['en', 'fr', 'de', 'es', 'it', 'pt', 'zh-cn', 'ja', 'ko'],
                ),
            )

            # Check for Kokoro 82M
            kokoro_dir = settings.MODEL_PATHS.get('speech', {}).get('kokoro', speech_dir / 'kokoro')
            kokoro_dir = Path(kokoro_dir)
            kokoro_downloaded = _check_hf_model_downloaded(kokoro_dir, 'hexgrad/Kokoro-82M')

            self._models["synthesizer:kokoro"] = ModelInfo(
                id="synthesizer:kokoro",
                name="Kokoro 82M",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description=_SYNTH_DESC.get('kokoro', {}).get('long', ''),
                description_short=_SYNTH_DESC.get('kokoro', {}).get('short', ''),
                vram_gb=0.5,
                ram_gb=1.0,
                is_downloaded=kokoro_downloaded,
                backend_ref='synthesizer',
                format='pt',
                preferred_format=preferred,
                can_convert_to=[],
                extra_info={'hf_id': 'hexgrad/Kokoro-82M', 'path': str(kokoro_dir)},
                capabilities=_tts_caps(
                    supports_cloning=False,  # Kokoro = voix fixes par langue
                    languages=['fr', 'en', 'es', 'it', 'pt', 'ja', 'zh-cn'],
                ),
            )

            logger.info(
                f"[ModelRegistry] Synthesizer: Coqui={coqui_downloaded}, "
                f"Bark={bark_downloaded}, Higgs={higgs_downloaded}, Kokoro={kokoro_downloaded}"
            )

        except Exception as e:
            logger.error(f"Could not discover Synthesizer models: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    def _discover_enhancer_models(self):
        """Discover Enhancer app models (ONNX upscalers)."""
        try:
            from django.conf import settings
            # Descriptions = source unique dans le model_config de l'app (R9).
            from wama.enhancer.utils.model_config import REGISTRY_MODEL_DESCRIPTIONS as _ENH_DESC

            # Get preferred format for upscaling models
            preferred = self._get_preferred_format(ModelType.UPSCALING)

            # ALIGNEMENT 18/08 (route : clés canoniques = catalogue, SPEC §356) : la clé était
            # frappée sur le STEM DU FICHIER (RealESR_Gx4_fp16) — un artefact : `_fp16` est le
            # FORMAT (champ dédié du registre), pas l'identité. On résout stem → id canonique
            # de l'app via ENHANCER_MODELS (id → file) ; repli stem pour un ONNX inconnu.
            from wama.enhancer.utils.model_config import ENHANCER_MODELS as _ENH_MODELS
            _stem_to_id = {Path(cfg.get('file', '')).stem: mid
                           for mid, cfg in _ENH_MODELS.items() if cfg.get('file')}

            onnx_dir = settings.MODEL_PATHS.get('upscaling', {}).get('onnx')
            if onnx_dir and Path(onnx_dir).exists():
                for onnx_file in Path(onnx_dir).glob('*.onnx'):
                    model_name = _stem_to_id.get(onnx_file.stem, onnx_file.stem)
                    size_mb = onnx_file.stat().st_size / (1024 * 1024)

                    # Capacités : tâche (débruitage IRCNN vs upscaling) + facteur d'échelle.
                    _n = model_name.lower()
                    _caps = {
                        'task': 'denoise' if 'ircnn' in _n else 'upscale',
                        'modalities': ['image', 'video'],
                        # Appariement entrée↔modèle (INPUT_MODEL_MATCHING.md) : un upscaler
                        # exige le fichier de travail. Sans cette clé, WamaInputMatch n'a rien
                        # à comparer et ne peut pas griser les moteurs incompatibles.
                        'inputs_required': ['work_file'],
                    }
                    if 'x4' in _n:
                        _caps['scale'] = 4
                    elif 'x2' in _n:
                        _caps['scale'] = 2

                    # These models are already in ONNX format
                    self._models[f"enhancer:{model_name}"] = ModelInfo(
                        id=f"enhancer:{model_name}",
                        name=model_name,
                        model_type=ModelType.UPSCALING,
                        source=ModelSource.WAMA_ENHANCER,
                        # Descriptions déclarées dans enhancer/utils/model_config.py (R9,
                        # court/long séparés) ; repli générique si fichier ONNX inconnu.
                        description=_ENH_DESC.get(model_name, {}).get(
                            'long', f"ONNX upscaling model ({size_mb:.1f}MB)"),
                        description_short=_ENH_DESC.get(model_name, {}).get(
                            'short', f"ONNX upscaling model ({size_mb:.1f}MB)"),
                        vram_gb=round(size_mb / 500, 1),  # Estimate
                        is_downloaded=True,
                        extra_info={'path': str(onnx_file), 'size_mb': size_mb},
                        backend_ref='enhancer',
                        format='onnx',
                        preferred_format=preferred,
                        can_convert_to=[],  # Already optimal format
                        capabilities=_caps,
                    )
        except Exception as e:
            logger.debug(f"Could not discover Enhancer models: {e}")

        # ── Moteurs de restauration AUDIO (backends pip, hors fichiers) : déclarés au catalogue avec
        # leurs CAPACITÉS (params supportés) → l'UI s'adapte via WamaModelCaps, PAS de show_if hardcodé. ──
        _audio_engines = {
            'resemble': {
                'name': 'Resemble Enhance',
                'short': 'Restauration par diffusion — débruitage + extension de bande, meilleure qualité',
                'long': ('Resemble Enhance : modèle génératif (diffusion) qui débruite ET restaure les '
                         'hautes fréquences (super-résolution audio). Qualité supérieure mais plus lent ; '
                         'les réglages Mode / Force / Qualité (NFE) s\'appliquent.'),
                'vram': 4.0,
                'params': ['mode', 'strength', 'quality'],
            },
            'deepfilternet': {
                'name': 'DeepFilterNet 3',
                'short': 'Débruitage temps réel — rapide, faible empreinte',
                'long': ('DeepFilterNet 3 : débruitage discriminatif temps réel (48 kHz), très rapide et '
                         'léger, sans extension de bande. Recommandé pour prétraiter avant transcription ; '
                         'les réglages Mode / Force / Qualité ne s\'appliquent pas.'),
                'vram': 1.0,
                'params': [],
            },
        }
        for _eng_id, _eng in _audio_engines.items():
            self._models[f'enhancer:{_eng_id}'] = ModelInfo(
                id=f'enhancer:{_eng_id}',
                name=_eng['name'],
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_ENHANCER,
                description=_eng['long'],
                description_short=_eng['short'],
                vram_gb=_eng['vram'],
                is_downloaded=True,
                backend_ref='enhancer',
                # kebab-case comme tout le vocabulaire (ModelTask) : 'audio_enhance' etait la
                # seule valeur en snake_case, donc hors taxonomie declaree.
                capabilities={'task': 'audio-enhance', 'modalities': ['audio'], 'params': _eng['params'],
                              # Moteurs AUDIO : c'est ce qui les distingue des upscalers
                              # image/vidéo de la même app (eux exigent 'work_file').
                              'inputs_required': ['work_audio']},
            )

    def _discover_composer_models(self):
        """Discover Composer app models (MusicGen + AudioGen)."""
        try:
            from wama.composer.utils.model_config import COMPOSER_MODELS, MUSICGEN_DIR, AUDIOGEN_DIR

            for model_id, config in COMPOSER_MODELS.items():
                cache_dir = config['cache_dir']
                hf_id = config['hf_id']
                is_downloaded = _check_hf_model_downloaded(cache_dir, hf_id)

                model_info = ModelInfo(
                    id=model_id,
                    name=config['description'],
                    model_type=ModelType.MUSIC,
                    source=ModelSource.WAMA_COMPOSER,
                    # Deux champs SÉPARÉS (format transcriber) : court sous le select,
                    # long autonome en overlay ⓘ (cf. model_config 'description_long').
                    description=config.get('description_long') or config['description'],
                    description_short=config['description'],
                    hf_id=hf_id,
                    vram_gb=config['vram_gb'],
                    is_downloaded=is_downloaded,
                    extra_info={
                        'type': config['type'],
                        'max_duration': config['max_duration'],
                        'sample_rate': config['sample_rate'],
                    },
                    # Capacités CANONIQUES (tronc commun, cf. common/utils/model_capabilities.py) :
                    #   modalities = sortie audio ; task dérivé du type (music vs sfx) ;
                    #   languages=['en'] car l'encodeur texte AudioCraft (T5) est anglais → lang_routing
                    #   traduit FR→EN en entrée (fait établi, pas une invention).
                    #   inputs_optional : appariement card↔modèles (INPUT_MODEL_MATCHING.md) —
                    #   seul musicgen-melody accepte une mélodie de référence (conditionnement
                    #   OPTIONNEL : il improvise sans).
                    capabilities={
                        'modalities': ['audio'],
                        'task': 'text-to-music' if config.get('type') == 'music' else 'text-to-audio',
                        'languages': ['en'],
                        # Requis pour TOUS (AudioCraft part d'une description textuelle) ;
                        # la mélodie n'est OPTIONNELLE que pour melody — c'est cette
                        # distinction requis/optionnel que l'appariement exploite.
                        'inputs_required': ['prompt'],
                        **({'inputs_optional': ['reference_melody']}
                           if model_id == 'musicgen-melody' else {}),
                    },
                )
                # Clé de registre = `{source}:{id}` (convention des 7 autres apps) → devient model_key
                # en base. Sans le préfixe, `_resolve_model` (pilier traduction) ne retrouve pas les
                # capacités et retombe en repli type ['en']. Cf. REMOVAL_LEDGER F4.
                self._models[f"composer:{model_id}"] = model_info

        except Exception as e:
            logger.debug(f"Could not discover Composer models: {e}")

    def _discover_reader_models(self):
        """Discover Reader app OCR models (olmOCR-2 + docTR)."""
        try:
            from wama.reader.utils.model_config import READER_MODELS, OLMOCR_DIR, DOCTR_DIR

            cache_dirs = {'olmocr': OLMOCR_DIR, 'doctr': DOCTR_DIR}

            for model_id, config in READER_MODELS.items():
                hf_id = config.get('hf_model_id', '')
                cache_dir = cache_dirs.get(model_id)

                if hf_id:
                    is_downloaded = _check_hf_model_downloaded(str(cache_dir), hf_id)
                elif config.get('ollama_id'):
                    # Servi par Ollama : « téléchargé » = présent dans la liste Ollama.
                    # Sa DISPONIBILITÉ réelle (serveur allumé) est une sonde runtime, pas
                    # une propriété du catalogue — cf. `_backend_is_available` du reader.
                    is_downloaded = any(
                        k == f"ollama:{config['ollama_id']}" or
                        k.startswith(f"ollama:{config['ollama_id'].split(':', 1)[0]}")
                        for k in self._models)
                else:
                    # docTR : les poids vivent dans DOCTR_DIR (DOCTR_CACHE_DIR, posé par le
                    # backend) — critère DISQUE d'abord ; l'import du paquet n'est qu'un
                    # repli (propriété du venv, pas du modèle : mesuré faux positif depuis
                    # venv_win le 2026-08-12, doctr n'étant installé que côté venv_linux).
                    is_downloaded = any(Path(cache_dir).rglob('*.pt')) \
                        if cache_dir and Path(cache_dir).is_dir() else False
                    if not is_downloaded:
                        try:
                            import doctr  # noqa
                            is_downloaded = True
                        except ImportError:
                            pass

                model_info = ModelInfo(
                    id=model_id,
                    name=config['description'],
                    model_type=ModelType.OCR,
                    source=ModelSource.WAMA_READER,
                    # Court/long séparés (format transcriber), cf. model_config 'description_long'.
                    description=config.get('description_long') or config['description'],
                    description_short=config['description'],
                    hf_id=hf_id or None,
                    vram_gb=config['vram_gb'],
                    is_downloaded=is_downloaded,
                    extra_info={'type': config['type']},
                    # Capacités CANONIQUES : OCR sur images/documents. Langues non déclarées
                    # (olmOCR/docTR sont multi-écritures ; ne pas sur-affirmer un jeu de langues).
                    capabilities={
                        'modalities': ['image', 'document'],
                        'task': 'ocr',
                        'inputs_required': ['work_file'],
                    },
                )
                # Clé de registre = `{source}:{id}` (convention). Cf. REMOVAL_LEDGER F4.
                self._models[f"reader:{model_id}"] = model_info

        except Exception as e:
            logger.debug(f"Could not discover Reader models: {e}")

    @staticmethod
    def _ollama_charges() -> dict:
        """
        Modèles Ollama actuellement EN MÉMOIRE : `{nom: empreinte_Go}` (`/api/ps`).

        ⚠ Rend un DICT depuis le 2026-08-19 (auparavant un `set` de noms) : l'empreinte est
        nécessaire pour DÉCLARER cette résidence au gouverneur (`refresh_ollama_residency`).
        Le test d'appartenance (`nom in charges`) est identique sur un dict — l'unique
        appelant historique n'a pas eu à changer.

        Sans ce signal, `select_model(prefer_loaded=True)` ne peut rien privilégier côté LLM :
        `is_loaded` restait à False pour les 11 modèles Ollama du catalogue, donc l'arbitrage
        « éviter un déchargement/rechargement » ne s'appliquait qu'aux modèles non-Ollama.
        `/api/ps` était déjà interrogé par `reader/backends/olmocr_backend.py` — jamais par la
        synchro du catalogue.

        Best-effort : Ollama injoignable → ensemble vide (aucun modèle privilégié), jamais
        d'exception, la découverte ne doit pas échouer pour ça.
        """
        try:
            import requests
            from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
            r = requests.get(f"{ollama_base()}/api/ps", **ollama_kwargs(timeout=3))
            r.raise_for_status()
            return {m.get('name', ''): round((m.get('size') or 0) / (1024 ** 3), 2)
                    for m in r.json().get('models', [])}
        except Exception as exc:
            logger.debug("[ModelRegistry] /api/ps indisponible : %s", exc)
            return {}

    @staticmethod
    def _ollama_capacites() -> dict:
        """
        Capacités DÉCLARÉES PAR OLLAMA, par modèle : `/api/tags` → `{nom: {'vision', 'tools', …}}`.

        Ollama publie `capabilities` pour chaque modèle — `completion`, `embedding`, `vision`,
        `tools`, `thinking`. Ce champ n'était lu nulle part, alors qu'il résout deux problèmes
        que le catalogue avait :
          • les modèles d'EMBEDDING (bge-m3, nomic, mxbai) étaient étiquetés `ModelType.LLM`
            comme les modèles de chat, donc sélectionnables comme describer — ils ne peuvent
            pourtant pas générer de texte ;
          • la MULTIMODALITÉ était réputée inconnaissable ici (« la liste Ollama ne dit pas si
            un modèle est multimodal »), ce qui est faux : `vision` y figure.

        La découverte passe par `ollama list` (subprocess), qui ne porte pas cette information —
        d'où cet appel HTTP séparé. Best-effort : indisponible → dict vide, aucune capacité
        affirmée (on retombe sur `text`/`text-generation`, comme avant).
        """
        try:
            import requests
            from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
            r = requests.get(f"{ollama_base()}/api/tags", **ollama_kwargs(timeout=5))
            r.raise_for_status()
            return {m.get('name', ''): set(m.get('capabilities') or [])
                    for m in r.json().get('models', [])}
        except Exception as exc:
            logger.debug("[ModelRegistry] capacités Ollama indisponibles : %s", exc)
            return {}

    @staticmethod
    def _ollama_fiche(nom: str) -> dict:
        """
        Métadonnées RICHES d'un modèle Ollama (`/api/show`) — bien au-delà de `/api/tags`.

        Rend `{params_b, quantization, context_length, experts_total, experts_actifs, arch}`,
        ou `{}` si indisponible. Ce que ça débloque, et qu'aucune autre source ne donnait :
          • le nombre de paramètres EXACT (`details.parameter_size`), là où la découverte
            parsait un libellé de tag — parsing qui échouait justement sur `35b-a3b`, laissant
            `vram_gb=0.0` et faisant paraître le modèle gratuit au sélecteur ;
          • le ratio d'experts d'un MoE (`<arch>.expert_used_count` / `expert_count`), donc la
            séparation entre qualité (params totaux) et coût (params actifs) ;
          • la fenêtre de contexte, capacité canonique jamais renseignée jusqu'ici ;
          • les capacités COMPLÈTES : `/api/tags` en rend un sous-ensemble — mesuré le
            2026-08-19, gemma4:12b y annonce [completion, tools, thinking, vision] quand
            `/api/show` ajoute `audio`. L'entrée audio native du parc était donc invisible.
            Récupérées ICI, sans requête supplémentaire (l'appel est déjà fait).

        ⚠ UN APPEL PAR MODÈLE. Acceptable à la synchro (périodique, ~12 modèles) ; à ne pas
        mettre dans un chemin de requête.
        """
        try:
            import requests
            from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
            r = requests.post(f"{ollama_base()}/api/show", json={'model': nom},
                              **ollama_kwargs(timeout=15))
            r.raise_for_status()
            d = r.json()
            details, infos = d.get('details') or {}, d.get('model_info') or {}
            arch = infos.get('general.architecture') or ''
            return {
                'params_b': details.get('parameter_size') or '',
                'quantization': details.get('quantization_level') or '',
                'context_length': infos.get(f'{arch}.context_length'),
                'experts_total': infos.get(f'{arch}.expert_count'),
                'experts_actifs': infos.get(f'{arch}.expert_used_count'),
                'arch': arch,
                'capabilities': set(d.get('capabilities') or []),
            }
        except Exception as exc:
            logger.debug("[ModelRegistry] /api/show %s indisponible : %s", nom, exc)
            return {}

    @staticmethod
    def _capacites_canoniques(brutes: set, nom_modele: str = '') -> dict:
        """Capacités Ollama → vocabulaire CANONIQUE (`model_capabilities.CANONICAL_CAPABILITIES`).

        `requires=` de `select_model()` teste des clés TRUTHY : on expose donc des drapeaux
        positifs (`completion`, `vision`, `audio`, `tools`, `embedding`) plutôt qu'une
        négation, qu'il ne saurait pas exprimer. `nom_modele` sert à la SPÉCIALISATION
        déclarée (cf. `SPECIALISATIONS_OLLAMA`), que la découverte ne peut pas deviner.
        """
        embarque = 'embedding' in brutes
        # `audio` (ENTRÉE audio native) était JETÉ : absent de la liste blanche et des
        # modalités, alors que gemma4:12b et gemma4:e4b le déclarent (mesuré 2026-08-19).
        # Une capacité réelle du parc restait invisible à `select_model(requires=...)`.
        modalites = (['text'] + (['image'] if 'vision' in brutes else [])
                     + (['audio'] if 'audio' in brutes else []))
        caps = {
            'modalities': modalites,
            'task': 'feature-extraction' if embarque else 'text-generation',
            'inputs_required': ['prompt'],
        }
        for drapeau in ('completion', 'vision', 'audio', 'tools', 'thinking', 'embedding'):
            if drapeau in brutes:
                caps[drapeau] = True
        # Spécialisation DÉCLARÉE (humaine) : elle ne se découvre pas — Ollama rend
        # `completion, vision` pour translategemma comme pour un généraliste. Déclarée ICI
        # parce que la découverte réécrit `capabilities` EN ENTIER à chaque sync (une valeur
        # posée en base serait effacée au passage suivant — leçon `audio_enhance`, 05/08).
        for prefixe, domaine in SPECIALISATIONS_OLLAMA.items():
            if nom_modele and nom_modele.split(':')[0].lower().startswith(prefixe):
                caps['specialisation'] = domaine
                break
        # Un modèle sans capacité déclarée (Ollama ancien, ou API injoignable) est traité comme
        # un modèle de complétion : c'est le comportement d'avant, on ne régresse pas.
        if not brutes:
            caps['completion'] = True
        return caps

    def _discover_ollama_models(self):
        """Discover Ollama models (with short timeout to avoid blocking)."""
        # Try multiple methods to discover Ollama models
        models_found = False
        charges = self._ollama_charges()
        capacites = self._ollama_capacites()

        # Method 1: Try ollama command (works on native Windows/Linux)
        for cmd in ['ollama', 'ollama.exe']:
            if models_found:
                break
            try:
                result = subprocess.run(
                    [cmd, 'list'],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )

                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')[1:]  # Skip header
                    for line in lines:
                        if not line.strip():
                            continue
                        parts = line.split()
                        if len(parts) >= 2:
                            model_name = parts[0]
                            model_id_hash = parts[1]  # colonne ID d'`ollama list` (≠ taille)

                            # Taille : repérée par regex où qu'elle soit sur la ligne
                            # (format `NAME ID SIZE MODIFIED`, ex. "18 GB" ou "669 MB"),
                            # au lieu de supposer parts[1] = taille (qui est l'ID).
                            ram_gb = 0.0
                            size_display = 'taille inconnue'
                            sm = re.search(r'(\d+(?:[.,]\d+)?)\s*(GB|MB|TB)', line, re.IGNORECASE)
                            if sm:
                                num = float(sm.group(1).replace(',', '.'))
                                unit = sm.group(2).upper()
                                ram_gb = num if unit == 'GB' else (num / 1024 if unit == 'MB' else num * 1024)
                                size_display = f"{sm.group(1)} {unit}"

                            # Ollama models use GGUF format
                            preferred = self._get_preferred_format(ModelType.LLM)

                            # Métadonnées structurelles → indice de qualité + axe de coût.
                            # `params_b` vient de `/api/show`, PAS du libellé de tag : ce
                            # dernier laissait `vram_gb=0.0` sur les noms composés (`35b-a3b`).
                            fiche = self._ollama_fiche(model_name)
                            pb = _params_b(fiche.get('params_b'))
                            # Actifs AVANT l'indice : depuis la révision 2026-08-19, l'axe
                            # qualité retient les paramètres EFFECTIFS √(totaux × actifs)
                            # (un MoE 8/256 ne vaut plus ses totaux — cf. model_quality.py).
                            actifs = _params_actifs(pb, fiche.get('experts_total'),
                                                    fiche.get('experts_actifs'))
                            qualite = _indice_qualite(
                                params_b=pb,
                                context_length=fiche.get('context_length'),
                                quantization=fiche.get('quantization', ''),
                                params_active_b=actifs,
                            )

                            self._models[f"ollama:{model_name}"] = ModelInfo(
                                id=f"ollama:{model_name}",
                                name=model_name,
                                model_type=ModelType.LLM,
                                source=ModelSource.OLLAMA,
                                description=f"Ollama LLM ({size_display})",
                                ram_gb=ram_gb,
                                # APPROXIMATION ASSUMÉE : pour un GGUF servi par Ollama, l'empreinte
                                # VRAM est de l'ordre de la taille du fichier (le KV cache s'y
                                # ajoute, variable selon le contexte). Sans cette valeur, `vram_gb`
                                # restait à 0.0 pour TOUS les LLM et le budget VRAM de
                                # `select_model()` ne pouvait pas les départager — un 4b et un 35b
                                # se valaient. Approcher vaut mieux qu'un zéro qui ment.
                                vram_gb=ram_gb,
                                is_loaded=(model_name in charges),
                                is_downloaded=True,
                                backend_ref='ollama',
                                format='gguf',
                                preferred_format=preferred,
                                can_convert_to=[],  # Managed by Ollama
                                extra_info={'disk_gb': ram_gb, 'ollama_id': model_id_hash},
                                # Capacités CANONIQUES, dérivées de ce qu'OLLAMA DÉCLARE
                                # (`/api/tags` → `capabilities`), plus de ce qu'on suppose.
                                # Corrige deux angles morts : les modèles d'embedding ne sont
                                # plus confondus avec des modèles de chat, et `vision` est
                                # renseigné là où le commentaire précédent le disait — à tort —
                                # hors de portée.
                                quality_index=qualite,
                                capabilities=dict(
                                    # UNION tags ∪ show : `/api/tags` rend un SOUS-ENSEMBLE
                                    # (pas d'`audio`), `/api/show` la liste complète — la
                                    # fiche est déjà chargée, donc gratuit (mesuré 19/08).
                                    self._capacites_canoniques(
                                        capacites.get(model_name, set())
                                        | (fiche.get('capabilities') or set()),
                                        model_name),
                                    # L'ensemble BRUT d'Ollama, conservé tel quel : `tools` et
                                    # `thinking` n'ont d'équivalent dans aucune autre taxonomie, et
                                    # ce sont eux qui disent si un modèle peut servir l'assistant.
                                    # Écrit ICI et pas par une commande de rattrapage : la
                                    # découverte réécrit `capabilities` en entier à chaque sync et
                                    # effacerait toute valeur posée en dehors d'elle (constaté le
                                    # 2026-08-05 — 11 modèles renseignés, puis 0 après un sync).
                                    **({'abilities': sorted(capacites.get(model_name, set())
                                                            | (fiche.get('capabilities') or set()))}
                                       if (capacites.get(model_name)
                                           or fiche.get('capabilities')) else {}),
                                    # `context_length` est au vocabulaire canonique et n'était
                                    # jamais rempli ; `params_*_b` séparent explicitement la
                                    # QUALITÉ (totaux) du COÛT (actifs) — voir model_quality.py.
                                    **({'context_length': fiche['context_length']}
                                       if fiche.get('context_length') else {}),
                                    **({'params_total_b': pb} if pb else {}),
                                    **({'params_active_b': actifs} if actifs else {}),
                                ),
                            )
                            models_found = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
            except Exception as e:
                logger.debug(f"Ollama command '{cmd}' failed: {e}")

        # Method 2: If command failed, scan Ollama models directory directly
        if not models_found:
            self._discover_ollama_from_directory()

    def _discover_ollama_from_directory(self):
        """Scan Ollama models directory directly (useful for WSL)."""
        # Possible Ollama model directories
        ollama_dirs = []

        # Check if running in WSL
        is_wsl = sys.platform == 'linux' and 'microsoft' in os.uname().release.lower() if hasattr(os, 'uname') else False

        if is_wsl:
            # WSL: Check Windows user's .ollama directory
            # Common locations: D:\.ollama, C:\Users\<user>\.ollama
            for drive in ['d', 'c']:
                ollama_dirs.append(Path(f"/mnt/{drive}/.ollama/models"))
            # Also check Windows user profile
            try:
                result = subprocess.run(
                    ['cmd.exe', '/c', 'echo', '%USERPROFILE%'],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    userprofile = result.stdout.strip()
                    if userprofile and not userprofile.startswith('%'):
                        # Convert Windows path to WSL path
                        userprofile = userprofile.replace('\\', '/').replace('C:', '/mnt/c').replace('D:', '/mnt/d')
                        ollama_dirs.append(Path(userprofile) / ".ollama" / "models")
            except Exception:
                pass
        else:
            # Native Windows
            ollama_dirs.append(Path(os.path.expanduser("~")) / ".ollama" / "models")
            ollama_dirs.append(Path("D:/.ollama/models"))
            ollama_dirs.append(Path("C:/.ollama/models"))

        for ollama_dir in ollama_dirs:
            if not ollama_dir.exists():
                continue

            # Ollama stores models in manifests/registry.ollama.ai/library/<model>/<tag>
            manifests_dir = ollama_dir / "manifests" / "registry.ollama.ai" / "library"
            if manifests_dir.exists():
                try:
                    for model_dir in manifests_dir.iterdir():
                        if model_dir.is_dir():
                            model_name = model_dir.name
                            # Check for tags
                            for tag_file in model_dir.iterdir():
                                if tag_file.is_file():
                                    tag = tag_file.name
                                    full_name = f"{model_name}:{tag}" if tag != "latest" else model_name

                                    # Try to get size from blob
                                    size_gb = 0
                                    try:
                                        manifest = json.loads(tag_file.read_text())
                                        for layer in manifest.get('layers', []):
                                            size_gb += layer.get('size', 0) / (1024**3)
                                    except Exception:
                                        pass

                                    # Ollama models use GGUF format
                                    preferred = self._get_preferred_format(ModelType.LLM)

                                    self._models[f"ollama:{full_name}"] = ModelInfo(
                                        id=f"ollama:{full_name}",
                                        name=full_name,
                                        model_type=ModelType.LLM,
                                        source=ModelSource.OLLAMA,
                                        description=f"Ollama LLM ({size_gb:.1f}GB)" if size_gb > 0 else "Ollama LLM",
                                        ram_gb=round(size_gb, 1),
                                        is_downloaded=True,
                                        backend_ref='ollama',
                                        format='gguf',
                                        preferred_format=preferred,
                                        can_convert_to=[],  # Managed by Ollama
                                    )
                except Exception as e:
                    logger.debug(f"Error scanning Ollama directory {ollama_dir}: {e}")
                break  # Found models, stop searching

    # =========================================================================
    # Format Policy Methods
    # =========================================================================

    def get_models_needing_conversion(self) -> List[ModelInfo]:
        """
        Get models that are not in their preferred format according to policy.

        Returns:
            List of ModelInfo objects needing conversion
        """
        return [
            m for m in self._models.values()
            if m.format and m.preferred_format and m.format != m.preferred_format
        ]

    def get_format_stats(self) -> Dict[str, int]:
        """
        Get statistics of model formats.

        Returns:
            Dict mapping format names to counts
        """
        from wama.common.utils.format_policy import get_format_stats_template

        stats = get_format_stats_template()
        for model in self._models.values():
            if model.format:
                stats[model.format] = stats.get(model.format, 0) + 1
        return stats

    def get_compliance_stats(self) -> Dict[str, any]:
        """
        Get format policy compliance statistics.

        Returns:
            Dict with compliance percentages and counts
        """
        compliant = 0
        non_compliant = 0
        no_policy = 0

        for model in self._models.values():
            if not model.preferred_format:
                no_policy += 1
            elif model.format == model.preferred_format:
                compliant += 1
            else:
                non_compliant += 1

        total = compliant + non_compliant
        return {
            'compliant': compliant,
            'non_compliant': non_compliant,
            'no_policy': no_policy,
            'total': total,
            'percentage': round((compliant / total * 100) if total > 0 else 100, 1),
        }

    # Cache for YOLO model classes to avoid reloading models
    _yolo_classes_cache: Dict[str, List[str]] = {}

    # Known classes for specialty models (when YOLO loading is slow/unavailable)
    SPECIALTY_KNOWN_CLASSES = {
        'faces': ['face'],
        'plates': ['plate', 'license_plate'],
        'faces&plates': ['face', 'plate'],
    }

    def _get_yolo_model_classes(self, model_path: str, specialty: str = None) -> List[str]:
        """
        Get the class list for a YOLO model.

        Uses a cache to avoid repeatedly loading models. For specialty models,
        uses known class mappings when available.

        Args:
            model_path: Path to the YOLO model file
            specialty: Specialty directory name (faces, plates, etc.)

        Returns:
            List of class names the model supports, or empty list if unknown
        """
        if not model_path:
            return []

        # Check cache first
        if model_path in self._yolo_classes_cache:
            return self._yolo_classes_cache[model_path]

        # ── LE FICHIER D'ABORD, la table de repli ENSUITE ────────────────────────────────────
        # L'ancien ordre partait de `SPECIALTY_KNOWN_CLASSES` et RENDAIT SANS OUVRIR le fichier
        # dès que le modèle vivait dans un dossier de spécialité. Trois conséquences mesurées le
        # 2026-08-12 :
        #   • ordre FAUX  — `faces&plates` y vaut ['face','plate'] quand les poids déclarent
        #     ['plate','face'] ; or l'ordre EST l'index de classe passé à `predict(classes=…)` ;
        #   • classe PERDUE — `yolo11l_face_plate_signs.pt` porte ['sign','plate','face'] : la
        #     classe `sign` n'existait nulle part au catalogue, donc la demander rendait
        #     « aucun modèle ne couvre cette classe » alors que le seul qui sait le faire est
        #     installé (sélection auto mesurée à 0 % de couverture pour ['sign']) ;
        #   • table à tenir à la main pour une information que chaque fichier porte déjà.
        # Lecture via `weights_metadata` (métadonnées ONNX / checkpoint ultralytics) : moins
        # coûteux que l'instanciation `YOLO()` du repli ci-dessous, et sans effet de bord.
        from wama.model_manager.services.weights_metadata import classes_depuis_poids

        noms = classes_depuis_poids(model_path)
        if noms:
            classes = [str(c).lower() for c in noms]
            self._yolo_classes_cache[model_path] = classes
            return classes

        # Le fichier n'a rien déclaré → repli sur la table, qui reste utile pour les exports
        # ONNX dépourvus de métadonnées `names`.
        if specialty and specialty in self.SPECIALTY_KNOWN_CLASSES:
            classes = self.SPECIALTY_KNOWN_CLASSES[specialty]
            self._yolo_classes_cache[model_path] = classes
            return classes

        # Try to load classes from model (slower, but accurate)
        try:
            # For ONNX models, try to get classes from path-based inference
            if model_path.lower().endswith('.onnx'):
                # Check specialty from path
                path_lower = model_path.lower().replace('\\', '/')
                for spec, classes in self.SPECIALTY_KNOWN_CLASSES.items():
                    if f'/{spec}/' in path_lower:
                        self._yolo_classes_cache[model_path] = classes
                        return classes
                # Unknown ONNX model, return empty (will be filled by Anonymizer)
                return []

            # For PyTorch models, load via YOLO
            from ultralytics import YOLO
            model = YOLO(model_path)

            # Get class names
            if hasattr(model, 'names') and model.names:
                classes = [str(v).lower() for v in model.names.values()]
            elif hasattr(model.model, 'names'):
                classes = [str(v).lower() for v in model.model.names.values()]
            else:
                classes = []

            self._yolo_classes_cache[model_path] = classes
            logger.debug(f"[ModelRegistry] Loaded {len(classes)} classes from {Path(model_path).name}")
            return classes

        except Exception as e:
            logger.debug(f"[ModelRegistry] Could not load classes from {model_path}: {e}")
            return []

    def _detect_model_format(self, model_path: Optional[str]) -> str:
        """
        Detect the format of a model from its path.

        Args:
            model_path: Path to the model file or directory

        Returns:
            Format string ('pt', 'safetensors', 'onnx', etc.) or empty string
        """
        if not model_path:
            logger.debug("[_detect_model_format] No model_path provided")
            return ''

        path = Path(model_path)

        # Check if path exists
        if not path.exists():
            logger.debug(f"[_detect_model_format] Path does not exist: {model_path}")
            # Try to infer from extension anyway
            suffix = path.suffix.lower()
            if suffix:
                format_map = {
                    '.pt': 'pt',
                    '.pth': 'pth',
                    '.safetensors': 'safetensors',
                    '.onnx': 'onnx',
                    '.bin': 'bin',
                    '.gguf': 'gguf',
                }
                fmt = format_map.get(suffix, '')
                if fmt:
                    logger.debug(f"[_detect_model_format] Inferred from extension: {fmt}")
                    return fmt
            return ''

        # Direct file
        if path.is_file():
            suffix = path.suffix.lower()
            format_map = {
                '.pt': 'pt',
                '.pth': 'pth',
                '.safetensors': 'safetensors',
                '.onnx': 'onnx',
                '.bin': 'bin',
                '.gguf': 'gguf',
            }
            fmt = format_map.get(suffix, 'unknown')
            logger.debug(f"[_detect_model_format] File format: {fmt} from {suffix}")
            return fmt

        # HuggingFace cache directory - check for safetensors or bin
        if path.is_dir():
            # Check snapshots for model files
            for pattern in ['**/*.safetensors', '**/*.bin', '**/*.pt']:
                files = list(path.glob(pattern))
                if files:
                    # Prefer safetensors if found
                    if 'safetensors' in pattern:
                        return 'safetensors'
                    elif 'bin' in pattern:
                        return 'bin'
                    else:
                        return 'pt'

        return ''

    def _get_preferred_format(self, model_type: ModelType) -> str:
        """
        Get the preferred format for a model type.

        Args:
            model_type: The ModelType enum value

        Returns:
            Preferred format string
        """
        try:
            from wama.common.utils.format_policy import get_preferred_format, get_category_for_model_type

            category = get_category_for_model_type(model_type.value)
            preferred = get_preferred_format(category)
            logger.debug(f"[ModelRegistry] Preferred format for {model_type.value} (category={category}): {preferred}")
            return preferred
        except Exception as e:
            logger.error(f"[ModelRegistry] Error getting preferred format for {model_type}: {e}")
            return 'safetensors'  # Default fallback

    def _get_conversion_options(self, current_format: str, model_type: ModelType) -> List[str]:
        """
        Get available conversion options for a model.

        Args:
            current_format: Current format of the model
            model_type: Type of the model

        Returns:
            List of formats the model can be converted to
        """
        options = []

        if current_format in ['pt', 'pth']:
            options.extend(['safetensors', 'onnx'])
        elif current_format == 'bin':
            options.append('safetensors')
        elif current_format == 'ckpt':
            options.extend(['safetensors', 'onnx'])

        return options

    def _discover_avatarizer_models(self):
        """Discover Avatarizer app models (MuseTalk lip-sync pipeline)."""
        try:
            from django.conf import settings

            lipsync_dir = Path(settings.BASE_DIR) / 'AI-models' / 'models' / 'lipsync'
            if not lipsync_dir.exists():
                return

            # MuseTalk V1.5 (main model used by the avatarizer pipeline)
            musetalk_v15 = lipsync_dir / 'musetalk' / 'musetalkV15' / 'unet.pth'
            musetalk_v10 = lipsync_dir / 'musetalk' / 'musetalk' / 'pytorch_model.bin'

            for model_id, unet_path, name, description in [
                ('musetalk-v1.5', musetalk_v15, 'MuseTalk v1.5', 'Lip-sync pipeline v1.5 (UNet + DWPose + Whisper + SD-VAE + SyncNet)'),
                ('musetalk-v1.0', musetalk_v10, 'MuseTalk v1.0', 'Lip-sync pipeline v1.0 (UNet + DWPose + Whisper + SD-VAE)'),
            ]:
                is_downloaded = unet_path.exists()
                self._models[f"avatarizer:{model_id}"] = ModelInfo(
                    id=f"avatarizer:{model_id}",
                    name=name,
                    model_type=ModelType.LIPSYNC,
                    source=ModelSource.WAMA_AVATARIZER,
                    description=description,
                    hf_id='TMElyralab/MuseTalk',
                    vram_gb=4.0,
                    is_downloaded=is_downloaded,
                    extra_info={
                        'path': str(unet_path.parent),
                        'pipeline': 'musetalk',
                    },
                    # Capacités CANONIQUES : lip-sync = image (avatar) + audio (voix) → vidéo.
                    # DEUX entrées requises : c'est le seul modèle du catalogue dans ce cas,
                    # et c'est précisément ce que l'appariement doit dire à l'utilisateur
                    # AVANT le lancement plutôt que de le laisser échouer (INPUT_MODEL_MATCHING.md).
                    capabilities={
                        'modalities': ['image', 'audio', 'video'],
                        'task': 'lip-sync',
                        'inputs_required': ['work_image', 'work_audio'],
                    },
                    backend_ref='avatarizer',
                    format='pth',
                    preferred_format='pth',
                    can_convert_to=[],
                )

        except Exception as e:
            logger.debug(f"Could not discover Avatarizer models: {e}")
