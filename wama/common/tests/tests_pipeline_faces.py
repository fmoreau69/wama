"""The faces of the common preview ARE the processes of the card's pipeline (`ROUTE §F3b`,
2026-10-12 — Fabien : « le pipeline étant l'unité commune à tout WAMA, la preview pourrait
s'adapter au pipeline »).

Held here :
  - INVENTORY (step 0) : every process of every declared pipeline has a readable result — a
    text (`ProcessSpec.result`, decision n°1 of the day : « le process porte sa sortie ») or
    files (`outputs`) — or is LISTED with its reason. The list can only shrink ;
  - DERIVATION : a process with something to show is a face, in the order of the graph, typed
    by the output port of its function (detections over the input, a score as text, a voice as
    audio) ; a face that shows what the Input, the Output or a previous face shows is not one
    step more ; a reserved side is never a face ; a broken reader breaks no other face ; a file
    announced but gone from the disk is not shown ; an app without pipeline keeps Input | Output ;
  - the transcriber, end to end over HTTP : « Locuteurs », « Résumé », « Cohérence » between its
    Input and its Output (the transcription, which IS its Output, is not repeated) ;
  - the declaration travels with the pipeline : exported to the manifest, read back by the
    generator ;
  - NOTHING the apps' own result modals showed is lost (2026-10-13, Fabien : « on ne doit rien
    perdre, on complète le commun ») : the summary as markdown, the coherence as a REPORT (score
    coloured by its level, notes, the proposal set against the checked text), a word count on
    every text face.
The anonymizer's « Détection » face (the process `detect`) keeps its own parity test,
`tests_preview_faces`.
"""
import ast
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

#: Processes with NO declared readable result, and why — this list can only SHRINK. A process
#: that gains one must leave it (the test fails on a useless entry, like every WAMA exemption).
UNREADABLE = {
    'anonymizer.blur': "its blurred media is kept apart by the Output process (`native_outputs`) "
                       "only when the Output transforms it — the face of a kept original is to "
                       "come",
    'enhancer.generate': "same : its original is kept by the Output process when transformed",
    'imager.generate': "same : its original is kept by the Output process when transformed",
    'synthesizer.generate': "same : its original is kept by the Output process when transformed",
    'avatarizer.enhance': "it renders the card's Output itself (`output_step(transform=)` under "
                          "another key than `output`) : its face IS the Output",
    'transcriber.align': "it re-times words ; its effect reads on the segments (a `segments` "
                         "renderer is to come)",
}


def _real_pipelines():
    from wama.common.catalog import function_catalog
    from wama.common.sandbox import sandbox_labels
    from wama.common.services.process_pipeline import APP_PIPELINES
    function_catalog.load_all()
    twins = set(sandbox_labels())
    return {app: pipe for app, pipe in APP_PIPELINES.items()
            if app not in twins and not app.startswith('demo')}


class EveryProcessHasAReadableResultTest(SimpleTestCase):
    databases = '__all__'

    def test_every_process_shows_something_or_says_why(self):
        from wama.common.services.output_process import OUTPUT_KEY
        unreadable = {f'{app}.{spec.key}'
                      for app, pipe in _real_pipelines().items() for spec in pipe.specs
                      if not (spec.result or spec.outputs or spec.key == OUTPUT_KEY)}
        self.assertEqual(set(UNREADABLE), unreadable,
                         'a new process without readable result, or an entry that became useless')

    def test_each_declared_reader_resolves(self):
        from wama.common.catalog.function_catalog import resolve_impl
        declared = [(app, spec) for app, pipe in _real_pipelines().items()
                    for spec in pipe.specs if isinstance(spec.result, str) and spec.result]
        self.assertTrue(declared, 'the instrument sees the declarations')
        for app, spec in declared:
            with self.subTest(process=f'{app}.{spec.key}'):
                self.assertTrue(callable(resolve_impl(spec.result)))

    def test_the_declaration_travels_with_the_pipeline(self):
        """Exported in the `pipeline` manifest, read back for the generator — like `eta`."""
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        from wama.common.manifests.codegen.pipeline_decl import process_specs
        pipe = _real_pipelines()['transcriber']
        read = {s['key']: s['result'] for s in process_specs(pipe.manifest())}
        self.assertEqual('transcriber.utils.transcript_documents:summary_text', read['summarize'])
        self.assertEqual('', read['align'])
        manifest = json.loads((Path(settings.BASE_DIR) / 'manifests' / 'apps' / 'transcriber.json')
                              .read_text(encoding='utf-8'))
        # The real transcriber runs its pipeline from a worker the manifest does not declare as
        # its lifecycle task (not generated) : named here, only to reach the rendering.
        manifest['body'].setdefault('processing', {})['tasks'] = [
            {'function': 'transcribe', 'lifecycle': True}]
        src, reason = render_function_specs(manifest)
        self.assertIsNotNone(src, reason)
        rendered = {}
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'ProcessSpec':
                rendered[node.args[0].value] = {k.arg: getattr(k.value, 'value', None)
                                                for k in node.keywords}
        self.assertEqual(read['summarize'], rendered['summarize'].get('result'))
        self.assertNotIn('result', rendered['align'])
        # The FORM of the result travels the same way (2026-10-13).
        forms = {s['key']: s['result_format'] for s in process_specs(pipe.manifest())}
        self.assertEqual(('markdown', 'coherence', ''),
                         (forms['summarize'], forms['coherence'], forms['align']))
        self.assertEqual('markdown', rendered['summarize'].get('result_format'))
        self.assertEqual('coherence', rendered['coherence'].get('result_format'))
        self.assertNotIn('result_format', rendered['align'])

    def test_the_coherence_checks_are_shown_as_reports(self):
        """Every process that runs the common coherence brick declares the REPORT form — the
        describer and transcriber modals showed its score in colour and its proposal side by
        side ; a plain text face would lose both."""
        coherence = [(app, spec) for app, pipe in _real_pipelines().items() for spec in pipe.specs
                     if spec.key == 'coherence']
        self.assertEqual({'describer', 'transcriber'}, {app for app, _ in coherence})
        for app, spec in coherence:
            with self.subTest(app=app):
                self.assertEqual('coherence', spec.result_format)


