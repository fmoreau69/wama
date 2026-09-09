"""
Adoption de `llm_chat` par les 5 aides de haut niveau (2026-09-09).

⚠ POURQUOI CES GARDES EXISTENT — elles manquaient à la livraison, et c'est le pire cas.
Ces cinq fonctions (transcriber, describer, reader) appelaient `ollama_chat()` en direct :
**local-only par construction**. Le portage vers `llm_chat` porte DEUX détails dont aucun ne
lève d'exception locale s'il est défait :

  1. **`model or None`, jamais `model`.** Le défaut de ces signatures est `''`, et la branche
     cloud de `llm_chat` teste `if model is None` pour appliquer le défaut du fournisseur. Une
     chaîne VIDE passe ce test et produit le modèle `"openai/"` — une erreur DISTANTE, visible
     seulement quand quelqu'un route vers le cloud, c'est-à-dire jamais en test local.
  2. **`provider` remonte à l'appelant.** Le laisser implicite marierait un modèle résolu
     localement à un fournisseur global cloud — le seul appariement que `llm_chat` ne rattrape
     pas.

Un défaut qui ne se voit qu'à distance ne se trouve pas par l'usage : il se garde par un test.
Contrat documenté à `llm_utils.py::_APPEL_LLM`.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from .utils import llm_utils

#: Les cinq aides et un jeu d'arguments minimal qui atteint l'appel LLM.
AIDES = (
    ('generate_meeting_summary', {'text': 'du texte'}),
    ('verify_text_coherence', {'text': 'du texte'}),
    ('analyze_segments_coherence', {'segments': [{'index': 0, 'text': 'phrase'}]}),
    ('suggest_speaker_names', {'segments': [{'speaker_id': 'SPEAKER_00', 'text': 'bonjour'}]}),
    ('generate_structured_summary', {'text': 'du texte'}),
)


class AdoptionLlmChatTest(SimpleTestCase):
    """On espionne `llm_chat` et on lit les kwargs REÇUS — pas le code source."""

    def _appels(self, nom, kwargs):
        """Rend la liste des appels à `llm_chat` faits par l'aide `nom`.

        ⚠ Le retour du bouchon est volontairement INEXPLOITABLE, et l'exception qui suit est
        volontairement AVALÉE : ce qu'on mesure est ce qui PART vers le LLM, pas ce que l'aide
        fait de la réponse. Fabriquer un JSON valide pour chacune ferait dépendre ces gardes du
        format de sortie de cinq fonctions — elles casseraient au premier champ ajouté, pour une
        raison sans rapport avec ce qu'elles protègent.
        """
        with patch.object(llm_utils, 'llm_chat', return_value=('{}', None)) as espion:
            try:
                getattr(llm_utils, nom)(**kwargs)
            except Exception:
                pass
        return espion.call_args_list

    def test_aucune_aide_n_appelle_plus_ollama_chat_en_direct(self):
        """Le contournement le plus simple du portage : réintroduire l'appel direct.

        Il ne casserait AUCUN test fonctionnel — la sortie serait identique en local. Seule
        cette garde le voit.
        """
        for nom, kwargs in AIDES:
            with self.subTest(aide=nom):
                with patch.object(llm_utils, 'ollama_chat') as direct, \
                        patch.object(llm_utils, 'llm_chat', return_value=('{}', None)):
                    try:
                        getattr(llm_utils, nom)(**kwargs)
                    except Exception:
                        pass
                self.assertFalse(direct.called,
                                 f"{nom} appelle encore `ollama_chat` : elle redevient local-only")

    def test_le_modele_vide_part_en_None_jamais_en_chaine_vide(self):
        """`model=''` + branche cloud ⇒ modèle `"openai/"`. Erreur distante, muette ici."""
        for nom, kwargs in AIDES:
            with self.subTest(aide=nom):
                appels = self._appels(nom, kwargs)
                self.assertTrue(appels, f"{nom} n'a appelé aucun LLM")
                for appel in appels:
                    self.assertIsNone(
                        appel.kwargs.get('model', 'ABSENT'),
                        f"{nom} passe un `model` non-None alors qu'aucun n'a été demandé — "
                        f"`model or None` a dû sauter")

    def test_le_provider_demande_par_l_appelant_est_TRANSMIS(self):
        """Sans ça, l'appelant croit router vers son fournisseur et reste sur le défaut global."""
        for nom, kwargs in AIDES:
            with self.subTest(aide=nom):
                appels = self._appels(nom, dict(kwargs, provider='anthropic'))
                for appel in appels:
                    self.assertEqual('anthropic', appel.kwargs.get('provider'),
                                     f"{nom} n'a pas transmis le `provider` de l'appelant")

    def test_un_modele_EXPLICITE_est_transmis_tel_quel(self):
        """Contre-épreuve : `model or None` ne doit pas écraser un choix réel de l'appelant.

        Sans elle, la garde précédente serait satisfaite par un `model=None` en dur — qui
        casserait toute sélection de modèle par le catalogue.
        """
        for nom, kwargs in AIDES:
            with self.subTest(aide=nom):
                appels = self._appels(nom, dict(kwargs, model='gemma4:e4b'))
                for appel in appels:
                    self.assertEqual('gemma4:e4b', appel.kwargs.get('model'),
                                     f"{nom} écrase le modèle demandé")


class AdoptionReaderTest(SimpleTestCase):
    """`reader/tasks.py` était le DERNIER appelant direct hors `llm_utils` (porté le 09/09)."""

    def test_le_reader_passe_par_llm_chat(self):
        from pathlib import Path

        from django.conf import settings

        source = (Path(settings.BASE_DIR) / 'wama' / 'reader' / 'tasks.py').read_text(
            encoding='utf-8')
        self.assertNotIn('import ollama_chat', source,
                         "le reader réimporte `ollama_chat` : il redevient local-only")
        self.assertIn('model=model or None', source,
                      "le reader a perdu le `model or None` — modèle `\"openai/\"` en cloud")
