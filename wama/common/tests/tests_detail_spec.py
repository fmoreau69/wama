"""The DECLARATIVE detail of an element (`register_app_detail_spec`) — its vocabulary, every app.

Session of 2026-10-03 (Fabien: « aligner les applications, uniformiser, porter au commun »). Six
apps described their inspector detail with a hand-written Python function. Read one by one, five
of them did nothing a declaration cannot say — provided the spec learnt four generic forms:
the first non-empty field of a list, a value chosen by the PRESENCE of a field, a truncated text,
and a setting whose label is the one of the schema (`params.py`), a true value being shown « Oui »
by the inspector for every app. Before the switch, each old adapter and its candidate spec were
compared on unsaved witness elements: 16 of 19 strictly identical, the 3 others being the
transcriber's labels now read from its schema.

Here: the forms themselves, then — no app named — every registered spec against its model, and
the declared list of the code adapters that remain.
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.utils.detail_registry import DetailRegistry, detail_from_spec, spec_value

#: Code adapters that REMAIN, each with the reason the spec cannot say it. An app registering a
#: code adapter without being declared here fails the test: the declarative way is the default.
CODE_ADAPTERS = {
    'imager': 'schema chosen per element (image or video), a COLLECTION of results, a role that '
              'depends on what came out',
    'audio_enhancer': 'second domain of the enhancer: the spec reads ONE schema per app name',
}


def _element(**fields):
    fields.setdefault('status', 'PENDING')
    return SimpleNamespace(**fields)


class SpecValueFormsTest(SimpleTestCase):

    def test_a_field_name_reads_the_field(self):
        self.assertEqual('whisper', spec_value(_element(backend='whisper'), 'backend'))

    def test_a_constant_and_a_translated_field_are_unchanged(self):
        self.assertEqual('video', spec_value(_element(), {'const': 'video'}))
        table = {'field': 'kind', 'map': {'music': 'audio_music'}}
        self.assertEqual('audio_music', spec_value(_element(kind='music'), table))
        self.assertIsNone(spec_value(_element(kind='other'), table))

    def test_a_list_gives_the_first_field_that_is_not_empty(self):
        form = ['avatar', 'audio']
        self.assertEqual('a.png', spec_value(_element(avatar='a.png', audio='b.wav'), form))
        self.assertEqual('b.wav', spec_value(_element(avatar='', audio='b.wav'), form))
        self.assertIsNone(spec_value(_element(avatar='', audio=None), form))

    def test_a_value_follows_the_presence_of_any_of_the_fields(self):
        form = {'when_any': ['text_file', 'text'], 'then': 'text', 'else': 'audio'}
        self.assertEqual('text', spec_value(_element(text_file='', text='bonjour'), form))
        self.assertEqual('audio', spec_value(_element(text_file='', text=''), form))

    def test_nothing_declared_gives_nothing(self):
        for form in (None, '', [], {}):
            self.assertIsNone(spec_value(_element(), form))


class ExtraSettingsTest(SimpleTestCase):

    def _extra(self, element, entries, schema=()):
        with mock.patch('wama.common.utils.param_schema.schema_for_app', return_value=list(schema)):
            return detail_from_spec(element, {'extra': entries}, 'witness').get('extra') or {}

    def test_a_long_text_is_cut_and_a_short_one_is_left(self):
        entry = [{'label': 'Prompt', 'field': 'prompt', 'max_chars': 10}]
        self.assertEqual({'Prompt': 'abcdefghij…'}, self._extra(_element(prompt='abcdefghijKLM'), entry))
        self.assertEqual({'Prompt': 'abcdefghij'}, self._extra(_element(prompt='abcdefghij'), entry))

    def test_an_entry_without_a_label_takes_the_label_of_the_schema(self):
        schema = [{'name': 'enable_diarization', 'label': 'Identifier les locuteurs'}]
        extra = self._extra(_element(enable_diarization=True), [{'field': 'enable_diarization'}], schema)
        self.assertEqual({'Identifier les locuteurs': True}, extra,
                         'the data stays a boolean — the inspector says « Oui »')

    def test_a_declared_label_wins_and_an_unknown_field_keeps_its_name(self):
        schema = [{'name': 'kind', 'label': 'Schema label'}]
        self.assertEqual({'Type': 'x'}, self._extra(_element(kind='x'), [{'label': 'Type', 'field': 'kind'}], schema))
        self.assertEqual({'page_count': 3}, self._extra(_element(page_count=3), [{'field': 'page_count'}], schema))

    def test_a_false_or_empty_setting_is_not_shown(self):
        entries = [{'label': 'A', 'field': 'a'}, {'label': 'B', 'field': 'b'}]
        self.assertEqual({}, self._extra(_element(a=False, b=''), entries))


def _declared_specs():
    """(app, model, spec) for every app registered the declarative way — sandbox twins left out
    (their generated `apps.py` carries the spec of their source)."""
    from wama.common.app_registry import APP_CATALOG
    out = []
    for app in DetailRegistry.registered_apps():
        entry = DetailRegistry.get(app)
        if entry.get('spec') and not (APP_CATALOG.get(app) or {}).get('sandbox'):
            out.append((app, entry['model'], entry['spec']))
    return out


def _named_fields(form):
    """The model attributes a spec value reads."""
    if isinstance(form, str):
        return [form]
    if isinstance(form, (list, tuple)):
        return list(form)
    if isinstance(form, dict):
        return list(form.get('when_any') or ()) + ([form['field']] if form.get('field') else [])
    return []


VALUE_KEYS = ('source_file', 'source_type', 'engine', 'engine_effective', 'result_file',
              'result_role', 'result_text', 'source_text')
KNOWN_KEYS = set(VALUE_KEYS) | {'extra', 'extra_from_params', 'aliases', 'result_tabs'}


class EveryRegisteredSpecIsSoundTest(SimpleTestCase):

    def test_the_fleet_is_measured(self):
        apps = [app for app, _model, _spec in _declared_specs()]
        self.assertGreaterEqual(len(apps), 9, apps)

    def test_a_spec_only_uses_the_known_vocabulary(self):
        for app, _model, spec in _declared_specs():
            with self.subTest(app=app):
                self.assertEqual(set(), set(spec) - KNOWN_KEYS, 'keys the resolver never reads')
                for key in VALUE_KEYS:
                    form = spec.get(key)
                    if isinstance(form, dict):
                        self.assertTrue({'const'} & set(form) or {'field', 'map'} <= set(form)
                                        or {'when_any', 'then'} <= set(form), (key, form))

    def test_every_field_a_spec_names_exists_on_its_model(self):
        """A misspelt field is read as empty by `getattr` — the line would vanish silently."""
        for app, model, spec in _declared_specs():
            names = [n for key in VALUE_KEYS for n in _named_fields(spec.get(key))]
            names += [e.get('field') for e in (spec.get('extra') or [])]
            names += list(spec.get('aliases') or {})
            if isinstance(spec.get('extra_from_params'), str):
                names.append(spec['extra_from_params'])
            missing = sorted(n for n in names if n and not hasattr(model, n))
            with self.subTest(app=app):
                self.assertEqual([], missing, f'{model.__name__} has no such attribute')

    def test_a_setting_without_a_label_is_a_setting_of_the_schema(self):
        """Its label comes from `params.py` — outside the schema it would show a raw field name."""
        from wama.common.utils.param_schema import schema_for_app
        for app, _model, spec in _declared_specs():
            labels = {p.get('name') for p in (schema_for_app(app) or []) if p.get('label')}
            unlabelled = sorted(e.get('field') for e in (spec.get('extra') or [])
                                if not e.get('label') and e.get('field') not in labels)
            with self.subTest(app=app):
                self.assertEqual([], unlabelled)

    def test_a_spec_is_data_the_manifest_can_carry(self):
        for app, _model, spec in _declared_specs():
            with self.subTest(app=app):
                self.assertEqual(spec, json.loads(json.dumps(spec)), 'not plain JSON data')

    def test_the_code_adapters_that_remain_are_declared_with_their_reason(self):
        from wama.common.app_registry import APP_CATALOG
        coded = sorted(app for app in DetailRegistry.registered_apps()
                       if not DetailRegistry.get(app).get('spec')
                       and not (APP_CATALOG.get(app) or {}).get('sandbox'))
        self.assertEqual(sorted(CODE_ADAPTERS), coded,
                         'a code adapter appeared (use the spec) or a declared one is gone')


class PortedAppsSayWhatTheirAdaptersSaidTest(SimpleTestCase):
    """The five apps switched on 2026-10-03 — what each adapter computed, said by the spec."""

    def _detail(self, app, **fields):
        entry = DetailRegistry.get(app)
        instance = entry['model']()
        for name, value in fields.items():
            setattr(instance, name, value)
        return entry['adapter'](instance)

    def test_the_avatarizer_source_is_the_avatar_else_the_audio(self):
        self.assertIn('voix.wav', self._detail('avatarizer', audio_input='a/voix.wav')['source_file'])
        both = self._detail('avatarizer', avatar_upload='a/tete.png', audio_input='a/voix.wav')
        self.assertIn('tete.png', both['source_file'])
        self.assertEqual(('video', 'musetalk'), (both['source_type'], both['engine']))

    def test_the_synthesizer_source_type_follows_the_presence_of_a_text(self):
        self.assertEqual('text', self._detail('synthesizer', text_content='bonjour')['source_type'])
        self.assertEqual('audio', self._detail('synthesizer', voice_reference='s/ref.wav')['source_type'])

    def test_the_composer_role_is_its_type_and_its_prompt_is_cut(self):
        sfx = self._detail('composer', prompt='p' * 80, generation_type='sfx',
                           model='composer:audiogen-medium', audio_output='c/pluie.wav')
        self.assertEqual('audio_sfx', sfx['result_role'])
        self.assertEqual('p' * 60 + '…', sfx['extra']['Prompt'])
        music = self._detail('composer', prompt='piano', generation_type='music', audio_output='c/m.wav')
        self.assertEqual(('audio_music', 'Musique'), (music['result_role'], music['extra']['Type']))

    def test_the_anonymizer_role_follows_the_category_of_its_media(self):
        image = self._detail('anonymizer', file='a/x.jpg', media_type='image', output_file='a/y.jpg')
        self.assertEqual('image', image['result_role'])
        audio = self._detail('anonymizer', file='a/x.wav', media_type='audio', output_file='a/y.wav')
        self.assertNotIn('result_role', audio, 'an audio has no role derivable from its category')

    def test_the_transcriber_settings_carry_the_labels_of_its_schema(self):
        detail = self._detail('transcriber', audio='t/r.wav', backend='auto', used_backend='whisper',
                              text='bonjour', hotwords='WAMA', enable_diarization=True,
                              generate_summary=False, verify_coherence=True)
        self.assertEqual(('auto', 'whisper', 'bonjour'),
                         (detail['engine'], detail['engine_effective'], detail['result_text']))
        from wama.common.utils.param_schema import schema_for_app
        labels = {p['name']: p['label'] for p in schema_for_app('transcriber')}
        self.assertEqual({labels['enable_diarization']: True, labels['hotwords']: 'WAMA',
                          labels['verify_coherence']: True}, detail['extra'])


HAS_V8 = __import__('importlib').util.find_spec('py_mini_racer') is not None
INSPECTOR = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js' / 'wama-inspector.js'


class TrueSettingIsShownAsYesTest(SimpleTestCase):
    """One display rule for every app: the data keeps `true`, the inspector says « Oui »."""

    def test_the_settings_of_the_inspector_go_through_the_rule(self):
        source = INSPECTOR.read_text(encoding='utf-8')
        self.assertIn("_detailChip('fa-sliders', _settingValue(d.extra[lbl]), lbl)", source)

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_true_reads_oui_and_everything_else_is_left(self):
        from py_mini_racer import MiniRacer
        source = INSPECTOR.read_text(encoding='utf-8')
        rule = re.search(r'function _settingValue\(value\) \{.*?\n  \}', source, re.S).group(0)
        v8 = MiniRacer()
        v8.eval(rule)
        self.assertEqual(['Oui', 'true', 3, 'fr'], list(v8.eval(
            "[_settingValue(true), _settingValue('true'), _settingValue(3), _settingValue('fr')]")))


class AFactIsShownOnceTest(SimpleTestCase):
    """The settings list never repeats what the backbone already renders (2026-10-03): the engine
    (« Moteur / Modèle ») and the output format and quality (section Sortie). Seen in the panel
    of four apps — there since the 2026-07-11 audit, which listed EVERY schema setting."""

    def test_the_backbone_keys_and_the_skipped_names_are_left_out(self):
        from wama.common.utils.detail_registry import settings_from_schema
        schema = [{'name': 'tts_model', 'label': 'Modèle TTS'}, {'name': 'output_format', 'label': 'Format'},
                  {'name': 'output_quality', 'label': 'Qualité'}, {'name': 'speed', 'label': 'Vitesse'},
                  {'name': 'pitch', 'label': 'Hauteur'}, {'name': 'hidden_one', 'label': ''}]
        element = _element(tts_model='kokoro', output_format='wav', output_quality='max', speed=1.5,
                           pitch=0, hidden_one='x')
        self.assertEqual({'Vitesse': 1.5}, settings_from_schema(element, schema, skip=('tts_model',)))

    def test_a_carrier_is_read_first_and_the_dedicated_field_is_the_fallback(self):
        from wama.common.utils.detail_registry import settings_from_schema
        schema = [{'name': 'quality', 'label': 'Qualité'}, {'name': 'fps', 'label': 'Images/s'}]
        element = _element(quality=50, fps=24)
        self.assertEqual({'Qualité': 80, 'Images/s': 24},
                         settings_from_schema(element, schema, carrier={'quality': 80}))

    def test_param_objects_are_read_like_dicts(self):
        from wama.common.utils.detail_registry import settings_from_schema
        from wama.common.utils.param_schema import Param
        schema = [Param(name='denoise', type='toggle', label='Débruitage'),
                  Param(name='output_format', type='select', label='Format')]
        self.assertEqual({'Débruitage': True},
                         settings_from_schema(_element(denoise=True, output_format='png'), schema))

    def test_no_registered_detail_repeats_a_canonical_value_as_a_setting(self):
        """Both ways — spec and code adapter — on every registered app, with a witness element."""
        from wama.common.app_registry import APP_CATALOG
        engine_fields = ('model', 'ai_model', 'engine', 'backend', 'tts_model', 'model_to_use')
        measured = []
        for app in DetailRegistry.registered_apps():
            if (APP_CATALOG.get(app) or {}).get('sandbox'):
                continue
            entry = DetailRegistry.get(app)
            instance = entry['model']()
            spec = entry.get('spec') or {}
            # The engine field: the one the spec names (a constant engine, avatarizer, names no
            # field — its « Modèle TTS » is a genuine setting) ; for a code adapter, the usual names.
            if spec:
                fields = [spec['engine']] if isinstance(spec.get('engine'), str) else []
            else:
                fields = [f for f in engine_fields if hasattr(instance, f)]
            for f in fields:
                setattr(instance, f, 'engine-witness')
            for f in ('output_format', 'output_quality'):
                if hasattr(instance, f):
                    setattr(instance, f, f'{f}-witness')
            with self.subTest(app=app):
                detail = entry['adapter'](instance)
                repeated = {label: value for label, value in (detail.get('extra') or {}).items()
                            if isinstance(value, str) and value.endswith('-witness')}
                self.assertEqual({}, repeated, 'a canonical value listed again as a setting')
                measured.append(app)
        self.assertGreaterEqual(len(measured), 10, measured)
