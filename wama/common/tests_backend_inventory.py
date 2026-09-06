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
            self.assertIn(a.flavor, bi.FLAVORS, f'{a.app} : saveur hors vocabulaire')
            natures_vues = {n for e in a.entries for n in e.natures}
            self.assertEqual(natures_vues, set(a.routes),
                             f'{a.app} : toute nature routée doit mener à une entrée')
            # La colonne de nature EFFECTIVE ne peut pas être vide : le corps composé la lit.
            # (Ma 1ʳᵉ version confondait les CLÉS de ROUTES — des natures — avec le NOM de la
            # colonne : elle a fait sortir converter, qui hérite du défaut `media_type`.)
            self.assertTrue(a.effective_nature, f'{a.app} : colonne de nature effective vide')
            if not a.declared_nature:
                self.assertEqual(a.effective_nature, 'media_type',
                                 'le seul défaut admis est celui du pilote')

    def test_une_app_SANS_routes_le_dit_au_lieu_de_paraitre_complete(self):
        for a in self.inv:
            if not a.routes:
                self.assertIn('ROUTES', a.missing,
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
            self.assertNotIn(j.app, s['without_routes'])
            self.assertIn(j.generated_from, self.par_app,
                          'une jumelle nomme une source réellement inventoriée')
        entrees_reelles = sum(len(a.entries) for a in self.inv if not a.generated_from)
        self.assertEqual(s['backends_count'], entrees_reelles,
                         'les jumelles ne gonflent pas le total du vivier')

    def test_le_lien_modele_backend_dit_sa_PROVENANCE(self):
        for a in self.inv:
            for e in a.entries:
                if e.models:
                    self.assertIn(e.link, ('backend_ref', 'app'),
                                  'un rattachement sans provenance déclarée est illisible')

    def test_un_modele_rattache_a_plusieurs_entrees_ne_compte_qu_une_fois(self):
        s = bi.summary()
        couples = ({(e.app, m) for a in self.inv if not a.generated_from
                    for e in a.entries for m in e.models}
                   | {(a.app, m) for a in self.inv if not a.generated_from
                      for m in a.models_app})
        self.assertEqual(s['linked_models'], len(couples))
        self.assertLessEqual(s['declared_link_models'], s['linked_models'])

    def test_un_rattachement_de_NIVEAU_APP_n_est_pas_etale_sur_chaque_backend(self):
        """Défaut mesuré le 03/09 (recadrage Fabien « backend ≠ moteur ») : attribuer les
        modèles de l'app à CHAQUE entrée annonçait BarkBackend appelant coqui/higgs/kokoro.
        Une page qui étale une attribution inconnue ment plus qu'elle n'informe."""
        for a in self.inv:
            for e in a.entries:
                if e.models:
                    self.assertEqual(e.link, 'backend_ref',
                                     f'{e.app}:{e.name} : un backend ne porte que le lien DÉCLARÉ')
                for engine in e.engines:
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
            classes, unreadable = bi._class_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'])
        self.assertEqual(unreadable, [])

    def test_le_MOTEUR_declare_est_lu_avec_les_paquets_requis(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE})
            classes, _ = bi._class_backends(paquet, 'paquet_temoin')
        _, info = classes[0]
        self.assertEqual(info['attrs'].get('ENGINE'), 'moteur-temoin')
        self.assertEqual(info['attrs'].get('REQUIRED_PACKAGES'), ['torch'])

    def test_une_base_METIER_qui_n_implemente_pas_le_contrat_est_ECARTEE(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'base': self.ABSTRAITE, 'moteur': self.CLASSE})
            classes, _ = bi._class_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'],
                         'une base abstraite par HÉRITAGE ne doit pas passer pour exécutable')

    def test_un_module_dont_la_LIB_manque_reste_LISIBLE(self):
        """Gain direct du statique : un backend dont la librairie n'est pas installée
        s'inventorie quand même (c'est `moteur_installe` qui dit qu'il ne tournera pas).
        En lecture par IMPORT il disparaissait purement et simplement."""
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE.replace(
                "['torch']", "['bibliotheque_absente_xyz']")})
            classes, unreadable = bi._class_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'])
        self.assertEqual(unreadable, [])
        self.assertFalse(bi._packages_present(['bibliotheque_absente_xyz']))

    def test_un_sous_module_ILLISIBLE_est_rapporte_jamais_avale(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE,
                                      'casse': 'class Casse(:\n'})   # INSYNTAXIQUE
            classes, unreadable = bi._class_backends(paquet, 'paquet_temoin')
        self.assertEqual([n for n, _ in classes], ['MoteurTemoin'],
                         'un module cassé ne doit pas emporter les autres')
        self.assertEqual(len(unreadable), 1)
        self.assertIn('casse', unreadable[0])

    def test_une_classe_IMPORTEE_d_ailleurs_n_est_pas_comptee_deux_fois(self):
        with TemporaryDirectory() as d:
            paquet = self._paquet(d, {'moteur': self.CLASSE,
                                      'reexport': 'from .moteur import MoteurTemoin\n'})
            classes, _ = bi._class_backends(paquet, 'paquet_temoin')
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
                    'saveur': {e.flavor for a in bi.inventory() for e in a.entries},
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
                      for e in a.entries if e.kind == 'classe' and not e.engine)
        self.assertEqual(sans, [], "ces backends ne disent pas quelle librairie ils pilotent : "
                                   "ajouter `ENGINE = '<moteur>'` (contrat BaseModelBackend)")

    def test_le_vocabulaire_des_moteurs_est_PARTAGE_avec_les_modeles(self):
        """Un moteur déclaré par un backend doit pouvoir être celui qu'un modèle EXIGE :
        même graphie, sinon le lien ne se referme jamais. On vérifie l'intersection réelle —
        pas l'égalité : tous les moteurs installés n'ont pas encore un modèle qui les nomme."""
        from wama.model_manager.models import AIModel
        backends = {e.engine for a in bi.inventory() for e in a.entries if e.engine}
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
    grisait sur un paquet qu'il n'utilise pas). Aucun backend n'est isolé aujourd'hui : ce test
    tient la règle AVANT son premier client, pas après.
    """

    ISOLE = """
        from wama.common.backends.base import BaseModelBackend

        class MoteurLointain(BaseModelBackend):
            REQUIRED_PACKAGES = ['paquet_qui_n_existe_nulle_part']
            ENGINE = 'moteur-lointain'
            ISOLATION = 'venv:venvs/exemple_isole'

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
            ISOLATION = 'venv:venvs/exemple_isole'
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
            classes, _ = bi._class_backends(self._paquet(d, {'m': self.ISOLE}), 'paquet_isole')
        _, info = classes[0]
        self.assertEqual(info['attrs'].get('ISOLATION'),
                         'venv:venvs/exemple_isole')

    def test_un_backend_ISOLE_n_est_pas_grise_sur_un_paquet_absent_D_ICI(self):
        """Le cœur de la règle : `find_spec` de CE processus ne dit rien d'un autre venv."""
        self.assertFalse(bi._packages_present(['paquet_qui_n_existe_nulle_part']))
        self.assertTrue(bi._packages_present(['paquet_qui_n_existe_nulle_part'],
                                             'venv:venvs/exemple_isole'))

    def test_un_backend_NON_isole_reste_grise_sur_un_paquet_absent(self):
        """Contre-épreuve : la permissivité ne vaut QUE pour l'isolement déclaré — sinon on
        aurait échangé un verdict faux contre un verdict qui ne dit plus rien."""
        self.assertFalse(bi._packages_present(['paquet_qui_n_existe_nulle_part'], ''))

    def test_l_ISOLATION_d_une_base_metier_est_HERITEE_par_les_concrets(self):
        with TemporaryDirectory() as d:
            classes, _ = bi._class_backends(self._paquet(d, {'m': self.FAMILLE}), 'paquet_isole')
        concrets = dict(classes)
        self.assertIn('EmotionsBackend', concrets, 'le concret doit être trouvé')
        self.assertEqual(concrets['EmotionsBackend']['attrs'].get('ISOLATION'),
                         'venv:venvs/exemple_isole',
                         'un concret qui ne redéclare pas ISOLATION hérite celle de sa base '
                         '(ce que fait Python) — sinon toute famille isolée serait grisée')

    def test_un_concret_garde_SON_moteur_malgre_l_heritage(self):
        """L'héritage COMPLÈTE, il n'écrase pas : sinon deux moteurs d'une même famille
        deviendraient indiscernables."""
        with TemporaryDirectory() as d:
            classes, _ = bi._class_backends(self._paquet(d, {'m': self.FAMILLE}), 'paquet_isole')
        self.assertEqual(dict(classes)['EmotionsBackend']['attrs'].get('ENGINE'), 'emotions')

    def test_un_moteur_ISOLE_reste_EXECUTABLE_pour_known_engines(self):
        """`_MoteurDeclare` porte la même règle que le contrat commun — sinon le lien
        modèle↔moteur donnerait un verdict faux dès le premier backend porté."""
        lointain = bi._DeclaredEngine('moteur-lointain', ['paquet_qui_n_existe_nulle_part'],
                                     'venv:venvs/exemple_isole')
        local = bi._DeclaredEngine('moteur-local', ['paquet_qui_n_existe_nulle_part'])
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

