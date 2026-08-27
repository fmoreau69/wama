"""Verrouille la FERMETURE du compte de service anonyme.

Contexte (2026-08-22 puis 2026-08-27) : WAMA porte deux « anonymes » opposés — `AnonymousUser`
de Django, refusé partout, et l'utilisateur **`anonymous` EN BASE** que les vues substituent aux
requêtes non authentifiées. Le second portait les 4 rôles métier et le tier `utilisateur`, donc
il était **accepté partout** : `user_tier()` teste `is_authenticated`, propriété toujours vraie
sur une instance `User`.

La fermeture du 22/08 avait été faite À LA MAIN sur la base vivante. Mesuré le 27/08, ça ne
tenait pas : `UserProfile.account_tier` a pour défaut `utilisateur`, donc tout compte anonyme
recréé (installation neuve, restauration) revenait ouvert, et `grant_default_roles` — qui vise
les comptes SANS aucun rôle — lui rendait les 4 rôles. Ces tests prouvent que l'invariant vit
maintenant dans le CODE, où une réinstallation ne peut plus le défaire.
"""
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from wama.accounts.models import UserProfile
from wama.accounts.permissions import GROUP_PREFIX, ROLES, accessible, user_roles, user_tier
from wama.accounts.views import ANONYMOUS_USERNAME, get_or_create_anonymous_user
from wama.common.app_registry import APP_CATALOG


def _tous_les_groupes_de_role():
    return [Group.objects.get_or_create(name=GROUP_PREFIX + k)[0] for k in ROLES]


class FermetureDuCompteAnonymeTests(TestCase):

    def test_un_compte_anonyme_neuf_nait_ferme(self):
        # Le cas d'une installation neuve : rien n'a jamais été corrigé à la main.
        u = get_or_create_anonymous_user()
        self.assertEqual(user_tier(u), 'anonymous')
        self.assertEqual(user_roles(u), set())

    def test_un_compte_anonyme_neuf_n_ouvre_aucune_app(self):
        u = get_or_create_anonymous_user()
        ouvertes = [a for a in APP_CATALOG if accessible(u, 'app', a)]
        self.assertEqual(ouvertes, [], f"apps ouvertes à l'anonyme : {ouvertes}")

    def test_le_tier_pose_a_la_main_est_repose_au_prochain_appel(self):
        # La dérive qu'on veut rattraper : quelqu'un remonte le tier via l'admin.
        u = get_or_create_anonymous_user()
        UserProfile.objects.filter(user=u).update(account_tier='utilisateur')
        import wama.accounts.views as v
        v._CLOSURE_VERIFIEE = False          # simule un worker qui redémarre
        u = get_or_create_anonymous_user()
        self.assertEqual(user_tier(u), 'anonymous')

    def test_des_roles_rendus_a_la_main_sont_retires_au_prochain_appel(self):
        u = get_or_create_anonymous_user()
        u.groups.add(*_tous_les_groupes_de_role())
        import wama.accounts.views as v
        v._CLOSURE_VERIFIEE = False
        u = get_or_create_anonymous_user()
        self.assertEqual(user_roles(u), set())

    def test_grant_default_roles_ne_touche_jamais_le_compte_anonyme(self):
        # C'était le chemin de régression : la commande vise les users SANS rôle, c'est-à-dire
        # exactement l'anonyme depuis qu'on l'a fermé.
        _tous_les_groupes_de_role()
        anon = get_or_create_anonymous_user()
        autre = User.objects.create_user('quelquun', password='x')
        call_command('grant_default_roles', verbosity=0)
        self.assertEqual(user_roles(anon), set())
        self.assertTrue(user_roles(autre), "la commande doit rester utile aux autres comptes")

    def test_grant_default_roles_epargne_l_anonyme_meme_avec_all_users(self):
        # L'exclusion n'a pas d'échappatoire : `--all-users` ne doit pas la lever.
        _tous_les_groupes_de_role()
        anon = get_or_create_anonymous_user()
        call_command('grant_default_roles', '--all-users', verbosity=0)
        self.assertEqual(user_roles(anon), set())


class DeuxAxesDuModeleDAccesTests(TestCase):
    """Le modèle est à DEUX axes : on ne doit dépendre d'aucun des deux tout seul."""

    def setUp(self):
        _tous_les_groupes_de_role()
        self.u = get_or_create_anonymous_user()

    def test_le_tier_seul_ferme_deja_tout_meme_avec_tous_les_roles(self):
        self.u.groups.add(*_tous_les_groupes_de_role())
        ouvertes = [a for a in APP_CATALOG if accessible(self.u, 'app', a)]
        self.assertEqual(ouvertes, [], "le tier `anonymous` doit trancher avant les rôles")

    def test_le_tier_seul_perdu_rouvre_deja_une_app(self):
        # La preuve que le second verrou (les rôles) n'est pas décoratif : sans le tier, la
        # branche « app commune » laisse passer converter — et avec les rôles, 10 apps sur 11.
        UserProfile.objects.filter(user=self.u).update(account_tier='utilisateur')
        u = User.objects.get(username=ANONYMOUS_USERNAME)
        sans_roles = {a for a in APP_CATALOG if accessible(u, 'app', a)}
        u.groups.add(*_tous_les_groupes_de_role())
        u = User.objects.get(username=ANONYMOUS_USERNAME)
        avec_roles = {a for a in APP_CATALOG if accessible(u, 'app', a)}
        self.assertLess(len(sans_roles), len(avec_roles),
                        "les rôles doivent élargir l'accès une fois le tier perdu")
