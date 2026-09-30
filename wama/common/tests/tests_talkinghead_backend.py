"""Le moteur `talkinghead` : avatar 3D riggé rendu en vidéo, image par image (2026-09-30).

Ce que ces tests tiennent sans navigateur : la résolution du backend PAR SON MOTEUR, le calage du
son sur l'horloge de l'avatar, les fichiers que la page de rendu demande, les refus précoces, le
lanceur Chromium commun (le chemin GPU ne prend PAS le Chromium complet — mesuré : il reste sur
SwiftShader), et la syntaxe des deux modules JS par V8. Le rendu RÉEL (Chromium + 4090) a été joué
à la main le même jour — 10,7 s de vidéo en 20,6 s, `PROSPECTION_AVATARS_2026-09-30.md`.
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from wama.common.backends import talkinghead_backend as th

SOURCES = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static'
SERVED = Path(settings.BASE_DIR) / 'staticfiles'
MODULES = ('common/js/wama-avatar.js', 'common/js/wama-avatar-render.js')


class EngineResolutionTest(SimpleTestCase):

    def test_the_engine_resolves_to_this_backend(self):
        from wama.common.backends.manager import backend_for_engine
        self.assertIs(th.TalkingHeadBackend, backend_for_engine('talkinghead'))

    def test_the_backend_honours_the_common_contract(self):
        backend = th.TalkingHeadBackend()
        self.assertEqual('talkinghead', backend.ENGINE)
        self.assertTrue(backend.load())
        self.assertTrue(backend.is_loaded)
        backend.unload()
        self.assertFalse(backend.is_loaded)


class AudioAlignmentTest(SimpleTestCase):
    """Image i (instant vidéo i·pas) = avatar à clock0 + (i+1)·pas : le son part un pas plus tôt."""

    def test_the_audio_starts_one_step_before_the_lips_clock(self):
        self.assertEqual(20.0, th.audio_offset_in_video_ms(60.0, 40.0))

    def test_the_offset_is_never_negative(self):
        self.assertEqual(0.0, th.audio_offset_in_video_ms(0.0, 40.0))

    def test_the_frames_cover_the_audio_plus_a_closing_tail(self):
        # 10 s + 20 ms de décalage + 500 ms de fin, à 40 ms l'image → 263,0 → 263
        self.assertEqual(263, th.frame_count(10.0, 20.0, 40.0))
        self.assertEqual(1, th.frame_count(0.0, 0.0, 40.0, tail_ms=0.0), 'jamais zéro image')


class WordTimingsTest(SimpleTestCase):
    """Mots datés d'une transcription (secondes) → timings TalkingHead (ms) — 2026-09-30."""

    def test_dated_words_become_milliseconds(self):
        out = th.word_timings([{'word': ' Bonjour', 'start': 0.12, 'end': 0.5},
                               {'word': ',', 'start': 0.5, 'end': 0.5},
                               {'word': ' à tous', 'start': 0.6, 'end': 1.0}])
        self.assertEqual({'words': ['Bonjour', ',', 'à tous'], 'wtimes': [120, 500, 600],
                          'wdurations': [380, 0, 400]}, out)

    def test_empty_words_are_dropped_and_nothing_gives_none(self):
        self.assertIsNone(th.word_timings([{'word': '  ', 'start': 0, 'end': 1}]))
        self.assertIsNone(th.word_timings(None))

    def test_a_duration_is_never_negative(self):
        self.assertEqual([0], th.word_timings([{'word': 'x', 'start': 2.0, 'end': 1.0}])['wdurations'])


