"""
Les MOTS-CLÉS DE PROMPT d'un compte — les gestes, un seul lieu (`ROADMAP §29`, 2026-10-27 ;
Fabien : « aligne aussi les mots-clés »).

La route des skills de prompt (`common/services/user_skills`), appliquée à `PromptKeyword` :

- le tronc commun est SYSTÈME (sans auteur, public, `seed_prompt_keywords`) ;
- un mot-clé d'auteur naît PRIVÉ ; il se PARTAGE par une portée (`common/services/sharing`) ; un
  compte qui le voit le COPIE dans les siens — un mot-clé partagé ne s'impose à personne : la
  palette sous un champ-prompt ne montre que le système et les siens (`palette_keywords`) ;
- un ADMINISTRATEUR seul le rend système (`ownership.promote_element`).

Le mode gestion de la médiathèque voit ce que voit le filtre des catalogues (`catalogue_rows`).
"""
from __future__ import annotations

from django.db.models import Q

MAX_TEXT = 120


class KeywordRefused(Exception):
    """Refus MOTIVÉ — le motif est destiné à l'utilisateur."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def palette_keywords(user, domain: str = ''):
    """Ce que la palette propose sous un champ-prompt : le système et les siens."""
    from .models import PromptKeyword
    mine = Q(owner=user) if getattr(user, 'pk', None) else Q(pk__in=[])
    rows = PromptKeyword.objects.filter(Q(owner__isnull=True) | mine)
    return rows.filter(Q(domain='') | Q(domain=domain)) if domain else rows


def catalogue_rows(user, domain: str = ''):
    """Ce que le mode GESTION montre : le filtre des catalogues (système, publics, les siens, sa
    portée ; tout pour l'administrateur)."""
    from .models import PromptKeyword
    rows = PromptKeyword.objects.catalogue_visible_to(user).select_related(
        'owner', 'scope_org_unit', 'scope_project')
    return rows.filter(Q(domain='') | Q(domain=domain)) if domain else rows


def create(user, text: str, category: str, *, copied_from: str = '', domain: str = ''):
    """Un mot-clé PRIVÉ à `user` — le même mot dans la même catégorie n'est créé qu'une fois."""
    from .models import PromptKeyword
    text = (text or '').strip()[:MAX_TEXT]
    if not text:
        raise KeywordRefused('Texte vide')
    if category not in dict(PromptKeyword.CATEGORY_CHOICES):
        category = 'style'
    source = {'created_by': user.get_username()}
    if copied_from:
        source['copied_from'] = copied_from
    row, _ = PromptKeyword.objects.get_or_create(
        owner=user, category=category, text=text,
        defaults={'source': source, 'domain': domain})
    return row


def _row(user, pk):
    row = catalogue_rows(user).filter(pk=pk if str(pk).isdigit() else -1).first()
    if row is None:
        raise KeywordRefused('Mot-clé inconnu.', status=404)
    return row


def share(user, pk, scope: str):
    from wama.common.services.sharing import RefusDePartage, share_scope
    row = _row(user, pk)
    try:
        return share_scope(user, row, scope)
    except RefusDePartage as exc:
        raise KeywordRefused(str(exc), status=403)


def copy(user, pk):
    """Une copie PRIVÉE, dans les mots-clés de `user`, d'un mot-clé qu'il voit."""
    row = _row(user, pk)
    who = row.owner.get_username() if row.owner_id else 'système'
    return create(user, row.text, row.category, copied_from=f'{who}:{row.text}', domain=row.domain)


def delete(user, pk):
    """Son auteur, ou un administrateur — jamais le tronc commun par cette voie."""
    from wama.common.manifests.ownership import may_remove
    row = _row(user, pk)
    if row.owner_id is None or not may_remove(user, row):
        raise KeywordRefused('Seul son auteur, ou un administrateur, le retire.', status=403)
    row.delete()


def promote(user, pk):
    """Le rend SYSTÈME — un administrateur seul ; refusé si le tronc commun a déjà ce mot dans
    cette catégorie (la contrainte d'unicité le refuserait sans le dire)."""
    from wama.accounts.permissions import is_admin_tier
    from wama.common.manifests.ownership import promote_element
    from .models import PromptKeyword
    row = _row(user, pk)
    if is_admin_tier(user) and row.owner_id is not None and PromptKeyword.objects.filter(
            owner__isnull=True, category=row.category, text=row.text).exists():
        raise KeywordRefused(f'Le tronc commun a déjà « {row.text} ».')
    try:
        return promote_element(user, row)
    except PermissionError as exc:
        raise KeywordRefused(str(exc), status=403)
    except ValueError as exc:
        raise KeywordRefused(str(exc))


def as_dict(row, user) -> dict:
    """Le mot-clé tel que la palette le lit (`to_dict`), sa provenance et ses gestes en plus
    (`ownership.provenance_of`)."""
    from wama.common.manifests.ownership import provenance_of
    facts = provenance_of(row, user)
    # Copier un mot du tronc commun le doublerait dans la palette : on ne copie que celui d'autrui.
    return {**row.to_dict(), **facts, 'can_copy': not facts['mine'] and not facts['system']}
