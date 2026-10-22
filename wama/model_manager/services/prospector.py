"""
Prospection de modèles — version DÉTERMINISTE (sans LLM, sans scraping).

Interroge l'API officielle `huggingface_hub` pour lister les modèles notables d'une tâche
(triés par téléchargements) et signale ceux que WAMA possède déjà. C'est le socle factuel :
la couche multi-agents (lecture de benchmarks, confrontation d'avis, score de confiance)
viendra PAR-DESSUS ce signal, et toute intégration reste soumise à acceptation admin.

Mapping app WAMA → tâche HF dans `APP_TASKS`.
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

# Tâche HuggingFace par défaut pour chaque app WAMA (point de départ de la prospection).
APP_TASKS = {
    'imager':       'text-to-image',
    'video':        'text-to-video',
    'transcriber':  'automatic-speech-recognition',
    'synthesizer':  'text-to-speech',
    'describer':    'image-text-to-text',
    'anonymizer':   'object-detection',
    'enhancer':     'image-to-image',
}

def hf_task_to_wama(pipeline_tag: str, tags=()):
    """
    (tâche NÔTRE, model_type) d'un dépôt HF, d'après son tag de pipeline ET les tags de sa
    carte. Les tags sont des DONNÉES déclarées par l'auteur — pas une devinette sur le nom,
    qui est la trappe interdite ailleurs (identité de la LoRA logo lue dans « max 768 px »).

    ⚠ Deux tags HF sont plus GROSSIERS que notre taxonomie et se tranchent ICI, par les tags
    de la carte : `image-to-image` couvre l'ÉDITION (Qwen-Image-Edit, FLUX Kontext),
    l'agrandissement et le débruitage ; `image-to-text` couvre l'OCR et le LÉGENDAGE (BLIP) ;
    `text-to-audio` couvre la musique et l'ambiance. Mesuré le 2026-09-02 sur les proposés du
    jour : FLUX.2-dev et FLUX.2-klein taggés `image-editing`, Qwen-Image-Edit/Kontext sans tag
    fin mais pipelines d'édition — aucun des six n'était un upscaler ; BLIP-base taggé
    `image-captioning`, manga-ocr et PP-OCRv5 sans ce tag → OCR.

    HORS de ces cas, la traduction est celle du CATALOGUE (`models.canonical_task` /
    `model_type_for_task`, alias composites compris) : cette fonction portait deux tables
    parallèles (`_HF_TAG_TASK`, `_TASK_MODEL_TYPE`) jusqu'au 2026-09-19 — mesuré alors,
    **0 désaccord** avec celles du catalogue, et 3 tags que seules celles-ci connaissaient.
    Elles ont donc déménagé dans `models.py` (`PLATFORM_TAG_ALIASES`) au lieu d'être
    maintenues en double. Un tag inconnu ne donne AUCUNE tâche (jamais le tag brut, qui
    serait hors `ModelTask`) et retombe sur `diffusion` pour la catégorie, comme avant.
    """
    from wama.model_manager.models import model_type_for_task, wama_task

    t = (pipeline_tag or '').strip().lower()
    bag = {str(x).lower() for x in (tags or [])}
    # ANALYSE DE MISE EN PAGE (2026-10-07) — tranchée par la CARTE, quel que soit le pipeline :
    # PP-DocLayoutV3 publie `object-detection`, PP-DocLayout-L `image-to-text`, et tous deux le
    # tag d'éditeur `layout_detection` (mesuré sur les cartes). Table Transformer ne porte que son
    # tag d'ARCHITECTURE (`table-transformer`, le même pour la détection de tableaux et pour la
    # reconnaissance de leur structure) : c'est une donnée déclarée, pas une devinette sur le nom
    # — et la détection de tableaux EST de l'analyse de mise en page. Sans cette règle, tous
    # entraient en `detect`, avec les détecteurs d'objets d'une scène.
    if bag & {'layout_detection', 'layout-detection', 'document-layout-analysis',
              'table-transformer'}:
        return 'layout-detection', 'vision'
    # TRANSCRIPTION MUSICALE MULTI-INSTRUMENT (2026-10-16) — tranchée par la CARTE : aucune tâche de
    # pipeline HuggingFace ne la nomme (`MuScriptor/muscriptor-large` n'en publie AUCUNE, et ses tags
    # disent `audio-to-midi`, `automatic-music-transcription`). Sans cette règle le dépôt NOMMÉ était
    # écarté de la prospection (« sa tâche n'entre pas dans le périmètre »).
    if bag & {'audio-to-midi', 'automatic-music-transcription', 'music-transcription'}:
        return 'audio-to-midi', 'music'
    if t == 'image-to-image':
        if any(k in bag for k in ('super-resolution', 'upscaling', 'upscale', 'image-restoration')):
            return 'upscale', 'upscaling'
        if any('denois' in k for k in bag):
            return 'denoise', 'upscaling'
        return 'image-to-image', 'diffusion'
    if t == 'image-to-text':
        if 'image-captioning' in bag:
            return 'captioning', 'vlm'
        return 'ocr', 'ocr'
    if t == 'image-text-to-text':
        # Les OCR DOCUMENTAIRES récents sont des VLM par leur architecture : mesuré le
        # 2026-10-10 sur olmOCR-Bench, 6 des 7 premiers (LightOnOCR-3, Chandra-2,
        # Infinity-Parser2, dots.mocr, DeepSeek-OCR-2, jina-ocr) publient ce pipeline — et tous
        # taguent `ocr`. Sans cette branche ils entraient en `captioning`, chez le describer.
        if 'ocr' in bag:
            return 'ocr', 'ocr'
        # 4ᵉ tag plus GROSSIER que nous, mesuré le 2026-09-19 sur une ligne RÉELLE du catalogue :
        # `nvidia/LocateAnything-3B` publie `pipeline_tag: image-text-to-text` (c'est un VLM par
        # son architecture) et tague `object-detection` — il LOCALISE des objets décrits en
        # texte. L'alias seul en faisait du `captioning`/`vlm` : faux métier, donc mauvais banc
        # et mauvaise sélection. Même règle que les branches ci-dessus : le TAG de la carte
        # départage ce que le pipeline_tag mélange.
        # La nuance « vocabulaire OUVERT » est désormais une tâche (décision de Fabien,
        # 2026-10-07) : un VLM qui localise ce qu'on lui DÉCRIT est la détection
        # `zero-shot-object-detection` de HuggingFace — pas le `detect` d'un détecteur à classes
        # fixes, avec qui il partageait les selects (l'anonymizer le proposait sans savoir le
        # lancer).
        if bag & {'object-detection', 'zero-shot-object-detection', 'grounding'}:
            return 'zero-shot-object-detection', 'vision'
    if t == 'text-to-audio':
        # HF n'a qu'un tag pour la musique et l'ambiance ; les tags de la carte, eux, le disent
        # (mesuré le 2026-09-19 : ACE-Step 1.5 taggé `music`, `text2music`, catalogué en
        # AMBIANCE). Le composer sépare les deux métiers — on lit ce que l'éditeur déclare.
        if any(k in bag for k in ('music', 'text2music', 'text-to-music', 'music-generation')):
            return 'text-to-music', 'music'
        return 'text-to-audio', 'music'
    return wama_task(t), model_type_for_task(t) or 'diffusion'


def card_facts(pipeline_tag: str, tags=(), card_data=None, library_name: str = '') -> dict:
    """
    Ce que la CARTE HuggingFace dit d'un modèle, traduit en faits WAMA — MÉCANIQUEMENT, jamais
    par un LLM (doctrine `PROSPECTION_PIPELINE.md` : « tirer depuis la source est un geste
    mécanique ; un manifeste doit porter les mêmes faits qu'un candidat prospecté »).

    Rend `{task, model_type, capabilities: {task, languages?}, engine}` :
      • la tâche, par `hf_task_to_wama` (pipeline ET tags) ;
      • les LANGUES déclarées (`cardData.language` : code, liste de codes, ou « multilingual »
        → `['*']`) — le vocabulaire de `capabilities['languages']` que `lang_routing` lit ;
        mesuré le 2026-09-19 : canary en publie 25, le catalogue n'en avait aucune ;
      • le MOTEUR, quand `library_name` est un moteur qu'un backend WAMA sait servir
        (`engine_backends`) — `transformers`, `diffusers`… ; `nemo` n'en est pas un, et on ne
        pose rien plutôt qu'un moteur plausible.
    Une carte muette rend des clés absentes, jamais des valeurs inventées.
    """
    from wama.common.backends.manager import engine_backends

    task, model_type = hf_task_to_wama(pipeline_tag, tags)
    caps = _task_capabilities({}, task)
    data = {}
    if card_data:
        try:
            data = card_data.to_dict() if hasattr(card_data, 'to_dict') else dict(card_data)
        except Exception:
            data = {}
    language = data.get('language')
    if isinstance(language, str):
        language = [language]
    if isinstance(language, (list, tuple)):
        # Code COURT (`fr-FR` → `fr`, 2026-10-01) : `lang_routing._handles` compare des codes
        # exacts, une langue régionale ne s'y apparierait jamais. Doublons retirés, ordre gardé.
        codes = list(dict.fromkeys(str(x).strip().lower().replace('_', '-').split('-')[0]
                                   for x in language if x and str(x).strip()))
        if any(c in ('multilingual', 'multi') for c in codes):
            caps['languages'] = ['*']
        elif codes:
            caps['languages'] = codes
    engine = (library_name or '').strip().lower()
    engine = engine if engine and engine in engine_backends() else None
    return {'task': task, 'model_type': model_type, 'capabilities': caps, 'engine': engine}


#: Ce qu'une TÂCHE implique dans les capacités (`default_inputs_for`) — à redériver quand la
#: tâche change, jamais à hériter de l'ancienne.
_TASK_DERIVED = ('modalities', 'inputs_required', 'inputs_optional')


def _task_capabilities(caps: dict, task: str) -> dict:
    """Les capacités d'une proposition pour CETTE tâche : ce qu'elle implique (modalités, entrées —
    `default_inputs_for`, la dérivation de la découverte Ollama et des modèles distants) par-dessus
    les faits propres à la carte (langues).

    POURQUOI (2026-10-11, fil n° 38) : une proposition ne portait que `{'task'}` — aucune des 17
    propositions OCR n'avait de modalités, et `list_ai_models(task='ocr', modality='image')` de
    l'assistant les écartait toutes. Une ligne ne les recevait qu'à son INSTALLATION."""
    if not task:
        return dict(caps)
    from ..models import default_inputs_for
    kept = {k: v for k, v in caps.items() if k not in _TASK_DERIVED}
    return {**kept, **default_inputs_for(task), 'task': task}


def _metrique_declaree(card_data):
    """
    Metrique d'evaluation auto-declaree dans le `model-index` de la carte HF, ou None.

    C'est le seul signal de QUALITE que la plateforme expose ; tout le reste (telechargements,
    likes) mesure la popularite. Mais elle est auto-declaree, non verifiee, et calculee sur le
    jeu de validation de l'AUTEUR : deux modeles a 0.98 et 0.95 ne sont pas comparables s'ils
    n'ont pas ete evalues sur le meme jeu. On rend donc le jeu et le drapeau `verifie` avec la
    valeur -- de quoi trier des candidats, pas de quoi conclure.
    """
    if not card_data:
        return None
    try:
        donnees = card_data.to_dict() if hasattr(card_data, 'to_dict') else dict(card_data)
    except Exception:
        return None
    index = donnees.get('model-index') or donnees.get('model_index') or []
    for entree in index:
        for resultat in (entree.get('results') or []):
            jeu = ((resultat.get('dataset') or {}).get('name')) or ''
            for metrique in (resultat.get('metrics') or []):
                valeur = metrique.get('value')
                if isinstance(valeur, (int, float)):
                    return {
                        'nom': metrique.get('name') or metrique.get('type') or 'metrique',
                        'valeur': float(valeur),
                        'jeu': jeu,
                        'verifie': bool(metrique.get('verified')),
                    }
    return None


def _sans_suffixe_date(hf_id: str) -> str:
    """`qwen/qwen-image-edit-2511` → `qwen/qwen-image-edit` : le suffixe `-AAMM` (4 chiffres,
    mois plausible) que Qwen, Kimi… accolent à leurs versions. Un nombre qui n'est pas un
    mois (`-1024`, `-7000`) ou une taille (`-8b`) reste en place."""
    import re
    return re.sub(r'-(2[3-9])(0[1-9]|1[0-2])$', '', (hf_id or '').lower())


def prospect_hf(task: str, limit: int = 15, library: str | None = None, min_downloads: int = 0,
                search: str | None = None, sort: str = 'downloads'):
    """
    Top modèles HF d'une `task` (par téléchargements), avec flag « déjà dans WAMA ».
    Retourne {'ok': True, 'task': str, 'candidates': [...]} ou {'ok': False, 'error': str}.

    `search` restreint aux modèles dont le nom contient les termes donnés. Sans lui, une tâche
    large ne rend que les modèles les plus téléchargés — pour `object-detection`, des détecteurs
    COCO génériques, jamais les spécialisés qu'on cherche (visage, plaque). Constaté le
    2026-08-04 en cherchant à remplacer les modèles visage/plaque de l'anonymizer.
    """
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return {'ok': False, 'error': "huggingface_hub non installé (pip install huggingface_hub)"}

    from wama.model_manager.models import AIModel
    # « Déjà chez nous » s'indexe sur les DEUX identités de plateforme, pas sur `hf_id` seul :
    # les modèles découverts par scan disque n'ont pas de `hf_id`, mais peuvent porter un
    # `platform_ref` posé par la provenance vérifiée (backfill_platform_refs / manifeste).
    # Sans ça, morsetechlab/yolov11-license-plate-detection ressortait « ★ NOUVEAU » alors que
    # ses 5 fichiers sont installés — la veille proposait de télécharger l'existant (2026-08-12).
    have = {(m.hf_id or '').lower() for m in AIModel.objects.exclude(hf_id='')}
    have |= {ref.partition(':')[2].lower()
             for ref in AIModel.objects.filter(platform_ref__startswith='huggingface:')
                                       .values_list('platform_ref', flat=True)}
    have.discard('')
    # 2026-09-02 : un dépôt qui ne diffère d'un déclaré que par un SUFFIXE DATÉ est la même
    # famille — `Qwen/Qwen-Image-Edit-2509` proposé alors que l'imager déclare `…-2511`
    # (mesuré : la proposition d'une VERSION ANTÉRIEURE passait le dédoublonnage). On compare
    # aussi les identifiants sans leur date (`-AAMM`) : `have_famille`.
    have_famille = {_sans_suffixe_date(h) for h in have}

    api = HfApi()
    # huggingface_hub 1.x : filtrage par tâche = `pipeline_tag` (pas `task`), librairie via `filter`.
    # `sort` : 'downloads' (éprouvé) ou 'trendingScore' (ce qui MONTE — seul tri qui fait
    # sortir une famille fraîchement publiée avant qu'elle domine les téléchargements ;
    # vérifié 2026-08-18 : le top downloads text-to-video ignorait les sorties de la semaine).
    kwargs = {'pipeline_tag': task, 'sort': sort, 'limit': limit,
              'expand': ['downloads', 'likes', 'lastModified', 'pipeline_tag', 'cardData']}
    if library:
        kwargs['filter'] = library
    if search:
        kwargs['search'] = search
    try:
        models = list(api.list_models(**kwargs))
    except Exception as e:
        # Repli si `expand` non supporté/incompatible avec ce filtre.
        kwargs.pop('expand', None)
        try:
            models = list(api.list_models(**kwargs))
        except Exception as e2:
            return {'ok': False, 'error': f"{type(e2).__name__}: {e2}"}
    # Garantir l'ordre décroissant par téléchargements quel que soit le défaut de l'API.
    models.sort(key=lambda m: getattr(m, 'downloads', 0) or 0, reverse=True)

    candidates = []
    for m in models:
        dl = getattr(m, 'downloads', 0) or 0
        if dl < min_downloads:
            continue
        lm = getattr(m, 'last_modified', None)
        carte = getattr(m, 'card_data', None)
        licence, base_model = None, None
        language = None
        if carte is not None:
            try:
                cd = carte.to_dict() if hasattr(carte, 'to_dict') else dict(carte)
                licence = cd.get('license')
                # Le modèle de BASE déclaré par la carte : c'est lui qui porte la licence
                # d'un dérivé (cf. `analyze_license`). Chaîne ou liste selon les cartes.
                base_model = cd.get('base_model')
                # Les LANGUES déclarées (2026-09-19) — lues ici, dans la MÊME requête, pour que
                # le candidat les porte (`card_facts`).
                language = cd.get('language')
            except Exception:
                licence = None
        candidates.append({
            'language': language,
            'hf_id': m.id,
            'downloads': dl,
            'likes': getattr(m, 'likes', 0) or 0,
            'pipeline_tag': getattr(m, 'pipeline_tag', None) or task,
            'tags': [str(x) for x in (getattr(m, 'tags', None) or [])],
            'base_model': base_model,
            'last_modified': lm.isoformat() if hasattr(lm, 'isoformat') else (lm or None),
            'have': (m.id.lower() in have
                     or _sans_suffixe_date(m.id.lower()) in have_famille),
            'metrique': _metrique_declaree(carte),
            'license': licence,
            'url': f"https://huggingface.co/{m.id}",
        })
    return {'ok': True, 'task': task, 'candidates': candidates}


# ── Balayage HF → candidats `is_proposed` (cards UI) ───────────────────────────────
# Tâches HF balayées : catégorie d'installation (= valeur ModelType, cf. model_locations),
# plancher de poids (un modèle SOUS ce poids est un LoRA/config pour la génération, mais un
# YOLO légitime pèse 13 Mo — d'où le plancher PAR TÂCHE), plafond de candidats (une liste
# que personne ne lit ne vaut pas mieux qu'une liste vide — même règle que MAX_PAR_ROLE).
# Déclaratif : élargir la prospection = ajouter une entrée, pas du code.
#
# Volontairement ABSENTS : `image-text-to-text` (VLM — doublon du rôle Ollama `vlm`, qui
# couvre déjà describer/reader avec des modèles réellement branchés — et, depuis le
# 2026-10-10, les OCR documentaires de ce pipeline arrivent par les CLASSEMENTS,
# `seed_benchmark_candidates`, qui disent la tâche mieux que l'étiquette) ; `lipsync` (aucun
# pipeline_tag HF ; la prospection avatars est un chantier séparé — PROSPECTION_AVATARS).
HF_TASKS = {
    # Génération (imager / vidéo) — étendu le 2026-08-18
    'text-to-image':  {'category': 'diffusion', 'poids_min_go': 1.0,   'max': 5},
    'text-to-video':  {'category': 'diffusion', 'poids_min_go': 1.0,   'max': 5},
    'image-to-video': {'category': 'diffusion', 'poids_min_go': 1.0,   'max': 5},
    # Vidéo multimodale — MiniMax-H3 est taggé `image-text-to-video` : invisible des deux
    # tâches ci-dessus alors que ses dérivés text-to-video saturaient le trending
    # (mesuré 2026-08-28). `text-to-audio-video` = vidéo + audio synchronisés, même famille.
    'image-text-to-video': {'category': 'diffusion', 'poids_min_go': 1.0, 'max': 5},
    'text-to-audio-video': {'category': 'diffusion', 'poids_min_go': 1.0, 'max': 5},
    # Parole (transcriber / synthesizer) — ⚠ TTS : vérifier la LICENCE sur la card (souvent NC)
    'automatic-speech-recognition': {'category': 'speech', 'poids_min_go': 0.05, 'max': 3},
    'text-to-speech':               {'category': 'speech', 'poids_min_go': 0.05, 'max': 3},
    # Image → image (enhancer)
    'image-to-image': {'category': 'upscaling', 'poids_min_go': 0.05, 'max': 3},
    # Détection (anonymizer…) — top downloads = COCO génériques ; les spécialisés
    # (visage/plaque) exigent `search`, cf. docstring prospect_hf (leçon 2026-08-04)
    'object-detection': {'category': 'vision', 'poids_min_go': 0.005, 'max': 3},
    # Musique (composer)
    'text-to-audio': {'category': 'music', 'poids_min_go': 0.05, 'max': 3},
    # OCR / documents (reader)
    'image-to-text': {'category': 'ocr', 'poids_min_go': 0.05, 'max': 3},
}

#: Un dépôt de génération sous ce poids est un LoRA/config, pas un modèle installable seul.
_MIN_WEIGHT_GB = 1.0

#: Motifs de BRUIT dans l'id d'un dépôt de génération : dérivés (LoRA, quantifs, repacks
#: d'outils tiers) qui noient les modèles canoniques — mesuré 2026-08-18 : le trending
#: text-to-video était aux 3/4 des LoRA MiniMax-H3 de particuliers.
_NOISE_MARKERS = ('lora', 'gguf', 'comfyui', 'repackaged', 'fp8', 'bnb',
                 'int4', 'int8', 'fp4', 'nvfp4', '4bit',
                 'coreml', 'mlx',   # formats Apple : non chargeables sur l'hôte CUDA
                 # marqueurs déjà dans _QUANT_MARKERS mais absents d'ici : mesuré 2026-08-28,
                 # « Hippotes/LTX-2.3-quants » passait le seeding comme canonique
                 'quant', 'awq', 'gptq',
                 # add-ons non autonomes (même famille que `lora`) : mesuré 2026-08-29,
                 # « MiniMax-H3-Fun-Controlnet-Union » et « MiniMax-H3-Motion-Adapter »
                 # proposés comme canoniques alors qu'ils exigent le modèle de base
                 'controlnet', 'adapter')


#: Extensions de fichiers de POIDS (pour le détail par fichier des dépôts quantisés).
#: Remontée ici le 2026-09-07 avec la dérivation qui l'emploie — elle vivait 190 lignes plus
#: bas, à côté de la seule fonction qui la lisait.
#: ⚠ `.onnx` AJOUTÉ le 2026-09-19 : son absence faisait peser faux une composition DÉJÀ
#: déclarée — `huggingface:onnx-community/Kokoro-82M-v1.0-ONNX` déclare le rôle
#: `acoustic_model` sur `onnx/model.onnx`, et le relevé rendait 0,027 Go (ses seules voix
#: `.bin`) pour un modèle de 0,3 Go, le rôle principal comptant pour RIEN. WAMA catalogue de
#: vrais modèles ONNX (ce Kokoro, les 6 YOLO/ONNX de l'anonymizer, les upscalers de l'enhancer) :
#: pour eux l'ONNX n'est pas la copie d'un autre moteur, c'est LE modèle.
#: *Une extension absente d'une liste ne produit pas d'erreur — elle produit un zéro.*
#: ⚠ `.nemo` AJOUTÉ le 2026-09-28 : l'archive NeMo EST le modèle (canary-1b-v2, parakeet-tdt,
#: 6,4 et 2,5 Go installés) — sans elle, le prédicat de complétude les aurait dits « sans poids ».
_WEIGHT_EXTS = ('.gguf', '.safetensors', '.bin', '.pt', '.pth', '.onnx', '.nemo')

#: Formats de poids qui PROUVENT un moteur à eux seuls : l'archive ne s'ouvre que par lui. UNE
#: table, lue par les deux producteurs du moteur — les rôles wama-dev-ai (`role_utils`, où elle
#: est née le 2026-10-01 pour le `.nemo` de LinTO) et la dérivation du balayage
#: (`model_registry`). `.onnx` (2026-10-06, Swin2SR d'Optimum) : un graphe ONNX ne s'exécute que
#: par un runtime ONNX, `onnxruntime` est le seul que WAMA sert ; le `config.json` recopié du
#: modèle d'origine faisait dériver `transformers`, qui n'ouvre pas un `.onnx`. Un format absent
#: ne prouve rien (`.safetensors` se lit par dix libs).
WEIGHT_FORMAT_ENGINES = {'.nemo': 'nemo', '.onnx': 'onnxruntime'}


def _siblings(hf_id: str):
    """`[(nom, taille_octets)]` de TOUS les fichiers d'un dépôt — la SEULE requête HTTP de
    l'inventaire (2026-09-07).

    Domicile unique de ce geste : il partait en DEUX exemplaires dans ce fichier
    (`_repo_weight_gb` et l'ex-`_weight_files`, 170 lignes d'écart, même appel), et les deux
    étaient invoqués sur le MÊME dépôt à quatre lignes d'écart dans `install_options` — donc
    deux allers-retours HTTP par variante. Les DÉRIVATIONS, elles, restent distinctes : le
    poids total compte TOUS les fichiers, la liste de poids n'en garde que certains. C'est
    l'appel qui était en double, pas le calcul.

    None = dépôt injoignable, à distinguer d'un dépôt VIDE (`[]`) : l'un est une panne,
    l'autre un fait. À réserver aux candidats RETENUS, pas au listing.
    """
    try:
        from huggingface_hub import HfApi
        info = HfApi().model_info(hf_id, files_metadata=True)
        return [(s.rfilename, s.size or 0) for s in (info.siblings or [])]
    except Exception as e:
        logger.debug("[prospect_hf_seed] inventaire de %s indéterminable : %s", hf_id, e)
        return None


def _poids_total_gb(fichiers):
    """Go de la somme de TOUS les fichiers, ou None — dérivation PURE, aucun réseau.
    `0` rend None : un dépôt dont les tailles sont absentes n'est pas un dépôt vide."""
    total = sum(t for _, t in (fichiers or []))
    return round(total / 1024 ** 3, 1) if total else None


