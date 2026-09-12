"""
Gardes de la brique commune « ranger une sortie d'app dans ma médiathèque »
(`media_library/services.py`, 2026-09-11).

Ce qu'elles protègent, et qui ne se voit pas à l'exécution locale :
  • le geste est GÉNÉRIQUE — il lit le schéma canonique, donc il ne doit contenir AUCUNE
    connaissance d'app. Un test qui ne passerait que sur composer ne prouverait pas ça ;
  • il ne DEVINE pas le rôle d'un asset (un .mp3 peut être voix/musique/bruitage) ;
  • il ne CONSTRUIT aucun chemin — c'est `upload_to` qui décide du domicile. C'est ce qui le
    rend solidaire de la refonte des chemins utilisateur (chiffrement à venir) au lieu de la
    contredire, et c'est donc ce qu'il faut attester.
"""
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase

from wama.media_library.models import UserAsset
from wama.media_library.services import candidate_asset_types, export_item_to_library


def _utilisateur(nom, role='communication'):
    """Utilisateur qui FRANCHIT le portier d'app (rôle `communication` = composer, mesuré dans
    `DEFAULT_APP_ACCESS`), jamais `is_superuser` — neutraliser le portier rendrait aveugle aux
    régressions de gating. ⚠ Mesuré ici : sans rôle, la route composer répond **302** et le test
    de dépréciation lit une redirection là où il croit lire un refus métier."""
    from django.contrib.auth.models import Group

    from wama.accounts.permissions import GROUP_PREFIX
    user = get_user_model().objects.create_user(username=nom, password='x')
    if role:
        groupe, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
        user.groups.add(groupe)
    return user


def _generation(user, nom_fichier='piste.mp3', avec_sortie=True):
    """Un élément composer avec une vraie sortie sur disque (MEDIA_ROOT jetable du runner)."""
    from wama.composer.models import ComposerGeneration
    gen = ComposerGeneration.objects.create(user=user, prompt='un test', model='musicgen')
    if avec_sortie:
        gen.audio_output.save(nom_fichier, ContentFile(b'\x00\x01FAUXAUDIO'), save=True)
    return gen


class CandidatsDeRoleTest(TestCase):
    def test_un_mp3_a_PLUSIEURS_roles_possibles(self):
        """C'est tout le motif du refus de deviner : l'extension ne dit pas le rôle."""
        self.assertEqual(
            set(candidate_asset_types('x.mp3')), {'voice', 'audio_music', 'audio_sfx'})

    def test_un_glb_n_en_a_qu_UN(self):
        self.assertEqual(candidate_asset_types('scene.glb'), ['object3d'])

    def test_une_extension_inconnue_n_en_a_AUCUN(self):
        self.assertEqual(candidate_asset_types('archive.zip'), [])
        self.assertEqual(candidate_asset_types('sans_extension'), [])


