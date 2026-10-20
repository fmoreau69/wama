"""La PROVENANCE des éléments de chaque registre — étape 1 du chantier `ROADMAP §29`.

Deux axes de droits, à ne pas confondre : « qui a le DROIT » (`accounts.permissions.accessible`,
famille par famille dans `KIND_DECISION`) et « à QUI c'est » (propriétaire et portée,
`ScopedVisibility`). Ce fichier tient le second pour le CATALOGUE : chaque registre dit où vit la
provenance de ses éléments, et une capacité nouvelle ne peut pas entrer sans le dire.

Aucune décision d'accès ne change ici : on DÉCLARE et on MESURE. Les familles qui attendent leur
porteur sont nommées dans un budget qui ne peut que descendre — porter une famille (§29, étapes
2 à 5) la retire du budget dans le même commit.

⚠ À ne pas confondre avec `tests_provenance` : la provenance d'un FICHIER d'entrée (lien source ⟷
copie de travail, `MEDIA_STORAGE_TIERING §8.7`), une autre notion qui porte le même mot.
"""
from django.apps import apps
from django.test import SimpleTestCase

from wama.accounts.permissions import KIND_DECISION
from wama.common.models import ScopedVisibility
from wama.common.registries import (CARRIED, DERIVED, PROVENANCES, REGISTRIES, TO_CARRY, Registry,
                                    overview, register)

#: Les registres dont les éléments d'utilisateurs n'ont pas encore de porteur, mesuré le
#: 2026-10-18. Ne peut que DESCENDRE : y ajouter une clé, c'est faire entrer une capacité sans
#: dire à qui sont ses éléments ; en garder une qui ne l'est plus, c'est laisser une marge.
#: `models` en est sorti à l'étape 3 (même jour) : `AIModel` porte propriétaire et portée.
#: `skills` le 2026-10-20 : un skill d'utilisateur a sa ligne `PromptSkill`.
TO_CARRY_BUDGET = {'apps', 'libraries', 'ui_bricks'}


def _real_registries():
    """Les registres de WAMA, sans ceux qu'un test pose le temps d'un cas (`_t_…`)."""
    return {k: r for k, r in REGISTRIES.items() if not k.startswith('_t_')}


class ProvenanceIsDeclaredTest(SimpleTestCase):

    def test_every_registry_states_where_its_elements_provenance_lives(self):
        undeclared = sorted(k for k, r in _real_registries().items()
                            if r.provenance not in PROVENANCES)
        self.assertEqual(undeclared, [],
                         f"registre(s) sans provenance déclarée : {undeclared} — dire à QUI sont "
                         f"leurs éléments (`registries.PROVENANCES`, ROADMAP §29)")

    def test_a_carried_provenance_names_a_row_that_inherits_scoped_visibility(self):
        carried = {k: r for k, r in _real_registries().items() if r.provenance in CARRIED}
        self.assertTrue(carried, "aucun registre porté : le test ne mesurerait rien")
        for key, r in carried.items():
            model = apps.get_model(r.owner_model)
            self.assertTrue(issubclass(model, ScopedVisibility),
                            f"{key} : {r.owner_model} ne porte pas propriétaire et portée")

    def test_the_families_still_to_carry_can_only_shrink(self):
        measured = {k for k, r in _real_registries().items() if r.provenance == TO_CARRY}
        self.assertEqual(
            measured, TO_CARRY_BUDGET,
            f"en trop : {sorted(measured - TO_CARRY_BUDGET)} — une capacité nouvelle déclare son "
            f"porteur ; devenues portées : {sorted(TO_CARRY_BUDGET - measured)} — les retirer du "
            f"budget dans le même commit")

    def test_the_overview_shows_the_provenance(self):
        rows = {r['key']: r for r in overview()}
        self.assertEqual(rows['rag']['provenance_label'], PROVENANCES['owned'])
        self.assertEqual(rows['functions']['owner_model'], 'common.UserFunction')


