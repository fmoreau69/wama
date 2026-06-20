"""
Evaluation multi-agents (LLM) des candidats de prospection — couche (b), AU-DESSUS de prospect_hf.
Dry-run : rien n'est installe. Agents via LiteLLM (locaux Ollama gratuits par defaut, ou cloud).

  python manage.py assess_models --app imager --max-assess 3
  python manage.py assess_models --app transcriber --agents ollama:qwen3.5:9b,xai:grok-3
  python manage.py assess_models --task text-to-image --max-assess 2 --json
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Evaluation multi-agents des candidats de prospection (dry-run). Adoption = decision admin."

    def add_arguments(self, parser):
        parser.add_argument('--app', help="App WAMA (cf. APP_TASKS).")
        parser.add_argument('--task', help="Tache HF brute (prioritaire sur --app).")
        parser.add_argument('--agents', default='ollama:qwen3.5:9b',
                            help="provider:model separes par virgule (defaut: ollama:qwen3.5:9b).")
        parser.add_argument('--limit', type=int, default=10, help="Candidats prospectes a recuperer.")
        parser.add_argument('--max-assess', type=int, default=3,
                            help="Nb max de NOUVEAUX candidats a evaluer (limite le cout LLM).")
        parser.add_argument('--timeout', type=int, default=120)
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        from wama.model_manager.services.prospector import prospect_hf, APP_TASKS
        from wama.model_manager.services.prospect_agents import assess_candidate, parse_agents

        task = options.get('task')
        if not task:
            app = options.get('app')
            if not app:
                raise CommandError("Preciser --task ou --app.")
            task = APP_TASKS.get(app)
            if not task:
                raise CommandError(f"App inconnue. Connues : {', '.join(APP_TASKS)}.")
        app_label = options.get('app') or task

        res = prospect_hf(task, limit=options['limit'])
        if not res.get('ok'):
            self.stderr.write(self.style.ERROR(f"✗ Prospection : {res.get('error')}"))
            return

        agents = parse_agents(options['agents'])
        new = [c for c in res['candidates'] if not c['have']][:options['max_assess']]
        self.stdout.write(f"Evaluation de {len(new)} candidat(s) nouveau(x) — "
                          f"agents : {', '.join(f'{p}:{m}' for p, m in agents)}")

        results = []
        for c in new:
            self.stdout.write(f"  … {c['hf_id']}")
            results.append(assess_candidate(c, app_label, agents, timeout=options['timeout']))

        if options['json']:
            self.stdout.write(json.dumps(results, indent=2, ensure_ascii=False))
            return

        for r in results:
            cons = r['consensus']
            if cons:
                verdict = '✅ RECOMMANDÉ' if cons['recommend'] else '❌ non'
                self.stdout.write(
                    f"\n{r['hf_id']}  → {verdict}  "
                    f"(confiance {cons['confidence_avg']}, accord {int(cons['agreement']*100)}%, "
                    f"{cons['n_agents']} agent(s))")
            else:
                self.stdout.write(f"\n{r['hf_id']}  → (aucun avis exploitable)")
            for o in r['opinions']:
                if 'error' in o:
                    self.stdout.write(f"    [{o['agent']}] erreur : {o['error']}")
                else:
                    pour = 'pour' if o['recommend'] else 'contre'
                    self.stdout.write(f"    [{o['agent']}] {pour} conf={o['confidence']} "
                                      f"vram={o['vram_fit']} — {o['rationale']}")
        self.stdout.write(self.style.NOTICE(
            "\nSignal IA (jamais auto-applique). Adoption = decision admin ; "
            "ajouter des agents cloud pour confronter les avis."))
