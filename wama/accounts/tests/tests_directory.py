"""L'annuaire lu par unité et la PRÉ-INSCRIPTION des comptes (`accounts/directory.py`,
`PROFILES_PERMISSIONS.md §1.12`, 2026-11-25).

Sans annuaire : la liaison est un faux qui répond à la question qu'on lui pose (et garde ce qu'on
lui a demandé de lire), la fiche d'une personne est simulée au point où la librairie la charge.
Le reste — moteur de connexion, signaux, profil, formulaire, notifications — est le vrai. Toutes
les fiches sont inventées.
"""
import io
import re
from unittest import mock

import ldap
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django_auth_ldap.backend import _LDAPUser
from django_auth_ldap.config import LDAPSearch

from wama.accounts import directory, moderation
from wama.accounts.ldap_backend import WamaLDAPBackend
from wama.accounts.permissions import set_account_tier
from wama.common.models import Notification

PEOPLE_BASE, UNITS_BASE = 'ou=people,dc=test', 'ou=units,dc=test'

UNITS = [
    {'supannCodeEntite': 'LAB-A', 'description': 'Laboratoire A', 'supannCodeEntiteParent': 'DEPT'},
    {'supannCodeEntite': 'LAB-A-T1', 'description': 'Équipe 1', 'supannCodeEntiteParent': 'LAB-A'},
    {'supannCodeEntite': 'LAB-B', 'ou': 'Laboratoire B', 'supannCodeEntiteParent': 'DEPT'},
    {'supannCodeEntite': 'DEPT', 'description': 'Département'},
]

#: Chaque fiche porte PLUS que ce qu'un compte demande : le faux rend tout ce qu'on lui réclame.
PEOPLE = [
    {'uid': 'zoe.martin', 'givenName': 'Zoé', 'sn': 'Martin', 'mail': 'zoe.martin@univ.test',
     'supannEntiteAffectationPrincipale': 'LAB-A', 'supannEntiteAffectation': ['LAB-A', 'OLD-A'],
     'supannEtablissement': '{UAI}0000000X', 'eduPersonAffiliation': ['member', 'researcher'],
     'l': 'Ville-A',
     'telephoneNumber': '0102030405', 'title': 'Chercheuse'},
    {'uid': 'Adam.Petit', 'givenName': 'Adam', 'sn': 'Petit', 'mail': 'adam.petit@univ.test',
     'supannEntiteAffectationPrincipale': 'LAB-A-T1', 'supannEntiteAffectation': ['LAB-A-T1'],
     'telephoneNumber': '0102030406'},
    {'uid': 'lea.roux', 'givenName': 'Léa', 'sn': 'Roux', 'mail': 'lea.roux@univ.test',
     'supannEntiteAffectationPrincipale': 'LAB-A', 'supannEntiteAffectation': ['LAB-A', 'LAB-B'],
     'telephoneNumber': '0102030407'},
    {'uid': 'tom.blanc', 'givenName': 'Tom', 'sn': 'Blanc', 'mail': 'tom.blanc@univ.test',
     'supannEntiteAffectationPrincipale': 'LAB-B', 'supannEntiteAffectation': ['LAB-B']},
]

DIRECTORY_SETTINGS = dict(
    AUTH_LDAP_USER_SEARCH=LDAPSearch(PEOPLE_BASE, ldap.SCOPE_SUBTREE, '(uid=%(user)s)'),
    AUTH_LDAP_USER_ATTR_MAP={'first_name': 'givenName', 'last_name': 'sn', 'email': 'mail'},
    LDAP_STRUCTURES_BASE_DN=UNITS_BASE,
    WAMA_MODERATOR_EMAILS=['moderation@test.local'],
)


def _as_list(value):
    return value if isinstance(value, list) else [value]


class FakeDirectory:
    """Une liaison d'annuaire : elle répond aux filtres que la brique écrit, ne rend que les
    attributs RÉCLAMÉS (en octets, comme la vraie), et garde chaque question posée."""

    def __init__(self):
        self.asked = []          # (base, filtre, attributs réclamés)
        self.closed = False

    def unbind_s(self):
        self.closed = True

    def search_s(self, base, scope, filterstr, attrlist=None):
        self.asked.append((base, filterstr, tuple(attrlist or ())))
        rows = UNITS if base == UNITS_BASE else PEOPLE
        key = 'supannCodeEntite' if base == UNITS_BASE else 'uid'
        return [(f"{key}={row[key]},{base}",
                 {name: [str(v).encode() for v in _as_list(row[name])]
                  for name in (attrlist or row) if name in row})
                for row in rows if self._matches(row, filterstr)]

    @staticmethod
    def _matches(row, filterstr):
        """Un OU de clauses `(attribut=valeur)`, `*` en joker — ce que la brique sait écrire."""
        for name, wanted in re.findall(r'\(([\w-]+)=([^()]*)\)', filterstr):
            pattern = '.*'.join(re.escape(part) for part in wanted.split('*'))
            if any(re.fullmatch(pattern, str(v)) for v in _as_list(row.get(name, []))):
                return True
        return False


