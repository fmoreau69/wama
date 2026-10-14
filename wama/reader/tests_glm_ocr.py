"""GLM-OCR — propriété du dossier de travail (`backends/glm_ocr_backend.py`).

Ces tests ne touchent PAS Ollama : ils portent sur ce qui fuyait, c'est-à-dire la gestion
du dossier temporaire, et cela s'observe sans modèle.

Contexte (2026-08-25) : `_pdf_to_images` créait son propre `mkdtemp` et déléguait le
nettoyage à l'appelant par un commentaire. L'appelant l'honorait — mais le contrat fuyait
dans trois situations muettes, dont celle mesurée ici : une conversion qui ÉCHOUE rend `[]`,
et la boucle de nettoyage de l'appelant, qui itère sur la liste rendue, n'avait alors plus
rien à parcourir.
"""
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


def _dossiers_glmocr() -> set:
    """Dossiers `glmocr_*` présents dans le temporaire du système."""
    return {p for p in Path(tempfile.gettempdir()).glob('glmocr_*') if p.is_dir()}


class DossierDeTravailGlmOcrTests(SimpleTestCase):

    def test_la_conversion_ecrit_dans_le_dossier_FOURNI(self):
        """`dest_dir` est honoré : la fonction ne fabrique plus son propre dossier."""
        from wama.common.backends.glm_ocr_backend import _pdf_to_images

        avant = _dossiers_glmocr()
        with tempfile.TemporaryDirectory() as fourni:
            # PDF inexistant : les deux voies (PyMuPDF puis pdf2image) échouent et la
            # fonction rend []. C'est EXACTEMENT le cas qui laissait un dossier derrière lui.
            resultat = _pdf_to_images('/introuvable/absent.pdf', dpi=72, dest_dir=fourni)
            self.assertEqual(resultat, [], "une conversion impossible doit rendre une liste vide")

        self.assertEqual(
            _dossiers_glmocr() - avant, set(),
            "un dossier `glmocr_*` a été créé alors qu'un dossier était FOURNI — "
            "la fonction ne respecte pas la propriété de l'appelant")

    def test_le_dossier_fourni_survit_a_l_appel_puis_c_est_l_APPELANT_qui_le_ferme(self):
        """La fonction n'efface pas ce qui ne lui appartient pas : le `with` de l'appelant
        est seul responsable, ce qui est précisément ce qui rend le nettoyage garanti."""
        from wama.common.backends.glm_ocr_backend import _pdf_to_images

        fourni = Path(tempfile.mkdtemp(prefix='test_glmocr_proprio_'))
        try:
            _pdf_to_images('/introuvable/absent.pdf', dpi=72, dest_dir=str(fourni))
            self.assertTrue(fourni.exists(),
                            "la fonction a supprimé un dossier qu'elle ne possède pas")
        finally:
            import shutil
            shutil.rmtree(fourni, ignore_errors=True)

    def test_describer_extrait_ses_images_dans_le_dossier_FOURNI(self):
        """Même défaut, autre app : `extract_frames` créait son dossier sans le nettoyer, et
        l'appelant retirait les FICHIERS mais jamais le DOSSIER — un `describer_frames_*`
        vide restait dans le temporaire à chaque vidéo décrite."""
        from wama.describer.backends.video_backend import extract_frames

        avant = {p for p in Path(tempfile.gettempdir()).glob('describer_frames_*') if p.is_dir()}
        with tempfile.TemporaryDirectory() as fourni:
            # Fichier inexistant : ffmpeg échoue, la fonction rend [] sans lever.
            self.assertEqual(extract_frames('/introuvable/absent.mp4', 10, 2, dest_dir=fourni), [])
        apres = {p for p in Path(tempfile.gettempdir()).glob('describer_frames_*') if p.is_dir()}
        self.assertEqual(apres - avant, set(),
                         "un dossier `describer_frames_*` a été créé alors qu'un dossier "
                         "était FOURNI")

    def test_la_brique_work_dir_efface_meme_un_dossier_NON_vide(self):
        """Le 3ᵉ défaut : l'ancien nettoyage retirait le dossier « s'il est vide », or le
        repli `pdf2image` y laisse ses propres temporaires — la condition n'était donc
        jamais remplie, y compris quand tout s'était bien passé."""
        from wama.common.utils.work_dir import work_dir

        with work_dir('glmocr_test') as d:
            (d / 'page_0000.png').write_bytes(b'x')
            (d / 'residu_de_pdf2image.ppm').write_bytes(b'y')
            chemin = Path(d)
            self.assertTrue(any(chemin.iterdir()), "le dossier doit être non vide pour le test")
        self.assertFalse(chemin.exists(), "un dossier NON VIDE doit être supprimé quand même")


