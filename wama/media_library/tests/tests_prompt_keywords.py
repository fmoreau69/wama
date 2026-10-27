"""Mots-clés de prompt : ce qu'un mot-clé DIT de lui-même au navigateur.

Le payload de `PromptKeyword.to_dict()` n'avait aucune garde, et sa clé de portée s'appelait
`shared` — alors que « partagé » désigne dans WAMA un geste précis (quelqu'un donne accès à SON
élément, avec une ligne de partage, un droit, une portée : `WAMA_COLLABORATION §1`). Un mot-clé
du tronc commun n'a jamais été partagé par personne : il n'a simplement pas de propriétaire.
Renommée `common` le 2026-09-26.

Ce que ces gardes tiennent, c'est la chaîne ENTIÈRE — producteur et lecteur : la valeur ne sert
qu'à une chose, décider si l'utilisateur peut SUPPRIMER le mot-clé. Une clé renommée d'un seul
côté rendrait `undefined` côté navigateur, donc « falsy », donc une croix de suppression sur les
mots-clés communs — un bouton qui échouerait en silence, jamais une erreur.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from ..models import PromptKeyword

User = get_user_model()

CHIPS_SOURCE = Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-prompt-chips.js'
CHIPS_SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-prompt-chips.js'


class PromptKeywordScopeKeyTest(TestCase):

    def test_a_keyword_without_an_owner_says_it_belongs_to_the_common_trunk(self):
        keyword = PromptKeyword.objects.create(category='style', text='cinematic')
        payload = keyword.to_dict()
        self.assertIs(True, payload['common'])
        self.assertNotIn('shared', payload,
                         'le mot « partagé » a un autre sens dans WAMA — il ne revient pas')

    def test_a_personal_keyword_says_it_is_not_common(self):
        owner = User.objects.create_user('keyword_owner', password='x')
        payload = PromptKeyword.objects.create(owner=owner, category='style',
                                               text='aquarelle').to_dict()
        self.assertIs(False, payload['common'])


class PromptChipsReadTheSameKeyTest(SimpleTestCase):

    def test_the_brick_reads_the_key_the_server_sends(self):
        """Les DEUX copies : c'est `staticfiles/` qui est servi."""
        for path in (CHIPS_SOURCE, CHIPS_SERVED):
            if not path.exists():
                continue
            source = path.read_text(encoding='utf-8')
            self.assertIn('kw.common', source, path.name)
            self.assertNotIn('kw.shared', source, path.name)


