# -*- coding: utf-8 -*-
"""
Compare les modeles d'une TACHE sur un echantillon.

Remplace `bench_describer`, qui etait indexe sur une app alors que `describer` n'est pas une
categorie de modele. Un banc `detect` sert l'anonymizer et le cam_analyzer ; un banc par app en
aurait fait deux.

    python manage.py bench --task detect --media media/anonymizer/1/input/Faces_01.jpg
    python manage.py bench --task captioning --media une_image.jpg --models gemma4:12b,gemma4:e4b
    python manage.py bench --task text-generation --media prompt.txt --models qwen3.5:4b --runs 3

Pour `text-generation`, l'echantillon est un fichier TEXTE : le prompt. Le protocole CHARGE
chaque modele sur l'Ollama hote (rampe VRAM — cf. INFRA §crashs) : lancer un modele a la fois,
machine sous les yeux ; refuse sous WAMA_GPU_SAFE_MODE.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from wama.model_manager.services.bench import run_bench, available_tasks, models_for_task


class Command(BaseCommand):
    help = "Compare les modeles d'une tache sur un echantillon (mesures comparables, juge humain)."

    def add_arguments(self, parser):
        parser.add_argument('--task', required=True,
                            help=f"Tache a mesurer. Disponibles : {', '.join(available_tasks())}")
        parser.add_argument('--media', required=True, help="Chemin de l'echantillon.")
        parser.add_argument('--models', default='',
                            help="Restreint a ces modeles (noms ou cles, separes par des virgules).")
        parser.add_argument('--conf', type=float, default=0.25,
                            help="Seuil de confiance des familles de detection (defaut 0.25).")
        parser.add_argument('--runs', type=int, default=3,
                            help="Generation de texte : passes mesurees par modele (defaut 3, "
                                 "apres une passe de chauffe non comptee).")

    def handle(self, *args, **options):
        task, media = options['task'], options['media']
        if not os.path.isfile(media):
            raise CommandError(f"Echantillon introuvable : {media}")

        candidates = models_for_task(task)
        if not candidates:
            raise CommandError(
                f"Aucun modele installe ne declare la tache '{task}'. "
                f"Verifier avec : python manage.py check_model_taxonomy")

        self.stdout.write(f"Tache '{task}' — {len(candidates)} modele(s) — echantillon {media}\n")

        protocol_options = {}
        if task == 'text-generation':
            protocol_options['runs'] = options['runs']
        elif task != 'captioning':
            protocol_options['conf'] = options['conf']

        try:
            measures = run_bench(task, media,
                             models=[m for m in options['models'].split(',') if m.strip()] or None,
                             **protocol_options)
        except ValueError as e:
            raise CommandError(str(e))

        # Generation : le debit est la colonne qui compare, et c'est lui qui ordonne.
        generation = task == 'text-generation'
        header = f"  {'model':46s} {'outputs':>8s} {'conf.moy':>9s} {'inference':>10s} {'VRAM':>6s}"
        if generation:
            header += f" {'jetons/s':>9s} {'prefill':>9s} {'charg.':>7s}"
        self.stdout.write(header)
        self.stdout.write("  " + "-" * (len(header) - 2))

        def _order(x):
            if generation:
                return (x['error'] is not None, -(x.get('tokens_per_s') or 0))
            return (x['error'] is not None, -(x['outputs'] or 0))

        for m in sorted(measures, key=_order):
            if m['error']:
                self.stdout.write(self.style.ERROR(f"  {m['model']:46s} {m['error'][:44]}"))
                continue
            line = (f"  {m['model']:46s} {str(m['outputs']):>8s} "
                     f"{str(m['mean_confidence'] or '—'):>9s} "
                     f"{str(m['inference_s']) + ' s':>10s} "
                     f"{str(m['vram_gb'] or '—'):>6s}")
            if generation:
                load = m.get('load_s')
                line += (f" {str(m.get('tokens_per_s') or '—'):>9s} "
                          f"{str(m.get('prefill_ms')) + ' ms':>9s} "
                          f"{(str(load) + ' s') if load else 'résid.':>7s}")
            self.stdout.write(self.style.WARNING(line + "  ⚠ saturé") if m['saturated'] else line)

        self.stdout.write(self.style.NOTICE(
            "\nCe sont des mesures COMPARABLES, pas des notes de qualite : compter des sorties ne "
            "dit pas si elles sont justes. Sans verite terrain, ce tableau classe des candidats a "
            "essayer — le juge final reste humain."))
