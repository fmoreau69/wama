"""Réconciliation des tâches RUNNING orphelines — une tâche RÉUSSIE n'est pas une tâche morte.

⚠⚠ POURQUOI CE FICHIER (2026-09-07). Le scénario nocturne `<app>.batch_processing`, écrit la
veille, a trouvé un défaut RÉEL et visible par l'utilisateur : un lot de deux conversions de
0,3 s partait en « Traitement interrompu (worker arrêté) » alors que le journal du worker
disait « ✓ Terminé » pour les DEUX. Deux cards ROUGES, et les fichiers convertis à côté.

La cause tient en une ligne : `is_task_dead()` répond True pour l'état Celery **SUCCESS** — son
nom dit « terminal », pas « morte », et sa docstring PRÉVIENT qu'il demande « un délai de grâce
côté appelant ». `reconcile_orphaned_running` l'appelait sans aucun délai et basculait l'item en
ÉCHEC.

La course : la tâche publie son état au broker ET écrit le statut de son item — deux écritures,
deux instants. Un rechargement de page tombé entre les deux (et « Démarrer tout » RECHARGE, par
contrat de `queue-actions.js`) lisait l'item encore RUNNING et la tâche déjà terminée, puis
ÉCRASAIT le succès en échec.

Ces tests fixent les deux gardes. Sans eux, la correction se reperdrait au premier refactor —
c'est le genre de défaut qu'on ne retrouve qu'en le cherchant.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.utils import process_control


class TacheReussieTest(TestCase):
    """L'état SUCCESS ne doit JAMAIS produire un échec."""

    def setUp(self):
        self.user = User.objects.create_user('reconcile_test', 'r@test.local', 'x')
        from wama.converter.models import ConversionBatch, ConversionJob
        self.lot = ConversionBatch.objects.create(user=self.user, total=1, media_type='image')
        self.job = ConversionJob.objects.create(
            user=self.user, media_type='image', batch=self.lot, batch_row_index=0,
            status='RUNNING', task_id='tache-qui-a-reussi')

    def _reconcilier(self):
        from wama.converter.models import ConversionJob
        return process_control.reconcile_orphaned_running(
            [self.job], snapshot={'workers': (), 'task_ids': ()},
            error_field='error_message'), ConversionJob

    def test_une_tache_en_SUCCESS_ne_bascule_PAS_l_item_en_echec(self):
        """Le défaut mesuré : le travail a été FAIT, l'item ne doit pas devenir rouge."""
        with patch.object(process_control, 'is_task_dead', return_value=True), \
             patch.object(process_control, '_tache_reussie', return_value=True):
            n, Modele = self._reconcilier()
        self.assertEqual(0, n, "une tâche réussie a été comptée comme morte")
        self.assertEqual('RUNNING', Modele.objects.get(pk=self.job.pk).status,
                         "l'item a été basculé en échec alors que sa tâche avait RÉUSSI")

    def test_une_tache_en_ECHEC_bascule_bien_l_item(self):
        """La garde ne doit pas neutraliser le mécanisme : un vrai mort reste réconcilié."""
        with patch.object(process_control, 'is_task_dead', return_value=True), \
             patch.object(process_control, '_tache_reussie', return_value=False):
            n, Modele = self._reconcilier()
        self.assertEqual(1, n)
        frais = Modele.objects.get(pk=self.job.pk)
        self.assertEqual('FAILURE', frais.status)
        self.assertIn('interrompu', (frais.error_message or '').lower())

    def test_un_statut_qui_a_bouge_depuis_la_photo_n_est_PAS_ecrase(self):
        """La seconde garde : la tâche a fini son travail entre la lecture et l'écriture.

        C'est la fenêtre exacte qui laissait un FAILURE écraser un SUCCESS écrit une fraction
        de seconde plus tôt. L'objet en mémoire dit RUNNING, la BASE dit SUCCESS — c'est la
        base qui a raison.
        """
        from wama.converter.models import ConversionJob
        ConversionJob.objects.filter(pk=self.job.pk).update(status='SUCCESS')
        with patch.object(process_control, 'is_task_dead', return_value=True), \
             patch.object(process_control, '_tache_reussie', return_value=False):
            n, Modele = self._reconcilier()
        self.assertEqual(0, n)
        self.assertEqual('SUCCESS', Modele.objects.get(pk=self.job.pk).status,
                         "un succès déjà écrit en base a été écrasé par la réconciliation")

    def test_un_item_sans_task_id_est_ignore(self):
        """Contrat d'origine, préservé : peut-être tout juste démarré (cf. begin_processing)."""
        from wama.converter.models import ConversionJob
        self.job.task_id = ''
        self.job.save(update_fields=['task_id'])
        with patch.object(process_control, 'is_task_dead', return_value=True):
            n, Modele = self._reconcilier()
        self.assertEqual(0, n)
        self.assertEqual('RUNNING', Modele.objects.get(pk=self.job.pk).status)


class _FakeResult:
    """`AsyncResult` stand-in whose successive `.state` reads follow a script."""
    states = []

    def __init__(self, *_a, **_k):
        pass

    @property
    def state(self):
        return _FakeResult.states.pop(0) if len(_FakeResult.states) > 1 else _FakeResult.states[0]


class _FakeClient:
    def __init__(self, lists=None, unacked=None, pidbox=()):
        self.lists, self.unacked, self.pidbox = lists or {}, unacked or {}, pidbox

    def smembers(self, _key):
        return {m.encode() for m in self.pidbox}

    def scan_iter(self, _type=None, count=None):
        return iter(self.lists)

    def llen(self, key):
        return len(self.lists[key])

    def lrange(self, key, *_):
        return self.lists[key]

    def hscan_iter(self, _key, count=None):
        return iter(self.unacked.items())


