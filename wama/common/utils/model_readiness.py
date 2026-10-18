"""Un modèle s'INSTALLE par la route avant de servir — et l'utilisateur le sait.

DEPUIS LE 2026-10-16 (décision de Fabien, règle « librairies et modèles par la route » d'`AGENTS.md`) :
*« Ce n'est pas une dérive [de télécharger au moment du besoin]. La dérive arrive si l'installation
n'est pas complète. Mais il faut bien prévenir l'utilisateur. La tâche attendra jusqu'à ce que
l'installation soit complètement faite, proprement et alignée sur la route. »*

  • `ensure_installed` — pour une TÂCHE : un modèle du catalogue absent que la route sait installer
    (`model_installer.spec_for_catalog_row`) est installé PAR elle (`request_install` : garde
    d'espace disque, journal, jeton, provenance — la même que le bouton), l'utilisateur est
    prévenu, et la tâche ATTEND sans tenir son worker (`task_skeleton.ServiceNotReady` : elle
    revient d'elle-même, la card dit qu'elle attend). Une installation refusée (disque plein…) ou
    échouée fait échouer la tâche EN LE DISANT — jamais un téléchargement « au chargement » à côté.
    Une glu l'appelle par `ctx.ensure_model(clé)` (`task_skeleton.TaskContext`), une tâche hors
    squelette par `redeliver_later` ;
  • `install_and_wait` — le même geste pour un appelant SYNCHRONE (une commande : le banc) ;
  • `warn_if_weights_missing` — l'ancienne annonce, gardée pour la seule ligne que la route ne
    sait pas installer (aucun emplacement déclaré) : son backend télécharge au chargement, par un
    levier de `hf_weights` — on le dit.

Ce qui suit est l'en-tête d'origine de l'annonce (2026-09-08).

Prévenir l'utilisateur qu'un premier lancement va TÉLÉCHARGER les poids.

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

#: En-dessous, on ne MENTIONNE PAS le volume : l'avertissement a lieu de toute façon
#: (`volume = '' if taille < seuil`). ⚠ L'ancien libellé disait « l'annonce serait du
#: bruit » — un constat FAUX, que l'ancien nom `SEUIL_ANNONCE_GO` transportait.
SIZE_MENTION_THRESHOLD_GB = 0.5


def _volume(row) -> str:
    """« (~N Go) » quand le volume est CONNU et notable, '' sinon : `disk_gb` vaut 0 tant que le
    modèle n'a jamais été téléchargé (il se remplit au balayage) — on ne prétend pas connaître un
    volume jamais mesuré."""
    size = float(getattr(row, 'disk_gb', 0) or 0)
    return f' (~{size:.0f} Go)' if size >= SIZE_MENTION_THRESHOLD_GB else ''


def warn_if_weights_missing(model_key: str, console=None) -> bool:
    """Prévient (console) si les poids de `model_key` sont ABSENTS. Rend True si prévenu.

    ⚠ Le nom dit la CONDITION, pas un téléchargement : cette brique ne télécharge rien
    (cf. l'entête). Elle s'appelait `annoncer_telechargement` jusqu'au 2026-09-19 —
    remarque de Fabien : « la terminologie n'est pas correcte ». *Traduire ne suffit
    pas : le nom anglais doit encore dire ce que la chose EST.*

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
    message = (f"Premier lancement de « {nom} » : téléchargement des poids{_volume(ligne)} en cours — "
               f"cela peut prendre plusieurs minutes. Les lancements suivants seront immédiats.")
    logger.info('[readiness] %s : poids absents, annonce faite', model_key)
    if console:
        try:
            console(message)
        except Exception:
            pass
    return True


#: L'attente d'une installation : un tour toutes les 30 s, au plus la durée de vie de l'avancement
#: d'une installation (`model_manager.tasks.INSTALL_TTL`, lue à l'appel — au-delà, l'avancement
#: n'est plus lisible).
INSTALL_POLL_S = 30


def _max_wait_s() -> int:
    from wama.model_manager.tasks import INSTALL_TTL
    return int(INSTALL_TTL)


class ModelInstallRefused(RuntimeError):
    """La route n'a pas installé le modèle (refus ou échec) : la tâche échoue en le DISANT."""


def _route_row(model_key: str):
    """(ligne, spec de la route) d'un modèle du catalogue ABSENT que la route sait installer ;
    (ligne, None) s'il est absent sans emplacement déclaré ; (None, None) s'il n'y a rien à
    faire (installé, hors catalogue, catalogue illisible)."""
    try:
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_installer import spec_for_catalog_row
        row = AIModel.objects.filter(model_key=model_key, is_proposed=False).first()
    except Exception as e:
        logger.debug('[readiness] catalogue illisible pour %s : %s', model_key, e)
        return None, None
    if row is None or row.is_downloaded:
        return None, None
    return row, spec_for_catalog_row(row)


def _last_install(model_key: str) -> dict:
    """L'état publié par la DERNIÈRE installation de ce modèle (`INSTALL_CACHE_PREFIX`), {} sinon."""
    try:
        from django.core.cache import cache
        from wama.model_manager.tasks import INSTALL_CACHE_PREFIX
        return cache.get(INSTALL_CACHE_PREFIX + model_key) or {}
    except Exception:
        return {}


def _start_install(row, user, via: str) -> str:
    """Demande l'installation par LA route ; rend '' si elle part ou tourne déjà, sinon le motif
    du refus, dit à l'utilisateur."""
    from wama.model_manager.services.model_installer import request_install
    res = request_install(row.model_key, user=user, via=via)
    if res.get('ok') or res.get('reason') == 'already_downloaded':
        return ''
    if res.get('reason') == 'insufficient_storage':
        blocked = res.get('blocked') or {}
        return (f"espace disque insuffisant pour installer « {row.name} »"
                + (f" ({blocked.get('message')})" if blocked.get('message') else '')
                + " — libérer de la place depuis le model manager, puis relancer")
    return res.get('error') or res.get('reason') or 'installation refusée'


def _announce(row, console) -> None:
    if not console:
        return
    try:
        console(f"« {row.name} » n'est pas installé : installation par le model manager{_volume(row)} — "
                f"la tâche attend qu'elle soit COMPLÈTE, puis reprend d'elle-même.")
    except Exception:
        pass


def ensure_installed(model_key: str, *, user=None, console=None, redelivered: bool = False,
                     via: str = 'task') -> bool:
    """Pour une TÂCHE : rend True quand le modèle est prêt à servir (ou que rien ne le concerne).

    Lève `task_skeleton.ServiceNotReady` tant que la route installe (la tâche rend son worker et
    revient) ; `ModelInstallRefused` si la route refuse ou si l'installation que la tâche attendait
    a échoué. `redelivered` : la tâche revient d'une attente — une installation ÉCHOUÉE se dit
    alors au lieu d'être relancée en boucle ; un nouveau lancement, lui, la retente."""
    if not model_key:
        return True
    row, spec = _route_row(model_key)
    if row is None:
        return True
    if spec is None:
        # Aucun emplacement déclaré : le backend tirera ses poids au chargement (levier de
        # `hf_weights`) — l'annonce d'origine le dit.
        warn_if_weights_missing(model_key, console=console)
        return True
    from wama.common.utils.task_skeleton import ServiceNotReady
    last = _last_install(model_key)
    if redelivered and last.get('state') == 'FAILURE':
        raise ModelInstallRefused(f"L'installation de « {row.name} » a échoué : "
                                  f"{last.get('error') or 'cause non publiée'}")
    refusal = _start_install(row, user, via)
    if refusal:
        raise ModelInstallRefused(f"« {row.name} » n'est pas installé : {refusal}")
    if not redelivered:
        _announce(row, console)
    max_wait = _max_wait_s()
    raise ServiceNotReady(
        f"Installation de « {row.name} » en cours par le model manager",
        countdown=INSTALL_POLL_S, max_attempts=max_wait // INSTALL_POLL_S,
        gave_up=f"« {row.name} » toujours pas installé après {max_wait // 3600} h "
                "d'attente — voir le journal des installations du model manager")


def install_and_wait(model_key: str, *, user=None, console=None, via: str = 'command',
                     poll_s: float = 5, timeout_s: float = None) -> bool:
    """Le même geste pour un appelant SYNCHRONE (une commande, jamais un worker) : installe par la
    route et ATTEND la fin. Rend True quand le modèle est installé, lève `ModelInstallRefused` si
    la route refuse, échoue ou ne finit pas à temps ; False si la route ne sait pas l'installer."""
    import time
    row, spec = _route_row(model_key)
    if row is None:
        return True
    if spec is None:
        return False
    refusal = _start_install(row, user, via)
    if refusal:
        raise ModelInstallRefused(f"« {row.name} » n'est pas installé : {refusal}")
    _announce(row, console)
    timeout_s = _max_wait_s() if timeout_s is None else timeout_s
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        row.refresh_from_db(fields=['is_downloaded'])
        if row.is_downloaded:
            return True
        last = _last_install(model_key)
        if last.get('state') == 'FAILURE':
            raise ModelInstallRefused(f"L'installation de « {row.name} » a échoué : "
                                      f"{last.get('error') or 'cause non publiée'}")
    raise ModelInstallRefused(f"« {row.name} » toujours pas installé après {timeout_s:.0f} s")
