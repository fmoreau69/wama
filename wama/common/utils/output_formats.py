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

#: Domaines où la sortie peut revenir à la RÉSOLUTION de l'entrée (`output_keep_size`).
KEEP_SIZE_DOMAINS = ("image", "video")

# Presets de qualité génériques (indépendants du domaine) — les clés ET les libellés sont ceux de
# la table de conversion qui les APPLIQUE (`converter/utils/quality_presets`). Ils étaient recopiés
# ici sous d'autres mots (« Web (léger) / Équilibré / Maximum ») : deux vocabulaires pour les trois
# mêmes positions, contre l'arbitrage de Fabien du 02/09 (« Rapide / Équilibré / Qualité »),
# confirmé le 2026-10-28 (D1).
from wama.converter.utils.quality_presets import (  # noqa: E402
    DEFAULT_PRESET, PRESET_CHOICES, PRESET_LABELS)

OUTPUT_QUALITY_CHOICES: List[Tuple[str, str]] = [(k, PRESET_LABELS[k]) for k in PRESET_CHOICES]

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


#: Le choix « garder le format que le moteur a écrit » — 1ʳᵉ option de toute liste de sortie.
ORIGINAL = "original"
ORIGINAL_CHOICE = (ORIGINAL, "Original (inchangé)")

#: Libellé d'un groupe d'options par nature, quand une app rend PLUSIEURS natures.
NATURE_LABELS = {"image": "Image", "video": "Vidéo", "audio": "Audio", "document": "Document"}


def format_option_groups(natures, extra=()) -> list:
    """Les options de format d'une app qui rend PLUSIEURS natures selon l'élément (l'enhancer et
    l'anonymizer : une image OU une vidéo), en groupes : « Original » et les choix `extra` propres
    à l'app, puis un groupe par nature. Les deux apps recopiaient chacune cette union (2026-10-28,
    étape 1 du rangement des réglages de sortie) ; un format qui n'est pas celui de la nature de
    l'élément est REFUSÉ en le disant au rendu (`apply_output_settings`)."""
    groups = [("Conserver", [ORIGINAL_CHOICE] + list(extra))]
    for nature in natures:
        groups.append((NATURE_LABELS.get(nature, nature),
                       [c for c in get_output_formats(nature) if c[0] != ORIGINAL]))
    return groups


def quality_applies(item, output_format: str | None = None) -> bool:
    """La qualité a-t-elle un effet sur la sortie de cet élément ? Oui quand le fichier est
    RÉENCODÉ : un format choisi autre qu'« Original », ou « Garder la résolution d'origine » coché
    (la sortie est alors réencodée à la taille de l'entrée, `apply_output_settings`). La règle que
    rendent les surfaces (condition du `Param`, `output_format_params`) et l'inspecteur (Fabien,
    2026-10-28 : « on peut vouloir garder la résolution d'origine et changer le format et la
    qualité »)."""
    return (wanted_format(item, output_format) not in ('', ORIGINAL)
            or bool(getattr(item, 'output_keep_size', False)))


def get_output_qualities(domain: str | None = None) -> List[Tuple[str, str]]:
    """Presets de qualité (web/équilibré/max). `domain` réservé pour d'éventuelles variantes futures."""
    return list(OUTPUT_QUALITY_CHOICES)


def keep_size_param(contexts=None, dom_id=None, group: str | None = None, **extra):
    """Le réglage « Garder la résolution d'origine » (2026-10-16, demande de Fabien) : la sortie
    revient aux dimensions de l'ENTRÉE, par le converter, au process « Sortie ». Pour une app qui
    AGRANDIT (l'enhancer) : on garde le gain de qualité sans le poids d'un fichier ×4.

    OPT-IN, comme `output_upscale` : il ne vaut que chez une app qui passe à `output_step` la
    taille de son entrée (`input_size`) — offert sans elle, ce serait une promesse sans effet.
    Il déclare lui-même le process qu'il périme (`stales`) plutôt que d'entrer dans
    `OUTPUT_PARAM_NAMES` : seul le pipeline d'une app qui l'offre le surveille.
    `extra` : les autres attributs du `Param` (dom_id par surface, `show_if`…)."""
    from wama.common.services.output_process import OUTPUT_KEY
    from wama.common.utils.param_schema import Param, ALL_CONTEXTS
    return Param(name="output_keep_size", type="toggle", label="Garder la résolution d'origine",
                 icon="fa-compress", default=False, contexts=contexts or ALL_CONTEXTS,
                 dom_id=dom_id or "output_keep_size", group=group, stales=(OUTPUT_KEY,),
                 help="Améliore la qualité sans agrandir : la sortie est ramenée aux dimensions "
                      "du fichier d'entrée.", **extra)


