"""Identité d'un lot (`common/services/batch_identity.py`, 2026-10-19) : son titre — nom donné,
entrée commune, fichier de lot, dossier d'origine, plage des entrées — et ce qui varie d'une card
à l'autre ; le geste « Renommer le lot… » ; les surfaces qui nomment un lot."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.services import batch_identity
from wama.common.utils.card_chips import varying_chips_for_items


def _user(name='lot_identity'):
    return User.objects.create_user(name, password='x')


class _ConverterLot:
    """Un lot du converter (forme à FK DIRECTE) dont chaque job a son fichier d'entrée."""

    def make(self, user, names, formats=None, batch_file=''):
        from wama.converter.models import ConversionBatch, ConversionJob
        lot = ConversionBatch.objects.create(user=user, total=len(names), batch_file=batch_file)
        jobs = []
        for i, name in enumerate(names):
            jobs.append(ConversionJob.objects.create(
                user=user, batch=lot, batch_row_index=i, input_filename=name,
                input_file=f'users/{user.pk}/converter/input/{name}',
                output_format=(formats or [''] * len(names))[i]))
        return lot, jobs


class TitleTest(_ConverterLot, TestCase):
    def setUp(self):
        self.u = _user()

    def _identity(self, lot, jobs):
        return batch_identity.identify([(lot, jobs)])[0]

    def test_one_input_shared_by_every_card_is_the_title_and_what_varies_is_said(self):
        lot, jobs = self.make(self.u, ['concert.wav', 'concert.wav'], formats=['mp3', 'ogg'])
        ident = self._identity(lot, jobs)
        self.assertEqual((ident['title'], ident['kind']), ('concert.wav', 'shared_input'))
        self.assertTrue(any(d.startswith('Format de sortie') and 'mp3' in d.lower()
                            and 'ogg' in d.lower() for d in ident['details']), ident['details'])

    def test_inputs_with_a_common_start_are_said_by_that_start(self):
        lot, jobs = self.make(self.u, ['interview_01.wav', 'interview_02.wav', 'interview_03.wav'])
        self.assertEqual(self._identity(lot, jobs)['title'], 'interview_0…')

    def test_the_number_of_inputs_is_said_only_when_it_differs_from_the_cards(self):
        lot, jobs = self.make(self.u, ['interview_01.wav', 'interview_01.wav', 'interview_02.wav'])
        self.assertEqual(self._identity(lot, jobs)['title'], 'interview_0… (2 fichiers)')

    def test_unrelated_inputs_are_said_by_the_first_and_the_count_of_others(self):
        lot, jobs = self.make(self.u, ['chat.png', 'route.mp4', 'voix.wav'])
        ident = self._identity(lot, jobs)
        self.assertEqual(ident['title'], 'chat.png + 2 autres')
        self.assertIn('1 images', ' '.join(ident['details']).lower(), 'les natures mêlées sont dites')

    def test_the_batch_file_names_the_batch(self):
        lot, jobs = self.make(self.u, ['a.mp4', 'b.mp4'], batch_file='users/1/converter/prompts_noel.csv')
        self.assertEqual(self._identity(lot, jobs)['title'], 'prompts_noel.csv')

    def test_a_given_name_wins_and_an_empty_one_brings_back_the_derived_title(self):
        lot, jobs = self.make(self.u, ['concert.wav', 'concert.wav'])
        self.assertEqual(batch_identity.rename(lot, '  Concert   de Noël '), 'Concert de Noël')
        ident = self._identity(lot, jobs)
        self.assertEqual((ident['title'], ident['kind'], ident['manual']),
                         ('Concert de Noël', 'manual', 'Concert de Noël'))
        batch_identity.rename(lot, '')
        self.assertEqual(self._identity(lot, jobs)['title'], 'concert.wav')

    def test_a_batch_without_any_declared_input_falls_back_to_its_number(self):
        lot, _ = self.make(self.u, [])
        ident = self._identity(lot, [])
        self.assertEqual(ident['title'], '')
        self.assertEqual(batch_identity.display_title(ident), f'Lot #{lot.pk}')