def _fichiers_de_poids(fichiers):
    """`[(nom, taille)]` des seuls fichiers de POIDS — dérivation PURE, aucun réseau."""
    return [(n, t) for n, t in (fichiers or []) if n.lower().endswith(_WEIGHT_EXTS)]


def _repo_weight_gb(hf_id: str):
    """Poids total d'un dépôt HF en Go, ou None si indéterminable. Un appel HTTP par dépôt.
    Conservée : trois appelants ne veulent QUE cette valeur (`prospect_hf_seed` ×2,
    `views.install` pour sa garde d'espace) et n'ont pas à connaître l'inventaire."""
    return _poids_total_gb(_siblings(hf_id))


def local_revision(snapshot_root):
    """Le dossier dont les chemins de `local_inventory` sont RELATIFS : la révision la plus
    récente sous `snapshots/` d'une racine `models--org--nom`, ou le dossier de poids lui-même.
    None si absent ou sans révision. Nommé à part (2026-09-20) parce qu'un second lecteur —
    l'en-tête safetensors par composant — doit rouvrir ces mêmes fichiers : il lui faut la même
    base, pas une seconde règle de choix de révision."""
    from pathlib import Path

    root = Path(snapshot_root) if snapshot_root else None
    if root is None or not root.is_dir():
        return None
    if not (root / 'snapshots').is_dir():
        return root
    revisions = [p for p in (root / 'snapshots').iterdir() if p.is_dir()]
    if not revisions:
        return None
    return max(revisions, key=lambda p: p.stat().st_mtime)


def local_inventory(snapshot_root):
    """`[(chemin relatif, taille)]` d'un modèle INSTALLÉ — le jumeau LOCAL de `_siblings`
    (2026-09-19), même forme, pour que `model_installer.components_of_files` pèse un snapshot
    sur disque exactement comme un dépôt distant. Aucun réseau, aucun chargement.

    `snapshot_root` : la racine `models--org--nom` du cache HF (on prend la révision la plus
    récente sous `snapshots/`), ou directement un dossier de poids.

    ⚠ ON PÈSE LES BLOBS, PAS LES LIENS — mesuré le 2026-09-19 sur LTX-Video 13B installé : le
    snapshot porte `vae/text_encoder/…` et `vae/transformer/…`, liens vers les MÊMES blobs que
    `text_encoder/…` et `transformer/…` (22 blobs pour 34 liens). Un parcours qui pèse les
    chemins comptait 86 Go pour ~44 de poids réels. Chaque blob compte donc UNE fois, attribué
    au chemin le moins profond — la convention `premier segment = composant` reste vraie pour
    lui. Les tailles sont celles des cibles (les liens eux-mêmes pèsent 79 octets).

    None = dossier absent (indéterminable), à distinguer d'un dossier VIDE (`[]`).
    """
    import os

    revision = local_revision(snapshot_root)
    if revision is None:
        return None
    seen = {}                         # blob réel → (profondeur, chemin relatif, taille)
    for p in revision.rglob('*'):
        if not p.is_file():           # suit les liens ; un lien cassé n'est pas un fichier
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        rel = p.relative_to(revision).as_posix()
        blob = os.path.realpath(p)
        depth = rel.count('/')
        current = seen.get(blob)
        if current is None or depth < current[0]:
            seen[blob] = (depth, rel, size)
    return sorted((rel, size) for _, rel, size in seen.values())


