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

from .values import missing

#: Une table exportable : une liste de lignes, chaque ligne étant un dict champ → valeur.
Table = Sequence[Mapping[str, Any]]

#: Le contenu exportable d'un lot : nom de table → lignes. « Lot » plutôt que « trip » : le
#: modèle ne connaît pas le format `.trip`, seulement l'unité d'export que l'utilisateur groupe.
Lot = Mapping[str, Table]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. La DÉCLARATION — ce qui remplace la struct de session
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Column:
    """Une colonne exportée : de quel FLUX elle vient, quel CHAMP, et sous quel en-tête elle sort.

    `header` est un CHAMP, pas une reconstruction : c'est ce qui règle ③ ci-dessus. Laissé vide,
    il vaut `flux.champ` — la convention du livrable chercheur (`0_15.startTimecode`).

    ⚠ Frontière des DONNÉES (renommage du 2026-10-31) : l'attribut Python est `header`, la clé
    SÉRIALISÉE reste `entete` — comme `colonnes` et `identite` dans `Declaration.to_dict`. Ces clés
    sont saisies et STOCKÉES dans les réglages du nœud « Export de données » (`io/nodes.py`) ;
    les renommer rendrait illisibles les déclarations déjà enregistrées.

    ⚠ `stream` et non `source` (renommé le 2026-08-23, §9sexies) : dans ce monde, **`source`
    désigne déjà un fichier/format à lire** (`SourceReader`, `SourceInfo`, `sources/`). L'employer
    pour un nom de table était une ambiguïté, pas une préférence de style.
    """
    stream: str
    field: str
    header: str = ''

    def __post_init__(self) -> None:
        if not self.stream or not self.field:
            raise ValueError("une colonne exportée doit nommer son flux ET son champ")

    @property
    def title(self) -> str:
        return self.header or f"{self.stream}.{self.field}"

    def to_dict(self) -> Dict[str, Any]:
        return {'stream': self.stream, 'field': self.field, 'entete': self.header}


@dataclass(frozen=True)
class Identity:
    """Colonnes d'identité placées EN TÊTE de chaque ligne, avant les colonnes de données.

    Elles ne viennent pas d'une table mais des méta-informations du lot (nom du trip, participant,
    scénario). L'outil d'origine préfixe `trip_id` en dur dans un chemin et `Trip Name` dans
    l'autre ; ici c'est une liste déclarée, donc la même dans tous les chemins.

    ⚠ Sans identité, une concaténation entre lots produit un fichier où l'on ne peut plus dire de
    quel enregistrement vient une ligne. C'est pour cela que le défaut n'est pas « aucune ».
    """
    fields: Tuple[str, ...] = ('trip_id',)

    def headers(self) -> List[str]:
        return list(self.fields)

    def values(self, meta: Mapping[str, Any]) -> List[Any]:
        """Valeurs d'identité d'un lot. Un champ absent des méta rend `None`, jamais une erreur :
        un corpus hétérogène (un lot sans participant déclaré) doit s'exporter quand même, avec un
        trou visible plutôt qu'un export refusé."""
        return [meta.get(c) for c in self.fields]


@dataclass(frozen=True)
class Grouping:
    """Les DEUX AXES qui remplacent les quatre branches (①).

    `lots`         : concaténer les lots (trips) entre eux.
    `declarations` : concaténer les déclarations (fichiers) entre elles.

    Les quatre modes d'origine sont les quatre combinaisons — ce ne sont pas des chemins de code
    mais une conséquence du groupement.
    """
    lots: bool = False
    declarations: bool = False

    @property
    def legacy_mode(self) -> str:
        """Le nom qu'aurait ce groupement dans l'outil d'origine. Sert à la relecture par ceux
        qui connaissent l'ancien vocabulaire — jamais à choisir un chemin d'exécution."""
        return {(False, False): 'normal',
                (True, False): 'concat_trip',
                (False, True): 'concat_event_situation',
                (True, True): 'concat_all'}[(self.lots, self.declarations)]


@dataclass(frozen=True)
class Format:
    """Une CAPACITÉ de sortie déclarée.

    ⚠ `writer=None` signifie « format DÉCLARÉ, écrivain PAS ENCORE ÉCRIT » — et cette distinction
    est le cœur du modèle. §9ter.5 recense `.csv`, `.txt`, `.xlsx`, `.mat` comme formats du livrable
    chercheur : les quatre sont donc des cibles légitimes qu'une déclaration d'export a le droit de
    nommer. Mais deux d'entre eux demandent une bibliothèque, donc un écrivain vivant dans
    l'adaptateur. Les taire ferait croire qu'ils n'existent pas ; les accepter en silence ferait
    écrire un CSV sous une extension `.xlsx`. On les déclare, et l'écriture échoue en le disant.
    """
    separator: Optional[str] = None
    writer: Optional[Any] = None
    description: str = ''


