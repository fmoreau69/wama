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
    "<!-- WAMA:SECTION(audience=utilisateur; type=guide; nature=constat; etat=✅; porte=apps/x) -->",
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

    def test_notes_de_construction_et_numeros_ne_passent_pas(self):
        source = "\n".join([
            "## 4. Sujet", f"<!-- WAMA:SECTION({DEV}) -->",
            "<!-- vérifié le 2026-09-14 contre", "     wama/x.py -->",
            "Il y a <!-- WAMA:FAIT(registres) -->15<!-- /WAMA:FAIT --> registres.",
            "<!-- WAMA:FAIT(registres) -->15<!-- /WAMA:FAIT --> en tête de ligne.",
            "### 4.1 Détail", "texte", "### 9quinquies.2 LE CRITÈRE", "texte"]) + "\n"
        t = '\n'.join(excerpt_markdown(source, '4. Sujet', DEVELOPER, 's.md', 'd.md'))
        self.assertNotIn('vérifié', t)
        self.assertNotIn('wama/x.py', t)
        self.assertEqual(t.count('WAMA:FAIT(registres)'), 2, "une balise de fait passe")
        self.assertIn('\n### Détail\n', t)
        self.assertIn('\n### LE CRITÈRE\n', t)

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


USR = "audience=utilisateur; type=guide; nature={nature}; etat={etat}; porte={porte}"
SOURCE_USER = "\n".join([
    "# Guide",
    "",
    "## U",
    f"<!-- WAMA:SECTION({USR.format(nature='constat', etat='✅', porte='apps/x')}) -->",
    "Texte U.",
    "",
    "### U.1",
    "hérité",
    "",
    "### U.2",
    f"<!-- WAMA:SECTION({USR.format(nature='intention', etat='⏳', porte='apps/x')}) -->",
    "pas encore",
    "",
    "### U.3",
    f"<!-- WAMA:SECTION({USR.format(nature='constat', etat='✅', porte='apps/y')}) -->",
    "le registre ne le connaît pas",
    "",
    "## V",
    "<!-- WAMA:SECTION(audience=utilisateur,developpeur; type=explication; nature=intention; "
    "etat=🔄; porte=apps/x) -->",
    "une vision",
]) + "\n"


def _porte_de_test(chemin):
    return None if chemin == 'apps/x' else 'absent du registre'


class PorteTest(TestCase):
    """⑤ — n'entre chez l'utilisateur que ce que le registre confirme, et jamais une intention."""

    def _extrait(self, section, audience=USER):
        return '\n'.join(excerpt_markdown(SOURCE_USER, section, audience, 'SRC.md',
                                          'docs/utilisateur/X.md', porte=_porte_de_test))

    def test_porte_ouverte_le_fragment_entre_sans_ce_qui_est_retenu(self):
        t = self._extrait('U')
        self.assertIn('Texte U.', t)
        self.assertIn('hérité', t)
        self.assertNotIn('pas encore', t, "une intention n'arrive pas chez l'utilisateur")
        self.assertNotIn('le registre ne le connaît pas', t, "porte fermée")
        self.assertEqual(t.count('WAMA:PORTE-FERMEE('), 2, "chaque retenue laisse sa trace")

    def test_une_intention_est_retenue_pour_l_utilisateur_et_annoncee_au_developpeur(self):
        pour_user = self._extrait('V')
        self.assertNotIn('une vision', pour_user)
        self.assertIn('WAMA:PORTE-FERMEE(SRC.md — V) : intention', pour_user)
        pour_dev = self._extrait('V', audience=DEVELOPER)
        self.assertIn('une vision', pour_dev)
        self.assertIn('**Intention**', pour_dev)

    def test_la_trace_est_invisible_a_la_lecture(self):
        from .docs_catalog import render_markdown
        self.assertNotIn('PORTE-FERMEE', render_markdown(self._extrait('U'))['html'])

    def test_sans_resolveur_un_extrait_utilisateur_est_refuse(self):
        with self.assertRaises(PlanError):
            excerpt_markdown(SOURCE_USER, 'U', USER, 's.md', 'd.md')

    def test_la_vraie_porte_lit_le_registre(self):
        from .doc_plans import porte_fermee
        from .registries import REGISTRIES
        self.assertIsNone(porte_fermee('apps/transcriber'))
        self.assertIsNone(porte_fermee('apps/transcriber/has_batch'))
        self.assertIn('absent', porte_fermee('apps/app_qui_n_existe_pas'))
        sans_fiches = next(k for k, r in REGISTRIES.items() if r.entries is None)
        for invérifiable in ('registre_bidon/x', f'{sans_fiches}/x',
                             'apps/transcriber/champ_qui_n_existe_pas'):
            with self.assertRaises(PlanError, msg=invérifiable):
                porte_fermee(invérifiable)


class PiloteTest(TestCase):
    """« Les registres de WAMA » — le pilote de ③."""

    def test_le_pilote_se_construit_et_projette_chaque_registre(self):
        from .registries import REGISTRIES
        doc = BY_KEY['dev-registres']
        texte = build(doc)
        self.assertTrue(texte.startswith(HEADER.format(key='dev-registres')))
        self.assertIn('## Quand une chose mérite un registre', texte)
        self.assertIn('*Source : [docs/construction/mondes/WAMA_DATA_WORLD.md', texte)
        self.assertEqual([k for k in REGISTRIES if f"`{k}`" not in texte], [])

    def test_chaque_fichier_derive_est_ce_que_son_plan_produit(self):
        # La confrontation doc → doc : si une source ou un registre bouge, ce test (et
        # `doc_facts --check`) le voient. Régénérer : `python manage.py doc_facts`.
        # Étendu à TOUTES les docs dérivées le 2026-09-14 (il ne gardait que le pilote).
        from .docs_catalog import DOCS
        derivees = [d for d in DOCS if d.plan]
        self.assertGreater(len(derivees), 1, "moins de deux docs dérivées : garde affaiblie")
        for doc in derivees:
            sur_disque = file_of(doc).read_text(encoding='utf-8').replace('\r\n', '\n')
            self.assertEqual(sur_disque, build(doc), doc.path)

    def test_le_pilote_utilisateur_retient_la_vision_de_guidage(self):
        texte = build(BY_KEY['user-transcriber-correction'])
        self.assertIn('## Corriger une transcription', texte)
        self.assertIn('`Ctrl+Entrée`', texte)
        self.assertNotIn('barre de guidage', texte, "intention : elle reste dans la spec")
        self.assertIn('WAMA:PORTE-FERMEE(', texte)

    def test_un_plan_casse_est_refuse(self):
        for plan in ((Excerpt('inconnu', 'x'),),
                     (Facts('wama.common.dev_docs:inexistant'),),
                     (Facts('module.inexistant:f'),),
                     ()):
            doc = Doc('t', 'docs/dev/t.md', 'T', 'architecture', 'd', audience=DEVELOPER,
                      plan=plan)
            with self.assertRaises(PlanError, msg=repr(plan)):
                build(doc)
