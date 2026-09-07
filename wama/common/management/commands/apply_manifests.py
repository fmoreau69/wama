"""Applique le CORPUS de manifestes aux registres — le sens ENTRANT, qui manquait.

`manifest_export` écrit les manifestes DEPUIS les registres ; `manifest_roundtrip` vérifie un
aller-retour d'app en dry-run. Rien n'appliquait le corpus DANS l'autre sens, alors que
`manifests/ingest.write_back()` sait le faire kind par kind. Sur une installation neuve, les
16 manifestes de librairies restaient donc lettre morte — c'est en les appliquant à la main,
le 2026-09-06, que le trou est apparu.

QUEL KIND, ET POURQUOI PAS LES AUTRES (question de Fabien : « les catalogues sont vides, les
manifestes sont là pour les compléter à l'installation ou à la 1ʳᵉ utilisation ? ») :

  `library`  → OUI, à l'installation. C'est une DÉCLARATION pure (nom pip, licence, version
               cible) : aucune I/O, aucun disque à scanner, 16 fichiers JSON. Elle dit ce que
               WAMA sait installer — utile AVANT d'avoir quoi que ce soit sur disque.
  `model`    → NON. Le catalogue `AIModel` reflète le DISQUE, et sa vérité est le balayage
               (`sync_models` / `_refresh_models`, déjà branché en tâche périodique Celery Beat
               `model-manager-reconcile`). Appliquer les manifestes de modèles créerait des
               lignes pour des poids ABSENTS : un catalogue qui annonce ce qu'il n'a pas. Sur
               une installation neuve, un catalogue vide est JUSTE, pas un défaut.
  `app`      → NON à l'installation : `write_back_app` écrit du CODE (facettes projetées), ce
               qui est un geste de génération, pas d'initialisation.
  `function` → NON : le registre de fonctions est en mémoire, peuplé à l'import des apps.

⚠ DRY-RUN PAR DÉFAUT, comme tout ce qui écrit dans ce dépôt. `--apply` est la décision.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

#: Kinds dont l'application à l'installation a un SENS (cf. l'en-tête). Les autres restent
#: joignables explicitement, mais ne sont pas proposés par défaut.
KINDS_INITIALISABLES = ('library',)


class Command(BaseCommand):
    help = ("Applique les manifestes d'un kind aux registres (dry-run par défaut ; "
            "--apply exécute). Utile sur une installation neuve : library.")

    def add_arguments(self, parser):
        parser.add_argument('--kind', default='library',
                            help="Kind à appliquer (défaut : library).")
        parser.add_argument('--apply', action='store_true',
                            help="Écrire réellement (sinon : plan seul).")

    def handle(self, *args, **o):
        from wama.common.manifests.ingest import write_back

        # ⚠ La table kind→dossier a un DOMICILE (`manifest_export.DOSSIERS`) : la
        # re-dériver par pluralisation naïve donnait « librarys ». Une correspondance qui
        # existe se lit, elle ne se recalcule pas.
        from .manifest_export import DOSSIERS

        kind = o['kind']
        if kind not in DOSSIERS:
            self.stderr.write(self.style.ERROR(
                f"kind inconnu : {kind} (connus : {', '.join(sorted(DOSSIERS))})"))
            return
        dossier = Path(settings.BASE_DIR) / DOSSIERS[kind]
        if not dossier.is_dir():
            self.stderr.write(self.style.ERROR(f"aucun corpus pour le kind « {kind} » ({dossier})"))
            return
        if kind not in KINDS_INITIALISABLES:
            self.stdout.write(self.style.WARNING(
                f"⚠ « {kind} » n'est pas un kind d'INITIALISATION — voir l'en-tête de cette "
                f"commande pour la raison. Poursuite quand même, à vos risques."))

        fichiers = sorted(dossier.glob('*.json'))
        crees = changes = inchanges = 0
        erreurs = []
        for f in fichiers:
            try:
                manifeste = json.loads(f.read_text(encoding='utf-8'))
                res = write_back(manifeste, apply=o['apply'])
            except Exception as e:
                erreurs.append(f'{f.stem} : {e}')
                continue
            if res.get('error'):
                erreurs.append(f"{f.stem} : {res['error']}")
            elif res.get('created'):
                crees += 1
            elif res.get('changed') or res.get('would_change'):
                changes += 1
            else:
                inchanges += 1

        mode = 'APPLIQUÉ' if o['apply'] else 'PLAN (rien écrit)'
        self.stdout.write(f"  {kind} — {len(fichiers)} manifeste(s) · {mode}")
        self.stdout.write(f"    créés {crees} · modifiés {changes} · inchangés {inchanges}")
        for e in erreurs:
            self.stdout.write(self.style.ERROR(f"    ✗ {e}"))
        if not o['apply'] and (crees or changes):
            self.stdout.write(self.style.NOTICE(
                "    → relancer avec --apply pour écrire."))
