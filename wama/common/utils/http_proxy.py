"""Proxy HTTP sortant — brique commune.

Extrait de `cam_analyzer/utils/ortho_markings.py` (2026-07-29) : le besoin n'a rien de
spécifique au cam_analyzer — toute app joignant un service externe depuis WSL2 derrière le
proxy UGE le partage (tuiles IGN, WFS BD TOPO, et tout futur appel sortant).

Ordre de résolution : réglage Django dédié, puis `HTTPS_PROXY`/`HTTP_PROXY` de
l'environnement (les workers Celery en héritent en général).
"""
import os


def outbound_proxies(setting_name: str = 'WAMA_OUTBOUND_PROXY'):
    """Dict `proxies` pour `requests`, ou None si aucun proxy n'est configuré.

    `setting_name` permet de conserver un réglage historique par domaine
    (ex. `CAM_ANALYZER_ORTHO_PROXY`) sans le dupliquer ici.
    """
    p = None
    try:
        from django.conf import settings
        p = getattr(settings, setting_name, None) or getattr(settings, 'WAMA_OUTBOUND_PROXY', None)
    except Exception:
        p = None
    p = p or os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
    return {'http': p, 'https': p} if p else None


def local_proxies() -> dict:
    """Dict `proxies` qui NEUTRALISE le proxy pour un service LOCAL (localhost/127.0.0.1).

    Le besoin est l'exact opposé d'`outbound_proxies` et il n'a rien de spécifique à un
    service : dès que `.env` pose `HTTP_PROXY` (proxy UGE) SANS `NO_PROXY`, `requests`
    envoie AUSSI les appels à `localhost` au proxy — qui répond par sa page d'erreur HTML.
    L'appelant croit alors son service en panne.

    ⚠ MESURÉ le 2026-08-31, c'est un vrai incident, pas une précaution : `.env` a gagné
    `HTTP_PROXY` à 16:20 ; à 17:18 la vocalisation de l'assistant recevait
    « <!DOCTYPE html…><title>ERROR: The requested… » à la place de l'audio du service TTS
    (:8001), basculait sur son repli EN-PROCESS et chargeait un Kokoro `.pt` DANS le worker
    gunicorn (~90 s + VRAM prise côté web). Le service, lui, était parfaitement joignable.

    Mécanique : `requests` fusionne les proxies d'environnement par `setdefault` — une clé
    présente à `None` n'est donc pas remplacée par `http_proxy`. On neutralise pour CET
    appel, sans toucher à l'environnement du process (les appels sortants continuent de
    passer par le proxy).

    Domicile UNIQUE de ce geste : `ollama_host.ollama_proxies()` le portait seul depuis
    2026-07, alors que la panne vise tout service local.
    """
    return {'http': None, 'https': None}
