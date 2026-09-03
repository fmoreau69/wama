"""Garde du ROUTAGE des caches HuggingFace (ROADMAP §5b).

CE QUE CE CONTRÔLE PROTÈGE. Poser `os.environ['HF_HUB_CACHE'] = <dossier du modèle>` avant
un import HF est une règle TRANSITOIRE (`CLAUDE.md`, qui le dit lui-même) : la variable est
**globale au processus**, donc elle emporte dans le dossier du modèle principal tout ce que
la lib télécharge ensuite — sous-dépendances comprises. Le dépôt en porte déjà trois traces :

  - `wama/views.py:223` — « le **dump de modèles dans speech/kokoro** (`HF_HUB_CACHE` global
    muté en concurrence) », qui a coûté le retrait du préchargement Kokoro côté Django ;
  - `start_wama_prod.sh:271` — `--workers 1` du service TTS déclaré **STRUCTURANT**, pas un
    réglage de performance, à cause de cette même course ;
  - `model_manager/management/commands/dedup_models.py:3` — une commande entière écrite comme
    « séquelle de la course `os.environ['HF_HUB_CACHE']` qui a déversé… ».

Et une quatrième, MESURÉE le 2026-09-03 : `models--timm--resnet18.a1_in1k`, backbone timm du
DETR Table Transformer, s'est retrouvé DANS le dossier de table-transformer (et aussi dans le
cache partagé, sa place légitime) — d'où une ligne de catalogue fantôme pour une simple
sous-dépendance, sans tâche ni licence.

LA CIBLE (`ROADMAP §5b`, design validé le 2026-06-17) : `cache_dir=` explicite pour les
modèles PRINCIPAUX (la catégorisation est préservée, et c'est thread-safe), `HF_HOME` posé
**une seule fois au démarrage** pour les sous-dépendances partagées — ce qui est déjà le cas
(`settings.py:165-167`, en `setdefault`, et rien dans `.env` ni `start_wama_prod.sh` ne le
neutralise : vérifié).

CE QUE CE TEST FAIT — et surtout ce qu'il NE fait PAS. Il compte les sites de mutation
per-modèle restants et refuse qu'ils AUGMENTENT. Il ne prétend pas qu'ils sont tous
retirables : chacun se lit, et certains backends dépendent peut-être de la variable parce que
leur lib n'accepte pas `cache_dir=`. Le budget ne peut que DESCENDRE — un budget qui monte
tout seul cesse de protéger (leçon `CIBLES_ASSUMEES`, `/reprise`).

⚠ `settings.py` emploie `setdefault`, pas une affectation : il est hors périmètre PAR
CONSTRUCTION (on ne détecte que `os.environ[...] = ...`), et c'est voulu — c'est le socle.
"""

import ast
import re
import unittest
from functools import lru_cache
from pathlib import Path

#: Variables dont la mutation per-modèle est le défaut visé.
VARS_HF = {'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE', 'HF_HOME'}

#: Sites de mutation MESURÉS le 2026-09-03 après le retrait du 1er (table_transformer).
#: NE JAMAIS RELEVER CE NOMBRE. Le faire descendre = porter un backend au §5b ; le voir
#: monter = une nouvelle mutation a été introduite, et c'est ce que ce test refuse.
BUDGET_MUTATIONS = 37

#: Bacs à sable : copies GÉNÉRÉES d'une app source. Une mutation y est le reflet de la
#: source, pas une décision — la compter deux fois ferait bouger le budget à chaque
#: régénération, sans qu'aucune dette réelle n'ait changé.
_SANDBOX = re.compile(r'_\d\d(/|$)')
_HORS_PERIMETRE = ('site-packages', 'staticfiles', '/archive/', 'musetalk',
                   '/migrations/', 'node_modules')

#: Racines de CODE WAMA balayées. Explicites, et non un `rglob` depuis la racine du dépôt :
#: celui-ci descend dans `venv_win`/`venv_linux`, soit **97 000 des 113 000 fichiers .py**
#: mesurés le 2026-09-03 — 18 s de balayage pour un filtrage APRÈS coup. On élague pendant
#: la descente, jamais après.
_RACINES_CODE = ('wama', 'wama_lab', 'wama_data', 'scripts')

#: Dossiers dans lesquels on ne descend jamais (élagage `os.walk`).
_DOSSIERS_ELAGUES = {'__pycache__', 'node_modules', 'site-packages', 'staticfiles',
                     'archive', 'migrations', '.git'}


