"""Le partage d'un asset de médiathèque — mesuré par les VUES, jamais par le queryset.

POURQUOI CE FICHIER. `UserAsset` héritait du mixin de visibilité depuis des mois, mais sans
`ScopedManager` : `visible_to()` n'existait pas, et les deux lectures filtraient par
propriétaire. Un partage y était donc écrit et JAMAIS lu — il ne montrait rien, sans la moindre
erreur (mesuré le 2026-09-20). C'est le mode de panne que `PROFILES_PERMISSIONS` décrit comme le
pire des retours : ça n'échoue pas et ça ne marche pas.

Les tests interrogent donc les ENDPOINTS depuis le compte d'un TIERS — c'est ce qui distingue
« la colonne est écrite » de « la personne voit » (même geste que `common/tests_sharing.py`).
"""
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from wama.common.models import OrgUnit, ScopedVisibility
from wama.common.services.sharing import partager
from wama.common.utils.batch_common import batch_of
from wama.media_library.models import UserAsset


def _asset(user, nom='photo', visibility=ScopedVisibility.VIS_PRIVATE, unite=None):
    return UserAsset.objects.create(
        user=user, name=nom, asset_type='image',
        file=SimpleUploadedFile(f'{nom}.png', b'\x89PNG'),
        visibility=visibility, scope_org_unit=unite,
    )


def _affilier(user, code):
    prof = user.profile
    prof.org_entity_code = code
    prof.save(update_fields=['org_entity_code'])


class PartageDeMediathequeTest(TestCase):

    def setUp(self):
        self.a = User.objects.create_user('proprio', password='x')
        self.b = User.objects.create_user('collegue', password='x')
        self.labo = OrgUnit.objects.create(code='LESCOT_ML', name='Lescot', unit_type='labo')
        _affilier(self.a, 'LESCOT_ML')
        self.cb = Client()
        self.cb.force_login(self.b)

    def _noms_vus(self, client, **params):
        r = client.get(reverse('media_library:api_list'), params)
        self.assertEqual(200, r.status_code)
        return [a['name'] for a in r.json()['assets']]

    # ── LE test décisif ────────────────────────────────────────────────────────────────
    def test_un_asset_partage_a_l_unite_devient_visible_pour_ses_membres(self):
        actif = _asset(self.a, 'le_mien')
        self.assertNotIn('le_mien', self._noms_vus(self.cb, scope='visible'))

        partager(self.a, actif, ScopedVisibility.VIS_UNIT, org_unit_id=self.labo.id)
        self.assertNotIn('le_mien', self._noms_vus(self.cb, scope='visible'),
                         "hors de l'unité, un partage à l'unité ne doit RIEN montrer")

        _affilier(self.b, 'LESCOT_ML')
        self.assertIn('le_mien', self._noms_vus(self.cb, scope='visible'))

    def test_le_compteur_dit_la_meme_chose_que_la_grille(self):
        """Un badge qui compte autre chose que ce que la page affiche est un mensonge muet."""
        _asset(self.a, 'partagee', ScopedVisibility.VIS_PUBLIC)
        _asset(self.b, 'la_sienne')
        r = self.cb.get(reverse('media_library:api_counts'), {'scope': 'visible'})
        self.assertEqual(2, r.json()['counts']['image'])
        self.assertEqual(2, len(self._noms_vus(self.cb, type='image', scope='visible')))

    # ── La portée se DEMANDE : le sélecteur des apps ne bouge pas ──────────────────────
    def test_sans_portee_demandee_on_ne_voit_QUE_ses_assets(self):
        """`api_list` sert AUSSI `media-picker.js` (imager, imager_01, avatarizer). Le défaut
        doit donc rester « les miens » : élargir en silence ferait entrer l'asset d'autrui dans
        leur sélecteur de fichier."""
        _asset(self.a, 'publique_d_autrui', ScopedVisibility.VIS_PUBLIC)
        _asset(self.b, 'la_mienne')
        self.assertEqual(['la_mienne'], self._noms_vus(self.cb))

    def test_un_visiteur_non_connecte_ne_voit_pas_les_assets_publics_d_autrui(self):
        """⚠ Le compte de service anonyme est une VRAIE ligne `User` : `scoped_visible_q` pose
        `Q(visibility='public')` hors du test d'authentification. Sans garde, un visiteur verrait
        tous les assets publics du parc, avec leurs URL de fichier."""
        _asset(self.a, 'publique_d_autrui', ScopedVisibility.VIS_PUBLIC)
        self.assertEqual([], self._noms_vus(Client(), scope='visible'))

    # ── Le partage est en LECTURE SEULE ────────────────────────────────────────────────
    def test_le_destinataire_ne_peut_ni_modifier_ni_supprimer(self):
        actif = _asset(self.a, 'intouchable', ScopedVisibility.VIS_PUBLIC)
        r = self.cb.post(reverse('media_library:api_edit', args=[actif.id]),
                         data='{"name": "vole"}', content_type='application/json')
        self.assertEqual(404, r.status_code)
        r = self.cb.post(reverse('media_library:api_delete', args=[actif.id]))
        self.assertEqual(404, r.status_code)
        actif.refresh_from_db()
        self.assertEqual('intouchable', actif.name)

    def test_la_card_dit_a_qui_appartient_l_asset(self):
        """Sans `is_mine`, l'interface offrirait « Modifier » sur l'asset d'un autre, et le
        serveur répondrait « Asset introuvable » — un clic pour rien."""
        _asset(self.a, 'la_sienne', ScopedVisibility.VIS_PUBLIC)
        _asset(self.b, 'la_mienne')
        r = self.cb.get(reverse('media_library:api_list'), {'scope': 'visible'})
        par_nom = {a['name']: a for a in r.json()['assets']}
        self.assertFalse(par_nom['la_sienne']['is_mine'])
        self.assertEqual('proprio', par_nom['la_sienne']['owner'])
        self.assertTrue(par_nom['la_mienne']['is_mine'])

    # ── Ce que le service commun fait d'un asset (aucun lot) ───────────────────────────
    def test_le_service_commun_partage_un_asset_sans_chercher_de_lot(self):
        actif = _asset(self.a, 'sans_lot')
        self.assertIsNone(batch_of(actif), "un asset n'appartient à aucun lot")
        cr = partager(self.a, actif, ScopedVisibility.VIS_PUBLIC)
        actif.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PUBLIC, actif.visibility)
        self.assertIsNone(cr['lot'])
        self.assertFalse(cr['lot_non_partageable'])

    def test_l_unicite_du_nom_reste_PAR_UTILISATEUR(self):
        """Élargir les gardes d'unicité à ce qui est visible bloquerait la création d'un asset
        dès qu'un homonyme public existe quelque part."""
        _asset(self.a, 'voix', ScopedVisibility.VIS_PUBLIC)
        r = self.cb.post(reverse('media_library:api_upload'), {
            'name': 'voix', 'asset_type': 'image',
            'file': SimpleUploadedFile('voix.png', b'\x89PNG'),
        })
        self.assertEqual(200, r.status_code, r.content[:200])

    # ── La garde de non-retour ─────────────────────────────────────────────────────────
    def test_le_modele_expose_les_DEUX_chemins_nommes(self):
        """C'est l'oubli qui a duré des mois : le mixin posé, le manager jamais."""
        self.assertTrue(hasattr(UserAsset.objects, 'visible_to'))
        self.assertTrue(hasattr(UserAsset.objects, 'owned_by'))