class _FakeConn:
    def release(self):
        pass


class _FakeChannel:
    sep, unacked_key = ':', 'unacked'

    def __init__(self, client):
        self.client = client


NODES = ('::gpu@host.celery.pidbox', '::default@host.celery.pidbox',
         '\x06\x16\x06\x16celery@host.celery.pidbox')   # stale binding, old separator
ALL_ANSWERED = {'workers': {'gpu@host', 'default@host'}, 'task_ids': set()}


class TaskLostAfterHostCrashTest(TestCase):
    """`is_task_lost` — the host crashed, Redis came back from its last snapshot, the task's
    `STARTED` meta is gone (state falls back to PENDING): transcription #525, 2026-09-21."""

    def _lost(self, client, states=('PENDING',), snapshot=ALL_ANSWERED):
        _FakeResult.states = list(states)
        with patch('celery.result.AsyncResult', _FakeResult), \
             patch.object(process_control, '_broker_channel',
                          return_value=(_FakeConn(), _FakeChannel(client))):
            return process_control.is_task_lost('tid-525', snapshot)

    def test_a_task_found_nowhere_while_every_worker_answered_is_lost(self):
        self.assertTrue(self._lost(_FakeClient(pidbox=NODES)))

    def test_a_queued_task_is_not_lost(self):
        """Queued, not prefetched: PENDING too — the broker list gives it away."""
        client = _FakeClient(pidbox=NODES, lists={b'gpu:3': [b'{"id": "tid-525"}']})
        self.assertFalse(self._lost(client))

    def test_a_reserved_task_in_unacked_is_not_lost(self):
        client = _FakeClient(pidbox=NODES, unacked={b'tag': b'[{"id": "tid-525"}]'})
        self.assertFalse(self._lost(client))

    def test_a_silent_worker_forbids_any_conclusion(self):
        """The 2026-07-25 inverted signal: a busy solo worker does not answer."""
        silent_gpu = {'workers': {'default@host'}, 'task_ids': set()}
        self.assertFalse(self._lost(_FakeClient(pidbox=NODES), snapshot=silent_gpu))

    def test_a_task_picked_up_during_the_scan_is_not_lost(self):
        """Second state read: the worker started it meanwhile."""
        self.assertFalse(self._lost(_FakeClient(pidbox=NODES), states=('PENDING', 'STARTED')))

    def test_a_started_task_is_left_to_is_task_orphaned(self):
        self.assertFalse(self._lost(_FakeClient(pidbox=NODES), states=('STARTED',)))

    def test_an_unreadable_broker_proves_nothing(self):
        with patch.object(process_control, '_broker_holds', return_value=None):
            self.assertFalse(self._lost(_FakeClient(pidbox=NODES)))

    def test_known_nodes_ignore_bindings_written_under_another_separator(self):
        nodes = process_control._known_worker_nodes(_FakeClient(pidbox=NODES), ':')
        self.assertEqual({'gpu@host', 'default@host'}, nodes)


class _StartedMeta:
    """`AsyncResult` stand-in: a task STARTED by (`pid`, `hostname`)."""
    meta = {}
    state = 'STARTED'

    def __init__(self, task_id, app=None):
        self.task_id = task_id

    @property
    def result(self):
        return dict(self.meta)


class DeadWorkerProcessTest(TestCase):
    """A restarted worker settles its dead predecessor's tasks (2026-09-24).

    The proof is POSITIVE: the task STARTED on this worker name, in a process that no longer
    exists on this machine. No `inspect()` involved — the solo gpu worker never answers while
    busy (the inverted signal of 25/07)."""

    NODE = 'gpu@test-host'

    def setUp(self):
        self.user = User.objects.create_user('dead_worker_test', 'd@test.local', 'x')
        from wama.converter.models import ConversionBatch, ConversionJob
        lot = ConversionBatch.objects.create(user=self.user, total=1, media_type='image')
        self.job = ConversionJob.objects.create(
            user=self.user, media_type='image', batch=lot, batch_row_index=0,
            status='RUNNING', task_id='task-on-a-dead-process')

    def _settle(self, pid, hostname=NODE, alive=False):
        _StartedMeta.meta = {'pid': pid, 'hostname': hostname}
        with patch('celery.result.AsyncResult', _StartedMeta),              patch.object(process_control, '_pid_alive', return_value=alive),              patch.object(process_control, '_tache_reussie', return_value=False):
            return process_control.reconcile_dead_worker_tasks(self.NODE)

    def _status(self):
        from wama.converter.models import ConversionJob
        return ConversionJob.objects.get(pk=self.job.pk)

    def test_a_task_started_by_a_dead_process_of_this_worker_fails_relaunchably(self):
        done = self._settle(pid=424242)
        self.assertIn(('converter', 'ConversionJob', self.job.pk), done)
        fresh = self._status()
        self.assertEqual('FAILURE', fresh.status)
        self.assertIn('worker', (fresh.error_message or '').lower())

    def test_a_live_process_is_never_settled(self):
        self.assertEqual([], self._settle(pid=424242, alive=True))
        self.assertEqual('RUNNING', self._status().status)

    def test_another_worker_name_is_not_this_workers_business(self):
        self.assertEqual([], self._settle(pid=424242, hostname='default@test-host'))
        self.assertEqual('RUNNING', self._status().status)

    def test_settling_twice_changes_nothing_the_second_time(self):
        self.assertEqual(1, len(self._settle(pid=424242)))
        self.assertEqual([], self._settle(pid=424242))

    def test_every_wama_work_model_is_swept_by_its_shape(self):
        names = {m.__name__ for m in process_control.work_models()}
        self.assertIn('ConversionJob', names)
        self.assertGreaterEqual(len(names), 10, f'only {sorted(names)} — sweep too narrow')
