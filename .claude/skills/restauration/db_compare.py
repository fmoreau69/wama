"""Compare la base VIVANTE à la base de contrôle restaurée d'un dump. LECTURE SEULE (forcée).

    python <ce fichier> wama_check_<date> <rapport.json>

Lancé depuis la racine du dépôt, côté WSL. Par table : lignes alors / maintenant, et pour une clé
primaire à une colonne, les lignes du dump DISPARUES depuis (le signal de perte) et celles
ajoutées. Une disparition s'explique ensuite ligne par ligne (purge de visiteurs, témoins du
nocturne, retrait d'une card…) avant de conclure à une perte.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django  # noqa: E402

django.setup()
import psycopg  # noqa: E402
from django.conf import settings  # noqa: E402

db = settings.DATABASES['default']
check, out = sys.argv[1], sys.argv[2]
assert check.startswith('wama_check_'), check


def connect(name):
    return psycopg.connect(host=db['HOST'], port=db['PORT'], user=db['USER'], password=db['PASSWORD'],
                           dbname=name, options='-c default_transaction_read_only=on')


live, then = connect(db['NAME']), connect(check)


def tables(conn):
    return {r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()}


def pk_column(conn, table):
    rows = conn.execute("""
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary""", (f'"{table}"',)).fetchall()
    return rows[0][0] if len(rows) == 1 else None


report = {'only_then': sorted(tables(then) - tables(live)),
          'only_now': sorted(tables(live) - tables(then)), 'tables': {}}
for table in sorted(tables(then) & tables(live)):
    count = f'SELECT count(*) FROM "{table}"'
    entry = {'then': then.execute(count).fetchone()[0], 'now': live.execute(count).fetchone()[0]}
    pk = pk_column(then, table)
    if pk and entry['then'] <= 3_000_000:
        ids_then = {r[0] for r in then.execute(f'SELECT "{pk}" FROM "{table}"')}
        ids_now = {r[0] for r in live.execute(f'SELECT "{pk}" FROM "{table}"')}
        gone = ids_then - ids_now
        entry.update(gone=len(gone), added=len(ids_now - ids_then),
                     gone_sample=sorted(map(str, gone))[:15])
    report['tables'][table] = entry

with open(out, 'w', encoding='utf-8', newline='\n') as fh:
    json.dump(report, fh, ensure_ascii=False, indent=1)
print('tables comparées :', len(report['tables']), '| seulement dans le dump :', report['only_then'],
      '| seulement maintenant :', report['only_now'])
for table, e in report['tables'].items():
    if e.get('gone') or e['now'] < e['then']:
        print(f"{table:55s} alors={e['then']:8d} maintenant={e['now']:8d} disparues={e.get('gone')} "
              f"ajoutées={e.get('added')} exemples={e.get('gone_sample')}")
