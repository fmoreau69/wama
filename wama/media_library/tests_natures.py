"""Construction A′ — les natures d'assets (`natures.py`) : la déclaration, ses dérivations,
la normalisation à la sauvegarde et la porte de compatibilité (`MEDIA_STORAGE_TIERING §9.3`).

L'EMPREINTE du vocabulaire tel qu'il était écrit à la main dans `models.py` avant le
2026-09-13 est figée ici : les dérivations doivent la reproduire à l'identique — le
déplacement d'une déclaration ne change pas ce qu'elle déclare.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase

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
    # ⚠ Les trois natures AUDIO ont quitté l'empreinte le 2026-09-19 (décision Fabien : « pourquoi
    # un bruitage ne peut-il pas être un .aac ? ») : elles acceptent désormais le MÊME jeu, l'union
    # des trois anciens — le rôle se choisit ou se déclare, il ne se déduit plus de l'extension.
    'voice':       ['wav', 'mp3', 'flac', 'ogg', 'm4a', 'aac', 'aiff'],  # wama:redondance-ok — empreinte figée (test)
    'audio_music': ['wav', 'mp3', 'flac', 'ogg', 'm4a', 'aac', 'aiff'],  # wama:redondance-ok — empreinte figée (test)
    'audio_sfx':   ['wav', 'mp3', 'flac', 'ogg', 'm4a', 'aac', 'aiff'],  # wama:redondance-ok — empreinte figée (test)
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


class ResolutionDUneCategorieTest(TestCase):
    """Un puits qui ne dit qu'une catégorie obtient une NATURE — jamais un alias en base."""

    def test_une_nature_revient_telle_quelle(self):
        self.assertEqual(natures.resolve_asset_type('voice'), 'voice')

    def test_une_categorie_donne_sa_nature_par_defaut_declaree(self):
        self.assertEqual(natures.resolve_asset_type('audio'), 'audio_music')
        self.assertEqual(natures.resolve_asset_type('3d'), 'object3d')

    def test_l_extension_departage_dans_la_categorie_le_defaut_en_tete(self):
        self.assertEqual(natures.resolve_asset_type('audio', 'x.mp3'), 'audio_music')
        # Depuis le 2026-09-19 l'extension ne départage PLUS l'audio (jeu commun) : le défaut.
        self.assertEqual(natures.resolve_asset_type('audio', 'x.aiff'), 'audio_music')
        self.assertEqual(natures.resolve_asset_type('image', 'x.gif'), 'image')   # avatar ne l'admet pas

    def test_ni_nature_ni_categorie_est_refuse_avec_le_vocabulaire(self):
        with self.assertRaisesRegex(ValueError, 'audio_music'):
            natures.resolve_asset_type('musique')

    def test_le_defaut_de_chaque_categorie_est_une_nature_de_cette_categorie(self):
        for c, t in natures.CATEGORY_DEFAULT.items():
            self.assertEqual(natures.ASSET_NATURES[t].category, c)


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


class ANatureSaysHowItsValuesAreReadTest(TestCase):
    """Les LIBELLÉS de valeurs vivent avec la déclaration (2026-09-27).

    Avant, ils vivaient dans `common/tts/voice_refs.py` : le menu du synthesizer savait dire
    « Français — Adulte — Homme 1 », et la médiathèque, qui STOCKE ces attributs, les affichait
    nulle part. Deux tables auraient divergé — celle-ci est la seule.
    """

    def test_the_voice_nature_labels_its_values(self):
        schema = natures.attribute_schema('voice')
        self.assertEqual('Langue', schema['language']['label'])
        self.assertEqual('Français', schema['language']['labels']['fr'])
        self.assertEqual('Adulte', schema['age']['labels']['adult'])
        self.assertEqual('Femme', schema['gender']['labels']['female'])

    def test_the_tts_brick_reads_those_labels_and_does_not_hold_its_own(self):
        """⚠ La garde qui compte : la brique TTS ne DÉCLARE plus ces tables, elle les LIT.
        Sans elle, on recopierait la table le jour où l'import gêne, et les deux surfaces
        diraient deux choses de la même voix."""
        import inspect

        from wama.common.tts import voice_refs
        self.assertIs(voice_refs._LANG_CODE_TO_LABEL,
                      natures.ASSET_NATURES['voice'].attributes['language'].labels)
        source = inspect.getsource(voice_refs)
        self.assertNotIn("'fr': 'Français'", source,
                         "la table des langues est redéclarée dans la brique TTS")

    def test_the_age_order_still_goes_child_adult_elderly(self):
        """Contre-épreuve : déplacer les libellés ne doit pas toucher au TRI du menu."""
        from wama.common.tts import voice_refs
        self.assertEqual({'child': 0, 'adult': 1, 'elderly': 2}, voice_refs._AGE_ORDER)

    def test_an_undeclared_nature_attribute_has_no_labels(self):
        """Une nature sans vocabulaire de valeurs rend un dictionnaire vide, jamais `None` :
        le JS y lit `spec.labels[value]` sans garde."""
        schema = natures.attribute_schema('audio_music')
        self.assertEqual({}, schema['bpm']['labels'])
        self.assertEqual('bpm', schema['bpm']['label'])


