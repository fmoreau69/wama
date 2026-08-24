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
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

#: Dossiers jamais parcourus (code vendored, artefacts, arbre de dépendances). Sans cet élagage
#: le balayage part sur des dizaines de milliers de fichiers — la leçon `/mnt/d` de `check_docs`.
DOSSIERS_EXCLUS = {
    'venv_win', 'venv_linux', 'node_modules', '.git', 'migrations', 'staticfiles',
    'static', 'media', 'logs', 'AI-models', '__pycache__', 'wama-dev-ai', 'patches',
    'musetalk', 'codeformer',   # vendored upstream
}

#: Racines de NOTRE code — **les TROIS mondes** (`docs/VISION_STATUS.md §Architecture en MONDES`).
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
RACINES = ('wama', 'wama_lab', 'wama_data')


def modules_python(base: Path):
    """Chemins .py de notre code (relatifs à base), vendored et artefacts élagués."""
    for racine in RACINES:
        depart = base / racine
        if not depart.is_dir():
            continue
        for dossier, sous, fichiers in os.walk(depart):
            sous[:] = [d for d in sous if d not in DOSSIERS_EXCLUS]
            for f in fichiers:
                if f.endswith('.py'):
                    yield Path(dossier, f).relative_to(base).as_posix()


def sources_front(base: Path):
    """Chemins .html/.js de notre front (templates + static d'app), relatifs à base.

    Corpus des CONSOMMATEURS des briques front : une brique est consommée par la balise
    <script>/l'include qui la référence, pas par un import Python. `staticfiles/` (copies
    collectées) reste élagué — compter une copie mentirait — et `vendors/` (libs tierces)
    aussi ; `static` est réadmis, c'est là que vit le front.
    """
    exclus = (DOSSIERS_EXCLUS - {'static'}) | {'vendors'}
    for racine in RACINES:
        depart = base / racine
        if not depart.is_dir():
            continue
        for dossier, sous, fichiers in os.walk(depart):
            sous[:] = [d for d in sous if d not in exclus]
            for f in fichiers:
                if f.endswith(('.html', '.js')):
                    yield Path(dossier, f).relative_to(base).as_posix()


def charger_sources(base: Path | None = None) -> dict[str, str]:
    """{chemin relatif: contenu} pour tout le corpus balayé. Coûteux : à charger UNE fois."""
    if base is None:
        from django.conf import settings
        base = Path(settings.BASE_DIR)
    sources = {}
    for rel in list(modules_python(base)) + list(sources_front(base)):
        try:
            sources[rel] = (base / rel).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
    return sources


def consommateurs(mecanisme, sources: dict[str, str]) -> list[str]:
    """
    Fichiers qui IMPORTENT le domicile (ou une annexe), hors le mécanisme lui-même.

    Quand `symbole` est renseigné, on compte les importateurs de CE symbole et non du module :
    un mécanisme logé dans un module partagé (`common/models.py`) héritait sinon du compte de
    tous ses importateurs, quelle que soit la raison de leur import.
    """
    siens = {mecanisme.domicile, *mecanisme.annexes}
    if mecanisme.symbole:
        motif = re.compile(rf'\b{re.escape(mecanisme.symbole)}\b')
        return sorted({rel for rel, src in sources.items()
                       if rel not in siens and motif.search(src)})
    motifs = []
    for chemin in siens:
        if chemin.endswith('.py'):
            pointe = chemin[:-3].replace('/', '.')      # wama/common/x.py → wama.common.x
            feuille = chemin.rsplit('/', 1)[-1][:-3]     # → x
            motifs.append(re.compile(
                rf'(?:from\s+{re.escape(pointe)}\s+import|import\s+{re.escape(pointe)}\b'
                rf'|from\s+[.\w]*\.?{re.escape(feuille)}\s+import)'))
        else:
            # Brique front (.js/.html) : consommée par la référence de son NOM de fichier
            # (balise <script src=…>, {% include %}, {% static %}).
            motifs.append(re.compile(re.escape(chemin.rsplit('/', 1)[-1])))
    return sorted({rel for rel, src in sources.items()
                   if rel not in siens and any(m.search(src) for m in motifs)})


@lru_cache(maxsize=1)
def _apps_notees() -> tuple:
    """Apps du catalogue effectivement NOTÉES par la grille (les jumelles sandbox sont hors)."""
    try:
        from wama.common.app_registry import APP_CATALOG
    except Exception:
        return ()
    return tuple(sorted(a for a, spec in APP_CATALOG.items() if not (spec or {}).get('sandbox')))


def apps_consommatrices(mecanisme, sources: dict[str, str], consos=None) -> list[str]:
    """Apps du catalogue dont au moins un fichier consomme le mécanisme."""
    consos = consommateurs(mecanisme, sources) if consos is None else consos
    return [a for a in _apps_notees()
            if any(rel.startswith(f'wama/{a}/') for rel in consos)]


def matrice_adoption(sources: dict[str, str] | None = None) -> dict:
    """
    Mesure complète, UNE passe : {cle: {'consommateurs': [...], 'apps': [...], 'niveau_app': bool}}.

    C'est la matière commune du rendu de la carte, du contrôle de jonction et (à venir) de la
    page développeur : une seule définition de l'adoption, pas trois.
    """
    from wama.common.mecanismes import MECANISMES

    sources = charger_sources() if sources is None else sources
    mesure = {}
    for m in MECANISMES:
        consos = consommateurs(m, sources)
        apps = apps_consommatrices(m, sources, consos)
        mesure[m.cle] = {'consommateurs': consos, 'apps': apps, 'niveau_app': bool(apps)}
    return mesure


def mecanismes_sans_critere(sources: dict[str, str] | None = None) -> list[tuple]:
    """
    LE contrôle de jonction : mécanismes de NIVEAU APP qu'AUCUN critère de grille ne vérifie.

    Retourne [(mecanisme, apps_qui_l_adoptent)] trié par adoption décroissante — les plus
    répandus d'abord, ce sont les trous les plus coûteux. Une brique adoptée par 10 apps et
    vérifiée nulle part est exactement le cas qui a laissé `card_gear` diverger sans signal.
    """
    from wama.common.mecanismes import MECANISMES, par_cle
    from wama.common.services.conformity_checker import CRITERIA

    couverts = {c.mecanisme for c in CRITERIA if getattr(c, 'mecanisme', '')}
    mesure = matrice_adoption(sources)
    trous = [(m, mesure[m.cle]['apps']) for m in MECANISMES
             if mesure[m.cle]['niveau_app'] and m.cle not in couverts]
    return sorted(trous, key=lambda t: (-len(t[1]), t[0].cle))


def criteres_orphelins() -> list[str]:
    """
    Garde-fou SYMÉTRIQUE : critère dont le `mecanisme=` ne correspond à aucune clé du registre.

    Sans lui, une faute de frappe dans la liaison la rendrait silencieusement inerte — le
    critère se croirait rattaché et le contrôle ci-dessus continuerait de signaler le trou.
    """
    from wama.common.mecanismes import par_cle
    from wama.common.services.conformity_checker import CRITERIA

    connues = par_cle()
    return sorted({c.mecanisme for c in CRITERIA
                   if getattr(c, 'mecanisme', '') and c.mecanisme not in connues})
