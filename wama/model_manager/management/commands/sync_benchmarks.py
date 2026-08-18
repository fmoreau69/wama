"""
`sync_benchmarks` — alimente le signal « benchmark tiers confronté » du catalogue.

Étage 2 de l'échelle des signaux qualité (a priori < benchmark tiers < mesure interne) —
voir `services/benchmark_sync.py` (doctrine, sources, garde-fous, appariement).

Codes retour (patron check_dep_vulns) :
  0 = synchronisé (même partiellement : une source peut manquer, c'est TRACÉ) ;
  3 = AUCUNE source joignable (clé absente + réseau) → SKIP côté nocturne, pas un rouge.
"""
import sys

from django.core.management.base import BaseCommand

from wama.model_manager.services.benchmark_sync import SourceIndisponible, synchroniser


class Command(BaseCommand):
    help = "Apparie le catalogue LLM aux benchmarks tiers (Artificial Analysis + Elo Arena)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Apparier et rapporter sans écrire en base.")

    def handle(self, *args, **opts):
        try:
            r = synchroniser(dry_run=opts['dry_run'])
        except SourceIndisponible as e:
            self.stdout.write(f"SKIP : aucune source de benchmark joignable — {e}")
            sys.exit(3)

        for src, n in r['sources'].items():
            self.stdout.write(f"source {src} : {n} entrées")
        for src, motif in r['indisponibles'].items():
            self.stdout.write(self.style.WARNING(f"source {src} INDISPONIBLE : {motif}"))
        mode = ' (dry-run, rien écrit)' if opts['dry_run'] else ''
        self.stdout.write(f"\nAppariés{mode} : {len(r['apparies'])}")
        for nom, idx, elo in r['apparies']:
            self.stdout.write(f"  {nom:24s} AA={idx if idx is not None else '—':>6}  "
                              f"Elo={elo if elo is not None else '—'}")
        if r['non_apparies']:
            self.stdout.write(f"Non appariés (benchmark_index reste NULL) : "
                              f"{', '.join(r['non_apparies'])}")
        if r['inversions']:
            self.stdout.write(self.style.WARNING(
                "⚠ CONFRONTATION — ordres AA et Elo en désaccord (à examiner, pas arbitré) :"))
            for ligne in r['inversions']:
                self.stdout.write(f"  {ligne}")
