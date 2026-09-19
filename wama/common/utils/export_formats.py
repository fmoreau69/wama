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

VOCABULARY: dict[str, dict] = {
    'txt':  {'label': 'TXT',        'icon': 'fas fa-file-alt',           'group': TEXT},
    'md':   {'label': 'Markdown',   'icon': 'fab fa-markdown',           'group': TEXT},
    'srt':  {'label': 'SRT',        'icon': 'fas fa-closed-captioning',  'group': TEXT},
    'vtt':  {'label': 'VTT',        'icon': 'fas fa-closed-captioning',  'group': TEXT},
    'pdf':  {'label': 'PDF',        'icon': 'fas fa-file-pdf text-danger',   'group': DOCUMENT},
    'docx': {'label': 'DOCX',       'icon': 'fas fa-file-word text-primary', 'group': DOCUMENT},
    'json': {'label': _('JSON brut'), 'icon': 'fas fa-code text-warning',    'group': RAW},
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
    b = _BUILDERS.get(app_name)
    if b is None:
        try:
            from wama.common.app_registry import APP_CATALOG
            source = (APP_CATALOG.get(app_name) or {}).get('generated_from')
        except Exception:
            source = None
        return export_builder_for(source) if source and source != app_name else None
    if isinstance(b, str):
        from importlib import import_module
        module, _, attr = b.partition(':')
        try:
            b = getattr(import_module(module), attr)
        except Exception:
            return None
        _BUILDERS[app_name] = b
    return b if callable(b) else None
