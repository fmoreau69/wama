"""Cohérence d'une app GÉNÉRÉE — ce que les gabarits ÉMETTENT × ce que les fichiers COPIÉS
consomment, et les juges qui refusent une jumelle incohérente.

POURQUOI CE FICHIER (2026-09-03, constats écran Fabien sur `describer_01` : « je ne peux pas
importer depuis filemanager », « aucun bouton d'action ne fonctionne », « pas de preview, pas
de réglages » — demande explicite : *« qu'une nouvelle génération ne redécouvre pas les mêmes
problèmes »*).

Les trois défauts du jour avaient la même forme — **une jumelle qui REND (HTTP 200) et qui ne
FONCTIONNE PAS** — et aucun contrôle ne les voyait : `manifest_roundtrip` mesure la
projetabilité, la grille l'adoption, le smoke de substitution ne demandait qu'un 200 sur une
file VIDE. Chaque test ci-dessous tient la CLASSE du défaut, jamais son exemplaire :

  1. `params_gen` n'exposait que `PARAMS_JSON` ; le `models.py` COPIÉ importe `PARAMS` dans une
     property → ImportError **au rendu de chaque card** (file « vide », page 200) ;
  2. templates GÉNÉRÉS × views COPIÉES = paire incohérente (l'index généré inclut la card
     générique, les vues copiées rendent l'autre partial) → boutons morts ;
  3. le corps composé de `tasks_gen` doit rendre les DEUX saveurs (fichier / texte) sans
     accolade doublée dans ses f-strings.

⚠ Ne pas remplacer ces assertions par des `assertIn('PARAMS', src)` : une sous-chaîne dit que
le gabarit a écrit quelque chose, pas que le paquet RÉSOUT. Le juge d'imports travaille par AST
et couvre les imports PARESSEUX — c'est précisément là que vivait le défaut `PARAMS`, et un
simple `import_module` du paquet ne l'aurait jamais levé.
"""
import ast
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from wama.common.management.commands import app_sandbox as cmd_sandbox
from wama.common.manifests.codegen.params_gen import render_params
from wama.common.manifests.codegen.tasks_gen import render_tasks


def _manifeste(routes=None, result=None, nature=None, schemas=None):
    """Manifeste MINIMAL portant de quoi composer — écrit à la main (jamais extrait) : ces
    tests jugent les GABARITS, pas l'état de l'arbre."""
    return {
        'key': 'appfictive',
        'name': 'App Fictive',
        'body': {
            'params': {'primary': 'PARAMS_JSON',
                       'schemas': schemas or {'PARAMS_JSON': [{'name': 'quality', 'type': 'range'}]}},
            'processing': {
                'item_model': 'ItemFictif',
                'tasks': [{'function': 'traiter_item', 'task_name': None, 'lifecycle': True}],
                'model_spec': {'item': {'params_fields': ['quality', 'output_format']}},
                **({'backend_routes': routes} if routes else {}),
                **({'backend_result': result} if result else {}),
                **({'backend_nature_field': nature} if nature else {}),
            },
        },
    }


class SymbolesPublicsDuParamsGenereTest(SimpleTestCase):
    """Défaut n°1 : le généré doit exposer les DEUX graphies du schéma."""

    def test_chaque_schema_JSON_expose_aussi_sa_graphie_courte(self):
        src, _ = render_params(_manifeste(schemas={
            'PARAMS_JSON': [{'name': 'a'}], 'AUDIO_PARAMS_JSON': [{'name': 'b'}]}))
        espace = {}
        exec(compile(src, '<params_gen>', 'exec'), espace)     # noqa: S102 — c'est le sujet
        self.assertIn('PARAMS', espace, "le models COPIÉ importe la graphie courte")
        self.assertIn('AUDIO_PARAMS', espace, 'la règle vaut pour TOUS les schémas, pas le premier')
        self.assertIs(espace['PARAMS'], espace['PARAMS_JSON'],
                      'alias, jamais une seconde liste qui pourrait diverger')

    def test_un_schema_deja_court_ne_produit_pas_d_alias_absurde(self):
        src, _ = render_params(_manifeste(schemas={'PARAMS': [{'name': 'a'}]}))
        self.assertNotIn('PARAMS = PARAMS', src)


class ParamsRenderedAsLiteralsTest(SimpleTestCase):
    """A live-extracted schema carries the model's own objects: a `TextChoices` member rendered
    by its `repr` (`ReadingItem.Backend.AUTO`) — NameError on import, twin page 404
    (reader_01, 2026-10-07)."""

    def test_a_choices_member_is_written_as_its_value(self):
        from django.db import models

        class Backend(models.TextChoices):
            AUTO = 'auto', 'Auto'

        src, _ = render_params(_manifeste(schemas={'PARAMS_JSON': [
            {'name': 'backend', 'default': Backend.AUTO, 'contexts': ('item', 'panel')}]}))
        space = {}
        exec(compile(src, '<params_gen>', 'exec'), space)     # noqa: S102 — c'est le sujet
        param = space['PARAMS_JSON'][0]
        self.assertEqual(param['default'], 'auto')
        self.assertIs(type(param['default']), str)
        self.assertEqual(param['contexts'], ('item', 'panel'), 'tuples stay tuples')

    def test_a_value_that_is_no_literal_is_named_at_generation(self):
        # Counter-check: an arbitrary object is refused HERE, not by a NameError at import.
        with self.assertRaisesRegex(ValueError, 'non littérale'):
            render_params(_manifeste(schemas={'PARAMS_JSON': [{'name': 'a', 'default': object()}]}))

    def test_the_generated_params_carry_the_common_storage_key_like_the_real_apps(self):
        """Every real `params.py` declares its settings storage key since the birth cascade
        (`user_setting_key`, 2026-10-18); the template did not, and COPIED views importing it sent
        `params` back to the witness on four twins (2026-10-20). For an app on the common rule the
        generated defaults equal the real ones."""
        from wama.common.manifests.ingest import extract
        from wama.describer import params as real
        src, _ = render_params(extract('app', 'describer'))
        space = {}
        exec(compile(src, '<params_gen>', 'exec'), space)     # noqa: S102 — c'est le sujet
        self.assertIn('user_setting_key', space)
        self.assertEqual(real.USER_SETTINGS_DEFAULTS, space['USER_SETTINGS_DEFAULTS'])
        # Counter-check: a schema without a main `PARAMS_JSON` declares no key of its own.
        other, _ = render_params(_manifeste(schemas={'AUDIO_PARAMS_JSON': [{'name': 'a'}]}))
        self.assertNotIn('user_setting_key', other)


