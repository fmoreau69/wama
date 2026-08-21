"""
Skills de RÔLE de l'assistant — qui il est, ce qu'il sait, comment il répond.

⚠ DEUX NATURES DE SKILLS COEXISTENT, ET LES CONFONDRE COÛTE UNE PASSE LLM POUR RIEN.

  • skill d'ENRICHISSEMENT (`imager-image`, `composer-music`…) : consigne donnée au LLM
    d'enrichissement pour transformer un prompt de génération. Elle est appliquée DANS
    L'APP, au lancement de la tâche (`process_prompt_for`, cf. `imager/tasks.py`). Rien à
    câbler ici : le faire une seconde fois côté assistant enrichirait un prompt déjà
    enrichi.
  • skill de RÔLE (ce module, `assistant-*`) : consigne donnée à l'ASSISTANT lui-même, dans
    son prompt système. Elle ne transforme aucun prompt — elle définit une posture, un
    domaine et des interdits.

C'est la seconde qui manquait : jusqu'au 2026-08-21 le prompt système de l'assistant tenait
en trois lignes génériques, sans domaine et sans contexte de laboratoire. Un assistant
scientifique n'est pas un assistant généraliste à qui on demande poliment d'être rigoureux.

CE MODULE NE RECRÉE PAS DE CHARGEUR. Les fichiers vivent dans `common/prompt_skills/` et
sont lus par `prompt_skills.load_skill()` — même dossier, même cache, même fail-safe que les
skills d'enrichissement. Seule la FAMILLE (préfixe `assistant-`) et le contrat diffèrent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DomaineAssistant:
    """Un domaine d'intervention de l'assistant."""

    cle: str
    libelle: str
    #: Nom du fichier de skill dans `common/prompt_skills/` (sans extension).
    skill: str
    #: Le domaine tire-t-il parti du contexte du laboratoire (RAG) ?
    #: DÉCLARÉ, jamais deviné : c'est ce qui évite de payer une recherche vectorielle sur
    #: « quel est le statut de ma transcription ? ».
    rag: bool = False
    #: Une ligne pour l'UI.
    aide: str = ''


#: Registre DÉCLARATIF des domaines. Ajouter un domaine = ajouter une entrée ici et un
#: fichier `assistant-<skill>.md` — aucune app, aucune vue à modifier.
#: ⚠ L'ORDRE fait l'ordre d'affichage ; `general` reste le défaut et le premier.
DOMAINES = (
    DomaineAssistant('general', 'Général', 'assistant-general',
                     aide="Usage courant de WAMA : lancer, suivre, récupérer."),
    DomaineAssistant('science', 'Scientifique', 'assistant-science', rag=True,
                     aide="Questions de méthode et de résultats, avec le contexte du labo."),
    DomaineAssistant('design', 'Graphisme', 'assistant-design', rag=True,
                     aide="Logos, illustrations, visuels — cadrés par l'identité du labo."),
    DomaineAssistant('dev', 'Développement', 'assistant-dev',
                     aide="Code, architecture et conventions de WAMA."),
)

DOMAINE_DEFAUT = 'general'

_PAR_CLE = {d.cle: d for d in DOMAINES}

#: Nombre d'extraits de contexte injectés. Volontairement bas : au-delà, le contexte chasse
#: la question du champ d'attention des petits modèles locaux, et la réponse se dégrade.
RAPPEL_K = 3


def domaine(cle: str = None) -> DomaineAssistant:
    """Domaine déclaré, ou le domaine par défaut si la clé est inconnue (fail-safe)."""
    return _PAR_CLE.get((cle or '').strip().lower(), _PAR_CLE[DOMAINE_DEFAUT])


def domaines_pour_ui() -> list:
    """Options du sélecteur de domaine — dérivées du registre, jamais réécrites à la main."""
    return [{'value': d.cle, 'label': d.libelle, 'help': d.aide} for d in DOMAINES]


def consigne_de_role(cle: str = None) -> str:
    """
    Texte du skill de rôle pour ce domaine — '' si le fichier est absent.

    Fail-safe absolu : un skill manquant doit dégrader l'assistant, jamais l'empêcher de
    répondre. Le prompt système de base reste posé par l'appelant.
    """
    d = domaine(cle)
    try:
        from wama.common.utils.prompt_skills import load_skill
        return load_skill(d.skill) or ''
    except Exception:
        logger.debug("[assistant_skills] skill de rôle indisponible : %s", d.skill, exc_info=True)
        return ''


def annonce_des_competences(sauf: str = None) -> str:
    """
    Ligne d'annonce injectée au prompt système : quelles compétences existent, et comment
    en charger une.

    POURQUOI ANNONCER PLUTÔT QUE TOUT CHARGER. Concaténer les quatre skills coûterait
    plusieurs milliers de jetons à CHAQUE tour, sur des modèles locaux à fenêtre étroite —
    et noierait la question de l'utilisateur. On annonce donc leur existence en quelques
    lignes, et l'assistant charge celui dont il a besoin, quand il en a besoin.

    ⚠ LE CHOIX APPARTIENT À L'ASSISTANT, pas à la surface qui l'appelle (arbitrage Fabien,
    2026-08-21). Un adaptateur de canal ne doit pas décider du domaine : il ne connaît que
    le protocole. Déduire le domaine du nom d'un salon serait de surcroît faux la plupart
    du temps — un canal porte le nom d'un projet de recherche, pas d'une discipline.
    """
    lignes = [f"- `{d.cle}` : {d.aide}" for d in DOMAINES if d.cle != (sauf or '')]
    if not lignes:
        return ''
    return ("\n\nSpecialised competences you can load with the `charger_competence` tool "
            "when the request calls for one (do it BEFORE answering, and only once per "
            "topic):\n" + "\n".join(lignes))


def contexte_laboratoire(user, question: str, cle: str = None) -> str:
    """
    Extraits du corpus du laboratoire pertinents pour la question — '' si rien.

    C'EST CE QUI REND L'ASSISTANT « DU LABO » PLUTÔT QUE GÉNÉRIQUE. Sans ce rappel,
    « propose-moi un logo pour le labo » oblige l'utilisateur à redécrire son laboratoire à
    chaque demande — ce qui vide le RAG de sa raison d'être.

    Trois gardes, toutes délibérées :
      • DÉCLARÉ — seuls les domaines marqués `rag=True` paient la recherche ;
      • DATA-GATED — sans extrait pertinent, on rend '' et le prompt sort INCHANGÉ. On
        n'injecte jamais de bruit : un contexte hors-sujet dégrade plus qu'il n'aide ;
      • FAIL-SAFE — toute panne du rappel rend '', jamais une exception. Le RAG est un
        bonus de contexte, pas une dépendance de la conversation.

    Le scoping est celui de `recall()` (`scoped_visible_q`) : l'utilisateur ne voit que ce
    qu'il a le droit de voir. Rien à re-garder ici.
    """
    if not domaine(cle).rag or not (question or '').strip() or user is None:
        return ''

    try:
        from wama.common.memory.store import recall
        hits = recall(question, user=user, k=RAPPEL_K,
                      include_rag=True, include_memory=True)
    except Exception:
        logger.debug("[assistant_skills] rappel de contexte indisponible", exc_info=True)
        return ''

    extraits = []
    for h in hits or []:
        obj = getattr(h, 'obj', None)
        contenu = (getattr(obj, 'content', '') or '').strip()
        if not contenu:
            continue
        # La RÉFÉRENCE accompagne l'extrait : un contexte sans provenance n'est pas
        # vérifiable par l'utilisateur, et l'assistant doit pouvoir la citer.
        ref = (getattr(obj, 'source_id', '')
               or getattr(obj, 'subject', '')
               or f"memoire#{getattr(obj, 'pk', '?')}")
        extraits.append(f"[{ref}] {contenu}")

    if not extraits:
        return ''

    return ("\n\nLaboratory context (retrieved from the lab corpus — cite the reference "
            "when you use it):\n" + "\n".join(f"- {e}" for e in extraits))
