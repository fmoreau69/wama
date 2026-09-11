"""
Faits EN LIGNE dans les `.md` — une balise qui va chercher sa valeur dans un registre.

POURQUOI (Fabien, 2026-09-11 — AGENTS.md §Trois docs, ROADMAP.md §25)

    La doc de construction porte l'INTENTION ; les registres portent l'ÉTAT. Une doc qui recopie
    un chiffre ou un libellé de registre le périme dès qu'il bouge. `doc_facts` régénérait déjà des
    BLOCS, un par fait, chacun avec sa fonction écrite à la main (six). Cette brique en est la
    généralisation EN LIGNE : une seule syntaxe pour n'importe quel champ de n'importe quel registre
    qui déclare ses fiches (`Registry.entries`). C'est la première pièce de la mécanique des docs
    dérivées : les docs développeur et utilisateur y puiseront leurs vérités terrain.

SYNTAXE — même famille que `WAMA:FAITS`, invisible sur GitHub comme dans le lecteur de doc

    <!-- WAMA:FAIT(apps/transcriber/label) -->Transcriber<!-- /WAMA:FAIT -->
    <!-- WAMA:FAIT(registres) -->15<!-- /WAMA:FAIT -->      ← sans clé : le NOMBRE d'entrées

    Le chemin est `<registre>` ou `<registre>/<clé>/<champ>`. `registres` désigne le registre des
    registres lui-même (`registries.overview()`). La valeur entre les balises est régénérée par
    `manage.py doc_facts` et confrontée par `doc_facts --check` — jamais saisie à la main.

CE QU'UNE BALISE NE PEUT PAS FAIRE — refusé, jamais deviné

    Viser un registre inconnu ou qui ne déclare pas ses fiches, une clé ou un champ absents, un
    champ qui n'est pas une valeur (un dict) : la balise est CASSÉE, et signalée comme telle. Un
    fait qu'on pourrait inventer n'est plus un fait.
"""
from __future__ import annotations

import dataclasses
import re
from typing import Dict, List, Tuple

TAG = re.compile(r'<!-- WAMA:FAIT\(([^)\s]+)\) -->(.*?)<!-- /WAMA:FAIT -->')

#: Une balise CITÉE en code (bloc ``` ou `en ligne`) n'est pas une balise : une doc doit pouvoir
#: EXPLIQUER la syntaxe sans que le résolveur la prenne pour un fait. Trouvé le 2026-09-11 par la
#: garde de corpus, à sa première exécution — sur la phrase même qui présentait la syntaxe.
#: Le code est capturé EN PREMIER (groupe 1) et rendu tel quel ; seul ce qui reste est une balise.
_CODE_OU_TAG = re.compile(r'((?s:```.*?```)|`[^`\n]*`)|' + TAG.pattern)

#: Le registre des registres : il n'est pas une entrée de `REGISTRIES`, il EST leur liste.
META = 'registres'


class FactError(ValueError):
    """Une balise qui ne se résout pas — cassée, pas approximée."""


def _as_dict(fiche) -> dict:
    if isinstance(fiche, dict):
        return fiche
    if dataclasses.is_dataclass(fiche):
        return {f.name: getattr(fiche, f.name) for f in dataclasses.fields(fiche)}
    raise FactError(f"fiche de type {type(fiche).__name__} : ni dict ni dataclass")


def entries(registre: str) -> Dict[str, dict]:
    """Les fiches d'un registre, par clé."""
    from .registries import REGISTRIES, overview
    if registre == META:
        return {r['key']: r for r in overview()}
    r = REGISTRIES.get(registre)
    if r is None:
        raise FactError(f"registre « {registre} » inconnu")
    if r.entries is None:
        raise FactError(f"le registre « {registre} » ne déclare pas ses fiches "
                        f"(`Registry.entries`) — il peut être compté, pas cité")
    return {str(k): _as_dict(v) for k, v in r.entries().items()}


def _count(registre: str) -> int:
    from .registries import REGISTRIES
    if registre == META:
        return len(REGISTRIES)
    r = REGISTRIES.get(registre)
    if r is None:
        raise FactError(f"registre « {registre} » inconnu")
    if r.entries is not None:
        return len(r.entries())
    if r.count is not None:
        return int(r.count())
    raise FactError(f"le registre « {registre} » ne sait ni se compter ni lister ses fiches")


def render_value(valeur) -> str:
    """Une VALEUR en texte d'une ligne. Une structure (dict) est refusée : une balise cite une
    valeur, elle ne sérialise pas une fiche."""
    if valeur is None:
        return '—'
    if isinstance(valeur, bool):
        return 'oui' if valeur else 'non'
    if isinstance(valeur, (int, float, str)):
        return ' '.join(str(valeur).split())
    if isinstance(valeur, (list, tuple, set, frozenset)):
        items = sorted(valeur) if isinstance(valeur, (set, frozenset)) else list(valeur)
        if all(isinstance(v, (int, float, str)) for v in items):
            return ', '.join(str(v) for v in items)
    raise FactError("champ non scalaire — une balise vise une VALEUR, pas une structure")


def resolve(chemin: str) -> str:
    """La valeur ACTUELLE que désigne un chemin de balise."""
    parties = chemin.strip('/').split('/')
    if len(parties) == 1:
        return str(_count(parties[0]))
    if len(parties) != 3:
        raise FactError(f"chemin « {chemin} » : attendu `<registre>` ou "
                        f"`<registre>/<clé>/<champ>`")
    registre, cle, champ = parties
    fiches = entries(registre)
    if cle not in fiches:
        raise FactError(f"clé « {cle} » absente du registre « {registre} »")
    fiche = fiches[cle]
    if champ not in fiche:
        raise FactError(f"champ « {champ} » absent de la fiche {registre}/{cle}")
    return render_value(fiche[champ])


def refresh_text(texte: str) -> Tuple[str, int, List[Tuple[str, str]]]:
    """Régénère toutes les balises d'un texte : `(texte neuf, nombre de balises, erreurs)`.

    Une balise cassée garde sa valeur ACTUELLE dans le texte et remonte dans les erreurs : on
    ne réécrit jamais une valeur qu'on n'a pas su calculer.
    """
    erreurs: List[Tuple[str, str]] = []
    valeurs: Dict[str, str] = {}
    compte = 0

    def _remplacer(m):
        nonlocal compte
        if m.group(1):                  # du CODE : une balise citée, pas résolue
            return m.group(0)
        compte += 1
        chemin = m.group(2)
        if chemin not in valeurs:
            try:
                valeurs[chemin] = resolve(chemin)
            except FactError as e:
                erreurs.append((chemin, str(e)))
                return m.group(0)
        return f"<!-- WAMA:FAIT({chemin}) -->{valeurs[chemin]}<!-- /WAMA:FAIT -->"

    return _CODE_OU_TAG.sub(_remplacer, texte), compte, erreurs
