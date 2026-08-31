"""
Verrous de l'installation de librairies — jonction manifeste→pip (2026-08-31).

Ce que ces tests attestent : les VERROUS (ROADMAP §16.7) refusent avant de toucher pip
(pin exact, PyPI par nom, kill switch, allowlist humaine) et le plan (dry-run) n'a aucun
effet. Aucun test n'installe quoi que ce soit — le chemin `--apply` réel se valide à la
main sur une librairie choisie (geste humain par définition).
"""
import os

from django.test import TestCase

from wama.common.models import Library
from wama.model_manager.services.model_installer import (
    PIP_KILL_SWITCH_ENV,
    install_library,
    pip_install_packages,
    pip_spec_error,
)


class VerrousPipTest(TestCase):
    def test_un_spec_pinne_passe_les_verrous(self):
        self.assertIsNone(pip_spec_error('kokoro-onnx==0.4.9'))
        self.assertIsNone(pip_spec_error('chatterbox-tts[cuda]==0.1.2'))
        self.assertIsNone(pip_spec_error('faster-whisper==1.2.1'))

    def test_un_spec_non_pinne_est_refuse(self):
        for s in ('kokoro-onnx', 'kokoro-onnx>=0.4', 'kokoro-onnx~=0.4', 'pkg==*'):
            self.assertIsNotNone(pip_spec_error(s), s)

    def test_une_source_non_pypi_est_refusee(self):
        for s in ('git+https://github.com/x/y', 'file:///tmp/x', './paquet-local',
                  'pkg==1.0 --index-url https://ailleurs', '-e .', 'pkg==1.0; extra == "x"',
                  'https://evil/pkg.whl', 'pkg @ file:///tmp/pkg'):
            self.assertIsNotNone(pip_spec_error(s), s)

    def test_le_kill_switch_bloque_avant_pip(self):
        os.environ[PIP_KILL_SWITCH_ENV] = '1'
        try:
            res = pip_install_packages(['nimporte==1.0'])
        finally:
            os.environ.pop(PIP_KILL_SWITCH_ENV, None)
        self.assertFalse(res['ok'])
        self.assertIn(PIP_KILL_SWITCH_ENV, res['error'])

    def test_un_spec_invalide_est_refuse_avant_pip(self):
        res = pip_install_packages(['git+https://github.com/x/y'])
        self.assertFalse(res['ok'])
        self.assertIn('refusé', res['error'])


class InstallLibraryTest(TestCase):
    def _lib(self, **surcharges):
        champs = dict(key='kokoro-onnx', name='kokoro-onnx',
                      pip_spec='kokoro-onnx==0.4.9')
        champs.update(surcharges)
        return Library.objects.create(**champs)

    def test_absente_du_registre_est_refusee(self):
        res = install_library('inconnue')
        self.assertFalse(res['ok'])
        self.assertIn('absente du registre', res['error'])

    def test_sans_is_allowed_l_installation_est_refusee(self):
        self._lib()   # is_allowed=False par défaut (jamais posé par la projection)
        res = install_library('kokoro-onnx', apply=True)
        self.assertFalse(res['ok'])
        self.assertIn('is_allowed', res['error'])

    def test_un_pip_spec_non_pinne_au_registre_est_refuse(self):
        self._lib(pip_spec='kokoro-onnx', is_allowed=True)
        res = install_library('kokoro-onnx', apply=True)
        self.assertFalse(res['ok'])
        self.assertIn('refusé', res['error'])

    def test_le_plan_n_installe_rien_et_dit_ce_qu_il_ferait(self):
        self._lib(is_allowed=True)
        res = install_library('kokoro-onnx')          # apply=False : plan seul
        self.assertTrue(res['ok'])
        self.assertTrue(res['would_install'])
        self.assertIn('venv_win', res['plan'])        # le venv non traité est SIGNALÉ
        lib = Library.objects.get(key='kokoro-onnx')
        self.assertFalse(lib.is_installed)            # aucun effet

    def test_deja_satisfaite_ne_reinstalle_pas(self):
        # `django` est forcément présent dans le venv de test : version constatée = cible.
        import importlib.metadata as im
        version = im.version('django')
        self._lib(key='django', name='django', pip_spec=f'django=={version}',
                  is_allowed=True)
        res = install_library('django', apply=True)
        self.assertTrue(res['ok'])
        self.assertFalse(res['installed'])            # rien tiré, patches non rejoués
        self.assertIsNone(res['patches'])
        lib = Library.objects.get(key='django')
        self.assertTrue(lib.is_installed)
        self.assertEqual(lib.installed_version, version)
