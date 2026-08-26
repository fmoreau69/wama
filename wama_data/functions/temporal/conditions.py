"""
Déclaration au catalogue de la CHAÎNE CONDITIONNELLE (implémentation : `wama_data/core/conditions.py`).

Aucune logique de comparaison ici — des adaptateurs de ports, comme pour le Segmenter et le
Calculator. Mais cet adaptateur porte une responsabilité que les deux autres n'ont pas, et c'est la
raison d'être du fichier :

    ⚠ C'EST ICI QUE LA SORTE D'UNE COLONNE EST DÉTERMINÉE.

Le cœur (`core/conditions.py`) reçoit la sorte comme une donnée d'entrée : il est pur, il ne
connaît pas pandas. La déduire depuis un `dtype` est un travail de frontière, donc le sien à lui.

⚠ ET ELLE N'EST PAS DÉCLARÉE PAR L'UTILISATEUR — elle est LUE DANS LA DONNÉE. C'est ce qui fait la
différence avec un simple champ de plus dans la déclaration : si la sorte était saisie, se tromper
en la saisissant rétablirait exactement le défaut qu'on corrige (`<` appliqué à du texte, cf. ③ en
tête de `core/conditions.py`). Lue dans la colonne, elle ne peut pas mentir sur la colonne.

⚠ `data_types.py` NE TYPE PAS LES COLONNES. Il type le CADRE (`TypedFrame.data_type`) et
`TypedFrame` n'expose que `.fields`, une liste de NOMS. La phrase de `WAMA_DATA_WORLD §9ter.6 B3`
— « WAMA a déjà `data_types.py` pour savoir de quel type est une colonne : la vérification est
gratuite, il suffit de la brancher » — est donc fausse. Elle n'est pas gratuite : elle coûte
exactement `sorte_de_colonne()` ci-dessous, et il fallait l'écrire.

FORME DE LA DÉCLARATION. Les conditions circulent en JSON parce qu'un `ParamSpec` ne porte que des
scalaires (`float|int|bool|enum|str`). Ce n'est pas un contournement : la déclaration EST un objet
sérialisable (§9ter.6 B1), et le JSON en est la sérialisation. ⚠ Aucun rendu d'interface ne lit
encore ce type — la modale de réglages des fonctions-cartes annoncée par `function_catalog.py:30`
n'existe pas. Le type `'json'` déclaré ici est donc honnête et INERTE : il dit ce que le champ
contient, il ne le fait pas encore afficher.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionCategory, FunctionSpec, ParamSpec,
                                                  PortSpec, register)
from ...core.conditions import (BOOLEEN, NUMERIQUE, TEXTE, Condition, analyser, evaluer,
                                nom_chaine, operateurs_pour)
from ...core.segmentation import bascules, conditionnelle
from .segmentation import CHAMPS_SEGMENT, _colonne, _segments

#: Champs produits par une bascule — `time` vient de la taxonomie, le reste est la traçabilité.
CHAMPS_BASCULE = CANONICAL_FIELDS[DataType.EVENTS] + ['edge', 'name', 'origin']


def sorte_de_colonne(frame: TypedFrame, champ: str) -> str:
    """Sorte d'une colonne, LUE dans la donnée — numérique, texte ou booléen.

    L'ordre des tests n'est pas indifférent : en pandas, `bool` est un sous-type de `number`, donc
    tester le booléen d'abord est la seule façon de ne pas voir une colonne de vrai/faux comme
    numérique — et de ne pas lui proposer `>=`, qui n'y veut rien dire.

    Le repli est TEXTE, jamais numérique. Une colonne `object` mêlant nombres et chaînes (le cas
    ordinaire d'un CSV mal typé) doit se voir proposer `contient`, pas `<` : c'est le repli qui
    refuse le plus, donc celui qui ne laisse pas passer une comparaison silencieusement fausse.
    """
    import pandas as pd
    try:
        serie = frame.df[champ]
    except Exception:
        raise ValueError(
            f"colonne '{champ}' absente (disponibles : {', '.join(frame.fields) or '—'})")
    if pd.api.types.is_bool_dtype(serie):
        return BOOLEEN
    if pd.api.types.is_numeric_dtype(serie):
        return NUMERIQUE
    return TEXTE


def _conditions(frame: TypedFrame, declaration: str) -> List[Condition]:
    """Construit les `Condition` déclarées, en LEUR IMPOSANT la sorte lue dans le cadre.

    Une `sorte` présente dans le JSON est IGNORÉE — délibérément. L'accepter permettrait à une
    déclaration de se contredire avec la donnée qu'elle décrit, et c'est la donnée qui a raison.
    """
    try:
        brut = json.loads(declaration) if isinstance(declaration, str) else declaration
    except (TypeError, ValueError) as e:
        raise ValueError(f"déclaration de conditions illisible (JSON attendu) : {e}")
    if not isinstance(brut, list) or not brut:
        raise ValueError("déclarer au moins une condition, sous forme de liste JSON — "
                         '[{"key": "C1", "field": "vitesse", "operator": ">=", "value": 30}]')

    out: List[Condition] = []
    for i, item in enumerate(brut):
        if not isinstance(item, dict):
            raise ValueError(f"condition n°{i + 1} : objet attendu, reçu {item!r}")
        champ = item.get('field', '')
        cle = item.get('key') or f"C{i + 1}"
        sorte = sorte_de_colonne(frame, champ)
        out.append(Condition(cle=cle, champ=champ, operator=item.get('operator', ''),
                             valeur=item.get('value'), flux=item.get('stream', ''),
                             sorte=sorte))
    cles = [c.cle for c in out]
    doublons = sorted({c for c in cles if cles.count(c) > 1})
    if doublons:
        raise ValueError(f"clés de condition en double ({', '.join(doublons)}) — l'arbre logique "
                         "ne pourrait pas les distinguer")
    return out


def _masque(signal: TypedFrame, conditions: str, connectors: str) -> tuple:
    """Le masque booléen d'une chaîne, et le nom dérivé qui va avec.

    C'est LE point de passage commun aux deux ports de sortie (§9ter.6 B4) : segments et
    événements consomment le même masque, calculé une fois ici.
    """
    decl = _conditions(signal, conditions)
    masques = {c.cle: c.evaluer(_colonne(signal, c.champ)) for c in decl}
    texte = (connectors or '').strip()
    if not texte:
        # Une seule condition n'a pas besoin d'arbre ; plusieurs, si — sans quoi on choisirait
        # un connecteur implicite à leur place, et « ET » n'est pas plus évident que « OU ».
        if len(decl) > 1:
            raise ValueError(
                f"{len(decl)} conditions déclarées mais aucun connecteur — préciser leur "
                f"assemblage, par exemple ET({', '.join(c.cle for c in decl)})")
        arbre = decl[0].cle
    else:
        arbre = analyser(texte, list(masques))
    return evaluer(arbre, masques), nom_chaine(arbre)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Les DEUX ports de sortie du même masque
# ══════════════════════════════════════════════════════════════════════════════════════════════

def chain_to_segments(signal: TypedFrame, conditions: str = '', connectors: str = '',
                         min_duration: float = 0.0, gap_tolerance: float = 0.0,
                         name: str = '') -> TypedFrame:
    """Plages où la chaîne conditionnelle est vraie, avec hystérésis."""
    masque, derive = _masque(signal, conditions, connectors)
    return _segments(conditionnelle(_colonne(signal, 'time'), masque, min_duration=min_duration,
                                    gap_tolerance=gap_tolerance, name=name or derive),
                     meta=signal.meta)


def chain_to_events(signal: TypedFrame, conditions: str = '', connectors: str = '',
                       rising: bool = True, falling: bool = False,
                       name: str = '') -> TypedFrame:
    """Instants où la chaîne conditionnelle BASCULE."""
    import pandas as pd
    masque, derive = _masque(signal, conditions, connectors)
    rows = bascules(_colonne(signal, 'time'), masque, rising=rising,
                    falling=falling, name=name or derive)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=CHAMPS_BASCULE)
    return TypedFrame(df, DataType.EVENTS, meta=signal.meta)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Déclarations
# ══════════════════════════════════════════════════════════════════════════════════════════════

_ENTREE = PortSpec('signal', DataType.TIMESERIES, required_fields=['time'],
                   description="Signal portant les colonnes testées par les conditions.")

_AIDE_CONDITIONS = (
    'Liste JSON de conditions — [{"key": "C1", "field": "vitesse", "operator": ">=", '
    '"value": 30}]. La SORTE de la colonne (numérique / texte / booléen) est LUE dans la donnée, '
    'jamais déclarée : un opérateur qui ne lui convient pas est refusé à la déclaration. '
    'Opérateurs numériques : ' + ', '.join(operateurs_pour(NUMERIQUE)) + '. '
    'Opérateurs texte : ' + ', '.join(operateurs_pour(TEXTE)) + '.')

_AIDE_CONNECTEURS = (
    "Assemblage logique en forme préfixe — ET(C1, C2), NON(C1), OU(C1, ET(C2, C3)). "
    "ET et OU acceptent 2 arguments ou plus ; XOR en prend exactement 2 ; NON, un seul. "
    "Facultatif s'il n'y a qu'une condition. Le texte est une SAISIE : il est converti en arbre "
    "et c'est l'arbre qui est conservé, si bien que deux saisies équivalentes se comparent.")

register(FunctionSpec(
    key='segment_condition_chain',
    name="Segments par chaîne de conditions",
    description="Plages où PLUSIEURS conditions assemblées par ET / OU / XOR / NON sont "
                "satisfaites, avec hystérésis. Généralise « Segments par condition », qui n'en "
                "accepte qu'une seule et sur une colonne numérique. Les opérateurs de texte "
                "(contient, commence par…) y sont disponibles, et un opérateur inadapté à la "
                "sorte de la colonne est refusé AVANT exécution plutôt que de rendre un masque "
                "plausible et faux.",
    category=FunctionCategory.DETECTOR,
    tags=['temporel', 'segmentation', 'conditionnel'],
    inputs=[_ENTREE],
    outputs=[PortSpec('segments', DataType.SEGMENTS, produced_fields=CHAMPS_SEGMENT,
                      description="Plages satisfaisant la chaîne — origine tracée.")],
    params=[
        ParamSpec('conditions', 'json', '', description=_AIDE_CONDITIONS),
        ParamSpec('connectors', 'str', '', description=_AIDE_CONNECTEURS),
        ParamSpec('min_duration', 'float', 0.0, 0.0, unit='s',
                  description="Durée minimale d'une plage retenue."),
        ParamSpec('gap_tolerance', 'float', 0.0, 0.0, unit='s',
                  description="Interruption recollée au lieu de couper la plage."),
        ParamSpec('name', 'str', '',
                  description="Préfixe des segments. Vide : dérivé de l'arbre (« et_c1_c2 »)."),
    ],
    cost={'cpu_bound': True},
    fn=chain_to_segments,
))

register(FunctionSpec(
    key='event_condition_chain',
    name="Événements aux bascules d'une chaîne de conditions",
    description="Instants où la chaîne change d'état, montantes et/ou descendantes. C'est le "
                "SECOND port de sortie du même masque : « que créer, un événement ou une "
                "situation ? » n'est pas un mode de segmentation mais un choix de sortie, donc "
                "deux fonctions chaînables plutôt qu'un bouton radio au milieu du geste. Une "
                "chaîne déjà vraie au premier échantillon ne produit pas de bascule montante — "
                "la transition n'a pas été observée.",
    category=FunctionCategory.DETECTOR,
    tags=['temporel', 'segmentation', 'conditionnel', 'evenement'],
    inputs=[_ENTREE],
    outputs=[PortSpec('events', DataType.EVENTS, produced_fields=CHAMPS_BASCULE,
                      description="Instants de bascule — `edge` dit le sens.")],
    params=[
        ParamSpec('conditions', 'json', '', description=_AIDE_CONDITIONS),
        ParamSpec('connectors', 'str', '', description=_AIDE_CONNECTEURS),
        ParamSpec('rising', 'bool', True,
                  description="Retenir les passages faux → vrai."),
        ParamSpec('falling', 'bool', False,
                  description="Retenir les passages vrai → faux."),
        ParamSpec('name', 'str', ''),
    ],
    cost={'cpu_bound': True},
    fn=chain_to_events,
))
