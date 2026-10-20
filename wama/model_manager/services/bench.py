# -*- coding: utf-8 -*-
"""
Banc de comparaison de modeles, indexe sur la TACHE et non sur l'app.

Pourquoi pas par app : `bench_describer` etait nomme d'apres le describer, or `describer` n'est
pas une categorie de modele — c'est une app. Le vocabulaire que les modeles portent vraiment est
celui des taches (`ModelTask`). Un banc `detect` sert l'anonymizer ET le cam_analyzer ; un banc
par app en aurait fait deux (Fabien, 2026-08-05).

Ce que ce banc mesure, et ce qu'il ne mesure PAS
------------------------------------------------
Il rend des grandeurs COMPARABLES entre modeles sur un meme echantillon : latence, nombre de
sorties, confiance moyenne. Ce ne sont pas des notes de qualite. Compter des boites ne dit pas
si elles sont justes — un modele qui sature a `max_det` en produit 300 sans rien valoir. Sans
verite terrain, le banc classe des candidats a essayer ; **le juge final reste humain**, meme
precaution que la commande qu'il remplace.

Place dans l'echelle des signaux (`model_selector._quality_scalars`) : ce banc est le 3e etage,
la MESURE INTERNE — mais il ne mesure que des COUTS (latence, debit, chargement). Le seul
protocole qui persiste est celui de la generation de texte, et il persiste des DUREES
(`ModelRuntimeStat`, la boucle d'ETA), jamais une valeur de qualite : le tri par qualite reste
au banc tiers confronte (`benchmark_sync`) et a l'a priori (`model_quality`).
"""
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from wama.model_manager.models import AIModel, ModelTask

logger = logging.getLogger(__name__)

# Ultralytics plafonne les detections a 300 par defaut. Un compte EXACTEMENT egal a cette valeur
# est une saturation, pas une performance : on le signale au lieu de le presenter comme un score.
DETECTION_CAP = 300

# Generation de texte : plafond de jetons produits par passe (`num_predict`). Meme lecture que
# DETECTION_CAP — un modele qui atteint le plafond est SATURE, pas « prolixe ». La valeur
# est celle du banc llmfit (`bench.rs`, 2026-09-14) : assez longue pour que le debit se
# stabilise apres le prefill, assez courte pour qu'un lot de 3 passes tienne en une minute.
TOKEN_CAP = 300
GENERATION_RUNS = 3
# Chargement a froid : en dessous de ce seuil, `load_duration` d'Ollama mesure un modele DEJA
# resident (quelques ms de re-attachement), pas un chargement — on ne l'apprend pas comme tel.
# Borne posee, pas mesuree : un chargement reel de poids se compte en secondes.
COLD_LOAD_THRESHOLD_S = 1.0


def models_for_task(task: str, *, installed_only: bool = True):
    """Modeles du catalogue qui declarent cette tache. Le catalogue est la seule source."""
    qs = AIModel.objects.filter(is_available=True)
    if installed_only:
        qs = qs.filter(is_downloaded=True)
    return [m for m in qs if (m.capabilities or {}).get('task') == task]


def _bench_detection(entry: AIModel, sample: str, *, conf: float = 0.25) -> dict:
    """Familles vision d'Ultralytics : detect, segment, obb, pose, classify."""
    from ultralytics import YOLO

    start = time.perf_counter()
    y = YOLO(entry.local_path)
    load_time = time.perf_counter() - start

    start = time.perf_counter()
    results = y.predict(sample, verbose=False, conf=conf, device=0)
    inference = time.perf_counter() - start

    box_count, confidences = 0, []
    for r in results:
        for b in (r.boxes or []):
            box_count += 1
            try:
                confidences.append(float(b.conf))
            except Exception:
                pass

    return {
        'outputs': box_count,
        'mean_confidence': round(sum(confidences) / len(confidences), 3) if confidences else None,
        'load_s': round(load_time, 2),
        'inference_s': round(inference, 3),
        'saturated': box_count >= DETECTION_CAP,
    }


def _bench_depth(entry: AIModel, sample: str, **_) -> dict:
    """
    Profondeur monoculaire metrique (Depth Pro et candidats natifs `transformers`).

    Comme le reste du banc, ce ne sont PAS des notes de qualite : sans verite terrain (KITTI,
    lidar) on ne calcule pas d'AbsRel/delta1. On rend des grandeurs COMPARABLES entre candidats
    sur une meme image — latence, couverture de profondeur valide, mediane metrique, focale
    estimee. Le juge final (le re-calage du plan de sol dans cam_analyzer, metrique
    `placement_spread`) reste en aval.
    """
    import numpy as np
    from PIL import Image
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    # Le dossier de FAMILLE est celui du moteur (`depth_engine.DEPTH_MODEL_DIR`, seul
    # domicile) : un candidat chargé par identifiant Hub sans `cache_dir=` atterrissait dans le
    # cache PARTAGÉ — la règle « le modèle principal par `cache_dir=` » (AGENTS.md) vaut pour
    # un candidat de banc comme pour le modèle retenu. Relevé par Fabien le 2026-09-14.
    from wama.common.backends.depth_engine import DEPTH_MODEL_DIR

    src = entry.local_path or entry.hf_id
    cache = str(DEPTH_MODEL_DIR)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    start = time.perf_counter()
    processor = AutoImageProcessor.from_pretrained(src, cache_dir=cache)
    model = AutoModelForDepthEstimation.from_pretrained(
        src, cache_dir=cache,
        torch_dtype=torch.float16 if device == 'cuda' else torch.float32).to(device).eval()
    load_time = time.perf_counter() - start

    image = Image.open(sample).convert('RGB')
    w0, h0 = image.size
    inputs = processor(images=image, return_tensors='pt').to(device)

    start = time.perf_counter()
    with torch.no_grad():
        outputs = model(**inputs)
    post = processor.post_process_depth_estimation(outputs, target_sizes=[(h0, w0)])[0]
    inference = time.perf_counter() - start

    depth = post['predicted_depth'].float().cpu().numpy()
    focal = post.get('focal_length')
    if focal is not None:
        try:
            focal = round(float(np.asarray(focal).reshape(-1)[0]), 1)
        except Exception:
            focal = None
    valid = np.isfinite(depth) & (depth > 0)
    coverage = round(float(valid.mean()), 3) if depth.size else None
    median = round(float(np.median(depth[valid])), 2) if valid.any() else None

    return {
        'outputs': int(valid.sum()),                 # pixels de profondeur valide
        'mean_confidence': coverage,              # couverture [0..1] (reutilise la colonne)
        'load_s': round(load_time, 2),
        'inference_s': round(inference, 3),
        'saturated': False,
        'median_m': median,
        'focal_px': focal,
    }


