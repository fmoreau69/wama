# -*- coding: utf-8 -*-
"""
Confronte la LANGUE des identifiants de code a la doctrine (AGENTS.md : « tout identifiant de
code en ANGLAIS — les tests COMPRIS depuis le 2026-09-19 ; commentaires, docstrings et textes
affiches restent en francais »).

RAISON D'ETRE (question de Fabien, 2026-09-19 : « Encore des termes en francais... Comment
arreter ca ? »). La regle existait depuis le 2026-08-22, elle a ete durcie le 14/09 — et elle a
DERIVE quand meme : releve du 19/09, **2653 identifiants francais dans 358 fichiers**, plus
133 noms de classes de test et 1298 noms de methodes de test — **4084 en tout**. Le defaut
n'est pas la regle, c'est qu'AUCUN CONTROLE ne la tenait : elle demandait de s'en souvenir.
*Une regle qui demande de se souvenir n'est pas un controle.*

Le meme jour, deux occurrences ont ete introduites dans du code NEUF puis relevees a l'oeil par
Fabien (`declarees`/`fusion`/`ouvertes`, puis `banc`/`lus`) : la relecture humaine est la seule
garde aujourd'hui, et elle passe apres l'ecriture.

CE QUE CE CONTROLE FAIT — un BUDGET QUI NE PEUT QUE DESCENDRE, motif deja eprouve ici
(`tests_hf_cache_routing` pour les mutations de cache HF) : il ne demande AUCUN grand chantier de
renommage, il rend seulement l'AJOUT impossible. Un renommage fait baisser le budget ; un oubli le
fait monter et le test echoue en nommant le fichier et la ligne.

PERIMETRE (ce que la doctrine appelle « identifiant de code ») : classes, fonctions, arguments,
variables assignees, alias d'import. EXCLUS : les chaines, les commentaires, les docstrings, les
cles de DONNEES (frontiere des donnees, regle 3 du 29/08) et les migrations (generees).

PLUS AUCUNE EXEMPTION depuis le 2026-09-19 (decision de Fabien : « on bascule tout le code y
compris les tests en anglais »). L'exemption des noms de tests, ecrite le 22/08 (« il se lit dans
un rapport d'echec, et nulle part ailleurs »), est LEVEE : elle defendait en realite le STYLE
— une phrase qui enonce un COMPORTEMENT plutot qu'un nom de cible — et ce style se garde en
anglais (`test_refreshing_twice_changes_nothing_the_second_time`).

TROIS COMPTES SEPARES, tous appliques, parce qu'ils se soldent differemment :
  * le CODE (2653) a des consommateurs : un renommage y rend FAUX (jumeaux par chaine, cles de
    payload, docs) — il se fait par passes tokenisees, radical par radical (`--by-root`) ;
  * les noms de CLASSES de test (133) et de METHODES de test (1298) n'ont aucun appelant : sans
    risque, mais 1431 renommages qui noieraient tout autre diff — donc app par app, en dernier.

Ne modifie RIEN. Sort en code 1 si le budget est depasse, pour servir en CI.
"""
import ast
import json
import re
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

#: Racines de code WAMA. `wama-dev-ai` en fait partie : ses roles sont du code lu en revue.
ROOTS = ('wama', 'wama_data', 'wama_lab', 'wama-dev-ai')
#: Chemins hors perimetre : venvs, dependances, fichiers generes, poids.
SKIPPED = ('venv_linux', 'venv_win', 'node_modules', 'staticfiles', 'vendor',
           'migrations', '__pycache__', 'AI-models')

