"""
L'abonnement Claude Code — QUI y a droit, et par QUELLES surfaces (ROADMAP §19.3).

Ce que ces tests protègent n'est pas du confort : le fournisseur `claude-abo` exécute un
agent avec accès au dépôt ET consomme le crédit mensuel du titulaire. Deux propriétés
doivent tenir quoi qu'il arrive :

  1. la garde est au PASSAGE OBLIGÉ (`run_assistant_turn`), donc elle vaut pour les trois
     surfaces — un client peut poster `provider` librement, le `{% if is_admin %}` du
     gabarit ne CACHE qu'une ligne, il ne protège rien ;
  2. le prédicat a un DOMICILE UNIQUE (`claude_code.subscription_allowed`) — il avait trois
     appelants au 2026-08-31, et trois copies auraient dérivé.

Lancer : `python manage.py test wama.common.tests.tests_claude_subscription` (venv WSL).
Aucun réseau, aucun CLI : `demander()` est remplacé par un double.
"""
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings

from wama.common.services.assistant_engine import run_assistant_turn
from wama.common.services.claude_code import subscription_allowed


class QuiPeutConsommerLAbonnementTests(TestCase):

    def test_un_utilisateur_ordinaire_n_y_a_pas_droit(self):
        self.assertFalse(subscription_allowed(User.objects.create(username='alice')))

    def test_un_anonyme_n_y_a_pas_droit(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(subscription_allowed(AnonymousUser()))
        self.assertFalse(subscription_allowed(None))

    def test_un_superutilisateur_y_a_droit(self):
        self.assertTrue(subscription_allowed(
            User.objects.create(username='fabien', is_superuser=True)))

    def test_les_deux_vocabulaires_de_role_sont_acceptes(self):
        """⚠ `dev`/`admin` sont des GROUPES, `developpeur` un groupe HOMONYME d'un tier.
        S'en remettre à un seul vocabulaire refuserait un compte légitime."""
        for nom_de_groupe in ('dev', 'admin', 'developpeur'):
            user = User.objects.create(username=f'u-{nom_de_groupe}')
            user.groups.add(Group.objects.get_or_create(name=nom_de_groupe)[0])
            self.assertTrue(subscription_allowed(user), f"groupe {nom_de_groupe} refusé")


class LaGardeEstAuPassageObligeTests(TestCase):
    """Le menu de l'UI ne garde RIEN : la vraie garde est dans le moteur, que les trois
    surfaces (web, API v1, passerelle Discord) traversent toutes."""

    def test_un_utilisateur_ordinaire_qui_poste_le_provider_est_refuse(self):
        alice = User.objects.create(username='alice')
        with patch('wama.common.services.claude_code.demander') as cli:
            resultat = run_assistant_turn(alice, 'audite le dépôt', provider='claude-abo')
        self.assertEqual(resultat.get('status'), 403)
        # Le CLI ne doit même pas être atteint : pas de process, pas de crédit consommé.
        cli.assert_not_called()

    def test_un_admin_atteint_bien_le_cli_de_l_abonnement(self):
        fabien = User.objects.create(username='fabien', is_superuser=True)
        with patch('wama.common.services.claude_code.demander',
                   return_value={'success': True, 'texte': 'réponse abonnement',
                                 'cout_usd': 0.99, 'duree_ms': 3300}) as cli:
            resultat = run_assistant_turn(fabien, 'où vit le nommage de sortie ?',
                                          provider='claude-abo')
        cli.assert_called_once()
        self.assertEqual(resultat.get('response'), 'réponse abonnement')

    def test_l_historique_est_replie_dans_le_prompt(self):
        """⚠ `claude -p` est SANS ÉTAT (process neuf à chaque appel, jamais `--resume`) :
        sans repli de l'historique, l'assistant serait amnésique d'un message à l'autre
        alors que la surface affiche un fil continu."""
        fabien = User.objects.create(username='fabien', is_superuser=True)
        historique = [{'role': 'user', 'content': 'je travaille sur le converter'},
                      {'role': 'assistant', 'content': 'noté'}]
        with patch('wama.common.services.claude_code.demander',
                   return_value={'success': True, 'texte': 'ok', 'cout_usd': None}) as cli:
            run_assistant_turn(fabien, 'et ses tests ?', provider='claude-abo',
                               history=historique)
        prompt = cli.call_args.args[0]
        self.assertIn('je travaille sur le converter', prompt)
        self.assertIn('et ses tests ?', prompt)


@override_settings(SECRET_KEY='k' * 50, SECRET_KEY_FALLBACKS=[])
class LEcranEtLaGardeNeDiverjentPasTests(TestCase):
    """
    ⚠ Le défaut que ces tests empêchent de revenir (trouvé le 2026-08-31 en écrivant la
    ligne d'UI, CORRIGÉ depuis) : `views.home` reposait alors `is_admin` avec **`is_staff`**
    — un TROISIÈME vocabulaire de rôle, différent de la garde. Gater l'option dessus aurait
    fait diverger l'écran de la garde DANS LES DEUX SENS : un membre du groupe `dev`
    autorisé par le moteur sans jamais voir l'option, et un compte `is_staff` voyant une
    option refusée.

    « Deux mesures qui ne répondent pas à la même question ne divergent pas » : ici, elles
    doivent répondre à la MÊME — la liste des fournisseurs (`chat_provider_choices`) applique
    le prédicat unique de la garde.

    2026-09-15 : l'option exige en plus le jeton PERSONNEL et un niveau cloud qui l'autorise
    (même règle que les clés d'API). Les profils ci-dessous les posent donc, pour que la seule
    variable mesurée reste le RÔLE.
    """

    #: 2026-09-16 : l'abonnement n'est plus une option écrite dans le gabarit — c'est une ligne
    #: DÉCLARÉE du catalogue, servie par le sélecteur COMMUN. L'écran se mesure donc là où il se
    #: remplit : l'endpoint d'options, avec les clés de l'utilisateur.
    OPTIONS = '/model-manager/api/models/options/?model_type=llm,vlm&cloud=1'
    MODELE = 'claude_code:default'

    def _ouvrir(self, user, jeton=True, niveau='cloud_allowed'):
        from wama.accounts.models import UserApiKey
        from wama.model_manager.services.cloud_models import refresh_key
        user.profile.cloud_policy = niveau
        # L'abonnement est un hébergeur TIERS : « ouvrir » le cloud à ce compte, c'est aussi
        # relever son plafond d'hébergement (second axe, 2026-10-03).
        user.profile.cloud_hosting_max = 'third_party'
        user.profile.save()
        if jeton:
            # `refresh_key` passe par la synchronisation commune (2026-09-18) : découverte
            # réduite à sa source cloud, ni disque ni Ollama, et pas d'écriture du corpus.
            from wama.model_manager.tests.tests_cloud_models import _sync_cloud_seul
            _sync_cloud_seul(self)
            refresh_key(UserApiKey.objects.create(user=user, source='claude_code',
                                                  api_key='jeton'))
        return user

    def _options(self, user):
        self.client.force_login(user)
        groupes = self.client.get(self.OPTIONS).json()['groups'][0]['options']
        return [(o[0] if isinstance(o, list) else o['value']) for o in groupes]

    def test_un_membre_du_groupe_dev_voit_l_abonnement_bien_que_non_staff(self):
        user = User.objects.create_user('devguy', password='x')
        user.groups.add(Group.objects.get_or_create(name='dev')[0])
        self.assertFalse(user.is_staff, "prérequis du test : ce compte n'est PAS staff")
        self.assertIn(self.MODELE, self._options(self._ouvrir(user)))

    def test_un_utilisateur_ordinaire_ne_voit_pas_l_abonnement(self):
        # Le jeton d'un autre ne lui ouvre rien : la liste suit SES clés.
        self._ouvrir(User.objects.create_user('proprietaire', password='x', is_superuser=True))
        alice = self._ouvrir(User.objects.create_user('alice', password='x'), jeton=False)
        self.assertNotIn(self.MODELE, self._options(alice))

    def test_sans_jeton_ou_en_local_un_developpeur_ne_voit_pas_l_abonnement(self):
        sans_jeton = User.objects.create_user('dev_sans_jeton', password='x', is_superuser=True)
        self.assertNotIn(self.MODELE, self._options(self._ouvrir(sans_jeton, jeton=False)))
        en_local = User.objects.create_user('dev_local', password='x', is_superuser=True)
        self.assertNotIn(self.MODELE, self._options(self._ouvrir(en_local, niveau='local_only')))

    def test_tout_compte_qui_voit_l_abonnement_est_bien_autorise_par_la_garde(self):
        """L'invariant, énoncé dans les deux sens sur un échantillon de profils."""
        profils = [
            ('ordinaire', {}, None),
            ('staff_seul', {'is_staff': True}, None),
            ('superutilisateur', {'is_superuser': True}, None),
            ('groupe_dev', {}, 'dev'),
            ('groupe_developpeur', {}, 'developpeur'),
        ]
        for nom, attributs, groupe in profils:
            user = User.objects.create_user(nom, password='x', **attributs)
            if groupe:
                user.groups.add(Group.objects.get_or_create(name=groupe)[0])
            visible = self.MODELE in self._options(self._ouvrir(user))
            self.assertEqual(visible, subscription_allowed(user),
                             f"écran et garde divergent pour « {nom} »")


class AFailureMustBeReadableTests(TestCase):
    """Le MESSAGE d'échec, pas la télémétrie (mesuré le 2026-09-23).

    Un appel réel a échoué le 22/09 depuis Discord ; l'utilisateur a reçu
    `Claude Code a échoué (code 1) : {"duration_api_ms":0,"stop_reason":"stop_sequence",…` —
    la raison était au-delà des 500 caractères conservés, dans le champ `result`. Le petit
    modèle local a lu ce charabia comme une impossibilité et a répondu « je ne peux pas
    lancer Claude Code », après l'avoir lancé. *Une erreur illisible se propage en fausse
    incapacité.*"""

    def _failure(self, stdout='', stderr='', code=1):
        from wama.common.services.claude_code import _failure_message
        return _failure_message(code, stdout, stderr)

    def test_the_reason_is_extracted_from_the_json_however_deep_in_the_output(self):
        import json
        raw = json.dumps({
            'duration_api_ms': 0, 'stop_reason': 'stop_sequence',
            'session_id': 'x' * 400,
            'usage': {'input_tokens': 0, 'output_tokens': 0},
            'is_error': True, 'subtype': 'error_during_execution',
            'result': "Claude AI usage limit reached",
        })
        message = self._failure(stdout=raw)
        self.assertIn('Claude AI usage limit reached', message)
        self.assertNotIn('duration_api_ms', message)

    def test_without_a_result_the_failure_family_is_still_named(self):
        import json
        message = self._failure(stdout=json.dumps({'subtype': 'error_max_turns',
                                                 'api_error_status': 429, 'result': ''}))
        self.assertIn('error_max_turns', message)
        self.assertIn('429', message)

    def test_a_non_json_or_empty_output_falls_back_to_stderr(self):
        self.assertIn('commande introuvable',
                      self._failure(stdout='', stderr='commande introuvable'))
        self.assertIn('bruit', self._failure(stdout='bruit', stderr=''))
        self.assertIn('aucun détail', self._failure())

    def test_the_tool_hands_that_message_to_the_assistant(self):
        """Contre-épreuve de bout en bout : c'est bien CE texte que le modèle reçoit."""
        from unittest.mock import patch

        from wama.tool_api import ask_claude_code

        user = User.objects.create(username='dev-legible', is_superuser=True)
        with patch('wama.common.services.claude_code.demander',
                   return_value={'success': False, 'error': 'Claude Code a échoué (code 1) : '
                                                            'Claude AI usage limit reached'}):
            result = ask_claude_code(user, 'audite le dépôt')
        self.assertIn('usage limit reached', result.get('error', ''))


@override_settings(SECRET_KEY='k' * 50, SECRET_KEY_FALLBACKS=[])
class SubscriptionModelsTests(TestCase):
    """L'abonnement a PLUSIEURS modèles, et dit lequel a répondu (2026-10-04).

    Question de Fabien : « en abonnement je n'ai accès qu'à un seul modèle et je ne sais même pas
    lequel ». La source déclarait une ligne unique, et l'identifiant choisi au sélecteur était
    abandonné avant l'appel. Les modèles sont les ALIAS du CLI (`claude --model`), DÉCLARÉS sur
    la source ; le modèle réellement servi se lit dans la réponse du CLI.
    Aucun réseau, aucun CLI : `subprocess.run` est remplacé par un double.
    """

    ANSWER = ('{"result": "ok", "total_cost_usd": 0.03, "duration_ms": 1200, "modelUsage": {'
              '"claude-haiku-4-5": {"outputTokens": 12}, "claude-opus-5-5": {"outputTokens": 480}}}')

    def _run_cli(self, **kwargs):
        from unittest.mock import Mock
        from wama.common.services import claude_code
        done = Mock(returncode=0, stdout=self.ANSWER, stderr='')
        with patch.object(claude_code, 'chemin_cli', return_value='claude'), \
                patch.object(claude_code.subprocess, 'run', return_value=done) as run:
            result = claude_code.demander('question', **kwargs)
        return result, run

    def test_the_source_lists_the_aliases_of_the_cli(self):
        from wama.common.services.claude_code import declared_model_ids
        self.assertEqual(('default', 'fable', 'opus', 'sonnet'), declared_model_ids())

    def test_a_chosen_alias_reaches_the_cli(self):
        result, run = self._run_cli(model='opus')
        command = run.call_args.args[0]
        self.assertEqual(['--model', 'opus'], command[command.index('--model'):][:2])
        self.assertTrue(result['success'])

    def test_the_default_model_lets_the_cli_choose(self):
        """Contre-épreuve : « défaut » (ou rien) ne passe aucun `--model` — le comportement d'avant."""
        for model in ('default', ''):
            _result, run = self._run_cli(model=model)
            self.assertNotIn('--model', run.call_args.args[0], repr(model))

    def test_an_undeclared_model_never_reaches_the_cli(self):
        result, run = self._run_cli(model='claude-opus-5-5; rm -rf /')
        self.assertFalse(result['success'])
        self.assertIn('non déclaré', result['error'])
        run.assert_not_called()

    def test_the_served_model_is_read_from_the_answer(self):
        from wama.common.services.claude_code import _lire_sortie
        result, _run = self._run_cli(model='opus')
        self.assertEqual('claude-opus-5-5', result['modele'], 'celui qui a produit le plus de texte')
        # Une réponse qui ne le dit pas ne fait rien inventer.
        self.assertEqual('', _lire_sortie('{"result": "ok"}')['modele'])

    def test_the_turn_label_names_the_model_that_really_answered(self):
        fabien = User.objects.create(username='fabien_models', is_superuser=True)
        with patch('wama.common.services.claude_code.demander',
                   return_value={'success': True, 'texte': 'réponse', 'cout_usd': 0.03,
                                 'modele': 'claude-opus-5-5'}) as cli:
            result = run_assistant_turn(fabien, 'bonjour', provider='claude-abo', model='opus')
        self.assertEqual('opus', cli.call_args.kwargs['model'])
        self.assertEqual('claude-abo (opus → claude-opus-5-5)', result['model'])

    def test_a_silent_answer_keeps_the_plain_label(self):
        fabien = User.objects.create(username='fabien_silent', is_superuser=True)
        with patch('wama.common.services.claude_code.demander',
                   return_value={'success': True, 'texte': 'réponse', 'cout_usd': None}):
            result = run_assistant_turn(fabien, 'bonjour', provider='claude-abo', model='opus')
        self.assertEqual('claude-abo (opus)', result['model'])

    def test_every_declared_model_enters_the_catalogue_with_its_origin(self):
        from wama.accounts.models import UserApiKey
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.cloud_models import refresh_key
        from wama.model_manager.tests.tests_cloud_models import _sync_cloud_seul
        user = User.objects.create(username='abo_catalogue', is_superuser=True)
        _sync_cloud_seul(self)
        row = UserApiKey.objects.create(user=user, source='claude_code', api_key='jeton')
        with patch('requests.get') as network:
            self.assertEqual((4, ''), refresh_key(row))
        network.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(['claude_code:default', 'claude_code:fable', 'claude_code:opus',
                          'claude_code:sonnet'], sorted(row.open_models))
        opus = AIModel.objects.get(model_key='claude_code:opus')
        self.assertEqual('Claude Code — Opus', opus.name)
        self.assertIn('alias « opus »', opus.description)
        self.assertEqual('Cloud commercial · Claude Code (abonnement) · abonnement', opus.origin_label)
