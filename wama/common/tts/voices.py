"""
Résolution des voix Kokoro — brique COMMUNE (langue ↔ voix).

POURQUOI ICI. Le même calcul vivait en DEUX exemplaires, et en miroir l'un de l'autre :
  • `synthesizer/backends/kokoro_backend.py` : langue → code → voix (sens ALLER) ;
  • `wama/views.py::_tts_via_service` : voix → code → langue (sens RETOUR), reconstruit par une
    recherche inverse dans `KOKORO_LANG_MAP`.
Deux consommateurs, donc extraction légitime (règle du SECOND consommateur). Les tables restent
dans `constants.py` — ce module ne porte que la LECTURE dérivée, pas les données.

⚠ NE PAS CONFONDRE avec `common/utils/voice_options.py` : celui-là sert le SYNTHESIZER (voix de
référence, clonage `ua_`, presets Bark — un vocabulaire multi-moteurs). Ici c'est le
vocabulaire PROPRE à Kokoro (`ff_siwis`, `am_adam`…), qui est celui de l'assistant. Les deux
coexistent parce que ce sont deux registres de moteurs différents, pas une duplication.

PIÈGE DE LA TABLE, à connaître avant de lire un code de langue : `KOKORO_LANG_MAP` RABAT 8 langues
sans pipeline propre (de/nl/pl/tr/ru/cs/ar/ko) sur le pipeline anglais `'a'`. Une voix anglaise
lisant de l'allemand reste un pis-aller — d'où `est_repli()`, pour que l'UI puisse le DIRE au lieu
de laisser croire à un bug.
"""
from __future__ import annotations

from .constants import KOKORO_LANG_MAP, KOKORO_VOICE_MAP

#: Voix de dernier recours si la table ne rend rien (comportement historique du backend).
VOIX_DEFAUT = 'af_heart'

#: Libellés des langues RÉELLEMENT servies par un pipeline Kokoro propre.
_LANGUES_PROPRES = {
    'fr': 'Français', 'en': 'Anglais', 'es': 'Espagnol', 'it': 'Italien',
    'pt': 'Portugais', 'ja': 'Japonais', 'zh-cn': 'Chinois',
}


def code_langue(langue: str) -> str:
    """Code Kokoro (`'f'`, `'a'`…) d'une langue WAMA. Inconnue → `'a'` (comportement historique)."""
    return KOKORO_LANG_MAP.get(langue, 'a')


def est_repli(langue: str) -> bool:
    """Vrai si la langue n'a PAS de pipeline propre et retombe sur l'anglais.

    Sert la TRANSPARENCE : l'utilisateur doit savoir qu'il sera lu par une voix anglaise.
    """
    return langue not in _LANGUES_PROPRES and langue in KOKORO_LANG_MAP


def voix_pour(langue: str, masculin: bool = False) -> str:
    """Voix Kokoro d'une langue. Reproduit EXACTEMENT le calcul historique du backend :
    repli sur la voix féminine du même code, puis sur `VOIX_DEFAUT`."""
    code = code_langue(langue)
    return (KOKORO_VOICE_MAP.get((code, masculin))
            or KOKORO_VOICE_MAP.get((code, False), VOIX_DEFAUT))


def langue_de_voix(voix: str) -> tuple[str, bool]:
    """Sens RETOUR : nom de voix → (langue WAMA, masculin).

    Convention Kokoro : 1re lettre = code de langue, 2e = `f`/`m`. La langue rendue est la
    PREMIÈRE de la table pour ce code — pour `'a'` (partagé par l'anglais et les 8 replis),
    c'est donc `'en'`, ce qui est le comportement voulu : on ne devine pas un repli.
    """
    code = (voix[:1] or 'a')
    masculin = len(voix) > 1 and voix[1] == 'm'
    langue = next((k for k, v in KOKORO_LANG_MAP.items() if v == code), 'en')
    return langue, masculin


def kokoro_voices() -> tuple[dict, ...]:
    """Les voix PROPRES de Kokoro — une par langue servie et par genre (le FR n'a qu'une voix) —
    au format des voix de moteur (`TTSBackend.VOICES`, 2026-10-28) : `{value, label, language,
    gender}`. Les deux moteurs Kokoro les déclarent ; le catalogue les porte (`apply_engine_flags`),
    d'où la source commune des voix les propose sous eux seuls — l'assistant comme le synthesizer.
    Remplace `choix_voix`, la liste que l'accueil était seul à proposer (REMOVAL_LEDGER R184)."""
    seen: set[str] = set()
    voices: list[dict] = []
    for language, label in _LANGUES_PROPRES.items():
        for male in (False, True):
            voice = voix_pour(language, male)
            if voice in seen:
                continue          # ex. le FR n'a pas de voix masculine → une seule entrée
            seen.add(voice)
            voices.append({'value': voice, 'label': f"{label} {'masculin' if male else 'féminin'}",
                           'language': language, 'gender': 'male' if male else 'female'})
    return tuple(voices)


def kokoro_voice(language: str, voice_preset: str = 'default') -> str:
    """La voix Kokoro que désigne `voice_preset` : la sienne (un nom de la table, `ff_siwis`), sinon
    celle de la langue au genre du préréglage commun (`male_1`…). Une voix d'un autre moteur ne se
    dit pas ici : la voix de la langue."""
    preset = (voice_preset or 'default').strip()
    if preset in KOKORO_VOICE_MAP.values():
        return preset
    return voix_pour(language, preset in ('male_1', 'male_2'))
