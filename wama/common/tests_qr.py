"""
Brique QR (`common/utils/qr.py`) — tests.

La préoccupation n'est pas « segno marche » mais la SCANNABILITÉ réelle : le PNG produit
est DÉCODÉ par OpenCV (`QRCodeDetector`), comme le ferait un smartphone. Un test qui se
contenterait de « le PNG existe » attesterait une adoption, jamais un fonctionnement.

Lancer : `python manage.py test wama.common.tests_qr` (venv WSL).
"""
import cv2
import numpy as np
from django.test import SimpleTestCase

from wama.common.utils.qr import qr_png, qr_svg


def _decode(png: bytes) -> str:
    """Décode un PNG de QR comme un lecteur réel — rend '' s'il est illisible."""
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    contenu, _, _ = cv2.QRCodeDetector().detectAndDecode(image)
    return contenu


class QrTests(SimpleTestCase):

    def test_le_png_se_scanne_et_rend_la_donnee_exacte(self):
        url = 'https://wama.exemple.fr/accounts/profile/?link_code=K7M2P9QR'
        self.assertEqual(_decode(qr_png(url)), url)

    def test_une_donnee_courte_ne_produit_pas_un_micro_qr(self):
        # `segno.make` (sans `_qr`) aurait choisi ici un Micro QR — que beaucoup de
        # lecteurs de smartphone ne décodent pas, OpenCV non plus : ce décodage
        # échouerait. C'est la garde de `_make`.
        self.assertEqual(_decode(qr_png('A1')), 'A1')

    def test_le_svg_est_vectoriel_et_autonome(self):
        svg = qr_svg('https://wama.exemple.fr/')
        self.assertIn('<svg', svg)
        self.assertIn('</svg>', svg)
