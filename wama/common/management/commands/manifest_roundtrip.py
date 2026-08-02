"""
Round-trip de manifeste d'app : extraire → valider → confronter → projeter (dry-run).

Répond par la MESURE à « peut-on régénérer cette app depuis son manifeste ? ». Assemble les
briques qui existaient déjà séparément (`extract`/`validate`/`verify`/`project`/`facet_report`/
`studio_redundancy`) et qu'aucune commande ne reliait.

  python manage.py manifest_roundtrip transcriber
  python manage.py manifest_roundtrip transcriber --json     # sortie machine
  python manage.py manifest_roundtrip --all                  # les 10 apps, tableau de synthèse

Ne modifie RIEN : `project()` est appelé en dry-run. L'écriture reste un geste explicite
(propriété de sûreté §2.1 de WAMA_MANIFEST_SPEC).
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Round-trip de manifeste d'app (extract → validate → verify → project dry-run)."

    def add_arguments(self, parser):
        parser.add_argument('app_id', nargs='?', help="App à tester (ex. transcriber).")
        parser.add_argument('--all', action='store_true', help="Toutes les apps du catalogue.")
        parser.add_argument('--json', action='store_true', help="Sortie JSON brute.")

    # ── Un round-trip ────────────────────────────────────────────────────────
    def _roundtrip(self, app_id):
        from wama.common.manifests.ingest import extract, validate, verify, project
        from wama.common.manifests.projection import facet_report, studio_redundancy

        out = {'app': app_id}

        manifest = extract('app', app_id)
        if not manifest:
            out['erreur'] = "extraction impossible (app absente d'APP_CATALOG ?)"
            return out

        body = manifest.get('body') or {}
        out['facettes_extraites'] = sorted(body.keys())

        out['erreurs_validation'] = list(validate(manifest) or [])

        # Fidélité : ré-extraire et diffe. Doit être vide — sinon l'extraction n'est pas
        # déterministe, et régénérer depuis le manifeste produirait autre chose.
        out['ecarts_fidelite'] = list(verify(manifest) or [])

        # `facet_report` expose déjà le tri : on le CONSOMME, on ne le recalcule pas.
        rapport = facet_report(app_id) or {}
        out['projetables'] = sorted(rapport.get('runtime_projectable') or [])
        out['codegen_requis'] = sorted(rapport.get('codegen_required') or [])
        out['facettes_absentes'] = sorted(rapport.get('missing_facets') or [])
        # Cible d'écriture de chaque facette restant en code-gen — c'est la liste des fichiers
        # qu'un générateur devra produire pour que l'app soit régénérable.
        out['cibles_codegen'] = {
            f['facet']: f.get('target')
            for f in (rapport.get('facets') or [])
            if f.get('gap') == 'CODEGEN'
        }

        try:
            plan = project(manifest, apply=False)
            out['plan_projection'] = plan if isinstance(plan, (dict, list)) else str(plan)
        except NotImplementedError as e:
            out['plan_projection'] = f"non implémenté : {e}"

        try:
            red = studio_redundancy(app_id)
            out['divergence_catalogue_studio'] = red or {}
        except Exception as e:
            out['divergence_catalogue_studio'] = {'_erreur': repr(e)}

        total = len(out['projetables']) + len(out['codegen_requis'])
        out['regenerable'] = (not out['codegen_requis']
                              and not out['erreurs_validation']
                              and not out['ecarts_fidelite'])
        out['couverture_projection'] = f"{len(out['projetables'])}/{total}" if total else "0/0"
        return out

    # ── Rendu ────────────────────────────────────────────────────────────────
    def _afficher(self, r):
        w, s, e = self.stdout.write, self.style.SUCCESS, self.style.ERROR
        warn = self.style.WARNING

        w(f"\n{'=' * 78}")
        w(f"ROUND-TRIP MANIFESTE — {r['app']}")
        w('=' * 78)
        if 'erreur' in r:
            w(e(f"  {r['erreur']}"))
            return

        w(f"\n  Facettes extraites ({len(r['facettes_extraites'])}) : "
          f"{', '.join(r['facettes_extraites'])}")

        if r['erreurs_validation']:
            w(e(f"\n  Validation : {len(r['erreurs_validation'])} erreur(s)"))
            for m in r['erreurs_validation'][:10]:
                w(e(f"    - {m}"))
        else:
            w(s("\n  Validation : OK"))

        if r['ecarts_fidelite']:
            w(e(f"\n  Fidélité extract→verify : {len(r['ecarts_fidelite'])} écart(s) "
                f"— l'extraction n'est PAS déterministe"))
            for d in r['ecarts_fidelite'][:10]:
                w(e(f"    - {d.get('path')}: manifeste={d.get('manifest')!r} "
                    f"courant={d.get('current')!r}"))
        else:
            w(s("  Fidélité extract→verify : OK (aucun écart)"))

        w(f"\n  Projection : {r['couverture_projection']} facette(s) réellement projetables")
        if r['projetables']:
            w(s(f"    projetables   : {', '.join(r['projetables'])}"))
        if r['codegen_requis']:
            w(warn(f"    CODE-GEN requis : {', '.join(r['codegen_requis'])}"))
        if r['facettes_absentes']:
            w(f"    non applicables : {', '.join(r['facettes_absentes'])}")

        div = r.get('divergence_catalogue_studio') or {}
        ecarts = div.get('diffs') or div.get('divergences') or div
        if isinstance(ecarts, dict) and ecarts and '_erreur' not in ecarts:
            w(f"\n  APP_CATALOG ⟷ GENERIC_APPS : {ecarts}")

        w("")
        if r['regenerable']:
            w(s("  VERDICT : régénérable depuis le manifeste."))
        else:
            manque = []
            if r['codegen_requis']:
                manque.append(f"{len(r['codegen_requis'])} facette(s) sans code-gen")
            if r['erreurs_validation']:
                manque.append("manifeste invalide")
            if r['ecarts_fidelite']:
                manque.append("extraction non fidèle")
            w(warn(f"  VERDICT : NON régénérable — {' ; '.join(manque)}."))

    def handle(self, *args, **o):
        from wama.common.app_registry import APP_CATALOG

        if o['all']:
            cibles = sorted(APP_CATALOG)
        elif o['app_id']:
            cibles = [o['app_id']]
        else:
            self.stderr.write(self.style.ERROR("Préciser une app, ou --all."))
            return

        rapports = [self._roundtrip(a) for a in cibles]

        if o['json']:
            self.stdout.write(json.dumps(rapports, ensure_ascii=False, indent=1, default=str))
            return

        if len(rapports) == 1:
            self._afficher(rapports[0])
            return

        self.stdout.write(f"\n{'app':14s} {'facettes':9s} {'projet.':8s} {'fidélité':9s} verdict")
        self.stdout.write('-' * 78)
        for r in rapports:
            if 'erreur' in r:
                self.stdout.write(f"{r['app']:14s} {r['erreur']}")
                continue
            fid = 'OK' if not r['ecarts_fidelite'] else f"{len(r['ecarts_fidelite'])} écarts"
            verdict = 'régénérable' if r['regenerable'] else f"{len(r['codegen_requis'])} codegen"
            self.stdout.write(f"{r['app']:14s} {len(r['facettes_extraites']):<9d} "
                              f"{r['couverture_projection']:8s} {fid:9s} {verdict}")
