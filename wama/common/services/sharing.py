"""PARTAGE d'un élément de file — la première INTERFACE du mécanisme de visibilité.

DEMANDE DE FABIEN (2026-09-08) : le menu contextuel / le « … » d'une card doit porter
« Partager », et « on parle exclusivement de l'UI, pas du fonctionnement qui est déjà en place ».
C'est exact, et c'est ce que ce module respecte : il n'invente aucun axe de droit, il POSE une
valeur que le substrat lit déjà.

CE QUI EXISTAIT (et qui n'a pas bougé)
--------------------------------------
`ScopedVisibility` (`common/models.py`) : `visibility` ∈ privé / unité / projet / public, plus
`scope_org_unit` et `scope_project`. Les lectures sont filtrées par `scoped_visible_q(user)`.
`PROFILES_PERMISSIONS §7` cadre le tout depuis le 2026-07-31, et §7.5 nommait le trou :
**« il n'existe aucune interface de partage »** — il fallait passer par l'admin Django.
Mesuré le 2026-09-08 : `shareable_models` et `scoped_reads` sont à **10/10** au rapport de
grille. Le mécanisme est donc prêt ; c'est le geste qui manquait. (La photo « 3 ✅ / 6 ❌ » du
§7.4bis datait du 31/07 et était périmée.)

CE QUE CE MODULE FAIT, ET SURTOUT CE QU'IL NE FAIT PAS
------------------------------------------------------
Il écrit `visibility` (+ le scope) sur l'élément ET sur son LOT. Rien d'autre.

⚠⚠ LE LOT N'EST PAS UN DÉTAIL. `PROFILES_PERMISSIONS §7.4bis` le dit noir sur blanc : « une card
partagée sans son batch **n'apparaît pas** » — la file est construite à partir des LOTS. Partager
la seule card produirait un partage qui n'échoue pas et ne marche pas : le destinataire ne verrait
rien, et rien ne le lui dirait. C'est le pire des retours, et c'est pour ça que la propagation est
dans le SERVICE et non à la charge de l'appelant.

⚠ UNE PORTÉE N'ACCORDE AUCUN DROIT D'ÉCRITURE. Elle est en lecture seule **par construction**, pas
par vigilance : `visibility` ne dit QUE qui voit. Les droits sur une INSTANCE vivent dans
`ObjectGrant` (`WAMA_COLLABORATION §4.3` ; ~~S3 `AccessGrant`~~, cité ici jusqu'au 2026-10-03,
porte les droits sur une APP : `PROFILES_PERMISSIONS:392`, « deux tables ») : la demande de
propriété et de collaboration (`access_requests`, 2026-10-03), et depuis le 2026-10-06 le PARTAGE
À UNE PERSONNE (`share_with_person`, plus bas) — seul geste qui accorde la collaboration (E1).
L'UI doit donc DIRE « lecture seule » pour une portée, sans quoi elle promettrait l'écriture.

⚠ Seul le PROPRIÉTAIRE partage. Ce n'est pas une politique inventée ici : `scoped_visible_q`
donne déjà à un destinataire la seule LECTURE, donc lui laisser repartager reviendrait à créer un
droit qui n'existe nulle part.
"""
from wama.common.models import ScopedVisibility, user_projects, user_scope_org_ids
from wama.common.utils.batch_common import batch_of

#: Les portées, DÉRIVÉES du mixin — jamais recopiées. Une 5ᵉ valeur ajoutée au modèle apparaît
#: ici sans geste, et l'UI la propose sans qu'on y touche.
PORTEES = dict(ScopedVisibility.VIS_CHOICES)

#: Les MODES de partage d'une card (`WAMA_COLLABORATION §3bis.1`, décision de Fabien 2026-09-30) —
#: une seule déclaration, lue par la pastille de la card, le menu « … » (« Mon accès ») et la
#: modale « Partager… ». `available` : ce que le code SAIT faire ; un mode non construit est
#: montré GRISÉ (« bientôt ») — décision de Fabien, 2026-10-03. La COLLABORATION existe depuis le
#: même jour (E1-E5 tranchées : accordée à une PERSONNE, sur demande acceptée) ; la MODIFICATION
#: attend les variantes (marche 8b).
#: L'icône n'est pas décorative : le niveau se lit au mot ET au signe, jamais à la seule couleur.
SHARE_MODES = (
    {'key': 'read', 'label': 'Lecture seule', 'icon': '👁', 'available': True},
    {'key': 'fork', 'label': 'Modification', 'icon': '✎', 'available': False},
    {'key': 'collaborate', 'label': 'Collaboration', 'icon': '👥', 'available': True},
)


