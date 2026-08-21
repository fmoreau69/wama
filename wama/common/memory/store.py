"""
Les cinq opérations de la mémoire. Doc : `WAMA_MEMORY.md §5-6`.

    remember(...)  écrire un souvenir          (par défaut : NON approuvé, donc invisible)
    recall(...)    retrouver                   (hybride vecteur + lexical, fusionné par RRF)
    forget(...)    invalider                   (par défaut : `valid_to`, JAMAIS un DELETE)
    merge(...)     PROPOSER une fusion         (n'écrit rien)
    expire()       appliquer les TTL           (n'atteint jamais un souvenir approuvé)

Vocabulaire emprunté à memorywire (arXiv 2606.01138) — la FORME du contrat, pas la dépendance
(v0.4, format qui se réserve de casser jusqu'en v0.5). L'emprunter rend un adaptateur externe
possible plus tard sans réécrire les appelants.
"""
from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

#: Constante de la Reciprocal Rank Fusion. 60 est la valeur de la littérature ; elle amortit
#: l'écart entre les premiers rangs, ce qui est exactement le but — un document premier chez un
#: seul ranker ne doit pas écraser un document deuxième chez les deux.
RRF_K = 60

#: Nombre de candidats demandés à CHAQUE ranker avant fusion. Plus large que le `k` final :
#: la fusion n'a d'intérêt que si les listes se recouvrent partiellement.
CANDIDATS_PAR_RANKER = 50

#: Rang minimal pour qu'un appariement lexical COMPTE. Voir `_par_lexique` : Postgres rend
#: 1e-20 sur toutes les lignes quand la requête ne contient aucun terme connu, et `> 0` laissait
#: donc tout passer. Sur ce corpus un vrai appariement note ≥ 0.06 : le seuil est six ordres de
#: grandeur au-dessus du plancher et six en dessous du plus faible vrai positif.
SEUIL_LEXICAL = 1e-6

#: Poids de la saillance dans le score final. Une saillance de 1.0 majore le score de 25 % —
#: assez pour départager deux résultats proches, trop peu pour faire remonter un hors-sujet.
#: Voir `WAMA_MEMORY.md §8` : la saillance est DÉRIVÉE de gestes réels, jamais d'une inférence.
POIDS_SAILLANCE = 0.25

_ESPACES = re.compile(r'\s+')


class Hit:
    """Un résultat de rappel. `obj` est un `MemoryItem` ou un `RagChunk`."""

    __slots__ = ('obj', 'source', 'score', 'rangs')

    def __init__(self, obj, source, score, rangs):
        self.obj = obj
        self.source = source        # 'memory' | 'rag'
        self.score = score
        self.rangs = rangs          # {'vecteur': 3, 'lexical': 11} — traçabilité du classement

    def __repr__(self):
        return f"<Hit {self.source} #{self.obj.pk} score={self.score:.4f} {self.rangs}>"


def content_hash(text: str) -> str:
    """
    SHA-256 du contenu NORMALISÉ (espaces repliés, casse pliée).

    La normalisation ne touche QUE le hachage — `content` reste verbatim. Elle existe pour que
    deux projections du même fait, écrites à une espace près, ne fassent pas deux souvenirs.
    """
    norme = _ESPACES.sub(' ', (text or '').strip()).casefold()
    return hashlib.sha256(norme.encode('utf-8')).hexdigest()


# ─────────────────────────────────────────────────────────── remember ────────

