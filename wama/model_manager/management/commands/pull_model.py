"""
Installe un modele par la ROUTE d'installation — la demande du bouton « Installer » et de
l'assistant (`request_install` : garde d'espace disque, idempotence, tache Celery suivie au model
manager, journal voie `cli`). Les workers Celery doivent tourner.

Une CLE (ligne du catalogue ou candidat de prospection) :
  python manage.py pull_model avatarizer:codeformer
  python manage.py pull_model huggingface:depthpro

Un depot HuggingFace (`org/repo` ou son adresse) — la ligne du catalogue qui le porte, sinon sa
PROPOSITION (recherche nommee `seed_hf_search`, celle de l'assistant), puis la demande :
  python manage.py pull_model black-forest-labs/FLUX.1-dev

Pour TOUS les modeles et librairies d'une app : `install_requires <app> --apply`.

⚠ 2026-10-10 : la branche depot HF telechargeait elle-meme (`pull_hf_model`, `--category`) — sans
garde d'espace, sans candidat, sans journal : une entree parallele a la route unique du 19/09.
Elle passe par la route ; `--category`/`--family`/`--dry-run` n'avaient pas d'autre usage.

Un nom Ollama (sans '/') — sa PROPOSITION (`seed_ollama_candidate`, verifiee au registre),
puis la demande :
  python manage.py pull_model bge-m3

⚠ 2026-10-11 (decision de Fabien) : la branche Ollama tirait elle-meme (`pull_ollama_model`),
dernier ecart nomme de la route ; `--no-sync`/`--timeout` ne servaient que ce tirage.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Installe un modele par la route du bouton « Installer » : une cle, ou un depot HF / "
            "un nom Ollama proposes puis demandes.")

    def add_arguments(self, parser):
        parser.add_argument('name', help="Cle du catalogue, depot HF (org/repo) ou nom Ollama.")

    def handle(self, *args, **options):
        from wama.common.utils.model_keys import split_key
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.prospector import named_repo

        name = options['name'].strip()
        if split_key(name)[0] or AIModel.objects.filter(model_key=name).exists():
            return self._request_install(name)
        repo = named_repo(name)
        if repo:
            return self._hf_repo(repo)
        return self._ollama(name)

    def _hf_repo(self, repo):
        """Le depot designe : sa ligne du catalogue, sinon sa proposition — ecrite au besoin par
        la recherche nommee —, puis la demande. Jamais de telechargement hors de la route."""
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.prospect_ollama import PROPOSED_PREFIX
        from wama.model_manager.services.prospector import seed_hf_search

        row = (AIModel.objects.filter(hf_id__iexact=repo, is_proposed=False)
               .order_by('-is_downloaded').first())
        if row is not None:
            return self._request_install(row.model_key)
        cand = AIModel.objects.filter(hf_id__iexact=repo, is_proposed=True).first()
        if cand is None:
            self.stdout.write(f"Proposition du depot {repo} (recherche nommee) …")
            res = seed_hf_search(repo, max_retenus=1)
            if not res.get('ok'):
                raise CommandError(f"✗ {repo} : {res.get('error')}")
            cand = AIModel.objects.filter(hf_id__iexact=repo, is_proposed=True).first()
            if cand is None:
                raise CommandError(
                    f"« {repo} » n'a pas ete propose ({res}) : sa tache n'entre pas dans le "
                    "perimetre de la prospection (HF_TASKS) — rien n'est installe hors de la route")
            self.stdout.write(f"  → proposition {cand.model_key}")
        return self._request_install(cand.model_key)

    def _ollama(self, name):
        """Le nom demande : sa proposition (ou sa ligne s'il est installe), puis la demande."""
        from wama.model_manager.services.prospector import seed_ollama_candidate

        res = seed_ollama_candidate(name)
        if not res.get('ok'):
            raise CommandError(f"✗ {name} : {res.get('error')}")
        if res.get('created'):
            self.stdout.write(f"  → proposition {res['model_key']}")
        return self._request_install(res['model_key'])

    def _request_install(self, key):
        """`request_install` tel quel — le corps unique du geste « Installer » (2026-10-10 : une
        premiere version appelait ici `install_from_spec`, le pilote INTERNE, et sautait la garde
        d'espace disque, l'idempotence et le suivi de la tache — un chemin parallele)."""
        from wama.model_manager.services.model_installer import request_install

        res = request_install(key, via='cli')
        if res.get('ok'):
            if res.get('already_running'):
                self.stdout.write(f"… {key} : installation deja en cours — suivie au model manager")
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"✓ {key} : installation enfilee (tache {res['task_id']}) — suivie au model "
                    "manager ; un worker Celery doit tourner"))
            return
        if res.get('reason') == 'already_downloaded':
            self.stdout.write(self.style.SUCCESS(f"✓ {key} : deja installe"))
            return
        if res.get('reason') == 'not_found':
            raise CommandError(f"« {key} » : absent du catalogue — `manage.py sync_models` "
                               "d'abord (la decouverte de l'app cree la ligne)")
        raise CommandError((res.get('blocked') or {}).get('error') or res.get('error')
                           or res.get('reason'))
