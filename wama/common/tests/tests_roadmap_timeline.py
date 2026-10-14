"""`roadmap_timeline.parse` — the milestone timeline read from ROADMAP.md (2026-10-13).

The timeline is DERIVED: the presentation shows what the ROADMAP table says. A table that breaks
must say so, never vanish silently along with its slide.
"""
from django.test import SimpleTestCase

from wama.common.roadmap_timeline import parse

TABLE = """# Roadmap

## Frise — les grands jalons

> Une ligne par jalon.

| Quand | État | Jalon | Détail |
|---|---|---|---|
| 2025-06 | ✅ | Premières apps | Transcriber, Anonymizer. |
| prochain | ⏳ | Writer sort du bac à sable | |

## Horizons
| a | b |
|---|---|
| x | y |
"""


class RoadmapTimelineTests(SimpleTestCase):

    def test_rows_are_read_in_table_order_with_their_state(self):
        items = parse(TABLE)
        self.assertEqual(['Premières apps', 'Writer sort du bac à sable'], [i['label'] for i in items])
        self.assertEqual(('✅', 'ok'), (items[0]['state'], items[0]['css']))
        self.assertEqual(('prochain', 'todo', ''), (items[1]['when'], items[1]['css'], items[1]['detail']))

    def test_a_table_outside_the_timeline_section_is_ignored(self):
        self.assertNotIn('x', [i['label'] for i in parse(TABLE)])

    def test_a_missing_section_is_an_error_not_an_empty_timeline(self):
        with self.assertRaises(ValueError):
            parse("# Roadmap\n\n## Horizons\n")

    def test_an_unknown_state_is_an_error(self):
        with self.assertRaises(ValueError):
            parse(TABLE.replace('| ✅ |', '| fait |'))

    def test_a_section_without_rows_is_an_error(self):
        with self.assertRaises(ValueError):
            parse("## Frise\n\n| Quand | État | Jalon |\n|---|---|---|\n")
