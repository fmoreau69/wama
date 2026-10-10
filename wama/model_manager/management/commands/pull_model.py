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

Ligne du CATALOGUE declaree par une app (cle) — le jumeau du bouton « Installer » (2026-10-10) :
  python manage.py pull_model avatarizer:codeformer
  (spec derive par `spec_for_catalog_row`, installe par `install_from_spec`, journalise)
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Telecharge un modele (Ollama ou HF) via API officielle puis re-synchronise le catalogue."

    def add_arguments(self, parser):
        parser.add_argument('name', help="Nom Ollama (ex: bge-m3) ou repo HF (ex: org/repo).")
        parser.add_argument('--category', help="HF : categorie de dossier = valeur ModelType (diffusion/speech/vlm/vision/upscaling/ocr/music/llm/embedding/lipsync).")
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

        # Une CLE de catalogue installable : la route du bouton « Installer » (meme spec, meme
        # pilote, meme journal) — un script d'installation d'app n'a plus a telecharger lui-meme.
        from wama.common.utils.model_keys import split_key
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=name, is_proposed=False).first()
        if row is not None:
            return self._install_catalog_row(row, options)
        if split_key(name)[0]:
            # Une clé (`<source WAMA>:…`) absente du catalogue n'est PAS un nom Ollama : on le dit
            # au lieu de demander `ollama pull avatarizer:…`.
            raise CommandError(f"« {name} » : clé absente du catalogue — `manage.py sync_models` "
                               "d'abord (la découverte de l'app la crée)")

        if is_hf:
            category = options.get('category')
            if not category:
                from wama.model_manager.models import AIModel
                m = AIModel.objects.filter(hf_id=name).first()
                if m:
                    category = _TYPE_CATEGORY.get(m.model_type)
            if not category:
                raise CommandError(
                    "Modele HF : preciser --category (valeur ModelType : diffusion/speech/vlm/"
                    "vision/upscaling/ocr/music/llm/embedding/lipsync).")
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

    def _install_catalog_row(self, row, options):
        """Installe une ligne du catalogue par SA spec (`spec_for_catalog_row`) — le corps de
        `install_catalog_task`, joue en synchrone : `install_from_spec` puis provenance et
        re-synchronisation (`record_provenance`), dans un evenement date du journal."""
        from wama.model_manager.services.install_history import opened
        from wama.model_manager.services.model_installer import (
            install_from_spec, pull_github_files, spec_for_catalog_row)

        spec = spec_for_catalog_row(row)
        if spec is None:
            raise CommandError(f"« {row.model_key} » ne declare pas d'emplacement d'installation "
                               "(install_dir + hf_id ou fichiers de version)")
        if options['dry_run']:
            res = (pull_github_files(spec, dry_run=True) if spec.get('files') is not None
                   else {'ok': True, 'target': spec.get('ref')})
            self.stdout.write(self.style.SUCCESS(f"✓ (dry-run) {res}"))
            return
        self.stdout.write(f"Installation depuis le catalogue : {row.model_key} ({spec['ref']}) …")
        with opened('model', row.model_key, name=row.name, via='cli') as outcome:
            res = install_from_spec(spec)
            outcome.update(res)
        if not res.get('ok'):
            raise CommandError(f"✗ Echec : {res.get('error')}")
        self.stdout.write(self.style.SUCCESS(
            f"✓ {row.model_key} : {len(res.get('downloaded') or [])} telecharge(s), "
            f"{len(res.get('kept') or [])} deja en place — catalogue re-synchronise"))