def _bench_description(entry: AIModel, sample: str, **_) -> dict:
    """Modeles vision-langage servis par Ollama — protocole repris de `bench_describer`."""
    from wama.model_manager.services.vision_probe import describe_image_ollama

    start = time.perf_counter()
    response = describe_image_ollama(sample, model=entry.name)
    duration = time.perf_counter() - start
    # `describe_image_ollama` rend un dict {'ok', 'description'|'error'} — ce protocole le lisait
    # comme une chaine (`.strip()` sur un dict → AttributeError avale par `run_bench`, donc CHAQUE
    # modele de legendage sortait « en erreur »). Corrige le 2026-09-14 en ecrivant le protocole
    # voisin ; un echec de la sonde est un RESULTAT et se rapporte comme tel.
    if not response.get('ok'):
        raise RuntimeError(response.get('error') or 'sonde vision muette')
    text = (response.get('description') or '').strip()
    return {
        'outputs': len(text.split()) if text else 0,
        'mean_confidence': None,
        'load_s': None,
        'inference_s': round(duration, 2),
        'saturated': False,
        'text': text,
    }


def _read_prompt(sample: str) -> str:
    """L'echantillon d'un banc de generation est un PROMPT : un fichier texte (chemin) ou la
    chaine elle-meme. Le fichier est la forme de la commande (`--media`), la chaine celle des
    appels programmatiques."""
    if sample and os.path.isfile(sample):
        return Path(sample).read_text(encoding='utf-8').strip()
    return (sample or '').strip()


