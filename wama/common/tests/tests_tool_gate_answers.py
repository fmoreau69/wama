"""
Ce que la porte des outils DIT au modèle — les défauts du fil Discord n° 43 (2026-10-30).

LES DÉFAUTS MESURÉS, chacun dans le fil persisté (`ConversationTurn.tool_steps`) :
  1. `start_imager(media_id=1163)` : le paramètre s'appelle `generation_id`. L'argument était jeté
     en silence, l'outil recevait « aucun élément » et lançait TOUTE la file — un élément d'août est
     reparti. Une ÉCRITURE qui reçoit un argument inconnu d'un modèle est REFUSÉE ; une LECTURE
     répond et dit ce qu'elle a ignoré. Le Studio, qui passe tous les réglages d'un nœud, garde le
     filtrage (ce n'est pas un modèle qui les écrit).
  2. L'ETA `16:27:57+00:00` annoncée « 16h27 » à 17 h, heure de Paris : les heures d'un résultat
     destiné à un modèle sont dans le fuseau de WAMA, et le prompt porte l'heure courante.
  3. 50 modèles sur 142 lus comme le catalogue entier (« aucun modèle d'image installé ») : une
     liste coupée le DIT ; un modèle installé sans backend porte `not_runnable`.
  4. « Le modèle que j'ai installé récemment » : aucun outil ne lisait le journal des installations.
  5. Un rapport de Claude Code coupé en silence, puis une « suite » inventée : la coupure est dite
     avec l'outil qui donne la suite (`dev_read_report`).
"""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from wama import tool_api as T
from wama.common.tests.tests_tool_api_lectures import _utilisateur


def _fake_start(calls):
    """Un `start_imager` de même signature, qui ne lance rien : on observe s'il est appelé."""
    @T.tool_effect(T.WRITE)
    def start_imager(user, generation_id: int = None, process: str = None) -> dict:
        calls.append(generation_id)
        return {'status': 'started', 'item_id': generation_id}
    return start_imager


class UnknownArgumentTest(TestCase):

    def setUp(self):
        self.user = _utilisateur('gate_args')          # rôle `communication` : l'Imager est ouvert

    def test_a_write_from_a_model_with_an_unknown_argument_is_refused_and_does_nothing(self):
        calls = []
        with mock.patch.dict(T.TOOL_REGISTRY, {'start_imager': _fake_start(calls)}):
            out = T.execute_tool('start_imager', {'media_id': 1163}, self.user, model_call=True)
        self.assertEqual([], calls, 'nothing may start: the whole queue would have been launched')
        self.assertIn('media_id', out['error'])
        self.assertIn('generation_id', out['error'], 'the refusal names the accepted arguments')

    def test_the_same_write_with_its_real_argument_runs(self):
        """Contre-épreuve : la garde ne ferme pas l'outil."""
        calls = []
        with mock.patch.dict(T.TOOL_REGISTRY, {'start_imager': _fake_start(calls)}):
            out = T.execute_tool('start_imager', {'generation_id': 1163}, self.user, model_call=True)
        self.assertEqual([1163], calls)
        self.assertNotIn('error', out)

    def test_a_caller_that_is_not_a_model_keeps_the_filtering_and_is_told(self):
        """Le Studio passe tous les réglages d'un nœud : il n'est pas refusé, la réponse le dit."""
        calls = []
        with mock.patch.dict(T.TOOL_REGISTRY, {'start_imager': _fake_start(calls)}):
            out = T.execute_tool('start_imager', {'generation_id': 7, 'node_setting': 1}, self.user)
        self.assertEqual([7], calls)
        self.assertEqual(['node_setting'], out['ignored_arguments'])

    def test_a_read_answers_and_says_what_it_ignored(self):
        out = T.execute_tool('list_my_items', {'app': 'imager', 'pk': 3}, self.user, model_call=True)
        self.assertIn('items', out)
        self.assertEqual(['pk'], out['ignored_arguments'])
        self.assertIn('ne les applique PAS', out['ignored_note'])


