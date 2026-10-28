"""
Les PRONONCIATIONS d'un compte — le lexique de la voix, les gestes, un seul lieu (`ROADMAP §29`,
2026-10-27 ; Fabien : « Oui, lance-le […] Ok pour ta recommandation »).

Le lexique SYSTÈME est le fichier du dépôt (`common/tts/pronunciations.json`, lu par
`tts_text.lexicon`) ; une entrée d'utilisateur a sa LIGNE (`common.Pronunciation`). Même route
que les skills de prompt (`services/user_skills`) et les thèmes de charte :

- elle naît PRIVÉE à son auteur, et pour lui elle passe devant l'entrée système du même terme ;
- elle se PARTAGE par une portée (`services/sharing`) ; un compte qui la voit peut la COPIER dans
  les siennes — une prononciation partagée ne s'impose à personne (la règle du skill et du RAG) ;
- un ADMINISTRATEUR seul la rend SYSTÈME (`ownership.promote_element`), jamais par-dessus une
  entrée du fichier : corriger le fichier est un geste de développement.

La voix tourne dans un AUTRE processus, sans Django (`common/tts/service.py`) : `lexicon_for` résout ici
ce qu'elle doit dire en plus du fichier, et le client du service le joint à la demande
(`tts.service_client.tts_via_service`, `options['lexicon']`).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_TERM = 80
MAX_SPELLING = 120
MAX_PHONEMES = 200


class PronunciationRefused(Exception):
    """Refus MOTIVÉ — le motif est destiné à l'utilisateur."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def languages() -> list:
    """Les langues de VOIX (`tts.constants.LANGUAGE_CHOICES`) : `[(code, libellé)]`."""
    from wama.common.tts.constants import LANGUAGE_CHOICES
    return list(LANGUAGE_CHOICES)


def visible_pronunciations(user):
    """Les lignes `Pronunciation` que `user` voit dans le catalogue."""
    from wama.common.models import Pronunciation
    return Pronunciation.objects.catalogue_visible_to(user).select_related(
        'owner', 'scope_org_unit', 'scope_project')


def lexicon_for(user, language: str) -> dict:
    """Ce que la voix dit EN PLUS du fichier pour `user` en `language` : {terme : entrée} — les
    lignes système (promues), puis les siennes, qui passent devant. Jamais celles qu'on lui
    partage : copiées, elles deviennent les siennes. {} si rien, ou si la base ne répond pas — la
    voix dit alors le fichier seul, elle ne se tait jamais pour un lexique."""
    from django.db.models import Q
    try:
        from wama.common.models import Pronunciation
        mine = Q(owner=user) if getattr(user, 'pk', None) else Q(pk__in=[])
        rows = (Pronunciation.objects.filter(language=language or 'fr')
                .filter(Q(owner__isnull=True) | mine))
        # Le système d'abord, les siennes ensuite : la dernière écrite gagne (`tts_text.lexicon`).
        entries = {}
        for row in sorted(rows, key=lambda r: r.owner_id is not None):
            entry = row.as_entry()
            if entry:
                entries[row.term] = entry
        return entries
    except Exception as exc:
        logger.debug('lexique de prononciation du compte non résolu : %s', exc)
        return {}


def tried_entry(user, pk) -> dict:
    """{terme : entrée} d'UNE ligne que `user` voit — pour l'écouter avant de l'adopter ; {}
    sinon (clé absente, illisible, ou ligne qu'il ne voit pas)."""
    if not str(pk or '').isdigit():
        return {}
    row = visible_pronunciations(user).filter(pk=pk).first()
    return {row.term: row.as_entry()} if row is not None and row.as_entry() else {}


#: La phrase dans laquelle on ÉCOUTE un terme : seul, un mot ne s'entend pas comme dans le
#: discours. Langue de voix sans phrase : le terme seul.
LISTEN_SENTENCES = {'fr': 'Je dis {term}, dans une phrase.', 'en': 'I say {term}, in a sentence.'}


