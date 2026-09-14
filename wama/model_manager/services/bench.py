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
PLAFOND_DETECTIONS = 300

# Generation de texte : plafond de jetons produits par passe (`num_predict`). Meme lecture que
# PLAFOND_DETECTIONS — un modele qui atteint le plafond est SATURE, pas « prolixe ». La valeur
# est celle du banc llmfit (`bench.rs`, 2026-09-14) : assez longue pour que le debit se
# stabilise apres le prefill, assez courte pour qu'un lot de 3 passes tienne en une minute.
PLAFOND_TOKENS = 300
PASSES_GENERATION = 3
# Chargement a froid : en dessous de ce seuil, `load_duration` d'Ollama mesure un modele DEJA
# resident (quelques ms de re-attachement), pas un chargement — on ne l'apprend pas comme tel.
# Borne posee, pas mesuree : un chargement reel de poids se compte en secondes.
SEUIL_CHARGEMENT_FROID_S = 1.0


def models_for_task(tache: str, *, installes_seulement: bool = True):
    """Modeles du catalogue qui declarent cette tache. Le catalogue est la seule source."""
    qs = AIModel.objects.filter(is_available=True)
    if installes_seulement:
        qs = qs.filter(is_downloaded=True)
    return [m for m in qs if (m.capabilities or {}).get('task') == tache]


def _bench_detection(modele: AIModel, echantillon: str, *, conf: float = 0.25) -> dict:
    """Familles vision d'Ultralytics : detect, segment, obb, pose, classify."""
    from ultralytics import YOLO

    debut = time.perf_counter()
    y = YOLO(modele.local_path)
    charge = time.perf_counter() - debut

    debut = time.perf_counter()
    resultats = y.predict(echantillon, verbose=False, conf=conf, device=0)
    inference = time.perf_counter() - debut

    boites, confiances = 0, []
    for r in resultats:
        for b in (r.boxes or []):
            boites += 1
            try:
                confiances.append(float(b.conf))
            except Exception:
                pass

    return {
        'sorties': boites,
        'confiance_moyenne': round(sum(confiances) / len(confiances), 3) if confiances else None,
        'chargement_s': round(charge, 2),
        'inference_s': round(inference, 3),
        'sature': boites >= PLAFOND_DETECTIONS,
    }


def _bench_depth(modele: AIModel, echantillon: str, **_) -> dict:
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

    src = modele.local_path or modele.hf_id
    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    debut = time.perf_counter()
    processor = AutoImageProcessor.from_pretrained(src)
    model = AutoModelForDepthEstimation.from_pretrained(
        src, torch_dtype=torch.float16 if device == 'cuda' else torch.float32).to(device).eval()
    charge = time.perf_counter() - debut

    image = Image.open(echantillon).convert('RGB')
    w0, h0 = image.size
    inputs = processor(images=image, return_tensors='pt').to(device)

    debut = time.perf_counter()
    with torch.no_grad():
        outputs = model(**inputs)
    post = processor.post_process_depth_estimation(outputs, target_sizes=[(h0, w0)])[0]
    inference = time.perf_counter() - debut

    depth = post['predicted_depth'].float().cpu().numpy()
    focal = post.get('focal_length')
    if focal is not None:
        try:
            focal = round(float(np.asarray(focal).reshape(-1)[0]), 1)
        except Exception:
            focal = None
    valide = np.isfinite(depth) & (depth > 0)
    couverture = round(float(valide.mean()), 3) if depth.size else None
    mediane = round(float(np.median(depth[valide])), 2) if valide.any() else None

    return {
        'sorties': int(valide.sum()),                 # pixels de profondeur valide
        'confiance_moyenne': couverture,              # couverture [0..1] (reutilise la colonne)
        'chargement_s': round(charge, 2),
        'inference_s': round(inference, 3),
        'sature': False,
        'mediane_m': mediane,
        'focale_px': focal,
    }


def _bench_description(modele: AIModel, echantillon: str, **_) -> dict:
    """Modeles vision-langage servis par Ollama — protocole repris de `bench_describer`."""
    from wama.model_manager.services.vision_probe import describe_image_ollama

    debut = time.perf_counter()
    reponse = describe_image_ollama(echantillon, model=modele.name)
    duree = time.perf_counter() - debut
    # `describe_image_ollama` rend un dict {'ok', 'description'|'error'} — ce protocole le lisait
    # comme une chaine (`.strip()` sur un dict → AttributeError avale par `run_bench`, donc CHAQUE
    # modele de legendage sortait « en erreur »). Corrige le 2026-09-14 en ecrivant le protocole
    # voisin ; un echec de la sonde est un RESULTAT et se rapporte comme tel.
    if not reponse.get('ok'):
        raise RuntimeError(reponse.get('error') or 'sonde vision muette')
    texte = (reponse.get('description') or '').strip()
    return {
        'sorties': len(texte.split()) if texte else 0,
        'confiance_moyenne': None,
        'chargement_s': None,
        'inference_s': round(duree, 2),
        'sature': False,
        'texte': texte,
    }


