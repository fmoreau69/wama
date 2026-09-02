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
#: `task` (2026-09-02) : la TÂCHE canonique écrite sur le candidat — sans elle, 26 lignes
#: `proposed:ollama:*` n'avaient aucun banc ni aucune sélection par tâche (`check_model_taxonomy`
#: les comptait « sans task ») là où les candidats HF en portaient une depuis le matin.
ROLES = {
    'llm': {
        'libelle': 'LLM généraliste (describer, assistant)',
        'capacite': 'tools', 'requetes': (), 'model_type': 'llm', 'task': 'text-generation',
    },
    'vlm': {
        'libelle': 'Vision / VLM (describer image, reader OCR)',
        'capacite': 'vision', 'requetes': (), 'model_type': 'vlm', 'task': 'captioning',
    },
    'embedding': {
        'libelle': 'Embedding (RAG)',
        'capacite': 'embedding', 'requetes': (), 'model_type': 'embedding',
        'task': 'feature-extraction',
    },
    'coder': {
        'libelle': 'Code (wama-dev-ai)',
        'capacite': '', 'requetes': ('coder',), 'model_type': 'llm', 'task': 'text-generation',
    },
    'translation': {
        'libelle': 'Traduction (translator)',
        'capacite': '', 'requetes': ('translate',), 'model_type': 'llm',
        'task': 'text-generation',
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


def write_candidate(cand_key, *, nom, model_type, description, kind, confidence, extra,
                    source='ollama', complexite='simple', **champs):
    """
    Écrit/rafraîchit UN candidat de prospection (`AIModel(is_proposed=True)`).

    Writer UNIQUE, toutes sources (généralisé le 2026-08-18 pour la prospection
    génération HF — `prospector.seed_hf_candidates`) : c'est lui qui porte la
    garde de préservation des évaluations LLM, elle doit valoir partout.
    `champs` : colonnes additionnelles (hf_id, license, platform_ref, disk_gb…).
    """
    from wama.model_manager.models import AIModel
    defaults = dict(
        name=nom, model_type=model_type, source=source,
        description=description, is_proposed=True, proposal_kind=kind,
        confidence=confidence,
        update_complexity=complexite,    # ollama pull / snapshot HF : install en place
        is_downloaded=False, is_loaded=False, is_available=False, hf_id='',
        extra_info={'prospect': extra},
    )
    defaults.update(champs)
    # Une évaluation LLM persistée (`assess_proposed`) a COÛTÉ des appels d'agents :
    # la re-prospection rafraîchit le candidat (raison, cible…), elle ne l'efface pas.
    # Sans cette garde, chaque clic « Prospecter » remettait `confidence=None` sur tous
    # les `new` et repartait de zéro (constaté à la conception, 2026-08-18).
    existant = AIModel.objects.filter(model_key=cand_key, is_proposed=True).first()
    if existant:
        assess = ((existant.extra_info or {}).get('prospect') or {}).get('assess')
        if assess:
            defaults['extra_info'] = {'prospect': dict(extra, assess=assess)}
            if confidence is None:
                defaults['confidence'] = existant.confidence
    _, cree = AIModel.objects.update_or_create(model_key=cand_key, defaults=defaults)
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
            res = reg.search(requete=req, capacite=role['capacite'])
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

    from .update_checker import local_digests
    digests = local_digests()      # {nom: digest} — vide si le démon ne répond pas
    identiques = 0                  # « MAJ » écartées parce que le distant est le même

    for r in revue:
        origine = r.get('model_key')
        src = AIModel.objects.filter(model_key=origine).first() if origine else None
        if not src:
            continue
        nom_installe = origine.split(':', 1)[1]
        age = r.get('age_days')
        maj_reelle = False          # digests différents = republication du même tag

        cible = None
        if ok_registre:
            for succ in reg.successeurs(nom_installe, catalogue_uniq):
                tag = reg.tag_equivalent(succ, nom_installe.split(':', 1)[1]
                                         if ':' in nom_installe else '')
                if tag:
                    cible = f"{succ}:{tag}"
                    break

        # ── « MAJ » qui ne mettrait RIEN à jour : on ne la propose pas ────────────────
        # Sans successeur identifié, un candidat `update` propose de re-tirer LE MÊME TAG sur
        # le seul critère de l'âge d'installation — d'où l'absurdité constatée par Fabien le
        # 2026-08-19 : « qwen3.5:9b … Remplace qwen3.5:9b » (installé il y a 166 j, mais le
        # tag distant a EXACTEMENT le même digest : le pull serait un no-op).
        # Le digest tranche : identique ⇒ pas de candidat (et le candidat existant sera purgé,
        # puisqu'il ne figure pas dans `vus_maj`) ; différent ⇒ vraie nouvelle version publiée
        # sous le même tag, on le dit. Indéterminable (réseau) ⇒ comportement d'avant.
        if not cible:
            distant = None
            try:
                nom_court, _, tag_court = nom_installe.partition(':')
                distant = reg.remote_digest(nom_court, tag_court or 'latest')
            except Exception:
                distant = None
            local = digests.get(nom_installe) or ''
            if distant and local and distant == local:
                identiques += 1
                logger.info("[prospect_ollama] %s : tag distant IDENTIQUE (digest %s…) — "
                            "aucune mise à jour à proposer", nom_installe, local[:12])
                continue
            if distant and local and distant != local:
                maj_reelle = True

        cand_key = PROPOSED_PREFIX + origine
        vus_maj.add(cand_key)
        if cible:
            desc = (f"Successeur disponible : {cible} (remplace {nom_installe}, "
                    f"installé il y a {age} j).")
            conf = 0.9
        elif maj_reelle:
            # Le tag n'a pas changé de nom, mais son CONTENU a été republié : c'est une vraie
            # mise à jour en place, et on l'affirme sur preuve (digests différents), pas sur l'âge.
            desc = (f"Nouvelle version publiée sous le même tag {nom_installe} "
                    f"(local installé il y a {age} j).")
            conf = 0.9
        else:
            desc = f"Mise à jour suggérée — {r.get('reason', 'version locale ancienne')}."
            conf = _confidence_from_age(age)
        cree = write_candidate(cand_key, nom=cible or src.name, model_type=src.model_type,
                               description=desc, kind='update', confidence=conf,
                               # Un successeur exerce le MÊME métier que l'installé qu'il vise.
                               capabilities={'task': (src.capabilities or {}).get('task')}
                               if (src.capabilities or {}).get('task') else {},
                               extra={'kind': 'update', 'origin_key': origine,
                                      'reason': r.get('reason', ''), 'age_days': age,
                                      'cible': cible,
                                      # Preuve de la nature de la MAJ (vue par l'inspecteur) :
                                      # 'republication' = même tag, contenu différent.
                                      'maj': ('successeur' if cible else
                                              'republication' if maj_reelle else 'age')})
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
        # Référentiel « à surpasser » par type — calculé UNE fois par rôle et PERSISTÉ sur le
        # candidat (`concurrence`) : c'est ce que la card affiche pour répondre à « qu'est-ce
        # que ce nouveau modèle pourrait remplacer ? » (demande Fabien 2026-08-18).
        _refs_type: dict = {}
        for nom_role, role in ROLES.items():
            if role['model_type'] not in _refs_type:
                _refs_type[role['model_type']] = [
                    m.name for m in AIModel.best_installed(role['model_type'])]
            retenus = 0
            for req in (role['requetes'] or ('',)):
                res = reg.search(requete=req, capacite=role['capacite'])
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
                    cree = write_candidate(
                        cand_key, nom=ref, model_type=role['model_type'],
                        description=f"[{role['libelle']}] Proposé par la bibliothèque Ollama.",
                        kind='new', confidence=None,
                        extra={'kind': 'new', 'role': nom_role, 'name': ref,
                               'reason': f"rôle {nom_role} — non installé",
                               'concurrence': _refs_type[role['model_type']]},
                        capabilities={'task': role['task']})
                    crees += int(cree)
                    maj += int(not cree)

    # ── 4) Purge CIBLÉE : uniquement le périmètre des sources qui ont abouti ──────
    # Une source en échec ne doit RIEN effacer : c'est précisément ce qui, avant, réduisait la
    # liste aux seuls candidats codés en dur dès qu'Ollama ou le réseau hoquetait.
    # ⚠ Un candidat porteur d'une ÉVALUATION LLM n'est jamais purgé : elle a coûté des
    # appels d'agents (et du GPU). Il reste jusqu'à ce qu'un humain le rejette — même règle
    # que `write_candidate`, qui préserve déjà l'évaluation à l'écriture (2026-08-19).
    supprimes = preserves = 0

    def _purge(qs):
        nonlocal supprimes, preserves
        for m in qs:
            if ((m.extra_info or {}).get('prospect') or {}).get('assess'):
                preserves += 1
                continue
            m.delete()
            supprimes += 1

    base = AIModel.objects.filter(is_proposed=True, source='ollama')
    if ok_installes:
        _purge(base.filter(proposal_kind='update').exclude(model_key__in=vus_maj))
    if ok_registre and include_new:
        _purge(base.filter(proposal_kind='new').exclude(model_key__in=vus_new))

    resume = {'created': crees, 'updated': maj, 'removed': supprimes,
              'preserved': preserves,   # évalués, hors périmètre courant : conservés
              'total': len(vus_maj) + len(vus_new),
              # « MAJ » écartées : tag ancien mais digest distant IDENTIQUE (le pull serait
              # un no-op). Tracé pour qu'un écart de comptage s'explique sans lire le code.
              'identiques': identiques,
              'sources': {'installes': ok_installes, 'registre': ok_registre}}
    logger.info("[prospect_ollama] %s", resume)
    return resume
