"""Prévenir l'utilisateur qu'un premier lancement va TÉLÉCHARGER les poids.

POURQUOI (2026-09-08, constat de Fabien) : « pour les modèles qui ont leurs poids absents, c'est
juste qu'ils n'ont jamais été utilisés — à la première utilisation les poids sont automatiquement
téléchargés ; il faudrait vérifier si un message prévient l'utilisateur avant le lancement de la
tâche, sur la card, dans le cycle de vie ».

Vérifié : le téléchargement automatique existe bel et bien (37 appels `from_pretrained` /
`snapshot_download` dans les backends), mais **AUCUNE couche ne l'annonçait** — ni le squelette
commun, ni les backends, ni la card. Mesuré le même jour : 4 modèles catalogués sont
`is_downloaded=False` (mochi-1-preview 22 Go de VRAM, qwen-image-edit, flux2-klein-4b,
musicgen-melody). Les lancer produit une tâche qui démarre et ne bouge pas pendant le temps de
récupérer plusieurs dizaines de Go, sans un mot.

*Une attente qu'on n'explique pas se lit comme une panne.* Le catalogue SAIT déjà
(`is_downloaded`, `disk_gb`) : il n'y avait qu'à le dire.

⚠ CE QUE CETTE BRIQUE NE FAIT PAS : elle ne télécharge rien, ne bloque rien et ne décide rien.
Elle ANNONCE. Le téléchargement reste le fait du backend, au moment où il charge — c'est lui qui
sait quoi chercher. Un modèle absent du catalogue ou déjà présent ne produit aucun message : on
ne parle que de ce qu'on sait.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: En-dessous, le téléchargement est imperceptible et l'annonce serait du bruit.
SEUIL_ANNONCE_GO = 0.5


def annoncer_telechargement(model_key: str, console=None) -> bool:
    """Prévient (console) si les poids de `model_key` sont absents. Rend True si annoncé.

    `model_key` : clé de catalogue (`<source>:<id>`) — la même que celle qui résout le backend
    (`backend_for_key`), pour que l'annonce et l'exécution parlent du MÊME modèle.

    Best-effort intégral : une base indisponible, une ligne absente ou une console qui lève ne
    doivent JAMAIS empêcher une tâche de tourner. Prévenir est un confort, pas une condition.
    """
    if not model_key:
        return False
    try:
        from wama.model_manager.models import AIModel
        ligne = AIModel.objects.filter(model_key=model_key).only(
            'model_key', 'name', 'is_downloaded', 'disk_gb').first()
    except Exception as e:
        logger.debug('[readiness] catalogue illisible pour %s : %s', model_key, e)
        return False
    if ligne is None or ligne.is_downloaded:
        return False

    nom = ligne.name or model_key.rsplit(':', 1)[-1]
    taille = float(ligne.disk_gb or 0)
    # `disk_gb` vaut 0 tant que le modèle n'a jamais été téléchargé (il se remplit au balayage) :
    # on ne prétend donc pas connaître le volume quand on ne l'a jamais mesuré.
    volume = f' (~{taille:.0f} Go)' if taille >= SEUIL_ANNONCE_GO else ''
    message = (f"Premier lancement de « {nom} » : téléchargement des poids{volume} en cours — "
               f"cela peut prendre plusieurs minutes. Les lancements suivants seront immédiats.")
    logger.info('[readiness] %s : poids absents, annonce faite', model_key)
    if console:
        try:
            console(message)
        except Exception:
            pass
    return True
