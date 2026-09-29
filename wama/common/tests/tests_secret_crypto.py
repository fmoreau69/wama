"""
Chiffrement des secrets d'utilisateur (2026-09-15) — clé DÉRIVÉE de SECRET_KEY.

⚠ CE QUE CES GARDES PROTÈGENT : une clé d'API chiffrée avec une clé qui a quitté les
`SECRET_KEY_FALLBACKS` est PERDUE, et rien ne le signale au moment de la rotation. Le rechiffrement
(`reencrypt`) est ce qui l'évite : il doit rendre un secret lisible par la SEULE nouvelle clé.
"""
from django.test import SimpleTestCase, override_settings

from wama.common.utils import secret_crypto as sc

CLE_A = 'a' * 50
CLE_B = 'b' * 50
CLE_C = 'c' * 50


class SecretCryptoTest(SimpleTestCase):

    @override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[])
    def test_aller_retour(self):
        jeton = sc.encrypt('sk-albert-123')
        self.assertNotIn('sk-albert-123', jeton)
        self.assertEqual('sk-albert-123', sc.decrypt(jeton))

    def test_une_autre_cle_ne_lit_pas(self):
        with override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[]):
            jeton = sc.encrypt('secret')
        with override_settings(SECRET_KEY=CLE_B, SECRET_KEY_FALLBACKS=[]):
            with self.assertRaises(sc.SecretUnreadable):
                sc.decrypt(jeton)

    def test_juste_apres_une_rotation_le_fallback_lit(self):
        with override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[]):
            jeton = sc.encrypt('secret')
        with override_settings(SECRET_KEY=CLE_B, SECRET_KEY_FALLBACKS=[CLE_A]):
            self.assertEqual('secret', sc.decrypt(jeton))

    def test_le_rechiffrement_rend_le_secret_lisible_par_la_seule_nouvelle_cle(self):
        with override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[]):
            jeton = sc.encrypt('secret')
        neuf = sc.reencrypt(jeton, CLE_C, [CLE_B, CLE_A])
        # CLE_A a quitté les fallbacks : sans rechiffrement, le secret serait perdu.
        with override_settings(SECRET_KEY=CLE_C, SECRET_KEY_FALLBACKS=[]):
            self.assertEqual('secret', sc.decrypt(neuf))

    def test_la_derivation_ne_chiffre_pas_avec_la_cle_de_signature_brute(self):
        """Une clé Fernet construite DIRECTEMENT sur SECRET_KEY ne doit pas lire nos secrets."""
        import base64
        import hashlib
        from cryptography.fernet import Fernet, InvalidToken
        with override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[]):
            jeton = sc.encrypt('secret')
        naif = Fernet(base64.urlsafe_b64encode(hashlib.sha256(CLE_A.encode()).digest()))
        with self.assertRaises(InvalidToken):
            naif.decrypt(jeton.encode())

    @override_settings(SECRET_KEY='django-insecure-dev-only-CHANGE-ME', SECRET_KEY_FALLBACKS=[])
    def test_une_cle_non_sure_refuse_d_enregistrer(self):
        self.assertFalse(sc.storage_available())
        with self.assertRaises(sc.SecretStorageUnavailable):
            sc.encrypt('secret')

    def test_un_rechiffrement_vers_une_cle_non_sure_est_refuse(self):
        with override_settings(SECRET_KEY=CLE_A, SECRET_KEY_FALLBACKS=[]):
            jeton = sc.encrypt('secret')
        with self.assertRaises(sc.SecretStorageUnavailable):
            sc.reencrypt(jeton, 'django-insecure-x', [CLE_A])
