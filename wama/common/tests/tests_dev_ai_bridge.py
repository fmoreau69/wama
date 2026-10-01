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
import importlib.util
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

    Vécu le 2026-09-30 : `e750fa74` avait servi `INPUT_TYPES` au seul rôle `model` ; le rôle
    frère `scout` écrit le même manifeste et, sans ce vocabulaire, qwen3.8 a déclaré `audio`/
    `image` comme entrées de LongCat-Video-Avatar-1.5 (manifeste invalide). La garde est
    GÉNÉRIQUE : elle part de ce que fait un rôle (valider un manifeste), pas d'une liste.
    """

    #: Rôles qui valident un manifeste d'un AUTRE kind — exemptés, avec leur raison.
    OTHER_KINDS = {'run_librarian.py': 'écrit des manifestes `library` (vocabulaire pip)'}

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

    def test_a_format_that_proves_nothing_poses_nothing(self):
        manifest, concerns = self._enforce({'body': {}}, None,
                                           files=('config.json', 'model.safetensors'))
        self.assertNotIn('composition', manifest['body'])
        self.assertEqual([], concerns)


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
                    'body': {'identity': {'hf_id': 'kyutai/stt-2.6b-en'}}}
        concerns = []
        self.role_utils.enforce_identity(manifest, self.KEY, self.HF, concerns)
        self.assertEqual((self.KEY, self.HF, self.KEY),
                         (manifest['key'], manifest['body']['identity']['hf_id'],
                          manifest['body']['identity']['platform_ref']))
        self.assertEqual(1, len(concerns))
        self.assertIn('stt-2.6b-en', concerns[0])

    def test_the_right_identity_says_nothing(self):
        manifest = {'key': self.KEY, 'body': {'identity': {'hf_id': self.HF}}}
        concerns = []
        self.role_utils.enforce_identity(manifest, self.KEY, self.HF, concerns)
        self.assertEqual([], concerns)

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

    def test_ollama_reste_call_ollama_a_l_identique(self):
        from unittest.mock import patch
        with patch.object(self.role_utils, 'call_ollama', return_value='OK') as direct:
            self.role_utils.call_llm('ollama', 'gemma4:e4b', 'sys', 'msg', keep_alive='0')
        direct.assert_called_once()
        self.assertEqual('0', direct.call_args.kwargs['keep_alive'])

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
