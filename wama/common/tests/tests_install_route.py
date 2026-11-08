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

The scan reads the CODE (AST, defined calls), not names in strings — the named download calls,
pip runs, and since 2026-11-06 any HTTP response body written to a file. Three declared lists :
  * `ROUTE` : the route itself ;
  * `DATA` : downloads of DATA (evaluation corpora, benchmark tables, reference voices), which
    are neither models nor libraries — each with its reason ;
  * `DRIFT_BUDGET` : the drifts that existed when the rule was written, per file. It can ONLY GO
    DOWN : a new site fails, and so does a site that has been ported without lowering the budget
    (a margin is a permission to add one). EMPTY since 2026-10-16 (all ported).

A model NEEDED at task time is not a drift (Fabien, 2026-10-16) — an INCOMPLETE install beside the
route is : the task asks the route (`model_readiness.ensure_installed`), the user is told, the task
waits ; the load-time levers of `hf_weights` remain for a row the route cannot install.
"""
import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

# The reading itself is the common brick (`download_calls`, 2026-11-08) : the backend role reads
# the same sites in a vendored engine's code.
from wama.common.utils.download_calls import download_sites

ROOTS = ('wama', 'wama_lab', 'wama_data')
SKIPPED_PARTS = {'vendor', 'migrations', 'tests', '__pycache__', 'static', 'staticfiles'}

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
    # A response body written to a file (seen since 2026-11-06, `download_calls.writes_a_response_body`):
    'wama/common/utils/video_utils.py': "a media the user imports by its URL (`url_ingest`)",
    'wama/common/utils/url_ingest.py': "a web page the user imports as an input (`fetch_html_page`)",
    'wama/common/tts/service_client.py': "the audio the LOCAL voice service has just rendered — "
                                         "nothing is fetched from outside",
}
#: Measured on 2026-10-16 at 5 sites in 4 files, ALL ported the same week (Fabien : « on aligne
#: tout ») : YOLOPv2 (a declared row the cam_analyzer asks the route for), LPIPS's AlexNet (a
#: `quality-metric` row the bench installs and waits for), TripoSR (declared files), the dead
#: single-file diffusion loader (removed, REMOVAL_LEDGER R148). EMPTY : any entry is a new drift.
DRIFT_BUDGET = {}


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
            count = len(download_sites(tree))
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

    def test_a_response_body_written_to_a_file_is_a_download(self):
        """2026-11-06 : the anonymizer fetched YOLO weights by a streamed `requests.get` written to
        a file, which no named call showed. Both forms count; an upload copied by `chunks()` and a
        body read in memory do not."""
        import tempfile
        code = {
            'streamed.py': "for chunk in r.iter_content(8192):\n    f.write(chunk)\n",
            'whole.py': "f.write(resp.content)\n",
            'upload.py': "for chunk in upload.chunks():\n    out.write(chunk)\n",
            'in_memory.py': "for part in r.iter_content(8192):\n    parts.append(part)\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'wama').mkdir()
            for name, text in code.items():
                (Path(tmp) / 'wama' / name).write_text(text, encoding='utf-8')
            self.assertEqual({'wama/streamed.py': 1, 'wama/whole.py': 1}, scan(Path(tmp)))
