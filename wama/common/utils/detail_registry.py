"""
WAMA Common — Registre des DÉTAILS d'item pour l'inspecteur (miroir de preview_registry).

`unified_detail(app, pk)` renvoie les infos d'un item selon le schéma canonique figé
(INSPECTOR_DETAIL_FIELDS.md) : un dict plat {clé_canonique: valeur} + `extra` (réglages
spécifiques d'app). Les LABELS/ICÔNES/SECTIONS vivent côté JS (DETAIL_SCHEMA de WamaDetails) —
ici on ne produit que les VALEURS par clé canonique.

Chaque app enregistre un adapter dans son apps.py :
    from wama.common.utils.detail_registry import register_app_detail
    register_app_detail('reader', ReadingItem, reader_detail_adapter)

L'adapter reçoit l'instance et renvoie le dict canonique (via build_detail).
"""

# Statuts hétérogènes → normalisation d'AFFICHAGE (base inchangée) : DONE→SUCCESS, ERROR→FAILURE.
_STATUS_ALIAS = {'DONE': 'SUCCESS', 'ERROR': 'FAILURE'}

# Icône de `source_properties` dérivée du type de média (jamais la vague audio par défaut).
_PROPS_ICON = {
    'audio': 'fa-wave-square', 'image': 'fa-image', 'video': 'fa-film',
    'document': 'fa-file-lines', 'pdf': 'fa-file-lines', 'text': 'fa-file-lines',
    'archive': 'fa-file-zipper', 'zip': 'fa-file-zipper',
}


def props_icon_for(media_type: str) -> str:
    return _PROPS_ICON.get((media_type or '').lower(), 'fa-circle-info')


def normalize_status(status: str) -> str:
    s = (status or '').upper()
    return _STATUS_ALIAS.get(s, s)


class DetailRegistry:
    _registry = {}

    @classmethod
    def register(cls, app_name, model_class, adapter):
        cls._registry[app_name] = {'model': model_class, 'adapter': adapter}

    @classmethod
    def is_registered(cls, app_name):
        return app_name in cls._registry

    @classmethod
    def get(cls, app_name):
        return cls._registry.get(app_name)


def register_app_detail(app_name, model_class, adapter):
    """Enregistre l'adapter de détail d'une app. `adapter(instance) -> dict canonique`."""
    DetailRegistry.register(app_name, model_class, adapter)


def build_detail(instance, *, source_file=None, source_type=None, engine=None,
                 engine_effective=None, result_file=None, result_text=None,
                 source_text=None, extra=None):
    """Assemble le dict canonique d'un item (épine dorsale). Les valeurs vides sont OMISES
    (la ligne disparaît côté WamaDetails). `extra` = réglages spécifiques d'app {label: valeur}.

    Arguments = valeurs DÉJÀ résolues par l'adapter (il connaît les noms de champs de son modèle) :
      source_file (FieldFile|str), source_type (str), engine, engine_effective, result_file,
      result_text (str — clé canonique AJOUTÉE 2026-07-13 pour les apps à sortie TEXTE :
      transcriber/describer/reader ; consommée par le runner générique du studio).
    Les champs communs (id/created_at/status/…) sont lus directement sur l'instance.
    """
    def _url(f):
        # Gère str, FieldFile plein/vide (hasattr(fieldfile,'url') lève ValueError si vide → à éviter).
        if not f:
            return None
        if isinstance(f, str):
            return f
        try:
            return f.url if getattr(f, 'name', None) else None
        except Exception:
            return None

    d = {}
    d['id'] = getattr(instance, 'id', None)
    created = getattr(instance, 'created_at', None) or getattr(instance, 'uploaded_at', None)
    if created:
        d['created_at'] = created.strftime('%d/%m/%Y %H:%M')

    src = _url(source_file)
    if src:
        d['source_file'] = src
    if source_type:
        d['source_type'] = source_type
        d['source_properties_icon'] = props_icon_for(source_type)

    dur = getattr(instance, 'duration_display', None) or getattr(instance, 'duration_inMinSec', None)
    if dur:
        d['source_duration_display'] = dur
    props = getattr(instance, 'properties', None)
    if props:
        d['source_properties'] = props

    # Fallback UNIVERSEL (chantier lié INSPECTOR_DETAIL_FIELDS.md) : si l'app ne fournit ni
    # propriétés ni durée, sonde commune probe_media (image L×H / vidéo fps / audio kHz /
    # PDF pages / archive entrées), cachée par (chemin, mtime) — une sonde par fichier.
    if (source_file and not isinstance(source_file, str)
            and (not d.get('source_properties') or not d.get('source_duration_display'))):
        try:
            fpath = source_file.path if getattr(source_file, 'name', None) else None
        except Exception:
            fpath = None
        if fpath:
            from .media_probe import probe_media_cached
            info = probe_media_cached(fpath)
            if info.get('properties') and not d.get('source_properties'):
                d['source_properties'] = info['properties']
            if info.get('duration_display') and not d.get('source_duration_display'):
                d['source_duration_display'] = info['duration_display']
            if info.get('media_type') and not source_type:
                d['source_type'] = info['media_type']
                d['source_properties_icon'] = props_icon_for(info['media_type'])

    if engine:
        d['engine'] = engine
    if engine_effective and engine_effective != engine:
        d['engine_effective'] = engine_effective

    res = _url(result_file)
    if res:
        d['result_file'] = res

    if result_text:
        d['result_text'] = result_text
    if source_text:
        # Clé canonique du TEXTE D'ENTRÉE (prompt) — symétrique de result_text. Lue par
        # `preview_utils._input_preview` pour servir l'entrée sans nom de champ en dur.
        d['source_text'] = source_text

    for k in ('output_format', 'output_quality'):
        v = getattr(instance, k, None)
        if v:
            d[k] = v

    d['status'] = normalize_status(getattr(instance, 'status', ''))
    err = getattr(instance, 'error_message', None)
    if err:
        d['error_message'] = err

    pt = getattr(instance, 'processing_display', None)
    if pt:
        d['processing_time_display'] = pt

    if extra:
        d['extra'] = {k: v for k, v in extra.items() if v not in (None, '', False)}
    return d


def unified_detail(request, app_name: str, pk: int):
    """Endpoint commun : infos d'un item selon le schéma canonique (miroir de unified_preview)."""
    from django.http import JsonResponse, HttpResponseNotFound, HttpResponseForbidden
    from django.shortcuts import get_object_or_404

    entry = DetailRegistry.get(app_name)
    if not entry:
        return HttpResponseNotFound(f"App '{app_name}' non enregistrée pour le détail")
    instance = get_object_or_404(entry['model'], pk=pk)

    viewer = request.user if request.user.is_authenticated else None
    owner = getattr(instance, 'user', None)
    if owner is not None and viewer is not None and owner != viewer and not viewer.is_staff:
        return HttpResponseForbidden("Accès refusé.")

    try:
        return JsonResponse(entry['adapter'](instance))
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
