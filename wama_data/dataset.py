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

    manifeste `dataset` → référentiel → `View` → fonctions du catalogue → `Declaration` d'export

⚠ LA DOCTRINE QUI COMMANDE TOUT CE FICHIER (§9bis, avis critique consigné) :

    « Le LLM propose, la machine dispose. Un manifeste généré par LLM qui VALIDE ensuite l'import
      est CIRCULAIRE. Le manifeste déclare des attentes **vérifiables mécaniquement** et
      l'importer **MESURE L'ÉCART**. »

D'où deux conséquences qui ne sont pas des détails :

  ① **On ne rend jamais un référentiel seul.** `load()` rend le couple `(référentiel, écart)`.
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
# ⚠ `load` de sources est ALIASÉ : ce module expose SA PROPRE `load()` (charger un dataset
# déclaré), qui délègue à celle des sources (charger UN fichier) — deux étages, deux fonctions.
from .sources import READERS, load as load_source, probe, reader_for


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. L'ÉCART — ce que le manifeste DÉCLARE vs ce que la source CONTIENT
# ══════════════════════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Discrepancy:
    """Le compte-rendu de confrontation. `compliant` ne veut PAS dire « rien à signaler » —
    il veut dire « aucun signal déclaré ne manque ». Les autres constats restent lisibles."""

    missing: Tuple[str, ...] = ()
    undeclared: Tuple[str, ...] = ()
    #: Format du lecteur qui a RÉELLEMENT ouvert la source — INFORMATIF, jamais un écart.
    #:
    #: ⚠ CORRECTION DE MA PROPRE VEILLE (2026-08-24). Ce champ comparait `source.type` au format
    #: du lecteur et rapportait la différence comme une divergence « garde-fou G1 ». **C'était une
    #: erreur de catégorie** : `source.type` dit d'où la donnée VIENT (provenance : rtmaps, lsl,
    #: csv, db…), le format du lecteur dit QUI SAIT L'OUVRIR (capacité : trip, tabular). Le kind
    #: `dataset` le dit lui-même en toutes lettres — le chantier attendu était « un **reader
    #: source-agnostique** ». Les deux vocabulaires sont donc **volontairement indépendants**, et
    #: `reader_for()` ne consulte jamais `source.type`.
    #:
    #: Conséquence mesurée : la « divergence » se déclenchait sur **tout manifeste valide**. Un
    #: contrôle qui sonne toujours n'est pas un contrôle — il apprend à ignorer le compte-rendu.
    #: Le champ est conservé parce que savoir QUI a lu est utile ; il n'est plus un verdict.
    reader: str = ''
    notes: Tuple[str, ...] = ()

    #: Coordonnées d'AXES retrouvées dans la source, en paires `(clé d'axe, valeur)`.
    #:
    #: ⭐ Mesuré le 2026-08-26 sur un `.trip` réel (§13.15) : le fichier de 2019 portait déjà
    #: `('scenario', 'Test')` et `('participant_id', 'Passation_01')` dans `MetaTripDatas`. Le
    #: rangement n'est donc pas une convention à instaurer — c'est une pratique à RECONNAÎTRE.
    coordinates: Tuple[Tuple[str, str], ...] = ()

    #: Axes déclarés dont aucune coordonnée n'a été trouvée dans la source.
    #:
    #: ⚠ **INFORMATIF, jamais un verdict** — et c'est délibéré. Tous les axes ne sont pas des
    #: coordonnées de conteneur : `participant` ou `scenario` valent pour tout le fichier, mais une
    #: fenêtre d'analyse indexe des LIGNES à l'intérieur. Faire échouer la conformité sur son
    #: absence ferait sonner le contrôle sur tout manifeste correct — le défaut déjà corrigé sur
    #: `reader` ci-dessus, et « un contrôle qui sonne toujours n'est pas un contrôle ».
    axes_without_coordinate: Tuple[str, ...] = ()

    @property
    def compliant(self) -> bool:
        """Vrai quand tout ce que le manifeste PROMET est présent.

        Un flux non déclaré ne rend pas l'écart non conforme : une source peut contenir plus que
        ce qu'on a choisi d'en décrire, et c'est légitime. Le manquant, lui, est une promesse non
        tenue — c'est la seule asymétrie qui compte.
        """
        return not self.missing

    def render(self) -> str:
        """Compte-rendu lisible — destiné à être MONTRÉ, pas seulement testé."""
        parts: List[str] = []
        if self.missing:
            parts.append(f"{len(self.missing)} signal(aux) déclaré(s) ABSENT(s) de la source : "
                         + ', '.join(self.missing))
        if self.undeclared:
            parts.append(f"{len(self.undeclared)} flux présent(s) non déclaré(s) : "
                         + ', '.join(self.undeclared))
        if self.coordinates:
            parts.append("axes situés : "
                         + ', '.join(f"{k}={v}" for k, v in self.coordinates))
        if self.axes_without_coordinate:
            parts.append(f"{len(self.axes_without_coordinate)} axe(s) sans coordonnée dans la "
                         f"source : " + ', '.join(self.axes_without_coordinate))
        parts.extend(self.notes)
        if not parts:
            read_by = f" (lue par « {self.reader} »)" if self.reader else ''
            return f"conforme — rien à signaler{read_by}"
        return ' · '.join(parts)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. Lecture du manifeste
