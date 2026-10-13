"""
WAMA Common - Preview Utilities

Unified preview functionality for all WAMA applications.
Uses the PreviewRegistry to handle different model types.
"""

import os
import mimetypes
import logging

from django.http import HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.encoding import iri_to_uri
from django.contrib.auth.models import User

from .preview_registry import PreviewRegistry

logger = logging.getLogger(__name__)


def get_or_create_anonymous_user():
    """Get or create the anonymous user."""
    user, _ = User.objects.get_or_create(
        username='anonymous',
        defaults={'is_active': True}
    )
    return user


def _mime_category(mime):
    return (mime or '').split('/')[0]


#: Documents sans rendu natif dans le navigateur : leur TEXTE est extrait côté serveur et servi
#: en `content`. Seul l'aperçu du filemanager le savait jusqu'au 2026-10-12 — une card dont
#: l'entrée était un .docx (synthesizer, describer) n'offrait qu'un lien de téléchargement.
OFFICE_TEXT_EXTENSIONS = ('.docx', '.odt', '.rtf')
TEXT_PREVIEW_MAX_CHARS = 10000


def file_face(url, path=None, name=None):
    """Payload d'aperçu d'UN fichier : `{name, url, mime_type}`, plus `content` (le texte
    extrait) pour un document bureautique. LA fabrique de toute face fichier — l'Entrée et la
    Sortie d'une card, et l'aperçu du filemanager (2026-10-12 : chacun avait sa copie, et seul
    le filemanager extrayait le texte).

    Un texte se sert TOUJOURS sous la clé `content`, la seule que lisent le volet et la modale
    (`media-preview.js`). `url` est rendue telle quelle (l'appelant la fait absolue) ; `path`,
    le fichier sur disque, est déduit de l'URL de MEDIA quand l'appelant ne le donne pas."""
    from urllib.parse import unquote

    from .mime_utils import guess_mime_type
    clean = str(url or '').split('?')[0]
    name = name or os.path.basename(unquote(clean)) or 'fichier'
    data = {'name': name, 'url': url,
            'mime_type': guess_mime_type(name) or 'application/octet-stream'}
    if os.path.splitext(name)[1].lower() not in OFFICE_TEXT_EXTENSIONS:
        return data
    path = path or _local_media_path(url)
    if not path:
        return data
    try:
        from wama.synthesizer.utils.text_extractor import extract_text_from_file
        text = extract_text_from_file(str(path))
    except Exception as exc:
        # Le fichier reste téléchargeable : un aperçu ne casse pas pour un extracteur.
        logger.warning(f"Aperçu : texte non extrait de {name} : {exc}")
        return data
    if len(text) > TEXT_PREVIEW_MAX_CHARS:
        text = text[:TEXT_PREVIEW_MAX_CHARS] + '\n\n... [Contenu tronqué]'
    data.update(mime_type='text/plain', content=text)
    return data


def _detail_of(app_name, instance):
    """Le detail canonique de l'élément (`build_detail`, INSPECTOR_DETAIL_FIELDS.md), ou None
    si l'app n'en déclare pas. LA déclaration de ce qu'est son entrée et sa sortie."""
    from .detail_registry import DetailRegistry
    entry = DetailRegistry.get(app_name)
    adapter = entry.get('adapter') if entry else None
    return (adapter(instance) or {}) if adapter else None


def _output_preview_data(app_name, instance, request):
    """Payload preview du RÉSULTAT, dérivé des clés CANONIQUES du detail (`result_file`
    de build_detail — INSPECTOR_DETAIL_FIELDS.md). Zéro code par app : si l'app a un
    adapter detail avec un résultat, la preview de sortie existe. None sinon."""
    try:
        d = _detail_of(app_name, instance)
        if d is None:
            return None
        from .mime_utils import guess_mime_type as _mime
        # Sortie MULTIPLE (2026-08-22) : si l'app déclare la clé canonique `result_files`, la
        # face Sortie sert la COLLECTION — le rendu commun en fait une grille. Le représentant
        # `result_file` reste servi en `url` : un consommateur qui ne connaît pas `files`
        # (studio, modale, anciens appels) continue d'afficher exactement ce qu'il affichait.
        multi = (d or {}).get('result_files')
        if multi and len(multi) > 1:
            repr_url = (d or {}).get('result_file') or multi[0]
            propre = repr_url.split('?')[0]
            return {
                'name': f'{len(multi)} fichiers',
                'url': request.build_absolute_uri(repr_url),
                'mime_type': _mime(propre) or 'application/octet-stream',
                'files': [{'name': os.path.basename(u.split('?')[0]),
                           'url': request.build_absolute_uri(u),
                           'mime_type': _mime(u.split('?')[0]) or 'application/octet-stream'}
                          for u in multi],
            }
        url = (d or {}).get('result_file')
        if not url:
            # Sortie TEXTE (transcriber/describer/reader…) : servir `result_text` inline —
            # SYMÉTRIQUE de l'entrée-prompt. `build_detail` expose déjà cette clé canonique.
            # → la face Sortie existe pour les apps sans fichier de résultat (toggle visible).
            txt = (d or {}).get('result_text')
            if txt:
                return {'name': 'Sortie', 'mime_type': 'text/plain', 'content': str(txt).strip()}
            return None
        return _media_face(url, request)
    except Exception:
        return None


