"""Lecteurs des formats d'ANNOTATION des jeux de données publiés (2026-10-10).

Les annotations natives sont la vérité d'un jeu (`WAMA_APPRENTISSAGE §8bis`) : on les LIT telles
qu'elles sont publiées, on ne les convertit pas en copies éditables. Chaque lecteur rend la même
forme — une entrée par image :

    {'path': <chemin relatif publié>, 'boxes': [[x1, y1, x2, y2], …], 'ignore': [[…], …]}

`ignore` : les objets que le jeu marque lui-même comme inexploitables (WIDER : `invalid`) — un
détecteur qui les trouve n'est pas en faute, un détecteur qui les rate non plus.

Premier lecteur : WIDER FACE (format texte officiel, `wider_face_<split>_bbx_gt.txt`). Les
suivants (Pascal VOC, COCO, YOLO) s'ajoutent ici quand un banc en a besoin.
"""
from __future__ import annotations


def read_wider_face(txt_path) -> list:
    """Le fichier de vérité WIDER FACE : par image, son chemin relatif (`0--Parade/….jpg`), le
    nombre de visages, puis une ligne par visage `x1 y1 w h blur expression illumination invalid
    occlusion pose` (`readme.txt` du jeu). Une image sans visage porte une ligne de zéros."""
    with open(txt_path, encoding='utf-8') as source:
        lines = [line.strip() for line in source if line.strip()]
    entries, k = [], 0
    while k < len(lines):
        path = lines[k]
        count = int(lines[k + 1])
        rows = lines[k + 2:k + 2 + max(count, 1)]
        k += 2 + max(count, 1)
        boxes, ignore = [], []
        for row in rows[:count]:
            values = [int(v) for v in row.split()[:10]]
            x, y, w, h = values[:4]
            if w <= 0 or h <= 0:
                continue
            box = [x, y, x + w, y + h]
            invalid = len(values) > 7 and values[7] == 1
            (ignore if invalid else boxes).append(box)
        entries.append({'path': path, 'boxes': boxes, 'ignore': ignore})
    return entries


#: Format déclaré par une référence de banc → son lecteur.
READERS = {'wider_face': read_wider_face}
