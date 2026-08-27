"""
Catalogue des SKILLS de prompt — vue DÉRIVÉE, sans registre propre.

POURQUOI CETTE PAGE (demande de Fabien, 2026-08-27)

    Le registre `skills` existait déjà (`registries_builtin.py`) avec son compteur et son
    rafraîchisseur, mais **sans `url_name`** : il était le seul registre de la carte à ne
    désigner aucune page. Le catalogue était donc lisible par l'assistant IA et par
    wama-dev-ai (`skills_catalog()`), et par personne d'autre.

CE QUE LA PAGE AJOUTE À UN `ls` DU DOSSIER — et c'est tout son intérêt : **qui consomme quoi**.
Un fichier `.md` posé dans `prompt_skills/` ne sert à rien tant qu'une déclaration ne le fait
pas résoudre. Le lien est calculé ici, jamais déclaré :

  • famille ENRICHISSEMENT → rejointe par `resolve_skill(app, domain, kind)` depuis les
    `PROMPT_TARGETS` d'`app_metadata.py` ;
  • famille RÔLE → rejointe par `assistant_skills.DOMAINES` (`charger_competence`).

⚠ LES DEUX FAMILLES NE SE MÉLANGENT PAS, et les confondre « coûte une passe LLM pour rien »
(`assistant_skills.py`). Un skill d'enrichissement transforme UN PROMPT dans l'app ; un skill
de rôle définit la POSTURE de l'assistant. La page les sépare visuellement pour cette raison.

⚠ DEUX ÉCARTS SONT AFFICHÉS, parce qu'ils sont muets partout ailleurs — c'est la leçon
« ce qui ne plante pas ne se signale pas » : un skill orphelin est un fichier qu'on croit
actif, un target sans skill est une app qu'on croit outillée. Ni l'un ni l'autre ne lève
d'erreur : le LLM reçoit simplement une consigne générique, ou aucune.

Rien n'est stocké : la synthèse dérive de `skills_catalog()`, de `PROMPT_TARGETS` et de
`DOMAINES` à chaque affichage — elle ne peut pas diverger d'eux.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Familles DÉCLARÉES. La clé sert de facette ; l'ordre fait l'ordre d'affichage.
FAMILLES = {
    'enrichissement': "Enrichissement de prompt",
    'role': "Rôle de l'assistant",
    'repli': "Repli générique",
}


def _resume(texte: str) -> str:
    """Première phrase utile du skill — le fichier EST le system prompt, il n'a pas de titre."""
    for ligne in (texte or '').splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith(('#', '-', '```')):
            return ligne
    return ''


def _consommateurs_enrichissement(presents: set) -> dict:
    """
    {nom_de_skill: [phrases]} — qui, dans les `PROMPT_TARGETS`, atteint quel skill.

    On REJOUE la résolution de `resolve_skill` au lieu de l'appeler : la vraie fonction rend le
    premier candidat EXISTANT, ce qui suffit à l'exécution mais masquerait ici le repli. La page
    doit dire « ce target tombe sur le générique », pas seulement « il a un skill ».

    ⚠ `domain_field` (imager `output_type`) n'est connu qu'à l'exécution : le domaine dépend de
    l'instance. On ne l'invente pas — on attribue le target à TOUS les skills `<app>-*` présents,
    en le disant. Deviner une valeur produirait un lien faux, ce qui est pire qu'un lien large.
    """
    from ..utils.app_metadata import PROMPT_TARGETS
    from ..utils.prompt_skills import _slug

    par_skill, orphelins_de_target = {}, []

    for app, targets in sorted(PROMPT_TARGETS.items()):
        a = _slug(app)
        for t in targets:
            champ = t.get('field', '?')
            kind = t.get('kind') or 'generative'
            qui = f"{app} · <code>{champ}</code>"

            if t.get('domain_field'):
                # Domaine dynamique : les skills `<app>-*` présents sont les cibles possibles.
                candidats = sorted(n for n in presents if n.startswith(f"{a}-"))
                if candidats:
                    for n in candidats:
                        par_skill.setdefault(n, []).append(
                            f"{qui} (domaine lu sur <code>{t['domain_field']}</code>)")
                    continue

            d = _slug(t.get('domain'))
            for nom in ([f"{a}-{d}"] if d else []) + [a, f"default-{_slug(kind)}"]:
                if nom in presents:
                    par_skill.setdefault(nom, []).append(qui)
                    break
            else:
                # Aucun candidat n'existe : le pipeline garde son repli intégré et le LLM
                # travaille sans consigne dédiée. Silencieux à l'exécution, donc affiché ici.
                orphelins_de_target.append({'app': app, 'champ': champ, 'kind': kind})

    return par_skill, orphelins_de_target


def _consommateurs_role() -> dict:
    """{nom_de_skill: [phrases]} depuis le registre déclaratif des domaines de l'assistant."""
    try:
        from ..utils.assistant_skills import DOMAINES
    except Exception:
        logger.debug("[skills_catalog] domaines d'assistant indisponibles", exc_info=True)
        return {}
    return {d.skill: [f"Assistant · domaine « {d.libelle} »"
                      + (" · rappel RAG" if d.rag else "")] for d in DOMAINES}


def synthese() -> dict:
    """Le catalogue complet, prêt à rendre. Aucun argument : les skills ne sont pas scopés."""
    from ..utils.prompt_skills import skills_catalog

    catalogue = skills_catalog()
    presents = set(catalogue)

    par_skill, targets_orphelins = _consommateurs_enrichissement(presents)
    role = _consommateurs_role()

    skills = []
    for nom, texte in sorted(catalogue.items()):
        if nom in role:
            famille = 'role'
        elif nom.startswith('default-'):
            famille = 'repli'
        else:
            famille = 'enrichissement'

        app, _, domaine = nom.partition('-')
        conso = role.get(nom) or par_skill.get(nom, [])
        skills.append({
            'nom': nom,
            'famille': famille,
            'famille_label': FAMILLES[famille],
            'app': app,
            'domaine': domaine,
            'resume': _resume(texte),
            'texte': texte,
            'lignes': len((texte or '').splitlines()),
            'consommateurs': conso,
            # Un skill de repli n'a pas de consommateur NOMMÉ : il est atteint par défaut,
            # donc l'absence de lien y est normale et ne doit pas s'afficher en alerte.
            'orphelin': not conso and famille != 'repli',
        })

    return {
        'skills': skills,
        'total': len(skills),
        'par_famille': {c: sum(1 for s in skills if s['famille'] == c) for c in FAMILLES},
        'orphelins': sum(1 for s in skills if s['orphelin']),
        'targets_orphelins': targets_orphelins,
    }
