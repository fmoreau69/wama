"""The VOICE of a composer generation — sung or instrumental (setting `vocals`, 2026-10-04).

Fabien's question: « can the user say singing / no singing in the prompt? Or is a switch
instrumental ↔ song better? » The prompt says it by its FORM (tagged lyrics); `auto` reads that
form, the setting decides when the form is not enough. Who sings is the model's declared
capability (`supports_vocals`), never a model name."""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.composer.utils import vocals

SONG = "Pop douce\n[Verse]\nSous la pluie je marche"


class TheVoiceIsReadFromTheSettingThenFromThePromptTest(SimpleTestCase):

    def test_auto_sings_only_tagged_lyrics(self):
        self.assertTrue(vocals.wants_vocals('auto', SONG))
        self.assertFalse(vocals.wants_vocals('auto', 'une chanson sur la mer'))

    def test_the_setting_wins_over_the_prompt(self):
        self.assertFalse(vocals.wants_vocals('instrumental', SONG))
        self.assertTrue(vocals.wants_vocals('song', 'une chanson sur la mer'))

    def test_an_unknown_value_reads_as_auto(self):
        self.assertEqual('auto', vocals.normalize('karaoke'))
        self.assertEqual('auto', vocals.normalize(None))


class ThePromptOfThisLaunchFollowsTheVoiceTest(SimpleTestCase):

    def _prepare(self, mode, text, *, singer=True, written='[Verse]\nla mer revient', stored='',
                 with_new=False):
        said = []
        with mock.patch.object(vocals, 'sings', return_value=singer), \
                mock.patch('wama.composer.utils.model_choice.label_of', return_value='MusicGen'), \
                mock.patch.object(vocals, 'lyrics_language', return_value='fr'), \
                mock.patch('wama.common.utils.app_metadata.write_lyrics_for',
                           return_value=written) as writer:
            out, new = vocals.prepare_prompt(mode, text, 'composer:x', stored_lyrics=stored,
                                             console=said.append)
        return (out, new, said, writer) if with_new else (out, said, writer)

    def test_instrumental_drops_the_lyrics_and_says_so(self):
        out, said, _ = self._prepare('instrumental', SONG)
        self.assertEqual('Pop douce', out)
        self.assertIn('instrumental', said[0])

    def test_auto_without_lyrics_changes_nothing_and_writes_nothing(self):
        out, said, writer = self._prepare('auto', 'une chanson sur la mer')
        self.assertEqual('une chanson sur la mer', out)
        self.assertEqual([], said)
        writer.assert_not_called()

    def test_a_model_that_does_not_sing_gets_the_description_only(self):
        out, said, _ = self._prepare('auto', SONG, singer=False)
        self.assertEqual('Pop douce', out)
        self.assertIn('MusicGen ne chante pas', said[0])

    def test_a_singer_keeps_the_user_s_lyrics_and_nothing_is_written(self):
        out, _, writer = self._prepare('song', SONG)
        self.assertEqual(SONG, out)
        writer.assert_not_called()

    def test_song_without_lyrics_has_them_written_in_a_language_the_model_sings(self):
        out, new, said, writer = self._prepare('song', 'une chanson sur la mer', with_new=True)
        self.assertEqual('une chanson sur la mer\n\n[Verse]\nla mer revient', out)
        self.assertEqual('[Verse]\nla mer revient', new, 'returned so that the card keeps them')
        self.assertEqual('fr', writer.call_args.kwargs['language'])
        self.assertIn('Paroles écrites', said[0])

    def test_lyrics_that_could_not_be_written_leave_the_piece_instrumental(self):
        out, new, said, _ = self._prepare('song', 'une chanson sur la mer', written='',
                                          with_new=True)
        self.assertEqual(('une chanson sur la mer', ''), (out, new))
        self.assertIn('instrumental', said[0])

    def test_the_card_s_lyrics_are_sung_and_never_rewritten(self):
        out, new, _, writer = self._prepare('song', 'pop douce', stored='[Chorus]\nla la',
                                            with_new=True)
        self.assertEqual(('pop douce\n\n[Chorus]\nla la', ''), (out, new))
        writer.assert_not_called()

    def test_under_auto_the_card_s_lyrics_ask_for_a_voice(self):
        out, _, _ = self._prepare('auto', 'pop douce', stored='la la')
        self.assertEqual('pop douce\n\n[Verse]\nla la', out, 'untagged lyrics become a verse')

    def test_lyrics_in_the_prompt_win_over_the_card_s_and_it_is_said(self):
        out, said, _ = self._prepare('song', SONG, stored='[Chorus]\nautre')
        self.assertEqual(SONG, out)
        self.assertIn('celles de la card sont ignorées', said[0])

    def test_instrumental_leaves_the_card_s_lyrics_unsung_but_kept(self):
        out, new, said, _ = self._prepare('instrumental', 'pop douce', stored='[Verse]\nla',
                                          with_new=True)
        self.assertEqual(('pop douce', ''), (out, new))
        self.assertIn('instrumental', said[0])


