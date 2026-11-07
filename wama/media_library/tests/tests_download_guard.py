"""Un téléchargement de la médiathèque ne fait parler le serveur qu'à une adresse PUBLIQUE
(2026-11-06, audit de sécurité) : l'adresse vient du navigateur, et un connecteur à
`download_domains = ()` (Openverse) acceptait `http://127.0.0.1:…`, dont il rendait le corps.
"""
import urllib.request
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils.url_guard import UrlRefusee
from wama.media_library.providers.base import _CheckedRedirects, build_opener


class DownloadGuardTest(SimpleTestCase):

    def _provider(self):
        from wama.media_library.providers.openverse import OpenverseProvider
        return OpenverseProvider()

    def test_an_internal_address_is_refused_before_any_request(self):
        provider = self._provider()
        with mock.patch.object(provider, 'open_url') as opened:
            for url in ('http://127.0.0.1:8001/health', 'http://10.0.0.5/x', 'file:///etc/passwd'):
                with self.assertRaises(UrlRefusee, msg=url):
                    provider.download_bytes(url)
        opened.assert_not_called()

    def test_every_redirect_hop_is_judged_before_being_followed(self):
        handler = _CheckedRedirects()
        request = urllib.request.Request('https://example.org/a')
        with self.assertRaises(UrlRefusee):
            handler.redirect_request(request, None, 302, 'Found', {}, 'http://192.168.1.10/x')

    def test_the_connector_opener_carries_the_checked_redirects(self):
        with mock.patch('wama.common.external_sources.proxies_for', return_value=None):
            opener = build_opener('openverse')
        self.assertTrue(any(isinstance(h, _CheckedRedirects) for h in opener.handlers))
