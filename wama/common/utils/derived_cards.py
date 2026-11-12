"""CARDS DÉRIVÉES — les résultats d'une card deviennent des cards sœurs, dans SON lot.

Demande de Fabien (2026-11-12) : « après avoir ajouté un audio en entrée qui devient une card
unitaire, pouvoir découper l'audio en stems et que ça devienne un lot contenant les stems séparés
de l'audio, pour pouvoir par exemple déchiffrer la partition d'un élément séparé ». Décision du
même jour : la card DEVIENT le lot — l'originale (le mélange) reste en tête, ses pistes la
rejoignent, une card par piste, chacune avec ses réglages.

Le geste est générique (une app qui découpe une vidéo en plans, un document en pages, y
viendrait) ; il n'existait nulle part (relevé le 2026-11-12 : aucune brique « une card → N
cards ») et se compose des briques existantes :
  • la COPIE de la card source, ses réglages compris, sans ses résultats (`duplicate_instance`,
    qui vide déjà ce que ses process ont écrit) ;
  • le LOT de la source (`batch_of`), qu'elle reçoit au besoin (`wrap_in_batch`), et le
    rattachement à la suite (`attach_to_batch`) ;
  • le LIEN card → card du mixin commun (`DerivedCardMixin` : `derived_from`, `derived_role`),
    qui fait l'IDENTITÉ d'une card dérivée — relancer le process de la source REMPLACE l'entrée
    des cards existantes (l'ancien fichier part par `safe_delete_file`, le geste d'une relance),
    elle n'en crée pas d'autres ;
  • la PROVENANCE du fichier (`provenance.record_provenance`, kind `app`) : d'où vient l'entrée.

Le lot est celui de la source tant qu'elle y est ; une card dérivée que l'utilisateur a sortie du
lot reste où il l'a mise (seule son entrée est remplacée). Une card dérivée ne se lance pas toute
seule : l'utilisateur choisit ce qu'il fait de chaque piste.
"""
import logging
import os

logger = logging.getLogger(__name__)


def derive_cards(source, parts, *, field, item_model=None, fk_name=None, item_extra=None,
                 reset_fields=None, clear_fields=None):
    """Range dans le lot de `source` une card par `(rôle, fichier)` de `parts` — `fichier` relatif
    à MEDIA_ROOT, posé dans le champ d'entrée `field` de la card. Rend les cards, dans l'ordre de
    `parts`.

    `item_model`, `fk_name`, `item_extra` : la LIAISON du lot de l'app (forme de
    `attach_to_batch` ; absents = FK directe). `reset_fields` : valeurs posées sur une card NÉE ici
    (statut, interrupteurs qui n'ont pas de sens sur une dérivée) ; `clear_fields` : champs vidés
    à la copie (forme de `duplicate_instance`). Le modèle doit porter `DerivedCardMixin`."""
    from django.conf import settings
    from django.db import transaction
    from django.db.models import Max

    from wama.common.utils.batch_common import attach_to_batch, batch_model_for, batch_of, wrap_in_batch
    from wama.common.utils.provenance import record_provenance, ref_for
    from wama.common.utils.queue_duplication import duplicate_instance, safe_delete_file

    model = type(source)
    source_file = getattr(getattr(source, field, None), 'name', '') or ''
    link = {'item_model': item_model, 'fk_name': fk_name, 'item_extra': item_extra}
    cards = []
    with transaction.atomic():
        lot = batch_of(source)
        if lot is None:
            lot = wrap_in_batch(source, batch_model=batch_model_for(model), **link)
        existing = {card.derived_role: card for card in
                    model.objects.filter(derived_from=source).exclude(derived_role='')}
        row = 'row_index' if item_model is not None else 'batch_row_index'
        for role, rel in parts:
            card = existing.get(role)
            if card is not None:
                if (getattr(getattr(card, field, None), 'name', '') or '') != rel:
                    safe_delete_file(card, field)         # la relance remplace l'ancienne piste
                    setattr(card, field, rel)
                    card.save(update_fields=[field])
            else:
                values = dict(reset_fields or {})
                values.update({'derived_from': source, 'derived_role': role, field: rel})
                card = duplicate_instance(source, reset_fields=values, clear_fields=clear_fields)
                nxt = (lot.items.aggregate(m=Max(row))['m'] or 0) + 1
                attach_to_batch(card, lot, nxt, **link)
            # D'où vient le FICHIER : l'entrée de la card source, dont il est une piste.
            origin = ref_for(os.path.join(settings.MEDIA_ROOT, source_file)) if source_file else ''
            record_provenance(card, field, kind='app', ref=origin,
                              original_name=os.path.basename(rel),
                              source_path=os.path.join(settings.MEDIA_ROOT, rel))
            cards.append(card)
        total = lot.items.count()
        if getattr(lot, 'total', total) != total:
            lot.total = total
            lot.save(update_fields=['total'])
    logger.info("[derived_cards] %s#%s : %d card(s) dérivée(s) dans le lot #%s", model.__name__,
                source.pk, len(cards), lot.pk)
    return cards