#: REGISTRE des formats de sortie — `ajouter un format = enregistrer une capacité`, jamais éditer
#: le moteur. Même geste que le registre de lecteurs de l'Importer (`sources/__init__.py`), et
#: pour la même raison : **la méthode d'export est universelle, les formats sont agrégatifs.**
#: (Doctrine consignée en `WAMA_DATA_WORLD.md §9quinquies`.)
FORMATS: Dict[str, Format] = {}


def register_format(extension: str, *, separator: Optional[str] = None,
                    writer: Optional[Any] = None, description: str = '') -> None:
    """Déclare une capacité de sortie. Idempotent par extension — le dernier inscrit gagne,
    ce qui permet à un adaptateur de FOURNIR l'écrivain d'un format déclaré sans lui."""
    FORMATS[extension] = Format(separator=separator, writer=writer,
                                description=description)


def available_formats() -> List[str]:
    """Extensions déclarées, dans l'ordre d'enregistrement. C'est cette liste que l'UI propose —
    elle n'est écrite nulle part ailleurs."""
    return list(FORMATS)


def writable_formats() -> List[str]:
    """Extensions qui ont RÉELLEMENT un écrivain. Toujours un sous-ensemble de `available_formats`
    — l'écart est la dette, et elle est ainsi mesurable au lieu d'être supposée."""
    return [e for e, f in FORMATS.items()
            if f.writer is not None or f.separator is not None]


# ── Formats natifs du cœur : ceux qui ne demandent aucune bibliothèque ────────────────────────
# `;` et non `,` pour le CSV — c'est la convention de l'outil d'origine (`writecell`
# `'Delimiter', ';'`) et celle qu'attend un tableur en locale française.
register_format('csv', separator=';', description='Tableur, séparateur point-virgule')
register_format('tsv', separator='\t', description='Tabulations')
register_format('txt', separator='\t', description='Texte, tabulations')
# Déclarés SANS écrivain : ils appartiennent au livrable (§9ter.5) mais demandent une bibliothèque.
register_format('xlsx', description='Classeur — écrivain à fournir par un adaptateur')
register_format('mat', description='MATLAB — écrivain à fournir par un adaptateur')


@dataclass(frozen=True)
class Declaration:
    """UNE déclaration d'export — sérialisable, donc un manifeste, donc rejouable.

    Elle remplace `app.export.ficN` de l'outil d'origine, qui vit dans une struct d'application.
    C'est toute la différence entre « j'ai refait la même analyse » et « j'ai rejoué la même ».
    Ses `save_env_export` / `load_export` viennent alors gratuitement : sauver la déclaration,
    c'est sauver un objet déjà sérialisable, pas un état d'interface.
    """
    name: str
    columns: Tuple[Column, ...]
    identity: Identity = field(default_factory=Identity)
    decimation: int = 1
    format: str = 'csv'

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("une déclaration d'export doit porter un nom")
        if not self.columns:
            raise ValueError(f"« {self.name} » : aucune colonne sélectionnée")
        if self.decimation < 1:
            raise ValueError(
                f"« {self.name} » : la décimation est un PAS (garder une ligne sur N), "
                f"donc ≥ 1 — reçu {self.decimation}")
        if self.format not in FORMATS:
            raise ValueError(f"« {self.name} » : format '{self.format}' inconnu "
                             f"(disponibles : {', '.join(FORMATS)})")
        titles = [c.title for c in self.columns]
        duplicates = sorted({t for t in titles if titles.count(t) > 1})
        # Deux colonnes de même en-tête produiraient un fichier que rien ne permet de relire :
        # l'outil d'origine ne le voit pas, parce que ses en-têtes sont reconstruits par chemin.
        if duplicates:
            raise ValueError(f"« {self.name} » : en-têtes en double ({', '.join(duplicates)}) — "
                             "préciser `entete` sur l'une des colonnes")

    @property
    def stream(self) -> List[str]:
        """Tables citées par la déclaration, dans l'ordre de première apparition."""
        seen: List[str] = []
        for c in self.columns:
            if c.stream not in seen:
                seen.append(c.stream)
        return seen

    def headers(self) -> List[str]:
        """Ligne d'en-tête : identité d'abord, puis les colonnes DANS L'ORDRE DÉCLARÉ.

        L'ordre est celui de la déclaration (`▲▼✕` de l'interface d'origine) : c'est une donnée,
        pas un tri. Un export dont les colonnes se réordonnent tout seules cesse d'être comparable
        à celui de la semaine précédente.
        """
        return self.identity.headers() + [c.title for c in self.columns]

    # ── Sérialisation — §9quater C1 l'affirmait (« c'est un manifeste ») sans l'écrire (§9sexies)
    #    ⚠ Les clés `colonnes` / `identite` / `entete` sont des DONNÉES stockées (cf. `Column`) :
    #    elles ne suivent pas les noms Python `columns` / `identity` / `header`.
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'colonnes': [c.to_dict() for c in self.columns],
            'identite': list(self.identity.fields),
            'decimation': self.decimation,
            'format': self.format,
        }


