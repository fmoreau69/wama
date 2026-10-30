"""
Schéma de paramètres WAMA — source unique pour rendre les réglages d'une app dans
TOUTES les surfaces (modale item/batch, volet inspecteur card/batch/file) depuis une
seule description, au lieu de markup dupliqué par template (cause des divergences).

Principe (cf. ROADMAP §2) : la **structure** des champs est DÉRIVÉE du modèle Django
(type, choices, default, help_text, verbose_name) — pas de hardcode — et une surcouche
UI minimale (`overrides`) ajoute ce que le modèle ne connaît pas : contextes d'affichage,
source d'options dynamiques (ex. endpoint backends), visibilité conditionnelle, basique/avancé.

Le rendu (JS/Django) consommera `Param.to_dict()` ; ce module reste pur (aucun rendu ici).
"""

from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional, Tuple

# Feuille sans import Django : les noms des réglages de tirage, tels que la fiche d'un modèle les dit.
from wama.common.utils.model_capabilities import SEED, TEMPERATURE, TOP_P

# Contextes de rendu d'un paramètre :
#   item   = modale « Paramètres » d'un élément
#   batch  = modale « Paramètres » d'un batch
#   panel  = volet droit (inspecteur card/batch/file)
ALL_CONTEXTS = ("item", "batch", "panel")


