"""Surfaces de l'anonymizer — DÉCLARÉES, servies par les vues communes (`common/surface_views`).

La page de correction des détections suit la NATURE du média (décision de Fabien, 2026-11-15 :
« la page d'édition suit simplement la nature du fichier traité », sans onglet) — une surface par
nature, chacune réservée à la sienne (`Surface.only`) : la card n'en propose qu'une.

`review` (2026-10-10, 1ʳᵉ surface du chantier SURFACES) : corriger les détections d'une IMAGE —
ajouter une zone oubliée (un visage, une plaque), retirer une fausse alerte. Les corrections
vivent à part du document du détecteur (`Media.detection_corrections`, décision de Fabien) et le
Floutage les surveille : enregistrer le périme, « Appliquer » le rejoue.

`review_video` (2026-11-15) : les mêmes gestes sur une VIDÉO, image par image — la même brique
des zones, posée sur l'axe partagé, et le transport commun (lecture, sauts, pas d'une image). Une
correction porte l'indice de l'image où elle est faite (`i`), que le floutage relit
(`detections.apply_corrections`).
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
    only={'media_type': 'image'},
    # Assainies : une ancienne sauvegarde a laissé 'false' dans des listes de classes.
    context={'classes': lambda media: sane_classes(media.classes2blur)},
    # L'élément témoin des vignettes du catalogue des briques (nocturne) : une image et ses
    # détections ; `media_type` et `file_ext` sont ce que l'import de l'app poserait.
    witness={'file': '.png', 'detections_file': 'detections', 'media_type': 'image',
             'file_ext': '.png'}))

register_surface(Surface(
    app='anonymizer', key='review_video', label='Corriger les détections',
    model='anonymizer.Media',
    slots=(BrickSlot('video', 'image_boxes', 0, 0, 9, 12,
                     {'role': 'video', 'video': True, 'title': 'Vidéo et zones'}),
           # Les commandes seules : la vidéo est posée sur l'axe par la brique des zones.
           BrickSlot('transport', 'media_transport', 0, 12, 9, 2, {'media': False, 'jump': 5}),
           BrickSlot('objects', 'object_list', 9, 0, 3, 9),
           BrickSlot('actions', 'surface_actions', 9, 9, 3, 5)),
    reads={'video': 'file', 'detections': 'detections_file'},
    documents=('detections',),
    edits='detection_corrections', validate=validate_corrections,
    reruns='blur', available=_review_available,
    only={'media_type': 'video'},
    context={'classes': lambda media: sane_classes(media.classes2blur)},
    # Le témoin des vignettes : la mire du harnais et des détections (celles de l'image témoin,
    # posées sur sa première image).
    witness={'file': '.mp4', 'detections_file': 'detections', 'media_type': 'video',
             'file_ext': '.mp4'}))
