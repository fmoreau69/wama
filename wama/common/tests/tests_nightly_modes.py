"""Modes du runner nocturne — le mode « sans GPU » est-il RÉEL ?

⚠⚠ POURQUOI CE FICHIER (2026-09-06, question de Fabien : « on a normalement des modes dans les
tests nocturnes pour n'effectuer que des parties des tests, notamment pour écarter les tests
mettant en œuvre le GPU. On est ok ? »).

La réponse mesurée était **non, pas vraiment** : `Scenario.vram_gb` était déclaré sur chaque
scénario depuis l'origine — commenté « info de planification » — et **lu par personne**. Aucun
filtre ne s'en servait. L'exclusion du GPU reposait entièrement sur le fait de SAVOIR que les
étages `model_loaded` et `output` sont les étages GPU, et sur la discipline de passer
`--stage ui`.

*Un champ qui a l'air d'une garde sans en être une est pire qu'un champ absent : il fait croire
que la protection existe.* Ces tests sont ce qui empêche la garde de redevenir décorative.
"""

from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from wama.common.services import nightly_tests


class ModeSansGpuTest(SimpleTestCase):
    """Le plafond de VRAM filtre-t-il RÉELLEMENT, et le dit-il ?"""

    def setUp(self):
        # Registre isolé : on ne dépend pas de ce que les apps enregistrent (le parc bouge),
        # et on ne laisse rien derrière. Trois scénarios suffisent à couvrir les trois cas.
        self._registre = nightly_tests.REGISTRY
        nightly_tests.REGISTRY = []
        for ident, vram in (('t.cpu', 0.0), ('t.leger', 1.0), ('t.lourd', 10.0)):
            nightly_tests.register(
                id=ident, app='t', stage='ui', description=f'témoin {ident}',
                run=lambda ctx: (True, 'témoin'), vram_gb=vram,
            )

    def tearDown(self):
        nightly_tests.REGISTRY = self._registre

    def _lister(self, *args):
        sortie = StringIO()
        call_command('run_nightly_tests', '--dry-run', *args, stdout=sortie)
        return sortie.getvalue()

    def test_par_defaut_les_scenarios_a_vram_sont_ecartes(self):
        """Le défaut est l'EXCLUSION — décision Fabien : le passage nocturne est sans GPU."""
        texte = self._lister()
        self.assertIn('t.cpu', texte)
        self.assertNotIn('t.leger (cible', texte)
        self.assertNotIn('t.lourd (cible', texte)

    def test_l_exclusion_n_est_JAMAIS_silencieuse(self):
        """Une exclusion muette se lit comme une couverture — c'est le faux vert que tout
        `WAMA_VERIFICATION` traque. Le runner doit NOMMER ce qu'il écarte et dire comment
        le rejouer."""
        texte = self._lister()
        self.assertIn('ÉCARTÉ', texte)
        self.assertIn('t.leger', texte)
        self.assertIn('t.lourd', texte)
        self.assertIn('--with-gpu', texte, "le message doit dire comment les jouer")

    def test_avec_gpu_les_reintegre_tous(self):
        texte = self._lister('--with-gpu')
        for ident in ('t.cpu', 't.leger', 't.lourd'):
            self.assertIn(ident, texte)

    def test_un_plafond_intermediaire_trie_par_VRAM_declaree(self):
        """`--max-vram` sert le jour où l'on rouvrira le GPU progressivement : jouer les
        scénarios légers sans les lourds, plutôt que tout ou rien."""
        texte = self._lister('--max-vram', '2')
        self.assertIn('t.cpu', texte)
        self.assertIn('t.leger', texte)
        self.assertNotIn('t.lourd (cible', texte)


