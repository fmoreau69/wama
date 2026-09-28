"""
WAMA Synthesizer - Tests
"""

import os
import tempfile
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models import VoiceSynthesis
from .utils.text_extractor import extract_text_from_file, clean_text_for_tts

User = get_user_model()


def _utilisateur_autorise(username='testuser'):
    """User de test AYANT le droit d'ouvrir le synthesizer.

    ⚠ Sans le rôle, les 8 tests de vues échouaient sur `302 != 200` — et ce message ne
    désigne PAS le coupable : ni l'URL, ni l'authentification. C'est
    `AppAccessMiddleware` (`wama/accounts/middleware.py`) qui, AVANT toute vue, interroge
    `accessible(user, 'synthesizer')` et redirige vers `home` quand c'est faux. La
    politique (`permissions.py`, `DEFAULT_APP_ACCESS`) exige le rôle `communication` pour
    cette app, et un `create_user` nu n'appartient à aucun groupe.

    Le rôle est donc accordé ICI, comme le fait `nightly_tests.get_test_user()` : un test
    de VUES doit FRANCHIR le portier, pas le contourner. Le neutraliser (superuser,
    `@override_settings` sans le middleware) rendrait ces tests aveugles à une régression
    du gating, qui est précisément un mécanisme transverse à surveiller.
    """
    from django.contrib.auth.models import Group
    from wama.accounts.permissions import GROUP_PREFIX
    user = User.objects.create_user(username=username, password='testpass123')
    group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')
    user.groups.add(group)
    return user


class VoiceSynthesisModelTest(TestCase):
    """Tests pour le modèle VoiceSynthesis."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

        # Créer un fichier texte temporaire
        self.text_content = "Ceci est un test de synthèse vocale."
        self.text_file = SimpleUploadedFile(
            "test.txt",
            self.text_content.encode('utf-8'),
            content_type="text/plain"
        )

    def test_create_synthesis(self):
        """Test de création d'une synthèse."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file,
            tts_model='coqui-xtts',
            language='fr'
        )

        self.assertEqual(synthesis.user, self.user)
        self.assertEqual(synthesis.status, 'PENDING')
        self.assertEqual(synthesis.tts_model, 'coqui-xtts')
        self.assertEqual(synthesis.language, 'fr')

    def test_filename_property(self):
        """Test de la propriété filename."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        self.assertIn('test.txt', synthesis.filename)

    def test_estimate_duration(self):
        """Test de l'estimation de durée."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        synthesis.text_content = "Ceci est un test " * 150  # 300 mots
        synthesis.word_count = 300
        synthesis.speed = 1.0

        duration = synthesis.estimate_duration()
        self.assertGreater(duration, 0)
        self.assertLess(duration, 300)  # Moins de 5 minutes

    def test_format_duration(self):
        """Test du formatage de durée."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        self.assertEqual(synthesis.format_duration(65), "1:05")
        self.assertEqual(synthesis.format_duration(120), "2:00")
        self.assertEqual(synthesis.format_duration(0), "0:00")

    def test_update_metadata(self):
        """Test de la mise à jour des métadonnées."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        synthesis.text_content = "Ceci est un test de synthèse vocale."
        synthesis.update_metadata()

        self.assertEqual(synthesis.word_count, 7)
        self.assertGreater(synthesis.duration_seconds, 0)
        self.assertIsNotNone(synthesis.duration_display)


class TextExtractorTest(TestCase):
    """Tests pour l'extracteur de texte."""

    def test_extract_from_txt(self):
        """Test d'extraction depuis TXT."""
        # ⚠ lecture et suppression APRÈS le `with` : sous Windows un fichier encore ouvert
        # n'est ni relisible par un autre descripteur ni supprimable (PermissionError).
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test text content")
            chemin = f.name
        try:
            self.assertEqual(extract_text_from_file(chemin), "Test text content")
        finally:
            os.unlink(chemin)

    def test_clean_text_for_tts(self):
        """Test du nettoyage de texte."""
        dirty_text = "Test   with   spaces\n\n\nand http://example.com URLs"
        clean = clean_text_for_tts(dirty_text)

        self.assertNotIn("http://", clean)
        self.assertNotIn("   ", clean)


