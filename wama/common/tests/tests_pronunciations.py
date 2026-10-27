"""Le lexique de prononciation d'un COMPTE — registre `pronunciations`, `ROADMAP §29` (2026-10-27).

CE QUE CES GARDES TIENNENT :
  1. le CONTRAT des moteurs dit le lexique pour tous : un moteur qui lit du texte reçoit
     l'orthographe à dire, un moteur qui reçoit des phonèmes reçoit le texte tel quel ;
  2. la voix tourne sans Django : les lignes du compte partent AVEC la demande
     (`options['lexicon']`), résolues par `lexicon_for` — le système, puis les siennes ; jamais
     celles qu'on lui partage, jamais celles d'un autre ;
  3. les gestes (`services/user_pronunciations`) : elle naît privée, seul son auteur la modifie,
     elle se copie, un administrateur seul la rend système, jamais par-dessus le fichier ;
  4. la page du registre, « Mes partages », et l'ÉCOUTE avant d'adopter.
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile
from wama.common.backends.tts_base import TTSBackend
from wama.common.models import Pronunciation
from wama.common.services import user_pronunciations as up


def _account(username, tier='utilisateur'):
    user = get_user_model().objects.create_user(username, password='x')
    UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
    return get_user_model().objects.get(pk=user.pk)


class _TextEngine(TTSBackend):
    """Un moteur qui lit du TEXTE : il retient ce qu'on lui donne à dire."""
    engine = 'text-test'
    is_loaded = True

    def load(self, model=None):
        return True

    def unload(self):
        pass

    def process(self, text='', **kwargs):
        self.said = text
        return 'x.wav'


class _PhonemeEngine(_TextEngine):
    engine = 'phoneme-test'

    def takes_lexicon_phonemes(self, language):
        return True


class TheContractSaysTheLexiconTest(SimpleTestCase):

    def _said(self, engine, text, options=None):
        engine.synthesize(text=text, language='fr', options=options or {})
        return engine.said

    def test_a_text_engine_receives_the_spelling(self):
        self.assertEqual('Bienvenue dans Ouama.', self._said(_TextEngine(), 'Bienvenue dans WAMA.'))
        self.assertEqual('Un guite.', self._said(_TextEngine(), 'Un git.',
                                                 {'lexicon': {'git': {'spelling': 'guite'}}}))

    def test_a_phoneme_engine_receives_the_text_untouched(self):
        """Contre-épreuve : il dit le lexique lui-même (`phonemes_with_lexicon`) — remplacer
        avant lui ferait disparaître le terme que ses phonèmes attendent."""
        self.assertEqual('Bienvenue dans WAMA.', self._said(_PhonemeEngine(), 'Bienvenue dans WAMA.'))


