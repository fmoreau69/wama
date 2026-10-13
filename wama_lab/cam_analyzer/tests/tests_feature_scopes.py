"""Le scope d'une bascule ⚑ se MESURE à qui la lit (2026-10-13).

Le panneau « Comparer » range les bascules par scope, du plus direct au plus coûteux, et le
tracking ne se dit périmé que pour les bascules qu'il a retenues (`compute_snapshot`). Un scope
faux trompe donc deux fois. Constat du jour : trois bascules rangées « affichage immédiat »
(correction FOV, bras de levier, filtre reflets) étaient lues par le tracking — les changer ne le
périmait pas ; et sept bascules « à relancer » déplaçaient la navette au clic.

Règle tenue ici :
- `live` : lue par la page, jamais par un calcul ;
- `hybrid` : lue par la page ET par un calcul ;
- `compute` : lue par un calcul, pas par le rendu de la page (exceptions déclarées).
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.features import FEATURES

APP = Path(__file__).resolve().parents[1]
PAGE_JS = APP / 'static' / 'cam_analyzer' / 'js' / 'index.js'

# La page lit ces bascules de calcul sans rien dessiner avec.
PAGE_READS_WITHOUT_RENDERING = {
    'depth_estimation': 'choisit seulement si la passe GPU « Profondeur » part avec son étage',
}


def _server_sources():
    for path in APP.rglob('*.py'):
        rel = path.relative_to(APP).as_posix()
        if rel.startswith(('tests/', 'migrations/')) or path.name.startswith('tests') \
                or rel == 'utils/features.py':
            continue
        yield path.read_text(encoding='utf-8')


SERVER = '\n'.join(_server_sources())
PAGE = PAGE_JS.read_text(encoding='utf-8')
# `feature: 'map_buildings'` : les couches de zone lisent `camFeat[feature]`
ZONE_LAYER_KEYS = set(re.findall(r"makeZoneLayer\(\s*'(\w+)'", PAGE))


# ── Qui LIT une bascule, passe par passe (2026-10-13) ────────────────────────────────────────
#: aucune passe ne la lit (déclarée pour un chantier, pas implémentée)
READ_BY_NO_PASS = {'track_speed_unified'}
#: le graphe la voit lue par la passe, et ce n'est pas vrai — ou pas voulu
MEASURED_NOT_DECLARED = {
    ('lane_map_recalage', 'lane_map_recalage'): 'effective_gps_track(lane_map=False) : sa propre correction',
    ('ortho_correction', 'ortho_recalage'): "effective_gps_track(ortho=False) : la mesure ne lit pas sa correction",
    ('ortho_correction', 'ortho_correction'): 'idem, `ortho=False`',
    ('gps_latency', 'yolo_detect'): "l'analyse recalcule les FENÊTRES (passe « Fenêtres », déclarée)",
    ('gps_latency', 'yolopv2_lanes'): 'idem',
    ('sam3_homography', 'yolo_detect'): "distances géométriques de l'analyse (geometry_enabled) : "
                                        'ne pas relancer des heures de GPU pour une bascule (dit dans sa description)',
    ('sam3_homography', 'yolopv2_lanes'): 'idem',
}
#: la passe la lit, et le graphe ne peut pas le voir
DECLARED_NOT_MEASURED = {
    ('gps_latency', 'intersection_windows'): 'passe synchrone, sans tâche Celery où partir',
}
# Le corps du tracking : les Indicateurs et la fin d'analyse l'ENCHAÎNENT, ils ne le lisent pas.
TRACKING_BODY = {'global_tracking': {'compute_global_tracking_task', '_run_global_tracking'}}
SWITCH_READERS = {'enabled', '_feat_on', 'is_enabled', '_is_enabled'}


def measured_readers():
    """{bascule: {passes dont la tâche atteint une lecture de la bascule}} — graphe d'appels PAR
    NOM sur les modules du cam_analyzer (surestime plutôt qu'il ne rate : un homonyme ajoute)."""
    import ast
    from collections import defaultdict
    from wama_lab.cam_analyzer.utils.pass_tracking import PASSES
    keys = {f.key for f in FEATURES if f.scope != 'live'}
    defs = defaultdict(list)
    for path in APP.rglob('*.py'):
        rel = path.relative_to(APP).as_posix()
        if rel.startswith(('tests/', 'migrations/', 'archive/')) or path.name.startswith('tests') \
                or rel == 'utils/features.py':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs[node.name].append(node)

    def called(node):
        return {n for c in ast.walk(node) if isinstance(c, ast.Call)
                for n in [getattr(c.func, 'id', None) or getattr(c.func, 'attr', None)] if n in defs}

    def reads(node):
        out = set()
        for c in ast.walk(node):
            if not isinstance(c, ast.Call):
                continue
            name = getattr(c.func, 'id', None) or getattr(c.func, 'attr', None)
            consts = [a.value for a in c.args if isinstance(a, ast.Constant) and a.value in keys]
            if name == 'get' and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value in keys:
                out.add(c.args[0].value)
            elif name in SWITCH_READERS:
                out.update(consts)
        return out

    graph = {n: set().union(*(called(d) for d in ds)) for n, ds in defs.items()}
    direct = {n: set().union(*(reads(d) for d in ds)) for n, ds in defs.items()}
    tasks = {p.key: p.task or ('process_session_task' if p.key in DETECTION_CHAIN else '')
             for p in PASSES}
    entries = {t for t in tasks.values() if t} | {'_run_global_tracking'}
    out = defaultdict(set)
    for key, task in tasks.items():
        if not task:
            continue
        own = TRACKING_BODY.get(key, set()) | {task}
        seen, todo = set(), [task]
        while todo:
            n = todo.pop()
            if n in seen or (n in entries and n not in own):
                continue
            seen.add(n)
            todo.extend(graph.get(n, ()))
            for k in direct.get(n, ()):
                out[k].add(key)
    return out


#: passes portées par `process_session_task` (détection et ses suites internes)
DETECTION_CHAIN = ('yolo_detect', 'yolopv2_lanes', 'lane_events', 'distance')


def read_by_server(key):
    return re.search(r"""['"]%s['"]""" % key, SERVER) is not None


def read_by_page(key):
    return (re.search(r"camFeat(\.%s\b|\[\s*'%s'\s*\])" % (key, key), PAGE) is not None
            or key in ZONE_LAYER_KEYS)


class FeatureScopeMatchesItsReadersTest(SimpleTestCase):
    def test_a_display_switch_is_never_read_by_a_computation(self):
        wrong = [f.key for f in FEATURES if f.scope == 'live' and read_by_server(f.key)]
        self.assertEqual(wrong, [], 'lue par un calcul : scope « hybrid »')

    def test_a_hybrid_switch_is_read_by_the_page_and_by_a_computation(self):
        for f in FEATURES:
            if f.scope != 'hybrid':
                continue
            self.assertTrue(read_by_page(f.key), f'{f.key} : la page ne la lit pas → « compute »')
            self.assertTrue(read_by_server(f.key), f'{f.key} : aucun calcul ne la lit → « live »')

    def test_a_compute_switch_changes_nothing_on_the_page_before_the_recompute(self):
        wrong = [f.key for f in FEATURES if f.scope == 'compute' and read_by_page(f.key)
                 and f.key not in PAGE_READS_WITHOUT_RENDERING]
        self.assertEqual(wrong, [], 'la page la lit : scope « hybrid »')

    def test_declared_exceptions_are_still_needed(self):
        for key in PAGE_READS_WITHOUT_RENDERING:
            self.assertTrue(read_by_page(key), f'{key} : exception devenue inutile, la retirer')

    def test_every_computing_switch_names_the_passes_that_read_it(self):
        from wama_lab.cam_analyzer.utils.pass_tracking import ORDER
        for f in FEATURES:
            if f.scope == 'live':
                self.assertEqual(f.processes, (), f.key)
                continue
            self.assertTrue(set(f.processes) <= set(ORDER), f'{f.key} : passe inconnue')
            if f.key not in READ_BY_NO_PASS:
                self.assertTrue(f.processes, f'{f.key} : aucune passe déclarée')

    def test_the_declared_passes_are_the_measured_readers(self):
        """`processes` = les passes dont la tâche ATTEINT une lecture de la bascule (graphe d'appels
        par nom, lectures `enabled(…)` / `<état>.get(…)`), aux écarts déclarés près."""
        measured = measured_readers()
        for f in FEATURES:
            if f.scope == 'live':
                continue
            got = {p for p in measured.get(f.key, set())
                   if (f.key, p) not in MEASURED_NOT_DECLARED}
            want = {p for p in f.processes if (f.key, p) not in DECLARED_NOT_MEASURED}
            self.assertEqual(want, got, f'{f.key} : déclarées {sorted(want)}, mesurées {sorted(got)}')

    def test_declared_gaps_are_still_needed(self):
        measured = measured_readers()
        for key, p in MEASURED_NOT_DECLARED:
            self.assertIn(p, measured.get(key, set()), f'{key} / {p} : écart devenu inutile')
        for key, p in DECLARED_NOT_MEASURED:
            self.assertNotIn(p, measured.get(key, set()), f'{key} / {p} : écart devenu inutile')

    def test_the_page_renders_the_groups_from_the_most_direct_to_the_most_costly(self):
        from wama.common.utils.feature_flags import SCOPES
        self.assertEqual(SCOPES, ('live', 'hybrid', 'compute'))
        order = [PAGE.index("scope: '%s'" % s) for s in SCOPES]
        self.assertEqual(order, sorted(order))