class ASystemAssetIsNeverDeletedHereTest(TestCase):
    """`delete_asset` REFUSE un asset système, en le disant (2026-09-27).

    Elle lisait `asset.source_app` sans rien vérifier — champ absent de `SystemAsset` : passé
    une voix intégrée, elle levait `AttributeError`. *Une protection par accident n'en est pas
    une* — le message parlait d'un champ manquant, pas de ce qui est interdit.
    """

    def _fichier(self, nom='v.wav'):
        return ContentFile(b'RIFF\0\0\0\0WAVE', name=nom)

    def test_deleting_a_system_asset_is_refused_by_name(self):
        from wama.media_library.services import delete_asset
        s = SystemAsset(name='sys_protege', asset_type='voice')
        s.file.save('sys_protege.wav', self._fichier(), save=False)
        s.save()
        with self.assertRaisesRegex(TypeError, 'SystemAsset'):
            delete_asset(s)
        self.assertTrue(SystemAsset.objects.filter(pk=s.pk).exists())

    def test_a_user_asset_is_still_deleted(self):
        """Contre-épreuve : le refus ne doit pas fermer la porte normale."""
        from wama.media_library.services import delete_asset
        user = get_user_model().objects.create_user('del_t', password='x')
        a = UserAsset(user=user, name='a_supprimer', asset_type='voice')
        a.file.save('a_supprimer.wav', self._fichier('a_supprimer.wav'), save=False)
        a.save()
        delete_asset(a)
        self.assertFalse(UserAsset.objects.filter(pk=a.pk).exists())


class TheCardRendersWhatTheNatureDeclaresTest(SimpleTestCase):
    """Le rendu JS des attributs, exécuté sous V8 avec la VRAIE déclaration (2026-09-27).

    Garde ajoutée en revérifiant la session, pas en s'en souvenant : `assetAttributes` était le
    seul livrable du palier sans attestation. Un `.js` ne casse jamais à la compilation — et
    celui-ci est nourri par `natures_as_json()`, donc le test prouve la CHAÎNE entière :
    déclaration Python → JSON → libellés à l'écran.
    """

    SOURCE = Path(settings.BASE_DIR) / 'wama/media_library/static/media_library/js/media-library.js'

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = self.SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        # Parse du module ENTIER : il touche au DOM au chargement, on ne l'exécute pas.
        self.ctx.eval('(function(){ ' + src + '\n})')
        body = re.search(r'\n    function assetAttributes\(.*?\n    \}\n', src, re.S)
        self.assertIsNotNone(body, '`assetAttributes` a disparu ou changé de forme')
        self.ctx.eval(f'var natures = {json.dumps(natures.natures_as_json())};')
        self.ctx.eval("var currentType = 'voice';")
        self.ctx.eval(body.group(0))

    def _render(self, asset):
        return json.loads(self.ctx.eval(f'JSON.stringify(assetAttributes({json.dumps(asset)}))'))

    def test_a_voice_reads_in_plain_words(self):
        rendu = self._render({'asset_type': 'voice',
                              'attributes': {'language': 'fr', 'age': 'adult',
                                             'gender': 'female', 'variant': 2}})
        self.assertEqual([('Langue', 'Français'), ('Âge', 'Adulte'),
                          ('Genre', 'Femme'), ('Variante', '2')],
                         [(a['label'], a['value']) for a in rendu])

    def test_the_order_is_the_one_DECLARED_not_the_one_stored(self):
        """Deux voix doivent se lire dans le même ordre, quel que soit l'ordre du JSON stocké."""
        rendu = self._render({'asset_type': 'voice',
                              'attributes': {'gender': 'male', 'language': 'en'}})
        self.assertEqual(['Langue', 'Genre'], [a['label'] for a in rendu])

    def test_an_attribute_the_nature_does_not_declare_is_not_shown(self):
        """Contre-épreuve : la clé inconnue est CONSERVÉE en base (`normalize_attributes` ne
        perd rien) mais pas affichée — un libellé brut au milieu de libellés soignés serait pire
        que son absence."""
        rendu = self._render({'asset_type': 'voice',
                              'attributes': {'language': 'fr', 'inconnu': 'xyz'}})
        self.assertEqual(['Langue'], [a['label'] for a in rendu])

    def test_a_nature_without_labels_shows_the_raw_value(self):
        """Une nature sans vocabulaire de valeurs (musique) affiche la valeur telle quelle —
        le rendu est GÉNÉRIQUE, il ne connaît pas les voix."""
        self.ctx.eval("currentType = 'audio_music';")
        rendu = self._render({'asset_type': 'audio_music', 'attributes': {'bpm': 120, 'key': 'Am'}})
        self.assertEqual([('bpm', '120'), ('key', 'Am')],
                         [(a['label'], a['value']) for a in rendu])

    def test_an_asset_without_attributes_renders_nothing(self):
        self.assertEqual([], self._render({'asset_type': 'voice', 'attributes': {}}))
        self.assertEqual([], self._render({'asset_type': 'voice'}))

    def test_the_served_copy_matches_its_source(self):
        served = Path(settings.BASE_DIR) / 'staticfiles/media_library/js/media-library.js'
        if served.exists():
            self.assertEqual(self.SOURCE.read_bytes(), served.read_bytes())
