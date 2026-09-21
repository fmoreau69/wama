"""Les chemins nommés d'accès aux objets partageables (`common/utils/scoping.py`).

`listable_by` (2026-09-22) : la règle « le compte de service anonyme ne liste que ce qu'il
possède » vivait en deux exemplaires, écrits le même jour par la même session. Elle a un
domicile, et une garde empêche qu'elle en retrouve un second.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import ast
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

from wama.common.models import ScopedVisibility
from wama.common.utils.scoping import listable_by
from wama.media_library.models import UserAsset


class ListableByTest(TestCase):

    def setUp(self):
        from wama.accounts.views import get_or_create_anonymous_user
        self.owner = User.objects.create_user('scope_owner', password='x')
        self.other = User.objects.create_user('scope_other', password='x')
        self.anonymous = get_or_create_anonymous_user()
        UserAsset.objects.create(user=self.owner, name='public_asset', asset_type='image',
                                 file=SimpleUploadedFile('p.png', b'\x89PNG'),
                                 visibility=ScopedVisibility.VIS_PUBLIC)

    def _names(self, user):
        return sorted(listable_by(UserAsset.objects.all(), user).values_list('name', flat=True))

    def test_a_person_lists_what_is_public(self):
        self.assertEqual(['public_asset'], self._names(self.other))

    def test_the_anonymous_account_lists_only_what_it_owns(self):
        """Le compte anonyme est une VRAIE ligne `User` : sans la règle, tout visiteur hériterait
        des éléments publics du parc."""
        self.assertEqual([], self._names(self.anonymous))
        UserAsset.objects.create(user=self.anonymous, name='anonymous_own', asset_type='image',
                                 file=SimpleUploadedFile('a.png', b'\x89PNG'))
        self.assertEqual(['anonymous_own'], self._names(self.anonymous))


class SingleHomeTest(SimpleTestCase):

    def test_the_anonymous_rule_has_a_single_home(self):
        """Un fichier qui compare au nom du compte anonyme ET appelle `visible_to` recopie la
        règle. Relevé par AST (appels et noms réels), pas par motif texte."""
        root = Path(settings.BASE_DIR) / 'wama'
        offenders = []
        for path in root.rglob('*.py'):
            if 'tests' in path.name or 'migrations' in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            calls = {n.func.attr for n in ast.walk(tree)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            if 'ANONYMOUS_USERNAME' in names and 'visible_to' in calls:
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(['common/utils/scoping.py'],
                         sorted(p.replace('\\', '/') for p in offenders))
