"""
Calendrier — l'activité de WAMA posée sur l'axe du TEMPS.
Doc : `WAMA_MEMORY.md §9bis.1` (la vue) ; plan d'ensemble — trois natures de temps, actions
programmées, placement — : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13 (« le QUAND »).

⚠ CE N'EST PAS UN NOUVEAU STOCK D'ÉVÉNEMENTS. Presque tout ce qu'un calendrier affiche existe
déjà, horodaté : les items des files (sources du JOURNAL, elles-mêmes dérivées de
`detail_registry`), leurs exécutions (`RunOutcome` + `processing_seconds`), la maintenance de
l'instance (`CELERY_BEAT_SCHEDULE`). Ce module les PROJETTE sur l'axe du temps ; il n'écrit rien.
La seule table neuve du plan, celle des actions PROGRAMMÉES, n'arrive qu'à l'étape 3.

TROIS NATURES DE TEMPS (§10.6 point 13) :
- `observed` — ce qui a eu lieu : dérivé, aucune table ;
- `predicted` — ce qui aura lieu par construction : occurrences beat ; fin d'un traitement EN
  COURS par le débit observé (début mesuré au gouverneur) ; passage de la purge de rétention
  (étape 2, 2026-09-28) — calculé à la lecture ;
- `declared` — ce que quelqu'un a voulu (étape 3, `ScheduledAction`).

⚠ UNE CARD = UN ÉVÉNEMENT, SA DERNIÈRE EXÉCUTION. Les apps Médias ne portent pas de début/fin
d'exécution : l'intervalle est reconstruit de l'instant `produit`/`echec` (`RunOutcome`) moins la
durée persistée (`ProcessingTimeMixin`). Le Lab, lui, les porte (`started_at`/`completed_at`), et
un import de résultat externe pose `finished_at` : ces champs sont DÉTECTÉS par le journal
(`START_FIELDS`/`END_FIELDS`) et la fin la plus récente gagne. L'historique complet des exécutions
viendra de la ligne d'exécution par process (§10.6 4.1, moteur P3) : seule `_interval()` changera.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NATURE_OBSERVED = 'observed'
NATURE_PREDICTED = 'predicted'
NATURE_DECLARED = 'declared'

SCOPE_USER = 'user'
SCOPE_INSTANCE = 'instance'

#: Facette « nature » de la barre de filtrage commune. La maintenance de l'instance a sa propre
#: valeur : c'est une couche, pas une nature de temps (ses occurrences sont `predicted`).
NATURE_LABELS = {NATURE_OBSERVED: 'Réalisé', NATURE_PREDICTED: 'Prévu',
                 NATURE_DECLARED: 'Programmé', 'maintenance': 'Maintenance de WAMA'}

#: Bloc minimal d'un événement ponctuel : un item jamais exécuté (seul son dépôt est daté), ou
#: une exécution dont la durée n'a pas été persistée. Sans lui, l'événement serait invisible
#: dans une grille horaire.
POINT_MINUTES = 15

#: Plafond d'items lus PAR SOURCE et par requête. Une fenêtre d'un mois n'en approche pas
#: (207 items au total pour l'utilisateur le plus fourni, mesuré au journal) ; il protège d'une
#: fenêtre démesurée demandée par l'URL, pas d'un usage normal.
MAX_ITEMS_PER_SOURCE = 1000

#: Couleur neutre de la maintenance de l'instance — la couleur d'IDENTITÉ reste aux apps
#: (`app_registry._assign_derived_colors`), et « identité ≠ état » (CARD_DESIGN §9).
MAINTENANCE_COLOR = '#6c757d'


# ── Maintenance de l'instance : ce que beat lance, et ce que chaque fenêtre RÉSERVE ────────────
#
# ⚠ POURQUOI ICI ET PAS DANS `CELERY_BEAT_SCHEDULE` : beat construit un `ScheduleEntry` par
# `ScheduleEntry(**entry)`, dont la signature est FERMÉE — une clé de plus (`duration`,
# `reserves`) y lève un `TypeError` au démarrage de beat. La déclaration vit donc à côté, indexée
# par le NOM de l'entrée, et `tests_calendar` vérifie que chaque nom désigne une entrée réelle
# (même garde que `Registry.periodic`).
#
# `minutes` = durée DÉCLARÉE, faute de mesure. `measure` = nom d'une mesure (`_MEASURES`) qui la
# REMPLACE quand elle existe. `reserves` = ressources que la fenêtre retient : rien ne doit y
# être placé (étape 3), et aucune autre entrée beat ne doit la chevaucher (garde de test).
#
# Décision de Fabien (2026-09-28) : la plage des tests nocturnes est RÉSERVÉE — une tâche qui s'y
# superpose rallonge les tests et fausse leurs durées.
BEAT_WINDOWS = {
    'backup-config-daily': {'label': 'Sauvegarde de la configuration', 'minutes': 5},
    'backup-media-daily': {'label': 'Miroir des médias vers le NAS', 'minutes': 60},
    'backup-db-daily': {'label': 'Sauvegarde de la base', 'minutes': 20},
    'purge-expired-media': {'label': 'Purge des médias expirés', 'minutes': 10},
    'nightly-consistency': {'label': 'Tests nocturnes — cohérence', 'minutes': 15,
                            'measure': 'nightly:consistency', 'reserves': ('cpu',)},
    'nightly-functional-tests': {'label': 'Tests nocturnes — fonctionnels (GPU)', 'minutes': 180,
                                 'measure': 'nightly:all', 'reserves': ('gpu', 'cpu')},
}

#: Une fenêtre mesurée est la PLUS LONGUE exécution récente, majorée de cette marge puis
#: arrondie au quart d'heure : une réservation trop courte laisserait se superposer ce qu'elle
#: devait protéger.
MEASURE_MARGIN = 1.25
MEASURE_LOOKBACK_REPORTS = 60


def app_identity(app) -> tuple[str, str]:
    """`(libellé, couleur d'identité)` d'une app, pour les événements ET la légende.

    Une source du journal peut ne pas avoir d'entrée propre au catalogue (`audio_enhancer`,
    mesuré le 2026-09-28) : elle reçoit la couleur de la catégorie PLATEFORME plutôt que le bleu
    par défaut de FullCalendar, qui la ferait passer pour une autre app.
    """
    from ..app_registry import APP_CATALOG, category_color, extra_link_for

    spec = APP_CATALOG.get(app) or {}
    if not spec:
        # Lab, Studio : identité déclarée hors catalogue (`extra_links` de leur catégorie).
        declared = extra_link_for(app)
        if declared:
            category, link = declared
            return link.get('label') or app, link.get('color') or category_color(category)
    label = spec.get('label') or app.replace('_', ' ').capitalize()
    return label, spec.get('color') or category_color('platform')


@dataclass
class CalendarEvent:
    """Un événement du calendrier. Volontairement MINCE, comme l'entrée du journal : le détail
    d'un item reste à l'inspecteur et à la card, jamais recopié ici."""

    key: str
    title: str
    start: datetime
    end: datetime
    nature: str
    scope: str
    app: str = ''
    world: str = ''
    status: str = ''
    color: str = ''
    url: str = ''
    item_id: int | None = None
    reserves: tuple = ()
    #: `measured` | `declared` — d'où vient la DURÉE. Une fenêtre déclarée n'est qu'une borne.
    duration_source: str = ''
    extra: dict = field(default_factory=dict)

    def as_fullcalendar(self) -> dict:
        """Forme attendue par FullCalendar (`EventInput`) ; le reste en `extendedProps`."""
        classes = [f'wama-cal-{self.nature}', f'wama-cal-scope-{self.scope}']
        if self.status:
            classes.append(f'wama-cal-status-{self.status.lower()}')
        if self.reserves:
            classes.append('wama-cal-reserved')
        return {
            'id': self.key,
            'title': self.title,
            'start': self.start.isoformat(),
            'end': self.end.isoformat(),
            'backgroundColor': self.color,
            'borderColor': self.color,
            'classNames': classes,
            'extendedProps': {
                'nature': self.nature, 'scope': self.scope, 'app': self.app,
                'world': self.world, 'status': self.status, 'appUrl': self.url,
                'itemId': self.item_id, 'reserves': list(self.reserves),
                'durationSource': self.duration_source, **self.extra,
            },
        }


# ── Couche OBSERVÉE : les items de l'utilisateur ────────────────────────────────────────────

def _executions(user, start, end) -> dict:
    """Dernière exécution TERMINÉE de chaque item dans la fenêtre : `(app, type, id) → (instant,
    signal)`. Source : `RunOutcome` (`produit` posé par le squelette de tâche, `echec`).

    La fenêtre est élargie d'un jour vers l'arrière : un item terminé juste après `start` a pu
    COMMENCER avant, et doit apparaître en bord de grille.
    """
    from ..models import RunOutcome

    rows = (RunOutcome.objects
            .filter(user=user, signal__in=('produit', 'echec'),
                    occurred_at__gte=start, occurred_at__lt=end + timedelta(days=1))
            .order_by('occurred_at')
            .values_list('app', 'object_type', 'object_id', 'occurred_at', 'signal'))
    latest = {}
    for app, object_type, object_id, occurred_at, signal in rows:
        latest[(app, object_type, object_id)] = (occurred_at, signal)
    return latest


def _running_starts() -> dict:
    """`(app, item_id) → instant de démarrage` des tâches EN COURS, lu au gouverneur.

    Le squelette commun déclare chaque tâche au démarrage (`task_started`, horodatage `ts`) :
    c'est le seul début d'exécution MESURÉ qu'une app Médias possède. Le gouverneur vit dans
    Redis ; injoignable, il rend une table vide et le calendrier retombe sur les dates du modèle.
    """
    try:
        from .resource_governor import running_tasks
        rows = running_tasks()
    except Exception:
        logger.debug('[calendar] gouverneur injoignable', exc_info=True)
        return {}
    starts = {}
    for row in rows:
        try:
            starts[(row['app'], str(row['item']))] = datetime.fromtimestamp(
                float(row['ts']), tz=dt_timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
    return starts


def _progress_of(app, obj) -> float | None:
    """Progression 0-100 d'un item en cours : le cache du squelette (`<app>_progress_<pk>`),
    sinon le champ `progress` du modèle. None si rien d'exploitable."""
    try:
        from django.core.cache import cache
        value = cache.get(f'{app}_progress_{obj.pk}')
    except Exception:
        value = None
    if value is None:
        value = getattr(obj, 'progress', None)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if 0 < value < 100 else None


