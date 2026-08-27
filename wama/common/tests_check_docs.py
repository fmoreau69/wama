"""Verrouille le contrôle d'intégrité `check_docs`, skills comprises.

Pourquoi ces tests existent : le 2026-08-26, l'audit des 11 skills a trouvé que 8 portaient des
chiffres ou des chemins faux — dont `/brique`, qui envoyait explorer un package déporté quatre
jours plus tôt. **Rien ne les contrôlait.** La commande a été étendue le 27/08 ; ces tests
prouvent qu'elle DÉTECTE, au lieu d'annoncer « 0 cassée » sur un corpus qu'elle ne lit pas.

C'est la leçon récurrente du dépôt : un harnais qui ne voit rien annonce zéro échec exactement
comme un harnais qui voit tout et ne trouve rien. Seule une régression INJECTÉE les distingue.
"""
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from wama.common.management.commands.check_docs import JOURNAUX, _hors_depot

SKILL_MINIMAL = "---\nname: {nom}\ndescription: skill de test\n---\n\n# /{nom}\n\n{corps}\n"


def _depot_temporaire(nom, corps):
    """Un dépôt jetable ne contenant qu'une skill : `--skills` n'a besoin de rien d'autre."""
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name) / '.claude' / 'skills' / nom
    d.mkdir(parents=True)
    (d / 'SKILL.md').write_text(SKILL_MINIMAL.format(nom=nom, corps=corps), encoding='utf-8')
    return tmp


def _rapport(tmp):
    sortie = StringIO()
    call_command('check_docs', '--skills', stdout=sortie)
    return sortie.getvalue()


class ChecksDocsSkillsTests(SimpleTestCase):

    def _lancer(self, nom, corps):
        tmp = _depot_temporaire(nom, corps)
        self.addCleanup(tmp.cleanup)
        with override_settings(BASE_DIR=tmp.name):
            return _rapport(tmp)

    def test_un_chemin_de_code_inexistant_dans_une_skill_est_signale(self):
        r = self._lancer('essai', "Voir `wama/common/utils/inexistant_xyz.py` pour le détail.")
        self.assertIn('inexistant_xyz.py', r)
        self.assertIn('CASSÉ', r)

    def test_un_doc_de_reference_inexistant_dans_une_skill_est_signale(self):
        r = self._lancer('essai', "Lire d'abord `DOC_FANTOME_XYZ.md`.")
        self.assertIn('DOC_FANTOME_XYZ.md', r)

    def test_un_nom_de_frontmatter_qui_ne_vaut_pas_le_dossier_est_signale(self):
        tmp = _depot_temporaire('essai', "Rien à signaler.")
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / '.claude' / 'skills' / 'essai' / 'SKILL.md'
        p.write_text(p.read_text(encoding='utf-8').replace('name: essai', 'name: autre'),
                     encoding='utf-8')
        with override_settings(BASE_DIR=tmp.name):
            r = _rapport(tmp)
        self.assertIn('≠ dossier', r)

    def test_une_skill_saine_ne_declenche_aucune_alerte(self):
        # Le pendant indispensable : un contrôle qui signale TOUT ne vaut pas mieux qu'un
        # contrôle qui ne signale rien.
        r = self._lancer('essai', "Rien que du texte, sans référence.")
        self.assertIn('Aucune référence cassée', r)

    def test_une_reference_declaree_supprimee_ne_declenche_pas(self):
        r = self._lancer('essai', "- `wama/x/parti_xyz.py` — SUPPRIMÉ le 2026-01-01.")
        self.assertIn('Aucune référence cassée', r)

    def test_un_qualificatif_en_tete_de_puce_couvre_toute_la_puce(self):
        # Fenêtre élargie le 2026-08-27 : « archivés » ouvrait une puce de trois lignes et le
        # 3e fichier, hors fenêtre ±1, était signalé à tort.
        r = self._lancer('essai', "- Remplacés (archivés `docs/archive/`) : `a/un_xyz.py`,\n"
                                  "  `a/deux_xyz.py`,\n"
                                  "  `a/trois_xyz.py`.")
        self.assertIn('Aucune référence cassée', r)


