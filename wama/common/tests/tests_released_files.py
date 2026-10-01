"""Retirer une card LIBÈRE ses fichiers — on prévient, on ne supprime pas (2026-09-30).

Décision de Fabien : « la suppression est un geste explicite de l'utilisateur, mais il est
prévenu » — à la suppression de la card, par une notification si le fichier reste inutilisé trop
longtemps, et en rouge dans les informations du fichier. Ce module éprouve la brique
(`common/services/released_files.py`) sur une vraie card qui possède son fichier.
"""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from wama.common.models import Notification, ReleasedFile
from wama.common.services import released_files
from wama.common.utils.queue_duplication import release_card_file
from wama.synthesizer.models import VoiceSynthesis


def _owned_output(user, name='out.wav'):
    """Une synthèse dont la SORTIE vit chez l'app de son propriétaire (donc lui appartient)."""
    from wama.common.utils.media_paths import app_media_dir
    rel = f"{app_media_dir('synthesizer', user.id, 'output')}/{name}".replace('//', '/')
    path = Path(settings.MEDIA_ROOT) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'RIFF0000WAVE')
    synthesis = VoiceSynthesis.objects.create(user=user, text_file='x.txt')
    synthesis.audio_output.name = rel
    synthesis.save(update_fields=['audio_output'])
    return synthesis, rel, path


class ReleasingACardFileTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('releaser', password='x')

    def test_removing_a_card_keeps_its_file_and_notes_it(self):
        synthesis, rel, path = _owned_output(self.user)
        self.assertTrue(release_card_file(synthesis, 'audio_output'))
        synthesis.delete()
        self.assertTrue(path.exists(), 'le fichier n’est JAMAIS supprimé au retrait de la card')
        row = ReleasedFile.objects.get(path=rel)
        self.assertEqual(self.user, row.user)
        self.assertIn('VoiceSynthesis', row.origin)

    def test_a_file_still_carried_by_another_card_is_not_released(self):
        synthesis, rel, _ = _owned_output(self.user)
        twin = VoiceSynthesis.objects.create(user=self.user, text_file='y.txt')
        twin.audio_output.name = rel
        twin.save(update_fields=['audio_output'])
        self.assertFalse(release_card_file(synthesis, 'audio_output'))
        self.assertFalse(ReleasedFile.objects.filter(path=rel).exists())

    def test_it_is_announced_once(self):
        synthesis, rel, _ = _owned_output(self.user)
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        first = released_files.take_unannounced(self.user)
        self.assertEqual([rel], [f['path'] for f in first])
        self.assertEqual([], released_files.take_unannounced(self.user))

    def test_deleting_it_is_an_explicit_gesture_that_rechecks_usage(self):
        synthesis, rel, path = _owned_output(self.user)
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        row = ReleasedFile.objects.get(path=rel)
        result = released_files.delete_released(self.user, [row.pk])
        self.assertEqual([rel], result['deleted'])
        self.assertFalse(path.exists())
        self.assertFalse(ReleasedFile.objects.filter(path=rel).exists())

    def test_a_file_taken_back_by_a_card_is_kept_and_forgotten(self):
        synthesis, rel, path = _owned_output(self.user)
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        again = VoiceSynthesis.objects.create(user=self.user, text_file='z.txt')
        again.audio_output.name = rel
        again.save(update_fields=['audio_output'])
        row = ReleasedFile.objects.get(path=rel)
        self.assertEqual({'deleted': [], 'kept': [rel]}, released_files.delete_released(self.user, [row.pk]))
        self.assertTrue(path.exists())
        self.assertFalse(ReleasedFile.objects.filter(path=rel).exists())

    def test_someone_else_cannot_delete_it(self):
        synthesis, rel, path = _owned_output(self.user)
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        other = get_user_model().objects.create_user('not_the_owner', password='x')
        row = ReleasedFile.objects.get(path=rel)
        self.assertEqual([], released_files.delete_released(other, [row.pk])['deleted'])
        self.assertTrue(path.exists())

    def test_the_file_info_says_unused_and_since_when(self):
        synthesis, rel, _ = _owned_output(self.user)
        self.assertFalse(released_files.status_of(rel)['unused'])
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        status = released_files.status_of(rel)
        self.assertTrue(status['unused'])
        self.assertEqual(0, status['unused_days'])


class LongUnusedNotificationTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('forgetful', password='x')

    def test_one_grouped_notification_after_the_threshold_and_never_twice(self):
        for i in range(2):
            synthesis, _, _ = _owned_output(self.user, f'old{i}.wav')
            release_card_file(synthesis, 'audio_output')
            synthesis.delete()
        later = timezone.now() + timedelta(days=released_files.UNUSED_NOTICE_DAYS + 1)
        self.assertEqual(0, released_files.notify_long_unused(timezone.now()))
        self.assertEqual(1, released_files.notify_long_unused(later))
        note = Notification.objects.get(recipient=self.user, kind='files_unused')
        self.assertIn('2 fichier(s)', note.title)
        self.assertIn('rien n\'est supprimé sans vous', note.body)
        self.assertEqual(0, released_files.notify_long_unused(later))


