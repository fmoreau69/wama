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
from unittest import mock

from django.test import SimpleTestCase

from wama.common.mecanismes import Mechanism
from wama.common.services.mecanismes_scan import code_only, consumers

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


class CodeOnlyTest(SimpleTestCase):
    """A source WITHOUT its prose (`code_only`, 2026-10-19) : what a UI brick is composed of is
    read from what its code does, not from what its comments tell."""

    PICKER = Mechanism('fake_picker', 'Sélecteur', 'rôle', 'wama/common/static/common/js/picker.js')

    def test_a_file_named_in_a_comment_is_not_a_consumer_once_the_prose_is_gone(self):
        sources = {
            'wama/common/static/common/js/a.js': '/* called by picker.js */\nrun();\n// picker.js too\n',
            'wama/common/templates/common/b.html': '{# picker.js #}<!-- picker.js -->'
                                                   '{% comment %}picker.js{% endcomment %}',
            'wama/common/static/common/js/c.js': "load('/static/common/js/picker.js');",
        }
        self.assertEqual(sorted(sources), consumers(self.PICKER, sources), 'the scan reads prose')
        stripped = {rel: code_only(rel, src) for rel, src in sources.items()}
        self.assertEqual(['wama/common/static/common/js/c.js'], consumers(self.PICKER, stripped))

    def test_what_looks_like_a_comment_inside_code_is_kept(self):
        """An `accept="image/*"` opens no comment, a URL's `//` closes no line."""
        src = 'el.accept = "image/*"; load("picker.js"); /* end */ go("http://x/y");\n'
        kept = code_only('wama/common/static/common/js/d.js', src)
        for code in ('"image/*"', 'load("picker.js")', 'go("http://x/y")'):
            with self.subTest(code=code):
                self.assertIn(code, kept)
        self.assertNotIn('end', kept)

    def test_a_python_comment_goes_even_inside_a_docstring(self):
        """The rule the conformity grid had: a `# …` line written in a docstring is prose too —
        `tokenize` would keep it, and the grid then cited it as evidence."""
        kept = code_only('wama/x.py', '"""doc\n# cache_dir=X\n"""\nx = 1  # picker.js\n')
        for prose in ('picker.js', 'cache_dir'):
            with self.subTest(prose=prose):
                self.assertNotIn(prose, kept)
        self.assertIn('x = 1', kept)

    def test_lines_and_positions_are_kept_for_the_evidence_the_grid_cites(self):
        sources = {'wama/x.py': 'a = 1  # one\nb = 2\n',
                   'wama/common/static/common/js/d.js': '/* one\ntwo */ run();\n// three\ngo();\n',
                   'wama/common/templates/common/e.html': '{# one #}\n<script>\n  // two\n</script>\n'}
        for rel, src in sources.items():
            with self.subTest(rel=rel):
                kept = code_only(rel, src)
                self.assertEqual(len(src), len(kept))
                self.assertEqual(src.count('\n'), kept.count('\n'))
                self.assertNotIn('one', kept)

    def test_the_conformity_grid_reads_code_through_the_same_function(self):
        """One reading of the code without its prose (2026-10-20) : the grid had its own."""
        from wama.common.services import conformity_checker
        src = 'x = 1  # picker.js\n'
        with mock.patch('wama.common.services.mecanismes_scan.code_only',
                        lambda rel, text: 'SENTINEL'):
            self.assertEqual('SENTINEL', conformity_checker._sans_commentaires(src, '.py'))
        self.assertEqual(code_only('x.py', src), conformity_checker._sans_commentaires(src, '.py'))


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

    def test_a_top_level_module_is_read_by_its_name_alone(self):
        """A module at the root (a service run by uvicorn) has no package : the scan used to
        crash on it, and with it every reader of the map."""
        service = Mechanism('fake_service', 'Service', 'rôle', 'wama/common/x/client.py',
                            annexes=('fake_root_service.py',))
        sources = {'wama/a.py': 'import fake_root_service\n',
                   'wama/b.py': 'from fake_root_service import app\n',
                   'wama/c.py': 'from wama.fake_root_service_two import app\n'}  # contre-épreuve
        self.assertEqual(['wama/a.py', 'wama/b.py'], consumers(service, sources))

    def test_an_imported_name_that_is_itself_a_module_resolves(self):
        sources = {
            'wama/common/services/x.py': 'from ..utils import media_paths, mime_utils\n',
            'wama/common/utils/y.py': 'from . import media_paths\n',
            'wama/common/services/z.py': 'from ..utils import mime_utils\n',   # contre-épreuve
        }
        self.assertEqual(['wama/common/services/x.py', 'wama/common/utils/y.py'],
                         consumers(PATHS, sources))
