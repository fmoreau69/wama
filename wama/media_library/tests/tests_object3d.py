"""Objets 3D en médiathèque — ROADMAP §17ter, trous 2 et 3 (2026-09-13).

Trou 2 : un `.glb` déposé est un `UserAsset(object3d)` dont les `attributes` (nature A′) sont
LUS du fichier par la sonde commune — format, faces, rig, animations — et dont l'aperçu porte un
MIME `model/…`. Trou 3 : la nature déclare son `DataType` inter-mondes, et il existe.

Le témoin est un CUBE glTF 2.0 fabriqué ici, octet par octet (aucune dépendance) : 8 sommets,
12 triangles, 1 maillage, 0 rig, 0 animation — des nombres qu'on peut vérifier à la main.
"""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from wama.common.utils.media_probe import probe_media, probe_object3d


def cube_glb(animated: bool = False) -> bytes:
    """Le cube témoin vit UNE fois, dans la brique nocturne (`ui_smoke._glb_temoin`) — le
    nocturne et ces tests fabriquent le même octet par octet."""
    from wama.common.services.ui_smoke_matching import _glb_temoin
    return _glb_temoin(animated=animated)


class LaSondeLitLaTableDesMatieresTest(TestCase):
    def _fichier(self, octets, nom='cube.glb'):
        import tempfile
        p = tempfile.NamedTemporaryFile(suffix=nom[nom.rfind('.'):], delete=False)
        p.write(octets); p.close()
        return p.name

    def test_un_cube_glb_donne_ses_faces_son_rig_et_ses_animations(self):
        info = probe_object3d(self._fichier(cube_glb()))
        self.assertEqual(info['attributes'], {'format': 'glb', 'polygons': 12, 'rigged': False, 'animations': []})
        self.assertEqual(info['properties'], 'GLB • 1 maillage • 12 faces')
        anime = probe_object3d(self._fichier(cube_glb(animated=True)))
        self.assertEqual(anime['attributes']['animations'], ['tourne'])
        self.assertTrue(anime['attributes']['rigged'])
        self.assertIn('riggé', anime['properties'])

    def test_un_format_sans_table_des_matieres_ne_dit_que_son_format(self):
        self.assertEqual(probe_object3d(self._fichier(b'solid x\nendsolid x\n', 'a.stl')),
                         {'properties': 'STL', 'attributes': {'format': 'stl'}})

    def test_un_glb_corrompu_ne_leve_jamais(self):
        self.assertEqual(probe_object3d(self._fichier(b'pas un glb', 'x.glb'))['attributes'], {'format': 'glb'})

    def test_la_sonde_generique_dispatch_la_categorie_3d(self):
        self.assertEqual(probe_media(self._fichier(cube_glb()))['media_type'], '3d')


class UnDepotDeGlbEstUnAssetObject3dTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('obj3d', password='x')
        self.client = Client()
        self.client.force_login(self.user)

    def test_le_depot_pose_les_attributs_lus_du_fichier_et_un_mime_model(self):
        r = self.client.post(reverse('media_library:api_upload'), {
            'name': 'cube', 'asset_type': 'object3d',
            'file': SimpleUploadedFile('cube.glb', cube_glb(animated=True)),
        })
        self.assertEqual(r.status_code, 200, r.content[:200])
        d = r.json()
        self.assertEqual(d['asset_type'], 'object3d')
        self.assertEqual(d['attributes'], {'format': 'glb', 'polygons': 12, 'rigged': True, 'animations': ['tourne']})
        self.assertEqual(d['mime_type'], 'model/gltf-binary')

    def test_ce_que_l_utilisateur_saisit_prime_sur_la_sonde(self):
        from wama.media_library.models import UserAsset
        from wama.media_library.services import enrich_asset_from_file
        a = UserAsset(user=self.user, name='c2', asset_type='object3d', attributes={'units': 'cm', 'polygons': 999})
        a.file.save('c2.glb', SimpleUploadedFile('c2.glb', cube_glb()), save=False)
        enrich_asset_from_file(a)
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.attributes['polygons'], 999)         # saisi > lu
        self.assertEqual(a.attributes['units'], 'cm')
        self.assertEqual(a.attributes['format'], 'glb')         # lu, non saisi


class LaNatureDeclareSonTypeInterMondesTest(TestCase):
    def test_object3d_pointe_un_DataType_qui_existe(self):
        from wama.common.app_registry import MEDIA_CATEGORIES
        from wama.common.catalog.data_types import known_types
        from wama.media_library.natures import ASSET_NATURES
        types = known_types()      # accesseur unique (2026-09-16)
        for k, n in ASSET_NATURES.items():
            if n.data_type:
                self.assertIn(n.data_type, types, f'{k} déclare un data_type inconnu du monde Data')
        # ⚠ 2026-09-17 : `object3d` ne déclare PLUS de type de donnée. Un objet 3D est un fichier
        # MÉDIA — sa nature est `3d`. Le `data_type` d'une nature reste réservé à ce qui porte
        # vraiment une donnée du monde Data ; il ne sert jamais à créer un jumeau.
        # ⚠ Le défaut du champ est la chaîne VIDE, pas `None` (mesuré : mon `assertIsNone`
        # échouait sur `''`). Ce qui compte est « cette nature ne déclare AUCUN type de donnée ».
        self.assertFalse(ASSET_NATURES['object3d'].data_type,
                         'un objet 3D est un fichier média : il n’a pas de jumeau côté données')
        self.assertEqual(ASSET_NATURES['object3d'].category, '3d')
        self.assertIn('3d', MEDIA_CATEGORIES)
        self.assertNotIn('object_3d', types, 'le jumeau est revenu dans la taxonomie Data')