class CorpsComposeDesDeuxSaveursTest(SimpleTestCase):
    """Défaut n°3 : les deux saveurs (`RESULT.kind`) se composent, et compilent."""

    ROUTES_TEXTE = {'image': 'backends.image_backend.decrire'}
    ROUTES_FICHIER = {'image': 'backends.image_backend.convertir'}

    def test_la_saveur_TEXTE_persiste_le_retour_dans_la_colonne_declaree(self):
        src, _ = render_tasks(_manifeste(
            routes=self.ROUTES_TEXTE, nature='detected_type',
            result={'kind': 'text', 'field': 'result_text'}))
        ast.parse(src)
        self.assertIn("'result_text': texte", src)
        self.assertIn('partial_callback', src, "l'aperçu PENDANT fait partie du contrat texte")
        self.assertNotIn('output_file', src, 'la saveur texte ne range aucun fichier')

    def test_la_saveur_FICHIER_reste_celle_du_pilote_quand_RESULT_est_absent(self):
        src, _ = render_tasks(_manifeste(routes=self.ROUTES_FICHIER, nature='media_type'))
        ast.parse(src)
        self.assertIn('output_file', src)
        self.assertNotIn('partial_callback', src)

    def test_aucune_accolade_doublee_dans_les_f_strings_des_deux_saveurs(self):
        # Le message d'erreur perdait sa valeur (« nature {nature!r} » rendu littéralement) —
        # défaut hérité du pilote, latent chez converter_01 car jamais déclenché. Depuis le
        # 2026-10-05 ce message vit dans la porte commune (`route_for_nature`, gardée par
        # `tests_route_for_nature`) ; les f-strings qui RESTENT dans le corps sont celles de la
        # console, qui nomment la fonction et la nature.
        for result in ({'kind': 'text', 'field': 'result_text'}, None):
            src, _ = render_tasks(_manifeste(routes=self.ROUTES_TEXTE, nature='detected_type',
                                             result=result))
            self.assertIn('({fonc})', src)
            self.assertNotIn('{{fonc', src)
            self.assertNotIn('{{nature', src)

    def test_sans_routes_le_TROU_reste_marque_plutot_qu_invente(self):
        src, _ = render_tasks(_manifeste())
        self.assertIn('NotImplementedError', src)

    def test_une_saveur_texte_sans_colonne_declaree_ne_compose_PAS(self):
        # Déclaration incomplète → trou marqué, jamais un corps qui écrirait n'importe où.
        src, _ = render_tasks(_manifeste(routes=self.ROUTES_TEXTE, nature='detected_type',
                                         result={'kind': 'text'}))
        self.assertIn('NotImplementedError', src)


