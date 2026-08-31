"""
Passerelle de canaux — tests des GARDES (ROADMAP §19).

POURQUOI CES TESTS SONT VERSIONNÉS, ET PAS RESTÉS DES SCRIPTS DE VALIDATION. Ils ont
d'abord été écrits comme harnais jetables ; le 2026-08-21 le répertoire temporaire qui les
portait a été nettoyé et ils ont disparu — le même jour où deux éditions de fichiers
partagés étaient silencieusement écrasées par une autre instance. Or ce qu'ils vérifient
n'est pas du confort : ce sont les propriétés de SÉCURITÉ de la passerelle (un inconnu
n'obtient rien, un code ne sert qu'une fois, on ne délie pas le fil d'autrui). Une propriété
de sécurité qui n'est prouvée que par un script volatil n'est pas protégée contre les
régressions — elle attend juste qu'on la casse sans le voir.

Lancer : `python manage.py test wama.gateway` (venv WSL).

Aucun réseau, aucun LLM, aucune charge GPU : le moteur d'assistant est remplacé par un
double, et aucun adaptateur de canal n'est instancié.
"""

import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from wama.gateway import core
from wama.gateway.models import CODE_TTL, MAX_TENTATIVES, ChannelLink
from wama.gateway.services import (
    PairingError,
    account_for,
    confirm_link,
    unlink,
    request_link,
)

CANAL, EXT_ID = 'discord', '111222333'


class AppariementTests(TestCase):
    """L'appariement d'identité : le canal PROPOSE, WAMA DISPOSE."""

    def setUp(self):
        self.alice = User.objects.create(username='alice')
        self.mallory = User.objects.create(username='mallory')

    def test_sans_liaison_aucun_compte(self):
        self.assertIsNone(account_for(CANAL, EXT_ID))

    def test_cycle_nominal(self):
        lien = request_link(CANAL, EXT_ID, 'Fabien')
        self.assertEqual(len(lien.code), 8)
        self.assertFalse(lien.is_confirmed)
        # Tant que WAMA n'a pas tranché, la passerelle ne connaît personne.
        self.assertIsNone(account_for(CANAL, EXT_ID))

        confirm_link(self.alice, lien.code)
        self.assertEqual(account_for(CANAL, EXT_ID), self.alice)

    def test_le_compte_lie_est_celui_qui_saisit_le_code(self):
        """La propriété de sécurité centrale : un code volé ne donne AUCUN accès.

        Celui qui saisit le code lie le canal à SON PROPRE compte — il ne prend donc rien
        à personne. C'est ce qui rend le code inoffensif s'il circule dans une discussion.
        """
        lien = request_link(CANAL, EXT_ID, 'Fabien')
        confirm_link(self.mallory, lien.code)          # Mallory intercepte le code
        self.assertEqual(account_for(CANAL, EXT_ID), self.mallory)
        # …et n'a obtenu aucun accès au compte d'Alice.
        self.assertFalse(ChannelLink.objects.filter(user=self.alice).exists())

    def test_code_a_usage_unique(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.alice, lien.code)
        with self.assertRaises(PairingError):
            confirm_link(self.mallory, lien.code)

    def test_identite_deja_liee_non_reappropriable(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.alice, lien.code)
        with self.assertRaises(PairingError):
            request_link(CANAL, EXT_ID)

    def test_code_inconnu_refuse(self):
        with self.assertRaises(PairingError):
            confirm_link(self.alice, 'ZZZZZZZZ')

    def test_demande_pilonnee_meurt_meme_avec_le_bon_code(self):
        lien = request_link(CANAL, EXT_ID)
        ChannelLink.objects.filter(pk=lien.pk).update(tentatives=MAX_TENTATIVES)
        with self.assertRaises(PairingError):
            confirm_link(self.alice, lien.code)

    def test_code_expire_refuse(self):
        lien = request_link(CANAL, EXT_ID)
        ChannelLink.objects.filter(pk=lien.pk).update(
            created_at=timezone.now() - CODE_TTL - timedelta(minutes=1))
        with self.assertRaises(PairingError):
            confirm_link(self.alice, lien.code)

    def test_redemande_donne_un_code_neuf_et_remet_le_compteur(self):
        lien = request_link(CANAL, EXT_ID)
        ChannelLink.objects.filter(pk=lien.pk).update(tentatives=3)
        neuf = request_link(CANAL, EXT_ID)
        self.assertNotEqual(neuf.code, lien.code)
        self.assertEqual(neuf.tentatives, 0)

    def test_canal_inconnu_refuse(self):
        with self.assertRaises(PairingError):
            request_link('telegram', 'x')

    def test_delier_seulement_les_siennes(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.alice, lien.code)

        self.assertFalse(unlink(self.mallory, CANAL, EXT_ID))
        self.assertEqual(account_for(CANAL, EXT_ID), self.alice)   # intacte

        self.assertTrue(unlink(self.alice, CANAL, EXT_ID))
        self.assertIsNone(account_for(CANAL, EXT_ID))


