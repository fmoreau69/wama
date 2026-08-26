"""
Tests de l'écrivain de conteneur.

LA CONTRE-ÉPREUVE QUI COMPTE — et elle ne coûte rien
    Un `.trip` écrit par WAMA est **relu par `TripReader`**, c'est-à-dire par un module qui a été
    écrit contre le format de BIND sans rien savoir de cet écrivain. Un aller-retour jugé par le
    seul écrivain ne prouverait que sa cohérence interne ; ici les deux bouts sont indépendants,
    exactement comme le lecteur `.rec` avait été confronté à l'export CSV de RTMaps.

    ⚠ C'est aussi le seul contrôle qui atteste la CLAIM de compatibilité. « Ça écrit du `.trip` »
    n'est pas vérifiable ; « le lecteur du format de BIND retrouve les flux, les instants et les
    valeurs » l'est.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from wama.common.catalog.data_types import DataType

from ..core.temporal import PREVIOUS, Signal, SignalMeta, TemporalReferential
from ..sources import trip as lecteur_trip
from ..sources import wdat as lecteur_wdat
from . import (Contexte, Rapport, SCHEMAS, ecrire, extensions_ecrivables, modules_schemas,
               schema_pour, schemas_disponibles)


def _signal(name, temps, lignes=None, *, data_type=DataType.TIMESERIES, ends=None, **kw):
    meta = SignalMeta(name=name, data_type=data_type, **kw)
    acces = (lambda i0, i1: lignes[i0:i1]) if lignes is not None else None
    return Signal(meta, temps, acces, ends=ends)


def _referentiel():
    """Trois flux, un par famille — le cas minimal qui exerce les deux schémas de bout en bout."""
    ref = TemporalReferential(name='essai')
    ref.add(_signal(
        'vitesse', [0.0, 0.1, 0.2],
        [{'timecode': 0.0, 'value': 10.0, 'mode': 'auto'},
         {'timecode': 0.1, 'value': 11.5, 'mode': 'auto'},
         {'timecode': 0.2, 'value': None, 'mode': 'manuel'}],
        fs=10.0, units={'value': 'm/s'}))
    ref.add(_signal(
        'marqueurs', [1.0, 2.0], [{'timecode': 1.0, 'label': 'debut'},
                                  {'timecode': 2.0, 'label': 'fin'}],
        data_type=DataType.EVENTS, default_lookup=PREVIOUS))
    ref.add(_signal(
        'phases', [0.0, 5.0], [{'startTimecode': 0.0, 'endTimecode': 3.0, 'name': 'a'},
                               {'startTimecode': 5.0, 'endTimecode': None, 'name': 'b'}],
        data_type=DataType.SEGMENTS, ends=[3.0, None]))
    return ref


class RegistreTest(unittest.TestCase):
    """G1 côté écriture : le moteur ne cite aucun format."""

    def test_les_deux_schemas_livres_sont_enregistres(self):
        self.assertEqual(schemas_disponibles(), ['trip', 'wdat'])

    def test_les_schemas_sont_DECOUVERTS_pas_cites(self):
        moteur = (Path(__file__).parent / '__init__.py').read_text(encoding='utf-8')
        for name in modules_schemas():
            self.assertNotIn(
                f'from . import {name}', moteur,
                "le moteur cite un schéma : ajouter un format obligerait à l'éditer (G1)")

    def test_un_schema_se_trouve_par_son_nom_ou_par_une_extension(self):
        self.assertIs(schema_pour('wdat'), SCHEMAS['wdat'])
        self.assertIs(schema_pour('/tmp/x/essai.trip'), SCHEMAS['trip'])
        self.assertIs(schema_pour(Path('a.wdat')), SCHEMAS['wdat'])
        self.assertIsNone(schema_pour('essai.inconnu'))

    def test_les_extensions_ecrivables_sont_annoncees(self):
        self.assertEqual(extensions_ecrivables(), ['.trip', '.wdat'])


class EcritureTest(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix='wama_conteneur_'))
        self.ref = _referentiel()

    def tearDown(self):
        for f in self.dossier.glob('*'):
            f.unlink(missing_ok=True)
        self.dossier.rmdir()

    # ── Moteur ────────────────────────────────────────────────────────────────────────────────
    def test_le_format_se_deduit_de_l_extension(self):
        rapport = ecrire(self.ref, self.dossier / 'a.wdat')
        self.assertEqual(rapport.format, 'wdat')

    def test_une_extension_inconnue_est_refusee_en_nommant_les_formats_connus(self):
        with self.assertRaises(ValueError) as ctx:
            ecrire(self.ref, self.dossier / 'a.inconnu')
        self.assertIn('trip', str(ctx.exception))
        self.assertIn('wdat', str(ctx.exception))

    def test_un_conteneur_existant_n_est_PAS_ecrase_sans_le_dire(self):
        cible = self.dossier / 'a.wdat'
        ecrire(self.ref, cible)
        with self.assertRaises(FileExistsError):
            ecrire(self.ref, cible)
        ecrire(self.ref, cible, ecraser=True)   # explicite → autorisé

    def test_une_ecriture_qui_echoue_ne_laisse_NI_fichier_NI_partiel(self):
        """Le fichier de travail est tout ou rien : un conteneur à moitié rempli s'ouvre
        normalement et ment sur son contenu."""
        casse = TemporalReferential(name='casse')
        casse.add(_signal('boum', [0.0, 1.0], None))
        signal = casse.get('boum')
        signal._rows = lambda i0, i1: (_ for _ in ()).throw(RuntimeError('disque'))
        cible = self.dossier / 'casse.wdat'
        with self.assertRaises(RuntimeError):
            ecrire(casse, cible)
        self.assertFalse(cible.exists())
        self.assertFalse(cible.with_name(cible.name + '.partiel').exists())

    def test_un_echec_ne_detruit_pas_la_version_precedente(self):
        cible = self.dossier / 'a.wdat'
        ecrire(self.ref, cible)
        before = cible.read_bytes()
        casse = TemporalReferential(name='casse')
        casse.add(_signal('boum', [0.0], None))
        casse.get('boum')._rows = lambda i0, i1: (_ for _ in ()).throw(RuntimeError('disque'))
        with self.assertRaises(RuntimeError):
            ecrire(casse, cible, ecraser=True)
        self.assertEqual(cible.read_bytes(), before,
                         "un échec a remplacé un conteneur valide par rien")

    def test_on_peut_n_ecrire_qu_une_partie_des_flux(self):
        rapport = ecrire(self.ref, self.dossier / 'a.wdat', flux=['vitesse'])
        self.assertEqual(list(rapport.tables), ['flux_vitesse'])
        self.assertEqual(rapport.lignes, 3)

    # ── Valeurs ───────────────────────────────────────────────────────────────────────────────
    def test_une_valeur_ABSENTE_arrive_en_NULL(self):
        """⚠ Ce test vérifie le RÉSULTAT, pas un garde-fou : la morsure a montré que neutraliser
        `manquant()` ne le fait pas échouer, parce que **SQLite coerce lui-même `NaN` en `NULL`**.
        Il reste utile (il attesterait une régression du chemin d'écriture) mais il ne prouve pas
        ce que je lui avais d'abord fait dire."""
        import math
        ref = TemporalReferential()
        ref.add(_signal('x', [0.0, 1.0, 2.0],
                        [{'v': 1.0}, {'v': None}, {'v': math.nan}]))
        cible = self.dossier / 'a.wdat'
        ecrire(ref, cible)
        con = sqlite3.connect(cible)
        valeurs = [r[0] for r in con.execute('SELECT "v" FROM "flux_x" ORDER BY "time"')]
        con.close()
        self.assertEqual(valeurs, [1.0, None, None])

    def test_une_absence_DANS_une_structure_reste_du_JSON_VALIDE(self):
        """⭐ Le vrai piège, trouvé par la morsure : `json.dumps([nan])` rend `[NaN]`, que la
        spécification JSON n'accepte pas. Ni `manquant()` ni SQLite ne couvraient ce cas."""
        import math
        ref = TemporalReferential()
        ref.add(_signal('x', [0.0], [{'v': [1.0, math.nan, {'k': math.nan}]}]))
        cible = self.dossier / 'a.wdat'
        ecrire(ref, cible)
        con = sqlite3.connect(cible)
        brut = con.execute('SELECT "v" FROM "flux_x"').fetchone()[0]
        con.close()
        self.assertNotIn('NaN', brut)
        self.assertEqual(json.loads(brut), [1.0, None, {'k': None}])

    def test_l_axe_du_temps_n_est_PAS_reecrit_en_colonne_de_donnees(self):
        """Les lignes d'un `.trip` portent déjà `timecode` ; le recopier dupliquerait l'instant."""
        cible = self.dossier / 'a.wdat'
        ecrire(self.ref, cible)
        con = sqlite3.connect(cible)
        cols = [r[1] for r in con.execute('PRAGMA table_info("flux_vitesse")')]
        con.close()
        self.assertEqual(cols, ['time', 'value', 'mode'])

    def test_une_colonne_apparue_APRES_la_premiere_tranche_est_SIGNALEE(self):
        ref = TemporalReferential()
        lignes = [{'a': 1}, {'a': 2}, {'a': 3, 'surprise': 9}]
        ref.add(_signal('x', [0.0, 1.0, 2.0], lignes))
        rapport = ecrire(ref, self.dossier / 'a.wdat', tranche=2)
        self.assertTrue(any('surprise' in p for p in rapport.pertes),
                        "une variable entière a disparu sans trace")

    def test_l_axe_du_temps_est_INDEXE(self):
        cible = self.dossier / 'a.wdat'
        ecrire(self.ref, cible)
        con = sqlite3.connect(cible)
        idx = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='flux_vitesse'")]
        con.close()
        self.assertIn('idx_flux_vitesse', idx)


class WdatTest(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix='wama_wdat_'))
        self.cible = self.dossier / 'essai.wdat'
        self.ref = _referentiel()

    def tearDown(self):
        for f in self.dossier.glob('*'):
            f.unlink(missing_ok=True)
        self.dossier.rmdir()

    def _table(self, requete, parametres=()):
        con = sqlite3.connect(self.cible)
        try:
            return con.execute(requete, parametres).fetchall()
        finally:
            con.close()

    def test_le_nom_de_table_ne_dit_PAS_la_famille(self):
        """§9nonies appliqué à l'écriture : toutes les familles portent le même préfixe."""
        rapport = ecrire(self.ref, self.cible)
        self.assertEqual(sorted(rapport.tables),
                         ['flux_marqueurs', 'flux_phases', 'flux_vitesse'])

    def test_la_famille_est_dans_le_CATALOGUE(self):
        ecrire(self.ref, self.cible)
        familles = dict(self._table('SELECT name, data_type FROM "WamaStreams"'))
        self.assertEqual(familles, {'vitesse': DataType.TIMESERIES,
                                    'marqueurs': DataType.EVENTS,
                                    'phases': DataType.SEGMENTS})

    def test_les_segments_portent_start_et_end_D9(self):
        ecrire(self.ref, self.cible)
        cols = [r[1] for r in self._table('PRAGMA table_info("flux_phases")')]
        self.assertEqual(cols[:2], ['start', 'end'])

    def test_un_segment_OUVERT_est_ecrit_NULL_pas_referme_d_office(self):
        """D15 : `end = None` dit « fin non observée ». Refermer donnerait une durée mesurée sur
        ce que personne n'a mesuré."""
        ecrire(self.ref, self.cible)
        bornes = self._table('SELECT "start", "end" FROM "flux_phases" ORDER BY "start"')
        self.assertEqual(bornes, [(0.0, 3.0), (5.0, None)])

    def test_les_UNITES_sont_ecrites(self):
        """Le champ que `.trip` déclare, n'alimente jamais et ne relit jamais."""
        ecrire(self.ref, self.cible)
        unites = dict(self._table(
            'SELECT name, unit FROM "WamaVariables" WHERE stream = ?', ('vitesse',)))
        self.assertEqual(unites['value'], 'm/s')

    def test_les_PERTES_d_acquisition_sont_une_colonne(self):
        ref = TemporalReferential()
        ref.add(_signal('x', [0.0], [{'a': 1}], pertes=3))
        ecrire(ref, self.cible)
        self.assertEqual(self._table('SELECT losses FROM "WamaStreams"'), [(3,)])

    def test_la_copie_projetee_est_embarquee_et_estampillee(self):
        contexte = Contexte(auteur='fabien', manifestes=[
            {'manifest_kind': 'pipeline', 'key': 'protocole-a', 'schema_version': '2',
             'body': {'nodes': []}}])
        ecrire(self.ref, self.cible, contexte=contexte)
        lignes = self._table('SELECT manifest_kind, key, version, read_only, body '
                             'FROM "WamaManifests"')
        self.assertEqual(len(lignes), 1)
        kind, cle, version, lecture_seule, corps = lignes[0]
        self.assertEqual((kind, cle, version, lecture_seule), ('pipeline', 'protocole-a', '2', 1))
        self.assertEqual(json.loads(corps)['body'], {'nodes': []})

    def test_une_copie_projetee_SANS_ESTAMPILLE_est_REFUSEE(self):
        """Sans estampille, la copie cesse d'être une projection et devient une seconde source."""
        contexte = Contexte(manifestes=[{'body': {'nodes': []}}])
        with self.assertRaises(ValueError) as ctx:
            ecrire(self.ref, self.cible, contexte=contexte)
        self.assertIn('estampille', str(ctx.exception))
        self.assertFalse(self.cible.exists(), "un refus a quand même laissé un conteneur")

    def test_l_auteur_et_la_date_sont_ecrits(self):
        """L'usage visé est collaboratif : sans qui/quand, le suivi exige une base partagée."""
        ecrire(self.ref, self.cible, contexte=Contexte(auteur='fabien', horodatage='2026-08-24'))
        meta = dict(self._table('SELECT key, value FROM "WamaMeta"'))
        self.assertEqual(meta['created_by'], 'fabien')
        self.assertEqual(meta['created_at'], '2026-08-24')
        self.assertEqual(meta['format'], 'wdat')

    def test_le_format_natif_ne_declare_AUCUNE_perte(self):
        rapport = ecrire(self.ref, self.cible)
        self.assertTrue(rapport.fidele, rapport.pertes)


