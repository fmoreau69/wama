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
