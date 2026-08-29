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
    ErreurAppariement,
    compte_pour,
    confirmer_liaison,
    delier,
    demander_liaison,
)

CANAL, EXT_ID = 'discord', '111222333'


class AppariementTests(TestCase):
    """L'appariement d'identité : le canal PROPOSE, WAMA DISPOSE."""

    def setUp(self):
        self.alice = User.objects.create(username='alice')
        self.mallory = User.objects.create(username='mallory')

    def test_sans_liaison_aucun_compte(self):
        self.assertIsNone(compte_pour(CANAL, EXT_ID))

    def test_cycle_nominal(self):
        lien = demander_liaison(CANAL, EXT_ID, 'Fabien')
        self.assertEqual(len(lien.code), 8)
        self.assertFalse(lien.est_confirmee)
        # Tant que WAMA n'a pas tranché, la passerelle ne connaît personne.
        self.assertIsNone(compte_pour(CANAL, EXT_ID))

        confirmer_liaison(self.alice, lien.code)
        self.assertEqual(compte_pour(CANAL, EXT_ID), self.alice)

    def test_le_compte_lie_est_celui_qui_saisit_le_code(self):
        """La propriété de sécurité centrale : un code volé ne donne AUCUN accès.

        Celui qui saisit le code lie le canal à SON PROPRE compte — il ne prend donc rien
        à personne. C'est ce qui rend le code inoffensif s'il circule dans une discussion.
        """
        lien = demander_liaison(CANAL, EXT_ID, 'Fabien')
        confirmer_liaison(self.mallory, lien.code)          # Mallory intercepte le code
        self.assertEqual(compte_pour(CANAL, EXT_ID), self.mallory)
        # …et n'a obtenu aucun accès au compte d'Alice.
        self.assertFalse(ChannelLink.objects.filter(user=self.alice).exists())

    def test_code_a_usage_unique(self):
        lien = demander_liaison(CANAL, EXT_ID)
        confirmer_liaison(self.alice, lien.code)
        with self.assertRaises(ErreurAppariement):
            confirmer_liaison(self.mallory, lien.code)

    def test_identite_deja_liee_non_reappropriable(self):
        lien = demander_liaison(CANAL, EXT_ID)
        confirmer_liaison(self.alice, lien.code)
        with self.assertRaises(ErreurAppariement):
            demander_liaison(CANAL, EXT_ID)

    def test_code_inconnu_refuse(self):
        with self.assertRaises(ErreurAppariement):
            confirmer_liaison(self.alice, 'ZZZZZZZZ')

    def test_demande_pilonnee_meurt_meme_avec_le_bon_code(self):
        lien = demander_liaison(CANAL, EXT_ID)
        ChannelLink.objects.filter(pk=lien.pk).update(tentatives=MAX_TENTATIVES)
        with self.assertRaises(ErreurAppariement):
            confirmer_liaison(self.alice, lien.code)

    def test_code_expire_refuse(self):
        lien = demander_liaison(CANAL, EXT_ID)
        ChannelLink.objects.filter(pk=lien.pk).update(
            created_at=timezone.now() - CODE_TTL - timedelta(minutes=1))
        with self.assertRaises(ErreurAppariement):
            confirmer_liaison(self.alice, lien.code)

    def test_redemande_donne_un_code_neuf_et_remet_le_compteur(self):
        lien = demander_liaison(CANAL, EXT_ID)
        ChannelLink.objects.filter(pk=lien.pk).update(tentatives=3)
        neuf = demander_liaison(CANAL, EXT_ID)
        self.assertNotEqual(neuf.code, lien.code)
        self.assertEqual(neuf.tentatives, 0)

    def test_canal_inconnu_refuse(self):
        with self.assertRaises(ErreurAppariement):
            demander_liaison('telegram', 'x')

    def test_delier_seulement_les_siennes(self):
        lien = demander_liaison(CANAL, EXT_ID)
        confirmer_liaison(self.alice, lien.code)

        self.assertFalse(delier(self.mallory, CANAL, EXT_ID))
        self.assertEqual(compte_pour(CANAL, EXT_ID), self.alice)   # intacte

        self.assertTrue(delier(self.alice, CANAL, EXT_ID))
        self.assertIsNone(compte_pour(CANAL, EXT_ID))