@dataclass
class Param:
    """Description d'UN paramètre, indépendante de la surface de rendu."""
    name: str
    type: str                                   # toggle|select|radio|text|textarea|number|range|intent|datetime
                                                # |date|mapping
                                                # (`datetime` = date et heure locales, 2026-09-28 :
                                                #  programmation d'une card)
                                                # (`date` = une date seule, `AAAA-MM-JJ` — vide l'EFFACE ;
                                                #  `mapping` = {clé: texte}, rendu par la brique qui
                                                #  connaît ses clés — 2026-10-21, titre, date et noms
                                                #  d'intervenants du transcriber, ROUTE §F3b)
                                                # (`intent` = le curseur rapide/qualité commun,
                                                #  `auto_model.intent_param` ; borné par coerce_params)
                                                # (`temperature` = la température d'échantillonnage
                                                #  commune, `temperature_param` ; vide/None = celle
                                                #  du MODÈLE — 2026-10-21)
    label: str = ""
    icon: str = ""                              # classe FontAwesome optionnelle (ex. "fa-microchip")
    dom_id: Any = ""                            # pont de migration : ID DOM legacy (sinon wp-{ctx}-{name}).
                                                # str = toutes surfaces ; dict {ctx: id} = scopé par contexte
                                                # (ex. {"panel": "backendSelect", "item": "settingsBackend"}).
    radio_name: Any = ""                        # nom du groupe radio (str ou dict par contexte, comme dom_id)
    inline: bool = False                        # radios sur une seule ligne (form-check-inline)
    help: str = ""
    help_html: str = ""                         # aide en HTML brut (ex. lien « En savoir plus ») — prime sur help
    default: Any = None
    choices: Optional[List[Tuple[str, str]]] = None   # [(value, label)]
    option_groups: Optional[List[Tuple[str, List[Tuple[str, str]]]]] = None
                                                # select GROUPÉ (optgroup) : [(libellé_groupe, [(value, label)])]
                                                # ex. voix : [("Voix par défaut", [...]), ("Mes voix", [...])]
    min: Optional[float] = None
    max: Optional[float] = None
    step: Any = None                            # pas de la grille (nombre) ; "any" = décimal LIBRE,
                                                # sans grille (un `float` de fonction, 2026-10-12 —
                                                # sans lui, un champ nombre n'accepte que des entiers
                                                # et sa flèche avance de 1 sur une borne de 0 à 1).
                                                # Absent = le comportement du navigateur (pas de 1).
    unit: str = ""                              # unité AFFICHÉE avec la valeur : suffixe d'un range,
                                                # d'un champ nombre (ex. "s", "m")
    min_label: str = ""                         # libellés FORMATÉS des bornes du range (ex. "10s"/"10min")
    max_label: str = ""                         #   — priment sur min/max bruts à l'affichage (P2-bis)
    contexts: Tuple[str, ...] = ALL_CONTEXTS
    remember: Optional[bool] = None             # Le réglage se RETIENT-il d'un dépôt au suivant
                                                # (préférence de l'utilisateur, brique `user_settings`) ?
                                                # None = oui s'il est au VOLET (contexte `panel`) — le cas
                                                # de presque tous ; True = retenu hors du volet (la voix
                                                # de l'avatarizer, réglée dans la modale) ; False = jamais
                                                # (son modèle d'animation : il ne convient qu'à une nature
                                                # d'avatar). 2026-10-21 : déclaré ici, la règle vivait en
                                                # code dans les `params.py` (`remembered`).
    options_source: Optional[str] = None        # clé d'options dynamiques (ex. "backends")
    # ⚠ `options_domain` (porte + annonce aux assistants d'un select de catalogue) RETIRÉ le
    # 2026-10-07 (REMOVAL_LEDGER) : un seul utilisateur (le transcriber), une seule règle pour
    # toutes les apps (décision de Fabien) — un select de catalogue n'annonce rien à l'outil
    # et sa porte ne refuse rien (plus de `choices` préfixes) ; l'assistant découvre les modèles
    # par `list_ai_models`, le `save()` du modèle normalise, le lancement refuse ce que rien ne sert.
    options_query: Optional[dict] = None        # DOMAINE d'une source d'options qui en demande un :
                                                # {"task": "text-to-speech"} → querystring de l'endpoint.
                                                # Requis par `options_source="catalog"` : une clé ne porte
                                                # qu'une URL fixe, elle ne saurait pas DE QUOI parler.
                                                # ⚠ Ce champ MANQUAIT (ajouté 2026-09-01) : le socle F4b du
                                                # 31/08 a livré le LECTEUR (`_optionQuery`, wama-params.js)
                                                # et l'endpoint qui le sert, mais aucun schéma ne pouvait
                                                # l'émettre — `to_dict()` ne l'aurait jamais porté. Une
                                                # jambe livrée aux deux bouts et absente au milieu.
                                                # ⚠⚠ N'y mettre QUE ce qui borne le domaine (task /
                                                # model_type / modality / source). Jamais les entrées
                                                # fournies ni les capacités requises : celles-là GRISENT
                                                # côté client sur la liste complète (INPUT_MODEL_MATCHING
                                                # §2). Restreindre ici ferait une EXCLUSION serveur d'un
                                                # grisage expliqué — l'utilisateur perdrait « ce modèle
                                                # existe mais votre entrée l'écarte ».
    options_mode: Optional[dict] = None         # select `catalog` BORNÉ PAR LE MODE de l'élément
                                                # (2026-09-27) : {"app", "domain", "field"} — `field`
                                                # = le `mode_param` du domaine (`app_modes`). Le
                                                # navigateur ajoute `app/domain/mode=<valeur du champ>`
                                                # à la requête et la relance quand le mode change ; le
                                                # serveur en DÉRIVE ce que le mode impose au modèle
                                                # (`app_modes.mode_model_filter`). À part de
                                                # `options_query` À DESSEIN : les lecteurs serveur
                                                # passent celui-ci tel quel au catalogue. Déclarer par
                                                # `app_modes.options_mode_for(app, domain)`, jamais à la
                                                # main (le nom du champ vit dans `app_modes`).
    options_group: str = ""                     # select `catalog` : GROUPER les options ("task" = un
                                                # groupe par tâche, libellé du catalogue ;
                                                # "category" = un groupe par capacité `category`,
                                                # libellé `CATEGORY_LABELS`, les sans-catégorie
                                                # hors groupe — 2026-09-29). Drapeau d'UI, comme
                                                # `options_auto`.
    options_auto: bool | str = False            # select `catalog` : servir « auto » en 1ʳᵉ option
                                                # (+ PRÉVISION du modèle retenu sous le select).
                                                # "group" (2026-10-01) : un « auto:<tâche> » en tête
                                                # de CHAQUE groupe de tâche (`options_group="task"`).
                                                # "silent" (2026-10-03) : « auto » SANS prévision —
                                                # quand le tirage dépend des entrées de chaque
                                                # élément (avatarizer : la nature de l'avatar), la
                                                # prévision annoncerait un autre modèle que celui
                                                # du lancement. Elle dit vrai ou elle se tait.
                                                # OPT-IN par app : ne le déclarer QUE si le chemin de
                                                # lancement résout « auto » (brique commune
                                                # `common/utils/auto_model.py`) — sinon la valeur
                                                # stockée arriverait brute au dispatch.
    options_abilities: bool = False             # select `catalog` : afficher les capacités
                                                # DÉCLARÉES derrière le nom (« Vision, Outils ») —
                                                # ce que les rôles de l'assistant disaient en
                                                # épinglant des noms de modèles. Dérivé du
                                                # catalogue (`model_selector.abilities_of`).
    options_cloud: bool = False                 # select `catalog` : proposer AUSSI les modèles
                                                # DISTANTS que les clés d'API de l'utilisateur
                                                # ouvrent (`cloud=1` de l'endpoint). OPT-IN, comme
                                                # `options_auto` : une app dont le backend est
                                                # LOCAL ne doit pas proposer un modèle distant
                                                # qu'elle ne saurait pas exécuter.
    options_resolution: Optional[dict] = None   # select `catalog` à `options_auto` : affinages du
                                                # TIRAGE « auto » — {"priority": [sous-chaînes de
                                                # clé], "available_inputs": [entrées que l'élément
                                                # FOURNIT], "needs": {capacité: champ de
                                                # l'élément} — 2026-10-14, enhancer `scale` ←
                                                # `upscale_factor`, "voice": champ de voix —
                                                # 2026-10-28, la voix choisie borne le tirage aux
                                                # modèles qui la disent}. Lus par le LANCEMENT
                                                # (`auto_model.resolve_model_choice`) ET par la
                                                # PRÉVISION (le navigateur les transmet à l'endpoint) :
                                                # un seul lieu. Jusqu'au 2026-10-01 le transcriber les
                                                # passait au lancement seul — la prévision annonçait
                                                # Qwen3-ASR quand le lancement tirait Whisper. Hors
                                                # d'`options_query` À DESSEIN : ils affinent le
                                                # TIRAGE, jamais la liste (lister n'est pas choisir).
    options_ports: bool = False                 # select `catalog` : les modèles qu'il PROPOSE sont
                                                # ceux de l'app — leurs entrées ouvrent les PORTS de
                                                # la card (`app_registry.app_input_ports`), en plus
                                                # de ceux de sa source (2026-10-01). Sans lui, un
                                                # modèle venu d'une autre source (YuE2 au composer)
                                                # entre au select mais pas à la card. OPT-IN : le
                                                # select de voix de l'avatarizer propose des modèles
                                                # d'une ÉTAPE, pas ceux de l'app.
    show_if: Any = None                        # visibilité conditionnelle. string = nom d'un champ
                                                # (visible si « truthy » : toggle coché / valeur non vide).
                                                # dict = condition par VALEUR : {"field": "media_type",
                                                # "in": ["video","image"]} ou {"field": "use_sam3",
                                                # "equals": True} ou {"field": "engine", "not_equals":
                                                # "auto"} (2026-10-13) ou {"any": [cond, cond…]}, vraie
                                                # si L'UNE des conditions l'est (2026-10-28 : la qualité
                                                # de sortie, sous un format choisi OU la résolution
                                                # d'origine gardée). Réévalué au change de n'importe quel champ.
    advanced: bool = False                      # repliable sous « Avancé »
    help_source: Optional[str] = None           # select de MODÈLE : source catalogue (model_manager)
                                                 # → WamaParams affiche desc courte/longue + VRAM sous le select
    help_fallback: Optional[dict] = None         # {valeur_option: texte} pour backends HORS catalogue
                                                 # (ex. moteurs ASR/OCR maison) — repli si help_source absent/vide
    chip: bool = False                          # CARD_DESIGN §10.3 : le champ produit un CHIP méta sur la
                                                # card (état concis) — valeur courte (label d'option si
                                                # select), icône du schéma. Rendu : common/utils/card_chips.py.
    chip_label: str = ""                        # Libellé COURT du chip, quand le label du réglage est trop
                                                # long pour une card ("Diarisation" pour « Identifier les
                                                # locuteurs »). Vide = on reprend `label`. Le label complet
                                                # reste dans le title, donc rien n'est perdu.
    section: str = "settings"                   # CARD_DESIGN §11 : SECTION de la card v3 où le chip atterrit
                                                # ("settings" par défaut, "output" pour un champ qui décrit ce
                                                # qui va SORTIR — ex. format de sortie). Déclaré à la source :
                                                # ni la vue ni le template ne trient les chips.
    group: str = ""                             # Groupement UI des SURFACES de saisie (modale/volet) : clé
                                                # d'un ParamGroup déclaré par l'app. DISTINCT de `section`
                                                # (chips de card). Vide + advanced=True → groupe implicite
                                                # « Avancé » replié (WamaParams.render), sur TOUTE surface
                                                # depuis le 2026-10-22 (groupes déclarés ou non).
    pills: list = field(default_factory=list)   # Toggle rendu en sélecteur segmenté (2 pills radio) :
                                                # [libellé_off, libellé_on] — ex. ["YOLO", "SAM3"]. La valeur
                                                # lue/envoyée reste 'true'/'false' (contrat serveur inchangé).
    cap_from: Any = None                        # Curseur BORNÉ PAR LA CAPACITÉ DU MODÈLE choisi (2026-09-23,
                                                # un dict, ou une LISTE de dicts quand le réglage lit
                                                # plusieurs capacités — la température : la lit-il, sa
                                                # valeur recommandée, son maximum ; 2026-10-21,
                                                # `cap_bindings`),
                                                # Fabien : « les paramètres tirent leurs infos des capacités
                                                # des modèles dans le registre »). {"field": "<param modèle>",
                                                # "capability": "<clé de capabilities>", "extension":
                                                # "<clé qui autorise l'au-delà>", "unit": "s"}. Rendu :
                                                # zone NATIVE (bleue) jusqu'à la capacité ; au-delà, zone
                                                # EXTRAPOLÉE (rouge) si le modèle déclare l'extension, sinon
                                                # le curseur est BORNÉ à la capacité. Modèle « auto » ou sans
                                                # capacité → curseur du schéma, inchangé. Serveur : la tâche
                                                # lit les MÊMES capacités (ex. `video_caps_from_declaration`).
                                                # "mode": "reads" (2026-10-13) — le réglage est GRISÉ,
                                                # raison dite, quand le modèle ne le LIT pas : capacité
                                                # liste (`params`, appartenance du nom) ou booléenne
                                                # (`supports_*`) ; inconnue ou « auto » → intact.
                                                # "mode": "voices" (2026-10-28, `voices_of`) — un select
                                                # de voix ne garde que celles du modèle choisi.
    display_format: str = ""                    # FORMAT d'affichage de la valeur (2026-10-04) : "duration"
                                                # (secondes → « 3:30 ») | "size" (octets → « 3,8 Go »).
                                                # Remplace le suffixe nu `unit` partout où la valeur se LIT :
                                                # libellé du curseur, bornes, chip de card. Formateurs
                                                # COMMUNS (`WamaApp.formatDuration`/`formatSize`, Python
                                                # `DISPLAY_FORMATS`) — jamais une copie par app.
    default_from: Optional[dict] = None         # Valeur PROPOSÉE d'après une ENTRÉE de la card (2026-10-04,
                                                # Fabien : la durée du composer reprend celle de la chanson
                                                # à reprendre) : {"port": "<id du port>", "property":
                                                # "duration"}. Au dépôt (ou à la désignation) d'un fichier sur
                                                # ce port, la propriété est lue — chez le client pour un
                                                # fichier téléversé, par `common:api_media_probe` pour un
                                                # fichier désigné — et posée dans le champ, BORNÉE par son
                                                # max (y compris celui de `cap_from`). Une valeur que
                                                # l'utilisateur change ensuite reste la sienne.
    stales: Optional[Tuple[str, ...]] = None    # Process du pipeline de l'app que ce réglage PÉRIME quand il
                                                # change (2026-10-05, forme demandée par la session pipeline) :
                                                # `('plan', 'render')`. `ProcessSpec.watched` en est DÉRIVÉ
                                                # (`AppPipeline.watched_of`) — le réglage le dit une fois, au
                                                # lieu d'être recopié dans la liste de chaque process.
                                                # `()` = DÉCLARÉ sans péremption (réglage d'AFFICHAGE : les
                                                # `show_*` de l'anonymizer). `None` = non déclaré : la garde
                                                # `tests_process_watched` le refuse, sauf interrupteur d'un
                                                # process (`toggle`) ou réglage de sortie (`output_spec`).

    def to_dict(self) -> dict:
        return asdict(self)