def share_mode(key: str) -> dict:
    """La déclaration d'un mode (`SHARE_MODES`), ou celle de la lecture si la clé est inconnue."""
    return next((m for m in SHARE_MODES if m['key'] == key), SHARE_MODES[0])
#: Le mode d'un partage tant qu'aucun autre n'existe : la lecture (voir `SHARE_MODES`).
CURRENT_SHARE_MODE = SHARE_MODES[0]


def shares_overview(user, limit: int = 200) -> dict:
    """Ce que montre la page « Partages » (`WAMA_COLLABORATION §5.3`, 2026-10-03) : ce que `user` a
    PARTAGÉ (portée, collaborateurs, de quoi retirer) et ce qu'on LUI a partagé (de qui, avec quel
    accès), plus les demandes en attente dans les deux sens.

    L'unité est l'ENTRÉE de file (le lot, ou la card sans lot) — celle du partage, du rangement et
    de la collaboration. Les modèles se DÉRIVENT des surfaces enregistrées (`PreviewRegistry`) :
    aucune app n'est nommée ici."""
    from django.db.models import Q
    from wama.common.models import ObjectGrant
    from wama.common.services.access_requests import _label, collaboration_grant, entry_of, target
    from wama.common.services.reception import owner_label
    from wama.common.utils.batch_common import batch_model_for
    from wama.common.utils.preview_registry import PreviewRegistry
    from wama.common.utils.scoping import listable_by

    def describe(entry, surface, element_model, mine):
        is_lot = entry._meta.model is batch_model_for(element_model)
        row = {'app': entry._meta.app_label, 'surface': surface, 'pk': entry.pk,
               'nature': 'lot' if is_lot else 'element',
               'label': (f"Lot #{entry.pk} · {getattr(entry, 'total', '?')} card(s)" if is_lot
                         else _label(entry)),
               'scope': scope_label(entry), 'scope_since': scope_since(entry),
               'url': f'/{entry._meta.app_label}/'}
        if mine:
            # Les PERSONNES (partage nominatif, ou collaboration accordée sur demande) : une
            # par personne, son mode, depuis quand — et de quoi la retirer (E5).
            row['persons'] = persons_of(entry)
        else:
            row['owner'] = owner_label(entry)
            row['mode'] = share_mode('collaborate' if collaboration_grant(user, entry) else 'read')
        return row

    shared, received, seen = [], [], set()
    import logging
    from django.db import DatabaseError, transaction
    for surface in PreviewRegistry.list_registered():
        model = PreviewRegistry.get_model(surface)
        manager = getattr(model, '_default_manager', None)
        if model is None or not hasattr(manager, 'visible_to'):
            continue
        # Une surface dont la table ne suit pas son modèle (jumelle de bac à sable non migrée,
        # mesuré le 2026-10-03 sur `writer_01`) ne doit pas faire tomber toute la page.
        try:
            with transaction.atomic():
                # Partagé par une PORTÉE, ou à des PERSONNES seulement (élément resté privé).
                named = (ObjectGrant.in_force().filter(object_type=model._meta.label,
                                                       level__in=ObjectGrant.VISIBLE_LEVELS)
                         .values('object_id'))
                mine = list(manager.filter(user=user)
                            .filter(~Q(visibility=ScopedVisibility.VIS_PRIVATE) | Q(pk__in=named))
                            [:limit])
                theirs = list(listable_by(manager.all(), user).exclude(user=user)[:limit])
        except DatabaseError as exc:
            logging.getLogger(__name__).warning('[partages] surface %s illisible : %s', surface, exc)
            continue
        for element, bucket, is_mine in [(e, shared, True) for e in mine] + \
                                         [(e, received, False) for e in theirs]:
            entry = entry_of(element)
            key = (entry._meta.label, entry.pk)
            if key not in seen:
                seen.add(key)
                bucket.append(describe(entry, surface, model, is_mine))

    incoming, outgoing = [], []
    for grant in ObjectGrant.objects.filter(state=ObjectGrant.STATE_REQUESTED).select_related(
            'beneficiary'):
        obj = target(grant)
        if obj is None:
            continue
        row = {'id': grant.pk, 'level': grant.get_level_display(), 'label': _label(obj),
               'app': obj._meta.app_label, 'who': grant.beneficiary.username,
               'created_at': grant.created_at}
        if getattr(obj, 'user_id', None) == user.pk:
            incoming.append(row)
        elif grant.beneficiary_id == user.pk:
            outgoing.append(row)
    return {'shared': shared, 'received': received, 'incoming': incoming, 'outgoing': outgoing}


