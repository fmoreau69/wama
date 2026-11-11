"""La recherche CIBLÉE rend le dépôt qu'on a DÉSIGNÉ (2026-09-29).

LE DÉFAUT MESURÉ. Pour installer Supra2-IMG, trois recherches collées depuis la barre d'adresse
(`https://huggingface.co/SupraLabs/Supra2-IMG`) ont rendu 0 résultat : HF cherchait la chaîne
entière. Puis « Supra2-IMG » a écarté l'OFFICIEL — 0,4 Go, sous le plancher de 1 Go du
texte→image, pris pour une LoRA — et n'a laissé que deux reconditionnements tiers, dont l'un a été
installé à sa place.

CE QUE CES GARDES TIENNENT :
  1. une URL de page HF, avec ou sans schéma ni sous-chemin, désigne son dépôt ;
  2. le dépôt désigné passe le plancher de poids ; un dépôt voisin de la même recherche, non ;
  3. le dépôt désigné entre même quand la recherche plein texte ne le rend pas.
Aucun réseau : `HfApi` est simulé.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from wama.model_manager.services import prospector


def _repo(repo_id, downloads=0):
    return SimpleNamespace(id=repo_id, pipeline_tag='text-to-image', downloads=downloads, likes=0,
                           card_data=None, tags=['text-to-image'])


class NamedRepoTest(TestCase):

    def test_a_page_url_or_an_id_names_its_repo(self):
        for q in ('https://huggingface.co/SupraLabs/Supra2-IMG',
                  'huggingface.co/SupraLabs/Supra2-IMG/tree/main',
                  'SupraLabs/Supra2-IMG'):
            self.assertEqual('SupraLabs/Supra2-IMG', prospector.named_repo(q), q)
        self.assertIsNone(prospector.named_repo('kokoro onnx'))
        self.assertIsNone(prospector.named_repo('Supra2-IMG'))


class DesignatedRepoFloorTest(TestCase):

    def _search(self, query, listed, info=None):
        api = mock.Mock()
        api.list_models.return_value = listed
        api.model_info.return_value = info
        written = []
        with mock.patch('huggingface_hub.HfApi', return_value=api), \
             mock.patch.object(prospector, '_repo_weight_gb', return_value=0.4), \
             mock.patch.object(prospector, 'analyze_license', return_value=None), \
             mock.patch('wama.model_manager.services.prospect_ollama.write_candidate',
                        side_effect=lambda key, **kw: written.append(key) or True):
            res = prospector.seed_hf_search(query)
        return res, written, api

    def test_the_named_repo_passes_the_weight_floor_and_its_neighbours_do_not(self):
        res, written, _ = self._search('Supra2-IMG', [_repo('SupraLabs/Supra2-IMG', 689),
                                                      _repo('someone/Supra2-IMG-LoRA', 5)])
        self.assertEqual(['proposed:hf:SupraLabs/Supra2-IMG'], written)
        self.assertEqual(1, res['skipped'])

    def test_a_pasted_url_searches_the_repo_and_puts_it_first(self):
        res, written, api = self._search('https://huggingface.co/SupraLabs/Supra2-IMG', [],
                                         info=_repo('SupraLabs/Supra2-IMG', 689))
        self.assertEqual('SupraLabs/Supra2-IMG', api.list_models.call_args.kwargs['search'])
        api.model_info.assert_called_once_with('SupraLabs/Supra2-IMG')
        self.assertEqual(['proposed:hf:SupraLabs/Supra2-IMG'], written)

    def test_an_unnamed_search_keeps_the_floor(self):
        """Contre-épreuve : un listing SUBI garde sa garde anti-LoRA."""
        res, written, _ = self._search('supra image', [_repo('SupraLabs/Supra2-IMG', 689)])
        self.assertEqual([], written)
        self.assertEqual(1, res['skipped'])


def _vlm(repo_id, tags):
    return SimpleNamespace(id=repo_id, pipeline_tag='image-text-to-text', downloads=10, likes=0,
                           card_data=None, tags=['image-text-to-text', *tags])


class DesignatedRepoOutsideTheSweepTest(TestCase):
    """2026-10-11 : « lightonai/lightonocr-3-1b » rendait 0 résultat — un VLM (`image-text-to-text`,
    hors balayage) qui tague `ocr`. Le dépôt NOMMÉ est jugé sur la tâche que sa carte déclare."""

    _search = DesignatedRepoFloorTest._search

    def test_a_named_vlm_that_tags_ocr_is_proposed_as_ocr(self):
        repo = _vlm('lightonai/lightonocr-3-1b', ['ocr'])
        res, written, _ = self._search('lightonai/lightonocr-3-1b', [repo], info=repo)
        self.assertEqual(['proposed:hf:lightonai/lightonocr-3-1b'], written)
        self.assertEqual(0, res['skipped'])

    def test_a_named_vlm_with_no_task_we_install_stays_out(self):
        """Contre-épreuve : un VLM qui ne dit que décrire n'invente pas de catégorie."""
        repo = _vlm('someone/captioner', [])
        res, written, _ = self._search('someone/captioner', [repo], info=repo)
        self.assertEqual([], written)
        self.assertEqual(1, res['skipped'])

    def test_an_uninstalled_repo_can_be_proposed_again(self):
        """2026-10-11 : la ligne d'un modèle désinstallé reste (son historique) ; elle ne doit plus
        compter comme « déjà chez nous ». Contre-épreuve : une ligne installée, si."""
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='ollama:hf.co/x/LightOnOCR-3-4B-GGUF:Q6_K', name='q6',
                               model_type='ocr', source='ollama', is_downloaded=False,
                               platform_ref='huggingface:lightonai/LightOnOCR-3-4B',
                               extra_info={'uninstalled_at': '2026-10-11T01:41:46'})
        repo = _vlm('lightonai/LightOnOCR-3-4B', ['ocr'])
        res, written, _ = self._search('lightonai/LightOnOCR-3-4B', [repo], info=repo)
        self.assertEqual(['proposed:hf:lightonai/LightOnOCR-3-4B'], written)
        AIModel.objects.filter(platform_ref='huggingface:lightonai/LightOnOCR-3-4B').update(is_downloaded=True)
        res, written, _ = self._search('lightonai/LightOnOCR-3-4B', [repo], info=repo)
        self.assertEqual([], written)
        self.assertEqual(1, res['already'])

    def test_an_unnamed_search_still_ignores_the_vlm_tag(self):
        """Contre-épreuve : un listing SUBI ne balaie toujours pas `image-text-to-text`."""
        res, written, _ = self._search('lightonocr', [_vlm('lightonai/lightonocr-3-1b', ['ocr'])])
        self.assertEqual([], written)
        self.assertEqual(1, res['skipped'])


