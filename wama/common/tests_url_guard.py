"""Tests de la garde SSRF (url_guard) et de son application dans url_ingest.

Nés du correctif 2026-08-29 : le `requests.head(allow_redirects=True)` de
`fetch_url_content` ne re-validait pas les redirections suivies — son jumeau
`fetch_html_as_text` le faisait. « Une garde se pose avec ses jumeaux. »
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils.url_guard import UrlRefusee, verifier_redirections, verifier_url


class _Saut:
    def __init__(self, url):
        self.url = url


class _Reponse:
    def __init__(self, sauts, finale):
        self.history = [_Saut(u) for u in sauts]
        self.url = finale


class UrlGuardTests(SimpleTestCase):

    def test_une_redirection_vers_une_adresse_interne_est_refusee(self):
        reponse = _Reponse(["https://example.org/a"], "http://10.0.0.5/admin")
        with self.assertRaises(UrlRefusee):
            verifier_redirections(reponse)

    def test_des_redirections_toutes_publiques_passent(self):
        reponse = _Reponse(["https://example.org/a"], "https://example.org/b")
        verifier_redirections(reponse)  # ne doit pas lever

    def test_le_loopback_est_refuse_des_l_url_saisie(self):
        with self.assertRaises(UrlRefusee):
            verifier_url("http://127.0.0.1:8000/admin")


class FetchUrlContentGardeTests(SimpleTestCase):
    """Le HEAD de fetch_url_content re-valide ses redirections, et le refus SORT du try."""

    def test_le_head_redirige_vers_l_interne_fait_echouer_l_ingest(self):
        from wama.common.utils import url_ingest

        head_pirate = _Reponse(["https://example.org/page"], "http://192.168.1.10/secret")
        head_pirate.headers = {'Content-Type': 'text/html'}
        with mock.patch('requests.head', return_value=head_pirate):
            with self.assertRaises(UrlRefusee):
                url_ingest.fetch_url_content("https://example.org/page", "/tmp")
