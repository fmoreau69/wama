"""
WAMA Common — Orchestration batch (côté serveur).

Le PARSING des fichiers batch vit dans ``batch_parsers.py`` ; l'UI de détection
et de prévisualisation dans ``static/common/js/batch-import.js`` +
``templates/common/batch_detect_bar.html``.

Ce module formalise la partie restante, jusqu'ici dupliquée/spécifique :
  - regrouper des fichiers par NATURE (image/vidéo/audio/document) — nécessaire
    quand les réglages de sortie sont communs au batch (ex. Converter) ;
  - créer/consolider un batch-of-N à partir d'items déjà créés, via des
    callbacks fournis par chaque app (chaque app conserve son modèle batch).

Conçu pour être branché progressivement dans TOUTES les apps génériques
(on commence par le Converter). Reader/Synthesizer peuvent y migrer ensuite
sans changement de comportement.
"""

from collections import OrderedDict
from typing import Callable, Iterable, List, Optional, Sequence


def group_paths_by_nature(paths: Sequence[str],
                          classifier: Callable[[str], Optional[str]]) -> "OrderedDict[str, List[str]]":
    """Regroupe des chemins par nature de média, en conservant l'ordre d'apparition.

    Args:
        paths:      chemins (ou noms) de fichiers.
        classifier: fonction ``path -> nature`` (ex. 'image'|'video'|'audio'|
                    'document'|'archive') ou ``None`` si non supporté.

    Returns:
        OrderedDict {nature: [paths…]} — les chemins non classables (classifier
        renvoie None) sont ignorés. Permet à l'appelant de créer UN batch par
        nature (réglages de sortie communs à chaque batch).
    """
    groups: "OrderedDict[str, List[str]]" = OrderedDict()
    for p in paths:
        nature = classifier(p)
        if not nature:
            continue
        groups.setdefault(nature, []).append(p)
    return groups


def consolidate_into_batch(items: Iterable,
                           *,
                           create_batch: Callable[[int], object],
                           link_item: Callable[[object, object, int], None],
                           unwrap_singletons: Optional[Callable[[List], None]] = None):
    """Crée UN batch-of-N reliant ``items`` (généralise la consolidation reader).

    Chaque app fournit les opérations propres à son modèle batch :

        create_batch(total)            -> instance batch (ex. BatchReadingItem)
        link_item(batch, item, index)  -> crée le lien batch↔item
        unwrap_singletons(item_ids)    -> (optionnel) supprime les batch-of-1
                                          créés au préalable pour ces items
                                          (cas reader : import wrappe en
                                          batch-of-1, puis on consolide).

    Returns:
        l'instance batch créée, ou ``None`` si aucun item.
    """
    items = list(items)
    if not items:
        return None
    if unwrap_singletons:
        unwrap_singletons([getattr(i, 'id', i) for i in items])
    batch = create_batch(len(items))
    for idx, item in enumerate(items):
        link_item(batch, item, idx)
    return batch


def group_into_batches_by_nature(items,
                                 *,
                                 nature_of: Callable[[object], str],
                                 create_batch: Callable[[str, int], object],
                                 link_item: Callable[[object, object, int], None],
                                 unwrap_singletons: Optional[Callable[[List], None]] = None):
    """Crée UN batch PAR NATURE — **règle générale** de regroupement batch (conventions §9).

    Règle unifiée pour TOUTES les apps :
      - app mono-nature → ``nature_of`` renvoie une constante → un seul batch
        (comportement identique à une consolidation simple) ;
      - app multi-natures (image/vidéo/audio/document…) → un batch par nature
        (réglages cohérents par groupe, UI plus lisible).

    Callbacks fournis par l'app (chaque app garde son modèle batch) :
        nature_of(item)              -> str (nature)
        create_batch(nature, total)  -> instance batch (la nature peut être ignorée
                                        si l'app ne la stocke pas sur le batch)
        link_item(batch, item, idx)  -> lien batch↔item
        unwrap_singletons(item_ids)  -> (optionnel) supprime les batch-of-1 préalables

    Returns: liste des batchs créés (un par nature, dans l'ordre d'apparition).
    """
    items = list(items)
    if not items:
        return []
    if unwrap_singletons:
        unwrap_singletons([getattr(i, 'id', i) for i in items])
    by_nature: "OrderedDict[str, List]" = OrderedDict()
    for it in items:
        by_nature.setdefault(nature_of(it), []).append(it)
    batches = []
    for nature, group in by_nature.items():
        batch = create_batch(nature, len(group))
        for idx, it in enumerate(group):
            link_item(batch, it, idx)
        batches.append(batch)
    return batches


# ---------------------------------------------------------------------------
# Batch UNIFIÉ — « tout est batch » (le batch-of-1 est rendu comme card simple).
# Généralise les helpers jusqu'ici dupliqués transcriber/composer/describer
# (audit empirique PROJECT_STATUS §20bis, 2026-07-06).
# ---------------------------------------------------------------------------

