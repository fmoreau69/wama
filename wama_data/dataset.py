"""
Le manifeste `dataset` devient EXÉCUTABLE — et l'importer MESURE L'ÉCART.

⚠ POURQUOI CE MODULE (mesuré le 2026-08-23/24). Le kind `dataset` existe depuis longtemps, se
valide, et déclare tout ce qu'il faut — `source {type, ref}`, `signals` typés, `reference_tables`,
`records`. Il porte même `extract=None` avec la mention « **AUTORÉ — le manifeste est l'origine** ».
Mais **rien ne le consommait** : zéro référence hors de son propre module, zéro manifeste `dataset`
au corpus (`manifests/` ne contient que `apps`, `libraries`, `models`).

Autrement dit : la déclaration de « quel jeu de données j'ouvre » existait, et **on ne savait pas
l'ouvrir**. Même forme de trou que le Référentiel sans consommateur (§9quater.7) — une pièce
déclarée, complète, et débranchée.

Avec ce module, la chaîne devient exécutable **de bout en bout depuis des déclarations** :

    manifeste `dataset` → référentiel → `Vue` → fonctions du catalogue → `Declaration` d'export

⚠ LA DOCTRINE QUI COMMANDE TOUT CE FICHIER (§9bis, avis critique consigné) :

    « Le LLM propose, la machine dispose. Un manifeste généré par LLM qui VALIDE ensuite l'import
      est CIRCULAIRE. Le manifeste déclare des attentes **vérifiables mécaniquement** et
      l'importer **MESURE L'ÉCART**. »

D'où deux conséquences qui ne sont pas des détails :

  ① **On ne rend jamais un référentiel seul.** `charger()` rend le couple `(référentiel, écart)`.
     Ignorer l'écart devient alors un geste délibéré — on ne peut pas l'oublier par distraction,
     ce qui serait le cas s'il fallait penser à appeler une seconde fonction.

  ② **Un écart n'est pas une erreur par défaut.** Un corpus réel est hétérogène : refuser de
     charger parce qu'un signal déclaré manque rendrait le manifeste inutilisable sur une
     passation partielle — exactement la rigidité qu'on combat. On charge ce qui est là, on
     RAPPORTE ce qui diverge, et `strict=True` reste disponible pour qui veut la barrière.

⚠ CE QUE CE MODULE NE PEUT PAS VÉRIFIER, ET NE PRÉTEND PAS VÉRIFIER : le `data_type` déclaré de
chaque signal. `SourceInfo` rend des NOMS de flux (`streams`), pas leurs types — et le type ne
s'observe qu'après chargement, où il reste partiel (un `Signal` ne porte pas sa famille
données/événements, cf. `frames.py`). Annoncer une vérification de type serait promettre ce que la
mesure ne donne pas ; le trou est nommé plutôt que comblé en apparence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .core.temporal import TemporalReferential
from .sources import READERS, load, probe, reader_for


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. L'ÉCART — ce que le manifeste DÉCLARE vs ce que la source CONTIENT
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Ecart:
    """Le compte-rendu de confrontation. `conforme` ne veut PAS dire « rien à signaler » —
    il veut dire « aucun signal déclaré ne manque ». Les autres constats restent lisibles."""

    manquants: Tuple[str, ...] = ()
    non_declares: Tuple[str, ...] = ()
    #: `(type déclaré, format du lecteur qui a réellement lu)` quand les deux vocabulaires
    #: ne se recouvrent pas — c'est le garde-fou **G1**, rendu MESURABLE (voir §9octies).
    type_source: Optional[Tuple[str, str]] = None
    notes: Tuple[str, ...] = ()

    @property
    def conforme(self) -> bool:
        """Vrai quand tout ce que le manifeste PROMET est présent.

        Un flux non déclaré ne rend pas l'écart non conforme : une source peut contenir plus que
        ce qu'on a choisi d'en décrire, et c'est légitime. Le manquant, lui, est une promesse non
        tenue — c'est la seule asymétrie qui compte.
        """
        return not self.manquants

    def rendre(self) -> str:
        """Compte-rendu lisible — destiné à être MONTRÉ, pas seulement testé."""
        bouts: List[str] = []
        if self.manquants:
            bouts.append(f"{len(self.manquants)} signal(aux) déclaré(s) ABSENT(s) de la source : "
                         + ', '.join(self.manquants))
        if self.non_declares:
            bouts.append(f"{len(self.non_declares)} flux présent(s) non déclaré(s) : "
                         + ', '.join(self.non_declares))
        if self.type_source:
            declare, lu = self.type_source
            bouts.append(f"source.type déclaré « {declare} », lue par le lecteur « {lu} » — "
                         "les deux vocabulaires ne sont pas réconciliés (garde-fou G1)")
        bouts.extend(self.notes)
        return ' · '.join(bouts) if bouts else 'conforme — rien à signaler'


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. Lecture du manifeste
# ══════════════════════════════════════════════════════════════════════════════════════════════

def chemin(body: Mapping[str, Any], racine: Optional[Any] = None) -> Path:
    """`source.ref` résolu. Relatif, il se résout sous `racine` — jamais sous le cwd.

    Un manifeste doit être rejouable ailleurs : le faire dépendre du répertoire courant le rendrait
    valide sur une machine et faux sur une autre, sans que rien ne le dise.
    """
    src = body.get('source')
    if not isinstance(src, Mapping) or not src.get('ref'):
        raise ValueError("manifeste `dataset` sans `source.ref` — rien à ouvrir")
    p = Path(str(src['ref']))
    if not p.is_absolute() and racine is not None:
        p = Path(racine) / p
    return p


def signaux_declares(body: Mapping[str, Any]) -> List[str]:
    """Identifiants des signaux déclarés, dans l'ordre du manifeste."""
    out: List[str] = []
    for s in (body.get('signals') or []):
        if isinstance(s, Mapping) and s.get('id'):
            out.append(str(s['id']))
    return out


