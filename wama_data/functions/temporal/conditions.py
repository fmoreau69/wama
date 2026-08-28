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
exactement `column_kind()` ci-dessous, et il fallait l'écrire.

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
from ...core.conditions import (BOOLEAN, NUMERIC, TEXT, Condition, parse, evaluate,
                                chain_name, operators_for)
from ...core.segmentation import edges, conditional
from .segmentation import CHAMPS_SEGMENT, _colonne, _fin, _segments

#: Champs produits par une bascule — `time` vient de la taxonomie, le reste est la traçabilité.
CHAMPS_BASCULE = CANONICAL_FIELDS[DataType.EVENTS] + ['edge', 'name', 'origin']


def column_kind(frame: TypedFrame, field: str) -> str:
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
        series = frame.df[field]
    except Exception:
        raise ValueError(
            f"colonne '{field}' absente (disponibles : {', '.join(frame.fields) or '—'})")
    if pd.api.types.is_bool_dtype(series):
        return BOOLEAN
    if pd.api.types.is_numeric_dtype(series):
        return NUMERIC
    return TEXT


def _conditions(frame: TypedFrame, declaration: str) -> List[Condition]:
    """Construit les `Condition` déclarées, en LEUR IMPOSANT la sorte lue dans le cadre.

    Une `kind` présente dans le JSON est IGNORÉE — délibérément. L'accepter permettrait à une
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
        field = item.get('field', '')
        key = item.get('key') or f"C{i + 1}"
        kind = column_kind(frame, field)
        out.append(Condition(key=key, field=field, operator=item.get('operator', ''),
                             value=item.get('value'), stream=item.get('stream', ''),
                             kind=kind))
    cles = [c.key for c in out]
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
    masques = {c.key: c.evaluate(_colonne(signal, c.field)) for c in decl}
    text = (connectors or '').strip()
    if not text:
        # Une seule condition n'a pas besoin d'arbre ; plusieurs, si — sans quoi on choisirait
        # un connecteur implicite à leur place, et « ET » n'est pas plus évident que « OU ».
        if len(decl) > 1:
            raise ValueError(
                f"{len(decl)} conditions déclarées mais aucun connecteur — préciser leur "
                f"assemblage, par exemple ET({', '.join(c.key for c in decl)})")
        arbre = decl[0].key
    else:
        arbre = parse(text, list(masques))
    return evaluate(arbre, masques), chain_name(arbre)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Les DEUX ports de sortie du même masque
# ══════════════════════════════════════════════════════════════════════════════════════════════

def chain_to_segments(signal: TypedFrame, conditions: str = '', connectors: str = '',
                         min_duration: float = 0.0, gap_tolerance: float = 0.0,
                         name: str = '') -> TypedFrame:
    """Plages où la chaîne conditionnelle est vraie, avec hystérésis."""
    masque, derive = _masque(signal, conditions, connectors)
    return _segments(conditional(_colonne(signal, 'time'), masque, min_duration=min_duration,
                                    gap_tolerance=gap_tolerance, name=name or derive),
                     meta=signal.meta)


def chain_to_events(signal: TypedFrame, conditions: str = '', connectors: str = '',
                       rising: bool = True, falling: bool = False,
                       name: str = '') -> TypedFrame:
    """Instants où la chaîne conditionnelle BASCULE."""
    import pandas as pd
    masque, derive = _masque(signal, conditions, connectors)
    rows = edges(_colonne(signal, 'time'), masque, rising=rising,
                    falling=falling, name=name or derive)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=CHAMPS_BASCULE)
    return TypedFrame(df, DataType.EVENTS, meta=signal.meta)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Le FILTRE D'OCCURRENCES — la même chaîne, appliquée à des lignes qui EXISTENT déjà
# (trou ③ de §11.9, étendu aux situations sur question de Fabien : « durée > 1 min ?
# vitesse moyenne > 30 km/h ? » — par COMPOSITION, pas par concept neuf)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _garder(frame: TypedFrame, mask, eval_frame: TypedFrame = None) -> TypedFrame:
    """Les lignes du cadre D'ORIGINE où le masque est vrai — jamais celles du cadre d'évaluation :
    une colonne dérivée pour ÉVALUER (la durée) n'a pas à entrer dans la sortie d'un FILTRE."""
    keep = [i for i, m in enumerate(mask) if m]
    return TypedFrame(frame.df.iloc[keep].copy(), frame.data_type, meta=frame.meta)


def filter_events(events: TypedFrame, conditions: str = '', connectors: str = '') -> TypedFrame:
    """Occurrences d'événements satisfaisant une chaîne de conditions — la bascule [Data|Event]
    de l'écran d'origine (« les occurrences dont `var_commentaires` contient FIN »).

    Même chaîne, mêmes opérateurs, même arbre que `chain_to_segments` : un filtre n'est pas un
    mode, c'est le même masque appliqué à des lignes qui existent déjà.
    """
    mask, _ = _masque(events, conditions, connectors)
    return _garder(events, mask)


def filter_segments(segments: TypedFrame, conditions: str = '', connectors: str = '') -> TypedFrame:
    """Situations satisfaisant une chaîne de conditions — durée comprise.

    ⭐ La colonne `duration` (end − start) est DISPONIBLE À L'ÉVALUATION même si le cadre ne la
    porte pas — dérivée en flottant, jamais écrite dans la sortie (un filtre sélectionne, il
    n'enrichit pas). Un segment OUVERT a une durée ABSENTE : une condition numérique le REJETTE
    (une durée inconnue ne satisfait pas « > 60 »), et l'opérateur `empty` sur `duration` permet
    de le SÉLECTIONNER explicitement. « Vitesse moyenne > 30 » se compose : `calc_per_segment`
    adjoint l'indicateur, puis ce filtre s'applique — deux fonctions chaînées, zéro concept neuf.
    """
    eval_frame = segments
    if 'duration' not in segments.df.columns:
        df = segments.df.copy()
        df['duration'] = [float('nan') if _fin(e) is None else float(_fin(e)) - float(s)
                          for s, e in zip(df['start'], df['end'])]
        eval_frame = TypedFrame(df, segments.data_type, meta=segments.meta)
    mask, _ = _masque(eval_frame, conditions, connectors)
    return _garder(segments, mask)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Déclarations
# ══════════════════════════════════════════════════════════════════════════════════════════════

_ENTREE = PortSpec('signal', DataType.TIMESERIES, required_fields=['time'],
                   description="Signal portant les colonnes testées par les conditions.")

_AIDE_CONDITIONS = (
    'Liste JSON de conditions — [{"key": "C1", "field": "vitesse", "operator": ">=", '
    '"value": 30}]. La SORTE de la colonne (numérique / texte / booléen) est LUE dans la donnée, '
    'jamais déclarée : un opérateur qui ne lui convient pas est refusé à la déclaration. '
    'Opérateurs numériques : ' + ', '.join(operators_for(NUMERIC)) + '. '
    'Opérateurs texte : ' + ', '.join(operators_for(TEXT)) + '.')

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

register(FunctionSpec(
    key='event_filter',
    name="Filtrer des événements par conditions",
    description="Ne garde que les OCCURRENCES satisfaisant la chaîne de conditions — la bascule "
                "[Data|Event] de l'écran d'origine (« les occurrences dont le commentaire "
                "contient FIN »). Même chaîne, mêmes opérateurs que « Segments par chaîne de "
                "conditions » : un filtre n'est pas un mode, c'est le même masque appliqué à des "
                "lignes qui existent déjà. Couvre en DÉCLARATIF l'essentiel du filtrage manuel "
                "de l'outil d'origine (§11.9 ④).",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'conditionnel', 'ensembliste', 'evenement'],
    inputs=[PortSpec('events', DataType.EVENTS, required_fields=['time'],
                     description="Occurrences à trier — leurs colonnes portent les conditions.")],
    outputs=[PortSpec('events', DataType.EVENTS,
                      description="Les occurrences retenues, colonnes inchangées.")],
    params=[
        ParamSpec('conditions', 'json', '', description=_AIDE_CONDITIONS),
        ParamSpec('connectors', 'str', '', description=_AIDE_CONNECTEURS),
    ],
    cost={'cpu_bound': True},
    fn=filter_events,
))

register(FunctionSpec(
    key='segment_filter',
    name="Filtrer des situations par conditions",
    description="Ne garde que les situations satisfaisant la chaîne — DURÉE comprise : la "
                "colonne `duration` (end − start) est disponible à l'évaluation même si le cadre "
                "ne la porte pas, sans entrer dans la sortie. Un segment OUVERT a une durée "
                "ABSENTE : rejeté par toute condition numérique, sélectionnable par `empty`. "
                "« Vitesse moyenne > 30 » se COMPOSE : `calc_per_segment` adjoint l'indicateur, "
                "puis ce filtre s'applique — deux fonctions chaînées, zéro concept neuf.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'conditionnel', 'ensembliste', 'segmentation'],
    inputs=[PortSpec('segments', DataType.SEGMENTS, required_fields=['start', 'end'],
                     description="Situations à trier — leurs colonnes (et `duration` dérivée) "
                                 "portent les conditions.")],
    outputs=[PortSpec('segments', DataType.SEGMENTS,
                      description="Les situations retenues, colonnes inchangées.")],
    params=[
        ParamSpec('conditions', 'json', '', description=_AIDE_CONDITIONS),
        ParamSpec('connectors', 'str', '', description=_AIDE_CONNECTEURS),
    ],
    cost={'cpu_bound': True},
    fn=filter_segments,
))