def wrap_in_batch(item, *, batch_model, item_model, fk_name, item_extra=None):
    """Enveloppe UN item métier dans un batch-of-1 (règle « tout est batch »).

    Args:
        item        : objet métier (Transcript, ComposerGeneration, Description…) ; porte ``.user``.
        batch_model : modèle batch de l'app (ex. BatchTranscript).
        item_model  : modèle de liaison (ex. BatchTranscriptItem).
        fk_name     : nom de la FK métier sur le modèle de liaison (ex. 'transcript').
        item_extra  : dict OU callable(item)->dict de champs supplémentaires du lien
                      (ex. composer : output_filename).
    """
    batch = batch_model.objects.create(user=item.user, total=1)
    kwargs = {'batch': batch, 'row_index': 0, fk_name: item}
    if item_extra:
        kwargs.update(item_extra(item) if callable(item_extra) else dict(item_extra))
    item_model.objects.create(**kwargs)
    return batch


def auto_wrap_orphans(user, *, work_model, batch_model, item_model, fk_name,
                      item_extra=None, wrap_group=None, order_by='id'):
    """Rattache paresseusement (au chargement de page) les items hors batch.

    Les orphelins proviennent des imports serveur (« Envoyer vers » du filemanager…) —
    l'upload JS, lui, enveloppe déjà à la création.

    Stratégie de regroupement :
      - défaut : chaque orphelin → SON batch-of-1 (composer) ;
      - ``wrap_group(orphans)`` : stratégie d'app qui crée les batchs elle-même —
        transcriber (1 → of-1, N → UN of-N), describer (un batch par nature).

    Silencieux par item (un orphelin cassé ne bloque pas la page — comportement historique).
    Returns: liste des batchs créés (vide si aucun orphelin).
    """
    existing_ids = set(
        item_model.objects.filter(batch__user=user).values_list(f'{fk_name}_id', flat=True)
    )
    orphans = list(
        work_model.objects.filter(user=user).exclude(id__in=existing_ids).order_by(order_by)
    )
    if not orphans:
        return []
    if wrap_group is not None:
        return wrap_group(orphans) or []
    wrapped = []
    for orphan in orphans:
        try:
            wrapped.append(wrap_in_batch(orphan, batch_model=batch_model,
                                         item_model=item_model, fk_name=fk_name,
                                         item_extra=item_extra))
        except Exception:
            pass
    return wrapped


def build_batches_list(user, *, batch_model, work_attr, items_related='items',
                       order_by='-id', has_output=None, extra=None):
    """Agrégats de file pour le template — contrat de la toolbar commune (``queue_view.py``).

    Returns:
        [{'obj', 'items', 'success_count', 'running_count', 'failure_count',
          'has_success' [, **extra(batch, items, works)]}, …]

    Args:
        work_attr  : nom de la FK métier sur le modèle de liaison ('transcript', 'generation'…).
        has_output : callable(work)->bool optionnel — 'has_success' exige alors au moins un
                     SUCCESS avec sortie exploitable (ex. composer : audio_output non vide) ;
                     sinon 'has_success' = success_count > 0.
        extra      : callable(batch, items, works)->dict — enrichissements d'app
                     (ex. transcriber : success_pct + méta communes aux filles).
    """
    batches = (batch_model.objects.filter(user=user)
               .prefetch_related(f'{items_related}__{work_attr}')
               .order_by(order_by))
    result = []
    for batch in batches:
        # sorted() sur le cache prefetch (pas de .order_by() ici : re-requêterait par batch)
        items = sorted(getattr(batch, items_related).all(),
                       key=lambda it: getattr(it, 'row_index', 0) or 0)
        works = [w for w in (getattr(it, work_attr) for it in items) if w]
        # Vocabulaires de statut variables selon les apps (reader : DONE/ERROR…) —
        # même tolérance que _cycle_button.html / wama-cycle-button.js stateFor().
        _ALIAS = {'DONE': 'SUCCESS', 'COMPLETED': 'SUCCESS', 'ERROR': 'FAILURE',
                  'FAILED': 'FAILURE', 'PROCESSING': 'RUNNING', 'STARTED': 'RUNNING'}
        statuses = [_ALIAS.get((w.status or '').upper(), (w.status or '').upper()) for w in works]
        row = {
            'obj': batch,
            'items': items,
            'success_count': statuses.count('SUCCESS'),
            'running_count': statuses.count('RUNNING'),
            'failure_count': statuses.count('FAILURE'),
        }
        if has_output is not None:
            row['has_success'] = any(s == 'SUCCESS' and has_output(w)
                                     for s, w in zip(statuses, works))
        else:
            row['has_success'] = row['success_count'] > 0
        if extra is not None:
            row.update(extra(batch, items, works) or {})
        result.append(row)
    return result
