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
    """Le balayage, tenu sur un paquet FABRIQUÉ (jamais l'arbre courant).

    ⚠ Depuis le 2026-09-03 la lecture est STATIQUE (AST) : le paquet témoin n'est plus
    importé du tout — c'est le but (lire une déclaration ne doit rien exécuter), et c'est
    ce qui a fait passer la page de 9,07 s à 0,16 s au premier affichage.
    """

    def _paquet(self, racine, submodules: dict):
        p = Path(racine) / 'paquet_temoin'
        p.mkdir()
        (p / '__init__.py').write_text('', encoding='utf-8')   # rien de ré-exporté : le cas
        for nom, code in submodules.items():
            (p / f'{nom}.py').write_text(textwrap.dedent(code), encoding='utf-8')
        return p

    #: Un backend CONCRET doit implémenter le contrat — sinon il est abstrait par héritage
    #: (défaut mesuré le 03/09 : `DetectionBackend`/`TTSBackend` passaient pour exécutables).
    CLASSE = """
        from wama.common.backends.base import BaseModelBackend

        class MoteurTemoin(BaseModelBackend):
            REQUIRED_PACKAGES = ['torch']
            recommended_vram_gb = 2.5
            description = "moteur témoin"
            ENGINE = 'moteur-temoin'

            @property
            def is_loaded(self): return False
            def load(self, model=None): return True
            def unload(self): return None
            def process(self, **kw): return None
    """

    ABSTRAITE = """
        from wama.common.backends.base import BaseModelBackend

        class BaseMetier(BaseModelBackend):
            \"\"\"Base métier : n'implémente PAS le contrat -> jamais un backend exécutable.\"\"\"
            description = "base metier"
    """

    def test_une_classe_d_un_SOUS_MODULE_non_re_exporte_est_trouvee(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE})
            classes, illisibles = bi._classe_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'])
        self.assertEqual(illisibles, [])

    def test_le_MOTEUR_declare_est_lu_avec_les_paquets_requis(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE})
            classes, _ = bi._classe_backends(paquet, 'paquet_temoin')
        _, info = classes[0]
        self.assertEqual(info['attrs'].get('ENGINE'), 'moteur-temoin')
        self.assertEqual(info['attrs'].get('REQUIRED_PACKAGES'), ['torch'])

    def test_une_base_METIER_qui_n_implemente_pas_le_contrat_est_ECARTEE(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'base': self.ABSTRAITE, 'moteur': self.CLASSE})
            classes, _ = bi._classe_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'],
                         'une base abstraite par HÉRITAGE ne doit pas passer pour exécutable')

    def test_un_module_dont_la_LIB_manque_reste_LISIBLE(self):
        """Gain direct du statique : un backend dont la librairie n'est pas installée
        s'inventorie quand même (c'est `moteur_installe` qui dit qu'il ne tournera pas).
        En lecture par IMPORT il disparaissait purement et simplement."""
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE.replace(
                "['torch']", "['bibliotheque_absente_xyz']")})
            classes, illisibles = bi._classe_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'])
        self.assertEqual(illisibles, [])
        self.assertFalse(bi._paquets_presents(['bibliotheque_absente_xyz']))

    def test_un_sous_module_ILLISIBLE_est_rapporte_jamais_avale(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE,
                                      'casse': 'class Casse(:\n'})   # INSYNTAXIQUE
            classes, illisibles = bi._classe_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'],
                         'un module cassé ne doit pas emporter les autres')
        self.assertEqual(len(illisibles), 1)
        self.assertIn('casse', illisibles[0])

    def test_une_classe_IMPORTEE_d_ailleurs_n_est_pas_comptee_deux_fois(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE,
                                      'reexport': 'from .moteur import MoteurTemoin\n'})
            classes, _ = bi._classe_backends(paquet, 'paquet_temoin')
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


