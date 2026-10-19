"""
WAMA Common — CHIPS méta des cards (CARD_DESIGN §10.3, pilote Reader 2026-07-06).

Les chips de l'état CONCIS sont GÉNÉRÉS depuis le schéma params de l'app (champ ``chip=True``
dans params.py) — jamais écrits à la main par app (règle métadonnée-driven). Un select affiche
le LABEL de l'option courante ; un booléen True affiche le label du champ ; vide/False/None
n'affiche rien (un chip = une info POSÉE).

Usage template :
    {% include 'common/_card_chips.html' with chips=item_chips %}
avec, côté vue ou via un helper d'app :
    from wama.common.utils.card_chips import chips_for
    item_chips = chips_for(item, PARAMS_JSON)
"""


#: Mémo des inventaires de catalogue par DOMAINE (`options_query`), partagé entre appels.
#: Une file rend `chips_for` une fois PAR CARD : un cache local à l'appel donnait 20 requêtes
#: pour 20 cards (mesuré). TTL court — ce sont des libellés, pas une décision : au pire un
#: modèle fraîchement installé porte sa clé technique pendant quelques secondes.
_CATALOGUE_MEMO: dict = {}
_CATALOGUE_TTL = 30.0


def _inventaire_voix(user) -> list:
    """[(valeur, libellé)] des voix AFFICHABLES pour cet utilisateur — mémoïsé par user.

    2ᵉ source dynamique résolue par les chips après `catalog` (constat Fabien, card 65 :
    le chip affichait `cv_1` là où l'utilisateur devait lire « Voix Fab »). Les plaques du
    schéma ne portent que les presets STATIQUES du champ — les voix par utilisateur
    (`ua_<id>` ; l'héritage `cv_<id>` est retiré le 2026-09-30) n'y sont jamais. La connaissance vit dans
    `voice_options` (le module qui centralise les voix) ; ici on ne fait que mémoïser.
    """
    import time

    cle = ('voices', getattr(user, 'pk', None))
    entree = _CATALOGUE_MEMO.get(cle)
    if entree and (time.monotonic() - entree[0]) < _CATALOGUE_TTL:
        return entree[1]
    try:
        from wama.common.utils.voice_options import voice_display_options
        valeur = voice_display_options(user)
    except Exception:
        return []                      # même repli que `catalog` : valeur nue, jamais inventée
    _CATALOGUE_MEMO[cle] = (time.monotonic(), valeur)
    return valeur


def _inventaire_catalogue(options_query: dict) -> list:
    """[(clé, libellé)] du domaine déclaré — mémoïsé, jamais fatal.

    La brique ne connaît aucune app : elle passe au catalogue EXACTEMENT ce que le schéma
    déclare (`options_query`), et rien d'autre.
    """
    import time

    cle = tuple(sorted((options_query or {}).items()))
    entree = _CATALOGUE_MEMO.get(cle)
    if entree and (time.monotonic() - entree[0]) < _CATALOGUE_TTL:
        return entree[1]
    try:
        from wama.model_manager.services import get_registry_models
        # ⚠ `source` se passe en POSITIONNEL, il ne peut pas rester dans les mots-clés
        # (2026-09-08) : `get_registry_models(None, source='reader', …)` lève
        # « got multiple values for argument 'source' » — et le `except` ci-dessous
        # l'AVALAIT, donc les chips seraient retombés sur la clé nue sans que rien ne le
        # dise. Aucun schéma ne déclarait de `source` avant les portages du jour : le
        # défaut attendait son premier appelant. Sans source déclarée, on garde le mode
        # PAR CAPACITÉ (source=None), qui est l'intention d'origine.
        domaine = dict(options_query or {})
        choix, _ = get_registry_models(domaine.pop('source', None), **domaine)
        valeur = list(choix)
    except Exception:
        # Catalogue indisponible : valeur NUE plutôt qu'un libellé inventé. Une clé technique
        # est laide ; un faux libellé est pire. Non mémoïsé — l'indisponibilité est transitoire.
        return []
    _CATALOGUE_MEMO[cle] = (time.monotonic(), valeur)
    return valeur


def field_unit(field) -> str:
    """L'UNITÉ d'un champ numérique : `unit` s'il est déclaré, sinon un `chip_label` COURT en
    minuscules — c'est une déclaration d'unité (idiome imager : « s », « fps », « steps » ;
    l'afficher en préfixe donnait « s 5 », mesuré absurde à l'audit 31/08)."""
    unit = field.get('unit') or ''
    cl = field.get('chip_label') or ''
    if not unit and cl and len(cl) <= 5 and cl == cl.lower():
        unit = cl
    return unit


