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


def _simulated_reply(user, message, **kw):
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
        reply = core.handle_message(self._msg('!aide'))
        self.assertIn('!lier', reply.text)

    def test_inconnu_invite_a_se_lier_et_le_moteur_n_est_jamais_appele(self):
        """⚠ Un inconnu ne doit JAMAIS être servi « en anonyme ».

        C'est le piège mesuré sur `/filemanager/api/upload/`, dont le `get_user()` retombait
        silencieusement sur l'utilisateur anonyme partagé : le traitement réussissait, au
        mauvais nom. Ici, l'absence de compte est une FIN de parcours.
        """
        with patch('wama.common.services.assistant_engine.run_assistant_turn') as moteur:
            reply = core.handle_message(self._msg('transcris ce fichier'))
        self.assertIn('!lier', reply.text)
        self.assertTrue(reply.private)
        moteur.assert_not_called()

    def test_code_rendu_en_prive(self):
        reply = core.handle_message(self._msg('!lier'))
        self.assertTrue(reply.private, "le code ne doit JAMAIS être publié dans un salon")
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        self.assertIn(lien.code, reply.text)

    def test_apres_liaison_le_moteur_recoit_le_bon_compte(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=_simulated_reply) as moteur:
            reply = core.handle_message(self._msg('bonjour'))
        self.assertEqual(reply.text, 'reponse simulee')
        self.assertEqual(moteur.call_args.args[0], self.user)

    def test_piece_jointe_deposee_et_annoncee(self):
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.user, lien.code)
        piece = core.Attachment(name='note.txt', content=b'contenu')
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=_simulated_reply) as moteur:
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
            reply = core.handle_message(self._msg('coucou'))
        self.assertIn('panne simulee', reply.text)

    def test_exception_imprevue_ne_fait_pas_planter_le_bot(self):
        """Un bot qui plante sur UN message cesse de servir TOUS les autres."""
        lien = request_link(CANAL, EXT_ID)
        confirm_link(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=RuntimeError('boum')):
            reply = core.handle_message(self._msg('coucou'))
        self.assertIn('erreur interne', reply.text.lower())


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
        reply = self._lier()
        self.assertEqual(reply.attachments, [])
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        self.assertIn(lien.code, reply.text)

    @override_settings(WAMA_PUBLIC_URL='https://wama.exemple.fr')
    def test_avec_url_publique_un_qr_scannable_accompagne_le_code(self):
        import cv2
        import numpy as np
        from django.urls import reverse

        reply = self._lier()
        self.assertTrue(reply.private, "le QR est aussi secret que le code")
        self.assertEqual(len(reply.attachments), 1)

        # Décodé comme le ferait un smartphone : la cible est la page de profil avec le
        # code prérempli — et rien d'autre (pas de jeton, pas de connexion automatique).
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        image = cv2.imdecode(np.frombuffer(reply.attachments[0].content, np.uint8),
                             cv2.IMREAD_GRAYSCALE)
        contenu, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
        self.assertEqual(
            contenu,
            f"https://wama.exemple.fr{reverse('accounts:profile')}?link_code={lien.code}")

    @override_settings(WAMA_PUBLIC_URL='https://wama.exemple.fr')
    def test_le_qr_absent_ne_prive_jamais_du_code(self):
        """Le QR est un confort, jamais le chemin : segno cassé → le code texte part."""
        with patch('wama.common.utils.qr.qr_png', side_effect=RuntimeError('boum')):
            reply = self._lier()
        self.assertEqual(reply.attachments, [])
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        self.assertIn(lien.code, reply.text)


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

    def _envoyer(self, sent_text):
        return core.handle_message(core.IncomingMessage(
            channel=CANAL, external_id=EXT_ID, text=sent_text))

    def test_le_geste_est_annonce_dans_l_aide(self):
        # Le trou du chantier était d'ERGONOMIE : un chemin que rien n'annonce n'existe pas.
        self.assertIn('!code', core.handle_message(core.IncomingMessage(
            channel=CANAL, external_id=EXT_ID, text='!aide')).text)

    def test_un_utilisateur_ordinaire_est_refuse_sans_atteindre_le_cli(self):
        self._lier(self.alice)
        with patch('wama.common.services.claude_code.demander') as cli:
            reply = self._envoyer('!code audite tout le dépôt')
        cli.assert_not_called()
        self.assertIn('⛔', reply.text)

    def test_un_admin_obtient_la_reponse_et_VOIT_le_cout(self):
        self._lier(self.fabien)
        with patch('wama.common.services.claude_code.demander',
                   return_value={'success': True, 'texte': 'la réponse',
                                 'cout_usd': 0.99, 'duree_ms': 3300}):
            reply = self._envoyer('!code où vit le nommage de sortie ?')
        self.assertIn('la réponse', reply.text)
        # Un chemin dont on ne voit jamais le prix finit par être pris pour du bavardage.
        self.assertIn('0.99', reply.text)

    def test_sans_question_le_geste_explique_son_usage(self):
        self._lier(self.fabien)
        with patch('wama.common.services.claude_code.demander') as cli:
            reply = self._envoyer('!code')
        cli.assert_not_called()
        self.assertIn('Usage', reply.text)

    def test_le_geste_n_est_pas_offert_a_un_inconnu(self):
        """L'appariement reste la première garde : un inconnu ne franchit rien."""
        with patch('wama.common.services.claude_code.demander') as cli:
            reply = self._envoyer('!code audite le dépôt')
        cli.assert_not_called()
        self.assertIn('!lier', reply.text)


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
    `Reply.files` n'était JAMAIS rempli, le code d'envoi de l'adaptateur était mort).

    ⚠⚠ CES TESTS ONT ATTESTÉ UNE FORME QUI N'EXISTE PAS, du 29/08 au 2026-09-23. Ils
    posaient `{'output_urls': [...]}` à PLAT, quand les dix `get_<app>_status` rendent
    `{'jobs': [{…, 'output_url': …}]}` (`tool_api.py:320-328` pour l'anonymizer,
    `:503-512` pour l'imager). Verts, ils couvraient un correctif qui n'avait rien
    corrigé : en Discord, un « quel est le statut ? » n'a jamais rapporté de fichier.
    La forme ci-dessous est désormais COPIÉE de ces fonctions, jamais réinventée."""

    def _creer_media(self, rel):
        from pathlib import Path
        from django.conf import settings
        file_path = Path(settings.MEDIA_ROOT) / rel
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b'contenu')
        self.addCleanup(file_path.unlink)
        return file_path

    def test_the_real_get_status_shape_does_carry_the_output(self):
        """La forme MESURÉE : la sortie vit sous `jobs[]`, pas à la racine du résultat."""
        self._creer_media('gateway_tests/sortie.png')
        self._creer_media('gateway_tests/sortie.wav')
        result = {'tool_steps': [
            # `get_imager_status` — tool_api.py:503-512
            {'tool': 'get_imager_status', 'result': {'jobs': [
                {'id': 42, 'status': 'SUCCESS',
                 'output_urls': ['/media/gateway_tests/sortie.png',
                                 'https://exemple.org/ailleurs.png'],
                 'video_url': None},
            ]}},
            # `get_synthesizer_status` — même forme, clé `audio_url`
            {'tool': 'get_synthesizer_status', 'result': {'jobs': [
                {'id': 7, 'status': 'done', 'audio_url': '/media/gateway_tests/sortie.wav'},
            ]}},
            {'tool': 'search_web', 'result': {'results': []}},
        ]}
        files = core._produced_files(result)[0]
        self.assertEqual(files, ['gateway_tests/sortie.png', 'gateway_tests/sortie.wav'])

    def test_only_the_most_recent_job_travels_back(self):
        """Les `get_<app>_status` rendent les DIX derniers jobs (tri `-id`). Republier les
        anciens renverrait à chaque question de statut des sorties déjà récupérées."""
        self._creer_media('gateway_tests/recent.jpg')
        self._creer_media('gateway_tests/ancien.jpg')
        result = {'tool_steps': [
            {'tool': 'get_anonymizer_status', 'result': {'jobs': [
                {'id': 647, 'status': 'done', 'output_url': '/media/gateway_tests/recent.jpg'},
                {'id': 646, 'status': 'done', 'output_url': '/media/gateway_tests/ancien.jpg'},
            ]}},
        ]}
        self.assertEqual(core._produced_files(result)[0], ['gateway_tests/recent.jpg'])

    def test_the_output_of_the_real_get_imager_status_travels_back(self):
        """LA mesure — celle qui manquait. Aucune forme écrite à la main ici : on crée un
        item, on appelle l'outil RÉEL, et on vérifie que la passerelle y voit le fichier.
        C'est le seul test que la forme des outils ne peut pas contourner."""
        from django.contrib.auth.models import User

        from wama.imager.models import ImageGeneration
        from wama.tool_api import get_imager_status

        path = self._creer_media('gateway_tests/rendu.png')
        user = User.objects.create(username='mesureuse')
        ImageGeneration.objects.create(user=user, prompt='un chat', status='SUCCESS',
                                       generated_images=[str(path)])

        result = {'tool_steps': [{'tool': 'get_imager_status',
                                    'result': get_imager_status(user)}]}
        self.assertEqual(core._produced_files(result)[0], ['gateway_tests/rendu.png'])

    def test_a_flat_shape_still_works(self):
        """Contre-épreuve : les outils qui rendent l'URL à la racine ne régressent pas."""
        self._creer_media('gateway_tests/plat.png')
        result = {'tool_steps': [
            {'tool': 'x', 'result': {'file_url': '/media/gateway_tests/plat.png'}}]}
        self.assertEqual(core._produced_files(result)[0], ['gateway_tests/plat.png'])

    def test_une_traversee_hors_media_root_est_ignoree(self):
        outcome = {'tool_steps': [{'tool': 'x', 'result': {
            'file_url': '/media/../wama/settings.py'}}]}
        self.assertEqual(core._produced_files(outcome)[0], [])

    def test_un_fichier_inexistant_ou_un_resultat_non_dict_ne_cassent_rien(self):
        outcome = {'tool_steps': [
            {'tool': 'x', 'result': {'file_url': '/media/gateway_tests/absent.png'}},
            {'tool': 'y', 'result': 'erreur en chaîne'},
        ]}
        self.assertEqual(core._produced_files(outcome)[0], [])


class SurfaceThatAttachesFilesIsDeclaredTests(TestCase):
    """Le moteur d'assistant ne dit à un canal « tes fichiers repartent joints » que si sa
    surface est DÉCLARÉE (`assistant_engine.SURFACES_WITH_ATTACHMENTS`). Un adaptateur
    ajouté sans y être inscrit ferait retomber l'assistant dans le refus mesuré le 23/09
    (« je ne peux pas envoyer de fichiers par Discord »), sans rien casser d'autre — donc
    sans que rien ne le signale. Ce test est ce signal."""

    def test_the_discord_adapter_channel_is_declared(self):
        from wama.common.services.assistant_engine import surface_attaches_files
        from wama.gateway.adapters.discord_bot import CANAL
        self.assertIn(CANAL, core.CHANNELS)
        self.assertTrue(surface_attaches_files(CANAL))

    def test_the_engine_reads_the_gateway_list_it_keeps_none_of_its_own(self):
        """Le moteur ne redeclare pas les canaux : un canal ajoute a la passerelle DOIT
        suffire. Sans cela, l'assistant continuerait de dire a ses utilisateurs Matrix qu'il
        ne peut pas leur envoyer de fichier."""
        from wama.common.services.assistant_engine import surface_attaches_files
        with patch.object(core, 'CHANNELS', ('discord', 'matrix')):
            self.assertTrue(surface_attaches_files('matrix'))
        self.assertFalse(surface_attaches_files('web'))
        self.assertFalse(surface_attaches_files('api'))

    def test_the_instruction_is_added_only_on_a_channel_surface(self):
        """Contre-épreuve : le web, lui, ne joint rien — il ne doit pas l'annoncer."""
        from wama.common.services import assistant_engine

        seen = {}

        def _fake_call(messages, *args, **kwargs):
            seen['system'] = messages[0]['content']
            return 'ok', {}

        user = User.objects.create(username='surface')
        with patch.object(assistant_engine, '_llm_call', _fake_call):
            assistant_engine.run_assistant_turn(user, 'bonjour', provider='ollama',
                                                model='m', surface='discord')
            self.assertIn('attached to your reply automatically', seen['system'].lower())
            assistant_engine.run_assistant_turn(user, 'bonjour', provider='ollama',
                                                model='m', surface='web')
            self.assertNotIn('attached to your reply automatically', seen['system'].lower())


class FileTooLargeTests(TestCase):
    """Un fichier que le canal ne peut pas porter doit être DIT, pas écarté en silence.

    MESURÉ le 2026-09-27 (question de Fabien sur le lien de téléchargement) : au-delà du
    plafond, `_produced_files` écartait le fichier sans un mot. Pour une image le cas est
    théorique ; **pour une vidéo anonymisée c'est le cas NORMAL** — l'utilisateur recevait
    « c'est terminé », sans pièce jointe et sans explication.
    ⭐ *Ce qui ne plante pas ne se signale pas.*
    """

    def _creer_media(self, rel, octets):
        from pathlib import Path
        from django.conf import settings
        file_path = Path(settings.MEDIA_ROOT) / rel
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b'\0' * octets)
        self.addCleanup(file_path.unlink)
        return file_path

    def _result(self, url):
        return {'tool_steps': [{'tool': 'get_anonymizer_status',
                                'result': {'jobs': [{'id': 1, 'output_url': url}]}}]}

    def test_an_oversized_output_is_reported_instead_of_vanishing(self):
        self._creer_media('gateway_tests/gros.mp4', core._MAX_OUTPUT_BYTES + 1)
        files, oversized = core._produced_files(
            self._result('/media/gateway_tests/gros.mp4'))
        self.assertEqual([], files)
        self.assertEqual(1, len(oversized))
        self.assertEqual('gros.mp4', oversized[0][0])

    def test_the_reply_says_it_in_words(self):
        """Contre-épreuve de bout en bout : c'est l'utilisateur qui doit l'apprendre."""
        from unittest.mock import patch

        from wama.gateway.models import ChannelLink
        self._creer_media('gateway_tests/lourd.mp4', core._MAX_OUTPUT_BYTES + 1)
        user = User.objects.create(username='gros-fichier')
        ChannelLink.objects.create(user=user, channel=CANAL, external_id='999',
                                   confirmed_at=timezone.now())
        # Le moteur est patché à SA source : `core` l'importe tardivement, il n'en est pas
        # un attribut (même geste que les autres gardes de ce fichier).
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   return_value={'success': True, 'response': "C'est terminé.",
                                 'model': 'test', 'usage': {},
                                 'tool_steps': self._result(
                                     '/media/gateway_tests/lourd.mp4')['tool_steps']}):
            reply = core.handle_message(core.IncomingMessage(
                channel=CANAL, external_id='999', text='où est ma vidéo ?'))
        self.assertIn('Trop volumineux', reply.text)
        self.assertIn('lourd.mp4', reply.text)
        self.assertEqual([], reply.files)

    def test_a_file_within_the_ceiling_travels_and_says_nothing(self):
        """Contre-épreuve : le cas normal ne doit pas hériter d'un avertissement."""
        self._creer_media('gateway_tests/leger.jpg', 1024)
        files, oversized = core._produced_files(
            self._result('/media/gateway_tests/leger.jpg'))
        self.assertEqual(['gateway_tests/leger.jpg'], files)
        self.assertEqual([], oversized)


