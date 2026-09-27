"""Une librairie qu'on importe DOIT être déclarée — même quand son absence ne plante pas.

Trou mesuré le 2026-09-27 (question de Fabien) : `librosa`, `soundfile` et `datasets` étaient
importées par la chaîne des voix de référence et ne figuraient dans AUCUN `requirements*.txt` ;
`datasets` n'avait même pas de manifeste. Personne ne l'avait vu, et pour une raison précise :
`voice_refs.py` les prend dans des `try/except ImportError` qui **dégradent en silence**. Sur
une machine sans `librosa`, la vérification du genre par la hauteur est simplement SAUTÉE — or
c'est elle qui avait trouvé 12 voix sur 25 en contradiction avec leur libellé.

*Une dépendance non déclarée dont l'absence ne plante pas ne manque à personne — jusqu'au jour
où son contrôle ne s'exécute plus.*

⚠ La garde relève les imports par **AST**, et seulement ceux des modules DÉCLARÉS ci-dessous :
elle n'essaie pas de deviner tout le dépôt (le vendoré, les extras d'un backend et la
bibliothèque standard produiraient un bruit qu'on finirait par désactiver). Ajouter un module à
`SOUS_SURVEILLANCE` est le geste qui étend la garde — il se fait quand un module devient une
CHAÎNE dont on dépend, pas par principe.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import ast
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)

#: Les modules dont TOUS les imports de tiers doivent être déclarés.
SOUS_SURVEILLANCE = (
    'wama/common/tts/voice_refs.py',
    'wama/common/utils/web_search.py',
    'wama/common/search_engines/base.py',
)

#: Ce qui n'a pas à figurer aux requirements : la bibliothèque standard employée ici, et ce que
#: WAMA fournit lui-même. Liste COURTE à dessein — un écart doit se voir.
IGNORED = {
    'os', 'sys', 're', 'io', 'json', 'time', 'math', 'shutil', 'random', 'logging', 'hashlib',
    'pathlib', 'tempfile', 'datetime', 'collections', 'statistics', 'subprocess', 'warnings',
    'functools', 'itertools', 'typing', 'dataclasses', 'abc', 'urllib', 'unittest', 'csv',
    'wave',   # stdlib : lecture/écriture WAV — oublié à la 1re rédaction, et la garde l'a dit
    'wama', 'django', '__future__', 'wama_data', 'wama_lab',
}

#: Nom d'import → nom de distribution, quand les deux diffèrent.
DISTRIBUTION = {'bs4': 'beautifulsoup4', 'PIL': 'pillow', 'yaml': 'pyyaml', 'fitz': 'pymupdf'}


def _declared() -> set:
    """Les distributions déclarées dans les `requirements*.txt`, en minuscules."""
    noms = set()
    for source_file in BASE.glob('requirements*.txt'):
        for line in source_file.read_text(encoding='utf-8').splitlines():
            line = line.split('#')[0].strip()
            if not line or line.startswith('-'):
                continue
            nom = re.split(r'[<>=!~\[ ]', line, 1)[0].strip()
            if nom:
                noms.add(nom.lower().replace('_', '-'))
    return noms


def _imported(path: Path) -> set:
    """Les modules TIERS importés par ce fichier — imports paresseux compris (c'est justement
    là que vivent ceux qui dégradent en silence)."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    racines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            racines.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            racines.add(node.module.split('.')[0])
    return {r for r in racines if r not in IGNORED}


class OptionalImportsAreDeclaredTest(SimpleTestCase):

    def test_every_third_party_import_of_a_watched_module_is_in_requirements(self):
        declared = _declared()
        missing = []
        for rel in SOUS_SURVEILLANCE:
            path = BASE / rel
            if not path.exists():
                continue
            for module in sorted(_imported(path)):
                dist = DISTRIBUTION.get(module, module).lower().replace('_', '-')
                if dist not in declared:
                    missing.append(f'{rel} importe `{module}` — absent des requirements')
        self.assertEqual([], missing, '\n'.join(missing))

    def test_the_voice_chain_libraries_also_have_their_manifest(self):
        """Le manifeste est l'autre moitié : il porte identité, licence et version installée.
        `datasets` était importée, non déclarée ET sans manifeste — les trois trous à la fois."""
        manifests = {p.stem.lower() for p in (BASE / 'manifests' / 'libraries').glob('*.json')}
        for lib in ('librosa', 'soundfile', 'datasets'):
            self.assertIn(lib, manifests, f'`{lib}` n\'a pas de manifeste library')

    def test_the_watched_list_names_files_that_exist(self):
        """Contre-épreuve : une garde qui surveille des fichiers disparus ne surveille RIEN, et
        reste verte pour cette raison — le pire état possible pour un contrôle."""
        for rel in SOUS_SURVEILLANCE:
            self.assertTrue((BASE / rel).exists(), f'{rel} : fichier surveillé introuvable')
