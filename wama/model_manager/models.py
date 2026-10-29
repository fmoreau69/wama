"""
WAMA Model Manager - Database Models

PostgreSQL-backed catalog for all AI models.
Provides instant loading instead of dynamic filesystem scanning.
"""

from django.db import models
from django.contrib.auth import get_user_model

from wama.common.models import ScopedManager, ScopedVisibility

User = get_user_model()


class ModelType(models.TextChoices):
    """Types of AI models."""
    VISION = 'vision', 'Vision'
    DIFFUSION = 'diffusion', 'Diffusion'
    SPEECH = 'speech', 'Speech'
    VLM = 'vlm', 'Vision-Language'
    LLM = 'llm', 'Large Language Model'
    EMBEDDING = 'embedding', 'Embedding'
    UPSCALING = 'upscaling', 'Upscaling'
    LIPSYNC = 'lipsync', 'Lip Sync'
    MUSIC = 'music', 'Music / Audio'
    OCR = 'ocr', 'OCR / Document'
    # Traitement du LANGAGE NATUREL hors génération et vectorisation (2026-10-28, décision de
    # Fabien) : les encodeurs qui ANALYSENT un texte — reconnaissance d'entités, données
    # personnelles. Le nom est la catégorie « Natural Language Processing » de HuggingFace, qui
    # range `token-classification` ; aucun type existant ne convenait : `embedding` aurait fait
    # entrer ces détecteurs dans le relevé des vectoriseurs (`benchmark_sync._mteb_markers`),
    # `llm` produit du texte, ces modèles n'en produisent pas.
    NLP = 'nlp', 'Langage naturel (NLP)'

    # `summarization` RETIRE le 2026-08-05 : zero modele l'a jamais porte, et resumer est un
    # USAGE d'un LLM, pas un type de modele. `embedding` ajoute : 5 modeles le portaient en base
    # sans qu'il soit declare nulle part.
    #
    # ⚠ Cet enum melange encore trois axes — famille (vision/diffusion/llm/vlm/embedding),
    # modalite (speech/music) et tache (upscaling/lipsync/ocr). C'est pourquoi il derive : une
    # tache n'a pas sa place ici, elle se declare dans `capabilities['task']` (cf. ModelTask).
    # Retirer upscaling/lipsync/ocr demande de re-typer 12 modeles — a faire, pas encore fait.


class ModelTask(models.TextChoices):
    """
    Ce qu'un modele SAIT FAIRE, par opposition a ce qu'il EST (`ModelType`).

    Vocabulaire jusqu'ici implicite : la decouverte ecrivait librement `capabilities['task']`,
    donc personne ne pouvait dire quelles valeurs existaient. Releve le 2026-08-05 sur les 129
    modeles du catalogue, puis normalise en kebab-case.

    C'est l'axe qui compte pour EVALUER un modele : on ne mesure pas un detecteur et un
    classifieur de la meme facon, alors que les deux sont `ModelType.VISION`.
    """
    # vision
    DETECT = 'detect', 'Détection'
    # Deux détections que `detect` confondait avec celle des OBJETS d'une scène (2026-10-07,
    # route F4b ⑤, décision de Fabien) : un select par TÂCHE proposait des détecteurs de PAGES
    # pour flouter des visages. Termes STANDARD, jamais inventés :
    #   • `layout-detection` — le tag que l'éditeur pose lui-même (`layout_detection`, PaddleX /
    #     PP-DocLayout) : l'analyse de mise en page d'un document, tableaux compris ;
    #   • `zero-shot-object-detection` — le tag HuggingFace de la détection en VOCABULAIRE OUVERT
    #     (LocateAnything) ; il était listé « non porté » (`PLATFORM_TASKS_NOT_CARRIED`) faute de
    #     décision, consignée ouverte dans PROSPECTION_PIPELINE.md.
    LAYOUT_DETECTION = 'layout-detection', 'Analyse de mise en page'
    ZERO_SHOT_OBJECT_DETECTION = 'zero-shot-object-detection', 'Détection en vocabulaire ouvert'
    SEGMENT = 'segment', 'Segmentation'
    CLASSIFY = 'classify', 'Classification'
    OBB = 'obb', 'Boîtes orientées'
    POSE = 'pose', 'Pose'
    OCR = 'ocr', 'OCR'
    # Declaree en amont du besoin (2026-08-05) : le chantier cam_analyzer/profondeur va faire
    # entrer un modele de ce type au catalogue, et `check_model_taxonomy` refuserait a juste
    # titre une valeur non declaree. Mieux vaut la declarer que voir le garde-fou contourne.
    DEPTH_ESTIMATION = 'depth-estimation', 'Estimation de profondeur'
    # Quatre taches ECRITES par la decouverte depuis des semaines sans etre declarees (mesure
    # 2026-09-17 par `check_model_taxonomy` : diarization 1, face-analysis 3, face-restoration 1,
    # image-to-3d 1). Hors vocabulaire, un modele n'a ni categorie derivable ni entrees par
    # defaut ; on declare ce que le registre fait deja plutot que de le laisser passer.
    FACE_ANALYSIS = 'face-analysis', 'Analyse de visage'
    FACE_RESTORATION = 'face-restoration', 'Restauration de visage'
    IMAGE_TO_3D = 'image-to-3d', 'Image → 3D'
    # audio / parole
    TRANSCRIPTION = 'transcription', 'Transcription'
    DIARIZATION = 'diarization', 'Diarisation'
    # Alignement forcé (2026-09-24) : date les mots d'un texte DÉJÀ écrit sur son audio. Ni une
    # transcription (il ne produit aucun texte) ni une diarisation (il ne dit pas qui parle).
    ALIGNMENT = 'alignment', 'Alignement forcé'
    TEXT_TO_SPEECH = 'text-to-speech', 'Synthèse vocale'
    # Fin de TOUR de parole (2026-10-28) : la personne a-t-elle fini sa phrase ? (Smart Turn,
    # conversation vocale de l'assistant). Ni une transcription (aucun texte), ni un filtre de
    # parole (il ne dit pas OÙ l'on parle, mais si l'on a FINI).
    END_OF_TURN = 'end-of-turn', 'Fin de tour de parole'
    AUDIO_ENHANCE = 'audio-enhance', 'Débruitage audio'
    DENOISE = 'denoise', 'Débruitage'
    # texte / multimodal
    TEXT_GENERATION = 'text-generation', 'Génération de texte'
    FEATURE_EXTRACTION = 'feature-extraction', 'Extraction de traits'
    # Les DONNÉES PERSONNELLES d'un texte (2026-10-28, ROADMAP §16.4bis) : noms, adresses,
    # identifiants… repérés par passage (début, fin, type) pour être occultés. Plus fin que le
    # `token-classification` de HuggingFace, qui couvre aussi la NER générale et l'étiquetage.
    PII_DETECTION = 'pii-detection', 'Détection de données personnelles'
    CAPTIONING = 'captioning', 'Légendage'
    # generation visuelle
    TEXT_TO_IMAGE = 'text-to-image', 'Texte → image'
    IMAGE_TO_IMAGE = 'image-to-image', 'Image → image'
    TEXT_TO_VIDEO = 'text-to-video', 'Texte → vidéo'
    IMAGE_TO_VIDEO = 'image-to-video', 'Image → vidéo'
    UPSCALE = 'upscale', 'Agrandissement'
    # audio genere — MUSIQUE et AMBIANCE/BRUITAGE sont deux metiers, pas deux mots pour un.
    # Le composer s'en sert deja pour separer composition musicale et ambiance/FX, et un
    # generateur de films scenarises devra distinguer la musique d'accompagnement des bruitages.
    # Les modeles portent eux-memes la distinction : MusicGen compose, AudioGen fait du son
    # d'ambiance. HuggingFace ne la fait PAS (un seul tag grossier) — raison de plus pour
    # l'ecrire ici plutot que de s'aligner et de la perdre. (Fabien, 2026-08-05.)
    TEXT_TO_MUSIC = 'text-to-music', 'Texte → musique'
    TEXT_TO_AUDIO = 'text-to-audio', 'Texte → ambiance / bruitage'
    # Extraction de PARTITION (2026-10-03) : un audio → sa partition (mélodie, accords, structure).
    # Ni une transcription de parole (`transcription` rend du texte), ni une extraction de traits
    # (étiquette HuggingFace de SheetSage2, qui ne dit pas ce qu'il PRODUIT). La cible `score` est
    # la nature des partitions (`app_registry.MEDIA_CATEGORIES`) : le domaine de sortie se dérive
    # du nom (`<source>-to-<cible>`). 1er modèle : SheetSage2, le maillon audio → partition du cover.
    AUDIO_TO_SCORE = 'audio-to-score', 'Audio → partition'
    # Transcription MULTI-INSTRUMENT (2026-10-16, décision de Fabien : la « Partition complète » du
    # composer) : un audio → un MIDI à une piste PAR INSTRUMENT, voix et batterie comprises. Pas
    # `audio-to-score` : celui-ci rend la grille mélodie + accords qu'un cover suit (SheetSage2) ;
    # les confondre ferait tirer un MIDI à N parties pour le rendu. 1er modèle : MuScriptor, dont la
    # carte se déclare elle-même `audio-to-midi`.
    AUDIO_TO_MIDI = 'audio-to-midi', 'Audio → MIDI multi-instrument'
    # Segmentation de la ROUTE (2026-10-16) : zone roulable et lignes de voie d'une caméra embarquée
    # (YOLOPv2, cam_analyzer). Sortie de `segment` pour la raison de `layout-detection` : le select
    # de l'anonymizer se tire par `detect,segment`, et y proposait YOLOPv2 — qui ne sait pas
    # anonymiser et que son moteur YOLO ne charge même pas (le banc l'avait relevé).
    ROAD_SEGMENTATION = 'road-segmentation', 'Segmentation de la route (zone roulable, voies)'
    # Métrique de QUALITÉ (2026-10-16) : un réseau qui MESURE, ne produit rien — LPIPS (distance
    # perceptuelle) du banc d'agrandissement (`WAMA_QUALITE §4`, mesure interne). Une tâche à part
    # pour qu'aucune sélection d'app ne le tire, et qu'il s'installe comme tout modèle.
    QUALITY_METRIC = 'quality-metric', 'Métrique de qualité (mesure)'
    # Gestes de la MAIN (2026-10-22) : la webcam pilote les scènes 3D (MediaPipe Gesture
    # Recognizer, exécuté dans le navigateur). Ni `pose` (le corps entier, sans les doigts), ni une
    # détection : il rend des repères de main ET un geste nommé (poing fermé, main ouverte…).
    HAND_GESTURE = 'hand-gesture', 'Gestes de la main'
    # video
    LIP_SYNC = 'lip-sync', 'Synchronisation labiale'


