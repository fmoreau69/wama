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

#: Code adapters STILL TO PORT — not exceptions (Fabien, 2026-10-03: « on uniformise et on porte
#: tout »). Each names what the spec must still learn to say it; the list can only shrink. An app
#: registering a code adapter without being listed here fails the test: the declarative way is
#: the only way, and nothing new enters by the old door.
#: EMPTY since 2026-10-05: the last two (imager, audio_enhancer) were ported once the spec learnt
#: a COLLECTION of results (`result_files`), a schema NAMED or chosen per element
#: (`params_schema`) and « first element of a list » in the first-non-empty form.
CODE_ADAPTERS = {}


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

    def test_a_collection_in_the_first_non_empty_form_gives_its_first_element(self):
        form = ['video', 'images']
        self.assertEqual('a.png', spec_value(_element(video=None, images=['a.png', 'b.png']), form))
        self.assertEqual('v.mp4', spec_value(_element(video='v.mp4', images=['a.png']), form))
        self.assertIsNone(spec_value(_element(video=None, images=[]), form),
                          'an empty collection is an empty field')

    def test_a_single_field_naming_a_collection_gives_the_whole_list(self):
        self.assertEqual(['a.png', 'b.png'], spec_value(_element(images=['a.png', 'b.png']), 'images'))


class ResultCollectionTest(SimpleTestCase):

    def _detail(self, element, spec):
        return detail_from_spec(element, spec, 'witness')

    def test_the_collection_is_carried_beside_its_representative(self):
        d = self._detail(_element(images=['/m/a.png', '/m/b.png']),
                         {'result_file': ['images'], 'result_files': 'images'})
        self.assertEqual(('/m/a.png', ['/m/a.png', '/m/b.png']), (d['result_file'], d['result_files']))

    def test_one_element_or_a_non_list_is_no_collection(self):
        self.assertNotIn('result_files', self._detail(_element(images=['/m/a.png']), {'result_files': 'images'}))
        self.assertNotIn('result_files', self._detail(_element(images='/m/ab.png'), {'result_files': 'images'}),
                         'a string would be read character by character')


class NamedSchemaTest(SimpleTestCase):
    """`params_schema`: the settings of an element come from the schema the spec NAMES."""

    DECLARED = {'primary': 'MAIN_PARAMS_JSON',
                'schemas': {'MAIN_PARAMS_JSON': [{'name': 'a', 'label': 'Main A'}],
                            'VIDEO_PARAMS_JSON': [{'name': 'fps', 'label': 'Images/s'}]}}

    def _extra(self, element, spec):
        with mock.patch('wama.common.utils.param_schema.declared_param_schemas', return_value=self.DECLARED), \
             mock.patch('wama.common.utils.param_schema.schema_for_app',
                        return_value=self.DECLARED['schemas']['MAIN_PARAMS_JSON']):
            # No `extra_from_params` : the settings of the schema are listed for EVERY spec since
            # 2026-11-23 (the key only names a JSON carrier now).
            return detail_from_spec(element, spec, 'witness').get('extra') or {}

    def test_without_a_name_the_main_schema_is_read(self):
        self.assertEqual({'Main A': 'x'}, self._extra(_element(a='x', fps=24), {}))

    def test_a_named_schema_replaces_the_main_one(self):
        self.assertEqual({'Images/s': 24},
                         self._extra(_element(a='x', fps=24), {'params_schema': {'const': 'VIDEO_PARAMS_JSON'}}))

    def test_the_schema_can_be_chosen_per_element(self):
        form = {'params_schema': {'when_any': ['video'], 'then': 'VIDEO_PARAMS_JSON', 'else': 'MAIN_PARAMS_JSON'}}
        self.assertEqual({'Images/s': 24}, self._extra(_element(video=True, a='x', fps=24), form))
        self.assertEqual({'Main A': 'x'}, self._extra(_element(video=False, a='x', fps=24), form))

    def test_an_entry_without_a_label_takes_it_from_the_named_schema(self):
        with mock.patch('wama.common.utils.param_schema.declared_param_schemas', return_value=self.DECLARED):
            d = detail_from_spec(_element(fps=24), {'params_schema': {'const': 'VIDEO_PARAMS_JSON'},
                                                    'extra': [{'field': 'fps'}]}, 'witness')
        self.assertEqual({'Images/s': 24}, d['extra'])


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

    def test_the_schema_is_listed_whole_and_a_named_entry_is_not_repeated(self):
        """2026-11-23 (Fabien : « parfaitement aligné, universel, uniforme et schéma-driven ») :
        the panel lists every SET setting of the schema for every spec — four apps still wrote
        three or four of them by hand. What `extra` names itself is said once, its way."""
        schema = [{'name': 'kind', 'label': 'Schema label'}, {'name': 'speed', 'label': 'Vitesse'},
                  {'name': 'unset', 'label': 'Jamais posé'}]
        element = _element(kind='x', speed=2, unset='')
        self.assertEqual({'Vitesse': 2, 'Schema label': 'x'}, self._extra(element, [], schema))
        self.assertEqual({'Type': 'x', 'Vitesse': 2},
                         self._extra(element, [{'label': 'Type', 'field': 'kind'}], schema))

    def test_no_registered_spec_lists_by_hand_a_setting_of_its_schema(self):
        """The contract on the DECLARATIONS : an `extra` entry is a fact OUTSIDE the schema (a type,
        a page count) — a schema setting listed there would be a second list to keep in step."""
        from wama.common.utils.param_schema import schema_for_app
        for app, _model, spec in _declared_specs():
            names = {p.get('name') for p in (schema_for_app(app) or [])}
            by_hand = sorted(e.get('field') for e in (spec.get('extra') or []) if e.get('field') in names)
            with self.subTest(app=app):
                self.assertEqual([], by_hand)
                self.assertIsNot(False, spec.get('extra_from_params', True),
                                 'no spec opts out of the settings of its schema')


