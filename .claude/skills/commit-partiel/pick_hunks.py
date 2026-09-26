"""Extraire d'un `git diff -U0` les hunks dont la ligne ANCIENNE de depart est listee.

Complement de stage_my_hunks.py : quand mes hunks n'ont aucun mot-cle commun (ici une ligne de
prose modifiee qui ne partage aucun terme avec les autres), la selection par NUMERO est plus
sure qu'un mot-cle trop large -- a condition d'avoir LU chaque hunk d'abord, ce qui est fait.
"""
import re
import subprocess
import sys

sys.stdout.reconfigure(errors='replace')   # la console Windows n'encode pas tout l'Unicode
path, out = sys.argv[1], sys.argv[2]
wanted = {int(n) for n in sys.argv[3:]}

raw = subprocess.run(['git', 'diff', '-U0', '--', path], capture_output=True).stdout
header, hunks, cur = [], [], None
for line in raw.split(b'\n'):
    if line.startswith(b'@@'):
        cur = [line]
        hunks.append(cur)
    elif cur is None:
        header.append(line)
    else:
        cur.append(line)

kept = []
for h in hunks:
    start = int(re.match(rb'@@ -(\d+)', h[0]).group(1))
    (kept if start in wanted else []).append(h)
    print(('RETENU  ' if start in wanted else 'laisse  ') + h[0].decode('utf-8', 'replace')[:72])

assert len(kept) == len(wanted), f'{len(kept)} hunks retenus pour {len(wanted)} demandes'
body = b'\n'.join(header) + b'\n' + b'\n'.join(b'\n'.join(h) for h in kept) + b'\n'
open(out, 'wb').write(body)
print(f'{len(kept)} hunks -> {out}')
