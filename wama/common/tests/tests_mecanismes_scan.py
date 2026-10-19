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


class OneFileOneOwnerTest(SimpleTestCase):
    """La règle du 2026-09-15 (« un FICHIER appartient à UN mécanisme ; la relation se DÉCLARE
    en `depends_on`, jamais en rangeant le domicile de l'un parmi les annexes de l'autre »), tenue
    là où elle COMPTE : un fichier partagé n'est compté par son NOM que par un seul propriétaire,
    les autres s'y comptent par leur symbole. Mesuré le 2026-10-17 : 18 fichiers la violaient —
    `app_registry.py` en annexe de la navigation faisait « adopter » celle-ci par toute vue qui
    importe le registre d'apps, `wama-inspector.js` faisait adopter le geste RAG par l'inspecteur."""

    def test_a_shared_file_is_counted_by_name_by_one_owner_at_most(self):
        from collections import defaultdict

        from wama.common.mecanismes import MECHANISMS
        by_name = defaultdict(list)
        for m in MECHANISMS:
            for path in (m.home, *m.annexes):
                if not m.symbol:
                    by_name[path].append(m.key)
        self.assertEqual({}, {p: keys for p, keys in by_name.items() if len(keys) > 1})

    def test_a_shared_front_home_is_counted_by_symbol_alone(self):
        """`wama-app-base.js` : domicile d'`app_base_js` ET d'`add_to_queue` ; l'ajout à la file
        ne s'adopte pas parce qu'une page charge le socle JS."""
        from wama.common.mecanismes import MECHANISMS
        add = next(m for m in MECHANISMS if m.key == 'add_to_queue')
        sources = {'wama/fake/templates/fake/index.html': "<script src='wama-app-base.js'></script>",
                   'wama/fake/static/fake/x.js': 'WamaApp.addToQueue(card);'}
        self.assertEqual(['wama/fake/static/fake/x.js'], consumers(add, sources))


class PythonSymbolIsNotReadInScriptsTest(SimpleTestCase):
    """A Python home counted by its symbol (2026-10-19) : a browser script never imports it — the
    same word there is only a word (the visitor identity, counted by a common verb, was « adopted »
    by 17 scripts through a same-named method). A template can still consume it : a tag is one."""

    VISITORS = Mechanism('fake_visitors', 'Visiteurs', 'rôle', 'wama/accounts/visitors.py',
                         symbol='enlist')

    def test_a_script_using_the_same_word_is_not_a_consumer(self):
        sources = {'wama/common/static/common/js/x.js': 'axis.enlist(el, {});',
                   'wama/accounts/views.py': 'from .visitors import enlist\nenlist(request)\n',
                   'wama/fake/templates/fake/index.html': '{% enlist %}'}
        self.assertEqual(['wama/accounts/views.py', 'wama/fake/templates/fake/index.html'],
                         consumers(self.VISITORS, sources))


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
