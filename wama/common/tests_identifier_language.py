# -*- coding: utf-8 -*-
"""
La LANGUE des identifiants de code est tenue par des BUDGETS, pas par la mémoire de qui écrit.

Question de Fabien, 2026-09-19 : *« Encore des termes en français... Comment arrêter ça ? »* — la
règle existe depuis le 2026-08-22 (`AGENTS.md`), elle a été durcie le 14/09, et elle a dérivé
quand même : **4084 identifiants français** au relevé (2653 de code, 133 noms de classes de
test, 1298 noms de méthodes de test — 4081 depuis que ce fichier-ci est en anglais). Deux fois dans la même journée, du code NEUF en a introduit et
c'est l'œil de Fabien qui l'a vu, après l'écriture.

*Une règle qui demande de se souvenir n'est pas un contrôle.* Ces tests SONT le contrôle : ils
rendent l'ajout impossible sans exiger le renommage des 4081 (qui serait un chantier à part, et
risqué côté code — un renommage ne casse pas, il rend FAUX). Motif déjà éprouvé ici :
`tests_hf_cache_routing`, dont le budget de mutations de cache HF « ne peut que descendre » et a
fini à zéro.

Décision de Fabien le même jour : *« on bascule tout le code y compris les tests en anglais »* —
l'exemption des noms de tests est LEVÉE, et les trois budgets sont appliqués.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.management.commands.check_identifier_language import (
    BUDGET_CODE, BUDGET_TEST_CLASSES, BUDGET_TEST_NAMES, BUDGET_TOTAL, counts, is_french,
    is_test_class, roots_of,
)


class IdentifierLanguageTest(SimpleTestCase):
    """Les budgets ne peuvent que DESCENDRE — et le message d'échec doit nommer les coupables.

    ⭐ PREMIER fichier de tests écrit APRÈS la bascule du 2026-09-19 : ses noms sont en anglais.
    Le STYLE que la doctrine défendait — une phrase qui énonce un COMPORTEMENT, pas un nom de
    cible — est conservé ; c'est lui qui valait, pas la langue.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.measured = counts(Path(settings.BASE_DIR))
        cls.by_file = cls.measured['by_file']
        cls.names = cls.measured['names']

    def _budgets(self):
        """(libellé, mesuré, budget) — les trois comptes, tels que la commande les applique."""
        return (('code', self.measured['code'], BUDGET_CODE),
                ('noms de classes de test', self.measured['test_classes'], BUDGET_TEST_CLASSES),
                ('noms de méthodes de test', self.measured['test_names'], BUDGET_TEST_NAMES))

    def test_no_budget_is_exceeded(self):
        """Un identifiant français AJOUTÉ fait monter un compte : le test échoue en nommant les
        fichiers les plus chargés, pour que la correction soit immédiate."""
        over = [(label, seen, budget) for label, seen, budget in self._budgets() if seen > budget]
        if over:
            worst = sorted(self.by_file.items(), key=lambda kv: -len(kv[1]))[:5]
            detail = '\n    '.join(
                f"{rel} : {sorted({n for _, n, _ in found})[:6]}" for rel, found in worst)
            self.fail(
                '; '.join(f"{label} {seen} > {budget}" for label, seen, budget in over) + '\n'
                f"  Un identifiant de code se nomme en ANGLAIS (AGENTS.md — les tests aussi, "
                f"décision du 2026-09-19) : le remède est de renommer, JAMAIS de relever un "
                f"budget.\n"
                f"  `manage.py check_identifier_language --detail` / `--test-names` les listent ; "
                f"`git diff` dit lesquels sont de vous.\n    {detail}")

    def test_budgets_stay_pinned_to_the_measure_with_no_slack(self):
        """Une marge est une autorisation d'en ajouter. Quand un compte descend (passe de
        renommage), son budget doit descendre avec lui — sinon le gain se perd en silence."""
        for label, seen, budget in self._budgets():
            with self.subTest(budget=label):
                self.assertEqual(seen, budget,
                                 f"budget « {label} » à recaler : mesuré {seen}, déclaré {budget} "
                                 f"(le descendre verrouille le gain ; le relever est interdit)")
        self.assertEqual(self.measured['total'], BUDGET_TOTAL)

    def test_the_test_suite_is_actually_found(self):
        """Garde de vacuité : si le relevé ne voyait plus les tests, ses budgets tomberaient à
        zéro et le contrôle passerait au vert en ne mesurant rien."""
        self.assertGreater(self.measured['test_methods'], 2000)
        self.assertGreater(len(self.by_file), 300)

    def test_what_is_counted_and_in_which_budget(self):
        """Une méthode `test_*` et une classe `*Test` sont désormais comptées (décision du
        19/09), mais dans LEURS budgets — le budget `code` ne les voit pas, sinon une passe de
        renommage des tests masquerait une dérive de la production."""
        import ast

        from wama.common.management.commands.check_identifier_language import _Collector
        tree = ast.parse(
            "class TacheDeclareeTest:\n"
            "    def test_une_tache_est_declaree(self):\n"
            "        lus = 1\n"
            "        return lus\n"
            "def charger_le_fichier(chemin):\n"
            "    return chemin\n")
        collector = _Collector()
        collector.visit(tree)
        seen = {(kind, name) for kind, name, _ in collector.found}
        # Le collecteur ne rend PAS les noms de méthodes de test : `scan_test_names` s'en charge.
        self.assertNotIn(('function', 'test_une_tache_est_declaree'), seen)
        self.assertIn(('variable', 'lus'), seen)          # une variable DANS un test est du code
        self.assertIn(('function', 'charger_le_fichier'), seen)
        self.assertIn(('argument', 'chemin'), seen)
        self.assertIn(('class', 'TacheDeclareeTest'), seen)
        self.assertTrue(is_test_class('class', 'TacheDeclareeTest'))

    def test_test_method_names_have_their_own_count(self):
        """Réponse mesurée à « c'est surtout les tests ? » : non — 2653 de code contre 1431 de
        nommage de tests. Le détail par nature reste lisible parce que les comptes sont séparés."""
        from wama.common.management.commands.check_identifier_language import scan_test_names
        french, total = scan_test_names(Path(settings.BASE_DIR))
        self.assertEqual(len(french), self.measured['test_names'])
        self.assertEqual(total, self.measured['test_methods'])
        self.assertGreater(self.measured['code'], self.measured['test_names'],
                           "le code reste la part majoritaire de la dette")

    def test_steering_by_root_says_where_the_next_pass_goes(self):
        """Une passe de renommage par RADICAL solde par tranches nettes : 605 noms distincts
        seulement, et les 20 premiers radicaux couvrent plus de la moitié de la dette de code."""
        roots = roots_of(self.by_file)
        top = roots.most_common(20)
        self.assertGreaterEqual(sum(n for _, n in top) * 100 // self.measured['code'], 50,
                                "si la dette n'est plus concentrée, le plan par radical tombe")
        self.assertEqual(top[0][0], 'cle', "le radical le plus rentable a changé : replanifier")

    def test_an_accent_is_a_certain_signal(self):
        """Python 3 accepte les accents dans un identifiant : `bougé` était en production."""
        self.assertTrue(is_french('bougé'))
        self.assertTrue(is_french('déjà_vu'))

    def test_words_ambiguous_in_both_languages_are_not_counted(self):
        """Un budget bruyant se contourne : `source`, `type`, `mode`, `page`, `total`, `format`,
        `instance`, `table` s'écrivent pareil dans les deux langues et restent hors de la liste."""
        for name in ('source', 'model_type', 'mode', 'page_size', 'total', 'output_format',
                     'instance', 'table_name', 'note', 'charge'):
            with self.subTest(name=name):
                self.assertFalse(is_french(name), f"{name} ne doit pas être compté")

    def test_an_unknown_word_passes(self):
        """Liste NOIRE, jamais blanche : le contrôle ne bloque pas un nom anglais qu'il ne
        connaît pas — c'est ce qui le rend utilisable sans dictionnaire embarqué."""
        for name in ('merged_capabilities', 'request_install', 'yolo_task_of', 'disk_space_guard'):
            with self.subTest(name=name):
                self.assertFalse(is_french(name))
