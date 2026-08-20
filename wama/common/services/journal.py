"""
Journal de l'utilisateur — agrégat transversal de ce qu'il a lancé dans WAMA.
Doc : `WAMA_MEMORY.md §9bis`.

PRINCIPE : AUCUNE LIGNE DANS LES APPS. Les sources ne sont pas déclarées une à une — elles sont
DÉRIVÉES de `detail_registry`, que chaque app alimente déjà dans son `apps.py`
(`register_app_detail` / `register_app_detail_spec`) pour l'inspecteur. Une app qui apparaît dans
l'inspecteur apparaît donc dans le journal, le jour où elle est écrite, sans qu'on y touche.
C'est la même dérivation que `WAMA_MECANISMES.md` fait depuis son registre : la donnée existe
déjà, on ne la ressaisit pas.

CE QUE ÇA ÉVITE : dix requêtes écrites à la main, qui divergeraient à la première app ajoutée.

⚠ CE N'EST PAS UNE 4e VUE DES DONNÉES. Le journal ne réinvente ni la card, ni la preview, ni
l'inspecteur : il ne rend qu'un rang minimal (titre, date, statut) et DÉLÈGUE le reste aux
endpoints transversaux existants — `/common/preview/<app>/<pk>/` et `/common/detail/<app>/<pk>/`.
Écrire ici un rendu d'item maison créerait la 4e vue qu'on veut éviter, et elle dériverait.

MONDES. `WAMA_DATA_WORLD.md` découpe WAMA en mondes (Médias, Data, Lab, Transversal). Seul le
monde MÉDIA est peuplé aujourd'hui, mais l'ajout d'un monde doit rester une INSCRIPTION, pas une
modification de ce module ni de la page : `enregistrer_source()` existe pour ça (studio, wama-lab,
wama-data quand ils auront leurs modèles).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MONDE_MEDIA = 'media'
MONDE_STUDIO = 'studio'
MONDE_LAB = 'lab'
MONDE_DATA = 'data'

LIBELLES_MONDES = {
    MONDE_MEDIA: 'Médias',
    MONDE_STUDIO: 'Studio',
    MONDE_LAB: 'Lab',
    MONDE_DATA: 'Data',
}

#: Champs de date candidats, par ordre de préférence. `created_at` est la convention (11 apps
#: sur 12) ; `uploaded_at` est l'exception d'anonymizer. Détecter plutôt que déclarer évite une
#: table à tenir à jour — et une app qui n'aurait aucun de ces champs est SIGNALÉE, pas ignorée
#: en silence (un trou silencieux est la façon dont un journal devient faux).
CHAMPS_DATE = ('created_at', 'uploaded_at', 'added_at', 'date_created')

#: Sources hors `detail_registry` (autres mondes). Vide aujourd'hui — c'est le point d'extension.
_SOURCES_EXPLICITES: list = []


@dataclass(frozen=True)
class SourceJournal:
    """Un modèle dont les items entrent au journal."""

    app: str
    monde: str
    model: type
    champ_date: str
    champ_user: str = 'user'

    @property
    def libelle_monde(self):
        return LIBELLES_MONDES.get(self.monde, self.monde)


def enregistrer_source(app, model, *, monde, champ_date=None, champ_user='user'):
    """
    Ajoute une source hors `detail_registry` — point d'extension des mondes studio/lab/data.

    À n'utiliser QUE pour un modèle qui n'a pas d'inspecteur : si l'app est dans
    `detail_registry`, elle est déjà au journal et l'inscrire ici la dupliquerait.
    """
    champ_date = champ_date or _detecter_champ_date(model)
    if champ_date is None:
        logger.warning("[journal] %s sans champ de date connu — source ignorée", model.__name__)
        return
    _SOURCES_EXPLICITES.append(SourceJournal(app=app, monde=monde, model=model,
                                             champ_date=champ_date, champ_user=champ_user))


def _detecter_champ_date(model):
    champs = {f.name for f in model._meta.get_fields() if hasattr(f, 'attname')}
    return next((c for c in CHAMPS_DATE if c in champs), None)


def sources():
    """
    Toutes les sources du journal. Dérivées de `detail_registry` + les inscriptions explicites.

    Une app sans champ `user` est ÉCARTÉE : le journal est personnel, et un modèle sans
    propriétaire ne peut être rattaché à personne.
    """
    from ..utils.detail_registry import DetailRegistry

    trouvees = []
    for app, entree in DetailRegistry._registry.items():
        model = entree.get('model')
        if model is None:
            continue
        champs = {f.name for f in model._meta.get_fields() if hasattr(f, 'attname')}
        if 'user' not in champs:
            logger.debug('[journal] %s sans champ user — écartée', app)
            continue
        champ_date = _detecter_champ_date(model)
        if champ_date is None:
            logger.warning("[journal] %s (%s) n'a aucun champ de date connu (%s) — écartée. "
                           "Ajouter le champ au modèle ou l'inscrire via enregistrer_source().",
                           app, model.__name__, ', '.join(CHAMPS_DATE))
            continue
        trouvees.append(SourceJournal(app=app, monde=MONDE_MEDIA, model=model,
                                      champ_date=champ_date))
    return trouvees + list(_SOURCES_EXPLICITES)


@dataclass
class Entree:
    """Un item au journal. Volontairement MINCE — le détail vient des endpoints transversaux."""

    app: str
    monde: str
    pk: int
    date: object
    titre: str
    statut: str
    modele: str
    #: Chips méta GÉNÉRÉS du schéma params de l'app (`card_chips`) — jamais écrits ici.
    chips: list = None
    #: Histoire des gestes, quand `RunOutcome` en a (couche 2). Vide sinon — la ligne reste utile.
    gestes: list = None
    saillance: float = 0.0

    @property
    def url_app(self):
        """
        Page de file de l'app, où l'item vit vraiment. Vide si l'app n'a pas de route déclarée.

        C'est la CIBLE du clic — pas un volet réimplémenté ici. Combinée à
        `sessionStorage['wama_focus_card']`, elle amène l'utilisateur sur sa card, mise en
        évidence, avec TOUTES les actions de l'app disponibles. `wama-queue.js` documente
        lui-même ce passage inter-pages ; on ne réinvente rien.
        """
        from django.urls import NoReverseMatch, reverse

        from ..app_registry import APP_CATALOG

        spec = APP_CATALOG.get(self.app) or {}
        if not spec.get('url_name'):
            return ''
        try:
            return reverse(spec['url_name'])
        except NoReverseMatch:
            return ''

    @property
    def url_detail(self):
        """
        Endpoint canonique de détail (`detail_registry.unified_detail`).

        ⚠ IL EST PORTEUR, pas dormant : `wama-inspector.js::fillDetail()` le FETCH pour remplir
        la section « Infos » du volet droit. Il ne le nomme jamais littéralement — il dérive
        l'URL de `data-preview-url` par `replace('/preview/', '/detail/')` (l.328), ce qui le
        rend invisible à toute recherche du chemin. Ne pas le retirer ni en changer le contrat
        sans passer par l'inspecteur.

        Non utilisé par le clic du journal, qui emmène sur la page de l'app (cf. `url_app`).
        """
        from django.urls import reverse
        return reverse('common:unified_detail', args=[self.app, self.pk])

    @property
    def url_preview(self):
        from django.urls import reverse
        return reverse('common:unified_preview', args=[self.app, self.pk])


def entrees(user, *, mondes=None, apps=None, depuis=None, jusqu_a=None, limite=50, offset=0,
            avec_gestes=True):
    """
    Rend `(liste d'Entree triée du plus récent au plus ancien, total)`.

    ⚠ TRI INTER-MODÈLES EN PYTHON. Une union SQL sur 12 tables hétérogènes (colonnes et types
    différents) demanderait une vue matérialisée ou un `UNION ALL` construit à la main, qui se
    casserait à la première app ajoutée — exactement ce que ce module veut éviter. On tire donc
    de chaque source les `offset + limite` plus récents, on fusionne, on tranche. Le coût est
    borné par le nombre de sources × la profondeur demandée, pas par le volume total.
    À revoir si une source dépasse quelques dizaines de milliers de lignes par utilisateur.
    """
    if not getattr(user, 'is_authenticated', False):
        return [], 0

    besoin = offset + limite
    candidats, total = [], 0

    for src in sources():
        if mondes and src.monde not in mondes:
            continue
        if apps and src.app not in apps:
            continue
        qs = src.model.objects.filter(**{src.champ_user: user})
        if depuis is not None:
            qs = qs.filter(**{f'{src.champ_date}__gte': depuis})
        if jusqu_a is not None:
            qs = qs.filter(**{f'{src.champ_date}__lte': jusqu_a})
        total += qs.count()
        for obj in qs.order_by(f'-{src.champ_date}')[:besoin]:
            candidats.append((getattr(obj, src.champ_date), obj, src))

    # ⚠ ON TRIE ET ON TRANCHE **AVANT** DE FABRIQUER LES ENTRÉES. Fabriquer d'abord coûterait les
    # chips (donc des accès aux relations) sur ~sources × besoin objets pour n'en afficher que
    # `limite` : mesuré 73 requêtes SQL pour 20 lignes, ramené à ~26 en différant l'hydratation.
    # C'est la même règle que partout : ne payer que ce qu'on affiche.
    candidats.sort(key=lambda t: t[0], reverse=True)
    tranche = candidats[offset:offset + limite]

    schemas = {}   # schéma params mémoïsé PAR APP — sinon une lecture de schéma par ligne
    page = [_vers_entree(obj, src, schemas) for _, obj, src in tranche]

    if avec_gestes and page:
        _hydrater_gestes(page, user)
    return page, total


def _vers_entree(obj, src, schemas=None):
    """
    Fabrique l'entrée SANS rien demander à l'app.

    Le titre est `str(obj)` : chaque modèle Django a un `__str__`, c'est la seule information
    lisible qu'on puisse obtenir de N modèles hétérogènes sans écrire une ligne par app. Un
    titre médiocre est un défaut de `__str__` à corriger dans le modèle — au bon endroit, où il
    profitera aussi à l'admin et aux logs.
    """
    statut = getattr(obj, 'status', '') or getattr(obj, 'state', '') or ''
    return Entree(
        app=src.app,
        monde=src.monde,
        pk=obj.pk,
        date=getattr(obj, src.champ_date),
        titre=str(obj),
        statut=str(statut),
        modele=type(obj).__name__,
        chips=_chips(obj, src.app, schemas),
        gestes=[],
    )


def _chips(obj, app, schemas):
    """
    Chips méta via la brique commune — GÉNÉRÉS du schéma params, jamais écrits ici.

    Best-effort : une app dont le schéma n'est pas lisible perd ses chips, pas sa ligne.
    """
    if schemas is None:
        schemas = {}
    try:
        from ..utils.card_chips import chips_for
        from ..utils.param_schema import schema_for_app

        if app not in schemas:
            schemas[app] = schema_for_app(app) or []
        if not schemas[app]:
            return []
        return chips_for(obj, schemas[app]) or []
    except Exception:
        logger.debug('[journal] chips indisponibles pour %s', app, exc_info=True)
        return []


def _hydrater_gestes(page, user):
    """
    COUCHE 2 — accroche l'histoire des gestes (`RunOutcome`) aux entrées affichées.

    En UNE requête pour toute la page, pas une par ligne. Best-effort absolu : une erreur ici
    ne doit jamais faire disparaître le journal, dont les lignes sont déjà utiles sans gestes.
    """
    try:
        from django.db.models import Q

        from ..memory.project import _LIBELLES, _POIDS_SAILLANCE
        from ..models import RunOutcome

        filtre = Q(pk__in=[])
        for e in page:
            filtre |= Q(app=e.app, object_type=e.modele, object_id=e.pk)

        par_item = {}
        for r in RunOutcome.objects.filter(filtre, user=user).order_by('occurred_at'):
            par_item.setdefault((r.app, r.object_type, r.object_id), []).append(r.signal)

        for e in page:
            signaux = par_item.get((e.app, e.modele, e.pk), [])
            if not signaux:
                continue
            vus, gestes = set(), []
            for s in signaux:
                if s in vus:
                    continue
                vus.add(s)
                n = signaux.count(s)
                libelle = _LIBELLES.get(s, s)
                gestes.append(f"{libelle} ({n} fois)" if n > 1 else libelle)
            e.gestes = gestes
            # Même formule que la projection — une seule définition de la saillance, sinon les
            # deux dériveraient et le journal contredirait la mémoire.
            e.saillance = min(1.0, sum(_POIDS_SAILLANCE.get(s, 0.0) for s in vus))
    except Exception:
        logger.warning('[journal] hydratation des gestes impossible', exc_info=True)


def compter_par_app(user, **kwargs):
    """Répartition par app — alimente les filtres de la page sans requête supplémentaire côté vue."""
    if not getattr(user, 'is_authenticated', False):
        return []
    lignes = []
    for src in sources():
        n = src.model.objects.filter(**{src.champ_user: user}).count()
        if n:
            lignes.append({'app': src.app, 'monde': src.monde,
                           'libelle_monde': src.libelle_monde, 'total': n})
    lignes.sort(key=lambda d: (-d['total'], d['app']))
    return lignes
