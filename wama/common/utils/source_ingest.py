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
            'derive': 'wama.<app>.tasks._fn',  # (option) champs propres à l'app, cf. plus bas
        }

Modes :
    'audio' : plateformes média → download_youtube_audio (audio yt-dlp) ; sinon → upload_media_from_url
    'media' : upload_media_from_url (tout fichier : image/vidéo/audio/document/archive)
    'smart' : fetch_url_content (page web → `.html` gardé tel quel / média → download + sniff HTML)

QUAND (décision de Fabien, 2026-10-13 — « téléchargement à la création, sans seuil de taille ») :
une URL se télécharge DÈS LA CRÉATION de la card, HORS de la requête — le récepteur `post_save`
branché ici sur tout modèle qui déclare `WAMA_INGEST` met en file la tâche commune
`common.ingest_source` (file `default`, CPU). Une seule règle pour toutes les apps et toutes les
tailles : une page arrive en une seconde, une vidéo de 3 min en une dizaine (mesuré), et aucune
requête n'attend (gunicorn coupe à 120 s). Le lancement garde `ensure_local_input` en tête de
tâche : il rattrape un téléchargement échoué, et ATTEND celui qui est en cours plutôt que de le
refaire (verrou partagé).

`derive` : chemin pointé d'une fonction `derive(instance, path, fname) -> list[str]` qui pose les
champs propres à l'app (la nature du describer, les métadonnées de l'anonymizer) AVANT le save.
DÉCLARÉ ici plutôt que passé par la tâche de l'app : le téléchargement à la création ne passe par
aucune tâche d'app, et la déclaration voyage avec le manifeste (`processing.ingest`). Un chemin
qui ne se résout pas (jumelle aux tâches régénérées) est ignoré, jamais une cause d'échec.
"""
import logging
import os
import tempfile
import shutil
import time

from django.core.files import File

logger = logging.getLogger(__name__)

#: Durée max d'un téléchargement : borne le verrou partagé, donc l'attente du lancement.
LOCK_TTL_S = 2 * 3600
#: Mémoire d'un échec de téléchargement à la création — ce que l'aperçu de l'Entrée affiche.
FAILURE_TTL_S = 7 * 86400


def _download(url, mode, dest_dir):
    """Retourne (chemin_local, titre) selon le mode, via les primitives communes."""
    from wama.common.utils.video_utils import upload_media_from_url

    if mode == 'audio':
        from wama.common.utils.url_ingest import is_media_platform
        from wama.common.utils.video_utils import download_youtube_audio
        if is_media_platform(url):
            path, title = download_youtube_audio(url, dest_dir)
            return path, (title or '')
        return upload_media_from_url(url, dest_dir), ''

    if mode == 'smart':
        from wama.common.utils.url_ingest import fetch_url_content
        return fetch_url_content(url, dest_dir), ''

    # défaut : 'media'
    return upload_media_from_url(url, dest_dir), ''


def _spec(instance):
    return getattr(type(instance), 'WAMA_INGEST', None)


def _source_url(instance, spec) -> str:
    return (getattr(instance, spec.get('source', 'source_url'), '') or '').strip()


def _has_target(instance, spec) -> bool:
    target = getattr(instance, spec['target'], None)
    return bool(target and target.name)


def _key(instance, what='lock') -> str:
    return f"source_ingest:{what}:{instance._meta.label_lower}:{instance.pk}"


def _declared_derive(spec):
    """La fonction `derive` DÉCLARÉE par la spec (chemin pointé), ou None — jamais une erreur."""
    path = spec.get('derive')
    if not path:
        return None
    try:
        from django.utils.module_loading import import_string
        return import_string(path)
    except Exception as exc:
        logger.warning("[source_ingest] derive %s introuvable — ignoré : %s", path, exc)
        return None


def _wait_for_running_download(instance, spec):
    """Un autre processus télécharge cette entrée (verrou pris) : attendre qu'il ait fini, puis
    relire la cible. Rend le nom du fichier s'il est arrivé, None sinon."""
    from django.core.cache import cache
    deadline = time.monotonic() + LOCK_TTL_S
    while cache.get(_key(instance)) and time.monotonic() < deadline:
        time.sleep(1)
    instance.refresh_from_db(fields=[spec['target']])
    target = getattr(instance, spec['target'])
    return target.name if target and target.name else None


def ensure_local_input(instance, *, console=None, derive=None):
    """Si `instance` déclare `WAMA_INGEST` et a une URL dans son champ source mais
    pas de fichier dans son champ target, télécharge et sauve. No-op sinon.

    Idempotent (ne re-télécharge pas si le target a déjà un fichier) et EXCLUSIF : un seul
    processus télécharge une entrée donnée — l'autre attend son résultat (création et lancement
    rapprochés). Réutilisable par toute app : appelé en tête de tâche ET à la création.

    - console : callback optionnel `console(message)` pour journaliser.
    - derive  : hook optionnel `derive(instance, path, fname) -> list[str]` ; à défaut, celui que
      DÉCLARE la spec (`'derive'`).

    Retourne le nom de fichier téléchargé (str) ou None si no-op.
    """
    spec = _spec(instance)
    if not spec:
        return None

    target_field = spec['target']
    mode = spec.get('mode', 'media')
    url = _source_url(instance, spec)
    if _has_target(instance, spec) or not url:
        return None

    from django.core.cache import cache
    if not cache.add(_key(instance), 1, LOCK_TTL_S):
        if console:
            console("Téléchargement de l'entrée déjà en cours — attente de son résultat")
        return _wait_for_running_download(instance, spec)

    temp_dir = tempfile.mkdtemp()
    try:
        # Relu SOUS le verrou : un téléchargement a pu finir entre la lecture de l'appelant et ici.
        instance.refresh_from_db(fields=[target_field])
        if _has_target(instance, spec):
            return None
        derive = derive or _declared_derive(spec)
        path, title = _download(url, mode, temp_dir)
        fname = os.path.basename(path)
        target = getattr(instance, target_field)

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
        cache.delete(_key(instance, 'failed'))
        # Provenance (troisième site annoncé par `utils/provenance.py`, câblé le 2026-09-22) :
        # l'entrée matérialisée se souvient de son URL. Ne fait jamais échouer le geste.
        from wama.common.utils.provenance import record_provenance
        record_provenance(instance, target_field, kind='url', ref=url,
                          original_name=fname, source_path=path)
        if console:
            console(f"Média téléchargé depuis l'URL : {fname}")
        return fname
    finally:
        cache.delete(_key(instance))
        shutil.rmtree(temp_dir, ignore_errors=True)


