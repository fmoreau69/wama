"""Les BANQUES DE SONS de la lecture MIDI d'une partition (2026-11-08, décision de Fabien) — déclarées
une fois, lues par la page (le lecteur `wama-midi-player.js`, SpessaSynth) et par le rendu serveur
(FluidSynth, à venir). Veille et choix : `PROSPECTION_PIPELINE.md §Session du 2026-11-08`.

Deux banques, à COMPARER à l'écoute (« tester les 2 pour voir ce qui sonne le mieux ») : chacune a sa
copie VENDORISÉE (`tools/update_vendors.sh`, section `soundfonts`, gitignorée) et, quand son serveur
le permet (en-tête CORS), une adresse EN LIGNE que la page essaie d'abord — la copie locale en
secours si l'accès extérieur est coupé (« ceinture et bretelles »). Les adresses en ligne se lisent
au registre des sources (`external_sources`), jamais écrites ici en entier.

S'y ajoute le moteur d'abcjs (`ABCJS_ONLINE_BANK`) : sa banque MIDI.js FluidR3_GM, chargée en ligne
seulement — l'autre lecture à comparer, que SpessaSynth remplace quand l'accès est coupé.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SoundBank:
    key: str
    label: str
    #: La copie vendorisée, relative aux fichiers statiques (`vendors/soundfonts/…`).
    static_path: str
    #: La source du registre (`external_sources`) d'où elle vient.
    source: str
    #: Le chemin EN LIGNE sous l'adresse de sa source ('' = pas de chargement en ligne : le serveur
    #: ne sert pas l'en-tête CORS). Épinglé : le même que celui de `tools/update_vendors.sh`.
    online_path: str = ''


#: Le commit épinglé de GeneralUser GS — le même que `GENERALUSER_GS_COMMIT` de
#: `tools/update_vendors.sh` (tenu par `tests_sound_banks`).
GENERALUSER_GS_COMMIT = '97049183643d5fc5a9322a69c5b09efb667c6c3a'

SOUND_BANKS = (
    SoundBank('generaluser_gs', 'GeneralUser GS', 'vendors/soundfonts/GeneralUser-GS.sf2',
              source='generaluser_gs', online_path=f'{GENERALUSER_GS_COMMIT}/GeneralUser-GS.sf2'),
    SoundBank('musescore_general', 'MuseScore General', 'vendors/soundfonts/MuseScore_General.sf3',
              source='musescore_soundfonts'),
)

#: La banque MIDI.js du synthétiseur d'abcjs, en ligne seulement (`midi_js_soundfonts`).
ABCJS_ONLINE_BANK = ('midi_js_soundfonts', '/FluidR3_GM/')

#: Le moteur VENDORISÉ (`tools/update_vendors.sh`, section `spessasynth`) : son module ES (ses
#: imports réécrits vers ses voisins, donc chargeable par son adresse seule) et son processeur
#: AudioWorklet. Le dossier porte la version épinglée `SPESSASYNTH_LIB_VER`.
SPESSASYNTH_MODULE = 'vendors/spessasynth-4.4.7/lib/index.js'
SPESSASYNTH_PROCESSOR = 'vendors/spessasynth-4.4.7/lib/spessasynth_processor.min.js'
#: Son cœur (`BasicMIDI` : lire un MIDI et sa durée) — le fichier même que le module importe.
SPESSASYNTH_CORE = 'vendors/spessasynth-4.4.7/core/index.js'


def bank(key: str) -> SoundBank | None:
    return next((b for b in SOUND_BANKS if b.key == key), None)


def local_file(sound_bank: SoundBank) -> Path:
    """Le fichier vendorisé d'une banque (dans les sources statiques) — ce que lit un rendu serveur."""
    from django.conf import settings
    return Path(settings.BASE_DIR) / 'wama' / 'static' / sound_bank.static_path


def page_banks() -> dict:
    """Ce que la page reçoit (configuration d'une surface) : les banques, chacune avec son adresse
    LOCALE (servie par WAMA, présente ou non) et EN LIGNE ('' sans), et l'adresse en ligne de la
    banque d'abcjs. Une banque dont la copie n'est pas installée garde son adresse en ligne."""
    from django.templatetags.static import static
    from wama.common.external_sources import base_url
    out = []
    for sound_bank in SOUND_BANKS:
        online = (base_url(sound_bank.source).rstrip('/') + '/' + sound_bank.online_path
                  if sound_bank.online_path else '')
        out.append({'key': sound_bank.key, 'label': sound_bank.label,
                    'local': static(sound_bank.static_path) if local_file(sound_bank).is_file() else '',
                    'online': online})
    source, path = ABCJS_ONLINE_BANK
    return {'banks': out, 'abcjs_online': base_url(source).rstrip('/') + path,
            'engine': {'module': static(SPESSASYNTH_MODULE), 'core': static(SPESSASYNTH_CORE),
                       'processor': static(SPESSASYNTH_PROCESSOR)}}
