"""
Le VIEW-MODEL de l'Explorer — une DÉCLARATION de ce qu'on regarde.

Seconde moitié du cœur de l'Explorer (`WAMA_DATA_WORLD.md §9quater.7`), la première étant le pont
(`frames.py`). Elle répond à : **quels flux, quelle fenêtre, quelle résolution, quelles colonnes
dérivées** — et elle y répond par un objet SÉRIALISABLE, donc rejouable, diffable, et entrant dans
un manifeste. Même geste que la déclaration d'export (§9quater.5) : *on persiste la déclaration,
pas les valeurs.*

CE QUE CE MODULE APPORTE, ET QUI N'EXISTAIT PAS

    La règle de §9quater.4 — « une colonne calculée reste dans SA table tant que la CLÉ TEMPORELLE
    ne change pas » — était jusqu'ici une DOCTRINE écrite et une propriété émergente du Calculator.
    Ici elle devient **exécutable**, et surtout **dérivée du catalogue** : c'est la
    `FunctionCategory` déclarée par chaque fonction qui décide, pas une liste de noms tenue à jour
    à la main.

        adjointes à la table      TRANSFORM  ENRICHER
        nouvelle table            DETECTOR  INDICATOR  RESAMPLER  AGGREGATE  JOIN

    Ce découpage n'est pas une invention : il se lit dans les définitions mêmes des catégories
    (`function_catalog.py`) — « ajoute des champs/colonnes à l'entrée » et « même type en sortie »
    d'un côté ; « produit des events », « produit un scalaire », « change l'échantillonnage »,
    « agrège par groupe », « combine plusieurs entrées » de l'autre. **Ajouter une fonction au
    catalogue la range donc automatiquement du bon côté, sans toucher ce fichier.**

⚠ POURQUOI LA FENÊTRE EST DANS LA DÉCLARATION, et pas un paramètre d'appel. Une vue sans fenêtre
n'est pas rejouable : rouvrir « la même vue » sur un autre corpus doit montrer la même chose. Et
`buckets` y est parce que la RÉSOLUTION fait partie de ce qu'on regarde — sur 5 M points, le tracé
à 2000 tranches et le tracé à 200 ne disent pas la même chose du signal.

⚠ CE MODULE NE MATÉRIALISE RIEN DE DURABLE. `appliquer()` calcule à la demande et rend des cadres ;
il n'écrit pas. C'est la conséquence directe de §9quater.5 — une colonne matérialisée devient
périmée vis-à-vis de sa source sans que rien ne le signale, et l'enregistrement réel fait 1,28 Go.

⚠ VOCABULAIRE FRANÇAIS, comme tout le monde Data (`segmentation.py`, `calculation.py`,
`conditions.py`, `export.py`, `frames.py`). La règle générale du dépôt veut l'anglais pour les
identifiants importés ; l'appliquer ICI seulement créerait la juxtaposition de vocabulaires que
WAMA s'interdit. Si la dette se solde, elle se soldera pour le monde entier, d'un geste.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import FUNCTION_CATALOG, FunctionCategory, get

from .core.noms import nom_annexe
from .core.temporal import TemporalReferential
from .frames import frame_depuis_referentiel

# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. LA RÈGLE, dérivée du catalogue
# ══════════════════════════════════════════════════════════════════════════════════════════════

#: Catégories qui LAISSENT la granularité intacte — leur sortie a les mêmes lignes que l'entrée,
#: donc la colonne produite s'adjoint à la table qu'on regarde.
CATEGORIES_ADJOINTES = frozenset({FunctionCategory.TRANSFORM, FunctionCategory.ENRICHER})

#: Tout le reste change la clé temporelle, donc sort dans une table à part. On énumère quand même
#: — un `not in` silencieux rangerait une catégorie NOUVELLE du mauvais côté sans le dire.
CATEGORIES_NOUVELLE_TABLE = frozenset({
    FunctionCategory.DETECTOR, FunctionCategory.INDICATOR, FunctionCategory.RESAMPLER,
    FunctionCategory.AGGREGATE, FunctionCategory.JOIN,
})


def change_la_cle_temporelle(cle_fonction: str) -> bool:
    """La fonction change-t-elle la clé temporelle — donc faut-il une nouvelle table ?

    Lu dans la `FunctionCategory` DÉCLARÉE, jamais dans une liste de noms de fonctions. C'est ce
    qui fait que la règle de §9quater.4 s'applique à une fonction écrite demain sans qu'on touche
    ici. Une catégorie inconnue lève : mieux vaut refuser que ranger au hasard.
    """
    spec = get(cle_fonction)
    if spec is None:
        raise ValueError(f"fonction '{cle_fonction}' absente du catalogue "
                         f"(connues : {', '.join(sorted(FUNCTION_CATALOG)) or '—'})")
    if spec.category in CATEGORIES_ADJOINTES:
        return False
    if spec.category in CATEGORIES_NOUVELLE_TABLE:
        return True
    raise ValueError(
        f"catégorie '{spec.category}' de '{cle_fonction}' non classée par la règle de "
        "§9quater.4 — décider si elle change la clé temporelle et l'ajouter à l'un des deux "
        "ensembles de `vue.py`, plutôt que de la laisser tomber d'un côté par défaut")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. La DÉCLARATION
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Piste:
    """Un flux regardé, et les CHAMPS qu'on en montre. `champs` vide = tous."""
    flux: str
    champs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.flux:
            raise ValueError("une piste doit nommer son flux")


