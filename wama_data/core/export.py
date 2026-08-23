"""
Exporter — une DÉCLARATION d'export, et une seule implémentation de groupement.

Spécification : `WAMA_DATA_WORLD.md §9ter.5` (ce que le livrable doit contenir) et `§9ter.6 C`
(comment WAMA le porte). L'Exporter n'est **en aval d'aucun module** : il exporte tout ce qu'un
trip contient à l'instant où on l'exporte — tables de données, méta-informations, événements,
situations et les indicateurs que le Calculator y a adjoints.

⚠ UN PREMIER JET A ÉTÉ REVERTÉ (ef756b63) parce qu'il était fondé sur un **pivot long → large**
qui n'existe nulle part dans l'outil d'origine. Ses quatre chemins d'export produisent tous du
LONG ; le tableau large à 393 colonnes que reçoivent les chercheurs naît d'un remaniement fait à
la main. **L'export SÉLECTIONNE, ORDONNE et CONCATÈNE — il n'oriente rien.**

CE QUE LA LECTURE DU CODE D'ORIGINE A ÉTABLI (`BIND_GUI.mlapp` + `ExportTrip2Files.m`, 2026-08-23) :

  ① LES QUATRE MODES SONT DEUX AXES. Sa fonction `exportation` porte quatre branches `elseif`
     (`normal`, `concat_event_situation`, `concat_trip`, `concat_all`) qui parcourent toutes la
     même matrice `data_for_all{i_fic, i_trip}` — déclarations × trips. Concaténer ou non sur
     chaque axe donne exactement ces quatre modes : ce sont donc deux booléens, pas quatre
     chemins de code. Le §9ter.6 C2 le supposait ; c'est vérifié.

  ② CE QUE LES QUATRE BRANCHES ONT COÛTÉ, mesuré ligne à ligne — c'est l'argument, pas le style :
       • `concat_all` accumule dans la mauvaise variable (`dataconcat_fic = [dataconcat; …]` au
         lieu de `[dataconcat_fic; …]`) : seule la DERNIÈRE déclaration de chaque trip survit ;
       • `concat_all` et `concat_trip` lisent `i_trip` / `i_fic` APRÈS la fin de leur boucle —
         le nom de fichier et le chemin sont donc ceux du dernier tour, quel que soit le contenu ;
       • `concat_all` concatène horizontalement (`,`) là où les trois autres empilent (`;`) ;
       • le `header` retenu est celui de la dernière déclaration alors que les données en
         concatènent plusieurs, aux colonnes différentes ;
       • deux `try … catch` à corps VIDE avalent en silence les incompatibilités de taille.
     Cinq défauts, tous dans les branches qui se recopient. Une implémentation unique n'en a aucun
     — non par talent, mais parce qu'il n'y a plus quatre endroits où diverger.

  ③ IL Y A DÉJÀ DEUX CONVENTIONS D'EN-TÊTE dans le même système. L'interface produit
     `table.variable` (`strcat(tables, '.', vars)`) — d'où les en-têtes `0_15.startTimecode` du
     livrable. Le chemin script produit le nom de variable NU, précédé d'un `trip_id`, et sa
     branche multi-occurrences est du code mort qui référence une variable jamais définie
     (`i_occurrence`) : elle lèverait si on l'atteignait. Une déclaration unique supprime la
     question — l'en-tête est un CHAMP de la colonne déclarée, pas une reconstruction par chemin.

  ④ LA DÉCIMATION EXISTE MAIS N'EST PAS OFFERTE. `subSampling = 1000` est écrit en dur dans le
     script de lot, et l'option « Échantillonnage » annoncée par la présentation n'a 0 occurrence
     dans le code (§9ter.5). Sa sémantique est un PAS (`for i = 1:sub_sampling:length`), pas une
     troncature — on garde une ligne sur N, on ne coupe pas après N. Elle devient ici un champ
     déclaré, avec cette sémantique-là.

⚠ CE MODULE EST PUR — listes et dicts Python, aucune dépendance à pandas ni à Django, comme
`segmentation.py`, `calculation.py` et `conditions.py`. L'écriture des fichiers et la conversion
depuis `TypedFrame` appartiennent à l'adaptateur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .valeurs import manquant

#: Une table exportable : une liste de lignes, chaque ligne étant un dict champ → valeur.
Table = Sequence[Mapping[str, Any]]

#: Le contenu exportable d'un lot : nom de table → lignes. « Lot » plutôt que « trip » : le
#: modèle ne connaît pas le format `.trip`, seulement l'unité d'export que l'utilisateur groupe.
Lot = Mapping[str, Table]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. La DÉCLARATION — ce qui remplace la struct de session
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Colonne:
    """Une colonne exportée : d'où elle vient, et sous quel en-tête elle sort.

    `entete` est un CHAMP, pas une reconstruction : c'est ce qui règle ③ ci-dessus. Laissé vide,
    il vaut `source.champ` — la convention du livrable chercheur (`0_15.startTimecode`).
    """
    source: str
    champ: str
    entete: str = ''

    def __post_init__(self) -> None:
        if not self.source or not self.champ:
            raise ValueError("une colonne exportée doit nommer sa source ET son champ")

    @property
    def titre(self) -> str:
        return self.entete or f"{self.source}.{self.champ}"


@dataclass(frozen=True)
class Identite:
    """Colonnes d'identité placées EN TÊTE de chaque ligne, avant les colonnes de données.

    Elles ne viennent pas d'une table mais des méta-informations du lot (nom du trip, participant,
    scénario). L'outil d'origine préfixe `trip_id` en dur dans un chemin et `Trip Name` dans
    l'autre ; ici c'est une liste déclarée, donc la même dans tous les chemins.

    ⚠ Sans identité, une concaténation entre lots produit un fichier où l'on ne peut plus dire de
    quel enregistrement vient une ligne. C'est pour cela que le défaut n'est pas « aucune ».
    """
    champs: Tuple[str, ...] = ('trip_id',)

    def entetes(self) -> List[str]:
        return list(self.champs)

    def valeurs(self, meta: Mapping[str, Any]) -> List[Any]:
        """Valeurs d'identité d'un lot. Un champ absent des méta rend `None`, jamais une erreur :
        un corpus hétérogène (un lot sans participant déclaré) doit s'exporter quand même, avec un
        trou visible plutôt qu'un export refusé."""
        return [meta.get(c) for c in self.champs]


