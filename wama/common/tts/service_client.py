"""
Client COMMUN du microservice TTS (`common/tts/service.py`, FastAPI, uvicorn :8001).

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
    """URL du service TTS : settings Django si disponibles, sinon env, sinon défaut.

    Cette cascade EST celle du registre commun des sources externes (2026-09-01) : elle y est
    écrite une fois, avec le défaut déclaré au même endroit que la portée `LOCAL` — celle qui
    dit que le proxy doit être neutralisé pour ce service. C'est cette portée, restée implicite
    jusqu'au 2026-08-31, qui avait coûté un repli en-process de 90 s le jour où `.env` a gagné
    `HTTP_PROXY` : le proxy répondait sa page d'erreur HTML à la place de l'audio.
    """
    from wama.common.external_sources import base_url
    return base_url('tts_service')


def tts_eta_key_size(text, model):
    """(clé, taille, unité) de l'ETA d'une synthèse par le service : durée ∝ longueur du texte,
    apprise par MODÈLE TTS — la même clé quelle que soit l'app qui fait parler le service
    (synthesizer, voix de l'avatarizer) : un moteur parle au même débit pour toutes. None sans
    texte. Rendu par la glu (`record_run`) et déclaré à son process (`ProcessSpec.eta`)."""
    from wama.model_manager.services.eta_estimator import make_key
    from .constants import DEFAULT_TTS_MODEL
    text = text or ''
    return (make_key(DEFAULT_TTS_MODEL.split(':', 1)[0], model), len(text), 'char') if text else None


def tts_via_service(text, model, *, language='fr', voice_preset='default',
                    speaker_wav=None, multi_speaker=False, scene_description='',
                    options=None, read_timeout=DEFAULT_READ_TIMEOUT, raw=False, user=None):
    """
    Synthétise `text` via le microservice TTS et renvoie le chemin d'un WAV TEMPORAIRE
    (à supprimer par l'appelant), ou les octets bruts si `raw=True` (vocalisation
    assistant, preview — aucun fichier intermédiaire).

    Le payload suit le contrat d'appel uniforme des moteurs (`TTSBackend.synthesize`) :
    toujours les mêmes clés, chaque moteur consomme ce qui le concerne.

    `user` (2026-10-27) : le compte pour qui la voix parle. Son LEXIQUE de prononciation — les
    lignes système promues et les siennes, `user_pronunciations.lexicon_for` — part dans
    `options['lexicon']` : le service n'a pas Django, il ne lit que le fichier du dépôt. Sans
    compte, les lignes système seules.

    Lève `TTSServiceLoadingError` sur 503 « loading » (service pas encore chaud) et
    `RuntimeError` pour toute autre indisponibilité (connexion, délai, erreur moteur).
    """
    payload = _tts_payload(text, model, language=language, voice_preset=voice_preset,
                           speaker_wav=speaker_wav, multi_speaker=multi_speaker,
                           scene_description=scene_description, options=options, user=user)
    resp = _post('/tts', read_timeout, json=payload)
    if raw:
        return resp.content
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


def tts_stream_via_service(text, model, *, language='fr', voice_preset='default',
                           speaker_wav=None, options=None, read_timeout=30, user=None):
    """La même demande AU FIL DE L'EAU (2026-10-28, voix de l'assistant) : rend `(rate, morceaux)`,
    des octets PCM 16 bits mono little-endian à `rate` Hz, lus à mesure que le service les calcule
    (`/tts/stream`). Le premier son est déjà calculé au retour ; fermer l'itérateur abandonne la
    réponse et arrête le calcul. Mêmes erreurs que `tts_via_service`."""
    payload = _tts_payload(text, model, language=language, voice_preset=voice_preset,
                           speaker_wav=speaker_wav, options=options, user=user)
    resp = _post('/tts/stream', read_timeout, json=payload, stream=True)
    rate = int(resp.headers.get('X-Sample-Rate') or 24000)

    def chunks():
        try:
            for block in resp.iter_content(chunk_size=None):
                if block:
                    yield block
        finally:
            resp.close()
    return rate, chunks()


def _tts_payload(text, model, *, language, voice_preset, speaker_wav, options, user,
                 multi_speaker=False, scene_description=''):
    """Le corps d'une demande de voix — le contrat d'appel uniforme des moteurs."""
    # Moteur DÉCLARÉ du modèle, résolu au catalogue et PASSÉ au service (route F4b ②,
    # 2026-09-01) : le service n'a pas Django et ne peut pas aller le chercher. Sans lui, un
    # modèle installé par la prospection est proposable mais pas exécutable — son nom ne dit
    # pas son moteur. `None` pour les moteurs historiques : le routage par le nom suffit.
    from wama.common.services.user_pronunciations import lexicon_for
    from wama.common.tts.ui_meta import tts_engine_declared

    options = dict(options or {})
    # Les entrées que l'appelant joint lui-même passent devant (l'écoute d'une prononciation
    # avant de l'adopter, `kokoro_tts`).
    lexicon = {**lexicon_for(user, language), **(options.get('lexicon') or {})}
    if lexicon:
        options['lexicon'] = lexicon
    return {
        'text': text,
        'model': model,
        'engine': tts_engine_declared(model),
        'language': language,
        'voice_preset': voice_preset,
        'speaker_wav': speaker_wav,
        'multi_speaker': multi_speaker,
        'scene_description': scene_description,
        'options': options or {},
    }


def stt_via_service(audio, *, content_type='audio/wav', language='', model=None,
                    read_timeout=90):
    """
    Transcrit un extrait COURT (octets audio) par le même service — la conversation vocale de
    l'assistant (2026-10-10). Rend `{'text', 'language'}`.

    `read_timeout` 90 s : la PREMIÈRE phrase attend le chargement de Whisper (37 à 50 s mesurés
    le 2026-10-10, poids sur /mnt/d) ; à chaud, 1,2 s pour une phrase de 5 s. Sous les 120 s de
    gunicorn et d'Apache, qui couperaient sinon la requête sans réponse lisible.

    Mêmes erreurs que `tts_via_service` : `TTSServiceLoadingError` sur 503 « loading »,
    `RuntimeError` pour toute autre indisponibilité. `model` absent = celui de l'assistant
    (`constants.ASSISTANT_STT_MODEL`).
    """
    from .constants import ASSISTANT_STT_MODEL
    params = {'language': language or '', 'model': model or ASSISTANT_STT_MODEL}
    resp = _post('/stt', read_timeout, data=audio, params=params,
                 headers={'Content-Type': content_type or 'audio/wav'})
    return resp.json()


def speech_only_via_service(audio, *, content_type='audio/wav', read_timeout=90):
    """Les seuls passages PARLÉS d'un extrait (WAV 16 kHz mono), b'' s'il n'y en a aucun — le
    filtre de parole de l'écoute DISTANTE (2026-10-11), exécuté par le service, où son import
    (52 à 66 s) n'est payé qu'une fois. Mêmes erreurs que `stt_via_service`."""
    resp = _post('/speech-only', read_timeout, data=audio,
                 headers={'Content-Type': content_type or 'audio/wav'})
    return b'' if resp.status_code == 204 else resp.content


def end_of_turn_via_service(audio, *, model_path, read_timeout=1.5):
    """Probabilité que la personne ait FINI sa phrase (0 à 1), d'après les 8 dernières
    secondes de l'extrait — Smart Turn, exécuté par le service (2026-10-28,
    `common/tts/end_of_turn.py`). Le chemin du modèle vient de Django : le service ne cherche
    dans aucun dossier. Délai COURT : l'avis est demandé à 300 ms de pause et ne sert plus à
    rien après 900 ms ; mesuré 21 à 33 ms à chaud, ~35 s au premier appel d'un processus froid
    (le service continue de charger, la place gunicorn, elle, est rendue). Mêmes erreurs que
    `stt_via_service`."""
    resp = _post('/end-of-turn', read_timeout, data=audio, params={'model_path': str(model_path)},
                 headers={'Content-Type': 'audio/wav'})
    return float(resp.json()['probability'])


def _post(path, read_timeout, **kwargs):
    """UN appel au service et sa traduction d'erreurs — partagée par la voix et l'écoute."""
    import requests

    url = service_url()
    try:
        # ⚠ `proxies` OBLIGATOIRE : `.env` pose `HTTP_PROXY` (proxy UGE) sans `NO_PROXY`, et
        # `settings.load_dotenv()` l'injecte dans os.environ → sans neutralisation, `requests`
        # envoie CET APPEL LOCAL au proxy, qui répond une page d'erreur HTML. Vécu le
        # 2026-08-31 (cf. `http_proxy.local_proxies`) : le service tournait, la vocalisation
        # basculait quand même sur son repli en-process (~90 s + VRAM dans le worker web).
        # DÉRIVÉ de la portée déclarée (`tts_service` est `LOCAL`), plus choisi à la main : la
        # prochaine source locale héritera de la neutralisation sans que personne ait à se
        # souvenir de cet incident.
        from wama.common.external_sources import proxies_for
        resp = requests.post(f"{url}{path}", proxies=proxies_for('tts_service'),
                             timeout=(5, read_timeout), **kwargs)  # (connexion, lecture)
        resp.raise_for_status()
    except requests.ConnectionError:
        raise RuntimeError(
            f"Service TTS inaccessible à {url}. "
            "Démarrage : python -m uvicorn wama.common.tts.service:app --port 8001"
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
    return resp
