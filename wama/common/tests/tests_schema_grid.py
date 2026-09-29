"""
Une valeur que le schéma ne peut PAS appliquer est refusée, pas corrigée en silence.

LE DÉFAUT MESURÉ (2026-09-23). L'assistant a lancé une anonymisation avec `blur_ratio=2`,
alors que le schéma déclare `min=1, step=2` (noyau gaussien → impair) et que la description
qu'il lit dit « Taille du noyau gaussien (impaire). [1–99] (défaut : 25) ». Rien ne l'a
refusé : `normalize_blur_ratio` a réécrit 2 en 3. Résultat mesuré sur la photo : SAM3 trouve
les TROIS visages (masques aux bonnes coordonnées), et la sortie ne diffère de l'entrée que
de **682 pixels** en liseré de bord — une anonymisation vide qui a l'air d'un succès.

⭐ *Une valeur corrigée en silence est une valeur qu'on n'a pas refusée.*

Les bornes min/max restent CLAMPÉES (`coerce_params`) : on ne refuse que ce qu'aucune
coercition ne peut rendre applicable.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama import tool_api as T
from wama.common.utils.param_schema import schema_for_app, unapplicable_numeric_values


class GridValuesTest(TestCase):

    def test_an_even_gaussian_kernel_is_refused(self):
        bad = unapplicable_numeric_values(schema_for_app('anonymizer'), {'blur_ratio': 2})
        self.assertIn('blur_ratio', bad)
        value, why = bad['blur_ratio']
        self.assertEqual(2, value)
        # le défaut de l'app est NOMMÉ — lu dans le schéma : il était écrit « 25 » en dur, et le
        # passage du défaut à 75 (2026-09-27) a cassé ce test sans rien casser d'autre
        default = next(p['default'] for p in schema_for_app('anonymizer') if p['name'] == 'blur_ratio')
        self.assertIn(f"défaut de l'app : {default}", why)
        self.assertIn('omettez', why)       # et l'omission est la sortie recommandée

    def test_a_value_on_the_grid_passes(self):
        schema = schema_for_app('anonymizer')
        for value in (1, 3, 25, 99):
            self.assertEqual({}, unapplicable_numeric_values(schema, {'blur_ratio': value}),
                             f'blur_ratio={value} refusé à tort')

    def test_a_float_step_tolerates_its_own_arithmetic(self):
        """`detection_threshold` a un pas de 0.05 : 0.6 est sur la grille malgré les flottants."""
        schema = schema_for_app('anonymizer')
        self.assertEqual({}, unapplicable_numeric_values(schema, {'detection_threshold': 0.6}))
        self.assertIn('detection_threshold',
                      unapplicable_numeric_values(schema, {'detection_threshold': 0.123}))

    def test_absent_empty_and_boolean_values_are_left_alone(self):
        schema = schema_for_app('anonymizer')
        for data in ({}, {'blur_ratio': None}, {'blur_ratio': ''}, {'show_boxes': True}):
            self.assertEqual({}, unapplicable_numeric_values(schema, data), data)

    def test_the_door_says_no_and_names_what_to_do(self):
        """Contre-épreuve de câblage : c'est `execute_tool` qui doit dire non.

        ⚠ Le compte FRANCHIT le portier d'app (rôle `communication`), il ne le contourne
        pas : un `is_superuser` rendrait ce test aveugle à une régression du gating, et un
        compte neuf n'a AUCUN rôle — il recevrait `forbidden` avant d'atteindre la grille
        (mesuré ici même)."""
        from django.contrib.auth.models import Group

        from wama.accounts.permissions import GROUP_PREFIX
        user = get_user_model().objects.create_user('grid', password='x')
        user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')[0])
        result = T.execute_tool('add_to_anonymizer',
                                {'file_path': 'users/1/temp/x.jpg', 'blur_ratio': 2}, user)
        self.assertIn('error', result)
        self.assertIn('blur_ratio', result['error'])