def remember(content, *, kind, provenance, user=None, subject='', source_app='',
             source_object_type='', source_object_id=None, confidence=None,
             visibility=None, scope_org_unit=None, scope_project=None,
             approved=False, approved_by=None, salience=0.0, valid_from=None,
             embed=True):
    """
    Écrit un souvenir. Rend le `MemoryItem` (créé ou déjà existant), ou `None` en cas d'échec.

    ⚠ `embed=False` écrit SANS TOUCHER AU GPU (`embedding=NULL`), à rattraper par `reindex()`.
    À utiliser dans les trois cas où embarquer à l'écriture est une faute :
      - **projection en masse** (jalon 4 : des milliers de `RunOutcome`) — un appel Ollama par
        ligne serait absurde là où un lot en fait un seul ;
      - **tests** — un smoke ne doit jamais charger un modèle sur la machine de quelqu'un ;
      - **GPU occupé** — une écriture n'a pas à attendre, ni à concurrencer un traitement.
    L'écriture et le calcul du vecteur sont deux choses : la première ne doit jamais échouer ni
    attendre, la seconde peut se faire plus tard et par lot.

    ⚠ `approved=False` PAR DÉFAUT, et un souvenir non approuvé est INVISIBLE au rappel. Seules
    les projections mécaniques (`provenance='projection'`) ont le droit de s'auto-approuver :
    elles ne font que pointer un fait déjà en base, sans inférence. Tout ce qui sort d'un LLM
    passe par une validation humaine — mesure du 2026-07-17 : sur 6 audits wama-dev-ai, les
    affirmations d'absence étaient fausses 4 fois sur 6.

    Dédup : un contenu identique, même propriétaire et même sujet ⇒ on rend l'existant sans
    réécrire ni recalculer d'embedding.
    """
    from django.utils import timezone

    from ..models import MemoryItem, ScopedVisibility
    from .embed import EMBEDDING_MODEL, embed_text

    if not (content or '').strip():
        logger.warning('[memory] remember() sur un contenu vide — ignoré')
        return None

    if provenance != MemoryItem.PROV_PROJECTION and approved and approved_by is None:
        # Garde-fou : « approuvé par personne » est le trou par lequel une sortie LLM entrerait
        # comme un fait. Une projection, elle, n'a pas d'approbateur humain PAR CONSTRUCTION.
        logger.warning("[memory] approbation sans approbateur (provenance=%s) — souvenir écrit "
                       "NON approuvé", provenance)
        approved = False

    h = content_hash(content)
    existant = MemoryItem.objects.filter(content_hash=h, user=user, subject=subject,
                                         valid_to__isnull=True).first()
    if existant is not None:
        return existant

    # None si `embed=False` (aucun appel GPU) OU si l'embedder est indisponible : les deux sont
    # des cas NORMAUX, rattrapés par `reindex()`. La ligne s'écrit dans tous les cas.
    vecteur = embed_text(content) if embed else None

    try:
        return MemoryItem.objects.create(
            content=content,
            content_hash=h,
            embedding=vecteur,
            embedding_model=EMBEDDING_MODEL if vecteur is not None else '',
            kind=kind,
            provenance=provenance,
            user=user,
            subject=subject,
            source_app=source_app,
            source_object_type=source_object_type,
            source_object_id=source_object_id,
            confidence=confidence,
            visibility=visibility or ScopedVisibility.VIS_PRIVATE,
            scope_org_unit=scope_org_unit,
            scope_project=scope_project,
            approved_at=timezone.now() if approved else None,
            approved_by=approved_by if approved else None,
            salience=salience,
            valid_from=valid_from or timezone.now(),
        )
    except Exception:
        logger.exception('[memory] écriture impossible')
        return None


# ───────────────────────────────────────────────────────────── recall ────────

