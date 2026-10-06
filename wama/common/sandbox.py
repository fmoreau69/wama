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


#: Dernière lecture du registre, rejouée tant que le fichier n'a pas changé (même mtime et taille).
_REGISTRY_CACHE = {'stamp': None, 'data': []}


def load_registry() -> list:
    """Liste des jumelles [{label, generated_from, created, created_by?}] — [] si registre
    absent/illisible. `created_by` (2026-09-03, demande Fabien) = username du CRÉATEUR :
    porte la visibilité « créateur + dev + admin » ; absent/vide = jumelle d'opérateur CLI
    (visible des seuls dev/admin, comportement historique).

    Relu seulement s'il a CHANGÉ (2026-10-02) : le menu le lisait 26 fois par page, une lecture
    et une analyse JSON sur /mnt/d à chaque fois. Un `stat` suffit à savoir s'il a bougé ; la
    copie rendue est neuve, un appelant ne peut pas altérer le cache."""
    try:
        st = REGISTRY_PATH.stat()
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp != _REGISTRY_CACHE['stamp']:
            data = json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))
            _REGISTRY_CACHE['data'] = data if isinstance(data, list) else []
            _REGISTRY_CACHE['stamp'] = stamp
        return [dict(e) if isinstance(e, dict) else e for e in _REGISTRY_CACHE['data']]
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


def declaring_app(app: str) -> str:
    """L'app dont la DÉCLARATION fait foi pour `app` : elle-même, ou sa SOURCE si c'est une
    jumelle. Les registres indexés par app qui servent une jumelle passent par ici (le catalogue
    des modèles : une jumelle LIT les modèles de sa source, elle n'en duplique aucune ligne)."""
    return twin_source(app) or app


def _retarget(value, src: str, label: str):
    """Une déclaration de la source, ses chemins `wama.<src>.…` re-ciblés sur le paquet de la
    jumelle. Un module `workers` devient `tasks` quand la jumelle a le sien généré : la
    substitution `tasks` REMPLACE `workers.py` (Celery autodécouvre les deux noms, la même tâche
    serait enregistrée deux fois — règle de `app_sandbox substitute`)."""
    if isinstance(value, dict):
        return {k: _retarget(v, src, label) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_retarget(v, src, label) for v in value)
    if not isinstance(value, str) or not value.startswith(f'wama.{src}.'):
        return value
    moved = f'wama.{label}.' + value[len(f'wama.{src}.'):]
    base = Path(__file__).resolve().parent.parent / label
    if moved.startswith(f'wama.{label}.workers.') and not (base / 'workers.py').exists() \
            and (base / 'tasks.py').exists():
        moved = moved.replace(f'wama.{label}.workers.', f'wama.{label}.tasks.', 1)
    return moved


def inject_sandbox_registry(registry: dict, *, runnable=None) -> None:
    """Entrées d'un registre INDEXÉ PAR APP pour les jumelles : la déclaration de la source,
    chemins re-ciblés (`_retarget`). Décision de Fabien (2026-10-06) : une jumelle expose ce que
    son app source expose — mais SEULEMENT ce que l'exécution peut réellement faire tourner :
    `runnable(label)` écarte une entrée qui mènerait à un appel impossible (le nœud studio d'une
    jumelle sans outil de création). Consommateurs : `TRIAD_SPECS` (tool_api), `GENERIC_APPS`
    (studio). Une app née d'un manifeste (sans source) n'emprunte rien ici."""
    import copy
    for e in load_registry():
        label, src = e.get('label'), e.get('generated_from')
        if not label or not src or label in registry or src not in registry:
            continue
        if label not in sandbox_labels() or (runnable is not None and not runnable(label)):
            continue
        registry[label] = _retarget(copy.deepcopy(registry[src]), src, label)


def born_declaration(label: str, facet: str):
    """Facette DÉCLARÉE d'une app créée DE ZÉRO (`app_sandbox create --from-manifest`), telle que
    son manifeste la portait, ou None.

    Le pendant de `twin_source` pour une app SANS source : une jumelle emprunte les déclarations
    de son app source ; une app née d'un manifeste n'a que le manifeste. Les registres indexés par
    nom d'app (`APP_MODES`, `PROMPT_TARGETS`…) ne la connaissent pas — ce sont leurs ACCESSEURS qui
    lisent ici, comme ils lisent `twin_source` (règle de la docstring ci-dessus). Les facettes sont
    stockées au registre à la création : ce module reste pur (aucun import de la couche manifestes).
    """
    for e in load_registry():
        if e.get('label') == label and not e.get('generated_from'):
            return (e.get('declarations') or {}).get(facet)
    return None


def save_registry(entries: list) -> None:
    REGISTRY_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def sandbox_labels() -> list:
    """Labels des jumelles dont le PACKAGE existe réellement (garde anti-registre orphelin :
    une entrée sans package casserait le boot Django entier au chargement d'INSTALLED_APPS)."""
    base = Path(__file__).resolve().parent.parent
    return [e['label'] for e in load_registry()
            if LABEL_RE.match(e.get('label', '')) and (base / e['label'] / 'apps.py').exists()]


def twins_with_copied_views() -> set:
    """Labels des jumelles dont les VUES sont une COPIE figée de l'app source (non régénérées).

    Elles ne suivent pas le code réel par construction : un contrat qui les exigerait reviendrait
    à éditer une copie à la main. Les contrats génériques (suppression, parcours des adresses) les
    écartent donc — nommé ici le 2026-09-22 pour que les deux ne recopient pas la même règle.
    """
    # Le VERDICT fait foi, pas la présence de la clé : une substitution qui a échoué
    # (`revert`, `reverted-manuel`, `reverted-couple`) laisse la COPIE en place — imager_01
    # (22/09) était compté « généré » sur une clé `views: reverted-couple`, et le contrat de
    # suppression tombait sur sa copie du 05/09 (`find_member_batch`, retiré le 15/09).
    return {e['label'] for e in load_registry()
            if ((e.get('substituted') or {}).get('views') or {}).get('verdict') != 'ok'}


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
        if not label or label in app_catalog or label not in sandbox_labels():
            continue
        # App créée DE ZÉRO depuis un manifeste (`app_sandbox create --from-manifest`) : pas de
        # source à cloner — son entrée a été calculée à la création, depuis les facettes
        # identity/ports/capabilities du manifeste, et stockée au registre. Relue telle quelle :
        # ce module reste pur (aucun import de la couche manifestes au boot).
        if not src and entry.get('catalog'):
            born = dict(entry['catalog'])
            born['label'] = f"{born.get('label', label)} ⚠ BAC À SABLE"
            born['sandbox'] = True
            born['generated_from'] = ''
            born['from_manifest'] = entry.get('from_manifest', '')
            born['generation_run'] = entry.get('created', '')
            app_catalog[label] = born
            continue
        if src not in app_catalog:
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
