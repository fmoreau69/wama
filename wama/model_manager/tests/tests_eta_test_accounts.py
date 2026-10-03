"""
L'ETA apprise ne se nourrit pas des comptes de TEST (`eta_estimator.record_run`, 2026-09-29).

Mesuré : les images témoins des scénarios nocturnes (1×1 ou 8×8 px), traitées pour de vrai sous le
compte de test le 26/09, avaient appris 828 338 s/Mpx à l'anonymizer et 672 705 s/Mpx à l'enhancer.
Une photo réelle de 2 Mpx était annoncée à ~19 jours, et la progression simulée de l'anonymizer,
calée sur cette estimation, n'avançait plus.

Deux gardes jumelles : la règle, et la présence de `user=` à CHAQUE appel du dépôt — sans quoi un
appelant qui oublie l'utilisateur rouvrirait le trou en silence.
"""
import ast
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from wama.common.services.nightly_tests import TEST_USERNAME, is_test_account
from wama.model_manager.models import ModelRuntimeStat
from wama.model_manager.services.eta_estimator import record_run

#: Appelants DISPENSÉS de `user=`, avec leur raison : ils ne traitent pas l'élément d'un compte.
EXEMPT_CALLERS = {
    'wama/model_manager/services/bench.py': 'banc des modèles lancé par un admin, sans élément',
}


class TestAccountsDoNotTeachTest(TestCase):

    def test_a_test_account_run_is_not_learned(self):
        robot = User.objects.create_user(TEST_USERNAME + '_eta', password='x')
        robot.username = TEST_USERNAME            # le nom seul décide
        self.assertTrue(is_test_account(robot))
        record_run('eta-guard:witness', size=0.000064, unit='megapixel', process_seconds=50,
                   user=robot)
        self.assertFalse(ModelRuntimeStat.objects.filter(model_key='eta-guard:witness').exists())

    def test_counter_proof_a_real_account_run_is_learned(self):
        real = User.objects.create_user('eta_real_user', password='x')
        self.assertFalse(is_test_account(real))
        record_run('eta-guard:real', size=2.0, unit='megapixel', process_seconds=4, user=real)
        stat = ModelRuntimeStat.objects.get(model_key='eta-guard:real')
        self.assertAlmostEqual(stat.per_unit_ema_seconds, 2.0)


class EveryCallerPassesTheUserTest(SimpleTestCase):

    def _calls(self):
        base = Path(settings.BASE_DIR)
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (base / root).rglob('*.py'):
                rel = path.relative_to(base).as_posix()
                if '/tests' in rel or rel.split('/')[-1].startswith('tests') or '/vendor/' in rel:
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                if 'record_run(' not in text:
                    continue
                for node in ast.walk(ast.parse(text)):
                    if (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'record_run'):
                        yield rel, node

    def test_each_record_run_call_names_the_owner(self):
        missing, seen = [], 0
        for rel, node in self._calls():
            seen += 1
            if rel in EXEMPT_CALLERS:
                continue
            if not any(k.arg == 'user' for k in node.keywords):
                missing.append(f'{rel}:{node.lineno}')
        # Plancher = la mesure (2026-10-03 : 6). Il baissait de 8 quand synthesizer, avatarizer
        # et anonymizer ont rendu leur appel à celui du squelette commun (`task_skeleton.
        # _record_eta`, qui nomme le propriétaire) : moins d'appels, c'est la centralisation —
        # pas un parcours aveugle. Il ne protège que contre un parcours qui ne trouverait RIEN.
        self.assertGreaterEqual(seen, 6, 'trop peu d’appels trouvés : le parcours est aveugle')
        self.assertEqual(missing, [], 'record_run sans `user=` : un compte de test y apprendrait')

    def test_exemptions_are_still_callers(self):
        callers = {rel for rel, _ in self._calls()}
        for rel in EXEMPT_CALLERS:
            self.assertIn(rel, callers, f'dispense devenue inutile : {rel}')


class ModelKeyTest(SimpleTestCase):
    """`make_key` ne double pas un préfixe déjà présent (2026-09-29 : le synthesizer apprenait
    sous `synthesizer:synthesizer:coqui-xtts`, son `tts_model` portant déjà la clé du catalogue)."""

    def test_a_catalog_key_is_kept_as_is(self):
        from wama.model_manager.services.eta_estimator import make_key
        self.assertEqual(make_key('synthesizer', 'synthesizer:coqui-xtts'), 'synthesizer:coqui-xtts')

    def test_counter_proof_a_bare_id_is_prefixed(self):
        from wama.model_manager.services.eta_estimator import make_key
        self.assertEqual(make_key('transcriber', 'whisper'), 'transcriber:whisper')
        # un id qui CONTIENT la source sans la porter en préfixe reste préfixé
        self.assertEqual(make_key('synthesizer', 'xtts:synthesizer'), 'synthesizer:xtts:synthesizer')

    def test_the_synthesizer_learns_under_its_catalog_key(self):
        from wama.model_manager.services.eta_estimator import make_key
        from wama.synthesizer.models import VoiceSynthesis
        default = VoiceSynthesis._meta.get_field('tts_model').default
        self.assertEqual(make_key('synthesizer', default).count('synthesizer:'), 1)
