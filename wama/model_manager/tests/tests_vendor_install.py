"""
Route VENDOR de la route `library` (ROADMAP D-a, 2026-09-30) — une librairie que pip ne sait
pas installer, déclarée par son dépôt épinglé à un commit et un correctif versionné.

Ce que ces tests attestent, sur un VRAI dépôt git LOCAL (aucun réseau) :
  • les verrous de la déclaration (dépôt « owner/name », commit exact, correctif sous `patches/`) ;
  • pip OU vendor, jamais les deux ; la projection porte `vendor` et jamais `is_allowed` ;
  • le plan n'a aucun effet ; l'exécution exige l'allowlist ; elle clone AU COMMIT, applique le
    correctif et CONSTATE l'état ; la relancer ne fait rien ;
  • une modification locale NON déclarée n'est jamais écrasée — contre-épreuves : un chemin
    `ignore` et un simple changement de fins de ligne ne bloquent pas ;
  • les trois moteurs du corpus (MuseTalk, CodeFormer, TripoSR) sont déclarés et leurs
    correctifs existent.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from wama.common.manifests.builtin.library import (
    extract_library,
    validate_library_body,
    vendor_spec_error,
    write_back_library,
)
from wama.common.models import Library
from wama.model_manager.services import vendor_installer
from wama.model_manager.services.model_installer import install_library

GIT_ID = ['-c', 'user.email=test@wama.local', '-c', 'user.name=wama-test']


def _git(cwd, *args):
    return subprocess.run(['git', *GIT_ID, *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _valid_vendor(**over):
    spec = {'repo': 'owner/engine-repo', 'commit': 'a' * 40, 'engine': 'fake_engine'}
    spec.update(over)
    return spec


class VendorSpecLocksTest(TestCase):
    def test_a_pinned_declaration_passes(self):
        self.assertIsNone(vendor_spec_error(_valid_vendor()))
        self.assertIsNone(vendor_spec_error(_valid_vendor(patch='patches/x_local.diff',
                                                          ignore=['weights/', 'models'])))

    def test_a_moving_or_free_source_is_refused(self):
        for over in ({'repo': 'https://github.com/owner/repo'}, {'repo': 'owner'},
                     {'repo': '../owner/repo'}, {'commit': 'main'}, {'commit': 'v1.5'},
                     {'commit': 'a' * 7}, {'commit': 'A' * 40}, {'engine': ''},
                     {'engine': '../musetalk'}, {'patch': 'elsewhere/x.diff'},
                     {'patch': 'patches/../x.diff'}, {'ignore': '/abs'},
                     {'ignore': ['../out']}, {'url': 'https://x'}):
            self.assertIsNotNone(vendor_spec_error(_valid_vendor(**over)), over)

    def test_pip_or_vendor_never_both(self):
        body = {'identity': {'version': '1'}}
        self.assertEqual(validate_library_body(dict(body, install={'vendor': _valid_vendor()})), [])
        self.assertTrue(validate_library_body(dict(body, install={'pip': 'x==1',
                                                                  'vendor': _valid_vendor()})))
        self.assertTrue(validate_library_body(dict(body, install={})))
        self.assertTrue(validate_library_body(dict(body, install={'vendor': {'repo': 'x'}})))

    def test_the_import_root_is_a_path_inside_the_clone(self):
        self.assertIsNone(vendor_spec_error(_valid_vendor(import_root='src')))
        for root in ('../src', '/abs', 'src/../..'):
            self.assertIsNotNone(vendor_spec_error(_valid_vendor(import_root=root)), root)

    def test_projection_carries_vendor_but_never_the_allowlist(self):
        manifest = {'key': 'fake_engine', 'name': 'Fake',
                    'body': {'identity': {'version': 'aaaa'},
                             'install': {'vendor': _valid_vendor()}}}
        write_back_library(manifest, apply=True)
        lib = Library.objects.get(key='fake_engine')
        self.assertEqual(lib.vendor['commit'], 'a' * 40)
        self.assertEqual(lib.pip_spec, '')
        self.assertFalse(lib.is_allowed)


class VendorInstallTest(TestCase):
    """Un dépôt amont LOCAL à deux commits, un correctif sous un `patches/` jetable."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wama-vendor-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        upstream = self.tmp / 'upstream'
        upstream.mkdir()
        _git(upstream, 'init', '-q')
        (upstream / 'engine.py').write_text("VALUE = 1\n", encoding='utf-8', newline='\n')
        (upstream / 'other.py').write_text("OTHER = 1\n", encoding='utf-8', newline='\n')
        _git(upstream, 'add', '.')
        _git(upstream, 'commit', '-q', '-m', 'first')
        self.pinned = _git(upstream, 'rev-parse', 'HEAD')
        (upstream / 'engine.py').write_text("VALUE = 2\n", encoding='utf-8', newline='\n')
        _git(upstream, 'commit', '-q', '-am', 'second — must NOT be installed')
        self.upstream = upstream

        # Correctif déclaré : VALUE = 1 → VALUE = 42, exporté comme on exporte un vrai correctif.
        root = self.tmp / 'wama'
        (root / 'patches').mkdir(parents=True)
        work = self.tmp / 'work'
        _git(self.tmp, 'clone', '-q', str(upstream), str(work))
        _git(work, 'checkout', '-q', self.pinned)
        (work / 'engine.py').write_text("VALUE = 42\n", encoding='utf-8', newline='\n')
        (root / 'patches' / 'fake_local.diff').write_text(_git(work, 'diff') + '\n',
                                                          encoding='utf-8', newline='\n')
        self.root = root
        self.vendor_root = self.tmp / 'vendor'

        patchers = [mock.patch.object(vendor_installer, 'repo_url', lambda repo: str(upstream)),
                    mock.patch.object(vendor_installer, 'repo_root', lambda: root)]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        override = override_settings(BACKEND_VENDOR_DIR=self.vendor_root)
        override.enable()
        self.addCleanup(override.disable)

        self.lib = Library.objects.create(
            key='fake_engine', name='Fake engine', version=self.pinned[:12],
            vendor={'repo': 'owner/engine-repo', 'commit': self.pinned, 'engine': 'fake_engine',
                    'patch': 'patches/fake_local.diff', 'ignore': ['weights/']})
        self.clone = self.vendor_root / 'fake_engine'

    def test_the_plan_has_no_effect(self):
        res = install_library('fake_engine', apply=False)
        self.assertTrue(res['ok'])
        self.assertEqual(res['plan']['route'], 'vendor')
        self.assertEqual(res['plan']['actions'], ['clone', 'apply_patch'])
        self.assertFalse(self.clone.exists())

    def test_execution_requires_the_human_allowlist(self):
        res = install_library('fake_engine', apply=True)
        self.assertFalse(res['ok'])
        self.assertIn('is_allowed', res['error'])
        self.assertFalse(self.clone.exists())

    def test_install_clones_the_pinned_commit_applies_the_patch_and_is_idempotent(self):
        Library.objects.filter(key='fake_engine').update(is_allowed=True)
        res = install_library('fake_engine', apply=True)
        self.assertTrue(res['ok'], res.get('error'))
        self.assertEqual(_git(self.clone, 'rev-parse', 'HEAD'), self.pinned)
        self.assertEqual((self.clone / 'engine.py').read_text(), "VALUE = 42\n")
        lib = Library.objects.get(key='fake_engine')
        self.assertTrue(lib.is_installed)
        self.assertEqual(lib.installed_version, self.pinned)
        # Relancer ne fait rien : l'état constaté est déjà conforme.
        again = install_library('fake_engine', apply=True)
        self.assertTrue(again['ok'])
        self.assertEqual(again['plan']['actions'], [])
        self.assertFalse(again['installed'])

    def test_an_undeclared_local_change_is_never_overwritten(self):
        Library.objects.filter(key='fake_engine').update(is_allowed=True)
        install_library('fake_engine', apply=True)
        (self.clone / 'other.py').write_text("OTHER = 'hand-made fix'\n", encoding='utf-8')
        res = install_library('fake_engine', apply=True)
        self.assertFalse(res['ok'])
        self.assertEqual(res['plan']['state']['local_changes'], ['other.py'])
        self.assertEqual((self.clone / 'other.py').read_text(), "OTHER = 'hand-made fix'\n")

    def test_ignored_paths_and_line_endings_do_not_block(self):
        """Contre-épreuve : ni un chemin `ignore` ni une conversion CRLF ne sont des modifications."""
        Library.objects.filter(key='fake_engine').update(is_allowed=True)
        install_library('fake_engine', apply=True)
        (self.clone / 'weights').mkdir()
        (self.clone / 'weights' / 'model.pth').write_bytes(b'weights')
        (self.clone / 'other.py').write_bytes(b"OTHER = 1\r\n")
        state = vendor_installer.vendor_state(Library.objects.get(key='fake_engine').vendor)
        self.assertEqual(state['verdict'], 'conform', state)
        self.assertEqual(state['untracked'], [])

    def test_a_clone_at_another_commit_is_moved_to_the_pinned_one(self):
        Library.objects.filter(key='fake_engine').update(is_allowed=True)
        _git(self.tmp, 'clone', '-q', str(self.upstream), str(self.clone))   # à « second »
        state = vendor_installer.vendor_state(Library.objects.get(key='fake_engine').vendor)
        self.assertEqual(state['verdict'], 'other_commit')
        res = install_library('fake_engine', apply=True)
        self.assertTrue(res['ok'], res.get('error'))
        self.assertEqual(_git(self.clone, 'rev-parse', 'HEAD'), self.pinned)
        self.assertEqual((self.clone / 'engine.py').read_text(), "VALUE = 42\n")


