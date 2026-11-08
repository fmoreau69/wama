"""
Format Converter Service

Centralized service for model format conversions.

Les conversions se font À LA MAIN (`can_convert_to`). Le format RECOMMANDÉ, que lisent les
suggestions et les statistiques, se dérive du moteur DÉCLARÉ de chaque ligne du catalogue
(`format_policy.preferred_format`) : jusqu'au 2026-11-08 il venait d'une catégorie devinée sur le
NOM du dossier (`dir_to_category`, « diffusion » par défaut), et une conversion automatique à
l'installation (`auto_convert_on_download`) n'avait aucun appelant (`REMOVAL_LEDGER R229`).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Result of a model conversion operation."""
    success: bool
    message: str
    source_path: str
    target_path: Optional[str] = None
    source_format: str = ''
    target_format: str = ''
    size_before_mb: float = 0
    size_after_mb: float = 0


@dataclass
class ConversionSuggestion:
    """Suggestion for a model format conversion."""
    model_id: str
    model_path: str
    current_format: str
    suggested_format: str
    engine: str
    reason: str
    priority: int = 0  # Higher = more important


class FormatConverter:
    """
    Centralized service for model format conversions.

    Supports:
    - .pt/.pth → .safetensors
    - .bin → .safetensors
    - .pt (YOLO) → .onnx
    - Generic PyTorch → .onnx
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._initialized = getattr(self, '_initialized', False)
        if self._initialized:
            return
        self._initialized = True

    def convert_model(
        self,
        model_path: str,
        target_format: str,
        model_type: Optional[str] = None,
        keep_original: bool = True,
        **kwargs
    ) -> ConversionResult:
        """
        Convert a model to a different format.

        Args:
            model_path: Path to the source model file
            target_format: Target format ('safetensors', 'onnx')
            model_type: Type hint for conversion ('yolo', 'diffusion', 'generic')
            keep_original: Whether to keep the original file. À False, la source n'est PAS
                simplement effacée : elle est d'abord archivée sur l'espace distant et
                vérifiée (_retire_source). Elle reste en local si l'archivage échoue.
            **kwargs: Additional arguments for specific converters

        Returns:
            ConversionResult with conversion details
        """
        from wama.common.utils.safetensors_utils import get_model_format

        source_path = Path(model_path)
        if not source_path.exists():
            return ConversionResult(
                success=False,
                message=f"Source file not found: {model_path}",
                source_path=model_path,
            )

        source_format = get_model_format(model_path)
        size_before = source_path.stat().st_size / (1024 * 1024)

        # Route to appropriate converter
        if target_format.lower() == 'safetensors':
            result = self._convert_to_safetensors(
                model_path, source_format, keep_original
            )
        elif target_format.lower() == 'onnx':
            result = self._convert_to_onnx(
                model_path, source_format, model_type, keep_original, **kwargs
            )
        else:
            return ConversionResult(
                success=False,
                message=f"Unsupported target format: {target_format}",
                source_path=model_path,
                source_format=source_format,
            )

        # Add size info
        result.source_format = source_format
        result.target_format = target_format
        result.size_before_mb = round(size_before, 2)

        if result.success and result.target_path:
            target_path = Path(result.target_path)
            if target_path.exists():
                result.size_after_mb = round(
                    target_path.stat().st_size / (1024 * 1024), 2
                )

        return result

    def _retire_source(self, model_path: str) -> bool:
        """
        Retire le fichier SOURCE après une conversion réussie — JAMAIS par un unlink() sec.

        Invariant WAMA : le LOCAL ne garde que le format cible (ex. .onnx), l'espace
        DISTANT garde les deux (.pt d'origine + .onnx converti). La suppression locale
        doit donc être précédée d'une sauvegarde VÉRIFIÉE : offload_file() copie,
        compare la taille, et ne supprime qu'ensuite.

        overwrite=False : si le poids d'origine est déjà archivé, on ne re-transfère pas
        plusieurs Go pour rien — la vérification de taille reste faite, donc une copie
        distante tronquée bloque quand même la suppression.

        Si l'espace distant est indisponible, la source est CONSERVÉE en local : perdre
        un poids d'origine est irréversible, garder un fichier en trop ne l'est pas.

        Returns: True si la source a bien été archivée puis supprimée en local.
        """
        from .remote_backup import get_backup_service

        service = get_backup_service()
        if not service.is_available():
            logger.warning(
                f"Source conservée ({model_path}) : espace de sauvegarde distant "
                f"indisponible — suppression locale refusée, le format d'origine serait perdu."
            )
            return False

        result = service.offload_file(model_path, overwrite=False)
        if not result.get('deleted'):
            logger.warning(
                f"Source conservée ({model_path}) : "
                f"{result.get('error') or 'offload incomplet'}"
            )
            return False

        logger.info(
            f"Source archivée puis supprimée en local : {model_path} -> {result.get('dest_path')}"
        )
        return True

    def _convert_to_safetensors(
        self,
        model_path: str,
        source_format: str,
        keep_original: bool,
    ) -> ConversionResult:
        """Convert a model to safetensors format."""
        from wama.common.utils.safetensors_utils import (
            convert_pt_to_safetensors,
            convert_bin_to_safetensors,
        )

        # remove_original=False EN DUR : la suppression de la source passe uniquement par
        # _retire_source() (archivage vérifié d'abord). Ne pas déléguer la suppression à
        # la lib de conversion, qui ferait un unlink() sec sans filet.
        if source_format in ['pt', 'pth']:
            success, message, output_path = convert_pt_to_safetensors(
                model_path,
                remove_original=False,
            )
        elif source_format == 'bin':
            success, message, output_path = convert_bin_to_safetensors(
                model_path,
                remove_original=False,
            )
        else:
            return ConversionResult(
                success=False,
                message=f"Cannot convert {source_format} to safetensors",
                source_path=model_path,
            )

        if success and not keep_original:
            self._retire_source(model_path)

        return ConversionResult(
            success=success,
            message=message,
            source_path=model_path,
            target_path=output_path,
        )

    def _convert_to_onnx(
        self,
        model_path: str,
        source_format: str,
        model_type: Optional[str],
        keep_original: bool,
        **kwargs
    ) -> ConversionResult:
        """Convert a model to ONNX format."""
        from wama.common.utils.onnx_utils import (
            convert_yolo_to_onnx,
            convert_pytorch_to_onnx,
        )

        if source_format not in ['pt', 'pth']:
            return ConversionResult(
                success=False,
                message=f"Cannot convert {source_format} to ONNX",
                source_path=model_path,
            )

        # Use YOLO-specific converter if appropriate
        if model_type == 'yolo' or self._is_yolo_model(model_path):
            success, message, output_path = convert_yolo_to_onnx(
                model_path,
                imgsz=kwargs.get('imgsz', 640),
                half=kwargs.get('half', False),
                dynamic=kwargs.get('dynamic', True),
                simplify=kwargs.get('simplify', True),
                opset=kwargs.get('opset', 12),
            )

            if success and not keep_original:
                self._retire_source(model_path)

            return ConversionResult(
                success=success,
                message=message,
                source_path=model_path,
                target_path=output_path,
            )

        # Generic PyTorch conversion requires input shape
        input_shape = kwargs.get('input_shape')
        if not input_shape:
            return ConversionResult(
                success=False,
                message="Generic PyTorch to ONNX conversion requires input_shape parameter",
                source_path=model_path,
            )

        try:
            import torch
            model = torch.load(model_path, map_location='cpu', weights_only=False)
            output_path = str(Path(model_path).with_suffix('.onnx'))

            success, message = convert_pytorch_to_onnx(
                model,
                output_path,
                input_shape=input_shape,
                input_names=kwargs.get('input_names'),
                output_names=kwargs.get('output_names'),
                dynamic_axes=kwargs.get('dynamic_axes'),
                opset_version=kwargs.get('opset', 12),
            )

            if success and not keep_original:
                self._retire_source(model_path)

            return ConversionResult(
                success=success,
                message=message,
                source_path=model_path,
                target_path=output_path if success else None,
            )
        except Exception as e:
            return ConversionResult(
                success=False,
                message=f"Conversion failed: {str(e)}",
                source_path=model_path,
            )

    def _is_yolo_model(self, model_path: str) -> bool:
        """Check if a model is a YOLO model based on path or content."""
        path_lower = model_path.lower()
        return 'yolo' in path_lower or 'ultralytics' in path_lower

    def get_conversion_options(self, model_path: str) -> List[str]:
        """
        Get available conversion options for a model.

        Args:
            model_path: Path to the model file

        Returns:
            List of formats the model can be converted to
        """
        from wama.common.utils.safetensors_utils import get_model_format

        current_format = get_model_format(model_path)
        options = []

        if current_format in ['pt', 'pth']:
            options.extend(['safetensors', 'onnx'])
        elif current_format == 'bin':
            options.append('safetensors')
        elif current_format == 'ckpt':
            options.extend(['safetensors', 'onnx'])

        return options

    def scan_and_suggest(self) -> List[ConversionSuggestion]:
        """Les modèles INSTALLÉS du catalogue dont le format n'est pas celui que lit leur moteur
        déclaré (`format_policy.conversion_suggestion`) — rien pour un moteur qui lit plusieurs
        formats, ni pour une ligne sans moteur."""
        from wama.common.utils.format_policy import conversion_suggestion
        from wama.model_manager.models import AIModel

        suggestions = []
        for row in AIModel.objects.filter(is_downloaded=True).exclude(format='') \
                .only('model_key', 'local_path', 'format', 'composition'):
            suggested = conversion_suggestion(row.format, row.composition)
            if suggested:
                engine = ((row.composition or {}).get('runtime') or {}).get('engine') or ''
                suggestions.append(ConversionSuggestion(
                    model_id=row.model_key,
                    model_path=row.local_path,
                    current_format=row.format,
                    suggested_format=suggested,
                    engine=engine,
                    reason=f"le moteur déclaré ({engine}) lit le format {suggested}",
                    priority=1,
                ))
        return suggestions

    def batch_convert(
        self,
        model_paths: List[str],
        target_format: str,
        model_type: Optional[str] = None,
        keep_originals: bool = True,
        **kwargs
    ) -> Dict[str, ConversionResult]:
        """
        Convert multiple models to a target format.

        Args:
            model_paths: List of model file paths
            target_format: Target format for all models
            model_type: Model type hint
            keep_originals: Whether to keep original files
            **kwargs: Additional converter arguments

        Returns:
            Dict mapping model paths to conversion results
        """
        results = {}
        for model_path in model_paths:
            results[model_path] = self.convert_model(
                model_path,
                target_format,
                model_type=model_type,
                keep_original=keep_originals,
                **kwargs
            )
        return results

    def get_format_stats(self) -> Dict[str, Any]:
        """Les formats des modèles INSTALLÉS du catalogue, par moteur déclaré, et leur conformité :
        une ligne dont le moteur lit un seul format (`format_policy.preferred_format`) est conforme
        quand elle l'a ; les autres n'ont pas de format recommandé et ne comptent pas."""
        from wama.common.utils.format_policy import get_format_stats_template, preferred_format
        from wama.model_manager.models import AIModel

        stats = get_format_stats_template()
        compliance = {'compliant': 0, 'non_compliant': 0}
        by_engine = {}
        for row in AIModel.objects.filter(is_downloaded=True).only('format', 'composition'):
            fmt = (row.format or 'unknown').lower()
            stats[fmt] = stats.get(fmt, 0) + 1
            engine = ((row.composition or {}).get('runtime') or {}).get('engine') or ''
            counts = by_engine.setdefault(engine, get_format_stats_template())
            counts[fmt] = counts.get(fmt, 0) + 1
            preferred = preferred_format(row.composition)
            if preferred:
                compliance['compliant' if fmt == preferred else 'non_compliant'] += 1

        total = compliance['compliant'] + compliance['non_compliant']
        compliance['percentage'] = round(
            (compliance['compliant'] / total * 100) if total > 0 else 100, 1
        )

        return {
            'formats': stats,
            'compliance': compliance,
            'by_engine': by_engine,
            'total_models': sum(stats.values()),
        }


#: Les formats SOURCE qu'une conversion sait lire (`FormatConverter.convert_model`).
CONVERTIBLE_EXTS = ('.pt', '.pth', '.bin', '.ckpt')


def resolve_weight_file(ref: str):
    """
    Chemin du FICHIER de poids à convertir, depuis ce que l'UI envoie réellement : un chemin
    de fichier (rendu inchangé), un chemin de dossier, ou un ID de catalogue
    (`synthesizer:kokoro`) — résolu via `AIModel.extra_info['path']` puis, à défaut, le
    registre. Un dossier (snapshot HF compris) descend vers son plus gros fichier
    convertible. Retourne None si rien de convertible.

    Bug d'origine (2026-08-31) : `api_convert_and_backup` recevait l'ID de catalogue et le
    traitait comme un chemin — « Source file not found » systématique pour tous les modèles
    déclarés par app (les boutons Convert ne marchaient QUE pour les modèles découverts par
    scan disque, dont l'id EST un chemin). Sorti de la vue le 2026-11-08 : l'outil de
    l'assistant (`tool_api.convert_model_format`) résout la même clé par le même geste.
    """
    if not ref:
        return None

    def weight_file(p: Path):
        if p.is_file():
            return str(p) if p.suffix.lower() in CONVERTIBLE_EXTS else None
        if p.is_dir():
            weights = [f for f in p.rglob('*')
                       if f.is_file() and f.suffix.lower() in CONVERTIBLE_EXTS]
            if weights:
                # Le plus gros fichier = les poids du modèle (les petits .pt d'un snapshot
                # sont des têtes auxiliaires/config, jamais la cible d'une conversion).
                return str(max(weights, key=lambda f: f.stat().st_size))
        return None

    p = Path(ref)
    if p.exists():
        return weight_file(p)

    # ID de catalogue : la ligne AIModel porte le chemin posé par la découverte…
    from wama.model_manager.models import AIModel
    row = AIModel.objects.filter(model_key=ref).first()
    path = ((row.extra_info or {}).get('path') or row.local_path or '') if row else ''
    if not path:
        # …sinon le registre (découverte fraîche — tolérant au type de retour).
        from .model_registry import ModelRegistry
        res = ModelRegistry().discover_all_models()
        items = res.values() if hasattr(res, 'values') else res
        for info in items:
            if getattr(info, 'id', None) == ref:
                path = ((getattr(info, 'extra_info', None) or {}).get('path') or '')
                break
    return weight_file(Path(path)) if path else None


def conversion_options(ref: str) -> dict | None:
    """`{'model_path', 'current_format', 'available_conversions'}` du fichier de poids que `ref`
    désigne (chemin ou clé de catalogue, `resolve_weight_file`), None si rien de convertible —
    la lecture de la route `api/convert/options/` et de l'outil `get_model_formats`."""
    from wama.common.utils.safetensors_utils import get_model_format
    path = resolve_weight_file(ref)
    if path is None:
        return None
    return {'model_path': path, 'current_format': get_model_format(path),
            'available_conversions': FormatConverter().get_conversion_options(path)}


def convert_and_backup(ref: str, target_format: str = 'safetensors', *,
                       model_type: str = 'unknown', model_name: str | None = None,
                       backup_after: bool = True,
                       delete_source_after_backup: bool = False) -> dict:
    """Le geste « Convertir » de la gestion des modèles, UN corps pour la page et l'assistant :
    résoudre le fichier de poids (`resolve_weight_file`), le convertir, archiver le converti sur
    l'espace distant, puis — opt-in explicite — retirer la source locale après un archivage
    VÉRIFIÉ (`remote_backup.offload_file`). Rend `{'success', 'conversion', 'backup'?,
    'offload'?}`, ou `{'success': False, 'error', 'not_found'?}`."""
    from .remote_backup import get_backup_service

    resolved = resolve_weight_file(ref)
    if resolved is None:
        return {'success': False, 'not_found': True,
                'error': f"Aucun fichier de poids convertible trouvé pour « {ref} » "
                         f"(formats source : {', '.join(CONVERTIBLE_EXTS)})"}
    model_name = model_name or Path(resolved).stem

    result = FormatConverter().convert_model(resolved, target_format)
    if not result.success:
        return {'success': False, 'error': f'Conversion failed: {result.message}',
                'conversion': {'success': False, 'message': result.message}}

    response = {'success': True, 'conversion': {
        'success': True, 'source_path': result.source_path, 'target_path': result.target_path,
        'source_format': result.source_format, 'target_format': result.target_format,
        'size_before_mb': result.size_before_mb, 'size_after_mb': result.size_after_mb,
    }}
    if backup_after:
        service = get_backup_service()
        if service.is_available():
            backup = service.backup_file(result.target_path, model_type, model_name,
                                         target_format, overwrite=True)
            response['backup'] = {'success': backup.success, 'dest_path': backup.dest_path,
                                  'size_mb': backup.size_mb, 'error': backup.error}
        else:
            response['backup'] = {'success': False, 'error': 'Remote backup path not accessible'}
    # Offload du fichier SOURCE (ex. .pt) — OPT-IN explicite, destructif : sauvegardé sur le
    # distant (miroir), VÉRIFIÉ, puis supprimé en local ; jamais si la vérification échoue.
    if delete_source_after_backup:
        response['offload'] = get_backup_service().offload_file(result.source_path)
    return response
