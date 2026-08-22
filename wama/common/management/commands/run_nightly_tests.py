"""
Exécute la charpente des tests fonctionnels nocturnes (sérialisés, VRAM-aware).

Exemples :
    python manage.py run_nightly_tests --dry-run         # liste les scénarios
    python manage.py run_nightly_tests                   # joue tout
    python manage.py run_nightly_tests --app transcriber # filtre par app
    python manage.py run_nightly_tests --stage wired     # filtre par étape cible

Planification nocturne : à brancher sur Celery beat une fois la charpente validée.
"""
import json

from django.core.management.base import BaseCommand

from wama.common.services.nightly_tests import REGISTRY, run_all, STAGES


class Command(BaseCommand):
    help = "Charpente : joue les scénarios de test nocturnes (sérialisés, VRAM-aware)."

    def add_arguments(self, parser):
        parser.add_argument("--app", help="Filtrer par app (ex. transcriber)")
        parser.add_argument("--stage", choices=STAGES, help="Filtrer par étape cible")
        # Un scénario NOMMÉ : c'est ce qui manquait pour rejouer un cas précis après
        # correction, sans relancer toute la série. Accepte plusieurs ids séparés par des
        # virgules, et un préfixe (`--id converter_01.` joue tous ceux de la jumelle).
        parser.add_argument("--id", dest="ids",
                            help="Scénario(s) par id, séparés par des virgules. Un id terminé "
                                 "par '.' vaut PRÉFIXE (converter_01. = toute la jumelle) ; "
                                 "commencé par '.', SUFFIXE (.import = la famille import)")
        parser.add_argument("--list", action="store_true", dest="lister",
                            help="Liste les scénarios enregistrés (alias de --dry-run)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Liste les scénarios sans les exécuter")

    def handle(self, *args, **opts):
        voulus = [i.strip() for i in (opts.get("ids") or "").split(",") if i.strip()]

        def _retenu(s):
            if not voulus:
                return True
            return any(s.id == v
                       or (v.endswith('.') and s.id.startswith(v))
                       or (v.startswith('.') and s.id.endswith(v))
                       for v in voulus)

        scenarios = [
            s for s in REGISTRY
            if s.enabled
            and (not opts.get("app") or s.app == opts["app"])
            and (not opts.get("stage") or s.stage == opts["stage"])
            and _retenu(s)
        ]
        if voulus and not scenarios:
            connus = ", ".join(sorted(s.id for s in REGISTRY)[:12])
            self.stdout.write(self.style.WARNING(
                f"Aucun scénario pour --id {opts['ids']}. Connus (extrait) : {connus}…"))
            return
        if opts.get("lister"):
            opts["dry_run"] = True

        if not scenarios:
            self.stdout.write(self.style.WARNING("Aucun scénario ne correspond."))
            return

        if opts.get("dry_run"):
            self.stdout.write(f"{len(scenarios)} scénario(s) :")
            for s in scenarios:
                self.stdout.write(f"  - [{s.app}] {s.id} (cible: {s.stage}) — {s.description}")
            return

        report = run_all(scenarios)
        s = report["summary"]
        style = self.style.SUCCESS if s["failed"] == 0 else self.style.ERROR
        self.stdout.write(style(
            f"Tests nocturnes : {s['passed']}/{s['total']} OK, "
            f"{s['failed']} échec(s), {s.get('skipped', 0)} skip(s)."
        ))
        for r in report["results"]:
            mark = "⊘" if r["skipped"] else ("✓" if r["ok"] else "✗")
            line = f"  {mark} [{r['app']}] {r['scenario_id']} → {r['stage_reached']} ({r['duration_s']}s)"
            if r["error"]:
                line += f" — {r['error']}"
            elif r["skipped"] and r["detail"]:
                line += f" — {r['detail']}"
            self.stdout.write(line)
        if report.get("report_path"):
            self.stdout.write(f"Rapport : {report['report_path']}")
