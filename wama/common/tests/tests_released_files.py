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