#: Radicaux FRANCAIS releves dans ce depot. Liste NOIRE (jamais blanche) : un mot inconnu passe,
#: donc le controle ne bloque jamais un nom anglais legitime qu'il ne connaitrait pas. Les mots
#: AMBIGUS anglais/francais sont volontairement absents (source, type, mode, page, total, format,
#: image, instance, table, note, charge, sens) : les compter ferait un budget bruyant, et un
#: budget bruyant se contourne.
FRENCH_WORDS = frozenset({
    'banc', 'bancs', 'cle', 'cles', 'tache', 'taches', 'modele', 'modeles', 'fichier', 'fichiers',
    'chemin', 'chemins', 'donnee', 'donnees', 'taille', 'tailles', 'sortie', 'sorties', 'entree',
    'entrees', 'essai', 'essais', 'declare', 'declares', 'declaree', 'declarees', 'perime',
    'perimes', 'manquant', 'manquants', 'manquante', 'manquantes', 'cible', 'cibles', 'liste',
    'listes', 'valeur', 'valeurs', 'resultat', 'resultats', 'erreur', 'erreurs', 'etat', 'etats',
    'garde', 'gardes', 'seuil', 'seuils', 'ligne', 'lignes', 'dossier', 'dossiers', 'choix',
    'poids', 'langue', 'langues', 'compte', 'comptes', 'verifie', 'trouve', 'trouves', 'ecrit',
    'ecrits', 'reste', 'restes', 'ancien', 'anciens', 'nouveau', 'nouveaux', 'premier', 'dernier',
    'autre', 'autres', 'meme', 'memes', 'chaque', 'avant', 'apres', 'debut', 'nombre', 'ensemble',
    'exemple', 'exemples', 'libelle', 'libelles', 'motif', 'motifs', 'releve', 'releves',
    'mesure', 'mesures', 'sonde', 'sondes', 'jumeau', 'jumeaux', 'attendu', 'attendus',
    'obtenu', 'obtenus', 'lus', 'lue', 'lues', 'vus', 'vue', 'vues', 'faits', 'refus', 'refuses',
    'inchange', 'inchanges', 'supprime', 'supprimes', 'cree', 'crees', 'ajoute', 'ajoutes',
    'retire', 'retires', 'pose', 'poses', 'posee', 'posees', 'chargeur', 'lecteur', 'lecteurs',
    'ecriture', 'lecture', 'appel', 'appels', 'reponse', 'reponses', 'requete', 'requetes',
    'brut', 'bruts', 'brute', 'brutes', 'propre', 'propres', 'categorie', 'categories',
    'famille', 'familles', 'echelle', 'echelles', 'rang', 'rangs', 'indice', 'indices',
    'niveau', 'niveaux', 'utilisateur', 'utilisateurs', 'alerte', 'alertes', 'journal',
    'volet', 'volets',
})
#: Identifiants ACCEPTES malgre un mot de la liste : homonymes anglais, ou API tierce imposee.
ALLOWED = frozenset({'liste_id'})
#: Un accent est un signal CERTAIN (Python 3 les accepte dans les identifiants).
ACCENTED = re.compile(r'[àâäéèêëîïôöùûüÿçÀÂÄÉÈÊËÎÏÔÖÙÛÜŸÇ]')

#: TROIS BUDGETS ADDITIFS, mesures EXACTEMENT le 2026-09-19, TOUS APPLIQUES.
#: Cales au releve, sans marge : une marge est une autorisation d'en ajouter.
#: ⚠ ILS NE PEUVENT QUE DESCENDRE. Ne JAMAIS en relever un pour faire passer un ajout : le
#: remede est de nommer l'identifiant en anglais. Les baisser apres une passe de renommage est
#: le geste normal — c'est ainsi que la dette se solde sans chantier dedie.
#:
#: DECISION DE FABIEN, 2026-09-19 : « on bascule tout le code y compris les tests en anglais ».
#: Les noms de tests etaient la derniere exemption de la doctrine (AGENTS.md, 22/08) ; elle est
#: LEVEE. Ils restent comptes A PART parce qu'ils se soldent autrement : aucun appelant, donc
#: aucun risque de rendre FAUX — mais 1298 renommages qui noieraient tout autre diff.
BUDGET_CODE = 2653          # production (1722) + fichiers de tests hors noms (931)
BUDGET_TEST_CLASSES = 132   # noms de classes `*Test` (133 avant la 1re bascule)
BUDGET_TEST_NAMES = 1296    # noms de methodes `test_*` — sur 2777 (46 %)
#: Ce que coute l'uniformisation complete, pour memoire : 4081 (4084 au 1er releve —
#: le premier fichier de tests ecrit APRES la bascule a deja rendu 3 noms).
BUDGET_TOTAL = BUDGET_CODE + BUDGET_TEST_CLASSES + BUDGET_TEST_NAMES