@override_settings(TIME_ZONE='Europe/Paris', USE_TZ=True)
class LocalTimesTest(SimpleTestCase):

    def test_a_utc_time_is_said_in_the_time_zone_of_wama(self):
        out = T._local_times({'jobs': [{'queue': {'expectedEnd': '2026-10-30T16:27:57.773014+00:00'}}],
                              'name': 'pas une date', 'count': 3})
        self.assertEqual('2026-10-30T17:27:57.773014+01:00', out['jobs'][0]['queue']['expectedEnd'])
        self.assertEqual(('pas une date', 3), (out['name'], out['count']))

    def test_the_prompt_carries_the_current_time_and_its_zone(self):
        from wama.common.services.assistant_engine import _clock_line
        line = _clock_line()
        self.assertIn('Europe/Paris', line)
        self.assertIn(timezone.localtime().strftime('%Y-%m-%d'), line)


class CatalogueAnswersTest(TestCase):

    def setUp(self):
        from wama.model_manager.models import AIModel
        self.user = _utilisateur('gate_models')
        AIModel.objects.create(model_key='testsrc:sans-moteur', name='Sans moteur', source='testsrc',
                               is_downloaded=True,
                               composition={'runtime': {'engine': 'moteur-inexistant'}})
        for i in range(3):
            AIModel.objects.create(model_key=f'testsrc:m{i}', name=f'Témoin {i}', source='testsrc')

    def test_an_installed_model_without_backend_says_it_cannot_run(self):
        line = T.get_ai_model(self.user, 'testsrc:sans-moteur')
        self.assertIn('moteur-inexistant', line['not_runnable'])
        listed = {m['key']: m for m in T.list_ai_models(self.user, query='testsrc')['models']}
        self.assertIn('not_runnable', listed['testsrc:sans-moteur'])
        self.assertNotIn('not_runnable', listed['testsrc:m0'], 'no engine declared: not condemned')

    def test_a_cut_list_says_what_it_does_not_show(self):
        out = T.list_ai_models(self.user, query='testsrc', limit=2)
        self.assertTrue(out['truncated'])
        self.assertIn('Never conclude that a model is absent', out['truncated_note'])
        self.assertNotIn('truncated_note', T.list_ai_models(self.user, query='testsrc', limit=50))


class InstallationsTest(TestCase):

    def test_the_last_installations_come_first_and_say_their_way(self):
        from wama.model_manager.models import InstallEvent
        now = timezone.now()
        InstallEvent.objects.create(kind='model', key='old', name='Ancien', status='SUCCESS',
                                    via='assistant', started_at=now - timedelta(days=3))
        InstallEvent.objects.create(kind='model', key='hf:Abiray/Fibo', name='Fibo 2.0',
                                    status='SUCCESS', via='model_manager', started_at=now)
        out = T.list_installations(_utilisateur('gate_installs', role=None))
        self.assertEqual(['Fibo 2.0', 'Ancien'], [r['name'] for r in out['installations']])
        self.assertEqual('model manager', out['installations'][0]['via'])
        self.assertIn('error', T.list_installations(AnonymousUser()))

    def test_a_request_never_taken_up_is_said_as_the_calendar_says_it(self):
        """Ouverte il y a deux jours, jamais reprise : pas « En cours » (`effective_state`)."""
        from wama.model_manager.models import InstallEvent
        from wama.model_manager.services.install_history import NOT_RESUMED
        InstallEvent.objects.create(kind='model', key='stale', name='Oubliée', status='RUNNING',
                                    started_at=timezone.now() - timedelta(days=2))
        row = T.list_installations(_utilisateur('gate_stale', role=None))['installations'][0]
        self.assertEqual(('Échec', NOT_RESUMED), (row['status'], row['error']))

    def test_what_the_driver_verified_is_said_from_the_install_log_vocabulary(self):
        """2026-11-05: every driver checks what it lays against a fingerprint; the log keeps it,
        the assistant says it — in the log's own words (`install_history.verified_text`)."""
        from wama.model_manager.models import InstallEvent
        now = timezone.now()
        InstallEvent.objects.create(kind='model', key='hf:org/checked', name='Vérifié',
                                    status='SUCCESS', started_at=now,
                                    detail={'verified': {'against': 'published', 'count': 6}})
        InstallEvent.objects.create(kind='model', key='hf:org/older', name='Avant',
                                    status='SUCCESS', started_at=now - timedelta(hours=1))
        rows = T.list_installations(_utilisateur('gate_verified', role=None))['installations']
        self.assertEqual("6 fichier(s) vérifié(s) contre l'empreinte publiée par sa source",
                         rows[0]['verified'])
        self.assertNotIn('verified', rows[1], 'nothing claimed for an install that said nothing')


