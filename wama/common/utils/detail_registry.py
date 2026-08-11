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
    def register(cls, app_name, model_class, adapter, spec=None):
        """`spec` (A3a, route §10.3) : la DONNÉE déclarative dont l'adapter est dérivé, quand
        l'app est passée par `register_app_detail_spec` — c'est elle que la facette `inspector`
        du manifeste extrait et que le gabarit apps_gen saura projeter. None = adapter code
        (chemin des logiques irréductibles)."""
        cls._registry[app_name] = {'model': model_class, 'adapter': adapter, 'spec': spec}

    @classmethod
    def is_registered(cls, app_name):
        return app_name in cls._registry

    @classmethod
    def get(cls, app_name):
        return cls._registry.get(app_name)


def register_app_detail(app_name, model_class, adapter):
    """Enregistre l'adapter de détail d'une app. `adapter(instance) -> dict canonique`."""
    DetailRegistry.register(app_name, model_class, adapter)


def register_app_detail_spec(app_name, model_class, spec):
    """Variante DÉCLARATIVE (A3a) : la registration est une SPEC-donnée, pas un callable.

    La spec mappe les arguments de `build_detail` vers des NOMS DE CHAMPS du modèle (ou des
    constantes), déclare les réglages à afficher, et les alias vers les clés canoniques :

      {'source_file': 'input_file',
       'source_type': 'media_type' | {'const': 'document'},
       'engine': 'backend', 'engine_effective': 'used_backend',
       'result_file': 'output_file', 'result_text': 'result_text', 'source_text': …,
       'extra': [{'label': 'Langue', 'field': 'language'},
                 {'label': 'Mode', 'field': 'mode', 'display': True}],   # get_<f>_display()
       'extra_from_params': 'options' | True,   # labels du SCHÉMA (schema_for_app) ; str =
                                                # champ JSON porteur, True = champs individuels
       'aliases': {'quality_preset': 'output_quality'}}

    Étant une donnée, elle est EXTRACTIBLE (facette `inspector` du manifeste) et PROJETABLE
    (gabarit apps_gen) — c'est le déblocage de la marche A3. Une app à logique irréductible
    garde `register_app_detail` (adapter code)."""
    DetailRegistry.register(app_name, model_class,
                            lambda instance: detail_from_spec(instance, spec, app_name),
                            spec=spec)


def detail_from_spec(instance, spec, app_name):
    """Adapter GÉNÉRIQUE : résout la spec déclarative contre l'instance puis délègue à
    `build_detail` (l'épine dorsale reste la source unique du schéma canonique)."""
    def _val(cle):
        f = spec.get(cle)
        if not f:
            return None
        if isinstance(f, dict):
            return f.get('const')
        return getattr(instance, f, None)

    extra = {}
    for e in (spec.get('extra') or []):
        champ, label = e.get('field'), e.get('label') or e.get('field')
        if e.get('display'):
            fn = getattr(instance, f'get_{champ}_display', None)
            v = fn() if callable(fn) and getattr(instance, champ, None) else None
        else:
            v = getattr(instance, champ, None)
        extra[label] = v or None
    src_params = spec.get('extra_from_params')
    if src_params:
        from .param_schema import schema_for_app
        valeurs = (getattr(instance, src_params, None) or {}) if isinstance(src_params, str) \
            else None
        for p in (schema_for_app(app_name) or []):
            label, nom = p.get('label'), p.get('name')
            if not label or not nom:
                continue
            v = valeurs.get(nom) if valeurs is not None else getattr(instance, nom, None)
            # 0 compris : dans ces schémas une valeur nulle est un réglage non posé.
            if v not in (None, '', False, 0):
                extra[label] = v

    d = build_detail(
        instance,
        source_file=_val('source_file'),
        source_type=_val('source_type'),
        engine=_val('engine'),
        engine_effective=_val('engine_effective'),
        result_file=_val('result_file'),
        result_text=_val('result_text') or None,
        source_text=_val('source_text'),
        extra=extra or None,
    )
    for champ, cle in (spec.get('aliases') or {}).items():
        v = getattr(instance, champ, None)
        if v:
            d[cle] = v
    return d


def _short_error(err: str, limit: int = 280) -> str:
    """Résumé LISIBLE d'un message d'erreur pour le volet inspecteur (2026-08-03).

    Les workers stockent parfois la traceback complète (précieuse en console/logs) —
    affichée brute elle NOIE le volet INFOS. La ligne utile d'une traceback est la
    DERNIÈRE non vide (l'exception levée) : on la garde, tronquée, avec un marqueur.
    """
    err = (err or '').strip()
    if not err:
        return err
    lines = [l.strip() for l in err.splitlines() if l.strip()]
    if len(lines) > 1:
        # traceback / multi-lignes → la dernière ligne porte l'exception
        summary = lines[-1]
        if len(summary) < 20 and len(lines) >= 2:
            summary = lines[-2] + ' — ' + summary
        summary = '[…] ' + summary if len(lines) > 2 else summary
    else:
        summary = lines[0]
    if len(summary) > limit:
        summary = summary[:limit - 1] + '…'
    return summary


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
        d['error_message'] = _short_error(err)

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
