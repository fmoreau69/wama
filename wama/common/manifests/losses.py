"""Ce qu'une écriture de manifeste PERDRAIT — la garde des DEUX sens (2026-11-08, Fabien).

Un manifeste s'écrit dans les deux sens : on l'ÉDITE pour appliquer une modification aux registres
et au code (`ingest.write_back`), et on le RÉGÉNÈRE depuis eux après une modification
(`manifest_export`). Quand les deux arrivent en même temps, celui qui écrit le second efface ce que
l'autre a posé, et rien ne le disait : la perte gagne le corpus, puis revient par la synchro.
Vécu le jour même : Albert a cessé d'annoncer la vision de ses modèles, la base a perdu la modalité
`image` de trois modèles qui voient, et l'export s'apprêtait à la retirer du corpus versionné.

La règle, une seule pour les deux portes : un FAIT présent avant et absent après est une PERTE,
et une perte ne s'écrit que sur acceptation explicite (`--accept-losses` / `accept_losses=True`).
Un fait REMPLACÉ (une description réécrite, une mesure de plus) n'en est pas une : le remplacement
se voit au diff ; ce qui disparaît sans remplaçant ne se voit qu'en le cherchant.

Ce qui compte pour un fait :
  • une clé dont la valeur n'est pas vide, absente après ;
  • un élément de liste absent après — listes de scalaires comparées comme ENSEMBLES (l'ordre
    n'est pas un fait), listes d'objets appariées par leur clé naturelle (`kind:key` d'un
    `requires`, `name` d'un réglage, `id` d'un nœud…), sinon par leur contenu ;
  • une valeur non vide devenue vide.

À côté de `ingest.diff_dicts`, l'écart SYMÉTRIQUE d'un manifeste et de l'état courant (`drift`,
projection, `app_regen_check`) — et pas à sa place : il apparie les listes d'objets par INDICE, si
bien qu'un élément inséré en tête fait « changer » tous les suivants (mesuré le 2026-11-08 sur le
corpus : 808 faux écarts). Filtré sur ses côtés vides, il aurait rendu autant de fausses pertes.
Lui faire apparier par `_keyer` changerait trois consommateurs : c'est un chantier, pas un geste de
la garde.
"""
from __future__ import annotations

import json
from typing import Any

#: Clés qui NOMMENT un objet dans une liste, dans l'ordre où on les cherche. Une clé ne nomme que
#: si elle est UNIQUE dans la liste : les trois bornes `cap_from` d'un réglage de température
#: portent toutes `field: model` (2026-11-08, faux positifs au premier export gardé) — elles se
#: nomment alors par l'ensemble de ces clés, et à défaut par leur contenu entier.
NATURAL_KEYS = ('key', 'name', 'id', 'value', 'field', 'path', 'capability', 'mode')

#: Combien de pertes un message montre par manifeste (toutes restent dans la liste rendue).
SHOWN = 8


def _empty(value) -> bool:
    return value is None or value == '' or value == [] or value == {}


def _content(item) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)


def _naming(item, names) -> str:
    return ','.join(f'{n}={item.get(n)}' for n in names)


def _keyer(*lists):
    """La fonction qui nomme les objets de ces listes : la première clé naturelle portée par tous
    et unique dans chacune, sinon l'ensemble des clés naturelles s'il est unique, sinon le
    contenu. Un `requires` se nomme par `kind:key`."""
    items = [x for xs in lists for x in xs]
    if not items or not all(isinstance(x, dict) for x in items):
        return _content

    def unique(fn):
        return all(len({fn(x) for x in xs}) == len(xs) for xs in lists)

    if all('kind' in x and 'key' in x for x in items):
        return lambda x: f"{x['kind']}:{x['key']}"
    for name in NATURAL_KEYS:
        if all(isinstance(x.get(name), (str, int)) and not isinstance(x.get(name), bool)
               for x in items):
            fn = (lambda n: lambda x: f'{n}={x[n]}')(name)
            if unique(fn):
                return fn
    present = [n for n in NATURAL_KEYS if any(n in x for x in items)]
    if present and unique(lambda x: _naming(x, present)):
        return lambda x: _naming(x, present)
    return _content


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 120 else text[:117] + '…'


def lost_facts(before: Any, after: Any, path: str = '') -> list[dict]:
    """Les faits de `before` absents de `after` : `[{path, lost}]`, `lost` en texte court.

    `before`/`after` sont deux états du même manifeste (enveloppe entière, ou une facette)."""
    out: list[dict] = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key, value in before.items():
            sub = f'{path}.{key}' if path else str(key)
            if key not in after:
                if not _empty(value):
                    out.append({'path': sub, 'lost': _short(value)})
            else:
                out += lost_facts(value, after[key], sub)
        return out
    if isinstance(before, list) and isinstance(after, list):
        keyer = _keyer(before, after)
        kept = {keyer(x): x for x in after}
        for item in before:
            key = keyer(item)
            if key not in kept:
                out.append({'path': path, 'lost': _short(item)})
            elif isinstance(item, (dict, list)):
                out += lost_facts(item, kept[key], f'{path}[{key}]')
        return out
    if not _empty(before) and _empty(after):
        out.append({'path': path, 'lost': _short(before)})
    return out


def describe(losses: list[dict], shown: int = SHOWN) -> list[str]:
    """Les pertes en lignes lisibles (les `shown` premières, puis le compte du reste)."""
    lines = [f"{x['path'] or '(racine)'} : {x['lost']}" for x in losses[:shown]]
    if len(losses) > shown:
        lines.append(f'… et {len(losses) - shown} autre(s)')
    return lines