def _racine() -> Path:
    import wama
    return Path(wama.__file__).resolve().parent.parent


def _mutation(node):
    """Nom de la variable si `node` est `os.environ['HF_*'] = …`, sinon None."""
    if not isinstance(node, ast.Assign):
        return None
    for cible in node.targets:
        if (isinstance(cible, ast.Subscript)
                and isinstance(cible.value, ast.Attribute)
                and cible.value.attr == 'environ'
                and isinstance(cible.slice, ast.Constant)
                and cible.slice.value in VARS_HF):
            return cible.slice.value
    return None


@lru_cache(maxsize=1)
def sites_de_mutation():
    """[(chemin relatif, ligne, variable)] — par AST, jamais par grep.

    Par AST parce qu'un grep compterait les mentions en COMMENTAIRE (il y en a : la règle
    `CLAUDE.md` est citée dans plusieurs docstrings, et ce fichier-ci en est plein).

    ⚠ MÉMOÏSÉ : le balayage lit tout l'arbre, et `/mnt/d` depuis WSL2 est lent (le skill
    `/reprise` fait la même remarque pour `check_docs`, qu'il fait lancer depuis Windows).
    Sans le cache, les 3 tests de ce module parcouraient le dépôt 3 fois.
    """
    import os

    racine = _racine()
    trouves = []
    for nom in _RACINES_CODE:
        depart = racine / nom
        if not depart.is_dir():
            continue
        for dossier, sous_dossiers, fichiers in os.walk(depart):
            sous_dossiers[:] = [d for d in sous_dossiers
                                if d not in _DOSSIERS_ELAGUES and not d.startswith('venv')]
            for f in sorted(fichiers):
                if not f.endswith('.py'):
                    continue
                chemin = Path(dossier) / f
                rel = chemin.relative_to(racine).as_posix()
                if any(p in rel for p in _HORS_PERIMETRE) or _SANDBOX.search(rel):
                    continue
                try:
                    arbre = ast.parse(chemin.read_text(encoding='utf-8'))
                except (OSError, SyntaxError, ValueError):
                    continue
                for node in ast.walk(arbre):
                    var = _mutation(node)
                    if var:
                        trouves.append((rel, node.lineno, var))
    return tuple(sorted(trouves))  # immuable : le résultat est mémoïsé et partagé


class RoutageCacheHFTest(unittest.TestCase):

    def test_aucune_nouvelle_mutation_per_modele_de_cache_HF(self):
        """Le budget ne peut que DESCENDRE. Une mutation de plus = un dossier de modèle qui
        se remettra à collecter les sous-dépendances des autres."""
        sites = sites_de_mutation()
        if len(sites) <= BUDGET_MUTATIONS:
            return
        nouveaux = '\n'.join(f"    {f}:{l}  {v}" for f, l, v in sites)
        self.fail(
            f"{len(sites)} mutations per-modèle de cache HF pour un budget de "
            f"{BUDGET_MUTATIONS} — une au moins a été AJOUTÉE.\n"
            f"Cible : `cache_dir=` explicite + `HF_HOME` posé une fois au démarrage "
            f"(ROADMAP §5b ; `settings.py:165`).\n"
            f"Sites actuels :\n{nouveaux}")

    def test_le_budget_est_a_jour_quand_la_dette_a_baisse(self):
        """Miroir du précédent : quand un backend est porté, le budget DOIT suivre, sinon
        il cesse de protéger (un seuil trop large laisse passer la régression suivante).
        C'est le défaut exact que `/reprise` documente sur ses attendus périmés."""
        sites = sites_de_mutation()
        self.assertGreaterEqual(
            len(sites), BUDGET_MUTATIONS,
            f"La dette est descendue à {len(sites)} : mettre BUDGET_MUTATIONS à cette "
            f"valeur dans le MÊME commit que le portage.")

    def test_le_socle_pose_bien_les_caches_au_demarrage(self):
        """Retirer une mutation per-modèle n'est sûr que si le socle existe. On vérifie le
        FAIT (les variables sont posées au chargement des settings), pas la ligne de code."""
        import os
        from django.conf import settings
        attendu = str(settings.MODEL_PATHS['cache']['huggingface'])
        for var in ('HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE'):
            self.assertEqual(
                os.environ.get(var), attendu,
                f"{var} n'est pas posée sur le cache partagé : sans ce socle, retirer une "
                f"mutation per-modèle enverrait les poids dans le cache par défaut de HF "
                f"(hors AI-models/).")
