"""Bords d'image touchés par une bbox — la notion « l'objet SORT du champ », déclarée UNE fois.

Pourquoi ce module existe (2026-09-12). Trois consommateurs de `cam_analyzer` raisonnaient
déjà sur « la bbox est coupée au bord », chacun à sa façon :

    homography_estimator:53   bb[0] <= 6 or bb[2] >= size[0] - 6      → marge 6 px
    prediction_adapter:211    bb[0] <= 8 or bb[2] >= iw - 8           → marge 8 px
    multicam_tracker          l'infère de `pinhole_ego() is None`, après avoir écarté les
                              autres causes de ce `None` (mesure dégradée, l. 324-326)

⚠ Le troisième raisonnement est CORRECT — je l'avais d'abord cru fautif : le chemin dégradé
re-teste `distance_m` et la bbox, donc seule la cause « coupée au bord » l'atteint. *Lire la
moitié d'un chemin suffit à condamner à tort l'autre moitié.* Ce qui reste vrai, c'est qu'une
même notion vit en trois exemplaires, avec deux valeurs de marge et une version implicite —
donc **aucun levier d'aval ne peut s'y conditionner**.

Ce que ça débloque : un objet dont la bbox rétrécit parce qu'il SORT du champ n'est pas un
objet qui change de forme. Tant que la distinction n'est écrite nulle part, un levier de
« continuité d'aire » pour la conservation d'identité (`CHAINE §H`) ne peut pas exister.

⭐ La marge reste un ARGUMENT : chaque appelant garde la sienne. Unifier 6 et 8 px changerait
le comportement de l'estimateur d'homographie — c'est une décision à mesurer, pas un effet de
bord de refactoring.

Pur : ni Django, ni numpy, ni OpenCV.
"""

#: Marge par défaut (px). Celle de `pinhole_ego`, le consommateur le plus ancien.
DEFAULT_MARGIN_PX = 8.0


def bbox_edges(bbox, width, height, margin_px=DEFAULT_MARGIN_PX):
    """`[x1, y1, x2, y2]` + dimensions d'image → ensemble des bords touchés.

    Rend un `frozenset` parmi `{'left', 'right', 'top', 'bottom'}` — vide si la bbox est
    entièrement à l'intérieur. Une bbox invalide rend l'ensemble vide : *l'absence de mesure
    n'est pas une sortie de champ*, et un appelant qui confondrait les deux prendrait une
    donnée manquante pour un objet qui s'en va.
    """
    if not bbox or len(bbox) < 4:
        return frozenset()
    try:
        x1, y1, x2, y2 = (float(bbox[0]), float(bbox[1]),
                          float(bbox[2]), float(bbox[3]))
        w, h, m = float(width), float(height), float(margin_px)
    except (TypeError, ValueError):
        return frozenset()
    touches = []
    if x1 <= m:
        touches.append('left')
    if x2 >= w - m:
        touches.append('right')
    if y1 <= m:
        touches.append('top')
    if y2 >= h - m:
        touches.append('bottom')
    return frozenset(touches)


def touches_side_edge(bbox, width, height, margin_px=DEFAULT_MARGIN_PX):
    """Bords LATÉRAUX seulement (gauche/droite) — le cas qui tronque l'étendue apparente.

    C'est ce que testent les trois consommateurs historiques : un objet coupé en HAUT reste
    mesurable en largeur (donc son cap au ratio et son centre latéral tiennent), alors qu'un
    objet coupé à GAUCHE ou à DROITE a une largeur et un centre faux. Le bas de bbox, lui,
    est le point de CONTACT SOL : le couper fausse la distance, pas la largeur.
    """
    e = bbox_edges(bbox, width, height, margin_px)
    return bool(e & {'left', 'right'})