def ingest_state(instance):
    """Ce que l'Entrée d'une card peut dire de sa SOURCE distante tant que le fichier manque :
    `{'url', 'state': 'downloading'|'failed', 'error'}`, ou None (pas d'URL, ou fichier là).
    Lu par l'aperçu commun — la card montrait « Aucun aperçu » et rien d'autre."""
    spec = _spec(instance)
    if not spec:
        return None
    url = _source_url(instance, spec)
    if not url or _has_target(instance, spec):
        return None
    try:
        from django.core.cache import cache
        error = cache.get(_key(instance, 'failed')) or ''
    except Exception:
        error = ''
    return {'url': url, 'state': 'failed' if error else 'downloading', 'error': error}


def ingest_now(instance):
    """Le téléchargement DE CRÉATION (tâche `common.ingest_source`) : `ensure_local_input`, avec
    le journal dans la console de l'utilisateur, et un échec MÉMORISÉ pour l'aperçu de l'Entrée
    au lieu d'être perdu (le lancement retentera)."""
    app = instance._meta.app_label
    user_id = getattr(instance, 'user_id', None)

    def console(message, level='info'):
        if not user_id:
            return
        try:                                       # journaliser ne fait jamais échouer le geste
            from wama.common.utils.console_utils import push_console_line
            push_console_line(user_id, message, level=level, app=app)
        except Exception:
            logger.debug("[source_ingest] console indisponible", exc_info=True)

    try:
        return ensure_local_input(instance, console=console)
    except Exception as exc:
        from django.core.cache import cache
        cache.set(_key(instance, 'failed'), str(exc)[:500], FAILURE_TTL_S)
        console(f"Échec du téléchargement de l'entrée ({_source_url(instance, _spec(instance))}) : "
                f"{exc} — il sera retenté au lancement", level='error')
        logger.warning("[source_ingest] %s#%s : %s", instance._meta.label, instance.pk, exc)
        return None


def schedule_ingest(instance) -> bool:
    """Met en file le téléchargement de l'entrée d'une card dont la source est une URL http(s)
    et la cible vide. Rend True si une tâche part. Ne lève jamais : une création n'échoue pas
    pour un téléchargement. UNE mise en file par (card, URL) pendant 10 min : le récepteur passe
    à chaque enregistrement, la file ne voit que le premier."""
    spec = _spec(instance)
    if not spec or instance.pk is None:
        return False
    url = _source_url(instance, spec)
    if not url.lower().startswith(('http://', 'https://')) or _has_target(instance, spec):
        return False
    try:
        import hashlib

        from django.core.cache import cache
        from django.db import transaction

        from wama.common.tasks import ingest_source_task
        digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]
        if not cache.add(f"{_key(instance, 'queued')}:{digest}", 1, 600):
            return False
        cache.delete(_key(instance, 'failed'))
        label, name, pk = instance._meta.app_label, instance._meta.model_name, instance.pk
        # `on_commit` et pas `delay()` direct : créée dans une transaction (lot, import), la card
        # n'existe pas encore pour le worker. Hors transaction, on_commit s'exécute aussitôt.
        transaction.on_commit(lambda: ingest_source_task.delay(label, name, pk))
        return True
    except Exception as exc:                      # broker indisponible, etc.
        logger.debug("[source_ingest] mise en file ignorée (%s) — le lancement téléchargera", exc)
        return False


_connected = []


def _on_saved(sender, instance, created, update_fields=None, **kwargs):
    """Récepteur `post_save` : une card qui NAÎT avec une URL, ou dont l'URL change, voit son
    entrée téléchargée tout de suite. Un enregistrement qui ne touche pas à la source
    (progression, statut : `update_fields`) est ignoré."""
    spec = _spec(instance)
    if not spec:
        return
    if update_fields is not None and spec.get('source', 'source_url') not in update_fields:
        return
    schedule_ingest(instance)


def register_source_ingest_receivers():
    """Branche le récepteur sur tout modèle qui DÉCLARE `WAMA_INGEST` — aucune app n'écrit rien.
    Appelé depuis `CommonConfig.ready()`, comme la copie de lecture et l'enrichissement de prompt."""
    from django.apps import apps as django_apps
    from django.db.models.signals import post_save
    for model in django_apps.get_models():
        spec = getattr(model, 'WAMA_INGEST', None)
        if not spec or model in _connected:
            continue
        if not any(f.name == spec.get('source', 'source_url') for f in model._meta.get_fields()):
            continue                     # spec sans son champ source (modèle généré ancien)
        post_save.connect(_on_saved, sender=model,
                          dispatch_uid=f'source_ingest:{model._meta.label}')
        _connected.append(model)
