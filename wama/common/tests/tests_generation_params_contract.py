"""Un backend de génération ne lit que des champs qui EXISTENT dans ses paramètres (2026-09-29).

LE DÉFAUT MESURÉ. `Flux2KleinBackend.generate` lisait `params.num_inference_steps` alors que
`GenerationParams` nomme ce champ `steps` : l'AttributeError levait hors du `try`, donc TOUTE
génération FLUX.2 Klein échouait — sans qu'aucun test ne le voie, parce qu'aucun n'exécute une
génération. Relevé à l'œil, en relisant ce fichier comme voisin du rôle `backend`.

La garde est GÉNÉRIQUE et STATIQUE : pour chaque classe du paquet `backends` qui hérite
d'`ImageGenerationBackend`, les attributs `params.<x>` lus dans `generate()` doivent être des champs
de la classe de paramètres ANNOTÉE (`GenerationParams`, ou le jeu propre d'un backend vidéo), lue
par AST dans le module du backend ou dans `image_generation_base`. Rien n'est importé : un backend
qui ne s'importe pas dans ce venv reste contrôlé.
"""
import ast
from pathlib import Path

from django.test import SimpleTestCase

BACKENDS = Path(__file__).resolve().parents[1] / 'backends'


def _dataclass_fields(tree) -> dict:
    """{nom de classe: champs annotés} pour les classes d'un module."""
    out = {}
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            out[n.name] = {s.target.id for s in n.body
                           if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
    return out


def _violations(path: Path, shared: dict) -> list:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    local = _dataclass_fields(tree)
    found = []
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        if 'ImageGenerationBackend' not in {getattr(b, 'id', getattr(b, 'attr', '')) for b in cls.bases}:
            continue
        for fn in (s for s in cls.body if isinstance(s, ast.FunctionDef) and s.name == 'generate'):
            arg = next((a for a in fn.args.args if a.arg == 'params'), None)
            ann = getattr(getattr(arg, 'annotation', None), 'id', None) if arg else None
            fields = local.get(ann) or shared.get(ann)
            if not fields:
                continue                      # annotation absente ou hors portée : on ne devine pas
            for node in ast.walk(fn):
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == 'params' and node.attr not in fields
                        and not isinstance(node.ctx, ast.Store)):
                    found.append(f'{path.name}:{node.lineno} {cls.name} lit params.{node.attr} '
                                 f'(absent de {ann})')
    return found


class GenerationParamsContractTest(SimpleTestCase):

    def test_generate_reads_only_fields_its_params_define(self):
        shared = _dataclass_fields(ast.parse(
            (BACKENDS / 'image_generation_base.py').read_text(encoding='utf-8')))
        self.assertIn('steps', shared['GenerationParams'])
        found = []
        for path in sorted(BACKENDS.glob('*.py')):
            found += _violations(path, shared)
        self.assertEqual([], found)

    def test_the_guard_sees_the_defect_it_was_written_for(self):
        """Contre-épreuve : le défaut d'origine, réintroduit dans une copie, est vu."""
        import tempfile
        shared = _dataclass_fields(ast.parse(
            (BACKENDS / 'image_generation_base.py').read_text(encoding='utf-8')))
        source = (BACKENDS / 'flux2_klein_backend.py').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / 'flux2_klein_backend.py'
            broken.write_text(source.replace('int(params.steps or', 'int(params.num_inference_steps or'),
                              encoding='utf-8')
            found = _violations(broken, shared)
        self.assertTrue(any('num_inference_steps' in f for f in found), found)
