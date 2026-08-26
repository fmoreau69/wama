"""
Capacité d'import : enregistrements RTMaps `.rec`.

Troisième lecteur, et le premier qui éprouve VRAIMENT le contrat : `.trip` est du SQLite indexé,
un `.csv` porte un flux unique — un `.rec` est un **texte séquentiel où tous les flux sont
entrelacés**. Rien n'y est indexé par flux.

Spécification : `WAMA_DATA_WORLD.md §6.6` (portage de `pynd/rec2trip`) et **§6.6bis** (ce que la
lecture du code ET de deux corpus RÉELS a ajouté). Ce module ne redécouvre rien : il traduit.

CE QUE DEUX CORPUS RÉELS ONT APPRIS, ET QU'AUCUNE LECTURE DE CODE SEULE N'AURAIT DONNÉ
─────────────────────────────────────────────────────────────────────────────────────────

⭐ **① LE `.idy` EST L'INVENTAIRE, ET IL TIENT DANS QUELQUES KILO-OCTETS.** 2,7 Ko en face d'un
   `.rec` de 1,54 Go — un rapport de ~500 000. C'est donc lui, et jamais un balayage, qui répond à
   `probe()`. Une ligne par flux :

       <time_of_issue> @ Record <composant>.<sortie>(…) as <encodage>

⚠ **② SA GRAMMAIRE CHANGE SELON LA VERSION DE RTMAPS — mesuré sur les deux corpus :**

       v4.5.3 (2019)   Record DR2.message(DR2_message, python_v2.output[…]) as txt
       v4.8.0 (2022)   Record GPS_NMEA0183_3.oPosition(GPS_NMEA0183.oPosition[…]) as tabbed_text
                                                  └── le nom de table a DISPARU

   Un lecteur écrit sur un seul échantillon casserait sur l'autre. On ne lit donc **que
   `composant.sortie` et le suffixe `as <encodage>`**, en s'arrêtant à la parenthèse — exactement
   ce que fait `rec2trip`, qui est de ce fait immunisé sans le dire. Le nom du fichier compagnon
   se DÉRIVE par convention (`<rec>_<composant>_<sortie>.<ext>`), il ne se lit pas.

⚠ **③ L'ENCODAGE DÉCLARE LE TRANSPORT, PAS LA STRUCTURE.** Deux flux `as txt` du même corpus :

       DR2.message   →  Pas=1776;V_vp:Vitesse=0,000;V_vp:Pk=1420000;…   (clé=valeur, virgule FR)
       PUPIL_GLASSES →  {"topic": "gaze.3d.01.", "gaze_normals_3d": {…}} (JSON)

   Ce module s'arrête donc au TRANSPORT : il rend la charge utile **telle quelle**, en texte. La
   sémantique par famille de flux (le `data_parser/` de pynd) est une couche au-dessus, et elle
   n'est pas écrite ici — ⚠ notamment la **virgule décimale française**, sur laquelle un `float()`
   naïf échoue en silence.

⚠ **④ LES PERTES SE COMPTENT, ELLES NE SE TAISENT PAS.** RTMaps numérote les échantillons (`#idx`).
   Un index qui saute = un échantillon perdu à l'acquisition. `pynd` le détecte (`check_idx`) et
   se contente d'un `log.error` — son propre `TODO` l'admet. Ici le compte est porté comme
   **DONNÉE** (`SignalMeta.pertes`), pas comme un message.

⚠ **⑤ LES DONNÉES SONT INLINE, même quand des CSV par flux existent à côté.** Vérifié sur le
   corpus 2022 : `Accel_Sensor.X_axis#0@00:00.669604=-0.0390625` est dans le `.rec`, et un
   `…_Accel_Sensor_X_axis.csv` existe aussi. Le `.rec` est plus riche — il porte les DEUX temps
   (émission et capture) et l'index. C'est donc lui qu'on lit ; les CSV sont un recoupement.

⏳ NON EXPLOITÉ, ET DÉLIBÉRÉMENT : le `.idx` est un index binaire (`[STDB v2.0]`, section
`[Index]`, entiers 8 octets croissants — un point tous les ~740 Ko). Il permettrait de chercher
sans balayer. **`pynd` ne le lit pas et la spec RTMaps n'est pas à disposition** : construire
dessus serait deviner. Noté comme piste, pas comme fondation.
"""
from __future__ import annotations

import re
from array import array
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from wama.common.catalog.data_types import DataType

from ..core.temporal import NEAREST, PREVIOUS, SignalMeta
from . import SourceInfo, SourceReader, StreamSpec, register_reader

