"""ABONNEMENT — la couche PRÉFÉRENCE (PROFILES_PERMISSIONS §8, jalon S1).

POURQUOI CES TESTS. Le mécanisme est muet par construction : masquer une app ne lève rien, et un
filtrage qui filtrerait TROP (ou pas du tout) se lirait « c'est cassé » sans qu'aucune trace ne
dise pourquoi. Deux propriétés doivent donc être PROUVÉES, jamais relues :

  1. une préférence ne peut que RESTREINDRE — aucune ligne de cette table n'ouvre un accès ;
  2. les DEUX MOITIÉS du geste — l'app masquée disparaît du MENU **et** reste dans le CATALOGUE.
     N'éprouver que la première laisserait passer le pire défaut possible : une app qu'on ne peut
     plus retrouver nulle part, donc plus jamais réafficher.

⚠ Aucun test ne fige la liste des apps ni un compte d'apps : l'ensemble autorisé se MESURE au
moment du test (`accessible`), sinon ajouter une app au catalogue rendrait ces tests faux.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse

from wama.common.models import ElementPreference
from wama.common.services import subscriptions as abo


def _apps_autorisees(user):
    """Tout ce qui est SOUS CONTRÔLE d'accès et autorisé — la mesure du DROIT, telle quelle."""
    from wama.accounts.permissions import accessible, all_gated_apps
    return sorted(a for a in all_gated_apps() if accessible(user, a))


def _apps_catalogue_autorisees(user):
    """…restreint aux apps qui ont une CARD dans le catalogue.

    ⚠ Les deux ensembles diffèrent RÉELLEMENT (mesuré) : `all_gated_apps()` dérive de
    `DEFAULT_APP_ACCESS`, qui garde des surfaces sans entrée dans `APP_CATALOG` (`media_library`).
    Confondre les deux ferait échouer le bandeau sur un écart qui n'est pas le sien."""
    from wama.common.app_registry import APP_CATALOG
    return [a for a in _apps_autorisees(user) if a in APP_CATALOG]


