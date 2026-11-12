"""
Le PONT wama-dev-ai ↔ skills WAMA, et la santé du corpus de skills (2026-09-09).

⚠ POURQUOI CES GARDES EXISTENT — elles manquaient à la livraison. Le pont avait été validé par
un smoke MANUEL, hors suite : il pouvait donc casser sans que rien ne sonne, et il venait
précisément de passer 14 mois à ne pas exister pendant que trois documents l'affirmaient.
*Un pont attesté par un script qu'on lance à la main n'est pas gardé.*

⚠ POURQUOI CE MODULE VIT CÔTÉ WAMA. `wama-dev-ai` est en tiret-case, donc **non importable**
(règle de nommage) et **exclu de la découverte** des tests (`RACINES_HORS_DECOUVERTE`). Ses
modules se chargent donc par CHEMIN, exactement comme ses lanceurs le font. C'est le seul
endroit d'où ce contrat peut être tenu automatiquement.
"""
import ast
import importlib.util
import json
import sys

from django.conf import settings
from django.test import SimpleTestCase
from django.core.management import call_command
from io import StringIO
from pathlib import Path

RACINE = Path(settings.BASE_DIR)
DEV_AI = RACINE / 'wama-dev-ai'


def _charger(nom):
    """Charge un module de `wama-dev-ai` PAR CHEMIN — comme ses lanceurs (`python run_*.py`)."""
    chemin = DEV_AI / f'{nom}.py'
    spec = importlib.util.spec_from_file_location(f'_devai_{nom}', chemin)
    module = importlib.util.module_from_spec(spec)
    # Ses modules s'importent en ABSOLU entre eux (`from config import …`) parce que le lanceur
    # met `wama-dev-ai/` sur le chemin. On reproduit cette condition, on ne la contourne pas.
    if str(DEV_AI) not in sys.path:
        sys.path.insert(0, str(DEV_AI))
    spec.loader.exec_module(module)
    return module


class PontSkillsTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def test_le_pont_existe_et_resout_la_cascade(self):
        """`<app>-<domain>` → `<app>` → `default-<kind>`, vue depuis wama-dev-ai."""
        nom, texte = self.role_utils.skill_wama(app='imager', domain='image')
        self.assertEqual('imager-image', nom)
        self.assertTrue(texte)

    def test_une_app_inconnue_retombe_sur_le_repli_et_ne_leve_pas(self):
        """Le fail-safe est le contrat : l'appelant garde son repli intégré."""
        nom, texte = self.role_utils.skill_wama(app='nexistepas')
        self.assertEqual('default-generative', nom)
        self.assertTrue(texte)

    def test_le_catalogue_est_le_MEME_que_celui_de_WAMA(self):
        """Deux sources qui divergent, c'est le défaut que ce pont était censé finir."""
        from ..utils.prompt_skills import skills_catalog
        self.assertEqual(set(skills_catalog()), set(self.role_utils.catalogue_skills()))

    def test_la_constante_MORTE_n_est_pas_revenue(self):
        """`PROMPT_SKILLS_DIR` a été déclarée 14 mois sans être lue, et son RETRAIT est le
        correctif. La rétablir « pour la commodité » rouvrirait la même illusion de liaison."""
        config = _charger('config')
        self.assertFalse(hasattr(config, 'PROMPT_SKILLS_DIR'),
                         "un chemin déclaré sans lecteur fait croire à une liaison")


class ConsigneRoleTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def test_l_accesseur_unique_lit_les_consignes(self):
        for nom in ('audit', 'codegen', 'system'):
            with self.subTest(consigne=nom):
                self.assertTrue(self.role_utils.consigne_role(nom).strip())

    def test_une_consigne_ABSENTE_LEVE_et_liste_les_connues(self):
        """L'ancien `cli.py` rendait `""` : un rôle SANS POSTURE rend une sortie plausible et
        fausse — le pire cas pour un agent dont tout part en validation humaine."""
        with self.assertRaises(FileNotFoundError) as ctx:
            self.role_utils.consigne_role('nexistepas')
        self.assertIn('audit', str(ctx.exception),
                      "le message doit lister les consignes connues, sinon la faute de frappe "
                      "reste muette")

    def test_plus_aucune_lecture_du_dossier_hors_de_l_accesseur(self):
        """Il y avait QUATRE lecteurs. Un chemin réécrit en dur ne casse rien — il diverge."""
        for fichier in ('cli.py', 'run_audit.py', 'run_codegen.py'):
            source = (DEV_AI / fichier).read_text(encoding='utf-8')
            with self.subTest(fichier=fichier):
                self.assertIn('consigne_role', source,
                              f"{fichier} n'utilise plus l'accesseur unique")
                # Le CHEMIN, pas le mot (2026-10-01) : `'prompts'` est aussi le nom d'une facette
                # du manifeste app, que run_codegen lit légitimement. Une garde par motif nu
                # aurait interdit de nommer la facette ; elle vise la composition de chemin.
                self.assertNotRegex(source.replace("PROMPTS_DIR", ""),
                                    r"/\s*['\"]prompts['\"]|['\"]prompts['\"]\s*/"
                                    r"|joinpath\([^)]*['\"]prompts['\"]",
                                    f"{fichier} recompose un chemin vers le dossier de consignes")


class CheckSkillsTest(SimpleTestCase):
    """La commande de santé du corpus — elle n'avait aucune garde non plus."""

    def _sortie(self, *args):
        flux = StringIO()
        call_command('check_skills', *args, stdout=flux)
        return flux.getvalue()

    def test_elle_compte_les_skills_et_ne_tourne_pas_a_vide(self):
        """Garde d'INSTRUMENT : « 0 défaut » sur un scan vide ressemble à un dépôt sain."""
        sortie = self._sortie()
        self.assertIn('SANTÉ DES SKILLS', sortie)
        self.assertNotIn('(0 skill(s)', sortie)

    def test_le_detecteur_de_declencheur_ne_produit_PAS_de_faux_positif(self):
        """⚠ Ma 1ʳᵉ rédaction énumérait des préfixes littéraux et accusait `/conformite`, dont
        la description dit pourtant « Utiliser après un palier ». Mesuré ensuite : les 14
        skills contiennent « utiliser ». *Un détecteur qui rate des correspondances est pire
        qu'aucun détecteur — il rend un chiffre.*"""
        self.assertNotIn('SANS DÉCLENCHEUR', self._sortie())

    def test_strict_sort_en_zero_quand_le_corpus_est_sain(self):
        try:
            self._sortie('--strict')
        except SystemExit as e:  # pragma: no cover — ne doit pas arriver sur un corpus sain
            self.fail(f"`--strict` a échoué sur un corpus sans défaut franc : {e}")


class ModelVocabulariesServedToEveryRoleTest(SimpleTestCase):
    """Les vocabulaires FERMÉS d'un manifeste `model` sont servis à TOUT rôle qui en écrit un.

    Vécu le 2026-09-30 : `5331eaea` avait servi `INPUT_TYPES` au seul rôle `model` ; le rôle
    frère `scout` écrit le même manifeste et, sans ce vocabulaire, qwen3.8 a déclaré `audio`/
    `image` comme entrées de LongCat-Video-Avatar-1.5 (manifeste invalide). La garde est
    GÉNÉRIQUE : elle part de ce que fait un rôle (valider un manifeste), pas d'une liste.
    """

    #: Rôles qui valident un manifeste d'un AUTRE kind — exemptés, avec leur raison.
    OTHER_KINDS = {'run_librarian.py': 'écrit des manifestes `library` (vocabulaire pip)',
                   'run_app_manifest.py': 'écrit des manifestes `app` — ses vocabulaires fermés '
                                          '(types de port, états, groupes) servis par '
                                          '`vocabularies()`'}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def _validating_roles(self):
        return sorted(p.name for p in DEV_AI.glob('run_*.py')
                      if 'manifests.ingest import validate' in p.read_text(encoding='utf-8'))

    def test_every_manifest_writing_role_receives_the_vocabularies(self):
        roles = self._validating_roles()
        self.assertIn('run_scout.py', roles, "garde d'instrument : le relevé ne voit plus le scout")
        for name in roles:
            if name in self.OTHER_KINDS:
                continue
            with self.subTest(role=name):
                self.assertIn('model_vocabularies()', (DEV_AI / name).read_text(encoding='utf-8'),
                              f"{name} valide un manifeste sans servir les vocabulaires fermés")

    def test_no_exemption_outlives_its_role(self):
        for name in self.OTHER_KINDS:
            with self.subTest(role=name):
                self.assertIn(name, self._validating_roles(),
                              f"exemption devenue inutile : {name} ne valide plus de manifeste")

    def test_the_vocabularies_carry_every_input_type(self):
        from wama.common.utils.app_modes import INPUT_TYPES
        text = self.role_utils.model_vocabularies()
        for input_id in INPUT_TYPES:
            with self.subTest(input_id=input_id):
                self.assertIn(input_id, text)

    def test_the_vocabularies_carry_the_language_rule(self):
        """Le rôle apprend la forme d'une langue que le validateur exige (2026-11-06, ACE-Step)."""
        from wama.common.utils.model_capabilities import LANGUAGE_CAPABILITIES
        text = self.role_utils.model_vocabularies()
        for key in LANGUAGE_CAPABILITIES:
            with self.subTest(key=key):
                self.assertIn(key, text)
        self.assertIn('ISO 639', text)


