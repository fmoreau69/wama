# -*- coding: utf-8 -*-
"""
Le stage `suite` lit le verdict de `manage.py test` dans sa SORTIE, jamais dans son code retour.

⚠⚠ C'est tout l'enjeu de ces tests : `manage.py test` **sort en 0 sans avoir rien lancé**
(`reference_test_suite_exit_code_ment`). Un scénario qui se fierait au code retour serait VERT
sur une base occupée ou un label vide — et un vert qui n'a rien exécuté est pire qu'un rouge, il
éteint la surveillance en silence.

Noms de tests en ANGLAIS : décision de Fabien du 2026-09-19 (« on bascule tout le code y compris
les tests en anglais »). Le style « phrase qui énonce un comportement » est conservé.
"""
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from wama.common.nightly_suite import _run_label, test_labels
from wama.common.services.nightly_tests import SkipScenario


def _process(stdout: str, returncode: int = 0):
    """Un faux `CompletedProcess` — c'est la SORTIE qui doit décider, pas `returncode`."""
    return type('Done', (), {'stdout': stdout, 'stderr': '', 'returncode': returncode})()


class NightlySuiteVerdictTest(SimpleTestCase):

    def _verdict(self, stdout, returncode=0):
        with patch('wama.common.nightly_suite.subprocess.run',
                   return_value=_process(stdout, returncode)):
            return _run_label('wama.demo')({})

    def test_a_green_run_is_read_from_the_output(self):
        ok, detail = self._verdict("Ran 42 tests in 3.500s\n\nOK\n")
        self.assertTrue(ok)
        self.assertIn('42 tests', detail)

    def test_a_failure_names_the_guilty_tests(self):
        """La grille doit dire QUEL test est rouge, pas seulement combien : sans les noms, il
        faut relancer la suite à la main pour savoir quoi regarder."""
        ok, detail = self._verdict(
            "FAIL: test_le_role_est_declare (wama.x.tests.RoleTest.test_le_role_est_declare)\n"
            "ERROR: test_autre (wama.x.tests.AutreTest.test_autre)\n"
            "Ran 120 tests in 88.000s\n\nFAILED (failures=1, errors=1)\n")
        self.assertFalse(ok)
        self.assertIn('FAILED (failures=1, errors=1)', detail)
        self.assertIn('test_le_role_est_declare', detail)
        self.assertIn('test_autre', detail)

    def test_a_zero_exit_code_does_NOT_make_a_success(self):
        """Le cas qui justifie ce module : code retour 0, et pourtant la suite a ÉCHOUÉ."""
        ok, _ = self._verdict("Ran 10 tests in 1.000s\n\nFAILED (failures=3)\n", returncode=0)
        self.assertFalse(ok)

    def test_nothing_ran_is_SKIPPED_never_green(self):
        """Base de test occupée par une autre instance, erreur avant collecte… : aucun `Ran N
        tests`. Un skip ne pollue ni les succès ni les échecs ; un vert mentirait."""
        with self.assertRaises(SkipScenario):
            self._verdict("Got an error creating the test database: database is being accessed\n",
                          returncode=0)

    def test_an_unreadable_verdict_is_not_taken_for_a_green(self):
        ok, detail = self._verdict("Ran 7 tests in 0.500s\n")     # ni OK ni FAILED
        self.assertFalse(ok)
        self.assertIn('ILLISIBLE', detail)

    def test_a_timeout_is_a_failure_that_says_so(self):
        import subprocess
        with patch('wama.common.nightly_suite.subprocess.run',
                   side_effect=subprocess.TimeoutExpired(cmd='test', timeout=1)):
            ok, detail = _run_label('wama.demo')({})
        self.assertFalse(ok)
        self.assertIn('sans rendre son verdict', detail)


class NightlySuiteLabelsTest(SimpleTestCase):

    def test_third_party_apps_stay_out(self):
        """Mesuré au premier dry-run : `django.contrib.admin` et `rest_framework` étaient
        entrés, parce que les venvs vivent DANS le dépôt — `site-packages` est le vrai critère."""
        labels = test_labels()
        self.assertTrue(labels, "aucun label : la dérivation ne voit plus les apps")
        for label in labels:
            with self.subTest(label=label):
                self.assertFalse(label.startswith(('django.', 'rest_framework')))

    def test_our_apps_with_tests_are_in(self):
        labels = test_labels()
        self.assertIn('wama.common', labels)
        self.assertIn('wama.model_manager', labels)


class FunctionalGridSeparatesSubstrateFromAppsTest(TestCase):
    """
    Le SUBSTRAT n'est pas une app — remarque de Fabien, 2026-09-19, sur la page `/apps/`.

    Le stage `suite` a fait entrer 18 labels dans la grille fonctionnelle, dont **10 hors du
    catalogue d'apps** (`wama.common`, `wama_data`, `accounts`, `gateway`, `filemanager`,
    `model_manager`, `studio`, `media_library`, et les deux du Lab). Les afficher dans une table
    dont la première colonne s'intitule « Application » ferait MENTIR la page : une grille par app
    répond à « cette app est-elle conforme et fonctionne-t-elle ? », pas à « le dépôt est-il
    sain ? ».

    Cette garde existe pour qu'un label transverse ajouté demain ne se range pas tout seul parmi
    les apps — c'est exactement ainsi que la première version l'a fait.
    """

    def test_no_non_app_label_is_shown_as_an_app(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        from wama.common.app_registry import APP_CATALOG
        admin = get_user_model().objects.create_user('admin_grids', password='x',
                                                     is_superuser=True, is_staff=True)
        self.client.force_login(admin)
        response = self.client.get(reverse('common:apps_catalog'))
        self.assertEqual(response.status_code, 200)
        apps_grid = response.context['grille_fonctionnelle']
        substrate = response.context['grille_substrat']
        intruders = [k for k in apps_grid if k not in APP_CATALOG]
        self.assertEqual(intruders, [], "un module hors catalogue est affiché comme une app")
        self.assertTrue(all(k not in APP_CATALOG for k in substrate),
                        "une app est rangée dans le substrat")
        self.assertFalse(set(apps_grid) & set(substrate), "les deux tables se recoupent")
