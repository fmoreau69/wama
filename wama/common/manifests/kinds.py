"""
Registre des KINDS de manifeste — c'est ce qui EMPÊCHE de mélanger des manifestes sans rapport.

Chaque kind fournit :
  - `validate(body) -> list[str]`   : erreurs de structure du `body` (au-delà de l'enveloppe).
  - `extract(key) -> dict | None`   : LIT l'état courant des registres → produit un manifeste complet
                                      (enveloppe + body). Base du round-trip (spec §2).
  - `verify(manifest) -> list[dict]` : diff manifeste ↔ état courant (facultatif ; défaut = compare au
                                      résultat de `extract`).
  - `write_back(manifest, *, apply=False) -> dict` : ÉCRIT les entrées dérivées dans les registres
                                      (dry-run par défaut). IMPLÉMENTÉ sur 4 kinds — cf. spec §7.1 ter.
  - `un_write_back(manifest, *, apply=False) -> dict` : retire les entrées dérivées (réversibilité).

QUI PROJETTE, ET DANS QUELLE MESURE (corrigé le 2026-09-09 — cet en-tête annonçait « 3 kinds » et
rangeait `function` parmi ceux qui n'en ont PAS, alors qu'il en enregistre un depuis 2026-08-11) :

  | kind      | write_back | portée                                                            |
  |-----------|------------|-------------------------------------------------------------------|
  | `app`     | ✅         | facette `access` en base + facettes projetées en CODE              |
  | `library` | ✅         | CRÉE la ligne `common.models.Library`                              |
  | `model`   | ✅         | champs déclaratifs seuls — ne crée JAMAIS la ligne (un modèle se DÉCOUVRE) |
  | `function`| ⚠ PARTIEL  | binding `user` → `UserFunction`. `pure`/`app` = catalogue CODE : REFUSÉ, avec `skipped` |
  | `pipeline` / `project` / `dataset` | ❌ | « store+verify only » : stocké et diffable, n'écrit dans aucun registre |

⚠ LA PORTÉE PARTIELLE DE `function` N'EST PAS DÉCLARÉE, ELLE EST RENVOYÉE À L'EXÉCUTION — un
`{'skipped': …}` par manifeste refusé. Conséquence MESURÉE le 2026-09-09 :
`apply_manifests --kind function` rendait « 62 manifeste(s) · créés 0 · modifiés 0 · **inchangés
62** » alors qu'AUCUN n'avait été tenté. Un refus compté comme « déjà synchrone » se lit comme un
succès. La commande distingue désormais « sauté » d'« inchangé » ; le vocabulaire du kind, lui,
ne sait toujours pas dire « je ne projette que pour tel binding » — c'est un manque de
FORMALISME, pas de construction, et il est ouvert.
*Un vert qui ne se joue pas est pire qu'un rouge.*
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class ManifestKind:
    kind: str
    validate: Callable[[dict], list]                 # body -> [erreurs]
    extract: Optional[Callable[[str], Optional[dict]]] = None   # key -> manifeste complet
    verify: Optional[Callable[[dict], list]] = None             # manifeste -> [diffs]
    # Write-back (facultatif). Contrat RÉEL, tenu par `write_back_app` comme par `write_back_library` :
    #   (manifeste: dict, *, apply: bool = False) -> dict
    # `apply=False` = DRY-RUN qui retourne le PLAN ; `apply=True` écrit (idempotent, transactionnel)
    # et retourne ce qui a changé. L'ancienne annotation `Callable[[dict], None]` décrivait ni les
    # arguments ni le retour et faisait diagnostiquer à tort les deux implémentations existantes.
    # Nommé `write_back` et non `project` : `project` est DÉJÀ le nom d'un kind (le périmètre de
    # collaboration), donc `MANIFEST_KINDS['project'].project` se lisait « le project du project ».
    # Homonyme verbe/nom levé le 2026-08-05 ; le terme write-back avait déjà cours dans le dépôt
    # (docstring de `projection.py`).
    write_back: Optional[Callable[..., dict]] = None
    un_write_back: Optional[Callable[..., dict]] = None
    description: str = ''


MANIFEST_KINDS: dict[str, ManifestKind] = {}


def register_kind(mk: ManifestKind) -> ManifestKind:
    if mk.kind in MANIFEST_KINDS:
        raise ValueError(f"kind '{mk.kind}' déjà enregistré")
    MANIFEST_KINDS[mk.kind] = mk
    return mk


def get_kind(kind: str) -> ManifestKind:
    try:
        return MANIFEST_KINDS[kind]
    except KeyError:
        raise KeyError(
            f"manifest_kind '{kind}' inconnu (enregistrés: {', '.join(sorted(MANIFEST_KINDS)) or '—'})"
        )