class DiffusersEngineMustBeProvenTest(SimpleTestCase):
    """`engine: diffusers` n'est gardé que si le `_class_name` du dépôt existe dans `diffusers`.

    Cas réels du 2026-09-30 (qwen3.8) : LongCat-Video-Avatar-1.5 (`model_index.json` sans
    `_class_name`) et SoulX-FlashHead (`WanModelAudioProject`) déclarés `diffusers`. Témoins
    réels : `StableDiffusionXLPipeline`, `LTXPipeline`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    @staticmethod
    def _manifest(engine='diffusers'):
        return {'body': {'composition': {'components': [{'role': 'vae', 'pattern': 'v.pth'}],
                                         'runtime': {'engine': engine}}}}

    def _enforce(self, manifest, class_name, files=()):
        concerns = []
        reader = lambda _hf: (class_name, f'model_index.json nomme {class_name!r}')
        self.role_utils.enforce_engine_facts(manifest, 'org/repo', concerns, reader=reader,
                                             lister=lambda _hf: list(files))
        return manifest, concerns

    def test_the_pipeline_class_is_read_from_a_modular_index_too(self):
        """`flux-3-image-klein` (2026-11-12) has no `model_index.json`, only a
        `modular_model_index.json`: the role read the first only and said « no index »."""
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            modular = Path(tmp) / 'modular_model_index.json'
            modular.write_text(json.dumps({'_class_name': 'Flux3DistilledModularPipeline'}), encoding='utf-8')

            def download(repo_id, name):
                if name != 'modular_model_index.json':
                    raise FileNotFoundError(name)
                return str(modular)
            with mock.patch('huggingface_hub.hf_hub_download', side_effect=download):
                found, reason = self.role_utils.diffusers_pipeline_class('bfl/klein')
                self.assertEqual('Flux3DistilledModularPipeline', found, reason)
            # Counter-check: neither index → no class, and the reason names both.
            with mock.patch('huggingface_hub.hf_hub_download', side_effect=FileNotFoundError):
                found, reason = self.role_utils.diffusers_pipeline_class('o/none')
                self.assertIsNone(found)
                self.assertIn('modular_model_index.json', reason)

    def test_a_real_diffusers_pipeline_keeps_its_engine(self):
        manifest, concerns = self._enforce(self._manifest(), 'StableDiffusionXLPipeline')
        self.assertEqual('diffusers', manifest['body']['composition']['runtime']['engine'])
        self.assertEqual([], concerns)

    def test_an_unknown_pipeline_class_loses_the_engine_and_says_why(self):
        manifest, concerns = self._enforce(self._manifest(), 'WanModelAudioProject')
        composition = manifest['body']['composition']
        self.assertNotIn('runtime', composition, "un moteur non prouvé ne doit pas survivre")
        self.assertTrue(composition['components'], "les composants, eux, restent")
        self.assertEqual(1, len(concerns))
        self.assertIn('WanModelAudioProject', concerns[0])

    def test_no_model_index_loses_the_engine(self):
        manifest, _ = self._enforce(self._manifest(), None)
        self.assertNotIn('runtime', manifest['body']['composition'])

    def test_another_engine_is_left_to_its_own_judgment(self):
        """Le contrôle ne tranche QUE ce que le fait prouve : il ne touche pas `musetalk`."""
        manifest, concerns = self._enforce(self._manifest('musetalk'), None)
        self.assertEqual('musetalk', manifest['body']['composition']['runtime']['engine'])
        self.assertEqual([], concerns)

    def test_both_manifest_roles_apply_it(self):
        for name in ('run_scout.py', 'run_model_manifest.py'):
            with self.subTest(role=name):
                self.assertIn('enforce_engine_facts(', (DEV_AI / name).read_text(encoding='utf-8'))

    def test_an_architecture_absent_from_transformers_loses_the_engine(self):
        """Cas réel du 2026-09-30 : LinTO FastConformer, `ParakeetForRNNT`."""
        manifest, concerns = self._enforce(self._manifest('transformers'), ['ParakeetForRNNT'])
        self.assertNotIn('runtime', manifest['body']['composition'])
        self.assertIn('ParakeetForRNNT', concerns[0])

    def test_a_repo_declaring_its_code_gets_the_remote_code_engine(self):
        """Cas réel du 2026-10-03 : SheetSage2, `SheetSage2Model` déclaré par `auto_map`."""
        concerns = []
        manifest = self._manifest('transformers')
        reader = lambda _hf: (['SheetSage2Model'], "config.json nomme ['SheetSage2Model'] "
                                                   f"({self.role_utils.REMOTE_CODE_MARK})")
        self.role_utils.enforce_engine_facts(manifest, 'org/repo', concerns, reader=reader,
                                             lister=lambda _hf: [])
        self.assertEqual('transformers-remote-code',
                         manifest['body']['composition']['runtime']['engine'])
        self.assertEqual(1, len(concerns))

    def test_an_installed_architecture_keeps_transformers(self):
        manifest, concerns = self._enforce(self._manifest('transformers'),
                                           ['WhisperForConditionalGeneration'])
        self.assertEqual('transformers', manifest['body']['composition']['runtime']['engine'])
        self.assertEqual([], concerns)

    def test_several_weight_formats_are_said(self):
        files = ('config.json', 'model.safetensors', 'linto_stt_fr_fastconformer_pc.nemo')
        _, concerns = self._enforce(self._manifest('musetalk'), None, files=files)
        self.assertEqual(1, len(concerns))
        self.assertIn('.nemo', concerns[0])
        self.assertIn('.safetensors', concerns[0])

    def test_a_single_weight_format_says_nothing(self):
        _, concerns = self._enforce(self._manifest('musetalk'), None,
                                    files=('config.json', 'model.safetensors'))
        self.assertEqual([], concerns)

    def _resolution(self, manifest, configs):
        concerns = []
        self.role_utils.enforce_resolution_facts(
            manifest, 'org/repo', concerns, lister=lambda _hf: list(configs),
            loader=lambda name: configs[name])
        return manifest, concerns

    def test_a_config_size_is_posed_when_the_manifest_is_silent(self):
        """Real case (2026-09-30): Supra2-IMG, `pipeline_config.json` → `image_size: 256`."""
        manifest, concerns = self._resolution({'body': {'capabilities': {}}},
                                              {'pipeline_config.json': {'image_size': 256}})
        self.assertEqual('256x256', manifest['body']['capabilities']['native_resolution'])
        self.assertIn('POSÉE', concerns[0])

    def test_a_contrary_size_is_corrected_and_said(self):
        manifest, concerns = self._resolution(
            {'body': {'capabilities': {'native_resolution': '1024x1024'}}},
            {'pipeline_config.json': {'image_size': 256}})
        self.assertEqual('256x256', manifest['body']['capabilities']['native_resolution'])
        self.assertIn('CORRIGÉE', concerns[0])

    def test_no_size_in_the_configs_changes_nothing(self):
        manifest, concerns = self._resolution({'body': {'capabilities': {}}},
                                              {'config.json': {'architectures': ['X']},
                                               'sub/config.json': {'image_size': 64}})
        self.assertNotIn('native_resolution', manifest['body']['capabilities'],
                         'only ROOT configs speak for the model')
        self.assertEqual([], concerns)

    def test_both_manifest_roles_apply_the_resolution_fact(self):
        for name in ('run_scout.py', 'run_model_manifest.py'):
            with self.subTest(role=name):
                self.assertIn('enforce_resolution_facts(',
                              (DEV_AI / name).read_text(encoding='utf-8'))

    def test_an_engine_no_backend_serves_is_kept_and_said(self):
        manifest, concerns = self._enforce(self._manifest('no-such-engine'), None)
        self.assertEqual('no-such-engine', manifest['body']['composition']['runtime']['engine'])
        self.assertEqual(1, len(concerns))
        self.assertIn('AUCUN backend', concerns[0])

    LINTO_FILES = ('config.json', 'model.safetensors', 'linto_stt_fr_fastconformer_pc.nemo')

    def test_a_removed_engine_gives_way_to_the_one_the_weight_format_proves(self):
        """Real case (2026-10-01, LinTO): transformers removed, the `.nemo` proves `nemo`."""
        manifest, concerns = self._enforce(self._manifest('transformers'), ['ParakeetForRNNT'],
                                           files=self.LINTO_FILES)
        self.assertEqual('nemo', manifest['body']['composition']['runtime']['engine'])
        self.assertTrue(any('PROPOSÉ' in c and '.nemo' in c for c in concerns), concerns)

    def test_a_manifest_without_engine_gets_the_proven_one(self):
        manifest, _ = self._enforce({'body': {}}, None, files=self.LINTO_FILES)
        self.assertEqual('nemo', manifest['body']['composition']['runtime']['engine'])

    def test_a_format_that_proves_nothing_adds_nothing(self):
        manifest, concerns = self._enforce({'body': {}}, None,
                                           files=('config.json', 'model.safetensors'))
        self.assertNotIn('composition', manifest['body'])
        self.assertEqual([], concerns)


class SimpleModelAnatomyTest(SimpleTestCase):
    """The `backend` role demands `composition.components`; a single-piece model never got one
    (2026-10-01: FrWhisper, Kyutai, LinTO). File lists are the real repositories'."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def _anatomy(self, files, engine=None, components=None):
        composition = {'runtime': {'engine': engine}} if engine else {}
        if components:
            composition['components'] = components
        manifest, concerns = {'body': {'composition': composition}}, []
        self.role_utils.enforce_component_facts(manifest, 'org/repo', concerns,
                                                lister=lambda _hf: list(files))
        return manifest['body'].get('composition', {}).get('components'), concerns

    def test_sharded_weights_are_designated_by_their_pattern(self):
        components, concerns = self._anatomy(
            ['config.json', 'model-00001-of-00002.safetensors', 'model-00002-of-00002.safetensors',
             'model.safetensors.index.json'], engine='transformers')
        self.assertEqual([{'role': 'model', 'pattern': 'model-*.safetensors', 'format': 'safetensors'}],
                         components)
        self.assertIn('POSÉE', concerns[0])

    def test_a_single_weight_file_is_designated_by_its_name(self):
        components, _ = self._anatomy(['config.json', 'model.safetensors'], engine='transformers')
        self.assertEqual('model.safetensors', components[0]['pattern'])

    def test_several_formats_take_the_one_that_proves_the_engine(self):
        components, _ = self._anatomy(['model.safetensors', 'linto_stt_fr_fastconformer_pc.nemo'],
                                      engine='nemo')
        self.assertEqual('linto_stt_fr_fastconformer_pc.nemo', components[0]['pattern'])

    def test_several_formats_without_proof_choose_nothing_and_say_so(self):
        components, concerns = self._anatomy(['model.safetensors', 'model.onnx'], engine='transformers')
        self.assertIsNone(components)
        self.assertIn('NON posée', concerns[0])

    def test_a_declared_anatomy_is_left_alone(self):
        declared = [{'role': 'acoustic_model', 'pattern': 'a.safetensors'}]
        components, concerns = self._anatomy(['a.safetensors', 'b.safetensors'], components=declared)
        self.assertEqual((declared, []), (components, concerns))

    #: Real file list of `onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX` (2026-10-06).
    SWIN2SR_FILES = ['.gitattributes', 'README.md', 'config.json', 'onnx/model.onnx',
                     'onnx/model_bnb4.onnx', 'onnx/model_fp16.onnx', 'onnx/model_int8.onnx',
                     'onnx/model_q4.onnx', 'onnx/model_q4f16.onnx', 'onnx/model_quantized.onnx',
                     'onnx/model_uint8.onnx', 'preprocessor_config.json', 'quantize_config.json']

    def test_an_onnx_export_keeps_its_full_precision_variant(self):
        """Without a component the install pulled all eight variants (210 MB for 51 useful)."""
        components, concerns = self._anatomy(self.SWIN2SR_FILES)
        self.assertEqual([{'role': 'model', 'pattern': 'onnx/model.onnx', 'format': 'onnx'}],
                         components)
        self.assertIn('model_q4.onnx', concerns[0], 'the variants left aside are said')

    def test_root_weights_win_over_an_onnx_export(self):
        components, _ = self._anatomy(['model.safetensors', 'onnx/model.onnx'])
        self.assertEqual('model.safetensors', components[0]['pattern'])