def scope_label(element) -> str:
    """La portée d'un élément partagé, dite par sa CIBLE (« LESCOT », « Projet X », « Public ») —
    ce que la pastille de la card affiche chez son propriétaire. '' s'il est privé."""
    vis = getattr(element, 'visibility', ScopedVisibility.VIS_PRIVATE)
    if vis == ScopedVisibility.VIS_PRIVATE:
        return ''
    if vis == ScopedVisibility.VIS_UNIT and getattr(element, 'scope_org_unit', None):
        return element.scope_org_unit.name
    if vis == ScopedVisibility.VIS_PROJECT and getattr(element, 'scope_project', None):
        return str(element.scope_project)
    return PORTEES.get(vis, vis)


class RefusDePartage(Exception):
    """Refus MOTIVÉ : le motif est destiné à l'utilisateur, pas au journal."""


# ── CONSENTEMENT : partager un élément qui porte une PERSONNE (2026-09-30) ──────────────────
# Décision de Fabien : « s'il partage, c'est pour le rendre atteignable aux autres utilisateurs ;
# il faut juste le prévenir et lui faire valider le consentement. Sinon, il annule. Il peut aussi
# retirer le partage à tout moment. » L'élément DÉCLARE ce qu'il porte d'une personne
# (`share_consent_subject()`) ; ce module n'en connaît aucun. Le texte validé est tracé
# (`common.ShareConsent`), le retrait aussi.

#: Le texte que l'on fait VALIDER. Versionné par sa date : une ligne de `ShareConsent` garde le
#: texte EXACT, donc changer ce texte ne réécrit jamais ce qui a été consenti.
CONSENT_STATEMENT = (
    "Cet élément contient {subject}. En le partageant, je le rends utilisable par les personnes "
    "de la portée choisie. J'atteste qu'il s'agit de la mienne, ou que j'ai l'accord de la ou des "
    "personnes concernées pour ce partage. Je peux retirer ce partage à tout moment."
)


class ConsentRequired(RefusDePartage):
    """Le partage d'un élément personnel attend le consentement de celui qui partage."""

    def __init__(self, subject: str):
        self.subject = subject
        self.statement = CONSENT_STATEMENT.format(subject=subject)
        super().__init__(f"consentement requis : cet élément contient {subject}")


def consent_subject(element) -> str:
    """Ce que l'élément porte d'une personne (« la voix d'une personne »), ou '' — DÉCLARÉ par
    son modèle (`share_consent_subject()`). Un modèle qui ne déclare rien n'en demande pas."""
    declared = getattr(element, 'share_consent_subject', None)
    try:
        return (declared() if callable(declared) else '') or ''
    except Exception:
        return ''


def _consent_gate(subjects, visibility, consent: bool) -> str:
    """Le sujet qui exige un consentement pour cette portée, ou '' ; lève s'il manque."""
    subject = next((s for s in subjects if s), '')
    if subject and visibility != ScopedVisibility.VIS_PRIVATE and not consent:
        raise ConsentRequired(subject)
    return subject


def _record_consent(user, element, visibility, unite, projet, subject):
    """Une ligne par geste sur un élément personnel : partage consenti ou retrait."""
    from wama.common.models import ShareConsent
    withdrawal = visibility == ScopedVisibility.VIS_PRIVATE
    ShareConsent.objects.create(
        object_type=element._meta.label, object_id=element.pk,
        user=user if getattr(user, 'pk', None) else None,
        username=getattr(user, 'username', '') or '',
        visibility=visibility, scope_org_unit_id=unite, scope_project_id=projet,
        subject=subject, statement='' if withdrawal else CONSENT_STATEMENT.format(subject=subject))


