"""Le worker choisit le MOTEUR d'après la NATURE de l'avatar (2026-09-30).

Une photo s'anime par MuseTalk (inchangé) ; un avatar 3D riggé (.glb) se rend par TalkingHead,
résolu par son moteur. Le TTS et les moteurs sont simulés : c'est l'AIGUILLAGE qui est testé,
pas le rendu (joué à la main sur la 4090, `PROSPECTION_AVATARS_2026-09-30.md`).
"""
import wave
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.avatarizer import workers
from wama.avatarizer.models import AvatarJob

User = get_user_model()


def _media(rel, data=b'x'):
    path = Path(settings.MEDIA_ROOT) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def _silent_wav(path):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b'\x00\x00' * 1600)
    return str(path)


class FakeRender:
    """Tient lieu de moteur : écrit une « vidéo » là où on la lui demande, et note l'appel."""
    calls = []

    def process(self, *args, **kwargs):
        # CodeFormer est appelé en POSITIONNEL : process(vidéo, dossier de travail).
        FakeRender.calls.append(kwargs or {'args': args})
        folder = kwargs.get('output_dir') or (args[1] if len(args) > 1 else None)
        target = Path(kwargs.get('output_path') or Path(folder) / f'out{len(FakeRender.calls)}.mp4')
        target.write_bytes(b'mp4')
        return str(target)


