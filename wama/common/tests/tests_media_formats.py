"""Le registre `media_formats` et son accesseur (2026-09-17, demande de Fabien).

POURQUOI. Les trois registres de FORMATS de WAMA (`lecteurs_data`, `formats_export_data`,
`conteneurs_data`) appartenaient tous au monde Data ; la carte des registres laissait donc lire
« le monde Médias ne gouverne pas ses formats », ce qui est faux. Cette entrée DÉRIVÉE le rend
consultable sans changer le domicile du vocabulaire, qui reste une TAXONOMIE
(`WAMA_DATA_WORLD §9quinquies.2` : « le monde Médias n'a rien à changer »).

⚠ Le piège que ces gardes tiennent : `_CAT_OF` est MUTÉ au `ready()` des mondes. Un accesseur
qui en prendrait une capture à l'import afficherait une carte fausse — précisément pour les
natures qui s'ajoutent, c'est-à-dire le cas que la page doit montrer.
"""
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.app_registry import MEDIA_CATEGORIES, media_extensions


class AccesseurDesExtensionsTest(SimpleTestCase):

    def test_toutes_les_natures_sont_rendues_meme_vides(self):
        par_nature = media_extensions()
        self.assertEqual(set(par_nature), set(MEDIA_CATEGORIES),
                         'une nature absente de la carte est invisible de la page')

    def test_les_extensions_sont_sans_point_et_triees(self):
        for nature, exts in media_extensions().items():
            self.assertEqual(exts, sorted(exts), nature)
            for e in exts:
                self.assertFalse(e.startswith('.'), f'{nature} : {e} porte un point')

    def test_les_natures_outillees_le_sont_vraiment(self):
        par_nature = media_extensions()
        for nature in ('image', 'video', 'audio', 'document'):
            self.assertTrue(par_nature[nature], f'{nature} sans aucune extension')

    def test_la_carte_est_LUE_A_L_APPEL_et_non_capturee_a_l_import(self):
        """C'est ainsi qu'un MONDE pousse ses formats au démarrage (`dataset` aujourd'hui).
        Un accesseur figé à l'import ne les verrait jamais."""
        from wama.common.app_registry import _CAT_OF, register_category_extensions
        avant = media_extensions()['3d']
        register_category_extensions('3d', ['wamatestext'])
        try:
            self.assertIn('wamatestext', media_extensions()['3d'],
                          'une extension poussée après import doit apparaître')
        finally:
            _CAT_OF.pop('wamatestext', None)
        self.assertEqual(media_extensions()['3d'], avant, 'état non restauré')

    def test_une_nature_inconnue_est_refusee_a_la_poussee(self):
        from wama.common.app_registry import register_category_extensions
        with self.assertRaises(ValueError):
            register_category_extensions('nature-qui-nexiste-pas', ['zzz'])


class RegistreDesFormatsMediasTest(SimpleTestCase):

    def _registre(self):
        from wama.common.registries import get
        import wama.common.registries_builtin  # noqa: F401  (déclare les registres)
        return get('media_formats')

    def test_il_est_declare_DERIVE_donc_sans_bouton_d_actualisation(self):
        """Un « Actualiser » sur une page qui recalcule à chaque affichage serait un mensonge —
        et `register()` refuse d'ailleurs un rafraîchisseur sur un registre dérivé."""
        from wama.common.registries import DERIVED
        r = self._registre()
        self.assertEqual(r.nature, DERIVED)
        self.assertIsNone(r.refresh)

    def test_sa_cle_est_en_ANGLAIS(self):
        """Règle du 2026-09-14 : tout identifiant de code en anglais, sauf les noms de tests.
        Le LIBELLÉ, lui, reste en français — c'est du texte affiché."""
        r = self._registre()
        self.assertEqual(r.key, 'media_formats')
        self.assertEqual(r.label, 'Formats médias')

    def test_il_compte_les_extensions_et_fiche_chaque_nature(self):
        r = self._registre()
        self.assertEqual(r.count(), sum(len(e) for e in media_extensions().values()))
        fiches = r.entries()
        self.assertEqual(set(fiches), set(MEDIA_CATEGORIES))
        for nature, fiche in fiches.items():
            self.assertEqual(fiche['nombre'], len(fiche['extensions']), nature)
            self.assertIn('sorties_converter', fiche)


class PageDesFormatsMediasTest(TestCase):

    def test_la_page_repond_et_montre_les_natures(self):
        from django.contrib.auth import get_user_model
        self.client.force_login(
            get_user_model().objects.create_user('formats-medias', password='x'))
        reponse = self.client.get(reverse('common:media_formats_catalog'))
        self.assertEqual(reponse.status_code, 200)
        texte = reponse.content.decode('utf-8', 'replace')
        for nature in MEDIA_CATEGORIES:
            self.assertIn(nature, texte, f'{nature} absente de la page')