def recall(query, *, user, kinds=None, subject=None, k=8, include_rag=True,
           include_memory=True, semantic=True):
    """
    Retrouve les `k` meilleurs éléments visibles par `user`.

    ⚠ `semantic=False` force le LEXICAL SEUL et ne touche pas au GPU (aucun embedding de la
    requête). Même motivation que `remember(embed=False)` : un test, ou un contexte où le GPU
    ne doit pas être sollicité, doit pouvoir rappeler sans charger de modèle.

    HYBRIDE — vecteur (pgvector, cosinus) ET lexical (full-text FR), fusionnés par RRF. Le
    lexical n'est pas un luxe : il rattrape les identifiants exacts (`model_key`, nom de
    fichier, code projet) que le vectoriel manque parce qu'ils n'ont pas de voisinage
    sémantique. Fusion par RRF et non par max ni somme pondérée — l'évaluation memorywire
    montre que RRF tient sous injection adverse en rang 0, là où `max` s'effondre.

    Si l'embedder est indisponible, le rappel se poursuit en LEXICAL SEUL (dégradé, pas cassé).
    """
    from .embed import embed_text

    if not (query or '').strip():
        return []

    vecteur = embed_text(query) if semantic else None
    listes = []

    if include_memory:
        base = _memoire_visible(user, kinds=kinds, subject=subject)
        listes.append(('vecteur', 'memory', _par_vecteur(base, vecteur)))
        listes.append(('lexical', 'memory', _par_lexique(base, query)))
    if include_rag:
        base = _rag_visible(user)
        listes.append(('vecteur', 'rag', _par_vecteur(base, vecteur)))
        listes.append(('lexical', 'rag', _par_lexique(base, query)))

    return _fusion_rrf(listes)[:k]


def _memoire_visible(user, *, kinds=None, subject=None):
    """Souvenirs ACTIFS et visibles : approuvés, non invalidés, dans le scope de `user`."""
    from django.utils import timezone

    from ..models import MemoryItem, scoped_visible_q

    qs = MemoryItem.objects.filter(scoped_visible_q(user))
    # Les trois filtres qui font la gouvernance. Les retirer « pour déboguer » exposerait des
    # sorties LLM non validées comme si c'étaient des faits — ne jamais les rendre optionnels.
    qs = qs.filter(approved_at__isnull=False)
    qs = qs.filter(_q_valides(timezone.now()))
    qs = qs.filter(superseded_by__isnull=True)
    if kinds:
        qs = qs.filter(kind__in=list(kinds))
    if subject:
        qs = qs.filter(subject=subject)
    return qs


def _q_valides(maintenant):
    """`Q` des souvenirs dont la fenêtre de validité couvre `maintenant`."""
    from django.db.models import Q
    return Q(valid_to__isnull=True) | Q(valid_to__gt=maintenant)


def _rag_visible(user):
    from ..models import RagChunk, scoped_visible_q
    return RagChunk.objects.filter(scoped_visible_q(user))


def _par_vecteur(queryset, vecteur):
    """Candidats par distance cosinus. Liste VIDE si pas de vecteur de requête (dégradation)."""
    if vecteur is None:
        return []
    try:
        from pgvector.django import CosineDistance
        qs = (queryset.exclude(embedding__isnull=True)
                      .annotate(_dist=CosineDistance('embedding', vecteur))
                      .order_by('_dist')[:CANDIDATS_PAR_RANKER])
        return list(qs)
    except Exception:
        logger.warning('[memory] recherche vectorielle indisponible — lexical seul', exc_info=True)
        return []


