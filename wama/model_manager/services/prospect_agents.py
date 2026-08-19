"""
Prospection — couche LLM multi-agents (v0), AU-DESSUS des signaux déterministes.

Deux entrées, un même juge :
  • `assess_candidate` (HF)      — candidats `prospect_hf`, contexte = carte de modèle HF.
    Consommée par la CLI `assess_models` (rapport dry-run, rien n'est persisté).
  • `assess_proposed`            — candidats `kind='new'` de la chaîne UI (Ollama ET
    HuggingFace/génération), contexte = registre/carte HF + installés comparables.
    PERSISTE le verdict dans la ligne candidate : `AIModel.confidence` +
    `extra_info['prospect']['assess']` — la card et l'inspecteur les affichent déjà.
    Comble la SUITE (a) de la prospection (2026-06-24) : les `new` restaient à
    `confidence=None`, l'heuristique d'âge ne valant que pour les `update`.

Pour chaque candidat : N agents (via `llm_chat`/LiteLLM — locaux Ollama gratuits, ou cloud)
émettent un verdict JSON (recommend / confiance / ajustement VRAM / rationale / risques).
La « confrontation » = **consolidation déterministe** des avis (consensus majoritaire +
confiance moyenne + taux d'accord) — pas besoin d'un juge LLM pour une moyenne.

JAMAIS d'auto-application : le verdict informe la card ; toute adoption reste une décision admin.
La recherche web de benchmarks (au-delà des cartes) est une extension (besoin clé/recherche).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_AGENT_SYSTEM = (
    "Tu es un expert en modèles d'IA qui évalue l'adoption d'un modèle pour la plateforme WAMA "
    "(automatisation média, GPU RTX 4090 24GB, usage recherche). Sois prudent et factuel. "
    "Réponds en JSON valide UNIQUEMENT, rien d'autre."
)

#: Réglage par défaut des agents de la chaîne UI (surchargable : `settings.PROSPECT_ASSESS_AGENTS`).
#: `'ollama'` SANS nom de modèle : `llm_chat(model=None)` résout via `modele_par_defaut()`
#: (catalogue → VRAM libre → repli Ollama) — un nom figé ici pourrirait au premier
#: remplacement par la prospection (leçon qwen3.5→qwen3.6, cf. llm_utils).
#: Local d'abord (gratuit) ; ajouter un agent cloud = ajouter `,google:gemini-2.0-flash` (clé requise).
_AGENTS_DEFAUT = 'ollama'


def _hf_card_excerpt(hf_id: str, max_chars: int = 2500) -> str:
    """Extrait de la carte de modèle HF (API officielle), ou '' si indisponible."""
    try:
        from huggingface_hub import ModelCard
        return (ModelCard.load(hf_id).text or '')[:max_chars]
    except Exception as e:
        logger.debug(f"[prospect_agents] carte {hf_id} indisponible: {e}")
        return ''


def _juger(contexte: str, provider, model, timeout=120):
    """Un agent rend un verdict JSON sur `contexte` → dict d'avis (ou {'agent','error'}).
    `model=None` = résolution par le catalogue (`llm_chat` → `modele_par_defaut`)."""
    from wama.common.utils.llm_utils import llm_chat, extract_json_from_llm
    etiquette = f"{provider}:{model}" if model else f"{provider} (catalogue)"
    prompt = (
        contexte + "\n\n"
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
        return {'agent': etiquette, 'error': err or 'réponse vide'}
    data = extract_json_from_llm(text) or {}
    try:
        conf = float(data.get('confidence') or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return {
        'agent': etiquette,
        'recommend': bool(data.get('recommend')),
        'confidence': max(0.0, min(1.0, conf)),
        'vram_fit': str(data.get('vram_fit', 'unknown')),
        'rationale': str(data.get('rationale', ''))[:300],
        'concerns': str(data.get('concerns', ''))[:300],
    }


def _consolider(opinions):
    """Consolidation déterministe des avis valides → consensus (None si aucun exploitable)."""
    valid = [o for o in opinions if 'error' not in o]
    if not valid:
        return None
    recs = [o['recommend'] for o in valid]
    confs = [o['confidence'] for o in valid]
    return {
        'recommend': sum(recs) > len(recs) / 2,
        'confidence_avg': round(sum(confs) / len(confs), 2),
        'agreement': round(sum(recs) / len(recs), 2),  # part d'agents « pour »
        'n_agents': len(valid),
    }


def _assess_one(candidate, app, card, provider, model, timeout=120):
    """Un agent évalue un candidat HF → dict de verdict (ou {'agent','error'})."""
    contexte = (
        f"App WAMA cible : {app}.\n"
        f"Modèle HF candidat : {candidate['hf_id']}\n"
        f"Téléchargements : {candidate.get('downloads')} | Likes : {candidate.get('likes')} | "
        f"Tâche : {candidate.get('pipeline_tag')}\n"
        f"Carte (extrait) :\n{card or '(non disponible)'}"
    )
    return _juger(contexte, provider, model, timeout=timeout)


def assess_candidate(candidate, app, agents, timeout=120):
    """
    `agents` : liste de (provider, model). Retourne {hf_id, downloads, consensus, opinions}.
    consensus = consolidation déterministe des avis valides (None si aucun avis exploitable).
    """
    card = _hf_card_excerpt(candidate['hf_id'])
    opinions = [_assess_one(candidate, app, card, p, m, timeout) for (p, m) in agents]
    return {
        'hf_id': candidate['hf_id'],
        'downloads': candidate.get('downloads'),
        'consensus': _consolider(opinions),
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


# ── Chaîne UI : candidats Ollama `new` ──────────────────────────────────────────

def _contexte_ollama(cand) -> str:
    """
    Contexte FACTUEL d'un candidat Ollama — uniquement ce que le registre et le catalogue
    savent (pas de carte HF ici). Les installés comparables donnent au juge le référentiel
    « surpasse-t-il ce qu'on a ? » — c'est ce qui manquait pour envisager un remplacement.
    """
    from wama.model_manager.models import AIModel
    from . import ollama_registry
    p = (cand.extra_info or {}).get('prospect', {})
    nom, _, tag = cand.name.partition(':')
    try:
        taille = ollama_registry.taille_go(nom, tag or 'latest')
    except Exception:
        taille = None
    lignes = _referentiel(cand.model_type)
    return (
        f"Modèle candidat de la bibliothèque Ollama : {cand.name}\n"
        f"Rôle WAMA visé : {p.get('role') or cand.model_type} — {p.get('reason', '')}\n"
        f"Taille estimée : {taille if taille is not None else '?'} Go\n"
        + _ligne_benchmark(cand)
        + f"Modèles déjà installés pour ce type (référentiel à surpasser) :\n{lignes}"
    )


def _referentiel(model_type: str) -> str:
    """Référentiel installé d'un type, en lignes lisibles (brique `meilleurs_installes`).
    Le benchmark TIERS confronté (étage 2, `sync_benchmarks`) prime sur l'a priori quand
    il existe — c'est la mesure qui a corrigé « qwen3.6 devant qwen3.8 » le 19/08."""
    from wama.model_manager.models import AIModel
    lignes = []
    for m in AIModel.meilleurs_installes(model_type, limit=5):
        bench = (f", benchmark tiers {m.benchmark_index}"
                 if m.benchmark_index is not None else "")
        lignes.append(f"  - {m.name} (indice a priori {m.quality_index}{bench}, "
                      f"VRAM {m.vram_gb} Go)")
    return "\n".join(lignes) or "  (aucun)"


