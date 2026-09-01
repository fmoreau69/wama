"""Adressage de l'hôte Ollama — brique commune.

Brique SŒUR de `http_proxy.py`, et de sens inverse : celui-ci sert à joindre l'extérieur
*à travers* le proxy UGE ; celui-ci sert à joindre un service **local** en le *contournant*.

Extraite de `wama-dev-ai/run_librarian.py` (2026-08-02), seule implémentation correcte du repo :
les ~11 autres points d'appel lisent `settings.OLLAMA_HOST` brut et tombent dans l'un des deux
pièges ci-dessous. Le besoin n'a rien de spécifique à un consommateur — toute app parlant à
Ollama le partage (describer, reader, model_manager, llm_utils, assistant…).

DEUX PIÈGES, tous deux vérifiés sur cette machine :

1. **WSL2 → hôte Windows.** Ollama tourne sur Windows ; depuis WSL2, `127.0.0.1` désigne la VM
   Linux, PAS l'hôte. Il faut l'IP de la passerelle par défaut. `start_wama_prod.sh` l'exporte
   déjà dans `OLLAMA_HOST` — mais tout process lancé hors de ce script (shell, cron, test,
   commande manuelle) hérite du défaut `127.0.0.1` et échoue silencieusement.

2. **Le proxy avale la passerelle.** Avec `http_proxy` positionné (cas courant sur le réseau UGE),
   `requests` route AUSSI `http://172.x.x.x:11434` vers le proxy, qui ne peut évidemment pas
   l'atteindre → `ReadTimeout` après le délai, pas une erreur de connexion franche. Symptôme
   trompeur : « Ollama ne répond pas » alors qu'il tourne parfaitement.

Le piège n°2 a une conséquence qui dépasse la connectivité : `prospect_ollama()` purge ses
candidats quand la liste des modèles revient vide. Un simple proxy mal contourné effaçait donc
des propositions valides.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: Adresse et réglage viennent du registre commun des sources externes (2026-09-01) : le défaut
#: ne vit plus qu'à un endroit. Ce module garde ce que le registre ne saurait faire — la
#: réécriture WSL2 → passerelle Windows ci-dessous.
_LOCAL = ('127.0.0.1', 'localhost')


def _sous_wsl() -> bool:
    try:
        return 'microsoft' in Path('/proc/version').read_text().lower()
    except OSError:
        return False


def _passerelle() -> str | None:
    """IP de la passerelle par défaut (= l'hôte Windows vu depuis WSL2)."""
    import subprocess
    try:
        out = subprocess.run(['sh', '-c', "ip route | awk '/default/ {print $3; exit}'"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def ollama_base() -> str:
    """
    URL de base d'Ollama, réécrite vers la passerelle quand on tourne sous WSL2 et que le
    réglage pointe encore sur la boucle locale. Sans réécriture possible, retourne le réglage
    tel quel (échouer visiblement vaut mieux qu'inventer une adresse).
    """
    from wama.common.external_sources import base_url
    base = base_url('ollama')

    if any(h in base for h in _LOCAL) and _sous_wsl():
        gw = _passerelle()
        if gw:
            base = re.sub(r'127\.0\.0\.1|localhost', gw, base)
        else:
            logger.warning("[ollama_host] WSL2 détecté mais passerelle introuvable — "
                           "les appels vers %s échoueront probablement", base)
    return base


def ollama_proxies() -> dict:
    """
    `proxies` à passer à `requests` pour NE PAS proxifier l'hôte Ollama.

    `requests` fusionne les proxies d'environnement par `setdefault` : une clé présente à `None`
    n'est donc pas remplacée par `http_proxy`, ce qui neutralise le proxy pour cet appel — sans
    toucher aux variables d'environnement du process (les autres appels sortants continuent de
    passer par le proxy, cf. `http_proxy.outbound_proxies`).

    Corps DÉPORTÉ dans la brique commune le 2026-08-31 (`http_proxy.local_proxies`) : le geste
    valait pour tout service LOCAL, pas pour le seul Ollama — le service TTS (:8001) l'a payé
    d'un repli en-process de 90 s le jour où `.env` a gagné `HTTP_PROXY`. Nom conservé : les
    appelants Ollama ne changent pas.
    """
    from wama.common.utils.http_proxy import local_proxies
    return local_proxies()


def ollama_kwargs(**extra) -> dict:
    """Raccourci pour `requests` :
    `requests.get(f'{ollama_base()}/api/tags', **ollama_kwargs(timeout=5))`.

    ⚠ Réservé à `requests`. Avec **httpx**, le contournement du proxy s'obtient par
    `httpx.Client(trust_env=False)` (déjà en place dans `llm_utils.ollama_chat`) : `proxies=`
    n'y a pas la même sémantique. Un appelant httpx n'a donc besoin que de `ollama_base()`.
    """
    return {'proxies': ollama_proxies(), **extra}
