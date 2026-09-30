"""
Source COMMUNE des formats + qualités de FICHIER de sortie — pendant de voice_options pour la sortie.

`get_output_formats(domain)` : choix de format de fichier par domaine (audio/image/video/document),
réutilise `CONVERTER_OUTPUT_FORMATS` (converter.format_router) = source unique déjà maintenue.
`get_output_qualities(domain)` : presets de qualité (web/équilibré/max).
`output_format_params(domain, …)` : fabrique les `Param` output_format + output_quality prêts à injecter
dans le schéma d'une app **render-based** (export_binding=early : réglés AVANT génération, per-item).

Pour les apps **master-based** (export_binding=late), le format est choisi AU TÉLÉCHARGEMENT (split-button
multi_format_download) — pas un param de schéma. Le choix early/late est déclaré dans APP_CATALOG.
"""
from __future__ import annotations
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

#: Noms des paramètres que fabrique cette brique — lus par qui doit les appliquer (dépôt imager)
#: au lieu d'être recopiés en littéraux.
OUTPUT_PARAM_NAMES = ("output_format", "output_quality", "output_upscale")

# Presets de qualité génériques (indépendants du domaine).
OUTPUT_QUALITY_CHOICES: List[Tuple[str, str]] = [
    ("web", "Web (léger)"),
    ("balanced", "Équilibré"),
    ("max", "Maximum"),
]

#: Agrandissement de la SORTIE (2026-09-30) — un POST-TRAITEMENT de l'app, appliqué après
#: N'IMPORTE QUEL backend (`apply_output_settings`). Il vivait dans les backends : seul
#: `DiffusersBackend` l'appliquait (un simple LANCZOS ×2), les backends dédiés l'ignoraient en
#: silence (constat Fabien sur Supra2-IMG). Valeurs = celles de l'option `upscale` du converter
#: (`CROSS_APP_OPTIONS`) : un seul vocabulaire. L'upscaler est TIRÉ du catalogue (tâche
#: `upscale`, capacité `scale` = le facteur), jamais nommé ici.
OUTPUT_UPSCALE_CHOICES: List[Tuple[str, str]] = [
    ("", "Aucun"),
    ("x2", "×2"),
    ("x4", "×4"),
]
#: Domaine du tirage de l'upscaler : les modèles d'AGRANDISSEMENT, toutes sources confondues.
UPSCALER_SPEC = {"model_type": "upscaling", "capabilities__task": "upscale"}


def get_output_formats(domain: str) -> List[Tuple[str, str]]:
    """[(valeur, libellé)] des formats de fichier de sortie pour un domaine. 'original' = inchangé.

    ⚠ Un format de SORTIE garde la nature du résultat (2026-09-23, relevé par Fabien : « les
    réglages de sortie vidéo proposent du mp3 »). La table du converter liste pour la vidéo
    aussi les formats d'EXTRACTION audio (mp3, wav, ogg) — légitimes dans le converter, dont
    c'est le métier, mais absurdes pour une app qui PRODUIT une vidéo (imager, enhancer,
    anonymizer) : la vidéo générée finirait en piste audio, muette de surcroît. On retire donc
    d'un domaine les formats qui appartiennent en propre au domaine audio. Le converter lit sa
    propre table (`format_router.get_output_formats`), il n'est pas concerné."""
    try:
        from wama.common.app_registry import CONVERTER_OUTPUT_FORMATS
        fmts = list(CONVERTER_OUTPUT_FORMATS.get(domain) or [])
        if domain != 'audio':
            audio_only = set(CONVERTER_OUTPUT_FORMATS.get('audio') or [])
            fmts = [f for f in fmts if f not in audio_only]
    except Exception:
        fmts = []
    return [("original", "Original (inchangé)")] + [(f, "." + f.upper()) for f in fmts]


def get_output_qualities(domain: str | None = None) -> List[Tuple[str, str]]:
    """Presets de qualité (web/équilibré/max). `domain` réservé pour d'éventuelles variantes futures."""
    return list(OUTPUT_QUALITY_CHOICES)


