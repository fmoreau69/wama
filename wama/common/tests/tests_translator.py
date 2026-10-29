"""La brique de traduction (`common/utils/translator.py`) — moteur de l'app Translator (2026-10-16).

Elle n'avait AUCUN test alors que le pipeline de prompts de toutes les apps et l'assistant
l'appellent. Ce qui est tenu : le passthrough, le modèle désigné par une CLÉ DE CATALOGUE (voie
locale gouvernée pour `ollama:*`, `chat_with_catalog_model` sinon, avec la clé de l'utilisateur),
l'ancien nom nu accepté, l'aperçu au fil des morceaux, et un cache qui distingue les modèles.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.utils import llm_utils, translator


class TranslatorServiceTest(SimpleTestCase):

    def _service(self, **kw):
        return translator.TranslatorService(use_cache=False, **kw)

    def test_same_language_or_empty_text_calls_no_model(self):
        with mock.patch.object(llm_utils, 'llm_chat') as local, \
                mock.patch.object(llm_utils, 'chat_with_catalog_model') as remote:
            self.assertEqual('Bonjour', self._service().translate('Bonjour', 'fr', 'fr')['text'])
            self.assertTrue(self._service().translate('  ', 'fr', 'en')['ok'])
        local.assert_not_called()
        remote.assert_not_called()

    def test_a_local_key_takes_the_governed_ollama_path(self):
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('Hello', None)) as local:
            out = self._service().translate('Bonjour', 'fr', 'en')
        self.assertEqual('Hello', out['text'])
        self.assertEqual(('ollama', 'translategemma:12b'),
                         (local.call_args.kwargs['provider'], local.call_args.kwargs['model']))

    def test_a_remote_key_goes_through_the_catalog_call_with_the_user(self):
        user = object()
        with mock.patch.object(llm_utils, 'chat_with_catalog_model',
                               return_value=('Hello', None)) as remote, \
                mock.patch.object(llm_utils, 'llm_chat') as local:
            out = self._service(model='ilaas:qwen-3.8-27b', user=user).translate(
                'Bonjour', 'fr', 'en')
        self.assertEqual('Hello', out['text'])
        self.assertEqual('ilaas:qwen-3.8-27b', remote.call_args.args[0])
        self.assertIs(user, remote.call_args.kwargs['user'])
        local.assert_not_called()

    def test_the_former_bare_ollama_name_is_still_accepted(self):
        self.assertEqual('ollama:translategemma:12b',
                         self._service(model='translategemma:12b').model)

    def test_each_translated_chunk_is_reported_as_it_comes(self):
        text = 'a' * 3000 + '\n\n' + 'b' * 3000          # deux morceaux (> _CHUNK_CHARS)
        seen = []
        with mock.patch.object(llm_utils, 'llm_chat', side_effect=[('A', None), ('B', None)]):
            out = self._service().translate(text, 'fr', 'en', on_chunk=seen.append)
        self.assertEqual(['A', 'A\n\nB'], seen)
        self.assertEqual('A\n\nB', out['text'])

    def test_an_unknown_source_is_left_to_the_model_and_never_named_auto(self):
        """Mesuré le 2026-10-16 sur translategemma : « de « auto » vers « en » » rendait le texte
        INCHANGÉ. La consigne nomme les langues par code ISO et fait détecter la source."""
        with mock.patch.object(llm_utils, 'llm_chat', return_value=('Hello', None)) as local:
            self._service().translate('Bonjour', 'auto', 'en')
            unknown = local.call_args.kwargs['messages'][0]['content']
            self._service().translate('Bonjour', 'fr', 'en')
            known = local.call_args.kwargs['messages'][0]['content']
        self.assertNotIn('« auto »', unknown)
        self.assertIn('détecte', unknown)
        self.assertIn('ISO 639-1 « en »', unknown)
        self.assertIn('« fr »', known)                    # contre-épreuve : la source connue se dit

    def test_a_rewritten_prompt_does_not_serve_the_old_cached_translations(self):
        key = translator.TranslatorService._cache_key
        before = key('Bonjour', 'auto', 'en', [], 'ollama:translategemma:12b')
        with mock.patch.object(translator, 'PROMPT_VERSION', translator.PROMPT_VERSION + 1):
            self.assertNotEqual(before, key('Bonjour', 'auto', 'en', [], 'ollama:translategemma:12b'))

    def test_two_models_never_share_a_cached_translation(self):
        key = translator.TranslatorService._cache_key
        self.assertNotEqual(key('Bonjour', 'fr', 'en', [], 'ollama:translategemma:12b'),
                            key('Bonjour', 'fr', 'en', [], 'ilaas:qwen-3.8-27b'))


def _fake_translate(self, text, source_lang, target_lang, glossary=None, timeout=120,
                    on_chunk=None):
    """A deterministic « translation » : the text upper-cased, with a Polish letter (that cp1252
    cannot carry) — enough to see WHERE each block landed, and that the form stayed."""
    return {'ok': True, 'text': f'Ł {text.upper()}', 'cached': False}


class TranslateDocumentTest(SimpleTestCase):
    """2026-10-28 — a document translated KEEPS ITS FORM : same format, each block translated in
    its place (`document_text`, unit `block`), never the plain text rewritten as a `.md`."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.object(translator.TranslatorService, 'translate', _fake_translate)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_docx_keeps_its_paragraph_form_and_its_format(self):
        import docx
        source = self.tmp / 'in.docx'
        document = docx.Document()
        title = document.add_paragraph()
        title.add_run('Rapport annuel').bold = True
        document.add_paragraph('')
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = 'Dans le tableau'
        document.save(str(source))
        seen = []
        out = translator.translate_document(source, self.tmp / 'out.docx', 'fr', 'en',
                                            on_chunk=seen.append)
        result = docx.Document(out)
        self.assertEqual('Ł RAPPORT ANNUEL', result.paragraphs[0].text)
        self.assertTrue(result.paragraphs[0].runs[0].bold)
        self.assertEqual('', result.paragraphs[1].text)            # an empty paragraph stays
        self.assertEqual('Ł DANS LE TABLEAU', result.tables[0].cell(0, 0).text)
        self.assertEqual('Ł RAPPORT ANNUEL\n\nŁ DANS LE TABLEAU', seen[-1])

    def test_a_pdf_is_translated_block_by_block_and_keeps_its_drawings(self):
        import fitz
        source = self.tmp / 'in.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.draw_rect(fitz.Rect(40, 40, 300, 200), color=(1, 0, 0))
            page.insert_text((50, 80), 'Premier bloc', fontsize=12)
            page.insert_text((50, 400), 'Second bloc', fontsize=12)
            pdf.save(str(source))
        out = translator.translate_document(source, self.tmp / 'out.pdf', 'fr', 'en')
        with fitz.open(out) as pdf:
            text = pdf[0].get_text()
            drawings = pdf[0].get_drawings()
        self.assertIn('PREMIER BLOC', text)
        self.assertIn('SECOND BLOC', text)
        self.assertNotIn('Premier bloc', text)                 # the original is gone, not hidden
        self.assertTrue(drawings, 'the drawn rectangle must survive the rewrite')

    def test_a_text_file_its_encoding_cannot_carry_passes_to_utf8(self):
        source = self.tmp / 'in.txt'
        source.write_bytes('Été'.encode('cp1252'))
        out = translator.translate_document(source, self.tmp / 'out.txt', 'fr', 'pl')
        from pathlib import Path
        self.assertEqual('Ł ÉTÉ', Path(out).read_text(encoding='utf-8'))

    def test_a_document_without_text_is_refused_with_the_reason(self):
        import fitz
        source = self.tmp / 'scan.pdf'
        with fitz.open() as pdf:
            pdf.new_page()
            pdf.save(str(source))
        with self.assertRaisesRegex(ValueError, 'PDF scanné'):
            translator.translate_document(source, self.tmp / 'out.pdf', 'fr', 'en')

    def test_a_glossary_written_one_term_per_line_gives_terms_not_characters(self):
        with mock.patch.object(translator.TranslatorService, 'translate',
                               return_value={'ok': True, 'text': 'x', 'cached': False}) as call:
            translator.translate_text('Bonjour', 'fr', 'en', glossary='WAMA\n\n Lescot \n')
        self.assertEqual(['WAMA', 'Lescot'], call.call_args.kwargs['glossary'])

    def test_a_failed_translation_raises_its_reason(self):
        failing = lambda *a, **k: {'ok': False, 'error': 'modèle absent', 'cached': False}  # noqa: E731
        with mock.patch.object(translator.TranslatorService, 'translate', failing), \
                self.assertRaisesRegex(RuntimeError, 'modèle absent'):
            translator.translate_text('Bonjour', 'fr', 'en')


