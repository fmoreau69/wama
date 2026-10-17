"""Thèmes de WAMA — LA déclaration (chantier ouvert le 2026-10-17, demande de Fabien : « ça
fonctionnera aussi quand on aura mis en place plusieurs thèmes/modes (sombre/clair/UGE/etc) »).

Un thème, c'est :
  • une clé et un libellé, déclarés ICI — la page, le scénario de contraste et (demain) la
    préférence du compte les lisent ici, jamais dans une liste recopiée ;
  • ses VALEURS, dans `common/css/wama-theme.css`, bloc `:root[data-wama-theme="<clé>"]` — un
    composant ne pose plus de couleur, il lit un token (`var(--wama-text-label)`) ;
  • le mode natif de Bootstrap 5.3 sur lequel il s'appuie (`data-bs-theme`).

⚠ Le sombre d'aujourd'hui est PEINT À LA MAIN sur un Bootstrap en mode CLAIR — d'où
`bootstrap='light'`, qui est la vérité, pas une faute de frappe. Mesuré le 2026-10-17 : poser
`data-bs-theme="dark"` ne change aucun contraste des 30 pages de `common.contrast` (sauf un lien,
qui y gagne), mais il change les états INTERACTIFS que ces pages ne montrent pas — alertes,
champs de formulaire, tableaux, modales. Basculer est donc l'étape suivante du chantier, mesurée
à part (`WAMA_VERIFICATION §10`).

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
    Theme('dark', 'Sombre', bootstrap='light'),
)

#: Le thème de qui n'a rien choisi — aussi celui que `wama-theme.css` pose sur `:root` seul.
DEFAULT = 'dark'


def theme(key: str) -> Theme:
    """Le thème déclaré sous `key`, sinon le thème par défaut (jamais une page sans thème)."""
    return next((t for t in THEMES if t.key == key), None) or next(t for t in THEMES if t.key == DEFAULT)


def theme_for(request) -> Theme:
    """Le thème d'une requête. Aucune préférence n'existe encore : c'est le défaut. ⏳ La
    préférence du compte viendra des réglages durables (`user_settings`), comme celle de
    l'avatar (`context_processors.assistant_avatar`) — une préférence de plus, pas un mécanisme."""
    return theme(DEFAULT)