class VendorRequiresTest(TestCase):
    """Une librairie vendorisée qui REQUIERT une autre librairie vendorisée (2026-11-13, SAM Audio :
    `dacvae`, `perception_models`… tirés par `git+`) — deux vrais dépôts git LOCAUX, un corpus
    jetable qui porte le `requires`."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wama-vendor-requires-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repos, self.commits = {}, {}
        for repo, files in (('owner/engine-repo', {'engine.py': 'import depmod\nVALUE = depmod.DEP\n'}),
                            ('owner/dep-repo', {'src/depmod.py': 'DEP = 7\n'})):
            upstream = self.tmp / repo.replace('/', '_')
            for name, text in files.items():
                (upstream / name).parent.mkdir(parents=True, exist_ok=True)
                (upstream / name).write_text(text, encoding='utf-8', newline='\n')
            _git(upstream, 'init', '-q')
            _git(upstream, 'add', '.')
            _git(upstream, 'commit', '-q', '-m', 'first')
            self.repos[repo], self.commits[repo] = upstream, _git(upstream, 'rev-parse', 'HEAD')
        self.vendor_root = self.tmp / 'vendor'
        self.corpus = self.tmp / 'base'
        (self.corpus / 'manifests' / 'libraries').mkdir(parents=True)
        self.vendors = {
            'fake_engine': {'repo': 'owner/engine-repo', 'commit': self.commits['owner/engine-repo'],
                            'engine': 'fake_engine'},
            'fake_dep': {'repo': 'owner/dep-repo', 'commit': self.commits['owner/dep-repo'],
                         'engine': 'fake_dep', 'import_root': 'src'}}
        self._write_manifest('fake_engine', requires=['fake_dep'])
        self._write_manifest('fake_dep')
        for key, vendor in self.vendors.items():
            Library.objects.create(key=key, name=key, version=vendor['commit'][:12], vendor=vendor)
        patcher = mock.patch.object(vendor_installer, 'repo_url', lambda repo: str(self.repos[repo]))
        patcher.start()
        self.addCleanup(patcher.stop)
        override = override_settings(BACKEND_VENDOR_DIR=self.vendor_root, BASE_DIR=self.corpus)
        override.enable()
        self.addCleanup(override.disable)
        from wama.common.manifests.builtin.library import forget_vendor_engines
        forget_vendor_engines()
        self.addCleanup(forget_vendor_engines)

    def _write_manifest(self, key, requires=()):
        manifest = {'manifest_kind': 'library', 'key': key, 'name': key, 'schema_version': '1.0',
                    'world': 'transverse', 'visibility': 'public', 'projects': [],
                    'source': {'type': 'authored', 'ref': f"github:{self.vendors[key]['repo']}"},
                    'requires': [{'kind': 'library', 'key': r} for r in requires],
                    'body': {'identity': {'version': 'a' * 12},
                             'install': {'vendor': self.vendors[key]}}}
        (self.corpus / 'manifests' / 'libraries' / f'{key}.json').write_text(
            json.dumps(manifest), encoding='utf-8')

    def test_the_plan_names_the_required_library_and_installs_nothing(self):
        res = install_library('fake_engine', apply=False)
        self.assertTrue(res['ok'], res)
        self.assertEqual(['fake_dep'], [r['key'] for r in res['plan']['requires']])
        self.assertTrue(res['plan']['requires'][0]['would_install'])
        self.assertFalse(self.vendor_root.exists())

    def test_the_required_library_is_installed_first_and_its_refusal_stops_everything(self):
        Library.objects.filter(key='fake_engine').update(is_allowed=True)
        refused = install_library('fake_engine', apply=True)
        self.assertFalse(refused['ok'])
        self.assertIn('fake_dep', refused['error'])
        self.assertFalse((self.vendor_root / 'fake_engine').exists(), "rien sans sa requise")
        Library.objects.filter(key='fake_dep').update(is_allowed=True)
        res = install_library('fake_engine', apply=True)
        self.assertTrue(res['ok'], res.get('error'))
        for key, vendor in self.vendors.items():
            self.assertEqual(vendor['commit'], _git(self.vendor_root / key, 'rev-parse', 'HEAD'))

    def test_the_engine_imports_the_code_of_its_required_clone(self):
        """Le geste commun `import_vendored` pose aussi le clone REQUIS, à son `import_root` ;
        `missing_packages` nomme un clone requis absent. Contre-épreuve : sans le `requires`, le
        moteur ne voit pas `depmod`."""
        import sys

        from wama.common.backends.base import BaseModelBackend
        from wama.common.manifests.builtin.library import required_vendor_roots

        class FakeEngine(BaseModelBackend):
            ENGINE, VENDORED, REQUIRED_PACKAGES = 'fake_engine', True, ()

        self.assertEqual([('fake_dep', self.vendor_root / 'fake_dep' / 'src')],
                         required_vendor_roots('fake_engine'))
        self.assertIn('vendor:fake_dep (manage.py install_library fake_dep)',
                      FakeEngine.missing_packages())
        Library.objects.update(is_allowed=True)
        self.assertTrue(install_library('fake_engine', apply=True)['ok'])
        self.assertEqual([], FakeEngine.missing_packages())
        saved = list(sys.path)
        self.addCleanup(lambda: (sys.path.__setitem__(slice(None), saved),
                                 [sys.modules.pop(m, None) for m in ('engine', 'depmod')]))
        self.assertEqual(7, FakeEngine.import_vendored('engine').VALUE)

        sys.path[:] = saved
        for name in ('engine', 'depmod'):
            sys.modules.pop(name, None)
        self._write_manifest('fake_engine')                      # contre-épreuve : plus de `requires`
        with self.assertRaises(ModuleNotFoundError):
            FakeEngine.import_vendored('engine')

    def test_a_circular_requires_stops_instead_of_looping(self):
        self._write_manifest('fake_dep', requires=['fake_engine'])
        Library.objects.update(is_allowed=True)
        res = install_library('fake_engine', apply=True)
        self.assertFalse(res['ok'])
        self.assertIn('circulaire', res['error'])


class VendoredEnginesCorpusTest(TestCase):
    """Les moteurs vendorisés sont DÉCLARÉS au corpus, et leur déclaration tient."""

    ENGINES = {'musetalk': 'musetalk_backend.py', 'codeformer': 'codeformer_backend.py',
               'triposr': 'image_to_3d_backend.py'}

    def test_each_vendored_engine_has_a_valid_authored_manifest(self):
        base = Path(settings.BASE_DIR)
        for key, backend in self.ENGINES.items():
            manifest = extract_library(key)
            self.assertIsNotNone(manifest, key)
            self.assertEqual(manifest['source']['type'], 'authored', key)
            self.assertEqual(validate_library_body(manifest['body']), [], key)
            vendor = manifest['body']['install']['vendor']
            if vendor.get('patch'):
                self.assertTrue((base / vendor['patch']).is_file(), vendor['patch'])
            source = (base / 'wama' / 'common' / 'backends' / backend).read_text(encoding='utf-8')
            self.assertIn(f"ENGINE = '{vendor['engine']}'", source, key)

    def test_each_vendored_backend_says_so_and_reports_a_missing_clone(self):
        from wama.common.backends.manager import backend_for_engine
        for key in self.ENGINES:
            cls = backend_for_engine(key)
            self.assertIsNotNone(cls, key)
            self.assertTrue(cls.VENDORED, key)
            marker = f'vendor:{key} (manage.py install_library {key})'
            with override_settings(BACKEND_VENDOR_DIR='/nowhere'):
                self.assertIn(marker, cls.missing_packages(), key)
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / key / '.git').mkdir(parents=True)
                with override_settings(BACKEND_VENDOR_DIR=tmp):
                    self.assertNotIn(marker, cls.missing_packages(), key)

    def test_a_backend_that_is_not_vendored_never_reports_a_clone(self):
        """Contre-épreuve : la vérification ne vaut que pour les moteurs DÉCLARÉS vendorisés."""
        from wama.common.backends.manager import backend_for_engine
        cls = backend_for_engine('talkinghead')
        self.assertFalse(cls.VENDORED)
        with override_settings(BACKEND_VENDOR_DIR='/nowhere'):
            self.assertFalse([m for m in cls.missing_packages() if m.startswith('vendor:')])

    def test_a_validated_vendor_library_extracts_before_reaching_the_corpus(self):
        """« Valider » projette au registre PUIS exporte au corpus : l'export d'une PREMIÈRE
        librairie vendorisée doit trouver son manifeste au registre (2026-10-01, YuE)."""
        key = 'never_in_corpus_engine'
        manifest = {'manifest_kind': 'library', 'key': key, 'name': 'Never', 'schema_version': '1.0',
                    'world': 'transverse', 'visibility': 'public', 'projects': [],
                    'body': {'identity': {'version': 'a' * 12, 'license': 'MIT'},
                             'install': {'vendor': _valid_vendor(engine=key)},
                             'dependencies': ['torch']}}
        self.assertIsNone(extract_library(key), 'contre-épreuve : rien avant la projection')
        write_back_library(manifest, apply=True)
        extracted = extract_library(key)
        self.assertEqual(extracted['body']['install']['vendor']['engine'], key)
        self.assertEqual(validate_library_body(extracted['body']), [])
        self.assertEqual(write_back_library(extracted)['would_change'], [],
                         "l'aller-retour registre → manifeste → registre ne change rien")

    def test_an_authored_pip_library_keeps_what_its_package_does_not_say(self):
        """2026-10-16 : un manifeste PyPI écrit à la main porte `constraints.no_deps` ; ré-extrait du
        paquet installé, il le perdait — l'export ne doit pas le remplacer."""
        for key in ('muscriptor', 'beat-this', 'rotary-embedding-torch'):
            manifest = extract_library(key)
            self.assertEqual('authored', manifest['source']['type'], key)
            self.assertIs(True, manifest['body']['constraints'].get('no_deps'), key)
            self.assertEqual([], validate_library_body(manifest['body']), key)

    def test_a_pip_library_still_goes_through_pip(self):
        """Contre-épreuve : la délégation ne capte que les librairies vendorisées."""
        Library.objects.create(key='some-pip-lib', name='x', pip_spec='some-pip-lib==1.0')
        with mock.patch('wama.model_manager.services.vendor_installer.install_vendor') as vendor, \
                mock.patch('wama.model_manager.services.model_installer.simuler_installation',
                           return_value={'ok': True}):
            res = install_library('some-pip-lib', apply=False)
        vendor.assert_not_called()
        self.assertEqual(res['plan']['spec'], 'some-pip-lib==1.0')
        json.dumps(res, default=str)