# Projection de NOTRE vocabulaire vers celui des plateformes : a SENS UNIQUE, PLUSIEURS-VERS-UN.
#
# On recoupe PLUSIEURS referentiels au lieu de s'aligner sur un seul — aucun ne couvre le champ,
# et chacun decrit une chose differente (releve le 2026-08-05) :
#
#   HuggingFace  UNE tache par modele, « ce a quoi il sert »  (47 tags, /api/tasks)
#   Ultralytics  UNE tache par fichier de poids               (detect/segment/classify/pose/obb)
#   Ollama       UN ENSEMBLE de capacites, « ce qu'il sait faire » (/api/show -> capabilities)
#
# La difference Ollama n'est pas cosmetique : `qwen3.6:35b` rend
# ['completion','vision','tools','thinking']. `tools` et `thinking` n'ont AUCUN equivalent chez
# HF, et ce sont justement les capacites qui decident si un modele peut servir l'assistant. Un
# champ `task` singulier les perd — c'est pourquoi 16 LLM du catalogue n'ont aucune tache : la
# question « quelle est SA tache » n'a pas de reponse pour eux.
#
# Consequence assumee : `task` reste le bon axe pour vision/diffusion/audio (un modele = un
# metier), et les LLM doivent porter en plus un ENSEMBLE de capacites. Les deux cohabitent dans
# `capabilities` ; ce n'est pas une incoherence, c'est que les objets different.
#
# Converger, donc, mais en PROJETANT : plusieurs de nos taches sont deliberement plus fines que
# le tag officiel, chaque fois pour une raison de metier. `denoise` et `upscale` retombent tous
# deux sur `image-to-image` chez HF ; `text-to-music` et `text-to-audio` sur rien du tout alors
# que le composer s'en sert pour separer composition et ambiance. S'aligner effacerait la
# distinction qui sert a CHOISIR un modele.
#
# None = aucun equivalent sur cette plateforme. Ce n'est pas un trou a combler.
# ⚠ Ici c'est NOUS qui sommes trop grossiers : Roboflow separe `Instance Segmentation` (un masque
# par objet) de `Semantic Segmentation` (un masque par classe), quand `segment` melange les deux.
# Pour anonymiser c'est l'INSTANCE qui compte — un masque par visage, pas un masque << visage >>.
# Distinction a introduire le jour ou un modele semantique entrera au catalogue ; aucun aujourd'hui,
# donc on ne scinde pas a vide (releve le 2026-08-05, docs.roboflow.com/models/supported-models).
TASK_TO_PLATFORM_TAGS = {
    #                              huggingface                     ultralytics  ollama        roboflow
    ModelTask.DETECT:             ('object-detection',             'detect',    None,        'Object Detection'),
    # HF range la mise en page sous `object-detection` (pas de tag de pipeline à elle) : c'est le
    # tag de CARTE `layout_detection` qui départage (`prospector.hf_task_to_wama`), comme
    # `super-resolution` départage `image-to-image`. Le tag principal reste celui de DETECT.
    ModelTask.LAYOUT_DETECTION:   (None,                           None,        None,        None),
    ModelTask.ZERO_SHOT_OBJECT_DETECTION: ('zero-shot-object-detection', None, None,         None),
    ModelTask.SEGMENT:            ('image-segmentation',           'segment',   None,        'Instance Segmentation'),
    ModelTask.CLASSIFY:           ('image-classification',         'classify',  None,        'Classification'),
    ModelTask.POSE:               ('keypoint-detection',           'pose',      None,        'Keypoint Detection'),
    ModelTask.OBB:                (None,                           'obb',       None,        None),
    ModelTask.OCR:                ('image-to-text',                None,        None,        'OCR'),
    ModelTask.DEPTH_ESTIMATION:   ('depth-estimation',             None,        None,        'Depth Estimation'),
    # `image-to-3d` est un tag HF (TripoSR le porte) ; la restauration de visage se range avec
    # les autres image→image ; l'analyse de visage et la diarisation n'ont d'equivalent nulle part.
    ModelTask.FACE_ANALYSIS:      (None,                           None,        None,        None),
    ModelTask.FACE_RESTORATION:   ('image-to-image',               None,        None,        None),
    ModelTask.IMAGE_TO_3D:        ('image-to-3d',                  None,        None,        None),
    ModelTask.TRANSCRIPTION:      ('automatic-speech-recognition', None,        None,        None),
    ModelTask.DIARIZATION:        (None,                           None,        None,        None),
    # HuggingFace range les aligneurs CTC sous l'ASR (c'est leur entraînement, pas leur usage ici).
    ModelTask.ALIGNMENT:          (None,                           None,        None,        None),
    ModelTask.TEXT_TO_SPEECH:     ('text-to-speech',               None,        None,        None),
    ModelTask.AUDIO_ENHANCE:      ('audio-to-audio',               None,        None,        None),
    ModelTask.DENOISE:            ('image-to-image',               None,        None,        None),
    ModelTask.TEXT_GENERATION:    ('text-generation',              None,        'completion', None),
    ModelTask.FEATURE_EXTRACTION: ('feature-extraction',           None,        'embedding',  None),
    ModelTask.PII_DETECTION:      ('token-classification',         None,        None,        None),
    ModelTask.CAPTIONING:         ('image-to-text',                None,        'vision',    'Multimodal'),
    ModelTask.TEXT_TO_IMAGE:      ('text-to-image',                None,        None,        None),
    ModelTask.IMAGE_TO_IMAGE:     ('image-to-image',               None,        None,        None),
    ModelTask.TEXT_TO_VIDEO:      ('text-to-video',                None,        None,        None),
    ModelTask.IMAGE_TO_VIDEO:     ('image-to-video',               None,        None,        None),
    ModelTask.UPSCALE:            ('image-to-image',               None,        None,        None),
    ModelTask.TEXT_TO_MUSIC:      (None,                           None,        None,        None),
    ModelTask.TEXT_TO_AUDIO:      (None,                           None,        None,        None),
    # HuggingFace n'a pas de tâche officielle « transcription musicale » (SheetSage2 se range en
    # `feature-extraction`, ce qu'il n'est pas pour nous).
    ModelTask.AUDIO_TO_SCORE:     (None,                           None,        None,        None),
    # Pas de tâche de PIPELINE chez HuggingFace non plus ; la carte porte le tag `audio-to-midi`
    # (lu par `prospector.hf_task_to_wama`, comme `layout_detection`).
    ModelTask.AUDIO_TO_MIDI:      (None,                           None,        None,        None),
    # Ni l'une ni l'autre n'a d'équivalent sur les plateformes (propres à WAMA).
    ModelTask.ROAD_SEGMENTATION:  (None,                           None,        None,        None),
    ModelTask.QUALITY_METRIC:     (None,                           None,        None,        None),
    # Repères de main + geste nommé : aucune tâche de pipeline ne le dit (`keypoint-detection` de HF
    # ne nomme pas le geste, `pose` d'Ultralytics est le corps entier).
    ModelTask.HAND_GESTURE:       (None,                           None,        None,        None),
    # HuggingFace range Smart Turn sous `voice-activity-detection`, qui nomme aussi les filtres de
    # parole ordinaires (Silero) : projeter ce tag sur la fin de tour ferait de tout VAD un juge
    # de fin de phrase.
    ModelTask.END_OF_TURN:        (None,                           None,        None,        None),
    ModelTask.LIP_SYNC:           (None,                           None,        None,        None),
}
REFERENCE_PLATFORMS = ('huggingface', 'ultralytics', 'ollama', 'roboflow')


# NOTRE tâche → NOTRE catégorie. Table DIRECTE, et c'est le point : la dérivation passait
# jusqu'ici par le tag HuggingFace (`platform_tag` puis la table de la prospection), ce qui
# marchait tant que la tâche AVAIT un équivalent. Or `lip-sync`, `text-to-music`,
# `text-to-audio` et `obb` n'en ont AUCUN (colonne huggingface à None, par décision) : pour
# eux l'ancrage par catégorie ne s'activait pas, et il ne restait que le filtre par tâche —
# avec sa permissivité (un modèle sans capacités déclarées passe). C'est par là que
# `LocateAnything` avait fui dans une requête TTS. Relevé le 2026-09-01 en répondant à la
# question de Fabien sur l'avatarizer : `lip-sync` est exactement dans ce cas.
#
# Un aller-retour par une taxonomie ÉTRANGÈRE ne peut pas répondre pour ce qu'elle ne nomme
# pas. On déclare donc le lien chez nous, et `check_model_taxonomy` vérifie qu'AUCUNE tâche
# n'en manque — sans quoi une tâche ajoutée demain retomberait dans le même trou en silence.
TASK_TO_MODEL_TYPE = {
    ModelTask.DETECT:             ModelType.VISION,
    ModelTask.LAYOUT_DETECTION:   ModelType.VISION,
    ModelTask.ZERO_SHOT_OBJECT_DETECTION: ModelType.VISION,
    ModelTask.SEGMENT:            ModelType.VISION,
    ModelTask.CLASSIFY:           ModelType.VISION,
    ModelTask.OBB:                ModelType.VISION,
    ModelTask.POSE:               ModelType.VISION,
    ModelTask.DEPTH_ESTIMATION:   ModelType.VISION,
    ModelTask.FACE_ANALYSIS:      ModelType.VISION,
    ModelTask.FACE_RESTORATION:   ModelType.VISION,
    ModelTask.IMAGE_TO_3D:        ModelType.VISION,
    ModelTask.OCR:                ModelType.OCR,
    ModelTask.TRANSCRIPTION:      ModelType.SPEECH,
    ModelTask.DIARIZATION:        ModelType.SPEECH,
    ModelTask.ALIGNMENT:          ModelType.SPEECH,
    ModelTask.TEXT_TO_SPEECH:     ModelType.SPEECH,
    ModelTask.AUDIO_ENHANCE:      ModelType.SPEECH,
    ModelTask.UPSCALE:            ModelType.UPSCALING,
    ModelTask.DENOISE:            ModelType.UPSCALING,
    ModelTask.TEXT_GENERATION:    ModelType.LLM,
    ModelTask.FEATURE_EXTRACTION: ModelType.EMBEDDING,
    ModelTask.PII_DETECTION:      ModelType.NLP,
    ModelTask.CAPTIONING:         ModelType.VLM,
    ModelTask.TEXT_TO_IMAGE:      ModelType.DIFFUSION,
    ModelTask.IMAGE_TO_IMAGE:     ModelType.DIFFUSION,
    ModelTask.TEXT_TO_VIDEO:      ModelType.DIFFUSION,
    ModelTask.IMAGE_TO_VIDEO:     ModelType.DIFFUSION,
    ModelTask.TEXT_TO_MUSIC:      ModelType.MUSIC,
    ModelTask.TEXT_TO_AUDIO:      ModelType.MUSIC,
    ModelTask.AUDIO_TO_SCORE:     ModelType.MUSIC,
    ModelTask.AUDIO_TO_MIDI:      ModelType.MUSIC,
    ModelTask.ROAD_SEGMENTATION:  ModelType.VISION,
    ModelTask.QUALITY_METRIC:     ModelType.VISION,
    ModelTask.HAND_GESTURE:       ModelType.VISION,
    ModelTask.END_OF_TURN:        ModelType.SPEECH,
    ModelTask.LIP_SYNC:           ModelType.LIPSYNC,
}


