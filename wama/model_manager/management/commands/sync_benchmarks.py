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

from wama.model_manager.services.benchmark_sync import SourceUnavailable, synchronize


class Command(BaseCommand):
    help = "Apparie le catalogue LLM aux benchmarks tiers (Artificial Analysis + Elo Arena)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Apparier et rapporter sans écrire en base.")

    def handle(self, *args, **opts):
        try:
            r = synchronize(dry_run=opts['dry_run'])
        except SourceUnavailable as e:
            self.stdout.write(f"SKIP : aucune source de benchmark joignable — {e}")
            sys.exit(3)

        for src, cats in r['sources'].items():
            detail = ', '.join(f'{c}={n}' for c, n in sorted(cats.items()))
            self.stdout.write(f"source {src} : {detail}")
        for src, reasons in (r.get('reasons') or {}).items():
            for cat, reason in reasons.items():
                self.stdout.write(self.style.WARNING(f"  {src}/{cat} : {reason}"))
        for src, reason in r['unavailable'].items():
            self.stdout.write(self.style.WARNING(f"source {src} INDISPONIBLE : {reason}"))
        mode = ' (dry-run, rien écrit)' if opts['dry_run'] else ''
        self.stdout.write(f"\nAppariés{mode} : {len(r['matched'])} "
                          f"(hors catégorie : {r['without_category']})")
        for key, cat, val, scale, elo in r['matched']:
            self.stdout.write(f"  {key:40s} [{cat}] {val:>8} ({scale})"
                              + (f"  Elo={elo}" if elo is not None else ''))
        if r['unmatched']:
            self.stdout.write(f"Non appariés (benchmark_index reste NULL) : "
                              f"{', '.join(r['unmatched'])}")
        if r['without_identity']:
            # Ces lignes ne tombaient dans AUCUN compteur avant le 2026-09-01 : le total
            # affiché était inférieur au catalogue examiné, sans que rien ne le signale.
            self.stdout.write(f"Sans identité lisible (jamais appariables en l'état) : "
                              f"{', '.join(r['without_identity'])}")
        if r['inversions']:
            self.stdout.write(self.style.WARNING(
                "⚠ CONFRONTATION — ordres AA et Elo en désaccord (à examiner, pas arbitré) :"))
            for line in r['inversions']:
                self.stdout.write(f"  {line}")
