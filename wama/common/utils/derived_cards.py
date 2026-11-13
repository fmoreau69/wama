"""CARDS DÉRIVÉES — les résultats d'une card deviennent des cards sœurs, dans SON lot.

Demande de Fabien (2026-11-12) : « après avoir ajouté un audio en entrée qui devient une card
unitaire, pouvoir découper l'audio en stems et que ça devienne un lot contenant les stems séparés
de l'audio, pour pouvoir par exemple déchiffrer la partition d'un élément séparé ». Décision du
même jour : la card DEVIENT le lot — l'originale (le mélange) reste en tête, ses pistes la
rejoignent, une card par piste, chacune avec ses réglages.

Le geste est générique (une app qui découpe une vidéo en plans, un document en pages, y
viendrait) ; il n'existait nulle part (relevé le 2026-11-12 : aucune brique « une card → N
cards ») et se compose des briques et déclarations existantes — l'app n'y repasse RIEN de ce
qu'elle a déjà déclaré :
  • une card dérivée est une COPIE de la source : la remise à zéro et les sorties vidées sont
    celles du geste ⧉ (`reset_on_duplicate`, `output_fields`), la liaison de lot celle de sa
    fabrique — lues à la déclaration d'élément de l'app (`batch_views.element_declaration`,
    revérification du 2026-11-13 : la 1ʳᵉ version se les faisait repasser par la glu, une jumelle
    les aurait reçus de l'original) ; `duplicate_instance` vide déjà ce que ses process ont écrit ;
  • elle n'hérite d'AUCUNE ligne de lot : la règle de nommage de sa ligne (`item_extra(copie,
    original)`) reçoit la card elle-même comme origine — elle se nomme d'après SON entrée ;
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


def derive_cards(source, parts, *, field, reset_fields=None):
    """Range dans le lot de `source` une card par `(rôle, fichier)` de `parts` — `fichier` relatif
    à MEDIA_ROOT, posé dans le champ d'entrée `field` de la card. Rend les cards, dans l'ordre de
    `parts`.

    `reset_fields` : ce qu'une card DÉRIVÉE pose en plus de la remise à zéro d'une copie (un
    interrupteur qui n'a pas de sens sur elle, l'adresse d'où venait l'entrée de la source). Le
    modèle porte `DerivedCardMixin` et sa fabrique de lot (`make_batch_views`) est déclarée."""
    from django.conf import settings
    from django.db import transaction
    from django.db.models import Max

    from wama.common.utils.batch_common import attach_to_batch, batch_of, wrap_in_batch
    from wama.common.utils.batch_views import element_declaration
    from wama.common.utils.provenance import record_provenance, ref_for
    from wama.common.utils.queue_duplication import duplicate_instance, safe_delete_file

    model = type(source)
    declared = element_declaration(model)
    if declared is None:
        raise LookupError(f"{model._meta.label} : aucune fabrique de lot déclarée (make_batch_views)")
    link = dict(declared['link'])
    naming = declared['item_extra']

    def own_line(card):
        """La ligne d'une card dérivée : nommée d'après elle-même (aucune ligne d'origine)."""
        return naming(card, card) if naming else {}

    reset = {**dict(declared['reset_on_duplicate']), **dict(reset_fields or {})}
    source_file = getattr(getattr(source, field, None), 'name', '') or ''
    cards = []
    with transaction.atomic():
        lot = batch_of(source)
        if lot is None:
            lot = wrap_in_batch(source, batch_model=declared['batch_model'],
                                item_extra=lambda work: own_line(work), **link)
        existing = {card.derived_role: card for card in
                    model.objects.filter(derived_from=source).exclude(derived_role='')}
        row = 'row_index' if link.get('item_model') is not None else link.get('row_field')
        for role, rel in parts:
            card = existing.get(role)
            if card is not None:
                if (getattr(getattr(card, field, None), 'name', '') or '') != rel:
                    safe_delete_file(card, field)         # la relance remplace l'ancienne piste
                    setattr(card, field, rel)
                    card.save(update_fields=[field])
            else:
                values = {**reset, 'derived_from': source, 'derived_role': role, field: rel}
                card = duplicate_instance(source, reset_fields=values,
                                          clear_fields=list(declared['output_fields']))
                nxt = (lot.items.aggregate(m=Max(row))['m'] or 0) + 1
                attach_to_batch(card, lot, nxt, item_extra=own_line(card) or None, **link)
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
