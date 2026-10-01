"""TRANSFÉRER une card à quelqu'un — le changement de propriétaire (2026-10-01).

Décision de Fabien (`WAMA_COLLABORATION §3bis`, cadre du 2026-09-28 : « celui qui partage DÉFINIT
les droits — lecture seule, édition, changement de propriétaire ») ; construit le 2026-10-01 à sa
demande (« on termine "Transférer à…" »). Ce n'est pas un mode de partage : après le geste, la
card n'a plus qu'UN propriétaire, le nouveau — pour passer une card sur son autre compte, ou la
confier à un collègue. Partager puis supprimer ne le fait pas (en lecture, le destinataire voit la
MÊME card : la supprimer la lui retire aussi).

RÈGLE DES FICHIERS (accordée le même jour) : *après le geste, la card ne désigne plus que des
fichiers de son nouveau propriétaire.*
  • les fichiers que la card POSSÉDAIT (domicile de l'app, `owns_file`) et que rien d'autre ne
    porte sont DÉPLACÉS chez lui — les liens suivent (`file_references.repoint`, le geste du
    gestionnaire de fichiers) ;
  • ceux qu'elle ne faisait que DÉSIGNER (temp, médiathèque de l'ancien propriétaire) ou qu'une
    autre card de l'ancien propriétaire partage encore sont COPIÉS — l'ancien garde les siens.
Jamais de bascule implicite : rien ne change de propriétaire sans ce geste.

Ce qui suit le transfert : la card sort du lot de l'ancien propriétaire (`batch_common.leave_batch`),
naît PRIVÉE chez le nouveau, qui est prévenu (notification). Une card qui porte une PERSONNE (une
voix) exige le consentement, comme un partage (`sharing.consent_subject`) — céder, c'est au moins
autant que partager.
"""
import logging
import os
import shutil

from django.db import transaction

from wama.common.services.sharing import RefusDePartage, consent_subject

logger = logging.getLogger(__name__)

TRANSFER_STATEMENT = (
    "Cet élément contient {subject}. En le transférant à {recipient}, je lui en cède la propriété : "
    "il pourra l'utiliser et le partager. J'atteste qu'il s'agit de la mienne, ou que j'ai l'accord "
    "de la ou des personnes concernées pour cette cession."
)


class TransferConsentRequired(RefusDePartage):
    """Le transfert d'un élément personnel attend le consentement de celui qui le cède."""

    def __init__(self, subject: str, recipient: str):
        self.subject = subject
        self.statement = TRANSFER_STATEMENT.format(subject=subject, recipient=recipient)
        super().__init__(f"consentement requis : cet élément contient {subject}")


def find_recipient(text: str, user):
    """Le destinataire désigné par son identifiant ou son adresse e-mail — un compte ACTIF, une
    personne (pas le compte de service anonyme), et pas soi-même. Lève `RefusDePartage` sinon."""
    from django.contrib.auth import get_user_model
    from django.db.models import Q
    from wama.accounts.views import ANONYMOUS_USERNAME
    text = (text or '').strip()
    if not text:
        raise RefusDePartage("indiquez l'identifiant ou l'adresse e-mail du destinataire")
    matches = list(get_user_model().objects.filter(
        Q(username__iexact=text) | Q(email__iexact=text), is_active=True)[:2])
    if len(matches) != 1 or matches[0].username == ANONYMOUS_USERNAME:
        raise RefusDePartage(f"aucun compte unique ne correspond à « {text} »")
    if matches[0].pk == getattr(user, 'pk', None):
        raise RefusDePartage("c'est déjà votre card")
    return matches[0]


def _moved_path(name: str, app: str, old_owner: int, new_owner: int) -> str:
    """Le chemin d'un fichier POSSÉDÉ chez le nouveau propriétaire : même place dans le domicile de
    l'app, nom rendu unique s'il est pris."""
    from django.conf import settings
    from wama.common.utils.media_paths import app_media_dir
    old_home, new_home = app_media_dir(app, old_owner, ''), app_media_dir(app, new_owner, '')
    candidate = new_home + name[len(old_home):]
    stem, ext = os.path.splitext(candidate)
    n = 1
    while os.path.exists(os.path.join(settings.MEDIA_ROOT, candidate)):
        candidate = f'{stem}_{n}{ext}'
        n += 1
    return candidate


