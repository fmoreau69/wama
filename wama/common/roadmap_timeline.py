"""
La frise des grands jalons de WAMA, LUE dans `ROADMAP.md` (section « Frise — les grands jalons »).

POURQUOI (Fabien, 2026-10-13)

    Une vue d'ensemble des grandes étapes, sans le détail des chantiers, tenue dans la ROADMAP et
    DÉRIVÉE dans la présentation. Une seule source : la table de la ROADMAP. La présentation la
    projette (`wama/views.py::presentation`) ; un jalon ne se recopie jamais dans un gabarit.

FORMAT — une table Markdown, une ligne par jalon :

    | Quand | État | Jalon | Détail |
    |---|---|---|---|
    | 2026-09 | ✅ | Les apps se génèrent | Une fiche décrit l'app, le reste se génère. |

    Quand  : texte libre et court (« 2026-09 », « prochain »…) — affiché tel quel.
    État   : ✅ livré · 🔄 en cours · ⏳ à venir (vocabulaire de `doc_sections.STATES`).
    Jalon  : quelques mots. Détail : une phrase, facultative.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from wama.common.doc_sections import STATES, sections
from wama.common.file_cache import FileCache

ROADMAP = 'docs/construction/suivi/ROADMAP.md'
#: Le titre de la section commence par ce mot ; la suite du titre est libre.
SECTION_PREFIX = 'Frise'
#: Classe CSS de chaque état, pour la présentation.
STATE_CLASSES = {'✅': 'ok', '🔄': 'wip', '⏳': 'todo'}

_CACHE = FileCache()


def _cells(row: str) -> List[str]:
    return [c.strip() for c in row.strip().strip('|').split('|')]


def parse(text: str) -> List[Dict[str, str]]:
    """Les jalons de la section « Frise… » d'un texte de ROADMAP, dans l'ordre de la table.

    Lève `ValueError` si la section manque ou si une ligne est mal formée : une frise qui se
    viderait en silence ferait disparaître la diapositive sans que personne ne le voie.
    """
    section = next((s for s in sections(text)[0]
                    if s.level == 2 and s.title.startswith(SECTION_PREFIX)), None)
    if section is None:
        raise ValueError(f"section « {SECTION_PREFIX}… » absente de la ROADMAP")
    rows = [l for l in section.body.splitlines() if l.lstrip().startswith('|')]
    if len(rows) < 3:
        raise ValueError("la frise n'a pas de table (en-tête, séparateur, au moins un jalon)")
    items = []
    for row in rows[2:]:
        cells = _cells(row)
        if len(cells) < 3:
            raise ValueError(f"ligne de frise incomplète : {row.strip()}")
        when, state, label = cells[:3]
        if state not in STATES:
            raise ValueError(f"état « {state} » inconnu (attendu : {' '.join(STATES)}) : {label}")
        items.append({'when': when, 'state': state, 'css': STATE_CLASSES[state],
                       'label': label, 'detail': cells[3] if len(cells) > 3 else ''})
    return items


def milestones() -> List[Dict[str, str]]:
    """Les jalons de la ROADMAP du dépôt, relus seulement quand le fichier change."""
    from django.conf import settings
    path = Path(settings.BASE_DIR) / ROADMAP
    return _CACHE.get(path, lambda p: parse(p.read_text(encoding='utf-8')))
