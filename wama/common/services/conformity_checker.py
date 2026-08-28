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

    def find_code(self, patterns: list[str], regex: str) -> str | None:
        """Comme `find`, mais les COMMENTAIRES sont neutralisés avant la recherche.

        POURQUOI (mesuré le 2026-08-19). `find` est un regex brut sur le texte : le critère
        `inspector_adapters` était VERT pour imager parce que son `apps.py` portait la ligne
        `# NB : PAS de register_app_preview pour l'instant` — un commentaire qui disait
        exactement le CONTRAIRE de ce que le critère concluait. Une grille qu'un commentaire
        peut faire mentir ne mesure pas, elle devine. Les numéros de ligne restent justes :
        on remplace le commentaire par des espaces, on ne le supprime pas.
        """
        rx = re.compile(regex)
        for pattern in patterns:
            for path in self.glob(pattern):
                text = _sans_commentaires(self._read(path), path.suffix)
                m = rx.search(text)
                if m:
                    line = text.count('\n', 0, m.start()) + 1
                    rel = path.relative_to(WAMA_ROOT).as_posix()
                    return f"{rel}:{line}"
        return None


def _blanc(m: re.Match) -> str:
    """Remplace un commentaire par autant d'espaces/sauts de ligne : les offsets sont préservés."""
    return re.sub(r'[^\n]', ' ', m.group(0))


