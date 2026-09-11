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
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama import tool_api as T


def _utilisateur(nom):
    return get_user_model().objects.create_user(username=nom, password='x')


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


_LECTURES = ('list_my_items', 'get_item_detail', 'list_registries',
             'get_my_access', 'list_my_memories')


class PorteTest(TestCase):
    """Les lectures doivent passer par `execute_tool`, qui promet de ne JAMAIS lever."""

    def test_toutes_sont_au_registre_et_decrites(self):
        desc = T.tool_descriptions()
        for nom in _LECTURES:
            self.assertIn(nom, T.TOOL_REGISTRY)
            self.assertTrue(str(desc[nom]['description']).strip(), nom)

    def test_aucune_n_est_prise_pour_un_outil_de_triade(self):
        """`get_item_detail` et `get_my_access` commencent par `get_` : si le motif de triade
        les attrapait, ils seraient gatés sur une app fantôme et refusés à tout le monde."""
        for nom in _LECTURES:
            self.assertIsNone(T.tool_role(nom), nom)
            self.assertIsNone(T.app_id_for_tool(nom), nom)

    def test_repondent_par_la_porte_reelle(self):
        moi = _utilisateur('moi4')
        _item(moi)
        for nom in ('list_my_items', 'list_registries', 'get_my_access', 'list_my_memories'):
            self.assertNotIn('error', T.execute_tool(nom, {}, moi) or {}, nom)
