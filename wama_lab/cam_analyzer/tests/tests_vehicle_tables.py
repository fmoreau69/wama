"""Tableaux par véhicule (2026-10-29) : la passe, ses exports, et le cap des garés par leur rangée."""
import inspect
import json
from unittest import mock

from django import test as django_test
from django.http import Http404
from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import multicam_tracker as mt
from wama_lab.cam_analyzer.utils import pass_tracking as pt
from wama_lab.cam_analyzer.utils.features import FEATURES

TABLES = {
    'insertions': [{'intersection': 'X', 'window_idx': 0, 'id': '452', 'class_name': 'car', 'inserted': True,
                    'before_shuttle': True, 'after_shuttle': False, 'shuttle_lane': True, 'opposite_lane': False,
                    't0_s': 512.58, 't1_s': 515.75, 't2_s': 517.25, 'dmin_m': 4.39, 'rear_present': None}],
    'overtakes': [{'id': '59', 'class_name': 'car', 'direction': 'vehicle_overtakes_shuttle', 'side': 'left',
                   't_alongside_s': 189.84, 'cut_in': True, 'cut_in_gap_m': 14.74}],
}


class VehicleTablesPassTest(SimpleTestCase):

    def test_the_pass_follows_the_indicators_and_the_windows(self):
        self.assertEqual(sorted(pt._DEPENDS_ON['vehicle_tables']), ['indicators', 'intersection_windows'])
        self.assertEqual(pt._BY_KEY['vehicle_tables'].stage, 'calcul')
        self.assertFalse(pt._BY_KEY['vehicle_tables'].gpu)

    def test_the_task_runs_on_the_cpu_queue(self):
        from django.conf import settings
        route = settings.CELERY_TASK_ROUTES['wama_lab.cam_analyzer.tasks.compute_vehicle_tables_task']
        self.assertEqual(route['queue'], 'default')


class TimeBaseTest(SimpleTestCase):
    """Les instants sortent en temps VIDÉO, les durées en secondes physiques : chaque champ en `_s` que le
    calcul pur produit est déclaré l'un ou l'autre — un instant non déclaré sortirait décalé sans erreur."""

    def test_every_seconds_field_is_an_instant_or_a_duration(self):
        from wama_data.functions.driving import tests_vehicle_interactions as scene
        from wama_data.functions.driving.vehicle_interactions import insertion_rows, overtaking_rows
        from wama_lab.cam_analyzer.utils.vehicle_tables import DURATION_FIELDS, INSTANT_FIELDS
        rows = insertion_rows(scene.WINDOW, scene.track(), {'7': scene.side_vehicle()}, lane_w=3.5)
        car = [(k * 0.1, -3.5 if k < 90 else 0.0, -80.0 + k, 0.0, 10.0, 'car', None, None) for k in range(141)]
        rows += overtaking_rows(scene.track(with_path=False), {'4': car}, lane_w=3.5)
        self.assertEqual(len(rows), 2)
        seconds = {k for row in rows for k in row if k.endswith('_s')}
        self.assertEqual(set(INSTANT_FIELDS) & set(DURATION_FIELDS), set())
        self.assertEqual(seconds - set(INSTANT_FIELDS) - set(DURATION_FIELDS), set())


class VehicleTableExportsTest(django_test.TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from wama_lab.cam_analyzer.models import AnalysisSession
        self.user = get_user_model().objects.create_user('vehicle-tables-test', password='x')
        self.session = AnalysisSession.objects.create(user=self.user, name='s')

    def _get(self, view):
        from django.test import RequestFactory
        from wama_lab.cam_analyzer import views
        request = RequestFactory().get('/')
        request.user = self.user
        return getattr(views, view)(request, self.session.id)

    def test_before_the_pass_the_exports_say_it_and_the_report_hides_them(self):
        with mock.patch('wama_lab.cam_analyzer.utils.vehicle_tables.read_tables', return_value=None):
            with self.assertRaises(Http404):
                self._get('export_insertions_csv')
            self.assertEqual(json.loads(self._get('get_vehicle_tables').content), {'available': False})

    def test_one_line_per_vehicle_with_its_g_number_and_yes_no(self):
        with mock.patch('wama_lab.cam_analyzer.utils.vehicle_tables.read_tables', return_value=TABLES):
            body = b''.join(self._get('export_insertions_csv').streaming_content).decode('utf-8')
            lines = body.strip().splitlines()
            self.assertEqual(len(lines), 2)
            # le séparateur de l'Exporter du monde Data (`core/export.py`, format « csv »)
            header, row = lines[0].split(';'), lines[1].split(';')
            cell = dict(zip(header, row))
            self.assertEqual(cell['vehicule_G'], 'G452')
            self.assertEqual(cell['insertion_avant_passage_navette'], 'oui')
            self.assertEqual(cell['insertion_voie_opposee'], 'non')
            self.assertEqual(cell['vehicule_arriere_navette'], '', 'une absence reste vide')
            body = b''.join(self._get('export_overtakes_csv').streaming_content).decode('utf-8')
            cell = dict(zip(*[line.split(';') for line in body.strip().splitlines()]))
            self.assertEqual((cell['vehicule_G'], cell['cote'], cell['rabattement']), ('G59', 'left', 'oui'))


class HeadingRowSpacingTest(SimpleTestCase):

    def test_declared_off_measured_always_applied_under_the_switch(self):
        f = {x.key: x for x in FEATURES}['heading_row_spacing']
        self.assertFalse(f.default)
        self.assertEqual(f.scope, 'compute')
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertIn('parked_row_kinds = row_heading_counts(_rows)', src)
        self.assertIn("if _feat.get('heading_row_spacing', False):", src)
        # après le lissage par voisinage, avant la mesure des garés en double
        self.assertLess(src.index("if _feat.get('heading_cluster', True):"), src.index('row_headings('))
        self.assertLess(src.index('row_headings('), src.index('parked_twin_kinds = '))
        self.assertIn("'parked_row_kinds': parked_row_kinds", src)

    def test_the_task_reports_the_row_kinds(self):
        from wama_lab.cam_analyzer import tasks
        self.assertIn("rs['parked_row_kinds']", inspect.getsource(tasks._run_global_tracking))
