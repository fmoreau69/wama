"""
WAMA Synthesizer - Tests
"""

import os
import tempfile
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models import VoiceSynthesis, VoicePreset
from .utils.text_extractor import (
    extract_text_from_file,
    clean_text_for_tts,
    estimate_reading_time,
    split_text_by_sentences
)
from .utils.audio_processor import (
    process_audio_output,
    get_audio_duration,
    normalize_audio
)

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


class VoicePresetModelTest(TestCase):
    """Tests pour le modèle VoicePreset."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

        # Créer un fichier audio temporaire
        self.audio_file = SimpleUploadedFile(
            "reference.wav",
            b"fake audio content",
            content_type="audio/wav"
        )

    def test_create_preset(self):
        """Test de création d'un preset."""
        preset = VoicePreset.objects.create(
            name="Test Voice",
            description="A test voice preset",
            reference_audio=self.audio_file,
            language='en',
            gender='male',
            created_by=self.user
        )

        self.assertEqual(preset.name, "Test Voice")
        self.assertEqual(preset.language, 'en')
        self.assertEqual(preset.gender, 'male')
        self.assertEqual(preset.created_by, self.user)


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

    def test_estimate_reading_time(self):
        """Test de l'estimation du temps de lecture."""
        text = " ".join(["word"] * 150)  # 150 mots
        time = estimate_reading_time(text, wpm=150)

        self.assertAlmostEqual(time, 60, delta=5)  # ~60 secondes

    def test_split_text_by_sentences(self):
        """Test de la division en phrases."""
        text = "Première phrase. Deuxième phrase! Troisième phrase?"
        chunks = split_text_by_sentences(text, max_length=30)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 30)


class ViewsTest(TestCase):
    """Tests pour les vues."""

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise()     # cf. _utilisateur_autorise : le 302 venait du gating
        # `force_login` plutôt que `client.login` : convention du dépôt (tests_volet,
        # tests_memory, tests_codegen_lot) et évite de traverser le backend LDAP en tête
        # d'`AUTHENTICATION_BACKENDS` pour rien — ces tests portent sur les VUES.
        self.client.force_login(self.user)

        self.text_file = SimpleUploadedFile(
            "test.txt",
            b"Test content",
            content_type="text/plain"
        )

    def test_index_view(self):
        """Test de la page d'index."""
        response = self.client.get(reverse('synthesizer:index'))

        self.assertEqual(response.status_code, 200)
        # ⚠ l'assertion précédente cherchait « WAMA Synthesizer » — chaîne qui n'a JAMAIS
        # existé dans ce gabarit (elle ne vit que dans des docstrings et les libellés
        # `AIModel.source`). Elle était donc fausse depuis toujours, mais le 302 du gating
        # échouait AVANT elle et la masquait : lever une cause en découvre une plus vieille.
        # On ancre désormais sur le titre réel ET sur un élément propre à CETTE app —
        # le volet de paramètres — pour que le test distingue « la page a rendu » de
        # « seul le gabarit de base a rendu ».
        self.assertContains(response, "Synthesizer - Text To Speech")
        self.assertContains(response, 'id="synthPanelParams"')

    def test_upload_view(self):
        """Test de l'upload."""
        response = self.client.post(
            reverse('synthesizer:upload'),
            {
                'file': self.text_file,
                'tts_model': 'kokoro',
                'language': 'fr',
                'speed': 1.0,
                'pitch': 1.0
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('id', data)
        self.assertEqual(data['status'], 'PENDING')

    def test_upload_invalid_format(self):
        """Test d'upload avec format invalide."""
        invalid_file = SimpleUploadedFile(
            "test.xyz",
            b"Invalid content",
            content_type="application/octet-stream"
        )

        response = self.client.post(
            reverse('synthesizer:upload'),
            {'file': invalid_file}
        )

        self.assertEqual(response.status_code, 400)

    def test_start_synthesis(self):
        """Test du démarrage d'une synthèse."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file,
            text_content="Test content"
        )

        response = self.client.get(
            reverse('synthesizer:start', args=[synthesis.id])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('task_id', data)

    def test_progress_view(self):
        """Test de la vue de progression."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file,
            status='RUNNING',
            progress=50
        )

        response = self.client.get(
            reverse('synthesizer:progress', args=[synthesis.id])
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'RUNNING')
        self.assertGreaterEqual(data['progress'], 0)

    def test_delete_view(self):
        """Test de suppression."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        response = self.client.post(
            reverse('synthesizer:delete', args=[synthesis.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            VoiceSynthesis.objects.filter(id=synthesis.id).exists()
        )

    def test_unauthorized_access(self):
        """Test d'accès non autorisé."""
        other_user = User.objects.create_user(
            username='otheruser',
            password='testpass123'
        )

        synthesis = VoiceSynthesis.objects.create(
            user=other_user,
            text_file=self.text_file
        )

        response = self.client.get(
            reverse('synthesizer:start', args=[synthesis.id])
        )

        self.assertEqual(response.status_code, 404)


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
        response = self.client.get(
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


class PerformanceTest(TestCase):
    """Tests de performance."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_bulk_create(self):
        """Test de création en masse."""
        syntheses = []
        for i in range(100):
            text_file = SimpleUploadedFile(
                f"test_{i}.txt",
                b"Test content",
                content_type="text/plain"
            )
            syntheses.append(
                VoiceSynthesis(
                    user=self.user,
                    text_file=text_file,
                    text_content="Test content"
                )
            )

        VoiceSynthesis.objects.bulk_create(syntheses)
        self.assertEqual(VoiceSynthesis.objects.count(), 100)

    def test_query_optimization(self):
        """Test d'optimisation des requêtes."""
        # Créer des synthèses
        for i in range(10):
            text_file = SimpleUploadedFile(
                f"test_{i}.txt",
                b"Test content",
                content_type="text/plain"
            )
            VoiceSynthesis.objects.create(
                user=self.user,
                text_file=text_file
            )

        # Requête optimisée avec select_related
        with self.assertNumQueries(1):
            list(VoiceSynthesis.objects.select_related('user').all())

# Pour exécuter les tests:
# python manage.py test synthesizer

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