class RequestedAndEmployedModelTest(SimpleTestCase):
    """2026-11-23 (Fabien : « j'ai toujours auto:text-to-music, ce qui n'est pas le modèle mais la
    tâche. Il faut peut-être donner les 2 infos ») : the model ASKED reads as on the card, the model
    EMPLOYED is the one the step lines kept — for the engine and for every model selector."""

    SCHEMA = [{'name': 'model', 'label': 'Modèle', 'type': 'select', 'options_source': 'catalog',
               'options_auto': 'group'},
              {'name': 'parts_model', 'label': 'Modèle des partitions', 'type': 'select',
               'options_source': 'catalog', 'options_auto': True},
              {'name': 'idle_model', 'label': 'Modèle au repos', 'type': 'select',
               'options_source': 'catalog', 'options_auto': True}]
    NAMES = {'lab:ace': 'ACE-Step', 'lab:mu': 'MuScriptor'}

    def _detail(self, element, employed=None, unread=()):
        used = employed or {}
        with mock.patch('wama.common.utils.param_schema.schema_for_app', return_value=self.SCHEMA), \
             mock.patch('wama.common.utils.card_chips._inventaire_catalogue',
                        return_value=[('lab:ace', 'ACE-Step')]), \
             mock.patch('wama.common.utils.card_chips.catalog_name', side_effect=lambda k: self.NAMES.get(k, '')), \
             mock.patch('wama.common.services.process_pipeline.unread_settings', return_value=tuple(unread)), \
             mock.patch('wama.common.services.process_pipeline.employed_models',
                        side_effect=lambda item, name, pipeline=None: list(used.get(name, ()))):
            return detail_from_spec(element, {'engine': 'model'}, 'witness')

    def test_an_auto_reads_as_a_choice_and_names_its_task(self):
        from wama.common.utils.card_chips import auto_choice_label, display_value
        self.assertEqual(('Automatique', '', ''),
                         (auto_choice_label('auto'), auto_choice_label('lab:ace'), auto_choice_label('')))
        from wama.model_manager.models import ModelTask
        task = ModelTask.choices[0]
        self.assertEqual(f'Automatique ({task[1]})', auto_choice_label(f'auto:{task[0]}'),
                         'the task by its catalogue label')
        self.assertEqual('Automatique (unknown-task)', auto_choice_label('auto:unknown-task'))
        with mock.patch('wama.common.utils.card_chips._inventaire_catalogue', return_value=[]):
            self.assertEqual('Automatique', display_value(self.SCHEMA[1], 'auto'))
            own = dict(self.SCHEMA[1], choices=[('auto', 'Auto (meilleur disponible)')])
            self.assertEqual('Auto (meilleur disponible)', display_value(own, 'auto'),
                             'an « auto » the schema labels itself keeps its label')
            self.assertEqual(3, display_value({'name': 'n', 'type': 'number'}, 3),
                             'counter-proof : nothing else is touched')

    def test_the_engine_says_what_was_asked_and_what_was_employed(self):
        element = _element(pk=7, model='auto', parts_model='auto', idle_model='')
        detail = self._detail(element, employed={'model': ['lab:mu', 'lab:ace'], 'parts_model': ['lab:mu']})
        self.assertEqual(('auto', 'Automatique', 'lab:ace', 'MuScriptor, ACE-Step'),
                         (detail['engine'], detail['engine_label'], detail['engine_effective'],
                          detail['engine_effective_label']),
                         'the keys keep the VALUES (the last step made the output), the labels read')
        self.assertEqual({'Modèle des partitions': 'Automatique → MuScriptor'}, detail['extra'])

    def test_nothing_employed_yet_says_only_what_is_asked(self):
        detail = self._detail(_element(pk=7, model='auto', parts_model='auto'))
        self.assertNotIn('engine_effective', detail)
        self.assertEqual({'Modèle des partitions': 'Automatique'}, detail['extra'])
        named = self._detail(_element(pk=7, model='lab:ace', parts_model='lab:mu'),
                             employed={'model': ['lab:ace'], 'parts_model': ['lab:mu']})
        self.assertEqual(('lab:ace', 'ACE-Step', None, {'Modèle des partitions': 'lab:mu'}),
                         (named['engine'], named['engine_label'], named.get('engine_effective'),
                          named['extra']), 'a named model that was employed is said once')

    def test_a_model_no_step_reads_is_not_said(self):
        """A cover one only draws scores from : its music model served nothing — neither the
        engine line nor the settings of the steps that do not take place."""
        detail = self._detail(_element(pk=7, model='auto', parts_model='lab:mu', idle_model='auto'),
                              unread=('model', 'idle_model'))
        self.assertNotIn('engine', detail)
        self.assertEqual({'Modèle des partitions': 'lab:mu'}, detail['extra'])

    def test_the_panel_writes_both_in_one_reading(self):
        from wama.common.utils.detail_registry import EMPLOYED_ARROW, requested_and_employed
        self.assertEqual('Auto', requested_and_employed('Auto', []))
        source = INSPECTOR.read_text(encoding='utf-8')
        self.assertIn(f"used ? asked + ' {EMPLOYED_ARROW} ' + used : asked", source,
                      'the same arrow in the panel and in the settings')
        self.assertIn("d.engine_label || d.engine", source)


