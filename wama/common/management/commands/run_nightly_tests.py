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
        # ── LE MODE « SANS GPU », ET IL EST LE DÉFAUT ────────────────────────────────────
        #
        # ⚠⚠ `vram_gb` était déclaré sur CHAQUE scénario depuis l'origine… et lu par PERSONNE
        # (`Scenario.vram_gb`, commenté « info de planification »). Un champ qui a l'air d'une
        # garde sans en être une est pire qu'un champ absent : il fait croire que l'exclusion
        # du GPU est tenue, alors qu'elle reposait entièrement sur le fait de SAVOIR que les
        # étages `model_loaded` et `output` sont les étages GPU. Rien ne l'appliquait.
        #
        # Le défaut est l'EXCLUSION (décision Fabien, 2026-09-06 : « pour le moment on lance
        # les tests nocturnes sans GPU, mais on prépare tout »). Les scénarios GPU restent
        # donc ÉCRITS, ENREGISTRÉS et listés — simplement pas joués sans `--with-gpu`. Un
        # scénario qu'on n'écrit pas n'existera jamais ; un scénario écrit et non joué attend.
        #
        # ⚠ Ce filtre porte sur ce que le scénario DÉCLARE. Il ne peut pas deviner qu'un
        # scénario déclaré à 0 touche le GPU par un chemin détourné (le triage VLM d'une
        # batterie UI a déjà provoqué deux crashs hôte le 02/09). La déclaration engage donc
        # son auteur — d'où le contrôle `tests_nightly_modes.py`, qui exige `vram_gb > 0` de
        # tout scénario des étages GPU.
        parser.add_argument("--with-gpu", action="store_true", dest="avec_gpu",
                            help="INCLURE les scénarios qui déclarent de la VRAM (vram_gb > 0). "
                                 "Par défaut ils sont écartés : le passage nocturne est sans GPU.")
        parser.add_argument("--max-vram", type=float, dest="max_vram", default=None,
                            help="Plafond de VRAM déclarée (Go). Implique --with-gpu en deçà du "
                                 "plafond ; sert à jouer les scénarios légers seulement.")

    def handle(self, *args, **opts):
        voulus = [i.strip() for i in (opts.get("ids") or "").split(",") if i.strip()]

        def _retenu(s):
            if not voulus:
                return True
            return any(s.id == v
                       or (v.endswith('.') and s.id.startswith(v))
                       or (v.startswith('.') and s.id.endswith(v))
                       for v in voulus)

        # Plafond de VRAM effectif : 0 = aucun scénario déclarant de la VRAM (défaut).
        max_vram = opts.get("max_vram")
        if max_vram is None:
            max_vram = float('inf') if opts.get("avec_gpu") else 0.0

        candidats = [
            s for s in REGISTRY
            if s.enabled
            and (not opts.get("app") or s.app == opts["app"])
            and (not opts.get("stage") or s.stage == opts["stage"])
            and _retenu(s)
        ]
        scenarios = [s for s in candidats if (s.vram_gb or 0.0) <= max_vram]
        ecartes = [s for s in candidats if s not in scenarios]
        if ecartes:
            # JAMAIS silencieux : une exclusion muette se lit comme une couverture.
            detail = ", ".join(f"{s.id} ({s.vram_gb:g} Go)" for s in sorted(
                ecartes, key=lambda x: x.id)[:8])
            suite = "…" if len(ecartes) > 8 else ""
            self.stdout.write(self.style.WARNING(
                f"{len(ecartes)} scénario(s) ÉCARTÉ(S) — VRAM déclarée au-dessus du plafond "
                f"({'aucune VRAM autorisée' if max_vram == 0.0 else f'{max_vram:g} Go'}) : "
                f"{detail}{suite}\n"
                f"  → `--with-gpu` pour les jouer, `--max-vram N` pour un plafond."))
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
