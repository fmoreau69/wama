"""
Client du registre Ollama PUBLIC — découverte déterministe, sans LLM.

Comble le trou (b) des « suites » de prospection (PROJECT_STATUS §2) : jusqu'ici les candidats
« nouveaux » venaient d'un seed codé en dur de 2 modèles, jamais rafraîchi — d'où des propositions
plus ANCIENNES que ce qui est déjà installé.

Trois surfaces, toutes vérifiées le 2026-08-04 :

  • `ollama.com/search?c=<capacité>` → liste de modèles par CAPACITÉ (`vision`, `embedding`,
    `tools`, `thinking`). C'est le levier qui permet d'élargir la prospection au-delà des LLM.
  • `ollama.com/library/<nom>`       → tags disponibles + résumé.
  • `registry.ollama.ai/v2/library/<nom>/manifests/<tag>` → 200/404 : EXISTENCE vérifiable.

Le troisième point est ce qui distingue ce module d'un scrapeur : on ne PROPOSE jamais un
`nom:tag` sans avoir vérifié qu'il est réellement tirable. (`/v2/.../tags/list` répond 404 sur ce
registre — la liste des tags vient donc de la page HTML, mais chaque tag retenu est re-validé
contre le manifeste.)

Sortie SORTANTE (Internet) : passe par `http_proxy.outbound_proxies()`, brique sœur de
`ollama_host` — celle-ci contourne le proxy pour l'hôte LOCAL, celle-là l'emprunte pour l'extérieur.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

BASE_SITE = 'https://ollama.com'
BASE_REGISTRY = 'https://registry.ollama.ai'

#: Capacités exposées par le filtre `?c=` du site.
CAPACITES = ('vision', 'embedding', 'tools', 'thinking')

_RE_LIB = re.compile(r'href="/library/([^"?:]+)"')
_RE_TAG_TMPL = r'href="/library/{}:([^"]+)"'


def _get(url: str, timeout: int = 20) -> str | None:
    """GET texte, best-effort : une indisponibilité réseau ne doit jamais lever ici — l'appelant
    distingue « rien trouvé » de « échec » via `None`, ce qui conditionne la purge des candidats."""
    import requests
    from wama.common.utils.http_proxy import outbound_proxies
    try:
        r = requests.get(url, timeout=timeout, proxies=outbound_proxies(),
                         headers={'User-Agent': 'wama/model-prospection'})
        r.raise_for_status()
        return r.text
    except Exception as exc:
        logger.info("[ollama_registry] %s indisponible : %s", url, exc)
        return None


@lru_cache(maxsize=32)
def rechercher(requete: str = '', capacite: str = '') -> tuple[str, ...] | None:
    """
    Noms de modèles de la bibliothèque, par requête libre et/ou capacité.

    L'ordre du site (popularité/actualité) est PRÉSERVÉ : c'est un signal de pertinence gratuit.
    Retourne `None` si la source est injoignable — à ne pas confondre avec un tuple vide.
    """
    params = []
    if requete:
        params.append(f'q={requete}')
    if capacite:
        params.append(f'c={capacite}')
    html = _get(f"{BASE_SITE}/search?{'&'.join(params)}")
    if html is None:
        return None
    vus, ordonnes = set(), []
    for nom in _RE_LIB.findall(html):
        if nom not in vus:
            vus.add(nom)
            ordonnes.append(nom)
    return tuple(ordonnes)


@lru_cache(maxsize=128)
def tags(nom: str) -> tuple[str, ...] | None:
    """Tags publiés pour un modèle de la bibliothèque (ordre du site préservé)."""
    html = _get(f"{BASE_SITE}/library/{nom}")
    if html is None:
        return None
    motif = re.compile(_RE_TAG_TMPL.format(re.escape(nom)))
    vus, ordonnes = set(), []
    for t in motif.findall(html):
        if t not in vus:
            vus.add(t)
            ordonnes.append(t)
    return tuple(ordonnes)


@lru_cache(maxsize=256)
def existe(nom: str, tag: str = 'latest') -> bool:
    """Le couple `nom:tag` est-il RÉELLEMENT tirable ? (manifeste du registre, 200 vs 404)."""
    import requests
    from wama.common.utils.http_proxy import outbound_proxies
    try:
        r = requests.get(f"{BASE_REGISTRY}/v2/library/{nom}/manifests/{tag}",
                         timeout=15, proxies=outbound_proxies(),
                         headers={'Accept': 'application/vnd.docker.distribution.manifest.v2+json'})
        return r.status_code == 200
    except Exception:
        return False


# ── Successeur de famille — le cœur du « qwen3.5 → qwen3.6 » ────────────────────

_RE_FAMILLE = re.compile(r'^([a-z][a-z\-]*?)(\d+(?:\.\d+)*)$')


def decomposer(nom: str) -> tuple[str, tuple[int, ...]] | None:
    """
    'qwen3.5' → ('qwen', (3, 5)) · 'gemma4' → ('gemma', (4,)) · 'translategemma' → None.

    Le suffixe numérique terminal est la convention de versionnage de la bibliothèque Ollama.
    Un nom sans suffixe n'a pas de notion de successeur : on retourne None plutôt que de deviner.
    """
    m = _RE_FAMILLE.match(nom.split(':')[0])
    if not m:
        return None
    return m.group(1), tuple(int(x) for x in m.group(2).split('.'))


def successeurs(nom_installe: str, catalogue: tuple[str, ...]) -> list[str]:
    """
    Modèles du `catalogue` qui sont une version SUPÉRIEURE de la même famille que `nom_installe`.

    Comparaison par tuple de version — `(3, 6) > (3, 5)`, et `(3, 10) > (3, 9)` là où une
    comparaison textuelle se tromperait.
    """
    ref = decomposer(nom_installe)
    if ref is None:
        return []
    prefixe, version = ref
    out = []
    for cand in catalogue:
        d = decomposer(cand)
        if d and d[0] == prefixe and d[1] > version:
            out.append((d[1], cand))
    return [c for _, c in sorted(out, reverse=True)]


#: Facteur de taille maximal toléré entre un modèle installé et son successeur proposé.
#: Sans ce garde-fou, `qwen3.5:4b` se voyait proposer `qwen3.6:27b` (seul tag publié le plus
#: proche) — soit ~7× la taille, intenable sur les 24 Go de la machine et contraire au choix
#: initial de l'utilisateur, qui avait retenu un petit modèle pour une raison.
FACTEUR_TAILLE_MAX = 2.0


def _milliards(tag: str):
    """'35b-a3b' → 35.0 · 'latest' → None. Le nombre de paramètres est le proxy de VRAM ici."""
    m = re.match(r'^(\d+(?:\.\d+)?)b', (tag or '').lower())
    return float(m.group(1)) if m else None


def tag_equivalent(nom_cible: str, tag_source: str) -> str | None:
    """
    Tag de `nom_cible` correspondant le mieux à `tag_source` — VÉRIFIÉ existant et de taille
    comparable.

    Priorité : tag identique (`9b`→`9b`), sinon la taille publiée la plus proche DANS la limite
    de `FACTEUR_TAILLE_MAX`, sinon `latest` (uniquement si la source n'a pas de taille connue).
    Retourne None si rien de tirable ET de raisonnable — « null plutôt que plausible » : mieux
    vaut ne rien proposer qu'une montée en gamme non désirée.
    """
    dispo = tags(nom_cible)
    src = _milliards(tag_source or '')

    if not dispo:
        # Sans liste de tags, on ne peut pas garantir la comparabilité de `latest` : on ne
        # l'accepte que si la source n'exprimait aucune taille.
        return 'latest' if (src is None and existe(nom_cible, 'latest')) else None

    if tag_source in dispo and existe(nom_cible, tag_source):
        return tag_source

    if src is not None:
        proches = sorted(
            ((abs(_milliards(t) - src), t) for t in dispo if _milliards(t) is not None),
            key=lambda x: x[0])
        for _, t in proches:
            if _milliards(t) <= src * FACTEUR_TAILLE_MAX and existe(nom_cible, t):
                return t
        return None      # une famille supérieure existe, mais aucune taille compatible
    return 'latest' if existe(nom_cible, 'latest') else None
