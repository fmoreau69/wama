"""
Backend SheetSage2 — extraction de la partition ABC d'un audio (tâche `audio-to-score`).
(`transcribe` ci-dessous est l'API du modèle amont ; le vocabulaire WAMA est `extract_score`,
« transcribe » désignant déjà le transcriber et la parole.)

Écrit par le rôle `backend` de wama-dev-ai (Albert, 2026-10-03), revu avant validation.

Le moteur est `transformers-remote-code` : le code du modèle est livré DANS son dépôt
(`auto_map`) et exécuté par `trust_remote_code=True`. Le dépôt ne porte qu'un ADAPTATEUR ; son
parent `m-a-p/MERT-v2-FullSong` (composant `base` du catalogue) est chargé par ce code lui-même,
avec le `cache_dir` qu'on lui passe — il se range donc À CÔTÉ du modèle (`component_repos`).

⚠ Chargé par l'IDENTIFIANT du dépôt + `cache_dir` + révision, jamais par le chemin du snapshot :
avec un dossier local, transformers 4.57 ne recopie que les imports relatifs DIRECTS du code
distant (`chord_spelling_sheetsage2.py`, importé en second rang, manque — mesuré le 2026-10-03).
La branche « dépôt » les recopie tous ; `installed_snapshot` donne la révision installée.

Mesuré le 2026-10-03 (RTX 4090) : 2,7 Go de VRAM en float32, 7 s pour 1 min d'audio ; CPU 76 s
pour 18 s. Une note collée à la toute fin de l'audio fait lever le moteur (grille de sous-temps) :
l'erreur est rendue telle quelle, jamais une partition vide.
"""

import logging
from typing import Callable, Optional

from wama.common.utils.model_components import installed_snapshot

from .score_extraction_base import ScoreExtractionBackend

logger = logging.getLogger(__name__)

HF_REPO = "m-a-p/SheetSage2"
MODEL_KEY = f"huggingface:{HF_REPO}"

# Clé LITTÉRALE : l'inventaire la lit par AST — c'est elle qui départage ce backend d'Audio8, qui
# partage le moteur `transformers-remote-code`.
# Le nom de sa ligne de catalogue, et RIEN d'autre : nom, description et VRAM sont au
# REGISTRE (l'inventaire ne lit que la clé) — 2026-10-06, `backend_proposals`.
SUPPORTED_MODELS = {
    "m-a-p/SheetSage2": {"model_key": "huggingface:m-a-p/SheetSage2"},
}


