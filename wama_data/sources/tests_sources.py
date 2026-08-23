"""Tests de l'importer universel (`sources/`) — le registre et ses capacités.

Comme `tests_temporal`, ce fichier remplace des scripts jetables. Il vérifie ce qui fait la valeur
du registre : qu'AUCUN format n'est privilégié, que le contrat tient sur deux formats sans rien de
commun, et que le ré-horodatage ne se déclenche jamais tout seul.
"""
import csv
import tempfile
import unittest
from pathlib import Path

from wama_data import sources
from wama_data.sources import ResamplingTS, TimeOfIssueTS, TimestampTS

from ..corpus import BASE_REELLE, raison_absence


class RegistreTest(unittest.TestCase):
    def test_au_moins_deux_capacites(self):
        # Un registre à un seul lecteur ne prouve rien : c'est un lecteur déguisé.
        self.assertGreaterEqual(len(sources.READERS), 2)

    def test_aiguillage_par_format(self):
        self.assertEqual(sources.reader_for(Path("x.csv")).format, "tabular")

    def test_xlsx_decline_proprement_si_la_dependance_manque(self):
        # `openpyxl` est optionnel. Un lecteur qui ne peut pas honorer un format doit le DÉCLINER
        # à la reconnaissance, pas échouer à la lecture : l'appelant reçoit alors un message sur
        # la capacité absente au lieu d'une ImportError au milieu d'un import.
        try:
            import openpyxl  # noqa: F401
            dispo = True
        except ImportError:
            dispo = False
        lecteur = sources.reader_for(Path("x.xlsx"))
        if dispo:
            self.assertEqual(lecteur.format, "tabular")
        else:
            self.assertIsNone(lecteur)

    def test_format_inconnu_rend_none_sans_lever(self):
        self.assertIsNone(sources.reader_for(Path("x.rosbag")))

    def test_load_sur_format_inconnu_dit_pourquoi(self):
        with self.assertRaises(ValueError) as ctx:
            sources.load("x.inconnu")
        self.assertIn("aucune capacité", str(ctx.exception))
        self.assertIn(".csv", str(ctx.exception))   # le message LISTE ce qui est connu

    def test_extensions_declarees(self):
        self.assertIn(".trip", sources.supported_extensions())
        self.assertIn(".csv", sources.supported_extensions())


class HorodatageTest(unittest.TestCase):
    """Trois stratégies, et une distinction que la confusion courante écrase."""

    def test_timestamp_prefere_l_horodatage_porte(self):
        ts = TimestampTS()
        self.assertEqual(ts.timestamp(100.0, 0, 42.0), 42.0)
        self.assertEqual(ts.missing, 0)

    def test_le_repli_est_signale_pas_silencieux(self):
        ts = TimestampTS()
        self.assertEqual(ts.timestamp(100.0, 0, None), 100.0)
        self.assertEqual(ts.missing, 1, "un basculement de source de temps doit se compter")

    def test_time_of_issue(self):
        self.assertEqual(TimeOfIssueTS().timestamp(7.0, 3, 99.0), 7.0)

    def test_re_horodatage_n_interpole_pas(self):
        # Il RECALCULE les étiquettes ; il ne crée ni ne supprime d'échantillon.
        ts = ResamplingTS(100.0)
        instants = [ts.timestamp(0.0, i, 10.0) for i in range(5)]
        self.assertEqual(instants, [10.0, 10.01, 10.02, 10.03, 10.04])

    def test_origine_fixee_par_le_premier(self):
        ts = ResamplingTS(50.0)
        ts.timestamp(0.0, 0, 5.0)
        self.assertEqual(ts.timestamp(0.0, 10, 999.0), 5.2)   # 5.0 + 10/50

    def test_frequence_invalide_refusee(self):
        with self.assertRaises(ValueError):
            ResamplingTS(0)


