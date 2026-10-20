"""
Les SKILLS DE PROMPT d'un compte — les gestes, un seul lieu (`ROADMAP §29`, 2026-10-20).

Décision de Fabien (piste 2) : un skill d'utilisateur a sa LIGNE (`common.PromptSkill`), que le
résolveur lit avant les fichiers (`prompt_skills.resolve_skill`). Il suit la route commune de
tout ce qui entre dans WAMA, la même que le thème d'une charte (`common.UserTheme`) :

- il naît PRIVÉ à son auteur ;
- il se PARTAGE par une portée, par le service commun (`services/sharing.partager`) ; un compte
  qui le voit peut le COPIER dans les siens — un skill partagé ne s'impose à personne (le RAG
  suit la même règle : l'utilisateur OPTE pour un niveau plus large, `WAMA_MEMORY`) ;
- un ADMINISTRATEUR seul le rend SYSTÈME (`ownership.promote_owned_row`, décision b), et jamais
  par-dessus un fichier du dépôt : remplacer `prompt_skills/<nom>.md` est un geste de
  développement (modifier le fichier), pas une promotion.

Les lectures passent par le filtre des catalogues (`catalogue_visible_to` : système, publics, les
siens, sa portée ; tout pour l'administrateur, décision c).
"""
from __future__ import annotations

#: Plafond du texte d'un skill : un system prompt, pas un document.
MAX_TEXT = 20000


class SkillRefused(Exception):
    """Refus MOTIVÉ — le motif est destiné à l'utilisateur."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def visible_skills(user):
    """Les lignes `PromptSkill` que `user` voit dans le catalogue."""
    from wama.common.models import PromptSkill
    return PromptSkill.objects.catalogue_visible_to(user).select_related(
        'owner', 'scope_org_unit', 'scope_project')


def _check(name: str, text: str):
    from wama.common.utils.prompt_skills import is_valid_name
    name, text = (name or '').strip(), (text or '').strip()
    if not is_valid_name(name):
        raise SkillRefused("Nom invalide : minuscules, chiffres et tirets (« imager-image », "
                           "« composer », « default-generative »), 64 caractères au plus.")
    if not text:
        raise SkillRefused("La consigne est vide.")
    if len(text) > MAX_TEXT:
        raise SkillRefused(f"La consigne dépasse {MAX_TEXT} caractères.")
    return name, text


def create(user, name: str, text: str, *, copied_from: str = ''):
    """Un skill PRIVÉ à `user`. Un seul par nom et par compte."""
    from wama.common.models import PromptSkill
    name, text = _check(name, text)
    if PromptSkill.objects.filter(owner=user, name=name).exists():
        raise SkillRefused(f"Vous avez déjà un skill « {name} » : modifiez-le.")
    source = {'created_by': user.get_username()}
    if copied_from:
        source['copied_from'] = copied_from
    return PromptSkill.objects.create(owner=user, name=name, text=text, source=source)


def _row(user, pk):
    row = visible_skills(user).filter(pk=pk if str(pk).isdigit() else -1).first()
    if row is None:
        raise SkillRefused("Skill inconnu.", status=404)
    return row


def update(user, pk, text: str):
    """Seul son auteur modifie un skill — le partage est en LECTURE (`owned_by`)."""
    row = _row(user, pk)
    if row.owner_id != getattr(user, 'pk', None):
        raise SkillRefused("Seul son auteur modifie ce skill ; copiez-le pour en faire le vôtre.",
                           status=403)
    _name, text = _check(row.name, text)
    row.text = text
    row.save(update_fields=['text', 'updated_at'])
    return row


def share(user, pk, scope: str):
    """La portée (`sharing.scope_choices` : `private`, `public`, `unit:<id>`, `project:<id>`), par
    le service commun — qui revérifie que `user` est le propriétaire."""
    from wama.common.services.sharing import RefusDePartage, share_scope
    row = _row(user, pk)
    try:
        return share_scope(user, row, scope)
    except RefusDePartage as exc:
        raise SkillRefused(str(exc), status=403)


def copy(user, *, pk=None, name: str = ''):
    """Une copie PRIVÉE dans les skills de `user` : d'un skill qu'il voit (`pk`), ou d'un skill
    SYSTÈME par son nom (le fichier du dépôt, ou une ligne promue) — « personnaliser »."""
    from wama.common.utils.prompt_skills import skills_catalog
    if pk is not None:
        row = _row(user, pk)
        who = row.owner.get_username() if row.owner_id else 'système'
        return create(user, row.name, row.text, copied_from=f'{who}:{row.name}')
    text = skills_catalog().get((name or '').strip())
    if not text:
        raise SkillRefused(f"Aucun skill système « {name} ».", status=404)
    return create(user, name, text, copied_from=f'système:{name}')


def delete(user, pk):
    """Son auteur, ou un administrateur (`ownership.may_remove`)."""
    from wama.common.manifests.ownership import may_remove
    row = _row(user, pk)
    if not may_remove(user, row):
        raise SkillRefused("Seul son auteur, ou un administrateur, le retire.", status=403)
    row.delete()


def promote(user, pk):
    """Rend le skill SYSTÈME — un administrateur seul (décision b). Refusé s'il porte le nom
    d'un skill système existant : un fichier du dépôt se modifie, il ne se remplace pas ici."""
    from wama.accounts.permissions import is_admin_tier
    from wama.common.manifests.ownership import promote_by
    from wama.common.models import PromptSkill
    from wama.common.utils.prompt_skills import file_skill_names
    row = _row(user, pk)
    # Les frontières PROPRES au skill (un seul système par nom), puis le geste commun
    # (`ownership.promote_by` : un administrateur, une ligne qui a un auteur).
    if is_admin_tier(user) and row.owner_id is not None:
        if row.name in file_skill_names():
            raise SkillRefused(f"« {row.name} » est un fichier du dépôt (prompt_skills/{row.name}.md) "
                               f": le remplacer est un geste de développement, pas une promotion.")
        if PromptSkill.objects.filter(owner__isnull=True, name=row.name).exists():
            raise SkillRefused(f"Un skill système « {row.name} » existe déjà.")
    try:
        return promote_by(user, row, 'skill')
    except PermissionError as exc:
        raise SkillRefused(str(exc), status=403)
    except ValueError as exc:
        raise SkillRefused(str(exc))


