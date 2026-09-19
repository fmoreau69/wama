# -*- coding: utf-8 -*-
"""
Scénarios nocturnes du stage `suite` — la SUITE DJANGO entre dans la grille fonctionnelle.

Demande de Fabien, 2026-09-19 : *« C'est le résultat des tests qui importe »*, après la mesure qui
a montré le trou : **2769 méthodes de test dans 149 fichiers, invisibles depuis WAMA**. Les 300
scénarios nocturnes couvrent l'UI, les sorties et la cohérence (`ui`, `output`, `consistency`,
`wired`) — aucun ne lançait la suite Django. Son verdict ne vivait que dans un terminal, et le
coût est mesuré : le 19/09, deux échecs préexistants (`AddItemToMediaLibraryTest`,
`tests_doc_plans`) ont dû être élucidés et expliqués à la main dans un handoff, alors qu'un
tableau les aurait datés et attribués.

**Un scénario par label de test**, DÉRIVÉ des apps installées qui ont au moins un fichier
`test*.py` — jamais une liste en dur : « le registre ne connaît jamais ses producteurs »
(AGENTS.md). Le verdict rejoint le même rapport JSON que les autres scénarios, donc la grille
fonctionnelle de `/apps/` l'affiche **sans une ligne de front à écrire**.

⚠⚠ LE CODE DE SORTIE DE `manage.py test` MENT — `reference_test_suite_exit_code_ment` : il sort en
**0 sans avoir rien lancé** (label inconnu, base occupée). Le verdict se lit dans la SORTIE
(`Ran N tests` + `OK` / `FAILED`), jamais dans le code retour. Aucun `Ran` = rien n'a tourné =
`SkipScenario`, pas un succès — un scénario vert qui n'a rien exécuté est pire qu'un rouge.

⭐ MESURE du 19/09, contraire a l'attente : un LABEL ERRONE n'est pas silencieux — Django
fabrique un `_FailedTest` (« Ran 1 test… FAILED (errors=1) »), donc le scenario ROUGIT et nomme le
module. C'est mieux qu'un skip : un module de test qui ne s'importe plus est un vrai defaut. Le
`SkipScenario` reste pour le cas ou RIEN n'a tourne (pas de « Ran N tests » du tout : base de test
occupee par une autre instance, erreur avant collecte).

⚠ `--keepdb` et JAMAIS `--noinput` : la base de test est PARTAGÉE avec les autres instances
(mémoire de session). `--noinput` répondrait « oui » à « détruire la base ? » — il détruirait le
travail d'à côté.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings

from wama.common.services.nightly_tests import SkipScenario, register

#: Temps large : la suite `wama.common` seule prend ~500 s (1368 tests). C'est la nuit.
TIMEOUT_S = 2400
#: Ce que Django écrit en fin de run — les deux seules formes qui valent verdict.
RAN = re.compile(r'^Ran (\d+) tests? in ([\d.]+)s', re.MULTILINE)
VERDICT_OK = re.compile(r'^OK(?: \(.*\))?$', re.MULTILINE)
VERDICT_FAILED = re.compile(r'^FAILED \((.*)\)$', re.MULTILINE)
#: Les rouges NOMMÉS : c'est ce qui rend la grille exploitable (quel test, pas juste combien).
NAMED = re.compile(r'^(?:FAIL|ERROR): (\S+)', re.MULTILINE)


def test_labels() -> list:
    """Labels `manage.py test` des apps installées qui ont au moins un fichier `test*.py`.

    Dérivé, jamais déclaré : une app qui gagne des tests entre d'elle-même dans la grille, et une
    app sans test n'y figure pas en vert trompeur.
    """
    from django.apps import apps as django_apps

    labels = []
    for config in django_apps.get_app_configs():
        folder = Path(config.path)
        try:
            has_tests = any(folder.glob('test*.py')) or any(folder.glob('tests/test*.py'))
        except OSError:
            continue
        # Hors périmètre : les apps TIERCES ont leurs propres suites (lancer celle de
        # `django.contrib.admin` jouerait des milliers de tests de Django).
        # ⚠ Le critère « sous BASE_DIR » ne suffit PAS : les venvs sont DANS le dépôt
        # (`venv_linux/`, `venv_win/`), donc `rest_framework` et `django.contrib.*` y passaient —
        # mesuré au premier dry-run, 22 scénarios dont 4 étrangers. C'est `site-packages` qui
        # sépare, pas la racine.
        parts = set(folder.parts)
        third_party = 'site-packages' in parts or any(p.startswith('venv_') for p in parts)
        if has_tests and not third_party:
            labels.append(config.name)
    return sorted(labels)


def _run_label(label: str):
    """(ok, detail) du lancement de `manage.py test <label>` — la SORTIE fait foi."""
    def run(ctx):
        command = [sys.executable, 'manage.py', 'test', label, '--keepdb']
        try:
            done = subprocess.run(command, cwd=str(settings.BASE_DIR), capture_output=True,
                                  text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return False, f"{label} : dépassé {TIMEOUT_S} s sans rendre son verdict"
        output = f"{done.stdout}\n{done.stderr}"

        ran = RAN.search(output)
        if not ran:
            # Ni « Ran N tests » ni verdict : le runner n'a pas tourné (label vide, base occupée
            # par une autre instance, erreur d'import au chargement). JAMAIS un succès.
            tail = ' / '.join(line.strip() for line in output.strip().splitlines()[-3:])
            raise SkipScenario(f"{label} : aucun test lancé — {tail[:300]}")

        count, seconds = ran.group(1), ran.group(2)
        failed = VERDICT_FAILED.search(output)
        if failed:
            names = NAMED.findall(output)
            detail = f"{label} : {count} tests en {seconds}s → FAILED ({failed.group(1)})"
            if names:
                detail += ' — ' + ', '.join(sorted(set(names))[:8])
            return False, detail
        if VERDICT_OK.search(output):
            return True, f"{label} : {count} tests en {seconds}s → OK"
        # « Ran N tests » sans verdict lisible : on ne conclut pas au vert sur un silence.
        return False, f"{label} : {count} tests lancés, verdict ILLISIBLE dans la sortie"
    return run


def register_scenarios() -> int:
    """Déclare un scénario `suite` par label. Retourne le nombre enregistré."""
    total = 0
    for label in test_labels():
        register(
            id=f"{label}.suite",
            app=label.split('.')[-1],
            description=f"Suite Django de `{label}` — verdict lu dans la SORTIE, jamais au code retour",
            stage='suite',
            run=_run_label(label),
            timeout_s=TIMEOUT_S,
            vram_gb=0.0,        # CPU pur : aucune charge GPU, donc jouable sans `--with-gpu`
        )
        total += 1
    return total
