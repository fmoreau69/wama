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


def owned_or_404(model, user, **kwargs):
    """
    Objet que `user` a le droit de MODIFIER — aujourd'hui : le sien, point.

    À utiliser dans TOUS les chemins mutants : démarrer, arrêter, supprimer, dupliquer,
    enregistrer des paramètres. Une card partagée n'est donc jamais modifiable par le
    destinataire, même si une vue de lecture la lui a montrée.
    """
    return get_object_or_404(model.objects.owned_by(user), **kwargs)
