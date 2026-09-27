"""Moteurs de recherche web : l'inventaire vient du REGISTRE, le choix est une préférence.

Ce que ces gardes tiennent, c'est ce qui rendrait le mécanisme faux SANS lever d'erreur :
  • un moteur déclaré au registre mais sans adaptateur serait offert au choix et échouerait à
    la première recherche ; un adaptateur sans source n'aurait ni adresse ni proxy ;
  • une instance SearXNG jamais montée deviendrait le moteur par défaut de toute installation
    neuve — « sans clé, donc utilisable » — et chaque recherche mourrait sur une connexion
    refusée, là où le repli devait simplement passer au moteur suivant ;
  • une préférence pointant un moteur dont on n'a pas la clé produirait une panne silencieuse
    à chaque recherche, sans que l'utilisateur puisse comprendre pourquoi ;
  • un adaptateur qui appellerait `requests` sans les proxies de sa source ne suivrait pas le
    proxy de l'établissement — le défaut mesuré le 26/09 sur la brique qu'ils remplacent.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common import external_sources
from wama.common import search_engines
from wama.common.search_engines import registry


class EveryEngineIsADeclaredSourceTest(SimpleTestCase):

    def test_each_adapter_has_its_source_and_back(self):
        declared = {s.key for s in external_sources.SOURCES if s.kind == 'recherche'}
        adapters = set(search_engines.engine_slugs())
        self.assertTrue(adapters <= declared,
                        f'adaptateur(s) sans source déclarée : {adapters - declared}')
        # L'inverse n'est PAS une égalité exigée : une source de recherche peut être déclarée
        # avant son adaptateur (veille). Elle n'est alors simplement pas offerte au choix.
        offered = {s.key for s in search_engines.declared_engines()}
        self.assertEqual(adapters, offered)

    def test_no_adapter_hardcodes_its_address(self):
        """L'adresse vient du registre — une constante d'URL dans un adaptateur la dédoublerait.

        ⚠ Relevé par AST, pas par motif texte, et pour une raison vécue : ma première rédaction
        cherchait la chaîne dans le fichier et a échoué sur une adresse **citée en docstring**
        (« base `https://api.staan.ai/v2`, déclarée au registre ») — une documentation exacte,
        que la garde accusait de duplication. Même idiome que la garde jumelle des connecteurs
        (`tests_providers`) : *un texte qui parle du code n'est pas le code.*
        """
        import ast
        from pathlib import Path
        from urllib.parse import urlparse

        from django.conf import settings
        folder = Path(settings.BASE_DIR) / 'wama' / 'common' / 'search_engines'
        offenders = []
        for path in sorted(folder.glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                          if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
                          and node.body and isinstance(node.body[0], ast.Expr)
                          and isinstance(node.body[0].value, ast.Constant)
                          and isinstance(node.body[0].value.value, str)}
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and id(node) not in docstrings
                        and urlparse(node.value).netloc):
                    # ⚠ `netloc` et non « commence par http » : les adaptateurs valident les
                    # URL qu'ils REÇOIVENT (`url.startswith(('http://', 'https://'))`), et un
                    # schéma nu n'est pas une adresse. La 1ʳᵉ version les accusait tous les
                    # quatre — une garde qui crie sur du code correct finit désactivée.
                    offenders.append(f'{path.name}:{node.lineno} → {node.value}')
        self.assertEqual([], offenders)


class EngineResolutionTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('engine_user', password='x')

    def _put_key(self, slug, value='k-123'):
        from wama.accounts.models import UserApiKey
        UserApiKey.objects.create(user=self.user, source=slug, api_key=value)

    def test_an_engine_needing_a_key_is_not_offered_without_one(self):
        self.assertNotIn('exa', search_engines.usable_slugs(self.user))
        self._put_key('exa')
        self.assertIn('exa', search_engines.usable_slugs(self.user))

    def test_an_undeclared_local_instance_is_not_usable(self):
        """SearXNG porte une adresse par défaut qui ne désigne rien tant que rien n'est monté."""
        self.assertNotIn('searxng', search_engines.usable_slugs(self.user))
        with override_settings(SEARXNG_URL='http://searx.labo.test'):
            self.assertIn('searxng', search_engines.usable_slugs(self.user))

    def test_the_profile_preference_wins_over_the_instance_default(self):
        self._put_key('exa')
        self._put_key('staan')
        with override_settings(WAMA_SEARCH_ENGINE='staan'):
            self.assertEqual('staan', search_engines.preferred_slug(self.user))
            self.user.profile.search_engine = 'exa'
            self.user.profile.save(update_fields=['search_engine'])
            self.user.refresh_from_db()
            self.assertEqual('exa', search_engines.preferred_slug(self.user))

    def test_a_preference_that_became_unusable_falls_back_instead_of_failing(self):
        """La clé retirée, la préférence ne doit pas geler la recherche sur un moteur mort."""
        self.user.profile.search_engine = 'exa'
        self.user.profile.save(update_fields=['search_engine'])
        self.user.refresh_from_db()
        self.assertEqual('duckduckgo', search_engines.preferred_slug(self.user))

    def test_with_no_usable_engine_the_message_names_the_remedy(self):
        from wama.common.search_engines import SearchEngineUnavailable
        with mock.patch.object(registry, 'usable_slugs', return_value=[]):
            with self.assertRaises(SearchEngineUnavailable) as caught:
                search_engines.engine_for(self.user)
        self.assertIn('profil', str(caught.exception))