@dataclass(frozen=True)
class Regroupement:
    """Les DEUX AXES qui remplacent les quatre branches (①).

    `lots`         : concaténer les lots (trips) entre eux.
    `declarations` : concaténer les déclarations (fichiers) entre elles.

    Les quatre modes d'origine sont les quatre combinaisons — ce ne sont pas des chemins de code
    mais une conséquence du groupement.
    """
    lots: bool = False
    declarations: bool = False

    @property
    def mode_origine(self) -> str:
        """Le nom qu'aurait ce groupement dans l'outil d'origine. Sert à la relecture par ceux
        qui connaissent l'ancien vocabulaire — jamais à choisir un chemin d'exécution."""
        return {(False, False): 'normal',
                (True, False): 'concat_trip',
                (False, True): 'concat_event_situation',
                (True, True): 'concat_all'}[(self.lots, self.declarations)]


#: Formats d'écriture déclarés : extension → séparateur de colonnes. `None` = format non
#: séparé par un caractère (le tableur et MATLAB sont écrits par l'adaptateur, pas par le cœur).
FORMATS: Dict[str, Optional[str]] = {
    'csv': ';',     # `;` et non `,` — c'est la convention de l'outil d'origine (`writecell`
                    # `'Delimiter', ';'`), et celle qu'attend un tableur en locale française.
    'tsv': '\t',
    'txt': '\t',
    'xlsx': None,
    'mat': None,
}


@dataclass(frozen=True)
class Declaration:
    """UNE déclaration d'export — sérialisable, donc un manifeste, donc rejouable.

    Elle remplace `app.export.ficN` de l'outil d'origine, qui vit dans une struct d'application.
    C'est toute la différence entre « j'ai refait la même analyse » et « j'ai rejoué la même ».
    Ses `save_env_export` / `load_export` viennent alors gratuitement : sauver la déclaration,
    c'est sauver un objet déjà sérialisable, pas un état d'interface.
    """
    nom: str
    colonnes: Tuple[Colonne, ...]
    identite: Identite = field(default_factory=Identite)
    decimation: int = 1
    format: str = 'csv'

    def __post_init__(self) -> None:
        if not self.nom:
            raise ValueError("une déclaration d'export doit porter un nom")
        if not self.colonnes:
            raise ValueError(f"« {self.nom} » : aucune colonne sélectionnée")
        if self.decimation < 1:
            raise ValueError(
                f"« {self.nom} » : la décimation est un PAS (garder une ligne sur N), "
                f"donc ≥ 1 — reçu {self.decimation}")
        if self.format not in FORMATS:
            raise ValueError(f"« {self.nom} » : format '{self.format}' inconnu "
                             f"(disponibles : {', '.join(FORMATS)})")
        titres = [c.titre for c in self.colonnes]
        doublons = sorted({t for t in titres if titres.count(t) > 1})
        # Deux colonnes de même en-tête produiraient un fichier que rien ne permet de relire :
        # l'outil d'origine ne le voit pas, parce que ses en-têtes sont reconstruits par chemin.
        if doublons:
            raise ValueError(f"« {self.nom} » : en-têtes en double ({', '.join(doublons)}) — "
                             "préciser `entete` sur l'une des colonnes")

    @property
    def sources(self) -> List[str]:
        """Tables citées par la déclaration, dans l'ordre de première apparition."""
        vues: List[str] = []
        for c in self.colonnes:
            if c.source not in vues:
                vues.append(c.source)
        return vues

    def entetes(self) -> List[str]:
        """Ligne d'en-tête : identité d'abord, puis les colonnes DANS L'ORDRE DÉCLARÉ.

        L'ordre est celui de la déclaration (`▲▼✕` de l'interface d'origine) : c'est une donnée,
        pas un tri. Un export dont les colonnes se réordonnent tout seules cesse d'être comparable
        à celui de la semaine précédente.
        """
        return self.identite.entetes() + [c.titre for c in self.colonnes]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. Extraction — une déclaration appliquée à UN lot
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _table(lot: Lot, nom: str, declaration: str) -> Table:
    try:
        return lot[nom]
    except KeyError:
        raise ValueError(
            f"« {declaration} » : table '{nom}' absente du lot "
            f"(présentes : {', '.join(sorted(lot)) or '— aucune'})")


