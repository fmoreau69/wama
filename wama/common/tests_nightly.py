"""Tests de la charpente nocturne — la DÉCOUVERTE des suites d'un monde.

⚠ POURQUOI CE FICHIER (mesuré le 2026-08-23). `_run_wama_data` nommait **2 modules en dur** alors
que le monde en comptait **15** : 13 suites ne tournaient jamais la nuit, et rien ne le signalait.
Sa garde — « aucun test chargé, les modules ont-ils été déplacés ? » — protégeait contre une
DISPARITION, jamais contre une OMISSION.

Le correctif (découvrir au lieu d'énumérer) crée à son tour un mode de panne qu'il faut garder :
`pkgutil.walk_packages` **ne descend pas dans un répertoire sans `__init__.py`**. Une suite entière
pourrait donc cesser d'être découverte sans qu'aucun test n'échoue — seul le total baisserait, et
personne ne connaît un total par cœur. D'où le contrôle central ci-dessous : **ce qui est découvert
doit égaler ce qui est sur le disque.**
"""
import unittest
from pathlib import Path

from django.conf import settings

from .nightly_scenarios import _modules_de_test


def _fichiers_de_test(racine: Path):
    """Les fichiers de test réellement présents, vus depuis le SYSTÈME DE FICHIERS.

    Volontairement indépendant de `pkgutil` : un contrôle qui emprunterait le même chemin que ce
    qu'il vérifie ne pourrait rien attraper.
    """
    return sorted(p for p in racine.rglob('*.py')
                  if p.name.startswith(('tests_', 'test_'))
                  and '__pycache__' not in p.parts)


class DecouverteTest(unittest.TestCase):

    RACINE = Path(settings.BASE_DIR) / 'wama_data'

    def test_la_decouverte_egale_le_disque(self):
        """⚠ LE test de ce fichier — il attrape le paquet sans `__init__.py`."""
        decouverts = _modules_de_test('wama_data')
        sur_disque = _fichiers_de_test(self.RACINE)
        self.assertEqual(
            len(decouverts), len(sur_disque),
            f"{len(sur_disque)} fichier(s) de test sur le disque mais {len(decouverts)} "
            f"module(s) découvert(s) — un répertoire sans __init__.py ? "
            f"disque={[p.name for p in sur_disque]} découverts={decouverts}")

    def test_les_deux_conventions_de_nommage_sont_acceptees(self):
        # `tests_*` est la convention du monde Data ; `test_*` existe aussi (kinematics) et c'est
        # le motif par défaut de Django. En imposer un après coup ferait disparaître l'autre.
        decouverts = _modules_de_test('wama_data')
        self.assertTrue(any(m.rsplit('.', 1)[-1].startswith('tests_') for m in decouverts))
        self.assertTrue(any(m.rsplit('.', 1)[-1].startswith('test_') and
                            not m.rsplit('.', 1)[-1].startswith('tests_') for m in decouverts))

    def test_les_suites_de_la_RACINE_du_monde_sont_vues(self):
        # `tests_frames.py`, `tests_vue.py` et `tests_registres.py` vivent à la racine de
        # `wama_data/`, pas sous `core/` ni `functions/`. C'est exactement le cas qu'une liste
        # écrite pour `core.*` et `sources.*` avait manqué.
        decouverts = set(_modules_de_test('wama_data'))
        for attendu in ('wama_data.tests_frames', 'wama_data.tests_vue',
                        'wama_data.tests_registres'):
            self.assertIn(attendu, decouverts)

    def test_aucun_doublon(self):
        decouverts = _modules_de_test('wama_data')
        self.assertEqual(len(decouverts), len(set(decouverts)))

    def test_un_paquet_sans_module_de_test_rend_une_liste_vide_sans_lever(self):
        # Le scénario distingue « rien découvert » de « découvert mais rien chargé » : les deux
        # messages sont différents, et celui-ci ne doit pas être une exception.
        self.assertEqual(_modules_de_test('wama.common.catalog'), [])


if __name__ == '__main__':
    unittest.main()
