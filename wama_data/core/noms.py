"""
NOMS DÉRIVÉS — la seule brique qui décide comment une production se nomme.

DOCTRINE (`WAMA_DATA_WORLD.md §9ter.6 B7`) : **le nom se DÉRIVE des paramètres, il ne se saisit
pas.** Deux productions de mêmes réglages portent alors le même nom, et deux réglages différents
ne peuvent pas le partager. Une saisie libre ne garantit ni l'un ni l'autre — et surtout, elle
rompt le lien entre le nom lu dans un tableau et le réglage qui l'a produit.

⚠ POURQUOI CE FICHIER EXISTE (audit A du 2026-08-23, `§9sexies`). La doctrine était écrite, mais
appliquée par **quatre règles éparpillées dans trois lieux** — et l'une d'elles n'était même pas
une règle :

    nom_produit()              functions/temporal/calculation.py   ← dans l'ADAPTATEUR
    nom_jonction(), nom_chaine()   core/conditions.py              ← dans le CŒUR
    Colonne.titre              core/export.py
    f"{d.flux}_{d.fonction}"   vue.py, EN DUR dans une f-string    ← pas une règle du tout

Même famille de règle, moitié dans le cœur, moitié dans l'adaptateur, et une écrite à la volée.
C'est le patron que le dépôt nomme déjà « la divergence est la trace d'une brique absente ».

⚠ CE MODULE N'A AUCUNE DÉPENDANCE — pas même aux autres modules du cœur. C'est la condition pour
que `conditions.py` puisse l'importer sans cycle, alors que `nom_chaine()` a besoin du rendu de
l'arbre : la brique fournit la **normalisation**, l'appelant fournit le **texte**.

⚠ `Colonne.titre` (export) reste chez lui À DESSEIN : ce n'est pas un nom dérivé de paramètres,
c'est un **en-tête de fichier** dont la convention (`flux.champ`) appartient au livrable chercheur
et se surcharge colonne par colonne. Le rapprocher d'ici mêlerait deux règles qui n'ont ni la même
source ni la même raison de changer.
"""
from __future__ import annotations

#: Longueur du préfixe retenu d'un nom de table. Trois caractères est la règle de l'outil
#: d'origine (`app.tddTable1.Value(1:3)`), qui produit `deb_fin_0_0`. On la garde telle quelle :
#: c'est un nom que les utilisateurs de ce laboratoire LISENT déjà.
PREFIXE_TABLE = 3


def abreger(nom: str) -> str:
    """Préfixe minuscule d'un nom de table — `debut_bloc` → `deb`."""
    return (nom or '')[:PREFIXE_TABLE].lower()


def entier(x: float) -> str:
    """`0` plutôt que `0.0`, `-2.5` conservé — un nom ne porte pas de décimale inutile."""
    return f"{int(x)}" if float(x).is_integer() else f"{x:g}"


def normaliser(texte: str) -> str:
    """Texte quelconque → fragment de nom : minuscules, alphanumérique, `_` unique, sans bords.

    ⚠ POINT DE PASSAGE UNIQUE de la mise en forme des noms. La règle est ici et nulle part
    ailleurs : deux normalisations légèrement différentes produiraient deux noms pour le même
    réglage, ce qui est exactement ce que la doctrine interdit.
    """
    out = ''.join(c if c.isalnum() else '_' for c in (texte or '').lower())
    while '__' in out:
        out = out.replace('__', '_')
    return out.strip('_')


def nom_produit(colonne: str, suffixe: str) -> str:
    """Colonne dérivée — `vitesse` + `moyenne` → `vitesse_moyenne`.

    Déterministe et sans paramètre de renommage : le nom se lit dans le tableau final sans avoir
    à retrouver quel réglage l'a produit. C'est ce qui rend deux exports comparables.
    """
    return f"{colonne}_{suffixe}"


def nom_jonction(table_debut: str, table_fin: str,
                 offset_debut: float, offset_fin: float) -> str:
    """Segmentation temporelle double — `deb_fin_0_0`, la graphie de l'outil d'origine."""
    return (f"{abreger(table_debut)}_{abreger(table_fin)}"
            f"_{entier(offset_debut)}_{entier(offset_fin)}")


def nom_annexe(flux: str, fonction: str) -> str:
    """Table ANNEXE née d'un calcul qui change la clé temporelle — `vitesse_calcul_par_segment`.

    ⚠ Remplace une f-string écrite en dur dans `vue.py` (audit A). Le nom d'une annexe est une
    production comme une autre : il doit dire de quel flux et de quelle fonction elle vient, sinon
    deux annexes du même flux deviennent indiscernables dès qu'on en produit une seconde.
    """
    return normaliser(f"{flux}_{fonction}")
