"""Intégrité STRUCTURELLE de la base vivante. LECTURE SEULE (forcée).

    python <ce fichier>

Lancé depuis la racine du dépôt, côté WSL. Index invalides, contraintes non validées, et chaque
clé étrangère revérifiée à la main (une orpheline existe si une contrainte a été supprimée ou
posée NOT VALID). Compléter par `manage.py migrate --check` (aucune migration en attente).
"""
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402

django.setup()
import psycopg  # noqa: E402
from django.conf import settings  # noqa: E402

db = settings.DATABASES['default']
live = psycopg.connect(host=db['HOST'], port=db['PORT'], user=db['USER'], password=db['PASSWORD'],
                       dbname=db['NAME'], options='-c default_transaction_read_only=on')
print('lecture seule :', live.execute('SHOW default_transaction_read_only').fetchone()[0])
print('index invalides :', live.execute(
    'SELECT indexrelid::regclass::text FROM pg_index WHERE NOT indisvalid OR NOT indisready').fetchall())
print('contraintes NOT VALID :', live.execute(
    "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE NOT convalidated").fetchall())
fks = live.execute("""
    SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, af.attname
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = c.confkey[1]
    WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1""").fetchall()
orphans = []
for table, col, ref, refcol in fks:
    n = live.execute(f'SELECT count(*) FROM {table} t WHERE t."{col}" IS NOT NULL AND NOT EXISTS '
                     f'(SELECT 1 FROM {ref} r WHERE r."{refcol}" = t."{col}")').fetchone()[0]
    if n:
        orphans.append((table, col, ref, n))
print('clés étrangères vérifiées :', len(fks), '| orphelines :', orphans)
