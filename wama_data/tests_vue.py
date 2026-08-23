"""Tests du VIEW-MODEL de l'Explorer (`wama_data/vue.py`).

Le test qui porte ce fichier est `RegleTest` : il vérifie que la règle de §9quater.4 est **dérivée
du catalogue** et non codée en dur — c'est-à-dire qu'une fonction ajoutée demain se range du bon
côté sans qu'on touche `vue.py`. Le reste vérifie qu'une vue est bien une DÉCLARATION (elle fait
l'aller-retour, elle refuse ses fautes avant tout calcul) et qu'elle ne persiste rien.
"""
import unittest

from wama.common.catalog.data_types import DataType
from wama.common.catalog.function_catalog import FUNCTION_CATALOG, FunctionCategory, get

from .core.temporal import SignalMeta, Signal, TemporalReferential
from .vue import (CATEGORIES_ADJOINTES, CATEGORIES_NOUVELLE_TABLE, ColonneDerivee, Fenetre,
                  Piste, Vue, appliquer, change_la_cle_temporelle, depuis_dict, serie, valider)


def _referentiel():
    ref = TemporalReferential('essai')
    lignes = [{'timecode': float(i), 'value': 40.0 if 3 <= i <= 6 else 5.0} for i in range(12)]
    ref.add(Signal(SignalMeta(name='vitesse'), [float(i) for i in range(12)],
                   rows=lambda i0, i1: lignes[i0:i1]))
    lignes2 = [{'timecode': float(i), 'value': float(i)} for i in range(12)]
    ref.add(Signal(SignalMeta(name='distance'), [float(i) for i in range(12)],
                   rows=lambda i0, i1: lignes2[i0:i1]))
    return ref


class RegleTest(unittest.TestCase):
    """§9quater.4 rendue exécutable — et DÉRIVÉE du catalogue."""

    def test_enricher_reste_dans_la_table(self):
        self.assertFalse(change_la_cle_temporelle('calcul_glissant'))

    def test_aggregate_sort_dans_une_table_a_part(self):
        self.assertTrue(change_la_cle_temporelle('calcul_par_segment'))

    def test_detector_sort_aussi(self):
        # `masque → events` change bien la nature de ce qu'on regarde.
        self.assertTrue(change_la_cle_temporelle('event_chaine_conditionnelle'))

    def test_transform_reste(self):
        self.assertFalse(change_la_cle_temporelle('segment_present_dans')
                         if get('segment_present_dans') else True)

    def test_la_regle_est_LUE_dans_la_categorie_pas_dans_une_liste_de_noms(self):
        # LE test du fichier : pour CHAQUE fonction du catalogue, le verdict doit coïncider avec
        # sa catégorie déclarée. Une fonction ajoutée demain se range donc toute seule.
        for cle, spec in FUNCTION_CATALOG.items():
            if spec.category not in (CATEGORIES_ADJOINTES | CATEGORIES_NOUVELLE_TABLE):
                continue
            attendu = spec.category in CATEGORIES_NOUVELLE_TABLE
            self.assertEqual(change_la_cle_temporelle(cle), attendu,
                             f"{cle} ({spec.category}) mal rangée")

    def test_les_deux_ensembles_couvrent_les_categories_du_catalogue(self):
        # Une catégorie réellement employée et non classée ferait lever à l'exécution.
        employees = {s.category for s in FUNCTION_CATALOG.values()}
        non_classees = employees - (CATEGORIES_ADJOINTES | CATEGORIES_NOUVELLE_TABLE)
        self.assertEqual(non_classees, set(), f"catégories non classées : {non_classees}")

    def test_une_categorie_INCONNUE_leve_au_lieu_de_tomber_d_un_cote(self):
        from wama.common.catalog.function_catalog import FunctionSpec, PortSpec, register
        cle = '_essai_categorie_inconnue'
        try:
            register(FunctionSpec(key=cle, name='x', description='x', category='inedite',
                                  inputs=[PortSpec('e', DataType.TIMESERIES)],
                                  outputs=[PortSpec('s', DataType.TIMESERIES)],
                                  fn=lambda f: f))
            with self.assertRaises(ValueError) as ctx:
                change_la_cle_temporelle(cle)
            self.assertIn('non classée', str(ctx.exception))
        finally:
            FUNCTION_CATALOG.pop(cle, None)

    def test_fonction_absente_du_catalogue_refusee(self):
        with self.assertRaises(ValueError):
            change_la_cle_temporelle('inexistante')


