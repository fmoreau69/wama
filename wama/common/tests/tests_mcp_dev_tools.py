"""
Surface MCP « wama-dev » (2026-09-15, étape 3) — outils de développement dans un process séparé.

⚠ CE QUE CES GARDES PROTÈGENT, et aucun de ces défauts ne lève d'exception :
  1. §16 : les outils de dev ne doivent JAMAIS être chargés dans le process de prod — seul un
     import vérifié dans un process neuf le prouve ;
  2. les droits sont vérifiés à CHAQUE appel, pas seulement à la liste (un client peut appeler
     un outil qu'on ne lui a pas annoncé) ;
  3. un argument non déclaré ou une valeur lue comme une option n'arrive jamais à la commande ;
  4. `app_regen_check` ne reçoit jamais `--force` : sa garde (refus sur dev/main) reste entière ;
  5. le prédicat développeur lit le VRAI champ de tier (`account_tier`) — la version d'avant
     lisait `profile.tier`, inexistant, et aucun test ne le voyait.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import anyio
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase

from wama.common.services import dev_tools, mcp_server


class PredicatDeveloppeurTest(TestCase):

    def _user(self, name):
        return get_user_model().objects.create_user(name, password='x')

    def test_un_utilisateur_ordinaire_n_est_pas_developpeur(self):
        from wama.accounts.permissions import is_developer
        self.assertFalse(is_developer(self._user('ordinaire')))
        self.assertFalse(is_developer(None))

    def test_les_groupes_font_un_developpeur(self):
        from wama.accounts.permissions import DEVELOPER_GROUPS, is_developer
        for groupe in DEVELOPER_GROUPS:
            with self.subTest(groupe=groupe):
                user = self._user(f'g_{groupe}')
                user.groups.add(Group.objects.get_or_create(name=groupe)[0])
                self.assertTrue(is_developer(user))

    def test_le_TIER_developpeur_suffit_sans_groupe(self):
        """La branche qui était MORTE : `profile.tier` n'existe pas, le champ est `account_tier`."""
        from wama.accounts.models import UserProfile
        from wama.accounts.permissions import is_developer
        from wama.common.services.claude_code import subscription_allowed
        user = self._user('tier_dev')
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.account_tier = 'developpeur'
        profile.save()
        user = get_user_model().objects.get(pk=user.pk)       # relire le profil
        self.assertTrue(is_developer(user))
        self.assertTrue(subscription_allowed(user), "l'abonnement délègue au même prédicat")


class ArgumentsTest(SimpleTestCase):

    def test_un_role_construit_une_liste_d_arguments(self):
        argv = dev_tools.role_command('librarian', {'dist': 'requests'}, provider='albert')
        self.assertTrue(argv[1].endswith('run_librarian.py'))
        self.assertEqual(['--dist', 'requests', '--provider', 'albert'], argv[2:])

    def test_un_booleen_devient_une_option_sans_valeur(self):
        argv = dev_tools.role_command('scout', {'hf': 'org/x', 'dry_run': True})
        self.assertIn('--dry-run', argv)
        self.assertNotIn('True', argv)

    def test_un_role_ou_un_argument_inconnu_est_refuse(self):
        with self.assertRaises(dev_tools.DevToolError):
            dev_tools.role_command('audit')
        with self.assertRaises(dev_tools.DevToolError):
            dev_tools.role_command('librarian', {'output': '/etc/passwd'})

    def test_une_valeur_lue_comme_option_ou_multiligne_est_refusee(self):
        for valeur in ('--force', '-x', 'a\nb', ''):
            with self.subTest(valeur=valeur):
                with self.assertRaises(dev_tools.DevToolError):
                    dev_tools.role_command('librarian', {'dist': valeur})

    def test_le_bac_a_sable_exige_ses_arguments(self):
        self.assertEqual(['app_sandbox', 'list'], dev_tools.sandbox_command('list')[2:])
        self.assertEqual(['app_sandbox', 'create', 'converter', '--proprietaire', 'fab'],
                         dev_tools.sandbox_command('create', 'converter', owner='fab')[2:])
        with self.assertRaises(dev_tools.DevToolError):
            dev_tools.sandbox_command('substitute', 'converter_01')
        with self.assertRaises(dev_tools.DevToolError):
            dev_tools.sandbox_command('rm')

    def test_le_harnais_ne_recoit_jamais_force(self):
        self.assertNotIn('--force', dev_tools.regen_check_command('converter'))


