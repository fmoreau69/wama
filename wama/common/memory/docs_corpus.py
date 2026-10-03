"""
Corpus SYSTÈME — la doc de WAMA rendue rappelable par l'assistant. Doc : `WAMA_MEMORY.md §7quinquies`.

POURQUOI (question de Fabien, 2026-10-03 : « l'assistant a-t-il accès à toute la doc de WAMA ? »)

    Mesuré ce jour : non. L'assistant ne lisait AUCUN document de WAMA — ni la doc utilisateur,
    ni la doctrine. Le skill `assistant-dev` le disait lui-même (« you do not have direct access
    to the repository files »), et pour une question d'usage il répondait de sa seule mémoire de
    modèle. Or les docs existent, sont DÉCLARÉES (`docs_catalog.py`) et savent déjà dire qui les
    lit (`visible_to`).

CE MODULE N'INVENTE RIEN — il relie quatre briques existantes

    • la LISTE et la GARDE : `docs_catalog.DOCS` et `docs_catalog.visible_to`. Une doc qu'un
      compte ne peut pas ouvrir dans le lecteur N'EXISTE PAS non plus pour son assistant —
      même prédicat, appelé au rappel, jamais recopié ;
    • le DÉCOUPAGE : `doc_sections.sections()` (titres, niveaux, balises constat/intention),
      puis `index.split_text()` pour une section plus longue qu'un fragment ;
    • le SUBSTRAT : `RagChunk` (`source_kind='doc'`), dont c'est la destination prévue depuis
      l'origine — re-dérivable, donc réécrit sans perte ;
    • le CLASSEMENT : `store.recall(include_docs=True)` — hybride, RRF, mêmes seuils.

EN QUOI CE N'EST PAS LE BALAYAGE RETIRÉ LE 2026-08-21

    La règle « l'entrée au RAG est un GESTE » protège le CONSENTEMENT : ce qu'un utilisateur a
    produit n'entre nulle part sans qu'il l'ait demandé. Ici rien n'appartient à un utilisateur :
    ce sont les documents de WAMA lui-même, déjà publiés à ces mêmes comptes par le lecteur
    `/common/docs/`. La projection est donc MÉCANIQUE et DÉCLARÉE, comme celle de `project.py`.

    Et elle reste hors du RAG des utilisateurs, par construction : les fragments sont écrits
    SANS propriétaire et en visibilité privée, donc `scoped_visible_q` ne les rend à personne.
    « Mon RAG », `memory_recall` et le contexte de laboratoire ne les voient pas ; seul l'accès
    nommé (`include_docs`) les atteint, derrière la garde du catalogue.

CE QUI N'ENTRE PAS

    Les JOURNAUX (`Doc.journal`) : ce qu'ils écrivent était vrai à leur date. Un extrait de
    journal sorti de sa date se lit comme un constat présent — exactement ce qu'`AGENTS.md`
    interdit de faire. Ils restent lisibles en entier (`read`), jamais rappelés par morceaux.

⚠ ZÉRO APPEL DE MODÈLE ICI (règle §5bis) : `embedding=NULL` à l'écriture, les vecteurs viennent
par lot (`store.reindex()`). Un fragment INCHANGÉ garde le sien : modifier une ligne d'un doc
ne fait recalculer que les fragments touchés.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Préfixe du `source_id` des fragments de doc : `wama-doc:<clé du catalogue>`.
SOURCE_PREFIX = 'wama-doc:'

#: Séparateur du `source_ref` : `<chemin>:<ligne du titre> § <titre de section>`.
REF_SEPARATOR = ' § '

#: Plafond d'un texte rendu par `read` (caractères). Une section de doctrine dépasse rarement
#: cette taille ; au-delà, le lecteur dit qu'il a coupé et où reprendre.
READ_MAX_CHARS = 8000

#: Plafond du sommaire rendu par `read` sans section : les journaux ont des milliers de titres.
OUTLINE_MAX = 200


def source_id_of(key: str) -> str:
    return f'{SOURCE_PREFIX}{key}'


def indexed_docs():
    """Les docs qui ENTRENT au corpus : déclarés, et pas des journaux datés."""
    from ..docs_catalog import DOCS
    return [d for d in DOCS if not d.journal]


def visible_keys(user) -> list:
    """Clés des docs que `user` peut lire — le prédicat du lecteur, pas une copie.

    Un compte non identifié n'a aucune doc : le lecteur lui-même exige une session.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return []
    from wama.accounts.views import is_admin

    from ..docs_catalog import DOCS, visible_to
    admin = is_admin(user)
    return [d.key for d in DOCS if visible_to(d, admin)]


