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
- `predicted` — ce qui aura lieu par construction (occurrences beat, et à l'étape 2 : fin
  estimée par l'ETA, expiration de rétention) : calculé à la lecture ;
- `declared` — ce que quelqu'un a voulu (étape 3, `ScheduledAction`).

⚠ UNE CARD = UN ÉVÉNEMENT, SA DERNIÈRE EXÉCUTION. Aucun modèle d'item ne porte de début/fin
d'exécution : l'intervalle est reconstruit de l'instant `produit`/`echec` (`RunOutcome`) moins la
durée persistée (`ProcessingTimeMixin`). L'historique complet des exécutions viendra de la ligne
d'exécution par process (§10.6 4.1, moteur commun P3) : ce jour-là, seule `_executions()` change.
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
    from ..app_registry import APP_CATALOG, category_color

    spec = APP_CATALOG.get(app) or {}
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


def observed_events(user, start, end) -> list[CalendarEvent]:
    """Items de l'utilisateur dont l'exécution ou le dépôt tombe dans `[start, end)`.

    Les sources sont CELLES DU JOURNAL (`journal.sources()`) : une app qui entre au journal entre
    au calendrier, sans une ligne de plus — et un monde inscrit par `enregistrer_source()` aussi.
    """
    if not getattr(user, 'is_authenticated', False):
        return []

    from django.db.models import Q

    from ..models import normalize_job_status
    from .journal import app_queue_url, sources

    executions = _executions(user, start, end)
    events = []
    for src in sources():
        model_name = src.model.__name__
        executed_ids = [oid for (app, otype, oid) in executions
                        if app == src.app and otype == model_name]
        in_window = Q(**{f'{src.champ_date}__gte': start, f'{src.champ_date}__lt': end})
        qs = (src.model.objects
              .filter(**{src.champ_user: user})
              .filter(in_window | Q(pk__in=executed_ids))
              .order_by(f'-{src.champ_date}')[:MAX_ITEMS_PER_SOURCE])
        _label, color = app_identity(src.app)
        url = app_queue_url(src.app)
        for obj in qs:
            status = normalize_job_status(getattr(obj, 'status', '') or getattr(obj, 'state', ''))
            run = executions.get((src.app, model_name, obj.pk))
            if run:
                ended_at, _signal = run
                seconds = float(getattr(obj, 'processing_seconds', 0) or 0)
                began_at = ended_at - timedelta(seconds=seconds) if seconds > 0 else None
                duration_source = 'measured' if began_at else 'declared'
                began_at = began_at or ended_at - timedelta(minutes=POINT_MINUTES)
            else:
                # Jamais exécuté (ou exécuté hors fenêtre) : seul le DÉPÔT est daté.
                began_at = getattr(obj, src.champ_date)
                ended_at = began_at + timedelta(minutes=POINT_MINUTES)
                duration_source = 'declared'
            events.append(CalendarEvent(
                key=f'{src.app}:{model_name}:{obj.pk}', title=str(obj),
                start=began_at, end=ended_at, nature=NATURE_OBSERVED, scope=SCOPE_USER,
                app=src.app, world=src.monde, status=status, color=color, url=url,
                item_id=obj.pk, duration_source=duration_source,
                extra={'executed': bool(run)},
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


def events_for(user, start, end, *, with_maintenance=True) -> list[CalendarEvent]:
    events = observed_events(user, start, end)
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
