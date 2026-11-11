"""
Le pipeline que la CARD porte — ce qu'elle AJOUTE au pipeline déclaré de son app.
`WAMA_APP_GENERATION_ROUTE §10.6` 3.2bis, marche 2 (forme validée par Fabien le 2026-11-10).

D'OÙ ÇA VIENT. Une card porte déjà son pipeline et il fluctue déjà (3.2) ; ce qui manquait est
qu'elle en garde un AJUSTÉ par l'utilisateur. La forme a été revue avant tout code (29/10) :
  • la card ne DÉSIGNE pas un pipeline enregistré du Studio — un `StudioPipeline` est l'objet de
    travail de son auteur, modifiable et supprimable à part : le désigner ferait changer la card
    sans elle. Il reste sa PROVENANCE (`source`) ;
  • elle ne garde pas le graphe ENTIER : ses process déclarés seraient figés, et la première
    évolution du pipeline de l'app la rendrait illisible (règle 1). Elle garde ce qu'ELLE ajoute
    — nœuds, réglages, liens —, recomposé au pipeline déclaré DU MOMENT par
    `AppPipeline.extended` (qui en tient les deux règles) ;
  • dans un lot, l'ajout se règle sur la mère et se promeut : il voyage dans la charge utile de
    la promotion (`BatchSettings`) sous la clé `PIPELINE_KEY`.

UNE ligne par card qui ajoute quelque chose (`PipelineExtension`, adressée comme `ProcessRun`) ;
aucune ligne : la card joue le pipeline de son app. La ligne suit la DUPLICATION (`copy`) et part
avec la card (`forget`, appelé par `release_card_files` ; balayage des orphelins par
`process_runs.forget_orphans`).

LECTURE. `process_pipeline.pipeline_of(item)` rend le pipeline étendu ; l'ajout est lu UNE fois
par élément et retenu sur l'instance (`preload` le lit pour toute une page, en une requête).
Une table absente (migration pas encore passée) se lit comme « aucun ajout » : la file se rend.
"""
from __future__ import annotations

import logging

# L'adresse de la card est celle de ses lignes d'exécution : la MÊME fonction, pas une copie.
from wama.common.services.process_runs import address  # noqa: F401

logger = logging.getLogger(__name__)

#: Attribut posé sur un élément : l'ajout de sa card (dict body) ou None — lu une fois.
ADDED_ATTR = '_pipeline_added'
#: Attribut posé sur un élément : son pipeline étendu, construit une fois.
BUILT_ATTR = '_card_pipeline'
#: Clé de l'ajout dans la charge utile promue d'un lot. Le `@` l'écarte de tout nom de réglage
#: (la convention de `process_pipeline.UPSTREAM_KEY`).
PIPELINE_KEY = '@pipeline'
_MISSING = object()


def _rows(items):
    """`{pk (texte): (body, source)}` des cards de `items` (même modèle) qui ajoutent quelque
    chose — UNE requête. `{}` sans table."""
    from wama.common.models import PipelineExtension
    items = [i for i in items if getattr(i, 'pk', None) is not None]
    if not items:
        return {}
    meta = items[0]._meta
    try:
        rows = PipelineExtension.objects.filter(
            app=meta.app_label, object_type=meta.object_name,
            object_id__in=[str(i.pk) for i in items]).values_list('object_id', 'body', 'source')
        return {object_id: (body, source) for object_id, body, source in rows}
    except Exception:
        logger.warning("[card_pipelines] ajouts de %s illisibles", meta.label, exc_info=True)
        return {}


def preload(items) -> None:
    """Lit en UNE requête l'ajout de chaque card de `items` et le retient sur l'instance — la page
    d'une file, comme `process_pipeline.preload` pour les lignes."""
    # Une card déjà lue (`card_view` demande son pipeline avant d'ouvrir sa fenêtre) ne l'est pas
    # deux fois.
    items = [i for i in items if i is not None and ADDED_ATTR not in i.__dict__]
    found = _rows(items)
    for item in items:
        if getattr(item, 'pk', None) is not None:
            item.__dict__[ADDED_ATTR] = (found.get(str(item.pk)) or (None, None))[0] or None
            item.__dict__.pop(BUILT_ATTR, None)


def release(item) -> None:
    """Oublie ce qui a été lu sur l'instance (`process_pipeline.release`)."""
    item.__dict__.pop(ADDED_ATTR, None)
    item.__dict__.pop(BUILT_ATTR, None)


def added(item) -> dict | None:
    """L'ajout de la card (`{nodes, links}` au format du body du kind `pipeline`), ou None. Lu une
    fois par instance. Un élément sans identifiant n'ajoute rien (il n'est pas encore une card)."""
    if getattr(item, 'pk', None) is None:
        return None
    cached = item.__dict__.get(ADDED_ATTR, _MISSING)
    if cached is _MISSING:
        cached = (_rows([item]).get(str(item.pk)) or (None, None))[0] or None
        item.__dict__[ADDED_ATTR] = cached
    return cached


def source_of(item) -> dict:
    """La provenance de l'ajout (`{type, ref}`), `{}` sans ajout ou ajout fait sur la card."""
    return dict((_rows([item]).get(str(getattr(item, 'pk', ''))) or (None, None))[1] or {})


def composed(declared, body) -> dict:
    """Le graphe CANVAS du pipeline de la card : celui du pipeline déclaré, plus l'ajout."""
    from wama.common.manifests.builtin.pipeline import body_to_graph
    graph = declared.graph()
    extra = body_to_graph(body or {})
    return {'nodes': graph['nodes'] + extra['nodes'], 'links': graph['links'] + extra['links']}


