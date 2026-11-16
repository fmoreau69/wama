"""
Suivre un objet DÉSIGNÉ, tranche par tranche — la logique commune du « clic sur un objet »
(2026-11-16, la page de correction des détections ; décision de Fabien : le suivi par le module de
SAM3, dans la boucle commune `playhead_follow`, sur le patron de l'écriture à la lecture).

Ce qui est commun ici, et rien d'autre : l'ENCHAÎNEMENT des tranches d'un suivi. Un moteur qui
sait suivre (`supports_object_tracking`, `track_object(média, image, point= | box=, count=,
reverse=)`) ne tient qu'une fenêtre d'images en mémoire ; l'objet désigné sur une image se suit
donc vers l'avant, tranche après tranche, puis vers l'arrière, chaque tranche repartant de la
dernière boîte vue. Le suivi d'un sens s'arrête à un bord du média, ou quand l'objet n'est plus vu
sur toute la fin d'une tranche.

Ce module ne sait PAS : quel moteur charger, où vit le média, où ranger les résultats — la glu de
l'app (une boucle `playhead_follow`) les fournit. Le serveur n'écrit jamais la correction : il
dépose des PROPOSITIONS, que la page accepte ou refuse (`playback_writing`).
"""
from __future__ import annotations

#: L'objet perdu sur les `LOST_TAIL` dernières images d'une tranche : le suivi de ce sens s'arrête.
LOST_TAIL = 10
#: Cibles suivies à la fois sur un élément (une désignation est un geste humain, pas un flux).
MAX_TARGETS = 8

FORWARD, BACKWARD = 'forward', 'backward'


def clean_targets(raw) -> list:
    """Les cibles envoyées par la page, assainies : `[{'id', 'i', 'point': [x, y]}]`. Lève
    `ValueError` sur une cible illisible ; au plus `MAX_TARGETS`."""
    targets = []
    for entry in list(raw or [])[:MAX_TARGETS]:
        point = [float(v) for v in entry['point']]
        if len(point) != 2 or min(point) < 0:
            raise ValueError(f"point illisible : {entry.get('point')!r}")
        targets.append({'id': str(entry['id'])[:32], 'i': max(0, int(entry['i'])), 'point': point})
    return targets


def next_slice(progress: dict, target: dict):
    """La prochaine tranche à suivre pour `target`, d'après ce qui est déjà fait (`progress` :
    `{sens: {'i', 'box', 'done'}}` de cette cible) — `(sens, image de départ, désignation)` où la
    désignation est `{'point': …}` (la toute première tranche) ou `{'box': …}` (la dernière boîte
    vue) ; None quand les deux sens sont finis. L'avant d'abord : l'arrière part de la boîte que
    l'avant a trouvée sur l'image désignée."""
    forward = progress.get(FORWARD)
    if forward is None:
        return FORWARD, target['i'], {'point': tuple(target['point'])}
    if not forward.get('done'):
        return FORWARD, forward['i'], {'box': forward['box']}
    backward = progress.get(BACKWARD)
    if backward is None:
        start = progress.get('start')
        if not start:                                   # l'objet n'a pas été vu où on l'a désigné
            return None
        return BACKWARD, target['i'], {'box': start}
    if not backward.get('done'):
        return BACKWARD, backward['i'], {'box': backward['box']}
    return None


def advance(progress: dict, direction: str, found: list, window: int) -> list:
    """Range une tranche suivie (`found` : `[{'i', 'box'}]`, l'image de départ d'abord) dans
    `progress` et rend les images NEUVES où l'objet est vu (`[{'i', 'box'}]`) — l'image de départ
    d'une tranche de reprise est celle où la précédente s'est arrêtée : elle n'est pas redite.

    Le sens est FINI quand la tranche est plus courte que la fenêtre (un bord du média), que
    l'objet n'y est vu nulle part après le départ, ou plus sur ses `LOST_TAIL` dernières images."""
    state = progress.get(direction)
    resumed = state is not None
    fresh = found[1:] if resumed else found
    seen = [f for f in fresh if f.get('box')]
    if not resumed and direction == FORWARD:
        progress['start'] = found[0]['box'] if found and found[0].get('box') else None
    if direction == BACKWARD and not resumed:
        seen = [f for f in seen if f is not found[0]]   # l'image désignée, déjà dite par l'avant
    tail = found[-LOST_TAIL:]
    lost = bool(tail) and not any(f.get('box') for f in tail)
    edge = len(found) < window
    last = next((f for f in reversed(found) if f.get('box')), None)
    done = edge or lost or last is None or not seen
    progress[direction] = {'i': last['i'] if last else None, 'box': last['box'] if last else None,
                           'done': done}
    return [{'i': int(f['i']), 'box': [int(v) for v in f['box']]} for f in seen]


def finished(progress: dict, target: dict) -> bool:
    """Le suivi de `target` est-il allé au bout, dans les deux sens ?"""
    return next_slice(progress, target) is None
