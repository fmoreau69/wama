"""LocateAnything-3B — le backend est CÂBLÉ ; son exécution réelle reste non éprouvée.

POURQUOI CE FICHIER (2026-09-08). Sur les 6 modèles prospectés que rien ne servait, la mesure a
montré qu'UN SEUL est chargeable par le venv actuel : les autres exigent transformers 5.x
(canary, parakeet, PP-DocLayout) ou un toolkit absent (fastvideo pour FastWan). LocateAnything
résout sa config avec `transformers 4.57.6` — ce qui répond, au passage, à la question que la
ROADMAP §17 laissait explicitement ouverte : *« venv_linux à 4.57.6, écart mineur, TESTER AVANT
de créer un venv isolé »*. Testé : **pas de venv isolé nécessaire**.

⚠⚠ CE QUE CES TESTS N'ATTESTENT PAS : que le modèle TOURNE. Il pèse ~9 Go de VRAM et aucune
charge GPU n'est lancée depuis cette session (crashs hôte). Ils tiennent le CÂBLAGE — résolution,
déclarations, contrat, garde-fous d'entrée — c'est-à-dire tout ce qui casserait en silence si
quelqu'un déplaçait ou renommait quelque chose. *Un backend qui n'a jamais tourné se dit tel
quel ; ce qui est vérifiable se vérifie quand même.*
"""
from django.test import SimpleTestCase, TestCase

from wama.common.backends.base import BaseModelBackend
from wama.common.backends.locate_anything_backend import (
    HF_ID, TACHES, LocateAnythingBackend, _dossier_poids,
)


class ContratLocateAnythingTest(SimpleTestCase):

    def test_herite_du_contrat_commun(self):
        """« Conforme au contrat » ≠ « hérite du contrat » — seul l'héritage capte les
        mécanismes AJOUTÉS ensuite (leçon du transcriber, 2026-07-29)."""
        self.assertTrue(issubclass(LocateAnythingBackend, BaseModelBackend))

    def test_declare_son_moteur_et_le_modele_qu_il_sert(self):
        self.assertEqual(LocateAnythingBackend.ENGINE, 'transformers')
        self.assertIn(HF_ID, LocateAnythingBackend.SUPPORTED_MODELS)

    def test_la_cle_servie_est_un_LITTERAL_lisible_par_AST(self):
        """L'inventaire lit `SUPPORTED_MODELS` sans importer le module : une clé portée par la
        constante `HF_ID` y serait INVISIBLE (défaut mesuré le 07/09 sur table-transformer)."""
        import ast
        from pathlib import Path
        from django.conf import settings
        source = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'backends' /
                  'locate_anything_backend.py').read_text(encoding='utf-8')
        cles = [n.value for noeud in ast.walk(ast.parse(source))
                if isinstance(noeud, ast.Assign)
                and getattr(noeud.targets[0], 'id', '') == 'SUPPORTED_MODELS'
                and isinstance(noeud.value, ast.Dict)
                for n in noeud.value.keys if isinstance(n, ast.Constant)]
        self.assertIn(HF_ID, cles, 'clé non littérale : le vivier ne la verra pas')

    def test_la_VRAM_est_declaree(self):
        """Sans elle, le gouverneur croit la place libre et laisse démarrer par-dessus."""
        self.assertGreaterEqual(LocateAnythingBackend.recommended_vram_gb, 8)

    def test_le_dossier_des_poids_vient_de_MODEL_PATHS(self):
        """Un CHEMIN se lit à sa source déclarée, il ne se reconstruit pas dans un backend."""
        from django.conf import settings
        attendu = (settings.MODEL_PATHS.get('vision') or {}).get('locate_anything')
        self.assertIsNotNone(attendu, 'chemin non déclaré dans settings.MODEL_PATHS')
        self.assertEqual(str(_dossier_poids()), str(attendu))

    def test_la_licence_NON_COMMERCIALE_est_dite_dans_la_description(self):
        """La contrainte doit voyager AVEC le modèle — pas dans la mémoire de quelqu'un."""
        textes = (LocateAnythingBackend.description +
                  LocateAnythingBackend.description_long).lower()
        self.assertIn('non commercial', textes.replace('non-commercial', 'non commercial'))


class GardesEntreeTest(SimpleTestCase):
    """Les refus, vérifiables SANS charger le modèle — ils précèdent tout chargement."""

    def test_sans_image_on_refuse_en_le_DISANT(self):
        with self.assertRaises(ValueError):
            LocateAnythingBackend().process(image_path=None, prompt='car')

    def test_une_tache_inconnue_est_refusee_AVANT_le_chargement(self):
        with self.assertRaises(ValueError) as ctx:
            LocateAnythingBackend().process(image_path='/tmp/x.jpg', prompt='car',
                                            task='tache-qui-nexiste-pas')
        self.assertIn('tâche inconnue', str(ctx.exception))

    def test_les_taches_annoncees_sont_celles_de_la_classe_officielle(self):
        """La liste ne se recopie pas : elle doit correspondre aux méthodes du worker NVIDIA,
        gardé verbatim dans `scripts/`. Si l'amont en ajoute une, la divergence se voit ici."""
        import ast
        from pathlib import Path
        from django.conf import settings
        source = (Path(settings.BASE_DIR) / 'scripts' /
                  'locate_anything_worker.py').read_text(encoding='utf-8')
        classe = next(n for n in ast.parse(source).body
                      if isinstance(n, ast.ClassDef) and n.name == 'LocateAnythingWorker')
        methodes = {n.name for n in classe.body if isinstance(n, ast.FunctionDef)}
        self.assertTrue(set(TACHES) <= methodes,
                        f'tâches annoncées absentes du worker officiel : {set(TACHES) - methodes}')


class ResolutionDepuisLeCatalogueTest(TestCase):
    """Le modèle prospecté trouve son backend — la moitié qui manquait."""

    def test_le_modele_resout_CE_backend(self):
        from wama.common.backends.manager import backend_for_model
        from wama.model_manager.models import AIModel
        m = AIModel.objects.create(
            model_key=f'huggingface:{HF_ID}', name='LocateAnything-3B', model_type='vision',
            source='huggingface', composition={'runtime': {'engine': 'transformers'}})
        classe = backend_for_model(m)
        self.assertIsNotNone(classe, 'le modèle ne résout aucun backend')
        self.assertEqual(classe.__name__, 'LocateAnythingBackend')

    def test_un_AUTRE_modele_transformers_n_est_pas_capte(self):
        """Contre-épreuve : `transformers` est partagé par 6 backends — celui-ci ne doit
        capter QUE le sien, sinon on aurait servi un modèle par le mauvais moteur."""
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_for_model
        autre = SimpleNamespace(model_key='describer:blip',
                                composition={'runtime': {'engine': 'transformers'}})
        classe = backend_for_model(autre)
        self.assertIsNotNone(classe)
        self.assertNotEqual(classe.__name__, 'LocateAnythingBackend')
