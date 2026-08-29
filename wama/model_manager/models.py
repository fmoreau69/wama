"""
WAMA Model Manager - Database Models

PostgreSQL-backed catalog for all AI models.
Provides instant loading instead of dynamic filesystem scanning.
"""

from django.db import models
from django.contrib.auth import get_user_model

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
    SEGMENT = 'segment', 'Segmentation'
    CLASSIFY = 'classify', 'Classification'
    OBB = 'obb', 'Boîtes orientées'
    POSE = 'pose', 'Pose'
    OCR = 'ocr', 'OCR'
    # Declaree en amont du besoin (2026-08-05) : le chantier cam_analyzer/profondeur va faire
    # entrer un modele de ce type au catalogue, et `check_model_taxonomy` refuserait a juste
    # titre une valeur non declaree. Mieux vaut la declarer que voir le garde-fou contourne.
    DEPTH_ESTIMATION = 'depth-estimation', 'Estimation de profondeur'
    # audio / parole
    TRANSCRIPTION = 'transcription', 'Transcription'
    TEXT_TO_SPEECH = 'text-to-speech', 'Synthèse vocale'
    AUDIO_ENHANCE = 'audio-enhance', 'Débruitage audio'
    DENOISE = 'denoise', 'Débruitage'
    # texte / multimodal
    TEXT_GENERATION = 'text-generation', 'Génération de texte'
    FEATURE_EXTRACTION = 'feature-extraction', 'Extraction de traits'
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
TACHE_VERS_TAGS_PLATEFORMES = {
    #                              huggingface                     ultralytics  ollama        roboflow
    ModelTask.DETECT:             ('object-detection',             'detect',    None,        'Object Detection'),
    ModelTask.SEGMENT:            ('image-segmentation',           'segment',   None,        'Instance Segmentation'),
    ModelTask.CLASSIFY:           ('image-classification',         'classify',  None,        'Classification'),
    ModelTask.POSE:               ('keypoint-detection',           'pose',      None,        'Keypoint Detection'),
    ModelTask.OBB:                (None,                           'obb',       None,        None),
    ModelTask.OCR:                ('image-to-text',                None,        None,        'OCR'),
    ModelTask.DEPTH_ESTIMATION:   ('depth-estimation',             None,        None,        'Depth Estimation'),
    ModelTask.TRANSCRIPTION:      ('automatic-speech-recognition', None,        None,        None),
    ModelTask.TEXT_TO_SPEECH:     ('text-to-speech',               None,        None,        None),
    ModelTask.AUDIO_ENHANCE:      ('audio-to-audio',               None,        None,        None),
    ModelTask.DENOISE:            ('image-to-image',               None,        None,        None),
    ModelTask.TEXT_GENERATION:    ('text-generation',              None,        'completion', None),
    ModelTask.FEATURE_EXTRACTION: ('feature-extraction',           None,        'embedding',  None),
    ModelTask.CAPTIONING:         ('image-to-text',                None,        'vision',    'Multimodal'),
    ModelTask.TEXT_TO_IMAGE:      ('text-to-image',                None,        None,        None),
    ModelTask.IMAGE_TO_IMAGE:     ('image-to-image',               None,        None,        None),
    ModelTask.TEXT_TO_VIDEO:      ('text-to-video',                None,        None,        None),
    ModelTask.IMAGE_TO_VIDEO:     ('image-to-video',               None,        None,        None),
    ModelTask.UPSCALE:            ('image-to-image',               None,        None,        None),
    ModelTask.TEXT_TO_MUSIC:      (None,                           None,        None,        None),
    ModelTask.TEXT_TO_AUDIO:      (None,                           None,        None,        None),
    ModelTask.LIP_SYNC:           (None,                           None,        None,        None),
}
PLATEFORMES_DE_REFERENCE = ('huggingface', 'ultralytics', 'ollama', 'roboflow')

