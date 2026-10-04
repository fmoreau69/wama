"""The progress bar of a card is ALWAYS rendered; the common CSS hides it while the card waits.

Fabien, 2026-10-04 (composer): « le process est en cours mais la barre de progression ne s'affiche
pas, alors que les cards déjà traitées l'affichent ». The card templates rendered the bar only
outside PENDING: a card created, then started by ▶, had NO bar to fill until the page was
reloaded — in 10 apps and in the generator. Nothing at run time says so: the progress is polled,
the card just stays without a bar. Hence a generic guard on every card template.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
BAR = re.compile(r'class="wcv3-bar[" ]')
TAG = re.compile(r'\{\{?%\s*(if|endif)\b([^%]*)%\}?\}')


def _open_conditions_at_the_bar(text):
    """The `{% if %}` still open where the bar is written (generator: `{{% if %}}`)."""
    bar = BAR.search(text)
    if bar is None:
        return None
    stack = []
    for tag in TAG.finditer(text[:bar.start()]):
        if tag.group(1) == 'if':
            stack.append(tag.group(2).strip())
        elif stack:
            stack.pop()
    return stack


def _card_templates():
    """The card templates of the REAL apps, plus the generator. The sandbox twins (`*_01`) are
    left out: their templates are a copy of the generator's output, regenerated and never edited
    (`common/sandbox.py`) — the generator itself is checked here."""
    from wama.common.sandbox import sandbox_labels
    twins = set(sandbox_labels())
    found = [p for p in (ROOT / 'wama').glob('*/templates/*/_*card*.html')
             if p.parts[-4] not in twins and BAR.search(p.read_text(encoding='utf-8'))]
    return found + [ROOT / 'wama/common/manifests/codegen/templates_gen.py']


class TheBarIsAlwaysRenderedTest(SimpleTestCase):

    def test_every_card_template_has_the_bar_outside_any_status_condition(self):
        templates = _card_templates()
        self.assertGreaterEqual(len(templates), 10, 'the card templates were not found')
        for path in templates:
            with self.subTest(template=str(path.relative_to(ROOT))):
                opened = _open_conditions_at_the_bar(path.read_text(encoding='utf-8'))
                self.assertIsNotNone(opened, 'no progress bar found')
                self.assertEqual([], [c for c in opened if 'status' in c],
                                 'the bar is rendered only under a status condition: a card '
                                 'started by ▶ would have no bar to fill')

    def test_the_common_css_hides_it_while_the_card_waits(self):
        for css in ('wama/common/static/common/css/app_modern.css',
                    'staticfiles/common/css/app_modern.css'):
            with self.subTest(css=css):
                text = (ROOT / css).read_text(encoding='utf-8')
                self.assertRegex(text, r'\.wama-card\[data-status="PENDING"\]\s+\.wcv3-bar\s*\{'
                                       r'\s*display:\s*none')