class WrittenLyricsAreKeptOnTheCardTest(TestCase):
    """Fabien, 2026-10-04: « persiste les paroles écrites sur la card »."""

    def test_the_launch_writes_them_on_the_card_and_in_memory(self):
        from wama.composer import tasks
        from wama.composer.models import ComposerGeneration
        user = get_user_model().objects.create_user('lyrics_kept', password='x')
        gen = ComposerGeneration.objects.create(user=user, prompt='la mer', vocals='song',
                                                model='huggingface:org/Singer')
        ctx = SimpleNamespace(app_id='composer', console=lambda *a, **k: None)
        with mock.patch.object(tasks, '_model_key', return_value='huggingface:org/Singer'), \
                mock.patch.object(vocals, 'sings', return_value=True), \
                mock.patch.object(vocals, 'lyrics_language', return_value='fr'), \
                mock.patch('wama.common.utils.app_metadata.write_lyrics_for',
                           return_value='[Verse]\nla mer revient'), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: text):
            routed = tasks._routed_prompt(gen, ctx)
        self.assertEqual('la mer\n\n[Verse]\nla mer revient', routed)
        self.assertEqual('[Verse]\nla mer revient', gen.lyrics, 'in memory: the run snapshot')
        gen.refresh_from_db()
        self.assertEqual('[Verse]\nla mer revient', gen.lyrics)

    def test_a_card_lyric_change_makes_the_score_and_the_render_stale(self):
        from wama.composer.function_specs import PIPELINE
        for key in ('plan', 'render'):
            watched = PIPELINE.watched_of(PIPELINE.spec(key))   # dérivé des réglages (2026-10-05)
            self.assertIn('lyrics', watched)
            self.assertIn('vocals', watched)
            self.assertIn('prompt_processed', watched)


class WhoSingsIsDeclaredByTheCatalogueTest(TestCase):

    def setUp(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='huggingface:org/Singer', name='Singer',
                               source='huggingface',
                               capabilities={'task': 'text-to-music', 'languages': ['zh', 'en'],
                                             'supports_vocals': True})
        AIModel.objects.create(model_key='composer:musicgen-small', name='MusicGen',
                               source='composer', capabilities={'task': 'text-to-music'})

    def test_only_the_models_with_the_capability_sing(self):
        self.assertTrue(vocals.sings('huggingface:org/Singer'))
        self.assertFalse(vocals.sings('composer:musicgen-small'))
        self.assertEqual(['huggingface:org/Singer'], vocals.singing_models('text-to-music'))

    def test_the_lyrics_language_is_one_the_model_sings(self):
        french = SimpleNamespace(profile=SimpleNamespace(preferred_language='fr'))
        self.assertEqual('en', vocals.lyrics_language('huggingface:org/Singer', french))
        chinese = SimpleNamespace(profile=SimpleNamespace(preferred_language='zh'))
        self.assertEqual('zh', vocals.lyrics_language('huggingface:org/Singer', chinese))

    def _drawn_spec(self, mode, prompt):
        from wama.composer.utils import auto_model
        gen = SimpleNamespace(model='auto:text-to-music', vocals=mode, prompt=prompt,
                              prompt_processed='', melody_reference=None, source_url='',
                              reference_score=None, user=None, quality_intent=None)
        with mock.patch.object(auto_model, 'resolve_model_choice', return_value='x') as draw:
            auto_model.resolve_auto_model(gen)
        return draw.call_args.kwargs['spec']

    def test_auto_draws_among_singers_when_the_voice_is_wanted(self):
        self.assertEqual(['huggingface:org/Singer'], self._drawn_spec('song', 'la mer')['candidates'])
        self.assertEqual(['huggingface:org/Singer'], self._drawn_spec('auto', SONG)['candidates'])

    def test_without_a_voice_the_draw_is_not_narrowed(self):
        self.assertNotIn('candidates', self._drawn_spec('auto', 'la mer'))
        self.assertNotIn('candidates', self._drawn_spec('instrumental', SONG))