def _format_size(value) -> str:
    """Octets → « 3,8 Go » — jumeau Python de `WamaApp.formatSize` (base 1024, unités FR)."""
    units, v, i = ('o', 'Ko', 'Mo', 'Go', 'To'), abs(float(value)), 0
    while v >= 1024 and i < len(units) - 1:
        v, i = v / 1024, i + 1
    text = f"{v:.0f}" if (v >= 100 or i == 0) else f"{v:.1f}".replace('.', ',')
    if text.endswith(',0'):
        text = text[:-2]
    return f"{'-' if float(value) < 0 else ''}{text} {units[i]}"


def format_display(value, display_format: str) -> Optional[str]:
    """La valeur dans le FORMAT déclaré (`Param.display_format`), None si le format est inconnu
    ou la valeur illisible — l'appelant garde alors son affichage d'avant."""
    try:
        if display_format == 'duration':
            from wama.common.utils.media_probe import format_duration
            return format_duration(float(value)) or None
        if display_format == 'size':
            return _format_size(value)
    except (TypeError, ValueError):
        return None
    return None


# ── Dérivation depuis un modèle Django ───────────────────────────────────────
def _django_field_to_param(f) -> Param:
    """Mappe un champ de modèle Django vers un Param (structure uniquement)."""
    internal = f.get_internal_type()
    choices = list(f.choices) if getattr(f, 'choices', None) else None

    if choices:
        ptype = "select"
    elif internal == "BooleanField":
        ptype = "toggle"
    elif internal in ("IntegerField", "FloatField", "PositiveIntegerField", "DecimalField"):
        ptype = "number"
    elif internal == "TextField":
        ptype = "textarea"
    elif internal == "DateField":
        ptype = "date"
    else:
        ptype = "text"

    # default : NOT_PROVIDED → None
    default = f.default
    try:
        from django.db.models.fields import NOT_PROVIDED
        if default is NOT_PROVIDED:
            default = None
    except Exception:
        pass
    if callable(default):
        default = None

    label = str(getattr(f, 'verbose_name', '') or f.name).strip()
    return Param(
        name=f.name,
        type=ptype,
        label=label[:1].upper() + label[1:] if label else f.name,
        help=str(getattr(f, 'help_text', '') or ''),
        default=default,
        choices=choices,
    )


def derive_from_model(model_class, include: List[str], overrides: dict = None) -> List[Param]:
    """
    Construit la liste de `Param` d'une app à partir des champs d'un modèle Django.

    Args:
        model_class : le modèle (ex. Transcript).
        include     : noms de champs à exposer, DANS L'ORDRE d'affichage.
        overrides   : { champ : {attr: valeur, …} } — surcouche UI (type, label, help,
                      contexts, options_source, show_if, advanced, min/max/step…).

    Returns:
        [Param] prêtes pour le rendu (cf. to_dict()).

    Lève `ValueError` pour une surcharge dont le champ n'est pas exposé (2026-10-22) : elle ne
    rendait rien, en silence — « Transcrire l'audio préparé » avait sa surcharge et son process,
    mais ni modale ni route ne le montraient ni ne l'écrivaient, faute d'être dans `include`.
    """
    overrides = overrides or {}
    orphans = sorted(set(overrides) - set(include))
    if orphans:
        raise ValueError(f"{model_class.__name__} : surcharge sans champ exposé "
                         f"({', '.join(orphans)}) — l'ajouter à `include`, ou la retirer")
    meta = model_class._meta
    params: List[Param] = []
    for name in include:
        ov = dict(overrides.get(name, {}))
        try:
            p = _django_field_to_param(meta.get_field(name))
        except Exception:
            # Champ hors modèle (paramètre transitoire UI) : tout vient de l'override.
            p = Param(name=name, type=ov.pop('type', 'text'))
        for k, v in ov.items():
            setattr(p, k, v)
        params.append(p)
    return params


@dataclass
class ParamGroup:
    """Groupe d'affichage d'une surface de saisie (modale ⚙ / volet) — l'app le déclare,
    WamaParams.render l'affiche (titre + éventuel show_if de groupe, même grammaire que
    Param.show_if). Le groupe « avancé » implicite (Param.advanced sans group) n'a PAS à
    être déclaré ici."""
    key: str                                    # référencé par Param.group
    title: str
    icon: str = ""                              # classe Font Awesome (ex. "fa-eye-slash")
    show_if: object = None                      # visibilité du groupe ENTIER
    collapsed: bool = False                     # rendu replié (details fermé)
    columns: int = 1                            # 2 = corps en 2 colonnes (sliders côte à côte)

    def to_dict(self) -> dict:
        return asdict(self)


def groups_to_dicts(groups: List[ParamGroup]) -> List[dict]:
    """Sérialise les groupes pour le front (JSON) / un template."""
    return [g.to_dict() for g in groups]


def schema_to_dicts(params: List[Param]) -> List[dict]:
    """Sérialise un schéma pour le front (JSON) / un template."""
    return [p.to_dict() for p in params]


def cap_bindings(p) -> List[dict]:
    """Les liaisons `cap_from` d'un réglage, toujours en LISTE (un dict seul, la forme d'avant
    le 2026-10-21, en est une à un élément). Jumeau serveur de `wama-params.js::_capBindings`."""
    cf = _pget(p, 'cap_from')
    if not cf:
        return []
    return [b for b in (cf if isinstance(cf, (list, tuple)) else [cf]) if b]


# ── La TEMPÉRATURE d'échantillonnage — un réglage COMMUN à tout modèle qui tire (2026-10-21) ──
# Demande de Fabien : « le modèle doit porter l'information et le réglage doit apparaître si le
# modèle le permet ». Le modèle la porte au catalogue (`model_capabilities` : `params` contient
# `temperature`, `recommended_temperature`, `max_temperature`) ; ce réglage se pose À CÔTÉ de
# n'importe quel choix de modèle (`model_field`) et en lit les trois par `cap_from` : grisé, raison
# dite, sous un modèle qui ne tire pas ; la valeur de l'éditeur à côté du curseur ; borné au maximum
# du moteur. Vide = « celle du modèle » : rien n'est envoyé, le moteur applique la sienne. Il n'entre
# PAS dans le curseur rapide/qualité (Fabien, même jour) : celui-là choisit le modèle, celle-ci règle
# sa façon de tirer.

TEMPERATURE_MAX = 2.0


def temperature_param(model_field: str, **overrides) -> dict:
    """Surcouche STANDARD du réglage de température, liée au choix de modèle `model_field` du
    même schéma — l'app déclare la colonne (`FloatField(null=True, blank=True)`) et passe
    `temperature_param('<champ modèle>', dom_id=…, stales=…)` en override."""
    base = dict(
        type='temperature', label='Température', icon='fa-temperature-half',
        default=None, min=0, max=TEMPERATURE_MAX, step=0.05,
        # Un réglage AVANCÉ (Fabien, 2026-10-22 : « c'est là si l'utilisateur veut aller plus loin,
        # mais s'il n'y touche pas, ça ne change rien ») : rangé dans le groupe « Avancé » replié.
        advanced=True,
        # La REPRODUCTIBILITÉ dépend de la valeur (Fabien, 2026-10-21) : à 0, le choix le plus
        # probable ; au-dessus, un tirage — « celle du modèle » est souvent au-dessus. La ligne
        # sous le curseur le dit pour la valeur du moment (`wama-params.js::_temperatureHint`).
        help="Le hasard du modèle. À 0, même entrée, même résultat ; plus haut, le résultat "
             "varie d'un lancement à l'autre. Un modèle distant ne garantit pas toujours le même "
             "résultat, même à 0.",
        # La valeur de l'éditeur (`recommended_temperature`) n'a plus de ligne de note : le curseur
        # l'affiche à côté de « Celle du modèle » (compacté le 2026-10-22), lue sur la fiche que
        # chaque liaison laisse au champ (`wamaModelCaps`).
        cap_from=[
            {'field': model_field, 'capability': 'params', 'mode': 'reads', 'param': TEMPERATURE,
             'reason': "Ce modèle ne reçoit pas de réglage de température."},
            {'field': model_field, 'capability': 'max_temperature'},
            {'field': model_field, 'capability': 'min_temperature', 'mode': 'min'},
        ],
    )
    base.update(overrides)
    return base