def visible_chunks(user):
    """Fragments de doc rappelables par `user` — la base que `recall(include_docs=True)` classe."""
    from ..models import RagChunk
    keys = visible_keys(user)
    if not keys:
        return RagChunk.objects.none()
    return RagChunk.objects.filter(user__isnull=True, source_kind='doc',
                                   source_id__in=[source_id_of(k) for k in keys])


def _state_mark(attrs: dict) -> str:
    """` [intention ⏳]` quand la section se déclare — ce qui distingue un projet d'un fait."""
    nature, state = attrs.get('nature'), attrs.get('etat')
    if not nature:
        return ''
    return f" [{nature}{' ' + str(state) if state else ''}]"


def fragments_of(doc, text: str) -> list:
    """`[(contenu, source_ref)]` d'un doc, dans l'ordre du texte.

    Une section = son titre et son corps, VERBATIM ; une section plus longue qu'un fragment est
    redécoupée par `split_text` (frontière de phrase, recouvrement). Le titre accompagne le
    premier fragment — c'est lui qui porte les mots que la question emploie — et chaque
    fragment garde dans sa référence la ligne et le titre de sa section, pour citer et rouvrir.
    """
    from ..doc_sections import sections
    from .index import split_text

    out = []
    for s in sections(text)[0]:
        body = (s.body or '').strip()
        if not body:
            continue                     # un titre sans texte n'apprend rien : pas de fragment
        ref = f"{doc.path}:{s.line}{REF_SEPARATOR}{s.title}{_state_mark(s.attrs)}"
        heading = f"{'#' * s.level} {s.title}"
        for piece in split_text(f"{heading}\n\n{body}"):
            out.append((piece, ref))
    return out


def index_docs(*, dry_run: bool = False) -> dict:
    """Projette la doc déclarée vers le corpus. Rend `{'docs', 'written', 'unchanged',
    'removed', 'fragments', 'missing', 'dry_run'}`.

    IDEMPOTENT : un doc dont les fragments n'ont pas bougé n'est pas réécrit. Un doc modifié est
    réécrit en entier (re-dérivable, `WAMA_MEMORY §3`), mais chaque fragment au contenu identique
    REPREND son vecteur — l'embedding ne dépend que du contenu. Les fragments d'un doc retiré du
    catalogue, ou devenu journal, sont supprimés.
    """
    from django.db import transaction

    from ..docs_catalog import file_of
    from ..models import RagChunk, ScopedVisibility
    from .store import content_hash

    summary = {'docs': 0, 'written': [], 'unchanged': 0, 'removed': [], 'fragments': 0,
              'missing': [], 'dry_run': dry_run}
    expected = set()
    for doc in indexed_docs():
        sid = source_id_of(doc.key)
        expected.add(sid)
        try:
            text = file_of(doc).read_text(encoding='utf-8', errors='replace')
        except OSError:
            # Déclaré mais absent du disque : `check_docs` le dit déjà ; on ne détruit pas ce
            # qui était indexé pour un fichier momentanément illisible.
            summary['missing'].append(doc.key)
            continue
        summary['docs'] += 1
        pieces = fragments_of(doc, text)
        hashes = [content_hash(f) for f, _ in pieces]
        summary['fragments'] += len(pieces)

        qs = RagChunk.objects.filter(user__isnull=True, source_kind='doc', source_id=sid)
        existing = list(qs.order_by('ordinal').values_list('content_hash', 'source_ref'))
        if existing == [(e, r) for e, (_, r) in zip(hashes, pieces)]:
            summary['unchanged'] += 1
            continue
        summary['written'].append(doc.key)
        if dry_run:
            continue
        # Vecteurs repris par empreinte : seuls les fragments NEUFS attendront `reindex()`.
        vectors = {h: (e, m) for h, e, m in
                   qs.exclude(embedding__isnull=True)
                     .values_list('content_hash', 'embedding', 'embedding_model')}
        with transaction.atomic():
            qs.delete()
            RagChunk.objects.bulk_create([
                RagChunk(content=piece, content_hash=digest,
                         embedding=vectors.get(digest, (None, ''))[0],
                         embedding_model=vectors.get(digest, (None, ''))[1],
                         source_kind='doc', source_id=sid, source_ref=ref, ordinal=i,
                         # Sans propriétaire ET privé : invisible de `scoped_visible_q`, donc
                         # hors de tout RAG d'utilisateur. Seul `visible_chunks` y mène.
                         user=None, visibility=ScopedVisibility.VIS_PRIVATE)
                for i, ((piece, ref), digest) in enumerate(zip(pieces, hashes))
            ])

    stale = (RagChunk.objects.filter(user__isnull=True, source_kind='doc',
                                     source_id__startswith=SOURCE_PREFIX)
             .exclude(source_id__in=expected))
    summary['removed'] = sorted(set(stale.values_list('source_id', flat=True)))
    if summary['removed'] and not dry_run:
        stale.delete()
    if summary['written'] or summary['removed']:
        logger.info('[memory.docs] %s doc(s) réécrit(s), %s retiré(s)%s',
                    len(summary['written']), len(summary['removed']),
                    ' (dry-run)' if dry_run else '')
    return summary