def model_type_for_task(task: str):
    """Catégorie d'une tâche (vocabulaire NÔTRE ou celui d'une plateforme), ou None.

    Accepte les deux vocabulaires : un tag de plateforme est d'abord ramené au nôtre par
    `canonical_task`. None = tâche inconnue — on ne devine pas, l'appelant reste libre de
    passer `model_type` explicitement.
    """
    t = canonical_task(task)
    for tache, categorie in TASK_TO_MODEL_TYPE.items():
        if tache.value == t:
            return categorie.value
    return None


def model_type_for_tasks(task: str):
    """Catégorie d'une OU PLUSIEURS tâches (« upscale,denoise ») : celle qu'elles partagent toutes,
    None si elles en ont plusieurs ou si l'une est inconnue — on ne devine pas.

    Une règle, deux lecteurs : le listage (`get_registry_models`) et le tirage (`select_model_id`).
    Jusqu'au 2026-10-14 le tirage passait la chaîne ENTIÈRE à `model_type_for_task`, qui rendait
    None : sans catégorie, `select_model` refuse de tirer, et l'« auto » de l'enhancer (domaine
    « agrandir, débruiter ») rendait son REPLI quel que soit le curseur, depuis le 2026-10-06."""
    kinds = {model_type_for_task(t.strip()) for t in str(task or '').split(',') if t.strip()}
    return kinds.pop() if len(kinds) == 1 else None


def uninstalled_q():
    """Le filtre (`Q`) des lignes DÉSINSTALLÉES : poids retirés par `uninstall_model`, ligne
    gardée pour son historique et marquée `uninstalled_at`.

    Une ligne ÉCARTÉE n'en est pas une (`is_available=False` + `exclusion`, décision humaine
    motivée) : elle garde ses poids ou non, mais sa raison reste une connaissance. Une ligne
    qu'une app DÉCLARE perd la marque au sync suivant (la découverte réécrit `extra_info`) et
    redevient « non téléchargée » — installable, donc plus désinstallée.
    Lu par la prospection (un dépôt désinstallé se repropose) et par le corpus de manifestes
    (un modèle désinstallé en sort, 2026-10-11)."""
    return models.Q(is_downloaded=False, extra_info__has_key='uninstalled_at')


# NOTRE tâche → MODALITÉS et ENTRÉES par défaut (vocabulaire de `INPUT_TYPES`, `app_modes.py`).
#
# Pourquoi (2026-09-19, chantier « source unique des capacités ») : `modalities`,
# `inputs_required` et `inputs_optional` sont ce que lit l'appariement entrée ↔ modèle
# (`model_selector.matches_inputs`) et ce dont `INPUT_MODEL_MATCHING §6.3` dérive les slots
# d'une app. Ils étaient écrits EN DUR, app par app, dans `model_registry` (13 sites) — donc
# jamais pour un modèle qu'aucune app ne déclare : 8 modèles installés par la chaîne générique
# n'avaient que `task`. Cette table dit ce qu'une tâche IMPLIQUE ; elle est remplie avec
# exactement ce que le registre écrivait, et elle ne fait que COMBLER (fusion clé par clé —
# un modèle qui déclare plus, comme SAM3 promptable par texte ou LTX qui accepte une image
# en option, garde sa déclaration). Le jugement d'un rôle LLM (scout) complète ce que la
# tâche ne dit pas : langues, clonage, contexte.
# `check_model_taxonomy` vérifie qu'aucune tâche n'en manque et que les valeurs sont du vocabulaire.
TASK_DEFAULT_INPUTS = {
    #                              modalities                      inputs_required            inputs_optional
    ModelTask.DETECT:             (('image', 'video'),             ('work_file',),            ()),
    # Une PAGE (scan, image, PDF) — pas une vidéo ; et un détecteur ouvert lit ce qu'on cherche.
    ModelTask.LAYOUT_DETECTION:   (('image', 'document'),          ('work_file',),            ()),
    ModelTask.ZERO_SHOT_OBJECT_DETECTION: (('image', 'video'),     ('work_file', 'prompt'),   ()),
    ModelTask.SEGMENT:            (('image', 'video'),             ('work_file',),            ()),
    ModelTask.CLASSIFY:           (('image', 'video'),             ('work_file',),            ()),
    ModelTask.OBB:                (('image', 'video'),             ('work_file',),            ()),
    ModelTask.POSE:               (('image', 'video'),             ('work_file',),            ()),
    ModelTask.OCR:                (('image', 'document'),          ('work_file',),            ()),
    ModelTask.DEPTH_ESTIMATION:   (('image', 'video'),             ('work_file',),            ()),
    ModelTask.FACE_ANALYSIS:      (('image', 'video'),             ('work_file',),            ()),
    ModelTask.FACE_RESTORATION:   (('image', 'video'),             ('work_file',),            ()),
    ModelTask.IMAGE_TO_3D:        (('image',),                     ('work_file',),            ()),
    ModelTask.TRANSCRIPTION:      (('audio',),                     ('work_audio',),           ()),
    ModelTask.DIARIZATION:        (('audio',),                     ('work_audio',),           ()),
    ModelTask.ALIGNMENT:          (('audio', 'text'),              ('work_audio', 'work_result'), ()),
    ModelTask.TEXT_TO_SPEECH:     (('audio',),                     ('prompt',),               ()),
    ModelTask.AUDIO_ENHANCE:      (('audio',),                     ('work_audio',),           ()),
    ModelTask.DENOISE:            (('image', 'video'),             ('work_file',),            ()),
    ModelTask.UPSCALE:            (('image', 'video'),             ('work_file',),            ()),
    ModelTask.TEXT_GENERATION:    (('text',),                      ('prompt',),               ()),
    ModelTask.FEATURE_EXTRACTION: (('text',),                      ('prompt',),               ()),
    # Le document de l'Anonymizer (son texte extrait), ou le texte qu'un appel distant enverrait.
    ModelTask.PII_DETECTION:      (('text', 'document'),           ('work_file',),            ('prompt',)),
    ModelTask.CAPTIONING:         (('image',),                     ('work_file',),            ()),
    ModelTask.TEXT_TO_IMAGE:      (('image',),                     ('prompt',),               ()),
    ModelTask.IMAGE_TO_IMAGE:     (('image',),                     ('prompt', 'work_image'),  ()),
    ModelTask.TEXT_TO_VIDEO:      (('video',),                     ('prompt',),               ()),
    ModelTask.IMAGE_TO_VIDEO:     (('video',),                     ('prompt', 'work_image'),  ()),
    ModelTask.TEXT_TO_MUSIC:      (('audio',),                     ('prompt',),               ()),
    ModelTask.TEXT_TO_AUDIO:      (('audio',),                     ('prompt',),               ()),
    ModelTask.AUDIO_TO_SCORE:     (('audio',),                     ('work_audio',),           ()),
    ModelTask.AUDIO_TO_MIDI:      (('audio',),                     ('work_audio',),           ()),
    ModelTask.ROAD_SEGMENTATION:  (('image', 'video'),             ('work_file',),            ()),
    ModelTask.QUALITY_METRIC:     (('image',),                     ('work_file',),            ()),
    # Le flux de la webcam, lu image par image dans le navigateur.
    ModelTask.HAND_GESTURE:       (('image', 'video'),             ('work_file',),            ()),
    # La phrase en cours, captée au micro par l'écoute de l'assistant.
    ModelTask.END_OF_TURN:        (('audio',),                     ('work_audio',),           ()),
    ModelTask.LIP_SYNC:          (('image', 'audio', 'video'),    ('work_image', 'work_audio'), ()),
}


def default_inputs_for(task: str) -> dict:
    """`{modalities, inputs_required[, inputs_optional]}` qu'une tâche IMPLIQUE, ou {} si la
    tâche est inconnue (on ne devine pas). Accepte le vocabulaire d'une plateforme
    (`canonical_task`). Les listes vides ne sont pas écrites : « rien d'optionnel » n'est pas
    un fait à poser par-dessus une déclaration."""
    value = canonical_task(task)
    for known, (modalities, required, optional) in TASK_DEFAULT_INPUTS.items():
        if known.value == value:
            out = {'modalities': list(modalities), 'inputs_required': list(required)}
            if optional:
                out['inputs_optional'] = list(optional)
            return out
    return {}


