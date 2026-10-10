"""
YOLOPv2's download goes through the model installer's common one (2026-10-10).

`road_model_downloader` re-implemented a download (partial file, length check) with no digest.
It now hands it to `model_installer.download_asset` with the PINNED digest, the address derived
from the declared `github` source — same folder, same name, same return contract, because the
profile dropdown lists that folder. The network is simulated: no test downloads 156 MB.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import road_model_downloader as rmd

HISTORICAL_URL = 'https://github.com/CAIC-AD/YOLOPv2/releases/download/V0.0.1/yolopv2.pt'


class YolopV2DownloadTest(SimpleTestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        patcher = patch.object(rmd, 'ROAD_MODELS_DIR', self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_derived_address_is_the_historical_one(self):
        from wama.model_manager.services.model_installer import github_asset_url
        self.assertEqual(HISTORICAL_URL, github_asset_url(rmd.YOLOPV2_SPEC))
        self.assertEqual('yolopv2.pt', rmd.YOLOPV2_LOCAL_NAME)
        self.assertEqual(rmd.YOLOPV2_LOCAL_NAME, rmd.BDD100K_SEG_LOCAL_NAME, 'the view imports it')

    def test_a_present_file_is_kept_without_any_download(self):
        (self.dir / 'yolopv2.pt').write_bytes(b'weights')
        with patch('wama.model_manager.services.model_installer.download_asset') as dl:
            ok, path, msg = rmd.ensure_bdd100k_seg()
        self.assertEqual((True, str(self.dir / 'yolopv2.pt')), (ok, path))
        self.assertIn('Déjà présent', msg)
        dl.assert_not_called()

    def test_the_download_is_the_common_one_with_the_pinned_digest(self):
        with patch('wama.model_manager.services.model_installer.download_asset',
                   return_value={'ok': True}) as dl:
            ok, path, msg = rmd.ensure_bdd100k_seg()
        url, target = dl.call_args.args
        self.assertEqual(HISTORICAL_URL, url)
        self.assertEqual(str(self.dir / 'yolopv2.pt'), target)
        self.assertEqual(rmd.YOLOPV2_SPEC['sha256'], dl.call_args.kwargs['sha256'])
        self.assertIn('proxies', dl.call_args.kwargs)
        self.assertEqual((True, target), (ok, path))
        self.assertIn('Téléchargé', msg)

    def test_force_downloads_again_over_a_present_file(self):
        (self.dir / 'yolopv2.pt').write_bytes(b'weights')
        with patch('wama.model_manager.services.model_installer.download_asset',
                   return_value={'ok': True}) as dl:
            rmd.ensure_bdd100k_seg(force=True)
        dl.assert_called_once()

    def test_a_failure_is_said_with_the_contract_of_before(self):
        with patch('wama.model_manager.services.model_installer.download_asset',
                   return_value={'ok': False, 'error': 'empreinte différente'}):
            ok, path, msg = rmd.ensure_bdd100k_seg()
        self.assertEqual((False, ''), (ok, path))
        self.assertIn('Échec téléchargement', msg)
        self.assertIn('empreinte', msg)
        self.assertFalse(os.listdir(self.dir), 'nothing left behind')