# Taches portees par des plateformes et ABSENTES de chez nous. Pas un oubli : rien ne les
# consomme aujourd'hui. Notees pour que la prochaine question << ou est la profondeur ? >> trouve
# une reponse ecrite. `Gaze Detection` (Roboflow) est a surveiller — un labo qui analyse la
# conduite finira par en vouloir.
TACHES_CONNUES_NON_PORTEES = {
    # (`Depth Estimation` en est SORTIE le 2026-08-05 : declaree dans ModelTask en amont du
    #  chantier cam_analyzer/profondeur.)
    # DEJA UTILISE dans WAMA — wama_lab/face_analyzer (eye_tracking.py), mais l'app a ses propres
    # venv_win/venv_linux et ses modeles ne sont PAS au catalogue. A porter (Fabien, 2026-08-05) :
    # c'est un cas ou la tache existe deja en production sans que le registre le sache.
    'Gaze Detection': 'roboflow — et wama_lab/face_analyzer, hors registre',
    'Semantic Segmentation': 'roboflow — cf. remarque ci-dessus sur `segment`',
    'zero-shot-object-detection': 'huggingface — detection en vocabulaire ouvert',
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
    """Sources/applications that use models."""
    WAMA_IMAGER = 'imager', 'WAMA Imager'
    WAMA_DESCRIBER = 'describer', 'WAMA Describer'
    WAMA_ANONYMIZER = 'anonymizer', 'WAMA Anonymizer'
    WAMA_TRANSCRIBER = 'transcriber', 'WAMA Transcriber'
    WAMA_SYNTHESIZER = 'synthesizer', 'WAMA Synthesizer'
    WAMA_ENHANCER = 'enhancer', 'WAMA Enhancer'
    WAMA_AVATARIZER = 'avatarizer', 'WAMA Avatarizer'
    # Alignées sur l'enum de découverte (services/model_registry.py) : la découverte écrit déjà
    # 'composer'/'reader' dans le CharField `source` (4 + 2 modèles en base), mais ils manquaient ici
    # (choices/admin). Converter n'a PAS de modèles IA (ffmpeg/pandoc) → pas de source dédiée.
    WAMA_COMPOSER = 'composer', 'WAMA Composer'
    WAMA_READER = 'reader', 'WAMA Reader'
    OLLAMA = 'ollama', 'Ollama'
    HUGGINGFACE = 'huggingface', 'HuggingFace'
    CUSTOM = 'custom', 'Custom'


class AIModel(models.Model):
    """
    Unified AI Model catalog entry.
    Stores both downloaded and available (not yet downloaded) models.
    """

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
    source = models.CharField(
        max_length=20,
        choices=ModelSource.choices,
        db_index=True
    )

    # Description — deux tiers par usage :
    #   description       = long/canonique (page model_manager, à-propos, tooltip détaillé)
    #   description_short = une ligne pour l'aide sous le sélecteur de modèle (WamaModelHelp)
    description = models.TextField(blank=True, default='')
    description_short = models.CharField(max_length=255, blank=True, default='')

    # External references
    hf_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text="HuggingFace model ID (e.g., 'Wan-AI/Wan2.2-T2V')"
    )

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
            models.Index(fields=['hf_id']),
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
    def platform_url(self):
        """
        Page publique du modele sur SA plateforme, ou None si on ne sait pas la construire.

        Le template conditionnait le bouton a `hf_id` seul : les 38 modeles Ollama n'avaient
        donc jamais de lien, alors que leur page existe. On derive ici au lieu de coder une
        plateforme en dur dans la vue -- ajouter une plateforme se fera a cet endroit unique.
        """
        plateforme, _, identifiant = (self.platform_ref or '').partition(':')
        if plateforme and identifiant:
            gabarit = self._URL_PAR_PLATEFORME.get(plateforme)
            if gabarit:
                return gabarit.format(id=identifiant)

        # Repli tant que `platform_ref` n'est pas renseigne partout (il vient du manifeste).
        if self.hf_id:
            return f"https://huggingface.co/{self.hf_id}"
        if 'ollama:' in (self.model_key or ''):
            from wama.model_manager.services.ollama_registry import BASE_SITE
            # `gemma4:12b` -> page de la famille, le tag n'a pas de page propre.
            famille = (self.name or '').split(':', 1)[0]
            return f"{BASE_SITE}/library/{famille}" if famille else None
        return None

    # Un seul endroit a etendre pour brancher une plateforme de plus (Roboflow…).
    _URL_PAR_PLATEFORME = {
        'huggingface': 'https://huggingface.co/{id}',
        'ollama': 'https://ollama.com/library/{id}',
        'roboflow': 'https://universe.roboflow.com/{id}',
        'github': 'https://github.com/{id}',
    }

    @property
    def platform_label(self):
        """Nom de la plateforme, pour libeller le lien sans le deviner cote template."""
        plateforme = (self.platform_ref or '').partition(':')[0]
        if plateforme:
            return {'huggingface': 'HuggingFace', 'ollama': 'Ollama',
                    'roboflow': 'Roboflow', 'github': 'GitHub'}.get(plateforme, plateforme)
        if self.hf_id:
            return 'HuggingFace'
        if 'ollama:' in (self.model_key or ''):
            return 'Ollama'
        return ''

    @property
    def size_display(self):
        """Human-readable size display."""
        if self.vram_gb:
            return f"{self.vram_gb:.1f}GB VRAM"
        elif self.ram_gb:
            return f"{self.ram_gb:.1f}GB RAM"
        return "Unknown"

    @classmethod
    def best_installed(cls, model_type: str, limit: int = 3):
        """
        Les meilleurs modèles INSTALLÉS d'un type — le référentiel qu'un candidat de
        prospection devrait surpasser. Consommé par la prospection (champ `concurrence`
        des candidats, affiché sur la card) et par la confrontation LLM (`prospect_agents`).

        ⚠ MÊME RÈGLE D'ÉTAGE QUE LA SÉLECTION (`model_selector._rank_key`, audit du
        2026-08-19) : on classe par `benchmark_index` (mesure tierce) SI TOUT le lot en a
        un, sinon par `quality_index` (a priori) pour tout le monde. Mélanger les deux
        comparerait des échelles incommensurables — le piège déjà corrigé le 2026-08-12.
        """
        from django.db.models import F
        lot = list(cls.objects.filter(model_type=model_type, is_downloaded=True,
                                      is_proposed=False))
        if lot and all(m.benchmark_index is not None for m in lot):
            lot.sort(key=lambda m: m.benchmark_index, reverse=True)
            return lot[:limit]
        return list(
            cls.objects.filter(model_type=model_type, is_downloaded=True,
                               is_proposed=False)
            .order_by(F('quality_index').desc(nulls_last=True))[:limit]
        )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            'id': self.model_key,
            'model_key': self.model_key,
            'name': self.name,
            'type': self.model_type,
            'source': self.source,
            'description': self.description,
            'description_short': self.description_short,
            'hf_id': self.hf_id,
            'license': self.license,
            'author': self.author,
            'platform_ref': self.platform_ref,
            'platform_url': self.platform_url,
            'platform_label': self.platform_label,
            'vram_gb': self.vram_gb,
            'ram_gb': self.ram_gb,
            'disk_gb': self.disk_gb,
            'is_downloaded': self.is_downloaded,
            'is_loaded': self.is_loaded,
            'is_available': self.is_available,
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
        }


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

    Modèle d'estimation :  ETA ≈ (chargement à froid) + per_unit × taille
      - `load_ema_seconds`     : temps de chargement à froid (size-indépendant) ; None tant qu'inconnu.
      - `per_unit_ema_seconds` : secondes de traitement par unité de `unit` (ex. s de calcul / s d'audio).
      - `unit`                 : grandeur du domaine (audio_sec|video_sec|megapixel|step|token|item).

    Bucketisé par **empreinte hardware** : un changement de GPU repart de l'a-priori et réapprend
    (les stats de l'ancien matériel ne polluent pas le nouveau). L'a-priori (1ʳᵉ utilisation) vit
    dans `AIModel.extra_info['eta']` ; ici on stocke ce qui est mesuré, via moyenne mobile (EMA).
    """
    model_key = models.CharField(max_length=255, db_index=True,
                                 help_text='Identifiant registre : {source}:{model_id}')
    hardware_fingerprint = models.CharField(max_length=128, db_index=True,
                                            help_text='ex. "NVIDIA GeForce RTX 4090|24GB" ou "cpu"')
    unit = models.CharField(max_length=32, default='item')

    load_ema_seconds = models.FloatField(null=True, blank=True)
    per_unit_ema_seconds = models.FloatField(default=0.0)
    samples = models.PositiveIntegerField(default=0)

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