class ToutBackendDeclareSonMoteurTest(TestCase):
    """INVARIANT (2026-09-04) : un backend CONCRET déclare le moteur qu'il pilote.

    C'est la moitié BACKEND du lien modèle↔moteur (`composition.runtime.engine` côté modèle,
    `ENGINE` côté backend). Sans elle, `known_engines()` ne peut pas dériver l'inventaire des
    exécutables et un modèle peut être grisé faute d'inventaire, pas faute de moteur.

    Comme l'invariant des importeurs de fichiers, ce test ne vérifie pas les backends d'un
    jour : il vérifie que le PROCHAIN sera écrit déclaré.
    """

    def test_chaque_backend_concret_declare_ENGINE(self):
        sans = sorted(f'{a.app}:{e.name}' for a in bi.inventory() if not a.generated_from
                      for e in a.entries if e.kind == 'classe' and not e.moteur)
        self.assertEqual(sans, [], "ces backends ne disent pas quelle librairie ils pilotent : "
                                   "ajouter `ENGINE = '<moteur>'` (contrat BaseModelBackend)")

    def test_le_vocabulaire_des_moteurs_est_PARTAGE_avec_les_modeles(self):
        """Un moteur déclaré par un backend doit pouvoir être celui qu'un modèle EXIGE :
        même graphie, sinon le lien ne se referme jamais. On vérifie l'intersection réelle —
        pas l'égalité : tous les moteurs installés n'ont pas encore un modèle qui les nomme."""
        from wama.model_manager.models import AIModel
        backends = {e.moteur for a in bi.inventory() for e in a.entries if e.moteur}
        modeles = {(m.composition or {}).get('runtime', {}).get('engine')
                   for m in AIModel.objects.exclude(composition={})}
        modeles.discard(None)
        orphelins = sorted(m for m in modeles if m not in backends)
        self.assertEqual(orphelins, [],
                         'moteur EXIGÉ par un modèle que plus aucun backend ne déclare piloter')


class EnvironnementDExecutionTest(SimpleTestCase):
    """`ISOLATION` (2026-09-04) — la MOITIÉ MANQUANTE du verdict de disponibilité.

    Sans elle, « paquet absent du venv » et « backend qui vit ailleurs » se confondent, et un
    backend parfaitement fonctionnel est grisé à vie. Mesuré en petit le 03/09 (codeformer se
    grisait sur un paquet qu'il n'utilise pas) ; en grand, `wama_lab/face_analyzer` a son PROPRE
    venv — ses paquets ne seront JAMAIS dans venv_linux.
    """

    ISOLE = """
        from wama.common.backends.base import BaseModelBackend

        class MoteurLointain(BaseModelBackend):
            REQUIRED_PACKAGES = ['paquet_qui_n_existe_nulle_part']
            ENGINE = 'moteur-lointain'
            ISOLATION = 'venv:wama_lab/face_analyzer/venv_linux'

            @property
            def is_loaded(self): return False
            def load(self, model=None): return True
            def unload(self): return None
            def process(self, **kw): return None
    """

    #: Une FAMILLE isolée déclare son environnement UNE fois, sur sa base métier — c'est ainsi
    #: qu'un paquet isolé s'écrira réellement. Une lecture à plat raterait les concrets.
    FAMILLE = """
        from wama.common.backends.base import BaseModelBackend

        class BaseLointaine(BaseModelBackend):
            ISOLATION = 'venv:wama_lab/face_analyzer/venv_linux'
            REQUIRED_PACKAGES = ['paquet_qui_n_existe_nulle_part']

        class EmotionsBackend(BaseLointaine):
            ENGINE = 'emotions'

            @property
            def is_loaded(self): return False
            def load(self, model=None): return True
            def unload(self): return None
            def process(self, **kw): return None
    """

    def _paquet(self, racine, submodules):
        p = Path(racine) / 'paquet_isole'
        p.mkdir()
        (p / '__init__.py').write_text('', encoding='utf-8')
        for nom, code in submodules.items():
            (p / f'{nom}.py').write_text(textwrap.dedent(code), encoding='utf-8')
        return p

    def test_l_ISOLATION_declaree_est_LUE(self):
        with TemporaryDirectory() as d:
            classes, _ = bi._classe_backends(self._paquet(d, {'m': self.ISOLE}), 'paquet_isole')
        _, info = classes[0]
        self.assertEqual(info['attrs'].get('ISOLATION'),
                         'venv:wama_lab/face_analyzer/venv_linux')

    def test_un_backend_ISOLE_n_est_pas_grise_sur_un_paquet_absent_D_ICI(self):
        """Le cœur de la règle : `find_spec` de CE processus ne dit rien d'un autre venv."""
        self.assertFalse(bi._paquets_presents(['paquet_qui_n_existe_nulle_part']))
        self.assertTrue(bi._paquets_presents(['paquet_qui_n_existe_nulle_part'],
                                             'venv:wama_lab/face_analyzer/venv_linux'))

    def test_un_backend_NON_isole_reste_grise_sur_un_paquet_absent(self):
        """Contre-épreuve : la permissivité ne vaut QUE pour l'isolement déclaré — sinon on
        aurait échangé un verdict faux contre un verdict qui ne dit plus rien."""
        self.assertFalse(bi._paquets_presents(['paquet_qui_n_existe_nulle_part'], ''))

    def test_l_ISOLATION_d_une_base_metier_est_HERITEE_par_les_concrets(self):
        with TemporaryDirectory() as d:
            classes, _ = bi._classe_backends(self._paquet(d, {'m': self.FAMILLE}), 'paquet_isole')
        concrets = dict(classes)
        self.assertIn('EmotionsBackend', concrets, 'le concret doit être trouvé')
        self.assertEqual(concrets['EmotionsBackend']['attrs'].get('ISOLATION'),
                         'venv:wama_lab/face_analyzer/venv_linux',
                         'un concret qui ne redéclare pas ISOLATION hérite celle de sa base '
                         '(ce que fait Python) — sinon toute famille isolée serait grisée')

    def test_un_concret_garde_SON_moteur_malgre_l_heritage(self):
        """L'héritage COMPLÈTE, il n'écrase pas : sinon deux moteurs d'une même famille
        deviendraient indiscernables."""
        with TemporaryDirectory() as d:
            classes, _ = bi._classe_backends(self._paquet(d, {'m': self.FAMILLE}), 'paquet_isole')
        self.assertEqual(dict(classes)['EmotionsBackend']['attrs'].get('ENGINE'), 'emotions')

    def test_un_moteur_ISOLE_reste_EXECUTABLE_pour_known_engines(self):
        """`_MoteurDeclare` porte la même règle que le contrat commun — sinon le lien
        modèle↔moteur donnerait un verdict faux dès le premier backend porté."""
        lointain = bi._MoteurDeclare('moteur-lointain', ['paquet_qui_n_existe_nulle_part'],
                                     'venv:wama_lab/face_analyzer/venv_linux')
        local = bi._MoteurDeclare('moteur-local', ['paquet_qui_n_existe_nulle_part'])
        self.assertEqual(lointain.missing_packages(), [])
        self.assertEqual(local.missing_packages(), ['paquet_qui_n_existe_nulle_part'])


