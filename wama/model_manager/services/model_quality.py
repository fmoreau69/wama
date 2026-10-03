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

RÉVISION 2026-08-19 (décision Fabien) — les paramètres ACTIFS entrent dans l'axe qualité.
  L'hypothèse d'origine (« un MoE raisonne comme un gros modèle » → crédité de ses paramètres
  TOTAUX) a été prise en défaut par le réel : elle classait qwen3.6:35b (MoE 8/256, 1,12 Md
  actifs) au-dessus de qwen3.8 (27,3 Md DENSES), à rebours du jugement de qualité constaté.
  L'indice retient désormais les paramètres EFFECTIFS = moyenne géométrique √(totaux × actifs)
  (heuristique usuelle d'équivalent dense d'un MoE) : un dense est inchangé (actifs = totaux),
  un MoE est ramené entre ses actifs et ses totaux. Limite ASSUMÉE : sur une sparsité extrême
  (8/256), l'√ pénalise peut-être trop — c'est toujours de l'a priori, et la contrainte d'en
  tête reste entière : une mesure (interne, ou benchmark tiers confronté) devra PRIMER.
  Les actifs restent AUSSI exposés séparément (`params_active_b`) comme axe de COÛT.
"""
from __future__ import annotations

import math
import re

#: Pénalité (points d'indice) par niveau de quantification. À nombre de paramètres égal, une
#: quantification agressive dégrade la qualité — Q2 est nettement en dessous de Q8, F16 est la
#: référence non dégradée. Valeurs indicatives, ordonnées : c'est l'ORDRE qui compte, pas l'échelle.
QUANT_PENALTY = {
    'F32': 2.0, 'F16': 2.0, 'BF16': 2.0,
    'Q8': 0.0, 'Q6': -1.0, 'Q5': -2.0, 'Q4': -3.0, 'Q3': -5.0, 'Q2': -8.0,
}

#: Contexte de référence (tokens) au-delà duquel on accorde un bonus logarithmique.
REFERENCE_CONTEXT = 8192


def _quant_level(label: str) -> str:
    """'Q4_K_M' → 'Q4' · 'F16' → 'F16' · inconnu → ''."""
    m = re.match(r'^(F32|BF16|F16|Q\d)', (label or '').upper())
    return m.group(1) if m else ''


def params_in_billions(label: str) -> float | None:
    """'36.0B' → 36.0 · '8.0B' → 8.0 · '' → None. Tolère 'M' (millions)."""
    m = re.match(r'^\s*([\d.]+)\s*([BM])', (label or '').upper())
    if not m:
        return None
    val = float(m.group(1))
    return val if m.group(2) == 'B' else val / 1000.0


def apriori_quality_index(*, params_b: float | None, context_length: int | None = None,
                   quantization: str = '', params_active_b: float | None = None) -> float | None:
    """
    Indice a priori, croissant avec la capacité. None si le signal principal manque.

    Composition (chaque terme est borné pour qu'aucun ne domine seul) :
      • paramètres EFFECTIFS, en log2 — √(totaux × actifs) pour un MoE (révision 2026-08-19,
        cf. en-tête), les totaux seuls pour un dense ; un 70B n'est pas 9× meilleur qu'un 8B ;
      • fenêtre de contexte, en log2 du rapport à la référence ;
      • quantification, en pénalité additive.

    `params_active_b` absent ou ≥ `params_b` → modèle traité comme dense (inchangé).

    Retourne None plutôt que 0 quand `params_b` est inconnu : un indice absent doit se distinguer
    d'un indice nul, sinon le tri traite « inconnu » comme « mauvais ».
    """
    if not params_b or params_b <= 0:
        return None
    effective = params_b
    if params_active_b and 0 < params_active_b < params_b:
        effective = math.sqrt(params_b * params_active_b)
    score = 10.0 * math.log2(effective)
    if context_length and context_length > REFERENCE_CONTEXT:
        score += 2.0 * math.log2(context_length / REFERENCE_CONTEXT)
    score += QUANT_PENALTY.get(_quant_level(quantization), 0.0)
    return round(score, 2)


#: A PRIORI DÉCLARÉS, AVEC LEUR SOURCE (2026-10-03, décision de Fabien) — pour les modèles que
#: l'a priori STRUCTUREL ne sait pas noter (des paramètres ne disent rien d'un modèle de musique
#: face à un autre d'une autre architecture) et qu'aucun banc tiers lisible par machine ne couvre.
#: Mesuré ce jour-là : aucun des six modèles de musique ne portait de signal de qualité, le tirage
#: classait donc par VRAM — MiniMax-Music3 (13 Go) devant YuE2 (8,8 Go).
#:
#: ⚠ LES VALEURS NE SE LISENT QU'ENTRE MODÈLES D'UNE MÊME TÂCHE (le tirage borne son lot par
#: tâche) ; un modèle NON NOTÉ du lot est écarté du classement par la sélection, d'où une table
#: qui couvre la tâche ENTIÈRE ou rien. Une mesure (banc tiers confronté, mesure interne) PRIME
#: dès qu'elle existe : cette table est l'étage le plus bas de l'échelle des signaux.
#: Clé = `model_key` du catalogue ; valeur = (indice, source DATÉE).
_SONGBENCH = ("SongBench Avg ×10, WildSongBench 192 prompts — fiche m-a-p/YuE2-3B du 2026-09-12 "
              "(AUTO-ÉVALUATION des auteurs de YuE2)")
DECLARED_PRIORS = {
    # text-to-music — chansons : le banc publié les mesure sur UNE échelle.
    'huggingface:m-a-p/YuE2-3B': (67.32, f"{_SONGBENCH} : 6,7316"),
    'composer:minimax-music3': (62.83, f"{_SONGBENCH} : MiniMax Music 3 6,2830 — mesuré sur le "
                                       f"modèle d'origine, servi ici en GGUF Q8 (borne haute)"),
    'huggingface:ACE-Step/Ace-Step1.5': (60.12, f"{_SONGBENCH} : ACE-Step 1.5 6,0118"),
    # text-to-music — MusicGen : INSTRUMENTAL, hors de SongBench (qui juge des chansons). Seul
    # appui comparatif lisible : les votes humains de Music Arena (CC-BY-4.0, parquet converti,
    # lu le 2026-10-03 ; les mois 2026-04 à 07 n'étaient pas lisibles). PEU de duels : ce sont des
    # RANGS, pas des mesures — à remplacer dès qu'un banc couvre ces modèles.
    'composer:musicgen-medium': (60.12, "Music Arena 2026-03 : 22 duels contre acestep-1.5-turbo, "
                                        "8 victoires contre 6 (8 « mauvais tous deux ») — aucune "
                                        "différence mesurable : même rang qu'ACE-Step 1.5 (lu le "
                                        "2026-10-03)"),
    'composer:musicgen-melody': (60.12, "variante 1,5 B de musicgen-medium conditionnée par la "
                                        "mélodie — même rang (2026-10-03, pas de duel publié)"),
    'composer:musicgen-small': (57.62, "Music Arena 2025-09 → 2026-02 : 51 duels contre "
                                       "musicgen-medium, 5 victoires contre 10 — rang INFÉRIEUR ; "
                                       "l'écart (−2,5) est un CHOIX, non mesuré (2026-10-03)"),
}


def declared_prior(model_key: str) -> float | None:
    """L'indice a priori DÉCLARÉ pour ce modèle (`DECLARED_PRIORS`), None sinon."""
    entry = DECLARED_PRIORS.get(model_key or '')
    return entry[0] if entry else None


def active_params_b(params_b: float | None, total_experts, active_experts) -> float | None:
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
        total, active = int(total_experts or 0), int(active_experts or 0)
    except (TypeError, ValueError):
        return params_b
    if total <= 0 or active <= 0 or active >= total:
        return params_b
    return round(params_b * (active / total), 2)