class _MediaRootMixin:

    def _media_root(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root, MEDIA_URL='/media/')
        media.enable()
        self.addCleanup(media.disable)

    def _file(self, rel, data=b'x'):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as out:
            out.write(data)
        return rel


class ProcessFacesTest(_MediaRootMixin, TestCase):

    def setUp(self):
        self._media_root()
        self.request = RequestFactory().get('/')
        self.user = get_user_model().objects.create_user('pipeline_faces_owner', password='x')

    def _faces(self, app, item, input_data=None, output_data=None):
        from wama.common.utils.preview_utils import _process_faces
        return _process_faces(app, item, self.request, input_data, output_data)

    def _face_of(self, rel):
        from wama.common.utils.preview_utils import _media_face
        return _media_face(f'/media/{rel}', self.request)

    def test_the_score_of_the_composer_is_a_face_and_its_audio_is_the_output(self):
        from wama.composer.models import ComposerGeneration
        audio = self._file('composer/output/song.wav')
        gen = ComposerGeneration(user=self.user, prompt='p', audio_output=audio,
                                 planned_score=self._file('composer/output/song.abc', b'X:1'))
        faces = self._faces('composer', gen, output_data=self._face_of(audio))
        self.assertEqual(['plan'], list(faces), 'the render IS the Output : not repeated')
        meta, data = faces['plan']
        self.assertEqual({'key': 'plan', 'label': 'Partition', 'icon': 'fa-music'}, meta)
        self.assertEqual('text/vnd.abc', data['mime_type'], 'a score opens as text, everywhere')

    def test_a_file_gone_from_the_disk_is_not_shown(self):
        from wama.composer.models import ComposerGeneration
        gen = ComposerGeneration(user=self.user, prompt='p', planned_score='composer/output/gone.abc')
        self.assertEqual({}, self._faces('composer', gen))

    def test_the_voice_of_the_avatarizer_is_a_face_between_the_avatar_and_the_video(self):
        from wama.avatarizer.models import AvatarJob
        avatar = self._file('avatarizer/input/face.png')
        video = self._file('avatarizer/output/talk.mp4')
        job = AvatarJob(user=self.user, mode='pipeline', avatar_upload=avatar, output_video=video,
                        audio_input=self._file('avatarizer/output/voice.wav'))
        faces = self._faces('avatarizer', job, self._face_of(avatar), self._face_of(video))
        self.assertEqual(['speak'], list(faces), 'the animation IS the Output : not repeated')
        self.assertEqual(('Voix', 'fa-volume-high'),
                         (faces['speak'][0]['label'], faces['speak'][0]['icon']))
        self.assertTrue(faces['speak'][1]['mime_type'].startswith('audio/'))

    def test_a_voice_that_is_the_input_is_not_one_step_more(self):
        from wama.avatarizer.models import AvatarJob
        voice = self._file('avatarizer/input/voice.wav')
        job = AvatarJob(user=self.user, mode='standalone', audio_input=voice)
        self.assertEqual({}, self._faces('avatarizer', job, self._face_of(voice)))

    def test_an_app_without_pipeline_keeps_input_and_output(self):
        self.assertEqual({}, self._faces('accounts', self.user))

    def test_a_reserved_side_is_never_a_face_and_a_broken_reader_breaks_no_other(self):
        from wama.common.services.process_pipeline import AppPipeline, ProcessSpec

        def broken(item):
            raise RuntimeError('boom')

        pipe = AppPipeline('demo_faces', (
            ProcessSpec('first', label='Premier', result=lambda item: 'un texte'),
            ProcessSpec('broken', depends_on=('first',), result=broken),
            ProcessSpec('output', depends_on=('broken',), result=lambda item: 'la sortie'),
            ProcessSpec('same', depends_on=('output',), result=lambda item: 'un texte'),
        ), label='Demo')
        with mock.patch('wama.common.services.process_pipeline.pipeline_of', return_value=pipe):
            faces = self._faces('demo_faces', self.user)
        self.assertEqual(['first'], list(faces), 'broken : nothing ; output : reserved ; same : '
                                                 'shows what « first » shows')
        self.assertEqual({'name': 'Premier', 'mime_type': 'text/plain', 'content': 'un texte'},
                         faces['first'][1])

    def test_a_markdown_result_is_served_formatted_and_neutralized(self):
        # 2026-10-13 : the Describer's own modal formatted its summary, the common face showed
        # the raw `##`. The process DECLARES the form ; the text stays under `content` (Copy).
        from wama.common.services.process_pipeline import AppPipeline, ProcessSpec
        text = '## Synthèse\n\n- **un** point\n\n<script>alert(1)</script>'
        pipe = AppPipeline('demo_faces', (
            ProcessSpec('sum', label='Résumé', result=lambda item: text, result_format='markdown'),
            ProcessSpec('raw', depends_on=('sum',), result=lambda item: '## brut'),
        ), label='Demo')
        with mock.patch('wama.common.services.process_pipeline.pipeline_of', return_value=pipe):
            faces = self._faces('demo_faces', self.user)
        formatted, raw = faces['sum'][1], faces['raw'][1]
        self.assertEqual(('text/markdown', text), (formatted['mime_type'], formatted['content']))
        self.assertIn('<h2', formatted['html'])
        self.assertIn('<strong>un</strong>', formatted['html'])
        self.assertNotIn('<script>', formatted['html'], 'raw HTML is never rendered')
        self.assertNotIn('html', raw, 'a plain text result stays plain')

    def test_a_coherence_report_is_served_with_its_level_and_its_text(self):
        from wama.common.services.process_pipeline import AppPipeline, ProcessSpec
        from wama.common.utils.llm_utils import build_coherence_report
        reports = {key: build_coherence_report(score, 'n1\n\n n2 ', 'proposé', 'vérifié')
                   for key, score in (('high', 80), ('mid', 50), ('low', 49))}
        pipe = AppPipeline('demo_faces', tuple(
            ProcessSpec(key, label=key, result=(lambda item, r=report: r), result_format='coherence')
            for key, report in reports.items()), label='Demo')
        with mock.patch('wama.common.services.process_pipeline.pipeline_of', return_value=pipe):
            faces = self._faces('demo_faces', self.user)
        self.assertEqual(['success', 'warning', 'danger'],
                         [faces[k][1]['coherence']['level'] for k in ('high', 'mid', 'low')])
        high = faces['high'][1]
        self.assertEqual({'score': 80, 'level': 'success', 'notes': ['n1', 'n2'],
                          'suggestion': 'proposé', 'original': 'vérifié'}, high['coherence'])
        self.assertEqual('Score : 80/100\n\nRemarques :\n• n1\n• n2\n\nVersion proposée :\nproposé',
                         high['content'], 'the text Copy takes')
        self.assertIsNone(build_coherence_report(None, '', '', 'x'), 'nothing checked : no report')

    def test_an_unknown_result_form_is_refused_at_declaration(self):
        from wama.common.services.process_pipeline import AppPipeline, ProcessSpec
        with self.assertRaises(ValueError):
            AppPipeline('demo_faces', (ProcessSpec('a', result_format='rst'),), label='Demo')


