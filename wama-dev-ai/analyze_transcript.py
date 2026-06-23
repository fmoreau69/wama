#!/usr/bin/env python3
"""
analyze_transcript.py — Analyser la COMPOSITION/taille d'un transcript Claude Code (.jsonl).

Pendant « statistiques » de query_transcript.py (« recherche »). Ventile le poids du fichier par
type de ligne (user / assistant / file-history-snapshot / progress / …) pour comprendre ce qui le
fait gonfler (utile pour diagnostiquer une session lourde avant de la mettre à plat).

Exemples :
    python analyze_transcript.py
    python analyze_transcript.py --file ~/.claude/projects/<proj>/<id>.jsonl

Par défaut, cible le plus GROS .jsonl du dossier projet courant (souvent la session lourde).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def _default_transcript() -> str | None:
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    candidates = glob.glob(os.path.join(base, "*", "*.jsonl")) if os.path.isdir(base) else []
    return max(candidates, key=os.path.getsize) if candidates else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyser la composition d'un transcript Claude Code (.jsonl).")
    ap.add_argument("--file", "-f", default=None, help="Chemin du .jsonl (défaut : le plus gros du projet).")
    args = ap.parse_args()

    path = os.path.expanduser(args.file) if args.file else _default_transcript()
    if not path or not os.path.exists(path):
        print(f"Transcript introuvable ({path}). Précise --file.", file=sys.stderr)
        return 2

    top_level_bytes: dict[str, int] = {}
    top_level_count: dict[str, int] = {}
    parse_fail_bytes = parse_fail_count = total_bytes = accounted_bytes = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_bytes = len(line.encode("utf-8"))
            total_bytes += line_bytes
            try:
                obj = json.loads(line)
            except Exception:
                parse_fail_bytes += line_bytes
                parse_fail_count += 1
                continue
            t = obj.get("type", "unknown")
            top_level_bytes[t] = top_level_bytes.get(t, 0) + line_bytes
            top_level_count[t] = top_level_count.get(t, 0) + 1
            content = (obj.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    accounted_bytes += len(json.dumps(block))

    print(f"# Transcript : {path}")
    print(f"Taille totale lue : {total_bytes/1024/1024:.1f} Mo")
    print(f"Échecs de parsing : {parse_fail_count} lignes ({parse_fail_bytes/1024/1024:.1f} Mo)")
    print(f"Comptabilisé dans message.content : {accounted_bytes/1024/1024:.1f} Mo\n")
    print("Répartition par type de ligne (champ top-level 'type') :")
    for t, b in sorted(top_level_bytes.items(), key=lambda x: -x[1]):
        print(f"  {t}: {top_level_count[t]} lignes, {b/1024/1024:.1f} Mo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
