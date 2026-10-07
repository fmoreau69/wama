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
from django.test import SimpleTestCase

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
        self.assertEqual(cmd_sandbox._superseded_task_modules(manifest, 'tasks.py'), ['workers.py'])
        self.assertEqual(cmd_sandbox._superseded_task_modules({'body': {}}, 'tasks.py'), [])

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
                 patch.object(cmd_sandbox, '_smoke_page', return_value=ok), \
                 patch.dict(cmd_sandbox._SUBSTITUTABLE,
                            {'tasks': ('tasks.py', __name__, '_render_stub_tasks')}), \
                 patch('wama.common.manifests.ingest.extract',
                       return_value={'key': 'appfictive', 'body': {}}):
                cmd = cmd_sandbox.Command()
                cmd.stdout = cmd.stderr = __import__('io').StringIO()
                cmd._substitute('jumelle_00', 'tasks')
            self.assertTrue((Path(d) / 'jumelle_00' / 'tasks.py').exists())
        self.assertEqual(saved[-1]['substituted']['tasks']['verdict'], 'ok')


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

    def _inject(self, registry, *, labels=('converter_01',), runnable=None, files=('tasks.py',)):
        from wama.common import sandbox
        entries = [{'label': 'converter_01', 'generated_from': 'converter'}]

        def exists(path):
            return Path(path).name in files and 'converter_01' in str(path)
        with patch.object(sandbox, 'load_registry', return_value=entries), \
                patch.object(sandbox, 'sandbox_labels', return_value=list(labels)), \
                patch.object(sandbox.Path, 'exists', lambda self: exists(self)):
            sandbox.inject_sandbox_registry(registry, runnable=runnable)
        return registry

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
