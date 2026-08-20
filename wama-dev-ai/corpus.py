"""
Corpus externes — accès EN LECTURE SEULE à des dépôts hors du dépôt WAMA.

POURQUOI CE MODULE. wama-dev-ai était scopé au seul dépôt WAMA (`FileDiscovery(base_dir=BASE_DIR)`).
Cartographier un framework tiers (BIND en MATLAB, pynd en Python) imposait soit d'en copier les
sources dans le dépôt — un doublon qui dérive dès la première modification en amont — soit de
donner à l'agent un accès nommé au dossier d'origine. Arbitrage Fabien du 2026-08-20 :
**on ajoute l'accès, on ne copie pas.** Ce besoin se représentera (autres frameworks à confronter),
donc la brique est générique et déclarative, pas taillée pour BIND.

CE QUE CE MODULE GARANTIT
  1. **Lecture seule, par construction** — `assert_readonly()` refuse toute écriture dans un corpus.
     wama-dev-ai est déjà read-only en Phase 1, mais la garantie ne doit pas dépendre de cette phase :
     un corpus est la propriété de quelqu'un d'autre, on ne le modifie jamais.
  2. **Pas d'évasion de racine** — `resolve()` refuse tout chemin qui sortirait du corpus après
     résolution (`..`, liens). Un corpus est une boîte, pas un point de départ.
  3. **Périmètre déclaré** — chaque corpus déclare ce qu'on en retient. Sans ça, BIND expose 4305
     fichiers dont ~2900 d'outillage (packagers, NaturalDocs, sqlite4m, scripts d'analyse) qui
     noieraient la cartographie sans rien lui apprendre.
  4. **Formats non-texte décodés à la lecture** — un `.mlapp` MATLAB est une archive ZIP ; le lire
     en texte brut rend du binaire. `read_text()` le décode de façon transparente, donc AUCUN
     appelant n'a à connaître le format.

RÉFÉRENCE MÉTIER : `WAMA_DATA_WORLD.md §9` (périmètre et méthode de la cartographie BIND).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, Optional, Set, Tuple

#: Séparateur d'une référence de corpus : « bind:BIND_core/src/… ».
#: Choisi parce qu'il ne peut pas apparaître dans un chemin relatif POSIX ou Windows valide.
CORPUS_SEP = ":"


@dataclass(frozen=True)
class Corpus:
    """Un dépôt externe consultable en lecture seule."""

    name: str
    root: Path
    #: Ce qu'on RETIENT (préfixes de chemin relatif). Vide = tout le corpus.
    include: Tuple[str, ...] = ()
    #: Ce qu'on écarte, même à l'intérieur d'`include` (noms de dossier, à n'importe quel niveau).
    exclude: Tuple[str, ...] = ()
    #: Extensions retenues. Vide = celles du projet (`CODE_EXTENSIONS`).
    extensions: Tuple[str, ...] = ()
    description: str = ""

    def available(self) -> bool:
        """Le corpus est-il joignable ? (partage réseau démonté, VPN absent…)"""
        try:
            return self.root.is_dir()
        except OSError:
            return False


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Déclaration des corpus
#
# ⚠ Le périmètre `include` de BIND N'EST PAS une commodité : il est le résultat de la passe 0 de
# cartographie (WAMA_DATA_WORLD.md §9). Le modifier = changer ce que l'agent voit du framework.
# ──────────────────────────────────────────────────────────────────────────────────────────────

MATLAB_EXTENSIONS = (".m", ".mlapp")

CORPORA: Dict[str, Corpus] = {
    "bind": Corpus(
        name="bind",
        root=Path(r"\\vrlescot\SAVES\DEV\BIND"),
        include=(
            "BIND_core",           # le noyau : kernel (Trip/TripSet/TimerTrip/SQLiteTrip), plugins, processing
            "BIND_plugins",        # implémentations, dont Magneto.m
            "BIND_plugins_coding",  # plugins de codage
            "BIND_GUI",            # mince en .m, mais porte les 3 .mlapp (GUI, VISU, GUIDE)
            "pynd",                # copie du cœur Python présente sous BIND
        ),
        # Outillage et analyses résiduelles : ~2900 fichiers qui n'apprennent rien du framework.
        exclude=(
            "BIND_scripts", "BIND_packagers", "NaturalDocs4Matlab", "Matjab", "sqlite4m",
            "dependencies", "gmapsBot", "DShowAudio4BIND", "DShowVideo4BIND", "XUPy", "BIND_GS",
            "BIND_doc",            # doc NaturalDocs : dérivée des .m, redondante pour un LLM
            ".git", "__pycache__",
        ),
        extensions=MATLAB_EXTENSIONS + (".py", ".md", ".txt"),
        description="BIND — framework MATLAB d'analyse de données expérimentales (LESCOT). "
                    "Source du monde DATA de WAMA : couche temporelle, plugins synchronisés, format .trip.",
    ),
    "pynd": Corpus(
        name="pynd",
        root=Path(r"\\vrlescot\SAVES\DEV\pynd"),
        exclude=(".git", "__pycache__", ".idea"),
        extensions=(".py", ".md", ".txt", ".bat"),
        description="pynd — portage Python du CŒUR de BIND (sans GUI). Dit ce que le portage a "
                    "retenu et ce qu'il a abandonné.",
    ),
}


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Résolution de chemins
# ──────────────────────────────────────────────────────────────────────────────────────────────

def get(name: str) -> Corpus:
    """Corpus par son nom, avec un message utile si le nom est inconnu."""
    try:
        return CORPORA[name]
    except KeyError:
        raise KeyError(
            f"corpus '{name}' inconnu (déclarés : {', '.join(sorted(CORPORA)) or '—'})"
        ) from None


def parse_ref(ref: str) -> Tuple[Optional[str], str]:
    """
    Sépare « bind:BIND_core/src/x.m » en ('bind', 'BIND_core/src/x.m').

    Un chemin sans préfixe connu rend (None, ref) : c'est un chemin du dépôt WAMA, et cette
    fonction ne doit JAMAIS transformer un chemin de projet (ex. 'C:/…' sous Windows contient un
    ':' mais 'C' n'est pas un corpus).
    """
    if CORPUS_SEP not in ref:
        return None, ref
    head, _, tail = ref.partition(CORPUS_SEP)
    if head in CORPORA:
        return head, tail.lstrip("/\\")
    return None, ref


def resolve(ref: str) -> Path:
    """
    Chemin absolu d'une référence de corpus, ou chemin tel quel s'il n'en est pas une.

    Lève ValueError si le chemin s'évade de la racine du corpus — un `..` dans une référence
    produite par un LLM ne doit jamais donner accès au reste du disque.
    """
    name, rel = parse_ref(ref)
    if name is None:
        return Path(ref)
    corpus = get(name)
    target = (corpus.root / rel).resolve()
    root = corpus.root.resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"chemin hors du corpus '{name}' : {ref}")
    return target


#: Racines résolues, calculées UNE fois. `Path.resolve()` sur un chemin UNC est un aller-retour
#: réseau : le faire par fichier (4305 pour BIND) rendait toute énumération interminable — mesuré
#: le 2026-08-20, un démarrage d'agent bloqué > 10 min sans le moindre message. Règle : sur un
#: corpus distant, AUCUN appel système par fichier au-delà de ceux qu'exige le parcours lui-même.
_ROOTS_RESOLUS: Dict[str, str] = {}


def _root_str(corpus: Corpus) -> str:
    """Racine résolue en minuscules, mise en cache (comparaisons de préfixe, pas d'I/O)."""
    cached = _ROOTS_RESOLUS.get(corpus.name)
    if cached is None:
        try:
            cached = str(corpus.root.resolve()).rstrip("\\/").lower()
        except OSError:
            cached = str(corpus.root).rstrip("\\/").lower()
        _ROOTS_RESOLUS[corpus.name] = cached
    return cached


def find_corpus(path: Path) -> Optional[Corpus]:
    """
    Le corpus qui contient ce chemin, ou None (= dépôt WAMA).

    Comparaison de PRÉFIXE sur des chaînes : aucun accès disque ni réseau. Les chemins qui
    arrivent ici viennent soit de `resolve()` (références de corpus), soit de `rglob()` sur la
    racine — ils sont déjà normalisés, et re-résoudre coûterait un aller-retour SMB par appel.
    """
    candidate = str(path).rstrip("\\/").lower()
    for corpus in CORPORA.values():
        root = _root_str(corpus)
        if candidate == root or candidate.startswith(root + "\\") or candidate.startswith(root + "/"):
            return corpus
    return None


def label(path: Path) -> str:
    """
    Étiquette lisible et REJOUABLE d'un chemin : « bind:BIND_core/src/…/Trip.m ».

    C'est ce que l'agent doit citer dans ses rapports — un chemin UNC brut dans un rapport n'est
    ni portable ni vérifiable par un lecteur qui n'a pas le partage monté.
    """
    corpus = find_corpus(path)
    if corpus is None:
        return str(path)
    # Découpe sur la longueur de la racine — pas de `resolve()` (aller-retour réseau par appel).
    rel = str(path)[len(_root_str(corpus)):].lstrip("\\/").replace("\\", "/")
    return f"{corpus.name}{CORPUS_SEP}{rel}"


def assert_readonly(path: Path) -> None:
    """
    Refuse toute écriture visant un corpus externe.

    À appeler dans TOUT chemin d'écriture. Un corpus appartient à quelqu'un d'autre : même une
    correction « évidente » s'y interdit, parce qu'elle serait invisible pour son propriétaire.
    """
    corpus = find_corpus(path)
    if corpus is not None:
        raise PermissionError(
            f"écriture refusée : '{label(path)}' appartient au corpus en LECTURE SEULE "
            f"'{corpus.name}'. Les corpus externes ne sont jamais modifiés."
        )


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Parcours
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _kept(corpus: Corpus, rel: Path, suffix: str, extensions: Set[str]) -> bool:
    """Filtre sur le chemin DÉJÀ relatif — aucun accès disque."""
    if suffix not in extensions:
        return False
    parts = rel.parts
    if any(part in corpus.exclude for part in parts):
        return False
    if corpus.include and (not parts or parts[0] not in corpus.include):
        return False
    return True


#: Liste des fichiers retenus, par corpus — le parcours d'un partage réseau est CHER et le corpus
#: ne bouge pas pendant un run. Sans ce cache, chaque recherche de l'agent re-parcourait 4305
#: fichiers en SMB.
_FICHIERS_CACHE: Dict[str, list] = {}


def iter_files(corpus: Corpus, extensions: Optional[Set[str]] = None) -> Iterator[Path]:
    """
    Fichiers retenus d'un corpus. Silencieux si le corpus est injoignable (partage démonté) :
    l'agent doit pouvoir tourner sur le dépôt WAMA même sans VPN.

    Le parcours complet n'a lieu qu'UNE fois par corpus et par process ; le filtre par extensions
    s'applique ensuite en mémoire. On descend d'abord dans les seuls dossiers `include`, ce qui
    évite d'énumérer les ~2900 fichiers d'outillage qu'on écarte de toute façon.
    """
    if not corpus.available():
        return
    exts = extensions or set(corpus.extensions)
    if not exts:
        return

    tous = _FICHIERS_CACHE.get(corpus.name)
    if tous is None:
        tous = []
        # Racines de descente : les `include` déclarés, sinon le corpus entier. Ne JAMAIS
        # rglob la racine quand on sait déjà qu'on n'en retiendra qu'une fraction.
        bases = [corpus.root / inc for inc in corpus.include] if corpus.include else [corpus.root]
        connues = set(corpus.extensions) or None
        for base in bases:
            try:
                if not base.is_dir():
                    continue
                for path in base.rglob("*"):
                    try:
                        rel = path.relative_to(corpus.root)
                    except ValueError:
                        continue
                    suffix = path.suffix.lower()
                    if connues is not None and suffix not in connues:
                        continue          # écarté sans appel système (pas de is_file())
                    if any(part in corpus.exclude for part in rel.parts):
                        continue
                    if path.is_file():
                        tous.append((path, rel, suffix))
            except OSError:
                continue
        _FICHIERS_CACHE[corpus.name] = tous

    for path, rel, suffix in tous:
        if _kept(corpus, rel, suffix, exts):
            yield path


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Lecture — décodage des formats non-texte
# ──────────────────────────────────────────────────────────────────────────────────────────────

#: Le source MATLAB d'un `.mlapp` vit dans cette entrée de l'archive (OPC/WordprocessingML),
#: à l'intérieur d'un unique bloc CDATA. Vérifié le 2026-08-20 sur BIND_GUI/VISU/GUIDE.
MLAPP_SOURCE_ENTRY = "matlab/document.xml"
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def read_mlapp(path: Path) -> str:
    """
    Source MATLAB d'un `.mlapp` (App Designer).

    Un `.mlapp` est une archive ZIP ; `matlab/document.xml` y enveloppe le `classdef` complet dans
    un bloc CDATA. `appdesigner/appModel.mat` porte la mise en page, en binaire MAT — non extrait
    ici : ce qui nous intéresse est la LOGIQUE, pas la position des boutons.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(MLAPP_SOURCE_ENTRY).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        return f"[.mlapp illisible : {exc}]"
    blocks = _CDATA.findall(raw)
    if blocks:
        return "\n".join(blocks)
    # Repli : pas de CDATA (variante de format) → on retire le balisage plutôt que rendre du XML.
    return _TAG.sub("", raw)


#: Extension → décodeur. Ajouter un format se fait ICI, pas chez les appelants.
READERS = {".mlapp": read_mlapp}


def read_text(path: Path) -> str:
    """
    Contenu textuel d'un fichier, quel que soit son conditionnement.

    C'est le point d'entrée unique : un appelant n'a jamais à savoir qu'un `.mlapp` est un ZIP.
    """
    path = Path(path)
    reader = READERS.get(path.suffix.lower())
    if reader is not None:
        return reader(path)
    return path.read_text(encoding="utf-8", errors="ignore")


def status() -> str:
    """Ligne d'état lisible — à afficher au démarrage d'un audit qui utilise des corpus."""
    lines = []
    for corpus in CORPORA.values():
        if corpus.available():
            count = sum(1 for _ in iter_files(corpus))
            lines.append(f"  {corpus.name:<8} OK   {count} fichiers retenus  ({corpus.root})")
        else:
            lines.append(f"  {corpus.name:<8} INJOIGNABLE  ({corpus.root})")
    return "\n".join(lines)


if __name__ == "__main__":   # python wama-dev-ai/corpus.py → contrôle rapide
    print("Corpus déclarés :")
    print(status())
