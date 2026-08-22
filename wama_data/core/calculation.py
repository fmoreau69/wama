"""
Calculator — DEUX modes de calcul sur des signaux temporels.

    ① COLONNES DÉRIVÉES   signal → signal   (moyenne glissante, dérivée, cumul)
    ② INDICATEURS PAR SEGMENT   `segments` + signal → indicateurs   (un jeu de valeurs par segment)

Les deux partagent **un seul vocabulaire de statistiques** (`STATISTIQUES`). C'est le point de
conception : « moyenne » doit vouloir dire la même chose dans une fenêtre glissante et dans un
segment, sinon deux tableaux du même corpus cessent d'être comparables sans que rien ne le dise.
Ajouter une statistique la rend donc disponible AUX DEUX modes, par construction.

CE MODULE EST PUR — listes de flottants, aucune dépendance à pandas ni à Django. Les adaptateurs
de ports (`wama_data/functions/temporal/calculation.py`) font la conversion depuis/vers
`TypedFrame`. Même partage que `core/segmentation.py` ↔ `functions/temporal/segmentation.py`.

TROIS DÉCISIONS QUI NE SONT PAS DES DÉTAILS

  1. **La fenêtre se déclare en SECONDES, jamais en nombre d'échantillons.** WAMA Data existe pour
     aligner des flux à cadences incommensurables (`core/temporal.py`) : « 50 échantillons » ne
     désigne pas la même durée d'un flux à l'autre, et la même chaîne appliquée à deux corpus
     donnerait des résultats non comparables. Une durée, elle, est intrinsèque.

  2. **Une agrégation sans donnée rend `None`, jamais `0`.** La moyenne de rien n'est pas zéro.
     C'est la faute qui remplit une colonne de zéros crédibles là où il n'y avait pas de mesure —
     et personne ne la voit, parce que zéro est une valeur plausible.

  3. **Un segment OUVERT n'a pas de durée observée.** `duree` y vaut `None` et l'indicateur porte
     `tronque=True`. La doctrine vient du codage comportemental (`core/coding.py`) : une durée
     refermée par la fin de l'enregistrement n'est pas une durée mesurée, et les confondre fausse
     toute statistique de durée. Le Calculator hérite de la règle au lieu de la re-trancher.

CE QUI N'EST DÉLIBÉRÉMENT PAS ICI — le « temps passé au-dessus d'un seuil ». Il ne demande aucune
brique neuve : `segments_conditionnels` produit déjà les plages où le prédicat tient, et leur durée
est un indicateur de ce module. L'écrire ici en dupliquerait le seuil et l'hystérésis.
"""
from __future__ import annotations

import statistics as _stats
from bisect import bisect_left, bisect_right
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .valeurs import manquant, presentes

#: Fin inconnue — importé du Segmenter plutôt que redéfini : c'est le MÊME `None`.
from .segmentation import OUVERT  # noqa: F401  (réexporté : un calcul sur segments en parle)


def _ecart_type(vals: List[float]) -> float:
    # Écart-type d'ÉCHANTILLON (n-1) : on mesure un phénomène à travers un échantillon de points,
    # pas une population exhaustive. Exige 2 points — d'où son minimum déclaré ci-dessous.
    return _stats.stdev(vals)


#: Vocabulaire COMMUN aux deux modes : nom → (calcul, nombre minimal de valeurs présentes).
#: Le minimum est déclaré et non codé dans les appelants — c'est lui qui décide `None` vs valeur,
#: et le laisser à chaque appelant produirait deux réponses différentes pour la même question.
STATISTIQUES: Dict[str, Tuple[Callable[[List[float]], Any], int]] = {
    'moyenne':    (lambda v: _stats.fmean(v), 1),
    'mediane':    (lambda v: _stats.median(v), 1),
    'min':        (min, 1),
    'max':        (max, 1),
    'somme':      (lambda v: float(sum(v)), 1),
    'etendue':    (lambda v: max(v) - min(v), 1),
    'premier':    (lambda v: v[0], 1),
    'dernier':    (lambda v: v[-1], 1),
    # `delta` a besoin de deux points : avec un seul il vaudrait 0, ce qui se lirait « pas de
    # variation » alors qu'on n'a rien pu observer.
    'delta':      (lambda v: v[-1] - v[0], 2),
    'ecart_type': (_ecart_type, 2),
    # `nombre` est le seul défini sur l'ensemble vide : compter zéro mesure est une réponse.
    'nombre':     (len, 0),
}

#: Statistique par défaut — celle que l'on veut dans l'immense majorité des cas.
DEFAUT = 'moyenne'


def _verifier(nom: str) -> Tuple[Callable, int]:
    try:
        return STATISTIQUES[nom]
    except KeyError:
        raise ValueError(
            f"statistique '{nom}' inconnue (disponibles : {', '.join(sorted(STATISTIQUES))})")


