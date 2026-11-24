"""Ce qu'un compte peut LIRE de l'arbre d'un autre, et ce qu'un visiteur peut déclencher
(2026-11-06, audit de sécurité — chaque garde a été rouge avant son correctif) :

  - `in_user_home` / `readable_by` jugent le chemin NORMALISÉ : `users/<moi>/../<autre>/…` n'est
    pas chez moi ;
  - les sites qui reçoivent un chemin passent par la désignation commune (`designated_source`) :
    l'extraction de texte de l'avatarizer ne lit plus le fichier d'autrui ;
  - l'arbre du gestionnaire ne déploie pas le dossier d'un autre compte ;
  - le JSON des voix, injecté dans un `<script>`, ne peut pas le fermer ;
  - l'enrichissement de prompt n'appelle pas de LLM pour un visiteur.
"""
import json
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.utils.media_paths import in_user_home, readable_by

User = get_user_model()


class NormalisedPathsTest(TestCase):

    def setUp(self):
        self.me = User.objects.create_user('wama_reads_me')
        self.other = User.objects.create_user('wama_reads_other')

    def test_a_parent_segment_does_not_make_another_tree_mine(self):
        forged = f'users/{self.me.id}/../{self.other.id}/temp/x.txt'
        self.assertFalse(in_user_home(forged, self.me.id))
        self.assertFalse(readable_by(forged, self.me))
        self.assertTrue(in_user_home(f'users/{self.me.id}/temp/./a/../x.txt', self.me.id))

    def test_climbing_above_the_media_root_is_never_mine(self):
        self.assertFalse(in_user_home(f'users/{self.me.id}/../../../etc/passwd', self.me.id))
        self.assertFalse(readable_by('../../etc/passwd', self.me))


class AnotherAccountsFilesTest(TestCase):

    def setUp(self):
        if 'media_tests' not in str(settings.MEDIA_ROOT).replace('\\', '/'):
            self.skipTest('MEDIA_ROOT non redirigé : rien n’est écrit')
        self.me = User.objects.create_user('wama_reads_reader')
        self.victim = User.objects.create_user('wama_reads_victim')
        self.me.groups.add(Group.objects.get_or_create(name='role:communication')[0])
        folder = Path(settings.MEDIA_ROOT) / f'users/{self.victim.id}/temp'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'private_note.txt').write_text('WITNESS-OF-B', encoding='utf-8')
        self.client = Client()
        self.client.force_login(self.me)

    def test_the_avatarizer_does_not_extract_the_text_of_another_account(self):
        reply = self.client.post(reverse('avatarizer:extract_text'),
                                 {'media_path': f'users/{self.victim.id}/temp/private_note.txt'})
        self.assertEqual(reply.status_code, 403)
        self.assertNotIn(b'WITNESS-OF-B', reply.content)

    def test_its_own_file_is_still_extracted(self):
        mine = Path(settings.MEDIA_ROOT) / f'users/{self.me.id}/temp'
        mine.mkdir(parents=True, exist_ok=True)
        (mine / 'note.txt').write_text('MY-TEXT', encoding='utf-8')
        reply = self.client.post(reverse('avatarizer:extract_text'),
                                 {'media_path': f'users/{self.me.id}/temp/note.txt'})
        self.assertEqual(reply.status_code, 200)
        self.assertIn(b'MY-TEXT', reply.content)

    def test_the_file_tree_does_not_unfold_another_accounts_folder(self):
        reply = self.client.get(reverse('filemanager:api_children'),
                                {'path': f'users/{self.victim.id}/temp'})
        self.assertEqual(reply.status_code, 403)
        self.assertNotIn(b'private_note.txt', reply.content)
        listing = self.client.get(reverse('filemanager:api_children'), {'path': 'users'})
        self.assertEqual(listing.status_code, 403)

    def test_its_own_folder_still_unfolds(self):
        mine = Path(settings.MEDIA_ROOT) / f'users/{self.me.id}/temp'
        mine.mkdir(parents=True, exist_ok=True)
        (mine / 'visible.txt').write_text('x', encoding='utf-8')
        reply = self.client.get(reverse('filemanager:api_children'),
                                {'path': f'users/{self.me.id}/temp'})
        self.assertEqual(reply.status_code, 200)
        self.assertIn(b'visible.txt', reply.content)


