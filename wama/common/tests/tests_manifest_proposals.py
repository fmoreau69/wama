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
  5. une proposition pour un modèle absent du catalogue est refusée sans rien écrire.
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
        from unittest import mock
        export = mock.patch('django.core.management.call_command')
        self.export = export.start()
        self.addCleanup(export.stop)
        self.row = AIModel.objects.create(
            model_key=KEY, name='Img', model_type='diffusion', source='huggingface',
            is_downloaded=True, hf_id='Org/Img', license='apache-2.0', author='Org',
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
        self.assertEqual(proposals.PROMOTED_VISIBILITY, obj.visibility)
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
        self.assertContains(page, 'id="mmProposals"')

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

    def test_fill_empty_treats_lists_as_values(self):
        merged, filled, diverged = proposals.fill_empty(
            {'a': [], 'b': ['x'], 'c': {'d': ''}}, {'a': ['y'], 'b': ['z'], 'c': {'d': 'e'}})
        self.assertEqual({'a': ['y'], 'b': ['x'], 'c': {'d': 'e'}}, merged)
        self.assertEqual(['a', 'c.d'], filled)
        self.assertEqual([{'path': 'b', 'current': ['x'], 'proposed': ['z']}], diverged)