class TheSearchReadsTheCardTagsTest(TestCase):
    """2026-11-11 : `ACE-Step/acestep-v15-sft`, taguée `music` et `text2music` sur le Hub, s'est
    installée en `text-to-audio` — les bruitages du Composer. La règle qui départage existe
    (`hf_task_to_wama`), mais la recherche ne demandait pas les TAGS (`expand` ne rend que ce qu'il
    nomme) : la règle lisait un sac vide."""

    def test_the_search_asks_the_hub_for_the_tags_and_a_music_repo_is_music(self):
        repo = SimpleNamespace(id='org/music-model', pipeline_tag='text-to-audio', downloads=5,
                               likes=0, card_data=None, tags=['audio', 'music', 'text2music'])
        api = mock.Mock()
        api.list_models.return_value = [repo]
        written = {}
        with mock.patch('huggingface_hub.HfApi', return_value=api), \
             mock.patch.object(prospector, '_repo_weight_gb', return_value=5.0), \
             mock.patch.object(prospector, 'analyze_license', return_value=None), \
             mock.patch('wama.model_manager.services.prospect_ollama.write_candidate',
                        side_effect=lambda key, **kw: written.update({key: kw}) or True):
            prospector.seed_hf_search('music model')
        self.assertIn('tags', api.list_models.call_args.kwargs['expand'])
        self.assertEqual('text-to-music',
                         written['proposed:hf:org/music-model']['capabilities']['task'])


def _carded(repo_id, card, downloads=0):
    return SimpleNamespace(id=repo_id, pipeline_tag='text-to-image', downloads=downloads, likes=0,
                           card_data=card, tags=['text-to-image'])


