"""CARDS DÉRIVÉES — les résultats d'une card deviennent des cards, rangées sous elle.

Demande de Fabien (2026-11-12) : « après avoir ajouté un audio en entrée qui devient une card
unitaire, pouvoir découper l'audio en stems et que ça devienne un lot contenant les stems séparés
de l'audio, pour pouvoir par exemple déchiffrer la partition d'un élément séparé ». Décision du
même jour : la card DEVENAIT le lot — l'originale en tête, ses pistes à la suite. Décision du
2026-11-19, livrée le 23 (`family_lot`, `MODES_QUEUE_UX §5quater`) : un morceau seul reste une card
seule ; ses pistes, une card par piste, chacune avec ses réglages, vont dans un lot À ELLES que la
file montre sous lui.

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
  • le LOT qui les reçoit (`family_lot`) et le rattachement à la suite (`attach_to_batch`) ;
  • le LIEN card → card du mixin commun (`DerivedCardMixin` : `derived_from`, `derived_role`),
    qui fait l'IDENTITÉ d'une card dérivée — relancer le process de la source REMPLACE l'entrée
    des cards existantes (l'ancien fichier part par `safe_delete_file`, le geste d'une relance),
    elle n'en crée pas d'autres ;
  • la PROVENANCE du fichier (`provenance.record_provenance`, kind `app`) : d'où vient l'entrée.

Une card dérivée que l'utilisateur a déplacée reste où il l'a mise (seule son entrée est
remplacée). Une card dérivée ne se lance pas toute seule : l'utilisateur choisit ce qu'il fait de
chaque piste.
"""
import logging
import os

logger = logging.getLogger(__name__)



#: Au-delà, ce n'est plus une lignée de cards : une piste d'une piste d'une piste… s'arrête bien
#: avant (une séparation donne UN étage ; deux ou trois en enchaînant les gestes).
ORIGIN_DEPTH = 16


def origin_of(card):
    """La card d'ORIGINE d'une card dérivée — sa source, remontée jusqu'à celle qui n'en a pas ;
    la card elle-même sinon. Une piste séparée tient le TEMPS de son mélange, à l'échantillon près
    (2026-11-15) : ce qui se mesure sur le morceau entier (sa pulsation) se lit sur l'origine — une
    voix seule n'a pas de batterie, sa grille de temps flottait de 86 à 96 bpm sur « Plus d'eau »
    quand le mélange tient 90,1 à 0,09 s près. Une chaîne qui boucle s'arrête où elle repasse, et
    la remontée est BORNÉE (`ORIGIN_DEPTH`) : le 2026-11-16, un faux objet de test qui fabriquait
    une source neuve à chaque accès l'a fait tourner jusqu'à 42 Go (suite tuée sans verdict)."""
    seen = set()
    while (getattr(card, 'derived_from_id', None) and card.pk not in seen
           and len(seen) < ORIGIN_DEPTH):
        seen.add(card.pk)
        source = card.derived_from
        if source is None:
            break
        card = source
    return card

def family_lot(source, derived):
    """Le lot qui reçoit une card dérivée NEUVE de `source` — `derived` : ses cards dérivées déjà
    nées. None : il n'existe pas encore, la première l'ouvre (`derive_cards`).

    Décision de Fabien du 2026-11-19, option B soumise au concile : « un morceau seul n'est plus
    mis d'office dans un lot ; ses pistes s'affichent sous la card source ». L'audit demandé par le
    concile (« ce qui suppose qu'une card dérivée est toujours dans un lot ») a répondu : TOUTE
    card est dans un lot (`auto_wrap_orphans` — une card seule est un lot d'un), et une piste hors
    lot aurait été enveloppée seule au premier affichage. Les cards dérivées ont donc LEUR lot, que
    la file montre sous la card source (`batch_common.nest_derived_lots`) : la source reste une card
    seule, et les gestes du lot (▶, ⚙, ↓ réaligner, ZIP, étapes) portent sur les pistes et sur
    elles seules, sans une ligne de plus. Dans l'ordre :
      1. où sont déjà ses sœurs — une famille garde UNE place (y compris les familles nées avant
         cette décision, rangées avec leur source) ;
      2. le lot de la source quand elle est la fille d'un VRAI lot (d'autres cards qu'elle et les
         siennes) : l'utilisateur a composé ce lot, ses pistes l'y rejoignent, comme avant ;
      3. sinon leur propre lot — None tant qu'il n'existe pas."""
    from wama.common.utils.batch_common import batch_elements, batch_of
    for card in derived:
        lot = batch_of(card)
        if lot is not None:
            return lot
    home = batch_of(source)
    if home is None or getattr(home, 'total', 1) <= 1:
        return None
    own = {source.pk} | {card.pk for card in derived}
    others = [e for e in batch_elements(home, type(source)) if e.pk not in own]
    return home if others else None