def _par_lexique(queryset, query):
    """
    Candidats par recherche plein texte française.

    Configuration `french` : sans elle, Postgres n'applique ni le stemming ni les mots vides du
    français, et « transcriptions corrigées » ne retrouverait pas « transcription corrigée ».
    """
    try:
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

        vecteur = SearchVector('content', config='french')
        # ⚠ OU, PAS ET. `SearchQuery(phrase)` utilise `plainto_tsquery`, qui exige que TOUS les
        # termes soient présents dans le MÊME fragment. Une question en langage naturel — « que
        # disent mes entretiens sur le consentement ? » — n'a alors AUCUNE chance : elle
        # réclamerait « disent » ET « entretiens » ET « consentement » côte à côte. Mesuré le
        # 2026-08-21 : la phrase rendait 0 là où le seul mot « consentement » rendait 8.
        # En OU, chaque terme contribue et le RANG fait le tri — c'est le rang qui distingue le
        # fragment pertinent, pas la conjonction. Les mots vides sont écartés par le
        # dictionnaire français lui-même, on n'en tient donc pas de liste.
        termes = [t for t in re.split(r'\W+', query) if len(t) > 2]
        if not termes:
            return []
        requete = SearchQuery(termes[0], config='french')
        for t in termes[1:]:
            requete = requete | SearchQuery(t, config='french')
        # ⚠ SEUIL, ET NON `> 0`. Quand AUCUN terme de la requête n'est connu du dictionnaire,
        # Postgres rend un rang PLANCHER de 1e-20 — sur TOUTES les lignes. Or 1e-20 > 0 : le
        # filtre laissait donc tout passer. Mesuré le 2026-08-21 : « xyzzy quuxbaz » ramenait
        # les 939 fragments, et le Hook B injectait du contexte hors-sujet dans un prompt sans
        # la moindre correspondance — le mode d'échec qu'on reproche aux RAG opaques.
        # Le seuil sépare proprement : un vrai appariement note ≥ 0.06 sur ce corpus, le
        # plancher vaut 1e-20 — six ordres de grandeur d'écart avec 1e-6.
        # (Le filtre `@@` via une 2e annotation donne EXACTEMENT les mêmes résultats — vérifié
        # sur 4 requêtes — mais chaîner deux annotations sur la même queryset la vidait ; une
        # seule annotation est plus simple et plus sûre.)
        qs = (queryset.annotate(_rank=SearchRank(vecteur, requete))
                      .filter(_rank__gte=SEUIL_LEXICAL)
                      .order_by('-_rank')[:CANDIDATS_PAR_RANKER])
        return list(qs)
    except Exception:
        logger.warning('[memory] recherche lexicale indisponible', exc_info=True)
        return []


def _fusion_rrf(listes):
    """
    Reciprocal Rank Fusion : score = Σ 1/(RRF_K + rang). Puis majoration par la saillance.

    On fusionne sur (source, pk) et non sur l'objet : un même souvenir remonté par les deux
    rankers doit CUMULER, c'est tout l'intérêt de la fusion.
    """
    scores, objets, rangs = {}, {}, {}
    for nom_ranker, source, resultats in listes:
        for rang, obj in enumerate(resultats):
            cle = (source, obj.pk)
            scores[cle] = scores.get(cle, 0.0) + 1.0 / (RRF_K + rang + 1)
            objets[cle] = obj
            rangs.setdefault(cle, {})[f'{nom_ranker}/{source}'] = rang + 1

    hits = []
    for cle, score in scores.items():
        obj = objets[cle]
        # La saillance ne s'applique qu'aux souvenirs : un fragment RAG n'a pas de vécu
        # d'utilisateur derrière lui, seulement un document.
        saillance = getattr(obj, 'salience', 0.0) or 0.0
        hits.append(Hit(obj, cle[0], score * (1 + POIDS_SAILLANCE * saillance), rangs[cle]))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


# ──────────────────────────────────────────────────────────── reindex ────────

