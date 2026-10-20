"""À QUI EST un skill de prompt — `ROADMAP §29`, décision de Fabien du 2026-10-20 (piste 2).

CE QUE CES GARDES TIENNENT :
  1. un skill d'utilisateur (`common.PromptSkill`) passe devant le skill système du même nom
     POUR SON AUTEUR SEUL ; un autre compte, une tâche sans compte gardent le système ;
  2. un skill PARTAGÉ se voit et se copie, il ne s'impose à personne ; un skill promu SYSTÈME
     s'applique à tous, avant le fichier ;
  3. la décision unique `accessible(user, 'skill', nom)` lit la ligne, et la ligne privée d'un
     autre ne retire pas le fichier système du même nom (`Registry.in_code`) ;
  4. les gestes (`services/user_skills`) : il naît privé, seul son auteur le modifie et le
     partage, un administrateur seul le rend système, jamais par-dessus un fichier du dépôt ;
  5. les appelants passent le compte : le bouton ✨, l'ingestion, les paroles du composer.
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile
from wama.accounts.permissions import accessible
from wama.common.models import PromptSkill
from wama.common.services import user_skills as us
from wama.common.utils.prompt_skills import load_skill, resolve_skill, skills_catalog

FILE_SKILL = 'imager-image'          # un fichier du dépôt (`prompt_skills/imager-image.md`)
FRESH = 'zzprov-skill'               # un nom qu'aucun fichier ne porte


def _account(username, tier='utilisateur'):
    user = get_user_model().objects.create_user(username, password='x')
    UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
    return get_user_model().objects.get(pk=user.pk)


class _Accounts(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.author = _account('skill_author')
        cls.other = _account('skill_other')
        cls.dev = _account('skill_dev', 'developpeur')
        cls.admin = _account('skill_admin', 'admin')


class ResolutionTest(_Accounts):

    def test_the_authors_skill_passes_before_the_system_file_for_the_author_only(self):
        self.assertTrue(load_skill(FILE_SKILL), "le fichier système doit exister")
        us.create(self.author, FILE_SKILL, 'MY OWN CONSIGNE')
        self.assertEqual((FILE_SKILL, 'MY OWN CONSIGNE'),
                         resolve_skill(app='imager', domain='image', user=self.author))
        for who in (self.other, self.admin, None):
            self.assertEqual(load_skill(FILE_SKILL),
                             resolve_skill(app='imager', domain='image', user=who)[1], who)

    def test_a_shared_skill_is_seen_and_copied_never_imposed(self):
        row = us.create(self.author, FILE_SKILL, 'SHARED CONSIGNE')
        us.share(self.author, row.pk, 'public')
        self.assertIn(row.pk, [r.pk for r in us.visible_skills(self.other)])
        self.assertEqual(load_skill(FILE_SKILL),
                         resolve_skill(app='imager', domain='image', user=self.other)[1])
        mine = us.copy(self.other, pk=row.pk)
        self.assertEqual((self.other.pk, 'private', 'skill_author:imager-image'),
                         (mine.owner_id, mine.visibility, mine.source['copied_from']))
        self.assertEqual('SHARED CONSIGNE',
                         resolve_skill(app='imager', domain='image', user=self.other)[1])

    def test_a_promoted_skill_applies_to_everyone_and_joins_the_system_catalogue(self):
        row = us.create(self.author, FRESH, 'PROMOTED CONSIGNE')
        self.assertNotIn(FRESH, skills_catalog(), "un skill privé n'est pas au système")
        self.assertEqual((None, None), resolve_skill(app='zzprov', domain='skill',
                                                     user=self.other, kind=None))
        us.promote(self.admin, row.pk)
        for who in (self.other, None):
            self.assertEqual((FRESH, 'PROMOTED CONSIGNE'),
                             resolve_skill(app='zzprov', domain='skill', user=who, kind=None))
        self.assertEqual('PROMOTED CONSIGNE', skills_catalog()[FRESH])


class AccessDecisionTest(_Accounts):

    def test_a_private_skill_is_seen_by_its_author_and_the_administrator(self):
        us.create(self.author, FRESH, 'x')
        self.assertEqual((True, False, True),
                         tuple(accessible(u, 'skill', FRESH)
                               for u in (self.author, self.other, self.admin)))

    def test_another_accounts_private_skill_does_not_hide_the_system_file(self):
        us.create(self.author, FILE_SKILL, 'x')
        self.assertTrue(accessible(self.other, 'skill', FILE_SKILL))

    def test_a_file_skill_without_a_row_is_open(self):
        self.assertTrue(accessible(self.other, 'skill', FILE_SKILL))


class GesturesTest(_Accounts):

    def test_a_skill_is_born_private_once_per_name_and_validated(self):
        row = us.create(self.author, FRESH, '  consigne  ')
        self.assertEqual(('private', 'consigne', 'skill_author'),
                         (row.visibility, row.text, row.source['created_by']))
        for name, text in ((FRESH, 'again'), ('Bad Name', 'x'), ('ok-name', '   ')):
            with self.assertRaises(us.SkillRefused, msg=name):
                us.create(self.author, name, text)

    def test_only_its_author_edits_and_shares_it(self):
        row = us.create(self.author, FRESH, 'x')
        us.share(self.author, row.pk, 'public')
        with self.assertRaises(us.SkillRefused) as edit:
            us.update(self.other, row.pk, 'hijack')
        self.assertEqual(403, edit.exception.status)
        with self.assertRaises(us.SkillRefused):
            us.share(self.other, row.pk, 'private')
        self.assertEqual('x', PromptSkill.objects.get(pk=row.pk).text)

    def test_a_system_skill_is_customised_into_a_private_copy(self):
        mine = us.copy(self.other, name=FILE_SKILL)
        self.assertEqual((load_skill(FILE_SKILL), 'système:imager-image'),
                         (mine.text, mine.source['copied_from']))

    def test_its_author_or_an_administrator_deletes_it(self):
        row = us.create(self.author, FRESH, 'x')
        us.share(self.author, row.pk, 'public')
        with self.assertRaises(us.SkillRefused):
            us.delete(self.other, row.pk)
        us.delete(self.admin, row.pk)
        self.assertFalse(PromptSkill.objects.filter(pk=row.pk).exists())

    def test_only_an_administrator_promotes_and_never_over_a_repository_file(self):
        row = us.create(self.author, FRESH, 'x')
        own = us.create(self.dev, 'zzprov-dev', 'x')        # une ligne que le développeur VOIT
        with self.assertRaises(us.SkillRefused) as refused:
            us.promote(self.dev, own.pk)
        self.assertEqual(403, refused.exception.status)
        self.assertEqual(self.dev.pk, PromptSkill.objects.get(pk=own.pk).owner_id)
        us.promote(self.admin, row.pk)
        row.refresh_from_db()
        self.assertEqual((None, 'public', 'skill_author', 'skill_admin'),
                         (row.owner_id, row.visibility, row.source['proposed_by'],
                          row.source['promoted_by']))
        over_file = us.create(self.author, FILE_SKILL, 'x')
        with self.assertRaises(us.SkillRefused):
            us.promote(self.admin, over_file.pk)
        self.assertEqual(self.author.pk, PromptSkill.objects.get(pk=over_file.pk).owner_id)


class PromotionRequestTest(_Accounts):
    """« Demander la promotion », universelle (Fabien, 2026-10-20 : *« des boutons de modération,
    avec notification systématique aux administrateurs pour se rendre directement à la demande,
    l'inspecter, puis la valider ou la refuser »*). Le circuit des demandes d'accès : une ligne
    `ObjectGrant` de niveau `system`, UNE route pour toutes les familles
    (`common:api_promotion_request`), la page de la demande (`/common/requests/<pk>/`) et ses
    boutons dans la cloche ; un ADMINISTRATEUR tranche."""

    def _notes(self, user, kind):
        from wama.common.models import Notification
        return Notification.objects.filter(recipient=user, kind=kind)

    def _request(self, user, **target):
        self.client.force_login(user)
        return self.client.post(reverse('common:api_promotion_request'), json.dumps(target),
                                content_type='application/json')

    def _answer(self, user, grant, accept):
        self.client.force_login(user)
        return self.client.post(reverse('common:access_request_answer', args=[grant.pk]),
                                {'accept': '1' if accept else '0'}).json()

    def _grant(self, row):
        from wama.common.services.access_requests import pending_promotion
        return pending_promotion(row)

    def test_the_author_requests_once_and_every_administrator_is_led_to_the_request(self):
        row = us.create(self.author, FRESH, 'x')
        made = self._request(self.author, registry='skills', pk=row.pk).json()
        grant = self._grant(row)
        self.assertEqual(('system', self.author.pk), (grant.level, grant.beneficiary_id))
        self.assertTrue(made['requested'])
        self.assertEqual(made['url'], reverse('common:access_request', args=[grant.pk]))
        (note,) = self._notes(self.admin, 'promotion_requested')
        self.assertEqual(made['url'], note.url)
        self.assertFalse(self._notes(self.dev, 'promotion_requested').exists())
        again = self._request(self.author, registry='skills', pk=row.pk).json()
        self.assertEqual(made['url'], again['url'], "une demande en attente est rendue, pas recréée")
        us.share(self.author, row.pk, 'public')
        self.assertEqual(404, self._request(self.other, registry='skills', pk=row.pk).status_code)

    def test_an_administrator_inspects_then_accepts_or_declines_and_the_author_is_told(self):
        refused = us.create(self.author, FRESH, 'x')
        self._request(self.author, registry='skills', pk=refused.pk)
        grant = self._grant(refused)
        self.client.force_login(self.admin)
        page = self.client.get(reverse('common:access_request', args=[grant.pk]))
        self.assertContains(page, 'Demande de promotion')
        self.assertContains(page, reverse('common:skills_catalog'))   # « Inspecter l'élément »
        self.assertContains(page, 'data-request-answer="1"')
        self.assertFalse(self._answer(self.dev, grant, False)['done'])
        self.assertTrue(self._answer(self.admin, grant, False)['done'])
        refused.refresh_from_db()
        grant.refresh_from_db()
        self.assertEqual((self.author.pk, 'refused'), (refused.owner_id, grant.state))
        self.assertTrue(self._notes(self.author, 'promotion_refused').exists())
        validated = us.create(self.author, 'zzprov-validated', 'x')
        self._request(self.author, registry='skills', pk=validated.pk)
        grant = self._grant(validated)
        self.assertTrue(self._answer(self.admin, grant, True)['done'])
        validated.refresh_from_db()
        grant.refresh_from_db()
        self.assertEqual((None, 'granted', self.admin.pk),
                         (validated.owner_id, grant.state, grant.granted_by_id))
        self.assertTrue(self._notes(self.author, 'promotion_granted').exists())

    def test_rendering_system_from_the_element_page_grants_the_pending_request(self):
        row = us.create(self.author, FRESH, 'x')
        self._request(self.author, registry='skills', pk=row.pk)
        grant = self._grant(row)
        us.promote(self.admin, row.pk)
        grant.refresh_from_db()
        self.assertEqual('granted', grant.state)

    def test_the_request_page_is_the_requesters_and_the_administrators_only(self):
        row = us.create(self.author, FRESH, 'x')
        self._request(self.author, registry='skills', pk=row.pk)
        url = reverse('common:access_request', args=[self._grant(row).pk])
        self.client.force_login(self.author)
        self.assertContains(self.client.get(url), "d'un administrateur")
        self.client.force_login(self.other)
        self.assertEqual(404, self.client.get(url).status_code)

    def test_the_bell_offers_validate_and_refuse_to_an_administrator_only(self):
        from wama.common.services.notification_panel import notification_actions
        row = us.create(self.author, FRESH, 'x')
        self._request(self.author, registry='skills', pk=row.pk)
        (note,) = self._notes(self.admin, 'promotion_requested')
        self.assertEqual(['Valider', 'Refuser'],
                         [a['label'] for a in notification_actions(note, self.admin)])
        self.assertEqual([], notification_actions(note, self.dev))

    def test_the_same_route_carries_a_charter_theme_and_an_authors_model(self):
        from wama.common.models import UserTheme
        from wama.model_manager.models import AIModel
        theme = UserTheme.objects.create(owner=self.author, name='Labo', base='light',
                                         accent='#2f2a85')
        self.assertTrue(self._request(self.author, registry='themes', pk=theme.pk).json()['requested'])
        model = AIModel.objects.create(model_key='ollama:zzprov-author-llm', name='zz',
                                       model_type='llm', source='ollama', owner=self.author,
                                       visibility='private', is_available=True)
        self.assertTrue(self._request(self.author, registry='models',
                                      key=model.model_key).json()['requested'])
        self.assertTrue(self._answer(self.admin, self._grant(model), True)['done'])
        model.refresh_from_db()
        self.assertEqual((None, 'public', 'ollama'), (model.owner_id, model.visibility, model.source),
                         "la source d'un modèle (un texte) n'est pas une trace de promotion")

    def test_the_pages_offer_the_button_then_the_request(self):
        row = us.create(self.author, FRESH, 'x')
        self.client.force_login(self.author)
        self.assertContains(self.client.get(reverse('common:skills_catalog')),
                            'data-promotion-request="/common/api/promotion/request/"')
        self._request(self.author, registry='skills', pk=row.pk)
        url = reverse('common:access_request', args=[self._grant(row).pk])
        page = self.client.get(reverse('common:skills_catalog'))
        self.assertContains(page, 'Promotion demandée')
        self.assertContains(page, f'href="{url}"')
        self.assertNotContains(page, 'data-promotion-request=')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('common:skills_catalog')), f'href="{url}"')


class PageAndCallersTest(_Accounts):

    def test_the_skills_page_shows_the_account_section_and_the_endpoint_obeys(self):
        us.create(self.author, FRESH, 'MINE ON THE PAGE')
        self.client.force_login(self.author)
        page = self.client.get(reverse('common:skills_catalog'))
        self.assertContains(page, 'id="skMine"')
        self.assertContains(page, 'MINE ON THE PAGE')
        api = reverse('common:skills_manage')
        made = self.client.post(api, json.dumps({'action': 'create', 'name': 'zzprov-other',
                                                 'text': 'y'}), content_type='application/json')
        self.assertTrue(made.json()['success'], made.content)
        pk = made.json()['skill']['pk']
        self.assertEqual(403, self.client.post(api, json.dumps({'action': 'promote', 'pk': pk}),
                                               content_type='application/json').status_code)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('common:skills_catalog')),
                               'MINE ON THE PAGE')

    def test_a_shared_skill_is_on_the_shares_page_on_both_sides_and_unshares_from_there(self):
        """« Mes partages » montre TOUS les partages (Fabien, 2026-10-20) : un élément de
        catalogue partagé y figure par la page commune, pas par une liste à côté."""
        row = us.create(self.author, FRESH, 'x')
        us.share(self.author, row.pk, 'public')
        self.client.force_login(self.author)
        mine = self.client.get(reverse('common:shares'))
        self.assertContains(mine, f'data-registry="skills" data-pk="{row.pk}"')
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('common:shares')), FRESH)
        unshare = reverse('common:api_catalogue_unshare')
        self.assertEqual(404, self.client.post(unshare, {'registry': 'skills',
                                                         'pk': row.pk}).status_code)
        self.client.force_login(self.author)
        self.assertTrue(self.client.post(unshare, {'registry': 'skills',
                                                   'pk': row.pk}).json()['ok'])
        self.assertEqual('private', PromptSkill.objects.get(pk=row.pk).visibility)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('common:shares')), FRESH)

    def test_the_enrich_button_resolves_the_skill_of_the_account(self):
        from wama.common.utils.app_metadata import enrich_prompt_value
        us.create(self.author, FILE_SKILL, 'BUTTON CONSIGNE')
        with mock.patch('wama.common.utils.prompt_enrichment.enrich_generative',
                        return_value='enriched') as enrich:
            enrich_prompt_value('imager', 'prompt', 'a cat', domain='image', user=self.author)
        self.assertEqual('BUTTON CONSIGNE', enrich.call_args.kwargs['skill_text'])

    def test_the_composer_lyrics_are_written_with_the_accounts_skill(self):
        from wama.common.utils.app_metadata import write_lyrics_for
        us.create(self.author, 'composer-lyrics', 'LYRICS CONSIGNE')
        with mock.patch('wama.common.utils.prompt_enrichment.enrich_generative',
                        return_value='[Verse]\nla') as enrich:
            write_lyrics_for('composer', 'prompt', 'a song', user=self.author)
        self.assertEqual('LYRICS CONSIGNE', enrich.call_args.kwargs['skill_text'])