def corpus_state() -> dict:
    """`{'fragments', 'vectorized', 'docs'}` — ce que le corpus contient, pour le dire."""
    from django.db.models import Count, Q

    from ..models import RagChunk
    state = (RagChunk.objects.filter(user__isnull=True, source_kind='doc',
                                     source_id__startswith=SOURCE_PREFIX)
             .aggregate(fragments=Count('id'),
                        vectorized=Count('id', filter=Q(embedding__isnull=False)),
                        docs=Count('source_id', distinct=True)))
    return {k: state[k] or 0 for k in ('fragments', 'vectorized', 'docs')}


def describe_hit(chunk) -> dict:
    """Ce qu'un fragment retrouvé dit de sa provenance : doc, section, audience, lien, date."""
    from django.urls import reverse

    from ..docs_catalog import AUDIENCE_BADGES, BY_KEY, CONSTRUCTION, entry

    doc_key = (chunk.source_id or '')[len(SOURCE_PREFIX):]
    doc = BY_KEY.get(doc_key)
    location, _, section = (chunk.source_ref or '').partition(REF_SEPARATOR)
    out = {'doc': doc_key, 'section': section, 'location': location, 'content': chunk.content}
    if doc is None:
        return out
    card = entry(doc)
    modified = card.get('modified')
    out.update(
        label=doc.label, audience=AUDIENCE_BADGES.get(doc.audience, doc.audience),
        url=reverse('common:doc_read', args=[doc.key]),
        modified=modified.date().isoformat() if modified else None)
    if doc.audience == CONSTRUCTION:
        # La doc de construction mêle constats et intentions, et un statut y est une trace
        # DATÉE (`AGENTS.md §Trois docs`) : le dire avec l'extrait, pas dans un prompt à part.
        out['caution'] = ("doc de construction : trace datée, qui mêle ce qui existe et ce qui "
                          "est visé — un état présent se vérifie dans le code ou les registres")
    return out


def read(user, key: str, section: str = '') -> dict:
    """Lit UN doc déclaré : son sommaire, ou une section avec ses sous-sections.

    `{'error'}` si la doc n'existe pas POUR CE COMPTE — même réponse qu'elle soit inconnue ou
    réservée, comme le lecteur (un refus confirmerait qu'elle existe). Les journaux se lisent
    ici : ils ne sont écartés que du rappel par morceaux.
    """
    from ..doc_sections import sections
    from ..docs_catalog import BY_KEY, file_of

    doc = BY_KEY.get((key or '').strip())
    if doc is None or doc.key not in visible_keys(user):
        return {'error': f"document « {key} » inconnu"}
    try:
        text = file_of(doc).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return {'error': f"document « {key} » déclaré mais absent du disque"}
    parts = sections(text)[0]
    base = {'doc': doc.key, 'label': doc.label, 'description': doc.description,
            'journal': doc.journal}

    wanted = (section or '').strip().casefold()
    if not wanted:
        outline = [{'title': s.title, 'level': s.level, 'line': s.line}
                   for s in parts if s.level <= 3]
        return {**base, 'outline': outline[:OUTLINE_MAX],
                'outline_truncated': len(outline) > OUTLINE_MAX}

    # Titre EXACT d'abord, puis sous-chaîne : « §7ter » ou « Entrée au RAG » trouvent la même
    # section sans que l'appelant ait à recopier un titre de soixante caractères.
    index = next((i for i, s in enumerate(parts) if s.title.casefold() == wanted), None)
    if index is None:
        index = next((i for i, s in enumerate(parts) if wanted in s.title.casefold()), None)
    if index is None:
        return {**base, 'error': f"section « {section} » introuvable — demandez le sommaire "
                                 "(sans `section`) pour voir les titres"}
    head = parts[index]
    pieces = []
    for s in parts[index:]:
        if s is not head and s.level <= head.level:
            break                         # la section s'arrête au titre de même rang suivant
        pieces.append(f"{'#' * s.level} {s.title}\n\n{(s.body or '').strip()}".strip())
    content = '\n\n'.join(pieces)
    return {**base, 'section': head.title + _state_mark(head.attrs), 'line': head.line,
            'content': content[:READ_MAX_CHARS], 'truncated': len(content) > READ_MAX_CHARS}
