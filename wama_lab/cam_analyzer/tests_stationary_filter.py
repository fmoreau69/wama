"""Le filtre des GARÉS doit dire par quelle porte il écarte (`stationary_rejects`, 2026-09-09).

Pourquoi ce test existe : le filtre enchaînait QUATRE conditions en silence. On lisait
« 77 stationnés détectés » sans savoir si les 4113 autres candidats étaient mobiles, vus trop
brièvement ou trop étalés — et deux analyses menées DE L'EXTÉRIEUR (sur les positions
persistées, donc lissées) ont conclu faux avant qu'on ne compte à la source. Le compte est
maintenant rendu par le filtre lui-même ; ces tests garantissent qu'il reste exact et exhaustif.

⚠ Ils exercent la logique de qualification sur des historiques SYNTHÉTIQUES, pas la fonction
complète (qui exige une session, ses caméras et son GPS). C'est assumé : ce qu'on garde ici est
l'ARITHMÉTIQUE du tri — que chaque candidat sorte par une porte et une seule.
"""
import math

from django.test import SimpleTestCase

SPREAD_MAX = 6.0


def trier(hists, near=lambda hs: False, spread_max=SPREAD_MAX):
    """Réplique EXACTE de la boucle de `multicam_tracker` (mêmes seuils, même ORDRE des
    conditions — c'est l'ordre qui décide de la porte de sortie quand deux motifs valent)."""
    retenus, rej = [], {'moins_de_5_obs': 0, 'vu_moins_de_4s': 0, 'trop_etale': 0,
                        'trop_rapide': 0, 'pres_intersection': 0, 'retenu': 0}
    for gid, hist in hists.items():
        hs = sorted(hist)
        dur = (hs[-1][1] - hs[0][1]) if len(hs) >= 2 else 0.0
        if len(hs) < 5:
            rej['moins_de_5_obs'] += 1
            continue
        if dur < 4.0:
            rej['vu_moins_de_4s'] += 1
            continue
        e0, n0 = hs[0][2], hs[0][3]
        spread = max(math.hypot(e - e0, n - n0) for (_, _, e, n, _) in hs)
        if spread >= spread_max:
            rej['trop_etale'] += 1
            continue
        if (spread / dur) >= 0.7:
            rej['trop_rapide'] += 1
            continue
        if near(hs):
            rej['pres_intersection'] += 1
            continue
        rej['retenu'] += 1
        retenus.append(gid)
    return retenus, rej


def _hist(n, dt, pas_m, t0=0.0):
    """n observations espacées de `dt` s, dérivant de `pas_m` mètres à chaque pas."""
    return [(i, t0 + i * dt, i * pas_m, 0.0, 'car') for i in range(n)]


class ChaqueCandidatSortParUneSeulePorteTest(SimpleTestCase):

    def test_le_total_des_rejets_egale_le_nombre_de_candidats(self):
        """L'invariant qui rend le compte lisible : rien ne se perd, rien ne compte deux fois."""
        hists = {
            'court': _hist(3, 1.0, 0.0),          # < 5 obs
            'bref': _hist(10, 0.2, 0.0),          # 1,8 s
            'mobile': _hist(20, 0.5, 1.0),        # 19 m d'étalement
            'lent': _hist(20, 0.5, 0.3),          # 5,7 m en 9,5 s → 0,6 m/s : RETENU
            'gare': _hist(30, 0.5, 0.0),
        }
        retenus, rej = trier(hists)
        self.assertEqual(sum(rej.values()), len(hists))
        self.assertEqual(rej['retenu'], len(retenus))

    def test_chaque_porte_est_ATTEIGNABLE(self):
        """Une porte que rien ne franchit jamais serait un compteur décoratif."""
        hists = {
            'a': _hist(4, 1.0, 0.0),                       # moins_de_5_obs
            'b': _hist(10, 0.2, 0.0),                      # vu_moins_de_4s
            'c': _hist(20, 0.5, 1.0),                      # trop_etale
            'd': _hist(6, 1.0, 1.1),                       # 5,5 m / 5 s = 1,1 m/s → trop_rapide
            'e': _hist(30, 0.5, 0.0),                      # pres_intersection (via `near`)
        }
        _, rej = trier(hists, near=lambda hs: hs[0][0] == 0 and len(hs) == 30)
        for porte in ('moins_de_5_obs', 'vu_moins_de_4s', 'trop_etale', 'trop_rapide',
                      'pres_intersection'):
            with self.subTest(porte=porte):
                self.assertEqual(rej[porte], 1, f"porte '{porte}' jamais empruntée")
        self.assertEqual(rej['retenu'], 0)

    def test_l_ORDRE_des_conditions_decide_de_la_porte(self):
        """Un track à la fois trop court ET trop étalé sort par la PREMIÈRE condition.

        Ce n'est pas un détail de présentation : c'est ce qui rend la répartition
        interprétable. La changer changerait le diagnostic sans changer le filtre.
        """
        _, rej = trier({'x': _hist(3, 0.1, 50.0)})
        self.assertEqual(rej['moins_de_5_obs'], 1)
        self.assertEqual(rej['trop_etale'], 0)

    def test_un_gare_vu_longtemps_et_immobile_est_RETENU(self):
        """Le cas nominal — sans lui, tout ce qui précède pourrait mesurer un filtre mort."""
        retenus, rej = trier({'gare': _hist(40, 0.5, 0.0)})
        self.assertEqual(retenus, ['gare'])
        self.assertEqual(rej['retenu'], 1)


class LeFiltreExposeSonCompteTest(SimpleTestCase):

    def test_le_tracker_declare_les_memes_portes(self):
        """Le dict du module et celui d'ici doivent lister LES MÊMES clés : c'est ce qui
        empêche d'ajouter une condition sans ajouter son compteur."""
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'wama_lab' / 'cam_analyzer' / 'utils'
               / 'multicam_tracker.py').read_text(encoding='utf-8')
        for porte in ('moins_de_5_obs', 'vu_moins_de_4s', 'trop_etale', 'trop_rapide',
                      'pres_intersection', 'retenu'):
            with self.subTest(porte=porte):
                self.assertIn(f"'{porte}'", src)
        self.assertIn("'stationary_rejects': _rejets", src,
                      "le compte doit être RENDU, sinon il ne sort jamais de la fonction")

    def test_la_tache_persiste_le_compte_et_l_annonce(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'wama_lab' / 'cam_analyzer'
               / 'tasks.py').read_text(encoding='utf-8')
        self.assertIn("rs['stationary_rejects']", src)
        self.assertIn('Garés — pourquoi le filtre écarte', src)