class TaskFactsTest(SimpleTestCase):
    """Real case (2026-10-06, Swin2SR ONNX on Albert): the scout wrote `image-to-image` (an EDITING
    model, offered to the imager), a `64x64` native resolution (the training window — the model
    upscales 80×128, measured) and no engine. The config.json says otherwise."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    CONFIG = {'config.json': {'architectures': ['Swin2SRForImageSuperResolution'],
                              'upscale': 4, 'image_size': 64}}

    def _scout_manifest(self):
        return {'body': {'identity': {'model_type': 'vision'},
                         'capabilities': {'task': 'image-to-image', 'modalities': ['image'],
                                          'inputs_required': ['work_image'],
                                          'native_resolution': '64x64'}}}

    def _facts(self, manifest, architectures, configs=None):
        configs = self.CONFIG if configs is None else configs
        concerns = []
        kw = dict(lister=lambda _hf: list(configs), loader=lambda name: configs[name])
        self.role_utils.enforce_task_facts(
            manifest, 'org/repo', concerns, reader=lambda _hf: (architectures, ''), **kw)
        self.role_utils.enforce_resolution_facts(manifest, 'org/repo', concerns, **kw)
        return manifest['body'], concerns

    def test_a_super_resolution_class_proves_the_upscale_task(self):
        body, concerns = self._facts(self._scout_manifest(), ['Swin2SRForImageSuperResolution'])
        caps = body['capabilities']
        self.assertEqual(('upscale', 'upscaling', 4),
                         (caps['task'], body['identity']['model_type'], caps['scale']))
        self.assertEqual(['work_file'], caps['inputs_required'],
                         "the inputs follow the corrected task, not the scout's")
        self.assertIn('video', caps['modalities'])
        self.assertTrue(any('CORRIGÉE' in c for c in concerns), concerns)

    def test_an_upscaler_has_no_native_resolution(self):
        body, concerns = self._facts(self._scout_manifest(), ['Swin2SRForImageSuperResolution'])
        self.assertNotIn('native_resolution', body['capabilities'])
        self.assertTrue(any('RETIRÉE' in c for c in concerns), concerns)

    def test_an_unknown_class_changes_nothing(self):
        """Counter-case: a generator keeps its task AND its config size (Supra2-IMG rule)."""
        manifest = {'body': {'identity': {'model_type': 'diffusion'},
                             'capabilities': {'task': 'text-to-image'}}}
        configs = {'pipeline_config.json': {'image_size': 256}}
        body, _ = self._facts(manifest, ['SomePipeline'], configs)
        self.assertEqual('text-to-image', body['capabilities']['task'])
        self.assertEqual('256x256', body['capabilities']['native_resolution'])

    def test_both_manifest_roles_apply_the_task_before_the_resolution(self):
        for name in ('run_scout.py', 'run_model_manifest.py'):
            with self.subTest(role=name):
                source = (DEV_AI / name).read_text(encoding='utf-8')
                self.assertIn('enforce_task_facts(', source)
                self.assertLess(source.index('enforce_task_facts('),
                                source.index('enforce_resolution_facts('))

    def test_an_onnx_graph_proves_the_onnxruntime_engine(self):
        manifest, concerns = {'body': {}}, []
        self.role_utils.enforce_engine_facts(manifest, 'org/repo', concerns,
                                             lister=lambda _hf: ['config.json', 'onnx/model.onnx'])
        self.assertEqual('onnxruntime', manifest['body']['composition']['runtime']['engine'])


class CategoryFollowsTheTaskTest(SimpleTestCase):
    """Real case (2026-10-07, GaterV3 — a GitHub release — on Albert): task `denoise` right,
    category `vision` judged by the LLM. The weights were stored under `vision/`, the row was
    born `vision`, and the enhancer select (anchored on `upscaling` by the task) lost it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def _manifest(self, task, model_type):
        return {'body': {'identity': {'model_type': model_type},
                         'capabilities': ({'task': task} if task else {})}}

    def test_the_category_of_the_task_wins_and_is_said(self):
        manifest, concerns = self._manifest('denoise', 'vision'), []
        self.role_utils.enforce_category_facts(manifest, concerns)
        self.assertEqual('upscaling', manifest['body']['identity']['model_type'])
        self.assertIn('denoise', concerns[0])

    def test_counter_proof_nothing_is_guessed(self):
        for task, model_type in (('denoise', 'upscaling'),    # already right
                                 ('not-a-task', 'vision'),    # unknown task: no table entry
                                 ('', 'vision')):             # no task at all
            with self.subTest(task=task):
                manifest, concerns = self._manifest(task, model_type), []
                self.role_utils.enforce_category_facts(manifest, concerns)
                self.assertEqual(model_type, manifest['body']['identity']['model_type'])
                self.assertEqual([], concerns)

    def test_both_manifest_roles_apply_it_after_the_task(self):
        for name in ('run_scout.py', 'run_model_manifest.py'):
            with self.subTest(role=name):
                source = (DEV_AI / name).read_text(encoding='utf-8')
                self.assertIn('enforce_category_facts(manifest, concerns)', source)
                self.assertLess(source.index('enforce_task_facts(manifest'),
                                source.index('enforce_category_facts(manifest'))