def _reponse_simulee(user, message, **kw):
    """Double du moteur : on teste le CŒUR de la passerelle, pas le LLM."""
    return {'success': True, 'response': 'reponse simulee', 'model': 'faux:1b',
            'tool_steps': []}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='wama-test-gateway-'))
class CoeurPasserelleTests(TestCase):
    """
    `handle_message` — ce que la passerelle décide, indépendamment du protocole.

    ⚠ `MEDIA_ROOT` est REDIRIGÉ vers un répertoire temporaire. Sans cette redirection, le
    test de pièce jointe écrit dans le média RÉEL de l'instance : chaque exécution y laissait
    un fichier, et Django renommait le suivant (`note_iN8GAGE.txt`) pour éviter la collision
    — ce qui a fait échouer le test au deuxième passage. Un test qui pollue le disque de
    production est un défaut, pas un détail : il rend aussi le résultat dépendant de
    l'historique des exécutions.
    """

    def setUp(self):
        self.user = User.objects.create(username='fabien')

    def _msg(self, text='', pieces=None, thread='salon-1'):
        return core.IncomingMessage(channel=CANAL, external_id=EXT_ID, external_label='Fabien',
                                   text=text, thread=thread, attachments=pieces or [])

    def test_aide_sans_identite(self):
        reponse = core.handle_message(self._msg('!aide'))
        self.assertIn('!lier', reponse.text)

    def test_inconnu_invite_a_se_lier_et_le_moteur_n_est_jamais_appele(self):
        """⚠ Un inconnu ne doit JAMAIS être servi « en anonyme ».

        C'est le piège mesuré sur `/filemanager/api/upload/`, dont le `get_user()` retombait
        silencieusement sur l'utilisateur anonyme partagé : le traitement réussissait, au
        mauvais nom. Ici, l'absence de compte est une FIN de parcours.
        """
        with patch('wama.common.services.assistant_engine.run_assistant_turn') as moteur:
            reponse = core.handle_message(self._msg('transcris ce fichier'))
        self.assertIn('!lier', reponse.text)
        self.assertTrue(reponse.private)
        moteur.assert_not_called()

    def test_code_rendu_en_prive(self):
        reponse = core.handle_message(self._msg('!lier'))
        self.assertTrue(reponse.private, "le code ne doit JAMAIS être publié dans un salon")
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        self.assertIn(lien.code, reponse.text)

    def test_apres_liaison_le_moteur_recoit_le_bon_compte(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=_reponse_simulee) as moteur:
            reponse = core.handle_message(self._msg('bonjour'))
        self.assertEqual(reponse.text, 'reponse simulee')
        self.assertEqual(moteur.call_args.args[0], self.user)

    def test_piece_jointe_deposee_et_annoncee(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.user, lien.code)
        piece = core.Attachment(name='note.txt', content=b'contenu')
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=_reponse_simulee) as moteur:
            core.handle_message(self._msg('transcris', pieces=[piece]))
        invite = moteur.call_args.args[1]
        self.assertIn('Fichiers déposés', invite)
        # Le CHEMIN déposé, pas le nom d'origine : le stockage peut suffixer le fichier en
        # cas de collision (`note_iN8GAGE.txt`). Ce qui compte est que l'assistant reçoive
        # un chemin exploitable dans l'espace de l'utilisateur.
        self.assertIn(f'users/{self.user.id}/temp/note', invite)
        self.assertIn('.txt`]', invite)

    def test_erreur_moteur_ne_fait_pas_planter_le_bot(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   return_value={'error': 'panne simulee'}):
            reponse = core.handle_message(self._msg('coucou'))
        self.assertIn('panne simulee', reponse.text)

    def test_exception_imprevue_ne_fait_pas_planter_le_bot(self):
        """Un bot qui plante sur UN message cesse de servir TOUS les autres."""
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=RuntimeError('boum')):
            reponse = core.handle_message(self._msg('coucou'))
        self.assertIn('erreur interne', reponse.text.lower())


