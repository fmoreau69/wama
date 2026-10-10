"""Surfaces de l'anonymizer — DÉCLARÉES, servies par les vues communes (`common/surface_views`).

`review` (2026-10-10, 1ʳᵉ surface du chantier SURFACES) : corriger les détections d'une IMAGE —
ajouter une zone oubliée (un visage, une plaque), retirer une fausse alerte. Les corrections
vivent à part du document du détecteur (`Media.detection_corrections`, décision de Fabien) et le
Floutage les surveille : enregistrer le périme, « Appliquer » le rejoue.
Images d'abord (décision de Fabien) : la vidéo attend l'axe commun du chantier.
"""
from wama.anonymizer.utils.media_utils import sane_classes
from wama.common.surfaces import BrickSlot, Surface, register_surface

#: Plafonds de validation : une correction est un geste humain, pas un flux.
MAX_CORRECTIONS = 20000


def _box(value):
    box = [float(v) for v in value]
    if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"zone invalide : {value}")
    return [round(v, 1) for v in box]


def validate_corrections(value) -> dict:
    """La couche de corrections assainie — `{added: [{i, box, label}], removed: [{i, box}]}`."""
    if not isinstance(value, dict):
        raise ValueError("corrections : un objet est attendu")
    added = [{'i': int(a.get('i', 0)), 'box': _box(a['box']),
              'label': str(a.get('label') or 'face')[:64]} for a in value.get('added') or []]
    removed = [{'i': int(r.get('i', 0)), 'box': _box(r['box'])} for r in value.get('removed') or []]
    if len(added) + len(removed) > MAX_CORRECTIONS:
        raise ValueError(f"corrections : plus de {MAX_CORRECTIONS} gestes")
    return {'added': added, 'removed': removed} if (added or removed) else {}


def _review_available(media) -> tuple:
    if getattr(media, 'media_type', '') != 'image':
        return False, "La correction s'ouvre sur une image ; la vidéo viendra avec le lecteur commun."
    if not media.detections_file:
        return False, "Aucune détection : lancer d'abord la détection."
    return True, ''


register_surface(Surface(
    app='anonymizer', key='review', label='Corriger les détections',
    model='anonymizer.Media',
    slots=(BrickSlot('image', 'image_boxes', 0, 0, 9, 14),
           BrickSlot('objects', 'object_list', 9, 0, 3, 9),
           BrickSlot('actions', 'surface_actions', 9, 9, 3, 5)),
    reads={'image': 'file', 'detections': 'detections_file'},
    documents=('detections',),
    edits='detection_corrections', validate=validate_corrections,
    reruns='blur', available=_review_available,
    # Assainies : une ancienne sauvegarde a laissé 'false' dans des listes de classes.
    context={'classes': lambda media: sane_classes(media.classes2blur)}))