def installed_weights_complete(snapshot_root) -> bool:
    """Un modèle installé porte-t-il des POIDS complets ? — LE jugement « téléchargé » (2026-09-28).

    POURQUOI. Deux jugements coexistaient et aucun ne regardait les poids : la découverte des apps
    (`model_registry._check_hf_model_downloaded`) se contentait d'un dossier muni de `snapshots/`
    ou `blobs/`, le balayage générique ajoutait seulement « pas de blob `.incomplete` ». Cas
    mesuré : Qwen3-ASR-1.7B, dont le chargement avorté du 25/09 (architecture inconnue de
    transformers) avait laissé un `snapshots/` de CONFIG seule (4 Mo) — catalogué « ready », donc
    ni signalé par `verify_models`, ni annoncé par `model_readiness` avant un premier lancement
    qui aurait tiré 4,7 Go en silence.

    Composé de ce qui existe, sans règle neuve : la règle `.incomplete` du balayage, l'inventaire
    LOCAL (`local_inventory`, la même lecture que la pesée par composant) et la liste d'extensions
    de poids de ce module (`_WEIGHT_EXTS`, que `model_anatomy` lit aussi). Accepte une racine
    `models--org--nom` ou un dossier de poids direct (CTranslate2, `.pt` d'une famille).

    ⚠ Ne dit PAS où sont les poids : c'est `model_locations.installed_snapshots`, qui retient
    exprès un dossier incomplet — la désinstallation doit pouvoir le trouver pour le retirer.
    ⚠ Une RECETTE sans poids propres (pipeline pyannote : un `config.yaml`, ses poids sont ses
    composants) n'a rien à y faire : l'appelant la déclare comme telle.
    """
    from pathlib import Path

    root = Path(snapshot_root) if snapshot_root else None
    if root is None or not root.is_dir():
        return False
    blobs = root / 'blobs'
    if blobs.is_dir() and any(blobs.glob('*.incomplete')):
        return False
    files = local_inventory(root)
    return bool(files) and any(rel.lower().endswith(_WEIGHT_EXTS) for rel, _ in files)


def safetensors_facts(path):
    """`{'params': nombre de paramètres, 'dtypes': [...]}` lus dans l'EN-TÊTE seul d'un
    `.safetensors` (8 octets de longueur + JSON), ou None s'il n'est pas lisible. Aucun tenseur
    n'est chargé : c'est ce qui rend le pic PAR PRÉCISION calculable sans GPU — 17,43 Md de
    paramètres en BF16 = 32,5 Go, en 8 bits 17,4, en 4 bits 8,7 (HunyuanImage 2.1, mesuré le
    2026-09-19, quand son manifeste déclare 16). `components_of_files` pèse des fichiers et ne
    lit volontairement pas les dtypes ; ceci est le complément, local par nature.
    """
    import json
    import struct

    try:
        with open(path, 'rb') as fh:
            length = struct.unpack('<Q', fh.read(8))[0]
            if not 0 < length <= 256 * 1024 * 1024:
                return None
            header = json.loads(fh.read(length))
    except (OSError, ValueError, struct.error):
        return None
    if not isinstance(header, dict):
        return None
    params, by_dtype = 0, {}
    for key, tensor in header.items():
        if key == '__metadata__' or not isinstance(tensor, dict):
            continue
        count = 1
        for dim in tensor.get('shape') or []:
            count *= int(dim)
        params += count
        dtype = str(tensor.get('dtype') or '') or None
        if dtype:
            by_dtype[dtype] = by_dtype.get(dtype, 0) + count
    # `params_by_dtype` (2026-09-20, question de la sœur) : un fichier MÉLANGE les précisions
    # (normes en F32 à côté de poids BF16, courant) — le pic « tel que stocké » se calcule tenseur
    # par tenseur (Σ params × octets du dtype), pas sur un dtype « dominant ».
    return {'params': params, 'dtypes': sorted(by_dtype), 'params_by_dtype': by_dtype}


def precision_of_files(revision, files_by_role) -> dict:
    """`{rôle: {'params', 'dtypes'}}` — la PRÉCISION de chaque composant, lue dans les en-têtes
    safetensors des fichiers que la dérivation a RETENUS (`components_of_files(...)['files']`,
    2026-09-20 : les chemins par rôle sont rendus précisément pour ça — aucun second tri des
    jeux, jumeaux ou variantes ici). Les shards d'un rôle s'additionnent ; un rôle sans
    `.safetensors` lisible (GGUF, ONNX, `.bin`, dépôt frère hors de cette révision) n'apparaît
    pas — l'absence se lit, elle ne vaut pas zéro. `revision` : la base des chemins
    (`local_revision`). Aucun tenseur chargé.
    """
    from pathlib import Path

    if not revision or not files_by_role:
        return {}
    base = Path(revision)
    out = {}
    for role, entries in files_by_role.items():
        params, by_dtype = 0, {}
        for entry in entries or []:
            rel = entry[0] if isinstance(entry, (tuple, list)) else entry
            if not str(rel).lower().endswith('.safetensors'):
                continue
            facts = safetensors_facts(base / rel)
            if not facts:
                continue
            params += facts['params']
            for dtype, n in (facts.get('params_by_dtype') or {}).items():
                by_dtype[dtype] = by_dtype.get(dtype, 0) + n
        if params:
            # Deux termes pour le lecteur du pic : Σ par dtype (tel que stocké) et le total
            # (casté par le chargeur : total × octets du dtype cible).
            out[role] = {'params': params, 'dtypes': sorted(by_dtype), 'params_by_dtype': by_dtype}
    return out


def remote_precision(hf_id: str, files_by_role) -> dict:
    """JUMEAU DISTANT de `precision_of_files`, même forme `{rôle: {params, dtypes,
    params_by_dtype}}` — pour un CANDIDAT, dont aucun fichier n'est sur disque (2026-09-23).
    `parse_safetensors_file_metadata` ne lit que l'EN-TÊTE de chaque fichier retenu (requête de
    plage), jamais un tenseur — fichier par fichier, parce que `get_safetensors_metadata` ne voit
    que la racine du dépôt et rate les sous-dossiers d'un dépôt diffusers (mesuré sur Wan).
    `{}` si rien n'est lisible : l'absence se lit, elle ne vaut pas zéro. Sans cette lecture, le
    pic d'un encodeur stocké en F32 (UMT5 de Wan : 21 Go) passait pour celui qu'il aura chargé
    en bf16 (10,6)."""
    if not hf_id or not files_by_role:
        return {}
    try:
        from huggingface_hub import HfApi
        api = HfApi()
    except Exception:
        return {}
    out = {}
    for role, entries in files_by_role.items():
        by_dtype = {}
        for entry in entries or []:
            rel = str(entry[0] if isinstance(entry, (tuple, list)) else entry)
            if not rel.lower().endswith('.safetensors'):
                continue
            try:
                counts = api.parse_safetensors_file_metadata(hf_id, rel).parameter_count or {}
            except Exception as e:
                logger.debug("[prospect_hf] en-tête %s:%s illisible : %s", hf_id, rel, e)
                continue
            for dtype, n in counts.items():
                by_dtype[dtype] = by_dtype.get(dtype, 0) + n
        if by_dtype:
            out[role] = {'params': sum(by_dtype.values()), 'dtypes': sorted(by_dtype),
                         'params_by_dtype': by_dtype}
    return out


#: Marqueurs de QUANTISATION/repack dans l'id d'un dépôt dérivé. Sous-ensemble de
#: `_NOISE_MARKERS` (moins `lora` — un adaptateur n'est pas une variante du modèle — et moins
#: `coreml`/`mlx`, inchargeables sur l'hôte CUDA), plus les schémas absents du bruit
#: (`awq`, `gptq`…). `comfy` couvre les repacks Comfy-Org/ComfyUI : single-file + variantes
#: fp8 SANS marqueur dans l'id du dépôt (mesuré 2026-08-26 : le repack le plus téléchargé
#: de MiniMax-Music3, 551 k, était invisible sans lui).
_QUANT_MARKERS = ('gguf', 'fp8', 'bnb', 'int4', 'int8', 'fp4', 'nvfp4',
                 '4bit', '8bit', 'awq', 'gptq', 'quant', 'comfy')


def quantized_variants(hf_id: str, limit: int = 5) -> list[dict]:
    """
    Dépôts HF dérivés QUANTISÉS d'un modèle (GGUF/FP8/4-8bit/AWQ…), triés par téléchargements.

    Ce qui est du BRUIT pour le listing des canoniques (`_NOISE_MARKERS` les écarte du seeding)
    est l'INFORMATION du juge de confiance : un gros modèle se juge sur sa meilleure variante,
    pas sur ses poids pleins. Vécu 2026-08-26 : MiniMax-Music3 rejeté à 10 % « 53 Go > 24 Go »
    alors que son repack single-file dominait les téléchargements de la famille.

    Recherche LARGE (radical sans le numéro de version final — « MiniMax-Music » retrouve
    « MiniMax-Music-3 », tiret inséré par le repackageur), filtre STRICT (le nom complet
    normalisé alphanumérique
    doit apparaître dans l'id candidat + un marqueur de quantisation). Réseau : 2 requêtes.
    """
    import re
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return []

    nom_court = hf_id.split('/')[-1]
    normaliser = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())  # noqa: E731
    cible = normaliser(nom_court)
    radical = re.sub(r'[-_ ]?\d+(\.\d+)?$', '', nom_court) or nom_court

    vus, variantes = {hf_id.lower()}, []
    api = HfApi()
    for terme in dict.fromkeys((nom_court, radical)):        # dédupliqué, ordre stable
        try:
            depots = api.list_models(search=terme, sort='downloads', limit=100,
                                     expand=['downloads', 'likes'])
        except Exception as e:
            logger.debug("[quantized_variants] recherche « %s » en échec : %s", terme, e)
            continue
        for d in depots:
            did = d.id.lower()
            if did in vus or cible not in normaliser(d.id):
                continue
            if not any(m in did for m in _QUANT_MARKERS):
                continue
            vus.add(did)
            variantes.append({'hf_id': d.id,
                              'downloads': getattr(d, 'downloads', 0) or 0,
                              'likes': getattr(d, 'likes', 0) or 0})
    variantes.sort(key=lambda v: v['downloads'], reverse=True)
    return variantes[:limit]


#: Licences SPDX standard SANS restriction territoriale : le texte n'est pas relu.
_SAFE_LICENSES = {'apache-2.0', 'mit', 'bsd-2-clause', 'bsd-3-clause', 'cc0-1.0',
                   'cc-by-4.0', 'openrail', 'openrail++', 'bigscience-openrail-m'}


def analyze_license(hf_id: str, license_id: str = '', base_model=None, _profondeur: int = 0):
    """
    Verdict de COMPATIBILITÉ de licence d'un candidat, pour AFFICHAGE sur la card —
    JAMAIS pour éliminer (décision Fabien 2026-08-29 : le choix reste à l'utilisateur).

    Né du cas MiniMax-H3 : la card disait `license: other` — opaque — alors que le TEXTE
    excluait l'Union européenne (« Excluded Territories »), le piège Hunyuan à l'identique.
    Un identifiant SPDX permissif (`_SAFE_LICENSES`) rend None (rien à afficher) ; sinon
    le texte du fichier LICENSE est lu (endpoint `raw` — AUCUN passage par le cache HF,
    zéro résidu disque) et scanné pour les clauses territoriales.

    ⚠ LICENCE À DOUBLE ÉTAGE (2026-09-02, question de Fabien sur H3-Turbo). Un dérivé
    (distillation, fine-tune, merge) reste un « Model Derivative » soumis à l'accord du
    modèle AMONT : le tag `apache-2.0` que `lightx2v/Minimax-h3-Turbo` s'est donné ne lève
    rien. Or ce tag est SPDX permissif, donc la garde rendait None et la card se taisait —
    pendant que la card du modèle de base affichait « UE EXCLUE ». La carte du dérivé
    DÉCLARE son `base_model` : on hérite donc du verdict du modèle de base, en le DISANT
    (`herite_de`). Un dérivé sans `base_model` déclaré reste hors de portée — un tag ne
    dit pas ce que son auteur a omis.

    Retour : None | {'verdict': 'exclusion_ue'|'restriction_territoriale'|'a_verifier',
    'label': str, 'detail': str, ['herite_de': str]}. Mémoïsé par process (lru_cache) — le
    tri tendance renouvelle la liste à chaque clic, le texte d'une licence ne change pas.
    """
    lid = (license_id or '').strip().lower()
    propre = None if lid in _SAFE_LICENSES else _analyze_license_text(hf_id, lid)
    if propre and propre['verdict'] != 'a_verifier':
        return propre          # un verdict territorial PROPRE prime sur l'héritage
    bases = base_model if isinstance(base_model, (list, tuple)) else ([base_model] if base_model else [])
    if _profondeur < 2:        # un dérivé de dérivé remonte d'un cran, pas à l'infini
        for base in bases:
            base = str(base or '').strip()
            if not base or base.lower() == (hf_id or '').lower():
                continue
            # La licence du modèle de base n'est pas connue ici : son texte est lu.
            v = analyze_license(base, '', None, _profondeur + 1)
            if v and v['verdict'] != 'a_verifier':
                return {'verdict': v['verdict'],
                        'label': f"{v['label']} (modèle de base)",
                        'detail': f"hérité de {base} — un dérivé reste un « Model Derivative » "
                                  f"soumis à l'accord amont, quel que soit son propre tag "
                                  f"({lid or '?'}). {v['detail']}",
                        'herite_de': base}
    return propre