def platform_tag(task: str, platform: str = 'huggingface'):
    """Tag de `task` (vocabulaire NÔTRE) chez une plateforme, ou None s'il n'y en a pas.

    Lecture DIRECTE de `TASK_TO_PLATFORM_TAGS`. `None` n'est pas un trou à combler :
    `obb`, `lip-sync` et `text-to-music` n'ont volontairement aucun équivalent HF.
    """
    try:
        i = REFERENCE_PLATFORMS.index(platform)
    except ValueError:
        return None
    for t, tags in TASK_TO_PLATFORM_TAGS.items():
        if t.value == task:
            return tags[i]
    return None


#: Tags de plateforme COMPOSITES qui retombent sur une de NOS tâches. Ce ne sont pas des
#: secondes valeurs de `TASK_TO_PLATFORM_TAGS` — le tag PRINCIPAL d'une tâche reste unique,
#: c'est lui que `platform_tag` rend ; ce sont des graphies d'éditeur que la carte d'un dépôt
#: porte et que nous ne nommons pas plus finement.
#:
#: ⚠ Ces trois rattachements ne sont PAS nouveaux : ils vivaient dans
#: `prospector._HF_TAG_TASK` + `_TASK_MODEL_TYPE`, deux tables que la même brique lisait en
#: parallèle de celle-ci (`select_model_id` par l'une, `get_registry_models` par l'autre).
#: Mesuré avant de les fondre (2026-09-19) : **0 désaccord** entre les deux — 9 tags d'accord,
#: 3 que seule la table de la prospection connaissait, ces trois-ci. Ils déménagent donc ici,
#: au domicile de la taxonomie, et la prospection les LIT. *Deux vocabulaires pour un même
#: fait ne divergent pas bruyamment : ils se rejoignent sur un repli qui a l'air de marcher.*
PLATFORM_TAG_ALIASES = {
    # VLM conversationnel (image + question → texte) : pour nous c'est du légendage au sens
    # large — même catégorie `vlm` que `captioning`, dont le tag principal est `image-to-text`.
    'image-text-to-text':  ModelTask.CAPTIONING,
    # TI2V : une image ET un prompt → vidéo (cf. FastWan 2.2). Notre `image-to-video` le porte ;
    # le prompt est une entrée de plus, pas un autre métier.
    'image-text-to-video': ModelTask.IMAGE_TO_VIDEO,
    # ⚠ WAMA ne nomme pas encore la sortie audio+vidéo CONJOINTE (le modèle produit les deux).
    # La catégorie, elle, est bien `diffusion` : on rattache à `text-to-video` sans prétendre
    # que la piste audio est décrite. À scinder le jour où un tel modèle entre au catalogue.
    'text-to-audio-video': ModelTask.TEXT_TO_VIDEO,
}


def canonical_task(task: str):
    """Traduit une tâche EXPRIMÉE DANS LE VOCABULAIRE D'UNE PLATEFORME vers le nôtre.

    Rend la valeur `ModelTask` correspondante, ou `task` inchangée si elle est déjà des
    nôtres (ou inconnue — on ne devine pas). Lecture INVERSE de la table ci-dessus, donc
    aucune seconde table à tenir : ajouter une plateforme reste une colonne, pas un
    dictionnaire de plus.

    ⚠ POURQUOI (mesuré le 2026-08-31, route F4b). Le catalogue parle NOTRE vocabulaire
    (`transcription`, `segment`, `text-to-music` — volontairement plus fin que HF, cf.
    l'entête de cette table) ; la prospection et les manifestes parlent souvent celui de
    HuggingFace. Une requête d'options `task='automatic-speech-recognition'` ne trouvait
    donc AUCUNE cible — et le repli « liste non filtrée » de `get_registry_models` servait
    alors TOUTE la catégorie `speech` : un select ASR proposait bark, kokoro et un
    débruiteur, en silence. *Deux vocabulaires pour un même fait ne divergent pas bruyamment :
    ils se rejoignent sur un repli qui a l'air de marcher.*
    """
    if not task:
        return task
    known = {t.value for t in ModelTask}
    if task in known:
        return task
    for t, tags in TASK_TO_PLATFORM_TAGS.items():
        if task in [x for x in tags if x]:
            return t.value
    alias = PLATFORM_TAG_ALIASES.get(task)
    return alias.value if alias else task


def wama_task(task: str):
    """`task` ramenée à NOTRE vocabulaire, ou None si elle n'en fait pas partie.

    Différence avec `canonical_task`, qui rend l'entrée INCHANGÉE quand elle est inconnue :
    ici l'inconnu est dit. C'est ce qu'il faut à qui ÉCRIT une tâche en base — poser un tag
    d'éditeur non traduit dans `capabilities['task']` fabriquerait une valeur hors
    `ModelTask`, que ni la sélection ni les bancs ne savent lire.
    """
    t = canonical_task(task)
    return t if t in {x.value for x in ModelTask} else None

# Taches portees par des plateformes et ABSENTES de chez nous. Pas un oubli : rien ne les
# consomme aujourd'hui. Notees pour que la prochaine question << ou est la profondeur ? >> trouve
# une reponse ecrite. `Gaze Detection` (Roboflow) est a surveiller — un labo qui analyse la
# conduite finira par en vouloir.
PLATFORM_TASKS_NOT_CARRIED = {
    # (`Depth Estimation` en est SORTIE le 2026-08-05 : declaree dans ModelTask en amont du
    #  chantier cam_analyzer/profondeur.)
    # DEJA UTILISE dans WAMA — wama_lab/face_analyzer (eye_tracking.py), mais l'app a ses propres
    # venv_win/venv_linux et ses modeles ne sont PAS au catalogue. A porter (Fabien, 2026-08-05) :
    # c'est un cas ou la tache existe deja en production sans que le registre le sache.
    'Gaze Detection': 'roboflow — et wama_lab/face_analyzer, hors registre',
    'Semantic Segmentation': 'roboflow — cf. remarque ci-dessus sur `segment`',
    # (`zero-shot-object-detection` en est SORTIE le 2026-10-07 : déclarée dans ModelTask,
    #  LocateAnything la porte.)
}


class ModelAbility(models.TextChoices):
    """
    Ce qu'un modele sait faire EN PLUS de sa tache — plusieurs a la fois, contrairement a `task`.

    Vocabulaire repris d'Ollama (`/api/show` -> capabilities), le seul referentiel qui le porte.
    HuggingFace n'a rien d'equivalent, alors que ce sont ces capacites qui decident si un modele
    peut servir l'assistant (appeler un outil) ou lire une image.
    """
    COMPLETION = 'completion', 'Génération'
    VISION = 'vision', 'Lecture d’images'
    AUDIO = 'audio', 'Écoute audio'
    TOOLS = 'tools', 'Appel d’outils'
    THINKING = 'thinking', 'Raisonnement explicite'
    EMBEDDING = 'embedding', 'Vectorisation'


class ModelSource(models.TextChoices):
    """Le VOCABULAIRE des sources de modèle — le premier segment de `AIModel.model_key`
    (`model_keys.split_key`), que la découverte écrit et que la validation du manifeste `model`
    lit. Chaque valeur est la clé d'une déclaration existante : une app (`app_registry`) ou une
    source du registre (`external_sources` : fournisseur distant, plateforme, serveur de poids).

    AUCUN LIBELLÉ ici (2026-10-22, Fabien : « le moins de choses écrites à la main possible ») :
    une source se NOMME par `source_identity` — l'identité de l'app, la phrase de coût d'un
    fournisseur (`remote_origin_label`), le nom d'une plateforme au registre. Les libellés écrits
    ici recopiaient ces noms et avaient divergé (13 sur 19, « Claude Code (abonnement) »,
    « HuggingFace ») ; le champ `source` ne porte plus de `choices=`, si bien qu'une source de plus
    ne demande plus de migration (il y en avait eu six, 0008 → 0024). Garde :
    `tests_source_identity.SourceVocabularyTest`.
    """
    WAMA_IMAGER = 'imager'
    WAMA_DESCRIBER = 'describer'
    WAMA_ANONYMIZER = 'anonymizer'
    WAMA_TRANSCRIBER = 'transcriber'
    WAMA_SYNTHESIZER = 'synthesizer'
    WAMA_ENHANCER = 'enhancer'
    WAMA_AVATARIZER = 'avatarizer'
    # Converter n'a PAS de modèles IA (ffmpeg/pandoc) → pas de source dédiée.
    WAMA_COMPOSER = 'composer'
    WAMA_READER = 'reader'
    # Monde LAB (2026-09-05) : le champ porte le nom d'app, pas le monde — c'est la même clé que
    # la déclaration de l'app, il ne faut pas la préfixer.
    WAMA_FACE_ANALYZER = 'face_analyzer'
    # Fournisseurs DISTANTS (2026-09-15, ROADMAP §8d Phase 3, étape 4b — verrou ① levé). La valeur
    # est la clé de la source `external_sources` (adresse, variable de clé, hébergement, coût). Un
    # modèle distant entre au catalogue par DÉCOUVERTE, avec la clé d'un utilisateur ; son moteur se
    # lit dans `composition.runtime.engine`, comme pour tout modèle : le fournisseur se DÉRIVE.
    ALBERT = 'albert'
    ILAAS = 'ilaas'
    OPENROUTER = 'openrouter'
    ANTHROPIC = 'anthropic'
    CLAUDE_CODE = 'claude_code'
    OLLAMA = 'ollama'
    HUGGINGFACE = 'huggingface'
    # Poids publiés dans une VERSION GitHub (2026-10-07, pilote `github` de `install_from_spec`) :
    # le pendant de HUGGINGFACE pour le balayage générique — même valeur que la plateforme et que
    # la source déclarée (`external_sources`, qui déclare aussi sa fiche : `model_platforms`).
    GITHUB = 'github'
    # Serveurs de poids OFFICIELS du registre (famille « poids », 2026-10-27) : le modèle d'une
    # BRIQUE commune, qu'aucune app ne porte, se range sous la source d'où viennent ses fichiers
    # DÉCLARÉS — le patron de YOLOPv2 (`github:`). Remplace `custom` (« ajouts manuels »), qui
    # cachait une provenance pourtant déclarée fichier par fichier (Fabien : « il faut corriger
    # le rangement ») : LPIPS (dorsale AlexNet de torchvision) et les gestes de la main.
    PYTORCH_DOWNLOAD = 'pytorch_download'
    MEDIAPIPE_MODELS = 'mediapipe_models'


