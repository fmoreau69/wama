"""Schéma déclaratif des paramètres Enhancer — un schéma PAR DOMAINE (multi-domaine).

Enhancer est multi-domaine (image/vidéo + audio). Chaque domaine a son propre jeu de réglages, câblé
au volet droit correspondant (#imgSettings / #audioSettings) ET à la modale (WamaParams context:'item').
Les dom_id pointent sur les champs du template. Le format/qualité de sortie est partagé (brique commune).

Descriptions modèles (courtes + longues) = métadonnée-driven via help_fallback {valeur: {description,
description_long, recommended_vram_gb}} — mécanisme d'aide modèle (WamaModelHelp), pour les modèles hors
catalogue model_manager. Image/vidéo : dérivées de MODELS_INFO (source unique). Audio : curées.
"""
from wama.common.utils.output_formats import (
    get_output_formats, get_output_qualities, output_format_params,
)
from wama.common.utils.param_schema import Param, schema_to_dicts
from wama.enhancer.models import Enhancement
from wama.common.backends.ai_upscaler import MODELS_INFO


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
    Param(name='ai_model', type='select', label='Modèle AI', icon='fa-brain', chip=True,
          dom_id={'panel': 'defaultAiModel', 'item': 'settingsAiModel'}, contexts=('panel', 'item'),
          # ── Route F4b (2026-09-08) — les OPTIONS viennent du catalogue ────────────────
          # `choices` (les 7 valeurs d'`AI_MODEL_CHOICES`) restent le REPLI rendu avant que
          # la requête réponde ; la liste servie, elle, est celle du catalogue : un modèle
          # d'upscaling installé apparaît désormais sans toucher au code.
          # Domaine = `source` + `model_type`, et les DEUX sont nécessaires :
          #   • sans `model_type`, la source rendait les 9 modèles de l'enhancer, dont les
          #     2 moteurs AUDIO (un select d'upscaling proposant un débruiteur de voix) ;
          #   • une tâche unique ne convient pas — les 7 se partagent `upscale` (5) et
          #     `denoise` (2, les IRCNN) ; `model_type='upscaling'` est la catégorie qui
          #     les réunit, et c'est la taxonomie du catalogue, pas une invention d'ici.
          # `source` maintient aussi l'ESPACE DE CLÉS : identifiants nus ('BSRGANx4'), ceux
          # que `Enhancement.ai_model` porte et que `tasks.py` recompose en
          # `enhancer:<id>` pour résoudre son backend.
          # Pas d'`options_auto` : l'enhancer ne RÉSOUT pas « auto » — l'utilisateur désigne
          # son moteur (c'est aussi pourquoi le critère `select_model` y est non applicable).
          options_source='catalog',
          options_query={'source': 'enhancer', 'model_type': 'upscaling'},
          choices=list(Enhancement.AI_MODEL_CHOICES),
          # Catalogue (desc + VRAM) branchable depuis l'ALIGNEMENT des model_key (18/08,
          # artefact _fp16 retiré : clés = valeurs d'option) ; le repli statique reste.
          help_source='enhancer',
          help_fallback=MEDIA_MODEL_HELP),
    Param(name='denoise', type='toggle', label='Débruitage', icon='fa-broom',
          chip=True, chip_label='Débruitage',
          dom_id={'panel': 'defaultDenoise', 'item': 'settingsDenoise'}, contexts=('panel', 'item')),
    Param(name='blend_factor', type='range', label='Blend', icon='fa-sliders-h', chip=True,
          dom_id={'panel': 'defaultBlendFactor', 'item': 'settingsBlendFactor'},
          min=0, max=1, step=0.1, contexts=('panel', 'item')),
]

# ── Domaine AUDIO — modèle AudioEnhancement ───────────────────────────────────
# 'strength' colle à la card data-strength (le champ modèle est denoising_strength, mappé côté vue).
AUDIO_PARAMS = [
    Param(name='engine', type='select', label='Moteur', icon='fa-cogs', chip=True,
          dom_id={'panel': 'audioEngine', 'item': 'settingsAudioEngine'}, contexts=('panel', 'item'),
          # Options du CATALOGUE (route F4b, 2026-09-08) — `enhancer:resemble` et
          # `enhancer:deepfilternet` y sont, avec la tâche `audio-enhance` : le commentaire
          # « moteurs audio HORS catalogue » qui vivait ici était PÉRIMÉ (mesuré). Domaine
          # par `source` + `task` : c'est la tâche qui sépare les moteurs audio des 7
          # modèles d'upscaling de la même source. Clés nues = valeurs d'`engine`.
          options_source='catalog',
          options_query={'source': 'enhancer', 'task': 'audio-enhance'},
          choices=[('resemble', 'Resemble Enhance (Recommandé)'),
                   ('deepfilternet', 'DeepFilterNet 3 (Rapide — temps réel)')],
          help_source='enhancer',   # moteurs audio au catalogue (déjà alignés) ; repli statique
          help_fallback=AUDIO_ENGINE_HELP),
    # mode/force/qualité = spécifiques Resemble → affichés seulement si engine=resemble (show_if).
    Param(name='mode', type='select', label='Mode', icon='fa-sliders-h', chip=True,
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

# ── Format/qualité de SORTIE (la docstring le PROMETTAIT « via la brique commune » sans
# jamais le câbler — la modale n'offrait pas le choix, constat Fabien 18/08).
# MEDIA : un Enhancement est image OU vidéo PAR ITEM → la brique app-level ne sait déduire
# qu'UN domaine ; on suit le contrat du VOLET (index.html) : select UNION en optgroups
# Image/Vidéo + « Original », choix sourcés de la brique COMMUNE (get_output_formats).
def _media_format_groups():
    img = [c for c in get_output_formats('image') if c[0] != 'original']
    vid = [c for c in get_output_formats('video') if c[0] != 'original']
    return [('Conserver', [('original', 'Original (inchangé)')]),
            ('Image', img), ('Vidéo', vid)]


MEDIA_PARAMS += [
    Param(name='output_format', type='select', label='Format de sortie', icon='fa-file-export',
          chip=True, option_groups=_media_format_groups(),
          dom_id={'panel': 'output_format', 'item': 'settingsOutputFormat'},
          contexts=('panel', 'item'),
          help='Doit correspondre au type du média (image ou vidéo).'),
    Param(name='output_quality', type='select', label='Qualité', icon='fa-sliders',
          choices=get_output_qualities('image'),
          dom_id={'panel': 'output_quality', 'item': 'settingsOutputQuality'},
          contexts=('panel', 'item')),
]

# AUDIO : domaine déterministe → brique telle quelle (item seulement : le volet audio n'a
# pas de champs de sortie — la valeur voyage par la modale → gear → payload de start).
AUDIO_PARAMS += output_format_params(
    'audio', contexts=('item',),
    dom_id_format={'item': 'settingsAudioOutputFormat'},
    dom_id_quality={'item': 'settingsAudioOutputQuality'},
)

MEDIA_PARAMS_JSON = schema_to_dicts(MEDIA_PARAMS)
AUDIO_PARAMS_JSON = schema_to_dicts(AUDIO_PARAMS)
