"""Mesure le lien modèle↔backend sur le catalogue RÉEL.

POURQUOI UNE COMMANDE ET PAS UN TEST (leçon du 2026-09-06) : un test tourne sur la base de
TEST, qui contient **0 modèle**. L'invariant écrit en `TestCase` itérait donc un ensemble vide
— vert permanent, mesure nulle. Les deux surfaces sont nécessaires et ne se remplacent pas :

    le TEST tient la LOGIQUE (il sème ses cas, il est déterministe) ;
    la COMMANDE mesure l'ÉTAT (elle lit le catalogue réel, elle varie avec l'installation).

Même partage que `check_model_layout` (disque) et `check_app_conformity` (code) : ce qui dépend
de l'installation se MESURE, ça ne s'assert pas.

Sortie : les modèles qui déclarent un moteur sans résoudre de backend, avec la RAISON.
Code de retour 1 s'il en reste un qui n'est pas expliqué — utilisable en contrôle nocturne.
"""
from django.core.management.base import BaseCommand

#: Moteurs qui ne sont PAS du code Python qu'on charge — ils n'auront jamais de classe de
#: backend, et leur absence de résolution est NORMALE (le démon Ollama, un binaire C++).
HORS_PROCESSUS = {'ollama', 'audio-cpp'}


class Command(BaseCommand):
    help = "Mesure quels modèles du catalogue résolvent réellement un backend."

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help="Code de retour 1 s'il reste un modèle non résolu et non expliqué.")

    def handle(self, *args, **options):
        from wama.common.backends.manager import backend_for_model, known_engines
        from wama.model_manager.models import AIModel

        moteurs = known_engines()
        reels = [m for m in AIModel.objects.all() if not m.is_proposed]
        avec, sans_moteur = [], []
        for m in reels:
            moteur = ((m.composition or {}).get('runtime') or {}).get('engine') or ''
            (avec if moteur else sans_moteur).append((m, moteur))

        resolus, hors_processus, moteur_absent, sans_backend = [], [], [], []
        for m, moteur in avec:
            if backend_for_model(m):
                resolus.append(m)
            elif moteur in HORS_PROCESSUS:
                hors_processus.append((m, moteur))
            elif moteur not in moteurs:
                moteur_absent.append((m, moteur))
            else:
                sans_backend.append((m, moteur))

        ligne = '═' * 78
        self.stdout.write(f'{ligne}\nLIEN MODÈLE ↔ BACKEND — catalogue réel\n{ligne}')
        self.stdout.write(f'  modèles (hors prospection)   {len(reels):>4}')
        self.stdout.write(f'  déclarent un moteur          {len(avec):>4}')
        self.stdout.write(f'  résolvent un backend         {len(resolus):>4}')
        self.stdout.write('')

        if hors_processus:
            self.stdout.write(self.style.SUCCESS(
                f'  {len(hors_processus)} hors processus — NORMAL '
                f'(le moteur n’est pas du code Python qu’on charge)'))
        for m, moteur in moteur_absent:
            self.stdout.write(self.style.WARNING(
                f'  ⚠ {m.model_key} — moteur « {moteur} » qu’AUCUN backend ne pilote'))
        for m, moteur in sans_backend:
            self.stdout.write(self.style.ERROR(
                f'  ✗ {m.model_key} — moteur « {moteur} » installé, mais aucun backend ne '
                f'déclare servir ce modèle (il manque un `SUPPORTED_MODELS`)'))
        if sans_moteur:
            self.stdout.write(
                f'\n  {len(sans_moteur)} modèle(s) sans moteur déclaré — non condamnés : '
                f'on ne condamne pas ce qu’on ne sait pas mesurer.')
            for m, _ in sans_moteur[:8]:
                self.stdout.write(f'      {m.model_key}')

        if not (moteur_absent or sans_backend):
            self.stdout.write(self.style.SUCCESS(
                '\n✓ tout modèle à moteur exécutable résout son backend.'))
        elif options['strict']:
            raise SystemExit(1)