#: Les relations qu'une carte du Hub nomme entre un modèle et son `base_model` — vocabulaire repris
#: tel quel (2026-10-27). `quantized` seule fait de la ligne CE modèle (`AIModel.quantized_base`) ;
#: le manifeste `model` valide sa paire contre cette liste.
BASE_RELATION_QUANTIZED = 'quantized'
BASE_MODEL_RELATIONS = ('adapter', 'finetune', 'merge', BASE_RELATION_QUANTIZED)


def source_groups() -> list:
    """Les GROUPES du filtre « Source » du model manager, dans leur ordre — `[{'key', 'label'}]`.

    Aucun n'est écrit ici : une app se range dans son MONDE (`app_registry.WORLD_SECTIONS`, l'ordre
    et le libellé du menu, de l'accueil et de `/apps/`), une source du registre dans sa FAMILLE
    (`external_sources.KINDS`, la facette « Type » de la page des sources). Remplace les trois
    groupes écrits à la main le 2026-10-20 (« Apps WAMA », « Fournisseurs distants »,
    « Plateformes »), qui redisaient ces déclarations en les simplifiant : Ollama, un service local,
    et Hugging Face, un catalogue, y tombaient sous le même mot.
    """
    from wama.common import external_sources
    from wama.common.app_registry import WORLD_SECTIONS
    worlds = sorted(WORLD_SECTIONS.items(), key=lambda item: item[1].get('order', 0))
    return ([{'key': f'world:{world}', 'label': section['label']} for world, section in worlds]
            + [{'key': f'kind:{kind}', 'label': label}
               for kind, label in external_sources.KINDS.items()])


def source_identity(source: str) -> dict:
    """LE nom d'une source de modèle (`AIModel.source`) — `{'key', 'group', 'label'}`.

    La clé a deux natures, et chacune est déjà NOMMÉE ailleurs : rien n'est redit ici.
    • une app → son identité commune (`app_registry.app_identity`), rangée dans son monde ;
    • un FOURNISSEUR distant (famille `llm` du registre) → `remote_origin_label`, la phrase des
      sélecteurs de modèle : hébergement · fournisseur · COÛT. « Claude Code » seul ne dit pas
      l'abonnement — Claude Code peut aussi tourner sur l'API ; « Cloud commercial · Claude Code ·
      abonnement » et « Cloud commercial · API Anthropic (Claude) · facturé à l'usage », si ;
    • une autre source du registre (Hugging Face Hub, Ollama, GitHub, un serveur de poids) → son
      nom déclaré.
    Une valeur que rien ne déclare (une ligne d'avant un renommage) se rend telle quelle, hors
    groupe : `group` est une clé de `source_groups()`, '' pour elle. Il n'y en a plus aucune
    dans l'énumération depuis le 2026-10-27 (`custom` retiré, R180).

    ⚠ Corrigé le 2026-10-22 (Fabien : « je dois connaître la provenance exacte des modèles, donc
    savoir si c'est Claude API ou Claude abonnement »). La version du 20/10 nommait un fournisseur
    par son seul nom au registre, qui a perdu « (abonnement) » le 10/10 parce que le COÛT se dit par
    `remote_origin_label` : le filtre, le badge et l'inspecteur ne disaient plus l'abonnement,
    alors que la route consignée le jour même prescrivait `remote_origin_label`
    (`WAMA_APP_GENERATION_ROUTE §10.6 P1`).
    """
    from wama.common import external_sources
    from wama.common.app_registry import app_identity
    app = app_identity(source)
    if app['declared']:
        return {'key': source, 'group': f"world:{app['world']}" if app['world'] else '',
                'label': app['label']}
    declared = external_sources.by_key().get(source)
    if declared is not None:
        label = (external_sources.remote_origin_label(source) if declared.kind == 'llm'
                 else declared.label)
        return {'key': source, 'group': f'kind:{declared.kind}', 'label': label}
    return {'key': source, 'group': '', 'label': source}


EXECUTION_LOCAL = 'local'
EXECUTION_CLOUD = 'cloud'
EXECUTION_CHOICES = [(EXECUTION_LOCAL, 'Local'), (EXECUTION_CLOUD, 'Distant')]
#: Vocabulaire des coûts — UN domicile, `external_sources.COST_TIERS` (2026-10-10), que les
#: libellés d'origine lisent aussi. Mêmes valeurs et libellés qu'avant : aucune migration.
from wama.common.external_sources import COST_TIERS as _COST_TIERS  # noqa: E402 (module feuille)
COST_TIER_CHOICES = list(_COST_TIERS)