def chips_for(instance, params_json, extra=None, values=None):
    """Construit la liste des chips d'une card depuis le schéma sérialisé (schema_to_dicts).

    Args:
        instance    : l'objet métier (les valeurs sont lues par getattr sur ``name``).
        params_json : liste de dicts (PARAMS_JSON de l'app).
        extra       : chips additionnels d'app, déjà formés [{'label','icon','title','variant'}]
                      — ex. « X pages » (reader), « → mp3 » (format cible, variant='target').
        values      : dict prioritaire sur getattr — pour les valeurs qui vivent dans un
                      conteneur JSON (``options``/``cross_app_options``) et non en colonnes.
                      MÊME contrat que ``card_gear.gear_data`` (brique jumelle) ; sans lui,
                      chipper un champ hors-colonne rendait silencieusement RIEN (getattr →
                      None → filtré) — mesuré le 2026-08-31 sur le converter réel.

    Returns: [{'label','icon','title','variant'}] (variant '' ou 'target').
    """
    chips = []
    src = values or {}
    for field in params_json or []:
        if not field.get('chip'):
            continue
        name = field.get('name')
        value = src[name] if name in src else getattr(instance, name, None)
        # Normalisation AMONT : les valeurs arrivent aussi en CHAÎNES (conteneur JSON,
        # data-*) — 'false' passait le filtre booléen et la card affichait un chip « false »
        # (constat Fabien 31/08) ; 'true' doit suivre la voie du toggle coché.
        if isinstance(value, str):
            s = value.strip()
            if s.lower() == 'false':
                value = False
            elif s.lower() == 'true':
                value = True
            else:
                value = s
        if value in (None, '', False):
            continue
        # chip_label permet un libellé court : « Diarisation » plutôt que « Identifier les
        # locuteurs », qui tiendrait mal dans une piste. Le libellé complet reste au title.
        libelle = field.get('chip_label') or field.get('label') or name
        display = value
        if value is True:
            # Une case cochée s'affiche par son NOM (le réglage est actif) ; décochée, elle ne
            # produit aucun chip (filtré plus haut) — une card ne liste pas ce qui est inactif.
            display = libelle
        else:
            # choices Django = [(value, label), …] (schema_to_dicts) ; options = [{value,label}]
            # (fallback) ; option_groups = [(groupe, [(v, l), …]), …] — l'enhancer ne déclare
            # QUE par groupes : les ignorer rendait son format « non résolu » (audit 31/08).
            _plates = list(field.get('choices') or []) + list(field.get('options') or [])
            for _g in field.get('option_groups') or []:
                _plates += list((_g[1] if isinstance(_g, (list, tuple)) else _g.get('options')) or [])
            # Options tirées du CATALOGUE (`options_source: 'catalog'`, route F4b) : le schéma
            # ne porte plus AUCUNE plaque — c'est tout l'intérêt du portage. Sans résolution
            # ici, le chip retombait sur la valeur NUE et la card affichait la clé technique
            # `synthesizer:coqui-xtts` au lieu de « Coqui XTTS v2 » (constat Fabien, cards
            # 307/309/310). C'est exactement le geste que le commentaire ci-dessous prescrit
            # depuis l'audit du 31/08 : RÉSOUDRE, jamais préfixer.
            # Générique par construction : on n'interroge que ce que le SCHÉMA déclare
            # (`options_query`), la brique ne connaît ni le TTS ni aucune app. Le résultat est
            # mémoïsé par domaine — une file de 50 cards ne fait pas 50 requêtes.
            # ⚠ JOINT SANS CONDITION depuis le 2026-09-08, comme les voix ci-dessous. La
            # garde `not _plates` supposait qu'un champ porte SOIT des plaques statiques,
            # SOIT le catalogue. Les portages F4b du jour (reader, enhancer) font les deux :
            # les `choices` du modèle restent le REPLI rendu avant la réponse de la requête,
            # et le catalogue est la liste servie. Avec la garde, un modèle installé APRÈS
            # coup — le cas même que la route F4b existe pour rendre choisissable — se serait
            # affiché en clé technique sur la card, jamais par son nom. Les plaques statiques
            # gardent la PRIORITÉ (premier match) : aucun libellé existant ne change.
            if field.get('options_source') == 'catalog':
                _plates += _inventaire_catalogue(field.get('options_query') or {})
            # Voix par utilisateur (`options_source: 'voices'`) : les valeurs `ua_` ne
            # sont dans AUCUNE plaque statique — sans cette résolution le chip affichait
            # l'identifiant brut. Joint APRÈS les plaques du champ (un preset statique garde
            # son libellé d'origine) et sans condition `not _plates` : le champ voix PORTE
            # des plaques statiques, elles sont juste incomplètes. Coût : une résolution par
            # utilisateur et par 30 s (mémo), quelle que soit la taille de la file.
            if field.get('options_source') == 'voices':
                _plates += _inventaire_voix(getattr(instance, 'user', None))
            for opt in _plates:
                ov, ol = (opt if isinstance(opt, (list, tuple)) else (opt.get('value'), opt.get('label')))
                if str(ov) == str(value):
                    display = ol or value
                    break
            else:
                if field.get('type') in ('number', 'range'):
                    # SEUL cas légitimement préfixé/suffixé : « 85 » nu ne dit rien (constat
                    # Fabien 31/08 — la card disait « 85 », l'inspecteur « Qualité 85 »).
                    unit = field_unit(field)
                    display = f"{value} {unit}" if unit else f"{libelle} {value}"
                    # FORMAT DÉCLARÉ (`display_format`, 2026-10-04) : « 3:30 » plutôt que
                    # « 210 s » — le même formateur que le curseur (jumeau Python).
                    if field.get('display_format'):
                        from wama.common.utils.param_schema import format_display
                        display = format_display(value, field['display_format']) or display
                # ⚠ Un select/text NON résolu reste NU : le préfixer produisait « Format de
                # sortie mp4 » sur la SORTIE du converter et « Moteur de transcription
                # faster-whisper-large-v3 » chez transcriber (régressions R1/R3 de l'audit
                # 31/08). Le geste juste est de RÉSOUDRE (options_source côté vue), pas de
                # préfixer — le libellé complet reste au title du chip.
        chips.append({
            'label': str(display),
            'icon': field.get('icon') or '',
            'title': field.get('label') or name,
            'variant': '',
            # Section de card v3 où ce chip doit atterrir (CARD_DESIGN §11). Déclaré à la
            # SOURCE, dans le schéma de params : un champ « format de sortie » décrit ce qui
            # va sortir, pas comment on traite — il appartient à la section SORTIE. Défaut
            # 'settings' : sans déclaration, un chip reste un réglage (comportement d'avant).
            'section': field.get('section') or 'settings',
        })
    if extra:
        for c in extra:
            c.setdefault('section', 'settings')
        chips.extend(extra)
    return chips