def _ollama_generate(model: str, prompt: str, num_predict: int, timeout: int = 300) -> dict:
    """
    UN appel `POST /api/generate` non streame, rendu BRUT : c'est la reponse d'Ollama qui porte
    les temps natifs en nanosecondes (`eval_count`/`eval_duration` = generation,
    `prompt_eval_count`/`prompt_eval_duration` = prefill, `load_duration` = chargement,
    `total_duration`). On ne chronometre pas au mur : le mur ajoute le reseau et la
    serialisation, que le modele n'a pas a payer. Seul point HTTP du protocole — c'est lui
    que les tests remplacent.
    """
    import requests
    from wama.common.utils.ollama_host import ollama_base

    payload = {'model': model, 'prompt': prompt, 'stream': False,
               'options': {'num_predict': int(num_predict)}}
    # `trust_env=False` : Ollama est LOCAL — meme precaution que `vision_probe`/`llm_utils`.
    with requests.Session() as s:
        s.trust_env = False
        r = s.post(f"{ollama_base()}/api/generate", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _ns_to_s(value) -> float:
    try:
        return round(float(value or 0) / 1e9, 3)
    except (TypeError, ValueError):
        return 0.0


def _bench_generation(entry: AIModel, sample: str, *, runs: int = GENERATION_RUNS,
                      num_predict: int = TOKEN_CAP, **_) -> dict:
    """
    Generation de texte servie par Ollama — le DEBIT (jetons/s), le prefill et le chargement.

    Ce que ce protocole mesure : le COUT d'un LLM sur ce materiel, la seule grandeur que WAMA
    ne mesurait pas encore pour cette famille (constate le 2026-09-14 en confrontant llmfit :
    `ModelRuntimeStat` avait une unite `token` a priori et AUCUN enregistrement). Il ne dit
    RIEN de la qualite des reponses — meme reserve que les autres protocoles : le banc tiers
    confronte (`benchmark_sync`) porte la qualite, ici on ne classe que des couts.

    Deroulement (repris du banc llmfit, `bench.rs`) : une passe de CHAUFFE, non comptee, qui
    charge le modele et dont `load_duration` donne le chargement a froid ; puis `runs` passes
    sur LE MEME prompt, `num_predict` jetons au plus. Un modele qui atteint le plafond a
    CHAQUE passe est marque sature — son `sorties` ne compare plus rien.

    Ce qu'il PERSISTE, et pourquoi c'est ici : chaque passe est une execution reelle
    → `eta_estimator.record_run(unit='token')`, bucketise par empreinte materielle. C'est la
    boucle d'ETA existante (les 8 apps media la nourrissent deja) ; les LLM y entrent par ce
    banc parce qu'aucune app LLM ne l'appelle. Rien d'autre n'est ecrit par le banc : ni
    `vram_gb`, ni un indice de qualite. L'empreinte VRAM de la chauffe suit la voie commune de la
    mesure au chargement (`ollama_host.measured_load` → `extra_info['vram_measured']`).

    ⚠ Ce protocole CHARGE un modele sur l'Ollama hote — la rampe VRAM qui a tue l'hote
    plusieurs fois (INFRA §crashs). Il respecte `WAMA_GPU_SAFE_MODE` comme ses jumeaux
    (triage VLM du smoke, describer) et refuse EN LE DISANT.
    """
    from wama.common.services.resource_governor import gpu_safe_mode
    from wama.model_manager.services.eta_estimator import record_run

    if gpu_safe_mode():
        raise RuntimeError("WAMA_GPU_SAFE_MODE actif : chargement d'un LLM hote refuse")
    if entry.source != 'ollama':
        raise ValueError(f"protocole Ollama seulement (source={entry.source!r})")
    prompt = _read_prompt(sample)
    if not prompt:
        raise ValueError("prompt vide")

    # La CHAUFFE est l'appel qui charge le modèle : son empreinte se mesure à la carte et rejoint
    # le catalogue (`ollama_host.measured_load`, 2026-10-20) — le banc ne l'écrit pas lui-même.
    from wama.common.utils.ollama_host import measured_load
    warmup = measured_load(entry.name, lambda: _ollama_generate(
        entry.name, 'Réponds simplement « ok ».', 8))
    load_s = _ns_to_s(warmup.get('load_duration'))
    cold = load_s >= COLD_LOAD_THRESHOLD_S

    run_results = []
    for i in range(max(int(runs), 1)):
        d = _ollama_generate(entry.name, prompt, num_predict)
        tokens = int(d.get('eval_count') or 0)
        duration = _ns_to_s(d.get('eval_duration'))
        run_result = {
            'tokens': tokens,
            'generation_s': duration,
            'tokens_per_s': round(tokens / duration, 1) if tokens and duration else None,
            'prefill_ms': round(float(d.get('prompt_eval_duration') or 0) / 1e6, 1),
            'prompt_tokens': int(d.get('prompt_eval_count') or 0),
        }
        run_results.append(run_result)
        if tokens and duration:
            record_run(entry.model_key, size=tokens, unit='token', process_seconds=duration,
                       load_seconds=load_s if (cold and i == 0) else None)

    throughputs = [p['tokens_per_s'] for p in run_results if p['tokens_per_s']]
    return {
        'outputs': round(sum(p['tokens'] for p in run_results) / len(run_results)),
        'mean_confidence': None,
        'load_s': load_s if cold else None,
        'inference_s': round(sum(p['generation_s'] for p in run_results) / len(run_results), 3),
        'saturated': all(p['tokens'] >= num_predict for p in run_results),
        'tokens_per_s': round(sum(throughputs) / len(throughputs), 1) if throughputs else None,
        'prefill_ms': round(sum(p['prefill_ms'] for p in run_results) / len(run_results), 1),
        'runs': run_results,
    }


# ── Rappel par CONTENANT (2026-10-10) — la premiere MESURE DE QUALITE de ce banc ─────────────
# Sans verite terrain des plaques, on mesure contre des CONTENANTS deja connus : une plaque
# appartient a un vehicule. La reference donne, image par image, les boites des vehicules (sorties
# d'un suivi deja valide) ; un vehicule PROCHE (boite d'au moins `min_height` px) est « trouve »
# si le centre d'une detection tombe dedans. Le taux MANQUE (1 - rappel) est une borne : un
# vehicule de profil n'a pas de plaque visible — il compte comme manque pour TOUS les modeles,
# donc l'ordre reste juste. La part des detections tombant dans un vehicule dit les fausses
# alertes (capot, logo, panneaux).
# Chaque modele passe par le MEME chemin que l'anonymizer (`detection_ensemble`), avec ses propres
# reglages (seuil mesure d'EgoBlur, agrandissement…) : on mesure ce qui floutera.
RECALL_PROTOCOL = 'containment_v1'
RECALL_APP, RECALL_OBJECT = 'model_manager', 'DetectionBench'


def read_recall_reference(sample: str) -> dict:
    """La reference d'un banc de rappel (JSON) : `media` (chemin, relatif au fichier ou
    absolu), `class`, `min_height`, `containers` (une liste de boites [x1,y1,x2,y2] par image,
    dans l'ordre des images du media)."""
    import json
    with open(sample, encoding='utf-8') as f:
        ref = json.load(f)
    media = ref.get('media') or ''
    if media and not os.path.isabs(media):
        media = os.path.join(os.path.dirname(os.path.abspath(sample)), media)
    if not (media and os.path.isfile(media) and ref.get('class') and ref.get('containers')):
        raise ValueError(f"{sample} : reference de rappel incomplete (media, class, containers)")
    ref['media'] = media
    ref.setdefault('min_height', 45)
    return ref


def containment_counts(doc: dict, ref: dict) -> dict:
    """Les comptes du rappel par contenant — sans interpretation (cf. en-tete du protocole)."""
    by_index = {f['i']: f.get('d') or [] for f in doc.get('frames') or []}
    near = found = detections = inside = 0
    for index, containers in enumerate(ref['containers']):
        centres = [((d['box'][0] + d['box'][2]) / 2, (d['box'][1] + d['box'][3]) / 2)
                   for d in by_index.get(index, [])]
        detections += len(centres)
        inside += sum(any(c[0] - 4 <= x <= c[2] + 4 and c[1] - 4 <= y <= c[3] + 4
                          for c in containers) for x, y in centres)
        for c in containers:
            if c[3] - c[1] >= ref['min_height']:
                near += 1
                found += any(c[0] <= x <= c[2] and c[1] <= y <= c[3] for x, y in centres)
    return {'near': near, 'found': found, 'missed': near - found, 'detections': detections,
            'inside': inside}


def _bench_recall(entry: AIModel, sample: str, *, conf: float = 0.25, record: bool = False,
                  **_) -> dict:
    """Le rappel d'UN modele sur une reference de contenants ; `record` range la mesure
    (`ResultEvaluation`, une ligne par modele — l'etage 3 de l'echelle des signaux)."""
    import hashlib

    from wama.common.services.detection_ensemble import DetectorSet
    from wama.common.services.model_coverage import miss_metric

    ref = read_recall_reference(sample)
    frames = max(len(ref['containers']), 1)
    # Le chargement du modèle HORS du temps (2026-10-11 : il y était compté, d'où des ms par image
    # qui mesuraient aussi le chargement) ; le média copié en local par le chronomètre. Pas de
    # passe de chauffe : sur une vidéo elle doublerait le banc — la première image porte donc
    # l'initialisation du GPU, une part négligeable sur des centaines d'images.
    detectors = DetectorSet([{'model_key': entry.model_key, 'path': entry.local_path,
                              'name': entry.name, 'classes': [ref['class']]}])
    clock = _SpeedClock(warm_up=False)
    try:
        doc = clock.detect(detectors, ref['media'], classes2blur=[ref['class']],
                           detection_threshold=conf)
    finally:
        clock.close()
    elapsed = clock.total
    clock.record(entry.model_key, frames)
    counts = containment_counts(doc, ref)
    miss = round(counts['missed'] / counts['near'], 4) if counts['near'] else None
    if record and miss is not None:
        from wama.common.models import ResultEvaluation
        with open(sample, 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        ResultEvaluation.objects.update_or_create(
            app=RECALL_APP, object_type=RECALL_OBJECT, object_id=entry.pk,
            metric=miss_metric(ref['class']),
            defaults={'model_key': entry.model_key, 'value': miss, 'direction': 'lower',
                      'protocol': RECALL_PROTOCOL, 'reference_sha256': digest,
                      'reference_name': os.path.basename(sample),
                      'detail': {'errors': counts['missed'], 'reference_length': counts['near'],
                                 'unit': 'object', 'detections': counts['detections'],
                                 'inside': counts['inside'], 'threshold': conf,
                                 'ms_per_frame': round(1000 * elapsed / frames, 1)}})
    return {
        'outputs': counts['detections'],
        'mean_confidence': None,
        'load_s': None,
        'inference_s': round(elapsed, 2),
        'saturated': False,
        'recall': round(1 - miss, 3) if miss is not None else None,
        'inside_rate': round(counts['inside'] / counts['detections'], 3)
        if counts['detections'] else None,
        'ms_per_frame': round(1000 * elapsed / frames, 1),
    }


# ── Rappel et precision sur VRAIES boites (2026-10-10) — un jeu annote, lu dans son format natif ─
# La reference ne recopie pas les boites : elle DESIGNE le fichier d'annotation publie et son
# format (`dataset_formats.READERS`), en chemins RELATIFS a elle-meme — elle survit au deplacement
# de l'arborescence des jeux (`WAMA_APPRENTISSAGE §8bis`). Premier jeu : WIDER FACE val.
# Appariement glouton par confiance decroissante a IoU >= `iou` : un objet trouve = vrai positif ;
# une detection sans objet = fausse alerte, SAUF si elle tombe sur un objet que le jeu marque
# lui-meme inexploitable (`ignore`). Le rappel se lit aussi par TAILLE d'objet (hauteur en
# pixels) : c'est la ou un detecteur de visages lache dans une foule.
BOXES_PROTOCOL = 'boxes_iou50_v1'
BOXES_OBJECT = 'DetectionBenchBoxes'
SIZE_BUCKETS = ((16, 'tiny'), (32, 'small'), (96, 'medium'), (10 ** 9, 'large'))

# ── Temps PROPRE de traitement (2026-10-11) — ce que le curseur rapide/qualité peut comparer ──
# Le temps « mur » d'un banc sur le partage réseau des jeux mesure surtout le partage : le premier
# modèle d'une campagne lit des images que les suivants retrouvent en cache (mesuré : 537 ms pour
# le plus petit lindevs, 133 pour le plus gros). Le temps propre lit l'image depuis une copie
# LOCALE faite hors chronomètre, sur un modèle déjà chargé et une première passe de chauffe
# écartée : c'est ce que coûte une image à l'anonymizer (décodage + ses passes + le modèle).
# Il va dans la boucle d'ETA COMMUNE, comme les jetons d'un LLM (`_bench_generation`) : secondes
# par image sous la clé de catalogue du modèle, sur ce matériel (`_SpeedClock.record`). C'est là
# que le curseur de toutes les apps lit la vitesse (`eta_estimator.comparable_speeds`).
#: Taille de l'échantillon régulier d'une mesure de vitesse seule (`detect-speed`).
SPEED_SAMPLE = 200
#: Unité de la vitesse d'un détecteur : une image analysée, photo ou image de vidéo.
IMAGE_UNIT = 'image'


class _SpeedClock:
    """Chronomètre du temps propre : `detect` copie le média dans un dossier local (hors temps),
    chauffe le modèle sur le premier, puis ne compte que l'appel de détection."""

    def __init__(self, warm_up: bool = True):
        import tempfile
        self.folder = tempfile.mkdtemp(prefix='wama-bench-')
        self.warm_up, self.total, self.count = warm_up, 0.0, 0

    def detect(self, detectors, path: str, **kwargs) -> dict:
        import shutil
        local = os.path.join(self.folder, 'item' + os.path.splitext(path)[1].lower())
        shutil.copyfile(path, local)
        if self.warm_up:
            detectors.detect(media_path=local, **kwargs)
            self.warm_up = False
        start = time.perf_counter()
        doc = detectors.detect(media_path=local, **kwargs)
        self.total += time.perf_counter() - start
        self.count += 1
        return doc

    def ms_per_item(self, items: int = 0) -> Optional[float]:
        """Moyenne par image ; `items` = nombre d'images d'une vidéo (sinon un appel = une image)."""
        n = items or self.count
        return round(1000 * self.total / n, 1) if n else None

    def record(self, model_key: str, items: int = 0) -> Optional[float]:
        """Range le temps propre dans la boucle d'ETA commune (`eta_estimator.record_run`) : une
        exécution réelle de `items` images (sinon une par appel), hors chargement. Rend les ms par
        image, None sans mesure."""
        from wama.model_manager.services.eta_estimator import record_run
        n = items or self.count
        if not n:
            return None
        record_run(model_key, size=n, unit=IMAGE_UNIT, process_seconds=self.total)
        return self.ms_per_item(n)

    def close(self):
        import shutil
        shutil.rmtree(self.folder, ignore_errors=True)


def _sampled(entries: list, limit: int) -> list:
    """Échantillon RÉGULIER, reproductible, de `limit` éléments (0 = tous)."""
    if limit and limit < len(entries):
        step = len(entries) / limit
        return [entries[int(k * step)] for k in range(limit)]
    return entries


def benchmark_reference(name: str) -> str:
    """Le fichier de reference du banc `name`, sous la racine des jeux de donnees — resolue par la
    brique commune des espaces distants (`mirror_sync.resolve_remote_root`, surchargeable par
    `WAMA_DATASETS_ROOT`) : aucun chemin du partage n'est ecrit dans WAMA."""
    from wama.common.services.mirror_sync import resolve_remote_root
    return os.path.join(resolve_remote_root('DATASETS', 'WAMA_DATASETS_ROOT'), 'benchmarks', name,
                        'reference.json')


def read_boxes_reference(sample: str) -> dict:
    """Une reference « vraies boites » : `class`, `format`, `images` (dossier), `annotations`
    (fichier), `iou` — chemins relatifs au fichier de reference ou absolus."""
    import json
    from wama.common.utils.dataset_formats import READERS
    with open(sample, encoding='utf-8') as f:
        ref = json.load(f)
    base = os.path.dirname(os.path.abspath(sample))
    for key in ('images', 'annotations'):
        if ref.get(key) and not os.path.isabs(ref[key]):
            ref[key] = os.path.normpath(os.path.join(base, ref[key]))
    if ref.get('format') not in READERS:
        raise ValueError(f"{sample} : format inconnu {ref.get('format')!r} ({', '.join(READERS)})")
    if not (ref.get('class') and os.path.isdir(ref.get('images') or '')
            and os.path.isfile(ref.get('annotations') or '')):
        raise ValueError(f"{sample} : reference incomplete (class, images, annotations)")
    ref.setdefault('iou', 0.5)
    ref['entries'] = READERS[ref['format']](ref['annotations'])
    return ref


def _iou(a, b) -> float:
    from wama.common.utils.detections import _iou as iou
    return iou(a, b)


def _bucket(box) -> str:
    h = box[3] - box[1]
    return next(name for ceiling, name in SIZE_BUCKETS if h < ceiling)


def merged(found, iou: float = 0.5) -> list:
    """Les detections d'UNE image sans leurs DOUBLONS : un meme objet vu a deux echelles (une
    image passe native ET agrandie) ou par deux modeles d'un ensemble donne deux boites. Pour
    flouter c'est sans effet — les zones se reunissent —, pour une PRECISION c'est une fausse
    alerte fictive (mesure le 2026-10-10 : 44 % de precision « perdue » sur WIDER par ce seul
    doublon). Suppression glouton par confiance, comme la NMS d'un detecteur."""
    kept = []
    for box, conf in sorted(found, key=lambda x: -x[1]):
        if all(_iou(box, k[0]) < iou for k in kept):
            kept.append((box, conf))
    return kept


def match_boxes(found, truth, ignore, iou: float = 0.5) -> dict:
    """Comptes d'UNE image : `found` = [(box, conf)], `truth`/`ignore` = [box]. Les doublons de
    `found` sont fusionnes d'abord (`merged`)."""
    found = merged(found, iou)
    taken, tp, fp = set(), 0, 0
    hit_buckets = {}
    for box, _conf in sorted(found, key=lambda x: -x[1]):
        best, best_iou = None, iou
        for k, gt in enumerate(truth):
            if k in taken:
                continue
            value = _iou(box, gt)
            if value >= best_iou:
                best, best_iou = k, value
        if best is not None:
            taken.add(best)
            tp += 1
            name = _bucket(truth[best])
            hit_buckets[name] = hit_buckets.get(name, 0) + 1
        elif not any(_iou(box, g) >= iou for g in ignore):
            fp += 1
    totals = {}
    for gt in truth:
        name = _bucket(gt)
        totals[name] = totals.get(name, 0) + 1
    return {'truth': len(truth), 'tp': tp, 'fp': fp, 'hit_buckets': hit_buckets,
            'truth_buckets': totals}


def _bench_boxes(entry: AIModel, sample: str, *, conf: float = 0.25, record: bool = False,
                 limit: int = 0, **_) -> dict:
    """Rappel et precision d'UN modele sur un jeu annote (par le chemin de l'anonymizer)."""
    import hashlib

    from wama.common.services.detection_ensemble import DetectorSet
    from wama.common.services.model_coverage import miss_metric

    ref = read_boxes_reference(sample)
    entries = _sampled(ref['entries'], limit)
    detectors = DetectorSet([{'model_key': entry.model_key, 'path': entry.local_path,
                              'name': entry.name, 'classes': [ref['class']]}])
    totals = {'truth': 0, 'tp': 0, 'fp': 0}
    buckets = {}
    clock = _SpeedClock()
    start = time.perf_counter()
    try:
        for item in entries:
            doc = clock.detect(detectors, os.path.join(ref['images'], item['path']),
                               classes2blur=[ref['class']], detection_threshold=conf)
            found =[(d['box'], d.get('conf', 1.0)) for f in doc.get('frames') or [] for d in f['d']]
            counts = match_boxes(found, item['boxes'], item['ignore'], ref['iou'])
            for k in totals:
                totals[k] += counts[k]
            for name, n in counts['truth_buckets'].items():
                b = buckets.setdefault(name, [0, 0])
                b[1] += n
                b[0] += counts['hit_buckets'].get(name, 0)
    finally:
        clock.close()
    elapsed = time.perf_counter() - start
    ms_per_item = clock.record(entry.model_key)
    missed = totals['truth'] - totals['tp']
    miss = round(missed / totals['truth'], 4) if totals['truth'] else None
    detections = totals['tp'] + totals['fp']
    precision = round(totals['tp'] / detections, 4) if detections else None
    by_size = {name: {'found': f, 'truth': t, 'recall': round(f / t, 3) if t else None}
               for name, (f, t) in buckets.items()}
    if record and miss is not None:
        from wama.common.models import ResultEvaluation
        with open(ref['annotations'], 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        ResultEvaluation.objects.update_or_create(
            app=RECALL_APP, object_type=BOXES_OBJECT, object_id=entry.pk,
            metric=miss_metric(ref['class']),
            defaults={'model_key': entry.model_key, 'value': miss, 'direction': 'lower',
                      'protocol': BOXES_PROTOCOL, 'reference_sha256': digest,
                      'reference_name': ref.get('name') or os.path.basename(sample),
                      'detail': {'errors': missed, 'reference_length': totals['truth'],
                                 'unit': 'object', 'images': len(entries),
                                 'false_positives': totals['fp'], 'precision': precision,
                                 'by_size': by_size, 'threshold': conf,
                                 'ms_per_image': round(1000 * elapsed / max(len(entries), 1), 1)}})
    return {
        'outputs': detections, 'mean_confidence': None, 'load_s': None,
        'inference_s': round(elapsed, 2), 'saturated': False,
        'recall': round(1 - miss, 3) if miss is not None else None,
        'precision': precision, 'by_size': by_size,
        'ms_per_frame': ms_per_item,
    }


def _bench_speed(entry: AIModel, sample: str, *, conf: float = 0.25, record: bool = False,
                 limit: int = 0, **_) -> dict:
    """Le temps PROPRE seul d'un détecteur, sur un échantillon régulier d'un jeu annoté
    (`SPEED_SAMPLE` images par défaut) — sans refaire le rappel, qui ne dépend pas de la machine.
    Comme tout passage de détecteur du banc, il va dans la boucle d'ETA commune
    (`_SpeedClock.record`) : c'est le geste à rejouer après un changement de carte ou de
    librairie."""
    from wama.common.services.detection_ensemble import DetectorSet

    ref = read_boxes_reference(sample)
    entries = _sampled(ref['entries'], limit or SPEED_SAMPLE)
    detectors = DetectorSet([{'model_key': entry.model_key, 'path': entry.local_path,
                              'name': entry.name, 'classes': [ref['class']]}])
    clock = _SpeedClock()
    try:
        for item in entries:
            clock.detect(detectors, os.path.join(ref['images'], item['path']),
                         classes2blur=[ref['class']], detection_threshold=conf)
    finally:
        clock.close()
    return {'outputs': None, 'mean_confidence': None, 'load_s': None,
            'inference_s': round(clock.total, 2), 'saturated': False,
            'ms_per_frame': clock.record(entry.model_key)}


# ── Agrandissement « PAR CONSTRUCTION » (2026-10-14) — une vérité exacte sans humain ─────────
# `WAMA_QUALITE §4` (⑤, la vérité la plus gratuite de toutes) : on RÉDUIT une image nette du
# facteur du modèle (bicubique), le modèle l'agrandit, et sa sortie se compare à l'ORIGINAL. La
# métrique retenue est LPIPS (distance perceptuelle, plus bas = mieux — décision de Fabien : ce que
# l'œil juge sur une photo agrandie ; PSNR et SSIM pourront s'y ajouter, chacun son échelle).
# Le PROTOCOLE porte le facteur : ×2 et ×4 ne se mesurent pas sur la même image d'entrée, ce sont
# deux populations (`internal_quality`). Chaque modèle passe par le MÊME chemin que l'enhancer
# et la sortie commune (`backend_for_key` → classe du moteur déclaré, identifiant de SON
# vocabulaire). La vitesse va dans la boucle d'ETA commune (secondes par MÉGAPIXEL d'entrée, clé
# de catalogue, ce matériel) — c'est là que le curseur lit le coût (`comparable_speeds`).
UPSCALE_PROTOCOL = 'bicubic_x{scale}_v1'
UPSCALE_OBJECT = 'UpscaleBench'
UPSCALE_METRIC = 'lpips'
#: Unité de la vitesse d'un agrandisseur : un mégapixel d'ENTRÉE.
MEGAPIXEL_UNIT = 'megapixel'
#: Extensions lues comme images d'une référence « dossier d'images ».
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')


def read_image_reference(sample: str) -> dict:
    """Une référence « dossier d'images nettes » : `images` (dossier, relatif au fichier de
    référence ou absolu) ; `entries` = les noms d'images, triés (ordre reproductible)."""
    import json
    with open(sample, encoding='utf-8') as f:
        ref = json.load(f)
    images = ref.get('images') or ''
    if images and not os.path.isabs(images):
        images = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(sample)), images))
    if not os.path.isdir(images):
        raise ValueError(f"{sample} : dossier d'images introuvable ({images})")
    ref['images'] = images
    ref['entries'] = sorted(n for n in os.listdir(images) if n.lower().endswith(IMAGE_EXTENSIONS))
    if not ref['entries']:
        raise ValueError(f"{sample} : aucune image dans {images}")
    return ref


