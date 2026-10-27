"""Surfaces du transcriber — DÉCLARÉES, servies par les vues communes (`common/surface_views`).

`correct` (2026-10-21, 4ᵉ surface, `ROUTE §F3b` étape 2 — décisions de Fabien le même jour) : la
page de CORRECTION, qui était écrite à la main (`edit.html` + `edit.js`, 1 450 lignes), est
COMPOSÉE de briques universelles, en gardant son apparence : la liste des segments au centre, en
bas le TEMPS — la ligne de temps (onde fenêtrée et ses couches : silences, bornes, bandes
d'écriture ; bande de qualité, minimap, zoom, outil Bornes), le transport (aller à, sauts,
vitesse) et l'écriture à la lecture —, et dans la colonne du VOLET droit les actions, le document
(titre, date) et les intervenants. Ces trois briques du temps étaient, jusqu'au redécoupage du
même jour (décision de Fabien : l'axe, le transport, les vues, les outils de domaine), des options
d'un seul transport.

La valeur éditée est la CORRECTION (`corrected_segments_json`) ; la sortie ASR (`segments_json`)
reste immuable et se lit à côté (« charger la dernière transcription », mots de référence de
l'outil Bornes). Titre, date et noms sont des RÉGLAGES de la card, écrits par sa route commune.
Parité attestée geste par geste par le scénario `transcriber.editor_parity` (formes « editor »
et « surface »).
"""
from wama.common.surfaces import BrickSlot, Surface, register_surface

#: Plafond de validation : une transcription de plusieurs heures reste sous quelques milliers.
MAX_SEGMENTS = 100_000


def validate_segments(value) -> list:
    """La correction reçue, CONTRÔLÉE et rendue telle quelle — une liste de segments dont les temps
    se lisent. Rien n'est réécrit : la page compare ce qu'elle a envoyé à ce que le serveur rend."""
    if not isinstance(value, list):
        raise ValueError("segments : une liste est attendue")
    if len(value) > MAX_SEGMENTS:
        raise ValueError(f"segments : plus de {MAX_SEGMENTS}")
    for seg in value:
        if not isinstance(seg, dict):
            raise ValueError("segment : un objet est attendu")
        try:
            float(seg.get('start_time') or 0)
            float(seg.get('end_time') or 0)
        except (TypeError, ValueError):
            raise ValueError(f"segment : temps illisible ({seg.get('start_time')!r})")
        if not isinstance(seg.get('text', ''), str):
            raise ValueError("segment : le texte doit être une chaîne")
    return value


def _segments(transcript):
    """La correction si elle existe, sinon la sortie ASR — locuteurs sous leur forme canonique."""
    from wama.transcriber.views import _editor_segments
    return _editor_segments(transcript)


def _saved(transcript, segments, user, finished):
    from wama.transcriber.views import correction_saved
    correction_saved(transcript, segments, user, finished)


def _available(transcript) -> tuple:
    if transcript.status != 'SUCCESS':
        return False, "La correction n'est disponible qu'après une transcription réussie."
    return True, ''


def _facts(transcript) -> list:
    """Ce que la page montre de l'élément, en lecture seule : `[[icône, texte], …]`."""
    return [[icon, str(text)] for icon, text in (
        ('fa-file-audio', transcript.filename),
        ('fa-clock', transcript.duration_display or '—'),
        ('fa-microchip', transcript.used_backend or 'auto'),
        ('fa-globe', transcript.language or 'auto'),
        ('fa-wave-square', transcript.properties or ''),
    ) if text]


register_surface(Surface(
    app='transcriber', key='correct', label='Corriger la transcription',
    model='transcriber.Transcript',
    # Au centre, le texte et le temps ; au VOLET (sa colonne, 2026-10-21), les actions, le
    # document et les intervenants — là où l'éditeur d'origine les avait.
    slots=(BrickSlot('segments', 'segment_list', 0, 0, 12, 10,
                     {'latest': 'latest', 'names': 'speaker_map'}),
           BrickSlot('timeline', 'media_timeline', 0, 10, 12, 4,
                     {'role': 'audio', 'segments': True, 'quality': True, 'minimap': True,
                      'zoom': True, 'boundaries': 'retime'}),
           BrickSlot('transport', 'media_transport', 0, 14, 12, 2,
                     {'role': 'audio', 'wave': False, 'goto': True, 'speed': 'steps'}),
           BrickSlot('writing', 'playback_writing', 0, 16, 12, 3),
           BrickSlot('actions', 'surface_actions', 0, 0, 1, 6, zone='panel'),
           BrickSlot('document', 'item_settings', 0, 6, 1, 5,
                     {'title': 'Document', 'fields': ['title', 'meeting_date'], 'facts': 'facts'},
                     zone='panel'),
           BrickSlot('speakers', 'speaker_names', 0, 11, 1, 6,
                     {'setting': 'speaker_map', 'suggest': 'suggest_speakers'}, zone='panel')),
    reads={'audio': 'audio', 'latest': 'segments_json'},
    documents=('latest',),
    edits='corrected_segments_json', validate=validate_segments,
    value=_segments, autosave=True,
    finish='Terminer la correction', saved=_saved,
    settings=('title', 'meeting_date', 'speaker_map'),
    # « Écouter » (original, nivellement, débruitage) se retrouve à la prochaine ouverture.
    sources_setting='listened_sources',
    routes={'retime': 'retime_segments', 'write_cursor': 'write_cursor',
            'write_results': 'write_results', 'suggest_speakers': 'suggest_speakers'},
    available=_available,
    # Le ✎ de la card dit brouillon / corrigé d'après l'état que la correction PORTE — sans lire
    # les segments, que la file ne charge pas (`Transcript.QUEUE_DEFERRED_FIELDS`).
    edit_state=lambda t: t.correction_status if t.correction_status in ('draft', 'done') else 'none',
    context={'corrected': lambda t: bool(t.corrected_segments_json), 'facts': _facts},
    # L'élément témoin des vignettes du catalogue des briques (nocturne) : un audio et trois
    # segments, une transcription réussie — rien n'est lancé.
    witness={'audio': '.wav', 'status': 'SUCCESS',
             'segments_json': [{'start_time': i * 2.0, 'end_time': i * 2.0 + 2.0, 'text': word,
                                'speaker_id': 'SPEAKER_00'}
                               for i, word in enumerate(('Témoin', 'de la', 'correction'))]}))