def reindex(*, lot=64, limite=None, modeles_obsoletes=False, dry_run=False):
    """
    Calcule les vecteurs manquants, PAR LOT. Rend un résumé `{...}`.

    C'est le complément OBLIGATOIRE de `remember(embed=False)` : sans lui, une écriture sans
    vecteur resterait introuvable en sémantique pour toujours. Les deux vont ensemble — écrire
    d'abord (jamais bloquant, jamais sur le GPU), vectoriser ensuite (par lot, quand la machine
    est libre).

    ⚠ SEUL ENDROIT où la mémoire sollicite le GPU en volume. À déclencher explicitement (commande
    ou tâche), jamais dans le chemin d'une requête utilisateur : la règle d'exploitation de ce
    poste interdit les chargements Ollama enchaînés hors action explicite.

    `modeles_obsoletes=True` reprend AUSSI les lignes vectorisées par un autre modèle — c'est ce
    qui rend une bascule d'embedder possible sans corrompre la colonne : les deux espaces
    vectoriels ne cohabitent que le temps du réindex, et on sait lesquels restent à refaire.
    """
    from ..models import MemoryItem, RagChunk
    from .embed import EMBEDDING_MODEL, decharger, embed_batch, embedder_disponible

    #: Résidence tenue PENDANT le réindex — cf. `embed_batch`. Décharger entre chaque lot
    #: imposerait ~15 cycles charge/décharge sur 940 éléments, et c'est un enchaînement de
    #: chargements qui a précédé le crash du 2026-08-20. On décharge UNE fois, à la fin.
    RESIDENCE_REINDEX = '5m'

    resume = {'embedder_disponible': embedder_disponible(), 'traites': 0, 'echecs': 0,
              'restants': 0, 'dry_run': dry_run}
    if not resume['embedder_disponible']:
        # On ne tente rien : sans le modèle, chaque lot partirait en timeout puis en `[]`, et on
        # aurait dépensé une série d'appels réseau pour rien.
        logger.warning("[memory] reindex : embedder indisponible (modèle tiré ? Ollama démarré ?)")
        return resume

    from django.db.models import Q
    manquant = Q(embedding__isnull=True)
    if modeles_obsoletes:
        manquant |= ~Q(embedding_model=EMBEDDING_MODEL)

    for modele in (MemoryItem, RagChunk):
        qs = modele.objects.filter(manquant).order_by('pk')
        resume['restants'] += qs.count()
        if dry_run:
            continue
        traites_ici = 0
        while True:
            if limite is not None and resume['traites'] >= limite:
                break
            paquet = list(qs[:lot])
            if not paquet:
                break
            vecteurs = embed_batch([o.content for o in paquet],
                                   keep_alive=RESIDENCE_REINDEX)
            if not vecteurs:
                # Lot perdu : on ARRÊTE au lieu de boucler. Les lignes restent sans vecteur (elles
                # seront reprises au prochain passage) — insister ferait tourner à vide.
                resume['echecs'] += len(paquet)
                logger.warning('[memory] reindex : lot de %s échoué, arrêt', len(paquet))
                break
            for obj, vec in zip(paquet, vecteurs):
                obj.embedding = vec
                obj.embedding_model = EMBEDDING_MODEL
            modele.objects.bulk_update(paquet, ['embedding', 'embedding_model'])
            traites_ici += len(paquet)
            resume['traites'] += len(paquet)
        if traites_ici:
            logger.info('[memory] reindex : %s %s vectorisés', traites_ici, modele.__name__)
    if not dry_run:
        resume['restants'] = max(0, resume['restants'] - resume['traites'])
        # Point final OBLIGATOIRE : la résidence tenue pendant l'opération ne doit pas lui
        # survivre. Sans ce déchargement, on aurait remplacé 15 cycles par un squat de VRAM.
        if resume['traites']:
            resume['decharge'] = decharger()
    return resume


# ───────────────────────────────────────────────────────────── forget ────────

def forget(item, *, reason='', hard=False, at=None):
    """
    Invalide un souvenir — `valid_to = maintenant`. Il cesse d'être rappelé, sans disparaître.

    ⚠ `hard=True` SUPPRIME définitivement et n'est justifié QUE par une obligation légale
    (effacement RGPD). Dans tous les autres cas l'invalidation suffit : détruire la ligne
    détruirait aussi la trace de ce qui était tenu pour vrai, donc toute possibilité d'audit.
    """
    from django.utils import timezone

    if item is None:
        return None
    if hard:
        logger.warning('[memory] SUPPRESSION DURE du souvenir #%s (motif : %s)',
                       item.pk, reason or 'non précisé')
        item.delete()
        return None
    item.valid_to = at or timezone.now()
    if reason:
        # Le motif rejoint le contenu plutôt qu'un champ dédié : il fait partie de l'histoire du
        # souvenir, et un champ de plus ne serait lu par personne.
        item.content = f"{item.content}\n\n[invalidé : {reason}]"
    item.save(update_fields=['valid_to', 'content', 'updated_at'])
    return item


