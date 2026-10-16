"""
Un MIDI multi-pistes → une partition ABC LISIBLE (2026-10-16, la « Partition complète » du composer).

Commune à tout moteur de la tâche `audio-to-midi` (`MidiExtractionBackend`) : le moteur rend des
notes, la NOTATION est d'ici — la page d'édition grave l'ABC (abcjs) et le cale sur l'audio
(`WamaScore.align`) comme la partition extraite. Décision de Fabien (veille du 2026-10-16, point d) :
une brique à nous plutôt que MuseScore 4 — pas de binaire hôte, et le format que la page lit déjà.

Ce qu'elle écrit :
  • UNE voix par instrument, nommée comme sa piste ; le PIANO sur deux portées liées par une
    accolade (`%%score {…}`), coupées au do du milieu ; la BATTERIE sur une portée de percussion
    (`clef=perc`, têtes en croix pour charleston et cymbales — `%%percmap`) ;
  • quantifiée sur la double croche (`grid` pas par noire) au tempo du MIDI — un MIDI de
    MuScriptor est à tempo constant, la mesure 1 au temps 0 ;
  • polyphonie d'une voix en ACCORDS, une note qui continue au-delà d'un découpage LIÉE (`-`),
    une durée non écrivable découpée en valeurs usuelles liées ;
  • altérations en dièses, la règle ABC respectée : une altération vaut jusqu'à la barre, donc un
    bécarre (`=`) est écrit quand la même note revient naturelle dans la mesure.
Elle ne devine PAS la tonalité (`K:C`, altérations écrites) : la partition extraite (SheetSage2) la
porte, celle-ci rend ce qui sonne.

Le fichier se lit par `read_midi`, la LECTURE MIDI commune : le moteur YuE2 la consomme aussi
(`yue2_3b_backend._midi_events`, une partition MIDI ramenée à sa ligne mélodique).
"""
from __future__ import annotations

import io

#: Classe de hauteur → (lettre, dièse ?) — on écrit en dièses (`K:C`).
_PITCH_CLASSES = [('C', False), ('C', True), ('D', False), ('D', True), ('E', False), ('F', False),
                  ('F', True), ('G', False), ('G', True), ('A', False), ('A', True), ('B', False)]

#: Batterie General MIDI → ligne de la portée de percussion (note ABC). Charleston et cymbales
#: reçoivent une tête en croix (`%%percmap`).
_DRUM_LINES = {
    35: 'F', 36: 'F',                                   # grosse caisse
    37: 'c', 38: 'c', 39: 'c', 40: 'c',                 # caisse claire, rim, clap
    41: 'A', 43: 'A', 45: 'B', 47: 'B', 48: 'd', 50: 'e',   # toms, du grave à l'aigu
    42: 'g', 44: 'g', 46: 'g',                          # charleston
    49: 'a', 51: 'f', 52: 'a', 53: 'f', 55: 'a', 57: 'a', 59: 'f',  # cymbales
}
#: Ligne → son General MIDI qui la représente (`%%percmap <ligne> <numéro MIDI> [tête]` : abcjs
#: attend un NUMÉRO de 35 à 81 ou son nom, relu dans sa source le 2026-10-16), et les lignes à
#: tête en croix.
_DRUM_SOUNDS = {'F': 36, 'c': 38, 'A': 45, 'B': 47, 'd': 48, 'e': 50, 'g': 42, 'a': 49, 'f': 51}
_DRUM_CROSS = ('g', 'a', 'f')
#: Valeurs écrivables, en pas de grille (double croche → ronde), de la plus longue à la plus courte.
_WRITABLE = (16, 12, 8, 6, 4, 3, 2, 1)
#: Un instrument de clavier : deux portées (main droite / main gauche).
_KEYBOARD_WORDS = ('piano', 'keyboard', 'clavier', 'harpsichord', 'organ', 'orgue')
#: Libellés AFFICHÉS des pistes (la langue de l'interface est le français) : le vocabulaire fermé
#: des 35 groupes d'instruments de MuScriptor (`MT3_FULL_PLUS`, relu le 2026-10-16) ; un nom
#: inconnu s'affiche tel quel, capitalisé.
INSTRUMENT_LABELS = {
    'acoustic bass': 'Contrebasse jazz', 'acoustic guitar': 'Guitare acoustique',
    'acoustic piano': 'Piano', 'baritone sax': 'Saxophone baryton', 'bassoon': 'Basson',
    'brass section': 'Cuivres', 'cello': 'Violoncelle', 'chromatic percussion': 'Percussions à clavier',
    'clarinet': 'Clarinette', 'clean electric guitar': 'Guitare électrique',
    'contrabass': 'Contrebasse', 'distorted electric guitar': 'Guitare saturée',
    'drums': 'Batterie', 'electric bass': 'Basse électrique', 'electric piano': 'Piano électrique',
    'english horn': 'Cor anglais', 'flutes': 'Flûtes', 'french horn': 'Cor', 'oboe': 'Hautbois',
    'orchestra hit': 'Coup d’orchestre', 'orchestral harp': 'Harpe', 'organ': 'Orgue',
    'soprano and alto sax': 'Saxophone', 'string ensemble': 'Cordes', 'synth lead': 'Synthé solo',
    'synth pad': 'Nappe de synthé', 'synth strings': 'Cordes synthétiques',
    'tenor sax': 'Saxophone ténor', 'timpani': 'Timbales', 'trombone': 'Trombone',
    'trumpet': 'Trompette', 'tuba': 'Tuba', 'viola': 'Alto', 'violin': 'Violon', 'voice': 'Voix',
}