def _words(name: str):
    """Les mots d'un identifiant (snake_case, camelCase, SCREAMING_CASE), en minuscules."""
    spaced = re.sub(r'(?<!^)(?=[A-Z][a-z])', '_', name)
    return [w for w in spaced.lower().split('_') if w]


def is_french(name: str) -> bool:
    if not name or name in ALLOWED:
        return False
    if ACCENTED.search(name):
        return True
    return any(w in FRENCH_WORDS for w in _words(name))


def is_test_class(kind: str, name: str) -> bool:
    return kind == 'class' and (name.endswith('Test') or name.endswith('Tests'))


class _Collector(ast.NodeVisitor):
    """Les identifiants DEFINIS par un fichier — jamais ceux qu'il consomme (une API tierce
    francaise ne doit pas etre comptee contre nous a chaque appel)."""

    def __init__(self):
        self.found = []          # (kind, name, line)

    def _see(self, kind, name, line):
        if is_french(name):
            self.found.append((kind, name, line))

    def visit_FunctionDef(self, node):
        if not node.name.startswith('test_'):        # seule exception de la doctrine
            self._see('function', node.name, node.lineno)
        args = node.args
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self._see('argument', a.arg, a.lineno)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._see('class', node.name, node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self._see('variable', node.id, node.lineno)
        self.generic_visit(node)

    def visit_alias(self, node):
        if node.asname:
            self._see('import', node.asname, getattr(node, 'lineno', 0))
        self.generic_visit(node)


def python_files(base: Path):
    for root in ROOTS:
        folder = base / root
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob('*.py')):
            if not any(part in SKIPPED for part in path.parts):
                yield path


def scan_test_names(base: Path):
    """(francais, total) parmi les methodes `test_*` — la dette que le budget n'attrape PAS.

    Les noms de tests sont la seule exemption de la doctrine (« il se lit dans un rapport
    d'echec ») : ils ne sont donc pas dans `scan`. Mais ils EXISTENT, en nombre, et Fabien veut
    savoir ce que couterait de les uniformiser : ce releve le dit sans rien bloquer.
    """
    french, total = [], 0
    for path in python_files(base):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(base).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                total += 1
                if is_french(node.name):
                    french.append((rel, node.name, node.lineno))
    return french, total


def roots_of(by_file):
    """Radical francais -> nombre d'identifiants qui le portent. C'est l'outil de PILOTAGE :
    20 radicaux couvrent 56 % des 2653 (mesure du 2026-09-19, 605 noms distincts), donc une
    passe PAR RADICAL solde la dette par tranches nettes au lieu de fichier par fichier."""
    counter = Counter()
    for found in by_file.values():
        for _, name, _ in found:
            for word in _words(name):
                if word in FRENCH_WORDS:
                    counter[word] += 1
    return counter


def scan(base: Path, with_test_classes: bool = False):
    """(total, par fichier, compteur de noms) — le relevé complet, sans rien écrire."""
    by_file, names, total = {}, Counter(), 0
    for path in python_files(base):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError):
            continue                      # un fichier illisible se signale ailleurs (py_compile)
        collector = _Collector()
        collector.visit(tree)
        kept = [f for f in collector.found
                if with_test_classes or not is_test_class(f[0], f[1])]
        if kept:
            rel = path.relative_to(base).as_posix()
            by_file[rel] = kept
            total += len(kept)
            for _, name, _ in kept:
                names[name] += 1
    return total, by_file, names


def counts(base: Path) -> dict:
    """Les TROIS comptes, additifs — c'est la seule lecture dont la commande et le test ont
    besoin, et elle evite de rescanner trois fois dans trois endroits differents."""
    code, by_file, names = scan(base, with_test_classes=False)
    with_classes, _, _ = scan(base, with_test_classes=True)
    test_names, test_methods = scan_test_names(base)
    return {'code': code, 'test_classes': with_classes - code,
            'test_names': len(test_names), 'test_methods': test_methods,
            'total': with_classes + len(test_names),
            'by_file': by_file, 'names': names, 'test_name_hits': test_names}


