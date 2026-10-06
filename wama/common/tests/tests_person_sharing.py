"""PARTAGE À UNE PERSONNE + PRÉVENIR CELUI QUI REÇOIT (N1) — 2026-10-06.

Question de Fabien : *« on ne peut pas partager à un utilisateur seul »*. Exact : `ScopedVisibility`
n'offre que privé / unité / projet / public. La réponse était dessinée (`WAMA_COLLABORATION §2.1`,
§4.3, §4.5) : une ligne `ObjectGrant` à la personne, lue par `scoped_visible_q` EN EXTENSION de ses
portées. Ces tests éprouvent que la personne VOIT (par le filtre des vraies vues), que personne
d'autre ne voit, que le retrait défait ce que le partage a fait — aux deux niveaux, élément et
lot —, et que le destinataire est prévenu.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.common.models import (Notification, ObjectGrant, OrgUnit, Project, ProjectMembership,
                                ScopedVisibility)
from wama.common.services.sharing import (RefusDePartage, partager, persons_of, share_with_person,
                                          shares_overview, unshare_person)

User = get_user_model()


def _batch(user, total=1):
    from wama.converter.models import ConversionBatch
    return ConversionBatch.objects.create(user=user, total=total)


def _job(user, batch=None, name='witness.png'):
    from wama.converter.models import ConversionJob
    return ConversionJob.objects.create(user=user, input_filename=name, batch=batch)


def _job_model():
    from wama.converter.models import ConversionJob
    return ConversionJob


def _sees(user, obj) -> bool:
    return type(obj).objects.visible_to(user).filter(pk=obj.pk).exists()


class SharingWithAPersonTest(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user('ps_owner', password='x', email='owner@ex.org')
        self.bob = User.objects.create_user('ps_bob', password='x', email='bob@ex.org')
        self.third = User.objects.create_user('ps_third', password='x')

    def test_a_private_element_shared_with_a_person_is_visible_to_them_only(self):
        batch = _batch(self.owner)
        job = _job(self.owner, batch=batch)
        self.assertFalse(_sees(self.bob, job))
        share_with_person(self.owner, job, _job_model(), self.bob)
        job.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PRIVATE, job.visibility,
                         "un partage nominatif ne touche pas la portée")
        self.assertTrue(_sees(self.bob, job))
        self.assertTrue(_sees(self.bob, batch), "sans son lot, la card n'est pas dans la file")
        self.assertFalse(_sees(self.third, job))
        self.assertFalse(_sees(self.third, batch))

    def test_sharing_a_whole_batch_with_a_person_covers_its_elements(self):
        batch = _batch(self.owner, total=2)
        jobs = [_job(self.owner, batch=batch, name=f'{i}.png') for i in range(2)]
        share_with_person(self.owner, batch, _job_model(), self.bob, nature='lot')
        self.assertTrue(_sees(self.bob, batch))
        self.assertTrue(all(_sees(self.bob, j) for j in jobs), "un lot partagé ne s'affiche pas vide")

    def test_the_recipient_is_notified(self):
        job = _job(self.owner)
        share_with_person(self.owner, job, _job_model(), self.bob)
        note = Notification.objects.get(recipient=self.bob, kind='share_received')
        self.assertIn('ps_owner', note.title)
        self.assertEqual(str(job.pk), note.object_id)
        self.assertFalse(Notification.objects.filter(recipient=self.third).exists())

    def test_collaboration_is_given_only_by_its_mode(self):
        from wama.common.utils.scoping import can_edit
        job = _job(self.owner)
        share_with_person(self.owner, job, _job_model(), self.bob, 'read')
        self.assertFalse(can_edit(self.bob, job))
        share_with_person(self.owner, job, _job_model(), self.bob, 'collaborate')
        self.assertTrue(can_edit(self.bob, job))
        self.assertTrue(_sees(self.bob, job))

    def test_changing_the_mode_keeps_the_previous_line_as_memory(self):
        job = _job(self.owner)
        share_with_person(self.owner, job, _job_model(), self.bob, 'read')
        share_with_person(self.owner, job, _job_model(), self.bob, 'collaborate')
        lines = ObjectGrant.objects.filter(object_type=job._meta.label, object_id=job.pk,
                                           beneficiary=self.bob)
        self.assertEqual({('read', 'revoked'), ('collaborate', 'granted')},
                         set(lines.values_list('level', 'state')))
        self.assertEqual(['collaborate'], [p['mode']['key'] for p in persons_of(job)])

    def test_sharing_twice_in_the_same_mode_changes_nothing_the_second_time(self):
        job = _job(self.owner)
        share_with_person(self.owner, job, _job_model(), self.bob)
        share_with_person(self.owner, job, _job_model(), self.bob)
        self.assertEqual(1, ObjectGrant.objects.filter(object_type=job._meta.label,
                                                       object_id=job.pk).count())

    def test_a_pending_request_becomes_the_grant(self):
        """La demande ET le droit sont la même ligne (§4.3)."""
        job = _job(self.owner)
        request = ObjectGrant.objects.create(object_type=job._meta.label, object_id=job.pk,
                                             beneficiary=self.bob, level='collaborate')
        share_with_person(self.owner, job, _job_model(), self.bob, 'collaborate')
        request.refresh_from_db()
        self.assertEqual(ObjectGrant.STATE_GRANTED, request.state)
        self.assertEqual(self.owner, request.granted_by)

    def test_refusals(self):
        job = _job(self.owner)
        with self.assertRaises(RefusDePartage):
            share_with_person(self.third, job, _job_model(), self.bob)       # pas le propriétaire
        with self.assertRaises(RefusDePartage):
            share_with_person(self.owner, job, _job_model(), self.owner)     # soi-même
        with self.assertRaises(RefusDePartage):
            share_with_person(self.owner, job, _job_model(), self.bob, 'fork')   # pas construit
        with self.assertRaises(RefusDePartage):
            share_with_person(self.owner, job, _job_model(), self.bob, 'own')    # pas un mode
        self.assertFalse(_sees(self.bob, job))

    def test_an_expired_line_no_longer_shows_the_element(self):
        from datetime import timedelta
        from django.utils import timezone
        job = _job(self.owner)
        share_with_person(self.owner, job, _job_model(), self.bob)
        ObjectGrant.objects.filter(beneficiary=self.bob).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        self.assertFalse(_sees(self.bob, job))


class UnsharingAPersonTest(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user('pu_owner', password='x')
        self.bob = User.objects.create_user('pu_bob', password='x')

    def test_unsharing_hides_the_element_and_its_batch_and_notifies(self):
        batch = _batch(self.owner)
        job = _job(self.owner, batch=batch)
        share_with_person(self.owner, job, _job_model(), self.bob)
        self.assertEqual(1, unshare_person(self.owner, job, self.bob))
        self.assertFalse(_sees(self.bob, job))
        self.assertFalse(_sees(self.bob, batch), "le lot couvert part avec l'élément")
        note = Notification.objects.get(recipient=self.bob, kind='access_revoked')
        self.assertIn("n'est plus partagée", note.body)

    def test_the_batch_stays_while_another_element_is_still_shared(self):
        batch = _batch(self.owner, total=2)
        first, second = _job(self.owner, batch=batch, name='1.png'), _job(self.owner, batch=batch,
                                                                        name='2.png')
        share_with_person(self.owner, first, _job_model(), self.bob)
        share_with_person(self.owner, second, _job_model(), self.bob)
        unshare_person(self.owner, first, self.bob)
        self.assertFalse(_sees(self.bob, first))
        self.assertTrue(_sees(self.bob, second))
        self.assertTrue(_sees(self.bob, batch))

    def test_revoking_the_batch_line_revokes_its_elements(self):
        """Le geste de « Mes partages » (une ligne par entrée) : il défait les deux niveaux."""
        from wama.common.services.access_requests import revoke
        batch = _batch(self.owner, total=2)
        jobs = [_job(self.owner, batch=batch, name=f'{i}.png') for i in range(2)]
        share_with_person(self.owner, batch, _job_model(), self.bob, nature='lot',
                          surface='converter')
        line = ObjectGrant.objects.get(object_type=batch._meta.label, object_id=batch.pk)
        revoke(self.owner, line)
        self.assertFalse(any(_sees(self.bob, j) for j in jobs))

    def test_only_the_owner_unshares(self):
        job = _job(self.owner)
        share_with_person(self.owner, job, _job_model(), self.bob)
        with self.assertRaises(RefusDePartage):
            unshare_person(self.bob, job, self.bob)
        self.assertTrue(_sees(self.bob, job))


class ProjectMembersAreNotifiedTest(TestCase):
    """N1 pour une PORTÉE : les membres d'un projet sont prévenus ; une unité, non (§5.2)."""

    def setUp(self):
        self.owner = User.objects.create_user('pn_owner', password='x')
        self.member = User.objects.create_user('pn_member', password='x')
        self.project = Project.objects.create(code='PN_T', name='Projet témoin')
        for u in (self.owner, self.member):
            ProjectMembership.objects.create(project=self.project, user=u)

    def test_members_are_notified_once_when_the_element_enters_the_project(self):
        job = _job(self.owner)
        partager(self.owner, job, ScopedVisibility.VIS_PROJECT, project_id=self.project.id)
        partager(self.owner, job, ScopedVisibility.VIS_PROJECT, project_id=self.project.id)
        self.assertEqual(1, Notification.objects.filter(recipient=self.member,
                                                        kind='share_received').count())
        self.assertFalse(Notification.objects.filter(recipient=self.owner,
                                                     kind='share_received').exists())

    def test_a_unit_share_notifies_nobody(self):
        unit = OrgUnit.objects.create(code='PN_U', name='Labo PN', unit_type='labo')
        profile = self.owner.profile
        profile.org_entity_code = 'PN_U'
        profile.save(update_fields=['org_entity_code'])
        partager(self.owner, _job(self.owner), ScopedVisibility.VIS_UNIT, org_unit_id=unit.id)
        self.assertFalse(Notification.objects.filter(kind='share_received').exists())


