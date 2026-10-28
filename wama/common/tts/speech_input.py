"""
Ce que l'utilisateur DIT à l'assistant → texte : le moteur qui l'écoute, et ce qu'on en retire.

POURQUOI CE MODULE (2026-10-11, demande de Fabien) : la conversation vocale de la veille passait
par le Whisper LOCAL du service vocal seul. Mesuré au premier essai réel : la carte était prise
par d'autres traitements, la première phrase a attendu 90 s la place que réserve le gouverneur
(10 Go pour Whisper), les suivantes 4 à 5 s au lieu de 1,2. Albert sert le MÊME modèle
(`whisper-large-v3`) sans rien prendre au GPU.

LE CHOIX DU MOTEUR n'est pas un réglage de plus : c'est le profil qui le porte, par la règle
commune du tirage AUTOMATIQUE (`cloud_models.allowed_cloud_keys(automatic=True)`) — « 100 %
local » et « cloud si WAMA est saturé » restent en local, « cloud autorisé » passe par le modèle
de transcription distant que SA clé ouvre. L'appel passe par la porte commune
(`backend_instance_for_key` : garde `cloud_access`, clé posée). Le distant refuse, plafonne son
débit ou ne répond pas → le local prend la phrase : un micro qui marchait ne cesse pas de marcher.

LES PHRASES FANTÔMES : sur un extrait sans parole nette, Whisper rend des génériques de
sous-titres appris à l'entraînement — vécu le 2026-10-11, trois « Sous-titrage ST' 501 » et un
« Merci. » envoyés à l'assistant comme des répliques. Le filtre de parole les réduit sans les
supprimer ; on retire donc les génériques CONNUS, et eux seuls : un « Merci. » réellement dit
reste une réplique.
"""

import logging
import os
import re
import tempfile
import time

logger = logging.getLogger(__name__)

#: Génériques de sous-titres que Whisper invente sur du silence ou du bruit (relevés FR et EN).
#: Motifs ENTIERS et spécifiques : « sous-titre cette vidéo », dit à l'assistant, doit passer.
_PHANTOM = re.compile(
    r"(?:sous-titrage\s+st['’]?\s*\d+"
    r"|sous-titr\w*\s+(?:réalisés?\s+)?(?:par|para)\s+la\s+communauté\s+d['’]\s*amara\.org"
    r"|sous-titrage\s+(?:de\s+la\s+)?société\s+radio-canada"
    r"|merci\s+d['’]avoir\s+regardé(?:\s+cette\s+vidéo)?"
    r"|thanks?\s+(?:you\s+)?for\s+watching"
    r"|subtitles\s+by\s+the\s+amara\.org\s+community)"
    r"[\s.!?…]*",
    re.IGNORECASE)


def drop_phantom_phrases(text: str) -> str:
    """`text` sans les génériques de sous-titres inventés ; vide s'il ne restait qu'eux."""
    cleaned = _PHANTOM.sub(' ', text or '')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned if re.search(r'\w', cleaned) else ''


def remote_stt_key(user) -> str:
    """Clé du modèle de transcription DISTANT que le profil de `user` ouvre au tirage
    automatique ; vide = le local écoute."""
    try:
        from wama.model_manager.models import AIModel, EXECUTION_CLOUD
        from wama.model_manager.services.cloud_models import allowed_cloud_keys
        allowed = allowed_cloud_keys(user, automatic=True)
        if not allowed:
            return ''
        return (AIModel.objects
                .filter(model_key__in=allowed, execution=EXECUTION_CLOUD, is_available=True,
                        capabilities__task='transcription')
                .order_by('model_key').values_list('model_key', flat=True).first()) or ''
    except Exception:
        logger.warning('[speech_input] catalogue illisible — écoute locale', exc_info=True)
        return ''