class BackendRefNAbsoutPlusTest(SimpleTestCase):
    """`backend_ref` ne court-circuite PLUS le verdict d'exécutabilité (2026-09-05).

    Le champ atteste une APPARTENANCE (il porte un nom d'app), jamais une EXÉCUTABILITÉ.
    Tant qu'il absolvait, `backend_missing()` ne pouvait rien dire d'utile sur les 95 modèles
    qui le portent — et le chantier « retirer backend_ref » ne pouvait pas commencer, puisque
    rien ne mesurait ce qu'on perdrait en le retirant.

    Cette garde existe parce que le court-circuit était ÉCRIT DANS UN TEST : le remettre
    aurait donc paru légitime. *Une décision retirée sans garde revient par la porte du test
    qui l'encodait.*
    """

    def test_un_backend_ref_n_excuse_pas_un_moteur_introuvable(self):
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_missing
        verdict = backend_missing(SimpleNamespace(
            backend_ref='une_app',
            composition={'runtime': {'engine': 'moteur-qui-n-existe-pas'}}))
        self.assertIsNotNone(verdict, "backend_ref ne doit plus absoudre")
        self.assertIn('moteur-qui-n-existe-pas', verdict)

    def test_l_absence_de_moteur_declare_reste_NON_condamnee(self):
        """La contrepartie : on ne condamne pas ce qu'on ne sait pas mesurer. Sans cette
        moitié, retirer le court-circuit aurait grisé 159 modèles d'un coup."""
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_missing
        self.assertIsNone(backend_missing(SimpleNamespace(backend_ref='une_app', composition={})))
        self.assertIsNone(backend_missing(SimpleNamespace(backend_ref='', composition={})))

    def test_aucun_court_circuit_sur_backend_ref_ne_subsiste_dans_le_verdict(self):
        """Garde par AST : le motif retiré ne doit pas réapparaître dans le CODE de la fonction.

        ⚠ La 1ʳᵉ version était textuelle et accusait la DOCSTRING (« ou tout porteur de
        `composition`/`backend_ref` ») — une phrase, pas une dépendance. Troisième fois de la
        session qu'un motif textuel se trompe de cible. *Un grep lit des caractères ; seul
        l'AST lit du code.*
        """
        import ast
        from pathlib import Path
        from django.conf import settings

        source = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'backends' / 'manager.py'
                  ).read_text(encoding='utf-8')
        fonction = next(n for n in ast.parse(source).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'backend_missing')
        corps = fonction.body[1:] if ast.get_docstring(fonction) else fonction.body
        usages = [n for stmt in corps for n in ast.walk(stmt)
                  if (isinstance(n, ast.Attribute) and n.attr == 'backend_ref')
                  or (isinstance(n, ast.Constant) and n.value == 'backend_ref')]
        self.assertEqual(usages, [],
                         "`backend_ref` est redevenu ACTIF dans backend_missing — il atteste "
                         "une appartenance, pas une exécutabilité")


