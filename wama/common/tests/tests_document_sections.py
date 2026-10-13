"""La mise en forme AJUSTÉE d'un document (`common/utils/document_sections.py`, 2026-10-13).

Décision de Fabien : la quantité de modifications du fond définit l'ajustement — un bout de phrase
changé réutilise la forme, une section très modifiée se remet en forme seule, une structure qui
change refait tout. Ce que ces tests tiennent :
  - le découpage du fond est LE MÊME côté serveur et dans la brique de surface (V8) ;
  - le plan dit « tout refaire » dès qu'il manque une base, des sections ou des repères ;
  - un bout de phrase se remplace dans la forme SANS appeler de modèle ; une section très modifiée
    est remise en forme seule, le reste du document intact ;
  - une réponse de modèle entourée de « ```html » est rendue sans sa clôture (constat de Fabien) ;
  - la base de comparaison vient des copies gardées, et disparaît quand la forme demandée change.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings

DRAFT = ('# Titre\n\nIntroduction du document.\n\n'
         '## Méthode\nLe signal est mesuré par une caméra ordinaire.\n\n'
         '## Résultats\nLa précision dépasse celle des méthodes classiques.\n')
HTML = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>.s{color:red}</style></head><body>'
        '<section class="s" data-wama-section="0"><h1>Titre</h1><p>Introduction du document.</p></section>'
        '<section class="s" data-wama-section="1"><h2>Méthode</h2>'
        '<p>Le signal est mesuré par une caméra ordinaire.</p></section>'
        '<section class="s" data-wama-section="2"><h2>Résultats</h2>'
        '<p>La précision dépasse celle des méthodes classiques.</p></section></body></html>')


def _never(messages):
    raise AssertionError('no model must be called for a phrase change')


class SplitIsTheBrickRuleTest(SimpleTestCase):

    CASES = ['# Title\n\nIntro.\n\n## Part\nBody\n', 'No heading at all.\nSecond line.', '',
             '# A\n```\n# not a heading, inside code\n```\n# B\n\n\n', 'Preamble\n# First\ntext',
             DRAFT]

    def test_the_server_cuts_like_the_surface_brick(self):
        from py_mini_racer import MiniRacer

        from wama.common.utils.document_sections import split_sections
        engine = MiniRacer()
        source = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
                  / 'surfaces' / 'brick-text-sections.js').read_text(encoding='utf-8')
        engine.eval('var window = {WamaSurface: {registerBrick: function (k, d) { window.__b = d; }}};'
                    + source)
        for text in self.CASES:
            with self.subTest(text=text):
                js = json.loads(engine.eval('JSON.stringify(window.__b.split(%s))' % json.dumps(text)))
                self.assertEqual(js, split_sections(text))
                self.assertEqual(text, ''.join(split_sections(text)))


class LayoutPlanTest(SimpleTestCase):

    def _plan(self, previous, text, html=HTML):
        from wama.common.utils.document_sections import plan_layout_update
        return plan_layout_update(previous, text, html)

    def test_without_a_base_or_with_a_new_structure_everything_is_redone(self):
        self.assertEqual('full', self._plan('', DRAFT).mode)
        self.assertEqual('full', self._plan(DRAFT, DRAFT + '\n## Conclusion\nFin.\n').mode)
        self.assertEqual('full', self._plan(DRAFT, DRAFT, html=HTML.replace(' data-wama-section="2"', '')).mode,
                         'a render without all its anchors cannot be adjusted')

    def test_the_amount_of_change_decides_per_section(self):
        self.assertEqual('none', self._plan(DRAFT, DRAFT).mode)
        small = DRAFT.replace('caméra ordinaire', 'caméra standard')
        plan = self._plan(DRAFT, small)
        self.assertEqual(('adjust', {'keep': 2, 'patch': 1, 'relayout': 0}), (plan.mode, plan.counts()))
        rewritten = DRAFT.replace('La précision dépasse celle des méthodes classiques.',
                                  'Trois jeux de données publics confirment un gain net et stable.')
        plan = self._plan(DRAFT, rewritten)
        self.assertEqual({'keep': 2, 'patch': 0, 'relayout': 1}, plan.counts())


class ApplyPlanTest(SimpleTestCase):

    def _adjust(self, text, ask=_never):
        from wama.common.utils.document_sections import apply_plan, plan_layout_update
        return apply_plan(HTML, plan_layout_update(DRAFT, text, HTML), ask)

    def test_a_phrase_change_reuses_the_form_without_a_model(self):
        html = self._adjust(DRAFT.replace('caméra ordinaire', 'caméra standard'))
        self.assertIn('Le signal est mesuré par une caméra standard.', html)
        self.assertIn('<style>.s{color:red}</style>', html, 'the form is kept')
        self.assertEqual(3, html.count('data-wama-section='))

    def test_a_rewritten_section_is_laid_out_alone(self):
        asked = []

        def ask(messages):
            asked.append(messages)
            return ('```html\n<section class="s" data-wama-section="2"><h2>Résultats</h2>'
                    '<p>Trois jeux confirment un gain net.</p></section>\n```')
        text = DRAFT.replace('La précision dépasse celle des méthodes classiques.',
                             'Trois jeux confirment un gain net et stable, sur toutes les mesures.')
        html = self._adjust(text, ask)
        self.assertEqual(1, len(asked), 'one call, for the rewritten section only')
        self.assertIn('data-wama-section="2"', asked[0][0]['content'])
        self.assertIn('Trois jeux confirment un gain net.', html)
        self.assertIn('caméra ordinaire', html, 'the other sections are untouched')
        self.assertNotIn('```', html)

    def test_a_reply_without_a_section_gives_up_the_adjustment(self):
        text = DRAFT.replace('La précision dépasse celle des méthodes classiques.',
                             'Trois jeux confirment un gain net et stable, sur toutes les mesures.')
        self.assertIsNone(self._adjust(text, lambda m: 'Désolé, je ne peux pas.<p>a</p><p>b</p>'))

    def test_an_added_line_is_a_relayout_not_a_patch(self):
        from wama.common.utils.document_sections import patch_section, _soup
        tag = _soup(HTML).find(attrs={'data-wama-section': '1'})
        old = '## Méthode\nLe signal est mesuré par une caméra ordinaire.\n'
        self.assertFalse(patch_section(tag, old, old + 'Une ligne de plus.\n'))


class DocumentReplyTest(SimpleTestCase):

    def test_the_code_fence_and_the_reasoning_are_removed(self):
        from wama.common.utils.document_sections import extract_document
        self.assertEqual('<html></html>', extract_document('<think>hmm</think>\n```html\n<html></html>\n```'))
        self.assertEqual('<html></html>', extract_document('Voici le document :\n```html\n<html></html>\n```'))
        self.assertEqual('<p>a</p>', extract_document('<p>a</p>'))

    def test_a_document_always_declares_its_charset(self):
        from wama.common.utils.document_sections import with_charset
        self.assertIn('<head><meta charset="utf-8">', with_charset('<html><head></head></html>'))
        self.assertIn('<meta charset="utf-8">', with_charset('<p>é</p>'))
        kept = '<html><head><meta charset="UTF-8"></head></html>'
        self.assertEqual(kept, with_charset(kept))

    def test_a_full_layout_asks_one_anchor_per_section_and_says_when_they_miss(self):
        from wama.common.utils.document_sections import finish_document, full_layout_instruction
        self.assertIn('de 0 à 2', full_layout_instruction(DRAFT))
        said = []
        finish_document('```html\n' + HTML.replace(' data-wama-section="1"', '') + '\n```', DRAFT,
                        console=lambda msg, level=None: said.append(msg))
        self.assertTrue(said and '2 section(s) sur 3' in said[0])


class AdjustmentBasisTest(TestCase):
    """The base comes from the KEPT revision files — the ▶ of a process removes its output before
    launching — and only while the requested form has not moved."""

    def setUp(self):
        from wama.common.tests.tests_kept_revision_outputs import _keeping_models
        self.models = _keeping_models()
        if not self.models:
            self.skipTest('aucun modèle installé ne porte la liste des fichiers gardés')
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('layout_basis_owner', password='x')
        from wama.common.services import revisions
        saved = dict(revisions._KEEPING)
        self.addCleanup(lambda: (revisions._KEEPING.clear(), revisions._KEEPING.update(saved)))

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as out:
            out.write(text)

    def test_the_last_render_and_its_fond_come_from_the_kept_copies(self):
        from wama.common.services.revisions import keep_outputs, record_revision
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.document_sections import adjustment_basis
        from wama.common.utils.media_paths import app_media_dir
        for model in self.models:
            app = model._meta.app_label
            keep_outputs(app, keep=20)
            source, output = [f.name for f in model._meta.concrete_fields
                              if isinstance(f, models.FileField)][:2]
            item = _instance(model, self.user)
            home = app_media_dir(app, self.user.id, 'output')
            self._write(f'{home}/basis.md', DRAFT)
            self._write(f'{home}/basis.html', HTML)
            setattr(item, source, f'{home}/basis.md')
            setattr(item, output, f'{home}/basis.html')
            item.save()
            record_revision(app, item, output_fields=[source, output])
            self._write(f'{home}/basis.md', DRAFT.replace('ordinaire', 'standard'))
            record_revision(app, item, output_fields=[source])       # a hand correction
            os.remove(os.path.join(self.root, home, 'basis.html'))   # the ▶ removed the render
            item.refresh_from_db()
            same = {'style': 'sobre', '@upstream': {'write': 'a'}}
            ctx = SimpleNamespace(previous_snapshot=same, snapshot={**same, '@upstream': {'write': 'b'}})
            basis = adjustment_basis(app, item, ctx, source_field=source, output_field=output)
            self.assertEqual((DRAFT, HTML), (basis.previous_text, basis.previous_html),
                             'the fond the last render was made from, not the corrected one')
            ctx.snapshot = {'style': 'coloré', '@upstream': {'write': 'b'}}
            self.assertIsNone(adjustment_basis(app, item, ctx, source_field=source, output_field=output),
                              'the requested form changed : everything is redone')
            ctx.previous_snapshot = None
            self.assertIsNone(adjustment_basis(app, item, ctx, source_field=source, output_field=output))


class TheCodegenRoleSeesTheBricksForTheReplayedProcessTest(SimpleTestCase):
    """The adjustment bricks are SHOWN to the `codegen` role for the process a surface replays
    after a hand correction (`surfaces[].reruns`) — and to it only : a triggered brick that a glue
    does not call is a warning of the role's checks, which would fire on every other process."""

    def test_only_the_replayed_process_gets_them_and_they_resolve(self):
        from wama.common.tests.tests_dev_ai_bridge import _charger
        codegen = _charger('run_codegen')
        man = {'body': {'surfaces': [{'key': 'edit', 'reruns': 'layout'}]}}
        layout = [names for _key, names in codegen._triggered([], man, 'layout')]
        write = [names for _key, names in codegen._triggered([], man, 'write')]
        self.assertTrue(any('plan_layout_update' in names for names in layout))
        self.assertFalse(any('plan_layout_update' in names for names in write))
        signatures = codegen.signatures_briques()
        self.assertIn('apply_plan', signatures, 'the registry points at the module that defines them')
        self.assertIn('ask', signatures['apply_plan'])
