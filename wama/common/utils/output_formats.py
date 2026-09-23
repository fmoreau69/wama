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
from typing import List, Tuple

# Presets de qualité génériques (indépendants du domaine).
OUTPUT_QUALITY_CHOICES: List[Tuple[str, str]] = [
    ("web", "Web (léger)"),
    ("balanced", "Équilibré"),
    ("max", "Maximum"),
]


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
                         include_quality: bool = True, group: str | None = None) -> list:
    """
    Fabrique les Param COMMUNS output_format (+ output_quality) pour un domaine, prêts à concaténer au
    schéma d'une app early-binding. dom_id_* = ponts vers les IDs existants par surface (str ou dict).
    `group` (17/08, 4ᵉ consommateur — imager) : section ParamGroup d'accueil pour les rendus groupés —
    sans lui, les params SANS groupe sortent HORS sections, en TÊTE du volet (constat Fabien : le
    format de sortie doit arriver EN DERNIER, ordre chronologique du process).
    """
    from wama.common.utils.param_schema import Param, ALL_CONTEXTS
    ctx = contexts or ALL_CONTEXTS
    params = [
        Param(name="output_format", type="select", label="Format de sortie", icon="fa-file-export",
              choices=get_output_formats(domain), contexts=ctx,
              dom_id=dom_id_format or "output_format", group=group),
    ]
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
                                 group: str | None = None, domain: str | None = None) -> list:
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
                                group=group)
