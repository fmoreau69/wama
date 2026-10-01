"""
WAMA — Common utilities for queue item duplication and safe file deletion.

Usage across apps
-----------------
1. In the app's delete / clear_all views (a card is REMOVED):
       from wama.common.utils.queue_duplication import release_card_files
       release_card_files(instance)             # never deletes: every file the card holds is
                                                # released, the user is warned and deletes it
                                                # explicitly (2026-09-30)
   It reads the card's declarations (its FileFields, its declared path lists);
   `release_card_file(instance, 'audio')` is the same gesture for ONE field.
   `safe_delete_file` is kept for a card REPLACING its own result (relaunch).

2. In the app's duplicate view:
       from wama.common.utils.queue_duplication import duplicate_instance
       new = duplicate_instance(
           instance,
           reset_fields={'status': 'PENDING', 'progress': 0, 'task_id': ''},
           clear_fields=['output_file', 'result_text'],
       )

Design notes
------------
- Files are NEVER copied when duplicating ONE'S OWN card. Both rows point to the same relative
  path. A card RECEIVED through a share (`duplicate_instance(for_user=…)`) is the exception: its
  copy belongs to the requester, so its files are copied to them (2026-10-01).
- safe_delete_file() destroys a file only if it is the card's OWN file (`owns_file`: it lives
  in the app's home for the card's owner) AND no other row still uses it
  (`is_shared_elsewhere`). A file the card only references is never destroyed; a file still
  used by a duplicate is kept.
- duplicate_instance() fetches a fresh DB copy of the row to avoid mutating the
  caller's in-memory object.
"""
import logging

logger = logging.getLogger(__name__)


def _owner_id(instance):
    """Propriétaire de la card : `user` direct, ou porté par une relation (`session`, `batch`).
    `None` si aucun — et alors rien n'est détruit (cf. `owns_file`). Les deux relations sont
    celles que le parc emploie réellement (`tests_media_paths._chemin_simule` mesure la
    première) ; en ajouter une par précaution serait deviner."""
    owner = getattr(instance, 'user_id', None)
    for relation in ('session', 'batch'):
        if owner is not None:
            break
        owner = getattr(getattr(instance, relation, None), 'user_id', None)
    return owner


def owns_file(instance, file_name: str) -> bool:
    """Le fichier vit-il dans le DOMICILE de l'app de cette card (`users/<uid>/<app>/…`) ?

    ⚠ La règle « supprimer une card ne détruit jamais un fichier HORS de chez l'app » est née le
    31/08 pour le seul converter (et, par le générateur, pour les jumelles). Mesuré le 2026-09-22
    sur tout le parc : les 10 autres apps détruisaient un fichier qu'elles ne faisaient que
    RÉFÉRENCER — perte réelle pour les deux pointeurs vivants (`text_file` du synthesizer quand on
    importe un fichier déjà sur le serveur, `audio_input` de l'avatarizer par un lot `-i`) :
    effacer la card effaçait l'original dans le temp de l'utilisateur. La règle vit désormais ICI,
    une fois, pour toutes les apps. Le domicile vient de `app_media_dir` — jamais recomposé.
    """
    owner = _owner_id(instance)
    if owner is None or not file_name:
        return False
    from wama.common.utils.media_paths import app_media_dir
    home = app_media_dir(instance._meta.app_label, owner, '')
    return file_name.replace('\\', '/').startswith(home)


