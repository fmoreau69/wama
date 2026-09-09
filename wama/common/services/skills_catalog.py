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
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: Placeholder de `str.format()` — ce qui distingue un GABARIT d'une consigne.
_PLACEHOLDER = re.compile(r'\{(\w+)\}')

#: Familles DÉCLARÉES. La clé sert de facette ; l'ordre fait l'ordre d'affichage.
#:
#: ⚠ ÉTENDU le 2026-09-09 de 3 à 5 familles — et l'axe qui les ordonne n'est PAS « quel outil
#: lit le fichier » mais **QUI CHOISIT LA CONSIGNE**, parce que c'est lui qui impose le format
#: (tranché avec Fabien, `WAMA_LLM §0bis 🔒`) :
#:
#:   • CHOISIE PAR LE CODE → fichier NU. Le consommateur final ne sait pas choisir : un modèle
#:     de diffusion, SAM3 ou MusicGen n'encaissent qu'une chaîne. Les quatre premières familles
#:     sont là — y compris les consignes de rôle de wama-dev-ai, que `consigne_role(nom)`
#:     sélectionne par NOM DE RÔLE, jamais par description.
#:   • CHOISIE PAR UN AGENT → dossier + SKILL.md à frontmatter, parce qu'il faut une
#:     `description` à lire pour décider. C'est `.claude/skills/`, et c'est la seule.
#:
#: CE QUE CETTE EXTENSION A CORRIGÉ DANS MON PROPRE PLAN : on avait envisagé de FUSIONNER
#: `wama-dev-ai/prompts/` et `.claude/skills/` en un seul dossier, au motif qu'ils travaillent
#: tous deux sur le CODE. La mesure du 2026-09-09 l'a interdit : **5 des 11 consignes de rôle
#: sont des gabarits `.format()`** (`{task}`, `{tools}`, `{code}`, `{files}`) — les porter en
#: SKILL.md casserait la substitution ET le contrat du format, qui veut un corps lu VERBATIM.
#: L'objet traité (le code) rapprochait les deux familles ; le mécanisme de sélection les
#: sépare, et c'est le mécanisme qui décide. *Elles se rejoignent sur cette PAGE, pas sur le
#: disque.*
FAMILLES = {
    'enrichissement': "Enrichissement de prompt",
    'role': "Rôle de l'assistant",
    'repli': "Repli générique",
    'role_dev': "Rôle wama-dev-ai",
    'dev_agent': "Skill de développement",
}

#: Où vivent les deux familles ajoutées. Relatif à la racine du dépôt, résolu à l'appel.
DOSSIER_ROLES_DEV = 'wama-dev-ai/prompts'
DOSSIER_SKILLS_AGENT = '.claude/skills'


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
    return {d.skill: [f"Assistant · domaine « {d.label} »"
                      + (" · rappel RAG" if d.rag else "")] for d in DOMAINES}


def _racine():
    from django.conf import settings
    return Path(settings.BASE_DIR)


def _roles_dev(sequences=None) -> list:
    """Consignes de rôle de wama-dev-ai (`prompts/*.txt`) — famille `role_dev`.

    Leur consommateur est `role_utils.consigne_role(nom)`, qui les choisit PAR NOM DE RÔLE.
    C'est donc bien le CODE qui sélectionne, comme pour l'enrichissement — d'où le fichier nu.

    On DIT lesquelles sont des gabarits (`{task}`, `{tools}`…) : c'est l'information qui
    interdit de les confondre avec un skill d'agent, et elle est invisible partout ailleurs.
    Une consigne à placeholders n'est pas une consigne, c'est un patron à remplir.
    """
    sequences = sequences or {}
    dossier = _racine() / DOSSIER_ROLES_DEV
    sorties = []
    try:
        fichiers = sorted(dossier.glob('*.txt'))
    except OSError as e:
        logger.debug("[skills_catalog] rôles dev illisibles : %s", e)
        return sorties

    for p in fichiers:
        try:
            texte = p.read_text(encoding='utf-8')
        except OSError:
            continue
        trous = sorted(set(_PLACEHOLDER.findall(texte)))
        conso = [f"wama-dev-ai · <code>consigne_role('{p.stem}')</code>"]
        if trous:
            conso.append("gabarit <code>.format()</code> — attend "
                         + ", ".join(f"<code>{{{t}}}</code>" for t in trous))
        # Le SENS INVERSE du lien déclaré : quel skill d'agent séquence cette méthode. Sans lui,
        # la page dirait « qui l'exécute » sans jamais dire « qui l'orchestre ».
        sequence_par = sequences.get(p.stem, [])
        for s in sequence_par:
            conso.append(f"séquencé par le skill <code>/{s}</code> "
                         f"(<code>prompt: {p.stem}</code>)")
        sorties.append({
            'nom': p.stem, 'famille': 'role_dev', 'famille_label': FAMILLES['role_dev'],
            'app': 'wama-dev-ai', 'domaine': '', 'resume': _resume(texte), 'texte': texte,
            'lignes': len(texte.splitlines()), 'consommateurs': conso,
            'selection': 'code', 'gabarit': bool(trous), 'orphelin': False,
            'sequence_par': sequence_par,
        })
    return sorties