class IdentityIsTheRequestedOneTest(SimpleTestCase):
    """Real case (2026-10-01, gpt-oss-120b on Albert): asked for `kyutai/stt-1b-en_fr-trfs`, the
    LLM wrote the key of ANOTHER model (`kyutai/stt-2.6b-en`) — and the engine check then read
    that other model's config and removed a valid engine."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    KEY, HF = 'huggingface:kyutai/stt-1b-en_fr-trfs', 'kyutai/stt-1b-en_fr-trfs'

    def test_another_models_identity_is_replaced_and_said(self):
        manifest = {'key': 'huggingface:kyutai/stt-2.6b-en',
                    'body': {'identity': {'platform_ref': 'huggingface:kyutai/stt-2.6b-en'}}}
        concerns = []
        self.role_utils.enforce_identity(manifest, self.KEY, self.HF, concerns)
        self.assertEqual((self.KEY, self.KEY),
                         (manifest['key'], manifest['body']['identity']['platform_ref']))
        self.assertEqual(1, len(concerns))
        self.assertIn('stt-2.6b-en', concerns[0])

    def test_a_wrong_identity_takes_the_wrong_name_with_it(self):
        manifest = {'key': 'huggingface:kyutai/stt-2.6b-en', 'name': 'stt-2.6b-en', 'body': {}}
        self.role_utils.enforce_identity(manifest, self.KEY, self.HF, [])
        self.assertEqual('stt-1b-en_fr-trfs', manifest['name'])

    def test_the_card_languages_override_the_llms(self):
        manifest = {'body': {'capabilities': {'languages': ['en']}}}
        concerns = []
        self.role_utils.enforce_language_facts(manifest, ['en', 'fr'], concerns)
        self.assertEqual(['en', 'fr'], manifest['body']['capabilities']['languages'])
        self.assertIn('CORRIGÉES', concerns[0])

    def test_a_card_without_languages_leaves_them_alone(self):
        manifest = {'body': {'capabilities': {'languages': ['fr']}}}
        concerns = []
        self.role_utils.enforce_language_facts(manifest, [], concerns)
        self.assertEqual((['fr'], []), (manifest['body']['capabilities']['languages'], concerns))

    def test_the_card_languages_are_read_from_the_yaml_header(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'README.md').write_text('---\nlanguage:\n- en\n- fr-FR\nlicense: cc-by-4.0\n'
                                                 '---\n# Card\n', encoding='utf-8')
            self.assertEqual(['en', 'fr'], self.role_utils.card_languages('org/repo', folder))

    def test_the_right_identity_says_nothing(self):
        manifest = {'key': self.KEY, 'body': {'identity': {'platform_ref': self.KEY}}}
        concerns = []
        self.role_utils.enforce_identity(manifest, self.KEY, self.HF, concerns)
        self.assertEqual([], concerns)

    def test_a_retired_hf_id_written_by_the_llm_does_not_enter_the_identity(self):
        manifest = {'key': self.KEY, 'body': {'identity': {'hf_id': self.HF, 'platform_ref': self.KEY}}}
        self.role_utils.enforce_identity(manifest, self.KEY, self.HF, [])
        self.assertEqual({'platform_ref': self.KEY}, manifest['body']['identity'])

    def test_the_scout_drops_the_retired_hf_id_after_its_facts(self):
        source = (DEV_AI / 'run_scout.py').read_text(encoding='utf-8')
        self.assertNotIn("'hf_id'", source)
        self.assertLess(source.index('for chemin, valeur in facts:'),
                        source.index('drop_retired_identity(manifest)'))

    def test_the_model_role_imposes_it_before_the_engine_check(self):
        source = (DEV_AI / 'run_model_manifest.py').read_text(encoding='utf-8')
        self.assertLess(source.index('enforce_identity(manifest'),
                        source.index('enforce_engine_facts(manifest'),
                        'the engine check must read the REQUESTED model')


class InstallChannelFromRepoFactsTest(SimpleTestCase):
    """`librarian --repo` : le canal d'installation se pose d'après les FAITS du dépôt.

    Un dépôt sans fichier de paquet (MuseTalk, TripoSR) n'est pas installable par pip : il se
    vendorise au commit MESURÉ (ROADMAP D-a). Un paquet reste sur pip, quoi qu'écrive le LLM.
    Le manifeste produit doit passer le MÊME validateur que le corpus.
    """

    SHA = '0a89dec45a0192b824e3cf4daf96c239440c5ed8'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    @staticmethod
    def _llm_manifest(install):
        return {'manifest_kind': 'library', 'key': 'MuseTalk', 'name': 'MuseTalk',
                'schema_version': '1.0', 'description': 'lip sync', 'world': 'transverse',
                'visibility': 'public', 'projects': [],
                'source': {'type': 'extract', 'ref': 'https://github.com/TMElyralab/MuseTalk'},
                'body': {'identity': {'version': '1.5', 'license': 'MIT'}, 'install': install}}

    def test_a_repo_without_packaging_is_vendored_at_the_measured_commit(self):
        from wama.common.manifests.ingest import validate
        notes = []
        manifest = self.role_utils.enforce_install_channel(
            self._llm_manifest({'pip': 'musetalk==1.5'}), 'TMElyralab/MuseTalk', [], self.SHA, notes)
        self.assertEqual(manifest['body']['install'],
                         {'vendor': {'repo': 'TMElyralab/MuseTalk', 'commit': self.SHA,
                                     'engine': 'musetalk'}})
        self.assertEqual(manifest['key'], 'musetalk')
        self.assertEqual(manifest['source']['type'], 'authored')
        self.assertEqual(validate(manifest) or [], [])
        self.assertTrue(any('RETIRÉ' in n for n in notes), notes)

    def test_a_packaged_repo_stays_on_pip(self):
        """Contre-épreuve : un paquet garde pip, et un `vendor` inventé par le LLM est retiré."""
        notes = []
        manifest = self.role_utils.enforce_install_channel(
            self._llm_manifest({'pip': 'faster-whisper==1.2.1',
                                'vendor': {'repo': 'x/y', 'commit': self.SHA, 'engine': 'y'}}),
            'SYSTRAN/faster-whisper', ['pyproject.toml'], None, notes)
        self.assertEqual(manifest['body']['install'], {'pip': 'faster-whisper==1.2.1'})
        self.assertEqual(manifest['key'], 'MuseTalk')

    def test_a_package_absent_from_pypi_is_vendored_too(self):
        """YuE et ACE-Step : un `pyproject.toml`, aucune publication — la route pip les refuserait."""
        notes = []
        manifest = self.role_utils.enforce_install_channel(
            self._llm_manifest({'pip': 'acestep==1.5.0'}), 'ace-step/ACE-Step-1.5',
            ['pyproject.toml'], self.SHA, notes, published=False)
        self.assertEqual(manifest['body']['install']['vendor']['engine'], 'ace_step_1_5')
        self.assertTrue(any('NON publié' in n for n in notes), notes)

    def test_pypi_publication_is_measured_at_the_pinned_version(self):
        """`ace-step` existe sur PyPI en 0.1.0 seulement : la 1.5.0 proposée n'est PAS publiée."""
        published = {'/pypi/ace-step/json': 200, '/pypi/ace-step/0.1.0/json': 200}
        seen = []

        def status_of(url):
            seen.append(url)
            return next((code for path, code in published.items() if url.endswith(path)), 404)

        def offline(url):
            raise OSError('proxy')
        pp = self.role_utils.pypi_published
        self.assertTrue(pp('ace-step', status_of=status_of))
        self.assertFalse(pp('ace-step', '1.5.0', status_of=status_of))
        self.assertTrue(seen[-1].endswith('/pypi/ace-step/1.5.0/json'), seen)
        self.assertFalse(pp('acestep', status_of=status_of))
        self.assertIsNone(pp('ace-step', '1.5.0', status_of=offline),
                          'une panne réseau ne vaut pas « non publié »')
        self.assertIsNone(pp('ace-step', status_of=lambda url: 503))

    def test_a_distribution_only_published_is_read_on_pypi(self):
        """2026-11-06 : `gguf` n'était pas installé, et son dépôt publie un autre paquet à sa
        racine — `librarian --dist` lit ce que PyPI publie. Un PyPI muet n'invente rien."""
        payload = {'info': {'name': 'gguf', 'version': '0.19.0', 'summary': 'GGUF for GGML',
                            'requires_python': '>=3.10',
                            'requires_dist': ['numpy>=1.17', 'PySide6<7.0,>=6.9; extra == "gui"'],
                            'description': 'README gguf'}}
        seen = []

        def fetcher(url):
            seen.append(url)
            return json.dumps(payload)
        facts = self.role_utils.pypi_metadata('gguf', fetcher=fetcher)
        self.assertEqual((facts['name'], facts['version'], facts['requires_python']),
                         ('gguf', '0.19.0', '>=3.10'))
        self.assertEqual(facts['dependencies'], ['numpy'], "une exigence d'extra n'est pas une dépendance")
        self.assertTrue(seen[0].endswith('/pypi/gguf/json'), seen)
        self.assertIn('numpy>=1.17', facts['text'])
        self.assertIsNone(self.role_utils.pypi_metadata('gguf', fetcher=lambda url: 1 / 0))
        self.assertIsNone(self.role_utils.pypi_metadata(
            'gguf', fetcher=lambda url: json.dumps({'info': {'name': 'gguf'}})))

    def test_a_reply_cut_by_the_proxy_is_read_again(self):
        """Mesuré le 2026-11-06 : le proxy coupe la fiche (`IncompleteRead`), la suivante passe."""
        import http.client
        replies = [http.client.IncompleteRead(b'{"info"', 7439),
                   json.dumps({'info': {'name': 'gguf', 'version': '0.19.0'}})]

        def fetcher(url):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        self.assertEqual(self.role_utils.pypi_metadata('gguf', fetcher=fetcher)['version'], '0.19.0')

        def always_cut(url):
            raise http.client.IncompleteRead(b'{', 10)
        self.assertIsNone(self.role_utils.pypi_metadata('gguf', fetcher=always_cut))

    def test_a_published_distribution_is_pinned_by_pypi_not_by_the_llm(self):
        from wama.common.manifests.ingest import validate
        notes = []
        llm = {**self._llm_manifest({'pip': 'gguf>=0.10', 'requires_python': '>=3.8'}),
               'key': 'gguf', 'name': 'gguf'}
        llm['body']['dependencies'] = ['PySide6', 'numpy']
        published = {'name': 'gguf', 'version': '0.19.0', 'requires_python': '>=3.10',
                     'dependencies': ['numpy'], 'text': ''}
        manifest = self.role_utils.enforce_published_facts(llm, published, notes)
        self.assertEqual(manifest['body']['install'],
                         {'pip': 'gguf==0.19.0', 'requires_python': '>=3.10'},
                         "les deux faits publiés, aucun du LLM")
        self.assertEqual(manifest['body']['dependencies'], ['numpy'], "l'extra du LLM est retiré")
        self.assertEqual(manifest['source'], {'type': 'extract', 'ref': 'pypi:gguf==0.19.0'},
                         "lu sur PyPI : une extraction, qui ne ferait pas foi contre la ré-extraction")
        self.assertEqual(manifest['body']['identity']['version'], '0.19.0')
        self.assertEqual(llm['body']['install'], {'pip': 'gguf>=0.10', 'requires_python': '>=3.8'},
                         "l'entrée n'est pas mutée")
        self.assertTrue(any('PyPI' in n for n in notes), notes)
        self.assertEqual(validate(manifest) or [], [])

    def test_requirements_are_confronted_to_the_reference_venv(self):
        venv = {'transformers': '4.57.6', 'numpy': '2.3.5', 'torch': '2.9.1', 'accelerate': '1.6.0'}
        lines = self.role_utils.repo_requirements({
            'requirements.txt': 'transformers>=5.0  # ACE-Step\nnumpy\n-e .\naccelerate==1.13.0\n',
            'pyproject.toml': '[project]\ndependencies = ["torch>=2.4", "vector-quantize-pytorch",'
                              ' "pywin32; sys_platform == \'win32\'"]\n'})
        verdict = self.role_utils.requirements_verdict(lines, installed=venv)
        self.assertEqual([{'requirement': 'transformers>=5.0', 'installed': '4.57.6'}],
                         verdict['conflicts'])
        self.assertEqual([{'requirement': 'accelerate==1.13.0', 'installed': '1.6.0'}],
                         verdict['pinned'], "une épingle exacte d'amont n'est pas un conflit de borne")
        self.assertEqual(['vector-quantize-pytorch'], verdict['missing'])
        self.assertEqual({'numpy', 'torch'}, set(verdict['satisfied']),
                         'une exigence d\'une AUTRE plateforme (pywin32) ne compte pas')

    def test_the_envelope_constants_are_filled_never_overwritten(self):
        from wama.common.manifests.ingest import validate
        manifest = self._llm_manifest({'pip': 'x==1'})
        for key in ('name', 'world', 'visibility'):
            manifest.pop(key)
        manifest['description'] = 'kept'
        notes = []
        self.role_utils.complete_library_envelope(manifest, 'MeiGen-AI/InfiniteTalk', notes)
        self.assertEqual(('InfiniteTalk', 'transverse', 'public'),
                         (manifest['name'], manifest['world'], manifest['visibility']))
        self.assertEqual('kept', manifest['description'])
        self.assertEqual(validate(manifest) or [], [])

    def test_an_unmeasured_head_is_said_not_invented(self):
        notes = []
        manifest = self.role_utils.enforce_install_channel(
            self._llm_manifest({'pip': 'musetalk==1.5'}), 'TMElyralab/MuseTalk', [], None, notes)
        self.assertEqual(manifest['body']['install'], {'pip': 'musetalk==1.5'})
        self.assertTrue(any('non mesurée' in n for n in notes), notes)

    def test_engine_name_and_head_sha(self):
        self.assertEqual(self.role_utils.vendor_engine_name('VAST-AI-Research/TripoSR'), 'triposr')
        self.assertEqual(self.role_utils.vendor_engine_name('org/3DTalk'), 'engine_3dtalk')
        seen = []
        sha = self.role_utils.github_head_sha(
            'TMElyralab/MuseTalk', 'main',
            fetcher=lambda url: seen.append(url) or '{"sha": "%s"}' % self.SHA)
        self.assertEqual(sha, self.SHA)
        self.assertTrue(seen[0].endswith('/repos/TMElyralab/MuseTalk/commits/main'), seen)


