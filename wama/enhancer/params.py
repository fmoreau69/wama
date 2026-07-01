"""Schéma déclaratif des paramètres Enhancer — un schéma PAR DOMAINE (multi-domaine).

Enhancer est multi-domaine (image/vidéo + audio). Chaque domaine a son propre jeu de réglages, câblé
au volet droit correspondant (#imgSettings / #audioSettings). Les dom_id pointent sur les champs
existants du template → l'inspecteur (WamaInspector.initFromSchema) lit/écrit ces champs sans HTML
par app. Le format/qualité de sortie est partagé (brique commune) et n'est pas dupliqué ici.
"""
from wama.common.utils.param_schema import Param, schema_to_dicts

# ── Domaine MEDIA (image / vidéo) — modèle Enhancement ────────────────────────
MEDIA_PARAMS = [
    Param(name='ai_model', type='select', label='Modèle AI', icon='fa-brain',
          dom_id='defaultAiModel', contexts=('panel', 'item'),
          help_source='enhancer', help_fallback='Moteur d\'upscaling / débruitage.'),
    Param(name='denoise', type='toggle', label='Débruitage', icon='fa-broom',
          dom_id='defaultDenoise', contexts=('panel', 'item'),
          help_fallback='Applique un débruitage avant l\'upscaling.'),
    Param(name='blend_factor', type='range', label='Blend', icon='fa-sliders-h',
          dom_id='defaultBlendFactor', min=0, max=1, step=0.1, contexts=('panel', 'item'),
          help_fallback='Mélange IA ↔ original (0 = 100% IA, 1 = 100% original).'),
]

# ── Domaine AUDIO — modèle AudioEnhancement ───────────────────────────────────
AUDIO_PARAMS = [
    Param(name='engine', type='select', label='Moteur', icon='fa-cogs',
          dom_id='audioEngine', contexts=('panel', 'item'),
          choices=[('resemble', 'Resemble Enhance (Recommandé)'),
                   ('deepfilternet', 'DeepFilterNet 3 (Rapide — temps réel)')],
          help_fallback='Moteur de restauration audio.'),
    Param(name='mode', type='select', label='Mode', icon='fa-sliders-h',
          dom_id='audioMode', contexts=('panel', 'item'),
          choices=[('both', 'Débruitage + Amélioration (Recommandé)'),
                   ('denoise', 'Débruitage seul (Rapide)'),
                   ('enhance', 'Amélioration seule')],
          help_fallback='Type de traitement audio.'),
    Param(name='denoising_strength', type='range', label='Force', icon='fa-wind',
          dom_id='audioDenoisingStrength', min=0, max=1, step=0.1, contexts=('panel', 'item'),
          help_fallback='Intensité du débruitage.'),
    Param(name='quality', type='select', label='Qualité (NFE)', icon='fa-star',
          dom_id='audioQuality', contexts=('panel', 'item'),
          choices=[('32', 'Rapide (32 étapes)'),
                   ('64', 'Équilibré (64 étapes)'),
                   ('128', 'Meilleur (128 étapes)')],
          help_fallback='Nombre d\'étapes de génération (Resemble).'),
]

MEDIA_PARAMS_JSON = schema_to_dicts(MEDIA_PARAMS)
AUDIO_PARAMS_JSON = schema_to_dicts(AUDIO_PARAMS)
