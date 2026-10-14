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
        self.assertEqual(3, len(result['tool_steps']))
        self.assertIn('déjà vérifié', result['tool_steps'][1]['result']['next_step'])


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

    def test_a_refused_profile_never_starts_a_job(self):
        with mock.patch('wama.common.services.claude_code.subscription_allowed', return_value=True), \
             mock.patch('wama.common.services.claude_code.prepare',
                        return_value={'error': 'profil 100 % local'}), \
             mock.patch.object(dev_tools, 'start_job') as start:
            out = dev_tools.dev_claude_code(self.user, 'corrige', write=True)
        self.assertEqual('profil 100 % local', out['error'])
        start.assert_not_called()
