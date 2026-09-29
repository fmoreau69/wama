"""
Où vivent les tests — la règle `WAMA_APP_CONVENTIONS §1.1` tenue par un contrôle (2026-09-29).

Au-delà d'une dizaine de fichiers de test, une app les range dans un paquet `tests/` ; et une app
qui a ce paquet n'en remet plus à sa racine. Le 29/09, les 144 tests de `wama/common` y sont passés
(`0db25a8c`) pendant que plusieurs instances avaient l'habitude d'écrire `wama/common/tests_x.py` :
sans garde, le premier test neuf serait revenu à la racine, et la règle n'aurait tenu que de mémoire.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

#: Au-delà, un paquet `tests/`.
MAX_ROOT_TEST_FILES = 10
#: Apps qui dépassent la règle, à déplacer — budget qui ne peut que DESCENDRE (mesuré le 29/09).
PENDING = {
    'wama_lab/cam_analyzer': 20,        # model_manager et media_library rangés le 2026-09-29
}
ROOTS = ('wama', 'wama_lab', 'wama_data')


def _test_folders():
    """Dossier → nombre de `tests*.py` à sa racine, pour tout dossier qui en porte."""
    from wama.common.sandbox import LABEL_RE
    base = Path(settings.BASE_DIR)
    counts = {}
    for root in ROOTS:
        for path in (base / root).rglob('tests*.py'):
            folder = path.parent
            if folder.name == 'tests' or any(p in ('migrations', '__pycache__') for p in folder.parts):
                continue
            rel = folder.relative_to(base)
            if len(rel.parts) > 1 and LABEL_RE.match(rel.parts[1]):
                continue                                   # jumelles du bac à sable, générées
            counts[rel.as_posix()] = counts.get(rel.as_posix(), 0) + 1
    return counts


class TestLayoutTest(SimpleTestCase):

    def test_an_app_with_a_tests_package_keeps_none_at_its_root(self):
        base = Path(settings.BASE_DIR)
        mixed = [f'{folder} ({n})' for folder, n in _test_folders().items()
                 if (base / folder / 'tests' / '__init__.py').exists()]
        self.assertEqual(mixed, [], 'un test neuf va dans le paquet tests/ de son app')

    def test_no_app_grows_past_ten_root_test_files(self):
        over = [f'{folder}: {n}' for folder, n in _test_folders().items()
                if n > PENDING.get(folder, MAX_ROOT_TEST_FILES)]
        self.assertEqual(over, [], 'au-delà d’une dizaine : un paquet tests/ (§1.1)')

    def test_pending_moves_are_still_needed_and_pinned(self):
        counts = _test_folders()
        done = [f for f in PENDING if counts.get(f, 0) <= MAX_ROOT_TEST_FILES]
        self.assertEqual(done, [], 'déplacement fait : retirer l’entrée de PENDING')
        slack = {f: (counts.get(f, 0), n) for f, n in PENDING.items() if counts.get(f, 0) < n}
        self.assertEqual(slack, {}, 'budget à baisser à la mesure (une marge autorise un ajout)')

    def test_the_common_tests_live_in_their_package(self):
        # contre-épreuve de lecture : le paquet est bien vu, et la racine de common est vide
        self.assertNotIn('wama/common', _test_folders())
        self.assertTrue((Path(settings.BASE_DIR) / 'wama/common/tests/__init__.py').exists())