class TranscriberFacesTest(_MediaRootMixin, TestCase):
    """End to end : the endpoint the panel and the viewer read (`/common/preview/<app>/<pk>/`)."""

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self._media_root()
        self.user = get_user_model().objects.create_user('pipeline_faces_listener', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def _transcript(self, **kw):
        from wama.transcriber.models import Transcript
        return Transcript.objects.create(user=self.user, text='Bonjour à tous.', status='SUCCESS',
                                         audio=self._file('transcriber/input/a.wav'), **kw)

    def _preview(self, t, side=None):
        url = f'/common/preview/transcriber/{t.pk}/' + (f'?side={side}' if side else '')
        return self.client.get(url).json()

    def test_its_processes_are_faces_between_its_input_and_its_output(self):
        from wama.transcriber.models import TranscriptSegment
        t = self._transcript(summary='Un résumé.', coherence_score=90)
        TranscriptSegment.objects.create(transcript=t, speaker_id='SPEAKER_00', start_time=0,
                                         end_time=1, text='Bonjour à tous.')
        sides = self._preview(t)['sides']
        self.assertTrue(sides['has_input'] and sides['has_output'])
        self.assertEqual([('diarize', 'Locuteurs'), ('summarize', 'Résumé'),
                          ('coherence', 'Cohérence')],
                         [(f['key'], f['label']) for f in sides['faces']],
                         'the transcription IS the Output : it is not repeated as a face')
        summary = self._preview(t, 'summarize')
        self.assertEqual(('summarize', 'Un résumé.'), (summary['side'], summary['content']))
        self.assertIn('<p>Un résumé.</p>', summary['html'], 'the summary is declared markdown')
        self.assertEqual('Bonjour à tous.', self._preview(t, 'output')['content'])

    def test_its_summary_lists_and_its_coherence_report_reach_the_viewer(self):
        # What the transcriber's own modal showed : key points and actions as lists, the score
        # with its level, the proposal set against the transcription.
        t = self._transcript(summary='Un résumé.', key_points=['a'], action_items=['c'],
                             coherence_score=45, coherence_notes='n1',
                             coherence_suggestion='Bonjour à tous !')
        summary = self._preview(t, 'summarize')['html']
        self.assertIn('<li>a</li>', summary)
        self.assertIn('<li>c</li>', summary)
        report = self._preview(t, 'coherence')['coherence']
        self.assertEqual({'score': 45, 'level': 'danger', 'notes': ['n1'],
                          'suggestion': 'Bonjour à tous !', 'original': 'Bonjour à tous.'}, report)

    def test_before_its_optional_processes_it_has_no_face(self):
        sides = self._preview(self._transcript())['sides']
        self.assertEqual([], sides['faces'])
        self.assertEqual('input', sides['compare_base'])


class ViewerDrawsTheReportTest(SimpleTestCase):
    """The viewer's drawing of a report and its word count — pure functions of the brick, in V8."""

    def setUp(self):
        import importlib.util
        if importlib.util.find_spec('py_mini_racer') is None:
            self.skipTest('py_mini_racer absent de ce venv')
        from py_mini_racer import MiniRacer
        from .tests_cap_from_js import FAKE_DOM, JS
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))

    def _html(self, report, compact=False):
        return self.v8.eval(f'window.WamaMediaPreview.coherenceHtml({json.dumps(report)}, '
                            f'{json.dumps(compact)})')

    def test_the_score_is_coloured_and_the_proposal_set_against_the_original(self):
        html = self._html({'score': 42, 'level': 'danger', 'notes': ['<b>n1</b>'],
                           'suggestion': 'proposé', 'original': 'vérifié'})
        self.assertIn('badge bg-danger fs-5', html)
        self.assertIn('42/100', html)
        self.assertIn('&lt;b&gt;n1&lt;/b&gt;', html, 'every text is escaped')
        self.assertIn('class="row mt-3"', html, 'side by side in the viewer')
        self.assertLess(html.index('vérifié'), html.index('proposé'))
        self.assertNotIn('row mt-3', self._html({'score': 42, 'level': 'danger',
                                                 'suggestion': 'p', 'original': 'o'}, True),
                         'one under the other in the panel')

    def test_without_a_proposal_there_are_no_columns_and_an_unknown_level_is_neutral(self):
        html = self._html({'score': 90, 'level': '" onmouseover="x', 'notes': []})
        self.assertIn('badge bg-secondary', html)
        self.assertNotIn('wama-coherence-original', html)
        self.assertNotIn('<ul', html)

    def test_a_text_face_counts_its_words(self):
        label = lambda text: self.v8.eval(f'window.WamaMediaPreview.wordsLabel({json.dumps(text)})')
        self.assertEqual(('3 mots', '1 mot', ''), (label(' un  deux\ntrois '), label('un'), label('  ')))
