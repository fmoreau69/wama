"""
Exporte les manifestes d'app en fichiers — le CORPUS d'exemples de référence.

But (cadré par Fabien, 2026-08-02) : disposer d'exemples réels et valides de manifestes, à
partir desquels **wama-dev-ai traduira des projets GitHub en manifestes WAMA**. Ce sont donc
des supports d'apprentissage : un manifeste invalide exporté enseignerait une erreur, la
commande REFUSE de l'écrire.

  python manage.py manifest_export                  # les 10 apps → manifests/apps/
  python manage.py manifest_export transcriber      # une seule
  python manage.py manifest_export --check          # n'écrit rien ; sort en erreur si périmé

Le corpus est un artefact DÉRIVÉ mais VERSIONNÉ : le `git diff` du corpus est la revue de ce
qui change dans la surface déclarée d'une app. `--check` permet de refuser un commit qui
modifie un registre sans régénérer le corpus.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

DEFAUT_SORTIE = 'manifests/apps'


class Command(BaseCommand):
    help = "Exporte les manifestes d'app en JSON (corpus d'exemples de référence)."

    def add_arguments(self, parser):
        parser.add_argument('app_id', nargs='?', help="App à exporter (défaut : toutes).")
        parser.add_argument('--out', default=DEFAUT_SORTIE, help=f"Dossier (défaut {DEFAUT_SORTIE}).")
        parser.add_argument('--check', action='store_true',
                            help="N'écrit rien ; code de sortie 1 si le corpus est périmé.")
        parser.add_argument('--force', action='store_true',
                            help="Écrit même les manifestes invalides (déconseillé).")

    def handle(self, *args, **o):
        from django.conf import settings
        from wama.common.app_registry import APP_CATALOG
        from wama.common.manifests.ingest import extract, validate

        cibles = [o['app_id']] if o['app_id'] else sorted(APP_CATALOG)
        dossier = Path(settings.BASE_DIR) / o['out']
        if not o['check']:
            dossier.mkdir(parents=True, exist_ok=True)

        w, s, e, warn = self.stdout.write, self.style.SUCCESS, self.style.ERROR, self.style.WARNING
        ecrits, perimes, refuses, inchanges = [], [], [], []

        for app_id in cibles:
            manifest = extract('app', app_id)
            if not manifest:
                w(e(f"  {app_id:14s} extraction impossible"))
                continue

            erreurs = list(validate(manifest) or [])
            if erreurs and not o['force']:
                refuses.append(app_id)
                w(e(f"  {app_id:14s} REFUSÉ — {len(erreurs)} erreur(s) de validation"))
                for m in erreurs[:5]:
                    w(e(f"    - {m}"))
                continue

            # Le corpus ne doit contenir que du DÉCLARATIF. `_missing_facets` (et tout futur
            # `_`) est un diagnostic DÉRIVÉ, calculé à l'extraction pour `facet_report` : un
            # LLM entraîné là-dessus apprendrait à l'inventer. Retiré du fichier, remonté en
            # console pour ne pas perdre l'information.
            body = manifest.get('body') or {}
            absentes = list(body.get('_missing_facets') or [])
            manifest = dict(manifest)
            manifest['body'] = {k: v for k, v in body.items() if not k.startswith('_')}

            # `sort_keys` + indentation stable : le diff git doit refléter un changement de
            # contenu, jamais un réordonnancement de dict.
            texte = json.dumps(manifest, ensure_ascii=False, indent=2,
                               sort_keys=True, default=str) + '\n'
            cible = dossier / f"{app_id}.json"
            actuel = cible.read_text(encoding='utf-8') if cible.exists() else None

            if actuel == texte:
                inchanges.append(app_id)
                continue
            if o['check']:
                perimes.append(app_id)
                w(warn(f"  {app_id:14s} PÉRIMÉ ({'absent' if actuel is None else 'différent'})"))
                continue

            cible.write_text(texte, encoding='utf-8', newline='\n')
            ecrits.append(app_id)
            note = f" · facettes absentes : {', '.join(absentes)}" if absentes else ""
            w(s(f"  {app_id:14s} écrit — {len(manifest['body'])} facettes, "
                f"{len(texte):,} octets{note}"))

        w("")
        if o['check']:
            if perimes or refuses:
                w(e(f"Corpus PÉRIMÉ : {len(perimes)} à régénérer, {len(refuses)} invalide(s). "
                    f"Lancer : python manage.py manifest_export"))
                raise SystemExit(1)
            w(s(f"Corpus à jour ({len(inchanges)} manifeste(s))."))
            return

        w(f"{len(ecrits)} écrit(s), {len(inchanges)} inchangé(s), {len(refuses)} refusé(s) "
          f"→ {dossier.relative_to(settings.BASE_DIR)}")
        if refuses:
            w(warn("Les manifestes refusés ne sont PAS des exemples utilisables : corriger "
                   "l'extraction ou la donnée source avant de les faire servir de référence."))
