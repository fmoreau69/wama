"""
Déclaration au catalogue du CODAGE (implémentation : `wama_data/core/coding.py`).

Le codage est le 5ᵉ mode de segmentation. Il entre au catalogue comme les quatre autres, et c'est
tout l'enjeu : **un codage automatique par un modèle de vision devient alors un NŒUD DE PIPELINE**,
chaînable après une détection et avant un export, sans une ligne de code studio. Sans cette
déclaration, le codage IA resterait un script à part — exactement la fracture que le monde Data
existe pour éviter.

La SESSION interactive (`SessionCodage`) n'a volontairement pas d'entrée ici : elle est
événementielle et pilotée par le transport, donc elle relève de l'interface, pas du pipeline. Ce
qu'on déclare est sa forme REJOUABLE — une liste de gestes en entrée, des segments en sortie. C'est
la même exécution : `rejouer` construit une vraie session et lui envoie les gestes un à un.

⚠ ADAPTATEURS DE PORTS uniquement, comme pour `segmentation.py` : aucune logique ici.
"""
from __future__ import annotations

from ...core.coding import Protocole, accord, rejouer
from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType, TypedFrame
from wama.common.catalog.function_catalog import FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register
from .segmentation import CHAMPS_SEGMENT, _colonne, _fin, _segments, manquant

#: Champs d'un événement produit par le codage — un ponctuel garde la même forme qu'un état.
CHAMPS_EVENT = CANONICAL_FIELDS[DataType.EVENTS] + ['value', 'label', 'origin']


def _protocole(source) -> Protocole:
    """Accepte un `Protocole`, son dictionnaire, ou un chemin de fichier JSON.

    Les trois formes sont la MÊME déclaration : c'est la propriété qui fait du protocole un
    manifeste. Un paramètre de nœud est sérialisé, donc arrive en dict ou en chemin ; du code
    Python passe l'objet.
    """
    if isinstance(source, Protocole):
        return source
    if isinstance(source, dict):
        return Protocole.depuis_dict(source)
    if isinstance(source, (str,)) and source:
        import json
        from pathlib import Path
        return Protocole.depuis_dict(json.loads(Path(source).read_text(encoding='utf-8')))
    raise ValueError("protocole requis (objet, dictionnaire ou chemin JSON)")


def _gestes(frame: TypedFrame, code_column: str) -> list:
    """Un flux d'événements → la liste de gestes attendue par `rejouer`.

    Tout champ hors (temps, code, sujet, commentaire) est passé en MODIFICATEUR : c'est ainsi qu'un
    détecteur transmet ce qu'il a mesuré (confiance, classe, vitesse) sans que le catalogue ait à
    connaître le protocole. La validation de ces champs se fait alors dans la session, contre le
    protocole — donc au bon endroit.

    ⚠ Les valeurs ABSENTES sont écartées ici, et ce n'est pas cosmétique : un cadre a une colonne
    par modificateur de TOUT le protocole, remplie de `NaN` sur les lignes que ce modificateur ne
    concerne pas. Les laisser passer ferait refuser chaque geste comme portant un modificateur non
    déclaré. Un modificateur RÉELLEMENT hors protocole, lui, reste refusé — c'est le garde-fou qui
    arrête une hallucination de modèle.
    """
    reserves = {'time', code_column, 'subject', 'comment'}
    gestes = []
    for r in frame.df.to_dict('records'):
        mods = {k: v for k, v in r.items() if k not in reserves and not manquant(v)}
        gestes.append({'t': float(r['time']), 'code': r[code_column],
                       'subject': '' if manquant(r.get('subject')) else (r.get('subject') or ''),
                       'comment': '' if manquant(r.get('comment')) else (r.get('comment') or ''),
                       'modifiers': mods or None})
    return gestes


def coding_replay(gestes: TypedFrame, protocole=None, coder: str = '', media: str = '',
                   code_column: str = 'value',
                   session_end: float = None) -> TypedFrame:
    """Rejoue une liste de gestes contre un protocole → segments.

    Le `codeur` distingue un codage humain d'un codage automatique. C'est le SEUL point de
    différence : le reste du chemin — validation, exclusion mutuelle, états ouverts, sortie typée —
    est identique. C'est ce qui rend un codage assisté vérifiable ligne à ligne contre un codage
    humain, avec `codage_accord`.
    """
    proto = _protocole(protocole)
    media = media or (gestes.meta or {}).get('media') or (gestes.meta or {}).get('source') or ''
    segs, _ev = rejouer(proto, media, _gestes(gestes, code_column), coder=coder,
                        session_end=session_end)
    return _segments(segs, meta=gestes.meta)


def coding_events(gestes: TypedFrame, protocole=None, coder: str = '', media: str = '',
                      code_column: str = 'value') -> TypedFrame:
    """Même exécution, sortie ÉVÉNEMENTS : les comportements ponctuels du protocole.

    Séparé de `codage_rejouer` parce qu'un port a UN type : mélanger états et ponctuels dans un
    même cadre ferait perdre la distinction que le protocole vient précisément d'établir.
    """
    import pandas as pd
    proto = _protocole(protocole)
    media = media or (gestes.meta or {}).get('media') or (gestes.meta or {}).get('source') or ''
    _segs, ev = rejouer(proto, media, _gestes(gestes, code_column), coder=coder)
    rows = [dict(e, time=e['start']) for e in ev]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=CHAMPS_EVENT)
    return TypedFrame(df, DataType.EVENTS, meta=gestes.meta)