def _reponse_simulee(user, message, **kw):
    """Double du moteur : on teste le CŒUR de la passerelle, pas le LLM."""
    return {'success': True, 'response': 'reponse simulee', 'model': 'faux:1b',
            'tool_steps': []}


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='wama-test-gateway-'))
class CoeurPasserelleTests(TestCase):
    """
    `traiter_message` — ce que la passerelle décide, indépendamment du protocole.

    ⚠ `MEDIA_ROOT` est REDIRIGÉ vers un répertoire temporaire. Sans cette redirection, le
    test de pièce jointe écrit dans le média RÉEL de l'instance : chaque exécution y laissait
    un fichier, et Django renommait le suivant (`note_iN8GAGE.txt`) pour éviter la collision
    — ce qui a fait échouer le test au deuxième passage. Un test qui pollue le disque de
    production est un défaut, pas un détail : il rend aussi le résultat dépendant de
    l'historique des exécutions.
    """

    def setUp(self):
        self.user = User.objects.create(username='fabien')

    def _msg(self, texte='', pieces=None, fil='salon-1'):
        return core.MessageEntrant(channel=CANAL, external_id=EXT_ID, external_label='Fabien',
                                   texte=texte, fil=fil, pieces_jointes=pieces or [])

    def test_aide_sans_identite(self):
        reponse = core.traiter_message(self._msg('!aide'))
        self.assertIn('!lier', reponse.texte)

    def test_inconnu_invite_a_se_lier_et_le_moteur_n_est_jamais_appele(self):
        """⚠ Un inconnu ne doit JAMAIS être servi « en anonyme ».

        C'est le piège mesuré sur `/filemanager/api/upload/`, dont le `get_user()` retombait
        silencieusement sur l'utilisateur anonyme partagé : le traitement réussissait, au
        mauvais nom. Ici, l'absence de compte est une FIN de parcours.
        """
        with patch('wama.common.services.assistant_engine.run_assistant_turn') as moteur:
            reponse = core.traiter_message(self._msg('transcris ce fichier'))
        self.assertIn('!lier', reponse.texte)
        self.assertTrue(reponse.prive)
        moteur.assert_not_called()

    def test_code_rendu_en_prive(self):
        reponse = core.traiter_message(self._msg('!lier'))
        self.assertTrue(reponse.prive, "le code ne doit JAMAIS être publié dans un salon")
        lien = ChannelLink.objects.get(channel=CANAL, external_id=EXT_ID)
        self.assertIn(lien.code, reponse.texte)

    def test_apres_liaison_le_moteur_recoit_le_bon_compte(self):
        lien = demander_liaison(CANAL, EXT_ID)
        confirmer_liaison(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=_reponse_simulee) as moteur:
            reponse = core.traiter_message(self._msg('bonjour'))
        self.assertEqual(reponse.texte, 'reponse simulee')
        self.assertEqual(moteur.call_args.args[0], self.user)

    def test_piece_jointe_deposee_et_annoncee(self):
        lien = demander_liaison(CANAL, EXT_ID)
        confirmer_liaison(self.user, lien.code)
        piece = core.PieceJointe(nom='note.txt', contenu=b'contenu')
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=_reponse_simulee) as moteur:
            core.traiter_message(self._msg('transcris', pieces=[piece]))
        invite = moteur.call_args.args[1]
        self.assertIn('Fichiers déposés', invite)
        # Le CHEMIN déposé, pas le nom d'origine : le stockage peut suffixer le fichier en
        # cas de collision (`note_iN8GAGE.txt`). Ce qui compte est que l'assistant reçoive
        # un chemin exploitable dans l'espace de l'utilisateur.
        self.assertIn(f'users/{self.user.id}/temp/note', invite)
        self.assertIn('.txt`]', invite)

    def test_erreur_moteur_ne_fait_pas_planter_le_bot(self):
        lien = demander_liaison(CANAL, EXT_ID)
        confirmer_liaison(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   return_value={'error': 'panne simulee'}):
            reponse = core.traiter_message(self._msg('coucou'))
        self.assertIn('panne simulee', reponse.texte)

    def test_exception_imprevue_ne_fait_pas_planter_le_bot(self):
        """Un bot qui plante sur UN message cesse de servir TOUS les autres."""
        lien = demander_liaison(CANAL, EXT_ID)
        confirmer_liaison(self.user, lien.code)
        with patch('wama.common.services.assistant_engine.run_assistant_turn',
                   side_effect=RuntimeError('boum')):
            reponse = core.traiter_message(self._msg('coucou'))
        self.assertIn('erreur interne', reponse.texte.lower())


class TronconnageDiscordTests(TestCase):
    """La limite de 2000 caractères de Discord est une limite DURE : la dépasser = 400."""

    def test_reponse_longue_decoupee(self):
        from wama.gateway.adapters.discord_bot import _tronconner
        morceaux = _tronconner('x' * 5000)
        self.assertEqual(len(morceaux), 3)
        self.assertTrue(all(len(m) <= 2000 for m in morceaux))

    def test_coupe_de_preference_sur_saut_de_ligne(self):
        from wama.gateway.adapters.discord_bot import _tronconner
        morceaux = _tronconner('ligne\n' * 500)
        self.assertTrue(all(len(m) <= 2000 for m in morceaux))
        self.assertTrue(all(not m.startswith('\n') for m in morceaux))


class FichiersProduitsTests(TestCase):
    """`_fichiers_produits` — le retour des sorties d'outils vers le canal (correctif 29/08 :
    `Reponse.fichiers` n'était JAMAIS rempli, le code d'envoi de l'adaptateur était mort)."""

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
        fichiers = core._fichiers_produits(resultat)
        self.assertEqual(fichiers, ['gateway_tests/sortie.png', 'gateway_tests/sortie.wav'])

    def test_une_traversee_hors_media_root_est_ignoree(self):
        resultat = {'tool_steps': [{'tool': 'x', 'result': {
            'file_url': '/media/../wama/settings.py'}}]}
        self.assertEqual(core._fichiers_produits(resultat), [])

    def test_un_fichier_inexistant_ou_un_resultat_non_dict_ne_cassent_rien(self):
        resultat = {'tool_steps': [
            {'tool': 'x', 'result': {'file_url': '/media/gateway_tests/absent.png'}},
            {'tool': 'y', 'result': 'erreur en chaîne'},
        ]}
        self.assertEqual(core._fichiers_produits(resultat), [])
