"""Tests de la garde SSRF (url_guard) et de son application dans url_ingest.

Nés du correctif 2026-08-29 : le `requests.head(allow_redirects=True)` de
`fetch_url_content` ne re-validait pas les redirections suivies — son jumeau
`fetch_html_as_text` le faisait. « Une garde se pose avec ses jumeaux. »

Depuis le 2026-11-06 (audit de sécurité), un saut de redirection est jugé AVANT d'être envoyé
(`guarded_request`) : relire l'historique d'une réponse obtenue (`verifier_redirections`, retiré,
R223) laissait partir la requête vers l'adresse interne.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils.url_guard import UrlRefusee, guarded_request, verifier_url


class _Hop:
    """Une réponse `requests` simulée : une redirection (`location`) ou une réponse finale."""

    def __init__(self, url, location=None, status=302, headers=None):
        self.url = url
        self.status_code = status if location else 200
        self.is_redirect = bool(location)
        self.headers = {'Location': location} if location else dict(headers or {})
        self.history = []
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        pass


def _chain(*hops):
    """Un faux `requests.get`/`requests.head` qui rend les sauts dans l'ordre et note les URL
    effectivement ENVOYÉES."""
    sent = []

    def send(url, **kwargs):
        assert kwargs.get('allow_redirects') is False, 'requests ne doit jamais suivre seul'
        sent.append(url)
        return hops[len(sent) - 1]
    return send, sent


class UrlGuardTests(SimpleTestCase):

    def test_a_redirect_to_an_internal_address_is_refused_before_being_sent(self):
        send, sent = _chain(_Hop('https://example.org/a', location='http://10.0.0.5/admin'))
        with mock.patch('requests.get', side_effect=send):
            with self.assertRaises(UrlRefusee):
                guarded_request('GET', 'https://example.org/a')
        self.assertEqual(sent, ['https://example.org/a'], 'la cible interne n’est jamais envoyée')

    def test_public_redirects_are_followed_hop_by_hop(self):
        final = _Hop('https://cdn.example.org/b')
        send, sent = _chain(_Hop('https://example.org/a', location='/b'),
                            _Hop('https://example.org/b', location='https://cdn.example.org/b'),
                            final)
        with mock.patch('wama.common.utils.url_guard.verifier_url', side_effect=lambda u: u), \
                mock.patch('requests.get', side_effect=send):
            self.assertIs(guarded_request('GET', 'https://example.org/a'), final)
        self.assertEqual(sent, ['https://example.org/a', 'https://example.org/b',
                                'https://cdn.example.org/b'])

    def test_too_many_redirects_are_refused(self):
        loop = [_Hop(f'https://example.org/{i}', location=f'/{i + 1}') for i in range(10)]
        send, _sent = _chain(*loop)
        with mock.patch('wama.common.utils.url_guard.verifier_url', side_effect=lambda u: u), \
                mock.patch('requests.get', side_effect=send):
            with self.assertRaises(UrlRefusee):
                guarded_request('GET', 'https://example.org/0')

    def test_le_loopback_est_refuse_des_l_url_saisie(self):
        with self.assertRaises(UrlRefusee):
            verifier_url("http://127.0.0.1:8000/admin")


class FetchUrlContentGardeTests(SimpleTestCase):
    """Le HEAD de fetch_url_content juge ses redirections, et le refus SORT du try."""

    def test_le_head_redirige_vers_l_interne_fait_echouer_l_ingest(self):
        from wama.common.utils import url_ingest

        send, sent = _chain(_Hop('https://example.org/page', location='http://192.168.1.10/secret'))
        with mock.patch('requests.head', side_effect=send):
            with self.assertRaises(UrlRefusee):
                url_ingest.fetch_url_content("https://example.org/page", "/tmp")
        self.assertEqual(sent, ['https://example.org/page'])