@lru_cache(maxsize=256)
def _analyze_license_text(hf_id: str, lid: str):
    import re

    import requests
    try:
        from huggingface_hub import HfApi, hf_hub_url
        siblings = HfApi().model_info(hf_id).siblings or []
        fichiers = [s.rfilename for s in siblings
                    if 'licen' in s.rfilename.lower() and '/' not in s.rfilename]
        if not fichiers:
            return {'verdict': 'a_verifier', 'label': 'licence à vérifier',
                    'detail': f"licence « {lid or '?'} » sans fichier LICENSE lisible "
                              "dans le dépôt — lire la card avant d'installer"}
        texte = requests.get(hf_hub_url(hf_id, fichiers[0]),
                             timeout=(5, 20)).text.lower()
        m = re.search(r'excluded\s+territor|restricted\s+territor', texte)
        if not m:
            # Filet plus large : « european union » cité dans un contexte d'exclusion.
            for hit in re.finditer(r'european union', texte):
                fenetre = texte[max(0, hit.start() - 300):hit.start() + 300]
                if 'exclud' in fenetre or 'prohibit' in fenetre or 'not apply' in fenetre:
                    m = hit
                    break
        if m:
            i = m.start()
            fenetre = texte[max(0, i - 400):i + 600]
            extrait = ' '.join(texte[max(0, i - 120):i + 240].split())
            ue = 'european union' in fenetre
            return {
                'verdict': 'exclusion_ue' if ue else 'restriction_territoriale',
                'label': 'UE EXCLUE par la licence' if ue else 'restriction territoriale',
                'detail': f'« …{extrait}… »',
            }
        return {'verdict': 'a_verifier', 'label': 'licence à vérifier',
                'detail': f"licence non standard ({lid or '?'}) — aucun marqueur "
                          "territorial détecté ; lire le texte avant d'installer"}
    except Exception as e:
        logger.debug("[analyze_license] %s illisible : %s", hf_id, e)
        return {'verdict': 'a_verifier', 'label': 'licence à vérifier',
                'detail': f"texte de licence illisible ({lid or '?'})"}



def install_options(cand) -> dict:
    """
    Options d'installation EXPLICITES d'un candidat HF : poids pleins + variantes quantisées,
    chacune avec son poids disque — l'information à montrer AVANT d'installer, pour que
    l'utilisateur choisisse en connaissance de cause (demande Fabien 2026-08-27 : le juge
    évaluait la faisabilité sur les variantes quantisées, mais l'installation tirait les
    poids pleins du dépôt canonique — 54 Go inexploitables sur 24 Go de VRAM).

    Un dépôt GGUF porte souvent PLUSIEURS niveaux de quantisation : l'option descend alors au
    FICHIER (une ligne par .gguf, la taille du fichier ≈ la VRAM nécessaire), et l'installation
    se fera par `allow_patterns` — jamais le dépôt entier. Les relevés (1 requête réseau par
    variante) sont PERSISTÉS dans `extra_info['prospect']['quant_variants']` : payés une fois.

    Retourne {'choice': bool, 'options': [{ref, file, label, disk_gb, vram_note, downloads,
    kind}]} — liste plate, prête pour l'UI.
    """
    prospect = dict((cand.extra_info or {}).get('prospect') or {})
    if (prospect.get('spec') or {}).get('kind') != 'hf':
        return {'choice': False, 'options': []}

    by_ollama = _ollama_runs_task(_candidate_task(cand))
    # Le dépôt du candidat EST un dépôt GGUF (une recherche ciblée en propose : « PaddleOCR-VL-1.6 »
    # a écrit `mradermacher/PaddleOCR-VL-1.6-GGUF`, 2026-10-11) et sa tâche est servie par Ollama :
    # ses PROPRES fichiers sont les choix, par Ollama. Ses « poids pleins » par le Hub tiraient le
    # dépôt ENTIER (4,1 Go, toutes les quantifications) vers un dossier que rien ne lit.
    own_gguf = prospect.get('own_gguf') if by_ollama else []
    a_persister = False
    if by_ollama and (own_gguf is None or (own_gguf and 'own_projector' not in prospect)):
        repo_files = _siblings(cand.hf_id)
        own_gguf = _gguf_files(repo_files)
        if repo_files is not None:          # injoignable : on réessaiera, rien n'est figé
            prospect['own_gguf'] = own_gguf
            prospect['own_projector'] = _has_projector(name for name, _ in repo_files)
            a_persister = True
    # Une tâche qui LIT des images (ses modalités, `default_inputs_for`) exige le projecteur de
    # vision dans le dépôt : Ollama le tire avec le modèle, et sans lui il installe un modèle AVEUGLE
    # (« image input is not supported »). Mesuré le 2026-10-11 : PaddleOCR-VL-1.6 et LightOnOCR-3-4B
    # installés depuis des dépôts de quantification sans `mmproj` ont rendu un texte vide.
    needs_projector = _needs_projector(cand)

    variants = prospect.get('quant_variants')
    if variants is None:
        a_persister = True
        variants = quantized_variants(cand.hf_id)
    enrichies = []
    for v in variants:
        v = dict(v)
        besoin_taille = v.get('disk_gb') is None
        besoin_fichiers = 'files' not in v
        # UNE requête pour les deux besoins : ils portaient sur le MÊME dépôt et partaient
        # chacun en HTTP (2 allers-retours PAR VARIANTE, sur une boucle). Les deux gardes
        # restent DISTINCTES — une variante peut n'avoir besoin que de l'une des deux.
        fichiers = _siblings(v['hf_id']) if (besoin_taille or besoin_fichiers) else None
        if besoin_taille:
            v['disk_gb'] = _poids_total_gb(fichiers)
            a_persister = True
        if besoin_fichiers:
            v['files'] = [{'file': nom, 'gb': round(taille / 1024 ** 3, 1)}
                          for nom, taille in _fichiers_de_poids(fichiers)]
            a_persister = True
        enrichies.append(v)
    if a_persister:
        prospect['quant_variants'] = enrichies
        info = dict(cand.extra_info or {})
        info['prospect'] = prospect
        cand.extra_info = info
        cand.save(update_fields=['extra_info'])

    if own_gguf:
        # Un dépôt GGUF n'a jamais de « poids pleins » ; sans projecteur exigé, aucune option.
        own_ok = prospect.get('own_projector') or not needs_projector
        options = [_gguf_option(cand.hf_id, f, by_ollama, None)
                   for f in sorted(own_gguf, key=lambda x: x['gb'], reverse=True)] if own_ok else []
    else:
        options = [{
            'ref': cand.hf_id, 'file': None,
            'label': f"Poids pleins — {cand.hf_id}",
            'disk_gb': cand.disk_gb or None,
            'vram_note': "ne tient pas en VRAM sans quantisation/offload"
                         if (cand.disk_gb or 0) > 24 else "",
            'downloads': None, 'kind': 'full',
        }]
    for v in enrichies:
        ggufs = [f for f in (v.get('files') or []) if _is_model_gguf(f['file'])]
        if ggufs and needs_projector \
                and not _has_projector(f['file'] for f in (v.get('files') or [])):
            continue                         # dépôt sans projecteur : un modèle aveugle
        if ggufs:
            # Une ligne PAR fichier gguf : c'est le fichier qu'on installe, pas le dépôt.
            for f in sorted(ggufs, key=lambda x: x['gb'], reverse=True):
                options.append(_gguf_option(v['hf_id'], f, by_ollama, v.get('downloads')))
        else:
            options.append({
                'ref': v['hf_id'], 'file': None,
                'label': v['hf_id'],
                'disk_gb': v.get('disk_gb'),
                'vram_note': "",
                'downloads': v.get('downloads'), 'kind': 'variant',
            })
    return {'choice': len(options) > 1, 'options': options}


def needs_variant_choice(cand) -> bool:
    """Le candidat n'a-t-il AUCUN choix par défaut ? — vrai quand ses options ne portent pas de
    « poids pleins » (un dépôt GGUF servi par Ollama), ou quand des fichiers exécutés par Ollama
    leur font concurrence : installer sans variante tirerait alors, en silence, ce que rien ne lit
    peut-être. `request_install` refuse ce cas et renvoie aux options."""
    options = install_options(cand).get('options') or []
    own_gguf = ((cand.extra_info or {}).get('prospect') or {}).get('own_gguf')
    # Des fichiers EXÉCUTÉS PAR OLLAMA existent à côté des poids pleins : le défaut n'est plus
    # évident, on choisit (fil n° 42, 2026-10-11 — « installe PaddleOCR-VL-1.6 » sans variante a
    # tiré 1,8 Go de poids pleins, une architecture que notre transformers ne sait pas lire, alors
    # que le GGUF officiel par Ollama était proposé). La page ouvre déjà ce choix (`choice`).
    by_ollama_offered = any(o.get('driver') == 'ollama' for o in options)
    return bool(own_gguf) or by_ollama_offered \
        or (bool(options) and not any(o.get('kind') == 'full' for o in options))


def _needs_projector(cand) -> bool:
    """La tâche du candidat est servie par Ollama ET lit des images : un GGUF ne s'installe que
    depuis un dépôt qui porte son projecteur de vision."""
    from ..models import default_inputs_for
    task = _candidate_task(cand)
    return _ollama_runs_task(task) and 'image' in (default_inputs_for(task).get('modalities') or [])


def _has_projector(names) -> bool:
    """Le dépôt porte-t-il un projecteur de vision (`mmproj`) ?"""
    return any('mmproj' in str(n).lower() and str(n).lower().endswith('.gguf') for n in names)


def _is_model_gguf(name: str) -> bool:
    """Un fichier GGUF de MODÈLE. Le projecteur de vision (`mmproj`) n'est pas une variante :
    le proposer comme fichier à installer seul était faux (relevé le 2026-10-10 sur
    PaddleOCR-VL-1.6 : trois `mmproj` listés comme des niveaux de quantification)."""
    low = name.lower()
    return low.endswith('.gguf') and 'mmproj' not in low


def _gguf_files(repo_files) -> list:
    """`[{file, gb}]` des GGUF de modèle d'un inventaire `_siblings` — dérivation pure."""
    return [{'file': name, 'gb': round(size / 1024 ** 3, 1)}
            for name, size in (repo_files or []) if _is_model_gguf(name)]


def _gguf_option(repo: str, f: dict, by_ollama: bool, downloads) -> dict:
    """UNE option d'installation par fichier GGUF : c'est le fichier qu'on installe, pas le dépôt."""
    return {
        'ref': repo, 'file': f['file'],
        'label': f"{repo} — {f['file']}" + (" (par Ollama)" if by_ollama else ""),
        'disk_gb': f['gb'],
        'vram_note': f"VRAM ≈ {f['gb']:.1f} Go (+ marge de contexte)",
        'downloads': downloads, 'kind': 'variant_file',
        'driver': 'ollama' if by_ollama else 'hf',
    }


def spec_for_choice(cand, variant_ref: str, variant_file: str | None) -> dict | None:
    """
    Le SPEC d'installation qui respecte le choix validé par l'utilisateur, ou None si le choix
    ne correspond à aucune option connue (on n'installe jamais un dépôt non proposé).

    La famille de dossier reste celle du modèle CANONIQUE (`cand.name`) : les poids d'une
    variante vivent sous `models/<cat>/<famille>/models--org--variante/` — regroupés avec les
    poids pleins qu'ils remplacent, désinstallables l'un comme l'autre.
    """
    prospect = (cand.extra_info or {}).get('prospect') or {}
    base = prospect.get('spec') or {}
    if base.get('kind') != 'hf' or not variant_ref:
        return None
    own_gguf = {f['file'] for f in (prospect.get('own_gguf') or [])}
    if variant_ref == cand.hf_id and not variant_file:
        # Poids pleins : le spec d'origine, inchangé — sauf pour un dépôt GGUF servi par Ollama,
        # qui n'en a pas (`install_options` ne les propose pas).
        return None if own_gguf else dict(base)
    if variant_ref == cand.hf_id:
        files = own_gguf                       # un fichier du dépôt du candidat lui-même
        projector = bool(prospect.get('own_projector'))
    else:
        v = {x['hf_id']: x for x in (prospect.get('quant_variants') or [])}.get(variant_ref)
        if v is None:
            return None
        files = {f['file'] for f in (v.get('files') or [])}
        projector = _has_projector(files)
    if variant_file and variant_file not in files:
        return None
    if variant_file and variant_file.lower().endswith('.gguf') and not projector \
            and _needs_projector(cand):
        return None                            # un modèle aveugle : jamais installé
    if variant_file and variant_file.lower().endswith('.gguf') \
            and _ollama_runs_task(_candidate_task(cand)):
        # Un GGUF dont la TÂCHE est exécutée par le moteur Ollama (un backend la sert,
        # `backend_for_engine('ollama', task)` — l'OCR par `GlmOcrBackend`) s'installe PAR OLLAMA :
        # `ollama pull hf.co/<dépôt>[:<quantification>]`, la branche Ollama d'`install_candidate`.
        # Ollama tire lui-même le projecteur de vision et l'exécute ; téléchargé seul par le Hub,
        # le fichier n'aurait été lu par rien (2026-10-10, PaddleOCR-VL, Chandra, LightOnOCR-3 —
        # architectures absentes de notre transformers, servies par Ollama comme Qwen 3.5/3.6).
        quant = _gguf_quant(variant_file)
        return {'kind': 'ollama', 'ref': f"hf.co/{variant_ref}" + (f":{quant}" if quant else ''),
                'task': base.get('task') or _candidate_task(cand),
                'base_hf_id': _canonical_repo(cand),
                'note': f"variante GGUF par Ollama, choisie par l'utilisateur : {variant_ref} / "
                        f"{variant_file}"}
    spec = dict(base)
    spec['ref'] = variant_ref
    spec['family'] = cand.name
    if variant_file:
        # Le fichier choisi + les petits fichiers de bord (config/tokenizer) — jamais les
        # autres niveaux de quantisation du dépôt.
        spec['allow_patterns'] = [variant_file, '*.json', '*.txt', 'tokenizer*']
    spec['note'] = (f"variante quantisée choisie par l'utilisateur : {variant_ref}"
                    + (f" / {variant_file}" if variant_file else ""))
    return spec


def _canonical_repo(cand) -> str:
    """Le modèle CANONIQUE d'un candidat : son propre dépôt, sauf pour un dépôt GGUF (ses fichiers
    sont ses options, `own_gguf`) dont la carte déclare un `base_model` — un seul : une fusion de
    plusieurs bases n'est le canonique d'aucune. Fil n° 41 : PaddleOCR et Chandra installés depuis
    leurs dépôts GGUF portaient le dépôt du publieur, et le banc ne pouvait pas les apparier."""
    prospect = (cand.extra_info or {}).get('prospect') or {}
    base = prospect.get('base_model')
    if isinstance(base, (list, tuple)):
        base = base[0] if len(base) == 1 else None
    if prospect.get('own_gguf') and isinstance(base, str) and '/' in base:
        return base
    return cand.hf_id or ''


def _candidate_task(cand) -> str:
    """La tâche d'un candidat : celle de son descripteur, sinon celle de sa ligne."""
    spec = ((cand.extra_info or {}).get('prospect') or {}).get('spec') or {}
    return spec.get('task') or (cand.capabilities or {}).get('task') or ''


