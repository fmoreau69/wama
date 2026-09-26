"""Les types MIME que WAMA déclare au démarrage — ce que le navigateur recevra.

`settings.py` pose une table MIME explicite (`mimetypes.add_type`) parce que l'OS décide sinon :
sous Windows, la table vient du REGISTRE, et ce qu'il ignore part en `text/plain` ou en
`application/octet-stream`. Deux conséquences vécues :
  • un `.m4a` servi en octet-stream ne se lit pas dans une balise `<audio>` ;
  • un `.mjs` servi en `text/plain` est REFUSÉ par le contrôle MIME strict des modules ES —
    mesuré le 2026-09-23, `talkinghead.mjs` cassé sur le serveur de dev (jamais en production,
    où whitenoise sert juste), ce qui faisait échouer la garde « console propre » de tout smoke
    navigateur : 9/10 gestes au lieu de 10/10, un faux rouge à chaque campagne.

Aucune garde ne tenait cette table : cinq types y dormaient depuis des mois sans test. Elle est
posée pour les SIX ensemble — une garde se pose avec ses jumeaux.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import mimetypes

from django.test import SimpleTestCase

# Ce que WAMA déclare, et la famille attendue (pas le libellé exact : `text/javascript` et
# `application/javascript` sont tous deux acceptés par les navigateurs).
DECLARED = {
    '.m4a': ('audio/mp4',),
    '.aac': ('audio/aac',),
    '.ogg': ('audio/ogg',),
    '.flac': ('audio/flac',),
    '.weba': ('audio/webm',),
    '.mjs': ('text/javascript', 'application/javascript'),
}


class DeclaredMimeTypesTest(SimpleTestCase):

    def test_every_declared_extension_is_served_with_its_type(self):
        for extension, accepted in DECLARED.items():
            with self.subTest(extension=extension):
                guessed, _ = mimetypes.guess_type('file' + extension)
                self.assertIn(guessed, accepted,
                              f'{extension} servi en {guessed!r} : l\'OS décide à notre place')

    def test_an_undeclared_extension_stays_unknown(self):
        """Contre-épreuve : sans elle, le test passerait même si la table était vide."""
        guessed, _ = mimetypes.guess_type('file.wamaxyz')
        self.assertIsNone(guessed)