class DeclarationVramTest(SimpleTestCase):
    """Hygiène des déclarations sur le registre RÉEL — le filtre ne vaut que ce qu'elles valent.

    ⚠ Ce contrôle ne peut PAS attester qu'un scénario déclaré à 0 ne touche pas le GPU par un
    chemin détourné : le triage VLM d'une batterie UI a provoqué deux crashs hôte le 02/09 en
    étant, lui, parfaitement « sans VRAM déclarée ». La déclaration ENGAGE son auteur ; ce test
    vérifie seulement qu'elle est exploitable.
    """

    def test_toute_declaration_de_vram_est_un_nombre_positif(self):
        from wama.common.services.nightly_tests import REGISTRY, register_examples
        register_examples()
        # ⚠ Un contrôle sur un registre VIDE passe toujours — « 0 FAIL sur du VIDE », piège
        # déjà rencontré deux fois dans ce dépôt (project_backend_capabilities). On exige
        # d'abord d'avoir quelque chose à contrôler.
        self.assertGreater(len(REGISTRY), 50,
                           "registre quasi vide : ce test ne contrôlerait rien")
        fautifs = [s.id for s in REGISTRY
                   if not isinstance(s.vram_gb, (int, float)) or s.vram_gb < 0]
        self.assertEqual([], fautifs,
                         f"vram_gb inexploitable (le filtre les laisserait passer) : {fautifs}")

    def test_les_scenarios_qui_CHARGENT_un_modele_declarent_leur_VRAM(self):
        """Un scénario d'étage `model_loaded` charge un backend par définition : sans VRAM
        déclarée, il passerait dans un passage « sans GPU » sans que rien ne l'arrête.

        ⚠ L'étage `output` n'est PAS soumis à la même exigence, et ce n'est pas un oubli :
        `studio.pipeline.converter` va jusqu'au résultat en ffmpeg pur (CPU), et lui imposer
        une VRAM fictive l'exclurait du passage nocturne sans aucune raison. C'est la CHARGE
        qui décide, pas la profondeur.
        """
        from wama.common.services.nightly_tests import REGISTRY, register_examples
        register_examples()
        etage = [s for s in REGISTRY if s.stage == 'model_loaded']
        self.assertTrue(etage, "aucun scénario `model_loaded` : rien à contrôler ici")
        muets = [s.id for s in REGISTRY if s.stage == 'model_loaded' and not (s.vram_gb or 0)]
        self.assertEqual([], muets,
                         f"étage `model_loaded` sans vram_gb — jouerait en mode sans GPU : {muets}")

    def test_les_gestes_verses_du_bloc_notes_le_13_09_sont_bien_au_registre(self):
        """Les sondes de session qui ont trouvé le bloc d'appariement MORT de l'avatarizer,
        « auto » grisé par une voix clonée et `three.core.js` absent (13/09) vivent désormais
        dans `ui_smoke_matching` — et un module de scénarios qu'on oublie d'ENREGISTRER est
        exactement une sonde qui meurt avec sa session, en plus discret."""
        from wama.common.services.nightly_tests import REGISTRY, register_examples
        register_examples()
        ids = {s.id: s for s in REGISTRY}
        for attendu, app in (('synthesizer.voice_language_matching', 'synthesizer'),
                             ('avatarizer.voice_language_matching', 'avatarizer'),
                             ('media_library.natures_3d', 'media_library')):
            self.assertIn(attendu, ids, f'{attendu} absent du registre nocturne')
            self.assertEqual(ids[attendu].app, app)
            self.assertEqual(ids[attendu].stage, 'ui')

    def test_les_gestes_de_MENU_verses_le_14_09_sont_bien_au_registre(self):
        """Question de Fabien (14/09) : « tu as ajouté tous les tests nécessaires, y compris pour
        les menus contextuels ? » — le comportement n'était attesté que par une sonde de session.
        Versés dans `ui_smoke_menus` ; un module qu'on oublie d'ENREGISTRER les ferait mourir en
        silence, comme la sonde qu'ils remplacent."""
        from wama.common.services.nightly_tests import REGISTRY, register_examples
        register_examples()
        ids = {s.id: s for s in REGISTRY}
        for attendu, app in (('common.tree_menu_keyboard', 'common'),
                             ('common.tree_send_to_menus', 'common'),
                             ('media_library.card_menu_state', 'media_library'),
                             ('common.nav_sandbox_keyboard', 'common')):
            self.assertIn(attendu, ids, f'{attendu} absent du registre nocturne')
            self.assertEqual(ids[attendu].app, app)
            self.assertEqual(ids[attendu].stage, 'ui')
            self.assertFalse(ids[attendu].vram_gb, f'{attendu} ne charge aucun modèle')


