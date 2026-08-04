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
"""
import logging
import time
from typing import Callable, Optional

from wama.model_manager.models import AIModel, ModelTask

logger = logging.getLogger(__name__)

# Ultralytics plafonne les detections a 300 par defaut. Un compte EXACTEMENT egal a cette valeur
# est une saturation, pas une performance : on le signale au lieu de le presenter comme un score.
PLAFOND_DETECTIONS = 300


def modeles_pour_tache(tache: str, *, installes_seulement: bool = True):
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


def _bench_description(modele: AIModel, echantillon: str, **_) -> dict:
    """Modeles vision-langage servis par Ollama — protocole repris de `bench_describer`."""
    from wama.model_manager.services.vision_probe import describe_image_ollama

    debut = time.perf_counter()
    texte = describe_image_ollama(echantillon, model=modele.name)
    duree = time.perf_counter() - debut
    texte = (texte or '').strip()
    return {
        'sorties': len(texte.split()) if texte else 0,
        'confiance_moyenne': None,
        'chargement_s': None,
        'inference_s': round(duree, 2),
        'sature': False,
        'texte': texte,
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
}


def taches_disponibles() -> list:
    """Taches pour lesquelles un protocole existe — les autres restent a ecrire."""
    return sorted(PROTOCOLES)


def lancer(tache: str, echantillon: str, *, modeles: Optional[list] = None, **options) -> list:
    """
    Passe chaque modele de `tache` sur `echantillon` et rend des mesures comparables.

    Un modele qui echoue n'interrompt pas le banc : il rend son erreur, parce qu'un modele
    illisible (poids TorchScript, format inattendu) est un RESULTAT — c'est ainsi qu'on a
    repere `yolopv2.pt`.
    """
    protocole = PROTOCOLES.get(tache)
    if protocole is None:
        raise ValueError(
            f"Aucun protocole pour la tache '{tache}'. Disponibles : {', '.join(taches_disponibles())}")

    candidats = modeles_pour_tache(tache)
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
