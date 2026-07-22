"""
source_ingest — Ingest média DÉCLARATIF et COMMUN (hors common/manifests/**).

Comble le trou #14 (WAMA_APP_GENERATION_ROUTE.md §11) : télécharger
`source_url` → FileField n'était pas mutualisé (describer et transcriber
réécrivaient chacun le maillon). Ici l'app DÉCLARE sa spec d'ingest sur le modèle
(attribut de classe `WAMA_INGEST`, stopgap avant la facette manifeste F5) et UN
mécanisme commun fait tout, en réutilisant les primitives communes existantes
(`url_ingest.fetch_url_content`, `video_utils.upload_media_from_url` /
`download_youtube_audio`).

Déclaration (attribut de classe du modèle) :

    class Transcript(models.Model):
        WAMA_INGEST = {
            'source': 'source_url',   # CharField portant l'URL/chemin (défaut 'source_url')
            'target': 'audio',        # FileField cible où sauver le fichier téléchargé
            'mode': 'audio',          # 'audio' | 'media' | 'smart'
            'title_field': 'title',   # (option) rempli avec le titre/nom si vide
            'name_field': 'filename', # (option) rempli avec le basename
            'size_field': 'file_size',# (option) rempli avec la taille en octets
        }

Modes :
    'audio' : plateformes média → download_youtube_audio (audio yt-dlp) ; sinon → upload_media_from_url
    'media' : upload_media_from_url (tout fichier : image/vidéo/audio/document/archive)
    'smart' : fetch_url_content (page web → texte lisible / média → download + sniff HTML)

→ Adopter l'entrée URL sur une app = déclarer `WAMA_INGEST` + appeler
`ensure_local_input(instance)` en tête de sa tâche. Plus de wrapper par app.
"""
import os
import tempfile
import shutil

from django.core.files import File


def _download(url, mode, dest_dir):
    """Retourne (chemin_local, titre) selon le mode, via les primitives communes."""
    from wama.common.utils.video_utils import upload_media_from_url

    if mode == 'audio':
        from wama.common.utils.url_ingest import MEDIA_PLATFORM_DOMAINS
        from wama.common.utils.video_utils import download_youtube_audio
        if any(d in url for d in MEDIA_PLATFORM_DOMAINS):
            path, title = download_youtube_audio(url, dest_dir)
            return path, (title or '')
        return upload_media_from_url(url, dest_dir), ''

    if mode == 'smart':
        from wama.common.utils.url_ingest import fetch_url_content
        return fetch_url_content(url, dest_dir), ''

    # défaut : 'media'
    return upload_media_from_url(url, dest_dir), ''


def ensure_local_input(instance, *, console=None, derive=None):
    """Si `instance` déclare `WAMA_INGEST` et a une URL dans son champ source mais
    pas de fichier dans son champ target, télécharge et sauve. No-op sinon.

    Idempotent (ne re-télécharge pas si le target a déjà un fichier). Réutilisable
    par toute app : appeler en tête de tâche.

    - console : callback optionnel `console(message)` pour journaliser.
    - derive  : hook optionnel `derive(instance, path, fname) -> list[str]` pour
      renseigner des champs spécifiques app (ex. describer.detected_type) AVANT le
      save ; retourne la liste des champs qu'il a positionnés.

    Retourne le nom de fichier téléchargé (str) ou None si no-op.
    """
    spec = getattr(type(instance), 'WAMA_INGEST', None)
    if not spec:
        return None

    source_field = spec.get('source', 'source_url')
    target_field = spec['target']
    mode = spec.get('mode', 'media')

    url = (getattr(instance, source_field, '') or '').strip()
    target = getattr(instance, target_field)
    if (target and target.name) or not url:
        return None

    temp_dir = tempfile.mkdtemp()
    try:
        path, title = _download(url, mode, temp_dir)
        fname = os.path.basename(path)

        with open(path, 'rb') as fh:
            target.save(fname, File(fh), save=False)
        update_fields = [target_field]

        name_field = spec.get('name_field')
        if name_field and not getattr(instance, name_field, ''):
            setattr(instance, name_field, fname)
            update_fields.append(name_field)

        size_field = spec.get('size_field')
        if size_field:
            setattr(instance, size_field, os.path.getsize(path))
            update_fields.append(size_field)

        title_field = spec.get('title_field')
        if title_field and not getattr(instance, title_field, ''):
            setattr(instance, title_field, title or fname)
            update_fields.append(title_field)

        if derive:
            update_fields.extend(derive(instance, path, fname) or [])

        instance.save(update_fields=update_fields)
        if console:
            console(f"Média téléchargé depuis l'URL : {fname}")
        return fname
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
