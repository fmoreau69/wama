"""
Mapping ETA spécifique au Describer (app multi-modale).

Le Describer traite image / vidéo / audio / texte avec des coûts très différents.
On NE peut PAS utiliser une seule unité : on choisit la grandeur du domaine selon le
type de contenu, et on garde une clé ETA par type (`describer:{content_type}`) pour que
l'apprentissage EMA ne mélange pas un clip d'1 h et une image unique.

Utilisé par `workers.py` (record_run) ET `views.py::progress` (estimate) → source unique.
"""
from __future__ import annotations


def eta_size_unit(content_type: str, description) -> tuple[float, str]:
    """(size, unit) pour le seeding ETA selon le type de contenu décrit.

    - vidéo  → durée en secondes (`video_sec`)
    - audio  → durée en secondes (`audio_sec`)
    - image / texte / pdf → 1 élément (`item`) — durée gouvernée par le modèle, pas la taille.
    """
    ct = (content_type or '').lower()
    dur = float(getattr(description, 'duration_seconds', 0) or 0)
    if ct == 'video':
        return (dur or 1.0), 'video_sec'
    if ct == 'audio':
        return (dur or 1.0), 'audio_sec'
    return 1.0, 'item'
