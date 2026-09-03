"""Le VIVIER des backends — dérivation (`services/backend_inventory.py`) et sa page.

POURQUOI CE FICHIER (demande Fabien 2026-09-03) : « un registre des backends pour simplifier
le travail du LLM qui devra piocher dans le vivier pour s'inspirer du plus approchant, et me
permettre d'avoir une vision d'ensemble ». Le registre est DÉRIVÉ — il ne stocke rien, donc
il n'a pas de rafraîchisseur à tester ; ce qui doit être tenu, c'est **qu'il ne rate rien** et
**qu'il ne surestime rien**.

Les invariants génériques des registres (url résolvable, source déclarée, `count` qui ne lève
jamais, cohérence nature/exécution) sont déjà tenus par `tests_registries.py` et s'appliquent
tout seuls à `backends` — c'est le bénéfice de l'uniformité, on ne les recopie pas ici.

Deux défauts MESURÉS à l'écriture, chacun devenu un test :
  1. balayer le seul `__init__` du paquet ratait 4 apps sur 9 (leurs classes vivent dans des
     sous-modules) — *un inventaire qui rate des entrées est pire qu'aucun inventaire* ;
  2. `AIModel.backend_ref` porte un nom d'APP, pas de backend : fabriquer un lien fin là où
     il n'y en a pas aurait maquillé le chantier au lieu de le montrer.
"""
import sys
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, TestCase

from wama.common.services import backend_inventory as bi


class DerivationDuVivierTest(TestCase):
    """Sur les apps RÉELLES : le vivier reflète les déclarations, sans en inventer."""

    @classmethod
    def setUpTestData(cls):
        cls.inv = bi.inventory()
        cls.par_app = {a.app: a for a in cls.inv}

    def test_toute_app_a_paquet_backends_est_inventoriee(self):
        """Le balayage des SOUS-MODULES est la seule raison pour laquelle ces apps sont là."""
        import wama
        racine = Path(wama.__file__).parent
        attendues = {p.parent.parent.name for p in racine.glob('*/backends/__init__.py')}
        attendues.discard('common')                      # le contrat lui-même, pas une app
        manquantes = sorted(attendues - set(self.par_app))
        self.assertEqual(manquantes, [], "apps à paquet `backends/` absentes du vivier")

    def test_une_app_ROUTEE_expose_ses_natures_et_sa_saveur(self):
        routees = [a for a in self.inv if a.routes]
        self.assertTrue(routees, 'au moins une app routée (marche B1) doit exister')
        for a in routees:
            self.assertIn(a.saveur, bi.SAVEURS, f'{a.app} : saveur hors vocabulaire')
            natures_vues = {n for e in a.entries for n in e.natures}
            self.assertEqual(natures_vues, set(a.routes),
                             f'{a.app} : toute nature routée doit mener à une entrée')
            # La colonne de nature EFFECTIVE ne peut pas être vide : le corps composé la lit.
            # (Ma 1ʳᵉ version confondait les CLÉS de ROUTES — des natures — avec le NOM de la
            # colonne : elle a fait sortir converter, qui hérite du défaut `media_type`.)
            self.assertTrue(a.nature_effective, f'{a.app} : colonne de nature effective vide')
            if not a.nature_declaree:
                self.assertEqual(a.nature_effective, 'media_type',
                                 'le seul défaut admis est celui du pilote')

    def test_une_app_SANS_routes_le_dit_au_lieu_de_paraitre_complete(self):
        for a in self.inv:
            if not a.routes:
                self.assertIn('ROUTES', a.manque,
                              f"{a.app} : l'absence de routage doit être NOMMÉE (trou marche B)")

    def test_chaque_entree_porte_une_signature_de_voisinage(self):
        # C'est LA donnée que le LLM trie pour trouver « le plus approchant ».
        for a in self.inv:
            for e in a.entries:
                self.assertTrue(e.signature and '→' in e.signature)
                self.assertIn(e.kind, ('route', 'classe'))
                self.assertTrue(e.path, f'{e.app}:{e.name} sans chemin d’import')

    def test_les_jumelles_sont_MARQUEES_et_hors_des_comptes(self):
        s = bi.summary()
        jumelles = [a for a in self.inv if a.generated_from]
        for j in jumelles:
            self.assertNotIn(j.app, s['sans_routage'])
            self.assertIn(j.generated_from, self.par_app,
                          'une jumelle nomme une source réellement inventoriée')
        entrees_reelles = sum(len(a.entries) for a in self.inv if not a.generated_from)
        self.assertEqual(s['backends_count'], entrees_reelles,
                         'les jumelles ne gonflent pas le total du vivier')

    def test_le_lien_modele_backend_dit_sa_PROVENANCE(self):
        for a in self.inv:
            for e in a.entries:
                if e.models:
                    self.assertIn(e.lien, ('backend_ref', 'app'),
                                  'un rattachement sans provenance déclarée est illisible')

    def test_un_modele_rattache_a_plusieurs_entrees_ne_compte_qu_une_fois(self):
        s = bi.summary()
        couples = ({(e.app, m) for a in self.inv if not a.generated_from
                    for e in a.entries for m in e.models}
                   | {(a.app, m) for a in self.inv if not a.generated_from
                      for m in a.models_app})
        self.assertEqual(s['modeles_lies'], len(couples))
        self.assertLessEqual(s['modeles_lien_declare'], s['modeles_lies'])

    def test_un_rattachement_de_NIVEAU_APP_n_est_pas_etale_sur_chaque_backend(self):
        """Défaut mesuré le 03/09 (recadrage Fabien « backend ≠ moteur ») : attribuer les
        modèles de l'app à CHAQUE entrée annonçait BarkBackend appelant coqui/higgs/kokoro.
        Une page qui étale une attribution inconnue ment plus qu'elle n'informe."""
        for a in self.inv:
            for e in a.entries:
                if e.models:
                    self.assertEqual(e.lien, 'backend_ref',
                                     f'{e.app}:{e.name} : un backend ne porte que le lien DÉCLARÉ')
                for moteur in e.engines:
                    modeles_du_moteur = {m for m in e.models}
                    self.assertTrue(modeles_du_moteur,
                                    'un moteur affiché doit venir de modèles DÉCLARÉS')


