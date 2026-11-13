"""Le geste de VALIDATION d'un manifeste proposé par un rôle (2026-09-29).

POURQUOI. Le cycle sandbox → vérifié → promu est écrit depuis août (`WAMA_MANIFEST_ARCHITECTURE
§4`) et le magasin existe, mais rien ne l'appelait : un rôle déposait son manifeste dans
`wama-dev-ai/outputs/`, et seul un terminal pouvait le projeter.

CE QUE CES GARDES TIENNENT :
  1. proposer ne projette RIEN (le registre est intact tant que personne n'a validé) ;
  2. appliquer COMBLE les vides et n'efface JAMAIS une valeur curée — le défaut mesuré : un
     manifeste brut qui ne dit rien de la licence la remettait à vide ;
  3. une valeur proposée qui contredit une valeur établie est MONTRÉE, pas appliquée ;
  4. rejeter ne défait rien (contre-épreuve : `un_ingest` aurait vidé la licence) ;
  5. une proposition pour un modèle absent du catalogue est refusée sans rien écrire ;
  6. (2026-10-18, `ROADMAP §29` étape 2) privé n'est pas « en attente » : seule une DEMANDE entre
     dans la file ; valider rend l'élément au SYSTÈME, pas à l'admin qui valide ; rejeter la
     demande d'un auteur lui laisse son manifeste ;
  7. (2026-10-20, décision b) un développeur LIT la file, seul un administrateur la décide.
"""
from django.test import TestCase

from wama.common.manifests import proposals
from wama.common.manifests.builtin.model import extract_model
from wama.common.models import Manifest
from wama.model_manager.models import AIModel

KEY = 'huggingface:Org/Img'
COMPOSITION = {'components': [{'role': 'dit', 'pattern': 'dit/model.onnx', 'format': 'onnx'}],
               'runtime': {'engine': 'onnxruntime'}}


def _llm_manifest(**identity):
    """Ce qu'un rôle rend : l'anatomie qu'il a jugée, et RIEN sur la licence ni l'auteur."""
    m = extract_model(KEY)
    m['body']['identity'] = {'model_type': 'diffusion', 'source': 'huggingface', **identity}
    m['body']['composition'] = COMPOSITION
    return m


