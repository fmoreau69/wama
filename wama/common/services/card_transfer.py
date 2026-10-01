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


def _hand_over_files(element, new_owner) -> dict:
    """Applique la règle des fichiers ; rend {champ: nouveau chemin} et les comptes."""
    from django.conf import settings
    from django.db import models as dj_models
    from wama.common.utils.file_references import repoint
    from wama.common.utils.media_paths import copy_into_app_input
    from wama.common.utils.queue_duplication import is_shared_elsewhere, owns_file
    app, old_owner = element._meta.app_label, element.user_id
    fields, moved, copied = {}, 0, 0
    for f in element._meta.concrete_fields:
        if not isinstance(f, dj_models.FileField):
            continue
        name = getattr(getattr(element, f.name, None), 'name', '') or ''
        source = os.path.join(settings.MEDIA_ROOT, name) if name else ''
        if not name or not os.path.isfile(source):
            continue
        if owns_file(element, name) and not is_shared_elsewhere(element, f.name, name):
            new = _moved_path(name, app, old_owner, new_owner.pk)
            os.makedirs(os.path.dirname(os.path.join(settings.MEDIA_ROOT, new)), exist_ok=True)
            shutil.move(source, os.path.join(settings.MEDIA_ROOT, new))
            repoint(name, new)                       # cette card, ses provenances, sa note éventuelle
            fields[f.name] = new
            moved += 1
        else:
            _dest, new = copy_into_app_input(source, app, new_owner.pk, for_instance=element,
                                             field=f.name, provenance_kind='app',
                                             provenance_ref=name)
            fields[f.name] = new
            copied += 1
    return {'fields': fields, 'moved': moved, 'copied': copied}


def transfer_card(user, element, recipient, consent: bool = False) -> dict:
    """Cède `element` (une card de `user`) à `recipient`. Rend un compte-rendu
    `{'to', 'moved', 'copied', 'lot'}` ; lève `RefusDePartage` (motif pour l'utilisateur) ou
    `TransferConsentRequired` (le texte à valider)."""
    from wama.common.models import ShareConsent
    from wama.common.utils.batch_common import leave_batch
    from wama.common.utils.notifications import notify_in_app
    if not any(f.name == 'user' for f in element._meta.concrete_fields):
        raise RefusDePartage("cet élément n'est pas transférable (pas de propriétaire direct)")
    if element.user_id != getattr(user, 'pk', None):
        raise RefusDePartage("seul le propriétaire peut transférer")
    if getattr(element, 'status', '') == 'RUNNING':
        raise RefusDePartage("traitement en cours : transférez-la une fois terminé")
    subject = consent_subject(element)
    if subject and not consent:
        raise TransferConsentRequired(subject, recipient.username)

    with transaction.atomic():
        lot = leave_batch(element)
        handed = _hand_over_files(element, recipient)
        element.refresh_from_db()
        for name, value in handed['fields'].items():
            setattr(element, name, value)
        element.user = recipient
        for name, value in (('visibility', 'private'), ('scope_org_unit', None),
                            ('scope_project', None)):
            if any(f.name == name for f in element._meta.concrete_fields):
                setattr(element, name, value)
        element.save()
        if subject:
            ShareConsent.objects.create(
                object_type=element._meta.label, object_id=element.pk, user=user,
                username=user.username, visibility='transfer', subject=subject,
                statement=TRANSFER_STATEMENT.format(subject=subject, recipient=recipient.username))

    label = str(getattr(element, 'name', '') or getattr(element, 'filename', '') or
                getattr(element, 'input_filename', '') or f'#{element.pk}')
    notify_in_app([recipient], 'card_transferred',
                  f"{user.username} vous a transféré une card",
                  body=(f"« {label} » ({element._meta.app_label}) est désormais à vous, avec ses "
                        f"fichiers. Elle est privée : à vous de la partager si besoin."),
                  url=f'/{element._meta.app_label}/')
    logger.info('[transfer] %s#%s : %s → %s (%d déplacé(s), %d copié(s))', element._meta.label,
                element.pk, user.username, recipient.username, handed['moved'], handed['copied'])
    return {'to': recipient.username, 'moved': handed['moved'], 'copied': handed['copied'],
            'lot': lot.pk if lot is not None else None}