class ResolutionParDeclarationTest(TestCase):
    """Un backend se trouve par sa DÉCLARATION, jamais par son chemin d'import (2026-09-06).

    C'est l'étape qui rend l'emplacement physique des backends INDIFFÉRENT — préalable à leur
    déplacement vers le substrat transversal. Tant qu'on importe par chemin, tout déplacement
    casse des imports ; une fois qu'on résout par déclaration, il ne casse plus rien.
    """

    def test_le_MOTEUR_seul_ne_suffit_pas_quand_il_est_PARTAGE(self):
        """LE défaut que ce test existe pour empêcher, et qui a bien eu lieu.

        Une 1ʳᵉ version résolvait par moteur seul et rendait « le premier qui le déclare ».
        Or `diffusers` est piloté par 8 backends de l'imager : un modèle Mochi se voyait servir
        par CogVideoX — silencieusement. Le lien FIN (`SUPPORTED_MODELS`) tranche.
        """
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_for_model
        for cle, attendu in (('imager:mochi-1-preview', 'MochiBackend'),
                             ('imager:cogvideox-5b-i2v', 'CogVideoXBackend'),
                             ('imager:qwen-image-2', 'QwenImageBackend')):
            modele = SimpleNamespace(model_key=cle,
                                     composition={'runtime': {'engine': 'diffusers'}})
            classe = backend_for_model(modele)
            self.assertIsNotNone(classe, f'{cle} : aucun backend résolu')
            self.assertEqual(classe.__name__, attendu,
                             f"{cle} servi par le mauvais backend — c'est le défaut mesuré "
                             f"le 06/09, une erreur SILENCIEUSE")

    def test_l_ambiguite_rend_NONE_jamais_un_tirage(self):
        """À égalité de spécificité, on refuse. *Une erreur silencieuse coûte plus qu'un refus.*"""
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_for_model
        inconnu = SimpleNamespace(model_key='imager:modele-que-personne-ne-declare',
                                  composition={'runtime': {'engine': 'diffusers'}})
        self.assertIsNone(backend_for_model(inconnu))

    def test_un_porteur_HORS_PROCESSUS_n_est_jamais_rendu_comme_backend(self):
        """`ollama` est un DÉMON : son porteur est une classe, mais pas un `BaseModelBackend`.

        Une 1ʳᵉ version le rendait — l'appelant aurait cru tenir un backend et cherché un
        `load()` qui n'existe pas. On ne rend QUE le contrat.
        """
        from wama.common.backends.manager import backend_for_engine
        self.assertIsNone(backend_for_engine('ollama'))
        self.assertIsNone(backend_for_engine('moteur-qui-n-existe-pas'))
        self.assertIsNone(backend_for_engine(''))

    def test_ce_qui_est_resolu_EST_un_backend_au_contrat(self):
        from wama.common.backends.base import BaseModelBackend
        from wama.common.backends.manager import backend_for_engine, known_engines
        for moteur in sorted(known_engines()):
            classe = backend_for_engine(moteur)
            if classe is None:
                continue                      # hors processus, ou moteur partagé sans model_id
            self.assertTrue(issubclass(classe, BaseModelBackend),
                            f'{moteur} rend {classe!r}, qui n\'est pas au contrat commun')

    def test_tout_modele_a_moteur_DANS_LE_PROCESSUS_se_resout(self):
        """INVARIANT de non-régression : un modèle qui déclare un moteur piloté par du code
        Python DOIT trouver son backend. Les exceptions sont NOMMÉES, pas tolérées en masse.
        """
        from wama.common.backends.manager import backend_for_model, known_engines
        from wama.model_manager.models import AIModel
        #: Moteurs qui ne sont PAS du code Python qu'on charge — ils n'auront jamais de classe.
        HORS_PROCESSUS = {'ollama', 'audio-cpp'}
        orphelins = []
        for m in AIModel.objects.all():
            if m.is_proposed:
                continue
            moteur = ((m.composition or {}).get('runtime') or {}).get('engine') or ''
            if not moteur or moteur in HORS_PROCESSUS or moteur not in known_engines():
                continue                      # sans moteur, hors processus, ou moteur absent
            if backend_for_model(m) is None:
                orphelins.append(f'{m.model_key} ({moteur})')
        self.assertEqual(sorted(orphelins), [],
                         "ces modèles déclarent un moteur piloté par du code Python mais ne "
                         "résolvent AUCUN backend : il manque un `SUPPORTED_MODELS` sur le "
                         "backend qui les sert (le moteur seul ne tranche pas quand il est "
                         "partagé)")