def declaration_from_dict(raw: Mapping[str, Any]) -> Declaration:
    """Reconstruit une déclaration d'export. Valide comme à la construction — une déclaration
    relue d'un manifeste ne mérite pas moins de contrôles qu'une déclaration écrite en code."""
    if not isinstance(raw, Mapping):
        raise ValueError(f"déclaration attendue sous forme d'objet, reçu {type(raw).__name__}")
    return Declaration(
        name=raw.get('name', ''),
        columns=tuple(Column(stream=c.get('stream', ''), field=c.get('field', ''),
                             header=c.get('entete', ''))
                      for c in (raw.get('colonnes') or ())),
        identity=Identity(tuple(raw.get('identite') or ())),
        decimation=int(raw.get('decimation') or 1),
        format=raw.get('format') or 'csv',
    )


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. Extraction — une déclaration appliquée à UN lot
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _table(lot: Lot, name: str, declaration: str) -> Table:
    try:
        return lot[name]
    except KeyError:
        raise ValueError(
            f"« {declaration} » : table '{name}' absente du lot "
            f"(présentes : {', '.join(sorted(lot)) or '— aucune'})")


def rows(declaration: Declaration, lot: Lot, meta: Optional[Mapping[str, Any]] = None,
           *, limit: Optional[int] = None) -> List[List[Any]]:
    """Lignes produites par une déclaration sur un lot — identité en tête, ordre déclaré.

    ⚠ TOUTES LES COLONNES DOIVENT VENIR DE TABLES DE MÊME HAUTEUR. Une déclaration mêlant une
    table de 12 situations et une table de 30 000 échantillons ne décrit aucun tableau : il n'y a
    pas de correspondance ligne à ligne entre elles. L'outil d'origine rencontre exactement ce cas
    et l'avale dans un `try … catch` à corps vide (②) — l'export sort alors tronqué, sans un mot.
    Ici c'est une erreur nommée, à l'endroit où on peut encore la corriger.

    `limit` borne le nombre de lignes rendues. C'est l'APERÇU : le même chemin, pas un second
    (§9ter.6 C4). Chez l'outil d'origine l'aperçu est une fonction distincte — deux chemins qui
    peuvent diverger, donc un aperçu qui finit par mentir.
    """
    meta = meta or {}
    heights = {name: len(_table(lot, name, declaration.name)) for name in declaration.stream}
    if len(set(heights.values())) > 1:
        detail = ', '.join(f"{n}={h}" for n, h in heights.items())
        raise ValueError(
            f"« {declaration.name} » : tables de hauteurs différentes ({detail}) — une ligne "
            "d'export ne peut pas mêler des tables sans correspondance ligne à ligne ; "
            "exporter séparément, ou restreindre à un contexte commun")

    height = next(iter(heights.values()), 0)
    identity = declaration.identity.values(meta)
    out: List[List[Any]] = []
    # Décimation = un PAS, pas une troncature (④). L'aperçu s'applique APRÈS elle : montrer les
    # N premières lignes brutes d'un export décimé au 1000ᵉ ne montrerait pas l'export.
    for i in range(0, height, declaration.decimation):
        out.append(list(identity) + [_table(lot, c.stream, declaration.name)[i].get(c.field)
                                     for c in declaration.columns])
        if limit is not None and len(out) >= limit:
            break
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. GROUPEMENT — une seule implémentation, deux axes
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass
class ExportFile:
    """Un fichier d'export produit : son nom, ses en-têtes, ses lignes."""
    name: str
    headers: List[str]
    rows: List[List[Any]]
    format: str = 'csv'

    @property
    def row_count(self) -> int:
        return len(self.rows)