def _skills_agent() -> list:
    """Skills de développement (`.claude/skills/<nom>/SKILL.md`) — famille `dev_agent`.

    La SEULE famille choisie par un AGENT, d'après la `description` de son frontmatter — d'où
    le format à frontmatter, et d'où sa présence ici : sans elle, la page prétendrait montrer
    « les consignes données aux modèles » en en cachant un tiers.

    ⚠ Elles ne sont PAS résolues par WAMA : aucun code du dépôt ne les charge. Leur
    « consommateur » est le harnais de l'agent, ce qu'on affiche tel quel plutôt que de laisser
    croire à un orphelin.
    """
    dossier = _racine() / DOSSIER_SKILLS_AGENT
    sorties = []
    try:
        fichiers = sorted(dossier.glob('*/SKILL.md'))
    except OSError as e:
        logger.debug("[skills_catalog] skills d'agent illisibles : %s", e)
        return sorties

    for p in fichiers:
        try:
            texte = p.read_text(encoding='utf-8')
        except OSError:
            continue
        meta, corps = _frontmatter(texte)
        # Lien DÉCLARÉ vers une consigne de rôle : `prompt: <nom>` (+ `agent:`). Le skill porte
        # le SÉQUENÇAGE, le prompt porte la MÉTHODE — l'un ne recopie jamais l'autre. Un lien
        # qui ne résout pas est signalé : aujourd'hui il serait parfaitement muet.
        lien = meta.get('prompt', '')
        sorties.append({
            'nom': meta.get('name') or p.parent.name,
            'famille': 'dev_agent', 'famille_label': FAMILLES['dev_agent'],
            'app': '', 'domaine': '',
            'prompt_lie': lien,
            'agent_lie': meta.get('agent', ''),
            # Le résumé EST la description du frontmatter : c'est littéralement le texte sur
            # lequel l'agent décide d'activer le skill. Le remplacer par la 1ʳᵉ ligne du corps
            # afficherait autre chose que ce qui sert à choisir.
            'resume': meta.get('description') or _resume(corps),
            'texte': corps, 'lignes': len(corps.splitlines()),
            'consommateurs': [f"Harnais d'agent · <code>{DOSSIER_SKILLS_AGENT}/"
                              f"{p.parent.name}/</code> (choisi sur description)"],
            'selection': 'agent', 'gabarit': False, 'orphelin': False,
        })
    return sorties


