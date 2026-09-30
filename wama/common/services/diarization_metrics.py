"""
Métriques de DIARISATION à vérité terrain — cpWER et DER (`WAMA_QUALITE.md` M3, 2026-09-30).

Une transcription diarisée répond à deux questions : QU'A-T-ON dit (le WER, `text_metrics`) et
QUI l'a dit. Ce module mesure la seconde, contre une référence qui nomme ses locuteurs (SRT
`[Locuteur 012]`, VTT `<v Nom>`, tours de parole — `transcript_documents`).

DEUX MESURES, deux angles — aucune ne remplace l'autre :
  • **cpWER** (*concatenated minimum-permutation WER*, CHiME-6) : les mots de chaque locuteur sont
    mis bout à bout, de part et d'autre ; on cherche l'appariement des locuteurs qui minimise les
    erreurs (hongrois, `scipy.optimize.linear_sum_assignment`), puis on compte comme un WER. Un
    mot bien entendu mais prêté au mauvais locuteur devient une erreur. C'est la mesure de ce que
    LIT l'utilisateur d'un compte rendu : « qui a dit quoi ».
    `attribution_errors` = erreurs du cpWER − erreurs du WER des mêmes segments : la part due aux
    LOCUTEURS seuls. ⚠ Signée, jamais écrêtée : la concaténation par locuteur réordonne les mots
    des paroles qui se chevauchent, et peut rendre un cpWER légèrement INFÉRIEUR au WER — on le
    montre plutôt que de le cacher sous un zéro.
  • **DER** (*Diarization Error Rate*, NIST RT) : sur le TEMPS, (parole manquée + fausse alarme +
    confusion de locuteur) / durée de parole de la référence. Calculé par `pyannote.metrics`
    (MIT) — la définition de référence, jamais réécrite ici. Appariement optimal compris.
    ⚠ Ce que mesure le DER d'une card : les segments hypothèses sont ceux de l'ASR, étiquetés par
    le diariseur (`pyannote_diarizer.diarize`). Parole manquée et fausse alarme viennent donc
    surtout de l'ASR (segments absents, bornes larges) ; la CONFUSION est la part du diariseur.
    Les trois composantes sont rendues pour que cette lecture reste possible.
    Collier 0 et chevauchements comptés par défaut : le protocole des bancs publiés par pyannote.

Une mesure qui n'a pas de sens rend None — jamais un zéro inventé : référence sans locuteurs,
sortie non diarisée (aucun locuteur nommé), DER sans temps de part ou d'autre.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

from wama.common.services.text_metrics import comparable_words

#: Version du protocole des mesures de diarisation. La changer change l'ÉCHELLE.
#: `diar_v1` : mots normalisés comme `text_v2` ; DER collier 0, chevauchements comptés.
DIARIZATION_PROTOCOL = 'diar_v1'

#: Locuteur d'un segment que le diariseur n'a pas attribué : un locuteur à part entière pour
#: le cpWER (ses mots ne s'apparieront à personne de juste), jamais écarté en silence.
UNATTRIBUTED = '?'


def is_diarized(segments: Optional[Sequence[dict]]) -> bool:
    """Au moins un segment porte un locuteur nommé — sinon il n'y a pas de diarisation à mesurer."""
    return any(isinstance(s, dict) and (s.get('speaker_id') or '').strip() for s in segments or ())


def _in_time_order(segments: Sequence[dict]) -> List[dict]:
    """Segments dans l'ordre du temps ; un segment sans temps garde sa place relative."""
    usable = [s for s in segments if isinstance(s, dict)]
    return sorted(usable, key=lambda s: (s.get('start_time') is None, s.get('start_time') or 0.0))


def _words_by_speaker(segments: Sequence[dict], language: Optional[str]) -> Dict[str, list]:
    words: Dict[str, list] = {}
    for seg in _in_time_order(segments):
        speaker = (seg.get('speaker_id') or '').strip() or UNATTRIBUTED
        words.setdefault(speaker, []).extend(comparable_words(seg.get('text') or '', language))
    return words


@dataclass(frozen=True)
class SpeakerAttributedRate:
    """Le compte d'un cpWER : un WER où le locuteur fait partie du mot."""

    unit: str                        # 'word'
    rate: Optional[float]            # (S + D + I) / N après appariement optimal ; None si N = 0
    substitutions: int
    deletions: int
    insertions: int
    reference_length: int            # N — mots de la référence
    hypothesis_length: int
    #: WER des MÊMES segments, locuteurs ignorés — le point de comparaison.
    word_errors: int
    reference_speakers: int
    hypothesis_speakers: int
    #: locuteur de référence → locuteur de sortie retenu ('' = aucun : ses mots sont tous manqués).
    mapping: Dict[str, str] = field(default_factory=dict)

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def attribution_errors(self) -> int:
        """Erreurs dues aux LOCUTEURS seuls (signé — voir l'en-tête du module)."""
        return self.errors - self.word_errors

    def as_dict(self) -> dict:
        return {**asdict(self), 'errors': self.errors,
                'attribution_errors': self.attribution_errors}


