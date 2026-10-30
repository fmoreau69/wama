"""Les mesures d'une session d'analyse en SÉRIE TEMPORELLE du monde Data (2026-10-29).

Le face_analyzer écrit, image par image, ce que ses modules rendent (`AnalysisFrame` : rPPG, regard,
émotions, respiration, pose de la tête — chacun par son `to_dict()`). Ici ces lignes deviennent UNE
donnée typée, `TypedFrame(DataType.TIMESERIES)` : `time` + une colonne numérique par mesure, avec
libellé et unité DÉCLARÉS dans ses méta (`meta['columns']`). C'est ce que lisent les briques UI
universelles de la surface d'analyse (`surfaces.py`) — les premiers plugins graphiques du monde Data
(`WAMA_DATA_WORLD §8.4`) —, jamais une forme propre au face_analyzer.

Une colonne se DÉCLARE (`COLUMNS`) : son nom, son libellé, son unité et le chemin de sa valeur dans
le JSON qu'un module a écrit — la forme de son `to_dict()`, lue telle quelle. Une colonne vide sur
toute la session (un module non activé) n'est pas rendue.
"""
from __future__ import annotations

from wama.common.backends.emotions import EmotionRecognizer


def _percent(value):
    return None if value is None else round(value * 100, 1)


#: (colonne, libellé, unité, champ de `AnalysisFrame`, chemin dans son JSON, transformation).
COLUMNS = (
    ('heart_rate', 'Fréquence cardiaque', 'BPM', 'rppg_data', ('heart_rate',), None),
    ('spo2', 'SpO2', '%', 'rppg_data', ('spo2',), None),
    ('hrv_rmssd', 'Variabilité cardiaque (RMSSD)', 'ms', 'rppg_data', ('hrv', 'rmssd'), None),
    ('hrv_sdnn', 'Variabilité cardiaque (SDNN)', 'ms', 'rppg_data', ('hrv', 'sdnn'), None),
    ('respiration_rate', 'Respiration', '/min', 'respiration_data', ('respiratory_rate',), None),
    ('perclos', 'PERCLOS (yeux fermés)', '%', 'eye_tracking_data', ('perclos',), _percent),
    ('blink_rate', 'Clignements', '/min', 'eye_tracking_data', ('blink', 'blink_rate'), None),
    ('gaze_horizontal', 'Regard horizontal', '°', 'eye_tracking_data', ('gaze', 'horizontal'), None),
    ('gaze_vertical', 'Regard vertical', '°', 'eye_tracking_data', ('gaze', 'vertical'), None),
    ('pupil', 'Diamètre pupillaire (relatif)', '', 'eye_tracking_data',
     ('pupil', 'average_diameter'), None),
    ('valence', 'Valence', '', 'emotion_data', ('valence',), None),
    ('arousal', 'Activation', '', 'emotion_data', ('arousal',), None),
) + tuple(
    # Les émotions : celles que le module commun déclare (`EmotionRecognizer.EMOTION_LABELS`), sous
    # le nom qu'il leur donne (`EMOTION_NAMES`).
    (f'emotion_{name}', EmotionRecognizer.EMOTION_NAMES.get(name, name), '', 'emotion_data',
     ('emotions', name), None)
    for name in EmotionRecognizer.EMOTION_LABELS
) + tuple(
    (f'head_{axis}', f'Tête — {label}', '°', 'head_pose', (axis,), None)
    for axis, label in (('yaw', 'lacet'), ('pitch', 'tangage'), ('roll', 'roulis'))
)


def _at(document, path):
    value = document
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def frame_values(frame) -> dict:
    """Les valeurs d'UNE image, colonne par colonne (None quand le module n'a rien rendu)."""
    out = {'time': float(frame.timestamp)}
    for name, _label, _unit, field, path, transform in COLUMNS:
        value = _at(getattr(frame, field, None), path)
        out[name] = transform(value) if transform else value
    return out


def session_series(session):
    """La série temporelle d'une session : `TypedFrame(DataType.TIMESERIES)`."""
    import pandas as pd

    from wama.common.catalog.data_types import DataType, TypedFrame

    from .models import AnalysisFrame
    rows = [frame_values(f) for f in AnalysisFrame.objects.filter(session=session).order_by('frame_number')]
    df = pd.DataFrame(rows, columns=['time'] + [c[0] for c in COLUMNS])
    df = df.dropna(axis='columns', how='all') if len(df) else df[['time']]
    kept = set(df.columns)
    return TypedFrame(df, DataType.TIMESERIES, meta={
        'source': 'face_analyzer',
        'columns': {name: {'label': label, 'unit': unit}
                    for name, label, unit, *_rest in COLUMNS if name in kept},
    })
