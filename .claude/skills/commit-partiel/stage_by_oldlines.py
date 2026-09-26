"""Poser dans l'INDEX le contenu = HEAD + SEULEMENT mes hunks, par numeros de lignes ANCIENS.

Usage (remplace le `git apply --cached --unidiff-zero` de l'etape 1c du skill) :
    python .claude/skills/commit-partiel/stage_my_hunks.py <scratchpad>/mine.patch "<fichier>=<mot-cle>"
    python .claude/skills/commit-partiel/stage_by_oldlines.py <fichier> <scratchpad>/mine.patch
Un fichier par appel. Chaque hunk de REMPLACEMENT est confronte a HEAD avant pose : s'il ne
correspond pas, le script s'arrete et ne touche pas a l'index.

POURQUOI (mesure du 2026-09-26) : `git apply --cached --unidiff-zero` place une INSERTION PURE
d'apres le numero de ligne NOUVEAU du hunk. Si des hunks laisses a autrui la PRECEDENT, ce
numero ne designe plus le meme endroit : 5 lignes de docstring ont atterri au milieu du corps
de la fonction, et le fichier indexe ne compilait plus. Les numeros ANCIENS, eux, referencent
tous le meme fichier (HEAD) : ils ne se decalent pas.
"""
import re, subprocess, sys

path = sys.argv[1]
patch = open(sys.argv[2], 'rb').read()

head = subprocess.run(['git', 'show', f'HEAD:{path}'], capture_output=True).stdout
old = head.split(b'\n')                      # 1-based : old[i-1] = ligne i

hunks, cur = [], None
for line in patch.split(b'\n'):
    if line.startswith(b'@@'):
        m = re.match(rb'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        cur = {'a': int(m.group(1)), 'b': int(m.group(2) or 1), 'lines': []}
        hunks.append(cur)
    elif cur is not None and line[:1] in (b'+', b'-', b' '):
        cur['lines'].append(line)

hunks.sort(key=lambda h: h['a'])
out, pos = [], 0                              # pos = index 0-based dans `old`
for h in hunks:
    anchor = h['a'] if h['b'] == 0 else h['a'] - 1      # insertion APRES a / remplacement DE a
    assert anchor >= pos, f"hunks qui se chevauchent : {h['a']}"
    out += old[pos:anchor]
    removed = [l[1:] for l in h['lines'] if l.startswith(b'-')]
    present = old[anchor:anchor + h['b']]
    assert present == removed, f"hunk -{h['a']} ne correspond pas a HEAD :\n{present}\n{removed}"
    out += [l[1:] for l in h['lines'] if l.startswith(b'+')]
    pos = anchor + h['b']
out += old[pos:]

blob = b'\n'.join(out)
sha = subprocess.run(['git', 'hash-object', '-w', '--stdin'], input=blob,
                     capture_output=True).stdout.decode().strip()
subprocess.run(['git', 'update-index', '--cacheinfo', f'100644,{sha},{path}'], check=True)
print(f"{path} : {len(hunks)} hunks poses par numeros ANCIENS -> blob {sha[:12]}")
