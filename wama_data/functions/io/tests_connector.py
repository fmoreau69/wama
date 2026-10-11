"""Le CONNECTOR et l'export d'un NŒUD DE SORTIE — sur de vraies bases `.wdat` écrites par
l'écrivain du monde (`containers/`), relues par le registre des lecteurs.

Ce que ces tests tiennent (`WAMA_DATA_WORLD §7`, `§11.5`, `§11.8 ⑨`, `§11.1`) :
  • le Connector branche une base EXISTANTE ou un dossier de bases (récursif), sans copie, et
    refuse un fichier volant (qui relève de l'Importer) en le disant ;
  • rien n'est lu à la connexion : un consommateur ne lit QUE les flux qu'il demande ;
  • l'export d'un nœud de sortie applique des déclarations SÉRIALISÉES à N bases, n'écrase rien
    sans qu'on le demande, et refuse deux bases de même nom.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wama.common.catalog.data_types import DataType

from ...containers import Context, write as write_container
from ...core.temporal import Signal, SignalMeta, TemporalReferential
from .connector import connect, connectable
from .export import export_lots


def _base(path: Path, participant: str, offset: float = 0.0) -> Path:
    """Une base minimale : deux flux de même hauteur (une table de situations et ses
    indicateurs) et un flux d'échantillons, d'une autre hauteur."""
    ref = TemporalReferential(name=path.stem)

    def add(name, times, rows, data_type, **kw):
        ref.add(Signal(SignalMeta(name=name, data_type=data_type), times,
                       lambda i0, i1: rows[i0:i1], **kw))

    add('situations', [0.0, 10.0],
        [{'start': 0.0, 'end': 5.0, 'label': 'approche'},
         {'start': 10.0, 'end': 15.0, 'label': 'freinage'}],
        DataType.SEGMENTS, ends=[5.0, 15.0])
    add('indicateurs', [0.0, 10.0],
        [{'time': 0.0, 'speed_mean': 12.5 + offset}, {'time': 10.0, 'speed_mean': 8.0 + offset}],
        DataType.TIMESERIES)
    add('vitesse', [0.0, 0.1, 0.2],
        [{'time': 0.0, 'value': 1.0}, {'time': 0.1, 'value': 2.0}, {'time': 0.2, 'value': 3.0}],
        DataType.TIMESERIES)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_container(ref, path, contexte=Context(attributs={'participant': participant}))
    return path


DECLARATION = {'name': 'situations', 'identite': ['trip_id', 'participant'],
               'colonnes': [{'stream': 'situations', 'field': 'label'},
                            {'stream': 'indicateurs', 'field': 'speed_mean'}]}


class ConnectorTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='wama_connector_'))
        self.a = _base(self.root / 'P01' / 'essai_01.wdat', 'P01')
        self.b = _base(self.root / 'P02' / 'essai_02.wdat', 'P02', offset=1.0)

    def test_a_base_connects_without_reading_anything(self):
        lots = connect(self.a)
        self.assertEqual([lot.name for lot in lots], ['essai_01'])
        lot = lots[0]
        self.assertEqual(lot.format, 'wdat')
        self.assertEqual(sorted(lot.streams), ['indicateurs', 'situations', 'vitesse'])
        self.assertEqual(lot.meta['participant'], 'P01')
        self.assertEqual(lot.meta['trip_id'], 'essai_01',
                         "sans trip_id déclaré, le nom du fichier identifie le lot")

    def test_a_folder_connects_recursively_in_a_stable_order(self):
        self.assertEqual([lot.name for lot in connect(self.root)], ['essai_01', 'essai_02'])

    def test_the_data_home_is_the_connected_folder_not_the_first_file_s(self):
        """Règle d'export §11.1 : pour un dossier connecté, la destination par défaut est CE
        dossier — pas celui du premier fichier trouvé dedans (défaut vécu à l'écriture)."""
        self.assertEqual({lot.home for lot in connect(self.root)}, {self.root})
        self.assertEqual(connect(self.a)[0].home, self.a.parent)

    def test_a_loose_file_is_not_a_base(self):
        csv = self.root / 'volant.csv'
        csv.write_text('time;value\n0;1\n', encoding='utf-8')
        self.assertFalse(connectable(csv))
        with self.assertRaisesRegex(ValueError, 'Importer'):
            connect(csv)

    def test_a_folder_without_any_base_is_refused_and_says_so(self):
        vide = self.root / 'vide'
        vide.mkdir()
        with self.assertRaisesRegex(ValueError, 'aucune base connectable'):
            connect(vide)

    def test_a_consumer_reads_only_the_streams_it_asks_for(self):
        from ... import sources
        lot = connect(self.a)[0]
        with mock.patch.object(sources, 'load', wraps=sources.load) as load:
            frames = lot.frames(['situations'])
        self.assertEqual(list(frames), ['situations'])
        self.assertEqual(load.call_args.kwargs['streams'], ['situations'])
        self.assertEqual(list(frames['situations'].df['label']), ['approche', 'freinage'])

    def test_a_missing_stream_is_refused_by_name(self):
        with self.assertRaisesRegex(ValueError, 'inexistant'):
            connect(self.a)[0].frames(['inexistant'])


class ExportLotsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='wama_export_lots_'))
        self.lots = connect(_base(self.root / 'essai_01.wdat', 'P01')) \
            + connect(_base(self.root / 'sous' / 'essai_02.wdat', 'P02', offset=1.0))
        self.out = self.root / 'exports'

    def test_a_serialized_declaration_applies_to_every_base(self):
        written = export_lots([DECLARATION], self.lots, self.out)
        self.assertEqual(sorted(p.name for p in written),
                         ['situations_essai_01.csv', 'situations_essai_02.csv'])
        text = (self.out / 'situations_essai_02.csv').read_text(encoding='utf-8')
        self.assertEqual(text.splitlines()[0],
                         'trip_id;participant;situations.label;indicateurs.speed_mean')
        self.assertIn('essai_02;P02;freinage;9.0', text)

    def test_concatenating_bases_gives_one_file_identified_per_row(self):
        from .export import grouping_from_dict
        written = export_lots([DECLARATION], self.lots, self.out,
                              grouping=grouping_from_dict({'lots': True}))
        self.assertEqual([p.name for p in written], ['situations.csv'])
        rows = written[0].read_text(encoding='utf-8').splitlines()[1:]
        self.assertEqual([r.split(';')[0] for r in rows],
                         ['essai_01', 'essai_01', 'essai_02', 'essai_02'])

    def test_an_existing_file_is_not_replaced_unless_asked(self):
        export_lots([DECLARATION], self.lots, self.out)
        with self.assertRaises(FileExistsError):
            export_lots([DECLARATION], self.lots, self.out)
        self.assertEqual(len(export_lots([DECLARATION], self.lots, self.out, overwrite=True)), 2)

    def test_refusing_to_overwrite_writes_NOTHING(self):
        """Contre-épreuve : un seul fichier déjà présent arrête l'export AVANT toute écriture —
        sinon le dossier mêlerait l'export d'hier et celui d'aujourd'hui."""
        self.out.mkdir(parents=True)
        (self.out / 'situations_essai_02.csv').write_text('ancien', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            export_lots([DECLARATION], self.lots, self.out)
        self.assertFalse((self.out / 'situations_essai_01.csv').exists())
        self.assertEqual((self.out / 'situations_essai_02.csv').read_text(encoding='utf-8'), 'ancien')

    def test_two_bases_with_the_same_name_are_refused(self):
        twin = connect(_base(self.root / 'autre' / 'essai_01.wdat', 'P09'))
        with self.assertRaisesRegex(ValueError, 'même nom'):
            export_lots([DECLARATION], self.lots + twin, self.out)

    def test_an_invalid_declaration_is_refused_as_at_construction(self):
        with self.assertRaisesRegex(ValueError, 'aucune colonne'):
            export_lots([{'name': 'vide', 'colonnes': []}], self.lots, self.out)

    def test_tables_of_different_heights_are_refused(self):
        """Le cœur le refuse déjà (`rows`) ; le nœud de sortie ne l'avale pas."""
        decl = {'name': 'mix', 'colonnes': [{'stream': 'situations', 'field': 'label'},
                                            {'stream': 'vitesse', 'field': 'value'}]}
        with self.assertRaisesRegex(ValueError, 'hauteurs différentes'):
            export_lots([decl], self.lots, self.out)


if __name__ == '__main__':
    unittest.main()
