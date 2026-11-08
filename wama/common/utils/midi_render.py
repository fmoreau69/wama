"""Le RENDU AUDIO d'un MIDI côté serveur, par FluidSynth (2026-11-08, décision de Fabien :
« FluidSynth oui ») — l'export WAV d'une partition, avec les MÊMES banques que la lecture dans la page
(`sound_banks`), donc le même son. Veille : `PROSPECTION_PIPELINE.md §Session du 2026-11-08`.

FluidSynth est un programme SYSTÈME (LGPL-2.1), pas un paquet PyPI : `tools/install_wama.sh` le
vérifie et dit la commande (`INSTALL_COMMAND`) ; absent, le rendu le DIT
(`FluidSynthMissing`), il ne retombe sur rien en silence.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

#: Fréquence d'échantillonnage du rendu, celle de la lecture dans la page.
SAMPLE_RATE = 44100
#: Le gain de FluidSynth : 0,2 par défaut, un rendu de banque GM y sonne bas ; 0,8 sans saturer.
GAIN = 0.8
#: Plafond d'un rendu (s) : un MIDI d'une heure n'est pas une partition à écouter.
TIMEOUT_S = 600
#: La commande à donner quand FluidSynth manque — la forme de `tools/install_wama.sh`. Mesuré à
#: l'installation du 2026-11-08 : un `apt install fluidsynth` nu a échoué (index périmé, 404 sur des
#: paquets que seuls les RECOMMANDÉS tirent — Qt, 41 paquets) ; mis à jour et sans les recommandés,
#: il en pose 7.
INSTALL_COMMAND = 'sudo apt-get update && sudo apt-get install -y --no-install-recommends fluidsynth'


class FluidSynthMissing(RuntimeError):
    """FluidSynth n'est pas installé sur l'hôte."""


def fluidsynth_path() -> str:
    return shutil.which('fluidsynth') or ''


def render_wav(midi: bytes, bank_key: str) -> bytes:
    """Les octets WAV du MIDI `midi`, joué avec la banque `bank_key` (`sound_banks.SOUND_BANKS`).
    Lève `FluidSynthMissing`, `ValueError` (banque inconnue ou non installée, MIDI vide) ou
    `RuntimeError` (le rendu a échoué, avec la fin de ce que FluidSynth a dit)."""
    from wama.common.utils.sound_banks import bank, local_file
    program = fluidsynth_path()
    if not program:
        raise FluidSynthMissing("FluidSynth n'est pas installé sur le serveur "
                                "(sous WSL2 : " + INSTALL_COMMAND + ").")
    chosen = bank(bank_key)
    if chosen is None:
        raise ValueError(f'banque de sons inconnue : {bank_key}')
    sound = local_file(chosen)
    if not sound.is_file():
        raise ValueError(f"banque « {chosen.label} » non installée "
                         "(bash tools/update_vendors.sh soundfonts)")
    if not midi:
        raise ValueError('MIDI vide')
    with tempfile.TemporaryDirectory(prefix='wama_midi_') as work:
        source, out = Path(work, 'score.mid'), Path(work, 'score.wav')
        source.write_bytes(midi)
        done = subprocess.run(
            [program, '-ni', '-g', str(GAIN), '-r', str(SAMPLE_RATE), '-F', str(out), str(sound),
             str(source)],
            capture_output=True, text=True, timeout=TIMEOUT_S)
        if done.returncode != 0 or not out.is_file() or out.stat().st_size <= 44:
            raise RuntimeError(f'rendu FluidSynth en échec : {(done.stderr or done.stdout)[-300:]}')
        return out.read_bytes()
