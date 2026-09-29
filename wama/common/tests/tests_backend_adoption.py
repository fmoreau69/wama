"""ADOPTION de la résolution par déclaration — le côté APP du lien modèle↔backend.

`tests_backend_inventory.py` tient la RÉSOLUTION (le vivier, `backend_for_model`). Ce fichier
tient ce que les apps en FONT : la ROUTE §10.3 dit qu'elles « demandent un backend pour leur
MODÈLE, plus jamais un module par son chemin ». Le 2026-09-07, `backend_for_model()` existait,
était mesuré (97 modèles résolus) — et n'avait AUCUN adoptant dans le code des apps. Pire : le
déplacement des backends vers le substrat avait été fait en RÉÉCRIVANT les imports de chemin,
c'est-à-dire en reconduisant précisément le motif interdit, sur 20 sites, suite verte.

Une règle de doc ne l'a pas empêché ; ce budget le peut. Même forme que `tests_hf_cache_routing`
(BUDGET_MUTATIONS) : le nombre de sites où une app importe une CLASSE de backend par son chemin
est MESURÉ, et il ne peut que DESCENDRE. Adopter `backend_for_key` = faire baisser le budget dans
le même commit ; le voir monter = un import par chemin vient d'être réintroduit.

Ce qui N'EST PAS compté (ce n'est pas le lien modèle→backend) :
  • les fonctions utilitaires d'un module de backend (`upscale_image_file`,
    `run_audio_enhancement`) et ses données (`MODELS_INFO`) — une autre couche, un autre chantier ;
  • les tests, les scénarios nocturnes et les bacs à sable — copies ou harnais, pas des décisions ;
  • le substrat lui-même (`wama/common`) et les paquets `backends/` : c'est là que vivent les
    classes, ils ont le droit de se nommer.
"""
import ast
import os
import re
from pathlib import Path

from django.test import TestCase

from wama.common.services import backend_inventory as bi

#: **0 depuis le 2026-09-07 (nuit)** — le budget est SOLDÉ, la garde est désormais ABSOLUE.
#: Trajet mesuré dans la journée : 22 (premiers adoptants composer/enhancer) → 18 (reader,
#: imager image) → 0 (imager vidéo ×5 — la classe de PARAMÈTRES est DÉCLARÉE par le backend,
#: `PARAMS` ; model_registry ×8 — la découverte résout par le moteur que la déclaration d'app
#: porte déjà ; avatarizer ×2 — résolution paresseuse ; anonymizer SAM3 ; DeepFilterNet du
#: préprocesseur ; défauts de l'imager lus sur la déclaration du modèle).
#: ⚠ Sur les 18 derniers, 2 étaient du CODE MORT EN PARALLÈLE (branches Wan et HunyuanVideo :
#: plus aucune surface ne les offrait, poids partis depuis janvier) — un budget compte des
#: lignes, pas des chemins vivants ; le test de vie se fait à part.
#: NE JAMAIS RELEVER CE NOMBRE.
BUDGET_IMPORTS_PAR_CHEMIN = 0

_RACINES_CODE = ('wama', 'wama_lab')
_DOSSIERS_ELAGUES = {'__pycache__', 'node_modules', 'site-packages', 'staticfiles',
                     'archive', 'migrations', '.git', 'backends', 'common'}
_SANDBOX = re.compile(r'_\d\d(/|$)')
_MODULE_BACKEND = re.compile(r'^(wama|wama_lab)\.[a-z0-9_]+\.backends(\.|$)')


def _racine() -> Path:
    import wama
    return Path(wama.__file__).resolve().parent.parent


def _classes_de_backend() -> set:
    """Noms des classes inventoriées (kind 'classe') — la cible du lien, pas les fonctions."""
    return {e.name for a in bi.inventory() for e in a.entries if e.kind == 'classe'}


def _module_vise_un_backend(node, niveau_relatif: bool) -> bool:
    module = getattr(node, 'module', None) or ''
    if niveau_relatif:                       # `from .backends…` / `from ..backends…`
        return module == 'backends' or module.startswith('backends.')
    return bool(_MODULE_BACKEND.match(module))


def sites_import_par_chemin():
    """[(chemin relatif, ligne, nom importé)] — par AST, jamais par grep (les docstrings
    de ce dépôt citent le motif interdit pour l'expliquer)."""
    classes = _classes_de_backend()
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
                if not f.endswith('.py') or f.startswith('tests') or f == 'nightly_scenarios.py':
                    continue
                chemin = Path(dossier) / f
                rel = chemin.relative_to(racine).as_posix()
                if _SANDBOX.search(rel):
                    continue
                try:
                    arbre = ast.parse(chemin.read_text(encoding='utf-8'))
                except (OSError, SyntaxError, ValueError):
                    continue
                for node in ast.walk(arbre):
                    if not isinstance(node, ast.ImportFrom):
                        continue
                    if not _module_vise_un_backend(node, niveau_relatif=bool(node.level)):
                        continue
                    for alias in node.names:
                        if alias.name in classes:
                            trouves.append((rel, node.lineno, alias.name))
    return sorted(trouves)


class AdoptionParLesAppsTest(TestCase):

    def test_aucune_app_n_importe_une_classe_de_backend_par_son_chemin_de_plus(self):
        """Le budget ne peut que DESCENDRE."""
        sites = sites_import_par_chemin()
        if len(sites) <= BUDGET_IMPORTS_PAR_CHEMIN:
            return
        liste = '\n'.join(f'    {f}:{l}  {n}' for f, l, n in sites)
        self.fail(
            f"{len(sites)} import(s) de classe de backend par chemin pour un budget de "
            f"{BUDGET_IMPORTS_PAR_CHEMIN} — un au moins a été AJOUTÉ.\n"
            f"Le MODÈLE porte son moteur ; l'app demande `backend_for_key('<app>:<id>')` "
            f"(common/backends/manager.py) et n'importe aucun module par son chemin (ROUTE §10.3).\n"
            f"Sites actuels :\n{liste}")

    def test_le_budget_est_a_jour_quand_une_app_a_adopte(self):
        """Miroir : un budget trop large ne protège plus (leçon des attendus périmés de /reprise)."""
        sites = sites_import_par_chemin()
        self.assertGreaterEqual(
            len(sites), BUDGET_IMPORTS_PAR_CHEMIN,
            f"Il reste {len(sites)} site(s) : mettre BUDGET_IMPORTS_PAR_CHEMIN à cette valeur "
            f"dans le MÊME commit que l'adoption.")

    def test_les_adoptants_n_ont_plus_aucun_import_par_chemin(self):
        """Preuve POSITIVE de l'adoption — le budget seul ne dit pas QUI a adopté.

        Depuis le 2026-09-07 (budget 0) : TOUTES les apps des deux mondes. Le test nomme le
        site fautif, là où le budget ne donnerait qu'un compte."""
        adoptants = ('wama/', 'wama_lab/')
        restes = [s for s in sites_import_par_chemin() if s[0].startswith(adoptants)]
        self.assertEqual(restes, [], f'une app importe encore une classe de backend par chemin : {restes}')