class ChiffreSansSourceTests(SimpleTestCase):
    """3ᵉ famille (27/08) : un chiffre en position de CONSTAT doit dire d'où il vient.

    Le défaut qui l'a motivée ne cassait aucune référence : `/port-app` annonçait « F6/F7/F8 :
    ZÉRO critère » alors que les critères couvrent les 8 facettes. Le chemin existait, le chiffre
    mentait — angle mort total du contrôle de références.

    Un skill est de la doctrine EXÉCUTABLE : on lui OBÉIT. Un chiffre faux y coûte plus cher que
    dans un doc, et un chiffre périmé posé à côté de la bonne règle se fait lire à sa place.
    """

    def _lancer(self, corps):
        tmp = _depot_temporaire('essai', corps)
        self.addCleanup(tmp.cleanup)
        with override_settings(BASE_DIR=tmp.name):
            return _rapport(tmp)

    def test_un_chiffre_nu_en_position_de_constat_est_signale(self):
        r = self._lancer("La grille couvre 82 critères aujourd'hui.")
        self.assertIn('CHIFFRE SANS SOURCE', r)
        self.assertIn('82 critères', r)

    def test_zero_en_toutes_lettres_compte_comme_un_chiffre(self):
        # C'est la graphie EXACTE du défaut du 26/08. Sans elle, la famille aurait raté le seul
        # cas qui l'a fait naître — un contrôle qui ne détecte pas son propre motif fondateur.
        r = self._lancer("F6/F7/F8 : ZÉRO critère, et 12 apps portées.")
        self.assertIn('CHIFFRE SANS SOURCE', r)

    def test_le_chiffre_apres_deux_points_est_vu_aussi(self):
        r = self._lancer("Bilan : critères : 82, et rien d'autre à dire.")
        self.assertIn('CHIFFRE SANS SOURCE', r)

    def test_la_commande_qui_produit_le_chiffre_l_acquitte(self):
        r = self._lancer("La grille couvre 82 critères — mesurer avec\n"
                         "`python manage.py check_app_conformity`.")
        self.assertNotIn('CHIFFRE SANS SOURCE', r)

    def test_une_date_de_releve_acquitte_le_chiffre(self):
        # La date ne rend pas le chiffre vrai : elle le rend DATÉ, donc relisible comme un constat
        # d'époque plutôt que comme une règle. C'est exactement ce qu'on demande.
        r = self._lancer("Relevé du 2026-08-26 : 82 critères couvrant les 8 facettes.")
        self.assertNotIn('CHIFFRE SANS SOURCE', r)

    def test_un_bloc_genere_doc_facts_est_hors_perimetre(self):
        # Le contenu d'un bloc généré n'est pas écrit à la main : le signaler demanderait de
        # corriger une sortie de commande, c'est-à-dire de mentir à la source.
        r = self._lancer("<!-- WAMA:FAITS(mecanismes) -->\n"
                         "La grille couvre 82 critères.\n"
                         "<!-- /WAMA:FAITS(mecanismes) -->")
        self.assertNotIn('CHIFFRE SANS SOURCE', r)

    def test_un_bloc_de_code_est_hors_perimetre(self):
        r = self._lancer("```bash\npython -c \"print(82)\"  # 82 critères\n```")
        self.assertNotIn('CHIFFRE SANS SOURCE', r)

    def test_une_erreur_passee_citee_entre_guillemets_n_est_pas_reprochee(self):
        # Faux positif réel : `/reprise` cite « un défaut dans les 11 apps » pour dire que c'était
        # FAUX. Reprocher sa propre citation d'erreur apprendrait à ne plus consigner les erreurs.
        r = self._lancer("Ce skill a longtemps annoncé « un défaut dans les 11 apps » — c'était faux.")
        self.assertNotIn('CHIFFRE SANS SOURCE', r)

    def test_un_chiffre_qui_ne_compte_rien_ne_declenche_pas(self):
        # Le filtrage se fait par NOM COMPTABLE, pas par exclusion de faux positifs : la liste des
        # choses que WAMA compte est courte et stable, celle des nombres qui ne comptent rien est
        # infinie. Versions, ports et dates ne doivent donc jamais entrer dans la famille.
        r = self._lancer("Django 5.2 écoute sur le port 8000 depuis le 2026-01-01.")
        self.assertNotIn('CHIFFRE SANS SOURCE', r)

    def test_un_chiffre_non_source_n_est_pas_excuse_par_supprime(self):
        # Deux familles distinctes : « supprimé » excuse une RÉFÉRENCE morte, jamais un chiffre.
        r = self._lancer("- 12 apps portées — SUPPRIMÉ.")
        self.assertIn('CHIFFRE SANS SOURCE', r)


class HorsDepotTests(SimpleTestCase):
    """La mémoire Claude vit hors du dépôt : la citer n'est pas une référence morte."""

    def test_les_fichiers_de_memoire_claude_sont_hors_perimetre(self):
        for c in ('MEMORY.md', 'memory/project_x.md', 'project_wama_data_chantier.md',
                  'reference_infra_wsl_windows.md', 'feedback_no_destructive_tests.md',
                  'user_context.md'):
            self.assertTrue(_hors_depot(c), c)

    def test_un_doc_du_depot_reste_dans_le_perimetre(self):
        for c in ('CLAUDE.md', 'WAMA_LLM.md', 'wama/common/README.md', 'ROADMAP.md'):
            self.assertFalse(_hors_depot(c), c)


