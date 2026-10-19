"""Un premier lancement qui va TÉLÉCHARGER les poids le DIT à l'utilisateur.

POURQUOI (2026-09-08, constat de Fabien) : « à la première utilisation les poids sont
automatiquement téléchargés ; il faudrait vérifier si un message prévient l'utilisateur avant le
lancement de la tâche, sur la card, dans le cycle de vie ». Vérifié : le téléchargement existait
(37 appels `from_pretrained`/`snapshot_download`), **l'annonce non** — ni squelette, ni backend,
ni card. Quatre modèles catalogués sont dans ce cas (mochi-1-preview, qwen-image-edit,
flux2-klein-4b, musicgen-melody) : les lancer donnait une tâche figée, sans un mot, le temps de
récupérer des dizaines de Go.

⚠ Ce module SÈME ses cas : le catalogue de la base de TEST est vide, et un invariant qui
l'interroge mesurerait ce vide (défaut vécu deux fois cette session). L'état réel se lit avec
`check_backend_links` / la cartographie.
"""
from django.test import TestCase

from wama.common.utils.model_readiness import SIZE_MENTION_THRESHOLD_GB, warn_if_weights_missing


class AnnonceTelechargementTest(TestCase):

    def _semer(self, cle, *, telecharge, disk_gb=0.0, nom=''):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(
            model_key=cle, name=nom or cle, model_type='image',
            source=cle.split(':')[0], is_downloaded=telecharge, disk_gb=disk_gb)

    def _capter(self, cle):
        vues = []
        dit = warn_if_weights_missing(cle, console=vues.append)
        return dit, vues

    def test_poids_absents__on_previent(self):
        self._semer('imager:jamais-utilise', telecharge=False, nom='Mochi')
        dit, vues = self._capter('imager:jamais-utilise')
        self.assertTrue(dit)
        self.assertEqual(len(vues), 1)
        self.assertIn('Mochi', vues[0])
        self.assertIn('téléchargement', vues[0].lower())

    def test_poids_presents__on_se_TAIT(self):
        """Le contre-exemple qui compte : un avertissement permanent n'avertit plus de rien.
        C'est le défaut qu'on retire de l'imager vidéo (message en dur à chaque lancement)."""
        self._semer('imager:deja-la', telecharge=True)
        dit, vues = self._capter('imager:deja-la')
        self.assertFalse(dit)
        self.assertEqual(vues, [])

    def test_modele_inconnu_du_catalogue__on_ne_dit_rien(self):
        """On ne parle que de ce qu'on SAIT : pas de ligne, pas d'annonce."""
        dit, vues = self._capter('imager:jamais-catalogue')
        self.assertFalse(dit)
        self.assertEqual(vues, [])

    def test_la_taille_n_est_annoncee_que_si_elle_est_CONNUE(self):
        """`disk_gb` vaut 0 tant qu'un modèle n'a jamais été téléchargé — on n'invente pas un
        volume (l'ancien message en dur annonçait « ~5-10GB » pour tout modèle vidéo)."""
        self._semer('imager:sans-taille', telecharge=False, disk_gb=0.0)
        _, sans = self._capter('imager:sans-taille')
        self.assertNotIn('~', sans[0])

        self._semer('imager:avec-taille', telecharge=False, disk_gb=18.0)
        _, avec = self._capter('imager:avec-taille')
        self.assertIn('~18 Go', avec[0])

    def test_une_taille_negligeable_n_est_pas_annoncee(self):
        self._semer('imager:minuscule', telecharge=False, disk_gb=SIZE_MENTION_THRESHOLD_GB / 2)
        _, vues = self._capter('imager:minuscule')
        self.assertNotIn('~', vues[0])

    def test_une_console_qui_leve_ne_casse_JAMAIS_la_tache(self):
        """Prévenir est un confort, pas une condition — la règle de toute la couche console."""
        self._semer('imager:console-cassee', telecharge=False)

        def _explose(_):
            raise RuntimeError('console indisponible')

        self.assertTrue(warn_if_weights_missing('imager:console-cassee', console=_explose))

    def test_sans_console_on_ne_leve_pas(self):
        self._semer('imager:sans-console', telecharge=False)
        self.assertTrue(warn_if_weights_missing('imager:sans-console'))

    def test_cle_vide_ne_leve_pas(self):
        self.assertFalse(warn_if_weights_missing(''))
        self.assertFalse(warn_if_weights_missing(None))


