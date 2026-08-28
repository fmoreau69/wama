"""
Charpente des tests fonctionnels nocturnes de WAMA.
============================================================================

Idée (Fabien) : plutôt que des bêta-testeurs, automatiser le debug fonctionnel via
des SCÉNARIOS déclaratifs joués la nuit, sérialisés (un seul à la fois) pour ne pas
superposer des tâches gourmandes en VRAM, avec déchargement entre chaque.

Principes (cf. CLAUDE.md §Philosophie) :
- **Déclaratif & métadonnée-driven** : un scénario = des métadonnées + un callable `run`.
  Les apps enregistrent leurs scénarios ; le runner est générique.
- **Sérialisé + VRAM-aware** : un scénario à la fois, téardown VRAM avant ET après.
- **Étapes** : `stage` cible = 'wired' (chaîne importable) | 'model_loaded' (backend chargé,
  test rapide) | 'output' (chaîne complète jusqu'au résultat). Le mode partiel ('wired'/
  'model_loaded') permet un smoke test rapide et peu coûteux.
- **Garde-fous** : tourne sous un UTILISATEUR DE TEST dédié (jamais le compte réel id=1) ;
  les sorties de test se nettoient par IDs précis (cf. règle « pas de tests destructifs »).

⚠️ CHARPENTE : le cadre (registre, runner, téardown, rapport, user de test) est réel et
exécutable ; les scénarios fournis ici sont des SMOKE TESTS 'wired' (imports). À compléter
par app avec de vrais scénarios 'model_loaded'/'output' (pilotés via tool_api / tasks).

Lancement : `python manage.py run_nightly_tests [--app X] [--dry-run]`.
Planification nocturne : via Celery beat (non activé ici — charpente à valider d'abord).
"""
from __future__ import annotations

import importlib
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

TEST_USERNAME = "wama_nightly_test"

# Étapes cibles d'un scénario, du plus léger au plus complet.
# `ui` est à part : ~2 s par app, aucun GPU — à ne pas noyer dans la série lourde à teardown
# VRAM (`python manage.py run_nightly_tests --stage ui` doit rester quasi instantané).
# `consistency` est à part aussi : contrôles DÉCLARATIFS (docs↔code, corpus de manifestes,
# faits générés, redondances) — CPU pur, aucun média. Le runner nocturne est le SEUL
# ordonnanceur de ces contrôles : ne pas leur créer de cron concurrent (§16.9).
STAGES = ("wired", "ui", "consistency", "model_loaded", "output")


class SkipScenario(Exception):
    """Levée par un `run` quand une dépendance est absente (modèle/lib non installé) :
    le scénario est SKIPPÉ (ni succès ni échec) — il ne pollue pas les compteurs d'échec."""


@dataclass
class Scenario:
    """Un test fonctionnel déclaratif. `run(ctx) -> (ok: bool, detail: str)` ; peut lever."""
    id: str
    app: str
    description: str
    stage: str                       # cible attendue : voir STAGES
    run: Callable                    # callable(ctx: dict) -> (bool, str)
    timeout_s: int = 300
    vram_gb: float = 0.0             # info de planification (sérialisation déjà garantie)
    enabled: bool = True


@dataclass
class ScenarioResult:
    scenario_id: str
    app: str
    ok: bool
    stage_target: str
    stage_reached: str               # ok→stage cible ; sinon 'skipped'/'failed'/'error'
    duration_s: float
    detail: str = ""
    error: Optional[str] = None
    skipped: bool = False            # dépendance absente → ni passed ni failed


# Registre global. Les apps appellent register(...) (idéalement depuis leur AppConfig.ready()).
REGISTRY: List[Scenario] = []


def register(**kwargs) -> Scenario:
    """Enregistre un scénario. Doublon d'id → remplace (réimport sûr)."""
    sc = Scenario(**kwargs)
    global REGISTRY
    REGISTRY = [s for s in REGISTRY if s.id != sc.id]
    REGISTRY.append(sc)
    return sc


# ── Garde-fous & utilitaires ────────────────────────────────────────────────

