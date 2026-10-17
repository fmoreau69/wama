"""Le balayage d'ADOPTION des mécanismes (`mecanismes_scan.consumers`) ne confond plus deux
modules de même nom (2026-10-17).

Demande de Fabien : *« peux-tu ajouter les mesures ? »* — la liste des mécanismes de niveau app
sans critère de grille. Avant d'écrire un critère, il a fallu constater que la LISTE mentait :
l'alternative relative du détecteur (`from [.\\w]*\\.?<feuille> import`) acceptait n'importe quel
paquet devant la feuille. `wama/gateway/services.py` (appariement d'identité Discord) était
« adopté » par les dix apps, parce que chacune fait `from .services import …` ou
`from wama.media_library.services import …` — 3016 faux consommateurs au registre. Et dans l'autre
sens, un vrai import relatif (`from ..services import bench`) n'était pas vu — 242 manquants.
L'import relatif est désormais RÉSOLU depuis le dossier du fichier qui importe.
"""
from django.test import SimpleTestCase

from wama.common.mecanismes import Mechanism
from wama.common.services.mecanismes_scan import consumers

GATEWAY = Mechanism('fake_gateway', 'Passerelle', 'rôle', 'wama/gateway/services.py')
PATHS = Mechanism('fake_paths', 'Chemins', 'rôle', 'wama/common/utils/media_paths.py')


class ScanResolvesImportsTest(SimpleTestCase):

    def test_a_same_named_module_of_another_package_is_not_a_consumer(self):
        sources = {
            'wama/reader/views.py': 'from .services import read_file\n',
            'wama/composer/views.py': 'from wama.media_library.services import export_item\n',
            'wama/imager/tasks.py': 'from ..converter.services import convert\n',
        }
        self.assertEqual([], consumers(GATEWAY, sources))

    def test_an_import_that_resolves_to_the_home_is_a_consumer_in_every_form(self):
        sources = {
            'wama/gateway/core.py': 'from .services import pair_identity\n',
            'wama/gateway/bots/discord.py': 'from ..services import pair_identity\n',
            'wama/accounts/views.py': 'from wama.gateway.services import pair_identity\n',
            'wama/accounts/api.py': 'from wama.gateway import services\n',
            'wama/accounts/admin.py': 'from wama.gateway import (\n    core,\n    services,\n)\n',
        }
        self.assertEqual(sorted(sources), consumers(GATEWAY, sources))

    def test_an_imported_name_that_is_itself_a_module_resolves(self):
        sources = {
            'wama/common/services/x.py': 'from ..utils import media_paths, mime_utils\n',
            'wama/common/utils/y.py': 'from . import media_paths\n',
            'wama/common/services/z.py': 'from ..utils import mime_utils\n',   # contre-épreuve
        }
        self.assertEqual(['wama/common/services/x.py', 'wama/common/utils/y.py'],
                         consumers(PATHS, sources))