# ── La GRAINE et le TOP P — les deux voisins de la température (2026-10-22) ─────────────────────
# Fabien : « certains modèles comme dans l'Imager portent déjà seed ou graine. Vérifie bien ce qui
# existe déjà pour ne pas faire de doublon. On aligne tout parfaitement. » La graine vivait dans le
# seul imager (`seed`, type `number`, « vide = aléatoire » tenu par une exception de sa vue) ; le top_p
# nulle part, écrit en dur dans deux moteurs (Audio8, Higgs : 0,95). Mêmes règles que la température :
# le modèle dit s'il les lit (`params` ∋ `seed` / `top_p`), le réglage se grise sinon ; vide = un
# choix (`EMPTY_IS_NONE_TYPES`) ; réglages AVANCÉS. `nullable` n'est pas un champ de `Param` : un
# champ de plus réécrirait le schéma sérialisé de toutes les apps — ce sont deux TYPES.

#: Une graine tient dans une colonne `IntegerField` (PostgreSQL : entier signé de 32 bits).
SEED_MAX = 2 ** 31 - 1


def seed_param(model_field: str, **overrides) -> dict:
    """Surcouche STANDARD de la graine, liée au choix de modèle `model_field` : colonne
    `IntegerField(null=True, blank=True)`. Vide = un tirage neuf à chaque lancement."""
    base = dict(
        type='seed', label='Graine', icon='fa-dice', default=None, min=0, max=SEED_MAX, step=1,
        advanced=True,
        help="Vide : un tirage neuf à chaque lancement. Une graine fixée, avec les mêmes réglages "
             "et le même modèle, redonne le même résultat sur cette machine.",
        cap_from=[{'field': model_field, 'capability': 'params', 'mode': 'reads', 'param': SEED,
                   'reason': "Ce modèle ne reçoit pas de graine."}],
    )
    base.update(overrides)
    return base


def top_p_param(model_field: str, **overrides) -> dict:
    """Surcouche STANDARD du top_p, liée au choix de modèle `model_field` : colonne
    `FloatField(null=True, blank=True)`. Vide = celui du modèle, rien n'est envoyé."""
    base = dict(
        type='top_p', label='Top P', icon='fa-filter', default=None, min=0, max=1, step=0.05,
        advanced=True,
        help="Le modèle ne tire que parmi ses choix les plus probables, jusqu'à cette part du "
             "total : plus bas, un résultat plus sûr et moins varié ; 1, tous les choix.",
        cap_from=[{'field': model_field, 'capability': 'params', 'mode': 'reads', 'param': TOP_P,
                   'reason': "Ce modèle ne reçoit pas de top_p."}],
    )
    base.update(overrides)
    return base


def voices_of(model_field: str) -> dict:
    """La liaison `cap_from` d'un select de VOIX (`options_source='voices'`) au choix de modèle
    `model_field` (2026-10-28) : il ne garde que les voix que ce modèle peut dire — pas de voix
    clonée sous un moteur qui ne clone pas, la voix propre d'un moteur sous ceux qui la nomment
    (Phonon, Kokoro, Bark) — par la règle commune `WamaModelCaps.cloneVoiceFilter`. Sous « auto »,
    toutes restent : le tirage reçoit la voix choisie (`options_resolution.voice`). Toutes les
    surfaces où les deux champs sont rendus : volet, modale d'élément, modale de lot."""
    return {'field': model_field, 'capability': 'voices', 'mode': 'voices'}


#: Les réglages de TIRAGE d'un modèle — leur nom au schéma, sans préfixe, dans `options` et dans
#: les `params` de la fiche (les noms de `model_capabilities`), et le nom de leur TYPE de réglage.
SAMPLING_SETTINGS = (TEMPERATURE, SEED, TOP_P)


def sampling_of(source, prefix: str = '') -> dict:
    """Les réglages de tirage d'un élément (ses colonnes `<prefix>temperature`, `<prefix>seed`,
    `<prefix>top_p`) ou d'un dict d'options, par leur nom NU — TOUJOURS les trois clés : `None` y
    veut dire « celui du modèle » (graine : un tirage neuf), jamais « non dit ». Ce que les apps
    passent aux moteurs (`options`) et aux appels de langage (`**sampling_of(item, 'llm_')`), au
    lieu de relire chaque colonne."""
    def read(name):
        key = prefix + name
        return source.get(key) if isinstance(source, dict) else getattr(source, key, None)
    return {name: read(name) for name in SAMPLING_SETTINGS}


def sampling_options(source, prefix: str = '') -> dict:
    """`sampling_of` réduit à ce qui est RÉGLÉ — le `options` d'un moteur (le contrat uniforme de
    `BaseModelBackend.sampling_*`), où une clé absente laisse jouer celle du moteur."""
    return given_values(sampling_of(source, prefix))


def _pget(p, key, default=None):
    """Accès uniforme à un champ de schéma, que `p` soit un Param ou un dict (schema_to_dicts)."""
    return p.get(key, default) if isinstance(p, dict) else getattr(p, key, default)


def _show_if_met(cond, values) -> bool:
    """Le `show_if` d'un param est-il satisfait par `values` ? MÊME vocabulaire que le moteur
    JS (wama-params.js::met) : {field, equals:…} | {field, not_equals:…} | {field, in:[…]} |
    champ seul → truthy | {any: [conditions]} → l'une d'elles (2026-10-28).

    Une valeur en LISTE veut dire « l'une de » (2026-10-18) : un porteur dont la valeur n'est pas
    encore connue — la nature de ce que recevra un nœud du Studio, image OU vidéo — satisfait la
    condition de chacune (`studio/services/graph_flow`, « inconnu n'est pas vide »)."""
    if not cond:
        return True
    if isinstance(cond, str):
        cond = {'field': cond}
    if cond.get('any'):
        return any(_show_if_met(one, values) for one in cond['any'])
    cur = values.get(cond.get('field'))
    if isinstance(cur, (list, tuple, set)):
        return any(_show_if_met(cond, {cond.get('field'): one}) for one in cur)
    if cond.get('in'):
        return str(cur) in [str(x) for x in cond['in']]
    if 'equals' in cond:
        return str(cur) == str(cond['equals'])
    if 'not_equals' in cond:
        return str(cur) != str(cond['not_equals'])
    return bool(cur) and cur not in ('false', '0')


def condition_fields(cond) -> List[str]:
    """Les champs qu'une condition `show_if` LIT — un seul, ou ceux de chaque branche d'un `any`.
    Lu par qui doit connaître la commande d'un réglage (`scoped_names`, la clause `when` des
    prompts) au lieu de supposer un `field` unique."""
    if not cond:
        return []
    if isinstance(cond, str):
        return [cond]
    if cond.get('any'):
        return [name for one in cond['any'] for name in condition_fields(one)]
    return [cond['field']] if cond.get('field') else []


def scoped_names(schema, names) -> List[str]:
    """Les réglages de la ⚙ d'UN process : `names` (ce qu'il surveille), plus le champ qui COMMANDE
    la condition d'un réglage retenu (et la commande de cette commande), plus les porteurs cachés —
    dans l'ordre du schéma. JUMEAU SERVEUR de `wama-params.js::scopedSchema` (la ⚙ d'une étape sur
    la card, 2026-10-13), même règle — garde de parité `tests_cap_from_js`. Lu par le nœud d'étape
    du Studio, qui montre la ⚙ de son étape, et par son exécuteur, qui écrit ce que le nœud a décidé
    (2026-10-18 : une seconde règle cachait l'interrupteur de l'étape et ne l'écrivait jamais — une
    étape éteinte sur l'élément ne se lançait pas)."""
    wanted = set(names or ())
    grew = True
    while grew:
        grew = False
        for p in schema:
            if _pget(p, 'name') not in wanted:
                continue
            for field in condition_fields(_pget(p, 'show_if')):
                if field not in wanted:
                    wanted.add(field)
                    grew = True
    return [_pget(p, 'name') for p in schema
            if _pget(p, 'type') == 'hidden' or _pget(p, 'name') in wanted]


