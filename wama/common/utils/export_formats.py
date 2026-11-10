"""
Vocabulaire COMMUN des formats de TÉLÉCHARGEMENT — libellé, icône et regroupement.

Pendant d'`output_formats.py`, mais pour l'autre bout de la chaîne : `output_formats` sert les
apps **early-binding** (le format est un réglage AVANT génération, donc un `Param` de schéma) ;
ce module-ci sert les apps **late-binding**, où le format est choisi AU TÉLÉCHARGEMENT et rendu
par le split-button de `WAMA_APP_CONVENTIONS §6.3`.

POURQUOI CE MODULE EXISTE (mesuré le 2026-08-23). Des six boutons d'action d'une card, ⬇ était le
SEUL sans brique — et le seul encore divergent : trois apps écrivaient leur dropdown à la main
(describer, reader, transcriber) et deux rendaient un `<button>`+JS là où leur PROPRE déclaration
disait « lien » (anonymizer, imager). La doctrine, elle, était écrite depuis longtemps (§6.3) et
la déclaration `export_binding` était JUSTE sur 10 apps sur 10. Ce qui manquait n'était donc ni
la règle ni la donnée : c'était le morceau de code qui les relie.

Le relevé des trois dropdowns écrits à la main a montré des icônes et libellés **identiques** pour
les formats partagés — la table ci-dessous ne tranche donc aucun arbitrage, elle constate.

⚠ RENOMMAGE DU 2026-08-30 (question de Fabien : « je vois encore un nom de fonction en français »).
`VOCABULAIRE` / `entree` / `entrees` / `entrees_pour_app` et les clés de payload `valeur`/`icone`/
`groupe`/`separateur` sont passés à l'anglais. Ce module est IMPORTÉ et son tag est lu dans 12
gabarits : c'est une API, donc la règle de AGENTS.md s'applique sans exception. Il avait échappé
à la passe du 29/08 parce que celle-ci visait le model_manager et le JS commun — *un renommage se
mesure sur un CRITÈRE, jamais sur la liste des fichiers qu'on avait en tête*.
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _

# Groupes d'affichage : un SÉPARATEUR est inséré à chaque changement de groupe. C'est ainsi que
# reader et transcriber séparaient déjà « formats texte » / « documents » / « brut » — le
# regroupement REPRODUIT leur mise en forme au lieu de l'aplatir (règle : généraliser sans
# changer ce que l'utilisateur voit).
TEXT, DOCUMENT, RAW = 'text', 'document', 'raw'
#: Les PARTITIONS (2026-11-08, la partition lue du Reader) : leur propre groupe, séparé du texte.
SCORE = 'score'

_DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

#: `mime` (2026-10-28) : le type servi au téléchargement d'UN élément (`download_response`) — les
#: trois vues d'app l'écrivaient chacune à la main.
VOCABULARY: dict[str, dict] = {
    'txt':  {'label': 'TXT',        'icon': 'fas fa-file-alt',           'group': TEXT,
             'mime': 'text/plain; charset=utf-8'},
    'md':   {'label': 'Markdown',   'icon': 'fab fa-markdown',           'group': TEXT,
             'mime': 'text/markdown; charset=utf-8'},
    'srt':  {'label': 'SRT',        'icon': 'fas fa-closed-captioning',  'group': TEXT,
             'mime': 'text/plain; charset=utf-8'},
    'vtt':  {'label': 'VTT',        'icon': 'fas fa-closed-captioning',  'group': TEXT,
             'mime': 'text/vtt; charset=utf-8'},
    'pdf':  {'label': 'PDF',        'icon': 'fas fa-file-pdf text-danger',   'group': DOCUMENT,
             'mime': 'application/pdf'},
    'docx': {'label': 'DOCX',       'icon': 'fas fa-file-word text-primary', 'group': DOCUMENT,
             'mime': _DOCX_MIME},
    'json': {'label': _('JSON brut'), 'icon': 'fas fa-code text-warning',    'group': RAW,
             'mime': 'application/json; charset=utf-8'},
    'abc':  {'label': 'ABC',        'icon': 'fas fa-music',              'group': SCORE,
             'mime': 'text/vnd.abc; charset=utf-8'},
    'musicxml': {'label': 'MusicXML', 'icon': 'fas fa-music text-primary', 'group': SCORE,
                 'mime': 'application/vnd.recordare.musicxml+xml'},
}

# Ordre d'affichage stable, quel que soit l'ordre de déclaration de l'app : le premier format
# reste le format PAR DÉFAUT du bouton principal, les autres suivent le vocabulaire.
_ORDER = list(VOCABULARY)


def entry(value: str) -> dict:
    """Décrit UN format. Un format inconnu du vocabulaire reste affichable (repli neutre) —
    une app ne doit jamais perdre un bouton parce qu'elle a déclaré un format exotique."""
    v = (value or '').lower().lstrip('.')
    meta = VOCABULARY.get(v) or {'label': v.upper(), 'icon': 'fas fa-file', 'group': DOCUMENT}
    return {'value': v, **meta}


