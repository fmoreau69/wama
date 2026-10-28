"""
La FIN DE TOUR de la conversation vocale : la personne a-t-elle fini sa phrase, ou reprend-elle
son souffle ? (2026-10-28, Fabien : « on commence par les quick wins ».)

POURQUOI. L'écoute (`wama-assistant-listen.js`) ferme une phrase après 900 ms de silence. C'est
un compromis aveugle : trop court, une pause au milieu d'une idée coupe la phrase en deux
répliques ; trop long, chaque réponse attend 900 ms de plus. Smart Turn (pipecat-ai, BSD-2,
8 Mo, encodeur Whisper tiny) juge sur le SON — intonation, fin de mot — si le tour est fini.

CE QUE LE MODÈLE DÉCIDE, ET SEULEMENT CELA. Le silence garde ses bornes, le modèle ne fait que
bouger la décision entre elles, et seulement quand il est NET (`FINISH_ABOVE`, `WAIT_BELOW`) :
  • après une pause COURTE, l'écoute lui demande son avis ; « fini » → la phrase part tout de
    suite, au lieu d'attendre les 900 ms ;
  • « pas fini » → l'écoute attend plus longtemps la suite (une pause au milieu d'une idée
    n'est plus une fin de réplique) ;
  • avis incertain, pas de modèle, pas de service, réponse tardive → les 900 ms d'avant.
⚠ Les taux publiés par l'éditeur (94 % en français) sont mesurés sur SES corpus : la valeur
ici se juge à l'usage, au casque, pas sur ce chiffre (`feedback` du 2026-10-28).

LE MODÈLE est une ligne du catalogue comme une autre (`model_registry._discover_turn_end_models`),
installée et désinstallée par la route (pilote `files`, origine Hub à un commit FIGÉ). Absent, rien
ne casse : l'écoute ne le demande plus de la session. Il tourne dans le service vocal, sur le
processeur (aucune VRAM) : Django lui donne le chemin, le service ne cherche dans aucun dossier.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

HF_REPO = 'pipecat-ai/smart-turn-v3'
#: Commit du dépôt au 2026-10-28 (version 3.2, publiée le 2026-01-07).
HF_REVISION = 'f766f81d3cfdf7737ac64aad813d91bbfd56bf93'
#: Variante PROCESSEUR quantifiée en int8 : ~12 ms par avis selon l'éditeur, aucune VRAM.
WEIGHTS = 'smart-turn-v3.2-cpu.onnx'

#: Taille et empreinte LUES sur le Hub le 2026-10-28 (`X-Linked-Size`, `X-Linked-ETag` du
#: fichier LFS) ; le pilote `files` les vérifie à l'installation.
TURN_FILES = [
    {'path': WEIGHTS, 'size': 8679182,
     'sha256': '2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f',
     'origin': {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION, 'file': WEIGHTS}},
]
MODEL_KEY = f'huggingface:{HF_REPO}'

#: TROIS zones, pas le seuil unique de 0,5 de l'implémentation de référence. Sonde du
#: 2026-10-28 (voix locale Kokoro, 13 extraits — synthétiques, donc une alerte et pas une
#: mesure) : deux pauses d'HÉSITATION sur trois jugées « finies » à 0,82 et 0,94 — au seuil de
#: l'éditeur, elles auraient coupé une phrase que les 900 ms d'avant laissent entière ; les
#: phrases entières à 0,96–0,99 pour 7 sur 10, une seule sous 0,2 (0,07).
#: Au-dessus de `FINISH_ABOVE` : la phrase part. Sous `WAIT_BELOW` : la pause peut durer. Entre
#: les deux : aucun avis, le silence décide comme avant. À revoir sur la voix RÉELLE, au casque.
FINISH_ABOVE = 0.95
WAIT_BELOW = 0.2


def model_folder() -> Path:
    from django.conf import settings
    return Path(settings.MODEL_PATHS['speech']['smart_turn'])


def model_path() -> Path:
    """Chemin du modèle — existe ou non, c'est l'appelant qui mesure."""
    return model_folder() / WEIGHTS


def model_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(model_folder(), TURN_FILES)


def judge(audio: bytes) -> dict:
    """La phrase dite jusqu'ici (WAV 16 kHz) → `{available, complete, probability}`.

    `available: False` : pas de modèle installé — l'écoute cesse de demander pour la session.
    Le service qui ne répond pas rend `complete: None` (l'écoute garde le silence d'avant) :
    un avis manqué ne coûte rien, il ne doit donc rien casser."""
    if not model_installed():
        return {'available': False, 'complete': None, 'probability': None}
    from wama.common.tts.service_client import end_of_turn_via_service
    try:
        probability = end_of_turn_via_service(audio, model_path=model_path())
    except Exception as exc:
        logger.warning(f"[end_of_turn] avis indisponible, le silence décide : {exc}")
        return {'available': True, 'complete': None, 'probability': None}
    complete = (True if probability >= FINISH_ABOVE else False if probability <= WAIT_BELOW
                else None)
    # Une ligne par avis : la voix réelle dira si les seuils tiennent (une pause jugée « finie »
    # suivie d'une phrase coupée se lit au journal, à côté de la réplique transcrite).
    verdict = {True: 'finie', False: 'pas finie', None: 'le silence décide'}[complete]
    logger.info(f"[end_of_turn] p={probability:.3f} → {verdict}")
    return {'available': True, 'complete': complete, 'probability': round(probability, 3)}