def applicable_defaults(schema, values=None) -> dict:
    """Défauts APPLICABLES d'un schéma pour un élément NAISSANT : params de contexte 'item'
    dont `default` est renseigné et dont le `show_if` est satisfait par `values` (typiquement
    {nature_détectée}).

    Pourquoi le filtre show_if : appliquer TOUS les défauts poserait sur l'élément les champs
    d'une AUTRE famille de média (gif_fps=12 sur une image) — l'app réelle n'envoie que les
    champs VISIBLES de sa zone de composition, ce filtre en est l'équivalent serveur.
    C'est la première couche de la cascade du dépôt (défauts ← user_settings ← POST), celle
    qui donne ses valeurs à un élément frais — section RÉGLAGES de card vide sinon (constat
    Fabien 31/08 sur la jumelle converter_01). `schema` : Param ou dicts (accès _pget).
    """
    values = dict(values or {})
    out = {}
    for p in schema:
        if 'item' not in (_pget(p, 'contexts') or ()):
            continue
        default = _pget(p, 'default')
        if default is None:
            continue
        if not _show_if_met(_pget(p, 'show_if') or None, values):
            continue
        out[_pget(p, 'name')] = default
    return out


# ── Réglages UTILISATEUR du VOLET (brique `user_settings`) — dérivés du schéma ─────────────
# Portés de l'imager le 2026-09-26, quand le transcriber en a eu besoin : le volet EST la
# surface des défauts utilisateur, seuls ses params sont persistés, et la clé de STOCKAGE est
# une fonction du param — le `dom_id` du volet par défaut (la forme de l'imager, unique entre
# ses deux domaines) ; une app dont les clés stockées suivent une autre règle la DÉCLARE
# (`key=`), les clés déjà en base restant ce qu'elles sont (frontière des données).
# ⏳ 2026-10-21 : LA règle commune est posée (`domain_key` : `<domaine>.<nom>` d'un réglage
# `remembered`), et `manage.py align_setting_keys` en fait le plan et la preuve sur la base ; les
# trois règles du parc (ce `dom_id`, `panel_name_key`, les règles écrites des apps) restent lues
# jusqu'à la bascule, qui se fait dans le même geste que l'exécution du plan validé.
def panel_dom_id(p):
    """dom_id du param sur la surface VOLET, ou None s'il n'y figure pas.

    Deux formes coexistent : un dict par surface (params d'app, IDs legacy différents selon la
    surface) ou une chaîne unique (params de brique, même id partout — la surface se lit alors
    dans `contexts`). Ignorer la 2ᵉ écartait silencieusement output_format/output_quality."""
    dom = _pget(p, 'dom_id')
    if isinstance(dom, dict):
        return dom.get('panel')
    if dom and 'panel' in (_pget(p, 'contexts') or ()):
        return dom
    return None


def panel_name_key(p):
    """Clé de stockage = le NOM du param, s'il figure au volet (None sinon). L'autre règle que
    `panel_dom_id`, celle des apps dont les réglages portent le nom de leur colonne (transcriber,
    anonymizer, 2026-09-27)."""
    return _pget(p, 'name') if 'panel' in (_pget(p, 'contexts') or ()) else None


def remembered(p) -> bool:
    """Le réglage se retient-il (préférence de l'utilisateur) ? Sa déclaration `remember`, sinon
    sa présence au volet — la surface des défauts de l'utilisateur."""
    declared = _pget(p, 'remember')
    if declared is not None:
        return bool(declared)
    return 'panel' in (_pget(p, 'contexts') or ())


def domain_key(domain: str):
    """LA règle de clé de stockage (2026-10-21, « une seule règle pour tous ») : `<domaine>.<nom>`
    d'un réglage retenu, None sinon. Le domaine est toujours nommé (`app_modes`), donc deux
    domaines d'une app ne se mêlent jamais (l'`audio.quality_intent` de l'enhancer n'est pas son
    `image_video.quality_intent`), et une app qui gagne un domaine ne déplace aucune clé. Le nom
    est celui du param : ce que lisent la cascade de naissance et le curseur au lancement.
    Rend une fonction de param, la forme du `key=` des fonctions du volet."""
    def key(p):
        name = _pget(p, 'name')
        return f'{domain}.{name}' if name and remembered(p) else None
    return key


def panel_defaults(params, key=None) -> dict:
    """{clé de stockage: défaut} des params du volet."""
    key = key or panel_dom_id
    return {k: _pget(p, 'default') for p in params if (k := key(p))}


def panel_values_by_name(stored, params, key=None) -> dict:
    """Ré-indexe les réglages STOCKÉS vers ce que `WamaParams.render` attend (le `name` du
    param, `p.name in values` côté JS)."""
    key = key or panel_dom_id
    return {_pget(p, 'name'): stored[k] for p in params if (k := key(p)) and k in stored}


def panel_prefs_from_post(post, params, key=None) -> dict:
    """Chemin INVERSE de `panel_values_by_name` : les valeurs postées par NOM, re-clées pour le
    stockage. Ne retient que ce que le POST porte : une clé absente n'écrase pas un réglage."""
    key = key or panel_dom_id
    return {k: post.get(_pget(p, 'name')) for p in params
            if (k := key(p)) and _pget(p, 'name') in post}


#: Une valeur est POSÉE si elle n'est ni absente ni vide. `False` et `0` COMPTENT — un
#: interrupteur décoché et un « 0 = inchangé » sont des choix, pas des silences (même
#: convention que la vue d'upload du converter depuis toujours).
def _posee(v) -> bool:
    return v not in (None, '')


def given_values(values) -> dict:
    """`values` réduit à ce qui est POSÉ (`_posee`) : le « posté » qu'un appel hors formulaire passe
    à une naissance (`user_settings.new_element_settings`) — un créateur de `tool_api`, où ce qui
    est omis prend le réglage retenu de l'auteur, sinon le défaut du schéma (2026-10-29)."""
    return {name: value for name, value in (values or {}).items() if _posee(value)}


def effective_settings(schema, posees=None, preset=None, contexte=None) -> dict:
    """Valeurs EFFECTIVES d'un élément — **défauts (schéma) ← preset ← réglages POSÉS**.

    LA cascade, écrite une fois (formulation de Fabien, 2026-09-01 ; cf. `ROADMAP §23.2bis`).
    Elle remplace trois couches qui faisaient le même travail chacune dans son coin :
    `converter/utils/quality_presets.resolve_options` (preset ← posé, sans les défauts), les
    défauts en dur des backends (`options.get('gif_fps', 12)`) et `applicable_defaults` seule.

    ⚠ Ce qui rend un preset POSSIBLE : la base ne doit porter que ce que l'utilisateur a POSÉ
    (vide = « non réglé, le preset décide »). Un défaut stocké en base est indiscernable d'un
    choix délibéré — et un preset ne pourrait alors plus rien arbitrer. C'est la raison pour
    laquelle les presets du converter fonctionnent (son JSON ne contient que l'explicite) et
    pour laquelle les 8 autres apps devront passer par là AVANT d'avoir des profils (§23.2bis).

    Args:
        schema   : `Param` ou dicts (`schema_to_dicts`).
        posees   : ce que l'utilisateur a réglé — vide/absent = non réglé.
        preset   : valeurs du préréglage choisi (l'app le résout : elle seule connaît sa table).
        contexte : valeurs qui pilotent les `show_if` (ex. `{'media_type': 'image'}`) ; les
                   valeurs posées s'y ajoutent, comme dans le moteur JS.

    Returns: {nom: valeur} — les seules clés applicables à ce contexte.
    """
    posees = {k: v for k, v in (posees or {}).items() if _posee(v)}
    ctx = dict(contexte or {})
    ctx.update(posees)
    out = applicable_defaults(schema, ctx)
    out.update({k: v for k, v in (preset or {}).items() if _posee(v)})
    out.update(posees)
    return out


