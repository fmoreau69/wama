"""
Indice de qualité A PRIORI d'un modèle — pour choisir autrement que « le plus gros qui tient ».

POURQUOI. `select_model()` classait les candidats par `vram_gb` : son helper s'appelle encore
`_best_by_vram` et son docstring assimile « le plus gros » à « la meilleure qualité ». C'est faux,
et un cas réel du catalogue le montre — `qwen3.6:35b` est un MoE qui active **8 experts sur 256** :

    qualité         ≈ 36 Md de paramètres      (il raisonne comme un gros modèle)
    coût de calcul  ≈ ~3 Md actifs             (il répond comme un petit)
    VRAM            = 22 Go                    (tous les experts doivent résider)

Trois grandeurs distinctes que la taille seule écrase en une. Trier par VRAM se trompe sur deux
axes sur trois, et c'est ce qui fait qu'« un modèle plus petit est parfois meilleur ».

CE QUE CET INDICE EST — et n'est pas.
  • A PRIORI : dérivé de propriétés STRUCTURELLES déclarées par le fournisseur (nombre de
    paramètres, fenêtre de contexte, quantification). Aucun benchmark n'est scrapé, aucune
    réputation n'est inventée.
  • RELATIF au catalogue : il sert à ORDONNER des candidats entre eux, pas à affirmer qu'un
    modèle « vaut 62/100 » dans l'absolu.
  • REMPLAÇABLE : dès qu'une mesure interne existera, elle devra primer. Le champ
    `AIModel.quality_index` accepte donc une valeur posée à la main.

⚠ CONTRAINTE HÉRITÉE DE `common/utils/qc.py` (garde-fou n°2, ROADMAP §16.5) : le score du QC est
un signal **relatif** de régression, à escalader vers l'humain — « JAMAIS un gate absolu
d'acceptation automatique ». Brancher un jour le QC ici ne devra donc pas transformer une mesure
relative en classement absolu : ce sera un signal d'ordre parmi d'autres, pas un verdict.

CE QUI N'EST VOLONTAIREMENT PAS DANS L'INDICE.
  • La récence de famille (`qwen3.6 > qwen3.5`). Elle n'a de sens qu'À L'INTÉRIEUR d'une famille :
    comparer « 3.6 » à « gemma 4 » n'a aucun sens, et un bonus global classerait gemma4 au-dessus
    de qwen3.6 sur un simple numéro. C'est la PROSPECTION qui porte ce signal (elle propose le
    successeur), pas le classement de l'installé.
  • Les paramètres ACTIFS. Ils mesurent un COÛT, pas une qualité — ils sont exposés séparément
    (`params_active_b`) pour qu'un appelant sensible à la latence puisse en tenir compte sans
    polluer l'axe qualité.
"""
from __future__ import annotations

import math
import re

#: Pénalité (points d'indice) par niveau de quantification. À nombre de paramètres égal, une
#: quantification agressive dégrade la qualité — Q2 est nettement en dessous de Q8, F16 est la
#: référence non dégradée. Valeurs indicatives, ordonnées : c'est l'ORDRE qui compte, pas l'échelle.
PENALITE_QUANT = {
    'F32': 2.0, 'F16': 2.0, 'BF16': 2.0,
    'Q8': 0.0, 'Q6': -1.0, 'Q5': -2.0, 'Q4': -3.0, 'Q3': -5.0, 'Q2': -8.0,
}

#: Contexte de référence (tokens) au-delà duquel on accorde un bonus logarithmique.
CONTEXTE_REFERENCE = 8192


def _niveau_quant(libelle: str) -> str:
    """'Q4_K_M' → 'Q4' · 'F16' → 'F16' · inconnu → ''."""
    m = re.match(r'^(F32|BF16|F16|Q\d)', (libelle or '').upper())
    return m.group(1) if m else ''


def params_en_milliards(libelle: str) -> float | None:
    """'36.0B' → 36.0 · '8.0B' → 8.0 · '' → None. Tolère 'M' (millions)."""
    m = re.match(r'^\s*([\d.]+)\s*([BM])', (libelle or '').upper())
    if not m:
        return None
    val = float(m.group(1))
    return val if m.group(2) == 'B' else val / 1000.0


def indice_qualite(*, params_b: float | None, context_length: int | None = None,
                   quantization: str = '') -> float | None:
    """
    Indice a priori, croissant avec la capacité. None si le signal principal manque.

    Composition (chaque terme est borné pour qu'aucun ne domine seul) :
      • paramètres TOTAUX, en log2 — un 70B n'est pas 9× meilleur qu'un 8B ;
      • fenêtre de contexte, en log2 du rapport à la référence ;
      • quantification, en pénalité additive.

    Retourne None plutôt que 0 quand `params_b` est inconnu : un indice absent doit se distinguer
    d'un indice nul, sinon le tri traite « inconnu » comme « mauvais ».
    """
    if not params_b or params_b <= 0:
        return None
    score = 10.0 * math.log2(params_b)
    if context_length and context_length > CONTEXTE_REFERENCE:
        score += 2.0 * math.log2(context_length / CONTEXTE_REFERENCE)
    score += PENALITE_QUANT.get(_niveau_quant(quantization), 0.0)
    return round(score, 2)


def params_actifs_b(params_b: float | None, experts_total, experts_actifs) -> float | None:
    """
    Paramètres réellement activés par jeton, en milliards — axe de COÛT, pas de qualité.

    Pour un MoE, seule une fraction des experts est routée par jeton. L'approximation retenue
    borne le résultat par le bas : les couches d'attention restent denses, donc le coût réel est
    supérieur au produit brut. Mieux vaut une borne basse explicite qu'un chiffre faussement précis.
    Dense (pas d'experts déclarés) → `params_b` inchangé.
    """
    if not params_b:
        return None
    try:
        total, actifs = int(experts_total or 0), int(experts_actifs or 0)
    except (TypeError, ValueError):
        return params_b
    if total <= 0 or actifs <= 0 or actifs >= total:
        return params_b
    return round(params_b * (actifs / total), 2)