class VendorEngineFromSourcesTest(SimpleTestCase):
    """Un modèle servi par un moteur VENDORISÉ : moteur et composants posés par les FAITS.

    Cas réel du 2026-10-01 : YuE2-3B, composition rendue VIDE par le rôle alors que son README
    cite le dépôt vendorisé et que le code vendorisé nomme ses dépôts par défaut."""

    LIBS = [{'key': 'yue', 'repo': 'multimodal-art-projection/YuE', 'engine': 'yue'},
            {'key': 'musetalk', 'repo': 'TMElyralab/MuseTalk', 'engine': 'musetalk'}]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        src = self.root / 'yue' / 'src' / 'yue2'
        src.mkdir(parents=True)
        (src / 'pipeline.py').write_text(
            'class P:\n'
            '    @classmethod\n'
            '    def from_pretrained(cls, model="m-a-p/YuE2-3B", *, vae="m-a-p/YuE2-Vae",\n'
            '                        cache_dir=None):\n'
            '        pass\n', encoding='utf-8')
        (src / 'tokenizer.py').write_text(
            'def from_pretrained(path="someone/other-repo"):\n    pass\n', encoding='utf-8')
        tests = self.root / 'yue' / 'tests'
        tests.mkdir()
        (tests / 'test_x.py').write_text(
            'def from_pretrained(model="m-a-p/YuE2-3B", extra="x/should-not-count"):\n    pass\n',
            encoding='utf-8')

    def _enforce(self, sources, manifest=None):
        concerns = []
        manifest = manifest or {'body': {'composition': {}}}
        self.role_utils.enforce_vendor_engine(manifest, 'm-a-p/YuE2-3B', sources, concerns,
                                              libraries=self.LIBS, vendor_root=self.root)
        return manifest, concerns

    def test_a_cited_vendored_repo_gives_engine_and_components(self):
        manifest, _ = self._enforce('See https://github.com/multimodal-art-projection/YuE for code.')
        compo = manifest['body']['composition']
        self.assertEqual('yue', compo['runtime']['engine'])
        self.assertEqual([{'role': 'model', 'pattern': '*.safetensors'},
                          {'role': 'vae', 'repo': 'm-a-p/YuE2-Vae'}], compo['components'],
                         "le from_pretrained qui charge CE modèle, jamais un autre ni les tests")

    def test_no_citation_leaves_the_manifest_alone(self):
        """Contre-épreuve : sans citation d'un dépôt vendorisé, rien n'est posé."""
        manifest, concerns = self._enforce('github.com/some/unrelated-repo')
        self.assertEqual({}, manifest['body']['composition'])
        self.assertEqual([], concerns)

    def test_two_cited_engines_are_left_to_judgment(self):
        manifest, concerns = self._enforce('github.com/multimodal-art-projection/YuE and '
                                           'github.com/TMElyralab/MuseTalk')
        self.assertEqual({}, manifest['body']['composition'])
        self.assertTrue(any('PLUSIEURS' in c for c in concerns), concerns)

    def test_declared_components_are_kept(self):
        manifest = {'body': {'composition': {'components': [{'role': 'x', 'pattern': 'a.bin'}]}}}
        manifest, _ = self._enforce('github.com/multimodal-art-projection/YuE', manifest)
        self.assertEqual([{'role': 'x', 'pattern': 'a.bin'}],
                         manifest['body']['composition']['components'])

    def test_a_cited_repo_whose_code_does_not_load_the_model_sets_no_engine(self):
        """Cas réel du 2026-10-03 : la fiche de SheetSage2 cite le dépôt de YuE (même labo), mais
        le code de YuE ne charge pas SheetSage2 — le moteur `yue` lui avait été posé."""
        concerns = []
        manifest = {'body': {'composition': {}}}
        self.role_utils.enforce_vendor_engine(
            manifest, 'm-a-p/SheetSage2', 'github.com/multimodal-art-projection/YuE', concerns,
            libraries=self.LIBS, vendor_root=self.root)
        self.assertEqual({}, manifest['body']['composition'])
        self.assertTrue(any('NON posé' in c for c in concerns), concerns)

    def test_an_engine_naming_the_repo_by_a_module_constant_gets_its_engine(self):
        """2026-11-05, ACE-Step 1.5: its loader reads a checkpoint folder and names the repo by a
        module constant (`MAIN_MODEL_REPO`), not by a `from_pretrained` default — the role left
        the model without an engine. A constant naming ANOTHER repo, or one inside a function or a
        test, sets nothing (the SheetSage2 trap stays closed)."""
        libs = [{'key': 'ace_step_1_5', 'repo': 'ace-step/ACE-Step-1.5', 'engine': 'ace_step_1_5'}]
        src = self.root / 'ace_step_1_5' / 'acestep'
        src.mkdir(parents=True)
        (src / 'model_downloader.py').write_text(
            'MAIN_MODEL_REPO = "ACE-Step/Ace-Step1.5"\n'
            'OTHER = "someone/other-model"\n'
            'def f():\n    LOCAL = "m-a-p/SheetSage2"\n', encoding='utf-8')
        (src / 'downloader_test.py').write_text('REPO = "m-a-p/SheetSage2"\n', encoding='utf-8')
        for repo_id, engine in (('ACE-Step/Ace-Step1.5', 'ace_step_1_5'), ('m-a-p/SheetSage2', None)):
            concerns = []
            manifest = {'body': {'composition': {'components': [{'role': 'vae', 'pattern': 'vae/*'}]}}}
            self.role_utils.enforce_vendor_engine(manifest, repo_id, 'github.com/ace-step/ACE-Step-1.5',
                                                  concerns, libraries=libs, vendor_root=self.root)
            compo = manifest['body']['composition']
            self.assertEqual(engine, (compo.get('runtime') or {}).get('engine'), repo_id)
            self.assertEqual([{'role': 'vae', 'pattern': 'vae/*'}], compo['components'],
                             'a constant names the repo, not its roles: components are kept')

    def test_an_engine_naming_the_repo_in_a_module_table_gets_its_engine(self):
        """2026-11-10, ACE-Step SFT: the engine names its variants as VALUES of a module table
        (`SUBMODEL_REGISTRY`), not as constants — the SFT had no engine. A table naming another
        repo, or a table inside a function, sets nothing."""
        src = self.root / 'ace_step_1_5' / 'acestep'
        src.mkdir(parents=True)
        (src / 'model_downloader.py').write_text(
            'SUBMODEL_REGISTRY: dict = {"acestep-v15-sft": "ACE-Step/acestep-v15-sft",\n'
            '                           "other": "someone/other-model"}\n'
            'def f():\n    LOCAL = {"x": "m-a-p/SheetSage2"}\n', encoding='utf-8')
        self.assertEqual(['acestep/model_downloader.py:SUBMODEL_REGISTRY[acestep-v15-sft]'],
                         self.role_utils.vendor_names_repo(self.root / 'ace_step_1_5',
                                                           'ACE-Step/acestep-v15-sft'))
        self.assertEqual([], self.role_utils.vendor_names_repo(self.root / 'ace_step_1_5',
                                                               'm-a-p/SheetSage2'))


class BackboneFromEngineSiblingsTest(SimpleTestCase):
    """Une VARIANTE qui ne porte qu'une partie de l'anatomie de son moteur (2026-11-10, Fabien :
    « Dorsale ») : ses rôles prennent le nom que la ligne du même moteur donne au même poids, et la
    seule ligne installée qui couvre ce qui manque devient sa dorsale (`identity.base_model`).

    Cas réel : `ACE-Step/acestep-v15-sft` ne publie que son DiT ; le rôle l'avait nommé `dit` et la
    proposition n'avait ni VAE, ni encodeur, ni modèle de langage."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def setUp(self):
        import json
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

        def folder(root, rel, arch):
            (root / rel).mkdir(parents=True, exist_ok=True)
            (root / rel / 'model.safetensors').write_bytes(b'0')
            if arch:
                (root / rel / 'config.json').write_text(json.dumps({'architectures': [arch]}))

        self.main = self.tmp / 'main'
        for rel, arch in (('acestep-v15-turbo', 'AceStepConditionGenerationModel'),
                          ('acestep-5Hz-lm-1.7B', 'Qwen3Model'), ('Qwen3-Embedding-0.6B', 'Qwen3Model'),
                          ('vae', None)):
            folder(self.main, rel, arch)
        self.sft = self.tmp / 'sft'
        folder(self.sft, '.', 'AceStepConditionGenerationModel')
        self.main_components = [
            {'role': 'diffusion_transformer', 'pattern': 'acestep-v15-turbo/model.safetensors'},
            {'role': 'language_model', 'pattern': 'acestep-5Hz-lm-1.7B/model.safetensors'},
            {'role': 'Qwen3-Embedding-0.6B', 'pattern': 'Qwen3-Embedding-0.6B/model.safetensors'},
            {'role': 'vae', 'pattern': 'vae/model.safetensors'}]

    def _manifest(self, role='dit'):
        return {'key': 'huggingface:ACE-Step/acestep-v15-sft', 'body': {'composition': {
            'runtime': {'engine': 'ace_step_1_5'},
            'components': [{'role': role, 'pattern': 'model.safetensors'}]}}}

    def _enforce(self, manifest, siblings):
        concerns = []
        self.role_utils.enforce_backbone_from_siblings(manifest, self.sft, concerns, siblings=siblings)
        return manifest, concerns

    def test_the_role_is_aligned_and_the_backbone_is_posed(self):
        sibling = ('huggingface:ACE-Step/Ace-Step1.5', 'ACE-Step/Ace-Step1.5', self.main,
                   self.main_components)
        manifest, concerns = self._enforce(self._manifest(), [sibling])
        body = manifest['body']
        self.assertEqual([{'role': 'diffusion_transformer', 'pattern': 'model.safetensors'}],
                         body['composition']['components'])
        self.assertEqual({'base_model': 'ACE-Step/Ace-Step1.5', 'base_model_relation': 'finetune'},
                         body['identity'])
        self.assertEqual(2, len(concerns), concerns)

    def test_an_architecture_shared_by_two_roles_renames_nothing(self):
        """Contre-épreuve : le modèle de langage et l'encodeur sont tous deux des `Qwen3Model` —
        une correspondance non UNIQUE ne renomme rien."""
        (self.sft / 'config.json').write_text('{"architectures": ["Qwen3Model"]}')
        sibling = ('k', 'ACE-Step/Ace-Step1.5', self.main, self.main_components)
        manifest, _ = self._enforce(self._manifest('encoder'), [sibling])
        self.assertEqual('encoder', manifest['body']['composition']['components'][0]['role'])

    def test_sharded_weights_of_the_same_architecture_take_the_role(self):
        """La XL-SFT (2026-11-11) : DiT en quatre morceaux, même architecture que le DiT de la
        sœur — le rôle s'aligne ; un morceau `Qwen3Model` (deux rôles chez la sœur) ne bouge pas."""
        (self.sft / 'model.safetensors').unlink()
        (self.sft / 'model-00001-of-00004.safetensors').write_bytes(b'0')
        sibling = ('k', 'ACE-Step/Ace-Step1.5', self.main, self.main_components)
        manifest = self._manifest()
        manifest['body']['composition']['components'] = [
            {'role': 'transformer', 'pattern': 'model-*.safetensors'}]
        manifest, _ = self._enforce(manifest, [sibling])
        self.assertEqual('diffusion_transformer', manifest['body']['composition']['components'][0]['role'])
        (self.sft / 'config.json').write_text('{"architectures": ["Qwen3Model"]}')
        manifest = self._manifest('encoder')
        manifest['body']['composition']['components'] = [
            {'role': 'encoder', 'pattern': 'model-*.safetensors'}]
        manifest, _ = self._enforce(manifest, [sibling])
        self.assertEqual('encoder', manifest['body']['composition']['components'][0]['role'])

    def test_two_covering_lines_leave_the_backbone_to_judgment(self):
        siblings = [('a', 'org/a', self.main, self.main_components),
                    ('b', 'org/b', self.main, self.main_components)]
        manifest, concerns = self._enforce(self._manifest(), siblings)
        self.assertNotIn('base_model', manifest['body'].get('identity') or {})
        self.assertTrue(any('PLUSIEURS' in c for c in concerns), concerns)

    def test_a_complete_line_gets_no_backbone(self):
        """Contre-épreuve : une ligne qui porte déjà tous les rôles de sa sœur n'en hérite pas."""
        manifest = {'key': 'k2', 'body': {'composition': {'runtime': {'engine': 'ace_step_1_5'},
                                                          'components': list(self.main_components)}}}
        concerns = []
        self.role_utils.enforce_backbone_from_siblings(
            manifest, self.main, concerns, siblings=[('k', 'org/k', self.main, self.main_components)])
        self.assertNotIn('identity', manifest['body'])
        self.assertEqual([], concerns)


class AdapterParentTest(SimpleTestCase):
    """Le parent d'un ADAPTATEUR entre dans l'anatomie (2026-10-03, SheetSage2 → MERT)."""

    CONFIG = {'base_model_name_or_path': 'm-a-p/MERT-v2-FullSong', 'base_model_revision': 'd8ba1c7' * 6}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def _enforce(self, manifest, config):
        concerns = []
        self.role_utils.enforce_adapter_parent(manifest, 'm-a-p/SheetSage2', concerns,
                                               loader=lambda: config)
        return manifest, concerns

    def test_the_parent_named_by_the_config_becomes_a_repo_component(self):
        manifest = {'body': {'composition': {'components': [
            {'role': 'model', 'pattern': 'model.safetensors'}]}}}
        manifest, concerns = self._enforce(manifest, self.CONFIG)
        self.assertEqual([{'role': 'model', 'pattern': 'model.safetensors'},
                          {'role': 'base', 'repo': 'm-a-p/MERT-v2-FullSong'}],
                         manifest['body']['composition']['components'])
        self.assertTrue(any('MERT-v2-FullSong' in c for c in concerns), concerns)

    def test_an_already_declared_parent_is_not_added_twice(self):
        manifest = {'body': {'composition': {'components': [
            {'role': 'encoder', 'repo': 'm-a-p/MERT-v2-FullSong'}]}}}
        manifest, concerns = self._enforce(manifest, self.CONFIG)
        self.assertEqual(1, len(manifest['body']['composition']['components']))
        self.assertEqual([], concerns)

    def test_a_config_without_a_parent_changes_nothing(self):
        """Contre-épreuve : un config.json ordinaire (architectures seules) ne pose rien."""
        manifest = {'body': {'composition': {}}}
        manifest, concerns = self._enforce(manifest, {'architectures': ['WhisperForConditionalGeneration']})
        self.assertEqual({}, manifest['body']['composition'])
        self.assertEqual([], concerns)


