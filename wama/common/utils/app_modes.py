"""
Schéma déclaratif DOMAINES → MODES des apps — clé de voûte UX (voir MODES_QUEUE_UX.md).

3 axes distincts :
  1. DOMAINE média (image/vidéo/audio/document) → ONGLET, conditionnel (si >1 domaine). Scope la file.
  2. MODE (dans un domaine) → switch (texte→image, image→image, yolo/sam3, normal/temps-réel).
  3. WORKFLOW (pipeline/standalone) → la MÉTA-APP (PAS modélisé ici).

Hiérarchie : App → Domaine → Mode → {entrées typées + sections de réglages}. Tout est métadonnée-driven :
l'UI (onglets, switch de mode, champs, sections) se GÉNÈRE depuis ce schéma (générateur JS `WamaModes`).

Les ENTRÉES typées (prompt / work_file / reference_file / url / prompt_file) sont AUSSI les futurs
**ports de la méta-app** (typage par connexion : card batch → port travail ; card unitaire → port référence).

Dicts simples (JSON-sérialisables) → exposables tels quels à l'endpoint que `WamaModes` consomme.
"""

# ── Types d'entrée canoniques (= ports de la méta-app) ───────────────────────
INPUT_TYPES = {
    'prompt':          {'label': 'Prompt', 'kind': 'text', 'multi': False, 'port': 'travail'},
    'negative_prompt': {'label': 'Prompt négatif', 'kind': 'text', 'multi': False, 'port': None},
    'work_file':       {'label': 'Fichier de travail', 'kind': 'file', 'multi': True, 'port': 'travail'},
    'work_image':      {'label': 'Image de travail', 'kind': 'file', 'accept': 'image', 'multi': True, 'port': 'travail'},
    'reference_image': {'label': 'Image de référence (style)', 'kind': 'file', 'accept': 'image', 'multi': False, 'port': 'reference'},
    'work_audio':      {'label': 'Audio de travail', 'kind': 'file', 'accept': 'audio', 'multi': True, 'port': 'travail'},
    'reference_file':  {'label': 'Fichier de référence', 'kind': 'file', 'multi': False, 'port': 'reference'},
    'reference_voice': {'label': 'Voix de référence', 'kind': 'file', 'accept': 'audio', 'multi': False, 'port': 'reference'},
    'url':             {'label': 'URL', 'kind': 'url', 'multi': False, 'port': 'travail'},
    'prompt_file':     {'label': 'Fichier de prompts (batch)', 'kind': 'file', 'multi': False, 'port': 'travail'},
}