class OnlyAskedLyricsAreWrittenTest(SimpleTestCase):

    def test_the_lyrics_skill_exists_and_is_the_composer_s(self):
        from wama.common.utils.prompt_skills import resolve_skill
        self.assertEqual('composer-lyrics', resolve_skill(app='composer', domain='lyrics',
                                                          kind=None)[0])

    def _write(self, llm_out, app='composer'):
        from wama.common.utils.app_metadata import write_lyrics_for
        with mock.patch('wama.common.utils.prompt_enrichment.enrich_generative',
                        return_value=llm_out):
            return write_lyrics_for(app, 'prompt', 'une chanson sur la mer', language='fr')

    def test_the_tagged_lyrics_are_kept_and_a_caption_dropped(self):
        self.assertEqual('[Verse]\nla mer revient', self._write('Titre\n[Verse]\nla mer revient'))

    def test_an_answer_without_a_tag_is_not_lyrics(self):
        self.assertEqual('', self._write('la mer revient sans balise'))

    def test_a_target_without_lyrics_never_gets_any(self):
        self.assertEqual('', self._write('[Verse]\nx', app='imager'))


class TheSettingTravelsThroughTheRoutesTest(TestCase):

    def setUp(self):
        user = get_user_model().objects.create_user('voice_me', password='x')
        user.groups.add(*[Group.objects.get_or_create(name=n)[0]
                          for n in ('user', 'role:communication')])
        self.client.force_login(user)

    def test_creation_keeps_the_chosen_voice(self):
        from wama.composer.models import ComposerGeneration
        response = self.client.post(reverse('composer:generate'),
                                    {'prompt': 'la mer', 'model': 'composer:musicgen-small',
                                     'vocals': 'song'})
        self.assertEqual(200, response.status_code, response.content[:200])
        self.assertEqual('song', ComposerGeneration.objects.get(id=response.json()['id']).vocals)

    def test_the_item_settings_keep_it_and_skip_an_unknown_one(self):
        from wama.composer.models import ComposerGeneration
        gen = ComposerGeneration.objects.create(user=get_user_model().objects.get(
            username='voice_me'), prompt='la mer', model='composer:musicgen-small')
        url = reverse('composer:update_settings', args=[gen.id])
        self.assertEqual(200, self.client.post(url, {'vocals': 'instrumental'}).status_code)
        gen.refresh_from_db()
        self.assertEqual('instrumental', gen.vocals)
        self.assertEqual(200, self.client.post(url, {'vocals': 'karaoke'}).status_code)
        gen.refresh_from_db()
        self.assertEqual('instrumental', gen.vocals)

    def test_a_creation_without_duration_takes_the_field_s_default_not_ten_seconds(self):
        # `d4a30c43` moved the default to 3:30 and left two fallbacks of 10 s in the view.
        from wama.composer.models import ComposerGeneration
        with mock.patch('wama.common.utils.user_settings.get_user_app_settings',
                        side_effect=lambda user, app, defaults: dict(defaults)):
            response = self.client.post(reverse('composer:generate'),
                                        {'prompt': 'la mer', 'model': 'composer:minimax-music3'})
        self.assertEqual(200, response.status_code, response.content[:200])
        self.assertEqual(210.0, ComposerGeneration.objects.get(id=response.json()['id']).duration)

    def test_the_card_s_lyrics_are_edited_and_can_be_erased(self):
        from wama.composer.models import ComposerGeneration
        gen = ComposerGeneration.objects.create(user=get_user_model().objects.get(
            username='voice_me'), prompt='la mer', model='composer:musicgen-small',
            lyrics='[Verse]\nla mer')
        url = reverse('composer:update_settings', args=[gen.id])
        self.client.post(url, {'lyrics': '[Verse]\nla mer revient'})
        gen.refresh_from_db()
        self.assertEqual('[Verse]\nla mer revient', gen.lyrics)
        self.client.post(url, {'vocals': 'song'})
        gen.refresh_from_db()
        self.assertEqual('[Verse]\nla mer revient', gen.lyrics, 'not posted: untouched')
        self.client.post(url, {'lyrics': ''})
        gen.refresh_from_db()
        self.assertEqual('', gen.lyrics)