def cp_word_error_rate(reference_segments: Sequence[dict], hypothesis_segments: Sequence[dict],
                       language: Optional[str] = None) -> Optional[SpeakerAttributedRate]:
    """cpWER de `hypothesis_segments` contre `reference_segments` (dicts `speaker_id`, `text`,
    `start_time`). None si l'un des deux côtés ne nomme aucun locuteur."""
    if not is_diarized(reference_segments) or not is_diarized(hypothesis_segments):
        return None
    import numpy as np
    from rapidfuzz.distance import Levenshtein
    from scipy.optimize import linear_sum_assignment

    reference = _words_by_speaker(reference_segments, language)
    hypothesis = _words_by_speaker(hypothesis_segments, language)
    ref_names, hyp_names = list(reference), list(hypothesis)
    size = max(len(ref_names), len(hyp_names))
    # Matrice carrée : un locuteur sans vis-à-vis s'apparie à un locuteur VIDE (tous ses mots
    # sont alors des suppressions, ou des insertions de l'autre côté).
    ref_words = [reference[n] for n in ref_names] + [[]] * (size - len(ref_names))
    hyp_words = [hypothesis[n] for n in hyp_names] + [[]] * (size - len(hyp_names))
    cost = np.array([[Levenshtein.distance(r, h) for h in hyp_words] for r in ref_words])
    rows, cols = linear_sum_assignment(cost)

    counts = {'replace': 0, 'delete': 0, 'insert': 0}
    mapping = {}
    for i, j in zip(rows, cols):
        for op in Levenshtein.editops(ref_words[i], hyp_words[j]):
            counts[op.tag] += 1
        if i < len(ref_names):
            mapping[ref_names[i]] = hyp_names[j] if j < len(hyp_names) else ''

    all_reference = [w for s in _in_time_order(reference_segments)
                     for w in comparable_words(s.get('text') or '', language)]
    all_hypothesis = [w for s in _in_time_order(hypothesis_segments)
                      for w in comparable_words(s.get('text') or '', language)]
    n = len(all_reference)
    errors = counts['replace'] + counts['delete'] + counts['insert']
    return SpeakerAttributedRate(
        unit='word', rate=round(errors / n, 4) if n else None,
        substitutions=counts['replace'], deletions=counts['delete'], insertions=counts['insert'],
        reference_length=n, hypothesis_length=len(all_hypothesis),
        word_errors=Levenshtein.distance(all_reference, all_hypothesis),
        reference_speakers=len(ref_names), hypothesis_speakers=len(hyp_names), mapping=mapping)


@dataclass(frozen=True)
class DiarizationRate:
    """Le compte d'un DER, en SECONDES."""

    unit: str                        # 'second'
    rate: Optional[float]            # (manquée + fausse alarme + confusion) / parole de référence
    missed: float
    false_alarm: float
    confusion: float
    reference_length: float          # secondes de parole de la référence
    collar: float

    @property
    def errors(self) -> float:
        return round(self.missed + self.false_alarm + self.confusion, 3)

    def as_dict(self) -> dict:
        return {**asdict(self), 'errors': self.errors}


def _annotation(segments: Sequence[dict]):
    from pyannote.core import Annotation, Segment
    annotation = Annotation()
    for track, seg in enumerate(segments):
        start, end = seg.get('start_time'), seg.get('end_time')
        if end > start:
            speaker = (seg.get('speaker_id') or '').strip() or UNATTRIBUTED
            annotation[Segment(float(start), float(end)), track] = speaker
    return annotation


def _timed(segments: Sequence[dict]) -> bool:
    return bool(segments) and all(
        isinstance(s, dict) and isinstance(s.get('start_time'), (int, float))
        and isinstance(s.get('end_time'), (int, float)) for s in segments)


def diarization_error_rate(reference_segments: Sequence[dict], hypothesis_segments: Sequence[dict],
                           language: Optional[str] = None,
                           collar: float = 0.0) -> Optional[DiarizationRate]:
    """DER de `hypothesis_segments` contre `reference_segments`, par `pyannote.metrics`.

    None si l'un des côtés ne nomme aucun locuteur ou n'est pas entièrement horodaté.
    `language` est accepté pour la signature commune des métriques ; le DER ne lit pas les mots.
    """
    if not is_diarized(reference_segments) or not is_diarized(hypothesis_segments):
        return None
    if not _timed(reference_segments) or not _timed(hypothesis_segments):
        return None
    from pyannote.metrics.diarization import DiarizationErrorRate

    detail = DiarizationErrorRate(collar=collar, skip_overlap=False)(
        _annotation(reference_segments), _annotation(hypothesis_segments), detailed=True)
    total = float(detail.get('total') or 0.0)
    missed = float(detail.get('missed detection') or 0.0)
    false_alarm = float(detail.get('false alarm') or 0.0)
    confusion = float(detail.get('confusion') or 0.0)
    return DiarizationRate(
        unit='second',
        rate=round((missed + false_alarm + confusion) / total, 4) if total else None,
        missed=round(missed, 3), false_alarm=round(false_alarm, 3),
        confusion=round(confusion, 3), reference_length=round(total, 3), collar=collar)
