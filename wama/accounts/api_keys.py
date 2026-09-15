"""
Clés d'API PERSONNELLES des fournisseurs LLM — lecture et résolution (ROADMAP §8d Phase 3, étape 4a).

Les fournisseurs NE sont PAS déclarés ici : ce sont les sources `external_sources` de type `llm` qui
portent une variable de clé (Albert, API Anthropic, abonnement Claude Code). Ce module ne fait que
dire, pour un utilisateur, quelles clés il a posées et laquelle utiliser.

RÈGLE DE RÉSOLUTION (Fabien, 2026-09-15) : un utilisateur n'utilise QUE sa propre clé — pas de repli
sur la clé d'instance du `.env`, sinon les quotas ne se répartissent plus. La clé d'instance ne sert
qu'aux usages SANS utilisateur (rôles wama-dev-ai en ligne de commande, tâches planifiées).
"""
from __future__ import annotations

from wama.common import external_sources


def llm_sources(user=None) -> list:
    """Les fournisseurs LLM qui demandent une clé, dans l'ordre de déclaration.

    Une source `developer_only` (abonnement Claude Code : accès au dépôt) n'est proposée qu'à un
    développeur — même prédicat que la garde de l'abonnement.
    """
    from wama.accounts.permissions import is_developer
    return [s for s in external_sources.SOURCES
            if s.kind == 'llm' and s.api_key_env
            and (not s.developer_only or is_developer(user))]


def is_llm_source(key: str, user=None) -> bool:
    return any(s.key == key for s in llm_sources(user))


def configured_sources(user) -> set:
    """Clés des sources pour lesquelles `user` a posé une clé."""
    from wama.accounts.models import UserApiKey
    return set(UserApiKey.objects.filter(user=user).exclude(api_key='')
               .values_list('source', flat=True))


def key_for(user, source: str) -> str:
    """La clé à utiliser pour `source` : celle de l'utilisateur, ou celle de l'instance SANS
    utilisateur. '' si aucune — jamais d'exception, l'appelant refuse avec un motif lisible."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return external_sources.api_key(source)
    from wama.accounts.models import UserApiKey
    row = UserApiKey.objects.filter(user=user, source=source).first()
    return row.api_key if row else ''


def listing(user) -> list:
    """Même forme que la liste des connecteurs de la médiathèque (`api_provider_keys`) : le volet
    du profil rend les deux avec le même code. Jamais la clé elle-même."""
    configured = configured_sources(user)
    return [{
        'slug': s.key,
        'name': s.label,
        'api_key_label': s.api_key_label or "Clé d'API",
        'api_key_help_url': s.api_key_help_url,
        'has_key': s.key in configured,
    } for s in llm_sources(user)]