class EngineFromAvatarNatureTest(TestCase):

    def setUp(self):
        FakeRender.calls = []
        self.user = User.objects.create_user('th_engine_user', password='x')
        wav_dir = Path(settings.MEDIA_ROOT) / 'tmp_tests'
        wav_dir.mkdir(parents=True, exist_ok=True)
        self.tts = patch.object(workers, '_call_tts_service',
                                side_effect=lambda job: _silent_wav(wav_dir / f'tts{job.id}.wav'))
        self.tts.start()
        self.addCleanup(self.tts.stop)
        # La tâche ferme les connexions périmées en entrée (utile dans un worker Celery) : dans
        # un TestCase, cela fermerait la connexion de la transaction du test.
        keep_connection = patch.object(workers, 'close_old_connections')
        keep_connection.start()
        self.addCleanup(keep_connection.stop)

    def _job(self, avatar_rel, text='Bonjour, voici une consigne.'):
        return AvatarJob.objects.create(
            user=self.user, mode='pipeline' if text else 'standalone', text_content=text,
            tts_model='synthesizer:kokoro', avatar_source='upload', avatar_upload=avatar_rel,
            use_enhancer=True)

    def _run(self, job):
        with patch.object(workers, '_backend', return_value=FakeRender()) as by_key:
            workers.generate_avatar.apply(args=[job.id])
        job.refresh_from_db()
        return job, [c.args[0] for c in by_key.call_args_list]

    def _talking_glb(self, name='scientist.glb', complete=True):
        """Un GLB réduit à sa table des matières : squelette + visage ARKit (+ visèmes)."""
        from wama.common.utils.media_probe import ARKIT_BLENDSHAPES, OCULUS_VISEMES
        from wama.media_library.tests.tests_object3d import glb_from_json
        names = ARKIT_BLENDSHAPES + OCULUS_VISEMES if complete else ('jawOpen',)
        doc = {'asset': {'version': '2.0'}, 'skins': [{}] if complete else [],
               'meshes': [{'name': 'Head', 'extras': {'targetNames': list(names)}, 'primitives': []}]}
        return _media(f'avatarizer/{self.user.id}/input/{name}', glb_from_json(doc))

    def _register_talkinghead(self):
        """La ligne de catalogue, avec l'exigence d'attributs que la découverte déclare."""
        from wama.model_manager.models import AIModel
        AIModel.objects.update_or_create(model_key=workers.TALKINGHEAD_KEY, defaults=dict(
            name='TalkingHead', model_type='lipsync', source='avatarizer',
            is_available=True, is_downloaded=True,
            composition={'runtime': {'engine': 'talkinghead'}},
            capabilities={'task': 'lip-sync', 'inputs_required': ['work_object3d', 'work_audio'],
                          'inputs_optional': ['prompt'],
                          'input_attributes': {'work_object3d': {
                              'require': {'rigged': True, 'face_rig': 'arkit'},
                              'prefer': {'visemes': 'oculus'}}}}))

    def test_a_glb_avatar_is_rendered_by_talkinghead(self):
        self._register_talkinghead()
        job, keys = self._run(self._job(self._talking_glb()))
        self.assertEqual('SUCCESS', job.status, job.error_message)
        # Ni MuseTalk ni CodeFormer : sans objet sur un rendu 3D. Résolu par le CATALOGUE.
        self.assertEqual([workers.TALKINGHEAD_KEY], keys)
        call = FakeRender.calls[0]
        self.assertEqual('Bonjour, voici une consigne.', call['text'], 'le texte donne les lèvres')
        self.assertTrue(call['avatar_path'].endswith('scientist.glb'))
        self.assertIn('talkinghead', job.output_video.name)

    def test_a_mesh_without_rig_or_face_is_refused_with_its_reason(self):
        """Le bon RÔLE (objet 3D) mais pas les ATTRIBUTS : un maillage TripoSR ne parlera pas."""
        self._register_talkinghead()
        job, keys = self._run(self._job(self._talking_glb('mesh.glb', complete=False)))
        self.assertEqual('FAILURE', job.status)
        self.assertIn('rigged', job.error_message)
        self.assertIn('ARKit', job.error_message)
        self.assertEqual([], keys, 'refusé AVANT tout rendu')

    def test_a_photo_still_goes_to_musetalk(self):
        """Contre-épreuve : le chemin historique est inchangé (MuseTalk puis CodeFormer)."""
        job, keys = self._run(self._job(_media(f'avatarizer/{self.user.id}/input/face.png')))
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual(['avatarizer:musetalk-v1.5', 'avatarizer:codeformer'], keys)

    def _audio_only_job(self):
        self._register_talkinghead()
        job = self._job(self._talking_glb(), text='')
        job.audio_input = _media(f'avatarizer/{self.user.id}/input/voice.wav',
                                 Path(_silent_wav(Path(settings.MEDIA_ROOT) / 'v.wav')).read_bytes())
        job.save()
        return job

    def _heard(self, words, language='en'):
        from wama.common.utils.whisper_utils import WhisperResult, WhisperSegment
        return WhisperResult(text=' '.join(w['word'] for w in words), language=language,
                             duration=1.0, segments=[WhisperSegment(0.0, 1.0, '', words)])

    def test_an_audio_without_text_is_transcribed_into_dated_words(self):
        """Le sens inverse du TTS : audio → Transcriber (brique commune) → mots DATÉS → lèvres."""
        words = [{'word': ' Hello', 'start': 0.1, 'end': 0.4}, {'word': ' world', 'start': 0.5, 'end': 0.9}]
        with patch('wama.common.utils.whisper_utils.transcribe_audio',
                   return_value=self._heard(words)) as heard:
            job, keys = self._run(self._audio_only_job())
        self.assertEqual('SUCCESS', job.status, job.error_message)
        heard.assert_called_once()
        self.assertEqual([workers.TALKINGHEAD_KEY], keys)
        call = FakeRender.calls[0]
        self.assertEqual(words, call['words'], 'les mots datés vont au moteur tels quels')
        self.assertEqual('en', call['language'], 'la langue ENTENDUE choisit les visèmes')

    def test_an_audio_with_no_speech_fails_with_a_reason(self):
        with patch('wama.common.utils.whisper_utils.transcribe_audio', return_value=self._heard([])):
            job, keys = self._run(self._audio_only_job())
        self.assertEqual('FAILURE', job.status)
        self.assertIn('aucune parole', job.error_message)
        self.assertEqual([], keys)


