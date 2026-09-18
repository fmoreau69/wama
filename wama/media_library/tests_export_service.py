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


def _audio_ameliore(user, nom_fichier='ameliore.wav'):
    """Un élément dont le rôle de sortie est AMBIGU par construction : la branche audio de
    l'enhancer ne déclare pas de `result_role` (une voix, une musique ou un bruitage amélioré
    reste ce qu'il était — l'app ne le sait pas). ⚠ Le composer, exemple jusqu'au 2026-09-18,
    déclare désormais son rôle : il ne peut plus servir à tester le refus de deviner."""
    from wama.enhancer.models import AudioEnhancement
    ae = AudioEnhancement.objects.create(user=user)
    ae.output_file.save(nom_fichier, ContentFile(b'\x00\x01FAUXAUDIO'), save=True)
    return ae


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
        ae = _audio_ameliore(self.moi)
        out = export_item_to_library(self.moi, 'audio_enhancer', ae.pk)
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
        ae = _audio_ameliore(self.moi)
        r = self.client.get(self._url('audio_enhancer', ae.pk))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(set(d['candidates']), {'voice', 'audio_music', 'audio_sfx'})
        self.assertEqual(set(d['labels']), set(d['candidates']))
        self.assertTrue(all(d['labels'].values()))
        self.assertEqual(set(d['choices']), set(d['candidates']))

    def test_POST_range_et_rend_l_asset(self):
        r = self.client.post(self._url(), {'asset_type': 'audio_music'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['success'])
        self.assertEqual(UserAsset.objects.filter(user=self.moi).count(), 1)

    def test_POST_sans_role_rend_400_ET_les_candidats(self):
        """400 et pas 500 : « précisez le rôle » est une réponse, pas une panne — et le menu
        doit pouvoir la distinguer d'un refus de droit."""
        ae = _audio_ameliore(self.moi)
        r = self.client.post(self._url('audio_enhancer', ae.pk))
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


class ProvenanceEtRetraitTest(TestCase):
    """L'état « déjà dans la médiathèque » et le RETRAIT depuis le menu « … » (2026-09-14).

    Demande de Fabien : que le sous-menu dise qu'une sortie est déjà rangée (une coche) et permette
    de la retirer sans aller dans la médiathèque. Ce qui se garde : l'état vient de la PROVENANCE
    (jamais du nom), le retrait ne touche que la COPIE rangée et que les assets de l'appelant.
    """

    def setUp(self):
        self.moi = _utilisateur('prov1')
        self.autre = _utilisateur('prov2')
        self.client.force_login(self.moi)
        self.gen = _generation(self.moi)

    def _url(self, pk=None):
        from django.urls import reverse
        return reverse('media_library:api_export_item', args=['composer', pk or self.gen.pk])

    def test_le_rangement_pose_la_PROVENANCE(self):
        out = export_item_to_library(self.moi, 'composer', self.gen.pk, asset_type='audio_music')
        asset = UserAsset.objects.get(pk=out['asset_id'])
        self.assertEqual((asset.source_app, asset.source_pk), ('composer', self.gen.pk))

    def test_une_sortie_deja_rangee_sous_ce_role_est_REFUSEE_meme_sous_un_autre_nom(self):
        """Sans la provenance, un second rangement sous un autre nom passait : deux copies, et la
        coche du menu n'aurait su dire laquelle retirer."""
        from wama.composer.models import ComposerGeneration
        export_item_to_library(self.moi, 'composer', self.gen.pk, asset_type='audio_music')
        ComposerGeneration.objects.filter(pk=self.gen.pk).update(exported_to_library=False)
        out = export_item_to_library(self.moi, 'composer', self.gen.pk,
                                     asset_type='audio_music', name='un autre nom')
        self.assertIn('error', out)
        self.assertEqual(UserAsset.objects.filter(user=self.moi).count(), 1)

    def test_GET_dit_sous_quels_roles_la_sortie_est_DEJA_rangee(self):
        self.assertEqual(self.client.get(self._url()).json()['in_library'], {})
        out = export_item_to_library(self.moi, 'composer', self.gen.pk, asset_type='audio_music')
        d = self.client.get(self._url()).json()
        self.assertEqual(d['in_library']['audio_music']['asset_id'], out['asset_id'])
        self.assertIn('audio_music', d['labels'])

    def test_le_RETRAIT_supprime_la_copie_et_JAMAIS_la_sortie_de_l_app(self):
        from pathlib import Path
        out = export_item_to_library(self.moi, 'composer', self.gen.pk, asset_type='audio_music')
        copie = Path(UserAsset.objects.get(pk=out['asset_id']).file.path)
        sortie = Path(self.gen.audio_output.path)
        r = self.client.post(self._url(), {'action': 'remove', 'asset_type': 'audio_music'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['removed'], 1)
        self.assertFalse(UserAsset.objects.filter(pk=out['asset_id']).exists())
        self.assertFalse(copie.exists(), "la copie rangée doit partir avec l'asset")
        self.assertTrue(sortie.exists(), "le résultat de l'app ne doit JAMAIS être touché")

    def test_le_retrait_rend_l_element_de_nouveau_exportable(self):
        """Le drapeau d'app (composer) suit : sinon sa route refuserait « Déjà exporté » à vie."""
        export_item_to_library(self.moi, 'composer', self.gen.pk, asset_type='audio_music')
        self.client.post(self._url(), {'action': 'remove', 'asset_type': 'audio_music'})
        self.gen.refresh_from_db()
        self.assertFalse(self.gen.exported_to_library)
        self.assertNotIn('error', export_item_to_library(self.moi, 'composer', self.gen.pk,
                                                         asset_type='audio_music'))

    def test_le_retrait_ne_touche_JAMAIS_la_mediatheque_d_autrui(self):
        gen_autre = _generation(self.autre)
        out = export_item_to_library(self.autre, 'composer', gen_autre.pk, asset_type='audio_music')
        r = self.client.post(self._url(pk=gen_autre.pk), {'action': 'remove'})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(UserAsset.objects.filter(pk=out['asset_id']).exists())

    def test_retirer_ce_qui_n_est_pas_range_le_DIT(self):
        r = self.client.post(self._url(), {'action': 'remove', 'asset_type': 'audio_music'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.json())

    def test_supprimer_depuis_la_PAGE_mediatheque_libere_aussi_le_drapeau(self):
        """Audit du 14/09 (R1) : seul le retrait par le menu remettait `exported_to_library` ; un
        asset supprimé depuis la page laissait le composer répondre « Déjà exporté » à vie."""
        from django.urls import reverse
        out = export_item_to_library(self.moi, 'composer', self.gen.pk, asset_type='audio_music')
        self.gen.refresh_from_db()
        self.assertTrue(self.gen.exported_to_library)
        r = self.client.post(reverse('media_library:api_delete', args=[out['asset_id']]))
        self.assertEqual(r.status_code, 200, r.content)
        self.gen.refresh_from_db()
        self.assertFalse(self.gen.exported_to_library)

    def test_le_drapeau_reste_tant_qu_un_AUTRE_compte_garde_un_asset_de_l_element(self):
        """Le drapeau appartient à l'ÉLÉMENT, pas au compte qui retire (audit R11) : tant qu'un asset
        en provient encore, il reste posé."""
        from wama.media_library.services import delete_asset
        out = export_item_to_library(self.moi, 'composer', self.gen.pk, asset_type='audio_music')
        UserAsset.objects.create(user=self.autre, name='copie tierce', asset_type='audio_music',
                                 source_app='composer', source_pk=self.gen.pk)
        delete_asset(UserAsset.objects.get(pk=out['asset_id']))
        self.gen.refresh_from_db()
        self.assertTrue(self.gen.exported_to_library)


class RoleDeclareParLAppTest(TestCase):
    """Le RÔLE de la sortie se DÉCLARE au commun, pour toutes les apps (décision Fabien,
    2026-09-18) : clé canonique `result_role` du détail, lue par `admissible_roles`. Ce que ces
    tests tiennent : une app qui sait ce qu'elle produit n'a plus qu'un rôle proposé (et
    accepté) ; une app qui ne le sait pas garde le choix ; une déclaration NON admise pour
    l'extension est ignorée, jamais bloquante ; et la route d'app du composer — qui portait ce
    savoir à elle seule — n'existe plus (`REMOVAL_LEDGER R65`).
    """

    def setUp(self):
        self.moi = _utilisateur('role1')
        self.client.force_login(self.moi)

    def _url(self, app, pk):
        from django.urls import reverse
        return reverse('media_library:api_export_item', args=[app, pk])

    def test_admissible_roles_filtre_par_extension_PUIS_par_role_declare(self):
        from wama.media_library.services import admissible_roles
        self.assertEqual(admissible_roles({'result_role': 'audio_music'}, 'x.wav'), ['audio_music'])
        self.assertEqual(set(admissible_roles({}, 'x.wav')), {'voice', 'audio_music', 'audio_sfx'})
        # Déclaration non admise pour l'extension : IGNORÉE, l'utilisateur choisit.
        self.assertEqual(set(admissible_roles({'result_role': 'image'}, 'x.wav')),
                         {'voice', 'audio_music', 'audio_sfx'})
        self.assertEqual(admissible_roles({'result_role': 'image'}, 'x.zip'), [])

    def test_le_composer_DECLARE_musique_ou_bruitage_et_le_menu_ne_propose_que_ca(self):
        """Ce que faisait la route d'app, désormais par le schéma canonique ET le geste commun :
        GET rend UN rôle, POST sans rôle range sous ce rôle."""
        from wama.composer.models import ComposerGeneration
        for type_gen, attendu in (('music', 'audio_music'), ('sfx', 'audio_sfx')):
            gen = _generation(self.moi, f'{type_gen}.wav')
            ComposerGeneration.objects.filter(pk=gen.pk).update(generation_type=type_gen)
            r = self.client.get(self._url('composer', gen.pk))
            self.assertEqual(r.status_code, 200, r.content[:200])
            self.assertEqual(r.json()['candidates'], [attendu])
            r = self.client.post(self._url('composer', gen.pk))
            self.assertEqual(r.status_code, 200, r.content[:200])
            self.assertEqual(UserAsset.objects.get(pk=r.json()['asset_id']).asset_type, attendu)

    def test_un_role_hors_de_la_liste_proposee_est_REFUSE_meme_admis_par_l_extension(self):
        """Le menu ne propose jamais ce que le POST refuserait — et réciproquement : ranger une
        musique du composer comme « voix » n'est pas offert, donc pas accepté."""
        gen = _generation(self.moi, 'piste.wav')
        out = export_item_to_library(self.moi, 'composer', gen.pk, asset_type='voice')
        self.assertIn('error', out)
        self.assertEqual(out.get('candidates'), ['audio_music'])

    def test_une_app_qui_ne_declare_rien_garde_le_CHOIX(self):
        """La branche audio de l'enhancer ne sait pas si elle a amélioré une voix ou une
        musique : trois rôles restent proposés, et POST sans rôle demande de préciser."""
        from django.core.files.base import ContentFile
        from wama.enhancer.models import AudioEnhancement
        ae = AudioEnhancement.objects.create(user=self.moi)
        ae.output_file.save('ameliore.wav', ContentFile(b'\x00\x01'), save=True)
        r = self.client.get(self._url('audio_enhancer', ae.pk))
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(set(r.json()['candidates']), {'voice', 'audio_music', 'audio_sfx'})
        out = export_item_to_library(self.moi, 'audio_enhancer', ae.pk)
        self.assertIn('Précisez', out.get('error', ''))

    def test_la_forme_map_de_la_spec_traduit_la_categorie_en_role(self):
        """Converter (spec déclarative) : `{'field': 'media_type', 'map': MEDIA_CATEGORY_ROLE}`
        → image/vidéo/document déclarés, audio laissé au choix (absence VOULUE de la table)."""
        from django.core.files.base import ContentFile
        from wama.common.utils.detail_registry import DetailRegistry
        from wama.converter.models import ConversionJob
        adapter = DetailRegistry.get('converter')['adapter']
        for media_type, attendu in (('image', 'image'), ('video', 'video'), ('audio', None)):
            job = ConversionJob.objects.create(user=self.moi, input_filename='a', media_type=media_type)
            job.output_file.save(f'{media_type}.bin', ContentFile(b'x'), save=True)
            self.assertEqual(adapter(job).get('result_role'), attendu, media_type)
        # Sans sortie, pas de rôle : la clé suit `result_file`.
        sans = ConversionJob.objects.create(user=self.moi, input_filename='a', media_type='image')
        self.assertNotIn('result_role', adapter(sans))

    def test_chaque_role_declare_par_une_app_existe_dans_le_vocabulaire_des_natures(self):
        """Une déclaration est une CHAÎNE dans le substrat (pas de dépendance à une app) : c'est
        ici qu'on vérifie qu'aucune app ne déclare un rôle inconnu — par AST des `apps.py`."""
        import ast
        import re
        from pathlib import Path
        from wama.media_library.models import ASSET_TYPES
        connus = {t for t, _ in ASSET_TYPES}
        racine = Path(__file__).resolve().parent.parent
        inconnus = []
        for f in sorted(racine.glob('*/apps.py')):
            src = f.read_text(encoding='utf-8', errors='ignore')
            if 'result_role' not in src:
                continue
            for n in ast.walk(ast.parse(src)):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                        and re.fullmatch(r'[a-z_0-9]+', n.value) and n.value in (
                            'voice', 'audio_music', 'audio_sfx', 'image', 'video',
                            'document', 'avatar', 'object3d'):
                    continue
            # Les littéraux de rôle sont ceux passés à `result_role=` : on les relit au texte.
            for lit in re.findall(r"result_role=(?:'([a-z_0-9]+)'|.*?'([a-z_0-9]+)' if .*?else '([a-z_0-9]+)')",
                                  src):
                for role in lit:
                    if role and role not in connus:
                        inconnus.append(f'{f.parent.name}: {role}')
        self.assertEqual(inconnus, [])

    def test_la_route_d_app_du_composer_n_existe_PLUS(self):
        from django.urls import NoReverseMatch, reverse
        with self.assertRaises(NoReverseMatch):
            reverse('composer:export_to_library', args=[1])
        self.assertEqual(self.client.post('/composer/export/1/').status_code, 404)


class GardienAntiCopieTest(TestCase):
    """Les copies manuelles du geste (composer + sa jumelle) ont DÉLÉGUÉ à la brique le 12/09,
    puis la route composer a été RETIRÉE le 18/09. Reste le gardien.

    ⚠ `synthesizer/views.py:897` a été SORTI de la liste des copies : ce n'est pas le même geste
    — c'est l'UPLOAD d'une voix personnalisée (`request.FILES`, nom requis, extensions de voix),
    qui ne part d'aucun résultat d'app. Mon relevé du 11/09 l'avait compté à tort.
    """

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


class BoutonDedieRetireTest(TestCase):
    """Le bouton dédié « Exporter vers médiathèque » de la card composer est RETIRÉ (2026-09-18,
    demande de Fabien) : il DUPLIQUAIT le geste du menu « … » / clic droit, commun aux 10 apps,
    sans en connaître l'état persisté ni le retrait. La fonctionnalité RESTE — par la route
    commune, celle que le menu appelle. Trois choses à tenir : plus de bouton (gabarit, JS,
    CSS, config), la copie servie suit, et le geste répond toujours pour composer.
    """

    def _code(self, *rel):
        """Le CODE sans ses commentaires : ceux-ci citent le bouton retiré pour dire pourquoi."""
        import re
        from pathlib import Path
        import wama
        texte = Path(wama.__file__).parent.parent.joinpath(*rel).read_text(encoding='utf-8')
        texte = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', texte, flags=re.S)
        texte = re.sub(r'\{#.*?#\}', '', texte, flags=re.S)
        texte = re.sub(r'/\*.*?\*/', '', texte, flags=re.S)
        return re.sub(r'(^|[^:\'"\\])//[^\n]*', r'\1', texte)

    def test_le_gabarit_de_card_ne_porte_plus_le_bouton_ni_la_coche(self):
        code = self._code('wama', 'composer', 'templates', 'composer', '_generation_card.html')
        for motif in ('export-btn', 'Exporter vers médiathèque', 'Déjà exporté', 'exported_to_library'):
            self.assertNotIn(motif, code, f'le bouton dédié est encore dans le gabarit : `{motif}`')

    def test_le_js_la_css_et_la_config_ne_le_connaissent_plus(self):
        self.assertNotIn('export-btn', self._code('wama', 'composer', 'static', 'composer', 'js', 'index.js'))
        self.assertNotIn('exportUrlTemplate', self._code('wama', 'composer', 'static', 'composer', 'js', 'index.js'))
        self.assertNotIn('.export-btn', self._code('wama', 'composer', 'static', 'composer', 'css', 'index.css'))
        self.assertNotIn('exportUrlTemplate', self._code('wama', 'composer', 'templates', 'composer', 'index.html'))

    def test_la_copie_SERVIE_est_la_source(self):
        from pathlib import Path
        import wama
        racine = Path(wama.__file__).parent.parent
        for rel in ('js/index.js', 'css/index.css'):
            with self.subTest(rel=rel):
                self.assertEqual((racine / 'wama/composer/static/composer' / rel).read_bytes(),
                                 (racine / 'staticfiles/composer' / rel).read_bytes())

    def test_la_card_RENDUE_n_a_plus_le_bouton_mais_garde_sa_rangee(self):
        """Rendu serveur réel (`card_html`, source unique du markup) : la rangée conventionnelle
        est là, le bouton dédié n'y est plus — et rien ne dépend d'`exported_to_library`."""
        from django.urls import reverse
        moi = _utilisateur('btn1')
        self.client.force_login(moi)
        gen = _generation(moi, 'rendu.wav')
        for deja in (False, True):
            type(gen).objects.filter(pk=gen.pk).update(exported_to_library=deja)
            r = self.client.get(reverse('composer:card_html', args=[gen.pk]))
            self.assertEqual(r.status_code, 200, r.content[:200])
            html = r.content.decode('utf-8')
            self.assertNotIn('export-btn', html)
            self.assertNotIn('Déjà exporté', html)
            for classe in ('settings-btn', 'duplicate-btn', 'delete-btn', 'btn-group-actions'):
                self.assertIn(classe, html, f'{classe} manque à la rangée rendue')

    def test_le_geste_RESTE_par_la_route_commune_du_menu(self):
        """Ce que le menu « … » appelle : GET rend les rôles (le sous-menu), POST range, GET
        montre la coche — pour composer comme pour les autres."""
        from django.urls import reverse
        moi = _utilisateur('btn2')
        self.client.force_login(moi)
        gen = _generation(moi, 'reste.mp3')
        url = reverse('media_library:api_export_item', args=['composer', gen.pk])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertIn('audio_music', r.json()['candidates'])
        self.assertEqual(r.json()['in_library'], {})
        r = self.client.post(url, {'asset_type': 'audio_music'})
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertIn('audio_music', self.client.get(url).json()['in_library'])
        gen.refresh_from_db()
        self.assertTrue(gen.exported_to_library, 'le drapeau d’app suit le geste commun')


class LateBindingTest(TestCase):
    """Les apps à liage TARDIF (transcriber, describer, reader — `export_binding='late'`,
    `WAMA_APP_CONVENTIONS §6.4`) : le master est un TEXTE, le fichier n'existe qu'une fois
    RENDU. Mesuré le 2026-09-18 : le geste disait « rien à ranger » sur un transcript terminé.
    Il rend désormais le format choisi par le MÊME builder que le bouton ⬇ (déclaré par
    `register_export_builder`), et range un `document`. Ce que ces tests tiennent : les choix
    sont les formats du ⬇ acceptés par la nature `document` (srt/json exclus), le rendu passe
    par le builder de l'app, la coche et le retrait sont PAR FORMAT, et deux formats d'un même
    élément coexistent.
    """

    def setUp(self):
        self.moi = _utilisateur('late1')
        self.client.force_login(self.moi)

    def _transcript(self, texte='Bonjour à tous.'):
        from wama.transcriber.models import Transcript
        return Transcript.objects.create(user=self.moi, text=texte)

    def _url(self, app, pk):
        from django.urls import reverse
        return reverse('media_library:api_export_item', args=[app, pk])

    def test_les_trois_apps_declarent_leur_builder_et_sont_late(self):
        from wama.common.utils.export_formats import export_builder_for, is_late_binding
        for app in ('transcriber', 'describer', 'reader'):
            with self.subTest(app=app):
                self.assertTrue(is_late_binding(app))
                self.assertTrue(callable(export_builder_for(app)), f'{app} : builder non résolu')
        self.assertFalse(is_late_binding('composer'))
        self.assertIsNone(export_builder_for('composer'))

    def test_les_choix_sont_les_formats_du_bouton_telecharger_acceptes_comme_document(self):
        from wama.common.utils.export_formats import entries_for_app
        from wama.media_library.services import export_choices
        t = self._transcript()
        choix = export_choices('transcriber', {'result_text': t.text})
        cles = [c['key'] for c in choix]
        self.assertEqual(cles, ['txt', 'pdf', 'docx'], 'srt n’est pas un document de médiathèque')
        declares = [e['value'] for e in entries_for_app('transcriber')]
        self.assertTrue(set(cles) < set(declares))
        self.assertTrue(all(c['asset_type'] == 'document' and c['format'] == c['key'] for c in choix))
        # reader : json exclu, md gardé.
        self.assertEqual([c['key'] for c in export_choices('reader', {'result_text': 'x'})],
                         ['txt', 'md', 'pdf', 'docx'])

    def test_sans_master_aucun_choix(self):
        from wama.media_library.services import export_choices
        self.assertEqual([], export_choices('transcriber', {}))
        t = self._transcript(texte='')
        r = self.client.get(self._url('transcriber', t.pk))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['candidates'], [])

    def test_GET_rend_les_formats_et_POST_range_le_rendu_du_builder(self):
        t = self._transcript()
        r = self.client.get(self._url('transcriber', t.pk))
        self.assertEqual(r.status_code, 200, r.content[:200])
        d = r.json()
        self.assertEqual(d['candidates'], ['txt', 'pdf', 'docx'])
        self.assertEqual(d['choices']['pdf'], {'key': 'pdf', 'asset_type': 'document',
                                               'format': 'pdf', 'label': 'Document · PDF'})
        self.assertEqual(d['in_library'], {})

        r = self.client.post(self._url('transcriber', t.pk), {'asset_type': 'document',
                                                              'output_format': 'pdf'})
        self.assertEqual(r.status_code, 200, r.content[:200])
        asset = UserAsset.objects.get(pk=r.json()['asset_id'])
        self.assertEqual(asset.asset_type, 'document')
        self.assertTrue(asset.file.name.lower().endswith('.pdf'), asset.file.name)
        self.assertEqual((asset.source_app, asset.source_pk), ('transcriber', t.pk))
        with asset.file.open('rb') as f:
            self.assertTrue(f.read(5).startswith(b'%PDF'), 'le contenu doit être le rendu PDF du builder')
        # Le nom porte la convention du téléchargement (tag de process + id de card) et le format.
        self.assertIn(str(t.pk), asset.name)
        self.assertTrue(asset.name.endswith('(PDF)'), asset.name)

    def test_la_coche_et_le_retrait_sont_PAR_FORMAT_et_deux_formats_coexistent(self):
        t = self._transcript()
        url = self._url('transcriber', t.pk)
        self.client.post(url, {'output_format': 'pdf'})
        self.client.post(url, {'output_format': 'txt'})
        deja = self.client.get(url).json()['in_library']
        self.assertEqual(set(deja), {'pdf', 'txt'})
        self.assertEqual(UserAsset.objects.filter(source_app='transcriber', source_pk=t.pk).count(), 2)
        # Un second PDF est refusé par la provenance (même élément, même format).
        r = self.client.post(url, {'output_format': 'pdf'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('déjà', r.json()['error'])
        # Retrait d'UN format seulement.
        r = self.client.post(url, {'action': 'remove', 'asset_type': 'document', 'output_format': 'pdf'})
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(set(self.client.get(url).json()['in_library']), {'txt'})

    def test_sans_format_le_geste_demande_de_preciser_avec_les_formats(self):
        t = self._transcript()
        out = export_item_to_library(self.moi, 'transcriber', t.pk)
        self.assertIn('Précisez', out['error'])
        self.assertEqual(out['candidates'], ['txt', 'pdf', 'docx'])
        out = export_item_to_library(self.moi, 'transcriber', t.pk, output_format='srt')
        self.assertIn('error', out)
        out = export_item_to_library(self.moi, 'transcriber', t.pk, asset_type='voice', output_format='txt')
        self.assertIn('error', out, 'un rendu texte est un document, jamais une voix')

    def test_l_outil_de_l_assistant_passe_le_format(self):
        from wama.tool_api import add_item_to_media_library
        t = self._transcript()
        out = add_item_to_media_library(self.moi, 'transcriber', t.pk, output_format='docx')
        self.assertNotIn('error', out, out)
        self.assertTrue(UserAsset.objects.get(pk=out['asset_id']).file.name.endswith('.docx'))

    def test_un_element_early_binding_garde_le_contrat_des_roles(self):
        """Contre-épreuve : pour composer, `choices` décrit des RÔLES sans format."""
        gen = _generation(self.moi, 'piste.wav')
        d = self.client.get(self._url('composer', gen.pk)).json()
        self.assertEqual(d['candidates'], ['audio_music'])
        self.assertEqual(d['choices']['audio_music']['format'], '')
        self.assertEqual(d['choices']['audio_music']['asset_type'], 'audio_music')


class RolesDeclaresParChaqueAppTest(TestCase):
    """Le rôle DÉCLARÉ par chaque app early-binding, VALEUR PAR VALEUR — la garde déclarée
    manquante à la clôture du 19/09 (jusque-là seul le vocabulaire était attesté, par AST : une
    déclaration inversée image ↔ vidéo serait passée). Chaque cas construit un vrai élément avec
    une sortie et lit `result_role` par l'adapter enregistré, comme le geste commun."""

    def setUp(self):
        self.moi = _utilisateur('roles_apps')

    def _role(self, app, instance):
        from wama.common.utils.detail_registry import DetailRegistry
        return DetailRegistry.get(app)['adapter'](instance).get('result_role')

    def test_anonymizer_suit_la_categorie_du_media(self):
        from wama.anonymizer.models import Media
        for media_type, attendu in (('image', 'image'), ('video', 'video')):
            m = Media.objects.create(user=self.moi, media_type=media_type)
            m.output_file = f'anonymizer/out.{ "png" if media_type == "image" else "mp4" }'
            m.save()
            self.assertEqual(self._role('anonymizer', m), attendu, media_type)

    def test_enhancer_suit_la_categorie_et_sa_branche_audio_ne_declare_rien(self):
        from wama.enhancer.models import AudioEnhancement, Enhancement
        for media_type, attendu in (('image', 'image'), ('video', 'video')):
            e = Enhancement.objects.create(user=self.moi, media_type=media_type)
            e.output_file.save(f'e.{media_type}', ContentFile(b'x'), save=True)
            self.assertEqual(self._role('enhancer', e), attendu, media_type)
        ae = AudioEnhancement.objects.create(user=self.moi)
        ae.output_file.save('a.wav', ContentFile(b'x'), save=True)
        self.assertIsNone(self._role('audio_enhancer', ae))

    def test_avatarizer_declare_toujours_une_video(self):
        from wama.avatarizer.models import AvatarJob
        job = AvatarJob.objects.create(user=self.moi)
        self.assertIsNone(self._role('avatarizer', job), 'sans sortie, pas de rôle')
        job.output_video.save('av.mp4', ContentFile(b'x'), save=True)
        self.assertEqual(self._role('avatarizer', job), 'video')

    def test_imager_declare_image_ou_video_selon_la_generation(self):
        from pathlib import Path
        from django.conf import settings
        from wama.common.utils.media_paths import app_media_dir
        from wama.imager.models import ImageGeneration
        rel = f"{app_media_dir('imager', self.moi.id, 'output')}/role_test.png"
        absolu = Path(settings.MEDIA_ROOT) / rel
        absolu.parent.mkdir(parents=True, exist_ok=True)
        absolu.write_bytes(b'\x89PNG')
        try:
            g = ImageGeneration.objects.create(user=self.moi, prompt='x', generated_images=[str(absolu)])
            self.assertFalse(g.is_video_generation)
            self.assertEqual(self._role('imager', g), 'image')
        finally:
            absolu.unlink(missing_ok=True)
        v = ImageGeneration.objects.create(user=self.moi, prompt='x')
        v.output_video.save('v.mp4', ContentFile(b'x'), save=True)
        attendu = 'video' if v.is_video_generation else 'image'
        self.assertEqual(self._role('imager', v), attendu)

    def test_composer_declare_selon_le_type_de_generation(self):
        from wama.composer.models import ComposerGeneration
        for type_gen, attendu in (('music', 'audio_music'), ('sfx', 'audio_sfx')):
            gen = _generation(self.moi, f'{type_gen}.wav')
            ComposerGeneration.objects.filter(pk=gen.pk).update(generation_type=type_gen)
            gen.refresh_from_db()
            self.assertEqual(self._role('composer', gen), attendu)
        sans = _generation(self.moi, avec_sortie=False)
        self.assertIsNone(self._role('composer', sans), 'sans sortie, pas de rôle')