def safe_delete_file(instance, field_name: str) -> bool:
    """
    ⚠ Depuis le 2026-09-30, RÉSERVÉ au REMPLACEMENT d'un fichier par SA card (l'ancien rendu
    qu'une relance régénère, un fichier de travail interne d'une tâche). Une card qu'on RETIRE
    ne supprime plus ses fichiers : elle les LIBÈRE (`release_card_file`), l'utilisateur est
    prévenu et la suppression reste un geste explicite (décision de Fabien).

    Delete a FileField's physical file only if it is the card's OWN file and no other row
    still uses it.

    Two rules, both required:
      * OWNERSHIP — the file lives in the app's home for the card's owner (`owns_file`). A file
        the card only REFERENCES (the user's temp, the media library, a mount) is never
        destroyed: deleting the card removes the link, not the original.
      * SHARING — no other row references the same path, IN ANY MODEL (`is_shared_elsewhere`,
        widened on 2026-09-23). `duplicate_instance` shares files by contract, and so does an
        input designated across apps: deleting one holder must never break another.

    Args:
        instance:   The model instance that is about to be deleted from the DB.
        field_name: The name of the FileField attribute (e.g. 'audio', 'input_file').

    Returns:
        True  — file was deleted.
        False — file was kept (not the app's own file, still shared, empty field, or the
                deletion failed).
    """
    field = getattr(instance, field_name, None)
    if field is None or not field.name:
        return False

    file_name = field.name          # relative path stored in the DB column
    if not owns_file(instance, file_name) or is_shared_elsewhere(instance, field_name, file_name):
        return False
    try:
        field.delete(save=False)
        return True
    except Exception:
        return False


def release_card_file(instance, field_name: str) -> bool:
    """Une card que l'utilisateur RETIRE (supprimer, tout effacer, lot) LIBÈRE son fichier : il
    reste sur le disque, l'utilisateur en est prévenu, et c'est LUI qui le supprime s'il le veut
    (décision de Fabien, 2026-09-30 — `common/services/released_files.py`).

    Mêmes deux règles que `safe_delete_file`, qui décident si le fichier DEVIENT orphelin :
      * il appartient à la card (`owns_file`) — un fichier qu'elle ne faisait que RÉFÉRENCER
        (temp, médiathèque, montage) reste à sa place et n'est pas signalé : il a son propre maître ;
      * aucune autre ligne, d'aucun modèle, ne le porte (`is_shared_elsewhere`).
    Rend `True` si le fichier vient d'être libéré (noté, à annoncer), `False` sinon. Ne lève jamais.
    """
    field = getattr(instance, field_name, None)
    if field is None or not field.name:
        return False
    file_name = field.name
    try:
        if not owns_file(instance, file_name) or is_shared_elsewhere(instance, field_name, file_name):
            return False
        return _note_released(instance, field_name, file_name)
    except Exception:
        return False


def _note_released(instance, field_name: str, file_name: str) -> bool:
    """Note le fichier comme libéré par cette card (qui, quand, d'où) ; le fichier n'est pas touché."""
    from django.contrib.auth import get_user_model
    from wama.common.services.released_files import release_path
    owner = _owner_id(instance)
    user = get_user_model().objects.filter(pk=owner).first() if owner else None
    return release_path(file_name, user,
                        origin=f'{instance._meta.label}#{instance.pk} · {field_name}') is not None


def release_card_files(instance) -> int:
    """Le retrait à l'échelle de la CARD : elle libère TOUT ce qu'elle porte, lu de ses
    déclarations — jamais d'une liste de champs écrite dans la vue (2026-10-01).

      * chacun de ses `FileField` (`release_card_file`) — la même énumération que l'aperçu de la
        confirmation (`released_files.freed_by`) et que la purge de rétention : le geste ne peut
        donc plus libérer autre chose que ce que son aperçu a annoncé ;
      * chaque entrée de ses LISTES DE CHEMINS déclarées (`file_references.listed_paths`), sous
        les deux mêmes règles : elle vit chez l'app de la card, et aucun champ fichier du dépôt
        ne la désigne.

    Né du reste que la décision D34 laissait : les images de l'imager (`generated_images`, une
    liste et non un `FileField`) étaient EFFACÉES à la main au retrait de la card, sans règle de
    propriété ni de partage, alors que sa vidéo était libérée. Rend le nombre de fichiers libérés.
    Ne lève jamais.
    """
    from django.db import models as dj_models
    from wama.common.utils.file_references import is_referenced_elsewhere, listed_paths
    released = 0
    for f in instance._meta.concrete_fields:
        if isinstance(f, dj_models.FileField) and release_card_file(instance, f.name):
            released += 1
    try:
        for field_name, file_name in listed_paths(instance):
            if (owns_file(instance, file_name)
                    and not is_referenced_elsewhere(file_name, label=instance._meta.label,
                                                    pk=instance.pk, field=field_name)
                    and _note_released(instance, field_name, file_name)):
                released += 1
    except Exception:
        pass
    return released