class TripCompatibiliteTest(unittest.TestCase):
    """⭐ La contre-épreuve : ce que WAMA écrit, le lecteur du format de BIND le relit."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix='wama_trip_'))
        self.cible = self.dossier / 'essai.trip'
        self.ref = _referentiel()

    def tearDown(self):
        for f in self.dossier.glob('*'):
            f.unlink(missing_ok=True)
        self.dossier.rmdir()

    def test_les_prefixes_de_table_sont_ceux_du_format_de_l_autre(self):
        rapport = ecrire(self.ref, self.cible)
        self.assertEqual(sorted(rapport.tables),
                         ['data_vitesse', 'event_marqueurs', 'situation_phases'])

    def test_le_LECTEUR_EXISTANT_reconnait_le_fichier(self):
        ecrire(self.ref, self.cible)
        self.assertTrue(lecteur_trip.TripReader().can_read(self.cible))

    def test_le_LECTEUR_EXISTANT_retrouve_les_flux_les_instants_et_les_valeurs(self):
        ecrire(self.ref, self.cible)
        relu = lecteur_trip.TripReader().read(self.cible)
        par_nom = {s.meta.name: s for s in relu}
        self.assertEqual(sorted(par_nom), ['marqueurs', 'phases', 'vitesse'])
        self.assertEqual(list(par_nom['vitesse'].times), [0.0, 0.1, 0.2])
        lignes = par_nom['vitesse'].rows(0, 3)
        self.assertEqual([l['value'] for l in lignes], [10.0, 11.5, None])
        self.assertEqual([l['mode'] for l in lignes], ['auto', 'auto', 'manuel'])

    def test_l_aller_retour_conserve_la_FAMILLE(self):
        """Le préfixe est la seule chose qui la porte dans ce format — il doit donc être juste."""
        ecrire(self.ref, self.cible)
        relu = {s.meta.name: s.meta.data_type for s in lecteur_trip.TripReader().read(self.cible)}
        self.assertEqual(relu, {'vitesse': DataType.TIMESERIES,
                                'marqueurs': DataType.EVENTS,
                                'phases': DataType.SEGMENTS})

    def test_l_aller_retour_conserve_les_BORNES_de_segment(self):
        ecrire(self.ref, self.cible)
        phases = {s.meta.name: s for s in lecteur_trip.TripReader().read(self.cible)}['phases']
        self.assertEqual(list(phases.times), [0.0, 5.0])
        self.assertEqual(list(phases.ends), [3.0, None])

    def test_la_colonne_de_TEMPS_figure_parmi_les_variables_comme_dans_le_releve(self):
        ecrire(self.ref, self.cible)
        con = sqlite3.connect(self.cible)
        noms = [r[0] for r in con.execute(
            'SELECT name FROM "MetaSituationVariables" WHERE situation_name = ?', ('phases',))]
        con.close()
        self.assertIn('startTimecode', noms)
        self.assertIn('endTimecode', noms)

    def test_les_trois_tables_de_declaration_sont_alimentees_selon_la_famille(self):
        ecrire(self.ref, self.cible)
        con = sqlite3.connect(self.cible)
        try:
            self.assertEqual([r[0] for r in con.execute('SELECT name FROM "MetaDatas"')],
                             ['vitesse'])
            self.assertEqual([r[0] for r in con.execute('SELECT name FROM "MetaEvents"')],
                             ['marqueurs'])
            self.assertEqual([r[0] for r in con.execute('SELECT name FROM "MetaSituations"')],
                             ['phases'])
        finally:
            con.close()

    # ── Ce que la langue de l'autre ne sait pas dire ──────────────────────────────────────────
    def test_un_segment_OUVERT_est_declare_PERDU(self):
        rapport = ecrire(self.ref, self.cible)
        self.assertTrue(any('OUVERT' in p for p in rapport.pertes), rapport.pertes)

    def test_une_copie_projetee_est_declaree_NON_embarquee(self):
        contexte = Contexte(manifestes=[{'manifest_kind': 'pipeline', 'key': 'p'}])
        rapport = ecrire(self.ref, self.cible, contexte=contexte)
        self.assertTrue(any('autoportant' in p for p in rapport.pertes), rapport.pertes)

    def test_les_pertes_d_acquisition_sont_declarees_PERDUES(self):
        ref = TemporalReferential()
        ref.add(_signal('x', [0.0], [{'a': 1}], pertes=3))
        rapport = ecrire(ref, self.cible)
        self.assertTrue(any("pertes d'acquisition" in p for p in rapport.pertes), rapport.pertes)

    def test_une_cadence_FRACTIONNAIRE_est_declaree_arrondie(self):
        ref = TemporalReferential()
        ref.add(_signal('x', [0.0], [{'a': 1}], fs=18.7))
        rapport = ecrire(ref, self.cible)
        self.assertTrue(any('ARRONDIE' in p for p in rapport.pertes), rapport.pertes)

    def test_une_cadence_sur_un_EVENEMENT_est_declaree_perdue(self):
        """`MetaEvents` et `MetaSituations` n'ont pas de colonne `frequency` — mesuré."""
        ref = TemporalReferential()
        ref.add(_signal('e', [0.0], [{'a': 1}], data_type=DataType.EVENTS, fs=2.0))
        rapport = ecrire(ref, self.cible)
        self.assertTrue(any('frequency' in p for p in rapport.pertes), rapport.pertes)

    def test_une_famille_NON_DECLAREE_est_devinee_ET_signalee(self):
        ref = TemporalReferential()
        ref.add(_signal('muet', [0.0], [{'a': 1}], data_type=''))
        rapport = ecrire(ref, self.cible)
        self.assertIn('data_muet', rapport.tables)
        self.assertTrue(any('DEVINÉE' in p for p in rapport.pertes), rapport.pertes)

    def test_le_rapport_dit_qu_il_N_EST_PAS_fidele(self):
        rapport = ecrire(self.ref, self.cible)
        self.assertFalse(rapport.fidele)
        self.assertIn('perte', rapport.notes)


