"""stage_my_hunks.py — ne mettre dans l'INDEX que SES hunks d'un fichier co-édité.

Usage :
    python .claude/skills/commit-partiel/stage_my_hunks.py <patch_out> <fichier>=<mot-clé> [...]
    git apply --cached --unidiff-zero --whitespace=nowarn <patch_out>

Pour chaque fichier, le diff arbre ↔ index est pris avec ZÉRO ligne de contexte (`-U0`) : un
hunk par plage de lignes changées, donc jamais un hunk qui mêle mes lignes et celles d'autrui
(vécu le 2026-09-14 avec le contexte par défaut sur `WAMA_MECANISMES.md`). Un hunk est « mien »
si UNE de ses lignes `+`/`-` contient le mot-clé — un mot que seules mes lignes portent (nom du
chantier, clé de champ, date). ⚠ Le mot-clé doit être sur une ligne changée, pas dans le
contexte : avec `-U0` il n'y a pas de contexte, et un mot-clé qui n'apparaît qu'autour rend
0 hunk (vécu le 2026-09-16, « Banc de comparaison » était la ligne au-dessus).

Tout est lu et écrit en OCTETS : `text=True` traduisait les `\\r\\n` en `\\n` et le patch ne
correspondait plus à l'index (vécu le 2026-09-15 : un `apply --cached` antérieur avait fait
entrer des lignes CRLF dans le blob ; le diff suivant les rendait comme « modifiées », et le
patch décodé en texte ne les retrouvait plus). La console Windows n'encode pas tout l'Unicode
des titres (`↔`, `→`) : la sortie écran remplace ce qu'elle ne sait pas afficher.
"""
import pathlib
import subprocess
import sys


def split_hunks(diff: str):
    """(en-tête du fichier, [hunk, ...]) — un hunk = ses lignes, la première commence par @@."""
    header, hunks, current = [], [], None
    for line in diff.splitlines(keepends=True):
        if line.startswith('@@'):
            current = [line]
            hunks.append(current)
        elif current is None:
            header.append(line)
        else:
            current.append(line)
    return header, hunks


def is_mine(hunk, keyword: str) -> bool:
    return any(keyword in line for line in hunk[1:] if line.startswith(('+', '-')))


def build_patch(specs) -> tuple[str, list]:
    """specs = [(fichier, mot-clé), ...] → (patch, rapport de lignes lisibles)."""
    pieces, report = [], []
    for path, keyword in specs:
        raw = subprocess.run(['git', 'diff', '-U0', '--', path], capture_output=True).stdout
        diff = raw.decode('utf-8', errors='surrogateescape')
        header, hunks = split_hunks(diff)
        mine = [h for h in hunks if is_mine(h, keyword)]
        report.append(f"{path}: hunks={len(hunks)} miens={len(mine)} laissés={len(hunks) - len(mine)}")
        report += [f"   MIEN   : {h[0].strip()[:70]}" for h in mine]
        report += [f"   laissé : {h[0].strip()[:70]}" for h in hunks if h not in mine]
        if mine:
            pieces.append(''.join(header) + ''.join(''.join(h) for h in mine))
    return ''.join(pieces), report


def main(argv):
    if len(argv) < 3 or any('=' not in spec for spec in argv[2:]):
        print(__doc__)
        return 2
    sys.stdout.reconfigure(errors='replace')
    out = pathlib.Path(argv[1])
    specs = [tuple(spec.split('=', 1)) for spec in argv[2:]]
    patch, report = build_patch(specs)
    print('\n'.join(report))
    out.write_bytes(patch.encode('utf-8', errors='surrogateescape'))
    print(f"patch -> {out}  ({'VIDE — rien à appliquer' if not patch else 'à appliquer avec git apply --cached --unidiff-zero'})")
    return 0 if patch else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
