"""Anonymisation des vidéos pour l'AFFICHAGE — passes `anonymize_detect` puis `anonymize_blur`.

POURQUOI (Fabien, 2026-10-07 → 12) : montrer le cam_analyzer en démonstration publique sans
montrer de visage ni de plaque. Le floutage est une BRANCHE d'affichage : l'analyse continue de
lire les vidéos d'origine (un flou en amont dégraderait YOLO et périmerait toutes les passes GPU).
Seules les FENÊTRES d'intersection sont anonymisées, pour ne pas payer le GPU sur toute la vidéo ;
hors fenêtre l'image entière est floutée, pour que rien d'identifiable ne s'affiche.

RIEN DE NEUF, tout est repris :
  • le CHOIX des détecteurs est celui de l'Anonymizer (`needs_parallel_detection` : classes ×
    curseur rapide/qualité → ensemble de modèles), ses RÉGLAGES de flou sont les défauts déclarés
    à son schéma (`param_schema.applicable_defaults`) ;
  • la détection passe par l'ensemble commun (`common/services/detection_ensemble.DetectorSet`),
    le document par le type de donnée commun (`common/utils/detections`), le floutage par
    `blur_utils.blur_detections` et `detections.rewrite_media` — exactement les deux process
    « Détection » et « Floutage » de l'Anonymizer ;
  • les fenêtres se découpent comme pour la détection YOLO (`window_clips`).

La vidéo floutée garde EXACTEMENT les images de l'originale (cadence, taille, nombre) : les
boîtes et la vue de dessus tombent dessus à l'affichage.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from bisect import bisect_right

logger = logging.getLogger(__name__)

DETECT_PASS = 'anonymize_detect'
BLUR_PASS = 'anonymize_blur'
#: Libellé de la zone « image entière » posée hors des fenêtres anonymisées.
OUTSIDE_LABEL = 'outside_windows'


# ── Où vivent les fichiers produits ──────────────────────────────────────────────────────────
def output_dir(session) -> str:
    """Dossier (absolu) des sorties d'anonymisation de la session."""
    from django.conf import settings
    from wama.common.utils.media_paths import app_media_dir
    return os.path.join(settings.MEDIA_ROOT, app_media_dir('cam_analyzer', session.user_id, 'output'),
                        'anonymized', str(session.id))


def detections_path(session, position: str) -> str:
    return os.path.join(output_dir(session), f'{position}_detections.json')


def video_path(session, position: str) -> str:
    """La vidéo floutée d'une caméra — ce que l'option d'affichage sert à la place de l'originale."""
    return os.path.join(output_dir(session), f'{position}.mp4')


def anonymized_video(camera):
    """Chemin de la vidéo floutée de cette caméra si elle existe, sinon None."""
    path = video_path(camera.session, camera.position)
    return path if os.path.isfile(path) else None


# ── Ce que l'Anonymizer décide ──────────────────────────────────────────────────────────────
def detectors_for(profile) -> tuple:
    """(modèles, classes non couvertes) : l'ensemble que l'Anonymizer retient pour les classes et
    le cran du curseur du profil. ⚠ Import Lab → Médias, assumé : le choix d'un ensemble pour
    anonymiser EST la politique de l'Anonymizer (plancher de rappel, préférences) — la recopier
    ici la ferait diverger. Même cas que le chargeur SAM3 (`ROADMAP §18.2`, à instruire)."""
    from wama.anonymizer.parallel_detection import needs_parallel_detection
    classes = list(getattr(profile, 'anonymize_classes', None) or ['face', 'plate'])
    quality = int(getattr(profile, 'anonymize_quality', 50))
    info = needs_parallel_detection(classes, quality)
    return list(info.get('models') or []), list(info.get('unsupported_classes') or [])


def anonymizer_settings() -> dict:
    """Les défauts DÉCLARÉS au schéma de l'Anonymizer (seuil, flou, interpolation…). Deux tours :
    un réglage qui n'apparaît que sous condition (`show_if`, ex. le nombre d'images interpolées
    sous « interpoler ») est lu avec les valeurs du premier."""
    from wama.common.utils.param_schema import applicable_defaults, schema_for_app
    schema = schema_for_app('anonymizer')
    first = applicable_defaults(schema)
    return {**first, **applicable_defaults(schema, values=first)}


# ── Les détecteurs, chargés une fois pour toutes les caméras ─────────────────────────────────
def load_detectors(models, user):
    from wama.common.services.detection_ensemble import DetectorSet
    return DetectorSet(models, user=user)


def unload_detectors(detector_set) -> None:
    """Libère la VRAM de l'ensemble (moteur YOLO et détecteurs d'autres familles)."""
    if detector_set is None:
        return
    for holder in [detector_set.engine] + [d for _m, d in detector_set.others]:
        try:
            if holder is not None and hasattr(holder, 'unload'):
                holder.unload()
        except Exception:
            logger.debug('unload', exc_info=True)