class JugeDeCoherenceDuPaquetTest(SimpleTestCase):
    """Défaut n°1, généralisé : tout `from .x import Y` intra-paquet doit RÉSOUDRE.

    Le paquet est FABRIQUÉ en temporaire (jamais l'arbre courant : un test qui lit l'arbre
    mesure l'arbre — leçon du même jour sur `sandbox_apps.json`, gitignoré).
    """

    def _paquet(self, racine, params_src, models_src):
        p = Path(racine) / 'jumelle_00'
        p.mkdir()
        (p / '__init__.py').write_text('', encoding='utf-8')
        (p / 'params.py').write_text(params_src, encoding='utf-8')
        (p / 'models.py').write_text(models_src, encoding='utf-8')
        return p

    #: L'import vit dans une PROPERTY — la forme exacte du défaut `gear_data` du 03/09.
    MODELS_PARESSEUX = (
        'class Item:\n'
        '    @property\n'
        '    def gear_data(self):\n'
        '        from .params import PARAMS\n'
        '        return PARAMS\n'
    )

    def test_un_symbole_importe_ABSENT_de_sa_cible_est_nomme(self):
        with TemporaryDirectory() as d:
            self._paquet(d, 'PARAMS_JSON = [1]\n', self.MODELS_PARESSEUX)
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                manquants = cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00')
        self.assertEqual(len(manquants), 1, 'un défaut, un signalement')
        self.assertIn('models.py', manquants[0])
        self.assertIn('PARAMS', manquants[0])
        self.assertIn('params', manquants[0], 'le message nomme la CIBLE, pas seulement le manque')

    def test_l_alias_de_compatibilite_suffit_a_faire_taire_le_juge(self):
        with TemporaryDirectory() as d:
            self._paquet(d, 'PARAMS_JSON = [1]\nPARAMS = PARAMS_JSON\n', self.MODELS_PARESSEUX)
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00'), [])

    def test_un_import_EXTERNE_au_paquet_n_est_jamais_reproche(self):
        with TemporaryDirectory() as d:
            self._paquet(d, 'PARAMS_JSON = [1]\n',
                         'from django.db import models\n'
                         'from wama.common.utils.card_gear import gear_data\n')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00'), [])

    def test_un_symbole_RE_EXPORTE_par_import_compte_comme_expose(self):
        # `from .backends import get_blip` puis `from .models import get_blip` ailleurs :
        # une ré-exportation est une exposition légitime, pas un manque.
        with TemporaryDirectory() as d:
            p = self._paquet(d, 'PARAMS_JSON = [1]\n', 'from .params import PARAMS_JSON\n')
            (p / 'views.py').write_text('from .models import PARAMS_JSON\n', encoding='utf-8')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00'), [])

    def test_a_name_set_inside_a_module_level_try_is_exposed(self):
        # `MODELS_ROOT` of the anonymizer lives in a `try/except ImportError` (2026-10-07).
        with TemporaryDirectory() as d:
            p = self._paquet(d, 'try:\n    import x\n    ROOT = 1\nexcept ImportError:\n'
                                '    ROOT = 2\n', 'from .params import ROOT\n')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00'), [])
            # Counter-check: a name local to a FUNCTION is not exposed by the module.
            (p / 'params.py').write_text('def f():\n    ROOT = 1\n', encoding='utf-8')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(len(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00')), 1)

    def test_importing_a_submodule_of_the_package_is_resolved(self):
        with TemporaryDirectory() as d:
            p = self._paquet(d, 'PARAMS_JSON = [1]\n', 'from wama.jumelle_00 import params\n')
            (p / 'tests.py').write_text('from . import models\n', encoding='utf-8')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00'), [])
                # Counter-check: an absent name is still reported.
                (p / 'views.py').write_text('from wama.jumelle_00 import nothing\n', encoding='utf-8')
                self.assertEqual(len(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00')), 1)


class RegistryWritesRereadTest(SimpleTestCase):
    """Chaque écriture du registre relit ce qu'il contient À L'INSTANT (2026-10-07 : un
    `remove` qui réécrivait la liste chargée à son début a effacé deux jumelles créées
    pendant son `migrate zero` par une autre chaîne)."""

    def _store(self, entries):
        store = {'entries': [dict(e) for e in entries]}
        return (store,
                patch.object(cmd_sandbox, 'load_registry',
                             side_effect=lambda: [dict(e) for e in store['entries']]),
                patch.object(cmd_sandbox, 'save_registry',
                             side_effect=lambda out: store.update(entries=list(out))))

    def test_removing_a_twin_keeps_one_registered_meanwhile(self):
        store, load, save = self._store([{'label': 'describer_01'}])
        with load, save:
            # Une autre chaîne enregistre sa jumelle PENDANT le retrait…
            cmd_sandbox._save_entry({'label': 'reader_01'})
            cmd_sandbox._drop_entry('describer_01')
        self.assertEqual([e['label'] for e in store['entries']], ['reader_01'])

    def test_saving_an_entry_replaces_only_that_entry(self):
        # Contre-épreuve : la mise à jour d'une entrée ne touche pas les autres.
        store, load, save = self._store([{'label': 'a_01', 'stage': 'x'}, {'label': 'b_01'}])
        with load, save:
            cmd_sandbox._save_entry({'label': 'a_01', 'stage': 'y'})
        self.assertEqual(store['entries'], [{'label': 'a_01', 'stage': 'y'}, {'label': 'b_01'}])


class LostModelMembersJudgeTest(SimpleTestCase):
    """La glu d'un modèle (properties, méthodes, constantes de classe) n'est pas dans la
    facette `data` : un `models` GÉNÉRÉ la perd. Mesuré sur `converter_02` le 2026-10-07 —
    smokes verts, `tasks.py` copié lisant `job.options` : AttributeError au premier lancement.
    Paquet FABRIQUÉ en temporaire, comme le juge des imports."""

    COPIED = (
        'from django.db import models\n'
        'class Job(models.Model):\n'
        '    quality = models.IntegerField(null=True)\n'
        '    CROSS = ("upscale",)\n'
        '    @property\n'
        '    def options(self):\n'
        '        return {"quality": self.quality}\n'
        '    def __str__(self):\n'
        '        return "job"\n'
    )
    GENERATED = (
        'from django.db import models\n'
        'class Job(models.Model):\n'
        '    quality = models.IntegerField(null=True)\n'
    )

    def _package(self, root, reader_src, generated=GENERATED, template=''):
        p = Path(root) / 'jumelle_00'
        p.mkdir()
        (p / 'models.py.temoin').write_text(self.COPIED, encoding='utf-8')
        (p / 'models.py').write_text(generated, encoding='utf-8')
        (p / 'tasks.py').write_text(reader_src, encoding='utf-8')
        if template:
            (p / 'templates').mkdir()
            (p / 'templates' / 'card.html').write_text(template, encoding='utf-8')
        return p

    def _judge(self, *args, **kwargs):
        with TemporaryDirectory() as d:
            self._package(d, *args, **kwargs)
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                return cmd_sandbox._lost_model_members_read('jumelle_00')

    def test_a_lost_member_still_read_is_named_with_its_line(self):
        found = self._judge('def run(job):\n    x = 1\n    return job.options, job.CROSS\n')
        self.assertEqual(found, ['tasks.py:3 .CROSS', 'tasks.py:3 .options'])

    def test_a_member_nobody_reads_is_not_reproached(self):
        # Perdre une glu que plus rien ne lit est exactement ce qu'une régénération doit pouvoir faire.
        self.assertEqual(self._judge('def run(job):\n    return job.quality\n'), [])

    def test_a_member_the_views_set_by_name_is_not_lost(self):
        # Les vues générées posent `options` sur l'élément (`_set_unless_property`) : il existe.
        src = ('def ctx(item):\n    _set_unless_property(item, "options", {})\n'
               '    return item.options\n')
        self.assertEqual(self._judge(src), [])

    def test_a_member_still_held_by_another_generated_class_is_not_reproached(self):
        # Le receveur n'est pas typé : un nom encore porté ailleurs ne lève pas.
        generated = self.GENERATED + ('class Profile(models.Model):\n'
                                      '    options = models.JSONField(default=dict)\n')
        self.assertEqual(self._judge('def run(p):\n    return p.options\n', generated=generated), [])

    RENDERS_CARD = 'def card(r):\n    return render(r, "jumelle_00/card.html")\n'

    def test_a_template_reads_it_inside_its_tags_only(self):
        # Le JS inline (`select.options`) n'est pas une lecture de modèle.
        tpl = '<script>s.options.length</script>\n{{ elem.options }}\n'
        self.assertEqual(self._judge(self.RENDERS_CARD, template=tpl),
                         ['templates/card.html:2 .options'])

    def test_a_copied_template_nothing_renders_any_more_is_not_a_reader(self):
        # Contre-épreuve : vues et index générés ne citent plus l'ancienne card copiée.
        self.assertEqual(self._judge('x = 1\n', template='{{ elem.options }}\n'), [])


class TwinRelatedNamesTest(SimpleTestCase):
    """A twin's relations to EXTERNAL models (User…) get suffixed accessors, or they clash with
    the source's (E304/E305). `related_query_name` clashes like `related_name`: enhancer_01
    failed its system check from creation on (2026-10-07)."""

    SRC = ("class Batch(models.Model):\n    pass\n"
           "class Settings(models.Model):\n"
           "    user = models.OneToOneField(User, on_delete=models.CASCADE,\n"
           "        related_name='app_settings', related_query_name='app_settings')\n"
           "    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name='items')\n")

    def test_both_reverse_names_of_an_external_relation_are_suffixed(self):
        out = cmd_sandbox._patch_related_names(self.SRC, 'app_01')
        self.assertIn("related_name='app_settings_app_01'", out)
        self.assertIn("related_query_name='app_settings_app_01'", out)

    def test_an_internal_relation_keeps_its_accessor(self):
        # Counter-check: the app's own code reads `batch.items`.
        self.assertIn("related_name='items'", cmd_sandbox._patch_related_names(self.SRC, 'app_01'))


class CopiedOriginalTestsMeasureConvergenceTest(SimpleTestCase):
    """The original app's own tests, copied into its twin, MEASURE convergence (decision of
    2026-10-07): they do not judge a substitution, and the full suite leaves them out — only
    `app_sandbox converge <twin>` runs them, against the twin."""

    def test_what_a_test_module_is(self):
        from wama.common.sandbox import is_test_module
        for parts in (['tests.py'], ['tests_task.py'], ['test_x.py'], ['tests', 'a.py']):
            self.assertTrue(is_test_module(parts), parts)
        for parts in (['tasks.py'], ['testing.py'], ['utils', 'tests_helper.txt'], []):
            self.assertFalse(is_test_module(parts), parts)

    def test_a_copied_test_does_not_judge_a_substitution(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'jumelle_00'
            p.mkdir()
            (p / 'tasks.py').write_text('def run():\n    pass\n', encoding='utf-8')
            (p / 'tests_task.py').write_text('from .tasks import _convert\n', encoding='utf-8')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00'), [])
                # Counter-check: the same import from RUNTIME code is still reported.
                (p / 'views.py').write_text('from .tasks import _convert\n', encoding='utf-8')
                self.assertEqual(len(cmd_sandbox._imports_intra_paquet_non_resolus('jumelle_00')), 1)

    def _suite(self, *modules):
        import unittest
        cases = [type('T', (unittest.TestCase,), {'test_a': lambda self: None, '__module__': m})
                 for m in modules]
        return unittest.TestSuite(unittest.TestSuite([c('test_a')]) for c in cases)

    def _modules(self, suite):
        out = []
        for t in suite:
            out += self._modules(t) if hasattr(t, '_tests') else [type(t).__module__]
        return out

    def test_the_full_discovery_leaves_the_copied_tests_out(self):
        from wama.common.runners import prune_copied_twin_tests
        suite = self._suite('wama.reader_01.tests', 'wama.reader_01.tests_x',
                            'wama.reader.tests', 'wama.common.tests.tests_queue_delete_contract')
        self.assertEqual(prune_copied_twin_tests(suite, [], twins=['reader_01']), 2)
        # The ORIGINAL's tests and the generic contracts (which loop on twins) stay.
        self.assertEqual(self._modules(suite),
                         ['wama.reader.tests', 'wama.common.tests.tests_queue_delete_contract'])

    def test_aiming_at_the_twin_runs_its_copied_tests(self):
        from wama.common.runners import prune_copied_twin_tests
        for label in ('wama.reader_01', 'wama/reader_01', 'wama.reader_01.tests.T.test_a'):
            with self.subTest(label=label):
                suite = self._suite('wama.reader_01.tests')
                self.assertEqual(prune_copied_twin_tests(suite, [label], twins=['reader_01']), 0)
                self.assertEqual(self._modules(suite), ['wama.reader_01.tests'])

    def test_the_test_run_is_read_from_its_ran_line(self):
        parse = cmd_sandbox.parse_test_run
        self.assertEqual(parse('Ran 12 tests in 3.4s\n\nFAILED (failures=1, errors=2, skipped=3)'),
                         {'ran': 12, 'failures': 1, 'errors': 2, 'skipped': 3})
        self.assertEqual(parse('Ran 5 tests in 1s\n\nOK (skipped=1)'),
                         {'ran': 5, 'failures': 0, 'errors': 0, 'skipped': 1})
        # `manage.py test` exits 0 having run NOTHING: no « Ran » line, no measure.
        self.assertIsNone(parse('Found 0 test(s).\nSystem check identified no issues')['ran'])


class UnroutedTwinDoesNotTakeThePageDownTest(TestCase):
    """A twin whose `urls.py` cannot import is left out of the routing (`sandbox_urlpatterns`, so
    that it does not kill the GLOBAL routing) — but it stays in the catalogue. `/common/apps/`
    reversed its `url_name` again in the template: `NoReverseMatch`, the page down for everyone
    (avatarizer_01, half-written by an interrupted substitution, 2026-10-07)."""

    def test_the_catalogue_page_renders_and_says_the_app_is_unavailable(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        from wama.common import app_registry
        user = get_user_model().objects.create_user('unrouted_twin', password='x')
        self.client.force_login(user)
        ghost = {**next(iter(app_registry.APP_CATALOG.values())),
                 'label': 'Ghost', 'url_name': 'ghost_01:index'}
        with patch.dict(app_registry.APP_CATALOG, {'ghost_01': ghost}):
            response = self.client.get(reverse('common:apps_catalog'))
        self.assertEqual(200, response.status_code)
        self.assertContains(response, 'Ghost indisponible')

    def test_leaving_a_twin_out_of_the_routing_is_logged(self):
        # avatarizer_01 vanished from the menu for five days without a single log line
        # (2026-10-12) : the routing may skip a broken twin, never silently.
        from wama.common import sandbox
        with patch.object(sandbox, 'sandbox_labels', return_value=['ghost_01']), \
                self.assertLogs('wama.sandbox', level='WARNING') as logs:
            self.assertEqual([], sandbox.sandbox_urlpatterns())
        self.assertIn('ghost_01', logs.output[0])


class JudgesAreSilentOnSoundPackagesTest(SimpleTestCase):
    """A judge must say NOTHING about a sound package — and the ten real apps are sound by
    definition (they run). Two false positives of the import judge refused EVERY target of
    anonymizer_01 on its intact copy (2026-10-07) ; measured on the real packages here, the
    next one shows up in the suite instead of in the middle of a twin fleet."""

    APPS = ('anonymizer', 'avatarizer', 'composer', 'converter', 'describer', 'enhancer',
            'imager', 'reader', 'synthesizer', 'transcriber')

    def test_the_import_judge_finds_nothing_in_a_real_app(self):
        for app in self.APPS:
            with self.subTest(app=app):
                self.assertEqual(cmd_sandbox._imports_intra_paquet_non_resolus(app), [])

    def test_the_declared_path_judge_finds_nothing_in_a_real_app(self):
        # Mesuré à son écriture : deux NOMS de tâche Celery (synthesizer, transcriber) étaient pris
        # pour des chemins.
        for app in self.APPS:
            with self.subTest(app=app):
                self.assertEqual(cmd_sandbox._declared_paths_unresolved(app), [])


class CoupleViewsTemplatesTest(SimpleTestCase):
    """Défaut n°2 : substituer les templates SANS les views produit une paire incohérente —
    page 200, boutons morts. Le refus est nommé, et il précède toute génération."""

    def _commande(self, substitue):
        c = cmd_sandbox.Command()
        entree = {'label': 'jumelle_00', 'generated_from': 'converter', 'substituted': substitue}
        return c, [entree]

    def test_templates_sans_views_est_REFUSE(self):
        c, registre = self._commande({})
        with patch.object(cmd_sandbox, 'load_registry', return_value=registre):
            with self.assertRaises(CommandError) as cm:
                c._substitute('jumelle_00', 'templates')
        self.assertIn('views', str(cm.exception).lower())

    def test_templates_apres_un_views_REVERTE_est_aussi_refuse(self):
        c, registre = self._commande({'views': {'verdict': 'revert'}})
        with patch.object(cmd_sandbox, 'load_registry', return_value=registre):
            with self.assertRaises(CommandError):
                c._substitute('jumelle_00', 'templates')

    def test_une_autre_cible_n_est_PAS_soumise_au_couple(self):
        """La règle borne exactement le couple mesuré ; elle ne gêne aucune autre cible.

        ⚠ L'extraction est NEUTRALISÉE : sans ça, ce test lançait une VRAIE substitution
        (fichiers écrits sous `wama/jumelle_00/`, sous-process `manage.py check`) — un test
        qui modifie le dépôt pour prouver une garde est pire que pas de test. Le refus
        d'extraction prouve qu'on a dépassé la garde de couple sans rien écrire.
        """
        c, registre = self._commande({})
        with patch.object(cmd_sandbox, 'load_registry', return_value=registre), \
             patch('wama.common.manifests.ingest.extract', return_value=None):
            with self.assertRaises(CommandError) as cm:
                c._substitute('jumelle_00', 'params')
        message = str(cm.exception).lower()
        self.assertIn('extraction', message, 'la garde de couple a bien été franchie')
        self.assertNotIn('couple', message)

    def test_views_and_templates_substituted_together_pass_the_couple_guard(self):
        """`urls+views+templates` (2026-09-24): a route renamed at the source breaks each file
        alone; together they are one substitution, and the couple guard must let it through.
        Extraction neutralised, as above: nothing is written."""
        c, registre = self._commande({})
        with patch.object(cmd_sandbox, 'load_registry', return_value=registre), \
             patch('wama.common.manifests.ingest.extract', return_value=None):
            with self.assertRaises(CommandError) as cm:
                c._substitute('jumelle_00', 'urls+views+templates')
        self.assertIn('extraction', str(cm.exception).lower())

    def test_an_unknown_target_in_a_combination_is_refused_before_anything(self):
        c, registre = self._commande({})
        with patch.object(cmd_sandbox, 'load_registry', return_value=registre):
            with self.assertRaises(CommandError) as cm:
                c._substitute('jumelle_00', 'urls+bogus')
        self.assertIn('inconnue', str(cm.exception).lower())


class RegistryEntrySaveTest(SimpleTestCase):
    """Défaut n°4 (2026-09-22) : deux substitutions parallèles sur deux jumelles se sont
    écrasées, chacune réécrivant la liste ENTIÈRE chargée à son début. On n'écrit que
    l'entrée mesurée, sur le registre relu à l'instant."""

    def test_saving_one_entry_keeps_what_another_chain_wrote_meanwhile(self):
        mine = {'label': 'a_01', 'generated_from': 'a', 'substituted': {'views': {'verdict': 'ok'}}}
        theirs = {'label': 'b_01', 'generated_from': 'b', 'substituted': {'params': {'verdict': 'ok'}}}
        on_disk = [{'label': 'a_01', 'generated_from': 'a', 'substituted': {}}, theirs]
        written = []
        with patch.object(cmd_sandbox, 'load_registry', return_value=on_disk), \
             patch.object(cmd_sandbox, 'save_registry', side_effect=written.append):
            cmd_sandbox._save_entry(mine)
        self.assertEqual(written, [[mine, theirs]])

    def test_an_unknown_label_is_appended(self):
        written = []
        with patch.object(cmd_sandbox, 'load_registry', return_value=[]), \
             patch.object(cmd_sandbox, 'save_registry', side_effect=written.append):
            cmd_sandbox._save_entry({'label': 'c_01'})
        self.assertEqual(written, [[{'label': 'c_01'}]])


class SupersededTaskModuleTest(SimpleTestCase):
    """Défaut n°3 (2026-09-22, `describer_01`) : le `tasks.py` GÉNÉRÉ laissait à côté la copie
    du module de tâches RÉEL (`workers.py`, autodécouvert par Celery au même titre) — même
    tâche enregistrée deux fois, et un import mort vers les vues copiées qui faisait refuser
    la substitution de `views` pour un module que plus rien n'appelait."""

    def test_the_manifest_names_the_copied_task_module_the_generated_one_replaces(self):
        manifest = {'body': {'processing': {'tasks': [
            {'file': 'workers.py', 'function': 'describe_content'},
            {'file': 'workers.py', 'function': 'other'},
            {'file': 'tasks.py', 'function': 'kept'},
        ]}}}
        from wama.common.manifests.codegen.tasks_gen import superseded_task_files
        self.assertEqual(superseded_task_files(manifest, 'tasks.py'), ['workers.py'])
        self.assertEqual(superseded_task_files({'body': {}}, 'tasks.py'), [])

    def test_retiring_keeps_a_witness_and_restoring_brings_the_copy_back(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'jumelle_00'
            p.mkdir()
            (p / 'workers.py').write_text('COPIE = 1\n', encoding='utf-8')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual(cmd_sandbox._withdraw_modules('jumelle_00', ['workers.py', 'absent.py']),
                                 ['workers.py'])
                self.assertFalse((p / 'workers.py').exists())
                self.assertEqual((p / 'workers.py.temoin').read_text(encoding='utf-8'), 'COPIE = 1\n')
                # Un second retrait ne réécrit pas le témoin (préservé UNE fois, comme les cibles).
                (p / 'workers.py').write_text('AUTRE = 2\n', encoding='utf-8')
                cmd_sandbox._withdraw_modules('jumelle_00', ['workers.py'])
                self.assertEqual((p / 'workers.py.temoin').read_text(encoding='utf-8'), 'COPIE = 1\n')
                self.assertEqual(cmd_sandbox._restore_retired_modules('jumelle_00', ['workers.py']),
                                 ['workers.py'])
                self.assertEqual((p / 'workers.py').read_text(encoding='utf-8'), 'COPIE = 1\n')


def _render_stub_tasks(manifest):
    return '"""[manifest-gen] tasks.py"""\n', 'stub'


class NewFileSubstitutionTest(SimpleTestCase):
    """A target with NO copied file (no witness) — `tasks.py` of an app that keeps its tasks in
    `workers.py`. `temoin.exists()` on None raised AFTER writing: generated file in place,
    copied module withdrawn, no verdict, no revert (describer_01, 2026-10-07). Nothing real
    runs: extraction, renderer and sub-processes are neutralised, the package is temporary."""

    def test_a_brand_new_file_gets_a_verdict(self):
        import subprocess
        saved = []
        ok = subprocess.CompletedProcess([], 0, 'No changes detected', '')
        with TemporaryDirectory() as d:
            (Path(d) / 'jumelle_00' / 'migrations').mkdir(parents=True)
            entry = {'label': 'jumelle_00', 'generated_from': 'appfictive', 'substituted': {}}
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)), \
                 patch.object(cmd_sandbox, 'load_registry', return_value=[entry]), \
                 patch.object(cmd_sandbox, '_save_entry', side_effect=saved.append), \
                 patch.object(cmd_sandbox, '_manage', return_value=ok), \
                 patch.object(cmd_sandbox, '_judge', return_value=ok), \
                 patch.dict(cmd_sandbox._SUBSTITUTABLE,
                            {'tasks': ('tasks.py', __name__, '_render_stub_tasks')}), \
                 patch('wama.common.manifests.ingest.extract',
                       return_value={'key': 'appfictive', 'body': {}}):
                cmd = cmd_sandbox.Command()
                cmd.stdout = cmd.stderr = __import__('io').StringIO()
                cmd._substitute('jumelle_00', 'tasks')
            self.assertTrue((Path(d) / 'jumelle_00' / 'tasks.py').exists())
        self.assertEqual(saved[-1]['substituted']['tasks']['verdict'], 'ok')


def _render_stub_index(manifest):
    return {'index.html': "{% extends 'appfictive/base.html' %}\n"}, 'stub'


def _render_stub_base(manifest):
    return {'base.html': "{% extends 'common/app_modern_base.html' %}\n"}, 'stub'


class TemplatesBringTheirBaseWhenTheSourceHasNoneTest(SimpleTestCase):
    """The generated index extends `<label>/base.html`. A source without its own base (the
    avatarizer extends the common one) left the twin with `TemplateDoesNotExist` on every render
    (avatarizer_01, 2026-10-20): the templates then bring `base` along — never over a COPIED one."""

    def _substitute(self, with_copied_base):
        import io
        import subprocess
        saved = []
        ok = subprocess.CompletedProcess([], 0, '200', '')
        with TemporaryDirectory() as d:
            tpl = Path(d) / 'jumelle_00' / 'templates' / 'jumelle_00'
            tpl.mkdir(parents=True)
            (Path(d) / 'jumelle_00' / 'migrations').mkdir()
            if with_copied_base:
                (tpl / 'base.html').write_text('COPIED', encoding='utf-8')
            entry = {'label': 'jumelle_00', 'generated_from': 'appfictive', 'stage': 'S1',
                     'substituted': {'views': {'verdict': 'ok'}}}
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)), \
                 patch.object(cmd_sandbox, 'load_registry', return_value=[entry]), \
                 patch.object(cmd_sandbox, '_save_entry', side_effect=saved.append), \
                 patch.object(cmd_sandbox, '_judge', return_value=ok), \
                 patch.dict(cmd_sandbox._SUBSTITUTABLE,
                            {'templates': ('templates/', __name__, '_render_stub_index'),
                             'base': ('templates/', __name__, '_render_stub_base')}), \
                 patch('wama.common.manifests.ingest.extract',
                       return_value={'key': 'appfictive', 'body': {}}):
                cmd = cmd_sandbox.Command()
                cmd.stdout = cmd.stderr = io.StringIO()
                cmd._substitute('jumelle_00', 'templates')
            return (tpl / 'base.html').read_text(encoding='utf-8'), saved[-1]['substituted']

    def test_a_source_without_base_gets_the_generated_one(self):
        base, substituted = self._substitute(with_copied_base=False)
        self.assertIn('app_modern_base', base)
        self.assertEqual('ok', substituted['base']['verdict'])

    def test_a_copied_base_is_never_replaced_unasked(self):
        base, substituted = self._substitute(with_copied_base=True)
        self.assertEqual('COPIED', base)
        self.assertNotIn('base', substituted)


class DeclaredPathsJudgeTest(SimpleTestCase):
    """A function DECLARED by string (`WAMA_INGEST['derive']`, `ProcessSpec.eta`,
    `FunctionSpec.impl`) must resolve in the twin — nothing imports it, it only raises at first
    use. Lived on `converter_01` (2026-10-18): generated `tasks` held while the `derive` its model
    declares was gone; only the full suite saw it."""

    MODELS = ("class Item:\n"
              "    WAMA_INGEST = {'source': 'source_url', 'target': 'input_file',\n"
              "                   'derive': 'wama.jumelle_00.tasks._derive'}\n")

    def _package(self, root, tasks_src, extra=''):
        p = Path(root) / 'jumelle_00'
        p.mkdir()
        (p / '__init__.py').write_text('', encoding='utf-8')
        (p / 'models.py').write_text(self.MODELS + extra, encoding='utf-8')
        (p / 'tasks.py').write_text(tasks_src, encoding='utf-8')
        return p

    def test_a_declared_function_absent_from_its_module_is_named_with_its_line(self):
        with TemporaryDirectory() as d:
            self._package(d, 'def other():\n    pass\n')
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                found = cmd_sandbox._declared_paths_unresolved('jumelle_00')
        self.assertEqual(["models.py:3 'wama.jumelle_00.tasks._derive'"], found)

    def test_both_path_forms_resolve_when_the_function_is_there(self):
        with TemporaryDirectory() as d:
            self._package(d, 'def _derive(inst, path, fname):\n    return []\n'
                             'def run_eta(item):\n    return None\n',
                          "ETA = 'jumelle_00.tasks:run_eta'\n")
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual([], cmd_sandbox._declared_paths_unresolved('jumelle_00'))
                # Counter-check: the `module:attribute` form is judged too.
                (Path(d) / 'jumelle_00' / 'tasks.py').write_text(
                    'def _derive(inst, path, fname):\n    return []\n', encoding='utf-8')
                self.assertEqual(["models.py:4 'jumelle_00.tasks:run_eta'"],
                                 cmd_sandbox._declared_paths_unresolved('jumelle_00'))

    def test_what_only_looks_like_a_path_is_not_reproached(self):
        with TemporaryDirectory() as d:
            self._package(
                d, "from celery import shared_task\n"
                   "def _derive(inst, path, fname):\n    return []\n"
                   "@shared_task(name='wama.jumelle_00.refresh_refs')\n"
                   "def refresh():\n    pass\n",
                # A catalogue key, a sentence citing a path, a task NAME cited elsewhere.
                "KEY = 'jumelle_00.convert'\n"
                "HELP = 'voir wama.jumelle_00.tasks.absent'\n"
                "SENT = 'wama.jumelle_00.refresh_refs'\n")
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)):
                self.assertEqual([], cmd_sandbox._declared_paths_unresolved('jumelle_00'))

    def test_a_substitution_that_loses_a_declared_function_goes_back_to_the_witness(self):
        import io
        import subprocess
        saved = []
        ok = subprocess.CompletedProcess([], 0, 'No changes detected', '')
        copied = 'def _derive(inst, path, fname):\n    return []\n'
        with TemporaryDirectory() as d:
            p = self._package(d, copied)
            (p / 'migrations').mkdir()
            entry = {'label': 'jumelle_00', 'generated_from': 'appfictive', 'substituted': {},
                     'stage': 'S1'}
            with patch.object(cmd_sandbox, 'WAMA_DIR', Path(d)), \
                 patch.object(cmd_sandbox, 'load_registry', return_value=[entry]), \
                 patch.object(cmd_sandbox, '_save_entry', side_effect=saved.append), \
                 patch.object(cmd_sandbox, '_manage', return_value=ok), \
                 patch.object(cmd_sandbox, '_judge', return_value=ok), \
                 patch.dict(cmd_sandbox._SUBSTITUTABLE,
                            {'tasks': ('tasks.py', __name__, '_render_stub_tasks')}), \
                 patch('wama.common.manifests.ingest.extract',
                       return_value={'key': 'appfictive', 'body': {}}):
                cmd = cmd_sandbox.Command()
                cmd.stdout = cmd.stderr = io.StringIO()
                cmd._substitute('jumelle_00', 'tasks')
            self.assertEqual(copied, (p / 'tasks.py').read_text(encoding='utf-8'))
        verdict = saved[-1]['substituted']['tasks']
        self.assertEqual('revert', verdict['verdict'])
        self.assertTrue(any('_derive' in line for line in verdict['details']), verdict['details'])


class DeclaredGlueHolesTest(SimpleTestCase):
    """The generated `tasks.py` carries a marked GLUE HOLE for every function another declaration
    names by string in the app's task module — the ingest `derive`, each process `eta` and
    `result` — and the declarations the generators write follow it when the source kept its tasks
    in `workers.py`, which the generated file replaces."""

    @staticmethod
    def _functions(src):
        return {n.name: ast.get_source_segment(src, n) for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef)}

    def test_each_declared_function_is_a_marked_hole(self):
        from wama.common.manifests.ingest import extract
        src, reason = render_tasks(extract('app', 'converter'))
        self.assertIsNotNone(src, reason)
        functions = self._functions(src)
        for name in ('_derive_media_type', 'convert_eta', 'enhance_eta'):
            with self.subTest(name=name):
                self.assertIn(name, functions)
                self.assertIn('TROU DE GLU', functions[name])
                self.assertIn('NotImplementedError', functions[name])
        self.assertIn('(inst, path, fname)', functions['_derive_media_type'])
        # The hole is the one the `glue` gesture fills, by name.
        filled = cmd_sandbox.replace_glue_hole(
            src, '_derive_media_type', 'def _derive_media_type(inst, path, fname):\n    return []\n')
        self.assertNotIn('TROU DE GLU', self._functions(filled)['_derive_media_type'])

    def test_each_hole_points_to_the_caller_whose_docstring_is_its_contract(self):
        # The contract is not copied into the hole: it lives with its caller. A pointer that no
        # longer resolves would send the glue writer nowhere.
        from pydoc import locate         # a dotted path down to a method, unlike import_string
        from wama.common.manifests.codegen.tasks_gen import _DECLARED_GLUE
        from wama.common.manifests.ingest import extract
        src, _ = render_tasks(extract('app', 'converter'))
        functions = self._functions(src)
        for role, (_, _, caller) in _DECLARED_GLUE.items():
            with self.subTest(role=role):
                self.assertTrue(callable(locate(caller)), caller)
                self.assertTrue((locate(caller).__doc__ or '').strip())
        self.assertIn('source_ingest.ensure_local_input', functions['_derive_media_type'])
        self.assertIn('process_runs.process_eta', functions['convert_eta'])

    def test_a_manifest_declaring_nothing_gets_no_extra_function(self):
        src, _ = render_tasks(_manifeste())
        self.assertEqual({'traiter_item', '_process_traiter_item'}, set(self._functions(src)))

    def test_a_declaration_into_workers_follows_the_generated_tasks(self):
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        from wama.common.manifests.codegen.models_gen import render_models
        from wama.common.manifests.ingest import extract
        manifest = extract('app', 'describer')
        self.assertIn('_derive_detected_type', self._functions(render_tasks(manifest)[0]))
        models, _ = render_models(manifest)
        self.assertIn("'wama.describer.tasks._derive_detected_type'", models)
        specs, _ = render_function_specs(manifest)
        self.assertIn("eta='describer.tasks:transcribe_eta'", specs)
        self.assertNotIn('describer.workers', models + specs)
        # Counter-check: a declaration into another module is left as it is.
        from wama.common.manifests.codegen.tasks_gen import generated_task_path
        self.assertEqual('describer.function_specs:transcript_text',
                         generated_task_path(manifest, 'describer.function_specs:transcript_text'))


