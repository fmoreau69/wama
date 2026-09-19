"""L'anatomie DÉRIVÉE d'un pipeline diffusers — un test par cas MESURÉ sur le parc.

Ces tests ne valident pas une idée de ce que `model_index.json` contient : chaque cas vient d'un
dépôt réellement installé, relevé le 2026-09-20 (demande de Fabien : « par vérification
approfondie pour chaque cas de figure »). Ils tournent HORS RÉSEAU, sur des arborescences
fabriquées — la mesure sur le parc vit dans les commentaires de `model_anatomy`, pas ici.
"""
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from wama.common.utils.model_anatomy import (components_from_snapshot, model_composition,
                                             pattern_for_files)


def _snapshot(base: Path, index: dict, files: dict) -> Path:
    """Fabrique `models--org--nom/snapshots/<sha>/` avec son `model_index.json` et ses poids."""
    rev = base / 'models--org--nom' / 'snapshots' / 'abc123'
    rev.mkdir(parents=True)
    (rev / 'model_index.json').write_text(json.dumps(index), encoding='utf-8')
    for role, noms in files.items():
        (rev / role).mkdir(parents=True, exist_ok=True)
        for nom in noms:
            (rev / role / nom).write_bytes(b'x')
    return base / 'models--org--nom'


class DerivedAnatomyTest(SimpleTestCase):

    def test_a_role_without_weights_is_not_a_component(self):
        """`scheduler` et `tokenizer` sont DÉCLARÉS par tous les `model_index.json` du parc et
        n'ont aucun poids. On ne les écarte pas par une liste de noms à tenir à jour — c'est la
        présence de poids qui tranche, donc un rôle inconnu de demain sera traité juste."""
        index = {'_class_name': 'WanDMDPipeline',
                 'scheduler': ['diffusers', 'UniPCMultistepScheduler'],
                 'tokenizer': ['transformers', 'T5TokenizerFast'],
                 'vae': ['diffusers', 'AutoencoderKLWan']}
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot(Path(tmp), index,
                             {'scheduler': ['scheduler_config.json'],
                              'tokenizer': ['spiece.model', 'tokenizer_config.json'],
                              'vae': ['diffusion_pytorch_model.safetensors']})
            parts = components_from_snapshot(root)
        self.assertEqual(parts, [{'role': 'vae',
                                  'pattern': 'vae/diffusion_pytorch_model.safetensors'}])

    def test_a_setting_or_an_empty_slot_is_not_a_component(self):
        """Cas FastWan, mesuré : son `model_index.json` porte `boundary_ratio: None`,
        `expand_timesteps: True` (des RÉGLAGES) et `transformer_2: [None, None]` — une place
        VIDE. Seule une paire `[librairie, classe]` décrit un composant."""
        index = {'_class_name': 'WanDMDPipeline', 'boundary_ratio': None,
                 'expand_timesteps': True, 'transformer_2': [None, None],
                 'transformer': ['diffusers', 'WanTransformer3DModel']}
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot(Path(tmp), index,
                             {'transformer': ['diffusion_pytorch_model.safetensors'],
                              'transformer_2': ['diffusion_pytorch_model.safetensors']})
            parts = components_from_snapshot(root)
        self.assertEqual([c['role'] for c in parts], ['transformer'],
                         "une place vide `[None, None]` a été prise pour un composant")

    def test_the_installed_variant_is_what_the_pattern_names(self):
        """Cas SDXL, mesuré : seules les variantes `.fp16` sont installées, et c'est elles que le
        backend demande (`variant="fp16"` dès que le dtype est float16). Le motif dérivé doit donc
        nommer le fichier PRÉSENT — une déclaration écrite depuis la carte HF désignait la pleine
        précision, absente du disque, et pesait 9,56 Go là où la machine charge 4,78."""
        index = {'_class_name': 'StableDiffusionXLPipeline',
                 'unet': ['diffusers', 'UNet2DConditionModel']}
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot(Path(tmp), index,
                             {'unet': ['diffusion_pytorch_model.fp16.safetensors']})
            parts = components_from_snapshot(root)
        self.assertEqual(parts, [{'role': 'unet',
                                  'pattern': 'unet/diffusion_pytorch_model.fp16.safetensors'}])

    def test_a_shard_set_becomes_one_pattern_not_n_names(self):
        """Un jeu de shards est UN composant : `role/<tronc>-*<extension>`, pas neuf entrées."""
        index = {'_class_name': 'QwenImagePipeline',
                 'transformer': ['diffusers', 'QwenImageTransformer2DModel']}
        noms = [f'diffusion_pytorch_model-0000{i}-of-00003.safetensors' for i in (1, 2, 3)]
        with tempfile.TemporaryDirectory() as tmp:
            root = _snapshot(Path(tmp), index, {'transformer': noms})
            parts = components_from_snapshot(root)
        self.assertEqual(parts, [{'role': 'transformer',
                                  'pattern': 'transformer/diffusion_pytorch_model-*.safetensors'}])

    def test_the_most_complete_set_wins_when_two_coexist(self):
        """Cas mochi, mesuré : `text_encoder` porte DEUX jeux (`-of-00002` et `-of-00004`) que
        rien dans le nom ne distingue. La dérivation prend le plus complet — arbitrage stable —
        et le journalise, parce que seul l'`index.json` du dépôt sait lequel est chargé."""
        noms = ([f'model-0000{i}-of-00004.safetensors' for i in (1, 2, 3, 4)]
                + [f'model-0000{i}-of-00002.safetensors' for i in (1, 2)])
        self.assertEqual(pattern_for_files('text_encoder', noms),
                         'text_encoder/model-*.safetensors')

    def test_no_model_index_means_no_anatomy_never_an_empty_one(self):
        """Un modèle monobloc n'a pas d'anatomie à décrire. `[]` dit « rien à déclarer » —
        l'appelant ne doit surtout pas en faire un `{}` qui EFFACERAIT une anatomie connue
        (c'est le défaut corrigé le même jour dans la projection des manifestes)."""
        with tempfile.TemporaryDirectory() as tmp:
            nu = Path(tmp) / 'models--org--mono' / 'snapshots' / 'sha'
            nu.mkdir(parents=True)
            (nu / 'model.safetensors').write_bytes(b'x')
            self.assertEqual(components_from_snapshot(nu.parent.parent), [])
        self.assertEqual(components_from_snapshot('/chemin/qui/nexiste/pas'), [])
        self.assertEqual(components_from_snapshot(None), [])

    def test_the_shared_builder_keeps_the_manifest_schema(self):
        """Le constructeur partagé rend la forme que `_validate_composition` accepte — c'est tout
        son intérêt : dix assembleurs dispersés finissent par diverger d'un champ."""
        from wama.common.manifests.builtin.model import _validate_composition
        compo = model_composition('diffusers', [{'role': 'vae', 'pattern': 'vae/x.safetensors'}])
        self.assertEqual(_validate_composition(compo), [])
        self.assertEqual(compo['runtime'], {'engine': 'diffusers'})
        # sans composant : le moteur SEUL, jamais une liste vide (qui serait une anatomie fausse)
        self.assertEqual(model_composition('bark', []), {'runtime': {'engine': 'bark'}})
        self.assertEqual(model_composition('', []), {})