class AIModel(ScopedVisibility):
    """
    Unified AI Model catalog entry.
    Stores both downloaded and available (not yet downloaded) models.

    PROVENANCE (2026-10-18, `ROADMAP §29` étape 3) : un modèle est SYSTÈME (`owner` vide, public,
    tenu par WAMA) ou à un AUTEUR, avec une portée (`ScopedVisibility`). La provenance naît au
    geste d'installation (`model_installer.install_owner`) : un modèle déclaré par une app ou
    installé par un administrateur est système ; celui qu'un développeur fait naître est à lui,
    privé, jusqu'à sa promotion. Le catalogue se LIT par `AIModel.objects.catalogue_visible_to(user)`
    — sélection automatique, selects des apps, page du catalogue, assistant.
    """
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='owned_models',
                              help_text="Vide = modèle système (déclaré ou installé par un admin).")
    # Le défaut de la portée est PUBLIC ici, pas privé comme pour une instance : une ligne naît du
    # disque, sans auteur, donc système. `db_default` : le code en service avant sa relance insère
    # sans cette colonne (synchro périodique).
    visibility = models.CharField(max_length=12, choices=ScopedVisibility.VIS_CHOICES,
                                  default=ScopedVisibility.VIS_PUBLIC,
                                  db_default=ScopedVisibility.VIS_PUBLIC, db_index=True)

    objects = ScopedManager()

    # Primary identifier (unique per source)
    # Format: "{source}:{model_id}" e.g., "imager:wan-ti2v-5b", "ollama:llama3.2"
    model_key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique identifier: {source}:{model_id}"
    )

    # Display name
    name = models.CharField(max_length=255, db_index=True)

    # Classification
    model_type = models.CharField(
        max_length=20,
        choices=ModelType.choices,
        db_index=True
    )
    # Le vocabulaire est `ModelSource` (valeurs seules) ; le NOM d'une source, `source_identity`.
    # Pas de `choices=` (2026-10-22) : il figeait des libellés recopiés et une migration par source.
    source = models.CharField(
        max_length=20,
        db_index=True
    )

    # Description — deux tiers par usage :
    #   description       = long/canonique (page model_manager, à-propos, tooltip détaillé)
    #   description_short = une ligne pour l'aide sous le sélecteur de modèle (WamaModelHelp)
    description = models.TextField(blank=True, default='')
    description_short = models.CharField(max_length=255, blank=True, default='')

    # (`hf_id`, le dépôt du Hub écrit à part avant `platform_ref`, est RETIRÉ le 2026-10-27 — migration
    # `0031`, `REMOVAL_LEDGER` R181 : le dépôt se lit par `hf_repo`, le modèle canonique d'une
    # quantification par `quantized_base`.)

    # Resource requirements
    vram_gb = models.FloatField(default=0, help_text="Estimated VRAM in GB")
    ram_gb = models.FloatField(default=0, help_text="Estimated RAM in GB")
    disk_gb = models.FloatField(default=0, help_text="Disk space in GB")

    # Status flags
    is_downloaded = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Model files exist locally"
    )
    is_loaded = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Model is currently loaded in memory"
    )
    is_available = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Model is available for use (not deprecated/removed)"
    )

    # ── Exécution LOCALE ou DISTANTE (verrou §8d ① levé le 2026-09-15) ────────────────────
    # Un modèle distant n'a ni poids ni VRAM ici (`is_downloaded` reste faux, `vram_gb` à 0) :
    # sa disponibilité est une clé d'API ouverte à l'utilisateur. ⚠ NON-RÉGRESSION : la
    # sélection automatique l'écarte tant que l'appelant ne fournit pas les modèles distants
    # AUTORISÉS (`select_model(cloud_keys=…)`) — sans autorisation, le tirage est inchangé.
    execution = models.CharField(
        max_length=8, choices=EXECUTION_CHOICES, default=EXECUTION_LOCAL, db_index=True,
        help_text="local = poids sur cette machine ; cloud = appel à un fournisseur distant",
    )
    #: Coût d'un modèle distant — vide pour un modèle local.
    cost_tier = models.CharField(
        max_length=16, blank=True, default='', choices=COST_TIER_CHOICES,
        help_text="Distant seulement : gratuit (quota), facturé à l'usage, ou abonnement",
    )

    # File paths and format
    local_path = models.CharField(
        max_length=1024,
        blank=True,
        default='',
        help_text="Local file/directory path"
    )
    format = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Current format: pt, safetensors, onnx, gguf, etc."
    )
    preferred_format = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text="Recommended format per policy"
    )

    # Flexible metadata (JSON)
    extra_info = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional model-specific metadata"
    )

    # Capacités fonctionnelles du modèle — source UNIQUE consommée par : filtrage UI
    # (voix/langues), sélection par tâche (select_model requires=…), méta-app (compat I/O),
    # description dynamique. Schéma souple par type. Conventions courantes :
    #   speech/TTS : {"supports_cloning": bool, "languages": ["fr","en",...]}
    #   vision/YOLO: {"classes": ["face","plate",...], "task": "detect|segment|pose"}
    #   vlm/llm    : {"languages": [...], "context_length": int}
    capabilities = models.JSONField(
        default=dict,
        blank=True,
        help_text="Functional capabilities (cloning, languages, classes, task...) — single source for UI filtering & task selection"
    )

    # Conversion capabilities
    can_convert_to = models.JSONField(
        default=list,
        blank=True,
        help_text="List of formats model can be converted to"
    )

    # Backend reference for loading/unloading
    backend_ref = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text="Backend identifier for model operations"
    )

    # ── Prospection (proposé par IA) ──────────────────────────────────────────
    # Une entrée is_proposed=True est un CANDIDAT (MAJ d'un modèle existant ou
    # nouveau modèle/concurrent) suggéré par la prospection, pas un modèle réel
    # installé. Exclu des filtres all/loaded/downloaded ; visible sous l'onglet
    # « Proposés par IA ». Le verdict des agents est stocké dans extra_info.
    is_proposed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Candidat de prospection (proposé par IA), pas un modèle installé"
    )
    proposal_kind = models.CharField(
        max_length=10,
        blank=True,
        default='',
        choices=[('update', 'Mise à jour'), ('new', 'Nouveau / concurrent')],
        help_text="Type de proposition : maj d'un modèle existant ou nouveau modèle"
    )
    confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Taux de confiance de la recommandation (0..1)"
    )
    update_complexity = models.CharField(
        max_length=10,
        blank=True,
        default='',
        choices=[('simple', 'Simple'), ('moderate', 'Modérée'), ('complex', 'Complexe')],
        help_text="Complexité estimée de la mise à jour / installation"
    )

    # ── Qualité (indice a priori) ─────────────────────────────────────────────
    # Sert à ORDONNER les candidats de `select_model()` autrement que par la taille : trier par
    # VRAM assimile « le plus gros » à « le meilleur », ce qu'un MoE dément (qwen3.6:35b active
    # 8 experts sur 256 — qualité d'un 36B, coût d'un 3B, mais 22 Go de VRAM).
    # Calculé par `services/model_quality.py` depuis des propriétés STRUCTURELLES déclarées par
    # le fournisseur (paramètres, contexte, quantification) — jamais un benchmark inventé.
    # Une valeur posée à la main PRIME : c'est le point d'entrée d'une mesure interne future.
    # NULL = inconnu, ce qui doit rester distinct de « mauvais » (cf. le tri, qui replie sur vram).
    quality_index = models.FloatField(
        null=True, blank=True, db_index=True,
        help_text="Indice de qualité a priori (structurel). NULL = inconnu, pas zéro.")

    # ── Qualité (benchmark TIERS confronté) — 2e étage de l'échelle des signaux ───────────
    # a priori (ci-dessus) < benchmark tiers confronté (ICI) < mesure interne (qui primera
    # toujours — contrainte qc.py §16.5). Alimenté par `services/benchmark_sync.py`
    # (Artificial Analysis Intelligence Index, confronté à l'Elo Arena stocké en meta) via
    # `manage.py sync_benchmarks` — champ SÉPARÉ de quality_index : la découverte (sync_models)
    # n'a PAS autorité ici et ne l'écrase jamais (leçon audio_enhance/quality_index du 18/08).
    # NULL = non apparié à une mesure ; le tri ne compare des benchmarks QUE si tout le lot
    # en a un (même règle d'échelles que `_rank_key`). Jamais une valeur inventée.
    benchmark_index = models.FloatField(
        null=True, blank=True, db_index=True,
        help_text="Intelligence Index (Artificial Analysis) apparié. NULL = non mesuré/apparié.")
    benchmark_meta = models.JSONField(
        default=dict, blank=True,
        help_text="Traçabilité du benchmark : source, nom apparié, Elo Arena, date, version.")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this model was synced from source"
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this model was loaded/used"
    )

    class Meta:
        verbose_name = "AI Model"
        verbose_name_plural = "AI Models"
        ordering = ['source', 'model_type', 'name']
        indexes = [
            models.Index(fields=['source', 'model_type']),
            models.Index(fields=['is_downloaded', 'is_available']),
            models.Index(fields=['updated_at']),
        ]

    def __str__(self):
        status = "Downloaded" if self.is_downloaded else "Not Downloaded"
        return f"{self.name} ({self.source}) - {status}"

    @property
    def model_id(self):
        """Extract model_id from model_key (part after colon)."""
        if ':' in self.model_key:
            return self.model_key.split(':', 1)[1]
        return self.model_key

    @property
    def is_system(self) -> bool:
        """Sans auteur : tenu par WAMA (`ROADMAP §29`, décision a — système ≠ public partagé)."""
        return self.owner_id is None

    # Licence du modele. Portee par le manifeste (kind `model`, identity.license) et projetee ici :
    # manifeste = source, registre = projection. Necessaire a l'audit de licences WAMA (2026-08),
    # qui doit s'aligner sur le composant le MOINS permissif -- impossible sans inventaire.
    license = models.CharField(max_length=64, blank=True, default='', db_index=True,
                               help_text="Identifiant SPDX quand il existe (apache-2.0, agpl-3.0, cc-by-nc-4.0…).")

    # Auteur/editeur du modele. INDISSOCIABLE de `license` : une licence a attribution
    # (cc-by-*, bsd, mit, et l'Etalab 2.0 de Panoramax) est inapplicable sans le nom a citer --
    # on ne pouvait donc pas satisfaire les licences qu'on venait tout juste d'inventorier.
    # Vocabulaire repris de `media_library/providers/base.Asset` (seul endroit de WAMA ou le
    # couple existait deja), et non reinvente. Porte par le manifeste comme `license`.
    author = models.CharField(max_length=200, blank=True, default='', db_index=True,
                              help_text="Auteur/editeur declare en amont (organisation HuggingFace, "
                                        "editeur Ollama, laboratoire…).")

    # Identite du modele sur SA plateforme : 'huggingface:org/repo', 'ollama:gemma4',
    # 'roboflow:projet/3'. C'est le FAIT ; l'URL n'en est qu'un rendu, derive par platform_url --
    # sinon un changement de schema d'adresse chez la plateforme invaliderait autant de chaines
    # stockees qu'il y a de modeles.
    platform_ref = models.CharField(max_length=255, blank=True, default='', db_index=True)

    # ACCES au depot amont. Fait MECANIQUE tire de la source (`HfApi().model_info().gated`),
    # porte par le manifeste comme `license` (identity.gated) et projete ici.
    #
    # Ne existe parce que la contrainte vivait UNIQUEMENT en prose : la description de SAM3
    # disait « Necessite un token HuggingFace configure », ce qu'aucun selecteur, aucun
    # installeur et aucun planificateur ne pouvait lire. Une contrainte en prose n'agit pas.
    #
    # ⚠ QUATRE valeurs, et le vide n'est PAS « libre » -- c'est INCONNU. Un modele jamais
    # ausculte ne doit pas se presenter comme accessible : c'est la meme regle que « VRAM
    # inconnue != gratuite ». D'ou `no` explicite pour un depot VERIFIE libre.
    #   ''       inconnu -- jamais interroge
    #   'no'     verifie libre
    #   'auto'   conditions a accepter en ligne, acces immediat
    #   'manual' approbation HUMAINE chez l'editeur, delai non maitrise
    # La distinction auto/manual est operationnelle, pas cosmetique (mesure le 2026-09-07 :
    # facebook/sam3 = 'manual', pyannote/speaker-diarization-3.1 = 'auto') : un jeton suffit
    # pour l'un, pas pour l'autre.
    GATED_INCONNU, GATED_LIBRE, GATED_AUTO, GATED_MANUEL = '', 'no', 'auto', 'manual'
    GATED_CHOICES = [
        (GATED_INCONNU, 'Inconnu — jamais interrogé'),
        (GATED_LIBRE, 'Libre — accès vérifié sans condition'),
        (GATED_AUTO, 'Conditionné — acceptation en ligne, accès immédiat'),
        (GATED_MANUEL, 'Sur approbation — un humain de l’éditeur valide'),
    ]
    gated = models.CharField(max_length=8, blank=True, default=GATED_INCONNU,
                             choices=GATED_CHOICES, db_index=True,
                             help_text="Régime d'accès au dépôt amont, tiré de la source. "
                                       "Vide = inconnu, jamais « libre ».")

    # Contrat de SORTIE du prompt attendu par CE modele (markdown, anglais) : longueur,
    # structure, sections, tags de paroles, prompt negatif… Fait DECLARE comme `license` --
    # porte par le manifeste `model` (body.prompts.contract), JAMAIS par la decouverte
    # (`capabilities` est reecrit en entier a chaque sync, ce champ est preserve). Injecte
    # au system prompt d'enrichissement APRES le skill d'app : le skill porte la methode,
    # le modele porte son contrat (doctrine 2026-08-26, prompt_skills/README.md).
    prompt_contract = models.TextField(blank=True, default='',
                                       help_text="Contrat de sortie du prompt pour ce modele "
                                                 "(markdown), declare par son manifeste.")

    # ANATOMIE d'un modele multi-composants + son contrat d'execution. Fait DECLARE comme
    # `license`/`prompt_contract` -- porte par le manifeste `model` (body.composition), JAMAIS
    # par la decouverte. Ne le declarer que si le modele est REELLEMENT compose (2026-08-27,
    # cas d'ecole MiniMax-Music3 : 5 GGUF = 1 modele -- un fichier seul n'est pas un modele).
    #   {'components': [{'role': 'language_model', 'pattern': '*-language_model-Q8_0.gguf',
    #                    'format': 'gguf'}, ...],
    #    'runtime': {'engine': 'audio-cpp', ...}}
    # Consommateurs : l'INSTALLATION derive ses allow_patterns des components (jeu coherent,
    # jamais le depot entier) ; le BACKEND compose derive quoi charger et comment (engine).
    # Un modele mono-fichier n'en a pas besoin : composition vide = cas general inchange.
    composition = models.JSONField(default=dict, blank=True,
                                   help_text="Composants + runtime d'un modele compose "
                                             "(declare par son manifeste, vide sinon).")

    @property
    def hf_repo(self) -> str:
        """Le dépôt du Hub (`org/nom`) d'où vient le modèle — DÉRIVÉ de `platform_ref`, '' pour une
        autre plateforme (`external_sources.hf_repo`). Ce qu'on passe à `from_pretrained`, ce qu'on
        cherche dans les snapshots installés, ce qu'on interroge sur le Hub."""
        from wama.common.external_sources import hf_repo
        return hf_repo(self.platform_ref)

    @property
    def quantized_base(self) -> str:
        """Le modèle CANONIQUE dont cette ligne est une QUANTIFICATION (un GGUF du Hub tiré par
        Ollama), '' sinon — `extra_info['base_model']` quand la relation déclarée est `quantized`.

        Le vocabulaire est celui du Hub (`base_model` + `base_model_relation` de la carte d'un
        modèle). Il sépare deux faits que `hf_id` confondait jusqu'au 2026-10-27 : d'où viennent les
        poids (`platform_ref`, le dépôt GGUF) et quel modèle ils SONT (`base_model`, ce qu'un banc
        publie). Une LoRA porte aussi `base_model`, sa DORSALE : sans la relation `quantized`, elle
        n'est pas sa dorsale, et ce n'est pas ici qu'elle se lit."""
        info = self.extra_info or {}
        if info.get('base_model_relation') != BASE_RELATION_QUANTIZED:
            return ''
        return str(info.get('base_model') or '').strip()

    @property
    def quantization(self) -> str:
        """La PRÉCISION des poids tels qu'ils tournent ici (`Q4_K_M`, `Q6_K`, `Q8_0`, `BF16`…), ''
        quand rien ne la dit — celle que relève la synchronisation d'Ollama (`/api/show`).

        Dite AU TIRAGE (2026-10-29, Fabien : « garder la précision qu'ils sont quantisés au tirage
        pour en être informé à minima ») : une quantification HÉRITE la note de son modèle d'origine
        (`quantized_base`), en borne haute — la précision dit ce que cette note ne dit pas."""
        return str((self.extra_info or {}).get('quantization') or '').strip()

    def hub_repos(self) -> set:
        """Les dépôts du Hub que cette ligne EST, en minuscules : celui de ses poids (`hf_repo`) et,
        pour une quantification, son modèle canonique (`quantized_base`). LA règle par ligne de
        « déjà chez nous » (`prospector.catalogue_repos`) et de l'appariement du banc
        (`benchmark_sync._local_repos`), qui la recopiaient chacun."""
        return {r.lower() for r in (self.hf_repo, self.quantized_base) if r}

    def platform_refs(self):
        """`platform_ref`, puis ce que la ligne porte déjà du même fait tant qu'il n'est pas
        renseigné partout (il vient du manifeste) : une clé `ollama:` → `ollama:<famille>`. LA
        règle de dérivation : le lien de la card la lit, et `backfill_platform_refs` pose la
        première référence d'une ligne qui n'en a pas. (`hf_id` n'y entre plus depuis le
        2026-10-27 : mesuré ce jour, aucune ligne ne le portait sans `platform_ref`.)"""
        refs = [self.platform_ref] if self.platform_ref else []
        if 'ollama:' in (self.model_key or ''):
            # L'identité d'un tag Ollama a SA fonction (`provenance.ollama_identity`).
            from .services.provenance import ollama_identity
            ref = (ollama_identity(self.name) or {}).get('platform_ref')
            if ref:
                refs.append(ref)
        return refs

    def _platform(self):
        """`(source de la plateforme, platform_ref)` — la première référence qu'une plateforme
        DÉCLARÉE sait rendre (`external_sources.model_platforms`), ou `(None, '')`."""
        from wama.common.external_sources import model_platforms
        platforms = model_platforms()
        for ref in self.platform_refs():
            prefix, _, ident = ref.partition(':')
            if ident and prefix in platforms:
                return platforms[prefix], ref
        return None, ''

    @property
    def platform_url(self):
        """
        Page publique du modele sur SA plateforme, ou None si on ne sait pas la construire.

        Le template conditionnait le bouton a `hf_id` seul : les 38 modeles Ollama n'avaient
        donc jamais de lien, alors que leur page existe. L'adresse se DÉRIVE de la fiche que la
        plateforme déclare au registre des sources (`external_sources.model_page_url`) — depuis
        le 2026-10-22, plus de table d'adresses ici : ajouter une plateforme se fait là-bas.
        """
        from wama.common.external_sources import model_page_url
        _source, ref = self._platform()
        return model_page_url(ref) if ref else None

    @property
    def is_installable(self):
        """La ROUTE sait-elle installer cette ligne de catalogue ? — `spec_for_catalog_row`, la
        regle meme de `request_install`. La page la LIT au lieu de la recopier (2026-10-10 : le
        bouton « Installer » testait `hf_id` + `install_dir` en JavaScript, si bien qu'une ligne a
        fichiers de version declares n'aurait pas eu de bouton). Un candidat a son propre geste."""
        if self.is_proposed or self.is_downloaded:
            return False
        from .services.model_installer import spec_for_catalog_row
        return spec_for_catalog_row(self) is not None

    @property
    def platform_label(self):
        """Nom de la plateforme, pour libeller le lien sans le deviner cote template — le NOM
        que la source déclare au registre (« HuggingFace Hub », « ollama.com »…). Une plateforme
        que rien ne déclare garde son préfixe brut, comme avant."""
        source, _ref = self._platform()
        if source is not None:
            return source.label
        return (self.platform_ref or '').partition(':')[0]

    @property
    def size_display(self):
        """Human-readable size display."""
        if self.vram_gb:
            return f"{self.vram_gb:.1f}GB VRAM"
        elif self.ram_gb:
            return f"{self.ram_gb:.1f}GB RAM"
        return "Unknown"

    @classmethod
    def best_installed(cls, model_type: str, limit: int = 3, task: str = None):
        """
        Les meilleurs modèles INSTALLÉS d'un type — le référentiel qu'un candidat de
        prospection devrait surpasser. Consommé par la prospection (champ `concurrence`
        des candidats, affiché sur la card) et par la confrontation LLM (`prospect_agents`).

        ⚠ MÊME RÈGLE D'ÉTAGE QUE LA SÉLECTION (`model_selector._rank_key`, audit du
        2026-08-19) : on classe par `benchmark_index` (mesure tierce) SI TOUT le lot en a
        un, sinon par `quality_index` (a priori) pour tout le monde. Mélanger les deux
        comparerait des échelles incommensurables — le piège déjà corrigé le 2026-08-12.

        ⚠⚠ Cette phrase était FAUSSE jusqu'au 2026-09-01 : le test n'exigeait que « tout le
        lot est mesuré » et ne regardait JAMAIS l'échelle, alors que le lot `diffusion` porte
        déjà `aa_elo_text_to_image` ET `arena_elo_text_to_image`. Rien ne s'était vu parce
        qu'un seul modèle non mesuré suffisait à basculer sur le repli — *un défaut masqué par
        une couverture incomplète*. Le test a maintenant UN domicile, `benchmarks_comparable`.
        `task` (2026-09-23) : `model_type` ('diffusion') est plus grossier que le MÉTIER — un
        candidat texte→vidéo affichait « Concurrence : Stable Diffusion XL, FLUX… », et le
        jury le jugeait contre ce référentiel. Donnée, la tâche restreint le lot aux modèles
        qui l'exercent (`capabilities.task` ou `tasks`, vocabulaire canonique). Lot vide =
        aucun concurrent installé pour ce métier : on le dit, on ne retombe pas sur un autre.
        """
        from .services.benchmark_sync import benchmarks_comparable, orderable_value
        lot = list(cls.objects.filter(model_type=model_type, is_downloaded=True,
                                      is_proposed=False))
        wanted = canonical_task((task or '').strip().lower()) if task else None
        if wanted:
            def tasks_of(m):
                caps = m.capabilities or {}
                raw = caps.get('tasks') or ([caps['task']] if caps.get('task') else [])
                return {canonical_task((t or '').strip().lower()) for t in raw}
            lot = [m for m in lot if wanted in tasks_of(m)]
        if benchmarks_comparable(lot):
            # `orderable_value`, pas `benchmark_index` : un taux d'erreur (WER) se trie à
            # l'envers d'un score, et c'est l'échelle qui le dit (`direction`), pas ce code.
            lot.sort(key=orderable_value, reverse=True)
            return lot[:limit]
        # Repli a priori, `None` en dernier (l'ordre de l'ancien `order_by(...nulls_last)`).
        lot.sort(key=lambda m: (m.quality_index is None, -(m.quality_index or 0)))
        return lot[:limit]

    @property
    def origin_label(self) -> str:
        """OÙ ce modèle s'exécute, dit simplement — « WAMA local · Ollama », « Cloud souverain ·
        Albert API (DINUM) · gratuit », « Cloud commercial · API Anthropic (Claude) · facturé à
        l'usage ».

        Demande de Fabien (2026-10-04) : sous le sélecteur de l'assistant, rien ne disait d'où
        venait le modèle choisi. Tout est DÉRIVÉ de ce que la ligne déclare déjà — `execution`,
        la source et son hébergement (`external_sources`), `cost_tier` : aucun libellé recopié
        dans une description. C'est aussi l'intention du 02/10 : DIRE quand une donnée part.
        """
        from wama.common import external_sources
        if self.execution != EXECUTION_CLOUD:
            # Le MÊME mot que l'intitulé de groupe des sélecteurs (`model_origin`).
            local = external_sources.LOCAL_ORIGIN_LABEL
            return f'{local} · Ollama' if self.source == 'ollama' else local
        # Le MÊME calcul que l'intitulé de groupe des sélecteurs (2026-10-10) : une seule phrase
        # pour dire d'où vient un modèle distant et ce qu'il coûte.
        return external_sources.remote_origin_label(self.source, self.cost_tier)

    @property
    def hosting(self) -> str:
        """L'ANNEAU où ce modèle s'exécute, en clé : `local`, ou l'hébergement DÉCLARÉ de sa source
        (`private`, `sovereign`, `third_party`) — '' pour une source distante qui ne le dit pas.
        Le même calcul que `origin_label`, sans la phrase : la barre de filtres du model manager
        le lit (2026-10-16)."""
        from wama.common import external_sources
        if self.execution != EXECUTION_CLOUD:
            return external_sources.LOCAL_ORIGIN_KEY
        return getattr(external_sources.by_key().get(self.source), 'hosting', '') or ''

    def to_dict(self):
        """Convert to dictionary for API responses."""
        from wama.common.external_sources import model_origin
        source = source_identity(self.source)
        return {
            'source_label': source['label'],
            'source_group': source['group'],
            'origin': self.origin_label,
            'hosting': self.hosting,
            # Rang sur l'échelle des hébergements (0 = local) : le tri « le plus proche d'abord ».
            'origin_rank': model_origin(self.model_key, self.execution, self.cost_tier)[2],
            'id': self.model_key,
            'model_key': self.model_key,
            'name': self.name,
            'type': self.model_type,
            'source': self.source,
            'description': self.description,
            'description_short': self.description_short,
            # Le modèle canonique d'une quantification (l'inspecteur le nomme) — le dépôt d'où
            # viennent les poids se lit dans `platform_ref`, juste en dessous.
            'quantized_base': self.quantized_base,
            'quantization': self.quantization,
            'license': self.license,
            'author': self.author,
            'platform_ref': self.platform_ref,
            'platform_url': self.platform_url,
            'platform_label': self.platform_label,
            'installable': self.is_installable,
            'vram_gb': self.vram_gb,
            'ram_gb': self.ram_gb,
            'disk_gb': self.disk_gb,
            'is_downloaded': self.is_downloaded,
            'is_loaded': self.is_loaded,
            'is_available': self.is_available,
            'execution': self.execution,
            'cost_tier': self.cost_tier,
            'local_path': self.local_path,
            'format': self.format,
            'preferred_format': self.preferred_format,
            'can_convert_to': self.can_convert_to,
            'backend_ref': self.backend_ref,
            'extra_info': self.extra_info,
            'capabilities': self.capabilities,
            'is_proposed': self.is_proposed,
            'proposal_kind': self.proposal_kind,
            'confidence': self.confidence,
            'update_complexity': self.update_complexity,
            # Échelle de qualité, exposée depuis le 2026-08-19 (cards + inspecteur + agents) :
            # `quality_index` = a priori STRUCTUREL (étage 1), `benchmark_index` = performance
            # mesurée par un banc TIERS (étage 2). Ni l'un ni l'autre n'est la « confiance »,
            # qui est le verdict d'un agent LLM sur l'opportunité d'adopter un CANDIDAT.
            'quality_index': self.quality_index,
            'benchmark_index': self.benchmark_index,
            'benchmark_meta': self.benchmark_meta,
            'vram_footprint': self.vram_footprint(),
        }

    def vram_footprint(self) -> dict:
        """Les deux pics que ce modèle EXIGE (cascade commune `model_footprint_gb`) : `offload`
        (composants déchargés, le plus gros seul en VRAM) et `full` (tout sur la carte), avec la
        provenance. Lu par le tri et l'inspecteur (2026-09-23) ; `{}` si rien n'est connu."""
        from .services.memory_manager import model_footprint_gb
        offload, provenance = model_footprint_gb(self, offload=True)
        full, _ = model_footprint_gb(self, offload=False)
        if offload is None and full is None:
            return {}
        return {'offload': offload, 'full': full, 'provenance': provenance}


