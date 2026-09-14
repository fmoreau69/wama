"""Tests du cache par empreinte de fichier (`common/file_cache.py`) et de ce qu'il a permis :
une résolution de backends EN SÉRIE qui ne relit plus l'inventaire à chaque modèle.

Ce qui justifie la brique : une valeur n'est calculée qu'une fois pour une même empreinte, et un
fichier modifié est RELU — un cache qui servirait du périmé serait pire que pas de cache.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from .file_cache import FileCache, file_stamp


class FileCacheTest(SimpleTestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.f = Path(tmp.name) / 'x.txt'
        self.f.write_text('un', encoding='utf-8')
        self.appels = 0

    def _lire(self, chemin):
        self.appels += 1
        return chemin.read_text(encoding='utf-8')

    def test_une_valeur_n_est_calculee_qu_une_fois_pour_une_meme_empreinte(self):
        cache = FileCache()
        self.assertEqual([cache.get(self.f, self._lire) for _ in range(3)], ['un'] * 3)
        self.assertEqual(self.appels, 1)

    def test_un_fichier_modifie_est_relu(self):
        cache = FileCache()
        cache.get(self.f, self._lire)
        self.f.write_text('deux', encoding='utf-8')
        self.assertEqual(cache.get(self.f, self._lire), 'deux')

    def test_meme_taille_mais_date_changee_est_relu(self):
        # Le cas qu'une empreinte par TAILLE seule raterait : une réécriture de même longueur.
        cache = FileCache()
        cache.get(self.f, self._lire)
        st = self.f.stat()
        self.f.write_text('UN', encoding='utf-8')
        os.utime(self.f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
        self.assertEqual(cache.get(self.f, self._lire), 'UN')

    def test_un_fichier_absent_leve_et_n_a_pas_d_empreinte(self):
        absent = self.f.with_name('absent.txt')
        with self.assertRaises(OSError):
            FileCache().get(absent, self._lire)
        self.assertIsNone(file_stamp(absent))

    def test_la_cle_separe_deux_calculs_du_meme_fichier(self):
        cache = FileCache()
        self.assertEqual(cache.get(self.f, lambda p: 'admin', key=(str(self.f), True)), 'admin')
        self.assertEqual(cache.get(self.f, lambda p: 'compte', key=(str(self.f), False)), 'compte')


class ResolutionEnSerieTest(TestCase):
    """Le vivier lu UNE fois se passe à la résolution — mesuré le 2026-09-14 : sans lui, une
    extraction de manifeste relisait l'inventaire autant de fois que l'app a de modèles (48)."""

    def test_avec_le_vivier_la_resolution_ne_relit_pas_l_inventaire_et_rend_la_meme_classe(self):
        from .backends.manager import backend_for_engine
        from .services import backend_inventory as bi

        vivier = bi.resolvable_entries()
        moteurs = sorted({e.engine for e in vivier if e.engine})
        self.assertTrue(moteurs, "aucun moteur déclaré : le test ne mesurerait rien")
        attendu = {m: backend_for_engine(m) for m in moteurs}
        with patch.object(bi, 'inventory', side_effect=AssertionError("inventaire relu")):
            obtenu = {m: backend_for_engine(m, entries=vivier) for m in moteurs}
        self.assertEqual(obtenu, attendu)
