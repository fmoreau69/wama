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
        from wama.common.utils.media_paths import app_media_dir
        self.job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        # Jumeau de la fixture du test `sorties_de` plus haut, porté le 12/09 avec la même
        # remarque — celle-ci avait été oubliée (relevé le 2026-09-22).
        self.output_name = f"{app_media_dir('converter', self.u.id, 'output')}/a.png"
        self.job.output_file.name = self.output_name
        self.job.save(update_fields=['output_file'])

    def _url(self, surface='converter', pk=None):
        return reverse('common:api_envoyer_vers', args=[surface, pk or self.job.id])

    def test_le_resolveur_rend_chemins_destinations_et_endpoint(self):
        rep = self.client.get(self._url())
        self.assertEqual(200, rep.status_code, rep.content[:200])
        d = rep.json()
        self.assertEqual([self.output_name], d['chemins'])
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


def _surfaces_with_batches():
    """`(surface, modèle d'élément)` de chaque surface à LOT — registre de preview, jumelles de
    bac à sable exclues (leurs tables ne sont pas celles de la base de test). Aucune app nommée :
    une app de plus est couverte sans toucher ce fichier."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.utils.batch_common import batch_model_for_app
    from wama.common.utils.preview_registry import PreviewRegistry
    found = []
    for surface in PreviewRegistry.list_registered():
        spec = APP_CATALOG.get(surface) or {}
        if spec.get('generated_from') or spec.get('sandbox'):
            continue
        model = PreviewRegistry.get_model(surface)
        if model is not None and batch_model_for_app(surface) is not None:
            found.append((surface, model))
    return found


class BatchSendToContractTest(TestCase):
    """« Envoyer le lot vers… » (2026-10-14) — contrat GÉNÉRIQUE, toutes les surfaces à lot.

    Un lot envoie exactement la somme de ses cards : les sorties de `sorties_de`, élément par
    élément, dans l'ordre des lignes ; les éléments sans sortie sont comptés, jamais envoyés.
    """

    def setUp(self):
        self.u = _utilisateur('batch_send_contract')
        self.client.force_login(self.u)

    def _url(self, surface, pk):
        return reverse('common:api_send_batch_to', args=[surface, pk])

    def test_every_batch_sends_the_outputs_of_its_cards_in_row_order(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        surfaces = _surfaces_with_batches()
        self.assertGreaterEqual(len(surfaces), 10, [s for s, _ in surfaces])
        for surface, model in surfaces:
            with self.subTest(surface=surface):
                batch, elements = _lot_de(model, self.u, 2)
                response = self.client.get(self._url(surface, batch.pk))
                self.assertEqual(200, response.status_code, response.content[:200])
                data = response.json()
                expected = []
                for element in elements:
                    expected += [p for p in sorties_de(surface, element) if p not in expected]
                self.assertEqual(expected, data['chemins'])
                self.assertEqual(2, data['elements'])
                self.assertEqual(sum(not sorties_de(surface, e) for e in elements),
                                 data['without_output'])
                # L'envoi passe par l'import EXISTANT — rendu, jamais écrit dans le JS.
                self.assertEqual(reverse('filemanager:api_import'), data['endpoint'])

    def test_a_batch_of_another_user_is_never_resolved(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        other = _utilisateur('batch_send_other')
        for surface, model in _surfaces_with_batches():
            with self.subTest(surface=surface):
                batch, _ = _lot_de(model, other, 1)
                self.assertEqual(404, self.client.get(self._url(surface, batch.pk)).status_code)

    def test_an_unknown_surface_answers_404(self):
        self.assertEqual(404, self.client.get(self._url('not_an_app', 1)).status_code)


class BatchSendToConverterTest(TestCase):
    """Le cas concret, sur des sorties réelles : ordre, élément sans résultat, partiel annoncé."""

    def setUp(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        self.u = _utilisateur('batch_send_converter')
        self.client.force_login(self.u)
        self.batch, jobs = _lot_de(ConversionJob, self.u, 3)
        folder = app_media_dir('converter', self.u.id, 'output')
        # Lignes 0 et 2 rendues, ligne 1 sans résultat ; un .wav pour mêler deux formats.
        for job, name in zip(jobs, ('b.png', '', 'a.wav')):
            job.output_file.name = f'{folder}/{name}' if name else ''
            job.save(update_fields=['output_file'])
        self.expected = [f'{folder}/b.png', f'{folder}/a.wav']

    def _get(self):
        response = self.client.get(reverse('common:api_send_batch_to',
                                           args=['converter', self.batch.pk]))
        self.assertEqual(200, response.status_code, response.content[:200])
        return response.json()

    def test_the_outputs_leave_in_row_order_and_the_missing_one_is_counted(self):
        data = self._get()
        self.assertEqual(self.expected, data['chemins'])
        self.assertEqual((3, 1), (data['elements'], data['without_output']))

    def test_each_destination_says_which_files_it_takes(self):
        from wama.common.app_registry import APP_CATALOG
        data = self._get()
        self.assertTrue(data['destinations'], 'aucune app pour png + wav, même en partiel')
        for destination in data['destinations']:
            accepted = {e.lower() for e in
                        (APP_CATALOG.get(destination['app']) or {}).get('input_extensions', ())}
            self.assertTrue(destination['acceptes'], destination)
            for path in destination['acceptes']:
                self.assertIn(path, self.expected)
                self.assertIn('.' + path.rsplit('.', 1)[-1], accepted, destination)

    def test_every_resolved_path_passes_the_import_guard(self):
        from wama.filemanager.views import is_path_allowed
        for path in self._get()['chemins']:
            self.assertTrue(is_path_allowed(path, self.u), path)

    def test_resolving_changes_nothing(self):
        before = list(self.batch.items.order_by('batch_row_index')
                      .values_list('pk', 'output_file'))
        self._get()
        self.assertEqual(before, list(self.batch.items.order_by('batch_row_index')
                                      .values_list('pk', 'output_file')))


class BatchSentArrivesAsABatchTest(TestCase):
    """Le geste ENTIER, par les deux endpoints réels : résoudre le lot, puis l'envoyer comme le
    fait la brique JS — les fichiers arrivent en UN lot chez la destination (regroupement « par
    arrivée » de l'import), dans l'ordre des lignes du lot source."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        media = tempfile.mkdtemp(prefix='wama_batch_send_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        setting = override_settings(MEDIA_ROOT=media)
        setting.enable()
        self.addCleanup(setting.disable)
        self.media = Path(media)
        self.u = User.objects.create_user('batch_send_e2e', password='x', is_staff=True,
                                          is_superuser=True)
        self.client.force_login(self.u)

    def test_a_converter_batch_sent_to_the_reader_arrives_as_one_batch(self):
        import io
        import json
        from PIL import Image
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        from wama.reader.models import BatchReadingItem, ReadingItem
        batch, jobs = _lot_de(ConversionJob, self.u, 2)
        folder = app_media_dir('converter', self.u.id, 'output')
        for job, name in zip(jobs, ('first.png', 'second.png')):
            buffer = io.BytesIO()
            Image.new('RGB', (8, 8), (20, 120, 200)).save(buffer, format='PNG')
            (self.media / folder).mkdir(parents=True, exist_ok=True)
            (self.media / folder / name).write_bytes(buffer.getvalue())
            job.output_file.name = f'{folder}/{name}'
            job.save(update_fields=['output_file'])

        resolved = self.client.get(reverse('common:api_send_batch_to',
                                           args=['converter', batch.pk])).json()
        reader = next(d for d in resolved['destinations'] if d['app'] == 'reader')
        before = set(BatchReadingItem.objects.filter(user=self.u).values_list('pk', flat=True))
        sent = self.client.post(resolved['endpoint'],
                                json.dumps({'paths': reader['acceptes'], 'app': 'reader'}),
                                content_type='application/json')
        self.assertEqual(200, sent.status_code, sent.content[:300])
        self.assertEqual(2, sent.json()['count'], sent.json())

        new_batches = BatchReadingItem.objects.filter(user=self.u).exclude(pk__in=before)
        self.assertEqual(1, new_batches.count(), 'le lot envoyé est arrivé en plusieurs morceaux')
        names = [link.reading.original_filename
                 for link in new_batches.get().items.select_related('reading').order_by('row_index')]
        self.assertEqual(['first.png', 'second.png'], names)
        self.assertEqual(2, ReadingItem.objects.filter(user=self.u).count())


class ReceivedCardSendToTest(TestCase):
    """« Envoyer vers » depuis une card REÇUE (2026-10-16). En mode lecture, le destinataire peut
    « voir, télécharger, ENVOYER VERS une autre app, dupliquer » (`WAMA_COLLABORATION §3bis`) :
    le menu offrait le geste, le résolveur ne servait que les cards du compte (404 → sous-menu
    « Indisponible ») et l'import refusait le chemin. Les deux portes suivent désormais la règle
    qui MONTRE la card (`listable_by`), et le fichier est COPIÉ chez le destinataire."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        from django.test import override_settings
        media = tempfile.mkdtemp(prefix='wama_received_send_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        setting = override_settings(MEDIA_ROOT=media)
        setting.enable()
        self.addCleanup(setting.disable)
        self.media = Path(media)
        self.owner = _utilisateur('received_send_owner')
        self.bob = _utilisateur('received_send_bob')
        self.stranger = _utilisateur('received_send_stranger')

    def _job_with_output(self, name='shared.png'):
        import io
        from PIL import Image
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        folder = app_media_dir('converter', self.owner.id, 'output')
        (self.media / folder).mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), (90, 20, 200)).save(buffer, format='PNG')
        (self.media / folder / name).write_bytes(buffer.getvalue())
        job = ConversionJob.objects.create(user=self.owner, input_filename='a.png')
        job.output_file.name = f'{folder}/{name}'
        job.save(update_fields=['output_file'])
        return job

    def _share(self, target, nature='element'):
        from wama.common.services.sharing import share_with_person
        from wama.converter.models import ConversionJob
        share_with_person(self.owner, target, ConversionJob, self.bob, nature=nature)

    def test_a_received_card_resolves_its_output_and_its_destinations(self):
        job = self._job_with_output()
        self._share(job)
        self.client.force_login(self.bob)
        data = self.client.get(reverse('common:api_envoyer_vers', args=['converter', job.pk])).json()
        self.assertEqual([job.output_file.name], data['chemins'])
        self.assertTrue(data['destinations'])

    def test_the_output_is_readable_by_the_recipient_only(self):
        from wama.common.utils.media_paths import readable_by
        job = self._job_with_output()
        self._share(job)
        self.assertTrue(readable_by(job.output_file.name, self.bob))
        self.assertFalse(readable_by(job.output_file.name, self.stranger))

    def test_sending_it_gives_the_recipient_his_own_copy(self):
        import json
        from wama.reader.models import ReadingItem
        job = self._job_with_output()
        self._share(job)
        self.client.force_login(self.bob)
        sent = self.client.post(reverse('filemanager:api_import'),
                                json.dumps({'path': job.output_file.name, 'app': 'reader'}),
                                content_type='application/json')
        self.assertEqual(200, sent.status_code, sent.content[:300])
        self.assertTrue(sent.json().get('imported'), sent.json())
        item = ReadingItem.objects.get(pk=sent.json()['id'])
        self.assertEqual(self.bob, item.user)
        self.assertTrue(item.input_file.name.startswith(f'users/{self.bob.id}/'),
                        f"{item.input_file.name} : l'entrée du destinataire doit être SA copie")

    def test_a_card_that_is_not_shared_stays_refused_at_both_doors(self):
        import json
        job = self._job_with_output()
        self.client.force_login(self.stranger)
        self.assertEqual(404, self.client.get(
            reverse('common:api_envoyer_vers', args=['converter', job.pk])).status_code)
        refused = self.client.post(reverse('filemanager:api_import'),
                                   json.dumps({'path': job.output_file.name, 'app': 'reader'}),
                                   content_type='application/json').json()
        self.assertFalse(refused.get('imported'))
        self.assertEqual('Access denied', refused.get('error'))

    def test_a_received_batch_sends_the_outputs_its_recipient_sees(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        from wama.converter.models import ConversionJob
        batch, jobs = _lot_de(ConversionJob, self.owner, 2)
        for job, name in zip(jobs, ('one.png', 'two.png')):
            source = self._job_with_output(name)
            job.output_file.name = source.output_file.name
            job.save(update_fields=['output_file'])
        self._share(batch, nature='lot')
        self.client.force_login(self.bob)
        data = self.client.get(reverse('common:api_send_batch_to',
                                       args=['converter', batch.pk])).json()
        self.assertEqual(sorted(j.output_file.name for j in jobs), sorted(data['chemins']))
        self.client.force_login(self.stranger)
        self.assertEqual(404, self.client.get(reverse('common:api_send_batch_to',
                                                      args=['converter', batch.pk])).status_code)


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