class ExportTest(TestCase):
    def setUp(self):
        self.moi = _utilisateur('exp1')
        self.autre = _utilisateur('exp2')

    def test_refuse_de_DEVINER_quand_plusieurs_roles_conviennent(self):
        """Et il REND les candidats : une erreur qui n'aide pas à se corriger est un cul-de-sac
        pour un menu comme pour l'assistant."""
        gen = _generation(self.moi)
        out = export_item_to_library(self.moi, 'composer', gen.pk)
        self.assertIn('error', out)
        self.assertEqual(set(out['candidates']), {'voice', 'audio_music', 'audio_sfx'})
        self.assertEqual(UserAsset.objects.filter(user=self.moi).count(), 0)

    def test_range_quand_le_role_est_FOURNI(self):
        gen = _generation(self.moi)
        out = export_item_to_library(self.moi, 'composer', gen.pk, asset_type='audio_music')
        self.assertNotIn('error', out, out)
        asset = UserAsset.objects.get(pk=out['asset_id'])
        self.assertEqual(asset.user, self.moi)
        self.assertEqual(asset.asset_type, 'audio_music')

    def test_ne_CONSTRUIT_aucun_chemin_le_domicile_vient_de_upload_to(self):
        """🔴 La garde qui distingue cette brique des 3 copies qu'elle remplace. La version
        composer fabriquait `media_library/<uid>/audio` à la main ; ici le chemin doit être
        celui que `UploadToUserPath` décide — donc porter l'id de l'utilisateur sans qu'aucune
        ligne de ce module ne l'ait écrit. Si quelqu'un réintroduit un `os.path.join`, le
        chemin cessera de suivre la refonte des domiciles et ce test le dira."""
        gen = _generation(self.moi)
        out = export_item_to_library(self.moi, 'composer', gen.pk, asset_type='audio_music')
        chemin = UserAsset.objects.get(pk=out['asset_id']).file.name
        self.assertIn('media_library', chemin)
        self.assertIn(str(self.moi.id), chemin)

    def test_refuse_un_role_NON_admis_pour_l_extension(self):
        gen = _generation(self.moi)
        out = export_item_to_library(self.moi, 'composer', gen.pk, asset_type='image')
        self.assertIn('error', out)
        self.assertIn('candidates', out)

    def test_refuse_l_element_d_un_AUTRE_utilisateur(self):
        gen = _generation(self.autre)
        out = export_item_to_library(self.moi, 'composer', gen.pk, asset_type='audio_music')
        self.assertEqual(out.get('error'), 'forbidden')
        self.assertEqual(UserAsset.objects.count(), 0)

    def test_dit_qu_il_n_y_a_RIEN_a_ranger_quand_la_sortie_manque(self):
        """Un élément en attente n'a pas de résultat : le geste doit le DIRE, pas échouer."""
        gen = _generation(self.moi, avec_sortie=False)
        out = export_item_to_library(self.moi, 'composer', gen.pk, asset_type='audio_music')
        self.assertIn('error', out)
        self.assertIn('résultat', out['error'])

    def test_refuse_un_doublon_de_nom_et_de_role(self):
        """⚠ Le nom par défaut est le STEM du fichier, pas son chemin (ma 1ʳᵉ version de ce test
        comparait un chemin complet à un stem : il ne pouvait donc jamais voir de doublon)."""
        gen = _generation(self.moi)
        premier = export_item_to_library(self.moi, 'composer', gen.pk,
                                         asset_type='audio_music', name='ma piste')
        self.assertNotIn('error', premier, premier)
        gen2 = _generation(self.moi)
        out = export_item_to_library(self.moi, 'composer', gen2.pk,
                                     asset_type='audio_music', name='ma piste')
        self.assertIn('error', out)
        self.assertEqual(UserAsset.objects.filter(user=self.moi, name='ma piste').count(), 1)

    def test_pose_le_drapeau_d_app_quand_elle_en_a_un(self):
        """`exported_to_library` existe sur composer et nulle part ailleurs : la brique le pose
        SANS l'exiger des autres apps — sinon le geste ne serait pas générique."""
        gen = _generation(self.moi)
        export_item_to_library(self.moi, 'composer', gen.pk, asset_type='audio_music')
        gen.refresh_from_db()
        self.assertTrue(gen.exported_to_library)

    def test_app_inconnue_et_element_absent_sans_lever(self):
        self.assertIn('error', export_item_to_library(self.moi, 'pasunapp', 1))
        self.assertIn('error', export_item_to_library(self.moi, 'composer', 10 ** 9))

    def test_refuse_l_anonyme(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIn('error', export_item_to_library(AnonymousUser(), 'composer', 1))


class VueExportTest(TestCase):
    """La ROUTE commune — c'est elle que le menu « … » appelle, donc c'est elle qu'il faut
    garder, pas seulement la fonction qu'elle enveloppe."""

    def setUp(self):
        self.moi = _utilisateur('vue1')
        self.autre = _utilisateur('vue2')
        self.client.force_login(self.moi)
        self.gen = _generation(self.moi)

    def _url(self, app='composer', pk=None):
        from django.urls import reverse
        return reverse('media_library:api_export_item', args=[app, pk or self.gen.pk])

    def test_GET_rend_les_roles_admissibles_et_leurs_libelles(self):
        """C'est ce qui REMPLIT le sous-menu : sans libellés, le menu afficherait des clés
        techniques ; sans candidats, il proposerait des rôles que le POST refuserait."""
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(set(d['candidates']), {'voice', 'audio_music', 'audio_sfx'})
        self.assertEqual(set(d['labels']), set(d['candidates']))
        self.assertTrue(all(d['labels'].values()))

    def test_POST_range_et_rend_l_asset(self):
        r = self.client.post(self._url(), {'asset_type': 'audio_music'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        self.assertEqual(UserAsset.objects.filter(user=self.moi).count(), 1)

    def test_POST_sans_role_rend_400_ET_les_candidats(self):
        """400 et pas 500 : « précisez le rôle » est une réponse, pas une panne — et le menu
        doit pouvoir la distinguer d'un refus de droit."""
        r = self.client.post(self._url())
        self.assertEqual(r.status_code, 400)
        self.assertIn('candidates', r.json())

    def test_l_element_d_un_AUTRE_rend_403_en_GET_comme_en_POST(self):
        gen = _generation(self.autre)
        for methode in (self.client.get, self.client.post):
            r = methode(self._url(pk=gen.pk))
            self.assertEqual(r.status_code, 403, methode)

    def test_app_inconnue_rend_404(self):
        self.assertEqual(self.client.get(self._url(app='pasunapp')).status_code, 404)

    def test_l_anonyme_est_redirige_vers_la_connexion(self):
        self.client.logout()
        r = self.client.get(self._url())
        self.assertIn(r.status_code, (302, 403))


class DeprecationDesCopiesTest(TestCase):
    """Les 2 copies manuelles du geste (composer + sa jumelle) DÉLÈGUENT désormais à la brique
    (2026-09-12). Ce qui se garde ici n'est pas « ça marche » mais **que rien n'a changé pour
    l'appelant** : une dépréciation qui casse le contrat de réponse casse un bouton qui marchait.

    ⚠ `synthesizer/views.py:897` a été SORTI de la liste des copies : ce n'est pas le même geste
    — c'est l'UPLOAD d'une voix personnalisée (`request.FILES`, nom requis, extensions de voix),
    qui ne part d'aucun résultat d'app. Mon relevé du 11/09 l'avait compté à tort.
    """

    def setUp(self):
        self.moi = _utilisateur('depr1')
        self.client.force_login(self.moi)

    def test_la_route_composer_garde_son_CONTRAT_de_reponse(self):
        from django.urls import reverse
        gen = _generation(self.moi, 'piste.wav')
        r = self.client.post(reverse('composer:export_to_library', args=[gen.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('success'), r.json())
        self.assertEqual(UserAsset.objects.filter(user=self.moi).count(), 1)

    def test_le_ROLE_reste_derive_du_type_de_generation(self):
        """Le composer SAIT ce qu'il produit : la brique refuse de deviner, l'app fournit. Si ce
        lien se perdait, une musique atterrirait en « bruitage » sans que rien ne le dise."""
        from django.urls import reverse
        from wama.composer.models import ComposerGeneration
        for type_gen, attendu in (('music', 'audio_music'), ('sfx', 'audio_sfx')):
            gen = _generation(self.moi, f'{type_gen}.wav')
            ComposerGeneration.objects.filter(pk=gen.pk).update(generation_type=type_gen)
            r = self.client.post(reverse('composer:export_to_library', args=[gen.pk]))
            self.assertEqual(r.status_code, 200, r.content[:200])
            self.assertEqual(UserAsset.objects.get(pk=r.json()['asset_id']).asset_type, attendu)

    def test_le_double_export_reste_REFUSE(self):
        """Garde propre à l'app (`exported_to_library`) que la brique ne connaît pas — donc la
        seule chose que la délégation pouvait faire disparaître en silence."""
        from django.urls import reverse
        gen = _generation(self.moi, 'unefois.wav')
        self.assertEqual(self.client.post(
            reverse('composer:export_to_library', args=[gen.pk])).status_code, 200)
        r2 = self.client.post(reverse('composer:export_to_library', args=[gen.pk]))
        self.assertEqual(r2.status_code, 400)
        self.assertIn('Déjà', r2.json()['error'])

    def test_plus_AUCUNE_copie_manuelle_du_geste(self):
        """🔴 Le gardien de la dette : si une vue d'app réintroduit une copie de fichier vers la
        médiathèque, le geste recommence à figer la forme du domicile.

        ⚠ PAR AST, JAMAIS PAR GREP — et ce n'est pas de la coquetterie : ma 1ʳᵉ version cherchait
        la chaîne `shutil.copy2` dans le texte et accusait `composer/views.py`… à cause de MA
        PROPRE DOCSTRING, qui cite le défaut qu'elle vient de retirer. Un gardien qui lit les
        commentaires condamne les fichiers qui expliquent leur correction.
        (Même famille que le `find_code` du `conformity_checker`, et que la règle de mémoire
        « gardien anti-duplication par AST, jamais grep ».)
        """
        import ast
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent
        coupables = []
        for vues in sorted(racine.glob('*/views.py')):
            if vues.parent.name == 'media_library':
                continue                       # le domicile du geste a le droit d'écrire
            try:
                arbre = ast.parse(vues.read_text(encoding='utf-8', errors='ignore'))
            except SyntaxError:
                continue
            cite_mediatheque = 'media_library' in vues.read_text(encoding='utf-8',
                                                                 errors='ignore')
            if not cite_mediatheque:
                continue
            for n in ast.walk(arbre):
                # `shutil.copy2(...)` / `shutil.copyfile(...)` APPELÉS, pas mentionnés.
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in ('copy2', 'copyfile', 'copy')
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == 'shutil'):
                    coupables.append(f'{vues.parent.name}/views.py:{n.lineno}')
        self.assertEqual(coupables, [], f'copie manuelle vers la médiathèque : {coupables}')


class GeneriquePourTOUTESLesAppsTest(TestCase):
    """Le geste ne doit contenir aucune connaissance d'app. On l'atteste en le passant sur
    TOUTES les apps enregistrées au détail : aucune ne doit provoquer d'exception, et celles
    sans résultat doivent rendre un refus PARLANT — jamais une trace."""

    def test_aucune_app_enregistree_ne_fait_LEVER_la_brique(self):
        from wama.common.utils.detail_registry import DetailRegistry
        moi = _utilisateur('gen1')
        apps = DetailRegistry.registered_apps()
        self.assertGreaterEqual(len(apps), 10, "le registre de détail semble vide : test vacueux")
        for app in apps:
            out = export_item_to_library(moi, app, 10 ** 9)
            self.assertIsInstance(out, dict, app)
            self.assertIn('error', out, app)