def _media_face(url, request):
    """Face d'un fichier de MEDIA désigné par le detail : absolue, versionnée (`?v=<mtime>`)."""
    return file_face(request.build_absolute_uri(_versioned(url)), path=_local_media_path(url))


def _versioned(url):
    """`url?v=<mtime>` pour un fichier de MEDIA sans requête (2026-09-27).

    Une card relancée RÉÉCRIT sa sortie sous le même nom (anonymizer : un nom par card, pour
    que relancer remplace au lieu d'accumuler) : même URL, donc le navigateur réaffichait
    l'image de son cache — le nouveau réglage semblait sans effet. La date du fichier change
    à chaque écriture, l'URL avec elle. Toute autre URL passe telle quelle.
    """
    from django.conf import settings
    media_url = settings.MEDIA_URL or '/media/'
    if '?' in url or not url.startswith(media_url):
        return url
    from urllib.parse import unquote
    path = os.path.join(str(settings.MEDIA_ROOT), unquote(url[len(media_url):]))
    try:
        return f'{url}?v={int(os.path.getmtime(path))}'
    except OSError:
        return url


#: Au-delà de ce poids, le lecteur commun ne décode pas l'audio pour en dessiner l'onde
#: (`wama-audio-player.js`, MAX_DECODE_BYTES — même valeur) : il n'affichait qu'une ligne de temps.
CLIENT_DECODE_LIMIT_BYTES = 30 * 1024 * 1024


def _media_rel(url):
    """Chemin RELATIF à MEDIA_ROOT d'une URL de MEDIA (absolue ou non, `?v=` toléré), ou None."""
    from urllib.parse import unquote, urlparse
    from django.conf import settings
    media_url = settings.MEDIA_URL or '/media/'
    path = urlparse(str(url or '')).path
    if not path.startswith(media_url):
        return None
    return unquote(path[len(media_url):])


def _local_media_path(url):
    """Chemin disque d'une URL de MEDIA (absolue ou non, `?v=` toléré), ou None."""
    from django.conf import settings
    rel = _media_rel(url)
    if rel is None:
        return None
    local = os.path.join(str(settings.MEDIA_ROOT), rel)
    return local if os.path.isfile(local) else None


def _add_server_peaks(data):
    """PICS d'onde calculés SERVEUR pour un audio trop lourd pour le navigateur (2026-10-04).

    Constat de Fabien : la card YuE2 n'affichait pas son onde, les plus anciennes si. Une chanson
    de 3:52 en flottant 32 bits à 48 kHz pèse 89 Mo — au-delà de la borne de décodage du lecteur,
    qui se rabattait sur une simple ligne de temps ; les sorties de 30 s (5 Mo) passaient.
    Le front DESSINAIT déjà des pics fournis (`wama-inspector.js`, `setPeaks`) : seule la face
    « pendant » en publiait. Brique de calcul commune (`waveform.compute_peaks`, ffmpeg, uint8),
    mise en cache par (fichier, date). Additif : un petit fichier reste décodé par le navigateur."""
    if not data or data.get('peaks') or not str(data.get('mime_type') or '').startswith('audio/'):
        return
    path = _local_media_path(data.get('url'))
    try:
        if not path or os.path.getsize(path) <= CLIENT_DECODE_LIMIT_BYTES:
            return
        key = f'wama_preview_peaks:{path}:{int(os.path.getmtime(path))}'
    except OSError:
        return
    from django.core.cache import cache
    entry = cache.get(key)
    if entry is None:
        from .waveform import compute_peaks
        peaks, duration = compute_peaks(path, buckets=800, dtype='uint8', with_duration=True)
        entry = {'peaks': list(peaks or []), 'duration': duration}
        if entry['peaks']:
            cache.set(key, entry, 86400)
    if entry.get('peaks'):
        data['peaks'] = entry['peaks']
        data.setdefault('duration', entry.get('duration'))


def _input_port_group(app_name):
    """Groupe du port d'ENTRÉE de l'app, lu par l'UNIQUE accesseur de ports `studio_node_ports`.

    Contrat de jonction avec le manifeste (WAMA_MANIFEST_SPEC §preview) : on ne lit JAMAIS
    `app_modes`/`app_registry` directement ici — uniquement `studio_node_ports(app_id)`. Quand le
    manifeste deviendra autoritaire, `studio_node_ports` en sera la projection et cette logique
    héritera sans changer. Règle : l'entrée bind sur le port de TRAVAIL, sinon le PROMPT —
    JAMAIS un port `reference` (la référence conditionne le traitement, elle n'EST pas l'entrée).
    """
    try:
        from wama.common.app_registry import studio_node_ports
        ports = studio_node_ports(app_name) or {}
    except Exception:
        return None
    groups = [p.get('group') for p in (ports.get('inputs') or [])]
    if 'travail' in groups:
        return 'travail'
    if 'prompt' in groups:
        return 'prompt'
    return None