class BalayageDesSousModulesTest(SimpleTestCase):
    """Le défaut n°1, tenu sur un paquet FABRIQUÉ (jamais l'arbre courant)."""

    def _paquet(self, racine, submodules: dict):
        p = Path(racine) / 'paquet_temoin'
        p.mkdir()
        (p / '__init__.py').write_text('', encoding='utf-8')   # rien de ré-exporté : le cas
        for nom, code in submodules.items():
            (p / f'{nom}.py').write_text(textwrap.dedent(code), encoding='utf-8')
        sys.path.insert(0, racine)
        self.addCleanup(sys.path.remove, racine)

        # ⚠ Purge des modules À LA FIN, pas d'une liste figée MAINTENANT : ma 1ʳᵉ version
        # collectait les modules AVANT l'import (donc aucun) — le paquet du test précédent
        # restait dans `sys.modules`, `import_module` rendait un module dont le `__path__`
        # pointait sur un temporaire SUPPRIMÉ, et le balayage trouvait 0 classe.
        def _purger():
            for mod in [m for m in list(sys.modules) if m.startswith('paquet_temoin')]:
                sys.modules.pop(mod, None)
        _purger()
        self.addCleanup(_purger)
        from importlib import import_module
        return import_module('paquet_temoin')

    CLASSE = """
        from wama.common.backends.base import BaseModelBackend

        class MoteurTemoin(BaseModelBackend):
            REQUIRED_PACKAGES = ['torch']
            recommended_vram_gb = 2.5
            description = "moteur témoin"
    """

    def test_une_classe_d_un_SOUS_MODULE_non_re_exporte_est_trouvee(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE})
            classes, illisibles = bi._classe_backends(paquet)
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'])
        self.assertEqual(illisibles, [])

    def test_un_sous_module_ILLISIBLE_est_rapporte_jamais_avale(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE,
                                      'casse': 'import bibliotheque_absente_xyz\n'})
            classes, illisibles = bi._classe_backends(paquet)
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'],
                         'un module cassé ne doit pas emporter les autres')
        self.assertEqual(len(illisibles), 1)
        self.assertIn('casse', illisibles[0])

    def test_une_classe_IMPORTEE_d_ailleurs_n_est_pas_comptee_deux_fois(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE,
                                      'reexport': 'from .moteur import MoteurTemoin\n'})
            classes, _ = bi._classe_backends(paquet)
        self.assertEqual(len(classes), 1, 'compté par sa DÉFINITION, pas par ses imports')


class PageDuVivierTest(TestCase):
    """La page rend, et elle rend le vivier (pas une coquille)."""

    def test_la_page_liste_une_carte_par_backend(self):
        from wama.common.services.nightly_tests import get_test_user
        self.client.force_login(get_test_user())
        r = self.client.get('/common/backends/')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode('utf-8', 'replace')
        total = sum(len(a.entries) for a in bi.inventory())
        self.assertEqual(html.count('class="wama-cat-card"'), total)

    def test_les_facettes_ne_proposent_que_des_options_PRESENTES(self):
        from wama.common.services.nightly_tests import get_test_user
        self.client.force_login(get_test_user())
        facettes = self.client.get('/common/backends/').context['facettes_backends']
        presents = {'app': {e.app for a in bi.inventory() for e in a.entries},
                    'saveur': {e.saveur for a in bi.inventory() for e in a.entries},
                    'famille': {e.kind for a in bi.inventory() for e in a.entries}}
        for f in facettes:
            self.assertTrue(set(f['options']) <= presents[f['cle']],
                            f"facette {f['cle']} : une option sans carte viderait la page")
