"""Tests du marquage des sections (`common/doc_sections.py`) — ROADMAP §25.1 ②.

Ce qui est vérifié est ce qui justifie la brique : une section dit à qui elle parle et ce qu'elle
est ; `nature` et `etat` se contrôlent l'un l'autre (double vérification voulue par Fabien) ; une
balise qu'on ne sait pas lire est SIGNALÉE, jamais ignorée ; et `check_docs` en fait un défaut.
"""
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from .doc_sections import extract, parse_attrs, sections

OK = "audience=developpeur; type=guide; nature=constat; etat=✅"


def _doc(*blocs):
    return '\n'.join(blocs) + '\n'


class LectureTest(SimpleTestCase):

    def test_une_section_marquee_se_lit(self):
        secs, erreurs = sections(_doc("# Titre", f"<!-- WAMA:SECTION({OK}) -->", "", "Corps."))
        self.assertEqual(erreurs, [])
        self.assertEqual(secs[0].attrs, {'audience': ('developpeur',), 'type': 'guide',
                                         'nature': 'constat', 'etat': '✅'})
        self.assertFalse(secs[0].inherited)
        self.assertEqual(secs[0].body, "\nCorps.".strip('\n'))

    def test_la_balise_peut_suivre_des_lignes_vides(self):
        secs, erreurs = sections(_doc("## T", "", f"<!-- WAMA:SECTION({OK}) -->"))
        self.assertEqual(erreurs, [])
        self.assertEqual(secs[0].attrs['type'], 'guide')

    def test_une_sous_section_herite_puis_peut_se_redeclarer(self):
        autre = "audience=utilisateur; type=explication; nature=intention; etat=⏳"
        secs, erreurs = sections(_doc("# A", f"<!-- WAMA:SECTION({OK}) -->",
                                      "## A.1", "texte",
                                      "## A.2", f"<!-- WAMA:SECTION({autre}) -->",
                                      "### A.2.a", "texte",
                                      "# B", "texte"))
        self.assertEqual(erreurs, [])
        par_titre = {s.title: s for s in secs}
        self.assertTrue(par_titre['A.1'].inherited)
        self.assertEqual(par_titre['A.1'].attrs['type'], 'guide')
        self.assertEqual(par_titre['A.2.a'].attrs['audience'], ('utilisateur',))
        self.assertEqual(par_titre['B'].attrs, {}, "un frère de niveau 1 n'hérite de rien")

    def test_plusieurs_publics(self):
        attrs, erreurs = parse_attrs(
            "audience=developpeur,utilisateur; type=reference; nature=constat; etat=✅")
        self.assertEqual(erreurs, [])
        self.assertEqual(attrs['audience'], ('developpeur', 'utilisateur'))


class DoubleVerificationTest(SimpleTestCase):
    """nature × etat : un constat est ✅, une intention est 🔄 ou ⏳."""

    def _erreurs(self, nature, etat):
        return parse_attrs(f"audience=developpeur; type=guide; nature={nature}; etat={etat}")[1]

    def test_les_combinaisons_coherentes_passent(self):
        for nature, etat in (('constat', '✅'), ('intention', '🔄'), ('intention', '⏳')):
            self.assertEqual(self._erreurs(nature, etat), [], f"{nature} {etat}")

    def test_un_constat_en_cours_ou_en_attente_est_refuse(self):
        for etat in ('🔄', '⏳'):
            self.assertTrue(any('constat' in e for e in self._erreurs('constat', etat)), etat)

    def test_une_intention_realisee_est_a_requalifier(self):
        self.assertTrue(any('requalifier' in e for e in self._erreurs('intention', '✅')))


class ErreursTest(SimpleTestCase):

    def test_vocabulaire_et_cles_sont_verifies(self):
        for raw, motif in (("audience=chercheur; type=guide; nature=constat; etat=✅", 'audience'),
                           ("audience=developpeur; type=roman; nature=constat; etat=✅", 'type'),
                           ("audience=developpeur; type=guide; nature=reve; etat=✅", 'nature'),
                           ("audience=developpeur; type=guide; nature=constat; etat=ok", 'etat'),
                           ("audience=developpeur; type=guide; nature=constat", 'manquante'),
                           (f"{OK}; public=tous", 'inconnue'),
                           (f"{OK}; type=guide", 'double'),
                           (f"{OK}; bancal", 'clé=valeur')):
            self.assertTrue(any(motif in e for e in parse_attrs(raw)[1]), raw)

    def test_une_balise_hors_titre_est_signalee(self):
        _, erreurs = sections(_doc("# T", "Un paragraphe.", f"<!-- WAMA:SECTION({OK}) -->"))
        self.assertEqual(len(erreurs), 1)
        self.assertIn('hors', erreurs[0][1])

    def test_une_balise_mal_formee_n_est_pas_ignoree_en_silence(self):
        _, erreurs = sections(_doc("# T", f"<!-- WAMA:SECTION({OK}) --> suivi de texte"))
        self.assertTrue(any('mal formée' in e for _, e in erreurs))

    def test_une_balise_citee_en_code_n_est_pas_une_balise(self):
        texte = _doc("# T", "La syntaxe : `<!-- WAMA:SECTION(x) -->`.",
                     "```", f"<!-- WAMA:SECTION(pas=une; vraie=balise) -->", "```")
        self.assertEqual(sections(texte)[1], [])


class ExtractionTest(SimpleTestCase):

    def test_extraire_par_public_et_par_type(self):
        texte = _doc("# Dev", f"<!-- WAMA:SECTION({OK}) -->", "pour dev",
                     "# Tous", "<!-- WAMA:SECTION(audience=developpeur,utilisateur; "
                               "type=explication; nature=constat; etat=✅) -->", "pour tous",
                     "# Rien", "construction seule")
        self.assertEqual([s.title for s in extract(texte, 'developpeur')], ['Dev', 'Tous'])
        self.assertEqual([s.title for s in extract(texte, 'utilisateur')], ['Tous'])
        self.assertEqual([s.title for s in extract(texte, 'developpeur', 'guide')], ['Dev'])


class CheckDocsTest(SimpleTestCase):
    """Une section incohérente est un défaut de `check_docs` — pas une note de bas de page."""

    def _rapport(self, corps):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / 'DOC.md').write_text(corps, encoding='utf-8')
        sortie = StringIO()
        with override_settings(BASE_DIR=tmp.name):
            call_command('check_docs', '--doc', 'DOC.md', stdout=sortie)
        return sortie.getvalue()

    def test_un_constat_en_attente_est_casse(self):
        r = self._rapport(_doc("# T", "<!-- WAMA:SECTION(audience=developpeur; type=guide; "
                                      "nature=constat; etat=⏳) -->"))
        self.assertIn('CASSÉ', r)
        self.assertIn('section : constat', r)

    def test_une_section_coherente_passe(self):
        self.assertNotIn('section :', self._rapport(_doc("# T", f"<!-- WAMA:SECTION({OK}) -->")))


class CorpusTest(SimpleTestCase):

    def test_chaque_section_marquee_du_corpus_est_valide(self):
        from .docs_catalog import checked_paths
        base = Path(settings.BASE_DIR)
        fautes = []
        for rel in checked_paths():
            f = base / rel
            if f.is_file():
                fautes += [(rel, n, m) for n, m in
                           sections(f.read_text(encoding='utf-8', errors='replace'))[1]]
        self.assertEqual(fautes, [])
