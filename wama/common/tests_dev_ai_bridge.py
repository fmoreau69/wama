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
        from .utils.prompt_skills import skills_catalog
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
                self.assertNotIn("'prompts'", source.replace("PROMPTS_DIR", ""),
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