#: Les types de réglage NUMÉRIQUES — bornés par le schéma (`coerce_params`). `temperature` en est un
#: (2026-10-21), avec une valeur de plus : vide = celle du modèle (None, jamais le minimum). La
#: graine (`seed`, vide = un tirage neuf) et le `top_p` (vide = celui du modèle) aussi (2026-10-22).
NUMERIC_TYPES = ('range', 'number', 'intent') + SAMPLING_SETTINGS

#: Les réglages de TIRAGE pour qui VIDE est un CHOIX — « celle du modèle » (température, top_p),
#: « un tirage neuf » (graine) — rendu `None`, jamais le minimum ni le défaut (2026-10-22 : la
#: règle de la température étendue à ses deux voisins ; la graine de l'imager la tenait par une
#: exception locale, `SETTINGS_EMPTY_IS_VALUE`, et un `seed_cleared` écrit dans sa vue).
EMPTY_IS_NONE_TYPES = SAMPLING_SETTINGS     # chaque type porte le nom de son réglage


def coerce_params(schema, data, caps=None):
    """Borne UNIQUE des paramètres numériques = le SCHÉMA (`params.py`). Source de vérité serveur.

    Remplace les clamps hardcodés `max(min_, min(max_, x))` disséminés dans les vues/tâches
    (≈28 sites, cf. PROJECT_STATUS §21bis) : la borne n'est plus copiée, elle est LUE du schéma
    déjà affiché côté client → plus de dérive possible entre le slider et la validation serveur.

    schema : itérable de `Param` (ou de dicts issus de `schema_to_dicts`).
    data   : mapping nom→valeur brute (ex. `request.POST`, ou un simple dict).
    caps   : optionnel {nom: max_dynamique} — plafonne DAVANTAGE la borne haute d'un range/number
             selon une capacité runtime (ex. `duration` ← `max_duration` du modèle choisi). Un cap
             ne peut que RESSERRER la borne du schéma, jamais l'élargir.

    Retourne {nom: valeur_coercée} pour chaque paramètre numérique (`range`/`number`) du schéma :
    valeur absente/illisible → `default` du schéma ; sinon clampée à [min, min(max, cap)].
    Les paramètres non numériques (select/toggle/text…) sont ignorés — le caller les valide à part.

    `intent` (le curseur rapide/qualité commun, chantier C 2026-09-20) est numérique lui aussi :
    borné à [0, 100], défaut 50, rendu en ENTIER — jusque-là il était ignoré ici et chaque vue
    rappelait `read_quality_intent` à la main (mesuré : `wama/views.py`, synthesizer, avatarizer).
    """
    caps = caps or {}
    out = {}
    for p in schema:
        ptype = _pget(p, 'type')
        if ptype not in NUMERIC_TYPES:
            continue
        name = _pget(p, 'name')
        lo = _pget(p, 'min')
        hi = _pget(p, 'max')
        if ptype == 'intent':
            lo = 0 if lo is None else lo
            hi = 100 if hi is None else hi
        cap = caps.get(name)
        if cap is not None:
            hi = cap if hi is None else min(hi, cap)
        raw = data.get(name) if hasattr(data, 'get') else None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            if ptype in EMPTY_IS_NONE_TYPES:
                out[name] = None        # vide, absent ou illisible : celle du MODÈLE (graine : neuve)
                continue
            dflt = _pget(p, 'default')
            val = float(dflt) if dflt is not None else (float(lo) if lo is not None else 0.0)
        if lo is not None:
            val = max(float(lo), val)
        if hi is not None:
            val = min(float(hi), val)
        out[name] = int(round(val)) if ptype in ('intent', 'seed') else val
    return out


# ── Accès au schéma d'une app (accesseur UNIQUE, facette F3) ─────────────────
def schema_for_app(app_id: str) -> List[dict]:
    """
    Schéma de params d'une app, résolu depuis le REGISTRE (`wama/<app>/params.py`).

    Accesseur UNIQUE de la facette F3 — pendant de `app_capabilities()` (F2 capacités) et de
    `studio_node_ports()` (F2 ports). Consommateurs : runner studio, surface outils
    (`tool_api.sanitize_tool_args`). Évite que chaque consommateur recopie la résolution.

    Résolution : pointeur DÉCLARATIF `GENERIC_APPS[app_id]` (`params_module`/`params_attr`),
    sinon convention `wama.<app_id>.params.PARAMS_JSON`. Aucun nom de module en dur.

    Retourne [] si l'app n'en déclare pas — l'appelant ne doit pas s'en trouver bloqué.

    ⚠ Une app à plusieurs domaines (imager image/vidéo, enhancer média/audio) n'expose ici que
    son attribut PRINCIPAL (`params_attr`). Le schéma de CHAQUE domaine, le domaine le nomme
    (`app_modes`, `params_schema`, 2026-10-21) : il se lit par `app_modes.domain_schema`.
    """
    module_name, attr = _params_location(app_id)
    return _module_list(module_name, attr)


def _params_location(app_id: str):
    """(module, attribut) du schéma PRINCIPAL d'une app — la résolution que `schema_for_app` et
    `groups_for_app` partagent : pointeur DÉCLARATIF `GENERIC_APPS[app_id]`, sinon convention."""
    module_name = attr = None
    try:
        from wama.studio.services.generic_runner import GENERIC_APPS
        conf = GENERIC_APPS.get(app_id) or {}
        module_name, attr = conf.get('params_module'), conf.get('params_attr')
    except Exception:
        pass
    if not module_name:
        module_name, attr = f'wama.{app_id}.params', 'PARAMS_JSON'
    return module_name, attr or 'PARAMS_JSON'


def _module_list(module_name: str, attr: str) -> List[dict]:
    import importlib
    try:
        return list(getattr(importlib.import_module(module_name), attr, []) or [])
    except Exception:
        return []


def groups_for_app(app_id: str) -> List[dict]:
    """Groupes d'affichage (`ParamGroup`) du schéma PRINCIPAL d'une app — le pendant de
    `schema_for_app`, pour qu'une surface qui rend le schéma ENTIER (le nœud du Studio,
    2026-10-12) le rende comme la modale de l'app : groupes, conditions de groupe, colonnes.

    Convention, comme les schémas : le groupe d'un schéma `<X>PARAMS_JSON` s'appelle
    `<X>GROUPS_JSON` (anonymizer, converter : `GROUPS_JSON` ; imager : `IMAGE_GROUPS_JSON`).
    [] quand l'app n'en déclare pas — le rendu est alors à plat, comme dans sa propre modale."""
    module_name, attr = _params_location(app_id)
    if not attr.endswith('PARAMS_JSON'):
        return []
    return _module_list(module_name, attr[:-len('PARAMS_JSON')] + 'GROUPS_JSON')


def declared_param_schemas(app_id: str):
    """
    TOUS les schémas de params déclarés par le module de l'app — pas seulement l'attribut
    principal que rend `schema_for_app()`. Forme : {'primary': <attr du nœud studio>,
    'schemas': {attr: [param, …]}} ; None quand l'app n'en déclare pas.

    Domicile de la capacité « déclaration COMPLÈTE » (imager IMAGE+VIDEO, enhancer
    MEDIA+AUDIO — trou #10 du manifeste, résorbé 2026-08-11). Consommateur : extraction de
    manifeste (facette params). Même résolution déclarative que `schema_for_app`
    (GENERIC_APPS.params_module/params_attr, repli convention `wama.<app>.params`).
    """
    import importlib
    module_name, primary = _params_location(app_id)
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None
    schemas = {}
    for attr in sorted(dir(mod)):
        if attr.endswith('PARAMS_JSON') and not attr.startswith('_'):
            val = getattr(mod, attr)
            if isinstance(val, list) and val:
                schemas[attr] = list(val)
    if not schemas:
        return None
    return {'primary': primary if primary in schemas else sorted(schemas)[0],
            'schemas': schemas}


