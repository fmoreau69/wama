"""Catalogue des skills : la synthèse DÉRIVE, et la page la rend.

Pourquoi ces tests. Le registre `skills` a vécu cinq jours avec un compteur, un rafraîchisseur
et AUCUNE page — sans que rien ne le signale. Le défaut que cette page expose est de la même
nature : un skill que rien ne résout ne lève aucune erreur, le LLM reçoit juste une consigne
générique. Un catalogue qui se tromperait sur « qui consomme quoi » serait donc muet lui aussi.

⚠ On éprouve la DÉRIVATION, pas le contenu des fichiers : asserter « 11 skills » figerait ici
un chiffre que déposer un `.md` suffit à démentir — exactement le défaut que `check_docs`
traque dans les skills de doctrine depuis le 27/08.
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.services.skills_catalog import FAMILLES, _resume, synthese


class SyntheseTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cat = synthese()
        cls.par_nom = {s['nom']: s for s in cls.cat['skills']}

    def test_le_catalogue_n_est_pas_vide(self):
        # Garde d'INSTRUMENT : sans elle, tous les tests suivants passeraient sur une liste vide
        # — le harnais qui annonce « 0 échec » parce qu'il ne voit rien.
        self.assertGreater(self.cat['total'], 0)
        self.assertEqual(self.cat['total'], len(self.cat['skills']))

    def test_le_readme_n_est_pas_un_skill(self):
        self.assertNotIn('readme', {n.lower() for n in self.par_nom})

    def test_chaque_skill_porte_une_famille_declaree(self):
        for s in self.cat['skills']:
            self.assertIn(s['famille'], FAMILLES, s['nom'])
            self.assertEqual(s['famille_label'], FAMILLES[s['famille']])

    def test_les_comptes_par_famille_totalisent_le_catalogue(self):
        self.assertEqual(sum(self.cat['par_famille'].values()), self.cat['total'])

    def test_un_skill_de_role_est_rattache_a_son_domaine_d_assistant(self):
        # Le lien vient du registre DÉCLARATIF `DOMAINES`, pas d'une convention de nom : c'est
        # ce qui distingue un rôle réellement câblé d'un fichier `assistant-*.md` oublié.
        from wama.common.utils.assistant_skills import DOMAINES
        for d in DOMAINES:
            s = self.par_nom.get(d.skill)
            self.assertIsNotNone(s, f"skill de rôle absent : {d.skill}")
            self.assertEqual(s['famille'], 'role')
            self.assertTrue(s['consommateurs'], d.skill)

    def test_un_skill_d_enrichissement_cite_le_champ_qui_le_resout(self):
        # `composer-music` est résolu par le target `composer.prompt` (domain='music', statique).
        s = self.par_nom.get('composer-music')
        if s is None:
            self.skipTest("skill composer-music retiré du dépôt")
        self.assertEqual(s['famille'], 'enrichissement')
        self.assertTrue(any('composer' in c and 'prompt' in c for c in s['consommateurs']),
                        s['consommateurs'])

    def test_un_domaine_dynamique_relie_toutes_ses_variantes(self):
        # imager déclare `domain_field='output_type'` : le domaine n'est connu qu'à l'exécution.
        # On ne l'invente pas — les deux variantes présentes sont reliées, en le disant.
        for nom in ('imager-image', 'imager-video'):
            s = self.par_nom.get(nom)
            if s is None:
                self.skipTest(f"skill {nom} retiré du dépôt")
            self.assertTrue(any('output_type' in c for c in s['consommateurs']), s)

    def test_un_repli_n_est_jamais_compte_comme_orphelin(self):
        # Il est atteint PAR DÉFAUT : le marquer en alerte produirait un rouge permanent, donc
        # un rouge que plus personne ne lit.
        for s in self.cat['skills']:
            if s['famille'] == 'repli':
                self.assertFalse(s['orphelin'], s['nom'])

    def test_le_compteur_d_orphelins_suit_les_cartes(self):
        self.assertEqual(self.cat['orphelins'],
                         sum(1 for s in self.cat['skills'] if s['orphelin']))

    def test_un_target_sans_aucun_skill_est_signale(self):
        # `assistant.message` (kind='intent') n'a ni `assistant.md` ni `default-intent.md` : le
        # pipeline garde son repli intégré, en silence. C'est l'écart INVERSE de l'orphelin, et
        # la page est la seule surface où il existe.
        couples = {(t['app'], t['champ']) for t in self.cat['targets_orphelins']}
        self.assertIn(('assistant', 'message'), couples)

    def test_tout_target_orpheline_est_bien_absente_du_dossier(self):
        # Contre-épreuve : un signalement faux serait pire qu'aucun signalement.
        from wama.common.utils.prompt_skills import _slug, load_skill
        for t in self.cat['targets_orphelins']:
            self.assertIsNone(load_skill(_slug(t['app'])), t)
            self.assertIsNone(load_skill(f"default-{_slug(t['kind'])}"), t)

    def test_le_resume_ignore_titres_et_puces(self):
        self.assertEqual(_resume("# Titre\n\n- puce\nLa vraie phrase.\n"), "La vraie phrase.")
        self.assertEqual(_resume(""), "")


class PageSkillsTests(TestCase):
    """La page se rend — et affiche ce que la synthèse a dérivé, pas une liste réécrite."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('skills_page_test', password='x')

    def test_la_page_se_rend_et_montre_les_skills(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('common:skills_catalog'))
        self.assertEqual(r.status_code, 200)
        noms = {s['nom'] for s in r.context['cat']['skills']}
        self.assertTrue(noms)
        for nom in noms:
            self.assertContains(r, nom)

    def test_la_page_declare_la_facette_famille(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('common:skills_catalog'))
        self.assertEqual([f['cle'] for f in r.context['facettes_skills']], ['famille'])

    def test_le_registre_designe_bien_cette_page(self):
        # C'est le défaut d'origine : un registre sans `url_name` n'a aucune page, et rien ne
        # le disait. Le lien se vérifie donc, il ne se relit pas.
        from wama.common.registries import overview
        skills = next(r for r in overview() if r['key'] == 'skills')
        self.assertEqual(skills['url_name'], 'common:skills_catalog')
        # Et le nom se résout — un `url_name` qui ne pointe nulle part serait la même panne
        # silencieuse, déplacée d'un cran.
        self.assertTrue(reverse(skills['url_name']))