class EmptyDrawFallsBackTest(TestCase):
    """Un tirage que RIEN ne satisfait rend le repli (2026-09-30, brique `select_model_id`).

    Mesuré sur la vraie base : des entrées qu'aucun modèle n'accepte rendaient `musetalk-v1.0`
    — la liste vide de candidats valait « aucune restriction » pour `select_model`."""

    def test_no_matching_model_gives_the_fallback_not_any_model(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services import model_selector as ms
        AIModel.objects.create(model_key='avatarizer:other', name='other', model_type='lipsync',
                               source='avatarizer', is_available=True, is_downloaded=True,
                               capabilities={'task': 'lip-sync', 'inputs_required': ['work_image']})
        with patch.object(ms, 'get_registry_models', return_value=([], [])):
            got = ms.select_model_id('avatarizer', requested='auto', fallback='REPLI', task='lip-sync',
                                     available_inputs=['work_audio'], consumes=['work_audio'])
        self.assertEqual('REPLI', got)


class TalkingHeadDeclarationTest(TestCase):
    """La découverte déclare le modèle : son moteur, son RÔLE d'entrée et les ATTRIBUTS exigés."""

    def test_the_catalog_row_carries_engine_role_and_attribute_requirements(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = object.__new__(ModelRegistry)       # hors singleton : aucun état partagé
        registry._models = {}
        registry._discover_avatarizer_models()
        info = registry._models.get('avatarizer:talkinghead')
        if info is None:
            self.skipTest('AI-models/models/lipsync absent : la découverte avatarizer ne tourne pas')
        caps = info.capabilities
        self.assertEqual('talkinghead', info.composition['runtime']['engine'])
        self.assertEqual(['work_object3d', 'work_audio'], caps['inputs_required'])
        self.assertEqual({'rigged': True, 'face_rig': 'arkit'},
                         caps['input_attributes']['work_object3d']['require'])
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.model_capabilities import MODALITIES
        self.assertTrue(set(caps['inputs_required'] + caps['inputs_optional']) <= set(INPUT_TYPES))
        self.assertTrue(set(caps['modalities']) <= set(MODALITIES))


class AddTimeVerdictTest(TestCase):
    """Un GLB qui ne peut pas parler est refusé DÈS L'AJOUT à la file (2026-09-30), pas au
    lancement ; un avatar 3D se cite aussi par son NOM (lot, Studio, assistant)."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.user = User.objects.create_user('th_add_user', password='x')
        for role in (DEFAULT_APP_ACCESS.get('avatarizer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)
        EngineFromAvatarNatureTest._register_talkinghead(self)

    @staticmethod
    def _glb(complete):
        from wama.common.utils.media_probe import ARKIT_BLENDSHAPES, OCULUS_VISEMES
        from wama.media_library.tests.tests_object3d import glb_from_json
        names = ARKIT_BLENDSHAPES + OCULUS_VISEMES if complete else ('jawOpen',)
        return glb_from_json({'asset': {'version': '2.0'}, 'skins': [{}] if complete else [],
                              'meshes': [{'name': 'Head', 'extras': {'targetNames': list(names)},
                                          'primitives': []}]})

    def _create(self, glb_bytes):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post('/avatarizer/create/', {
            'text_content': 'Bonjour.', 'avatar_source': 'upload',
            'avatar_upload': SimpleUploadedFile('avatar.glb', glb_bytes, 'model/gltf-binary')})

    def test_a_mute_glb_is_refused_when_added_with_its_reason(self):
        response = self._create(self._glb(complete=False))
        self.assertEqual(400, response.status_code, response.content[:300])
        self.assertIn('rigged', response.json()['error'])
        self.assertFalse(AvatarJob.objects.filter(user=self.user).exists(), 'rien ne naît')

    def test_a_talking_glb_is_added(self):
        response = self._create(self._glb(complete=True))
        self.assertEqual(200, response.status_code, response.content[:300])
        job = AvatarJob.objects.get(pk=response.json()['id'])
        self.assertTrue(job.avatar_upload.name.endswith('.glb'))

    def test_a_3d_avatar_is_designated_by_its_name(self):
        from wama.media_library.models import UserAsset
        from wama.avatarizer.system_assets import designate_named_avatar
        rel = _media(f'users/{self.user.id}/media_library/assets/scientist.glb', self._glb(True))
        UserAsset.objects.create(user=self.user, name='scientist', asset_type='object3d', file=rel)
        self.assertEqual(rel, designate_named_avatar('scientist', self.user).value)

    def test_only_talking_3d_objects_join_the_avatar_names(self):
        """Studio (liste par nom) : un objet 3D n'y entre que s'il PORTE un visage ARKit."""
        from wama.media_library.models import UserAsset
        from wama.media_library.services import visible_asset_names
        UserAsset.objects.create(user=self.user, name='talker', asset_type='object3d',
                                 file=_media(f'users/{self.user.id}/media_library/assets/t.glb'),
                                 attributes={'rigged': True, 'face_rig': 'arkit'})
        UserAsset.objects.create(user=self.user, name='mesh', asset_type='object3d',
                                 file=_media(f'users/{self.user.id}/media_library/assets/m.glb'),
                                 attributes={'rigged': False})
        self.assertEqual(['talker'], visible_asset_names(self.user, 'object3d',
                                                         attributes={'face_rig': 'arkit'}))
        self.assertEqual(['mesh', 'talker'], visible_asset_names(self.user, 'object3d'),
                         'sans filtre, la nature entière (comportement inchangé)')