class _Accounts(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.author = _account('pron_author')
        cls.other = _account('pron_other')
        cls.admin = _account('pron_admin', 'admin')


class TheAccountLexiconTravelsWithTheRequestTest(_Accounts):

    def test_the_system_rows_then_the_accounts_own(self):
        Pronunciation.objects.create(term='ENA_CASA', spelling='éna kaza', visibility='public')
        up.create(self.author, 'ENA_CASA', 'fr', spelling='ena casa')
        up.create(self.author, 'git', 'fr', spelling='jite')
        self.assertEqual({'ENA_CASA': {'spelling': 'ena casa'}, 'git': {'spelling': 'jite'}},
                         up.lexicon_for(self.author, 'fr'))
        # Un autre compte, une tâche sans compte : les lignes système seules.
        for who in (self.other, None):
            self.assertEqual({'ENA_CASA': {'spelling': 'éna kaza'}}, up.lexicon_for(who, 'fr'), who)

    def test_a_shared_row_is_never_imposed(self):
        row = up.create(self.author, 'git', 'fr', spelling='jite')
        up.share(self.author, row.pk, 'public')
        self.assertIn(row.pk, [r.pk for r in up.visible_pronunciations(self.other)])
        self.assertEqual({}, up.lexicon_for(self.other, 'fr'))

    def test_the_lexicon_is_per_voice_language(self):
        up.create(self.author, 'git', 'en', spelling='ghit')
        self.assertEqual({}, up.lexicon_for(self.author, 'fr'))

    def test_the_service_client_joins_it_and_the_callers_entry_wins(self):
        from wama.common.tts import service_client
        up.create(self.author, 'git', 'fr', spelling='jite')
        with mock.patch.object(service_client, '_post') as post:
            post.return_value.content = b'RIFF'
            service_client.tts_via_service('Un git.', 'kokoro-onnx', raw=True, user=self.author,
                                           options={'lexicon': {'cache': {'spelling': 'kache'}}})
        sent = post.call_args.kwargs['json']['options']['lexicon']
        self.assertEqual({'git': {'spelling': 'jite'}, 'cache': {'spelling': 'kache'}}, sent)


class GesturesTest(_Accounts):

    def test_born_private_once_per_term_whatever_the_case(self):
        row = up.create(self.author, ' Docker ', 'fr', spelling=' dokeur ')
        self.assertEqual(('private', 'Docker', 'dokeur', 'pron_author'),
                         (row.visibility, row.term, row.spelling, row.source['created_by']))
        for term, language, spelling in (('docker', 'fr', 'x'), ('', 'fr', 'x'),
                                         ('git', 'klingon', 'x'), ('git', 'fr', '')):
            with self.assertRaises(up.PronunciationRefused, msg=(term, language, spelling)):
                up.create(self.author, term, language, spelling=spelling)

    def test_phonemes_outside_the_voice_vocabulary_are_refused(self):
        """Kokoro EFFACE sans erreur un caractère qu'il ne connaît pas — le g du clavier en tête."""
        if up._vocabulary() is None:
            self.skipTest('kokoro_onnx absent de ce venv')
        with self.assertRaises(up.PronunciationRefused) as refused:
            up.create(self.author, 'git', 'fr', phonemes='gˈit')
        self.assertIn('U+0261', str(refused.exception))
        self.assertEqual('ɡˈit', up.create(self.author, 'git', 'fr', phonemes='ɡˈit').phonemes)

    def test_only_its_author_edits_it_and_another_copies_it(self):
        row = up.create(self.author, 'git', 'fr', spelling='jite')
        up.share(self.author, row.pk, 'public')
        with self.assertRaises(up.PronunciationRefused) as edit:
            up.update(self.other, row.pk, spelling='hijack')
        self.assertEqual(403, edit.exception.status)
        mine = up.copy(self.other, pk=row.pk)
        self.assertEqual((self.other.pk, 'private', 'jite', 'pron_author:git'),
                         (mine.owner_id, mine.visibility, mine.spelling, mine.source['copied_from']))

    def test_a_system_file_entry_is_customised_into_a_private_copy(self):
        mine = up.copy(self.other, term='github', language='fr')
        self.assertEqual(('GitHub', 'ɡitˈœb', 'système:GitHub'),
                         (mine.term, mine.phonemes, mine.source['copied_from']))

    def test_an_administrator_promotes_never_over_the_file(self):
        row = up.create(self.author, 'ENA_CASA', 'fr', spelling='éna kaza')
        with self.assertRaises(up.PronunciationRefused):
            up.promote(self.other, row.pk)
        up.promote(self.admin, row.pk)
        row.refresh_from_db()
        self.assertEqual((None, 'public', 'pron_author'),
                         (row.owner_id, row.visibility, row.source['proposed_by']))
        self.assertEqual({'ENA_CASA': {'spelling': 'éna kaza'}}, up.lexicon_for(self.other, 'fr'))
        over_file = up.create(self.author, 'git', 'fr', spelling='jite')
        with self.assertRaises(up.PronunciationRefused):
            up.promote(self.admin, over_file.pk)
        self.assertEqual(self.author.pk, Pronunciation.objects.get(pk=over_file.pk).owner_id)

    def test_its_author_or_an_administrator_deletes_it(self):
        row = up.create(self.author, 'git', 'fr', spelling='jite')
        up.share(self.author, row.pk, 'public')
        with self.assertRaises(up.PronunciationRefused):
            up.delete(self.other, row.pk)
        up.delete(self.admin, row.pk)
        self.assertFalse(Pronunciation.objects.filter(pk=row.pk).exists())


class RegistryPageAndListeningTest(_Accounts):

    def test_the_registry_carries_its_rows_and_knows_the_file(self):
        from wama.common.registries import MIXED, REGISTRIES
        from wama.common.services.sharing import catalogue_owned_rows
        registry = REGISTRIES['pronunciations']
        self.assertEqual((MIXED, 'common.Pronunciation'), (registry.provenance, registry.owner_model))
        self.assertTrue(registry.in_code('GitHub'))
        self.assertFalse(registry.in_code('ENA_CASA'))
        self.assertIn('pronunciations', [r.key for r, _model in catalogue_owned_rows()])
        self.assertIn('fr:GitHub', registry.entries())

    def test_the_page_shows_the_file_and_the_accounts_rows_and_the_endpoint_obeys(self):
        up.create(self.author, 'ENA_CASA', 'fr', spelling='MINE ON THE PAGE')
        self.client.force_login(self.author)
        page = self.client.get(reverse('common:pronunciations_catalog'))
        self.assertContains(page, 'id="prMine"')
        self.assertContains(page, 'MINE ON THE PAGE')
        self.assertContains(page, 'GitHub')
        self.assertContains(page, 'data-registry="pronunciations"')
        api = reverse('common:pronunciations_manage')
        made = self.client.post(api, json.dumps({'action': 'create', 'term': 'Celery',
                                                 'language': 'fr', 'spelling': 'sélri'}),
                                content_type='application/json')
        self.assertTrue(made.json()['success'], made.content)
        pk = made.json()['pronunciation']['pk']
        self.assertEqual(403, self.client.post(api, json.dumps({'action': 'promote', 'pk': pk}),
                                               content_type='application/json').status_code)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('common:pronunciations_catalog')),
                               'MINE ON THE PAGE')

    def test_the_inline_script_of_the_served_page_parses(self):
        """Un `.js` casse dans le navigateur, jamais à la compilation : le script en ligne de la
        page SERVIE se parse par V8 (`AGENTS.md`, §JS), sans s'exécuter."""
        import re
        from py_mini_racer import MiniRacer
        self.client.force_login(self.author)
        html = self.client.get(reverse('common:pronunciations_catalog')).content.decode()
        scripts = [s for s in re.findall(r'<script>(.*?)</script>', html, re.S) if 'prPage' in s]
        self.assertEqual(1, len(scripts))
        MiniRacer().eval('(function(){' + scripts[0] + '})')

    def test_a_shared_pronunciation_is_on_the_shares_page(self):
        row = up.create(self.author, 'ENA_CASA', 'fr', spelling='éna kaza')
        up.share(self.author, row.pk, 'public')
        self.client.force_login(self.other)
        self.assertContains(self.client.get(reverse('common:shares')), 'ENA_CASA (fr)')

    def test_listening_says_the_row_one_sees_for_this_request_only(self):
        """On écoute une prononciation PARTAGÉE avant de la copier : elle est dite pour cette
        demande, sans devenir la sienne. Une ligne qu'on ne voit pas n'est pas dite."""
        row = up.create(self.author, 'git', 'fr', spelling='jite')
        self.client.force_login(self.other)
        with mock.patch('wama.views._tts_via_service', return_value='AA==') as tts:
            body = {'text': 'Je dis git.', 'pronunciation': row.pk}
            self.client.post(reverse('kokoro_tts'), json.dumps(body), content_type='application/json')
            self.assertNotIn('lexicon', tts.call_args.args[2])     # privée : invisible
            up.share(self.author, row.pk, 'public')
            self.client.post(reverse('kokoro_tts'), json.dumps(body), content_type='application/json')
        self.assertEqual({'git': {'spelling': 'jite'}}, tts.call_args.args[2]['lexicon'])
        self.assertEqual(self.other, tts.call_args.kwargs['user'])
        self.assertEqual({}, up.lexicon_for(self.other, 'fr'), "écouter n'est pas adopter")