def entries(formats, available=None) -> list[dict]:
    """
    Liste ordonnée d'entrées prêtes pour `common/_download_button.html`.

    `formats`   : ce que l'app DÉCLARE (`APP_CATALOG[app]['conventions']['export_formats']`).
    `available` : restriction au niveau de l'ITEM (optionnelle) — reader n'offre `json` que si
                  l'item porte un `raw_result`. Un format déclaré mais indisponible sur CET
                  élément ne doit pas s'afficher : la déclaration dit ce que l'app sait faire,
                  l'item dit ce qu'il a.
    Chaque entrée porte `separator=True` quand elle ouvre un nouveau groupe (jamais la première).
    """
    if isinstance(formats, str):
        formats = [f for f in formats.replace(' ', '').split(',') if f]
    wanted = [f.lower().lstrip('.') for f in (formats or [])]
    if available is not None:
        # Accepte une CHAÎNE « txt,md,pdf » : un gabarit Django ne sait pas construire une liste
        # sans contorsion (`{% with %}` refuse une expression filtrée), et exiger une property de
        # modèle pour une restriction d'affichage serait faire payer le modèle pour l'UI.
        if isinstance(available, str):
            available = [d for d in available.replace(' ', '').split(',') if d]
        allowed = {f.lower().lstrip('.') for f in available}
        wanted = [f for f in wanted if f in allowed]
    # Ordre du vocabulaire, puis les inconnus à la fin (dans l'ordre déclaré).
    known = [f for f in _ORDER if f in wanted]
    unknown = [f for f in wanted if f not in VOCABULARY]
    out, previous_group = [], None
    for f in known + unknown:
        e = entry(f)
        e['separator'] = previous_group is not None and e['group'] != previous_group
        previous_group = e['group']
        out.append(e)
    return out


def entries_for_app(app_name: str, available=None) -> list[dict]:
    """Idem, en lisant la déclaration de l'app — l'appelant n'a que son nom à donner."""
    try:
        from wama.common.app_registry import APP_CATALOG
        conv = (APP_CATALOG.get(app_name, {}) or {}).get('conventions', {}) or {}
    except Exception:
        return []
    return entries(conv.get('export_formats') or (), available)


#: Les formats déclarés qu'un élément NE PEUT PAS rendre : `{app: (élément) -> formats}` — le
#: `json` du reader suppose un `raw_result`. Déclaré par l'app (`register_export_missing`), lu
#: par le bouton ⬇ de la card ET par la visionneuse : la règle vivait dans le gabarit de la
#: card seul (2026-10-13), la visionneuse l'aurait ignorée. Par ce qui MANQUE, pour ne jamais
#: recopier la liste déclarée.
_MISSING: dict = {}


def register_export_missing(app_name: str, missing) -> None:
    """`missing` : `(élément) -> itérable des formats déclarés` que CET élément n'a pas."""
    _MISSING[app_name] = missing


def available_formats(app_name: str, item):
    """Les formats déclarés que `item` peut rendre, ou None (= tous ceux que l'app déclare)."""
    missing = _MISSING.get(app_name)
    if missing is None or item is None:
        return None
    absent = {f.lower() for f in missing(item)}
    return [e['value'] for e in entries_for_app(app_name) if e['value'] not in absent]


