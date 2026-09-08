"""Barre d'outils COMMUNE — UN registre d'outils, des PROFILS par nature de surface.

DEMANDE DE FABIEN (2026-09-08) : « on gère du coup 2 barres d'outils, 1 pour les registres et 1
pour les files d'attente. Elles ne sont pas identiques, mais je me demandais si on ne pourrait
pas en faire une générale commune proposant tous les outils possibles (union de toutes les
barres d'outils) et que les app tirent les outils dont elles ont besoin **de façon globale, pas
par app** […] Peut-on faire ça tout en conservant l'apparence actuelle ? »

CE QUI EXISTAIT. Deux briques communes, chacune bonne dans son coin :
  * `common/_queue_toolbar.html` — tri, statut, disposition, densité, pile, puis les actions
    globales ; 12 files l'incluent ;
  * `common/_filter_bar.html` — facettes + recherche EN DIRECT, compteur, réinitialisation ;
    15 surfaces de registre/catalogue l'incluent (brique JS `wama-filter-bar.js`).
Aucune duplication entre les deux — mais aucune UNION non plus : la recherche existait pour les
registres et manquait aux files, et rien ne permettait d'ajouter un outil « à toutes les files »
sans ouvrir douze gabarits.

CE QUE CE REGISTRE CHANGE. L'outil devient une ENTRÉE, la surface un PROFIL. Ajouter la
recherche aux douze files = une clé dans `PROFILS['file']`. Aucune app n'énumère ses outils :
c'est exactement le « de façon globale, pas par app » demandé. Le rendu de chaque outil reste
le markup existant, DÉPLACÉ tel quel dans son partial — porter, c'est déplacer.

L'APPARENCE EST PRÉSERVÉE PAR CONSTRUCTION, en deux points :
  1. les deux ENVELOPPES sont conservées à l'identique (la file en pôles `d-flex
     justify-content-between`, le registre en `row`/`col-auto` sur fond `#2b3035`) — elles ne
     se ressemblent pas, et les unifier aurait changé les deux ;
  2. `_queue_toolbar.html` et `_filter_bar.html` SURVIVENT comme façades vers `_toolbar.html`.
     Les 27 pages appelantes ne changent pas d'une ligne, donc rien ne peut régresser chez
     elles par oubli de portage.

⚠ `pole` = 'gauche' (organisation de l'affichage) ou 'droite' (actions / lecture). C'est la
décision de Fabien du 2026-07-03, déjà écrite dans l'ancien gabarit de file : les actions à
droite, en cohérence avec les cards, le danger à l'extrême droite.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Outil:
    """Un outil de barre. `partial` est la SEULE chose qui rend — le registre ne rend rien."""

    cle: str
    libelle: str
    partial: str
    pole: str = 'gauche'
    #: L'outil émet LUI-MÊME son enrobage de colonne. Vrai pour `facettes` seul : il rend N
    #: selects, chacun dans son `col-auto` — un enrobage posé par l'enveloppe les collerait
    #: tous dans une seule colonne, ce qui change la mise en page du registre.
    enveloppe_propre: bool = False


#: L'UNION de tous les outils de barre du dépôt. Une entrée ici, et n'importe quel profil peut
#: la tirer. Le libellé sert à la documentation et aux tests, pas au rendu (chaque partial
#: porte ses propres textes, déjà traduits par l'usage).
OUTILS = {
    'tri': Outil('tri', "Trier la file", 'common/toolbar/_tri.html'),
    'statut': Outil('statut', "Filtrer par statut", 'common/toolbar/_statut.html'),
    'recherche': Outil('recherche', "Rechercher", 'common/toolbar/_recherche.html'),
    'facettes': Outil('facettes', "Facettes déclarées", 'common/toolbar/_facettes.html',
                      enveloppe_propre=True),
    'disposition': Outil('disposition', "Ligne / mosaïque", 'common/toolbar/_disposition.html'),
    'densite': Outil('densite', "Densité des cards", 'common/toolbar/_densite.html'),
    'pile': Outil('pile', "Empiler autour de la sélection", 'common/toolbar/_pile.html'),
    'compteur': Outil('compteur', "Compteur « X sur Y »", 'common/toolbar/_compteur.html',
                      pole='droite'),
    'reinitialiser': Outil('reinitialiser', "Réinitialiser les filtres",
                           'common/toolbar/_reinitialiser.html', pole='droite'),
    'actions': Outil('actions', "Actions globales de la file",
                     'common/toolbar/_actions.html', pole='droite'),
}


#: Les PROFILS — une nature de surface, ses outils, son enveloppe.
#: ⚠ L'ORDRE compte : c'est l'ordre de rendu dans le pôle.
PROFILS = {
    # Files d'attente des 12 apps. `recherche` y est AJOUTÉE le 2026-09-08 (demande Fabien) :
    # une clé, et les douze files l'ont. Elle est placée après le filtre par statut — les trois
    # premiers outils disent CE QU'ON MONTRE, les trois suivants COMMENT c'est disposé.
    'file': {
        'enveloppe': 'file',
        'outils': ('tri', 'statut', 'recherche', 'disposition', 'densite', 'pile', 'actions'),
    },
    # Registres, catalogues, journal. Pas de tri ni de disposition : ces surfaces sont des
    # tableaux ou des grilles de tuiles, pas des files — leur ordre vient du serveur.
    'registre': {
        'enveloppe': 'registre',
        'outils': ('facettes', 'recherche', 'compteur', 'reinitialiser'),
    },
}


def outils_du_profil(profil: str) -> list:
    """Les `Outil` du profil, dans l'ordre déclaré. Profil inconnu → `KeyError` explicite.

    On ne se replie PAS sur un profil par défaut : une faute de frappe rendrait alors une barre
    plausible mais fausse, et personne ne le verrait. Mieux vaut la page qui échoue bruyamment.
    """
    if profil not in PROFILS:
        raise KeyError(f"profil de barre d'outils inconnu : {profil!r} "
                       f"(connus : {', '.join(sorted(PROFILS))})")
    return [OUTILS[cle] for cle in PROFILS[profil]['outils']]


def enveloppe_du_profil(profil: str) -> str:
    if profil not in PROFILS:
        raise KeyError(f"profil de barre d'outils inconnu : {profil!r}")
    return PROFILS[profil]['enveloppe']
