"""Schéma déclaratif des paramètres Enhancer — un schéma PAR DOMAINE (multi-domaine).

Enhancer est multi-domaine (image/vidéo + audio). Chaque domaine a son propre jeu de réglages, câblé
au volet droit correspondant (#imgSettings / #audioSettings) ET à la modale (WamaParams context:'item').
Les dom_id pointent sur les champs du template. Le format/qualité de sortie est partagé (brique commune).

Descriptions modèles (courtes + longues) = métadonnée-driven via help_fallback {valeur: {description,
description_long, recommended_vram_gb}} — mécanisme d'aide modèle (WamaModelHelp), pour les modèles hors
catalogue model_manager. Image/vidéo : dérivées de MODELS_INFO (source unique). Audio : curées.
"""
from wama.common.utils.param_schema import Param, schema_to_dicts
from wama.enhancer.models import Enhancement
from wama.enhancer.utils.ai_upscaler import MODELS_INFO


def _media_model_help():
    """Aide modèle image/vidéo (courte + longue) dérivée de MODELS_INFO — source unique."""
    out = {}
    for key, info in MODELS_INFO.items():
        desc = info.get('description', '')
        scale, vram, file = info.get('scale'), info.get('vram_usage'), info.get('file', '')
        if scale and scale > 1:
            long = f"{desc}. Facteur d'agrandissement ×{scale}"
        elif scale == 1:
            long = f"{desc}. Débruitage sans agrandissement (×1)"
        else:
            long = desc
        if vram:
            long += f", ~{vram} GB VRAM"
        long += f" — ONNX ({file})." if file else "."
        out[key] = {'description': desc, 'description_long': long, 'recommended_vram_gb': vram}
    return out


MEDIA_MODEL_HELP = _media_model_help()

# Aide moteurs audio (hors catalogue) — courte + longue, curée.
AUDIO_ENGINE_HELP = {
    'resemble': {
        'description': 'Restauration par diffusion — débruitage + extension de bande, meilleure qualité',
        'description_long': (
            "Resemble Enhance : modèle génératif (diffusion) qui débruite ET restaure les hautes "
            "fréquences (super-résolution audio). Qualité supérieure mais plus lent ; les réglages "
            "Mode / Force / Qualité (NFE) s'appliquent. Idéal pour des voix dégradées."),
        'recommended_vram_gb': 4,
    },
    'deepfilternet': {
        'description': 'Débruitage temps réel — rapide, faible empreinte',
        'description_long': (
            "DeepFilterNet 3 : débruitage discriminatif temps réel (48 kHz), très rapide et léger, "
            "sans extension de bande. Recommandé pour prétraiter avant transcription. Les réglages "
            "Mode / Force / Qualité ne s'appliquent pas."),
        'recommended_vram_gb': 1,
    },
}

# ── Domaine MEDIA (image / vidéo) — modèle Enhancement ────────────────────────
# name = clé POST (update_settings) ET data-attr de la card ; dom_id.panel/item = ids des champs volet/modale.
MEDIA_PARAMS = [
    Param(name='ai_model', type='select', label='Modèle AI', icon='fa-brain',
          dom_id={'panel': 'defaultAiModel', 'item': 'settingsAiModel'}, contexts=('panel', 'item'),
          choices=list(Enhancement.AI_MODEL_CHOICES),
          help_fallback=MEDIA_MODEL_HELP),
    Param(name='denoise', type='toggle', label='Débruitage', icon='fa-broom',
          dom_id={'panel': 'defaultDenoise', 'item': 'settingsDenoise'}, contexts=('panel', 'item')),
    Param(name='blend_factor', type='range', label='Blend', icon='fa-sliders-h',
          dom_id={'panel': 'defaultBlendFactor', 'item': 'settingsBlendFactor'},
          min=0, max=1, step=0.1, contexts=('panel', 'item')),
]

# ── Domaine AUDIO — modèle AudioEnhancement ───────────────────────────────────
# 'strength' colle à la card data-strength (le champ modèle est denoising_strength, mappé côté vue).
AUDIO_PARAMS = [
    Param(name='engine', type='select', label='Moteur', icon='fa-cogs',
          dom_id={'panel': 'audioEngine', 'item': 'settingsAudioEngine'}, contexts=('panel', 'item'),
          choices=[('resemble', 'Resemble Enhance (Recommandé)'),
                   ('deepfilternet', 'DeepFilterNet 3 (Rapide — temps réel)')],
          help_fallback=AUDIO_ENGINE_HELP),
    # mode/force/qualité = spécifiques Resemble → affichés seulement si engine=resemble (show_if).
    Param(name='mode', type='select', label='Mode', icon='fa-sliders-h',
          dom_id={'panel': 'audioMode', 'item': 'settingsAudioMode'}, contexts=('panel', 'item'),
          choices=[('both', 'Débruitage + Amélioration (Recommandé)'),
                   ('denoise', 'Débruitage seul (Rapide)'),
                   ('enhance', 'Amélioration seule')],
          show_if={'field': 'engine', 'equals': 'resemble'}),
    Param(name='strength', type='range', label='Force débruitage', icon='fa-wind',
          dom_id={'panel': 'audioDenoisingStrength', 'item': 'settingsAudioStrength'},
          min=0, max=1, step=0.1, contexts=('panel', 'item'),
          show_if={'field': 'engine', 'equals': 'resemble'}),
    Param(name='quality', type='select', label='Qualité (NFE)', icon='fa-star',
          dom_id={'panel': 'audioQuality', 'item': 'settingsAudioQuality'}, contexts=('panel', 'item'),
          choices=[('32', 'Rapide (32 étapes)'),
                   ('64', 'Équilibré (64 étapes)'),
                   ('128', 'Meilleur (128 étapes)')],
          show_if={'field': 'engine', 'equals': 'resemble'}),
]

MEDIA_PARAMS_JSON = schema_to_dicts(MEDIA_PARAMS)
AUDIO_PARAMS_JSON = schema_to_dicts(AUDIO_PARAMS)