def appliquer(nom: str, valeurs: Sequence[Any]) -> Optional[float]:
    """UNE statistique sur des valeurs éventuellement absentes. `None` si le minimum n'est pas tenu.

    Point de passage unique des deux modes : c'est ce qui garantit que « moyenne » signifie la
    même chose dans une fenêtre glissante et dans un segment.
    """
    calcul, minimum = _verifier(nom)
    vals = presentes(valeurs)
    if len(vals) < minimum:
        return None
    return calcul(vals)


def _croissants(times: Sequence[float]) -> None:
    """Le tri des temps est une PRÉCONDITION, pas une commodité.

    Les deux modes indexent la fenêtre par dichotomie : sur des temps désordonnés le résultat
    serait faux SANS ERREUR — la pire des sorties. On refuse plutôt que de trier en douce, car
    trier ici désolidariserait silencieusement les temps de la colonne de valeurs de l'appelant.
    """
    for i in range(1, len(times)):
        if times[i] < times[i - 1]:
            raise ValueError(
                f"temps non croissants à l'indice {i} ({times[i]} < {times[i - 1]}) — "
                "aligner le flux (voir core/temporal.py) avant de calculer")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ① COLONNES DÉRIVÉES — signal → signal, même longueur, mêmes temps
# ══════════════════════════════════════════════════════════════════════════════════════════════

def glissant(times: Sequence[float], valeurs: Sequence[Any], fenetre_s: float,
             statistique: str = DEFAUT, *, centre: bool = True,
             min_points: int = 1) -> List[Optional[float]]:
    """Statistique sur une fenêtre GLISSANTE exprimée en secondes.

    `centre=True`  → fenêtre `[t − f/2, t + f/2]` : c'est le lissage d'ANALYSE, sans déphasage.
    `centre=False` → fenêtre `[t − f, t]` : fenêtre CAUSALE, la seule licite quand le résultat
    doit pouvoir être produit en temps réel (elle ne lit pas l'avenir).

    Le choix n'est pas cosmétique : une fenêtre centrée appliquée à un signal destiné à déclencher
    quelque chose ferait dépendre la décision d'échantillons postérieurs à elle.

    `min_points` exige un minimum d'échantillons PRÉSENTS dans la fenêtre — sans lui, un trou de
    données produit une valeur calculée sur un seul point, indiscernable d'une vraie mesure.

    Rend une liste de la longueur de `times` : la colonne reste alignée sur le signal d'origine,
    ce qui est la condition pour l'y adjoindre.
    """
    if fenetre_s <= 0:
        raise ValueError("la fenêtre doit être une durée strictement positive (en secondes)")
    _verifier(statistique)
    _croissants(times)
    if len(times) != len(valeurs):
        raise ValueError(f"temps et valeurs de longueurs différentes ({len(times)} ≠ {len(valeurs)})")

    avant, apres = (fenetre_s / 2.0, fenetre_s / 2.0) if centre else (fenetre_s, 0.0)
    ts = list(times)
    sortie: List[Optional[float]] = []
    for i, t in enumerate(ts):
        # Bornes INCLUSIVES des deux côtés — même convention que `chevauche` du Segmenter.
        lo = bisect_left(ts, t - avant)
        hi = bisect_right(ts, t + apres)
        fenetre = presentes(valeurs[lo:hi])
        if len(fenetre) < max(1, min_points):
            sortie.append(None)
            continue
        sortie.append(appliquer(statistique, fenetre))
    return sortie


def derivee(times: Sequence[float], valeurs: Sequence[Any]) -> List[Optional[float]]:
    """Taux de variation instantané (unité/seconde), par différence CENTRÉE quand c'est possible.

    Différence centrée à l'intérieur `(v[i+1] − v[i−1]) / (t[i+1] − t[i−1])`, décentrée aux bords.
    C'est le compromis usuel : la centrée est d'ordre 2 (deux fois plus précise que la décentrée)
    et surtout elle n'introduit pas de déphasage d'un demi-pas.

    `None` partout où le calcul n'a pas de sens : voisin absent, ou deux échantillons au MÊME
    instant (division par zéro). Un signal à cadence irrégulière en contient — les taire donnerait
    des `inf` qui contaminent toute statistique en aval.
    """
    _croissants(times)
    if len(times) != len(valeurs):
        raise ValueError(f"temps et valeurs de longueurs différentes ({len(times)} ≠ {len(valeurs)})")
    n = len(times)
    if n < 2:
        return [None] * n

    sortie: List[Optional[float]] = []
    for i in range(n):
        g, d = (i - 1, i + 1) if 0 < i < n - 1 else ((i, i + 1) if i == 0 else (i - 1, i))
        dt = times[d] - times[g]
        if dt <= 0 or manquant(valeurs[g]) or manquant(valeurs[d]):
            sortie.append(None)
            continue
        sortie.append((valeurs[d] - valeurs[g]) / dt)
    return sortie


