"""
Scénarios `consistency` — les contrôles mécaniques de la base de connaissance, joués
chaque nuit par la charpente nocturne (SEUL ordonnanceur de ces contrôles, §16.9 :
pas de cron concurrent). CPU pur, aucun média, aucun GPU.

S'y ajoute (2026-08-18) le CONTRAT TOOL_API (stage `wired`, §fin de module) : le pivot de
l'assistant éprouvé chaque nuit — versé du banc d'épreuve demandé par Fabien (trou #8 ROUTE
§11, « test de contrat triade », entamé).

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
    # VENV-DÉPENDANT pour les libraries (importlib.metadata) : les wheels Windows ne portent
    # pas les dépendances nvidia-*/triton des wheels Linux → depuis venv_win, 3 faux
    # « périmés » permanents (torch/transformers/vibevoice, §REPRISE 2026-08-13). Le contrôle
    # fait foi depuis WSL2 (= le runtime) ; ailleurs on SKIPPE plutôt qu'un rouge trompeur.
    import platform
    if platform.system() == 'Windows':
        raise SkipScenario("venv-dépendant : fait foi depuis WSL2 (venv_linux), pas venv_win")
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


# ── Contrat TOOL_API (stage 'wired') — versé du banc d'épreuve du 2026-08-18 ─────────────
# Le pivot de l'assistant (`execute_tool` : gating F7 → sanitisation → bornes de choix →
# coercition) est éprouvé chaque nuit. Règles héritées du banc :
#   - les noms se DÉRIVENT (`primary_arg_name`, `schema_for_app`), jamais devinés ;
#   - sondes mutantes sous transaction à ROLLBACK FORCÉ (zéro trace en base) ;
#   - user de test dédié (ctx['user'], jamais id=1) ; AUCUN start_*/translate_text
#     (dispatch Celery/GPU/LLM hôte — hors périmètre 'wired') ;
#   - 'forbidden' = POLITIQUE d'accès du user de test, distingué d'un échec.
# Ce contrat aurait attrapé la nuit même le FieldError de `get_imager_status` (self-FK
# `parent_generation` retiré le 07/08, glu manuelle dérivée du modèle — corrigé le 18/08).


class _RollbackProbe(Exception):
    """Force l'annulation de la transaction d'une sonde mutante (aucune trace en base)."""


def _call_rolled_back(tool, args, user):
    from django.db import transaction
    from wama import tool_api as T
    box = {}
    try:
        with transaction.atomic():
            box['out'] = T.execute_tool(tool, args, user)
            raise _RollbackProbe
    except _RollbackProbe:
        pass
    return box['out'] or {}


def _run_tool_api_inventaire(ctx):
    """Contrat STRUCTUREL du registre — aucun compte en dur (il évolue avec les outils) :
    tout outil décrit, triades complètes (studio excepté : add+start fusionnés dans run,
    voulu), argument principal dérivable pour tout add/start."""
    from wama import tool_api as T
    reg = T.TOOL_REGISTRY
    desc = T.tool_descriptions()
    sans_desc = [n for n in reg
                 if not str((desc.get(n) or {}).get('description', '')).strip()]
    roles = {}
    for n in reg:
        app, role = T.app_id_for_tool(n), T.tool_role(n)
        if app and role in ('add', 'start', 'status'):
            roles.setdefault(app, set()).add(role)
    incomplets = {a: sorted({'add', 'start', 'status'} - r) for a, r in roles.items()
                  if a != 'studio' and r != {'add', 'start', 'status'}}
    sans_arg = [n for n in reg
                if T.tool_role(n) in ('add', 'start') and not T.primary_arg_name(n)]
    problemes = ([f"sans description : {sans_desc}"] if sans_desc else []) \
        + ([f"triades incomplètes : {incomplets}"] if incomplets else []) \
        + ([f"arg principal non dérivable : {sans_arg}"] if sans_arg else [])
    if problemes:
        return False, ' ; '.join(problemes)
    return True, f"{len(reg)} outils décrits, {len(roles)} apps à triade complète"


def _run_tool_api_lectures(ctx):
    """Toutes les LECTURES du registre répondent via la porte réelle (la sonde qui aurait
    attrapé le FieldError imager du 07→18/08). Refus 'forbidden' comptés à part ; s'ils
    couvrent TOUT, on skippe (un vert vide masquerait la classe de bug visée)."""
    from wama import tool_api as T
    user = ctx['user']
    lectures = [n for n in sorted(T.TOOL_REGISTRY) if T.tool_role(n) == 'status']
    lectures += ['list_user_files', 'list_media_assets', 'sam3_examples',
                 'list_ai_models', 'list_studio_pipelines']
    echecs, refus, ok = [], [], 0
    for tool in lectures:
        try:
            out = T.execute_tool(tool, {}, user) or {}
        except Exception as e:      # execute_tool promet de ne jamais lever
            echecs.append(f"{tool} LÈVE {type(e).__name__}: {e}")
            continue
        err = out.get('error')
        if err == 'forbidden':
            refus.append(tool)
        elif err:
            echecs.append(f"{tool}: {str(err)[:90]}")
        else:
            ok += 1
    if echecs:
        return False, ' ; '.join(echecs)
    if refus and not ok:
        raise SkipScenario(f"user de test refusé sur les {len(refus)} lectures — gating à ouvrir")
    note = f" ({len(refus)} refusées au user de test : politique, pas un échec)" if refus else ""
    return True, f"{ok} lectures OK{note}"


def _run_tool_api_garde_fous(ctx):
    """Chemins négatifs de la porte : outil inconnu, gating anonyme, borne de choix
    (paramètre DÉRIVÉ du schéma), garde MEDIA_ROOT — sondes mutantes sous rollback."""
    from django.contrib.auth.models import AnonymousUser
    from wama import tool_api as T
    from wama.common.utils.param_schema import schema_for_app
    user = ctx['user']
    echecs = []

    out = T.execute_tool('outil_inexistant_nightly', {}, user)
    if 'Outil inconnu' not in str(out.get('error', '')):
        echecs.append('outil inconnu non refusé')

    garde = next((n for n in sorted(T.TOOL_REGISTRY)
                  if T.tool_role(n) == 'status' and T.app_id_for_tool(n)), None)
    if garde:
        out = T.execute_tool(garde, {}, AnonymousUser())
        if out.get('error') != 'forbidden':
            echecs.append(f'anonyme non refusé sur {garde}')

    # Les sondes suivantes doivent TRAVERSER la porte : elles se choisissent parmi les
    # outils ACCESSIBLES au user de test (sinon le gating répond avant la borne — 1er run
    # nocturne pris à ce piège : `forbidden` sur add_to_anonymizer diagnostiqué « borne
    # inerte », et le même `forbidden` faisait passer la sonde MEDIA_ROOT en vert).
    from wama.accounts.permissions import tool_accessible
    notes = []

    # Borne de choix : 1er add_* accessible dont un paramètre à choix du schéma figure
    # dans la SURFACE ACCEPTÉE par l'outil (tool_descriptions()['args'] — la vue du
    # mécanisme : signature ∪ schéma si **params ; un paramètre hors surface serait FILTRÉ
    # avant la borne, donc jamais borné — d'où la dérivation par la surface et non par le
    # schéma brut). Refus attendu AVANT exécution (le fichier factice n'est jamais lu).
    # NB : l'échec du 1er run sur add_to_anonymizer.output_quality était le GATING (forbidden
    # avant la borne), pas la surface — vérifié le 18/08 : une fois l'app accessible, la
    # borne refuse bien output_quality hors schéma.
    desc = T.tool_descriptions()
    probe = None
    for n in sorted(T.TOOL_REGISTRY):
        if T.tool_role(n) != 'add' or not tool_accessible(user, n):
            continue
        app = T.app_id_for_tool(n)
        surface = set((desc.get(n) or {}).get('args') or {})
        choix = [p['name'] for p in (schema_for_app(app) if app else [])
                 if p.get('choices') and p['name'] in surface]
        arg = T.primary_arg_name(n)
        if choix and arg:
            probe = (n, arg, choix[0])
            break
    if probe:
        n, arg, param = probe
        out = _call_rolled_back(n, {arg: 'sonde_nightly.tmp', param: 'hors_schema_nightly'}, user)
        if 'hors schéma' not in str(out.get('error', '')):
            echecs.append(f'borne de choix inerte ({n}.{param}) : {str(out)[:90]}')
        else:
            notes.append(f'borne ({n}.{param})')
    else:
        notes.append('borne de choix NON sondée (aucun add_* accessible au user de test)')

    if 'add_to_reader' in T.TOOL_REGISTRY and tool_accessible(user, 'add_to_reader'):
        from wama.reader.models import ReadingItem
        arg = T.primary_arg_name('add_to_reader')
        n0 = ReadingItem.objects.count()
        out = _call_rolled_back('add_to_reader',
                                {arg: '/hors/media_root/sonde_nightly.pdf'}, user)
        if not out.get('error') or out.get('error') == 'forbidden':
            echecs.append(f'garde MEDIA_ROOT douteuse : {str(out)[:90]}')
        elif ReadingItem.objects.count() != n0:
            echecs.append('ligne fuitée par la sonde reader')
        else:
            notes.append('MEDIA_ROOT')
    else:
        notes.append('MEDIA_ROOT NON sondée (reader inaccessible au user de test)')

    if echecs:
        return False, ' ; '.join(echecs)
    return True, 'porte saine — inconnu, gating anonyme, ' + ', '.join(notes)


def _modules_de_test(paquet: str):
    """Modules de test d'un monde, DÉCOUVERTS — jamais énumérés.

    ⚠ POURQUOI CETTE FONCTION EXISTE (mesuré le 2026-08-23). Cet exécuteur nommait **2 modules en
    dur** alors que le monde en comptait **15** : 13 suites ne tournaient donc jamais la nuit, et
    rien ne le signalait. Sa garde — « aucun test chargé, les modules ont-ils été déplacés ? » —
    protégeait contre une DISPARITION, jamais contre une OMISSION : **une liste en dur ne peut
    détecter que sa propre péremption vers le bas.**

    C'est le même anti-patron que `WAMA_DATA_WORLD.md §9quinquies` vient de nommer pour les
    capacités (« ajouter un format = déposer un lecteur, jamais éditer le moteur »). La réponse est
    donc la même : on ne complète pas la liste au fil de l'eau, on supprime le besoin de la tenir.
    Écrire un fichier `tests_*.py` suffit désormais à le faire tourner la nuit.
    """
    import importlib
    import pkgutil

    racine = importlib.import_module(paquet)
    out = []
    for info in pkgutil.walk_packages(racine.__path__, prefix=f'{paquet}.'):
        feuille = info.name.rsplit('.', 1)[-1]
        # `tests_*` est la convention du monde ; `test_*` existe aussi (kinematics) et c'est le
        # motif par défaut de Django — on accepte les deux plutôt que d'en imposer un après coup.
        if feuille.startswith(('tests_', 'test_')):
            out.append(info.name)
    return sorted(out)


def _run_wama_data(ctx):
    """Cœur de WAMA Data : TOUTES ses suites de test, découvertes à chaque passage.

    Pourquoi au stage `consistency` et pas `wired` : ces contrôles sont du **CPU pur**, sans
    modèle ni GPU — ils peuvent donc tourner sans le gate, comme les autres contrôles nocturnes.

    Deux niveaux dans ces modules (cf. leur en-tête) : la logique sur données synthétiques tourne
    partout, les contrôles sur base réelle se SAUTENT quand elle est absente (dossier hors dépôt).
    Un `skipped` non nul est donc NORMAL sur une installation sans corpus — on le rapporte au lieu
    de le taire, sinon on croirait avoir tout couvert.

    ⚠ LE NOMBRE DE MODULES EST RAPPORTÉ, pas seulement le nombre de tests. Sans lui, une suite
    entière qui cesserait d'être découverte (fichier renommé hors convention, paquet sans
    `__init__`) ferait juste baisser un total que personne ne connaît par cœur.
    """
    from django.test.utils import get_runner
    from django.conf import settings

    modules = _modules_de_test('wama_data')
    if not modules:
        return False, ("aucun module de test découvert sous `wama_data` — convention "
                       "`tests_*.py` respectée ? paquet importable ?")

    runner = get_runner(settings)(verbosity=0, interactive=False, keepdb=True)
    suite = runner.test_loader.loadTestsFromNames(modules)
    total = suite.countTestCases()
    if not total:
        return False, (f"{len(modules)} module(s) découvert(s) mais aucun test chargé — "
                       "erreur d'import dans les modules de test ?")

    result = runner.run_suite(suite)
    echecs = len(result.failures) + len(result.errors)
    sautes = len(getattr(result, 'skipped', ()))
    detail = (f"{len(modules)} module(s) découvert(s), {result.testsRun} test(s), "
              f"{echecs} échec(s), {sautes} sauté(s)")
    if echecs:
        premier = (result.failures + result.errors)[0]
        return False, f"{detail} — 1er : {premier[0]}"
    if sautes:
        detail += " (base d'expérimentation absente : contrôles sur volumes réels non joués)"
    return True, detail


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
    register(id='common.consistency.wama_data', app='common', stage='consistency',
             description='Monde WAMA Data : TOUTES ses suites, découvertes à chaque passage '
                         '(CPU pur ; contrôles sur base réelle sautés si le corpus est absent)',
             run=_run_wama_data, timeout_s=600)
    register(id='common.consistency.redundancy', app='common', stage='consistency',
             description='Recopies locales d\'un domicile unique (contrat : ≤5, dette anonymizer)',
             run=_run_redundancy, timeout_s=300)
    register(id='common.consistency.dep_vulns', app='common', stage='consistency',
             description='CVE des paquets installés vs baseline versionnée (OSV.dev — contrat : 0 nouvelle)',
             run=_run_dep_vulns, timeout_s=300)
    register(id='common.consistency.secrets', app='common', stage='consistency',
             description='Fuites de secrets : historique git complet + hook pre-commit (gitleaks)',
             run=_run_secret_leaks, timeout_s=300)
    # ── Contrat tool_api (stage 'wired' : CPU + DB, aucun GPU, sondes sous rollback) ──
    register(id='common.tool_api.inventaire', app='common', stage='wired',
             description='Contrat structurel du pivot assistant (descriptions, triades, args dérivables)',
             run=_run_tool_api_inventaire, timeout_s=60)
    register(id='common.tool_api.lectures', app='common', stage='wired',
             description='Toutes les lectures tool_api répondent via execute_tool (user de test dédié)',
             run=_run_tool_api_lectures, timeout_s=120)
    register(id='common.tool_api.garde_fous', app='common', stage='wired',
             description='Chemins négatifs de la porte : gating, bornes de choix, garde MEDIA_ROOT (rollback)',
             run=_run_tool_api_garde_fous, timeout_s=120)
