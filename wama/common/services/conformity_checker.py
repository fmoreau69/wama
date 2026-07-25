"""Vérification AUTOMATISÉE de conformité des apps — confrontation au RÉEL.

Remplace la saisie manuelle des booléens `_conv(...)` d'app_registry par des checks
exécutables (analyse statique du code de chaque app). Organisation par facettes
F1–F8 de `WAMA_APP_GENERATION_ROUTE.md` ; critères issus des conventions
(`WAMA_APP_CONVENTIONS.md`, checklist `TRANSCRIBER_REFERENCE_AUDIT.md §6`) et de
l'audit empirique 2026-07-25 (critères M1–M26).

Chaque check retourne (état, preuve) :
    True      conforme (brique commune consommée)
    'partial' présent mais partiel OU implémentation locale au lieu de la brique
    False     absent / non conforme
    None      non mesurable / N/A pour cette app

Module PUR (stdlib seulement, pas d'import Django) → utilisable par la management
command, les tests nocturnes, ou un hook. Les résultats sont écrits en JSON
(`logs/conformity_report.json`) et fusionnés dans `get_conformity_summary()`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

WAMA_ROOT = Path(__file__).resolve().parents[2]          # wama/


# ── Accès fichiers (cache par app) ────────────────────────────────────────────────

class _AppFiles:
    def __init__(self, app: str):
        self.app = app
        self.root = WAMA_ROOT / app
        self._cache: dict[str, str] = {}

    def _read(self, path: Path) -> str:
        key = str(path)
        if key not in self._cache:
            try:
                self._cache[key] = path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                self._cache[key] = ''
        return self._cache[key]

    def glob(self, pattern: str) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(p for p in self.root.glob(pattern) if p.is_file())

    def find(self, patterns: list[str], regex: str) -> str | None:
        """Première occurrence de `regex` dans les fichiers matchant `patterns`.
        Retourne une preuve 'chemin/relatif:ligne' ou None."""
        rx = re.compile(regex)
        for pattern in patterns:
            for path in self.glob(pattern):
                text = self._read(path)
                m = rx.search(text)
                if m:
                    line = text.count('\n', 0, m.start()) + 1
                    rel = path.relative_to(WAMA_ROOT).as_posix()
                    return f"{rel}:{line}"
        return None

    def text(self, patterns: list[str]) -> str:
        return '\n'.join(self._read(p) for pattern in patterns for p in self.glob(pattern))


TEMPLATES = ['templates/**/*.html']
JS = ['static/**/*.js']
VIEWS = ['views.py', 'views/*.py']
MODELS = ['models.py', 'models/*.py']
TASKS = ['tasks.py', 'workers.py', 'tasks/*.py']
URLS = ['urls.py']
APPS_PY = ['apps.py']
CARD_TPL = ['templates/**/*card*.html', 'templates/**/index.html', 'templates/**/media_table.html']


# ── Critères ─────────────────────────────────────────────────────────────────────

@dataclass
class Criterion:
    key: str          # clé du rapport ; si égale à une clé `_conv`, ÉCRASE la valeur déclarée
    facette: str      # F1..F8 (route)
    label: str
    fn: object        # callable(_AppFiles) -> (state, evidence)


def _present(f: _AppFiles, patterns, regex, label_ok=None):
    ev = f.find(patterns, regex)
    return (True, ev) if ev else (False, None)


def _tool_api_triad(f: _AppFiles):
    text = (WAMA_ROOT / 'tool_api.py').read_text(encoding='utf-8', errors='replace')
    # On ne regarde que le bloc TOOL_REGISTRY (les clés effectivement exposées).
    m = re.search(r'TOOL_REGISTRY\s*=\s*\{(.*?)\n\}', text, re.S)
    block = m.group(1) if m else text
    keys = [f"'add_to_{f.app}'", f"'start_{f.app}'", f"'get_{f.app}_status'"]
    found = [k for k in keys if k in block]
    if len(found) == 3:
        return True, f"tool_api.py TOOL_REGISTRY ({', '.join(keys)})"
    if found:
        missing = [k for k in keys if k not in found]
        return 'partial', f"tool_api.py: manquent {', '.join(missing)}"
    return False, None


def _url_ingest(f: _AppFiles):
    ev = f.find(MODELS, r'WAMA_INGEST')
    if ev:
        return True, ev
    ev = f.find(MODELS, r'source_url')
    if ev:
        return 'partial', f"{ev} (source_url local, pas WAMA_INGEST/ensure_local_input)"
    return False, None


def _batch_import(f: _AppFiles):
    js = f.find(TEMPLATES, r'batch-import\.js')
    srv = f.find(VIEWS + ['utils/*.py'], r'batch_parsers|parse_unified_batch|parse_media_list_batch')
    if js and srv:
        return True, f"{js} + {srv}"
    if js or srv:
        return 'partial', js or srv
    return False, None


def _inspector_adapters(f: _AppFiles):
    prev = f.find(APPS_PY, r'register_app_preview|PreviewRegistry\.register')
    det = f.find(APPS_PY, r'register_app_detail')
    if prev and det:
        return True, f"{prev} + detail"
    if prev or det:
        return 'partial', prev or det
    return False, None


def _eta_seeded(f: _AppFiles):
    rec = f.find(TASKS, r'record_run')
    est = f.find(VIEWS, r'\bestimate\(')
    if rec and est:
        return True, f"{rec} + {est}"
    if rec or est:
        return 'partial', rec or est
    return False, None


_START_DEF = re.compile(r'^def\s+((?:re)?start\w*|batch_start\w*)\s*\(', re.M)
_LOCK = re.compile(r'begin_processing|select_for_update|cache\.add\(')  # cache.add = verrou atomique (pattern anonymizer)


def _anti_race(f: _AppFiles):
    """CHAQUE vue de démarrage (start/restart/start_all/batch_start) qui enfile une
    tâche (.delay) doit verrouiller (begin_processing OU select_for_update)."""
    results, evid = [], []
    for pattern in VIEWS:
        for path in f.glob(pattern):
            text = path.read_text(encoding='utf-8', errors='replace')
            rel = path.relative_to(WAMA_ROOT).as_posix()
            defs = list(_START_DEF.finditer(text))
            for i, m in enumerate(defs):
                end = defs[i + 1].start() if i + 1 < len(defs) else len(text)
                # borne aussi sur la prochaine def quelconque
                nxt = re.search(r'^def\s+\w+', text[m.end():end], re.M)
                body_end = m.end() + nxt.start() if nxt else end
                body = text[m.start():body_end]
                if '.delay(' not in body and 'apply_async' not in body:
                    continue  # pas une vue d'enfilement
                line = text.count('\n', 0, m.start()) + 1
                ok = bool(_LOCK.search(body))
                results.append(ok)
                if not ok:
                    evid.append(f"{rel}:{line} {m.group(1)}() SANS verrou")
    if not results:
        return None, None  # aucune vue de démarrage détectée (spécificité)
    if all(results):
        return True, f"{len(results)} vue(s) de démarrage verrouillée(s)"
    if any(results):
        return 'partial', ' ; '.join(evid[:3])
    return False, ' ; '.join(evid[:3])


def _toast(f: _AppFiles):
    toast = f.find(JS, r'WamaApp\.toast')
    alert_ev = f.find(JS, r'(?<![.\w])alert\(')
    if toast and not alert_ev:
        return True, toast
    if toast and alert_ev:
        return 'partial', f"alert() résiduel: {alert_ev}"
    return False, alert_ev


def _duplicate_wiring(f: _AppFiles):
    data_url = f.find(TEMPLATES, r'data-duplicate-url')
    local = f.find(JS, r"\.duplicate-btn|duplicate-btn'\)|duplicate-btn\"\)")
    if data_url and not local:
        return True, data_url
    if data_url and local:
        return False, f"DOUBLE-FIRE possible: brique + handler local {local}"
    if local:
        return 'partial', f"{local} (impl locale, brique queue-actions non consommée)"
    return False, None


def _user_settings(f: _AppFiles):
    brick = f.find(VIEWS + URLS, r'user_settings')
    if brick:
        return True, brick
    local = f.find(MODELS, r'class UserSettings')
    if local:
        return 'partial', f"{local} (modèle local, pas la brique commune)"
    return False, None


def _queue_manipulation(f: _AppFiles):
    fab = f.find(VIEWS, r'make_queue_manipulation_views')
    if fab:
        return True, fab
    cons = f.find(URLS, r'consolidate')
    if cons:
        return 'partial', f"{cons} (consolidate seul)"
    return False, None


def _queue_toolbar(f: _AppFiles):
    tpl = f.find(TEMPLATES, r"common/_queue_toolbar\.html")
    srv = f.find(VIEWS, r'apply_queue_sort_filter')
    if tpl and srv:
        return True, f"{tpl} + {srv}"
    if tpl or srv:
        return 'partial', tpl or srv
    return False, None


def _params_modal(f: _AppFiles):
    render = f.find(TEMPLATES + JS, r'WamaParams\.render')
    if render:
        return True, render
    if (f.root / 'params.py').is_file():
        return False, "params.py existe mais WamaParams.render jamais appelé"
    return False, None


def _console(f: _AppFiles):
    blk = f.find(TEMPLATES, r'block console_app_name')
    url = f.find(URLS, r"'console/?'|\"console/?\"")
    if blk and url:
        return True, f"{blk} + {url}"
    if blk or url:
        return 'partial', blk or url
    return False, None


def _btn_order(f: _AppFiles):
    """M1 — ordre canonique ⚙▶⬇⧉🗑 dans le template de card (best effort)."""
    markers = [r'fa-cog|fa-gear', r'_cycle_button\.html|fa-play|fa-redo', r'fa-download',
               r'fa-copy|fa-clone', r'fa-trash']
    best = None
    for path in f.glob('templates/**/*card*.html') + f.glob('templates/**/index.html'):
        text = path.read_text(encoding='utf-8', errors='replace')
        pos = [re.search(m, text) and re.search(m, text).start() for m in markers]
        if all(p is not None for p in pos):
            rel = path.relative_to(WAMA_ROOT).as_posix()
            if pos == sorted(pos):
                return True, rel
            best = ('partial', f"{rel} (les 5 boutons présents, ordre non canonique)")
    return best if best else (False, "5 boutons ⚙▶⬇⧉🗑 jamais réunis dans un template de card")


CRITERIA: list[Criterion] = [
    # ── F1 identité / intégration transverse ──
    Criterion('tool_api', 'F1', 'Triade tool_api (add_to/start/get_status) au TOOL_REGISTRY', _tool_api_triad),
    Criterion('console', 'F1', 'Console app (bloc + endpoint)', _console),
    Criterion('help_about', 'F1', 'Vues Aide / À-propos',
              lambda f: _present(f, VIEWS, r'class (Help|About)View')),
    # ── F2 entrée ──
    Criterion('new_item_card', 'F2', "Card d'entrée commune _new_item_card",
              lambda f: _present(f, TEMPLATES, r"common/_new_item_card\.html")),
    Criterion('drag_drop', 'F2', 'Zone drag & drop',
              lambda f: _present(f, TEMPLATES + JS, r'drop_zone_id|drop-zone|dragover')),
    Criterion('url_ingest', 'F2', 'Import URL déclaratif (WAMA_INGEST + ensure_local_input)', _url_ingest),
    Criterion('batch_import', 'F2', 'Import batch unifié (batch-import.js + batch_parsers)', _batch_import),
    Criterion('media_library_slot', 'F2', 'Slot médiathèque sur la card d’entrée',
              lambda f: _present(f, TEMPLATES, r'show_media_library')),
    # ── F3 UI / params / inspecteur ──
    Criterion('settings_modal_item', 'F3', 'Modale paramètres générée (WamaParams.render)', _params_modal),
    Criterion('init_from_schema', 'F3', 'Volet droit initFromSchema',
              lambda f: _present(f, TEMPLATES + JS, r'initFromSchema')),
    Criterion('inspector_adapters', 'F3', 'Adapters preview + detail (apps.py)', _inspector_adapters),
    Criterion('inspector_actions', 'F3', 'Actions clonées dans le volet (_inspector_actions)',
              lambda f: _present(f, TEMPLATES, r"common/_inspector_actions\.html")),
    Criterion('settings_modal_footer', 'F3', 'Pied de modale commun (_settings_modal_footer)',
              lambda f: _present(f, TEMPLATES, r"common/_settings_modal_footer\.html")),
    Criterion('model_help', 'F3', 'Descriptif moteur (wama-model-help)',
              lambda f: _present(f, TEMPLATES + JS, r'wama-model-help|WamaModelHelp')),
    # ── F4 modèles ──
    Criterion('eta_seeded', 'F4', 'ETA seedée auto-apprenante (record_run + estimate)', _eta_seeded),
    # ── F5 cycle de vie ──
    Criterion('anti_race', 'F5', 'Verrou anti-race sur TOUTES les vues de démarrage', _anti_race),
    Criterion('reconcile_orphans', 'F5', 'Réconciliation RUNNING orphelins (IndexView)',
              lambda f: _present(f, VIEWS, r'reconcile_orphaned_running')),
    Criterion('auto_wrap_orphans', 'F5', 'Auto-wrap des items hors batch',
              lambda f: _present(f, VIEWS, r'auto_wrap_orphans')),
    Criterion('processing_time', 'F5', 'ProcessingTimeMixin (temps réel persisté)',
              lambda f: _present(f, MODELS, r'ProcessingTimeMixin')),
    Criterion('status_vocab', 'F5', 'Vocabulaire de statuts SUCCESS/FAILURE en base',
              lambda f: _present(f, MODELS, r"'SUCCESS'")),
    Criterion('cycle_button', 'F5', 'Bouton de cycle commun (_cycle_button)',
              lambda f: _present(f, TEMPLATES, r"common/_cycle_button\.html")),
    Criterion('card_html_endpoint', 'F5', 'Card = partial serveur + endpoint card_html',
              lambda f: _present(f, URLS, r'card_html')),
    Criterion('batch_card_common', 'F5', 'Card mère de batch commune (_batch_card)',
              lambda f: _present(f, TEMPLATES, r"common/_batch_card\.html")),
    Criterion('build_batches_list', 'F5', 'Agrégats de file communs (build_batches_list)',
              lambda f: _present(f, VIEWS, r'build_batches_list')),
    Criterion('queue_manipulation', 'F5', 'Manipulation directe (fabrique 4 vues)', _queue_manipulation),
    Criterion('queue_toolbar', 'F5', 'Tri/filtre communs (queue_view + _queue_toolbar)', _queue_toolbar),
    Criterion('wama_card', 'F5', 'Contrat CSS .wama-card sur la card',
              lambda f: _present(f, CARD_TPL, r'wama-card')),
    Criterion('card_progress_brick', 'F5', 'Brique _card_progress/_card_state',
              lambda f: _present(f, TEMPLATES, r"common/_card_progress\.html|common/_card_state\.html")),
    Criterion('eta_individual', 'F5', 'ETA affichée par card (.wama-eta)',
              lambda f: _present(f, TEMPLATES, r'wama-eta')),
    Criterion('eta_queue', 'F5', 'Barre globale (_global_progress)',
              lambda f: _present(f, TEMPLATES, r"common/_global_progress\.html")),
    Criterion('toast', 'F5', 'WamaApp.toast (zéro alert())', _toast),
    Criterion('duplicate_wiring', 'F5', 'Duplication via la brique (handler UNIQUE)', _duplicate_wiring),
    Criterion('duplicate_instance', 'F5', 'duplicate_instance() (brique commune)',
              lambda f: _present(f, VIEWS, r'duplicate_instance')),
    Criterion('safe_delete', 'F5', 'safe_delete_file() (fichiers partagés)',
              lambda f: _present(f, VIEWS, r'safe_delete_file')),
    Criterion('user_settings', 'F5', 'Réglages user persistés (brique user_settings)', _user_settings),
    Criterion('start_all', 'F5', 'Vue start_all',
              lambda f: _present(f, URLS, r'start_all|start-all')),
    Criterion('clear_all', 'F5', 'Vue clear_all',
              lambda f: _present(f, URLS, r'clear_all|clear-all')),
    Criterion('download_all', 'F5', 'Vue download_all',
              lambda f: _present(f, URLS, r'download_all|download-all')),
    Criterion('batch_template', 'F5', 'Gabarit batch téléchargeable',
              lambda f: _present(f, URLS, r'batch_template|batch-template')),
    Criterion('btn_order', 'F5', 'Ordre canonique des boutons ⚙▶⬇⧉🗑', _btn_order),
]


def run_checks(app_ids: list[str]) -> dict:
    """Exécute tous les critères sur chaque app. Retourne le rapport sérialisable."""
    report = {'criteria': {c.key: {'facette': c.facette, 'label': c.label} for c in CRITERIA},
              'apps': {}}
    for app in app_ids:
        f = _AppFiles(app)
        conv, evidence = {}, {}
        for c in CRITERIA:
            try:
                state, ev = c.fn(f)
            except Exception as exc:  # un check cassé ne doit pas invalider le rapport
                state, ev = None, f'CHECK ERROR: {exc}'
            if state is not None:
                conv[c.key] = state
            if ev:
                evidence[c.key] = ev
        ok = sum(1 for v in conv.values() if v is True)
        partial = sum(1 for v in conv.values() if v == 'partial')
        total = len(conv)
        report['apps'][app] = {
            'conv': conv, 'evidence': evidence,
            'score': ok, 'partial': partial, 'total': total,
            'pct': int((ok + 0.5 * partial) / total * 100) if total else 100,
        }
    return report