def _work_natures(app_name) -> set:
    """Natures (`MEDIA_CATEGORIES`) qu'acceptent les ports de TRAVAIL de l'app — même accesseur
    unique. Ce qui rend la règle « jamais un port `reference` » applicable à un FICHIER : aucune
    déclaration ne relie un champ de modèle à son jeton de port (`voice_reference` ↔
    `reference_voice`), mais un fichier de travail est de la nature d'un port de travail. Mesuré
    le 2026-10-12 (relecture de l'instance de portage) : sans ce filtre, une synthèse au texte
    SAISI montrait sa voix de référence en face Entrée — sa spec la remonte en `source_file`
    pour le volet. ⚠ Limite : une référence de MÊME nature qu'un port de travail n'est pas
    distinguée ici (aucune app ne la nomme en `source_file` aujourd'hui)."""
    try:
        from wama.common.app_registry import studio_node_ports
        ports = studio_node_ports(app_name) or {}
    except Exception:
        return set()
    return {t for p in (ports.get('inputs') or []) if p.get('group') == 'travail'
            for t in (p.get('types') or [])}


#: Ce que l'adaptateur du registre AJOUTE à la face Entrée, quand il décrit le même fichier.
REGISTERED_METADATA = ('duration', 'resolution', 'properties')


def _input_preview(app_name, instance, request):
    """Face ENTRÉE de la preview. La RÈGLE reste celle de la route (`ROUTE §F3b`,
    `WAMA_MANIFEST_SPEC §preview`) : l'entrée bind sur le port de TRAVAIL, sinon sur le PROMPT,
    jamais sur un port `reference` — groupe lu par l'accesseur unique (`_input_port_group`).

    Ce qui change le 2026-10-12, c'est OÙ se lit le contenu : dans les clés CANONIQUES du detail,
    SYMÉTRIQUES de la face Sortie (`result_file`/`result_text`) —
      - port `prompt` → `source_text` (la consigne), jamais un fichier : une app à consigne qui
        nomme une référence en `source_file` (jumelle writer_01) n'en fait pas son entrée ;
      - port `travail` → `source_file` S'IL est de la nature d'un port de travail
        (`_work_natures`), sinon `source_text` (le texte saisi « l'un ou l'autre » du
        synthesizer, dont la voix de RÉFÉRENCE n'est jamais l'entrée ; la consigne de l'imager
        sans image de travail).
    ⚠ Le port `travail` lisait jusque-là le `file_field` du REGISTRE d'aperçu, une seconde
    déclaration de l'entrée qui avait dérivé : composer et synthesizer y nommaient leur SORTIE
    audio (la face Entrée montrait le résultat, ou une erreur avant lui) ; le générateur l'avait
    constaté (`models_gen.declared_result_fields`) sans que l'aperçu change. Le registre garde ce
    que lui seul sait : le modèle et son propriétaire, les faces propres à l'app, et la
    durée/résolution d'un média (`REGISTERED_METADATA`, reprises si son fichier EST l'entrée).
    Une app sans detail (médiathèque) garde l'adaptateur du registre seul.
    """
    d = _detail_of(app_name, instance)
    if d is None:
        return PreviewRegistry.get_preview_data(app_name, instance, request)
    group = _input_port_group(app_name)
    url = d.get('source_file') if group != 'prompt' else None
    natures = _work_natures(app_name) if url else set()
    if url and natures:
        from wama.common.app_registry import category_of_path
        if category_of_path(str(url).split('?')[0]) not in natures:
            url = None          # pas de la nature d'un port de TRAVAIL : une référence (§F3b)
    if url:
        data = _media_face(url, request)
        data.update(_registered_metadata(app_name, instance, request, url))
        return data
    txt = str(d.get('source_text') or '').strip()
    name = 'Prompt' if group == 'prompt' else 'Entrée'
    return {'name': name, 'mime_type': 'text/plain', 'content': txt} if txt else None


def _registered_metadata(app_name, instance, request, url):
    """Durée, résolution, propriétés que l'adaptateur du registre sait d'un média — reprises
    seulement s'il décrit le fichier d'ENTRÉE (même chemin de MEDIA), jamais un autre."""
    try:
        reg = PreviewRegistry.get_preview_data(app_name, instance, request)
    except Exception:
        return {}
    if not isinstance(reg, dict) or not reg.get('url') or _media_rel(reg['url']) != _media_rel(url):
        return {}
    return {key: reg[key] for key in REGISTERED_METADATA if reg.get(key)}


