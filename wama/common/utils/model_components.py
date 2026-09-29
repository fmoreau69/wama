"""
Fichiers des COMPOSANTS DÉCLARÉS d'un modèle installé — la moitié « exécution » de l'anatomie.

L'anatomie d'un modèle se déclare UNE fois (`AIModel.composition.components`, projetée du
manifeste `model`) et deux consommateurs la lisent : l'installation (quels fichiers tirer —
`patterns_from_composition`) et le backend (quoi charger). La seconde lecture n'avait pas de
brique : `KokoroOnnxBackend` la réécrit à la main, clé de catalogue et motifs codés en dur
(`kokoro_onnx_backend._declared_patterns`, `_snapshot_dir`). Un backend ÉCRIT PAR UN RÔLE LLM
(marche B2, 2026-09-29) la réécrirait à son tour — c'est ce que ce module évite : il reçoit une
CLÉ et rend des CHEMINS, rien d'autre à deviner.

Le dossier du dépôt vient de `model_installer.weights_dir_of` (le même lien que la
désinstallation et `persist_weights`) ; la révision est celle que désigne `refs/main`, sinon la
plus récente.
"""
from __future__ import annotations

from pathlib import Path


class ComponentsUnavailable(RuntimeError):
    """Le modèle n'est pas installé, ou un composant déclaré est absent du disque — DIT."""


def snapshot_dir(model) -> Path | None:
    """Dossier du snapshot d'une ligne de catalogue installée (révision de `refs/main`, sinon la
    plus récente), ou le dossier déclaré lui-même quand il n'a pas la disposition HF."""
    from wama.model_manager.services.model_installer import weights_dir_of
    repo = weights_dir_of(model)
    if repo is None:
        return None
    snapshots = repo / 'snapshots'
    if not snapshots.is_dir():
        return repo if repo.is_dir() else None
    ref = repo / 'refs' / 'main'
    if ref.is_file():
        pinned = snapshots / ref.read_text(encoding='utf-8').strip()
        if pinned.is_dir():
            return pinned
    revs = sorted((d for d in snapshots.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
    return revs[-1] if revs else None


def component_paths(model_key: str) -> dict:
    """`{rôle: Path}` pour chaque composant DÉCLARÉ du modèle `model_key`.

    Un motif qui désigne plusieurs fichiers rend le premier par ordre de nom ; un composant
    introuvable LÈVE `ComponentsUnavailable` avec son rôle et son motif — un backend qui
    chargerait sans lui échouerait plus loin, avec un message moins clair.
    """
    from wama.model_manager.models import AIModel
    row = AIModel.objects.filter(model_key=model_key).first()
    if row is None:
        raise ComponentsUnavailable(f"{model_key} : absent du catalogue")
    components = ((row.composition or {}).get('components') or [])
    if not components:
        raise ComponentsUnavailable(
            f"{model_key} : aucune anatomie déclarée (composition.components) — rôle `model`, "
            "puis Valider au model manager")
    root = snapshot_dir(row)
    if root is None:
        raise ComponentsUnavailable(f"{model_key} : poids introuvables sur le disque")
    paths = {}
    for comp in components:
        role, pattern = comp.get('role'), comp.get('pattern')
        if not role or not pattern:
            continue
        found = sorted(root.glob(pattern)) or sorted(root.rglob(pattern))
        if not found:
            raise ComponentsUnavailable(
                f"{model_key} : composant « {role} » absent ({pattern} sous {root})")
        paths[role] = found[0]
    return paths
