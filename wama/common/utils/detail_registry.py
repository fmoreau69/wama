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

# Statuts hétérogènes → normalisation d'AFFICHAGE (base inchangée).
# ⚠ La table vit désormais au DOMICILE DU VOCABULAIRE (`common/models.JOB_STATUS_ALIASES`,
# 2026-09-17, marche P2). Celle qui était écrite ici n'avait que deux entrées (DONE, ERROR) :
# elle ignorait `COMPLETED`/`FAILED`, donc un état du monde LAB lu par le journal ressortait BRUT
# à l'écran. Cette fonction garde son nom et sa signature — elle a des consommateurs (journal,
# générateur de vues) —, elle ne porte simplement plus sa propre table.

# Icône de `source_properties` dérivée du type de média (jamais la vague audio par défaut).
_PROPS_ICON = {
    'audio': 'fa-wave-square', 'image': 'fa-image', 'video': 'fa-film',
    'document': 'fa-file-lines', 'pdf': 'fa-file-lines',
    # 'text' reste en LECTURE (valeurs historiques en base — describer) ; nature retirée 30/08.
    'text': 'fa-file-lines', 'dataset': 'fa-table',
    'archive': 'fa-file-zipper', 'zip': 'fa-file-zipper',
}


def props_icon_for(media_type: str) -> str:
    return _PROPS_ICON.get((media_type or '').lower(), 'fa-circle-info')


