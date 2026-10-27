"""Garde-fou PROCESSUS : aucun `shutil.rmtree` ne peut effacer `media/` en bloc.

POURQUOI (2026-10-27, perte de TOUS les médias des utilisateurs)
    Un test (`SurfaceLayoutTest`) empruntait le `setUp` d'une autre classe sans son
    `override_settings(MEDIA_ROOT=…)` ; ce `setUp` programmait `addCleanup(shutil.rmtree,
    settings.MEDIA_ROOT)`. Lancé HORS du lanceur de tests — un script de contre-épreuve qui fait
    `django.setup()` sur les vrais réglages —, `MEDIA_ROOT` désignait le vrai `media/` : effacé à
    16:34, restauré depuis la sauvegarde du NAS. Les fichiers créés depuis la sauvegarde de 02:30
    sont perdus.

    La redirection du lanceur (`runners.WamaTestRunner`) et la garde par AST
    (`tests_media_tests_hygiene`) ne voient pas un script ; ce garde-fou, lui, vit dans TOUT
    processus qui a chargé Django : gunicorn, Celery, commandes, scripts `django.setup()`, tests.

CE QUI EST REFUSÉ
    `shutil.rmtree` d'un dossier qui EST la racine des médias, qui est l'un des domiciles des
    données réelles (`users/`, `media_library/`, `MEDIA_STORAGE_TIERING`), ou qui CONTIENT la
    racine (le dépôt, `D:/WAMA`…). Les autres dossiers de premier niveau restent effaçables :
    les smokes y montent des dossiers jetables (`smoke_preview_*`) qu'ils retirent. La racine
    est celle des RÉGLAGES au démarrage, avant toute redirection de test : la garde protège le
    vrai `media/` même quand `settings.MEDIA_ROOT` pointe ailleurs.
    Le reste est permis : un dossier d'utilisateur (`users/<id>/`, purge des visiteurs), un
    dossier de travail, un dossier de test.

    Le refus LÈVE `PermissionError` avant tout effacement — `ignore_errors=True` ne l'avale donc
    pas — et l'écrit au journal en ERREUR, pour qu'un appelant qui l'attrape laisse une trace.

ET LA CAUSE : UN TEST DE DJANGO HORS DU LANCEUR WAMA (même soir, 21:30)
    La règle écrite (`AGENTS.md`) n'a pas tenu trois heures : une contre-épreuve a de nouveau
    joué des tests par `unittest.TextTestRunner`. Et le nocturne le faisait chaque nuit
    (`nightly_scenarios._run_wama_data`, `run_suite` en processus). Le lanceur
    (`runners.WamaTestRunner`) est le seul à rediriger `MEDIA_ROOT` et à monter la base de TEST,
    et `manage.py test` le seul processus dont le cache et le broker Celery restent en mémoire
    (`runtime_side`) : une suite (avant ses `setUpClass`) ou un test (avant son `setUp`) de
    Django refuse donc de démarrer hors de `manage.py test`, tant que `MEDIA_ROOT` désigne les
    vrais médias, ou — s'il déclare des bases — tant que la base est la vraie (lue au
    démarrage). Un test `unittest` sans Django (le moteur de WAMA Data) reste libre. Sous le
    lanceur, ces conditions sont fausses dès le départ : la garde ne coûte qu'une comparaison.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
import unittest
from pathlib import Path

logger = logging.getLogger(__name__)

#: Racines protégées, résolues au démarrage (`install`).
_PROTECTED: list[Path] = []

#: Nom de la base RÉELLE, lu au démarrage (`install`) — avant que le lanceur la remplace.
_REAL_DATABASES: list[str] = []

#: Les domiciles des données RÉELLES sous la racine — jamais effacés en bloc. Leur FORME vit dans
#: `media_paths` (`app_media_dir` : `users/<id>/<app>/…`, tous mondes ; `SYSTEM_ASSET_ROOT`) :
#: déplacer un domicile, c'est aussi le déclarer ici.
DATA_HOMES = ('users', 'media_library')


def _resolve(path) -> Path | None:
    try:
        return Path(os.fspath(path)).resolve()
    except (TypeError, OSError, ValueError):
        return None


def refusal(path, roots=None) -> str:
    """La raison de refuser d'effacer `path` en bloc, ou '' s'il peut l'être."""
    target = _resolve(path)
    if target is None:
        return ''
    for root in (_PROTECTED if roots is None else roots):
        if target == root:
            return f'{target} est la racine des médias'
        if target.parent == root and target.name in DATA_HOMES:
            return f'{target} est un domicile des données réelles ({root})'
        if target in root.parents:
            return f'{target} contient la racine des médias ({root})'
    return ''


