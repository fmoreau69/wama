"""Le chargement À LA DEMANDE d'un script ou d'une feuille de style passe par la plomberie
commune (`WamaApp.loadScript`, `WamaApp.loadStyle`, `wama-app-base.js`) — 2026-10-28.

Trouvé à la revérification du volet en briques : le module du volet recopiait le chargeur de
script que le chat de l'assistant et l'ajout à la médiathèque recopiaient déjà chacun en privé,
et le chargeur de feuille de la main virtuelle. Ce test tient l'absence de copie, sans V8 : aucun
JS de WAMA hors de `wama-app-base.js` ne crée lui-même une balise `<script>` ou `<link>`.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

HOME = 'wama/common/static/common/js/wama-app-base.js'
#: Une balise de chargement créée à la main.
CREATED = re.compile(r"""createElement\(\s*['"](script|link)['"]\s*\)""")


class EveryLoaderIsTheCommonOneTest(SimpleTestCase):

    def test_no_script_creates_its_own_script_or_link_tag(self):
        base = Path(settings.BASE_DIR)
        found = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (base / root).rglob('*.js'):
                rel = path.relative_to(base).as_posix()
                # Le code tiers (vendorisé, ou livré minifié comme jQuery) n'est pas le nôtre.
                if ('vendors' in path.parts or 'staticfiles' in path.parts or rel == HOME
                        or path.name.endswith('.min.js')):
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                found += [f'{rel} : <{m.group(1)}>' for m in CREATED.finditer(text)]
        self.assertEqual([], found, 'charger par WamaApp.loadScript / WamaApp.loadStyle')

    def test_the_common_loaders_are_exported(self):
        source = (Path(settings.BASE_DIR) / HOME).read_text(encoding='utf-8')
        self.assertIn('loadScript: loadScript,', source)
        self.assertIn('loadStyle: loadStyle,', source)
        self.assertEqual(1, len(CREATED.findall(source.split('function loadStyle')[0])),
                         'un seul chargeur de script')