class RoleGpuGuardTest(SimpleTestCase):
    """La garde GPU COMMUNE des rôles et de l'audit (`role_utils.local_llm_guard`, 2026-10-13).

    Elle vivait dans le seul rôle `model`, avec un besoin VRAM lu dans `config.py` ; l'audit,
    lui, déchargeait TOUT Ollama au début et à la fin de chaque run. Ce qui est gardé : la règle
    du gouverneur (on attend en mode dépannage ; on ne libère que sur ACCORD), le besoin lu au
    CATALOGUE, et aucune sonde quand rien n'est à décider."""

    GOV = 'wama.common.services.resource_governor'

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def _guard(self, *, safe=True, need=12.0, free=20.0, wait=(True, 20.0), **kw):
        from unittest.mock import patch
        self.logs = []
        with patch(f'{self.GOV}.gpu_safe_mode', return_value=safe), \
                patch(f'{self.GOV}.effective_free_gb', return_value=free) as probe, \
                patch(f'{self.GOV}.wait_for_free_vram', return_value=wait) as waiting, \
                patch(f'{self.GOV}.obtain_vram', return_value=(True, 30.0)) as obtain, \
                patch(f'{self.GOV}.holders_summary', return_value='résidents : x (9 Go)'), \
                patch('wama.common.utils.auto_model.vram_needed_gb', return_value=need) as needed:
            self.result = self.role_utils.local_llm_guard(kw.pop('provider', 'ollama'),
                                                          'big:8b', log=self.logs.append, **kw)
        return probe, waiting, obtain, needed

    def test_a_remote_provider_is_not_guarded_and_nothing_is_probed(self):
        probe, waiting, obtain, _ = self._guard(provider='albert')
        self.assertIsNone(self.result)
        for call in (probe, waiting, obtain):
            call.assert_not_called()

    def test_out_of_safe_mode_nothing_is_probed_nor_awaited(self):
        probe, waiting, obtain, needed = self._guard(safe=False)
        self.assertIsNone(self.result, "keep_alive nominal : le défaut d'Ollama")
        for call in (probe, waiting, obtain, needed):
            call.assert_not_called()

    def test_in_safe_mode_the_role_waits_for_the_need_read_in_the_catalogue(self):
        _, waiting, obtain, needed = self._guard()
        needed.assert_called_once_with('ollama:big:8b')
        self.assertEqual(12.0, waiting.call_args.args[0])
        obtain.assert_not_called()
        self.assertEqual('0', self.result, 'déchargement sitôt la réponse rendue')

    def test_an_unknown_need_is_said_and_not_awaited(self):
        _, waiting, _, _ = self._guard(need=None)
        waiting.assert_not_called()
        self.assertTrue(any('inconnu au catalogue' in m for m in self.logs), self.logs)

    def test_a_wait_that_runs_out_refuses_and_says_who_holds_the_card(self):
        with self.assertRaises(SystemExit) as raised:
            self._guard(wait=(False, 4.0))
        self.assertIn('résidents : x', str(raised.exception))

    def test_force_skips_the_wait_never_the_keep_alive(self):
        _, waiting, _, _ = self._guard(force=True)
        waiting.assert_not_called()
        self.assertEqual('0', self.result)

    def test_freeing_the_card_needs_the_explicit_consent(self):
        _, _, obtain, _ = self._guard(safe=False, free=4.0)
        obtain.assert_not_called()
        _, waiting, obtain, _ = self._guard(safe=False, free=4.0, release_reason='audit')
        obtain.assert_called_once()
        self.assertEqual('audit', obtain.call_args.kwargs['reason'])
        waiting.assert_not_called()

    def test_consent_is_not_used_when_the_model_already_fits(self):
        _, _, obtain, _ = self._guard(safe=False, free=20.0, release_reason='audit')
        obtain.assert_not_called()


class RolesFollowTheCommonRouteTest(SimpleTestCase):
    """Gardes de STRUCTURE, faute de pouvoir exécuter un rôle sans modèle : chaque rôle qui appelle
    un modèle passe par la garde commune, aucun rôle ne retire son modèle par la chaîne de
    `config.py`, et l'audit ne décharge plus que SON modèle."""

    def _roles_calling_a_model(self):
        return sorted(p.name for p in DEV_AI.glob('run_*.py')
                      if 'call_llm(' in p.read_text(encoding='utf-8'))

    def test_every_role_calling_a_model_applies_the_gpu_guard(self):
        roles = self._roles_calling_a_model()
        self.assertEqual(8, len(roles), f"garde d'instrument : {roles}")
        for name in roles:
            source = (DEV_AI / name).read_text(encoding='utf-8')
            with self.subTest(role=name):
                self.assertIn('local_llm_guard(', source)
                # L'APPEL ne suffit pas : `run_codegen.py` appelait la garde sans l'importer
                # (relevé le 2026-10-15 par l'assistant) — `NameError` au premier lancement, que
                # cette garde, qui ne lisait que le texte, laissait passer.
                imported = {alias.asname or alias.name
                            for node in ast.walk(ast.parse(source))
                            if isinstance(node, ast.ImportFrom) and node.module == 'role_utils'
                            for alias in node.names}
                self.assertIn('local_llm_guard', imported,
                              f"{name} appelle local_llm_guard sans l'importer de role_utils")
                self.assertEqual(source.count('call_llm('),
                                 source.count('keep_alive=keep_alive'),
                                 f"{name} : un appel au modèle ignore le keep_alive de la garde")

    def test_no_role_draws_its_model_from_the_config_chain(self):
        for name in self._roles_calling_a_model():
            with self.subTest(role=name):
                self.assertNotIn('select_model_for_role', self._code_only(DEV_AI / name))

    @staticmethod
    def _code_only(path):
        """Le source SANS ses commentaires : l'audit raconte, en commentaire, les gestes retirés
        — c'est le code qu'on garde, pas le récit."""
        import io
        import tokenize
        tokens = tokenize.generate_tokens(io.StringIO(path.read_text(encoding='utf-8')).readline)
        return tokenize.untokenize((t.type, t.string) for t in tokens if t.type != tokenize.COMMENT)

    def test_the_audit_no_longer_unloads_the_others(self):
        code = self._code_only(DEV_AI / 'run_audit.py')
        for gesture in ('/api/ps', 'clear-gpu', 'getpass', 'WAMA_PASSWORD'):
            with self.subTest(gesture=gesture):
                self.assertNotIn(gesture, code)
        source = (DEV_AI / 'run_audit.py').read_text(encoding='utf-8')
        self.assertIn('MemoryManager.unload_model(', source)
        self.assertIn('local_llm_guard(', source)


