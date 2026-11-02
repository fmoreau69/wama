"""Les GESTES D'UNE CARD — ⏹ ⬇ 🗑 ⧉ ⚙ — par la fabrique commune (`item_views.make_item_views`).

Étape ④ de l'alignement des domaines (`ROUTE §11 #42`, 2026-11-01) : les vues d'élément lisent ce
que l'app déclare déjà à sa fabrique de lot (`batch_views.element_declaration` : remise à zéro de
la copie, sorties, rattachement, nettoyage, schéma et écrivain de réglages, nom du résultat). Mesuré
avant : les dix apps écrivaient ces cinq vues à la main (≈ 48), l'enhancer deux fois — une par
domaine —, et la copie d'une card ne se rangeait pas partout de la même façon (l'audio de
l'enhancer ne rejoignait jamais le lot de l'original, l'avatarizer et le describer rejoignaient un
lot d'un, le changeant en lot de deux).

Le 2026-11-02, les sept autres apps (`ROUTE §11 #42` ④, suite) : ce qu'elles avaient de propre
passe par quatre crochets déclarés (`on_stop`, `item_settings`, `item_empty_is_value`,
`settings_file`) et par la déclaration du lot (`list_settings`, `batch_extra`). Avant, mesuré :
quatre règles de placement de la copie pour dix apps — sœur dans tout lot (describer, synthesizer,
avatarizer), sœur dans un vrai lot seulement (transcriber, composer), jamais dans le lot (audio de
l'enhancer), aucun lot (reader, anonymizer, converter, imager) ; trois ⏹ (en échec, en attente,
« réinitialisé ») ; la ⚙ de lot qui écrivait ce que la ⚙ d'une card refusait (avatarizer).

Ce que ce fichier tient :
  • les gestes d'une card de chaque app sont ceux de la fabrique (la grille, puis les vues) ;
  • la copie trouve sa place par UNE règle, dans chaque app, le lot d'un gardant la nature du lot ;
  • ⏹ arrête en échec dans chaque app, et oublie ce que l'app déclare ;
  • les spécificités déclarées : réglages propres à une card, vide qui vaut une valeur, liste de
    réglages, fichier reçu avec les réglages, nettoyage déclaré au lot ;
  • les gestes d'une card de l'enhancer, des deux domaines, sont ceux de la fabrique ;
  • la copie d'une card seule a son propre lot d'un ; celle d'une fille rejoint son lot ;
  • 🗑 retire la card, purge sa progression et dit ce que devient son lot ;
  • ⬇ sert le résultat sous le nom déclaré, et dit qu'il n'y en a pas ;
  • ⚙ écrit par l'écrivain de l'app et n'écrit que ce qui change ;
  • ⏹ rend relançable ce qui attend, et ne touche pas ce qui est fini.
"""
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.filemanager.tests_send_to_settings import SendToTestBase


def _factory_made(view) -> bool:
    return 'make_item_views.<locals>' in getattr(view, '__qualname__', '')


#: Les apps qui écrivent ENCORE des gestes de card à la main — portées app par app (décision de
#: Fabien, « porter app par app »). Ne peut que RÉTRÉCIR : une app portée en sort dans le même
#: commit, une app neuve n'y entre jamais. VIDE depuis le 2026-11-02 : les dix apps sont portées.
NOT_YET_PORTED = set()
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


#: Le nom de la route du ⏹ quand ce n'est pas `stop` : le converter dit `cancel` (que le
#: générateur connaît, `urls_gen`) — une vue qui DÉLÈGUE au geste de la fabrique.
STOP_ROUTE = {'converter': 'cancel'}


def _gesture_route(surface, gesture):
    """La route d'un geste de card pour une surface de `_surfaces()` (l'audio de l'enhancer a ses
    routes préfixées)."""
    if surface == 'audio_enhancer':
        return f"enhancer:audio_{'update' if gesture == 'update_settings' else gesture}"
    if gesture == 'stop':
        gesture = STOP_ROUTE.get(surface, 'stop')
    return f'{surface}:{gesture}'