class ContratNocturneTests(SimpleTestCase):
    """Le gate nocturne compte des CIBLES DISTINCTES — pending du 23/08, soldé le 27/08.

    ⚠ Le défaut suivant n'a été trouvé qu'en LANÇANT le scénario : l'en-tête du rapport porte
    lui aussi une flèche (« INTÉGRITÉ DOCS+SKILLS → CODE ») et comptait pour une cible. La
    commande affichait 1 cible, le scénario en voyait 2 et restait rouge.
    """

    #: Toute sortie conforme porte la ligne de la 3ᵉ famille (27/08). Les fixtures la posent donc
    #: par défaut : son ABSENCE est elle-même un échec (contrôle muet), éprouvée à part plus bas.
    CHIFFRES_ZERO = "Chiffres sans source : 0 (skills)\n"

    def _verdict(self, sortie, chiffres=CHIFFRES_ZERO):
        from wama.common import nightly_scenarios as ns
        with patch.object(ns, '_capture', return_value=(1, sortie + chiffres)):
            return ns._run_check_docs(None)

    def test_une_meme_cible_citee_cinq_fois_ne_compte_que_pour_une(self):
        lignes = '\n'.join(f"  PROJECT_STATUS.md:{n}  fichier inexistant → common/_x.html"
                           for n in (10, 20, 30, 40, 50))
        ok, detail = self._verdict(f"INTÉGRITÉ DOCS+SKILLS → CODE  (11 documents)\n"
                                   f"CASSÉ (5) :\n{lignes}\n"
                                   f"Bilan : 5 cassée(s), 0 périmée(s)\n")
        self.assertTrue(ok, detail)
        self.assertIn('1 cible(s) distincte(s)', detail)

    def test_la_fleche_de_l_en_tete_ne_compte_pas_pour_une_cible(self):
        ok, detail = self._verdict("INTÉGRITÉ DOCS+SKILLS → CODE  (11 documents)\n"
                                   "CASSÉ (1) :\n"
                                   "  PROJECT_STATUS.md:10  fichier inexistant → common/_x.html\n"
                                   "Bilan : 1 cassée(s), 0 périmée(s)\n")
        self.assertTrue(ok, detail)
        self.assertIn('1 cible(s) distincte(s)', detail)

    def test_une_deuxieme_cible_distincte_fait_echouer_le_contrat(self):
        ok, detail = self._verdict("INTÉGRITÉ DOCS+SKILLS → CODE\n"
                                   "CASSÉ (2) :\n"
                                   "  A.md:1  fichier inexistant → common/_x.html\n"
                                   "  B.md:2  fichier inexistant → wama/y/z.py\n"
                                   "Bilan : 2 cassée(s), 0 périmée(s)\n")
        self.assertFalse(ok, detail)

    def test_un_defaut_franc_de_skill_n_est_jamais_assume(self):
        # Un frontmatter invalide ne désigne aucune cible à créer : tolérance zéro.
        ok, detail = self._verdict("INTÉGRITÉ DOCS+SKILLS → CODE\n"
                                   "CASSÉ (1) :\n"
                                   "  .claude/skills/x/SKILL.md:1  `name: autre` ≠ dossier `x`\n"
                                   "Bilan : 1 cassée(s), 0 périmée(s)\n")
        self.assertFalse(ok, detail)
        self.assertIn('défaut(s) franc(s)', detail)

    def test_le_bloc_perime_ne_gonfle_pas_les_defauts_francs(self):
        ok, detail = self._verdict("INTÉGRITÉ DOCS+SKILLS → CODE\n"
                                   "PÉRIMÉ (1) :\n"
                                   "  A.md:3  wama/x.py:900 — le fichier n'a que 10 lignes\n"
                                   "Bilan : 0 cassée(s), 1 périmée(s)\n")
        self.assertFalse(ok, detail)          # une périmée reste un échec…
        self.assertNotIn('défaut(s) franc(s)', detail)   # …mais pas un « défaut franc »

    def test_un_chiffre_sans_source_fait_echouer_le_contrat(self):
        ok, detail = self._verdict("INTÉGRITÉ DOCS+SKILLS → CODE\n"
                                   "Bilan : 0 cassée(s), 0 périmée(s)\n",
                                   chiffres="Chiffres sans source : 1 (skills)\n")
        self.assertFalse(ok, detail)
        self.assertIn('chiffre(s) sans source', detail)

    def test_la_ligne_absente_n_est_PAS_lue_comme_un_zero(self):
        # ⚠ Le défaut que j'ai écrit en premier, et qui est le défaut RÉCURRENT du dépôt : une
        # ligne manquante lue comme 0 rend le scénario VERT sur un contrôle MUET — exactement le
        # harnais qui annonce « 0 échec » sur du vide. Ligne absente = pas conforme, et on le dit.
        ok, detail = self._verdict("INTÉGRITÉ DOCS+SKILLS → CODE\n"
                                   "Bilan : 0 cassée(s), 0 périmée(s)\n",
                                   chiffres="")
        self.assertFalse(ok, detail)
        self.assertIn('ABSENTE', detail)


class JournauxTests(SimpleTestCase):
    """Un journal consigne ce qui était vrai à une date : ses renvois .md ne se corrigent pas."""

    def test_le_statut_projet_est_declare_journal(self):
        self.assertIn('PROJECT_STATUS.md', JOURNAUX)

    def test_les_docs_de_doctrine_ne_sont_pas_des_journaux(self):
        # L'exemption doit rester ÉTROITE : elle vaut pour l'archive datée, pas pour la doctrine.
        for d in ('CLAUDE.md', 'WAMA_APP_CONVENTIONS.md', 'WAMA_MECANISMES.md'):
            self.assertNotIn(d, JOURNAUX)