def instrument_label(name: str) -> str:
    """Le libellé français d'une piste nommée par le moteur (`INSTRUMENT_LABELS`)."""
    key = (name or '').strip().replace('_', ' ').lower()
    return INSTRUMENT_LABELS.get(key) or (name or '').strip().capitalize()


class MidiPart:
    """Une partie du MIDI — une piste et un canal : son nom (`track_name`), batterie ou non (canal
    10), ses notes `(début, fin, hauteur)` en TICKS."""
    __slots__ = ('name', 'is_drum', 'notes')

    def __init__(self, name: str, is_drum: bool, notes: list):
        self.name, self.is_drum, self.notes = name, is_drum, notes


class MidiSong:
    """Ce qu'un fichier MIDI déclare, lu une fois (`read_midi`) : la base de temps, la carte des
    tempos `[(tick, µs par noire)]`, la PREMIÈRE mesure et la PREMIÈRE tonalité déclarées (None
    sinon), les marqueurs et les parties qui ont des notes."""

    def __init__(self, ticks_per_beat: int, tempi: list, meter, key, markers: list, parts: list):
        self.ticks_per_beat, self.tempi, self.meter, self.key = ticks_per_beat, tempi, meter, key
        self.markers, self.parts = markers, parts

    def quarters(self, tick) -> float:
        """Un instant en noires écrites (la grille du MIDI, quel que soit son tempo)."""
        return tick / self.ticks_per_beat

    def seconds(self, tick) -> float:
        """Un instant en secondes, à travers la carte des tempos (120 à la noire avant le 1er)."""
        total, last, tempo = 0.0, 0, 500000
        for at, value in self.tempi:
            if at >= tick:
                break
            total += (at - last) * tempo / (self.ticks_per_beat * 1e6)
            last, tempo = at, value
        return total + (tick - last) * tempo / (self.ticks_per_beat * 1e6)


