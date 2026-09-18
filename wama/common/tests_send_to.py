"""ENVOYER VERS — la sortie d'une card en entrée d'une autre app (chaînage progressif).

Cadre (Fabien, 2026-09-08) : « la sortie qu'on envoie en entrée d'une autre app […] sans
forcément devoir passer par le studio ».

⚠⚠ CE QUE CES TESTS PROTÈGENT AVANT TOUT : la règle des TROIS conditions. Le menu « Envoyer
vers… » du gestionnaire de fichiers a offert pendant des semaines trois apps que le serveur
REFUSAIT, avec un critère de grille vert au-dessus (`WAMA_VERIFICATION §Geste 14`). Une
destination n'est donc offerte que si un importeur existe, que l'extension est DÉCLARÉE
acceptée, et que l'utilisateur a accès à l'app. *Ce qu'on n'offre pas ne peut pas décevoir.*
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from wama.common.services.send_to import destinations, sorties_de

User = get_user_model()


def _utilisateur(nom, tous_les_roles=True):
    from wama.accounts.permissions import GROUP_PREFIX
    u = User.objects.create_user(nom, password='x')
    if tous_les_roles:
        for role in ('communication', 'recherche', 'ingenierie', 'administratif'):
            g, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
            u.groups.add(g)
    return u


class SortiesDeclareesTest(TestCase):
    """`sorties_de` passe par l'ADAPTER de détail — le même accesseur que l'inspecteur."""

    def setUp(self):
        self.u = _utilisateur('envoi_sorties')

    def test_un_element_SANS_sortie_ne_rend_aucun_chemin(self):
        """Une card sans résultat n'a rien à envoyer — et l'entrée de menu ne doit pas paraître."""
        from wama.converter.models import ConversionJob
        job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        self.assertEqual([], sorties_de('converter', job))

    def test_une_surface_inconnue_rend_une_liste_vide_sans_lever(self):
        self.assertEqual([], sorties_de('pas_une_app', None))

    def test_la_sortie_est_rendue_en_chemin_RELATIF_a_media(self):
        """L'adapter rend des URL (`/media/…`) ; l'endpoint d'import attend un chemin relatif.

        C'est la seule conversion de ce module, et elle doit ÉCARTER ce qui ne relève pas de
        `MEDIA_URL` : un chemin fabriqué autrement ne serait pas importable.
        """
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        # ⚠ Le chemin vient de la BRIQUE, plus d'un littéral : ce test écrivait
        # `converter/{uid}/output/…` en dur, donc il serait resté VERT après la bascule au
        # domicile unique (2026-09-12) tout en n'attestant plus la forme réelle.
        attendu = f"{app_media_dir('converter', self.u.id, 'output')}/a.webp"
        job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        job.output_file.name = attendu
        job.save(update_fields=['output_file'])
        self.assertEqual([attendu], sorties_de('converter', job))

    def test_le_chemin_rendu_est_celui_qu_AUTORISE_la_garde_d_import(self):
        """Le contrat entre les deux endpoints : ce que l'un rend, l'autre doit l'accepter.

        `is_path_allowed` doit accepter la forme que le résolveur rend. Si l'une des deux
        change sans l'autre, l'envoi échoue avec un « Access denied » incompréhensible — c'est
        exactement le genre de couture qu'aucun des deux côtés ne teste tout seul.

        ⚠ Le cas s'est PRODUIT le 2026-09-12 : la bascule au domicile unique a déplacé la
        forme rendue vers `users/<uid>/<app>/…` pendant que la garde n'autorisait encore que
        `<app>/<uid>/…`. Ce test ne l'aurait PAS vu — il fabriquait son chemin à la main, donc
        il testait l'ancienne forme des deux côtés. Il part maintenant de la brique.
        """
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        from wama.filemanager.views import is_path_allowed
        job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        job.output_file.name = f"{app_media_dir('converter', self.u.id, 'output')}/a.webp"
        job.save(update_fields=['output_file'])
        for chemin in sorties_de('converter', job):
            self.assertTrue(is_path_allowed(chemin, self.u),
                            f"{chemin} : rendu par le résolveur, REFUSÉ par la garde d'import")


class DestinationsTest(TestCase):
    """Les TROIS conditions. Chacune a son test, parce que chacune a déjà manqué quelque part."""

    def setUp(self):
        self.u = _utilisateur('envoi_dest')

    def test_aucune_destination_sans_chemin(self):
        self.assertEqual([], destinations(self.u, []))
        self.assertEqual([], destinations(self.u, None))

    def test_une_extension_que_personne_ne_declare_ne_propose_RIEN(self):
        """Une liste vide est une RÉPONSE : l'UI doit la dire, pas ouvrir un menu creux."""
        self.assertEqual([], destinations(self.u, ['converter/1/output/x.zzz']))

    def test_une_image_propose_des_apps_qui_la_DECLARENT(self):
        from wama.common.app_registry import APP_CATALOG
        apps = {d['app'] for d in destinations(self.u, ['converter/1/output/x.png'])}
        self.assertTrue(apps, "aucune app pour un .png : le catalogue ou la dérivation a changé")
        for app in apps:
            exts = {e.lower() for e in (APP_CATALOG.get(app) or {}).get('input_extensions', ())}
            self.assertIn('.png', exts,
                          f"{app} est offerte alors qu'elle ne déclare pas .png")

    def test_une_app_est_offerte_seulement_si_elle_a_un_IMPORTEUR(self):
        """`avatarizer` et `composer` n'en ont pas (prompt-primaires) : ils ne doivent pas
        apparaître, même si leurs extensions correspondent. Ils ne mentent plus, c'est tout."""
        from wama.filemanager.views import importer_for
        for d in destinations(self.u, ['converter/1/output/x.png']):
            self.assertIsNotNone(importer_for(d['app']),
                                 f"{d['app']} offerte sans importeur")

    def test_une_app_INACCESSIBLE_n_est_pas_offerte(self):
        """Le menu ne va jamais un cran plus loin que le portier de la page."""
        from wama.accounts.permissions import accessible
        nu = _utilisateur('envoi_sans_role', tous_les_roles=False)
        for d in destinations(nu, ['converter/1/output/x.png']):
            self.assertTrue(accessible(nu, 'app', d['app']),
                            f"{d['app']} offerte à un compte qui n'y a pas accès")
        # …et il en voit MOINS qu'un compte doté de tous les rôles.
        self.assertLessEqual(len(destinations(nu, ['converter/1/output/x.png'])),
                             len(destinations(self.u, ['converter/1/output/x.png'])))

    def test_une_app_qui_ne_prend_QU_UNE_PARTIE_des_fichiers_n_est_pas_offerte(self):
        """Sinon l'envoi serait partiel EN SILENCE : l'utilisateur croirait avoir transmis tout
        son résultat. On exige donc l'inclusion de TOUTES les extensions envoyées."""
        from wama.common.app_registry import APP_CATALOG
        melange = ['converter/1/output/x.png', 'converter/1/output/y.wav']
        for d in destinations(self.u, melange):
            exts = {e.lower() for e in (APP_CATALOG.get(d['app']) or {}).get('input_extensions', ())}
            self.assertTrue({'.png', '.wav'} <= exts,
                            f"{d['app']} offerte pour png+wav sans déclarer les deux")

    def test_chaque_destination_porte_de_quoi_s_afficher(self):
        for d in destinations(self.u, ['converter/1/output/x.png']):
            self.assertTrue(d.get('libelle'), f"{d} sans libellé")
            self.assertTrue(d.get('icone'), f"{d} sans icône")