@dataclass(frozen=True)
class Fenetre:
    """Ce qu'on regarde du temps, ET à quelle résolution.

    `buckets = 0` : pas de décimation — c'est la TABLE, qui montre les échantillons réels.
    `buckets > 0` : le TRACÉ, décimé en autant de tranches (en pratique : la largeur en pixels).
    Les deux sortent du même référentiel, mais ne répondent pas à la même question.
    """
    t0: Optional[float] = None
    t1: Optional[float] = None
    buckets: int = 0

    def __post_init__(self) -> None:
        if self.buckets < 0:
            raise ValueError("buckets est un nombre de tranches (≥ 0), pas un indicateur")
        if self.t0 is not None and self.t1 is not None and self.t1 < self.t0:
            raise ValueError(f"fenêtre inversée : t1={self.t1} < t0={self.t0}")

    @property
    def bornee(self) -> bool:
        return self.t0 is not None and self.t1 is not None


@dataclass(frozen=True)
class ColonneDerivee:
    """Un calcul DÉCLARÉ sur un flux — pas son résultat.

    C'est le cœur de « on persiste la déclaration, pas les valeurs » (§9quater.5) : cet objet est
    ce qu'on garde, et les valeurs se recalculent. `nom` vide laisse la fonction nommer sa sortie
    par sa propre règle (`nom_produit()`, `nom_chaine()`) — une saisie libre ferait perdre le lien
    entre le nom lu dans le tableau et le réglage qui l'a produit.
    """
    fonction: str
    flux: str
    params: Mapping[str, Any] = field(default_factory=dict)
    nom: str = ''

    def __post_init__(self) -> None:
        if not self.fonction or not self.flux:
            raise ValueError("une colonne dérivée doit nommer sa fonction ET son flux d'entrée")

    @property
    def sort_de_la_table(self) -> bool:
        return change_la_cle_temporelle(self.fonction)


@dataclass(frozen=True)
class Vue:
    """CE QU'ON REGARDE — sérialisable, donc rejouable, diffable, et entrant dans un manifeste."""
    nom: str
    pistes: Tuple[Piste, ...]
    fenetre: Fenetre = field(default_factory=Fenetre)
    derivees: Tuple[ColonneDerivee, ...] = ()

    def __post_init__(self) -> None:
        if not self.nom:
            raise ValueError("une vue doit porter un nom")
        if not self.pistes:
            raise ValueError(f"« {self.nom} » : aucune piste — il n'y a rien à regarder")
        flux = [p.flux for p in self.pistes]
        doublons = sorted({f for f in flux if flux.count(f) > 1})
        if doublons:
            raise ValueError(f"« {self.nom} » : flux en double ({', '.join(doublons)}) — "
                             "une piste par flux, les colonnes se déclarent dans la piste")

    @property
    def flux(self) -> List[str]:
        return [p.flux for p in self.pistes]

    # ── Sérialisation : c'est une DÉCLARATION, elle doit faire l'aller-retour ─────────────────
    def to_dict(self) -> Dict[str, Any]:
        return {
            'nom': self.nom,
            'pistes': [{'flux': p.flux, 'champs': list(p.champs)} for p in self.pistes],
            'fenetre': {'t0': self.fenetre.t0, 't1': self.fenetre.t1,
                        'buckets': self.fenetre.buckets},
            'derivees': [{'fonction': d.fonction, 'flux': d.flux,
                          'params': dict(d.params), 'nom': d.nom} for d in self.derivees],
        }


def depuis_dict(brut: Mapping[str, Any]) -> Vue:
    """Reconstruit une vue depuis sa forme sérialisée. Valide comme à la construction."""
    if not isinstance(brut, Mapping):
        raise ValueError(f"déclaration de vue attendue sous forme d'objet, reçu {type(brut).__name__}")
    f = brut.get('fenetre') or {}
    return Vue(
        nom=brut.get('nom', ''),
        pistes=tuple(Piste(flux=p.get('flux', ''), champs=tuple(p.get('champs') or ()))
                     for p in (brut.get('pistes') or ())),
        fenetre=Fenetre(t0=f.get('t0'), t1=f.get('t1'), buckets=int(f.get('buckets') or 0)),
        derivees=tuple(ColonneDerivee(fonction=d.get('fonction', ''), flux=d.get('flux', ''),
                                      params=dict(d.get('params') or {}), nom=d.get('nom', ''))
                       for d in (brut.get('derivees') or ())),
    )


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. Application à un référentiel
# ══════════════════════════════════════════════════════════════════════════════════════════════

