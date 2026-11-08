"""The MIDI READING of a score (2026-11-08, Fabien : « pouvoir lire simplement la partition en audio
midi avec la meilleure restitution possible » — SpessaSynth, two sound banks to compare, the online
copy first and the vendored one as a fallback, abcjs online as the other reading).

What each test holds:
  * the banks are declared ONCE (`sound_banks`) and agree with the vendoring script (pinned commit,
    SpessaSynth version) ;
  * their origins are in the registry of sources (Fabien : « on ajoute bien les sources dans le
    registre des sources ») and the page gets an online address only where the server allows it ;
  * the player (V8) proposes one reading per bank + abcjs, and falls back to the LOCAL copy when the
    online one cannot be reached — saying so (`from`).
"""
import json
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase, TestCase

try:
    from py_mini_racer import MiniRacer  # noqa: F401
    HAS_V8 = True
except ImportError:
    HAS_V8 = False

ROOT = Path(settings.BASE_DIR)
SCRIPT = (ROOT / 'tools' / 'update_vendors.sh').read_text(encoding='utf-8')
JS = ROOT / 'wama' / 'common' / 'static' / 'common' / 'js'


class SoundBanksAreDeclaredOnceTest(SimpleTestCase):

    def test_the_declaration_agrees_with_the_vendoring_script(self):
        from wama.common.utils import sound_banks as sb
        pinned = re.search(r'^GENERALUSER_GS_COMMIT=(\w+)', SCRIPT, re.M).group(1)
        self.assertEqual(pinned, sb.GENERALUSER_GS_COMMIT, 'one pin, in the script and the registry')
        version = re.search(r'^SPESSASYNTH_LIB_VER=([\d.]+)', SCRIPT, re.M).group(1)
        for path in (sb.SPESSASYNTH_MODULE, sb.SPESSASYNTH_CORE, sb.SPESSASYNTH_PROCESSOR):
            self.assertIn(f'spessasynth-{version}/', path)
        for bank in sb.SOUND_BANKS:
            self.assertIn(Path(bank.static_path).name, SCRIPT, f'{bank.key} is fetched by the script')

    def test_every_origin_is_in_the_registry_of_sources(self):
        from wama.common import external_sources
        from wama.common.utils import sound_banks as sb
        for key in [b.source for b in sb.SOUND_BANKS] + [sb.ABCJS_ONLINE_BANK[0], 'jsdelivr']:
            self.assertIsNotNone(external_sources.get(key), key)

    def test_the_page_gets_an_online_address_only_where_the_server_allows_it(self):
        from wama.common.external_sources import base_url
        from wama.common.utils.sound_banks import page_banks
        payload = page_banks()
        banks = {b['key']: b for b in payload['banks']}
        self.assertTrue(banks['generaluser_gs']['online'].startswith(base_url('generaluser_gs')))
        self.assertEqual('', banks['musescore_general']['online'], 'no CORS header : local only')
        self.assertTrue(payload['abcjs_online'].startswith(base_url('midi_js_soundfonts')))
        self.assertEqual({'module', 'core', 'processor'}, set(payload['engine']))

    def test_the_score_brick_brings_the_player_and_its_banks_to_the_page(self):
        from wama.common.surfaces import surface
        self.assertIn('common/js/wama-midi-player.js', surface('composer', 'score').scripts())


