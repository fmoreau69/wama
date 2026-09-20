"""Chantier B1 — le gouverneur sait ce qui TOURNE, qui est OCCUPÉ, et fait libérer À TRAVERS les
process sur demande (2026-09-20).

POURQUOI. Décisions de Fabien (16/09, reformulées le 20/09) : une tâche qui ne tient pas attend
que les résidences se libèrent ; libérer TOUTE la carte n'intervient que sur accord explicite de
l'utilisateur ; les services se DÉCLARENT (occupé ? décharger ? recharger ?). Mesuré avant
d'écrire : le registre connaissait les MODÈLES résidents mais pas les TÂCHES en cours ; le
déchargement restait LOCAL au process (`unload_live_backends`) — « canal inter-process : conçu,
non implémenté » (ROADMAP :546).

Aucun GPU, aucun Redis : le faux Redis des tests du registre, le temps est une variable.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.services import resource_governor as gov
from wama.common.tests_vram_ledger import _FauxRedis


class _WithRegistry(SimpleTestCase):

    def setUp(self):
        self.redis = _FauxRedis()
        self.t = 2_000_000.0
        for kw in ({'_redis': mock.Mock(return_value=self.redis)},
                   {'_now': mock.Mock(side_effect=lambda: self.t)}):
            p = mock.patch.multiple(gov, **kw)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(gov, 'tenant_id', return_value='4242')
        p.start()
        self.addCleanup(p.stop)


class RunningTasksTest(_WithRegistry):

    def test_a_task_is_visible_while_it_runs_and_gone_when_finished(self):
        token = gov.task_started('imager', 7, 21.0)
        tasks = gov.running_tasks()
        self.assertEqual([(t['app'], t['item'], t['gb'], t['tenant']) for t in tasks],
                         [('imager', 7, 21.0, '4242')])
        gov.task_finished(token)
        self.assertEqual(gov.running_tasks(), [])

    def test_a_task_line_expires_with_its_own_duration_limit(self):
        """Un worker mort ne laisse pas une tâche fantôme : la ligne meurt avec le traitement."""
        gov.task_started('imager', 1, 10.0, max_s=600)
        gov.task_started('composer', 2, 5.0)              # défaut : TASK_DEFAULT_MAX_S
        self.t += 601
        self.assertEqual([t['app'] for t in gov.running_tasks()], ['composer'])
        self.t += gov.TASK_DEFAULT_MAX_S
        self.assertEqual(gov.running_tasks(), [])


class BusyTenantsTest(_WithRegistry):

    def test_a_declared_busy_tenant_stays_busy_for_the_window_only(self):
        gov.mark_busy('tts')
        self.assertIn('tts', gov.busy_tenants())
        self.t += gov.BUSY_WINDOW_S
        self.assertNotIn('tts', gov.busy_tenants())
        gov.mark_busy('tts')
        gov.clear_busy('tts')
        self.assertNotIn('tts', gov.busy_tenants())

    def test_a_resident_that_just_served_makes_its_tenant_busy(self):
        """`mark_used` (chaque `process()` d'un backend) suffit : le tenant n'a rien à déclarer."""
        gov.reserve_vram('wama.common.backends.x.XBackend:777#@kokoro', 0.5)
        gov.mark_used('wama.common.backends.x.XBackend:777#@kokoro')
        self.assertIn('777', gov.busy_tenants())
        self.t += gov.BUSY_WINDOW_S
        self.assertEqual(gov.busy_tenants(), set())

    def test_gpu_is_busy_reads_tasks_and_tenants_but_not_the_asker(self):
        self.assertFalse(gov.gpu_is_busy())
        gov.mark_busy('4242')                              # moi-même
        self.assertFalse(gov.gpu_is_busy(exclude_tenant='4242'))
        self.assertTrue(gov.gpu_is_busy())
        gov.clear_busy('4242')
        gov.task_started('reader', 3, 2.0)                 # ma propre tâche
        self.assertFalse(gov.gpu_is_busy(exclude_tenant='4242'))
        with mock.patch.object(gov, 'tenant_id', return_value='9'):
            gov.task_started('imager', 4, 20.0)
        self.assertTrue(gov.gpu_is_busy(exclude_tenant='4242'))

    def test_the_tenant_of_an_owner_is_its_pid_and_ollama_has_none(self):
        self.assertEqual(gov.tenant_of_owner('wama.x.YBackend:31337#@m'), '31337')
        self.assertEqual(gov.tenant_of_owner('composer.audiocpp:88'), '88')
        self.assertIsNone(gov.tenant_of_owner(gov.ollama_host_owner('gemma')))


class ExplicitGrantTest(_WithRegistry):

    def test_nothing_is_granted_until_the_user_says_so_and_it_expires(self):
        self.assertFalse(gov.release_granted('imager', 5))
        gov.grant_release('imager', 5, user_id=1)
        self.assertTrue(gov.release_granted('imager', 5))
        self.assertFalse(gov.release_granted('imager', 6))
        self.t += gov.GRANT_TTL_S
        self.assertFalse(gov.release_granted('imager', 5))
        gov.grant_release('imager', 5)
        gov.revoke_grant('imager', 5)
        self.assertFalse(gov.release_granted('imager', 5))


class FitsAloneTest(SimpleTestCase):

    def test_fits_alone_compares_to_the_whole_card_and_says_nothing_without_a_gpu(self):
        with mock.patch.object(gov, 'total_vram_gb', return_value=24.0):
            self.assertTrue(gov.fits_alone(21.0))
            self.assertFalse(gov.fits_alone(32.5))
        with mock.patch.object(gov, 'total_vram_gb', return_value=0.0):
            self.assertIsNone(gov.fits_alone(1.0))


class _FakeTenant:
    """Un tenant qui compte ce qu'on lui demande."""

    def __init__(self, name, *, resident=2, busy=False):
        self.resident, self.busy, self.restored = resident, busy, 0
        self.tenant = gov.Tenant(name, unload=self._unload, restore=self._restore,
                                 is_busy=lambda: self.busy)

    def _unload(self):
        n, self.resident = self.resident, 0
        return n

    def _restore(self):
        self.restored += 1


class ReleaseChannelTest(_WithRegistry):

    def _as(self, pid):
        return mock.patch.object(gov, 'tenant_id', return_value=pid)

    def test_a_request_is_served_by_a_tenant_in_another_process_and_acknowledged(self):
        request_id = gov.request_release(20.0, requester='4242', reason='imager #7')
        self.assertIn(request_id, gov.pending_release_requests())
        holder = _FakeTenant('worker-studio')
        with self._as('5000'):
            freed = gov.serve_release_requests(holder.tenant)
        self.assertEqual((freed, holder.resident), (2, 0))
        self.assertEqual(gov.release_acks(request_id)['5000']['freed'], 2)
        with self._as('5000'):                        # un second passage ne refait rien
            self.assertEqual(gov.serve_release_requests(holder.tenant), 0)

    def test_a_busy_tenant_says_so_and_keeps_its_models(self):
        request_id = gov.request_release(20.0, requester='4242')
        holder = _FakeTenant('tts', busy=True)
        with self._as('6000'):
            self.assertEqual(gov.serve_release_requests(holder.tenant), 0)
        self.assertEqual(holder.resident, 2)
        self.assertTrue(gov.release_acks(request_id)['6000']['busy'])

    def test_the_requester_never_unloads_itself_for_its_own_request(self):
        gov.request_release(20.0, requester='4242')
        me = _FakeTenant('gpu-worker')
        self.assertEqual(gov.serve_release_requests(me.tenant), 0)
        self.assertEqual(me.resident, 2)

    def test_restore_happens_once_after_the_request_is_closed(self):
        request_id = gov.request_release(20.0, requester='4242')
        holder = _FakeTenant('tts')
        with self._as('6000'):
            gov.serve_release_requests(holder.tenant)
            self.assertEqual(holder.restored, 0)      # la demande vit encore
            gov.close_release_request(request_id)
            gov.serve_release_requests(holder.tenant)
            gov.serve_release_requests(holder.tenant)
        self.assertEqual(holder.restored, 1)
        self.assertEqual(gov.release_acks(request_id), {})

    def test_a_tenant_that_freed_nothing_does_not_restore(self):
        request_id = gov.request_release(20.0, requester='4242')
        holder = _FakeTenant('empty', resident=0)
        with self._as('6000'):
            gov.serve_release_requests(holder.tenant)
            gov.close_release_request(request_id)
            gov.serve_release_requests(holder.tenant)
        self.assertEqual(holder.restored, 0)

    def test_a_request_whose_requester_died_expires_with_its_acks(self):
        request_id = gov.request_release(20.0, requester='4242')
        gov.acknowledge_release(request_id, '1', freed=1)
        self.t += gov.REQUEST_TTL_S + 1
        self.assertEqual(gov.pending_release_requests(), {})
        self.assertEqual(gov.release_acks(request_id), {})

    def test_a_tenant_whose_probe_fails_is_treated_as_busy(self):
        def boom():
            raise RuntimeError('probe')
        t = gov.Tenant('x', unload=lambda: 1, is_busy=boom)
        self.assertTrue(t.is_busy())

    def test_the_contract_tenant_unloads_through_the_existing_brick(self):
        """`MemoryManager.release_vram` — contrat ET hors-contrat (`_VRAM_UNLOADERS`), pas seulement
        `unload_live_backends` (1re version, revérifiée le 20/09)."""
        with mock.patch('wama.model_manager.services.memory_manager.MemoryManager.release_vram',
                        return_value=3) as m:
            self.assertEqual(gov.contract_tenant('gpu').unload(), 3)
        m.assert_called_once_with()


class WorkerRegistersItselfTest(SimpleTestCase):

    def test_the_celery_worker_hook_starts_the_release_listener_as_a_contract_tenant(self):
        from wama.celery import _wama_configure_worker_resources
        with mock.patch.object(gov, 'configure_cuda_process', return_value=True), \
                mock.patch('wama.common.backends.base.start_reservation_heartbeat', return_value=True), \
                mock.patch.object(gov, 'start_release_listener', return_value=True) as start:
            _wama_configure_worker_resources()
        start.assert_called_once()
        tenant = start.call_args.args[0]
        self.assertIsInstance(tenant, gov.Tenant)
        self.assertTrue(tenant.name.startswith('celery:'))
        self.assertFalse(tenant.is_busy())


class ObtainVramTest(_WithRegistry):

    def test_obtaining_waits_for_the_probe_not_for_the_acks_and_closes_the_request(self):
        with mock.patch.object(gov, 'effective_free_gb', side_effect=[1.0, 1.0, 30.0]), \
                mock.patch('time.sleep'):
            ok, libre = gov.obtain_vram(20.0, requester='4242', timeout_s=60, poll_s=0)
        self.assertEqual((ok, libre), (True, 30.0))
        self.assertEqual(gov.pending_release_requests(), {})

    def test_a_timeout_is_said_with_who_stayed_busy_and_the_request_is_closed(self):
        lines = []
        with mock.patch.object(gov, 'effective_free_gb', return_value=2.0), \
                mock.patch.object(gov, 'request_release', return_value='req1'), \
                mock.patch.object(gov, 'release_acks',
                                  return_value={'6000': {'busy': True}, '5000': {'freed': 1}}):
            ok, libre = gov.obtain_vram(20.0, requester='4242', timeout_s=0,
                                        console=lines.append)
        self.assertEqual((ok, libre), (False, 2.0))
        self.assertIn("occupés : ['6000']", lines[0])
        self.assertEqual(gov.pending_release_requests(), {})
