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


def chips_for(instance, params_json, extra=None):
    """Construit la liste des chips d'une card depuis le schéma sérialisé (schema_to_dicts).

    Args:
        instance    : l'objet métier (les valeurs sont lues par getattr sur ``name``).
        params_json : liste de dicts (PARAMS_JSON de l'app).
        extra       : chips additionnels d'app, déjà formés [{'label','icon','title','variant'}]
                      — ex. « X pages » (reader), « → mp3 » (format cible, variant='target').

    Returns: [{'label','icon','title','variant'}] (variant '' ou 'target').
    """
    chips = []
    for field in params_json or []:
        if not field.get('chip'):
            continue
        name = field.get('name')
        value = getattr(instance, name, None)
        if value in (None, '', False):
            continue
        display = value
        if value is True:
            # Une case cochée s'affiche par son NOM (le réglage est actif) ; décochée, elle ne
            # produit aucun chip (filtré plus haut) — une card ne liste pas ce qui est inactif.
            # chip_label permet un libellé court : « Diarisation » plutôt que « Identifier les
            # locuteurs », qui tiendrait mal dans une piste. Le libellé complet reste au title.
            display = field.get('chip_label') or field.get('label') or name
        else:
            # choices Django = [(value, label), …] (schema_to_dicts) ; options = [{value,label}] (fallback).
            for opt in field.get('choices') or []:
                ov, ol = (opt if isinstance(opt, (list, tuple)) else (opt.get('value'), opt.get('label')))
                if str(ov) == str(value):
                    display = ol or value
                    break
            else:
                for opt in field.get('options') or []:
                    if str(opt.get('value')) == str(value):
                        display = opt.get('label') or value
                        break
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


def chips_by_section(instance, params_json, extra=None):
    """Mêmes chips que `chips_for`, mais GROUPÉS par section de card v3 (CARD_DESIGN §11).

    Renvoie {'settings': [...], 'output': [...], …} — une clé par section rencontrée.
    Permet à une card de remplir ses sections depuis la SEULE déclaration du schéma, sans
    qu'aucune app ne réparte ses chips à la main (métadonnée-driven, philosophie WAMA §3).
    """
    grouped = {}
    for chip in chips_for(instance, params_json, extra=extra):
        grouped.setdefault(chip.get('section') or 'settings', []).append(chip)
    return grouped
