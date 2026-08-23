#!/usr/bin/env python3
"""
Analyse des rails d'alimentation (HWiNFO64) et corrélation avec `hwlog`.

CONTEXTE (2026-08-10)
=====================
L'hôte enchaîne des coupures froides AU REPOS depuis le 31/07 (7 à ce jour).
L'alimentation fait 1600 W — le sous-dimensionnement est donc EXCLU. Restent
deux hypothèses non départagées :
  - vieillissement du bloc (rail bas ou qui dérive lentement) ;
  - instabilité à FAIBLE charge (régulation qui décroche sous ~10 % de charge).

Les deux se voient dans les tensions de rails ; aucune des deux ne se voit dans
`hwlog`, qui ne mesure que le GPU. D'où ce script.

CE QU'IL VOIT / CE QU'IL NE VOIT PAS
====================================
HWiNFO échantillonne au mieux toutes les ~0,5-2 s. L'événement qui tue la
machine dure des MICROSECONDES : la dernière ligne avant la coupure affichera
des valeurs normales, exactement comme `hwlog` aujourd'hui. Ce script ne dira
donc JAMAIS « voilà ce qui l'a tuée ». Il répond à une autre question, non
mesurée jusqu'ici : « un rail est-il chroniquement hors tolérance, ou dérive-t-il ? »

Test ASYMÉTRIQUE, à garder en tête en lisant la sortie :
  - un rail hors spec ou en dérive  → diagnostic quasiment bouclé ;
  - rien d'anormal                  → n'innocente PAS le bloc (angle mort µs).

USAGE
=====
    python scripts/analyze_rails.py <hwinfo.csv> [--hwlog-dir logs/hwlog]
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Tolérances ATX (±5 % sur les rails principaux, ±5 % sur le 3,3 V).
# Sortir de ces bornes, même brièvement, est un défaut caractérisé.
ATX_SPECS = {
    "+12V": (12.0, 11.40, 12.60),
    "+5V": (5.0, 4.75, 5.25),
    "+3.3V": (3.3, 3.135, 3.465),
    "GPU 12VHPWR": (12.0, 11.40, 12.60),
    "GPU PCIe +12V": (12.0, 11.40, 12.60),
}

# Les noms de capteurs varient selon la carte (ici MSI Z390-A PRO → Nuvoton) ET selon la
# LOCALE de HWiNFO. On ANCRE au début du libellé : c'est ce qui sépare le vrai rail
# « +5V [V] » d'un homonyme comme « Core 5 VID [V] ».
#
# ⚠ DEUX BUGS CORRIGÉS LE 2026-08-23, AU PREMIER USAGE RÉEL (23 h de journal) :
#   1. `search()` NON ANCRÉ + « première correspondance retenue » faisait pointer +5V sur
#      « Core 5 VID [V] » (colonne 16) au lieu de « +5V [V] » (colonne 256) → le rapport
#      annonçait « 🔴 HORS TOLÉRANCE : 100,00 % des échantillons, moy=1,089 V » sur un rail
#      parfaitement sain à 5,08 V. Un instrument qui accuse à tort est pire que pas
#      d'instrument : il aurait fait condamner une alimentation.
#   2. La locale FR écrit « +3 3V (AVCC) » — ESPACE en séparateur décimal, pas un point.
#      L'ancien motif `3[.,]3` ne matchait rien, et le +3,3 V n'était donc SILENCIEUSEMENT
#      jamais analysé. Une absence ne se voyait nulle part dans le rapport.
RAIL_PATTERNS = (
    ("+12V", re.compile(r"^\+?12\s*V\b", re.I)),
    ("+5V", re.compile(r"^\+?5\s*V(?!\s*SB)\b", re.I)),
    ("+3.3V", re.compile(r"^\+?3[.,\s]3\s*V", re.I)),
    # Lus À LA CARTE et non au SuperIO. Le 12VHPWR est LE rail qui alimente la 4090 en
    # rampe, et sa résolution est bien meilleure que celle du Nuvoton (qui quantifie par
    # pas de ~96 mV, au point d'afficher min=max sur des dizaines d'échantillons).
    ("GPU 12VHPWR", re.compile(r"^GPU\s+12VHPWR", re.I)),
    ("GPU PCIe +12V", re.compile(r"^GPU\s+PCIe\s*\+?12\s*V", re.I)),
)

# Un trou supérieur à ce seuil dans la série = coupure (même convention qu'hwlog).
GAP_SECONDS = 45


def sniff_reader(path: Path):
    """
    Ouvre le CSV HWiNFO. Deux pièges : l'encodage (ANSI/latin-1 selon la locale,
    pas UTF-8) et le séparateur (';' en locale FR, ',' en locale EN).
    """
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"Encodage illisible : {path}")

    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    return list(csv.reader(text.splitlines(), delimiter=delimiter))


def find_rail_columns(header: list[str]) -> dict[str, int]:
    """
    Associe chaque rail à sa colonne, par motif ANCRÉ sur le début du libellé.

    Le libellé HWiNFO peut être entre guillemets et suffixé de son unité
    (« "+12V [V]" ») : on nettoie avant d'ancrer, sinon `^` ne matche jamais.
    """
    found: dict[str, int] = {}
    for index, name in enumerate(header):
        propre = name.strip().strip('"').strip()
        for rail, pattern in RAIL_PATTERNS:
            if rail not in found and pattern.match(propre):
                found[rail] = index
    return found


def parse_timestamp(row: list[str]) -> datetime | None:
    """HWiNFO écrit Date puis Time en deux colonnes ; formats locale-dépendants."""
    if len(row) < 2:
        return None
    stamp = f"{row[0].strip()} {row[1].strip()}"
    for fmt in ("%d.%m.%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S.%f",
                "%d.%m.%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def to_float(value: str) -> float | None:
    """Les valeurs peuvent être en virgule décimale selon la locale."""
    try:
        return float(value.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None


def analyse_rail(name: str, samples: list[tuple[datetime, float]]) -> None:
    """Statistiques, hors-spec et dérive pour un rail."""
    nominal, low, high = ATX_SPECS[name]
    values = [v for _, v in samples]

    out_of_spec = [(t, v) for t, v in samples if v < low or v > high]
    ecart_pct = (statistics.mean(values) - nominal) / nominal * 100

    print(f"\n  {name}  (nominal {nominal} V, tolérance {low}–{high} V)")
    print(f"    n={len(values)}  min={min(values):.3f}  moy={statistics.mean(values):.3f}  "
          f"max={max(values):.3f}  écart-type={statistics.pstdev(values):.4f}")
    print(f"    écart à la valeur nominale : {ecart_pct:+.2f} %")

    if out_of_spec:
        print(f"    🔴 HORS TOLÉRANCE : {len(out_of_spec)} échantillon(s) "
              f"({len(out_of_spec) / len(values) * 100:.2f} %)")
        for stamp, value in out_of_spec[:5]:
            print(f"       {stamp:%Y-%m-%d %H:%M:%S}  {value:.3f} V")
        if len(out_of_spec) > 5:
            print(f"       … et {len(out_of_spec) - 5} autre(s)")
    else:
        print("    ✅ toujours dans la tolérance ATX")

    # Dérive : première heure vs dernière heure. Une alim qui vieillit sous
    # contrainte thermique s'affaisse progressivement — invisible sur les min/max.
    if samples[-1][0] - samples[0][0] > timedelta(hours=2):
        debut = [v for t, v in samples if t < samples[0][0] + timedelta(hours=1)]
        fin = [v for t, v in samples if t > samples[-1][0] - timedelta(hours=1)]
        if debut and fin:
            delta = statistics.mean(fin) - statistics.mean(debut)
            marque = "  ⚠ dérive notable" if abs(delta) > 0.05 else ""
            print(f"    dérive 1re heure → dernière heure : {delta:+.3f} V{marque}")


def report_gaps(series: list[datetime]) -> list[datetime]:
    """Trous dans la série = coupures. Renvoie les instants de dernière mesure."""
    deaths = []
    for previous, current in zip(series, series[1:]):
        if (current - previous).total_seconds() > GAP_SECONDS:
            deaths.append(previous)
    return deaths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path, help="CSV produit par HWiNFO64")
    parser.add_argument("--hwlog-dir", type=Path, default=Path("logs/hwlog"),
                        help="Répertoire des CSV hwlog (défaut : logs/hwlog)")
    parser.add_argument("--tail", type=int, default=8,
                        help="Échantillons à afficher avant chaque coupure (défaut : 8)")
    args = parser.parse_args()

    if not args.csv.is_file():
        print(f"Introuvable : {args.csv}", file=sys.stderr)
        return 1

    rows = sniff_reader(args.csv)
    if not rows:
        print("CSV vide.", file=sys.stderr)
        return 1

    header = rows[0]
    columns = find_rail_columns(header)
    if not columns:
        print("Aucune colonne de rail reconnue. Colonnes disponibles :", file=sys.stderr)
        for name in header[:60]:
            print(f"  - {name}", file=sys.stderr)
        print("\nDans HWiNFO, vérifie que les tensions de la carte mère (groupe "
              "Nuvoton) ne sont pas masquées dans la fenêtre Sensors.", file=sys.stderr)
        return 2

    series: dict[str, list[tuple[datetime, float]]] = {rail: [] for rail in columns}
    stamps: list[datetime] = []

    for row in rows[1:]:
        stamp = parse_timestamp(row)
        if stamp is None:
            continue  # pied de fichier HWiNFO, lignes partielles
        stamps.append(stamp)
        for rail, index in columns.items():
            if index < len(row):
                value = to_float(row[index])
                if value is not None:
                    series[rail].append((stamp, value))

    if not stamps:
        print("Aucun horodatage exploitable — format inattendu.", file=sys.stderr)
        return 2

    print("=" * 72)
    print(f"RAILS D'ALIMENTATION — {args.csv.name}")
    print(f"période : {stamps[0]:%Y-%m-%d %H:%M:%S} → {stamps[-1]:%Y-%m-%d %H:%M:%S}  "
          f"({len(stamps)} échantillons)")
    print("=" * 72)
    print(f"colonnes reconnues : " +
          ", ".join(f"{rail} → « {header[i]} »" for rail, i in sorted(columns.items())))

    for rail in sorted(series):
        if series[rail]:
            analyse_rail(rail, series[rail])

    deaths = report_gaps(stamps)
    print("\n" + "=" * 72)
    if not deaths:
        print("Aucune coupure sur la période journalisée.")
    else:
        print(f"{len(deaths)} coupure(s) détectée(s) — derniers échantillons avant chaque mort :")
        for death in deaths:
            print(f"\n  ── mort ~{death:%Y-%m-%d %H:%M:%S} ──")
            for rail in sorted(series):
                tail = [(t, v) for t, v in series[rail] if t <= death][-args.tail:]
                if tail:
                    valeurs = "  ".join(f"{v:.3f}" for _, v in tail)
                    print(f"    {rail:<6} {valeurs}")
        print("\n  ⚠ Rappel : l'échantillonnage HWiNFO (~1 s) ne peut PAS capturer")
        print("    l'événement lui-même (microsecondes). Des valeurs normales sur")
        print("    ces dernières lignes n'innocentent pas l'alimentation.")

    print("\n" + "=" * 72)
    print("Corrélation avec hwlog (charge GPU au même instant) :")
    if args.hwlog_dir.is_dir():
        jours = sorted({s.strftime("%Y%m%d") for s in stamps})
        presents = [j for j in jours if (args.hwlog_dir / f"hwlog_{j}.csv").is_file()]
        print(f"  hwlog disponible pour : {', '.join(presents) or '(aucun jour correspondant)'}")
        print(f"  → recouper les instants de coupure ci-dessus avec la colonne gpu_w")
    else:
        print(f"  (répertoire {args.hwlog_dir} absent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
