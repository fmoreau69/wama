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


#: Les familles qui ont DÉJÀ leur propre écran et leur propre stockage de clés.
#: ⚠ `media` : les connecteurs de la médiathèque rangent la leur dans
#: `media_library.UserProviderConfig` (chiffrée elle aussi) et la saisissent dans leur section
#: du profil. Les faire entrer ici les afficherait DEUX FOIS, chacune écrivant ailleurs. Les
#: réunir est un chantier de FUSION — deux domiciles pour une même notion —, pas un ajout.
KINDS_WITH_THEIR_OWN_SCREEN = ('media',)


def keyed_sources(user=None, kinds: tuple = ()) -> list:
    """Les sources dont la clé se pose AU PROFIL, dans l'ordre de déclaration.

    Le critère est `user_key` — le drapeau qui dit précisément « cette clé est celle de
    chacun ». ⚠ C'était une LISTE DE FAMILLES (`('llm', 'recherche')`) jusqu'au 2026-09-27 :
    elle a fallu l'élargir à chaque famille nouvelle, et le jour où un corpus de voix a
    demandé une clé par utilisateur (Mozilla Data Collective), il n'aurait rien affiché —
    silencieusement, puisqu'une liste vide n'est pas une erreur. *Une énumération à tenir à
    jour finit par être en retard ; un drapeau déclaré à la source, jamais.*

    `kinds` reste accepté pour RESTREINDRE (c'est ce dont `llm_sources` a besoin), jamais pour
    élargir. Une source `developer_only` (abonnement Claude Code : accès au dépôt) n'est
    proposée qu'à un développeur — même prédicat que la garde de l'abonnement.
    """
    from wama.accounts.permissions import is_developer
    return [s for s in external_sources.SOURCES
            if s.user_key
            and s.kind not in KINDS_WITH_THEIR_OWN_SCREEN
            and (not kinds or s.kind in kinds)
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


def download_token(user, source: str):
    """Le jeton d'un TÉLÉCHARGEMENT chez `source` (2026-09-27, HuggingFace) — même règle que
    `key_for`, dite dans la forme que les bibliothèques de téléchargement comprennent :

      • lancé par quelqu'un → SON jeton, ou `False` s'il n'en a pas posé : « aucun jeton »
        explicite, pour que `huggingface_hub` ne retombe PAS sur celui de l'instance. Un dépôt
        qui en exige un est alors refusé, avec un message qui renvoie au profil ;
      • sans utilisateur (synchronisation, tâche planifiée, ligne de commande) → `None` : la
        bibliothèque lit la variable d'instance (`HF_TOKEN`).
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    return key_for(user, source) or False


def listing(user, kinds: tuple = ()) -> list:
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