class EndpointEnvoyerVersTest(TestCase):

    def setUp(self):
        self.u = _utilisateur('envoi_endpoint')
        self.client.force_login(self.u)
        from wama.converter.models import ConversionJob
        self.job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        self.job.output_file.name = f'converter/{self.u.id}/output/a.png'
        self.job.save(update_fields=['output_file'])

    def _url(self, surface='converter', pk=None):
        return reverse('common:api_envoyer_vers', args=[surface, pk or self.job.id])

    def test_le_resolveur_rend_chemins_destinations_et_endpoint(self):
        rep = self.client.get(self._url())
        self.assertEqual(200, rep.status_code, rep.content[:200])
        d = rep.json()
        self.assertEqual([f'converter/{self.u.id}/output/a.png'], d['chemins'])
        self.assertTrue(d['destinations'])
        # L'endpoint est RENDU : le front n'écrit pas les routes d'une autre app.
        self.assertEqual(reverse('filemanager:api_import'), d['endpoint'])

    def test_un_pk_etranger_rend_404(self):
        from wama.converter.models import ConversionJob
        autre = _utilisateur('envoi_autrui')
        etranger = ConversionJob.objects.create(user=autre, input_filename='b.png')
        self.assertEqual(404, self.client.get(self._url(pk=etranger.id)).status_code)

    def test_surface_inconnue_rend_404(self):
        self.assertEqual(404, self.client.get(self._url(surface='pas_une_app')).status_code)

    def test_le_resolveur_ne_MUTE_rien(self):
        """C'est un GET, et il doit le rester : la lecture ne change pas la file."""
        avant = (self.job.visibility, self.job.output_file.name)
        self.client.get(self._url())
        self.job.refresh_from_db()
        self.assertEqual(avant, (self.job.visibility, self.job.output_file.name))


