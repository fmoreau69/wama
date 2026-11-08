"""
L'assistant reste DISPONIBLE pendant les tâches de développement (2026-10-12, fil Discord #43).

Mesuré ce jour-là : l'assistant suivait sa tâche DANS son tour — cinq `dev_job_status` d'affilée,
six minutes pendant lesquelles il ne répondait à rien —, et une modification confiée à Claude Code
s'exécutait de façon SYNCHRONE dans le process de la conversation. Ce qui est gardé ici :
  1. la fin d'une tâche de dev est ANNONCÉE une fois (notification `app='dev'`), par le process
     qui la possède — le chemin des tâches d'app, sans en écrire un second ;
  2. la passerelle la poste dans le fil d'où la tâche a été lancée ;
  3. un second statut d'une tâche en cours, dans le même tour, n'est plus relayé ;
  4. Claude Code part en tâche de fond, son jeton dans l'environnement — jamais dans la fiche.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
import json
import os
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import dev_tools


def _job(directory: Path, job_id: str, user: str, rc='0', log='', tool='role:codegen', age_s=0):
    (directory / f'{job_id}.json').write_text(json.dumps(
        {'id': job_id, 'tool': tool, 'command': [], 'user': user, 'pid': 0}), encoding='utf-8')
    (directory / f'{job_id}.log').write_text(log, encoding='utf-8')
    if rc is not None:
        rc_path = directory / f'{job_id}.rc'
        rc_path.write_text(rc, encoding='utf-8')
        if age_s:
            old = time.time() - age_s
            os.utime(rc_path, (old, old))


class FinishedJobIsAnnouncedOnceTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('dev_follow', password='x')
        self.tmp = Path(tempfile.mkdtemp(prefix='test_dev_jobs_'))
        patcher = mock.patch.object(dev_tools, 'jobs_dir', return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _notes(self):
        from wama.common.models import Notification
        return Notification.objects.filter(recipient=self.user, app='dev')

    def test_a_finished_job_is_announced_once_and_designates_itself(self):
        _job(self.tmp, '20261012-130634-d8b321', 'dev_follow', rc='1',
             log="gabarit tasks non rendable : aucune tâche lifecycle déclarée\n")
        self.assertEqual(1, dev_tools.notify_finished_jobs())
        note, = self._notes()
        self.assertEqual(('job_failed', 'DevJob', '20261012-130634-d8b321'),
                         (note.kind, note.object_type, note.object_id))
        self.assertIn('gabarit tasks non rendable', note.body)
        self.assertEqual(0, dev_tools.notify_finished_jobs(), "une seule annonce par tâche")

    def test_a_running_job_and_an_old_end_are_not_announced(self):
        _job(self.tmp, '20261012-130000-aaaaaa', 'dev_follow', rc=None)
        _job(self.tmp, '20261011-080000-bbbbbb', 'dev_follow', age_s=dev_tools.NOTIFY_MAX_AGE_S + 60)
        self.assertEqual(0, dev_tools.notify_finished_jobs())
        meta = json.loads((self.tmp / '20261011-080000-bbbbbb.json').read_text(encoding='utf-8'))
        self.assertTrue(meta['notified'], "une fin trop ancienne est marquée sans être annoncée")

    def test_a_claude_code_job_announces_its_answer_not_its_raw_log(self):
        answer = json.dumps({'result': 'Le builder du reader est déclaré dans apps.py.',
                             'total_cost_usd': 0.04, 'modelUsage': {}})
        _job(self.tmp, '20261012-140000-cccccc', 'dev_follow', log=answer, tool='claude_code')
        dev_tools.notify_finished_jobs()
        self.assertEqual('Le builder du reader est déclaré dans apps.py.', self._notes().get().body)

    def test_a_claude_code_write_job_says_there_is_nothing_to_validate_before_the_cut(self):
        """2026-11-01, fil n° 43 : le rapport coupé avait perdu « relancer gunicorn », et le
        modèle a inventé une proposition « à valider en base ». La note passe AVANT la coupure."""
        long_answer = 'Le Writer est joignable. ' + 'détail ' * 600 + 'Relancer gunicorn.'
        answer = json.dumps({'result': long_answer, 'total_cost_usd': 0.9, 'modelUsage': {}})
        _job(self.tmp, '20261101-143154-d135ab', 'dev_follow', log=answer, tool='claude_code:write')
        dev_tools.notify_finished_jobs()
        body = self._notes().get().body
        self.assertTrue(body.startswith(dev_tools.CLAUDE_CODE_WRITE_NOTE))
        self.assertIn('rapport tronqué', body)
        status = dev_tools.dev_job_status(self.user, '20261101-143154-d135ab')
        self.assertEqual(dev_tools.CLAUDE_CODE_WRITE_NOTE, status['next_step'])

    def test_a_read_only_claude_code_job_carries_no_such_note(self):
        """Contre-épreuve : sans écriture, rien n'a bougé dans le dépôt — la note serait fausse."""
        answer = json.dumps({'result': 'Rien à signaler.', 'total_cost_usd': 0.1, 'modelUsage': {}})
        _job(self.tmp, '20261101-150000-dddddd', 'dev_follow', log=answer, tool='claude_code')
        dev_tools.notify_finished_jobs()
        self.assertEqual('Rien à signaler.', self._notes().get().body)
        self.assertNotIn('next_step', dev_tools.dev_job_status(self.user, '20261101-150000-dddddd'))

    def test_a_job_whose_proposal_awaits_opens_the_queue_where_it_is_decided(self):
        """2026-11-05 (Fabien) : la fin du librarian disait « Propositions écrites (en attente de
        validation) » sans bouton « Ouvrir » vers la file du model manager."""
        from django.urls import reverse
        from wama.common.manifests.proposals import propose
        output = 'wama-dev-ai/outputs/library_fake_engine_2026-11-05_17-48.json'
        propose({'manifest_kind': 'library', 'schema_version': '1.0', 'key': 'fake_engine',
                 'name': 'fake-engine', 'world': 'transverse', 'visibility': 'public',
                 'projects': [], 'body': {'identity': {'summary': 'x'}}}, origin=output)
        _job(self.tmp, '20261105-164742-d7583f', 'dev_follow', tool='role:librarian',
             log=f"proposition : {output}\n")
        _job(self.tmp, '20261105-170000-eeeeee', 'dev_follow', tool='role:codegen',
             log="sortie : wama-dev-ai/outputs/codegen_nothing_waits.json\n")
        dev_tools.notify_finished_jobs()
        urls = dict(self._notes().values_list('object_id', 'url'))
        self.assertEqual(reverse('model_manager:index') + '#' + dev_tools.PROPOSALS_ANCHOR,
                         urls['20261105-164742-d7583f'])
        self.assertEqual('', urls['20261105-170000-eeeeee'],
                         "an output that no queue lists has no page where it is decided")


