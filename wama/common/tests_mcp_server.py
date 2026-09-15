"""
Serveur MCP (2026-09-15) — l'adaptateur mince au-dessus de `tool_api`.

⚠ CE QUE CES GARDES PROTÈGENT : l'uniformité. MCP n'a de valeur que si un client y voit
EXACTEMENT ce que voient l'assistant et l'API — mêmes outils, mêmes droits, même porte. Les deux
dérives possibles ne lèvent aucune exception :
  1. une seconde porte (validation ou gating recopiés ici) qui finirait par dire autre chose
     qu'`execute_tool` ;
  2. un schéma d'arguments plus strict que la porte, qui ferait refuser côté client ce que WAMA
     accepte.
Les appels passent par le VRAI protocole (session client ↔ serveur en mémoire du SDK), pas par
les fonctions internes : c'est le contrat vu du client qui est gardé.
"""
import json
from types import SimpleNamespace
from unittest import mock

import anyio
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.services import mcp_server
from wama.tool_api import TOOL_REGISTRY, app_id_for_tool, tool_input_schema


async def _inline(fn):
    """Exécution en ligne : les requêtes restent dans la transaction du test."""
    return fn()


def _inline_orm(test):
    """Remplace le passage par un thread (`_run_sync`) par une exécution en ligne, pour la durée
    du test.

    ⚠ En ligne, l'ORM tourne DANS la boucle asyncio — ce que Django refuse
    (`SynchronousOnlyOperation`). On l'autorise ICI SEULEMENT : c'est la seule façon de rester
    sur la connexion, donc dans la transaction, du test. En production, `_run_sync` passe par un
    thread et la question ne se pose pas.
    """
    import os
    for patcher in (mock.patch.object(mcp_server, '_run_sync', _inline),
                    mock.patch.dict(os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'})):
        patcher.start()
        test.addCleanup(patcher.stop)


class SchemaArgumentsTest(SimpleTestCase):

    def test_chaque_outil_a_un_schema_objet_serialisable(self):
        for name in TOOL_REGISTRY:
            with self.subTest(outil=name):
                schema = tool_input_schema(name)
                self.assertEqual('object', schema['type'])
                self.assertIsInstance(schema['properties'], dict)
                json.dumps(schema)

    def test_user_n_est_jamais_un_argument(self):
        """L'identité vient du jeton de la session — un argument `user` serait une usurpation."""
        for name in TOOL_REGISTRY:
            with self.subTest(outil=name):
                self.assertNotIn('user', tool_input_schema(name)['properties'])

    def test_requis_et_types_viennent_de_la_signature(self):
        schema = tool_input_schema('memory_recall')
        self.assertEqual(['query'], schema.get('required'))
        self.assertEqual('integer', schema['properties']['k']['type'])
        self.assertEqual('boolean', schema['properties']['include_rag']['type'])
        self.assertEqual(5, schema['properties']['k']['default'])

    def test_un_enum_n_est_jamais_plus_strict_que_la_porte(self):
        """Chaque valeur annoncée doit être acceptée par `invalid_choice_values` — et la garde
        doit porter sur au moins un enum réel, sinon elle passe à vide."""
        from wama.common.utils.param_schema import schema_choice_values
        vus = 0
        for name in TOOL_REGISTRY:
            app_id = app_id_for_tool(name)
            for arg, prop in tool_input_schema(name)['properties'].items():
                if 'enum' in prop:
                    vus += 1
                    with self.subTest(outil=name, argument=arg):
                        self.assertTrue(set(prop['enum']) <= schema_choice_values(app_id, arg))
        self.assertGreater(vus, 0, "aucun enum mesuré : la garde tournerait à vide")


class ProtocoleTest(TestCase):
    """Le contrat vu du CLIENT : session MCP réelle, en mémoire."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('mcp_protocole', password='x')
        _inline_orm(self)

    def _with_session(self, action):
        async def main():
            from mcp.shared.memory import create_connected_server_and_client_session
            server = mcp_server.build_server(fixed_user=self.user)
            async with create_connected_server_and_client_session(server) as session:
                return await action(session)
        return anyio.run(main)

    def test_la_liste_est_le_registre_filtre_par_les_droits(self):
        async def names(session):
            return sorted(t.name for t in (await session.list_tools()).tools)
        with mock.patch('wama.accounts.permissions.tool_accessible',
                        side_effect=lambda user, name: name != 'list_registries'):
            vus = self._with_session(names)
        self.assertEqual(sorted(n for n in TOOL_REGISTRY if n != 'list_registries'), vus)

    def test_un_appel_passe_par_execute_tool_avec_le_compte_de_la_session(self):
        with mock.patch('wama.tool_api.execute_tool', return_value={'ok': 1}) as porte:
            result = self._with_session(
                lambda session: session.call_tool('memory_recall', {'query': 'x', 'k': '3'}))
        # `'3'` arrive TEL QUEL à la porte : la validation du SDK ne l'a pas refusé.
        porte.assert_called_once_with('memory_recall', {'query': 'x', 'k': '3'}, self.user)
        self.assertFalse(result.isError)
        self.assertEqual({'ok': 1}, result.structuredContent)

    def test_une_erreur_de_la_porte_est_rendue_en_isError(self):
        with mock.patch('wama.tool_api.execute_tool',
                        return_value={'error': 'forbidden', 'detail': 'non'}):
            result = self._with_session(lambda session: session.call_tool('list_registries', {}))
        self.assertTrue(result.isError)
        self.assertIn('forbidden', result.content[0].text)


class IdentiteTest(TestCase):

    def setUp(self):
        from rest_framework.authtoken.models import Token
        self.user = get_user_model().objects.create_user('mcp_identite', password='x')
        self.key = Token.objects.create(user=self.user).key
        _inline_orm(self)

    def test_un_jeton_valide_rend_son_compte(self):
        self.assertEqual(self.user, mcp_server.user_for_token(self.key))

    def test_un_jeton_inconnu_ou_vide_ne_rend_rien(self):
        self.assertIsNone(mcp_server.user_for_token('inconnu'))
        self.assertIsNone(mcp_server.user_for_token(''))

    def test_un_compte_desactive_n_ouvre_pas_de_session(self):
        self.user.is_active = False
        self.user.save()
        self.assertIsNone(mcp_server.user_for_token(self.key))

    def test_le_verificateur_porte_le_compte_dans_le_sujet(self):
        """Contrat du vérificateur : compte → `AccessToken` qui le porte.

        ⚠ La recherche du compte est DOUBLÉE ici : sous `anyio.run`, Django ouvre une connexion
        propre au contexte asynchrone, qui ne voit pas la transaction non commitée du test (le
        jeton y serait introuvable). La recherche elle-même est gardée par les tests synchrones
        ci-dessus."""
        with mock.patch.object(mcp_server, 'user_for_token', return_value=self.user):
            token = anyio.run(mcp_server.WamaTokenVerifier().verify_token, self.key)
        self.assertEqual(str(self.user.pk), token.subject)
        self.assertEqual([mcp_server.SCOPE], token.scopes)

    def test_le_verificateur_refuse_un_jeton_sans_compte(self):
        with mock.patch.object(mcp_server, 'user_for_token', return_value=None):
            self.assertIsNone(anyio.run(mcp_server.WamaTokenVerifier().verify_token, 'x'))


class TransportHttpTest(SimpleTestCase):
    """L'authentification est posée DEVANT le transport : sans jeton, rien n'est servi."""

    _INIT = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
             'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                        'clientInfo': {'name': 'test', 'version': '0'}}}

    def setUp(self):
        # L'adresse vient du REGISTRE (`wama_mcp`) — jamais recopiée ici (garde d'external_sources).
        self.host, self.port = mcp_server.http_address()
        self._HEADERS = {'Host': f'{self.host}:{self.port}',
                         'Accept': 'application/json, text/event-stream',
                         'Content-Type': 'application/json'}

    def _client(self):
        from starlette.testclient import TestClient
        return TestClient(mcp_server.build_http_app(self.host, self.port),
                          base_url=f'http://{self.host}:{self.port}')

    def test_sans_jeton_la_requete_est_refusee(self):
        with self._client() as client:
            r = client.post(mcp_server.MCP_PATH, json=self._INIT, headers=self._HEADERS)
        self.assertEqual(401, r.status_code)

    def test_avec_un_jeton_valide_la_session_s_ouvre(self):
        compte = SimpleNamespace(pk=7, is_active=True)
        with mock.patch.object(mcp_server, 'user_for_token', return_value=compte), \
                mock.patch.object(mcp_server, '_user_by_pk', return_value=compte):
            with self._client() as client:
                r = client.post(mcp_server.MCP_PATH, json=self._INIT,
                                headers=dict(self._HEADERS, Authorization='Bearer valide'))
        self.assertEqual(200, r.status_code)

    def test_un_hote_etranger_est_refuse_meme_avec_un_jeton(self):
        """DNS rebinding : la protection du SDK est désactivée par défaut, activée ici."""
        compte = SimpleNamespace(pk=7, is_active=True)
        with mock.patch.object(mcp_server, 'user_for_token', return_value=compte):
            with self._client() as client:
                r = client.post(mcp_server.MCP_PATH, json=self._INIT,
                                headers=dict(self._HEADERS, Host=f'evil.example:{self.port}',
                                             Authorization='Bearer valide'))
        self.assertNotEqual(200, r.status_code)
