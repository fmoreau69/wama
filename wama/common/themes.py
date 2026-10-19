"""Thèmes de WAMA — LA déclaration (chantier ouvert le 2026-10-17, demande de Fabien : « ça
fonctionnera aussi quand on aura mis en place plusieurs thèmes/modes (sombre/clair/UGE/etc) »).

Un thème, c'est :
  • une clé et un libellé, déclarés ICI — la page, le scénario de contraste et le choix du
    compte (carte « Apparence » du Profil) les lisent ici, jamais dans une liste recopiée ;
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
    #: Le thème dont il reçoit toutes les valeurs (liste de sélecteurs du bloc de ce thème dans
    #: `wama-theme.css`) ; son propre bloc ne redéfinit que ce que sa charte change. '' = complet.
    base: str = ''
    #: La charte (`CHARTERS`) d'où vient chaque couleur de son bloc — exigée d'un thème dérivé.
    charter: str = ''
    #: Le logo que la barre du haut montre sous ce thème (chemin de fichier statique), tel que sa
    #: charte le fournit ; '' = aucun.
    logo: str = ''

    def to_dict(self) -> dict:
        return asdict(self)


THEMES = (
    Theme('dark', 'Sombre', bootstrap='dark'),
    # Le miroir de luminance du sombre (contrastes conservés), sur le mode clair natif de
    # Bootstrap — étape 4, 2026-10-18 ; la règle et ses exceptions : en-tête de son bloc.
    Theme('light', 'Clair', bootstrap='light'),
    # La charte de l'université, claire : le clair, dont l'identité devient la sienne (2026-10-19,
    # Fabien : « on passe au thème UGE ») ; son logo dans la barre du haut (même jour, « oui pour
    # le logo UGE »).
    Theme('uge', 'Université Gustave Eiffel', bootstrap='light', base='light', charter='uge',
          logo='common/images/themes/logo-uge.svg'),
    # Le design system de La Suite numérique (Cunningham, MIT), en clair (2026-10-19, Fabien :
    # « j'aimerais aussi un thème la suite numérique ») …
    Theme('lasuite', 'La Suite numérique', bootstrap='light', base='light', charter='lasuite'),
    # … et en sombre, que Cunningham décline aussi — le clair reste La Suite « de base » (même
    # jour, Fabien : « La Suite en sombre, mais la suite de base en version claire »).
    Theme('lasuite-dark', 'La Suite numérique (sombre)', bootstrap='dark', base='dark',
          charter='lasuite'),
)

#: Les CHARTES graphiques dont un thème dérivé tire ses couleurs — chaque couleur écrite dans son
#: bloc en vient (`tests_theme` le vérifie) : une couleur de la charte, ou une teinte que Bootstrap
#: en calcule (`derived` : nom → (couleur de la charte, mélange, part de la couleur)).
CHARTERS = {
    'uge': {
        'source': 'claude/Charte_Gustave_Eiffel/Charte_Gustave_Eiffel_V2-4.pdf',
        'colors': {
            'principale (Pantone 2746C)': '#2f2a85',
            'bleu nuit': '#0f273b', 'rose': '#e83583', 'rouge': '#d2213c', 'vert': '#00936e',
            'vert clair': '#92c56e', 'cyan': '#1eafd0', 'bleu': '#0097d7', 'jaune': '#fbba00',
            'orange': '#ef7d00', 'violet': '#8b4a97',
            'fond de page (relevé sur ses pages)': '#f1f2f2',
        },
        'derived': {
            '#131135': ('#2f2a85', '#000000', 0.40),   # `--bs-primary-text-emphasis`
            '#d5d4e7': ('#2f2a85', '#ffffff', 0.20),   # `--bs-primary-bg-subtle`
            '#acaace': ('#2f2a85', '#ffffff', 0.40),   # `--bs-primary-border-subtle`
        },
    },
    # Les valeurs de sa palette globale ; le RÔLE de chacune est celui que Cunningham lui donne,
    # en clair et en sombre (ses tokens « contextuels » : fond de marque = brand-550, texte de
    # marque = brand-700 en clair, brand-100 / brand-250 en sombre, page = gray-025 / gray-900…).
    'lasuite': {
        'source': 'github.com/suitenumerique/cunningham (MIT) — packages/react/src/cunningham-tokens.css',
        'colors': {
            'brand-100': '#d5e4f7', 'brand-250': '#96bcec', 'brand-300': '#80aee8',
            'brand-350': '#6ca0e4', 'brand-450': '#4085dc', 'brand-550': '#1167d4',
            'brand-600': '#0659c5', 'brand-700': '#20467f', 'brand-850': '#1a2638',
            'purple-550': '#8b43da', 'gray-025': '#f7f8f8', 'gray-900': '#1b1c1d',
        },
        'derived': {},
    },
}

#: Les polices d'une charte sous licence COMMERCIALE ne sont jamais servies par WAMA (le dépôt est
#: public, et la licence fournie avec TT Norms — Monotype, poste unique — interdit de la
#: distribuer, de la poser sur un serveur ou de la convertir) : un thème la NOMME, et le
#: navigateur ne l'emploie que si elle est installée sur le poste ; sinon, le repli de sa charte.
#: `tests_theme` refuse un fichier de ces polices dans les dossiers statiques.
LICENSED_FONTS = ('TT Norms',)

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


# ── Le CHOIX du compte (étape 5, 2026-10-19 — Fabien : « ok pour le Profil avec Auto ») ──────
# Un réglage durable du compte (`user_settings`), comme l'avatar de l'assistant : une préférence
# de plus, pas un mécanisme. Il se règle au Profil (carte « Apparence ») et vaut sur toute page.

#: Le choix « Automatique » : le thème suit le mode clair ou sombre du système
#: (`prefers-color-scheme`), lu par `common/js/wama-theme.js` — le serveur ne le connaît pas.
AUTO = 'auto'
AUTO_LABEL = 'Automatique (suit le système)'
#: Le thème que prend « Automatique », par mode du système.
AUTO_THEMES = {'dark': 'dark', 'light': 'light'}
#: Le choix de qui n'a rien choisi, ou n'a pas de compte : le SOMBRE, pas « Automatique »
#: (Fabien, 2026-10-19 : « la plupart des gens ont leur système en clair, or le thème sombre est
#: plus agréable actuellement »). C'est aussi ce qui garde les captures nocturnes en sombre :
#: Playwright se présente comme un système clair, et le compte de test ne choisit rien.
DEFAULT_CHOICE = DEFAULT
#: Où vit le choix : `user_settings`, app `common` (les réglages du compte, hors de toute app).
SETTING_APP, SETTING_NAME = 'common', 'theme'


def choices() -> list[tuple[str, str]]:
    """Ce que propose le Profil : « Automatique », puis chaque thème déclaré."""
    return [(AUTO, AUTO_LABEL)] + [(t.key, t.label) for t in THEMES]


def _valid(value) -> bool:
    return value == AUTO or any(t.key == value for t in THEMES)


def theme_choice(user) -> str:
    """Le choix du compte : une clé de thème, ou `AUTO`. `DEFAULT_CHOICE` sans compte, sans
    choix posé, ou si le thème choisi n'est plus déclaré. Fail-safe : une panne du store rend le
    défaut, jamais une page en erreur."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return DEFAULT_CHOICE
    try:
        from wama.common.utils.user_settings import get_user_app_setting
        value = get_user_app_setting(user, SETTING_APP, SETTING_NAME, DEFAULT_CHOICE)
    except Exception:
        return DEFAULT_CHOICE
    return value if _valid(value) else DEFAULT_CHOICE


