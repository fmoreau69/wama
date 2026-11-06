"""The FILES a lot line gives an element — one common path (2026-11-06, Fabien : « fais la brique
commune pour le -r de l'imager et du synthesizer »).

The imager (`-r` → the guiding image), the synthesizer (`-r` → the voice to clone) and the composer
(`-r` → the song to cover) read the column and then LOST it : nothing joined it to the card. A line
now goes to the PORTS of its app (`batch_parsers.line_file_ports`, the Studio's rule, the file's
nature choosing among candidates) and each file is received like on the card
(`line_file_inputs` : a path is DESIGNATED, an address goes to the element's declared source).
"""
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

#: A prompt-first app with two work ports of two natures, and no `-i` (the composer's shape).
COVER_PORTS = [
    {'id': 'prompt', 'group': 'prompt', 'types': ['prompt']},
    {'id': 'work_score', 'group': 'travail', 'types': ['score']},
    {'id': 'work_audio', 'group': 'travail', 'types': ['audio']},
]


class TheReferenceGoesToThePortOfItsNatureTest(SimpleTestCase):

    def _port(self, reference, ports=COVER_PORTS, **line):
        from wama.common.utils.batch_parsers import line_to_ports
        return line_to_ports({'reference': reference, **line}, ports)[0]

    def test_among_several_work_ports_the_file_chooses_by_its_nature(self):
        self.assertEqual({'work_audio': 'theme.wav'}, self._port('theme.wav'))
        self.assertEqual({'work_score': 'song.abc'}, self._port('song.abc'))
        self.assertEqual({'work_score': 'photo.png'}, self._port('photo.png'),
                         'no port of that nature : the first candidate, as before')

    def test_the_main_work_port_stays_to_the_input_of_the_line(self):
        ports = self._port('other.wav', input='first.wav')
        self.assertEqual({'work_score': 'first.wav', 'work_audio': 'other.wav'}, ports)


class ABatchLineGivesItsFilesTest(TestCase):
    """Through the REAL import route of each app : what the line names is on the element."""

    def setUp(self):
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.common.utils.media_paths import app_media_dir, get_app_media_path
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('batch_line_files', password='x')
        for app in ('imager', 'synthesizer'):
            for role in (DEFAULT_APP_ACCESS.get(app) or {}).get('roles', []):
                self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)
        self.files = {}
        for app, name in (('imager', 'guide.png'), ('synthesizer', 'voice.wav')):
            folder = get_app_media_path(app, self.user.id, 'input')
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(b'\x89PNG' if name.endswith('.png') else b'RIFF')
            self.files[app] = f"{app_media_dir(app, self.user.id, 'input')}/{name}"

    def _post(self, url_name, text, field='batch_file'):
        upload = SimpleUploadedFile('lot.txt', text.encode('utf-8'), content_type='text/plain')
        return self.client.post(reverse(url_name), {field: upload}).json()

    def test_the_imager_line_joins_its_image_and_follows_the_mode_of_the_card(self):
        from wama.imager.models import ImageGeneration
        out = self._post('imager:import_batch',
                         f'-p "a lighthouse" -r "{self.files["imager"]}"\n'
                         '-p "a harbour" -r "https://example.org/sea.jpg"\n-p "a boat"\n')
        guided, remote, plain = (ImageGeneration.objects.get(pk=pk) for pk in out['children_ids'])
        self.assertEqual((self.files['imager'], 'img2img'),
                         (guided.reference_image.name, guided.generation_mode))
        self.assertEqual(('https://example.org/sea.jpg', 'img2img'),
                         (remote.source_url, remote.generation_mode))
        self.assertEqual(('', 'txt2img'), (plain.reference_image.name or '', plain.generation_mode))

    def test_the_synthesizer_line_joins_its_voice(self):
        from wama.synthesizer.models import VoiceSynthesis
        out = self._post('synthesizer:batch_create',
                         f'-p "Bonjour à tous" -r "{self.files["synthesizer"]}"\n-p "Au revoir"\n')
        cloned, plain = (VoiceSynthesis.objects.get(pk=pk) for pk in out['synthesis_ids'])
        self.assertEqual(self.files['synthesizer'], cloned.voice_reference.name)
        self.assertFalse(plain.voice_reference)

    def test_a_file_the_user_cannot_read_drops_its_line_and_says_why(self):
        from wama.synthesizer.models import VoiceSynthesis
        out = self._post('synthesizer:batch_create',
                         '-p "Bonjour" -r "users/999999/synthesizer/input/voice.wav"\n-p "Salut"\n')
        self.assertEqual(1, len(out['synthesis_ids']), out)
        self.assertTrue(any(w.startswith('Ligne 1') for w in out['warnings']), out['warnings'])
        self.assertFalse(VoiceSynthesis.objects.filter(voice_reference__contains='999999').exists())

    def test_the_avatarizer_line_reads_only_an_audio_its_author_can_read(self):
        """Its batch checked the confinement only : the audio of another account passed. It is now
        DESIGNATED like on the card — and a refused line is dropped with its reason, instead of a
        job born without audio."""
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.avatarizer.models import AvatarJob
        from wama.common.utils.media_paths import app_media_dir, get_app_media_path
        from wama.studio.tests.tests_entries import _avatar_ports
        for role in (DEFAULT_APP_ACCESS.get('avatarizer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        folder = get_app_media_path('avatarizer', self.user.id, 'input')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'speech.wav').write_bytes(b'RIFF')
        mine = f"{app_media_dir('avatarizer', self.user.id, 'input')}/speech.wav"
        other = get_user_model().objects.create_user('batch_line_other', password='x')
        theirs_dir = get_app_media_path('avatarizer', other.id, 'input')
        theirs_dir.mkdir(parents=True, exist_ok=True)
        (theirs_dir / 'secret.wav').write_bytes(b'RIFF')
        theirs = f"{app_media_dir('avatarizer', other.id, 'input')}/secret.wav"
        with _avatar_ports():
            out = self._post('avatarizer:batch_create',
                             f'-i "{mine}" -r "avatar.png"\n-i "{theirs}" -r "avatar.png"\n')
        jobs = AvatarJob.objects.filter(user=self.user)
        self.assertEqual([mine], [j.audio_input.name for j in jobs], out)
        self.assertTrue(any(w.startswith('Ligne 2') for w in out['warnings']), out['warnings'])