_LPIPS = {}

#: L'instrument LPIPS au catalogue (2026-10-16) : une ligne de tâche `quality-metric`, que le
#: model manager installe, vérifie et désinstalle comme tout modèle — la dorsale AlexNet de
#: torchvision était tirée par `torch.hub` au premier banc, à côté de la route d'installation.
LPIPS_KEY = 'custom:lpips-alexnet'
LPIPS_WEIGHTS = 'alexnet-owt-7be5be79.pth'
#: Le fichier DÉCLARÉ (pilote `files`) : la version officielle de torchvision (source déclarée
#: `pytorch_download`), taille et empreinte MESURÉES le 2026-10-16 sur le fichier installé — son nom
#: porte le début de cette empreinte (`7be5be79`), la convention de `torch.hub`.
LPIPS_FILES = [
    {'path': LPIPS_WEIGHTS, 'size': 244408911,
     'sha256': '7be5be791159472b1fbf3c69796f7cb30dca7ad8466c2df70058c37116cdee02',
     'origin': {'source': 'pytorch_download', 'file': f'models/{LPIPS_WEIGHTS}'}},
]


def lpips_folder() -> Path:
    from django.conf import settings
    return Path(settings.MODEL_PATHS['vision']['lpips'])


def lpips_metric(device: str):
    """LPIPS (réseau AlexNet), chargé une fois par processus. Les couches linéaires viennent du
    paquet ; la dorsale AlexNet est celle que le model manager installe (`LPIPS_KEY`) — absente,
    elle s'installe par la route et le banc ATTEND (`model_readiness.install_and_wait`, le banc
    est une commande). Jamais dans le $HOME, où `torch.hub` la rangeait de lui-même."""
    if device not in _LPIPS:
        import lpips
        import torch
        from wama.common.utils.model_readiness import install_and_wait
        weights = lpips_folder() / LPIPS_WEIGHTS
        if not weights.exists():
            install_and_wait(LPIPS_KEY, console=logger.info)
            if not weights.exists():
                raise RuntimeError(f"LPIPS : {weights} absent — installer « LPIPS (AlexNet) » depuis "
                                   f"le model manager (`pull_model {LPIPS_KEY}`)")
        state = torch.load(weights, map_location='cpu', weights_only=True)
        metric = lpips.LPIPS(net='alex', pnet_rand=True, verbose=False)
        # Le réseau de LPIPS range les couches de `alexnet.features` par TRANCHES (`slice1.0`…),
        # sous leur indice d'origine : `features.<i>.<p>` → `slice<k>.<i>.<p>`.
        mapped = {}
        for key in metric.net.state_dict():
            _slice, index, param = key.split('.', 2)
            mapped[key] = state[f'features.{index}.{param}']
        metric.net.load_state_dict(mapped)
        _LPIPS[device] = metric.eval().to(device)
    return _LPIPS[device]