def valider(vue: Vue, ref: TemporalReferential) -> None:
    """Refuse une vue qui ne s'appliquera pas, EN LE DISANT — avant tout calcul.

    Une vue est une déclaration : ses fautes doivent se voir à la déclaration, comme celles de
    l'arbre de conditions (§9ter.6 B2). Trouver « flux inconnu » après avoir décimé 5 M points
    serait la même faute de conception que le `uialert` unique de l'outil d'origine.
    """
    connus = set(ref.names)
    for p in vue.pistes:
        if p.flux not in connus:
            raise ValueError(f"« {vue.nom} » : flux '{p.flux}' inconnu du référentiel "
                             f"(présents : {', '.join(sorted(connus)) or '—'})")
    for d in vue.derivees:
        if d.flux not in connus:
            raise ValueError(f"« {vue.nom} » : la colonne dérivée '{d.fonction}' porte sur un flux "
                             f"inconnu '{d.flux}'")
        d.sort_de_la_table          # lève si la fonction ou sa catégorie est inconnue


@dataclass
class Resultat:
    """Ce qu'une vue produit : les tables regardées, et celles que les calculs ont fait naître.

    ⚠ LES DEUX SONT SÉPARÉES À DESSEIN, et c'est la règle de §9quater.4 rendue VISIBLE : ce qui
    est resté dans `tables` a gardé la clé temporelle de son flux ; ce qui est dans `annexes` en a
    changé. L'interface n'a rien à décider — une colonne qui s'ajoute à la table qu'on regarde, ou
    un onglet qui s'ouvre.
    """
    tables: Dict[str, TypedFrame] = field(default_factory=dict)
    annexes: Dict[str, TypedFrame] = field(default_factory=dict)


def appliquer(vue: Vue, ref: TemporalReferential) -> Resultat:
    """Calcule ce que la vue déclare. **Ne persiste RIEN** (§9quater.5).

    Les colonnes dérivées sont appliquées dans l'ordre déclaré : une dérivée peut donc s'appuyer
    sur une colonne produite par la précédente, ce qui est le geste ordinaire d'un tableur.
    """
    valider(vue, ref)
    out = Resultat()
    for p in vue.pistes:
        out.tables[p.flux] = frame_depuis_referentiel(
            ref, p.flux, t0=vue.fenetre.t0, t1=vue.fenetre.t1,
            champs=p.champs or None)

    for d in vue.derivees:
        spec = get(d.fonction)
        entree = out.tables.get(d.flux)
        if entree is None:
            # Le flux porte une dérivée sans être regardé : on le charge quand même, sinon la
            # déclaration serait à moitié honorée sans que rien ne le dise.
            entree = frame_depuis_referentiel(ref, d.flux, t0=vue.fenetre.t0, t1=vue.fenetre.t1)
        produit = spec.fn(entree, **dict(d.params))
        if d.sort_de_la_table:
            out.annexes[d.nom or nom_annexe(d.flux, d.fonction)] = produit
        else:
            out.tables[d.flux] = produit      # la fonction a adjoint sa colonne à l'entrée
    return out


def serie(vue: Vue, ref: TemporalReferential, flux: str, champ: str) -> List[dict]:
    """La série DÉCIMÉE d'une colonne, pour un tracé — min/max RÉELS par tranche.

    ⚠ N'utilise pas `appliquer()` : passer par un cadre pandas matérialiserait les 5 M points que
    la décimation existe précisément pour éviter. On appelle donc `decimate_values` du référentiel,
    qui agrège dans la source quand elle sait le faire (une base SQL le fait en SQL).

    Exige une fenêtre bornée et `buckets > 0` : décimer « tout, en zéro tranche » n'a pas de sens,
    et laisser un défaut implicite ferait tracer autre chose que ce que la vue déclare.
    """
    if not vue.fenetre.bornee:
        raise ValueError(f"« {vue.nom} » : un tracé demande une fenêtre bornée (t0 et t1)")
    if vue.fenetre.buckets <= 0:
        raise ValueError(f"« {vue.nom} » : buckets doit être > 0 pour un tracé "
                         "(0 signifie « table, échantillons réels »)")
    valider(vue, ref)
    return ref.decimate_values(flux, vue.fenetre.t0, vue.fenetre.t1,
                               vue.fenetre.buckets, champ)
