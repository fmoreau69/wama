"""
Exporter — rend les segments et leurs indicateurs exploitables HORS de WAMA.

CE MODULE TRADUIT BIND_GUI, ET COMBLE CE QUI LUI MANQUE.

    Les quatre chemins d'export de BIND ont été LUS (`BIND_GUI/src/+fr/+lescot/+bind/+export/`
    et `BIND_scripts/export/`) avant d'écrire une ligne. Tous les quatre produisent du LONG :

      • `exportTripTable2File`                    une table → un TSV/CSV, préfixé d'un `trip_id`
      • `batchExportDatasTables2TSVBindGUI`       le même, bouclé sur les `.trip` d'un dossier
      • `exportTripDataBySituation2TSVByParticipant`  une ligne par occurrence de situation
      • `exportSituationsAndEvents2CSV`           paires (clé, valeur) par marqueur

    Le livrable à 393 colonnes décrit en `WAMA_DATA_WORLD.md §6.7` n'est produit par AUCUN d'eux :
    il naît d'un remaniement Excel fait à la main par les chercheurs. Le pivot est donc
    exactement l'étape manuelle que l'Exporter doit absorber — ce que §6.7 appelle « son vrai
    travail ».

    ⚠ Et BIND le savait : `ExportTrip2Files.buildHeader` porte une branche `nb_occurrences > 1`
    qui compose `{variable}_{table}{i_occurrence}` — le nommage du format large. Elle référence
    `i_occurrence`, **variable non définie dans sa portée**, et n'est jamais appelée qu'avec
    `nb_occurrences = 1`. L'intention existait, le code n'a jamais tourné. On la reprend ici
    en la rendant vraie, pas en la recopiant.

CE QU'ON NE TRADUIT PAS — des résidus d'étude, dans du code pourtant générique :

    • `if strcmp(var_name,'HRinterp')` au cœur de l'export par situation : les valeurs de TOUTE
      autre variable sont écrites… nulle part. Le fichier sort vide de mesures, sans un mot.
    • `subSampling = 1000` en dur dans le batch.
    • `id_participant` obtenu en découpant le CHEMIN du fichier (`strsplit(trip_file,'\')`).

    Ici l'identité de ligne est un paramètre, la décimation aussi, et une colonne demandée mais
    absente est une ERREUR nommée — jamais un silence.

CE MODULE EST PUR : listes de dicts, aucune dépendance à pandas ni à Django. L'écriture de
fichiers n'est pas ici non plus — elle appartient à l'adaptateur, qui dispose déjà des briques.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .valeurs import manquant

#: Sépare l'identité de colonne de l'indicateur : `0_15.moyenne`. Repris de la forme RÉELLE du
#: livrable (§6.7 : « colonnes préfixées "0_15.*" »), pas inventé.
SEPARATEUR = '.'

#: Marque une occurrence de rang > 1 pour une même identité de colonne : `freinage#2.moyenne`.
#: Nécessaire dès qu'un segment se répète dans une passation — le cas NORMAL (12 fenêtres,
#: 377 lignes en §6.7). Sans lui, la seconde occurrence écraserait la première en silence :
#: c'est précisément le trou que la branche morte de `buildHeader` tentait de boucher.
RANG = '#'


def _texte(valeur) -> str:
    """Identité rendue en texte, de façon STABLE. `None` devient '' et non 'None'."""
    return '' if manquant(valeur) else str(valeur)


def nom_de_colonne(identite: str, mesure: str, rang: int = 1) -> str:
    """`0_15` + `moyenne` → `0_15.moyenne` ; au 2ᵉ passage → `0_15#2.moyenne`.

    Le rang n'apparaît QU'À PARTIR DE 2 : la très grande majorité des colonnes gardent la forme
    lisible, et une numérotation systématique (`0_15#1.`) rendrait illisible un livrable qui est
    lu par des humains dans un tableur.
    """
    base = identite if rang <= 1 else f"{identite}{RANG}{rang}"
    return f"{base}{SEPARATEUR}{mesure}"


def pivot_large(lignes: Sequence[Dict[str, Any]], *, cle_ligne: Sequence[str],
                cle_colonne: str, mesures: Sequence[str],
                trier: bool = True) -> Tuple[List[Dict[str, Any]], List[str]]:
    """LE travail de l'Exporter : passer du LONG au LARGE.

    Entrée (long) — une ligne par segment :

        trip_id  nom      moyenne  max
        P01      0_15     72.3     91
        P01      15_30    68.1     88
        P02      0_15     75.0     93

    Sortie (large) — une ligne par PASSATION, les fenêtres côte à côte :

        trip_id  0_15.moyenne  0_15.max  15_30.moyenne  15_30.max
        P01      72.3          91        68.1           88
        P02      75.0          93        —              —

    `cle_ligne`   : les colonnes qui IDENTIFIENT une ligne du livrable (souvent le participant,
                    parfois participant + scénario — BIND écrit les deux côte à côte).
    `cle_colonne` : la colonne dont les VALEURS deviennent des préfixes de colonnes.
    `mesures`     : les colonnes à répartir sous chaque préfixe.

    Rend `(lignes_larges, colonnes)` — l'ordre des colonnes est rendu explicitement parce qu'un
    dict ne le garantit pas pour un lecteur, et qu'un livrable dont les colonnes bougent d'un
    export à l'autre est inexploitable en comparaison.

    ⚠ Une combinaison absente reste ABSENTE (clé non écrite), jamais 0 : sur 69 passations et
    12 fenêtres, une fenêtre non observée et une fenêtre mesurée à zéro ne se corrigent pas de la
    même façon, et rien dans un tableur ne les distingue une fois confondues.
    """
    if not cle_ligne:
        raise ValueError("`cle_ligne` est obligatoire : sans identité, toutes les lignes "
                         "fusionneraient en une seule")
    if not mesures:
        raise ValueError("aucune mesure à exporter")

    _exiger_colonnes(lignes, [*cle_ligne, cle_colonne, *mesures])

    larges: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    ordre_identites: List[Tuple[str, ...]] = []
    # Compte les occurrences PAR LIGNE : le rang est local à une passation, sinon le second
    # participant hériterait du compteur du premier et ses colonnes seraient décalées.
    vus: Dict[Tuple[Tuple[str, ...], str], int] = {}
    colonnes_vues: List[str] = []

    for ligne in lignes:
        identite = tuple(_texte(ligne.get(c)) for c in cle_ligne)
        if identite not in larges:
            larges[identite] = {c: ligne.get(c) for c in cle_ligne}
            ordre_identites.append(identite)

        prefixe = _texte(ligne.get(cle_colonne))
        rang = vus.get((identite, prefixe), 0) + 1
        vus[(identite, prefixe)] = rang

        for mesure in mesures:
            colonne = nom_de_colonne(prefixe, mesure, rang)
            valeur = ligne.get(mesure)
            if manquant(valeur):
                continue                      # absent ⇒ on n'écrit PAS la clé
            larges[identite][colonne] = valeur
            if colonne not in colonnes_vues:
                colonnes_vues.append(colonne)

    colonnes = list(cle_ligne) + (sorted(colonnes_vues) if trier else colonnes_vues)
    return [larges[i] for i in ordre_identites], colonnes


def _exiger_colonnes(lignes: Sequence[Dict[str, Any]], attendues: Iterable[str]) -> None:
    """Une colonne demandée mais absente est une ERREUR NOMMÉE.

    C'est la leçon directe du `if strcmp(var_name,'HRinterp')` de BIND : demander une variable
    que l'export ne sait pas écrire y produit un fichier sans mesures, et rien ne le signale.
    Un export muet coûte une campagne — il ne se découvre qu'à l'analyse.
    """
    if not lignes:
        return
    disponibles = set()
    for ligne in lignes:
        disponibles.update(ligne)
    manquantes = [c for c in dict.fromkeys(attendues) if c not in disponibles]
    if manquantes:
        raise ValueError(
            f"colonne(s) absente(s) : {', '.join(manquantes)} "
            f"(disponibles : {', '.join(sorted(disponibles)) or '—'})")


def en_lignes(lignes: Sequence[Dict[str, Any]], colonnes: Sequence[str],
              *, absent: str = '') -> List[List[str]]:
    """Aplatit en tableau de chaînes, en-tête compris — la forme qu'un écrivain de fichier attend.

    `absent` est le texte des trous. Vide par défaut : dans un tableur une cellule vide se lit
    « pas de donnée », là où `0` ou `NaN` se lisent comme des mesures.
    """
    sortie = [list(colonnes)]
    for ligne in lignes:
        sortie.append([absent if manquant(ligne.get(c)) else str(ligne.get(c)) for c in colonnes])
    return sortie


def decimer(lignes: Sequence[Any], pas: int = 1) -> List[Any]:
    """Garde une ligne sur `pas` — la décimation d'export de BIND (`sub_sampling`).

    Elle n'est PAS une commodité : §6.7 mesure 1,28 Go pour 34 minutes et un seul participant,
    ~88 Go à l'échelle d'une étude. Ce qui est repris de BIND est le mécanisme ; ce qui ne l'est
    pas, c'est son `subSampling = 1000` écrit en dur dans le batch — ici c'est un paramètre, et
    son défaut (1) n'enlève rien.
    """
    if pas < 1:
        raise ValueError("le pas de décimation vaut au moins 1 (1 = tout garder)")
    return list(lignes[::pas])