class TachesTest(SimpleTestCase):
    """Cycle RÉEL d'une tâche détachée, avec une commande inoffensive."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(dev_tools, 'jobs_dir', return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _attendre(self, job_id, secondes=20):
        for _ in range(secondes * 10):
            state = dev_tools.job_state(job_id)
            if state['status'] != 'running':
                return state
            time.sleep(0.1)
        self.fail("la tâche n'a pas fini")

    def test_une_tache_reussie_rend_son_journal(self):
        user = mock.Mock(username='dev')
        job = dev_tools.start_job(user, 'essai', [sys.executable, '-c', "print('bonjour')"])
        state = self._attendre(job['job_id'])
        self.assertEqual('done', state['status'])
        self.assertEqual(0, state['returncode'])
        self.assertIn('bonjour', state['log_tail'])

    def test_une_tache_en_echec_le_dit(self):
        job = dev_tools.start_job(mock.Mock(username='dev'), 'essai',
                                  [sys.executable, '-c', 'raise SystemExit(3)'])
        state = self._attendre(job['job_id'])
        self.assertEqual('failed', state['status'])
        self.assertEqual(3, state['returncode'])

    def test_un_identifiant_forge_est_refuse(self):
        with self.assertRaises(dev_tools.DevToolError):
            dev_tools.job_state('../../etc/passwd')


class DroitsEtSurfaceTest(TestCase):

    def setUp(self):
        self.ordinaire = get_user_model().objects.create_user('mcp_dev_ordinaire', password='x')
        self.dev = get_user_model().objects.create_user('mcp_dev_dev', password='x')
        self.dev.groups.add(Group.objects.get_or_create(name='dev')[0])

    def test_un_non_developpeur_ne_voit_ni_n_appelle_rien(self):
        self.assertEqual([], dev_tools.tools_for(self.ordinaire))
        with mock.patch.object(dev_tools, 'start_job') as lancement:
            res = dev_tools.call(self.ordinaire, 'dev_sandbox', {'action': 'list'})
        self.assertEqual('forbidden', res['error'])
        lancement.assert_not_called()

    def test_un_developpeur_voit_les_outils_de_dev(self):
        noms = sorted(t.name for t in dev_tools.tools_for(self.dev))
        self.assertEqual(sorted(dev_tools.DEV_TOOLS), noms)

    def test_un_refus_d_argument_devient_une_erreur_lisible(self):
        res = dev_tools.call(self.dev, 'dev_run_role', {'role': 'librarian',
                                                        'args': {'dist': '--evil'}})
        self.assertIn('refusée', res['error'])

    def test_la_surface_dev_sert_les_outils_de_dev_par_le_protocole(self):
        import os as _os

        async def main():
            from mcp.shared.memory import create_connected_server_and_client_session
            server = mcp_server.build_server(fixed_user=self.dev, surface=mcp_server.SURFACE_DEV)
            async with create_connected_server_and_client_session(server) as session:
                return sorted(t.name for t in (await session.list_tools()).tools)

        # ⚠ Prédicat DOUBLÉ ici : sous `anyio.run`, Django ouvre une connexion propre au contexte
        # asynchrone, qui ne voit pas les groupes créés dans la transaction du test. Le prédicat
        # est gardé en synchrone par `PredicatDeveloppeurTest` ; ce test garde le TRANSPORT.
        with mock.patch.object(mcp_server, '_run_sync', lambda fn: _inline(fn)), \
                mock.patch.dict(_os.environ, {'DJANGO_ALLOW_ASYNC_UNSAFE': 'true'}), \
                mock.patch('wama.accounts.permissions.is_developer', return_value=True):
            noms = anyio.run(main)
        self.assertEqual(sorted(dev_tools.DEV_TOOLS), noms)
        self.assertFalse(set(noms) & set(__import__('wama.tool_api', fromlist=['x']).TOOL_REGISTRY))


async def _inline(fn):
    return fn()


class SeparationDesProcessTest(SimpleTestCase):
    """§16 : lancer la surface `wama` ne charge JAMAIS les outils de développement.

    Vérifié dans un process NEUF — dans celui des tests, le module est déjà importé par ce fichier."""

    def test_la_surface_prod_n_importe_pas_les_outils_de_dev(self):
        code = ("import os,sys,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');"
                "django.setup();"
                "from wama.common.services import mcp_server;mcp_server.build_server();"
                "import wama.tool_api;"
                "print(json.dumps('wama.common.services.dev_tools' in sys.modules))")
        res = subprocess.run([sys.executable, '-c', 'import json;' + code],
                             capture_output=True, text=True, cwd=str(settings.BASE_DIR),
                             timeout=300)
        self.assertEqual(0, res.returncode, res.stderr[-800:])
        self.assertEqual('false', res.stdout.strip().splitlines()[-1])
