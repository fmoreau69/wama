"""Pose dans l'index (GIT_INDEX_FILE de l'appelant) le blob de HEAD où UNE seule ligne, repérée par
son préfixe, prend la valeur de l'arbre de travail — pour une doc générée qui porte aussi le travail
d'autrui dans d'autres lignes (et parfois dans la ligne voisine du même hunk). Échoue si le préfixe
n'est pas unique des deux côtés, ou si la ligne n'a pas changé."""
import subprocess
import sys

path, prefix = sys.argv[1], sys.argv[2].encode('utf-8')
head = subprocess.run(['git', 'show', 'HEAD:' + path], capture_output=True, check=True).stdout
tree = open(path, 'rb').read()


def lines(b):
    return b.split(b'\n')


h, t = lines(head), lines(tree)
hi = [i for i, l in enumerate(h) if l.startswith(prefix)]
ti = [l for l in t if l.startswith(prefix)]
assert len(hi) == 1 and len(ti) == 1, (path, len(hi), len(ti))
new = ti[0]
if h[hi[0]].endswith(b'\r') and not new.endswith(b'\r'):
    new += b'\r'
assert h[hi[0]].rstrip(b'\r') != new.rstrip(b'\r'), 'ligne inchangée'
h[hi[0]] = new
blob = subprocess.run(['git', 'hash-object', '-w', '--stdin'], input=b'\n'.join(h),
                      capture_output=True, check=True).stdout.decode().strip()
mode = subprocess.run(['git', 'ls-files', '-s', '--', path], capture_output=True,
                      check=True).stdout.decode().split()[0]
subprocess.run(['git', 'update-index', '--cacheinfo', f'{mode},{blob},{path}'], check=True)
print(f'{path} : ligne {hi[0] + 1} posée -> blob {blob[:12]}')