def predicted_end(started_at, progress, now) -> datetime | None:
    """Fin prévue par le DÉBIT OBSERVÉ — la même règle que `wama-eta.js` côté navigateur :
    le temps écoulé pour `progress` % donne le temps qui reste. None sans progression."""
    if progress is None or started_at is None or started_at >= now:
        return None
    elapsed = (now - started_at).total_seconds()
    return now + timedelta(seconds=elapsed * (100.0 - progress) / progress)


def _interval(obj, src, run, running_start, now):
    """`(début, fin, nature, source de la durée, exécuté)` de l'événement d'un item.

    Règle : la FIN LA PLUS RÉCENTE gagne — c'est la dernière exécution, qu'elle vienne de
    `RunOutcome` (produit par WAMA) ou d'un champ du modèle (`completed_at`, `finished_at` : Lab,
    import d'un résultat externe). `processing_seconds` ne date que la dernière exécution
    PRODUITE : on ne le soustrait pas d'une fin qui vient d'ailleurs.
    """
    from ..models import JOB_RUNNING, normalize_job_status

    point = timedelta(minutes=POINT_MINUTES)
    status = normalize_job_status(getattr(obj, 'status', '') or getattr(obj, 'state', ''))
    model_start = getattr(obj, src.start_field, None) if src.start_field else None
    model_end = getattr(obj, src.end_field, None) if src.end_field else None

    if status == JOB_RUNNING:
        began = running_start or model_start
        if began is not None:
            end = predicted_end(began, _progress_of(src.app, obj), now)
            return (began, end or max(now, began + point), NATURE_PREDICTED,
                    'measured' if end else 'declared', True)

    run_end = run[0] if run else None
    if run_end is not None and (model_end is None or run_end >= model_end):
        if model_start is not None and model_start <= run_end:
            return model_start, run_end, NATURE_OBSERVED, 'measured', True
        seconds = float(getattr(obj, 'processing_seconds', 0) or 0)
        if seconds > 0:
            return run_end - timedelta(seconds=seconds), run_end, NATURE_OBSERVED, 'measured', True
        return run_end - point, run_end, NATURE_OBSERVED, 'declared', True
    if model_end is not None:
        if model_start is not None and model_start <= model_end:
            return model_start, model_end, NATURE_OBSERVED, 'measured', True
        return model_end - point, model_end, NATURE_OBSERVED, 'declared', True
    # Jamais exécuté (ou exécuté hors fenêtre) : seul le DÉPÔT est daté.
    created = getattr(obj, src.champ_date)
    return created, created + point, NATURE_OBSERVED, 'declared', False