# ── Détection : les fenêtres seules, document pour la vidéo entière ─────────────────────────
def detect_camera(camera, windows, detector_set, *, classes, threshold, cancelled=None,
                  progress=None) -> dict:
    """Document `detections` de la VIDÉO ENTIÈRE de `camera`, détecté sur les seules images de
    ses fenêtres d'intersection (`windows`, temps vidéo). Chaque plage est extraite
    (`window_clips.extract_clip`), passée à l'ensemble de détecteurs, et ses indices ramenés à
    la vidéo. Le document porte en plus `scope` : les plages réellement anonymisées — le
    floutage floute l'image ENTIÈRE ailleurs.

    Une plage qui ne s'extrait pas fait échouer la caméra : la laisser de côté afficherait ses
    images en clair, alors que le document les dirait traitées."""
    import cv2
    from wama.common.utils import detections as dets
    from .window_clips import extract_clip, ffmpeg_path, window_frame_ranges
    source = camera.video_file.path
    capture = cv2.VideoCapture(source)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or float(camera.fps or 12.0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    finally:
        capture.release()
    ranges = window_frame_ranges(windows, fps, total)
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise RuntimeError("ffmpeg introuvable : les fenêtres ne peuvent pas être extraites.")
    doc = dets.new_document(media='video', width=width, height=height, fps=fps,
                            frame_count=total, classes=classes)
    doc['scope'] = [[int(s), int(e)] for s, e in ranges]
    todo = sum(e - s + 1 for s, e in ranges) or 1
    done = 0
    workdir = tempfile.mkdtemp(prefix=f'wama_cam{camera.id}_anon_')
    try:
        for n, (start, end) in enumerate(ranges):
            if cancelled is not None and cancelled():
                raise InterruptedError("Anonymisation annulée.")
            clip = os.path.join(workdir, f'range_{n:03d}.mp4')
            if not extract_clip(source, start, end, fps, clip, ffmpeg=ffmpeg):
                raise RuntimeError(f"Extrait {start}-{end} impossible à produire.")
            span = end - start + 1

            def _progress(part_done, part_total, _base=done, _span=span):
                if progress is not None:
                    progress(_base + _span * part_done / max(part_total, 1), todo)

            part = detector_set.detect(media_path=clip, classes2blur=classes,
                                       detection_threshold=threshold, progress=_progress)
            for frame in part.get('frames') or []:
                index = start + int(frame['i'])
                if index > end:
                    continue
                # Les pistes repartent à chaque extrait : préfixées de la plage, deux plages ne
                # confondent pas leurs objets à l'interpolation.
                dets.add(doc, index, [dict(d, track=f"r{n}:{d['track']}") if d.get('track') else dict(d)
                                      for d in frame.get('d') or []])
            doc['engine'] = part.get('engine') or doc['engine']
            doc['models'] = part.get('models') or doc['models']
            done += span
            os.remove(clip)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    doc.pop('_index', None)
    return doc


# ── Floutage : la vidéo entière réécrite ─────────────────────────────────────────────────────
class _FramesWithOutside(dict):
    """Détections par image, plus l'image ENTIÈRE pour toute image hors des plages anonymisées
    (`rewrite_media` lit chaque image par `get`)."""

    def __init__(self, frames, scope, whole):
        super().__init__(frames)
        self._starts = [int(s) for s, _e in scope]
        self._ends = [int(e) for _s, e in scope]
        self._whole = [whole]

    def inside(self, index: int) -> bool:
        k = bisect_right(self._starts, index) - 1
        return k >= 0 and index <= self._ends[k]

    def get(self, index, default=None):
        if not self.inside(index):
            return self._whole
        return super().get(index, default)


def class_floors(profile) -> dict:
    """{classe: seuil} du floutage pour chaque classe floutée du profil : son seuil propre
    (`anonymize_class_min_confidence`), sinon le seuil commun (`anonymize_min_confidence`)."""
    default = float(getattr(profile, 'anonymize_min_confidence', 0.0) or 0.0)
    own = getattr(profile, 'anonymize_class_min_confidence', None) or {}
    return {c: float(own.get(c, default)) for c in (getattr(profile, 'anonymize_classes', None) or [])}


def clean_class_floors(value) -> dict:
    """{classe: seuil} reçu d'un formulaire → seuils bornés à [0, 1] (3 décimales). Lève
    `ValueError` si ce n'est pas un objet de nombres."""
    if not isinstance(value, dict):
        raise ValueError('seuils par classe : objet attendu')
    return {str(c).strip(): round(max(0.0, min(1.0, float(v))), 3)
            for c, v in value.items() if str(c).strip()}


def profile_fields(profile) -> dict:
    """Les réglages d'anonymisation d'un profil tels que le volet les lit — avec les écritures
    équivalentes de chaque classe, pour que l'aperçu range une détection sous sa classe."""
    classes = getattr(profile, 'anonymize_classes', None) or []
    return {'anonymize_classes': classes,
            'anonymize_quality': profile.anonymize_quality,
            'anonymize_min_confidence': profile.anonymize_min_confidence,
            'anonymize_class_min_confidence': profile.anonymize_class_min_confidence or {},
            'anonymize_class_forms': class_forms(classes)}


def class_forms(classes) -> dict:
    """{classe: [écritures équivalentes, normalisées]} — une détection se nomme comme son jeu de
    poids (`license_plate`), le profil comme l'Anonymizer (`plate`) : la table d'équivalence est
    celle de la couverture des modèles (`model_coverage.formes_equivalentes`), servie aussi à
    l'aperçu du volet pour qu'il ne la recopie pas."""
    from wama.common.services.model_coverage import formes_equivalentes
    return {c: sorted(formes_equivalentes(c)) for c in classes or []}


def confident(doc: dict, min_confidence: float, floors: dict | None = None) -> dict:
    """Le document sans les détections sous leur seuil (une détection sans confiance est gardée) :
    le seuil de sa classe dans `floors` ({classe: seuil}, `class_floors`), sinon `min_confidence`.
    Filtré AVANT l'interpolation : une fausse détection écartée n'est plus prolongée en bande
    floutée, et un objet réel dont la confiance faiblit une image est comblé par ses voisines.
    L'aperçu du volet trace la même règle (`index.js`, panneau « Anonymisé »)."""
    from wama.common.services.model_coverage import normaliser_classe
    default = float(min_confidence or 0.0)
    by_form = {f: float(v) for c, v in (floors or {}).items() for f in class_forms([c])[c]}
    frames = []
    for frame in doc.get('frames') or []:
        kept = [d for d in frame.get('d') or []
                if float(d.get('conf', 1.0)) >= by_form.get(normaliser_classe(d.get('label')), default)]
        if kept:
            frames.append(dict(frame, d=kept))
    return dict(doc, frames=frames)


#: Finitions du floutage d'AFFICHAGE — essai esthétique (Fabien, 2026-10-29), pris ICI seulement :
#: les défauts de l'Anonymizer ne bougent qu'une fois l'essai jugé (`blur_utils.blur_box_inside`).
#: Flou à 50 % du petit côté de l'objet (indépendant de la résolution : le noyau fixe de 75 px
#: rasait les petites plaques en aplat), zone ×1,44 en aire (+10 % par côté : la place du fondu,
#: la boîte restant floutée en entier), coins de 5 px pris sur la zone, fondu sur toute la marge.
#: Banc du 2026-10-29 sur 32 objets des quatre caméras (384×244 à 408×248) : même coût (2,7 ms
#: par image) ; la zone ×1,05 ne laissait aucune place au fondu (bords francs, coins dans la boîte).
BLUR_LOOK = {'intensity': 50, 'rounded_edges': 5, 'progressive_blur': 100, 'roi_enlargement': 1.44}


def blur_look() -> dict:
    """Les finitions du floutage, telles que la photo d'une passe les retient (`pass_tracking`)."""
    return {'style': 'inside', **BLUR_LOOK}


def blur_camera(camera, doc, settings_: dict, target: str, progress=None,
                min_confidence: float = 0.0, floors: dict | None = None) -> str:
    """Réécrit la vidéo de `camera` floutée selon `doc` — le process « Floutage » de
    l'Anonymizer (interpolation des trous, extrapolation aux bords, flou à la forme ou au
    rectangle) aux finitions `BLUR_LOOK` — et l'image entière hors des plages anonymisées. Rend
    le chemin écrit. Les détections sous le seuil de leur classe ne sont pas floutées
    (`confident`) ; `settings_` (l'Anonymizer) donne l'interpolation et le flou hors fenêtres."""
    from wama.common.utils import detections as dets
    from wama.common.utils.blur_utils import blur_detections, blur_detections_inside
    doc = confident(doc, min_confidence, floors)
    frames = dets.by_frame(
        doc, interpolate=bool(settings_.get('interpolate_detections', True)),
        max_gap=dets.max_gap_for(doc.get('fps'), settings_.get('max_interpolation_frames') or 0),
        max_extrapolation=int(settings_.get('max_extrapolation_frames') or 0))
    whole = dets.detection(box=[0, 0, doc['width'], doc['height']], label=OUTSIDE_LABEL)
    frames = _FramesWithOutside(frames, sorted(doc.get('scope') or []), whole)
    # L'image ENTIÈRE hors fenêtres garde le flou de l'Anonymizer : à 50 % de son petit côté,
    # elle deviendrait un aplat uniforme (et coûterait plus, sur la plupart des images).
    outside = {'blur_ratio': settings_.get('blur_ratio', 75),
               'rounded_edges': settings_.get('rounded_edges', 5),
               'progressive_blur': settings_.get('progressive_blur', 0),
               'roi_enlargement': settings_.get('roi_enlargement', 1.0)}

    def blur_frame(image, found):
        if found and found[0].get('label') == OUTSIDE_LABEL:
            return blur_detections(image, found, **outside)
        return blur_detections_inside(image, found, **BLUR_LOOK)

    os.makedirs(os.path.dirname(target), exist_ok=True)
    return dets.rewrite_media(camera.video_file.path, frames, blur_frame, target, progress=progress)
