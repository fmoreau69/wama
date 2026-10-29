"""ONE storage rule for the panel preferences: `<domain>.<name>` of a remembered param (2026-10-21).

Measured before: three rules in the fleet — the panel `dom_id` (enhancer, converter, imager), the
param NAME (reader, describer, anonymizer, composer, and every generated twin), rules written in
code (transcriber's two old names, the avatarizer's voice and animation model, the synthesizer's
`preferred_*`). The `dom_id` rule depends on an interface identifier: the converter has one on 1
of its 20 panel settings, so its panel remembered almost nothing, and a generated twin — no
`dom_id` at all — remembered nothing.

Here: what is remembered is DECLARED on the param (`remember`, else its presence in the panel),
the key is derived from the domain, no user loses a setting the old rules kept, and the
alignment command proves, moves and puts back — on test rows only.
"""
import json
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from wama.common.utils.app_modes import APP_MODES, domain_schema, get_domains
from wama.common.utils.param_schema import Param, domain_key, remembered


class RememberedTest(SimpleTestCase):

    def test_a_panel_setting_is_remembered_and_another_is_not(self):
        self.assertTrue(remembered(Param(name='a', type='text', contexts=('item', 'panel'))))
        self.assertFalse(remembered(Param(name='b', type='text', contexts=('item',))))

    def test_the_declaration_wins_both_ways(self):
        self.assertTrue(remembered(Param(name='voice', type='text', contexts=('item',), remember=True)))
        self.assertFalse(remembered({'name': 'model', 'contexts': ['panel'], 'remember': False}))

    def test_a_schema_without_the_attribute_follows_the_panel(self):
        """A twin generated before the attribute existed carries no `remember` key."""
        self.assertTrue(remembered({'name': 'x', 'contexts': ['panel']}))

    def test_the_key_is_the_domain_and_the_name(self):
        key = domain_key('audio')
        self.assertEqual('audio.quality_intent', key({'name': 'quality_intent', 'contexts': ['panel']}))
        self.assertIsNone(key({'name': 'prompt', 'contexts': ['item']}))
        self.assertNotEqual(domain_key('image_video')({'name': 'q', 'contexts': ['panel']}),
                            key({'name': 'q', 'contexts': ['panel']}), 'two domains never share a key')


class NoRememberedSettingIsLostTest(SimpleTestCase):
    """Every setting an app's old rule kept is kept by the common rule — read on every app."""

    def test_the_common_rule_keeps_everything_the_old_rules_kept(self):
        from wama.common.management.commands.align_setting_keys import legacy_rule
        for app in sorted(APP_MODES):
            old, _extra = legacy_rule(app)
            for d in get_domains(app):
                schema = domain_schema(app, d['id'])
                lost = sorted(p['name'] for p in schema if old(p) and not domain_key(d['id'])(p))
                with self.subTest(app=app, domain=d['id']):
                    self.assertEqual([], lost, 'remembered before, forgotten by the common rule')


class AlignmentCommandTest(TestCase):
    """The command on TEST rows: plan and proof, apply, refusal, revert."""

    def setUp(self):
        from wama.common.models import UserAppSetting
        self.U = UserAppSetting
        self.user = get_user_model().objects.create_user('keys_witness', password='x')
        # The two rules the witness apps follow today: the name (anonymizer), the panel dom_id
        # (enhancer, audio domain).
        from wama.enhancer.params import AUDIO_PARAMS_JSON
        from wama.common.utils.param_schema import panel_dom_id
        self.audio_intent = next(panel_dom_id(p) for p in AUDIO_PARAMS_JSON if p['name'] == 'quality_intent')
        UserAppSetting.objects.create(user=self.user, app='anonymizer', name='target_mode', value='description')
        UserAppSetting.objects.create(user=self.user, app='enhancer', name=self.audio_intent, value=80)
        UserAppSetting.objects.create(user=self.user, app='assistant', name='model', value='auto')
        self.dir = Path(tempfile.mkdtemp())

    def _plan(self):
        from wama.common.management.commands import align_setting_keys as cmd
        old = cmd.PLAN_DIR
        cmd.PLAN_DIR = self.dir
        try:
            call_command('align_setting_keys', stdout=open(self.dir / 'out.txt', 'w', encoding='utf-8'))
        finally:
            cmd.PLAN_DIR = old
        path = sorted(self.dir.glob('plan_*.json'))[-1]
        return path, json.loads(path.read_text(encoding='utf-8'))

    def _names(self, app):
        return set(self.U.objects.filter(user=self.user, app=app).values_list('name', flat=True))

    def test_the_plan_moves_each_rule_to_the_common_key_and_proves_it(self):
        _path, plan = self._plan()
        moves = {(m['app'], m['name']): m['new'] for m in plan['moves'] if m['user_id'] == self.user.pk}
        self.assertEqual({('anonymizer', 'target_mode'): ['image_video.target_mode'],
                          ('enhancer', self.audio_intent): ['audio.quality_intent']}, moves)
        mine = [p for p in plan['proof'] if p['user_id'] == self.user.pk]
        self.assertTrue(mine and all(p['identical'] for p in mine), mine)
        self.assertIn('target_mode', next(p for p in mine if p['app'] == 'anonymizer')['set_by_user'])
        self.assertIn(('assistant', 'model'), {(l['app'], l['name']) for l in plan['left']},
                      'a surface without a domain is left as it is')
        self.assertEqual({'target_mode'}, self._names('anonymizer'), 'the dry run writes nothing')

    def test_apply_then_revert_gives_back_the_exact_rows(self):
        path, _plan = self._plan()
        call_command('align_setting_keys', apply=str(path), stdout=open(self.dir / 'a.txt', 'w'))
        self.assertEqual({'image_video.target_mode'}, self._names('anonymizer'))
        self.assertEqual(80, self.U.objects.get(user=self.user, app='enhancer', name='audio.quality_intent').value)
        call_command('align_setting_keys', revert=str(path), stdout=open(self.dir / 'r.txt', 'w'))
        self.assertEqual({'target_mode'}, self._names('anonymizer'))
        self.assertEqual({self.audio_intent}, self._names('enhancer'))

    def test_a_plan_whose_rows_changed_since_is_not_applied(self):
        path, _plan = self._plan()
        self.U.objects.filter(user=self.user, app='anonymizer').update(value='classes')
        with self.assertRaises(CommandError):
            call_command('align_setting_keys', apply=str(path), stdout=open(self.dir / 'a.txt', 'w'))
        self.assertEqual({'target_mode'}, self._names('anonymizer'), 'nothing written: all or none')
