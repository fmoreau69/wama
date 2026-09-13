"""Construction A′ — les natures d'assets (`natures.py`) : la déclaration, ses dérivations,
la normalisation à la sauvegarde et la porte de compatibilité (`MEDIA_STORAGE_TIERING §9.3`).

L'EMPREINTE du vocabulaire tel qu'il était écrit à la main dans `models.py` avant le
2026-09-13 est figée ici : les dérivations doivent la reproduire à l'identique — le
déplacement d'une déclaration ne change pas ce qu'elle déclare.
"""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase

from wama.common.app_registry import MEDIA_CATEGORIES
from wama.media_library import natures
from wama.media_library.models import (ALLOWED_EXTENSIONS, ASSET_TYPE_CATEGORY, ASSET_TYPES,
                                       TYPE_GROUPS, SystemAsset, UserAsset)

#: `models.py` au 2026-09-12 (commit e90c18de) — recopié tel quel, c'est la référence.
ASSET_TYPES_AVANT = [
    ('voice', 'Voix'), ('audio_music', 'Musique'), ('audio_sfx', 'Bruitage'),
    ('image', 'Image'), ('video', 'Vidéo'), ('document', 'Document'),
    ('avatar', 'Avatar'), ('object3d', 'Objet 3D'),
]
ALLOWED_AVANT = {  # empreinte FIGÉE de l'ancien littéral — c'est la recopie qui est le test
    'voice':       ['wav', 'mp3', 'flac', 'ogg', 'm4a'],  # wama:redondance-ok — empreinte figée (test)
    'audio_music': ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'],  # wama:redondance-ok — empreinte figée (test)
    'audio_sfx':   ['mp3', 'wav', 'ogg', 'flac', 'aiff'],  # wama:redondance-ok — empreinte figée (test)
    'image':       ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'],  # wama:redondance-ok — empreinte figée (test)
    'video':       ['mp4', 'webm', 'mov', 'avi', 'mkv'],  # wama:redondance-ok — empreinte figée (test)
    'document':    ['pdf', 'txt', 'docx', 'md', 'csv'],  # wama:redondance-ok — empreinte figée (test)
    'avatar':      ['jpg', 'jpeg', 'png', 'webp'],  # wama:redondance-ok — empreinte figée (test)
    'object3d':    ['glb', 'gltf', 'obj', 'fbx', 'stl', 'ply', 'usdz'],  # wama:redondance-ok — empreinte figée (test)
}
CATEGORIE_AVANT = {
    'voice': 'audio', 'audio_music': 'audio', 'audio_sfx': 'audio',
    'image': 'image', 'avatar': 'image', 'video': 'video',
    'document': 'document', 'object3d': '3d',
}


class LaDeclarationReproduitLesTablesDAvantTest(TestCase):
    def test_ASSET_TYPES_derive_a_l_identique_ordre_compris(self):
        self.assertEqual(ASSET_TYPES, ASSET_TYPES_AVANT)

    def test_ALLOWED_EXTENSIONS_derive_a_l_identique(self):
        self.assertEqual(ALLOWED_EXTENSIONS, ALLOWED_AVANT)

    def test_ASSET_TYPE_CATEGORY_derive_a_l_identique(self):
        self.assertEqual(ASSET_TYPE_CATEGORY, CATEGORIE_AVANT)

    def test_TYPE_GROUPS_suit_et_connait_le_3d(self):
        self.assertEqual(TYPE_GROUPS['audio'], ['voice', 'audio_music', 'audio_sfx'])
        self.assertEqual(TYPE_GROUPS['3d'], ['object3d'])

    def test_chaque_nature_se_rattache_a_une_categorie_du_vocabulaire_commun(self):
        for k, n in natures.ASSET_NATURES.items():
            self.assertIn(n.category, MEDIA_CATEGORIES, k)

    def test_la_page_recoit_TOUTES_les_natures_avec_icone_et_formats(self):
        j = natures.natures_as_json()
        self.assertEqual(list(j), [t for t, _ in ASSET_TYPES])
        for k, v in j.items():
            self.assertTrue(v['icon'].startswith('fa-'), k)
            self.assertTrue(v['extensions'], k)
        self.assertEqual(j['object3d']['icon'], 'fa-cube')      # l'entrée que le JS n'avait pas
        self.assertEqual(set(j['voice']['attributes']), {'language', 'age', 'gender', 'variant'})