class DeclarationTest(unittest.TestCase):

    def test_vue_sans_piste_refusee(self):
        with self.assertRaises(ValueError):
            Vue(nom='v', pistes=())

    def test_vue_sans_nom_refusee(self):
        with self.assertRaises(ValueError):
            Vue(nom='', pistes=(Piste('a'),))

    def test_flux_en_double_refuse(self):
        with self.assertRaises(ValueError) as ctx:
            Vue(nom='v', pistes=(Piste('a'), Piste('a')))
        self.assertIn('double', str(ctx.exception))

    def test_fenetre_inversee_refusee(self):
        with self.assertRaises(ValueError):
            Fenetre(t0=10.0, t1=2.0)

    def test_buckets_negatif_refuse(self):
        with self.assertRaises(ValueError):
            Fenetre(buckets=-1)

    def test_colonne_derivee_incomplete_refusee(self):
        with self.assertRaises(ValueError):
            ColonneDerivee(fonction='calcul_glissant', flux='')


class SerialisationTest(unittest.TestCase):
    """Une vue est une DÉCLARATION : elle doit faire l'aller-retour sans perte."""

    def _vue(self):
        return Vue(nom='exploration',
                   pistes=(Piste('vitesse', ('value',)), Piste('distance')),
                   fenetre=Fenetre(t0=0.0, t1=10.0, buckets=200),
                   derivees=(ColonneDerivee('calcul_glissant', 'vitesse',
                                            {'fenetre_s': 2.0, 'colonne': 'value'}),))

    def test_aller_retour_fidele(self):
        v = self._vue()
        self.assertEqual(depuis_dict(v.to_dict()), v)

    def test_la_forme_serialisee_est_du_JSON_pur(self):
        import json
        v = self._vue()
        self.assertEqual(depuis_dict(json.loads(json.dumps(v.to_dict()))), v)

    def test_une_declaration_vide_est_refusee_a_la_relecture(self):
        with self.assertRaises(ValueError):
            depuis_dict({})


class ValidationTest(unittest.TestCase):
    """Les fautes se voient AVANT tout calcul."""

    def test_flux_inconnu_refuse_en_nommant_les_presents(self):
        with self.assertRaises(ValueError) as ctx:
            valider(Vue(nom='v', pistes=(Piste('absent'),)), _referentiel())
        self.assertIn('vitesse', str(ctx.exception))

    def test_derivee_sur_flux_inconnu_refusee(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),),
                derivees=(ColonneDerivee('calcul_glissant', 'absent'),))
        with self.assertRaises(ValueError):
            valider(v, _referentiel())

    def test_derivee_sur_fonction_inconnue_refusee(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),),
                derivees=(ColonneDerivee('inexistante', 'vitesse'),))
        with self.assertRaises(ValueError):
            valider(v, _referentiel())


