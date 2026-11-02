"""« À PROPOS » et « AIDE » de chaque app — ce qui est DÉCLARÉ, et ce qui se DÉRIVE (2026-11-02).

Demande de Fabien, le même jour : *« Les "À propos" et "Aide" de toutes les applications sont à
revérifier et mettre à jour si besoin. Les modèles se mettent bien à jour dans la section Modèles
et publications, mais le corps "À propos", lui, ne porte pas la mise à jour des modèles. Le corps
pourrait aussi se mettre à jour en fonction des déclarations des modèles utilisés dans les
applications. »* Mesuré avant : les dix apps et les deux du Lab réécrivaient ces onglets en HTML
dans leur gabarit (≈ 2000 lignes) et y recopiaient leurs modèles — des modèles retirés y restaient
présentés (imager).

Deux natures, jamais mêlées :
  • DÉCLARÉ (`ABOUT`, ci-dessous) : ce que l'app fait et ses gestes propres, en prose — sans aucun
    nom de modèle, ni mémoire, ni version : ils vieillissent ;
  • DÉRIVÉ (`about_facts`) : les MOTEURS actuels (les modèles des selects de catalogue de l'app,
    `model_publications.app_models` — la lecture de la section « Modèles et publications »), les
    entrées et sorties, les capacités déclarées au catalogue, l'ORIGINE de l'app (WAMA, ou le bac à
    sable et ses développeurs, `sandbox.entry_contributors`).
Une jumelle lit la déclaration de son app source ; une app née d'un manifeste, sa fiche de
catalogue (sa description vient du manifeste).

Rendu : `common/_app_about.html` et `common/_app_help.html`, chargés à l'ouverture de leur onglet
(`common.views.app_about` / `app_help`), comme l'était la seule section des modèles — un gabarit
est relu à chaud par le serveur en service, une balise neuve ne l'est pas. Garde :
`common/tests/tests_app_about.py` — aucun gabarit d'app ne réécrit ces onglets, aucune déclaration
ne cite un modèle du catalogue.
"""
from django.urls import NoReverseMatch, reverse

from wama.common.sandbox import SANDBOX_BADGE

