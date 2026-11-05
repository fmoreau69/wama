"""A COMPOUND licence expression (2026-11-05) — `license_audit.license_terms` and `qualifier`.

Whisper's weights are published by OpenAI (apache-2.0) and converted to CTranslate2 by Systran
(mit): the model WAMA installs carries both, `apache-2.0 AND mit` (Fabien's decision). Libraries
already carried such expressions (`MIT AND MPL-2.0`), and the audit qualified them by their FIRST
token — `MIT AND MPL-2.0` passed for permissive while MPL-2.0 is a weak copyleft.
"""
from django.test import SimpleTestCase

from wama.common.services import license_audit as audit


class LicenseTermsTest(SimpleTestCase):

    def test_an_expression_is_split_into_normalised_terms(self):
        self.assertEqual(('AND', ['apache-2.0', 'mit']), audit.license_terms('apache-2.0 AND mit'))
        self.assertEqual(('OR', ['mit', 'apache-2.0']), audit.license_terms('MIT OR Apache-2.0'))
        self.assertEqual(('AND', ['unlicense', 'mit', 'isc']),
                         audit.license_terms('Unlicense AND MIT AND ISC'))

    def test_a_single_licence_and_nothing(self):
        self.assertEqual(('', ['mit']), audit.license_terms('MIT License'))
        self.assertEqual(('', []), audit.license_terms(''))
        self.assertEqual(('', []), audit.license_terms(None))

    def test_a_lower_case_and_belongs_to_a_licence_name(self):
        """SPDX writes its operators in capitals; free text says « and » inside a name."""
        operator, _terms = audit.license_terms('Research and Commercial License')
        self.assertEqual('', operator)

    def test_a_mixed_or_bracketed_expression_is_not_guessed(self):
        self.assertEqual('', audit.license_terms('MIT AND BSD OR ISC')[0])
        self.assertEqual('', audit.license_terms('MIT OR (Apache-2.0 AND BSD)')[0])


class CompoundQualificationTest(SimpleTestCase):

    def test_and_obliges_to_every_term_so_the_most_constraining_one(self):
        q = audit.qualifier('MIT AND MPL-2.0')
        self.assertEqual((audit.COPYLEFT_FAIBLE, 'mit AND mpl-2.0'), (q['rang'], q['id']))

    def test_or_lets_one_choose_so_the_least_constraining_one(self):
        q = audit.qualifier('AGPL-3.0 OR MIT')
        self.assertEqual((audit.PERMISSIVE, 'agpl-3.0 OR mit'), (q['rang'], q['id']))

    def test_whispers_licence_is_permissive_and_owes_attribution(self):
        q = audit.qualifier('apache-2.0 AND mit')
        self.assertEqual((audit.PERMISSIVE, True), (q['rang'], q['attribution']))

    def test_counter_proof_a_single_licence_is_qualified_as_before(self):
        self.assertEqual(audit.qualifier('mpl-2.0')['rang'], audit.COPYLEFT_FAIBLE)
        self.assertEqual('apache-2.0', audit.qualifier('Apache 2.0 License')['id'])
        self.assertEqual(audit.INCONNUE, audit.qualifier('')['rang'])