class ChannelFollowUpOfADevJobTest(TestCase):
    """La fin d'une tâche de dev revient dans le fil Discord qui l'a lancée."""

    def setUp(self):
        from django.utils import timezone

        from wama.gateway.models import ChannelLink
        self.user = get_user_model().objects.create_user('dev_channel', password='x')
        ChannelLink.objects.create(user=self.user, channel='discord', external_id='4242',
                                   confirmed_at=timezone.now())

    def test_the_end_is_posted_in_the_thread_that_launched_it(self):
        from wama.common.services import conversation_store
        from wama.common.utils.notifications import notify_in_app
        from wama.gateway import core
        from wama.gateway.models import ChannelCursor

        ChannelCursor.objects.update_or_create(channel='discord',
                                               defaults={'last_notification_id': 0})
        thread = conversation_store.thread(self.user, surface='discord', thread_key='salon-9')
        conversation_store.record_exchange(thread, 'lance codegen', {
            'response': 'lancé', 'model': 'm',
            'tool_steps': [{'tool': 'dev_run_role', 'args': {'role': 'codegen'},
                            'result': {'job_id': 'J-1', 'status': 'running'}}]})
        notify_in_app([self.user], 'job_done', "Tâche de développement « role:codegen » terminée",
                      body='Propositions écrites : x.json', app='dev', object_type='DevJob',
                      object_id='J-1')
        with mock.patch('wama.common.services.mcp_client.call_dev_tool',
                        return_value={'id': 'J-1', 'status': 'done'}) as status:
            follow_up, = core.collect_job_follow_ups('discord')
        self.assertEqual('salon-9', follow_up.thread)
        self.assertIn('x.json', follow_up.reply.text)
        self.assertEqual('dev_job_status', follow_up.step['tool'])
        status.assert_called_once()


class NoPollingInsideATurnTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('dev_poll', password='x')

    def test_a_second_status_of_a_running_job_is_not_relayed(self):
        from wama.common.services import assistant_engine, mcp_client
        usage = {'input_tokens': 0, 'output_tokens': 0}
        answers = iter(['{"tool": "dev_job_status", "args": {"job_id": "J-2"}}'] * 3 + ['lancé'])
        dev_tool = {'name': 'dev_job_status', 'description': '', 'args': ['job_id']}
        with mock.patch.object(mcp_client, 'dev_tools_for', return_value=[dev_tool]), \
             mock.patch.object(mcp_client, 'call_dev_tool',
                               return_value={'id': 'J-2', 'status': 'running'}) as relay, \
             mock.patch.object(assistant_engine, '_llm_call',
                               side_effect=lambda *a, **k: (next(answers), usage)):
            result = assistant_engine.run_assistant_turn(self.user, 'où en est J-2 ?',
                                                         provider='wama-dev-ai', model='m')
        relay.assert_called_once()
        # Les seuls statuts : le tour peut aussi charger la compétence du domaine (`charger_competence`
        # après le premier outil de développement), un geste distinct de celui qu'on surveille ici.
        statuses = [s for s in result['tool_steps'] if s['tool'] == 'dev_job_status']
        self.assertEqual(3, len(statuses))
        self.assertIn('déjà vérifié', statuses[1]['result']['next_step'])


class ClaudeCodeInTheBackgroundTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('dev_claude', password='x')

    def test_a_repository_change_is_refused_in_the_turn_and_points_to_the_background_tool(self):
        from wama import tool_api
        with mock.patch('wama.common.services.claude_code.subscription_allowed', return_value=True):
            out = tool_api.ask_claude_code(self.user, 'corrige le reader', write=True)
        self.assertIn('dev_claude_code', out['error'])

    def test_the_background_job_carries_the_token_in_its_environment_only(self):
        prepared = {'argv': ['claude', '-p', 'corrige le reader', '--output-format', 'json'],
                    'env': {'CLAUDE_CODE_OAUTH_TOKEN': 'sk-secret'}}
        with mock.patch('wama.common.services.claude_code.subscription_allowed', return_value=True), \
             mock.patch('wama.common.services.claude_code.prepare', return_value=prepared), \
             mock.patch.object(dev_tools, 'start_job', return_value={'job_id': 'J-3'}) as start:
            out = dev_tools.dev_claude_code(self.user, 'corrige le reader', write=True, model='opus')
        self.assertEqual('J-3', out['job_id'])
        args, kwargs = start.call_args
        self.assertEqual('claude_code:write', args[1])
        self.assertEqual(prepared['env'], kwargs['env'])
        self.assertNotIn('sk-secret', json.dumps([args[2], kwargs['shown']]))
        self.assertEqual('timeout', args[2][0], "un process détaché a une borne")

    def test_a_role_output_is_never_corrected_by_hand(self):
        """2026-11-07 (ACE-Step par l'assistant) : Claude Code reçu en écriture pour « corriger »
        l'anatomie dans le fichier d'`outputs/`. La proposition vit au magasin : refusé, le refus
        dit la route. Contre-épreuve : le même fichier se LIT."""
        task = ("Corriger wama-dev-ai/outputs/model_huggingface:ACE-Step_Ace-Step1.5_x.json : "
                "ajouter le composant manquant")
        prepared = {'argv': ['claude', '-p', task], 'env': {}}
        with mock.patch('wama.common.services.claude_code.subscription_allowed', return_value=True), \
             mock.patch('wama.common.services.claude_code.prepare', return_value=prepared), \
             mock.patch.object(dev_tools, 'start_job', return_value={'job_id': 'J-4'}) as start:
            with self.assertRaisesRegex(dev_tools.DevToolError, 'dev_run_role'):
                dev_tools.dev_claude_code(self.user, task, write=True)
            start.assert_not_called()
            self.assertEqual('J-4', dev_tools.dev_claude_code(self.user, task)['job_id'])

    def test_a_refused_profile_never_starts_a_job(self):
        with mock.patch('wama.common.services.claude_code.subscription_allowed', return_value=True), \
             mock.patch('wama.common.services.claude_code.prepare',
                        return_value={'error': 'profil 100 % local'}), \
             mock.patch.object(dev_tools, 'start_job') as start:
            out = dev_tools.dev_claude_code(self.user, 'corrige', write=True)
        self.assertEqual('profil 100 % local', out['error'])
        start.assert_not_called()