def read_midi(source) -> MidiSong:
    """La LECTURE MIDI commune (2026-10-16) — un chemin ou des octets → `MidiSong`, par `mido`.

    Extraite au second consommateur, comme son premier l'annonçait : le moteur YuE2 qui suit une
    partition MIDI (`yue2_3b_backend._midi_events`) et la notation d'ici. Une partie par PISTE ET
    CANAL (un MIDI de type 0 porte tous ses instruments dans une seule piste) ; une note commence
    à un `note_on` de vélocité non nulle et finit au `note_off` (ou `note_on` à 0) suivant."""
    import mido

    song = (mido.MidiFile(file=io.BytesIO(source)) if isinstance(source, (bytes, bytearray))
            else mido.MidiFile(str(source)))
    tempi, meter, key, markers, tick = [], None, None, [], 0
    for msg in mido.merge_tracks(song.tracks):
        tick += msg.time
        if msg.type == 'set_tempo':
            # Un tempo RÉPÉTÉ d'une piste à l'autre (MuScriptor le recopie pour MuseScore) n'en
            # est pas un nouveau.
            if not tempi or tempi[-1][1] != msg.tempo:
                tempi.append((tick, msg.tempo))
        elif msg.type == 'time_signature' and meter is None:
            meter = (msg.numerator, msg.denominator)
        elif msg.type == 'key_signature' and key is None:
            key = msg.key
        elif msg.type == 'marker':
            markers.append(msg.text)
    parts = []
    for track in song.tracks:
        name, tick, started, by_channel = '', 0, {}, {}
        for msg in track:
            tick += msg.time
            if msg.type == 'track_name' and not name:
                name = msg.name
            elif msg.type in ('note_on', 'note_off'):
                slot = (msg.channel, msg.note)
                if msg.type == 'note_on' and msg.velocity > 0:
                    started.setdefault(slot, []).append(tick)
                elif slot in started:
                    # Une fin ferme toutes les attaques ouvertes de cette hauteur SAUF celles de
                    # cet instant : une note re-frappée au tick où la précédente finit commence
                    # là (la règle de pretty_midi ; garder la seule 1re attaque perdait la note,
                    # mesuré le 2026-10-16 sur des MIDI écrits par MuScriptor).
                    keep = [s for s in started[slot] if s == tick]
                    closing = [s for s in started[slot] if s != tick]
                    by_channel.setdefault(msg.channel, []).extend((s, tick, msg.note) for s in closing)
                    if closing and keep:
                        started[slot] = keep
                    else:
                        del started[slot]
        parts += [MidiPart(name.strip(), channel == 9, sorted(notes))
                  for channel, notes in sorted(by_channel.items())]
    return MidiSong(song.ticks_per_beat or 480, tempi, meter, key, markers, parts)


def abc_pitch(pitch: int) -> tuple:
    """(lettre ABC avec octave, dièse ?) d'une hauteur MIDI : 60 → ('C', False), 73 → ('c', True)."""
    letter, sharp = _PITCH_CLASSES[pitch % 12]
    octave = pitch // 12 - 5                      # 0 = l'octave du do du milieu
    if octave >= 1:
        return letter.lower() + "'" * (octave - 1), sharp
    return letter + ',' * (-octave), sharp


def split_length(steps: int) -> list:
    """Une durée en pas découpée en valeurs écrivables (la plus longue d'abord)."""
    out, left = [], int(steps)
    while left > 0:
        part = next(v for v in _WRITABLE if v <= left)
        out.append(part)
        left -= part
    return out


def _length(steps: int) -> str:
    return '' if steps == 1 else str(steps)


class _Voice:
    def __init__(self, vid: str, name: str, clef: str, notes: list, drum: bool = False):
        self.id, self.name, self.clef, self.notes, self.drum = vid, name, clef, notes, drum

    def header(self) -> str:
        # La main gauche d'un clavier ne se nomme pas : l'accolade porte le nom, une fois.
        name = '' if self.id.endswith('L') else self.name
        return f'V:{self.id} clef={self.clef} name="{name}" snm="{name[:12]}"'


def _quantize(notes, to_steps) -> list:
    """`[(début, fin, hauteur)]` en pas de grille (`to_steps` : ticks MIDI → pas, réel) ; une
    note dure au moins un pas."""
    out = []
    for start_tick, end_tick, pitch in notes:
        start = int(round(to_steps(start_tick)))
        end = max(start + 1, int(round(to_steps(end_tick))))
        out.append((start, end, int(pitch)))         # négatif possible : `midi_to_abc` décale
    return out


def bar_offset_of(markers) -> float:
    """Le décalage (s) qu'un moteur a ajouté pour poser la mesure 1 sur un temps fort — marqueur
    `…bar_offset=<s>` (convention de MuScriptor, lue sans le nommer) ; 0 s'il n'y en a pas.
    Temps de l'audio ≈ temps du MIDI − ce décalage (à la latence d'attaque près, < 25 ms)."""
    import re
    for text in markers:
        found = re.search(r'bar_offset=([-0-9.]+)', text or '')
        if found:
            return float(found.group(1))
    return 0.0


