"""
Le bloc « Rattachement institutionnel » du profil DIT ce que le partage fait (2026-09-26).

LE DÉFAUT MESURÉ (relevé par Fabien sur son propre profil). La page affichait trois codes
d'annuaire à égalité — `{IFSTTAR}LESCOT`, `CFR - LESCOT`, `{EIFFEL}CFR - LESCOT` — sous un
établissement nommé `{UAI}0772894C`, et concluait : « Elles vous ouvrent le partage au niveau
labo ». Or `lab_share_target` REFUSE quand il y a plusieurs affiliations : « nommer l'unité
cible via org_unit ». La page promettait donc l'inverse de ce que le code fait.

⭐ *Une page qui promet ce que le code refuse est un bug d'interface, pas de présentation.*

CE QUE CES GARDES TIENNENT :
  1. l'état du partage est DEMANDÉ au mécanisme (`lab_share_target`), jamais redit ici ;
  2. une seule unité → elle est nommée ; plusieurs → on dit qu'il faudra désigner ;
  3. les libellés sont lisibles (le préfixe d'autorité SUPANN sort du titre), et le code brut
     reste disponible — il sert au diagnostic ;
  4. deux unités homonymes restent distinguables par leur annuaire émetteur.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.accounts.ldap import split_namespace
from wama.accounts.views import rattachement_institutionnel
from wama.common.models import OrgUnit


class SupannNamespaceTest(TestCase):

    def test_the_authority_prefix_is_separated_from_the_value(self):
        self.assertEqual(('IFSTTAR', 'LESCOT'), split_namespace('{IFSTTAR}LESCOT'))
        self.assertEqual(('UAI', '0772894C'), split_namespace('{UAI}0772894C'))

    def test_a_plain_code_is_left_alone(self):
        self.assertEqual(('', 'CFR - LESCOT'), split_namespace('CFR - LESCOT'))
        self.assertEqual(('', ''), split_namespace(None))


class AffiliationBlockTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('agent', password='x')
        self.profile = self.user.profile
        self.profile.establishment = '{UAI}0772894C'
        self.profile.save()

    def _unit(self, code, name, unit_type='labo'):
        return OrgUnit.objects.create(code=code, name=name, unit_type=unit_type)

    def test_a_single_recognised_unit_is_named_as_the_share_target(self):
        self._unit('CFR - LESCOT', 'LESCOT')
        self.profile.org_affiliations = ['CFR - LESCOT']
        self.profile.org_entity_code = 'CFR - LESCOT'
        self.profile.save()

        ctx = rattachement_institutionnel(self.profile)
        self.assertIsNotNone(ctx['partage_cible'])
        self.assertEqual('LESCOT', ctx['partage_cible'].name)
        self.assertFalse(ctx['partage_a_designer'])

    def test_several_affiliations_say_the_user_will_have_to_choose(self):
        """LE cas mesuré : le mécanisme refuse de trancher, la page le DIT."""
        self._unit('CFR - LESCOT', 'LESCOT')
        self._unit('{IFSTTAR}LESCOT', '{IFSTTAR}LESCOT', 'autre')
        self.profile.org_affiliations = ['{IFSTTAR}LESCOT', 'CFR - LESCOT',
                                         '{EIFFEL}CFR - LESCOT']
        self.profile.org_entity_code = 'CFR - LESCOT'
        self.profile.save()

        ctx = rattachement_institutionnel(self.profile)
        self.assertIsNone(ctx['partage_cible'], "rien n'est ouvert automatiquement")
        self.assertTrue(ctx['partage_a_designer'])
        self.assertIn('nommer', ctx['partage_raison'])

    def test_labels_are_readable_and_raw_codes_are_kept(self):
        self._unit('{IFSTTAR}LESCOT', '{IFSTTAR}LESCOT', 'autre')
        self.profile.org_affiliations = ['{IFSTTAR}LESCOT', '{EIFFEL}CFR - LESCOT']
        self.profile.save()

        ctx = rattachement_institutionnel(self.profile)
        par_code = {r['code']: r for r in ctx['rattachements']}
        # Le nom de l'unité VAUT son propre code brut (artefact d'import) → on affiche la
        # valeur sans son préfixe, et l'annuaire émetteur distingue les homonymes.
        self.assertEqual('LESCOT', par_code['{IFSTTAR}LESCOT']['libelle'])
        self.assertEqual('IFSTTAR', par_code['{IFSTTAR}LESCOT']['autorite'])
        # Le code brut reste là : c'est lui qui sert au diagnostic.
        self.assertEqual('{IFSTTAR}LESCOT', par_code['{IFSTTAR}LESCOT']['code'])
        self.assertEqual('CFR - LESCOT', par_code['{EIFFEL}CFR - LESCOT']['libelle'])
        self.assertEqual('0772894C', ctx['etablissement_libelle'])
        self.assertEqual('UAI', ctx['etablissement_autorite'])

    def test_an_account_without_any_affiliation_says_nothing_it_cannot_hold(self):
        ctx = rattachement_institutionnel(self.profile)
        self.assertEqual([], ctx['rattachements'])
        self.assertIsNone(ctx['partage_cible'])
        self.assertFalse(ctx['partage_a_designer'])