def _ligne_benchmark(cand) -> str:
    """Ligne « benchmark tiers » du candidat lui-même, si `sync_benchmarks` l'a apparié
    (les lignes `proposed:` sont incluses dans le sync — critère AVANT installation)."""
    if cand.benchmark_index is None:
        return ""
    meta = cand.benchmark_meta or {}
    return (f"Benchmark tiers confronté : {cand.benchmark_index}"
            f" ({meta.get('source', 'source inconnue')})\n")


def _vram_agents(agents) -> float:
    """
    VRAM (Go) à déclarer au gouverneur pour une passe : le PLUS GOURMAND des agents
    locaux (Ollama ne garde qu'un modèle chargé en NUM_PARALLEL=1 ; les agents cloud
    ne coûtent rien ici). Agent sans nom (résolution catalogue) → on résout MAINTENANT
    pour réserver la vraie empreinte, pas une supposition.
    """
    from wama.model_manager.models import AIModel
    besoin = 0.0
    for provider, model in agents:
        if provider != 'ollama':
            continue
        nom = model
        if not nom:
            try:
                from wama.common.utils.llm_utils import modele_par_defaut
                nom = modele_par_defaut()
            except Exception:
                nom = ''
        m = AIModel.objects.filter(model_key=f"ollama:{nom}").first() if nom else None
        besoin = max(besoin, float((m and m.vram_gb) or 8.0))   # 8 Go = repli prudent
    return besoin or 8.0


def _contexte_hf(cand) -> str:
    """
    Contexte d'un candidat HuggingFace (prospection génération) : la CARTE de modèle HF
    (même source factuelle que la voie CLI `assess_models`) + popularité + référentiel.
    """
    p = (cand.extra_info or {}).get('prospect', {})
    carte = _hf_card_excerpt(cand.hf_id)
    return (
        f"Modèle HF candidat : {cand.hf_id}\n"
        f"Rôle WAMA visé : {p.get('role') or cand.model_type} — {p.get('reason', '')}\n"
        f"Téléchargements : {p.get('downloads')} | Likes : {p.get('likes')} | "
        f"Poids : {cand.disk_gb or '?'} Go\n"
        + _ligne_benchmark(cand)
        + f"Modèles déjà installés pour ce type (référentiel à surpasser) :\n"
          f"{_referentiel(cand.model_type)}\n"
        f"Carte (extrait) :\n{carte or '(non disponible)'}"
    )


