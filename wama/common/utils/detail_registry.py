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
    def surface_of(cls, model_class):
        """La surface qui DÉCLARE ce modèle d'élément (`enhancer`, `audio_enhancer`…), ou None —
        l'accesseur inverse de `get` (2026-10-17, lu par l'écrivain de ZIP `batch_views`)."""
        return next((name for name, entry in sorted(cls._registry.items())
                     if entry.get('model') is model_class), None)

    @classmethod
    def registered_apps(cls):
        """Apps ayant un adapter de détail, triées. Accesseur PUBLIC : `tool_api` en a besoin
        pour nommer les cibles valides d'une erreur, et lire `_registry` de l'extérieur ferait
        d'un attribut privé une API de fait."""
        return sorted(cls._registry)

    @classmethod
    def preview_url(cls, app_name, pk) -> str:
        """L'aperçu commun d'un élément (`common:unified_preview`) — LE crochet de l'inspecteur
        (`data-preview-url`, dont `fillDetail` dérive le détail). Vide pour une source hors du
        registre ou à clé non entière : le Lab a des clés UUID, et `reverse` levait alors au point
        de faire tomber toute la page du journal (2026-09-28). Lu par le journal et le calendrier,
        qui montrent la card d'un élément hors de son app (2026-10-18)."""
        if app_name not in cls._registry or not isinstance(pk, int):
            return ''
        from django.urls import reverse
        return reverse('common:unified_preview', args=[app_name, pk])


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
       #   • PREMIER CHAMP NON VIDE — une LISTE de noms : `['work_image', 'audio_input']`
       #     (ce que l'adapter écrivait `a or b`) ; un nom est un champ OU un PORT de la table
       #     commune des entrées (`port_fields.element_value`, 2026-11-25) ;
       #   • VALEUR SELON LA PRÉSENCE — `{'when_any': ['text_file', 'text_content'],
       #     'then': 'text', 'else': 'audio'}` : `then` si l'un des champs est renseigné ;
       #   • TEXTE TRONQUÉ dans `extra` — `{'field': 'prompt', 'max_chars': 60}` ;
       #   • LIBELLÉ D'UN RÉGLAGE = celui du SCHÉMA — une entrée d'`extra` SANS `label` prend
       #     le `label` de `params.py` (source unique, `INSPECTOR_DETAIL_FIELDS` principe 2 :
       #     aucun libellé réécrit à la main). Un booléen vrai reste `True` dans la donnée ;
       #     c'est l'inspecteur qui l'affiche « Oui » (`wama-inspector.js`, toutes apps).
       # Les réglages POSÉS du schéma sont listés pour TOUTE spec (2026-11-23) : `extra` ne porte
       # que les faits hors schéma. La clé ne dit plus que le PORTEUR de leurs valeurs.
       'extra_from_params': 'options',          # str = champ JSON porteur ; absent ou True =
                                                # champs individuels du modèle
       # FORMES ajoutées le 2026-10-05 — les deux derniers adapters code (imager, audio de
       # l'enhancer) n'écrivaient rien d'autre :
       #   • SCHÉMA CHOISI PAR ÉLÉMENT — `params_schema` : une valeur de spec qui rend le nom
       #     d'un `*PARAMS_JSON` du module de l'app (`{'when_any': ['is_video_generation'],
       #     'then': 'VIDEO_PARAMS_JSON', 'else': 'IMAGE_PARAMS_JSON'}`), pour une surface qui
       #     sert DEUX domaines ; absent = le schéma du domaine que sert la surface
       #     (`app_modes`, `params_schema` du domaine), sinon le principal (`spec_schema`) ;
       #   • COLLECTION de résultats — `result_files` : le champ qui porte la liste ;
       #   • PREMIER ÉLÉMENT D'UNE LISTE — dans la forme « premier champ non vide » ci-dessus,
       #     un champ qui porte une liste rend son premier élément (`['output_video',
       #     'output_images']` : la vidéo, sinon la première image).
       'aliases': {'quality_preset': 'output_quality'},
       # TITRE LU dans le CONTENU (2026-11-08, la partition du Reader : « le titre est écrit en
       # haut d'une des pages ») — une valeur de spec ; il nomme le LOT
       # (`batch_identity`, après le nom donné à la main) et l'élément sur sa card.
       'content_title': 'read_title'}

       # Plus de `result_tabs` (facettes TEXTE d'un résultat, retirées le 2026-10-13,
       # `REMOVAL_LEDGER R127`) : les lectures d'un même résultat — diarisation, résumé,
       # cohérence — sont les PROCESS du pipeline de l'app, et la visionneuse commune les montre
       # en faces (`ProcessSpec.result` / `result_format`, `ROUTE §F3b`).

    Étant une donnée, elle est EXTRACTIBLE (facette `inspector` du manifeste) et PROJETABLE
    (gabarit apps_gen) — c'est le déblocage de la marche A3. Une app à logique irréductible
    garde `register_app_detail` (adapter code)."""
    DetailRegistry.register(app_name, model_class,
                            lambda instance: detail_from_spec(instance, spec, app_name),
                            spec=spec)


def spec_value(instance, form):
    """UNE valeur de spec résolue contre l'instance — le vocabulaire entier tient ici :
    nom de champ · `{'const': x}` · `{'field': f, 'map': table, 'default'?: x}` · LISTE de champs
    (le premier non vide — d'une COLLECTION, son premier élément) · `{'when_any': [champs],
    'then': x, 'else': y}` (selon la présence)."""
    # Un NOM désigne un attribut de l'élément — ou un PORT, lu au lecteur commun quand l'élément n'a
    # pas d'attribut de ce nom (`port_fields.element_value`, 2026-11-25) : une app déclare ses ports
    # là où elle nommait sa colonne (l'avatar de l'avatarizer, passé dans la table des entrées).
    from wama.common.utils.port_fields import element_value
    if not form:
        return None
    if isinstance(form, (list, tuple)):
        for name in form:
            value = element_value(instance, name)
            if value:
                # « Premier élément d'une liste » (2026-10-05) : la vidéo, sinon la PREMIÈRE des
                # images de l'imager — le représentant d'une collection est son premier élément.
                return value[0] if isinstance(value, (list, tuple)) else value
        return None
    if isinstance(form, dict):
        if 'when_any' in form:
            present = any(element_value(instance, name) for name in (form.get('when_any') or ()))
            return form.get('then') if present else form.get('else')
        # `{'field': 'media_type', 'map': {...}}` (2026-09-18) : la valeur d'un champ TRADUITE
        # par une table — né pour `result_role` (la catégorie d'un média n'est pas un rôle
        # d'asset). `default` (2026-11-01) : la valeur d'une clé absente de la table — un domaine
        # qui prend « tout le reste » (l'imager : image, sauf les modes vidéo) se déclare sans
        # recopier chaque mode. Une valeur de CHAMP désigne l'élément, donc la même déclaration
        # sait aussi le chercher en base (`app_modes.domain_filter`). Sinon `{'const': …}`.
        if 'map' in form:
            return (form['map'] or {}).get(getattr(instance, form.get('field', ''), None),
                                           form.get('default'))
        return form.get('const')
    return element_value(instance, form)


def spec_schema(instance, spec, app_name):
    """Le schéma de réglages d'un ÉLÉMENT : celui que la spec choisit pour lui (`params_schema`,
    une valeur de spec qui rend un nom d'attribut `*PARAMS_JSON` — imager : image OU vidéo selon
    l'élément), sinon celui du DOMAINE que sert la surface (`app_modes.params_schema`, l'audio de
    l'enhancer), sinon le schéma principal de l'app.

    Le nom se lit dans le module de l'app Django PROPRIÉTAIRE du modèle (`declared_param_schemas`
    connaît tous ses schémas) — pas dans celui de la surface : `audio_enhancer` est une surface de
    l'app `enhancer`, dont le module déclare `AUDIO_PARAMS_JSON`. 2026-10-21 : la spec de
    `audio_enhancer` ne le recopie plus en constante, son domaine le nomme."""
    from .app_modes import domain_schema_name, surface_domains
    from .param_schema import declared_param_schemas, schema_for_app
    meta = getattr(type(instance), '_meta', None)
    app = getattr(meta, 'app_label', None) or app_name
    name = spec_value(instance, spec.get('params_schema'))
    if not name:
        served = surface_domains(app, app_name)
        name = domain_schema_name(app, served[0]) if len(served) == 1 else ''
    if not name:
        return schema_for_app(app_name) or []
    declared = declared_param_schemas(app) or {}
    return list((declared.get('schemas') or {}).get(name) or [])


def detail_from_spec(instance, spec, app_name):
    """Adapter GÉNÉRIQUE : résout la spec déclarative contre l'instance puis délègue à
    `build_detail` (l'épine dorsale reste la source unique du schéma canonique)."""
    def _val(key):
        return spec_value(instance, spec.get(key))

    schema = spec_schema(instance, spec, app_name)      # le schéma de l'élément
    extra = {}
    for entry in (spec.get('extra') or []):
        name = entry.get('field')
        label = entry.get('label')
        if not label:
            label = next((p.get('label') for p in schema if p.get('name') == name), None) or name
        if entry.get('display'):
            fn = getattr(instance, f'get_{name}_display', None)
            v = fn() if callable(fn) and getattr(instance, name, None) else None
        else:
            v = getattr(instance, name, None)
        limit = entry.get('max_chars')
        if limit and isinstance(v, str) and len(v) > limit:
            v = v[:limit] + '…'
        extra[label] = v or None
    # LES RÉGLAGES DU SCHÉMA, pour TOUTE app (2026-11-23, Fabien : « parfaitement aligné, universel,
    # uniforme et schéma-driven ») : la liste « Réglages » du volet est celle des réglages POSÉS du
    # schéma — la source que lit la card, en entier. Avant, une spec devait le demander
    # (`extra_from_params`) : quatre apps listaient encore leurs réglages à la main (composer,
    # transcriber, describer, reader) et n'en montraient que trois ou quatre. `extra` ne porte plus
    # que les faits HORS schéma (un type, un nombre de pages) ou une mise en forme voulue (un
    # prompt coupé) ; `extra_from_params` ne dit plus que le PORTEUR des valeurs (un champ JSON).
    # Ce que RIEN ne lit sur cette card (`unread_settings` : les réglages des étapes qui n'ont pas
    # lieu) ne s'y lit pas — sur un élément enregistré seulement, ses étapes se jugent en base.
    unread = set()
    if getattr(instance, 'pk', None):
        from wama.common.services.process_pipeline import unread_settings
        unread = set(unread_settings(instance))
    src_params = spec.get('extra_from_params', True)
    if src_params:
        carrier = (getattr(instance, src_params, None) or {}) if isinstance(src_params, str) \
            else None
        # Déjà rendus : les alias et le champ que `engine` / `engine_effective` nomment (sinon
        # « Moteur / Modèle » puis « Modèle TTS », deux fois), et ce qu'`extra` nomme lui-même.
        skip = set(spec.get('aliases') or {})
        skip |= {spec[k] for k in ('engine', 'engine_effective') if isinstance(spec.get(k), str)}
        skip |= {entry.get('field') for entry in (spec.get('extra') or [])}
        extra.update(settings_from_schema(instance, schema, skip=skip | unread, carrier=carrier))

    # LE MODÈLE : ce qui est DEMANDÉ, et ce qui a été EMPLOYÉ (2026-11-23, Fabien : « j'ai toujours
    # auto:text-to-music, ce qui n'est pas le modèle mais la tâche. Il faut peut-être donner les 2
    # infos »). Le demandé se LIT comme sur la card (le libellé de l'option : « Automatique (Texte
    # → musique) », « Coqui XTTS v2 »). L'employé, quand la spec ne nomme aucun champ pour lui,
    # est celui que retiennent les lignes des étapes qui lisent ce réglage (`employed_models`, ce
    # que la bande écrit à côté de chaque étape). Les clés canoniques gardent la VALEUR (une clé de
    # catalogue : le rangement en médiathèque en fait une étiquette) ; les `_label` sont pour l'œil.
    # Un modèle qu'aucune étape ne lit sur cette card (un cover dont on ne tire que les partitions)
    # ne s'y dit pas : il n'a servi à rien.
    from wama.common.utils.card_chips import catalog_name, display_value
    engine, effective = _val('engine'), _val('engine_effective')
    engine_field = spec.get('engine') if isinstance(spec.get('engine'), str) else None
    if engine_field in unread:
        engine = effective = engine_field = None
    declared = next((p for p in schema if p.get('name') == engine_field), None) if engine_field else None
    labels = {}
    if engine and declared:
        labels['engine_label'] = display_value(declared, engine, instance)
    if engine_field and not spec.get('engine_effective'):
        from wama.common.services.process_pipeline import employed_models
        employed = employed_models(instance, engine_field)
        if employed:
            effective = employed[-1]            # celui de la dernière étape : il a fait la sortie
            labels['engine_effective_label'] = ', '.join(catalog_name(k) or k for k in employed)
    elif effective and declared:
        labels['engine_effective_label'] = display_value(declared, effective, instance)

    # COLLECTION de résultats (2026-10-05) : le champ qui porte la liste (imager : les N images
    # d'une génération, `output_images`). `result_file` reste le représentant ; `build_detail`
    # n'émet la collection qu'à partir de deux éléments. Une valeur qui n'est pas une liste n'est
    # pas une collection — une chaîne serait lue caractère par caractère.
    files = spec_value(instance, spec.get('result_files'))
    files = list(files) if isinstance(files, (list, tuple)) else None

    d = build_detail(
        instance,
        source_file=_val('source_file'),
        source_type=_val('source_type'),
        engine=engine,
        engine_effective=effective,
        result_file=_val('result_file'),
        result_files=files,
        result_role=_val('result_role'),
        result_text=_val('result_text') or None,
        source_text=_val('source_text'),
        extra=extra or None,
    )
    for champ, cle in (spec.get('aliases') or {}).items():
        v = getattr(instance, champ, None)
        if v:
            d[cle] = v
    # Un libellé n'accompagne que la clé qu'il lit, et seulement s'il dit autre chose qu'elle.
    for key, label in labels.items():
        value = d.get(key[:-len('_label')])
        if value and label and str(label) != str(value):
            d[key] = str(label)
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
    Accepte un schéma en dicts (`schema_to_dicts`) comme en `Param`.

    La valeur est MONTRÉE comme sur la card (`card_chips.display_value`, 2026-11-19, décision de
    Fabien : « un alignement parfait » des chips de la card et de la section INFOS) — le libellé de
    l'option choisie, une durée en horloge, un nombre avec son unité ; une case cochée reste `True`
    (le volet écrit « Oui » en regard de son libellé)."""
    from wama.common.utils.card_chips import display_value
    from wama.common.utils.param_schema import _show_if_met

    def read(name):
        value = carrier.get(name) if carrier is not None else None
        if value in (None, '', False, 0):
            value = getattr(instance, name, None)
        return value

    class _Values:
        """Les valeurs de l'élément, lues à la demande — ce que `show_if` interroge."""
        @staticmethod
        def get(name, default=None):
            value = read(name)
            return default if value is None else value

    out = {}
    excluded = set(skip) | set(RENDERED_BY_BACKBONE)
    names = {(p if isinstance(p, dict) else p.to_dict()).get('name') for p in schema}
    for p in schema:
        field = p if isinstance(p, dict) else p.to_dict()
        name, label = field.get('name'), field.get('label')
        if not name or not label or name in excluded:
            continue
        # Un réglage que sa CONDITION masque dans la ⚙ ne se lit pas ici non plus (2026-11-23 : le
        # curseur « Rapide ↔ Qualité » d'un modèle désigné s'affichait, mesuré sur six apps). Une
        # condition sur un champ que ce schéma ne porte pas ne masque rien — la règle de la ⚙.
        cond = field.get('show_if')
        if cond and _condition_fields(cond) <= names and not _show_if_met(cond, _Values):
            continue
        value = read(name)
        if isinstance(value, (list, tuple)):
            # Une valeur composée VIDE est un réglage non posé (« Ce qu'on floute : [] », « Mots-clés
            # contextuels : [''] », mesurés).
            value = [v for v in value if v not in (None, '')]
        if value in (None, '', False, 0) or (isinstance(value, (list, dict)) and not value):
            continue
        if value is True:
            out[label] = True
            continue
        shown = display_value(field, value, instance)
        # Un modèle laissé à « Automatique » dit aussi celui qui a été EMPLOYÉ, dès qu'une étape
        # l'a retenu (`requested_and_employed`) — la forme du modèle principal, pour tout
        # sélecteur de modèle (partitions, paroles, séparation).
        if field.get('options_source') == 'catalog' and getattr(instance, 'pk', None):
            from wama.common.services.process_pipeline import employed_models
            from wama.common.utils.auto_model import is_auto
            if is_auto(value):
                shown = requested_and_employed(shown, employed_models(instance, name))
        # Un TEXTE long se coupe (une consigne, des paroles) : le volet résume, l'aperçu montre.
        if (field.get('type') in ('text', 'textarea') and isinstance(shown, str)
                and len(shown) > LONG_TEXT):
            shown = shown[:LONG_TEXT] + '…'
        out[label] = shown
    return out


def requested_and_employed(requested, model_keys) -> str:
    """« demandé → employé » : le choix tel qu'il se lit, puis les modèles retenus par leur nom du
    catalogue (« Automatique → MuScriptor Large »). Le demandé seul quand rien n'a encore tourné."""
    from wama.common.utils.card_chips import catalog_name
    names = ', '.join(catalog_name(key) or key for key in model_keys or ())
    return f"{requested} {EMPLOYED_ARROW} {names}" if names else requested


#: Ce qui sépare le demandé de l'employé — la même flèche que le volet pose entre « Moteur /
#: Modèle » et le modèle employé (`wama-inspector.js`, garde `tests_detail_spec`).
EMPLOYED_ARROW = '→'


#: Longueur à laquelle un texte de réglage se coupe dans le volet (celle que les specs écrivaient
#: à la main pour le prompt, `max_chars: 60`).
LONG_TEXT = 60


def _condition_fields(cond) -> set:
    """Les champs qu'une condition `show_if` interroge (vocabulaire de `param_schema._show_if_met`)."""
    if isinstance(cond, str):
        return {cond}
    if not isinstance(cond, dict):
        return set()
    out = set()
    for key in ('any', 'all'):
        for one in cond.get(key) or ():
            out |= _condition_fields(one)
    if 'not' in cond:
        out |= _condition_fields(cond['not'])
    if cond.get('field'):
        out.add(cond['field'])
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
    if 'output_quality' in d:
        # La qualité ne se DIT que si elle agit (2026-10-28, la règle des surfaces de réglage,
        # `output_formats.quality_applies`) : sous « Original », l'inspecteur affichait une
        # qualité qui n'avait rien changé au fichier.
        from wama.common.utils.output_formats import quality_applies
        if not quality_applies(instance):
            del d['output_quality']

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

    # La règle de l'aperçu, son jumeau (`scoping.can_view`) : le propriétaire, le staff, ou qui
    # peut le LISTER — une card reçue a son détail au volet. Elle refusait tout non-propriétaire
    # (2026-10-20) et laissait passer une requête sans compte ; le visiteur est celui de l'aperçu.
    from .preview_utils import get_or_create_anonymous_user
    from .scoping import can_view
    viewer = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    if not can_view(instance, viewer):
        return HttpResponseForbidden("Accès refusé.")

    try:
        return JsonResponse(entry['adapter'](instance))
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
