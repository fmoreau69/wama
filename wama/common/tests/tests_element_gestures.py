"""Les GESTES D'UNE CARD — ⏹ ⬇ 🗑 ⧉ ⚙ — par la fabrique commune (`item_views.make_item_views`).

Étape ④ de l'alignement des domaines (`ROUTE §11 #42`, 2026-11-01) : les vues d'élément lisent ce
que l'app déclare déjà à sa fabrique de lot (`batch_views.element_declaration` : remise à zéro de
la copie, sorties, rattachement, nettoyage, schéma et écrivain de réglages, nom du résultat). Mesuré
avant : les dix apps écrivaient ces cinq vues à la main (≈ 48), l'enhancer deux fois — une par
domaine —, et la copie d'une card ne se rangeait pas partout de la même façon (l'audio de
l'enhancer ne rejoignait jamais le lot de l'original, l'avatarizer et le describer rejoignaient un
lot d'un, le changeant en lot de deux).

Ce que ce fichier tient :
  • les gestes d'une card de l'enhancer, des deux domaines, sont ceux de la fabrique ;
  • la copie d'une card seule a son propre lot d'un ; celle d'une fille rejoint son lot ;
  • 🗑 retire la card, purge sa progression et dit ce que devient son lot ;
  • ⬇ sert le résultat sous le nom déclaré, et dit qu'il n'y en a pas ;
  • ⚙ écrit par l'écrivain de l'app et n'écrit que ce qui change ;
  • ⏹ rend relançable ce qui attend, et ne touche pas ce qui est fini.
"""
from django.core.cache import cache
from django.test import SimpleTestCase
from django.urls import reverse

from wama.filemanager.tests_send_to_settings import SendToTestBase


def _factory_made(view) -> bool:
    return 'make_item_views.<locals>' in getattr(view, '__qualname__', '')


#: Les apps qui écrivent ENCORE des gestes de card à la main — portées app par app (décision de
#: Fabien, « porter app par app »). Ne peut que RÉTRÉCIR : une app portée en sort dans le même
#: commit, une app neuve n'y entre jamais.
NOT_YET_PORTED = {'anonymizer', 'avatarizer', 'composer', 'converter', 'imager', 'synthesizer',
                  'transcriber'}
REAL_APPS = ('anonymizer', 'avatarizer', 'composer', 'converter', 'describer', 'enhancer',
             'imager', 'reader', 'synthesizer', 'transcriber')


class CardGesturesAreTheFactorysTest(SimpleTestCase):

    def test_only_the_apps_not_yet_ported_write_card_gestures_by_hand(self):
        from wama.common.services import conformity_checker as checker
        states = {app: checker._element_views_common(checker._AppFiles(app)) for app in REAL_APPS}
        for app, (state, evidence) in states.items():
            with self.subTest(app=app):
                if app in NOT_YET_PORTED:
                    self.assertIsNot(True, state, f'{app} est portée : la retirer de la liste')
                else:
                    self.assertIs(True, state, evidence)


class EnhancerGesturesAreTheFactorysTest(SendToTestBase):

    def test_both_domains_take_their_card_gestures_from_the_factory(self):
        from wama.enhancer import views
        names = ('stop', 'delete', 'duplicate', 'download', 'update_settings')
        audio = ('audio_stop', 'audio_delete', 'audio_duplicate', 'audio_download', 'audio_update')
        for name in names + audio:
            with self.subTest(view=name):
                self.assertTrue(_factory_made(getattr(views, name)), f'{name} écrite à la main')

    def test_the_batch_factory_describes_the_elements_of_both_domains(self):
        from django.apps import apps as django_apps

        from wama.common.utils.batch_views import element_declaration
        for label in ('enhancer.Enhancement', 'enhancer.AudioEnhancement'):
            with self.subTest(model=label):
                found = element_declaration(django_apps.get_model(label))
                self.assertIsNotNone(found)
                self.assertIn('output_file', found['output_fields'])


class _AudioCards(SendToTestBase):

    def setUp(self):
        super().setUp()
        self.client.force_login(self.author)

    def card(self, name='voice.wav', **fields):
        from wama.enhancer.models import AudioEnhancement
        rel = self._temp_file(self.author, name, b'RIFF0000WAVE')
        return AudioEnhancement.objects.create(user=self.author, input_file=rel, **fields)

    def lot(self, *cards):
        from wama.enhancer.models import BatchAudioEnhancement, BatchAudioEnhancementItem
        batch = BatchAudioEnhancement.objects.create(user=self.author, total=len(cards))
        for i, c in enumerate(cards):
            BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=c, row_index=i)
        return batch

    def post(self, route, pk, data=None):
        return self.client.post(reverse(f'enhancer:{route}', args=[pk]), data or {})