def _frontmatter(texte: str):
    """`(métadonnées, corps)` d'un SKILL.md. Sans PyYAML : les clés utiles sont plates.

    Volontairement minimal — on ne lit que `name` et `description`, seules clés dont la page a
    besoin. Un parseur complet ferait dépendre une page d'affichage d'un format tiers.
    """
    if not texte.startswith('---'):
        return {}, texte
    fin = texte.find('\n---', 3)
    if fin == -1:
        return {}, texte
    meta = {}
    for ligne in texte[3:fin].splitlines():
        cle, sep, valeur = ligne.partition(':')
        # `prompt` / `agent` : le LIEN DÉCLARÉ vers une consigne de rôle wama-dev-ai. Convention
        # posée par `/cartographie` et documentée dans son corps (« la méthode vit dans le
        # prompt, le séquençage ici, ne JAMAIS recopier la méthode »). Elle existait sans être
        # ni outillée ni mesurée : 1 skill sur 14 la portait, et rien ne l'aurait dit.
        if sep and cle.strip() in ('name', 'description', 'prompt', 'agent'):
            meta[cle.strip()] = valeur.strip()
    return meta, texte[fin + 4:].lstrip('\n')


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
            'selection': 'code',
            'gabarit': False,
            # Un skill de repli n'a pas de consommateur NOMMÉ : il est atteint par défaut,
            # donc l'absence de lien y est normale et ne doit pas s'afficher en alerte.
            'orphelin': not conso and famille != 'repli',
        })

    # Les deux familles ajoutées le 2026-09-09. Elles ne passent PAS par `skills_catalog()` :
    # ce sont d'autres dossiers, d'autres extensions, d'autres consommateurs. Les y forcer
    # aurait demandé d'élargir un accesseur dont le contrat est « les skills de prompt WAMA ».
    # ORDRE IMPOSÉ : les skills d'agent d'abord, parce qu'ils PORTENT le lien déclaré
    # (`prompt: <nom>`) dont les consignes de rôle ont besoin pour afficher le sens inverse.
    agents = _skills_agent()
    sequences = {}
    for s in agents:
        if s['prompt_lie']:
            sequences.setdefault(s['prompt_lie'], []).append(s['nom'])

    roles = _roles_dev(sequences)
    connus = {r['nom'] for r in roles}

    # ⚠ Un `prompt:` qui ne résout pas est PARFAITEMENT MUET aujourd'hui : le skill s'active
    # quand même, l'agent lit son séquençage, et la méthode qu'il est censé appliquer n'existe
    # pas. Même famille que le skill orphelin — l'absence ne lève rien, donc elle s'affiche.
    liens_casses = [{'skill': s['nom'], 'prompt': s['prompt_lie']}
                    for s in agents if s['prompt_lie'] and s['prompt_lie'] not in connus]

    skills += roles
    skills += agents

    # ⚠ DEUX totaux, et les nommer mal se paie tout de suite : `total` doit rester le nombre de
    # ce que la page LISTE (sinon `sum(par_famille) != total`, et deux gardes préexistantes le
    # signalent aussitôt — elles l'ont fait). Le compte des skills de PROMPT est un total à part,
    # parce que c'est LUI que le registre `skills` publie (`_count_skills` → `skills_catalog()`).
    # Les confondre ferait afficher deux nombres différents pour la même chose sur la page et
    # sur la carte des registres, et on chercherait longtemps lequel ment.
    total_prompt = sum(1 for s in skills if s['famille'] in ('enrichissement', 'role', 'repli'))

    return {
        'skills': skills,
        'total': len(skills),
        'total_prompt': total_prompt,
        'par_famille': {c: sum(1 for s in skills if s['famille'] == c) for c in FAMILLES},
        'orphelins': sum(1 for s in skills if s['orphelin']),
        'targets_orphelins': targets_orphelins,
        'liens_casses': liens_casses,
        # Combien de paires méthode↔séquençage sont DÉCLARÉES. Mesuré le 2026-09-09 : 1 sur 14.
        # La convention existe (posée et documentée par `/cartographie`), elle n'était ni
        # outillée ni comptée — donc invisible, donc jamais étendue.
        'paires_declarees': sum(1 for s in agents if s['prompt_lie']),
        # Les DÉCLARATIONS elles-mêmes (registre `prompts`) : la page montrait les champs-prompt
        # seulement comme « consommateurs » d'un skill, donc une app qui n'en résout aucun était
        # invisible — `synthesizer` déclare `[]` DÉLIBÉRÉMENT (§16.6 : un texte TTS ne se traduit
        # jamais) et n'apparaissait nulle part. Un « explicitement rien » qu'on ne voit pas se
        # relit comme un oubli.
        'declarations': _declarations(),
    }


def _declarations() -> list:
    """`PROMPT_TARGETS` rendu lisible — le registre `prompts` (14ᵉ) sur sa page."""
    from ..utils.app_metadata import PROMPT_TARGETS

    lignes = []
    for app, targets in sorted(PROMPT_TARGETS.items()):
        lignes.append({
            'app': app,
            'champs': [{'champ': t.get('field', '?'), 'kind': t.get('kind') or 'generative',
                        'domaine': t.get('domain') or t.get('domain_field') or '',
                        'enrich': bool(t.get('enrich'))} for t in targets],
            'aucun': not targets,
        })
    return lignes
