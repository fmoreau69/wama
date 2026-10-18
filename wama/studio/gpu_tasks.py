"""Tâches GPU du studio — routées sur la file `gpu` (settings `CELERY_TASK_ROUTES`), PAS sur la
file `studio` : celle-ci est l'ORCHESTRATEUR (solo, un run la retient le temps d'un poll) ; y
faire tourner une inférence bloquerait tous les runs et échapperait au gouverneur VRAM.

`image_to_3d_task` = l'`impl` de la fonction `studio.image_to_3d` (§17ter trou 4).
"""
import logging
import os

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def image_to_3d_task(self, image, user_id: int, resolution: int = 256, foreground_ratio: float = 0.85,
                     model: str = 'huggingface:triposr', asset_name: str = ''):
    """Image (chemin RELATIF à MEDIA_ROOT, fourni par le port `image`) → GLB chez l'utilisateur.

    Rend le chemin RELATIF du GLB — l'exécuteur du studio reconnaît un chemin média et le
    transmet au nœud « Sortie » comme un fichier (pas un texte).
    """
    from django.conf import settings

    from django.contrib.auth import get_user_model

    from wama.common.backends.manager import backend_for_key
    from wama.common.utils.media_paths import app_media_dir, resolve_under_media_root
    from wama.common.utils.model_readiness import ensure_installed
    from wama.common.utils.task_skeleton import ServiceNotReady, redeliver_later

    src, _rel_src = resolve_under_media_root(image)       # confinement : une entrée vient d'une donnée
    src = str(src)
    # Le modèle absent : la ROUTE l'installe et la tâche revient d'elle-même (2026-10-16, décision
    # de Fabien) — la même politique que le squelette, hors squelette : une re-livraison Celery.
    try:
        ensure_installed(model, user=get_user_model().objects.filter(pk=user_id).first(),
                         redelivered=bool(self.request.retries))
    except ServiceNotReady as wait:
        logger.info('[studio] image_to_3d : %s', wait)
        redeliver_later(self, wait)
    cls = backend_for_key(model)
    if cls is None:
        raise ValueError(f"aucun moteur ne pilote le modèle {model!r} (backend introuvable)")
    manques = cls.missing_packages()
    if manques:
        raise RuntimeError(f"{cls.__name__} indisponible — manque : {', '.join(manques)}")

    base = (asset_name or '').strip() or os.path.splitext(os.path.basename(src))[0]
    rel_dir = app_media_dir('studio', user_id, 'output')
    rel = f"{rel_dir}/{base}_3d.glb"
    out = os.path.join(settings.MEDIA_ROOT, rel)
    k = 2
    while os.path.exists(out):
        rel = f"{rel_dir}/{base}_3d ({k}).glb"
        out = os.path.join(settings.MEDIA_ROOT, rel)
        k += 1

    be = cls()
    try:
        be.load()
        be.process(image_path=src, output_path=out, resolution=int(resolution),
                   foreground_ratio=float(foreground_ratio))
    finally:
        be.unload()
    logger.info('[studio] image_to_3d %s → %s', image, rel)
    return rel