def requested_format(app_name: str, query) -> str:
    """Le format DEMANDÉ à un téléchargement d'une app late-binding, lu dans la query du bouton ⬇
    commun (`?format=`) et borné aux formats que l'app DÉCLARE ; absent ou inconnu → le premier
    déclaré (celui du bouton principal). `''` pour une app qui ne déclare aucun format.

    `?fmt=` reste lu : c'était la graphie des menus de LOT, écrits à la main par app jusqu'au
    2026-10-02 (les deux autres niveaux, card et barre de file, disaient déjà `format`) — un lien
    gardé en favori ou une page ouverte avant le rechargement ne doit pas retomber sur le défaut.
    """
    declared = [e['value'] for e in entries_for_app(app_name)]
    if not declared:
        return ''
    asked = str(query.get('format') or query.get('fmt') or '').lower().lstrip('.')
    return asked if asked in declared else declared[0]


def download_response(app_name: str, item, query, stem: str):
    """Le ⬇ d'UN élément d'une app late-binding : le format DEMANDÉ (`requested_format`, borné aux
    formats déclarés), rendu par le rendu que l'app a ENREGISTRÉ (`export_builder_for`) — le même
    que son ZIP de lot, la médiathèque et l'assistant. Rend la réponse, ou None si l'élément ne
    peut pas rendre ce format (pas encore de résultat, rendu en échec — le rendu le journalise).

    Avant le 2026-10-28, les trois vues `download` (transcriber, describer, reader) recodaient
    chacune leurs formats à côté de ce rendu : le SRT du transcriber s'écrivait de quatre façons
    selon le chemin, et le fichier d'un élément n'était pas celui de son entrée dans le ZIP."""
    render = export_builder_for(app_name)
    fmt = requested_format(app_name, query)
    built = render(item, fmt) if (render is not None and fmt) else None
    if not built:
        return None
    ext, data = built
    return attachment(data, ext, stem)


def attachment(data, ext: str, stem: str):
    """La réponse qui sert `data` en fichier `<stem>.<ext>`, au type du vocabulaire — celle d'un
    élément (`download_response`) et du fichier combiné d'un lot (`batch_download?combine=1`)."""
    from django.http import HttpResponse
    from django.utils.http import content_disposition_header
    response = HttpResponse(data, content_type=(VOCABULARY.get(ext) or {}).get(
        'mime', 'application/octet-stream'))
    response['Content-Disposition'] = content_disposition_header(True, f'{stem}.{ext}')
    return response


def rendered_stem(app_name: str, instance, source_name: str = '') -> str:
    """Souche du nom d'un rendu late-binding — la convention du téléchargement
    (`compose_output_name` : tag de process + identifiant de card), lue par la médiathèque et par
    « Envoyer vers » (2026-11-03). `source_name` : le nom d'entrée quand l'élément n'a pas de
    `filename`."""
    from pathlib import Path

    from wama.common.utils.output_naming import compose_output_name
    source = getattr(instance, 'filename', '') or source_name
    try:
        return Path(compose_output_name(app=app_name, source_name=source or '',
                                        item_id=instance.pk)).stem
    except Exception:
        return f'{app_name}_{instance.pk}'


def is_late_binding(app_name: str) -> bool:
    """L'app choisit-elle son format AU TÉLÉCHARGEMENT (`export_binding='late'`, §6.4) ?
    Le master est alors un texte structuré ; le fichier n'existe qu'une fois RENDU."""
    try:
        from wama.common.app_registry import APP_CATALOG
        conv = (APP_CATALOG.get(app_name, {}) or {}).get('conventions', {}) or {}
    except Exception:
        return False
    return conv.get('export_binding') == 'late' or bool(conv.get('multi_format_download'))