def _ollama_runs_task(task: str) -> bool:
    """Un backend au moteur Ollama sert-il cette TÂCHE ? — la résolution commune
    (`backend_for_engine`), jamais une liste de tâches tenue ici."""
    if not task:
        return False
    from wama.common.backends.manager import backend_for_engine
    return backend_for_engine('ollama', '', task=task) is not None


#: Étiquette de quantification dans un nom de fichier GGUF (convention llama.cpp) : celle
#: qu'Ollama attend après `hf.co/<dépôt>:` pour choisir le fichier.
_GGUF_QUANT = re.compile(r'(?i)(?:^|[-_.])((?:I?Q\d+(?:_[0-9A-Z]+)*)|BF16|F16|F32)(?=\.gguf$)')


def _gguf_quant(filename: str) -> str:
    """`PaddleOCR-VL-1.6-q4_k_m.gguf` → `Q4_K_M` ; '' quand le nom n'en porte pas (dépôt à fichier
    unique : Ollama prend alors le fichier par défaut du dépôt)."""
    m = _GGUF_QUANT.search(filename or '')
    return m.group(1).upper() if m else ''


def _card_dict(card) -> dict:
    """La carte d'un dépôt (`ModelCardData` ou dict) en dict — {} si absente ou illisible."""
    if card is None:
        return {}
    try:
        return card.to_dict() if hasattr(card, 'to_dict') else dict(card)
    except Exception:
        return {}


def _installed_repos() -> set:
    """Dépôts Hugging Face des lignes INSTALLÉES (non proposées), en minuscules — par les DEUX
    identités de plateforme (`hf_id`, `platform_ref`) : un modèle découvert par scan disque n'a
    pas de `hf_id` mais peut porter un `platform_ref` posé par la provenance vérifiée.

    Une ligne DÉSINSTALLÉE n'en est plus (2026-10-11) : `uninstall_model` la garde pour son
    historique, marquée `uninstalled_at` — comptée ici, elle interdisait de reproposer le dépôt
    (`lightonai/LightOnOCR-3-4B`, `PaddlePaddle/PaddleOCR-VL-1.6` : « already » au lendemain de
    leur retrait)."""
    from wama.model_manager.models import AIModel, uninstalled_q
    rows = AIModel.objects.filter(is_proposed=False).exclude(uninstalled_q())
    have = {(h or '').lower() for h in rows.exclude(hf_id='').values_list('hf_id', flat=True)}
    have |= {ref.partition(':')[2].lower()
             for ref in rows.filter(platform_ref__startswith='huggingface:')
                            .values_list('platform_ref', flat=True)}
    have.discard('')
    return have


def _write_hf_candidate(hf_id, *, facts, refs_type, role, reason, description, note,
                        weight_gb=None, license=None, base_model=None, downloads=0, likes=0,
                        metric=None, kind='new', confidence=None, key=None, name=None,
                        extra=None) -> bool:
    """
    Écrit UN candidat Hugging Face — corps commun des balayages par tâche, de la recherche
    nommée, des classements et des successeurs (2026-10-10). Il vivait en deux copies
    (`seed_hf_candidates`, `seed_hf_search`) ; une troisième source l'aurait recopié.

    `facts` : ce que la carte dit (`card_facts`), éventuellement corrigé par l'appelant — un
    classement connaît la TÂCHE mieux que l'étiquette. `refs_type` : mémo du référentiel
    `concurrence`, partagé par un même passage. Rend True si le candidat est créé.
    """
    from wama.model_manager.models import AIModel

    from .prospect_ollama import PROPOSED_PREFIX, write_candidate

    task, model_type = facts['task'], facts['model_type']
    # Référentiel par MÉTIER, pas par catégorie : un texte→vidéo ne concourt pas contre SDXL
    # (2026-09-23). Identité courte : `name` porte parfois « — … ».
    if (model_type, task) not in refs_type:
        refs_type[(model_type, task)] = [
            (m.name or '').split('—')[0].strip()
            for m in AIModel.best_installed(model_type, task=task)]
    prospect = {'kind': kind, 'role': role, 'name': hf_id, 'reason': reason,
                'concurrence': refs_type[(model_type, task)],
                'downloads': downloads, 'likes': likes, 'metrique': metric,
                # Verdict de licence AFFICHÉ, jamais éliminatoire (Fabien 29/08) — None pour un
                # SPDX permissif ; mémoïsé, licences non standard seules. Hérité du
                # `base_model` déclaré quand le dérivé se dit permissif.
                'license_flag': analyze_license(hf_id, str(license or ''), base_model),
                # `task` dans le spec : la ligne INSTALLÉE en hérite (provenance) — la
                # découverte générique d'un snapshot HF ne sait pas la dire.
                'spec': {'kind': 'hf', 'ref': hf_id, 'category': model_type,
                         'task': task, 'note': note},
                # Le modèle CANONIQUE que la carte déclare (2026-10-11) : pour un dépôt de
                # quantification, c'est par lui que le banc apparie la ligne installée
                # (`spec_for_choice` → `base_hf_id`), pas par le dépôt du publieur.
                **({'base_model': base_model} if base_model else {}),
                **(extra or {})}
    return write_candidate(
        key or PROPOSED_PREFIX + f"hf:{hf_id}", nom=name or hf_id.split('/')[-1],
        model_type=model_type, source='huggingface', description=description,
        kind=kind, confidence=confidence, extra=prospect,
        hf_id=hf_id, license=str(license or '')[:64], platform_ref=f"huggingface:{hf_id}",
        disk_gb=weight_gb or 0.0,      # 0.0 = inconnu → la garde d'espace refusera (forçable)
        # La TÂCHE écrite sur la ligne : c'est elle qui donne un banc à un candidat
        # (`benchmark_sync._local_categories`) — sans elle, « hors catégorie ». Et les LANGUES
        # de la carte (2026-09-19) : le candidat porte les mêmes faits que la ligne installée.
        capabilities=facts['capabilities'],
    )


def _purge_hf_candidates(roles_ok, seen, kind: str = 'new'):
    """
    Purge CIBLÉE des candidats Hugging Face d'un passage : seuls ceux des RÔLES qui ont abouti
    (une source en échec réseau n'efface rien) et absents de `seen`. Rend (retirés, préservés).
    """
    from wama.model_manager.models import AIModel

    removed = preserved = 0
    if not roles_ok:
        return removed, preserved
    installed = _installed_repos()
    perimeter = AIModel.objects.filter(is_proposed=True, source='huggingface',
                                       proposal_kind=kind).exclude(model_key__in=seen)
    for m in perimeter:
        pr = (m.extra_info or {}).get('prospect', {})
        if (pr.get('role') or '') not in roles_ok:
            continue
        # Candidat dont le dépôt a été INSTALLÉ entre-temps : résolu par l'installation, on
        # purge MÊME évalué — la garde d'évaluation protège un travail encore utile, jamais une
        # proposition devenue sans objet (vécu Qwen3-ASR-1.7B, 2026-08-31 : installé côté
        # transcriber, la card « Nouveau » préservée continuait de proposer l'existant).
        if (m.hf_id or '').lower() in installed:
            m.delete()
            removed += 1
            continue
        # ⚠ NE JAMAIS PURGER UN CANDIDAT ÉVALUÉ (2026-08-19). Le tri « tendance » de HF bouge
        # en continu : d'un run à l'autre la liste retenue change presque entièrement (mesuré :
        # 32 créés / 32 purgés). Sans cette garde, chaque clic « Prospecter » DÉTRUISAIT les
        # évaluations LLM déjà payées (13 perdues au test). Un candidat évalué reste jusqu'à ce
        # qu'un humain le rejette — même règle que `write_candidate` à l'écriture.
        if pr.get('assess'):
            preserved += 1
            continue
        m.delete()
        removed += 1
    return removed, preserved


def seed_hf_candidates(limit: int = 12, min_downloads: int = 1000, tasks=None) -> dict:
    """
    Candidats `is_proposed` depuis la bibliothèque HuggingFace — pendant HF de la découverte
    par rôles de `prospect_ollama`. Né « génération image/vidéo » (2026-08-18, demande
    Fabien : « que Wan3 sorte ») puis étendu le même jour à TOUTE la table `HF_TASKS`
    (parole, détection, upscaling, musique, OCR).

    Réutilise : `prospect_hf` (découverte + flag « déjà chez nous » + licence),
    `write_candidate` (writer unique, garde de préservation des évaluations comprise),
    `AIModel.best_installed` (référentiel `concurrence` affiché sur la card),
    `_repo_weight_gb` (garde d'espace). Chaque candidat porte son **spec d'installation**
    (`install_from_spec`) — c'était le RESTE (3) du pipeline (« spec attaché »).

    Purge CIBLÉE comme dans prospect_ollama : uniquement le périmètre des tâches dont le
    balayage a ABOUTI (une panne réseau HF ne vide pas la liste).
    """
    from .prospect_ollama import PROPOSED_PREFIX

    crees = maj = 0
    vus: set = set()
    taches_ok: list = []
    refs_type: dict = {}
    table = {t: HF_TASKS[t] for t in (tasks or HF_TASKS) if t in HF_TASKS}

    for tache, regle in table.items():
        # Deux tris complémentaires : `downloads` = l'éprouvé, `trendingScore` = ce qui
        # MONTE (une famille publiée cette semaine — c'est LE tri qui la fait sortir avant
        # qu'elle domine les téléchargements). Dédupliqués via `vus`.
        candidats, ok_tache = [], False
        for tri in ('downloads', 'trendingScore'):
            res = prospect_hf(tache, limit=limit, min_downloads=(min_downloads
                              if tri == 'downloads' else 0), sort=tri)
            if res.get('ok'):
                ok_tache = True
                candidats.extend(res['candidates'])
            else:
                logger.warning("[prospect_hf_seed] %s (%s) indisponible : %s",
                               tache, tri, res.get('error'))
        if not ok_tache:
            continue
        taches_ok.append(tache)
        retenus = 0
        for c in candidats:
            if retenus >= regle['max']:
                break
            hf_id = c['hf_id']
            cand_key = PROPOSED_PREFIX + f"hf:{hf_id}"
            if c['have'] or cand_key in vus:
                continue
            if any(motif in hf_id.lower() for motif in _NOISE_MARKERS):
                continue    # dérivé (LoRA/quantif/repack), pas un modèle canonique
            poids = _repo_weight_gb(hf_id)   # un appel HTTP — candidats retenus seulement
            if poids is not None and poids < regle['poids_min_go']:
                continue    # sous le plancher de la tâche : LoRA/config, pas un modèle
            vus.add(cand_key)
            retenus += 1
            # Tâche et catégorie PAR CANDIDAT (tags de la carte), plus par tâche balayée :
            # un balayage `image-to-image` rend surtout des modèles d'ÉDITION.
            facts = card_facts(c.get('pipeline_tag') or tache, c.get('tags'),
                               {'language': c.get('language')})
            cree = _write_hf_candidate(
                hf_id, facts=facts, refs_type=refs_type, role=f"hf:{tache}",
                reason=f"tâche {tache} — non installé",
                description=(f"[{tache}] {c['downloads']} téléchargements, "
                             f"{c['likes']} ♥ — proposé par la bibliothèque HuggingFace."),
                note=f"prospection HF {tache}", weight_gb=poids,
                license=c.get('license'), base_model=c.get('base_model'),
                downloads=c['downloads'], likes=c['likes'], metric=c.get('metrique'))
            crees += int(cree)
            maj += int(not cree)

    # Transition : les candidats du 18/08 portaient `generation:<t>` avant le passage au
    # préfixe générique `hf:<t>` — on purge les deux graphies du même périmètre.
    roles_ok = {f"hf:{t}" for t in taches_ok} | {f"generation:{t}" for t in taches_ok}
    supprimes, preserves = _purge_hf_candidates(roles_ok, vus)

    resume = {'created': crees, 'updated': maj, 'removed': supprimes,
              'preserved': preserves,      # évalués, sortis de la tendance : conservés
              'total': len(vus), 'tasks_ok': taches_ok}
    logger.info("[prospect_hf_seed] %s", resume)
    return resume


#: Candidats retenus par CLASSEMENT : les premiers non installés. Même règle que `HF_TASKS`
#: (`max`) et `MAX_PAR_ROLE` : une liste que personne ne lit ne vaut pas mieux qu'une vide.
BENCH_CANDIDATES_PER_CATEGORY = 3

#: Le rôle des candidats SUCCESSEURS — un seul périmètre de purge, toutes tâches confondues.
SUCCESSOR_ROLE = 'hf:successor'


#: Ratio poids publiés / poids quantifiés 4 bits pour un dépôt en 16 bits — le REPLI de
#: `_q4_size_gb` quand le Hub ne dit pas le nombre de paramètres. Un candidat de classement dont
#: même le Q4 dépasse la VRAM TOTALE n'est pas proposé — mesuré le 2026-10-10 : MDPBench place un
#: modèle de 180 milliards de paramètres et un LLM frontière dans ses trois premiers, qui auraient
#: pris les places de modèles exécutables. Le jury tranche ensuite la faisabilité fine.
Q4_WEIGHT_RATIO = 4.0


def _q4_size_gb(info, weight_gb):
    """Taille du modèle quantifié 4 bits (Go) : nombre de paramètres publié par le Hub ×
    octets d'un paramètre Q4 — `memory_manager.dtype_bytes`, la brique des précisions (pas un
    second barème) ; à défaut, le poids publié ÷ `Q4_WEIGHT_RATIO`. None si rien n'est connu."""
    from .memory_manager import dtype_bytes
    params = getattr(getattr(info, 'safetensors', None), 'total', None)
    if params:
        return params * dtype_bytes('Q4') / 1e9
    return weight_gb / Q4_WEIGHT_RATIO if weight_gb else None


def _gpu_total_gb() -> float:
    """VRAM de la carte : la mesure UNIQUE (`resource_governor.total_vram_gb`, qui n'ouvre pas de
    contexte CUDA dans le processus web), repli 24 Go sans GPU — le même que le jury."""
    from wama.common.services.resource_governor import total_vram_gb
    return total_vram_gb() or 24.0


class HubRateLimited(Exception):
    """Le Hub refuse encore (429) après l'attente qu'il demande : la passe s'arrête, et ce qu'elle
    n'a pas lu ne compte pas comme lu — rien n'est purgé sur une lecture interrompue."""


#: Attente maximale (s) après un 429 du Hub avant l'UNIQUE nouvelle tentative. Mesuré le
#: 2026-10-10 : la prospection complète lancée par l'assistant a reçu 429 sur CHAQUE dépôt des
#: classements, juste après les dizaines d'appels du balayage par tâche — sautés en silence, et le
#: classement passait pour lu (donc sa purge aurait vidé les candidats d'une passe précédente).
HUB_RETRY_MAX_WAIT_S = 30


