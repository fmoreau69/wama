"""Restaure un dump de la base dans une base de CONTRÔLE SÉPARÉE — jamais dans la base vivante.

    python <ce fichier> <dump> wama_check_<date>         → crée la base et y restaure le dump
    python <ce fichier> --drop wama_check_<date>         → la supprime (APRÈS accord de Fabien)

Lancé depuis la racine du dépôt, côté WSL (`PYTHONPATH=. venv_linux/bin/python …`).

⚠ JAMAIS `manage.py restore_db` pour VÉRIFIER : il restaure par `--create --clean`, donc SUPPRIME
et recrée la base vivante (`wama_db`). Ici : `createdb` d'une base neuve, puis `pg_restore` sans
`--create` ni `--clean` — rien ne peut être supprimé ; le nom cible doit commencer par
`wama_check_`, n'être ni la base vivante ni une base de test, et ne pas exister déjà.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402

db = settings.DATABASES['default']
env = {**os.environ, 'PGPASSWORD': db['PASSWORD']}
conn = ['-h', db['HOST'], '-p', str(db['PORT']), '-U', db['USER']]


def checked(name: str) -> str:
    assert name.startswith('wama_check_') and name != db['NAME'], f'nom refusé : {name}'
    return name


def exists(name: str) -> bool:
    return bool(subprocess.run(
        ['psql', *conn, '-d', 'postgres', '-tAc',
         f"SELECT 1 FROM pg_database WHERE datname = '{name}'"],
        env=env, capture_output=True, text=True, check=True).stdout.strip())


if sys.argv[1] == '--drop':
    target = checked(sys.argv[2])
    if not exists(target):
        sys.exit(f'{target} n’existe pas — rien à faire')
    subprocess.run(['dropdb', *conn, target], env=env, check=True)
    print('supprimée :', target, '| la base vivante reste :', exists(db['NAME']))
    sys.exit(0)

dump, target = sys.argv[1], checked(sys.argv[2])
if exists(target):
    sys.exit(f'{target} existe déjà — choisir un autre nom (rien fait)')
subprocess.run(['createdb', *conn, target], env=env, check=True)
proc = subprocess.run(['pg_restore', '--no-owner', '--no-acl', *conn, '-d', target, dump],
                      env=env, capture_output=True, text=True)
print('pg_restore exit', proc.returncode)
print(proc.stderr[-1500:])
