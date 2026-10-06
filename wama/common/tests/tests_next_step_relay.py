"""Un AJOUT n'est pas un LANCEMENT — et le résultat de l'outil doit le dire (2026-09-23).

LE DÉFAUT MESURÉ. Conversation Discord #11 du 22/09 : le modèle appelle `add_to_anonymizer`,
lit `{"status": "queued"}`, annonce « la tâche d'anonymisation a été lancée », puis, au tour
suivant, « terminée avec succès » avec un lien inventé. Mesure du lendemain : l'item 647 est
toujours `queued`, progress 0 — `start_anonymizer` n'a jamais été appelé. Rien dans le
résultat ne distinguait « rangé dans la file » de « en cours ».

CE QUE CES GARDES PROTÈGENT :
  1. un `add_to_<app>` en attente rend `started: False` + le NOM du `start_*` à appeler ;
  2. le rappel est DÉRIVÉ (rôle de l'outil + registre), donc une app portée à la triade
     l'obtient sans qu'on touche au code du relais ;
  3. la garde est dans la DONNÉE (l'état rendu), pas dans une liste d'apps : un ajout qui
     aurait déjà dispatché ne reçoit pas le rappel ;
  4. un résultat en erreur ou un outil hors triade ne sont jamais touchés.
"""
from django.test import TestCase

from wama.tool_api import TOOL_REGISTRY, relay_next_step


class NextStepRelayTest(TestCase):

    def test_a_queued_add_says_what_to_call_next(self):
        # La forme RÉELLE de `add_to_anonymizer` (sa clé propre ET la clé uniforme du contrat) —
        # le rappel lit `item_id` (`items_of_step`, 2026-10-06), plus une liste de clés d'app.
        result = relay_next_step('add_to_anonymizer', {'media_id': 647, 'item_id': 647,
                                                       'status': 'queued', 'name': 'photo.jpg'})
        self.assertIs(False, result['started'])
        self.assertEqual('start_anonymizer', result['next_step'])
        self.assertIn('647', result['next_step_hint'])

    def test_the_start_tool_it_names_really_exists(self):
        """Le rappel ne vaut que s'il nomme un outil APPELABLE — sinon il envoie le modèle
        sur un nom inventé, ce que l'on est précisément en train de corriger."""
        for tool in ('add_to_anonymizer', 'add_to_reader', 'add_to_transcriber'):
            result = relay_next_step(tool, {'item_id': 1, 'status': 'queued'})
            self.assertIn(result['next_step'], TOOL_REGISTRY, f'{tool} → {result}')

    def test_the_common_status_vocabulary_is_what_is_read(self):
        """`add_to_reader` rend `PENDING`, l'anonymizer le littéral hérité `queued`. L'état est
        lu par `normalize_job_status` contre `JOB_STATUS_NOT_STARTED` (domicile commun), donc
        `AWAITING_RESOURCES` compte aussi — sans qu'aucune app ait à le redire."""
        for status in ('PENDING', 'queued', 'AWAITING_RESOURCES'):
            result = relay_next_step('add_to_reader', {'item_id': 12, 'status': status})
            self.assertEqual('start_reader', result.get('next_step'), status)

    def test_an_add_that_already_dispatched_gets_no_reminder(self):
        result = relay_next_step('add_to_anonymizer', {'media_id': 5, 'status': 'RUNNING'})
        self.assertNotIn('next_step', result)

    def test_an_error_a_status_tool_and_a_transverse_tool_are_left_alone(self):
        for tool, payload in (('add_to_anonymizer', {'error': 'format non supporté'}),
                              ('get_anonymizer_status', {'jobs': [], 'status': 'queued'}),
                              ('list_user_files', {'status': 'queued'})):
            self.assertNotIn('next_step', relay_next_step(tool, payload), tool)
