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

═══ LES ENTRÉES SE DÉCLARENT AUSSI SANS SWITCH — `inputs` au niveau DOMAINE (2026-08-30) ═════

`inputs[]` ne se déclarait que sur un MODE, or 6 apps sur 10 ont `modes: []` (à raison — un mode
n'existe que si le comportement diverge). Leurs slots de card d'entrée n'étaient donc déclarables
NULLE PART : le typage par slot vivait en littéraux dans 2 gabarits sur 10 (`reference_accept` de
composer et imager), le générateur n'émettait qu'un slot unique, et la déclaration PLATE
(`input_extensions`) tranchait les slots de référence en sens inverse selon l'app (l'avatarizer
inclut son image, le composer excluait sa mélodie — d'où un « Envoyer vers… » qui ne proposera
jamais le composer pour un audio). Règle : **un domaine SANS switch porte ses `inputs`
lui-même ; un domaine À switch les laisse à ses modes** (c'est précisément ce que le switch fait
varier). `studio_node_ports` lit LES DEUX niveaux — les ports `reference` du studio, la facette
`ports` du manifeste, l'intake (`capabilities_for_path`) et l'appariement entrée⇄modèle en
dérivent sans une ligne par consommateur. Détail : `WAMA_APP_GENERATION_ROUTE.md` §S2bis.6 (b).

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
             'accepts': ('prompt', 'image'),
             # Slots MESURÉS sur la card réelle (index.html:133) : prompt primaire, image de
             # référence (`reference_accept='image/*'`), fichier de prompts batch (.txt/.csv).
             'inputs': ['prompt', 'reference_image', 'prompt_file'], 'modes': []},
            {'id': 'video', 'label': 'Vidéo', 'icon': 'fa-film', 'variant': 'success',
             'accepts': ('prompt', 'image'),
             # Card vidéo (index.html:175) : prompt + image de DÉPART (i2v) — pas de batch file.
             'inputs': ['prompt', 'reference_image'], 'modes': []},
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
            # `route_prefix` — le SEUL cas du dépôt où un domaine a ses PROPRES routes
            # (`audio_batch_delete`, `audio_delete`… face à `batch_delete`, `delete`). Il est
            # DÉCLARÉ et non déduit de l'ordre des domaines : une règle « le premier n'a pas de
            # préfixe » se casserait au premier réordonnancement, et rien ne l'aurait signalé.
            # Absent = pas de préfixe, ce qui est le cas de tous les autres domaines.
            {'id': 'audio', 'label': 'Audio', 'icon': 'fa-volume-high', 'variant': 'success',
             'accepts': ('audio',), 'route_prefix': 'audio', 'modes': [
                {'id': 'enhance_audio', 'label': 'Débruitage / Restauration', 'icon': 'fa-wave-square',
                 'inputs': ['work_audio'],
                 'settings': ['engine', 'mode', 'denoising_strength', 'quality']},
            ]},
        ],
    },

    # ── SYNTHESIZER (mono-domaine audio) ──────────────────────────────────────
    # ⚠ Le mode `realtime` est PARTI le 2026-08-30 (tranché Fabien, 2ᵉ confirmation — la 1ʳᵉ
    # était le 2026-07-25, MODES_QUEUE_UX §5) : « pas de mode temps réel, mais une modalité
    # dans la card d'entrée gérée via la PREVIEW ». Les deux modes déclarés ici étaient
    # IDENTIQUES (mêmes inputs, mêmes settings — la définition même de ce qui n'est pas un
    # mode) et AUCUNE UI ne les consommait (0 WamaModes dans l'app, mesuré). La tension
    # MODES_QUEUE_UX §5bis est close ; l'aperçu SSE de la card reste l'affordance temps réel.
    'synthesizer': {
        'domains': [
            {'id': 'audio', 'label': 'Audio', 'icon': 'fa-volume-high',
             'accepts': ('prompt',), 'inputs': ['prompt', 'reference_voice'], 'modes': []},
        ],
    },

    # ── AVATARIZER (mono-domaine, mono-mode → AUCUN onglet/switch rendu ; décision route F2 :
    # rapide/qualité = simple paramètre (quality_mode/use_enhancer), PAS un mode. L'entrée vaut
    # surtout pour les PORTS : cas double-entrée du catalogue, image + (audio OU texte).) ──
    'avatarizer': {
        'domains': [
            # `modes: []` TOUJOURS — le pipeline texte→TTS→avatar est REVENU le 2026-08-28,
            # mais comme WORKFLOW DE BACKEND dérivé des entrées (audio/URL → animation seule,
            # texte → TTS puis animation), pas comme switch : précédent imager txt2img/img2vid,
            # §2bis. `text` dans accepts = le prompt est une entrée de plein droit.
            {'id': 'avatar', 'label': 'Avatar parlant', 'icon': 'fa-user-astronaut',
             'accepts': ('image', 'audio', 'prompt'),
             # Card réelle (index.html:140) : prompt (texte à dire) + voix (input fichier,
             # politique VOICE_SAMPLE_EXTENSIONS). ⚠ `work_audio`, PAS `reference_voice` :
             # l'audio EST l'entrée de travail (il pilote l'animation), déjà porté par le port
             # TRAVAIL via input_types — un slot `reference` créerait un port audio EN DOUBLE.
             # L'AVATAR (image) passe par la galerie (`extra_zone_template`), pas par un input
             # fichier — l'image reste au port travail, la galerie est la modalité d'app.
             'inputs': ['prompt', 'work_audio'], 'modes': []},
        ],
    },

    # ── TRANSCRIBER (mono-domaine ; Speak = MODALITÉ de la card, pas un mode) ──
    # ⚠ Le mode `realtime` est PARTI le 2026-08-30 (même décision que le synthesizer
    # ci-dessus) : Speak est une AFFORDANCE de la card d'entrée (`show_live`), la session
    # live s'affiche via la preview « during » de la card créée — cf. CARD_DESIGN §11.8
    # exigence 6. Aucune UI ne consommait ces modes (0 WamaModes dans l'app, mesuré).
    'transcriber': {
        'domains': [
            {'id': 'audio', 'label': 'Transcription', 'icon': 'fa-microphone-lines', 'variant': 'info',
             # la VIDÉO est acceptée : elle est une source audio ici. C'est bien la preuve qu'un
             # domaine n'est pas une nature de fichier — son nom dit le workflow, `accepts` dit
             # ce qu'on peut y déposer.
             'accepts': ('audio', 'video'), 'inputs': ['work_file'], 'modes': []},
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
             'accepts': ('image', 'video', 'audio', 'document', 'archive'),
             'inputs': ['work_file'], 'modes': []},
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
         'accepts': ('prompt',),
         # Card réelle (index.html:78) : prompt primaire, mélodie de référence (le littéral
         # `reference_accept='audio/*'` a enfin sa déclaration — c'est ELLE qui donne au
         # composer son port audio, absent d'input_extensions), fichier de prompts batch.
         'inputs': ['prompt', 'reference_melody', 'prompt_file'], 'modes': []},
    ]},
    # reader : un seul geste « lire » ; backend/mode/langue sont des PARAMS, pas des modes.
    'reader': {'domains': [
        {'id': 'lecture', 'label': 'Lecture', 'icon': 'fa-file-lines',
         'accepts': ('document', 'image'), 'inputs': ['work_file'], 'modes': []},
    ]},
    # describer : mêmes réglages pour image et vidéo (aucune divergence par nature — le
    #   groupement de file par nature est de l'ORGANISATION, pas un mode).
    'describer': {'domains': [
        {'id': 'description', 'label': 'Description', 'icon': 'fa-comment-dots',
         'accepts': ('image', 'video', 'audio', 'document'), 'inputs': ['work_file'], 'modes': []},
    ]},
}