def observed_events(user, start, end, *, now=None) -> list[CalendarEvent]:
    """Items de l'utilisateur dont le dépôt, l'exécution ou la fin tombe dans `[start, end)`, plus
    ceux EN COURS (leur fin est une prévision : nature `predicted`).

    Les sources sont CELLES DU JOURNAL (`journal.sources()`) : une app qui entre au journal entre
    au calendrier, sans une ligne de plus — et un monde inscrit par `enregistrer_source()` aussi
    (Lab, Studio : 2026-09-28).
    """
    if not getattr(user, 'is_authenticated', False):
        return []

    from django.db.models import Q
    from django.utils import timezone

    from ..models import JOB_RUNNING, normalize_job_status
    from .journal import app_queue_url, sources

    now = now or timezone.now()
    executions = _executions(user, start, end)
    running = _running_starts()
    events = []
    for src in sources():
        model_name = src.model.__name__
        executed_ids = [oid for (app, otype, oid) in executions
                        if app == src.app and otype == model_name]
        wanted = (Q(**{f'{src.champ_date}__gte': start, f'{src.champ_date}__lt': end})
                  | Q(pk__in=executed_ids))
        for name in (src.start_field, src.end_field):
            if name:
                wanted |= Q(**{f'{name}__gte': start, f'{name}__lt': end})
        if _has_field(src.model, 'status'):
            wanted |= Q(status__in=_running_values(src.model))
        qs = (src.model.objects
              .filter(**{src.champ_user: user})
              .filter(wanted)
              .order_by(f'-{src.champ_date}')[:MAX_ITEMS_PER_SOURCE])
        _label, color = app_identity(src.app)
        url = app_queue_url(src.app)
        for obj in qs:
            status = normalize_job_status(getattr(obj, 'status', '') or getattr(obj, 'state', ''))
            run = executions.get((src.app, model_name, obj.pk))
            began, ended, nature, duration_source, executed = _interval(
                obj, src, run, running.get((src.app, str(obj.pk))), now)
            if ended <= start or began >= end:
                continue                     # un item EN COURS lancé hors fenêtre, par exemple
            events.append(CalendarEvent(
                key=f'{src.app}:{model_name}:{obj.pk}', title=str(obj),
                start=began, end=ended, nature=nature, scope=SCOPE_USER,
                app=src.app, world=src.monde, status=status, color=color, url=url,
                item_id=obj.pk, duration_source=duration_source,
                extra={'executed': executed, 'running': status == JOB_RUNNING},
            ))
    return events


