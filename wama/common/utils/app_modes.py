"""
Schéma déclaratif DOMAINES → MODES des apps — clé de voûte UX (voir MODES_QUEUE_UX.md).

3 axes distincts :
  1. DOMAINE → ONGLET, conditionnel (si >1 domaine). Scope la file.
  2. MODE (dans un domaine) → switch (yolo/sam3, normal/temps-réel).
  3. WORKFLOW (pipeline/standalone) → la MÉTA-APP (PAS modélisé ici).

═══ CE QU'EST UN DOMAINE, ET CE QU'IL N'EST PAS (clarifié le 2026-08-23) ═══════════════

**Un domaine est un WORKFLOW distinct, PAS un type de fichier d'entrée.** C'est la règle qui
manquait, et son absence avait produit deux erreurs de modélisation opposées :

  • le converter déclarait **5 domaines** (image/video/audio/document/archive) — soit ses 5
    natures d'entrée. Or il ne rend AUCUN onglet et ne doit pas en rendre : l'utilisateur y
    dépose n'importe quel fichier, le type est DÉTECTÉ et les réglages s'adaptent. Cinq onglets
    obligeraient l'utilisateur à classer son fichier lui-même — un travail que la machine fait
    mieux. Un seul domaine, `conversion`, qui `accepts` les cinq natures ;
  • le describer, à l'inverse, ne déclarait AUCUN domaine alors qu'il en a bien un (« décrire »),
    simplement mono. Résultat : rien à nommer, rien à porter au DOM.

Le critère qui tranche : **le domaine se justifie quand la surface de RÉGLAGES et le workflow
divergent**, pas quand la nature du fichier diverge. Décrire une image, un PDF ou un audio se
règle pareil (style, langue, longueur) → un domaine. Produire une image ou une vidéo n'a ni les
mêmes réglages ni le même moteur → deux domaines.

**Un domaine est TOUJOURS déclaré et NOMMÉ, même seul.** Jamais de `default` implicite : le jour
où une app en gagne un second, on se retrouverait avec `default` + `audio` + `document`, et le
nommage perdrait sa cohérence pour toujours. Une app mono-domaine nomme son workflow
(`conversion`, `description`, `lecture`) ; une app multi-domaines nomme l'axe qui les sépare —
le plus souvent les catégories média, jointes par `_` (`image_video`).

⚠ **`image_video` plutôt que `media` ou `visuel`** (arbitrage Fabien, 2026-08-23). `media`
englobe l'audio, donc désigner par lui le seul couple image+vidéo est faux ; `visuel` est tout
aussi faux (la 3D, les documents et le texte sont visuels). Les pistes sémiotiques (`iconique`,
`visuel_2d`) sont justes mais opaques dans du code. `image_video` gagne pour une raison
structurelle et non de goût : **il est composé des noms de la taxonomie elle-même**, donc le nom
EST la liste `accepts` — dérivable, vérifiable par un critère, et jamais à re-débattre.

═══ UN MODE EST UN SWITCH — donc `[]` quand il n'y a pas de variante ════════════════════

Un mode ne se déclare que si l'UTILISATEUR a un choix à faire. `wama-modes.js` l'applique déjà :
il ne rend le groupe de boutons que `if (modes.length > 1)`. Déclarer un mode unique n'affiche
donc rien — c'est de la taxonomie morte, et c'est ce qu'étaient `standalone` (avatarizer, résidu
de l'époque à deux modes TTS→audio→avatar / audio→avatar) et `convert` répété cinq fois.

⚠ **Ne PAS confondre mode d'UI et workflow de backend.** L'imager choisit txt2img / img2img /
style2img selon les entrées fournies et les réglages : c'est une décision de MOTEUR, prise sans
switch à l'écran. Un workflow backend n'a rien à faire ici.


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
    'reference_melody': {'label': 'Mélodie de référence', 'kind': 'file', 'accept': 'audio', 'multi': False, 'port': 'reference'},
    'url':             {'label': 'URL', 'kind': 'url', 'multi': False, 'port': 'travail'},
    'prompt_file':     {'label': 'Fichier de prompts (batch)', 'kind': 'file', 'multi': False, 'port': 'travail'},
}


# RÈGLE D'APPARIEMENT (INPUT_MODEL_MATCHING.md) : les slots de la card d'entrée d'une app =
# ses inputs déclarés ci-dessous (niveau APP : communs à tous les modèles, ex. prompt/prompt_file)
# ∪ l'union des `inputs_required/optional` de ses MODÈLES (capabilities catalogue, ex.
# reference_melody porté par musicgen-melody seul). La brique `wama-input-match.js` lie les deux :
# entrée fournie → modèles incompatibles DÉSACTIVÉS avec raison (jamais cachés) ; modèle choisi →
# slots attendus mis en évidence. Réversible par retrait de la chip.

# ── Schéma par app : domaines → modes ────────────────────────────────────────
# mode = {id, label, icon, realtime?, inputs:[input_type_id], settings:[setting_id]}
APP_MODES = {
    # ── IMAGER (app de référence — le plus de modes) ─────────────────────────
    # ── IMAGER — 2 domaines (Image, Vidéo), AUCUN mode ────────────────────────
    # Déclarait 5 modes `image` (txt2img/img2img/style2img/file2img/describe2img) et 2 `video`
    # (txt2vid/img2vid) — soit 7 switches. Ils ont RÉELLEMENT existé, puis ont été retirés au
    # profit d'UNE card d'entrée par domaine offrant toutes les entrées possibles, avec
    # appariement bidirectionnel entrée ⇄ modèle (WamaInputMatch). L'utilisateur n'a plus à
    # choisir un mode : le moteur le DÉRIVE de ce qu'on lui donne.
    #
    # La déclaration, elle, n'avait pas suivi — et le JS non plus : `driveRadios` visait
    # `#wamaImageModes`/`#imageModeRadios`, quatre ancres qui n'existent PLUS dans le DOM (elles
    # ne subsistaient que comme chaînes dans l'appel lui-même). Trois étages morts en silence :
    # déclaration → API → JS. Vérifié le 2026-08-23, pas déduit.
    #
    # ⚠ txt2img/img2vid restent des WORKFLOWS DE BACKEND, choisis d'après les entrées et les
    # réglages. Un workflow de backend n'est pas un mode d'UI : il n'a rien à faire ici.
    'imager': {
        'domains': [
            {'id': 'image', 'label': 'Image', 'icon': 'fa-image', 'variant': 'primary',
             # accepts = ce que le DOMAINE prend en ENTRÉE (le prompt est du `text`) ; son NOM
             # dit la SORTIE. Les deux domaines acceptent la même chose et diffèrent par ce
             # qu'ils produisent — la preuve qu'un domaine n'est pas une nature de fichier.
             'accepts': ('text', 'image'), 'modes': []},
            {'id': 'video', 'label': 'Vidéo', 'icon': 'fa-film', 'variant': 'success',
             'accepts': ('text', 'image'), 'modes': []},
        ],
    },

    # ── ENHANCER (MULTI-DOMAINE : image/vidéo + audio → 2 onglets domaine) ────
    # Deux sous-modèles (Enhancement image/vidéo, AudioEnhancement) unifiés sous les onglets WamaModes ;
    # l'onglet domaine scope la file + les réglages + la dropzone.
    'enhancer': {
        'domains': [
            {'id': 'image_video', 'label': 'Image / Vidéo', 'icon': 'fa-photo-film',
             'variant': 'primary', 'accepts': ('image', 'video'), 'modes': [
                {'id': 'enhance', 'label': 'Amélioration', 'icon': 'fa-wand-magic-sparkles',
                 'inputs': ['work_file'],
                 'settings': ['ai_model', 'upscale_factor', 'denoise', 'blend_factor', 'tile_size',
                              'output_format', 'output_quality']},
            ]},
            {'id': 'audio', 'label': 'Audio', 'icon': 'fa-volume-high', 'variant': 'success',
             'accepts': ('audio',), 'modes': [
                {'id': 'enhance_audio', 'label': 'Débruitage / Restauration', 'icon': 'fa-wave-square',
                 'inputs': ['work_audio'],
                 'settings': ['engine', 'mode', 'denoising_strength', 'quality']},
            ]},
        ],
    },

    # ── SYNTHESIZER (mono-domaine audio ; prouve le mode TEMPS RÉEL) ──────────
    'synthesizer': {
        'domains': [
            {'id': 'audio', 'label': 'Audio', 'icon': 'fa-volume-high',
             'accepts': ('text',), 'modes': [
                {'id': 'normal', 'label': 'Synthèse', 'icon': 'fa-play',
                 'inputs': ['prompt', 'reference_voice'],
                 'settings': ['voice', 'language', 'speed']},
                {'id': 'realtime', 'label': 'Temps réel', 'icon': 'fa-bolt', 'realtime': True,
                 'inputs': ['prompt', 'reference_voice'],
                 'settings': ['voice', 'language', 'speed']},
            ]},
        ],
    },

    # ── AVATARIZER (mono-domaine, mono-mode → AUCUN onglet/switch rendu ; décision route F2 :
    # rapide/qualité = simple paramètre (quality_mode/use_enhancer), PAS un mode. L'entrée vaut
    # surtout pour les PORTS : seul cas double-entrée du catalogue, image + audio requis.) ──
    'avatarizer': {
        'domains': [
            # `modes: []` — le mode `standalone` était un RÉSIDU de l'époque à deux modes
            # (TTS→audio→avatar / audio→avatar) ; le TTS relève du synthesizer depuis 2026-07-15.
            # Un mode unique ne rendait aucun switch : sa purge ne change pas un pixel.
            {'id': 'avatar', 'label': 'Avatar parlant', 'icon': 'fa-user-astronaut',
             'accepts': ('image', 'audio'), 'modes': []},
        ],
    },

    # ── TRANSCRIBER (mono-domaine ; le MODE temps réel = « Speak », normal = fichier) ──
    'transcriber': {
        'domains': [
            {'id': 'audio', 'label': 'Transcription', 'icon': 'fa-microphone-lines', 'variant': 'info',
             # la VIDÉO est acceptée : elle est une source audio ici. C'est bien la preuve qu'un
             # domaine n'est pas une nature de fichier — son nom dit le workflow, `accepts` dit
             # ce qu'on peut y déposer.
             'accepts': ('audio', 'video'), 'modes': [
                {'id': 'normal', 'label': 'Normal', 'icon': 'fa-file-audio',
                 'inputs': ['work_file'],
                 'settings': ['model', 'language', 'diarization', 'summary']},
                {'id': 'realtime', 'label': 'Temps réel', 'icon': 'fa-microphone', 'realtime': True,
                 'inputs': [],
                 'settings': ['language']},
            ]},
        ],
    },

    # ── CONVERTER (multi-domaine par NATURE, mono-mode « convertir » ; aucun modèle IA —
    # les settings par domaine = les show_if réels de params.py) ──────────────────────
    # ── CONVERTER — UN domaine, cinq natures acceptées ────────────────────────
    # Déclarait 5 domaines = ses 5 natures d'entrée, et n'a JAMAIS rendu d'onglet (aucun
    # WamaModes dans son gabarit — mesuré 2026-08-23). La déclaration décrivait donc une UI qui
    # n'existait pas, et qu'on ne veut pas : l'utilisateur dépose n'importe quel fichier, le type
    # est détecté, les réglages s'adaptent (`show_if` par media_type dans params.py). Les cinq
    # natures deviennent `accepts` — la donnée est conservée, sa NATURE est corrigée.
    'converter': {
        'domains': [
            {'id': 'conversion', 'label': 'Conversion', 'icon': 'fa-right-left', 'variant': 'info',
             'accepts': ('image', 'video', 'audio', 'document', 'archive'), 'modes': []},
        ],
    },

    # ── ANONYMIZER (multi-domaine futur ; prouve le switch de MODE yolo/sam3) ──
    'anonymizer': {
        'domains': [
            {'id': 'image_video', 'label': 'Image / Vidéo', 'icon': 'fa-photo-film',
             'accepts': ('image', 'video'), 'modes': [
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

    # ── ABSENCES DÉCLARÉES (≠ non traité) — même pattern que PROMPT_TARGETS['synthesizer']=[].
    # Un MODE n'existe que si le COMPORTEMENT diverge (entrées/réglages différents — doctrine
    # common/README §Modes) ; déclarer un mode unique factice serait de la taxonomie. Si le
    # comportement diverge un jour, remplir `domains` ici — l'UI (onglets/switch) se génère.
    # composer : prompt-primaire, un seul geste « composer » (cf. composer/index.html:31 — la
    #   mélodie Melody est un SLOT optionnel, pas un mode).
    'composer': {'domains': [
        {'id': 'composition', 'label': 'Composition', 'icon': 'fa-music',
         'accepts': ('text',), 'modes': []},
    ]},
    # reader : un seul geste « lire » ; backend/mode/langue sont des PARAMS, pas des modes.
    'reader': {'domains': [
        {'id': 'lecture', 'label': 'Lecture', 'icon': 'fa-file-lines',
         'accepts': ('document', 'image'), 'modes': []},
    ]},
    # describer : mêmes réglages pour image et vidéo (aucune divergence par nature — le
    #   groupement de file par nature est de l'ORGANISATION, pas un mode).
    'describer': {'domains': [
        {'id': 'description', 'label': 'Description', 'icon': 'fa-comment-dots',
         'accepts': ('image', 'video', 'audio', 'document'), 'modes': []},
    ]},
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
