"""
Client COMMUN du service de confidentialité (`common/privacy/service.py`, uvicorn 127.0.0.1:8003).
Même patron que les clients TTS et de vectorisation : tout le monde passe par ici — l'Anonymizer
(domaine document), la porte de l'assistant avant un modèle distant, la mémoire.

    detect_segments([texte, …], language='') → document `detections` (forme texte)
    detect(text, language='')                 → le même, un segment
    occult(text, doc, language='', segment=0) → le texte, passages remplacés par `[LIBELLÉ]`

Service éteint (pas encore relancé, arrêté) ⇒ le MÊME moteur s'exécute dans ce process : rien ne
casse, on perd seulement le déport. ⚠ Une différence VOULUE avec la vectorisation, qui se dégrade
en `[]` : ici un délai dépassé ou un refus LÈVE `PrivacyUnavailable`. Un filtre de confidentialité
qui répondrait « aucune donnée personnelle » faute d'avoir pu regarder laisserait tout passer.

L'occultation n'a aucun modèle : elle se fait toujours dans ce process (`engine.occult`).
"""
from __future__ import annotations

import logging

from . import engine

logger = logging.getLogger(__name__)

#: Le premier appel du service paie le chargement des détecteurs (~30 s mesurés le 2026-10-28).
TIMEOUT_S = 180


class PrivacyUnavailable(RuntimeError):
    """La détection n'a pas pu se faire — l'appelant doit REFUSER, jamais continuer sans elle."""


def service_url() -> str:
    from wama.common.external_sources import base_url
    return base_url('privacy_service')


def detect_segments(segments, language: str = '', *, entities=None, detectors=None,
                    threshold=None, timeout: float = TIMEOUT_S) -> dict:
    """Le document de détections des segments, par le service ou par le moteur en process."""
    import requests

    from wama.common.external_sources import proxies_for
    payload = {'segments': list(segments), 'language': language or '', 'entities': entities,
               'detectors': list(detectors) if detectors is not None else None,
               'threshold': threshold}
    try:
        resp = requests.post(f'{service_url()}/detect', json=payload,
                             proxies=proxies_for('privacy_service'), timeout=(2, timeout))
    except requests.ConnectionError:
        logger.info('[privacy] service injoignable à %s — moteur exécuté dans ce process',
                    service_url())
        return engine.detect_segments(list(segments), language, entities=entities,
                                      detectors=detectors, threshold=threshold)
    except requests.Timeout as exc:
        raise PrivacyUnavailable(f'service de confidentialité : délai dépassé ({timeout} s)') from exc
    if resp.status_code != 200:
        raise PrivacyUnavailable(f'service de confidentialité : HTTP {resp.status_code} '
                                 f'({resp.text[:200]})')
    return resp.json()


def detect(text: str, language: str = '', **kwargs) -> dict:
    return detect_segments([text], language, **kwargs)


def occult(text: str, doc: dict, language: str = '', segment: int = 0) -> str:
    return engine.occult(text, doc, language, segment)
