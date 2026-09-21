"""Backends de l'enhancer — la FRONTIÈRE de l'app (portage 2026-09-21, marche B1).

Les CLASSES vivent au substrat depuis le 06/09 (`wama/common/backends/ai_upscaler.py`,
`wama/common/backends/audio_enhancer.py`, contrat `BaseModelBackend`) et se DÉRIVENT du
catalogue (`backend_for_key('enhancer:<id>')`). Ce paquet ne porte que ce qui reste une
décision d'app : le ROUTAGE nature → callable au contrat commun (« ce n'est pas un reste,
c'est la frontière », 8c556100), que `tasks_gen` compose en corps de tâche.
"""

#: ── ROUTAGE nature → backend : LA déclaration que la chaîne de génération COMPOSE ─────────
#: CONTRAT COMMUN « fichier » (pilote converter, 2026-09-02) :
#:     callable(input_path, output_path, output_format, options=dict, progress_callback=fn)
#: `options` = valeurs EFFECTIVES lues des colonnes (modèle événementiel §23.2quater — pour
#: l'enhancer : le modèle RÉSOLU par la glu quand la colonne dit « auto », puis
#: denoise/blend/tile, ou moteur/mode/force/NFE côté audio). `output_format` est reçu et
#: IGNORÉ par les trois routes : la conversion de sortie est un geste de la glu (converter
#: inline, `_apply_enhancer_output_format`), le fichier produit garde son format natif.
#: La route vidéo accepte en plus `frame_callback(frame, index)` (aperçu « pendant »), optionnel.
#:
#: Chemins EN CHAÎNES (pas d'imports) : la déclaration se lit sans rien charger (extracteur
#: de manifeste), et la jumelle qui copie `backends/` résout vers SES copies via son propre
#: chemin de paquet (le composeur remplace le préfixe d'app).
ROUTES = {
    'image': 'backends.media_backend.enhance_image',
    'video': 'backends.media_backend.enhance_video',
    'audio': 'backends.audio_backend.enhance_audio',
}

#: Colonne du modèle d'item qui porte la NATURE (clé de ROUTES) — `Enhancement.media_type`
#: (image/vidéo). La branche AUDIO a son propre modèle (`AudioEnhancement`) sans colonne de
#: nature : sa tâche route sur la constante 'audio'.
NATURE_FIELD = 'media_type'

__all__ = ['ROUTES', 'NATURE_FIELD']
