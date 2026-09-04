"""Rotation propre de la caméra estimée depuis le FLUX de points image (ego-motion visuel).

But : donner à la chaîne une mesure de rotation **indépendante du GPS**. Le cap ne vient
aujourd'hui que d'une source, donc rien ne peut le contredire — et il se propage à la
projection sol, aux `world_en` et aux indicateurs sans qu'aucun chiffre ne le signale.

Ce n'est pas une amélioration spéculative : `CAM_ANALYZER_CHAINE_TRAITEMENT.md §[2]` désigne
ce cap comme **LA source d'erreur angulaire dominante** de la chaîne, et la chiffre —
« bearing entre fixes consécutifs → bruité à faible vitesse (±10-25°) », avec un effet de
bras de levier « 8 m × 15° ≈ 2 m d'arc sur les objets ». La complémentarité est structurelle :
le cap GPS se dégrade quand la navette ralentit, la mesure visuelle devient au contraire plus
sûre (recouvrement plus grand, moins de flou de bougé). Chacune est bonne là où l'autre faiblit.

⚠ Corollaire à ne pas perdre : sous 0,30 m de déplacement le cap GPS n'est pas bruité, il est
**TENU au dernier connu** (`ego_pose.py`). Voir `yaw_disagreement` — comparer contre une
constante fabriquerait un désaccord au lieu d'en mesurer un.

**Ce module n'est PAS un SLAM et ne cherche pas à l'être.** Il n'estime ni position, ni
échelle, ni carte : seulement les deux angles de rotation entre deux images. C'est le
sous-problème que le rig permet de traiter honnêtement — un SLAM complet supposerait des
intrinsèques propres par caméra, alors que la résolution utile (~384×248, fx ≈ 134 px) plafonne
déjà la précision, et il ferait doublon avec `homography_estimator` + Depth Pro + Kalman.

Modèle (3 paramètres, moindres carrés) — pour un déplacement court entre deux images :

    Δx = fx·Δlacet   + s·(x − cx)
    Δy = fy·Δtangage + s·(y − cy)

Le premier terme est la ROTATION : elle décale tous les points du même nombre de pixels, où
qu'ils soient dans l'image. Le second est la TRANSLATION vers l'avant : elle écarte les points
du point de fuite, proportionnellement à leur distance à celui-ci. Les deux signatures sont
géométriquement distinctes — c'est ce qui permet de les séparer sans connaître la profondeur.

⚠ **Limite assumée** : `s` ne vaut « une expansion » que si les points suivis sont à des
profondeurs comparables. Sur une scène très étagée (façade proche + fond lointain), `s` absorbe
une moyenne et la rotation reste bonne tant que les points sont répartis autour du point de
fuite. C'est pourquoi la fonction rend `residual_px` et `n_inliers` : un résidu qui monte dit
que le modèle ne tient pas, et l'appelant doit alors écarter la mesure plutôt que l'utiliser.

Le module ne fait AUCUN appariement de points : il consomme des correspondances déjà établies
(Lucas-Kanade, ORB, peu importe). Fonction pure — ni OpenCV, ni image, ni Django.
"""
from __future__ import annotations

import math

_MIN_POINTS = 6          # 3 inconnues : en dessous, l'ajustement n'a plus de marge
_MAX_ITER = 3            # rejets d'aberrants successifs
_OUTLIER_SIGMA = 2.5