# `ViewsTest` RETIRÉ le 2026-09-26 : ses 7 tests (page, dépôt, extension refusée, ▶, progression,
# suppression, élément d'autrui) sont tenus pour TOUTES les apps par les contrats génériques
# (`common/tests_endpoints`, `tests_import_contract`, `tests_item_lifecycle_contract`,
# `tests_queue_delete_contract`) — `WAMA_VERIFICATION §8`.


class IntegrationTest(TestCase):
    """Tests d'intégration."""

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise()     # cf. ViewsTest.setUp
        self.client.force_login(self.user)

    def test_full_workflow(self):
        """Test du workflow complet."""
        # 1. Upload
        text_file = SimpleUploadedFile(
            "test.txt",
            b"Ceci est un test de synthese vocale.",
            content_type="text/plain"
        )

        response = self.client.post(
            reverse('synthesizer:upload'),
            {
                'file': text_file,
                'tts_model': 'kokoro',
                'language': 'fr',
                'speed': 1.0,
                'pitch': 1.0
            }
        )

        self.assertEqual(response.status_code, 200)
        synthesis_id = response.json()['id']

        # 2. Vérifier la synthèse créée
        synthesis = VoiceSynthesis.objects.get(id=synthesis_id)
        self.assertEqual(synthesis.status, 'PENDING')

        # 3. Démarrer (sans vraiment exécuter Celery en test)
        response = self.client.post(
            reverse('synthesizer:start', args=[synthesis_id])
        )
        self.assertEqual(response.status_code, 200)

        # 4. Vérifier le statut
        synthesis.refresh_from_db()
        self.assertEqual(synthesis.status, 'RUNNING')

        # 5. Simuler la complétion
        # ⚠ la progression a DEUX canaux : le cache (fil temps réel, lu EN PREMIER par
        # `views.progress`) et la colonne en base (repli). Écrire la seule colonne, comme
        # le faisait ce test, laissait le cache à 0 posé par `start` — la vue répondait
        # donc 0 alors que la base disait 100. Ce n'est pas un défaut de l'app : son
        # écrivain, `workers._set_progress`, tient les deux canaux ensemble. Le test
        # passe donc par LUI plutôt que de recopier la clé de cache ici (une clé recopiée
        # est une clé qui divergera).
        from wama.synthesizer.workers import _set_progress
        _set_progress(synthesis, 100)
        synthesis.status = 'SUCCESS'
        synthesis.save(update_fields=['status'])

        # 6. Vérifier la progression
        response = self.client.get(
            reverse('synthesizer:progress', args=[synthesis_id])
        )
        data = response.json()
        self.assertEqual(data['status'], 'SUCCESS')
        self.assertEqual(data['progress'], 100)


# `PerformanceTest` RETIRÉ le 2026-09-26 : il testait l'ORM de Django (bulk_create,
# select_related), pas un comportement de WAMA.


class ConfinementServerPathTest(TestCase):
    """🔴 Traversée de chemin refusée (2026-09-05, `MEDIA_STORAGE_TIERING §8.6` D1).

    `import_individual_from_path` faisait `Path(MEDIA_ROOT) / server_path` sans `resolve()`
    ni contrôle : un `../../…` lisait n'importe quel fichier du serveur et injectait son
    texte dans une card. La vue passe désormais par la brique commune de confinement —
    ce test franchit le portier (rôle `communication`) et exige le REFUS, jamais un 404
    qui laisserait croire que le chemin a simplement été cherché.
    """

    def setUp(self):
        self.user = _utilisateur_autorise('confinement')
        self.client = Client()
        self.client.login(username='confinement', password='testpass123')

    def test_un_server_path_qui_remonte_hors_de_media_est_refuse_403(self):
        # Un fichier qui EXISTE hors de MEDIA_ROOT : sans la garde, la vue le lirait.
        rep = self.client.post(reverse('synthesizer:import_individual_from_path'),
                               {'server_path': '../manage.py'})
        self.assertEqual(rep.status_code, 403, rep.content[:200])
        self.assertFalse(VoiceSynthesis.objects.filter(user=self.user).exists(),
                         'aucune card ne doit naître d\'un chemin refusé')

    def test_le_meme_refus_vaut_pour_le_lot_depuis_server_path(self):
        rep = self.client.post(reverse('synthesizer:batch_create'),
                               {'server_path': '../manage.py'})
        self.assertEqual(rep.status_code, 403, rep.content[:200])


