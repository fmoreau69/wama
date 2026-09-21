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


class DeclaredCompositionsAreValidTest(SimpleTestCase):
    """Toute composition DÉCLARÉE par une app passe le schéma du manifeste `model`.

    Ajouté à la clôture du 2026-09-21 : seules les déclarations imager étaient validées
    (`imager.tests.DeclaredCompositionTest`). Celles de composer (audiocraft) et du synthesizer
    (bark, coqui, higgs, kokoro — le service TTS les lit) ne l'étaient pas : une clé mal nommée y
    serait transportée au catalogue, puis REFUSÉE à la projection du manifeste, sans bruit.
    """

    SOURCES = (('wama.imager.utils.model_config', 'IMAGER_MODELS'),
               ('wama.composer.utils.model_config', 'COMPOSER_MODELS'),
               ('wama.synthesizer.utils.model_config', 'SYNTHESIZER_MODELS'))

    def test_every_declared_composition_passes_the_manifest_schema(self):
        import importlib
        from wama.common.manifests.builtin.model import _validate_composition
        seen = 0
        for module, table in self.SOURCES:
            models = getattr(importlib.import_module(module), table)
            for key, cfg in models.items():
                compo = cfg.get('composition')
                if not compo:
                    continue
                seen += 1
                with self.subTest(app=table, model=key):
                    self.assertEqual(_validate_composition(compo), [])
        # contre-épreuve : le test ne doit pas passer à vide si une table change de nom
        self.assertGreaterEqual(seen, 20, "moins de compositions déclarées que mesuré le 21/09")


class ComponentOverlayFillsOnlyTheVoidTest(SimpleTestCase):
    """`ModelRegistry._overlay_components_derived_from_disk` — la passe qui DÉRIVE l'anatomie.

    Le contrat qu'aucun autre test ne tenait : elle ne comble qu'un VIDE. Une composition déclarée
    est l'autorité (mochi : deux jeux de shards que seul l'app sait départager) ; et une ligne
    déclarée par une app, sans `extra_info['path']`, se résout par l'index des snapshots installés
    (sans lui, 1 modèle sur 81 était couvert le 2026-09-20).
    """

    def _registry(self, **models):
        from types import SimpleNamespace
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry.__new__(ModelRegistry)
        registry._models = {k: SimpleNamespace(**v) for k, v in models.items()}
        return registry

    def _run(self, registry, index, derived):
        from unittest import mock
        with mock.patch('wama.common.utils.model_locations.installed_snapshots',
                        return_value=index), \
             mock.patch('wama.common.utils.model_anatomy.components_from_snapshot',
                        return_value=derived) as derive:
            registry._overlay_components_derived_from_disk()
        return derive

    def test_a_declared_anatomy_is_never_overwritten(self):
        declared = {'components': [{'role': 'text_encoder', 'pattern': 'te/model-*-of-00004.x'}]}
        registry = self._registry(m={'composition': dict(declared), 'extra_info': {'path': '/p'},
                                     'hf_id': 'org/m'})
        derive = self._run(registry, {}, [{'role': 'vae', 'pattern': 'vae/x'}])
        self.assertEqual(registry._models['m'].composition, declared)
        derive.assert_not_called()

    def test_an_app_row_without_path_is_found_through_the_snapshot_index(self):
        registry = self._registry(m={'composition': {'runtime': {'engine': 'diffusers'}},
                                     'extra_info': {}, 'hf_id': 'Org/M'})
        parts = [{'role': 'vae', 'pattern': 'vae/x.safetensors'}]
        derive = self._run(registry, {'org/m': '/snap/models--org--m'}, parts)
        derive.assert_called_once_with('/snap/models--org--m')
        # le moteur déclaré est GARDÉ : on ajoute les composants, on ne remplace pas la composition
        self.assertEqual(registry._models['m'].composition,
                         {'runtime': {'engine': 'diffusers'}, 'components': parts})

    def test_nothing_derivable_leaves_the_row_untouched(self):
        registry = self._registry(m={'composition': {}, 'extra_info': {}, 'hf_id': 'org/absent'})
        self._run(registry, {}, [{'role': 'vae', 'pattern': 'x'}])
        self.assertEqual(registry._models['m'].composition, {})
        registry = self._registry(m={'composition': {}, 'extra_info': {'path': '/mono'},
                                     'hf_id': 'org/mono'})
        self._run(registry, {}, [])                    # monobloc : `[]`, jamais `{'components': []}`
        self.assertEqual(registry._models['m'].composition, {})
