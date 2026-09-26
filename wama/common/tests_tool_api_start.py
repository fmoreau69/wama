"""
Gardes des outils de LANCEMENT du pivot assistant (`start_*`) — le côté ÉCRITURE.

LE DÉFAUT MESURÉ (2026-09-23, depuis Discord). `start_anonymizer` rendait
`property 'processed' of 'Media' object has no setter` : il écrivait encore
`media.processed = False` et filtrait `Media.objects.filter(processed=False)`, alors que
l'audit du 2026-07-11 a remplacé ce booléen par `status` et n'a laissé `processed` qu'en
PROPERTY dérivée, pour les lecteurs. **Les deux branches de l'outil étaient donc mortes** —
l'assistant n'a jamais pu lancer une anonymisation, ni à l'unité (AttributeError) ni en lot
(FieldError sur un filtre SQL portant sur une property). Deux mois sans que rien ne le dise :
le scénario nocturne appelle les lectures, pas les lancements.

CE QUE CES GARDES TIENNENT :
  1. l'anonymizer se lance VRAIMENT depuis l'assistant, et par la MÊME brique anti-race que
     le bouton ▶ de sa card (`begin_processing`) — même verrou, mêmes resets, même refus du
     double lancement ;
  2. générique, pour les dix apps : un `start_*` appelé sans élément RÉPOND (dict d'erreur),
     il ne lève pas. C'est ce contrôle-là qui aurait attrapé la branche de lot, et il vaut
     pour toute app portée ensuite.

⚠ Aucune tâche Celery n'est réellement envoyée : `.delay` est remplacé par un double.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from wama import tool_api as T


class _FakeTask:
    id = 'fake-task-id'


class StartAnonymizerTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('starter', password='x')

    def _media(self, status='PENDING'):
        from wama.anonymizer.models import Media
        return Media.objects.create(
            user=self.user, status=status, file_ext='.jpg', media_type='image',
            file=SimpleUploadedFile('photo.jpg', b'x'))

    def test_starting_one_item_really_launches_it(self):
        media = self._media()
        with mock.patch('wama.anonymizer.tasks.process_single_media.delay',
                        return_value=_FakeTask()) as delay:
            result = T.start_anonymizer(self.user, media_id=media.pk)

        self.assertNotIn('error', result)
        self.assertEqual('started', result['status'])
        media.refresh_from_db()
        self.assertEqual('RUNNING', media.status)
        self.assertEqual('fake-task-id', media.task_id)
        # Comme le bouton ▶ : à l'unité, les réglages de l'item font foi.
        self.assertEqual({'force_individual': True}, delay.call_args.kwargs)

    def test_an_item_already_running_is_refused_not_relaunched(self):
        media = self._media(status='RUNNING')
        with mock.patch('wama.anonymizer.tasks.process_single_media.delay',
                        return_value=_FakeTask()) as delay:
            result = T.start_anonymizer(self.user, media_id=media.pk)
        self.assertIn('error', result)
        delay.assert_not_called()

    def test_someone_elses_item_is_not_found(self):
        media = self._media()
        other = get_user_model().objects.create_user('intruder', password='x')
        with mock.patch('wama.anonymizer.tasks.process_single_media.delay',
                        return_value=_FakeTask()) as delay:
            result = T.start_anonymizer(other, media_id=media.pk)
        self.assertIn('introuvable', result.get('error', ''))
        delay.assert_not_called()

    def test_the_batch_branch_answers_on_an_empty_queue(self):
        """La branche qui levait `FieldError` (filtre SQL sur une property)."""
        result = T.start_anonymizer(self.user)
        self.assertIn('error', result)

    def test_the_batch_branch_launches_what_has_not_succeeded(self):
        self._media()
        self._media(status='ERROR')
        self._media(status='SUCCESS')          # abouti : hors lot
        with mock.patch('wama.anonymizer.tasks.process_user_media_batch.delay',
                        return_value=_FakeTask()):
            result = T.start_anonymizer(self.user)
        self.assertEqual(2, result['count'])


class EveryStartToolAnswersTest(TestCase):
    """Générique : un `start_*` sans élément à lancer REND une erreur, il ne LÈVE pas.

    Le contrôle qui manquait. Il ne mesure pas que le lancement marche (cela demande un
    élément par app), mais il traverse le code de sélection de CHAQUE outil — c'est
    exactement là que vivait la moitié du défaut du 23/09, et un filtre écrit sur un champ
    qui n'existe plus lève à la première requête."""

    def test_no_start_tool_raises_when_the_queue_is_empty(self):
        import inspect

        user = get_user_model().objects.create_user('empty-queue', password='x')
        checked = []
        for name, fn in sorted(T.TOOL_REGISTRY.items()):
            if T.tool_role(name) != 'start':
                continue
            params = list(inspect.signature(fn).parameters.values())[1:]
            if any(p.default is inspect.Parameter.empty for p in params):
                continue                       # l'outil EXIGE un id (composer) — hors sujet
            try:
                result = fn(user)
            except Exception as e:             # noqa: BLE001 — c'est ce qu'on interdit
                self.fail(f'{name} a levé {type(e).__name__} : {e}')
            self.assertIsInstance(result, dict, name)
            checked.append(name)
        self.assertGreater(len(checked), 5, f'trop peu d\'outils traversés : {checked}')