def is_shared_elsewhere(instance, field_name: str, file_name: str) -> bool:
    """Une AUTRE ligne désigne-t-elle ce fichier — DANS N'IMPORTE QUEL MODÈLE ?

    La moitié PARTAGE de `safe_delete_file`, nommée à part le 2026-09-22 à la demande de
    l'instance qui remplace les voix SYSTÈME : un `SystemAsset` n'a pas de propriétaire, donc la
    règle de propriété ne s'y applique pas — mais celle du partage, si. Un appelant hors card
    emploie CETTE fonction, jamais `safe_delete_file`, dont la règle de propriété refuserait tout
    fichier sans propriétaire.

    ⚠⚠ **ÉLARGIE LE 2026-09-23** : elle ne regardait que le MÊME modèle et le MÊME champ. Cela
    suffisait tant que le partage venait de « Dupliquer » (une card copiée dans sa propre app) ;
    mesuré sur les données réelles, le partage ENTRE apps existe déjà — trois jobs du converter
    désignent un fichier rangé chez l'anonymizer, et la voix de la médiathèque partage son fichier
    avec la voix clonée du synthesizer. La garde locale les tenait pour non partagés : supprimer la
    dernière card de l'app propriétaire détruisait le fichier d'une autre app. *Une garde qui ne
    regarde que sa propre famille ne voit pas le partage qui compte.* Le balayage global vit dans
    `file_references.is_referenced_elsewhere` ; la vérification LOCALE reste tentée d'abord, parce
    qu'elle répond en une requête dans le cas le plus fréquent (une duplication).
    """
    local = (type(instance).objects
             .filter(**{field_name: file_name})
             .exclude(pk=instance.pk)
             .exists())
    if local:
        return True
    from wama.common.utils.file_references import is_referenced_elsewhere
    return is_referenced_elsewhere(file_name, label=instance._meta.label,
                                   pk=instance.pk, field=field_name)


def delete_file_unless_shared(instance, field_name: str) -> bool:
    """Suppression VOULUE du fichier d'un objet — mais jamais s'il en reste un porteur.

    Pour les gestes où l'utilisateur supprime délibérément l'objet ET ses octets : une voix ou un
    asset de sa médiathèque, une ligne de son index de fichiers. La règle de PROPRIÉTÉ de
    `safe_delete_file` n'y a pas de sens (l'asset n'appartient pas à une app), celle du PARTAGE, si
    — et c'est elle qui manquait : mesuré le 2026-09-23, supprimer la voix de la médiathèque
    effaçait le fichier que la voix clonée du synthesizer désigne encore.

    Rend `True` si le fichier a été supprimé, `False` s'il a été gardé (partagé, champ vide, ou
    échec). Ne lève jamais.
    """
    field = getattr(instance, field_name, None)
    if field is None or not field.name:
        return False
    if is_shared_elsewhere(instance, field_name, field.name):
        return False
    try:
        field.delete(save=False)
        return True
    except Exception:
        return False


def is_received(instance, user) -> bool:
    """La card appartient-elle à QUELQU'UN D'AUTRE que `user` (une card qu'on lui a partagée) ?"""
    owner = _owner_id(instance)
    return owner is not None and getattr(user, 'pk', None) is not None and owner != user.pk