class ScriptInjectionTest(TestCase):

    def test_a_voice_name_cannot_close_the_script_block(self):
        # L'échappement vit au gabarit depuis le 2026-11-07 (`|script_json`) : c'est la page qui
        # se juge, et les deux gabarits qui posent ces groupes passent par la brique.
        from django.template import Context, Template
        from wama.common.utils import voice_options
        hostile = [{'label': 'x', 'options': [{'value': 'v', 'label': '</script><script>x()</script>'}]}]
        with mock.patch.object(voice_options, 'get_voice_groups', return_value=hostile):
            groups = voice_options.voice_groups_json(None)
        rendered = Template('{% load wama_json %}{{ g|script_json }}').render(Context({'g': groups}))
        self.assertNotIn('</script>', rendered)
        self.assertEqual(json.loads(rendered), hostile, 'le JSON reste lisible tel quel')
        for page in ('synthesizer/templates/synthesizer/index.html',
                     'avatarizer/templates/avatarizer/index.html'):
            text = (Path(settings.BASE_DIR) / 'wama' / page).read_text(encoding='utf-8')
            self.assertIn('voice_groups_json|default:"[]"|script_json', text)

    def test_the_two_patched_scripts_still_parse(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent')
        for rel in ('media_library/js/media-library.js', 'studio/js/wama-studio.js'):
            src = (Path(settings.BASE_DIR) / 'staticfiles' / rel).read_text(encoding='utf-8')
            MiniRacer().eval('(function(){' + src + '\n})')       # parse, n'exécute pas

    def test_the_license_and_the_pipeline_label_are_escaped_where_they_are_drawn(self):
        base = Path(settings.BASE_DIR) / 'wama'
        library = (base / 'media_library/static/media_library/js/media-library.js').read_text('utf-8')
        studio = (base / 'studio/static/studio/js/wama-studio.js').read_text('utf-8')
        self.assertIn('${esc(asset.license)}', library)
        self.assertNotIn('${asset.license}', library)
        self.assertIn("esc(a.label) + '</span>'", studio)
        self.assertNotIn("+ a.label + '</span>'", studio)


def _concept_targets():
    """(app, field, element model) of every DECLARED concept prompt whose element keeps what was
    understood (`<field>_processed`) — read from `PROMPT_TARGETS`, no app named."""
    from wama.common.utils.app_metadata import PROCESSED_SUFFIX, PROMPT_TARGETS
    from wama.common.utils.preview_registry import PreviewRegistry
    out = []
    for app, targets in PROMPT_TARGETS.items():
        model = PreviewRegistry.get_model(app)
        for tgt in targets:
            field = tgt.get('field')
            if tgt.get('kind') == 'concept' and model is not None \
                    and hasattr(model, f'{field}{PROCESSED_SUFFIX}'):
                out.append((app, field, model))
    return out


class UnderstoodPromptTest(TestCase):
    """2026-11-24 (decision of Fabien : « what the system understood must be shown to the user ») —
    a CONCEPT prompt is understood, not enriched : the ✨ button runs the launch pipeline for it,
    what a launch understood is kept beside the typed text, and typing again drops it."""

    def test_the_fleet_is_measured(self):
        self.assertTrue(_concept_targets(), 'no declared concept prompt keeps what it understood')

    def test_the_button_understands_a_concept_prompt_by_its_declaration(self):
        from wama.common.utils import app_metadata
        for app, field, _model in _concept_targets():
            with self.subTest(app=app), \
                    mock.patch.object(app_metadata, 'process_prompt_for',
                                      return_value={'prompt': 'human face, logo'}) as pipeline, \
                    mock.patch('wama.common.utils.prompt_enrichment.enrich_on_demand') as enrich:
                self.assertEqual('human face, logo',
                                 app_metadata.enrich_prompt_value(app, field, 'les visages'))
                enrich.assert_not_called()
                self.assertIs(True, pipeline.call_args.kwargs['enrich'])
            with mock.patch.object(app_metadata, 'process_prompt_for',
                                   return_value={'prompt': 'les visages'}), \
                    self.assertRaises(RuntimeError):
                app_metadata.enrich_prompt_value(app, field, 'les visages')

    def test_what_a_launch_understood_is_kept_and_typing_again_drops_it(self):
        from django.contrib.auth.models import User as Account
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.app_metadata import apply_prompt_state, keep_processed_prompt
        owner = Account.objects.create_user('wama_understood')
        for app, field, model in _concept_targets():
            with self.subTest(app=app):
                item = _instance(model, owner)
                setattr(item, field, 'les visages')
                self.assertFalse(keep_processed_prompt(item, field, {'prompt': 'les visages',
                                                                     'original': 'les visages'}),
                                 'nothing changed : nothing kept')
                self.assertTrue(keep_processed_prompt(item, field, {
                    'prompt': 'human face', 'original': 'les visages', 'translated': True}))
                item.refresh_from_db()
                self.assertEqual('human face', getattr(item, f'{field}_processed'))
                self.assertTrue(item.prompt_trace[field]['translated'])
                touched = apply_prompt_state(item, field, 'les visages et les logos', 'user')
                self.assertEqual('', getattr(item, f'{field}_processed'),
                                 'the typed text changed : what was understood of the old one goes')
                self.assertIn(f'{field}_processed', touched)


class TheModalsPostTheDisplayedFaceTest(SimpleTestCase):
    """The imager's modal posted the ORIGINAL under the `processed` state, which
    `apply_prompt_state` writes into `<field>_processed` : saving an enriched card replaced the
    enriched text by the typed one (2026-08-05 → 2026-10-04). Nothing says so at run time. Since
    2026-11-24 the common modal cycle posts every two-state prompt — its DISPLAYED text with the
    other fields, its state read at the controller — and no app does it by hand any more (the
    imager's and the composer's copies were removed ; moved from `composer/tests_prompt_harness`)."""

    COMMON = 'common/js/wama-params.js'

    def test_the_common_cycle_posts_the_state_of_every_two_state_prompt(self):
        import re
        root = Path(settings.BASE_DIR)
        for served in (root / 'wama' / 'common' / 'static' / self.COMMON,
                       root / 'staticfiles' / self.COMMON):
            with self.subTest(file=served.name, served='staticfiles' in served.parts):
                src = served.read_text(encoding='utf-8')
                self.assertIn("textarea[data-prompt-state][name]", src)
                self.assertTrue(re.search(r"fd\.set\(t\.name \+ '_state', ctrl \? ctrl\.snapshot\(\)"
                                          r"\.state", src), 'the state is read at the controller')

    def test_no_app_posts_a_prompt_state_by_hand(self):
        import re
        hand = re.compile(r"fd\.(?:set|append)\('\w*_state'|fd\.(?:set|append)\('\w+',[^;]*\.original\b")
        found = []
        for script in (Path(settings.BASE_DIR) / 'wama').glob('*/static/**/*.js'):
            if 'common' in script.relative_to(Path(settings.BASE_DIR) / 'wama').parts[:1]:
                continue
            if hand.search(script.read_text(encoding='utf-8', errors='replace')):
                found.append(str(script.relative_to(settings.BASE_DIR)))
        self.assertEqual([], found, 'a modal posts its prompt state by hand : the common cycle does')


class VisitorTriggersNoLlmTest(TestCase):

    def test_prompt_enrichment_rejects_a_visitor_before_any_model_call(self):
        with mock.patch('wama.common.utils.app_metadata.enrich_prompt_value') as engine:
            reply = Client().post(reverse('common:enrich_prompt'),
                                  data=json.dumps({'prompt': 'a cat', 'app': 'imager'}),
                                  content_type='application/json')
        self.assertEqual(reply.status_code, 401)
        engine.assert_not_called()

    def test_an_account_still_enriches(self):
        user = User.objects.create_user('wama_reads_enrich')
        client = Client()
        client.force_login(user)
        with mock.patch('wama.common.utils.app_metadata.enrich_prompt_value',
                        return_value='ENRICHED'):
            reply = client.post(reverse('common:enrich_prompt'),
                                data=json.dumps({'prompt': 'a cat', 'app': 'imager'}),
                                content_type='application/json')
        self.assertEqual(reply.json().get('enhanced'), 'ENRICHED')
