"""
Client COMMUN du microservice TTS (`tts_service.py`, FastAPI, uvicorn :8001).

Extrait le 2026-08-28 (chantier « pipeline avatarizer ») : QUATRE exemplaires du même
`POST /tts` vivaient dans le dépôt — `synthesizer/workers._tts_via_service` (seul à
détecter le 503 « loading »), `avatarizer/workers._call_tts_service`,
`wama/views._tts_via_service` (vocalisation assistant) et la preview SSE de
`synthesizer/views`. Chacun avait sa gestion d'erreur propre ; un seul savait attendre
un service pas encore chaud. Même patron que `common/utils/whisper_utils.py` : la
brique parle AU service, les POLITIQUES (retry Celery, chunking, replis en-process)
restent aux appelants.

Importable sans Django initialisé : l'URL du service est résolue à l'appel.
"""

import logging
import tempfile

logger = logging.getLogger(__name__)

#: Délai de lecture par défaut (s) — textes longs (75+ mots) même sous pression RAM ;
#: la formule max_tokens réduite côté service borne déjà les générations qui s'emballent.
DEFAULT_READ_TIMEOUT = 600


class TTSServiceLoadingError(Exception):
    """Le service TTS répond 503 « loading » (démarrage/chargement d'un moteur) —
    l'appelant décide de la politique d'attente (retry Celery, repli, abandon)."""


def service_url() -> str:
    """URL du service TTS : settings Django si disponibles, sinon env, sinon défaut."""
    try:
        from django.conf import settings
        return getattr(settings, 'TTS_SERVICE_URL', 'http://localhost:8001')
    except Exception:
        import os
        return os.environ.get('TTS_SERVICE_URL', 'http://localhost:8001')


def tts_via_service(text, model, *, language='fr', voice_preset='default',
                    speaker_wav=None, multi_speaker=False, scene_description='',
                    options=None, read_timeout=DEFAULT_READ_TIMEOUT, raw=False):
    """
    Synthétise `text` via le microservice TTS et renvoie le chemin d'un WAV TEMPORAIRE
    (à supprimer par l'appelant), ou les octets bruts si `raw=True` (vocalisation
    assistant, preview — aucun fichier intermédiaire).

    Le payload suit le contrat d'appel uniforme des moteurs (`TTSBackend.synthesize`) :
    toujours les mêmes clés, chaque moteur consomme ce qui le concerne.

    Lève `TTSServiceLoadingError` sur 503 « loading » (service pas encore chaud) et
    `RuntimeError` pour toute autre indisponibilité (connexion, délai, erreur moteur).
    """
    import requests

    url = service_url()
    payload = {
        'text': text,
        'model': model,
        'language': language,
        'voice_preset': voice_preset,
        'speaker_wav': speaker_wav,
        'multi_speaker': multi_speaker,
        'scene_description': scene_description,
        'options': options or {},
    }
    try:
        # ⚠ `proxies` OBLIGATOIRE : `.env` pose `HTTP_PROXY` (proxy UGE) sans `NO_PROXY`, et
        # `settings.load_dotenv()` l'injecte dans os.environ → sans neutralisation, `requests`
        # envoie CET APPEL LOCAL au proxy, qui répond une page d'erreur HTML. Vécu le
        # 2026-08-31 (cf. `http_proxy.local_proxies`) : le service tournait, la vocalisation
        # basculait quand même sur son repli en-process (~90 s + VRAM dans le worker web).
        from wama.common.utils.http_proxy import local_proxies
        resp = requests.post(f"{url}/tts", json=payload,
                             proxies=local_proxies(),
                             timeout=(5, read_timeout))  # (connexion, lecture)
        resp.raise_for_status()
    except requests.ConnectionError:
        raise RuntimeError(
            f"Service TTS inaccessible à {url}. "
            "Démarrage : python -m uvicorn tts_service:app --port 8001"
        )
    except requests.Timeout:
        raise RuntimeError(f"Service TTS : délai dépassé après {read_timeout}s")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 503:
            try:
                # FastAPI enveloppe : {"detail": {"status": "loading", ...}}
                body = e.response.json()
                detail_obj = body.get("detail", {}) if isinstance(body, dict) else {}
                if isinstance(detail_obj, dict) and detail_obj.get("status") == "loading":
                    raise TTSServiceLoadingError(
                        detail_obj.get("message", "TTS service is still loading"))
            except TTSServiceLoadingError:
                raise
            except Exception:
                pass
        detail = ""
        try:
            detail = str(e.response.json().get("detail") or "")
        except Exception:
            detail = e.response.text[:200] if e.response is not None else ""
        raise RuntimeError(f"Erreur service TTS : {detail or str(e)}")

    if raw:
        return resp.content
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name