class ProvenanceTest(_ConverterLot, TestCase):
    """L'origine et le vrai nom viennent de la provenance que l'import enregistre."""

    def setUp(self):
        self.u = _user()

    def _trace(self, job, ref, original=''):
        from wama.common.models import InputProvenance
        InputProvenance.objects.create(app='converter', object_type='ConversionJob',
                                       object_id=job.pk, field='input_file', kind='temp',
                                       ref=ref, original_name=original, user=self.u)

    def test_the_folder_every_input_came_from_names_the_batch(self):
        lot, jobs = self.make(self.u, ['x1.png', 'y2.png'])
        for j, n in zip(jobs, ('x1.png', 'y2.png')):
            self._trace(j, f'users/{self.u.pk}/temp/vacances_2026/{n}')
        ident = batch_identity.identify([(lot, jobs)])[0]
        self.assertEqual((ident['title'], ident['kind']), ('vacances_2026', 'folder'))

    def test_the_root_of_a_source_is_not_a_folder_name(self):
        lot, jobs = self.make(self.u, ['x1.png', 'y2.png'])
        for j, n in zip(jobs, ('x1.png', 'y2.png')):
            self._trace(j, f'users/{self.u.pk}/temp/{n}')
        self.assertNotEqual(batch_identity.identify([(lot, jobs)])[0]['kind'], 'folder')

    def test_the_original_name_beats_the_working_copy_name(self):
        lot, jobs = self.make(self.u, ['copie_a1b2.wav', 'copie_c3d4.wav'])
        for j in jobs:
            self._trace(j, f'users/{self.u.pk}/temp/source.wav', original='source.wav')
        self.assertEqual(batch_identity.identify([(lot, jobs)])[0]['title'], 'source.wav')


class TextEntryTest(TestCase):
    """Une app à TEXTE (imager, forme à LIAISON) : l'entrée dite est le prompt."""

    def test_the_prompt_is_the_entry_and_a_long_one_is_shortened(self):
        from wama.imager.models import GenerationBatch, GenerationBatchItem, ImageGeneration
        u = _user()
        lot = GenerationBatch.objects.create(user=u, total=2)
        long_prompt = 'un chat roux ' * 10
        for i in range(2):
            g = ImageGeneration.objects.create(user=u, prompt=long_prompt)
            GenerationBatchItem.objects.create(batch=lot, generation=g, row_index=i)
        ident = batch_identity.identity_of(lot)
        self.assertEqual(ident['kind'], 'shared_input')
        self.assertTrue(ident['title'].startswith('un chat roux'), ident['title'])
        self.assertLessEqual(len(ident['title']), batch_identity.TEXT_CHARS)
        self.assertTrue(ident['title'].endswith('…'))


class QueueTest(_ConverterLot, TestCase):
    """Les constructeurs de file portent l'identité de chaque lot de plusieurs cards."""

    def test_the_common_queue_carries_the_identity_of_a_batch_of_several_cards_only(self):
        from wama.common.utils.batch_common import build_batches_list
        from wama.imager.models import GenerationBatch, GenerationBatchItem, ImageGeneration
        u = _user()
        for n in (2, 1):
            lot = GenerationBatch.objects.create(user=u, total=n)
            for i in range(n):
                g = ImageGeneration.objects.create(user=u, prompt=f'lot de {n}')
                GenerationBatchItem.objects.create(batch=lot, generation=g, row_index=i)
        rows = {r['obj'].total: r for r in build_batches_list(
            u, batch_model=GenerationBatch, work_attr='generation')}
        self.assertEqual(rows[2]['identity']['title'], 'lot de 2')
        self.assertNotIn('identity', rows[1], "un lot d'une card s'affiche en card seule")

    def test_a_queue_built_by_hand_on_direct_rows_gets_it_the_same_way(self):
        """Le converter et l'index généré en FK directe bâtissent leurs lignes eux-mêmes : les
        éléments y SONT les lignes (pas d'alias `elem`)."""
        from wama.common.utils.batch_common import attach_identities
        u = _user()
        lot, jobs = self.make(u, ['concert.wav', 'concert.wav'])
        rows = attach_identities([{'obj': lot, 'items': jobs}, {'obj': None, 'items': jobs[:1]}])
        self.assertEqual(rows[0]['identity']['title'], 'concert.wav')
        self.assertNotIn('identity', rows[1], 'un job sans lot')

    def test_the_converter_page_shows_the_title_of_its_batches(self):
        u = _user()
        lot, _ = self.make(u, ['concert.wav', 'concert.wav'], formats=['mp3', 'ogg'])
        self.client.force_login(u)
        html = self.client.get(reverse('converter:index')).content.decode()
        self.assertIn('data-batch-title="concert.wav"', html)


