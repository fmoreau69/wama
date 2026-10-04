"""The grid criterion `process_start_common` (2026-10-04) — measured on FICTITIOUS apps ; the real
state of the fleet is read by `check_app_conformity`.

It is the first criterion that looks at the PIPELINE of an app : an app that declares one must
route the ▶ of a process through the common factory (`process_views.make_process_start_view`).
"""
from django.test import SimpleTestCase

from wama.common.tests import tests_queue_delete_contract as contract

DECLARED = "PIPELINE = register_app_pipeline('app', (ProcessSpec('a'),), label='x')\n"


class ProcessStartCriterionTest(SimpleTestCase):

    _app = contract.CriteresDeLaGrilleTest._app

    def _verdict(self, **files):
        f, cc = self._app({name.replace('__', '.'): text for name, text in files.items()})
        criterion = next(c for c in cc.CRITERIA if c.key == 'process_start_common')
        return criterion.fn(f)

    def test_the_factory_alone_is_green(self):
        state, evidence = self._verdict(
            function_specs__py=DECLARED,
            views__py="start_process = make_process_start_view(work_model=M, task_for=t)\n")
        self.assertIs(state, True)
        self.assertIn('views.py:1', evidence)

    def test_a_hand_written_view_is_red_and_names_the_factory(self):
        state, evidence = self._verdict(
            function_specs__py=DECLARED,
            views__py="def start_process(request, pk, process):\n    pass\n")
        self.assertIs(state, False)
        self.assertIn('make_process_start_view', evidence)

    def test_a_start_view_that_takes_the_process_beside_the_factory_is_partial(self):
        state, _ = self._verdict(
            function_specs__py=DECLARED,
            views__py=("start_process = make_process_start_view(work_model=M, task_for=t)\n"
                       "def audio_start(request, pk, process=None):\n    pass\n"))
        self.assertEqual('partial', state)

    def test_a_declared_pipeline_without_any_run_button_is_red(self):
        state, evidence = self._verdict(function_specs__py=DECLARED, views__py="x = 1\n")
        self.assertIs(state, False)
        self.assertIn('sans ▶ par process', evidence)

    def test_an_app_with_a_single_process_is_not_concerned(self):
        state, _ = self._verdict(views__py="def start(request, pk):\n    pass\n")
        self.assertIsNone(state)

    def test_a_comment_naming_the_factory_does_not_make_it_green(self):
        state, _ = self._verdict(
            function_specs__py=DECLARED,
            views__py="# make_process_start_view( viendra plus tard\nx = 1\n")
        self.assertIs(state, False)