def output_format_params(domain, contexts=None, dom_id_format=None, dom_id_quality=None,
                         include_quality: bool = True, group: str | None = None,
                         include_upscale: bool = False, dom_id_upscale=None,
                         keep_size: bool = False, dom_id_keep_size=None, extra_formats=(),
                         **extra) -> list:
    """
    Fabrique les Param COMMUNS output_format (+ output_quality) pour un domaine, prêts à concaténer au
    schéma d'une app early-binding. dom_id_* = ponts vers les IDs existants par surface (str ou dict).
    `domain` : une nature, ou un TUPLE de natures pour une app dont l'élément est l'une ou l'autre
    (l'enhancer, l'anonymizer : image ou vidéo) — les formats viennent alors en groupes par nature
    (`format_option_groups`), avec les choix `extra_formats` propres à l'app après « Original ».
    `group` (17/08, 4ᵉ consommateur — imager) : section ParamGroup d'accueil pour les rendus groupés —
    sans lui, les params SANS groupe sortent HORS sections, en TÊTE du volet (constat Fabien : le
    format de sortie doit arriver EN DERNIER, ordre chronologique du process).
    `include_upscale` (2026-09-30) : le réglage `output_upscale`, domaine IMAGE seulement. OPT-IN :
    il ne vaut que chez une app dont la tâche passe par `apply_output_settings` — un réglage
    offert sans application serait une promesse sans effet (le défaut même qu'il corrige).
    `keep_size` (2026-10-28) : « Garder la résolution d'origine » (`keep_size_param`), avant le
    format ; la qualité vaut alors AUSSI quand il est coché, au format d'origine (`quality_applies`).
    `extra` : les autres attributs communs aux trois `Param` (ex. `chip=True` sur le format seul
    n'en fait pas partie — voir `format_extra`).
    """
    from wama.common.utils.param_schema import Param, ALL_CONTEXTS
    ctx = contexts or ALL_CONTEXTS
    natures = tuple(domain) if isinstance(domain, (tuple, list)) else (domain,)
    format_extra = dict(extra.pop("format_extra", None) or {})
    params = []
    if keep_size:
        params.append(keep_size_param(contexts=ctx, dom_id=dom_id_keep_size, group=group,
                                      **dict(extra.pop("keep_size_extra", None) or {})))
    if include_upscale and natures == ("image",):
        # Avant le format : l'agrandissement précède la conversion (ordre du process).
        params.append(
            Param(name="output_upscale", type="select", label="Agrandir la sortie", icon="fa-expand",
                  choices=list(OUTPUT_UPSCALE_CHOICES), default="", contexts=ctx,
                  dom_id=dom_id_upscale or "output_upscale", group=group,
                  help="Agrandissement par un modèle d'upscaling IA, appliqué après la génération.")
        )
    if len(natures) == 1 and not extra_formats:
        options = dict(choices=get_output_formats(natures[0]))
        converted = [v for v, _ in options["choices"] if v != ORIGINAL]
    else:
        options = dict(option_groups=format_option_groups(natures, extra_formats))
        converted = [v for _, group_choices in options["option_groups"]
                     for v, _ in group_choices if v != ORIGINAL]
    params.append(
        # Défaut « original » (2026-10-11) : celui des colonnes `output_format` des apps qui
        # emploient cette brique, et la 1ʳᵉ option de toute liste (`get_output_formats`). Sans
        # lui, « Réinitialiser » (`WamaParams.applyDefaults`) vidait le select d'un volet généré.
        Param(name="output_format", type="select", label="Format de sortie", icon="fa-file-export",
              default=ORIGINAL, contexts=ctx, dom_id=dom_id_format or "output_format",
              group=group, **options, **{**extra, **format_extra}),
    )
    if include_quality:
        # La qualité ne s'applique QUE quand le fichier est RÉENCODÉ (`quality_applies`) : un
        # format choisi, ou la résolution d'origine gardée. Affichée sous « Original », elle
        # promettait un réglage sans effet.
        condition = {"field": "output_format", "in": converted}
        if keep_size:
            condition = {"any": [condition, {"field": "output_keep_size"}]}
        params.append(
            # Défaut « balanced » (2026-10-11) : celui de TOUTES les colonnes `output_quality` et
            # du repli de la conversion (`apply_output_settings`). Sans défaut déclaré, une surface
            # générée (volet, modale) proposait la PREMIÈRE option, « web » — mesuré sur le volet
            # généré du synthesizer, quand l'ancien volet écrit à la main proposait « Équilibré ».
            Param(name="output_quality", type="select", label="Qualité", icon="fa-sliders",
                  choices=get_output_qualities(), default=DEFAULT_PRESET, contexts=ctx,
                  dom_id=dom_id_quality or "output_quality", group=group, show_if=condition,
                  help=("Appliquée quand la sortie est réencodée : format choisi, ou résolution "
                        "d'origine gardée." if keep_size
                        else "Appliquée à la conversion vers le format choisi."), **extra)
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
    from wama.common.utils.model_keys import backend_model_id

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
    # Le temporaire naît DANS le dossier de la sortie : `os.replace` ne traverse pas deux systèmes
    # de fichiers, et `/tmp` n'est pas celui de `media/` (mesuré le 2026-10-03, premier
    # agrandissement de sortie joué en réel : « Invalid cross-device link »).
    fd, tmp = tempfile.mkstemp(prefix='.wama_upscale_', suffix=suffix,
                               dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    try:
        # Le backend reçoit l'identifiant de SON vocabulaire, celui que la résolution a comparé.
        size = upscale_image_file(path, tmp, model_name=backend_model_id(key), denoise=denoise,
                                  progress_callback=progress_callback,
                                  factory=lambda name: backend_class(model_name=name))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    logger.info("[output] %s agrandi ×%s par %s → %sx%s", path, n, key, *size)
    return size


def wanted_format(item, output_format: str | None = None) -> str:
    """Le format de sortie DEMANDÉ, en minuscules ('original' = inchangé). `output_format` : la
    valeur qu'une app a RÉSOLUE elle-même quand son réglage n'est pas un format (l'anonymizer et
    son « format de l'entrée ») — sinon le réglage de l'item."""
    value = getattr(item, 'output_format', '') if output_format is None else output_format
    return (value or 'original').lower()


def keep_size_target(item, domain: str, input_size=None):
    """Les dimensions `(largeur, hauteur)` auxquelles ramener la sortie, ou None : le réglage
    `output_keep_size` est coché, le domaine s'y prête, et l'app a dit la taille de son entrée."""
    if domain not in KEEP_SIZE_DOMAINS or not getattr(item, 'output_keep_size', False):
        return None
    size = input_size(item) if callable(input_size) else input_size
    if not size or not all(int(v or 0) > 0 for v in size[:2]):
        return None
    return int(size[0]), int(size[1])


def apply_output_settings(paths, item, *, domain: str, app_id: str | None = None,
                          console=None, output_format: str | None = None,
                          input_size=None) -> list:
    """Les réglages de SORTIE de l'item appliqués aux fichiers produits, dans l'ordre du
    process : agrandissement (image), retour à la résolution de l'entrée, PUIS conversion de
    format. Rend les chemins finaux.

    Une seule application pour toutes les apps render-based (2026-09-30) : chacune recopiait
    sa boucle de conversion, et l'agrandissement vivait dans UN backend. Lit les champs de
    l'item nommés comme les params de cette brique (`OUTPUT_PARAM_NAMES`).
    `input_size` : `(largeur, hauteur)` de l'entrée, ou `callable(item)` — sans elle,
    `output_keep_size` n'a pas d'objet.
    Un échec d'AGRANDISSEMENT lève (il a été demandé), un échec du RETOUR À LA RÉSOLUTION
    aussi (un fichier à la mauvaise taille rendu en silence serait un mensonge) ; un échec de
    CONVERSION seule garde le fichier natif et le DIT — le comportement historique des apps."""
    import os
    say = console or (lambda _msg: None)
    paths = list(paths or [])
    factor = upscale_factor(getattr(item, 'output_upscale', ''))
    if factor > 1 and domain == 'image':
        say(f"Agrandissement ×{factor} de {len(paths)} image(s)…")
        for p in paths:
            w, h = upscale_output_image(p, factor, item=item, app_id=app_id)
        say(f"Agrandissement terminé : {w}×{h}")
    fmt = wanted_format(item, output_format)
    if fmt not in ('', ORIGINAL) and fmt not in {v for v, _ in get_output_formats(domain)}:
        # Un format d'une AUTRE nature (une vidéo demandée en .png, chez une app qui rend l'une ou
        # l'autre — `format_option_groups`) : la conversion l'ignorait sans un mot
        # (`apply_inline_conversion`). Le fichier garde son format, et on le DIT.
        say(f"Format .{fmt} impossible pour une sortie {NATURE_LABELS.get(domain, domain).lower()}"
            f" — format d'origine conservé")
        fmt = ORIGINAL
    preset = getattr(item, 'output_quality', '') or DEFAULT_PRESET
    target = keep_size_target(item, domain, input_size)
    if target is not None:
        # Le converter redimensionne ET convertit d'un même passage. « Original » garde le
        # format du fichier : il est alors réencodé à sa taille d'entrée.
        from wama.common.utils.video_utils import get_media_info
        from wama.converter.utils.inline_convert import apply_inline_conversion
        w, h = target
        say(f"Retour à la résolution d'origine : {w}×{h}")
        resized = []
        for p in paths:
            same = os.path.splitext(p)[1].lower().lstrip('.')
            out = apply_inline_conversion(p, same if fmt in ('', 'original') else fmt, preset,
                                          extra_options={'resize_w': w, 'resize_h': h})
            # La taille se VÉRIFIE sur le fichier rendu : le converter rend sa source inchangée
            # quand il ne sait pas faire (format non pris), sans lever.
            info = get_media_info(out)
            if (info.get('width'), info.get('height')) != (w, h):
                raise RuntimeError(f"retour à {w}×{h} impossible — le fichier rendu fait "
                                   f"{info.get('width')}×{info.get('height')}")
            resized.append(out)
        return resized
    if fmt in ('', 'original'):
        return paths
    try:
        # Le MÉCANISME de conversion vit dans le converter (convention d'appel inline).
        from wama.converter.utils.inline_convert import apply_inline_conversion
        return [apply_inline_conversion(p, fmt, preset) for p in paths]
    except Exception as exc:
        logger.warning("[output] conversion vers %s échouée : %s", fmt, exc)
        say(f"Conversion vers {fmt} échouée ({exc}) — fichier natif conservé")
        return paths


# ── Garder le fichier D'ORIGINE (2026-10-03, décision de Fabien) ─────────────────────────────
# Agrandissement et conversion se faisaient EN PLACE : changer de format après coup obligeait à
# REGÉNÉRER (une image, une vidéo, une voix) pour un réglage qui ne touche que la sortie. La
# brique garde donc le fichier que le moteur a écrit, à côté du rendu, tant que les réglages de
# sortie le TRANSFORMENT ; le process « sortie » d'une app repart de lui. Sans transformation,
# il n'y a qu'un fichier : le natif EST le rendu, rien n'est gardé en double.

#: Marque du nom d'un fichier d'origine gardé : `gen12_sdxl.png` → `gen12_sdxl.native.png`. Le
#: rendu garde le nom que l'app a toujours donné à sa sortie.
NATIVE_MARK = '.native'

#: Champ (liste de chemins relatifs à MEDIA_ROOT) où une card désigne ses fichiers d'origine —
#: celui de `common.models.NativeOutputsMixin`, déclaré à la rétention (`path_lists`).
NATIVE_FIELD = 'native_outputs'


def is_native(path) -> bool:
    """Ce chemin porte-t-il la marque d'un fichier d'origine gardé ?"""
    import os
    return os.path.splitext(os.path.basename(str(path)))[0].endswith(NATIVE_MARK)


def native_name(path) -> str:
    """Le nom sous lequel le fichier d'origine de `path` est gardé (idempotent)."""
    import os
    stem, ext = os.path.splitext(str(path))
    return str(path) if stem.endswith(NATIVE_MARK) else f'{stem}{NATIVE_MARK}{ext}'


def final_name(path) -> str:
    """Le nom du rendu d'un fichier d'origine gardé, avant conversion (idempotent)."""
    import os
    stem, ext = os.path.splitext(str(path))
    return f'{stem[:-len(NATIVE_MARK)]}{ext}' if stem.endswith(NATIVE_MARK) else str(path)


def transforms_output(item, domain: str, output_format: str | None = None,
                      input_size=None) -> bool:
    """Les réglages de sortie de l'item changent-ils le fichier que le moteur a écrit ?"""
    if domain == 'image' and upscale_factor(getattr(item, 'output_upscale', '')) > 1:
        return True
    if keep_size_target(item, domain, input_size) is not None:
        return True
    return wanted_format(item, output_format) not in ('', 'original')


def render_outputs(sources, item, *, domain: str, app_id: str | None = None, console=None,
                   previous=(), output_format: str | None = None, transform=None,
                   apply=None, input_size=None, then_settings: bool = False) -> tuple:
    """Les réglages de sortie appliqués en GARDANT le fichier d'origine ; rend
    `(rendus, originaux gardés)`, en chemins absolus.

    `sources` : ce dont on part — les fichiers que le moteur vient d'écrire, OU les originaux
    gardés d'un rendu précédent (reconnus à leur marque) : c'est ce qui laisse rejouer la sortie
    SEULE après un changement de format. `previous` : les rendus de la fois d'avant ; ceux que ce
    rendu ne reprend pas sont retirés (un `.webp` quand on revient au PNG).

    Sans transformation, l'original reprend son nom de rendu et rien n'est gardé en double.
    `transform` / `apply` : une transformation PROPRE à l'app, à la place des réglages de sortie
    communs (l'amélioration faciale de l'avatarizer) — `transform` dit si elle a lieu,
    `apply(copie) -> chemin(s)` la joue sur la COPIE de l'original et rend ce qu'elle a écrit.
    `then_settings` (2026-10-28, D5) : les réglages de sortie COMMUNS (format, qualité) s'appliquent
    APRÈS la transformation de l'app, au lieu d'être remplacés par elle — un même original gardé,
    un seul process ; ils valent aussi quand la transformation de l'app n'a pas lieu.
    Les règles d'`apply_output_settings` valent : un agrandissement demandé qui échoue LÈVE, une
    conversion qui échoue garde le rendu au format d'origine et le dit."""
    import os
    import shutil

    finals, natives = [], []
    common = transforms_output(item, domain, output_format, input_size)
    if transform is None:
        transform = common
    settings_after = apply is not None and then_settings and common
    for source in list(sources or []):
        source = str(source)
        target = final_name(source)
        if not (transform or settings_after):
            if source != target:
                os.replace(source, target)
            finals.append(target)
            continue
        kept = native_name(source)
        if source != kept:
            os.replace(source, kept)
        shutil.copy2(kept, target)
        try:
            if apply is not None:
                produced = apply(target) if transform else target
                produced = [produced] if isinstance(produced, str) else list(produced)
                if settings_after:
                    produced = apply_output_settings(produced, item, domain=domain, app_id=app_id,
                                                     console=console, output_format=output_format,
                                                     input_size=input_size)
                finals.extend(produced)
            else:
                finals.extend(apply_output_settings([target], item, domain=domain, app_id=app_id,
                                                    console=console, output_format=output_format,
                                                    input_size=input_size))
        except Exception:
            # Un échec (agrandissement demandé, impossible) ne laisse rien derrière lui : l'original
            # reprend la place d'où il venait, comme si la sortie n'avait pas été tentée.
            os.replace(kept, source)
            if target != source and os.path.isfile(target):
                os.remove(target)
            raise
        natives.append(kept)
    keep = {os.path.abspath(p) for p in finals + natives}
    for old in previous or ():
        old = str(old)
        if os.path.abspath(old) not in keep and os.path.isfile(old):
            os.remove(old)
    return finals, natives
