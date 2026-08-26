"""
Segmenter — produit des `segments` à partir d'événements, de signaux ou d'un codage.

CE MODULE NE RÉINVENTE RIEN. Sa spécification (`WAMA_DATA_WORLD.md §9ter`) vient de la
confrontation de trois systèmes éprouvés sur de vraies campagnes : un outil d'exploitation MATLAB
(la combinatoire simple/double, « présent dans », le filtrage), une toolbox tierce (l'hystérésis —
durée minimale et trou toléré), et un logiciel de codage comportemental (le segment OUVERT et le
vocabulaire de l'éthogramme). Le travail fait ici est de les TRADUIRE dans le vocabulaire typé de
WAMA, pas de les redécouvrir.

DEUX POINTS OÙ MON MODÈLE INITIAL ÉTAIT FAUX, corrigés par la lecture du code d'origine :
  • une ancre donne **DEUX offsets indépendants**, pas une durée. Sans cela on ne peut pas exprimer
    une fenêtre qui commence APRÈS l'ancre (« de +15 s à +45 s ») — or c'est un cas courant.
  • un segment peut naître de la **jonction de DEUX flux** : début pris dans l'un, fin dans l'autre.
    C'est ce qui produit « du début du bloc à la pause suivante ».

VOCABULAIRE : `segment` est le MODÈLE ; l'utilisateur lit « situation » ou « état ».
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

#: Un segment produit : bornes + attributs libres (l'origine y est toujours tracée).
Segment = Dict[str, Any]

#: Fin inconnue — un état commencé et pas encore fermé. Représenté par `None`, pas par une
#: convention numérique : un sentinelle (0, -1, l'infini) finit toujours par être calculée comme
#: une vraie borne quelque part.
OUVERT = None


def _tri(segments: List[Segment]) -> List[Segment]:
    return sorted(segments, key=lambda s: (s['start'], s['end'] if s['end'] is not None else float('inf')))


def _tracer(seg: Segment, origine: str, **details) -> Segment:
    """Toute production porte son ORIGINE. Sans elle, impossible de distinguer plus tard un
    segment codé par un humain d'un segment proposé par un modèle — or c'est exactement ce qu'il
    faudra savoir pour valider un codage assisté."""
    seg['origin'] = origine
    for k, v in details.items():
        if v is not None:
            seg[k] = v
    return seg


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 1. Autour d'une ANCRE — deux offsets indépendants
# ──────────────────────────────────────────────────────────────────────────────────────────────

def autour(ancres: Sequence[float], offset_debut: float, offset_fin: float,
           *, nom: str = '', attributs: Optional[Sequence[dict]] = None) -> List[Segment]:
    """`start = ancre + offset_debut`, `end = ancre + offset_fin`.

    Les deux offsets sont INDÉPENDANTS et peuvent être tous deux positifs : « de +15 s à +45 s
    après l'événement » est un cas normal, pas une bizarrerie. C'est la forme qui engendre des
    familles de fenêtres emboîtées ou glissantes sur la même ancre.
    """
    if offset_fin < offset_debut:
        raise ValueError("offset_fin doit être ≥ offset_debut")
    out: List[Segment] = []
    for i, a in enumerate(ancres):
        seg = {'start': a + offset_debut, 'end': a + offset_fin}
        if nom:
            seg['name'] = f"{nom}_{i + 1:02d}"
        if attributs and i < len(attributs):
            seg.update(attributs[i])
        out.append(_tracer(seg, 'autour', anchor=a,
                           window=f"{offset_debut:g}_{offset_fin:g}"))
    return out


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 2. JONCTION de deux flux — le mode que j'avais manqué
# ──────────────────────────────────────────────────────────────────────────────────────────────

def jonction(debuts: Sequence[float], fins: Sequence[float], *, nom: str = '',
             depuis_debut: int = 0, depuis_fin: int = 0,
             offset_debut: float = 0.0, offset_fin: float = 0.0,
             repeter: bool = True,
             fermer_dernier: bool = False) -> List[Segment]:
    """Apparie le i-ème début avec la première fin qui le SUIT.

    ⚠ L'appariement se fait par l'ordre temporel, pas par index : deux flux indépendants n'ont
    aucune raison d'avoir le même nombre d'occurrences ni de s'alterner proprement. Prendre
    `fins[i]` en face de `debuts[i]` produirait des segments à durée négative dès qu'une occurrence
    manque — défaut silencieux et difficile à voir sur un tracé.

    ⚠ CE CHOIX EST CONFIRMÉ PAR LE CODE D'ORIGINE, qui fait l'inverse et en paie le prix. Son
    `appliquer_prochainSeg` apparie bien par INDEX (`startTimecodes = tc1; endTimecodes = tc2;`)
    et, quand les deux tables n'ont pas le même nombre d'occurrences, n'a d'autre recours que de
    refuser en renvoyant l'utilisateur au filtrage manuel : « Impossible de répéter sur les
    prochains segments puisque la taille des tableaux sont differents. Veuillez filtrer les
    tables. » L'appariement temporel n'a pas ce cas d'échec.

    `depuis_debut` / `depuis_fin` sautent les premières occurrences de chaque flux (l'outil
    d'origine expose exactement ces deux curseurs, `tddAvant` / `tddApres`).

    `offset_debut` / `offset_fin` décalent les DEUX bornes indépendamment, comme le fait la
    segmentation temporelle double d'origine (`Table 1 + offset`, `Table 2 + offset`). Sans eux,
    « du début du bloc moins 2 s jusqu'à la pause suivante plus 5 s » n'était pas exprimable.

    `repeter=True` (défaut) produit un segment par début — c'est le comportement historique de
    cette fonction. `repeter=False` n'en produit qu'UN, celui des curseurs : c'est le mode par
    défaut de l'outil d'origine, où « Répéter sur les prochains segments » est une case à cocher.
    Le défaut est inversé ici À DESSEIN — produire toute la série est le cas courant d'une analyse,
    et le cas particulier mérite d'être demandé plutôt que subi.

    `fermer_dernier=False` : un début sans fin postérieure donne un segment **OUVERT** plutôt
    qu'un segment jeté. Perdre le dernier état d'une session est une perte de donnée, pas une
    simplification.
    """
    d = sorted(debuts)[depuis_debut:]
    f = sorted(fins)[depuis_fin:]
    if not repeter:
        d = d[:1]
    out: List[Segment] = []
    for i, t0 in enumerate(d):
        j = bisect_right(f, t0)
        t1 = f[j] if j < len(f) else OUVERT
        if t1 is OUVERT and fermer_dernier:
            continue
        # Les offsets s'appliquent APRÈS l'appariement : les décaler avant changerait quelle fin
        # suit quel début, donc l'appariement lui-même. Un décalage de bornes ne doit pas modifier
        # la structure de ce qui a été apparié.
        seg = {'start': t0 + offset_debut,
               'end': OUVERT if t1 is OUVERT else t1 + offset_fin}
        if nom:
            seg['name'] = f"{nom}_{i + 1:02d}"
        out.append(_tracer(seg, 'jonction', open=(t1 is OUVERT),
                           window=(f"{offset_debut:g}_{offset_fin:g}"
                                   if (offset_debut or offset_fin) else None)))
    return out


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 3. CONDITIONNELLE — prédicat + hystérésis
# ──────────────────────────────────────────────────────────────────────────────────────────────

def conditionnelle(times: Sequence[float], masque: Sequence[bool], *,
                   duree_min: float = 0.0, trou_tolere: float = 0.0,
                   nom: str = '') -> List[Segment]:
    """Plages où le masque est vrai, avec DURÉE MINIMALE et TROU TOLÉRÉ.

    L'hystérésis n'est pas un raffinement : sans elle, un seuil sur un signal réel produit du
    confetti — des centaines de micro-segments dus au bruit. `trou_tolere` recolle deux plages
    séparées par une courte interruption ; `duree_min` écarte ce qui reste trop bref.
    (Emprunté à une toolbox tierce, où ce sont les deux seuls paramètres jugés indispensables.)
    """
    if len(times) != len(masque):
        raise ValueError("times et masque doivent avoir la même longueur")
    brutes: List[List[float]] = []
    debut = None
    for i, actif in enumerate(masque):
        if actif and debut is None:
            debut = times[i]
        elif not actif and debut is not None:
            brutes.append([debut, times[i - 1] if i else debut])
            debut = None
    if debut is not None:
        brutes.append([debut, times[-1]])

    # Recollage des plages séparées par un trou plus court que toléré.
    fusionnees: List[List[float]] = []
    for plage in brutes:
        if fusionnees and (plage[0] - fusionnees[-1][1]) <= trou_tolere:
            fusionnees[-1][1] = plage[1]
        else:
            fusionnees.append(plage)

    out: List[Segment] = []
    for i, (t0, t1) in enumerate([p for p in fusionnees if (p[1] - p[0]) >= duree_min]):
        seg = {'start': t0, 'end': t1}
        if nom:
            seg['name'] = f"{nom}_{i + 1:02d}"
        out.append(_tracer(seg, 'conditionnelle',
                           min_duration=duree_min or None,
                           max_gap=trou_tolere or None))
    return out


def masque_hysteresis(valeurs: Sequence[Any], seuil_entree: float, seuil_sortie: float,
                      *, operateur: str = '<=') -> List[bool]:
    """Masque à DEUX SEUILS — on entre à `seuil_entree`, on ne sort qu'à `seuil_sortie`.

    C'est le déclencheur de Schmitt, et c'est la réponse classique au tremblement d'une mesure
    autour d'une frontière. `conditionnelle()` porte déjà une hystérésis **de TEMPS**
    (`duree_min`, `trou_tolere`) ; celle-ci est l'hystérésis **de VALEUR**, qui lui manquait.

    ⚠ ELLE VIENT D'UNE MESURE, PAS D'UNE INTUITION (2026-08-23). `cam_analyzer` calcule des
    fenêtres de proximité autour d'un carrefour et fusionne ensuite deux fenêtres consécutives
    « si la navette n'a jamais dépassé `exit_distance_factor × radius` pendant l'écart » —
    c'est-à-dire si elle n'est jamais vraiment sortie. Sans ce mécanisme, porter cam_analyzer sur
    le Segmenter serait une RÉGRESSION : un GPS qui tremble sur la frontière découperait un
    passage unique en confettis.

    ⚠ CE N'EST PAS BIT-À-BIT L'ÉQUIVALENT DE SA FUSION A POSTERIORI, et il faut le dire : lui
    OUVRE deux fenêtres puis les recolle ; le déclencheur de Schmitt n'en ouvre jamais qu'une. Les
    deux coïncident dans le cas courant et diffèrent aux bords (une sortie franche suivie d'un
    retour immédiat). La forme en flux est la bonne généralisation — elle ne demande pas de
    connaître l'avenir.

    `operateur` dit de quel côté est « dedans » :
      `'<='` — dedans quand la valeur est PETITE (une distance) ; `seuil_sortie ≥ seuil_entree`.
      `'>='` — dedans quand la valeur est GRANDE (une vitesse) ; `seuil_sortie ≤ seuil_entree`.

    Une valeur ABSENTE ne décide de rien : elle **maintient l'état courant**. C'est le choix
    honnête — un trou GPS n'est ni une entrée ni une sortie, et le traiter comme « dehors »
    couperait un passage à chaque perte de fix.
    """
    if operateur not in ('<=', '>='):
        raise ValueError(f"opérateur '{operateur}' : attendu '<=' (dedans = petit) "
                         "ou '>=' (dedans = grand)")
    if operateur == '<=' and seuil_sortie < seuil_entree:
        raise ValueError(
            f"hystérésis incohérente : avec '<=', on sort PLUS LOIN qu'on entre, donc "
            f"seuil_sortie ({seuil_sortie}) doit être ≥ seuil_entree ({seuil_entree})")
    if operateur == '>=' and seuil_sortie > seuil_entree:
        raise ValueError(
            f"hystérésis incohérente : avec '>=', on sort PLUS BAS qu'on entre, donc "
            f"seuil_sortie ({seuil_sortie}) doit être ≤ seuil_entree ({seuil_entree})")

    dedans = False
    out: List[bool] = []
    for v in valeurs:
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            out.append(dedans)          # absence : on maintient l'état
            continue
        if operateur == '<=':
            dedans = (v <= seuil_entree) if not dedans else (v <= seuil_sortie)
        else:
            dedans = (v >= seuil_entree) if not dedans else (v >= seuil_sortie)
        out.append(dedans)
    return out


def bascules(times: Sequence[float], masque: Sequence[bool], *,
             montantes: bool = True, descendantes: bool = False,
             nom: str = '') -> List[Dict[str, Any]]:
    """Instants où le masque CHANGE d'état — le second port de sortie d'une condition.

    C'est la traduction du choix « Que créer ? Event | Situation » de l'outil d'origine, où il est
    un bouton radio au milieu du geste de segmentation. Ici les deux sorties sont deux fonctions
    qui consomment le MÊME masque (`conditionnelle()` pour les plages, celle-ci pour les instants) :
    le mode de production ne décide plus de la nature du produit. C'est ce que veut dire « la
    sortie est un PORT, pas un mode » (§9ter.6 B4).

    Rend des ÉVÉNEMENTS (`time`), pas des segments : une bascule n'a pas de durée. Chacune porte
    `edge` (`'montante'` / `'descendante'`), sans quoi deux bascules successives seraient
    indiscernables alors qu'elles disent le contraire l'une de l'autre.

    ⚠ Un masque vrai DÈS le premier échantillon ne produit pas de bascule montante : on n'a pas
    observé la transition, on a trouvé la condition déjà satisfaite. L'inventer daterait un
    changement d'état au début de l'enregistrement — c'est-à-dire à un instant choisi par
    l'acquisition, pas par le phénomène.
    """
    if len(times) != len(masque):
        raise ValueError("times et masque doivent avoir la même longueur")
    out: List[Dict[str, Any]] = []
    for i in range(1, len(masque)):
        avant, apres = bool(masque[i - 1]), bool(masque[i])
        if avant == apres:
            continue
        sens = 'montante' if apres else 'descendante'
        if (sens == 'montante' and not montantes) or (sens == 'descendante' and not descendantes):
            continue
        ev: Dict[str, Any] = {'time': times[i], 'edge': sens}
        if nom:
            ev['name'] = f"{nom}_{len(out) + 1:02d}"
        ev['origin'] = 'bascule'
        out.append(ev)
    return out


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 4. ÉTATS — plages de valeur constante d'un signal catégoriel
# ──────────────────────────────────────────────────────────────────────────────────────────────

def etats(times: Sequence[float], valeurs: Sequence[Any], *,
          ignorer: Iterable[Any] = (), nom: str = '') -> List[Segment]:
    """Découpe un signal catégoriel en segments de valeur constante (run-length).

    C'est la forme IMPLICITE d'un segment : l'utilisateur voit « un état », la donnée n'est qu'une
    colonne échantillonnée. Les deux représentations sont convertibles, et c'est cette fonction
    qui fait la conversion — sans elle, un état déclaré dans un signal reste inexploitable comme
    segment (pas de calcul par segment, pas d'export par segment).
    """
    if len(times) != len(valeurs):
        raise ValueError("times et valeurs doivent avoir la même longueur")
    a_ignorer = set(ignorer)
    out: List[Segment] = []
    i, n = 0, len(valeurs)
    while i < n:
        v = valeurs[i]
        j = i
        while j + 1 < n and valeurs[j + 1] == v:
            j += 1
        if v not in a_ignorer:
            seg = {'start': times[i], 'end': times[j], 'value': v}
            if nom:
                seg['name'] = f"{nom}_{len(out) + 1:02d}"
            out.append(_tracer(seg, 'etat', samples=j - i + 1))
        i = j + 1
    return out


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 5. Opérations ENSEMBLISTES — « présent dans » et compagnie
# ──────────────────────────────────────────────────────────────────────────────────────────────

def present_dans(segments: Sequence[Segment], reference: Sequence[Segment], *,
                 strict: bool = True) -> List[Segment]:
    """Ne garde que les segments INCLUS dans l'un des segments de référence.

    ⚠ Cette opération n'appartient pas au Segmenter : dans l'outil d'origine elle est réutilisée
    **à l'export**. C'est donc une fonction ensembliste sur segments, applicable partout où l'on
    restreint un ensemble à un contexte — d'où sa place ici parmi les opérations, et non dans un
    mode de segmentation.

    `strict` reproduit le comportement d'origine (bornes strictement intérieures) ; `False` accepte
    l'égalité des bornes, ce qu'on veut quand la référence a été produite par le même découpage.
    """
    debuts = [r['start'] for r in reference]
    fins = [r['end'] if r['end'] is not None else float('inf') for r in reference]
    out: List[Segment] = []
    for s in segments:
        fin = s['end'] if s['end'] is not None else float('inf')
        for d, f in zip(debuts, fins):
            dedans = (s['start'] > d and fin < f) if strict else (s['start'] >= d and fin <= f)
            if dedans:
                out.append(s)
                break
    return out


def chevauche(segments: Sequence[Segment], reference: Sequence[Segment]) -> List[Segment]:
    """Segments qui INTERSECTENT au moins un segment de référence (inclusion non exigée)."""
    out: List[Segment] = []
    for s in segments:
        fin = s['end'] if s['end'] is not None else float('inf')
        for r in reference:
            rfin = r['end'] if r['end'] is not None else float('inf')
            if s['start'] <= rfin and fin >= r['start']:
                out.append(s)
                break
    return out


def ouverts(segments: Sequence[Segment]) -> List[Segment]:
    """Segments dont la fin est inconnue — un état commencé et non refermé.

    Les compter est une VÉRIFICATION, pas une curiosité : à la fin d'un codage, des états encore
    ouverts signalent soit une session interrompue, soit un codage incomplet. Les taire reviendrait
    à livrer des durées fausses.
    """
    return [s for s in segments if s.get('end') is None]


def fermer(segments: Sequence[Segment], fin: float) -> List[Segment]:
    """Ferme les segments ouverts à un instant donné (fin de média, fin d'observation).

    La fermeture est un ACTE EXPLICITE et tracé (`closed_at`) : une durée obtenue en refermant
    d'office n'a pas le même statut qu'une durée observée, et un traitement en aval doit pouvoir
    faire la différence.
    """
    out = []
    for s in segments:
        s = dict(s)
        if s.get('end') is None:
            s['end'] = fin
            s['closed_at'] = fin
        out.append(s)
    return out


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 6. MARGES — ajuster les bornes d'un segment EXISTANT (temporelles, ou spatiales par colonne)
# ──────────────────────────────────────────────────────────────────────────────────────────────

def marges(segments: Sequence[Segment], avant: float = 0.0, apres: float = 0.0) -> List[Segment]:
    """Décale les bornes de chaque segment : `start − avant`, `end + apres`.

    C'est le mode « Simple » de l'outil d'origine appliqué à une SITUATION (bascule
    [Event|Situation] de l'écran, marges inf/sup) : `autour()` ne sait le faire que pour une ancre
    PONCTUELLE — une situation a DEUX bornes à décaler indépendamment. Négatif = rétrécir.

    ⚠ Un segment qui s'INVERSE en rétrécissant (`start ≥ end`) est ÉCARTÉ — même geste que
    `duree_min` dans `conditionnelle()` : la contrainte déclarée vaut filtre, pas une bizarrerie.
    ⚠ Une fin OUVERTE le reste : on ne décale pas une borne inconnue.
    L'origine d'AVANT la marge survit dans `source` — décaler des bornes ne doit pas effacer
    d'où le segment vient.
    """
    out: List[Segment] = []
    for s in segments:
        seg = dict(s)
        seg['start'] = s['start'] - avant
        fin = s.get('end')
        seg['end'] = OUVERT if fin is OUVERT else fin + apres
        if seg['end'] is not OUVERT and seg['end'] <= seg['start']:
            continue
        out.append(_tracer(seg, 'marges', source=s.get('origin'),
                           window=f"{avant:g}_{apres:g}"))
    return out


def marges_spatiales(segments: Sequence[Segment], times: Sequence[float],
                     abscisses: Sequence[Optional[float]],
                     avant_m: float = 0.0, apres_m: float = 0.0) -> List[Segment]:
    """Décale les bornes d'une DISTANCE PARCOURUE le long de la trace, pas d'une durée.

    Même généralisation que la segmentation spatiale (§9septies) : « 50 m avant l'entrée de
    zone » n'est pas un mode nouveau, c'est une marge exprimée sur l'ABSCISSE CURVILIGNE — une
    colonne (`core/geo.py::abscisse_curviligne`), passée ici en séquence pour que ce module reste
    pur (ni pandas, ni géodésie).

    Les bornes rendues sont des ÉCHANTILLONS EXISTANTS de la trace — aucune valeur inventée, comme
    `at()` : pour la marge amont on prend le DERNIER échantillon dont l'abscisse est ≤ cible, pour
    la marge aval le PREMIER dont l'abscisse est ≥ cible, donc la marge rendue vaut AU MOINS la
    marge demandée. Une cible au-delà de la trace est bornée au premier/dernier échantillon
    valide : la marge s'arrête où la donnée s'arrête.

    ⚠ Fin OUVERTE : inchangée (on ne mesure pas une distance jusqu'à un instant inconnu).
    ⚠ Segment inversé après rétrécissement : écarté (cf. `marges`).
    ⚠ Les positions invalides (abscisse `None` — trou GPS) sont ignorées par la recherche.
    """
    if len(times) != len(abscisses):
        raise ValueError(f"times et abscisses de longueurs différentes "
                         f"({len(times)} ≠ {len(abscisses)})")
    ts = [t for t, a in zip(times, abscisses) if a is not None]
    ab = [a for a in abscisses if a is not None]
    if not ts:
        raise ValueError("trace sans aucune position valide : marge spatiale incalculable")

    def _abscisse_a(t: float) -> float:
        i = bisect_right(ts, t) - 1
        return ab[max(i, 0)]

    out: List[Segment] = []
    for s in segments:
        seg = dict(s)
        i = bisect_right(ab, _abscisse_a(s['start']) - avant_m) - 1
        seg['start'] = ts[max(i, 0)]
        fin = s.get('end')
        if fin is not OUVERT:
            j = bisect_left(ab, _abscisse_a(fin) + apres_m)
            seg['end'] = ts[min(j, len(ts) - 1)]
            if seg['end'] <= seg['start']:
                continue
        out.append(_tracer(seg, 'marges_spatiales', source=s.get('origin'),
                           window=f"{avant_m:g}_{apres_m:g}_m"))
    return out