def _as_tensor(bgr, device: str):
    """Image BGR uint8 → tenseur RGB [-1, 1] (N, C, H, W), la convention de LPIPS."""
    import torch
    rgb = bgr[:, :, ::-1].copy()
    return (torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).float().div(127.5).sub(1.0)
            .to(device))


def _bench_upscale(entry: AIModel, sample: str, *, record: bool = False, limit: int = 0,
                   **_) -> dict:
    """LPIPS d'UN agrandisseur sur une référence d'images nettes, réduites de SON facteur."""
    import hashlib

    import cv2
    import torch

    from wama.common.backends.manager import backend_for_key
    from wama.common.services.resource_governor import gpu_safe_mode
    from wama.common.utils.model_keys import backend_model_id
    from wama.model_manager.services.eta_estimator import record_run

    if gpu_safe_mode():
        raise RuntimeError("WAMA_GPU_SAFE_MODE actif : chargement d'un agrandisseur refusé")
    scale = int((entry.capabilities or {}).get('scale') or 0)
    if scale < 2:
        raise ValueError(f"capacité `scale` absente ou < 2 ({scale}) : rien à agrandir")
    backend_class = backend_for_key(entry.model_key)
    if backend_class is None:
        raise RuntimeError(f"{entry.model_key} : aucun backend résolu depuis le catalogue")
    ref = read_image_reference(sample)
    entries = _sampled(ref['entries'], limit)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    metric = lpips_metric(device)
    upscaler = backend_class(model_name=backend_model_id(entry.model_key))
    total, elapsed, megapixels, warm = 0.0, 0.0, 0.0, True
    try:
        for name in entries:
            hr = cv2.imread(os.path.join(ref['images'], name))
            if hr is None:
                raise ValueError(f"image illisible : {name}")
            h, w = (hr.shape[0] // scale) * scale, (hr.shape[1] // scale) * scale
            hr = hr[:h, :w]
            lr = cv2.resize(hr, (w // scale, h // scale), interpolation=cv2.INTER_CUBIC)
            if warm:                      # chauffe : chargement de la session, non comptée
                upscaler.upscale_image(lr)
                warm = False
            start = time.perf_counter()
            sr = upscaler.upscale_image(lr)
            elapsed += time.perf_counter() - start
            megapixels += lr.shape[0] * lr.shape[1] / 1e6
            if sr.shape != hr.shape:
                raise ValueError(f"{name} : sortie {sr.shape[:2]} au lieu de {hr.shape[:2]}")
            with torch.no_grad():
                total += float(metric(_as_tensor(sr, device), _as_tensor(hr, device)).item())
    finally:
        upscaler.close()
    count = len(entries)
    if megapixels:
        record_run(entry.model_key, size=megapixels, unit=MEGAPIXEL_UNIT, process_seconds=elapsed)
    mean = round(total / count, 4)
    if record:
        from wama.common.models import ResultEvaluation
        # L'identité de la référence : son fichier ET les images retenues (un échantillon `limit`
        # est une autre population que le jeu entier).
        digest = hashlib.sha256()
        with open(sample, 'rb') as f:
            digest.update(f.read())
        digest.update('\n'.join(entries).encode('utf-8'))
        ResultEvaluation.objects.update_or_create(
            app=RECALL_APP, object_type=UPSCALE_OBJECT, object_id=entry.pk, metric=UPSCALE_METRIC,
            defaults={'model_key': entry.model_key, 'value': mean, 'direction': 'lower',
                      'protocol': UPSCALE_PROTOCOL.format(scale=scale),
                      'reference_sha256': digest.hexdigest(),
                      'reference_name': ref.get('name') or os.path.basename(sample),
                      'detail': {'errors': round(total, 4), 'reference_length': count,
                                 'unit': 'image', 'scale': scale,
                                 'ms_per_megapixel': round(1000 * elapsed / megapixels, 1)
                                 if megapixels else None}})
    return {'outputs': count, 'mean_confidence': None, 'load_s': None,
            'inference_s': round(elapsed, 2), 'saturated': False, 'lpips': mean,
            'scale': scale, 'ms_per_frame': round(1000 * elapsed / count, 1) if count else None}


def boxes_candidates(sample: str) -> list:
    """Detecteurs installes qui couvrent la classe d'une reference « vraies boites »."""
    import json
    from wama.common.services.model_coverage import classes_couvertes
    with open(sample, encoding='utf-8') as f:
        cls = json.load(f)['class']
    return [m for t in (ModelTask.DETECT.value, ModelTask.SEGMENT.value)
            for m in models_for_task(t) if classes_couvertes(m, [cls])]


def recall_candidates(sample: str) -> list:
    """Les modeles a mesurer pour une reference : detecteurs installes qui couvrent sa classe."""
    from wama.common.services.model_coverage import classes_couvertes
    cls = read_recall_reference(sample)['class']
    return [m for t in (ModelTask.DETECT.value, ModelTask.SEGMENT.value)
            for m in models_for_task(t) if classes_couvertes(m, [cls])]


# Un protocole par FAMILLE de tache. Ajouter une tache = ajouter une entree ici, jamais une
# commande de plus.
PROTOCOLS: dict[str, Callable] = {
    ModelTask.DETECT.value: _bench_detection,
    ModelTask.SEGMENT.value: _bench_detection,
    ModelTask.OBB.value: _bench_detection,
    ModelTask.POSE.value: _bench_detection,
    ModelTask.CLASSIFY.value: _bench_detection,
    ModelTask.CAPTIONING.value: _bench_description,
    ModelTask.DEPTH_ESTIMATION.value: _bench_depth,
    ModelTask.TEXT_GENERATION.value: _bench_generation,
    # Pas une tache de modele : un protocole de QUALITE sur les detecteurs (`detect`/`segment`)
    # qui couvrent la classe de la reference — cf. `_bench_recall`.
    'detect-recall': _bench_recall,
    # Rappel + precision sur un jeu ANNOTE (WIDER FACE val…) — cf. `_bench_boxes`.
    'detect-boxes': _bench_boxes,
    # Le temps propre seul, sur la référence d'un banc « vraies boîtes » — cf. `_bench_speed`.
    'detect-speed': _bench_speed,
    # Agrandissement par construction (LPIPS contre l'original) — cf. `_bench_upscale`.
    ModelTask.UPSCALE.value: _bench_upscale,
}

#: Protocoles dont les candidats ne se lisent pas par `models_for_task(tache)`.
CANDIDATES = {'detect-recall': recall_candidates, 'detect-boxes': boxes_candidates,
              'detect-speed': boxes_candidates}

#: Protocoles qui savent RANGER leur mesure (`--record`) et échantillonner (`--limit`).
RECORDING = ('detect-recall', 'detect-boxes', 'detect-speed', ModelTask.UPSCALE.value)
SAMPLING = ('detect-boxes', 'detect-speed', ModelTask.UPSCALE.value)


def available_tasks() -> list:
    """Taches pour lesquelles un protocole existe — les autres restent a ecrire."""
    return sorted(PROTOCOLS)


def run_bench(task: str, sample: str, *, models: Optional[list] = None, **options) -> list:
    """
    Passe chaque modele de `tache` sur `echantillon` et rend des mesures comparables.

    Un modele qui echoue n'interrompt pas le banc : il rend son erreur, parce qu'un modele
    illisible (poids TorchScript, format inattendu) est un RESULTAT — c'est ainsi qu'on a
    repere `yolopv2.pt`.
    """
    protocol = PROTOCOLS.get(task)
    if protocol is None:
        raise ValueError(
            f"Aucun protocole pour la tache '{task}'. Disponibles : {', '.join(available_tasks())}")

    candidates = CANDIDATES[task](sample) if task in CANDIDATES else models_for_task(task)
    if models:
        wanted = {m.strip() for m in models}
        candidates = [m for m in candidates if m.name in wanted or m.model_key in wanted]

    measures = []
    for m in candidates:
        try:
            measure = protocol(m, sample, **options)
            measure['error'] = None
        except Exception as e:
            measure = {'outputs': None, 'mean_confidence': None, 'load_s': None,
                      'inference_s': None, 'saturated': False, 'error': f"{type(e).__name__}: {e}"}
        measure['model'] = m.model_key
        measure['name'] = m.name
        measure['vram_gb'] = m.vram_gb
        measures.append(measure)
        logger.info("[bench:%s] %s -> %s", task, m.model_key, measure)
    return measures
