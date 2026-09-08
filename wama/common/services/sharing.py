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
par vigilance : `visibility` ne dit QUE qui voit. L'escalade « demande → acceptation » est le
jalon **S3 `AccessGrant`** (`PROFILES_PERMISSIONS §8.7`), encore dû — et §7.5 est explicite sur
l'ordre : construire l'écriture avant l'adoption reviendrait à empiler du neuf sur du
non-branché. L'UI doit donc DIRE « lecture seule », sans quoi elle promettrait S3.

⚠ Seul le PROPRIÉTAIRE partage. Ce n'est pas une politique inventée ici : `scoped_visible_q`
donne déjà à un destinataire la seule LECTURE, donc lui laisser repartager reviendrait à créer un
droit qui n'existe nulle part.
"""
from wama.common.models import ScopedVisibility, user_projects, user_scope_org_ids
from wama.common.utils.batch_common import batch_of

#: Les portées, DÉRIVÉES du mixin — jamais recopiées. Une 5ᵉ valeur ajoutée au modèle apparaît
#: ici sans geste, et l'UI la propose sans qu'on y touche.
PORTEES = dict(ScopedVisibility.VIS_CHOICES)


class RefusDePartage(Exception):
    """Refus MOTIVÉ : le motif est destiné à l'utilisateur, pas au journal."""


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


def partager(user, element, visibility, org_unit_id=None, project_id=None) -> dict:
    """Applique la portée à l'élément ET à son lot. Rend un compte-rendu.

    Le compte-rendu DIT ce qui a été touché (`lot` : id du lot propagé, ou None) : c'est ce qui
    permet à l'UI de ne pas annoncer un partage plus large qu'il n'est. Un service qui rend
    `True` laisse l'appelant inventer le message.
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

    element.visibility = visibility
    element.scope_org_unit_id = unite
    element.scope_project_id = projet
    element.save(update_fields=['visibility', 'scope_org_unit', 'scope_project'])

    lot = batch_of(element)
    lot_touche = None
    if lot is not None and _porte_la_visibilite(lot):
        lot.visibility = visibility
        lot.scope_org_unit_id = unite
        lot.scope_project_id = projet
        lot.save(update_fields=['visibility', 'scope_org_unit', 'scope_project'])
        lot_touche = lot.id

    return {'visibility': visibility, 'libelle': PORTEES[visibility],
            'org_unit_id': unite, 'project_id': projet,
            'lot': lot_touche,
            # Le lot EXISTE mais ne porte pas la visibilité : le partage est alors incomplet et
            # il faut le dire, pas le taire (§7.4bis : 🔶 si un seul des deux modèles l'a).
            'lot_non_partageable': lot is not None and lot_touche is None}


def etat(element) -> dict:
    """La portée COURANTE d'un élément, telle que l'UI doit la pré-sélectionner."""
    return {
        'visibility': getattr(element, 'visibility', ScopedVisibility.VIS_PRIVATE),
        'org_unit_id': getattr(element, 'scope_org_unit_id', None),
        'project_id': getattr(element, 'scope_project_id', None),
    }