def _directory_people():
    """Ce que la librairie de connexion charge pour UNE personne (`populate_user`) : sa fiche
    inventée, ou rien si l'annuaire ne la connaît pas."""
    known = {row['uid'].lower(): row for row in PEOPLE}

    def load_dn(ldap_user):
        row = known.get(ldap_user._username.lower())
        ldap_user._user_dn = f"uid={row['uid']},{PEOPLE_BASE}" if row else None

    def load_attrs(ldap_user):
        row = known.get(ldap_user._username.lower())
        ldap_user._user_attrs = ({name: [str(v) for v in _as_list(value)]
                                  for name, value in row.items()} if row else None)

    return mock.patch.multiple(_LDAPUser, _load_user_dn=load_dn, _load_user_attrs=load_attrs)


@override_settings(**DIRECTORY_SETTINGS)
class DirectoryReadTests(SimpleTestCase):
    """La lecture seule : unités, personnes, et rien que la liste fermée."""

    def setUp(self):
        self.conn = FakeDirectory()

    def test_a_text_finds_its_units_and_all_their_sub_units(self):
        units = directory.find_units('LAB-A', conn=self.conn)
        self.assertEqual(['LAB-A', 'LAB-A-T1'], [u['code'] for u in units])
        self.assertEqual({'code': 'LAB-A', 'name': 'Laboratoire A', 'type': '', 'parent': 'DEPT'},
                         units[0])
        by_label = directory.find_units('Département', conn=self.conn)
        self.assertEqual(['DEPT', 'LAB-A', 'LAB-A-T1', 'LAB-B'], [u['code'] for u in by_label])
        self.assertEqual('Laboratoire B', by_label[-1]['name'], "le nom court en repli du libellé")

    def test_an_exact_code_does_not_match_its_neighbours_and_survives_being_unknown(self):
        self.assertEqual(['LAB-B'],
                         [u['code'] for u in directory.find_units('LAB-B', exact=True, conn=self.conn)])
        self.assertEqual([{'code': 'OLD-A', 'name': 'OLD-A', 'type': '', 'parent': ''}],
                         directory.find_units('OLD-A', exact=True, conn=self.conn))
        self.assertEqual([], directory.find_units('   ', conn=self.conn))

    def test_people_of_a_unit_are_those_whose_main_unit_it_is(self):
        people = directory.people_of(['LAB-A', 'LAB-A-T1'], conn=self.conn)
        self.assertEqual(['Adam.Petit', 'lea.roux', 'zoe.martin'], [p['username'] for p in people])
        self.assertEqual({'username': 'zoe.martin', 'first_name': 'Zoé', 'last_name': 'Martin',
                          'email': 'zoe.martin@univ.test', 'main_unit': 'LAB-A'}, people[-1])
        # Une seule appartenance, la principale : Léa porte aussi LAB-B sur sa fiche, Zoé un code
        # hérité — ni l'une ni l'autre ne se retrouve sous ces unités-là.
        self.assertEqual(['tom.blanc'],
                         [p['username'] for p in directory.people_of(['LAB-B'], conn=self.conn)])
        self.assertEqual([], directory.people_of(['OLD-A'], conn=self.conn))
        self.assertEqual([], directory.people_of([], conn=self.conn))

    def test_only_the_closed_list_of_attributes_is_ever_asked_from_the_directory(self):
        directory.find_units('LAB', conn=self.conn)
        directory.people_of(['LAB-A', 'LAB-B'], conn=self.conn)
        allowed = {UNITS_BASE: set(directory.UNIT_ATTRIBUTES),
                   PEOPLE_BASE: {'uid', 'givenName', 'sn', 'mail',
                                 'supannEntiteAffectationPrincipale'}}
        self.assertEqual({UNITS_BASE, PEOPLE_BASE}, {base for base, _f, _a in self.conn.asked})
        for base, _filter, asked in self.conn.asked:
            self.assertTrue(asked, "une question sans liste d'attributs lit TOUTE la fiche")
            self.assertLessEqual(set(asked), allowed[base])
        for person in directory.people_of(['LAB-A', 'LAB-B'], conn=self.conn):
            self.assertEqual({'username', 'first_name', 'last_name', 'email', 'main_unit'},
                             set(person))

    def test_a_code_is_escaped_before_it_enters_a_filter(self):
        directory.people_of(['A)(uid=*'], conn=self.conn)
        directory.find_units('x)(ou=*', conn=self.conn)
        for _base, filterstr, _asked in self.conn.asked:
            self.assertNotIn('(uid=*', filterstr)
            self.assertNotIn('x)(ou=*', filterstr)
        self.assertIn(r'A\29\28uid=\2a', self.conn.asked[0][1])

    def test_the_login_attribute_is_read_from_the_settings_search(self):
        self.assertEqual('uid', directory.login_attribute())
        other = LDAPSearch(PEOPLE_BASE, ldap.SCOPE_SUBTREE, '(&(cn=%(user)s)(objectClass=person))')
        with override_settings(AUTH_LDAP_USER_SEARCH=other):
            self.assertEqual('cn', directory.login_attribute())
            self.assertEqual('cn', directory.person_attributes()[0])

    def test_an_unset_or_silent_directory_says_so(self):
        with override_settings(AUTH_LDAP_SERVER_URI=''):
            with self.assertRaises(directory.DirectoryUnavailable):
                directory.connect()
        with override_settings(LDAP_STRUCTURES_BASE_DN=None):
            with self.assertRaises(directory.DirectoryUnavailable):
                directory.find_units('LAB', conn=self.conn)
        with mock.patch.object(self.conn, 'search_s', side_effect=ldap.SIZELIMIT_EXCEEDED()):
            with self.assertRaises(directory.DirectoryUnavailable):
                directory.people_of(['LAB-A'], conn=self.conn)

    def test_a_session_closes_the_connection_it_opened_and_only_that_one(self):
        with mock.patch.object(directory, 'connect', return_value=self.conn):
            with directory.session() as opened:
                self.assertIs(self.conn, opened)
            self.assertTrue(self.conn.closed)
        mine = FakeDirectory()
        with directory.session(mine):
            pass
        self.assertFalse(mine.closed)


