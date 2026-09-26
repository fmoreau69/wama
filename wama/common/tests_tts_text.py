"""
Le texte À DIRE (`common/utils/tts_text.py`) — 2026-09-26.

⚠ POURQUOI CES GARDES EXISTENT SEULEMENT AUJOURD'HUI. La chaîne de préparation du texte
vocalisé s'est enrichie pendant des semaines (retrait des emojis, flèches, respirations de fin
de ligne, tiret d'incise) et **aucun test ne la touchait** — relevé à la demande de Fabien le
jour où elle est devenue une brique commune. Chaque règle avait été ajoutée après un défaut
ENTENDU par un humain ; rien n'empêchait la suivante de la défaire.

⚠⚠ ET LE RISQUE N'EST PAS L'EXCEPTION, C'EST LA VOIX QUI DÉRAILLE SANS QUE RIEN NE PLANTE.
Un pictogramme non retiré fait dire « emoji visage souriant » ; une liste sans ponctuation est
lue d'un trait. Le serveur répond 200, le fichier audio existe, la page ne montre aucune
erreur. C'est le défaut qui ne se voit qu'à l'oreille — donc celui qui a le plus besoin d'un
test.

Chaque règle vient avec sa CONTRE-ÉPREUVE, parce que toutes ces règles sont des arbitrages :
retirer un tiret est juste en incise et faux dans un mot composé ; ponctuer une fin de ligne est
juste sur une puce et faux sur une phrase déjà ponctuée. Une règle sans contre-épreuve passe le
test en cassant le cas voisin — c'est arrivé une fois, sur le tiret (`\\s+` au lieu de `[ \\t]+`
fusionnait la liste entière en une phrase).
"""
from django.test import SimpleTestCase

from wama.common.utils.tts_text import make_audible, text_for_speech


class PronounceableTest(SimpleTestCase):
    """Ce que le moteur ne doit PAS se mettre à verbaliser."""

    def test_a_pictogram_is_removed_but_the_accents_survive(self):
        """La contre-épreuve est le cœur de la règle : le retrait passe par des catégories
        Unicode, et un mauvais choix de catégories emporterait les accents français."""
        said = text_for_speech('Résultat ✅ prêt, à écouter 🎧')
        self.assertNotIn('✅', said)
        self.assertNotIn('🎧', said)
        self.assertIn('Résultat', said)
        self.assertIn('à écouter', said)

    def test_an_arrow_becomes_a_pause_instead_of_disappearing(self):
        """Retirer la flèche AVANT de la traduire enchaînerait les deux mots d'un trait."""
        said = text_for_speech('Anonymisation → Masque')
        self.assertNotIn('→', said)
        self.assertIn(',', said)

    def test_a_table_is_flattened_and_its_rules_are_gone(self):
        said = text_for_speech('| Modèle | VRAM |\n|---|---|\n| Kokoro | 2 Go |')
        self.assertNotIn('|', said)
        self.assertNotIn('---', said)
        self.assertIn('Kokoro', said)

    def test_a_link_keeps_its_label_and_loses_its_address(self):
        said = text_for_speech('Voir [le rapport](https://wama.example/rapport.pdf) svp.')
        self.assertIn('le rapport', said)
        self.assertNotIn('https', said)

    def test_a_bare_address_is_not_spelled_out(self):
        said = text_for_speech('Écrivez à contact@exemple.fr ou https://exemple.fr pour suivre.')
        self.assertNotIn('@', said)
        self.assertNotIn('https', said)
        self.assertIn('pour suivre', said)

    def test_a_removed_address_leaves_a_sentence_one_can_still_say(self):
        """⚠⚠ LE DÉFAUT QUE LA GARDE PRÉCÉDENTE NE VOYAIT PAS, trouvé par un smoke réel le
        2026-09-26. Elle vérifiait l'ABSENCE de l'adresse et rien de plus : effacer l'adresse
        rendait « Écrivez à contact@… ou https://… » en **« Écrivez a ou. »**, lu tel quel à
        voix haute. *Vérifier qu'une chose a disparu ne dit pas ce qui reste à sa place.*
        L'adresse est donc REMPLACÉE par un mot qui nomme sa nature."""
        said = text_for_speech('Écrivez à contact@exemple.fr ou https://exemple.fr')
        self.assertIn('une adresse électronique', said)
        self.assertIn('un lien', said)
        self.assertNotIn(' a ou', said)
        self.assertNotIn('  ', said)

    def test_the_replacement_does_not_fire_when_there_is_no_address(self):
        """Contre-épreuve : une phrase sans adresse ne gagne aucun mot."""
        said = text_for_speech('Écrivez-moi quand vous voulez.')
        self.assertNotIn('un lien', said)
        self.assertNotIn('adresse électronique', said)


