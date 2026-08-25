"""Nom de fichier proposé au TÉLÉCHARGEMENT — encodage de `Content-Disposition`.

Contexte (2026-08-25, symptôme signalé par Fabien : « plusieurs fois des soucis d'affichage
des noms de fichiers à cause de l'encodage »). Onze vues écrivaient l'en-tête à la main :

    response['Content-Disposition'] = f'attachment; filename="{nom}"'

Un en-tête HTTP est transmis en latin-1. Django ne lève pas — il replie sur un encodage MIME
(`=?utf-8?b?…?=`) que les navigateurs n'interprètent PAS pour un nom de fichier : l'utilisateur
recevait un nom abîmé. La forme correcte est la RFC 5987 (`filename*=utf-8''…`), et Django la
produit lui-même via `content_disposition_header` — le dépôt savait d'ailleurs la LIRE
(`common/utils/video_utils.py:135`) sans savoir l'écrire.

⚠ Ces tests comptent d'autant plus que la brique de nommage PRÉSERVE désormais les accents
du nom d'origine (décision du 2026-08-25) : les noms non-ASCII sont passés de l'exception à
la norme, donc l'exposition à ce défaut a AUGMENTÉ.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.utils.http import content_disposition_header


class EncodageDuNomTelechargeTests(SimpleTestCase):

    def test_un_nom_accentue_part_en_RFC_5987(self):
        entete = content_disposition_header(True, "Réunion équipe_voice_xtts.wav")
        self.assertIn("filename*=utf-8''", entete)
        self.assertNotIn('Réunion', entete, "le nom brut ne doit pas voyager en latin-1")
        self.assertIn('R%C3%A9union', entete)

    def test_un_nom_ASCII_garde_la_forme_SIMPLE(self):
        """Compatibilité maximale : on ne complique pas ce qui n'en a pas besoin."""
        self.assertEqual(content_disposition_header(True, "rapport.pdf"),
                         'attachment; filename="rapport.pdf"')


class PasDeRecidiveTests(SimpleTestCase):
    """⚠ Garde-fou. Le défaut était RECOPIÉ dans 7 fichiers de vues : le corriger une fois ne
    protège de rien si le prochain copie l'idiome d'à côté. Ce test échoue à la RÉAPPARITION.
    """

    #: `f'attachment; filename="…"'` ou `inline` — l'en-tête composé à la main.
    IDIOME = re.compile(r"""f['"](attachment|inline); filename=""")

    def test_aucune_vue_n_ecrit_Content_Disposition_a_la_main(self):
        racine = Path(settings.BASE_DIR)
        coupables = []
        for chemin in list(racine.glob('wama/*/views.py')) + list(racine.glob('wama_lab/*/views.py')):
            for num, ligne in enumerate(chemin.read_text(encoding='utf-8').splitlines(), 1):
                if self.IDIOME.search(ligne):
                    coupables.append(f"{chemin.relative_to(racine)}:{num}")
        self.assertEqual(
            coupables, [],
            "en-tête Content-Disposition écrit à la main — utiliser "
            "`django.utils.http.content_disposition_header(as_attachment, nom)`, "
            "qui bascule seul en RFC 5987 sur un nom non-ASCII :\n  "
            + "\n  ".join(coupables))