class ServiceAbonnementTests(TestCase):
    """Le service seul — sans vue, sans gabarit."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('abo_service_test', password='x')

    def test_un_compte_neuf_est_abonne_a_tout_sans_aucune_ligne(self):
        # Le DÉFAUT est l'absence de ligne : c'est ce qui évite de semer une ligne par
        # (utilisateur × élément) et de maintenir un invariant qui dériverait.
        self.assertEqual(ElementPreference.objects.filter(user=self.user).count(), 0)
        self.assertEqual(abo.masques(self.user, 'app'), set())
        self.assertTrue(abo.est_abonne(self.user, 'app', 'transcriber'))

    def test_se_desabonner_ecrit_une_ligne_se_reabonner_l_efface(self):
        self.assertFalse(abo.definir(self.user, 'app', 'transcriber', False))
        self.assertEqual(ElementPreference.objects.filter(user=self.user, kind='app').count(), 1)
        self.assertFalse(abo.est_abonne(self.user, 'app', 'transcriber'))
        # Réabonnement : la ligne DISPARAÎT (deux représentations du même état divergeraient).
        self.assertTrue(abo.definir(self.user, 'app', 'transcriber', True))
        self.assertEqual(ElementPreference.objects.filter(user=self.user, kind='app').count(), 0)

    def test_filtrer_preserve_l_ordre_et_n_ajoute_jamais_rien(self):
        abo.definir(self.user, 'app', 'imager', False)
        entree = ['transcriber', 'imager', 'describer']
        sortie = abo.filtrer(self.user, 'app', entree)
        self.assertEqual(sortie, ['transcriber', 'describer'])
        # 🔴 L'INVARIANT du §8.1 : la sortie est un SOUS-ensemble de l'entrée. Un filtre qui
        # saurait ajouter un élément serait une élévation de droit déguisée.
        self.assertTrue(set(sortie) <= set(entree))

    def test_filtrer_ne_peut_rien_ajouter_meme_avec_une_ligne_a_true(self):
        # `subscribed=True` reste stockable (usage futur) : on prouve qu'une telle ligne
        # n'introduit PAS l'élément dans une liste qui ne le contenait pas.
        ElementPreference.objects.create(user=self.user, kind='app',
                                         element_id='anonymizer', subscribed=True)
        self.assertEqual(abo.filtrer(self.user, 'app', ['transcriber']), ['transcriber'])

    def test_tout_masquer_puis_tout_afficher(self):
        ids = ['transcriber', 'imager', 'describer']
        self.assertEqual(abo.definir_lot(self.user, 'app', ids, False), 3)
        self.assertEqual(abo.filtrer(self.user, 'app', ids), [])
        # « Tout afficher » efface la nature ENTIÈRE — y compris un élément absent de la page
        # courante, sinon il resterait masqué sans surface pour le retrouver.
        abo.definir(self.user, 'app', 'hors_page', False)
        abo.definir_lot(self.user, 'app', ids, True)
        self.assertEqual(abo.masques(self.user, 'app'), set())

    def test_masquer_deux_fois_ne_cree_pas_de_doublon(self):
        abo.definir(self.user, 'app', 'imager', False)
        abo.definir(self.user, 'app', 'imager', False)
        abo.definir_lot(self.user, 'app', ['imager', 'describer'], False)
        self.assertEqual(
            ElementPreference.objects.filter(user=self.user, kind='app', element_id='imager').count(), 1)

    def test_le_resume_compte_ce_qui_est_masque(self):
        abo.definir(self.user, 'app', 'imager', False)
        self.assertEqual(abo.resume(self.user, 'app', ['transcriber', 'imager', 'describer']),
                         {'total': 3, 'abonnes': 2, 'masques': 1})

    def test_une_nature_inconnue_leve_au_lieu_de_filtrer_dans_le_vide(self):
        # Sans cette garde, une faute de frappe rendrait un ensemble vide — donc « aucun
        # masquage », donc un mécanisme muet qui a l'air de marcher.
        with self.assertRaises(ValueError):
            abo.masques(self.user, 'apps')
        with self.assertRaises(ValueError):
            abo.definir(self.user, 'app_inconnue', 'x', False)

    def test_l_anonyme_ne_porte_aucune_preference(self):
        # Écrire pour `anonymous` vaudrait pour TOUS ses visiteurs.
        anon = get_user_model().objects.create_user('anonymous', password='x')
        self.assertTrue(abo.definir(anon, 'app', 'imager', False))
        self.assertEqual(ElementPreference.objects.filter(user=anon).count(), 0)
        self.assertEqual(abo.masques(AnonymousUser(), 'app'), set())
        self.assertEqual(abo.filtrer(AnonymousUser(), 'app', ['imager']), ['imager'])


class EndpointAbonnementTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('abo_api_test', password='x')

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('common:api_subscription')

    def _post(self, charge):
        return self.client.post(self.url, data=charge, content_type='application/json')

    def test_bascule_unitaire_aller_retour(self):
        r = self._post({'kind': 'app', 'element_id': 'imager', 'subscribed': False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['subscribed'], False)
        self.assertEqual(abo.masques(self.user, 'app'), {'imager'})
        r = self._post({'kind': 'app', 'element_id': 'imager', 'subscribed': True})
        self.assertEqual(r.json()['subscribed'], True)
        self.assertEqual(abo.masques(self.user, 'app'), set())

    def test_le_lot_renvoie_l_etat_du_serveur(self):
        r = self._post({'kind': 'app', 'all': False, 'ids': ['imager', 'describer']})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sorted(r.json()['masques']), ['describer', 'imager'])

    def test_une_nature_inconnue_est_refusee(self):
        self.assertEqual(self._post({'kind': 'modele', 'element_id': 'x'}).status_code, 400)
        self.assertEqual(self._post({'kind': 'app'}).status_code, 400)
        self.assertEqual(
            self.client.post(self.url, data='pas du json', content_type='application/json').status_code, 400)

    def test_l_endpoint_exige_une_session(self):
        self.client.logout()
        r = self._post({'kind': 'app', 'element_id': 'imager', 'subscribed': False})
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(ElementPreference.objects.count(), 0)

    def test_l_endpoint_n_ouvre_aucun_acces(self):
        # 🔴 La propriété centrale : quoi qu'on poste, l'ensemble des apps AUTORISÉES ne bouge
        # pas d'un pouce. C'est ce qui autorise un simple `@login_required` ici.
        avant = _apps_autorisees(self.user)
        for cible in ('imager', 'model_manager', 'app_inexistante'):
            self._post({'kind': 'app', 'element_id': cible, 'subscribed': True})
        self.assertEqual(_apps_autorisees(self.user), avant)


class MenuEtCatalogueTests(TestCase):
    """Les DEUX moitiés du geste — le menu retire, le catalogue conserve."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('abo_nav_test', password='x')

    def setUp(self):
        self.client.force_login(self.user)
        autorisees = _apps_catalogue_autorisees(self.user)
        # Garde d'INSTRUMENT : sans app autorisée ET présente au catalogue, tout ce qui suit
        # passerait sur du vide — le harnais qui annonce « 0 échec » parce qu'il ne voit rien.
        self.assertTrue(autorisees, "aucune app autorisée au catalogue : le test ne mesurerait rien")
        self.cible = autorisees[0]

    def _nav_apps(self):
        r = self.client.get(reverse('common:apps_catalog'))
        return r, {a['name'] for g in r.context['nav_apps_grouped'] for a in g['apps']}

    def test_une_app_masquee_quitte_le_menu_et_reste_au_catalogue(self):
        _, avant = self._nav_apps()
        self.assertIn(self.cible, avant)

        abo.definir(self.user, 'app', self.cible, False)
        r, apres = self._nav_apps()
        self.assertNotIn(self.cible, apres)
        # …mais la card est TOUJOURS dans le catalogue, marquée `masquees` : c'est le seul
        # endroit où la retrouver, donc le seul endroit où pouvoir la réafficher.
        card = next(a for a in r.context['apps_list'] if a['name'] == self.cible)
        self.assertTrue(card['autorisee'])
        self.assertFalse(card['abonne'])
        self.assertContains(r, 'data-abo-id="%s"' % self.cible)

        abo.definir(self.user, 'app', self.cible, True)
        _, retour = self._nav_apps()
        self.assertEqual(retour, avant)

    def test_le_menu_annonce_combien_d_apps_sont_masquees(self):
        # Un filtrage SILENCIEUX se lirait « c'est cassé ». Le compte est donc rendu.
        abo.definir(self.user, 'app', self.cible, False)
        r = self.client.get(reverse('common:apps_catalog'))
        self.assertEqual(r.context['apps_masquees_count'], 1)
        self.assertContains(r, '1 masquée')

    def test_masquer_ne_ferme_aucune_porte(self):
        # Une préférence n'est pas un droit : l'app masquée reste ACCESSIBLE si on y va.
        from wama.accounts.permissions import accessible
        abo.definir(self.user, 'app', self.cible, False)
        self.assertTrue(accessible(self.user, self.cible))
        self.assertIn(self.cible, _apps_autorisees(self.user))

    def test_le_catalogue_declare_la_facette_abonnement(self):
        r = self.client.get(reverse('common:apps_catalog'))
        facettes = {f['cle'] for f in r.context['facettes_apps']}
        self.assertEqual(facettes, {'categorie', 'abonnement'})
        # Les valeurs rendues sur les cards sont EXACTEMENT celles déclarées par la facette :
        # une facette dont aucune card ne porte la valeur filtrerait vers le vide.
        options = next(f for f in r.context['facettes_apps'] if f['cle'] == 'abonnement')['options']
        for a in r.context['apps_list']:
            attendu = 'mes' if a['abonne'] else ('fermees' if not a['autorisee'] else 'masquees')
            self.assertIn(attendu, options)

    def test_le_resume_du_bandeau_ne_compte_que_les_apps_autorisees(self):
        r = self.client.get(reverse('common:apps_catalog'))
        # Le bandeau compte les CARDS autorisées — et cet ensemble est bien celui du droit,
        # restreint au catalogue (cf. `_apps_catalogue_autorisees`). La double dérivation est
        # vérifiée ici plutôt que relue : c'est le seul endroit où elles doivent coïncider.
        self.assertEqual(r.context['abo']['total'], len(_apps_catalogue_autorisees(self.user)))
        self.assertEqual({a['name'] for a in r.context['apps_list'] if a['autorisee']},
                         set(_apps_catalogue_autorisees(self.user)))
        self.assertEqual(r.context['abo']['masques'], 0)
        abo.definir(self.user, 'app', self.cible, False)
        r = self.client.get(reverse('common:apps_catalog'))
        self.assertEqual(r.context['abo']['masques'], 1)