#: Les déclarations, app par app — relues contre le CODE le 2026-11-02 à partir des onglets écrits à
#: la main qu'elles remplacent ; chaque point cite la ligne qui le fonde (`# verified:`). Ce qui
#: n'était plus vrai a été retiré (modèles retirés, réglages disparus, fourchettes périmées).
ABOUT: dict = {
    'anonymizer': {
        'summary': "Anonymizer repère puis floute automatiquement les visages, les plaques "
                   "d'immatriculation ou tout autre objet désigné dans vos photos et vidéos. "
                   "Vous pouvez ainsi diffuser ou conserver des images sans que les personnes "
                   "soient identifiables.",
        'features': [
            {'title': "Deux façons de désigner",
             'text': "Choisissez des classes (visages, plaques, objets courants) ou décrivez "
                     "simplement en texte ce qu'il faut flouter."},
            # verified: wama/anonymizer/params.py:75 (target_mode Classes/Description) ; wama/anonymizer/templates/anonymizer/index.html:440 (classes spéciales visage/plaque) et :461 (objets courants)
            {'title': "Détection et floutage séparés",
             'text': "Changer l'intensité du flou ne relance pas la détection, et changer le "
                     "format de sortie ne refloute pas : seule l'étape concernée est rejouée."},
            # verified: wama/anonymizer/function_specs.py:17 ; wama/anonymizer/function_specs.py:70
            {'title': "Corrections à la main",
             'text': "Sur une image, ajoutez une zone oubliée ou retirez une fausse alerte. "
                     "Vos corrections sont gardées même si la détection est relancée."},
            # verified: wama/anonymizer/surfaces.py:43 ; wama/anonymizer/tasks.py:518 (apply_corrections à chaque floutage) ; wama/anonymizer/templates/anonymizer/_media_card.html:104
            {'title': "Suivi dans les vidéos",
             'text': "Les trous de détection entre deux images sont comblés, et un objet reste "
                     "flouté quelques images avant d'entrer et après être sorti du champ."},
            # verified: wama/anonymizer/params.py:164 (interpolation) ; wama/anonymizer/params.py:180 (prolongation avant/après)
            {'title': "Un flou réglable",
             'text': "Intensité, bords arrondis, flou progressif, et zone floutée agrandie "
                     "ou réduite autour de chaque objet."},
            # verified: wama/anonymizer/params.py:139 (blur_ratio) ; :145 (rounded_edges) ; :151 (roi_enlargement 0,75–1,25) ; :159 (progressive_blur)
            {'title': "Le format d'origine conservé",
             'text': "Par défaut, le média flouté garde le format du fichier déposé, et une "
                     "vidéo garde sa bande son."},
            # verified: wama/anonymizer/params.py:210 ; wama/anonymizer/models.py:168 (output_format='original') ; wama/common/utils/detections.py:568 (audio de la source recopié)
            {'title': "Aperçu en cours de route",
             'text': "Pendant le traitement d'une vidéo, l'aperçu montre l'image courante, avec "
                     "ses détections ou déjà floutée."},
            # verified: wama/anonymizer/tasks.py:537 (publish detection + blur) ; wama/anonymizer/tasks.py:503
        ],
        'help': [
            {'title': "Choisir les classes",
             'text': "Dans le volet, « Sélectionner les classes » ouvre la liste : visages et "
                     "plaques en tête, puis les objets courants."},
            # verified: wama/anonymizer/templates/anonymizer/index.html:35 ; wama/anonymizer/templates/anonymizer/index.html:440
            {'title': "Décrire ce qu'il faut flouter",
             'text': "En mode Description, écrivez votre consigne dans le volet ; le bouton "
                     "« Exemples de descriptions » vous donne des modèles de formulation."},
            # verified: wama/anonymizer/templates/anonymizer/index.html:47 ; wama/anonymizer/templates/anonymizer/index.html:61 ; wama/anonymizer/views.py:920
            {'title': "Rapide ou précis",
             'text': "Le curseur Rapide ↔ Qualité compte cinq paliers ; à partir du milieu, le "
                     "flou épouse le contour de l'objet plutôt qu'un rectangle."},
            # verified: wama/anonymizer/params.py:122 (intent_param step=5) ; wama/anonymizer/params.py:124 (« à partir de 50, segmentation fine »)
            {'title': "Trop de fausses alertes ?",
             'text': "Relevez le seuil de détection : seuls les objets détectés avec plus de "
                     "confiance seront floutés."},
            # verified: wama/anonymizer/params.py:127 (detection_threshold 0–1)
            {'title': "Corriger une détection",
             'text': "Le bouton ✎ de la card s'active sur une image dont la détection est faite. "
                     "Les vidéos ne se corrigent pas encore à la main."},
            # verified: wama/anonymizer/surfaces.py:35 (_review_available : image seulement, détection requise)
        ],
        'links': [],
    },

    'avatarizer': {
        'summary': "L'Avatarizer fait parler un avatar : à partir d'une voix (un fichier audio, "
                   "ou un texte qu'il transforme en parole) et d'un portrait ou d'un avatar 3D, "
                   "il produit une vidéo dont les lèvres suivent la parole.",
        'features': [
            {'title': "Un audio ou un texte",
             'text': "Fournissez la voix de l'avatar, ou seulement le texte à dire : la voix est "
                     "alors synthétisée. Si vous donnez les deux, l'audio prime."},
            # verified: wama/avatarizer/views.py:192 ; wama/avatarizer/views.py:203 (mode dérivé : audio/URL → standalone, sinon pipeline)
            {'title': "Une voix réglable",
             'text': "Pour un texte, choisissez le moteur de voix, la langue et la voix ; ces "
                     "choix sont retenus pour la vidéo suivante."},
            # verified: wama/avatarizer/params.py:75 (tts_model) ; :101 (language) ; :106 (voice_preset) ; :175 (VOICE_SETTINGS retenus)
            {'title': "Photo ou avatar 3D",
             'text': "L'avatar peut être un portrait (JPG, PNG, WebP) ou un avatar 3D riggé au "
                     "format .glb, importé ou pris dans la médiathèque."},
            # verified: wama/avatarizer/models.py:23 (AVATAR_FILE_EXTENSIONS) ; wama/avatarizer/function_specs.py:64 (ports work_image / work_object3d)
            {'title': "Animation choisie d'après l'avatar",
             'text': "En « Auto », le modèle d'animation se déduit de l'avatar fourni : une photo "
                     "et un avatar 3D ne s'animent pas de la même façon."},
            # verified: wama/avatarizer/params.py:45 (animation_model, options_auto) ; wama/avatarizer/params.py:48 (help_fallback auto)
            {'title': "Amélioration du visage",
             'text': "Pour une photo animée, une restauration faciale facultative rend le visage "
                     "plus net, au prix d'un rendu un peu plus long."},
            # verified: wama/avatarizer/params.py:128 (use_enhancer, sans effet sur un avatar 3D)
            {'title': "Relancer sans tout refaire",
             'text': "Voix, animation, puis visage et sortie sont des étapes distinctes : changer "
                     "l'avatar ne régénère pas la voix, et retirer l'amélioration ne réanime pas."},
            # verified: wama/avatarizer/function_specs.py:20 ; wama/avatarizer/function_specs.py:85
        ],
        'help': [
            {'title': "Reprendre un texte existant",
             'text': "Glissez un fichier texte (TXT, MD, PDF, DOCX, CSV) sur la zone de texte : "
                     "son contenu devient le texte à dire."},
            # verified: wama/avatarizer/views.py:396 (ALLOWED_EXTS) ; wama/avatarizer/static/avatarizer/js/index.js:158 ; wama/avatarizer/templates/avatarizer/index.html:88 (prompt_hint)
            {'title': "Choisir un avatar",
             'text': "L'onglet Image de la card accepte une photo ; la médiathèque s'y ouvre sur "
                     "ses avatars. L'onglet Objet 3D reçoit un avatar .glb."},
            # verified: wama/avatarizer/templates/avatarizer/index.html:81 (onglet par port, médiathèque sur l'onglet Avatar) ; wama/avatarizer/static/avatarizer/js/index.js:200
            {'title': "Avatar 3D et audio seul",
             'text': "Sans texte, l'audio est d'abord transcrit pour caler les lèvres sur les "
                     "mots. Si aucune parole n'y est reconnue, fournissez le texte dit."},
            # verified: wama/avatarizer/workers.py:359 ; wama/avatarizer/workers.py:370
            {'title': "Bouche mal placée ?",
             'text': "Sur une photo animée, ajustez le décalage vertical de la zone de la bouche "
                     "(de −10 à +10, 0 = automatique)."},
            # verified: wama/avatarizer/params.py:134 (bbox_shift min=-10 max=10)
            {'title': "Suivre le rendu",
             'text': "Pour un avatar 3D, l'aperçu montre la dernière image rendue pendant le "
                     "calcul ; pour une photo, la vidéo n'apparaît qu'à la fin."},
            # verified: wama/avatarizer/workers.py:376
            {'title': "Un avatar 3D d'un seul fichier",
             'text': "Seul le format .glb est accepté : un .gltf à fichiers séparés ne peut pas "
                     "se charger."},
            # verified: wama/common/app_registry.py:1369 ; wama/avatarizer/models.py:23
        ],
        'links': [],
    },

    'composer': {
        'summary': "Composer génère de la musique, des chansons et des bruitages à partir d'une "
                   "description en texte. Il sait aussi reprendre un morceau existant et, selon "
                   "le modèle, écrire puis vous laisser corriger sa partition.",
        'features': [
            {'title': "Musique ou ambiances",
             'text': "Les modèles sont groupés par usage — musique d'un côté, ambiances et "
                     "bruitages de l'autre —, chacun avec son choix automatique."},
            # verified: wama/composer/params.py:36 (options_group="task", options_auto="group") ; wama/composer/utils/model_choice.py:21
            {'title': "Instrumental ou chanté",
             'text': "Le réglage Voix choisit entre instrumental et chanson ; en « Auto », le "
                     "morceau est chanté si votre texte porte des paroles."},
            # verified: wama/composer/params.py:55 ; wama/composer/utils/vocals.py:9
            {'title': "Des paroles écrites pour vous",
             'text': "Demandez une chanson sans paroles : elles sont écrites dans une langue que "
                     "le modèle chante, puis gardées sur la card pour être corrigées."},
            # verified: wama/composer/utils/vocals.py:124 ; wama/composer/params.py:65 (lyrics)
            {'title': "Reprise d'un morceau",
             'text': "Donnez l'audio d'un morceau à reprendre : selon le modèle, sa mélodie est "
                     "rejouée dans le style demandé, ou suivie par sa partition."},
            # verified: wama/composer/function_specs.py:157 (work_audio du rendu) ; wama/composer/function_specs.py:14 (extract_score pour un cover)
            {'title': "Partitions lisibles et corrigeables",
             'text': "Pour les modèles qui passent par une partition, la page « Éditer la "
                     "partition » la montre, la joue en synchronisation et permet de la corriger."},
            # verified: wama/composer/surfaces.py:52 ; wama/composer/surfaces.py:3
            {'title': "Partitions par instrument",
             'text': "En option, une partition complète, une partie par instrument, pour le "
                     "morceau repris comme pour le morceau produit, afin de les comparer."},
            # verified: wama/composer/params.py:113 (extract_parts) ; wama/composer/params.py:125 (extract_rendered_parts)
            {'title': "Une consigne dans votre langue",
             'text': "Écrivez en français : la description est traduite si le modèle l'exige, et "
                     "peut être enrichie avant la génération."},
            # verified: wama/common/utils/app_metadata.py:84 (PROMPT_TARGETS composer, enrich=True) ; wama/composer/utils/vocals.py:97
        ],
        'help': [
            {'title': "Faire chanter vos paroles",
             'text': "Placez-les sous la description, en sections balisées ([Verse], [Chorus]…). "
                     "Des paroles écrites dans le texte priment sur celles de la card."},
            # verified: wama/composer/params.py:57 ; wama/composer/params.py:66
            {'title': "Retoucher des paroles écrites",
             'text': "Les paroles écrites pour vous se trouvent dans ⚙ → Paroles : modifiez-les, "
                     "puis relancez."},
            # verified: wama/composer/utils/vocals.py:130 ; wama/composer/params.py:65
            {'title': "Reprendre depuis une adresse",
             'text': "L'audio à reprendre peut venir d'une URL : il est téléchargé au lancement. "
                     "Sa durée est proposée comme durée du morceau."},
            # verified: wama/composer/models.py:81 (WAMA_INGEST source_url → melody_reference) ; wama/composer/params.py:86 (default_from work_audio duration)
            {'title': "Ouvrir la partition",
             'text': "Le bouton ✎ de la card ouvre la page de la partition. Il reste grisé pour un "
                     "modèle qui compose sans partition."},
            # verified: wama/composer/templates/composer/_generation_card.html:110 ; wama/composer/surfaces.py:46
            {'title': "Une durée à la mesure du modèle",
             'text': "Le curseur de durée s'arrête à ce que le modèle choisi sait produire : "
                     "certains ne dépassent pas quelques dizaines de secondes."},
            # verified: wama/composer/params.py:94 (cap_from max_duration_s) ; wama/composer/params.py:90
            {'title': "Relancer sans tout refaire",
             'text': "Changer la durée ou le format ne réécrit pas la partition, et une partition "
                     "corrigée se rejoue sans être recalculée."},
            # verified: wama/composer/function_specs.py:22 ; wama/composer/params.py:95 (duration stales=("render",))
        ],
        'links': [],
    },

    'converter': {
        'summary': "Converter change le format de vos images, vidéos, sons, documents et "
                   "archives, avec des réglages d'encodage simples à prendre en main.",
        'features': [
            {'title': "Cinq familles de fichiers",
             'text': "Images, vidéos, audio, documents (livres numériques compris) et archives, "
                     "chacune avec ses formats d'entrée et de sortie."},
            # verified: wama/converter/utils/format_router.py:17 (SUPPORTED_CONVERSIONS)
            {'title': "Un format proposé d'office",
             'text': "Le format de sortie se choisit selon la nature du fichier, et le dernier "
                     "que vous avez retenu pour cette nature est repris."},
            # verified: wama/converter/utils/format_router.py:165 (output_format_for) ; wama/converter/utils/format_router.py:143
            {'title': "Rapide ou qualité",
             'text': "Un curseur pose les réglages d'encodage, du plus léger au plus soigné ; "
                     "ils restent ensuite retouchables un par un."},
            # verified: wama/converter/params.py:84 (quality_intent) ; wama/converter/params.py:104 (quality, advanced)
            {'title': "Transformations",
             'text': "Redimensionner une image en gardant ses proportions, tourner ou retourner "
                     "une image ou une vidéo, changer la cadence d'une vidéo."},
            # verified: wama/converter/params.py:112 (resize_w/h) ; :123 (rotation) ; :126 (flip_h/v) ; :135 (fps)
            {'title': "Réglages du son",
             'text': "Débit, fréquence d'échantillonnage, mono ou stéréo, et normalisation du "
                     "volume."},
            # verified: wama/converter/params.py:148 ; :152 ; :156 ; :159
            {'title': "Du son ou un GIF depuis une vidéo",
             'text': "Extrayez la bande son d'une vidéo (MP3, WAV, OGG) ou transformez-la en GIF "
                     "animé, cadence et largeur réglables."},
            # verified: wama/converter/utils/format_router.py:27 (sortie vidéo : gif, mp3, wav, ogg) ; wama/converter/params.py:140 (gif_fps, gif_width)
            {'title': "Post-traitement IA en option",
             'text': "Après la conversion, agrandissez ou débruitez une image, ou améliorez le son "
                     "d'un audio ou d'une vidéo."},
            # verified: wama/converter/utils/format_router.py:66 (CROSS_APP_OPTIONS) ; wama/converter/params.py:179
        ],
        'help': [
            {'title': "Plusieurs fichiers à la fois",
             'text': "Déposez des fichiers de natures différentes : ils sont rangés en un lot par "
                     "nature, que vous réglez d'un seul geste."},
            # verified: wama/converter/views.py:63 (group_into_batches_by_nature) ; wama/converter/params.py:66
            {'title': "Profils",
             'text': "Enregistrez une combinaison format et réglages sous un nom, pour la "
                     "réappliquer à vos prochaines conversions."},
            # verified: wama/converter/views.py:651 (profile_save) ; wama/converter/static/converter/js/converter.js:8
            {'title': "Conversion rapide",
             'text': "Depuis le Gestionnaire de fichiers, « Conversion rapide » écrit le résultat "
                     "à côté du fichier source, sans passer par la file."},
            # verified: wama/converter/views.py:745 ; wama/filemanager/static/filemanager/js/filemanager.js:670
            {'title': "PDF vers DOCX",
             'text': "La mise en page, les images et les tableaux sont reconstruits, mais aucun "
                     "texte n'est reconnu sur un scan : pour cela, passez par le Reader."},
            # verified: wama/converter/backends/document_backend.py:135 (pdf2docx, sans OCR : document_backend.py:109)
            {'title': "Page web vers PDF",
             'text': "Une page HTML mise en forme devient un PDF fidèle, styles et dessins "
                     "vectoriels compris."},
            # verified: wama/converter/backends/document_backend.py:145 ; wama/converter/backends/document_backend.py:152
            {'title': "Changer d'avis sur le post-traitement",
             'text': "Passer de ×2 à ×4, par exemple, ne refait pas la conversion : seul le "
                     "post-traitement est rejoué."},
            # verified: wama/converter/params.py:212 ; wama/converter/params.py:226
        ],
        'links': [],
    },

    'describer': {
        'summary': "Describer décrit et résume automatiquement vos contenus : images, vidéos, "
                   "enregistrements audio et documents. Chaque fichier passe par une chaîne "
                   "d'étapes adaptée à sa nature.",
        'features': [
            {'title': "Images",
             'text': "Un modèle de vision rédige la description de l'image, au style et dans "
                     "la langue choisis."},  # verified: wama/describer/function_specs.py:121
            {'title': "Audio et vidéo",
             'text': "La parole est d'abord transcrite ; pour une vidéo, des images-clés sont "
                     "aussi légendées. La description s'appuie sur les deux."},  # verified: wama/describer/function_specs.py:12
            {'title': "Documents et pages web",
             'text': "Textes, PDF, DOCX, Markdown, CSV et pages HTML sont lus puis décrits."},  # verified: wama/common/app_registry.py:1542
            {'title': "Résumé en option",
             'text': "Un résumé structuré de la description, ou un compte-rendu de réunion "
                     "rédigé à partir de toute la parole."},  # verified: wama/describer/function_specs.py:19
            {'title': "Vérification de cohérence",
             'text': "En option : une note de cohérence, les anomalies relevées et une "
                     "version corrigée proposée."},  # verified: wama/describer/function_specs.py:150
            {'title': "Un modèle par rôle",
             'text': "Transcription, vision et langage ont chacun leur modèle, choisi "
                     "automatiquement ou désigné par vous."},  # verified: wama/describer/params.py:14
            {'title': "Export",
             'text': "Le résultat se télécharge en TXT, PDF ou DOCX, au choix."},  # verified: wama/common/app_registry.py:1557
        ],
        'help': [
            {'title': "Choisir le format de sortie",
             'text': "Résumé court pour un aperçu rapide, description détaillée, synthèse "
                     "scientifique pour un article, ou points clés en liste."},  # verified: wama/describer/models.py:46
            {'title': "Compte-rendu de réunion",
             'text': "Activez « Générer un résumé LLM » puis choisissez « Réunion » : le "
                     "compte-rendu est rédigé depuis toute la parole de l'enregistrement."},  # verified: wama/describer/params.py:181
            {'title': "Langue et longueur",
             'text': "La description sort en français, en anglais ou dans la langue de la "
                     "source. La longueur maximale se règle en caractères."},  # verified: wama/describer/models.py:60
            {'title': "Seul ce qui change est refait",
             'text': "Changer le style ou le modèle de langage ne réécoute pas l'audio et ne "
                     "relégende pas la vidéo. Un résumé ou une vérification en échec se "
                     "relance seul."},  # verified: wama/describer/function_specs.py:27
            {'title': "Vidéos longues",
             'text': "Une image-clé est prise toutes les 10 secondes, 18 au plus : au-delà de "
                     "trois minutes, l'intervalle s'allonge."},  # verified: wama/describer/backends/video_backend.py:43
        ],
        'links': [],
    },

    'enhancer': {
        'summary': "Enhancer améliore la qualité de vos médias : agrandissement et débruitage "
                   "des images et des vidéos, débruitage et restauration de la voix dans "
                   "l'audio.",
        'features': [
            {'title': "Deux domaines",
             'text': "Un onglet Image / Vidéo et un onglet Audio, chacun avec sa file et ses "
                     "réglages."},  # verified: wama/common/utils/app_modes.py:267
            {'title': "Agrandissement ×2 ou ×4",
             'text': "En automatique, le modèle est choisi au lancement parmi ceux qui "
                     "donnent le facteur demandé."},  # verified: wama/enhancer/params.py:113
            {'title': "Débruitage et mélange",
             'text': "Un débruitage peut précéder l'agrandissement, et le résultat peut être "
                     "mélangé à l'original pour un rendu plus naturel."},  # verified: wama/common/backends/ai_upscaler.py:481
            {'title': "Résolution d'origine",
             'text': "Gardez les dimensions de départ : la qualité gagnée, sans le poids d'un "
                     "fichier agrandi."},  # verified: wama/enhancer/models.py:52
            {'title': "Restauration audio",
             'text': "Débruitage seul, amélioration seule ou les deux, avec une force et une "
                     "qualité réglables."},  # verified: wama/enhancer/params.py:171
            {'title': "Aperçu en cours de traitement",
             'text': "Pendant une vidéo, l'image améliorée courante s'affiche sur la card."},  # verified: wama/enhancer/tasks.py:185
        ],
        'help': [
            {'title': "GIF animés",
             'text': "Un GIF est traité comme une vidéo : toutes ses images sont agrandies, "
                     "pas seulement la première."},  # verified: wama/common/utils/app_modes.py:272
            {'title': "Curseur Blend",
             'text': "À 0, le résultat est 100 % IA ; à 1, c'est l'original. Une valeur "
                     "intermédiaire adoucit un rendu trop lisse."},  # verified: wama/enhancer/params.py:131
            {'title': "Réglages audio grisés",
             'text': "Mode, force et qualité ne s'appliquent qu'aux moteurs qui les lisent : "
                     "ils sont grisés sinon, et cachés en automatique."},  # verified: wama/enhancer/params.py:165
            {'title': "Changer le format sans tout refaire",
             'text': "Le format et la qualité de sortie sont une étape à part : les modifier "
                     "ne relance pas l'amélioration."},  # verified: wama/enhancer/function_specs.py:14
        ],
        'links': [],
    },

    'imager': {
        'summary': "Imager génère des images et des vidéos à partir d'une description "
                   "textuelle, d'une image de référence, ou des deux.",
        'features': [
            {'title': "Images",
             'text': "Depuis un texte, depuis une image à transformer, ou depuis une image "
                     "seule dont la description devient la consigne."},  # verified: wama/imager/static/imager/js/input_card.js:156
            {'title': "Vidéos",
             'text': "Depuis un texte, ou en animant une image de départ."},  # verified: wama/imager/static/imager/js/input_card.js:160
            {'title': "Pas de mode à choisir",
             'text': "Le type de génération se déduit de ce que vous fournissez ; un modèle "
                     "qui ne convient pas à vos entrées est grisé, avec la raison."},  # verified: wama/imager/static/imager/js/input_card.js:4
            {'title': "Consigne traduite et enrichie",
             'text': "Écrivez dans votre langue : la consigne est traduite si le modèle le "
                     "demande, et ✨ l'enrichit. Des mots-clés vous sont proposés."},  # verified: wama/common/utils/prompt_pipeline.py:9
            {'title': "Logos",
             'text': "Des modèles spécialisés dans les logos, regroupés à part dans la liste."},  # verified: wama/imager/params.py:71
            {'title': "Aperçu pendant la génération",
             'text': "Une image approchée s'affiche au fil des étapes, environ toutes les "
                     "deux secondes."},  # verified: wama/imager/tasks.py:388
            {'title': "Réglages guidés par le modèle",
             'text': "Étapes et guidage recommandés, résolution et cadence natives : la fiche "
                     "du modèle choisi les indique."},  # verified: wama/imager/params.py:109
        ],
        'help': [
            {'title': "Une image sans texte",
             'text': "Déposez une image sans consigne : sa description sert de consigne. "
                     "Avec une image désignée par lien, elle est transformée telle quelle."},  # verified: wama/imager/static/imager/js/input_card.js:161
            {'title': "Fichiers de consignes",
             'text': "En plus du TXT et du CSV, un lot de consignes peut venir d'un fichier "
                     "JSON ou YAML, en image comme en vidéo."},  # verified: wama/imager/views.py:438
            {'title': "Plusieurs images, plus grandes",
             'text': "Générez jusqu'à 4 images en une passe, et agrandissez-les à la sortie."},  # verified: wama/imager/params.py:95
            {'title': "Force de la référence",
             'text': "Dans les réglages avancés : à 0 l'image de référence est ignorée, à 1 "
                     "elle est presque copiée."},  # verified: wama/imager/params.py:130
            {'title': "Durée d'une vidéo",
             'text': "De 1 à 15 secondes. La zone native du modèle est signalée ; au-delà, "
                     "la vidéo est prolongée."},  # verified: wama/imager/params.py:183
            {'title': "Changer le format sans tout refaire",
             'text': "Le format de sortie est une étape à part : le modifier ne relance pas "
                     "la génération."},  # verified: wama/imager/params.py:236
        ],
        'links': [],
    },

    'reader': {
        'summary': (
            "Reader extrait le texte de vos documents numérisés, photos et PDF. "
            "Il peut ensuite le remettre en forme et en tirer un résumé."
        ),
        'features': [
            {'title': "Documents et images",
             'text': "PDF de plusieurs pages, JPG, PNG, TIFF, WebP et BMP."},
            # verified: wama/common/app_registry.py:39
            {'title': "PDF numériques lus directement",
             'text': "Le texte d'un PDF numérique est repris tel quel, sans reconnaissance de caractères. "
                     "Une seule page scannée suffit pour que tout le document passe par la lecture optique."},
            # verified: wama/reader/tasks.py:233
            {'title': "Mode de lecture",
             'text': "Auto, imprimé ou manuscrit. Grisé, avec sa raison, quand le moteur choisi n'en tient pas compte."},
            # verified: wama/reader/params.py:76
            {'title': "Photos redressées",
             'text': "Une image prise de travers est remise droite avant la lecture ; l'original reste intact."},
            # verified: wama/reader/tasks.py:279
            {'title': "Mise en forme par IA",
             'text': "Une étape cochée par défaut : un modèle de langage restructure le texte lu "
                     "(titres, listes, tableaux) sans rien en retrancher."},
            # verified: wama/reader/params.py:134
            {'title': "Analyse",
             'text': "En option : résumé, points clés et actions tirés du texte."},
            # verified: wama/reader/tasks.py:373
            {'title': "Lecture en direct",
             'text': "Le texte se construit page après page pendant la lecture."},
            # verified: wama/reader/tasks.py:262
        ],
        'help': [
            {'title': "Langue",
             'text': "Optionnelle (ex. fr, en) : laissée vide, elle est détectée. "
                     "Elle sert aussi d'indice à la mise en forme."},
            # verified: wama/reader/params.py:83
            {'title': "Rejouer sans relire",
             'text': "Changer de modèle de langage ne relit pas le document : seules la mise en forme "
                     "et l'analyse sont rejouées."},
            # verified: wama/reader/params.py:107
            {'title': "Le format se choisit au téléchargement",
             'text': "TXT donne un texte brut, sans mise en forme ; MD la garde ; PDF et DOCX sont mis en page ; "
                     "JSON rend la sortie brute du moteur."},
            # verified: wama/reader/views.py:623
            {'title': "Lecture coupée",
             'text': "Si le moteur se met à boucler sur une page, la lecture y est coupée et la card le signale : "
                     "vérifiez alors cette page."},
            # verified: wama/reader/tasks.py:291
        ],
        'links': [],
    },

    'synthesizer': {
        'summary': (
            "Synthesizer fait dire un texte par une voix de synthèse : texte saisi ou fichier, "
            "voix du moteur ou voix clonée à partir d'un échantillon. Le texte est dit tel quel, jamais traduit."
        ),
        'features': [
            {'title': "Texte saisi ou fichier",
             'text': "Saisissez le texte, ou déposez un fichier TXT, MD, PDF, DOCX ou CSV : il est lu en entier."},
            # verified: wama/synthesizer/services.py:28
            {'title': "Voix au choix",
             'text': "Voix propres du moteur, voix de référence ou voix clonées. "
                     "Vos voix s'ajoutent et s'écoutent dans la médiathèque."},
            # verified: wama/synthesizer/params.py:74
            {'title': "Clonage de voix",
             'text': "Un court échantillon audio (6 à 10 secondes recommandées) suffit à cloner une voix."},
            # verified: wama/synthesizer/models.py:63
            {'title': "Diction réglable",
             'text': "Vitesse, hauteur, pause en fin de phrase et pause sur virgule, parenthèse ou tiret."},
            # verified: wama/synthesizer/params.py:91
            {'title': "Aperçu de la voix",
             'text': "Écoutez les premiers mots avec vos réglages, rendus exactement comme la synthèse finale."},
            # verified: wama/synthesizer/views.py:757
            {'title': "Écoute pendant la synthèse",
             'text': "Sur un texte long, l'audio s'écoute au fur et à mesure, segment après segment."},
            # verified: wama/synthesizer/workers.py:74
            {'title': "Dialogue à plusieurs voix",
             'text': "Avec le moteur qui le propose : balises [S1], [S2]… dans le texte et description de la scène."},
            # verified: wama/synthesizer/templates/synthesizer/index.html:35
        ],
        'help': [
            {'title': "Jamais traduit",
             'text': "Le texte est prononcé tel que vous l'avez écrit : rédigez-le dans la langue de la voix."},
            # verified: wama/common/utils/app_metadata.py:97
            {'title': "Texte préparé pour être lu",
             'text': "Pictogrammes et syntaxe Markdown sont retirés ; liens et adresses sont remplacés par un mot."},
            # verified: wama/common/utils/tts_text.py:413
            {'title': "Voix et langues selon le moteur",
             'text': "Seules les voix et les langues que le moteur choisi sait dire sont proposées. "
                     "Une voix clonée grise les moteurs qui ne clonent pas."},
            # verified: wama/synthesizer/templates/synthesizer/index.html:305
            {'title': "Format du fichier audio",
             'text': "Choisissez le format et la qualité de sortie dans le volet : la conversion se fait en fin de synthèse."},
            # verified: wama/synthesizer/params.py:140
            {'title': "Fichier de lot",
             'text': "Une ligne par texte à dire : nom de sortie, texte, voix, vitesse. "
                     "Voix et vitesse sont facultatives (celles du volet)."},
            # verified: wama/synthesizer/views.py:466
        ],
        'links': [],
    },

    'transcriber': {
        'summary': (
            "Transcriber transforme la parole d'un audio ou d'une vidéo en texte horodaté, locuteurs compris. "
            "Une page de correction permet ensuite de relire et de corriger la transcription à l'écoute."
        ),
        'features': [
            {'title': "Audio, vidéo ou micro",
             'text': "Un fichier audio ou vidéo (la bande son en est extraite), ou un enregistrement en direct "
                     "au micro (« Speak ») qui devient une card comme les autres."},
            # verified: wama/transcriber/views.py:565
            {'title': "Préparation de l'audio",
             'text': "Nivellement des voix, débruitage pour les fonds très bruyants ; "
                     "vous choisissez de transcrire l'original ou l'audio préparé."},
            # verified: wama/transcriber/params.py:121
            {'title': "Locuteurs",
             'text': "Identification de qui parle et quand."},
            # verified: wama/transcriber/params.py:164
            {'title': "Résumé et cohérence",
             'text': "Résumé structuré ou compte-rendu de réunion ; contrôle de cohérence avec un score "
                     "et une correction proposée côte à côte."},
            # verified: wama/transcriber/params.py:174
            {'title': "Page de correction",
             'text': "Segments synchronisés à l'audio, onde avec bande de qualité, aller à un instant, "
                     "vitesse de lecture, coupe et fusion au clavier, enregistrement automatique."},
            # verified: wama/transcriber/surfaces.py:78
            {'title': "Transcrire au fil de la lecture",
             'text': "Sur la page de correction, un passage écouté peut être retranscrit "
                     "et remplacer ce qui s'y disait."},
            # verified: wama/transcriber/workers.py:1234
            {'title': "Comparer à une référence",
             'text': "Mesurez une transcription contre une référence (taux d'erreur sur les mots, "
                     "et sur les locuteurs si elle les nomme), ou reprenez une transcription faite ailleurs."},
            # verified: wama/transcriber/apps.py:145
        ],
        'help': [
            {'title': "Mots-clés contextuels",
             'text': "Noms propres, sigles, termes techniques, séparés par des virgules. "
                     "Grisés quand le modèle choisi n'en tient pas compte."},
            # verified: wama/transcriber/params.py:105
            {'title': "Débruitage avec prudence",
             'text': "Il dégrade la transcription d'un enregistrement propre ou lointain : "
                     "réservez-le aux fonds très bruyants. Le nivellement seul aide souvent davantage."},
            # verified: wama/transcriber/params.py:127
            {'title': "Langues et silences",
             'text': "« Langues parlées » : une seule, plusieurs, ou Auto qui écoute d'abord l'audio. "
                     "Le filtre de parole désactivé garde tout, au risque de texte inventé dans les longs silences."},
            # verified: wama/transcriber/params.py:151
            {'title': "Ouvrir la correction",
             'text': "Le ✎ de la card ouvre la correction, après une transcription réussie. "
                     "« Terminer la correction » met à jour le texte et les sous-titres téléchargés."},
            # verified: wama/transcriber/views.py:748
            {'title': "Intervenants et document",
             'text': "Sur la page de correction, renommez les intervenants (l'IA peut proposer des noms, "
                     "à valider) et donnez un titre et une date : ils apparaissent dans le document de sortie."},
            # verified: wama/transcriber/params.py:187
            {'title': "Référence et transcription existante",
             'text': "Elles se joignent à une card existante par son menu « … ». "
                     "Téléchargements : TXT, SRT (sous-titres avec locuteurs), PDF, DOCX."},
            # verified: wama/common/app_registry.py:1823
        ],
        'links': [],
    },

    'cam_analyzer': {
        'summary': (
            "Outil de recherche qui analyse les vidéos des caméras embarquées sur une navette autonome "
            "pour étudier sa cohabitation avec les autres usagers de la route : suivi des objets sur les "
            "quatre caméras, reconstitution de la scène vue de dessus, puis rapports d'interactions "
            "(proximité, dépassements, insertions aux intersections)."
        ),  # verified: wama_lab/cam_analyzer/README.md:3-6, wama_lab/cam_analyzer/models.py:71-74
        'features': [
            {'title': "Sessions multi-caméras synchronisées",
             'text': "Une session réunit jusqu'à quatre vues (avant, arrière, gauche, droite), lues ensemble "
                     "image par image, avec un décalage de synchronisation propre à chaque caméra."},
            # verified: wama_lab/cam_analyzer/models.py:334-338, wama_lab/cam_analyzer/templates/cam_analyzer/index.html:233-274
            {'title': "Enregistrements de la navette",
             'text': "Outre des vidéos par caméra, l'app importe une vidéo quadrature exportée d'un "
                     "enregistrement de la navette, ou l'enregistrement binaire lui-même, avec un CSV GPS "
                     "facultatif : les quatre vues sont découpées automatiquement et la trace GPS rattachée "
                     "à la session."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/index.html:154-198, wama_lab/cam_analyzer/views.py:1645-1699, wama_lab/cam_analyzer/tasks.py:3757-3780
            {'title': "Chaîne de traitement par passes",
             'text': "L'analyse se découpe en passes (perception, puis calculs rejouables sans GPU). Changer un "
                     "réglage ne périme que les passes qui en dépendent : « Compléter les passes » ne relance "
                     "que celles-là, et le mode Live analyse au fil de la lecture les tranches jamais vues."},
            # verified: wama_lab/cam_analyzer/utils/pass_tracking.py:82-161, wama_lab/cam_analyzer/static/cam_analyzer/js/index.js:1401-1404, wama_lab/cam_analyzer/templates/cam_analyzer/base.html:179-182
            {'title': "Vue de dessus à 360°",
             'text': "Les objets de toutes les caméras sont fusionnés dans le repère de la navette et tracés "
                     "sur une carte : un véhicule garde son identifiant d'une caméra à l'autre, les "
                     "trajectoires sont lissées, le fond peut être l'orthophoto IGN et la carte peut tourner "
                     "avec le cap de la navette."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/base.html:105-108, wama_lab/cam_analyzer/utils/pass_tracking.py:150-151, wama_lab/cam_analyzer/static/cam_analyzer/js/index.js:3158-3260
            {'title': "Deux types de rapport",
             'text': "« Proximité & dépassements » repère, sans GPS, les suivis rapprochés, les dépassements "
                     "sur les caméras latérales et les traversées de piétons ou cyclistes devant la navette. "
                     "« Insertions aux intersections » étudie la caméra avant dans les fenêtres GPS autour "
                     "des carrefours déclarés : arrêts, puis insertions devant la navette."},
            # verified: wama_lab/cam_analyzer/tasks.py:636-661, wama_lab/cam_analyzer/tasks.py:220-229, wama_lab/cam_analyzer/tasks.py:295-306, wama_lab/cam_analyzer/tasks.py:354-364
            {'title': "Indicateurs, conflits et tableaux par véhicule",
             'text': "Distance, vitesse et temps à collision des objets, conflits consolidés par objet "
                     "(navette passée avant ou après, marge, sévérité) et, pour chaque véhicule, un tableau "
                     "des insertions (instants t0/t1/t2, distances, TTC et PET observés, véhicule derrière "
                     "la navette) et des dépassements, avec rabattement."},
            # verified: wama_lab/cam_analyzer/models.py:517-554, wama_lab/cam_analyzer/utils/vehicle_tables.py:1-7, wama_lab/cam_analyzer/utils/vehicle_tables.py:26-32, wama_lab/cam_analyzer/CAM_ANALYZER_CHAINE_TRAITEMENT.md:287-304
            {'title': "Calibration et comparaison avec / sans",
             'text': "Chaque session se calibre une fois (synchronisation GPS↔vidéo, orientation et champ "
                     "des caméras, position de l'antenne, calibration du sol) ; le panneau « Comparer » "
                     "active ou coupe chaque amélioration pour en mesurer l'effet."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/base.html:36-101, wama_lab/cam_analyzer/templates/cam_analyzer/base.html:175-178
            {'title': "Vidéos anonymisées pour l'affichage",
             'text': "Visages et plaques peuvent être floutés, avec un seuil par classe, dans des vidéos "
                     "réservées à la démonstration : l'analyse lit toujours les vidéos d'origine."},
            # verified: wama_lab/cam_analyzer/models.py:136-170, wama_lab/cam_analyzer/utils/pass_tracking.py:104-119, wama_lab/cam_analyzer/templates/cam_analyzer/index.html:601-632
        ],
        'help': [
            {'title': "Préparer un profil d'analyse",
             'text': "Le profil fixe le type de rapport, les classes suivies, les seuils de confiance et "
                     "d'IoU, le suivi d'objets et les vues à analyser ; les autres vues restent en lecture "
                     "seule. Un profil se réutilise d'une session à l'autre."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/index.html:420-521, wama_lab/cam_analyzer/models.py:63-112
            {'title': "Placer les intersections",
             'text': "Pour le rapport « Insertions », ajoutez chaque carrefour : cherchez la ville, cliquez "
                     "sur la carte pour poser le point, puis réglez le rayon d'analyse et le rayon où un "
                     "véhicule immobile n'est jamais compté comme garé."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/index.html:652-709, wama_lab/cam_analyzer/static/cam_analyzer/js/index.js:4984-4989, wama_lab/cam_analyzer/static/cam_analyzer/js/index.js:5011-5023
            {'title': "Analyser vite, compléter ensuite",
             'text': "« Restreindre l'analyse aux fenêtres d'intersection » fait gagner beaucoup de temps sur "
                     "un long trajet ; un rapport qui demande le parcours entier se rattrape plus tard en "
                     "complétant les tranches manquantes, sans tout refaire."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/index.html:639-649, wama_lab/cam_analyzer/urls.py:23, wama_lab/cam_analyzer/CAM_ANALYZER_CHAINE_TRAITEMENT.md:340-365
            {'title': "Recaler le GPS sur la vidéo",
             'text': "Si la navette ne colle pas à l'image, ouvrez « Calibration » : glissez le décalage "
                     "GPS jusqu'à l'alignement puis enregistrez, ou recalculez-le depuis l'enregistrement "
                     "avec « Sync .rec ». Le recalage s'applique à l'affichage, sans nouvelle analyse."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/base.html:47-61, wama_lab/cam_analyzer/models.py:283-295
            {'title': "Exports",
             'text': "Une fois l'analyse terminée, le volet Exports propose les détections, les segments, "
                     "les conflits, les insertions par véhicule et les dépassements en CSV, ainsi que le "
                     "rapport complet en JSON ; une vidéo annotée est produite par caméra lors d'une analyse "
                     "complète (pas lors d'une complétion)."},
            # verified: wama_lab/cam_analyzer/templates/cam_analyzer/base.html:272-296, wama_lab/cam_analyzer/urls.py:52-57, wama_lab/cam_analyzer/tasks.py:1014-1030
        ],
        'links': [],  # une seule page (cam_analyzer:index) ; aucune page propre à lister — verified: wama_lab/cam_analyzer/urls.py:11
    },
    'face_analyzer': {
        'summary': (
            "Application de recherche qui estime, sans contact et à partir d'une vidéo de visage, des "
            "indicateurs physiologiques et comportementaux : rythme cardiaque, respiration, regard, "
            "clignements, pose de la tête et émotions."
        ),  # verified: wama_lab/face_analyzer/README.md:3-5, wama_lab/face_analyzer/pipeline.py:93-103
        'features': [
            {'title': "Deux modes d'analyse",
             'text': "En temps réel depuis la webcam, ou en post-traitement d'un fichier vidéo enregistré."},
            # verified: wama_lab/face_analyzer/models.py:80-82, wama_lab/face_analyzer/urls.py:12-14, wama_lab/face_analyzer/templates/face_analyzer/index.html:14-59
            {'title': "Signaux cardiaques par photopléthysmographie",
             'text': "Les infimes variations de couleur de la peau donnent la fréquence cardiaque, sa "
                     "variabilité (RMSSD, SDNN) et une estimation de la saturation en oxygène, calculées "
                     "sur une fenêtre glissante de dix secondes."},
            # verified: wama_lab/face_analyzer/rppg.py:75-92, wama_lab/face_analyzer/rppg.py:154-198, wama_lab/face_analyzer/utils/signal_processing.py:14-17
            {'title': "Respiration",
             'text': "Fréquence respiratoire, amplitude relative et type de respiration (régulière, "
                     "irrégulière, superficielle, profonde)."},
            # verified: wama_lab/face_analyzer/respiration.py:32-45, wama_lab/face_analyzer/pipeline.py:231-239
            {'title': "Oculométrie",
             'text': "Direction du regard, diamètre pupillaire, clignements et PERCLOS — la part du temps "
                     "où les yeux sont fermés à plus de 80 %, indicateur de fatigue."},
            # verified: wama_lab/face_analyzer/eye_tracking.py:3-9, wama_lab/face_analyzer/eye_tracking.py:188-189, wama_lab/face_analyzer/eye_tracking.py:424-427
            {'title': "Émotions, âge et genre",
             'text': "Sept émotions de base (joie, tristesse, colère, peur, surprise, dégoût, neutre), avec "
                     "deux moteurs au choix : l'un rapide, l'autre plus complet qui estime aussi l'âge et "
                     "le genre."},
            # verified: wama/common/backends/emotions.py:141-144, wama_lab/face_analyzer/templates/face_analyzer/video.html:129-145, wama_lab/face_analyzer/pipeline.py:48-49
            {'title': "Pose de la tête",
             'text': "Lacet, tangage et roulis de la tête, image par image."},
            # verified: wama_lab/face_analyzer/pipeline.py:211-213, wama_lab/face_analyzer/surfaces.py:42-43
            {'title': "Résultats du post-traitement",
             'text': "Une vidéo annotée (repères du visage, zones de mesure, axes de la tête, valeurs "
                     "affichées), des courbes temporelles, un résumé statistique de la session et un "
                     "export JSON des mesures."},
            # verified: wama_lab/face_analyzer/pipeline.py:249-312, wama_lab/face_analyzer/tasks.py:139, wama_lab/face_analyzer/views.py:340-407, wama_lab/face_analyzer/templates/face_analyzer/video.html:1628-1637
        ],
        'help': [
            {'title': "Choisir ses modules",
             'text': "Cochez seulement les mesures utiles (cœur, oculométrie, émotions, respiration) : un "
                     "module décoché n'est pas chargé, ce qui allège le traitement."},
            # verified: wama_lab/face_analyzer/templates/face_analyzer/video.html:99-124, wama_lab/face_analyzer/pipeline.py:136-158
            {'title': "Patienter dix secondes",
             'text': "Fréquence cardiaque, variabilité et saturation ne s'affichent qu'après une dizaine de "
                     "secondes de visage détecté : c'est la durée de la fenêtre d'analyse."},
            # verified: wama_lab/face_analyzer/rppg.py:78, wama_lab/face_analyzer/rppg.py:143-152
            {'title': "Un seul visage",
             'text': "L'analyse suit un seul visage à la fois : cadrez la personne seule, de face."},
            # verified: wama_lab/face_analyzer/pipeline.py:115-118
            {'title': "Âge et genre",
             'text': "Ils ne sont estimés qu'avec le moteur d'émotions « complet », option cochée."},
            # verified: wama_lab/face_analyzer/pipeline.py:48-49, wama_lab/face_analyzer/views.py:122-123
            {'title': "Raccourcis du lecteur",
             'text': "Espace lance ou met en pause la vidéo ; F ou un double-clic passe en plein écran."},
            # verified: wama_lab/face_analyzer/templates/face_analyzer/video.html:481-496
            {'title': "Des estimations de recherche",
             'text': "Les mesures sont des estimations, sans valeur médicale ni diagnostique ; la saturation "
                     "en oxygène, en particulier, est approchée à partir du canal vert de l'image."},
            # verified: wama_lab/face_analyzer/rppg.py:182-185
        ],
        'links': [
            {'label': "Analyse en temps réel (webcam)", 'url_name': "wama_lab:face_analyzer:realtime"},
            # verified: wama_lab/face_analyzer/urls.py:12, wama_lab/urls.py:9, wama/urls.py:63
            {'label': "Post-traitement d'une vidéo", 'url_name': "wama_lab:face_analyzer:video"},
            # verified: wama_lab/face_analyzer/urls.py:13, wama_lab/urls.py:9, wama/urls.py:63
        ],
    },
}

#: Libellé d'une nature d'entrée qui n'est pas une nature de FICHIER (`output_formats.NATURE_LABELS`
#: porte les autres).
_INPUT_LABELS = {'prompt': 'Consigne écrite', 'text': 'Texte'}

#: Les capacités déclarées au catalogue que l'« À propos » montre, dans cet ordre.
CAPABILITIES = (
    ('has_batch', 'fas fa-layer-group', 'Traitement par lots'),
    ('has_url_import', 'fas fa-link', 'Import depuis une adresse'),
    ('has_youtube', 'fab fa-youtube', 'Vidéos YouTube'),
    ('has_live_input', 'fas fa-microphone', 'Saisie en direct'),
    ('instant_preview', 'fas fa-bolt', 'Résultat pendant la frappe'),
    ('has_text_file_input', 'fas fa-file-lines', 'Fichier texte en entrée'),
    ('has_result_import', 'fas fa-file-import', 'Import d\'un résultat existant'),
    ('has_reference_result', 'fas fa-scale-balanced', 'Comparaison à un résultat de référence'),
)

#: Nombre de moteurs nommés par groupe dans le corps (la liste entière suit, avec leurs publications).
ENGINES_SHOWN = 6



def _spec(app_id: str) -> dict:
    from wama.common.app_registry import APP_CATALOG
    return APP_CATALOG.get(app_id) or {}


def _identity(app_id: str) -> dict:
    """L'identité d'une app hors du catalogue des apps (monde Lab) : `app_registry.app_identity`."""
    from wama.common.app_registry import app_identity
    return app_identity(app_id) or {}


def declaration_key(app_id: str) -> str:
    """La clé de déclaration d'une app : la sienne, ou celle de sa SOURCE pour une jumelle."""
    if app_id in ABOUT:
        return app_id
    source = _spec(app_id).get('generated_from') or ''
    return source if source in ABOUT else app_id


def declared(app_id: str) -> dict:
    return ABOUT.get(declaration_key(app_id)) or {}


def _type_label(kind: str) -> str:
    from wama.common.utils.output_formats import NATURE_LABELS
    found = _INPUT_LABELS.get(kind) or NATURE_LABELS.get(kind)
    # Une sortie peut être un FORMAT (`txt`, `srt`) : il se dit en capitales.
    return found or (kind.upper() if len(kind) <= 4 else kind.capitalize())


def _links(app_id: str, items) -> list:
    """Les pages propres à l'app — sur une jumelle, la même page dans SON espace de noms ; une
    page qui ne se résout pas n'est pas offerte (jamais un lien mort)."""
    source = declaration_key(app_id)
    out = []
    for item in items or ():
        name = item['url_name']
        if source != app_id and name.startswith(source + ':'):
            name = app_id + name[len(source):]
        try:
            out.append({'label': item['label'], 'url': reverse(name)})
        except NoReverseMatch:
            continue
    return out


def origin(app_id: str) -> dict:
    """D'où vient l'app : WAMA, ou le bac à sable — ses DÉVELOPPEURS (créateur d'abord, puis ceux
    qui ont pris part à sa génération), l'app dont elle est la jumelle, le manifeste dont elle est
    née. Un développeur se nomme comme son compte l'affiche (nom complet, sinon identifiant)."""
    spec = _spec(app_id)
    if not spec.get('sandbox'):
        # Le monde se LIT (`app_identity` → `app_world`) et se nomme par son libellé déclaré
        # (`world_label`) : le substrat ne cite aucun monde.
        from wama.common.app_registry import world_label
        world = _identity(app_id).get('world')
        return {'kind': 'wama', 'label': 'Application de WAMA',
                'world': world_label(world) if world else ''}
    from django.contrib.auth import get_user_model
    from wama.common.sandbox import app_contributors
    names = app_contributors(app_id)
    accounts = {u.username: u for u in get_user_model().objects.filter(username__in=names)}
    developers = [(accounts[n].get_full_name() or n) if n in accounts else n for n in names]
    source = spec.get('generated_from') or ''
    return {'kind': 'sandbox', 'developers': developers,
            'source': _spec(source).get('label', source) if source else '',
            'manifest': spec.get('from_manifest') or ''}


def short_name(name: str) -> str:
    """Le nom COURT d'un modèle pour une pastille : avant le tiret qui ouvre sa description
    (« Qwen Image 2 (20B) — #1 open source… »), dernier segment d'une clé de dépôt, sans son
    étiquette de quantification (`hf.co/org/Model-GGUF:Q6_K` → `Model-GGUF`). La fiche entière
    reste dans « Modèles et publications »."""
    name = (name or '').split(' — ')[0].strip()
    if '/' in name:
        name = name.rsplit('/', 1)[-1]
    return name.split(':', 1)[0] or name


def engines(app_id: str, groups=None) -> list:
    """Les MOTEURS actuels, par groupe (un select de catalogue) : `[{label, names, more}]` — la
    lecture de « Modèles et publications », que le corps résume."""
    if groups is None:
        from wama.common.services.model_publications import app_models
        groups = app_models(app_id)
    out = []
    for group in groups:
        names = list(dict.fromkeys(short_name(m['name']) for m in group['models']))
        out.append({'label': group['label'], 'names': names[:ENGINES_SHOWN],
                    'more': max(0, len(names) - ENGINES_SHOWN)})
    return out


def about_facts(app_id: str, groups=None) -> dict:
    """Ce que l'onglet « À propos » montre : le déclaré et le dérivé, prêts à rendre."""
    spec = _spec(app_id)
    who = spec or _identity(app_id)
    mine = declared(app_id)
    return {
        'app': app_id,
        'label': (who.get('label') or app_id).replace(SANDBOX_BADGE, ''),
        'icon': who.get('icon') or 'fas fa-cube',
        'color': who.get('color') or '',
        'summary': mine.get('summary') or who.get('description') or '',
        'features': list(mine.get('features') or ()),
        'links': _links(app_id, mine.get('links')),
        'inputs': [_type_label(t) for t in spec.get('input_types') or ()],
        'extensions': list(spec.get('input_extensions') or ()),
        'outputs': [_type_label(t) for t in spec.get('output_types') or ()],
        'capabilities': [{'icon': icon, 'label': label} for key, icon, label in CAPABILITIES
                         if spec.get(key)],
        'engines': engines(app_id, groups),
        'origin': origin(app_id),
    }


def help_facts(app_id: str) -> dict:
    """Ce que l'onglet « Aide » montre : les gestes COMMUNS (le gabarit), les capacités déclarées
    qui en ajoutent, et l'aide PROPRE à l'app déclarée."""
    spec = _spec(app_id)
    mine = declared(app_id)
    return {'app': app_id,
            'label': ((spec or _identity(app_id)).get('label') or app_id).replace(SANDBOX_BADGE, ''),
            'has_batch': bool(spec.get('has_batch')),
            'has_url_import': bool(spec.get('has_url_import')),
            'has_youtube': bool(spec.get('has_youtube')),
            'items': list(mine.get('help') or ()),
            'links': _links(app_id, mine.get('links'))}
