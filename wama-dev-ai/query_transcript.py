#!/usr/bin/env python3
"""
query_transcript.py — Rechercher dans un transcript Claude Code (.jsonl) SANS le charger en entier.

Utile pour repêcher des éléments d'une vieille session lourde (ex. ~265 Mo) depuis une session
neuve, sans la rouvrir. Itère ligne par ligne (un message JSON par ligne), n'imprime que les
messages dont le contenu texte matche le terme recherché, avec un extrait contextuel.

Exemples :
    python query_transcript.py "ego-motion"
    python query_transcript.py "distance_speed" --ignore-case --context 300
    python query_transcript.py "TTC|conflit" --regex --max 30
    python query_transcript.py "headroom" --file ~/.claude/projects/<proj>/<id>.jsonl
    python query_transcript.py "vitesse" --roles user,assistant --no-thinking

Par défaut, cible le plus GROS .jsonl du dossier projet courant (souvent la session lourde).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys


def _default_transcript() -> str | None:
    """Plus gros .jsonl sous ~/.claude/projects/<dossier du projet courant>/."""
    home = os.path.expanduser("~")
    base = os.path.join(home, ".claude", "projects")
    if not os.path.isdir(base):
        return None
    # Heuristique : dossier dont le nom encode le cwd (Claude Code remplace les séparateurs par '-').
    candidates = glob.glob(os.path.join(base, "*", "*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: os.path.getsize(p))


def _blocks_text(obj: dict, include_thinking: bool) -> list[tuple[str, str]]:
    """Retourne [(label, texte)] pour les blocs de contenu d'un message."""
    out: list[tuple[str, str]] = []
    msg = obj.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        out.append(("text", content))
        return out
    if not isinstance(content, list):
        return out
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "?")
        if btype == "thinking":
            if include_thinking:
                out.append(("thinking", block.get("thinking", "")))
        elif btype == "text":
            out.append(("text", block.get("text", "")))
        elif btype == "tool_use":
            out.append((f"tool_use:{block.get('name','?')}",
                        json.dumps(block.get("input", {}), ensure_ascii=False)))
        elif btype == "tool_result":
            c = block.get("content")
            out.append(("tool_result", c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Rechercher dans un transcript Claude Code (.jsonl).")
    ap.add_argument("term", help="Terme recherché (texte littéral, ou regex avec --regex).")
    ap.add_argument("--file", "-f", default=None, help="Chemin du .jsonl (défaut : le plus gros du projet).")
    ap.add_argument("--regex", action="store_true", help="Interpréter le terme comme une regex.")
    ap.add_argument("--ignore-case", "-i", action="store_true", help="Insensible à la casse.")
    ap.add_argument("--context", "-C", type=int, default=200, help="Caractères de contexte autour du match (défaut 200).")
    ap.add_argument("--max", "-m", type=int, default=50, help="Nombre max de résultats (défaut 50).")
    ap.add_argument("--roles", default=None, help="Filtrer par type top-level, ex: user,assistant.")
    ap.add_argument("--no-thinking", action="store_true", help="Ignorer les blocs de raisonnement.")
    args = ap.parse_args()

    path = args.file or _default_transcript()
    if not path:
        print("Aucun transcript trouvé. Précise --file.", file=sys.stderr)
        return 2
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        print(f"Introuvable : {path}", file=sys.stderr)
        return 2

    flags = re.IGNORECASE if args.ignore_case else 0
    pattern = re.compile(args.term if args.regex else re.escape(args.term), flags)
    roles = set(r.strip() for r in args.roles.split(",")) if args.roles else None

    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"# Transcript : {path} ({size_mb:.1f} Mo)")
    print(f"# Recherche  : {args.term!r}{' (regex)' if args.regex else ''}\n")

    hits = 0
    with open(path, "r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh):
            if hits >= args.max:
                print(f"\n… (limite {args.max} atteinte ; affine ou augmente --max)")
                break
            try:
                obj = json.loads(line)
            except Exception:
                continue
            ttype = obj.get("type", "?")
            if roles and ttype not in roles:
                continue
            for label, text in _blocks_text(obj, include_thinking=not args.no_thinking):
                if not text:
                    continue
                m = pattern.search(text)
                if not m:
                    continue
                start = max(0, m.start() - args.context)
                end = min(len(text), m.end() + args.context)
                snippet = text[start:end].replace("\n", " ").strip()
                prefix = "…" if start > 0 else ""
                suffix = "…" if end < len(text) else ""
                print(f"[line {idx} · {ttype} · {label}] {prefix}{snippet}{suffix}\n")
                hits += 1
                if hits >= args.max:
                    break

    if hits == 0:
        print("Aucun résultat.")
    else:
        print(f"# {hits} résultat(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