class StructuredArgumentsTest(TestCase):
    """2026-11-07 : `dev_run_role(args='{"catalog": "…"}')` à chaque intégration, refusé au premier
    appel. `dev_tools` reporte ses annotations : la signature lue portait `'dict'` en TEXTE, et le
    schéma MCP n'annonçait aucun type pour `args`. Le schéma dit désormais `object`, et un objet
    écrit en texte JSON se décode à la porte — la même règle sur les deux surfaces."""

    def test_the_dev_schema_announces_an_object_for_a_dict_parameter(self):
        from wama.tool_api import input_schema_for
        schema = input_schema_for(dev_tools.dev_run_role)
        self.assertEqual('object', schema['properties']['args'].get('type'), schema)

    def test_an_object_written_as_json_text_reaches_the_tool_as_an_object(self):
        from wama.tool_api import decode_structured_args
        decoded = decode_structured_args(dev_tools.dev_run_role,
                                         {'role': 'model', 'args': '{"catalog": "huggingface:Org/X"}'})
        self.assertEqual({'catalog': 'huggingface:Org/X'}, decoded['args'])
        self.assertEqual('model', decoded['role'])
        # Contre-épreuve : un texte qui n'est pas l'objet annoncé reste tel quel — l'outil le
        # refuse alors lui-même, en disant ce qu'il attend.
        for raw in ('catalog=huggingface:Org/X', '["a"]'):
            self.assertEqual(raw, decode_structured_args(dev_tools.dev_run_role, {'args': raw})['args'])


class IntegrationStepTravelsWithTheOutputTest(TestCase):
    """2026-11-07 : l'outil de plan d'intégration existait, l'assistant ne l'appelait pas et
    improvisait l'étape suivante. Elle voyage désormais avec ce qu'il lit : la fin de la tâche du
    rôle, son état, la lecture de sa sortie, la réponse de « Valider »."""

    KEY = 'huggingface:Org/Unserved'

    def setUp(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key=self.KEY, name='Unserved', model_type='music',
                               source='huggingface', is_downloaded=True, is_available=True,
                               capabilities={'task': 'text-to-music'},
                               composition={'runtime': {'engine': 'no_such_engine_2026'},
                                            'components': [{'role': 'model', 'pattern': '*.pt'}]})
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, self.root, True)
        (self.root / 'wama-dev-ai' / 'outputs').mkdir(parents=True)

    def _output(self, name, content):
        (self.root / 'wama-dev-ai' / 'outputs' / name).write_text(json.dumps(content), encoding='utf-8')
        return f'wama-dev-ai/outputs/{name}'

    def test_a_model_role_output_carries_the_next_step_of_the_route(self):
        from wama.tool_api import plan_model_integration
        relative = self._output('model_x.json', {'role': 'model', 'manifest': {
            'manifest_kind': 'model', 'key': self.KEY}})
        with mock.patch.object(dev_tools, 'base_dir', return_value=self.root):
            step = dev_tools.integration_step([relative])
            read = dev_tools.dev_read_output(None, relative)
        plan = plan_model_integration(None, self.KEY)
        self.assertEqual({self.KEY: {'next_step': plan['next_step'],
                                     'human_gesture': plan['human_gesture']}}, step)
        self.assertIn('backend', plan['human_gesture'])
        self.assertEqual(step, read['integration_route'])

    def test_an_output_about_no_model_carries_no_route(self):
        """Contre-épreuve : une glu, un manifeste de librairie — pas de route de modèle."""
        relative = self._output('librarian_x.json', {'role': 'librarian', 'manifest': {
            'manifest_kind': 'library', 'key': 'somelib'}})
        with mock.patch.object(dev_tools, 'base_dir', return_value=self.root):
            self.assertEqual({}, dev_tools.integration_step([relative]))

    def test_validating_says_the_next_step(self):
        from wama.model_manager.views import _integration_next_step
        step = _integration_next_step(self.KEY)
        self.assertIn('backend', step['human_gesture'])
        self.assertEqual({}, _integration_next_step(''))
