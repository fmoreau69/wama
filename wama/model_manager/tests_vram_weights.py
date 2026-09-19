"""Le POIDS PAR COMPOSANT d'un modèle installé est rendu au catalogue (décision A, 16/09).

POURQUOI. Le tirage ne connaissait qu'un chiffre, `vram_gb`, tantôt somme de composants (CogVideoX
21), tantôt plus gros composant (Qwen 38), jamais lu dans les fichiers. La dérivation existe
(`components_for_spec`, côté installation) et l'inventaire local aussi (`local_inventory`) ; il
manquait le geste qui relie une LIGNE de catalogue à son snapshot et écrit le résultat en clé
collante — `extra_info['weights']` — sans toucher `vram_gb`.

Aucun GPU, aucun réseau : une fausse racine `AI-models/models/` dans un dossier temporaire, des
fichiers CREUX (`truncate`) pour les tailles, des lignes de catalogue fabriquées.
"""
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from wama.common.utils.model_locations import hf_folder_name, hf_id_of_folder, installed_snapshots
from wama.model_manager.models import AIModel
from wama.model_manager.services.model_registry import ModelInfo, ModelSource, ModelType
from wama.model_manager.services.model_sync import ModelSyncService

MIB = 1024 ** 2


def _sparse(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as fh:
        fh.truncate(size)


class _FakeModelsRoot(TestCase):
    """Une racine canonique jetable ; `override_settings` la donne à `models_root()`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ai = Path(self.tmp.name) / 'AI-models'
        self.shared = self.ai / 'cache' / 'huggingface'
        self.shared.mkdir(parents=True)
        self._settings = override_settings(AI_MODELS_DIR=self.ai, HF_DEFAULT_CACHE=self.shared)
        self._settings.enable()
        self.addCleanup(self._settings.disable)

    def snapshot(self, hf_id: str, files: dict, *, category='diffusion', family='fam',
                 base: Path = None) -> Path:
        """Un `models--org--nom/snapshots/rev/` avec `files` = {chemin relatif: octets}."""
        root = (base or (self.ai / 'models' / category / family)) / hf_folder_name(hf_id)
        rev = root / 'snapshots' / 'rev0'
        for rel, size in files.items():
            _sparse(rev / rel, size)
        (root / 'blobs').mkdir(exist_ok=True)
        return root


class InstalledSnapshotsIndexTest(_FakeModelsRoot):

    def test_the_folder_name_round_trips_with_double_dashes_intact(self):
        self.assertEqual(hf_folder_name('Lightricks/LTX-Video-0.9.8-13B-distilled'),
                         'models--Lightricks--LTX-Video-0.9.8-13B-distilled')
        self.assertEqual(hf_id_of_folder('models--Lightricks--LTX-Video-0.9.8-13B-distilled'),
                         'Lightricks/LTX-Video-0.9.8-13B-distilled')
        self.assertIsNone(hf_id_of_folder('blobs'))
        self.assertIsNone(hf_id_of_folder('models--sans-org'))

    def test_the_index_walks_category_family_and_keeps_only_real_snapshots(self):
        root = self.snapshot('Org/One', {'model.safetensors': 10})
        (self.ai / 'models' / 'speech' / 'kokoro' / 'models--Org--Empty').mkdir(parents=True)
        index = installed_snapshots()
        self.assertEqual(index, {'org/one': root})

    def test_the_canonical_tree_wins_over_the_shared_cache(self):
        canon = self.snapshot('Org/Two', {'a.bin': 1})
        self.snapshot('Org/Two', {'a.bin': 1}, base=self.shared)
        only_shared = self.snapshot('Org/Dep', {'a.bin': 1}, base=self.shared)
        index = installed_snapshots()
        self.assertEqual(index['org/two'], canon)
        self.assertEqual(index['org/dep'], only_shared)

    def test_no_root_at_all_yields_an_empty_index(self):
        with override_settings(AI_MODELS_DIR=Path(self.tmp.name) / 'nowhere',
                               HF_DEFAULT_CACHE=Path(self.tmp.name) / 'nowhere-either'):
            self.assertEqual(installed_snapshots(), {})


_PIPELINE = {'transformer/diffusion_pytorch_model.safetensors': 8 * MIB,
             'vae/diffusion_pytorch_model.safetensors': 4 * MIB,
             'text_encoder/model.safetensors': 2 * MIB,
             'model_index.json': 400}
_DECLARED = {'components': [{'role': 'transformer', 'pattern': 'transformer/*.safetensors'},
                            {'role': 'vae', 'pattern': 'vae/*.safetensors'}],
             'runtime': {'engine': 'diffusers'}}


class PersistWeightsTest(_FakeModelsRoot):

    def _row(self, key, hf_id, **kw):
        base = dict(model_key=key, name=key, model_type='image', source='imager', hf_id=hf_id,
                    vram_gb=16.0, is_downloaded=True)
        base.update(kw)
        return AIModel.objects.create(**base)

    def _weights(self, key):
        return (AIModel.objects.get(model_key=key).extra_info or {}).get('weights')

    def test_a_declared_composition_decides_the_roles_and_vram_gb_is_untouched(self):
        self.snapshot('Org/Pipe', _PIPELINE)
        self._row('imager:pipe', 'Org/Pipe', composition=_DECLARED)
        self.assertEqual(ModelSyncService().persist_weights(), 1)
        w = self._weights('imager:pipe')
        self.assertEqual(w['source'], 'declared')
        self.assertEqual(w['components'], {'transformer': 0.008, 'vae': 0.004})
        self.assertEqual((w['total_gb'], w['largest_gb']), (0.012, 0.008))
        self.assertIn('signature', w)
        self.assertIn('at', w)
        self.assertEqual(AIModel.objects.get(model_key='imager:pipe').vram_gb, 16.0)

    def test_without_a_declaration_the_repo_convention_is_a_bound_and_says_so(self):
        self.snapshot('Org/Bare', _PIPELINE)
        self._row('imager:bare', 'Org/Bare')
        ModelSyncService().persist_weights()
        w = self._weights('imager:bare')
        self.assertEqual(w['source'], 'repo')
        self.assertEqual(set(w['components']), {'transformer', 'vae', 'text_encoder'})
        self.assertEqual(w['total_gb'], 0.014)

    def test_an_unchanged_snapshot_is_neither_derived_nor_rewritten(self):
        self.snapshot('Org/Same', _PIPELINE)
        self._row('imager:same', 'Org/Same', composition=_DECLARED)
        svc = ModelSyncService()
        self.assertEqual(svc.persist_weights(), 1)
        first = self._weights('imager:same')
        self.assertEqual(svc.persist_weights(), 0)
        self.assertEqual(self._weights('imager:same'), first)

    def test_a_changed_composition_or_snapshot_is_derived_again(self):
        root = self.snapshot('Org/Move', _PIPELINE)
        row = self._row('imager:move', 'Org/Move', composition=_DECLARED)
        svc = ModelSyncService()
        svc.persist_weights()
        row.composition = {}
        row.save(update_fields=['composition'])
        self.assertEqual(svc.persist_weights(), 1)
        self.assertEqual(self._weights('imager:move')['source'], 'repo')
        # Un fichier de plus dans `vae/` : la signature bouge, la dérivation est refaite — et,
        # sans déclaration, elle garde UN jeu par rôle (le plus lourd) et range l'autre dans
        # `variants` (règle de `components_of_files`, pas une addition).
        _sparse(root / 'snapshots' / 'rev0' / 'vae' / 'extra.safetensors', 1 * MIB)
        self.assertEqual(svc.persist_weights(), 1)
        w = self._weights('imager:move')
        self.assertEqual(w['components']['vae'], 0.004)
        self.assertEqual(w['variants'], {'vae': 0.001})

    def test_a_row_whose_snapshot_is_nowhere_gets_nothing_and_stays_honest(self):
        self._row('imager:ghost', 'Org/Ghost', composition=_DECLARED)
        self.assertEqual(ModelSyncService().persist_weights(), 0)
        self.assertIsNone(self._weights('imager:ghost'))

    def test_local_path_naming_a_snapshot_outside_the_tree_is_honoured(self):
        elsewhere = Path(self.tmp.name) / 'elsewhere'
        root = self.snapshot('Org/Far', _PIPELINE, base=elsewhere)
        self._row('huggingface:Org/Far', 'Org/Far', local_path=str(root))
        self.assertEqual(ModelSyncService().persist_weights(), 1)
        self.assertEqual(self._weights('huggingface:Org/Far')['root'], str(root))

    def test_remote_proposed_and_undownloaded_rows_are_out_of_scope(self):
        self.snapshot('Org/Out', _PIPELINE)
        self._row('imager:not-yet', 'Org/Out', is_downloaded=False)
        self._row('imager:proposed', 'Org/Out', is_proposed=True)
        self._row('cloud:far', 'Org/Out', execution='cloud')
        self.assertEqual(ModelSyncService().persist_weights(), 0)

    def test_keys_restrict_the_pass(self):
        self.snapshot('Org/A', _PIPELINE)
        self.snapshot('Org/B', _PIPELINE)
        self._row('imager:a', 'Org/A')
        self._row('imager:b', 'Org/B')
        self.assertEqual(ModelSyncService().persist_weights(keys=['imager:a']), 1)
        self.assertIsNone(self._weights('imager:b'))

    def test_precision_is_read_from_the_headers_of_the_retained_files_per_role(self):
        """Le pic par précision a besoin des PARAMÈTRES et du dtype de chaque composant : lus
        dans l'en-tête des fichiers que la dérivation a retenus. Un rôle sans safetensors lisible
        (`.bin`) n'apparaît pas — l'absence se lit, elle ne vaut pas zéro."""
        from wama.model_manager.tests_local_inventory import _safetensors
        root = self.snapshot('Org/Prec', {'vae/diffusion_pytorch_model.bin': 4 * MIB,
                                          'model_index.json': 400})
        rev = root / 'snapshots' / 'rev0'
        for shard in ('00001-of-00002', '00002-of-00002'):
            p = rev / 'transformer' / f'diffusion_pytorch_model-{shard}.safetensors'
            _safetensors(p, {'w': {'dtype': 'BF16', 'shape': [1024, 512],
                                   'data_offsets': [0, 1024 * 512 * 2]}})
            with open(p, 'r+b') as fh:
                fh.truncate(8 * MIB)                    # la taille compte, l'en-tête reste intact
        self._row('imager:prec', 'Org/Prec')
        self.assertEqual(ModelSyncService().persist_weights(), 1)
        w = self._weights('imager:prec')
        self.assertEqual(w['precision'], {'transformer': {'params': 2 * 1024 * 512,
                                                          'dtypes': ['BF16']}})
        self.assertNotIn('files', w)
        self.assertEqual(w['components']['transformer'], 0.016)

    def test_a_declaration_matching_no_installed_file_falls_back_to_the_repo_and_says_so(self):
        """Le cas SDXL (2026-09-20) : installé en fp16, déclaré sur les fichiers pleine précision.
        Plutôt que se taire, on pèse par la convention et on marque `declared_unmatched`."""
        self.snapshot('Org/Fp16', {'unet/diffusion_pytorch_model.fp16.safetensors': 8 * MIB,
                                   'vae/diffusion_pytorch_model.fp16.safetensors': 4 * MIB,
                                   'model_index.json': 400})
        full_only = {'components': [{'role': 'unet', 'pattern': 'unet/diffusion_pytorch_model.safetensors'},
                                    {'role': 'vae', 'pattern': 'vae/diffusion_pytorch_model.safetensors'}]}
        self._row('imager:fp16', 'Org/Fp16', composition=full_only)
        self.assertEqual(ModelSyncService().persist_weights(), 1)
        w = self._weights('imager:fp16')
        self.assertTrue(w['declared_unmatched'])
        self.assertEqual(w['source'], 'repo')
        self.assertEqual(set(w['components']), {'unet', 'vae'})

    def test_weights_survive_the_next_sync_like_the_measure(self):
        self.snapshot('Org/Sticky', _PIPELINE)
        self._row('imager:sticky', 'Org/Sticky', composition=_DECLARED)
        svc = ModelSyncService()
        svc.persist_weights()
        info = ModelInfo(id='imager:sticky', name='sticky', model_type=ModelType.DIFFUSION,
                         source=ModelSource.WAMA_IMAGER, hf_id='Org/Sticky', vram_gb=16.0,
                         is_downloaded=True, composition=_DECLARED)
        svc._sync_model('imager:sticky', info)
        self.assertEqual(self._weights('imager:sticky')['largest_gb'], 0.008)
