"""
Balayage d'ADOPTION des mécanismes : qui consomme quoi, et à quel niveau.

POURQUOI CE MODULE. La logique vivait en closure dans `doc_facts` (rendu de la carte). Elle a
un DEUXIÈME consommateur depuis le 2026-08-19 — le contrôle de jonction « mécanisme de niveau
app sans critère de grille » — donc elle sort ici plutôt que d'être dupliquée (règle du dépôt :
extraire au 2ᵉ consommateur, jamais copier). `doc_facts` l'importe et rend exactement la même
carte ; le contrôle et (plus tard) la page développeur lisent la même mesure.

NIVEAU D'UN MÉCANISME — la distinction qui rend la jonction mécanique (décision Fabien 19/08).
  • **niveau app** : au moins un fichier sous `wama/<app>/` le consomme → la grille de conformité
    DOIT avoir un critère qui le vérifie, sinon une app peut sortir à 100 % sans l'avoir adopté.
  • **infrastructure** : aucune app ne le consomme (`bench`, `mirror_sync`, `retention`…) → un
    critère par app n'aurait AUCUN sens.
Cette règle remplace le seuil arbitraire (« à partir de combien de consommateurs ? ») qui était
la question ouverte : on ne compte plus des fichiers, on regarde d'OÙ ils viennent.

CE QUE LA MESURE VOIT, ET CE QU'ELLE NE VOIT PAS. Elle voit l'IMPORT (ou la référence au nom de
fichier pour une brique front) : « la brique est là ». Elle ne dit RIEN de la qualité de
l'intégration — c'est le rôle du critère de grille, qui interroge le registre runtime quand il
existe. Les deux couches sont complémentaires : celle-ci est globale et pas chère, l'autre est
stricte et par app.

⚠ Identifiants passés en ANGLAIS le 2026-09-15 (règle « tout le code en anglais », GO Fabien),
avec le registre lui-même (`Mechanism`, `MECHANISMS`). Le NOM DE FICHIER reste `mecanismes_scan`
— il est cité par chemin dans la doc et ses traces datées, que `check_docs` vérifie.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

#: Dossiers jamais parcourus (code vendored, artefacts, arbre de dépendances). Sans cet élagage
#: le balayage part sur des dizaines de milliers de fichiers — la leçon `/mnt/d` de `check_docs`.
EXCLUDED_DIRS = {
    'venv_win', 'venv_linux', 'node_modules', '.git', 'migrations', 'staticfiles',
    'static', 'media', 'logs', 'AI-models', '__pycache__', 'wama-dev-ai', 'patches',
    'musetalk', 'codeformer',   # vendored upstream
}

#: Racines de NOTRE code — **les TROIS mondes** (`docs/construction/mondes/WAMA_VISION_COMPLET.md §Les quatre mondes`).
#:
#: ⚠ `wama_data` MANQUAIT, et le défaut était SILENCIEUX au pire endroit possible (corrigé le
#: 2026-08-24). Le monde Data est sorti du substrat le 22/08 (`wama/common/data/` → `wama_data/`)
#: et cette liste n'a pas suivi : **57 fichiers étaient invisibles au balayage**. Conséquence, un
#: mécanisme du monde Data ne pouvait avoir QUE zéro consommateur — ses appelants vivent chez lui.
#: `WAMA_MECANISMES.md` affichait donc `temporal_referential`, `data_frames_bridge`, `data_vue` et
#: `data_noms` dans la liste « ⚠ sans consommateur (brique morte ou pas encore adoptée) », alors
#: que `frames.py` consomme le référentiel et que `vue.py` consomme `frames.py`.
#:
#: ⚠⚠ Et c'est le cas le plus coûteux d'instrument faux : il ne se trompait pas au hasard, il
#: accusait **précisément le monde qu'il ne regardait pas**. Un zéro produit par une absence de
#: mesure est indiscernable d'un zéro mesuré — c'est ce qui l'a rendu crédible pendant deux jours.
#: Ajouter un monde à WAMA = ajouter sa racine ici, dans le même commit que le déport.
ROOTS = ('wama', 'wama_lab', 'wama_data')


def python_modules(base: Path):
    """Chemins .py de notre code (relatifs à base), vendored et artefacts élagués."""
    for root in ROOTS:
        start = base / root
        if not start.is_dir():
            continue
        for folder, subdirs, files in os.walk(start):
            subdirs[:] = [d for d in subdirs if d not in EXCLUDED_DIRS]
            for f in files:
                if f.endswith('.py'):
                    yield Path(folder, f).relative_to(base).as_posix()


def front_sources(base: Path):
    """Chemins .html/.js de notre front (templates + static d'app), relatifs à base.

    Corpus des CONSOMMATEURS des briques front : une brique est consommée par la balise
    <script>/l'include qui la référence, pas par un import Python. `staticfiles/` (copies
    collectées) reste élagué — compter une copie mentirait — et `vendors/` (libs tierces)
    aussi ; `static` est réadmis, c'est là que vit le front.
    """
    excluded = (EXCLUDED_DIRS - {'static'}) | {'vendors'}
    for root in ROOTS:
        start = base / root
        if not start.is_dir():
            continue
        for folder, subdirs, files in os.walk(start):
            subdirs[:] = [d for d in subdirs if d not in excluded]
            for f in files:
                if f.endswith(('.html', '.js')):
                    yield Path(folder, f).relative_to(base).as_posix()


def load_sources(base: Path | None = None) -> dict[str, str]:
    """{chemin relatif: contenu} pour tout le corpus balayé. Coûteux : à charger UNE fois."""
    if base is None:
        from django.conf import settings
        base = Path(settings.BASE_DIR)
    sources = {}
    for rel in list(python_modules(base)) + list(front_sources(base)):
        try:
            sources[rel] = (base / rel).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
    return sources


def consumers(mechanism, sources: dict[str, str]) -> list[str]:
    """
    Fichiers qui IMPORTENT le domicile (ou une annexe), hors le mécanisme lui-même.

    Quand `symbol` est renseigné, on compte les importateurs de CE symbole et non du module :
    un mécanisme logé dans un module partagé (`common/models.py`) héritait sinon du compte de
    tous ses importateurs, quelle que soit la raison de leur import.
    """
    # ⚠ PRÉFILTRE PAR SOUS-CHAÎNE (2026-09-14) : chaque motif ci-dessous EXIGE un littéral — le
    # symbole, la feuille du module ou le nom de fichier. Un source qui ne le contient pas ne
    # peut pas correspondre : le tester d'abord (`in`, C) rend EXACTEMENT le même résultat que
    # la regex seule. Mesuré sans lui : 940 284 recherches regex sur le texte entier des 1 069
    # sources, 84 s du fait `mecanismes` de `doc_facts` (et la même matrice rejouée 3 fois).
    own = {mechanism.home, *mechanism.annexes}
    by_symbol = set()
    if mechanism.symbol:
        pattern = re.compile(rf'\b{re.escape(mechanism.symbol)}\b')
        by_symbol = {rel for rel, src in sources.items()
                     if rel not in own and mechanism.symbol in src and pattern.search(src)}
        # Module PYTHON partagé : le symbole REMPLACE l'import du module (la raison d'être
        # du champ — `ScopedVisibility` dans `common/models.py`, 2026-08-13).
        if mechanism.home.endswith('.py'):
            return sorted(by_symbol)
        # Brique FRONT (2026-09-06) : le symbole S'AJOUTE au nom. Une brique chargée par
        # `base.html` s'adopte par son GLOBAL (`WamaFolderImport.collect` — jamais par son
        # fichier, que seul base.html cite : 2 consommateurs comptés pour 9 apps), mais aussi
        # par l'inclusion d'une ANNEXE (`_filter_bar.html`, `_queue_toolbar.html`). Mesuré en
        # posant les symboles : le remplacement faisait tomber la barre de filtrage de 14 à 2
        # et la file de 81 à 2 — vrai d'un côté, faux de l'autre. Les deux sont des adoptions.
    patterns = []
    for path in own:
        if path.endswith('.py'):
            dotted = path[:-3].replace('/', '.')       # wama/common/x.py → wama.common.x
            leaf = path.rsplit('/', 1)[-1][:-3]        # → x
            # Les trois alternatives contiennent `leaf` (`dotted` finit par elle).
            patterns.append((leaf, re.compile(
                rf'(?:from\s+{re.escape(dotted)}\s+import|import\s+{re.escape(dotted)}\b'
                rf'|from\s+[.\w]*\.?{re.escape(leaf)}\s+import)')))
        else:
            # Brique front (.js/.html) : consommée par la référence de son NOM de fichier
            # (balise <script src=…>, {% include %}, {% static %}).
            name = path.rsplit('/', 1)[-1]
            patterns.append((name, re.compile(re.escape(name))))
    return sorted(by_symbol | {rel for rel, src in sources.items()
                               if rel not in own
                               and any(lit in src and p.search(src) for lit, p in patterns)})


@lru_cache(maxsize=1)
def _scored_apps() -> tuple:
    """Apps du catalogue effectivement NOTÉES par la grille (les jumelles sandbox sont hors)."""
    try:
        from wama.common.app_registry import APP_CATALOG
    except Exception:
        return ()
    return tuple(sorted(a for a, spec in APP_CATALOG.items() if not (spec or {}).get('sandbox')))


#: Modules de HARNAIS — ils consomment un mécanisme pour le MESURER, jamais pour s'en servir.
#: ⚠ Ils sont exclus de l'ADOPTION seulement, pas de la colonne « consommateurs » : un test
#: importe réellement le domicile, donc le compte de consommateurs ne mentait pas. Ce qui
#: mentait, c'est la phrase DÉRIVÉE « adoptés par des apps » du contrôle de jonction.
#: Mesuré le 2026-09-08 : un test ajouté à `wama/imager/tests.py` (il appelle `queue_dnd_attrs`
#: pour construire l'URL que le gabarit émet — c'est le bon test) faisait apparaître
#: « `queue_dnd` — adopté par 1 app : imager » dans la liste des trous de grille. Une app ne
#: devient pas adoptante parce qu'on l'a testée. À l'échelle du registre le biais portait sur
#: **83 mécanismes** et **328** fichiers de test comptés (queue_order 44, gateway_identity 43,
#: queue_entry 40) — donc autant de lignes d'adoption gonflées.
#: Même règle, même raison que `conformity_checker._AppFiles.code_paths()`, qui écarte déjà
#: `tests*`/`nightly_*` : *une preuve qui pointe un test dit qu'on a regardé au mauvais endroit.*
HARNESS_PREFIXES = ('tests', 'test_', 'nightly_')


def _is_harness(rel: str) -> bool:
    return Path(rel).name.startswith(HARNESS_PREFIXES)


def consuming_apps(mechanism, sources: dict[str, str], found=None) -> list[str]:
    """Apps du catalogue dont au moins un fichier NON-HARNAIS consomme le mécanisme.

    Cf. `HARNESS_PREFIXES` : mesurer un mécanisme n'est pas l'adopter.
    """
    found = consumers(mechanism, sources) if found is None else found
    useful = [rel for rel in found if not _is_harness(rel)]
    return [a for a in _scored_apps()
            if any(rel.startswith(f'wama/{a}/') for rel in useful)]


def adoption_matrix(sources: dict[str, str] | None = None) -> dict:
    """
    Mesure complète, UNE passe : {key: {'consommateurs': [...], 'apps': [...], 'niveau_app': bool}}.

    C'est la matière commune du rendu de la carte, du contrôle de jonction et (à venir) de la
    page développeur : une seule définition de l'adoption, pas trois. ⚠ Les CLÉS du dict
    rendu restent en français : c'est une donnée lue par ses consommateurs, pas un identifiant.
    """
    from wama.common.mecanismes import MECHANISMS

    sources = load_sources() if sources is None else sources
    measure = {}
    for m in MECHANISMS:
        found = consumers(m, sources)
        apps = consuming_apps(m, sources, found)
        measure[m.key] = {'consommateurs': found, 'apps': apps, 'niveau_app': bool(apps)}
    return measure


def mechanisms_without_criterion(sources: dict[str, str] | None = None) -> list[tuple]:
    """
    LE contrôle de jonction : mécanismes de NIVEAU APP qu'AUCUN critère de grille ne vérifie.

    Retourne [(mechanism, apps_qui_l_adoptent)] trié par adoption décroissante — les plus
    répandus d'abord, ce sont les trous les plus coûteux. Une brique adoptée par 10 apps et
    vérifiée nulle part est exactement le cas qui a laissé `card_gear` diverger sans signal.
    """
    from wama.common.mecanismes import MECHANISMS
    from wama.common.services.conformity_checker import CRITERIA

    covered = {c.mechanism for c in CRITERIA if getattr(c, 'mechanism', '')}
    measure = adoption_matrix(sources)
    gaps = [(m, measure[m.key]['apps']) for m in MECHANISMS
            if measure[m.key]['niveau_app'] and m.key not in covered]
    return sorted(gaps, key=lambda t: (-len(t[1]), t[0].key))


def orphan_criteria() -> list[str]:
    """
    Garde-fou SYMÉTRIQUE : critère dont le `mechanism=` ne correspond à aucune clé du registre.

    Sans lui, une faute de frappe dans la liaison la rendrait silencieusement inerte — le
    critère se croirait rattaché et le contrôle ci-dessus continuerait de signaler le trou.
    """
    from wama.common.mecanismes import by_key
    from wama.common.services.conformity_checker import CRITERIA

    known = by_key()
    return sorted({c.mechanism for c in CRITERIA
                   if getattr(c, 'mechanism', '') and c.mechanism not in known})
