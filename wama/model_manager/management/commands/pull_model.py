"""
Télécharge un modèle Ollama (API officielle locale) et l'enregistre dans le catalogue WAMA.
Étape 2 du système d'auto-maintenance : accept→download→register.

  python manage.py pull_model bge-m3
  python manage.py pull_model qwen3.6:35b-a3b
  python manage.py pull_model nomic-embed-text --no-sync
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Telecharge un modele Ollama (API locale officielle) puis re-synchronise le catalogue."

    def add_arguments(self, parser):
        parser.add_argument('name', help="Nom du modele Ollama (ex: bge-m3, qwen3.6:35b-a3b).")
        parser.add_argument('--no-sync', action='store_true',
                            help="Ne pas re-synchroniser le catalogue apres le telechargement.")
        parser.add_argument('--timeout', type=int, default=1800)

    def handle(self, *args, **options):
        from wama.model_manager.services.model_installer import pull_ollama_model, register_after_install

        name = options['name']
        self.stdout.write(f"Telechargement Ollama : {name} …")
        res = pull_ollama_model(name, timeout=options['timeout'],
                                progress=lambda s: self.stdout.write(f"  … {s}"))
        if not res.get('ok'):
            self.stderr.write(self.style.ERROR(f"✗ Echec : {res.get('error')}"))
            return
        self.stdout.write(self.style.SUCCESS(f"✓ {name} telecharge ({res.get('status')})"))

        if options['no_sync']:
            self.stdout.write("(catalogue non re-synchronise : --no-sync)")
            return
        self.stdout.write("Re-synchronisation du catalogue …")
        sync = register_after_install()
        self.stdout.write(self.style.SUCCESS(
            f"✓ Catalogue re-synchronise (+{sync.added} ajoute(s), {sync.updated} maj)."))
        if sync.errors:
            self.stderr.write(self.style.WARNING(f"  {len(sync.errors)} erreur(s) de sync."))
