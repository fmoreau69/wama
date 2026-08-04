"""
Prospection Ollama (déterministe) — peuple la catégorie « Proposés par IA ».

Candidats écrits comme `AIModel(is_proposed=True)` (model_key préfixé `proposed:`), donc
réutilisant card + inspecteur + filtres sans table séparée. Trois sources :

  • `update`  — modèle installé ancien SANS successeur identifié (signal d'âge seul) ;
  • `update`  — **successeur de famille** : `qwen3.5:9b` → `qwen3.6:27b`, cible NOMMÉE et dont
                l'existence est vérifiée au manifeste du registre ;
  • `new`     — modèle de la bibliothèque couvrant un RÔLE WAMA, non installé.

── Ce que cette version corrige (2026-08-04) ────────────────────────────────────
1. Le seed `CURATED_OLLAMA` codé en dur (qwen2.5:7b, gemma2:9b) est SUPPRIMÉ. Figé à la création
   (2026-06-24) et jamais rafraîchi, il proposait fin 2026 des modèles plus anciens que ceux
   déjà installés — une régression présentée comme une amélioration. Remplacé par une découverte
   réelle du registre (`ollama_registry`).
2. Un candidat `update` désignait un problème (« installé il y a 151 j ») sans désigner de
   solution. Il porte désormais sa CIBLE quand une famille supérieure existe.
3. **La purge n'est plus inconditionnelle.** Avant, une simple indisponibilité d'Ollama ou du
   registre vidait `ollama_review`, et le `delete()` effaçait des candidats valides — ne laissant
   que les 2 en dur. Chaque source publie maintenant son succès, et on ne purge QUE le périmètre
   des sources qui ont réellement abouti.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PROPOSED_PREFIX = "proposed:"

# ── RÔLES WAMA → comment les découvrir dans la bibliothèque Ollama ──────────────
# Déclaratif : élargir la prospection = ajouter une entrée, pas du code. `capacite` utilise le
# filtre `?c=` du site (vision/embedding/tools/thinking) ; `requetes` complète par recherche
# libre là où aucun filtre ne correspond (traduction, code).
ROLES = {
    'llm': {
        'libelle': 'LLM généraliste (describer, assistant)',
        'capacite': 'tools', 'requetes': (), 'model_type': 'llm',
    },
    'vlm': {
        'libelle': 'Vision / VLM (describer image, reader OCR)',
        'capacite': 'vision', 'requetes': (), 'model_type': 'vlm',
    },
    'embedding': {
        'libelle': 'Embedding (RAG)',
        'capacite': 'embedding', 'requetes': (), 'model_type': 'embedding',
    },
    'coder': {
        'libelle': 'Code (wama-dev-ai)',
        'capacite': '', 'requetes': ('coder',), 'model_type': 'llm',
    },
    'translation': {
        'libelle': 'Traduction (translator)',
        'capacite': '', 'requetes': ('translate',), 'model_type': 'llm',
    },
}

#: Plafond de candidats `new` par rôle. Sans plafond, 4 capacités × ~20 modèles noieraient l'UI :
#: une liste que personne ne lit ne vaut pas mieux qu'une liste vide.
MAX_PAR_ROLE = 5


def _confidence_from_age(age_days) -> float:
    """Plus le modèle installé est ancien, plus on est confiant qu'une MAJ s'impose."""
    try:
        age = float(age_days or 0)
    except (TypeError, ValueError):
        age = 0.0
    return round(min(0.5 + age / 365.0, 0.95), 2)


def _installes() -> set:
    """Noms Ollama réellement installés (sans le préfixe de source)."""
    from wama.model_manager.models import AIModel
    return {
        m.model_key.split(':', 1)[1] for m in
        AIModel.objects.filter(source='ollama', is_proposed=False)
        if ':' in m.model_key
    }


def _ecrire(cand_key, *, nom, model_type, description, kind, confidence, extra):
    from wama.model_manager.models import AIModel
    _, cree = AIModel.objects.update_or_create(
        model_key=cand_key,
        defaults=dict(
            name=nom, model_type=model_type, source='ollama',
            description=description, is_proposed=True, proposal_kind=kind,
            confidence=confidence,
            update_complexity='simple',      # `ollama pull` : remplacement en place
            is_downloaded=False, is_loaded=False, is_available=False, hf_id='',
            extra_info={'prospect': extra},
        ),
    )
    return cree


def prospect_ollama(age_days_threshold: int = 120, include_new: bool = True,
                    max_par_role: int = MAX_PAR_ROLE) -> dict:
    """Lance la prospection Ollama et persiste les candidats. Retourne un résumé."""
    from wama.model_manager.models import AIModel
    from . import ollama_registry as reg
    from .update_checker import check_updates

    crees = maj = 0
    vus_maj: set = set()      # périmètre de la source « installés » (âge + successeurs)
    vus_new: set = set()      # périmètre de la source « bibliothèque »
    ok_installes = ok_registre = False
    installes = _installes()

    # ── 1) Catalogue de la bibliothèque (une fois, partagé par les deux sources) ──
    catalogue: list = []
    for role in ROLES.values():
        for req in (role['requetes'] or ('',)):
            res = reg.rechercher(requete=req, capacite=role['capacite'])
            if res is not None:
                ok_registre = True
                catalogue.extend(res)
    catalogue_uniq = tuple(dict.fromkeys(catalogue))

    # ── 2) Modèles installés : successeur de famille, sinon signal d'âge ──────────
    try:
        report = check_updates(age_days_threshold=age_days_threshold, do_hf=False)
        revue = report.get('ollama_review', [])
        ok_installes = True
    except Exception as exc:                        # pragma: no cover - dépend d'Ollama up
        logger.warning("[prospect_ollama] check_updates indisponible: %s", exc)
        revue = []

    for r in revue:
        origine = r.get('model_key')
        src = AIModel.objects.filter(model_key=origine).first() if origine else None
        if not src:
            continue
        nom_installe = origine.split(':', 1)[1]
        age = r.get('age_days')

        cible = None
        if ok_registre:
            for succ in reg.successeurs(nom_installe, catalogue_uniq):
                tag = reg.tag_equivalent(succ, nom_installe.split(':', 1)[1]
                                         if ':' in nom_installe else '')
                if tag:
                    cible = f"{succ}:{tag}"
                    break

        cand_key = PROPOSED_PREFIX + origine
        vus_maj.add(cand_key)
        if cible:
            desc = (f"Successeur disponible : {cible} (remplace {nom_installe}, "
                    f"installé il y a {age} j).")
            conf = 0.9
        else:
            desc = f"Mise à jour suggérée — {r.get('reason', 'version locale ancienne')}."
            conf = _confidence_from_age(age)
        cree = _ecrire(cand_key, nom=cible or src.name, model_type=src.model_type,
                       description=desc, kind='update', confidence=conf,
                       extra={'kind': 'update', 'origin_key': origine,
                              'reason': r.get('reason', ''), 'age_days': age,
                              'cible': cible})
        crees += int(cree)
        maj += int(not cree)

    # ── 3) Nouveaux candidats par RÔLE (bibliothèque, non installés) ──────────────
    if include_new and ok_registre:
        # Les familles déjà proposées comme SUCCESSEUR sont exclues des candidats « nouveaux » :
        # sinon `qwen3.6:latest` s'affiche en doublon de `qwen3.6:27b` déjà proposé en MAJ.
        familles_ciblees = {
            (m.extra_info.get('prospect', {}).get('cible') or '').split(':')[0]
            for m in AIModel.objects.filter(is_proposed=True, source='ollama',
                                            proposal_kind='update')
        } - {''}
        deja = set(installes) | familles_ciblees
        for nom_role, role in ROLES.items():
            retenus = 0
            for req in (role['requetes'] or ('',)):
                res = reg.rechercher(requete=req, capacite=role['capacite'])
                for nom in (res or ()):
                    if retenus >= max_par_role:
                        break
                    if nom in deja or any(i.split(':')[0] == nom for i in installes):
                        continue
                    tag = reg.tag_equivalent(nom, '')   # → 'latest' vérifié, ou None
                    if not tag:
                        continue                        # jamais proposer un tag non tirable
                    ref = f"{nom}:{tag}"
                    cand_key = PROPOSED_PREFIX + f"ollama:{ref}"
                    vus_new.add(cand_key)
                    deja.add(nom)
                    retenus += 1
                    cree = _ecrire(
                        cand_key, nom=ref, model_type=role['model_type'],
                        description=f"[{role['libelle']}] Proposé par la bibliothèque Ollama.",
                        kind='new', confidence=None,
                        extra={'kind': 'new', 'role': nom_role, 'name': ref,
                               'reason': f"rôle {nom_role} — non installé"})
                    crees += int(cree)
                    maj += int(not cree)

    # ── 4) Purge CIBLÉE : uniquement le périmètre des sources qui ont abouti ──────
    # Une source en échec ne doit RIEN effacer : c'est précisément ce qui, avant, réduisait la
    # liste aux seuls candidats codés en dur dès qu'Ollama ou le réseau hoquetait.
    supprimes = 0
    base = AIModel.objects.filter(is_proposed=True, source='ollama')
    if ok_installes:
        perimetre = base.filter(proposal_kind='update').exclude(model_key__in=vus_maj)
        supprimes += perimetre.count()
        perimetre.delete()
    if ok_registre and include_new:
        perimetre = base.filter(proposal_kind='new').exclude(model_key__in=vus_new)
        supprimes += perimetre.count()
        perimetre.delete()

    resume = {'created': crees, 'updated': maj, 'removed': supprimes,
              'total': len(vus_maj) + len(vus_new),
              'sources': {'installes': ok_installes, 'registre': ok_registre}}
    logger.info("[prospect_ollama] %s", resume)
    return resume
