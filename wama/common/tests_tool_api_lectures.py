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


class PorteTest(TestCase):
    """Les trois outils doivent passer par `execute_tool`, qui promet de ne JAMAIS lever."""

    def test_les_trois_sont_au_registre_et_decrits(self):
        desc = T.tool_descriptions()
        for nom in ('list_my_items', 'get_item_detail', 'list_registries'):
            self.assertIn(nom, T.TOOL_REGISTRY)
            self.assertTrue(str(desc[nom]['description']).strip(), nom)

    def test_aucun_n_est_pris_pour_un_outil_de_triade(self):
        """`get_item_detail` commence par `get_` : si le motif de triade l'attrapait, il
        serait gaté sur une app fantôme « item_detail » et refusé à tout le monde."""
        for nom in ('list_my_items', 'get_item_detail', 'list_registries'):
            self.assertIsNone(T.tool_role(nom), nom)
            self.assertIsNone(T.app_id_for_tool(nom), nom)

    def test_repondent_par_la_porte_reelle(self):
        moi = _utilisateur('moi4')
        _item(moi)
        for nom in ('list_my_items', 'list_registries'):
            self.assertNotIn('error', T.execute_tool(nom, {}, moi) or {}, nom)