# ── Le RENDU d'un format, par app (2026-09-18) ──────────────────────────────────────────────
#
# Les apps late-binding rendent leur master dans un format par UNE fonction, déjà partagée par
# leurs trois téléchargements (unitaire, lot, « tout ») : `build_transcript_bytes(t, fmt)`,
# `build_description_bytes(d, fmt)`, `build_reading_bytes(item, fmt)` → `(ext, bytes)` ou
# `None`. Elle vivait sans registre : seul le JS de l'app savait l'appeler, via `?format=`.
# Le geste « ranger en médiathèque » en avait besoin — sans lui il disait « rien à ranger »
# sur un transcript terminé. Chaque app DÉCLARE son rendu ici, par chemin pointé (résolu au
# premier usage : `apps.ready()` n'importe pas ses vues au boot), et le commun l'appelle.
_BUILDERS: dict = {}


def register_export_builder(app_name: str, builder) -> None:
    """`builder` : callable `(instance, fmt) -> (ext, bytes) | None`, ou son chemin pointé
    `'wama.<app>.views:build_x_bytes'` (résolu paresseusement)."""
    _BUILDERS[app_name] = builder


def export_builder_for(app_name: str):
    """Le rendu déclaré par l'app, ou `None`. Une app early-binding n'en déclare pas : son
    fichier est déjà rendu (`apply_inline_conversion` l'a converti à la génération).

    ⚠ Une JUMELLE de bac à sable (`generated_from` au catalogue) HÉRITE du builder de sa source
    — même dérivation que `importer_for` pour les importeurs : ses vues sont générées et ne
    déclarent rien, mais ses éléments ont la forme de ceux de la source, et le builder ne lit
    que l'élément. Trouvé par le parcours de TOUTES les apps du registre (19/09) : `describer_01`
    répondait « rien à ranger » sur une description terminée.
    """
    return _registered(_BUILDERS, app_name)


def _registered(registry: dict, app_name: str):
    """Le callable inscrit pour `app_name` dans `registry` — son chemin pointé résolu au premier
    usage —, sinon celui de la SOURCE d'une jumelle de bac à sable (`generated_from`), sinon None."""
    b = registry.get(app_name)
    if b is None:
        try:
            from wama.common.app_registry import APP_CATALOG
            source = (APP_CATALOG.get(app_name) or {}).get('generated_from')
        except Exception:
            source = None
        return _registered(registry, source) if source and source != app_name else None
    if isinstance(b, str):
        from importlib import import_module
        module, _, attr = b.partition(':')
        try:
            b = getattr(import_module(module), attr)
        except Exception:
            return None
        registry[app_name] = b
    return b if callable(b) else None


# ── Le fichier COMBINÉ d'un lot (2026-11-10) ────────────────────────────────────────────────
#
# Décision de Fabien (inventaire mesuré des files + concile, 2026-11-09) : un lot fait tourner le
# même traitement une fois par élément (`CARD_DESIGN.md §Le LOT n'a PAS de port`), et rien, dans
# aucune app, ne faisait UN fichier de ses éléments — le lot n'offrait que le ZIP. Le lot garde sa
# règle ; une app qui sait COMBINER les résultats de ses éléments (les pages d'une partition en une
# partition) le DÉCLARE ici, et le ⬇ du lot l'offre à côté du ZIP (`batch_download?combine=1`,
# `make_batch_views`). Seul un lot dont TOUS les éléments ont réussi se combine : un fichier fait
# d'une partie du lot se lirait comme le tout.
#
# Et pour TOUTE app, sans rien déclarer : un lot dont les résultats sont des PAGES (images, PDF)
# se combine en UN PDF (`pages_to_pdf`). Les formats d'une app EARLY-binding ne sont pas ceux du
# téléchargement (`export_formats`, vide chez elle) : ils se règlent AVANT la génération
# (`output_formats.output_format_params`, table du converter par nature). Le PDF y est la sortie
# DÉCLARÉE de la nature image (`CONVERTER_OUTPUT_FORMATS['image']`) : assembler les images d'un
# lot, c'est la conversion image → PDF du converter passée d'un fichier à N (§6.4).
_LOT_BUILDERS: dict = {}
_LOT_FORMATS: dict = {}
#: Le format du lot fait de PAGES.
PAGES_FORMAT = 'pdf'


