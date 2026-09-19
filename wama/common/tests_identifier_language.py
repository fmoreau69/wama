# -*- coding: utf-8 -*-
"""
La LANGUE des identifiants de code est tenue par un BUDGET, pas par la mémoire de qui écrit.

Question de Fabien, 2026-09-19 : *« Encore des termes en français... Comment arrêter ça ? »* — la
règle existe depuis le 2026-08-22 (`AGENTS.md`), elle a été durcie le 14/09, et elle a dérivé
quand même : **2653 identifiants français dans 358 fichiers** au relevé. Deux fois dans la même
journée, du code NEUF en a introduit et c'est l'œil de Fabien qui l'a vu, après l'écriture.

*Une règle qui demande de se souvenir n'est pas un contrôle.* Ce test EST le contrôle : il rend
l'ajout impossible sans exiger le renommage des 2653 (qui serait un chantier à part, et risqué —
un renommage ne casse pas, il rend FAUX). Motif déjà éprouvé ici : `tests_hf_cache_routing`, dont
le budget de mutations de cache HF « ne peut que descendre » et a fini à zéro.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.management.commands.check_identifier_language import (
    BUDGET, BUDGET_WITH_TEST_CLASSES, is_french, is_test_class, scan,
)


class LangueDesIdentifiantsTest(SimpleTestCase):
    """Le budget ne peut que DESCENDRE — et le message d'échec doit nommer les coupables."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(settings.BASE_DIR)
        cls.total, cls.by_file, cls.names = scan(base)
        cls.strict_total, _, _ = scan(base, with_test_classes=True)

    def test_le_budget_n_est_pas_depasse(self):
        """Un identifiant français AJOUTÉ fait monter le compte : le test échoue en nommant les
        fichiers les plus chargés, pour que la correction soit immédiate."""
        if self.total > BUDGET:
            worst = sorted(self.by_file.items(), key=lambda kv: -len(kv[1]))[:5]
            detail = '\n    '.join(
                f"{rel} : {sorted({n for _, n, _ in found})[:6]}" for rel, found in worst)
            self.fail(
                f"{self.total} identifiants de code en français > budget {BUDGET}.\n"
                f"  Un identifiant de code se nomme en ANGLAIS (AGENTS.md) — le remède est de "
                f"renommer, JAMAIS de relever le budget.\n"
                f"  `manage.py check_identifier_language --detail` les liste ; `git diff` dit "
                f"lesquels sont de vous.\n    {detail}")

    def test_le_budget_reste_CALE_sur_la_mesure_sans_marge(self):
        """Une marge est une autorisation d'en ajouter. Quand le compte descend (passe de
        renommage), le budget doit descendre avec lui — sinon le gain se perd en silence."""
        self.assertEqual(self.total, BUDGET,
                         f"budget à recaler : mesuré {self.total}, déclaré {BUDGET} "
                         f"(descendre BUDGET verrouille le gain ; le relever est interdit)")
        self.assertEqual(self.strict_total, BUDGET_WITH_TEST_CLASSES,
                         "budget `--strict-classes` à recaler de la même façon")

    def test_les_noms_de_tests_sont_la_SEULE_exemption_de_la_doctrine(self):
        """`test_*` est exempté (« il se lit dans un rapport d'échec, et nulle part ailleurs »),
        mais une VARIABLE dans un test reste du code : c'est exactement ce que Fabien a relevé
        (`lus` dans `tests_external_sources`)."""
        from wama.common.management.commands.check_identifier_language import _Collector
        import ast
        tree = ast.parse(
            "class TacheDeclareeTest:\n"
            "    def test_une_tache_est_declaree(self):\n"        # exempté (méthode de test)
            "        lus = 1\n"                                   # compté (variable)
            "        return lus\n"
            "def charger_le_fichier(chemin):\n"                   # compté (fonction + argument)
            "    return chemin\n")
        collector = _Collector()
        collector.visit(tree)
        seen = {(kind, name) for kind, name, _ in collector.found}
        self.assertNotIn(('function', 'test_une_tache_est_declaree'), seen)
        self.assertIn(('variable', 'lus'), seen)
        self.assertIn(('function', 'charger_le_fichier'), seen)
        self.assertIn(('argument', 'chemin'), seen)
        # La classe de test est relevée mais EXEMPTÉE du budget par défaut (zone grise assumée).
        self.assertIn(('class', 'TacheDeclareeTest'), seen)
        self.assertTrue(is_test_class('class', 'TacheDeclareeTest'))

    def test_un_accent_est_un_signal_certain(self):
        """Python 3 accepte les accents dans un identifiant : `bougé` était en production."""
        self.assertTrue(is_french('bougé'))
        self.assertTrue(is_french('déjà_vu'))

    def test_les_mots_ambigus_anglais_francais_ne_sont_PAS_comptes(self):
        """Un budget bruyant se contourne : `source`, `type`, `mode`, `page`, `total`, `format`,
        `instance`, `table` s'écrivent pareil dans les deux langues et restent hors de la liste."""
        for name in ('source', 'model_type', 'mode', 'page_size', 'total', 'output_format',
                    'instance', 'table_name', 'note', 'charge'):
            with self.subTest(name=name):
                self.assertFalse(is_french(name), f"{name} ne doit pas être compté")

    def test_un_mot_inconnu_passe(self):
        """Liste NOIRE, jamais blanche : le contrôle ne bloque pas un nom anglais qu'il ne
        connaît pas — c'est ce qui le rend utilisable sans dictionnaire embarqué."""
        for name in ('merged_capabilities', 'request_install', 'yolo_task_of', 'disk_space_guard'):
            with self.subTest(name=name):
                self.assertFalse(is_french(name))