class OriginalFileCaptionTests(TestCase):
    """La légende qui porte le lien vers l'ORIGINAL (2026-09-27, mesure de Fabien).

    Il enregistre l'image depuis le fil et obtient un **webp de 75 Ko** là où WAMA a envoyé un
    **JPEG de 445 203 octets** : ce qu'on enregistre depuis l'aperçu est le proxy d'images de
    Discord. L'original est la pièce jointe, et son URL n'existe qu'APRÈS le téléversement.
    ⭐ *Un aperçu et un fichier se ressemblent à l'écran et ne pèsent pas la même chose.*

    C'est aussi le « lien de téléchargement » qui manquait : il ne demande ni URL publique de
    WAMA, ni de faire circuler un secret dans une messagerie.
    """

    class _Piece:
        url = 'https://cdn.discordapp.com/attachments/1/2/sortie.jpg?ex=abc'

    class _Message:
        def __init__(self, attachments):
            self.attachments = attachments
            self.content = None

        async def edit(self, content=None):
            self.content = content

    def _file(self, octets=445203):
        from pathlib import Path
        from django.conf import settings
        file_path = Path(settings.MEDIA_ROOT) / 'gateway_tests' / 'sortie.jpg'
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(b'\0' * octets)
        self.addCleanup(file_path.unlink)
        return file_path

    def _legender(self, message, file_path):
        import asyncio

        from wama.gateway.adapters.discord_bot import _caption_original
        asyncio.run(_caption_original(message, file_path))
        return message.content

    def test_the_caption_carries_the_attachment_url_its_size_and_the_warning(self):
        message = self._Message([self._Piece()])
        sent_text = self._legender(message, self._file())
        self.assertIn(self._Piece.url, sent_text)
        self.assertIn('sortie.jpg', sent_text)
        self.assertIn('0.4 Mo', sent_text)
        self.assertIn('compressée', sent_text, "l'utilisateur doit savoir que l'aperçu ment")

    def test_a_message_without_attachment_is_left_alone(self):
        """Contre-épreuve : rien à légender ne doit pas produire une légende vide."""
        message = self._Message([])
        self.assertIsNone(self._legender(message, self._file()))

    def test_a_failed_edit_never_costs_the_attachment(self):
        """La pièce jointe est DÉJÀ partie : une légende qui échoue ne doit rien emporter."""
        class _Rate(self._Message):
            async def edit(self, content=None):
                raise RuntimeError('discord indisponible')

        message = _Rate([self._Piece()])
        self._legender(message, self._file())      # ne lève pas
        self.assertIsNone(message.content)


