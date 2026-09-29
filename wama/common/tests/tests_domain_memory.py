"""
Le souvenir de compétence d'un fil a une SORTIE (2026-09-23, demande de Fabien).

LE DÉFAUT MESURÉ. Le fil web #12 a chargé la compétence `dev` le 22/09 à 10:22, sur la
question « Modification du code WAMA » — un choix parfaitement légitime. Le LENDEMAIN, un
« anonymise ma photo » partait encore bridé au niveau développement : `qwen3.6:35b` (23 Go)
tiré sur 3,6 Go libres, `DEV_QUALITY_INTENT=100` faisant cesser le budget de borner,
réflexion activée — et un tour si long que gunicorn rendait un 504 (donc une page HTML, donc
« Unexpected token '<' » à l'écran).

⭐ *Un état qu'aucun geste ne peut quitter n'est pas une mémoire, c'est un piège.*

Le signal de sortie est DÉRIVÉ, jamais listé : un outil de la triade d'app (`add_` / `start_`
/ `get_*_status`) dit que l'utilisateur SE SERT de WAMA au lieu d'en écrire le code. Une app
portée à la triade plus tard le fournit sans qu'on touche à ce code.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import conversation_store as store


class DomainMemoryExitTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('memo', password='x')
        self.thread = store.thread(self.user, surface='web', thread_key='t')

    def _turn(self, *tools):
        """Un tour d'assistant dont les étapes d'outil sont `tools` (nom ou (nom, args))."""
        steps = [{'tool': t[0], 'args': t[1]} if isinstance(t, tuple) else {'tool': t}
                 for t in tools]
        store.record_exchange(self.thread, 'question', {'response': 'r', 'tool_steps': steps})

    def test_a_loaded_competence_is_remembered(self):
        self._turn(('charger_competence', {'domaine': 'dev'}))
        self.assertEqual('dev', store.last_loaded_domain(self.thread))

    def test_using_an_app_afterwards_releases_it(self):
        """LE cas mesuré : compétence dev hier, anonymisation aujourd'hui."""
        self._turn(('charger_competence', {'domaine': 'dev'}))
        self._turn('list_user_files', 'add_to_anonymizer', 'start_anonymizer')
        self.assertEqual('', store.last_loaded_domain(self.thread))

    def test_merely_asking_for_a_status_releases_it_too(self):
        self._turn(('charger_competence', {'domaine': 'dev'}))
        self._turn('get_anonymizer_status')
        self.assertEqual('', store.last_loaded_domain(self.thread))

    def test_reloading_the_competence_takes_the_hand_back(self):
        """La sortie n'est pas un aller simple : reposer une question de code suffit."""
        self._turn(('charger_competence', {'domaine': 'dev'}))
        self._turn('add_to_anonymizer')
        self._turn(('charger_competence', {'domaine': 'dev'}))
        self.assertEqual('dev', store.last_loaded_domain(self.thread))

    def test_a_turn_without_any_app_tool_keeps_the_competence(self):
        """Contre-épreuve : parler du code sans lancer de tâche ne doit RIEN relâcher."""
        self._turn(('charger_competence', {'domaine': 'dev'}))
        self._turn('search_web', 'read_web_page')
        self._turn()
        self.assertEqual('dev', store.last_loaded_domain(self.thread))

    def test_the_engine_stops_bridling_the_turn_after_an_app_was_used(self):
        """Contre-épreuve de bout en bout : c'est le TOUR suivant qui doit changer de modèle."""
        from unittest.mock import patch

        from wama.common.services import assistant_engine

        self._turn(('charger_competence', {'domaine': 'dev'}))
        seen = {}

        def _fake_call(messages, llm_model, provider, **kwargs):
            seen['model'], seen['think'] = llm_model, kwargs.get('think')
            return 'ok', {}

        with patch.object(assistant_engine, '_llm_call', side_effect=_fake_call):
            with patch.object(assistant_engine, 'resolve_turn_model',
                              return_value=('ollama', 'grand-modele-dev')) as resolved:
                assistant_engine.conversation_turn(self.user, 'et le code ?',
                                                   surface='web', thread_key='t')
                self.assertEqual('dev', resolved.call_args.kwargs.get('domain'))

        self._turn('start_anonymizer')          # l'utilisateur se sert d'une app
        with patch.object(assistant_engine, '_llm_call', side_effect=_fake_call):
            with patch.object(assistant_engine, 'resolve_turn_model',
                              return_value=('ollama', 'petit-modele')) as resolved:
                assistant_engine.conversation_turn(self.user, 'anonymise ma photo',
                                                   surface='web', thread_key='t')
                self.assertIsNone(resolved.call_args.kwargs.get('domain'))
        self.assertEqual('petit-modele', seen['model'])