class TwinGridReadsWhatIsInjectedTest(SimpleTestCase):
    """La grille doit noter une jumelle sur ce qu'elle EST, pas sur ce que le contrôle lit.

    MESURÉ le 2026-09-26 (question de Fabien : faire entrer le bac à sable dans la grille pour
    qu'un modérateur puisse juger une app candidate). `describer_01` sortait à **75 %** contre
    **99 %** pour sa source ; sur ses 20 rouges, QUATRE étaient FAUX — le contrôle lisait le
    TEXTE d'un registre pendant que le bac à sable injecte la jumelle dans ce même registre au
    RUNTIME (`inject_sandbox_catalog`, `inject_sandbox_access`, `get_app_modes`).
    *Une grille qui reproche une déclaration qu'on a ment au modérateur qui la lit.*

    ⚠ ET LA CONTRE-ÉPREUVE COMPTE AUTANT : le repli ne doit PAS s'étendre à ce que le bac à
    sable ne sert pas. Décision de Fabien du 2026-10-06 (« oui, injecter ») : la découverte des
    modèles est désormais servie (la jumelle lit le catalogue de sa source — repli légitime) ;
    `TRIAD_SPECS` et `GENERIC_APPS` sont INJECTÉS pour de vrai, leurs critères lisent
    l'EXÉCUTION, sans repli ; l'outil de création `add_to_<app>` (glu écrite à la main) ne
    l'est pas — rouge MÉRITÉ.
    """

    #: Les fonctions de contrôle qui ne doivent PAS emprunter la déclaration de la source : elles
    #: lisent l'exécution (registres injectés) ou un outil qui n'est pas servi à la jumelle.
    SANS_REPLI = ('_tool_api_triad', '_tool_api_item_id', '_triad_specs', '_studio_params')

    def test_a_twin_inherits_the_declaration_of_its_source(self):
        from wama.common.services import conformity_checker as checker
        with patch('wama.common.sandbox.twin_source', return_value='describer'):
            self.assertEqual('describer', checker._declaring_app('describer_01'))

    def test_a_normal_app_answers_for_itself(self):
        from wama.common.services import conformity_checker as checker
        self.assertEqual('describer', checker._declaring_app('describer'))

    def test_the_fallback_stays_out_of_the_registries_the_sandbox_does_not_inject(self):
        """Contre-épreuve de PÉRIMÈTRE : un repli qui déborde ferait verdir un critère sur une
        chose que la jumelle n'expose pas — le contraire du service rendu au modérateur."""
        import re
        from pathlib import Path

        from wama.common.services import conformity_checker as checker
        source = Path(checker.__file__).read_text(encoding='utf-8')
        for name in self.SANS_REPLI:
            body = re.search(rf"^def {name}\b.*?(?=^def |\Z)", source, re.S | re.M)
            self.assertIsNotNone(body, f'{name} introuvable')
            self.assertNotIn('_declaring_app', body.group(0),
                             f"{name} lit un registre que le bac à sable n'injecte pas : "
                             f"le repli y ferait dire à la grille une chose fausse")

    def test_the_four_criteria_that_do_inherit_say_so_in_their_message(self):
        """Le modérateur doit voir que la déclaration est HÉRITÉE, pas propre à la jumelle."""
        import re
        from pathlib import Path

        from wama.common.services import conformity_checker as checker
        source = Path(checker.__file__).read_text(encoding='utf-8')
        for name in ('_catalog_entry', '_access_policy', '_model_discovery', '_model_caps_canonical'):
            body = re.search(rf"^def {name}\b.*?(?=^def |\Z)", source, re.S | re.M).group(0)
            self.assertIn('_declaring_app', body, name)
            self.assertIn('hérité de', body, f'{name} : le message doit dire que c\'est hérité')