class _EveryApp(TestCase):
    """Chaque app réelle, par sa VUE, sur des témoins construits sans rien connaître d'elle
    (`tests_queue_delete_contract._instance` / `_lot_de`). Les jumelles en sont exclues : leurs
    vues sont générées, et le générateur n'émet pas encore ces gestes (`ROUTE §11 #42` ⑦)."""

    def setUp(self):
        import shutil
        import tempfile

        from django.test import override_settings
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def fleet(self):
        from wama.common.tests.tests_queue_delete_contract import (SuppressionDansChaqueAppTest,
                                                                   _surfaces)
        from wama.common.utils.preview_registry import PreviewRegistry
        surfaces = [s for s, *_ in _surfaces() if s in REAL_APPS or s == 'audio_enhancer']
        self.assertEqual(len(REAL_APPS) + 1, len(surfaces), surfaces)
        for surface in surfaces:
            account = SuppressionDansChaqueAppTest._compte_pour(self, surface)
            yield surface, account, PreviewRegistry.get_model(surface)

    def post(self, surface, gesture, pk, data=None):
        return self.client.post(reverse(_gesture_route(surface, gesture), args=[pk]),
                                data=data or {})


class TheCopyFindsItsPlaceInEveryAppTest(_EveryApp):
    """⧉ : UNE règle de placement (`batch_common.place_copy`) — il y en avait quatre."""

    def test_a_lone_cards_copy_gets_a_lot_of_its_own_of_the_same_nature(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.common.utils.batch_common import batch_of
        for surface, account, model in self.fleet():
            with self.subTest(surface=surface):
                lot, (original,) = _lot_de(model, account, 1)
                natures = self._non_default_nature(lot)
                response = self.post(surface, 'duplicate', original.pk)
                self.assertEqual(200, response.status_code, response.content[:300])
                copy = model.objects.get(pk=response.json()['duplicated'])
                own = batch_of(copy)
                self.assertIsNotNone(own, 'la copie est restée sans lot')
                self.assertNotEqual(lot.pk, own.pk, 'une card seule devenait un lot de deux')
                self.assertTrue(own.is_unitary)
                for name, value in natures.items():
                    self.assertEqual(value, getattr(own, name),
                                     f'le lot d’un de la copie a perdu la nature du lot ({name})')

    @staticmethod
    def _non_default_nature(lot):
        """La NATURE figée sur le lot (`media_type`, `domain` — ce que `batch_extra` reporte), posée
        à une valeur qui n'est PAS le défaut du modèle : sans cela, un lot d'un né des défauts
        passerait pour un lot qui a gardé sa nature."""
        posed = {}
        for name in ('media_type', 'domain'):
            try:
                field = lot._meta.get_field(name)
            except Exception:
                continue
            # Ni `media_type` (converter) ni `domain` (imager) ne déclarent de choix : une nature
            # de la taxonomie, autre que le défaut du champ.
            other = next(n for n in ('video', 'audio', 'image') if n != field.get_default())
            setattr(lot, name, other)
            posed[name] = other
        if posed:
            lot.save(update_fields=list(posed))
        return posed

    def test_the_nature_check_is_not_empty(self):
        """Non-vacuité : deux apps figent une nature sur le lot (converter, imager)."""
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        posed = []
        for surface, account, model in self.fleet():
            lot, _cards = _lot_de(model, account, 1)
            if self._non_default_nature(lot):
                posed.append(surface)
        self.assertEqual({'converter', 'imager'}, set(posed))

    def test_a_childs_copy_joins_its_lot(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.common.utils.batch_common import batch_of
        for surface, account, model in self.fleet():
            with self.subTest(surface=surface):
                lot, (_first, second) = _lot_de(model, account, 2)
                response = self.post(surface, 'duplicate', second.pk)
                self.assertEqual(200, response.status_code, response.content[:300])
                copy = model.objects.get(pk=response.json()['duplicated'])
                self.assertEqual(lot.pk, getattr(batch_of(copy), 'pk', None))
                lot.refresh_from_db()
                self.assertEqual(3, lot.total)


class TheNightlyGestureJudgesWhereTheCopyLandsTest(TestCase):
    """L'instrument de la grille FONCTIONNELLE (`ui_smoke._copy_placement_verdict`, lu par le
    scénario `<app>.duplicate_delete`) : il dépliait le lot de deux né d'une card seule au lieu de
    le dire."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user('copy_placement_judge', password='x')

    def _attach(self, card, lot):
        from wama.transcriber.models import BatchTranscriptItem
        BatchTranscriptItem.objects.create(batch=lot, transcript=card, row_index=9)
        lot.total = lot.items.count()
        lot.save(update_fields=['total'])

    def test_it_says_a_lone_card_became_a_lot_of_two_and_lets_a_lot_of_its_own_pass(self):
        from wama.common.services.ui_smoke import _copy_placement_verdict
        from wama.common.tests.tests_queue_delete_contract import _instance, _lot_de
        from wama.transcriber.models import BatchTranscript, Transcript
        lot, (lone,) = _lot_de(Transcript, self.user, 1)
        wrong = _instance(Transcript, self.user)
        self._attach(wrong, lot)
        self.assertIn('lot de deux', _copy_placement_verdict(Transcript, lone.pk, wrong.pk))
        # Un autre original seul : le premier cas a fait grandir le lot qu'il jugeait.
        _other, (alone,) = _lot_de(Transcript, self.user, 1)
        right = _instance(Transcript, self.user)
        self._attach(right, BatchTranscript.objects.create(user=self.user, total=0))
        self.assertEqual('', _copy_placement_verdict(Transcript, alone.pk, right.pk))

    def test_it_says_a_childs_copy_left_its_lot(self):
        from wama.common.services.ui_smoke import _copy_placement_verdict
        from wama.common.tests.tests_queue_delete_contract import _instance, _lot_de
        from wama.transcriber.models import BatchTranscript, Transcript
        _lot, (child, _sister) = _lot_de(Transcript, self.user, 2)
        stray = _instance(Transcript, self.user)
        self._attach(stray, BatchTranscript.objects.create(user=self.user, total=0))
        self.assertIn('n’a pas rejoint', _copy_placement_verdict(Transcript, child.pk, stray.pk))
        orphan = _instance(Transcript, self.user)
        self.assertIn('sans lot', _copy_placement_verdict(Transcript, child.pk, orphan.pk))


class StopEndsInFailureInEveryAppTest(_EveryApp):
    """⏹ : la règle du bouton de cycle (`stop_instance`) — l'anonymizer et le converter remettaient
    en attente sans le dire, l'imager « réinitialisait »."""

    def test_a_waiting_card_stops_in_failure_and_forgets_its_progress(self):
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.item_views import declaration_for
        for surface, account, model in self.fleet():
            with self.subTest(surface=surface):
                card = _instance(model, account)
                model.objects.filter(pk=card.pk).update(status='PENDING')
                key = declaration_for(model).progress_cache_key(card.pk)
                cache.set(key, 40, 60)
                response = self.post(surface, 'stop', card.pk)
                self.assertEqual(200, response.status_code, response.content[:300])
                self.assertEqual('FAILURE', response.json()['status'])
                card.refresh_from_db()
                self.assertEqual('FAILURE', card.status)
                self.assertIsNone(cache.get(key), 'la progression du run arrêté reste affichée')

    def test_a_finished_card_is_left_as_it_is(self):
        from wama.common.tests.tests_queue_delete_contract import _instance
        for surface, account, model in self.fleet():
            with self.subTest(surface=surface):
                card = _instance(model, account)
                model.objects.filter(pk=card.pk).update(status='SUCCESS')
                self.assertEqual('SUCCESS', self.post(surface, 'stop', card.pk).json()['status'])

    def test_what_an_app_names_for_its_stop_is_forgotten(self):
        from wama.anonymizer.models import Media
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.transcriber.models import Transcript
        fleet = {surface: (account, model) for surface, account, model in self.fleet()}
        cases = (('anonymizer', Media, 'anon_lock:media:{pk}'),
                 ('transcriber', Transcript, 'transcriber_status_msg_{pk}'))
        for surface, model, key in cases:
            with self.subTest(surface=surface):
                account, _model = fleet[surface]
                self.client.force_login(account)
                card = _instance(model, account)
                cache.set(key.format(pk=card.pk), 'x', 60)
                self.post(surface, 'stop', card.pk)
                self.assertIsNone(cache.get(key.format(pk=card.pk)))


class EachAppsOwnRulesTest(_EveryApp):
    """Ce que les apps ont de propre, DÉCLARÉ à la fabrique au lieu d'être écrit dans leurs vues."""

    def setUp(self):
        super().setUp()
        self.accounts = {surface: (account, model) for surface, account, model in self.fleet()}

    def _card(self, surface, **fields):
        from wama.common.tests.tests_queue_delete_contract import _instance
        account, model = self.accounts[surface]
        self.client.force_login(account)
        card = _instance(model, account)
        if fields:
            model.objects.filter(pk=card.pk).update(**fields)
            card.refresh_from_db()
        return card

    def _lot(self, surface, n=2, **fields):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        account, model = self.accounts[surface]
        self.client.force_login(account)
        lot, cards = _lot_de(model, account, n)
        if fields:
            model.objects.filter(pk__in=[c.pk for c in cards]).update(**fields)
        return lot, [model.objects.get(pk=c.pk) for c in cards]

    def test_a_transcripts_own_settings_are_written_on_the_card_only(self):
        card = self._card('transcriber')
        self.post('transcriber', 'update_settings', card.pk, {'title': 'Réunion du lundi'})
        card.refresh_from_db()
        self.assertEqual('Réunion du lundi', card.title)
        self.post('transcriber', 'update_settings', card.pk, {'title': ''})
        card.refresh_from_db()
        self.assertEqual('', card.title, 'un titre vidé s’efface sur la card')
        lot, (first, _second) = self._lot('transcriber')
        self.client.post(reverse('transcriber:batch_update', args=[lot.pk]), {'title': 'Lot'})
        first.refresh_from_db()
        self.assertNotEqual('Lot', first.title, 'le titre est propre à une card')

    def test_the_classes_to_blur_are_read_whole_by_the_card_and_by_its_lot(self):
        card = self._card('anonymizer')
        self.post('anonymizer', 'update_settings', card.pk, {'classes2blur': ['face', 'plate']})
        card.refresh_from_db()
        self.assertEqual({'face', 'plate'}, set(card.classes2blur))
        lot, cards = self._lot('anonymizer')
        self.client.post(reverse('anonymizer:batch_update', args=[lot.pk]),
                         {'classes2blur': ['face', 'plate']})
        for child in cards:
            child.refresh_from_db()
            self.assertEqual({'face', 'plate'}, set(child.classes2blur),
                             'la ⚙ de lot ne gardait que la première classe')

    def test_a_refused_voice_writes_nothing(self):
        from wama.common.utils.media_paths import designation_field
        card = self._card('synthesizer', speed=1.0)
        response = self.post('synthesizer', 'update_settings', card.pk,
                             {'speed': '1.5', designation_field('voice_reference'): '../../../etc/hosts'})
        self.assertEqual(400, response.status_code)
        card.refresh_from_db()
        self.assertEqual(1.0, card.speed)

    def test_the_avatarizer_lot_follows_the_rule_of_its_cards(self):
        lot, (standalone, pipeline) = self._lot('avatarizer')
        type(standalone).objects.filter(pk=standalone.pk).update(mode='standalone', text_content='')
        type(pipeline).objects.filter(pk=pipeline.pk).update(mode='pipeline', text_content='Avant')
        self.client.post(reverse('avatarizer:batch_update', args=[lot.pk]), {'text_content': 'Après'})
        standalone.refresh_from_db()
        pipeline.refresh_from_db()
        self.assertEqual('', standalone.text_content, 'un job standalone n’a pas de texte à dire')
        self.assertEqual('Après', pipeline.text_content)

    def test_removing_an_avatar_lot_frees_the_folders_of_its_jobs(self):
        from pathlib import Path

        from wama.common.utils.media_paths import app_media_dir
        lot, cards = self._lot('avatarizer')
        account, _model = self.accounts['avatarizer']
        folders = []
        for job in cards:
            folder = Path(self.tmp) / app_media_dir('avatarizer', account.id, 'output') / f'job_{job.pk}'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'frame.png').write_bytes(b'x')
            folders.append(folder)
        self.client.post(reverse('avatarizer:batch_delete', args=[lot.pk]))
        self.assertEqual([], [f.name for f in folders if f.exists()],
                         'seule la 🗑 d’une card purgeait le dossier de son job')

    def test_emptied_lyrics_are_cleared_on_the_card(self):
        card = self._card('composer', lyrics='la la la')
        self.post('composer', 'update_settings', card.pk, {'lyrics': ''})
        card.refresh_from_db()
        self.assertEqual('', card.lyrics)


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