class EnginesGoThroughTheDeclaredProxyTest(TestCase):
    """Chaque adaptateur emprunte le proxy de SA source — jamais ce que `requests` devine."""

    def setUp(self):
        self.user = User.objects.create_user('proxy_engine_user', password='x')

    @override_settings(WAMA_OUTBOUND_PROXY='http://proxy.test:3128')
    def test_the_neural_engine_carries_them(self):
        engine = search_engines.get_engine('exa', api_key='k')
        payload = {'results': [{'title': 'T', 'url': 'https://example.org/a', 'text': 'x'}]}
        with mock.patch('requests.post', return_value=_Json(payload)) as posted:
            hits = engine.search('monstera', max_results=3)
        self.assertEqual('https://example.org/a', hits[0].url)
        self.assertEqual({'http': 'http://proxy.test:3128', 'https': 'http://proxy.test:3128'},
                         posted.call_args.kwargs['proxies'])
        self.assertEqual('k', posted.call_args.kwargs['headers']['x-api-key'])

    @override_settings(WAMA_OUTBOUND_PROXY='http://proxy.test:3128')
    def test_the_european_engine_sends_a_bearer_token(self):
        engine = search_engines.get_engine('staan', api_key='jeton')
        payload = {'results': [{'title': 'T', 'url': 'https://example.org/b', 'snippet': 'y'}]}
        with mock.patch('requests.get', return_value=_Json(payload)) as fetched:
            hits = engine.search('monstera')
        self.assertEqual('https://example.org/b', hits[0].url)
        self.assertEqual('Bearer jeton', fetched.call_args.kwargs['headers']['Authorization'])
        self.assertIn('proxies', fetched.call_args.kwargs)

    @override_settings(SEARXNG_URL='http://searx.labo.test')
    def test_a_local_instance_has_its_proxy_neutralised(self):
        """Portée LOCALE : on ne passe pas par le proxy pour joindre sa propre machine — c'est
        l'incident du 31/08 (le proxy répondait sa page d'erreur à la place du service)."""
        engine = search_engines.get_engine('searxng')
        with mock.patch('requests.get', return_value=_Json({'results': []})) as fetched:
            engine.search('monstera')
        self.assertEqual({'http': None, 'https': None}, fetched.call_args.kwargs['proxies'])

    def test_a_refused_key_is_said_out_loud(self):
        from wama.common.search_engines import SearchEngineUnavailable
        engine = search_engines.get_engine('exa', api_key='mauvaise')
        with mock.patch('requests.post', return_value=_Json({}, status=401)):
            with self.assertRaises(SearchEngineUnavailable) as caught:
                engine.search('monstera')
        self.assertIn('clé', str(caught.exception).lower())

    def test_a_searxng_without_json_enabled_says_so(self):
        """Le format JSON est désactivé PAR DÉFAUT dans SearXNG : sans ce message, l'instance
        paraîtrait simplement ne rien trouver."""
        from wama.common.search_engines import SearchEngineUnavailable
        engine = search_engines.get_engine('searxng')
        with mock.patch('requests.get', return_value=_Json({'query': 'x'})):
            with self.assertRaises(SearchEngineUnavailable) as caught:
                engine.search('monstera')
        self.assertIn('settings.yml', str(caught.exception))