class NormalisationTest(TestCase):
    def test_coerce_au_type_declare_et_garde_les_cles_inconnues(self):
        out = natures.normalize_attributes(
            'voice', {'language': ' fr ', 'variant': '2', 'age': 'adult', 'source': 'ljspeech'})
        self.assertEqual(out, {'language': 'fr', 'variant': 2, 'age': 'adult', 'source': 'ljspeech'})

    def test_une_valeur_hors_du_vocabulaire_declare_est_REFUSEE(self):
        with self.assertRaises(ValueError):
            natures.normalize_attributes('voice', {'age': 'senior'})

    def test_un_type_qui_n_est_pas_un_entier_est_refuse_avec_le_mot_juste(self):
        with self.assertRaisesRegex(ValueError, 'object3d.polygons'):
            natures.normalize_attributes('object3d', {'polygons': 'beaucoup'})

    def test_vide_ou_None_retire_la_cle(self):
        self.assertEqual(natures.normalize_attributes('voice', {'language': '', 'age': None}), {})

    def test_bool_et_liste_depuis_une_saisie_texte(self):
        out = natures.normalize_attributes('object3d', {'rigged': 'true', 'animations': 'idle, walk'})
        self.assertEqual(out, {'rigged': True, 'animations': ['idle', 'walk']})

    def test_un_asset_type_hors_vocabulaire_est_une_KeyError_avant_toute_base(self):
        with self.assertRaises(KeyError):
            natures.normalize_attributes('audio', {})

    def test_is_canonical_attribute(self):
        self.assertTrue(natures.is_canonical_attribute('voice', 'language'))
        self.assertFalse(natures.is_canonical_attribute('voice', 'bpm'))
        self.assertFalse(natures.is_canonical_attribute('inconnu', 'language'))


class LaPorteDeCompatibiliteTest(TestCase):
    """Trois états, une raison qui nomme ce qui manque — jamais « caché »."""

    def test_categorie_puis_attributs_requis(self):
        spec = natures.AssetSpec(category='3d', require={'units': 'm', 'rigged': False})
        self.assertEqual(natures.asset_accepts(spec, 'voice', {})[0], natures.INCOMPATIBLE)
        etat, raison = natures.asset_accepts(spec, 'object3d', {'units': 'cm', 'rigged': False})
        self.assertEqual(etat, natures.INCOMPATIBLE)
        self.assertIn('units', raison)
        self.assertEqual(natures.asset_accepts(spec, 'object3d', {'units': 'm', 'rigged': False}),
                         (natures.COMPATIBLE, ''))

    def test_un_attribut_manquant_est_nomme(self):
        spec = natures.AssetSpec(asset_types=('voice',), require={'language': ('fr', 'en')})
        etat, raison = natures.asset_accepts(spec, 'voice', {})
        self.assertEqual(etat, natures.INCOMPATIBLE)
        self.assertIn('language', raison)

    def test_prefere_donne_un_AVERTISSEMENT_pas_un_refus(self):
        spec = natures.AssetSpec(asset_types=('voice',), prefer={'language': 'fr'})
        etat, raison = natures.asset_accepts(spec, 'voice', {'language': 'de'})
        self.assertEqual(etat, natures.WARNING)
        self.assertIn("'de'", raison)

    def test_un_type_inconnu_est_incompatible_avec_raison(self):
        self.assertEqual(natures.asset_accepts(natures.AssetSpec(), 'audio', {})[0],
                         natures.INCOMPATIBLE)


class LaSauvegardeNormaliseTest(TestCase):
    """Le `save()` des deux modèles passe par la normalisation — et refuse un alias."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('natures_t', password='x')

    def _fichier(self, nom='v.wav'):
        return ContentFile(b'RIFF\0\0\0\0WAVE', name=nom)

    def test_UserAsset_coerce_ses_attributs_au_save(self):
        a = UserAsset(user=self.user, name='v', asset_type='voice',
                      attributes={'language': 'fr', 'variant': '1'})
        a.file.save('v.wav', self._fichier(), save=False)
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.attributes, {'language': 'fr', 'variant': 1})

    def test_update_fields_partiel_ecrit_quand_meme_les_attributs_normalises(self):
        a = UserAsset(user=self.user, name='w', asset_type='voice')
        a.file.save('w.wav', self._fichier('w.wav'), save=False)
        a.save()
        a.attributes = {'variant': '3'}
        a.save(update_fields=['mime_type'])
        a.refresh_from_db()
        self.assertEqual(a.attributes, {'variant': 3})

    def test_un_asset_type_qui_est_une_CATEGORIE_est_refuse(self):
        a = UserAsset(user=self.user, name='x', asset_type='audio')
        a.file.save('x.mp3', self._fichier('x.mp3'), save=False)
        with self.assertRaisesRegex(ValueError, "hors du vocabulaire"):
            a.save()

    def test_SystemAsset_aussi(self):
        s = SystemAsset(name='sys_v', asset_type='voice', attributes={'age': 'child', 'gender': 'female'})
        s.file.save('s.wav', self._fichier('s.wav'), save=False)
        s.save()
        s.refresh_from_db()
        self.assertEqual(s.attributes, {'age': 'child', 'gender': 'female'})
        with self.assertRaises(ValueError):
            s.attributes = {'gender': 'robot'}
            s.save()
