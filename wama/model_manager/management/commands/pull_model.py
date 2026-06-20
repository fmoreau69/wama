"""
Telecharge un modele (Ollama ou HuggingFace) et l'enregistre dans le catalogue WAMA.
Etape 2 du systeme d'auto-maintenance : accept->download->register.

Ollama (nom sans '/') :
  python manage.py pull_model bge-m3
  python manage.py pull_model qwen3.6:35b-a3b

HuggingFace (repo avec '/') — telecharge dans le dossier de la categorie (model_dir) :
  python manage.py pull_model black-forest-labs/FLUX.1-dev --category diffusion
  python manage.py pull_model <org/repo> --dry-run        # valide juste le dossier cible
  (si une entree 'recommended' existe pour ce hf_id, la categorie est deduite automatiquement)
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Telecharge un modele (Ollama ou HF) via API officielle puis re-synchronise le catalogue."

    def add_arguments(self, parser):
        parser.add_argument('name', help="Nom Ollama (ex: bge-m3) ou repo HF (ex: org/repo).")
        parser.add_argument('--category', help="HF : categorie de dossier (diffusion/speech/vlm/detect/enhance/ocr/music/llm).")
        parser.add_argument('--family', help="HF : sous-dossier famille (defaut = nom du repo).")
        parser.add_argument('--dry-run', action='store_true', help="HF : ne pas telecharger, montrer le dossier cible.")
        parser.add_argument('--no-sync', action='store_true', help="Ne pas re-synchroniser le catalogue apres.")
        parser.add_argument('--timeout', type=int, default=1800)

    def handle(self, *args, **options):
        from wama.model_manager.services.model_installer import (
            pull_ollama_model, pull_hf_model, register_after_install, _TYPE_CATEGORY)

        name = options['name']
        is_hf = '/' in name
        prog = lambda s: self.stdout.write(f"  … {s}")

        if is_hf:
            category = options.get('category')
            if not category:
                from wama.model_manager.models import AIModel
                m = AIModel.objects.filter(hf_id=name).first()
                if m:
                    category = _TYPE_CATEGORY.get(m.model_type)
            if not category:
                raise CommandError(
                    "Modele HF : preciser --category (diffusion/speech/vlm/detect/enhance/ocr/music/llm).")
            tag = ' (dry-run)' if options['dry_run'] else ''
            self.stdout.write(f"Telechargement HF : {name} → categorie '{category}'{tag} …")
            res = pull_hf_model(name, category, family=options.get('family'),
                                dry_run=options['dry_run'], progress=prog)
            if not res.get('ok'):
                self.stderr.write(self.style.ERROR(f"✗ Echec : {res.get('error')}"))
                return
            if res.get('dry_run'):
                self.stdout.write(self.style.SUCCESS(f"✓ (dry-run) dossier cible : {res['target']}"))
                return
            self.stdout.write(self.style.SUCCESS(f"✓ Telecharge dans {res['target']}"))
        else:
            self.stdout.write(f"Telechargement Ollama : {name} …")
            res = pull_ollama_model(name, timeout=options['timeout'], progress=prog)
            if not res.get('ok'):
                self.stderr.write(self.style.ERROR(f"✗ Echec : {res.get('error')}"))
                return
            self.stdout.write(self.style.SUCCESS(f"✓ Telecharge ({res.get('status')})"))

        if options['no_sync']:
            self.stdout.write("(catalogue non re-synchronise : --no-sync)")
            return
        self.stdout.write("Re-synchronisation du catalogue …")
        sync = register_after_install()
        self.stdout.write(self.style.SUCCESS(
            f"✓ Catalogue re-synchronise (+{sync.added} ajoute(s), {sync.updated} maj)."))
        if sync.errors:
            self.stderr.write(self.style.WARNING(f"  {len(sync.errors)} erreur(s) de sync."))