class ProviderErrorTextTest(SimpleTestCase):
    """L'échec d'un fournisseur se DIT : qui, quoi, que faire — jamais « litellm.APIError:
    APIError: OpenAIException - » (ILaaS, 2026-10-30 16:58, appel refusé sans message)."""

    class APIError(Exception):
        status_code = None

    class RateLimitError(Exception):
        status_code = 429

    def _text(self, exc):
        from wama.common.utils.llm_utils import provider_error_text
        return provider_error_text('ILaaS', 'gemma-4-31b', exc)

    def test_the_empty_refusal_of_the_thread_says_who_and_what_to_do(self):
        text = self._text(self.APIError('litellm.APIError: APIError: OpenAIException - '))
        self.assertIn('ILaaS (gemma-4-31b)', text)
        self.assertIn('sans dire pourquoi', text)
        self.assertIn('renvoyez-le', text)
        self.assertNotIn('OpenAIException', text)

    def test_the_provider_message_is_kept_when_there_is_one(self):
        text = self._text(self.APIError('litellm.InternalServerError: InternalServerError: '
                                        'OpenAIException - Connection error.'))
        self.assertIn('« Connection error. »', text)

    def test_the_status_says_the_kind_of_failure(self):
        self.assertIn('limite de débit', self._text(self.RateLimitError('429')))
        refused = self.APIError('')
        refused.status_code = 401
        self.assertIn('refuse la clé', self._text(refused))


class DevReportTest(SimpleTestCase):

    def setUp(self):
        from wama.common.services import dev_tools
        self.dev_tools = dev_tools
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.object(dev_tools, 'jobs_dir', return_value=self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job_id = '20261030-161333-d15fce'
        self.report = '\n'.join(f'ligne {i} du rapport de Claude Code' for i in range(600))
        (self.dir / f'{self.job_id}.json').write_text(
            '{"id": "%s", "tool": "claude_code:write", "pid": 1}' % self.job_id, encoding='utf-8')
        (self.dir / f'{self.job_id}.rc').write_text('0', encoding='utf-8')
        (self.dir / f'{self.job_id}.log').write_text('{}', encoding='utf-8')
        reader = mock.patch('wama.common.services.claude_code.read_output',
                            return_value={'texte': self.report})
        reader.start()
        self.addCleanup(reader.stop)

    def test_a_cut_report_says_so_and_names_the_tool_that_gives_the_rest(self):
        summary = self.dev_tools._job_summary(self.dev_tools.job_state(self.job_id))
        self.assertLess(len(summary), len(self.report))
        self.assertIn('rapport tronqué', summary)
        self.assertIn(f'dev_read_report` avec job_id={self.job_id}', summary)
        status = self.dev_tools.dev_job_status(None, self.job_id)
        self.assertIn('rapport tronqué', status['response'])
        self.assertNotIn('log_tail', status, 'the answer stands for the raw JSON log')

    def test_the_whole_report_is_read_page_by_page(self):
        pages, offset = [], 0
        while offset is not None:
            page = self.dev_tools.dev_read_report(None, self.job_id, offset)
            pages.append(page['text'])
            offset = page['next_offset']
        self.assertEqual(self.report, ''.join(pages))
        self.assertIn('dev_read_report', self.dev_tools.DEV_TOOLS)

    def test_a_short_report_is_not_marked(self):
        """Contre-épreuve : aucune marque quand rien n'est coupé."""
        self.assertEqual('court', self.dev_tools.cut_with_notice('court', 100, self.job_id))
