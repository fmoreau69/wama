"""
Politique de session — l'auto-déconnexion par inactivité et, surtout, SON DÉFAUT INERTE.

Le mécanisme est livré DÉSACTIVÉ (`WAMA_SESSION_IDLE_MINUTES=0`, 2026-08-31) : Fabien voulait
qu'il existe et se règle par une variable, sans rien changer aujourd'hui. Le seul défaut qui
compte dans ce montage est donc « la valeur par défaut a changé quelque chose » — et il ne se
voit pas à la lecture : une session qui expire trop tôt se manifeste par des déconnexions
apparemment aléatoires, chez l'utilisateur, des jours plus tard.

Lancer : `python manage.py test wama.accounts.tests_session_policy` (venv WSL).
"""
from django.conf import settings
from django.test import SimpleTestCase

from wama.settings import SESSION_AGE_PAR_DEFAUT, _politique_session_inactivite


class DefautInerteTests(SimpleTestCase):
    """0 (et l'absence de variable) doivent rendre EXACTEMENT la politique historique."""

    def test_zero_rend_la_politique_historique(self):
        age, glissant = _politique_session_inactivite(0)
        self.assertEqual(age, SESSION_AGE_PAR_DEFAUT)
        self.assertEqual(age, 86400 * 7, "la durée historique est 7 jours")
        self.assertFalse(glissant, "sans activation, aucun renouvellement par requête")

    def test_une_valeur_absente_ou_absurde_est_inerte(self):
        for valeur in (None, 0, -1):
            self.assertEqual(_politique_session_inactivite(valeur),
                             (SESSION_AGE_PAR_DEFAUT, False), f"valeur {valeur!r}")

    def test_l_instance_courante_tourne_bien_avec_le_defaut(self):
        """La contre-épreuve : ce n'est pas la FONCTION qu'on veut inerte, c'est WAMA."""
        self.assertEqual(settings.SESSION_COOKIE_AGE, 86400 * 7)
        self.assertFalse(getattr(settings, 'SESSION_SAVE_EVERY_REQUEST', False))
        self.assertEqual(settings.WAMA_SESSION_IDLE_MINUTES, 0)


class ActivationTests(SimpleTestCase):
    """Quand on l'active, l'expiration doit être GLISSANTE — pas absolue."""

    def test_l_activation_borne_l_inactivite_en_secondes(self):
        self.assertEqual(_politique_session_inactivite(30), (1800, True))
        self.assertEqual(_politique_session_inactivite(60), (3600, True))

    def test_l_expiration_est_glissante_et_non_absolue(self):
        """`SESSION_SAVE_EVERY_REQUEST` est ce qui distingue les deux sémantiques :
        sans lui, l'utilisateur serait déconnecté N minutes après sa CONNEXION, même en
        plein travail — ce n'est pas ce que « auto-déconnexion » veut dire."""
        _, glissant = _politique_session_inactivite(30)
        self.assertTrue(glissant)
