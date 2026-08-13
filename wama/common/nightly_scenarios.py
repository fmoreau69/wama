"""
Scénarios `consistency` — les contrôles mécaniques de la base de connaissance, joués
chaque nuit par la charpente nocturne (SEUL ordonnanceur de ces contrôles, §16.9 :
pas de cron concurrent). CPU pur, aucun média, aucun GPU.

Ce module n'implémente AUCUN contrôle : il joue les commandes existantes (check_docs,
check_app_conformity, manifest_export --check, manifest_roundtrip, doc_facts --check,
check_redundancy, check_dep_vulns, check_secret_leaks) et traduit leur verdict en
(ok, detail). Les seuils de tolérance sont
les CONTRATS DOCUMENTÉS du projet, pas des choix locaux :
  - check_docs : 2 CASSÉ assumés (cibles à créer, REPRISE §3a) — une 3ᵉ = dérive ;
  - check_redundancy : 5 trouvailles = dette du port anonymizer (ROADMAP §16.9 ②) —
    une 6ᵉ = nouvelle recopie. Ces seuils DÉCROISSENT avec les chantiers ; les baisser
    ici quand les docs de référence actent le nouveau contrat.
"""
import re
from io import StringIO

from wama.common.services.nightly_tests import SkipScenario, register

# Références EN AVANT assumées : des fichiers que la doc annonce et qui restent à créer.
# 3 → 2 le 2026-08-10 : `_settings_modal.html` est sorti de la liste, la modale ayant été
# LIVRÉE AUTREMENT le 06/08 (générée par `WamaParams.settingsModal()`, le partial n'a donc
# jamais existé) et sa référence retirée des docs. Restent `common/_result_tabs.html`
# (REMOVAL_LEDGER R18 — duplication vérifiée présente le 10/08) et `wama/common/middleware.py`
# (i18n, ROADMAP). Le test compare en `<=` : laisser 3 ne cassait rien mais rendait le contrat
# AVEUGLE à une vraie 3ᵉ dérive. Conformément à l'en-tête de ce module, le seuil DÉCROÎT dès
# qu'une cible est créée ou abandonnée — sinon il cesse silencieusement de protéger.
CASSE_ASSUMES = 2        # contrat REPRISE §3a (cibles à créer)
REDONDANCES_ASSUMEES = 0  # dette anonymizer résorbée au palier 1 du port (03/08) — toute trouvaille = nouvelle recopie


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


def _run_dep_vulns(ctx):
    # Les deux commandes sécurité utilisent le code 3 = « dépendance d'outillage/réseau
    # absente » → SKIP (ni succès ni échec), jamais un rouge trompeur.
    code, out = _capture('check_dep_vulns')
    derniere = (out.strip().splitlines() or ["?"])[-1]
    if code == 3:
        raise SkipScenario(derniere)
    return code == 0, derniere


def _run_secret_leaks(ctx):
    code, out = _capture('check_secret_leaks')
    derniere = (out.strip().splitlines() or ["?"])[-1]
    if code == 3:
        raise SkipScenario(derniere)
    return code == 0, derniere


def register_scenarios():
    # check_docs parcourt l'arborescence : minutes depuis WSL2 (/mnt/d), secondes depuis
    # Windows — d'où le timeout large. Les autres tiennent en secondes.
    register(id='common.consistency.docs', app='common', stage='consistency',
             description='Références doc→code (contrat : 2 CASSÉ assumés, 0 périmée)',
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
    register(id='common.consistency.dep_vulns', app='common', stage='consistency',
             description='CVE des paquets installés vs baseline versionnée (OSV.dev — contrat : 0 nouvelle)',
             run=_run_dep_vulns, timeout_s=300)
    register(id='common.consistency.secrets', app='common', stage='consistency',
             description='Fuites de secrets : historique git complet + hook pre-commit (gitleaks)',
             run=_run_secret_leaks, timeout_s=300)