class TwinRegistriesInjectedTest(SimpleTestCase):
    """`sandbox.inject_sandbox_registry` (décision de Fabien, 2026-10-06) : une jumelle reçoit la
    déclaration de sa source, chemins re-ciblés sur SON paquet — et seulement ce qui peut tourner."""

    def _inject(self, registry, *, labels=('converter_01',), runnable=None, files=('tasks.py',),
                resolves=lambda dotted: True):
        from wama.common import sandbox
        entries = [{'label': 'converter_01', 'generated_from': 'converter'}]

        def exists(path):
            return Path(path).name in files and 'converter_01' in str(path)
        with patch.object(sandbox, 'load_registry', return_value=entries), \
                patch.object(sandbox, 'sandbox_labels', return_value=list(labels)), \
                patch.object(sandbox, 'resolves', resolves), \
                patch.object(sandbox.Path, 'exists', lambda self: exists(self)):
            sandbox.inject_sandbox_registry(registry, runnable=runnable)
        return registry

    def test_a_path_the_twin_does_not_define_keeps_the_declaration_out(self):
        """The triad names launch functions of the app's VIEWS (2026-10-12) : a twin whose views
        were regenerated may lack them — injected anyway, the tool would raise on its first call
        and the grid would count it green."""
        reg = self._inject({'converter': {'model': 'wama.converter.models.Job',
                                          'task_for': 'wama.converter.views._task_for'}},
                           resolves=lambda dotted: not dotted.endswith('._task_for'))
        self.assertNotIn('converter_01', reg)

    def test_resolves_reads_the_disk_without_importing(self):
        from wama.common import sandbox
        self.assertTrue(sandbox.resolves('wama.common.sandbox'))                 # a module
        self.assertTrue(sandbox.resolves('wama.common.sandbox.resolves'))        # a function
        self.assertTrue(sandbox.resolves('wama.common.sandbox.REGISTRY_PATH'))   # an assignment
        self.assertTrue(sandbox.resolves('wama.common.sandbox.Path'))            # an import
        self.assertFalse(sandbox.resolves('wama.common.sandbox.no_such_name'))
        self.assertFalse(sandbox.resolves('wama.no_such_package.views._task_for'))

    def test_a_twin_gets_its_source_declaration_retargeted_on_its_own_package(self):
        reg = self._inject({'converter': {'model': 'wama.converter.models.Job',
                                          'task': 'wama.converter.tasks.convert',
                                          'status_fields': {'id': 'id'}}})
        self.assertEqual('wama.converter_01.models.Job', reg['converter_01']['model'])
        self.assertEqual('wama.converter_01.tasks.convert', reg['converter_01']['task'])
        self.assertEqual({'id': 'id'}, reg['converter_01']['status_fields'], 'non-paths untouched')
        self.assertEqual('wama.converter.models.Job', reg['converter']['model'], 'source untouched')

    def test_a_workers_module_follows_the_generated_tasks(self):
        """The generated `tasks.py` REPLACES `workers.py` in a twin (`app_sandbox substitute`)."""
        reg = self._inject({'converter': {'task': 'wama.converter.workers.convert'}})
        self.assertEqual('wama.converter_01.tasks.convert', reg['converter_01']['task'])
        kept = self._inject({'converter': {'task': 'wama.converter.workers.convert'}},
                            files=('workers.py', 'tasks.py'))
        self.assertEqual('wama.converter_01.workers.convert', kept['converter_01']['task'])

    def test_what_cannot_run_is_not_injected(self):
        reg = self._inject({'converter': {'params_module': 'wama.converter.params'}},
                           runnable=lambda label: False)
        self.assertNotIn('converter_01', reg)

    def test_a_twin_without_a_package_is_not_injected(self):
        self.assertNotIn('converter_01', self._inject({'converter': {}}, labels=()))

    def test_the_catalogue_of_a_twin_is_the_catalogue_of_its_source(self):
        from wama.common import sandbox
        with patch.object(sandbox, 'twin_source', return_value='describer'):
            self.assertEqual('describer', sandbox.declaring_app('describer_01'))
        self.assertEqual('describer', sandbox.declaring_app('describer'))