class CadenceTest(SimpleTestCase):
    """Two cadences (2026-10-13, Fabien: « distinguish the tests that must run every night and are
    short from those that can run weekly, on a weekend night »). The rule is DERIVED from what a
    scenario already declares; a declaration overrides it."""

    def setUp(self):
        self._registry = nightly_tests.REGISTRY
        nightly_tests.REGISTRY = []
        for ident, app, stage, vram, cadence in (
                ('t.gesture', 't', 'ui', 0.0, None),
                ('t.suite', 't', 'suite', 0.0, None),
                ('t.processing', 't', 'ui', float('inf'), None),
                ('t.load', 't', 'model_loaded', 10.0, None),
                ('t_01.gesture', 't_01', 'ui', 0.0, None),
                ('t.declared', 't', 'ui', 0.0, 'weekly')):
            nightly_tests.register(id=ident, app=app, stage=stage, description=ident,
                                   run=lambda ctx: (True, ''), vram_gb=vram, cadence=cadence)

    def tearDown(self):
        nightly_tests.REGISTRY = self._registry

    def _ids(self, cadence):
        from unittest import mock
        with mock.patch.object(nightly_tests, '_sandbox_apps', return_value={'t_01'}):
            return [s.id for s in nightly_tests.select_scenarios(cadence=cadence)]

    def test_a_short_gesture_of_a_real_app_runs_every_night(self):
        self.assertEqual(['t.gesture'], self._ids('daily'))

    def test_suites_gpu_twins_and_declared_scenarios_wait_for_the_weekend(self):
        self.assertEqual({'t.suite', 't.processing', 't.load', 't_01.gesture', 't.declared'},
                         set(self._ids('weekly')))

    def test_the_weekly_night_loads_its_models_first(self):
        """They load in the campaign's own process: before its processing gestures occupy the
        card, not after."""
        self.assertEqual('t.load', self._ids('weekly')[0])

    def test_no_cadence_is_every_scenario_and_an_unknown_one_is_refused(self):
        self.assertEqual(6, len(self._ids(None)))
        with self.assertRaises(ValueError):
            nightly_tests.select_scenarios(cadence='monthly')
        with self.assertRaises(ValueError):
            nightly_tests.register(id='t.bad', app='t', stage='ui', description='',
                                   run=lambda ctx: (True, ''), cadence='hourly')

    def test_the_command_plays_the_same_selection(self):
        out = StringIO()
        from unittest import mock
        with mock.patch.object(nightly_tests, '_sandbox_apps', return_value={'t_01'}):
            call_command('run_nightly_tests', '--dry-run', '--cadence', 'daily', stdout=out)
        self.assertIn('t.gesture', out.getvalue())
        self.assertNotIn('t.suite', out.getvalue())

    def test_the_scheduled_task_passes_its_cadence_to_the_selection_and_the_report(self):
        from unittest import mock
        from wama.common import tasks
        with mock.patch.object(nightly_tests, '_sandbox_apps', return_value={'t_01'}), \
                mock.patch.object(nightly_tests, 'run_all',
                                  return_value={'summary': {}}) as run_all:
            tasks.run_nightly_tests_task(cadence='daily')
        played, kwargs = run_all.call_args
        self.assertEqual(['t.gesture'], [s.id for s in played[0]])
        self.assertEqual('daily', kwargs['cadence'])


class CadenceOnTheRealRegistryTest(SimpleTestCase):
    """On the registry the apps really fill: the nightly part stays SHORT and GPU-free."""

    def test_the_daily_cadence_needs_no_gpu_and_runs_no_django_suite(self):
        from wama.common.services.nightly_tests import register_examples
        register_examples()
        daily = nightly_tests.select_scenarios(cadence='daily')
        weekly = nightly_tests.select_scenarios(cadence='weekly')
        self.assertGreater(len(daily), 50, 'registry nearly empty: nothing measured here')
        self.assertTrue(weekly)
        self.assertEqual([], [s.id for s in daily if (s.vram_gb or 0) > 0 or s.stage == 'suite'])

    def test_the_consistency_checks_run_once_a_night_under_their_own_entry(self):
        """They have their entry at 04:15; the full campaign played them again at 04:30
        (report of 2026-10-13). A cadence campaign leaves them out."""
        from wama.common.services.nightly_tests import register_examples
        register_examples()
        own = nightly_tests.select_scenarios(stage='consistency')
        self.assertTrue(own)
        for cadence in nightly_tests.CADENCES:
            self.assertEqual([], [s.id for s in nightly_tests.select_scenarios(cadence=cadence)
                                  if s.stage == 'consistency'], cadence)
