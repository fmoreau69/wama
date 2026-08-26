"""
Adaptateur de l'Exporter (implémentation : `wama_data/core/export.py`).

Aucune logique d'export ici — la conversion depuis `TypedFrame` et l'écriture des fichiers, c'est
tout. Le cœur reste pur (listes et dicts), comme `segmentation.py`, `calculation.py` et
`conditions.py`.

⚠ CE MODULE NE DÉCLARE VOLONTAIREMENT AUCUN `FunctionSpec`, contrairement à tous ses voisins.

`FunctionCategory` n'a pas de valeur pour « écrit des fichiers » : ses sept catégories
(`transform`, `enricher`, `detector`, `indicator`, `resampler`, `join`, `aggregate`) décrivent
toutes une fonction qui REND une donnée typée. Un export est un PUITS — il ne rend rien de
chaînable.

Trois options, et pourquoi celle-ci :

  • **En ranger un dans `aggregate` ou `transform`** — un mensonge de déclaration. La catégorie
    « pilote le regroupement UI + le type de sortie » (`function_catalog.py:18`) : la fausser
    ferait apparaître l'export comme branchable là où il ne l'est pas.
  • **Ajouter `FunctionCategory.SINK`** — une modification du SUBSTRAT (`wama/common/catalog/`),
    partagé avec le Lab (`cam_analyzer/function_specs.py` y déclare ses fonctions). On ne touche
    pas la glu inter-mondes pour un besoin d'un seul monde, surtout quand rien ne consommerait
    la valeur : aucune interface ne rend encore les catégories de fonctions.
  • **Ne pas déclarer, et le dire** — retenu. Le puits est déjà une notion du kind `pipeline`
    (`source|sink|app`), et la décision **D13** de `WAMA_DATA_WORLD §10` — « nœud fonction dans le
    kind `pipeline` : étendre `source|sink|app`, ou déclarer les fonctions comme un `app` d'un
    genre particulier ? » — est exactement la question qui tranchera où vit ce nœud-là. La
    trancher ici en passant, dans un fichier d'adaptateur, serait la trancher au mauvais endroit.

Conséquence assumée : l'Exporter n'est pas chaînable dans le canvas tant que D13 n'est pas tranchée.
Il est utilisable par code et par l'app qui le pilotera. C'est un manque NOMMÉ, pas un oubli.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from wama.common.catalog.data_types import TypedFrame
from ...core.export import (FORMATS, Colonne, Declaration, Fichier, Identite, Regroupement,
                            apercu, exporter, rendre)

__all__ = ['lot_depuis_frames', 'exporter_frames', 'apercu_frames', 'ecrire']


def lot_depuis_frames(frames: Mapping[str, TypedFrame]) -> Dict[str, List[Dict[str, Any]]]:
    """`TypedFrame`s → la forme que le cœur consomme (nom de table → liste de lignes).

    ⚠ `to_dict('records')` convertit un `NaN` pandas en `float('nan')`, PAS en `None` — et c'est
    ce qu'on veut : `manquant()` reconnaît les deux, et forcer `None` ici casserait le typage
    numérique des colonnes que l'appelant pourrait vouloir relire. Le rendu texte, lui, écrit une
    cellule vide dans les deux cas (`_cellule` dans le cœur).
    """
    return {name: frame.df.to_dict('records') for name, frame in frames.items()}


def exporter_frames(declarations: Sequence[Declaration],
                    lots: Mapping[str, Mapping[str, TypedFrame]],
                    metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
                    regroupement: Optional[Regroupement] = None) -> List[Fichier]:
    """Export complet depuis des cadres typés. Même point de passage que le cœur."""
    return exporter(declarations, {n: lot_depuis_frames(f) for n, f in lots.items()},
                    metas, regroupement)


def apercu_frames(declarations: Sequence[Declaration],
                  lots: Mapping[str, Mapping[str, TypedFrame]],
                  metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
                  regroupement: Optional[Regroupement] = None,
                  *, lignes_max: int = 20) -> List[Fichier]:
    """L'aperçu — le même chemin que l'export, borné (§9ter.6 C4)."""
    return apercu(declarations, {n: lot_depuis_frames(f) for n, f in lots.items()},
                  metas, regroupement, lignes_max=lignes_max)


def ecrire(fichiers: Sequence[Fichier], dossier) -> List[Path]:
    """Écrit les fichiers produits et rend leurs chemins.

    Les formats non séparés par un caractère (`xlsx`, `mat`) sont refusés par `rendre()` du cœur —
    ils demandent une bibliothèque, et l'endroit où la brancher est ici, pas dans le cœur pur.
    Ils ne sont PAS encore implémentés : le refus est explicite plutôt que silencieux.
    """
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    ecrits: List[Path] = []
    for f in fichiers:
        chemin = dossier / f"{f.name}.{f.format}"
        chemin.write_text(rendre(f), encoding='utf-8')
        ecrits.append(chemin)
    return ecrits
