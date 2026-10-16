"""A library or a model is installed by the ROUTE, never beside it (`AGENTS.md`, « LA ROUTE
D'INSTALLATION », Fabien's decision of 2026-10-16 : « Aucune dérive acceptée, sauf si je le
demande explicitement »).

The route is ONE family of code : the model installer (`install_from_spec` and its drivers
`hf` / `github` / `files` / `yolo` / `ollama`, `pip_install_packages` behind `install_library`),
the prospection that measures what it will install, and the load-time lever B of the doctrine
(`hf_weights.poids_locaux`). Any other module that DOWNLOADS weights or RUNS pip is a drift : it
skips the catalogue, the installation log, the disk-space guard, the uninstall, the token of a
gated repository — the defects measured on 2026-10-16, when the MuScriptor backend fetched the
Beat This! checkpoint itself while the `files` driver did exactly that.

The scan reads the CODE (AST, defined calls), not names in strings. Three declared lists :
  * `ROUTE` : the route itself ;
  * `DATA` : downloads of DATA (evaluation corpora, benchmark tables, reference voices), which
    are neither models nor libraries — each with its reason ;
  * `DRIFT_BUDGET` : the drifts that existed when the rule was written, per file. It can ONLY GO
    DOWN : a new site fails, and so does a site that has been ported without lowering the budget
    (a margin is a permission to add one).
"""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOTS = ('wama', 'wama_lab', 'wama_data')
SKIPPED_PARTS = {'vendor', 'migrations', 'tests', '__pycache__', 'static', 'staticfiles'}

#: Direct downloads of weights and pip runs, by the called name.
DOWNLOAD_CALLS = {'download_asset', 'urlretrieve', 'load_state_dict_from_url',
                  'download_url_to_file', 'hf_hub_download', 'snapshot_download',
                  'pip_install_packages'}

ROUTE = {
    'wama/model_manager/services/model_installer.py': "the installer and its drivers",
    'wama/model_manager/services/prospector.py': "measures the digest of what it will install, "
                                                 "in a throwaway folder",
    'wama/common/utils/hf_weights.py': "load-time lever B of the doctrine (`poids_locaux`)",
}
DATA = {
    'wama/model_manager/services/benchmark_sync.py': "benchmark result tables (datasets)",
    'wama/transcriber/management/commands/asr_eval_corpus.py': "evaluation corpus (dataset)",
    'wama/common/tts/voice_refs.py': "reference voices (audio files of the media library)",
}
#: Measured on 2026-10-16. Port each one to the route, then LOWER its count (0 = remove the line).
DRIFT_BUDGET = {
    'wama_lab/cam_analyzer/utils/road_model_downloader.py': 1,   # YOLOPv2 : a `github` spec, fetched beside `install_from_spec`
    'wama/model_manager/services/bench.py': 1,                   # LPIPS's AlexNet through `torch.hub`
    'wama/common/backends/image_to_3d_backend.py': 2,            # TripoSR at first load, beside `poids_locaux`
    'wama/model_manager/services/memory_manager.py': 1,          # single-file diffusion weights at load
}


def _called_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ''


def _runs_pip(call: ast.Call) -> bool:
    """A subprocess whose argument list names `pip` and `install` (`[python, '-m', 'pip', …]`)."""
    for arg in call.args:
        if isinstance(arg, (ast.List, ast.Tuple)):
            words = {e.value for e in arg.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if 'pip' in words and 'install' in words:
                return True
    return False


def scan(base: Path) -> dict:
    """{relative path: number of direct downloads / pip runs} over the code roots. The sandbox
    twins (`app_sandbox`) are left out, as everywhere : they are generated copies, never
    versioned — their original is scanned."""
    from wama.common.sandbox import sandbox_labels
    twins = set(sandbox_labels())
    found = {}
    for root in ROOTS:
        for path in (base / root).rglob('*.py'):
            rel = path.relative_to(base)
            if (SKIPPED_PARTS & set(rel.parts[:-1]) or rel.name.startswith('tests')
                    or twins & set(rel.parts[:2])):
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Call)
                        and (_called_name(node) in DOWNLOAD_CALLS or _runs_pip(node)))
            if count:
                found[rel.as_posix()] = count
    return found


class InstallRouteTest(SimpleTestCase):

    def test_nothing_downloads_weights_or_runs_pip_beside_the_route(self):
        found = scan(Path(settings.BASE_DIR))
        outside = {path: n for path, n in found.items() if path not in ROUTE and path not in DATA}
        new = {p: n for p, n in outside.items() if n > DRIFT_BUDGET.get(p, 0)}
        self.assertEqual({}, new, "a NEW drift : install through the route (`install_from_spec`, "
                                  "the `files` driver with declared origins, `install_library`) "
                                  "— never a download or a pip run of your own")
        ported = {p: (DRIFT_BUDGET[p], outside.get(p, 0)) for p in DRIFT_BUDGET
                  if outside.get(p, 0) < DRIFT_BUDGET[p]}
        self.assertEqual({}, ported, "a drift was ported : LOWER its budget (a margin is a "
                                     "permission to add one)")

    def test_the_declared_lists_name_files_that_still_exist(self):
        base = Path(settings.BASE_DIR)
        for path in (*ROUTE, *DATA, *DRIFT_BUDGET):
            self.assertTrue((base / path).exists(), path)