def _lire_prompt(echantillon: str) -> str:
    """L'echantillon d'un banc de generation est un PROMPT : un fichier texte (chemin) ou la
    chaine elle-meme. Le fichier est la forme de la commande (`--media`), la chaine celle des
    appels programmatiques."""
    if echantillon and os.path.isfile(echantillon):
        return Path(echantillon).read_text(encoding='utf-8').strip()
    return (echantillon or '').strip()


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


def _ns_en_s(valeur) -> float:
    try:
        return round(float(valeur or 0) / 1e9, 3)
    except (TypeError, ValueError):
        return 0.0


def _bench_generation(modele: AIModel, echantillon: str, *, runs: int = PASSES_GENERATION,
                      num_predict: int = PLAFOND_TOKENS, **_) -> dict:
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
    if modele.source != 'ollama':
        raise ValueError(f"protocole Ollama seulement (source={modele.source!r})")
    prompt = _lire_prompt(echantillon)
    if not prompt:
        raise ValueError("prompt vide")

    chauffe = _ollama_generate(modele.name, 'Réponds simplement « ok ».', 8)
    chargement = _ns_en_s(chauffe.get('load_duration'))
    a_froid = chargement >= SEUIL_CHARGEMENT_FROID_S

    passes = []
    for i in range(max(int(runs), 1)):
        d = _ollama_generate(modele.name, prompt, num_predict)
        jetons = int(d.get('eval_count') or 0)
        duree = _ns_en_s(d.get('eval_duration'))
        passe = {
            'jetons': jetons,
            'generation_s': duree,
            'tokens_par_s': round(jetons / duree, 1) if jetons and duree else None,
            'prefill_ms': round(float(d.get('prompt_eval_duration') or 0) / 1e6, 1),
            'prompt_jetons': int(d.get('prompt_eval_count') or 0),
        }
        passes.append(passe)
        if jetons and duree:
            record_run(modele.model_key, size=jetons, unit='token', process_seconds=duree,
                       load_seconds=chargement if (a_froid and i == 0) else None)

    debits = [p['tokens_par_s'] for p in passes if p['tokens_par_s']]
    return {
        'sorties': round(sum(p['jetons'] for p in passes) / len(passes)),
        'confiance_moyenne': None,
        'chargement_s': chargement if a_froid else None,
        'inference_s': round(sum(p['generation_s'] for p in passes) / len(passes), 3),
        'sature': all(p['jetons'] >= num_predict for p in passes),
        'tokens_par_s': round(sum(debits) / len(debits), 1) if debits else None,
        'prefill_ms': round(sum(p['prefill_ms'] for p in passes) / len(passes), 1),
        'passes': passes,
    }


# Un protocole par FAMILLE de tache. Ajouter une tache = ajouter une entree ici, jamais une
# commande de plus.
PROTOCOLES: dict[str, Callable] = {
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
    return sorted(PROTOCOLES)


def run_bench(tache: str, echantillon: str, *, modeles: Optional[list] = None, **options) -> list:
    """
    Passe chaque modele de `tache` sur `echantillon` et rend des mesures comparables.

    Un modele qui echoue n'interrompt pas le banc : il rend son erreur, parce qu'un modele
    illisible (poids TorchScript, format inattendu) est un RESULTAT — c'est ainsi qu'on a
    repere `yolopv2.pt`.
    """
    protocole = PROTOCOLES.get(tache)
    if protocole is None:
        raise ValueError(
            f"Aucun protocole pour la tache '{tache}'. Disponibles : {', '.join(available_tasks())}")

    candidats = models_for_task(tache)
    if modeles:
        voulus = {m.strip() for m in modeles}
        candidats = [m for m in candidats if m.name in voulus or m.model_key in voulus]

    mesures = []
    for m in candidats:
        try:
            mesure = protocole(m, echantillon, **options)
            mesure['erreur'] = None
        except Exception as e:
            mesure = {'sorties': None, 'confiance_moyenne': None, 'chargement_s': None,
                      'inference_s': None, 'sature': False, 'erreur': f"{type(e).__name__}: {e}"}
        mesure['modele'] = m.model_key
        mesure['nom'] = m.name
        mesure['vram_gb'] = m.vram_gb
        mesures.append(mesure)
        logger.info("[bench:%s] %s -> %s", tache, m.model_key, mesure)
    return mesures