def resolver_for(item):
    """Ce que la card peut RÉFÉRENCER comme nœud `pipeline` : la règle du Studio pour le compte qui
    la possède (`studio.services.pipeline_nodes.resolver`). PARESSEUX : le compte n'est lu que si
    un nœud `pipeline` est à déployer — une page de cards sans méta-process ne le lit pas."""

    def resolve(key):
        user = getattr(item, 'user', None)
        if user is None:
            raise ValueError("cette card n'a pas de propriétaire : elle ne référence aucun pipeline")
        from wama.studio.services.pipeline_nodes import resolver
        return resolver(user)(key)
    return resolve


def card_pipeline(item, declared, *, strict: bool = False):
    """Le pipeline de la card : `declared` étendu de ce qu'elle ajoute, ou `declared` lui-même.
    Construit une fois par instance. Un ajout que le pipeline déclaré d'aujourd'hui refuse (une
    évolution de l'app l'a rendu invalide) : `strict` lève `ValueError` en le nommant — le
    lancement le dit —, sinon la card se lit avec son pipeline déclaré et le journal le dit."""
    built = item.__dict__.get(BUILT_ATTR)
    if built is not None and (built is declared or built.base is declared) and not strict:
        return built
    body = added(item)
    if not body:
        built = declared
    else:
        try:
            built = declared.extended(composed(declared, body), resolve=resolver_for(item))
        except ValueError as exc:
            if strict:
                raise ValueError(f"le pipeline de cette card ne se compose plus : {exc}") from exc
            logger.warning("[card_pipelines] ajout de %s ignoré : %s", address(item), exc)
            built = declared
    item.__dict__[BUILT_ATTR] = built
    return built


def added_body(declared, graph: dict) -> dict:
    """Ce qu'un graphe CANVAS ajoute au pipeline `declared` : ses nœuds non déclarés et les liens
    qui y arrivent, au format du body (`graph_to_body`, sans la disposition du canvas)."""
    from wama.common.manifests.builtin.pipeline import graph_to_body
    body = graph_to_body(graph or {})
    known = {spec.key for spec in declared.specs}
    nodes = [n for n in body['nodes'] if n['id'] not in known]
    ids = {n['id'] for n in nodes}
    links = [l for l in body['links'] if l['to'] in ids]
    return {'nodes': nodes, 'links': links} if nodes else {}


def set_added(item, graph: dict | None, *, source: dict | None = None):
    """La card PORTE désormais le pipeline `graph` (forme canvas du Studio, celle de
    `AppPipeline.graph()`) : son ajout est validé par `AppPipeline.extended` (les deux règles,
    refus nommés en `ValueError`), puis retenu — seul ce qu'elle AJOUTE. Un graphe qui n'ajoute
    rien (le pipeline de l'app tel quel), ou None, retire la ligne. Rend le pipeline de la card."""
    from wama.common.models import PipelineExtension
    from wama.common.services.process_pipeline import app_pipeline
    declared = app_pipeline(item._meta.app_label)
    if declared is None:
        raise ValueError(f"{item._meta.app_label} ne déclare pas de pipeline : une card n'y ajoute "
                         f"rien")
    # Le graphe ENTIER est jugé d'abord : un lien interdit (vers un process déclaré) est refusé en
    # le nommant, jamais retiré en silence par le tri de ce que la card ajoute.
    built = declared.extended(graph, resolve=resolver_for(item)) if graph else declared
    body = added_body(declared, graph) if built is not declared else {}
    if built is declared:
        PipelineExtension.objects.filter(**address(item)).delete()
        body = {}
    else:
        PipelineExtension.objects.update_or_create(
            **address(item), defaults={'body': body, 'source': dict(source or {})})
    item.__dict__[ADDED_ATTR] = body or None
    item.__dict__[BUILT_ATTR] = built
    return built


def check_body(item, body: dict | None) -> None:
    """Lève `ValueError` (nommé) si l'ajout `body` ne se compose pas au pipeline de cette card —
    sans rien écrire : le premier temps d'un geste qui en pose un sur plusieurs cards."""
    from wama.common.services.process_pipeline import app_pipeline
    declared = app_pipeline(item._meta.app_label)
    if declared is None or not body:
        return
    declared.extended(composed(declared, body), resolve=resolver_for(item))


def set_added_body(item, body: dict | None, *, source: dict | None = None):
    """Comme `set_added`, depuis l'AJOUT lui-même (la charge utile d'une promotion, une copie)."""
    from wama.common.services.process_pipeline import app_pipeline
    declared = app_pipeline(item._meta.app_label)
    if declared is None or not body:
        return set_added(item, None) if declared is not None else None
    return set_added(item, composed(declared, body), source=source)


def copy(source_item, target_item) -> bool:
    """La copie d'une card (`duplicate_instance`) porte le même pipeline que sa source. Rend True
    si un ajout a été recopié. Ne lève jamais."""
    from wama.common.models import PipelineExtension
    try:
        row = PipelineExtension.objects.filter(**address(source_item)).first()
        if row is None:
            return False
        PipelineExtension.objects.update_or_create(
            **address(target_item), defaults={'body': row.body, 'source': row.source})
        release(target_item)
        return True
    except Exception:
        logger.warning("[card_pipelines] ajout de %s non recopié", address(source_item),
                       exc_info=True)
        return False


def forget(item) -> int:
    """La card disparaît : son ajout aussi. Rend le nombre de lignes retirées."""
    from wama.common.models import PipelineExtension
    deleted, _detail = PipelineExtension.objects.filter(**address(item)).delete()
    release(item)
    return deleted
