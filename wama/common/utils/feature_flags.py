"""
Bascules de fonctionnalités (feature flags) portées par un objet-config — mécanisme GÉNÉRIQUE.

But : pouvoir comparer instantanément un traitement AVEC/SANS une amélioration, sans
dupliquer le code ni multiplier les branches ad hoc. Chaque app déclare son registre de
`Feature` ; l'état effectif = défauts du registre surchargés par le JSON de l'objet
porteur (ex. `AnalysisSession.config['features']` pour cam_analyzer, demain n'importe
quel objet de WAMA Data exposant un champ config).

Contrat :
- le registre est la SOURCE UNIQUE des clés, libellés, descriptions et défauts ;
- l'objet porteur ne stocke QUE les surcharges (dict {key: bool}) — un flag absent
  retombe sur son défaut, ce qui permet de changer les défauts sans migration ;
- `scope` distingue les bascules à effet immédiat (`live` : rendu/affichage) de celles
  qui exigent de relancer un calcul (`compute`) — l'UI s'en sert pour prévenir.

Utilisé par : cam_analyzer (premier consommateur). Conçu pour WAMA Data.
"""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Feature:
    key: str            # identifiant stable (snake_case) — clé de surcharge en config
    label: str          # libellé court pour l'UI
    description: str    # effet précis (UI + doc)
    default: bool = True
    scope: str = 'live'  # 'live' = effet immédiat ; 'compute' = recalcul nécessaire


def resolve(registry, config):
    """État effectif {key: bool} : défauts du registre surchargés par config['features']."""
    overrides = (config or {}).get('features') or {}
    return {f.key: bool(overrides.get(f.key, f.default)) for f in registry}


def is_enabled(registry, config, key):
    """État effectif d'UNE bascule (KeyError si la clé n'est pas au registre)."""
    state = resolve(registry, config)
    return state[key]


def describe(registry, config=None):
    """Catalogue sérialisable pour l'UI : métadonnées + état effectif de chaque bascule."""
    state = resolve(registry, config)
    return [{**asdict(f), 'enabled': state[f.key]} for f in registry]


def sanitize_overrides(registry, raw):
    """Filtre un dict de surcharges venu du client : clés connues, valeurs booléennes."""
    known = {f.key for f in registry}
    return {k: bool(v) for k, v in (raw or {}).items() if k in known}