def export(declarations: Sequence[Declaration], lots: Mapping[str, Lot],
             metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
             grouping: Optional[Grouping] = None,
             *, limit: Optional[int] = None) -> List[ExportFile]:
    """LE point de passage unique de l'export. Les quatre modes d'origine en sont des paramètres.

    `lots` : nom du lot → son contenu. L'ordre d'itération est celui du mapping — donc stable, donc
    reproductible : deux exécutions de la même déclaration sur le même corpus rendent le même
    fichier, ligne pour ligne.

    `limit` borne CHAQUE fichier produit : c'est l'aperçu, le même chemin que l'export réel.

    ⚠ Concaténer des déclarations aux colonnes différentes est REFUSÉ. C'est le cas que l'outil
    d'origine traite en gardant l'en-tête de la dernière déclaration et en empilant les données de
    toutes (②) : le fichier obtenu a des colonnes qui ne décrivent pas son contenu.
    """
    metas = metas or {}
    grouping = grouping or Grouping()

    # Étape 1 — la matrice (déclaration × lot), exactement celle de l'outil d'origine, mais
    # calculée UNE fois et lue par un seul groupement au lieu de quatre.
    matrix: Dict[Tuple[str, str], List[List[Any]]] = {}
    for d in declarations:
        for lot_name, lot in lots.items():
            matrix[(d.name, lot_name)] = rows(d, lot, metas.get(lot_name), limit=limit)

    by_name = {d.name: d for d in declarations}

    def _headers(naming: Sequence[str]) -> List[str]:
        """En-têtes d'un groupe de déclarations — identiques ou refus."""
        shapes = {tuple(by_name[n].headers()) for n in naming}
        if len(shapes) > 1:
            raise ValueError(
                f"regroupement impossible : les déclarations {', '.join(naming)} n'ont pas les "
                "mêmes colonnes — les concaténer produirait un fichier dont l'en-tête ne décrit "
                "pas les lignes")
        return list(next(iter(shapes)))

    decl_names = [d.name for d in declarations]
    lot_names = list(lots)

    # Étape 2 — LE groupement. Les deux axes décident seulement ce qu'on met dans une même clé.
    groups: Dict[str, Tuple[List[str], List[List[Any]]]] = {}
    for decl_name in decl_names:
        for lot_name in lot_names:
            decl_key = '' if grouping.declarations else decl_name
            lot_key = '' if grouping.lots else lot_name
            file_name = '_'.join(p for p in (decl_key, lot_key) if p) or 'export'
            if file_name not in groups:
                members = decl_names if grouping.declarations else [decl_name]
                groups[file_name] = (_headers(members), [])
            groups[file_name][1].extend(matrix[(decl_name, lot_name)])

    fmt = declarations[0].format if declarations else 'csv'
    return [ExportFile(name=n, headers=e, rows=l, format=fmt) for n, (e, l) in groups.items()]


def preview(declarations: Sequence[Declaration], lots: Mapping[str, Lot],
           metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
           grouping: Optional[Grouping] = None, *, max_rows: int = 20) -> List[ExportFile]:
    """L'aperçu EST l'export borné (§9ter.6 C4) — pas un second chemin, par construction.

    Cette fonction n'a aucune logique propre : elle appelle `export` avec une limite. C'est
    voulu. Un aperçu qui recalcule autrement finit par montrer autre chose que ce qui sera écrit,
    et c'est précisément l'erreur qu'on ne peut pas détecter en relisant le fichier produit.
    """
    return export(declarations, lots, metas, grouping, limit=max_rows)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 4. Rendu texte — pour les formats séparés par un caractère
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _cell(v: Any, separator: str) -> str:
    """Une valeur en texte. Une absence rend une cellule VIDE, jamais « None » ni « nan ».

    Écrire `None` dans un CSV crée une valeur textuelle que le tableur relira comme une chaîne :
    la colonne cesse d'être numérique, et les moyennes calculées par le chercheur deviennent
    fausses sans qu'aucune ligne ne paraisse anormale.
    """
    if missing(v):
        return ''
    text = str(v)
    # Un séparateur présent dans une valeur casserait l'alignement des colonnes en aval.
    if separator in text or '"' in text or '\n' in text:
        return '"' + text.replace('"', '""') + '"'
    return text


def render(export_file: ExportFile) -> str:
    """Contenu texte d'un fichier d'export (formats `csv` / `tsv` / `txt`).

    Les formats `xlsx` et `mat` ne passent pas par ici : ils ne sont pas séparés par un caractère
    et relèvent de l'adaptateur, qui a les bibliothèques. Le refuser explicitement vaut mieux que
    rendre un CSV sous une extension `.xlsx`.
    """
    fmt = FORMATS.get(export_file.format)
    if fmt is None:
        raise ValueError(f"format '{export_file.format}' non enregistré "
                         f"(déclarés : {', '.join(available_formats())})")
    if fmt.writer is not None:
        return fmt.writer(export_file)
    if fmt.separator is None:
        raise ValueError(
            f"le format '{export_file.format}' est DÉCLARÉ mais aucun écrivain n'est enregistré — "
            "il demande une bibliothèque, donc un adaptateur "
            "(`register_format('{0}', writer=…)`)".format(export_file.format))
    sep = fmt.separator
    out = [sep.join(_cell(e, sep) for e in export_file.headers)]
    out += [sep.join(_cell(v, sep) for v in row) for row in export_file.rows]
    return '\n'.join(out) + '\n'