class DuplicateFindsItsPlaceTest(_AudioCards):

    def test_the_copy_of_a_lone_card_gets_its_own_lot(self):
        from wama.common.utils.batch_common import batch_of
        original = self.card()
        lot = self.lot(original)
        body = self.post('audio_duplicate', original.pk).json()
        from wama.enhancer.models import AudioEnhancement
        copy = AudioEnhancement.objects.get(pk=body['duplicated'])
        self.assertEqual(body['id'], copy.pk)
        self.assertNotEqual(lot.pk, batch_of(copy).pk, 'a lone card does not become a lot of two')
        self.assertTrue(batch_of(copy).is_unitary)
        self.assertEqual('PENDING', copy.status)
        self.assertFalse(copy.output_file)

    def test_the_copy_of_a_child_joins_its_lot(self):
        from wama.common.utils.batch_common import batch_of
        first, second = self.card('a.wav'), self.card('b.wav')
        lot = self.lot(first, second)
        body = self.post('audio_duplicate', second.pk).json()
        from wama.enhancer.models import AudioEnhancement
        copy = AudioEnhancement.objects.get(pk=body['duplicated'])
        self.assertEqual(lot.pk, batch_of(copy).pk)
        lot.refresh_from_db()
        self.assertEqual(3, lot.total)


class DeleteSaysWhatTheLotBecomesTest(_AudioCards):

    def test_the_card_leaves_its_progress_and_its_lot_says_so(self):
        from wama.enhancer.models import AudioEnhancement
        first, second = self.card('a.wav'), self.card('b.wav')
        lot = self.lot(first, second)
        cache.set(f'audio_enhancer_progress_{first.pk}', 40, 60)
        body = self.post('audio_delete', first.pk).json()
        self.assertEqual(first.pk, body['deleted'])
        self.assertEqual({'id': lot.pk, 'total': 1}, {k: body['batch'][k] for k in ('id', 'total')})
        self.assertFalse(AudioEnhancement.objects.filter(pk=first.pk).exists())
        self.assertIsNone(cache.get(f'audio_enhancer_progress_{first.pk}'))

    def test_only_its_owner_deletes_a_card(self):
        card = self.card()
        self.client.force_login(self.other)
        self.assertEqual(404, self.post('audio_delete', card.pk).status_code)


class DownloadServesTheDeclaredResultTest(_AudioCards):

    def test_the_result_is_served_under_its_name_or_its_absence_is_said(self):
        card = self.card()
        self.assertEqual(404, self.client.get(reverse('enhancer:audio_download',
                                                      args=[card.pk])).status_code)
        out = f'users/{self.author.id}/enhancer/output/audio/voice_clean.wav'
        (self.media / out).parent.mkdir(parents=True, exist_ok=True)
        (self.media / out).write_bytes(b'RIFF1111WAVE')
        card.output_file.name, card.status = out, 'SUCCESS'
        card.save()
        response = self.client.get(reverse('enhancer:audio_download', args=[card.pk]))
        self.assertEqual(200, response.status_code)
        self.assertIn('voice_clean.wav', response['Content-Disposition'])
        self.assertEqual(b'RIFF1111WAVE', b''.join(response.streaming_content))


class SettingsWriteOnlyWhatChangesTest(_AudioCards):

    def test_a_posted_setting_is_written_by_the_apps_writer(self):
        card = self.card(denoising_strength=0.5)
        body = self.post('audio_update', card.pk, {'denoising_strength': '0.3'}).json()
        card.refresh_from_db()
        self.assertAlmostEqual(0.3, card.denoising_strength)
        self.assertEqual(['denoising_strength'], body['updated'])

    def test_a_running_card_keeps_its_status(self):
        card = self.card(status='RUNNING')
        self.post('audio_update', card.pk, {'denoising_strength': '0.3'})
        card.refresh_from_db()
        self.assertEqual('RUNNING', card.status)


class StopMakesAWaitingCardRelaunchableTest(_AudioCards):

    def test_a_waiting_card_stops_and_a_finished_one_is_left(self):
        waiting, done = self.card('a.wav'), self.card('b.wav', status='SUCCESS')
        self.assertEqual('FAILURE', self.post('audio_stop', waiting.pk).json()['status'])
        waiting.refresh_from_db()
        self.assertTrue(waiting.error_message)
        self.assertEqual('SUCCESS', self.post('audio_stop', done.pk).json()['status'])
