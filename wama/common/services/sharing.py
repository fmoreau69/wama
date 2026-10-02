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

⚠ AUCUN DROIT D'ÉCRITURE n'est accordé. Le partage est en lecture seule **par construction**, pas
par vigilance : `visibility` ne dit QUE qui voit. L'escalade « demande → acceptation » vit dans
`ObjectGrant` (`WAMA_COLLABORATION §4.3` — droits sur une INSTANCE ; ~~S3 `AccessGrant`~~, cité ici
jusqu'au 2026-10-03, porte les droits sur une APP : `PROFILES_PERMISSIONS:392`, « deux tables »).
Depuis le 2026-10-03 on peut y DEMANDER la propriété (`access_requests`) ; l'écriture partagée
reste à construire. L'UI doit donc DIRE « lecture seule », sans quoi elle promettrait l'écriture.

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
#: modale « Partager… ». `available` : seul la LECTURE existe dans le code ; les deux autres sont
#: montrés GRISÉS (« bientôt ») — décision de Fabien, 2026-10-03 — jusqu'à leur construction.
#: L'icône n'est pas décorative : le niveau se lit au mot ET au signe, jamais à la seule couleur.
SHARE_MODES = (
    {'key': 'read', 'label': 'Lecture seule', 'icon': '👁', 'available': True},
    {'key': 'fork', 'label': 'Modification', 'icon': '✎', 'available': False},
    {'key': 'collaborate', 'label': 'Collaboration', 'icon': '👥', 'available': False},
)
#: Le mode d'un partage tant qu'aucun autre n'existe : la lecture (voir `SHARE_MODES`).
CURRENT_SHARE_MODE = SHARE_MODES[0]


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


def _poser(objet, visibility, unite, projet):
    objet.visibility = visibility
    objet.scope_org_unit_id = unite
    objet.scope_project_id = projet
    objet.save(update_fields=['visibility', 'scope_org_unit', 'scope_project'])


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
    _poser(element, visibility, unite, projet)
    if subject:
        _record_consent(user, element, visibility, unite, projet, subject)

    lot = batch_of(element)
    lot_touche = None
    if lot is not None and _porte_la_visibilite(lot):
        _poser(lot, visibility, unite, projet)
        lot_touche = lot.id

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
    _poser(lot, visibility, unite, projet)

    touches, non_partageables = 0, 0
    for element in elements:
        if not _porte_la_visibilite(element):
            non_partageables += 1
            continue
        _poser(element, visibility, unite, projet)
        if subjects.get(element.pk):
            _record_consent(user, element, visibility, unite, projet, subjects[element.pk])
        touches += 1

    return {'visibility': visibility, 'libelle': PORTEES[visibility],
            'org_unit_id': unite, 'project_id': projet,
            'lot': lot.id, 'elements': touches,
            # On COMPTE ce qui n'a pas suivi au lieu de le taire : un lot dont la moitié des
            # éléments reste privée est un partage à trous, et le destinataire n'en saura rien.
            'elements_non_partageables': non_partageables,
            'lot_non_partageable': False}


def etat(element) -> dict:
    """La portée COURANTE d'un élément, telle que l'UI doit la pré-sélectionner — et, s'il porte
    une personne, le texte de consentement que la modale fera valider AVANT d'envoyer (prévenir
    d'abord, plutôt que refuser puis expliquer)."""
    subject = consent_subject(element)
    return {
        'visibility': getattr(element, 'visibility', ScopedVisibility.VIS_PRIVATE),
        'org_unit_id': getattr(element, 'scope_org_unit_id', None),
        'project_id': getattr(element, 'scope_project_id', None),
        'consent': ({'subject': subject, 'statement': CONSENT_STATEMENT.format(subject=subject)}
                    if subject else None),
    }
