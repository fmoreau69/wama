"""
Métriques de texte À VÉRITÉ TERRAIN — WER et CER (`WAMA_QUALITE.md` M3).

La vérité terrain est une RÉFÉRENCE produite hors du traitement (souvent corrigée à la main) :
le port `reference_result` d'une app évaluable (`app_registry.app_result_ports`). Ces métriques
disent à quelle distance une sortie se trouve de cette référence, en nombre d'opérations
d'édition rapporté à la longueur de la référence.

CE QUE CE MODULE FAIT — et ne fait pas.
  • Il compte des substitutions, suppressions et insertions, sur des mots (WER) ou des
    caractères (CER). C'est un FAIT : il ne juge ni la gravité d'une erreur ni son origine.
  • Il ne normalise QUE ce qui n'est pas de l'écoute : casse et ponctuation (décisions de
    transcription, pas désaccords sur ce qui a été dit). Il NE retire PAS les hésitations
    (« euh », « hum ») : en entretien verbatim ce sont des données (`TRANSCRIBER_CORRECTION §8.2`).
    Les retirer serait une décision de PROFIL (§8.4), à prendre là, jamais par défaut ici.
  • Une référence vide rend un taux INDÉFINI (`None`), jamais un zéro : on préfère ne rien dire
    qu'estimer à faux (même précaution que `run_outcome.correction_magnitude`).

Le découpage en mots est celui de la DIVERGENCE inter-systèmes (M1, `divergence.py`) — un seul,
pour que deux signaux de qualité ne découpent jamais différemment le même texte.

La distance d'édition est calculée par RapidFuzz (C++, MIT) : en Python pur, un entretien d'une
heure (~10 000 mots de part et d'autre) coûterait de l'ordre de 10⁸ cases.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional, Sequence


def comparable_words(text: str) -> list:
    """
    Mots comparables : minuscules, sans ponctuation, **apostrophe traitée en séparateur**.

    La ponctuation est une DÉCISION de transcription, pas un désaccord d'écoute — la compter
    ferait diverger deux systèmes qui ont entendu la même chose.

    ⚠ L'apostrophe mérite sa propre règle, et la première version (dans `divergence.py`) s'y est
    trompée : en gardant `aujourd'hui` comme UN mot, « aujourd'hui » vs « aujourd hui » sortait à
    33 % de divergence alors que les deux systèmes ont entendu la même chose (mesuré le
    2026-08-13). On la coupe donc : les deux graphies rendent `['aujourd', 'hui']`. Même effet sur
    « m'appelle » vs « m appelle », et sur les élisions que les ASR écrivent différemment.
    """
    return re.findall(r'\w+', re.sub(r"['’]", ' ', (text or '').lower()))


@dataclass(frozen=True)
class ErrorRate:
    """Le compte d'une comparaison sortie ↔ référence, et son taux."""

    unit: str                        # 'word' | 'character'
    rate: Optional[float]            # (S + D + I) / N ; None si la référence est vide
    substitutions: int
    deletions: int                   # présent dans la référence, absent de la sortie
    insertions: int                  # présent dans la sortie, absent de la référence
    reference_length: int            # N
    hypothesis_length: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    def as_dict(self) -> dict:
        return {**asdict(self), 'errors': self.errors}


def word_error_rate(reference: str, hypothesis: str) -> ErrorRate:
    """WER — taux d'erreur par MOT de `hypothesis` (la sortie) contre `reference`."""
    return _error_rate(comparable_words(reference), comparable_words(hypothesis), 'word')


def character_error_rate(reference: str, hypothesis: str) -> ErrorRate:
    """CER — taux d'erreur par CARACTÈRE, sur le même texte normalisé que le WER (mots séparés
    par une espace). Plus indulgent qu'un WER pour un mot presque juste (accord, élision)."""
    return _error_rate(' '.join(comparable_words(reference)),
                       ' '.join(comparable_words(hypothesis)), 'character')


def _error_rate(reference: Sequence, hypothesis: Sequence, unit: str) -> ErrorRate:
    from rapidfuzz.distance import Levenshtein

    counts = {'replace': 0, 'delete': 0, 'insert': 0}
    # `editops(s1, s2)` transforme s1 (la référence) en s2 (la sortie) : un `delete` retire un
    # élément de la référence (suppression), un `insert` ajoute un élément de la sortie.
    for op in Levenshtein.editops(reference, hypothesis):
        counts[op.tag] += 1
    n = len(reference)
    errors = counts['replace'] + counts['delete'] + counts['insert']
    return ErrorRate(unit=unit, rate=round(errors / n, 4) if n else None,
                     substitutions=counts['replace'], deletions=counts['delete'],
                     insertions=counts['insert'], reference_length=n,
                     hypothesis_length=len(hypothesis))
