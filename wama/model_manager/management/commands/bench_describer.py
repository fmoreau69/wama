"""
Bench (d) : décrire une image avec des modeles vision Ollama (gemma4:12b, e4b…) et comparer.
QC optionnel via un validateur INDEPENDANT (garde-fou : different du modele qui decrit).
Le juge final reste HUMAIN — le QC texte ici mesure la plausibilite/coherence, pas l'exactitude
visuelle (un validateur texte ne voit pas l'image).

  python manage.py bench_describer --image wama/static/images/bg_anonymize1.png --models gemma4:12b,gemma4:e4b
  python manage.py bench_describer --image <path> --models gemma4:12b --qc
"""
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Bench de description d'image par modeles vision Ollama + QC optionnel (validateur independant)."

    def add_arguments(self, parser):
        parser.add_argument('--image', required=True)
        parser.add_argument('--models', default='gemma4:12b', help="Modeles vision Ollama, separes par virgule.")
        parser.add_argument('--prompt', default=None)
        parser.add_argument('--qc', action='store_true', help="Scorer chaque description (validateur independant).")
        parser.add_argument('--qc-validator', default='ollama:qwen3.5:9b')
        parser.add_argument('--timeout', type=int, default=180)

    def handle(self, *args, **options):
        from wama.model_manager.services.vision_probe import describe_image_ollama

        image = options['image']
        if not os.path.exists(image):
            raise CommandError(f"Image introuvable : {image}")
        models = [m.strip() for m in options['models'].split(',') if m.strip()]
        vp, _, vm = options['qc_validator'].partition(':')

        self.stdout.write(f"Image : {image}")
        for model in models:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {model} ==="))
            res = describe_image_ollama(image, model, options['prompt'], options['timeout'])
            if not res.get('ok'):
                self.stderr.write(self.style.ERROR(f"✗ {res.get('error')}"))
                continue
            desc = res['description']
            self.stdout.write(desc or '(vide)')

            if options['qc']:
                if model == vm:  # garde-fou independance
                    self.stdout.write(self.style.WARNING("  (QC saute : validateur = modele evalue → circulaire)"))
                    continue
                from wama.common.utils.qc import assess_output_quality
                q = assess_output_quality(
                    "Decrire precisement une image en francais",
                    f"image {os.path.basename(image)}", desc,
                    validator_provider=vp, validator_model=vm, timeout=options['timeout'])
                if 'error' in q:
                    self.stderr.write(self.style.WARNING(f"  QC indispo : {q['error']}"))
                else:
                    flag = ' ⚠ revue' if q['needs_human_review'] else ''
                    self.stdout.write(self.style.NOTICE(
                        f"  QC (plausibilite texte, validateur {q['validator']}) : "
                        f"{q['quality_score']}{flag} — {q['issues']}"))
        self.stdout.write(self.style.NOTICE(
            "\nJuge final = HUMAIN (le QC texte ne voit pas l'image). Compare les descriptions."))
