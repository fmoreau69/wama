"""
Registre DÉCLARATIF des modules de WAMA Data — et la MESURE de leur avancement.

POURQUOI CE FICHIER EXISTE (2026-08-22, recadrage Fabien)
    J'ai proposé un plan d'implémentation sans inventaire de l'existant : j'ai voulu « décider la
    forme » du manifeste `dataset` qui existe déjà, découvert `functions/io/rtmaps_rec.py` par
    hasard, et proposé de construire un Segmenter dont l'équivalent est écrit depuis des années
    ailleurs. La cause n'est pas l'inattention : c'est qu'**il n'existait aucun état lisible**.

    `PROJECT_STATUS §39` en est la démonstration. Écrit le 2026-07-22, il annonce « 10 DataType »
    et « 19 fonctions au catalogue ». Le réel : 11 et 31, plus deux briques entières qu'il ignore.
    Personne ne l'a mis à jour — un état écrit à la main DÉRIVE, toujours. Ajouter un quatrième
    `.md` de statut aurait reproduit exactement le même défaut.

    D'où le choix : **on ne déclare pas l'avancement, on le MESURE**. Ce registre déclare seulement
    ce qu'un module EST CENSÉ contenir ; l'état est calculé depuis le code réel et rendu dans
    `WAMA_DATA_WORLD.md §0` par `doc_facts`. Même geste que `mecanismes.py` → `WAMA_MECANISMES.md` :
    la source est le code, le document n'est qu'un rendu, donc incapable de mentir.

CE QU'ON DÉCLARE ICI
    L'INTENTION d'un module : ce qu'il fait, quelles briques il doit posséder, quelles fonctions il
    doit exposer au catalogue. Jamais son état — c'est précisément ce qu'on refuse d'écrire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ModuleData:
    """Un module du monde DATA : ce qu'il fait, et ce qu'il DEVRA contenir."""

    cle: str
    nom: str
    #: Une ligne. Ce que le module fait, pas comment.
    role: str
    #: Ce qu'il consomme → ce qu'il produit, en vocabulaire de `data_types`.
    flux: str
    #: Briques attendues (chemins relatifs à BASE_DIR). Vide = rien n'est encore spécifié.
    briques: Tuple[str, ...] = ()
    #: Clés attendues au `FUNCTION_CATALOG`.
    fonctions: Tuple[str, ...] = ()
    #: Section de `WAMA_DATA_WORLD.md` portant l'intention.
    doc: str = ''
    #: Ce qui bloque, en une ligne. Rendu tel quel — un blocage tu se paie plus tard.
    bloque_par: str = ''


#: ⚠ ORDRE = celui de la chaîne d'exploitation, pas l'ordre alphabétique : c'est ainsi qu'on lit
#: un avancement (où s'arrête-t-on ?), et le rendu le conserve.
MODULES: Tuple[ModuleData, ...] = (
    ModuleData(
        'importer', 'Importer', "Lit une source et rend un référentiel temporel interrogeable",
        "fichiers + manifeste `dataset` → référentiel",
        briques=('wama_data/sources/__init__.py',
                 'wama_data/sources/trip.py',
                 'wama_data/sources/tabular.py'),
        doc='§6.6, §9bis.1',
        bloque_par="alignement par TRIGGERS non conçu (D12) ; `DATASET_SOURCES` non réconcilié "
                   "avec le registre des lecteurs (G1) ; lecteur `.rec` encore une FONCTION "
                   "(`functions/io/rtmaps_rec.py`) au lieu d'un lecteur de source",
    ),
    ModuleData(
        'referentiel', 'Référentiel temporel', "Aligne des flux à cadences incommensurables",
        "référentiel → échantillons, `segments`, vue décimée",
        briques=('wama_data/core/temporal.py',),
        doc='§2, §3',
        bloque_par="AUCUN consommateur — la brique est inerte tant qu'un module ne s'en sert pas",
    ),
    ModuleData(
        'connector', 'Connector', "Branche une base existante comme source",
        "base SQLite → référentiel",
        briques=('wama_data/sources/trip.py',),
        doc='§6.2',
    ),
    ModuleData(
        'explorer', 'Explorer', "Explore un dataset en table et en graphe",
        "référentiel → vues",
        doc='§7',
    ),
    ModuleData(
        'segmenter', 'Segmenter', "Produit des segments : autour d'un événement, par jonction de "
                                  "deux flux, par prédicat avec hystérésis, par plages constantes "
                                  "d'un catégoriel, ou par CODAGE (humain ou IA)",
        "`events` ou signal + prédicat → `segments`",
        briques=('wama_data/core/segmentation.py',
                 'wama_data/core/coding.py',
                 'wama_data/functions/temporal/segmentation.py',
                 'wama_data/functions/temporal/coding.py'),
        fonctions=('segment_autour_event', 'segment_jonction', 'segment_conditionnel',
                   'segment_etats', 'segment_present_dans',
                   'codage_segments', 'codage_evenements', 'codage_accord'),
        doc='§9ter (spécification), §6.7',
        bloque_par="MOTEUR complet (5 modes) — reste l'INTERFACE de codage, qui doit se GÉNÉRER "
                   "du protocole et non s'écrire : elle dépend du transport (Magneto + vue média) "
                   "et de la vue déclarative, donc du Visualizer",
    ),
    ModuleData(
        'calculator', 'Calculator',
        # ⚠ La déclaration ne portait QUE le second mode. Précision de Fabien (2026-08-22) :
        # le Calculator en a DEUX, et le premier n'est pas un cas particulier du second — il ne
        # change pas la granularité (une ligne par échantillon reste une ligne par échantillon),
        # là où l'agrégation par segment la change. D'où deux catégories de catalogue distinctes,
        # `enricher` et `aggregate`, et non une famille unique.
        "Calcule des COLONNES DÉRIVÉES (moyenne glissante, dérivée, cumul) et des INDICATEURS "
        "PAR SEGMENT qu'il adjoint aux segments",
        "signal → signal enrichi · `segments` + signal → colonnes d'indicateurs",
        briques=('wama_data/core/calculation.py',
                 'wama_data/core/valeurs.py',
                 'wama_data/functions/temporal/calculation.py'),
        fonctions=('calcul_glissant', 'calcul_derivee', 'calcul_cumul', 'calcul_par_segment'),
        doc='§6.7',
        bloque_par="MOTEUR écrit et éprouvé (49 tests — 32 sur le cœur pur, 17 sur la frontière "
                   "pandas) : reste son emploi sur un corpus RÉEL, qui dépend de l'Importer — "
                   "sans flux aligné, il n'y a rien à calculer",
    ),
    ModuleData(
        'visualizer', 'Visualizer', "Vues synchronisées sur l'axe partagé (plugins)",
        "référentiel → plugins co-chargés",
        doc='§4, §8.2',
        bloque_par="vue déclarative = verrou §7ter point 3 ; écrire 2-3 plugins AVANT d'extraire",
    ),
    ModuleData(
        'exporter', 'Exporter',
        # ⚠ « pivot long → large » a été RETIRÉ le 2026-08-23 : c'était faux (§6.7, corrigé).
        # Une table de situations est déjà `occurrences × indicateurs` ; l'export n'oriente rien,
        # il SÉLECTIONNE des colonnes, les ordonne, et concatène. Le portage schéma-driven est
        # spécifié en §9ter.6 — une DÉCLARATION d'export (donc un manifeste), deux axes de
        # regroupement au lieu de quatre branches, et l'interface générée du schéma.
        "Sélection ordonnée de colonnes + identité + contexte, écrite en fichiers exploitables "
        "hors WAMA",
        "`segments`/`events`/données + sélection → fichiers (concaténation, jamais pivot)",
        doc='§9ter.5, §9ter.6',
        bloque_par="À ÉCRIRE sur le modèle réel (§9ter.6) — un premier jet fondé sur un pivot "
                   "inexistant a été reverté (ef756b63). Dépend du Segmenter : la chaîne "
                   "conditionnelle décide de ce qu'il y aura à exporter",
    ),
    ModuleData(
        'recorder', 'Recorder', "Enregistre depuis une source temps réel",
        "flux LSL/RTMaps/ROS → `dataset`",
        doc='§7',
        bloque_par="périmètre v1 non tranché (D5)",
    ),
    ModuleData(
        'analyzer', 'Analyzer', "Orchestre les modules selon un manifeste `pipeline`",
        "manifeste `pipeline` → exécution",
        doc='§9bis.2',
        bloque_par="nœud FONCTION absent du kind `pipeline` (D13)",
    ),
)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# MESURE — rien ici ne déclare un état ; tout est lu dans le code
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _racine() -> Path:
    from django.conf import settings
    return Path(settings.BASE_DIR)


def _catalogue() -> set:
    try:
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG
        return set(FUNCTION_CATALOG)
    except Exception:
        return set()


def _consommateurs(brique: str) -> Tuple[int, int]:
    """(consommateurs INTERNES à WAMA Data, consommateurs EXTERNES), hors tests et registres.

    ⚠ La distinction est le cœur de la mesure. Un module consommé uniquement PAR WAMA DATA
    lui-même reste inerte du point de vue du produit : le sous-système peut être parfaitement
    cohérent et ne servir à personne. C'est exactement l'état du référentiel temporel — utilisé
    par les lecteurs de sources, donc « consommé », mais aucune app, aucune tâche, aucun endpoint
    ne s'en sert. Ne compter qu'un total aurait affiché ✅ sur un sous-système sans usage.
    """
    import subprocess
    feuille = Path(brique).stem
    if feuille == '__init__':
        feuille = Path(brique).parent.name
    try:
        out = subprocess.run(
            ['git', 'grep', '-l', '-E', rf'from\s+\.{{0,3}}{feuille}\s+import|import\s+{feuille}\b',
             '--', '*.py'],
            cwd=str(_racine()), capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return 0, 0
    interne = externe = 0
    for f in out.splitlines():
        f = f.strip()
        if not f or f == brique:
            continue
        nom = Path(f).name
        if 'test' in nom or nom in ('mecanismes.py', 'modules.py'):
            continue
        if f.startswith('wama_data/'):
            interne += 1
        else:
            externe += 1
    return interne, externe


def mesurer() -> List[dict]:
    """État RÉEL de chaque module, calculé depuis le code. Aucune valeur écrite à la main."""
    racine, catalogue = _racine(), _catalogue()
    out: List[dict] = []
    for m in MODULES:
        presentes = [b for b in m.briques if (racine / b).exists()]
        fonctions = [f for f in m.fonctions if f in catalogue]
        paires = [_consommateurs(b) for b in presentes]
        interne = sum(p[0] for p in paires)
        externe = sum(p[1] for p in paires)

        # Un test « couvre » une brique s'il en porte le nom (convention du dépôt : `tests_<sujet>`).
        # ⚠ On construit les chemins CANDIDATS au lieu de balayer l'arborescence : un
        # `racine.glob('**/tests_*.py')` traverse `venv_linux`, `venv_win` et `AI-models` — mesuré,
        # la commande ne rendait plus la main. Même classe de défaut que l'agrégation par OFFSET
        # corrigée le 21/08 : une opération qui paraît anodine et qui parcourt tout.
        testees = []
        for b in presentes:
            chemin = racine / b
            sujet = chemin.stem if chemin.stem != '__init__' else chemin.parent.name
            dossiers = {chemin.parent, chemin.parent.parent}
            if any((d / f'{prefixe}_{sujet}.py').exists()
                   for d in dossiers for prefixe in ('tests', 'test')):
                testees.append(b)

        if not m.briques:
            etat = '⏳'          # rien de spécifié : le module n'est pas commencé
        elif len(presentes) < len(m.briques):
            etat = '🔄'
        elif not externe:
            # Livré, éventuellement consommé DANS WAMA Data, mais personne au-dehors ne s'en
            # sert : le sous-système est cohérent et sans usage. C'est un état à part entière.
            etat = '🔶'
        else:
            etat = '✅'
        out.append({
            'cle': m.cle, 'nom': m.nom, 'role': m.role, 'flux': m.flux, 'doc': m.doc,
            'etat': etat, 'briques': (len(presentes), len(m.briques)),
            'testees': len(testees), 'fonctions': (len(fonctions), len(m.fonctions)),
            'interne': interne, 'externe': externe, 'bloque_par': m.bloque_par,
        })
    return out
