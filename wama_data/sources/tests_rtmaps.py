"""Tests du lecteur RTMaps `.rec` — `WAMA_DATA_WORLD.md §6.6` et `§6.6bis`.

Deux niveaux, et la répartition n'est pas de commodité :

  • un `.rec` **SYNTHÉTIQUE** porte l'essentiel des contrôles — c'est le garde-fou G7 (« échantillon
    réduit versionné »), et la leçon du 2026-08-24 : le lecteur `.trip` s'était retrouvé à ZÉRO
    couverture le jour où son corpus de 1,28 Go avait bougé, sans que rien ne le signale ;
  • les **DEUX corpus réels** valident ce qu'aucun fixture ne peut inventer — notamment que la
    grammaire du `.idy` diffère entre RTMaps v4.5.3 et v4.8.0.

⚠ `CorpusReelTest` porte une contre-épreuve INDÉPENDANTE : RTMaps exporte lui-même le flux GPS en
CSV, et le lecteur doit retrouver les mêmes instants et les mêmes valeurs. Un test qui ne se
comparerait qu'à lui-même ne prouverait que sa propre cohérence.
"""
import tempfile
import unittest
from pathlib import Path

from wama.common.catalog.data_types import DataType

from .. import sources
from ..corpus import CSV_GPS_2022, REC_2019, REC_2022, absence_reason
from .rtmaps import ENCODAGES_EXTERNES, RecReader, to_seconds

_ENTETE = ("RTMaps Remote Runtime Release v4.8.0 (build 264192) for Win32\n"
           "Copyright (c) 2000-2020 INTEMPORA S.A.\n"
           "Launched at 12:40:00.563 (04/04/2022) UTC+02:00 - 10:40:00.563 (04/04/2022) UTC\n"
           "[Misc]\n")

#: ⚠ Grammaire **v4.8.0** — une seule expression entre parenthèses (pas de nom de table).
_RECORD_2022 = ("00:00.706888 @ Record Accel.X_axis(GSensor.X_axis[0x10000,,,64,1]) "
                "as tabbed_text\n"
                "00:01.545251 @ Record cam_1.output_stream(h264.output_stream[0x1000,,,16,512000])"
                " as video_file\n")

#: ⚠ Grammaire **v4.5.3** — DEUX expressions : le nom de table PUIS le producteur.
_RECORD_2019 = ("00:00.558436 @ Record DR2.message(DR2_message,python_v2.output[0x8,,,32,10240]) "
                "as txt\n")


def _ecrire(dossier: Path, name='essai', records=_RECORD_2022, donnees='', idy=True) -> Path:
    rec = dossier / f"{name}.rec"
    rec.write_text(_ENTETE + "[STDB v2.0]\nOffset (sec) : 0\n[Data]\n" + records + donnees,
                   encoding='latin-1')
    if idy:
        (dossier / f"{name}.idy").write_text(_ENTETE + records, encoding='latin-1')
    return rec


class TempsTest(unittest.TestCase):
    """Le format d'heure est VARIABLE — les heures n'apparaissent qu'au-delà de la première."""

    def test_minutes_secondes(self):
        self.assertAlmostEqual(to_seconds('00:12.500000'), 12.5)

    def test_avec_heures(self):
        self.assertAlmostEqual(to_seconds('1:02:03.000000'), 3723.0)

    def test_illisible_rend_None_sans_lever(self):
        self.assertIsNone(to_seconds('n/a'))
        self.assertIsNone(to_seconds(''))


class ReconnaissanceTest(unittest.TestCase):

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dossier = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def test_le_lecteur_est_enregistre_et_repond(self):
        rec = _ecrire(self.dossier)
        self.assertEqual(sources.reader_for(rec).format, 'rtmaps')
        self.assertIn('.rec', sources.supported_extensions())

    def test_un_fichier_mal_nomme_est_DECLINE(self):
        # On renifle l'en-tête : sans ça, l'import échouerait loin de sa cause.
        faux = self.dossier / 'faux.rec'
        faux.write_text('ceci n est pas un enregistrement\n', encoding='latin-1')
        self.assertIsNone(sources.reader_for(faux))


