"""
Poids publiés dans une VERSION GitHub (2026-10-07) — le pilote `github` de `install_from_spec`.

Il reproduit le pilote `yolo` (déjà un asset de version GitHub, mais verrouillé sur
`ultralytics/assets`) en l'adaptant : un dépôt quelconque, un tag EXACT, une empreinte épinglée.
Lot 1 : la primitive de téléchargement extraite de `pull_yolo_weights`, que les deux pilotes
partagent. Le réseau est simulé : aucun test ne télécharge.
"""
import hashlib
import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from wama.model_manager.services import model_installer as mi

PAYLOAD = b'onnx-weights' * 1000


class _FakeResponse:
    def __init__(self, body: bytes, fail: Exception = None):
        self.body, self.fail = body, fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.fail:
            raise self.fail

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.body), 4096):
            yield self.body[i:i + 4096]


class DownloadAssetTest(SimpleTestCase):
    """`download_asset` : un fichier complet et contrôlé, ou rien — jamais un partiel."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.target = os.path.join(self.dir, 'model.onnx')

    def _get(self, body=PAYLOAD, fail=None):
        return patch('requests.get', return_value=_FakeResponse(body, fail))

    def _leftovers(self):
        return sorted(os.listdir(self.dir))

    def test_a_complete_file_replaces_nothing_but_its_target(self):
        with self._get():
            res = mi.download_asset('https://example/x.onnx', self.target)
        self.assertTrue(res['ok'], res)
        self.assertEqual(['model.onnx'], self._leftovers())
        with open(self.target, 'rb') as fh:
            self.assertEqual(PAYLOAD, fh.read())
        # The digest computed along the stream is returned — a caller who MEASURES reads it here.
        self.assertEqual(hashlib.sha256(PAYLOAD).hexdigest(), res['sha256'])

    def test_the_pinned_digest_is_checked_and_accepted(self):
        with self._get():
            res = mi.download_asset('https://example/x.onnx', self.target,
                                    sha256=hashlib.sha256(PAYLOAD).hexdigest().upper())
        self.assertTrue(res['ok'], res)

    def test_a_different_digest_rejects_the_file_and_leaves_nothing(self):
        with self._get():
            res = mi.download_asset('https://example/x.onnx', self.target, sha256='0' * 64)
        self.assertFalse(res['ok'])
        self.assertIn('empreinte', res['error'])
        self.assertEqual([], self._leftovers())

    def test_an_error_page_below_the_floor_is_refused(self):
        with self._get(body=b'<html>Not Found</html>'):
            res = mi.download_asset('https://example/x.pt', self.target, min_bytes=1_000_000)
        self.assertFalse(res['ok'])
        self.assertIn('suspect', res['error'])
        self.assertEqual([], self._leftovers())

    def test_a_network_failure_leaves_no_partial(self):
        with self._get(fail=OSError('connection reset')):
            res = mi.download_asset('https://example/x.onnx', self.target)
        self.assertFalse(res['ok'])
        self.assertIn('connection reset', res['error'])
        self.assertEqual([], self._leftovers())

    def test_the_proxies_reach_the_request(self):
        with self._get() as get:
            mi.download_asset('https://example/x.onnx', self.target, proxies={'https': 'p'})
        self.assertEqual({'https': 'p'}, get.call_args.kwargs['proxies'])


#: Un descripteur réel : SPAN (Phhofm/models), relevé sur l'API GitHub le 2026-10-07.
SPAN = {
    'kind': 'github', 'ref': 'Phhofm/models:4xNomosUni_span_multijpg',
    'asset': '4xNomosUni_span_multijpg_fp32_opset17.onnx',
    'sha256': 'a' * 64, 'category': 'upscaling',
}


class GithubSpecLockTest(SimpleTestCase):
    """`github_spec_error` : les verrous de la voie vendor, transposés à une version."""

    def test_a_pinned_release_asset_passes(self):
        self.assertIsNone(mi.github_spec_error(SPAN))

    def test_a_release_key_is_a_valid_manifest_key(self):
        """Le tag entre dans la clé (`github:owner/repo:tag`, le précédent Ollama `nom:tag`) : la
        clé doit passer le validateur des manifestes — vécu au 1er scout réel avec « @ »."""
        from wama.common.manifests.envelope import _is_key
        self.assertTrue(_is_key('github:Phhofm/models:4xNomosUni_span_multijpg'))
        self.assertIn('tag refusé', mi.github_spec_error({**SPAN, 'ref': 'Phhofm/models:v1+x'}))

    def test_what_is_refused_before_any_network(self):
        for field, value, motive in (
                ('ref', 'https://github.com/Phhofm/models:x', 'ref refusé'),
                ('ref', 'Phhofm/models', 'ref refusé'),            # pas de version
                ('ref', 'Phhofm:x', 'ref refusé'),
                ('ref', 'Phhofm/models:latest', 'tag refusé'),     # « latest » bouge
                ('ref', 'Phhofm/models:a/b', 'tag refusé'),
                ('asset', '../x.onnx', 'asset refusé'),
                ('asset', 'dir/x.onnx', 'asset refusé'),
                ('asset', '', 'asset refusé'),
                ('sha256', '', 'sha256'),
                ('sha256', 'sha256:' + 'a' * 64, 'sha256'),        # le préfixe de l'API se retire avant
                ('category', '', 'category')):
            with self.subTest(field=field, value=value):
                self.assertIn(motive, mi.github_spec_error({**SPAN, field: value}) or '')


class PullGithubAssetTest(SimpleTestCase):
    """Le comportement de `pull_yolo_weights`, adapté : dossier canonique calqué sur HF,
    idempotence par EMPREINTE, adresse dérivée de la source déclarée."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.settings_cm = self.settings(AI_MODELS_DIR=self.root)
        self.settings_cm.enable()
        self.addCleanup(self.settings_cm.disable)
        self.release = os.path.join(self.root, 'models', 'upscaling', '4xNomosUni_span_multijpg',
                                    'github--Phhofm--models', '4xNomosUni_span_multijpg')

    def test_the_layout_mirrors_huggingface(self):
        res = mi.pull_github_asset(SPAN, dry_run=True)
        self.assertEqual(os.path.join(self.release, SPAN['asset']), res['target'])
        with_family = mi.pull_github_asset({**SPAN, 'family': 'span'}, dry_run=True)
        self.assertIn(os.path.join('upscaling', 'span', 'github--Phhofm--models'),
                      with_family['target'])

    def test_the_download_is_the_common_one_with_the_pinned_digest(self):
        from wama.common.external_sources import base_url
        with patch.object(mi, 'download_asset', return_value={'ok': True}) as dl:
            mi.pull_github_asset(SPAN)
        url, target = dl.call_args.args
        self.assertEqual(f"{base_url('github')}/Phhofm/models/releases/download/"
                         f"4xNomosUni_span_multijpg/{SPAN['asset']}", url)
        self.assertEqual(os.path.join(self.release, SPAN['asset']), target)
        self.assertEqual(SPAN['sha256'], dl.call_args.kwargs['sha256'])
        self.assertIn('proxies', dl.call_args.kwargs)

    def test_a_refused_spec_never_reaches_the_network(self):
        with patch.object(mi, 'download_asset') as dl:
            res = mi.pull_github_asset({**SPAN, 'ref': 'Phhofm/models:latest'})
        self.assertFalse(res['ok'])
        dl.assert_not_called()

    def _place(self, body: bytes) -> str:
        os.makedirs(self.release)
        path = os.path.join(self.release, SPAN['asset'])
        with open(path, 'wb') as fh:
            fh.write(body)
        return path

    def test_an_installed_asset_with_the_pinned_digest_is_already_there(self):
        self._place(PAYLOAD)
        spec = {**SPAN, 'sha256': hashlib.sha256(PAYLOAD).hexdigest()}
        with patch.object(mi, 'download_asset') as dl:
            res = mi.pull_github_asset(spec)
        self.assertTrue(res.get('already'), res)
        dl.assert_not_called()

    def test_a_different_file_in_place_is_said_and_left_untouched(self):
        path = self._place(b'something else')
        with patch.object(mi, 'download_asset') as dl:
            res = mi.pull_github_asset(SPAN)
        self.assertFalse(res['ok'])
        self.assertIn('AUTRE empreinte', res['error'])
        dl.assert_not_called()
        with open(path, 'rb') as fh:
            self.assertEqual(b'something else', fh.read())