class CablageFrontTest(TestCase):
    """Le câblage — le comportement, lui, s'atteste au navigateur."""

    def test_la_brique_est_chargee_APRES_le_partage_et_AVANT_le_menu(self):
        """Elle réutilise le lecteur de coordonnées du partage, et le menu ne l'offre que si
        elle existe. Dans le mauvais ordre, l'entrée disparaîtrait sans erreur."""
        import re
        from django.conf import settings
        from pathlib import Path
        base = (Path(settings.BASE_DIR) / 'wama' / 'templates'
                / 'base.html').read_text(encoding='utf-8')

        def position(fichier):
            m = re.search(r'<script[^>]+' + re.escape(fichier), base)
            return m.start() if m else -1

        i_share, i_envoi, i_menu = (position('wama-share.js'), position('wama-send-to.js'),
                                    position('wama-card-menu.js'))
        for nom, i in (('wama-share.js', i_share), ('wama-send-to.js', i_envoi),
                       ('wama-card-menu.js', i_menu)):
            self.assertNotEqual(-1, i, f"{nom} n'est plus chargé par une balise script")
        self.assertLess(i_share, i_envoi)
        self.assertLess(i_envoi, i_menu)

    def test_l_url_de_l_endpoint_d_import_n_est_PAS_ecrite_dans_le_JS(self):
        """Elle est rendue par le résolveur. Une brique commune qui écrit la route d'une autre
        app casse au premier renommage — et personne ne saurait où regarder."""
        from django.conf import settings
        from pathlib import Path
        js = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
              / 'wama-send-to.js').read_text(encoding='utf-8')
        self.assertNotIn('/filemanager/', js)
        self.assertIn('d.endpoint', js)

    def test_staticfiles_sert_la_meme_brique(self):
        from django.conf import settings
        from pathlib import Path
        racine = Path(settings.BASE_DIR)
        for rel in ('common/js/wama-send-to.js', 'common/css/wama-card-menu.css'):
            source = racine / 'wama' / 'common' / 'static' / rel
            servi = racine / 'staticfiles' / rel
            with self.subTest(fichier=rel):
                self.assertTrue(servi.exists())
                self.assertEqual(source.read_text(encoding='utf-8'),
                                 servi.read_text(encoding='utf-8'))


