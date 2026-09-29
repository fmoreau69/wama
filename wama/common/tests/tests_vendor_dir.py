"""Le code tiers vendorisé vit sous une racine DÉCLARÉE — et reste invisible aux balayages.

POURQUOI (2026-09-07/08, décision de Fabien : « pour les vendorisés, ils iront au même endroit
dans un dossier `vendor` avec un readme, et on gitignore les sous-dossiers de code tiers »).
MuseTalk (45 Mo) et CodeFormer (36 Mo) vivaient sous `wama/avatarizer/`, et les backends les
localisaient en résolvant un PAQUET PYTHON (`VENDOR_PACKAGE`) pour trouver un dossier JAMAIS
importé — la confusion backend/moteur incarnée, pointée par Fabien.

Ce que ces tests tiennent, et qui casserait en silence :
  • la racine est DÉCLARÉE (`settings.BACKEND_VENDOR_DIR`), comme `AI_MODELS_DIR` — un backend
    ne reconstruit pas un chemin ;
  • `vendor/` n'est PAS un paquet Python (pas d'`__init__.py`) : sinon la découverte de tests et
    les balayages y entreraient, et 81 Mo de source tierce seraient analysés à chaque passe ;
  • le vivier ne le voit pas — son balayage est `glob('*.py')`, NON récursif. C'est ce qui rend
    l'exclusion GRATUITE, et c'est précisément ce que j'avais annoncé à tort comme un obstacle
    (« il faudra l'exclure ») avant de lire le code. Un test vaut mieux qu'un souvenir ;
  • plus aucun backend ne résout un paquet Python pour localiser du code tiers.
"""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.services import backend_inventory as bi


def _vendor() -> Path:
    return Path(settings.BACKEND_VENDOR_DIR)


class RacineVendorDeclareeTest(SimpleTestCase):

    def test_la_racine_est_declaree_dans_settings(self):
        self.assertTrue(hasattr(settings, 'BACKEND_VENDOR_DIR'),
                        'racine du code vendorisé non déclarée')
        self.assertEqual(_vendor().name, 'vendor')

    def test_elle_vit_SOUS_le_paquet_des_backends(self):
        """Décision Fabien : « au même endroit », à côté des backends qui les exécutent."""
        self.assertEqual(_vendor().parent.name, 'backends')

    def test_vendor_n_est_PAS_un_paquet_python(self):
        """Un `__init__.py` ici ferait entrer la découverte de tests dans du code tiers."""
        self.assertFalse((_vendor() / '__init__.py').exists(),
                         'vendor/ ne doit JAMAIS être un paquet importable')

    def test_le_README_est_versionne_et_dit_la_regle(self):
        readme = _vendor() / 'README.md'
        self.assertTrue(readme.exists(), 'README manquant : le dossier ne dirait pas ce qu’il est')
        texte = readme.read_text(encoding='utf-8')
        for attendu in ('gitignor', 'BACKEND_VENDOR_DIR', 'sous-processus'):
            self.assertIn(attendu, texte, f'le README ne dit pas « {attendu} »')


class VendorInvisibleAuBalayageTest(SimpleTestCase):
    """Le vivier ne descend pas dans `vendor/` — et ce n'est pas une exclusion, c'est sa forme."""

    def test_le_balayage_du_vivier_n_est_PAS_recursif(self):
        """`glob('*.py')`, jamais `rglob` : c'est CE choix qui rend `vendor/` gratuit.

        ⚠ J'avais annoncé le contraire à Fabien (« il faudra l'exclure explicitement, sinon
        81 Mo sont analysés à chaque affichage ») AVANT d'avoir lu la ligne. Ce test remplace
        ce souvenir par une garde.
        """
        source = Path(bi.__file__).read_text(encoding='utf-8')
        arbre = ast.parse(source)
        appels = {n.func.attr for n in ast.walk(arbre)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn('glob', appels)
        self.assertNotIn('rglob', appels,
                         'un balayage récursif descendrait dans vendor/ (code tiers)')

    def test_aucune_entree_du_vivier_ne_vient_de_vendor(self):
        entrees = [e for a in bi.inventory() for e in a.entries]
        fautives = [e.path for e in entrees if 'vendor' in (e.module or e.path or '')]
        self.assertEqual(fautives, [], 'le vivier a capté du code tiers')


class PlusAucunPaquetPourTrouverUnDossierTest(SimpleTestCase):
    """`VENDOR_PACKAGE` résolvait un paquet importable pour situer du code jamais importé."""

    def test_les_backends_vendorises_lisent_la_racine_DECLAREE(self):
        for nom in ('musetalk_backend', 'codeformer_backend'):
            chemin = Path(settings.BASE_DIR) / 'wama' / 'common' / 'backends' / f'{nom}.py'
            source = chemin.read_text(encoding='utf-8')
            arbre = ast.parse(source)
            affectations = {t.id for n in ast.walk(arbre) if isinstance(n, ast.Assign)
                            for t in n.targets if isinstance(t, ast.Name)}
            self.assertNotIn('VENDOR_PACKAGE', affectations,
                             f'{nom} localise encore son moteur par un paquet Python')
            self.assertIn('BACKEND_VENDOR_DIR', source,
                          f'{nom} ne lit pas la racine déclarée')