# ── Schéma par app : domaines → modes ────────────────────────────────────────
# mode = {id, label, icon, realtime?, inputs:[input_type_id], settings:[setting_id]}
APP_MODES = {
    # ── IMAGER (app de référence — le plus de modes) ─────────────────────────
    'imager': {
        'domains': [
            # Modes ALIGNÉS sur l'existant Imager (JS currentMode : txt2img/img2img/style2img/file2img/
            # describe2img). NB : domaine image/vidéo aujourd'hui dérivé du MODÈLE choisi (à migrer en
            # onglet domaine). describe2img = mini-pipeline → candidat MÉTA-APP (Describer→Imager).
            {'id': 'image', 'label': 'Image', 'icon': 'fa-image', 'variant': 'primary', 'modes': [
                {'id': 'txt2img', 'label': 'Texte → Image', 'icon': 'fa-font',
                 'inputs': ['prompt', 'negative_prompt'],
                 'settings': ['model', 'seed', 'steps', 'guidance', 'resolution']},
                {'id': 'img2img', 'label': 'Édition (img2img)', 'icon': 'fa-wand-magic-sparkles',
                 'inputs': ['work_image', 'prompt'],
                 'settings': ['model', 'strength', 'seed', 'steps']},
                {'id': 'style2img', 'label': 'Transfert de style', 'icon': 'fa-palette',
                 'inputs': ['reference_image', 'prompt'],
                 'settings': ['model', 'style_weight', 'seed', 'steps']},
                {'id': 'file2img', 'label': 'Batch (fichier de prompts)', 'icon': 'fa-list',
                 'inputs': ['prompt_file'],
                 'settings': ['model', 'seed', 'steps', 'resolution']},
                {'id': 'describe2img', 'label': 'Décrire → Image', 'icon': 'fa-comment-dots',
                 'inputs': ['work_image'],
                 'settings': ['model', 'seed', 'steps'],
                 'pipeline_hint': 'Describer→Imager'},  # mini-pipeline → candidat MÉTA-APP
                # futur : {'id': 'to_3d', 'label': 'Image → 3D', 'inputs': ['work_image']}
            ]},
            # Ids ALIGNÉS sur l'existant (template + JS currentVideoMode : txt2vid/img2vid).
            {'id': 'video', 'label': 'Vidéo', 'icon': 'fa-film', 'variant': 'success', 'modes': [
                {'id': 'txt2vid', 'label': 'Texte → Vidéo', 'icon': 'fa-font',
                 'inputs': ['prompt'],
                 'settings': ['video_model', 'frames', 'fps', 'resolution']},
                {'id': 'img2vid', 'label': 'Image → Vidéo', 'icon': 'fa-image',
                 'inputs': ['work_image', 'prompt'],
                 'settings': ['video_model', 'frames', 'fps']},
            ]},
        ],
    },

    # ── SYNTHESIZER (mono-domaine audio ; prouve le mode TEMPS RÉEL) ──────────
    'synthesizer': {
        'domains': [
            {'id': 'audio', 'label': 'Audio', 'icon': 'fa-volume-high', 'modes': [
                {'id': 'normal', 'label': 'Synthèse', 'icon': 'fa-play',
                 'inputs': ['prompt', 'reference_voice'],
                 'settings': ['voice', 'language', 'speed']},
                {'id': 'realtime', 'label': 'Temps réel', 'icon': 'fa-bolt', 'realtime': True,
                 'inputs': ['prompt', 'reference_voice'],
                 'settings': ['voice', 'language', 'speed']},
            ]},
        ],
    },

    # ── TRANSCRIBER (mono-domaine ; le MODE temps réel = « Speak », normal = fichier) ──
    'transcriber': {
        'domains': [
            {'id': 'audio', 'label': 'Transcription', 'icon': 'fa-microphone-lines', 'variant': 'info', 'modes': [
                {'id': 'normal', 'label': 'Normal', 'icon': 'fa-file-audio',
                 'inputs': ['work_file'],
                 'settings': ['model', 'language', 'diarization', 'summary']},
                {'id': 'realtime', 'label': 'Temps réel', 'icon': 'fa-microphone', 'realtime': True,
                 'inputs': [],
                 'settings': ['language']},
            ]},
        ],
    },

    # ── ANONYMIZER (multi-domaine futur ; prouve le switch de MODE yolo/sam3) ──
    'anonymizer': {
        'domains': [
            {'id': 'image_video', 'label': 'Image / Vidéo', 'icon': 'fa-photo-film', 'modes': [
                # variant par mode (couleurs alignées sur l'UI existante : yolo=bleu, sam3=cyan).
                {'id': 'yolo', 'label': 'Détection (YOLO)', 'icon': 'fa-crosshairs', 'variant': 'primary',
                 'inputs': ['work_file'],
                 'settings': ['model', 'classes', 'blur_ratio', 'detection_threshold']},
                {'id': 'sam3', 'label': 'Prompt (SAM3)', 'icon': 'fa-wand-magic-sparkles', 'variant': 'info',
                 'inputs': ['work_file', 'prompt'],
                 'settings': ['blur_ratio']},
            ]},
            # futurs : {'id':'audio',…}, {'id':'document',…}
        ],
    },
}


# ── Accesseurs ───────────────────────────────────────────────────────────────
def get_app_modes(app: str) -> dict:
    """Schéma {domains:[…]} d'une app, ou {} si non déclaré."""
    return APP_MODES.get(app, {})


def get_domains(app: str) -> list:
    return get_app_modes(app).get('domains', [])


def has_domain_tabs(app: str) -> bool:
    """True si l'app a PLUSIEURS domaines (→ afficher des onglets). Sinon : modes directs."""
    return len(get_domains(app)) > 1


def get_domain(app: str, domain_id: str) -> dict:
    for d in get_domains(app):
        if d.get('id') == domain_id:
            return d
    return {}


def get_mode(app: str, domain_id: str, mode_id: str) -> dict:
    for m in get_domain(app, domain_id).get('modes', []):
        if m.get('id') == mode_id:
            return m
    return {}


def resolve_inputs(mode: dict) -> list:
    """Détaille les entrées d'un mode (avec leur définition de type INPUT_TYPES)."""
    out = []
    for key in mode.get('inputs', []):
        spec = INPUT_TYPES.get(key, {'label': key, 'kind': 'text'})
        out.append({'id': key, **spec})
    return out
