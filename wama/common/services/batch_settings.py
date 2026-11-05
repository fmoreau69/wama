"""
Les RÉGLAGES D'UN LOT — ce que la card MÈRE tient pour référence (`MODES_QUEUE_UX §5ter`,
`WAMA_APP_GENERATION_ROUTE §10.6` 5.3 ; marche P5, 2026-10-03).

D'OÙ ÇA VIENT. Un lot n'a jamais porté de réglages : sa modale ⚙ les POSAIT sur toutes les
filles et ne gardait rien. Deux gestes décidés le 2026-08-25 restaient donc impossibles :
  • ↑ PROMOUVOIR — depuis une fille, faire remonter SES réglages à la mère, qui les applique à
    tout le lot (n'importe quelle card peut servir de référence ; régler plusieurs filles en
    parallèle, écouter, promouvoir la gagnante) ;
  • ↓ RÉALIGNER — depuis la mère, remettre toutes les filles sur la référence (effacer les
    écarts individuels).
Le second exige une MÉMOIRE : c'est elle. UNE ligne par lot (`BatchSettings`), réécrite à
chaque geste de la mère — sa ⚙ comme une promotion. Une table commune, adressée comme
`ProcessRun` (app + type + identifiant), plutôt qu'une colonne sur les dix modèles de lot.

CE QUE LA RÉFÉRENCE CONTIENT. La charge utile promue est le PIPELINE de la card (`§10.6` 5.3) :
pour une app Médias, ses réglages — lus de son SCHÉMA (`revisions.settings_snapshot`, la règle
que la révision applique déjà), jamais une liste de champs écrite par app ; pour le monde Data,
son protocole (à venir : `promote_payload` déclaré). Les deux sont deux cas du même objet.

CE QUE CE MODULE NE FAIT PAS. Il n'applique rien : poser des réglages sur les filles reste la
fabrique des vues de lot (`batch_views.make_batch_views`), par la fonction de réglage de l'app
(`apply_settings`) — la même que sa route d'élément. Il ne lève jamais.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def address(batch) -> dict:
    """Adresse d'un lot : `{app, batch_type, batch_id}` — dérivée du lot SEUL (convention de
    `ProcessRun`)."""
    meta = batch._meta
    return {'app': meta.app_label, 'batch_type': meta.object_name, 'batch_id': str(batch.pk)}


def stored(batch) -> dict | None:
    """Les réglages de référence du lot, ou None s'il n'en a jamais reçu."""
    from wama.common.models import BatchSettings
    row = BatchSettings.objects.filter(**address(batch)).first()
    return dict(row.settings or {}) if row is not None else None


def remember(batch, settings: dict, *, source_id='') -> None:
    """La mère RETIENT ces réglages comme référence — réécrits, jamais empilés. `source_id` : la
    fille promue, quand il y en a une (vide pour la ⚙ de la mère)."""
    from wama.common.models import BatchSettings
    try:
        BatchSettings.objects.update_or_create(
            **address(batch),
            defaults={'settings': dict(settings or {}), 'source_object_id': str(source_id or '')})
    except Exception:
        logger.warning("[batch_settings] référence du lot %s non écrite", address(batch),
                       exc_info=True)


def forget(batch) -> int:
    """Le lot disparaît : sa référence aussi. Rend le nombre de lignes retirées."""
    from wama.common.models import BatchSettings
    try:
        deleted, _detail = BatchSettings.objects.filter(**address(batch)).delete()
        return deleted
    except Exception:
        logger.warning("[batch_settings] référence du lot %s non retirée", address(batch),
                       exc_info=True)
        return 0


def references_for(batch_model, batch_ids) -> dict:
    """`{id de lot (int): id de la fille promue ('' pour la ⚙ de la mère)}` des lots de
    `batch_ids` qui ONT une référence — UNE requête pour une page de file
    (`build_batches_list`), c'est ce qui dit à la card mère si « ↓ réaligner » a un sens.
    `{}` sans table (migration pas encore passée) : la file se rend quand même."""
    from wama.common.models import BatchSettings
    ids = [str(i) for i in (batch_ids or ())]
    if not ids:
        return {}
    meta = batch_model._meta
    try:
        rows = (BatchSettings.objects
                .filter(app=meta.app_label, batch_type=meta.object_name, batch_id__in=ids)
                .values_list('batch_id', 'source_object_id'))
        return {int(b): s for b, s in rows}
    except Exception:
        logger.warning("[batch_settings] références de %s illisibles", meta.label, exc_info=True)
        return {}


# ── Les valeurs PROPRES à une fille (2026-11-05, décision de Fabien) ─────────────────────────
#
# Un geste de la mère (sa ⚙, « réaligner », « faire de ses réglages la référence ») pose ses
# réglages sur les filles. Deux sortes de valeurs n'y sont pas celles du lot :
#   • CALCULÉES — tirées du fichier d'entrée de la fille (`Param.default_from` : la durée d'un
#     cover, les pages sans texte d'un PDF). Les écraser, c'est perdre le lien à la
#     caractéristique. Le schéma le DÉCLARE ; la fille le confirme en portant l'entrée qui propose
#     la valeur — relu à la demande, jamais écrit (rien à estampiller en base) ;
#   • PERSONNALISÉES — réglées sur la fille : sa valeur diffère de la référence du lot.
# Ce que le geste en fait se CHOISIT : les garder toutes (défaut de la ⚙), garder seulement les
# calculées (défaut de « réaligner » et de la promotion), ou tout remplacer.

COMPUTED, PERSONAL = 'computed', 'personal'
KEEP_OWN, KEEP_COMPUTED, REPLACE_ALL = 'keep_own', 'keep_computed', 'all'
SCOPES = (KEEP_OWN, KEEP_COMPUTED, REPLACE_ALL)


def computed_values(item, schema) -> dict:
    """`{réglage: valeur}` que le fichier d'entrée de CETTE fille propose (`Param.default_from`) —
    la lecture de la naissance d'un élément (`user_settings.inputs_by_port` puis
    `input_proposals`), rejouée sur l'entrée qu'il porte (`batch_identity.entry_file`)."""
    import os

    from django.conf import settings

    from wama.common.services.batch_identity import entry_file
    from wama.common.utils.param_schema import _pget
    from wama.common.utils.user_settings import input_proposals, inputs_by_port
    if not any(_pget(p, 'default_from') for p in schema or ()):
        return {}
    path = entry_file(item)
    if not path:
        return {}
    try:
        inputs = inputs_by_port(item._meta.app_label, os.path.join(settings.MEDIA_ROOT, path))
        return {name: proposal['value'] for name, proposal in input_proposals(schema, inputs).items()}
    except Exception:
        logger.warning("[batch_settings] entrée de %s illisible", item, exc_info=True)
        return {}


def input_settings(item, schema) -> set:
    """Les réglages de cette fille qui SONT une entrée de sa card — son port de consigne
    (`studio_node_ports`, groupe `prompt`), une valeur non vide : dans un lot de N consignes, c'est
    ce qui distingue les cards (le `prompt` du composer écrasait celui des sœurs, 2026-10-03)."""
    from wama.common.app_registry import studio_node_ports
    from wama.common.utils.param_schema import _pget
    ports = {p.get('id') for p in ((studio_node_ports(item._meta.app_label) or {}).get('inputs') or [])
             if p.get('group') == 'prompt'}
    return {name for name in (_pget(p, 'name') for p in schema or ())
            if name in ports and str(getattr(item, name, '') or '').strip()}


def own_settings(item, schema, reference=None) -> dict:
    """`{réglage: COMPUTED | PERSONAL}` — les valeurs de cette fille qui ne sont pas celles du lot.
    COMPUTED : liée à SON entrée — tirée de son fichier (`computed_values`) ou entrée elle-même
    (`input_settings`) ; une valeur calculée reste calculée même retouchée : elle suit SA card.
    Sans référence, rien n'est « personnalisé » : il n'y a pas encore de valeur du lot à quitter."""
    own = {name: COMPUTED for name in set(computed_values(item, schema)) | input_settings(item, schema)}
    if reference:
        from wama.common.utils.param_schema import coerce_schema_values
        current = settings_of(item, schema)
        try:
            expected = {**reference, **coerce_schema_values(schema, reference)}
        except Exception:
            expected = dict(reference)
        for name, value in expected.items():
            if name in current and name not in own and str(current[name]) != str(value):
                own[name] = PERSONAL
    return own


def kept(own: dict, scope: str = KEEP_OWN, replace=()) -> set:
    """Les réglages qu'un geste de la mère NE pose PAS sur cette fille : ses valeurs propres selon
    `scope`, sauf celles que `replace` désigne (« remplacer aussi », choisi ligne par ligne)."""
    if scope == REPLACE_ALL:
        return set()
    return {name for name, kind in (own or {}).items()
            if (kind == COMPUTED or scope == KEEP_OWN) and name not in set(replace or ())}


def settings_of(item, schema=None) -> dict:
    """Les réglages d'UNE fille, prêts à être promus : ceux de son schéma d'app, lus par la
    règle de la révision — restreints, quand `schema` est donné (la fabrique connaît le sien),
    à ce qu'une MÈRE peut poser : les réglages déclarés au contexte `batch`.

    ⚠ Ce qui appartient à la card SEULE ne se promeut pas (mesuré au smoke du 2026-10-03 : le
    `prompt` du composer, contexte `item` seul, écrasait celui des sœurs — dans un lot de N
    consignes, c'est exactement ce qui distingue les cards). La référence d'un lot est ce que
    sa ⚙ poserait, rien de plus. Un schéma qui ne déclare AUCUN contexte de lot garde ses
    réglages d'élément (comportement d'avant, plutôt qu'une promotion vide). `{}` sans schéma
    déclaré."""
    from wama.common.services.revisions import settings_snapshot
    from wama.common.utils.param_schema import _pget
    taken = settings_snapshot(item._meta.app_label, item)
    if schema:
        declared = [(_pget(p, 'name'), tuple(_pget(p, 'contexts') or ())) for p in schema]
        declared = [(name, contexts) for name, contexts in declared if name]
        of_the_batch = {name for name, contexts in declared if 'batch' in contexts}
        names = of_the_batch or {name for name, _contexts in declared}
        taken = {k: v for k, v in taken.items() if k in names}
    return taken
