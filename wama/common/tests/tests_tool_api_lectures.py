"""
Gardes des LECTURES TRANSVERSES du pivot assistant — `list_my_items`, `get_item_detail`,
`list_registries` (décision `WAMA_MEMORY.md §9ter`, jalon 12).

POURQUOI un fichier de gardes plutôt que le seul scénario nocturne. Le scénario
`common.tool_api.lectures` appelle chaque lecture À VIDE : il attrape « ça lève » ou « ça rend
une erreur », rien de plus. Or ce que ces trois outils promettent n'est pas « ça répond » —
c'est l'ISOLATION entre utilisateurs, le refus nommé, et les deux réserves explicites de §9ter
(date comparable, clés brutes à côté de l'affichage). Rien de tout cela ne se voit à vide.
⭐ Leçon de la session du 2026-09-10, appliquée ici : *lancer n'est pas garder.*

⚠ `get_item_detail` EXIGE (app, pk) : il est volontairement absent de la liste nocturne, où un
appel à vide rendrait une erreur légitime comptée comme un échec. Sa garde est ICI.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama import tool_api as T


def _utilisateur(nom, role='communication'):
    """Utilisateur qui FRANCHIT le portier d'app, il ne le contourne pas.

    ⚠ Mesuré ici le 2026-09-11 : un compte neuf n'a AUCUN rôle, donc aucun accès à `imager` —
    les tests d'écriture rendaient tous `forbidden`, y compris ceux du chemin heureux. La voie
    `is_superuser=True` est ÉCARTÉE (même raison que `synthesizer/tests.py:38`) : neutraliser
    le portier rendrait ces tests aveugles à une régression du gating, qui est précisément ce
    que `_refus_app` doit tenir. `imager` exige le rôle `communication` (mesuré dans
    `DEFAULT_APP_ACCESS`), on l'accorde — et rien de plus, pour qu'il reste des apps REFUSÉES
    sur lesquelles éprouver la garde.
    """
    from django.contrib.auth.models import Group

    from wama.accounts.permissions import GROUP_PREFIX
    user = get_user_model().objects.create_user(username=nom, password='x')
    if role:
        groupe, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
        user.groups.add(groupe)
    return user


def _item(user, prompt='une image de test'):
    """Le modèle le plus léger du registre de détail : ni fichier, ni dépendance."""
    from wama.imager.models import ImageGeneration
    return ImageGeneration.objects.create(user=user, prompt=prompt)


class ListMyItemsTest(TestCase):
    def setUp(self):
        self.moi = _utilisateur('moi')
        self.autre = _utilisateur('autre')

    def test_ne_rend_que_mes_elements(self):
        """L'ownership est la SEULE garantie de ces outils transverses (ils ne passent pas par
        le gating d'app) — c'est donc elle qu'il faut prouver, pas supposer."""
        _item(self.moi, 'à moi')
        _item(self.autre, 'à l’autre')
        out = T.list_my_items(self.moi)
        titres = ' '.join(str(i.get('titre') or '') for i in out['items'])
        self.assertNotIn('à l’autre', titres)
        self.assertTrue(all(i['app'] for i in out['items']))

    def test_refuse_un_statut_inconnu_en_nommant_les_valides(self):
        """Une erreur qui ne dit pas les valeurs acceptables oblige le modèle à deviner."""
        out = T.list_my_items(self.moi, statut='nawak')
        self.assertIn('error', out)
        self.assertIn('nawak', out['error'])
        self.assertIn('all', out['error'])

    def test_borne_la_limite_au_lieu_de_casser(self):
        """Un LLM envoie volontiers `limite=100000` ou `limite='beaucoup'`."""
        _item(self.moi)
        self.assertLessEqual(len(T.list_my_items(self.moi, limite=10 ** 6)['items']), 100)
        self.assertIsInstance(T.list_my_items(self.moi, limite='beaucoup')['items'], list)

    def test_la_date_est_comparable_pas_un_affichage(self):
        """Réserve 1 de §9ter : l'adapter rend « 12/08/2026 14:03 », lossy pour le calcul.
        Le listing doit rendre une date qu'on peut TRIER et COMPARER."""
        _item(self.moi)
        date = T.list_my_items(self.moi)['items'][0]['date']
        self.assertIsNotNone(date)
        from datetime import datetime
        datetime.fromisoformat(date)          # lève si ce n'est pas de l'ISO

    def test_refuse_l_anonyme(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIn('error', T.list_my_items(AnonymousUser()))


class GetItemDetailTest(TestCase):
    def setUp(self):
        self.moi = _utilisateur('moi2')
        self.autre = _utilisateur('autre2')

    def test_refuse_l_element_d_un_autre_utilisateur(self):
        """MÊME règle que `unified_detail` : si les deux portes divergent, l'assistant voit
        autre chose que l'inspecteur."""
        item = _item(self.autre)
        out = T.get_item_detail(self.moi, 'imager', item.pk)
        self.assertEqual(out.get('error'), 'forbidden')

    def test_nomme_les_apps_connues_quand_l_app_est_inconnue(self):
        out = T.get_item_detail(self.moi, 'app_qui_nexiste_pas', 1)
        self.assertIn('error', out)
        self.assertIn('imager', out['error'])

    def test_dit_introuvable_sans_lever_sur_un_pk_absent(self):
        out = T.get_item_detail(self.moi, 'imager', 10 ** 9)
        self.assertIn('error', out)
        self.assertNotEqual(out.get('error'), 'forbidden')

    def test_porte_les_cles_BRUTES_a_cote_de_l_affichage(self):
        """Réserve 1 de §9ter, l'autre moitié : `detail` est fait pour être lu, `raw` pour être
        calculé. Sans `raw`, un statut n'est lisible que via un libellé traduit."""
        item = _item(self.moi)
        out = T.get_item_detail(self.moi, 'imager', item.pk)
        self.assertIn('detail', out)
        self.assertIn('raw', out)
        self.assertIn('status', out['raw'])
        self.assertEqual(out['raw']['status'], item.status)


class ListRegistriesTest(TestCase):
    def test_rend_chaque_registre_avec_sa_nature(self):
        """La `nature` est ce qui dit à l'assistant CE QU'IL LIT : une mesure du système réel
        n'a pas le même statut épistémique qu'une redéclaration de code."""
        out = T.list_registries(_utilisateur('moi3'))
        self.assertGreater(out['count'], 0)
        natures = {r['nature'] for r in out['registries']}
        self.assertTrue(natures <= {'mesure', 'derive', 'redeclaration', 'scan'}, natures)
        self.assertTrue(all(r['key'] and r['label'] for r in out['registries']))


class GetItemPreviewTest(TestCase):
    def setUp(self):
        self.moi = _utilisateur('prev1')
        self.autre = _utilisateur('prev2')

    def test_l_hote_FABRIQUE_ne_fuite_JAMAIS_dans_une_reponse(self):
        """🔴 LA garde de cet outil. Les adapters appellent `build_absolute_uri()`, qui exige un
        hôte : la requête synthétique en fabrique un FAUX. S'il sortait, l'assistant proposerait
        une URL qui ne résout nulle part — un lien mort présenté comme valide."""
        from wama.tool_api import _HOTE_SYNTHETIQUE
        item = _item(self.moi)
        out = T.get_item_preview(self.moi, 'imager', item.pk)
        self.assertNotIn(_HOTE_SYNTHETIQUE, json.dumps(out, default=str))

    def test_le_normaliseur_rend_bien_un_chemin_relatif(self):
        """Garde DIRECTE du normaliseur — le test ci-dessus serait vert sur une charge SANS
        aucune URL (donc vacueux). Celui-ci ne peut pas l'être : il fournit les URL lui-même."""
        from wama.tool_api import _HOTE_SYNTHETIQUE, _url_relative
        charge = {'url': f'http://{_HOTE_SYNTHETIQUE}/media/a.png',
                  'liste': [{'u': f'http://{_HOTE_SYNTHETIQUE}/media/b.png?x=1'}],
                  'intact': 'https://exemple.org/c.png'}
        out = _url_relative(charge)
        self.assertEqual(out['url'], '/media/a.png')
        self.assertEqual(out['liste'][0]['u'], '/media/b.png?x=1')
        self.assertEqual(out['intact'], 'https://exemple.org/c.png')   # hôte tiers préservé

    def test_annonce_ce_qui_EXISTE_avant_qu_on_le_demande(self):
        """`sides` est ce qui permet de répondre « où en est mon job » : `has_during` dit qu'un
        job en cours a DÉJÀ quelque chose à montrer."""
        item = _item(self.moi)
        out = T.get_item_preview(self.moi, 'imager', item.pk)
        self.assertIn('sides', out)
        for cle in ('has_input', 'has_output', 'has_during', 'during_capable'):
            self.assertIn(cle, out['sides'])

    def test_refuse_l_element_d_un_autre_utilisateur(self):
        """La permission n'est pas réécrite ici : elle vient de l'endpoint réutilisé."""
        item = _item(self.autre)
        self.assertEqual(T.get_item_preview(self.moi, 'imager', item.pk).get('error'), 'forbidden')

    def test_refuse_un_side_invalide_en_nommant_les_valides(self):
        out = T.get_item_preview(self.moi, 'imager', 1, side='nawak')
        self.assertIn('during', out['error'])

    def test_app_inconnue_sans_lever(self):
        self.assertIn('error', T.get_item_preview(self.moi, 'pasunapp', 1))


class GetMyAccessTest(TestCase):
    def test_dit_les_apps_REFUSEES_autant_que_les_permises(self):
        """Sans la liste des refus, l'assistant ne peut qu'OMETTRE une app en silence — et
        l'utilisateur découvre le refus en cliquant au lieu de se l'entendre dire."""
        out = T.get_my_access(_utilisateur('acces1'))
        self.assertIn('apps_allowed', out)
        self.assertIn('apps_denied', out)
        from wama.accounts.permissions import all_gated_apps
        self.assertEqual(set(out['apps_allowed']) | set(out['apps_denied']), all_gated_apps())
        self.assertEqual(set(out['apps_allowed']) & set(out['apps_denied']), set())

    def test_n_elargit_aucun_droit_il_ne_fait_que_DIRE_la_decision(self):
        """La garde : cet outil doit rendre EXACTEMENT ce que `accessible()` décide. S'ils
        divergeaient, on aurait deux vérités sur les droits — la pire des deux."""
        from wama.accounts.permissions import accessible
        user = _utilisateur('acces2')
        out = T.get_my_access(user)
        for app in out['apps_allowed']:
            self.assertTrue(accessible(user, 'app', app), app)
        for app in out['apps_denied']:
            self.assertFalse(accessible(user, 'app', app), app)

    def test_refuse_l_anonyme(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIn('error', T.get_my_access(AnonymousUser()))


class ListMyMemoriesTest(TestCase):
    def test_ne_rend_jamais_la_file_de_revue(self):
        """🔴 LA garde de cet outil. `list_memories(en_attente=True)` n'est PAS scopée
        (store.py:686) : elle est réservée au staff par sa vue. Si l'outil l'exposait, un
        utilisateur lirait les souvenirs d'autrui — et du NON APPROUVÉ, que §6 rend
        volontairement invisible au rappel."""
        from wama.common.memory.store import list_memories, remember
        moi = _utilisateur('mem1')
        remember('un souvenir non approuvé', kind='fact', provenance='test', user=moi)
        en_attente = [m['content'] for m in list_memories(moi, en_attente=True)]
        # ⚠ SANS CETTE LIGNE LE TEST SERAIT VACUEUX : une file de revue vide le rendrait vert
        # sans rien exclure — et il le resterait le jour où `remember()` approuverait d'office.
        self.assertTrue(en_attente, "file de revue vide : le test n'exclurait rien")
        rendus = [m['content'] for m in T.list_my_memories(moi)['memories']]
        for contenu in en_attente:
            self.assertNotIn(contenu, rendus)

    def test_est_aligne_sur_ce_que_le_rappel_peut_rendre(self):
        """Même source que la page « Mes souvenirs » et que `recall()` — jamais une requête
        parallèle, sinon on débogue une différence entre deux vérités."""
        from wama.common.memory.store import list_memories
        moi = _utilisateur('mem2')
        self.assertEqual(T.list_my_memories(moi)['total'], len(list_memories(moi)))

    def test_borne_la_limite_et_rend_une_date_comparable(self):
        moi = _utilisateur('mem3')
        out = T.list_my_memories(moi, limite=10 ** 6)
        self.assertLessEqual(len(out['memories']), 100)
        for m in out['memories']:
            if m['cree_le']:
                from datetime import datetime
                datetime.fromisoformat(m['cree_le'])

    def test_refuse_l_anonyme(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertIn('error', T.list_my_memories(AnonymousUser()))


class VerbesDeCycleTest(TestCase):
    """🔴 Écritures. Leur garde d'app n'est portée NI par le registre (elles sont transverses
    par leur nom, donc `tool_accessible` les autorise) NI par `AppAccessMiddleware` (elles
    appellent la vue par une requête synthétique). Elle n'existe que dans leur corps — donc
    c'est elle qu'il faut prouver, et elle seule protège."""

    def setUp(self):
        self.moi = _utilisateur('cyc1')
        self.autre = _utilisateur('cyc2')

    def _app_refusee(self):
        refusees = T.get_my_access(self.moi)['apps_denied']
        if not refusees:
            self.skipTest("ce compte a accès à toutes les apps : la garde n'est pas éprouvable ici")
        return refusees[0]

    def test_la_garde_d_APP_tient_alors_que_les_DEUX_couches_habituelles_sont_absentes(self):
        """Le test qui justifie tout le bloc. On vérifie d'abord que les deux couches sont
        bien inertes ici — sinon on croirait tester la garde alors qu'autre chose protège."""
        from wama.accounts.permissions import tool_accessible
        app = self._app_refusee()
        self.assertTrue(tool_accessible(self.moi, 'delete_item'),
                        "si le registre gardait déjà, ce test ne prouverait rien")
        self.assertIsNone(T.app_id_for_tool('delete_item'))
        for outil in (T.delete_item, T.duplicate_item):
            self.assertEqual(outil(self.moi, app, 1).get('error'), 'forbidden', outil.__name__)
        self.assertEqual(T.clear_my_queue(self.moi, app, confirm=True).get('error'), 'forbidden')

    def test_clear_my_queue_REFUSE_sans_confirmation(self):
        """Un geste de masse qui part sur un malentendu ne se rattrape pas."""
        out = T.clear_my_queue(self.moi, 'imager')
        self.assertIn('error', out)
        self.assertNotEqual(out['error'], 'forbidden')      # c'est bien le REFUS de confirmation
        self.assertIn('confirm', out['error'])

    def test_ne_supprime_PAS_l_element_d_un_autre_utilisateur(self):
        from wama.imager.models import ImageGeneration
        item = _item(self.autre)
        T.delete_item(self.moi, 'imager', item.pk)
        self.assertTrue(ImageGeneration.objects.filter(pk=item.pk).exists(),
                        "l'élément d'autrui a été supprimé")

    def test_supprime_bien_le_MIEN(self):
        """Contre-épreuve du test précédent : sans elle, un outil qui ne supprime JAMAIS rien
        passerait les deux."""
        from wama.imager.models import ImageGeneration
        item = _item(self.moi)
        out = T.delete_item(self.moi, 'imager', item.pk)
        self.assertNotIn('error', out)
        self.assertFalse(ImageGeneration.objects.filter(pk=item.pk).exists())

    def test_duplique_le_MIEN_et_rend_un_nouvel_element(self):
        from wama.imager.models import ImageGeneration
        item = _item(self.moi, 'à dupliquer')
        avant = ImageGeneration.objects.filter(user=self.moi).count()
        out = T.duplicate_item(self.moi, 'imager', item.pk)
        self.assertNotIn('error', out, out)
        self.assertEqual(ImageGeneration.objects.filter(user=self.moi).count(), avant + 1)

    def test_les_trois_verbes_resolvent_sur_les_10_apps(self):
        """🔴 RECTIFICATION du 2026-09-12 (relevé de Fabien). La version du 11/09 affirmait
        « `duplicate` n'existe pas sur anonymizer, ni aucune des trois sur audio_enhancer ».
        LES DEUX ÉTAIENT FAUX, pour deux raisons différentes :
          • anonymizer nomme ses gestes d'après son modèle (`duplicate_media`,
            `clear_all_media`) — j'avais mesuré un NOM DE ROUTE et conclu sur l'existence d'un
            GESTE. Alias ajoutés à `ROUTE_ALIASES`, qui existe exactement pour ça ;
          • `audio_enhancer` n'est PAS une app : c'est la branche audio d'`enhancer`, et
            `TOOL_APP_ALIAS` le déclarait déjà.
        ⭐ *Un relevé par motif ne conclut pas.* Ce test remplace l'affirmation par la mesure."""
        from wama.tool_api import _route_dispo
        apps = ['anonymizer', 'avatarizer', 'composer', 'converter', 'describer',
                'enhancer', 'imager', 'reader', 'synthesizer', 'transcriber']
        manques = []
        for app in apps:
            for verbe, args in (('delete', [1]), ('duplicate', [1]), ('clear_all', [])):
                if not _route_dispo(app, verbe, args):
                    manques.append(f'{app}.{verbe}')
        self.assertEqual(manques, [], f'routes non résolues : {manques}')

    def test_dit_clairement_qu_une_route_MANQUE_au_lieu_d_echouer_obscurement(self):
        """Le cas reste à garder : une app SANS la route doit s'entendre dire laquelle manque,
        pas recevoir une trace. `audio_enhancer` est le cas réel — un sous-domaine d'app, donc
        sans URLconf propre."""
        out = T.duplicate_item(self.moi, 'audio_enhancer', 1)
        self.assertIn('error', out)
        self.assertIn('duplication', out['error'].lower())

    def test_app_inconnue_sans_lever(self):
        for outil in (T.delete_item, T.duplicate_item):
            self.assertIn('error', outil(self.moi, 'pasunapp', 1))

    def test_refusent_l_anonyme(self):
        from django.contrib.auth.models import AnonymousUser
        a = AnonymousUser()
        self.assertIn('error', T.delete_item(a, 'imager', 1))
        self.assertIn('error', T.duplicate_item(a, 'imager', 1))
        self.assertIn('error', T.clear_my_queue(a, 'imager', confirm=True))


class AddItemToMediaLibraryTest(TestCase):
    """3ᵉ surface du geste médiathèque (menu « … » · route d'app · assistant). Ce qui se garde
    ici, c'est qu'elle n'en soit pas une VARIANTE : même brique, donc mêmes refus."""

    def setUp(self):
        self.moi = _utilisateur('mlib1')
        self.autre = _utilisateur('mlib2')

    def _avec_sortie(self, user):
        from django.core.files.base import ContentFile
        from wama.composer.models import ComposerGeneration
        gen = ComposerGeneration.objects.create(user=user, prompt='t', model='musicgen')
        gen.audio_output.save('wama_temoin_outil.wav', ContentFile(b'\x00'), save=True)
        return gen

    def test_ne_DEVINE_pas_le_role_et_rend_les_candidats(self):
        gen = self._avec_sortie(self.moi)
        out = T.add_item_to_media_library(self.moi, 'composer', gen.pk)
        self.assertIn('candidates', out)
        self.assertIn('error', out)

    def test_range_quand_le_role_est_fourni(self):
        from wama.media_library.models import UserAsset
        gen = self._avec_sortie(self.moi)
        out = T.add_item_to_media_library(self.moi, 'composer', gen.pk,
                                         asset_type='audio_music')
        self.assertNotIn('error', out, out)
        self.assertEqual(UserAsset.objects.get(pk=out['asset_id']).user, self.moi)

    def test_refuse_l_element_d_un_autre(self):
        gen = self._avec_sortie(self.autre)
        out = T.add_item_to_media_library(self.moi, 'composer', gen.pk,
                                         asset_type='audio_music')
        self.assertEqual(out.get('error'), 'forbidden')

    def test_n_est_pas_pris_pour_une_triade_add_to(self):
        """Son nom COMMENCE par `add_` : s'il matchait `add_to_<app>`, il serait gaté sur une
        app fantôme « item_to_media_library » et refusé à tout le monde."""
        self.assertIsNone(T.tool_role('add_item_to_media_library'))
        self.assertIsNone(T.app_id_for_tool('add_item_to_media_library'))


_LECTURES = ('list_my_items', 'get_item_detail', 'get_item_preview', 'list_registries',
             'get_my_access', 'list_my_memories')
_ECRITURES = ('delete_item', 'duplicate_item', 'clear_my_queue',
              'add_item_to_media_library')


class PorteTest(TestCase):
    """Les lectures doivent passer par `execute_tool`, qui promet de ne JAMAIS lever."""

    def test_toutes_sont_au_registre_et_decrites(self):
        desc = T.tool_descriptions()
        for nom in _LECTURES + _ECRITURES:
            self.assertIn(nom, T.TOOL_REGISTRY)
            self.assertTrue(str(desc[nom]['description']).strip(), nom)

    def test_aucune_n_est_prise_pour_un_outil_de_triade(self):
        """`get_item_detail` et `get_my_access` commencent par `get_` : si le motif de triade
        les attrapait, ils seraient gatés sur une app fantôme et refusés à tout le monde."""
        for nom in _LECTURES + _ECRITURES:
            self.assertIsNone(T.tool_role(nom), nom)
            self.assertIsNone(T.app_id_for_tool(nom), nom)

    def test_repondent_par_la_porte_reelle(self):
        moi = _utilisateur('moi4')
        _item(moi)
        for nom in ('list_my_items', 'list_registries', 'get_my_access', 'list_my_memories'):
            self.assertNotIn('error', T.execute_tool(nom, {}, moi) or {}, nom)