class ShownSettingsTest(SimpleTestCase):
    """What the list of settings leaves out and how it writes a value (2026-11-23, measured on real
    cards of ten apps : a quality slider under a named model, « [] », a whole prompt)."""

    def _settings(self, element, schema, **kwargs):
        from wama.common.utils.detail_registry import settings_from_schema
        return settings_from_schema(element, schema, **kwargs)

    def test_a_setting_its_condition_hides_is_not_listed(self):
        schema = [{'name': 'model', 'label': 'Modèle'},
                  {'name': 'intent', 'label': 'Rapide ↔ Qualité', 'show_if': {'field': 'model', 'in': ['auto']}},
                  {'name': 'far', 'label': 'Ailleurs', 'show_if': {'field': 'not_in_this_schema'}}]
        self.assertEqual({'Modèle': 'auto', 'Rapide ↔ Qualité': 50, 'Ailleurs': 1},
                         self._settings(_element(model='auto', intent=50, far=1), schema))
        self.assertEqual({'Modèle': 'named', 'Ailleurs': 1},
                         self._settings(_element(model='named', intent=50, far=1), schema),
                         'a condition on a field this schema does not carry hides nothing')

    def test_a_compound_value_reads_plainly_and_an_empty_one_is_not_set(self):
        schema = [{'name': 'classes', 'label': 'Classes'}, {'name': 'levels', 'label': 'Niveaux'}]
        self.assertEqual({}, self._settings(_element(classes=[''], levels={}), schema))
        self.assertEqual({'Classes': 'face, plate', 'Niveaux': 'Voix 0.5, Basse 1.2'},
                         self._settings(_element(classes=['face', 'plate'],
                                                 levels={'Voix': 0.5, 'Basse': 1.2}), schema))

    def test_a_long_text_is_cut_and_a_long_option_label_is_not(self):
        from wama.common.utils.detail_registry import LONG_TEXT
        long = 'p' * (LONG_TEXT + 20)
        schema = [{'name': 'prompt', 'label': 'Prompt', 'type': 'textarea'},
                  {'name': 'mode', 'label': 'Mode', 'type': 'select', 'choices': [('m', long)]}]
        self.assertEqual({'Prompt': 'p' * LONG_TEXT + '…', 'Mode': long},
                         self._settings(_element(prompt=long, mode='m'), schema))


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
              'result_files', 'result_role', 'result_text', 'source_text', 'params_schema',
              # 2026-11-08 : the title READ in the content, which names the lot (`batch_identity`),
              # and the page number read, which orders it.
              'content_title', 'content_page')
