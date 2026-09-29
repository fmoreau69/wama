"""
SAM3 n'ancre qu'UN groupe nominal à la fois — le découpage en concepts, gardé (2026-09-26).

LA MESURE QUI FONDE CE DÉCOUPAGE (2026-09-23, sur une photo réelle, modèle chargé une fois,
seul le prompt changeant) :

    'face' · 'faces' · 'human face'                 -> 3 masques (0.93 / 0.89 / 0.88)
    'all human faces'                               -> 0   le quantificateur
    'face and person'                               -> 1   (0.60, dégradé)
    'faces and license plates'                      -> 0   la conjonction
    'all human faces and vehicle license plates'    -> 0   l'exemple que portait le skill
    'Detect faces and license plates.'              -> 0   ce qui partait réellement

Une conjonction, un quantificateur ou un verbe font échouer SILENCIEUSEMENT : zéro masque,
aucune erreur, et une image de sortie identique à l'entrée. D'où le contrat : une LISTE de
concepts, un appel SAM3 par concept, les masques réunis — la forme qu'a le cam_analyzer depuis
toujours (`sam3_markings_prompts` itérée un par un).

⚠ Ce que ces gardes tiennent est le DÉCOUPAGE, pas la segmentation : les séparateurs sont une
convention de parsing écrite à la main (virgule, point-virgule, retour ligne, « and », « et »),
et c'est la seule pièce de la chaîne SAM3 qui ne soit pas déclarée quelque part.
"""
from django.test import SimpleTestCase


class _Prompt:
    """Le strict nécessaire pour `concepts()` — elle ne lit que `text_prompt`. Évite de
    construire un `SAM3Processor` (torch, dossiers média) pour éprouver du découpage pur."""

    def __init__(self, text):
        self.text_prompt = text


def _concepts(text):
    from wama.common.backends.sam3_processor import SAM3Processor
    return SAM3Processor.concepts(_Prompt(text))


class Sam3ConceptSplitTest(SimpleTestCase):

    def test_a_comma_separated_list_becomes_one_concept_each(self):
        self.assertEqual(['face', 'license plate'], _concepts('face, license plate'))

    def test_the_conjunction_models_write_spontaneously_is_tolerated(self):
        """« and » est ce qu'un LLM écrit de lui-même : on le coupe au lieu de le subir."""
        self.assertEqual(['face', 'license plate'], _concepts('face and license plate'))
        self.assertEqual(['visage', 'plaque'], _concepts('visage et plaque'))

    def test_the_trailing_period_of_a_sentence_does_not_become_a_concept(self):
        self.assertEqual(['detect faces', 'license plates'],
                         _concepts('Detect faces and license plates.'.lower()))

    def test_newlines_and_semicolons_separate_too(self):
        self.assertEqual(['face', 'screen', 'badge'], _concepts('face;\nscreen\nbadge'))

    def test_an_empty_or_blank_prompt_yields_nothing_rather_than_an_empty_concept(self):
        """Un concept vide interrogerait SAM3 pour rien — et son zéro masque ressemblerait
        à un échec de détection."""
        for empty in ('', '   ', ',,', None):
            self.assertEqual([], _concepts(empty), repr(empty))

    def test_a_single_concept_stays_whole(self):
        self.assertEqual(['human face'], _concepts('human face'))