def register_lot_builder(app_name: str, builder, formats) -> None:
    """`builder` : `(éléments, fmt) -> (ext, bytes) | None` — UN fichier fait des résultats des
    éléments d'un lot, dans l'ordre du lot ; `formats` : `(éléments) -> formats` — ceux qu'il sait
    combiner pour CES éléments, parmi les formats que l'app rend (aucun : il ne combine pas ce lot).
    Chacun peut être un chemin pointé `'wama.<app>.views:…'`, résolu à l'usage."""
    _LOT_BUILDERS[app_name] = builder
    _LOT_FORMATS[app_name] = formats


def lot_builder_for(app_name: str):
    """Le rendu combiné déclaré par l'app (`register_lot_builder`), ou None."""
    return _registered(_LOT_BUILDERS, app_name)


def _own_formats(app_name: str, items) -> list:
    """Les formats que le rendu DÉCLARÉ de l'app combine pour `items` — bornés, pour une app
    late-binding, aux formats qu'elle déclare au téléchargement."""
    formats = _registered(_LOT_FORMATS, app_name)
    if formats is None or lot_builder_for(app_name) is None:
        return []
    found = list(formats(items) or ())
    if is_late_binding(app_name):
        declared = [e['value'] for e in entries_for_app(app_name)]
        found = [f for f in found if f in declared]
    return found


def result_pages(item) -> list:
    """Les fichiers résultats DÉCLARÉS de `item` (`send_to.result_paths`, la lecture du ZIP et
    d'« Envoyer vers ») quand ce sont TOUS des pages — images ou PDF —, sinon []."""
    from wama.common.app_registry import category_of_path
    from wama.common.services.send_to import result_paths
    from wama.common.utils.detail_registry import DetailRegistry
    surface = DetailRegistry.surface_of(type(item))
    paths = result_paths(surface, item) if surface else []
    if paths and all(p.suffix.lower() == '.pdf' or category_of_path(p) == 'image' for p in paths):
        return paths
    return []


def _pages_combine(items) -> bool:
    """Le lot se combine-t-il en PDF ? Tous ses éléments ont des pages pour résultat, et le PDF est
    une sortie déclarée de la nature image (`CONVERTER_OUTPUT_FORMATS`)."""
    from wama.common.app_registry import CONVERTER_OUTPUT_FORMATS
    return (PAGES_FORMAT in (CONVERTER_OUTPUT_FORMATS.get('image') or ())
            and all(result_pages(item) for item in items))


def combined_formats(app_name: str, items) -> list:
    """Les formats en lesquels les éléments `items` d'un lot se combinent en UN fichier : ceux du
    rendu que l'app déclare, sinon le PDF quand leurs résultats sont des pages ; [] pour un lot
    d'un seul élément (son ⬇ suffit). Les pages se lisent sur les RÉSULTATS : un lot dont un
    élément n'a pas encore rendu n'offre pas le PDF."""
    items = list(items or ())
    if len(items) < 2:
        return []
    return _own_formats(app_name, items) or ([PAGES_FORMAT] if _pages_combine(items) else [])


def combined_url(lot_url: str) -> str:
    """L'adresse du fichier combiné d'un lot : celle de son ZIP (`batch_download`), `combine=1`
    ajouté — lue par le bouton de la card mère (`lot_combined`) et par l'assistant."""
    return f"{lot_url}{'&' if '?' in lot_url else '?'}combine=1" if lot_url else ''


def combine_lot(app_name: str, items, fmt: str):
    """`(ext, bytes)` du fichier combiné des `items` au format `fmt`, ou None — le rendu déclaré de
    l'app pour ses formats, sinon les pages assemblées (`pdf_pages.pages_to_pdf`)."""
    items = list(items)
    if fmt in _own_formats(app_name, items):
        return lot_builder_for(app_name)(items, fmt)
    if fmt != PAGES_FORMAT or not _pages_combine(items):
        return None
    import tempfile
    from pathlib import Path

    from wama.common.utils.pdf_pages import pages_to_pdf
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / 'lot.pdf'
        pages_to_pdf([page for item in items for page in result_pages(item)], str(target))
        return PAGES_FORMAT, target.read_bytes()
