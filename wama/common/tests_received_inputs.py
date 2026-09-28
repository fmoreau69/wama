"""`media_paths.received_inputs` — ce qu'une vue d'upload reçoit : un fichier TÉLÉVERSÉ, ou un
fichier DÉSIGNÉ (choisi dans la médiathèque, glissé depuis l'arbre).

Décision du 2026-09-28 (plan de la card v4, étape 1, `CARD_DESIGN §11.11`) : la tuile
Médiathèque de la card ne re-téléverse plus le fichier — elle le DÉSIGNE à la MÊME vue d'upload,
qui garde ainsi les réglages du volet envoyés avec le dépôt. La brique décide pointer ou copier
(`reference_or_copy`) et refuse ce que l'utilisateur ne peut pas lire (`readable_by`).
"""
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from wama.common.utils.media_paths import (DESIGNATION_FIELD, SYSTEM_ASSET_ROOT, readable_by,
                                           received_inputs)


class ReceivedInputsTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = User.objects.create_user('designer', password='x')
        self.other = User.objects.create_user('someone_else', password='x')
        self.factory = RequestFactory()

    def _write(self, rel, content=b'RIFF'):
        path = Path(self.tmp) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return rel

    def _post(self, data):
        return self.factory.post('/upload/', data)

    def _app_files(self, app):
        base = Path(self.tmp) / 'users' / str(self.user.id) / app
        return sorted(p.name for p in base.rglob('*') if p.is_file()) if base.exists() else []

    def test_an_uploaded_file_is_received_unchanged(self):
        upload = SimpleUploadedFile('voice.wav', b'RIFF', content_type='audio/wav')
        got = received_inputs(self._post({'file': upload}), self.user, 'transcriber')
        self.assertEqual(1, len(got))
        self.assertFalse(got[0].designated)
        self.assertEqual('voice.wav', got[0].name)
        from django.core.files.uploadedfile import UploadedFile
        self.assertIsInstance(got[0].value, UploadedFile, 'la vue assigne le fichier téléversé')

    def test_a_file_designated_in_the_users_own_tree_is_pointed_not_copied(self):
        rel = self._write(f'users/{self.user.id}/media_library/assets/interview.wav')
        got = received_inputs(self._post({DESIGNATION_FIELD: rel}), self.user, 'transcriber')
        self.assertEqual(1, len(got), got.refusal)
        self.assertTrue(got[0].designated)
        self.assertEqual(rel, got[0].value, "la valeur assignée est le chemin : c'est le pointage")
        self.assertEqual('interview.wav', got[0].name)
        self.assertEqual(b'RIFF', b''.join(got[0].chunks()))
        self.assertEqual([], self._app_files('transcriber'), "aucune copie dans le dossier de l'app")

    def test_an_active_system_asset_is_pointed(self):
        from wama.media_library.models import SystemAsset
        rel = self._write(f'{SYSTEM_ASSET_ROOT}/voice/narrator.wav')
        SystemAsset.objects.create(name='narrator', asset_type='voice', file=rel, is_active=True)
        got = received_inputs(self._post({DESIGNATION_FIELD: rel}), self.user, 'synthesizer')
        self.assertEqual([rel], [r.value for r in got], got.refusal)
        self.assertEqual([], self._app_files('synthesizer'))

    def test_what_the_user_cannot_read_is_refused_and_said(self):
        from wama.media_library.models import SystemAsset
        theirs = self._write(f'users/{self.other.id}/media_library/assets/private.wav')
        inactive = self._write(f'{SYSTEM_ASSET_ROOT}/voice/retired.wav')
        SystemAsset.objects.create(name='retired', asset_type='voice', file=inactive,
                                   is_active=False)
        loose = self._write(f'{SYSTEM_ASSET_ROOT}/voice/no_row.wav')
        for designation in (theirs, inactive, loose, '../../etc/passwd',
                            f'users/{self.user.id}/temp/missing.wav'):
            with self.subTest(designation=designation):
                got = received_inputs(self._post({DESIGNATION_FIELD: designation}),
                                      self.user, 'transcriber')
                self.assertEqual([], list(got))
                self.assertTrue(got.refusal, 'un refus se DIT')
        self.assertEqual([], self._app_files('transcriber'), 'un refus ne copie rien non plus')

    def test_uploads_and_designations_arrive_together_in_that_order(self):
        rel = self._write(f'users/{self.user.id}/temp/b.wav')
        upload = SimpleUploadedFile('a.wav', b'RIFF')
        got = received_inputs(self._post({'files': [upload], DESIGNATION_FIELD: [rel]}),
                              self.user, 'reader', field='files')
        self.assertEqual(['a.wav', 'b.wav'], [r.name for r in got])
        self.assertEqual([False, True], [r.designated for r in got])

    def test_readable_by_is_the_single_rule(self):
        mine = f'users/{self.user.id}/temp/x.wav'
        self.assertTrue(readable_by(mine, self.user))
        self.assertFalse(readable_by(mine, self.other), "l'arbre d'autrui n'est pas lisible")
        self.assertFalse(readable_by(f'users/{self.user.id}0/temp/x.wav', self.user),
                         'le préfixe est un SEGMENT : users/12 ne lit pas users/120')

    def test_record_writes_the_provenance_of_a_designation(self):
        from wama.common.tests_queue_delete_contract import _instance
        from wama.common.utils.provenance import provenance_of
        from wama.transcriber.models import Transcript

        rel = self._write(f'users/{self.user.id}/media_library/assets/talk.wav')
        got = received_inputs(self._post({DESIGNATION_FIELD: rel}), self.user, 'transcriber')
        item = _instance(Transcript, self.user)
        item.audio = got[0].value
        item.save()
        got[0].record(item, 'audio')
        prov = provenance_of(item, 'audio')
        self.assertIsNotNone(prov)
        self.assertEqual('asset', prov.kind)
        self.assertEqual(rel, prov.ref)