class ForgetGestureTests(TestCase):
    """`!oublier` — repartir d'un fil vierge (2026-10-05).

    Un fil où une fabrication est entrée la resservait au modèle à chaque tour (fil Discord
    n° 11, `WAMA_LLM.md` §2026-10-05). Le geste efface CE fil — pas les autres fils de la
    personne, jamais ceux d'autrui — par la même brique que « Effacer » du chat web.
    """

    def setUp(self):
        from wama.common.services import conversation_store as store
        self.store = store
        self.user = User.objects.create(username='fabien')
        confirm_link(self.user, request_link(CANAL, EXT_ID).code)

    def _msg(self, text, thread='salon-1'):
        return core.IncomingMessage(channel=CANAL, external_id=EXT_ID, text=text, thread=thread)

    def _record(self, user, thread_key, surface=CANAL):
        fil = self.store.thread(user, surface=surface, thread_key=thread_key)
        self.store.record_exchange(fil, 'statut ?', {'response': 'La tâche 649 est terminée.'})
        return fil

    def test_the_gesture_is_announced_in_the_help(self):
        self.assertIn('!oublier', core.handle_message(self._msg('!aide')).text)

    def test_forget_erases_this_thread_only(self):
        from wama.common.models import Conversation
        here = self._record(self.user, 'salon-1')
        elsewhere = self._record(self.user, 'salon-2')
        web = self._record(self.user, '', surface='web')
        with patch('wama.common.services.assistant_engine.run_assistant_turn') as moteur:
            reply = core.handle_message(self._msg('!oublier'))
        moteur.assert_not_called()
        self.assertIn('effacée', reply.text)
        self.assertFalse(Conversation.objects.filter(pk=here.pk).exists())
        self.assertTrue(Conversation.objects.filter(pk__in=[elsewhere.pk, web.pk]).count() == 2)

    def test_the_next_turn_starts_without_history(self):
        self._record(self.user, 'salon-1')
        core.handle_message(self._msg('!oublier'))
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=_simulated_reply) as moteur:
            core.handle_message(self._msg('bonjour'))
        self.assertEqual([], moteur.call_args.kwargs['history'])

    def test_someone_else_s_thread_with_the_same_key_is_untouched(self):
        from wama.common.models import Conversation
        other = self._record(User.objects.create(username='alice'), 'salon-1')
        core.handle_message(self._msg('!oublier'))
        self.assertTrue(Conversation.objects.filter(pk=other.pk).exists())

    def test_nothing_to_forget_is_said(self):
        self.assertIn('rien à effacer', core.handle_message(self._msg('!oublier')).text)

    def test_an_unknown_person_forgets_nothing(self):
        """La garde d'identité passe AVANT le geste : un inconnu n'efface rien."""
        from wama.common.models import Conversation
        mine = self._record(self.user, 'salon-1')
        reply = core.handle_message(core.IncomingMessage(
            channel=CANAL, external_id='999', text='!oublier', thread='salon-1'))
        self.assertIn('!lier', reply.text)
        self.assertTrue(Conversation.objects.filter(pk=mine.pk).exists())
