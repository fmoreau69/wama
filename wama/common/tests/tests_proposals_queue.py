"""La file « Propositions à valider » est une brique COMMUNE, montée sur la page du registre de ce
qu'elle propose (décision de Fabien, 2026-11-07, `WAMA_VOLETS §2`) — la page des librairies
montre les propositions de librairies, et elles seules.
"""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from wama.common.models import Manifest


def _pending(kind, key):
    """Une DEMANDE de promotion en attente, comme la dépose un rôle (`proposals.propose`)."""
    return Manifest.objects.create(manifest_kind=kind, key=key, name=key, body={},
                                   visibility='private', promotion_requested_at=timezone.now())


class LibraryPageHostsItsQueueTest(TestCase):
    def test_the_served_page_mounts_the_library_queue_for_an_account_that_reads_it(self):
        admin = get_user_model().objects.create_user('queue_admin', password='x', is_superuser=True)
        self.client.force_login(admin)
        page = self.client.get(reverse('model_manager:libraries_catalog'))
        self.assertContains(page, 'data-wama-proposals')
        self.assertContains(page, '?kind=library')
        self.assertContains(page, 'common/js/wama-proposals.js')

    def test_an_ordinary_account_sees_the_registry_without_the_queue(self):
        self.client.force_login(get_user_model().objects.create_user('queue_user', password='x'))
        page = self.client.get(reverse('model_manager:libraries_catalog'))
        self.assertEqual(200, page.status_code)
        self.assertNotContains(page, 'data-wama-proposals')

    def test_the_queue_of_a_family_lists_that_family_only(self):
        library, model = _pending('library', 'probe-lib'), _pending('model', 'probe:model')
        self.client.force_login(get_user_model().objects.create_user(
            'queue_admin2', password='x', is_superuser=True))
        url = reverse('model_manager:api_manifest_proposals')
        listed = [p['id'] for p in self.client.get(url + '?kind=library').json()['proposals']]
        self.assertEqual([library.pk], listed)
        # Contre-épreuve : sans filtre, la file du model manager garde les deux familles.
        self.assertEqual({library.pk, model.pk},
                         {p['id'] for p in self.client.get(url).json()['proposals']})


class ServedQueueRendersThePlanTest(SimpleTestCase):
    """Le fichier SERVI (V8) : il se charge sans navigateur, et une proposition invalide n'offre
    pas « Valider » ; un compte qui ne décide pas ne voit aucun bouton ; le texte est échappé."""

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        ctx = MiniRacer()
        ctx.eval("""var window = this; var location = {hash: '', pathname: '/', search: ''};
                    var document = {readyState: 'complete', cookie: '',
                                    querySelectorAll: function () { return []; },
                                    addEventListener: function () {}};""")
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js' / 'wama-proposals.js'
        ctx.eval(served.read_text(encoding='utf-8'))
        return ctx

    def _html(self, ctx, proposal, hidden=False):
        return ctx.eval('WamaProposals.manifestHtml(%s, "", %s)'
                        % (json.dumps(proposal), 'true' if hidden else 'false'))

    def test_an_invalid_proposal_cannot_be_validated_and_its_text_is_escaped(self):
        ctx = self._ctx()
        html = self._html(ctx, {'id': 3, 'kind': 'library', 'key': '<img src=x>', 'filled': ['body'],
                                'errors': ['identity.author trop long']})
        self.assertIn('data-decision="apply" disabled', html)
        self.assertIn('&lt;img src=x&gt;', html)
        self.assertNotIn('<img src=x>', html)

    def test_a_valid_proposal_offers_validate_and_hides_the_buttons_from_a_developer(self):
        ctx = self._ctx()
        proposal = {'id': 4, 'kind': 'library', 'key': 'rosbags', 'filled': ['body'], 'errors': []}
        self.assertNotIn('disabled', self._html(ctx, proposal))
        self.assertIn('d-flex gap-1 mt-1 d-none', self._html(ctx, proposal, hidden=True))
