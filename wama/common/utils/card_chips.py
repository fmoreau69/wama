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
            for opt in _plates:
                ov, ol = (opt if isinstance(opt, (list, tuple)) else (opt.get('value'), opt.get('label')))
                if str(ov) == str(value):
                    display = ol or value
                    break
            else:
                if field.get('type') in ('number', 'range'):
                    # SEUL cas légitimement préfixé/suffixé : « 85 » nu ne dit rien (constat
                    # Fabien 31/08 — la card disait « 85 », l'inspecteur « Qualité 85 »).
                    # `unit` prime (« 120 s ») ; un chip_label COURT en minuscules est une
                    # déclaration d'UNITÉ (idiome imager : « s », « fps », « steps » —
                    # l'afficher en préfixe donnait « s 5 », mesuré absurde à l'audit 31/08).
                    unit = field.get('unit') or ''
                    cl = field.get('chip_label') or ''
                    if not unit and cl and len(cl) <= 5 and cl == cl.lower():
                        unit = cl
                    display = f"{value} {unit}" if unit else f"{libelle} {value}"
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
    items = list(items or [])
    if not items:
        return {}
    noms = [f.get('name') for f in (params_json or []) if f.get('chip') and f.get('name')]
    communs = {}
    for n in noms:
        vals = set()
        for it in items:
            src = values_of(it) if values_of else {}
            vals.add(src[n] if n in src else getattr(it, n, None))
        if len(vals) == 1:
            v = vals.pop()
            if v not in (None, ''):
                communs[n] = v
    return chips_by_section(None, params_json, values=communs) if communs else {}


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
