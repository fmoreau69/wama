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

from wama.common.services.skills_catalog import (DOSSIER_ROLES_DEV, DOSSIER_SKILLS_AGENT,
                                                 FAMILLES, _frontmatter, _resume, synthese)


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


class CinqFamillesTest(TestCase):
    """Les 2 familles ajoutées le 2026-09-09 — et surtout l'invariant qui les justifie.

    Rappel du raisonnement, parce qu'il a failli partir dans l'autre sens : on avait envisagé
    de FUSIONNER `wama-dev-ai/prompts/` et `.claude/skills/` en un dossier, au motif qu'ils
    travaillent tous deux sur le code. La mesure l'a interdit — 5 des consignes de rôle sont
    des gabarits `.format()`. Le critère qui tranche est le MÉCANISME DE SÉLECTION, et ces
    tests le figent pour qu'une session suivante ne re-propose pas la fusion.
    """

    def test_les_cinq_familles_sont_declarees(self):
        self.assertEqual(
            ['enrichissement', 'role', 'repli', 'role_dev', 'dev_agent'], list(FAMILLES))

    def test_seule_la_famille_des_agents_est_choisie_par_un_agent(self):
        """L'invariant CENTRAL : la sélection découle de la famille, jamais du dossier."""
        for s in synthese()['skills']:
            with self.subTest(skill=s['nom']):
                attendu = 'agent' if s['famille'] == 'dev_agent' else 'code'
                self.assertEqual(attendu, s['selection'])

    def test_les_gabarits_sont_REPERES_et_seulement_chez_les_roles_dev(self):
        """Un gabarit à `{placeholders}` n'est pas une consigne prête à l'emploi.

        S'il cessait d'être signalé, plus rien n'empêcherait de le porter au format des skills
        d'agent — et la substitution casserait sans bruit à l'exécution du rôle.
        """
        skills = synthese()['skills']
        gabarits = {s['nom'] for s in skills if s['gabarit']}
        self.assertTrue(gabarits, "aucun gabarit repéré : le détecteur de placeholders est muet")
        for s in skills:
            if s['gabarit']:
                self.assertEqual('role_dev', s['famille'],
                                 f"{s['nom']} : un gabarit hors des rôles wama-dev-ai")

    def test_le_registre_publie_le_compte_des_skills_de_PROMPT_pas_celui_de_la_page(self):
        """Deux totaux, deux sens — et c'est le NOM qui doit les tenir séparés.

        `total` = ce que la page liste (5 familles) ; `total_prompt` = ce que publie le registre
        `skills`. Ma première rédaction les avait intervertis, et deux gardes préexistantes
        l'ont attrapé en une seconde (`sum(par_famille) != total`). Les confondre afficherait
        deux nombres différents pour la même chose ici et sur la carte des registres.
        """
        from wama.common.registries import overview
        cat = synthese()
        registre = next(r for r in overview() if r['key'] == 'skills')['total']
        self.assertEqual(registre, cat['total_prompt'])
        self.assertGreater(cat['total'], cat['total_prompt'])

    def test_les_declarations_montrent_AUSSI_les_apps_sans_champ_prompt(self):
        """`synthesizer` déclare `[]` À DESSEIN (§16.6). Invisible, ça se relit comme un oubli."""
        apps = {d['app']: d for d in synthese()['declarations']}
        self.assertIn('synthesizer', apps)
        self.assertTrue(apps['synthesizer']['aucun'])

    def test_le_frontmatter_se_lit_sans_dependance(self):
        meta, corps = _frontmatter("---\nname: x\ndescription: y\n---\n\ncorps\n")
        self.assertEqual({'name': 'x', 'description': 'y'}, meta)
        self.assertEqual('corps\n', corps)
        # Un fichier SANS frontmatter ne doit pas perdre son corps.
        self.assertEqual(({}, 'nu'), _frontmatter('nu'))

    def test_les_deux_dossiers_declares_existent(self):
        from django.conf import settings
        from pathlib import Path
        for rel in (DOSSIER_ROLES_DEV, DOSSIER_SKILLS_AGENT):
            with self.subTest(dossier=rel):
                self.assertTrue((Path(settings.BASE_DIR) / rel).is_dir(),
                                f"{rel} déclaré mais absent — la famille serait vide en silence")
