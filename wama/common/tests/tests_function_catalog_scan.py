"""`function_catalog.load_all` balaie les modules déclarants UNE fois pour un même ensemble d'apps.

Mesuré le 2026-10-18 : appelé une fois par nœud fonction pour servir les réglages du Studio (142
fois), il relançait à chaque appel la recherche des modules déclarants ABSENTS — le cas normal, qu'
`import_module` ne met pas en cache — : 9 697 `stat` sur `/mnt/d`, 7,9 s sur les 8,6 s de la route.
Le balayage est désormais mémorisé ; l'actualisation du registre `functions` le refait
(`rescan=True`) pour trouver un module déclarant créé à chaud.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.catalog import function_catalog as fc


class TheDeclarantScanRunsOncePerAppSetTest(SimpleTestCase):

    def _imports_during(self, **kwargs):
        with mock.patch('importlib.import_module', wraps=__import__('importlib').import_module) as imp:
            fc.load_all(**kwargs)
        return imp.call_count

    def test_a_second_call_searches_nothing_again(self):
        fc.load_all()
        self.assertEqual(0, self._imports_during())

    def test_a_rescan_searches_every_declarant_again(self):
        """Contre-épreuve : le balayage forcé, celui de l'actualisation du registre, cherche
        de nouveau chaque module déclarant de chaque app installée."""
        from django.apps import apps
        fc.load_all()
        expected = len(list(apps.get_app_configs())) * len(fc.MODULES_DECLARANTS)
        self.assertEqual(expected, self._imports_during(rescan=True))
