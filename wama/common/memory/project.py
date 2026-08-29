"""
Projection des faits WAMA vers la mémoire. Doc : `WAMA_MEMORY.md §7` (jalon 4).

CE QU'ELLE FAIT : rendre RAPPELABLE ce que WAMA sait déjà. `RunOutcome` est le journal des gestes
réels de l'utilisateur ; ce module en tire des souvenirs interrogeables en langage naturel.

CE QU'ELLE NE FAIT PAS : recopier. `RunOutcome` reste la SOURCE DE VÉRITÉ — on n'y touche jamais,
et un souvenir projeté pointe la ligne d'origine (`source_app`/`source_object_type`/
`source_object_id`). Dupliquer les faits créerait deux vérités qui divergent, exactement la
maladie déjà diagnostiquée sur les `.md`.

DEUX PROPRIÉTÉS NON NÉGOCIABLES
  1. **ZÉRO APPEL DE MODÈLE.** Ni LLM ni embedding : tout est mécanique (agrégation + gabarit).
     C'est ce qui autorise à s'auto-approuver — il n'y a aucune inférence à valider. Les vecteurs
     se calculent après coup, par lot, via `store.reindex()`.
  2. **IDEMPOTENTE.** Relancer ne duplique pas : un souvenir dont le contenu n'a pas bougé est
     laissé tel quel ; un souvenir périmé est INVALIDÉ puis réécrit, jamais écrasé.

⚠ ON PROJETTE PAR OBJET, PAS PAR GESTE. Une ligne de mémoire par ligne de `RunOutcome`
noierait le magasin sous des milliers d'événements atomiques sans valeur de rappel (« a téléchargé
le 12/08 à 14h03 »). Ce qu'on veut retrouver est l'histoire d'un ITEM : « la transcription 142 a
été corrigée à la main puis exportée ». On agrège donc tous les signaux d'un même objet en UN
souvenir épisodique, réécrit quand l'histoire évolue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Libellés au PASSÉ, à la 3e personne : un souvenir se relit, il ne s'adresse pas à l'utilisateur.
#: Volontairement factuels — « supprimé » ne veut pas dire « mauvais » (cf. docstring `RunOutcome`),
#: et le gabarit ne doit pas glisser du fait vers le jugement.
_LIBELLES = {
    'produit': 'un résultat a été produit',
    'echec': 'la production a échoué',
    'telecharge': 'le résultat a été téléchargé',
    'corrige': 'le résultat a été corrigé à la main',
    'relance': 'le traitement a été relancé',
    'supprime': 'le résultat a été supprimé',
}

#: Contribution de chaque signal à la SAILLANCE (bornée à 1.0). C'est ici que se joue le bénéfice
#: de la « mémoire émotionnelle » SANS rien inférer : on ne devine pas une humeur, on constate un
#: geste. Une correction manuelle pèse le plus parce qu'elle représente du travail humain investi ;
#: une relance signale que le précédent n'a pas suffi.
#: ⚠ `supprime` ne pèse RIEN, volontairement : supprimer peut n'être qu'un ménage, et lui donner
#: du poids reviendrait à lire un jugement dans un geste neutre.
_POIDS_SAILLANCE = {
    'corrige': 0.40,
    'relance': 0.30,
    'telecharge': 0.20,
    'echec': 0.10,
    'produit': 0.0,
    'supprime': 0.0,
}


def project_run_outcomes(*, depuis=None, limite=None, dry_run=False, user=None):
    """
    Projette les gestes de `RunOutcome` en souvenirs épisodiques. Rend un résumé `{...}`.

    `depuis` : ne considérer que les objets touchés après cette date (projection incrémentale).
    `user`   : restreindre à un utilisateur (utile pour un test ou un rejeu ciblé).
    """
    from ..models import RunOutcome

    resume = {'objets': 0, 'crees': 0, 'inchanges': 0, 'reecrits': 0, 'ignores_sans_user': 0,
              'dry_run': dry_run}

    qs = RunOutcome.objects.all()
    if depuis is not None:
        qs = qs.filter(occurred_at__gte=depuis)
    if user is not None:
        qs = qs.filter(user=user)

    # Regroupement par OBJET. `values_list` plutôt que `.distinct()` sur des lignes complètes :
    # on ne veut que les clés, et les charger toutes en mémoire pour des dizaines de milliers de
    # lignes serait inutilement coûteux.
    cles = (qs.exclude(user__isnull=True)
              .values_list('app', 'object_type', 'object_id', 'user_id')
              .distinct().order_by('app', 'object_type', 'object_id'))

    resume['ignores_sans_user'] = (qs.filter(user__isnull=True)
                                     .values_list('app', 'object_type', 'object_id')
                                     .distinct().count())

    for app, otype, oid, uid in cles:
        if limite is not None and resume['objets'] >= limite:
            break
        resume['objets'] += 1

        signaux = list(RunOutcome.objects
                       .filter(app=app, object_type=otype, object_id=oid, user_id=uid)
                       .order_by('occurred_at'))
        if not signaux:
            continue

        texte = _compose(app, otype, oid, signaux)
        saillance = _salience(signaux)

        etat = _upsert(app, otype, oid, uid, texte, saillance, dry_run=dry_run)
        resume[etat] += 1

    if not dry_run:
        logger.info('[memory.project] %s objets → %s créés, %s réécrits, %s inchangés',
                    resume['objets'], resume['crees'], resume['reecrits'], resume['inchanges'])
    return resume


def _compose(app, otype, oid, signaux):
    """
    Rédige l'histoire d'un objet à partir de ses signaux. Gabarit pur — aucun modèle appelé.

    Le texte porte les IDENTIFIANTS en clair (`app`, type, pk, clés de modèles) : c'est ce que le
    ranker lexical retrouvera, là où le vectoriel n'a aucune prise sur un `#142` ou un `whisper-
    large-v3`. Les deux moitiés du rappel hybride sont donc servies par la même phrase.
    """
    from django.utils import timezone

    premier, dernier = signaux[0], signaux[-1]

    # On décrit une HISTOIRE, pas un journal : chaque geste apparaît une fois, dans l'ordre de sa
    # PREMIÈRE occurrence, et sa répétition est repliée en « (N fois) » à l'intérieur même de la
    # phrase. Une clause « Répétitions : … » séparée réécrirait les mêmes libellés une seconde
    # fois — du bruit pur, qui dilue en plus le vecteur du souvenir.
    compte = {}
    for s in signaux:
        compte[s.signal] = compte.get(s.signal, 0) + 1

    faits, vus = [], set()
    for s in signaux:
        if s.signal in vus:
            continue
        vus.add(s.signal)
        libelle = _LIBELLES.get(s.signal, s.signal)
        n = compte[s.signal]
        faits.append(f"{libelle} ({n} fois)" if n > 1 else libelle)

    modeles = []
    for s in signaux:
        for k in (s.model_keys or []):
            if k not in modeles:
                modeles.append(k)

    debut = timezone.localtime(premier.occurred_at).strftime('%Y-%m-%d')
    fin = timezone.localtime(dernier.occurred_at).strftime('%Y-%m-%d')
    periode = debut if debut == fin else f"du {debut} au {fin}"

    phrase = f"Dans {app}, sur {otype} #{oid} ({periode}) : " + ", puis ".join(faits) + "."
    if modeles:
        phrase += " Modèles impliqués : " + ", ".join(modeles) + "."
    return phrase


def _salience(signaux):
    """
    Saillance dans [0, 1], DÉRIVÉE des gestes — jamais saisie, jamais inférée.

    On somme les contributions des signaux DISTINCTS (pas de chaque occurrence) : trois
    téléchargements ne rendent pas un item trois fois plus marquant, alors qu'une correction
    ET une relance disent deux choses différentes.
    """
    distincts = {s.signal for s in signaux}
    return min(1.0, sum(_POIDS_SAILLANCE.get(s, 0.0) for s in distincts))


def _upsert(app, otype, oid, uid, texte, saillance, *, dry_run):
    """
    Écrit ou met à jour LE souvenir de cet objet. Rend 'crees' | 'reecrits' | 'inchanges'.

    Mise à jour = invalider l'ancien puis écrire le nouveau. On n'écrase pas : l'histoire de ce
    qui était tenu pour vrai a autant de valeur que l'état courant, et c'est la seule façon de
    comprendre après coup pourquoi un rappel disait autre chose la semaine dernière.
    """
    from ..models import MemoryItem
    from .store import content_hash, forget

    actif = (MemoryItem.objects
             .filter(source_app=app, source_object_type=otype, source_object_id=oid,
                     user_id=uid, provenance=MemoryItem.PROV_PROJECTION, valid_to__isnull=True)
             .order_by('-created_at').first())

    if actif is not None:
        if actif.content_hash == content_hash(texte):
            if actif.salience != saillance and not dry_run:
                # La saillance peut bouger sans que le texte change (nouveau geste du même type
                # déjà décrit). Elle est DÉRIVÉE, donc on la recalcule sans réécrire le souvenir.
                actif.salience = saillance
                actif.save(update_fields=['salience', 'updated_at'])
            return 'inchanges'
        if dry_run:
            return 'reecrits'
        forget(actif, reason='projection mise à jour')
        etat = 'reecrits'
    else:
        if dry_run:
            return 'crees'
        etat = 'crees'

    _write(app, otype, oid, uid, texte, saillance)
    return etat


def _write(app, otype, oid, uid, texte, saillance):
    """Écriture effective — `embed=False` : la projection ne touche JAMAIS le GPU."""
    from django.contrib.auth.models import User

    from ..models import MemoryItem
    from .store import remember

    remember(
        texte,
        kind=MemoryItem.KIND_EPISODIC,
        provenance=MemoryItem.PROV_PROJECTION,
        user=User.objects.filter(pk=uid).first(),
        subject=app,
        source_app=app,
        source_object_type=otype,
        source_object_id=oid,
        salience=saillance,
        # Auto-approuvé : une projection ne fait que pointer un fait déjà en base, il n'y a
        # aucune inférence à valider. C'est la SEULE provenance qui a ce droit.
        approved=True,
        # ⚠ Aucun appel de modèle. Les vecteurs viendront par `store.reindex()`, par lot.
        embed=False,
    )
