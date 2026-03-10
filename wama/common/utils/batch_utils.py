"""
WAMA Common — Batch utilities

Shared infrastructure for batch operations across WAMA apps.

Currently contains synthesizer-specific helpers. When other apps add batch
support, extract the generic pattern by:
  - Adding abstract models in wama/common/models/batch.py
    (AbstractBatch, AbstractBatchItem with shared fields/logic)
  - Replacing duplicate_synthesizer_batch() with a generic
    duplicate_batch(batch, synthesis_reset_fn, item_create_fn)
    that accepts app-specific callables for the variable parts.
"""

from .queue_duplication import duplicate_instance


def duplicate_synthesizer_batch(batch):
    """
    Duplicate a BatchSynthesis with all its VoiceSynthesis items.

    - New BatchSynthesis shares the same batch_file CSV (no physical copy)
    - Each VoiceSynthesis is duplicated via duplicate_instance()
      (input files shared, results cleared, status reset to PENDING)
    - Returns the new BatchSynthesis instance

    Note: safe_delete_file() in batch_delete() will correctly handle shared
    batch_file and text_file/voice_reference paths when either batch is deleted.
    """
    from wama.synthesizer.models import BatchSynthesis, BatchSynthesisItem

    # Create new batch sharing the same batch_file (same CSV path, no copy)
    new_batch = BatchSynthesis(
        user=batch.user,
        total=batch.total,
    )
    if batch.batch_file and batch.batch_file.name:
        new_batch.batch_file = batch.batch_file.name
    new_batch.save()

    # Duplicate each synthesis item in order
    for item in batch.items.select_related('synthesis').order_by('row_index'):
        s = item.synthesis
        if not s:
            continue
        new_s = duplicate_instance(
            s,
            reset_fields={
                'status': 'PENDING',
                'progress': 0,
                'task_id': '',
                'properties': '',
                'error_message': '',
            },
            clear_fields=['audio_output'],
        )
        BatchSynthesisItem.objects.create(
            batch=new_batch,
            synthesis=new_s,
            output_filename=item.output_filename,
            row_index=item.row_index,
        )

    return new_batch