@override_settings(**DIRECTORY_SETTINGS)
class PreregisterTests(TestCase):
    """La pré-inscription : un compte inactif, le minimum dessus, personne de prévenu."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('the.admin', password='x', email='admin@test.local')
        set_account_tier(cls.admin, 'admin')

    def setUp(self):
        people = _directory_people()
        people.start()
        self.addCleanup(people.stop)

    def _pending(self, user):
        return Notification.objects.filter(kind=moderation.ACCOUNT_PENDING_KIND,
                                           object_type='User', object_id=str(user.pk))

    def test_an_absent_person_gets_an_inactive_account_with_the_minimum_and_nobody_is_told(self):
        report = directory.preregister(['zoe.martin'])
        self.assertEqual({'created': ['zoe.martin'], 'existing': [], 'missing': []}, report)
        zoe = User.objects.get(username='zoe.martin')
        self.assertFalse(zoe.is_active)
        self.assertFalse(zoe.has_usable_password(), "le mot de passe reste à l'annuaire")
        self.assertIsNone(zoe.last_login)
        self.assertEqual(('Zoé', 'Martin', 'zoe.martin@univ.test'),
                         (zoe.first_name, zoe.last_name, zoe.email))
        self.assertEqual(0, zoe.groups.count(), "aucun rôle par défaut")
        self.assertEqual('utilisateur', zoe.profile.account_tier)
        # Le MINIMUM : l'unité principale, et rien de ce que la fiche porte d'autre.
        self.assertEqual('LAB-A', zoe.profile.org_entity_code)
        self.assertEqual(([], '', ''), (zoe.profile.org_affiliations, zoe.profile.establishment,
                                        zoe.profile.ldap_affiliation))
        # Personne n'a rien demandé : ni cloche, ni email.
        self.assertFalse(self._pending(zoe).exists())
        self.assertEqual([], mail.outbox)

    def test_preregistering_stays_inactive_even_when_moderation_is_switched_off(self):
        with override_settings(WAMA_MODERATE_NEW_USERS=False):
            directory.preregister(['tom.blanc'])
        self.assertFalse(User.objects.get(username='tom.blanc').is_active)

    def test_an_existing_account_is_left_untouched_and_an_unknown_name_is_reported(self):
        kept = User.objects.create_user('adam.petit', first_name='Adam (ici)', is_active=True)
        report = directory.preregister(['Adam.Petit', 'no.body', 'lea.roux', 'lea.roux'])
        self.assertEqual({'created': ['lea.roux'], 'existing': ['Adam.Petit'],
                          'missing': ['no.body']}, report)
        kept.refresh_from_db()
        self.assertEqual(('Adam (ici)', True, ''), (kept.first_name, kept.is_active,
                                                    kept.profile.org_entity_code))
        self.assertFalse(User.objects.filter(username__iexact='no.body').exists())
        # Rejouable : un second passage ne trouve que de l'existant.
        again = directory.preregister(['lea.roux'])
        self.assertEqual((['lea.roux'], []), (again['existing'], again['created']))

    def test_a_first_login_through_the_same_backend_still_asks_the_moderators(self):
        """Contre-épreuve : la pré-inscription ne tait la demande que pour ELLE — le moteur de
        connexion ordinaire, lui, prévient toujours. Le profil, lui, reçoit le même minimum dans
        les deux cas : le reste s'ajoute avec la personne (`tests_directory_consent`)."""
        user = WamaLDAPBackend().populate_user('tom.blanc')
        self.assertFalse(user.is_active)
        self.assertEqual({self.admin}, {n.recipient for n in self._pending(user)})
        profile = User.objects.get(pk=user.pk).profile
        self.assertEqual(('LAB-B', []), (profile.org_entity_code, profile.org_affiliations))

    def test_a_preregistered_person_who_comes_learns_it_waits_and_the_moderators_are_asked(self):
        directory.preregister(['zoe.martin'])
        zoe = User.objects.get(username='zoe.martin')
        with mock.patch.object(WamaLDAPBackend, 'authenticate', return_value=zoe):
            page = self.client.post(reverse('accounts:login'),
                                    {'username': 'zoe.martin', 'password': 'directory-ok'},
                                    REMOTE_ADDR='10.1.2.3', HTTP_USER_AGENT='Mozilla/5.0')
        self.assertContains(page, 'en attente de validation par un administrateur')
        self.assertEqual({self.admin}, {n.recipient for n in self._pending(zoe)})

    def test_activating_a_preregistered_account_welcomes_its_holder(self):
        directory.preregister(['zoe.martin'])
        zoe = User.objects.get(username='zoe.martin')
        self.client.force_login(self.admin)
        done = self.client.post(reverse('accounts:user-toggle-active', args=[zoe.pk]))
        self.assertTrue(done.json()['is_active'])
        self.assertEqual([['zoe.martin@univ.test']], [m.to for m in mail.outbox])
        # Elle n'a rien demandé : le message dit que le compte EXISTE, ce qu'il porte, d'où cela
        # vient et comment le faire supprimer — pas « votre compte a été validé ».
        welcome = mail.outbox[0]
        self.assertIn('préparé pour vous', welcome.subject)
        for told in ("l'annuaire de l'établissement", 'votre unité', 'supprimer',
                     'moderation@test.local'):
            self.assertIn(told, welcome.body)
        self.assertNotIn('a été validé', welcome.body)

    def test_activating_an_account_whose_holder_came_tells_it_was_validated(self):
        """Contre-épreuve du message : la personne VENUE lit que sa demande est acceptée."""
        directory.preregister(['zoe.martin'])
        zoe = User.objects.get(username='zoe.martin')
        moderation.pending_login(zoe)
        mail.outbox.clear()
        moderation.activate_accounts([zoe])
        self.assertEqual(['[WAMA] Votre compte est activé'], [m.subject for m in mail.outbox])
        self.assertIn('a été validé', mail.outbox[0].body)

    def test_the_states_of_a_unit_read_absent_preregistered_and_active_whatever_the_case(self):
        User.objects.create_user('adam.petit', is_active=True)
        directory.preregister(['lea.roux'])
        people = directory.with_account_state(
            directory.people_of(['LAB-A', 'LAB-A-T1'], conn=FakeDirectory()))
        self.assertEqual({'Adam.Petit': 'active', 'lea.roux': 'preregistered', 'zoe.martin': 'absent'},
                         {p['username']: p['state'] for p in people})
        self.assertLessEqual({p['state'] for p in people}, set(directory.state_labels()))

    def test_a_pass_never_creates_more_accounts_than_the_limit_and_then_creates_none(self):
        before = User.objects.count()
        with self.assertRaises(ValueError):
            directory.preregister(['zoe.martin', 'lea.roux'], limit=1)
        self.assertEqual(before, User.objects.count())

    # ── La commande ─────────────────────────────────────────────────────────────────────────

    def _command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(directory, 'connect', side_effect=FakeDirectory):
            call_command('preregister_accounts', *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_the_command_writes_nothing_without_apply(self):
        before = User.objects.count()
        out, err = self._command('--unit', 'LAB-A')
        self.assertEqual('', err)
        self.assertIn('LAB-A — Laboratoire A', out)
        self.assertIn('3 personne(s) : 3 sans compte', out)
        self.assertIn('Rien n\'est écrit', out)
        self.assertEqual(before, User.objects.count())

    def test_the_command_preregisters_the_absent_ones_with_apply_and_can_be_replayed(self):
        User.objects.create_user('adam.petit', is_active=True)
        out, _err = self._command('--code', 'LAB-A', '--apply')
        self.assertIn('2 compte(s) pré-inscrit(s), inactifs', out)
        self.assertEqual({'zoe.martin': False, 'lea.roux': False, 'adam.petit': True},
                         dict(User.objects.exclude(pk=self.admin.pk).values_list('username', 'is_active')))
        out, _err = self._command('--code', 'LAB-A', '--apply')
        self.assertIn('0 compte(s) pré-inscrit(s)', out)

    def test_the_command_will_not_create_more_accounts_than_its_limit(self):
        before = User.objects.count()
        _out, err = self._command('--unit', 'LAB', '--apply', '--limit', '2')
        self.assertIn('au plus 2', err)
        self.assertEqual(before, User.objects.count())

    def test_the_command_needs_a_unit_and_says_when_none_matches(self):
        _out, err = self._command()
        self.assertIn('Désigner une unité', err)
        out, _err = self._command('--unit', 'NOWHERE')
        self.assertIn('Aucune unité', out)


@override_settings(**DIRECTORY_SETTINGS)
class AccountsPageTests(TestCase):
    """La page des utilisateurs : l'état de chaque compte, son unité, l'activation d'une sélection,
    l'import depuis l'annuaire — et les mêmes gestes par l'assistant."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('the.admin', password='x', email='admin@test.local')
        set_account_tier(cls.admin, 'admin')
        cls.plain = User.objects.create_user('a.member', password='x')

    def setUp(self):
        people = _directory_people()
        people.start()
        self.addCleanup(people.stop)
        connect = mock.patch.object(directory, 'connect', side_effect=FakeDirectory)
        connect.start()
        self.addCleanup(connect.stop)

    def _post(self, name, payload):
        return self.client.post(reverse(name), data=payload, content_type='application/json')

    # ── L'état d'un compte ──────────────────────────────────────────────────────────────────

    def test_an_inactive_account_reads_preregistered_pending_or_disabled(self):
        from django.utils import timezone

        from wama.accounts.models import AccessLog
        directory.preregister(['zoe.martin', 'lea.roux', 'tom.blanc'])
        zoe, lea, tom = (User.objects.get(username=name)
                         for name in ('zoe.martin', 'lea.roux', 'tom.blanc'))
        moderation.pending_login(lea)                       # elle est venue, identité prouvée
        # Un mot de passe faux sur le compte de Tom ne laisse qu'un NOM au journal : il n'a rien
        # demandé, son compte reste pré-inscrit.
        AccessLog.objects.create(username='tom.blanc', event='login_denied', reason='inactive')
        gone = User.objects.create_user('gone.away', is_active=False, last_login=timezone.now())
        local = User.objects.create_user('local.closed', password='x', is_active=False)
        service = User.objects.create_user('anonymous', is_active=False)
        states = moderation.account_states([zoe, lea, tom, gone, local, service, self.admin])
        self.assertEqual({zoe.pk: 'preregistered', lea.pk: 'pending', tom.pk: 'preregistered',
                          gone.pk: 'disabled', local.pk: 'disabled', service.pk: 'disabled',
                          self.admin.pk: 'active'}, states)
        self.assertEqual(set(states.values()), set(moderation.ACCOUNT_STATES))
        self.assertEqual('pending', moderation.account_state(lea))

    def test_the_page_shows_each_account_state_and_unit_and_offers_the_directory(self):
        directory.preregister(['zoe.martin'])
        zoe = User.objects.get(username='zoe.martin')
        self.client.force_login(self.admin)
        page = self.client.get(reverse('accounts:user-management')).content.decode()
        row = re.search(r'<tr class="user-row" data-user-id="%d".*?</tr>' % zoe.pk, page, re.S).group(0)
        self.assertIn('data-f-statut="preregistered"', row)
        self.assertIn('data-f-unit="LAB-A"', row)
        self.assertIn('Pré-inscrit', row)
        self.assertIn('class="form-check-input select-account"', row, "un compte inactif se coche")
        mine = re.search(r'<tr class="user-row" data-user-id="%d".*?</tr>' % self.admin.pk,
                         page, re.S).group(0)
        self.assertIn('data-f-statut="active"', mine)
        self.assertNotIn('select-account', mine, "un compte actif ne se coche pas")
        self.assertIn('id="directoryModal"', page)
        self.assertIn(reverse('accounts:directory-lookup'), page)
        with override_settings(AUTH_LDAP_SERVER_URI=''):
            bare = self.client.get(reverse('accounts:user-management')).content.decode()
        self.assertNotIn('id="directoryModal"', bare, "sans annuaire réglé, rien à importer")

    # ── Activer une sélection ───────────────────────────────────────────────────────────────

    def test_a_selection_of_inactive_accounts_is_activated_and_each_holder_is_written_to(self):
        directory.preregister(['zoe.martin', 'lea.roux', 'tom.blanc'])
        ids = dict(User.objects.values_list('username', 'pk'))
        service = User.objects.create_user('anonymous', is_active=False)
        self.client.force_login(self.admin)
        done = self._post('accounts:users-activate',
                          {'ids': [ids['zoe.martin'], ids['lea.roux'], self.admin.pk, service.pk]})
        self.assertEqual((['lea.roux', 'zoe.martin'], ['anonymous', 'the.admin']),
                         (done.json()['activated'], sorted(done.json()['skipped'])))
        watched = ['zoe.martin', 'lea.roux', 'tom.blanc', 'anonymous']
        self.assertEqual({'zoe.martin': True, 'lea.roux': True, 'tom.blanc': False, 'anonymous': False},
                         dict(User.objects.filter(username__in=watched)
                              .values_list('username', 'is_active')))
        self.assertEqual({'zoe.martin@univ.test', 'lea.roux@univ.test'},
                         {m.to[0] for m in mail.outbox})
        self.assertEqual(400, self.client.post(reverse('accounts:users-activate'), data='not json',
                                               content_type='application/json').status_code)

    def test_only_an_administrator_activates_reads_the_directory_or_prepares_accounts(self):
        directory.preregister(['zoe.martin'])
        zoe = User.objects.get(username='zoe.martin')
        before = User.objects.count()
        for client_user in (None, self.plain):
            if client_user is not None:
                self.client.force_login(client_user)
            self.assertEqual(302, self._post('accounts:users-activate', {'ids': [zoe.pk]}).status_code)
            self.assertEqual(302, self.client.get(reverse('accounts:directory-lookup'),
                                                  {'q': 'LAB-A'}).status_code)
            self.assertEqual(302, self._post('accounts:directory-preregister',
                                             {'usernames': ['lea.roux']}).status_code)
        zoe.refresh_from_db()
        self.assertFalse(zoe.is_active)
        self.assertEqual(before, User.objects.count())

    # ── Importer depuis l'annuaire ──────────────────────────────────────────────────────────

    def test_the_page_reads_a_unit_with_each_person_state_and_prepares_the_chosen_ones(self):
        User.objects.create_user('adam.petit', is_active=True)
        self.client.force_login(self.admin)
        found = self.client.get(reverse('accounts:directory-lookup'), {'q': 'LAB-A'}).json()
        self.assertTrue(found['success'])
        self.assertEqual(['LAB-A', 'LAB-A-T1'], [u['code'] for u in found['units']])
        self.assertEqual({'Adam.Petit': 'active', 'lea.roux': 'absent', 'zoe.martin': 'absent'},
                         {p['username']: p['state'] for p in found['people']})
        self.assertEqual('absent', found['absent'])
        self.assertLessEqual({p['state'] for p in found['people']}, set(found['states']))
        short = self.client.get(reverse('accounts:directory-lookup'), {'q': 'LA'}).json()
        self.assertFalse(short['success'])
        self.assertIn('au moins 3', short['error'])

        done = self._post('accounts:directory-preregister', {'usernames': ['zoe.martin', 'no.body']})
        self.assertEqual((['zoe.martin'], ['no.body']), (done.json()['created'], done.json()['missing']))
        self.assertFalse(User.objects.get(username='zoe.martin').is_active)
        self.assertEqual([], mail.outbox)
        over = self._post('accounts:directory-preregister',
                          {'usernames': [f'someone.{n}' for n in range(directory.PREREGISTER_LIMIT + 1)]})
        self.assertEqual(400, over.status_code)
        self.assertFalse(User.objects.filter(username__startswith='someone.').exists())

    # ── Les mêmes gestes par l'assistant ────────────────────────────────────────────────────

    def test_the_assistant_tools_are_for_administrators_and_carry_no_name_nor_address(self):
        import json

        from wama import tool_api
        for tool, args in ((tool_api.list_directory_accounts, {'unit': 'LAB-A'}),
                           (tool_api.preregister_accounts, {'unit': 'LAB-A', 'confirm': True}),
                           (tool_api.activate_accounts, {'usernames': ['zoe.martin'], 'confirm': True})):
            self.assertIn('administrateur', tool(self.plain, **args)['error'])
            self.assertIn('error', tool(None, **args))
        self.assertFalse(User.objects.filter(username='zoe.martin').exists())

        listing = tool_api.list_directory_accounts(self.admin, 'LAB-A')
        self.assertEqual({'absent': 3}, listing['counts'])
        self.assertEqual({'username', 'state'}, {key for p in listing['people'] for key in p})
        told = json.dumps(listing, ensure_ascii=False)
        for private in ('@univ.test', 'Zoé', 'Martin', '0102030405'):
            self.assertNotIn(private, told)
        self.assertIn('au moins 3', tool_api.list_directory_accounts(self.admin, 'LA')['error'])

    def test_the_assistant_prepares_and_activates_accounts_only_once_confirmed(self):
        from wama import tool_api
        before = User.objects.count()
        asked = tool_api.preregister_accounts(self.admin, unit='LAB-A')
        self.assertIn('confirm=true', asked['error'])
        self.assertEqual((3, before), (asked['count'], User.objects.count()))
        done = tool_api.preregister_accounts(self.admin, unit='LAB-A', confirm=True)
        # L'identifiant d'un compte est celui que la connexion poserait : en minuscules.
        self.assertEqual(['adam.petit', 'lea.roux', 'zoe.martin'], done['preregistered'])
        self.assertIn('error', tool_api.preregister_accounts(self.admin, unit='LAB-A', confirm=True),
                      "plus personne sans compte dans cette unité")

        waiting = tool_api.activate_accounts(self.admin, ['ZOE.MARTIN', 'no.body'])
        self.assertEqual((['zoe.martin'], ['no.body']), (waiting['usernames'], waiting['unknown']))
        self.assertFalse(User.objects.get(username='zoe.martin').is_active)
        done = tool_api.activate_accounts(self.admin, ['ZOE.MARTIN', 'no.body', 'the.admin'], confirm=True)
        self.assertEqual((['zoe.martin'], ['the.admin'], ['no.body']),
                         (done['activated'], done['skipped'], done['unknown']))
        self.assertTrue(User.objects.get(username='zoe.martin').is_active)
        for name in ('list_directory_accounts', 'preregister_accounts', 'activate_accounts'):
            self.assertIn(name, tool_api.TOOL_REGISTRY)

    # ── La constellation ────────────────────────────────────────────────────────────────────

    def test_a_preregistered_account_waits_in_a_layer_of_the_constellation_that_starts_off(self):
        from wama.accounts.constellation import constellation
        from wama.common.scenes import get_scene
        directory.preregister(['zoe.martin'])
        people = {p['username']: p for p in constellation()['users']}
        self.assertEqual(('preregistered', 'preregistered', 'Pré-inscrit'),
                         tuple(people['zoe.martin'][key] for key in ('state', 'layer', 'state_label')))
        self.assertIsNone(people['the.admin']['layer'])
        layers = {layer['key']: layer for layer in get_scene('users').layers}
        self.assertEqual(('nodes', False), (layers['preregistered']['role'], layers['preregistered']['on']))
        self.assertLessEqual({p['layer'] for p in people.values()} - {None}, set(layers))

    # ── La fiche d'un compte, dans le volet droit ───────────────────────────────────────────

    def test_the_right_panel_reads_the_record_of_an_account_and_what_links_it_to_others(self):
        import json

        from wama import tool_api
        from wama.common.models import OrgUnit
        OrgUnit.objects.create(code='LAB-A', name='Laboratoire A', unit_type='labo')
        directory.preregister(['zoe.martin', 'lea.roux', 'tom.blanc'])
        zoe = User.objects.get(username='zoe.martin')
        zoe.profile.site = 'Ville-A'
        zoe.profile.save()
        self.client.force_login(self.admin)
        page = self.client.get(reverse('accounts:user-management')).content.decode()
        self.assertIn('id="userDetails"', page)
        self.assertIn('data-url="%s"' % reverse('accounts:user-details', args=[0]), page)
        self.assertIn('Ville-A</small>', page, "le site gardé par la personne, sous son unité")
        told = self.client.get(reverse('accounts:user-details', args=[zoe.pk])).json()
        card = told['card']
        self.assertEqual(('zoe.martin', 'preregistered', 'Pré-inscrit'),
                         (card['username'], card['state'], card['state_label']))
        self.assertEqual(['Laboratoire A'], [unit['name'] for unit in card['units']])
        # Léa a la même unité principale, Tom non : un seul autre compte dans l'unité.
        self.assertEqual({'count': 1, 'names': ['Léa Roux']}, card['colleagues'])
        self.assertEqual(([], [], []), (card['projects'], card['shares_given'], card['shares_received']))
        rows = {row['key']: row for row in told['directory']}
        self.assertEqual((True, 'Ville-A'), (rows['site']['stored'], rows['site']['value']))
        self.assertTrue(told['directory_account'])
        self.assertEqual(404, self.client.get(reverse('accounts:user-details', args=[999999])).status_code)
        local = self.client.get(reverse('accounts:user-details', args=[self.plain.pk])).json()
        self.assertEqual((False, []), (local['directory_account'], local['directory']))
        # L'assistant : les mêmes faits, sans nom ni adresse.
        said = tool_api.get_account_details(self.admin, 'ZOE.MARTIN')
        self.assertEqual(('zoe.martin', 'preregistered', ['Laboratoire A']),
                         (said['username'], said['state'], said['unit']))
        for private in ('@univ.test', 'Zoé', 'Léa', 'Ville-A'):
            self.assertNotIn(private, json.dumps(said, ensure_ascii=False))
        self.assertIn('administrateur', tool_api.get_account_details(self.plain, 'zoe.martin')['error'])
        self.assertIn('error', tool_api.get_account_details(self.admin, 'no.body'))
        self.client.force_login(self.plain)
        self.assertEqual(302, self.client.get(reverse('accounts:user-details', args=[zoe.pk])).status_code)

    # ── Les restes : la demande close, la qualité, le rapprochement ─────────────────────────

    def test_activating_an_account_closes_the_request_still_waiting_with_the_others(self):
        other = User.objects.create_user('second.admin', password='x')
        set_account_tier(other, 'admin')
        directory.preregister(['zoe.martin'])
        zoe = User.objects.get(username='zoe.martin')
        moderation.pending_login(zoe)
        waiting = Notification.objects.filter(kind=moderation.ACCOUNT_PENDING_KIND,
                                              object_id=str(zoe.pk))
        self.assertEqual(2, waiting.filter(read_at__isnull=True).count())
        moderation.activate_accounts([zoe])
        self.assertEqual((0, 2), (waiting.filter(read_at__isnull=True).count(), waiting.count()))
        # La ligne reste : c'est elle qui dit que la personne était venue.
        User.objects.filter(pk=zoe.pk).update(is_active=False)
        self.assertEqual('pending', moderation.account_state(User.objects.get(pk=zoe.pk)))

    def test_the_accounts_page_shows_the_status_a_person_keeps_on_the_profile(self):
        directory.preregister(['zoe.martin'])
        profile = User.objects.get(username='zoe.martin').profile
        profile.ldap_affiliation = 'member, researcher'
        profile.save()
        self.client.force_login(self.admin)
        page = self.client.get(reverse('accounts:user-management')).content.decode()
        self.assertIn('member, researcher</small>', page)

    def test_the_reconciliation_names_arrivals_and_departures_and_tells_the_administrators_once(self):
        directory.preregister(['zoe.martin', 'tom.blanc'])
        # Tom est rangé dans LAB-A par WAMA, l'annuaire le compte dans LAB-B : un départ de LAB-A.
        moved = User.objects.get(username='tom.blanc').profile
        moved.org_entity_code = 'LAB-A'
        moved.save()
        local = User.objects.create_user('local.person', password='x')      # pas un compte d'annuaire
        local.profile.org_entity_code = 'LAB-A'
        local.profile.save()
        report = directory.reconcile(['LAB-A'])
        self.assertEqual({'units': ['LAB-A', 'LAB-A-T1'], 'arrivals': ['Adam.Petit', 'lea.roux'],
                          'departures': ['tom.blanc']}, report)
        with override_settings(WAMA_DIRECTORY_FOLLOWED_UNITS=[]):       # aucune unité suivie
            self.assertEqual({'units': [], 'arrivals': [], 'departures': []}, directory.reconcile())
        asked = Notification.objects.filter(kind=directory.DIRECTORY_CHANGES_KIND)
        self.assertEqual(1, directory.report_reconciliation(report))
        self.assertEqual(0, directory.report_reconciliation(report), "une notification attend déjà")
        self.assertEqual([self.admin], [n.recipient for n in asked])
        self.assertIn('tom.blanc', asked.get().body)
        self.assertNotIn('lea.roux', asked.get().body)
        self.assertEqual(0, directory.report_reconciliation(
            {'units': ['LAB-A'], 'arrivals': [], 'departures': []}))

    def test_the_nightly_task_reads_nothing_without_followed_units_and_reports_with_them(self):
        from wama.common.tasks import reconcile_directory_accounts_task
        with mock.patch.object(directory, 'reconcile') as read, \
                override_settings(AUTH_LDAP_SERVER_URI=''):
            self.assertEqual({'units': 0}, reconcile_directory_accounts_task())
            read.assert_not_called()
        # Un compte d'annuaire déjà en base, que l'annuaire ne connaît plus : un départ, même
        # hors de toute unité suivie. Un autre, à jour de rien : remis à jour sans rien demander.
        gone = User.objects.create_user('gone.away')
        gone.set_unusable_password()
        gone.save()
        directory.preregister(['zoe.martin'])
        stale = User.objects.get(username='zoe.martin').profile
        stale.org_entity_code, stale.org_affiliations = 'OLD-A', ['OLD-A', 'LAB-A']
        stale.save()
        with override_settings(WAMA_DIRECTORY_FOLLOWED_UNITS=['LAB-B']):
            done = reconcile_directory_accounts_task()
        self.assertEqual({'units': 1, 'arrivals': 1, 'departures': 1, 'updated': 1, 'notified': 1}, done)
        fresh = User.objects.get(username='zoe.martin').profile
        self.assertEqual(('LAB-A', [], ''), (fresh.org_entity_code, fresh.org_affiliations,
                                             fresh.establishment),
                         "l'unité suit l'annuaire, l'ancienne liste part, rien de neuf ne s'ajoute")
        self.assertIn('gone.away', Notification.objects.get(kind=directory.DIRECTORY_CHANGES_KIND).body)
        out = io.StringIO()
        call_command('refresh_directory_profiles', stdout=out)
        self.assertIn("2 compte(s) d'annuaire : 0 à mettre à jour, 1 inconnu(s)", out.getvalue())
        out, err = io.StringIO(), io.StringIO()
        call_command('reconcile_directory_accounts', '--code', 'LAB-B', stdout=out, stderr=err)
        self.assertIn('1 arrivée(s), sans compte', out.getvalue())
        self.assertIn('tom.blanc', out.getvalue())
        self.assertEqual('', err.getvalue())