class EnsureInstalledTest(TestCase):
    """2026-10-16, Fabien : a model needed at task time is not a drift — an INCOMPLETE install is.
    The route installs it, the user is told, the task waits (giving its worker back) ; a refusal or
    a failed install fails the task SAYING so — never a download beside the route."""

    KEY = 'imager:not-yet-installed'

    def setUp(self):
        from unittest import mock
        from wama.model_manager.models import AIModel
        self.row = AIModel.objects.create(model_key=self.KEY, name='Mochi', model_type='image',
                                          source='imager', is_downloaded=False, disk_gb=18.0)
        self.spec = mock.patch('wama.model_manager.services.model_installer.spec_for_catalog_row',
                               return_value={'kind': 'files'})
        self.spec.start()
        self.addCleanup(self.spec.stop)
        self.last = mock.patch('wama.common.utils.model_readiness._last_install', return_value={})
        self.last_install = self.last.start()
        self.addCleanup(self.last.stop)

    def _ensure(self, answer, **kw):
        from unittest import mock
        from wama.common.utils.model_readiness import ensure_installed
        said = []
        with mock.patch('wama.model_manager.services.model_installer.request_install',
                        return_value=answer) as install:
            try:
                return ensure_installed(self.KEY, console=said.append, **kw), said, install
            except Exception as exc:
                return exc, said, install

    def test_a_missing_model_is_installed_by_the_route_and_the_task_waits(self):
        from wama.common.utils.task_skeleton import ServiceNotReady
        out, said, install = self._ensure({'ok': True, 'started': True})
        self.assertIsInstance(out, ServiceNotReady)
        self.assertEqual(('task',), (install.call_args.kwargs['via'],))
        self.assertEqual(1, len(said))
        self.assertIn('~18 Go', said[0])
        self.assertIn('attend', said[0])

    def test_back_from_a_wait_it_keeps_waiting_without_saying_it_again(self):
        from wama.common.utils.task_skeleton import ServiceNotReady
        out, said, _install = self._ensure({'ok': True, 'already_running': True}, redelivered=True)
        self.assertIsInstance(out, ServiceNotReady)
        self.assertEqual([], said)

    def test_a_failed_install_is_said_instead_of_relaunched_in_a_loop(self):
        from wama.common.utils.model_readiness import ModelInstallRefused
        self.last_install.return_value = {'state': 'FAILURE', 'error': 'HTTP 401'}
        out, _said, install = self._ensure({'ok': True}, redelivered=True)
        self.assertIsInstance(out, ModelInstallRefused)
        self.assertIn('HTTP 401', str(out))
        install.assert_not_called()

    def test_a_new_launch_retries_an_install_that_failed_before(self):
        from wama.common.utils.task_skeleton import ServiceNotReady
        self.last_install.return_value = {'state': 'FAILURE', 'error': 'disque plein'}
        out, _said, install = self._ensure({'ok': True, 'started': True})
        self.assertIsInstance(out, ServiceNotReady)
        install.assert_called_once()

    def test_a_refusal_fails_the_task_saying_why(self):
        from wama.common.utils.model_readiness import ModelInstallRefused
        out, _said, _install = self._ensure({'ok': False, 'reason': 'insufficient_storage',
                                             'blocked': {'message': '2 Go libres'}})
        self.assertIsInstance(out, ModelInstallRefused)
        self.assertIn('2 Go libres', str(out))

    def test_without_a_route_location_the_old_announcement_is_kept(self):
        from unittest import mock
        with mock.patch('wama.model_manager.services.model_installer.spec_for_catalog_row',
                        return_value=None):
            out, said, install = self._ensure({'ok': True})
        self.assertIs(True, out)
        self.assertIn('téléchargement', said[0].lower())
        install.assert_not_called()

    def test_an_installed_or_unknown_model_needs_nothing(self):
        type(self.row).objects.filter(pk=self.row.pk).update(is_downloaded=True)
        out, said, install = self._ensure({'ok': True})
        self.assertIs(True, out)
        install.assert_not_called()
        from wama.common.utils.model_readiness import ensure_installed
        self.assertIs(True, ensure_installed('imager:never-catalogued'))
        self.assertIs(True, ensure_installed(''))

    def test_a_synchronous_caller_waits_for_the_end_of_the_install(self):
        from unittest import mock
        from wama.common.utils.model_readiness import install_and_wait

        def finished(_seconds):
            type(self.row).objects.filter(pk=self.row.pk).update(is_downloaded=True)

        with mock.patch('wama.model_manager.services.model_installer.request_install',
                        return_value={'ok': True, 'started': True}), \
                mock.patch('time.sleep', side_effect=finished):
            self.assertTrue(install_and_wait(self.KEY, poll_s=0))