class FournisseurDesRolesTest(SimpleTestCase):
    """`role_utils.call_llm` (2026-09-15, Albert API) : les rôles choisissent leur fournisseur.

    ⚠ Le chemin `ollama` doit rester `call_ollama` à l'identique — keep_alive compris, c'est la
    parade du mode dépannage GPU. Le chemin distant doit passer par `llm_chat`, seule brique
    qui sait router vers Albert : une seconde construction d'appel ici divergerait.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def test_the_call_options_override_the_role_s_and_zero_lifts_the_timeout(self):
        """Two rules of WAMA cut the `backend` role on a local model (2026-11-10): the 30 min wait,
        then the 32 768-token window (26 631 tokens of request, « truncated » in Ollama's log) —
        relevable by `--llm-timeout` (0 removes it) and `--num-ctx`."""
        import argparse
        from unittest.mock import patch
        role_utils = self.role_utils
        self.addCleanup(role_utils.LLM_OVERRIDES.clear)
        cases = (([], 1800, 32768), (['--llm-timeout', '7200'], 7200, 32768),
                 (['--llm-timeout', '0'], None, 32768), (['--num-ctx', '65536'], 1800, 65536))
        for argv, timeout, num_ctx in cases:
            with self.subTest(argv=argv):
                role_utils.LLM_OVERRIDES.clear()
                parser = argparse.ArgumentParser()
                role_utils.add_llm_arguments(parser)
                parser.parse_args(argv)
                with patch.object(role_utils, 'call_ollama', return_value='OK') as direct:
                    role_utils.call_llm('ollama', 'm', 'sys', 'msg', timeout=1800, num_ctx=32768)
                self.assertEqual(timeout, direct.call_args.kwargs['timeout'])
                self.assertEqual(num_ctx, direct.call_args.kwargs['num_ctx'])
        for wrong in (['--num-ctx', '0'], ['--llm-timeout', '-1']):
            with self.subTest(wrong=wrong), self.assertRaises(SystemExit), \
                    patch('sys.stderr'):
                parser = argparse.ArgumentParser()
                role_utils.add_llm_arguments(parser)
                parser.parse_args(wrong)

    def test_ollama_reste_call_ollama_a_l_identique(self):
        from unittest.mock import patch
        with patch.object(self.role_utils, 'call_ollama', return_value='OK') as direct:
            self.role_utils.call_llm('ollama', 'gemma4:e4b', 'sys', 'msg', keep_alive='0')
        direct.assert_called_once()
        self.assertEqual('0', direct.call_args.kwargs['keep_alive'])

    def test_the_local_call_goes_through_the_common_brick_with_the_same_values(self):
        """`call_ollama` passe par la brique de l'assistant (`llm_chat`, fournisseur `ollama`,
        2026-10-20) : fenêtre, résidence, température et délai transmis, aucun plafond de jetons,
        et un échec LÈVE comme avant."""
        from unittest.mock import patch
        with patch('wama.common.utils.llm_utils.llm_chat', return_value=('OK', None)) as chat:
            self.assertEqual('OK', self.role_utils.call_ollama(
                'gemma4:e4b', 'sys', 'msg', num_ctx=32768, keep_alive='0', temperature=0.2,
                timeout=900))
        kwargs = chat.call_args.kwargs
        self.assertEqual(('ollama', 'gemma4:e4b', 32768, '0', 0.2, 900, None),
                         (kwargs['provider'], kwargs['model'], kwargs['num_ctx'],
                          kwargs['keep_alive'], kwargs['temperature'], kwargs['timeout'],
                          kwargs['num_predict']))
        with patch('wama.common.utils.llm_utils.llm_chat', return_value=(None, 'HTTP 500')):
            with self.assertRaises(RuntimeError):
                self.role_utils.call_ollama('gemma4:e4b', 'sys', 'msg')

    def test_un_fournisseur_distant_passe_par_llm_chat_sans_plafond(self):
        from unittest.mock import patch
        with patch('wama.common.utils.llm_utils.llm_chat', return_value=('OK', None)) as chat, \
                patch.object(self.role_utils, 'call_ollama') as direct:
            self.assertEqual('OK', self.role_utils.call_llm('albert', 'm', 'sys', 'msg'))
        self.assertFalse(direct.called)
        kwargs = chat.call_args.kwargs
        self.assertEqual('albert', kwargs['provider'])
        self.assertIsNone(kwargs['num_predict'], "un manifeste tronqué à 2 048 jetons est illisible")
        self.assertEqual(['system', 'user'], [m['role'] for m in chat.call_args.args[0]])

    def test_un_echec_distant_LEVE_comme_un_echec_ollama(self):
        """Les pilotes font `extract_json(call_llm(...))` : un None avalé deviendrait
        « aucun JSON dans la réponse », qui accuse le modèle au lieu de la clé absente."""
        from unittest.mock import patch
        with patch('wama.common.utils.llm_utils.llm_chat',
                   return_value=(None, 'clé absente : ALBERT_API_KEY')):
            with self.assertRaises(RuntimeError) as ctx:
                self.role_utils.call_llm('albert', 'm', 'sys', 'msg')
        self.assertIn('ALBERT_API_KEY', str(ctx.exception))

    def test_le_modele_distant_par_defaut_est_nomme_pour_le_rapport(self):
        from wama.common.utils.llm_utils import default_cloud_model
        self.assertEqual(default_cloud_model('albert'),
                         self.role_utils.resolve_model('albert', 'codegen'))
        self.assertEqual('choisi', self.role_utils.resolve_model('albert', 'codegen', 'choisi'))

    def test_la_variable_d_environnement_bascule_tous_les_roles(self):
        import argparse
        from unittest.mock import patch
        with patch.dict('os.environ', {'WAMA_DEV_AI_PROVIDER': 'albert'}):
            parser = argparse.ArgumentParser()
            self.role_utils.add_llm_arguments(parser)
            self.assertEqual('albert', parser.parse_args([]).provider)
        with patch.dict('os.environ', {}, clear=True):
            parser = argparse.ArgumentParser()
            self.role_utils.add_llm_arguments(parser)
            self.assertEqual('ollama', parser.parse_args([]).provider,
                             "sans variable, les rôles restent en local comme avant")


class ModelRoleTakesOneRepriseOnTheVerdictTest(SimpleTestCase):
    """Le rôle `model` juge sa sortie comme « Valider » la jugera, et se reprend UNE fois.

    Vécu le 2026-11-07 (ACE-Step 1.5, intégré par l'assistant) : le rôle se disait « VALIDE »
    d'une anatomie qui oubliait l'encodeur de texte ; « Valider » la refusait, et la chaîne
    s'arrêtait dans la file sur un défaut que le contrôle avait déjà nommé."""

    KEY = 'huggingface:Org/Composed'
    VERDICT = "anatomie incomplète : 1 poids (text_encoder/model.safetensors)"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role = _charger('run_model_manifest')

    def _run(self, answers, verdicts):
        from types import SimpleNamespace
        from unittest import mock
        role = self.role
        calls, written, proposed = [], {}, []

        def llm(provider, model, system, user_msg, **kw):
            calls.append(user_msg)
            return json.dumps(answers[len(calls) - 1])

        def output(_role, _slug, payload):
            written.update(payload)
            return role.REPO_ROOT / 'wama-dev-ai' / 'outputs' / 'model_test.json'

        def propose(manifest, origin=''):
            proposed.append(manifest)
            return SimpleNamespace(manifest_kind='model', key=self.KEY, errors=[])

        argv = ['run_model_manifest.py', '--catalog', self.KEY, '--provider', 'ilaas', '--model', 'm']
        with mock.patch.object(sys, 'argv', argv),                 mock.patch.object(role, 'sources_catalog', return_value=('snapshot:/x', 'SRC')),                 mock.patch.object(role, 'resolve_model', return_value='m'),                 mock.patch.object(role, 'local_llm_guard', return_value=None),                 mock.patch.object(role, 'exemples', return_value=''),                 mock.patch.object(role, 'model_vocabularies', return_value=''),                 mock.patch.object(role, 'enforce_facts', return_value=[]),                 mock.patch.object(role, 'call_llm', side_effect=llm),                 mock.patch.object(role, 'write_output', side_effect=output),                 mock.patch('wama.common.manifests.builtin.model.extract_model', return_value=None),                 mock.patch('wama.common.manifests.proposals.propose', side_effect=propose),                 mock.patch('wama.common.manifests.proposals.judge',
                           side_effect=lambda m: list(verdicts[m['name']])),                 mock.patch('builtins.print'):
            role.main()
        return calls, written, proposed

    def _manifest(self, name):
        return {'manifest_kind': 'model', 'key': self.KEY, 'name': name, 'body': {}}

    def test_a_refused_anatomy_is_handed_back_once_and_the_complete_one_is_proposed(self):
        calls, written, proposed = self._run(
            [self._manifest('first'), self._manifest('second')],
            {'first': [self.VERDICT], 'second': []})
        self.assertEqual(2, len(calls))
        self.assertIn(self.VERDICT, calls[1], "the reprise must carry the verdict word for word")
        self.assertEqual(['second'], [m['name'] for m in proposed])
        self.assertEqual([], written['validation_errors'])

    def test_a_reprise_no_less_refused_keeps_the_first_answer_with_its_verdict(self):
        calls, written, proposed = self._run(
            [self._manifest('first'), self._manifest('second')],
            {'first': [self.VERDICT], 'second': [self.VERDICT]})
        self.assertEqual(['first'], [m['name'] for m in proposed])
        self.assertEqual([self.VERDICT], written['validation_errors'],
                         "the output must say what Validate will refuse, never VALID")

    def test_an_accepted_answer_costs_a_single_call(self):
        calls, written, _ = self._run([self._manifest('first')], {'first': []})
        self.assertEqual(1, len(calls))
        self.assertEqual([], written['validation_errors'])


class EngineReadAnatomyIsAFactTest(SimpleTestCase):
    """Ce que le juge de « Valider » établit sur l'anatomie, le rôle le pose (2026-11-07).

    ACE-Step 1.5 : refusé pour avoir oublié son encodeur de texte, le rôle l'a ÉCARTÉ avec
    `silence_latent.pt` et vingt configurations, puis n'a pas su se reprendre. Le code vendorisé
    nomme les deux poids : ce sont des composants ; une exclusion sans poids tombe ; l'exclusion
    d'un AUTRE modèle du dépôt, que le code ne nomme pas, reste."""

    INVENTORY = [('acestep-5Hz-lm-1.7B/model.safetensors', 1), ('acestep-v15-turbo/model.safetensors', 1),
                 ('acestep-v15-turbo/silence_latent.pt', 1), ('acestep-v15-turbo/config.json', 1),
                 ('Qwen3-Embedding-0.6B/model.safetensors', 1), ('README.md', 1),
                 ('alt/model.safetensors', 1)]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def test_the_weights_the_engine_reads_become_components(self):
        import shutil
        import tempfile
        from wama.model_manager.services import model_installer, vendor_installer
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / 'probe_engine').mkdir()
        # La forme du chargeur réel (`init_service_loader_components.py:90`,
        # `init_service_loader.py:211`).
        (root / 'probe_engine' / 'loader.py').write_text(
            'import os\n'
            'text_encoder_path = os.path.join(checkpoint_dir, "Qwen3-Embedding-0.6B")\n'
            'silence_latent_path = os.path.join(model_checkpoint_path, "silence_latent.pt")\n',
            encoding='utf-8')
        self.addCleanup(vendor_installer._code_names.cache_clear)
        manifest = {'body': {'composition': {
            'components': [{'role': 'lm', 'pattern': 'acestep-5Hz-lm-1.7B/model.safetensors'},
                           {'role': 'dit', 'pattern': 'acestep-v15-turbo/model.safetensors'}],
            'excluded': [{'pattern': 'Qwen3-Embedding-0.6B/model.safetensors', 'reason': 'not used'},
                         {'pattern': 'acestep-v15-turbo/silence_latent.pt', 'reason': 'buffer'},
                         {'pattern': 'README.md', 'reason': 'doc'},
                         {'pattern': 'alt/*', 'reason': 'another model'}],
            'runtime': {'engine': 'probe_engine'}}}}
        concerns = []
        with self.settings(BACKEND_VENDOR_DIR=str(root)):
            vendor_installer._code_names.cache_clear()
            self.role_utils.enforce_engine_read_anatomy(manifest, self.INVENTORY, concerns)
            compo = manifest['body']['composition']
            self.assertEqual({}, model_installer.anatomy_gaps(self.INVENTORY, compo))
        self.assertIn({'role': 'Qwen3-Embedding-0.6B',
                       'pattern': 'Qwen3-Embedding-0.6B/model.safetensors'}, compo['components'])
        self.assertIn({'role': 'silence_latent', 'pattern': 'acestep-v15-turbo/silence_latent.pt'},
                      compo['components'])
        self.assertEqual(['alt/*'], [e['pattern'] for e in compo['excluded']])
        self.assertEqual(3, len(concerns), concerns)

    def test_without_a_declared_anatomy_nothing_is_posed(self):
        manifest = {'body': {'composition': {'runtime': {'engine': 'probe_engine'}}}}
        self.role_utils.enforce_engine_read_anatomy(manifest, self.INVENTORY, [])
        self.assertNotIn('components', manifest['body']['composition'])


class RoleOutputNameIsReadableEverywhereTest(SimpleTestCase):
    """Le nom d'une sortie de rôle suit l'assainissement des clés du corpus (2026-11-08) : la clé
    de catalogue y gardait son `:`, et 41 sorties `model_huggingface:…` étaient illisibles depuis
    Windows, où `:` est interdit dans un nom de fichier."""

    def test_a_catalogue_key_is_named_as_the_corpus_names_it(self):
        import tempfile
        from unittest import mock
        role_utils = _charger('role_utils')
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(role_utils, 'OUTPUTS', Path(folder)), \
                mock.patch.object(role_utils, 'RELAYS', []):
            out = role_utils.write_output('model', 'huggingface:ACE-Step/Ace-Step1.5', {})
            composed = role_utils.write_output('codegen', 'reader__ocr', {})
        self.assertTrue(out.name.startswith('model_huggingface__ACE-Step~Ace-Step1.5_'), out.name)
        self.assertNotIn(':', out.name)
        self.assertTrue(composed.name.startswith('codegen_reader__ocr_'), composed.name)