class RenderPageTest(SimpleTestCase):

    def test_every_file_the_page_asks_for_resolves_on_disk(self):
        """Ce que la page charge (importmap commune + modules + lib + visèmes FR) se résout par
        les finders — sinon le rendu se ferait sur une page vide, sans lever."""
        html = render_to_string('common/avatar_render.html', {'width': 64, 'height': 36,
                                                              'background': '#fff'})
        wanted = set(re.findall(r'"(/static/[^"]+\.m?js)"', html))
        wanted |= {'/static/vendors/talkinghead-1.7/lipsync-fr.mjs',
                   '/static/vendors/three-0.180.0/build/three.module.js'}
        self.assertTrue({f'/static/{m}' for m in MODULES} <= wanted, html)
        for url in sorted(wanted):
            with self.subTest(url=url):
                self.assertTrue(th._static_file(url), f'introuvable : {url}')

    def test_a_path_outside_static_is_never_served(self):
        self.assertIsNone(th._static_file('/media/users/1/secret.wav'))

    def test_the_default_video_framing_recentres_the_avatar(self):
        """Mesuré sur deux planches : avec `cameraX = 0` le visage sort décalé à droite."""
        self.assertLess(th.DEFAULT_CAMERA['cameraX'], 0)


class EarlyRefusalTest(SimpleTestCase):
    """Les refus se disent AVANT de lancer un navigateur."""

    def test_no_text_means_no_lips_and_is_refused(self):
        glb = finders.find('vendors/avatars/brunette.glb')
        if not glb:
            self.skipTest('avatar de test absent (gitignoré)')
        with patch('playwright.sync_api.sync_playwright') as launch:
            with self.assertRaises(ValueError):
                th.TalkingHeadBackend().process(avatar_path=glb, audio_path='x.wav',
                                                output_path='o.mp4', text='  ')
        launch.assert_not_called()

    def test_a_missing_avatar_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            th.TalkingHeadBackend().process(avatar_path='/nulle/part.glb', audio_path='x.wav',
                                            output_path='o.mp4', text='Bonjour.')


class ChromiumLauncherTest(SimpleTestCase):
    """`html_render.launch_chromium` — lanceur COMMUN (rendu PDF + rendu d'avatar)."""

    def _launch(self, gpu, wsl_gpu):
        from wama.common.utils import html_render
        playwright = MagicMock()
        with patch.object(html_render, '_wsl_gpu_available', return_value=wsl_gpu), \
                patch.object(html_render, '_find_chromium_executable', return_value='/full/chrome'):
            html_render.launch_chromium(playwright, gpu=gpu)
        return playwright.chromium.launch.call_args.kwargs

    def test_the_gpu_path_leaves_the_binary_to_playwright(self):
        kwargs = self._launch(gpu=True, wsl_gpu=True)
        self.assertNotIn('executable_path', kwargs, 'le Chromium complet reste sur SwiftShader')
        self.assertIn('--use-angle=gl-egl', kwargs['args'])
        self.assertEqual('d3d12', kwargs['env']['GALLIUM_DRIVER'])

    def test_without_the_wsl_driver_the_gpu_request_falls_back_quietly(self):
        kwargs = self._launch(gpu=True, wsl_gpu=False)
        self.assertNotIn('--use-angle=gl-egl', kwargs['args'])
        self.assertNotIn('env', kwargs)

    def test_the_pdf_path_is_unchanged(self):
        """Contre-épreuve : le rendu PDF garde son binaire et son `--disable-gpu`."""
        kwargs = self._launch(gpu=False, wsl_gpu=True)
        self.assertEqual('/full/chrome', kwargs['executable_path'])
        self.assertIn('--disable-gpu', kwargs['args'])


class RenderModulesSyntaxTest(SimpleTestCase):
    """Un `.js` ne casse pas à la compilation, il casse dans le navigateur — V8 fait foi (AGENTS)."""

    def test_both_modules_parse_in_v8(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv')
        ctx = MiniRacer()
        for rel in MODULES:
            with self.subTest(module=rel):
                src = (SOURCES / rel).read_text(encoding='utf-8')
                # V8 n'évalue pas `import`/`export` hors module : on les retire, le reste se parse
                # sans exécuter (le module touche au DOM).
                src = re.sub(r'^import .*?;\s*$', '', src, flags=re.M)
                src = re.sub(r'^export (?=(async |function|const|let))', '', src, flags=re.M)
                ctx.eval('(function(){' + src + '\n})')

    def test_the_served_copies_match_their_sources(self):
        for rel in MODULES:
            with self.subTest(module=rel):
                self.assertEqual((SOURCES / rel).read_text(encoding='utf-8'),
                                 (SERVED / rel).read_text(encoding='utf-8'),
                                 f'staticfiles/{rel} pas resynchronisé')
