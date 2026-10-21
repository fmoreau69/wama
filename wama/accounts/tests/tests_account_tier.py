"""
Le RÔLE d'un compte n'a qu'UNE définition : le NIVEAU de son profil (décision de Fabien, 2026-10-21).

Trois sources décidaient d'« administrateur » ou de « développeur » — le niveau
(`UserProfile.account_tier`), les drapeaux Django (`is_staff`, `is_superuser`) et les groupes
hérités `admin` / `dev` / `user` de `accounts/0002` — et rien ne les tenait d'accord (mesuré le
jour même : deux administrateurs au niveau « utilisateur », un compte du groupe `dev` au niveau
« utilisateur »). Ces tests tiennent la décision :
  • `set_account_tier` est le seul écrivain, et les drapeaux en DÉCOULENT ;
  • `is_admin_tier` ne lit ni `is_staff` ni un groupe ;
  • `administrators()` est la liste qu'on prévient (modération, promotion) ;
  • `align_account_tiers` reporte l'ancien état sur le niveau, puis retire les groupes ;
  • aucune décision du code ne relit `is_staff` (garde AST sur tout le dépôt).
"""
import ast
import warnings
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from wama.accounts.permissions import (
    administrators, is_admin_tier, is_developer, set_account_tier, user_tier,
)


def _fresh(user):
    return User.objects.select_related('profile').get(pk=user.pk)


class SetAccountTierTest(TestCase):

    def test_the_flags_follow_the_tier_both_ways(self):
        user = User.objects.create_user('tier_flags', password='x')
        set_account_tier(user, 'admin')
        user = _fresh(user)
        self.assertEqual(('admin', True, True),
                         (user.profile.account_tier, user.is_staff, user.is_superuser))
        set_account_tier(user, 'developpeur')
        user = _fresh(user)
        self.assertEqual(('developpeur', False, False),
                         (user.profile.account_tier, user.is_staff, user.is_superuser))

    def test_the_object_in_hand_follows_the_tier_it_was_given(self):
        user = User.objects.create_user('tier_in_hand', password='x')
        user.profile  # chargé avant l'écriture, comme dans une vue
        set_account_tier(user, 'developpeur')
        self.assertEqual('developpeur', user_tier(user))
        self.assertTrue(is_developer(user))

    def test_an_unknown_tier_is_refused_and_nothing_is_written(self):
        user = User.objects.create_user('tier_unknown', password='x')
        with self.assertRaises(ValueError):
            set_account_tier(user, 'superviseur')
        self.assertEqual('utilisateur', _fresh(user).profile.account_tier)


class OneDefinitionTest(TestCase):

    def test_neither_the_staff_flag_nor_a_legacy_group_makes_an_administrator(self):
        staff = User.objects.create_user('flag_only', password='x', is_staff=True)
        grouped = User.objects.create_user('group_only', password='x')
        grouped.groups.add(Group.objects.get_or_create(name='admin')[0])
        for user in (staff, grouped):
            self.assertFalse(is_admin_tier(_fresh(user)), user.username)
            self.assertNotIn(user.pk, [u.pk for u in administrators()])

    def test_administrators_are_the_active_admin_tier_accounts(self):
        tiered = User.objects.create_user('admin_by_tier', password='x')
        set_account_tier(tiered, 'admin')
        root = User.objects.create_superuser('admin_by_root', password='x')
        gone = User.objects.create_user('admin_gone', password='x', is_active=False)
        set_account_tier(gone, 'admin')
        found = {u.pk for u in administrators()}
        self.assertTrue({tiered.pk, root.pk} <= found)
        self.assertNotIn(gone.pk, found)