def _has_field(model, name) -> bool:
    return any(getattr(f, 'name', None) == name for f in model._meta.get_fields())


def _running_values(model) -> list:
    """Les graphies EN BASE qui veulent dire « en cours » pour ce modèle : `RUNNING` pour les
    files, `running`/`processing`… pour le Lab (alias lus à la lecture, la base ne bouge pas)."""
    from ..models import JOB_RUNNING, normalize_job_status

    field_obj = model._meta.get_field('status')
    values = [value for value, _ in (field_obj.choices or [])]
    matching = [v for v in values if normalize_job_status(v) == JOB_RUNNING]
    return matching or [JOB_RUNNING]


# ── Les LOTS : un regroupement est une activité datée ────────────────────────────────────────

def _batch_models(apps_wanted) -> list:
    """Modèles de lot (`BatchMixin`) des apps sources, DÉRIVÉS des modèles installés."""
    from django.apps import apps as django_apps

    from ..models import BatchMixin

    found = []
    for model in django_apps.get_models():
        if not issubclass(model, BatchMixin) or model._meta.app_label not in apps_wanted:
            continue
        if _has_field(model, 'user') and _has_field(model, 'created_at'):
            found.append(model)
    return found


def batch_events(user, start, end) -> list[CalendarEvent]:
    """La création des LOTS de l'utilisateur dans `[start, end)`.

    POURQUOI (mesuré le 2026-09-28) : trois lots du transcriber créés les 24 et 25/09
    rassemblaient des transcriptions de mars à juillet. La file les montre à leur date de lot, le
    calendrier n'en disait rien — leurs éléments n'ont pas été exécutés ces jours-là. Un lot d'UN
    élément s'affiche en card unique : l'événement de l'élément suffit, il n'est pas répété.
    """
    if not getattr(user, 'is_authenticated', False):
        return []
    from .journal import app_queue_url, sources

    worlds = {src.app: src.monde for src in sources()}
    events = []
    for model in _batch_models(set(worlds)):
        app = model._meta.app_label
        _label, color = app_identity(app)
        qs = (model.objects.filter(user=user, created_at__gte=start, created_at__lt=end)
              .order_by('-created_at')[:MAX_ITEMS_PER_SOURCE])
        for batch in qs:
            total = getattr(batch, 'total', None)
            if total is not None and total <= 1:
                continue
            count = f'{total} éléments' if total is not None else 'lot'
            events.append(CalendarEvent(
                key=f'{app}:{model.__name__}:{batch.pk}', title=f'Lot #{batch.pk} · {count}',
                start=batch.created_at, end=batch.created_at + timedelta(minutes=POINT_MINUTES),
                nature=NATURE_OBSERVED, scope=SCOPE_USER, app=app, world=worlds[app],
                color=color, url=app_queue_url(app), duration_source='declared',
                extra={'batchId': batch.pk, 'kind': 'batch'},
            ))
    return events