class AskingBeforeRemovalTest(TestCase):
    """La confirmation DEMANDE d'avance (2026-10-01) : aperçu de ce que le retrait libérerait,
    puis la décision — supprimer ou garder — sur ces chemins-là."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('asked', password='x')

    def test_the_last_card_of_a_file_frees_it(self):
        synthesis, rel, _ = _owned_output(self.user)
        self.assertEqual([rel], released_files.freed_by([synthesis]))

    def test_a_file_another_card_still_uses_is_not_offered(self):
        synthesis, rel, _ = _owned_output(self.user)
        twin = VoiceSynthesis.objects.create(user=self.user, text_file='t.txt')
        twin.audio_output.name = rel
        twin.save(update_fields=['audio_output'])
        self.assertEqual([], released_files.freed_by([synthesis]))
        # …mais retirer les DEUX (un lot, toute la file) le libère bien.
        self.assertEqual([rel], released_files.freed_by([synthesis, twin]))

    def test_a_file_the_card_only_designates_is_never_offered(self):
        path = Path(settings.MEDIA_ROOT) / f'users/{self.user.id}/temp/source.wav'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        card = VoiceSynthesis.objects.create(user=self.user, text_file='x.txt')
        card.audio_output.name = f'users/{self.user.id}/temp/source.wav'
        card.save(update_fields=['audio_output'])
        self.assertEqual([], released_files.freed_by([card]))

    def test_keeping_means_not_announced_again(self):
        synthesis, rel, path = _owned_output(self.user)
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        self.assertEqual(1, released_files.keep_released(self.user, paths=[rel]))
        self.assertEqual([], released_files.take_unannounced(self.user))
        self.assertTrue(path.exists())
        self.assertTrue(released_files.status_of(rel)['unused'], 'toujours dit inutilisé')

    def test_the_preview_route_and_the_decision_by_path(self):
        synthesis, rel, path = _owned_output(self.user)
        self.client.force_login(self.user)
        url = reverse('common:api_released_files_preview')
        files = self.client.get(url, {'surface': 'synthesizer', 'nature': 'element',
                                      'pk': synthesis.pk}).json()['files']
        self.assertEqual([rel], [f['path'] for f in files])
        queue = self.client.get(url, {'surface': 'synthesizer', 'nature': 'queue'}).json()['files']
        self.assertEqual([rel], [f['path'] for f in queue])
        # Le retrait, puis la case cochée : suppression par CHEMIN.
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        done = self.client.post(reverse('common:api_released_files_delete'), {'paths': [rel]}).json()
        self.assertEqual([rel], done['deleted'])
        self.assertFalse(path.exists())

    def test_the_preview_of_someone_elses_card_is_refused(self):
        synthesis, _rel, _ = _owned_output(self.user)
        other = get_user_model().objects.create_user('curious', password='x')
        self.client.force_login(other)
        r = self.client.get(reverse('common:api_released_files_preview'),
                            {'surface': 'synthesizer', 'nature': 'element', 'pk': synthesis.pk})
        self.assertEqual(404, r.status_code)


class UnusedListTest(TestCase):
    """L'onglet « Inutilisés » de la médiathèque (2026-10-01) : TOUS les fichiers libérés, avec taille
    et ancienneté, sans les marquer annoncés ; un fichier repris par une card n'y figure plus."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('unused_list', password='x')

    def _release(self, name):
        synthesis, rel, path = _owned_output(self.user, name)
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        return rel, path

    def test_the_list_gives_size_and_age_and_announces_nothing(self):
        rel, path = self._release('kept.wav')
        listed = released_files.list_unused(self.user)
        self.assertEqual([rel], [f['path'] for f in listed['files']])
        self.assertEqual(path.stat().st_size, listed['files'][0]['size'])
        self.assertEqual(path.stat().st_size, listed['total_size'])
        self.assertEqual(0, listed['files'][0]['unused_days'])
        self.assertEqual([rel], [f['path'] for f in released_files.take_unannounced(self.user)],
                         'lire la liste ne vaut pas annonce')

    def test_the_origin_reads_as_an_app_and_a_role(self):
        """L'origine affichée est LISIBLE (app · rôle du fichier), jamais la clé technique ; une
        origine illisible se rend telle quelle plutôt que de lever."""
        self.assertEqual('fichier de lot',
                         released_files.origin_label('composer.ComposerBatch#1 · batch_file').split(' · ')[1])
        self.assertTrue(released_files.origin_label('synthesizer.VoiceSynthesis#3 · audio_output')
                        .endswith(' · sortie'))
        self.assertTrue(released_files.origin_label('converter.ConversionJob#9 · input_file')
                        .endswith(' · entrée'))
        self.assertEqual('n’importe quoi', released_files.origin_label('n’importe quoi'))

    def test_a_file_taken_back_leaves_the_list(self):
        rel, _ = self._release('taken.wav')
        again = VoiceSynthesis.objects.create(user=self.user, text_file='t.txt')
        again.audio_output.name = rel
        again.save(update_fields=['audio_output'])
        self.assertEqual([], released_files.list_unused(self.user)['files'])

    def test_the_route_and_the_library_tab(self):
        rel, _ = self._release('routed.wav')
        self.client.force_login(self.user)
        data = self.client.get(reverse('common:api_released_files_all')).json()
        self.assertEqual([rel], [f['path'] for f in data['files']])
        other = get_user_model().objects.create_user('unused_other', password='x')
        self.client.force_login(other)
        self.assertEqual([], self.client.get(reverse('common:api_released_files_all')).json()['files'])


