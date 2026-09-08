"""Grille F4/F5 après l'EXTERNALISATION des backends (8c556100, 2026-09-08).

Le 08/09 au matin, une remesure de la grille rendait `backend_packages` 0/10,
`hf_cache_isolation` 🔶 9/10, `backend_contract` rouge sur 4 apps — la nuit même où les
35 classes de backend avaient quitté `wama/<app>/backends/` pour `wama/common/backends/`.
Aucune app n'avait rien perdu : les critères lisaient `wama/<app>/**/*.py`, et ce qu'ils
cherchaient (REQUIRED_PACKAGES, BaseModelBackend, cache_dir=) avait déménagé AVEC les classes.

Ce fichier tient les deux moitiés du correctif :
  • la RÉSOLUTION statique (`backend_inventory.app_backend_paths`) — une app résout ses
    backends par le catalogue (`AIModel.source` → moteur → `ENGINE`/`SUPPORTED_MODELS`),
    jamais par son dossier, et sans importer ;
  • la SURFACE lue par les critères (`_AppFiles.backend_paths` / `find_py`) — code de l'app
    PLUS ses backends résolus, avec un repli par imports quand le catalogue est muet.

Les cas sont SEMÉS (un `TestCase` mesure la base de test, vide) ; l'état réel se lit par la
commande `check_app_conformity`, jamais ici.
"""
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from wama.common.services import backend_inventory as bi
from wama.common.services import conformity_checker as cc

COMMUN = cc.WAMA_ROOT / 'common' / 'backends'


class _Fichiers(cc._AppFiles):
    """`_AppFiles` dont les backends résolus — et au besoin le dossier d'app — sont IMPOSÉS."""

    def __init__(self, app, backends, root=None):
        super().__init__(app)
        self._backend_paths = list(backends)
        if root is not None:
            self.root = Path(root)


def _ecrire(dossier, nom, contenu) -> Path:
    p = Path(dossier) / nom
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenu, encoding='utf-8')
    return p


BACKEND_CONFORME = '''
from wama.common.backends.base import BaseModelBackend

class UnBackend(BaseModelBackend):
    REQUIRED_PACKAGES = ['torch']
    def load(self, model_id):
        return AutoModel.from_pretrained(model_id, cache_dir=str(MON_DIR))
'''