class PanelVoiceFieldIsGeneratedTest(TestCase):
    """Le champ de voix du VOLET est GÉNÉRÉ du schéma depuis le 2026-09-23.

    Les quatre optgroups écrits dans le gabarit (défaut / références / « Mes voix » / Bark)
    redisaient à la main ce que `get_voice_groups` sert déjà à la modale d'item, à
    l'avatarizer et à l'endpoint commun — et cette copie-là ne savait pas dire les voix
    PARTAGÉES. Ce que ces gardes tiennent, c'est ce qui pouvait casser SANS lever :
      • le champ n'est plus dans le gabarit → un `<option>` réapparu y serait un retour en
        arrière muet (la page marcherait, avec deux inventaires qui divergent) ;
      • un select généré n'a pas de `name=` en contexte 'panel' → un lecteur qui n'interroge
        que `[name=]` cesse d'enregistrer la voix, sans erreur ni trace ;
      • le groupe « Mes voix » se retrouve par sa CLÉ, plus par un id de gabarit — sinon la
        voix qu'on vient de cloner atterrit dans un groupe recréé, ailleurs et autrement
        libellé.
    """

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise('panel_voice_user')
        self.client.force_login(self.user)

    def _page(self):
        return self.client.get(reverse('synthesizer:index')).content.decode('utf-8')

    def _template_source(self):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / 'wama' / 'synthesizer' / 'templates' / 'synthesizer'
                / 'index.html').read_text(encoding='utf-8')

    def test_the_panel_carries_a_host_instead_of_hand_written_voice_options(self):
        page = self._page()
        self.assertIn('id="voicePresetHost"', page)
        self.assertIn('id="voicePresetGroup"', page,
                      'la zone enveloppe reste : Higgs la masque, voiceSlot la désigne')
        # Une seule des dix options Bark suffit à signer la liste écrite à la main.
        self.assertNotIn('<option value="bark_v2_en_0"', page)
        self.assertNotIn('id="customVoicesGroup"', page)

    def test_the_page_serves_the_common_voice_groups_with_their_keys(self):
        import json
        page = self._page()
        line = next(text_line for text_line in page.splitlines()
                    if text_line.strip().startswith('var voiceGroups = '))
        groups = json.loads(line.split('=', 1)[1].strip().rstrip(';'))
        keys = [g['key'] for g in groups]
        # « mine » est TOUJOURS là, même sans voix clonée : c'est là qu'on insère la suivante.
        self.assertIn('default', keys)
        self.assertIn('mine', keys)
        self.assertIn('bark', keys)

    def test_the_generated_field_points_at_the_common_voice_source(self):
        from wama.synthesizer.params import PARAMS_JSON
        param = next(p for p in PARAMS_JSON if p['name'] == 'voice_preset')
        self.assertEqual('voices', param['options_source'])
        self.assertEqual('voice_preset', param['dom_id']['panel'],
                         'le JS d\'app lit le select par cet id — il ne doit pas bouger')

    def test_the_panel_saver_reads_generated_fields_too(self):
        self.assertIn('data-param="\' + k + \'"', self._template_source())

    def test_the_app_js_finds_the_voice_group_by_its_key(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for path in (base / 'wama' / 'synthesizer' / 'static' / 'synthesizer' / 'js' / 'index.js',
                     base / 'staticfiles' / 'synthesizer' / 'js' / 'index.js'):
            if not path.exists():
                continue
            js = path.read_text(encoding='utf-8')
            self.assertIn('optgroup[data-group-key="', js, path.name)
            self.assertNotIn('customVoicesGroup', js, path.name)
            # L'app ANNONCE que les options ont changé ; elle ne les écoute plus. Le seul
            # auditeur d'app (le miroir de la card d'entrée) a été retiré le 2026-09-27 avec
            # les contrôles qu'il servait — l'annonce, elle, reste indispensable : c'est ce
            # qui fait rejouer les filtres de capacité sur une voix fraîchement clonée.
            self.assertIn("dispatchEvent(new CustomEvent('wama:options-filled'", js, path.name)

    def test_the_voice_field_is_rendered_by_an_inline_script(self):
        """Le rendu du champ vit dans un script EN LIGNE du gabarit. Que TOUS les scripts en
        ligne de TOUTES les pages se parsent est tenu par le contrat générique
        `common/tests_served_assets_contract` (2026-09-26) ; reste ici ce qui est propre au
        synthesizer — le rendu du champ de voix est bien DANS un de ces blocs, sans quoi le
        contrat attesterait d'autres blocs pendant que celui-ci manquerait."""
        import re
        blocks = re.findall(r'<script>(.*?)</script>', self._page(), re.S)
        self.assertTrue(any('renderPanelVoiceField' in b for b in blocks),
                        'le rendu du champ de voix n\'est plus dans un script en ligne')


class VoicePreviewSharesTheSynthesisChainTest(TestCase):
    """L'aperçu de voix passe par LA chaîne de la synthèse (2026-09-28).

    Il avait la sienne (préparation en cache + flux SSE + WAV recollés par le navigateur) et
    n'entendait donc pas ce que la synthèse produirait : texte non nettoyé, « auto » envoyé tel
    quel au service, options Higgs ignorées (CARD_DESIGN §11.11 Étape 3, note sur l'aperçu).
    Le service TTS est SIMULÉ (un vrai WAV d'une demi-seconde) : on mesure ce que la vue lui
    envoie et la forme de ce qu'elle rend, pas la voix.
    """

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise('voice_preview_user')
        self.client.force_login(self.user)
        self.calls = []

    def _fake_service(self, text, model, **kwargs):
        import wave
        self.calls.append({'text': text, 'model': model, **kwargs})
        handle, path = tempfile.mkstemp(suffix='.wav')
        os.close(handle)
        with wave.open(path, 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(8000)
            out.writeframes(b'\x00\x10' * 4000)
        return path

    def _post(self, **fields):
        from unittest import mock
        data = {'text_content': 'Bonjour 🎧 à tous.', 'tts_model': 'synthesizer:kokoro',
                'voice_preset': 'default', 'language': 'fr', 'speed': '1.0', 'pitch': '1.0'}
        data.update(fields)
        with mock.patch('wama.synthesizer.utils.speech_render.tts_via_service',
                        side_effect=self._fake_service), \
                mock.patch('wama.common.services.resource_governor.release_in_progress',
                           return_value=False):
            return self.client.post(reverse('synthesizer:voice_preview'), data)

    def test_the_preview_answers_with_a_common_preview_payload(self):
        response = self._post()
        self.assertEqual(200, response.status_code, response.content[:300])
        data = response.json()
        self.assertEqual('audio/wav', data['mime_type'])
        self.assertIn('/partials/voice_preview.wav?v=', data['url'])
        self.assertTrue(data['peaks'], 'sans pics, le lecteur commun retéléchargerait le fichier')

    def test_the_text_is_cleaned_like_the_synthesis(self):
        self._post()
        self.assertNotIn('🎧', self.calls[0]['text'], 'text_for_speech non appliqué')

    def test_auto_is_resolved_before_reaching_the_service(self):
        from unittest import mock
        with mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                        return_value='synthesizer:kokoro') as resolve:
            self._post(tts_model='auto')
        resolve.assert_called_once()
        self.assertEqual('synthesizer:kokoro', self.calls[0]['model'])

    def test_higgs_options_reach_the_service(self):
        self._post(multi_speaker='1', scene_description='[S1] une femme')
        self.assertTrue(self.calls[0]['multi_speaker'])
        self.assertEqual('[S1] une femme', self.calls[0]['scene_description'])

    def test_worker_and_preview_share_one_render_function(self):
        from wama.synthesizer import workers
        from wama.synthesizer.utils import speech_render
        self.assertIs(workers.render_speech, speech_render.render_speech)
        self.assertIs(workers.resolve_tts_model, speech_render.resolve_tts_model)
        self.assertFalse(hasattr(workers, '_synthesize_via_service'),
                         'une 2ᵉ chaîne de rendu est revenue dans le worker')

    def test_the_segment_limit_reads_the_full_catalog_key(self):
        """La table est indexée par le nom NU : une clé entière la ratait (800 pour tous)."""
        from wama.synthesizer.utils.speech_render import chunk_limit, split_text_into_chunks
        self.assertEqual(400, chunk_limit('synthesizer:kokoro'))
        chunks = split_text_into_chunks('Une phrase. ' * 60, 400)
        self.assertTrue(all(len(c) <= 400 for c in chunks))
        self.assertGreater(len(chunks), 1)


class SynthesisIsHeardWhileItGrowsTest(TestCase):
    """Aperçu « PENDANT » (2026-09-28) : l'audio déjà synthétisé est publié après chaque segment
    d'un texte long, par la brique commune (`publish_partial` + pics → face `?side=during`)."""

    def _wav(self, frames):
        import wave
        handle, path = tempfile.mkstemp(suffix='.wav')
        os.close(handle)
        with wave.open(path, 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(8000)
            out.writeframes(b'\x00\x10' * frames)
        return path

    def _render(self, text, on_partial):
        from unittest import mock
        from wama.synthesizer.utils import speech_render
        out = tempfile.mkdtemp()
        with mock.patch.object(speech_render, 'tts_via_service',
                               side_effect=lambda *a, **k: self._wav(8000)):
            return speech_render.render_speech(
                text, os.path.join(out, 'final.wav'), model='synthesizer:kokoro',
                language='fr', voice_preset='default', on_partial=on_partial)

    def test_a_long_text_is_published_segment_after_segment(self):
        from pydub import AudioSegment
        seen = []
        final = self._render('Une phrase assez longue pour remplir. ' * 30,
                             lambda audio, done, total: seen.append((len(audio), done, total)))
        total = seen[0][2]
        self.assertGreater(total, 2, 'le texte devait tenir en plusieurs segments')
        self.assertEqual([done for _, done, _ in seen], list(range(1, total)),
                         'un partiel après chaque segment, SAUF le dernier (le résultat le remplace)')
        self.assertTrue(all(a < b for (a, _, _), (b, _, _) in zip(seen, seen[1:])), "l'audio doit grandir")
        # Le fichier final est inchangé : chaque segment d'une seconde suivi de 200 ms de silence.
        self.assertEqual(total * 1200, len(AudioSegment.from_wav(final)))

    def test_a_single_segment_has_nothing_to_show_before_its_result(self):
        seen = []
        self._render('Bonjour.', lambda *args: seen.append(args))
        self.assertEqual([], seen)

    def test_the_worker_publishes_the_during_face_then_clears_it(self):
        from types import SimpleNamespace
        from django.test import RequestFactory
        from pydub import AudioSegment
        from wama.common.utils.preview_utils import _during_preview_data
        from wama.synthesizer import workers
        synthesis = SimpleNamespace(id=987654, user_id=987654, speed=1.0, pitch=1.0)
        workers._during_preview(synthesis)(AudioSegment.from_wav(self._wav(8000)), 1, 3)
        request = RequestFactory().get('/')
        data = _during_preview_data('synthesizer', SimpleNamespace(pk=synthesis.id), request)
        self.assertIsNotNone(data, 'la capacité est déclarée et un partiel est publié : la face doit exister')
        self.assertIn('/partials/during_987654', data['url'])
        self.assertTrue(data['peaks'])
        workers._clear_during(synthesis)
        self.assertIsNone(_during_preview_data('synthesizer', SimpleNamespace(pk=synthesis.id), request))


class TheEntryCardKeepsOneHomePerSettingTest(TestCase):
    """La card d'entrée ne duplique plus les réglages du volet (constat de Fabien, 2026-09-27).

    Elle annonçait elle-même « Modèle, langue et options avancées : volet de droite » tout en
    portant un sélecteur de voix et un curseur de vitesse. Deux domiciles pour un même réglage,
    et le second n'avait pas de source propre : il RECOPIAIT le volet, donc il se réparait
    (recâblé sur `wama:options-filled` quand le select est devenu généré) au lieu de servir.

    ⚠ Ce que cette garde tient vraiment : que le retrait n'ait pas emporté ce que le volet
    doit encore offrir. Un contrôle retiré d'un côté DOIT exister de l'autre.
    """

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise('entry_card_user')
        self.client.force_login(self.user)

    def _page(self):
        return self.client.get(reverse('synthesizer:index')).content.decode('utf-8')

    def test_the_entry_card_no_longer_mirrors_voice_and_speed(self):
        page = self._page()
        self.assertNotIn('id="textVoiceQuick"', page)
        self.assertNotIn('id="textSpeedQuick"', page)
        self.assertIn('id="textTitle"', page, 'le titre reste : il n\'existe QUE là')

    def test_what_the_card_removed_the_panel_still_offers(self):
        """Contre-épreuve : la voix et la vitesse n'ont pas disparu de la page, elles n'ont
        plus qu'UN domicile — le volet."""
        page = self._page()
        self.assertIn('id="voicePresetHost"', page)     # champ de voix GÉNÉRÉ du schéma
        self.assertIn('id="speed"', page)               # curseur de vitesse du volet

    def test_no_dead_reference_to_the_removed_mirror(self):
        """Un JS qui lirait encore les ids retirés serait muet, jamais en erreur."""
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for path in (base / 'wama' / 'synthesizer' / 'static' / 'synthesizer' / 'js' / 'index.js',
                     base / 'staticfiles' / 'synthesizer' / 'js' / 'index.js'):
            if not path.exists():
                continue
            js = path.read_text(encoding='utf-8')
            for dead in ('textVoiceQuick', 'textSpeedQuick', 'cloneVoiceOptions'):
                self.assertNotIn(dead, js, f'{dead} dans {path.name}')

    def test_the_voice_preview_lives_once_in_the_panel(self):
        """L'aperçu fait entendre des RÉGLAGES : il a suivi la voix et la vitesse au volet
        (2026-09-28, CARD_DESIGN §11.11 Étape 3 (b)). Un seul exemplaire, hors de la card, et
        tout ce que `index.js` en lit est rendu — un id perdu rendrait l'aperçu muet."""
        from pathlib import Path

        from django.conf import settings
        page = self._page()
        for dom_id in ('previewTextBtn', 'previewAudioContainer'):
            self.assertEqual(1, page.count(f'id="{dom_id}"'), dom_id)
        card_zone = (Path(settings.BASE_DIR) / 'wama' / 'synthesizer' / 'templates' / 'synthesizer'
                     / '_new_item_extra.html').read_text(encoding='utf-8')
        self.assertNotIn('previewTextBtn', card_zone, "l'aperçu est revenu dans la card d'entrée")
        self.assertNotIn('volet de droite', card_zone.split('{% endcomment %}')[-1],
                         'la card commune le dit pour toutes les apps — pas de phrase par app')
