"""Vectoriser le RAG et les souvenirs (2026-10-16, décision de Fabien) : la page « Mon RAG »
annonçait « le prochain lot d'indexation » alors qu'aucun lot n'était planifié — seule la commande
`sync_memory --reindex` calculait les vecteurs.

Désormais : un bouton « Vectoriser maintenant » (la passe du COMPTE), un lot nocturne
(`memory-reindex-nightly`), une seule tâche (`common.reindex_memory`, file GPU, palier bas) —
jamais dans une requête (`WAMA_MEMORY §5bis`). Aucun modèle n'est chargé ici : l'embedder est
simulé.
"""
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from wama.common.models import EMBEDDING_DIMS, RagChunk

User = get_user_model()


def _chunk(user, text, ordinal=0):
    return RagChunk.objects.create(content=text, content_hash=f'h{ordinal}', source_kind='file',
                                   source_id='file:users/x/fiche.docx', ordinal=ordinal, user=user)


def _fake_embedder():
    """L'embedder simulé : disponible, résidence refusée, un vecteur nul par texte."""
    return mock.patch.multiple(
        'wama.common.memory.embed',
        embedder_available=mock.DEFAULT, residency_allowed=mock.DEFAULT,
        embed_batch=mock.DEFAULT, reserve=mock.DEFAULT, release=mock.DEFAULT,
        unload=mock.DEFAULT)


class ReindexOneAccountTest(TestCase):

    def setUp(self):
        self.me = User.objects.create_user('vec_me', password='x')
        self.other = User.objects.create_user('vec_other', password='x')
        _chunk(self.me, 'ma fiche', 0)
        _chunk(self.other, "la fiche d'autrui", 1)

    def _run(self, **kwargs):
        from wama.common.memory.store import reindex
        with _fake_embedder() as fakes:
            fakes['embedder_available'].return_value = True
            fakes['residency_allowed'].return_value = (False, 'test')
            fakes['embed_batch'].side_effect = lambda texts, **kw: [[0.0] * EMBEDDING_DIMS
                                                                    for _ in texts]
            return reindex(**kwargs)

    def test_the_accounts_pass_vectorises_only_its_own_rows(self):
        self._run(user=self.me)
        self.assertEqual(0, RagChunk.objects.filter(user=self.me, embedding__isnull=True).count())
        self.assertEqual(1, RagChunk.objects.filter(user=self.other, embedding__isnull=True).count(),
                         "a user's button must not spend the GPU on someone else's rows")

    def test_the_nightly_pass_vectorises_everything_waiting(self):
        self._run()
        self.assertFalse(RagChunk.objects.filter(embedding__isnull=True).exists())


class ReindexTaskTest(TestCase):

    def setUp(self):
        cache.delete('common.reindex_memory.lock')
        self.user = User.objects.create_user('vec_task', password='x')

    def test_the_task_passes_the_account_to_the_pass(self):
        from wama.common.tasks import reindex_memory_task
        with mock.patch('wama.common.memory.store.reindex', return_value={'traites': 1}) as run:
            reindex_memory_task(user_id=self.user.pk)
        self.assertEqual(self.user, run.call_args.kwargs['user'])
        with mock.patch('wama.common.memory.store.reindex', return_value={}) as run:
            reindex_memory_task()
        self.assertIsNone(run.call_args.kwargs['user'], 'the nightly batch takes everything')

    def test_a_pass_already_running_is_not_doubled(self):
        from wama.common.tasks import REINDEX_LOCK, reindex_memory_task
        cache.add(REINDEX_LOCK, 1, timeout=60)
        try:
            with mock.patch('wama.common.memory.store.reindex') as run:
                self.assertEqual({'skipped': 'en cours'}, reindex_memory_task(user_id=self.user.pk))
            run.assert_not_called()
        finally:
            cache.delete(REINDEX_LOCK)

    def test_the_lock_is_released_even_when_the_pass_fails(self):
        from wama.common.tasks import REINDEX_LOCK, reindex_memory_task
        with mock.patch('wama.common.memory.store.reindex', side_effect=RuntimeError('ollama')):
            with self.assertRaises(RuntimeError):
                reindex_memory_task()
        self.assertTrue(cache.add(REINDEX_LOCK, 1, timeout=1), 'the lock outlived its pass')
        cache.delete(REINDEX_LOCK)

    def test_the_task_waits_behind_user_work_on_the_gpu_queue(self):
        from wama.common.services.resource_governor import tier_for
        route = settings.CELERY_TASK_ROUTES['common.reindex_memory']
        self.assertEqual('gpu', route['queue'])
        self.assertEqual('basse', tier_for('_memory_reindex'))

    def test_the_task_takes_a_vector_of_another_model_as_missing(self):
        """Après une bascule d'embedder, ce sont le lot nocturne et le bouton qui finissent le
        réindex (2026-10-19, bge-m3 → qwen3-embedding)."""
        from wama.common.tasks import reindex_memory_task
        with mock.patch('wama.common.memory.store.reindex', return_value={}) as run:
            reindex_memory_task()
        self.assertTrue(run.call_args.kwargs['modeles_obsoletes'])