def _hand_over_files(objects, new_owner) -> dict:
    """Applique la règle des fichiers à un ENSEMBLE cédé d'un bloc (une card, ou un lot et ses
    cards) ; rend `{'fields': {(label, pk): {champ: chemin}}, 'lists': {(label, pk): {champ:
    {ancien: nouveau}}}, 'moved', 'copied'}`.

    Les LISTES de chemins déclarées comptent comme les champs fichier (2026-10-02,
    `file_references.listed_paths`) : un fichier listé DÉPLACÉ voit son entrée réécrite en base par
    `repoint` (rien à reposer) ; un fichier listé COPIÉ ne change que SON ENTRÉE, jamais le champ
    entier (`_make_theirs` → `relocated_list`).

    Le partage se juge sur l'ENSEMBLE, pas card par card (même règle que `released_files.freed_by`) :
    un fichier que deux cards du même lot portent est à l'ensemble, il est DÉPLACÉ une fois et ses
    deux liens suivent ; un fichier qu'une card RESTÉE chez l'ancien porte encore est COPIÉ."""
    from django.conf import settings
    from django.db import models as dj_models
    from wama.common.utils.file_references import listed_paths, referenced_outside, repoint
    from wama.common.utils.media_paths import copy_into_app_input
    from wama.common.utils.queue_duplication import copy_subfolder, owns_file

    def files_of(obj):
        """(champ, chemin, listé ?) pour chaque fichier que la ligne porte et qui existe."""
        found = [(f.name, getattr(getattr(obj, f.name, None), 'name', '') or '', False)
                 for f in obj._meta.concrete_fields if isinstance(f, dj_models.FileField)]
        found += [(field, rel, True) for field, rel in listed_paths(obj)]
        for field, name, listed in found:
            if name and os.path.isfile(os.path.join(settings.MEDIA_ROOT, name)):
                yield field, name, listed

    inside = {(o._meta.label, o.pk) for o in objects}
    owned = {name for o in objects for _f, name, _l in files_of(o) if owns_file(o, name)}
    outside = referenced_outside(owned, inside)
    fields, lists, moved_to, copied_to, moved, copied = {}, {}, {}, {}, 0, 0
    for obj in objects:
        app = obj._meta.app_label
        key = (obj._meta.label, obj.pk)
        for field, name, listed in files_of(obj):
            if name in owned and name not in outside:
                if name not in moved_to:
                    new = _moved_path(name, app, obj.user_id, new_owner.pk)
                    target = os.path.join(settings.MEDIA_ROOT, new)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    shutil.move(os.path.join(settings.MEDIA_ROOT, name), target)
                    repoint(name, new)               # toutes les cards de l'ensemble, provenances, note
                    moved_to[name] = new
                    moved += 1
                if listed:
                    continue                         # `repoint` a réécrit l'entrée en base
                new = moved_to[name]
            else:
                if (app, name) not in copied_to:
                    source = os.path.join(settings.MEDIA_ROOT, name)
                    if listed:
                        _dest, copied_to[(app, name)] = copy_into_app_input(
                            source, app, new_owner.pk, subfolder=copy_subfolder(name, app))
                    else:
                        _dest, copied_to[(app, name)] = copy_into_app_input(
                            source, app, new_owner.pk, for_instance=obj, field=field,
                            provenance_kind='app', provenance_ref=name)
                    copied += 1
                new = copied_to[(app, name)]
                if listed:
                    lists.setdefault(key, {}).setdefault(field, {})[name] = new
                    continue
            fields.setdefault(key, {})[field] = new
    return {'fields': fields, 'lists': lists, 'moved': moved, 'copied': copied}


def _make_theirs(obj, new_owner, fields, lists=None):
    """La ligne devient celle du nouveau propriétaire : ses chemins, lui, privée. Une liste de
    chemins ne voit changer que les ENTRÉES copiées (`lists` : {champ: {ancien: nouveau}})."""
    from wama.common.utils.file_references import relocated_list
    obj.refresh_from_db()
    for name, value in (fields or {}).items():
        setattr(obj, name, value)
    for name, mapping in (lists or {}).items():
        setattr(obj, name, relocated_list(getattr(obj, name), mapping))
    obj.user = new_owner
    for name, value in (('visibility', 'private'), ('scope_org_unit', None), ('scope_project', None)):
        if any(f.name == name for f in obj._meta.concrete_fields):
            setattr(obj, name, value)
    obj.save()


def _check_transferable(user, objects):
    for obj in objects:
        if not any(f.name == 'user' for f in obj._meta.concrete_fields):
            raise RefusDePartage("cet élément n'est pas transférable (pas de propriétaire direct)")
        if obj.user_id != getattr(user, 'pk', None):
            raise RefusDePartage("seul le propriétaire peut transférer")
        if getattr(obj, 'status', '') == 'RUNNING':
            raise RefusDePartage("traitement en cours : transférez une fois terminé")


