"""
Content type detection utilities.
"""

import os

# Valeurs HISTORIQUES de `detected_type` en base → vocabulaire courant. Normaliser à la
# lecture, en UN point de passage par consommateur qui DÉCIDE (workers + groupement de lot).
# ('text' et 'pdf' ont FUSIONNÉ dans 'document' le 2026-08-30, arbitrage taxonomie — même
# doctrine que data_types.LEGACY_TYPE_ALIASES : les migrations sont gitignorées, une migration
# de données n'atteindrait jamais une autre installation.)
LEGACY_DETECTED_TYPE_ALIASES = {'text': 'document', 'pdf': 'document'}

#: Le domaine du describer (`app_modes.APP_MODES['describer']`) — il n'en a qu'un.
DOMAIN = 'description'


def normalize_detected_type(value):
    return LEGACY_DETECTED_TYPE_ALIASES.get(value, value)


def file_nature(name, app: str = 'describer') -> str:
    """La nature d'un fichier pour le describer — image, video, audio ou document —, lue à la
    taxonomie COMMUNE par son domaine (`app_modes.domain_nature`, 2026-11-01). `app` re-cible une
    jumelle. Ce qu'il ne prend pas comme image, vidéo ou son est un document : son backend texte
    lit une page web, un `.json`, un `.xml`.

    ⚠ Jusqu'au 2026-11-01, cinq jeux d'extensions écrits ici et TROIS classeurs (celui-ci, avec un
    repli `mimetypes`, `views.detect_type_from_extension` et le groupement de lot) : un `.aiff`,
    un `.heif`, un `.qt` ou un `.ts` que la zone de dépôt acceptait étaient décrits comme des
    DOCUMENTS (`mimetypes` lit un `.ts` comme une traduction Qt Linguist, pas une vidéo MPEG-TS)."""
    from wama.common.utils.app_modes import domain_nature
    return domain_nature(app, DOMAIN, os.path.basename(str(name or ''))) or 'document'


def get_file_info(file_path: str) -> dict:
    """Get basic file information."""
    info = {
        'path': file_path,
        'exists': os.path.exists(file_path),
        'size': 0,
        'extension': '',
    }

    if info['exists']:
        info['size'] = os.path.getsize(file_path)
        if '.' in file_path:
            info['extension'] = file_path.rsplit('.', 1)[-1].lower()

    return info