def listen_text(term: str, language: str) -> str:
    return LISTEN_SENTENCES.get(language, '{term}.').format(term=term)


def _vocabulary():
    """Le vocabulaire de Kokoro (un phonème hors de lui est EFFACÉ sans erreur), ou None si la
    librairie n'est pas dans ce venv — les phonèmes ne sont alors pas contrôlés ici."""
    try:
        from kokoro_onnx.tokenizer import Tokenizer
    except Exception:
        return None
    return Tokenizer().vocab


def _check(term: str, language: str, spelling: str, phonemes: str):
    term, spelling, phonemes = ((term or '').strip(), (spelling or '').strip(),
                                (phonemes or '').strip())
    language = (language or 'fr').strip()
    if not term or len(term) > MAX_TERM or '\n' in term or not any(c.isalnum() for c in term):
        raise PronunciationRefused(f"Terme invalide : une à {MAX_TERM} lettres, chiffres ou signes, "
                                   "sur une ligne (« git », « Hugging Face », « C++ »).")
    if language not in dict(languages()):
        raise PronunciationRefused(f"Langue de voix inconnue : {language!r}.")
    if not (spelling or phonemes):
        raise PronunciationRefused("Donnez une orthographe à dire (« guite »), ou des phonèmes.")
    if len(spelling) > MAX_SPELLING or '\n' in spelling:
        raise PronunciationRefused(f"L'orthographe dépasse {MAX_SPELLING} caractères.")
    if len(phonemes) > MAX_PHONEMES or '\n' in phonemes:
        raise PronunciationRefused(f"Les phonèmes dépassent {MAX_PHONEMES} caractères.")
    vocab = _vocabulary() if phonemes else None
    unknown = sorted({c for c in phonemes.replace('^', '') if c not in vocab}) if vocab else []
    if unknown:
        hint = " (le g s'écrit ɡ, U+0261)" if 'g' in unknown else ''
        raise PronunciationRefused(f"Phonèmes inconnus de la voix, qui les effacerait : "
                                   f"{' '.join(unknown)}{hint}.")
    return term, language, spelling, phonemes


def create(user, term: str, language: str = 'fr', spelling: str = '', phonemes: str = '', *,
           copied_from: str = ''):
    """Une prononciation PRIVÉE à `user`. Une seule par terme (casse indifférente) et par langue."""
    from wama.common.models import Pronunciation
    term, language, spelling, phonemes = _check(term, language, spelling, phonemes)
    if Pronunciation.objects.filter(owner=user, language=language, term__iexact=term).exists():
        raise PronunciationRefused(f"Vous avez déjà une prononciation de « {term} » : modifiez-la.")
    source = {'created_by': user.get_username()}
    if copied_from:
        source['copied_from'] = copied_from
    return Pronunciation.objects.create(owner=user, term=term, language=language,
                                        spelling=spelling, phonemes=phonemes, source=source)


def _row(user, pk):
    row = visible_pronunciations(user).filter(pk=pk if str(pk).isdigit() else -1).first()
    if row is None:
        raise PronunciationRefused("Prononciation inconnue.", status=404)
    return row


def update(user, pk, spelling: str = '', phonemes: str = ''):
    """Seul son auteur modifie une prononciation — le partage est en LECTURE."""
    row = _row(user, pk)
    if row.owner_id != getattr(user, 'pk', None):
        raise PronunciationRefused("Seul son auteur la modifie ; copiez-la pour en faire la vôtre.",
                                   status=403)
    _term, _language, row.spelling, row.phonemes = _check(row.term, row.language, spelling,
                                                          phonemes)
    row.save(update_fields=['spelling', 'phonemes', 'updated_at'])
    return row


