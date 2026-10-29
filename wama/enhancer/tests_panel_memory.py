"""Le volet de l'enhancer MÉMORISE ses réglages par la brique commune (2026-09-29).

La table `UserSettings` propre à l'enhancer n'était jamais écrite : ses « défauts » étaient ceux
du modèle pour tout le monde, et le modèle, le débruitage et le blend du volet ne partaient
qu'avec « Tout démarrer » — un élément déposé naissait sur les défauts. Désormais le dépôt
poste le volet, l'élément naît complet, et ce qui a été posté devient la mémoire du volet
(`save_panel_settings` → `UserAppSetting`).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.common.tests.tests_import_contract import _WITNESSES
from wama.common.utils.user_settings import read_panel_settings
from wama.enhancer.models import Enhancement
from wama.enhancer.params import MEDIA_PARAMS

User = get_user_model()


def _call_tool(test, tool, user, kind, **kwargs):
    """The assistant's creating tool called on a file of the author's own tree (a disposable
    MEDIA_ROOT, erased by the path created here)."""
    import shutil
    import tempfile
    from pathlib import Path
    from wama import tool_api
    root = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, root, True)
    ext, content = _WITNESSES[kind]
    rel = f'users/{user.pk}/temp/sent{ext}'
    (Path(root) / rel).parent.mkdir(parents=True)
    (Path(root) / rel).write_bytes(content())
    with test.settings(MEDIA_ROOT=root):
        return getattr(tool_api, tool)(user, rel, **kwargs)


class PanelMemoryTest(TestCase):

    def _user(self, name):
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        user = User.objects.create_user(name, password='x')
        for role in (DEFAULT_APP_ACCESS.get('enhancer') or {}).get('roles', []):
            user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        return user

    def _deposit(self, **panel):
        ext, content = _WITNESSES['image']
        data = {'file': SimpleUploadedFile('witness' + ext, content(), content_type='image/png'),
                **panel}
        return self.client.post(reverse('enhancer:upload'), data)

    def _shown(self):
        """What the page gives its GENERATED panel (2026-10-11): the values handed to
        `WamaParams.render`, by param name — no pre-rendered `selected` any more."""
        import json
        response = self.client.get(reverse('enhancer:index'))
        return json.loads(response.context['panel_values_json'])

    def setUp(self):
        self.me = self._user('enhancer_panel_me')
        self.client.force_login(self.me)
        # A catalogued upscaler for the deposits (route F4b ⑤, 2026-10-06).
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='enhancer:BSRGANx2', name='BSRGANx2',
                               model_type='upscaling', source='enhancer', is_downloaded=True,
                               capabilities={'task': 'upscale', 'scale': 2},
                               composition={'runtime': {'engine': 'onnxruntime'}})

    def test_the_element_is_born_with_the_panel_settings(self):
        """A client of before posts the bare id: the element is born with its catalogue KEY."""
        response = self._deposit(ai_model='BSRGANx2', denoise='true', blend_factor='0.3')
        self.assertLess(response.status_code, 400, response.content[:300])
        item = Enhancement.objects.filter(user=self.me).latest('id')
        self.assertEqual(('enhancer:BSRGANx2', True, 0.3),
                         (item.ai_model, item.denoise, item.blend_factor))

    def test_the_deposit_is_remembered_and_the_page_shows_it(self):
        self._deposit(ai_model='enhancer:BSRGANx2', denoise='true', blend_factor='0.3')
        memory = read_panel_settings(self.me, 'enhancer', MEDIA_PARAMS)
        self.assertEqual(('enhancer:BSRGANx2', True, 0.3),
                         (memory['ai_model'], memory['denoise'], memory['blend_factor']))
        self.assertEqual('enhancer:BSRGANx2', self._shown()['ai_model'])

    def test_a_choice_remembered_before_the_switch_is_shown_under_its_key(self):
        """Memory written before route F4b ⑤ holds the bare id: the page selects its key."""
        self._deposit(ai_model='BSRGANx2')
        self.assertEqual('enhancer:BSRGANx2', self._shown()['ai_model'])

    def test_the_output_format_and_quality_come_back_too(self):
        """Format et qualité de sortie : mémorisés ET ré-affichés (rendus du schéma)."""
        self._deposit(output_format='png', output_quality='max')
        shown = self._shown()
        self.assertEqual(('png', 'max'), (shown['output_format'], shown['output_quality']))

    def test_the_assistant_tool_is_born_with_the_author_settings(self):
        """`add_to_enhancer` was born on fixed defaults (`RealESR_Gx4`, no denoising) whatever
        the panel said (2026-10-29) ; what the tool receives still wins."""
        self._deposit(ai_model='enhancer:BSRGANx2', denoise='true', blend_factor='0.3')
        result = _call_tool(self, 'add_to_enhancer', self.me, 'image')
        self.assertNotIn('error', result)
        item = Enhancement.objects.get(pk=result['item_id'])
        self.assertEqual(('enhancer:BSRGANx2', True, 0.3),
                         (item.ai_model, item.denoise, item.blend_factor))
        result = _call_tool(self, 'add_to_enhancer', self.me, 'image', blend_factor=0.6)
        self.assertEqual(0.6, Enhancement.objects.get(pk=result['item_id']).blend_factor)
        self.assertIn('error', _call_tool(self, 'add_to_enhancer', self.me, 'image',
                                          ai_model='enhancer:nowhere'))

    def test_another_user_does_not_inherit_it(self):
        """Contre-épreuve : la mémoire est celle de l'auteur, un autre repart des défauts."""
        self._deposit(ai_model='BSRGANx2', denoise='true', blend_factor='0.3')
        other = self._user('enhancer_panel_other')
        memory = read_panel_settings(other, 'enhancer', MEDIA_PARAMS)
        self.assertNotEqual('BSRGANx2', memory['ai_model'])
        self.assertFalse(memory['denoise'])


