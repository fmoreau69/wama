"""Tests du catalogue des docs (`common/docs_catalog.py`) et de la doc développeur générée
(`common/dev_docs.py`) : la liste UNIQUE, le lecteur, la garde, les projections.

Ce qui est vérifié est ce qui justifie ces modules :
  - la déclaration est la seule liste — `check_docs` en dérive, et la table d'AGENTS.md ne peut
    pas citer un doc qu'elle ne porte pas (sinon on retrouve deux listes qui divergent) ;
  - le lecteur ne lit QUE ce qui est déclaré, n'exécute aucun HTML des `.md`, et ne fait pas de
    la page un navigateur du dépôt ;
  - la page est réservée aux administrateurs, et le menu dit la même chose que la vue ;
  - une page développeur est une PROJECTION : elle couvre TOUT son registre, pas un échantillon.
"""
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .dev_docs import PARCOURS, module_api
from .docs_catalog import (AUDIENCES, BY_KEY, BY_PATH, DEVELOPER, DOCS, FAMILIES, checked_paths,
                           file_of, generate, journal_paths, render_doc, render_markdown)

BASE = Path(settings.BASE_DIR)
FICHIERS = [d for d in DOCS if d.path]
GENEREES = [d for d in DOCS if d.generator]


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

    def test_chaque_doc_fichier_existe_sur_le_disque(self):
        absents = [d.path for d in FICHIERS if not file_of(d).is_file()]
        self.assertEqual(absents, [], f"docs déclarés mais absents : {absents}")

    def test_une_doc_est_un_fichier_OU_une_generee_jamais_les_deux(self):
        self.assertEqual([d.key for d in DOCS if bool(d.path) == bool(d.generator)], [])

    def test_cles_et_chemins_uniques(self):
        self.assertEqual(len(BY_KEY), len(DOCS), "clé en double dans DOCS")
        self.assertEqual(len(BY_PATH), len(FICHIERS), "chemin en double dans DOCS")

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

    def test_check_docs_derive_du_catalogue_sans_les_pages_generees(self):
        from wama.common.management.commands.check_docs import DOCS as CIBLES, JOURNAUX
        self.assertEqual(list(CIBLES), checked_paths())
        self.assertEqual(set(JOURNAUX), journal_paths())
        self.assertNotIn('', CIBLES)

    def test_le_parcours_ne_cite_que_des_docs_declares(self):
        self.assertEqual([k for k in PARCOURS if k not in BY_KEY], [])


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

    def test_un_lien_de_site_n_est_suivi_que_depuis_une_page_generee(self):
        # Dans un `.md` du dépôt, `/x` désigne un fichier à la racine : pas une page de WAMA.
        self.assertNotIn('<a ', render_markdown("[b](/common/backends/)")['html'])
        self.assertIn('href="/common/backends/"',
                      render_markdown("[b](/common/backends/)", site_links=True)['html'])

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

    def test_un_commentaire_html_est_masque_comme_sur_github(self):
        # Les marqueurs `WAMA:FAITS` s'affichaient en texte brut avant le 2026-09-11.
        html = render_markdown("<!-- WAMA:FAITS(x) — généré -->\ncontenu\n"
                               "<!-- /WAMA:FAITS(x) -->\n")['html']
        self.assertNotIn('WAMA:FAITS', html)
        self.assertIn('contenu', html)

    def test_un_fait_en_ligne_montre_sa_valeur_sans_ses_balises(self):
        html = render_markdown(
            "Il y a <!-- WAMA:FAIT(registres) -->15<!-- /WAMA:FAIT --> registres.")['html']
        self.assertIn('Il y a 15 registres.', html)
        self.assertNotIn('WAMA:FAIT', html)

    def test_un_commentaire_cite_en_code_reste_lisible(self):
        # Masquer les commentaires ne doit pas effacer une doc qui EXPLIQUE la syntaxe.
        html = render_markdown("La balise `<!-- WAMA:FAIT(x) -->` s'écrit ainsi.")['html']
        self.assertIn('&lt;!-- WAMA:FAIT(x) --&gt;', html)


class ModuleApiTest(SimpleTestCase):
    """L'API d'une brique est lue par AST — ce qu'on montre doit être ce que le code DÉCLARE."""

    def _api(self, source):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        f = Path(tmp.name) / 'mod.py'
        f.write_text(source, encoding='utf-8')
        return module_api(f)

    def test_signatures_docstrings_et_prives_exclus(self):
        api = self._api('"""Module X.\n\nDétail qui ne sort pas."""\n'
                        'def f(a, b=1, *, c: str = "x") -> int:\n    """Fait f.\n\n    Plus."""\n'
                        'def _cache():\n    pass\n'
                        'class C(Base):\n    """La classe C."""\n')
        self.assertTrue(api['lisible'])
        self.assertEqual(api['doc'], 'Module X.')
        self.assertEqual([i['name'] for i in api['items']], ['f', 'C'])
        self.assertEqual(api['items'][0]['sig'], "f(a, b=1, *, c: str='x') -> int")
        self.assertEqual(api['items'][0]['doc'], 'Fait f.')
        self.assertEqual(api['items'][1]['sig'], 'class C(Base)')

    def test_un_module_illisible_le_dit(self):
        self.assertFalse(self._api("def (:\n")['lisible'])
        self.assertFalse(module_api(Path('/nulle/part/absent.py'))['lisible'])


class DocDeveloppeurTest(TestCase):
    """Les pages générées couvrent TOUT leur registre — une projection partielle mentirait."""

    def test_chaque_page_generee_se_rend(self):
        for d in GENEREES:
            r = render_doc(d)
            self.assertTrue(r['toc'], f"{d.key} : page sans titre")
            self.assertEqual(d.audience, DEVELOPER, d.key)

    def test_les_registres_sont_tous_projetes(self):
        from .registries import REGISTRIES
        texte = generate(BY_KEY['dev-registres'])
        manquants = [k for k in REGISTRIES if f"`{k}`" not in texte]
        self.assertEqual(manquants, [])

    def test_chaque_mecanisme_a_sa_section(self):
        from .mecanismes import MECANISMES
        toc = render_doc(BY_KEY['dev-briques'])['toc']
        self.assertEqual(sum(1 for h in toc if h['level'] == 3), len(MECANISMES))

    def test_le_parcours_mene_au_lecteur(self):
        html = render_doc(BY_KEY['dev-parcours'])['html']
        for cle in PARCOURS:
            self.assertIn(reverse('common:doc_read', args=[cle]), html, cle)


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

    def test_l_admin_lit_une_page_generee(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('common:doc_read', args=['dev-briques']))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'API publique')

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
