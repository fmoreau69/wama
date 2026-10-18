"""À QUI EST un manifeste — l'étape 2 du chantier PROVENANCE (`ROADMAP §29`, 2026-10-18).

CE QUE CES GARDES TIENNENT :
  1. la traduction enveloppe ↔ ligne de registre (`manifests/ownership.py`) fait l'aller-retour
     sans rien perdre — le `write_back` des fonctions perdait la portée PROJET ;
  2. le filtre commun (`scoped_visible_q`) lit les portées de `Manifest`, écrites en CODES : un
     manifeste partagé à une unité ou à un projet est vu de ses membres, et de personne d'autre ;
  3. seul un élément SYSTÈME entre au corpus versionné, publié avec le dépôt : un manifeste qui a
     un propriétaire est refusé à l'export, et aucun fichier du corpus n'en porte.
"""
import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from wama.common.manifests.builtin.function import extract_function, write_back_function
from wama.common.manifests.ownership import envelope_of, is_system, row_fields
from wama.common.models import Manifest, OrgUnit, Project, ProjectMembership, UserFunction

FUNCTION_KEY = 'ownership_test_function'


def _affiliate(user, code):
    profile = user.profile
    profile.org_entity_code = code
    profile.save(update_fields=['org_entity_code'])


class OwnershipRoundTripTest(TestCase):

    def setUp(self):
        self.owner = get_user_model().objects.create_user('ownership_owner', password='x')
        self.unit = OrgUnit.objects.create(code='OWNERSHIP_LAB', name='Lab', unit_type='labo')
        self.project = Project.objects.create(code='OWNERSHIP_PRJ', name='Prj')

    def test_a_row_and_its_envelope_say_the_same_thing(self):
        fn = UserFunction.objects.create(key=FUNCTION_KEY, name='F', owner=self.owner,
                                         visibility='unit', scope_org_unit=self.unit,
                                         scope_project=self.project)
        envelope = envelope_of(fn)
        self.assertEqual({'owner': 'ownership_owner', 'visibility': 'unit',
                          'scope_org_unit': 'OWNERSHIP_LAB', 'scope_project': 'OWNERSHIP_PRJ'},
                         envelope)
        back = row_fields(envelope)
        self.assertEqual((self.owner, 'unit', self.unit, self.project, {}),
                         tuple(back[k] for k in ('owner', 'visibility', 'scope_org_unit',
                                                 'scope_project', 'unresolved')))

    def test_an_unknown_name_is_reported_never_turned_into_the_system(self):
        back = row_fields({'owner': 'nobody_here', 'scope_project': 'NO_SUCH_PRJ'})
        self.assertIsNone(back['owner'])
        self.assertEqual({'owner': 'nobody_here', 'scope_project': 'NO_SUCH_PRJ'},
                         back['unresolved'])
        self.assertFalse(is_system({'owner': 'nobody_here'}))

    def test_the_function_write_back_keeps_the_project_scope(self):
        """Il résolvait l'unité et oubliait le projet : un aller-retour perdait la portée."""
        manifest = {'manifest_kind': 'function', 'key': FUNCTION_KEY, 'name': 'F',
                    'owner': 'ownership_owner', 'visibility': 'project',
                    'scope_project': 'OWNERSHIP_PRJ', 'body': {'binding': 'user'}}
        self.assertTrue(write_back_function(manifest, apply=True).get('created'))
        fn = UserFunction.objects.get(key=FUNCTION_KEY)
        self.assertEqual(('project', self.project), (fn.visibility, fn.scope_project))
        self.assertEqual('OWNERSHIP_PRJ', extract_function(FUNCTION_KEY)['scope_project'])


class ManifestScopesAreReadByTheCommonFilterTest(TestCase):

    def setUp(self):
        users = get_user_model().objects
        self.author = users.create_user('scope_author', password='x')
        self.lab_member = users.create_user('scope_lab_member', password='x')
        self.project_member = users.create_user('scope_project_member', password='x')
        self.stranger = users.create_user('scope_stranger', password='x')
        OrgUnit.objects.create(code='SCOPE_LAB', name='Lab', unit_type='labo')
        _affiliate(self.lab_member, 'SCOPE_LAB')
        project = Project.objects.create(code='SCOPE_PRJ', name='Prj')
        ProjectMembership.objects.create(project=project, user=self.project_member)
        rows = {'private': {}, 'unit': {'scope_org_unit': 'SCOPE_LAB'},
                'project': {'scope_project': 'SCOPE_PRJ'}}
        for visibility, scope in rows.items():
            Manifest.objects.create(manifest_kind='model', key=f'scope:{visibility}',
                                    name=visibility, owner=self.author,
                                    visibility=visibility, **scope)
        Manifest.objects.create(manifest_kind='model', key='scope:system', name='system',
                                visibility='public')

    def _seen(self, user):
        return sorted(Manifest.objects.filter(key__startswith='scope:')
                      .visible_to(user, owner_field='owner').values_list('key', flat=True))

    def test_each_account_sees_what_its_scopes_open_and_nothing_else(self):
        self.assertEqual(['scope:private', 'scope:project', 'scope:system', 'scope:unit'],
                         self._seen(self.author))
        self.assertEqual(['scope:system', 'scope:unit'], self._seen(self.lab_member))
        self.assertEqual(['scope:project', 'scope:system'], self._seen(self.project_member))
        self.assertEqual(['scope:system'], self._seen(self.stranger))


class CorpusAdmitsOnlySystemElementsTest(TestCase):

    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.out, True)

    def test_an_owned_function_never_enters_the_corpus(self):
        """Écart 3 : une fonction d'utilisateur s'exportait à la clé explicite, dans un dossier
        publié avec le dépôt public. `--force` n'y change rien."""
        owner = get_user_model().objects.create_user('corpus_owner', password='x')
        UserFunction.objects.create(key=FUNCTION_KEY, name='F', owner=owner)
        stdout = StringIO()
        call_command('manifest_export', FUNCTION_KEY, kind='function', out=str(self.out),
                     force=True, stdout=stdout)
        self.assertEqual([], list(self.out.iterdir()))
        self.assertIn('seul un élément système', stdout.getvalue())


class VersionedCorpusIsSystemOnlyTest(SimpleTestCase):

    def test_no_file_of_the_versioned_corpus_has_an_owner(self):
        owned = []
        for path in sorted((Path(settings.BASE_DIR) / 'manifests').rglob('*.json')):
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if not is_system(manifest):
                owned.append(f"{path.name} → {manifest.get('owner')!r}")
        self.assertEqual([], owned)