#: Une ligne de DONNÉE : `<toi> / <composant>.<sortie>#<idx>[…][@<ts>][=<charge>]`.
#: Les groupes optionnels le sont réellement — une ligne sans `=` porte son index pour valeur
#: (règle de `rec2trip`), et une ligne sans `@` retombe sur le temps d'émission.
_TEMPS = r"\d+:\d{2}(?::\d{2})?\.\d{6}"
_DONNEE = re.compile(
    r"^(?P<toi>" + _TEMPS + r")\s*/\s*"
    r"(?P<composant>\w+)\.(?P<sortie>\w+)#(?P<idx>\d+)[^@=\r\n]*"
    r"(?:@(?P<ts>" + _TEMPS + r")?[^=\r\n]*)?"
    r"(?:=(?P<charge>.*))?$")

#: Une ligne d'INVENTAIRE, dans le `.idy` comme dans le `.rec`. ⚠ On s'arrête à la parenthèse :
#: son contenu a changé entre RTMaps v4.5.3 et v4.8.0 (piège ②).
_RECORD = re.compile(
    r"^(?P<toi>" + _TEMPS + r")\s*@\s*Record\s+"
    r"(?P<composant>\w+)\.(?P<sortie>\w+)\(.*?\)\s*as\s+(?P<encodage>\w+)")

#: `Launched at 14:47:10.662 (02/05/2019)` — et sa variante 2022 suffixée `UTC+02:00 - …`.
_LANCEMENT = re.compile(r"^Launched at\s+(?P<quand>.+?)(?:\s+UTC.*)?$")

#: Encodages dont la charge utile vit dans un FICHIER EXTERNE, pas dans le `.rec`.
ENCODAGES_EXTERNES = {'video_file': '.avi', 'audio_file': '.wav', 'raw': '.raw'}

#: Encodages dont la charge est du texte inline — le périmètre de ce lecteur.
ENCODAGES_TEXTE = {'txt', 'tabbed_text'}


def to_seconds(brut: str) -> Optional[float]:
    """`MM:SS.ffffff` ou `H:MM:SS.ffffff` → secondes. `None` si illisible.

    Les heures n'apparaissent qu'au-delà de la première — d'où le format variable, qui est une
    propriété du format et non une négligence.
    """
    if not brut:
        return None
    bouts = brut.split(':')
    try:
        if len(bouts) == 2:
            return int(bouts[0]) * 60 + float(bouts[1])
        if len(bouts) == 3:
            return int(bouts[0]) * 3600 + int(bouts[1]) * 60 + float(bouts[2])
    except ValueError:
        return None
    return None


def _nom_flux(composant: str, sortie: str) -> str:
    return f"{composant}.{sortie}"


def _compagnon(rec: Path, composant: str, sortie: str, ext: str) -> Optional[Path]:
    """Fichier externe d'un flux, par CONVENTION `<rec>_<composant>_<sortie>.<ext>`.

    ⚠ Dérivé, jamais lu dans le `.idy` : le nom de table n'y figure plus depuis RTMaps v4.8
    (piège ②). Vérifié sur le corpus 2022 —
    `h264_stream_framer_1.output_stream` → `…_h264_stream_framer_1_output_stream.avi`.
    """
    p = rec.with_name(f"{rec.stem}_{composant}_{sortie}{ext}")
    return p if p.exists() else None