def family_in_one_lot(lot, model):
    """`(source, [cards dérivées])` quand `lot` est une famille rangée ENSEMBLE — une seule card
    qui ne dérive de rien, et des cards qui dérivent toutes d'elle : la forme d'avant le
    2026-11-23, où « la card devenait le lot ». `(None, [])` pour tout autre lot (un lot que
    l'utilisateur a composé, une source sans piste)."""
    from wama.common.utils.batch_common import batch_elements
    members = list(batch_elements(lot, model))
    roots = [m for m in members if not getattr(m, 'derived_from_id', None)]
    derived = [m for m in members if getattr(m, 'derived_from_id', None)]
    if len(roots) != 1 or not derived or any(d.derived_from_id != roots[0].pk for d in derived):
        return None, []
    return roots[0], derived


def split_family(lot, model) -> int:
    """Donne LEUR lot aux cards dérivées d'une famille rangée ensemble (`family_in_one_lot`) : la
    source redevient une card seule, ses pistes passent dans un lot à elles, que la file montre
    sous elle — la forme que `derive_cards` donne aux familles nouvelles. Les lignes sont DÉPLACÉES
    (leurs champs, leur nom de sortie et leur ordre suivent), rien n'est copié ni recréé. Rend le
    nombre de cards déplacées, 0 quand `lot` n'est pas une telle famille. Geste de la commande
    `split_family_lots` (les familles nées avant le 2026-11-23) — sans lui, elles restent des lots
    comme avant, ce qui marche aussi."""
    from django.db import transaction

    from wama.common.utils.batch_views import element_declaration
    source, derived = family_in_one_lot(lot, model)
    if source is None:
        return 0
    from wama.common.utils.batch_common import open_lot
    declared = element_declaration(model) or {}
    with transaction.atomic():
        own = open_lot(type(lot), lot.user, like=lot, batch_extra=declared.get('batch_extra'),
                       total=len(derived))
        for index, card in enumerate(derived):
            line = getattr(card, 'batch_link', None)
            if line is None or line is card:                # FK DIRECTE : l'élément porte son lot
                card.batch = own
                card.batch_row_index = index
                card.save(update_fields=['batch', 'batch_row_index'])
            else:                                           # par LIAISON : sa ligne change de lot
                line.batch = own
                line.row_index = index
                line.save(update_fields=['batch', 'row_index'])
        for changed in (lot, own):
            total = changed.items.count()
            if changed.total != total:
                changed.total = total
                changed.save(update_fields=['total'])
    logger.info("[derived_cards] famille du lot #%s : %d card(s) dérivée(s) dans leur lot #%s",
                lot.pk, len(derived), own.pk)
    return len(derived)


def derive_cards(source, parts, *, field, reset_fields=None):
    """Range une card par `(rôle, fichier)` de `parts` dans le lot des cards dérivées de `source`
    (`family_lot`) — `fichier` relatif à MEDIA_ROOT, posé dans le champ d'entrée `field` de la
    card. Rend les cards, dans l'ordre de `parts`.

    `reset_fields` : ce qu'une card DÉRIVÉE pose en plus de la remise à zéro d'une copie (un
    interrupteur qui n'a pas de sens sur elle, l'adresse d'où venait l'entrée de la source). Le
    modèle porte `DerivedCardMixin` et sa fabrique de lot (`make_batch_views`) est déclarée."""
    from django.conf import settings
    from django.db import transaction
    from django.db.models import Max

    from wama.common.utils.batch_common import attach_to_batch, batch_of, open_lot
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
        existing = {card.derived_role: card for card in
                    model.objects.filter(derived_from=source).exclude(derived_role='')}
        lot = family_lot(source, existing.values())
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
                if lot is None:
                    # La PREMIÈRE card dérivée d'une source seule ouvre LEUR lot (`family_lot`) —
                    # avec les champs de lot que l'app déclare (`batch_extra` : le domaine de
                    # l'imager, la nature du converter), lus sur le lot de la source comme pour
                    # la copie d'une card (`place_copy`).
                    lot = open_lot(declared['batch_model'], card.user, like=batch_of(source),
                                   batch_extra=declared.get('batch_extra'))
                    attach_to_batch(card, lot, 0, item_extra=own_line(card) or None, **link)
                else:
                    nxt = (lot.items.aggregate(m=Max(row))['m'] or 0) + 1
                    attach_to_batch(card, lot, nxt, item_extra=own_line(card) or None, **link)
            # D'où vient le FICHIER : l'entrée de la card source, dont il est une piste.
            origin = ref_for(os.path.join(settings.MEDIA_ROOT, source_file)) if source_file else ''
            record_provenance(card, field, kind='app', ref=origin,
                              original_name=os.path.basename(rel),
                              source_path=os.path.join(settings.MEDIA_ROOT, rel))
            cards.append(card)
        if lot is not None:
            total = lot.items.count()
            if getattr(lot, 'total', total) != total:
                lot.total = total
                lot.save(update_fields=['total'])
    logger.info("[derived_cards] %s#%s : %d card(s) dérivée(s) dans le lot #%s", model.__name__,
                source.pk, len(cards), getattr(lot, 'pk', None))
    return cards
