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
"""
from __future__ import annotations

from django.utils.translation import gettext_lazy as _

# Groupes d'affichage : un SÉPARATEUR est inséré à chaque changement de groupe. C'est ainsi que
# reader et transcriber séparaient déjà « formats texte » / « documents » / « brut » — le
# regroupement REPRODUIT leur mise en forme au lieu de l'aplatir (règle : généraliser sans
# changer ce que l'utilisateur voit).
TEXTE, DOCUMENT, BRUT = 'texte', 'document', 'brut'

VOCABULAIRE: dict[str, dict] = {
    'txt':  {'label': 'TXT',        'icone': 'fas fa-file-alt',           'groupe': TEXTE},
    'md':   {'label': 'Markdown',   'icone': 'fab fa-markdown',           'groupe': TEXTE},
    'srt':  {'label': 'SRT',        'icone': 'fas fa-closed-captioning',  'groupe': TEXTE},
    'vtt':  {'label': 'VTT',        'icone': 'fas fa-closed-captioning',  'groupe': TEXTE},
    'pdf':  {'label': 'PDF',        'icone': 'fas fa-file-pdf text-danger',   'groupe': DOCUMENT},
    'docx': {'label': 'DOCX',       'icone': 'fas fa-file-word text-primary', 'groupe': DOCUMENT},
    'json': {'label': _('JSON brut'), 'icone': 'fas fa-code text-warning',    'groupe': BRUT},
}

# Ordre d'affichage stable, quel que soit l'ordre de déclaration de l'app : le premier format
# reste le format PAR DÉFAUT du bouton principal, les autres suivent le vocabulaire.
_ORDRE = list(VOCABULAIRE)


def entree(valeur: str) -> dict:
    """Décrit UN format. Un format inconnu du vocabulaire reste affichable (repli neutre) —
    une app ne doit jamais perdre un bouton parce qu'elle a déclaré un format exotique."""
    v = (valeur or '').lower().lstrip('.')
    meta = VOCABULAIRE.get(v) or {'label': v.upper(), 'icone': 'fas fa-file', 'groupe': DOCUMENT}
    return {'valeur': v, **meta}


def entrees(formats, disponibles=None) -> list[dict]:
    """
    Liste ordonnée d'entrées prêtes pour `common/_download_button.html`.

    `formats`      : ce que l'app DÉCLARE (`APP_CATALOG[app]['conventions']['export_formats']`).
    `disponibles`  : restriction au niveau de l'ITEM (optionnelle) — reader n'offre `json` que si
                     l'item porte un `raw_result`. Un format déclaré mais indisponible sur CET
                     élément ne doit pas s'afficher : la déclaration dit ce que l'app sait faire,
                     l'item dit ce qu'il a.
    Chaque entrée porte `separateur=True` quand elle ouvre un nouveau groupe (jamais la première).
    """
    if isinstance(formats, str):
        formats = [f for f in formats.replace(' ', '').split(',') if f]
    voulus = [f.lower().lstrip('.') for f in (formats or [])]
    if disponibles is not None:
        # Accepte une CHAÎNE « txt,md,pdf » : un gabarit Django ne sait pas construire une liste
        # sans contorsion (`{% with %}` refuse une expression filtrée), et exiger une property de
        # modèle pour une restriction d'affichage serait faire payer le modèle pour l'UI.
        if isinstance(disponibles, str):
            disponibles = [d for d in disponibles.replace(' ', '').split(',') if d]
        permis = {f.lower().lstrip('.') for f in disponibles}
        voulus = [f for f in voulus if f in permis]
    # Ordre du vocabulaire, puis les inconnus à la fin (dans l'ordre déclaré).
    connus = [f for f in _ORDRE if f in voulus]
    inconnus = [f for f in voulus if f not in VOCABULAIRE]
    sortie, groupe_precedent = [], None
    for f in connus + inconnus:
        e = entree(f)
        e['separateur'] = groupe_precedent is not None and e['groupe'] != groupe_precedent
        groupe_precedent = e['groupe']
        sortie.append(e)
    return sortie


def entrees_pour_app(app_name: str, disponibles=None) -> list[dict]:
    """Idem, en lisant la déclaration de l'app — l'appelant n'a que son nom à donner."""
    try:
        from wama.common.app_registry import APP_CATALOG
        conv = (APP_CATALOG.get(app_name, {}) or {}).get('conventions', {}) or {}
    except Exception:
        return []
    return entrees(conv.get('export_formats') or (), disponibles)