# ── Phase PENDANT (chantier 2) : preview progressive/temporaire pendant le traitement ──────────
# Contrat de jonction : gâté par la capacité déclarée `during_preview`, lue via
# l'accesseur UNIQUE `app_supports_during_preview` (comme la preview d'entrée lit les ports par
# `studio_node_ports`). Le worker de l'app publie un aperçu partiel courant via `publish_partial`
# (mécanisme = moi ; déclaration du flag + production du partiel = l'app). Dormant tant qu'aucune
# app ne déclare la capacité ET ne publie de partiel.

def _partial_key(app_name, pk):
    return f'wama_partial_preview_{app_name}_{pk}'


def _partial_peaks_key(app_name, pk):
    return f'wama_partial_peaks_{app_name}_{pk}'


def _partial_variants_key(app_name, pk):
    return f'wama_partial_variants_{app_name}_{pk}'


def publish_partial(app_name, pk, url_or_path, variant=None, label=None):
    """Worker : publie l'URL (média) d'un aperçu PARTIEL courant, servi par `?side=during`.
    TTL court (le partiel est éphémère). Appeler `clear_partial` à la fin du traitement.

    `variant` / `label` (2026-10-04) : PLUSIEURS vues du même instant — l'anonymizer publie la
    frame avec ses détections dessinées ET la frame floutée ; l'aperçu offre de passer de l'une
    à l'autre (`?side=during&variant=<clé>`). La dernière variante publiée est la vue par défaut."""
    from django.core.cache import cache
    cache.set(_partial_key(app_name, pk), str(url_or_path), 900)
    if variant:
        variants = cache.get(_partial_variants_key(app_name, pk)) or {}
        variants.pop(variant, None)              # ré-insérée en DERNIER : la vue par défaut
        variants[variant] = {'url': str(url_or_path), 'label': label or variant}
        cache.set(_partial_variants_key(app_name, pk), variants, 900)


class PartialFrames:
    """L'aperçu « pendant » en IMAGES d'une vidéo en cours de traitement : une frame (ou
    plusieurs variantes de la même frame) écrite en JPEG et publiée au plus toutes les `every`
    secondes. Le traitement demande `due()` AVANT de calculer une vue coûteuse.

        frames = PartialFrames('anonymizer', media.pk, folder)
        if frames.due():
            frames.publish({'detection': ('Détection', annotated), 'blur': ('Floutage', blurred)})
        frames.close()          # fin du traitement : partiels retirés, la face SORTIE prend le relais

    Écrit pour l'anonymizer (2026-10-04) — il tenait seul, dans sa tâche, le chemin, l'URL et
    la cadence d'une frame partielle."""

    def __init__(self, app_name, pk, folder, every: float = 2.0):
        self.app_name, self.pk, self.folder, self.every = app_name, pk, str(folder), every
        self._last = 0.0
        self._written = set()

    def due(self) -> bool:
        import time
        return time.time() - self._last >= self.every

    def publish(self, views: dict, index=None) -> None:
        """`views` : {variante: (libellé, image BGR)} ; `index` versionne l'URL (cache navigateur).
        Une image déjà ENCODÉE en JPEG (`bytes`) est écrite telle quelle — le rendu 3D de
        l'avatarizer (TalkingHead) produit ses images ainsi : les décoder pour les réencoder
        coûterait deux passes pour rien (2026-10-06)."""
        import time

        from django.conf import settings
        self._last = time.time()
        os.makedirs(self.folder, exist_ok=True)
        stamp = index if index is not None else int(self._last * 1000)
        for variant, (label, image) in views.items():
            path = os.path.join(self.folder, f'during_{self.pk}_{variant}.jpg')
            try:
                if isinstance(image, (bytes, bytearray)):
                    with open(path, 'wb') as out:
                        out.write(image)
                else:
                    import cv2
                    cv2.imwrite(path, image)
            except Exception:
                continue
            self._written.add(path)
            url = settings.MEDIA_URL + os.path.relpath(path, settings.MEDIA_ROOT).replace('\\', '/')
            publish_partial(self.app_name, self.pk, f'{url}?v={stamp}', variant=variant, label=label)

    def sink(self, variant: str, label: str):
        """Récepteur d'UNE vue pour un producteur qui ne connaît pas Django (un backend) :
        `sink.due()` avant de calculer l'image, `sink(image)` pour la publier (2026-10-06,
        aperçu des latents de l'imager — `ImageGenerationBackend.preview_step`)."""
        frames = self

        class _Sink:
            def due(self):
                return frames.due()

            def __call__(self, image):
                frames.publish({variant: (label, image)})

        return _Sink()

    def close(self) -> None:
        clear_partial(self.app_name, self.pk)
        for path in self._written:
            try:
                os.remove(path)
            except OSError:
                pass
        self._written.clear()


