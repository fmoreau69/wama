"""
Accès à un objet partageable depuis une vue — DEUX chemins nommés, et deux seulement.

Pourquoi ce module : les droits par objet fuient dans toutes les requêtes. Un
`get_object_or_404(Model, pk=pk, user=user)` écrit machinalement dans une nouvelle vue
désactive le partage pour cette route, sans erreur, sans test rouge, sans trace. En nommant les
deux intentions, l'oubli redevient visible à la relecture — et **mesurable** : la grille de
conformité peut compter les vues qui passent par ici plutôt que d'espérer l'adoption
(PROFILES_PERMISSIONS §7.4 ; c'est ce qui a manqué à `ScopedVisibility`, écrit puis oublié sur
2 modèles pendant des mois).

Règle : **lecture → `visible_or_404`, mutation → `owned_or_404`**. Le partage est donc en
lecture seule par construction, et le restera jusqu'à `ObjectGrant` (§7.3) — aucune vue ne peut
accorder l'écriture par distraction.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404


def visible_or_404(model, user, **kwargs):
    """
    Objet que `user` a le droit de VOIR : le sien, ou partagé avec lui (unité/projet/public).

    À utiliser dans TOUS les chemins de lecture : détail, progression, téléchargement, aperçu.
    Le modèle doit hériter de `ScopedVisibility` et exposer `ScopedManager`.
    """
    return get_object_or_404(model.objects.visible_to(user), **kwargs)


def listable_by(queryset, user):
    """Ce que `user` a le droit de LISTER : `visible_to`, sauf pour le compte de service anonyme.

    ⚠ Le compte anonyme est une VRAIE ligne `User` (authentifiée : tous les visiteurs non
    connectés la partagent), et `scoped_visible_q` pose `Q(visibility='public')` pour tout le
    monde. Sans cette règle, n'importe quel visiteur hériterait des éléments publics de tout le
    parc, avec leurs chemins de fichier. Le compte anonyme n'est pas une personne : il ne liste
    que ce qu'il possède.

    Domicile UNIQUE de la règle depuis le 2026-09-22 : elle vivait en deux exemplaires
    (liste de la médiathèque, voix de clonage), écrits le même jour par la même session.
    """
    from wama.accounts.views import ANONYMOUS_USERNAME
    if getattr(user, 'username', '') == ANONYMOUS_USERNAME:
        return queryset.filter(user=user)
    return queryset.visible_to(user)


def owned_or_404(model, user, **kwargs):
    """
    Objet que `user` a le droit de MODIFIER — aujourd'hui : le sien, point.

    À utiliser dans TOUS les chemins mutants : démarrer, arrêter, supprimer, enregistrer des
    paramètres. Une card partagée n'est donc jamais modifiable par le destinataire, même si une
    vue de lecture la lui a montrée.
    """
    return get_object_or_404(model.objects.owned_by(user), **kwargs)


def editable_or_404(model, user, *, trace: str = '', **kwargs):
    """
    Objet que `user` peut ÉDITER : le sien, ou un élément sur lequel il COLLABORE.

    Décisions de Fabien (`WAMA_COLLABORATION §3bis`, E1-E5, 2026-10-03) : la collaboration
    s'accorde à une PERSONNE nommée (`ObjectGrant` `collaborate` accordé, lu sur l'élément et sur
    son lot) ; « éditer » = enregistrer les réglages, lancer/relancer/arrêter, corriger le résultat.
    ⚠ La SUPPRESSION, le PARTAGE et le TRANSFERT restent à `owned_or_404` : ils ne passent jamais
    ici (E2). Le droit est relu à CHAQUE appel — un retrait a effet immédiat (E5).

    `trace` (signal du journal `RunOutcome`, ex. 'regle') : le geste d'un COLLABORATEUR y est noté
    (E4 — « le dernier enregistrement gagne, tracé ») ; rien pour le propriétaire. À ne passer que
    sur une ÉCRITURE (POST), pas sur une lecture de la même vue.
    """
    obj = get_object_or_404(listable_by(model.objects.all(), user), **kwargs)
    if getattr(obj, 'user_id', None) == getattr(user, 'pk', None):
        return obj
    from wama.common.services.access_requests import collaboration_grant, trace_collaborator
    if collaboration_grant(user, obj) is None:
        from django.http import Http404
        raise Http404('élément non modifiable')
    if trace:
        trace_collaborator(user, obj, trace)
    return obj


def can_edit(user, obj) -> bool:
    """Même règle qu'`editable_or_404`, pour un objet déjà en main (cards, gabarits, tâches)."""
    if getattr(obj, 'user_id', None) == getattr(user, 'pk', None):
        return True
    from wama.common.services.access_requests import collaboration_grant
    return collaboration_grant(user, obj) is not None


def duplicable_or_404(model, user, **kwargs):
    """
    Objet que `user` peut DUPLIQUER : tout ce qu'il peut voir (le sien, ou partagé avec lui).

    Décision de Fabien (`WAMA_COLLABORATION §3bis`, mode lecture : « dupliquer ⧉ → sa copie » ;
    construit le 2026-10-01). Dupliquer ne modifie pas la source : la copie est un objet NEUF qui
    appartient à celui qui duplique — `queue_duplication.duplicate_instance(for_user=…)` en fait
    son objet (propriétaire, visibilité privée, hors du lot d'autrui, fichiers copiés chez lui).
    Le compte anonyme ne duplique que ce qu'il possède (`listable_by`).
    """
    return get_object_or_404(listable_by(model.objects.all(), user), **kwargs)
