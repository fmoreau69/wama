"""Quotas des SERVICES EXTERNES — une seule brique pour tous (`ROADMAP §8d` étape 3, 2026-10-14).

Demande de Fabien : « un fonctionnement unique, commun et centralisé ». Avant elle, cinq endroits
géraient un refus de débit (HTTP 429) chacun à sa façon — le chat (`llm_utils`), la transcription
d'Albert, les moteurs de recherche, la prospection (Hub, Artificial Analysis, GitHub) — et aucun
ne COMPTAIT : on découvrait la limite en la heurtant (jusqu'à 83,8 s d'attente mesurées).

Trois choses vivent ici, et seulement ici :

1. La NOTE de saturation (étape 2, déménagée de `cloud_models` le 14/10) : une source qui vient
   de refuser — limite de débit de la clé, ou panne — est écartée du tirage automatique le temps
   de la note.
2. Le COMPTE : chaque appel servi est compté par (source, portée de la clé, modèle), par fenêtre
   fixe d'une minute et d'un jour, en requêtes et en jetons quand on les connaît.
3. Les PLAFONDS, de trois origines :
   - DÉCLARÉS sur la source (`ExternalSource.quotas`, un `Quota` par limite) — la source le porte
     par défaut, et un `Quota` peut ne viser que certains de ses modèles (`models`) ou chacun
     séparément (`per_model`) : chez Albert la limite dépend du modèle, chez OpenRouter les
     modèles gratuits partagent UN compteur ;
   - APPRIS au premier refus réel : le nombre compté dans la fenêtre quand le 429 tombe devient le
     plafond de cette clé, pour ce modèle. Un service qui n'annonce rien (ILaaS, mesuré le 14/10)
     n'est donc jamais bloqué par le compte — jusqu'au jour où il refuse, et alors une seule fois ;
   - le plafond le plus BAS l'emporte.

Portée : la CLÉ, pas l'utilisateur — la sienne s'il l'a posée (`user:<pk>`), sinon la clé
d'instance (`instance`), partagée par tous ceux qui n'ont pas la leur (ILaaS : tout le labo sur un
seul quota). Une panne vaut pour toutes les clés (`ALL_KEYS`).

Tout vit dans le cache PARTAGÉ (Redis) : les workers web et Celery voient les mêmes comptes. Rien
ici ne lève : sans cache, on perd la mémoire du débit, jamais l'appel.
"""
from __future__ import annotations

import logging
import time

from wama.common.external_sources import Quota

logger = logging.getLogger(__name__)

#: Préfixe de la note de saturation — le même qu'à l'étape 2 : une note posée avant le
#: déménagement reste lue.
SATURATION_CACHE_PREFIX = 'wama:cloud_saturated:'
COUNT_PREFIX = 'wama:quota:n:'
LEARNED_PREFIX = 'wama:quota:learned:'
#: Durée de la note d'une PANNE (5xx, connexion refusée, délai dépassé) : rien ne dit quand le
#: fournisseur revient, on réessaie au bout de quelques minutes.
OUTAGE_NOTE_S = 180.0
SATURATION_NOTE_MAX_S = 3600.0
#: Portée d'une panne : le fournisseur, pour toutes les clés.
ALL_KEYS = 'all'

MINUTE = 60
DAY = 86400
#: Les fenêtres toujours comptées — celles qu'un plafond APPRIS peut viser.
COUNTED_WINDOWS = (MINUTE, DAY)
REQUESTS = 'requests'
TOKENS = 'tokens'
#: Un plafond appris se réapprend : la clé peut changer de palier, le service relever sa limite.
LEARNED_TTL_S = DAY
#: Motif affiché quand le COMPTE (et non un refus) écarte la source.
QUOTA_REACHED = 'quota atteint'


# ── Portée et note de saturation ───────────────────────────────────────────────────────────