# ── Couche PRÉVUE de l'utilisateur : les expirations de rétention ────────────────────────────

def expiry_events(user, start, end) -> list[CalendarEvent]:
    """Les purges de rétention qui toucheront l'utilisateur dans `[start, end)`.

    Un média expire à `date + rétention`, mais il n'est EFFACÉ qu'au passage suivant de la purge
    planifiée (`purge-expired-media`) : l'événement est posé à ce passage, un par app — c'est ce
    jour-là que l'utilisateur perd quelque chose, pas l'instant théorique de l'expiration.
    """
    if not getattr(user, 'is_authenticated', False):
        return []
    from django.conf import settings

    from .journal import app_queue_url
    from .retention import expirations_for

    purge = (getattr(settings, 'CELERY_BEAT_SCHEDULE', {}) or {}).get('purge-expired-media')
    tz = _beat_timezone()
    groups = {}
    for item in expirations_for(user, start - timedelta(days=2), end):
        at = item['expires_at']
        if purge is not None:
            at = next(_crontab_occurrences(purge['schedule'], at, at + timedelta(days=32), tz), at)
        if start <= at < end:
            groups.setdefault((item['app'], at), []).append(item['id'])
    events = []
    for (app, at), ids in sorted(groups.items(), key=lambda kv: kv[0][1]):
        label, color = app_identity(app)
        events.append(CalendarEvent(
            key=f'expiry:{app}:{at.isoformat()}',
            title=f'Purge : {len(ids)} élément{"s" if len(ids) > 1 else ""} {label}',
            start=at, end=at + timedelta(minutes=POINT_MINUTES), nature=NATURE_PREDICTED,
            scope=SCOPE_USER, app=app, color=color, url=app_queue_url(app),
            duration_source='declared', extra={'kind': 'expiry', 'itemIds': ids[:50]},
        ))
    return events


# ── Couche PRÉVUE de l'instance : la maintenance planifiée par beat ─────────────────────────

def _beat_timezone():
    from django.conf import settings
    return ZoneInfo(getattr(settings, 'CELERY_TIMEZONE', None) or settings.TIME_ZONE)


def _crontab_occurrences(schedule, start, end, tz):
    """Instants de déclenchement d'un `crontab` celery dans `[start, end)`.

    Lit les ENSEMBLES déjà développés par celery (`minute`, `hour`, `day_of_week`…) plutôt que
    de réinterpréter la chaîne cron : la sémantique reste celle de beat. ⚠ celery numérote les
    jours à partir du DIMANCHE (0), Python à partir du lundi.
    """
    day = start.astimezone(tz).date() - timedelta(days=1)
    last = end.astimezone(tz).date()
    while day <= last:
        celery_dow = (day.weekday() + 1) % 7
        if (celery_dow in schedule.day_of_week and day.day in schedule.day_of_month
                and day.month in schedule.month_of_year):
            for hour in sorted(schedule.hour):
                for minute in sorted(schedule.minute):
                    at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
                    if start <= at < end:
                        yield at
        day += timedelta(days=1)