class OllamaErrorIsNotAnEmptySuccessTests(SimpleTestCase):
    """Card reader #1335 (2026-10-12) : Ollama a répondu 500 « token repeat limit reached », la
    page a rendu '' et la card est passée SUCCESS à 0 caractère. Les appels sont bouchonnés : ce
    qui se mesure ici est ce que la page FAIT d'une erreur, pas le modèle."""

    def _ocr(self, answers):
        from unittest import mock

        from wama.common.backends import glm_ocr_backend
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append(kwargs.get('temperature'))
            return answers[len(calls) - 1]

        with mock.patch.object(glm_ocr_backend, '_image_to_b64', return_value='AAAA'), \
                mock.patch('wama.common.utils.llm_utils.llm_chat', side_effect=fake_chat):
            try:
                return glm_ocr_backend._ocr_image('glm-ocr:latest', '/x.jpg'), calls
            except RuntimeError as exc:
                return exc, calls

    def test_an_ollama_error_fails_the_page_instead_of_returning_empty_text(self):
        result, calls = self._ocr([(None, 'Ollama HTTP 500: token repeat limit reached')])
        self.assertIsInstance(result, RuntimeError)
        self.assertIn('token repeat limit', str(result))
        self.assertEqual(calls, [0.0], "aucun nouvel essai : échantillonné, il boucle en silence")

    def test_a_reading_followed_by_a_loop_keeps_the_first_pass(self):
        """La sortie MESURÉE sur la card #1335 redressée : la note lue juste, puis recopiée."""
        reading = ("- Personnalisé du pipeline par utilisateur. Chaque\n"
                   "utilisateur peut personnaliser / créer son propre\n"
                   "pipeline et l'utiliser dans les apps.\n")
        result, _ = self._ocr([("WAMA\n" + reading * 40, None)])
        self.assertEqual("WAMA\n" + reading.rstrip(), result)

    def test_a_loop_that_cannot_be_cut_is_a_failure_not_a_text(self):
        """Une boucle sans retour à la ligne ne se coupe pas par blocs : l'échec est DIT."""
        result, _ = self._ocr([("pipeline adapté à ses données " * 200, None)])
        self.assertIsInstance(result, RuntimeError)
        self.assertIn('boucle', str(result))

    def test_a_blank_page_and_a_real_page_stay_successes(self):
        """Contre-épreuves : une page SANS texte n'est pas une erreur, ni un long texte réel."""
        self.assertEqual(self._ocr([('', None)])[0], '')
        import random
        rng = random.Random(7)
        words = ['analyse', 'pipeline', 'données', 'utilisateur', 'modèle', 'résultat', 'voie',
                 'capteur', 'trajectoire', 'piéton', 'carrefour', 'mesure', 'seuil', 'image']
        prose = ' '.join(rng.choice(words) + str(rng.randint(0, 99)) for _ in range(600))
        self.assertEqual(self._ocr([(prose, None)])[0], prose)

    def test_a_loop_with_varying_headers_is_cut_at_the_first_return(self):
        """La forme exacte relevée sur la card #1335 redressée : des en-têtes qui varient entre
        les copies (```markdown, « I24 Rotation ») — une période exacte gardait 2,5 copies."""
        note = ("- Personnalisation du pipeline par utilisation. Chaque\n"
                "utilisateur peut personnaliser / créer son propre\n"
                "pipeline et l'utiliser dans les apps.\n"
                "⇒ il doit faire son propre pipeline adapté à ses\n"
                "propres données.\n")
        noisy = note + "WAMA\n```markdown\nI24 Rotation\n\n" + (note + "```\n```\nI24 Rotation\n") * 20
        result, _ = self._ocr([(noisy, None)])
        self.assertEqual(1, result.count('Personnalisation du pipeline'))


class UprightImageTests(SimpleTestCase):
    """`ocr_base.upright_image` — card #1335 : une note photographiée de côté, sans EXIF, que
    GLM-OCR ne lisait pas couchée. Le classifieur est bouchonné : ce qui se mesure ici est ce que
    la brique FAIT de sa prédiction (le classifieur réel est mesuré à part, cf. WAMA_LLM)."""

    def _upright(self, angle, confidence=0.95, exif_orientation=None, size=(40, 20)):
        import tempfile
        from unittest import mock

        from PIL import Image

        from wama.common.backends import ocr_base
        image = Image.new('RGB', size, 'white')
        exif = image.getexif()
        if exif_orientation:
            exif[0x0112] = exif_orientation
        work = Path(tempfile.mkdtemp(prefix='test_upright_'))
        source = work / 'photo.jpg'
        image.save(source, format='JPEG', exif=exif)
        predictor = mock.Mock(return_value=[[0], [angle], [confidence]])
        with mock.patch.object(ocr_base, '_orientation_predictor', return_value=predictor):
            result = ocr_base.upright_image(str(source), str(work))
        return source, Path(result), Image.open(result).size

    def test_a_sideways_page_is_rotated_into_a_copy(self):
        source, result, size = self._upright(90)
        self.assertNotEqual(source, result, "l'original n'est jamais réécrit")
        self.assertEqual((20, 40), size)

    def test_an_upright_page_is_returned_untouched(self):
        source, result, _ = self._upright(0)
        self.assertEqual(source, result)

    def test_an_uncertain_prediction_is_not_followed(self):
        source, result, _ = self._upright(90, confidence=0.3)
        self.assertEqual(source, result)

    def test_the_exif_orientation_is_applied_even_when_the_page_is_upright(self):
        """Le décodeur d'Ollama ignore l'EXIF : une photo de téléphone tenue de côté partait
        couchée."""
        source, result, size = self._upright(0, exif_orientation=6)
        self.assertNotEqual(source, result)
        self.assertEqual((20, 40), size)