class EncodageLecteurTest(unittest.TestCase):
    """Le texte cp1252 des bases réelles — défaut trouvé en relevant le schéma pour l'écrivain."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix='wama_cp1252_'))
        self.cible = self.dossier / 'ancien.trip'

    def tearDown(self):
        for f in self.dossier.glob('*'):
            f.unlink(missing_ok=True)
        self.dossier.rmdir()

    def _base_cp1252(self):
        """Reproduit ce que BIND écrit sous Windows : du cp1252 dans un SQLite."""
        con = sqlite3.connect(self.cible)
        con.execute('CREATE TABLE "MetaDatas" (name TEXT, type TEXT, frequency INT, '
                    'comments TEXT, isBase BOOL)')
        con.execute('CREATE TABLE "data_x" (timecode REAL, note TEXT)')
        con.execute('INSERT INTO "MetaDatas" VALUES (?, ?, ?, CAST(? AS TEXT), ?)',
                    ('x', 'REAL', 0, 'Ajouté à partir de BIND_GUI'.encode('cp1252'), 1))
        con.execute('INSERT INTO "data_x" VALUES (?, CAST(? AS TEXT))',
                    (0.0, 'Ajouté'.encode('cp1252')))
        con.commit()
        con.close()

    def test_un_SELECT_brut_ECHOUE_sur_ce_fichier(self):
        """La morsure : sans décodeur, sqlite3 lève une OperationalError — un message qui
        n'oriente même pas vers l'encodage."""
        self._base_cp1252()
        con = sqlite3.connect(f'file:{self.cible}?mode=ro', uri=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute('SELECT * FROM "data_x"').fetchall()
        finally:
            con.close()

    def test_le_lecteur_DECODE_le_texte_au_lieu_d_echouer(self):
        self._base_cp1252()
        lecteur = lecteur_trip.TripReader()
        self.assertTrue(lecteur.can_read(self.cible))
        flux = lecteur.read(self.cible)
        self.assertEqual(flux[0].rows(0, 1)[0]['note'], 'Ajouté',
                         "le repli doit RENDRE le texte, pas le remplacer par des losanges")

    def test_l_UTF8_reste_lu_comme_de_l_UTF8(self):
        """L'ordre des codecs : cp1252 essayé en premier rendrait « AjoutÃ© » sans jamais lever."""
        con = sqlite3.connect(self.cible)
        con.execute('CREATE TABLE "MetaDatas" (name TEXT, type TEXT, frequency INT, '
                    'comments TEXT, isBase BOOL)')
        con.execute('CREATE TABLE "data_x" (timecode REAL, note TEXT)')
        con.execute('INSERT INTO "MetaDatas" VALUES (?, ?, ?, ?, ?)', ('x', 'REAL', 0, '', 1))
        con.execute('INSERT INTO "data_x" VALUES (?, ?)', (0.0, 'Ajouté'))
        con.commit()
        con.close()
        flux = lecteur_trip.TripReader().read(self.cible)
        self.assertEqual(flux[0].rows(0, 1)[0]['note'], 'Ajouté')


