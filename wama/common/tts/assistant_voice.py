"""
La VOIX de l'assistant — quel modèle dit ses réponses, et avec quelle voix (2026-10-28).

Fabien, le jour même : « en plus du choix du modèle de réflexion, ne faut-il pas permettre de
choisir son modèle de vocalisation ? ». Jusque-là le moteur était une constante d'environnement
(`constants.ASSISTANT_TTS_ENGINE`, retirée — REMOVAL_LEDGER R184) et la voix un sélecteur Kokoro
que la seule page d'accueil proposait, sans le retenir.

Désormais deux réglages DURABLES du schéma de l'assistant (`assistant/params.py` : `voice_model`,
`voice_preset`), et un tirage « auto » qui passe par la brique COMMUNE (`resolve_model_choice`) :
parmi les modèles de synthèse installés, gardés chauds pour le temps réel (`realtime`) et qui
parlent la langue du profil, celui dont le premier son est le plus rapide (`first_audio_s`,
MESURÉ et déclaré par chaque moteur). Le voisin d'un moteur sans mesure passe après.
"""
from __future__ import annotations

import math

#: Le domaine du tirage : celui du menu de l'assistant (`voice_model.options_query`).
TTS_DOMAIN = {'task': 'text-to-speech'}


def _speaks(caps: dict, language: str) -> bool:
    languages = (caps or {}).get('languages') or []
    return not languages or '*' in languages or language in languages


def realtime_voices(language: str) -> list[str]:
    """Les clés des modèles de voix TEMPS RÉEL qui parlent `language`, le plus rapide en tête."""
    from wama.model_manager.models import AIModel
    from wama.model_manager.services.model_selector import domain_q
    rows = (AIModel.objects.filter(domain_q(TTS_DOMAIN), capabilities__realtime=True,
                                   is_downloaded=True)
            .values_list('model_key', 'capabilities'))
    ranked = sorted(((caps.get('first_audio_s') or math.inf, key) for key, caps in rows
                     if _speaks(caps, language)))
    return [key for _, key in ranked]


def voice_model_for(user, requested: str = '', language: str = 'fr') -> str | None:
    """Le modèle de voix de l'assistant : le choix du compte, sinon le tirage « auto » (le plus
    rapide en temps réel dans `language`). `None` : aucun modèle temps réel installé — l'appelant
    garde son repli."""
    from wama.common.utils.auto_model import is_auto, resolve_model_choice
    if requested and not is_auto(requested):
        return requested
    keys = realtime_voices(language)
    if not keys:
        return None
    return resolve_model_choice(requested, spec=TTS_DOMAIN, user=user, requires=['realtime'],
                                candidates=keys, priority=keys, prefer_loaded=False,
                                fallback=keys[0]) or keys[0]


def assistant_voice(user) -> dict:
    """`{model, voice_preset, language}` de la voix de `user` — ses réglages durables, la langue de
    son profil. Lu par la vue de vocalisation, pour toute surface qui fait parler l'assistant."""
    from wama.common.services.assistant_engine import assistant_settings
    settings_ = assistant_settings(user)
    language = getattr(getattr(user, 'profile', None), 'preferred_language', None) or 'fr'
    return {'model': voice_model_for(user, settings_.get('voice_model') or '', language),
            'voice_preset': settings_.get('voice_preset') or 'default',
            'language': language}