class KeywordProvenanceTest(TestCase):
    """Les mots-clés suivent la route de tout ce qui entre dans WAMA (`ROADMAP §29`, 2026-10-27,
    Fabien : « aligne aussi les mots-clés ») — celle des skills de prompt : le tronc commun est
    système, un mot-clé d'auteur naît privé, se partage, se COPIE (il ne s'impose à personne
    sous un prompt), un administrateur seul le rend système."""

    @classmethod
    def setUpTestData(cls):
        from wama.accounts.models import UserProfile
        cls.author = User.objects.create_user('kw_author', password='x')
        cls.other = User.objects.create_user('kw_other', password='x')
        cls.admin = User.objects.create_user('kw_admin', password='x')
        UserProfile.objects.update_or_create(user=cls.admin, defaults={'account_tier': 'admin'})
        cls.admin = User.objects.get(pk=cls.admin.pk)
        cls.system = PromptKeyword.objects.create(category='style', text='cinématique',
                                                  visibility=PromptKeyword.VIS_PUBLIC)

    def test_the_palette_offers_the_system_and_ones_own_never_a_share(self):
        from .. import keywords
        mine = keywords.create(self.author, 'aquarelle', 'style')
        keywords.share(self.author, mine.pk, 'public')
        self.assertEqual({'cinématique', 'aquarelle'},
                         {k.text for k in keywords.palette_keywords(self.author)})
        self.assertEqual({'cinématique'}, {k.text for k in keywords.palette_keywords(self.other)})
        # …mais la GESTION le montre, avec ce que l'autre compte peut en faire.
        seen = {k.text: keywords.as_dict(k, self.other) for k in keywords.catalogue_rows(self.other)}
        self.assertEqual('partagé par kw_author', seen['aquarelle']['provenance'])
        self.assertTrue(seen['aquarelle']['can_copy'])
        self.assertFalse(seen['cinématique']['can_copy'], 'copier le tronc commun le doublerait')
        copy = keywords.copy(self.other, mine.pk)
        self.assertEqual((self.other.pk, 'private', 'kw_author:aquarelle'),
                         (copy.owner_id, copy.visibility, copy.source['copied_from']))
        self.assertIn('aquarelle', {k.text for k in keywords.palette_keywords(self.other)})

    def test_an_administrator_promotes_and_nobody_deletes_the_trunk(self):
        from .. import keywords
        mine = keywords.create(self.author, 'heure bleue', 'light')
        with self.assertRaises(keywords.KeywordRefused):
            keywords.promote(self.other, mine.pk)
        keywords.promote(self.admin, mine.pk)
        mine.refresh_from_db()
        self.assertEqual((None, 'public', 'kw_author'),
                         (mine.owner_id, mine.visibility, mine.source['proposed_by']))
        self.assertIn('heure bleue', {k.text for k in keywords.palette_keywords(self.other)})
        with self.assertRaises(keywords.KeywordRefused):
            keywords.delete(self.admin, self.system.pk)
        self.assertTrue(PromptKeyword.objects.filter(pk=self.system.pk).exists())

    def test_the_management_endpoints_say_the_facts_and_obey(self):
        import json
        from django.urls import reverse
        from .. import keywords
        mine = keywords.create(self.author, 'néon', 'light')
        self.client.force_login(self.author)
        data = self.client.get(reverse('media_library:api_prompt_keywords') + '?manage=1').json()
        self.assertEqual('prompt_keywords', data['registry'])
        light = {k['text']: k for k in data['categories']['light']['items']}
        self.assertEqual('à moi', light['néon']['provenance'])
        self.assertTrue(light['néon']['can_share'])
        api = reverse('media_library:api_prompt_keyword_manage')
        shared = self.client.post(api, json.dumps({'action': 'share', 'pk': mine.pk, 'scope': 'public'}),
                                  content_type='application/json')
        self.assertTrue(shared.json()['success'], shared.content)
        self.assertEqual(403, self.client.post(api, json.dumps({'action': 'promote', 'pk': mine.pk}),
                                               content_type='application/json').status_code)
        # La palette, elle, garde sa forme d'avant : pas de faits, pas de portées.
        palette = self.client.get(reverse('media_library:api_prompt_keywords')).json()
        self.assertNotIn('scopes', palette)
        self.assertNotIn('provenance', palette['categories']['light']['items'][0])

    def test_a_shared_keyword_is_on_the_shares_page(self):
        from django.urls import reverse
        from .. import keywords
        mine = keywords.create(self.author, 'onirique', 'mood')
        keywords.share(self.author, mine.pk, 'public')
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('common:shares')), 'onirique')

    def test_the_seeded_trunk_is_system_and_public(self):
        from django.core.management import call_command
        import io
        call_command('seed_prompt_keywords', stdout=io.StringIO())
        self.assertFalse(PromptKeyword.objects.filter(owner__isnull=True)
                         .exclude(visibility=PromptKeyword.VIS_PUBLIC).exists())

    def test_the_glossary_still_reads_the_palette(self):
        from wama.common.utils.app_metadata import detected_keywords
        from .. import keywords
        keywords.create(self.author, 'aquarelle', 'style')
        self.assertEqual({'cinématique', 'aquarelle'},
                         set(detected_keywords('Une scène cinématique, aquarelle.', self.author)))
        self.assertEqual(['cinématique'], detected_keywords('Une scène cinématique, aquarelle.', self.other))


class PromptChipsManageModeTest(SimpleTestCase):
    """La brique servie se PARSE (V8) et son mode gestion lit les faits du serveur."""

    def test_the_served_brick_parses_and_asks_for_the_management_view(self):
        from py_mini_racer import MiniRacer
        for path in (CHIPS_SOURCE, CHIPS_SERVED):
            if not path.exists():
                continue
            source = path.read_text(encoding='utf-8')
            MiniRacer().eval('(function(){' + source + '})')
            for fact in ("'manage=1'", 'kw.can_delete', 'kw.can_share', 'kw.can_copy',
                         'kw.can_promote', 'data-promotion-request'):
                self.assertIn(fact, source, path.name)
