"""
Scénarios `consistency` — les contrôles mécaniques de la base de connaissance, joués
chaque nuit par la charpente nocturne (SEUL ordonnanceur de ces contrôles, §16.9 :
pas de cron concurrent). CPU pur, aucun média, aucun GPU.

Ce module n'implémente AUCUN contrôle : il joue les commandes existantes (check_docs,
check_app_conformity, manifest_export --check, manifest_roundtrip, doc_facts --check,
check_redundancy) et traduit leur verdict en (ok, detail). Les seuils de tolérance sont
les CONTRATS DOCUMENTÉS du projet, pas des choix locaux :
  - check_docs : 3 CASSÉ assumés (cibles à créer, REPRISE §3a) — une 4ᵉ = dérive ;
  - check_redundancy : 5 trouvailles = dette du port anonymizer (ROADMAP §16.9 ②) —
    une 6ᵉ = nouvelle recopie. Ces seuils DÉCROISSENT avec les chantiers ; les baisser
    ici quand les docs de référence actent le nouveau contrat.
"""
import re
from io import StringIO

from wama.common.services.nightly_tests import register

CASSE_ASSUMES = 3        # contrat REPRISE §3a (cibles à créer)
REDONDANCES_ASSUMEES = 5  # contrat ROADMAP §16.9 ② (dette du port anonymizer)


def _capture(cmd, *args, **opts):
    """(code, sortie) d'une management command — SystemExit(1) = verdict, pas un crash."""
    from django.core.management import call_command
    out = StringIO()
    try:
        call_command(cmd, *args, stdout=out, stderr=out, **opts)
        return 0, out.getvalue()
    except SystemExit as e:
        return int(e.code or 0), out.getvalue()


def _run_check_docs(ctx):
    _, out = _capture('check_docs')
    m = re.search(r"Bilan : (\d+) cassée\(s\), (\d+) périmée\(s\)", out)
    if not m:
        return False, "sortie de check_docs illisible (pas de Bilan)"
    casse, perime = int(m.group(1)), int(m.group(2))
    ok = casse <= CASSE_ASSUMES and perime == 0
    return ok, f"{casse} cassée(s) (contrat : ≤{CASSE_ASSUMES}), {perime} périmée(s)"


def _run_conformity(ctx):
    _, out = _capture('check_app_conformity')
    apps = re.findall(r"^([A-Z_]+) — .*→ (\d+) %", out, re.M)
    if not apps:
        return False, "sortie de check_app_conformity illisible"
    return True, "mesure rafraîchie : " + ", ".join(f"{a.lower()} {p}%" for a, p in apps)


def _run_manifest_corpus(ctx):
    code, out = _capture('manifest_export', '--check')
    derniere = (out.strip().splitlines() or ["?"])[-1]
    return code == 0, derniere


def _run_manifest_roundtrip(ctx):
    from wama.common.app_registry import APP_CATALOG
    from wama.common.management.commands.manifest_roundtrip import Command as Roundtrip
    rt, echecs = Roundtrip(), []
    for app_id in sorted(APP_CATALOG):
        r = rt._roundtrip(app_id)
        if r.get('erreur') or r.get('erreurs_validation') or r.get('ecarts_fidelite'):
            echecs.append(app_id)
    if echecs:
        return False, f"validation/fidélité en échec : {', '.join(echecs)}"
    return True, f"{len(APP_CATALOG)} apps : extraction fidèle et validée"


def _run_doc_facts(ctx):
    code, out = _capture('doc_facts', '--check')
    return code == 0, ("blocs de faits à jour" if code == 0
                       else (out.strip().splitlines() or ["?"])[-1])


def _run_redundancy(ctx):
    _, out = _capture('check_redundancy')
    if 'Aucune recopie' in out:
        return True, "aucune recopie"
    m = re.search(r"Bilan : (\d+) trouvaille", out)
    if not m:
        return False, "sortie de check_redundancy illisible"
    n = int(m.group(1))
    return n <= REDONDANCES_ASSUMEES, f"{n} trouvaille(s) (contrat : ≤{REDONDANCES_ASSUMEES})"


def register_scenarios():
    # check_docs parcourt l'arborescence : minutes depuis WSL2 (/mnt/d), secondes depuis
    # Windows — d'où le timeout large. Les autres tiennent en secondes.
    register(id='common.consistency.docs', app='common', stage='consistency',
             description='Références doc→code (contrat : 3 CASSÉ assumés, 0 périmée)',
             run=_run_check_docs, timeout_s=900)
    register(id='common.consistency.conformity', app='common', stage='consistency',
             description='Grille de conformité mesurée (rafraîchit logs/conformity_report.json)',
             run=_run_conformity, timeout_s=300)
    register(id='common.consistency.manifest_corpus', app='common', stage='consistency',
             description='Corpus de manifestes à jour (manifest_export --check)',
             run=_run_manifest_corpus, timeout_s=120)
    register(id='common.consistency.manifest_roundtrip', app='common', stage='consistency',
             description='Round-trip manifestes : validation + fidélité extract→verify',
             run=_run_manifest_roundtrip, timeout_s=300)
    register(id='common.consistency.doc_facts', app='common', stage='consistency',
             description='Couche factuelle des .md à jour (doc_facts --check)',
             run=_run_doc_facts, timeout_s=300)
    register(id='common.consistency.redundancy', app='common', stage='consistency',
             description='Recopies locales d\'un domicile unique (contrat : ≤5, dette anonymizer)',
             run=_run_redundancy, timeout_s=300)
