"""
Suivre la tête de lecture — la boucle « au fil de la lecture » COMMUNE.

Née dans le cam_analyzer (mode Live, 2026-07-18/19 : `live_analysis_task` + vue `live_cursor`),
extraite le 2026-09-24 quand le transcriber en est devenu le 2ᵉ utilisateur (modes d'écriture de
l'éditeur de correction). Ce qui est commun, c'est la MÉCANIQUE, jamais le traitement :

  • le navigateur POSE un curseur (où en est la lecture, et ce qu'il veut voir traité) ;
  • une tâche longue le SUIT : elle traite une tranche à la fois, modèle gardé chargé entre deux ;
  • elle s'arrête d'elle-même — arrêt demandé, inactivité, ou traitement prioritaire à laisser
    passer (le slot GPU est partagé : une analyse ou une transcription en file ne doit jamais
    attendre qu'un utilisateur ait fini d'écouter).

Chaque garde a son cas VÉCU, et c'est pourquoi elle est ici plutôt que réécrite par app :
  – verrou de LANCEMENT (`cache.add`, 15 s) : sans lui, chaque envoi de curseur pendant que la file
    GPU est occupée empilait une tâche — 1 440 messages en file mesurés le 2026-07-19 ;
  – verrou d'EXÉCUTION avec battement (30 s) : une seule boucle par canal, et un verrou qui meurt
    avec son processus ;
  – REFROIDISSEMENT après cession (30 s) : sortie silencieuse des tâches empilées entre-temps ;
  – cession au traitement PRIORITAIRE : sinon il restait > 5 min en file et le chien de garde le
    déclarait « worker mort » (constat utilisateur du 2026-07-19).

⚠ Les clés de cache sont `<préfixe>_<nature>_<identifiant>` — celles que le cam_analyzer écrivait
à la main (`cam_live_lock_<session>`…). Les garder à l'identique est ce qui rend le portage neutre.

Ce que la brique ne sait PAS : ce qu'est une tranche, quel modèle charger, où ranger le résultat.
L'app les fournit (`on_start`, `step`, `should_yield`) ; le curseur est un dict qu'elle définit.
Ce n'est pas encore le « curseur de session » du chantier transport (`WAMA_DATA_WORLD §5`) : c'est
sa première forme, un curseur par canal, que ce chantier pourra absorber.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from django.core.cache import cache

#: Durée de vie d'un curseur : sans nouvel envoi, la boucle le voit disparaître puis s'éteint.
CURSOR_TTL = 120
#: Verrou d'exécution, rafraîchi à chaque tour (battement) : il meurt avec sa boucle.
LOCK_TTL = 30
#: Verrou de lancement : un seul démarrage en vol, levé par la tâche dès qu'elle démarre.
SPAWN_TTL = 15
#: Refroidissement après une cession au traitement prioritaire.
COOLDOWN_TTL = 30
#: Inactivité (s) au-delà de laquelle la boucle s'arrête d'elle-même.
IDLE_SECONDS = 90
#: Pause entre deux tours sans travail.
POLL_SECONDS = 0.7
#: Fréquence (s) de la question « un traitement prioritaire attend-il ? ».
YIELD_CHECK_SECONDS = 3.0


class Channel:
    """Un canal de suivi : un préfixe par app, un identifiant par objet suivi."""

    def __init__(self, prefix: str, ident):
        self.prefix, self.ident = prefix, str(ident)

    def key(self, kind: str) -> str:
        return f"{self.prefix}_{kind}_{self.ident}"

    def is_running(self) -> bool:
        return bool(cache.get(self.key('lock')))


def post_cursor(channel: Channel, cursor: Optional[dict], spawn: Callable[[], None]) -> dict:
    """Pose le curseur envoyé par le navigateur, et lance la boucle si aucune ne tourne.

    `cursor=None` = le suivi est désactivé : le curseur est effacé et, si une boucle tourne, elle
    reçoit l'ordre de s'arrêter TOUT DE SUITE (sans attendre son délai d'inactivité).
    `spawn` démarre la tâche (typiquement `ma_tache.delay(...)`) ; il n'est appelé qu'une fois par
    fenêtre de lancement. Rend `{'running': bool, 'started': bool}`.
    """
    if cursor is None:
        cache.delete(channel.key('cursor'))
        running = channel.is_running()
        if running:
            cache.set(channel.key('stop'), 'user', timeout=CURSOR_TTL)
        return {'running': running, 'started': False}
    cache.set(channel.key('cursor'), cursor, timeout=CURSOR_TTL)
    started = False
    if not channel.is_running() and cache.add(channel.key('spawn'), 1, timeout=SPAWN_TTL):
        spawn()
        started = True
    return {'running': True, 'started': started}


def follow(channel: Channel, owner: str, step: Callable[[dict], bool], *,
           on_start: Optional[Callable[[], None]] = None,
           should_yield: Optional[Callable[[], bool]] = None,
           idle_seconds: float = IDLE_SECONDS, poll_seconds: float = POLL_SECONDS,
           clock: Callable[[], float] = time.time,
           sleep: Callable[[float], None] = time.sleep) -> str:
    """La boucle : suit le curseur du canal jusqu'à ce qu'une raison de s'arrêter survienne.

    `step(curseur)` traite UNE tranche et rend True s'il a travaillé (False : rien à faire à cet
    endroit, la boucle patiente). `on_start` est appelé une fois le verrou acquis — c'est là que
    l'app charge son modèle, jamais avant (une tâche qui n'obtient pas le verrou ne doit rien
    charger). `should_yield()` vrai = un traitement prioritaire attend : la boucle cède.

    Rend la raison de l'arrêt : `'idle'`, `'user'` (ou la valeur posée sur la clé d'arrêt),
    `'preempt'`, et avant tout travail `'cooldown'` ou `'already_running'`.
    Une exception de `step` ou `on_start` REMONTE (le verrou est tout de même libéré).
    """
    cache.delete(channel.key('spawn'))           # le lancement a abouti : on lève son verrou
    if cache.get(channel.key('cool')):
        return 'cooldown'                         # sortie SILENCIEUSE : draine un arriéré empilé
    if not cache.add(channel.key('lock'), owner, timeout=LOCK_TTL):
        return 'already_running'
    try:
        if on_start:
            on_start()
        last_work, last_check = clock(), 0.0
        while True:
            cache.set(channel.key('lock'), owner, timeout=LOCK_TTL)      # battement du verrou
            stop = cache.get(channel.key('stop'))
            if stop:
                cache.delete(channel.key('stop'))
                return stop if isinstance(stop, str) else 'user'
            if should_yield and clock() - last_check > YIELD_CHECK_SECONDS:
                last_check = clock()
                if should_yield():
                    cache.set(channel.key('cool'), 1, timeout=COOLDOWN_TTL)
                    return 'preempt'
            cursor = cache.get(channel.key('cursor'))
            if not cursor:
                if clock() - last_work > idle_seconds:
                    return 'idle'
                sleep(poll_seconds)
                continue
            if step(cursor):
                last_work = clock()
            else:
                sleep(poll_seconds)
    finally:
        cache.delete(channel.key('lock'))
