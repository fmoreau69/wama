"""Chaining the PROCESSES of a declared pipeline inside the common task skeleton —
`task_skeleton.run_process_steps` (`WAMA_APP_GENERATION_ROUTE §10.6`, provisional until the
common engine P3). Held here: the next process reads what the previous one wrote, progress is
split per process, and a failing process fails the task.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.utils.task_skeleton import run_process_steps


class _Ctx:
    app_id, user_id = 'converter', None

    def __init__(self, item):
        self.item, self.progress_seen, self.lines = item, [], []

    def progress(self, pct, msg=None):
        self.progress_seen.append(pct)

    def console(self, message, level=None):
        self.lines.append(message)


class RunProcessStepsTest(TestCase):

    def setUp(self):
        from wama.converter.models import ConversionJob
        user = get_user_model().objects.create_user('steps_owner', password='x')
        self.item = ConversionJob.objects.create(user=user, input_filename='in.png')

    def test_the_second_process_reads_what_the_first_one_wrote(self):
        seen = {}

        def draft(item, ctx):
            ctx.progress(100)
            return {'fields': {'output_format': 'mp4'}, 'models': ['m:a']}

        def render(item, ctx):
            seen['output_format'] = item.output_format
            ctx.progress(50)
            return {'fields': {'media_type': 'video'}, 'models': ['m:a', 'm:b'], 'label': 'fin'}

        ctx = _Ctx(self.item)
        merged = run_process_steps(self.item, ctx,
                                   [('draft', 'Rédiger', draft), ('render', 'Rendre', render)])
        self.assertEqual('mp4', seen['output_format'], 'the 2nd process did not see the 1st one')
        self.item.refresh_from_db()
        self.assertEqual(('mp4', 'video'), (self.item.output_format, self.item.media_type))
        self.assertEqual({'output_format': 'mp4', 'media_type': 'video'}, merged['fields'])
        self.assertEqual(['m:a', 'm:b'], merged['models'])
        self.assertEqual('fin', merged['label'])
        self.assertEqual([50, 75, 100], ctx.progress_seen, 'progress is not split per process')
        self.assertEqual(['▶ Rédiger', '▶ Rendre'], ctx.lines)

    def test_a_failing_process_stops_the_chain_and_raises(self):
        called = []

        def boom(item, ctx):
            raise RuntimeError('panne du fond')

        def never(item, ctx):
            called.append(True)

        with self.assertRaises(RuntimeError):
            run_process_steps(self.item, _Ctx(self.item), [('a', 'A', boom), ('b', 'B', never)])
        self.assertEqual([], called)