class ServerRenderTest(TestCase):
    """The audio EXPORT of a score, rendered by FluidSynth (Fabien : « FluidSynth oui ») with the
    same banks : said when the program is missing, the declared bank passed, the route guarded."""

    def test_without_fluidsynth_the_render_says_so(self):
        from unittest import mock
        from wama.common.utils import midi_render
        with mock.patch.object(midi_render, 'fluidsynth_path', return_value=''):
            with self.assertRaisesMessage(midi_render.FluidSynthMissing, 'apt install fluidsynth'):
                midi_render.render_wav(b'MThd', 'generaluser_gs')

    def test_the_declared_bank_and_the_midi_go_to_fluidsynth(self):
        from pathlib import Path as P
        from unittest import mock
        from wama.common.utils import midi_render, sound_banks
        seen = {}

        def run(command, **kwargs):
            seen['command'] = command
            P(command[command.index('-F') + 1]).write_bytes(b'RIFF' + b'\0' * 100)
            return mock.Mock(returncode=0, stderr='', stdout='')
        with mock.patch.object(midi_render, 'fluidsynth_path', return_value='/usr/bin/fluidsynth'), \
                mock.patch.object(sound_banks, 'local_file', return_value=mock.Mock(
                    is_file=lambda: True, __str__=lambda self: '/static/gu.sf2')), \
                mock.patch.object(midi_render.subprocess, 'run', side_effect=run):
            wav = midi_render.render_wav(b'MThd', 'generaluser_gs')
            with self.assertRaisesMessage(ValueError, 'inconnue'):
                midi_render.render_wav(b'MThd', 'no-such-bank')
        self.assertTrue(wav.startswith(b'RIFF'))
        self.assertEqual('/usr/bin/fluidsynth', seen['command'][0])
        self.assertIn('/static/gu.sf2', seen['command'])

    def test_the_route_reads_like_the_card_and_says_a_missing_program(self):
        from unittest import mock
        from django.contrib.auth import get_user_model
        from django.core.files.uploadedfile import SimpleUploadedFile
        from wama.common.utils import midi_render
        from wama.composer.models import ComposerGeneration
        owner = get_user_model().objects.create_user('score-audio-owner', password='x')
        stranger = get_user_model().objects.create_user('score-audio-stranger', password='x')
        gen = ComposerGeneration.objects.create(user=owner, prompt='p', status='SUCCESS')
        url = f'/common/surface/composer/score/{gen.pk}/audio/'
        self.client.force_login(stranger)
        self.assertEqual(404, self.client.post(url, {'bank': 'generaluser_gs'}).status_code,
                         'a card one cannot read is not rendered')
        self.client.force_login(owner)
        self.assertEqual(400, self.client.post(url, {'bank': 'generaluser_gs'}).status_code)
        with mock.patch.object(midi_render, 'fluidsynth_path', return_value=''):
            r = self.client.post(url, {'bank': 'generaluser_gs',
                                       'midi': SimpleUploadedFile('s.mid', b'MThd', 'audio/midi')})
        self.assertEqual(503, r.status_code)
        self.assertIn('fluidsynth', r.json()['error'])


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class MidiPlayerTest(SimpleTestCase):
    CONFIG = json.dumps({
        'banks': [{'key': 'gu', 'label': 'GeneralUser GS', 'local': '/static/gu.sf2',
                   'online': 'https://example.org/gu.sf2'},
                  {'key': 'ms', 'label': 'MuseScore General', 'local': '/static/ms.sf3', 'online': ''},
                  {'key': 'none', 'label': 'Absente', 'local': '', 'online': ''}],
        'abcjs_online': 'https://example.org/FluidR3_GM/'})

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval('var window = globalThis;')
        self.v8.eval((JS / 'wama-midi-player.js').read_text(encoding='utf-8'))

    def test_the_touched_surface_scripts_parse(self):
        """V8 parses without running (`(function(){…})`) : the core, the transport and the score
        brick that carry the MIDI versions."""
        for name in ('surfaces/wama-surface.js', 'surfaces/brick-media-transport.js',
                     'surfaces/brick-score-view.js'):
            with self.subTest(script=name):
                self.v8.eval('(function(){' + (JS / name).read_text(encoding='utf-8') + '\n})')

    def test_the_midi_of_a_score_is_written_once(self):
        """The reading and the score brick's export (MIDI, audio WAV) take the MIDI of a score from
        ONE writing, `WamaMidiPlayer.midiBytes` — the brick had its own copy until the 2026-11-08
        re-check. abcjs gives an array of tracks or bytes: the reader always gets bytes."""
        callers = sorted(str(p.relative_to(JS)) for p in JS.rglob('*.js')
                         if 'getMidiFile(' in p.read_text(encoding='utf-8'))
        self.assertEqual(['wama-midi-player.js'], callers)
        got = self.v8.eval("""
            window.ABCJS = {synth: {getMidiFile: function () { return [[77, 84, 104, 100]]; }}};
            var m = window.WamaMidiPlayer.midiBytes('X:1');
            JSON.stringify([m instanceof Uint8Array, Array.from(m)]);
        """)
        self.assertEqual([True, [77, 84, 104, 100]], json.loads(got))

    def test_one_reading_per_installed_bank_and_abcjs(self):
        labels = self.v8.eval(f'JSON.stringify(window.WamaMidiPlayer.choices({self.CONFIG}))')
        self.assertEqual([('gu', 'MIDI — GeneralUser GS'), ('ms', 'MIDI — MuseScore General'),
                          ('abcjs', 'MIDI — abcjs (en ligne)')],
                         [(c['key'], c['label']) for c in json.loads(labels)])

    def test_the_online_bank_falls_back_to_the_local_copy_and_says_so(self):
        """« garder le local en fallback si l'accès extérieur est coupé » : the online fetch fails,
        the local copy is fetched, and the reading says where its sound comes from."""
        self.v8.eval("""
            var asked = [], result = null;
            window.fetch = function (url) {
                asked.push(url);
                if (url.indexOf('https://') === 0) return Promise.reject(new Error('offline'));
                return Promise.resolve({ok: true, arrayBuffer: function () { return Promise.resolve(new ArrayBuffer(4)); }});
            };
            window.WamaMidiPlayer.fetchBank({label: 'GeneralUser GS', online: 'https://example.org/gu.sf2',
                                             local: '/static/gu.sf2'}).then(function (got) { result = got.from; });
        """)
        self.assertEqual(['https://example.org/gu.sf2', '/static/gu.sf2'], list(self.v8.eval('asked')))
        self.assertEqual('GeneralUser GS (copie locale)', self.v8.eval('result'))

    def test_abcjs_with_notes_it_could_not_load_is_a_failure_never_a_silent_reading(self):
        """Measured in the browser on 2026-11-08, access cut: abcjs's `init` RESOLVES — abcjs 6.4.4
        swallows a failed batch of notes, the result is `{loaded: [], cached: [], error: []}` — and
        the page announced a silent reading « en ligne ». No note obtained, or a note listed in
        `error`, sends the reading to its fallback — here none (no local bank), so it fails and
        says why ; with its notes loaded (or cached by an earlier reading), it is abcjs's."""
        outcome = {}
        for case, result in (('cut', "{loaded: [], cached: [], error: []}"),
                             ('partial', "{loaded: ['p:C4'], cached: [], error: ['p:C9 x']}"),
                             ('reached', "{loaded: ['p:C4'], cached: [], error: []}"),
                             ('cached', "{loaded: [], cached: ['p:C4'], error: []}")):
            self.v8.eval(f"""
                var outcome = null;
                window.document = {{createElement: function () {{ return {{}}; }}}};
                window.ABCJS = {{renderAbc: function () {{ return [{{}}]; }}, synth: {{CreateSynth: function () {{
                    this.init = function () {{ return Promise.resolve({result}); }};
                    this.prime = function () {{ return Promise.resolve(); }};
                    this.download = function () {{ return 'blob:abcjs'; }};
                }}}}}};
                window.WamaMidiPlayer.render('X:1\\nT:{case}\\nK:C\\nC|', 'abcjs',
                        {{banks: [], abcjs_online: 'https://example.org/FluidR3_GM/'}})
                    .then(function (got) {{ outcome = 'ok: ' + got.from; }},
                          function (e) {{ outcome = 'failed: ' + e.message; }});
            """)
            outcome[case] = self.v8.eval('outcome')
        self.assertEqual({'cut': 'failed: abcjs injoignable, et aucune copie locale',
                          'partial': 'failed: abcjs incomplet (1 notes manquantes), et aucune copie locale',
                          'reached': 'ok: abcjs, FluidR3_GM (en ligne)',
                          'cached': 'ok: abcjs, FluidR3_GM (en ligne)'}, outcome)