def saturation_scope(user, source: str) -> str:
    """Portée de la limite de `source` pour `user` — elle tient à la CLÉ : la sienne s'il l'a
    posée, sinon la clé d'instance (partagée, ou seule en usage sans utilisateur). Même règle que
    `api_keys.key_for`."""
    if user is not None and getattr(user, 'is_authenticated', False):
        from wama.accounts.models import UserApiKey
        if UserApiKey.objects.filter(user=user, source=source).exclude(api_key='').exists():
            return f'user:{user.pk}'
    return 'instance'


def note_saturation(source: str, *, scope: str, seconds: float, reason: str) -> None:
    """Note `source` saturée pour la portée `scope` (`saturation_scope`, ou `ALL_KEYS` pour une
    panne) pendant `seconds`."""
    from django.core.cache import cache
    seconds = min(max(float(seconds or 0), 1.0), SATURATION_NOTE_MAX_S)
    try:
        cache.set(f'{SATURATION_CACHE_PREFIX}{source}:{scope}', reason or 'saturé', timeout=seconds)
        logger.warning('[quota] %s noté saturé (%s, portée %s) pour %.0f s',
                       source, reason or 'saturé', scope, seconds)
    except Exception:
        logger.debug('[quota] note de saturation non écrite (%s)', source, exc_info=True)


def saturated_sources(scopes: dict) -> dict:
    """{source: motif} des sources notées saturées — `scopes` : {source: portée de la clé}. Une
    panne notée pour toutes les clés vaut quelle que soit la portée."""
    from django.core.cache import cache
    names = {}
    for source, scope in scopes.items():
        names[f'{SATURATION_CACHE_PREFIX}{source}:{scope}'] = source
        names[f'{SATURATION_CACHE_PREFIX}{source}:{ALL_KEYS}'] = source
    if not names:
        return {}
    try:
        found = cache.get_many(list(names))
    except Exception:
        logger.debug('[quota] notes de saturation illisibles', exc_info=True)
        return {}
    return {names[name]: reason for name, reason in found.items()}


def saturation_reason(user, source: str) -> str:
    """Le motif de saturation de `source` pour `user` (« limite de débit », « indisponible »), ou ''."""
    return saturated_sources({source: saturation_scope(user, source)}).get(source, '')


# ── Compte ─────────────────────────────────────────────────────────────────────────────────

def _declared(source: str) -> tuple:
    try:
        from wama.common import external_sources
        return tuple(getattr(external_sources.get(source), 'quotas', ()) or ())
    except Exception:
        return ()


def _count_key(source, scope, bucket, unit, window_s, now) -> str:
    return f'{COUNT_PREFIX}{source}:{scope}:{bucket}:{unit}:{window_s}:{int(now // window_s)}'


def _counters(source: str, scope: str, model: str, unit: str) -> list:
    """(bucket, fenêtre) que compte un appel : le modèle sur les fenêtres toujours comptées, plus
    chaque groupe déclaré qui le vise."""
    pairs = [(f'm:{model or ""}', window) for window in COUNTED_WINDOWS]
    for quota in _declared(source):
        if quota.unit == unit and quota.applies_to(model):
            pair = (quota.bucket(model), quota.window_s)
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def record(source: str, scope: str, model: str = '', *, tokens: int = 0, now: float = None) -> None:
    """Compte UN appel servi par `source` (et ses `tokens`, s'ils sont connus)."""
    from django.core.cache import cache
    now = time.time() if now is None else now
    try:
        for unit, amount in ((REQUESTS, 1), (TOKENS, int(tokens or 0))):
            if amount <= 0:
                continue
            for bucket, window in _counters(source, scope, model, unit):
                key = _count_key(source, scope, bucket, unit, window, now)
                # Deux fenêtres de vie : la PRÉCÉDENTE sert encore à l'estimation glissante.
                cache.add(key, 0, timeout=2 * window + 5)
                cache.incr(key, amount)
    except Exception:
        logger.debug('[quota] compte non écrit (%s)', source, exc_info=True)