class ScopeShareIsDatedTest(TestCase):
    """« Depuis quand » pour une PORTÉE aussi (Fabien, 2026-10-06 : *« autant rester homogène »*) :
    une ligne sans bénéficiaire, mémoire datée — jamais lue pour décider qui voit."""

    def setUp(self):
        self.owner = User.objects.create_user('sd_owner', password='x')
        self.bob = User.objects.create_user('sd_bob', password='x')

    def _lines(self, obj):
        return ObjectGrant.objects.filter(object_type=obj._meta.label, object_id=obj.pk,
                                          beneficiary__isnull=True)

    def test_a_scope_share_is_dated_and_reapplying_it_keeps_the_date(self):
        from wama.common.services.sharing import scope_since
        job = _job(self.owner)
        self.assertIsNone(scope_since(job))
        partager(self.owner, job, ScopedVisibility.VIS_PUBLIC)
        first = scope_since(job)
        self.assertIsNotNone(first)
        partager(self.owner, job, ScopedVisibility.VIS_PUBLIC)
        self.assertEqual(first, scope_since(job))
        self.assertEqual(1, self._lines(job).count())

    def test_changing_the_scope_or_going_private_keeps_the_memory(self):
        from wama.common.services.sharing import scope_since
        project = Project.objects.create(code='SD_P', name='Projet SD')
        ProjectMembership.objects.create(project=project, user=self.owner)
        job = _job(self.owner)
        partager(self.owner, job, ScopedVisibility.VIS_PUBLIC)
        partager(self.owner, job, ScopedVisibility.VIS_PROJECT, project_id=project.id)
        partager(self.owner, job, ScopedVisibility.VIS_PRIVATE)
        self.assertIsNone(scope_since(job))
        self.assertEqual([('public', 'revoked'), ('project', 'revoked')],
                         list(self._lines(job).order_by('created_at')
                              .values_list('visibility', 'state')))

    def test_a_batch_share_dates_the_batch_and_its_elements(self):
        from wama.common.services.sharing import partager_lot, scope_since
        batch = _batch(self.owner, total=2)
        jobs = [_job(self.owner, batch=batch, name=f'{i}.png') for i in range(2)]
        partager_lot(self.owner, batch, _job_model(), ScopedVisibility.VIS_PUBLIC)
        for obj in [batch, *jobs]:
            obj.refresh_from_db()
            self.assertIsNotNone(scope_since(obj))

    def test_a_scope_line_is_neither_a_person_nor_a_right(self):
        job = _job(self.owner)
        partager(self.owner, job, ScopedVisibility.VIS_PUBLIC)
        self.assertEqual([], persons_of(job))
        partager(self.owner, job, ScopedVisibility.VIS_PRIVATE)
        self.assertFalse(_sees(self.bob, job), "la ligne de portée ne fait voir à personne")

    def test_a_share_older_than_the_dating_has_no_invented_date(self):
        from wama.common.services.sharing import scope_since
        job = _job(self.owner)
        type(job).objects.filter(pk=job.pk).update(visibility=ScopedVisibility.VIS_PUBLIC)
        job.refresh_from_db()
        self.assertIsNone(scope_since(job))