def _nightly_reports_dir() -> Path:
    from django.conf import settings
    return Path(settings.BASE_DIR) / 'logs' / 'nightly_tests'


def measured_nightly_minutes(stage=None, reports_dir=None) -> float | None:
    """Plus longue durée récente d'une campagne nocturne, en minutes — `None` sans mesure.

    Source : les rapports `nightly_*.json` (`nightly_tests.write_report`), durée = somme des
    `duration_s` des scénarios (la campagne est SÉRIELLE, `run_all`). `stage` restreint aux
    rapports dont tous les scénarios visent ce stage ; `None` = toute campagne.

    ⚠ LA PLUS LONGUE, pas la moyenne : un rapport partiel (`--app`, `--id`) est court, et une
    réservation calée sur une moyenne serait débordée par la campagne complète qu'elle protège.
    """
    reports_dir = Path(reports_dir) if reports_dir else _nightly_reports_dir()
    if not reports_dir.is_dir():
        return None
    longest = None
    for path in sorted(reports_dir.glob('nightly_*.json'))[-MEASURE_LOOKBACK_REPORTS:]:
        try:
            results = json.loads(path.read_text(encoding='utf-8')).get('results') or []
        except (OSError, ValueError):
            continue
        if not results:
            continue
        if stage and any(r.get('stage_target') != stage for r in results):
            continue
        minutes = sum(float(r.get('duration_s') or 0) for r in results) / 60.0
        longest = minutes if longest is None else max(longest, minutes)
    return longest


_MEASURES = {
    'nightly:consistency': lambda: measured_nightly_minutes('consistency'),
    'nightly:all': lambda: measured_nightly_minutes(None),
}


