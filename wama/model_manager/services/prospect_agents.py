"""
Prospection — couche LLM multi-agents (v0), AU-DESSUS du signal déterministe `prospect_hf`.

Pour chaque candidat NOUVEAU : on récupère la carte HF (API officielle), puis N agents (via
`llm_chat`/LiteLLM — locaux Ollama gratuits, ou cloud) émettent un verdict JSON
(recommend / confiance / ajustement VRAM / rationale / risques). La « confrontation » =
**consolidation déterministe** des avis (consensus majoritaire + confiance moyenne + taux
d'accord) — pas besoin d'un juge LLM pour une moyenne. Un juge LLM reste possible en extension.

JAMAIS d'auto-application : produit un rapport ; toute adoption reste une décision admin.
La recherche web de benchmarks (au-delà de la carte HF) est une extension (besoin clé/recherche).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_AGENT_SYSTEM = (
    "Tu es un expert en modèles d'IA qui évalue l'adoption d'un modèle pour la plateforme WAMA "
    "(automatisation média, GPU RTX 4090 24GB, usage recherche). Sois prudent et factuel. "
    "Réponds en JSON valide UNIQUEMENT, rien d'autre."
)


def _hf_card_excerpt(hf_id: str, max_chars: int = 2500) -> str:
    """Extrait de la carte de modèle HF (API officielle), ou '' si indisponible."""
    try:
        from huggingface_hub import ModelCard
        return (ModelCard.load(hf_id).text or '')[:max_chars]
    except Exception as e:
        logger.debug(f"[prospect_agents] carte {hf_id} indisponible: {e}")
        return ''


def _assess_one(candidate, app, card, provider, model, timeout=120):
    """Un agent évalue un candidat → dict de verdict (ou {'agent','error'})."""
    from wama.common.utils.llm_utils import llm_chat, extract_json_from_llm
    prompt = (
        f"App WAMA cible : {app}.\n"
        f"Modèle HF candidat : {candidate['hf_id']}\n"
        f"Téléchargements : {candidate.get('downloads')} | Likes : {candidate.get('likes')} | "
        f"Tâche : {candidate.get('pipeline_tag')}\n"
        f"Carte (extrait) :\n{card or '(non disponible)'}\n\n"
        "Évalue l'adoption pour WAMA. Critères : tient sur 24GB de préférence, qualité, "
        "maturité/éprouvé, licence, effort d'intégration.\n"
        'Réponds JSON STRICT : {"recommend": true/false, "confidence": 0.0-1.0, '
        '"vram_fit": "ok|tight|no|unknown", "rationale": "1-2 phrases", "concerns": "risques/efforts"}.'
    )
    text, err = llm_chat(
        messages=[{"role": "system", "content": _AGENT_SYSTEM},
                  {"role": "user", "content": prompt}],
        provider=provider, model=model, num_predict=500, think=False, timeout=timeout,
    )
    if err or not text:
        return {'agent': f"{provider}:{model}", 'error': err or 'réponse vide'}
    data = extract_json_from_llm(text) or {}
    try:
        conf = float(data.get('confidence') or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return {
        'agent': f"{provider}:{model}",
        'recommend': bool(data.get('recommend')),
        'confidence': max(0.0, min(1.0, conf)),
        'vram_fit': str(data.get('vram_fit', 'unknown')),
        'rationale': str(data.get('rationale', ''))[:300],
        'concerns': str(data.get('concerns', ''))[:300],
    }


def assess_candidate(candidate, app, agents, timeout=120):
    """
    `agents` : liste de (provider, model). Retourne {hf_id, downloads, consensus, opinions}.
    consensus = consolidation déterministe des avis valides (None si aucun avis exploitable).
    """
    card = _hf_card_excerpt(candidate['hf_id'])
    opinions = [_assess_one(candidate, app, card, p, m, timeout) for (p, m) in agents]
    valid = [o for o in opinions if 'error' not in o]
    consensus = None
    if valid:
        recs = [o['recommend'] for o in valid]
        confs = [o['confidence'] for o in valid]
        consensus = {
            'recommend': sum(recs) > len(recs) / 2,
            'confidence_avg': round(sum(confs) / len(confs), 2),
            'agreement': round(sum(recs) / len(recs), 2),  # part d'agents « pour »
            'n_agents': len(valid),
        }
    return {
        'hf_id': candidate['hf_id'],
        'downloads': candidate.get('downloads'),
        'consensus': consensus,
        'opinions': opinions,
    }


def parse_agents(spec: str):
    """'ollama:qwen3.5:9b,xai:grok-3' → [('ollama','qwen3.5:9b'), ('xai','grok-3')]."""
    out = []
    for part in (spec or '').split(','):
        part = part.strip()
        if not part:
            continue
        provider, _, model = part.partition(':')
        out.append((provider.strip(), model.strip() or None))
    return out