class _Json:
    """Réponse `requests` minimale — JSON et statut, rien d'autre."""

    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f'statut {self.status_code} non traité avant raise_for_status')


class ProfileOffersTheKeysOfBothFamiliesTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('keys_user', password='x')

    def test_the_profile_listing_covers_every_family_that_asks_for_a_personal_key(self):
        """Le critère est `user_key`, plus une liste de familles à tenir à jour.

        ⚠ C'en était une (`('llm', 'recherche')`) jusqu'au 2026-09-27 : le jour où un CORPUS de
        voix a demandé une clé par utilisateur (Mozilla Data Collective), le profil n'aurait
        rien affiché — silencieusement, une liste vide n'étant pas une erreur."""
        from wama.accounts.api_keys import listing
        from wama.common import external_sources

        served = {row['slug'] for row in listing(self.user)}
        attendu = {s.key for s in external_sources.SOURCES
                   if s.user_key and s.kind != 'media' and not s.developer_only}
        self.assertTrue(attendu <= served, f'jamais proposées au profil : {attendu - served}')
        self.assertIn('corpus', {row['kind'] for row in listing(self.user)},
                      'un corpus à clé de chacun se pose au MÊME endroit que les autres')

    def test_media_connectors_never_appear_twice(self):
        """Contre-épreuve : les connecteurs de la médiathèque ont leur PROPRE écran et leur
        propre stockage — les lister ici les afficherait deux fois, chacun écrivant ailleurs."""
        from wama.accounts.api_keys import listing
        self.assertNotIn('media', {row['kind'] for row in listing(self.user)})

    def test_saving_a_search_engine_key_is_accepted(self):
        """La route refusait toute source non-LLM avant le 2026-09-26."""
        from wama.accounts.api_keys import is_keyed_source
        self.assertTrue(is_keyed_source('exa', self.user))
        self.assertTrue(is_keyed_source('albert', self.user))

    def test_choosing_an_engine_without_its_key_is_refused_with_a_reason(self):
        self.client.force_login(self.user)
        from django.urls import reverse
        resp = self.client.post(reverse('accounts:profile-search-engine'),
                                data='{"engine": "exa"}', content_type='application/json')
        self.assertEqual(400, resp.status_code)
        self.assertIn('clé', resp.json()['error'].lower())

    def test_the_listing_fields_are_all_consumed_by_the_page(self):
        """Garde anti-champ MORT : `kind_label` a été ajouté au payload « pour grouper par
        famille » et n'était consommé par rien — une intention écrite dans un docstring, pas
        dans la page. Le profil mêle désormais deux familles de clés : sans le sous-titre, une
        liste plate ne dit plus à quoi chaque clé sert."""
        from pathlib import Path

        from django.conf import settings
        from wama.accounts.api_keys import listing
        page = (Path(settings.BASE_DIR) / 'wama' / 'accounts' / 'templates' / 'accounts'
                / 'profile.html').read_text(encoding='utf-8')
        for field in listing(self.user)[0]:
            if field in ('slug', 'kind'):      # identifiants internes, jamais affichés
                continue
            self.assertIn(field, page, f'`{field}` est servi au profil mais rien ne le lit')