class FiniteRetentionForUnusedFilesTest(TestCase):
    """Rétention FINIE (décision de Fabien, 2026-10-01) : la durée choisie s'applique aussi aux
    fichiers gardés — annoncés avant leur terme, supprimés au terme s'il ne répond pas, la liste de
    ce qui est parti envoyée ensuite ; « Garder » leur redonne la durée. Jamais de suppression sans
    annonce préalable."""

    def setUp(self):
        from wama.accounts.models import UserProfile
        self.user = get_user_model().objects.create_user('finite_retention', password='x')
        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.media_retention_days = 10
        profile.save()
        synthesis, self.rel, self.path = _owned_output(self.user, 'kept_with_retention.wav')
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        self.now = timezone.now()

    def _at(self, days):
        return self.now + timedelta(days=days)

    def test_announced_before_the_term_then_deleted_and_reported(self):
        self.assertEqual(0, released_files.notify_long_unused(self._at(5)), 'trop tôt pour prévenir')
        self.assertEqual(1, released_files.notify_long_unused(self._at(8)))
        note = Notification.objects.get(recipient=self.user, kind='files_unused')
        self.assertIn('bientôt supprimé', note.title)
        self.assertIn('10 jours', note.body)
        self.assertEqual({'deleted': 1, 'users': 1}, released_files.purge_expired_released(self._at(11)))
        self.assertFalse(self.path.exists())
        gone = Notification.objects.get(recipient=self.user, kind='files_deleted')
        self.assertIn('kept_with_retention.wav', gone.body)

    def test_never_deleted_without_having_been_announced(self):
        self.assertEqual(0, released_files.purge_expired_released(self._at(30))['deleted'])
        self.assertTrue(self.path.exists())

    def test_keep_gives_the_whole_duration_again(self):
        released_files.notify_long_unused(self._at(8))
        row = ReleasedFile.objects.get(path=self.rel)
        self.assertEqual(1, released_files.renew_released(self.user, ids=[row.pk]))
        row.refresh_from_db()
        self.assertIsNone(row.notified_at, 'il sera annoncé de nouveau avant son prochain terme')
        self.assertEqual(0, released_files.purge_expired_released(self._at(11))['deleted'])
        self.assertTrue(self.path.exists())

    def test_the_list_says_when_it_will_go(self):
        listed = released_files.list_unused(self.user)
        self.assertEqual(10, listed['retention_days'])
        self.assertTrue(listed['files'][0]['deletes_on'])

    def test_infinite_retention_deletes_nothing(self):
        other = get_user_model().objects.create_user('infinite_retention', password='x')
        synthesis, _rel, path = _owned_output(other, 'kept_forever.wav')
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        released_files.notify_long_unused(self._at(400))
        released_files.purge_expired_released(self._at(800))
        self.assertTrue(path.exists())
        self.assertIsNone(released_files.list_unused(other)['retention_days'] or None)


class AnnounceRouteTest(TestCase):

    def test_the_page_reads_the_announcement_and_deletes_on_request(self):
        user = get_user_model().objects.create_user('announced', password='x')
        synthesis, rel, path = _owned_output(user)
        release_card_file(synthesis, 'audio_output')
        synthesis.delete()
        self.client.force_login(user)
        files = self.client.get(reverse('common:api_released_files')).json()['files']
        self.assertEqual([rel], [f['path'] for f in files])
        response = self.client.post(reverse('common:api_released_files_delete'),
                                    {'ids': [files[0]['id']]})
        self.assertEqual([rel], response.json()['deleted'])
        self.assertFalse(path.exists())