class InventaireTest(unittest.TestCase):
    """`probe()` lit le `.idy` — quelques kilo-octets contre un fichier de plusieurs gigas."""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dossier = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def test_les_flux_sont_nommes_composant_point_sortie(self):
        info = sources.probe(_ecrire(self.dossier))
        self.assertEqual(info.streams, ['Accel.X_axis', 'cam_1.output_stream'])

    def test_LES_DEUX_grammaires_du_idy_sont_acceptees(self):
        """⚠ LE test de ce fichier — le nom de table a disparu entre RTMaps v4.5.3 et v4.8.0.

        Un lecteur validé sur un seul échantillon casserait sur l'autre. On ne lit donc que
        `composant.sortie` et le suffixe `as <encodage>`, en s'arrêtant à la parenthèse.
        """
        deux = sources.probe(_ecrire(self.dossier, records=_RECORD_2019 + _RECORD_2022))
        self.assertEqual(deux.streams,
                         ['DR2.message', 'Accel.X_axis', 'cam_1.output_stream'])
        self.assertEqual(deux.attributes['encodages']['DR2.message'], 'txt')

    def test_l_encodage_declare_est_rapporte(self):
        info = sources.probe(_ecrire(self.dossier))
        self.assertEqual(info.attributes['encodages'],
                         {'Accel.X_axis': 'tabbed_text', 'cam_1.output_stream': 'video_file'})

    def test_un_flux_EXTERNE_devient_un_media_pas_un_flux_de_donnees(self):
        rec = _ecrire(self.dossier)
        (self.dossier / 'essai_cam_1_output_stream.avi').write_bytes(b'x')
        info = sources.probe(rec)
        self.assertEqual(len(info.media), 1)
        # ⚠ Le nom du compagnon est DÉRIVÉ par convention, jamais lu dans le `.idy` (v4.8 ne le
        # donne plus).
        self.assertTrue(info.media[0]['file'].endswith('essai_cam_1_output_stream.avi'))

    def test_un_media_ABSENT_est_signale_sans_lever(self):
        info = sources.probe(_ecrire(self.dossier))
        self.assertEqual(info.media[0]['file'], '')

    def test_l_heure_de_lancement_est_extraite(self):
        info = sources.probe(_ecrire(self.dossier))
        self.assertIn('04/04/2022', info.attributes['recording_start_time'])
        # La variante 2022 suffixe « UTC+02:00 - … » : le suffixe ne doit pas rester collé.
        self.assertNotIn('UTC', info.attributes['recording_start_time'])

    def test_SANS_idy_on_retombe_sur_l_en_tete_du_rec(self):
        # Les déclarations `@ Record` figurent aussi dans le `.rec` — le repli est réel.
        info = sources.probe(_ecrire(self.dossier, idy=False))
        self.assertEqual(info.streams, ['Accel.X_axis', 'cam_1.output_stream'])
        self.assertIn('balayage', info.attributes['inventaire'])