class DestinationsPourUneSelectionTest(TestCase):
    """L'arbre de fichiers passe au MÊME résolveur (2026-09-14). Une SÉLECTION mêlée n'est pas une
    sortie de card : elle est rendue en PARTIEL ANNONCÉ — chaque app dit quels fichiers elle prend."""

    def setUp(self):
        self.u = _utilisateur('envoi_selection')

    def test_en_partiel_chaque_app_dit_QUELS_fichiers_elle_prend(self):
        from wama.common.app_registry import APP_CATALOG
        melange = ['converter/1/output/x.png', 'converter/1/output/y.wav']
        dests = destinations(self.u, melange, partiel=True)
        self.assertTrue(dests, "aucune app pour png+wav, même en partiel")
        for d in dests:
            exts = {e.lower() for e in (APP_CATALOG.get(d['app']) or {}).get('input_extensions', ())}
            self.assertTrue(d['acceptes'], d)
            for chemin in d['acceptes']:
                self.assertIn(chemin, melange)
                self.assertIn('.' + chemin.rsplit('.', 1)[-1], exts,
                              f"{d['app']} annonce {chemin} sans déclarer son extension")

    def test_le_partiel_offre_AU_MOINS_ce_que_le_tout_ou_rien_offre(self):
        melange = ['converter/1/output/x.png', 'converter/1/output/y.wav']
        tout = {d['app'] for d in destinations(self.u, melange)}
        partiel = {d['app'] for d in destinations(self.u, melange, partiel=True)}
        self.assertLessEqual(tout, partiel)

    def test_un_dossier_n_offre_que_des_apps_a_importeur_ET_accessibles(self):
        from wama.accounts.permissions import accessible
        from wama.common.services.send_to import destinations_dossier
        from wama.filemanager.views import importer_for
        nu = _utilisateur('envoi_dossier_sans_role', tous_les_roles=False)
        from wama.common.app_registry import APP_CATALOG
        for compte in (self.u, nu):
            for d in destinations_dossier(compte):
                self.assertIsNotNone(importer_for(d['app']))
                self.assertTrue(accessible(compte, 'app', d['app']), d)
                # Mesuré à la sonde : cam_analyzer / face_analyzer étaient offerts sans rien
                # déclarer — leur import d'un dossier n'aurait jamais rien retenu.
                self.assertTrue((APP_CATALOG.get(d['app']) or {}).get('input_extensions'),
                                f"{d['app']} offerte pour un dossier sans déclarer d'extension")


class EndpointEnvoyerVersCheminsTest(TestCase):
    """`common:api_envoyer_vers_chemins` — l'entrée de l'arbre de fichiers dans le résolveur."""

    def setUp(self):
        from wama.common.utils.media_paths import app_media_dir
        self.u = _utilisateur('envoi_chemins')
        self.client.force_login(self.u)
        self.dossier = app_media_dir('converter', self.u.id, 'output')
        self.url = reverse('common:api_envoyer_vers_chemins')

    def _post(self, corps):
        import json
        return self.client.post(self.url, data=json.dumps(corps), content_type='application/json')

    def test_des_chemins_rendent_destinations_et_endpoint(self):
        rep = self._post({'paths': [f'{self.dossier}/a.png']})
        self.assertEqual(200, rep.status_code, rep.content[:200])
        d = rep.json()
        self.assertTrue(d['destinations'])
        self.assertEqual(reverse('filemanager:api_import'), d['endpoint'])

    def test_un_dossier_rend_ses_destinations(self):
        rep = self._post({'folder': self.dossier})
        self.assertEqual(200, rep.status_code, rep.content[:200])
        self.assertEqual(self.dossier, rep.json()['folder'])
        self.assertTrue(rep.json()['destinations'])

    def test_un_chemin_que_l_IMPORT_refuserait_n_obtient_pas_de_menu(self):
        """La garde de chemin est CELLE de l'import (`is_path_allowed`), pas une copie."""
        from wama.common.utils.media_paths import app_media_dir
        autre = _utilisateur('envoi_chemins_autrui')
        etranger = f"{app_media_dir('converter', autre.id, 'output')}/b.png"
        self.assertEqual(403, self._post({'paths': [etranger]}).status_code)
        self.assertEqual(403, self._post({'folder': app_media_dir('converter', autre.id, 'output')}).status_code)

    def test_sans_chemin_400_et_en_GET_405(self):
        self.assertEqual(400, self._post({}).status_code)
        self.assertEqual(405, self.client.get(self.url).status_code)