def _speech_only(audio: bytes, content_type: str):
    """Les passages parlés de l'extrait, par le service vocal (b'' : aucune parole) ; l'extrait
    tel quel si le service ne répond pas — le distant écoute alors sans filtre, et les
    génériques inventés restent retirés par `drop_phantom_phrases`.

    ⚠ Pas le `vad_filter` du backend : il importerait `faster_whisper` DANS gunicorn, 52 à 66 s
    (mesuré le 2026-10-11 : `ctranslate2` importe `transformers`), une fois par worker."""
    from wama.common.tts.service_client import speech_only_via_service
    try:
        return speech_only_via_service(audio, content_type=content_type), 'audio/wav'
    except Exception as exc:
        logger.warning(f"[speech_input] filtre de parole indisponible, extrait envoyé tel quel : {exc}")
        return audio, content_type


def _transcribe_remote(user, key: str, audio: bytes, content_type: str) -> dict:
    """Une phrase chez le fournisseur ; LÈVE `RuntimeError` (ou le refus de la garde) sinon."""
    from wama.common.backends.manager import backend_instance_for_key
    from wama.common.utils.model_keys import split_key
    backend = backend_instance_for_key(key, user)
    if not backend.load(split_key(key)[1]):
        raise RuntimeError(f"{key} : modèle distant non chargé")
    audio, content_type = _speech_only(audio, content_type)
    if not audio:
        return {'text': '', 'language': ''}
    suffix = '.webm' if 'webm' in content_type else '.ogg' if 'ogg' in content_type else '.wav'
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio)
        tmp.close()
        # Pas de `language` : chez Albert il TRADUIT la sortie, il n'impose pas la langue
        # entendue (`albert_asr_backend`). Pas d'attente sur la limite de débit (10/min) : le
        # local est là.
        result = backend.transcribe(tmp.name, vad_filter=False, wait_on_rate_limit=False)
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass
    if not result.success:
        raise RuntimeError(result.error or 'transcription distante échouée')
    return {'text': result.text, 'language': result.language}


def transcribe_utterance(user, audio: bytes, *, content_type: str = 'audio/wav',
                         language: str = '', warm_up: bool = False) -> dict:
    """Une réplique dite → `{text, language, engine}` (`engine` : la clé distante, ou 'local').

    `warm_up` : la brique d'écoute s'ouvre et veut que la PREMIÈRE phrase ne paie pas le
    chargement — utile au local seul ; un distant n'a rien à charger, on ne lui envoie rien.
    Les erreurs du LOCAL remontent telles quelles (`TTSServiceLoadingError`, `RuntimeError`).
    """
    content_type = (content_type or 'audio/wav').lower()
    started = time.monotonic()
    key = remote_stt_key(user)
    if key:
        if warm_up:
            return {'text': '', 'language': language, 'engine': key}
        try:
            result = _transcribe_remote(user, key, audio, content_type)
            _log_timing(key, started, audio)
            return {'text': drop_phantom_phrases(result.get('text')),
                    'language': result.get('language') or language, 'engine': key}
        except Exception as exc:
            logger.warning(f"[speech_input] {key} indisponible après "
                           f"{time.monotonic() - started:.2f} s, le local écoute : {exc}")
    from wama.common.tts.service_client import stt_via_service
    local_started = time.monotonic()
    result = stt_via_service(audio, content_type=content_type, language=language)
    if not warm_up:
        _log_timing('local', started, audio, local_started)
    return {'text': drop_phantom_phrases(result.get('text')),
            'language': result.get('language') or language, 'engine': 'local'}


def _log_timing(engine: str, started: float, audio: bytes, local_started: float = None):
    """Une ligne par réplique : quel moteur, combien de temps (2026-10-28, Fabien : « je
    suspecte plutôt des process qui pourraient interférer avec l'assistant »). Une phrase lente
    se lit alors au journal, avec la part du repli local quand le distant a d'abord échoué."""
    total = time.monotonic() - started
    # Durée dite : le WAV de l'écoute (16 kHz, 16 bits, mono) ; un autre format, sa taille.
    spoken = (f"{max(0, len(audio) - 44) / 32000:.1f} s" if audio[:4] == b'RIFF'
              else f"{len(audio)} octets")
    detail = ''
    if local_started is not None and local_started - started > 0.05:
        detail = f" (dont {local_started - started:.2f} s avant le repli local)"
    logger.info(f"[speech_input] réplique de {spoken} transcrite par {engine} "
                f"en {total:.2f} s{detail}")
