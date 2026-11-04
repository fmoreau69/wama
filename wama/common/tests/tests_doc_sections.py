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

from ..doc_sections import extract, parse_attrs, sections

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
        autre = "audience=utilisateur; type=explication; nature=intention; etat=⏳; porte=apps/x"
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
            "audience=developpeur,utilisateur; type=reference; nature=constat; etat=✅; "
            "porte=apps/x")
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


class CodeFenceTest(SimpleTestCase):
    """La règle des blocs de code (`code_fence`, CommonMark §4.5) — 2026-11-04 : une ligne qui
    COMMENCE par du code en ligne ouvrait un bloc jamais fermé, et tout ce qui suivait la §10.5 de
    la route disparaissait du lecteur de doc de l'assistant."""

    def test_inline_code_at_the_start_of_a_line_opens_no_block(self):
        text = _doc("# A", "```` ```html ```` retirée et la présence vérifiée.", "# B", "fin")
        self.assertEqual(['A', 'B'], [s.title for s in sections(text)[0]])

    def test_a_block_closes_only_on_the_same_marker_at_least_as_long(self):
        text = _doc("# A", "````", "```", "# inside a block", "~~~", "````", "# B",
                    "~~~", "```", "# inside again", "~~~", "# C")
        self.assertEqual(['A', 'B', 'C'], [s.title for s in sections(text)[0]])

    def test_a_closing_line_carries_nothing_but_its_marker(self):
        text = _doc("# A", "```python", "x = 1", "``` not a close", "# inside", "```", "# B")
        self.assertEqual(['A', 'B'], [s.title for s in sections(text)[0]])


class PorteTest(SimpleTestCase):
    """La porte (⑤) : obligatoire pour l'utilisateur, bien formée, héritée comme le reste."""

    def test_une_section_pour_l_utilisateur_sans_porte_est_refusee(self):
        erreurs = parse_attrs("audience=utilisateur; type=guide; nature=constat; etat=✅")[1]
        self.assertTrue(any('sans porte' in e for e in erreurs), erreurs)

    def test_la_porte_est_facultative_pour_le_developpeur(self):
        self.assertEqual(parse_attrs(OK)[1], [])

    def test_une_porte_se_lit_et_se_verifie_dans_sa_forme(self):
        attrs, erreurs = parse_attrs(f"{OK}; porte=apps/transcriber, apps/imager/has_batch")
        self.assertEqual(erreurs, [])
        self.assertEqual(attrs['porte'], ('apps/transcriber', 'apps/imager/has_batch'))
        for mauvaise in ('apps', 'apps/a/b/c', 'Apps/x', 'apps/'):
            self.assertTrue(any('porte' in e for e in parse_attrs(f"{OK}; porte={mauvaise}")[1]),
                            mauvaise)

    def test_une_sous_section_herite_de_la_porte(self):
        secs, erreurs = sections(_doc(
            "# A", "<!-- WAMA:SECTION(audience=utilisateur; type=guide; nature=constat; etat=✅; "
                   "porte=apps/x) -->", "## A.1", "texte"))
        self.assertEqual(erreurs, [])
        self.assertEqual(secs[1].attrs['porte'], ('apps/x',))


class ExtractionTest(SimpleTestCase):

    def test_extraire_par_public_et_par_type(self):
        texte = _doc("# Dev", f"<!-- WAMA:SECTION({OK}) -->", "pour dev",
                     "# Tous", "<!-- WAMA:SECTION(audience=developpeur,utilisateur; "
                               "type=explication; nature=constat; etat=✅; porte=apps/x) -->",
                     "pour tous",
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

    def test_une_porte_invérifiable_est_cassee(self):
        from ..registries import REGISTRIES
        sans_fiches = next(k for k, r in REGISTRIES.items() if r.entries is None)
        for porte, motif in (('registre_bidon/x', 'inconnu'), (f'{sans_fiches}/x', 'fiches')):
            r = self._rapport(_doc("# T", f"<!-- WAMA:SECTION({OK}; porte={porte}) -->"))
            self.assertIn('CASSÉ', r, porte)
            self.assertIn(motif, r, porte)
        self.assertNotIn('section :', self._rapport(
            _doc("# T", f"<!-- WAMA:SECTION({OK}; porte=apps/transcriber) -->")))


class CorpusTest(SimpleTestCase):

    def test_chaque_section_marquee_du_corpus_est_valide(self):
        from ..docs_catalog import checked_paths
        base = Path(settings.BASE_DIR)
        fautes = []
        for rel in checked_paths():
            f = base / rel
            if f.is_file():
                fautes += [(rel, n, m) for n, m in
                           sections(f.read_text(encoding='utf-8', errors='replace'))[1]]
        self.assertEqual(fautes, [])

    def test_no_document_of_the_corpus_ends_inside_a_code_block(self):
        """Un bloc de code jamais fermé AVALE la fin du document : ses titres ne sont plus des
        titres pour le lecteur de doc, le RAG des docs et `check_docs`. Rend le doc et la ligne
        qui ouvre le bloc."""
        from ..doc_sections import code_fence
        from ..docs_catalog import checked_paths
        base = Path(settings.BASE_DIR)
        unclosed = []
        for rel in checked_paths():
            f = base / rel
            if not f.is_file():
                continue
            fence, opened_at = '', 0
            for number, line in enumerate(f.read_text(encoding='utf-8', errors='replace')
                                          .splitlines(), 1):
                is_fence, after = code_fence(line, fence)
                if is_fence and after:
                    opened_at = number
                fence = after
            if fence:
                unclosed.append((rel, opened_at))
        self.assertEqual(unclosed, [])
