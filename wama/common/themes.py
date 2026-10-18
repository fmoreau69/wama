"""Thèmes de WAMA — LA déclaration (chantier ouvert le 2026-10-17, demande de Fabien : « ça
fonctionnera aussi quand on aura mis en place plusieurs thèmes/modes (sombre/clair/UGE/etc) »).

Un thème, c'est :
  • une clé et un libellé, déclarés ICI — la page, le scénario de contraste et (demain) la
    préférence du compte les lisent ici, jamais dans une liste recopiée ;
  • ses VALEURS, dans `common/css/wama-theme.css`, bloc `:root[data-wama-theme="<clé>"]` — un
    composant ne pose plus de couleur, il lit un token (`var(--wama-text-label)`) ;
  • le mode natif de Bootstrap 5.3 sur lequel il s'appuie (`data-bs-theme`).

Le sombre a été PEINT À LA MAIN sur un Bootstrap en mode CLAIR jusqu'au 2026-10-17 ; il repose
depuis sur le mode sombre NATIF (`ROADMAP §28`, étape 2). Mesuré avant de basculer, sur 166 états
(les 30 pages de `common.contrast`, leurs menus ouverts, chacune de leurs modales) : aucun texte
illisible dans aucun des deux modes ; liens, `code`, menus, onglets et croix de fermeture y
gagnent ; un seul défaut, les alertes, dont `app_modern.css` forçait le texte du mode clair
(1,9:1 sur leur fond sombre) — elles lisent désormais `--bs-alert-color`.

Tenu par `tests_theme` : chaque thème déclaré définit chaque token, base.html pose le thème, les
couleurs écrites en dur ne peuvent que diminuer."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    #: Le mode natif de Bootstrap 5.3 sous ce thème : 'light' ou 'dark'.
    bootstrap: str

    def to_dict(self) -> dict:
        return asdict(self)


THEMES = (
    Theme('dark', 'Sombre', bootstrap='dark'),
    # Le miroir de luminance du sombre (contrastes conservés), sur le mode clair natif de
    # Bootstrap — étape 4, 2026-10-18 ; la règle et ses exceptions : en-tête de son bloc.
    Theme('light', 'Clair', bootstrap='light'),
)

#: Le thème de qui n'a rien choisi — aussi celui que `wama-theme.css` pose sur `:root` seul.
DEFAULT = 'dark'

# ── Le thème CLAIR est le miroir du sombre (`theme_mirror.py`), sauf ce qui suit ─────────────
# Chaque exception est une DÉCISION de thème, avec sa raison ; `tests_theme` vérifie que tout le
# reste est le miroir exact (contraste conservé) et que chaque nom déclaré ici existe encore.

#: Surfaces de STRUCTURE, posées sur le Bootstrap clair (#fff, #f8f9fa, #e9ecef) : plus claires
#: que leur miroir, elles ne font que gagner du contraste sous un texte sombre (le test l'exige).
LIGHT_SURFACES = (
    '--wama-page-bg-start', '--wama-page-bg-end', '--wama-surface', '--wama-surface-modal',
    '--wama-surface-modal-rgb', '--wama-surface-raised', '--wama-surface-sunken',
    '--wama-surface-inset', '--wama-surface-wave', '--wama-footer-bg', '--wama-menu-bg',
    '--wama-night-surface', '--wama-night-surface-deep', '--wama-fm-field', '--wama-fm-field-focus',
)

#: Tokens qui ne sont pas des couleurs, posés à la main pour le clair, et pourquoi.
LIGHT_HAND = {
    '--wama-data-ink': "part d'une couleur de DONNÉE lue comme texte : assombrie de moitié sur fond clair",
}

_VIVID = "couleur vive : même identité dans tous les thèmes (lue comme texte, elle passe par `-text`)"
_VIVID_FILL = "couleur vive lue seulement comme fond, trait ou anneau"
_SHADOW = "une ombre est sombre dans tous les thèmes"
_OBJECT = "un objet, pas l'interface : il garde ses couleurs"
_ON_FILL = "texte posé sur un fond de palette, qui ne change pas : il le suit"

#: Même valeur que le sombre.
LIGHT_FIXED = {
    **dict.fromkeys(('--wama-shadow-rgb', '--wama-shadow', '--wama-shadow-strong', '--wama-ring-shadow',
                     '--wama-ml-card-shadow'), _SHADOW),
    **dict.fromkeys(('--wama-paper', '--wama-paper-text', '--wama-paper-band', '--wama-paper-rule',
                     '--wama-fade-end', '--wama-edit-paper-text', '--wama-edit-playing',
                     '--wama-video-bg', '--wama-map-control-text', '--wama-map-control-bg'), _OBJECT),
    **dict.fromkeys(('--wama-text-on-accent', '--wama-text-on-bright', '--wama-select-check'), _ON_FILL),
    **dict.fromkeys(('--wama-state-running', '--wama-state-success', '--wama-state-success-edge',
                     '--wama-state-failure', '--wama-state-awaiting', '--wama-state-awaiting-rgb',
                     '--wama-state-stale', '--wama-accent', '--wama-accent-rgb', '--wama-accent-soft',
                     '--wama-cat-accent', '--wama-cat-accent-rgb', '--wama-cat-active', '--wama-cat-active-rgb',
                     '--wama-eval-best', '--wama-eval-warning', '--wama-tx-reviewed',
                     '--wama-viewer-done'), _VIVID),
    **dict.fromkeys(('--wama-accent-batch', '--wama-accent-filter', '--wama-scrollbar-thumb',
                     '--wama-scrollbar-thumb-hover', '--wama-table-head-end', '--wama-table-row-hover',
                     '--wama-diff-added-border', '--wama-eval-border', '--wama-eval-best-bg',
                     '--wama-eval-isolated-bg', '--wama-collab-mid-rgb', '--wama-param-track',
                     '--wama-param-capped', '--wama-pulse-warning', '--wama-notif-count',
                     '--wama-notif-ok-border', '--wama-notif-ok-bg', '--wama-notif-danger-bg',
                     '--wama-studio-work', '--wama-studio-work-rgb', '--wama-studio-prompt',
                     '--wama-studio-reference', '--wama-studio-stale', '--wama-studio-stale-rgb',
                     '--wama-ml-active-tint', '--wama-ml-provider-tint', '--wama-mm-remote',
                     '--wama-mm-type-summarization', '--wama-mm-type-upscaling',
                     '--wama-mm-selection-tint', '--wama-tone-green-rgb', '--wama-home-info-border'),
                    _VIVID_FILL),
}
#: Familles de même valeur : les scènes AUTONOMES de présentation, sombres par dessein (elles ne
#: passent pas par `base.html`, donc ne reçoivent jamais le thème du compte).
LIGHT_FIXED_PREFIXES = ('--wama-pres-', '--wama-pres1-')


def theme(key: str) -> Theme:
    """Le thème déclaré sous `key`, sinon le thème par défaut (jamais une page sans thème)."""
    return next((t for t in THEMES if t.key == key), None) or next(t for t in THEMES if t.key == DEFAULT)


def theme_for(request) -> Theme:
    """Le thème d'une requête. Aucune préférence n'existe encore : c'est le défaut. ⏳ La
    préférence du compte viendra des réglages durables (`user_settings`), comme celle de
    l'avatar (`context_processors.assistant_avatar`) — une préférence de plus, pas un mécanisme."""
    return theme(DEFAULT)