def output_format_params(domain: str, contexts=None, dom_id_format=None, dom_id_quality=None,
                         include_quality: bool = True, group: str | None = None,
                         include_upscale: bool = False, dom_id_upscale=None) -> list:
    """
    Fabrique les Param COMMUNS output_format (+ output_quality) pour un domaine, prêts à concaténer au
    schéma d'une app early-binding. dom_id_* = ponts vers les IDs existants par surface (str ou dict).
    `group` (17/08, 4ᵉ consommateur — imager) : section ParamGroup d'accueil pour les rendus groupés —
    sans lui, les params SANS groupe sortent HORS sections, en TÊTE du volet (constat Fabien : le
    format de sortie doit arriver EN DERNIER, ordre chronologique du process).
    `include_upscale` (2026-09-30) : le réglage `output_upscale`, domaine IMAGE seulement. OPT-IN :
    il ne vaut que chez une app dont la tâche passe par `apply_output_settings` — un réglage
    offert sans application serait une promesse sans effet (le défaut même qu'il corrige).
    """
    from wama.common.utils.param_schema import Param, ALL_CONTEXTS
    ctx = contexts or ALL_CONTEXTS
    params = []
    if include_upscale and domain == "image":
        # Avant le format : l'agrandissement précède la conversion (ordre du process).
        params.append(
            Param(name="output_upscale", type="select", label="Agrandir la sortie", icon="fa-expand",
                  choices=list(OUTPUT_UPSCALE_CHOICES), default="", contexts=ctx,
                  dom_id=dom_id_upscale or "output_upscale", group=group,
                  help="Agrandissement par un modèle d'upscaling IA, appliqué après la génération.")
        )
    params.append(
        Param(name="output_format", type="select", label="Format de sortie", icon="fa-file-export",
              choices=get_output_formats(domain), contexts=ctx,
              dom_id=dom_id_format or "output_format", group=group),
    )
    if include_quality:
        # La qualité ne s'applique QUE lors d'une conversion (`apply_inline_conversion` ne
        # réencode pas un fichier déjà au format demandé) : affichée sous « Original », elle
        # promettait un réglage sans effet. Elle n'apparaît donc qu'avec un format choisi.
        converted = [v for v, _ in get_output_formats(domain) if v != "original"]
        params.append(
            Param(name="output_quality", type="select", label="Qualité", icon="fa-sliders",
                  choices=get_output_qualities(domain), contexts=ctx,
                  dom_id=dom_id_quality or "output_quality", group=group,
                  show_if={"field": "output_format", "in": converted},
                  help="Appliquée à la conversion vers le format choisi.")
        )
    return params


def _domain_from_output_types(output_types) -> str | None:
    """Déduit le domaine depuis les output_types d'APP_CATALOG (soit un nom de domaine direct
    ex. 'video', soit un format ex. 'mp3')."""
    types = set(str(t).lower() for t in (output_types or []))
    for domain in ("audio", "video", "image", "document"):   # 1) output_type == domaine ?
        if domain in types:
            return domain
    for domain in ("audio", "video", "image", "document"):   # 2) sinon, via le format
        if types & set(v for v, _ in get_output_formats(domain)):
            return domain
    return None


def output_format_params_for_app(app_name: str, contexts=None, dom_id_format=None,
                                 dom_id_quality=None, include_quality: bool = True,
                                 group: str | None = None, domain: str | None = None,
                                 include_upscale: bool = False, dom_id_upscale=None) -> list:
    """
    AUTO depuis APP_CATALOG : lit `multi_format_download` (early/late) + déduit le domaine des
    `output_types`. Renvoie les Param output_format/output_quality si l'app est **early-binding**
    (réglages avant génération), sinon [] (master-based → choix au téléchargement). L'app n'a plus qu'à
    fournir les dom_id de ses surfaces.

    `domain` (2026-09-23) : pour une app à PLUSIEURS domaines de sortie (imager : image ET vidéo),
    la déduction ne sait rendre qu'UN domaine — l'imager recevait les formats VIDÉO jusque dans sa
    modale d'IMAGE. Chaque schéma de domaine nomme alors le sien ; la règle early/late reste lue ici.
    """
    try:
        from wama.common.app_registry import APP_CATALOG
        cat = APP_CATALOG.get(app_name, {}) or {}
    except Exception:
        cat = {}
    conv = cat.get("conventions", {}) or {}
    # late-binding (format choisi au téléchargement) → pas un param de schéma. export_binding fait foi ;
    # multi_format_download reste un repli.
    if conv.get("export_binding") == "late" or conv.get("multi_format_download"):
        return []
    domain = domain or _domain_from_output_types(cat.get("output_types", []))
    if not domain:
        return []
    return output_format_params(domain, contexts, dom_id_format, dom_id_quality, include_quality,
                                group=group, include_upscale=include_upscale,
                                dom_id_upscale=dom_id_upscale)