class BackendsDecouplesDeLeurAppTest(SimpleTestCase):
    """Un backend ne doit pas importer le `model_config` de son app (étape 2, 2026-09-06).

    Tant que le backend vit DANS l'app, l'import est anodin. Le jour où il rejoint le substrat
    transversal — c'est le plan —, ce serait **le commun qui importerait une app** : inversion
    de couche interdite. La garde est posée MAINTENANT, pendant que le compte est à zéro : une
    règle qu'on n'installe qu'au moment d'en avoir besoin arrive toujours après la dette.

    Le remplacement est `common/utils/model_declarations.declaration()` — un passe-plat qui
    applique la CONVENTION `<APP>_MODELS` sans connaître aucune app, et **sans ORM** : c'est
    l'absence de Django qui rend un backend déplaçable, lire le catalogue la détruirait.
    """

    #: {module: raison} — couplages ASSUMÉS. **VIDE**, et c'est le résultat, pas un point
    #: de départ : les 15 sites mesurés le 06/09 sont tous levés.
    #:
    #: ⚠ Cette liste a d'abord contenu `diffusers_backend` et `hunyuan_video_backend`, que
    #: j'avais classés « logique métier, à remonter dans le commun » SANS AVOIR LU le corps
    #: des helpers. Vérification faite : ce sont des accesseurs d'une ligne (`Path(<CONST>)`,
    #: `str(<CONST>)`), et trois des symboles importés n'étaient même jamais appelés.
    #: *Classer sans lire, c'est décider sans savoir* — une entrée d'exception assumée doit
    #: se mériter par une mesure, sinon elle sanctuarise une dette imaginaire.
    COUPLAGES_ASSUMES = {}

    def test_aucun_backend_n_importe_le_model_config_de_son_app(self):
        import ast
        from django.conf import settings

        racine = Path(settings.BASE_DIR)
        coupables = []
        for dossier in ('wama', 'wama_lab'):
            for f in (racine / dossier).rglob('backends/*.py'):
                if 'venv' in f.parts or 'site-packages' in f.parts or '_01' in str(f):
                    continue                      # jumelles de bac à sable : copies, pas des sources
                try:
                    arbre = ast.parse(f.read_text(encoding='utf-8'))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                # AST, jamais grep : trois motifs textuels se sont trompés de cible cette
                # session en accusant des commentaires ou des docstrings.
                for n in ast.walk(arbre):
                    module = (n.module or '') if isinstance(n, ast.ImportFrom) else ''
                    if isinstance(n, ast.Import):
                        module = next((a.name for a in n.names if 'model_config' in a.name), '')
                    if module.startswith('wama.') and module.endswith('utils.model_config'):
                        coupables.append(str(f.relative_to(racine)).replace(chr(92), '/'))
        surprise = sorted(set(coupables) - set(self.COUPLAGES_ASSUMES))
        self.assertEqual(surprise, [],
                         "un backend importe le model_config d'une app : utiliser "
                         "`common/utils/model_declarations.declaration()` (déclarations) ou "
                         "`settings.MODEL_PATHS` (chemins de poids)")

    def test_le_passe_plat_ne_connait_aucune_app(self):
        """Contre-épreuve : il applique la convention, il ne contient pas de nom d'app."""
        from django.conf import settings
        source = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'utils'
                  / 'model_declarations.py').read_text(encoding='utf-8')
        import ast
        arbre = ast.parse(source)
        noms = [n for n in ast.walk(arbre)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value.startswith('wama.') and 'model_config' in n.value
                and '{' not in n.value]
        self.assertEqual(noms, [], "le passe-plat cite une app en dur : il doit DÉRIVER le "
                                   "chemin de module, jamais l'énumérer")

    def test_la_declaration_se_lit_sans_base_de_donnees(self):
        """L'invariant qui justifie de ne PAS lire le catalogue : aucune requête n'est faite."""
        from django.db import connection
        from wama.common.utils.model_declarations import declaration
        avant = len(connection.queries)
        self.assertTrue(declaration('composer', 'musicgen-small'))
        self.assertEqual(len(connection.queries), avant,
                         'lire une déclaration ne doit toucher aucune base')
