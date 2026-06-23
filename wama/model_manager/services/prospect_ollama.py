"""
Prospection Ollama-first (déterministe) — peuple la catégorie « Proposés par IA ».

Étape 1 du chantier prospection : on teste la CHAÎNE (prospect → cards candidates →
install) sur Ollama (le plus simple). La confrontation multi-agents / cloud (grok, gemini
free via la passerelle LiteLLM `llm_chat`) viendra enrichir la confiance dans une étape
ultérieure ; ici la confiance est heuristique et l'installation = `ollama pull` (simple).

Deux sources de candidats, écrits comme `AIModel(is_proposed=True)` (model_key préfixé
`proposed:`), donc réutilisant card + inspecteur + filtres sans table séparée :
  - kind='update' : modèles Ollama installés trop anciens (via update_checker).
  - kind='new'    : petite liste curated de modèles Ollama recommandés non installés (seed).

Idempotent : ré-exécution met à jour les candidats existants et purge les obsolètes.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PROPOSED_PREFIX = "proposed:"

# Seed curated minimal (modèles Ollama utiles à WAMA, rôle describer/LLM). Volontairement
# court : la découverte large viendra via agents/registre Ollama. Sert à tester la chaîne.
CURATED_OLLAMA = [
    {
        'name': 'qwen2.5:7b',
        'type': 'llm',
        'confidence': 0.82,
        'reason': "LLM polyvalent récent, bon rapport qualité/VRAM pour le rôle describer.",
    },
    {
        'name': 'gemma2:9b',
        'type': 'llm',
        'confidence': 0.78,
        'reason': "Alternative concurrente (Google) au describer actuel, multilingue.",
    },
]


def _confidence_from_age(age_days) -> float:
    """Plus le modèle installé est ancien, plus on est confiant qu'une MAJ s'impose."""
    try:
        age = float(age_days or 0)
    except (TypeError, ValueError):
        age = 0.0
    return round(min(0.5 + age / 365.0, 0.95), 2)


def prospect_ollama(age_days_threshold: int = 120, include_new: bool = True) -> dict:
    """Lance la prospection Ollama et persiste les candidats. Retourne un résumé."""
    from wama.model_manager.models import AIModel
    from .update_checker import check_updates

    created = updated = 0
    seen = set()

    # ── 1) MAJ des modèles Ollama installés anciens ──────────────────────────
    try:
        report = check_updates(age_days_threshold=age_days_threshold, do_hf=False)
        ollama_review = report.get('ollama_review', [])
    except Exception as exc:  # pragma: no cover - dépend d'Ollama up
        logger.warning("[prospect_ollama] check_updates indisponible: %s", exc)
        ollama_review = []

    for r in ollama_review:
        origin = r.get('model_key')
        src = AIModel.objects.filter(model_key=origin).first() if origin else None
        if not src:
            continue
        cand_key = PROPOSED_PREFIX + origin
        seen.add(cand_key)
        age = r.get('age_days')
        _, was_created = AIModel.objects.update_or_create(
            model_key=cand_key,
            defaults=dict(
                name=src.name,
                model_type=src.model_type,
                source='ollama',
                description=f"Mise à jour suggérée — {r.get('reason', 'version locale ancienne')}.",
                is_proposed=True,
                proposal_kind='update',
                confidence=_confidence_from_age(age),
                update_complexity='simple',  # `ollama pull` remplace en place
                is_downloaded=False,
                is_loaded=False,
                is_available=False,
                hf_id='',
                extra_info={'prospect': {
                    'kind': 'update', 'origin_key': origin,
                    'reason': r.get('reason', ''), 'age_days': age,
                }},
            ),
        )
        created += int(was_created)
        updated += int(not was_created)

    # ── 2) Nouveaux candidats curated (non installés) ────────────────────────
    if include_new:
        installed = set(
            AIModel.objects.filter(source='ollama', is_proposed=False)
            .values_list('model_key', flat=True)
        )
        for c in CURATED_OLLAMA:
            real_key = f"ollama:{c['name']}"
            if real_key in installed:
                continue
            cand_key = PROPOSED_PREFIX + real_key
            seen.add(cand_key)
            _, was_created = AIModel.objects.update_or_create(
                model_key=cand_key,
                defaults=dict(
                    name=c['name'],
                    model_type=c.get('type', 'llm'),
                    source='ollama',
                    description=c.get('reason', ''),
                    is_proposed=True,
                    proposal_kind='new',
                    confidence=c.get('confidence'),
                    update_complexity='simple',
                    is_downloaded=False,
                    is_loaded=False,
                    is_available=False,
                    hf_id='',
                    extra_info={'prospect': {
                        'kind': 'new', 'name': c['name'], 'reason': c.get('reason', ''),
                    }},
                ),
            )
            created += int(was_created)
            updated += int(not was_created)

    # ── 3) Purge des candidats obsolètes ─────────────────────────────────────
    stale = AIModel.objects.filter(is_proposed=True, source='ollama').exclude(model_key__in=seen)
    removed = stale.count()
    stale.delete()

    summary = {'created': created, 'updated': updated, 'removed': removed, 'total': len(seen)}
    logger.info("[prospect_ollama] %s", summary)
    return summary
