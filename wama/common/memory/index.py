"""
Entrée au RAG — un GESTE de l'utilisateur, jamais un balayage. Doc : `WAMA_MEMORY.md §7ter`.

⚠ CORRECTION DE CONCEPTION (2026-08-21). La première version de ce module dérivait ses sources
de `detail_registry` et BALAYAIT les sorties texte de toutes les apps, tous utilisateurs
confondus (`sync_memory --rag`) : 939 fragments écrits sans qu'aucun utilisateur n'ait rien
demandé. Objection de Fabien, fondée : « pour ajouter des médias au RAG c'est une action
spécifique de l'utilisateur ». Le flux voulu est :

    sortie d'app → (si l'utilisateur le veut) médiathèque → (ACTION EXPLICITE) → RAG

Les 939 fragments ont été PURGÉS le jour même — un `RagChunk` est RE-DÉRIVABLE par construction
(§3), la purge est donc sans perte : ce qui doit entrer au RAG y rentrera par le geste. Le
balayage est retiré ; ce module n'offre plus que des gestes UNITAIRES.

ON N'EXTRAIT TOUJOURS RIEN — ce principe-là survit à la correction. `texte` est la sortie déjà
produite par WAMA (OCR du reader, transcription, description…) ou le contenu d'un document déjà
textuel. Cas d'usage nommé par Fabien : un scan de notes manuscrites passe par le reader (OCR),
et c'est CE texte que l'utilisateur ajoute au RAG — où il servira ensuite, par exemple, à
rédiger un compte-rendu depuis une transcription de réunion.

NIVEAUX. Un document entre au RAG à un NIVEAU choisi par l'utilisateur au moment du geste :
  • 'user' (défaut) — mon RAG : privé, visible de moi seul ;
  • 'unit'          — RAG du labo / de l'équipe : visible des membres de l'unité et de ses
                      sous-unités (héritage `OrgUnit.parent`).
  'project' est ANNONCÉ comme niveau suivant (décision Fabien 2026-08-21) ; 'public' viendra en
  dernier. Le niveau EST la visibilité de `ScopedVisibility` — aucun second modèle de scope.
  ⚠ MULTI-ENTITÉS : un utilisateur peut appartenir à PLUSIEURS unités (`org_affiliations` est
  une liste). S'il en a plusieurs, le geste 'unit' doit NOMMER l'unité — on ne devine pas :
  un partage parti dans la mauvaise entité ne se voit pas.

⚠ ZÉRO APPEL DE MODÈLE ICI (règle §5bis) : le découpage est mécanique, `embedding=NULL`, les
vecteurs viennent par lot via `store.reindex()`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Taille de découpe, en caractères. ~800 tient largement dans la fenêtre de `bge-m3` tout en
#: gardant un fragment ASSEZ GRAND pour être compréhensible seul — un fragment trop court se
#: retrouve bien mais ne veut plus rien dire une fois sorti de son contexte.
CHUNK_SIZE = 800

#: Recouvrement entre fragments consécutifs. Sans lui, une phrase coupée en deux devient
#: introuvable : ni l'un ni l'autre des deux fragments ne la contient en entier.
CHUNK_OVERLAP = 120

#: Niveaux d'ÉCRITURE ouverts aujourd'hui. Étendre = ajouter ici + le mapping de
#: `_VISIBILITE_PAR_NIVEAU` — le rappel (`store.NIVEAUX_RAG`) sait déjà les filtrer tous.
WRITE_LEVELS = ('user', 'unit')


def split_text(texte, taille=CHUNK_SIZE, recouvrement=CHUNK_OVERLAP):
    """
    Découpe en fragments qui se recouvrent, en préférant une frontière NATURELLE.

    On cherche la dernière fin de phrase (ou à défaut le dernier espace) avant la limite, plutôt
    que de couper au caractère près : un fragment qui commence au milieu d'un mot pollue son
    propre vecteur, et se relit mal quand on le cite à l'utilisateur.
    """
    texte = (texte or '').strip()
    if not texte:
        return []
    if len(texte) <= taille:
        return [texte]

    fragments, debut = [], 0
    while debut < len(texte):
        fin = min(debut + taille, len(texte))
        if fin < len(texte):
            fenetre = texte[debut:fin]
            coupe = max(fenetre.rfind('. '), fenetre.rfind('.\n'),
                        fenetre.rfind('!\n'), fenetre.rfind('?\n'), fenetre.rfind('\n\n'))
            if coupe < taille // 2:              # frontière trop tôt : on n'ampute pas le fragment
                coupe = fenetre.rfind(' ')
            if coupe > taille // 2:
                fin = debut + coupe + 1
        fragment = texte[debut:fin].strip()
        if fragment:
            fragments.append(fragment)
        if fin >= len(texte):
            break
        debut = max(fin - recouvrement, debut + 1)
    return fragments


def add_to_rag(user, texte, *, source_ref, source_id=None, source_kind='doc',
                   niveau='user', org_unit=None):
    """
    Ajoute UN document au RAG, au niveau choisi par l'utilisateur. Rend un résumé `{...}`.

    C'est LE point d'entrée du RAG — le seul. Les surfaces (bouton « Ajouter au RAG » sur un
    résultat d'app ou un item de médiathèque, future page de gestion) appellent ceci ; aucune
    autre voie d'écriture n'existe.

    Idempotent par `source_id` : re-ajouter le même contenu ne duplique pas ; re-ajouter à un
    AUTRE niveau met à jour la visibilité SANS toucher aux vecteurs (changer la portée d'un
    document ne doit pas coûter un réindex) ; un contenu modifié est redécoupé (vecteurs à
    refaire par `store.reindex()`).
    """
    from ..models import RagChunk, ScopedVisibility
    from .store import content_hash

    texte = (texte or '').strip()
    if user is None:
        return {'erreur': 'utilisateur requis', 'fragments': 0}
    if not texte:
        return {'erreur': 'texte vide', 'fragments': 0}
    if niveau not in WRITE_LEVELS:
        return {'erreur': f"niveau inconnu {niveau!r} — ouverts : {', '.join(WRITE_LEVELS)}",
                'fragments': 0}

    visibilite, unite = ScopedVisibility.VIS_PRIVATE, None
    if niveau == 'unit':
        unite, pourquoi = _resolve_unit(user, org_unit)
        if unite is None:
            return {'erreur': pourquoi, 'fragments': 0}
        visibilite = ScopedVisibility.VIS_UNIT

    # `adhoc:` inclut l'utilisateur : la contrainte d'unicité porte sur (source_kind, source_id,
    # ordinal) GLOBALEMENT — deux utilisateurs ajoutant le même texte collisionneraient sinon.
    source_id = source_id or f'adhoc:{user.pk}:{content_hash(texte)[:12]}'

    fragments = split_text(texte)
    empreintes = [content_hash(f) for f in fragments]

    qs = RagChunk.objects.filter(user=user, source_id=source_id)
    existants = list(qs.order_by('ordinal').values_list('content_hash', flat=True))
    if existants == empreintes:
        # Contenu identique : seul le NIVEAU peut avoir changé — mise à jour sans réécriture,
        # les embeddings existants survivent.
        qs.update(visibility=visibilite, scope_org_unit=unite)
        return {'source_id': source_id, 'fragments': len(fragments), 'etat': 'inchangé',
                'niveau': niveau}

    etat = 'réindexé' if existants else 'indexé'
    qs.delete()
    RagChunk.objects.bulk_create([
        RagChunk(
            content=frag, content_hash=emp,
            # ⚠ Aucun vecteur ici : `store.reindex()` les calcule par lot, quand la machine est
            # libre (incident GPU du 2026-08-20, §5bis).
            embedding=None, embedding_model='',
            source_kind=source_kind, source_id=source_id, source_ref=source_ref,
            ordinal=i, user=user, visibility=visibilite, scope_org_unit=unite)
        for i, (frag, emp) in enumerate(zip(fragments, empreintes))
    ])
    logger.info('[memory.index] %s : %s fragments au niveau %s (%s)',
                source_id, len(fragments), niveau, etat)
    return {'source_id': source_id, 'fragments': len(fragments), 'etat': etat, 'niveau': niveau}


def remove_from_rag(user, source_id):
    """
    Retire un document du RAG — tous ses fragments. Rend le nombre de lignes supprimées.

    Ne touche que ce que POSSÈDE `user` : on ne retire pas le document d'un collègue, même
    partagé dans la même unité. C'est le pendant du geste d'ajout, et la condition posée dès
    l'objection : ce qui entre par un geste doit pouvoir sortir par un geste.
    """
    from ..models import RagChunk

    n, _ = RagChunk.objects.filter(user=user, source_id=source_id).delete()
    if n:
        logger.info('[memory.index] %s retiré du RAG (%s fragments)', source_id, n)
    return n


def list_rag(user):
    """
    Les documents de `user` au RAG — la matière de la future page de gestion.

    Rend [{'source_id', 'source_ref', 'fragments', 'vectorises', 'niveau', 'ajoute_le'}].
    `vectorises < fragments` signale qu'un `reindex` est à faire — la page pourra l'afficher.
    """
    from django.db.models import Count, Min, Q

    from ..models import RagChunk, ScopedVisibility

    niveau_de = {ScopedVisibility.VIS_PRIVATE: 'user', ScopedVisibility.VIS_UNIT: 'unit',
                 ScopedVisibility.VIS_PROJECT: 'project', ScopedVisibility.VIS_PUBLIC: 'public'}
    lignes = (RagChunk.objects.filter(user=user)
              .values('source_id', 'source_ref', 'visibility')
              .annotate(fragments=Count('id'),
                        vectorises=Count('id', filter=Q(embedding__isnull=False)),
                        ajoute_le=Min('created_at'))
              .order_by('-ajoute_le'))
    return [{'source_id': l['source_id'], 'source_ref': l['source_ref'],
             'fragments': l['fragments'], 'vectorises': l['vectorises'],
             'niveau': niveau_de.get(l['visibility'], '?'), 'ajoute_le': l['ajoute_le']}
            for l in lignes]


def _resolve_unit(user, org_unit):
    """
    Rend `(OrgUnit, '')` ou `(None, raison)`. STRICT sur deux points, délibérément :

      • l'unité doit être une AFFILIATION DIRECTE de l'utilisateur — pas un ancêtre. Publier au
        niveau du département ou de l'université est le niveau 3/4, pas encore ouvert ;
      • avec PLUSIEURS affiliations, l'unité doit être nommée — deviner publierait dans la
        mauvaise entité, et un partage raté ne se voit pas.
    """
    from ..models import OrgUnit

    prof = getattr(user, 'profile', None)
    codes = []
    if prof is not None:
        codes = list(prof.org_affiliations or [])
        if prof.org_entity_code:
            codes.append(prof.org_entity_code)
    codes = list(dict.fromkeys(codes))          # dédoublonne en préservant l'ordre

    if org_unit is not None:
        if isinstance(org_unit, OrgUnit):
            unite = org_unit
        else:
            unite = OrgUnit.local().filter(code=org_unit).first()
            if unite is None:
                return None, f"unité inconnue : {org_unit!r}"
        if unite.code not in codes:
            return None, (f"pas d'affiliation directe à « {unite.code} » — publier dans une "
                          "unité exige d'en être membre")
        return unite, ''

    if len(codes) == 1:
        unite = OrgUnit.local().filter(code=codes[0]).first()
        if unite is None:
            return None, f"l'affiliation « {codes[0]} » n'a pas d'OrgUnit correspondante"
        return unite, ''
    if not codes:
        return None, ("aucune affiliation d'unité sur le profil — renseigner "
                      "org_affiliations avant de partager au niveau labo")
    return None, (f"plusieurs affiliations ({', '.join(codes)}) : nommer l'unité cible "
                  "via org_unit")