def _hub_model_info(api, repo: str):
    """`api.model_info(repo)`, avec UNE nouvelle tentative après l'attente qu'un 429 demande
    (`Retry-After`, plafonnée) ; lève `HubRateLimited` si le refus persiste. Toute autre erreur
    (dépôt absent, privé) remonte telle quelle."""
    import time
    for attempt in (1, 2):
        try:
            return api.model_info(repo)
        except Exception as exc:
            response = getattr(exc, 'response', None)
            if getattr(response, 'status_code', None) != 429:
                raise
            if attempt == 2:
                raise HubRateLimited(repo) from exc
            try:
                wait = float((response.headers or {}).get('Retry-After') or 10)
            except (TypeError, ValueError, AttributeError):
                wait = 10.0
            time.sleep(min(max(wait, 1.0), HUB_RETRY_MAX_WAIT_S))


def _board_label(entry: dict) -> str:
    """Nom lisible d'un classement : le jeu pour un classement du Hub, sinon la source."""
    scale = entry.get('scale') or ''
    if scale.startswith('hf_bench:'):
        return scale.split(':')[1].rsplit('/', 1)[-1]
    return entry.get('source_label') or entry.get('source') or ''


def seed_benchmark_candidates(per_category: int = BENCH_CANDIDATES_PER_CATEGORY, tasks=None,
                              cache: str = 'read') -> dict:
    """
    Candidats `is_proposed` tirés des CLASSEMENTS (2026-10-10, demande de Fabien) : pour chaque
    banc rattaché à une tâche du catalogue, les premiers dépôts non installés.

    Ce que le balayage par étiquette ne peut pas faire, mesuré ce jour sur la tâche `ocr` : la
    prospection ne regardait que `image-to-text`, triée par popularité, et ne proposait aucun des
    sept premiers d'olmOCR-Bench — six sont des VLM étiquetés `image-text-to-text`. Ici la TÂCHE
    vient du banc (pas de l'étiquette) et le rang vient de la QUALITÉ mesurée ; la note a priori
    est donc connue dès la proposition (la synchro des bancs l'écrit sur la ligne proposée).

    Lit les classements par `benchmark_sync.leaderboard_repos` — mêmes sources, même cache que la
    synchro. Un dépôt déjà installé, déjà visé par un SUCCESSEUR ou de la même famille datée
    qu'un installé est sauté (`_sans_suffixe_date`, comme le balayage). Purge ciblée : les seuls
    classements LUS ce passage.
    """
    from huggingface_hub import HfApi

    from wama.model_manager.models import AIModel, model_type_for_task

    from .benchmark_sync import leaderboard_repos
    from .prospect_ollama import PROPOSED_PREFIX

    boards, reasons = leaderboard_repos(cache=cache)
    have = _installed_repos() | {
        (m.hf_id or '').lower() for m in AIModel.objects.filter(
            is_proposed=True, source='huggingface', proposal_kind='update').exclude(hf_id='')}
    have_family = {_sans_suffixe_date(h) for h in have}
    api = HfApi()
    created = updated = 0
    seen: set = set()
    boards_ok: list = []
    refs_type: dict = {}
    rate_limited = False
    for cat, board in boards.items():
        task = board['task']
        if tasks and task not in tasks:
            continue
        kept = 0
        for e in board['entries']:
            if kept >= per_category:
                break
            repo = e['repo']
            if repo in have or _sans_suffixe_date(repo) in have_family:
                continue
            if any(marker in repo for marker in _NOISE_MARKERS):
                continue    # dérivé (quantif, repack) : on propose le modèle canonique
            try:
                info = _hub_model_info(api, repo)    # casse canonique, carte, étiquettes
            except HubRateLimited:
                rate_limited = True
                logger.warning("[seed_benchmark] Hub en limite de débit (429) : passe arrêtée "
                               "au classement %s, rien n'est purgé au-delà", cat)
                break
            except Exception as exc:
                logger.info("[seed_benchmark] %s injoignable : %s", repo, exc)
                continue
            hf_id = info.id
            key = PROPOSED_PREFIX + f"hf:{hf_id}"
            if key in seen:
                kept += 1
                continue    # déjà proposé par un autre banc de la même tâche ce passage
            weight = _repo_weight_gb(hf_id)
            q4_gb = _q4_size_gb(info, weight)
            if q4_gb and q4_gb > _gpu_total_gb():
                continue    # même quantifié, ne tient pas sur le GPU de l'hôte
            kept += 1
            seen.add(key)
            card = getattr(info, 'card_data', None)
            cd = _card_dict(card)
            facts = card_facts(getattr(info, 'pipeline_tag', None),
                               getattr(info, 'tags', None) or (), card)
            # Le BANC dit le métier : un VLM classé sur olmOCR-Bench est proposé comme OCR, quoi
            # que dise son étiquette.
            facts = dict(facts, task=task,
                         model_type=model_type_for_task(task) or facts['model_type'],
                         capabilities=_task_capabilities(facts['capabilities'], task))
            label = _board_label(e)
            created_now = _write_hf_candidate(
                hf_id, facts=facts, refs_type=refs_type, role=f"bench:{cat}",
                reason=f"{e['rank']}ᵉ sur {e['population']} au classement {label} — non installé",
                description=(f"[{label}] {e['rank']}ᵉ sur {e['population']} "
                             f"({e['value']:g}) — proposé par le classement."),
                note=f"classement {label}", weight_gb=weight,
                license=cd.get('license'), base_model=cd.get('base_model'),
                downloads=getattr(info, 'downloads', 0) or 0,
                likes=getattr(info, 'likes', 0) or 0, metric=_metrique_declaree(card),
                extra={'leaderboard': {k: e.get(k) for k in (
                    'source', 'scale', 'rank', 'population', 'value', 'direction',
                    'provenance')} | {'category': cat, 'label': label}})
            created += int(created_now)
            updated += int(not created_now)
        if rate_limited:
            break           # ce classement n'a pas été lu jusqu'au bout : ni lui ni les suivants
        boards_ok.append(cat)

    removed, preserved = _purge_hf_candidates({f"bench:{c}" for c in boards_ok}, seen)
    summary = {'created': created, 'updated': updated, 'removed': removed,
               'preserved': preserved, 'total': len(seen), 'boards_ok': boards_ok,
               'rate_limited': rate_limited, 'unavailable': reasons}
    logger.info("[seed_benchmark] %s", summary)
    return summary


def hf_successor(repo: str, max_depth: int = 5, api=None):
    """
    `(chaîne, info du dernier)` des NOUVELLES VERSIONS qu'un auteur déclare sur la carte de son
    modèle (`new_version`, champ standard des cartes Hugging Face), ou `([], None)`.

    Exemple mesuré le 2026-10-10 : `allenai/olmOCR-7B-0225-preview` → `allenai/olmOCR-7B-0825`
    → `allenai/olmOCR-2-7B-1025`. C'est l'AUTEUR qui désigne le successeur : rien n'est déduit
    d'un nom. La chaîne s'arrête à une boucle, à `max_depth`, ou à un dépôt injoignable.
    """
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi()
    chain, info, current = [], None, repo
    visited = {repo.lower()}
    for _ in range(max_depth):
        info = _hub_model_info(api, current)
        nxt = _card_dict(getattr(info, 'card_data', None)).get('new_version')
        if isinstance(nxt, (list, tuple)):
            nxt = nxt[0] if nxt else None
        nxt = str(nxt or '').strip()
        if not nxt or nxt.lower() in visited:
            break
        visited.add(nxt.lower())
        chain.append(nxt)
        current = nxt
    if not chain:
        return [], None
    # Sorti par la profondeur, le dernier maillon n'a pas encore été lu.
    if info is None or info.id.lower() != chain[-1].lower():
        info = _hub_model_info(api, chain[-1])
    chain[-1] = info.id          # casse canonique
    return chain, info


def seed_hf_successors(workers: int = 8) -> dict:
    """
    Candidats de MISE À JOUR des modèles Hugging Face installés, désignés par leur auteur
    (`new_version`) — le pendant Hugging Face du « successeur de famille » d'Ollama
    (`prospect_ollama`), sur PREUVE comme lui (confiance 0,9).

    Jusqu'au 2026-10-10 un modèle Hugging Face n'avait AUCUNE mise à jour proposée
    (`install_candidate` : « un candidat HF est toujours `kind='new'` ») ; `update_checker` ne
    compare que des dates, ce qui dit « republié », jamais « remplacé par ». Le candidat porte
    `origin_key` (la ligne installée) et `cible` (le successeur) comme une MAJ Ollama, mais il
    n'entraîne AUCUN retrait : l'ancien reste installé (`replaced_model` ne vaut que pour Ollama).
    """
    from concurrent.futures import ThreadPoolExecutor

    from huggingface_hub import HfApi

    from wama.model_manager.models import AIModel

    from .prospect_ollama import PROPOSED_PREFIX

    rows = []
    for m in AIModel.objects.filter(is_proposed=False, is_downloaded=True).exclude(source='ollama'):
        ref = m.platform_ref or ''
        repo = m.hf_id or (ref.split(':', 1)[1] if ref.startswith('huggingface:') else '')
        if repo and '/' in repo:
            rows.append((m, repo))

    api = HfApi()

    def lookup(row):
        try:
            return row, hf_successor(row[1], api=api), None
        except Exception as exc:
            return row, ([], None), exc

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lookup, rows))
    reached = sum(1 for _, _, exc in results if exc is None)

    installed = _installed_repos()
    created = updated = 0
    seen: set = set()
    refs_type: dict = {}
    for (m, repo), (chain, info), _exc in results:
        if not chain or info is None or chain[-1].lower() in installed:
            continue
        successor = chain[-1]
        key = PROPOSED_PREFIX + m.model_key
        seen.add(key)
        card = getattr(info, 'card_data', None)
        cd = _card_dict(card)
        facts = card_facts(getattr(info, 'pipeline_tag', None),
                           getattr(info, 'tags', None) or (), card)
        # Un successeur exerce le MÊME métier que l'installé qu'il vise (règle d'Ollama).
        task = (m.capabilities or {}).get('task') or facts['task']
        facts = dict(facts, task=task, model_type=m.model_type,
                     capabilities=_task_capabilities(facts['capabilities'], task))
        created_now = _write_hf_candidate(
            successor, facts=facts, refs_type=refs_type, role=SUCCESSOR_ROLE,
            reason=f"la carte de {repo} désigne {chain[0]} comme nouvelle version",
            description=(f"Nouvelle version désignée par l'auteur : {successor} "
                         f"(remplace {repo})."),
            note=f"successeur de {repo}", weight_gb=_repo_weight_gb(successor),
            license=cd.get('license'), base_model=cd.get('base_model'),
            downloads=getattr(info, 'downloads', 0) or 0,
            likes=getattr(info, 'likes', 0) or 0, metric=_metrique_declaree(card),
            kind='update', confidence=0.9, key=key,
            extra={'origin_key': m.model_key, 'cible': successor, 'maj': 'successeur',
                   'chain': chain})
        created += int(created_now)
        updated += int(not created_now)

    # Un modèle dont la lecture a ÉCHOUÉ (429, réseau) garde le candidat qu'il avait : ne pas
    # l'avoir relu ne prouve pas que son successeur a disparu (2026-10-10, même leçon que les
    # classements). Aucun dépôt joint : rien n'est purgé du tout.
    seen |= {PROPOSED_PREFIX + m.model_key for (m, _repo), _r, exc in results if exc is not None}
    roles_ok = {SUCCESSOR_ROLE} if (reached or not rows) else set()
    removed, preserved = _purge_hf_candidates(roles_ok, seen, kind='update')
    summary = {'created': created, 'updated': updated, 'removed': removed,
               'preserved': preserved, 'total': created + updated, 'checked': len(rows),
               'reached': reached,
               'rate_limited': any(isinstance(exc, HubRateLimited) for *_x, exc in results)}
    logger.info("[seed_hf_successors] %s", summary)
    return summary


def enqueue_after_prospection() -> dict:
    """La suite de « Prospecter » : bancs tiers PUIS jury LLM, dans cet ordre (ex-
    `views._enqueue_after_prospect`, déplacée le 2026-10-10 pour être partagée avec l'assistant).

    • Les bancs s'enchaînent depuis le 2026-09-01 (décision Fabien) : purement réseau, et c'est
      le moment UTILE — les lignes `proposed:` qui viennent de naître n'ont pas encore de banc.
    • Le jury avait été DÉTACHÉ le 2026-08-19 : enchaîné sur l'Ollama hôte, il faisait tomber
      Windows à chaque prospection. Cause retenue : l'alimentation, remplacée le 21/09
      (`PROJECT_STATUS §NOTE 2026-09-21`) ; rebranché le 2026-09-23 à la demande de Fabien,
      derrière `PROSPECT_ASSESS_AUTO` et jamais sous `WAMA_GPU_SAFE_MODE`.
    • CHAÎNE et non deux `.delay()` : le jury LIT le banc dans son contexte
      (`prospect_agents._benchmark_line`). Lancés côte à côte, il jugeait des candidats encore
      sans banc. Chaque maillon garde sa route (bancs : `default` ; jury : `gpu`, palier basse).
    • Une passe de jury déjà vivante n'est pas doublée (même garde que le bouton).
    """
    from django.conf import settings as _settings

    from wama.common.services.resource_governor import gpu_safe_mode
    from wama.common.utils.task_progress import progression_en_cours

    from ..tasks import ASSESS_CACHE_KEY, assess_proposed_task, sync_benchmarks_task
    assess = (getattr(_settings, 'PROSPECT_ASSESS_AUTO', False) and not gpu_safe_mode()
              and not progression_en_cours(ASSESS_CACHE_KEY))
    # `cache='read'` (2026-10-10) : la prospection vient de lire les classements (même cache) ; tout
    # RELIRE ici réinterrogeait chaque source juste après les centaines d'appels de la prospection
    # — mesuré : le Hub (500 requêtes / 5 min) et Artificial Analysis (100 / jour) répondaient 429,
    # et les candidats OCR restaient sans note. La relecture complète reste celle de la nuit.
    try:
        if assess:
            # L'état TERMINÉ d'une passe précédente survit dans le cache (TTL) : le suivi
            # d'écran le lirait comme la fin de CELLE-CI avant même que le jury démarre.
            from django.core.cache import cache
            cache.delete(ASSESS_CACHE_KEY)
            (sync_benchmarks_task.si(cache='read') | assess_proposed_task.si()).apply_async()
        else:
            sync_benchmarks_task.delay(cache='read')
        return {'benchmarks_enqueued': True, 'assess_enqueued': bool(assess)}
    except Exception:
        # Broker indisponible : la prospection reste valable, les deux signaux attendront.
        logger.warning("suite de la prospection non enfilée", exc_info=True)
        return {'benchmarks_enqueued': False, 'assess_enqueued': False}