class AnAdapterBringsItsBackboneTest(TestCase):
    """2026-10-19 : a LoRA does not run alone — the logo LoRA loads FLUX.1-dev under it. Asking the
    route for the adapter asks for its BACKBONE too (`memory_manager.backbone_row`, the resolution
    the footprint and the uninstall already use), the backbone first ; before, an absent backbone
    was pulled by the backend at load, beside the catalogue."""

    def setUp(self):
        from unittest import mock
        from wama.model_manager.models import AIModel
        self.base = AIModel.objects.create(model_key='imager:test-base', name='Base', hf_id='Org/Base',
                                           model_type='image', source='imager', is_downloaded=False)
        self.lora = AIModel.objects.create(
            model_key='imager:test-lora', name='Lora', hf_id='Org/Lora', model_type='image',
            source='imager', is_downloaded=True,
            extra_info={'base_model': 'Org/Base', 'model_type': 'lora'})
        for target, value in (('wama.model_manager.services.model_installer.spec_for_catalog_row',
                               {'kind': 'hf'}),
                              ('wama.common.utils.model_readiness._last_install', {})):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _ensure(self, key):
        from unittest import mock
        from wama.common.utils.model_readiness import ensure_installed
        from wama.common.utils.task_skeleton import ServiceNotReady
        with mock.patch('wama.model_manager.services.model_installer.request_install',
                        return_value={'ok': True, 'started': True}) as install:
            try:
                ensure_installed(key)
                waited = False
            except ServiceNotReady:
                waited = True
        return waited, [c.args[0] for c in install.call_args_list]

    def test_an_installed_adapter_on_an_absent_backbone_waits_for_the_backbone(self):
        self.assertEqual((True, ['imager:test-base']), self._ensure('imager:test-lora'))

    def test_both_absent_the_backbone_is_asked_first(self):
        type(self.lora).objects.filter(pk=self.lora.pk).update(is_downloaded=False)
        self.assertEqual((True, ['imager:test-base']), self._ensure('imager:test-lora'))

    def test_the_backbone_installed_only_the_adapter_is_asked(self):
        type(self.base).objects.filter(pk=self.base.pk).update(is_downloaded=True)
        type(self.lora).objects.filter(pk=self.lora.pk).update(is_downloaded=False)
        self.assertEqual((True, ['imager:test-lora']), self._ensure('imager:test-lora'))

    def test_a_base_model_does_not_ask_for_itself(self):
        """`flux-1-dev` declares `base_model` = its OWN hf_id : not an adapter."""
        type(self.base).objects.filter(pk=self.base.pk).update(
            is_downloaded=True, extra_info={'base_model': 'Org/Base', 'model_type': 'base'})
        self.assertEqual((False, []), self._ensure('imager:test-base'))

    def test_a_synchronous_caller_waits_for_both(self):
        from unittest import mock
        from wama.common.utils.model_readiness import install_and_wait
        type(self.lora).objects.filter(pk=self.lora.pk).update(is_downloaded=False)
        installed = []

        def install(key, **_kw):
            installed.append(key)
            type(self.base).objects.filter(model_key=key).update(is_downloaded=True)
            return {'ok': True, 'started': True}
        with mock.patch('wama.model_manager.services.model_installer.request_install',
                        side_effect=install), mock.patch('time.sleep'):
            self.assertTrue(install_and_wait('imager:test-lora', poll_s=0))
        self.assertEqual(['imager:test-base', 'imager:test-lora'], installed)


