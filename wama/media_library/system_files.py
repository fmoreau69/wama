"""
Verser UN fichier dans la médiathèque comme élément SYSTÈME (`SystemAsset`) — la brique commune.

POURQUOI ICI (extrait le 2026-09-28). Ce corps vivait dans `common/tts/voice_refs.py` sous le nom
`ingest_voice_file`, écrit pour les voix. Le deuxième consommateur est arrivé avec les jeux
d'ÉVALUATION ASR (SUMM-RE : une réunion mixée = nature `speech`, sa référence = `document`) : le
recopier aurait dupliqué précisément ses parties difficiles — le REMPLACEMENT qui retire l'ancien
fichier seulement s'il n'est plus désigné ailleurs, et la reprise du nom propre après un suffixe
de collision. La voix y délègue désormais, et ne garde que ce qui est à elle (attributs dérivés de
son identifiant, durée d'un WAV).
"""
from __future__ import annotations

import os
from pathlib import Path


def ingest_system_file(asset_type: str, name: str, path, *, attributes: dict | None = None,
                       mime_type: str = '', duration: float | None = None, source_url: str = '',
                       license: str = '', description: str = '', replace: bool = False):
    """`SystemAsset(asset_type)` nommé `name`, fichier copié depuis `path`. Idempotent : un nom déjà
    porté est rendu tel quel (ou son fichier REMPLACÉ si `replace`). Le stockage Django COPIE sous
    `media_library/system/` (`upload_to` décide du domicile) — l'appelant décide du sort de
    l'original."""
    from django.core.files import File

    from wama.media_library.models import SystemAsset

    path = Path(path)
    existing = SystemAsset.objects.filter(asset_type=asset_type, name=name).first()
    if existing is not None and not replace:
        return existing

    asset = existing or SystemAsset(name=name, asset_type=asset_type)
    old_file = asset.file.name if (existing is not None and asset.file) else ''
    if attributes is not None:
        asset.attributes = attributes
    if mime_type:
        asset.mime_type = mime_type
    asset.file_size = path.stat().st_size
    asset.duration = duration
    if source_url:
        asset.source_url = source_url
    if license:
        asset.license = license
    if description:
        asset.description = description
    with open(path, 'rb') as fh:
        asset.file.save(path.name, File(fh), save=False)
    try:
        asset.save()
    except Exception:
        # Refusé (attribut hors vocabulaire de la nature…) : le fichier vient d'être ÉCRIT et
        # aucune ligne ne le désigne. Vécu le 2026-09-28 : l'orphelin gardait le nom propre, et
        # l'essai suivant a pris un suffixe de collision que `settle_file_name` ne peut rendre.
        asset.file.storage.delete(asset.file.name)
        raise
    # REMPLACER, c'est aussi retirer l'ancien fichier — sinon chaque remplacement laisse un
    # orphelin. Mesuré le 2026-09-22 : 3 passages de retéléchargement avaient laissé 14 WAV que
    # plus aucune ligne ne référençait. Ordre : la ligne d'abord (posée ci-dessus), le fichier
    # ensuite ; et jamais s'il est encore référencé ailleurs.
    # ⚠ PAS `safe_delete_file` : c'est la brique des CARDS, et depuis le 22/09 elle exige aussi la
    # PROPRIÉTÉ — le fichier doit vivre dans `users/<uid>/<app>/`. Un `SystemAsset` n'a PAS de
    # propriétaire, par conception (`MEDIA_STORAGE_TIERING §8bis`) : elle refuserait toujours, en
    # silence. Seule la règle de PARTAGE vaut ici — sa moitié nommée à part, `is_shared_elsewhere`.
    if old_file and old_file != asset.file.name:
        from wama.common.utils.queue_duplication import is_shared_elsewhere
        if not is_shared_elsewhere(asset, 'file', old_file):
            asset.file.storage.delete(old_file)
    settle_file_name(asset, path.name)
    return asset


def settle_file_name(asset, wanted: str) -> None:
    """Rend au fichier son nom propre quand le stockage a dû le suffixer.

    En remplacement, le nouveau fichier s'écrit PENDANT que l'ancien existe encore (la ligne
    d'abord, le fichier ensuite) : Django évite la collision par un suffixe aléatoire
    (`male_adult_1_en_HtZSn0F.wav`). Une fois l'ancien retiré, le nom propre est libre : on le
    reprend. Constat de Fabien, 22/09 : *« les médias sont en vrac »*.
    """
    current = Path(asset.file.path)
    target = current.with_name(wanted)
    if current.name == wanted or target.exists():
        return
    os.replace(current, target)
    asset.file.name = str(Path(asset.file.name).with_name(wanted)).replace('\\', '/')
    asset.save(update_fields=['file'])