def duplicate_instance(instance, reset_fields=None, clear_fields=None, *, for_user=None):
    """
    Create a new DB row that shares the same input file(s) as the original.

    Files are NOT copied. The new row gets the same FileField path as the original.
    Use release_card_file() in the delete view of the app: a file still shared with a
    duplicate stays untouched, and is released only when its last referencing row goes.

    ``for_user`` (2026-10-01, `WAMA_COLLABORATION §3bis` — « dupliquer une card reçue ») : quand
    la card appartient à quelqu'un d'autre, la copie devient l'objet de ``for_user`` — elle lui
    appartient, elle est privée, elle sort du lot du propriétaire, et chacun de ses fichiers est
    COPIÉ chez lui (règle accordée par Fabien : *après le geste, la card ne désigne plus que des
    fichiers de son propriétaire* — le propriétaire peut supprimer les siens sans casser la copie).
    Sa propre card : comportement inchangé (fichiers PARTAGÉS, pas recopiés).

    Args:
        instance:     Source model instance. Not mutated.
        reset_fields: dict {field_name: value} applied to the new row.
                      Typical: {'status': 'PENDING', 'progress': 0, 'task_id': ''}
        clear_fields: list of field names to blank/nullify on the new row.
                      FileFields and nullable fields → None if null=True, else ''.
                      Use for output files and result/text fields that must start empty.
        for_user:     who asks for the copy (None = the owner, as before).

    Returns:
        The new, saved model instance.
    """
    model_class = type(instance)
    received = for_user is not None and is_received(instance, for_user)

    # Fetch a clean copy from the DB so we don't mutate the caller's in-memory object
    obj = model_class.objects.get(pk=instance.pk)
    obj.pk = None
    obj._state.adding = True
    if received:
        _make_own(obj, for_user)

    if reset_fields:
        for field_name, value in reset_fields.items():
            setattr(obj, field_name, value)

    if clear_fields:
        for field_name in clear_fields:
            try:
                field_meta = obj._meta.get_field(field_name)
                if getattr(field_meta, 'null', False):
                    setattr(obj, field_name, None)
                else:
                    setattr(obj, field_name, '')
            except Exception:
                # Field not found or unexpected type — best effort
                try:
                    setattr(obj, field_name, None)
                except Exception:
                    pass

    obj.save()
    if received:
        _copy_files_to(obj, for_user)
    return obj


def _make_own(obj, user):
    """La copie d'une card reçue devient l'objet de `user` : propriétaire, visibilité privée, et
    hors du lot du propriétaire d'origine (une FK directe vers un lot est vidée — l'app la range
    ensuite comme une card neuve)."""
    from django.db import models as dj_models
    from wama.common.utils.batch_common import batch_model_for
    for name, value in (('user', user), ('visibility', 'private'), ('scope_org_unit', None),
                        ('scope_project', None)):
        if any(f.name == name for f in obj._meta.concrete_fields):
            setattr(obj, name, value)
    batch_model = batch_model_for(type(obj))
    for f in obj._meta.concrete_fields:
        if (isinstance(f, dj_models.ForeignKey) and batch_model is not None
                and f.related_model is batch_model and f.null):
            setattr(obj, f.name, None)


def _copy_files_to(obj, user):
    """Chaque fichier que la copie désigne est COPIÉ chez `user` (dossier d'entrée de l'app), et la
    copie le désigne là. La provenance (`kind='app'`) garde l'adresse de l'original."""
    import os
    from django.conf import settings
    from django.db import models as dj_models
    from wama.common.utils.media_paths import copy_into_app_input
    changed = []
    for f in obj._meta.concrete_fields:
        if not isinstance(f, dj_models.FileField):
            continue
        name = getattr(getattr(obj, f.name, None), 'name', '') or ''
        source = os.path.join(settings.MEDIA_ROOT, name) if name else ''
        if not name or not os.path.isfile(source):
            continue
        try:
            _dest, rel = copy_into_app_input(source, obj._meta.app_label, user.pk,
                                             for_instance=obj, field=f.name,
                                             provenance_kind='app', provenance_ref=name)
        except Exception as exc:  # pragma: no cover — la copie reste utilisable sans ce fichier
            logger.warning('[duplicate] copie de %s pour %s impossible : %s', name, user, exc)
            continue
        setattr(obj, f.name, rel)
        changed.append(f.name)
    if changed:
        obj.save(update_fields=changed)