def coding_agreement(reference: TypedFrame, compare: TypedFrame,
                  tolerance: float = 1.0) -> TypedFrame:
    """Compare deux codages du même média → une ligne de mesure.

    La question posée quand on valide un codage assisté est « ce que la machine a proposé
    correspond-il à ce que l'humain a codé ». Cette fonction y répond ; les indicateurs d'accord
    plus fins (kappa et suivants) relèvent du module de calcul, qui n'existe encore nulle part —
    ni ici, ni dans les systèmes confrontés.
    """
    import pandas as pd

    def _lire(f):
        return [{'start': s, 'end': _fin(e), 'value': v, 'subject': su}
                for s, e, v, su in zip(_colonne(f, 'start'), _colonne(f, 'end'),
                                       _colonne(f, 'value'),
                                       list(f.df['subject']) if 'subject' in f.df.columns
                                       else [None] * len(f.df))]
    r = accord(_lire(reference), _lire(compare), tolerance=tolerance)
    return TypedFrame(pd.DataFrame([r]), DataType.TABLE, meta=reference.meta)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Déclarations
# ──────────────────────────────────────────────────────────────────────────────────────────────

_ENTREE_GESTES = PortSpec(
    'gestes', DataType.EVENTS, required_fields=['time'],
    description="Gestes de codage : un instant + un code du protocole. Produits par un humain à "
                "l'interface OU par un modèle de vision — le port ne fait pas la différence, et "
                "c'est le but.")

_PARAM_PROTOCOLE = ParamSpec(
    'protocol', 'str', '',
    description="Protocole (éthogramme) : chemin JSON ou dictionnaire. Déclare CE QUI EST CODABLE — "
                "comportements, nature ponctuel/état, groupes d'exclusion mutuelle, sujets, "
                "modificateurs typés. C'est lui qui pilote l'interface ET contraint l'exécution.")

_PARAM_CODEUR = ParamSpec(
    'coder', 'str', '',
    description="Qui code : « fabien », « qwen3-vl », « detector:locate-anything ». Seul champ "
                "distinguant un codage humain d'un codage automatique.")

_PARAM_MEDIA = ParamSpec(
    'media', 'str', '',
    description="Média codé. Obligatoire (repris des métadonnées du flux si absent) : sans support, "
                "les bornes produites ne sont plus vérifiables par personne.")

register(FunctionSpec(
    key='coding_segments',
    name="Codage → segments",
    description="Rejoue des gestes de codage contre un protocole et produit les états observés. "
                "Un comportement se bascule (ouvrir/fermer), l'exclusion mutuelle ferme le "
                "concurrent, et un état non refermé reste OUVERT plutôt que d'être perdu ou "
                "refermé d'office. Une fermeture de fin de session est tracée séparément : une "
                "durée refermée par la fin de l'enregistrement n'est pas une durée observée.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'segmentation', 'codage', 'annotation'],
    inputs=[_ENTREE_GESTES],
    outputs=[PortSpec('segments', DataType.SEGMENTS, produced_fields=CHAMPS_SEGMENT + [
        'value', 'label', 'subject', 'nature', 'open', 'coder', 'protocol', 'media'],
        description="États codés — origine, codeur et protocole tracés sur chaque ligne.")],
    params=[
        _PARAM_PROTOCOLE, _PARAM_CODEUR, _PARAM_MEDIA,
        ParamSpec('code_column', 'str', 'value',
                  description="Colonne portant le code du comportement."),
        ParamSpec('session_end', 'float', None, unit='s',
                  description="Ferme d'office les états restés ouverts, en TRAÇANT la fermeture."),
    ],
    cost={'cpu_bound': True},
    fn=coding_replay,
))

register(FunctionSpec(
    key='coding_events',
    name="Codage → événements ponctuels",
    description="Même exécution que `codage_segments`, sortie ÉVÉNEMENTS : les comportements "
                "déclarés PONCTUELS dans le protocole, qui n'ont pas de durée. Séparé parce qu'un "
                "port a un seul type — et que confondre un instant et un état ferait perdre la "
                "distinction que le protocole vient d'établir.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'codage', 'annotation'],
    inputs=[_ENTREE_GESTES],
    outputs=[PortSpec('events', DataType.EVENTS, produced_fields=CHAMPS_EVENT,
                      description="Comportements ponctuels codés.")],
    params=[_PARAM_PROTOCOLE, _PARAM_CODEUR, _PARAM_MEDIA,
            ParamSpec('code_column', 'str', 'value')],
    cost={'cpu_bound': True},
    fn=coding_events,
))

register(FunctionSpec(
    key='coding_agreement',
    name="Accord entre deux codages",
    description="Apparie deux codages du même média par code, sujet et proximité des débuts, dans "
                "une tolérance. Répond à la question posée quand on valide un codage assisté : "
                "« ce que la machine a proposé correspond-il à ce que l'humain a codé ». Les "
                "indicateurs d'accord plus fins relèvent du module de calcul.",
    category=FunctionCategory.INDICATOR,
    tags=['temporel', 'codage', 'qualité'],
    inputs=[
        PortSpec('reference', DataType.SEGMENTS, required_fields=['start', 'end', 'value'],
                 description="Codage de référence (typiquement humain)."),
        PortSpec('compare', DataType.SEGMENTS, required_fields=['start', 'end', 'value'],
                 description="Codage à comparer (typiquement automatique)."),
    ],
    outputs=[PortSpec('mesure', DataType.TABLE,
                      produced_fields=['matched', 'only_a', 'only_b', 'mean_offset'],
                      description="Une ligne : appariés, propres à chaque source, décalage moyen.")],
    params=[ParamSpec('tolerance', 'float', 1.0, unit='s', min=0.0,
                      description="Écart maximal entre deux débuts pour les considérer appariés.")],
    cost={'cpu_bound': True},
    fn=coding_agreement,
))