class AudibleTest(SimpleTestCase):
    """Prononçable ne veut pas dire ÉCOUTABLE : seule la ponctuation fait une pause."""

    def test_a_line_without_punctuation_gains_the_pause_it_lacked(self):
        self.assertEqual('Première étape.', make_audible('Première étape'))

    def test_a_line_that_already_ends_punctuated_is_left_alone(self):
        """Contre-épreuve : sans elle, on doublerait la ponctuation de toute phrase normale."""
        self.assertEqual('Première étape.', make_audible('Première étape.'))
        self.assertEqual('Modèles actifs :', make_audible('Modèles actifs :'))

    def test_a_bullet_list_becomes_as_many_sentences(self):
        said = make_audible('- charger le modèle\n- lancer la tâche\n- récupérer le fichier')
        self.assertEqual(['charger le modèle.', 'lancer la tâche.', 'récupérer le fichier.'],
                         said.split('\n'))

    def test_the_list_is_never_merged_into_one_sentence(self):
        """LA régression mesurée : une classe d'espaces incluant le saut de ligne faisait
        traverser les lignes à la règle du tiret, et toute la liste devenait une phrase."""
        said = make_audible('- premier - avec incise\n- second')
        self.assertEqual(2, len(said.split('\n')), said)

    def test_a_dash_in_an_aside_becomes_a_comma_but_a_compound_word_keeps_its_dash(self):
        self.assertEqual('via Celery, vous recevrez un message.',
                         make_audible('via Celery - vous recevrez un message.'))
        self.assertEqual('en arrière-plan.', make_audible('en arrière-plan'))

    def test_a_slash_between_two_words_is_said_but_a_date_is_not_touched(self):
        self.assertEqual('audio ou vidéo.', make_audible('audio/vidéo'))
        self.assertIn('26/09/2026', make_audible('Palier du 26/09/2026.'))

    def test_an_ampersand_is_said(self):
        self.assertEqual('images et vidéos.', make_audible('images & vidéos'))


class NothingToSayTest(SimpleTestCase):

    def test_an_empty_text_stays_empty_and_does_not_raise(self):
        for nothing in ('', None):
            self.assertFalse(text_for_speech(nothing))


class BothSurfacesShareTheBrickTest(SimpleTestCase):
    """La garde du PORTAGE : deux implémentations portaient le même nom dans deux domiciles.

    Sans ce test, une des deux surfaces peut se remettre à écrire sa propre chaîne sans que
    rien ne le signale — c'est exactement ce qui était arrivé, et la duplication de NOM est ce
    qui l'avait rendue invisible à un `grep`.
    """

    def test_the_vocalization_view_uses_the_brick(self):
        from wama import views
        self.assertIs(text_for_speech, views.text_for_speech)

    def test_the_synthesizer_delegates_instead_of_holding_its_own_chain(self):
        from wama.synthesizer.utils.text_extractor import clean_text_for_tts
        said = clean_text_for_tts('Premier point ✅\nSecond point')
        self.assertNotIn('✅', said)
        self.assertEqual(['Premier point.', 'Second point.'], said.split('\n'))

    def test_what_the_synthesizer_already_guaranteed_still_holds(self):
        """Contre-épreuve du portage : son propre test n'exigeait que ces deux choses, et une
        délégation qui les perdrait serait une régression pour six appelants."""
        from wama.synthesizer.utils.text_extractor import clean_text_for_tts
        said = clean_text_for_tts('Test   with   spaces\n\n\nand http://example.com URLs')
        self.assertNotIn('http://', said)
        self.assertNotIn('   ', said)