class ManifestProposalTest(TestCase):

    def setUp(self):
        # L'export au corpus écrit dans `manifests/` du DÉPÔT : simulé (vécu à la 1ʳᵉ exécution,
        # un `huggingface__Org~Img.json` fictif y était apparu).
        # La porte du corpus est coupée par le runner (`MANIFEST_CORPUS_SYNC`) : on la rouvre
        # pour vérifier que « Valider » l'emprunte, l'écriture restant simulée.
        from unittest import mock
        switch = self.settings(MANIFEST_CORPUS_SYNC=True)
        switch.enable()
        self.addCleanup(switch.disable)
        export = mock.patch('django.core.management.call_command')
        self.export = export.start()
        self.addCleanup(export.stop)
        # Valider confronte l'anatomie aux fichiers du dépôt (`confront_model`, 2026-11-06) : le
        # dépôt fictif porte le seul fichier que l'anatomie proposée réclame — aucun réseau.
        inventory = mock.patch('wama.model_manager.services.model_installer.anatomy_inventory',
                               return_value=[('dit/model.onnx', 1)])
        inventory.start()
        self.addCleanup(inventory.stop)
        self.row = AIModel.objects.create(
            model_key=KEY, name='Img', model_type='diffusion', source='huggingface',
            is_downloaded=True, platform_ref='huggingface:Org/Img', license='apache-2.0', author='Org',
            capabilities={'task': 'text-to-image'})

    def test_proposing_projects_nothing(self):
        obj = proposals.propose(_llm_manifest(), origin='outputs/model_x.json')
        self.assertTrue(obj.is_sandbox)
        self.row.refresh_from_db()
        self.assertEqual({}, self.row.composition)
        self.assertEqual([obj], list(proposals.pending('model')))

    def test_applying_fills_the_gaps_and_never_erases_a_curated_value(self):
        obj = proposals.propose(_llm_manifest())
        res = proposals.apply(obj)
        self.assertTrue(res['applied'], res)
        self.row.refresh_from_db()
        self.assertEqual(COMPOSITION, self.row.composition)
        self.assertEqual(('apache-2.0', 'Org'), (self.row.license, self.row.author))
        obj.refresh_from_db()
        self.assertEqual(('public', True, False), (obj.visibility, obj.is_system, obj.is_pending))
        self.export.assert_called_once_with('manifest_export', KEY, kind='model', verbosity=0)

    def test_a_contradiction_is_shown_not_applied(self):
        obj = proposals.propose(_llm_manifest(license='mit'))
        p = proposals.plan(obj)
        self.assertIn({'path': 'body.identity.license', 'current': 'apache-2.0',
                       'proposed': 'mit'}, p['divergences'])
        proposals.apply(obj)
        self.row.refresh_from_db()
        self.assertEqual('apache-2.0', self.row.license)

    def test_rejecting_undoes_nothing(self):
        obj = proposals.propose(_llm_manifest())
        self.assertTrue(proposals.reject(obj))
        self.assertFalse(Manifest.objects.filter(pk=obj.pk).exists())
        self.row.refresh_from_db()
        self.assertEqual('apache-2.0', self.row.license,
                         "un rejet passé par un_ingest aurait vidé la licence")

    def test_a_private_manifest_without_a_request_is_not_pending(self):
        """Écart 1 : la file listait TOUT le privé — le modèle privé d'un utilisateur y tombait."""
        from django.contrib.auth import get_user_model

        from wama.common.manifests.ingest import ingest
        author = get_user_model().objects.create_user('manifest_author', password='x')
        mine = ingest({**_llm_manifest(), 'visibility': 'private'}, user=author)
        self.assertEqual((True, False), (mine.is_sandbox, mine.is_pending))
        self.assertEqual([], list(proposals.pending()))

    def test_validating_gives_the_element_to_the_system_not_to_the_validator(self):
        """Écart 2 : `apply` écrivait `owner = <valideur>` (8 des 13 manifestes du magasin)."""
        from django.contrib.auth import get_user_model
        users = get_user_model().objects
        author = users.create_user('manifest_author', password='x')
        admin = users.create_user('manifest_admin', password='x', is_superuser=True)
        obj = proposals.propose(_llm_manifest(), origin='outputs/model_x.json', user=author)
        self.assertTrue(proposals.apply(obj, user=admin)['applied'])
        obj.refresh_from_db()
        self.assertIsNone(obj.owner)
        self.assertEqual(('proposal', 'outputs/model_x.json', 'manifest_author', 'manifest_admin'),
                         tuple(obj.source.get(k) for k in ('type', 'ref', 'proposed_by',
                                                           'promoted_by')))

    def test_rejecting_an_authors_request_leaves_the_author_the_manifest(self):
        from django.contrib.auth import get_user_model
        author = get_user_model().objects.create_user('manifest_author', password='x')
        obj = proposals.propose(_llm_manifest(), user=author)
        self.assertTrue(proposals.reject(obj))
        obj.refresh_from_db()
        self.assertEqual((author, 'private', False), (obj.owner, obj.visibility, obj.is_pending))
        self.assertFalse(proposals.reject(obj), "une demande close ne se rejette pas deux fois")

    def test_a_proposal_for_an_uncatalogued_model_is_refused_without_writing(self):
        m = _llm_manifest()
        self.row.delete()
        res = proposals.apply(proposals.propose(m))
        self.assertFalse(res['applied'])
        self.assertTrue(res['errors'])

    def test_the_model_manager_gesture_lists_then_applies_or_rejects(self):
        """Le geste HORS terminal : la page montre le plan, Valider applique, Rejeter retire."""
        import json

        from django.contrib.auth import get_user_model
        from django.urls import reverse
        admin = get_user_model().objects.create_user('proposal_admin', password='x',
                                                     is_superuser=True)
        self.client.force_login(admin)
        obj = proposals.propose(_llm_manifest(license='mit'), origin='outputs/model_x.json')
        listing = self.client.get(reverse('model_manager:api_manifest_proposals')).json()
        item = next(p for p in listing['proposals'] if p['id'] == obj.pk)
        self.assertIn('body.composition.components', item['filled'])
        self.assertEqual('body.identity.license', item['divergences'][0]['path'])
        decide = reverse('model_manager:api_manifest_proposal_decide')
        res = self.client.post(decide, json.dumps({'id': obj.pk, 'decision': 'apply'}),
                               content_type='application/json').json()
        self.assertTrue(res['success'], res)
        self.row.refresh_from_db()
        self.assertEqual(COMPOSITION, self.row.composition)
        # Une proposition PROMUE n'est plus en attente : ni listée, ni rejetable.
        self.assertEqual(404, self.client.post(decide, json.dumps({'id': obj.pk,
                                                                    'decision': 'reject'}),
                                               content_type='application/json').status_code)
        page = self.client.get(reverse('model_manager:index'))
        self.assertContains(page, 'id="wamaProposals"')
        # La brique COMMUNE de la file (2026-11-08), filtrée sur les modèles, backends compris :
        # une librairie se valide sur la page des librairies.
        self.assertContains(page, '?kind=model')
        self.assertContains(page, 'data-backends="1"')
        self.assertContains(page, 'common/js/wama-proposals.js')

    def test_the_same_gesture_carries_backend_proposals(self):
        """Marche B2 : la liste porte aussi les backends proposés, et la décision les reconnaît
        par leur fichier — sans jamais sortir d'`outputs/`."""
        import json
        from unittest import mock

        from django.contrib.auth import get_user_model
        from django.urls import reverse
        self.client.force_login(get_user_model().objects.create_user(
            'backend_admin', password='x', is_superuser=True))
        pending = [{'file': 'backend_x.json', 'module': 'x_backend'}]
        with mock.patch('wama.common.services.backend_proposals.pending', return_value=pending):
            listing = self.client.get(reverse('model_manager:api_manifest_proposals')).json()
        self.assertEqual(pending, listing['backends'])
        decide = reverse('model_manager:api_manifest_proposal_decide')
        with mock.patch('wama.common.services.backend_proposals.apply',
                        return_value={'applied': True, 'written': 'w'}) as apply:
            res = self.client.post(decide, json.dumps({'file': 'backend_x.json',
                                                       'decision': 'apply'}),
                                   content_type='application/json').json()
        self.assertTrue(res['success'])
        self.assertEqual('backend_x.json', apply.call_args.args[0])
        r = self.client.post(decide, json.dumps({'file': '../../etc/passwd', 'decision': 'apply'}),
                             content_type='application/json')
        self.assertEqual(404, r.status_code)

    def test_the_gesture_is_refused_to_an_ordinary_account(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        self.client.force_login(get_user_model().objects.create_user('proposal_user',
                                                                     password='x'))
        r = self.client.get(reverse('model_manager:api_manifest_proposals'))
        self.assertNotEqual(200, r.status_code)

    def test_a_developer_reads_the_queue_but_only_an_administrator_decides(self):
        """« Les devs proposent, les admins valident » (Fabien, 2026-10-20, `ROADMAP §29` décision
        b) : le geste était ouvert aux développeurs depuis le 29/09 par la garde commune du model
        manager. Un développeur voit la file, sans boutons ; sa décision est refusée, rien
        n'est écrit, la demande reste en attente ; un administrateur décide."""
        import json

        from django.contrib.auth import get_user_model
        from django.urls import reverse

        from wama.accounts.models import UserProfile
        users = get_user_model().objects
        dev = users.create_user('proposal_dev', password='x')
        UserProfile.objects.update_or_create(user=dev, defaults={'account_tier': 'developpeur'})
        admin = users.create_user('proposal_tier_admin', password='x')
        UserProfile.objects.update_or_create(user=admin, defaults={'account_tier': 'admin'})
        obj = proposals.propose(_llm_manifest(), origin='outputs/model_x.json')
        listing, decide = (reverse('model_manager:api_manifest_proposals'),
                           reverse('model_manager:api_manifest_proposal_decide'))
        body = json.dumps({'id': obj.pk, 'decision': 'apply'})

        self.client.force_login(users.get(pk=dev.pk))
        seen = self.client.get(listing).json()
        self.assertEqual([obj.pk], [p['id'] for p in seen['proposals']])
        self.assertIs(False, seen['can_decide'])
        for decision in ('apply', 'reject'):
            r = self.client.post(decide, json.dumps({'id': obj.pk, 'decision': decision}),
                                 content_type='application/json')
            self.assertEqual(403, r.status_code, decision)
        self.row.refresh_from_db()
        self.assertEqual({}, self.row.composition)
        obj.refresh_from_db()
        self.assertTrue(obj.is_pending)

        self.client.force_login(users.get(pk=admin.pk))
        self.assertIs(True, self.client.get(listing).json()['can_decide'])
        self.assertTrue(self.client.post(decide, body,
                                         content_type='application/json').json()['success'])
        self.row.refresh_from_db()
        self.assertEqual(COMPOSITION, self.row.composition)

    def test_a_setting_declared_as_an_input_makes_the_proposal_invalid(self):
        """Vécu au 1er passage réel (gpt-oss-120b, 29/09) : `inputs_optional: [seed, steps, cfg]`
        passait pour VALIDE. Le plan le dit désormais, et Valider est refusé."""
        m = _llm_manifest()
        m['body']['capabilities'] = {'task': 'text-to-image', 'inputs_optional': ['seed', 'steps']}
        obj = proposals.propose(m)
        self.assertTrue(any('INPUT_TYPES' in e for e in proposals.plan(obj)['errors']))
        self.assertFalse(proposals.apply(obj)['applied'])
        self.row.refresh_from_db()
        self.assertEqual({}, self.row.composition)

    def test_a_language_that_is_no_language_code_makes_the_proposal_invalid(self):
        """Vécu le 2026-11-06 (ACE-Step, rôle `model`) : `languages: ["50+ languages"]` passait
        pour VALIDE. Les trois clés de langue suivent la même règle ; un code ISO 639, une région
        BCP 47 (`zh-cn`) et `*` passent."""
        for key, value in (('languages', ['50+ languages']), ('languages', 'fr'),
                           ('fallback_languages', ['English']), ('timestamp_languages', ['FR'])):
            m = _llm_manifest()
            m['body']['capabilities'] = {'task': 'text-to-music', key: value}
            obj = proposals.propose(m)
            self.assertTrue(any(f'capabilities.{key}' in e for e in proposals.plan(obj)['errors']),
                            (key, value))
            self.assertFalse(proposals.apply(obj)['applied'], (key, value))
        self.row.refresh_from_db()
        self.assertEqual({}, self.row.composition)
        from wama.common.manifests.ingest import validate
        m = _llm_manifest()
        m['body']['capabilities'] = {'languages': ['fr', 'yue', 'zh-cn'], 'fallback_languages': ['*']}
        self.assertFalse([e for e in validate(m) if 'languages' in e])

    def test_the_role_reads_the_verdict_validate_will_give_before_proposing(self):
        """2026-11-07 (ACE-Step par l'assistant) : le rôle ne jugeait que la forme. `judge` rend la
        liste que `plan` montrera, sur la même superposition — anatomie comprise — sans déposer."""
        m = _llm_manifest()
        m['body']['composition'] = {'components': [{'role': 'dit', 'pattern': 'dit/model.onnx'}],
                                    'runtime': {'engine': 'onnxruntime'}}
        from unittest import mock
        with mock.patch('wama.model_manager.services.model_installer.anatomy_inventory',
                        return_value=[('dit/model.onnx', 1), ('text_encoder/model.onnx', 1)]):
            verdict = proposals.judge(m)
            self.assertFalse(proposals.pending('model').exists())
            self.assertTrue(any('text_encoder/model.onnx' in e for e in verdict), verdict)
            self.assertEqual(verdict, proposals.plan(proposals.propose(m))['errors'])
        self.assertEqual([], proposals.judge(_llm_manifest()))

    def test_reading_a_role_output_says_what_validate_says_now(self):
        """2026-11-07 (ACE-Step) : l'assistant a lu `validation_errors: []` dans la sortie du rôle —
        un verdict de son heure — et a fait valider une anatomie que « Valider » refusait. La
        lecture porte le verdict du moment. Contre-épreuve : une sortie sans proposition n'en a pas."""
        import json
        import shutil
        import tempfile
        from pathlib import Path
        from unittest import mock
        from wama.common.services import dev_tools
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        outputs = root / 'wama-dev-ai' / 'outputs'
        outputs.mkdir(parents=True)
        for name in ('model_x.json', 'model_alone.json'):
            (outputs / name).write_text(json.dumps({'validation_errors': []}), encoding='utf-8')
        proposals.propose(_llm_manifest(), origin='wama-dev-ai/outputs/model_x.json')
        with mock.patch.object(dev_tools, 'base_dir', return_value=root), \
             mock.patch.object(dev_tools, 'outputs_dir', return_value=outputs), \
             mock.patch('wama.model_manager.services.model_installer.anatomy_inventory',
                        return_value=[('dit/model.onnx', 1), ('te/model.onnx', 1)]):
            now = dev_tools.dev_read_output(None, 'model_x.json')['validate_now']
            alone = dev_tools.dev_read_output(None, 'model_alone.json')
        self.assertTrue(any('te/model.onnx' in e for e in now['refused']), now)
        self.assertIn('REFUSERAIT', now['note'])
        self.assertNotIn('validate_now', alone)

    def test_the_requires_of_a_vendored_library_survives_its_validation(self):
        """2026-11-13, SAM Audio : le `requires` d'une librairie vendorisée (les dépôts git qu'elle
        importe) ne se ré-extrait de rien — le magasin le perdait au dépôt, l'export après « Valider »
        sortait sans lui. Il traverse désormais proposition, validation et extraction. Contre-épreuve :
        un manifeste sans `requires` reste sans la clé."""
        from wama.common.manifests.builtin.library import extract_library
        key = 'fake_vendor_requiring'
        manifest = {'manifest_kind': 'library', 'key': key, 'name': key, 'schema_version': '1.0',
                    'world': 'transverse', 'visibility': 'public', 'projects': [],
                    'requires': [{'kind': 'library', 'key': 'musetalk'}],
                    'body': {'identity': {'version': 'a' * 12},
                             'install': {'vendor': {'repo': 'owner/fake', 'commit': 'a' * 40,
                                                    'engine': key}}}}
        obj = proposals.propose(manifest, origin='test')
        self.assertEqual(manifest['requires'], obj.as_manifest()['requires'])
        result = proposals.apply(obj)
        self.assertTrue(result['applied'], result)
        self.assertEqual(manifest['requires'], extract_library(key)['requires'])
        self.assertNotIn('requires', proposals.propose(_llm_manifest(), origin='test').as_manifest())

    def test_fill_empty_treats_lists_as_values(self):
        merged, filled, diverged = proposals.fill_empty(
            {'a': [], 'b': ['x'], 'c': {'d': ''}}, {'a': ['y'], 'b': ['z'], 'c': {'d': 'e'}})
        self.assertEqual({'a': ['y'], 'b': ['x'], 'c': {'d': 'e'}}, merged)
        self.assertEqual(['a', 'c.d'], filled)
        self.assertEqual([{'path': 'b', 'current': ['x'], 'proposed': ['z']}], diverged)
