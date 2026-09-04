"""Bac à sable d'apps — jumelles EXÉCUTABLES (route §10.3, marche S, actée Fabien 2026-08-18).

Registre des apps-jumelles (`wama/sandbox_apps.json`, GITIGNORÉ — un bac à sable est jetable)
+ points d'injection runtime : une jumelle `converter_01` coexiste avec l'app en place pour
comparaison visuelle (Playwright côte à côte) et diff code dé-suffixé.

Consommateurs des helpers (injection au chargement, AUCUNE édition de fichier par jumelle) :
  - `settings.py`            → INSTALLED_APPS += sandbox_installed_apps()
  - `wama/urls.py`           → urlpatterns += sandbox_urlpatterns()
  - `accounts/permissions.py`→ inject_sandbox_access(DEFAULT_APP_ACCESS, APP_GROUP)
  - `common/app_registry.py` → inject_sandbox_catalog(APP_CATALOG)  (badge « BAC À SABLE »,
                               marqueur generated_from ; EXCLU de la grille de conformité)

Module PUR côté lecture (json/pathlib seulement au niveau module) : importable par settings
sans effet de bord. La commande `manage.py app_sandbox` (create/drop/list) est l'UNIQUE
écrivain du registre — jamais de nettoyage à la main.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

#: Registre des jumelles — au niveau du package wama/ (comme settings), gitignoré.
REGISTRY_PATH = Path(__file__).resolve().parent.parent / 'sandbox_apps.json'

#: Suffixe réglementaire : `_NN` (deux chiffres) — identifiant Python ET slug URL valides.
LABEL_RE = re.compile(r'^(?P<base>[a-z_]+)_(?P<num>\d{2})$')


def load_registry() -> list:
    """Liste des jumelles [{label, generated_from, created, created_by?}] — [] si registre
    absent/illisible. `created_by` (2026-09-03, demande Fabien) = username du CRÉATEUR :
    porte la visibilité « créateur + dev + admin » ; absent/vide = jumelle d'opérateur CLI
    (visible des seuls dev/admin, comportement historique)."""
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def twin_owner(label: str) -> str:
    """Username du créateur d'une jumelle ('' si CLI/inconnu) — consommé par la dérogation
    d'accès (`accounts.permissions._app_accessible`)."""
    for e in load_registry():
        if e.get('label') == label:
            return e.get('created_by') or ''
    return ''


def twin_source(label: str) -> str:
    """App SOURCE d'une jumelle ('' si ce label n'en est pas une).

    Permet aux registres INDEXÉS PAR NOM D'APP de servir une jumelle sans qu'elle y soit
    déclarée — une jumelle témoin EST le même code, donc les mêmes déclarations.
    `inject_sandbox_catalog` fait déjà ce clonage pour `APP_CATALOG` ; tout autre registre
    du même genre doit passer par ici plutôt que de rester muet.
    1er consommateur : `common/utils/app_modes.get_app_modes` (2026-09-04).
    """
    for e in load_registry():
        if e.get('label') == label:
            return e.get('generated_from') or ''
    return ''


def save_registry(entries: list) -> None:
    REGISTRY_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def sandbox_labels() -> list:
    """Labels des jumelles dont le PACKAGE existe réellement (garde anti-registre orphelin :
    une entrée sans package casserait le boot Django entier au chargement d'INSTALLED_APPS)."""
    base = Path(__file__).resolve().parent.parent
    return [e['label'] for e in load_registry()
            if LABEL_RE.match(e.get('label', '')) and (base / e['label'] / 'apps.py').exists()]


def sandbox_installed_apps() -> list:
    """Entrées INSTALLED_APPS des jumelles (consommé par settings.py)."""
    return [f'wama.{label}' for label in sandbox_labels()]


def sandbox_urlpatterns():
    """URLconfs des jumelles — préfixe = label (underscore assumé : `/converter_01/` — le
    segment premier résout directement le gating, sans entrer dans PATH_APP_MAP ; piège du
    tiret mesuré sur model-manager, audit P2 17/08)."""
    from django.urls import include, path
    pats = []
    for label in sandbox_labels():
        try:
            pats.append(path(f'{label}/', include((f'wama.{label}.urls', label),
                                                  namespace=label)))
        except Exception:
            # Une jumelle au urls.py cassé ne doit pas tuer le routing GLOBAL.
            continue
    return pats


def inject_sandbox_access(default_app_access: dict, app_group: dict) -> None:
    """Gating DEV-ONLY des jumelles (contrat marche S §3) + groupe d'affichage dédié."""
    for label in sandbox_labels():
        default_app_access.setdefault(
            label, {'roles': ['ingenierie'], 'min_tier': 'developpeur'})
        app_group.setdefault(label, 'Bac à sable')


def inject_sandbox_catalog(app_catalog: dict) -> None:
    """Entrées APP_CATALOG des jumelles : CLONE de l'app source (mêmes conventions — la
    jumelle témoin EST le même code) + marqueurs `sandbox`/`generated_from` + badge dans le
    label + url_name re-namespacé. Les consommateurs de conformité EXCLUENT `sandbox`."""
    import copy
    for entry in load_registry():
        label, src = entry.get('label'), entry.get('generated_from')
        if not label or label in app_catalog or src not in app_catalog:
            continue
        if label not in sandbox_labels():
            continue
        clone = copy.deepcopy(app_catalog[src])
        clone['label'] = f"{clone.get('label', src)} ⚠ BAC À SABLE"
        clone['sandbox'] = True
        clone['generated_from'] = src
        clone['generation_run'] = entry.get('created', '')
        url_name = clone.get('url_name', f'{src}:index')
        clone['url_name'] = f"{label}:{url_name.split(':', 1)[-1]}"
        app_catalog[label] = clone


def non_sandbox_apps(app_catalog: dict) -> list:
    """Apps RÉELLES du catalogue (les jumelles sont exclues de la grille de conformité :
    on ne mesure pas un bac à sable, on le COMPARE à sa source)."""
    return sorted(k for k, v in app_catalog.items() if not (v or {}).get('sandbox'))
