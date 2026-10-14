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

import hashlib
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


# ── Les gestes des SURFACES : un élément d'app, un fichier ──────────────────────────────
#
# Sortis de la vue `rag_ajouter` le 2026-10-14 (demande de Fabien : ajouter des fichiers au RAG
# depuis le gestionnaire de fichiers ET depuis l'assistant, « en réutilisant l'existant ») :
# l'endpoint et l'outil de l'assistant appellent les MÊMES fonctions, donc les mêmes gardes, les
# mêmes défauts de niveau et les mêmes refus. Les deux finissent dans `add_to_rag`.
# Un refus rend `{'erreur', 'fragments': 0, 'status'}` — `status` est le code HTTP que la vue
# renvoie tel quel.

def _refusal(message, status=400):
    return {'erreur': message, 'fragments': 0, 'status': status}


def _gesture_level(user, level, org_unit):
    """`(niveau, unité)` d'un geste : ceux du geste, sinon les défauts du profil (« Mon RAG »).

    L'unité cible ne se DEVINE pas quand il y en a plusieurs (`_resolve_unit` refuse) : sans le
    repli sur `rag_unite_defaut`, un utilisateur à plusieurs rattachements — cas courant à l'UGE,
    où les codes hérités coexistent avec les actuels — ne pourrait jamais partager au labo."""
    prof = getattr(user, 'profile', None)
    level = (level or '').strip() or (getattr(prof, 'rag_niveau_defaut', '') if prof else '') \
        or 'user'
    unit = (org_unit or '').strip() or (getattr(prof, 'rag_unite_defaut', '') if prof else '')
    return level, unit or None


def item_text(detail):
    """Le texte d'un élément, tel que le schéma canonique l'expose. `(text, origin)`.

    On ne fabrique RIEN : `result_text` (sortie produite par WAMA — OCR, transcription,
    description) puis `source_text` (le document était déjà textuel). Un élément sans texte n'est
    pas indexable, et c'est ce qui data-gate le geste : pas de « Ajouter au RAG » sur une vidéo.
    """
    for key, origin in (('result_text', 'sortie'), ('source_text', 'entrée')):
        v = (detail.get(key) or '').strip()
        if v:
            return v, origin
    return '', ''


def add_item_to_rag(user, app_name, pk, *, level='', org_unit=''):
    """Ajoute au RAG le texte d'un ÉLÉMENT d'app — le geste de l'inspecteur et du menu « … ».

    Générique par construction : `app_name`/`pk` suffisent, le texte vient du schéma canonique
    (`DetailRegistry`). `source_id` = `<app>:<pk>` — stable, donc le geste est IDEMPOTENT
    (re-cliquer ne duplique pas, changer de niveau ne recalcule pas les vecteurs) et « Mon RAG »
    sait remonter à l'élément d'origine."""
    from ..utils.detail_registry import DetailRegistry

    if user is None or not getattr(user, 'is_authenticated', False):
        return _refusal('utilisateur requis', 403)
    entry = DetailRegistry.get(app_name)
    if not entry:
        return _refusal(f"app inconnue : {app_name}", 404)
    instance = entry['model'].objects.filter(pk=pk).first()
    if instance is None:
        return _refusal(f"élément introuvable : {app_name}:{pk}", 404)
    owner = getattr(instance, 'user', None)
    # L'élément d'un collègue ne s'ajoute pas à MON rag : ce serait recopier son contenu sous mon
    # identité, donc contourner le partage par NIVEAU au lieu de l'utiliser.
    if owner is not None and owner != user and not user.is_staff:
        return _refusal("cet élément ne vous appartient pas", 403)

    text, origin = item_text(entry['adapter'](instance) or {})
    if not text:
        return _refusal("cet élément ne porte pas de texte à indexer")
    level, unit = _gesture_level(user, level, org_unit)
    if level not in WRITE_LEVELS:
        return _refusal(f"niveau non ouvert : {level}")
    res = add_to_rag(user, text,
                     # Référence CITABLE : c'est elle que le rappel affiche à côté de l'extrait.
                     source_ref=f'{app_name}:{pk}', source_id=f'{app_name}:{pk}',
                     source_kind=app_name, niveau=level, org_unit=unit)
    if res.get('erreur'):
        return _refusal(res['erreur'])
    res['origine'] = origin
    return res


