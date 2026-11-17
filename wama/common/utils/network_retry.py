"""Reprendre un appel à une source externe après une panne PASSAGÈRE — une règle, tous les appelants.

POURQUOI (2026-11-17, demande de Fabien : « une nouvelle tentative automatique à l'installation […]
avec une courte pause pour ne pas surcharger les requêtes vers les sources »). L'installation de
`FluidVoice-Labs/fluid-speech-pro` a échoué en 0,9 s : le Hub n'a pas répondu à cet instant, la
librairie a cherché une copie locale (`LocalEntryNotFoundError`), et l'utilisateur a reçu un échec ;
la même demande, refaite à la main trois minutes plus tard, a téléchargé les 17 fichiers. Trois
boucles de reprise existaient déjà, chacune à sa façon — une seule tentative sur un 429 du Hub
(`prospector._hub_call`), cinq attentes croissantes sur un 429 (`asr_eval_corpus.with_retry`) —, et
aucune pour les pilotes d'installation.

CE QUI SE REPREND — une panne de la SOURCE ou du chemin, jamais une faute de la demande :
  • une connexion impossible, coupée ou trop lente (`requests`, `urllib3`, `httpx`, les erreurs
    d'E/S de socket) ;
  • `LocalEntryNotFoundError` du Hub : la librairie la lève quand le Hub n'a pas répondu ET qu'aucune
    copie locale n'existe — c'est une panne réseau sous un autre nom ;
  • une réponse 408, 425, 429, 500, 502, 503, 504.
Un 401/403 (accès refusé), un 404 (dépôt absent), une empreinte fausse ne se reprennent pas : la
même demande rendrait la même réponse.

LA PAUSE — courte, croissante, et celle que la source DEMANDE quand elle en dit une : `RETRY_WAITS_S`
(10 s puis 30 s : trois tentatives en tout, ~40 s d'attente au pire) ; un 429 qui porte
`Retry-After` attend ce délai, plafonné à `MAX_WAIT_S`. Une pause de plus ne rend pas service à une
source en panne longue : au-delà, l'échec se DIT, avec sa raison.
"""
import logging
import time

logger = logging.getLogger(__name__)

#: Attentes entre deux tentatives, dans l'ordre (s) — leur nombre est celui des REPRISES.
RETRY_WAITS_S = (10, 30)
#: Plafond de l'attente que la source demande (`Retry-After`).
MAX_WAIT_S = 60
#: Statuts HTTP d'une source passagèrement indisponible ou saturée.
TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
#: Classes d'erreur d'une connexion (par NOM : `requests`, `urllib3`, `httpx` et `huggingface_hub`
#: ne s'importent pas tous partout, et la lecture ne doit rien importer).
TRANSIENT_ERRORS = frozenset({
    'ConnectionError', 'ConnectTimeout', 'ReadTimeout', 'Timeout', 'TimeoutError',
    'ChunkedEncodingError', 'ProtocolError', 'RemoteDisconnected', 'IncompleteRead',
    'NewConnectionError', 'MaxRetryError', 'ProxyError', 'SSLError',
    'ConnectError', 'ReadError', 'WriteError', 'RemoteProtocolError', 'PoolTimeout',
    'ConnectionResetError', 'ConnectionAbortedError', 'ConnectionRefusedError', 'BrokenPipeError',
    'LocalEntryNotFoundError',
})


def _chain(exc):
    """L'erreur et celles qu'elle enveloppe (`__cause__`, `__context__`), sans boucle."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def status_of(exc):
    """Le statut HTTP que porte l'erreur (ou celle qu'elle enveloppe), sinon None."""
    for link in _chain(exc):
        status = getattr(getattr(link, 'response', None), 'status_code', None)
        if status is None:
            status = getattr(link, 'status_code', None)
        if isinstance(status, int):
            return status
    return None


def transient_reason(exc) -> str:
    """Pourquoi l'échec est PASSAGER (« HTTP 503 », « ConnectTimeout »), ou '' s'il ne l'est pas.
    Un statut HTTP tranche d'abord : une 404 enveloppée dans une erreur de connexion reste une 404."""
    status = status_of(exc)
    if status is not None:
        return f'HTTP {status}' if status in TRANSIENT_STATUSES else ''
    for link in _chain(exc):
        for klass in type(link).__mro__:
            if klass.__name__ in TRANSIENT_ERRORS:
                return type(link).__name__
    return ''


def asked_wait_s(exc):
    """L'attente que la source DEMANDE (`Retry-After`, en secondes), plafonnée — None si elle ne dit rien."""
    for link in _chain(exc):
        headers = getattr(getattr(link, 'response', None), 'headers', None) or {}
        try:
            value = headers.get('Retry-After') or headers.get('retry-after')
            if value is not None:
                return min(max(float(value), 1.0), MAX_WAIT_S)
        except (TypeError, ValueError, AttributeError):
            continue
    return None


def with_retries(call, label: str, *, waits=RETRY_WAITS_S, on_retry=None, retry_if=None,
                 max_wait_s: float = MAX_WAIT_S):
    """`call()`, repris après chaque attente de `waits` tant que l'échec est PASSAGER ; la dernière
    erreur remonte telle quelle (l'appelant garde sa politique d'échec et ses messages).

    `on_retry(attempt, total, wait_s, reason)` : ce que l'appelant DIT pendant l'attente (la mesure
    d'une installation, la sortie d'une commande). `retry_if(exc) -> str` : une règle plus étroite que
    `transient_reason` (le seul 429, par exemple) ; elle rend la raison, ou '' pour ne pas reprendre.
    `max_wait_s` : le plafond de l'attente que la source demande (`Retry-After`).
    `call` doit rendre une valeur MATÉRIALISÉE : un générateur dont la requête part à l'itération
    échappe à la reprise."""
    judge = retry_if or transient_reason
    total = len(waits) + 1
    for attempt in range(1, total + 1):
        try:
            return call()
        except Exception as exc:
            reason = judge(exc) if attempt < total else ''
            if not reason:
                raise
            asked = asked_wait_s(exc)
            wait = min(asked, max_wait_s) if asked else waits[attempt - 1]
            logger.info('[network_retry] %s : échec passager (%s) — tentative %d/%d dans %g s',
                        label, reason, attempt + 1, total, wait)
            if on_retry is not None:
                on_retry(attempt + 1, total, wait, reason)
            time.sleep(wait)
