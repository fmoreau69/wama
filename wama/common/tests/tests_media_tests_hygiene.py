"""Hygiène des MÉDIAS DE TEST (question de Fabien, 2026-09-13) : la suite écrit dans
`media_tests/` (sœur de `media/`, jamais dedans), les exécutions orphelines s'y balaient, et
les témoins du nocturne se reconnaissent à leur NOM — y compris dans le dossier temporaire."""
import os
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from wama.common import runners


class LesMediasDeTestVivent_HORS_DeMediaTest(SimpleTestCase):
    def test_le_dossier_des_tests_est_une_soeur_de_media_jamais_un_enfant(self):
        racine = Path(settings.BASE_DIR) / runners.DOSSIER_MEDIAS_DE_TEST
        media = Path(settings.BASE_DIR) / 'media'
        self.assertEqual(racine.parent, media.parent)
        self.assertFalse(str(racine.resolve()).startswith(str(media.resolve()) + os.sep))

    def test_cette_execution_ecrit_bien_sous_media_tests(self):
        """Le runner a redirigé MEDIA_ROOT : ce test tourne DANS un `run-*` de media_tests."""
        self.assertIn(runners.DOSSIER_MEDIAS_DE_TEST, Path(settings.MEDIA_ROOT).parts)
        self.assertTrue(Path(settings.MEDIA_ROOT).name.startswith('run-'))


class BalayageDesRunsOrphelinsTest(SimpleTestCase):
    def setUp(self):
        self.racine = Path(tempfile.mkdtemp(prefix='mt_'))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.racine, ignore_errors=True)

    def _run(self, nom, vide=True, age_s=0):
        d = self.racine / nom
        d.mkdir()
        if not vide:
            (d / 'x.txt').write_text('x')
        t = time.time() - age_s
        os.utime(d, (t, t))
        return d

    def test_vide_ou_vieux_est_balaye_recent_et_plein_est_garde(self):
        from unittest.mock import patch
        vide = self._run('run-vide')
        vieux = self._run('run-vieux', vide=False, age_s=runners.RUN_ORPHELIN_APRES_S + 60)
        vivant = self._run('run-vivant', vide=False, age_s=60)
        etranger = self.racine / 'pas-un-run'
        etranger.mkdir()
        # `_supprimer_sans_risque` exige que la racine soit `BASE_DIR/media_tests` : on la
        # fait pointer sur la racine JETABLE de ce test pour mesurer le tri, pas la garde.
        with patch.object(runners.settings, 'BASE_DIR', str(self.racine.parent)), \
             patch.object(runners, 'DOSSIER_MEDIAS_DE_TEST', self.racine.name):
            n = runners.balayer_runs_orphelins(self.racine)
        self.assertEqual(n, 2)
        self.assertFalse(vide.exists())
        self.assertFalse(vieux.exists())
        self.assertTrue(vivant.exists(), 'une campagne concurrente ne se balaie JAMAIS')
        self.assertTrue(etranger.exists())


def _names_media_root(node) -> bool:
    """`settings.MEDIA_ROOT`, possibly wrapped (`Path(…)`, `str(…)`, `Path(…).resolve()`)."""
    import ast
    while True:
        if isinstance(node, ast.Attribute) and node.attr == 'MEDIA_ROOT':
            return True
        if isinstance(node, ast.Call) and len(node.args) == 1:   # `os.path.join(…, 'x')` : a child
            node = node.args[0]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            node = node.func.value
        else:
            return False


def _media_root_removals(source: str) -> list:
    """Lines where `MEDIA_ROOT`, read at that moment, is handed to `rmtree` — called directly or
    registered with `addCleanup` / `addClassCleanup`."""
    import ast
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, 'attr', getattr(node.func, 'id', ''))
        if name == 'rmtree' and node.args and _names_media_root(node.args[0]):
            lines.append(node.lineno)
        elif (name in ('addCleanup', 'addClassCleanup') and len(node.args) >= 2
              and getattr(node.args[0], 'attr', getattr(node.args[0], 'id', '')) == 'rmtree'
              and _names_media_root(node.args[1])):
            lines.append(node.lineno)
    return lines


class NothingRemovesMediaRootReadOnTheFlyTest(SimpleTestCase):
    """2026-10-27 : every user's media was deleted by `addCleanup(shutil.rmtree,
    settings.MEDIA_ROOT, True)` in a test class that had lost its `override_settings`, run by a
    script outside the test runner. Whatever MEDIA_ROOT names at that moment gets removed : the
    throwaway folder is removed by the PATH the test created, never by the setting."""

    def test_no_code_hands_media_root_to_rmtree(self):
        base = Path(settings.BASE_DIR)
        found = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (base / root).rglob('*.py'):
                if 'migrations' in path.parts or 'vendor' in path.parts:
                    continue
                source = path.read_text(encoding='utf-8', errors='replace')
                if 'MEDIA_ROOT' not in source or 'rmtree' not in source:
                    continue
                found += [f'{path.relative_to(base)}:{n}' for n in _media_root_removals(source)]
        self.assertEqual([], found)

    def test_the_scan_sees_each_form_of_the_fault(self):
        for line in ('shutil.rmtree(settings.MEDIA_ROOT)',
                     'shutil.rmtree(Path(settings.MEDIA_ROOT).resolve(), ignore_errors=True)',
                     'self.addCleanup(shutil.rmtree, settings.MEDIA_ROOT, True)',
                     'self.addCleanup(rmtree, str(settings.MEDIA_ROOT))'):
            self.assertEqual([1], _media_root_removals(line), line)
        for line in ('self.addCleanup(shutil.rmtree, self.media, True)',
                     "shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'smoke'))"):
            self.assertEqual([], _media_root_removals(line), line)


class LesTemoinsSeReconnaissentAuNomTest(TestCase):
    def test_la_fixture_du_studio_vit_chez_le_compte_de_test_et_porte_le_prefixe(self):
        from wama.studio import nightly_scenarios as ns
        self.assertTrue(ns._ENTREE_NOM.startswith('wama_temoin_'))

        class U:
            pk = 424242
        # sans ffmpeg : on ne génère rien, on ne lit que le CHEMIN décidé
        from unittest.mock import patch
        with patch.object(ns.os.path, 'exists', return_value=True):
            rel = ns._entree('/nulle/part', U())
        self.assertEqual(rel, f'users/424242/temp/{ns._ENTREE_NOM}')

    def test_le_balayage_couvre_aussi_le_dossier_temporaire_de_notre_seul_prefixe(self):
        from wama.common.services.nightly_tests import sweep_test_witnesses
        tmp = Path(tempfile.gettempdir())
        notre = tmp / f'wama_temoin_hygiene_{os.getpid()}.txt'
        autre = tmp / f'tmp_export_hygiene_{os.getpid()}.txt'
        notre.write_text('x'); autre.write_text('x')
        try:
            sweep_test_witnesses()
            self.assertFalse(notre.exists(), 'notre témoin est balayé')
            self.assertTrue(autre.exists(), "un fichier qui n'est pas à nous ne l'est jamais")
        finally:
            for p in (notre, autre):
                p.unlink(missing_ok=True)