def publish_partial_peaks(app_name, pk, peaks, duration=None):
    """Worker : publie des PICS d'onde partiels (« waveform par parties », cf. `waveform.compute_peaks`)
    pour le streaming « pendant » — le front dessine l'onde qui se CONSTRUIT sans re-décoder le
    fichier (effet « Suno »). Complémentaire de `publish_partial` (URL jouable). `peaks` = liste [0..1]."""
    from django.core.cache import cache
    cache.set(_partial_peaks_key(app_name, pk),
              {'peaks': list(peaks or []), 'duration': duration}, 900)


def emit_streaming_peaks(app_name, pk, pcm, sr, buckets=800):
    """Worker de streaming (COMMUN, toute app) : calcule les pics uint8 d'une fenêtre PCM courante
    (via la source unique `waveform.compute_peaks`) et les publie pour `?side=during` → l'onde se
    CONSTRUIT au fil de la génération (effet « Suno »). `pcm` = tableau/liste PCM (mono/stéréo),
    `sr` = fréquence d'échantillonnage. Ne lève jamais (best-effort — un tick raté n'arrête rien)."""
    try:
        from .waveform import compute_peaks
        peaks, duration = compute_peaks(pcm, buckets=buckets, sr=sr, dtype='uint8', with_duration=True)
        if peaks:
            publish_partial_peaks(app_name, pk, peaks, duration=duration)
    except Exception:
        pass


def _partial_text_key(app_name, pk):
    return f'wama_partial_text_{app_name}_{pk}'


def publish_partial_text(app_name, pk, text):
    """Worker : publie le TEXTE partiel courant (transcription/description qui se construit),
    servi par `?side=during` (mime text/plain + content inline — le front le rend déjà).
    Étend la brique aux apps à sortie TEXTE (2026-08-13) : transcriber/describer publiaient
    chacun dans une clé de cache MAISON que seul leur endpoint de progression lisait."""
    from django.core.cache import cache
    cache.set(_partial_text_key(app_name, pk), str(text or ''), 900)


def get_partial_text(app_name, pk):
    """Lecture du texte partiel (endpoints de progression des apps + `?side=during`)."""
    from django.core.cache import cache
    return cache.get(_partial_text_key(app_name, pk), '')


def clear_partial(app_name, pk):
    """Worker : retire l'aperçu partiel (fin de traitement — la face SORTIE prend le relais)."""
    from django.core.cache import cache
    cache.delete(_partial_key(app_name, pk))
    cache.delete(_partial_peaks_key(app_name, pk))
    cache.delete(_partial_text_key(app_name, pk))
    cache.delete(_partial_variants_key(app_name, pk))


def _during_preview_data(app_name, instance, request):
    """Payload preview PENDANT le traitement : aperçu partiel publié par le worker, si l'app
    déclare la capacité. Peut porter une URL jouable (`publish_partial`) ET/OU des pics d'onde
    (`publish_partial_peaks`). None si l'app ne déclare pas la capacité ou n'a rien publié (dormant)."""
    from wama.common.app_registry import app_supports_during_preview
    if not app_supports_during_preview(app_name):
        return None
    from django.core.cache import cache
    pk = getattr(instance, 'pk', None)
    url = cache.get(_partial_key(app_name, pk))
    peaks_entry = cache.get(_partial_peaks_key(app_name, pk))
    partial_text = cache.get(_partial_text_key(app_name, pk))
    variants = cache.get(_partial_variants_key(app_name, pk)) or {}
    if variants:
        # La vue DEMANDÉE (`?variant=`), sinon la dernière publiée.
        wanted = request.GET.get('variant') if request is not None else None
        chosen = wanted if wanted in variants else list(variants)[-1]
        url = variants[chosen]['url']
    if not url and not peaks_entry and not partial_text:
        return None
    if partial_text and not url and not peaks_entry:
        # Sortie TEXTE qui se construit (transcriber/describer) : contenu inline,
        # rendu par la branche text/* de renderInlinePreview (data.content).
        return {'partial': True, 'name': 'texte partiel', 'mime_type': 'text/plain',
                'content': partial_text[-3000:]}
    data = {'partial': True}
    if url:
        from .mime_utils import guess_mime_type
        clean = str(url).split('?')[0]
        data['name'] = os.path.basename(clean) or 'partiel'
        data['url'] = request.build_absolute_uri(url) if str(url).startswith('/') else str(url)
        data['mime_type'] = guess_mime_type(clean) or 'application/octet-stream'
        if variants:
            data['variant'] = chosen
            data['variants'] = [{'key': key, 'label': entry['label']}
                                for key, entry in variants.items()]
    else:
        # pics seuls (pas encore de fichier jouable) : onde qui se construit, mime audio générique
        data['name'] = 'partiel'
        data['mime_type'] = 'audio/*'
    if peaks_entry:
        data['peaks'] = peaks_entry.get('peaks') or []
        if peaks_entry.get('duration') is not None:
            data['duration'] = peaks_entry['duration']
    return data