def portees_offrables(user) -> list:
    """Ce que CET utilisateur peut offrir, avec les cibles réelles de chaque portée.

    Rendu : liste de {`valeur`, `libelle`, `cibles`: [{id, libelle}] | None}.
    Une portée sans cible n'est PAS offerte : proposer « Unité » à quelqu'un dont le profil ne
    porte aucune affiliation afficherait un choix qui ne peut pas aboutir. C'est la même règle
    que les attributs du glisser-déposer — *ce qui n'est pas déclaré n'existe pas*.
    """
    from wama.common.models import OrgUnit, Project

    offres = [
        {'valeur': ScopedVisibility.VIS_PRIVATE,
         'libelle': PORTEES[ScopedVisibility.VIS_PRIVATE], 'cibles': None},
    ]

    # UNITÉ — les unités qui COUVRENT l'utilisateur (ses rattachements et leurs ancêtres).
    # Partager au labo est légitime pour un membre d'une équipe du labo : c'est exactement
    # l'ensemble que `scoped_visible_q` accepte en lecture, donc offrir autre chose créerait
    # un partage que personne ne verrait.
    ids = user_scope_org_ids(user)
    if ids:
        # `OrgUnit.Meta.ordering = ['name']` : pas de tri à repréciser. Le TYPE est affiché avec
        # le nom parce que l'arbre mêle université, labo et équipe — « LESCOT » seul ne dit pas
        # à quelle échelle on partage, et c'est précisément ce que l'utilisateur choisit.
        unites = [{'id': u.id, 'libelle': f"{u.name} ({u.get_unit_type_display()})"}
                  for u in OrgUnit.objects.filter(id__in=ids)]
        if unites:
            offres.append({'valeur': ScopedVisibility.VIS_UNIT,
                           'libelle': PORTEES[ScopedVisibility.VIS_UNIT], 'cibles': unites})

    # PROJET — ceux dont il est membre. Le scope projet TRAVERSE les organisations
    # (partenaires d'un autre labo) : c'est sa raison d'être, cf. le mixin.
    pids = user_projects(user)
    if pids:
        projets = [{'id': p.id, 'libelle': str(p)}
                   for p in Project.objects.filter(id__in=pids)]
        if projets:
            offres.append({'valeur': ScopedVisibility.VIS_PROJECT,
                           'libelle': PORTEES[ScopedVisibility.VIS_PROJECT], 'cibles': projets})

    offres.append({'valeur': ScopedVisibility.VIS_PUBLIC,
                   'libelle': PORTEES[ScopedVisibility.VIS_PUBLIC], 'cibles': None})
    return offres


def _verifier_cible(user, visibility, org_unit_id, project_id):
    """Rend le couple (org_unit_id, project_id) NETTOYÉ, ou lève.

    Nettoyé, pas seulement validé : passer d'« unité » à « public » doit EFFACER le scope
    précédent. Sans ça un objet resterait rattaché à une unité qu'il ne concerne plus, et le
    jour où on le repasserait en `unit` il redeviendrait visible par cette unité-là sans que
    personne ne l'ait demandé.
    """
    if visibility == ScopedVisibility.VIS_UNIT:
        if not org_unit_id:
            raise RefusDePartage("aucune unité choisie")
        if int(org_unit_id) not in user_scope_org_ids(user):
            raise RefusDePartage("cette unité ne vous couvre pas")
        return int(org_unit_id), None
    if visibility == ScopedVisibility.VIS_PROJECT:
        if not project_id:
            raise RefusDePartage("aucun projet choisi")
        if int(project_id) not in user_projects(user):
            raise RefusDePartage("vous n'êtes pas membre de ce projet")
        return None, int(project_id)
    return None, None


def _porte_la_visibilite(obj) -> bool:
    return isinstance(obj, ScopedVisibility) or hasattr(obj, 'visibility')


def _poser(objet, visibility, unite, projet, user=None):
    objet.visibility = visibility
    objet.scope_org_unit_id = unite
    objet.scope_project_id = projet
    objet.save(update_fields=['visibility', 'scope_org_unit', 'scope_project'])
    _record_scope_share(user, objet, visibility, unite, projet)