def schema_model_kwargs(app_id: str, params: dict) -> dict:
    """
    Sous-ensemble de `params` qui est À LA FOIS déclaré au schéma de l'app ET un champ
    concret de son modèle — prêt à passer à `Model.objects.create(**…)`.

    Sert à ce qu'un outil `add_to_<app>` accepte TOUT ce que le schéma expose à l'UI, sans
    recopier la liste des champs dans sa signature (elle dériverait au prochain param ajouté).
    Le schéma étant lui-même dérivé du modèle (`derive_from_model`), la correspondance est la
    règle ; les params « transitoires UI » (déclarés par override, sans champ) sont écartés
    ici et restent à la charge de l'outil qui sait quoi en faire.

    Les valeurs sont coercées par le schéma (bornes + booléens) avant d'être rendues.
    """
    schema = schema_for_app(app_id)
    if not schema or not params:
        return {}
    try:
        from wama.common.utils.detail_registry import DetailRegistry
        entry = DetailRegistry.get(app_id)
        model = entry['model'] if entry else None
    except Exception:
        model = None
    if model is None:
        return {}
    concrete = {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}
    declared = {_pget(p, 'name') for p in schema}
    coerced = coerce_schema_values(schema, params)
    return {k: v for k, v in coerced.items() if k in declared and k in concrete}


def schema_extra_params(app_id: str, params: dict) -> dict:
    """
    Symétrique de `schema_model_kwargs` : les params DÉCLARÉS au schéma qui ne sont PAS des
    champs du modèle — les « réglages transitoires » que l'app range dans un champ JSON
    (`ConversionJob.options`, par ex.).

    Évite de re-lister ces clés à la main chez chaque appelant : la liste vit au schéma.
    """
    schema = schema_for_app(app_id)
    if not schema or not params:
        return {}
    model_keys = set(schema_model_kwargs(app_id, params))
    coerced = coerce_schema_values(schema, params)
    return {k: v for k, v in coerced.items() if k not in model_keys}


def schema_arg_names(app_id: str) -> set:
    """Noms de params qu'une app DÉCLARE — surface d'arguments acceptable d'un outil `**params`."""
    return {_pget(p, 'name') for p in schema_for_app(app_id)}


def choice_values(p) -> List[str]:
    """Valeurs VALIDES d'un select/radio : ses `choices` statiques. UNE fonction pour la porte
    (`invalid_choice_values`), l'annonce aux assistants (`tool_api` : enum JSON et ligne
    « choix ») et `schema_choice_values` : les trois ne peuvent plus diverger (garde
    `tests_mcp_server` : un enum n'est jamais plus strict que la porte). Un select tiré du
    CATALOGUE n'a pas de `choices` : rien à annoncer, rien à refuser (règle unique, 2026-10-07)."""
    return [str(c[0]) if isinstance(c, (list, tuple)) else str(c)
            for c in (_pget(p, 'choices') or [])]


def catalog_options(p) -> List[Tuple[str, str]]:
    """[(valeur, libellé)] d'un select tiré du CATALOGUE (`options_source='catalog'`), lus sur le
    domaine qu'il DÉCLARE (`options_query`), « auto » en tête quand il l'offre (`options_auto`).

    LA lecture côté serveur d'un select de catalogue (2026-10-07, demande de Fabien : « une route
    unique ») — celle de l'endpoint des selects (`api_model_options` : `get_registry_models` sur
    le même domaine), donc les mêmes valeurs dans le même espace de clés que le select, la modale
    et le volet que le navigateur remplit. Elle remplace cinq lectures écrites à la main : le
    pré-rendu des volets (`tts_engine_choices`, enhancer), le nœud du studio, la validation à la
    création de l'avatarizer. Le select du navigateur garde l'endpoint (drapeaux d'UI : prévision,
    groupes, distants de l'utilisateur, mode) ; ici, la liste seule. [] hors catalogue, ou
    catalogue illisible — jamais une levée, jamais une vieille liste."""
    if _pget(p, 'options_source') != 'catalog':
        return []
    query = dict(_pget(p, 'options_query') or {})
    source = query.pop('source', None)
    try:
        from wama.model_manager.services import get_registry_models
        choices, _info = get_registry_models(source, **query)
    except Exception:
        choices = []
    from wama.common.utils.auto_model import AUTO, AUTO_LABEL
    head = [(AUTO, AUTO_LABEL)] if _pget(p, 'options_auto') else []
    return head + [(str(key), label) for key, label in choices]


def invalid_choice_values(schema, data) -> dict:
    """{nom: (valeurs_refusées, choices_valides_triés)} pour chaque valeur PRÉSENTE hors
    des valeurs valides du schéma (`choice_values` : choix déclarés + domaine déclaré).

    Pendant de `coerce_params` pour les selects : la coercition borne les nombres, ceci
    borne les énumérations — au point d'exécution unique (`execute_tool`), pour que les
    43 outils soient couverts sans validation recopiée par app. `None` et `''` passent
    toujours (absence / « défaut ») ; les listes sont validées élément par élément."""
    out = {}
    for p in schema:
        name = _pget(p, 'name')
        if name not in data:
            continue
        valides = set(choice_values(p))
        if not valides:
            continue
        v = data[name]
        if v is None or v == '':
            continue
        elems = v if isinstance(v, (list, tuple)) else [v]
        refusees = [x for x in elems if str(x) not in valides]
        if refusees:
            out[name] = (refusees, sorted(x for x in valides if x))
    return out


def unapplicable_numeric_values(schema, data) -> dict:
    """{nom: (valeur_refusée, explication)} pour chaque nombre PRÉSENT que le schéma ne peut
    PAS appliquer — hors de la grille `step` déclarée depuis `min`.

    ⚠⚠ POURQUOI (mesuré le 2026-09-23). L'assistant a lancé une anonymisation avec
    `blur_ratio=2`, alors que le schéma déclare `min=1, step=2` (noyau gaussien, donc IMPAIR)
    et que la description remise au modèle dit « (impaire). [1–99] (défaut : 25) ». Personne
    ne l'a refusé : `normalize_blur_ratio` a réécrit 2 en 3, en silence. Un noyau de 3×3 ne
    floute rien — SAM3 avait pourtant trouvé les trois visages, et la photo est sortie
    IDENTIQUE, sans une erreur nulle part. *Une valeur corrigée en silence est une valeur
    qu'on n'a pas refusée.*

    Pendant de `invalid_choice_values` pour les nombres : celle-là borne les énumérations,
    celle-ci la GRILLE. Les bornes min/max, elles, restent CLAMPÉES par `coerce_params` — on
    ne refuse que ce qu'aucune coercition ne peut rendre applicable.

    L'explication nomme la grille ET le défaut, et invite à OMETTRE : un modèle qui ne sait
    pas quoi mettre ne doit pas deviner, il doit laisser l'app décider.
    """
    out = {}
    for p in schema:
        name, step = _pget(p, 'name'), _pget(p, 'step')
        if not step or name not in data:
            continue
        value = data[name]
        if value is None or value == '' or isinstance(value, bool):
            continue
        try:
            value, step = float(value), float(step)
            start = float(_pget(p, 'min') or 0)
        except (TypeError, ValueError):
            continue
        if step <= 0:
            continue
        gap = abs((value - start) / step - round((value - start) / step))
        if gap <= 1e-6:
            continue
        default = _pget(p, 'default')
        nearest = start + round((value - start) / step) * step
        nearest = int(nearest) if float(nearest).is_integer() else round(nearest, 6)
        out[name] = (data[name],
                     f"valeurs applicables de {_format_number(start)} en {_format_number(step)} "
                     f"(la plus proche : {_format_number(nearest)}"
                     + (f" ; défaut de l'app : {_format_number(default)}" if default is not None else '')
                     + ") — omettez ce paramètre pour laisser l'app décider")
    return out


def _format_number(v):
    """Affichage d'un nombre sans `.0` parasite (un noyau se lit « 25 », pas « 25.0 »)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f.is_integer() else str(round(f, 6))


def schema_choice_values(app_id, name) -> set:
    """Valeurs valides d'un param à `choices`, DÉRIVÉES du schéma — jamais recopiées.

    C'est l'anti-« liste en dur » : la copie locale des styles describer avait oublié
    'meeting' (proposé par l'UI, refusé par l'outil), celle des modèles enhancer vivait
    dans tool_api. Ensemble vide si le param n'existe pas ou n'a pas de choices —
    l'appelant décide alors de ne pas valider (plutôt que de tout refuser)."""
    p = next((p for p in schema_for_app(app_id) if _pget(p, 'name') == name), None)
    return set(choice_values(p)) if p else set()


_TRUTHY = ('1', 'true', 'on', 'oui', 'yes')


#: Plafonds d'un réglage `mapping` : des noms, pas un document.
MAPPING_MAX_KEYS = 500
MAPPING_MAX_CHARS = 200