class QrAppariementTests(TestCase):
    """Le QR joint au code d'appariement — un confort qui ne change RIEN au modèle
    « le canal propose, WAMA dispose » : il encode la page de profil code prérempli,
    jamais un jeton qui connecterait le scanneur."""

    def _lier(self):
        return core.handle_message(core.IncomingMessage(
            channel=CANAL, external_id=EXT_ID, text='!lier'))

    @override_settings(WAMA_PUBLIC_URL='')
    def test_sans_url_publique_le_code_part_seul(self):
        """Un QR pointant sur localhost échouerait sur le smartphone en accusant le
        mécanisme : sans URL publique, le comportement historique est conservé.

        ⚠ `override_settings`, PAS `os.environ` : la 1ʳᵉ version vidait l'environnement
        alors que `pairing_url` lisait `settings` en repli — le test était vert par
        accident et serait devenu ROUGE dès qu'on renseigne la variable pour de bon.
        Un test doit agir sur la source que le code lit VRAIMENT."""
        reponse = self._lier()
        self.assertEqual(reponse.attachments, [])
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        self.assertIn(lien.code, reponse.text)

    @override_settings(WAMA_PUBLIC_URL='https://wama.exemple.fr')
    def test_avec_url_publique_un_qr_scannable_accompagne_le_code(self):
        import cv2
        import numpy as np
        from django.urls import reverse

        reponse = self._lier()
        self.assertTrue(reponse.private, "le QR est aussi secret que le code")
        self.assertEqual(len(reponse.attachments), 1)

        # Décodé comme le ferait un smartphone : la cible est la page de profil avec le
        # code prérempli — et rien d'autre (pas de jeton, pas de connexion automatique).
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        image = cv2.imdecode(np.frombuffer(reponse.attachments[0].content, np.uint8),
                             cv2.IMREAD_GRAYSCALE)
        contenu, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
        self.assertEqual(
            contenu,
            f"https://wama.exemple.fr{reverse('accounts:profile')}?link_code={lien.code}")

    @override_settings(WAMA_PUBLIC_URL='https://wama.exemple.fr')
    def test_le_qr_absent_ne_prive_jamais_du_code(self):
        """Le QR est un confort, jamais le chemin : segno cassé → le code texte part."""
        with patch('wama.common.utils.qr.qr_png', side_effect=RuntimeError('boum')):
            reponse = self._lier()
        self.assertEqual(reponse.attachments, [])
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        self.assertIn(lien.code, reponse.text)