def input_props_for(instance, file_field='input_file', name=''):
    """Sous-ligne « propriétés RÉELLES du média » de la section ENTRÉE (CARD_DESIGN §11).

    Extraite du pilote reader (`_input_props`, candidat brique mesuré au balayage du
    31/08 — constat Fabien : « les propriétés du fichier d'entrée ne sont pas affichées
    dans la section Entrée des cards » de la jumelle). Relevées sur le FICHIER déposé,
    jamais dérivées des réglages : extension, poids ; les axes propres à une app (pages,
    durée…) restent chez elle, en tête de liste via le retour.
    """
    import os
    props = []
    ext = os.path.splitext(name or '')[1].lstrip('.').lower()
    if ext:
        props.append(ext)
    f = getattr(instance, file_field, None)
    try:
        size = f.size if f else 0
    except (OSError, ValueError):
        size = 0          # fichier absent du disque (purge, tiering) — la card reste lisible
    if size >= 1048576:
        props.append(f"{size / 1048576:.1f} Mo")
    elif size >= 1024:
        props.append(f"{size // 1024} Ko")
    elif size:
        props.append(f"{size} o")      # sinon un fichier <1 Ko s'affichait « 0 Ko »
    return props


def common_chips_for_items(items, params_json, values_of=None):
    """Chips des réglages COMMUNS aux filles d'un lot — pour la card MÈRE (slot
    `meta_template` de `_batch_card.html`).

    Généralisation du pilote transcriber (`views.py::_extra` : « valeur si partagée par
    toutes les filles, sinon rien ») : au lieu d'une liste d'attributs écrite à la main
    par app, la règle s'applique à TOUT champ `chip=True` du schéma. Portée au commun le
    31/08 (audit : mécanisme présent chez 2 apps sur 10, calcul recopiable à l'identique).

    Args:
        items     : les éléments MÉTIER du lot (déjà décorés/aplatis si les réglages
                    vivent en JSON — sinon passer `values_of`).
        values_of : callable(item)->dict optionnel — assiette de valeurs par fille quand
                    elles vivent dans un conteneur (ex. converter :
                    `lambda j: {**(j.options or {}), **(j.cross_app_options or {})}`).

    Returns: {'settings': […], 'output': […]} (mêmes sections que `chips_by_section`) —
    vide si rien n'est partagé. La divergence est OMISE (pas de « Mixte ») : une card
    mère liste ce qui est posé PARTOUT, le détail vit sur les filles.
    """
    communs = {}
    for n, vals in _chip_values(items, params_json, values_of).items():
        if len(vals) == 1:
            v = vals[0][0]
            if v not in (None, ''):
                communs[n] = v
    return chips_by_section(None, params_json, values=communs) if communs else {}


