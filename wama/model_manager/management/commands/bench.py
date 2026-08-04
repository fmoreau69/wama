# -*- coding: utf-8 -*-
"""
Compare les modeles d'une TACHE sur un echantillon.

Remplace `bench_describer`, qui etait indexe sur une app alors que `describer` n'est pas une
categorie de modele. Un banc `detect` sert l'anonymizer et le cam_analyzer ; un banc par app en
aurait fait deux.

    python manage.py bench --task detect --media media/anonymizer/1/input/Faces_01.jpg
    python manage.py bench --task captioning --media une_image.jpg --models gemma4:12b,gemma4:e4b
"""
import os

from django.core.management.base import BaseCommand, CommandError

from wama.model_manager.services.bench import lancer, taches_disponibles, modeles_pour_tache


class Command(BaseCommand):
    help = "Compare les modeles d'une tache sur un echantillon (mesures comparables, juge humain)."

    def add_arguments(self, parser):
        parser.add_argument('--task', required=True,
                            help=f"Tache a mesurer. Disponibles : {', '.join(taches_disponibles())}")
        parser.add_argument('--media', required=True, help="Chemin de l'echantillon.")
        parser.add_argument('--models', default='',
                            help="Restreint a ces modeles (noms ou cles, separes par des virgules).")
        parser.add_argument('--conf', type=float, default=0.25,
                            help="Seuil de confiance des familles de detection (defaut 0.25).")

    def handle(self, *args, **options):
        tache, media = options['task'], options['media']
        if not os.path.isfile(media):
            raise CommandError(f"Echantillon introuvable : {media}")

        candidats = modeles_pour_tache(tache)
        if not candidats:
            raise CommandError(
                f"Aucun modele installe ne declare la tache '{tache}'. "
                f"Verifier avec : python manage.py check_model_taxonomy")

        self.stdout.write(f"Tache '{tache}' — {len(candidats)} modele(s) — echantillon {media}\n")

        options_protocole = {}
        if tache != 'captioning':
            options_protocole['conf'] = options['conf']

        try:
            mesures = lancer(tache, media,
                             modeles=[m for m in options['models'].split(',') if m.strip()] or None,
                             **options_protocole)
        except ValueError as e:
            raise CommandError(str(e))

        entete = f"  {'modele':46s} {'sorties':>8s} {'conf.moy':>9s} {'inference':>10s} {'VRAM':>6s}"
        self.stdout.write(entete)
        self.stdout.write("  " + "-" * (len(entete) - 2))
        for m in sorted(mesures, key=lambda x: (x['erreur'] is not None, -(x['sorties'] or 0))):
            if m['erreur']:
                self.stdout.write(self.style.ERROR(f"  {m['modele']:46s} {m['erreur'][:44]}"))
                continue
            ligne = (f"  {m['modele']:46s} {str(m['sorties']):>8s} "
                     f"{str(m['confiance_moyenne'] or '—'):>9s} "
                     f"{str(m['inference_s']) + ' s':>10s} "
                     f"{str(m['vram_gb'] or '—'):>6s}")
            self.stdout.write(self.style.WARNING(ligne + "  ⚠ saturé") if m['sature'] else ligne)

        self.stdout.write(self.style.NOTICE(
            "\nCe sont des mesures COMPARABLES, pas des notes de qualite : compter des sorties ne "
            "dit pas si elles sont justes. Sans verite terrain, ce tableau classe des candidats a "
            "essayer — le juge final reste humain."))