def add_file_to_rag(user, path, *, level='', org_unit=''):
    """Ajoute au RAG un FICHIER de l'utilisateur, désigné par son chemin dans le gestionnaire de
    fichiers (relatif à `media/`, ou `mounts/<id>/…` pour un dossier connecté).

    Deux cas, et l'ordre compte :
      ① le fichier est la SORTIE d'un élément de l'utilisateur (`send_to.item_for_output_path`,
        le résolveur du menu de l'arbre) → c'est le geste de l'ÉLÉMENT : son texte tel que l'app
        l'a produit, sous `<app>:<pk>`. Ré-extraire le fichier donnerait un second texte,
        différent de celui que l'utilisateur voit (§7ter) ;
      ② sinon, un document DÉJÀ TEXTUEL (txt, md, csv, pdf à couche texte, docx, html) → son
        texte (`reference_comprehension.read_document_text`). Une image, un son, un PDF scanné sont
        REFUSÉS avec la marche à suivre : leur texte, c'est une app qui le produit.

    La garde de chemin est celle du gestionnaire (`filemanager.services.resoudre_chemin_lisible`,
    `is_path_allowed`), jamais une copie. `source_id` = `file:<uid>:<empreinte du chemin>` (le
    champ tient 64 caractères, un chemin non) : re-ajouter le même fichier le met à jour ;
    `source_ref` = le chemin, ce que « Mon RAG » affiche et que le rappel cite."""
    from wama.common.services.send_to import item_for_output_path
    from wama.common.services.user_files import is_mount_path
    from wama.common.utils.reference_comprehension import TEXT_DOCUMENT_EXTS, read_document_text
    from wama.filemanager.services import resoudre_chemin_lisible

    if user is None or not getattr(user, 'is_authenticated', False):
        return _refusal('utilisateur requis', 403)
    rel = (path or '').replace('\\', '/').lstrip('/')
    disk_path, error = resoudre_chemin_lisible(user, rel)
    if error is not None:
        message, status = error
        return _refusal(message, status)
    if disk_path.is_dir():
        return _refusal("un dossier ne s'ajoute pas au RAG : sélectionner ses fichiers")

    if not is_mount_path(rel):
        surface, element = item_for_output_path(user, rel)
        if element is not None:
            res = add_item_to_rag(user, surface, element.pk, level=level, org_unit=org_unit)
            if not res.get('erreur'):
                res['via'] = f'{surface}:{element.pk}'
            return res

    next_step = (" — son texte se produit par une app (clic droit › « Envoyer vers… » : lecture, "
                 "transcription, description), puis s'ajoute au RAG depuis son résultat")
    if disk_path.suffix.lower() not in TEXT_DOCUMENT_EXTS:
        return _refusal(f"« {disk_path.name} » n'est pas un document texte{next_step}")
    try:
        text = read_document_text(disk_path)
    except Exception as e:                   # dépendance manquante, fichier abîmé : on le DIT
        logger.warning('[memory.index] texte illisible : %s (%s)', rel, e)
        return _refusal(f"« {disk_path.name} » : texte illisible ({e})")
    if not (text or '').strip():
        return _refusal(f"« {disk_path.name} » ne porte aucun texte lisible "
                        f"(document scanné ?){next_step}")

    level, unit = _gesture_level(user, level, org_unit)
    if level not in WRITE_LEVELS:
        return _refusal(f"niveau non ouvert : {level}")
    # Empreinte du chemin EXACT (pas `content_hash`, qui plie la casse : deux fichiers dont le nom
    # ne diffère que par la casse sont deux documents).
    fingerprint = hashlib.sha256(rel.encode('utf-8')).hexdigest()[:16]
    res = add_to_rag(user, text, source_ref=rel, source_id=f'file:{user.pk}:{fingerprint}',
                     source_kind='doc', niveau=level, org_unit=unit)
    if res.get('erreur'):
        return _refusal(res['erreur'])
    res['origine'] = 'fichier'
    return res


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


def list_rag(user, level: str = '', query: str = ''):
    """
    Les documents de `user` au RAG — ce que montre la page « Mon RAG », et ce que lit
    l'assistant (`tool_api.list_my_rag`, 2026-10-14).

    Rend [{'source_id', 'source_ref', 'fragments', 'vectorises', 'niveau', 'ajoute_le'}].
    `vectorises < fragments` signale qu'un `reindex` est à faire — la page l'affiche.
    `level` (`user`, `unit`, `project`, `public` ; vide ou `all` = tous) et `query` (dans la
    référence de la source, casse ignorée) sont les deux filtres de la page.
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
    docs = [{'source_id': l['source_id'], 'source_ref': l['source_ref'],
             'fragments': l['fragments'], 'vectorises': l['vectorises'],
             'niveau': niveau_de.get(l['visibility'], '?'), 'ajoute_le': l['ajoute_le']}
            for l in lignes]
    if level and level != 'all':
        docs = [d for d in docs if d['niveau'] == level]
    if query:
        docs = [d for d in docs if query.lower() in (d['source_ref'] or '').lower()]
    return docs


def lab_share_target(user):
    """`(unité, raison)` — ce qu'un partage « labo » ferait SANS unité nommée.

    Porte d'entrée PUBLIQUE de la règle que `_resolve_unit` applique déjà : une seule
    affiliation → c'est elle ; plusieurs → WAMA ne choisit pas, l'utilisateur désigne ;
    aucune → rien à partager. Ajoutée le 2026-09-26 pour que la page de profil DISE ce que
    le mécanisme fait, au lieu de l'affirmer de son côté : elle annonçait « ces
    rattachements vous ouvrent le partage au niveau labo » dès qu'UN seul était reconnu,
    alors que le compte de Fabien en porte trois et que le partage refusait de trancher.
    *Une page qui promet ce que le code refuse est un bug d'interface, pas de présentation.*
    """
    return _resolve_unit(user, None)


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