class ArbreSansCalculClientTest(TestCase):
    """L'arbre ne DÉRIVE plus ses destinations chez le client : deux dérivations des mêmes
    conditions divergeaient (celle du client ne vérifiait pas l'accès). Garde sur le CODE, sans
    ses commentaires — un commentaire qui cite l'ancien mécanisme ne le rebranche pas."""

    def _code(self, *rel):
        import re
        from django.conf import settings
        from pathlib import Path
        texte = (Path(settings.BASE_DIR).joinpath(*rel)).read_text(encoding='utf-8')
        texte = re.sub(r'/\*.*?\*/', '', texte, flags=re.S)
        texte = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', '', texte, flags=re.S)
        return re.sub(r'(^|[^:\'"\\])//[^\n]*', r'\1', texte)

    def test_filemanager_js_passe_par_le_resolveur_serveur(self):
        code = self._code('wama', 'filemanager', 'static', 'filemanager', 'js', 'filemanager.js')
        for ancien in ('WAMA_FILEMANAGER_IMPORTERS', 'input_extensions', 'buildSendToSubmenu'):
            self.assertNotIn(ancien, code, f"l'arbre recalcule ses destinations : `{ancien}`")
        self.assertIn('WamaSendTo.entreesPourChemins', code)
        self.assertIn('WamaSendTo.entreesPourDossier', code)

    def test_la_liste_client_n_est_plus_publiee(self):
        code = self._code('wama', 'filemanager', 'templates', 'filemanager', 'sidebar.html')
        self.assertNotIn('WAMA_FILEMANAGER_IMPORTERS', code)