class GesteCodeTests(TestCase):
    """`!code` — le geste EXPLICITE de délégation au dépôt (correctif d'ergonomie §19.3).

    Il existe parce que le tour Discord part sur le fournisseur LOCAL : sans geste, ce
    serait à un PETIT modèle de décider d'appeler `ask_claude_code`. Le geste rend le
    chemin déterministe ET visible (`!aide` le liste)."""

    def setUp(self):
        self.fabien = User.objects.create(username='fabien', is_superuser=True)
        self.alice = User.objects.create(username='alice')

    def _lier(self, user):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(user, lien.code)

    def _envoyer(self, texte):
        return core.handle_message(core.IncomingMessage(
            channel=CANAL, external_id=EXT_ID, text=texte))

    def test_le_geste_est_annonce_dans_l_aide(self):
        # Le trou du chantier était d'ERGONOMIE : un chemin que rien n'annonce n'existe pas.
        self.assertIn('!code', core.handle_message(core.IncomingMessage(
            channel=CANAL, external_id=EXT_ID, text='!aide')).text)

    def test_un_utilisateur_ordinaire_est_refuse_sans_atteindre_le_cli(self):
        self._lier(self.alice)
        with patch('wama.common.services.claude_code.demander') as cli:
            reponse = self._envoyer('!code audite tout le dépôt')
        cli.assert_not_called()
        self.assertIn('⛔', reponse.text)

    def test_un_admin_obtient_la_reponse_et_VOIT_le_cout(self):
        self._lier(self.fabien)
        with patch('wama.common.services.claude_code.demander',
                   return_value={'success': True, 'texte': 'la réponse',
                                 'cout_usd': 0.99, 'duree_ms': 3300}):
            reponse = self._envoyer('!code où vit le nommage de sortie ?')
        self.assertIn('la réponse', reponse.text)
        # Un chemin dont on ne voit jamais le prix finit par être pris pour du bavardage.
        self.assertIn('0.99', reponse.text)

    def test_sans_question_le_geste_explique_son_usage(self):
        self._lier(self.fabien)
        with patch('wama.common.services.claude_code.demander') as cli:
            reponse = self._envoyer('!code')
        cli.assert_not_called()
        self.assertIn('Usage', reponse.text)

    def test_le_geste_n_est_pas_offert_a_un_inconnu(self):
        """L'appariement reste la première garde : un inconnu ne franchit rien."""
        with patch('wama.common.services.claude_code.demander') as cli:
            reponse = self._envoyer('!code audite le dépôt')
        cli.assert_not_called()
        self.assertIn('!lier', reponse.text)


class TronconnageDiscordTests(TestCase):
    """La limite de 2000 caractères de Discord est une limite DURE : la dépasser = 400."""

    def test_reponse_longue_decoupee(self):
        from wama.gateway.adapters.discord_bot import _chunk_text
        morceaux = _chunk_text('x' * 5000)
        self.assertEqual(len(morceaux), 3)
        self.assertTrue(all(len(m) <= 2000 for m in morceaux))

    def test_coupe_de_preference_sur_saut_de_ligne(self):
        from wama.gateway.adapters.discord_bot import _chunk_text
        morceaux = _chunk_text('ligne\n' * 500)
        self.assertTrue(all(len(m) <= 2000 for m in morceaux))
        self.assertTrue(all(not m.startswith('\n') for m in morceaux))


class FichiersProduitsTests(TestCase):
    """`_produced_files` — le retour des sorties d'outils vers le canal (correctif 29/08 :
    `Reply.files` n'était JAMAIS rempli, le code d'envoi de l'adaptateur était mort)."""

    def _creer_media(self, rel):
        from pathlib import Path
        from django.conf import settings
        chemin = Path(settings.MEDIA_ROOT) / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(b'contenu')
        self.addCleanup(chemin.unlink)
        return chemin

    def test_les_sorties_media_du_tour_repartent_et_les_autres_urls_non(self):
        self._creer_media('gateway_tests/sortie.png')
        self._creer_media('gateway_tests/sortie.wav')
        resultat = {'tool_steps': [
            {'tool': 'get_imager_status', 'result': {
                'output_urls': ['/media/gateway_tests/sortie.png',
                                'https://exemple.org/ailleurs.png']}},
            {'tool': 'get_synthesizer_status', 'result': {
                'audio_url': '/media/gateway_tests/sortie.wav'}},
            {'tool': 'search_web', 'result': {'results': []}},
        ]}
        fichiers = core._produced_files(resultat)
        self.assertEqual(fichiers, ['gateway_tests/sortie.png', 'gateway_tests/sortie.wav'])

    def test_une_traversee_hors_media_root_est_ignoree(self):
        resultat = {'tool_steps': [{'tool': 'x', 'result': {
            'file_url': '/media/../wama/settings.py'}}]}
        self.assertEqual(core._produced_files(resultat), [])

    def test_un_fichier_inexistant_ou_un_resultat_non_dict_ne_cassent_rien(self):
        resultat = {'tool_steps': [
            {'tool': 'x', 'result': {'file_url': '/media/gateway_tests/absent.png'}},
            {'tool': 'y', 'result': 'erreur en chaîne'},
        ]}
        self.assertEqual(core._produced_files(resultat), [])
