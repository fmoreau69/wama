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