class RecReader(SourceReader):
    format = 'rtmaps'
    extensions = ('.rec',)
    description = "Enregistrement RTMaps (.rec) — flux entrelacés, inventaire dans le .idy"

    # ── Reconnaissance ────────────────────────────────────────────────────────────────────────
    def can_read(self, path: Path) -> bool:
        if path.suffix.lower() not in self.extensions:
            return False
        # On renifle l'en-tête : un `.rec` RTMaps l'annonce en clair. Sans ça, un fichier mal
        # nommé échouerait loin de sa cause.
        try:
            with path.open('r', encoding='latin-1', errors='replace') as fh:
                return 'RTMaps' in (fh.readline() or '')
        except OSError:
            return False

    # ── Inventaire — par le `.idy`, jamais par un balayage ────────────────────────────────────
    def probe(self, path: Path) -> SourceInfo:
        idy = path.with_suffix('.idy')
        depuis_idy = idy.exists()
        rows = self._entete(idy if depuis_idy else path)

        stream: List[str] = []
        encodages: Dict[str, str] = {}
        medias: List[Dict[str, Any]] = []
        attributs: Dict[str, Any] = {}

        for ligne in rows:
            m = _LANCEMENT.match(ligne)
            if m:
                attributs['recording_start_time'] = m.group('quand').strip()
                continue
            m = _RECORD.match(ligne)
            if not m:
                continue
            name = _nom_flux(m.group('composant'), m.group('sortie'))
            if name in encodages:
                continue
            encodages[name] = m.group('encodage')
            stream.append(name)
            ext = ENCODAGES_EXTERNES.get(m.group('encodage'))
            if ext:
                compagnon = _compagnon(path, m.group('composant'), m.group('sortie'), ext)
                medias.append({'file': str(compagnon) if compagnon else '',
                               'offset': 0.0, 'description': f"{name} ({m.group('encodage')})"})

        attributs['encodages'] = encodages
        attributs['inventaire'] = 'idy' if depuis_idy else 'rec (balayage d\'en-tête)'
        lisibles = [f for f in stream if encodages[f] in ENCODAGES_TEXTE]
        return SourceInfo(
            format=self.format, path=str(path), streams=stream,
            attributes=attributs, media=medias,
            notes=(f"{len(stream)} flux déclaré(s), dont {len(lisibles)} en texte inline ; "
                   f"{len(medias)} fichier(s) externe(s) ; inventaire lu dans "
                   f"« {idy.name if depuis_idy else path.name} »"),
        )

    @staticmethod
    def _entete(path: Path, max_lignes: int = 20000) -> List[str]:
        """Lignes d'inventaire. Sur un `.idy` c'est tout le fichier (quelques kilo-octets) ;
        sur un `.rec`, on se borne — les déclarations `@ Record` sont en tête."""
        out: List[str] = []
        with path.open('r', encoding='latin-1', errors='replace') as fh:
            for i, ligne in enumerate(fh):
                if i >= max_lignes:
                    break
                out.append(ligne.rstrip('\r\n'))
        return out

    # ── Lecture ───────────────────────────────────────────────────────────────────────────────
    def read(self, path: Path, streams: Optional[Iterable[str]] = None,
             timestampers: Optional[Dict[str, Any]] = None) -> List[StreamSpec]:
        """UNE passe sur le `.rec`, en ne matérialisant que les flux DEMANDÉS.

        ⚠ Le coût est borné par la demande, pas par le fichier. C'est la seule façon tenable :
        un `.rec` réel fait 1,54 Go et porte 20 flux, dont l'appelant n'en veut presque jamais
        plus de deux ou trois — et le manifeste `dataset` déclare précisément lesquels.

        ⚠ Les flux à charge EXTERNE (vidéo, audio) ne sont pas des flux de données : ils sont
        rendus par `probe().media` avec leur décalage, jamais lus ici.
        """
        timestampers = timestampers or {}
        info = self.probe(path)
        encodages: Dict[str, str] = info.attributes.get('encodages', {})
        voulus = set(streams) if streams is not None else {
            f for f in info.streams if encodages.get(f) in ENCODAGES_TEXTE}

        inconnus = voulus - set(info.streams)
        if inconnus:
            raise ValueError(
                f"flux inconnu(s) de cette source : {', '.join(sorted(inconnus))} "
                f"(déclarés : {', '.join(info.streams) or '—'})")
        externes = {f for f in voulus if encodages.get(f) in ENCODAGES_EXTERNES}
        if externes:
            raise ValueError(
                f"{', '.join(sorted(externes))} : charge EXTERNE "
                f"({', '.join(sorted({encodages[f] for f in externes}))}) — ces flux sont des "
                "médias liés, exposés par `probe().media`, pas des flux de données")

        # `array` et non des listes Python : 7,7 M échantillons estimés sur le corpus réel, et un
        # flottant en liste coûte ~4× un `array('d')`.
        temps: Dict[str, array] = {f: array('d') for f in voulus}
        charges: Dict[str, List[Any]] = {f: [] for f in voulus}
        dernier_idx: Dict[str, int] = {}
        losses: Dict[str, int] = {f: 0 for f in voulus}

        with path.open('r', encoding='latin-1', errors='replace') as fh:
            for ligne in fh:
                m = _DONNEE.match(ligne)
                if not m:
                    continue
                name = _nom_flux(m.group('composant'), m.group('sortie'))
                if name not in voulus:
                    continue

                idx = int(m.group('idx'))
                precedent = dernier_idx.get(name)
                if precedent is not None and idx != precedent + 1:
                    # ④ Un index non consécutif = échantillon(s) perdu(s) à l'acquisition.
                    losses[name] += max(0, idx - precedent - 1)
                dernier_idx[name] = idx

                toi = to_seconds(m.group('toi'))
                ts = to_seconds(m.group('ts'))
                horodateur = timestampers.get(name)
                if horodateur is not None:
                    t = horodateur.timestamp(toi, idx, ts)
                else:
                    t = ts if ts is not None else toi
                if t is None:
                    continue
                temps[name].append(t)
                # ③ Charge rendue TELLE QUELLE : le transport est générique, la sémantique non.
                charge = m.group('charge')
                charges[name].append(idx if charge is None else charge)

        out: List[StreamSpec] = []
        for name in sorted(voulus):
            rows = [{'value': v} for v in charges[name]]
            meta = SignalMeta(
                name=name,
                data_type=DataType.TIMESERIES,
                default_lookup=NEAREST,
                losses=losses[name],
                comments=f"rtmaps · {encodages.get(name, '?')}",
            )
            out.append(StreamSpec(meta=meta, times=list(temps[name]),
                                  rows=(lambda l: (lambda i0, i1: l[i0:i1]))(rows)))
        return out


register_reader(RecReader())
