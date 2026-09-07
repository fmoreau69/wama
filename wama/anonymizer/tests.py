"""Anonymizer — ce qu'un DÉPÔT ne doit pas faire aux réglages des autres (2026-09-07).

Le `post_save` de `Media` (`signals.py`) réinitialisait les `UserSettings` de TOUS les
utilisateurs à chaque création de média, et fermait la connexion en plein cycle de requête.
Trouvé par `common/tests_import_contract` (« the connection is closed » dans un `TestCase`),
corrigé le jour même. Ces tests tiennent les deux invariants du correctif.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.anonymizer.models import Media, UserSettings

User = get_user_model()


class DepotEtReglagesDesAutresTest(TestCase):

    def setUp(self):
        self.deposant = User.objects.create_user('anon_deposant', password='x')
        self.autre = User.objects.create_user('anon_autre', password='x')
        # L'autre utilisateur a PERSONNALISÉ ses réglages.
        reglages, _ = UserSettings.objects.get_or_create(user=self.autre)
        reglages.blur_ratio = 61
        reglages.precision_level = 90
        reglages.show_preview = False
        reglages.GSValues_customised = True
        reglages.save()

    def test_creer_un_media_ne_reinitialise_pas_les_reglages_d_un_autre_utilisateur(self):
        Media.objects.create(user=self.deposant, file='anonymizer/x/input/temoin.png', file_ext='.png')
        r = UserSettings.objects.get(user=self.autre)
        self.assertEqual((61, 90, False, True),
                         (r.blur_ratio, r.precision_level, r.show_preview, r.GSValues_customised),
                         "le dépôt d'un utilisateur a réinitialisé les réglages d'un autre")

    def test_creer_un_media_garantit_les_reglages_du_deposant_sans_les_ecraser(self):
        mine, _ = UserSettings.objects.get_or_create(user=self.deposant)
        mine.blur_ratio = 33
        mine.save()
        Media.objects.create(user=self.deposant, file='anonymizer/x/input/temoin.png', file_ext='.png')
        self.assertEqual(33, UserSettings.objects.get(user=self.deposant).blur_ratio)

    def test_creer_un_media_dans_une_transaction_de_test_ne_ferme_pas_la_connexion(self):
        """La forme exacte du symptôme : un `TestCase` (transaction englobante) puis une requête."""
        Media.objects.create(user=self.deposant, file='anonymizer/x/input/temoin.png', file_ext='.png')
        self.assertEqual(1, Media.objects.filter(user=self.deposant).count())