def run_prospection() -> dict:
    """
    Le verbe « Prospecter » — corps UNIQUE du bouton du model manager et de l'outil
    `prospect_models` de l'assistant (2026-10-10). Rend le résumé, ne lève pas pour une source.

    Une source par périmètre : une panne de l'une ne fait échouer ni Ollama ni les autres. Dans
    CET ordre : Ollama, puis les successeurs (un dépôt visé par une MAJ n'est pas reproposé en
    « nouveau »), les CLASSEMENTS, puis le balayage par tâche (`HF_TASKS`). Les classements
    passent AVANT le balayage depuis le 2026-10-10 : c'est la source la plus utile, et les
    dizaines d'appels du balayage épuisaient le quota du Hub juste avant eux (429 sur chaque
    dépôt, mesuré). Le balayage saute un dépôt déjà au catalogue, propositions comprises
    (`prospect_hf`, « déjà chez nous ») : il ne réécrit pas un candidat de classement. Puis la
    suite en file (bancs tiers → jury).
    """
    from .prospect_ollama import prospect_ollama

    summary = prospect_ollama()
    for label, seed in (('hf_successors', seed_hf_successors),
                        ('benchmarks', seed_benchmark_candidates),
                        ('hf', seed_hf_candidates)):
        try:
            summary[label] = seed()
            summary['total'] = (summary.get('total') or 0) + summary[label]['total']
        except Exception:
            logger.warning("prospection %s en échec", label, exc_info=True)
            summary[label] = {'error': 'indisponible'}
    summary.update(enqueue_after_prospection())
    return summary


def seed_candidate_from_manifest(manifest: dict) -> dict:
    """
    Écrit/rafraîchit un CANDIDAT de prospection depuis un manifeste `model` — le chemin du
    rôle `scout` (wama-dev-ai) vers la route commune.

    Pourquoi ici et pas dans le script (2026-09-19, alignement des routes) : le scout
    déposait son manifeste dans `wama-dev-ai/outputs/`, d'où RIEN ne repartait — ses capacités
    jugées (model_type, task, composition) mouraient dans un fichier, et l'installation les
    redécouvrait depuis la carte. L'enrichissement doit se faire AVANT l'installation, sur le
    CANDIDAT, exactement comme le jugement de confiance : la ligne candidate est déjà un
    manifeste `model` (`extract_model` l'extrait), c'est donc le même objet des deux côtés.

    Ne décide rien : un candidat est une PROPOSITION, visible sur la page et rejetable d'un
    clic. La garde de `write_candidate` protège une évaluation LLM déjà payée.

    Retourne {'ok': True, 'model_key', 'created', 'task'} ou {'ok': False, 'error': …}.
    """
    from wama.model_manager.models import default_inputs_for

    from .prospect_ollama import PROPOSED_PREFIX, write_candidate

    manifest = manifest or {}
    if manifest.get('manifest_kind') != 'model':
        return {'ok': False, 'error': f"kind {manifest.get('manifest_kind')!r}, attendu 'model'"}
    body = manifest.get('body') or {}
    identity = body.get('identity') or {}
    hf_id = (identity.get('hf_id') or '').strip()
    source = identity.get('source')
    # Deux sources savent se proposer ainsi : un dépôt HuggingFace (`hf_id`) et une VERSION
    # GitHub (`platform_ref` github:…/releases/tag/…, 2026-10-07 — pilote `github`).
    if not ((source == 'huggingface' and hf_id) or source == 'github'):
        return {'ok': False,
                'error': "seul un manifeste de modèle HuggingFace (identity.hf_id + "
                         "source='huggingface') ou d'une version GitHub (source='github') "
                         "se propose ainsi"}
    model_type = (identity.get('model_type') or '').strip()
    if not model_type:
        return {'ok': False, 'error': "identity.model_type manquant : le candidat n'aurait ni "
                                      "catégorie d'installation ni référentiel de concurrence"}

    caps = dict(body.get('capabilities') or {})
    task = (caps.get('task') or '').strip()
    if task:
        # Ce que la tâche IMPLIQUE, posé sans écraser ce que le manifeste déclare déjà.
        caps = {**default_inputs_for(task), **caps}
    disk_gb = float((body.get('resources') or {}).get('disk_gb') or 0.0)
    if source == 'github':
        # La version se lit dans `platform_ref`, le fichier dans le composant ; l'empreinte est
        # lue sur l'API ou MESURÉE (`pinned_github_asset`) — jamais prise du manifeste.
        driver = github_spec_from_manifest(manifest)
        if driver.get('error'):
            return {'ok': False, 'error': driver['error']}
        ref = driver['ref']
        cand_key = PROPOSED_PREFIX + f"github:{ref}"
        spec_head = (('kind', 'github'), ('ref', ref), ('asset', driver['asset']),
                     ('sha256', driver['sha256']))
        platform_ref = identity.get('platform_ref')
        disk_gb = disk_gb or round(driver['size'] / 1024 ** 3, 4)
        name = ref.partition(':')[2]
    else:
        ref = hf_id
        cand_key = PROPOSED_PREFIX + f"hf:{hf_id}"
        spec_head = (('kind', 'hf'), ('ref', hf_id))
        platform_ref = identity.get('platform_ref') or f"huggingface:{hf_id}"
        name = hf_id.split('/')[-1]
    license_ = str(identity.get('license') or '')[:64]
    created = write_candidate(
        cand_key, nom=manifest.get('name') or name, model_type=model_type,
        source=source,
        description=(identity.get('description_short') or manifest.get('description')
                     or f"[{task or model_type}] Proposé par le rôle scout.")[:500],
        kind='new', confidence=None,
        extra={'kind': 'new', 'role': f"scout:{task or model_type}", 'name': ref,
               'reason': "manifeste produit par le rôle scout (wama-dev-ai)",
               # Le spec porte la COMPOSITION quand le manifeste en déclare une : c'est elle
               # qui fait tirer le jeu de poids COHÉRENT au lieu du dépôt entier.
               # Et les CAPACITÉS jugées (2026-10-06, Swin2SR) : le candidat est supprimé à
               # l'installation, la ligne installée ne recevait que la tâche — son facteur
               # `scale: 4` se perdait, et le tirage « auto » de l'enhancer filtre dessus.
               # La LICENCE voyage aussi pour une version GitHub : sa provenance n'a pas de
               # carte à relire à l'installation (`identity_for_spec`).
               'spec': {k: v for k, v in (
                   *spec_head, ('category', model_type),
                   ('task', task), ('composition', body.get('composition')),
                   ('capabilities', caps),
                   ('license', license_ if source == 'github' else ''),
                   ('note', 'manifeste scout')) if v}},
        capabilities=caps,
        hf_id=hf_id, license=license_,
        platform_ref=platform_ref,
        disk_gb=disk_gb,
    )
    return {'ok': True, 'model_key': cand_key, 'created': created, 'task': task}


def seed_yolo_candidate(name: str) -> dict:
    """
    Candidat de prospection pour des poids YOLO OFFICIELS demandés PAR LEUR NOM.

    L'installation VISION directe (`{'source': 'yolo', 'name': …}` → `install_from_spec`) était
    la seconde entrée NUE de l'endpoint : elle sautait la garde d'espace ET la tâche de fond,
    parce qu'elle n'avait pas de candidat où s'accrocher. Alignée sur la route commune
    (2026-09-19) : un nom demandé devient un CANDIDAT porteur de son spec, de sa tâche et de
    son poids, que `request_install` installe comme n'importe quel autre.

    Rien n'est réinventé ici : la validation du nom et la cible viennent du driver lui-même
    (`pull_yolo_weights(dry_run=True)` — un nom arbitraire, une URL ou un chemin sont refusés
    là-bas), la tâche de `yolo_task_of`, et le poids de `weight_for_spec` — le dispatch COMMUN
    par `kind`, jumeau de `identity_for_spec`, et non une fonction de poids par source.

    Retourne {'ok': True, 'model_key', 'created', 'task'} ou {'ok': False, 'error': …}.
    """
    from wama.model_manager.models import default_inputs_for

    from .model_installer import pull_yolo_weights, weight_for_spec, yolo_task_of
    from .prospect_ollama import PROPOSED_PREFIX, write_candidate
    from .provenance import identity_for_spec

    ref = (name or '').strip()
    verdict = pull_yolo_weights(ref, dry_run=True)
    if not verdict.get('ok'):
        return {'ok': False, 'error': verdict.get('error', 'nom de poids YOLO invalide')}

    base = ref[:-3] if ref.endswith('.pt') else ref
    task = yolo_task_of(base)
    cand_key = PROPOSED_PREFIX + f"yolo:{base}"
    # Le SPEC est écrit UNE fois et sert aux deux : il part sur le candidat, et c'est lui qu'on
    # pèse. Peser autre chose que ce qu'on va tirer est le défaut que le descripteur évite.
    spec = {'kind': 'yolo', 'ref': base, 'task': task, 'note': 'installation VISION par nom'}
    created = write_candidate(
        cand_key, nom=base, model_type='vision', source='yolo',
        description=f"[{task}] Poids officiels Ultralytics, demandés par leur nom.",
        kind='new', confidence=None,
        extra={'kind': 'new', 'role': f"yolo:{task}", 'name': base,
               'reason': "poids YOLO officiels — demande explicite", 'spec': spec},
        # La tâche se DÉDUIT du suffixe du nom (mécanique, jamais un jugement) et entraîne ses
        # modalités et entrées par défaut — le candidat porte donc les mêmes faits que la
        # ligne installée les portera.
        capabilities={'task': task, **default_inputs_for(task)},
        # L'identité que l'INSTALLATION posera (`provenance.identity_for_spec`), dérivée du même
        # spec : la ligne écrivait sa propre forme (`github:ultralytics/assets:<nom>`), dont la
        # page rendait `github.com/ultralytics/assets:<nom>` — une adresse qui n'existe pas.
        platform_ref=(identity_for_spec(spec) or {}).get('platform_ref', ''),
        disk_gb=weight_for_spec(spec) or 0.0,
    )
    return {'ok': True, 'model_key': cand_key, 'created': created, 'task': task}


#: Rôle d'un candidat Ollama écrit sur DEMANDE NOMMÉE (`seed_ollama_candidate`) : la purge de
#: `prospect_ollama` ne le retire pas — il n'appartient au périmètre d'aucun balayage.
NAMED_OLLAMA_ROLE = 'named'


def seed_ollama_candidate(name: str) -> dict:
    """
    Candidat de prospection pour un modèle Ollama demandé PAR SON NOM — le pendant de
    `seed_yolo_candidate` (décision de Fabien, 2026-10-11). `pull_model <nom>` tirait le modèle
    en direct (`pull_ollama_model`) : sans garde d'espace disque, sans tâche suivie, sans journal
    — le dernier écart nommé par `TheDriversStayInsideTheRouteTest`. Un nom demandé devient un
    CANDIDAT, que `request_install` installe comme ceux de la prospection par rôle.

    Rien n'est réinventé : l'existence vient du manifeste du registre (`ollama_registry.existe`,
    la vérification qui fait qu'on ne propose jamais un tag non tirable), le poids de
    `weight_for_spec` (kind `ollama`), la catégorie de `_type_ollama` (tâche inconnue → LLM, la
    règle de la découverte). La TÂCHE n'est pas supposée : la découverte la lit après
    installation, exactement comme après le tirage direct d'avant.

    Retourne {'ok': True, 'model_key', 'created'} — la clé de la LIGNE installée quand le modèle
    l'est déjà (`request_install` dit alors « déjà téléchargé ») —, ou {'ok': False, 'error'}.
    """
    from . import ollama_registry as reg
    from .model_installer import weight_for_spec
    from .model_registry import _type_ollama
    from .prospect_ollama import PROPOSED_PREFIX, _installes, write_candidate

    base, _, tag = (name or '').strip().partition(':')
    ref = f"{base}:{tag or 'latest'}"
    if not base:
        return {'ok': False, 'error': 'nom Ollama vide'}
    if ref in _installes():
        return {'ok': True, 'model_key': f"ollama:{ref}", 'created': False}
    cand_key = PROPOSED_PREFIX + f"ollama:{ref}"
    from wama.model_manager.models import AIModel
    if AIModel.objects.filter(model_key=cand_key, is_proposed=True).exists():
        # Déjà proposé (par un rôle, ou une demande précédente) : on le demande tel quel —
        # le réécrire effacerait son rôle et sa tâche.
        return {'ok': True, 'model_key': cand_key, 'created': False}
    if not reg.existe(base, tag or 'latest'):
        return {'ok': False,
                'error': f"« {ref} » n'est pas tirable du registre Ollama (manifeste absent, ou "
                         "registre injoignable)"
                         + (" — un GGUF du Hub se choisit par sa proposition Hugging Face, au "
                            "model manager" if base.startswith('hf.co/') else '')}
    spec = {'kind': 'ollama', 'ref': ref}
    created = write_candidate(
        cand_key, nom=ref, model_type=_type_ollama('').value,
        description="Modèle Ollama demandé par son nom.",
        kind='new', confidence=None,
        extra={'kind': 'new', 'role': NAMED_OLLAMA_ROLE, 'name': ref,
               'reason': "modèle Ollama — demande explicite"},
        disk_gb=weight_for_spec(spec) or 0.0,
    )
    return {'ok': True, 'model_key': cand_key, 'created': created}


# ── Versions GitHub (pilote `github`, 2026-10-07) ─────────────────────────────────────────────
# Le pendant de ce que `HfApi().model_info` donne au scout pour un dépôt HF : la version lue sur
# l'API GitHub — c'est l'usage DÉCLARÉ de la source `github_api` (« Liste des releases —
# résolution de la version d'un poids »), qui n'avait jusqu'ici aucun lecteur pour cela.
# Même client que `benchmark_sync._mteb_index` (en-tête, jeton facultatif de la source
# `github_api` : le quota anonyme est de 60 appels/h).