class TranslationIsDeclaredNotWrittenTest(SimpleTestCase):
    """The translation SPECIALITY is declared on the schema (`options_resolution`), read by the
    draw and by the `codegen` role — never passed by hand in a glue."""

    def test_the_declared_speciality_reaches_the_draw_as_a_single_value(self):
        from wama.common.utils import auto_model
        self.assertIn('specialization', auto_model.RESOLUTION_KEYS)
        self.assertEqual('translation', auto_model.read_refinement('specialization', 'translation'))
        with mock.patch.object(auto_model, 'catalog_field', return_value={
                'options_resolution': {'specialization': 'translation', 'unknown': 'x'}}):
            self.assertEqual({'specialization': 'translation'},
                             auto_model.declared_resolution('translator_01'))

    def test_codegen_shows_the_translation_brick_instead_of_the_bare_llm_call(self):
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        llm_model = [{'manifest_kind': 'model', 'body': {'identity': {'model_type': 'llm'}}}]
        select = {'name': 'model', 'options_resolution': {'specialization': 'translation'}}
        man = {'body': {'params': {'schemas': {'P': [select]}}}}
        bricks = [names for _key, names in codegen._triggered(llm_model, man)]
        self.assertIn(('translate_text', 'translate_document'), bricks)
        self.assertNotIn(('chat_with_catalog_model',), bricks)
        # Counter-proof : without the declared speciality, the bare LLM call is what it sees.
        plain = {'body': {'params': {'schemas': {'P': [{'name': 'model'}]}}}}
        self.assertEqual([('chat_with_catalog_model',)],
                         [names for _key, names in codegen._triggered(llm_model, plain)])
        self.assertEqual({'text', 'source_language', 'target_language', 'model', 'user',
                          'glossary', 'on_chunk', 'timeout'},
                         codegen.signatures_briques()['translate_text'])

    def test_the_judge_sees_what_the_first_generated_glue_invented(self):
        """2026-10-28 : the first glue generated for the Translator passed the checks with ONE
        warning out of five defects — `fields` built in a variable, an invented item attribute,
        `ctx.output_place` unpacked into three values."""
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        glue = ('def _process_t(item, ctx):\n'
                '    from wama.common.utils.document_text import ensure_text_file\n'
                '    text = item.options\n'
                '    rel, folder, name = ctx.output_place("txt", source_name=item.filename)\n'
                '    ctx.progress(5, colour="red")\n'
                '    fields = {"result_text": text, "model": "x"}\n'
                '    return {"fields": fields}\n')
        warnings = '\n'.join(codegen.controles(
            glue, '_process_t', app_id='translator_01',
            item_fields=['prompt', 'model', 'output_file'],
            settings_fields=['prompt', 'model'], item_properties=['filename'])['warnings'])
        for expected in ("['result_text']", "['options']", "réécrit un RÉGLAGE de l'utilisateur",
                         'DEUX valeurs', 'ctx.progress', "['ensure_text_file']"):
            self.assertIn(expected, warnings)
        # Counter-proof : a glue that keeps to the item and the context passes.
        sound = ('def _process_t(item, ctx):\n'
                 '    from wama.common.utils.translator import translate_document\n'
                 '    rel, path = ctx.output_place("txt", source_name=item.filename)\n'
                 '    return {"fields": {"output_file": rel}, "models": [item.model]}\n')
        self.assertEqual([], codegen.controles(
            sound, '_process_t', app_id='translator_01',
            item_fields=['prompt', 'model', 'output_file'],
            settings_fields=['prompt', 'model'], item_properties=['filename'])['warnings'])

    def test_the_judge_sees_a_mode_that_returns_nothing_and_an_emptied_input(self):
        """2026-10-28 : two task glues passed the judge while returning `'output_file': None` in
        text mode and `'source_document': None` in document mode — the declared-output check only
        ran for a pipeline of several processes."""
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        glue = ('def _process_t(item, ctx):\n'
                '    rel, path = ctx.output_place("txt", source_name="x")\n'
                '    if item.prompt:\n'
                '        return {"fields": {"output_file": None}}\n'
                '    return {"fields": {"source_document": None, "output_file": rel}}\n')
        warnings = '\n'.join(codegen.result_checks(glue, '_process_t', 'output_file',
                                                   'source_document'))
        self.assertIn("1 retour(s) sur 2 n'écrivent pas la sortie déclarée `output_file`", warnings)
        self.assertIn("réécrit l'ENTRÉE de l'élément : source_document", warnings)
        # Counter-proof : every path writes the declared output, the input is only read.
        sound = ('def _process_t(item, ctx):\n'
                 '    rel, path = ctx.output_place("txt", source_name="x")\n'
                 '    fields = {"output_file": rel}\n'
                 '    if item.prompt:\n'
                 '        return {"fields": fields}\n'
                 '    return {"fields": {"output_file": rel}}\n')
        self.assertEqual([], codegen.result_checks(sound, '_process_t', 'output_file',
                                                   'source_document'))
        # 2026-10-29 : the absolute path thrown away — the returned file is never written.
        thrown = ('def _process_t(item, ctx):\n'
                  '    rel, _ = ctx.output_place("txt", source_name="x")\n'
                  '    return {"fields": {"output_file": rel}}\n')
        self.assertIn("chemin absolu d'`ctx.output_place` est jeté",
                      '\n'.join(codegen.result_checks(thrown, '_process_t', 'output_file')))

    def test_the_matter_shows_what_an_item_property_returns_not_only_its_name(self):
        """2026-10-29 : a glue tested `item.filename is None` to pick the text mode — the property
        returns '' without a document. Its name alone did not say so."""
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        _fields, props = codegen.champs_item('ReadingItem', 'reader')
        self.assertIn('filename', props)
        bodies = codegen.property_bodies('ReadingItem', 'reader', ['filename'])
        self.assertIn('def filename(self):', bodies)
        self.assertIn('original_filename', bodies)
        # Counter-proof : an unknown model gives no matter, never an error.
        self.assertEqual('', codegen.property_bodies('NoSuchItem', 'reader', ['filename']))

    def test_the_judge_sees_an_invented_draw_domain(self):
        """2026-10-29 : two glues drew in `{'source': 'catalog', 'specialization': …}` while the
        selector declares `{'model_type': 'llm'}`."""
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        man = {'body': {'params': {'schemas': {'P': [
            {'name': 'model', 'options_source': 'catalog', 'options_query': {'model_type': 'llm'},
             'options_resolution': {'specialization': 'translation'}}]}}}}
        invented = ('def _process_t(item, ctx):\n'
                    '    key = resolve_model_choice(item.model, spec={"source": "catalog", '
                    '"specialization": "translation"}, item=item)\n')
        self.assertIn("n'est pas un domaine déclaré",
                      '\n'.join(codegen.draw_domain_checks(invented, man)))
        # Counter-proof : the declared domain, or one held in a variable, passes.
        for spec in ('{"model_type": "llm"}', 'domain'):
            sound = ('def _process_t(item, ctx):\n'
                     f'    key = resolve_model_choice(item.model, spec={spec}, item=item)\n')
            self.assertEqual([], codegen.draw_domain_checks(sound, man))

    def test_a_task_body_reads_its_settings_and_draws_its_model_like_every_app(self):
        """2026-10-29 (Fabien) : settings and draw domain « parfaitement alignés sur le
        fonctionnement des autres apps » — one preamble, composed by the MODEL flavour and handed
        to the `codegen` role, which the judge requires verbatim."""
        from wama.common.manifests.codegen import tasks_gen
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        man = {'body': {'params': {'primary': 'PARAMS_JSON', 'schemas': {'PARAMS_JSON': [
            {'name': 'model', 'options_source': 'catalog', 'options_query': {'model_type': 'llm'}}]}},
            'processing': {'model_spec': {'item': {'params_fields': ['prompt', 'model']}}}}}
        preamble = tasks_gen.declared_settings_and_draw(man)
        self.assertIn("opts = effective_settings(_SCH, posees=given)", preamble)
        self.assertIn("resolve_model_choice(opts.pop('model', ''), app_id=ctx.app_id,", preamble)
        self.assertIn("spec={'model_type': 'llm'}", preamble)
        aligned = 'def _process_t(item, ctx):\n' + preamble + '\n    return {"fields": {}}\n'
        self.assertEqual([], codegen.preamble_checks(aligned, '_process_t', preamble))
        # Counter-proof : the glue that read the settings its own way is caught.
        own_way = ('def _process_t(item, ctx):\n'
                   '    opts = effective_settings(PARAMS_JSON, posees={}, preset=item.quality_intent)\n'
                   '    key = resolve_model_choice(item.model, app_id=ctx.app_id, item=item)\n')
        self.assertIn('préambule COMMUN', '\n'.join(
            codegen.preamble_checks(own_way, '_process_t', preamble)))
        # The MODEL flavour composes the very same lines (one source, two readers).
        lines = tasks_gen.settings_and_draw_lines(['a'], param='m', domain={'task': 'ocr'},
                                                  app_id_expr="'reader_01'")
        self.assertEqual('    opts = effective_settings(_SCH, posees=given)', lines[5])
        self.assertIn("app_id='reader_01'", lines[6])

    def test_the_instant_hole_has_its_own_signature(self):
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        glue = 'def instant_result(item):\n    return item.prompt\n'
        self.assertTrue(codegen.controles(glue, 'instant_result',
                                          expected_args=('item',))['signature_ok'])
        # Counter-proof : a task body keeps its (item, ctx).
        self.assertFalse(codegen.controles('def _process_t(item):\n    pass\n',
                                           '_process_t')['signature_ok'])