class Command(BaseCommand):
    help = ("Compte les identifiants de code en francais — TROIS budgets qui ne peuvent que "
            "DESCENDRE (code, classes de test, noms de tests). Sort en 1 si l'un est depasse.")

    def add_arguments(self, parser):
        parser.add_argument('--detail', action='store_true',
                            help='Liste fichier:ligne de chaque identifiant releve.')
        parser.add_argument('--json', action='store_true', help='Sortie machine.')
        parser.add_argument('--top', type=int, default=15,
                            help='Nombre de fichiers les plus charges a afficher (defaut 15).')
        parser.add_argument('--by-root', action='store_true',
                            help="Classement des RADICAUX francais (outil de pilotage : une "
                                 "passe de renommage par radical, la plus rentable d'abord).")
        parser.add_argument('--test-names', action='store_true',
                            help='Liste les noms de methodes `test_*` en francais (fichier:ligne).')

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        measured = counts(base)
        by_file, names = measured['by_file'], measured['names']
        #: (libelle, mesure, budget) — les trois s'additionnent, et chacun se solde a son rythme.
        lines = (('code (production + tests hors noms)', measured['code'], BUDGET_CODE),
                 ('noms de classes `*Test`', measured['test_classes'], BUDGET_TEST_CLASSES),
                 ('noms de methodes `test_*`', measured['test_names'], BUDGET_TEST_NAMES))

        if options['json']:
            self.stdout.write(json.dumps(
                {'code': measured['code'], 'test_classes': measured['test_classes'],
                 'test_names': measured['test_names'], 'total': measured['total'],
                 'budgets': {'code': BUDGET_CODE, 'test_classes': BUDGET_TEST_CLASSES,
                             'test_names': BUDGET_TEST_NAMES, 'total': BUDGET_TOTAL},
                 'test_methods': measured['test_methods'], 'files': len(by_file),
                 'by_file': {f: len(v) for f, v in by_file.items()},
                 'names': names.most_common(40)}, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"{measured['total']} identifiant(s) de code en francais "
                              f"(budget {BUDGET_TOTAL}) :")
            for label, seen, budget in lines:
                verdict = '✓' if seen <= budget else '✗'
                self.stdout.write(f"  {verdict} {label:38} {seen:5} / {budget}")
            share = 100 * measured['test_names'] // max(measured['test_methods'], 1)
            self.stdout.write(f"    ({measured['test_methods']} methodes de test au total, "
                              f"{share} % nommees en francais)")
            self.stdout.write(f"\n  {len(by_file)} fichier(s) portent du code francais :")
            for rel, found in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:options['top']]:
                sample = ', '.join(sorted({n for _, n, _ in found})[:5])
                self.stdout.write(f"  {len(found):4}  {rel:58} {sample}")
            if options['by_root']:
                roots = roots_of(by_file)
                self.stdout.write("\n  radical         porte par   cumul")
                seen_total = 0
                for word, n in roots.most_common(25):
                    seen_total += n
                    self.stdout.write(
                        f"  {word:14} {n:9}   {100 * seen_total // max(measured['code'], 1):4} %")
                self.stdout.write(f"  ({len(roots)} radicaux pour {len(names)} noms distincts — "
                                  f"une passe PAR RADICAL solde par tranches nettes)")
            if options['detail']:
                for rel, found in sorted(by_file.items()):
                    for kind, name, line in found:
                        self.stdout.write(f"{rel}:{line}: {kind} {name}")
            if options['test_names']:
                for rel, name, line in measured['test_name_hits']:
                    self.stdout.write(f"{rel}:{line}: test {name}")

        over = [(label, seen, budget) for label, seen, budget in lines if seen > budget]
        if over:
            for label, seen, budget in over:
                self.stderr.write(f"\n✗ BUDGET DEPASSE — {label} : {seen} > {budget}")
            self.stderr.write(
                "Un identifiant de code se nomme en ANGLAIS (AGENTS.md, decision du 2026-09-19 : "
                "les tests aussi) — le remede est de renommer, JAMAIS de relever un budget. "
                "`--detail` / `--test-names` disent lesquels ; `git diff` dit lesquels sont de vous.")
            raise SystemExit(1)

        slack = [(label, budget - seen) for label, seen, budget in lines if seen < budget]
        if slack:
            for label, gain in slack:
                self.stdout.write(self.style.SUCCESS(
                    f"✓ {label} : {gain} sous le budget — le descendre verrouille ce gain "
                    f"({Path(__file__).name})"))
        else:
            self.stdout.write(self.style.SUCCESS("✓ les trois budgets sont tenus, sans marge"))
