"""
Corpus SYSTÈME — la doc de WAMA rappelable par l'assistant (`common/memory/docs_corpus.py`).
Doc : `WAMA_MEMORY.md §7quinquies`.

CE QU'ON PROTÈGE, dans l'ordre de ce qui coûterait le plus cher :

  1. la GARDE — une doc qu'un compte ne peut pas ouvrir dans le lecteur n'existe pas non plus
     pour son assistant (recherche ET lecture), et un visiteur n'a rien ;
  2. la SÉPARATION — ces fragments n'entrent dans AUCUN RAG d'utilisateur : ni le rappel par
     défaut, ni « Mon RAG ». La règle « l'entrée au RAG est un geste » reste entière ;
  3. la RE-DÉRIVATION — projeter deux fois ne réécrit rien, un fragment inchangé garde son
     vecteur, un doc sorti du catalogue sort du corpus ;
  4. les JOURNAUX datés ne sont pas rappelés par morceaux.

⚠ AUCUN APPEL DE MODÈLE : l'embedding de la requête est neutralisé (`embed_text` → None), le
rappel tourne en lexical seul. Un test ne charge jamais un modèle (`WAMA_MEMORY §5bis`).
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.test import TestCase

from wama import tool_api as T
from wama.common import docs_catalog
from wama.common.docs_catalog import CONSTRUCTION, DOCS, USER, Doc
from wama.common.memory import docs_corpus, recall
from wama.common.memory.index import list_rag
from wama.common.models import RagChunk, scoped_visible_q

NO_EMBEDDER = mock.patch('wama.common.memory.embed.embed_text', return_value=None)


def _key_of(chunk):
    return chunk.source_id[len(docs_corpus.SOURCE_PREFIX):]


class RealCatalogTests(TestCase):
    """Sur le catalogue RÉEL : la garde et la séparation valent pour chaque doc déclaré."""

    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user('wama_docs_member', password='x')
        cls.admin = User.objects.create_superuser('wama_docs_admin', password='x')
        cls.summary = docs_corpus.index_docs()

    def test_every_readable_doc_enters_and_no_dated_log_does(self):
        indexed = {_key_of(c) for c in RagChunk.objects.filter(
            source_id__startswith=docs_corpus.SOURCE_PREFIX)}
        journals = {d.key for d in DOCS if d.journal}
        self.assertTrue(journals, "le catalogue ne porte plus de journal : test à revoir")
        self.assertFalse(indexed & journals)
        expected = {d.key for d in DOCS if not d.journal} - set(self.summary['missing'])
        # Un doc sans aucun texte sous ses titres n'a pas de fragment : on compare donc à ceux
        # qui en PRODUISENT, pas à la liste nue.
        self.assertLessEqual(indexed, expected)
        self.assertGreater(len(indexed), len(expected) * 0.9)

    def test_a_second_run_writes_nothing(self):
        again = docs_corpus.index_docs()
        self.assertEqual(again['written'], [])
        self.assertEqual(again['removed'], [])
        self.assertEqual(again['unchanged'], again['docs'])

    def test_the_corpus_stays_out_of_every_user_rag(self):
        for user in (self.member, self.admin):
            visible = RagChunk.objects.filter(scoped_visible_q(user))
            self.assertFalse(visible.filter(
                source_id__startswith=docs_corpus.SOURCE_PREFIX).exists(), user.username)
            self.assertEqual(list_rag(user), [])
            with NO_EMBEDDER:
                hits = recall('transcription correction mémoire', user=user)
            self.assertFalse([h for h in hits if h.source == 'docs'])

    def test_a_member_only_reaches_the_user_docs(self):
        audience_of = {d.key: d.audience for d in DOCS}
        keys = {_key_of(c) for c in docs_corpus.visible_chunks(self.member)}
        self.assertTrue(keys, "aucune doc utilisateur indexée : la garde ne prouverait rien")
        self.assertEqual({audience_of[k] for k in keys}, {USER})

    def test_an_administrator_reaches_the_construction_docs_too(self):
        audience_of = {d.key: d.audience for d in DOCS}
        keys = {_key_of(c) for c in docs_corpus.visible_chunks(self.admin)}
        self.assertIn(CONSTRUCTION, {audience_of[k] for k in keys})

    def test_a_visitor_reaches_nothing(self):
        self.assertFalse(docs_corpus.visible_chunks(AnonymousUser()).exists())
        self.assertFalse(docs_corpus.visible_chunks(None).exists())
        self.assertIn('error', T.search_docs(AnonymousUser(), 'transcription'))
        self.assertIn('error', T.read_doc(AnonymousUser(), 'agents'))

    def test_the_search_tool_never_returns_a_doc_the_reader_would_hide(self):
        # « ScopedVisibility » est un mot de la doc de construction : un membre ne doit en
        # recevoir aucun extrait, un administrateur si.
        with NO_EMBEDDER:
            for_member = T.search_docs(self.member, 'ScopedVisibility héritage OrgUnit')
            for_admin = T.search_docs(self.admin, 'ScopedVisibility héritage OrgUnit')
        self.assertEqual([r for r in for_member['results'] if r['audience'] != 'doc utilisateur'],
                         [])
        self.assertTrue(for_admin['results'])
        hit = for_admin['results'][0]
        for field in ('doc', 'label', 'section', 'location', 'url', 'content', 'score'):
            self.assertIn(field, hit)
        self.assertTrue(any('caution' in r for r in for_admin['results']))

    def test_reading_gives_the_outline_then_a_section(self):
        outline = T.read_doc(self.admin, 'memory')
        self.assertTrue(outline['outline'])
        title = outline['outline'][1]['title']
        section = T.read_doc(self.admin, 'memory', title)
        self.assertIn(title, section['content'])
        self.assertIn('truncated', section)

    def test_a_hidden_doc_reads_like_an_unknown_one(self):
        hidden = T.read_doc(self.member, 'agents')
        unknown = T.read_doc(self.member, 'no-such-doc')
        self.assertIn('error', hidden)
        self.assertNotIn('outline', hidden)
        self.assertEqual(hidden['error'].replace('agents', 'X'),
                         unknown['error'].replace('no-such-doc', 'X'))

    def test_a_dated_log_is_still_readable_whole(self):
        dated = next(d for d in DOCS if d.journal)
        self.assertTrue(T.read_doc(self.admin, dated.key).get('journal'))

    def test_both_tools_are_registered_described_and_transverse(self):
        described = T.tool_descriptions()
        for name in ('search_docs', 'read_doc'):
            self.assertIn(name, T.TOOL_REGISTRY)
            self.assertTrue(str(described[name]['description']).strip(), name)
            self.assertIsNone(T.app_id_for_tool(name), name)


class RederivationTests(TestCase):
    """Sur un catalogue d'UN doc temporaire : ce qui se réécrit, ce qui se garde, ce qui sort."""

    FIRST = ("# Guide\n\nIntroduction du guide.\n\n## Lancer\n\nPour lancer, cliquer sur Démarrer.\n\n"
             "## Vision\n<!-- WAMA:SECTION(audience=developpeur; type=explication; "
             "nature=intention; etat=⏳) -->\n\nUn jour, tout sera automatique.\n\n## Vide\n")

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / 'guide.md'
        self.path.write_text(self.FIRST, encoding='utf-8')
        self.doc = Doc('wama-test-guide', 'docs/test/guide.md', 'Guide de test', 'doctrine',
                       "Un doc de test.", audience=USER)
        for target, value in (('wama.common.memory.docs_corpus.indexed_docs', [self.doc]),
                              ('wama.common.docs_catalog.file_of', self.path)):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _rows(self):
        return list(RagChunk.objects.filter(
            source_id=docs_corpus.source_id_of(self.doc.key)).order_by('ordinal'))

    def test_a_section_carries_its_title_its_line_and_its_stated_nature(self):
        docs_corpus.index_docs()
        rows = self._rows()
        self.assertEqual(len(rows), 3)                       # « Vide » n'a pas de texte
        self.assertTrue(rows[1].content.startswith('## Lancer'))
        self.assertEqual(rows[1].source_ref, 'docs/test/guide.md:5 § Lancer')
        self.assertTrue(rows[2].source_ref.endswith('§ Vision [intention ⏳]'))
        self.assertNotIn('WAMA:SECTION', rows[2].content)
        for row in rows:
            self.assertIsNone(row.user_id)
            self.assertIsNone(row.embedding)

    def test_an_unchanged_fragment_keeps_its_vector_when_the_doc_changes(self):
        docs_corpus.index_docs()
        RagChunk.objects.filter(pk__in=[r.pk for r in self._rows()]).update(
            embedding=[0.5] * 1024, embedding_model='bge-m3')
        self.path.write_text(self.FIRST + "\n## Ajout\n\nUne section de plus.\n", encoding='utf-8')
        summary = docs_corpus.index_docs()
        self.assertEqual(summary['written'], [self.doc.key])
        rows = self._rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual([r.embedding is not None for r in rows], [True, True, True, False])
        self.assertEqual(rows[0].embedding_model, 'bge-m3')

    def test_a_dry_run_writes_nothing(self):
        summary = docs_corpus.index_docs(dry_run=True)
        self.assertEqual(summary['written'], [self.doc.key])
        self.assertEqual(self._rows(), [])

    def test_a_doc_that_leaves_the_catalogue_leaves_the_corpus(self):
        docs_corpus.index_docs()
        self.assertTrue(self._rows())
        with mock.patch('wama.common.memory.docs_corpus.indexed_docs', return_value=[]):
            summary = docs_corpus.index_docs()
        self.assertEqual(summary['removed'], [docs_corpus.source_id_of(self.doc.key)])
        self.assertEqual(self._rows(), [])

    def test_an_unreadable_file_destroys_nothing(self):
        docs_corpus.index_docs()
        with mock.patch.object(docs_catalog, 'file_of', return_value=Path(self.dir.name) / 'gone.md'):
            summary = docs_corpus.index_docs()
        self.assertEqual(summary['missing'], [self.doc.key])
        self.assertEqual(len(self._rows()), 3)

    def test_a_user_fragment_is_never_touched_by_the_projection(self):
        owner = User.objects.create_user('wama_docs_owner', password='x')
        RagChunk.objects.create(content='à moi', content_hash='h', source_kind='doc',
                                source_id='transcriber:1', ordinal=0, user=owner)
        docs_corpus.index_docs()
        with mock.patch('wama.common.memory.docs_corpus.indexed_docs', return_value=[]):
            docs_corpus.index_docs()
        self.assertTrue(RagChunk.objects.filter(user=owner, source_id='transcriber:1').exists())