def lignes(declaration: Declaration, lot: Lot, meta: Optional[Mapping[str, Any]] = None,
           *, limite: Optional[int] = None) -> List[List[Any]]:
    """Lignes produites par une déclaration sur un lot — identité en tête, ordre déclaré.

    ⚠ TOUTES LES COLONNES DOIVENT VENIR DE TABLES DE MÊME HAUTEUR. Une déclaration mêlant une
    table de 12 situations et une table de 30 000 échantillons ne décrit aucun tableau : il n'y a
    pas de correspondance ligne à ligne entre elles. L'outil d'origine rencontre exactement ce cas
    et l'avale dans un `try … catch` à corps vide (②) — l'export sort alors tronqué, sans un mot.
    Ici c'est une erreur nommée, à l'endroit où on peut encore la corriger.

    `limite` borne le nombre de lignes rendues. C'est l'APERÇU : le même chemin, pas un second
    (§9ter.6 C4). Chez l'outil d'origine l'aperçu est une fonction distincte — deux chemins qui
    peuvent diverger, donc un aperçu qui finit par mentir.
    """
    meta = meta or {}
    hauteurs = {nom: len(_table(lot, nom, declaration.nom)) for nom in declaration.sources}
    if len(set(hauteurs.values())) > 1:
        detail = ', '.join(f"{n}={h}" for n, h in hauteurs.items())
        raise ValueError(
            f"« {declaration.nom} » : tables de hauteurs différentes ({detail}) — une ligne "
            "d'export ne peut pas mêler des tables sans correspondance ligne à ligne ; "
            "exporter séparément, ou restreindre à un contexte commun")

    hauteur = next(iter(hauteurs.values()), 0)
    identite = declaration.identite.valeurs(meta)
    out: List[List[Any]] = []
    # Décimation = un PAS, pas une troncature (④). L'aperçu s'applique APRÈS elle : montrer les
    # N premières lignes brutes d'un export décimé au 1000ᵉ ne montrerait pas l'export.
    for i in range(0, hauteur, declaration.decimation):
        out.append(list(identite) + [_table(lot, c.source, declaration.nom)[i].get(c.champ)
                                     for c in declaration.colonnes])
        if limite is not None and len(out) >= limite:
            break
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. GROUPEMENT — une seule implémentation, deux axes
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass
class Fichier:
    """Un fichier d'export produit : son nom, ses en-têtes, ses lignes."""
    nom: str
    entetes: List[str]
    lignes: List[List[Any]]
    format: str = 'csv'

    @property
    def nb_lignes(self) -> int:
        return len(self.lignes)


