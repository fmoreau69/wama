"""Tests de la brique web_search : parsing moteur, plafonds, gardes SSRF et d'identité."""
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase

from wama.common.utils.url_guard import UrlRefusee
from wama.common.utils import web_search

_DDG_SAMPLE = """
<html><body>
  <div class="result result--ad">
    <a class="result__a" href="https://pub.example.com/achetez">Publicité</a>
  </div>
  <div class="result">
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ffr.wikipedia.org%2Fwiki%2FMonstera&rut=abc">
      Monstera — Wikipédia</a>
    <a class="result__snippet">Le monstera est une plante tropicale…</a>
  </div>
  <div class="result">
    <a class="result__a" href="https://jardinage.example.org/monstera-soins">Soigner un monstera</a>
    <a class="result__snippet">Arrosage, lumière, maladies courantes.</a>
  </div>
</body></html>
"""


class _ReponseHttp:
    def __init__(self, *, text='', content=b'', headers=None, encoding='utf-8', url=''):
        self.text = text
        self._content = content
        self.headers = headers or {}
        self.encoding = encoding
        self.url = url
        self.history = []

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]

    def close(self):
        pass


class SearchWebTests(SimpleTestCase):

    def test_le_parsing_rend_titres_urls_decodees_et_snippets_sans_les_pubs(self):
        with mock.patch('requests.post', return_value=_ReponseHttp(text=_DDG_SAMPLE)):
            resultats = web_search.search_web('monstera feuilles jaunes')
        self.assertEqual(len(resultats), 2)  # la pub est écartée
        self.assertEqual(resultats[0]['url'], 'https://fr.wikipedia.org/wiki/Monstera')
        self.assertEqual(resultats[0]['title'], 'Monstera — Wikipédia')
        self.assertIn('tropicale', resultats[0]['snippet'])
        self.assertEqual(resultats[1]['url'], 'https://jardinage.example.org/monstera-soins')

    def test_une_requete_vide_ne_sort_pas_sur_le_reseau(self):
        with mock.patch('requests.post') as poste:
            self.assertEqual(web_search.search_web('   '), [])
        poste.assert_not_called()


class ReadWebPageTests(SimpleTestCase):

    def test_une_adresse_interne_est_refusee_avant_toute_sortie_reseau(self):
        with mock.patch('requests.get') as get:
            with self.assertRaises(UrlRefusee):
                web_search.read_web_page('http://127.0.0.1:8000/admin')
        get.assert_not_called()

    def test_le_plafond_d_octets_tronque_sans_planter(self):
        page = b'<html><body><main>' + b'x' * 50_000 + b'</main></body></html>'
        reponse = _ReponseHttp(content=page, headers={'Content-Type': 'text/html'},
                               url='https://example.org/longue')
        with mock.patch('wama.common.utils.url_guard.verifier_url'), \
                mock.patch('requests.get', return_value=reponse):
            rendu = web_search.read_web_page('https://example.org/longue', max_bytes=10_000)
        self.assertTrue(rendu['truncated'])
        self.assertLess(len(rendu['text']), 11_000)

    def test_un_type_media_est_renvoye_vers_url_ingest(self):
        reponse = _ReponseHttp(content=b'\x00\x01', headers={'Content-Type': 'video/mp4'},
                               url='https://example.org/film.mp4')
        with mock.patch('wama.common.utils.url_guard.verifier_url'), \
                mock.patch('requests.get', return_value=reponse):
            rendu = web_search.read_web_page('https://example.org/film.mp4')
        self.assertIn('error', rendu)
        self.assertIn('url_ingest', rendu['error'])


class OutilsAssistantTests(SimpleTestCase):
    """Garde d'identité : un outil sans app est autorisé à tous — la garde vit DANS le corps."""

    def test_le_visiteur_anonyme_est_refuse_sur_les_deux_outils(self):
        from wama.tool_api import TOOL_REGISTRY
        for nom in ('search_web', 'read_web_page'):
            outil = TOOL_REGISTRY[nom]
            rendu = outil(AnonymousUser(), 'quelconque')
            self.assertIn('error', rendu, nom)
            self.assertIn('identifi', rendu['error'], nom)