def github_release(ref: str):
    """La version `owner/repo:tag` telle que l'API GitHub la publie (dict), `{}` si elle
    n'existe pas (404), None si l'API n'a pas répondu — « l'un est une panne, l'autre un fait »
    (la distinction de `_siblings`)."""
    import requests

    from wama.common.external_sources import api_key, base_url, proxies_for

    from .model_installer import github_release_of
    repo, tag = github_release_of(ref)
    if not (repo and tag):
        return {}
    headers = {'Accept': 'application/vnd.github+json'}
    token = api_key('github_api').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        r = requests.get(f"{base_url('github_api')}/repos/{repo}/releases/tags/{tag}",
                         headers=headers, proxies=proxies_for('github_api'), timeout=30)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("[github] version %s illisible : %s", ref, e)
        return None


#: Ligne « License: … » du texte d'une version — la seule licence qu'une version GitHub porte
#: (le dépôt peut en publier des centaines sous des licences différentes : `Phhofm/models`).
_RELEASE_LICENSE_RE = re.compile(r'^\s*\**\s*licen[sc]e\s*\**\s*:\s*\**\s*(.+?)\s*$',
                                 re.IGNORECASE | re.MULTILINE)


def github_release_license(release: dict) -> str:
    """Licence DITE par le texte de la version (« License: CC BY 4.0 »), sinon '' — jamais
    supposée depuis la licence du dépôt, qui n'est pas celle du modèle."""
    m = _RELEASE_LICENSE_RE.search((release or {}).get('body') or '')
    return re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', m.group(1)).strip()[:64] if m else ''


#: Ligne « Scale: 4 » du texte d'une version — le facteur DÉCLARÉ d'un agrandisseur. Le pendant,
#: pour une version, des `SCALE_KEYS` qu'un `config.json` HF porte (`role_utils.enforce_task_facts`).
_RELEASE_SCALE_RE = re.compile(r'^\s*\**\s*scale\s*\**\s*:\s*\**\s*(\d+)\s*[x×]?\s*$',
                               re.IGNORECASE | re.MULTILINE)


def github_release_scale(release: dict):
    """Facteur que le texte de la version DÉCLARE (« Scale: 4 »), sinon None — jamais déduit du
    nom (« 4x… ») : le silence vaut mieux qu'une convention supposée."""
    m = _RELEASE_SCALE_RE.search((release or {}).get('body') or '')
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def pinned_github_asset(ref: str, asset: str, release: dict = None) -> dict:
    """{'asset', 'size', 'sha256', 'measured'} de l'asset d'une version, ou {'error'}.

    L'empreinte vient de l'API (`digest`) quand elle la publie. Mesuré le 2026-10-07 : 7 versions
    sur 100 de `Phhofm/models` seulement la portent (SPAN, avril 2024, non). Sinon elle se MESURE
    — le fichier est téléchargé dans un dossier jetable par la primitive commune, puis haché
    (`measured=True`). Une empreinte qu'on n'a ni lue ni mesurée n'est jamais écrite : c'est
    elle que l'installation exigera.
    """
    import tempfile

    from .model_installer import download_asset, github_asset_url
    release = github_release(ref) if release is None else release
    if release is None:
        return {'error': f"API GitHub injoignable pour {ref}"}
    found = next((a for a in (release.get('assets') or []) if a.get('name') == asset), None)
    if found is None:
        names = sorted(a.get('name', '') for a in (release.get('assets') or []))
        return {'error': f"asset {asset!r} absent de la version {ref} (fichiers : {names})"}
    digest = str(found.get('digest') or '')
    if digest.startswith('sha256:'):
        return {'asset': asset, 'size': int(found.get('size') or 0),
                'sha256': digest[len('sha256:'):].lower(), 'measured': False}
    from wama.common.external_sources import proxies_for
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, asset)
        res = download_asset(github_asset_url({'ref': ref, 'asset': asset}), target,
                             proxies=proxies_for('github'))
        if not res.get('ok'):
            return {'error': f"empreinte non mesurable : {res.get('error')}"}
        return {'asset': asset, 'size': os.path.getsize(target),
                'sha256': res['sha256'], 'measured': True}


def github_spec_from_manifest(manifest: dict) -> dict:
    """Descripteur `github` d'un manifeste `model` de source `github`, empreinte ÉPINGLÉE —
    ou {'error'}. La version se lit dans `identity.platform_ref`, le fichier dans le composant
    `model` (un NOM, pas un motif : une version publie des variantes fp32/fp16, on en tire une)."""
    from .model_installer import github_ref_of_platform, github_spec_error
    body = (manifest or {}).get('body') or {}
    identity = body.get('identity') or {}
    ref = github_ref_of_platform(identity.get('platform_ref'))
    if not ref:
        return {'error': "identity.platform_ref n'est pas une version GitHub "
                         "(github:owner/repo/releases/tag/<tag>)"}
    comps = [c for c in ((body.get('composition') or {}).get('components') or [])
             if isinstance(c, dict) and c.get('pattern')]
    if len(comps) != 1 or any(ch in comps[0]['pattern'] for ch in '*?[/'):
        return {'error': "composition.components doit nommer UN fichier de la version "
                         "(le composant `model`)"}
    pinned = pinned_github_asset(ref, comps[0]['pattern'])
    if pinned.get('error'):
        return pinned
    spec = {'kind': 'github', 'ref': ref, 'asset': pinned['asset'], 'sha256': pinned['sha256'],
            'category': identity.get('model_type') or '', 'size': pinned['size']}
    error = github_spec_error(spec)
    return {'error': error} if error else {**spec, 'sha256_measured': pinned['measured']}


def _rule_for_task(task):
    """La règle du balayage (`HF_TASKS`) dont la catégorie d'installation est celle de `task`, ou
    None — une tâche qu'aucune entrée ne couvre n'invente pas de catégorie (le captioning d'un VLM
    reste chez le describer)."""
    from wama.model_manager.models import model_type_for_task

    category = model_type_for_task(task) if task else None
    return next((r for r in HF_TASKS.values() if r['category'] == category), None) \
        if category else None


def named_repo(query: str):
    """Le dépôt HF qu'une requête DÉSIGNE — URL de page (`https://huggingface.co/org/nom`, avec ou
    sans schéma, sous-chemins `/tree/main`… tolérés) ou identifiant `org/nom` —, sinon None.

    ⚠ POURQUOI (2026-09-29) : trois recherches collées depuis la barre d'adresse
    (`https://huggingface.co/SupraLabs/Supra2-IMG`) rendaient 0 résultat — HF cherchait la chaîne
    ENTIÈRE dans les noms de dépôts. Un utilisateur qui colle l'adresse du modèle désigne un dépôt,
    il ne fait pas une recherche plein texte.
    """
    import re
    q = (query or '').strip()
    m = re.match(r'^(?:https?://)?(?:www\.)?huggingface\.co/([\w.-]+/[\w.-]+)', q, re.I)
    if m:
        return m.group(1)
    return q if re.fullmatch(r'[\w.-]+/[\w.-]+', q) else None


def seed_hf_search(query: str, limit: int = 10, max_retenus: int = 5) -> dict:
    """
    Prospection CIBLÉE : cherche `query` dans les noms de dépôts HF (toutes tâches de
    `HF_TASKS` confondues) et écrit les résultats en candidats `is_proposed` — le pendant
    UI du drapeau `--search` de `prospect_models` (leçon 2026-08-04 : un top par
    téléchargements ne rend jamais les spécialisés ; un modèle NOMMÉ par l'utilisateur ne
    peut pas non plus y entrer — plafond top-3/tâche, vécu Audio8-TTS le 2026-08-31).

    Différences ASSUMÉES avec le balayage `seed_hf_candidates` :
      • une seule requête `search=` SANS filtre de tâche — l'utilisateur ne connaît pas le
        `pipeline_tag` ; la tâche est lue sur chaque résultat et doit figurer dans
        `HF_TASKS` (un tag hors périmètre n'invente pas de catégorie d'installation) — sauf
        pour un dépôt DÉSIGNÉ, jugé sur la tâche que SA carte déclare (`_rule_for_task`) ;
      • `_NOISE_MARKERS` non appliqués : chercher « kokoro onnx » est un choix EXPLICITE —
        la garde anti-dérivés protège un listing subi, pas une demande nommée ;
      • AUCUNE purge : une recherche AJOUTE des candidats, elle ne redessine pas la liste ;
      • un dépôt DÉSIGNÉ échappe au plancher de poids de sa tâche (2026-09-29) — cf. `named`
        ci-dessous.
    """
    query = (query or '').strip()
    if not query:
        return {'ok': False, 'error': 'requête vide'}
    named = named_repo(query)
    search = named or query
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        models = list(api.list_models(
            search=search, sort='downloads', limit=limit,
            expand=['downloads', 'likes', 'pipeline_tag', 'cardData']))
        # Le dépôt désigné passe EN TÊTE, même si la recherche plein texte ne le rend pas (ou le
        # rend au-delà de `limit`) : c'est lui qu'on a demandé.
        if named:
            models = [m for m in models if m.id.lower() != named.lower()]
            try:
                models.insert(0, api.model_info(named))
            except Exception as e:
                return {'ok': False, 'error': f"dépôt {named} injoignable : {type(e).__name__}: {e}"}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}

    def _designated(repo_id: str) -> bool:
        """Le dépôt a-t-il été NOMMÉ par la requête ? Son id entier (URL, `org/nom`), ou son nom
        seul quand la requête est ce nom (« Supra2-IMG » désigne `SupraLabs/Supra2-IMG`)."""
        rid = repo_id.lower()
        return rid == (named or '').lower() or rid.rsplit('/', 1)[-1] == query.lower()

    # « Déjà chez nous » — mêmes deux identités que prospect_hf, mais lignes INSTALLÉES
    # seulement : un candidat déjà proposé doit pouvoir être RAFRAÎCHI par une nouvelle
    # recherche, pas compté comme possédé par sa propre ligne.
    have = _installed_repos()

    crees = maj = deja = ignores = 0
    retenus: list = []
    refs_type: dict = {}
    for m in models:
        if len(retenus) >= max_retenus:
            break
        tache = getattr(m, 'pipeline_tag', None)
        regle = HF_TASKS.get(tache or '')
        if regle is None and _designated(m.id):
            # Un dépôt NOMMÉ dont l'étiquette est hors balayage entre si SA carte dit une tâche
            # que le balayage sait installer (2026-10-11) : `lightonai/lightonocr-3-1b` publie
            # `image-text-to-text` et tague `ocr` — `card_facts` en fait un OCR, comme pour un
            # candidat de classement ; « lightonai/lightonocr-3-1b » rendait pourtant 0 résultat.
            regle = _rule_for_task(card_facts(tache, getattr(m, 'tags', None) or ())['task'])
        if regle is None:
            ignores += 1
            continue
        if m.id.lower() in have:
            deja += 1
            continue
        poids = _repo_weight_gb(m.id)   # un appel HTTP — candidats retenus seulement
        # Le plancher écarte les LoRA et les dépôts de config d'un listing SUBI. Il ne s'applique
        # pas au dépôt que l'utilisateur a NOMMÉ : mesuré le 2026-09-29, « Supra2-IMG » écartait
        # l'OFFICIEL (`SupraLabs/Supra2-IMG`, 104 M paramètres, 0,4 Go < 1 Go) et ne laissait que
        # deux reconditionnements tiers — dont l'un a été installé à sa place.
        if poids is not None and poids < regle['poids_min_go'] and not _designated(m.id):
            ignores += 1                 # sous le plancher : LoRA/config, pas un modèle
            continue
        dl = getattr(m, 'downloads', 0) or 0
        likes = getattr(m, 'likes', 0) or 0
        carte = getattr(m, 'card_data', None)
        cd = _card_dict(carte)
        cree = _write_hf_candidate(
            m.id, facts=card_facts(getattr(m, 'pipeline_tag', None) or tache,
                                   getattr(m, 'tags', None) or (), carte),
            refs_type=refs_type, role=f"hf:{tache}",
            reason=f"recherche ciblée « {query} »",
            description=(f"[{tache}] {dl} téléchargements, "
                         f"{likes} ♥ — recherche ciblée « {query} »."),
            note=f"recherche ciblée « {query} » ({tache})", weight_gb=poids,
            license=cd.get('license'), base_model=cd.get('base_model'),
            downloads=dl, likes=likes, metric=_metrique_declaree(carte))
        crees += int(cree)
        maj += int(not cree)
        retenus.append(m.id)

    resume = {'ok': True, 'query': query, 'created': crees, 'updated': maj,
              'already': deja, 'skipped': ignores, 'total': len(retenus), 'refs': retenus}
    logger.info("[seed_hf_search] %s", resume)
    return resume


def apply_recommendations(candidates, source: str, task: str):
    """
    Crée/maj des entrées `recommended` dans le catalogue pour les candidats NOUVEAUX (pas déjà
    dans WAMA). Non téléchargées, non disponibles, préfixe model_id `rec-` (distinctes des
    modèles découverts). Le flag `extra_info['recommended']` est préservé par le sync. Retourne
    le nombre d'entrées écrites. L'installation effective reste une action admin (HF à venir).
    """
    import re
    from datetime import datetime, timezone
    from wama.model_manager.models import AIModel

    from wama.model_manager.models import model_type_for_task
    mt = model_type_for_task(task) or 'llm'
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for c in candidates:
        if c.get('have'):
            continue
        hf_id = c['hf_id']
        model_id = 'rec-' + re.sub(r'[^a-z0-9.-]+', '-', hf_id.lower()).strip('-')
        AIModel.objects.update_or_create(
            model_key=f"{source}:{model_id}",
            defaults={
                'name': hf_id.split('/')[-1],
                'source': source,
                'model_type': mt,
                'hf_id': hf_id,
                # La prospection LIT déjà la licence sur la carte HF (prospect_hf) : la jeter ici
                # obligeait à repasser par backfill_platform_refs --licenses pour la retrouver.
                # `platform_ref` se dérive du même fait, sans requête supplémentaire.
                'license': str(c.get('license') or '')[:64],
                'platform_ref': f"huggingface:{hf_id}",
                'description': f"(Recommandé · prospection) {task} — {c['downloads']} téléchargements, {c['likes']} ♥",
                'is_downloaded': False,
                'is_available': False,
                'extra_info': {'recommended': {
                    'task': task,
                    'downloads': c['downloads'],
                    'likes': c['likes'],
                    'pipeline_tag': c.get('pipeline_tag'),
                    'prospected_at': now,
                }},
            },
        )
        n += 1
    return n