# ══════════════════════════════════════════════════════════════════════════════════════════════

def path(body: Mapping[str, Any], root: Optional[Any] = None) -> Path:
    """`source.ref` résolu. Relatif, il se résout sous `root` — jamais sous le cwd.

    Un manifeste doit être rejouable ailleurs : le faire dépendre du répertoire courant le rendrait
    valide sur une machine et faux sur une autre, sans que rien ne le dise.
    """
    src = body.get('source')
    if not isinstance(src, Mapping) or not src.get('ref'):
        raise ValueError("manifeste `dataset` sans `source.ref` — rien à ouvrir")
    p = Path(str(src['ref']))
    if not p.is_absolute() and root is not None:
        p = Path(root) / p
    return p


def declared_signals(body: Mapping[str, Any]) -> List[str]:
    """Identifiants des signaux déclarés, dans l'ordre du manifeste."""
    out: List[str] = []
    for s in (body.get('signals') or []):
        if isinstance(s, Mapping) and s.get('id'):
            out.append(str(s['id']))
    return out


def declared_axes(body: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Les axes du plan d'expérience déclarés, dans l'ordre du manifeste (`WAMA_DATA_WORLD §13`)."""
    return [a for a in (body.get('axes') or []) if isinstance(a, Mapping) and a.get('key')]


#: Préfixe CANONIQUE d'une coordonnée d'axe dans le catalogue d'un conteneur (`WamaMeta`,
#: `MetaTripDatas`). Il existe parce que `WamaMeta` est un espace PARTAGÉ : il porte déjà des métas
#: techniques (`format`, `schema_version`, `created_at`), et une clé `participant` posée à plat y
#: côtoierait une clé de format. La fusion des deux tables de `.trip` en une seule (`§9duodecies.3`)
#: rend donc le préfixe **nécessaire**, pas optionnel — c'est la réponse à D21.
AXIS_PREFIX = 'axe.'


def coordinate_attributes(coordinates: Mapping[str, Any]) -> Dict[str, str]:
    """Coordonnées d'axes → attributs de conteneur, sous la forme canonique `axe.<clé>`.

    Destiné à `Context.attributes` (`containers/`), qui les écrit telles quelles dans `WamaMeta`.
    C'est le pendant **écriture** de `locate()`, et le couple ferme l'aller-retour : ce que WAMA
    écrit, `locate()` le retrouve par sa première graphie.

    ⭐ Pourquoi écrire les coordonnées DANS le conteneur plutôt que de les déduire du chemin : elles
    **survivent au déplacement du fichier**. Un `.wdat` sorti de son arborescence continue de dire
    de quelle passation et de quel scénario il vient. C'est déjà ce que faisait l'outil d'origine
    (§13.15 : `MetaTripDatas` porte `scenario` et `participant_id` depuis 2019) — on ne l'invente
    pas, on le rend systématique.
    """
    return {f'{AXIS_PREFIX}{k}': ('' if v is None else str(v))
            for k, v in coordinates.items()}


def locate(axes: Sequence[Mapping[str, Any]],
           attributes: Mapping[str, Any]) -> Tuple[Dict[str, str], List[str]]:
    """Retrouve, pour chaque axe déclaré, sa coordonnée dans les attributs de la source.

    ⭐ **TROIS graphies sont acceptées, et ce n'est pas de la complaisance** — c'est le relevé du
    §13.15 : un `.trip` de 2019 range déjà ses coordonnées dans `MetaTripDatas`, **sans préfixe**
    (`scenario`, `participant_id`). Notre `axe.<clé>` est donc un CHANGEMENT de convention ; ne
    lire que lui reviendrait à cesser de reconnaître les corpus existants. Même geste que
    `timecode`, alias d'entrée de `time` depuis toujours.

    Ordre de résolution :
      1. `axe.<clé>`      — convention WAMA ;
      2. `<clé>`          — convention de l'outil d'origine ;
      3. `source_key`     — alias déclaré par l'axe, quand le nom diverge franchement
                            (mesuré : l'axe `passation` se range sous `participant_id`).

    Rend `(coordonnées trouvées, clés d'axes sans coordonnée)`.
    """
    found: Dict[str, str] = {}
    absent: List[str] = []
    for a in axes:
        key = str(a['key'])
        for candidate in (f'{AXIS_PREFIX}{key}', key, a.get('source_key')):
            if candidate and candidate in attributes:
                found[key] = str(attributes[candidate])
                break
        else:
            absent.append(key)
    return found, absent


def verify(body: Mapping[str, Any], root: Optional[Any] = None) -> Discrepancy:
    """Confronte le manifeste à la source **SANS la charger** (`probe` seul).

    C'est le contrat `verify` du §9bis : on peut dire ce qui cloche avant de payer la lecture —
    et sur une base de 1,28 Go, cette différence-là compte.
    """
    p = path(body, root)
    if not p.exists():
        return Discrepancy(missing=tuple(declared_signals(body)),
                     notes=(f"source introuvable : {p}",))

    reader = reader_for(p)
    if reader is None:
        return Discrepancy(missing=tuple(declared_signals(body)),
                     notes=(f"aucun lecteur pour '{p.name}' "
                            f"(formats enregistrés : {', '.join(sorted(READERS)) or '—'})",))

    info = probe(p)
    present = set(info.streams)
    declared = declared_signals(body)
    coords, without = locate(declared_axes(body), info.attributes or {})
    missing = tuple(s for s in declared if s not in present)

    return Discrepancy(
        missing=missing,
        undeclared=tuple(sorted(present - set(declared))),
        coordinates=tuple(sorted(coords.items())),
        axes_without_coordinate=tuple(without),
        reader=reader.format,
        notes=_prefix_hint(missing, present),
    )


def _prefix_hint(missing: Sequence[str], present: set) -> Tuple[str, ...]:
    """Quand TOUT est déclaré absent, dire POURQUOI plutôt que laisser deviner.

    ⚠ DÉFAUT RÉEL, mesuré le 2026-08-26 en confrontant le premier manifeste écrit à la main à un
    `.trip` réel (`WAMA_DATA_WORLD §13.15`) : le lecteur `.trip` **n'emploie pas le même
    identifiant pour DEMANDER un flux et pour le RENDRE**. `probe()` liste des noms de TABLE
    (`data_BIOPAC_MP150`), `read()` rend des signaux au nom du CATALOGUE (`BIOPAC_MP150`), et
    `load(streams=['CADISP'])` lève `n'est pas un flux reconnu` là où `['event_CADISP']` passe.

    Un auteur de manifeste lit le catalogue — il écrira donc systématiquement la mauvaise forme, et
    l'écart annoncerait « 15 signaux absents » sur un fichier qui les contient tous. Le pire cas
    n'est pas la perte, c'est la perte SILENCIEUSE : on nomme la cause. Le fond est ouvert (D31) ;
    ceci ne le tranche pas, il rend le symptôme lisible.
    """
    if not missing or not present:
        return ()
    families = ('data_', 'event_', 'situation_')
    covered = [m for m in missing if any(f + m in present for f in families)]
    if len(covered) != len(missing):
        return ()
    return (f"⚠ les {len(missing)} signaux déclarés existent dans la source SOUS UN NOM PRÉFIXÉ "
            f"(ex. « {covered[0]} » → « "
            + next(f + covered[0] for f in families if f + covered[0] in present)
            + " ») — nom de catalogue vs nom de table, voir D31",)


def load(body: Mapping[str, Any], root: Optional[Any] = None, *,
            strict: bool = False, name: str = '',
            timestampers: Optional[Dict[str, Any]] = None
            ) -> Tuple[TemporalReferential, Discrepancy]:
    """Ouvre le jeu déclaré et rend **le référentiel ET l'écart**.

    ⚠ LE COUPLE EST VOULU (① en tête) : on ne peut pas obtenir le référentiel sans recevoir aussi
    la confrontation. Ignorer l'écart devient un geste délibéré.

    Seuls les signaux DÉCLARÉS sont chargés — un manifeste qui n'en décrit que trois n'a pas à
    payer la lecture des dix autres.

    ⚠ **Cette docstring affirmait « `signals` vide est refusé par la validation du kind, donc ne
    peut pas arriver ici ». C'est devenu FAUX le 2026-08-26** : `signals` est désormais facultatif
    dès que `axes` est présent, pour admettre un corpus de questionnaires sans aucun flux temporel
    (`WAMA_DATA_WORLD §13.10`). Le cas arrive donc, et il est **sûr** — vérifié, pas supposé :
    `streams=[]` fait lire **zéro** flux (`trip.py` : `voulus = list(streams) if streams is not
    None else info.streams`), là où `None` les lirait tous. Un corpus sans signal rend un
    référentiel vide, ce qui est exactement ce qu'il décrit.
    *(Rappel de la leçon : un assouplissement ne casse rien — il rend FAUX ce qui le documentait.)*

    `strict=True` refuse dès qu'une promesse n'est pas tenue. Le défaut est `False` : un corpus
    réel est hétérogène, et refuser une passation partielle rendrait le manifeste inutilisable.
    """
    discrepancy = verify(body, root)
    if strict and not discrepancy.compliant:
        raise ValueError(f"manifeste `dataset` non tenu par la source — {discrepancy.render()}")
    if discrepancy.notes:                      # source introuvable / aucun lecteur : rien à charger
        raise ValueError(f"impossible d'ouvrir le jeu déclaré — {discrepancy.render()}")

    p = path(body, root)
    requested = [s for s in declared_signals(body) if s not in discrepancy.missing]
    ref = load_source(p, streams=requested, timestampers=timestampers, name=name or p.stem)
    return ref, discrepancy
