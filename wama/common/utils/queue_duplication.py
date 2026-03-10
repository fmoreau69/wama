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
- safe_delete_file() checks the DB for other rows referencing the same path before
  calling FileField.delete(). This prevents orphaning a file still used by a duplicate.
- duplicate_instance() fetches a fresh DB copy of the row to avoid mutating the
  caller's in-memory object.
"""


def safe_delete_file(instance, field_name: str) -> bool:
    """
    Delete a FileField's physical file only if no other DB row references the same path.

    When a queue item has been duplicated, its input file is shared between the original
    and the duplicate. Calling field.delete() on either row would remove the file and
    break the other. This function checks first.

    Args:
        instance:   The model instance that is about to be deleted from the DB.
        field_name: The name of the FileField attribute (e.g. 'audio', 'input_file').

    Returns:
        True  — file was deleted (no other references found).
        False — file was kept (at least one other row still references it, or the field
                was empty, or deletion failed silently).
    """
    field = getattr(instance, field_name, None)
    if field is None or not field.name:
        return False

    file_name = field.name          # relative path stored in the DB column
    model_class = type(instance)

    # Count rows (excluding the current one) that point to the same file
    other_refs = (
        model_class.objects
        .filter(**{field_name: file_name})
        .exclude(pk=instance.pk)
        .count()
    )

    if other_refs == 0:
        try:
            field.delete(save=False)
            return True
        except Exception:
            pass

    return False


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