def _coerce_date(raw):
    """Une date `AAAA-MM-JJ` (objet `date`), None si vide ou illisible."""
    import datetime
    if isinstance(raw, datetime.date):
        return raw
    try:
        return datetime.date.fromisoformat(str(raw).strip()[:10]) if str(raw).strip() else None
    except ValueError:
        return None


def _coerce_mapping(raw):
    """`{clé: texte}` assaini — un objet, ou son JSON posté par un formulaire ; les valeurs vides
    sortent (une clé sans texte n'est pas nommée). None si rien ne reste."""
    import json
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '{}')
        except ValueError:
            return None
    if not isinstance(raw, dict):
        return None
    out = {}
    for key, value in list(raw.items())[:MAPPING_MAX_KEYS]:
        text = str(value if value is not None else '').strip()[:MAPPING_MAX_CHARS]
        if str(key).strip() and text:
            out[str(key).strip()[:MAPPING_MAX_CHARS]] = text
    return out or None


def coerce_schema_values(schema, data, only_present: bool = True) -> dict:
    """
    Coercition COMPLÈTE d'un mapping selon le schéma : types (booléens) + bornes (numériques).

    COMPLÈTE `coerce_params()` sans la ré-implémenter : les bornes restent calculées par elle
    (la « borne unique » du schéma), on n'ajoute ici que le typage des toggles et le passage
    des autres champs. Remplace le `_coerce()` local du runner studio, qui convertissait les
    types SANS appliquer les bornes — le studio échappait donc au clamp serveur.

    only_present=True (défaut) : ne retourne QUE les clés réellement fournies. C'est ce qu'il
    faut pour un appel d'outil, où une clé absente doit laisser jouer le défaut de la fonction
    Python — à l'inverse d'un POST de formulaire, où `coerce_params` réinjecte le défaut du
    schéma pour tous les numériques.
    """
    get = data.get if hasattr(data, 'get') else (lambda k, d=None: d)
    numeric = coerce_params(schema, data)
    out = {}
    for p in schema:
        name, ptype = _pget(p, 'name'), _pget(p, 'type')
        raw = get(name)
        if ptype == 'date' and raw is not None:
            out[name] = _coerce_date(raw)       # vide EFFACE la date (« pas de date »)
            continue
        if ptype == 'mapping' and raw is not None:
            out[name] = _coerce_mapping(raw)
            continue
        if ptype in EMPTY_IS_NONE_TYPES and raw == '':
            out[name] = None                    # vide = revenir à celle du MODÈLE (un choix)
            continue
        # `''` = champ de formulaire laissé vide = NON FOURNI. Sans ça, un `resize_w=''` posté
        # par un <input number> vide serait clampé au minimum du schéma (0) au lieu d'être
        # ignoré, et écraserait la valeur par défaut du traitement.
        if only_present and (raw is None or raw == ''):
            continue
        if ptype in NUMERIC_TYPES:     # `intent` : entier 0-100 (chantier C)
            val = numeric.get(name)
            if val is not None and float(val).is_integer():
                val = int(val)          # 3.0 → 3 : les champs entiers n'aiment pas les floats
            out[name] = val
        elif ptype == 'toggle':
            out[name] = raw if isinstance(raw, bool) else str(raw).strip().lower() in _TRUTHY
        else:
            out[name] = raw
    return out


# ── La PORTE d'un réglage reçu : refuser ce qu'aucune coercition ne rend applicable ──────────
# `coerce_schema_values` TYPE et BORNE ; elle ne REFUSE rien. Trois cas ne se corrigent pas sans
# mentir, et se refusent en nommant la valeur : un choix hors liste (`invalid_choice_values`), un
# nombre hors de sa grille (`unapplicable_numeric_values`), un nombre ILLISIBLE — `coerce_params`
# le remplacerait par le défaut en silence, alors que l'utilisateur a écrit autre chose.
# Lue par la porte des outils (`tool_api.execute_tool`, qui composait les deux premiers à la main
# jusqu'au 2026-10-12), le lancement d'un graphe du Studio, l'exécution d'une fonction et d'un
# nœud intégré : UNE composition.

def schema_refusals(schema, data) -> dict:
    """{nom: raison} de chaque valeur PRÉSENTE que le schéma refuse. Vide = tout est applicable.

    La grille se juge sur la valeur BORNÉE, comme la porte des outils l'a toujours fait : une
    valeur au-delà du maximum est ramenée au maximum (coercition), et c'est lui que la grille
    juge — seul ce qu'aucune coercition ne rend applicable est refusé."""
    out = {}
    for name, (refused, valid) in invalid_choice_values(schema, data).items():
        out[name] = (f"{', '.join(map(repr, refused))} n'est pas un choix proposé "
                     f"(choix : {', '.join(valid)})")
    readable = []
    for p in schema:
        name = _pget(p, 'name')
        if name in out or _pget(p, 'type') not in NUMERIC_TYPES:
            continue
        raw = data.get(name) if hasattr(data, 'get') else None
        if raw is None or raw == '' or isinstance(raw, bool):
            continue
        try:
            float(raw)
            readable.append(name)
        except (TypeError, ValueError):
            out[name] = f"{raw!r} n'est pas un nombre"
    bounded = coerce_params(schema, data)
    for name, (value, why) in unapplicable_numeric_values(
            schema, {n: bounded[n] for n in readable if n in bounded}).items():
        out[name] = f"{value!r} — {why}"
    return out


def describe_refusals(refusals: dict) -> str:
    """Une phrase par valeur refusée, dans l'ordre des noms — le texte d'une erreur montrée."""
    return ' ; '.join(f"{name} : {why}" for name, why in sorted(refusals.items()))


def checked_values(schema, data) -> dict:
    """Les valeurs FOURNIES, refusées si le schéma les refuse, sinon typées et bornées — la porte
    d'un réglage reçu (graphe du Studio, card, vue). Lève `ValueError` qui nomme chaque refus."""
    refusals = schema_refusals(schema, data)
    if refusals:
        raise ValueError(f"réglage(s) refusé(s) — {describe_refusals(refusals)}")
    return coerce_schema_values(schema, data)


# ── Le PONT `ParamSpec` → `Param` (ROUTE §10.6 point 3.3bis, règle 2 — marche R1, 2026-10-12) ──
# Une fonction DÉCLARE ses réglages en `ParamSpec` (contrat sérialisé : kind `function`, clés des
# protocoles Data) ; toute surface les REND en `Param`. Le pont ne perd rien de ce que la
# déclaration dit — type, défaut, bornes, choix, unité, aide —, et n'invente rien de ce qu'elle
# ne dit pas : sans libellé court déclaré, le libellé est la CLÉ (la description, souvent une
# phrase entière, devient l'AIDE sous le champ). Il remplace deux projections qui perdaient les
# bornes et faisaient de chaque nombre un champ texte (`studio/views.function_node_params_specs`).
# Lecture par attributs (`key`, `type`…) : ce module ne dépend pas du catalogue.

#: Type de DÉCLARATION (`function_catalog.PARAM_TYPES`) → type de RENDU (`Param.type`).
SPEC_TYPE_TO_PARAM_TYPE = {
    'float': 'number', 'int': 'number', 'bool': 'toggle',
    'enum': 'select', 'str': 'text', 'json': 'textarea',
}


def param_from_spec(spec) -> Param:
    """Le `Param` d'un `ParamSpec`. Lève `ValueError` sur un type que le pont ne connaît pas —
    jamais un repli silencieux en champ texte (c'est ce qui rendait les nombres en texte)."""
    ptype = SPEC_TYPE_TO_PARAM_TYPE.get(spec.type)
    if ptype is None:
        raise ValueError(f"réglage `{spec.key}` : type « {spec.type} » inconnu du pont "
                         f"({', '.join(SPEC_TYPE_TO_PARAM_TYPE)})")
    choices = None
    if spec.type == 'enum':
        choices = [(str(c), str(c)) for c in (spec.choices or [])]
    step = 1 if spec.type == 'int' else ('any' if spec.type == 'float' else None)
    return Param(name=spec.key, type=ptype, label=spec.key, help=spec.description or '',
                 default=spec.default, choices=choices, min=spec.min, max=spec.max,
                 step=step, unit=spec.unit or '')