def _solve_3x3(a, b):
    """Résout a·x = b (3×3) par élimination de Gauss avec pivot. None si singulier."""
    m = [list(a[i]) + [b[i]] for i in range(3)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(3):
            if r == col:
                continue
            f = m[r][col] / m[col][col]
            for c in range(col, 4):
                m[r][c] -= f * m[col][c]
    return [m[i][3] / m[i][i] for i in range(3)]


def _fit(pairs, fx, fy, cx, cy):
    """Moindres carrés sur (Δlacet, Δtangage, s). Rend (params, residus) ou (None, None)."""
    # Normales de : [fx·yaw + s·(x-cx) - dx]² + [fy·pitch + s·(y-cy) - dy]²
    # Inconnues u = (yaw, pitch, s).
    a = [[0.0] * 3 for _ in range(3)]
    b = [0.0] * 3
    for (x0, y0, x1, y1) in pairs:
        dx, dy = x1 - x0, y1 - y0
        rx, ry = x0 - cx, y0 - cy
        # ligne x : coefficients (fx, 0, rx)
        for i, ci in enumerate((fx, 0.0, rx)):
            for j, cj in enumerate((fx, 0.0, rx)):
                a[i][j] += ci * cj
            b[i] += ci * dx
        # ligne y : coefficients (0, fy, ry)
        for i, ci in enumerate((0.0, fy, ry)):
            for j, cj in enumerate((0.0, fy, ry)):
                a[i][j] += ci * cj
            b[i] += ci * dy

    u = _solve_3x3(a, b)
    if u is None:
        return None, None
    yaw, pitch, s = u
    residus = []
    for (x0, y0, x1, y1) in pairs:
        ex = (fx * yaw + s * (x0 - cx)) - (x1 - x0)
        ey = (fy * pitch + s * (y0 - cy)) - (y1 - y0)
        residus.append(math.hypot(ex, ey))
    return (yaw, pitch, s), residus


def estimate_ego_rotation(matches, focal_px, principal_point=None, *, dt_s=None):
    """Rotation de la caméra entre deux images, depuis des correspondances de points.

    `matches` : itérable de `(x0, y0, x1, y1)` en pixels — un point de l'image A et son
    homologue dans l'image B. Ne doit contenir que des points du DÉCOR (les points portés par
    des objets mobiles violent le modèle ; les écarter est le travail de l'appelant, qui seul
    connaît les bbox).

    `focal_px` : focale en pixels, scalaire ou `(fx, fy)`.
    `principal_point` : `(cx, cy)`, centre optique. Par défaut (0, 0) — passer le vrai centre
    image change le résultat, ce n'est pas un détail cosmétique.
    `dt_s` : si fourni, les vitesses angulaires sont ajoutées en °/s.

    Rend un dict, ou None si la mesure n'est pas exploitable :
      `yaw_deg`     — lacet de la CAMÉRA, **positif vers la DROITE** (convention des caps du
                      projet : nord = 0, sens horaire), donc comparable tel quel à une
                      dérivée de `bearing_deg`. Un virage à droite fait défiler le décor
                      vers la gauche : le signe est inversé à la sortie, voir plus bas.
      `pitch_deg`   — tangage de la caméra, **positif nez en l'air** (le décor descend
                      alors dans l'image, dont l'axe y pointe vers le bas).
      `expansion`   — terme d'expansion radiale (sans unité) : > 0 en marche avant.
      `n_inliers`   — points retenus après rejet des aberrants.
      `residual_px` — résidu médian. **Le juge de la mesure** : au-delà de ~1-2 px le modèle
                      ne décrit plus la scène (objets mobiles restants, profondeurs trop
                      étagées, appariements faux) et la rotation ne doit pas être utilisée.
      `yaw_rate_dps` / `pitch_rate_dps` — présents seulement si `dt_s` est fourni.
    """
    pairs = [tuple(float(v) for v in m[:4]) for m in matches]
    if len(pairs) < _MIN_POINTS:
        return None

    fx, fy = (focal_px if isinstance(focal_px, (tuple, list)) else (focal_px, focal_px))
    if not fx or not fy:
        return None
    cx, cy = principal_point or (0.0, 0.0)

    params, residus = _fit(pairs, fx, fy, cx, cy)
    if params is None:
        return None

    # Rejet itératif : les appariements faux sont rares mais très écartés, et un seul
    # suffit à tirer un moindre carré. Le seuil se dérive des résidus eux-mêmes.
    for _ in range(_MAX_ITER):
        med = sorted(residus)[len(residus) // 2]
        # Écart absolu médian → seuil robuste, insensible aux aberrants qu'il traque.
        mad = sorted(abs(r - med) for r in residus)[len(residus) // 2]
        seuil = med + _OUTLIER_SIGMA * max(mad, 0.5)
        gardes = [p for p, r in zip(pairs, residus) if r <= seuil]
        if len(gardes) == len(pairs) or len(gardes) < _MIN_POINTS:
            break
        pairs = gardes
        params, residus = _fit(pairs, fx, fy, cx, cy)
        if params is None:
            return None

    yaw, pitch, s = params
    # ⚠ SIGNE — le seul endroit où il se pose, et il n'est pas neutre.
    # Le paramètre ajusté décrit le déplacement des POINTS ; le cap décrit celui de la
    # CAMÉRA, et les deux sont opposés : quand la caméra tourne à droite, le décor défile
    # vers la gauche (Δx < 0). On renvoie donc l'opposé, pour que `yaw_deg > 0` signifie
    # « virage à droite » — la convention des caps du projet (nord = 0, sens horaire),
    # donc directement comparable à une dérivée de `bearing_deg` GPS.
    # Une inversion ici ne lèverait rien : elle rendrait juste tous les désaccords doubles.
    out = {
        'yaw_deg': math.degrees(-yaw),
        'pitch_deg': math.degrees(pitch),
        'expansion': s,
        'n_inliers': len(pairs),
        'residual_px': round(sorted(residus)[len(residus) // 2], 3),
    }
    if dt_s:
        out['yaw_rate_dps'] = out['yaw_deg'] / dt_s
        out['pitch_rate_dps'] = out['pitch_deg'] / dt_s
    return out


def yaw_disagreement(visual_yaw_rate_dps, reference_yaw_rate_dps, *,
                     reference_held=False):
    """Écart entre le lacet VU et le lacet de RÉFÉRENCE, en °/s — la métrique A/B.

    Sépare volontairement le calcul de la mesure : c'est ce chiffre qui dit si le cap de
    référence est fiable sur un tronçon, et non un jugement porté sur une superposition
    d'images. Un désaccord qui enfle en canyon urbain est le symptôme attendu (multitrajet) ;
    un désaccord constant signe plutôt une erreur d'étalonnage ou de convention de signe.

    ⚠ **`reference_held` n'est pas une option de confort — sans lui la métrique MENT.**
    Le cap dérivé du GPS n'est pas seulement bruité à basse vitesse : sous 0,30 m de
    déplacement il est **TENU au dernier connu** (`ego_pose.annotate_gps_heading_speed`,
    « aucun gyroscope »). Ce n'est alors plus une mesure mais une CONSTANTE, dont la dérivée
    vaut 0 par construction. Comparer le lacet vu à cette constante rend un désaccord
    exactement égal au lacet vu — c'est-à-dire un artefact du gel, présenté comme une erreur
    de cap. À l'arrêt et en manœuvre lente, c'est-à-dire **précisément là où la vision est la
    plus fiable et le GPS le moins**, la métrique serait donc maximalement fausse.

    C'est le même piège que le gap G7 sur le placement (`CHAINE §[4]` : un A/B qui mélange
    homographie et repli pinhole silencieux compare deux choses qui ne sont pas comparables).
    On rend `None` plutôt qu'un chiffre : une absence se voit, un faux chiffre non.

    Note : un cap issu de l'API navette (`EgoPose.source == 'shuttle_api'`) reste fiable à
    l'arrêt — pour lui `reference_held` vaut False même immobile. D'où un paramètre porté par
    l'APPELANT, qui seul connaît la source, plutôt qu'un seuil de vitesse deviné ici.
    """
    if visual_yaw_rate_dps is None or reference_yaw_rate_dps is None:
        return None
    if reference_held:
        return None
    return abs(visual_yaw_rate_dps - reference_yaw_rate_dps)


def ego_rotation(matches: 'TypedFrame', *, focal_px=None, principal_point=None,
                 dt_s=None) -> 'TypedFrame':
    """Wrapper FunctionSpec : lit un `TypedFrame` de correspondances, rend un `TypedFrame`.

    Deux étages, comme `placement_metrics` : `estimate_ego_rotation` est le NOYAU, utilisable
    hors serveur sur des tuples ; ce wrapper est ce que le catalogue appelle. C'est lui qui
    honore le contrat `pure` — `apply()` (`wama_data/view.py`) invoque `spec.fn(entrée_typée,
    **params)` et range un `TypedFrame` : un `fn` qui prendrait des tuples et rendrait un dict
    casserait à l'exécution, alors même que son manifeste s'annonce chaînable.

    Sortie SCALAR = le lacet (l'indicateur qu'on compare au GPS) ; tangage, expansion, nombre
    d'inliers et résidu vont dans `meta` — diagnostic, pas mesure. `meta['usable']` reprend le
    verdict du résidu : au-delà de 2 px le modèle ne décrit plus la scène.
    """
    import pandas as pd
    from wama.common.catalog.data_types import TypedFrame as _TF, DataType as _DT

    df = matches.df if hasattr(matches, 'df') else matches
    paires = [(r['x0'], r['y0'], r['x1'], r['y1']) for _, r in df.iterrows()]
    res = estimate_ego_rotation(paires, focal_px, principal_point, dt_s=dt_s)
    if res is None:
        return _TF(pd.DataFrame([{'metric': 'ego_yaw_deg', 'value': None}]), _DT.SCALAR,
                   meta={'usable': False, 'reason': 'trop peu de points ou focale absente'})
    out = pd.DataFrame([{'metric': 'ego_yaw_deg', 'value': res['yaw_deg']}])
    return _TF(out, _DT.SCALAR, meta={**res, 'usable': res['residual_px'] <= 2.0})


# ── Manifeste ─────────────────────────────────────────────────────────────────────────
from wama.common.catalog.function_catalog import (  # noqa: E402
    FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from wama.common.catalog.data_types import DataType  # noqa: E402

SPEC = register(FunctionSpec(
    key='ego_rotation',
    name='Rotation propre par flux de points',
    description="Estime le lacet et le tangage de la caméra entre deux images à partir de "
                "correspondances de points du décor, en séparant la rotation (décalage "
                "uniforme) de la translation avant (expansion radiale). Source de cap "
                "INDÉPENDANTE du GPS : c'est le désaccord entre les deux qui se mesure. "
                "N'est pas un SLAM — ni position, ni échelle, ni carte.",
    category=FunctionCategory.ENRICHER,
    tags=['vision', 'geometry', 'ego-motion', 'ab-metric', 'no-ground-truth'],
    inputs=[PortSpec('matches', DataType.TABLE,
                     required_fields=['x0', 'y0', 'x1', 'y1'],
                     description='Correspondances de points du DÉCOR entre deux images.')],
    outputs=[PortSpec('ego_rotation', DataType.SCALAR,
                      produced_fields=['metric', 'value'],
                      description="Lacet caméra (°, positif à droite) ; tangage, expansion, "
                                  "inliers et résidu dans meta.")],
    params=[
        ParamSpec('focal_px', 'float', None, 1.0, 10000.0, unit='px',
                  description='Focale en pixels (fx, ou fx=fy).'),
        ParamSpec('dt_s', 'float', None, 0.0, 10.0, unit='s',
                  description='Intervalle entre les deux images, pour obtenir des °/s.'),
    ],
    cost={'cpu_bound': True},
    fn=ego_rotation,
))