class TheSingleEntryDispatchesGithubTest(SimpleTestCase):
    """`install_from_spec` et ses jumelles dispatchent `github` comme les autres pilotes."""

    def test_install_from_spec_calls_the_driver_then_records_provenance(self):
        with patch.object(mi, 'pull_github_asset', return_value={'ok': True}) as pull, \
                patch.object(mi, 'record_provenance', side_effect=lambda s, r: r) as rec:
            res = mi.install_from_spec(SPAN)
        self.assertTrue(res['ok'])
        pull.assert_called_once_with(SPAN)
        rec.assert_called_once()

    def test_the_weight_is_asked_to_the_asset_url(self):
        with patch.object(mi, '_asset_gb', return_value=0.002) as gb:
            self.assertEqual(0.002, mi.weight_for_spec(SPAN))
        self.assertTrue(gb.call_args.args[0].endswith(f"/releases/download/"
                                                       f"4xNomosUni_span_multijpg/{SPAN['asset']}"))
        with patch.object(mi, '_asset_gb') as gb:
            self.assertIsNone(mi.weight_for_spec({**SPAN, 'sha256': ''}))
        gb.assert_not_called()

    def test_an_asset_is_one_component(self):
        with patch.object(mi, '_asset_gb', return_value=0.002):
            comps = mi.components_for_spec(SPAN)
        self.assertEqual({'model': 0.002}, comps['components'])
        self.assertEqual('asset', comps['source'])

    def test_the_identity_names_the_release_page(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.provenance import identity_for_spec
        ident = identity_for_spec({**SPAN, 'license': 'CC-BY-4.0'})
        self.assertEqual('github:Phhofm/models/releases/tag/4xNomosUni_span_multijpg',
                         ident['platform_ref'])
        self.assertEqual('CC-BY-4.0', ident['license'])
        self.assertEqual('Phhofm', ident['author'], 'the publisher is the repository owner')
        self.assertEqual('https://github.com/Phhofm/models/releases/tag/4xNomosUni_span_multijpg',
                         AIModel(platform_ref=ident['platform_ref']).platform_url)


def _installed_release(root, category='upscaling', family='4xNomosUni_span_multijpg',
                       repo='Phhofm--models', tag='4xNomosUni_span_multijpg',
                       asset='4xNomosUni_span_multijpg_fp32_opset17.onnx', partial=False):
    """Une version GitHub installée sur disque, telle que `pull_github_asset` la dépose."""
    from pathlib import Path
    release = Path(root) / 'models' / category / family / f'github--{repo}' / tag
    release.mkdir(parents=True)
    (release / asset).write_bytes(b'0' * 4096)
    if partial:
        (release / 'other.onnx.part').write_bytes(b'0' * 10)
    return release


class GenericScanCataloguesAGithubReleaseTest(SimpleTestCase):
    """Le balayage générique, même passe que les snapshots HF : une version GitHub installée est
    CATALOGUÉE par des faits seuls — ni tâche ni échelle devinées."""

    def _scan(self, root):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        with self.settings(AI_MODELS_DIR=root):
            registry._discover_installed_hf_snapshots()
        return registry._models

    def test_an_installed_release_is_catalogued_by_its_version(self):
        with tempfile.TemporaryDirectory() as root:
            release = _installed_release(root)
            models = self._scan(root)
        key = 'github:Phhofm/models:4xNomosUni_span_multijpg'
        self.assertIn(key, models)
        m = models[key]
        self.assertEqual('github', m.source.value)
        self.assertEqual('upscaling', m.model_type.value)
        self.assertEqual('onnx', m.format)
        self.assertTrue(m.is_downloaded)
        self.assertEqual(str(release), m.extra_info['path'], 'the RELEASE folder, not the file')
        self.assertFalse(m.capabilities, 'nothing guessed: task and scale come from the spec')
        self.assertFalse(m.backend_ref, 'catalogued is not usable: no backend invented')

    def test_an_interrupted_download_is_not_downloaded(self):
        with tempfile.TemporaryDirectory() as root:
            _installed_release(root, partial=True)
            m = self._scan(root)['github:Phhofm/models:4xNomosUni_span_multijpg']
        self.assertFalse(m.is_downloaded)
        self.assertTrue(m.extra_info.get('incomplete'))

    def test_a_declared_family_stays_its_apps_like_for_huggingface(self):
        with tempfile.TemporaryDirectory() as root:
            release = _installed_release(root, family='declared-family')
            with patch('wama.model_manager.services.model_registry.ModelRegistry'
                       '._familles_model_paths', return_value={release.parent.parent.resolve()}):
                models = self._scan(root)
        self.assertFalse([k for k in models if k.startswith('github:')])

    def test_the_huggingface_branch_keeps_its_facts(self):
        """Les deux calculs rendus communs (format, VRAM) rendent la même chose pour un snapshot."""
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            snap = Path(root) / 'models' / 'upscaling' / 'sr' / 'models--org--sr'
            (snap / 'snapshots' / 'rev0').mkdir(parents=True)
            (snap / 'snapshots' / 'rev0' / 'model.onnx').write_bytes(b'0')
            (snap / 'snapshots' / 'rev0' / 'voices.bin').write_bytes(b'0')
            (snap / 'blobs').mkdir()
            (snap / 'blobs' / 'abc').write_bytes(b'0' * 600_000)
            m = self._scan(root)['huggingface:org/sr']
        self.assertEqual('onnx', m.format, 'onnx before bin (inference-first)')
        self.assertEqual(0.1, m.vram_gb, 'the 0.1 floor')


class AnInstalledReleaseResolvesLikeASnapshotTest(TestCase):
    """De la ligne au fichier : `weights_dir_of` rend le dossier de la version (désinstallable),
    `component_paths` y trouve le composant déclaré — le chemin de Swin2SR, sans rien de neuf."""

    def test_weights_dir_and_component_path(self):
        from wama.common.utils.model_components import component_paths
        from wama.model_manager.models import AIModel
        with tempfile.TemporaryDirectory() as root, self.settings(AI_MODELS_DIR=root):
            release = _installed_release(root)
            key = 'github:Phhofm/models:4xNomosUni_span_multijpg'
            row = AIModel.objects.create(
                model_key=key, name='4xNomosUni_span_multijpg', model_type='upscaling',
                source='github', is_downloaded=True, extra_info={'path': str(release)},
                composition={'components': [{'role': 'model', 'pattern': '*.onnx'}],
                             'runtime': {'engine': 'onnxruntime'}})
            self.assertEqual(release, mi.weights_dir_of(row))
            self.assertEqual(release / '4xNomosUni_span_multijpg_fp32_opset17.onnx',
                             component_paths(key)['model'])

    def test_without_engine_it_is_greyed_like_a_huggingface_snapshot(self):
        from types import SimpleNamespace

        from wama.common.backends.manager import backend_missing
        bare = dict(backend_ref='', composition={}, is_proposed=False, execution='local')
        self.assertIn('aucune route', backend_missing(SimpleNamespace(source='github', **bare)))
        self.assertIn('aucune route',
                      backend_missing(SimpleNamespace(source='huggingface', **bare)))

    def test_it_uninstalls_its_release_folder_only(self):
        from wama.model_manager.models import AIModel
        with tempfile.TemporaryDirectory() as root, self.settings(AI_MODELS_DIR=root):
            release = _installed_release(root)
            AIModel.objects.create(
                model_key='github:Phhofm/models:4xNomosUni_span_multijpg',
                name='4xNomosUni_span_multijpg', model_type='upscaling', source='github',
                is_downloaded=True, extra_info={'path': str(release)})
            res = mi.uninstall_model('github:Phhofm/models:4xNomosUni_span_multijpg')
            self.assertTrue(res['ok'], res)
            self.assertFalse(release.exists())
            self.assertTrue(release.parent.exists(), 'only the release goes, not its siblings')
        self.assertFalse(AIModel.objects.get(
            model_key='github:Phhofm/models:4xNomosUni_span_multijpg').is_downloaded)


#: La version SPAN telle que l'API la rend (champs utiles) — SANS `digest`, comme en vrai :
#: mesuré le 2026-10-07, 7 versions sur 100 de `Phhofm/models` seulement en publient.
SPAN_RELEASE = {
    'tag_name': '4xNomosUni_span_multijpg', 'published_at': '2024-04-15T00:00:00Z',
    'body': 'Name: 4xNomosUni_span_multijpg\r\nLicense: CC BY 4.0\r\nNetwork: SPAN\r\nScale: 4',
    'assets': [{'name': '4xNomosUni_span_multijpg.pth', 'size': 4546346, 'digest': None},
               {'name': '4xNomosUni_span_multijpg_fp32_opset17.onnx', 'size': len(PAYLOAD),
                'digest': None}],
}


def _span_manifest(**identity):
    from wama.model_manager.services.model_installer import github_platform_ref
    return {'manifest_kind': 'model', 'key': 'github:Phhofm/models:4xNomosUni_span_multijpg',
            'name': '4xNomosUni_span_multijpg',
            'body': {'identity': {'source': 'github', 'model_type': 'upscaling',
                                  'license': 'CC BY 4.0',
                                  'platform_ref': github_platform_ref(SPAN['ref']), **identity},
                     'capabilities': {'task': 'upscale', 'scale': 4},
                     'composition': {'components': [{'role': 'model', 'pattern': SPAN['asset']}],
                                     'runtime': {'engine': 'onnxruntime'}},
                     'resources': {'disk_gb': 0.0}}}


class ReadingAReleaseTest(SimpleTestCase):
    """La version lue sur l'API (source `github_api`), sa licence, son empreinte."""

    def test_absent_is_a_fact_unreachable_is_a_failure(self):
        from wama.model_manager.services import prospector as p

        class _R:
            def __init__(self, code):
                self.status_code = code

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise OSError(self.status_code)

            def json(self):
                return SPAN_RELEASE

        with patch('requests.get', return_value=_R(404)):
            self.assertEqual({}, p.github_release(SPAN['ref']))
        with patch('requests.get', side_effect=OSError('proxy')):
            self.assertIsNone(p.github_release(SPAN['ref']))
        with patch('requests.get', return_value=_R(200)) as get:
            self.assertEqual(SPAN_RELEASE, p.github_release(SPAN['ref']))
        self.assertTrue(get.call_args.args[0].endswith(
            '/repos/Phhofm/models/releases/tags/4xNomosUni_span_multijpg'))

    def test_the_token_is_the_registry_key_and_optional(self):
        """The `github_api` source's key (Sources page, then `.env`) — never sent when unset."""
        from wama.model_manager.services import prospector as p
        response = type('R', (), {'status_code': 404, 'raise_for_status': lambda s: None})()
        for key, expected in (('tok', 'Bearer tok'), ('', None)):
            with self.subTest(key=key), \
                    patch('wama.common.external_sources.api_key', return_value=key) as read, \
                    patch('requests.get', return_value=response) as get:
                p.github_release(SPAN['ref'])
            read.assert_called_with('github_api')
            self.assertEqual(expected, get.call_args.kwargs['headers'].get('Authorization'))

    def test_the_licence_is_the_one_the_release_states(self):
        from wama.model_manager.services.prospector import github_release_license
        self.assertEqual('CC BY 4.0', github_release_license(SPAN_RELEASE))
        self.assertEqual('CC BY 4.0', github_release_license(
            {'body': '**License:** [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)'}))
        self.assertEqual('', github_release_license({'body': 'Scale: 4'}))

    def test_the_scale_is_the_one_the_release_states_never_the_name(self):
        from wama.model_manager.services.prospector import github_release_scale
        self.assertEqual(4, github_release_scale(SPAN_RELEASE))
        self.assertEqual(2, github_release_scale({'body': '**Scale:** 2x'}))
        # La version de GaterV3, telle que publiée (signe ×, espaces de fin de ligne Markdown).
        self.assertEqual(1, github_release_scale({'body': '# t\n\n**Scale:** 1×  \n**Network'}))
        self.assertIsNone(github_release_scale({'tag_name': '4xNomos', 'body': 'Network: SPAN'}),
                          'a « 4x » name is a convention, not a declaration')

    def test_a_published_digest_is_read_not_measured(self):
        from wama.model_manager.services import prospector as p
        release = {**SPAN_RELEASE, 'assets': [{**SPAN_RELEASE['assets'][1],
                                               'digest': 'sha256:' + 'B' * 64}]}
        with patch.object(mi, 'download_asset') as dl:
            pinned = p.pinned_github_asset(SPAN['ref'], SPAN['asset'], release)
        self.assertEqual({'asset': SPAN['asset'], 'size': len(PAYLOAD), 'sha256': 'b' * 64,
                          'measured': False}, pinned)
        dl.assert_not_called()

    def test_without_a_published_digest_it_is_measured(self):
        from wama.model_manager.services import prospector as p

        def fake_download(url, target, **kw):
            with open(target, 'wb') as fh:
                fh.write(PAYLOAD)
            return {'ok': True, 'sha256': hashlib.sha256(PAYLOAD).hexdigest()}

        with patch.object(mi, 'download_asset', side_effect=fake_download):
            pinned = p.pinned_github_asset(SPAN['ref'], SPAN['asset'], SPAN_RELEASE)
        self.assertEqual(hashlib.sha256(PAYLOAD).hexdigest(), pinned['sha256'])
        self.assertTrue(pinned['measured'])

    def test_an_asset_the_release_does_not_publish_is_said(self):
        from wama.model_manager.services.prospector import pinned_github_asset
        res = pinned_github_asset(SPAN['ref'], 'other.onnx', SPAN_RELEASE)
        self.assertIn('absent', res['error'])


class SeedingAGithubCandidateTest(TestCase):
    """Le scout sème une VERSION comme un dépôt HF : un candidat porteur de son spec, que
    `request_install` installe par la route commune."""

    def _pinned(self):
        return patch('wama.model_manager.services.prospector.pinned_github_asset',
                     return_value={'asset': SPAN['asset'], 'size': 1717409,   # SPAN réel
                                   'sha256': 'c' * 64, 'measured': True})

    def test_the_candidate_carries_a_pinned_github_spec(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.prospector import seed_candidate_from_manifest
        with self._pinned():
            res = seed_candidate_from_manifest(_span_manifest())
        self.assertTrue(res['ok'], res)
        cand = AIModel.objects.get(model_key=res['model_key'])
        self.assertTrue(res['model_key'].endswith('github:Phhofm/models:4xNomosUni_span_multijpg'))
        self.assertEqual('github', cand.source)
        self.assertTrue(cand.is_proposed)
        spec = cand.extra_info['prospect']['spec']
        self.assertEqual({'kind': 'github', 'ref': SPAN['ref'], 'asset': SPAN['asset'],
                          'sha256': 'c' * 64, 'category': 'upscaling', 'task': 'upscale',
                          'license': 'CC BY 4.0'},
                         {k: spec[k] for k in ('kind', 'ref', 'asset', 'sha256', 'category',
                                               'task', 'license')})
        self.assertEqual(4, spec['capabilities']['scale'], 'the judged scale travels')
        self.assertIsNone(mi.github_spec_error(spec), 'the seeded spec passes the driver lock')
        self.assertEqual('https://github.com/Phhofm/models/releases/tag/4xNomosUni_span_multijpg',
                         cand.platform_url)
        self.assertEqual(0.0016, cand.disk_gb, 'a 1.7 MB asset is not « unknown »')

    def test_a_pattern_is_not_a_file(self):
        from wama.model_manager.services.prospector import seed_candidate_from_manifest
        manifest = _span_manifest()
        manifest['body']['composition']['components'][0]['pattern'] = '*.onnx'
        with self._pinned():
            res = seed_candidate_from_manifest(manifest)
        self.assertFalse(res['ok'])
        self.assertIn('UN fichier', res['error'])

    def test_request_install_dispatches_it_like_any_candidate(self):
        from wama.model_manager.services.prospector import seed_candidate_from_manifest
        with self._pinned():
            key = seed_candidate_from_manifest(_span_manifest())['model_key']
        with patch.object(mi, 'disk_space_guard', return_value=None), \
                patch.object(mi, 'dispatch_install',
                             return_value=type('T', (), {'id': 't1'})()) as dispatch:
            res = mi.request_install(key)
        self.assertTrue(res.get('started'), res)
        self.assertEqual(key, dispatch.call_args.args[1].model_key)


class TheScoutReadsAReleaseTest(SimpleTestCase):
    """`run_scout.github_skeleton` : les FAITS de la version, zéro LLM."""

    def _scout(self):
        import importlib.util
        from pathlib import Path

        from django.conf import settings
        path = Path(settings.BASE_DIR) / 'wama-dev-ai' / 'run_scout.py'
        spec = importlib.util.spec_from_file_location('run_scout_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_skeleton_names_the_release_and_the_retained_file(self):
        scout = self._scout()
        with patch('wama.model_manager.services.prospector.github_release',
                   return_value=SPAN_RELEASE):
            base, inventory, card = scout.github_skeleton(SPAN['ref'], SPAN['asset'])
        ident = base['body']['identity']
        self.assertEqual('github:Phhofm/models:4xNomosUni_span_multijpg', base['key'])
        self.assertEqual(('github', 'CC BY 4.0', 'Phhofm'),
                         (ident['source'], ident['license'], ident['author']))
        self.assertEqual([{'role': 'model', 'pattern': SPAN['asset'], 'format': 'onnx'}],
                         base['body']['composition']['components'])
        self.assertIn('4xNomosUni_span_multijpg.pth', inventory, 'the alternatives are shown')
        self.assertEqual({'scale': 4}, base['body']['capabilities'], 'the declared scale is a fact')
        self.assertIn('Scale: 4', card)

    def test_several_weight_files_and_no_choice_stops(self):
        scout = self._scout()
        with patch('wama.model_manager.services.prospector.github_release',
                   return_value=SPAN_RELEASE), self.assertRaises(SystemExit) as stop:
            scout.github_skeleton(SPAN['ref'])
        self.assertIn('--asset', str(stop.exception))


class TheBackendReceivesItsOwnIdentifierTest(SimpleTestCase):
    """`model_keys.backend_model_id` : la règle de `backend_for_model` (dernier segment), commune
    depuis le 2026-10-07 — et c'est elle qu'un constructeur de backend reçoit."""

    RELEASE_KEY = 'github:Phhofm/models:4xNomosUni_span_multijpg'

    def test_it_is_model_id_for_every_two_segment_key(self):
        from wama.common.utils.model_keys import backend_model_id, model_id
        for key in ('enhancer:BSRGANx4', 'BSRGANx4', '',
                    'huggingface:onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX'):
            with self.subTest(key=key):
                self.assertEqual(model_id(key), backend_model_id(key))

    def test_a_release_key_gives_its_tag(self):
        from wama.common.services.backend_proposals import model_id_of
        from wama.common.utils.model_keys import backend_model_id, model_id
        self.assertEqual('4xNomosUni_span_multijpg', backend_model_id(self.RELEASE_KEY))
        self.assertEqual('Phhofm/models:4xNomosUni_span_multijpg', model_id(self.RELEASE_KEY))
        self.assertEqual(backend_model_id(self.RELEASE_KEY), model_id_of(self.RELEASE_KEY),
                         'the role `backend` and the constructors use the same rule')

    def _built_with(self, call):
        built = {}

        class _Backend:
            def __init__(self, model_name, **kw):
                built['model_name'] = model_name

        with patch('wama.common.backends.manager.backend_for_key', return_value=_Backend):
            call()
        return built.get('model_name')

    def test_the_enhancer_builds_the_upscaler_with_the_tag(self):
        from wama.enhancer.backends import media_backend
        self.assertEqual('4xNomosUni_span_multijpg',
                         self._built_with(lambda: media_backend._upscaler_for(self.RELEASE_KEY)))
        self.assertEqual('BSRGANx4',
                         self._built_with(lambda: media_backend._upscaler_for('BSRGANx4')))

    def test_the_output_upscale_builds_it_with_the_tag(self):
        from wama.common.utils import output_formats
        seen = {}

        def fake_upscale(path, tmp, model_name, **kw):
            seen['model_name'] = model_name
            with open(tmp, 'wb'):
                pass
            return (8, 8)

        with tempfile.TemporaryDirectory() as root:
            image = os.path.join(root, 'x.png')
            open(image, 'wb').close()
            with patch('wama.common.utils.auto_model.candidates_with',
                       return_value=[self.RELEASE_KEY]), \
                    patch('wama.common.utils.auto_model.resolve_model_choice',
                          return_value=self.RELEASE_KEY), \
                    patch('wama.common.backends.manager.backend_for_key', return_value=object), \
                    patch('wama.common.backends.ai_upscaler.upscale_image_file',
                          side_effect=fake_upscale):
                output_formats.upscale_output_image(image, 4)
        self.assertEqual('4xNomosUni_span_multijpg', seen['model_name'])


#: Fichiers déclarés par une app (pilote `files`, 2026-10-11) — chacun nomme son origine. Les
#: trois formes : une version GitHub (CodeFormer), un dépôt du Hub figé à un commit, une adresse
#: fixe sous une source déclarée « Outillage et poids » (MuseTalk lit les trois).
COMMIT = '2bcb936e2fddb4d86db4c62fd45b387d0c061571'
DECLARED = [
    {'path': 'CodeFormer/codeformer.pth', 'size': 1000, 'sha256': hashlib.sha256(PAYLOAD).hexdigest(),
     'origin': {'source': 'github', 'release': 'sczhou/CodeFormer:v0.1.0',
                'file': 'codeformer.pth'}},
    {'path': 'facelib/parsing_parsenet.pth', 'size': 2000, 'sha256': 'd' * 64,
     'origin': {'source': 'huggingface', 'repo': 'TMElyralab/MuseTalk', 'revision': COMMIT,
                'file': 'musetalkV15/unet.pth'}},
    {'path': 'face-parse/resnet18.pth', 'size': 3000, 'sha256': 'e' * 64,
     'origin': {'source': 'pytorch_download', 'file': 'models/resnet18-5c106cde.pth'}},
]


class DeclaredFilesTest(TestCase):
    """Une ligne d'app qui DÉCLARE ses fichiers : installable par le catalogue, posée sous SON
    dossier, chaque fichier tiré de SON origine déclarée, mêmes verrous et même téléchargement."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.settings_cm = self.settings(AI_MODELS_DIR=self.root)
        self.settings_cm.enable()
        self.addCleanup(self.settings_cm.disable)
        self.app_dir = os.path.join(self.root, 'models', 'lipsync', 'codeformer')

    def _row(self, **extra):
        from wama.model_manager.models import AIModel
        return AIModel(model_key='avatarizer:codeformer', name='CodeFormer', source='avatarizer',
                       hf_id='sczhou/CodeFormer', extra_info=extra)

    def _spec(self, **over):
        return {'kind': 'files', 'ref': 'avatarizer:codeformer', 'files': DECLARED,
                'target_dir': self.app_dir, **over}

    def _with_origin(self, **origin):
        return [{**DECLARED[0], 'origin': origin}]

    def test_the_catalogue_row_derives_a_files_spec_before_its_hf_id(self):
        spec = mi.spec_for_catalog_row(self._row(install_dir=self.app_dir,
                                                 declared_files=DECLARED))
        self.assertEqual('files', spec['kind'], 'the declared files win over the hf_id')
        self.assertEqual(('avatarizer:codeformer', DECLARED, self.app_dir),
                         (spec['ref'], spec['files'], spec['target_dir']))
        self.assertIsNone(mi.declared_files_error(spec))

    def test_counter_proof_outside_the_models_root_is_not_installable(self):
        self.assertIsNone(mi.spec_for_catalog_row(
            self._row(install_dir='/elsewhere', declared_files=DECLARED)))

    def test_counter_proof_a_hf_app_row_keeps_its_hf_spec(self):
        spec = mi.spec_for_catalog_row(self._row(install_dir=self.app_dir))
        self.assertEqual(('hf', 'sczhou/CodeFormer'), (spec['kind'], spec['ref']))

    def test_the_lock_rejects_a_path_that_climbs_a_missing_digest_or_size(self):
        good = DECLARED[0]
        for files, motive in (([{**good, 'path': '../x.pth'}], 'fichier refusé'),
                              ([{**good, 'path': '/abs.pth'}], 'fichier refusé'),
                              ([{**good, 'sha256': ''}], 'sha256'),
                              ([{**good, 'size': None}], 'size manquante'),
                              ([{**good, 'size': 0}], 'size manquante'),
                              ([], 'liste non vide')):
            with self.subTest(files=files):
                self.assertIn(motive, mi.declared_files_error(self._spec(files=files)) or '')
        self.assertIn('target_dir', mi.declared_files_error(self._spec(target_dir='')))

    def test_an_origin_is_frozen_and_comes_from_a_declared_source(self):
        hf = {'source': 'huggingface', 'repo': 'TMElyralab/MuseTalk', 'revision': COMMIT,
              'file': 'musetalkV15/unet.pth'}
        cases = (
            ({**hf, 'revision': 'main'}, 'COMMIT exact'),
            ({**hf, 'revision': COMMIT[:12]}, 'COMMIT exact'),
            ({**hf, 'repo': 'https://evil/x'}, 'dépôt refusé'),
            ({**hf, 'file': '../escape'}, 'file refusé'),
            ({'source': 'github', 'release': 'sczhou/CodeFormer:latest', 'file': 'a.pth'},
             'tag refusé'),
            ({'source': 'github', 'release': 'sczhou/CodeFormer:v0.1.0', 'file': 'a/b.pth'},
             'asset refusé'),
            ({'source': 'nowhere', 'file': 'a.pth'}, 'source refusée'),
            # Une source déclarée, mais pas un hébergeur de poids : une API de LLM n'en sert pas.
            ({'source': 'albert', 'file': 'a.pth'}, 'source refusée'),
            ({'source': 'pytorch_download', 'file': '../../etc/passwd'}, 'file refusé'),
            (None, 'source refusée'),
        )
        for origin, motive in cases:
            with self.subTest(origin=origin):
                self.assertIn(motive, mi.declared_files_error(
                    self._spec(files=[{**DECLARED[0], 'origin': origin}])) or '')
        for origin in (hf, DECLARED[0]['origin'], DECLARED[2]['origin']):
            with self.subTest(accepted=origin):
                self.assertIsNone(mi.declared_files_error(self._spec(files=self._with_origin(
                    **origin))))

    def test_each_address_derives_from_its_declared_source(self):
        from wama.common.external_sources import base_url
        self.assertEqual(
            [f"{base_url('github')}/sczhou/CodeFormer/releases/download/v0.1.0/codeformer.pth",
             f"{base_url('huggingface')}/TMElyralab/MuseTalk/resolve/{COMMIT}/"
             "musetalkV15/unet.pth",
             f"{base_url('pytorch_download')}/models/resnet18-5c106cde.pth"],
            [mi.declared_file_url(f['origin']) for f in DECLARED])

    def test_files_land_under_the_app_folder_each_through_its_source(self):
        with patch.object(mi, 'download_asset', return_value={'ok': True}) as dl, \
                patch('wama.common.external_sources.proxies_for',
                      side_effect=lambda key: {'via': key}):
            res = mi.pull_declared_files(self._spec())
        self.assertTrue(res['ok'], res)
        calls = {c.args[1]: c for c in dl.call_args_list}
        target = os.path.join(self.app_dir, 'face-parse', 'resnet18.pth')
        self.assertTrue(calls[target].args[0].endswith('/models/resnet18-5c106cde.pth'))
        self.assertEqual('e' * 64, calls[target].kwargs['sha256'])
        self.assertEqual({'via': 'pytorch_download'}, calls[target].kwargs['proxies'],
                         "the proxy follows the file's own source")
        # La provenance de CHAQUE fichier est rendue (donc journalisée).
        self.assertEqual({(d['path'], d['action']) for d in res['files']},
                         {(os.path.join(self.app_dir, *f['path'].split('/')), 'downloaded')
                          for f in DECLARED})
        self.assertTrue(all(d['url'] and d['sha256'] for d in res['files']))

    def test_the_hub_token_goes_to_the_hub_files_only(self):
        """2026-10-16, MuScriptor : a gated Hub repository answers 401 without the token — and a
        secret is sent only where it serves, never to GitHub or an authors' server."""
        with patch.object(mi, 'download_asset', return_value={'ok': True}) as dl:
            mi.pull_declared_files(self._spec(), token='hf_secret')
        sent = [c.kwargs['headers'] for c in dl.call_args_list]
        self.assertEqual([None, {'Authorization': 'Bearer hf_secret'}, None], sent,
                         'github, huggingface, pytorch_download — in the declared order')
        with patch.object(mi, 'download_asset', return_value={'ok': True}) as dl:
            mi.pull_declared_files(self._spec())
        self.assertEqual([None, None, None], [c.kwargs['headers'] for c in dl.call_args_list],
                         'no token, no header')

    def test_install_from_spec_hands_the_token_to_the_files_driver(self):
        with patch.object(mi, 'pull_declared_files', return_value={'ok': True}) as files, \
                patch.object(mi, 'record_provenance', side_effect=lambda s, r: r):
            mi.install_from_spec(self._spec(), token='hf_secret')
        self.assertEqual('hf_secret', files.call_args.kwargs['token'])

    def test_a_file_in_place_is_kept_and_a_different_one_stops_everything(self):
        good = os.path.join(self.app_dir, 'CodeFormer', 'codeformer.pth')
        os.makedirs(os.path.dirname(good))
        with open(good, 'wb') as fh:
            fh.write(PAYLOAD)
        with patch.object(mi, 'download_asset', return_value={'ok': True}) as dl:
            res = mi.pull_declared_files(self._spec())
        self.assertEqual([good], res['kept'])
        self.assertEqual(2, dl.call_count, 'only the missing files are downloaded')
        with open(good, 'wb') as fh:
            fh.write(b'other')
        with patch.object(mi, 'download_asset') as dl:
            res = mi.pull_declared_files(self._spec())
        self.assertFalse(res['ok'])
        self.assertIn('AUTRE empreinte', res['error'])
        dl.assert_not_called()

    def test_a_failed_file_stops_the_install_and_says_what_was_done(self):
        with patch.object(mi, 'download_asset',
                          side_effect=[{'ok': True}, {'ok': False, 'error': 'empreinte'}]) as dl:
            res = mi.pull_declared_files(self._spec())
        self.assertFalse(res['ok'])
        self.assertEqual(2, dl.call_count, 'nothing is tried after the failing file')
        self.assertEqual(1, len(res['files']))

    def test_a_target_outside_the_models_root_is_refused(self):
        with patch.object(mi, 'download_asset') as dl:
            res = mi.pull_declared_files(self._spec(target_dir=tempfile.mkdtemp()))
        self.assertFalse(res['ok'])
        dl.assert_not_called()

    def test_the_weight_is_the_declared_sizes(self):
        self.assertEqual(round(6000 / 1024 ** 3, 3), mi.weight_for_spec(self._spec()))
        self.assertIsNone(mi.weight_for_spec(self._spec(files=[
            {**DECLARED[0], 'size': None}])), 'an undeclared size is never assumed')

    def test_presence_needs_every_declared_file(self):
        self.assertFalse(mi.declared_files_present(self.app_dir, DECLARED))
        for f in DECLARED:
            path = os.path.join(self.app_dir, *f['path'].split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'wb').close()
        self.assertTrue(mi.declared_files_present(self.app_dir, DECLARED))
        os.remove(os.path.join(self.app_dir, 'face-parse', 'resnet18.pth'))
        self.assertFalse(mi.declared_files_present(self.app_dir, DECLARED))
        self.assertFalse(mi.declared_files_present(self.app_dir, []))

    def test_install_from_spec_dispatches_the_files_driver(self):
        with patch.object(mi, 'pull_declared_files', return_value={'ok': True}) as files, \
                patch.object(mi, 'pull_github_asset') as single, \
                patch.object(mi, 'record_provenance', side_effect=lambda s, r: r):
            mi.install_from_spec(self._spec())
        files.assert_called_once()
        single.assert_not_called()

    def test_no_identity_is_drawn_from_a_files_origin(self):
        """A mirror is not an author: the model's identity is the one its discovery declares."""
        from wama.model_manager.services.provenance import identity_for_spec
        self.assertIsNone(identity_for_spec(self._spec()))


class UninstallingDeclaredFilesTest(TestCase):
    """Désinstaller une ligne à fichiers déclarés retire CES fichiers, jamais leur dossier :
    l'enhancer range ses sept modèles dans un seul, MuseTalk y garde des poids non déclarés."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.settings_cm = self.settings(AI_MODELS_DIR=self.root)
        self.settings_cm.enable()
        self.addCleanup(self.settings_cm.disable)
        self.app_dir = os.path.join(self.root, 'models', 'lipsync', 'codeformer')

    def _place(self, *paths):
        for rel in paths:
            path = os.path.join(self.app_dir, *rel.split('/'))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as fh:
                fh.write(b'x' * 1024)

    def _row(self, key, files, **over):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(
            model_key=key, name=key, source='avatarizer', is_downloaded=True,
            extra_info={'install_dir': self.app_dir, 'declared_files': files}, **over)

    def test_only_the_declared_files_go_and_emptied_folders_with_them(self):
        self._place(*(f['path'] for f in DECLARED), 'facelib/not_declared.pth')
        self._row('avatarizer:codeformer', DECLARED)
        res = mi.uninstall_model('avatarizer:codeformer')
        self.assertTrue(res['ok'], res)
        self.assertEqual('declared_files', res['kind'])
        for f in DECLARED:
            self.assertFalse(os.path.exists(os.path.join(self.app_dir, *f['path'].split('/'))))
        self.assertTrue(os.path.exists(os.path.join(self.app_dir, 'facelib', 'not_declared.pth')),
                        'a file the row does not declare stays')
        self.assertFalse(os.path.exists(os.path.join(self.app_dir, 'CodeFormer')),
                         'a folder emptied by the removal goes with it')
        self.assertTrue(os.path.isdir(self.app_dir), 'never the app folder')
        from wama.model_manager.models import AIModel
        self.assertFalse(AIModel.objects.get(model_key='avatarizer:codeformer').is_downloaded)

    def test_a_sibling_row_in_the_same_folder_keeps_its_file(self):
        """The enhancer case: one folder, one file per row."""
        self._place(DECLARED[0]['path'], DECLARED[2]['path'])
        self._row('enhancer:a', [DECLARED[0]])
        self._row('enhancer:b', [DECLARED[2]])
        res = mi.uninstall_model('enhancer:a')
        self.assertTrue(res['ok'], res)
        self.assertEqual([], res['also_marked'])
        self.assertTrue(os.path.exists(os.path.join(self.app_dir, 'face-parse', 'resnet18.pth')))

    def test_a_file_declared_by_another_installed_row_needs_confirmation(self):
        self._place(DECLARED[0]['path'])
        self._row('avatarizer:one', [DECLARED[0]])
        self._row('avatarizer:two', [DECLARED[0]])
        res = mi.uninstall_model('avatarizer:one')
        self.assertTrue(res.get('needs_confirmation'), res)
        self.assertEqual(['avatarizer:two'], res['sharing'])
        self.assertTrue(os.path.exists(os.path.join(self.app_dir, 'CodeFormer', 'codeformer.pth')))
        res = mi.uninstall_model('avatarizer:one', include_shared=True)
        self.assertTrue(res['ok'], res)
        self.assertEqual(['avatarizer:two'], res['also_marked'])

    def test_counter_proof_outside_the_models_root_nothing_is_removed(self):
        elsewhere = tempfile.mkdtemp()
        kept = os.path.join(elsewhere, 'CodeFormer', 'codeformer.pth')
        os.makedirs(os.path.dirname(kept))
        open(kept, 'wb').close()
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='avatarizer:outside', name='outside',
                               source='avatarizer', is_downloaded=True,
                               extra_info={'install_dir': elsewhere,
                                           'declared_files': [DECLARED[0]]})
        res = mi.uninstall_model('avatarizer:outside')
        self.assertFalse(res['ok'])
        self.assertTrue(os.path.exists(kept))


class PullModelRequestsTheInstallTest(TestCase):
    """`pull_model <clé>` : la DEMANDE du bouton « Installer » (`request_install`), jamais le
    pilote interne — une première version appelait `install_from_spec` et sautait la garde
    d'espace disque, l'idempotence et le suivi de la tâche (2026-10-10)."""

    def test_a_catalogue_key_is_the_buttons_request_on_the_cli_way(self):
        from io import StringIO

        from django.core.management import call_command
        with patch.object(mi, 'request_install',
                          return_value={'ok': True, 'started': True, 'task_id': 't1',
                                        'model_key': 'avatarizer:codeformer'}) as req, \
                patch.object(mi, 'install_from_spec') as driver:
            call_command('pull_model', 'avatarizer:codeformer', stdout=StringIO())
        req.assert_called_once_with('avatarizer:codeformer', via='cli')
        driver.assert_not_called()

    def test_the_request_is_dispatched_with_its_history_event(self):
        """Bout à bout sur la vraie demande : garde passée, tâche enfilée, événement `cli`."""
        from io import StringIO

        from django.core.management import call_command

        from wama.model_manager.models import AIModel, InstallEvent
        from wama.model_manager.tasks import install_catalog_task
        with tempfile.TemporaryDirectory() as root, self.settings(AI_MODELS_DIR=root):
            app_dir = os.path.join(root, 'models', 'lipsync', 'codeformer')
            AIModel.objects.create(model_key='avatarizer:codeformer', name='CodeFormer',
                                   source='avatarizer', model_type='vision',
                                   extra_info={'install_dir': app_dir, 'declared_files': DECLARED})
            with patch.object(mi, 'disk_space_guard', return_value=None), \
                    patch.object(install_catalog_task, 'delay') as delay:
                delay.return_value.id = 't1'
                call_command('pull_model', 'avatarizer:codeformer', stdout=StringIO())
        delay.assert_called_once()
        event = InstallEvent.objects.filter(key='avatarizer:codeformer').latest('started_at')
        self.assertEqual('cli', event.via)

    def test_an_absent_key_is_said_not_pulled_from_ollama(self):
        from django.core.management import CommandError, call_command
        with patch.object(mi, 'pull_ollama_model') as ollama, \
                self.assertRaisesMessage(CommandError, 'sync_models'):
            call_command('pull_model', 'avatarizer:nothing-here')
        ollama.assert_not_called()


class YoloAdoptsTheCommonDownloadTest(SimpleTestCase):
    """Le pilote `yolo` passe par la primitive commune, son garde-fou de 1 Mo inchangé."""

    def test_pull_yolo_weights_delegates_with_its_floor(self):
        with tempfile.TemporaryDirectory() as root, \
                self.settings(AI_MODELS_DIR=root), \
                patch.object(mi, 'download_asset', return_value={'ok': True}) as dl:
            mi.pull_yolo_weights('yolo11n-seg')
        from wama.common.external_sources import base_url, proxies_for
        url, target = dl.call_args.args
        # The address derives from the declared `github` source, like the `github` driver's.
        self.assertEqual(f"{base_url('github')}/ultralytics/assets/releases/latest/download/"
                         "yolo11n-seg.pt", url)
        self.assertEqual(proxies_for('github'), dl.call_args.kwargs['proxies'])
        self.assertEqual(os.path.join(root, 'models', 'vision', 'yolo', 'segment',
                                      'yolo11n-seg.pt'), target)
        self.assertEqual(1_000_000, dl.call_args.kwargs['min_bytes'])
