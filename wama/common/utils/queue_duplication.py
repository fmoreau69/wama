"""
WAMA — Common utilities for queue item duplication and safe file deletion.

Usage across apps
-----------------
1. In the app's delete view:
       from wama.common.utils.queue_duplication import safe_delete_file
       safe_delete_file(instance, 'audio')      # only deletes if no other row shares the file

2. In the app's duplicate view:
       from wama.common.utils.queue_duplication import duplicate_instance
       new = duplicate_instance(
           instance,
           reset_fields={'status': 'PENDING', 'progress': 0, 'task_id': ''},
           clear_fields=['output_file', 'result_text'],
       )

Design notes
------------
- Files are NEVER copied on duplication. Both rows point to the same relative path.
- safe_delete_file() destroys a file only if it is the card's OWN file (`owns_file`: it lives
  in the app's home for the card's owner) AND no other row still uses it
  (`is_shared_elsewhere`). A file the card only references is never destroyed; a file still
  used by a duplicate is kept.
- duplicate_instance() fetches a fresh DB copy of the row to avoid mutating the
  caller's in-memory object.
"""


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
    Delete a FileField's physical file only if it is the card's OWN file and no other row
    still uses it.

    Two rules, both required:
      * OWNERSHIP — the file lives in the app's home for the card's owner (`owns_file`). A file
        the card only REFERENCES (the user's temp, the media library, a mount) is never
        destroyed: deleting the card removes the link, not the original.
      * SHARING — no other row of the same model references the same path. `duplicate_instance`
        shares files by contract: deleting the original must not break its copy.

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


def is_shared_elsewhere(instance, field_name: str, file_name: str) -> bool:
    """Une AUTRE ligne du même modèle désigne-t-elle ce fichier dans le même champ ?

    La moitié PARTAGE de `safe_delete_file`, nommée à part le 2026-09-22 à la demande de
    l'instance qui remplace les voix SYSTÈME : un `SystemAsset` n'a pas de propriétaire, donc la
    règle de propriété ne s'y applique pas — mais celle du partage, si. Sans ce nom, elle
    recopiait ces deux lignes. Un appelant hors card emploie CETTE fonction, jamais
    `safe_delete_file`, dont la règle de propriété refuserait tout fichier sans propriétaire.
    """
    return (type(instance).objects
            .filter(**{field_name: file_name})
            .exclude(pk=instance.pk)
            .exists())


def duplicate_instance(instance, reset_fields=None, clear_fields=None):
    """
    Create a new DB row that shares the same input file(s) as the original.

    Files are NOT copied. The new row gets the same FileField path as the original.
    Use safe_delete_file() in the delete view of the app so that shared files are
    only removed from disk when the last referencing row is deleted.

    Args:
        instance:     Source model instance. Not mutated.
        reset_fields: dict {field_name: value} applied to the new row.
                      Typical: {'status': 'PENDING', 'progress': 0, 'task_id': ''}
        clear_fields: list of field names to blank/nullify on the new row.
                      FileFields and nullable fields → None if null=True, else ''.
                      Use for output files and result/text fields that must start empty.

    Returns:
        The new, saved model instance.
    """
    model_class = type(instance)

    # Fetch a clean copy from the DB so we don't mutate the caller's in-memory object
    obj = model_class.objects.get(pk=instance.pk)
    obj.pk = None
    obj._state.adding = True

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
    return obj
