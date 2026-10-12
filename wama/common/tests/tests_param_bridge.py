"""Le PONT `ParamSpec → Param` et la PORTE d'un réglage reçu — ROUTE §10.6 point 3.3bis, marche R1.

Une fonction DÉCLARE ses réglages en `ParamSpec` ; toute surface les REND en `Param` (modale ⚙
d'une card, volet, inspecteur du Studio) et toute exécution les fait passer par la même porte
(`checked_values`). Ces tests tiennent les trois promesses de la route :
  • la déclaration est BIEN FORMÉE (mesuré le 2026-10-12 : 20 déclarations sur 131 glissaient
    l'unité dans `choices` et la description dans `unit`, faute d'arguments nommés) ;
  • la projection ne PERD rien de ce que la déclaration dit, et n'invente rien ;
  • la porte TYPE, BORNE et REFUSE en nommant — l'ancienne coercition du Studio ne connaissait
    que les types.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
from django.test import SimpleTestCase

from wama.common.catalog import function_catalog as fc
from wama.common.catalog.function_catalog import PARAM_TYPES, FunctionSpec, ParamSpec
from wama.common.utils.param_schema import (SPEC_TYPE_TO_PARAM_TYPE, checked_values,
                                            param_from_spec, schema_refusals)


def _catalog_params():
    fc.load_all()
    return [(spec.key, p) for spec in fc.FUNCTION_CATALOG.values() for p in spec.params]


class ParamSpecDeclarationTest(SimpleTestCase):

    def test_arguments_past_max_must_be_named(self):
        """La forme rend la confusion IMPOSSIBLE : `ParamSpec(k, t, d, lo, hi, 'm', 'desc')`
        mettait 'm' dans `choices` et 'desc' dans `unit`, sans erreur."""
        with self.assertRaises(TypeError):
            ParamSpec('k', 'float', 1.0, 0.0, 2.0, 'm')
        p = ParamSpec('k', 'float', 1.0, 0.0, 2.0, unit='m', description='Une distance.')
        self.assertEqual(('m', 'Une distance.', None), (p.unit, p.description, p.choices))

    def test_every_declared_type_crosses_the_bridge(self):
        self.assertEqual(set(PARAM_TYPES), set(SPEC_TYPE_TO_PARAM_TYPE))

    def test_every_catalog_declaration_is_well_formed(self):
        problems = []
        for key, p in _catalog_params():
            where = f'{key}.{p.key}'
            if p.type not in PARAM_TYPES:
                problems.append(f'{where} : type « {p.type} » hors vocabulaire')
            if p.choices is not None and p.type != 'enum':
                problems.append(f'{where} : des `choices` sur un {p.type} ({p.choices!r})')
            if p.type == 'enum':
                if not p.choices or not all(isinstance(c, (str, int, float)) for c in p.choices):
                    problems.append(f'{where} : un enum sans liste de valeurs simples')
                elif p.default is not None and p.default not in p.choices:
                    problems.append(f'{where} : défaut {p.default!r} hors des choix')
            # Une unité est un SYMBOLE court ; une phrase dans `unit` est une description égarée.
            if p.unit and (len(p.unit) > 8 or any(ch.isspace() for ch in p.unit)):
                problems.append(f'{where} : unité « {p.unit} » — une description égarée ?')
            if (p.type in ('float', 'int') and isinstance(p.default, (int, float))
                    and not isinstance(p.default, bool)):
                if (p.min is not None and p.default < p.min) or (p.max is not None and p.default > p.max):
                    problems.append(f'{where} : défaut {p.default} hors de [{p.min}, {p.max}]')
        self.assertEqual([], problems)


class BridgeTest(SimpleTestCase):

    def test_the_projection_keeps_everything_the_declaration_says(self):
        for key, spec in _catalog_params():
            with self.subTest(param=f'{key}.{spec.key}'):
                p = param_from_spec(spec)
                self.assertEqual((spec.key, spec.default, spec.min, spec.max, spec.unit or ''),
                                 (p.name, p.default, p.min, p.max, p.unit))
                self.assertEqual(spec.description or '', p.help)
                self.assertEqual(SPEC_TYPE_TO_PARAM_TYPE[spec.type], p.type)
                if spec.type == 'enum':
                    self.assertEqual([str(c) for c in spec.choices], [v for v, _ in p.choices])

    def test_numbers_are_numbers_with_their_grid(self):
        """Un entier a une grille de 1 ; un décimal n'en a pas (`any`) — sans elle, un champ
        nombre du navigateur n'accepte que des entiers et sa flèche avance de 1."""
        cases = {'int': ('number', 1), 'float': ('number', 'any'), 'bool': ('toggle', None),
                 'enum': ('select', None), 'str': ('text', None), 'json': ('textarea', None)}
        for kind, expected in cases.items():
            with self.subTest(kind=kind):
                p = param_from_spec(ParamSpec('k', kind, choices=['a'] if kind == 'enum' else None))
                self.assertEqual(expected, (p.type, p.step))

    def test_without_a_short_label_the_key_is_the_label_and_the_description_the_help(self):
        p = param_from_spec(ParamSpec('max_delay', 'float', 2.0, unit='s',
                                      description='Délai maximal entre le départ et la fin.'))
        self.assertEqual(('max_delay', 'Délai maximal entre le départ et la fin.'), (p.label, p.help))

    def test_an_unknown_type_is_refused_not_rendered_as_text(self):
        with self.assertRaisesMessage(ValueError, 'duration'):
            param_from_spec(ParamSpec('k', 'duration'))