class RapportTest(unittest.TestCase):
    def test_un_rapport_sans_perte_est_fidele(self):
        self.assertTrue(Rapport(chemin='a', format='wdat', tables={'t': 2}).fidele)

    def test_un_rapport_compte_toutes_ses_lignes(self):
        self.assertEqual(Rapport(chemin='a', format='wdat',
                                 tables={'a': 2, 'b': 3}).lignes, 5)


class WdatAllerRetourTest(unittest.TestCase):
    """⭐ G7 appliqué au format natif : on écrit, on relit, on compare. Un lecteur jugé sur des
    fixtures qu'il a lui-même inspirées ne prouverait que sa cohérence interne."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix='wama_ar_'))
        self.cible = self.dossier / 'essai.wdat'
        self.ref = _referentiel()
        self.contexte = Contexte(auteur='fabien', horodatage='2026-08-24', manifestes=[
            {'manifest_kind': 'pipeline', 'key': 'protocole-a', 'schema_version': '2',
             'body': {'nodes': [{'id': 'n1'}]}}])

    def tearDown(self):
        for f in self.dossier.glob('*'):
            f.unlink(missing_ok=True)
        self.dossier.rmdir()

    def _relire(self):
        ecrire(self.ref, self.cible, contexte=self.contexte)
        return {s.meta.name: s for s in lecteur_wdat.WdatReader().read(self.cible)}

    def test_le_lecteur_natif_reconnait_ce_que_l_ecrivain_produit(self):
        ecrire(self.ref, self.cible, contexte=self.contexte)
        self.assertTrue(lecteur_wdat.WdatReader().can_read(self.cible))

    def test_un_wdat_n_est_PAS_pris_pour_un_trip(self):
        """Les deux sont du SQLite et le registre rend le PREMIER lecteur qui accepte : sans
        reniflage du contenu, l'un mangerait les fichiers de l'autre."""
        from .. import sources
        ecrire(self.ref, self.cible, contexte=self.contexte)
        self.assertEqual(sources.reader_for(self.cible).format, 'wdat')

    def test_les_flux_les_instants_et_les_valeurs_reviennent(self):
        relu = self._relire()
        self.assertEqual(sorted(relu), ['marqueurs', 'phases', 'vitesse'])
        self.assertEqual(list(relu['vitesse'].times), [0.0, 0.1, 0.2])
        lignes = relu['vitesse'].rows(0, 3)
        self.assertEqual([l['value'] for l in lignes], [10.0, 11.5, None])
        self.assertEqual([l['mode'] for l in lignes], ['auto', 'auto', 'manuel'])

    def test_la_FAMILLE_revient_sans_analyser_un_prefixe(self):
        relu = self._relire()
        self.assertEqual({n: s.meta.data_type for n, s in relu.items()},
                         {'vitesse': DataType.TIMESERIES, 'marqueurs': DataType.EVENTS,
                          'phases': DataType.SEGMENTS})

    def test_les_UNITES_reviennent(self):
        """⭐ Le fait que `.trip` écrit et ne relit jamais. Ici, écrit ET relu."""
        relu = self._relire()
        self.assertEqual(relu['vitesse'].meta.units, {'value': 'm/s'})

    def test_une_unite_VIDE_n_encombre_pas_le_dictionnaire(self):
        relu = self._relire()
        self.assertEqual(relu['marqueurs'].meta.units, {},
                         "un dictionnaire plein de chaînes vides ne se distingue pas d'un "
                         "dictionnaire renseigné")

    def test_les_PERTES_d_acquisition_reviennent(self):
        ref = TemporalReferential()
        ref.add(_signal('x', [0.0], [{'a': 1}], pertes=3))
        ecrire(ref, self.cible)
        relu = lecteur_wdat.WdatReader().read(self.cible)
        self.assertEqual(relu[0].meta.pertes, 3)

    def test_le_DECALAGE_par_flux_revient(self):
        """BIND n'a qu'un décalage par média ; le format natif le porte par flux."""
        ref = TemporalReferential()
        ref.add(_signal('x', [0.0], [{'a': 1}]), offset=-0.65)
        ecrire(ref, self.cible)
        self.assertAlmostEqual(lecteur_wdat.WdatReader().read(self.cible)[0].offset, -0.65)

    def test_un_segment_OUVERT_survit_a_l_aller_retour_ET_reste_INTERROGEABLE(self):
        """⚠ La leçon de D15 : prouver que la valeur SURVIT ne prouve pas qu'on puisse
        l'INTERROGER. On vérifie donc les deux."""
        relu = self._relire()
        phases = relu['phases'].to_signal()
        self.assertEqual(list(relu['phases'].ends), [3.0, None])
        self.assertIsNone(phases.end_at(1))
        self.assertEqual(phases.containing(99.0), [1])       # l'état ouvert court encore
        self.assertEqual(phases.overlapping(0.0, 100.0), [0, 1])

    def test_la_cadence_et_la_PROVENANCE_reviennent(self):
        relu = self._relire()
        self.assertEqual(relu['vitesse'].meta.fs, 10.0)
        self.assertTrue(relu['vitesse'].meta.is_base)

    def test_l_inventaire_COMPTE_les_protocoles_embarques(self):
        ecrire(self.ref, self.cible, contexte=self.contexte)
        info = lecteur_wdat.WdatReader().probe(self.cible)
        self.assertIn('1 protocole(s) embarqué(s)', info.notes)
        self.assertIn('pipeline:protocole-a', info.notes)
        self.assertEqual(info.attributes['created_by'], 'fabien')

    def test_les_protocoles_sont_EXPOSES_mais_jamais_ingeres(self):
        """Rouvrir un conteneur ne doit pas écrire dans le magasin par effet de bord (D16)."""
        ecrire(self.ref, self.cible, contexte=self.contexte)
        protos = lecteur_wdat.WdatReader().protocoles(self.cible)
        self.assertEqual(len(protos), 1)
        self.assertEqual(protos[0]['manifest_kind'], 'pipeline')
        self.assertTrue(protos[0]['read_only'])
        self.assertEqual(protos[0]['body']['body'], {'nodes': [{'id': 'n1'}]})

    def test_un_flux_INCONNU_est_refuse_en_nommant_les_flux_reels(self):
        ecrire(self.ref, self.cible, contexte=self.contexte)
        with self.assertRaises(ValueError) as ctx:
            lecteur_wdat.WdatReader().read(self.cible, streams=['fantome'])
        self.assertIn('vitesse', str(ctx.exception))

    def test_le_point_d_entree_UNIVERSEL_charge_un_wdat_sans_savoir_qui_le_lit(self):
        from .. import sources
        ecrire(self.ref, self.cible, contexte=self.contexte)
        referentiel = sources.load(self.cible)
        self.assertEqual(referentiel.names, ['marqueurs', 'phases', 'vitesse'])
        self.assertEqual(referentiel.at('vitesse', 0.11), 1)