def varying_chips_for_items(items, params_json, values_of=None):
    """Le PENDANT de `common_chips_for_items` : les réglages `chip=True` qui DIFFÈRENT d'une fille
    à l'autre — ce qui distingue les cards d'un lot (2026-10-19, identité du lot :
    `common/services/batch_identity.py`). La card mère ne les affiche pas en « Mixte » : elle dit
    « varie : Modèle (whisper, voxtral) », le détail restant sur les filles.

    Returns: [{'name', 'title', 'values': [libellés DISTINCTS, ordre des filles]}] — vide si tout
    est commun. Un libellé est celui d'un chip (`chips_for` : option résolue, unité, case cochée
    nommée) ; une valeur non posée se dit « — ». Chaque valeur se met en forme sur une fille qui
    la porte (les voix d'un compte se résolvent par son propriétaire)."""
    fields = {f.get('name'): f for f in (params_json or []) if f.get('chip') and f.get('name')}
    out = []
    for n, vals in _chip_values(items, params_json, values_of).items():
        if len(vals) < 2:
            continue
        field = fields[n]
        flags = all(_as_flag(v) is not None for v, _ in vals)
        labels = []
        for v, owner in vals:
            if flags:
                # Une case cochée sur certaines filles seulement : « oui, non » — son chip
                # (le nom du réglage, ou rien) ne dirait pas laquelle.
                label = 'oui' if _as_flag(v) else 'non'
            else:
                chip = chips_for(owner, [field], values={n: v})
                # « Nom — description » (libellés du catalogue) : le nom suffit dans une liste.
                label = chip[0]['label'].split(' — ')[0] if chip else '—'
            if label not in labels:
                labels.append(label)
        if len(labels) > 1:
            # Le libellé COURT du réglage (`chip_label`), sauf quand c'est une unité (« s »).
            short = field.get('chip_label') if not field_unit(field) else ''
            out.append({'name': n, 'title': short or field.get('label') or n, 'values': labels})
    return out


def _as_flag(value):
    """True / False pour une valeur de case à cocher (booléen, 'true'/'false', non posée), None
    pour toute autre valeur."""
    if isinstance(value, bool) or value in (None, ''):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
        return value.strip().lower() == 'true'
    return None


def _chip_values(items, params_json, values_of=None):
    """{nom: [(valeur DISTINCTE, première fille qui la porte)]} des champs `chip=True`, dans
    l'ordre des filles — la lecture commune aux réglages communs et à ce qui varie (une valeur
    qui vit dans un conteneur JSON se lit par `values_of`). Une liste et non un ensemble : une
    valeur JSON (liste, dict) n'est pas hachable."""
    items = list(items or [])
    out = {}
    for f in params_json or []:
        n = f.get('name')
        if not (f.get('chip') and n) or not items:
            continue
        seen = []
        for it in items:
            src = values_of(it) if values_of else {}
            v = src[n] if n in src else getattr(it, n, None)
            if all(v != s for s, _ in seen):
                seen.append((v, it))
        out[n] = seen
    return out


def chips_by_section(instance, params_json, extra=None, values=None):
    """Mêmes chips que `chips_for`, mais GROUPÉS par section de card v3 (CARD_DESIGN §11).

    Renvoie {'settings': [...], 'output': [...], …} — une clé par section rencontrée.
    Permet à une card de remplir ses sections depuis la SEULE déclaration du schéma, sans
    qu'aucune app ne réparte ses chips à la main (métadonnée-driven, philosophie WAMA §3).
    """
    grouped = {}
    for chip in chips_for(instance, params_json, extra=extra, values=values):
        grouped.setdefault(chip.get('section') or 'settings', []).append(chip)
    return grouped