SPEC = FunctionSpec(key='probe', name='Sonde', description='', category=fc.FunctionCategory.TRANSFORM,
                    params=[ParamSpec('ratio', 'float', 0.5, 0.0, 1.0),
                            ParamSpec('count', 'int', 3, 1, 10),
                            ParamSpec('mode', 'enum', 'a', choices=['a', 'b']),
                            ParamSpec('strict', 'bool', False),
                            ParamSpec('expr', 'json', '')])


class GateTest(SimpleTestCase):

    def test_values_are_typed_and_bounded(self):
        self.assertEqual({'ratio': 1, 'count': 4, 'mode': 'b', 'strict': True},
                         SPEC.call_params({'ratio': '1.7', 'count': '4', 'mode': 'b', 'strict': '1'}))

    def test_a_decimal_has_no_grid(self):
        self.assertEqual({'ratio': 0.123}, SPEC.call_params({'ratio': '0.123'}))

    def test_absent_or_empty_values_leave_the_function_default(self):
        self.assertEqual({}, SPEC.call_params({'ratio': '', 'count': None, 'unknown': '3'}))

    def test_a_structure_entered_as_text_reaches_the_function_as_written(self):
        self.assertEqual({'expr': '[{"key": "C1"}]'}, SPEC.call_params({'expr': '[{"key": "C1"}]'}))

    def test_refusals_name_the_setting_and_the_value(self):
        cases = {'mode': ('z', "'z' n'est pas un choix proposé"),
                 'ratio': ('beaucoup', "'beaucoup' n'est pas un nombre"),
                 'count': ('2.5', "2.5 — valeurs applicables de 1 en 1")}
        for name, (value, expected) in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as caught:
                    SPEC.call_params({name: value})
                self.assertIn(f'{name} : ', str(caught.exception))
                self.assertIn(expected, str(caught.exception))

    def test_every_refusal_is_listed_at_once(self):
        """Tout ce qui est refusé est dit en une fois — pas une correction à la fois."""
        refusals = schema_refusals(SPEC.param_schema(), {'mode': 'z', 'ratio': 'x', 'count': '5'})
        self.assertEqual({'mode', 'ratio'}, set(refusals))

    def test_the_gate_is_the_same_for_any_schema(self):
        """La porte ne connaît pas les fonctions : un schéma d'app ou d'un nœud intégré y passe."""
        schema = [{'name': 'size', 'type': 'range', 'min': 0, 'max': 10, 'step': 2}]
        self.assertEqual({'size': 10}, checked_values(schema, {'size': '12'}))
        with self.assertRaises(ValueError):
            checked_values(schema, {'size': '3'})

    def test_the_grid_judges_the_bounded_value(self):
        """Comme la porte des outils l'a toujours fait : 200 est ramené au maximum (99, impair),
        et c'est lui que la grille juge — seul l'inapplicable APRÈS coercition se refuse."""
        schema = [{'name': 'kernel', 'type': 'range', 'min': 1, 'max': 99, 'step': 2}]
        self.assertEqual({}, schema_refusals(schema, {'kernel': 200}))
        self.assertIn('kernel', schema_refusals(schema, {'kernel': 2}))


class GroupsForAppTest(SimpleTestCase):
    """Les groupes d'affichage suivent le schéma principal, par la même résolution."""

    def test_the_groups_of_the_principal_schema(self):
        from wama.anonymizer import params as anonymizer
        from wama.common.utils.param_schema import groups_for_app
        from wama.imager import params as imager
        self.assertEqual(anonymizer.GROUPS_JSON, groups_for_app('anonymizer'))
        self.assertEqual(imager.IMAGE_GROUPS_JSON, groups_for_app('imager'))

    def test_an_app_without_groups_renders_flat(self):
        from wama.common.utils.param_schema import groups_for_app
        self.assertEqual([], groups_for_app('enhancer'))
        self.assertEqual([], groups_for_app('nothing_here'))