def _sans_commentaires(text: str, suffixe: str) -> str:
    """Neutralise les commentaires Python (# …) ou de gabarit ({# #}, {% comment %}).

    Volontairement simple : un `#` dans une chaîne Python est rare dans le code balayé et le
    faux négatif qu'il produirait est bien moins grave que le faux POSITIF d'un commentaire
    qui déclare l'absence de la brique qu'on cherche.
    """
    if suffixe == '.py':
        return re.sub(r'#[^\n]*', _blanc, text)
    if suffixe in ('.html', '.js'):
        text = re.sub(r'\{#.*?#\}', _blanc, text, flags=re.S)
        text = re.sub(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', _blanc, text, flags=re.S)
        text = re.sub(r'<!--.*?-->', _blanc, text, flags=re.S)
        if suffixe == '.js':
            text = re.sub(r'/\*.*?\*/', _blanc, text, flags=re.S)
            text = re.sub(r'(?m)^\s*//[^\n]*', _blanc, text)
        return text
    return text


TEMPLATES = ['templates/**/*.html']
JS = ['static/**/*.js']
VIEWS = ['views.py', 'views/*.py']
MODELS = ['models.py', 'models/*.py']
TASKS = ['tasks.py', 'workers.py', 'tasks/*.py']
URLS = ['urls.py']
APPS_PY = ['apps.py']
CARD_TPL = ['templates/**/*card*.html', 'templates/**/index.html', 'templates/**/media_table.html']
PY = ['**/*.py']
PARAMS = ['params.py']


# ── Critères ─────────────────────────────────────────────────────────────────────

@dataclass
class Criterion:
    key: str          # clé du rapport ; si égale à une clé `_conv`, ÉCRASE la valeur déclarée
    facette: str      # F1..F8 (route)
    label: str
    fn: object        # callable(_AppFiles) -> (state, evidence)
    #: JONCTION avec le registre des mécanismes (décision Fabien 19/08, Q1) — clé de
    #: `common/mecanismes.py`. Le registre est la SOURCE, la grille l'EXPLOITE : ce champ dit
    #: quel mécanisme transversal ce critère vérifie. Sens choisi par la CARDINALITÉ : un
    #: critère vérifie 0 ou 1 mécanisme, un mécanisme peut être couvert par plusieurs critères
    #: (`param_schema` en a 4). '' = critère qui ne vérifie aucune brique commune (convention
    #: de gabarit, champ de modèle…) — c'est légitime, et ça reste lisible.
    #: LU PAR `mecanismes_scan.mecanismes_sans_critere()` (mécanisme de niveau app que RIEN ne
    #: vérifie) et `criteres_orphelins()` (clé mal orthographiée = liaison silencieusement
    #: inerte, le pire des deux mondes).
    mecanisme: str = ''


def _present(f: _AppFiles, patterns, regex, label_ok=None):
    ev = f.find(patterns, regex)
    return (True, ev) if ev else (False, None)


def _tool_api_triad(f: _AppFiles):
    # Registre RUNTIME (les clés effectivement exposées) : depuis la marche A4, une partie
    # des triades est CONSTRUITE à l'import (`TRIAD_SPECS` + `_register_triads()`) — le
    # littéral du fichier ne dit plus la vérité, seule l'exposition réelle compte.
    try:
        from wama.tool_api import TOOL_REGISTRY
    except Exception as e:
        return False, f'import tool_api impossible : {e!r}'
    keys = [f'add_to_{f.app}', f'start_{f.app}', f'get_{f.app}_status']
    found = [k for k in keys if k in TOOL_REGISTRY]
    if len(found) == 3:
        return True, f"tool_api.py TOOL_REGISTRY ({', '.join(keys)})"
    if found:
        missing = [k for k in keys if k not in found]
        return 'partial', f"tool_api.py: manquent {', '.join(missing)}"
    return False, None


def _shareable_models(f: _AppFiles):
    """
    Les modèles de card/batch héritent-ils de `ScopedVisibility` ?

    C'est la CONDITION du partage (PROFILES_PERMISSIONS §7) : sans le mixin, aucune card n'est
    partageable et le mécanisme reste inerte — ce qui lui est arrivé pendant des mois, adopté
    par 2 modèles seulement. Mesuré ici pour que l'adoption ne repose plus sur la bonne volonté.

    `partial` si un seul modèle l'a adopté : la file étant construite à partir des BATCHES
    (`batch_common.build_batches_list`), une card partagée sans son batch n'apparaît pas.
    """
    text = f.text(MODELS)
    n = len(re.findall(r'class\s+\w+\([^)]*ScopedVisibility', text))
    if n == 0:
        return False, None
    ev = f.find(MODELS, r'class\s+\w+\([^)]*ScopedVisibility')
    return (True, ev) if n >= 2 else ('partial', f"{ev} (1 seul modèle : card OU batch)")


def _scoped_reads(f: _AppFiles):
    """
    Les chemins de LECTURE passent-ils par les accès NOMMÉS (`visible_or_404` / `visible_to`) ?

    Un `get_object_or_404(Model, pk=pk, user=user)` écrit machinalement dans une nouvelle vue
    désactive le partage pour cette route — sans erreur, sans test rouge, sans trace. Ce critère
    rend l'oubli visible (PROFILES_PERMISSIONS §7.4).
    """
    return _present(f, VIEWS, r'visible_or_404|objects\.visible_to\(')


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
    """Adapters preview + detail — mesurés au REGISTRE RUNTIME, plus au texte d'`apps.py`.

    Durci le 2026-08-19 (Q4 Fabien : « pas simplement ça y est ou pas, mais est-ce que c'est
    proprement intégré »). Le grep textuel déclarait imager conforme à cause d'un COMMENTAIRE
    (`# NB : PAS de register_app_preview…`) ; le registre, lui, ne peut pas mentir : il dit ce
    qui est EFFECTIVEMENT enregistré au démarrage. Même précédent que `_tool_api_triad`.
    Repli sur le texte (sans commentaires) si Django n'est pas chargé — le module reste
    utilisable hors runtime.
    """
    try:
        from wama.common.utils.detail_registry import DetailRegistry
        from wama.common.utils.preview_utils import PreviewRegistry
        prev = PreviewRegistry.is_registered(f.app)
        det = DetailRegistry.is_registered(f.app)
        preuve = f"registre runtime : preview={'oui' if prev else 'non'}, detail={'oui' if det else 'non'}"
        if prev and det:
            return True, preuve
        if prev or det:
            return 'partial', preuve
        return False, preuve
    except Exception:
        prev = f.find_code(APPS_PY, r'register_app_preview|PreviewRegistry\.register')
        det = f.find_code(APPS_PY, r'register_app_detail')
        if prev and det:
            return True, f"{prev} + detail (texte : registre non chargé)"
        if prev or det:
            return 'partial', prev or det
        return False, None


def _card_gear(f: _AppFiles):
    """Les `data-*` du gear ⚙ viennent-ils de la brique `card_gear` (dérivés du schéma) ?

    Contrat : le modèle d'item expose `gear_data` construit par `common/utils/card_gear.py`, et
    la card émet `{% for k, v in <item>.gear_data.items %}`. Écrire ces attributs à la main
    marche… jusqu'à ce qu'un paramètre soit ajouté au schéma sans être reporté dans le gabarit —
    c'est le mode de panne que la brique supprime. `partial` quand la card écrit encore une
    série de `data-*` à la main : la modale se remplit, mais elle a cessé de suivre le schéma.
    """
    brique = f.find_code(MODELS, r'from wama\.common\.utils\.card_gear import|card_gear\.gear_data')
    if brique:
        return True, brique
    # `partial` = des data-* de PARAMÈTRES écrits à la main. On soustrait les data-* de
    # structure que TOUTE card porte (id, statut, aperçu…) : sans ce filtre la preuve
    # pointait sur `data-id` et accusait à tort une app dont le gear ne porte aucun réglage.
    structure = {'id', 'status', 'domain', 'preview-url', 'card-preview', 'player-id',
                 'duplicate-url', 'estimated-seconds', 'media-name', 'eta-ids', 's', 'layout'}
    texte = '\n'.join(_sans_commentaires(f._read(p), p.suffix)
                      for pattern in CARD_TPL for p in f.glob(pattern))
    noms = {m for m in re.findall(r'data-([\w-]+)="\{[\{%]', texte)} - structure
    if len(noms) >= 3:
        preuve = f.find_code(CARD_TPL, rf'data-{re.escape(sorted(noms)[0])}="')
        return 'partial', (f"{preuve} — {len(noms)} data-* de paramètres écrits à la main "
                           f"({', '.join(sorted(noms)[:4])}…), hors brique card_gear")
    return False, "aucun data-* de paramètre sur le gear (ni brique, ni écriture manuelle)"


def _card_preview_hydratee(f: _AppFiles):
    """Aperçu de résultat DANS la card via le mécanisme commun n°30 (placeholder hydraté).

    Contrat : la card déclare `data-card-preview="<unified_preview>?side=output"` et
    `WamaInspector.hydrateCardPreviews` la remplit (mime-driven : image/vidéo/audio+onde/pdf/
    texte). `partial` = la card porte encore son propre `<img>`/`<video>` de résultat : ça
    s'affiche, mais chaque app redécide du rendu et les corrections ne profitent qu'à elle.
    """
    commun = f.find_code(CARD_TPL, r'data-card-preview')
    if commun:
        return True, commun
    maison = f.find_code(CARD_TPL, r'<(?:img|video|audio)[^>]+(?:output|result|generated)')
    if maison:
        return 'partial', f"{maison} (markup de résultat propre à l'app, hors mécanisme n°30)"
    return False, None


def _inspector_detail_wired(f: _AppFiles):
    """Le volet REFLÈTE-t-il la card sélectionnée (sections Entrée / Réglages / Sortie) ?

    Deux conditions, et il FAUT les deux — c'est la panne d'imager du 19/08 : l'adapter detail
    était enregistré depuis un mois, mais la card ne portait pas `data-preview-url`, dont
    `WamaInspector.fillDetail` DÉRIVE l'URL `/detail/`. Résultat : card sélectionnable, volet
    muet, et aucun critère pour le voir. La registration est lue au registre runtime, l'attribut
    dans le gabarit (hors commentaires).
    """
    attr = f.find_code(CARD_TPL, r'data-preview-url')
    try:
        from wama.common.utils.detail_registry import DetailRegistry
        enregistre = DetailRegistry.is_registered(f.app)
    except Exception:
        enregistre = bool(f.find_code(APPS_PY, r'register_app_detail'))
    if attr and enregistre:
        return True, f"{attr} + adapter detail enregistré"
    if enregistre and not attr:
        return 'partial', "adapter detail enregistré, mais aucune card ne porte data-preview-url (volet muet)"
    if attr and not enregistre:
        return 'partial', f"{attr} sans adapter detail (le volet n'a rien à afficher)"
    return False, None


def _eta_seeded(f: _AppFiles):
    # `run_item_task` (brique task_skeleton, A2) fait le record_run pour la glu qui déclare `eta`.
    rec = f.find(TASKS, r'record_run|run_item_task')
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


def _queue_entry(f: _AppFiles):
    """L'entrée de file (card seule OU lot) vient-elle de la brique commune ?

    ⚠ GATE : le partial `_queue_entry.html` lit `batch_info.items[].elem`, alias posé par
    `build_batches_list`. Une app qui construit sa file À LA MAIN ne peut donc pas l'adopter
    sans passer d'abord par la brique commune — le lui reprocher désignerait le mauvais
    défaut. Mesuré le 2026-08-25 : le CONVERTER est dans ce cas (`views.py` groupe en mémoire,
    « FK directe job→batch, pas de modèle de liaison »), et son vrai reste-à-faire est
    l'adoption de `build_batches_list`, pas celle de ce partial.
    """
    #: ⚠ un APPEL, pas une mention : le converter cite `build_batches_list` dans un
    #: COMMENTAIRE (`views.py:150`) tout en construisant sa file a la main. Chercher le
    #: nom seul le declarait adoptant — le piege des commentaires, deja mesure sur
    #: `mecanismes_scan` (60 affiches / 18 reels).
    if not f.find(PY, r'build_batches_list\s*\('):
        return None, None          # file construite à la main → autre chantier
    trouve = f.find(TEMPLATES, r"common/_queue_entry\.html")
    if trouve:
        return True, trouve
    # A-t-elle seulement une file à lots ? Sinon le critère n'a pas d'objet.
    if not f.find(TEMPLATES, r'batch-group|_batch_card\.html'):
        return None, None
    return False, "bloc `card seule / lot` encore écrit dans le gabarit d'app"


def _has_engine_select(f: _AppFiles) -> bool:
    """Y a-t-il un SÉLECTEUR de moteur dans l'UI ? — précondition commune des critères
    model_help / input_match_ui / model_caps_ui (gate « composant sans hôte → N/A »,
    verdict Fabien 14/08 étendu le 17/08 aux deux autres critères, même verdict).

    Signal 1 = SCHÉMA réel (PARAMS_JSON importé). Signal 2 (schéma muet — imager/enhancer
    ont des schémas ÉCLATÉS sans PARAMS_JSON) = un VRAI hôte dans le HTML : token de select
    moteur en position d'ATTRIBUT (id/name/for). Un commentaire qui ne fait que CITER un nom
    ne compte pas (faux positif avatarizer 17/08 : « params.py ne déclare plus …tts_model… »).
    Indéterminé (import raté) → True : ne jamais passer N/A à l'aveugle."""
    try:
        import importlib
        schema = getattr(importlib.import_module(f'wama.{f.app}.params'), 'PARAMS_JSON', [])
        engine_selects = [p['name'] for p in schema
                          if p.get('type') == 'select'
                          and (p.get('help_source')
                               or p['name'] in ('model', 'backend', 'engine',
                                                'model_to_use', 'tts_model'))]
    except Exception:
        return True
    if engine_selects:
        return True
    return bool(f.find(
        TEMPLATES,
        r'(?:id|name|for)\s*=\s*["\'][^"\']*'
        r'(?:model_to_use|modelSelect|ModelSelect|backendSelect|tts_model|'
        r'AiModel|audioEngine)'))


_MODELHELP_TYPES: tuple[str, ...] | None = None


def _modelhelp_capable_types() -> tuple[str, ...]:
    """Types de champ que `WamaParams._bindModelHelp` auto-câble — **LUS dans le JS**, jamais
    recopiés ici : le jour où la brique gagne un type, le critère suit tout seul. Repli sur
    `('select',)` si la lecture échoue — mieux vaut le type historique qu'un ensemble vide,
    qui ferait rougir en silence toutes les apps câblées de façon centralisée."""
    global _MODELHELP_TYPES
    if _MODELHELP_TYPES is None:
        try:
            js = (WAMA_ROOT / 'common/static/common/js/wama-params.js').read_text(
                encoding='utf-8', errors='replace')
            found = tuple(re.findall(
                r"registerRenderer\(\s*'([^']+)'[\s\S]{0,400}?modelHelp:\s*true", js))
        except OSError:
            found = ()
        _MODELHELP_TYPES = found or ('select',)
    return _MODELHELP_TYPES


def _model_help(f: _AppFiles):
    """Descriptif moteur — N/A quand l'UI n'offre AUCUN sélecteur de moteur (gate commun
    `_has_engine_select`, cas nommé 14/08 : le describer choisit son modèle vision
    AUTOMATIQUEMENT — exiger la brique revenait à exiger un composant sans hôte).

    DEUX câblages valent adoption (durci le 2026-08-28) :
      1. **explicite** — l'app cite `WamaModelHelp` / `wama-model-help` dans ses gabarits ou son JS ;
      2. **centralisé** — son schéma déclare `help_source`/`help_fallback` sur un type que
         `WamaParams._bindModelHelp` auto-câble, ET l'app rend ce schéma via `WamaParams`.

    Le (2) manquait : le critère ne grep que `wama/<app>/**`, il déclarait donc ROUGE une app
    dont la brique est **vivante**. Même leçon que `_queue_entry` — *un critère qui mesure du
    MARKUP doit SUIVRE ce markup quand il se centralise*, et un gate cherche un APPEL, pas une
    MENTION. Portée MESURÉE avant durcissement (28/08, les 10 apps) : **une seule bascule**
    (avatarizer) ; 8 étaient déjà vertes en explicite, describer reste N/A."""
    ev = f.find(TEMPLATES + JS, r'wama-model-help|WamaModelHelp')
    if ev:
        return True, ev
    rend = f.find(TEMPLATES + JS, r'WamaParams\s*\.\s*(?:render|settingsModal)\s*\(')
    if rend:
        try:
            import importlib
            schema = getattr(importlib.import_module(f'wama.{f.app}.params'), 'PARAMS_JSON', [])
        except Exception:
            schema = []
        types = _modelhelp_capable_types()
        champs = [p['name'] for p in schema
                  if p.get('type') in types and (p.get('help_source') or p.get('help_fallback'))]
        if champs:
            return True, f"{rend} (auto-câblé par WamaParams sur {', '.join(champs)})"
    if not _has_engine_select(f):
        return None, None
    return False, None


def _modes_declared(f: _AppFiles):
    """Modes déclarés — ou ABSENCE DÉCLARÉE (`{'domains': []}` = « j'ai considéré, le
    comportement ne diverge pas ») → non applicable. Un mode n'existe que si le comportement
    diverge (doctrine common/README §Modes) ; exiger un mode factice d'une app mono-geste
    (composer/reader/describer, 14/08) sanctionnait la doctrine — même logique que
    PROMPT_TARGETS vide (gate F6, 14/08). Clé ABSENTE = toujours rouge (non traité)."""
    try:
        from wama.common.utils.app_modes import APP_MODES
        entry = APP_MODES.get(f.app)
    except Exception:
        entry = None
    if entry is None:
        return False, "absente d'APP_MODES (ni modes, ni absence déclarée)"
    if not entry.get('domains'):
        return None, None
    return True, f"common/utils/app_modes.py APP_MODES['{f.app}']"


def _duplicate_wiring(f: _AppFiles):
    # RÉALIGNÉ le 2026-08-23 sur son jumeau `_delete_wiring` (pending 6 du §REPRISE 22→23) :
    # écrit AVANT lui, il portait encore les deux faiblesses corrigées sur le jumeau le
    # 2026-08-22 — sans avoir produit de faux verdict, mais la faiblesse était la même :
    #   • `find` et non `find_code` — un COMMENTAIRE citant `.duplicate-btn` (queue-actions.js
    #     en est plein) suffisait à fabriquer un faux DOUBLE-FIRE ;
    #   • l'attribut mesuré SANS la classe — un `data-duplicate-url` posé sur un bouton d'une
    #     autre graphie aurait validé un câblage que la délégation n'atteint jamais
    #     (le faux vert constaté sur enhancer pour la suppression, même mécanique).
    data_url = f.find_code(TEMPLATES, r'class="[^"]*(?<![\w-])duplicate-btn[^"]*"[^>]*data-duplicate-url'
                                      r'|data-duplicate-url[^>]*class="[^"]*(?<![\w-])duplicate-btn')
    # (?<![\w-]) : ne pas compter `.batch-duplicate-btn` (bouton de la card MÈRE,
    # hors périmètre — la brique queue-actions ne cible que `.duplicate-btn`).
    local = f.find_code(JS, r"(?<![\w-])\.duplicate-btn|(?<![\w-])duplicate-btn'\)|(?<![\w-])duplicate-btn\"\)")
    if data_url and not local:
        return True, data_url
    if data_url and local:
        return False, f"DOUBLE-FIRE possible: brique + handler local {local}"
    if local:
        return 'partial', f"{local} (impl locale, brique queue-actions non consommée)"
    return False, None


def _delete_wiring(f: _AppFiles):
    """Suppression d'un ÉLÉMENT câblée sur la brique `queue-actions.js` — jumeau de
    `_duplicate_wiring`, écrit le 2026-08-22 le jour où la brique a existé.

    ⚠ POURQUOI IL N'EXISTAIT PAS AVANT, et ce que ça dit de la grille (question de Fabien).
    La duplication avait son critère depuis longtemps ; la suppression n'en avait aucun, non
    par oubli mais parce qu'il n'y avait **pas de brique** : le registre des mécanismes recense
    ce qui EXISTE, donc `mecanismes_sans_critere()` ne pouvait rien signaler d'absent. Le point
    aveugle de la grille n'est pas « un mécanisme sans critère » — celui-là est détecté — c'est
    **« un geste sans brique »** : 10 apps faisant la même chose de 6 façons, sans domicile
    commun, et aucun instrument n'avait de nom pour ça. C'est le scénario fonctionnel
    `<app>.duplicate_delete` qui l'a trouvé, en butant sur le nommage réel.

    Les 6 graphies relevées ce jour-là : `delete-btn` (6 apps), `job-delete-btn` (converter ×2),
    `btn-delete-job` (avatarizer), `js-audio-delete`/`js-delete-enhancement` (enhancer),
    `video-delete-btn` (imager vidéo), `data-action="delete"` sans classe (reader).
    """
    # Le contrat de la brique est un COUPLE : la classe `.delete-btn` ET l'attribut
    # `data-delete-url`. Mesurer le seul attribut produit un FAUX VERT — constaté sur enhancer
    # dans la minute qui a suivi l'écriture de ce critère : il porte `data-delete-url` sur un
    # bouton `js-delete-enhancement`, donc la délégation ne se déclenche JAMAIS et le critère
    # validait un câblage inexistant.
    data_url = f.find_code(TEMPLATES, r'class="[^"]*(?<![\w-])delete-btn[^"]*"[^>]*data-delete-url'
                                      r'|data-delete-url[^>]*class="[^"]*(?<![\w-])delete-btn')
    # (?<![\w-]) : ne compter NI `.batch-delete-btn` (card mère, hors périmètre), NI les
    # graphies préfixées (`job-delete-btn`…) — celles-ci sont justement ce qu'on veut voir
    # rester en `partial` tant que l'app n'est pas portée.
    # `find_code` et NON `find` : le converter portait un COMMENTAIRE disant « la brique délègue
    # sur `.delete-btn` », et un `find` brut y lisait un handler local — donc un faux DOUBLE-FIRE
    # sur l'app justement portée. Exactement la leçon d'`inspector_adapters` (19/08), refaite le
    # jour même : un critère qu'un commentaire fait mentir devine au lieu de mesurer.
    local = f.find_code(JS, r"(?<![\w-])\.delete-btn|(?<![\w-])delete-btn'\)|(?<![\w-])delete-btn\"\)")
    if data_url and not local:
        return True, data_url
    if data_url and local:
        # Exactement le défaut que §3 de CARD_DESIGN décrit : l'app ET la brique répondent au
        # même clic, donc DEUX requêtes de suppression. Le portage doit être ATOMIQUE.
        return False, f"DOUBLE-FIRE possible: brique + handler local {local}"
    if local:
        return 'partial', f"{local} (impl locale, brique queue-actions non consommée)"
    return False, None


def _settings_wiring(f: _AppFiles):
    """⚙ Paramètres câblé sur la brique `queue-actions.js` — troisième jumeau, écrit le
    2026-08-23 le jour où la brique a existé (cf. `_delete_wiring`, même histoire à un mois).

    ⚠ CE QUE CE CRITÈRE MESURE DE PLUS QUE SES DEUX JUMEAUX. Dupliquer et supprimer SONT des
    POST : le contrat tient dans le gabarit (`classe + data-*-url`), et la brique fait le reste.
    ⚙ ne fait qu'OUVRIR une modale propre à l'app : le contrat est donc en DEUX morceaux, et un
    seul des deux ne prouve rien —
      • le gabarit rend `.settings-btn[data-id]` (sinon la délégation ne voit rien) ;
      • le JS déclare `WamaQueueActions.onSettings(...)` (sinon le clic est délégué… à personne,
        et la brique le dit en console, mais l'écran, lui, reste mort).
    C'est exactement l'écart « ADOPTION vs FONCTIONNEMENT » de WAMA_VERIFICATION §1, réduit ici
    autant qu'une analyse statique le permet : le reste se prouve au clic (`<app>.settings`).

    ⚠ ET LE PIÈGE PROPRE À CE CRITÈRE : `.settings-btn` est LU par plusieurs apps pour reporter
    des `data-*` sur le gear (converter `index.html`, avatarizer, transcriber). Une LECTURE n'est
    pas un handler, et la compter comme telle produirait un faux DOUBLE-FIRE sur des apps
    correctement portées. On ne cherche donc pas la mention de la classe, on cherche les deux
    idiomes qui ACCROCHENT un clic — `closest('.settings-btn')` (délégation) et
    `querySelectorAll('.settings-btn')` (bind par bouton) — en laissant passer le
    `querySelector` singulier, qui est le geste de lecture. Lire un MÉCANISME, pas un motif :
    c'est la leçon des 5 erreurs de diagnostic du 2026-08-22.
    """
    markup = f.find_code(TEMPLATES, r'class="[^"]*(?<![\w-])settings-btn[^"]*"[^>]*data-id'
                                    r'|data-id[^>]*class="[^"]*(?<![\w-])settings-btn')
    declare = f.find_code(JS + TEMPLATES, r'WamaQueueActions\.onSettings')
    # (?<![\w-]) : ne compter ni `.batch-settings-btn` (lot, hors périmètre) ni `.save-settings-btn`
    # (pied de modale) — deux classes qui contiennent `settings-btn` en sous-chaîne.
    local = f.find_code(JS, r"closest\(\s*['\"][^'\"]*(?<![\w-])\.settings-btn"
                            r"|querySelectorAll\(\s*['\"][^'\"]*(?<![\w-])\.settings-btn")
    if local:
        return False, f"DOUBLE-FIRE possible: brique + handler local {local}"
    if markup and declare:
        return True, f"{markup} + {declare}"
    if markup:
        return 'partial', f"{markup} (bouton au contrat, mais AUCUN ouvreur déclaré — clic inerte)"
    if declare:
        return 'partial', f"{declare} (ouvreur déclaré, mais le gabarit ne rend pas .settings-btn[data-id])"
    return False, None


def _download_wiring(f: _AppFiles):
    """⬇ Télécharger rendu par la brique commune — QUATRIÈME et dernier jumeau (2026-08-23).

    ⚠ CELUI-CI NE MESURE PAS UN CÂBLAGE JS, ET C'EST TOUT SON INTÉRÊT. Dupliquer, supprimer et
    paramétrer sont des BOUTONS à comportement : leur divergence se voyait dans le JS. Télécharger
    est un LIEN — il n'a aucun handler, donc aucun grep d'`addEventListener` ne pouvait le
    signaler. Sa divergence vivait entièrement dans le GABARIT, et elle y est restée longtemps :
    trois apps recopiaient le même dropdown à la main, deux rendaient un `<button>`+JS contraire
    à §6.3 (et à leur propre déclaration `export_binding`), une postait un FORMULAIRE.

    Ce qu'on exige : le gabarit appelle `{% bouton_telecharger … %}`, et il ne reste NI dropdown
    écrit à la main, NI handler de clic sur `.download-btn`. Le second membre compte autant que le
    premier — adopter la brique en laissant l'ancien markup à côté donnerait deux boutons.
    """
    brique = f.find_code(TEMPLATES, r'bouton_telecharger')
    # Dropdown de formats écrit à la main : la marque en est `?format=` dans un `dropdown-item`.
    manuel = f.find_code(TEMPLATES, r'dropdown-item[^>]*\?format=')
    # Un `<a href>` n'a pas de handler : un clic écouté sur `.download-btn` est le signe d'une
    # navigation faite en JavaScript, que §6.3 ne prévoit pas.
    local = f.find_code(JS, r"closest\(\s*['\"][^'\"]*(?<![\w-])\.(?:video-)?download-btn")
    if manuel and brique:
        return False, f"brique adoptée MAIS dropdown manuel subsistant ({manuel}) — deux boutons"
    if local:
        return False, f"navigation en JS sur .download-btn ({local}) — un téléchargement est un lien"
    if brique:
        return True, brique
    if manuel:
        return 'partial', f"{manuel} (dropdown écrit à la main, brique non consommée)"
    return False, None


def _help_about(f: _AppFiles):
    # Durci 2026-08-11 : l'ancien motif `class (Help|About)View` mesurait la PRÉSENCE d'une
    # classe — or 9 apps sur 10 rendaient 500 (templates fantômes), et le seul 200 (converter)
    # re-rendait sa base. La brique commune = onglets du gabarit auto-remplis d'APP_CATALOG +
    # routes /about/ /help/ redirigeant vers l'onglet (common/views.py::AppAboutView).
    brick = f.find(URLS, r'AppAboutView') and f.find(URLS, r'AppHelpView')
    if brick:
        return True, f.find(URLS, r'AppAboutView')
    local = f.find(VIEWS, r'class (Help|About)View')
    if local:
        return 'partial', f"{local} (classe locale — vérifier que son template existe)"
    return False, None


def _user_settings(f: _AppFiles):
    # Durci 2026-08-11 : l'ancien motif `user_settings` matchait un simple import en lecture
    # (imager : volet rendu mais réglages jamais persistés) ET les variables locales
    # `user_settings, _ = UserSettings.objects…` d'anonymizer/enhancer (modèle legacy) —
    # trois faux verts. La preuve d'adoption est l'ÉCRITURE de la brique : sans
    # `save_user_app_settings`, rien ne persiste et le mécanisme est à moitié vivant.
    write = f.find(VIEWS, r'save_user_app_settings')
    if write:
        return True, write
    read_only = f.find(VIEWS, r'get_user_app_settings')
    if read_only:
        return 'partial', f"{read_only} (brique en LECTURE seule — aucun save, rien ne persiste)"
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
    """M1 — ordre canonique ⚙▶⬇⧉🗑 dans le template de card (best effort).

    ⚠ CHAQUE MARQUEUR DOIT ACCEPTER LA FORME COMMUNE AUTANT QUE LA FORME LOCALE, sinon ce
    critère PUNIT l'adoption d'une brique. Vécu deux fois :
      • ▶ : `_cycle_button.html` (include) accepté à côté de `fa-play|fa-redo` ;
      • ⬇ : `bouton_telecharger` (tag d'inclusion) ajouté le 2026-08-23 — sans lui, les 10 apps
        passaient au ROUGE le jour où le bouton de téléchargement a rejoint le commun, alors que
        rien n'avait disparu de l'écran. Le critère ne cherchait plus l'icône au bon endroit :
        elle avait simplement déménagé dans le partial.
    C'est le défaut symétrique de celui des graphies : là on lisait un motif au lieu d'un
    mécanisme, ici on lit un EMPLACEMENT au lieu d'une présence. Un critère qui mesure du markup
    doit suivre le markup quand il se centralise — sinon il transforme un progrès en régression.
    """
    markers = [r'fa-cog|fa-gear', r'_cycle_button\.html|fa-play|fa-redo',
               r'fa-download|bouton_telecharger',
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


# ── Registres transverses (lecture STATIQUE : le checker ne charge pas Django) ────

_ROOT_CACHE: dict[str, str] = {}


def _wama_text(rel: str) -> str:
    """Contenu d'un fichier sous `wama/` (chaîne vide s'il n'existe pas)."""
    if rel not in _ROOT_CACHE:
        try:
            _ROOT_CACHE[rel] = (WAMA_ROOT / rel).read_text(encoding='utf-8', errors='replace')
        except OSError:
            _ROOT_CACHE[rel] = ''
    return _ROOT_CACHE[rel]


def _registry_block(app: str, rel: str) -> str | None:
    """Corps du bloc `'<app>': { … }` d'un registre déclaré dans `rel`."""
    m = re.search(rf"^(\s*)'{re.escape(app)}':\s*\{{(.*?)^\1\}},", _wama_text(rel), re.S | re.M)
    return m.group(2) if m else None


def _registry_keys(name: str, rel: str) -> set[str]:
    """Clés de PREMIER niveau d'un dict-registre `NAME = { 'app': …, }` (indentation 4)."""
    m = re.search(rf"^{name}\s*[:=].*?\{{(.*?)^\}}", _wama_text(rel), re.S | re.M)
    return set(re.findall(r"^ {4}'([a-z_]+)'\s*:", m.group(1), re.M)) if m else set()


APP_REGISTRY_PY = 'common/app_registry.py'
MODEL_REGISTRY_PY = 'model_manager/services/model_registry.py'
GENERIC_RUNNER_PY = 'studio/services/generic_runner.py'


def _uses_models(f: _AppFiles) -> bool:
    """L'app porte-t-elle des modèles IA ? (converter = ffmpeg/pandoc → F4 non applicable)"""
    return bool(f.glob('utils/model_config.py')
                or f'_discover_{f.app}_models' in _wama_text(MODEL_REGISTRY_PY))


def _f4(fn):
    """Enveloppe un critère F4 : état None (= non applicable) si l'app n'a pas de modèle IA."""
    def wrapped(f: _AppFiles):
        return fn(f) if _uses_models(f) else (None, None)
    return wrapped


def _recursive_import(f: _AppFiles):
    """Import de DOSSIER récursif — PRÉSENCE D'ABORD, non-applicabilité en repli.

    Une adoption vaut toujours (le synthesizer importe un dossier de .txt alors que ses
    `input_types` ne déclarent que 'text' : chaque fichier EST un item). L'exemption ne
    joue que sur une ABSENCE : app sans aucune entrée média-fichier déclarée (composer —
    ses fichiers sont des DESCRIPTEURS de batch, un dossier n'a pas d'objet). Verdict
    Fabien 2026-08-13."""
    present = _present(f, TEMPLATES + JS, r'webkitdirectory|folder_input_id|WamaFolderImport')
    if present[0]:
        return present
    from wama.common.app_registry import APP_CATALOG
    kinds = set((APP_CATALOG.get(f.app) or {}).get('input_types') or ())
    if not kinds & {'image', 'video', 'audio', 'document', 'archive', 'pdf'}:
        return None, "aucune entrée média-fichier déclarée (input_types) — import de dossier sans objet"
    return present


def _import_wired(f: _AppFiles):
    """Zone de dépôt que RIEN n'écoute (trou #26 de la route) — le défaut le plus SILENCIEUX.

    La grille mesurait la PRÉSENCE du markup d'entrée, jamais l'existence d'un écouteur. Or le
    JS d'une app peut exister dans `static/` sans être JAMAIS chargé, si le gabarit n'émet pas
    le bloc `app_scripts` que le socle offre pourtant (`app_modern_base.html:294`). Rien n'est
    chargé, donc rien ne plante : **zéro erreur console**, et aucun critère ne baissait. Mesuré
    le 2026-08-22 sur converter_01 — 0 card créable par 5 voies, grille inchangée.

    ⚠ **La preuve se cherche DANS LE GABARIT** (« ce JS est-il chargé ? »), jamais dans
    l'existence du fichier `.js` — c'est toute la différence, et c'est ce que la grille
    confondait. `find_code` (et non `find`) parce que le gabarit généré porte un `{% comment %}`
    qui CITE `app_scripts` pour l'expliquer : un critère qu'un commentaire fait passer au vert
    devine au lieu de mesurer (même leçon que `inspector_adapters`, 19/08).

    NON APPLICABLE quand aucune card d'entrée n'est rendue (médiathèque, gestionnaire de
    modèles, studio) : il n'y a alors pas de dépôt à écouter. Même exemption que le scénario
    nocturne `<app>.import`, pour que les deux mesures racontent la même histoire.

    N'exige PAS que le dépôt CRÉE l'élément : avatarizer et imager déclarent
    `data-wama-depot="attache"` (le fichier est joint, le bouton primaire crée) et ont bien un
    écouteur. Ce critère mesure « quelque chose écoute », pas « quoi ».
    """
    # ⚠ La card d'entrée est le plus souvent INCLUSE depuis `common/`, pas écrite dans l'app :
    # ne chercher que du markup local répondait « aucune card d'entrée » sur 10 apps qui en ont
    # une (converter, transcriber, anonymizer…). Erreur commise en écrivant ce critère le
    # 2026-08-22, et de la MÊME famille que le trou qu'il traque : mesurer l'artefact local au
    # lieu de ce qui est réellement rendu. L'inclusion de la brique commune EST le markup.
    markup = f.find_code(
        TEMPLATES,
        r'_new_item_card\.html|data-wama-nic|wama-dropzone|dropzone|type=[\'"]file[\'"]')
    if not markup:
        return None, "aucune card d'entrée rendue — aucun dépôt à écouter"
    # ⚠ Coller à l'IDIOME RÉEL des gabarits, pas à celui qu'on imagine : le projet charge par
    # `{% static_v %}` (cache-busting), et la brique s'appelle `batch-import.js` avec un TIRET.
    # Écrit d'abord avec `static` et `batch_import`, ce motif déclarait le converter en échec
    # alors que son scénario d'import est VERT (mesuré le matin même). C'est ce vert empirique
    # qui a servi de garde-fou : un critère qui contredit une mesure de bout en bout a tort
    # jusqu'à preuve du contraire — on corrige le critère, jamais la mesure.
    charge = f.find_code(
        TEMPLATES,
        r'_app_scripts\.html|block\s+app_scripts|wama-import\.js|batch[-_]import\.js'
        rf'|static(?:_v)?\s+[\'"]{re.escape(f.app)}/js/')
    if charge:
        return True, charge
    return False, f'dépôt rendu ({markup}) mais AUCUNE voie d\'import chargée par le gabarit'


def _has_prompt(f: _AppFiles) -> bool:
    """L'app a-t-elle un champ prompt ? (sinon les critères F6 prompt sont non applicables)

    ⚠ La PRÉSENCE de la clé dans `PROMPT_TARGETS` ne suffit pas : une entrée VIDE est une
    DÉCLARATION D'ABSENCE, pas un champ à traiter. Cas nommé (13/08, décision §16.6 tracée
    dans app_metadata.py) : `PROMPT_TARGETS['synthesizer'] = []` — le `text_content` TTS ne
    doit JAMAIS être traduit (on prononce ce que l'utilisateur a écrit). Exiger la pipeline,
    la skill et l'UI d'enrichissement sur un prompt qui n'existe pas revenait à sanctionner
    la décision elle-même : le gate se lit désormais sur le CONTENU déclaré."""
    if f.find(MODELS, r'^\s*prompt\s*=\s*models\.'):
        return True
    try:
        from wama.common.utils.app_metadata import prompt_targets
        return bool(prompt_targets(f.app))
    except Exception:
        return f.app in _registry_keys('PROMPT_TARGETS', 'common/utils/app_metadata.py')


def _f6_prompt(fn):
    def wrapped(f: _AppFiles):
        return fn(f) if _has_prompt(f) else (None, None)
    return wrapped


# ── F1 / F2 — identité déclarée & entrée ─────────────────────────────────────────

def _catalog_entry(f: _AppFiles):
    block = _registry_block(f.app, APP_REGISTRY_PY)
    if block is None:
        return False, "absente d'APP_CATALOG (identité non déclarée)"
    missing = [k for k in ('input_types', 'output_types', 'input_extensions')
               if not re.search(rf"'{k}'\s*:", block)]
    if missing:
        return 'partial', f"APP_CATALOG['{f.app}'] : manquent {', '.join(missing)}"
    return True, f"{APP_REGISTRY_PY} APP_CATALOG['{f.app}'] (E/S typées + extensions)"


# ── F3 — preview « PENDANT » (backend câblé ⟷ frontend consommateur) ─────────────

def _during_preview(f: _AppFiles):
    """Émission backend par l'app ⟷ consommation par le front COMMUN (`?side=during`).

    Le consommateur vit dans `wama-inspector.js` (`_startDuring`), PAS dans `media-preview.js`
    qui ne fait que rendre la donnée — vérifié 2026-07-30 (le trou #4 de la route était périmé).
    """
    # L'émission se lit par l'API de la brique (publish_partial_text/peaks/…, 13/08) —
    # pas seulement par le flag : un worker qui publie EST la preuve.
    ev = f.find(PY + TEMPLATES + JS, r'during_preview|emit_streaming_peaks|publish_partial|side=during')
    if not ev:
        return False, None
    front = [p.relative_to(WAMA_ROOT).as_posix()
             for p in sorted((WAMA_ROOT / 'common' / 'static' / 'common' / 'js').glob('*.js'))
             if re.search(r"side=during", p.read_text(encoding='utf-8', errors='replace'))]
    if front:
        return True, f"{ev} ⟷ {', '.join(front)}"
    return 'partial', f"{ev} — émission backend OK, aucun front commun ne lit `?side=during`"


def _params_modal_batch(f: _AppFiles):
    ev = f.find(TEMPLATES + JS, r"context\s*:\s*['\"]batch['\"]|renderBatchParams")
    if ev:
        return True, ev
    return False, "modale batch hand-built (WamaParams jamais rendu en contexte batch)"


# ── F4 — modèles IA ──────────────────────────────────────────────────────────────

def _model_discovery(f: _AppFiles):
    fn = f'_discover_{f.app}_models'
    text = _wama_text(MODEL_REGISTRY_PY)
    if f'def {fn}' not in text:
        return False, f"{fn}() absent de {MODEL_REGISTRY_PY}"
    line = text.count('\n', 0, text.index(f'def {fn}')) + 1
    return True, f"{MODEL_REGISTRY_PY}:{line}"


def _backend_contract(f: _AppFiles):
    ev = f.find(PY, r'BaseModelBackend')
    if not ev:
        return False, "aucun backend ne dérive de common/backends/base.py::BaseModelBackend"
    # Piège documenté : l'alias de classe capture la fonction AVANT l'enveloppe
    # `__init_subclass__` → mécanisme présent mais inopérant.
    alias = f.find(PY, r'^\s*load_model\s*=\s*load\b|^\s*unload_model\s*=\s*unload\b')
    if alias:
        return 'partial', f"{ev} — mais alias de classe en {alias} (enveloppe VRAM court-circuitée)"
    return True, ev


# ── F6 — prompts & contrat tool_api ──────────────────────────────────────────────

def _prompt_skill(f: _AppFiles):
    files = sorted((WAMA_ROOT / 'common' / 'prompt_skills').glob(f'{f.app.replace("_", "-")}*.md'))
    if files:
        return True, ', '.join(p.relative_to(WAMA_ROOT).as_posix() for p in files)
    return False, f"aucun common/prompt_skills/{f.app}-*.md (fallback default-<kind>)"


def _tool_api_item_id(f: _AppFiles):
    """Contrat exigé par build_generic_runner : add_to_<app> doit retourner `item_id`."""
    text = _wama_text('tool_api.py')
    m = re.search(rf"^def add_to_{f.app}\b.*?(?=^def |\Z)", text, re.S | re.M)
    if not m:
        alias = re.search(rf"^add_to_{f.app}\s*=\s*(\w+)", text, re.M)
        if not alias:
            return False, f"add_to_{f.app} introuvable dans tool_api.py"
        m = re.search(rf"^def {alias.group(1)}\b.*?(?=^def |\Z)", text, re.S | re.M)
        if not m:
            return 'partial', f"add_to_{f.app} = alias {alias.group(1)} (corps non retrouvé)"
    line = text.count('\n', 0, m.start()) + 1
    if re.search(r"""['"]item_id['"]""", m.group(0)):
        return True, f"tool_api.py:{line} (retourne 'item_id')"
    return False, f"tool_api.py:{line} — add_to_{f.app} ne retourne pas 'item_id' (studio KO)"


# ── F7 — permissions & scope données ─────────────────────────────────────────────

def _access_policy(f: _AppFiles):
    m = re.search(r'DEFAULT_APP_ACCESS\s*=\s*\{(.*?)\n\}',
                  _wama_text('accounts/permissions.py'), re.S)
    if m and re.search(rf"'{f.app}'\s*:", m.group(1)):
        return True, f"accounts/permissions.py DEFAULT_APP_ACCESS['{f.app}']"
    return False, "absente du seed DEFAULT_APP_ACCESS (gating d'app non déclaré)"


# ── F8 — nœud studio ─────────────────────────────────────────────────────────────

def _select_model(f: _AppFiles):
    """L'app confie-t-elle son choix AUTOMATIQUE de modèle à la brique commune ?

    Non applicable quand il n'y a rien à choisir automatiquement : pas d'option « auto »
    et aucun sélecteur maison. L'enhancer, par exemple, laisse l'utilisateur désigner son
    moteur — lui reprocher de ne pas appeler `select_model()` reviendrait à exiger une
    fonctionnalité qu'il n'a pas, pas à combler un trou.

    Reste KO le cas qui compte : une app qui SÉLECTIONNE, mais avec sa propre cascade
    (sonde VRAM maison, seuils écrits en dur) au lieu de la brique — c'est là que les
    deux mécanismes divergent en silence.
    """
    adopted = f.find(PY, r'\bselect_model(_id)?\b')
    if adopted:
        return True, adopted

    # Sélecteur MAISON : soit une sonde VRAM écrite à la main, soit une fonction de choix.
    probe = f.find(PY, r'nvidia-smi|mem_get_info|free_vram')
    chooser = f.find(PY, r'def (select|choose|_select|_auto)\w*model|def select_best')
    home_made = probe or chooser
    if home_made:
        # Un sélecteur qui lit DÉJÀ le catalogue n'est pas une source concurrente : il peut
        # être un sur-ensemble légitime (l'anonymizer combine plusieurs modèles pour couvrir
        # un jeu de classes ; la brique commune n'en choisit qu'un). On le distingue du
        # sélecteur qui se fabrique sa propre vérité.
        reads_catalog = f.find(PY, r'model_manager|AIModel')
        if reads_catalog and not probe:
            return 'partial', (f"sélecteur maison en {home_made}, mais alimenté par le "
                               f"catalogue ({reads_catalog}) — sur-ensemble, pas doublon")
        return False, f"sélecteur maison en {home_made} — concurrent de select_model()"

    if not f.find(PARAMS + ['utils/model_config.py'], r"['\"]auto['\"]"):
        return None, None
    return False, "option « auto » exposée mais résolue hors de la brique commune"


def _model_caps_canonical(f: _AppFiles):
    """Les modèles de l'app entrent-ils au catalogue en vocabulaire CANONIQUE ?

    ⚠ Se mesure dans la DÉCOUVERTE (`model_registry._discover_<app>_models`), PAS dans le
    `model_config.py` de l'app. La frontière est délibérée et documentée : l'app déclare dans
    SON vocabulaire (`type`, `mode`, `supports_cloning`…), la découverte traduit vers le
    tronc commun, et `AIModel.capabilities` est la source unique que tout le monde lit
    (INPUT_MODEL_MATCHING.md). Une première version de ce critère cherchait le vocabulaire
    canonique dans les fichiers de l'app : elle sanctionnait une architecture correcte.

    `inputs_required`/`inputs_optional` est la clé qui compte — c'est elle qui alimente
    l'appariement entrée↔modèle et le grisage des moteurs incompatibles.
    """
    text = _wama_text(MODEL_REGISTRY_PY)
    m = re.search(rf"^    def _discover_{f.app}_models\b.*?(?=^    def |\Z)", text, re.S | re.M)
    if not m:
        return False, f"_discover_{f.app}_models() absent de {MODEL_REGISTRY_PY}"
    body, line = m.group(0), text.count('\n', 0, m.start()) + 1
    missing = [k for k, rx in (('task', r"'task'"),
                               ('modalities', r"'modalities'"),
                               ('inputs_required/optional', r"inputs_required|inputs_optional"))
               if not re.search(rx, body)]
    if missing:
        return 'partial', f"{MODEL_REGISTRY_PY}:{line} — manquent {', '.join(missing)}"
    return True, f"{MODEL_REGISTRY_PY}:{line} (task + modalities + inputs_*)"


def _vram_unloader(f: _AppFiles):
    """L'app sait-elle rendre sa VRAM au reclaim cross-app ?

    Trois voies légitimes, dans cet ordre de préférence :
      1. **automatique** — ses backends dérivent de `BaseModelBackend`, qui enregistre
         l'unloader de l'app au premier `load()` (`common/backends/base.py::_track_live`) ;
      2. **explicite** — `register_vram_unloader` dans `apps.py::ready()`, pour ce qui vit
         hors backend (modèle en variable de module, pipeline caché) ;
      3. **réservation** — `vram_reservation`, pour les modèles HORS PROCESS (sous-processus).

    Non applicable à une app qui ne charge RIEN en process : le synthesizer délègue tout au
    service TTS (aucun `torch`/`from_pretrained` chez lui) — y exiger un unloader ferait
    libérer de la VRAM qu'il ne détient pas.
    """
    explicit = f.find(PY, r'register_vram_unloader|vram_reservation')
    if explicit:
        return True, explicit
    auto = f.find(PY, r'BaseModelBackend')
    if auto:
        return True, f'automatique via BaseModelBackend ({auto})'
    if not f.find(PY, r'^\s*import torch|^\s*from torch|from_pretrained'):
        return None, None
    return False, "modèle résident sans unloader : ni BaseModelBackend, ni register_vram_unloader"


def _filemanager_import(f: _AppFiles):
    """Réception de « Envoyer vers app » — BRIQUE COMMUNE depuis 2026-07-30.

    Le listener `wama:fileimported` était recopié à l'identique dans chaque app (7 copies,
    3 apps oubliées au passage). Il vit désormais dans `wama-app-base.js`, monté globalement,
    et cible l'app via `window.WAMA_CURRENT_APP`. Une app est donc conforme dès qu'elle est
    dans `APP_CATALOG` — c'est lui qui résout `current_app` côté contexte.
    """
    if 'wama:fileimported' not in _wama_text('common/static/common/js/wama-app-base.js'):
        return False, 'brique commune absente de wama-app-base.js'
    if _registry_block(f.app, APP_REGISTRY_PY) is None:
        return False, "absente d'APP_CATALOG → window.WAMA_CURRENT_APP ne résout pas"
    own = f.find(JS, r"addEventListener\('wama:fileimported'")
    if own:
        return True, f'brique commune + intégration enrichie {own}'
    return True, 'brique commune wama-app-base.js (générique via WAMA_CURRENT_APP)'


def _studio_params(f: _AppFiles):
    block = _registry_block(f.app, GENERIC_RUNNER_PY)
    if block is None:
        return False, "absente de GENERIC_APPS (nœud studio non câblé)"
    mod = re.search(r"'params_module'\s*:\s*'([\w.]+)'", block)
    attr = re.search(r"'params_attr'\s*:\s*'(\w+)'", block)
    if not (mod and attr):
        return False, 'params_module / params_attr non déclarés'
    rel = mod.group(1).replace('wama.', '', 1).replace('.', '/') + '.py'
    text = _wama_text(rel)
    if not text:
        return False, f"module {mod.group(1)} introuvable"
    if not re.search(rf"^{attr.group(1)}\s*[:=]", text, re.M):
        return False, f"{mod.group(1)}.{attr.group(1)} absent"
    return True, f"{rel}::{attr.group(1)}"


CRITERIA: list[Criterion] = [
    # ── F1 identité / intégration transverse ──
    Criterion('tool_api', 'F1', 'Triade tool_api (add_to/start/get_status) au TOOL_REGISTRY', _tool_api_triad,
              mecanisme='tool_api'),
    Criterion('console', 'F1', 'Console app (bloc + endpoint)', _console,
              mecanisme='console'),
    Criterion('help_about', 'F1', 'Aide / À-propos (brique commune AppAboutView/AppHelpView)',
              _help_about),
    Criterion('catalog_entry', 'F1', "Identité APP_CATALOG (E/S typées + input_extensions)",
              _catalog_entry),
    # ── F2 entrée ──
    Criterion('new_item_card', 'F2', "Card d'entrée commune _new_item_card",
              lambda f: _present(f, TEMPLATES, r"common/_new_item_card\.html"),
              mecanisme='new_item_card'),
    Criterion('queue_entry', 'F2', 'Entrée de file commune (_queue_entry : card seule OU lot)',
              _queue_entry, mecanisme='queue_entry'),
    Criterion('drag_drop', 'F2', 'Zone drag & drop',
              lambda f: _present(f, TEMPLATES + JS, r'drop_zone_id|drop-zone|dragover')),
    Criterion('url_ingest', 'F2', 'Import URL déclaratif (WAMA_INGEST + ensure_local_input)', _url_ingest,
              mecanisme='source_ingest'),
    Criterion('batch_import', 'F2', 'Import batch unifié (batch-import.js + batch_parsers)', _batch_import,
              mecanisme='batch'),
    Criterion('media_library_slot', 'F2', 'Slot médiathèque sur la card d’entrée',
              lambda f: _present(f, TEMPLATES, r'show_media_library')),
    Criterion('input_card_collapsed', 'F2', "Card d'entrée REPLIABLE (collapsible)",
              lambda f: _present(f, TEMPLATES, r'collapsible=True|collapsible=1'),
              mecanisme='new_item_card'),
    # Grisage des MODÈLES par entrée : sans moteur IA il n'y a rien à griser (verdict
    # Fabien 13/08 — converter ffmpeg/pandoc → non applicable, même garde que F4) ; et sans
    # SÉLECTEUR il n'y a pas d'hôte (verdict Fabien 17/08 — describer routage auto,
    # avatarizer MuseTalk fixe → gate commun _has_engine_select, comme model_help).
    Criterion('input_match_ui', 'F2', 'Grisage des modèles incompatibles (WamaInputMatch)',
              lambda f: _present(f, TEMPLATES + JS, r'wama-input-match|WamaInputMatch')
              if _uses_models(f) and _has_engine_select(f) else (None, None),
              mecanisme='model_capabilities'),
    Criterion('filemanager_import', 'F2', 'Réception « Envoyer vers app » (wama:fileimported)',
              _filemanager_import),
    # Depuis 2026-08-13 la traversée vit dans la brique commune WamaFolderImport (extraite du
    # filemanager) : l'adoption se lit par `folder_input_id=` (card commune) ou l'appel direct.
    Criterion('recursive_import', 'F2', 'Import de DOSSIER récursif (brique WamaFolderImport)',
              _recursive_import,
              mecanisme='folder_import'),
    # Trou #26 (route §11) : le seul critère qui regarde si le markup d'entrée est ÉCOUTÉ.
    # Les autres critères d'import constatent une présence ; celui-ci constate un chargement.
    Criterion('import_wired', 'F2', 'Voie d’import CHARGÉE par le gabarit (dépôt non inerte)',
              _import_wired),
    # ── F3 UI / params / inspecteur ──
    Criterion('settings_modal_item', 'F3', 'Modale paramètres générée (WamaParams.render)', _params_modal,
              mecanisme='param_schema'),
    Criterion('init_from_schema', 'F3', 'Volet droit initFromSchema',
              lambda f: _present(f, TEMPLATES + JS, r'initFromSchema'),
              mecanisme='detail_registry'),
    Criterion('inspector_adapters', 'F3', 'Adapters preview + detail (apps.py)', _inspector_adapters,
              mecanisme='preview'),
    Criterion('inspector_actions', 'F3', 'Actions clonées dans le volet (_inspector_actions)',
              lambda f: _present(f, TEMPLATES, r"common/_inspector_actions\.html"),
              mecanisme='detail_registry'),
    Criterion('settings_modal_footer', 'F3', 'Pied de modale commun (_settings_modal_footer)',
              lambda f: _present(f, TEMPLATES, r"common/_settings_modal_footer\.html"),
              mecanisme='param_schema'),
    Criterion('model_help', 'F3', 'Descriptif moteur (wama-model-help)', _model_help,
              mecanisme='model_capabilities'),
    Criterion('params_schema', 'F3', 'Schéma de paramètres déclaratif (params.py → PARAMS_JSON)',
              lambda f: _present(f, PARAMS, r'schema_to_dicts\(|derive_from_model\(|Param\('),
              mecanisme='param_schema'),
    Criterion('params_modal_batch', 'F3', 'Modale BATCH générée par WamaParams', _params_modal_batch,
              mecanisme='param_schema'),
    Criterion('card_chips', 'F3', 'Chips métadonnée sur la card (card_chips)',
              lambda f: _present(f, VIEWS + TEMPLATES, r'card_chips|_card_chips\.html'),
              mecanisme='card_chips'),
    # ── Les 3 briques livrées le 18/08 et que RIEN ne mesurait (jonction 19/08) ──────────
    Criterion('card_gear', 'F3', 'data-* du gear ⚙ dérivés du schéma (brique card_gear)',
              _card_gear, mecanisme='card_gear'),
    Criterion('card_preview_hydratee', 'F3',
              'Aperçu de résultat dans la card par le mécanisme commun (data-card-preview)',
              _card_preview_hydratee, mecanisme='preview'),
    Criterion('inspector_detail_wired', 'F3',
              'Volet reflétant la card (data-preview-url + adapter detail enregistré)',
              _inspector_detail_wired, mecanisme='detail_registry'),
    # show_if des capacités-MODÈLE : sans moteur IA il n'y a pas de capacités à dériver
    # (verdict Fabien 13/08 — même garde _uses_models que F4) ; sans SÉLECTEUR, pas d'hôte
    # (verdict Fabien 17/08 — gate commun _has_engine_select, comme model_help).
    Criterion('model_caps_ui', 'F3', 'show_if dérivé des capacités-modèle (WamaModelCaps)',
              lambda f: _present(f, TEMPLATES + JS, r'wama-model-caps|WamaModelCaps')
              if _uses_models(f) and _has_engine_select(f) else (None, None),
              mecanisme='model_capabilities'),
    Criterion('modes', 'F3', 'Modes déclarés (APP_MODES) rendus par WamaModes', _modes_declared,
              mecanisme='app_modes'),
    Criterion('layout', 'F3', 'Bascule Ligne / Mosaïque (card_layout)',
              lambda f: _present(f, TEMPLATES + JS + VIEWS, r'card_layout|data-layout'),
              mecanisme='card_system'),
    Criterion('during_preview', 'F3', 'Aperçu « PENDANT » (émission backend + consommation front)',
              _during_preview,
              mecanisme='preview'),
    # ── F4 modèles ──
    Criterion('eta_seeded', 'F4', 'ETA seedée auto-apprenante (record_run + estimate)', _eta_seeded,
              mecanisme='eta'),
    Criterion('model_config', 'F4', 'Modèles déclarés par l’app (utils/model_config.py)',
              _f4(lambda f: _present(f, ['utils/model_config.py'], r'_MODELS\s*[:=]|_DIR\s*='))),
    Criterion('model_discovery', 'F4', 'Découverte au catalogue AIModel (_discover_<app>_models)',
              _f4(_model_discovery),
              mecanisme='model_registry_discovery'),
    Criterion('backend_contract', 'F4', 'Backends dérivés de BaseModelBackend (contrat commun)',
              _f4(_backend_contract),
              mecanisme='backend_contract'),
    Criterion('backend_packages', 'F4', 'Dépendances déclaratives (REQUIRED_PACKAGES)',
              _f4(lambda f: _present(f, PY, r'REQUIRED_PACKAGES'))),
    Criterion('model_caps_canonical', 'F4', 'Entrée au catalogue en capacités CANONIQUES',
              _f4(_model_caps_canonical),
              mecanisme='model_capabilities'),
    Criterion('select_model', 'F4', 'Sélection auto confiée à la brique commune (select_model)',
              _f4(_select_model),
              mecanisme='model_selector'),
    Criterion('vram_unloader', 'F4', 'Reclaim VRAM cross-app (unloader auto, explicite ou réservation)',
              _f4(_vram_unloader),
              mecanisme='memory_manager'),
    Criterion('hf_cache_isolation', 'F4', 'Cache HF isolé (HF_HUB_CACHE posé avant import)',
              _f4(lambda f: _present(f, PY, r'HF_HUB_CACHE')),
              mecanisme='hf_cache'),
    # ── F5 cycle de vie ──
    Criterion('anti_race', 'F5', 'Verrou anti-race sur TOUTES les vues de démarrage', _anti_race),
    Criterion('reconcile_orphans', 'F5', 'Réconciliation RUNNING orphelins (IndexView)',
              lambda f: _present(f, VIEWS, r'reconcile_orphaned_running')),
    Criterion('auto_wrap_orphans', 'F5', 'Auto-wrap des items hors batch',
              lambda f: _present(f, VIEWS, r'auto_wrap_orphans'),
              mecanisme='batch'),
    Criterion('processing_time', 'F5', 'ProcessingTimeMixin (temps réel persisté)',
              lambda f: _present(f, MODELS, r'ProcessingTimeMixin')),
    Criterion('status_vocab', 'F5', 'Vocabulaire de statuts SUCCESS/FAILURE en base',
              lambda f: _present(f, MODELS, r"'SUCCESS'")),
    Criterion('cycle_button', 'F5', 'Bouton de cycle commun (_cycle_button)',
              lambda f: _present(f, TEMPLATES, r"common/_cycle_button\.html"),
              mecanisme='cycle_button'),
    Criterion('card_html_endpoint', 'F5', 'Card = partial serveur + endpoint card_html',
              lambda f: _present(f, URLS, r'card_html'),
              mecanisme='card_system'),
    #: ⚠ DEUX graphies acceptees, et c'est deliberé : depuis le 2026-08-25 l'include de la card
    #: mere a migre dans `_queue_entry.html` (brique commune). Ne chercher que `_batch_card` dans
    #: le gabarit d'app ferait passer au ROUGE les 8 apps qui viennent de l'adopter — un critere
    #: qui mesure du markup doit SUIVRE ce markup quand il se centralise, sinon il punit
    #: l'adoption. Precedent identique : `btn_order`, rouge sur 10 apps quand le bouton
    #: telecharger a rejoint le partial commun (2026-08-23).
    Criterion('batch_card_common', 'F5', 'Card mère de batch commune (_batch_card, direct ou via _queue_entry)',
              lambda f: _present(f, TEMPLATES, r"common/_(batch_card|queue_entry)\.html"),
              mecanisme='queue_front'),
    Criterion('build_batches_list', 'F5', 'Agrégats de file communs (build_batches_list)',
              lambda f: _present(f, VIEWS, r'build_batches_list'),
              mecanisme='batch'),
    Criterion('queue_manipulation', 'F5', 'Manipulation directe (fabrique 4 vues)', _queue_manipulation,
              mecanisme='queue_manipulation'),
    Criterion('queue_toolbar', 'F5', 'Tri/filtre communs (queue_view + _queue_toolbar)', _queue_toolbar,
              mecanisme='queue_view'),
    Criterion('wama_card', 'F5', 'Contrat CSS .wama-card sur la card',
              lambda f: _present(f, CARD_TPL, r'wama-card'),
              mecanisme='card_system'),
    # La card v3 (CARD_DESIGN §11, pilote reader) INTÈGRE état + barre (wama-status-dot +
    # wcv3-bar/wama-progress-track) : elle satisfait le critère SANS les includes v2 —
    # le check retardait sur le formalisme et sanctionnait les cards les plus récentes
    # (constaté 13/08 : reader/describer/composer rouges, puis converter au moment du port).
    Criterion('card_progress_brick', 'F5', 'État + progression par briques communes (v2 includes ou card v3)',
              lambda f: _present(f, TEMPLATES,
                                 r"common/_card_progress\.html|common/_card_state\.html"
                                 r"|wcv3-bar|wama-progress-track"),
              mecanisme='progress_ui'),
    Criterion('eta_individual', 'F5', 'ETA affichée par card (.wama-eta)',
              lambda f: _present(f, TEMPLATES, r'wama-eta'),
              mecanisme='progress_ui'),
    Criterion('eta_queue', 'F5', 'Barre globale (_global_progress)',
              lambda f: _present(f, TEMPLATES, r"common/_global_progress\.html"),
              mecanisme='progress_ui'),
    Criterion('toast', 'F5', 'WamaApp.toast (zéro alert())', _toast,
              mecanisme='app_base_js'),
    Criterion('duplicate_wiring', 'F5', 'Duplication via la brique (handler UNIQUE)', _duplicate_wiring,
              mecanisme='queue_duplication'),
    # Jumeau du précédent, ajouté le 2026-08-22 EN MÊME TEMPS que la brique de suppression :
    # tant qu'aucun domicile commun n'existait, il n'y avait rien à mesurer (cf. `_delete_wiring`).
    Criterion('delete_wiring', 'F5', 'Suppression via la brique (handler UNIQUE)', _delete_wiring,
              mecanisme='queue_front'),
    # Troisième jumeau (2026-08-23) : la brique ⚙ a rejoint queue-actions.js. Les trois actions
    # de card qui SONT des comportements (dupliquer, supprimer, paramétrer) ont désormais chacune
    # leur critère — c'est la réponse à la « maille trop grossière » du §5 de WAMA_VERIFICATION :
    # on note des ACTIONS, pas un mécanisme fourre-tout qui passe au vert dès qu'un seul de ses
    # cinq comportements est vérifié.
    Criterion('settings_wiring', 'F5', 'Paramètres via la brique (bouton + ouvreur déclaré)',
              _settings_wiring, mecanisme='queue_front'),
    # Quatrième jumeau (2026-08-23) : les QUATRE actions de card qui ont un domicile commun ont
    # chacune leur critère. ⬇ est rattaché à `param_schema` et non à `queue_front` : sa forme est
    # dictée par une DÉCLARATION du catalogue (`export_formats`/`export_binding`), pas par le
    # comportement de la file.
    Criterion('download_wiring', 'F3', 'Téléchargement via la brique (forme dérivée de la déclaration)',
              _download_wiring, mecanisme='param_schema'),
    Criterion('duplicate_instance', 'F5', 'duplicate_instance() (brique commune)',
              lambda f: _present(f, VIEWS, r'duplicate_instance'),
              mecanisme='queue_duplication'),
    Criterion('safe_delete', 'F5', 'safe_delete_file() (fichiers partagés)',
              lambda f: _present(f, VIEWS, r'safe_delete_file'),
              mecanisme='queue_duplication'),
    Criterion('user_settings', 'F5', 'Réglages user persistés (brique user_settings)', _user_settings,
              mecanisme='user_settings'),
    Criterion('start_all', 'F5', 'Vue start_all',
              lambda f: _present(f, URLS, r'start_all|start-all')),
    Criterion('clear_all', 'F5', 'Vue clear_all',
              lambda f: _present(f, URLS, r'clear_all|clear-all')),
    Criterion('download_all', 'F5', 'Vue download_all',
              lambda f: _present(f, URLS, r'download_all|download-all')),
    Criterion('batch_template', 'F5', 'Gabarit batch téléchargeable',
              lambda f: _present(f, URLS, r'batch_template|batch-template')),
    Criterion('btn_order', 'F5', 'Ordre canonique des boutons ⚙▶⬇⧉🗑', _btn_order),
    Criterion('crash_redelivery_guard', 'F5', 'Garde anti-BOUCLE-de-crash (refuse_crash_redelivery)',
              # la brique task_skeleton (A2) porte la garde pour toute tâche qui l'adopte
              lambda f: _present(f, TASKS, r'refuse_crash_redelivery|run_item_task'),
              mecanisme='process_control'),
    Criterion('error_message_field', 'F5', 'Champ error_message sur le modèle d’item',
              lambda f: _present(f, MODELS, r'error_message\s*=\s*models\.')),
    # ── F6 prompts & tool_api ──
    Criterion('prompt_targets', 'F6', 'Champs-prompt déclarés (PROMPT_TARGETS)',
              _f6_prompt(lambda f: (
                  f.app in _registry_keys('PROMPT_TARGETS', 'common/utils/app_metadata.py'),
                  f"common/utils/app_metadata.py PROMPT_TARGETS['{f.app}']"
                  if f.app in _registry_keys('PROMPT_TARGETS', 'common/utils/app_metadata.py')
                  else "champ prompt non déclaré → ni traduction ni enrichissement")),
              mecanisme='prompt_pipeline'),
    Criterion('prompt_pipeline', 'F6', 'Pipeline commune appelée (process_prompt_for)',
              _f6_prompt(lambda f: _present(f, TASKS + VIEWS, r'process_prompt_for')),
              mecanisme='prompt_pipeline'),
    Criterion('prompt_skill', 'F6', 'Skill de prompt dédiée (common/prompt_skills/<app>-*.md)',
              _f6_prompt(_prompt_skill)),
    Criterion('prompt_enrich_ui', 'F6', 'Champ prompt à deux états (wama-prompt-enrich)',
              _f6_prompt(lambda f: _present(f, TEMPLATES + JS, r'wama-prompt-enrich|WamaPromptEnrich')),
              mecanisme='prompt_pipeline'),
    Criterion('tool_api_item_id', 'F6', "Contrat de retour add_to_<app> → 'item_id'", _tool_api_item_id,
              mecanisme='tool_api'),
    # ── F7 permissions & scope données ──
    Criterion('access_policy', 'F7', "Gating d'app déclaré (DEFAULT_APP_ACCESS)", _access_policy),
    Criterion('app_access_view', 'F7', 'Décorateur @app_access sur les vues (défense en profondeur)',
              lambda f: _present(f, VIEWS, r'@app_access')),
    Criterion('user_scope', 'F7', 'Requêtes filtrées par utilisateur (scope données)',
              lambda f: _present(f, VIEWS, r'user\s*=\s*(request\.user|self\.request\.user|user)\b'),
              mecanisme='scoping'),
    Criterion('shareable_models', 'F7', 'Cards ET batchs partageables (ScopedVisibility)',
              _shareable_models,
              mecanisme='scoped_visibility'),
    Criterion('scoped_reads', 'F7', 'Lectures via les accès nommés (visible_or_404/visible_to)',
              _scoped_reads,
              mecanisme='scoping'),
    # ── F8 studio ──
    Criterion('studio_runnable', 'F8', 'Nœud studio câblé (GENERIC_APPS)',
              lambda f: (f.app in _registry_keys('GENERIC_APPS', GENERIC_RUNNER_PY),
                         f"{GENERIC_RUNNER_PY} GENERIC_APPS['{f.app}']"
                         if f.app in _registry_keys('GENERIC_APPS', GENERIC_RUNNER_PY) else None),
              mecanisme='generic_runner'),
    Criterion('studio_params_module', 'F8', 'Params du nœud tirés du schéma de l’app', _studio_params,
              mecanisme='param_schema'),
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