#: Les côtés que `unified_preview` sert par leur NOM : une face de process ne les prend jamais. Le
#: process commun des réglages de sortie s'appelle `output` (`output_process.OUTPUT_KEY`) — sa face
#: EST la Sortie.
RESERVED_SIDES = ('input', 'output', 'during', 'compare')

#: Ce qu'on AFFICHE d'une face de process : l'icône du TYPE de ce qu'elle rend (premier port de
#: sortie de son `FunctionSpec` — nature média ou type de donnée). Les types produits aujourd'hui ;
#: un autre prend l'icône générique.
FACE_ICONS = {'detections': 'fa-vector-square', 'score': 'fa-music', 'audio': 'fa-volume-high',
              'video': 'fa-film', 'image': 'fa-image', 'document': 'fa-file-lines'}
FACE_ICON_DEFAULT = 'fa-layer-group'

#: Types de donnée qui se montrent PAR-DESSUS le média qu'ils décrivent (l'entrée de la card),
#: dessinés dans le navigateur par `WamaPreviewOverlay` — jamais réencodés en un média de plus.
OVERLAY_TYPES = ('detections',)


def _face_identity(data):
    """Ce qu'une face MONTRE : son fichier (sans `?v=`), sa surcouche, son texte. Deux faces de
    même identité sont une seule étape — la seconde ne s'affiche pas."""
    if not data:
        return None
    overlay = data.get('overlay') or {}
    return (_media_rel(data.get('url')) or str(data.get('url') or '').split('?')[0],
            _media_rel(overlay.get('url')) if overlay else None,
            str(data.get('content') or '').strip())


def _overlay_face(app_name, instance, request, base, url, data_type, label):
    """Une donnée qui se DESSINE sur l'entrée (des détections) : l'entrée de la card, la donnée
    par-dessus (`overlay`), avec ce que la card règle de ce dessin
    (`PreviewRegistry.overlay_options`). Sans entrée lisible (fichier libéré) : pas de face."""
    if not base or not base.get('url'):
        return None
    data = dict(base)
    data['name'] = f"{label} — {base.get('name', '')}"
    data['overlay'] = {'kind': data_type, 'url': request.build_absolute_uri(_versioned(url)),
                       **PreviewRegistry.overlay_options(app_name, instance)}
    return data


def _process_face(app_name, pipeline, spec, instance, request, input_data):
    """Ce que montre la face d'UN process : son résultat lisible déclaré (`ProcessSpec.result`,
    un texte), sinon le premier de ses fichiers déclarés (`outputs`) que le disque porte — rendu
    selon le TYPE de sa sortie (`AppPipeline.output_type`) : une surcouche sur l'entrée pour des
    détections, le fichier lui-même sinon (le rendu par MIME de la visionneuse). None : rien.

    Le contenu PRÉSENT décide, pas l'état de la ligne d'exécution : une card montre ce qu'elle
    porte. (L'état d'un process — périmé, en échec — sur sa face : à venir, `ROUTE §F3b`.)"""
    label = spec.label or spec.key
    text = pipeline.readable_result(spec, instance)
    if text and spec.result_format == 'markdown':
        # Mis en forme par LE rendu markdown de WAMA (celui du lecteur de docs : HTML brut
        # neutralisé, liens externes en nouvel onglet) ; `content` garde le texte, pour Copier.
        from wama.common.docs_catalog import render_markdown
        return {'name': label, 'mime_type': 'text/markdown', 'content': text,
                'html': render_markdown(text)['html']}
    if text:
        return {'name': label, 'mime_type': 'text/plain', 'content': text}
    data_type = pipeline.output_type(spec)
    for field in spec.outputs:
        value = getattr(instance, field, None)
        if not getattr(value, 'name', None):
            continue
        url = value.url
        if not _local_media_path(url):        # un fichier annoncé que le disque ne porte plus
            continue
        if data_type in OVERLAY_TYPES:
            return _overlay_face(app_name, instance, request, input_data, url, data_type, label)
        return _media_face(url, request)
    return None