class ProposalCarriesOnlyWhatItOwnsTest(SimpleTestCase):
    """2026-11-07 (ACE-Step) : trois divergences à chaque proposition du rôle `model`, jamais
    appliquées — `resources` à 0, la description réécrite face à la fiche du catalogue, et
    `["text", "audio"]` pour un `text-to-music` dont la tâche dit `("audio",)`. Du bruit au plan,
    qui noyait ce qui compte."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role_utils = _charger('role_utils')

    def test_modalities_are_the_media_the_task_treats(self):
        manifest = {'body': {'capabilities': {'task': 'text-to-music', 'modalities': ['text', 'audio']}}}
        concerns = []
        self.role_utils.enforce_modality_facts(manifest, concerns)
        self.assertEqual(['audio'], manifest['body']['capabilities']['modalities'])
        self.assertEqual(1, len(concerns))
        # Contre-épreuve : un sous-ensemble des médias de la tâche reste tel quel.
        detector = {'body': {'capabilities': {'task': 'detect', 'modalities': ['image']}}}
        self.role_utils.enforce_modality_facts(detector, [])
        self.assertEqual(['image'], detector['body']['capabilities']['modalities'])

    def test_measured_resources_and_card_descriptions_are_not_proposed(self):
        manifest = {'body': {'resources': {'vram_gb': 0, 'disk_gb': 0},
                             'identity': {'license': 'mit', 'description_short': 'Open-source music…'},
                             'capabilities': {'task': 'text-to-music'}}}
        concerns = []
        self.role_utils.enforce_owned_elsewhere(manifest, concerns)
        self.assertNotIn('resources', manifest['body'])
        self.assertEqual({'license': 'mit'}, manifest['body']['identity'])
        self.assertEqual(1, len(concerns))


class BackendRoleTakesOneRepriseOnItsChecksTest(SimpleTestCase):
    """Le rôle `backend` se reprend UNE fois sur le verdict de ses contrôles (2026-11-08).

    Vécu (ACE-Step 1.5, par l'assistant) : refusé pour trois défauts mécaniques — dont l'entrée du
    moteur qui télécharge elle-même —, le backend restait dans la file, refusé, sans que le rôle
    puisse se corriger. Même règle que le rôle `model` : le verdict mot pour mot, la reprise
    gardée seulement si elle est moins refusée."""

    KEY = 'huggingface:Org/Song'
    VERDICT = "appelle initialize_service (x.py:1) : le code du moteur « e » y télécharge lui-même"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role = _charger('run_backend')

    def _run(self, answers, verdicts, smokes=None):
        from types import SimpleNamespace
        from unittest import mock
        import wama.common.services.backend_proposals as bp
        role = self.role
        calls, written = [], {}

        def llm(provider, model, system, user_msg, **kw):
            calls.append(user_msg)
            return f"```python\n{answers[len(calls) - 1]}\n```"

        def output(_role, _slug, payload):
            written.update(payload)
            return role.REPO_ROOT / 'wama-dev-ai' / 'outputs' / 'backend_test.json'

        row = SimpleNamespace(model_key=self.KEY, capabilities={'task': 'text-to-music'}, hf_repo='Org/Song')
        manifest = {'body': {'composition': {'runtime': {'engine': 'e'},
                                             'components': [{'role': 'model', 'pattern': '*.pt'}]}}}
        argv = ['run_backend.py', '--catalog', self.KEY, '--provider', 'ilaas', '--model', 'm'] + (
            [] if smokes else ['--no-smoke'])
        with mock.patch.object(sys, 'argv', argv), \
                mock.patch('wama.model_manager.models.AIModel.objects') as objects, \
                mock.patch('wama.common.manifests.builtin.model.extract_model', return_value=manifest), \
                mock.patch.object(role, 'neighbours', return_value=[]), \
                mock.patch.object(role, 'model_material', return_value='SNAPSHOT'), \
                mock.patch.object(role, 'vendor_material', return_value=''), \
                mock.patch.object(role, 'base_excerpt', return_value=''), \
                mock.patch.object(role, '_read', return_value=''), \
                mock.patch.object(role, 'resolve_model', return_value='m'), \
                mock.patch.object(role, 'local_llm_guard', return_value=None), \
                mock.patch.object(role, 'call_llm', side_effect=llm), \
                mock.patch.object(role, 'write_output', side_effect=output), \
                mock.patch.object(bp, 'check_source', side_effect=lambda code, **kw: {
                    'ok': not verdicts[code.strip()], 'errors': list(verdicts[code.strip()]),
                    'warnings': []}), \
                mock.patch.object(bp, 'simulate_resolution', return_value={'resolved': True}), \
                mock.patch.object(bp, 'smoke', side_effect=lambda code, **kw: dict(
                    (smokes or {})[code.strip()])), \
                mock.patch('builtins.print'):
            objects.filter.return_value.first.return_value = row
            role.main()
        return calls, written

    def test_refused_checks_are_handed_back_once_and_the_corrected_module_is_proposed(self):
        calls, written = self._run(['first', 'second'], {'first': [self.VERDICT], 'second': []})
        self.assertEqual(2, len(calls))
        self.assertIn(self.VERDICT, calls[1], "the reprise must carry the verdict word for word")
        self.assertEqual('second', written['code'].strip())
        self.assertTrue(written['checks']['ok'])

    def test_a_reprise_no_less_refused_keeps_the_first_module_with_its_verdict(self):
        calls, written = self._run(['first', 'second'], {'first': [self.VERDICT], 'second': [self.VERDICT]})
        self.assertEqual('first', written['code'].strip())
        self.assertEqual([self.VERDICT], written['checks']['errors'])

    def test_an_accepted_module_costs_a_single_call(self):
        calls, written = self._run(['first'], {'first': []})
        self.assertEqual(1, len(calls))

    def test_the_material_says_how_each_component_file_climbs_to_the_weights_root(self):
        """`component_paths` gives a FILE per role; ACE-Step's loaders want folders. Two proposals
        of the same model climbed two levels (right) then one (`…/vae/vae`, missing at the trial)."""
        from unittest import mock
        root = Path('/w/snap')
        paths = {'vae': root / 'vae' / 'model.safetensors', 'tokenizer': root / 'tok.json',
                 'deep': root / 'a' / 'b' / 'c.bin'}
        with mock.patch('wama.common.utils.model_components.component_paths', return_value=paths):
            text = self.role.components_material('huggingface:Org/Song', root)
        self.assertIn("paths['vae'] = <racine>/vae/model.safetensors", text)
        self.assertIn("la racine des poids : paths['vae'].parents[1]", text)
        self.assertIn("la racine des poids : paths['tokenizer'].parent", text)
        self.assertIn("la racine des poids : paths['deep'].parents[2]", text)

    def test_every_loader_gets_its_share_of_the_budget_and_none_is_left_out(self):
        """In the compact material the budget was spent in calling order and the last loaders were
        left out — `_load_vae_model` among them, and the module passed `…/vae` (2026-11-10)."""
        import tempfile
        from unittest import mock

        from django.test import override_settings
        filler = ''.join(f'        step_{i} = {i}\n' for i in range(40))
        loaders = ''.join(
            f'    def _load_{name}(self, path):\n        """Loads {name} from <path>/{name}."""\n'
            f'{filler}        self.{name} = read(path + "/{name}")\n' for name in 'abc')
        source = ('from huggingface_hub import snapshot_download\n'
                  'class Mixin:\n'
                  '    def entry(self, path):\n        self._fetch(path)\n'
                  '        self._load_a(path)\n        self._load_b(path)\n        self._load_c(path)\n'
                  '    def _fetch(self, path):\n        snapshot_download("o/x", local_dir=path)\n'
                  + loaders)
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / 'eng' / 'pkg'
            package.mkdir(parents=True)
            (package / '__init__.py').write_text('', encoding='utf-8')
            (package / 'mod.py').write_text(source, encoding='utf-8')
            with override_settings(BACKEND_VENDOR_DIR=tmp), \
                    mock.patch.object(self.role, 'VENDOR_CHARS', 900):
                text = self.role.entry_loaders_material(Path(tmp) / 'eng', 'eng', 'entry', source)
        for name in 'abc':
            with self.subTest(loader=name):
                self.assertIn(f'----- _load_{name} ', text)
                self.assertIn(f'self.{name} = read(path + "/{name}")', text, 'what it joins to the path')
        self.assertNotIn('step_39', text, 'a loader past its share is served by its digest')

    def test_the_common_contract_excerpt_always_carries_its_abstract_methods(self):
        """They begin past the 22 000th character of `BaseModelBackend`: cut at 7 000, the excerpt
        never showed `load(...) -> bool`, and three modules wrote `-> None` (2026-11-10)."""
        excerpt = self.role.base_excerpt()
        self.assertIn('def load(self, model: Optional[str] = None) -> bool:', excerpt)
        self.assertIn('    @property\n    @abstractmethod\n    def is_loaded(self) -> bool:', excerpt)
        self.assertIn('def unload(self) -> None:', excerpt)
        self.assertLess(len(excerpt), self.role.BASE_CHARS + 3000, 'the head stays bounded')

    def test_a_loader_too_long_for_its_share_is_served_by_its_signature_doc_and_parameter_uses(self):
        """In the compact material the budget ran out before `_load_vae_model`, which joins `vae`
        to the folder it receives: the module passed `…/vae` (2026-11-10, `…/vae/vae`)."""
        source = ('def _load_vae_model(self, *, checkpoint_dir, device):\n'
                  '    """checkpoint_dir: Root checkpoint directory (= <checkpoint_dir>/vae)."""\n'
                  '    import os\n'
                  '    unrelated = 1\n'
                  '    path = os.path.join(checkpoint_dir, "vae")\n'
                  '    self.vae = load(path).to(device)\n')
        digest = self.role.parameter_uses(source)
        self.assertIn('Root checkpoint directory', digest)
        self.assertIn('os.path.join(checkpoint_dir, "vae")', digest)
        self.assertIn('.to(device)', digest)
        self.assertNotIn('unrelated', digest)

    #: What the trial said of the module the role proposed for ACE-Step on 2026-11-10.
    TRIAL = ("RuntimeError: ACE-Step generation failed: AceStepBackend.generate.<locals>."
             "wama_progress() takes 1 positional argument but 2 were given")

    def test_a_failed_trial_is_handed_back_once_and_kept_only_when_its_own_trial_passes(self):
        """The module passed the checks, loaded the model, and failed at generation on an error
        the trial names exactly — the role never received it (ACE-Step, 2026-11-10)."""
        calls, written = self._run(['first', 'second'], {'first': [], 'second': []}, smokes={
            'first': {'ran': True, 'ok': False, 'error': self.TRIAL},
            'second': {'ran': True, 'ok': True}})
        self.assertEqual(2, len(calls))
        self.assertIn(self.TRIAL, calls[1], 'the reprise must carry the trial word for word')
        self.assertEqual('second', written['code'].strip())
        self.assertTrue(written['smoke']['ok'])

    def test_a_reprise_whose_trial_still_fails_keeps_the_first_module_and_its_trial(self):
        calls, written = self._run(['first', 'second'], {'first': [], 'second': []}, smokes={
            'first': {'ran': True, 'ok': False, 'error': self.TRIAL},
            'second': {'ran': True, 'ok': False, 'error': 'another'}})
        self.assertEqual('first', written['code'].strip())
        self.assertEqual(self.TRIAL, written['smoke']['error'])

    def test_a_trial_that_could_not_run_is_no_verdict_to_hand_back(self):
        calls, written = self._run(['first'], {'first': []}, smokes={
            'first': {'ran': False, 'reason': 'pas de smoke pour le contrat X'}})
        self.assertEqual(1, len(calls))