def assess_proposed(max_assess: int = 10, agents=None, timeout: int = 120,
                    progress=None) -> dict:
    """
    Confronte les candidats `kind='new'` SANS confiance (Ollama ET HuggingFace) à N agents
    LLM et PERSISTE :
      - `AIModel.confidence` = probabilité que l'adoption vaille le coup, consolidée des avis
        (un avis « contre » à confiance c compte pour 1−c — un « non » sûr tire vers 0) ;
      - `extra_info['prospect']['assess']` = consensus + avis détaillés (badge card + inspecteur).

    Le contexte factuel dépend de la source : registre + référentiel installé (Ollama),
    carte de modèle HF + popularité + référentiel (HuggingFace — même source que la CLI).

    Idempotent et incrémental : ne traite que `confidence IS NULL`, `max_assess` par passe
    (les suivants partent à la passe d'après). `progress(dict)` optionnel pour publication.
    """
    from django.conf import settings
    from wama.model_manager.models import AIModel

    agents = agents or parse_agents(
        getattr(settings, 'PROSPECT_ASSESS_AGENTS', _AGENTS_DEFAUT))

    # ── GOUVERNEUR DE RESSOURCES (obligatoire depuis le 2026-08-19) ──────────────
    # La charge tourne dans l'OLLAMA HÔTE — même GPU physique, mais INVISIBLE des process
    # WAMA : sans déclaration, le gouverneur croit la VRAM libre et laisse une autre tâche
    # GPU s'empiler (scénario des kernel panics du 29/07 ; et la passe enchaînée hors
    # gouverneur a fait tomber l'hôte le 19/08). Même motif que MuseTalk/CodeFormer :
    # garde `effective_free_gb` PUIS `vram_reservation` pour la durée de la passe.
    import os as _os

    from wama.common.services.resource_governor import (effective_free_gb,
                                                        vram_reservation)
    besoin_gb = _vram_agents(agents)
    libre = effective_free_gb()
    if libre < besoin_gb:
        resume = {'assessed': 0, 'deferred': True, 'free_gb': round(libre, 1),
                  'needed_gb': besoin_gb}
        logger.info("[prospect_agents] passe REPORTÉE : VRAM effective %.1f Go < besoin "
                    "%.1f Go (les candidats restent sans confiance, repasse plus tard)",
                    libre, besoin_gb)
        return resume

    file_attente = AIModel.objects.filter(
        is_proposed=True, source__in=('ollama', 'huggingface'),
        proposal_kind='new', confidence__isnull=True,
    ).order_by('name')
    cands = list(file_attente[:max_assess])

    evalues, sans_avis = 0, 0
    with vram_reservation(f"model_manager.assess:{_os.getpid()}", besoin_gb):
        for i, cand in enumerate(cands):
            if progress:
                progress({'current': cand.name, 'done': i, 'total': len(cands)})
            contexte = (_contexte_hf(cand) if cand.source == 'huggingface'
                        else _contexte_ollama(cand))
            opinions = [_juger(contexte, p, m, timeout=timeout)
                        for (p, m) in agents]
            consensus = _consolider(opinions)
            if consensus is None:
                sans_avis += 1     # agents injoignables : on laisse `None`, repassera
                continue
            valid = [o for o in opinions if 'error' not in o]
            worth = sum((o['confidence'] if o['recommend'] else 1.0 - o['confidence'])
                        for o in valid) / len(valid)
            cand.confidence = round(worth, 2)
            info = dict(cand.extra_info or {})
            prospect = dict(info.get('prospect') or {})
            prospect['assess'] = {'consensus': consensus, 'opinions': opinions}
            info['prospect'] = prospect
            cand.extra_info = info
            cand.save(update_fields=['confidence', 'extra_info'])
            evalues += 1
            logger.info("[prospect_agents] %s → confiance %.2f (recommandé=%s, %d agent(s))",
                        cand.name, cand.confidence, consensus['recommend'],
                        consensus['n_agents'])

    restants = AIModel.objects.filter(
        is_proposed=True, source__in=('ollama', 'huggingface'),
        proposal_kind='new', confidence__isnull=True,
    ).count()
    resume = {'assessed': evalues, 'no_verdict': sans_avis, 'remaining': restants}
    logger.info("[prospect_agents] passe terminée : %s", resume)
    return resume
