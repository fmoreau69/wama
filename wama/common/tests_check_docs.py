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

    def _verdict(self, sortie):
        from wama.common import nightly_scenarios as ns
        with patch.object(ns, '_capture', return_value=(1, sortie)):
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


class JournauxTests(SimpleTestCase):
    """Un journal consigne ce qui était vrai à une date : ses renvois .md ne se corrigent pas."""

    def test_le_statut_projet_est_declare_journal(self):
        self.assertIn('PROJECT_STATUS.md', JOURNAUX)

    def test_les_docs_de_doctrine_ne_sont_pas_des_journaux(self):
        # L'exemption doit rester ÉTROITE : elle vaut pour l'archive datée, pas pour la doctrine.
        for d in ('CLAUDE.md', 'WAMA_APP_CONVENTIONS.md', 'WAMA_MECANISMES.md'):
            self.assertNotIn(d, JOURNAUX)
