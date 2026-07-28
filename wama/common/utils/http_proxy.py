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