def _process_faces(app_name, instance, request, input_data, output_data) -> dict:
    """Les faces ENTRE Entrée et Sortie : les PROCESS du pipeline de la card, dans l'ordre du
    graphe — `{clé du process: (méta {key, label, icon}, données)}` (`ROUTE §F3b`, 2026-10-12,
    demande de Fabien : « le pipeline étant l'unité commune à tout WAMA, la preview pourrait
    s'adapter au pipeline »).

    Elles se DÉRIVENT de ce que le pipeline déclare déjà (`ProcessSpec` : libellé, `outputs`,
    `result` ; le type du port de sortie au catalogue) : l'anonymizer déclarait sa face
    « Détection » à la main (`register(faces=)`), seconde déclaration de son process `detect`
    — retirée (`REMOVAL_LEDGER R119`). Une app à un seul process (pas de pipeline) garde
    Entrée | Sortie. Une face qui montre ce que montre déjà l'Entrée, la Sortie ou une face
    précédente n'est pas une étape de plus (le rendu que la sortie a gardé tel quel, la
    transcription qui EST la Sortie du transcriber). Une face qui casse n'emporte pas les autres."""
    from wama.common.services.process_pipeline import pipeline_of
    pipeline = pipeline_of(instance)
    if pipeline is None:
        return {}
    shown = [_face_identity(input_data), _face_identity(output_data)]
    faces = {}
    for spec in pipeline.ordered():
        if spec.key in RESERVED_SIDES:
            continue
        try:
            data = _process_face(app_name, pipeline, spec, instance, request, input_data)
        except Exception as exc:
            logger.warning(f"Preview {app_name}/{getattr(instance, 'pk', '?')} : face du process "
                           f"« {spec.key} » indisponible : {exc}")
            data = None
        identity = _face_identity(data)
        if identity is None or identity in shown:
            continue
        shown.append(identity)
        faces[spec.key] = ({'key': spec.key, 'label': spec.label or spec.key,
                            'icon': FACE_ICONS.get(pipeline.output_type(spec), FACE_ICON_DEFAULT)},
                           data)
    return faces


