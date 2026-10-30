"""Surfaces du face_analyzer — DÉCLARÉES, servies par les vues communes (`common/surface_views`).

`analysis` (2026-10-29, les premiers plugins graphiques du monde Data — `WAMA_DATA_WORLD §8.4`) :
le CONTENU d'une session d'analyse — la vidéo, horloge de l'axe partagé, et ses mesures image par
image en courbes synchronisées. Une surface en LECTURE SEULE (`edits=None`) : elle montre, rien ne
s'y enregistre. Ses mesures sont une donnée typée du monde Data (`series.session_series` →
`TypedFrame(timeseries)`), jamais une forme propre à l'app. Toutes ses briques sont universelles.

Elle deviendra la page d'édition ouverte depuis la card quand le face_analyzer passera à la file
d'attente commune (décision de Fabien, 2026-10-29) ; le temps réel ira à une page « Live ».
"""
from wama.common.surfaces import BrickSlot, Surface, register_surface

from .series import session_series


def _ready(session):
    """Une session sans vidéo n'a rien à montrer."""
    if not getattr(session.input_file, 'name', ''):
        return False, "Aucune vidéo dans cette session."
    return True, ''


register_surface(Surface(
    app='face_analyzer', key='analysis', label="Analyse faciale",
    model='face_analyzer.AnalysisSession',
    slots=(BrickSlot('video', 'video_view', 0, 0, 6, 9),
           BrickSlot('transport', 'media_transport', 0, 9, 6, 2,
                     {'media': False, 'jump': 5}),
           BrickSlot('heart', 'timeseries_chart', 6, 0, 6, 5,
                     {'title': 'Cœur', 'columns': ['heart_rate', 'spo2']}),
           BrickSlot('variability', 'timeseries_chart', 6, 5, 6, 4,
                     {'title': 'Variabilité cardiaque', 'columns': ['hrv_rmssd', 'hrv_sdnn']}),
           BrickSlot('breathing', 'timeseries_chart', 6, 9, 6, 4,
                     {'title': 'Respiration', 'columns': ['respiration_rate']}),
           BrickSlot('eyes', 'timeseries_chart', 0, 11, 6, 4,
                     {'title': 'Yeux', 'columns': ['perclos', 'blink_rate']}),
           BrickSlot('emotions', 'timeseries_chart', 6, 13, 6, 5,
                     {'title': 'Émotions', 'columns': ['emotion_happy', 'emotion_sad', 'emotion_angry',
                                                       'emotion_fear', 'emotion_surprise',
                                                       'emotion_disgust', 'emotion_neutral']}),
           BrickSlot('head', 'timeseries_chart', 0, 15, 6, 4,
                     {'title': 'Pose de la tête', 'columns': ['head_yaw', 'head_pitch', 'head_roll']})),
    reads={'video': 'input_file'},
    edits=None,
    available=_ready,
    context={'series': lambda session: session_series(session).to_payload()},
    # Le témoin du nocturne (vignettes des briques, `Surface.witness`) : une session terminée et sa
    # vidéo — ses mesures sont des LIGNES d'une autre table, qu'un témoin ne pose pas.
    witness={'input_file': '.mp4', 'status': 'completed'},
))