def exporter(declarations: Sequence[Declaration], lots: Mapping[str, Lot],
             metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
             regroupement: Optional[Regroupement] = None,
             *, limite: Optional[int] = None) -> List[Fichier]:
    """LE point de passage unique de l'export. Les quatre modes d'origine en sont des paramètres.

    `lots` : nom du lot → son contenu. L'ordre d'itération est celui du mapping — donc stable, donc
    reproductible : deux exécutions de la même déclaration sur le même corpus rendent le même
    fichier, ligne pour ligne.

    `limite` borne CHAQUE fichier produit : c'est l'aperçu, le même chemin que l'export réel.

    ⚠ Concaténer des déclarations aux colonnes différentes est REFUSÉ. C'est le cas que l'outil
    d'origine traite en gardant l'en-tête de la dernière déclaration et en empilant les données de
    toutes (②) : le fichier obtenu a des colonnes qui ne décrivent pas son contenu.
    """
    metas = metas or {}
    regroupement = regroupement or Regroupement()

    # Étape 1 — la matrice (déclaration × lot), exactement celle de l'outil d'origine, mais
    # calculée UNE fois et lue par un seul groupement au lieu de quatre.
    matrice: Dict[Tuple[str, str], List[List[Any]]] = {}
    for d in declarations:
        for nom_lot, lot in lots.items():
            matrice[(d.nom, nom_lot)] = lignes(d, lot, metas.get(nom_lot), limite=limite)

    par_nom = {d.nom: d for d in declarations}

    def _entetes(noms: Sequence[str]) -> List[str]:
        """En-têtes d'un groupe de déclarations — identiques ou refus."""
        formes = {tuple(par_nom[n].entetes()) for n in noms}
        if len(formes) > 1:
            raise ValueError(
                f"regroupement impossible : les déclarations {', '.join(noms)} n'ont pas les "
                "mêmes colonnes — les concaténer produirait un fichier dont l'en-tête ne décrit "
                "pas les lignes")
        return list(next(iter(formes)))

    noms_decl = [d.nom for d in declarations]
    noms_lots = list(lots)

    # Étape 2 — LE groupement. Les deux axes décident seulement ce qu'on met dans une même clé.
    groupes: Dict[str, Tuple[List[str], List[List[Any]]]] = {}
    for nom_d in noms_decl:
        for nom_l in noms_lots:
            cle_d = '' if regroupement.declarations else nom_d
            cle_l = '' if regroupement.lots else nom_l
            nom_fichier = '_'.join(p for p in (cle_d, cle_l) if p) or 'export'
            if nom_fichier not in groupes:
                membres = noms_decl if regroupement.declarations else [nom_d]
                groupes[nom_fichier] = (_entetes(membres), [])
            groupes[nom_fichier][1].extend(matrice[(nom_d, nom_l)])

    fmt = declarations[0].format if declarations else 'csv'
    return [Fichier(nom=n, entetes=e, lignes=l, format=fmt) for n, (e, l) in groupes.items()]


def apercu(declarations: Sequence[Declaration], lots: Mapping[str, Lot],
           metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
           regroupement: Optional[Regroupement] = None, *, lignes_max: int = 20) -> List[Fichier]:
    """L'aperçu EST l'export borné (§9ter.6 C4) — pas un second chemin, par construction.

    Cette fonction n'a aucune logique propre : elle appelle `exporter` avec une limite. C'est
    voulu. Un aperçu qui recalcule autrement finit par montrer autre chose que ce qui sera écrit,
    et c'est précisément l'erreur qu'on ne peut pas détecter en relisant le fichier produit.
    """
    return exporter(declarations, lots, metas, regroupement, limite=lignes_max)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 4. Rendu texte — pour les formats séparés par un caractère
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _cellule(v: Any, separateur: str) -> str:
    """Une valeur en texte. Une absence rend une cellule VIDE, jamais « None » ni « nan ».

    Écrire `None` dans un CSV crée une valeur textuelle que le tableur relira comme une chaîne :
    la colonne cesse d'être numérique, et les moyennes calculées par le chercheur deviennent
    fausses sans qu'aucune ligne ne paraisse anormale.
    """
    if manquant(v):
        return ''
    texte = str(v)
    # Un séparateur présent dans une valeur casserait l'alignement des colonnes en aval.
    if separateur in texte or '"' in texte or '\n' in texte:
        return '"' + texte.replace('"', '""') + '"'
    return texte


def rendre(fichier: Fichier) -> str:
    """Contenu texte d'un fichier d'export (formats `csv` / `tsv` / `txt`).

    Les formats `xlsx` et `mat` ne passent pas par ici : ils ne sont pas séparés par un caractère
    et relèvent de l'adaptateur, qui a les bibliothèques. Le refuser explicitement vaut mieux que
    rendre un CSV sous une extension `.xlsx`.
    """
    separateur = FORMATS.get(fichier.format)
    if separateur is None:
        raise ValueError(
            f"le format '{fichier.format}' n'est pas séparé par un caractère — "
            "son écriture appartient à l'adaptateur")
    out = [separateur.join(_cellule(e, separateur) for e in fichier.entetes)]
    out += [separateur.join(_cellule(v, separateur) for v in ligne) for ligne in fichier.lignes]
    return '\n'.join(out) + '\n'