def test_refusal(test, media_root, database: str, test_process: bool = True) -> str:
    """La raison de refuser de JOUER `test` maintenant, ou '' : un test de Django (`SimpleTestCase`)
    dans un processus qui n'est pas `manage.py test` (`test_process`), alors que `media_root`
    désigne les vrais médias, ou qu'il déclare des bases (`databases`) et que `database` est la
    vraie. Un test `unittest` sans Django n'est jamais refusé.

    Pourquoi `manage.py test` et lui seul : le cache et le broker Celery se décident AU CHARGEMENT
    des réglages, sur la ligne de commande (`runtime_side.running_tests`). Un script qui monte le
    lanceur par `get_runner(settings)` isole les médias et la base, pas eux — ses tâches iraient aux
    vrais workers avec des identifiants de la base de test, que le worker lirait dans la vraie."""
    testcases = sys.modules.get('django.test.testcases')
    if testcases is None or not isinstance(test, testcases.SimpleTestCase):
        return ''
    if not test_process:
        return ("ce processus n'est pas `manage.py test` : son cache et ses tâches Celery vont aux "
                "vrais (`runtime_side`)")
    where = refusal(media_root)
    if where:
        return f'MEDIA_ROOT désigne les vrais médias ({where})'
    if getattr(test, 'databases', None) and database in _REAL_DATABASES:
        return f'la base « {database} » est la vraie, pas une base de test'
    return ''


def _danger():
    """`(media_root, database, test_process)` quand le processus n'est pas `manage.py test`, ou
    pointe sur les vrais médias ou la vraie base, sinon None — sous le lanceur WAMA, c'est None."""
    from django.conf import settings
    from django.db import connections
    media_root = settings.MEDIA_ROOT
    database = str(connections['default'].settings_dict.get('NAME', ''))
    test_process = bool(getattr(settings, 'WAMA_RUNNING_TESTS', False))
    if not test_process or refusal(media_root) or database in _REAL_DATABASES:
        return media_root, database, test_process
    return None


def _tests_of(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from _tests_of(test)
        else:
            yield test


def _refuse_outside_the_runner(tests) -> None:
    danger = _danger()
    if danger is None:
        return
    for test in tests:
        reason = test_refusal(test, *danger)
        if reason:
            logger.error('[media_guard] test REFUSÉ hors du lanceur WAMA : %s — %s',
                         test.id(), reason, stack_info=True)
            raise PermissionError(
                f'[media_guard] {test.id()} refusé : {reason}. Un test de Django ne tourne que '
                f'par `manage.py test` (AGENTS.md).')


def _install_test_guard() -> None:
    """Enveloppe `unittest.TestSuite.run` et `unittest.TestCase.run` (`test_refusal`)."""
    if getattr(unittest.TestSuite.run, 'wama_media_guard', False):
        return
    suite_run, case_run = unittest.TestSuite.run, unittest.TestCase.run

    def guarded_suite_run(self, result, debug=False):
        _refuse_outside_the_runner(_tests_of(self))
        return suite_run(self, result, debug)

    def guarded_case_run(self, result=None):
        _refuse_outside_the_runner([self])
        return case_run(self, result)

    for guarded, original in ((guarded_suite_run, suite_run), (guarded_case_run, case_run)):
        guarded.wama_media_guard = True
        guarded.original = original
    unittest.TestSuite.run = guarded_suite_run
    unittest.TestCase.run = guarded_case_run


def install(media_root, database: str = '') -> bool:
    """Protège `media_root` (et la base `database`) dans ce processus. Idempotent ; rend True si
    la garde est en place."""
    root = _resolve(media_root)
    if root is None:
        return False
    if root not in _PROTECTED:
        _PROTECTED.append(root)
    if database and database not in _REAL_DATABASES:
        _REAL_DATABASES.append(str(database))
    _install_test_guard()
    if getattr(shutil.rmtree, 'wama_media_guard', False):
        return True
    original = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        reason = refusal(path)
        if reason:
            logger.error('[media_guard] effacement REFUSÉ : %s', reason, stack_info=True)
            raise PermissionError(f'[media_guard] effacement refusé : {reason}')
        return original(path, *args, **kwargs)

    guarded_rmtree.wama_media_guard = True
    guarded_rmtree.original = original
    guarded_rmtree.avoids_symlink_attacks = getattr(original, 'avoids_symlink_attacks', False)
    shutil.rmtree = guarded_rmtree
    return True
