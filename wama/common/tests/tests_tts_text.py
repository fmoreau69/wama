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

from wama.common.utils.tts_text import (lexicon, make_audible, pause_segments,
                                        phonemes_with_lexicon, pronunciations,
                                        respell_with_lexicon, say_emphasis, text_for_speech)


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


class HeardAsWrittenTest(SimpleTestCase):
    """Ce que Fabien ENTENDAIT de travers (2026-10-18), mesuré par un aller-retour voix →
    transcription : chaque règle porte le défaut entendu, et sa contre-épreuve."""

    def test_a_parenthesis_is_said_as_an_aside_between_commas(self):
        """« Le chat (gris et blanc) dort » était entendu « Le chat gris est blanc d'or »."""
        self.assertEqual('Le chat, gris et blanc, dort sur le canapé.',
                         text_for_speech('Le chat (gris et blanc) dort sur le canapé.'))

    def test_an_aside_closing_the_sentence_keeps_its_full_stop(self):
        self.assertEqual('Il dort, vraiment.', text_for_speech('Il dort (vraiment).'))
        self.assertEqual('Il dort, vraiment.', text_for_speech('Il dort (vraiment)'))

    def test_a_glued_optional_plural_merges_instead_of_pausing(self):
        """Contre-épreuve : « fichier(s) » n'est pas une incise."""
        self.assertEqual('Choisir les fichiers.', text_for_speech('Choisir les fichier(s)'))

    def test_inline_code_is_said_and_an_identifier_keeps_its_words_apart(self):
        """Le navigateur EFFAÇAIT le code en ligne (« (`instant_preview`) » → « () ») ; une fois
        gardé, le tiret bas retiré collait les mots (« instant-travilleux »)."""
        said = text_for_speech('Le champ `instant_preview` est lu par la card.')
        self.assertEqual('Le champ instant preview est lu par la card.', said)

    def test_an_italic_underscore_is_still_a_markdown_marker(self):
        """Contre-épreuve : `_mot_` est de l'italique, pas un identifiant."""
        self.assertEqual('Un mot souligné.', text_for_speech('Un _mot_ souligné'))

    def test_a_code_block_is_announced_not_read(self):
        said = text_for_speech('Voici :\n```python\nprint("x")\n```\nFin.')
        self.assertIn('bloc de code', said)
        self.assertNotIn('print', said)

    def test_a_short_emphasis_word_is_no_longer_spelled(self):
        """espeak épelait « UNE », « CE », « NE », « MOT », « DIT » (mesuré) ; les longs passaient."""
        self.assertEqual("Ce n'est pas une erreur, ne le dites pas.",
                         say_emphasis("CE n'est PAS UNE erreur, NE le dites pas."))

    def test_an_acronym_stays_an_acronym(self):
        """Contre-épreuve : un sigle mis en minuscules se lirait comme un mot (« rag »)."""
        self.assertEqual('Le RAG et la carte GPU.', say_emphasis('Le RAG et la carte GPU.'))
        self.assertEqual('Une phrase normale.', say_emphasis('Une phrase normale.'))

    def test_emphasis_no_longer_applies_the_lexicon(self):
        """Le lexique dépend de la langue de la voix et du compte, que ce texte ignore : il est
        au moteur depuis le 27/10 (`RespellingTest`). Le texte AFFICHÉ garde « WAMA »."""
        self.assertEqual('Bienvenue dans WAMA.', say_emphasis('Bienvenue dans WAMA.'))


def _brackets(part):
    """Un phonémiseur de test : chaque morceau phonémisé se lit entre chevrons."""
    return '<' + part.strip() + '>'


class PronunciationLexiconTest(SimpleTestCase):
    """Les termes techniques dits par leurs PHONÈMES (2026-10-27) : le découpage autour des
    termes, sans espeak — le moteur réel est gardé dans `tests_kokoro_onnx_phonemes`."""

    def _said(self, text, language='fr'):
        return phonemes_with_lexicon(text, language, _brackets)

    def test_a_term_is_said_by_its_lexicon_phonemes(self):
        self.assertEqual('<Fais un> ɡˈit kɔmˈit <, puis la suite.>',
                         self._said('Fais un git commit, puis la suite.'))

    def test_case_and_plural_find_the_same_entry(self):
        self.assertEqual('<Les> kɔmˈit <de> ɡˈit', self._said('Les commits de Git'))

    def test_the_longest_spelling_wins(self):
        self.assertEqual('<Sur> ɡitˈœb.', self._said('Sur GitHub.'))

    def test_a_word_that_only_contains_a_term_is_left_to_the_phonemizer(self):
        """Contre-épreuve : mot ENTIER — « digit » ne cache pas « git »."""
        self.assertEqual('<Un digit, un gîte.>', self._said('Un digit, un gîte.'))

    def test_an_affricate_loses_its_tie_by_default(self):
        self.assertEqual('<Un> mˈœʁdʒ', self._said('Un merge'))

    def test_a_language_without_lexicon_is_phonemized_as_before(self):
        """Contre-épreuve : une voix anglaise lit « git » elle-même."""
        self.assertEqual('<Push to git.>', self._said('Push to git.', language='en'))

    def test_a_failure_says_the_sentence_as_before(self):
        def finish(entry):
            raise ValueError('entrée illisible')
        self.assertEqual('<Un git.>', phonemes_with_lexicon('Un git.', 'fr', _brackets, finish))

    def test_every_entry_writes_its_g_as_the_phonetic_letter(self):
        """Le g du clavier n'est pas au vocabulaire de Kokoro, qui l'effacerait sans rien dire."""
        offenders = [term for term, entry in pronunciations('fr').items()
                     if 'g' in entry.get('phonemes', '')]
        self.assertEqual([], offenders)

    def test_an_entry_with_a_spelling_only_is_said_within_its_sentence(self):
        """« WAMA » n'a qu'une orthographe à dire : elle se substitue DANS le texte, phonémisé
        d'un seul tenant — « dans Ouama » garde sa liaison (un morceau à part la perdait)."""
        self.assertEqual('<Bienvenue dans Ouama.>', self._said('Bienvenue dans WAMA.'))

    def test_an_account_entry_passes_before_the_system_one(self):
        """Les lignes d'un compte (`extra`, jointes à la demande) remplacent, pour lui, l'entrée
        système du même terme — casse indifférente."""
        said = phonemes_with_lexicon('Un git.', 'fr', _brackets, extra={'GIT': {'phonemes': 'ʒit'}})
        self.assertEqual('<Un> ʒit.', said)
        # Contre-épreuve : sans `extra`, l'entrée système.
        self.assertEqual('<Un> ɡˈit.', self._said('Un git.'))

    def test_an_account_entry_adds_a_term_the_file_ignores(self):
        said = phonemes_with_lexicon('Lance ENA_CASA.', 'fr', _brackets,
                                     extra={'ENA_CASA': {'spelling': 'éna kaza'}})
        self.assertEqual('<Lance éna kaza.>', said)

    def test_a_malformed_account_entry_is_ignored(self):
        """La voix ne fait pas confiance à la forme de ce qui lui arrive : une entrée sans forme
        connue est ignorée, jamais une erreur."""
        merged = lexicon('fr', {'git': 'ɡit', 'deploy': {'accent': 'x'}, '': {'spelling': 'y'}})
        self.assertEqual({'phonemes': 'ɡˈit'}, merged['git'])
        self.assertEqual({'phonemes': 'diplˈɔj'}, merged['deploy'])