class TabulaireTest(unittest.TestCase):
    """Le contrat tient sur un format qui n'a rien de commun avec une base SQL."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.csv = Path(self.dir.name) / "capteur.csv"
        with self.csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["time", "speed", "mode"])
            for i in range(200):
                w.writerow([round(i * 0.05, 3), 10 + (i % 5), "AUTO" if i % 2 else "MANUAL"])

    def tearDown(self):
        self.dir.cleanup()

    def test_probe_avant_de_charger(self):
        info = sources.probe(self.csv)
        self.assertEqual(info.format, "tabular")
        self.assertEqual(info.attributes["rows"], 200)
        self.assertIn("time", info.notes)

    def test_chargement_et_cadence_deduite(self):
        ref = sources.load(self.csv)
        s = ref.get("capteur")
        self.assertEqual(len(s), 200)
        self.assertAlmostEqual(s.measured_fs(), 20.0, places=3)

    def test_acces_aux_valeurs(self):
        ref = sources.load(self.csv)
        i = ref.at("capteur", 1.0)
        # ⚠ Ce test assertait `"1.0"` — une CHAÎNE — sans justification : il enregistrait le
        # défaut plutôt qu'une décision. Un CSV ne porte aucun type, et le lecteur ne convertissait
        # que l'axe du temps utilisé pour l'indexation ; les LIGNES restaient textuelles. Un jeu
        # importé traversait donc tout et levait au premier calcul (`fmean` : « must be real
        # number, not str »). Corrigé le 2026-08-24 (`tabular._numerise`).
        self.assertEqual(ref.get("capteur").rows(i, i + 1)[0]["time"], 1.0)

    def test_une_colonne_ENTIEREMENT_numerique_est_convertie(self):
        # La fixture mêle du numérique (`time`, `speed`) et du catégoriel (`mode`) — c'est le cas
        # réel, et il montre les deux comportements d'un coup.
        ligne = sources.load(self.csv).get("capteur").rows(0, 1)[0]
        self.assertIsInstance(ligne["time"], float)
        self.assertIsInstance(ligne["speed"], float)
        self.assertIsInstance(ligne["mode"], str)

    def test_une_colonne_MIXTE_reste_du_TEXTE(self):
        # La décision est prise PAR COLONNE, jamais par cellule : convertir « quand ça marche »
        # ferait qu'une même colonne se comparerait tantôt comme du texte, tantôt comme un nombre.
        f = Path(self.dir.name) / "mixte.csv"
        f.write_text("time,v,note\n0,1,ok\n1,2,3\n", encoding="utf-8")
        ligne = sources.load(f).get("mixte").rows(0, 1)[0]
        self.assertEqual(ligne["v"], 1.0)
        self.assertEqual(ligne["note"], "ok")

    def test_une_cellule_VIDE_ne_disqualifie_pas_la_colonne(self):
        # Un trou est un trou, pas une valeur textuelle — il devient `None`.
        f = Path(self.dir.name) / "trou.csv"
        f.write_text("time,v\n0,1\n1,\n2,3\n", encoding="utf-8")
        lignes = sources.load(f).get("trou").rows(0, 3)
        self.assertEqual([l["v"] for l in lignes], [1.0, None, 3.0])

    def test_separateur_point_virgule(self):
        f = Path(self.dir.name) / "fr.csv"
        f.write_text("time;value\n0;1\n0.5;2\n1;3\n", encoding="utf-8")
        self.assertEqual(len(sources.load(f).get("fr")), 3)

    def test_colonne_temporelle_alternative(self):
        f = Path(self.dir.name) / "alt.csv"
        f.write_text("timestamp,v\n0,1\n1,2\n", encoding="utf-8")
        self.assertEqual(len(sources.load(f).get("alt")), 2)

    def test_sans_colonne_temporelle_refus_explicite(self):
        f = Path(self.dir.name) / "sans.csv"
        f.write_text("a,b\n1,2\n", encoding="utf-8")
        self.assertEqual(sources.probe(f).streams, [])      # probe SIGNALE sans lever
        with self.assertRaises(ValueError) as ctx:
            sources.load(f)
        self.assertIn("colonne temporelle", str(ctx.exception))

    def test_lignes_sans_temps_exploitable_ecartees(self):
        f = Path(self.dir.name) / "sale.csv"
        f.write_text("time,v\n0,1\nNON,2\n1,3\n", encoding="utf-8")
        self.assertEqual(len(sources.load(f).get("sale")), 2)   # écartée, pas devinée

    def test_re_horodatage_a_la_demande_seulement(self):
        sans = sources.load(self.csv).get("capteur")
        avec = sources.load(self.csv,
                            timestampers={"capteur": ResamplingTS(10.0)}).get("capteur")
        self.assertEqual(len(sans), len(avec), "aucun échantillon perdu ni créé")
        self.assertAlmostEqual(avec.measured_fs(), 10.0, places=3)
        self.assertNotAlmostEqual(sans.measured_fs(), 10.0, places=3)


def _trip_synthetique(chemin: Path) -> Path:
    """Construit un `.trip` MINIMAL — les trois familles de table, quelques lignes.

    ⚠ POURQUOI CE FIXTURE EXISTE (2026-08-24). Jusqu'ici, **les seuls tests du `TripReader`
    étaient `BaseReelleTest`**, conditionnés à un fichier de 1,28 Go vivant HORS DÉPÔT
    (`claude/`, gitignoré). Le jour où ce fichier a disparu de la machine, le lecteur le plus
    complexe du monde Data s'est retrouvé avec **zéro couverture** — et rien ne l'a signalé
    autrement que par « 10 sautés » dans un compte-rendu que personne ne lit ligne à ligne.

    C'est le garde-fou **G7** (« cas complet de bout en bout — nécessite un échantillon réduit
    VERSIONNÉ ») : on le satisfait en GÉNÉRANT l'échantillon plutôt qu'en committant un binaire.
    Le schéma reproduit ici est celui relevé sur la base réelle (§6.2-6.3), pas un schéma inventé.
    """
    import sqlite3
    con = sqlite3.connect(chemin)
    try:
        con.execute('CREATE TABLE "MetaDatas" (name TEXT, type TEXT, frequency TEXT, isBase INT)')
        con.executemany('INSERT INTO "MetaDatas" VALUES (?,?,?,?)', [
            ('vitesse', 'data', '10', 1),
            ('freinage', 'event', '', 1),
            ('0_15', 'situation', '', 0),
        ])
        con.execute('CREATE TABLE "data_vitesse" (timecode REAL, value REAL)')
        con.executemany('INSERT INTO "data_vitesse" VALUES (?,?)',
                        [(float(i), 10.0 * i) for i in range(5)])
        con.execute('CREATE TABLE "event_freinage" (timecode REAL, intensite REAL)')
        con.executemany('INSERT INTO "event_freinage" VALUES (?,?)', [(1.0, 0.4), (3.0, 0.9)])
        con.execute('CREATE TABLE "situation_0_15" '
                    '(startTimecode REAL, endTimecode REAL, label TEXT)')
        con.executemany('INSERT INTO "situation_0_15" VALUES (?,?,?)', [(1.0, 3.0, 'approche')])
        con.commit()
    finally:
        con.close()
    return chemin


class TripSynthetiqueTest(unittest.TestCase):
    """Le `TripReader` sans le corpus de 1,28 Go — couverture qui ne dépend de rien d'externe."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.trip = _trip_synthetique(Path(self.dir.name) / "essai.trip")

    def tearDown(self):
        self.dir.cleanup()

    def test_le_lecteur_le_reconnait(self):
        r = sources.reader_for(self.trip)
        self.assertIsNotNone(r)
        self.assertEqual(r.format, 'trip')

    def test_un_sqlite_SANS_le_catalogue_attendu_est_decline(self):
        # `can_read` renifle le CONTENU : un fichier mal nommé ne doit pas échouer loin de sa cause.
        import sqlite3
        faux = Path(self.dir.name) / "faux.trip"
        sqlite3.connect(faux).close()
        self.assertIsNone(sources.reader_for(faux))

    def test_probe_liste_les_trois_familles(self):
        self.assertEqual(sorted(sources.probe(self.trip).streams),
                         ['data_vitesse', 'event_freinage', 'situation_0_15'])

    def test_la_FAMILLE_est_portee_comme_DONNEE_pas_comme_commentaire(self):
        """⚠ Le test de la correction du 2026-08-24 : la famille vivait dans `comments`."""
        from wama.common.catalog.data_types import DataType
        ref = sources.load(self.trip)
        self.assertEqual(ref.get('vitesse').meta.data_type, DataType.TIMESERIES)
        self.assertEqual(ref.get('freinage').meta.data_type, DataType.EVENTS)
        self.assertEqual(ref.get('0_15').meta.data_type, DataType.SEGMENTS)

    def test_le_pont_distingue_desormais_DONNEES_et_EVENEMENTS(self):
        # Structurellement identiques (des instants + des colonnes) : seule la famille déclarée
        # les sépare. C'est exactement ce que le pont ne savait pas faire.
        from wama.common.catalog.data_types import DataType

        from wama_data.frames import frame_depuis_referentiel
        ref = sources.load(self.trip)
        self.assertEqual(frame_depuis_referentiel(ref, 'vitesse').data_type, DataType.TIMESERIES)
        self.assertEqual(frame_depuis_referentiel(ref, 'freinage').data_type, DataType.EVENTS)

    def test_une_situation_porte_ses_DEUX_bornes(self):
        ref = sources.load(self.trip)
        s = ref.get('0_15')
        self.assertTrue(s.is_segments)
        self.assertEqual(s.containing(2.0), [0])

    def test_le_lookup_suit_la_famille(self):
        from wama_data.core.temporal import NEAREST, PREVIOUS
        ref = sources.load(self.trip)
        self.assertEqual(ref.get('vitesse').meta.default_lookup, NEAREST)
        self.assertEqual(ref.get('freinage').meta.default_lookup, PREVIOUS)

    def test_les_valeurs_sont_lisibles(self):
        ref = sources.load(self.trip, streams=['data_vitesse'])
        ligne = ref.get('vitesse').rows(2, 3)[0]
        self.assertEqual(ligne['value'], 20.0)

    def test_frequence_non_numerique_ne_casse_PAS_le_flux(self):
        # Mesuré sur la base réelle : `frequency` vaut '' pour les flux dérivés, et `float('')`
        # levait, rendant le flux entier illisible.
        ref = sources.load(self.trip)
        self.assertIsNone(ref.get('freinage').meta.fs)
        self.assertEqual(ref.get('vitesse').meta.fs, 10.0)


