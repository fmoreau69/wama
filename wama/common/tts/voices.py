"""
Résolution des voix Kokoro — brique COMMUNE (langue ↔ voix).

POURQUOI ICI. Le même calcul vivait en DEUX exemplaires, et en miroir l'un de l'autre :
  • `synthesizer/backends/kokoro_backend.py` : langue → code → voix (sens ALLER) ;
  • `wama/views.py::_tts_via_service` : voix → code → langue (sens RETOUR), reconstruit par une
    recherche inverse dans `KOKORO_LANG_MAP`.
Deux consommateurs, donc extraction légitime (règle du SECOND consommateur). Les tables restent
dans `constants.py` — ce module ne porte que la LECTURE dérivée, pas les données.

⚠ NE PAS CONFONDRE avec `common/utils/voice_options.py` : celui-là sert le SYNTHESIZER (voix de
référence, clonage `ua_`/`cv_`, presets Bark — un vocabulaire multi-moteurs). Ici c'est le
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


def choix_voix(langue_preferee: str = 'fr') -> list[dict]:
    """Voix proposables, la langue préférée EN TÊTE.

    Rend des dicts (et non des tuples) parce que l'UI a besoin de plus que valeur/libellé :
    `preferee` pour présélectionner, `repli` pour avertir. Le sélecteur de l'assistant était
    jusqu'ici une liste de 3 options ÉCRITE EN DUR, ignorant `preferred_language` et 13 des
    16 voix de la table.
    """
    vues: set[str] = set()
    choix: list[dict] = []
    langues = sorted(_LANGUES_PROPRES, key=lambda l: (l != langue_preferee, l))
    for langue in langues:
        for masculin in (False, True):
            voix = voix_pour(langue, masculin)
            if voix in vues:
                continue          # ex. le FR n'a pas de voix masculine → une seule entrée
            vues.add(voix)
            genre = 'Masculin' if masculin else 'Féminin'
            choix.append({
                'valeur': voix,
                'libelle': f"{_LANGUES_PROPRES[langue]} {genre}",
                'langue': langue,
                'preferee': langue == langue_preferee,
                'repli': False,
            })
    return choix
