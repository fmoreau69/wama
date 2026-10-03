"""`access_cases()` — l'énumération des cas d'accès montrée par la présentation (vue 3D des droits).

Ce qui compte : la présentation affiche des décisions RÉELLES. Un compte fictif qui décide
autrement qu'un vrai compte de même profil et mêmes rôles montrerait des droits faux, avec
l'autorité d'une visualisation — d'où la confrontation à de vrais `User` ci-dessous.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile
from wama.accounts.permissions import (
    GROUP_PREFIX, ROLES, TIER_ORDER, access_cases, accessible,
)


class AccessCasesTests(TestCase):

    def setUp(self):
        self.cases = access_cases()

    def _account(self, name, tier, roles):
        u = User.objects.create_user(name, password='x')
        UserProfile.objects.update_or_create(user=u, defaults={'account_tier': tier})
        u.groups.add(*[Group.objects.get_or_create(name=GROUP_PREFIX + r)[0] for r in roles])
        return User.objects.get(pk=u.pk)

    def test_the_grid_covers_every_tier_times_every_role_combination(self):
        self.assertEqual(len(self.cases['role_sets']), 2 ** len(ROLES))
        self.assertEqual(self.cases['configurations'], len(TIER_ORDER) * 2 ** len(ROLES))
        self.assertEqual(len(self.cases['matrix']), len(TIER_ORDER))
        for rows in self.cases['matrix']:
            self.assertEqual(len(rows), len(self.cases['role_sets']))
            for row in rows:
                self.assertEqual(len(row), len(self.cases['apps']))

    def test_every_case_matches_the_decision_for_a_real_account(self):
        apps = [a['id'] for a in self.cases['apps']]
        self.assertTrue(apps, "aucune app : le test ne mesurerait rien")
        for t, tier in enumerate(TIER_ORDER):
            for r, roles in enumerate(self.cases['role_sets']):
                user = self._account(f'case_{t}_{r}', tier, roles)
                real = [accessible(user, 'app', a) for a in apps]
                self.assertEqual(self.cases['matrix'][t][r], real, f"{tier} + {roles}")

    def test_distinct_behaviours_never_exceed_configurations(self):
        self.assertGreaterEqual(self.cases['distinct_rows'], 1)
        self.assertLessEqual(self.cases['distinct_rows'], self.cases['configurations'])


class PresentationRoutesTests(TestCase):

    def test_the_current_presentation_and_its_access_cases_are_served(self):
        self.assertEqual(self.client.get(reverse('presentation')).status_code, 200)
        r = self.client.get(reverse('presentation_access_cases'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('matrix', r.json())

    def test_the_transcription_report_is_served_with_its_three_charts(self):
        """Added to « Présentations & annexes » on 2026-10-02: a generated snapshot of the report,
        whose three charts the export had dropped — they are redrawn, none may be missing."""
        r = self.client.get(reverse('report', args=['transcription']))
        self.assertEqual(200, r.status_code)
        page = r.content.decode()
        self.assertEqual(3, page.count('<figure class="chart">'))
        self.assertNotIn('embedded content', page)
        self.assertNotIn('{%', page, 'no template syntax may leak into the page')
        self.assertEqual('/reports/transcription/', reverse('report', args=['transcription']),
                         'the address given out on 2026-10-02 stays valid')

    def test_every_declared_report_is_served_and_listed_by_the_home_menu(self):
        """The « Rapports » category is filled from the `REPORTS` declaration, like the archives:
        a report is added by its line, never by a hand-written menu entry."""
        from pathlib import Path

        from django.conf import settings
        from wama.views import REPORTS
        self.assertTrue(REPORTS)
        for slug in REPORTS:
            self.assertEqual(200, self.client.get(reverse('report', args=[slug])).status_code)
        self.assertEqual(404, self.client.get(reverse('report', args=['unknown'])).status_code)
        home = (Path(settings.BASE_DIR) / 'wama' / 'templates' / 'home.html').read_text(encoding='utf-8')
        self.assertIn("{% url 'report' r.slug %}", home)
        self.assertIn('Rapports</h6>', home)

    def test_archived_presentations_stay_reachable(self):
        from wama.views import ARCHIVED_PRESENTATIONS
        self.assertTrue(ARCHIVED_PRESENTATIONS)
        for slug in ARCHIVED_PRESENTATIONS:
            self.assertEqual(self.client.get(reverse('presentation_archive', args=[slug])).status_code, 200)
        self.assertEqual(self.client.get(reverse('presentation_archive', args=['unknown'])).status_code, 404)