class AudioPanelMemoryTest(TestCase):
    """The AUDIO tab follows the SAME model as the image/video one (2026-10-28, Fabien : « il faut
    aligner l'onglet audio […] d'un bloc »). Before : the audio deposit created the element on the
    model's defaults, the panel was re-applied at EVERY ▶, nothing was retained, four views copied
    their own list of settings, and the force of the denoising was named `strength` for a column
    `denoising_strength`. Now : born with the panel, panel retained and shown again, ▶ launches
    with the STORED settings, one function applies them — and every way in (card, batch, « Envoyer
    vers », the assistant's tool) is born the same."""

    ENGINE = 'enhancer:resemble'

    _user = PanelMemoryTest._user

    def setUp(self):
        self.me = self._user('enhancer_audio_me')
        self.client.force_login(self.me)
        from wama.model_manager.models import AIModel
        for key in (self.ENGINE, 'enhancer:deepfilternet'):
            AIModel.objects.create(model_key=key, name=key.split(':')[1], model_type='audio',
                                   source='enhancer', is_downloaded=True, is_available=True,
                                   capabilities={'task': 'audio-enhance'},
                                   composition={'runtime': {'engine': 'torch'}})

    def _deposit(self, **panel):
        ext, content = _WITNESSES['audio']
        data = {'file': SimpleUploadedFile('voice' + ext, content(), content_type='audio/wav'),
                **panel}
        return self.client.post(reverse('enhancer:audio_upload'), data)

    def _latest(self):
        from wama.enhancer.models import AudioEnhancement
        return AudioEnhancement.objects.filter(user=self.me).latest('id')

    PANEL = {'engine': ENGINE, 'mode': 'denoise', 'denoising_strength': '0.8', 'quality': '128',
             'output_format': 'flac', 'output_quality': 'max'}

    def test_the_setting_has_the_name_of_its_column(self):
        from wama.enhancer.models import AudioEnhancement
        from wama.enhancer.params import AUDIO_PARAMS
        columns = {f.name for f in AudioEnhancement._meta.concrete_fields}
        self.assertEqual(set(), {p.name for p in AUDIO_PARAMS} - columns,
                         'a setting the birth cascade cannot pose is a setting lost')

    def test_the_audio_element_is_born_with_the_panel_and_it_is_remembered(self):
        response = self._deposit(**self.PANEL)
        self.assertLess(response.status_code, 400, response.content[:300])
        item = self._latest()
        self.assertEqual((self.ENGINE, 'denoise', 0.8, 128, 'flac', 'max'),
                         (item.engine, item.mode, item.denoising_strength, item.quality,
                          item.output_format, item.output_quality))
        import json
        shown = json.loads(self.client.get(reverse('enhancer:index'))
                           .context['audio_panel_values_json'])
        self.assertEqual(('denoise', 0.8, 'flac'),
                         (shown['mode'], shown['denoising_strength'], shown['output_format']))

    def test_a_deposit_without_panel_takes_the_remembered_one(self):
        self._deposit(**self.PANEL)
        self._deposit()
        item = self._latest()
        self.assertEqual(('denoise', 0.8, 'flac'),
                         (item.mode, item.denoising_strength, item.output_format))

    def test_the_card_start_launches_with_the_STORED_settings(self):
        """▶ of a card : empty body, the element keeps what it was set to — the panel changed
        meanwhile no longer rewrites it in silence."""
        from unittest import mock
        self._deposit(**self.PANEL)
        item = self._latest()
        with mock.patch('wama.enhancer.tasks.enhance_audio.delay',
                        return_value=mock.Mock(id='task-1')):
            response = self.client.post(reverse('enhancer:audio_start', args=[item.pk]),
                                        data='{}', content_type='application/json')
        self.assertLess(response.status_code, 400, response.content[:300])
        item.refresh_from_db()
        self.assertEqual(('denoise', 0.8), (item.mode, item.denoising_strength))

    def test_the_item_settings_route_writes_by_the_schema(self):
        self._deposit()
        item = self._latest()
        response = self.client.post(reverse('enhancer:audio_update', args=[item.pk]),
                                    {'denoising_strength': '0.2', 'mode': 'enhance',
                                     'output_format': 'mp3'})
        self.assertLess(response.status_code, 400, response.content[:300])
        item.refresh_from_db()
        self.assertEqual((0.2, 'enhance', 'mp3'),
                         (item.denoising_strength, item.mode, item.output_format))

    def test_sent_to_the_enhancer_an_audio_carries_the_author_settings(self):
        """« Envoyer vers » (filemanager) : born like a deposit — it took the model's defaults."""
        import tempfile
        from pathlib import Path
        from wama.filemanager.views import import_to_enhancer
        self._deposit(**self.PANEL)
        ext, content = _WITNESSES['audio']
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, folder, True)
        source = folder / ('sent' + ext)
        source.write_bytes(content())
        with self.settings(MEDIA_ROOT=str(folder)):
            result = import_to_enhancer(source, self.me)
        from wama.enhancer.models import AudioEnhancement
        sent = AudioEnhancement.objects.get(pk=result['id'])
        self.assertEqual(('denoise', 0.8, 'flac'),
                         (sent.mode, sent.denoising_strength, sent.output_format))

    def test_the_assistant_audio_tool_is_born_with_the_author_settings(self):
        """The fourth way in of the audio port (2026-10-28), until then without a guard."""
        self._deposit(**self.PANEL)
        result = _call_tool(self, 'add_to_audio_enhancer', self.me, 'audio')
        self.assertNotIn('error', result)
        from wama.enhancer.models import AudioEnhancement
        item = AudioEnhancement.objects.get(pk=result['item_id'])
        self.assertEqual((self.ENGINE, 'denoise', 0.8, 'flac'),
                         (item.engine, item.mode, item.denoising_strength, item.output_format))
        result = _call_tool(self, 'add_to_audio_enhancer', self.me, 'audio', mode='enhance')
        self.assertEqual('enhance', AudioEnhancement.objects.get(pk=result['item_id']).mode)

    def test_the_batch_modal_of_each_domain_has_its_settings(self):
        """No setting declared the BATCH context : the batch ⚙ opened EMPTY in both domains
        (measured 2026-10-28 : 0 of 8, 0 of 7)."""
        from wama.enhancer.params import AUDIO_PARAMS_JSON, MEDIA_PARAMS_JSON
        for schema in (MEDIA_PARAMS_JSON, AUDIO_PARAMS_JSON):
            self.assertEqual([p['name'] for p in schema],
                             [p['name'] for p in schema if 'batch' in p['contexts']])

    def test_the_audio_batch_settings_reach_every_child(self):
        """The audio batch had no settings route : its ⚙ was rendered, nothing listened."""
        from wama.enhancer.models import (AudioEnhancement, BatchAudioEnhancement,
                                          BatchAudioEnhancementItem)
        batch = BatchAudioEnhancement.objects.create(user=self.me, total=2)
        children = [AudioEnhancement.objects.create(user=self.me) for _ in range(2)]
        for index, child in enumerate(children):
            BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=child,
                                                     row_index=index)
        response = self.client.post(reverse('enhancer:audio_batch_update', args=[batch.pk]),
                                    {'mode': 'enhance', 'denoising_strength': '0.3'})
        self.assertLess(response.status_code, 400, response.content[:300])
        for child in children:
            child.refresh_from_db()
            self.assertEqual(('enhance', 0.3), (child.mode, child.denoising_strength))

    def test_another_user_does_not_inherit_the_audio_panel(self):
        self._deposit(**self.PANEL)
        other = self._user('enhancer_audio_other')
        from wama.enhancer.params import AUDIO_PARAMS
        memory = read_panel_settings(other, 'enhancer', AUDIO_PARAMS)
        self.assertEqual(('both', 0.5, 'original'),
                         (memory['mode'], memory['denoising_strength'], memory['output_format']))