def get_test_user():
    """Utilisateur de test DÉDIÉ (jamais le compte réel). Créé si absent.

    Rôles métier accordés (décision Fabien 2026-08-18 — travail de lecture/vérification/
    confrontation) : `communication` + `recherche` ouvrent toutes les apps à triade au
    gating (§F7), SANS tier développeur (pas de bypass : model_manager et jumelles bac à
    sable restent fermés — les outils de catalogue utiles sont transverses). Accordé ICI,
    déclarativement, pour être reproductible sur toute base (jamais un coup de base à la main).
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=TEST_USERNAME,
        defaults={"email": "nightly-test@wama.local", "is_active": True, "is_staff": False},
    )
    from wama.accounts.permissions import GROUP_PREFIX
    for role in ("communication", "recherche"):
        group, _ = Group.objects.get_or_create(name=f"{GROUP_PREFIX}{role}")
        user.groups.add(group)                 # idempotent
    return user


def free_vram() -> None:
    """Téardown VRAM best-effort entre scénarios (réutilise le cleaner du model_manager)."""
    try:
        from wama.model_manager.services.memory_cleaner import get_memory_cleaner
        get_memory_cleaner().aggressive_cleanup()
        return
    except Exception as exc:  # pragma: no cover
        logger.debug("cleaner indisponible (%s), fallback gc/torch", exc)
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# ── Runner sérialisé ────────────────────────────────────────────────────────

def run_one(sc: Scenario, ctx: dict) -> ScenarioResult:
    """Exécute UN scénario (timing + capture d'exception). NB : timeout dur = TODO prod
    (Celery soft_time_limit / subprocess) ; ici on mesure la durée, sans kill cross-platform."""
    start = time.time()
    try:
        ok, detail = sc.run(ctx)
        return ScenarioResult(
            scenario_id=sc.id, app=sc.app, ok=bool(ok), stage_target=sc.stage,
            stage_reached=sc.stage if ok else "failed",
            duration_s=round(time.time() - start, 2), detail=str(detail or ""),
        )
    except SkipScenario as skip:
        return ScenarioResult(
            scenario_id=sc.id, app=sc.app, ok=False, skipped=True, stage_target=sc.stage,
            stage_reached="skipped", duration_s=round(time.time() - start, 2),
            detail=str(skip),
        )
    except Exception as exc:
        logger.warning("[nightly] %s a levé: %s", sc.id, exc, exc_info=True)
        return ScenarioResult(
            scenario_id=sc.id, app=sc.app, ok=False, stage_target=sc.stage,
            stage_reached="error", duration_s=round(time.time() - start, 2),
            error=f"{type(exc).__name__}: {exc}",
        )


def run_all(scenarios: Optional[List[Scenario]] = None, write: bool = True) -> dict:
    """Joue les scénarios EN SÉRIE, téardown VRAM avant/après chacun. Retourne le rapport."""
    scenarios = scenarios if scenarios is not None else [s for s in REGISTRY if s.enabled]
    user = get_test_user()
    ctx = {"user": user}
    results: List[ScenarioResult] = []

    for sc in scenarios:
        free_vram()                       # état propre AVANT
        logger.info("[nightly] ▶ %s (%s, cible=%s)", sc.id, sc.app, sc.stage)
        results.append(run_one(sc, ctx))
        free_vram()                       # libère la VRAM APRÈS (pour le suivant)

    report = build_report(results)
    if write:
        path = write_report(report)
        report["report_path"] = str(path)
    return report


def build_report(results: List[ScenarioResult]) -> dict:
    passed = sum(1 for r in results if r.ok)
    skipped = sum(1 for r in results if r.skipped)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(results),
            "passed": passed,
            "skipped": skipped,
            "failed": len(results) - passed - skipped,
        },
        "results": [asdict(r) for r in results],
    }


def write_report(report: dict) -> Path:
    out_dir = Path(settings.BASE_DIR) / "logs" / "nightly_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"nightly_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ── Scénarios d'exemple (SMOKE 'wired' — imports sûrs, zéro effet de bord) ────
# À COMPLÉTER : ajouter par app des scénarios 'model_loaded' (charger le backend puis
# décharger) et 'output' (chaîne complète sur une fixture, assertion sur le résultat,
# nettoyage par IDs). Pilotage recommandé via tool_api (registre d'outils de l'assistant).

def _smoke_import(module_path: str) -> Callable:
    def run(ctx):
        importlib.import_module(module_path)
        return True, f"import {module_path} OK"
    return run


def register_examples() -> None:
    register(id="transcriber.wired", app="transcriber", stage="wired",
             description="Smoke : la chaîne du transcriber (views) est importable",
             run=_smoke_import("wama.transcriber.views"))
    register(id="synthesizer.wired", app="synthesizer", stage="wired",
             description="Smoke : la chaîne du synthesizer (views) est importable",
             run=_smoke_import("wama.synthesizer.views"))


# Auto-enregistrement des exemples au chargement du module (charpente démontrable).
register_examples()

# Scénarios UI (un par app exposant une page d'index) — import TARDIF et tolérant : Playwright
# ou le serveur peuvent manquer sur une machine de dev, ça ne doit pas casser le registre.
try:
    from wama.common.services.ui_smoke import (register_batch_actions_scenarios,
                                               register_batch_import_scenarios,
                                               register_clear_all_scenarios,
                                               register_duplicate_delete_scenarios,
                                               register_import_scenarios,
                                               register_inspector_actions_scenarios,
                                               register_settings_scenarios,
                                               register_ui_scenarios,
                                               register_volet_scenarios)
    register_ui_scenarios()
    # `<app>.ui` mesure la SANTÉ de la page (200, 0 erreur console) ; `<app>.import` mesure
    # son COMPORTEMENT. Les deux sont nécessaires : converter_01 satisfaisait le premier tout
    # en étant inerte — aucun script chargé, donc rien à planter (mesuré 2026-08-22).
    register_import_scenarios()
    # Phase 1 de la grille FONCTIONNELLE (WAMA_VERIFICATION.md §6) : les gestes 3 et 4 de la
    # convention. Premier scénario à mesurer une convention que ​RIEN ne garantissait — les
    # boutons `.duplicate-btn`/`.delete-btn` sont réécrits par chaque app, pas hérités d'un
    # partial commun.
    register_duplicate_delete_scenarios()
    # Geste 2 de la convention (2026-08-23), enregistré le jour où le ⚙ a obtenu sa brique et son
    # critère `settings_wiring`. Le critère est vert sur 10/10 ; ce scénario existe précisément
    # parce qu'un vert d'ADOPTION ne dit rien du FONCTIONNEMENT — il atteste deux présences dans
    # le code, pas qu'une modale s'ouvre ni qu'elle contient quoi que ce soit.
    register_settings_scenarios()
    # Premier scénario portant sur le LOT et non sur l'ÉLÉMENT (2026-08-24). Il manquait, et le
    # trou était structurel : `<app>.duplicate_delete` vise `.wama-card[data-id]`, donc la card
    # FILLE — les boutons de la card MÈRE n'étaient exercés par AUCUN clic, alors qu'ils venaient
    # d'être portés à la brique commune sur 5 apps. Un portage non exercé est un portage supposé ;
    # celui-ci commence par dire si l'app est portée (URLs émises) avant de mesurer le geste.
    register_batch_actions_scenarios()
    # Le VOLET DROIT est une troisième surface : ni la santé de la page ni la création d'un
    # élément ne voient un ✕ qui ne désélectionne pas (aucune erreur console — cf. WAMA_VOLETS §4).
    register_volet_scenarios()
    # 2026-08-27 — le chemin que AUCUN des six précédents n'emprunte : la SÉLECTION.
    # `batch_actions` clique les boutons DE la card ; c'est `selectItem`/`selectBatch` qui
    # peuplent le volet Actions. D'où deux défauts MUETS passés au travers du nocturne :
    # le contrat inversé de `renderBatchActions` (TypeError, 4 apps, atteint sur un compte
    # réel) et l'imager sans aucun rappel (`fillActions` fait `if (renderFn)` → volet vide,
    # zéro erreur). La mesure n'est que des clics ; le chemin « card mère » exige en revanche
    # un lot multi-éléments, que le scénario MONTE quand il manque, sous une garde qui retire
    # en sortie ce qu'il a créé et rien d'autre (différence d'ids) — jamais un objet existant.
    register_inspector_actions_scenarios()
    # 2026-08-27 — geste 14 (moitié « fichier de lot »), enregistré À LA PLACE du geste 7 qui
    # devait suivre. Le geste 7 (« créer par le bouton primaire ») débloquait d'un coup
    # `inspector_actions` et `batch_actions` sur les trois apps dont la file reste vide — mais
    # il s'est révélé être un geste GPU sur deux d'entre elles : composer expédie la tâche DANS
    # sa vue de création (`composer/views.py:235`), avatarizer enchaîne `createJob()` puis
    # `startJob()` (`avatarizer/js/index.js:253-254`). Une session ne lance jamais de traitement.
    # Le fichier de lot atteint le même but par la seule voie dont le CONTRAT sépare « Ajouter »
    # de « Démarrer » — et le scénario vérifie que ce contrat est tenu, car c'est lui qui
    # l'autorise à tourner de jour sur un GPU partagé.
    register_batch_import_scenarios()
    # 2026-08-28 — geste 5, le seul du catalogue dont l'effet VOULU est destructeur. Il ne
    # s'exerce donc que sous le compte de TEST, et la borne n'est pas la prudence de
    # l'instrument : les dix vues `clear_all` filtrent sur `user=` (10/10). Il mesure TROIS
    # vérités que rien n'obligeait à coïncider — la file vue par l'utilisateur juste après son
    # clic (les gestionnaires d'app retirent les cards à la main : ce que leur sélecteur ne vise
    # pas reste à l'écran), celle que le serveur a réellement vidée, et **la BASE, que nul écran
    # ne montre** : un lot vidé ne rend aucune card, donc rien ne le trahirait.
    register_clear_all_scenarios()
except Exception as _e:                                   # pragma: no cover
    logger.debug(f"[nightly] scénarios UI non enregistrés ({_e})")
