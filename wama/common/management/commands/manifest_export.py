"""
Exporte les manifestes d'app en fichiers — le CORPUS d'exemples de référence.

But (cadré par Fabien, 2026-08-02) : disposer d'exemples réels et valides de manifestes, à
partir desquels **wama-dev-ai traduira des projets GitHub en manifestes WAMA**. Ce sont donc
des supports d'apprentissage : un manifeste invalide exporté enseignerait une erreur, la
commande REFUSE de l'écrire.

  python manage.py manifest_export                  # les 10 apps → manifests/apps/
                                                    #  + libraries déjà semées → manifests/libraries/
                                                    #  + modèles cités par les requires → manifests/models/
  python manage.py manifest_export transcriber      # une seule app
  python manage.py manifest_export --kind library faster-whisper   # SEMER une library au corpus
  python manage.py manifest_export --check          # n'écrit rien ; sort en erreur si périmé

Libraries (SPEC §7.4-3) : le semis est EXPLICITE (`--kind library <clé>`) — aucun critère de
sélection inventé ; sans clé, la commande rafraîchit/contrôle ce qui a déjà été semé.

Modèles (micro-marche pré-B, actée 2026-08-12) : exportés par DÉRIVATION — les modèles cités
par les `requires` des apps (composition `app → model`), plus le refresh des déjà exportés.
L'export fichier sert la REVUE HUMAINE et le few-shot du rôle codegen ; la mécanique de
composition, elle, résout les requires par EXTRACTION LIVE (elle ne lit pas ces fichiers).
Les clés modèle portent un `:` (`transcriber:whisper`) interdit dans un nom de fichier
Windows → nom assaini `transcriber__whisper.json` (réversible au glob).

Le corpus est un artefact DÉRIVÉ mais VERSIONNÉ : le `git diff` du corpus est la revue de ce
qui change dans la surface déclarée d'une app. `--check` permet de refuser un commit qui
modifie un registre sans régénérer le corpus.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

DOSSIERS = {'app': 'manifests/apps', 'library': 'manifests/libraries',
            'model': 'manifests/models'}


def _nom_fichier(cle: str) -> str:
    """Nom de fichier assaini (les clés modèle portent `:` — interdit sous Windows)."""
    if '__' in cle:      # collision avec l'assainissement → le glob inverse rendrait une
        raise ValueError(  # autre clé ; refuser vaut mieux que corrompre en silence.
            f"clé {cle!r} : '__' entre en collision avec l'assainissement de ':'")
    return cle.replace(':', '__')


def _cle_du_stem(stem: str) -> str:
    return stem.replace('__', ':')


class Command(BaseCommand):
    help = "Exporte les manifestes (apps + libraries semées) en JSON — corpus d'exemples."

    def add_arguments(self, parser):
        parser.add_argument('cle', nargs='?',
                            help="Clé à exporter (app_id, ou nom de library avec --kind library). "
                                 "Défaut : toutes les apps + les libraries déjà semées.")
        parser.add_argument('--kind', default='app', choices=sorted(DOSSIERS),
                            help="Kind de la clé explicite (défaut app).")
        parser.add_argument('--out', default=None,
                            help="Dossier de sortie (défaut : celui du kind).")
        parser.add_argument('--check', action='store_true',
                            help="N'écrit rien ; code de sortie 1 si le corpus est périmé.")
        parser.add_argument('--force', action='store_true',
                            help="Écrit même les manifestes invalides (déconseillé).")

    def handle(self, *args, **o):
        from django.conf import settings
        from wama.common.app_registry import APP_CATALOG
        from wama.common.manifests.ingest import extract, validate

        base = Path(settings.BASE_DIR)
        extraits = {}          # (kind, clé) → manifeste : la pré-passe requires ne ré-extrait pas

        def _extract(kind, cle):
            if (kind, cle) not in extraits:
                extraits[(kind, cle)] = extract(kind, cle)
            return extraits[(kind, cle)]

        if o['cle']:
            cibles = [(o['kind'], o['cle'])]
        else:
            # Jumelles bac à sable EXCLUES : le corpus décrit les apps RÉELLES — une jumelle
            # est jetable et se COMPARE à sa source (route §10.3 marche S, fuite mesurée
            # 18/08 : converter_01 entrait au corpus).
            from wama.common.sandbox import non_sandbox_apps
            cibles = [('app', a) for a in non_sandbox_apps(APP_CATALOG)]
            cibles += [('library', _cle_du_stem(f.stem))
                       for f in sorted((base / DOSSIERS['library']).glob('*.json'))]
            # Modèles : DÉRIVÉS des requires des apps (composition app → model) ∪ refresh
            # des déjà exportés — même logique que les libraries, sans semis manuel.
            cites = {r['key'] for genre, a in cibles if genre == 'app'
                     for r in ((_extract('app', a) or {}).get('requires') or [])
                     if isinstance(r, dict) and r.get('kind') == 'model' and r.get('key')}
            semes = {_cle_du_stem(f.stem)
                     for f in (base / DOSSIERS['model']).glob('*.json')}
            cibles += [('model', k) for k in sorted(cites | semes)]

        w, s, e, warn = self.stdout.write, self.style.SUCCESS, self.style.ERROR, self.style.WARNING
        ecrits, perimes, refuses, inchanges = [], [], [], []

        for kind, app_id in cibles:
            dossier = base / (o['out'] or DOSSIERS[kind])
            if not o['check']:
                dossier.mkdir(parents=True, exist_ok=True)
            manifest = _extract(kind, app_id)
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
            cible = dossier / f"{_nom_fichier(app_id)}.json"
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
          f"→ {', '.join(sorted({DOSSIERS[k] for k, _ in cibles}))}")
        if refuses:
            w(warn("Les manifestes refusés ne sont PAS des exemples utilisables : corriger "
                   "l'extraction ou la donnée source avant de les faire servir de référence."))
