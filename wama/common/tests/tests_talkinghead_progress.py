"""
Le rendu TalkingHead rapporte sa progression HORS de la boucle d'événements de Playwright.

Défaut MESURÉ le 2026-10-03 sur un job réel (#591) : `sync_playwright` tient une boucle
d'événements dans le fil du rendu ; le rappel de progression de l'avatarizer écrit en base ;
Django refuse (`SynchronousOnlyOperation`). Le rendu démarrait puis échouait à la première
tranche d'images — l'avatar 3D n'avait jamais abouti par le worker. Ni les tests du worker
(moteur remplacé par un double) ni le rendu joué à la main (sans rappel) ne portaient le défaut :
il vivait dans leur COMPOSITION.

Ici le navigateur et ffmpeg sont des doubles ; ce qui est réel, c'est la CONDITION : le rendu
tourne sous une boucle d'événements active, et le rappel est gardé par le même décorateur que
l'ORM de Django (`async_unsafe`). Aucune base, aucun GPU.
"""
import asyncio
import base64
import contextlib
import tempfile
import wave
from pathlib import Path
from unittest import mock, skipUnless

from django.core.exceptions import SynchronousOnlyOperation
from django.test import TestCase
from django.utils.asyncio import async_unsafe

try:
    import playwright.sync_api  # noqa: F401
    HAS_PLAYWRIGHT = True
except Exception:                                            # paquet absent de ce venv
    HAS_PLAYWRIGHT = False


class FakePage:
    def on(self, *a, **k): pass
    def route(self, *a, **k): pass
    def goto(self, *a, **k): pass
    def wait_for_function(self, *a, **k): pass

    def evaluate(self, script, arg=None):
        if 'prepare' in script:
            return {'width': 64, 'height': 64, 'renderer': 'fake', 'stepMs': 40.0}
        if 'speak' in script:
            return {'audioOffsetMs': 0}
        return [base64.b64encode(b'jpeg').decode('ascii')] * int(arg)      # step(n)


class FakeBrowser:
    def new_page(self, **k): return FakePage()
    def close(self): pass


class FakeEncoder:
    """Tient lieu de ffmpeg : avale les images, sort en code 0."""
    def __init__(self, *a, **k):
        self.stdin = mock.Mock()
        self.stderr = mock.Mock(read=mock.Mock(return_value=b''))
    def wait(self, timeout=None): return 0
    def poll(self): return 0
    def kill(self): pass


@contextlib.contextmanager
def _fake_playwright():
    yield mock.Mock()


@async_unsafe('refusé sous une boucle d\'événements, comme une requête ORM')
def _guarded(seen, fraction):
    seen.append(fraction)


@skipUnless(HAS_PLAYWRIGHT, 'playwright absent de ce venv')
class ProgressOutsideTheEventLoopTest(TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='talkinghead_progress_'))
        self.avatar = self.dir / 'avatar.glb'
        self.avatar.write_bytes(b'glb')
        self.audio = self.dir / 'voice.wav'
        with wave.open(str(self.audio), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b'\x00\x00' * 32000)                                # 2 s
        self.output = self.dir / 'out.mp4'
        self.output.write_bytes(b'mp4')                                       # ce que ffmpeg écrirait

    def _render_under_a_running_loop(self, progress):
        from wama.common.backends import talkinghead_backend as th

        async def main():
            # `process` est SYNCHRONE : il s'exécute donc pendant que la boucle de ce fil tourne
            # — la situation exacte que crée `sync_playwright` dans le worker.
            return th.TalkingHeadBackend().process(
                avatar_path=str(self.avatar), audio_path=str(self.audio),
                output_path=str(self.output), text='bonjour', progress=progress)

        with mock.patch('playwright.sync_api.sync_playwright', _fake_playwright), \
                mock.patch('wama.common.utils.html_render.launch_chromium',
                           return_value=FakeBrowser()), \
                mock.patch.object(th.subprocess, 'Popen', FakeEncoder), \
                mock.patch('wama.common.services.resource_governor.vram_reservation',
                           lambda *a, **k: contextlib.nullcontext()), \
                mock.patch('wama.common.utils.ffmpeg_utils.get_ffmpeg_exe', return_value='ffmpeg'):
            return asyncio.run(main())

    def test_progress_is_reported_although_the_render_holds_an_event_loop(self):
        seen = []
        self._render_under_a_running_loop(lambda f: _guarded(seen, f))
        self.assertTrue(seen, 'aucune progression rapportée')
        self.assertEqual(1.0, seen[-1])
        self.assertEqual(sorted(seen), seen)                  # dans l'ordre, sans doublon de fin

    def test_the_same_callback_is_refused_in_the_rendering_thread_itself(self):
        """Contre-épreuve : le DÉTECTEUR voit le défaut. Appelé dans le fil qui porte la boucle,
        le rappel est refusé — c'est ce que faisait le rendu avant d'isoler la progression."""
        async def main():
            _guarded([], 0.5)
        with self.assertRaises(SynchronousOnlyOperation):
            asyncio.run(main())

    def test_a_failing_callback_is_not_swallowed(self):
        def broken(fraction):
            raise ValueError('rappel en panne')
        with self.assertRaises(ValueError):
            self._render_under_a_running_loop(broken)
