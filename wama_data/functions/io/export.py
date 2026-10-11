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

~~Conséquence assumée : l'Exporter n'est pas chaînable dans le canvas tant que D13 n'est pas tranchée.~~
✅ 2026-10-11 — D13 est tranchée (un seul kind `pipeline`, `§9undecies.2`) et la forme de l'export
précisée par Fabien (`§11.8 ⑨`) : l'Exporter est un NŒUD DE SORTIE du kind `pipeline`
(`data_export`, `manifests/builtin/pipeline.SINK_NODES`) qui porte ses `Declaration`s. Le
raisonnement ci-dessus RESTE VRAI : ce n'est toujours pas une `FunctionSpec` (aucune catégorie
honnête pour un puits), et la garde `PasDeDeclarationAuCatalogueTest` le tient toujours. Ce qui a
changé, c'est qu'il a désormais un lieu : `export_lots()` ci-dessous est ce que le nœud appelle.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from wama.common.catalog.data_types import TypedFrame
from ...core.export import (FORMATS, Column, Declaration, ExportFile, Identity, Grouping,
                            preview, export, render)

__all__ = ['lot_depuis_frames', 'exporter_frames', 'apercu_frames', 'write', 'export_lots',
           'grouping_from_dict']


def lot_depuis_frames(frames: Mapping[str, TypedFrame]) -> Dict[str, List[Dict[str, Any]]]:
    """`TypedFrame`s → la forme que le cœur consomme (nom de table → liste de lignes).

    ⚠ `to_dict('records')` convertit un `NaN` pandas en `float('nan')`, PAS en `None` — et c'est
    ce qu'on veut : `missing()` reconnaît les deux, et forcer `None` ici casserait le typage
    numérique des colonnes que l'appelant pourrait vouloir relire. Le rendu texte, lui, écrit une
    cellule vide dans les deux cas (`_cellule` dans le cœur).
    """
    return {name: frame.df.to_dict('records') for name, frame in frames.items()}


def exporter_frames(declarations: Sequence[Declaration],
                    lots: Mapping[str, Mapping[str, TypedFrame]],
                    metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
                    regroupement: Optional[Grouping] = None) -> List[ExportFile]:
    """Export complet depuis des cadres typés. Même point de passage que le cœur."""
    return export(declarations, {n: lot_depuis_frames(f) for n, f in lots.items()},
                    metas, regroupement)


def apercu_frames(declarations: Sequence[Declaration],
                  lots: Mapping[str, Mapping[str, TypedFrame]],
                  metas: Optional[Mapping[str, Mapping[str, Any]]] = None,
                  regroupement: Optional[Grouping] = None,
                  *, lignes_max: int = 20) -> List[ExportFile]:
    """L'aperçu — le même chemin que l'export, borné (§9ter.6 C4)."""
    return preview(declarations, {n: lot_depuis_frames(f) for n, f in lots.items()},
                  metas, regroupement, lignes_max=lignes_max)


def write(fichiers: Sequence[ExportFile], dossier, *, overwrite: bool = True) -> List[Path]:
    """Écrit les fichiers produits et rend leurs chemins.

    Les formats non séparés par un caractère (`xlsx`, `mat`) sont refusés par `render()` du cœur —
    ils demandent une bibliothèque, et l'endroit où la brancher est ici, pas dans le cœur pur.
    Ils ne sont PAS encore implémentés : le refus est explicite plutôt que silencieux.

    `overwrite=False` (2026-10-11, le nœud de sortie l'emploie) : un fichier déjà présent arrête
    TOUT avant la moindre écriture — un export écrit dans le dossier des données de l'utilisateur
    (`§11.1`) n'y remplace rien sans qu'on le lui ait demandé, et un export à moitié écrit ne
    mélange pas l'ancien et le nouveau.
    """
    dossier = Path(dossier)
    rendered = [(dossier / f"{f.name}.{f.format}", render(f)) for f in fichiers]
    if not overwrite:
        present = [p.name for p, _ in rendered if p.exists()]
        if present:
            raise FileExistsError(f"déjà présent(s) dans « {dossier} » : {', '.join(present)} — "
                                  "autoriser le remplacement, ou changer la destination")
    dossier.mkdir(parents=True, exist_ok=True)
    ecrits: List[Path] = []
    for path, text in rendered:
        path.write_text(text, encoding='utf-8')
        ecrits.append(path)
    return ecrits


def grouping_from_dict(raw: Optional[Mapping[str, Any]]) -> Grouping:
    """Le regroupement d'un nœud de sortie (JSON) — les deux axes de `Grouping`, rien d'autre."""
    raw = raw or {}
    return Grouping(lots=bool(raw.get('lots')), declarations=bool(raw.get('declarations')))


def export_lots(declarations: Sequence[Any], lots: Sequence[Any], folder, *,
                grouping: Optional[Grouping] = None, overwrite: bool = False) -> List[Path]:
    """L'export d'un NŒUD DE SORTIE : des déclarations appliquées à des bases connectées.

    `declarations` : des `Declaration` ou leur forme sérialisée (`declaration_from_dict`, validée
    comme à la construction) ; `lots` : des `ConnectedLot` (`connector.connect`). Chaque base ne lit
    QUE les flux que les déclarations citent. Deux bases de même nom (deux `essai_01` dans deux
    sous-dossiers) sont refusées : leurs lignes deviendraient indiscernables dans un export
    concaténé, et leurs fichiers s'écraseraient l'un l'autre."""
    from ...core.export import declaration_from_dict
    decls = [d if isinstance(d, Declaration) else declaration_from_dict(d) for d in declarations]
    if not decls:
        raise ValueError("aucune déclaration d'export")
    if not lots:
        raise ValueError("aucune base connectée en entrée")
    names = [lot.name for lot in lots]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"bases de même nom : {', '.join(duplicates)} — impossible de dire de "
                         "laquelle vient une ligne")
    streams = list(dict.fromkeys(s for d in decls for s in d.stream))
    frames = {lot.name: lot.frames(streams) for lot in lots}
    metas = {lot.name: lot.meta for lot in lots}
    return write(exporter_frames(decls, frames, metas, grouping), folder, overwrite=overwrite)
