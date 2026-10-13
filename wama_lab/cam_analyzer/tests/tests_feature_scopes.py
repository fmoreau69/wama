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

    def test_the_page_renders_the_groups_from_the_most_direct_to_the_most_costly(self):
        from wama.common.utils.feature_flags import SCOPES
        self.assertEqual(SCOPES, ('live', 'hybrid', 'compute'))
        order = [PAGE.index("scope: '%s'" % s) for s in SCOPES]
        self.assertEqual(order, sorted(order))