class PersonSharingSurfacesTest(TestCase):
    """La route, la page « Partages » et la pastille de la card."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        self.owner = User.objects.create_user('pv_owner', password='x')
        self.bob = User.objects.create_user('pv_bob', password='x', email='pv_bob@ex.org')
        for role in ('communication', 'recherche', 'ingenierie', 'administratif'):
            g, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
            self.owner.groups.add(g)
        self.client.force_login(self.owner)

    def test_the_route_shares_with_a_person_named_by_email_and_revokes(self):
        job = _job(self.owner, batch=_batch(self.owner))
        url = reverse('common:api_partage', args=['converter', 'element', job.id])
        rep = self.client.post(url, {'person': 'PV_BOB@ex.org', 'mode': 'read'})
        self.assertEqual(200, rep.status_code, rep.content[:300])
        self.assertEqual(['pv_bob'], [p['name'] for p in rep.json()['persons']])
        self.assertTrue(_sees(self.bob, job))
        self.assertEqual(['pv_bob'], [p['name'] for p in self.client.get(url).json()['etat']['persons']])
        rep = self.client.post(url, {'revoke_person': self.bob.pk})
        self.assertEqual([], rep.json()['persons'])
        self.assertFalse(_sees(self.bob, job))

    def test_the_route_refuses_an_unknown_person_with_a_reason(self):
        job = _job(self.owner)
        url = reverse('common:api_partage', args=['converter', 'element', job.id])
        rep = self.client.post(url, {'person': 'nobody-here'})
        self.assertEqual(400, rep.status_code)
        self.assertIn('aucun compte', rep.json()['reason'])

    def test_unsharing_everything_from_the_shares_page_removes_the_persons_too(self):
        job = _job(self.owner, batch=_batch(self.owner))
        share_with_person(self.owner, job, _job_model(), self.bob)
        url = reverse('common:api_partage', args=['converter', 'element', job.id])
        rep = self.client.post(url, {'visibility': 'private', 'unshare_persons': '1'})
        self.assertEqual(200, rep.status_code, rep.content[:300])
        self.assertFalse(_sees(self.bob, job))

    def test_the_shares_page_lists_a_private_element_shared_with_a_person(self):
        job = _job(self.owner, batch=_batch(self.owner))
        share_with_person(self.owner, job, _job_model(), self.bob)
        mine = shares_overview(self.owner)['shared']
        self.assertEqual(1, len(mine))
        self.assertEqual(['pv_bob'], [p['name'] for p in mine[0]['persons']])
        received = shares_overview(self.bob)['received']
        self.assertEqual(['read'], [r['mode']['key'] for r in received])
        page = self.client.get(reverse('common:shares'))
        self.assertContains(page, 'pv_bob')

    def test_the_shares_page_and_the_modal_say_since_when_for_a_scope(self):
        from django.utils import timezone
        job = _job(self.owner, batch=_batch(self.owner))
        url = reverse('common:api_partage', args=['converter', 'element', job.id])
        self.client.post(url, {'visibility': 'public'})
        self.assertIsNotNone(self.client.get(url).json()['etat']['scope_since'])
        today = timezone.localtime().strftime('%d/%m/%Y')
        self.assertContains(self.client.get(reverse('common:shares')), f'depuis le {today}')

    def test_the_owner_card_says_it_is_shared(self):
        from wama.common.services.reception import entry_arrangement
        batch = _batch(self.owner)
        _job(self.owner, batch=batch)
        self.assertEqual({}, entry_arrangement(self.owner, batch, {}))
        share_with_person(self.owner, batch, _job_model(), self.bob, nature='lot')
        label = entry_arrangement(self.owner, batch, {})['share_label']
        self.assertIn('Partagée', label)
        self.assertIn('1 personne', label)
        received = entry_arrangement(self.bob, batch, {})
        self.assertEqual('pv_owner', received['received_from'])