class TwinStaticFollowsItsSourceTest(SimpleTestCase):
    """No `substitute` target covered `static/` (no JS template) : a twin's JS stayed the copy of
    its creation day — `reader_01` still intercepted the double-click its source had handed to the
    common viewer (2026-10-12). `substitute static` copies it again, the creation's gesture."""

    def test_only_the_static_folder_is_copied_again_with_the_twin_renaming(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / 'app' / 'static' / 'app' / 'js').mkdir(parents=True)
            (root / 'app' / 'static' / 'app' / 'js' / 'index.js').write_text(
                "fetch('/app/text/' + id);", encoding='utf-8')
            (root / 'app' / 'views.py').write_text("x = 'app'\n", encoding='utf-8')
            with patch.object(cmd_sandbox, 'WAMA_DIR', root):
                written = cmd_sandbox._copy_package('app', 'app_01', only='static')
            self.assertEqual([root / 'app_01' / 'static' / 'app_01' / 'js' / 'index.js'], written)
            self.assertIn("'/app/text/'", written[0].read_text(encoding='utf-8'),
                          'the URL path is not a quoted app path : left as written')
            self.assertFalse((root / 'app_01' / 'views.py').exists(), 'nothing outside static/')
            self.assertFalse((root / 'app_01' / 'migrations').exists(), 'no package scaffolding')

    def test_a_twin_born_from_a_manifest_has_no_static_to_follow(self):
        registry = [{'label': 'writer_01', 'generated_from': '', 'from_manifest': 'x.json'}]
        with patch.object(cmd_sandbox, 'load_registry', return_value=registry):
            with self.assertRaisesRegex(CommandError, 'manifeste'):
                cmd_sandbox.Command()._resync_static('writer_01')


