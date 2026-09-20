"""Le partage d'un asset de médiathèque — mesuré par les VUES, jamais par le queryset.

POURQUOI CE FICHIER. `UserAsset` héritait du mixin de visibilité depuis des mois, mais SANS
`ScopedManager` : `visible_to()` n'existait pas, les deux lectures filtraient par propriétaire, et
un partage ne montrait donc rien — sans la moindre erreur (mesuré le 2026-09-20). C'est le mode de
panne que la doctrine décrit comme le pire des retours : ça n'échoue pas et ça ne marche pas.

Les tests interrogent les ENDPOINTS depuis le compte d'un TIERS : c'est ce qui distingue « la
colonne est écrite » de « la personne voit » (même geste que `common/tests_sharing.py`).

⚠ Identifiants en ANGLAIS, noms de tests compris (décision de Fabien, 2026-09-20) ; commentaires
et docstrings restent en français.
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from wama.common.models import OrgUnit, ScopedVisibility
from wama.common.services.sharing import partager
from wama.common.utils.batch_common import batch_of
from wama.media_library.models import UserAsset


def _asset(user, name='photo', visibility=ScopedVisibility.VIS_PRIVATE, unit=None):
    return UserAsset.objects.create(
        user=user, name=name, asset_type='image',
        file=SimpleUploadedFile(f'{name}.png', b'\x89PNG'),
        visibility=visibility, scope_org_unit=unit,
    )


def _affiliate(user, code):
    profile = user.profile
    profile.org_entity_code = code
    profile.save(update_fields=['org_entity_code'])


class MediaLibrarySharingTest(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user('proprio', password='x')
        self.other = User.objects.create_user('collegue', password='x')
        self.lab = OrgUnit.objects.create(code='LESCOT_ML', name='Lescot', unit_type='labo')
        _affiliate(self.owner, 'LESCOT_ML')
        self.client_other = Client()
        self.client_other.force_login(self.other)

    def _names_seen(self, client, **params):
        response = client.get(reverse('media_library:api_list'), params)
        self.assertEqual(200, response.status_code)
        return [a['name'] for a in response.json()['assets']]

    # ── LE test décisif ────────────────────────────────────────────────────────────────
    def test_asset_shared_with_unit_becomes_visible_to_its_members(self):
        asset = _asset(self.owner, 'le_mien')
        self.assertNotIn('le_mien', self._names_seen(self.client_other, scope='visible'))

        partager(self.owner, asset, ScopedVisibility.VIS_UNIT, org_unit_id=self.lab.id)
        self.assertNotIn('le_mien', self._names_seen(self.client_other, scope='visible'),
                         "hors de l'unité, un partage à l'unité ne doit RIEN montrer")

        _affiliate(self.other, 'LESCOT_ML')
        self.assertIn('le_mien', self._names_seen(self.client_other, scope='visible'))

    def test_counters_say_the_same_as_the_grid(self):
        """Un badge qui compte autre chose que ce que la page affiche est un mensonge muet."""
        _asset(self.owner, 'partagee', ScopedVisibility.VIS_PUBLIC)
        _asset(self.other, 'la_sienne')
        response = self.client_other.get(reverse('media_library:api_counts'),
                                         {'scope': 'visible'})
        self.assertEqual(2, response.json()['counts']['image'])
        self.assertEqual(2, len(self._names_seen(self.client_other, type='image',
                                                 scope='visible')))

    # ── La portée se DEMANDE : le sélecteur des apps ne bouge pas ──────────────────────
    def test_without_requested_scope_only_my_own_assets_are_listed(self):
        """`api_list` sert AUSSI `media-picker.js` (imager, imager_01, avatarizer). Le défaut
        reste « les miens » : élargir en silence ferait entrer l'asset d'autrui dans leur
        sélecteur de fichier."""
        _asset(self.owner, 'publique_d_autrui', ScopedVisibility.VIS_PUBLIC)
        _asset(self.other, 'la_mienne')
        self.assertEqual(['la_mienne'], self._names_seen(self.client_other))

    def test_anonymous_visitor_never_sees_public_assets_of_others(self):
        """⚠ Le compte de service anonyme est une VRAIE ligne `User` : `scoped_visible_q` pose
        `Q(visibility='public')` hors du test d'authentification. Sans garde, un visiteur verrait
        tous les assets publics du parc, avec leurs URL de fichier."""
        _asset(self.owner, 'publique_d_autrui', ScopedVisibility.VIS_PUBLIC)
        self.assertEqual([], self._names_seen(Client(), scope='visible'))

    # ── Le partage est en LECTURE SEULE ────────────────────────────────────────────────
    def test_recipient_can_neither_edit_nor_delete(self):
        asset = _asset(self.owner, 'intouchable', ScopedVisibility.VIS_PUBLIC)
        response = self.client_other.post(
            reverse('media_library:api_edit', args=[asset.id]),
            data='{"name": "vole"}', content_type='application/json')
        self.assertEqual(404, response.status_code)
        response = self.client_other.post(
            reverse('media_library:api_delete', args=[asset.id]))
        self.assertEqual(404, response.status_code)
        asset.refresh_from_db()
        self.assertEqual('intouchable', asset.name)

    def test_card_says_who_owns_the_asset(self):
        """Sans `is_mine`, l'interface offrirait « Modifier » sur l'asset d'un autre, et le
        serveur répondrait « Asset introuvable » — un clic pour rien."""
        _asset(self.owner, 'la_sienne', ScopedVisibility.VIS_PUBLIC)
        _asset(self.other, 'la_mienne')
        response = self.client_other.get(reverse('media_library:api_list'),
                                         {'scope': 'visible'})
        by_name = {a['name']: a for a in response.json()['assets']}
        self.assertFalse(by_name['la_sienne']['is_mine'])
        self.assertEqual('proprio', by_name['la_sienne']['owner'])
        self.assertTrue(by_name['la_mienne']['is_mine'])

    # ── Ce que le service commun fait d'un asset (aucun lot) ───────────────────────────
    def test_common_service_shares_an_asset_without_looking_for_a_batch(self):
        asset = _asset(self.owner, 'sans_lot')
        self.assertIsNone(batch_of(asset), "un asset n'appartient à aucun lot")
        report = partager(self.owner, asset, ScopedVisibility.VIS_PUBLIC)
        asset.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PUBLIC, asset.visibility)
        self.assertIsNone(report['lot'])
        self.assertFalse(report['lot_non_partageable'])

    def test_name_uniqueness_stays_per_user(self):
        """Élargir les gardes d'unicité à ce qui est visible bloquerait la création d'un asset
        dès qu'un homonyme public existe quelque part."""
        _asset(self.owner, 'voix', ScopedVisibility.VIS_PUBLIC)
        response = self.client_other.post(reverse('media_library:api_upload'), {
            'name': 'voix', 'asset_type': 'image',
            'file': SimpleUploadedFile('voix.png', b'\x89PNG'),
        })
        self.assertEqual(200, response.status_code, response.content[:200])

    # ── Le geste passe par la route COMMUNE ────────────────────────────────────────────
    def test_media_library_surface_is_registered(self):
        """`api_partage` résout le modèle par le registre d'aperçu. Sans cet enregistrement,
        l'entrée « Partager… » de la médiathèque répondrait « surface inconnue », en silence."""
        from wama.common.utils.preview_registry import PreviewRegistry
        self.assertIs(UserAsset, PreviewRegistry.get_model('media_library'))

    def test_common_route_shares_an_asset_end_to_end(self):
        asset = _asset(self.owner, 'par_le_commun')
        client_owner = Client()
        client_owner.force_login(self.owner)
        url = reverse('common:api_partage', args=['media_library', 'element', asset.id])

        read = client_owner.get(url)
        self.assertEqual(200, read.status_code)
        self.assertEqual(ScopedVisibility.VIS_PRIVATE, read.json()['etat']['visibility'])
        self.assertTrue(read.json()['portees'])

        write = client_owner.post(url, {'visibility': ScopedVisibility.VIS_PUBLIC})
        self.assertEqual(200, write.status_code, write.content[:200])
        asset.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PUBLIC, asset.visibility)
        self.assertIn('par_le_commun', self._names_seen(self.client_other, scope='visible'))

    def test_foreign_pk_returns_404_not_403(self):
        """Un 403 confirmerait l'existence de l'objet d'un autre (même règle que la file)."""
        asset = _asset(self.owner, 'pas_a_toi')
        response = self.client_other.get(
            reverse('common:api_partage', args=['media_library', 'element', asset.id]))
        self.assertEqual(404, response.status_code)

    # ── La garde de non-retour ─────────────────────────────────────────────────────────
    def test_model_exposes_both_named_paths(self):
        """C'est l'oubli qui a duré des mois : le mixin posé, le manager jamais."""
        self.assertTrue(hasattr(UserAsset.objects, 'visible_to'))
        self.assertTrue(hasattr(UserAsset.objects, 'owned_by'))