def cumul(times: Sequence[float], valeurs: Sequence[Any]) -> List[Optional[float]]:
    """Intégrale cumulée par la méthode des trapèzes (aire sous le signal, unité × seconde).

    À l'indice `i` : l'aire accumulée de `times[0]` à `times[i]`. Le premier point vaut donc `0.0`
    — l'intégrale d'un instant à lui-même, quelle que soit la valeur du signal (y compris absente).

    Un intervalle dont l'une des bornes manque n'apporte RIEN et le cumul se maintient : c'est le
    choix honnête. L'alternative — interpoler par-dessus le trou — inventerait de l'aire, et rien
    dans la sortie ne dirait qu'elle a été inventée.
    """
    _croissants(times)
    if len(times) != len(valeurs):
        raise ValueError(f"temps et valeurs de longueurs différentes ({len(times)} ≠ {len(valeurs)})")
    if not times:
        return []

    aire = 0.0
    sortie: List[Optional[float]] = [0.0]
    for i in range(1, len(times)):
        dt = times[i] - times[i - 1]
        if dt > 0 and not manquant(valeurs[i - 1]) and not manquant(valeurs[i]):
            aire += (valeurs[i - 1] + valeurs[i]) / 2.0 * dt
        sortie.append(aire)
    return sortie


# ══════════════════════════════════════════════════════════════════════════════════════════════
# ② INDICATEURS PAR SEGMENT — `segments` + signal → un jeu de valeurs par segment
# ══════════════════════════════════════════════════════════════════════════════════════════════

#: Champs de service ajoutés à CHAQUE jeu d'indicateurs, en plus des statistiques demandées.
#: Ils ne sont pas optionnels : sans eux un `None` est indéchiffrable — pas de mesure dans la
#: fenêtre, ou fenêtre jamais refermée ? Les deux se corrigent différemment.
CHAMPS_DE_SERVICE = ('n', 'duree', 'tronque')


def echantillons_du_segment(segment: Dict[str, Any], times: Sequence[float],
                            valeurs: Sequence[Any]) -> List[Any]:
    """Valeurs (présentes ou non) dont le temps tombe dans `[start, end]`, bornes INCLUSES.

    Une fin inconnue (`end is None`) vaut `+∞` — exactement la convention du Segmenter
    (`present_dans`, `chevauche`). Un état encore ouvert agrège donc jusqu'au dernier échantillon
    disponible ; c'est `tronque` qui dit que le résultat est partiel.
    """
    debut = segment['start']
    fin = segment.get('end')
    fin = float('inf') if manquant(fin) else fin
    ts = list(times)
    return list(valeurs[bisect_left(ts, debut):bisect_right(ts, fin)])


def par_segment(segments: Sequence[Dict[str, Any]], times: Sequence[float], valeurs: Sequence[Any],
                statistiques: Sequence[str] = (DEFAUT,)) -> List[Dict[str, Any]]:
    """Un jeu d'indicateurs PAR SEGMENT, dans l'ordre reçu.

    Rend une liste de dicts — les indicateurs SEULS, sans recopier le segment. L'adjonction aux
    segments est le travail de l'adaptateur : le cœur ne décide pas de la forme du tableau final.

    Chaque jeu porte, outre les statistiques demandées :
      `n`        nombre d'échantillons PRÉSENTS (0 = le segment ne couvre aucune mesure) ;
      `duree`    `end − start`, ou `None` si le segment est ouvert — voir la décision 3 en tête ;
      `tronque`  vrai si le segment est ouvert, donc agrégé sur un intervalle incomplet.

    Un segment sans échantillon ne fait pas échouer le calcul : ses statistiques valent `None` et
    `n` vaut 0. C'est un résultat légitime (la mesure n'a pas couvert cette plage) et le taire
    obligerait l'appelant à réaligner deux listes de longueurs différentes.
    """
    for nom in statistiques:
        _verifier(nom)
    _croissants(times)
    if len(times) != len(valeurs):
        raise ValueError(f"temps et valeurs de longueurs différentes ({len(times)} ≠ {len(valeurs)})")

    sortie: List[Dict[str, Any]] = []
    for segment in segments:
        dans = echantillons_du_segment(segment, times, valeurs)
        vals = presentes(dans)
        ouvert = manquant(segment.get('end'))
        jeu: Dict[str, Any] = {
            'n': len(vals),
            'duree': None if ouvert else segment['end'] - segment['start'],
            'tronque': ouvert,
        }
        for nom in statistiques:
            jeu[nom] = appliquer(nom, vals)
        sortie.append(jeu)
    return sortie