class DeadCopiedCardsTest(SimpleTestCase):
    """Generated templates that hold left the COPIED cards on disk, included by nothing — they
    misled any reading of the code (2026-10-12). They go to a witness ; the rest stays."""

    def test_only_a_copied_card_nothing_names_is_dead(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            tpl = root / 'x_01' / 'templates' / 'x_01'
            tpl.mkdir(parents=True)
            (tpl / 'index.html').write_text(
                "{# manifest-gen #}{% include 'x_01/_generic_card.html' %}", encoding='utf-8')
            (tpl / '_generic_card.html').write_text('{# manifest-gen #}<div></div>', encoding='utf-8')
            (tpl / '_item_card.html').write_text('<div>old copy</div>', encoding='utf-8')
            (tpl / '_meta.html').write_text('<span></span>', encoding='utf-8')
            # The COPIED index, kept as a witness, still includes the old card.
            (tpl / 'index.html.temoin').write_text("{% include 'x_01/_item_card.html' %}",
                                                   encoding='utf-8')
            (root / 'x_01' / 'views.py').write_text(
                "render(request, 'x_01/_meta.html')\n", encoding='utf-8')
            # Mentions that serve nothing : a comment, a COPIED test (left out of the suite).
            (root / 'x_01' / 'static').mkdir()
            (root / 'x_01' / 'static' / 'x.js').write_text(
                '// the class changed in `_item_card.html` too', encoding='utf-8')
            (root / 'x_01' / 'tests.py').write_text(
                "TEMPLATE = 'x_01/_item_card.html'\n", encoding='utf-8')
            with patch.object(cmd_sandbox, 'WAMA_DIR', root):
                dead = cmd_sandbox._dead_copied_templates('x_01')
        # A witness, a comment, a copied test name nothing that is served.
        self.assertEqual(['templates/x_01/_item_card.html'], dead)


class BornAppSubstitutionTest(SimpleTestCase):
    """An app born from a manifest is substituted from THAT manifest (2026-10-12 : writer_01 kept
    a card the generator had fixed, and only `remove` + `create` — data lost — regenerated it)."""

    def test_without_its_origin_manifest_it_is_refused(self):
        registry = [{'label': 'ghost_01', 'generated_from': ''}]
        with patch.object(cmd_sandbox, 'load_registry', return_value=registry):
            with self.assertRaisesRegex(CommandError, 'manifeste'):
                cmd_sandbox.Command()._substitute('ghost_01', 'templates')

    def test_its_templates_need_no_views_substitution_first(self):
        """Its views were generated at birth : the views↔templates couple already holds."""
        registry = [{'label': 'ghost_01', 'generated_from': '', 'from_manifest': 'x.json'}]
        with patch.object(cmd_sandbox, 'load_registry', return_value=registry), \
                patch.object(cmd_sandbox, '_born_manifest',
                             side_effect=CommandError('manifest read')) as born:
            with self.assertRaisesRegex(CommandError, 'manifest read'):
                cmd_sandbox.Command()._substitute('ghost_01', 'templates')
        born.assert_called_once()