def _record_scope_share(user, obj, visibility, unite, projet) -> None:
    """La MÉMOIRE DATÉE d'un partage par portée (2026-10-06, Fabien : *« autant rester homogène »*
    avec le partage à une personne) — une ligne `ObjectGrant` sans bénéficiaire
    (`WAMA_COLLABORATION §2.1`). Réappliquer la même portée garde la date d'origine ; en changer, ou
    revenir au privé, RETIRE la ligne en cours (la mémoire garde les deux). Jamais lue pour décider
    qui voit : c'est la colonne `visibility` qui le dit."""
    from django.utils import timezone
    from wama.common.models import ObjectGrant
    current = ObjectGrant.in_force().filter(object_type=obj._meta.label, object_id=obj.pk,
                                            beneficiary__isnull=True)
    shared = visibility != ScopedVisibility.VIS_PRIVATE
    if shared and current.filter(visibility=visibility, scope_org_unit_id=unite,
                                 scope_project_id=projet).exists():
        return
    now = timezone.now()
    current.update(state=ObjectGrant.STATE_REVOKED, answered_at=now)
    if shared:
        ObjectGrant.objects.create(object_type=obj._meta.label, object_id=obj.pk,
                                   visibility=visibility, scope_org_unit_id=unite,
                                   scope_project_id=projet, level=ObjectGrant.LEVEL_READ,
                                   state=ObjectGrant.STATE_GRANTED,
                                   granted_by=user if getattr(user, 'pk', None) else None,
                                   answered_at=now)


def scope_since(obj):
    """Depuis quand `obj` est partagé à sa portée COURANTE, ou None (privé, ou partagé avant que
    la date ne soit tenue — le 2026-10-06 : on ne l'invente pas)."""
    from wama.common.models import ObjectGrant
    vis = getattr(obj, 'visibility', ScopedVisibility.VIS_PRIVATE)
    if vis == ScopedVisibility.VIS_PRIVATE:
        return None
    line = (ObjectGrant.in_force()
            .filter(object_type=obj._meta.label, object_id=obj.pk, beneficiary__isnull=True,
                    visibility=vis, scope_org_unit_id=getattr(obj, 'scope_org_unit_id', None),
                    scope_project_id=getattr(obj, 'scope_project_id', None))
            .order_by('-created_at').first())
    return (line.answered_at or line.created_at) if line is not None else None


def partager(user, element, visibility, org_unit_id=None, project_id=None,
             consent: bool = False) -> dict:
    """Applique la portée à l'élément ET à son lot. Rend un compte-rendu.

    Le compte-rendu DIT ce qui a été touché (`lot` : id du lot propagé, ou None) : c'est ce qui
    permet à l'UI de ne pas annoncer un partage plus large qu'il n'est. Un service qui rend
    `True` laisse l'appelant inventer le message.

    `consent` : celui qui partage a validé le texte de consentement. Exigé (`ConsentRequired`)
    pour un élément qui DÉCLARE porter une personne, dès que la portée dépasse le privé.
    """
    if visibility not in PORTEES:
        raise RefusDePartage(f"portée inconnue : {visibility!r}")
    if not _porte_la_visibilite(element):
        # Une app non portée sur `ScopedVisibility` ne doit pas échouer en 500 : elle doit
        # DIRE qu'elle n'est pas partageable (grille : critère `shareable_models`).
        raise RefusDePartage("cet élément n'est pas partageable (app non portée)")
    if getattr(element, 'user_id', None) != getattr(user, 'id', None):
        raise RefusDePartage("seul le propriétaire peut partager")

    unite, projet = _verifier_cible(user, visibility, org_unit_id, project_id)
    subject = _consent_gate([consent_subject(element)], visibility, consent)
    newly_in_project = _newly_in_project(element, visibility, projet)
    _poser(element, visibility, unite, projet, user)
    if subject:
        _record_consent(user, element, visibility, unite, projet, subject)

    lot = batch_of(element)
    lot_touche = None
    if lot is not None and _porte_la_visibilite(lot):
        _poser(lot, visibility, unite, projet, user)
        lot_touche = lot.id
    if newly_in_project:
        _notify_project_members(user, element, projet)

    return {'visibility': visibility, 'libelle': PORTEES[visibility],
            'org_unit_id': unite, 'project_id': projet,
            'lot': lot_touche, 'elements': 1,
            # Le lot EXISTE mais ne porte pas la visibilité : le partage est alors incomplet et
            # il faut le dire, pas le taire (§7.4bis : 🔶 si un seul des deux modèles l'a).
            'lot_non_partageable': lot is not None and lot_touche is None}