class ARepackClimbsToItsOriginalTest(TestCase):
    """2026-11-10 (Fabien, ACE-Step) : la recherche « ACE-Step » rendait `Comfy-Org/ACE-Step-1.5`
    (58,8 Go) et des GGUF d'un publieur, jamais l'officiel de l'auteur. Un reconditionnement
    remonte à l'ORIGINAL que sa carte déclare ; un second reconditionnement du même original ne
    prend pas de place (il est l'une de ses options d'installation)."""

    ORIGINAL = 'ACE-Step/Ace-Step1.5'

    def _search(self, query, listed):
        api = mock.Mock()
        api.list_models.return_value = listed
        api.model_info.side_effect = lambda repo, **kw: _carded(repo, None, 90000)
        written = []
        with mock.patch('huggingface_hub.HfApi', return_value=api), \
             mock.patch.object(prospector, '_repo_weight_gb', return_value=9.0), \
             mock.patch.object(prospector, 'analyze_license', return_value=None), \
             mock.patch('wama.model_manager.services.prospect_ollama.write_candidate',
                        side_effect=lambda key, **kw: written.append(key) or True):
            res = prospector.seed_hf_search(query)
        return res, written

    def test_the_repacks_give_the_original_once(self):
        res, written = self._search('ACE-Step', [
            _carded('Comfy-Org/ACE-Step-1.5', {'base_model': self.ORIGINAL}, 500000),
            _carded('Serveurperso/ACE-Step-1.5-GGUF',
                    {'base_model': [self.ORIGINAL], 'base_model_relation': 'quantized'}, 9000),
            _carded('someone/other-model', None, 10)])
        self.assertEqual([f'proposed:hf:{self.ORIGINAL}', 'proposed:hf:someone/other-model'], written)
        self.assertEqual(1, res['grouped'])
        self.assertEqual({'Comfy-Org/ACE-Step-1.5': self.ORIGINAL}, res['climbed'])

    def test_an_installed_original_makes_its_repack_already_ours(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key=f'huggingface:{self.ORIGINAL}', name='ace', model_type='music',
                               source='huggingface', is_downloaded=True,
                               platform_ref=f'huggingface:{self.ORIGINAL}')
        res, written = self._search('ACE-Step', [
            _carded('Comfy-Org/ACE-Step-1.5', {'base_model': self.ORIGINAL})])
        self.assertEqual([], written)
        self.assertEqual(1, res['already'])

    def test_a_finetune_or_a_renamed_derivative_is_its_own_model(self):
        """Contre-épreuve : un affinage déclare aussi `base_model` — c'est un autre modèle."""
        self.assertIsNone(prospector.repack_original(
            'someone/ACE-Step-1.5-anime', {'base_model': self.ORIGINAL, 'base_model_relation': 'finetune'}))
        self.assertIsNone(prospector.repack_original(
            'someone/music-gen', {'base_model': self.ORIGINAL}))
        self.assertIsNone(prospector.repack_original(
            'ACE-Step/acestep-v15-sft', {'base_model': self.ORIGINAL}), "même auteur : pas un repack")
        # La relation `quantized` seule ne suffit pas : le Hub la pose parfois sur un affinage (la
        # règle de `provenance.quantized_base_identity`) — le NOM complet de l'original, si.
        self.assertIsNone(prospector.repack_original(
            'someone/gguf-of-it', {'base_model': self.ORIGINAL, 'base_model_relation': 'quantized'}))
        self.assertEqual(self.ORIGINAL, prospector.repack_original(
            'someone/Ace-Step1.5-GGUF', {'base_model': self.ORIGINAL, 'base_model_relation': 'quantized'}))

    def test_a_designated_repack_is_kept(self):
        """Contre-épreuve : un reconditionnement NOMMÉ est celui qu'on a demandé."""
        repack = _carded('Comfy-Org/ACE-Step-1.5', {'base_model': self.ORIGINAL})
        api = mock.Mock()
        api.list_models.return_value = []
        api.model_info.return_value = repack
        written = []
        with mock.patch('huggingface_hub.HfApi', return_value=api), \
             mock.patch.object(prospector, '_repo_weight_gb', return_value=9.0), \
             mock.patch.object(prospector, 'analyze_license', return_value=None), \
             mock.patch('wama.model_manager.services.prospect_ollama.write_candidate',
                        side_effect=lambda key, **kw: written.append(key) or True):
            prospector.seed_hf_search('Comfy-Org/ACE-Step-1.5')
        self.assertEqual(['proposed:hf:Comfy-Org/ACE-Step-1.5'], written)