class AlignAccountTiersTest(TestCase):

    def setUp(self):
        self.root = User.objects.create_superuser('align_root', password='x')       # niveau utilisateur
        self.grouped_admin = User.objects.create_user('align_grouped_admin', password='x')
        self.grouped_admin.groups.add(Group.objects.get_or_create(name='admin')[0])
        self.grouped_dev = User.objects.create_user('align_grouped_dev', password='x')
        self.grouped_dev.groups.add(Group.objects.get_or_create(name='dev')[0])
        self.staff_only = User.objects.create_user('align_staff_only', password='x', is_staff=True)
        self.business = Group.objects.get_or_create(name='role:recherche')[0]
        self.grouped_dev.groups.add(self.business)
        Group.objects.get_or_create(name='user')

    def _run(self, *args):
        out = StringIO()
        call_command('align_account_tiers', *args, stdout=out)
        return out.getvalue()

    def test_a_dry_run_reports_and_writes_nothing(self):
        report = self._run()
        self.assertIn('align_root', report)
        self.assertIn('--apply', report)
        self.assertEqual('utilisateur', _fresh(self.root).profile.account_tier)
        self.assertTrue(Group.objects.filter(name='admin').exists())

    def test_apply_moves_every_source_onto_the_tier_then_drops_the_legacy_groups(self):
        self._run('--apply')
        expected = {
            'align_root': ('admin', True, True),
            'align_grouped_admin': ('admin', True, True),
            'align_grouped_dev': ('developpeur', False, False),
            # Le drapeau seul ne faisait pas un administrateur : il est retiré, pas promu.
            'align_staff_only': ('utilisateur', False, False),
        }
        for username, wanted in expected.items():
            user = User.objects.select_related('profile').get(username=username)
            self.assertEqual(wanted, (user.profile.account_tier, user.is_staff, user.is_superuser),
                             username)
        self.assertFalse(Group.objects.filter(name__in=('admin', 'dev', 'user', 'developpeur')).exists())
        self.assertIn(self.business, _fresh(self.grouped_dev).groups.all(),
                      "un rôle MÉTIER `role:*` a été touché")
        self.assertIn('rien à faire', self._run('--apply'), "un second passage change encore")

    def test_a_tier_never_goes_down(self):
        set_account_tier(self.grouped_dev, 'admin')
        self._run('--apply')
        self.assertEqual('admin', _fresh(self.grouped_dev).profile.account_tier)


class NoDecisionReadsADjangoFlagTest(TestCase):
    """Aucune décision du code ne relit `is_staff` ni `is_superuser` : ils n'ouvrent que le site
    d'administration Django, et seul l'écrivain du niveau les pose. Relevé par AST sur `wama/`,
    `wama_lab/`, `wama_data/` (hors tests et migrations) : un attribut LU, un
    `getattr(…, '<drapeau>')`, un argument nommé `<drapeau>=` (filtre ou création)."""

    FLAGS = ('is_staff', 'is_superuser')

    #: Les seuls lieux admis, et pourquoi.
    ALLOWED = {
        # `user_tier` compte un superutilisateur administrateur (un compte de `createsuperuser`
        # n'a pas encore de profil) ; `set_account_tier` ÉCRIT les drapeaux.
        'wama/accounts/permissions.py',
        # Elle RELÈVE l'ancien état pour le reporter sur le niveau, puis le réécrit.
        'wama/accounts/management/commands/align_account_tiers.py',
    }

    def _reads(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in self.FLAGS \
                    and isinstance(node.ctx, ast.Load):
                yield node.lineno
            elif isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'getattr' \
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and node.args[1].value in self.FLAGS:
                yield node.lineno
            elif isinstance(node, ast.keyword) and node.arg \
                    and node.arg.split('__')[0] in self.FLAGS:
                yield node.value.lineno

    def test_no_decision_reads_a_django_flag(self):
        base = Path(settings.BASE_DIR)
        found = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (base / root).rglob('*.py'):
                rel = path.relative_to(base).as_posix()
                parts = path.relative_to(base).parts
                if rel in self.ALLOWED or 'migrations' in parts or 'tests' in parts \
                        or path.name.startswith('tests') or path.name == 'tests.py':
                    continue
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', SyntaxWarning)
                        tree = ast.parse(path.read_text(encoding='utf-8'))
                except (SyntaxError, UnicodeDecodeError):
                    continue
                found += [f'{rel}:{line}' for line in self._reads(tree)]
        self.assertEqual([], found, "une décision relit un drapeau Django (is_staff, is_superuser) "
                                    "— lire `permissions.is_admin_tier` (le niveau du profil)")
