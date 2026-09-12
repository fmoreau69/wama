"""Tests des docs DÉRIVÉES par plan (`common/doc_plans.py`) — ROADMAP §25.1 ③.

Ce qui est vérifié est ce qui justifie la brique : un extrait est la section source, ramenée au
bon niveau et débarrassée de ses balises, avec ses liens recalés et sa source citée ; une
sous-section destinée à un autre public n'y entre pas ; une intention y est ANNONCÉE ; un plan
qui ne se construit pas est refusé ; et le fichier versionné du pilote est bien ce que son plan
produit aujourd'hui — c'est la confrontation doc → doc, gratuite parce que la dérivation est
mécanique.
"""
from django.test import SimpleTestCase, TestCase

from .doc_plans import HEADER, PlanError, build, excerpt_markdown
from .docs_catalog import BY_KEY, DEVELOPER, USER, Doc, Excerpt, Facts, file_of

DEV = "audience=developpeur; type=explication; nature=constat; etat=✅"
SOURCE = "\n".join([
    "# Doc",
    "",
    "## A",
    f"<!-- WAMA:SECTION({DEV}) -->",
    "Texte A, voir [le voisin](VOISIN.md#x).",
    "",
    "### A.1",
    "hérité",
    "",
    "### A.2",
    "<!-- WAMA:SECTION(audience=utilisateur; type=guide; nature=constat; etat=✅) -->",
    "pour l'utilisateur seulement",
    "",
    "## B",
    "<!-- WAMA:SECTION(audience=developpeur; type=explication; nature=intention; etat=⏳) -->",
    "une vision",
    "",
    "## C",
    "rien",
]) + "\n"


class ExtraitTest(SimpleTestCase):

    def _extrait(self, section, audience=DEVELOPER, title=''):
        return '\n'.join(excerpt_markdown(SOURCE, section, audience, 'sous/SRC.md',
                                          'docs/dev/X.md', title))

    def test_la_section_est_extraite_au_niveau_2_sans_ses_balises(self):
        t = self._extrait('A')
        self.assertTrue(t.startswith('## A\n'))
        self.assertIn('### A.1', t)
        self.assertIn('hérité', t)
        self.assertNotIn('WAMA:SECTION', t)
        self.assertNotIn('## B', t, "l'extrait s'arrête au titre de même niveau")

    def test_une_sous_section_d_un_autre_public_n_entre_pas(self):
        t = self._extrait('A')
        self.assertNotIn('A.2', t)
        self.assertNotIn("pour l'utilisateur seulement", t)

    def test_les_liens_sont_recales_et_la_source_citee(self):
        t = self._extrait('A')
        self.assertIn('(../../sous/VOISIN.md#x)', t)
        self.assertIn('*Source : [sous/SRC.md — A](../../sous/SRC.md#a)*', t)

    def test_une_intention_est_annoncee(self):
        self.assertIn('⏳ **Intention**', self._extrait('B'))

    def test_le_titre_peut_etre_remplace(self):
        self.assertTrue(self._extrait('A', title='Autre titre').startswith('## Autre titre\n'))

    def test_ce_qui_ne_se_construit_pas_est_refuse(self):
        with self.assertRaises(PlanError):
            self._extrait('Inexistante')
        with self.assertRaises(PlanError):
            self._extrait('A', audience=USER)      # A est marquée pour les développeurs
        with self.assertRaises(PlanError):
            self._extrait('C')                      # C n'est marquée pour personne
        with self.assertRaises(PlanError):
            excerpt_markdown(SOURCE + "## A\n", 'A', DEVELOPER, 's.md', 'd.md')   # ambiguë
        with self.assertRaises(PlanError):
            excerpt_markdown("# T\n<!-- WAMA:SECTION(audience=developpeur) -->\n", 'T',
                             DEVELOPER, 's.md', 'd.md')                          # marquage invalide


class PiloteTest(TestCase):
    """« Les registres de WAMA » — le pilote de ③."""

    def test_le_pilote_se_construit_et_projette_chaque_registre(self):
        from .registries import REGISTRIES
        doc = BY_KEY['dev-registres']
        texte = build(doc)
        self.assertTrue(texte.startswith(HEADER.format(key='dev-registres')))
        self.assertIn('## Quand une chose mérite un registre', texte)
        self.assertIn('*Source : [WAMA_DATA_WORLD.md', texte)
        self.assertEqual([k for k in REGISTRIES if f"`{k}`" not in texte], [])

    def test_le_fichier_versionne_est_ce_que_le_plan_produit(self):
        # La confrontation doc → doc : si une source ou un registre bouge, ce test (et
        # `doc_facts --check`) le voient. Régénérer : `python manage.py doc_facts`.
        doc = BY_KEY['dev-registres']
        sur_disque = file_of(doc).read_text(encoding='utf-8').replace('\r\n', '\n')
        self.assertEqual(sur_disque, build(doc))

    def test_un_plan_casse_est_refuse(self):
        for plan in ((Excerpt('inconnu', 'x'),),
                     (Facts('wama.common.dev_docs:inexistant'),),
                     (Facts('module.inexistant:f'),),
                     ()):
            doc = Doc('t', 'docs/dev/t.md', 'T', 'architecture', 'd', audience=DEVELOPER,
                      plan=plan)
            with self.assertRaises(PlanError, msg=repr(plan)):
                build(doc)