class ProvenanceMeetsTheAccessDecisionTest(SimpleTestCase):
    """Le lien entre les deux axes : une famille de `KIND_DECISION` = un registre."""

    def test_each_access_family_is_listed_by_exactly_one_registry(self):
        declared = [r.access_kind for r in _real_registries().values() if r.access_kind]
        unknown = sorted(set(declared) - set(KIND_DECISION))
        self.assertEqual(unknown, [], f"famille(s) absente(s) de KIND_DECISION : {unknown}")
        twice = sorted({k for k in declared if declared.count(k) > 1})
        self.assertEqual(twice, [], f"famille(s) listée(s) par plusieurs registres : {twice}")
        self.assertEqual(sorted(set(KIND_DECISION) - set(declared)), [],
                         "famille d'accès sans registre qui en liste les éléments")

    def test_a_family_decided_by_scoped_visibility_has_carried_elements(self):
        # `rag_scope` est gardé par la portée héritée : son registre doit la porter réellement.
        by_kind = {r.access_kind: r for r in _real_registries().values() if r.access_kind}
        decided = [k for k, d in KIND_DECISION.items() if d == 'ScopedVisibility']
        self.assertTrue(decided, "aucune famille gardée par la portée : le test ne mesurerait rien")
        for kind in decided:
            self.assertIn(by_kind[kind].provenance, CARRIED, kind)

    def test_a_family_decided_by_its_provenance_names_the_row_and_its_key(self):
        # `accessible()` lit l'élément sur la ligne que son registre déclare : sans elle, la
        # décision ne saurait où chercher (`permissions._provenance_accessible`).
        by_kind = {r.access_kind: r for r in _real_registries().values() if r.access_kind}
        decided = [k for k, d in KIND_DECISION.items() if d == 'provenance']
        self.assertTrue(decided, "aucune famille décidée par la provenance : rien à mesurer")
        for kind in decided:
            r = by_kind[kind]
            self.assertIn(r.provenance, CARRIED, kind)
            model = apps.get_model(r.owner_model)
            self.assertTrue(issubclass(model, ScopedVisibility), kind)
            model._meta.get_field(r.owner_key)      # lève si le champ n'existe pas
            model._meta.get_field('owner')          # le filtre des catalogues lit `owner`


class RegisterRejectsAnIncoherentProvenanceTest(SimpleTestCase):

    def tearDown(self):
        for key in ('_t_prov_unknown', '_t_prov_no_row', '_t_prov_stray_row', '_t_prov_stray_key',
                    '_t_prov_stray_app', '_t_prov_stray_code'):
            REGISTRIES.pop(key, None)

    def test_a_code_overlap_without_the_row_key_is_refused(self):
        # `in_code` dit qu'une clé de ligne désigne AUSSI un élément du code ; sans `owner_key`,
        # aucune ligne n'est cherchée d'abord (`registries.declared_in_code`).
        with self.assertRaises(ValueError):
            register(Registry(key='_t_prov_stray_code', label='x', nature=DERIVED, source='s',
                              provenance='mixed', owner_model='common.PromptSkill',
                              in_code=lambda key: True))

    def test_a_declaring_app_without_the_row_key_is_refused(self):
        # `element_app` dit l'app d'un élément SANS ligne ; sans `owner_key`, rien ne
        # chercherait la ligne d'abord (`registries.declaring_app`).
        with self.assertRaises(ValueError):
            register(Registry(key='_t_prov_stray_app', label='x', nature=DERIVED, source='s',
                              provenance='mixed', owner_model='common.UserFunction',
                              element_app=lambda key: ''))

    def test_a_key_field_without_its_row_is_refused(self):
        with self.assertRaises(ValueError):
            register(Registry(key='_t_prov_stray_key', label='x', nature=DERIVED, source='s',
                              provenance='system', owner_key='model_key'))

    def test_an_unknown_provenance_is_refused(self):
        with self.assertRaises(ValueError):
            register(Registry(key='_t_prov_unknown', label='x', nature=DERIVED, source='s',
                              provenance='shared'))

    def test_a_carried_provenance_without_its_row_is_refused(self):
        with self.assertRaises(ValueError):
            register(Registry(key='_t_prov_no_row', label='x', nature=DERIVED, source='s',
                              provenance='owned'))

    def test_a_row_without_a_carried_provenance_is_refused(self):
        with self.assertRaises(ValueError):
            register(Registry(key='_t_prov_stray_row', label='x', nature=DERIVED, source='s',
                              provenance='system', owner_model='common.UserFunction'))