class ModelSyncLog(models.Model):
    """
    Log of model sync operations for debugging and auditing.
    """

    SYNC_TYPE_CHOICES = [
        ('full', 'Full Sync'),
        ('incremental', 'Incremental'),
        ('manual', 'Manual Trigger'),
        ('watchdog', 'File Watcher'),
    ]

    STATUS_CHOICES = [
        ('started', 'Started'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='started')

    models_added = models.IntegerField(default=0)
    models_updated = models.IntegerField(default=0)
    models_removed = models.IntegerField(default=0)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    error_message = models.TextField(blank=True, default='')
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Model Sync Log"
        verbose_name_plural = "Model Sync Logs"
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.sync_type} sync at {self.started_at} - {self.status}"

    @property
    def duration_seconds(self):
        """Calculate sync duration."""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


class ModelRuntimeStat(models.Model):
    """
    Durées de traitement APPRISES par modèle ET par hardware — base du *seeding* de l'ETA
    (cf. common WamaEta). Couplé au registre via `model_key` ("{source}:{model_id}").

    Modèle d'estimation :  ETA ≈ (chargement à froid) + coût fixe + per_unit × taille — le coût
    fixe et le coût par unité tirés des quatre moyennes mobiles ci-dessous (`eta_estimator._line`),
    le rapport `per_unit_ema_seconds` seul tant que les tailles mesurées ne s'écartent pas.
      - `load_ema_seconds`     : temps de chargement à froid (size-indépendant) ; None tant qu'inconnu.
      - `per_unit_ema_seconds` : secondes de traitement par unité de `unit` (ex. s de calcul / s d'audio).
      - `unit`                 : grandeur du domaine (audio_sec|video_sec|megapixel|step|token|
                                 char|page|mb|image|item — `eta_estimator._DEFAULT_PER_UNIT`).
    Sous la clé de CATALOGUE d'un modèle, c'est aussi sa VITESSE D'INFÉRENCE sur ce matériel, que
    le curseur rapide/qualité compare (`eta_estimator.comparable_speeds`, 2026-10-11).

    Bucketisé par **lieu de calcul** (`eta_estimator.compute_place`, rangé dans
    `hardware_fingerprint`) : l'empreinte du matériel de cette machine — un changement de GPU
    repart de l'a-priori et réapprend (les stats de l'ancien matériel ne polluent pas le nouveau) —,
    ou, pour un modèle DISTANT, la clé de sa SOURCE (`albert`, 2026-10-26 : sa vitesse ne dépend
    pas de la carte locale). L'a-priori (1ʳᵉ utilisation) vit dans `AIModel.extra_info['eta']` ;
    ici on stocke ce qui est mesuré, via moyenne mobile (EMA).
    """
    model_key = models.CharField(max_length=255, db_index=True,
                                 help_text='Identifiant registre : {source}:{model_id}')
    hardware_fingerprint = models.CharField(max_length=128, db_index=True,
                                            help_text='ex. "NVIDIA GeForce RTX 4090|24GB" ou "cpu"')
    unit = models.CharField(max_length=32, default='item')

    load_ema_seconds = models.FloatField(null=True, blank=True)
    per_unit_ema_seconds = models.FloatField(default=0.0)
    samples = models.PositiveIntegerField(default=0)
    #: Moyennes mobiles de la taille, de la durée, de la taille² et de taille × durée (2026-10-21,
    #: migration 0026) : la droite « durée = fixe + par unité × taille » qu'`estimate` en tire. Un
    #: rapport moyen (`per_unit_ema_seconds`) appris sur de PETITES tailles prête leur coût fixe à
    #: chaque unité : 11 h annoncées pour une transcription de 141 min qui en a pris 10.
    size_ema = models.FloatField(null=True, blank=True)
    seconds_ema = models.FloatField(null=True, blank=True)
    size_sq_ema = models.FloatField(null=True, blank=True)
    size_seconds_ema = models.FloatField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Model Runtime Stat"
        verbose_name_plural = "Model Runtime Stats"
        unique_together = ('model_key', 'hardware_fingerprint')
        indexes = [
            models.Index(fields=['model_key', 'hardware_fingerprint']),
        ]

    def __str__(self):
        return f"{self.model_key} @ {self.hardware_fingerprint} (n={self.samples})"