def played_beat_steps(beat_times, grid: int, offset: float):
    """`(secondes MIDI → pas)` sur les temps JOUÉS : une note se place entre les deux temps de
    l'audio qui l'encadrent, au prorata, puis en pas de `grid` par temps. Au-delà des temps
    connus, l'intervalle médian prolonge la grille."""
    import numpy as np
    beats = np.asarray(beat_times, dtype=float)
    ibi = float(np.median(np.diff(beats)))
    index = np.arange(len(beats), dtype=float)

    def to_steps(t: float) -> float:
        audio = t - offset
        if audio <= beats[0]:
            position = (audio - beats[0]) / ibi
        elif audio >= beats[-1]:
            position = len(beats) - 1 + (audio - beats[-1]) / ibi
        else:
            position = float(np.interp(audio, beats, index))
        return position * grid
    return to_steps, 60.0 / ibi


def _bar_tokens(notes, bar_start: int, bar_steps: int, drum: bool) -> str:
    """Le texte ABC d'UNE mesure d'une voix : accords, liaisons, silences, altérations."""
    bar_end = bar_start + bar_steps
    inside = [n for n in notes if n[0] < bar_end and n[1] > bar_start]
    cuts = {bar_start, bar_end}
    for s, e, _ in inside:
        cuts.add(min(max(s, bar_start), bar_end))
        # Une frappe dure jusqu'à la suivante (notation de batterie) : seules les attaques coupent.
        if not drum:
            cuts.add(min(max(e, bar_start), bar_end))
    cuts = sorted(cuts)
    accidentals = {}
    tokens = []
    for a, b in zip(cuts, cuts[1:]):
        pieces = split_length(b - a)
        if drum:
            # Une frappe ne se tient pas : seules celles qui COMMENCENT ici sonnent, au début du
            # découpage ; le reste est silence (une frappe longue n'est pas re-frappée plus loin).
            hits = sorted({_DRUM_LINES.get(p, 'c') for s, e, p in inside if s == a})
            if not hits:
                tokens.extend('z' + _length(p) for p in pieces)
                continue
            tokens.append((hits[0] if len(hits) == 1 else '[' + ''.join(hits) + ']')
                          + _length(pieces[0]))
            tokens.extend('z' + _length(p) for p in pieces[1:])
            continue
        sounding = sorted({(p, e > b) for s, e, p in inside if s <= a < e},
                          key=lambda x: (x[0], not x[1]))
        if not sounding:
            tokens.extend('z' + _length(p) for p in pieces)
            continue
        names = []
        for pitch, continues in sounding:
            name, sharp = abc_pitch(pitch)
            wanted = '^' if sharp else '='
            if accidentals.get(name, '=') != wanted:
                accidentals[name] = wanted
                name = wanted + name
            names.append((name, continues))
        # Une hauteur jouée deux fois au même instant (deux pistes fondues) ne s'écrit qu'une fois.
        names = list(dict.fromkeys(names))
        for i, piece in enumerate(pieces):
            last_piece = i == len(pieces) - 1
            # L'altération écrite au 1er morceau vaut jusqu'à la barre : les suivants s'en passent.
            notes_here = [(name if i == 0 else name.lstrip('^='),
                           '-' if (not last_piece or continues) else '') for name, continues in names]
            if len(notes_here) == 1:
                name, tie = notes_here[0]
                tokens.append(name + _length(piece) + tie)
            else:
                tokens.append('[' + ''.join(n + t for n, t in notes_here) + ']' + _length(piece))
    return ''.join(tokens)