class IsolementResteUneExceptionTest(TestCase):
    """GARDE de doctrine : le défaut est UN venv, l'isolement se DÉCLARE au cas par cas.

    Ce test ne réclame pas zéro isolement pour toujours — il réclame qu'aucun n'apparaisse
    SANS décision. Le coût n'est pas le disque (~10 Go de torch+CUDA par venv) mais la VRAM :
    chaque processus isolé est un détenteur que le gouverneur de ressources ne voit pas, et
    les crashs hôte du 02/09 sont déjà des montées VRAM concurrentes.

    ⚠ Si tu ajoutes un backend isolé LÉGITIME, inscris-le ici avec sa raison — c'est le geste
    qui transforme une dérive en décision.
    """

    #: {environnement: raison} — vide aujourd'hui : tous les backends vivent dans le venv principal.
    ISOLEMENTS_ASSUMES = {}

    def test_aucun_environnement_isole_n_apparait_sans_decision(self):
        declares = set(bi.summary()['isolations'])
        surprise = sorted(declares - set(self.ISOLEMENTS_ASSUMES))
        self.assertEqual(surprise, [],
                         "environnement(s) isolé(s) non assumé(s) : soit le backend rejoint le "
                         "venv principal, soit on inscrit la raison dans ISOLEMENTS_ASSUMES")


class ContratCommunIsolationTest(SimpleTestCase):
    """Le 3ᵉ site de la règle — le CONTRAT lui-même (`BaseModelBackend.missing_packages`).

    La règle vit à trois endroits (contrat, `_paquets_presents`, `_MoteurDeclare`) parce que
    trois chemins posent la même question. Les trois sont tenus ici : *une garde se pose avec
    ses JUMEAUX*, sinon le premier chemin oublié ramène le verdict faux.
    """

    def _backend(self, isolation=''):
        from wama.common.backends.base import BaseModelBackend

        class Temoin(BaseModelBackend):
            REQUIRED_PACKAGES = ['paquet_qui_n_existe_nulle_part']
            ISOLATION = isolation

            @property
            def is_loaded(self): return False
            def load(self, model=None): return True
            def unload(self): return None
            def process(self, **kw): return None

        return Temoin

    def test_un_backend_ISOLE_n_a_rien_a_installer_ICI(self):
        self.assertEqual(self._backend('venv:ailleurs').missing_packages(), [])

    def test_sans_isolation_le_paquet_absent_est_toujours_signale(self):
        self.assertEqual(self._backend().missing_packages(),
                         ['paquet_qui_n_existe_nulle_part'])

    def test_le_defaut_du_contrat_est_le_venv_PRINCIPAL(self):
        """Un backend qui ne dit rien n'est PAS isolé : le silence ne doit jamais valoir
        dispense de vérification."""
        from wama.common.backends.base import BaseModelBackend
        self.assertEqual(BaseModelBackend.ISOLATION, '')