def unified_preview(request, app_name: str, pk: int):
    """
    Unified preview endpoint for any registered app.

    Args:
        request: HTTP request
        app_name: The app identifier (e.g., 'anonymizer', 'describer')
        pk: Primary key of the instance

    Returns:
        JsonResponse with preview data or error
    """
    # Check if app is registered
    if not PreviewRegistry.is_registered(app_name):
        logger.warning(f"Preview requested for unregistered app: {app_name}")
        return HttpResponseNotFound(f"App '{app_name}' not registered for preview")

    # Get the model class
    model_class = PreviewRegistry.get_model(app_name)
    if not model_class:
        return HttpResponseNotFound(f"Model not found for app '{app_name}'")

    # Get the instance
    try:
        instance = get_object_or_404(model_class, pk=pk)
    except Exception as e:
        logger.error(f"Error fetching {app_name} instance {pk}: {e}")
        return HttpResponseNotFound(f"Instance not found")

    # Check permissions
    viewer = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    if not PreviewRegistry.check_permission(app_name, instance, viewer):
        return HttpResponseForbidden("You do not have access to this file.")

    # Get preview data using the registered adapter
    try:
        # Une face qui CASSE n'emporte pas les autres — comme les faces déclarées ci-dessous.
        # Mesuré le 2026-10-12 : l'anonymizer dont l'entrée a été LIBÉRÉE levait ici, et le 500
        # privait l'élément de sa SORTIE, qui existait.
        try:
            preview_data = _input_preview(app_name, instance, request)
        except Exception as exc:
            logger.warning(f"Preview {app_name}/{pk} : face Entrée indisponible : {exc}")
            preview_data = None
        # Preview ENTRÉE/SORTIE (décision 2026-07-12, STUDIO_VISION) : ?side=output sert le
        # RÉSULTAT (clé canonique result_file du detail) ; méta `sides` additive pour que
        # l'inspecteur affiche le toggle [Entrée|Sortie] (+ slider comparatif si comparable).
        output_data = _output_preview_data(app_name, instance, request)
        during_data = _during_preview_data(app_name, instance, request)   # chantier 2 (PENDANT)
        has_input = bool(preview_data and not preview_data.get('error'))
        has_output = bool(output_data)
        # Faces ENTRE Entrée et Sortie : les PROCESS du pipeline de la card (2026-10-12) —
        # l'anonymizer « Détection », le transcriber « Locuteurs », « Résumé », « Cohérence ».
        faces = _process_faces(app_name, instance, request,
                               preview_data if has_input else None, output_data)
        # Comparer confronte la Sortie à la dernière face qui MONTRE L'ENTRÉE (l'entrée et ses
        # détections dessinées), sinon à l'entrée elle-même.
        base_key = next((key for key, (_meta, d) in reversed(list(faces.items()))
                         if d.get('overlay')), 'input')
        base_data = faces[base_key][1] if base_key in faces else (preview_data if has_input else None)
        cat_base = _mime_category(base_data.get('mime_type')) if base_data else ''
        cat_out = _mime_category(output_data.get('mime_type')) if has_output else ''
        from wama.common.app_registry import app_supports_during_preview
        sides = {
            'has_input': has_input,
            'has_output': has_output,
            # Comparer : deux images (curseur), ou deux VIDÉOS synchronisées (2026-10-05).
            'comparable': bool(base_data and has_output and cat_base == cat_out
                               and cat_base in ('image', 'video')),
            'compare_base': base_key,
            'faces': [meta for meta, _d in faces.values()],
            # PENDANT : l'app sait-elle montrer sa sortie EN CONSTRUCTION (capacité) vs a-t-elle
            # un partiel MAINTENANT
            'during_capable': app_supports_during_preview(app_name),
            'has_during': bool(during_data),
        }
        side = (request.GET.get('side') or 'input').lower()
        if side in faces:
            data = dict(faces[side][1])
            data['side'] = side
        elif side == 'during' and during_data:
            data = dict(during_data)
            data['side'] = 'during'
        elif side == 'output' and has_output:
            data = dict(output_data)
            data['side'] = 'output'
        elif has_input:
            data = dict(preview_data)
            data['side'] = 'input'
        elif has_output:
            # Repli : app à entrée NON-fichier (synthesizer = texte) — l'adapter d'entrée
            # rend None et `dict(None)` faisait un 500 sur ?side=input (constat 03/08).
            data = dict(output_data)
            data['side'] = 'output'
        else:
            data = {'error': "Aucun aperçu disponible pour cet élément", 'side': side}
        _add_server_peaks(data)
        with_playback_copy(data, request)
        data['sides'] = sides
        return JsonResponse(data)
    except Exception as e:
        logger.error(f"Error generating preview for {app_name}/{pk}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def with_playback_copy(data, request):
    """Une vidéo que le navigateur ne lit pas est servie par sa COPIE DE LECTURE quand elle
    existe et est à jour (`video_compat`, 2026-10-06) — pour toute face, comparaison comprise.
    L'original n'est ni lu ni touché ici ; le téléchargement le sert toujours. Sans copie : rien
    ne change. Ne lève jamais : un aperçu ne casse pas pour une copie."""
    try:
        if not str(data.get('mime_type') or '').startswith('video/'):
            return data
        rel = _media_rel(data.get('url'))
        if not rel:
            return data
        from urllib.parse import quote
        from django.conf import settings
        from wama.common.utils.video_compat import playback_copy_for
        copy = playback_copy_for(rel)
        if copy:
            # Daté comme toute URL de média de l'aperçu (`_versioned`) : une copie REFAITE après
            # le remplacement de l'original garde son nom, le navigateur ne doit pas resservir
            # l'ancienne de son cache.
            media_url = settings.MEDIA_URL or '/media/'
            data['url'] = request.build_absolute_uri(_versioned(media_url + quote(copy)))
            data['mime_type'] = 'video/mp4'
            data['playback_copy'] = True
    except Exception as exc:
        logger.debug(f"copie de lecture ignorée : {exc}")
    return data


def register_app_preview(app_name: str, model_class, file_field: str = 'input_file',
                         user_field: str = 'user', duration_field: str = None,
                         width_field: str = None, height_field: str = None,
                         properties_field: str = None):
    """
    Convenience function to register an app with common field patterns.

    This creates a simple adapter based on field names and registers it.

    Args:
        app_name: Unique identifier for the app
        model_class: The Django model class
        file_field: Name of the FileField (default: 'input_file')
        user_field: Name of the user field (default: 'user')
        duration_field: Optional name of duration field
        width_field: Optional name of width field
        height_field: Optional name of height field
        properties_field: Optional name of properties field
    """
    from .preview_registry import create_simple_adapter

    adapter = create_simple_adapter(
        file_field=file_field,
        duration_field=duration_field,
        width_field=width_field,
        height_field=height_field,
        properties_field=properties_field
    )

    PreviewRegistry.register(
        app_name=app_name,
        model_class=model_class,
        adapter=adapter,
        file_field=file_field,
        user_field=user_field
    )


# ============================================================================
# App-specific adapters (for apps that need custom logic)
# ============================================================================

def anonymizer_preview_adapter(media, request):
    """Custom adapter for Anonymizer Media model. None once the input file is RELEASED (the
    card keeps its output) — `media.file.url` raised there, and took the whole preview down."""
    from django.utils.encoding import iri_to_uri

    if not media.file:
        return None
    media_url = request.build_absolute_uri(iri_to_uri(media.file.url))
    mime_type, _ = mimetypes.guess_type(media.file.path)

    return {
        "name": os.path.basename(media.file.name),
        "url": media_url,
        "mime_type": mime_type or "video/mp4",
        "duration": media.duration_inMinSec,
        "resolution": f"{media.width}x{media.height}" if media.width and media.height else "",
        "properties": media.properties if hasattr(media, 'properties') else "",
    }


def transcriber_preview_adapter(transcript, request):
    """Custom adapter for Transcriber Transcript model."""
    from django.utils.encoding import iri_to_uri

    if not transcript.audio:
        return {'error': 'No audio file available'}

    audio_url = request.build_absolute_uri(iri_to_uri(transcript.audio.url))
    mime_type, _ = mimetypes.guess_type(transcript.audio.path)

    data = {
        "name": os.path.basename(transcript.audio.name),
        "url": audio_url,
        "mime_type": mime_type or "audio/wav",
    }

    if hasattr(transcript, 'duration_display') and transcript.duration_display:
        data["duration"] = transcript.duration_display

    return data
