"""
Clés d'API PERSONNELLES — lecture et résolution (ROADMAP §8d Phase 3, étape 4a).

Les fournisseurs NE sont PAS déclarés ici : ce sont les sources `external_sources` qui portent une
variable de clé. Ce module ne fait que dire, pour un utilisateur, quelles clés il a posées et
laquelle utiliser.

⚠ Ce module ne connaissait QUE les sources `llm` jusqu'au 2026-09-26 — la famille était écrite en
dur dans `llm_sources`. Quand les MOTEURS DE RECHERCHE sont devenus des sources à clé de chacun
(décision de Fabien), ouvrir le mécanisme a consisté à RETIRER cette spécificité, pas à en ajouter
une : les familles concernées se déclarent (`KEYED_KINDS`), et le profil rend les mêmes champs
pour toutes. *Une brique qui nomme une famille en dur devra être modifiée à chaque famille ; une
brique qui lit le registre, jamais.*

RÈGLE DE RÉSOLUTION (Fabien, 2026-09-15) : un utilisateur n'utilise QUE sa propre clé — pas de repli
sur la clé d'instance du `.env`, sinon les quotas ne se répartissent plus. La clé d'instance ne sert
qu'aux usages SANS utilisateur (rôles wama-dev-ai en ligne de commande, tâches planifiées).
"""
from __future__ import annotations

from wama.common import external_sources


#: Les familles de sources dont la clé se pose au PROFIL, dans l'ordre d'affichage.
#: ⚠ `media` n'y est PAS : les connecteurs de la médiathèque ont leur propre stockage
#: (`media_library.UserProviderConfig`, chiffré lui aussi) et leur propre écran. Les y faire
#: entrer est un chantier de FUSION — deux domiciles pour une même notion —, pas un ajout ;
#: tant qu'il n'est pas fait, déclarer `media` ici rendrait les clés média en double.
KEYED_KINDS = ('llm', 'recherche')


def keyed_sources(user=None, kinds: tuple = KEYED_KINDS) -> list:
    """Les sources qui demandent une clé personnelle, dans l'ordre de déclaration.

    Une source entre ici si elle porte une clé d'INSTANCE (`api_key_env`) ou une clé de CHACUN
    (`user_key`) — les deux disent « cette source a besoin d'une clé », à des étages différents.
    Une source `developer_only` (abonnement Claude Code : accès au dépôt) n'est proposée qu'à un
    développeur — même prédicat que la garde de l'abonnement.
    """
    from wama.accounts.permissions import is_developer
    return [s for s in external_sources.SOURCES
            if s.kind in kinds and (s.api_key_env or s.user_key)
            and (not s.developer_only or is_developer(user))]


def llm_sources(user=None) -> list:
    """Les fournisseurs LLM seuls — la résolution de modèle n'a que faire d'un moteur de
    recherche. Conservé pour les appelants qui parlent de LLM (`is_llm_source` ci-dessous)."""
    return keyed_sources(user, kinds=('llm',))


def is_llm_source(key: str, user=None) -> bool:
    return any(s.key == key for s in llm_sources(user))


def is_keyed_source(key: str, user=None) -> bool:
    """La source accepte-t-elle une clé personnelle ? (garde de la vue d'enregistrement)"""
    return any(s.key == key for s in keyed_sources(user))


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


def listing(user, kinds: tuple = KEYED_KINDS) -> list:
    """Même forme que la liste des connecteurs de la médiathèque (`api_provider_keys`) : le volet
    du profil rend les deux avec le même code. Jamais la clé elle-même.

    `kind` accompagne chaque ligne pour que le profil puisse les GROUPER par famille (« LLM »,
    « Recherche web ») sans savoir laquelle existe : le libellé vient du registre.
    """
    configured = configured_sources(user)
    return [{
        'slug': s.key,
        'name': s.label,
        'kind': s.kind,
        'kind_label': external_sources.KINDS.get(s.kind, s.kind),
        'api_key_label': s.api_key_label or "Clé d'API",
        'api_key_help_url': s.api_key_help_url,
        'has_key': s.key in configured,
    } for s in keyed_sources(user, kinds)]
