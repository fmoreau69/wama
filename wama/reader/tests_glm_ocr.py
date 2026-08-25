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
        from wama.reader.backends.glm_ocr_backend import _pdf_to_images

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
        from wama.reader.backends.glm_ocr_backend import _pdf_to_images

        fourni = Path(tempfile.mkdtemp(prefix='test_glmocr_proprio_'))
        try:
            _pdf_to_images('/introuvable/absent.pdf', dpi=72, dest_dir=str(fourni))
            self.assertTrue(fourni.exists(),
                            "la fonction a supprimé un dossier qu'elle ne possède pas")
        finally:
            import shutil
            shutil.rmtree(fourni, ignore_errors=True)

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
