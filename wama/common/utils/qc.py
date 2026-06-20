"""
Contrôle qualité (QC) générique — primitive réutilisable, indépendante des apps.

Un validateur LLM **indépendant du générateur** note la qualité d'une sortie par rapport à son
entrée (score 0-1) et signale les cas à revoir. Les apps l'appellent après génération.

GARDE-FOUS (ROADMAP §16.5) — ne pas contourner :
1. **Validateur INDÉPENDANT du générateur** : passer un `validator_*` d'une autre famille que le
   modèle qui a produit la sortie (sinon validation circulaire — un modèle corrige sa copie).
2. **Score RELATIF** : signal de régression (N vs N+1) / détection d'outliers → revue humaine.
   JAMAIS un gate absolu d'acceptation automatique.
3. **JAMAIS le seul filet RGPD** : pour l'anonymisation, le déterministe + l'audit humain priment ;
   ce QC = alerte secondaire qui ESCALADE vers l'humain, jamais la validation finale.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_QC_SYSTEM = (
    "Tu es un évaluateur qualité rigoureux et indépendant. Tu notes une sortie produite par UN "
    "AUTRE système, par rapport à la demande. Sois critique et factuel. JSON valide UNIQUEMENT."
)


def assess_output_quality(task: str, input_summary: str, output: str,
                          validator_provider: str = 'ollama', validator_model: str | None = None,
                          review_threshold: float = 0.6, timeout: int = 120):
    """
    Note la qualité d'une `output` (texte) pour une `task`, via un validateur LLM indépendant.

    Retourne {'quality_score': 0..1, 'issues': str, 'needs_human_review': bool,
              'validator': str} ou {'error': str}.
    `needs_human_review` = score < seuil OU problème signalé → ESCALADE humaine (pas un rejet auto).
    """
    from wama.common.utils.llm_utils import llm_chat, extract_json_from_llm

    out = (output or '').strip()
    if not out:
        return {'quality_score': 0.0, 'issues': 'sortie vide', 'needs_human_review': True,
                'validator': f"{validator_provider}:{validator_model}"}

    prompt = (
        f"Tâche demandée : {task}\n"
        f"Entrée (résumé) : {input_summary}\n"
        f"Sortie produite à évaluer :\n\"\"\"\n{out[:4000]}\n\"\"\"\n\n"
        "Évalue la qualité de la sortie par rapport à la demande (pertinence, cohérence, "
        "complétude, absence d'artefacts/hallucinations).\n"
        'Réponds JSON STRICT : {"quality_score": 0.0-1.0, "issues": "problèmes notables ou \'aucun\'", '
        '"flag": true/false}.  flag=true si un problème mérite une revue humaine.'
    )
    text, err = llm_chat(
        messages=[{"role": "system", "content": _QC_SYSTEM},
                  {"role": "user", "content": prompt}],
        provider=validator_provider, model=validator_model,
        num_predict=400, think=False, timeout=timeout,
    )
    if err or not text:
        return {'error': err or 'réponse vide', 'validator': f"{validator_provider}:{validator_model}"}

    data = extract_json_from_llm(text) or {}
    try:
        score = max(0.0, min(1.0, float(data.get('quality_score') or 0)))
    except (TypeError, ValueError):
        score = 0.0
    issues = str(data.get('issues', ''))[:400]
    flagged = bool(data.get('flag')) or score < review_threshold
    return {
        'quality_score': round(score, 2),
        'issues': issues,
        'needs_human_review': flagged,
        'validator': f"{validator_provider}:{validator_model}",
    }