def verifier(body: Mapping[str, Any], racine: Optional[Any] = None) -> Ecart:
    """Confronte le manifeste à la source **SANS la charger** (`probe` seul).

    C'est le contrat `verify` du §9bis : on peut dire ce qui cloche avant de payer la lecture —
    et sur une base de 1,28 Go, cette différence-là compte.
    """
    p = chemin(body, racine)
    if not p.exists():
        return Ecart(manquants=tuple(signaux_declares(body)),
                     notes=(f"source introuvable : {p}",))

    lecteur = reader_for(p)
    if lecteur is None:
        return Ecart(manquants=tuple(signaux_declares(body)),
                     notes=(f"aucun lecteur pour '{p.name}' "
                            f"(formats enregistrés : {', '.join(sorted(READERS)) or '—'})",))

    info = probe(p)
    presents = set(info.streams)
    declares = signaux_declares(body)

    type_declare = str((body.get('source') or {}).get('type') or '')
    divergence = None
    if type_declare and type_declare != lecteur.format:
        divergence = (type_declare, lecteur.format)

    return Ecart(
        manquants=tuple(s for s in declares if s not in presents),
        non_declares=tuple(sorted(presents - set(declares))),
        type_source=divergence,
    )


def charger(body: Mapping[str, Any], racine: Optional[Any] = None, *,
            strict: bool = False, nom: str = '',
            timestampers: Optional[Dict[str, Any]] = None
            ) -> Tuple[TemporalReferential, Ecart]:
    """Ouvre le jeu déclaré et rend **le référentiel ET l'écart**.

    ⚠ LE COUPLE EST VOULU (① en tête) : on ne peut pas obtenir le référentiel sans recevoir aussi
    la confrontation. Ignorer l'écart devient un geste délibéré.

    Seuls les signaux DÉCLARÉS sont chargés — un manifeste qui n'en décrit que trois n'a pas à
    payer la lecture des dix autres. Aucun signal déclaré (`signals` vide) est refusé par la
    validation du kind, donc ne peut pas arriver ici.

    `strict=True` refuse dès qu'une promesse n'est pas tenue. Le défaut est `False` : un corpus
    réel est hétérogène, et refuser une passation partielle rendrait le manifeste inutilisable.
    """
    ecart = verifier(body, racine)
    if strict and not ecart.conforme:
        raise ValueError(f"manifeste `dataset` non tenu par la source — {ecart.rendre()}")
    if ecart.notes:                      # source introuvable / aucun lecteur : rien à charger
        raise ValueError(f"impossible d'ouvrir le jeu déclaré — {ecart.rendre()}")

    p = chemin(body, racine)
    demandes = [s for s in signaux_declares(body) if s not in ecart.manquants]
    ref = load(p, streams=demandes, timestampers=timestampers, name=nom or p.stem)
    return ref, ecart
