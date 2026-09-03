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
        # défaut hérité du pilote, latent chez converter_01 car jamais déclenché.
        for result in ({'kind': 'text', 'field': 'result_text'}, None):
            src, _ = render_tasks(_manifeste(routes=self.ROUTES_TEXTE, nature='detected_type',
                                             result=result))
            self.assertIn('{nature!r}', src)
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