class LectureTest(unittest.TestCase):

    DONNEES = ("00:00.706493 / Accel.X_axis#0@00:00.669604=-0.0390625\n"
               "00:00.806493 / Accel.X_axis#1@00:00.769604=-0.0078125\n"
               "00:00.906493 / Accel.X_axis#2@00:00.869604=0.95703125\n")

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dossier = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def test_instants_et_charges(self):
        ref = sources.load(_ecrire(self.dossier, donnees=self.DONNEES),
                           streams=['Accel.X_axis'])
        s = ref.get('Accel.X_axis')
        self.assertEqual(len(s), 3)
        self.assertAlmostEqual(s.span[0], 0.669604)
        self.assertEqual(s.rows(0, 1)[0]['value'], '-0.0390625')

    def test_le_timestamp_de_CAPTURE_prime_sur_le_temps_d_EMISSION(self):
        # `@ts` est le moment de capture ; c'est LUI qui synchronise les flux entre eux.
        ref = sources.load(_ecrire(self.dossier, donnees=self.DONNEES), streams=['Accel.X_axis'])
        self.assertAlmostEqual(ref.get('Accel.X_axis').span[0], 0.669604)  # pas 0.706493

    def test_sans_timestamp_on_retombe_sur_le_temps_d_emission(self):
        d = "00:01.500000 / Accel.X_axis#0=-1.0\n"
        ref = sources.load(_ecrire(self.dossier, donnees=d), streams=['Accel.X_axis'])
        self.assertAlmostEqual(ref.get('Accel.X_axis').span[0], 1.5)

    def test_une_ligne_SANS_charge_porte_son_INDEX_pour_valeur(self):
        # Règle reprise de `rec2trip` : `data = idx` quand il n'y a pas de `=`.
        d = "00:01.000000 / Accel.X_axis#7@00:01.000000\n"
        ref = sources.load(_ecrire(self.dossier, donnees=d), streams=['Accel.X_axis'])
        self.assertEqual(ref.get('Accel.X_axis').rows(0, 1)[0]['value'], 7)

    def test_LES_PERTES_SONT_COMPTEES_comme_une_DONNEE(self):
        """⚠ `pynd` les détecte et se contente d'un `log.error` — son `TODO` l'admet."""
        d = ("00:00.100000 / Accel.X_axis#0@00:00.100000=1\n"
             "00:00.200000 / Accel.X_axis#4@00:00.200000=2\n")     # 1,2,3 perdus
        ref = sources.load(_ecrire(self.dossier, donnees=d), streams=['Accel.X_axis'])
        self.assertEqual(ref.get('Accel.X_axis').meta.losses, 3)

    def test_aucune_perte_quand_les_index_se_suivent(self):
        ref = sources.load(_ecrire(self.dossier, donnees=self.DONNEES), streams=['Accel.X_axis'])
        self.assertEqual(ref.get('Accel.X_axis').meta.losses, 0)

    def test_seuls_les_flux_DEMANDES_sont_materialises(self):
        # Le coût est borné par la demande, pas par le fichier : un `.rec` réel fait 1,54 Go.
        d = self.DONNEES + "00:00.7 / autre.flux#0@00:00.7=9\n"
        rec = _ecrire(self.dossier,
                      records=_RECORD_2022 + "00:00.7 @ Record autre.flux(x.y[0]) as txt\n",
                      donnees=d)
        ref = sources.load(rec, streams=['Accel.X_axis'])
        self.assertEqual(ref.names, ['Accel.X_axis'])

    def test_un_flux_INCONNU_est_refuse_en_nommant_les_declares(self):
        with self.assertRaises(ValueError) as ctx:
            sources.load(_ecrire(self.dossier, donnees=self.DONNEES), streams=['absent.flux'])
        self.assertIn('Accel.X_axis', str(ctx.exception))

    def test_un_flux_a_charge_EXTERNE_est_refuse_en_DISANT_pourquoi(self):
        with self.assertRaises(ValueError) as ctx:
            sources.load(_ecrire(self.dossier, donnees=self.DONNEES),
                         streams=['cam_1.output_stream'])
        self.assertIn('EXTERNE', str(ctx.exception))
        self.assertIn('probe', str(ctx.exception))

    def test_par_defaut_on_ne_charge_que_les_flux_TEXTE(self):
        ref = sources.load(_ecrire(self.dossier, donnees=self.DONNEES))
        self.assertEqual(ref.names, ['Accel.X_axis'])   # la vidéo n'en est pas un

    def test_la_famille_est_portee_comme_donnee(self):
        ref = sources.load(_ecrire(self.dossier, donnees=self.DONNEES), streams=['Accel.X_axis'])
        self.assertEqual(ref.get('Accel.X_axis').meta.data_type, DataType.TIMESERIES)

    def test_la_charge_est_rendue_TELLE_QUELLE(self):
        # ③ L'encodage déclare le TRANSPORT, pas la structure : deux flux `as txt` du même corpus
        # portent l'un du `clé=valeur;` à virgule française, l'autre du JSON. Interpréter ici
        # serait deviner.
        d = "00:01.000000 / Accel.X_axis#0@00:01.000000=Pas=1776;V_vp:Vitesse=0,000;\n"
        ref = sources.load(_ecrire(self.dossier, donnees=d), streams=['Accel.X_axis'])
        self.assertEqual(ref.get('Accel.X_axis').rows(0, 1)[0]['value'],
                         'Pas=1776;V_vp:Vitesse=0,000;')