# ── Accesseurs ───────────────────────────────────────────────────────────────
def get_app_modes(app: str) -> dict:
    """Schéma {domains:[…]} d'une app, ou {} si non déclaré.

    ⚠ Repli JUMELLE (2026-09-04) — `APP_MODES` est indexé par NOM D'APP, donc une jumelle
    `<app>_NN` n'y figure jamais et perdait SILENCIEUSEMENT les `inputs[]` de sa source.
    Mesuré à la création de `composer_01` : 1 port rendu au lieu de 2, le port
    `reference_melody` évaporé — donc une jumelle incapable de tester ce que sa source
    déclare. `inject_sandbox_catalog` clone déjà `APP_CATALOG` pour exactement cette
    raison ; ce repli est son équivalent ici (cf. `sandbox.twin_source`).

    ⚠ Le silence était le vrai défaut : rien ne distinguait « cette app n'a pas de domaine »
    (converter, legitimement) de « cette jumelle a perdu les siens ».
    """
    if app in APP_MODES:
        return APP_MODES[app]
    from wama.common.sandbox import twin_source   # module PUR (json/pathlib) — aucun cycle
    src = twin_source(app)
    return APP_MODES.get(src, {}) if src else {}


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


def route_prefix(app: str, domain_id: str) -> str:
    """Préfixe des routes de ce domaine (`audio` → `audio_batch_delete`), '' par défaut.

    DÉCLARÉ, jamais déduit de la position : c'est ce qui permet à une app d'avoir plusieurs
    familles de routes sans qu'aucune brique n'ait à connaître son nom.
    """
    return get_domain(app, domain_id).get('route_prefix') or ''


def accepts(app: str, domain_id: str) -> tuple:
    """Catégories média (MEDIA_CATEGORIES) que ce domaine prend en ENTRÉE."""
    return tuple(get_domain(app, domain_id).get('accepts') or ())


def domain_for_category(app: str, categorie: str) -> str | None:
    """Domaine d'une app capable d'accueillir cette catégorie média — base du ROUTAGE d'un
    fichier déposé vers le bon onglet. Le PREMIER qui accepte gagne : une app qui voudrait
    trancher autrement doit ordonner ses domaines, ce qui se lit dans la déclaration."""
    for d in get_domains(app):
        if categorie in (d.get('accepts') or ()):
            return d.get('id')
    return None


def resolve_inputs(porteur: dict) -> list:
    """Détaille les entrées d'un MODE ou d'un DOMAINE (définitions `INPUT_TYPES`).

    Le porteur est quiconque déclare `inputs[]` : un mode (apps à switch) ou, depuis le
    2026-08-30, un domaine sans switch (cf. l'encadré du module).
    """
    out = []
    for key in porteur.get('inputs', []):
        spec = INPUT_TYPES.get(key, {'label': key, 'kind': 'text'})
        out.append({'id': key, **spec})
    return out