class TheSkeletonInstallsTheCardModelTest(TestCase):
    """The skeleton calls the brick INSIDE its main `try` : a wait re-delivers the task, a refusal
    fails the card with its reason (seen through the composer, a skeleton app)."""

    def setUp(self):
        import tempfile
        import shutil
        self.tmp = tempfile.mkdtemp()
        media = self.settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user('skeleton_install', password='x')

    def _run(self, effect):
        from unittest import mock
        from wama.composer import tasks
        from wama.composer.models import ComposerGeneration
        from wama.composer.tests_task import _celery_task
        gen = ComposerGeneration.objects.create(user=self.user, prompt='rain',
                                                model='composer:musicgen-small', status='RUNNING')
        task = _celery_task()
        task.retry = mock.MagicMock(side_effect=RuntimeError('re-delivered'))
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.utils.model_readiness.ensure_installed',
                           side_effect=effect) as ensure:
            try:
                tasks.compose_task.run.__func__(task, gen.pk, None)
            except RuntimeError as exc:
                self.assertEqual('re-delivered', str(exc))
        return ComposerGeneration.objects.get(pk=gen.pk), task, ensure

    def test_a_refusal_fails_the_card_with_its_reason(self):
        from wama.common.utils.model_readiness import ModelInstallRefused
        gen, _task, ensure = self._run(ModelInstallRefused("« X » n'est pas installé : disque plein"))
        self.assertEqual('composer:musicgen-small', ensure.call_args.args[0])
        self.assertEqual('FAILURE', gen.status)
        self.assertIn('disque plein', gen.error_message)

    def test_a_wait_redelivers_the_task_and_the_card_says_it_waits(self):
        from wama.common.utils.task_skeleton import ServiceNotReady
        gen, task, _ensure = self._run(ServiceNotReady('Installation de « X » en cours',
                                                       countdown=30, max_attempts=720))
        self.assertEqual({'countdown': 30, 'max_retries': 720}, task.retry.call_args.kwargs)
        self.assertEqual('RUNNING', gen.status)
        self.assertIn('Installation', gen.error_message)


class RedeliverLaterTest(TestCase):
    """Outside the skeleton (a studio node, a cam_analyzer analysis) the same policy : re-delivered
    after the countdown, and an exhausted wait fails SAYING WHY — never Celery's « Can't retry »."""

    def _task(self, effect):
        from unittest import mock
        task = mock.MagicMock()
        task.retry.side_effect = effect
        return task

    def test_the_task_is_redelivered_after_the_countdown(self):
        from wama.common.utils.task_skeleton import ServiceNotReady, redeliver_later
        task = self._task(RuntimeError('re-delivered'))
        with self.assertRaisesMessage(RuntimeError, 're-delivered'):
            redeliver_later(task, ServiceNotReady('installing', countdown=30, max_attempts=720))
        self.assertEqual({'countdown': 30, 'max_retries': 720}, task.retry.call_args.kwargs)

    def test_an_exhausted_wait_says_its_reason(self):
        from celery.exceptions import MaxRetriesExceededError
        from wama.common.utils.task_skeleton import ServiceNotReady, redeliver_later
        task = self._task(MaxRetriesExceededError("Can't retry"))
        with self.assertRaisesMessage(RuntimeError, 'still not installed after 6 h'):
            redeliver_later(task, ServiceNotReady('installing', gave_up='still not installed after 6 h'))

    def test_without_a_declared_reason_the_count_is_said(self):
        from celery.exceptions import MaxRetriesExceededError
        from wama.common.utils.task_skeleton import ServiceNotReady, redeliver_later
        task = self._task(MaxRetriesExceededError("Can't retry"))
        with self.assertRaisesMessage(RuntimeError, 'abandon après 3 tentatives'):
            redeliver_later(task, ServiceNotReady('service loading', max_attempts=3))


class SqueletteAnnonceTest(TestCase):
    """Le squelette commun sait le déclarer — comme `vram_needed`, et OPTIONNEL."""

    def test_le_squelette_accepte_model_key(self):
        import inspect
        from wama.common.utils.task_skeleton import run_item_task
        params = inspect.signature(run_item_task).parameters
        self.assertIn('model_key', params)
        self.assertIsNone(params['model_key'].default,
                          'la déclaration doit être OPTIONNELLE : une app qui ne la pose pas '
                          'garde exactement le comportement d’avant')