class RespellingTest(SimpleTestCase):
    """L'ORTHOGRAPHE à dire, pour un moteur qui lit du texte (le contrat commun l'appelle)."""

    def test_wama_is_said_the_french_way(self):
        """espeak lit « WAMA » à l'anglaise quelle que soit sa casse (entendu « WAM ») — l'ancien
        `SPOKEN_FORMS`, une entrée du fichier depuis le 27/10."""
        self.assertEqual('Bienvenue dans Ouama.', respell_with_lexicon('Bienvenue dans WAMA.', 'fr'))
        # Contre-épreuve : mot ENTIER — un mot qui le contient ne bouge pas.
        self.assertEqual('wamadata', respell_with_lexicon('wamadata', 'fr'))

    def test_a_phonemes_only_entry_is_left_to_the_engine(self):
        """Un moteur qui lit du texte ne saurait pas dire des phonèmes : « git » reste « git »."""
        self.assertEqual('Un git.', respell_with_lexicon('Un git.', 'fr'))

    def test_the_plural_stays_glued_to_the_spelling(self):
        self.assertEqual('Deux guites.',
                         respell_with_lexicon('Deux gits.', 'fr', {'git': {'spelling': 'guite'}}))

    def test_another_voice_language_keeps_its_text(self):
        """Contre-épreuve : le lexique est par langue de VOIX — une voix anglaise dit « WAMA »."""
        self.assertEqual('Welcome to WAMA.', respell_with_lexicon('Welcome to WAMA.', 'en'))


class LexiconFileIsReadAgainWhenItChangesTest(SimpleTestCase):
    """Le fichier se relit à chaque CHANGEMENT : le service vocal, un autre processus, voit une
    entrée corrigée sans relance."""

    def test_a_changed_file_is_read_again(self):
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        from wama.common.utils import tts_text
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pronunciations.json'
            path.write_text(json.dumps({'fr': {'git': {'spelling': 'guite'}}}), encoding='utf-8')
            with mock.patch.object(tts_text, '_PRONUNCIATIONS_FILE', path),                     mock.patch.object(tts_text, '_FILE_STATE', {'mtime': None, 'data': {}}):
                self.assertEqual('Un guite.', respell_with_lexicon('Un git.', 'fr'))
                path.write_text(json.dumps({'fr': {'git': {'spelling': 'jite'}}}), encoding='utf-8')
                stamp = path.stat().st_mtime_ns + 1_000_000
                os.utime(path, ns=(stamp, stamp))
                self.assertEqual('Un jite.', respell_with_lexicon('Un git.', 'fr'))


class PauseSegmentsTest(SimpleTestCase):
    """Où la voix respire, et combien — le réglage des pauses (2026-10-18)."""

    TEXT = 'Le chat dort, puis il mange. Ensuite il joue ; enfin il dort.'

    def test_each_mark_ends_a_segment_with_the_pause_it_asks_for(self):
        self.assertEqual([('Le chat dort,', 0.2), ('puis il mange.', 0.6),
                          ('Ensuite il joue ;', 0.2), ('enfin il dort.', 0.0)],
                         pause_segments(self.TEXT, 0.6, 0.2))

    def test_no_pause_asked_keeps_the_text_whole(self):
        """Contre-épreuve : réglages à zéro = le comportement d'avant, un seul appel au moteur."""
        self.assertEqual([(self.TEXT, 0.0)], pause_segments(self.TEXT, 0, 0))

    def test_a_clause_pause_at_zero_cuts_only_at_sentences(self):
        self.assertEqual([('Le chat dort, puis il mange.', 0.5),
                          ('Ensuite il joue ; enfin il dort.', 0.0)],
                         pause_segments(self.TEXT, 0.5, 0))

    def test_a_decimal_comma_is_not_a_pause(self):
        self.assertEqual([('Il pèse 3,5 kilos.', 0.0)], pause_segments('Il pèse 3,5 kilos.', 0.5, 0.2))


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