class EmbedderSwitchTest(TestCase):
    """La bascule bge-m3 → qwen3-embedding (2026-10-19) : deux espaces vectoriels ne se comparent
    jamais, un vecteur d'un autre modèle est un vecteur manquant, la requête porte son instruction
    et le modèle est appelé avec ce qui borne sa VRAM. Aucun modèle n'est chargé ici."""

    def setUp(self):
        from wama.common.memory.embed import EMBEDDING_MODEL
        self.me = User.objects.create_user('vec_switch', password='x')
        self.old = _chunk(self.me, 'vectorisé par l’ancien modèle', 0)
        self.new = _chunk(self.me, 'vectorisé par le modèle courant', 1)
        vec = [1.0] + [0.0] * (EMBEDDING_DIMS - 1)
        RagChunk.objects.filter(pk=self.old.pk).update(embedding=vec, embedding_model='bge-m3')
        RagChunk.objects.filter(pk=self.new.pk).update(embedding=vec, embedding_model=EMBEDDING_MODEL)
        self.vec = vec

    def test_vector_search_never_compares_two_spaces(self):
        from wama.common.memory.store import _by_vector
        found = [o.pk for _, o in _by_vector(RagChunk.objects.filter(user=self.me), self.vec)]
        self.assertEqual(found, [self.new.pk], "une ligne de l'ancien modèle n'est pas comparable")

    def test_a_vector_of_another_model_is_rebuilt_by_the_reindex(self):
        from wama.common.memory.embed import EMBEDDING_MODEL
        from wama.common.memory.store import reindex
        with _fake_embedder() as fakes:
            fakes['embedder_available'].return_value = True
            fakes['residency_allowed'].return_value = (False, 'test')
            fakes['embed_batch'].side_effect = lambda texts, **kw: [[0.0] * EMBEDDING_DIMS
                                                                    for _ in texts]
            summary = reindex(user=self.me, modeles_obsoletes=True)
        self.assertEqual(summary['traites'], 1, 'seule la ligne obsolète est refaite')
        self.old.refresh_from_db()
        self.assertEqual(self.old.embedding_model, EMBEDDING_MODEL)

    def test_the_counters_count_only_vectors_of_the_current_model(self):
        from wama.common.memory.index import list_rag
        row = next(d for d in list_rag(self.me) if d['source_id'] == 'file:users/x/fiche.docx')
        self.assertEqual((row['fragments'], row['vectorises']), (2, 1))

    def test_a_query_carries_its_instruction_and_a_document_does_not(self):
        from wama.common.memory import embed
        with mock.patch.object(embed, 'embed_batch', return_value=[[0.0] * EMBEDDING_DIMS]) as run:
            embed.embed_query('anonymisation')
            embed.embed_text('un fragment de document')
        self.assertEqual(run.call_args_list[0].args[0], [embed.QUERY_INSTRUCTION + 'anonymisation'])
        self.assertEqual(run.call_args_list[1].args[0], ['un fragment de document'])
        with mock.patch('wama.common.memory.embed.embed_query', return_value=None) as query:
            from wama.common.memory.store import recall
            recall('anonymisation', user=self.me)
        self.assertEqual(query.call_args.args[0], 'anonymisation', 'le rappel vectorise une REQUÊTE')

    def test_the_model_is_asked_for_the_column_size_and_a_bounded_window(self):
        """1024 dimensions demandées (la colonne `vector(1024)` reste) et une fenêtre de contexte
        bornée — sans elle, 9,3 Go de VRAM mesurés au lieu de 3,8."""
        from wama.common.memory import embed
        from wama.common.memory.index import CHUNK_SIZE
        client = mock.MagicMock()
        client.__enter__.return_value.post.return_value = mock.Mock(
            status_code=200, json=lambda: {'embeddings': [[0.0] * EMBEDDING_DIMS]})
        with mock.patch('httpx.Client', return_value=client):
            embed.embed_batch(['texte'])
        sent = client.__enter__.return_value.post.call_args.kwargs['json']
        self.assertEqual((sent['model'], sent['dimensions']), (embed.EMBEDDING_MODEL, EMBEDDING_DIMS))
        self.assertEqual(sent['options']['num_ctx'], embed.NUM_CTX)
        self.assertGreater(embed.NUM_CTX, CHUNK_SIZE, 'un fragment entier tient dans la fenêtre')
        self.assertTrue(embed.OWNER.endswith('#ollama:' + embed.EMBEDDING_MODEL),
                        'le gouverneur rattache la réservation à la ligne du catalogue')


class ReindexButtonTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('vec_button', password='x')

    def test_the_button_queues_the_accounts_pass_and_returns_to_the_page(self):
        self.client.force_login(self.user)
        with mock.patch('wama.common.tasks.reindex_memory_task.delay') as delay:
            response = self.client.post(reverse('common:rag_reindex'))
        delay.assert_called_once_with(user_id=self.user.pk)
        self.assertRedirects(response, reverse('common:rag'), fetch_redirect_response=False)

    def test_it_is_a_gesture_not_a_link(self):
        self.client.force_login(self.user)
        with mock.patch('wama.common.tasks.reindex_memory_task.delay') as delay:
            self.assertEqual(405, self.client.get(reverse('common:rag_reindex')).status_code)
        delay.assert_not_called()

    def test_a_visitor_cannot_spend_the_gpu(self):
        with mock.patch('wama.common.tasks.reindex_memory_task.delay') as delay:
            self.client.post(reverse('common:rag_reindex'))
        delay.assert_not_called()

    def test_the_page_says_when_and_offers_the_button_while_something_waits(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse('common:rag')), 'Vectoriser maintenant')
        _chunk(self.user, 'en attente')
        page = self.client.get(reverse('common:rag'))
        self.assertContains(page, 'Vectoriser maintenant')
        self.assertContains(page, 'action="%s"' % reverse('common:rag_reindex'))
        self.assertContains(page, 'faite chaque nuit (prochaine le')
        self.assertNotContains(page, "prochain lot d'indexation")


class NightlyReindexTest(TestCase):

    def test_the_nightly_batch_is_planned_and_shown_in_the_calendar(self):
        from wama.common.services.calendar import BEAT_WINDOWS, next_occurrence
        entry = settings.CELERY_BEAT_SCHEDULE['memory-reindex-nightly']
        self.assertEqual('common.reindex_memory', entry['task'])
        self.assertIn('memory-reindex-nightly', BEAT_WINDOWS)
        self.assertIsNotNone(next_occurrence('memory-reindex-nightly'))
        self.assertIsNone(next_occurrence('no-such-entry'))