@unittest.skipUnless(REC_2022.exists(), absence_reason(REC_2022))
class CorpusReelTest(unittest.TestCase):
    """Le corpus 2022 (40 Mo) — et une contre-épreuve que le lecteur ne peut pas se donner."""

    def test_inventaire(self):
        info = sources.probe(REC_2022)
        self.assertEqual(len(info.streams), 8)
        self.assertIn('GPS_NMEA0183_3.oPosition', info.streams)
        self.assertEqual(len(info.media), 1)
        self.assertTrue(info.media[0]['file'].endswith('.avi'), info.media)

    def test_CONTRE_EPREUVE_le_lecteur_retrouve_l_export_de_RTMaps(self):
        """⚠ RTMaps exporte lui-même ce flux en CSV : `<µs>;<lat>;<lon>[;…]`.

        Deux chemins indépendants doivent donner le même résultat. Un test qui ne comparerait le
        lecteur qu'à lui-même ne prouverait que sa cohérence interne.
        """
        if not CSV_GPS_2022.exists():
            self.skipTest(absence_reason(CSV_GPS_2022))
        premiere = CSV_GPS_2022.read_text(encoding='latin-1').splitlines()[0].split(';')
        t_csv, lat_csv, lon_csv = int(premiere[0]) / 1e6, premiere[1], premiere[2]

        ref = sources.load(REC_2022, streams=['GPS_NMEA0183_3.oPosition'])
        s = ref.get('GPS_NMEA0183_3.oPosition')
        self.assertAlmostEqual(s.span[0], t_csv, places=6)
        champs = s.rows(0, 1)[0]['value'].split('\t')
        self.assertEqual((champs[0], champs[1]), (lat_csv, lon_csv))

    def test_cadences_mesurees_plausibles(self):
        ref = sources.load(REC_2022, streams=['Accel_Sensor.X_axis',
                                              'GPS_NMEA0183_3.oPosition'])
        self.assertAlmostEqual(ref.get('Accel_Sensor.X_axis').measured_fs(), 10.0, delta=0.5)
        self.assertAlmostEqual(ref.get('GPS_NMEA0183_3.oPosition').measured_fs(), 3.0, delta=0.5)

    def test_le_pont_accepte_un_flux_rtmaps(self):
        from ..frames import frame_from_referential
        ref = sources.load(REC_2022, streams=['Accel_Sensor.X_axis'])
        cadre = frame_from_referential(ref, 'Accel_Sensor.X_axis', t0=0.0, t1=5.0)
        self.assertEqual(cadre.data_type, DataType.TIMESERIES)
        self.assertIn('time', cadre.df.columns)


@unittest.skipUnless(REC_2019.exists(), absence_reason(REC_2019))
class Corpus2019Test(unittest.TestCase):
    """Le corpus 2019 (1,54 Go, RTMaps v4.5.3) — **inventaire seulement**.

    ⚠ On ne le LIT pas : 1,54 Go dans une suite de tests serait un contrôle qu'on finirait par
    désactiver. L'inventaire, lui, coûte 2,7 Ko — et c'est précisément le point que ce corpus
    doit prouver : que l'ancienne grammaire du `.idy` passe.
    """

    def test_l_ANCIENNE_grammaire_est_lue(self):
        info = sources.probe(REC_2019)
        self.assertEqual(len(info.streams), 20)
        self.assertIn('DR2.message', info.streams)
        self.assertEqual(info.attributes['encodages']['BIOPAC_MP150.resp'], 'tabbed_text')

    def test_l_inventaire_vient_du_idy_pas_du_gigaoctet(self):
        self.assertEqual(sources.probe(REC_2019).attributes['inventaire'], 'idy')


if __name__ == '__main__':
    unittest.main()