class NomAbandonneTest(unittest.TestCase):
    """⚠ LA GARDE DU RENOMMAGE (D17, 2026-08-24). Le conteneur natif s'est appelé `.wrec` pendant
    24 heures avant de devenir `.wdat`.

    Pourquoi un test et pas une relecture : **un renommage ne casse rien, il rend FAUX** (leçon du
    23/08). Une occurrence oubliée ne lève aucune exception — elle produit une comparaison qui
    n'égale plus rien, un chemin qui ne pointe plus, ou une phrase de documentation qui décrit un
    format disparu. Aucun de ces trois cas ne se signale.

    ⚠ Le contrôle porte sur LE MONDE ENTIER, pas sur ce paquet : la chaîne vivait aussi dans
    `modules.py`, `core/noms.py` et `sources/`. Un garde-fou qui ne regarde que chez lui reproduit
    exactement le défaut de `mecanismes_scan.py`, corrigé le même jour — il accusait précisément
    le monde qu'il ne balayait pas.
    """

    ABANDONNE = 'wrec'

    #: Les SEULS fichiers autorisés à prononcer le nom abandonné, et pourquoi. ⚠ Une dérogation
    #: non motivée est une porte ouverte : la liste est courte, nominative, et **vérifiée** par
    #: `test_aucune_derogation_PERIMEE` — une dérogation qui ne sert plus doit disparaître, sinon
    #: elle finirait par couvrir une vraie régression le jour où le fichier change de contenu.
    DEROGATIONS = {
        'containers/tests_containers.py': "la garde doit nommer ce qu'elle interdit",
        'containers/wdat.py': "l'en-tête CONSIGNE la supersession (D3 → D17) — « consigner ce "
                              "que ça remplace » est une règle du dépôt",
    }

    def _occurrences(self):
        monde = Path(__file__).resolve().parents[1]
        trouve = {}
        for f in sorted(monde.rglob('*.py')):
            if '__pycache__' in str(f):
                continue
            texte = f.read_text(encoding='utf-8')
            if self.ABANDONNE in texte.lower():
                rel = f.relative_to(monde).as_posix()
                trouve[rel] = [i for i, l in enumerate(texte.splitlines(), 1)
                               if self.ABANDONNE in l.lower()]
        return trouve

    def test_le_nom_ABANDONNE_ne_survit_nulle_part_dans_le_monde(self):
        fautifs = [f"{rel}:{','.join(map(str, lignes))}"
                   for rel, lignes in self._occurrences().items()
                   if rel not in self.DEROGATIONS]
        self.assertEqual(
            fautifs, [],
            f"« {self.ABANDONNE} » a survécu au renommage D17 — et ça ne lèvera jamais tout "
            f"seul : {'; '.join(fautifs)}")

    def test_aucune_derogation_PERIMEE(self):
        """⚠ Le second risque d'une liste de dérogations : qu'elle survive à sa raison d'être."""
        presents = set(self._occurrences())
        mortes = sorted(set(self.DEROGATIONS) - presents)
        self.assertEqual(mortes, [],
                         f"dérogation sans objet — à retirer : {', '.join(mortes)}")

    def test_le_nom_RETENU_est_bien_celui_qui_est_enregistre(self):
        """Contre-épreuve : la garde ci-dessus passerait aussi si le format avait disparu."""
        self.assertIn('wdat', SCHEMAS)
        self.assertEqual(SCHEMAS['wdat'].extension, '.wdat')
        self.assertIn('.wdat', extensions_ecrivables())