def partager_lot(user, lot, modele_element, visibility,
                 org_unit_id=None, project_id=None, consent: bool = False) -> dict:
    """Partage un LOT ENTIER : le lot et TOUS ses éléments.

    Question de Fabien (2026-09-08) : « est-ce que le partage fonctionne pour les batch ? » Il
    ne fonctionnait PAS — la card mère de lot ne porte pas `data-preview-url`, donc l'entrée
    n'apparaissait même pas. C'est pourtant le geste le plus naturel : `imager/views.py:231`
    dit que « le batch est l'unité de partage », et `models_gen` le répète (« unité de partage
    F7 »). Le manque était dans l'UI, pas dans l'intention.

    ⚠⚠ LA DESCENTE AUX ÉLÉMENTS EST UNE EXIGENCE, exactement symétrique de la remontée au lot :
    un lot partagé dont les éléments restent privés s'affiche chez le destinataire… VIDE. Le
    filtre de lecture s'applique aux deux niveaux, donc le geste doit écrire aux deux.
    """
    if visibility not in PORTEES:
        raise RefusDePartage(f"portée inconnue : {visibility!r}")
    if not _porte_la_visibilite(lot):
        raise RefusDePartage("ce lot n'est pas partageable (app non portée)")
    if getattr(lot, 'user_id', None) != getattr(user, 'id', None):
        raise RefusDePartage("seul le propriétaire peut partager")

    unite, projet = _verifier_cible(user, visibility, org_unit_id, project_id)
    from wama.common.utils.batch_common import batch_elements
    elements = list(batch_elements(lot, modele_element))
    # Le consentement se demande AVANT d'écrire quoi que ce soit : un lot à moitié partagé parce
    # qu'un élément personnel a refusé en cours de route serait un partage à trous.
    subjects = {e.pk: consent_subject(e) for e in elements}
    _consent_gate([consent_subject(lot), *subjects.values()], visibility, consent)
    newly_in_project = _newly_in_project(lot, visibility, projet)
    _poser(lot, visibility, unite, projet, user)

    touches, non_partageables = 0, 0
    for element in elements:
        if not _porte_la_visibilite(element):
            non_partageables += 1
            continue
        _poser(element, visibility, unite, projet, user)
        if subjects.get(element.pk):
            _record_consent(user, element, visibility, unite, projet, subjects[element.pk])
        touches += 1
    if newly_in_project:
        _notify_project_members(user, lot, projet)

    return {'visibility': visibility, 'libelle': PORTEES[visibility],
            'org_unit_id': unite, 'project_id': projet,
            'lot': lot.id, 'elements': touches,
            # On COMPTE ce qui n'a pas suivi au lieu de le taire : un lot dont la moitié des
            # éléments reste privée est un partage à trous, et le destinataire n'en saura rien.
            'elements_non_partageables': non_partageables,
            'lot_non_partageable': False}


# ── PARTAGE À UNE PERSONNE + PRÉVENIR LE DESTINATAIRE (2026-10-06, N1) ──────────────────────
# Question de Fabien : « on ne peut pas partager à un utilisateur seul ». Exact — `ScopedVisibility`
# n'a que quatre portées. La réponse était écrite (`WAMA_COLLABORATION §2.1`, §4.3, §4.5) : un
# partage à une personne est une LIGNE `ObjectGrant` (bénéficiaire = la personne, niveau = le mode,
# état accordé), lue par `scoped_visible_q` en extension de ses portées. Rien d'autre n'est créé :
# la ligne est le droit ET sa mémoire (qui, à qui, quel mode, depuis quand) — et un changement de
# mode RETIRE l'ancienne ligne au lieu de l'écraser.
# Même propagation que la portée, pour la même raison (la file se construit à partir des lots) :
# un élément partagé l'est avec son lot, un lot avec ses éléments.
# Le mode suit E1 (2026-10-03) : l'écriture — la collaboration — ne s'accorde qu'à une personne
# nommée ; c'est exactement ce geste-ci.

#: Le mot qui désigne le partage à une personne dans la mémoire du consentement (`ShareConsent`).
PERSON_SCOPE = 'person'


def _person_objects(target, element_model, nature: str) -> list:
    """Ce qu'un partage à une personne couvre : l'élément et son lot, ou le lot et ses éléments."""
    from wama.common.utils.batch_common import batch_elements
    if nature == 'lot':
        return [target] + [e for e in batch_elements(target, element_model)
                           if _porte_la_visibilite(e)]
    lot = batch_of(target)
    return [target] + ([lot] if lot is not None and _porte_la_visibilite(lot) else [])


