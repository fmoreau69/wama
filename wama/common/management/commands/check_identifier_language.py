# -*- coding: utf-8 -*-
"""
Confronte la LANGUE des identifiants de code a la doctrine (AGENTS.md : « tout identifiant de
code en ANGLAIS, sauf les noms de tests ; commentaires, docstrings et textes affiches restent en
francais »).

RAISON D'ETRE (question de Fabien, 2026-09-19 : « Encore des termes en francais... Comment
arreter ca ? »). La regle existait depuis le 2026-08-22, elle a ete durcie le 14/09 — et elle a
DERIVE quand meme : releve du 19/09, **2653 identifiants francais dans 358 fichiers**
(2786 dans 366 si l'on compte les noms de classes de test). Le defaut
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

EXEMPTIONS ECRITES :
  * les methodes `test_*` — seule exception de la doctrine : « elle se lit dans un rapport
    d'echec, et nulle part ailleurs » ;
  * les NOMS DE CLASSES de test (`*Test`, `*Tests`) — meme nature qu'une methode de test, mais
    ⚠ ZONE GRISE de doctrine : une classe de test EST importable (`manage.py test
    wama.x.tests.MaClasseTest`), donc la lettre de la regle la voudrait en anglais. Exemptee ici
    pour ne pas transformer un controle d'hygiene en chantier de 143 renommages ; a trancher par
    Fabien. `--strict-classes` les compte, pour que le choix soit MESURABLE avant d'etre pris.

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

#: BUDGET — mesure EXACTE du 2026-09-19 sur les 4 racines, classes de test exemptees.
#: Cale au releve, sans marge : une marge est une autorisation d'en ajouter.
#: ⚠ IL NE PEUT QUE DESCENDRE. Ne JAMAIS le relever pour faire passer un ajout : le remede est
#: de nommer l'identifiant en anglais. Le baisser apres une passe de renommage est le geste
#: normal — c'est ainsi que la dette se solde sans chantier dedie.
BUDGET = 2653
#: Le meme, classes de test COMPRISES (`--strict-classes`) : chiffre de la decision en attente.
BUDGET_WITH_TEST_CLASSES = 2786
#: NOMS DE METHODES `test_*` en francais — 1298 sur 2774 (46 %), mesure du 2026-09-19.
#: ⚠ NON applique par defaut : la doctrine les autorise encore (AGENTS.md : « elle se lit dans un
#: rapport d'echec, et nulle part ailleurs »). Applique par `--include-test-names`, pour que la
#: bascule soit UNE OPTION deja outillee le jour ou Fabien tranche — il a dit le 19/09 vouloir
#: « uniformiser petit a petit en anglais et surtout ne pas reintroduire de termes en francais »,
#: ce qui pointe vers cette bascule sans la prononcer.
BUDGET_TEST_NAMES = 1298


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


class Command(BaseCommand):
    help = ("Compte les identifiants de code en francais (budget qui ne peut que DESCENDRE). "
            "Sort en 1 si le budget est depasse.")

    def add_arguments(self, parser):
        parser.add_argument('--detail', action='store_true',
                            help='Liste fichier:ligne de chaque identifiant releve.')
        parser.add_argument('--strict-classes', action='store_true',
                            help="Compte AUSSI les noms de classes de test (`*Test`) — la zone "
                                 "grise de doctrine, a trancher.")
        parser.add_argument('--json', action='store_true', help='Sortie machine.')
        parser.add_argument('--top', type=int, default=15,
                            help='Nombre de fichiers les plus charges a afficher (defaut 15).')
        parser.add_argument('--by-root', action='store_true',
                            help="Classement des RADICAUX francais (outil de pilotage : une "
                                 "passe de renommage par radical, la plus rentable d'abord).")
        parser.add_argument('--include-test-names', action='store_true',
                            help="Compte AUSSI les noms de methodes `test_*` et applique leur "
                                 "budget — la bascule que la doctrine n'a pas encore prononcee.")

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR)
        strict = options['strict_classes']
        budget = BUDGET_WITH_TEST_CLASSES if strict else BUDGET
        total, by_file, names = scan(base, with_test_classes=strict)

        if options['json']:
            self.stdout.write(json.dumps(
                {'total': total, 'budget': budget, 'files': len(by_file),
                 'with_test_classes': strict,
                 'by_file': {f: len(v) for f, v in by_file.items()},
                 'names': names.most_common(40)}, ensure_ascii=False, indent=2))
        else:
            etiquette = 'classes de test COMPRISES' if strict else 'classes de test exemptees'
            self.stdout.write(f"{total} identifiant(s) de code en francais dans "
                              f"{len(by_file)} fichier(s) ({etiquette}) — budget {budget}")
            for rel, found in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:options['top']]:
                echantillon = ', '.join(sorted({n for _, n, _ in found})[:5])
                self.stdout.write(f"  {len(found):4}  {rel:58} {echantillon}")
            if options['by_root']:
                roots = roots_of(by_file)
                self.stdout.write("\n  radical         porte par   cumul")
                seen = 0
                for word, n in roots.most_common(25):
                    seen += n
                    self.stdout.write(f"  {word:14} {n:9}   {100 * seen // max(total, 1):4} %")
                self.stdout.write(f"  ({len(roots)} radicaux pour {len(names)} noms distincts — "
                                  f"une passe PAR RADICAL solde par tranches nettes)")
            if options['detail']:
                for rel, found in sorted(by_file.items()):
                    for kind, name, line in found:
                        self.stdout.write(f"{rel}:{line}: {kind} {name}")

        test_names, test_total = scan_test_names(base)
        share = 100 * len(test_names) // max(test_total, 1)
        if not options['json']:
            self.stdout.write(
                f"\n  noms de methodes `test_*` en francais : {len(test_names)} sur {test_total} "
                f"({share} %) — budget {BUDGET_TEST_NAMES}, "
                + ("APPLIQUE" if options['include_test_names'] else
                   "NON applique (la doctrine les autorise encore ; `--include-test-names` "
                   "l'applique)"))
        if options['include_test_names'] and len(test_names) > BUDGET_TEST_NAMES:
            self.stderr.write(
                f"\n✗ BUDGET DES NOMS DE TESTS DEPASSE : {len(test_names)} > {BUDGET_TEST_NAMES}")
            raise SystemExit(1)

        if total > budget:
            self.stderr.write(
                f"\n✗ BUDGET DEPASSE : {total} > {budget}. Un identifiant de code se nomme en "
                f"ANGLAIS (AGENTS.md) — le remede est de renommer, JAMAIS de relever le budget. "
                f"`--detail` dit lesquels, `git diff` dit lesquels sont de vous.")
            raise SystemExit(1)
        if total < budget:
            self.stdout.write(self.style.SUCCESS(
                f"✓ sous le budget de {budget - total} — descendre `BUDGET` a {total} "
                f"dans {Path(__file__).name} verrouille ce gain."))
        else:
            self.stdout.write(self.style.SUCCESS("✓ budget tenu (a l'unite pres)"))