def used(source: str, scope: str, bucket: str, unit: str, window_s: int, now: float = None) -> int:
    """Ce qui a été servi sur les `window_s` DERNIÈRES secondes — estimation glissante : la
    fenêtre en cours, plus la part de la précédente qui y tombe encore. Un fournisseur compte
    souvent en glissant ; compter en fenêtres fixes ferait croire, juste après la frontière, que
    rien n'a été servi — et un refus tombé là ferait apprendre un plafond de 1."""
    from django.core.cache import cache
    now = time.time() if now is None else now
    current = _count_key(source, scope, bucket, unit, window_s, now)
    previous = _count_key(source, scope, bucket, unit, window_s, now - window_s)
    try:
        found = cache.get_many([current, previous])
    except Exception:
        return 0
    elapsed = (now % window_s) / window_s
    return int(round(int(found.get(current) or 0)
                     + int(found.get(previous) or 0) * (1.0 - elapsed)))


# ── Plafonds appris ────────────────────────────────────────────────────────────────────────

def _learned_key(source, scope, model, window_s) -> str:
    return f'{LEARNED_PREFIX}{source}:{scope}:m:{model or ""}:{window_s}'


def learn_from_refusal(source: str, scope: str, model: str = '', *, retry_after_s: float = 0.0,
                       now: float = None) -> int:
    """Un refus de débit RÉEL : ce qui a été servi sur la fenêtre devient le plafond de cette
    clé pour ce modèle. La fenêtre se lit à l'attente demandée — au-delà d'une minute, c'est la
    limite du jour qui a été heurtée. Le DERNIER refus fait foi (jamais le plus bas des refus :
    un plafond qui ne fait que descendre finirait à 1). Rend le plafond retenu (0 : rien servi,
    rien appris)."""
    from django.core.cache import cache
    now = time.time() if now is None else now
    window = DAY if float(retry_after_s or 0) > MINUTE else MINUTE
    ceiling = used(source, scope, f'm:{model or ""}', REQUESTS, window, now)
    if ceiling <= 0:
        return 0
    key = _learned_key(source, scope, model, window)
    try:
        cache.set(key, ceiling, timeout=LEARNED_TTL_S)
        logger.warning('[quota] %s (%s, portée %s) : plafond appris %d requêtes / %s',
                       source, model or '—', scope, ceiling, 'jour' if window == DAY else 'minute')
        return ceiling
    except Exception:
        logger.debug('[quota] plafond appris non écrit (%s)', source, exc_info=True)
        return 0


def _learned(source: str, scope: str, model: str) -> list:
    from django.core.cache import cache
    names = {_learned_key(source, scope, model, w): w for w in COUNTED_WINDOWS}
    try:
        found = cache.get_many(list(names))
    except Exception:
        return []
    return [Quota(int(v), names[k], REQUESTS, per_model=True) for k, v in found.items() if v]


# ── Ce que le tirage lit ───────────────────────────────────────────────────────────────────

def exhausted(source: str, scope: str, model: str = '', now: float = None) -> str:
    """'' si `source` peut encore servir `model` à cette clé ; sinon le motif — le plafond (déclaré
    ou appris) atteint dans sa fenêtre en cours."""
    now = time.time() if now is None else now
    limits = [q for q in _declared(source) if q.applies_to(model)] + _learned(source, scope, model)
    for quota in limits:
        if used(source, scope, quota.bucket(model), quota.unit, quota.window_s, now) >= quota.count:
            return QUOTA_REACHED
    return ''


def unavailable_keys(keys, scope_of) -> dict:
    """{model_key: motif} des clés de catalogue `<source>:<modèle>` que le tirage automatique doit
    écarter : source notée saturée (refus récent, panne) ou quota atteint. `scope_of(source)` :
    la portée de la clé employée pour cette source."""
    keys = list(keys or ())
    sources = {k.split(':', 1)[0] for k in keys}
    scopes = {s: scope_of(s) for s in sources}
    noted = saturated_sources(scopes)
    out = {}
    for key in keys:
        source, _, model = key.partition(':')
        reason = noted.get(source) or exhausted(source, scopes[source], model)
        if reason:
            out[key] = reason
    return out