class InstallEvent(models.Model):
    """
    Journal DATÉ des installations et désinstallations — modèles et librairies (2026-09-30).

    Pourquoi une table : rien ne DATAIT une installation. La progression vit en cache le temps de
    la tâche (`INSTALL_CACHE_PREFIX`) puis disparaît ; `AIModel` ne garde que la dernière
    désinstallation (`extra_info['uninstalled_at']`) ; `Library.updated_at` bouge à chaque
    projection. Le calendrier (couche « Installations », `WAMA_MEMORY §9bis.1`) ne pouvait donc rien
    montrer — ces événements ne se DÉRIVENT de rien, d'où la seule exception à « le calendrier
    dérive tout ».

    Couche de l'INSTANCE (décision de Fabien, 2026-09-28) : un modèle installé l'est pour tous, la
    ligne ne nomme donc personne. Elle dit par QUELLE voie (`via`) : le bouton du model manager,
    l'assistant, le marcheur d'app, la ligne de commande — les voies de la route unique
    `model_installer.request_install` (PROSPECTION_PIPELINE, alignement du 2026-09-19).
    Écrite par `services/install_history.py`, jamais ailleurs.
    """

    KIND_MODEL = 'model'
    KIND_LIBRARY = 'library'
    KIND_CHOICES = [(KIND_MODEL, 'Modèle'), (KIND_LIBRARY, 'Librairie')]

    ACTION_INSTALL = 'install'
    ACTION_UNINSTALL = 'uninstall'
    ACTION_CHOICES = [(ACTION_INSTALL, 'Installation'), (ACTION_UNINSTALL, 'Désinstallation')]

    #: Mêmes clés que les états du journal commun (`journal.STATUTS`) : la barre de filtrage du
    #: calendrier les lit sans table de traduction.
    STATUS_RUNNING = 'RUNNING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILURE = 'FAILURE'
    STATUS_CHOICES = [(STATUS_RUNNING, 'En cours'), (STATUS_SUCCESS, 'Terminé'),
                      (STATUS_FAILURE, 'Échec')]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES, db_index=True)
    #: Clé DEMANDÉE (candidat `proposed:*`, ligne de catalogue, clé de librairie). Un candidat
    #: installé devient une autre ligne de catalogue ; `name` reste lisible dans les deux cas.
    key = models.CharField(max_length=255, db_index=True)
    name = models.CharField(max_length=255, blank=True, default='')
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, default=ACTION_INSTALL)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING,
                              db_index=True)
    #: `model_manager` | `assistant` | `app_requirements` | `cli` — '' si l'appelant ne le dit pas.
    via = models.CharField(max_length=32, blank=True, default='')
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    #: Ce qui se mesure : Go libérés, version, erreur. Jamais un jugement.
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Installation"
        verbose_name_plural = "Installations"
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.action} {self.kind}:{self.key} → {self.status}"
