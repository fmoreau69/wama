"""Tests du catalogue des docs (`common/docs_catalog.py`) : la liste UNIQUE, le lecteur, la garde.

Ce qui est vérifié est ce qui justifie le module :
  - la déclaration est la seule liste — `check_docs` en dérive, et la table d'AGENTS.md ne peut
    pas citer un doc qu'elle ne porte pas (sinon on retrouve deux listes qui divergent) ;
  - le lecteur ne lit QUE ce qui est déclaré, n'exécute aucun HTML des `.md`, et ne fait pas de
    la page un navigateur du dépôt ;
  - la page est réservée aux administrateurs, et le menu dit la même chose que la vue.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .docs_catalog import (AUDIENCES, BY_KEY, BY_PATH, DOCS, FAMILIES, checked_paths, file_of,
                           journal_paths, render_markdown)

BASE = Path(settings.BASE_DIR)


def _cites_de_la_table_agents():
    """Les `.md` cités dans la 2ᵉ colonne de la table « Fichiers de référence par domaine »,
    hors noms anciens (« ex-`…` », « l'ancien `…` ») — eux sont cités POUR être retrouvés."""
    texte = (BASE / 'AGENTS.md').read_text(encoding='utf-8')
    debut = texte.index('### Fichiers de référence par domaine')
    fin = texte.index('\n> ⚠ Cette table', debut)
    cites = []
    for ligne in texte[debut:fin].splitlines():
        cellules = ligne.split('|')
        if not ligne.startswith('|') or len(cellules) < 3:
            continue
        cellule = cellules[2]
        for m in re.finditer(r'`([\w./\-]+\.md)`', cellule):
            avant = cellule[max(0, m.start() - 12):m.start()].lower()
            if 'ex-' in avant or 'ancien' in avant:
                continue
            cites.append(m.group(1))
    return cites


class DeclarationTest(SimpleTestCase):

    def test_chaque_doc_declare_existe_sur_le_disque(self):
        absents = [d.path for d in DOCS if not file_of(d).is_file()]
        self.assertEqual(absents, [], f"docs déclarés mais absents : {absents}")

    def test_cles_et_chemins_uniques(self):
        self.assertEqual(len(BY_KEY), len(DOCS), "clé en double dans DOCS")
        self.assertEqual(len(BY_PATH), len(DOCS), "chemin en double dans DOCS")

    def test_les_cles_sont_utilisables_dans_une_url(self):
        mauvaises = [d.key for d in DOCS if not re.fullmatch(r'[a-z0-9\-]+', d.key)]
        self.assertEqual(mauvaises, [])

    def test_familles_et_audiences_sont_du_vocabulaire_declare(self):
        self.assertEqual([d.key for d in DOCS if d.family not in FAMILIES], [])
        self.assertEqual([d.key for d in DOCS if d.audience not in AUDIENCES], [])

    def test_la_table_d_AGENTS_ne_cite_que_des_docs_declares(self):
        # Le garde-fou de la liste UNIQUE tant que la table reste écrite à la main : un doc de
        # référence ajouté à la table sans être déclaré ici serait invisible du lecteur ET de
        # check_docs — les deux lisent ce catalogue.
        cites = _cites_de_la_table_agents()
        self.assertGreater(len(cites), 20, "table introuvable ou mal lue : le test ne mesure rien")
        orphelins = sorted({c for c in cites
                            if not any(p == c or p.endswith('/' + c) for p in BY_PATH)})
        self.assertEqual(orphelins, [],
                         f"cités par la table d'AGENTS.md mais non déclarés dans docs_catalog : "
                         f"{orphelins}")

    def test_check_docs_derive_du_catalogue(self):
        from wama.common.management.commands.check_docs import DOCS as CIBLES, JOURNAUX
        self.assertEqual(list(CIBLES), checked_paths())
        self.assertEqual(set(JOURNAUX), journal_paths())


class RenduTest(SimpleTestCase):

    def test_le_html_brut_des_md_est_echappe(self):
        html = render_markdown("Avant <script>alert(1)</script>\n\n"
                               "<div onclick='x'>bloc</div>\n")['html']
        self.assertNotIn('<script', html)
        self.assertNotIn('<div', html)
        self.assertIn('&lt;script&gt;', html)

    def test_un_lien_vers_un_doc_declare_mene_au_lecteur(self):
        html = render_markdown("[llm](WAMA_LLM.md#skills)", 'AGENTS.md')['html']
        self.assertIn(f'href="{reverse("common:doc_read", args=["llm"])}#skills"', html)

    def test_un_lien_relatif_se_resout_depuis_le_dossier_du_doc(self):
        html = render_markdown("[carte](README.md)",
                               'wama_lab/cam_analyzer/CAM_ANALYZER_CHANGELOG.md')['html']
        self.assertIn(reverse('common:doc_read', args=['cam-readme']), html)

    def test_un_fichier_non_declare_n_est_pas_cliquable(self):
        html = render_markdown("[env](../.env) et [code](wama/settings.py)", 'AGENTS.md')['html']
        self.assertNotIn('<a ', html)
        self.assertEqual(html.count('wama-doc-horslien'), 2)

    def test_un_lien_externe_s_ouvre_ailleurs(self):
        html = render_markdown("[x](https://example.org)")['html']
        self.assertIn('href="https://example.org"', html)
        self.assertIn('target="_blank"', html)

    def test_javascript_n_est_jamais_un_lien(self):
        # markdown-it refuse le schéma (`validateLink`) : le texte reste, INERTE. La 1ʳᵉ version
        # de ce test cherchait la chaîne `javascript:` et accusait donc un texte sans danger —
        # c'est le LIEN qu'il faut chercher.
        html = render_markdown("[x](javascript:alert(1))")['html']
        self.assertNotIn('<a', html)
        self.assertNotIn('href="javascript', html)

    def test_les_titres_portent_des_ancres_uniques_et_un_texte_propre(self):
        r = render_markdown("## Règle A\n\n## Règle A\n\n### **Gras** et `code`\n")
        self.assertEqual([h['id'] for h in r['toc']], ['règle-a', 'règle-a-1', 'gras-et-code'])
        self.assertEqual(r['toc'][2]['text'], 'Gras et code')
        self.assertIn('id="règle-a-1"', r['html'])

    def test_les_tableaux_sont_rendus(self):
        self.assertIn('<table>', render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n")['html'])


class PageTest(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('docs_admin', 'docs_admin@example.org', 'x')
        self.compte = User.objects.create_user('docs_compte', password='x')

    def test_un_anonyme_est_envoye_se_connecter(self):
        r = self.client.get(reverse('common:docs_catalog'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('accounts:login'), r.url)

    def test_un_compte_non_admin_est_refuse_sur_les_deux_pages(self):
        self.client.force_login(self.compte)
        for url in (reverse('common:docs_catalog'), reverse('common:doc_read', args=['agents'])):
            self.assertEqual(self.client.get(url).status_code, 302, url)

    def test_l_admin_lit_le_catalogue_puis_un_doc(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('common:docs_catalog'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse('common:doc_read', args=['agents']))
        r = self.client.get(reverse('common:doc_read', args=['agents']))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'wama-doc-body')
        self.assertTrue(r.context['rendu']['toc'], "AGENTS.md sans sommaire : rendu vide ?")

    def test_une_cle_non_declaree_rend_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse('common:doc_read', args=['inconnu'])).status_code, 404)

    def test_le_menu_montre_la_doc_a_l_admin_seulement(self):
        cible = reverse('common:docs_catalog')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('accounts:profile')), cible)
        self.client.force_login(self.compte)
        self.assertNotContains(self.client.get(reverse('accounts:profile')), cible)


class RegistreTest(SimpleTestCase):

    def test_le_registre_docs_derive_du_catalogue(self):
        from .registries import DERIVED, REGISTRIES
        r = REGISTRIES['docs']
        self.assertEqual(r.nature, DERIVED)
        self.assertEqual(r.count(), len(DOCS))
        self.assertEqual(reverse(r.url_name), reverse('common:docs_catalog'))
