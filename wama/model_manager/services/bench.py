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
    banc parce qu'aucune app LLM ne l'appelle. Rien d'autre n'est ecrit : ni `vram_gb`, ni
    un indice de qualite.

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

    warmup = _ollama_generate(entry.name, 'Réponds simplement « ok ».', 8)
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
}


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

    candidates = models_for_task(task)
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