def normalize_status(status: str) -> str:
    """Un statut d'app → le vocabulaire commun. Délègue au domicile (`common/models.py`)."""
    from wama.common.models import normalize_job_status
    return normalize_job_status(status)


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

    @classmethod
    def registered_apps(cls):
        """Apps ayant un adapter de détail, triées. Accesseur PUBLIC : `tool_api` en a besoin
        pour nommer les cibles valides d'une erreur, et lire `_registry` de l'extérieur ferait
        d'un attribut privé une API de fait."""
        return sorted(cls._registry)


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
       # RÔLE d'asset de la sortie (2026-09-18, décision Fabien : « filtrer par rôle, au
       # commun, pour toutes les apps ») — ce que la médiathèque en ferait. Const, champ, ou
       # champ TRADUIT : {'field': 'media_type', 'map': MEDIA_CATEGORY_ROLE}. Non déclaré =
       # le geste commun laisse choisir parmi les rôles admissibles pour l'extension.
       'result_role': {'field': 'media_type', 'map': MEDIA_CATEGORY_ROLE},
       'extra': [{'label': 'Langue', 'field': 'language'},
                 {'label': 'Mode', 'field': 'mode', 'display': True}],   # get_<f>_display()
       # FORMES GÉNÉRIQUES ajoutées le 2026-10-03 (décision Fabien : « aligner, porter au
       # commun ») — cinq adapters code ne faisaient RIEN d'autre que ceci, chacun à sa main :
       #   • PREMIER CHAMP NON VIDE — une LISTE de noms : `['avatar_upload', 'audio_input']`
       #     (ce que l'adapter écrivait `a or b`) ;
       #   • VALEUR SELON LA PRÉSENCE — `{'when_any': ['text_file', 'text_content'],
       #     'then': 'text', 'else': 'audio'}` : `then` si l'un des champs est renseigné ;
       #   • TEXTE TRONQUÉ dans `extra` — `{'field': 'prompt', 'max_chars': 60}` ;
       #   • LIBELLÉ D'UN RÉGLAGE = celui du SCHÉMA — une entrée d'`extra` SANS `label` prend
       #     le `label` de `params.py` (source unique, `INSPECTOR_DETAIL_FIELDS` principe 2 :
       #     aucun libellé réécrit à la main). Un booléen vrai reste `True` dans la donnée ;
       #     c'est l'inspecteur qui l'affiche « Oui » (`wama-inspector.js`, toutes apps).
       'extra_from_params': 'options' | True,   # labels du SCHÉMA (schema_for_app) ; str =
                                                # champ JSON porteur, True = champs individuels
       'aliases': {'quality_preset': 'output_quality'},

       # FACETTES TEXTE du résultat (2026-09-07, R18). Une app à sortie texte peut en avoir
       # PLUSIEURS pour un même item : le transcriber rend transcription + diarisation +
       # résumé + cohérence. Le schéma canonique ne porte qu'UN `result_text` — c'est ce
       # manque qui a fait écrire deux modales à onglets quasi identiques (describer et
       # transcriber), la duplication tracée au `REMOVAL_LEDGER R18`.
       #
       # ⚠ Ce n'est PAS une seconde mécanique de preview : la preview de CARD reste
       # `PreviewRegistry` (fichier/média), et les autres apps n'ont qu'une facette — ou
       # plusieurs RÉSULTATS dans une seule preview (imager). Les onglets ne concernent que
       # le cas « un résultat, plusieurs LECTURES de ce résultat », et uniquement du TEXTE.
       #
       # Chaque facette : {'cle', 'label', 'icone'} + le rendu du panneau
       #   'cible'  : id de l'élément que le JS de l'app remplit (défaut : `<cle>Content`) ;
       #   'forme'  : 'pre' (texte préformaté) | 'html' (contenu riche) | 'nu' (l'app pose
       #              tout elle-même — cas cohérence, dont le bloc est déjà autonome) ;
       #   'copie'  : bouton « copier » (défaut True pour pre/html) ;
       #   'badge'  : compteur de mots `wc-<cle>` (le JS l'alimente) ;
       #   'cache'  : onglet masqué tant qu'il n'a rien (résumé/cohérence : à la demande) ;
       #   'attente': texte d'attente affiché avant remplissage (diarisation).
       'result_tabs': [{'cle': 'transcription', 'label': 'Transcription',
                        'icone': 'fa-file-alt', 'cible': 'resultText', 'forme': 'pre'}]}

    Étant une donnée, elle est EXTRACTIBLE (facette `inspector` du manifeste) et PROJETABLE
    (gabarit apps_gen) — c'est le déblocage de la marche A3. Une app à logique irréductible
    garde `register_app_detail` (adapter code)."""
    DetailRegistry.register(app_name, model_class,
                            lambda instance: detail_from_spec(instance, spec, app_name),
                            spec=spec)


def spec_value(instance, form):
    """UNE valeur de spec résolue contre l'instance — le vocabulaire entier tient ici :
    nom de champ · `{'const': x}` · `{'field': f, 'map': table}` · LISTE de champs (le premier
    non vide) · `{'when_any': [champs], 'then': x, 'else': y}` (selon la présence)."""
    if not form:
        return None
    if isinstance(form, (list, tuple)):
        for name in form:
            value = getattr(instance, name, None)
            if value:
                return value
        return None
    if isinstance(form, dict):
        if 'when_any' in form:
            present = any(getattr(instance, name, None) for name in (form.get('when_any') or ()))
            return form.get('then') if present else form.get('else')
        # `{'field': 'media_type', 'map': {...}}` (2026-09-18) : la valeur d'un champ TRADUITE
        # par une table — né pour `result_role` (la catégorie d'un média n'est pas un rôle
        # d'asset). Sinon `{'const': …}`.
        if 'map' in form:
            return (form['map'] or {}).get(getattr(instance, form.get('field', ''), None))
        return form.get('const')
    return getattr(instance, form, None)


def detail_from_spec(instance, spec, app_name):
    """Adapter GÉNÉRIQUE : résout la spec déclarative contre l'instance puis délègue à
    `build_detail` (l'épine dorsale reste la source unique du schéma canonique)."""
    def _val(key):
        return spec_value(instance, spec.get(key))

    schema_labels = None        # libellés de `params.py`, lus au premier besoin seulement
    extra = {}
    for entry in (spec.get('extra') or []):
        name = entry.get('field')
        label = entry.get('label')
        if not label:
            if schema_labels is None:
                from .param_schema import schema_for_app
                schema_labels = {p.get('name'): p.get('label')
                                 for p in (schema_for_app(app_name) or [])}
            label = schema_labels.get(name) or name
        if entry.get('display'):
            fn = getattr(instance, f'get_{name}_display', None)
            v = fn() if callable(fn) and getattr(instance, name, None) else None
        else:
            v = getattr(instance, name, None)
        limit = entry.get('max_chars')
        if limit and isinstance(v, str) and len(v) > limit:
            v = v[:limit] + '…'
        extra[label] = v or None
    src_params = spec.get('extra_from_params')
    if src_params:
        from .param_schema import schema_for_app
        carrier = (getattr(instance, src_params, None) or {}) if isinstance(src_params, str) \
            else None
        # Déjà rendus sous leur clé canonique : les alias, et le champ que `engine` /
        # `engine_effective` nomment (sinon « Moteur / Modèle » puis « Modèle TTS », deux fois).
        skip = set(spec.get('aliases') or {})
        skip |= {spec[k] for k in ('engine', 'engine_effective') if isinstance(spec.get(k), str)}
        extra.update(settings_from_schema(instance, schema_for_app(app_name) or [],
                                          skip=skip, carrier=carrier))

    d = build_detail(
        instance,
        source_file=_val('source_file'),
        source_type=_val('source_type'),
        engine=_val('engine'),
        engine_effective=_val('engine_effective'),
        result_file=_val('result_file'),
        result_role=_val('result_role'),
        result_text=_val('result_text') or None,
        source_text=_val('source_text'),
        extra=extra or None,
    )
    for champ, cle in (spec.get('aliases') or {}).items():
        v = getattr(instance, champ, None)
        if v:
            d[cle] = v
    return d


#: Clés que `build_detail` rend LUI-MÊME, sous la section Sortie, depuis l'instance (depuis
#: l'origine, 2026-07-07). Les relister parmi les réglages les montrait deux fois — vu au volet
#: le 2026-10-03 (« Format de sortie original » sous Réglages ET « Format original » sous Sortie),
#: là depuis l'audit du 2026-07-11 qui tirait les réglages de TOUS les params du schéma.
RENDERED_BY_BACKBONE = ('output_format', 'output_quality')


def settings_from_schema(instance, schema, *, skip=(), carrier=None):
    """{libellé: valeur} des réglages POSÉS du schéma — la liste « Réglages » du volet, pour les
    DEUX voies (spec `extra_from_params`, adapters code). Un fait rendu une fois : ni les clés que
    l'épine dorsale rend déjà (`RENDERED_BY_BACKBONE`), ni les noms de `skip` (le champ moteur,
    les alias). `carrier` : dict porteur des valeurs (JSON d'options) ; une valeur absente du
    porteur se lit sur le champ DÉDIÉ du modèle (les paramètres de tête vivent hors du JSON —
    repli du 2026-08-13, converter). `0` compris : une valeur nulle est un réglage non posé.
    Accepte un schéma en dicts (`schema_to_dicts`) comme en `Param`."""
    out = {}
    excluded = set(skip) | set(RENDERED_BY_BACKBONE)
    for p in schema:
        read = p.get if isinstance(p, dict) else (lambda key, _p=p: getattr(_p, key, None))
        name, label = read('name'), read('label')
        if not name or not label or name in excluded:
            continue
        value = carrier.get(name) if carrier is not None else None
        if value in (None, '', False, 0):
            value = getattr(instance, name, None)
        if value not in (None, '', False, 0):
            out[label] = value
    return out


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


#: Catégorie de média → rôle d'asset, pour les apps dont la sortie est « un média de la même
#: catégorie que l'entrée » (anonymizer, enhancer, converter). Deux absences VOULUES : `audio`
#: (voix, musique ou bruitage — le rôle n'est pas dérivable de la catégorie, l'app le dit ou
#: l'utilisateur choisit) et `avatar` (jamais une sortie générique : c'est une nature d'usage).
MEDIA_CATEGORY_ROLE = {'image': 'image', 'video': 'video', 'document': 'document'}


def build_detail(instance, *, source_file=None, source_type=None, engine=None,
                 engine_effective=None, result_file=None, result_files=None,
                 result_role=None, result_text=None, source_text=None, extra=None):
    """Assemble le dict canonique d'un item (épine dorsale). Les valeurs vides sont OMISES
    (la ligne disparaît côté WamaDetails). `extra` = réglages spécifiques d'app {label: valeur}.

    Arguments = valeurs DÉJÀ résolues par l'adapter (il connaît les noms de champs de son modèle) :
      source_file (FieldFile|str), source_type (str), engine, engine_effective, result_file,
      result_text (str — clé canonique AJOUTÉE 2026-07-13 pour les apps à sortie TEXTE :
      transcriber/describer/reader ; consommée par le runner générique du studio),
      result_role (str — clé canonique AJOUTÉE 2026-09-18 : le RÔLE d'asset de la sortie, dans
      le vocabulaire `media_library.natures.ASSET_NATURES` ; consommée par le geste commun
      « ranger en médiathèque », qui ne propose alors que ce rôle. L'app DÉCLARE ce qu'elle
      produit — le composer sait qu'une génération `music` est une musique — au lieu de le
      savoir dans une route à elle ; non déclaré = l'utilisateur choisit).
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

    # Sortie MULTIPLE — clé canonique ajoutée le 2026-08-22. Certaines apps produisent N
    # fichiers d'un seul traitement (imager : N images par génération). `result_file` reste le
    # REPRÉSENTANT et ne bouge pas : c'est lui que lisent le studio, le lien Sortie et la face
    # ?side=output des apps à sortie unique. `result_files` ajoute la COLLECTION à côté — un
    # consommateur qui l'ignore se comporte donc exactement comme avant.
    # Émise à partir de DEUX éléments seulement : en dessous, `result_file` dit déjà tout, et
    # une collection d'un seul élément ferait rendre une grille d'une case.
    urls = [u for u in (_url(f) for f in (result_files or [])) if u]
    if len(urls) > 1:
        d['result_files'] = urls

    # Rôle DÉCLARÉ de la sortie (2026-09-18). Une chaîne nue : la validation contre le
    # vocabulaire des natures appartient au consommateur (`media_library.services`), le
    # substrat ne dépend pas d'une app.
    if result_role and (res or urls):
        d['result_role'] = str(result_role)

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
    if err and d['status'] != 'SUCCESS':
        # Sur un item TERMINÉ, une erreur est un RÉSIDU d'un run précédent (le champ n'est
        # pas toujours purgé au restart) : l'afficher fait passer un succès pour un problème
        # (vécu 13/08 : note de smoke du 03/08 encore affichée sur l'item #49 SUCCESS).
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


def result_tabs_for(app_name: str) -> list:
    """Facettes TEXTE déclarées par `app_name` — [] si l'app n'en déclare pas.

    Lue depuis la SPEC de l'app (`register_app_detail_spec`, ou le `spec=` d'une app à adapter
    code) : les onglets sont une propriété de son DÉTAIL, pas une donnée d'interface posée à
    côté. C'est ce qui les rend extractibles au manifeste (facette `inspector`) et projetables
    par la chaîne de génération, sans rien déclarer deux fois.

    Les défauts sont appliqués ICI et non dans le gabarit : une valeur par défaut dans un
    template se recopie au premier partial qui l'oublie.
    """
    entree = DetailRegistry.get(app_name) or {}
    facettes = ((entree.get('spec') or {}).get('result_tabs')) or []
    sortie = []
    for f in facettes:
        if not isinstance(f, dict) or not f.get('cle'):
            continue
        forme = f.get('forme') or 'html'
        sortie.append({
            'cle': f['cle'],
            'label': f.get('label') or f['cle'].capitalize(),
            'icone': f.get('icone') or 'fa-file-alt',
            'cible': f.get('cible') or f"{f['cle']}Content",
            'forme': forme,
            'copie': f.get('copie', forme in ('pre', 'html')),
            'badge': bool(f.get('badge')),
            'cache': bool(f.get('cache')),
            'attente': f.get('attente') or '',
            'actif': not sortie,          # le PREMIER déclaré est l'onglet actif
        })
    return sortie