def _voices_of(song: MidiSong, to_steps) -> list:
    voices = []
    for index, inst in enumerate(song.parts):
        notes = _quantize(inst.notes, to_steps)
        original = inst.name
        label = (instrument_label(original) if original
                 else ('Batterie' if inst.is_drum else f'Instrument {index + 1}')).replace('"', "'")
        if inst.is_drum:
            voices.append(_Voice(f'D{index}', label, 'perc', notes, drum=True))
            continue
        pitches = sorted(p for _, _, p in notes)
        wide = pitches[-1] - pitches[0] >= 24
        if any(w in original.lower() for w in _KEYBOARD_WORDS) and wide:
            right = [n for n in notes if n[2] >= 60]
            left = [n for n in notes if n[2] < 60]
            voices.append(_Voice(f'P{index}R', label, 'treble', right))
            voices.append(_Voice(f'P{index}L', label, 'bass', left))
            continue
        median = pitches[len(pitches) // 2]
        voices.append(_Voice(f'I{index}', label, 'bass' if median < 55 else 'treble', notes))
    return voices


def midi_to_abc(midi_bytes: bytes, *, title: str = '', grid: int = 4, bars_per_line: int = 4,
                beat_times=None) -> str:
    """Le texte ABC d'un MIDI multi-pistes (voir l'en-tête). Lève `ValueError` sans aucune note.

    DEUX GRILLES (2026-10-16, mesuré sur cinq rendus YuE2) :
      • le MIDI porte une MÉTRIQUE (le moteur a trouvé un tempo constant et ses temps forts, #754) :
        on écrit sur SA grille — tempo du MIDI, mesure 1 au temps 0 ;
      • sinon (tempo de remplacement : le morceau change de tempo ou de phase d'une section à
        l'autre, #755, #756, #343) et `beat_times` est donné (les temps JOUÉS de l'audio,
        `common/utils/audio_rhythm.py`) : chaque note est placée sur ces temps-là
        (`played_beat_steps`), en 4/4, la mesure 1 au premier temps joué. Les barres suivent alors
        la musique au lieu d'un 120 bpm qui n'a jamais été joué."""
    song = read_midi(midi_bytes)
    bpm = 60e6 / song.tempi[0][1] if song.tempi else 120.0
    numerator, denominator = song.meter or (4, 4)
    # `grid` pas par NOIRE écrite : la grille du MIDI lui-même, sauf sans métrique (ci-dessus).
    to_steps = lambda tick: song.quarters(tick) * grid    # noqa: E731
    if song.meter is None and beat_times is not None and len(beat_times) >= 8:
        on_beats, bpm = played_beat_steps(beat_times, grid, bar_offset_of(song.markers))
        to_steps = lambda tick: on_beats(song.seconds(tick))    # noqa: E731
    bar_steps = int(round(numerator * 4 / denominator * grid))
    voices = _voices_of(song, to_steps)
    if not voices:
        raise ValueError("MIDI sans aucune note : rien à écrire")
    # Une note AVANT la mesure 1 (anacrouse avant le premier temps joué) : toute la partition
    # recule d'un nombre entier de mesures, rien n'est écrasé au temps 0.
    lowest = min(s for v in voices for s, _, _ in v.notes)
    if lowest < 0:
        shift = -(lowest // bar_steps) * bar_steps
        for v in voices:
            v.notes = [(s + shift, e + shift, p) for s, e, p in v.notes]
    last = max(e for v in voices for _, e, _ in v.notes)
    bars = max(1, -(-last // bar_steps))

    groups = []
    for v in voices:
        if v.id.endswith('L') and groups and groups[-1] == v.id[:-1] + 'R':
            groups[-1] = '{' + groups[-1] + ' ' + v.id + '}'
        else:
            groups.append(v.id)
    head = ['X:1', f'T:{title}', f'M:{numerator}/{denominator}', f'L:1/{4 * grid}',
            f'Q:1/4={int(round(bpm))}', '%%score ' + ' '.join(groups)]
    if any(v.drum for v in voices):
        head += [f'%%percmap {line} {sound}' + (' x' if line in _DRUM_CROSS else '')
                 for line, sound in _DRUM_SOUNDS.items()]
    head += [v.header() for v in voices]
    head.append('K:C')

    body = []
    for first in range(0, bars, bars_per_line):
        span = range(first, min(bars, first + bars_per_line))
        for v in voices:
            body.append(f'V:{v.id}')
            body.append('|'.join(_bar_tokens(v.notes, b * bar_steps, bar_steps, v.drum)
                                 for b in span) + '|')
    return '\n'.join(head + body) + '\n'
