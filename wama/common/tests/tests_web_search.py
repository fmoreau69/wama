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


class WebSearchFollowsTheOutboundProxyTest(SimpleTestCase):
    """La recherche web sort par le proxy que WAMA déclare, pas par ce que `requests` devine.

    Mesuré le 2026-09-26 dans WSL2 — le process qui exécute réellement gunicorn et Celery :
    `.env` n'y pose que `HTTP_PROXY`, et `requests`, laissé seul, ne trouve AUCUN proxy pour
    l'URL HTTPS du moteur (`get_environ_proxies` rend `{'http': …}` et rien pour https). Il
    sortait donc en direct, c'est-à-dire dans le vide derrière le proxy de l'université. La
    brique commune, elle, applique la valeur aux DEUX schémas.

    C'est le défaut exact soldé le 21/09 pour les connecteurs de la médiathèque, resté sur
    cette brique-ci : *une surface sortante qui n'emprunte pas la brique commune est une
    surface qui ne suit pas le proxy — et elle échoue sans rien dire d'utile.*
    """

    def test_the_search_engine_call_carries_the_declared_proxies(self):
        import requests as real_requests
        from django.test import override_settings
        # `web_search` importe `requests` DANS ses fonctions : on patche donc le module lui-même.
        with override_settings(WAMA_OUTBOUND_PROXY='http://proxy.test:3128'):
            with mock.patch.object(real_requests, 'post',
                                   return_value=_ReponseHttp(text=_DDG_SAMPLE)) as posted:
                web_search.search_web('monstera')
        self.assertEqual({'http': 'http://proxy.test:3128', 'https': 'http://proxy.test:3128'},
                         posted.call_args.kwargs['proxies'])

    def test_reading_a_page_carries_them_too(self):
        from django.test import override_settings
        import requests as real_requests
        page = _ReponseHttp(content=b'<html><body><p>Texte</p></body></html>',
                            headers={'Content-Type': 'text/html'}, url='https://example.org/a')
        # `verifier_url` résout le DNS : on la neutralise comme les autres tests de ce fichier
        # (elle a sa propre garde, `test_une_adresse_interne_est_refusee…`).
        with override_settings(WAMA_OUTBOUND_PROXY='http://proxy.test:3128'), \
                mock.patch('wama.common.utils.url_guard.verifier_url'):
            with mock.patch.object(real_requests, 'get', return_value=page) as fetched:
                web_search.read_web_page('https://example.org/a')
        self.assertEqual({'http': 'http://proxy.test:3128', 'https': 'http://proxy.test:3128'},
                         fetched.call_args.kwargs['proxies'])

    def test_without_any_proxy_nothing_is_forced(self):
        """Contre-épreuve : sans réglage, on ne force rien — `requests` garde son comportement
        (il lit l'environnement lui-même). Passer `{}` le priverait de cette lecture."""
        import os
        import requests as real_requests
        from django.test import override_settings
        clean = {k: v for k, v in os.environ.items()
                 if not (k.lower().endswith('_proxy') or k.lower() in ('no_proxy', 'all_proxy'))}
        with override_settings(WAMA_OUTBOUND_PROXY=''), mock.patch.dict(os.environ, clean, clear=True):
            with mock.patch.object(real_requests, 'post',
                                   return_value=_ReponseHttp(text=_DDG_SAMPLE)) as posted:
                web_search.search_web('monstera')
        self.assertIsNone(posted.call_args.kwargs['proxies'])


class ASilentEngineFailureIsSaidOutLoudTest(SimpleTestCase):
    """Un défi anti-robot n'est pas « zéro résultat » — mesuré sur le moteur réel le 26/09."""

    _CHALLENGE = ('<html><body><p>Unfortunately, bots use DuckDuckGo too. Please complete the '
                  'following challenge to confirm this search was made by a human.</p>'
                  '<script>anomaly</script></body></html>')

    def test_a_challenge_page_raises_instead_of_looking_empty(self):
        import requests as real_requests
        from wama.common.utils.web_search import SearchEngineUnavailable
        with mock.patch.object(real_requests, 'post',
                               return_value=_ReponseHttp(text=self._CHALLENGE)):
            with self.assertRaises(SearchEngineUnavailable):
                web_search.search_web('monstera')

    def test_a_genuinely_empty_result_page_stays_empty(self):
        """Contre-épreuve : sans marqueur de défi, zéro résultat reste une réponse LÉGITIME —
        la garde ne doit pas transformer toute recherche infructueuse en panne."""
        import requests as real_requests
        page = '<html><body><p>Aucun résultat pour cette recherche.</p></body></html>'
        with mock.patch.object(real_requests, 'post', return_value=_ReponseHttp(text=page)):
            self.assertEqual([], web_search.search_web('xyzzy introuvable'))
