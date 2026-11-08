from django.apps import AppConfig


class ReaderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.reader'
    verbose_name = 'Reader — OCR Document'

    def ready(self):
        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchReadingItemLink
            register_batch_sync(BatchReadingItemLink)
        except Exception:
            pass

        from wama.common.utils.preview_utils import register_app_preview
        from .models import ReadingItem
        register_app_preview('reader', ReadingItem, file_field='input_file')

        # Rendu des formats de sortie (late-binding, §6.4) — celui des téléchargements, déclaré
        # pour le geste commun « ranger en médiathèque » (2026-09-18). Chemin pointé, résolu à
        # l'usage.
        from wama.common.utils.export_formats import (register_export_builder,
                                                      register_export_missing)
        register_export_builder('reader', 'wama.reader.views:build_reading_bytes')
        # `json` suppose le résultat BRUT du moteur : un élément qui n'en a pas ne l'offre pas —
        # ni au bouton ⬇ de sa card, ni dans la visionneuse (2026-10-13, la règle vivait dans le
        # seul gabarit de la card). Une PARTITION lue (2026-11-08) n'offre que ses deux formats,
        # un texte lu jamais ceux d'une partition — lus par leur GROUPE au vocabulaire commun, jamais
        # recopiés de la déclaration d'`APP_CATALOG`.
        def _missing(item):
            from wama.common.utils.export_formats import SCORE, entries_for_app
            from wama.reader.function_specs import has_read_score
            score = has_read_score(item)
            other_nature = tuple(e['value'] for e in entries_for_app('reader')
                                 if (e['group'] == SCORE) != score)
            return other_nature + (() if score or getattr(item, 'raw_result', None) else ('json',))
        register_export_missing('reader', _missing)

        # Versions GARDÉES de la partition lue (2026-11-08, le patron du composer) : chaque
        # révision copie son ABC — produite, ou corrigée à la main sur la page « Éditer la
        # partition » —, que la brique « Versions » reprend.
        from wama.common.services.revisions import keep_outputs
        keep_outputs('reader', keep=20, fields=('score_file',))

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — SPEC déclarative
        # (A3a) : reader = OCR documents (source_type constant), sortie = texte (clé
        # canonique result_text), moteur demandé vs effectif.
        from wama.common.utils.detail_registry import register_app_detail_spec
        register_app_detail_spec('reader', ReadingItem, {
            'source_file': 'input_file',
            'source_type': {'const': 'document'},
            'engine': 'backend',
            'engine_effective': 'used_backend',
            'result_text': 'result_text',
            # La partition lue (2026-11-08) : le fichier de sortie d'une page lue comme partition.
            'result_file': 'score_file',
            # Le titre lu sur la partition (2026-11-08) : il nomme le lot de pages et la card.
            'content_title': 'read_title',
            'extra': [
                {'label': 'Mode de lecture', 'field': 'mode', 'display': True},
                {'label': 'Langue', 'field': 'language'},
                {'label': 'Pages', 'field': 'page_count'},
                {'label': 'Titre lu', 'field': 'read_title'},
                {'label': 'Page lue', 'field': 'score_page'},
            ],
        })