class ElementPourCheminTest(TestCase):
    """`item_for_output_path` — l'INVERSE de `sorties_de`, pour l'arbre de fichiers (2026-09-18).

    Les gestes du menu « … » (partager, médiathèque, RAG) sont définis sur un ÉLÉMENT ; un
    fichier de l'arbre ne les obtient qu'en remontant à l'élément dont il est la SORTIE. Ce
    que ces tests tiennent : c'est l'ADAPTER qui confirme (une entrée d'élément n'est pas une
    sortie), le périmètre est celui de l'utilisateur, et l'encodage d'URL ne fait pas rater.
    """

    def setUp(self):
        self.u = _utilisateur('chemin_elem')
        self.autre = _utilisateur('chemin_autre')

    def _job(self, user, sortie='a.webp', entree=''):
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        job = ConversionJob.objects.create(user=user, input_filename='a.png')
        if sortie:
            job.output_file.name = f"{app_media_dir('converter', user.id, 'output')}/{sortie}"
        if entree:
            job.input_file.name = f"{app_media_dir('converter', user.id, 'input')}/{entree}"
        job.save()
        return job

    def test_la_sortie_declaree_remonte_a_son_element(self):
        from wama.common.services.send_to import item_for_output_path
        job = self._job(self.u)
        surface, element = item_for_output_path(self.u, job.output_file.name)
        self.assertEqual((surface, element), ('converter', job))

    def test_la_surface_rendue_est_celle_que_porte_une_card(self):
        """Partage, médiathèque et RAG lisent `data-preview-url` : la surface doit être connue
        du registre de PREVIEW avec le MÊME modèle, sinon les gestes tomberaient en 404."""
        from wama.common.services.send_to import item_for_output_path
        from wama.common.utils.preview_registry import PreviewRegistry
        job = self._job(self.u)
        surface, element = item_for_output_path(self.u, job.output_file.name)
        self.assertIs(PreviewRegistry.get_model(surface), type(element))

    def test_une_ENTREE_d_element_n_est_pas_une_sortie(self):
        """Le `FileField` d'entrée référence le chemin, mais l'adapter ne le DÉCLARE pas comme
        résultat : partager « ce fichier » ouvrirait le partage d'un élément dont il n'est pas
        le résultat. C'est la confirmation par `sorties_de` qui l'écarte."""
        from wama.common.services.send_to import item_for_output_path
        job = self._job(self.u, sortie='b.webp', entree='b.png')
        self.assertEqual((None, None), item_for_output_path(self.u, job.input_file.name))
        self.assertEqual(('converter', job), item_for_output_path(self.u, job.output_file.name))

    def test_l_element_d_un_autre_utilisateur_n_est_JAMAIS_rendu(self):
        from wama.common.services.send_to import item_for_output_path
        job = self._job(self.autre)
        self.assertEqual((None, None), item_for_output_path(self.u, job.output_file.name))
        self.assertEqual(('converter', job), item_for_output_path(self.autre, job.output_file.name))

    def test_un_nom_encode_dans_l_URL_se_resout_quand_meme(self):
        """L'adapter rend l'URL d'un `FieldFile` (percent-encodée) ; le chemin de l'arbre est
        brut. Sans `unquote`, un fichier avec une espace ne remonterait jamais."""
        from wama.common.services.send_to import item_for_output_path, sorties_de
        job = self._job(self.u, sortie='mon fichier é.webp')
        self.assertIn('%20', sorties_de('converter', job)[0], 'le cas ne teste rien si rien n’est encodé')
        self.assertEqual(('converter', job), item_for_output_path(self.u, job.output_file.name))

    def test_les_sorties_en_JSON_de_l_imager_se_resolvent_aussi(self):
        """L'imager ne range pas ses images dans un `FileField` mais dans un JSON de chemins
        ABSOLUS (`generated_images`) : la sélection des candidats passe par le nom de fichier,
        et c'est `output_images` (l'accesseur) qui confirme via l'adapter."""
        from pathlib import Path
        from django.conf import settings
        from wama.common.services.send_to import item_for_output_path
        from wama.common.utils.media_paths import app_media_dir
        from wama.imager.models import ImageGeneration
        rel = f"{app_media_dir('imager', self.u.id, 'output')}/img_test_chemin.png"
        absolu = Path(settings.MEDIA_ROOT) / rel
        absolu.parent.mkdir(parents=True, exist_ok=True)
        absolu.write_bytes(b'\x89PNG')
        try:
            g = ImageGeneration.objects.create(user=self.u, prompt='x', generated_images=[str(absolu)])
            self.assertEqual(('imager', g), item_for_output_path(self.u, rel))
        finally:
            absolu.unlink(missing_ok=True)

    def test_un_chemin_inconnu_ou_un_anonyme_rendent_None_sans_lever(self):
        from django.contrib.auth.models import AnonymousUser
        from wama.common.services.send_to import item_for_output_path
        self.assertEqual((None, None), item_for_output_path(self.u, f'users/{self.u.id}/temp/x.png'))
        self.assertEqual((None, None), item_for_output_path(self.u, ''))
        self.assertEqual((None, None), item_for_output_path(AnonymousUser(), 'users/1/converter/output/a.webp'))


class ApiElementPourCheminTest(TestCase):
    """L'endpoint du menu de l'arbre : même garde de chemin que l'import, coordonnées ou nulls."""

    def setUp(self):
        self.u = _utilisateur('chemin_api')
        self.client.force_login(self.u)
        self.url = reverse('common:api_item_for_path')

    def test_sans_chemin_400(self):
        self.assertEqual(self.client.get(self.url).status_code, 400)

    def test_un_chemin_hors_perimetre_est_REFUSE_par_la_garde_d_import(self):
        r = self.client.get(self.url, {'path': 'users/999999/converter/output/x.png'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(self.url, {'path': '../settings.py'}).status_code, 403)

    def test_un_fichier_qui_n_est_la_sortie_de_rien_rend_des_nulls(self):
        r = self.client.get(self.url, {'path': f'users/{self.u.id}/temp/x.png'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()['surface'], r.json()['pk']), (None, None))

    def test_une_sortie_rend_les_coordonnees_de_sa_card(self):
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        job.output_file.name = f"{app_media_dir('converter', self.u.id, 'output')}/a.webp"
        job.save(update_fields=['output_file'])
        r = self.client.get(self.url, {'path': job.output_file.name})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['surface'], r.json()['pk']), ('converter', job.pk))

    def test_anonyme_refuse(self):
        self.client.logout()
        self.assertIn(self.client.get(self.url, {'path': 'users/1/temp/x.png'}).status_code, (302, 403))