class RenameEndpointTest(_ConverterLot, TestCase):
    def setUp(self):
        self.u = _user()
        self.lot, self.jobs = self.make(self.u, ['concert.wav', 'concert.wav'])
        self.url = reverse('common:api_batch_label', args=['converter', self.lot.pk])

    def test_the_owner_names_the_batch_and_gets_its_identity_back(self):
        self.client.force_login(self.u)
        r = self.client.post(self.url, {'label': 'Concert'})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual((data['identity']['title'], data['identity']['manual']), ('Concert', 'Concert'))
        r = self.client.post(self.url, data=json.dumps({'label': ''}), content_type='application/json')
        self.assertEqual(r.json()['identity']['title'], 'concert.wav', 'vide = titre dérivé')

    def test_someone_else_cannot_name_the_batch(self):
        self.client.force_login(_user('lot_identity_other'))
        self.assertEqual(self.client.post(self.url, {'label': 'X'}).status_code, 404)
        self.assertEqual(batch_identity.label_of(self.lot), '')

    def test_reading_is_not_renaming(self):
        self.client.force_login(self.u)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_the_name_follows_a_duplicate_and_leaves_with_a_deleted_batch(self):
        from django.test import RequestFactory
        from wama.common.utils.batch_views import make_batch_views
        from wama.converter.models import ConversionBatch, ConversionJob
        views = make_batch_views(work_model=ConversionJob, batch_model=ConversionBatch,
                                 get_user=lambda r: self.u, batch_attr='batch',
                                 row_field='batch_row_index')
        batch_identity.rename(self.lot, 'Concert')
        req = RequestFactory().post('/x/')
        req.user = self.u
        copy_id = json.loads(views['batch_duplicate'](req, self.lot.pk).content)['id']
        self.assertEqual(batch_identity.label_of(ConversionBatch.objects.get(pk=copy_id)),
                         'Concert (copie)')
        views['batch_delete'](req, self.lot.pk)
        from wama.common.models import BatchLabel
        self.assertFalse(BatchLabel.objects.filter(batch_id=str(self.lot.pk),
                                                   batch_type='ConversionBatch').exists())


