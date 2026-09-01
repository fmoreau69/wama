"""
Model Sync Service - Synchronizes models between filesystem/configs and database.

This service bridges the gap between the dynamic ModelRegistry discovery
and the PostgreSQL-backed AIModel catalog.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

from django.db import transaction
from django.utils import timezone

from wama.common.utils.model_capabilities import normalize_capabilities

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Result of a sync operation."""
    success: bool
    added: int = 0
    updated: int = 0
    removed: int = 0
    errors: List[str] = field(default_factory=list)
    #: Clés des modèles CRÉÉS par cette passe. Le compteur `added` ne disait pas LESQUELS, si
    #: bien qu'un appelant voulant agir sur les nouveaux (poser leur provenance après une
    #: installation) devait photographier le catalogue avant/après pour re-dériver ce que le
    #: sync savait déjà — avec la course que ça suppose. (2026-08-12)
    added_keys: List[str] = field(default_factory=list)


class ModelSyncService:
    """
    Service for synchronizing models between various sources and the database.

    Workflow:
    1. Uses existing ModelRegistry to discover models from all sources
    2. Syncs discovered models to AIModel database table
    3. Tracks sync history in ModelSyncLog
    """

    def __init__(self):
        self._registry = None

    def _get_registry(self):
        """Lazy load registry to avoid circular imports."""
        if self._registry is None:
            from .model_registry import ModelRegistry
            self._registry = ModelRegistry()
        return self._registry

    def full_sync(self, remove_missing: bool = False, delete_missing: bool = False) -> SyncResult:
        """
        Perform a full sync of all models from all sources.

        Args:
            remove_missing: If True, mark models not found in sources as unavailable
            delete_missing: If True, delete models not found in sources from the database
                           (takes precedence over remove_missing)

        Returns:
            SyncResult with counts and any errors
        """
        from ..models import AIModel, ModelSyncLog

        log = ModelSyncLog.objects.create(sync_type='full')
        result = SyncResult(success=True)

        try:
            # Discover all models from sources
            registry = self._get_registry()
            registry._models.clear()  # Force fresh discovery
            discovered_models = registry.discover_all_models()
            logger.info(f"Discovered {len(discovered_models)} models from sources")

            # Track which model_keys we've seen
            seen_keys: Set[str] = set()

            with transaction.atomic():
                for model_key, model_info in discovered_models.items():
                    seen_keys.add(model_key)

                    try:
                        created, updated = self._sync_model(model_key, model_info)
                        if created:
                            result.added += 1
                            result.added_keys.append(model_key)
                        elif updated:
                            result.updated += 1
                    except Exception as e:
                        error_msg = f"Error syncing {model_key}: {e}"
                        logger.error(error_msg)
                        result.errors.append(error_msg)

                # ⚠ UNE DÉCOUVERTE INCOMPLÈTE NE PROUVE AUCUNE DISPARITION.
                #
                # Incident du 2026-08-22 : la déclaration de SAM3 a levé dans le processus qui
                # faisait le sync (exception avalée par un `except: pass` du registre). SAM3 est
                # donc sorti de `discovered_models`, s'est retrouvé « absent des sources », et sa
                # ligne de catalogue a été EFFACÉE — alors que le modèle était installé, en cache
                # et opérationnel. Le seul signe visible fut un `-1` dans le journal de sync ;
                # la référence de manifeste n'est devenue pendante que des heures plus tard.
                #
                # La réconciliation ne peut donc s'appuyer sur la découverte QUE si celle-ci s'est
                # déroulée entièrement. Sinon on ne sait pas distinguer « retiré du disque » de
                # « pas su le lire », et seule la première justifie une suppression.
                echecs = list(getattr(registry, 'discovery_errors', ()) or ())
                if echecs and (delete_missing or remove_missing):
                    message = (f"réconciliation SUSPENDUE : découverte incomplète "
                               f"({len(echecs)} échec(s)) — {'; '.join(echecs[:3])}")
                    logger.error(message)
                    result.errors.append(message)
                    delete_missing = remove_missing = False

                # Handle models no longer in sources
                if delete_missing:
                    # Delete models that no longer exist on disk.
                    # NB : exclure les candidats de prospection (is_proposed) — ils ne sont
                    # pas sur disque par nature et ne doivent pas être réconciliés.
                    missing_models = AIModel.objects.exclude(model_key__in=seen_keys).exclude(is_proposed=True)
                    removed_count = missing_models.count()
                    if removed_count > 0:
                        deleted_keys = list(missing_models.values_list('model_key', flat=True))
                        logger.info(f"Deleting {removed_count} models no longer on disk: {deleted_keys[:5]}...")
                        missing_models.delete()
                    result.removed = removed_count
                elif remove_missing:
                    # Just mark as unavailable (legacy behavior)
                    removed_count = AIModel.objects.exclude(
                        model_key__in=seen_keys
                    ).exclude(is_proposed=True).update(is_available=False)
                    result.removed = removed_count

            log.status = 'completed'
            log.models_added = result.added
            log.models_updated = result.updated
            log.models_removed = result.removed
            log.completed_at = timezone.now()
            log.save()

            logger.info(
                f"Full sync completed: +{result.added}, ~{result.updated}, -{result.removed}"
            )

        except Exception as e:
            logger.error(f"Full sync failed: {e}")
            result.success = False
            result.errors.append(str(e))

            log.status = 'failed'
            log.error_message = str(e)
            log.completed_at = timezone.now()
            log.save()

        return result

    def _sync_model(self, model_key: str, model_info) -> Tuple[bool, bool]:
        """
        Sync a single model to the database.

        Returns:
            Tuple of (created, updated)
        """
        from ..models import AIModel

        # Description courte : explicite si fournie, sinon dérivée du long (1re phrase,
        # tronquée à 200c) → le catalogue a toujours un court exploitable pour l'UI.
        long_desc = model_info.description or ''
        short_desc = getattr(model_info, 'description_short', '') or ''
        if not short_desc and long_desc:
            short_desc = long_desc.split('. ')[0].strip()
            if len(short_desc) > 200:
                short_desc = short_desc[:197].rstrip() + '…'

        defaults = {
            'name': model_info.name,
            'model_type': model_info.model_type.value,
            'source': model_info.source.value,
            'description': long_desc,
            'description_short': short_desc,
            'vram_gb': model_info.vram_gb or 0,
            'ram_gb': model_info.ram_gb or 0,
            'is_downloaded': model_info.is_downloaded,
            'is_loaded': model_info.is_loaded,
            # `is_available` VOLONTAIREMENT absent : le champ vaut True par défaut, donc une
            # ligne NEUVE naît disponible — mais le sync ne le REMET pas à True sur une ligne
            # existante. Un `False` y est une DÉCISION HUMAINE (« ce modèle n'est pas adapté »,
            # cf. face_yolov8m-seg_60, modèle adetailer qui trouve 0 visage sur une scène de
            # rue), et la découverte n'a pas autorité pour l'écraser — même principe que
            # `hf_id`/`quality_index` (2026-08-12). L'ABSENCE de fichier reste traitée par
            # `remove_missing`, qui pose False ; réactiver un modèle écarté est donc explicite.
            'format': model_info.format or '',
            'preferred_format': model_info.preferred_format or '',
            'can_convert_to': model_info.can_convert_to or [],
            'backend_ref': model_info.backend_ref or '',
            'extra_info': model_info.extra_info or {},
            # Canonicalisation CENTRALISÉE des capacités (vocabulaire unique) au point d'entrée du
            # catalogue : dérive `languages`/`supports_*`, mappe les clés legacy (native_diarization→
            # supports_diarization) et laisse les clés inconnues intactes. Ainsi le catalogue DB est
            # canonique quel que soit ce qu'émet `_discover_*` (résidu source tracé dans REMOVAL_LEDGER
            # R1/R2, à nettoyer en fin de parcours). Cf. common/utils/model_capabilities.py.
            'last_synced_at': timezone.now(),
        }

        # ── Champs que la découverte n'a PAS autorité pour EFFACER ────────────────────────────
        # `hf_id` et `quality_index` étaient dans `defaults` avec un repli `or ''` / `or None` :
        # à chaque sync, tout modèle dont la découverte n'en porte pas (les 70 issus du scan
        # disque) voyait sa valeur REMISE À VIDE. Conséquences mesurées le 2026-08-12 :
        #   • une provenance vérifiée posée par `backfill_platform_refs --poser` ne survivait pas
        #     au sync suivant — la porte d'entrée était donc inopérante ;
        #   • `quality_index` contredisait sa propre docstring (« une valeur posée à la main
        #     PRIME »), qui était vraie jusqu'au prochain `sync_models`.
        # On n'écrit donc QUE lorsque la découverte a réellement quelque chose à dire. Un modèle
        # dont l'amont perd son identité se corrige explicitement, pas par effet de bord.
        # (`license` et `platform_ref` n'ont jamais été dans `defaults` — ils survivaient déjà.)
        if model_info.hf_id:
            defaults['hf_id'] = model_info.hf_id
        _qualite = getattr(model_info, 'quality_index', None)
        if _qualite:
            defaults['quality_index'] = _qualite
        # `capabilities` REJOINT cette famille (2026-08-31) — c'était le DERNIER champ que la
        # découverte effaçait sans avoir rien à dire, et ça bloquait toute la route F4b.
        # Un modèle installé par la prospection et catalogué par le balayage GÉNÉRIQUE des
        # snapshots HF n'est déclaré par aucune app : sa découverte émet `{}`. En écrivant ce
        # `{}` dans `defaults`, chaque sync effaçait les capacités posées par son MANIFESTE —
        # le modèle restait donc invisible d'un filtre par capacité, à jamais (mesuré le
        # 2026-08-31 sur Kokoro-ONNX / chatterbox / Audio8 : catalogués, licenciés, avec
        # `composition`, et sans une seule capacité).
        # Règle INCHANGÉE pour tout le reste : quand la découverte SAIT (une app déclare le
        # modèle), elle écrit et fait autorité — c'est elle qui connaît les flags des backends.
        # Ce qui change : un `{}` ne veut pas dire « aucune capacité », il veut dire « je n'en
        # sais rien » — et on n'efface pas un fait sur une absence de savoir.
        _caps = normalize_capabilities(getattr(model_info, 'capabilities', None) or {})
        if _caps:
            defaults['capabilities'] = _caps
        # `composition` : MÊME RÈGLE, et pour la même raison (2026-09-01). La découverte sait
        # désormais dire le moteur d'exécution d'un modèle déclaré par une app
        # (`SYNTHESIZER_MODELS[*]['engine']` → `runtime.engine`), mais elle n'en sait toujours
        # rien pour les modèles orphelins : ceux-là tiennent leur `composition` de leur MANIFESTE
        # (anatomie des composants, moteur), et un `{}` de découverte ne doit pas l'effacer.
        # C'est exactement la règle « ne jamais écraser un fait curé par une absence » que la
        # clôture du 31/08 signalait comme MANQUANTE pour le kind `library` — elle vaut ici aussi.
        _compo = getattr(model_info, 'composition', None) or {}
        if _compo:
            defaults['composition'] = _compo

        # Add local_path if available in extra_info
        if model_info.extra_info and 'path' in model_info.extra_info:
            defaults['local_path'] = str(model_info.extra_info['path'])

        # Get disk_gb from extra_info if available.
        # Les trois clés sont TOUTES émises par la découverte, selon la branche : `disk_gb`
        # (ollama), `size_mb` (enhancer/ONNX), `size_bytes` (anonymizer/YOLO, model_registry:502).
        # `size_bytes` manquait ici → les 48 modèles de l'anonymizer sortaient à disk_gb=0 alors
        # que la taille était portée. Mesuré le 2026-08-12 : 19/101 renseignés, dont 0 anonymizer.
        if model_info.extra_info:
            if 'disk_gb' in model_info.extra_info:
                defaults['disk_gb'] = model_info.extra_info['disk_gb']
            elif 'size_mb' in model_info.extra_info:
                defaults['disk_gb'] = model_info.extra_info['size_mb'] / 1024
            elif 'size_bytes' in model_info.extra_info:
                defaults['disk_gb'] = (model_info.extra_info['size_bytes'] or 0) / (1024 ** 3)

        # Log what we're syncing
        logger.info(
            f"[ModelSync] Syncing {model_key}: "
            f"format={defaults.get('format', 'EMPTY')!r}, "
            f"preferred_format={defaults.get('preferred_format', 'EMPTY')!r}, "
            f"vram_gb={defaults.get('vram_gb', 0)}"
        )

        # Préserver les clés "collantes" de extra_info écrites hors découverte (détecteur de MAJ
        # check_model_updates, décisions admin) : le sync réécrit extra_info → sans ça il les efface.
        # `exclusion` rejoint les clés collantes (2026-08-12) : elle porte la RAISON d'un
        # `is_available=False` décidé par un humain. Sans elle, la décision survivait mais sa
        # justification était effacée au sync suivant — un modèle écarté sans qu'on sache
        # pourquoi finit par être réactivé « au cas où ».
        _sticky = ('update_check', 'recommended', 'exclusion')
        _existing = AIModel.objects.filter(model_key=model_key).values_list('extra_info', flat=True).first()
        if _existing:
            _merged = dict(defaults.get('extra_info') or {})
            for _k in _sticky:
                if _k in _existing and _k not in _merged:
                    _merged[_k] = _existing[_k]
            defaults['extra_info'] = _merged

        obj, created = AIModel.objects.update_or_create(
            model_key=model_key,
            defaults=defaults
        )

        # If not created, it was updated
        updated = not created

        logger.debug(f"[ModelSync] {model_key}: created={created}, updated={updated}")
        return created, updated

    def sync_file_change(
        self,
        file_path: Path,
        is_added: bool,
        source: str = None
    ) -> bool:
        """
        Sync a single file change (from watchdog).

        Args:
            file_path: Path to the model file
            is_added: True if file was added, False if removed
            source: Source identifier (will be auto-detected if None)

        Returns:
            True if sync was successful
        """
        from ..models import AIModel, ModelSyncLog

        try:
            if source is None:
                source = self._path_to_source(file_path)

            if source is None:
                logger.debug(f"Could not determine source for {file_path}")
                return False

            model_key = f"{source}:{file_path.stem}"

            if is_added:
                # Create or update model entry
                model_info = self._create_model_info_from_path(file_path, source)
                if model_info:
                    self._sync_model(model_key, model_info)
                    logger.info(f"Synced new model: {model_key}")
            else:
                # Mark model as not downloaded (don't delete - keep in catalog)
                AIModel.objects.filter(model_key=model_key).update(
                    is_downloaded=False,
                    is_loaded=False,
                    updated_at=timezone.now()
                )
                logger.info(f"Marked model as not downloaded: {model_key}")

            return True

        except Exception as e:
            logger.error(f"Error syncing file change for {file_path}: {e}")
            return False

    def _path_to_source(self, path: Path) -> Optional[str]:
        """Determine source from file path."""
        path_str = str(path).lower()

        if 'enhancer' in path_str or 'upscal' in path_str:
            return 'enhancer'
        elif 'anonymizer' in path_str or 'yolo' in path_str or 'sam' in path_str:
            return 'anonymizer'
        elif 'imager' in path_str or 'diffusion' in path_str or 'wan' in path_str:
            return 'imager'
        elif 'transcriber' in path_str or 'whisper' in path_str:
            return 'transcriber'
        elif 'synthesizer' in path_str or 'tts' in path_str or 'coqui' in path_str:
            return 'synthesizer'
        elif 'describer' in path_str or 'blip' in path_str or 'bart' in path_str:
            return 'describer'
        elif 'vision' in path_str:
            return 'anonymizer'
        elif 'speech' in path_str:
            return 'transcriber'

        return None

    def _create_model_info_from_path(self, path: Path, source: str):
        """Create a ModelInfo-like object from file path."""
        from .model_registry import ModelInfo, ModelType, ModelSource

        # Map source string to enums
        source_mapping = {
            'enhancer': (ModelSource.WAMA_ENHANCER, ModelType.UPSCALING),
            'anonymizer': (ModelSource.WAMA_ANONYMIZER, ModelType.VISION),
            'imager': (ModelSource.WAMA_IMAGER, ModelType.DIFFUSION),
            'transcriber': (ModelSource.WAMA_TRANSCRIBER, ModelType.SPEECH),
            'synthesizer': (ModelSource.WAMA_SYNTHESIZER, ModelType.SPEECH),
            'describer': (ModelSource.WAMA_DESCRIBER, ModelType.VLM),
        }

        model_source, model_type = source_mapping.get(
            source,
            (ModelSource.WAMA_IMAGER, ModelType.DIFFUSION)
        )

        # Get file info
        try:
            file_size_mb = path.stat().st_size / (1024 * 1024)
        except OSError:
            file_size_mb = 0

        format_type = path.suffix.lstrip('.').lower()

        # Determine preferred format from policy
        from wama.common.utils.format_policy import get_preferred_format
        category = source if source != 'anonymizer' else 'vision'
        preferred = get_preferred_format(category)

        return ModelInfo(
            id=f"{source}:{path.stem}",
            name=path.stem,
            model_type=model_type,
            source=model_source,
            description=f"Discovered model ({file_size_mb:.1f}MB)",
            is_downloaded=True,
            format=format_type,
            preferred_format=preferred,
            extra_info={
                'path': str(path),
                'size_mb': file_size_mb,
                'auto_discovered': True,
            }
        )

    def update_download_status(self, model_key: str, is_downloaded: bool) -> bool:
        """Update the download status of a model."""
        from ..models import AIModel

        try:
            updated = AIModel.objects.filter(model_key=model_key).update(
                is_downloaded=is_downloaded,
                updated_at=timezone.now()
            )
            return updated > 0
        except Exception as e:
            logger.error(f"Error updating download status for {model_key}: {e}")
            return False

    def update_loaded_status(self, model_key: str, is_loaded: bool) -> bool:
        """Update the loaded status of a model."""
        from ..models import AIModel

        try:
            update_fields = {
                'is_loaded': is_loaded,
                'updated_at': timezone.now()
            }
            if is_loaded:
                update_fields['last_used_at'] = timezone.now()

            updated = AIModel.objects.filter(model_key=model_key).update(**update_fields)
            return updated > 0
        except Exception as e:
            logger.error(f"Error updating loaded status for {model_key}: {e}")
            return False

    def get_stats(self) -> Dict:
        """Get catalog statistics."""
        from ..models import AIModel

        total = AIModel.objects.filter(is_available=True).count()
        downloaded = AIModel.objects.filter(is_available=True, is_downloaded=True).count()
        loaded = AIModel.objects.filter(is_available=True, is_loaded=True).count()

        by_source = {}
        for source in AIModel.objects.filter(is_available=True).values_list(
            'source', flat=True
        ).distinct():
            by_source[source] = {
                'total': AIModel.objects.filter(source=source, is_available=True).count(),
                'downloaded': AIModel.objects.filter(
                    source=source, is_available=True, is_downloaded=True
                ).count(),
            }

        by_type = {}
        for model_type in AIModel.objects.filter(is_available=True).values_list(
            'model_type', flat=True
        ).distinct():
            by_type[model_type] = AIModel.objects.filter(
                model_type=model_type, is_available=True
            ).count()

        return {
            'total': total,
            'downloaded': downloaded,
            'loaded': loaded,
            'by_source': by_source,
            'by_type': by_type,
        }


# Singleton instance
_sync_service: Optional[ModelSyncService] = None


def get_sync_service() -> ModelSyncService:
    """Get the singleton ModelSyncService instance."""
    global _sync_service
    if _sync_service is None:
        _sync_service = ModelSyncService()
    return _sync_service