class ResolutionStatiqueTest(TestCase):
    """Une app résout ses backends par le CATALOGUE, statiquement."""

    @staticmethod
    def _semer(cle, moteur):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(
            model_key=cle, name=cle, model_type='audio', source=cle.split(':')[0],
            is_available=True, is_downloaded=True,
            composition={'runtime': {'engine': moteur}})

    def test_une_app_resout_ses_backends_par_le_catalogue_sans_les_importer(self):
        deja = 'wama.common.backends.whisper_backend' in sys.modules
        self._semer('appx:whisper', 'faster-whisper')
        chemins = bi.app_backend_paths('appx')
        self.assertEqual([p.name for p in chemins], ['whisper_backend.py'])
        self.assertEqual(chemins[0].parent, COMMUN)
        if not deja:
            self.assertNotIn('wama.common.backends.whisper_backend', sys.modules,
                             'la résolution de la grille doit rester une LECTURE, jamais un import')

    def test_un_moteur_partage_est_departage_par_supported_models(self):
        """`diffusers` est piloté par 8 backends : la clé du modèle tranche (règle de
        `resolve_entry`, la même que `backend_for_model`)."""
        self._semer('appx:mochi-1-preview', 'diffusers')
        self._semer('appx:stable-diffusion-v1-5', 'diffusers')
        noms = sorted(p.name for p in bi.app_backend_paths('appx'))
        self.assertEqual(noms, ['diffusers_backend.py', 'mochi_backend.py'])

    def test_un_moteur_hors_processus_ne_resout_rien(self):
        self._semer('appx:un-llm', 'ollama')
        self.assertEqual(bi.app_backend_paths('appx'), [])

    def test_une_app_sans_modele_au_catalogue_ne_resout_rien(self):
        self.assertEqual(bi.app_backend_entries('app_sans_modele'), [])

    def test_resolve_backend_ne_decide_plus_rien_lui_meme(self):
        """La DÉCISION vit dans `resolve_entry` ; `resolve_backend` importe ce qu'elle a choisi.
        Garde par AST : un second chemin de décision divergerait en silence."""
        import ast
        import inspect
        src = inspect.getsource(bi.resolve_backend)
        appels = {n.func.id for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn('resolve_entry', appels)
        self.assertNotIn('inventory', appels)


class SurfaceLueParLaGrilleTest(TestCase):
    """`_AppFiles.backend_paths` = lien du catalogue ∪ imports de l'app — sans base, le repli."""

    def test_sans_catalogue_le_repli_lit_les_imports_de_l_app(self):
        """Le transcriber nomme whisper/vibevoice/qwen_asr dans son manager ; `base` et
        `manager` du substrat ne sont jamais des backends."""
        noms = {p.stem for p in cc._AppFiles('transcriber').backend_paths()}
        self.assertTrue({'whisper_backend', 'vibevoice_backend', 'qwen_asr_backend'} <= noms, noms)
        self.assertFalse({'base', 'manager'} & noms)

    def test_un_import_de_module_sans_point_est_lu_aussi(self):
        """`from wama.common.backends import anonymize` (anonymizer/tasks.py)."""
        noms = {p.stem for p in cc._AppFiles('anonymizer').backend_paths()}
        self.assertIn('anonymize', noms)

    def test_les_bases_metier_suivent_leurs_backends(self):
        """anonymize → `.detection_base` → BaseModelBackend : c'est la base métier qui porte
        le contrat. Sans elle, l'anonymizer sortait « ne dérive pas du contrat » (08/09)."""
        noms = {p.stem for p in cc._AppFiles('anonymizer').backend_paths()}
        self.assertIn('detection_base', noms)
        self.assertFalse({'base', 'manager'} & noms)
        etat, preuve = cc._backend_contract(cc._AppFiles('anonymizer'))
        self.assertIs(etat, True, preuve)
        self.assertIn('common/backends/detection_base.py', preuve)

    def test_un_test_qui_importe_un_backend_ne_le_resout_pas(self):
        """reader/tests_table_transformer.py importe table_transformer_backend ; le code du
        reader, lui, ne le nomme pas (il passe par backend_for_key)."""
        with tempfile.TemporaryDirectory() as tmp:
            _ecrire(tmp, 'tests_x.py', 'from wama.common.backends.whisper_backend import WhisperBackend\n')
            _ecrire(tmp, 'tasks.py', 'from wama.common.backends.doctr_backend import DoctrBackend\n')
            f = _Fichiers('app_jetable', [], root=tmp)
            f._backend_paths = None
            self.assertEqual([p.stem for p in f.backend_paths()], ['doctr_backend'])

    def test_le_catalogue_et_les_imports_s_unissent(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='transcriber:pyannote-test', name='p', model_type='audio',
                               source='transcriber', is_available=True, is_downloaded=True,
                               composition={'runtime': {'engine': 'pyannote'}})
        noms = {p.stem for p in cc._AppFiles('transcriber').backend_paths()}
        self.assertIn('pyannote_diarizer', noms)
        self.assertIn('whisper_backend', noms)


class CriteresSurBackendsResolusTest(SimpleTestCase):
    """Chaque critère du 1ᵉʳ tableau lit les backends résolus — vert quand la déclaration y
    est, rouge/partiel quand elle n'y est pas, et jamais vert sur un harnais."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _app(self, contenu_backend, code_app=None):
        backends = [_ecrire(self.tmp / 'backends', 'b.py', contenu_backend)]
        root = self.tmp / 'app'
        root.mkdir(exist_ok=True)
        for nom, texte in (code_app or {}).items():
            _ecrire(root, nom, texte)
        return _Fichiers('app_jetable', backends, root=root)

    def test_backend_conforme_au_substrat_rend_les_quatre_criteres_verts(self):
        f = self._app(BACKEND_CONFORME)
        for critere in (cc._backend_packages, cc._backend_contract, cc._hf_cache_routing,
                        cc._vram_unloader):
            etat, preuve = critere(f)
            self.assertIs(etat, True, f'{critere.__name__}: {preuve}')
            self.assertIn('b.py', preuve, critere.__name__)

    def test_backend_muet_rend_rouge_ou_partiel_et_dit_pourquoi(self):
        f = self._app('import torch\n\nclass Rien:\n    pass\n')
        self.assertEqual(cc._backend_packages(f)[0], False)
        self.assertIn('aucun ne déclare REQUIRED_PACKAGES', cc._backend_packages(f)[1])
        self.assertEqual(cc._backend_contract(f)[0], False)
        self.assertEqual(cc._hf_cache_routing(f)[0], 'partial')
        self.assertEqual(cc._vram_unloader(f)[0], False, 'torch importé, aucun unloader')

    def test_sans_torch_ni_backend_l_unloader_est_non_applicable(self):
        f = self._app('x = 1\n')
        self.assertIsNone(cc._vram_unloader(f)[0])

    def test_une_mutation_d_environnement_dans_un_backend_resolu_condamne_l_app(self):
        f = self._app("import os\nos.environ['HF_HUB_CACHE'] = '/x'\n")
        etat, preuve = cc._hf_cache_routing(f)
        self.assertIs(etat, False)
        self.assertIn('mutation', preuve)

    def test_un_harnais_qui_cite_le_contrat_n_est_pas_une_preuve(self):
        """08/09 : `backend_contract` du reader était VERT via `tests_table_transformer.py:12`,
        celui de l'enhancer via `nightly_scenarios.py:22`."""
        f = self._app('x = 1\n', code_app={
            'tests_x.py': 'from wama.common.backends.base import BaseModelBackend\n',
            'nightly_scenarios.py': 'from wama.common.backends.base import BaseModelBackend\n'})
        self.assertIs(cc._backend_contract(f)[0], False)
        self.assertIsNone(cc._vram_unloader(f)[0])

    def test_un_commentaire_ne_fait_plus_de_preuve(self):
        f = self._app('# REQUIRED_PACKAGES = []  BaseModelBackend cache_dir=\nx = 1\n')
        self.assertIs(cc._backend_packages(f)[0], False)
        self.assertIs(cc._backend_contract(f)[0], False)
        self.assertEqual(cc._hf_cache_routing(f)[0], 'partial')

    def test_une_sonde_vram_maison_dans_un_backend_resolu_est_vue(self):
        f = self._app("import subprocess\nsubprocess.run(['nvidia-smi'])\n")
        etat, preuve = cc._select_model(f)
        self.assertIs(etat, False)
        self.assertIn('sélecteur maison', preuve)

    def test_backend_routes_dit_la_vraie_raison_quand_les_classes_sont_au_substrat(self):
        f = self._app(BACKEND_CONFORME)
        etat, preuve = cc._backend_routes(f)
        self.assertIs(etat, False)
        self.assertIn('résolu(s) au substrat', preuve)
        self.assertNotIn('enfoui', preuve)

    def test_sans_aucun_backend_resolu_le_manque_est_dit(self):
        f = _Fichiers('app_jetable', [], root=self.tmp / 'vide')
        self.assertIn('aucun backend résolu', cc._backend_packages(f)[1])
        self.assertIn('enfoui', cc._backend_routes(f)[1])


class MesureSurLArbreReelTest(SimpleTestCase):
    """Sans catalogue (base de test), le repli par imports suffit à ce que les apps qui
    nomment leurs backends redeviennent vertes — la preuve pointe le SUBSTRAT."""

    def test_le_transcriber_declare_ses_paquets_au_substrat(self):
        etat, preuve = cc._backend_packages(cc._AppFiles('transcriber'))
        self.assertIs(etat, True, preuve)
        self.assertTrue(preuve.startswith('common/backends/'), preuve)

    def test_le_synthesizer_derive_du_contrat_au_substrat(self):
        etat, preuve = cc._backend_contract(cc._AppFiles('synthesizer'))
        self.assertIs(etat, True, preuve)
        self.assertTrue(preuve.startswith('common/backends/'), preuve)