def _newly_in_project(obj, visibility, project_id) -> bool:
    """Le geste fait-il ENTRER l'élément dans un projet (N1 : ses membres sont prévenus) ? Une
    portée déjà posée qu'on réapplique ne prévient personne une seconde fois."""
    return (visibility == ScopedVisibility.VIS_PROJECT and bool(project_id)
            and (getattr(obj, 'visibility', '') != ScopedVisibility.VIS_PROJECT
                 or getattr(obj, 'scope_project_id', None) != project_id))


def _notify_project_members(owner, obj, project_id) -> int:
    """N1 — les MEMBRES d'un projet reçoivent la notification dans WAMA. Une unité ou le public,
    non (`WAMA_COLLABORATION §5.2` : une unité hérite à ses sous-unités, ce serait tout un labo ou
    toute l'université)."""
    from django.contrib.auth import get_user_model
    from wama.common.models import Project, ProjectMembership
    from wama.common.services.access_requests import _label
    from wama.common.utils.notifications import _job_url, notify_in_app
    members = get_user_model().objects.filter(
        pk__in=ProjectMembership.objects.filter(project_id=project_id).values('user_id'),
        is_active=True).exclude(pk=owner.pk)
    project = Project.objects.filter(pk=project_id).first()
    return notify_in_app(list(members), 'share_received',
                         f"{owner.username} partage « {_label(obj)} » avec le projet {project}",
                         body=f"{obj._meta.app_label} — 👁 Lecture seule. Vous le retrouvez dans "
                              "votre file, et dans « Mes partages ».",
                         url=_job_url(obj), app=obj._meta.app_label, item=obj)


def share_with_person(user, target, element_model, recipient, level: str = 'read', *,
                      nature: str = 'element', surface: str = '', consent: bool = False) -> dict:
    """Partage `target` (un élément, ou un lot si `nature='lot'`) avec UNE personne, dans un mode
    déclaré (`SHARE_MODES`, disponible). Le destinataire est prévenu (N1) : dans WAMA, et par
    e-mail selon son profil — un partage à UNE personne est le seul qui envoie un e-mail
    (`WAMA_COLLABORATION §5.2`). Rend un compte-rendu."""
    from django.db import transaction
    from django.utils import timezone
    from wama.common.models import ObjectGrant
    from wama.common.services.access_requests import _label
    from wama.common.utils.notifications import _job_url, notify_in_app, notify_user

    if not _porte_la_visibilite(target):
        raise RefusDePartage("cet élément n'est pas partageable (app non portée)")
    if getattr(target, 'user_id', None) != getattr(user, 'id', None):
        raise RefusDePartage("seul le propriétaire peut partager")
    if recipient is None or recipient.pk == user.pk:
        raise RefusDePartage("choisissez une autre personne que vous")
    mode = next((m for m in SHARE_MODES if m['key'] == level), None)
    if mode is None:
        raise RefusDePartage(f"mode inconnu : {level!r}")
    if not mode['available']:
        raise RefusDePartage(f"le mode « {mode['label']} » n'existe pas encore")

    objects = _person_objects(target, element_model, nature)
    subjects = {o.pk: consent_subject(o) for o in objects if o._meta.model is element_model}
    _consent_gate([consent_subject(target), *subjects.values()], PERSON_SCOPE, consent)
    now = timezone.now()
    with transaction.atomic():
        for obj in objects:
            lines = ObjectGrant.objects.filter(object_type=obj._meta.label, object_id=obj.pk,
                                               beneficiary=recipient)
            current = ObjectGrant.in_force().filter(pk__in=lines.values('pk'),
                                                    level__in=ObjectGrant.VISIBLE_LEVELS)
            if current.filter(level=level).exists():
                continue
            # Changer de mode RETIRE l'ancienne ligne : la mémoire garde les deux.
            current.update(state=ObjectGrant.STATE_REVOKED, answered_at=now)
            # Une DEMANDE en attente de ce niveau devient le droit : la même ligne (§4.3).
            pending = lines.filter(level=level, state=ObjectGrant.STATE_REQUESTED).first()
            if pending is not None:
                pending.state, pending.granted_by, pending.answered_at = (
                    ObjectGrant.STATE_GRANTED, user, now)
                pending.save(update_fields=['state', 'granted_by', 'answered_at'])
            else:
                ObjectGrant.objects.create(object_type=obj._meta.label, object_id=obj.pk,
                                           surface=surface, beneficiary=recipient, level=level,
                                           state=ObjectGrant.STATE_GRANTED, granted_by=user,
                                           answered_at=now)
        for obj in objects:
            if subjects.get(obj.pk):
                _record_consent(user, obj, PERSON_SCOPE, None, None, subjects[obj.pk])

    what = ("vous pouvez en modifier les réglages et le relancer ; la suppression reste à son "
            "propriétaire" if level == ObjectGrant.LEVEL_COLLABORATE else
            "vous pouvez le voir, le télécharger et le dupliquer")
    title = f"{user.username} vous partage « {_label(target)} »"
    body = (f"{target._meta.app_label} — {mode['icon']} {mode['label']} : {what}. "
            "Vous le retrouvez dans votre file, et dans « Mes partages ».")
    notify_in_app([recipient], 'share_received', title, body=body, url=_job_url(target, surface),
                  app=target._meta.app_label, item=target)
    profile = getattr(recipient, 'profile', None)
    if profile is None or getattr(profile, 'notify_email', True):
        notify_user(recipient, f"[WAMA] {title}", body)
    return {'person': recipient.username, 'mode': mode['key'], 'libelle': mode['label'],
            'objects': len(objects)}


