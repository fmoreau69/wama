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
        from wama.converter.models import ConversionJob
        job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        job.output_file.name = f'converter/{self.u.id}/output/a.webp'
        job.save(update_fields=['output_file'])
        self.assertEqual([f'converter/{self.u.id}/output/a.webp'],
                         sorties_de('converter', job))

    def test_le_chemin_rendu_est_celui_qu_AUTORISE_la_garde_d_import(self):
        """Le contrat entre les deux endpoints : ce que l'un rend, l'autre doit l'accepter.

        `is_path_allowed` n'autorise que `<app>/<user_id>/…`. Si la forme du chemin de sortie
        changeait, l'envoi échouerait avec un « Access denied » incompréhensible — c'est
        exactement le genre de couture qu'aucun des deux côtés ne teste tout seul.
        """
        from wama.converter.models import ConversionJob
        from wama.filemanager.views import is_path_allowed
        job = ConversionJob.objects.create(user=self.u, input_filename='a.png')
        job.output_file.name = f'converter/{self.u.id}/output/a.webp'
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