@unittest.skipUnless(BASE_REELLE.exists(), raison_absence())
class BaseReelleTest(unittest.TestCase):
    def test_reconnaissance_par_le_CONTENU(self):
        r = sources.reader_for(BASE_REELLE)
        self.assertEqual(r.format, "trip")

    def test_probe_n_ouvre_pas_les_donnees(self):
        info = sources.probe(BASE_REELLE)
        self.assertGreater(len(info.streams), 20)
        self.assertTrue(info.media, "les médias liés et leur offset doivent être inventoriés")
        self.assertIn("recording_start_time", info.attributes)

    def test_semantique_derivee_de_la_famille(self):
        ref = sources.load(BASE_REELLE,
                           streams=["data_BIOPAC_MP150", "event_CADISP", "situation_0_15"])
        self.assertEqual(ref.get("BIOPAC_MP150").meta.default_lookup, "nearest")
        # Un événement et un segment valent jusqu'au suivant.
        self.assertEqual(ref.get("CADISP").meta.default_lookup, "previous")
        self.assertEqual(ref.get("0_15").meta.default_lookup, "previous")

    def test_is_base_distingue_acquis_et_derive(self):
        ref = sources.load(BASE_REELLE,
                           streams=["data_BIOPAC_MP150", "data_ECG_processed"])
        self.assertTrue(ref.get("BIOPAC_MP150").meta.is_base)
        self.assertFalse(ref.get("ECG_processed").meta.is_base)

    def test_lecture_paresseuse(self):
        ref = sources.load(BASE_REELLE, streams=["data_BIOPAC_MP150"])
        s = ref.get("BIOPAC_MP150")
        self.assertGreater(len(s), 1_000_000)
        self.assertEqual(len(s.rows(1000, 1005)), 5)   # 5 lignes, pas 2 millions

    def test_segments_portent_leurs_deux_bornes(self):
        ref = sources.load(BASE_REELLE, streams=["situation_0_15"])
        s = ref.get("0_15")
        self.assertTrue(s.is_segments)
        self.assertAlmostEqual(s.duration_at(0), 15.0, places=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