# `result_tabs` left the vocabulary on 2026-10-13 (REMOVAL_LEDGER R127): a spec that still
# declared text tabs would be read by nothing, so it fails here.
KNOWN_KEYS = set(VALUE_KEYS) | {'extra', 'extra_from_params', 'aliases'}


def _schema_names(form):
    """The `*PARAMS_JSON` names a `params_schema` form can resolve to."""
    if isinstance(form, dict):
        if 'const' in form:
            return [form['const']]
        if 'when_any' in form:
            return [n for n in (form.get('then'), form.get('else')) if n]
        return list((form.get('map') or {}).values())
    return []


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

    def test_every_schema_a_spec_names_is_declared_by_its_app(self):
        """A misnamed schema resolves to nothing — the « Réglages » section would vanish silently."""
        from wama.common.utils.param_schema import declared_param_schemas
        for app, model, spec in _declared_specs():
            names = _schema_names(spec.get('params_schema'))
            if not names:
                continue
            declared = set((declared_param_schemas(model._meta.app_label) or {}).get('schemas') or {})
            with self.subTest(app=app):
                self.assertEqual([], sorted(set(names) - declared), f'{model._meta.app_label}.params')

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


class GeneratedModelsReadOnlyFieldNamesTest(SimpleTestCase):
    """A computed form (list, presence) names no field to generate — `models_gen` ignores it."""

    def test_a_computed_result_form_creates_no_field(self):
        from wama.common.manifests.codegen.models_gen import declared_result_fields
        body = {'inspector': {'detail_spec': {'result_file': ['output_video', 'output_image'],
                                              'result_text': 'text'}}}
        self.assertEqual([('text', 'text')], declared_result_fields(body))
        body['inspector']['detail_spec']['result_file'] = 'output_file'
        self.assertEqual([('output_file', 'file'), ('text', 'text')], declared_result_fields(body))


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

    def test_the_imager_reads_the_schema_of_its_element_and_its_collection(self):
        """Ported 2026-10-05: video settings for a video, image settings for an image — and the
        video, else the FIRST image, as representative of the collection."""
        with mock.patch('wama.imager.models.ImageGeneration.output_images',
                        new_callable=mock.PropertyMock, return_value=['/m/a.png', '/m/b.png']):
            image = self._detail('imager', generation_mode='txt2img', model='sdxl', prompt='p' * 80,
                                 num_images=3, video_fps=24)
        self.assertEqual(('image', 'image', '/m/a.png', ['/m/a.png', '/m/b.png']),
                         (image['source_type'], image['result_role'], image['result_file'], image['result_files']))
        self.assertEqual('p' * 60 + '…', image['extra']['Prompt'])
        from wama.imager.params import IMAGE_PARAMS_JSON, VIDEO_PARAMS_JSON
        image_label = {p['name']: p['label'] for p in IMAGE_PARAMS_JSON}
        video_label = {p['name']: p['label'] for p in VIDEO_PARAMS_JSON}
        # As the card shows it (`card_chips.display_value`, 2026-11-19) : the label of its option.
        self.assertEqual('3', str(image['extra'][image_label['num_images']]))
        self.assertNotIn(video_label['video_fps'], image['extra'], 'an image shows no VIDEO setting')
        video = self._detail('imager', generation_mode='txt2vid', model='ltx', prompt='x',
                             output_video='i/v.mp4', num_images=3, video_fps=24)
        self.assertEqual(('video', 'video'), (video['source_type'], video['result_role']))
        self.assertIn('v.mp4', video['result_file'])
        self.assertEqual('24', str(video['extra'][video_label['video_fps']]).split()[0],
                         'a video shows its VIDEO settings')
        self.assertNotIn(image_label['num_images'], video['extra'])

    def test_the_audio_enhancer_reads_its_named_schema(self):
        from wama.enhancer.params import AUDIO_PARAMS_JSON, MEDIA_PARAMS_JSON
        audio_only = sorted({p['name'] for p in AUDIO_PARAMS_JSON} - {p['name'] for p in MEDIA_PARAMS_JSON}
                            - {'engine', 'output_format', 'output_quality'})
        self.assertTrue(audio_only, 'witness: a setting only the AUDIO schema declares')
        name = audio_only[0]
        field = __import__('wama.enhancer.models', fromlist=['AudioEnhancement']).AudioEnhancement._meta.get_field(name)
        value = True if field.get_internal_type() == 'BooleanField' else 'w'
        detail = self._detail('audio_enhancer', input_file='a/x.wav', engine='deepfilternet', **{name: value})
        self.assertEqual(('audio', 'deepfilternet'), (detail['source_type'], detail['engine']))
        labels = {p['name']: p['label'] for p in AUDIO_PARAMS_JSON}
        self.assertEqual(value, (detail.get('extra') or {}).get(labels[name]))

    def test_the_transcriber_settings_carry_the_labels_of_its_schema(self):
        detail = self._detail('transcriber', audio='t/r.wav', backend='auto', used_backend='whisper',
                              text='bonjour', hotwords='WAMA', enable_diarization=True,
                              generate_summary=False, verify_coherence=True)
        self.assertEqual(('auto', 'whisper', 'bonjour'),
                         (detail['engine'], detail['engine_effective'], detail['result_text']))
        from wama.common.utils.param_schema import schema_for_app
        labels = {p['name']: p['label'] for p in schema_for_app('transcriber')}
        # The settings of the schema, all of them (2026-11-23) — the four once listed by hand
        # among them, the one left unset still absent.
        extra = detail['extra']
        self.assertEqual({labels['enable_diarization']: True, labels['hotwords']: 'WAMA',
                          labels['verify_coherence']: True},
                         {k: v for k, v in extra.items()
                          if k in (labels['enable_diarization'], labels['hotwords'],
                                   labels['verify_coherence'], labels['generate_summary'])})
        self.assertEqual(set(), set(extra) - set(labels.values()), 'only settings of the schema')


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

    def test_a_setting_reads_in_the_panel_as_on_the_card(self):
        """2026-11-19 (Fabien : « régler les écarts entre les chips affichées sur la card et celles
        qui vivent dans la section INFOS du volet […] un alignement parfait ») : ONE writing of a
        setting's value (`card_chips.display_value`) — the label of the chosen option, a duration in
        its declared format, a number with its unit. The card « 1:35 » and the panel « 95 » before.
        Only a number WITHOUT unit differs on purpose : the chip names it, the panel shows its label
        next to it."""
        from types import SimpleNamespace
        from wama.common.utils.card_chips import chips_for
        from wama.common.utils.detail_registry import settings_from_schema
        schema = [{'name': 'duration', 'label': 'Durée', 'type': 'range', 'unit': 's',
                   'display_format': 'duration', 'chip': True},
                  {'name': 'mode', 'label': 'Mode', 'type': 'select', 'chip': True,
                   'choices': [('fast', 'Rapide'), ('slow', 'Lent')]},
                  {'name': 'speed', 'label': 'Vitesse', 'type': 'number', 'unit': 'x', 'chip': True},
                  {'name': 'steps', 'label': 'Étapes', 'type': 'number', 'chip': True}]
        element = SimpleNamespace(duration=95, mode='fast', speed=1.5, steps=30)
        panel = settings_from_schema(element, schema)
        card = {chip['title']: chip['label'] for chip in chips_for(element, schema)}
        self.assertEqual({'Durée': '1:35', 'Mode': 'Rapide', 'Vitesse': '1.5 x', 'Étapes': 30}, panel)
        self.assertEqual({'Durée': '1:35', 'Mode': 'Rapide', 'Vitesse': '1.5 x', 'Étapes': 'Étapes 30'},
                         card)

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