class SheetSage2Backend(ScoreExtractionBackend):
    """SheetSage2 : un audio de morceau → sa partition ABC."""

    ENGINE = "transformers-remote-code"
    name = "sheetsage2"
    display_name = "SheetSage2"
    recommended_vram_gb = 2.7
    description = "Audio → partition (adaptateur SheetSage2 sur MERT-v2-FullSong)."
    REQUIRED_PACKAGES = ["transformers", "torch"]

    def __init__(self):
        super().__init__()
        self._model = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._model is not None:
            return True
        import torch
        from transformers import AutoModel

        snapshot = installed_snapshot(MODEL_KEY)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # float32 : la seule précision mesurée (la sonde du 2026-10-03), 2,7 Go sur GPU.
        self._model = AutoModel.from_pretrained(
            HF_REPO,
            revision=snapshot.name,
            cache_dir=str(snapshot.parent.parent.parent),
            trust_remote_code=True,
        ).to(device).eval()
        self._loaded = True
        self._current_model = HF_REPO
        logger.info("[SheetSage2] chargé (révision %s, %s)", snapshot.name[:12], device)
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._loaded = False
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[SheetSage2] déchargé")

    def extract_score(
        self,
        model_id: str,
        audio_path: str,
        output_dir: Optional[str] = None,
        melody_only: bool = True,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        if self._model is None:
            self.load()
        if progress_callback:
            progress_callback(0)
        import torch
        self.marks = None
        with torch.inference_mode():
            result = self._model.transcribe(audio_path, output_dir=output_dir,
                                            melody_only=melody_only)
        # Ce que la passe a décodé EN PLUS de la partition (parties, mesures, tonalité, accords) :
        # gardé avant tout refus — la structure se lit même quand la notation échoue.
        self.marks = music_marks(result)
        abc = (result or {}).get("abc")
        if not abc:
            raise RuntimeError("SheetSage2 n'a produit aucune partition : "
                               f"{(result or {}).get('abc_error') or 'raison non donnée'}")
        if progress_callback:
            progress_callback(100)
        return with_beat_sync(abc, result)


#: Ce que SheetSage2 écrit pour « aucun accord » (`chord.lab`) : une absence, pas une marque.
NO_CHORD = 'N'


def _lab_rows(result: dict, name: str) -> list:
    """Les lignes d'une annotation du moteur (`labs[name]`, colonnes séparées par une tabulation)."""
    text = ((result or {}).get('labs') or {}).get(name) or ''
    return [line.split('\t') for line in text.splitlines() if line.strip()]


def _spans(rows, name: str, skip=(), joined: bool = False) -> list:
    """Des lignes `début, fin, valeur` → des segments `{start, end, <name>}`, dans l'ordre du
    temps. `joined` : deux segments voisins de même valeur n'en font qu'un (le moteur répète un
    accord à chaque mesure : ce qui se lit sur le temps, c'est quand il CHANGE) — jamais pour les
    parties, où deux couplets qui se suivent sont deux couplets. Voisins : leurs bornes sont la
    même, à la tolérance des marques (`catalog.marks.TOLERANCE`)."""
    from wama.common.catalog.marks import TOLERANCE
    out = []
    for row in rows:
        try:
            start, end, value = round(float(row[0]), 3), round(float(row[1]), 3), row[2].strip()
        except (IndexError, ValueError):
            continue
        if not value or value in skip or end <= start:
            continue
        if (joined and out and out[-1][name] == value
                and abs(out[-1]['end'] - start) <= TOLERANCE):
            out[-1]['end'] = end
        else:
            out.append({'start': start, 'end': end, name: value})
    return out


def _measures(beats, duration: float) -> list:
    """Les MESURES d'un morceau depuis sa grille de temps datés (`beat.lab` : instant, position
    dans la mesure depuis 1, temps par mesure, valeur du temps) : d'un temps fort au suivant,
    numérotées depuis 1 dans l'ordre — une LEVÉE avant le premier temps fort est la mesure 1,
    comme la partition de la même passe l'écrit (complétée de silence). `number` est donc le
    numéro de mesure de cette partition : mesuré sur trois morceaux dont un à levée, les 30
    sections que la partition nomme (`% verse`…) commencent à la mesure où la partie commence
    dans l'audio — numérotée 0, la levée décalait tout d'une mesure. `meter` est le chiffrage que
    le moteur dit pour la mesure, `tempo` ses temps par minute, mesurés d'un temps fort au suivant
    — None pour une mesure INCOMPLÈTE (levée, grille irrégulière) et pour la dernière : un temps
    isolé en bout d'audio donnait 400 et 1 500 à la minute."""
    grid = []
    for row in beats:
        try:
            grid.append((float(row[0]), int(row[1]), int(row[2]), int(row[3])))
        except (IndexError, ValueError):
            continue
    if len(grid) < 2:
        return []
    gaps = sorted(b[0] - a[0] for a, b in zip(grid, grid[1:]))
    close = min(grid[-1][0] + gaps[(len(gaps) - 1) // 2], float(duration or 0) or float('inf'))
    starts = [i for i, beat in enumerate(grid) if beat[1] == 1]
    if not starts:
        return []
    bounds = ([0] if starts[0] else []) + starts
    out = []
    for number, (at, upto) in enumerate(zip(bounds, bounds[1:] + [len(grid)]), start=1):
        start = grid[at][0]
        end = grid[upto][0] if upto < len(grid) else close
        if end > start:
            _, _, per_measure, value = grid[at]
            # Mesurée d'un temps fort au suivant : la dernière, fermée faute de mieux, n'en dit rien.
            whole = upto < len(grid) and upto - at == per_measure
            out.append({'start': round(start, 3), 'end': round(end, 3), 'number': number,
                        'meter': f'{per_measure}/{value}',
                        'tempo': round(per_measure * 60.0 / (end - start), 1) if whole else None})
    return out


def music_marks(result: dict) -> Optional[dict]:
    """Les PISTES du morceau que la passe a décodées (`score_extraction_base.MUSIC_TRACKS`), ou
    None quand le moteur n'en a annoté aucune. Rien n'est recalculé : c'est ce que le moteur écrit
    à côté de sa partition (`structure.lab`, `beat.lab`, `key.lab`, `chord.lab`), sous les noms
    communs des marques."""
    from .score_extraction_base import CHORDS, MEASURES, STRUCTURE, TONALITY
    found = {
        STRUCTURE: _spans(_lab_rows(result, 'structure'), 'label'),
        MEASURES: _measures(_lab_rows(result, 'beat'), (result or {}).get('duration_seconds') or 0),
        TONALITY: _spans(_lab_rows(result, 'key'), 'key', joined=True),
        CHORDS: _spans(_lab_rows(result, 'chord'), 'chord', skip=(NO_CHORD,), joined=True),
    }
    return found if any(found.values()) else None


def with_beat_sync(abc: str, result: dict) -> str:
    """La partition avec ses REPÈRES (`score_timing`, 2026-11-15) : SheetSage2 écrit ses mesures sur
    les temps qu'il a décodés, DATÉS dans l'audio (`labs['beat']` : instant, position, temps par
    mesure, valeur du temps) — chaque mesure commence sur un temps fort, à la longueur que la
    partition lui ÉCRIT (un changement de mesure en cours de morceau compris, la 1re et la dernière
    complétées de silence). Les mesures lues dans la partition doivent être celles que le moteur dit
    avoir écrites (`abc_measures`), et la partition à tempo constant ; sinon aucun repère, la page
    cale sur les attaques."""
    from wama.common.utils.score_timing import sync_from_beats, with_sync, written_measures
    rows = _lab_rows(result, 'beat')
    measures = len(written_measures(abc) or ())
    try:
        pairs = (sync_from_beats(abc, rows)
                 if measures and measures == int((result or {}).get('abc_measures') or 0) else None)
    except (TypeError, ValueError):
        pairs = None
    if not pairs:
        logger.info("[SheetSage2] partition sans repères (mesures ou temps non concordants)")
        return abc
    return with_sync(abc, pairs)