def share(user, pk, scope: str):
    """La portée (`sharing.scope_choices`), par le service commun — qui revérifie l'auteur."""
    from wama.common.services.sharing import RefusDePartage, share_scope
    row = _row(user, pk)
    try:
        return share_scope(user, row, scope)
    except RefusDePartage as exc:
        raise PronunciationRefused(str(exc), status=403)


def copy(user, *, pk=None, term: str = '', language: str = 'fr'):
    """Une copie PRIVÉE dans les prononciations de `user` : d'une ligne qu'il voit (`pk`), ou
    d'une entrée du FICHIER par son terme — « personnaliser »."""
    from wama.common.utils.tts_text import pronunciations
    if pk is not None:
        row = _row(user, pk)
        who = row.owner.get_username() if row.owner_id else 'système'
        return create(user, row.term, row.language, row.spelling, row.phonemes,
                      copied_from=f'{who}:{row.term}')
    entry = {t.lower(): (t, e) for t, e in pronunciations(language).items()}.get(
        (term or '').strip().lower())
    if entry is None:
        raise PronunciationRefused(f"Aucune prononciation système de « {term} ».", status=404)
    found, forms = entry
    return create(user, found, language, forms.get('spelling', ''), forms.get('phonemes', ''),
                  copied_from=f'système:{found}')


def delete(user, pk):
    """Son auteur, ou un administrateur (`ownership.may_remove`)."""
    from wama.common.manifests.ownership import may_remove
    row = _row(user, pk)
    if not may_remove(user, row):
        raise PronunciationRefused("Seul son auteur, ou un administrateur, la retire.", status=403)
    row.delete()


def promote(user, pk):
    """La rend SYSTÈME — un administrateur seul. Refusé si le fichier du dépôt dit déjà ce terme
    dans cette langue, ou si une ligne système le dit : on ne remplace pas le système ici."""
    from wama.accounts.permissions import is_admin_tier
    from wama.common.manifests.ownership import promote_element
    from wama.common.models import Pronunciation
    row = _row(user, pk)
    if is_admin_tier(user) and row.owner_id is not None:
        if in_file(row.term, row.language):
            raise PronunciationRefused(f"« {row.term} » est au lexique du dépôt "
                                       "(common/tts/pronunciations.json) : le corriger est un "
                                       "geste de développement, pas une promotion.")
        if Pronunciation.objects.filter(owner__isnull=True, language=row.language,
                                        term__iexact=row.term).exists():
            raise PronunciationRefused(f"Une prononciation système de « {row.term} » existe déjà.")
    try:
        return promote_element(user, row)
    except PermissionError as exc:
        raise PronunciationRefused(str(exc), status=403)
    except ValueError as exc:
        raise PronunciationRefused(str(exc))


def in_file(term: str, language: str = '') -> bool:
    """Le fichier du dépôt dit-il `term` (dans `language`, ou dans une langue quelconque) ?"""
    from wama.common.utils.tts_text import system_lexicons
    wanted = (term or '').strip().lower()
    return any(wanted in {t.lower() for t in entries}
               for code, entries in system_lexicons().items() if not language or code == language)


def as_dict(row, user) -> dict:
    """Ce que la page montre d'une ligne : sa provenance et ses gestes (`ownership.provenance_of`),
    plus ce qui est propre à la prononciation."""
    from wama.common.manifests.ownership import provenance_of
    facts = provenance_of(row, user)
    return {'pk': row.pk, 'term': row.term, 'language': row.language, 'spelling': row.spelling,
            'phonemes': row.phonemes, **facts,
            'can_edit': facts['mine'], 'can_copy': not facts['mine']}


def system_entries() -> list:
    """Les entrées du FICHIER, pour la page : `[{term, language, spelling, phonemes}]`."""
    from wama.common.utils.tts_text import system_lexicons
    return [{'term': term, 'language': language, 'spelling': entry.get('spelling', ''),
             'phonemes': entry.get('phonemes', '')}
            for language, entries in sorted(system_lexicons().items())
            for term, entry in sorted(entries.items(), key=lambda i: i[0].lower())]