class HeaderRenderTest(TestCase):
    def _render(self, identity):
        from django.template.loader import render_to_string
        from wama.converter.models import ConversionBatch
        lot = ConversionBatch.objects.create(user=_user(), total=2)
        info = {'obj': lot, 'items': [], 'success_count': 0, 'running_count': 0,
                'failure_count': 0, 'has_success': False, 'evaluation': None,
                'agreement': None, 'reference': None}
        if identity is not None:
            info['identity'] = identity
        return lot, render_to_string('common/_batch_card.html', {'batch_info': info, 'app': 'converter'})

    def test_the_header_shows_the_title_its_number_and_what_varies(self):
        lot, html = self._render({'title': 'concert.wav', 'manual': '', 'kind': 'shared_input',
                                  'details': ['Format de sortie : mp3, ogg'], 'number': 0})
        self.assertIn('data-batch-title="concert.wav"', html)
        self.assertRegex(html, r'data-batch-field="title"[^>]*>concert\.wav<')
        self.assertIn(f'#{lot.pk}', html)
        self.assertRegex(html, r'data-batch-field="details"[^>]*>Format de sortie : mp3, ogg<')
        # La date du lot va au volet avec son numéro (2026-10-21, lot #489) : posée sur la mère.
        from django.utils.timezone import localtime
        self.assertIn(f'data-batch-created="{localtime(lot.created_at):%d/%m/%Y %H:%M}"', html)

    def test_without_identity_the_header_keeps_its_number(self):
        lot, html = self._render(None)
        self.assertRegex(html, r'data-batch-field="title"[^>]*>Batch<')
        self.assertIn(f'#{lot.pk}', html)
        self.assertNotIn('data-batch-field="details"', html)


class VaryingChipsTest(SimpleTestCase):
    SCHEMA = [
        {'name': 'model', 'label': 'Modèle', 'chip': True, 'type': 'select',
         'choices': [('a', 'Alpha — rapide, léger'), ('b', 'Beta — lent')]},
        {'name': 'summary', 'label': 'Générer un résumé', 'chip': True, 'chip_label': 'Résumé',
         'type': 'toggle'},
        {'name': 'duration', 'label': 'Durée', 'chip': True, 'chip_label': 's', 'type': 'range'},
        {'name': 'language', 'label': 'Langue', 'chip': True, 'type': 'select'},
    ]

    def test_only_what_differs_is_said_with_the_labels_of_the_card_chips(self):
        items = [SimpleNamespace(model='a', summary=True, duration=5, language='fr'),
                 SimpleNamespace(model='b', summary=False, duration=8, language='fr')]
        out = {v['name']: v for v in varying_chips_for_items(items, self.SCHEMA)}
        self.assertNotIn('language', out, 'un réglage commun ne varie pas')
        self.assertEqual(out['model']['values'], ['Alpha', 'Beta'], 'le nom, sans sa description')
        self.assertEqual((out['summary']['title'], out['summary']['values']), ('Résumé', ['oui', 'non']))
        self.assertEqual((out['duration']['title'], out['duration']['values']), ('Durée', ['5 s', '8 s']),
                         'un chip_label qui est une unité ne sert pas de titre')

    def test_a_value_held_in_a_json_carrier_is_read_through_it(self):
        items = [SimpleNamespace(opts={'model': 'a'}), SimpleNamespace(opts={'model': 'b'})]
        out = varying_chips_for_items(items, self.SCHEMA[:1], values_of=lambda i: i.opts)
        self.assertEqual(out[0]['values'], ['Alpha', 'Beta'])


class BannerSentenceTest(SimpleTestCase):
    """« le batch #N (tous les éléments) » était recopié par huit apps et le générateur dans leur
    configuration de l'inspecteur : la phrase vit dans la brique, qui dit le TITRE du lot."""

    def test_no_app_writes_the_batch_banner_sentence(self):
        writers = set()
        for root in ('wama', 'wama_lab'):
            for path in (Path(settings.BASE_DIR) / root).rglob('*'):
                if path.suffix not in ('.js', '.html', '.py') or 'staticfiles' in path.parts:
                    continue
                if re.match(r'.+_\d\d$', path.relative_to(settings.BASE_DIR).parts[1]):
                    continue                               # jumelles : régénérées depuis le générateur
                if 'tests' in path.name:
                    continue
                if re.search(r'batchLabel\s*:', path.read_text(encoding='utf-8', errors='replace')):
                    writers.add(path.relative_to(settings.BASE_DIR).as_posix())
        self.assertEqual(writers, set())
        inspector = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
                     / 'wama-inspector.js').read_text(encoding='utf-8')
        self.assertIn('dataset.batchTitle', inspector)