# ────────────────────────────────────────────────────────────── merge ────────

def merge(items, *, seuil=0.92):
    """
    PROPOSE de fusionner des souvenirs proches. N'ÉCRIT RIEN.

    Rend une liste de propositions `{'garder': item, 'fusionner': [items], 'similarite': float}`.
    Appliquer une fusion est un geste humain (`appliquer_fusion`) — doctrine « propose-cite-tu-
    valides » : une fusion automatique qui se trompe efface un souvenir qu'on ne peut pas
    reconstruire, et personne ne s'en apercevra.
    """
    items = [i for i in (items or []) if i is not None]
    propositions = []
    vus = set()
    for i, ref in enumerate(items):
        if ref.pk in vus or ref.embedding is None:
            continue
        proches = []
        for autre in items[i + 1:]:
            if autre.pk in vus or autre.embedding is None:
                continue
            sim = _cosinus(ref.embedding, autre.embedding)
            if sim >= seuil:
                proches.append((autre, sim))
        if proches:
            vus.update(a.pk for a, _ in proches)
            vus.add(ref.pk)
            propositions.append({
                'garder': ref,
                'fusionner': [a for a, _ in proches],
                'similarite': min(s for _, s in proches),
            })
    return propositions


def appliquer_fusion(proposition, *, par_utilisateur):
    """
    Applique UNE proposition de `merge()`. Réservé à un geste humain explicite.

    Les souvenirs fusionnés sont CHAÎNÉS (`superseded_by`), pas supprimés : la fusion reste
    réversible et l'historique lisible.
    """
    from django.utils import timezone

    garder = proposition['garder']
    for item in proposition['fusionner']:
        item.superseded_by = garder
        item.valid_to = timezone.now()
        item.save(update_fields=['superseded_by', 'valid_to', 'updated_at'])
    logger.info('[memory] fusion appliquée par %s : #%s absorbe %s',
                par_utilisateur, garder.pk, [i.pk for i in proposition['fusionner']])
    return garder


def _cosinus(a, b):
    import numpy as np
    va, vb = np.asarray(a, dtype='float32'), np.asarray(b, dtype='float32')
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    return 0.0 if not na or not nb else float(va.dot(vb) / (na * nb))


# ───────────────────────────────────────────────────────────── expire ────────

def expire(*, jours_non_approuve=90, dry_run=True):
    """
    Applique les politiques de rétention. Rend un résumé `{...}`.

    ⚠ N'ATTEINT JAMAIS UN SOUVENIR APPROUVÉ. Règle directe de l'incident du 2026-08-19, où une
    purge ciblée a détruit 13 évaluations LLM (GPU dépensé pour rien) : ce qui a été validé par
    un humain ne sort que par un geste humain. Seuls partent les brouillons jamais validés —
    et `dry_run=True` par défaut, pour qu'une purge soit toujours un choix, jamais un défaut.
    """
    from datetime import timedelta

    from django.utils import timezone

    from ..models import MemoryItem

    limite = timezone.now() - timedelta(days=jours_non_approuve)
    candidats = MemoryItem.objects.filter(approved_at__isnull=True, created_at__lt=limite)
    n = candidats.count()
    resume = {'non_approuves_expirables': n, 'jours': jours_non_approuve, 'applique': False}
    if n and not dry_run:
        candidats.delete()
        resume['applique'] = True
        logger.info('[memory] expire() : %s brouillons non approuvés purgés (>%s j)',
                    n, jours_non_approuve)
    return resume
