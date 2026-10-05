"""The ⚙ modal and the right panel offer the SAME settings — for EVERY app, from its schema.

Written on 2026-09-26 after Fabien found the transcriber's speech filter in the modal only: the
two surfaces are generated from one schema, but a param can be declared on one of them only
(`contexts`), and nothing said so. This test reads every app's schema (`APP_CATALOG` →
`declared_param_schemas`) and lists the settings present on one surface and not the other.

The gaps measured on that day are listed below with what is known about them. The list can only
SHRINK: a new gap fails (declare the setting on both surfaces), and a gap that has disappeared
fails too until it is removed here — a list with slack is a permission to add some.
"""
from django.test import SimpleTestCase

#: (app, schema attribute, param) → what is known. Measured 2026-09-26; none decided yet.
DECLARED_GAPS = {
    ('avatarizer', 'PARAMS_JSON', 'text_content'): 'modal only — not yet looked at',
    ('avatarizer', 'PARAMS_JSON', 'tts_model'): 'modal only — not yet looked at',
    ('avatarizer', 'PARAMS_JSON', 'quality_intent'): 'modal only — not yet looked at',
    ('avatarizer', 'PARAMS_JSON', 'language'): 'modal only — not yet looked at',
    ('avatarizer', 'PARAMS_JSON', 'voice_preset'): 'modal only — not yet looked at',
    ('composer', 'PARAMS_JSON', 'prompt'): 'modal only — not yet looked at',
    ('enhancer', 'AUDIO_PARAMS_JSON', 'output_format'): 'modal only — not yet looked at',
    ('enhancer', 'AUDIO_PARAMS_JSON', 'output_quality'): 'modal only — not yet looked at',
    ('reader', 'PARAMS_JSON', 'quality_intent'): 'panel only — not yet looked at',
}


def measured_gaps():
    """{(app, attr, param)} of the settings on ONE surface only — item (modal) vs panel."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.utils.param_schema import declared_param_schemas
    gaps = set()
    for app_id, spec in APP_CATALOG.items():
        if (spec or {}).get('sandbox'):
            continue          # generated twin: compared to its source, never measured on its own
        declared = declared_param_schemas(app_id)
        if not declared:
            continue
        for attr, schema in declared['schemas'].items():
            for p in schema:
                if p.get('type') == 'hidden':
                    continue  # carriers (media_type…), never shown
                contexts = set(p.get('contexts') or ())
                if ('item' in contexts) != ('panel' in contexts):
                    gaps.add((app_id, attr, p['name']))
    return gaps


class SettingsSurfacesTest(SimpleTestCase):

    def test_no_new_setting_lives_on_one_surface_only(self):
        new = sorted(measured_gaps() - set(DECLARED_GAPS))
        self.assertEqual([], new, "réglage présent dans la modale ⚙ OU dans le volet, pas les "
                                  "deux : le déclarer sur les deux surfaces (params.py)")

    def test_the_declared_gaps_are_still_real(self):
        """A gap that no longer exists leaves slack in the list — remove it."""
        stale = sorted(set(DECLARED_GAPS) - measured_gaps())
        self.assertEqual([], stale, "écart résorbé : le retirer de DECLARED_GAPS")

    def test_the_measure_does_see_a_gap(self):
        """Counter-check on a made-up schema: the instrument is not blind."""
        from unittest import mock
        schema = [{'name': 'a', 'contexts': ('item', 'panel')},
                  {'name': 'b', 'contexts': ('item', 'batch')}]
        with mock.patch('wama.common.app_registry.APP_CATALOG', {'fake': {}}), \
                mock.patch('wama.common.utils.param_schema.declared_param_schemas',
                           return_value={'primary': 'P', 'schemas': {'P': schema}}):
            self.assertEqual({('fake', 'P', 'b')}, measured_gaps())


def _panel_inputs(app_id):
    """{id: {min, max, step}} des curseurs et nombres ÉCRITS dans les gabarits de l'app."""
    import re
    from pathlib import Path
    from django.conf import settings
    found = {}
    for path in (Path(settings.BASE_DIR) / 'wama' / app_id / 'templates').rglob('*.html'):
        for tag in re.findall(r'<input\b[^>]*>', path.read_text(encoding='utf-8', errors='ignore'), re.S):
            if not re.search(r'type="(range|number)"', tag):
                continue
            ident = re.search(r'\bid="([^"{]+)"', tag)
            if ident:
                found[ident.group(1)] = {k: (re.search(r'\b%s="([^"{]+)"' % k, tag) or [None, None])[1]
                                         for k in ('min', 'max', 'step')}
    return found


def bound_mismatches():
    """[(app, param, borne, gabarit, schéma)] : un curseur du VOLET écrit en gabarit dont les
    bornes diffèrent de celles du schéma — celles que lit la modale ⚙."""
    from wama.common.app_registry import APP_CATALOG
    from wama.common.utils.param_schema import declared_param_schemas
    out = []
    for app_id, spec in APP_CATALOG.items():
        if (spec or {}).get('sandbox'):
            continue
        declared = declared_param_schemas(app_id)
        if not declared:
            continue
        written = _panel_inputs(app_id)
        for schema in declared['schemas'].values():
            for p in schema:
                if p.get('type') not in ('range', 'number'):
                    continue
                dom = p.get('dom_id')
                key = (dom.get('panel') if isinstance(dom, dict) else dom) or p['name']
                for bound, value in (written.get(key) or {}).items():
                    if value is not None and p.get(bound) is not None \
                            and float(value) != float(p[bound]):
                        out.append((app_id, p['name'], bound, value, p[bound]))
    return out


class PanelBoundsFollowTheSchemaTest(SimpleTestCase):
    """2026-10-06 (Fabien : « l'idée était de pouvoir la réduire ou l'augmenter ») : le volet de
    l'anonymizer, écrit en gabarit, bornait l'agrandissement à 0,5–1,5 pendant que sa modale ⚙,
    rendue du schéma, le bornait à 1,0–2,0 ; idem le flou progressif (3–31 / 0–100) et le
    `bbox_shift` de l'avatarizer (−10–10 / −9–9). Le gabarit ne peut pas s'en passer (un curseur
    sans bornes arrondit 1,05 à 1 avant tout script) : il doit porter CELLES DU SCHÉMA."""

    def test_a_panel_written_in_a_template_carries_the_bounds_of_the_schema(self):
        self.assertEqual([], bound_mismatches(),
                         "bornes du volet ≠ schéma (params.py fait foi) : (app, réglage, borne, "
                         "gabarit, schéma)")

    def test_the_measure_does_see_a_mismatch(self):
        from unittest import mock
        schema = [{'name': 'zone', 'type': 'range', 'min': 0.75, 'max': 1.25, 'step': 0.05,
                   'dom_id': {'panel': 'user_setting_zone'}}]
        with mock.patch('wama.common.app_registry.APP_CATALOG', {'fake': {}}), \
                mock.patch('wama.common.utils.param_schema.declared_param_schemas',
                           return_value={'primary': 'P', 'schemas': {'P': schema}}), \
                mock.patch(f'{__name__}._panel_inputs',
                           return_value={'user_setting_zone': {'min': '0.5', 'max': '1.25', 'step': None}}):
            self.assertEqual([('fake', 'zone', 'min', '0.5', 0.75)], bound_mismatches())