def save_theme_choice(user, value) -> str:
    """Enregistre le choix du compte ; `ValueError` pour un choix qui n'est pas proposé."""
    if not _valid(value):
        raise ValueError(f"Thème inconnu : '{value}'")
    from wama.common.utils.user_settings import save_user_app_settings
    save_user_app_settings(user, SETTING_APP, {SETTING_NAME: value})
    return value


def resolve(choice: str) -> Theme:
    """Le thème que le SERVEUR pose pour un choix. « Automatique » rend le défaut : le script de
    `base.html` le corrige avant le premier rendu, selon le mode du système."""
    return theme(DEFAULT if choice == AUTO else choice)


def declared_for_pages(choice: str) -> dict:
    """Ce que lit `wama-theme.js` : le choix, le mode de Bootstrap de chaque thème, et le thème que
    prend « Automatique » par mode du système — lus ICI, jamais recopiés dans le script."""
    return {'choice': choice, 'auto': AUTO, 'fallback': DEFAULT,
            'modes': {t.key: t.bootstrap for t in THEMES}, 'system': dict(AUTO_THEMES)}


def theme_for(request) -> Theme:
    """Le thème que le serveur pose pour une requête (le choix du compte connecté)."""
    return resolve(theme_choice(getattr(request, 'user', None)))
