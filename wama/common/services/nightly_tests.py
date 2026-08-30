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
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

TEST_USERNAME = "wama_nightly_test"
TEST_DEV_USERNAME = "wama_nightly_dev"   # surfaces dev-gated (jumelles) — cf. get_test_dev_user

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


def get_test_dev_user():
    """Compte de test DÉVELOPPEUR, dédié aux surfaces dev-gated (jumelles de bac à sable).

    ⚠ SÉPARÉ de `get_test_user` À DESSEIN : le compte nocturne standard est SANS tier
    développeur par décision (2026-08-18, docstring ci-dessus) et la matrice de droits
    (`rights_matrix`, 68 couples) mesure SES droits — l'élargir fausserait la matrice.
    Les scénarios des jumelles (`converter_01.*` — gate déclaré `sandbox.py` : rôle
    `ingenierie` + tier `developpeur`) utilisent CE compte-ci. Mesuré le 2026-08-30 :
    sans lui, les 11 scénarios de la jumelle skippent (« Accès non autorisé ») et rien
    de la surface générée n'est éprouvé mécaniquement.
    Créé déclarativement (reproductible sur toute base, jamais un coup de base à la main).
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username=TEST_DEV_USERNAME,
        defaults={"email": "nightly-dev@wama.local", "is_active": True, "is_staff": False},
    )
    from wama.accounts.permissions import GROUP_PREFIX
    group, _ = Group.objects.get_or_create(name=f"{GROUP_PREFIX}ingenierie")
    user.groups.add(group)                     # idempotent
    prof = getattr(user, 'profile', None)
    if prof is not None and getattr(prof, 'account_tier', '') != 'developpeur':
        prof.account_tier = 'developpeur'
        prof.save(update_fields=['account_tier'])
    return user


# Un fichier témoin se RECONNAÎT à son nom : `wama_temoin_*` depuis le 28/08 (`_fichier_temoin`),
# `tmp` + 8 caractères pour tout ce que `tempfile` a produit AVANT ce nommage — c'est la forme
# exacte de `NamedTemporaryFile`, pas un `tmp` au sens large : un fichier que quelqu'un aurait
# nommé `tmp_export.csv` n'est pas à nous et ne doit pas disparaître.
_MOTIF_TEMOIN = re.compile(r'^(wama_temoin_|tmp[A-Za-z0-9_]{8})')
# Les comptes de test connus (même liste que `_test_session_key` dans ui_smoke).
TEST_USERNAMES = (TEST_USERNAME, 'ui_smoke_v3', 'pw_smoke', 'wama_rights_commun',
                  'wama_rights_communication', 'wama_rights_recherche', 'wama_rights_developpeur')


def sweep_test_witnesses() -> int:
    """Efface les FICHIERS témoins restés dans les dossiers média des comptes de TEST.

    ⚠ Les scénarios ont un filet ORM (la garde de montage retire ce qu'ils ont créé, en
    différence d'ids), et il est bon. Mais un filet ORM ne voit que ce qui a une LIGNE : un
    fichier que l'app a copié dans `media/<app>/<uid>/input/` sans qu'un élément survive — import
    refusé, scénario interrompu, `delete()` d'une vue qui ne débranche pas le FileField — ne lui
    apparaît jamais. Mesuré le 2026-08-28 : **146 témoins** accumulés sur 7 apps, tous sous le
    compte de test, invisibles de toute mesure. D'où ce second filet, qui travaille sur le
    DISQUE et non sur la base.

    Trois bornes, cumulatives — c'est ce qui rend un balayage automatique acceptable :
      1. uniquement les dossiers média des comptes de TEST (`TEST_USERNAMES`) ;
      2. uniquement des fichiers dont le NOM est celui d'un témoin (`_MOTIF_TEMOIN`) ;
      3. jamais de dossier supprimé, et la récursion ne sort JAMAIS de `media/<app>/<uid>/`.
    Un fichier du compte réel de Fabien ne peut donc pas être atteint, même par accident.

    ⚠ La récursion n'est pas du zèle : une profondeur FIXE (`*/<uid>/*/*`) laissait 16 témoins
    sur place — l'enhancer range les siens dans `input/media/`, un niveau plus bas. Supposer
    l'arborescence des apps identique, c'est laisser le balayage mentir sur ce qu'il balaie.
    """
    from pathlib import Path
    from django.conf import settings
    from django.contrib.auth import get_user_model

    ids = list(get_user_model().objects.filter(username__in=TEST_USERNAMES)
               .values_list('pk', flat=True))
    if not ids:
        return 0
    racine = Path(settings.MEDIA_ROOT)
    n = 0
    for uid in ids:
        for dossier in racine.glob(f'*/{uid}'):
            if not dossier.is_dir():
                continue
            for chemin in dossier.rglob('*'):
                if not (chemin.is_file() and _MOTIF_TEMOIN.match(chemin.name)):
                    continue
                try:
                    chemin.unlink()
                    n += 1
                except OSError as exc:                       # pragma: no cover
                    logger.debug("[nightly] témoin non effacé %s (%s)", chemin, exc)
    return n


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

    # Filet de SORTIE — le pendant fichiers du filet ORM des scénarios. Voir `sweep_test_witnesses`.
    balayes = sweep_test_witnesses()
    if balayes:
        logger.info("[nightly] %d fichier(s) témoin balayé(s) des comptes de test", balayes)

    report = build_report(results)
    report["witness_files_swept"] = balayes
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
                                               register_folder_import_scenarios,
                                               register_import_scenarios,
                                               register_inspector_actions_scenarios,
                                               register_send_to_scenarios,
                                               register_settings_scenarios,
                                               register_ui_scenarios,
                                               register_url_import_scenarios,
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
    # 2026-08-28 — geste 14, moitié « ENVOYER VERS » : le seul import qui ne PART PAS de l'app.
    # Il traverse deux moitiés bâties sur des sources DIFFÉRENTES — le menu se construit chez le
    # client depuis `WAMA_APP_CATALOG.input_extensions` (la déclaration de l'app), la réception
    # se valide chez le serveur contre une liste écrite à la main dans `api_import_to_app`. Rien
    # n'oblige les deux à coïncider, et rien ne le signalait : une app OFFERTE puis REFUSÉE ne
    # produit qu'un toast d'erreur. Un test qui posterait sur l'endpoint ne le verrait jamais —
    # il faut passer par le menu, c'est-à-dire par le geste.
    register_send_to_scenarios()
    # 2026-08-28 — geste 14, moitié « URL ». Le seul geste du catalogue qui fait SORTIR le
    # serveur, donc le seul dont la mesure rencontre la garde SSRF (`url_guard`). Le scénario
    # ne la contourne pas : il publie son témoin sous MEDIA_URL (bouclage), et lit ce que
    # l'app en fait. Une app qui le TÉLÉCHARGE quand même n'appelle pas la garde — c'est un
    # échec de sécurité, pas un succès du geste, et aucune autre mesure ne le verrait.
    register_url_import_scenarios()
    # 2026-08-28 — geste 14, dernier quart : l'IMPORT DE DOSSIER. Le seul geste du catalogue
    # dont une partie est INATTEIGNABLE par un harnais — le sélecteur de dossier est une boîte
    # de dialogue du SYSTÈME. Il se mesure donc en deux moitiés SÉPARÉES, parce qu'elles
    # cassent séparément : la traversée récursive de la brique commune (exercée sur un arbre
    # synthétique — c'est le code de production qui tourne), puis le câblage de l'app (N
    # fichiers posés → N éléments EN BASE, car une app qui groupe rendrait UNE card pour deux).
    register_folder_import_scenarios()
except Exception as _e:                                   # pragma: no cover
    logger.debug(f"[nightly] scénarios UI non enregistrés ({_e})")

# Scénarios de DROITS — bloc SÉPARÉ, et pas par goût de la symétrie : ils ne dépendent pas de
# Playwright (HTTP nu). Les loger dans le `try` ci-dessus les ferait disparaître du registre sur
# toute machine sans navigateur, sans que rien ne le dise — exactement la panne muette que le
# dépôt traque. Demande de Fabien (28/08) : mesurer que les accès et restrictions appliqués
# correspondent à ce qui est octroyé à chaque utilisateur.
try:
    from wama.common.services.rights_matrix import register_rights_scenarios
    register_rights_scenarios()
except Exception as _e:                                   # pragma: no cover
    logger.debug(f"[nightly] scénarios de droits non enregistrés ({_e})")
