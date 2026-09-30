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

    def _declare_talkinghead(self):
        """La ligne de catalogue, avec l'exigence d'attributs que la découverte déclare."""
        from wama.model_manager.models import AIModel
        AIModel.objects.update_or_create(model_key=workers.TALKINGHEAD_KEY, defaults=dict(
            name='TalkingHead', model_type='lipsync', source='avatarizer',
            capabilities={'input_attributes': {'work_object3d': {
                'require': {'rigged': True, 'face_rig': 'arkit'}, 'prefer': {'visemes': 'oculus'}}}}))

    def test_a_glb_avatar_is_rendered_by_talkinghead(self):
        self._declare_talkinghead()
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
        self._declare_talkinghead()
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

    def test_a_glb_without_text_fails_with_a_reason(self):
        self._declare_talkinghead()
        job = self._job(self._talking_glb(), text='')
        job.audio_input = _media(f'avatarizer/{self.user.id}/input/voice.wav',
                                 Path(_silent_wav(Path(settings.MEDIA_ROOT) / 'v.wav')).read_bytes())
        job.save()
        job, keys = self._run(job)
        self.assertEqual('FAILURE', job.status)
        self.assertIn('TEXTE', job.error_message)
        self.assertEqual([], keys)


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