class ApplicationTest(unittest.TestCase):

    def test_les_pistes_deviennent_des_tables(self):
        r = appliquer(Vue(nom='v', pistes=(Piste('vitesse'), Piste('distance'))), _referentiel())
        self.assertEqual(sorted(r.tables), ['distance', 'vitesse'])
        self.assertEqual(r.annexes, {})

    def test_la_fenetre_restreint(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),), fenetre=Fenetre(t0=2.0, t1=5.0))
        r = appliquer(v, _referentiel())
        self.assertEqual(list(r.tables['vitesse'].df['time']), [2.0, 3.0, 4.0, 5.0])

    def test_une_derivee_ENRICHER_reste_dans_la_table(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),),
                derivees=(ColonneDerivee('calcul_glissant', 'vitesse',
                                         {'fenetre_s': 2.0, 'colonne': 'value'}),))
        r = appliquer(v, _referentiel())
        self.assertIn('value_moyenne', r.tables['vitesse'].df.columns)
        self.assertEqual(r.annexes, {}, "une ENRICHER ne doit produire aucune annexe")

    def test_une_derivee_DETECTOR_ouvre_une_annexe(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),),
                derivees=(ColonneDerivee(
                    'event_chaine_conditionnelle', 'vitesse',
                    {'conditions': [{'cle': 'C1', 'champ': 'value',
                                     'operateur': '>=', 'valeur': 30.0}]},
                    nom='bascules'),))
        r = appliquer(v, _referentiel())
        self.assertIn('bascules', r.annexes)
        self.assertEqual(r.annexes['bascules'].data_type, DataType.EVENTS)
        # La table regardée n'a PAS été modifiée : c'est ce que la séparation rend visible.
        self.assertNotIn('edge', r.tables['vitesse'].df.columns)

    def test_les_derivees_s_enchainent_dans_l_ordre_declare(self):
        # Geste ordinaire d'un tableur : une colonne calculée sur une colonne calculée.
        v = Vue(nom='v', pistes=(Piste('vitesse'),),
                derivees=(ColonneDerivee('calcul_glissant', 'vitesse',
                                         {'fenetre_s': 2.0, 'colonne': 'value'}),
                          ColonneDerivee('calcul_derivee', 'vitesse',
                                         {'colonne': 'value_moyenne'})))
        r = appliquer(v, _referentiel())
        self.assertIn('value_moyenne_derivee', r.tables['vitesse'].df.columns)

    def test_une_derivee_sur_un_flux_NON_regarde_est_quand_meme_honoree(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),),
                derivees=(ColonneDerivee('calcul_glissant', 'distance',
                                         {'fenetre_s': 2.0, 'colonne': 'value'}),))
        r = appliquer(v, _referentiel())
        self.assertIn('value_moyenne', r.tables['distance'].df.columns)

    def test_appliquer_ne_PERSISTE_rien(self):
        # §9quater.5 : le référentiel ne doit pas gagner de flux au passage.
        ref = _referentiel()
        avant = set(ref.names)
        appliquer(Vue(nom='v', pistes=(Piste('vitesse'),),
                      derivees=(ColonneDerivee('calcul_glissant', 'vitesse',
                                               {'fenetre_s': 2.0, 'colonne': 'value'}),)), ref)
        self.assertEqual(set(ref.names), avant)


class SerieTest(unittest.TestCase):
    """Le tracé — décimé, et sans matérialiser les points."""

    def test_serie_decimee(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),), fenetre=Fenetre(t0=0.0, t1=11.0, buckets=4))
        s = serie(v, _referentiel(), 'vitesse', 'value')
        self.assertEqual(len(s), 4)
        self.assertTrue(all('t_start' in b for b in s))

    def test_la_decimation_preserve_les_EXTREMA(self):
        # Premier+dernier de tranche perdrait la pointe : c'est la raison d'être de
        # `decimate_values`, et la vue ne doit pas la contourner.
        v = Vue(nom='v', pistes=(Piste('vitesse'),), fenetre=Fenetre(t0=0.0, t1=11.0, buckets=2))
        s = serie(v, _referentiel(), 'vitesse', 'value')
        self.assertEqual(max(b['max'] for b in s), 40.0)

    def test_un_trace_sans_fenetre_bornee_est_refuse(self):
        v = Vue(nom='v', pistes=(Piste('vitesse'),), fenetre=Fenetre(buckets=100))
        with self.assertRaises(ValueError) as ctx:
            serie(v, _referentiel(), 'vitesse', 'value')
        self.assertIn('bornée', str(ctx.exception))

    def test_un_trace_sans_buckets_est_refuse(self):
        # 0 signifie « table, échantillons réels » — pas « choisis pour moi ».
        v = Vue(nom='v', pistes=(Piste('vitesse'),), fenetre=Fenetre(t0=0.0, t1=5.0))
        with self.assertRaises(ValueError):
            serie(v, _referentiel(), 'vitesse', 'value')


if __name__ == '__main__':
    unittest.main()
