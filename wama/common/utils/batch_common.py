"""
WAMA Common — Orchestration batch (côté serveur).

Le PARSING des fichiers batch vit dans ``batch_parsers.py`` ; l'UI de détection
et de prévisualisation dans ``static/common/js/batch-import.js`` +
``templates/common/batch_detect_bar.html``.

Ce module formalise la partie restante, jusqu'ici dupliquée/spécifique :
  - regrouper des fichiers par NATURE (image/vidéo/audio/document) — nécessaire
    quand les réglages de sortie sont communs au batch (ex. Converter) ;
  - créer/consolider un batch-of-N à partir d'items déjà créés, via des
    callbacks fournis par chaque app (chaque app conserve son modèle batch).

Conçu pour être branché progressivement dans TOUTES les apps génériques
(on commence par le Converter). Reader/Synthesizer peuvent y migrer ensuite
sans changement de comportement.
"""

from collections import OrderedDict
from typing import Callable, Iterable, List, Optional, Sequence


def group_paths_by_nature(paths: Sequence[str],
                          classifier: Callable[[str], Optional[str]]) -> "OrderedDict[str, List[str]]":
    """Regroupe des chemins par nature de média, en conservant l'ordre d'apparition.

    Args:
        paths:      chemins (ou noms) de fichiers.
        classifier: fonction ``path -> nature`` (ex. 'image'|'video'|'audio'|
                    'document'|'archive') ou ``None`` si non supporté.

    Returns:
        OrderedDict {nature: [paths…]} — les chemins non classables (classifier
        renvoie None) sont ignorés. Permet à l'appelant de créer UN batch par
        nature (réglages de sortie communs à chaque batch).
    """
    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for p in paths:
        nature = classifier(p)
        if not nature:
            continue
        groups.setdefault(nature, []).append(p)
    return groups


def consolidate_into_batch(items: Iterable,
                           *,
                           create_batch: Callable[[int], object],
                           link_item: Callable[[object, object, int], None],
                           unwrap_singletons: Optional[Callable[[List], None]] = None):
    """Crée UN batch-of-N reliant ``items`` (généralise la consolidation reader).

    Chaque app fournit les opérations propres à son modèle batch :

        create_batch(total)            -> instance batch (ex. BatchReadingItem)
        link_item(batch, item, index)  -> crée le lien batch↔item
        unwrap_singletons(item_ids)    -> (optionnel) supprime les batch-of-1
                                          créés au préalable pour ces items
                                          (cas reader : import wrappe en
                                          batch-of-1, puis on consolide).

    Returns:
        l'instance batch créée, ou ``None`` si aucun item.
    """
    items = list(items)
    if not items:
        return None
    if unwrap_singletons:
        unwrap_singletons([getattr(i, 'id', i) for i in items])
    batch = create_batch(len(items))
    for idx, item in enumerate(items):
        link_item(batch, item, idx)
    return batch