def _page_url() -> str:
    from django.urls import reverse
    return reverse('common:skills_catalog')


def request_promotion(user, pk):
    """« Demander la promotion » — son auteur ; les administrateurs sont prévenus
    (`ownership.request_promotion`)."""
    from wama.common.manifests.ownership import request_promotion as request
    row = _row(user, pk)
    try:
        return request(user, row, 'skill', _page_url())
    except PermissionError as exc:
        raise SkillRefused(str(exc), status=403)
    except ValueError as exc:
        raise SkillRefused(str(exc))


def refuse_promotion(user, pk):
    """Un administrateur refuse la promotion demandée ; l'auteur est prévenu."""
    from wama.common.manifests.ownership import refuse_promotion as refuse
    row = _row(user, pk)
    try:
        return refuse(user, row, 'skill', _page_url())
    except PermissionError as exc:
        raise SkillRefused(str(exc), status=403)
    except ValueError as exc:
        raise SkillRefused(str(exc))


def as_dict(row, user) -> dict:
    """Ce que la page montre d'une ligne : sa provenance et ses gestes, par la lecture commune des
    lignes portées (`ownership.provenance_of`), plus ce qui est propre au skill."""
    from wama.common.manifests.ownership import provenance_of
    facts = provenance_of(row, user)
    return {'pk': row.pk, 'name': row.name, 'text': row.text,
            'lines': len(row.text.splitlines()), **facts,
            'can_edit': facts['mine'], 'can_copy': not facts['mine']}
