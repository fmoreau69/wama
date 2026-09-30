"""Lignes de CATALOGUE réalistes pour les tests du transcriber (route F4b ⑦, 2026-09-30).

Depuis que le moteur d'un modèle se RÉSOUT par le catalogue (`backend_for_key` : le modèle porte
son moteur, `composition.runtime.engine`), une ligne de test sans moteur ne mène nulle part — la
table par sous-chaîne qui s'en passait est tombée. Ces lignes déclarent ce que déclarent celles
de la production (mesuré le 2026-09-30), en UN seul endroit pour les trois fichiers qui en ont
besoin. Pas un module de tests : aucun test ici.
"""

#: Moteur de chaque modèle local de transcription, tel que le catalogue le déclare.
ENGINES = {
    'transcriber:whisper': 'faster-whisper',
    'transcriber:vibevoice-asr': 'vibevoice',
    'transcriber:qwen3-asr-0.6b': 'transformers',
    'transcriber:qwen3-asr-1.7b': 'transformers',
    'transcriber:canary-1b-v2': 'nemo',
    'transcriber:parakeet-tdt-0.6b-v3': 'nemo',
}


def transcription_row(model_key, engine=None, **fields):
    """Une ligne `AIModel` de tâche transcription, moteur déclaré."""
    from wama.model_manager.models import AIModel
    source, _, model_id = model_key.partition(':')
    return AIModel.objects.create(**{
        'model_key': model_key, 'name': model_id, 'source': source, 'model_type': 'speech',
        'is_available': True, 'is_downloaded': True,
        'composition': {'runtime': {'engine': engine or ENGINES[model_key]}},
        'capabilities': {'task': 'transcription', 'inputs_required': ['work_audio'],
                         'modalities': ['audio']},
        **fields})


def transcription_catalogue(*keys):
    """Les lignes de `keys` (toutes celles d'`ENGINES` par défaut)."""
    return [transcription_row(key) for key in (keys or ENGINES)]
