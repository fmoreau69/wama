"""Tri + filtre COMMUNS de la file (`common/utils/queue_view.apply_queue_sort_filter`).

POURQUOI CE FICHIER (2026-08-27). Quatre apps triaient leur `batches_list` en dur JUSTE
AVANT d'appeler cette brique, qui re-trie INCONDITIONNELLEMENT (`q_sort` vaut au minimum
`'recent'`, et `.sort()` n'est sous aucune garde). Ce code était donc MORT : il s'exécutait,
coûtait, et n'avait aucun effet observable. `c9408354` en a retiré 3 (enhancer ×2,
synthesizer ×1), le 4ᵉ (avatarizer) a suivi. Rien n'empêchait le 5ᵉ.

Un tri mort ne plante pas, ne se voit pas dans l'UI et ne laisse pas de trace : seule une
ASSERTION peut le tenir dehors. D'où les deux familles ci-dessous —
  * `TriEtFiltre*` : la brique fait-elle ce qu'elle promet, sur les 5 tris × 5 filtres ;
  * `GardeTriMort` : aucune app ne re-trie avant de l'appeler.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from wama.common.utils.queue_view import apply_queue_sort_filter

TRIS = ['recent', 'oldest', 'name', 'batches_first', 'singles_first']
FILTRES = ['all', 'draft', 'running', 'success', 'failure']


def _entree(ident, nom, total, age_min, succes=0, en_cours=0, echecs=0):
    """Une entrée de `batches_list` telle que les vues la construisent."""
    return {
        'obj': SimpleNamespace(id=ident, total=total,
                               created_at=timezone.now() - timedelta(minutes=age_min)),
        'nom': nom,
        'success_count': succes, 'running_count': en_cours, 'failure_count': echecs,
    }


def _jeu():
    """4 entrées : deux LOTS et deux CARDS, âges / noms / types volontairement décorrélés.

    Décorrélés à dessein, et le premier jet ne l'était pas ASSEZ : avec des cards toutes
    plus récentes que les lots, `singles_first` rendait le MÊME ordre que `recent` par pure
    coïncidence, et la garde ci-dessous a échoué sur une donnée dégénérée — pas sur un
    défaut du code. D'où une card (#2) intercalée entre les deux lots : aucun des cinq tris
    ne peut plus coïncider avec un autre par accident.
    """
    return [
        _entree(1, 'delta', total=3, age_min=30, succes=3),               # lot, milieu
        _entree(2, 'alpha', total=1, age_min=40, en_cours=1),             # card, AVANT un lot
        _entree(3, 'charlie', total=5, age_min=50, succes=1, echecs=1),   # lot, le + vieux
        _entree(4, 'bravo', total=1, age_min=1),                          # card, le + récent
    ]


def _appliquer(tri=None, filtre=None, entrees=None, session=None):
    requete = RequestFactory().get('/', {k: v for k, v in
                                         (('sort', tri), ('filter', filtre)) if v})
    requete.session = {} if session is None else session
    return apply_queue_sort_filter(requete, entrees if entrees is not None else _jeu(),
                                   name_of=lambda b: b['nom'])


class TriEtFiltreTests(SimpleTestCase):
    """Les 5 tris et les 5 filtres exposés par `_queue_toolbar.html`."""

    def test_les_cinq_tris_du_toolbar_sont_tous_reconnus(self):
        # Un tri absent du dictionnaire retomberait SILENCIEUSEMENT sur `recent`
        # (`_sorters.get(q_sort, _sorters['recent'])`) : la liste déroulante proposerait
        # une option sans effet, exactement le mode de panne muet que ce fichier traque.
        par_defaut = [e['obj'].id for e in _appliquer('recent')[0]]
        for tri in TRIS:
            ordre = [e['obj'].id for e in _appliquer(tri)[0]]
            if tri == 'recent':
                continue
            self.assertNotEqual(
                ordre, par_defaut,
                f"le tri '{tri}' rend le MÊME ordre que 'recent' — il n'est probablement "
                f"pas reconnu et retombe sur le défaut")

    def test_recent_va_du_plus_recent_au_plus_ancien(self):
        ordre = [e['obj'].id for e in _appliquer('recent')[0]]
        self.assertEqual(ordre, [4, 1, 2, 3])

    def test_oldest_est_exactement_l_inverse_de_recent(self):
        self.assertEqual([e['obj'].id for e in _appliquer('oldest')[0]],
                         list(reversed([e['obj'].id for e in _appliquer('recent')[0]])))

    def test_name_suit_name_of_et_non_la_date(self):
        self.assertEqual([e['nom'] for e in _appliquer('name')[0]],
                         ['alpha', 'bravo', 'charlie', 'delta'])

    def test_batches_first_place_les_lots_avant_les_cards(self):
        entrees = _appliquer('batches_first')[0]
        totaux = [e['obj'].total > 1 for e in entrees]
        self.assertEqual(totaux, [True, True, False, False])
        # …et, à type égal, reste chronologique décroissant.
        self.assertEqual([e['obj'].id for e in entrees], [1, 3, 4, 2])

    def test_singles_first_place_les_cards_avant_les_lots(self):
        entrees = _appliquer('singles_first')[0]
        self.assertEqual([e['obj'].total > 1 for e in entrees], [False, False, True, True])

    def test_un_tri_inconnu_retombe_sur_recent_sans_lever(self):
        entrees, tri, _ = _appliquer('n_importe_quoi')
        self.assertEqual([e['obj'].id for e in entrees], [4, 1, 2, 3])
        # La valeur est RENVOYÉE telle quelle : le <select> la réaffichera comme
        # sélectionnée alors qu'elle n'agit pas. Comportement constaté, pas souhaité —
        # documenté ici pour qu'un changement soit délibéré.
        self.assertEqual(tri, 'n_importe_quoi')

    def test_le_filtre_all_ne_retire_rien(self):
        self.assertEqual(len(_appliquer('recent', 'all')[0]), 4)

    def test_chaque_filtre_ne_garde_que_les_entrees_concernees(self):
        attendus = {'running': {2}, 'failure': {3}, 'success': {1, 3}}
        for filtre, ids in attendus.items():
            with self.subTest(filtre=filtre):
                self.assertEqual({e['obj'].id for e in _appliquer('recent', filtre)[0]}, ids)

    def test_draft_retient_ce_qui_n_est_pas_entierement_traite(self):
        # brouillon = traités (succès+en cours+échecs) < total
        # #1 : 3/3 traités → non ; #2 : 1/1 → non ; #3 : 2/5 → oui ; #4 : 0/1 → oui
        self.assertEqual({e['obj'].id for e in _appliquer('recent', 'draft')[0]}, {3, 4})

    def test_les_vingt_cinq_combinaisons_ne_levent_pas(self):
        for tri in TRIS:
            for filtre in FILTRES:
                with self.subTest(tri=tri, filtre=filtre):
                    entrees, t, f = _appliquer(tri, filtre)
                    self.assertEqual((t, f), (tri, filtre))
                    self.assertLessEqual(len(entrees), 4)

    def test_le_tri_est_stable_si_on_le_rejoue(self):
        self.assertEqual([e['obj'].id for e in _appliquer('name')[0]],
                         [e['obj'].id for e in _appliquer('name')[0]])

    def test_une_liste_vide_ou_a_un_element_passe_sur_les_cinq_tris(self):
        for entrees in ([], [_entree(9, 'seule', 1, 5)]):
            for tri in TRIS:
                with self.subTest(n=len(entrees), tri=tri):
                    self.assertEqual(len(_appliquer(tri, entrees=list(entrees))[0]),
                                     len(entrees))


class PersistanceEnSessionTests(SimpleTestCase):
    """Le choix survit à la requête suivante — et les clefs sont PARTAGÉES entre apps."""

    def test_le_choix_est_memorise_puis_reappliquee_sans_parametre(self):
        session = {}
        _appliquer('name', 'running', session=session)
        self.assertEqual((session['q_sort'], session['q_filter']), ('name', 'running'))
        # requête suivante SANS paramètre : la session tranche
        entrees, tri, filtre = _appliquer(session=session)
        self.assertEqual((tri, filtre), ('name', 'running'))
        self.assertEqual([e['obj'].id for e in entrees], [2])

    def test_le_defaut_est_recent_et_all_hors_session(self):
        # Décision 2026-06-29 : plus de « batchs d'abord » par défaut.
        _, tri, filtre = _appliquer(session={})
        self.assertEqual((tri, filtre), ('recent', 'all'))

    def test_un_parametre_d_url_l_emporte_sur_la_session(self):
        _, tri, _ = _appliquer('oldest', session={'q_sort': 'name', 'q_filter': 'all'})
        self.assertEqual(tri, 'oldest')


class GardeTriMortTests(SimpleTestCase):
    """Aucune vue ne doit trier sa liste avant de la confier à la brique commune.

    C'est la garde qui manquait : les 4 tris morts ont vécu des semaines parce qu'AUCUNE
    assertion ne les voyait. Volontairement TEXTUELLE — un tri mort ne se détecte pas à
    l'exécution, par définition : son effet est écrasé.
    """

    def test_aucune_vue_ne_trie_sa_liste_avant_apply_queue_sort_filter(self):
        import re
        from pathlib import Path

        from django.conf import settings

        motif = re.compile(r'^\s*\w*(?:batches|list|entries)\w*\.sort\s*\(', re.M)
        coupables = []
        for racine in ('wama', 'wama_lab', 'wama_data'):
            base = Path(settings.BASE_DIR) / racine
            if not base.is_dir():
                continue
            for vue in base.rglob('views*.py'):
                texte = vue.read_text(encoding='utf-8', errors='replace')
                if 'apply_queue_sort_filter' not in texte:
                    continue
                for m in motif.finditer(texte):
                    coupables.append(f"{vue.relative_to(settings.BASE_DIR)}:"
                                     f"{texte[:m.start()].count(chr(10)) + 1}")
        self.assertEqual(
            coupables, [],
            "tri LOCAL dans une vue qui appelle ensuite apply_queue_sort_filter — il sera "
            "écrasé (le tri commun est inconditionnel) : c'est du code mort, le retirer. "
            f"Trouvé : {coupables}")
