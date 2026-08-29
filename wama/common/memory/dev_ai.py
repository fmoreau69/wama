"""
Reprise de la mémoire de wama-dev-ai (`memory.json`) dans `MemoryItem`. Doc : `WAMA_MEMORY.md`.

CE QUE C'EST. wama-dev-ai tenait sa mémoire dans un JSON écrit à la main
(`wama-dev-ai/memory.json`, v1.0) : architecture, bugs connus, règles, modèles déployés,
implémentations récentes. Deux de ses champs — `past_sessions` et `persistent_notes` — sont
restés VIDES depuis la création : la mémoire ne s'écrivait pas toute seule.

⚠ CE FICHIER EST VIEUX, ET C'EST LE POINT CENTRAL DE CE MODULE. `last_updated = 2026-04-14`,
soit **129 jours** au moment de la reprise. Son `models_deployed` liste encore les `qwen3.5`
alors que le défaut est passé à `gemma4:e4b` puis que `qwen3.8` est arrivé ; ses `known_issues`
n'ont pas été rejoués depuis. Importer tout cela comme des FAITS injecterait des affirmations
périmées dans le magasin, avec le même statut que du vérifié.

D'où le parti : **tout arrive NON APPROUVÉ** (`provenance='dev-ai'`), donc invisible au rappel
tant qu'un humain n'a pas validé — c'est exactement ce pour quoi la gouvernance existe
(`WAMA_MEMORY.md §6`). La vétusté cesse d'être un risque : elle devient une **file de revue**.
Chaque souvenir porte la date de la source dans son contenu, pour que le relecteur sache sur quoi
il se prononce.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Emplacement du fichier historique. Il RESTE en place : ce module le LIT, ne le supprime pas.
#: Le retirer serait une décision de wama-dev-ai, pas de la brique mémoire.
CHEMIN_DEFAUT = 'wama-dev-ai/memory.json'


def _sentences(donnees, date_source):
    """
    Transforme le JSON en souvenirs lisibles `(kind, subject, texte)`.

    Chaque texte porte la DATE DE LA SOURCE : un relecteur doit pouvoir juger sans rouvrir le
    fichier, et un souvenir de 129 jours ne se lit pas comme un souvenir d'hier.
    """
    from ..models import MemoryItem

    suffixe = f" (source : memory.json de wama-dev-ai, {date_source})"
    sorties = []

    for cle, valeur in (donnees.get('architecture') or {}).items():
        sorties.append((MemoryItem.KIND_SEMANTIC, 'architecture',
                        f"Architecture WAMA — {cle} : {valeur}{suffixe}"))

    for cle, issue in (donnees.get('known_issues') or {}).items():
        if not isinstance(issue, dict):
            continue
        bouts = [f"Problème connu « {cle} » ({issue.get('status', 'statut inconnu')})"]
        if issue.get('symptom'):
            bouts.append(f"symptôme : {issue['symptom']}")
        if issue.get('file'):
            bouts.append(f"fichier : {issue['file']}")
        if issue.get('piste'):
            bouts.append(f"piste : {issue['piste']}")
        if issue.get('next_step'):
            bouts.append(f"prochaine étape : {issue['next_step']}")
        sorties.append((MemoryItem.KIND_SEMANTIC, cle, ' — '.join(bouts) + suffixe))

    # Les règles sont PROCÉDURALES : elles disent comment faire, pas ce qui est.
    for cle, regle in (donnees.get('rules') or {}).items():
        sorties.append((MemoryItem.KIND_PROCEDURAL, 'regles', f"Règle « {cle} » : {regle}{suffixe}"))

    deploiement = donnees.get('models_deployed') or {}
    if deploiement.get('ollama'):
        sorties.append((MemoryItem.KIND_SEMANTIC, 'modeles',
                        "Modèles Ollama déployés : "
                        + ', '.join(deploiement['ollama']) + suffixe))
    for famille, liste in (deploiement.get('huggingface_local') or {}).items():
        sorties.append((MemoryItem.KIND_SEMANTIC, 'modeles',
                        f"Modèles HuggingFace locaux ({famille}) : "
                        + ', '.join(liste) + suffixe))

    # Les implémentations sont ÉPISODIQUES : elles sont datées et ne se re-vérifient pas.
    for date, items in (donnees.get('recent_implementations') or {}).items():
        for item in items:
            sorties.append((MemoryItem.KIND_EPISODIC, 'implementations',
                            f"Le {date} : {item}{suffixe}"))

    return sorties


def import_memory(chemin=None, *, user=None, dry_run=False):
    """
    Importe `memory.json` en souvenirs NON APPROUVÉS. Rend un résumé `{...}`.

    Idempotente par `content_hash` : relancer ne duplique pas. `user=None` — ces souvenirs
    portent sur la PLATEFORME, pas sur une personne ; ils n'appartiennent donc à personne.

    ⚠ Conséquence assumée : avec `user=None` et une visibilité privée, ils ne sont rappelables
    par PERSONNE tant qu'un humain ne les a pas approuvés ET repositionnés (visibilité `public`
    ou `unit`). C'est voulu — un import automatique ne doit pas décider seul de la portée d'un
    savoir, et 129 jours de vétusté ne s'auto-publient pas.
    """
    from django.conf import settings

    from ..models import MemoryItem
    from .store import remember

    chemin = Path(chemin or (Path(settings.BASE_DIR) / CHEMIN_DEFAUT))
    resume = {'fichier': str(chemin), 'lus': 0, 'crees': 0, 'deja_presents': 0,
              'date_source': None, 'dry_run': dry_run}

    try:
        donnees = json.loads(chemin.read_text(encoding='utf-8'))
    except Exception as e:
        logger.warning('[memory.dev_ai] lecture impossible (%s) : %s', chemin, e)
        resume['erreur'] = str(e)
        return resume

    date_source = donnees.get('last_updated') or 'date inconnue'
    resume['date_source'] = date_source

    for kind, subject, texte in _sentences(donnees, date_source):
        resume['lus'] += 1
        if dry_run:
            continue
        avant = MemoryItem.objects.count()
        item = remember(
            texte,
            kind=kind,
            provenance=MemoryItem.PROV_DEV_AI,
            user=user,
            subject=subject,
            source_app='wama-dev-ai',
            # ⚠ JAMAIS approuvé à l'import — cf. docstring du module. Le relecteur tranche.
            approved=False,
            # Aucun appel de modèle : `store.reindex()` fera les vecteurs par lot.
            embed=False,
        )
        if item is None:
            continue
        if MemoryItem.objects.count() > avant:
            resume['crees'] += 1
        else:
            resume['deja_presents'] += 1

    if not dry_run:
        logger.info('[memory.dev_ai] %s entrées lues → %s créées (non approuvées), %s déjà là',
                    resume['lus'], resume['crees'], resume['deja_presents'])
    return resume