def upscale_factor(value) -> int:
    """`'x4'` → 4, `'x2'` → 2 ; 0 pour « aucun » ou une valeur illisible."""
    try:
        return int(str(value or '').strip().lower().lstrip('x') or 0)
    except ValueError:
        return 0


def upscale_output_image(path: str, factor, *, item=None, app_id=None, denoise: bool = False,
                         progress_callback=None) -> tuple:
    """Agrandit l'image `path` EN PLACE par un upscaler TIRÉ du catalogue ; rend `(largeur,
    hauteur)`. Lève si aucun upscaler ne rend ce facteur : l'agrandissement a été DEMANDÉ, un
    résultat non agrandi rendu en silence serait un mensonge (règle du converter, 18/08).

    Aucun modèle ni aucune app nommés : le domaine (`UPSCALER_SPEC`) et le BESOIN (capacité
    `scale` = facteur) filtrent, le curseur qualité de l'item classe (`resolve_model_choice`),
    la classe se dérive du moteur déclaré (`backend_for_key`). ⚠ Le contrat d'appel est celui
    des upscalers ONNX du substrat (`AIUpscaler(model_name=…)`), le seul que le catalogue
    serve aujourd'hui pour cette tâche."""
    import os
    import tempfile

    from wama.common.backends.ai_upscaler import upscale_image_file
    from wama.common.backends.manager import backend_for_key
    from wama.common.utils.auto_model import AUTO, candidates_with, resolve_model_choice
    from wama.common.utils.model_keys import model_id

    n = upscale_factor(factor)
    candidates = candidates_with('scale', n, **UPSCALER_SPEC) if n > 1 else []
    if not candidates:
        raise RuntimeError(f"Agrandissement ×{n} demandé : aucun modèle d'upscaling de ce facteur "
                           f"au catalogue")
    spec = {"model_type": UPSCALER_SPEC["model_type"], "task": "upscale"}
    key = resolve_model_choice(AUTO, spec=spec, fallback=candidates[0], item=item,
                               app_id=app_id, candidates=candidates) or candidates[0]
    backend_class = backend_for_key(key)
    if backend_class is None:
        raise RuntimeError(f"Upscaler « {key} » : aucun backend résolu depuis le catalogue")
    suffix = os.path.splitext(path)[1] or '.png'
    fd, tmp = tempfile.mkstemp(prefix='wama_upscale_', suffix=suffix)
    os.close(fd)
    try:
        size = upscale_image_file(path, tmp, model_name=model_id(key), denoise=denoise,
                                  progress_callback=progress_callback,
                                  factory=lambda name: backend_class(model_name=name))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    logger.info("[output] %s agrandi ×%s par %s → %sx%s", path, n, key, *size)
    return size


def apply_output_settings(paths, item, *, domain: str, app_id: str | None = None,
                          console=None) -> list:
    """Les réglages de SORTIE de l'item appliqués aux fichiers produits, dans l'ordre du
    process : agrandissement (image) PUIS conversion de format. Rend les chemins finaux.

    Une seule application pour toutes les apps render-based (2026-09-30) : chacune recopiait
    sa boucle de conversion, et l'agrandissement vivait dans UN backend. Lit les champs de
    l'item nommés comme les params de cette brique (`OUTPUT_PARAM_NAMES`).
    Un échec d'AGRANDISSEMENT lève (il a été demandé) ; un échec de CONVERSION garde le
    fichier natif et le DIT — le comportement historique des apps, conservé."""
    say = console or (lambda _msg: None)
    paths = list(paths or [])
    factor = upscale_factor(getattr(item, 'output_upscale', ''))
    if factor > 1 and domain == 'image':
        say(f"Agrandissement ×{factor} de {len(paths)} image(s)…")
        for p in paths:
            w, h = upscale_output_image(p, factor, item=item, app_id=app_id)
        say(f"Agrandissement terminé : {w}×{h}")
    fmt = (getattr(item, 'output_format', '') or 'original').lower()
    if fmt in ('', 'original'):
        return paths
    preset = getattr(item, 'output_quality', '') or 'balanced'
    try:
        # Le MÉCANISME de conversion vit dans le converter (convention d'appel inline).
        from wama.converter.utils.inline_convert import apply_inline_conversion
        return [apply_inline_conversion(p, fmt, preset) for p in paths]
    except Exception as exc:
        logger.warning("[output] conversion vers %s échouée : %s", fmt, exc)
        say(f"Conversion vers {fmt} échouée ({exc}) — fichier natif conservé")
        return paths