def _consent(user, objects, recipient, consent: bool):
    """Les sujets à consentir (une card qui porte une personne) ; lève s'il manque l'accord."""
    subjects = [(o, consent_subject(o)) for o in objects]
    subjects = [(o, s) for o, s in subjects if s]
    if subjects and not consent:
        raise TransferConsentRequired(subjects[0][1], recipient.username)
    return subjects


def _record_consents(user, subjects, recipient):
    from wama.common.models import ShareConsent
    for obj, subject in subjects:
        ShareConsent.objects.create(
            object_type=obj._meta.label, object_id=obj.pk, user=user, username=user.username,
            visibility='transfer', subject=subject,
            statement=TRANSFER_STATEMENT.format(subject=subject, recipient=recipient.username))


def _label(obj) -> str:
    return str(getattr(obj, 'name', '') or getattr(obj, 'filename', '') or
               getattr(obj, 'input_filename', '') or f'#{obj.pk}')


def transfer_card(user, element, recipient, consent: bool = False) -> dict:
    """Cède `element` (une card de `user`) à `recipient`. Rend un compte-rendu
    `{'to', 'moved', 'copied', 'lot'}` ; lève `RefusDePartage` (motif pour l'utilisateur) ou
    `TransferConsentRequired` (le texte à valider)."""
    from wama.common.utils.batch_common import leave_batch
    from wama.common.utils.notifications import notify_in_app
    _check_transferable(user, [element])
    subjects = _consent(user, [element], recipient, consent)

    with transaction.atomic():
        lot = leave_batch(element)
        handed = _hand_over_files([element], recipient)
        key = (element._meta.label, element.pk)
        _make_theirs(element, recipient, handed['fields'].get(key), handed['lists'].get(key))
        _record_consents(user, subjects, recipient)

    notify_in_app([recipient], 'card_transferred',
                  f"{user.username} vous a transféré une card",
                  body=(f"« {_label(element)} » ({element._meta.app_label}) est désormais à vous, "
                        f"avec ses fichiers. Elle est privée : à vous de la partager si besoin."),
                  url=f'/{element._meta.app_label}/')
    logger.info('[transfer] %s#%s : %s → %s (%d déplacé(s), %d copié(s))', element._meta.label,
                element.pk, user.username, recipient.username, handed['moved'], handed['copied'])
    return {'to': recipient.username, 'moved': handed['moved'], 'copied': handed['copied'],
            'lot': lot.pk if lot is not None else None}


def transfer_lot(user, lot, element_model, recipient, consent: bool = False) -> dict:
    """Cède un LOT ENTIER (2026-10-01, demande de Fabien : « un trou important ; le fonctionnement
    d'un batch est proche de celui d'une card ») : le lot ET toutes ses cards changent de
    propriétaire d'un bloc. Rien ne sort du lot — c'est le lot qui part, rangé tel quel chez le
    nouveau. Mêmes gardes que la card (propriétaire, rien en cours, consentement si une card porte
    une personne) ; règle des fichiers jugée sur l'ENSEMBLE (`_hand_over_files`)."""
    from wama.common.utils.batch_common import batch_elements
    from wama.common.utils.notifications import notify_in_app
    elements = list(batch_elements(lot, element_model))
    objects = [lot, *elements]
    _check_transferable(user, objects)
    subjects = _consent(user, objects, recipient, consent)

    with transaction.atomic():
        handed = _hand_over_files(objects, recipient)
        for obj in objects:
            key = (obj._meta.label, obj.pk)
            _make_theirs(obj, recipient, handed['fields'].get(key), handed['lists'].get(key))
        _record_consents(user, subjects, recipient)

    app = element_model._meta.app_label
    notify_in_app([recipient], 'card_transferred',
                  f"{user.username} vous a transféré un lot de {len(elements)} card(s)",
                  body=(f"Le lot ({app}) est désormais à vous, avec ses cards et leurs fichiers. "
                        f"Il est privé : à vous de le partager si besoin."),
                  url=f'/{app}/')
    logger.info('[transfer] lot %s#%s (%d card(s)) : %s → %s (%d déplacé(s), %d copié(s))',
                lot._meta.label, lot.pk, len(elements), user.username, recipient.username,
                handed['moved'], handed['copied'])
    return {'to': recipient.username, 'moved': handed['moved'], 'copied': handed['copied'],
            'cards': len(elements)}
