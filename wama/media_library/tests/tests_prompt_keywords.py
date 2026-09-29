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
        payload = PromptKeyword.objects.create(user=owner, category='style',
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