def window_minutes(entry_name) -> tuple[int, str]:
    """Durée réservée pour une entrée beat : `(minutes, 'measured' | 'declared')`."""
    spec = BEAT_WINDOWS.get(entry_name) or {}
    measure = _MEASURES.get(spec.get('measure') or '')
    measured = None
    if measure:
        try:
            measured = measure()
        except Exception:  # une mesure illisible retombe sur la déclaration, jamais sur rien
            logger.warning('[calendar] mesure %s illisible', spec.get('measure'), exc_info=True)
    if measured:
        padded = measured * MEASURE_MARGIN
        return int(-(-padded // 15) * 15), 'measured'
    return int(spec.get('minutes') or POINT_MINUTES), 'declared'


def maintenance_windows(start, end) -> list[CalendarEvent]:
    """Occurrences des entrées beat À HORAIRE (`crontab`) dans `[start, end)`.

    Les entrées à INTERVALLE (toutes les 10 min, toutes les heures) sont écartées : ce sont des
    battements de fond, pas des rendez-vous — les dessiner noierait la grille sans rien dire.
    """
    from celery.schedules import crontab
    from django.conf import settings

    tz = _beat_timezone()
    events = []
    for name, entry in (getattr(settings, 'CELERY_BEAT_SCHEDULE', {}) or {}).items():
        schedule = entry.get('schedule')
        if not isinstance(schedule, crontab):
            continue
        spec = BEAT_WINDOWS.get(name) or {}
        minutes, duration_source = window_minutes(name)
        for at in _crontab_occurrences(schedule, start, end, tz):
            events.append(CalendarEvent(
                key=f'beat:{name}:{at.isoformat()}', title=spec.get('label') or name,
                start=at, end=at + timedelta(minutes=minutes), nature=NATURE_PREDICTED,
                scope=SCOPE_INSTANCE, color=MAINTENANCE_COLOR,
                reserves=tuple(spec.get('reserves') or ()), duration_source=duration_source,
                extra={'beatEntry': name, 'task': entry.get('task', '')},
            ))
    return events


def reserved_windows(start, end, resource=None) -> list[CalendarEvent]:
    """Fenêtres qui RÉSERVENT une ressource (`gpu`, `cpu`), ou toutes si `resource` est `None`.
    C'est ce que le placement des actions programmées (étape 3) devra consulter."""
    return [e for e in maintenance_windows(start, end)
            if e.reserves and (resource is None or resource in e.reserves)]


def reserved_window_conflicts(start, end) -> list[tuple[CalendarEvent, CalendarEvent]]:
    """Paires `(fenêtre réservée, autre entrée planifiée qui la chevauche)` dans `[start, end)`.

    Vide = la plage des tests nocturnes est libre. Tenu par `tests_calendar` : déplacer une
    sauvegarde dans la plage, ou une campagne qui s'allonge jusqu'à l'entrée suivante, rougit
    la suite au lieu de ralentir les tests en silence.
    """
    windows = maintenance_windows(start, end)
    conflicts = []
    for reserved in (w for w in windows if w.reserves):
        for other in windows:
            if other is reserved:
                continue
            if other.start < reserved.end and other.end > reserved.start:
                conflicts.append((reserved, other))
    return conflicts


def declared_events(user, start, end) -> list[CalendarEvent]:
    """Les programmations ACTIVES de l'utilisateur (`ScheduledAction`, étape 3) — nature `voulu`."""
    if not getattr(user, 'is_authenticated', False):
        return []
    from ..models import ScheduledAction
    from .journal import app_queue_url, sources

    worlds = {src.app: src.monde for src in sources()}
    events = []
    for action in (ScheduledAction.objects
                   .filter(user=user, state=ScheduledAction.STATE_SCHEDULED,
                           run_at__gte=start, run_at__lt=end)[:MAX_ITEMS_PER_SOURCE]):
        _label, color = app_identity(action.app) if action.app else ('', MAINTENANCE_COLOR)
        item_id = int(action.object_id) if action.object_id.isdigit() else None
        events.append(CalendarEvent(
            key=f'schedule:{action.pk}', title=f'Programmé : {action.title or action.tool}',
            start=action.run_at, end=action.run_at + timedelta(minutes=POINT_MINUTES),
            nature=NATURE_DECLARED, scope=SCOPE_USER, app=action.app,
            world=worlds.get(action.app, ''), status='PENDING', color=color,
            url=app_queue_url(action.app) if action.app else '', item_id=item_id,
            duration_source='declared',
            extra={'kind': 'schedule', 'scheduleId': action.pk, 'placement': action.placement},
        ))
    return events


def events_for(user, start, end, *, with_maintenance=True) -> list[CalendarEvent]:
    events = (observed_events(user, start, end) + batch_events(user, start, end)
              + expiry_events(user, start, end) + declared_events(user, start, end))
    if with_maintenance:
        events += maintenance_windows(start, end)
    return events


# ── Export iCalendar (RFC 5545) ─────────────────────────────────────────────────────────────

def _ics_text(value) -> str:
    return (str(value).replace('\\', '\\\\').replace(';', '\\;')
            .replace(',', '\\,').replace('\r\n', '\\n').replace('\n', '\\n'))


def _ics_time(value) -> str:
    return value.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _ics_fold(line) -> str:
    """Repli des lignes à 75 octets (RFC 5545 §3.1) — sans lui, certains clients tronquent."""
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return line
    parts, current = [], b''
    for char in line:
        encoded = char.encode('utf-8')
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode('utf-8'))
            current = b''
        current += encoded
    parts.append(current.decode('utf-8'))
    return '\r\n '.join(parts)


def to_ics(events, *, host='wama', now=None) -> str:
    """Les événements au format iCalendar. `host` qualifie les UID (uniques et STABLES : un
    client qui réimporte met à jour au lieu de dupliquer)."""
    stamp = _ics_time(now or datetime.now(dt_timezone.utc))
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//WAMA//Calendrier//FR',
             'CALSCALE:GREGORIAN', 'X-WR-CALNAME:WAMA']
    for e in events:
        lines += [
            'BEGIN:VEVENT',
            f'UID:{_ics_text(e.key)}@{host}',
            f'DTSTAMP:{stamp}',
            f'DTSTART:{_ics_time(e.start)}',
            f'DTEND:{_ics_time(e.end)}',
            f'SUMMARY:{_ics_text(e.title)}',
        ]
        if e.app:
            lines.append(f'CATEGORIES:{_ics_text(e.app)}')
        if e.status:
            lines.append(f'DESCRIPTION:{_ics_text("État : " + e.status)}')
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    return '\r\n'.join(_ics_fold(line) for line in lines) + '\r\n'
