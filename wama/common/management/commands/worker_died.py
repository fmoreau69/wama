"""Un worker Celery ou un service est mort — appelée par la surveillance (`scripts/worker_watchdog.sh`).

  python manage.py worker_died --node gpu@<machine> --outcome restarted
  python manage.py worker_died --node gpu@<machine> --outcome restart_failed
  python manage.py worker_died --node gpu@<machine> --outcome gave_up --restarts 3
  python manage.py worker_died --node privacy_service --outcome restarted --kind service

Deux gestes (2026-09-24, demande de Fabien) :
  1. solder les traitements que le processus mort tenait — `reconcile_dead_worker_tasks`, la même
     brique que le worker relancé appelle à son démarrage (`wama/celery.py`) ; idempotente. Ici
     elle compte surtout quand la relance n'a PAS eu lieu (échec, budget épuisé) : sans worker
     neuf, personne d'autre ne les solderait ;
  2. prévenir les administrateurs DANS WAMA et par e-mail (`notify_admins`).
"""
from django.core.management.base import BaseCommand

OUTCOMES = {
    'restarted': "relancé automatiquement",
    'restart_failed': "la relance automatique a ÉCHOUÉ — le relancer à la main",
    'gave_up': "relances automatiques SUSPENDUES (trop d'arrêts rapprochés) — à examiner",
}


class Command(BaseCommand):
    help = "Signale la mort d'un worker Celery : solde ses traitements et prévient les admins."

    def add_arguments(self, parser):
        parser.add_argument('--node', required=True, help='nom du worker, ex. gpu@machine')
        parser.add_argument('--outcome', required=True, choices=sorted(OUTCOMES))
        parser.add_argument('--restarts', type=int, default=0,
                            help='relances dans la fenêtre de la surveillance')
        parser.add_argument('--kind', choices=('celery', 'service'), default='celery',
                            help='un worker Celery, ou un service uvicorn (aucune tâche à solder)')

    def handle(self, *args, **opts):
        from wama.common.utils.notifications import notify_admins
        from wama.common.utils.process_control import reconcile_dead_worker_tasks

        node, outcome = opts['node'], opts['outcome']
        is_service = opts['kind'] == 'service'
        # Un service ne tient aucune tâche Celery : ses appelants font sans lui.
        done = [] if is_service else reconcile_dead_worker_tasks(node)
        what = f"Le service {node}" if is_service else f"Le worker Celery {node}"
        lines = [f"{what} s'est arrêté : {OUTCOMES[outcome]}."]
        if opts['restarts']:
            lines.append(f"Arrêts dans la fenêtre de surveillance : {opts['restarts']}.")
        if done:
            items = ', '.join(f"{label} #{pk}" for label, _model, pk in done[:20])
            lines.append(f"Traitements interrompus, passés en échec relançable : {items}.")
        lines.append("Journal : logs/worker-watchdog.log (et le journal du "
                     + ("service)." if is_service else "worker)."))
        subject = (f"{'Service' if is_service else 'Worker'} {node} arrêté — "
                   f"{OUTCOMES[outcome].split(' —')[0]}")
        created, sent = notify_admins('worker_died', subject, '\n'.join(lines),
                                      url='/model-manager/')
        self.stdout.write(f"{node}: {outcome} ; {len(done)} élément(s) soldé(s) ; "
                          f"{created} notification(s), e-mail {'envoyé' if sent else 'non envoyé'}")