def unshare_person(user, target, beneficiary) -> int:
    """Retire à `beneficiary` tout partage EN PERSONNE sur `target` (et ce qu'il couvre, par
    `access_requests.revoke`), quel qu'en soit le mode — effet immédiat, il est prévenu (E5). Un
    lot reste couvert tant qu'un autre de ses éléments lui est encore partagé. Rend le nombre de
    lignes retirées."""
    from wama.common.models import ObjectGrant
    from wama.common.services.access_requests import revoke
    if getattr(target, 'user_id', None) != getattr(user, 'id', None):
        raise RefusDePartage("seul le propriétaire retire un partage")
    lines = list(ObjectGrant.in_force().filter(
        object_type=target._meta.label, object_id=target.pk, beneficiary=beneficiary,
        level__in=ObjectGrant.VISIBLE_LEVELS))
    # Prévenir UNE fois, après le dernier retrait : la notification dit alors s'il voit encore
    # l'élément (par une portée) ou plus du tout.
    for i, line in enumerate(lines):
        revoke(user, line, notify=(i == len(lines) - 1))
    return len(lines)


def persons_of(obj) -> list:
    """Les personnes à qui `obj` est partagé EN PERSONNE : `[{grant, user_id, name, mode, since}]`,
    une par personne (son mode le plus large) — ce que montrent la modale et « Mes partages »."""
    from wama.common.models import ObjectGrant
    rank = {k: i for i, k in enumerate(ObjectGrant.VISIBLE_LEVELS)}
    best = {}
    for g in (ObjectGrant.in_force()
              .filter(object_type=obj._meta.label, object_id=obj.pk, beneficiary__isnull=False,
                      level__in=ObjectGrant.VISIBLE_LEVELS)
              .select_related('beneficiary').order_by('created_at')):
        kept = best.get(g.beneficiary_id)
        if kept is None or rank[g.level] > rank[kept.level]:
            best[g.beneficiary_id] = g
    return [{'grant': g.pk, 'user_id': g.beneficiary_id, 'name': g.beneficiary.username,
             'mode': share_mode(g.level), 'since': g.answered_at or g.created_at}
            for g in best.values()]


def etat(element) -> dict:
    """La portée COURANTE d'un élément, telle que l'UI doit la pré-sélectionner — et, s'il porte
    une personne, le texte de consentement que la modale fera valider AVANT d'envoyer (prévenir
    d'abord, plutôt que refuser puis expliquer). `persons` : à qui il est partagé en personne."""
    subject = consent_subject(element)
    since = scope_since(element)
    return {
        'visibility': getattr(element, 'visibility', ScopedVisibility.VIS_PRIVATE),
        'scope_since': since.isoformat() if since else None,
        'org_unit_id': getattr(element, 'scope_org_unit_id', None),
        'project_id': getattr(element, 'scope_project_id', None),
        'consent': ({'subject': subject, 'statement': CONSENT_STATEMENT.format(subject=subject)}
                    if subject else None),
        'persons': [{**p, 'since': p['since'].isoformat() if p['since'] else None}
                    for p in persons_of(element)],
    }
