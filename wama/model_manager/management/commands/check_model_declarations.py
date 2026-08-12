"""
Détecteur de dérive des DÉCLARATIONS de modèles — les tables à la main confrontées au
catalogue (la source unique).

  python manage.py check_model_declarations          # exit ≠ 0 si un tag déclaré est mort
  python manage.py check_model_declarations --json

La couche MANQUANTE de la chaîne existante (tracée le 2026-08-12) :
  - installation/remplacement : `pull_model` → `register_after_install` (synchro catalogue) ;
  - catalogue ↔ réalité (disque + hôte Ollama) : `verify_models` (la découverte interroge
    l'hôte en premier) — le catalogue était JUSTE quand la prospection a remplacé
    `qwen3.5:35b-a3b` par `qwen3.6:35b` ;
  - **déclarations ↔ catalogue : PERSONNE** — les tables à la main pointaient le tag mort
    sans que rien ne le dise (`_OLLAMA_MODEL_MAP` : l'assistant ; `wama-dev-ai/config.py` :
    les rôles dev-ai, où llava:34b et llama3.2-vision:11b étaient morts aussi). Un nom en
    dur ne casse que le jour où on s'en sert — même leçon que `_route_model_by_context`
    (2026-08-04).

Sources déclarées contrôlées (en ajouter une ICI quand une nouvelle table apparaît) :
  1. `wama-dev-ai/config.py::MODELS` — registre de rôles wama-dev-ai (`ollama_id`) ; à
     dessein DÉCOUPLÉ du catalogue (chaînes RAM-aware propres, unification = Phase 4) —
     ce contrôle est précisément ce qui rend le découplage tenable.
(L'ancienne source `wama.views._OLLAMA_MODEL_MAP` a été SUPPRIMÉE le 2026-08-12 : les rôles
du chat dérivent désormais du catalogue via `select_chat_llm` — la meilleure table est
celle qui n'existe plus.)
Verdict par tag déclaré : OK (catalogue, téléchargé) / NON TÉLÉCHARGÉ (catalogue le connaît
mais `is_downloaded=False` — ex. remplacé par la prospection) / INCONNU (aucune ligne
catalogue). NON TÉLÉCHARGÉ et INCONNU ⇒ exit 1.

Ne touche ni l'hôte ni le GPU : lecture du catalogue seule (la fraîcheur du catalogue
vis-à-vis de l'hôte est le travail de `verify_models`, pas le sien).
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def _norm(tag: str) -> str:
    """`bge-m3` et `bge-m3:latest` sont le même tag pour Ollama."""
    return tag if ':' in tag else f'{tag}:latest'


def _sources() -> dict:
    """{source: {tags déclarés normalisés}} — chaque table à la main est une source nommée."""
    out = {}
    import importlib.util
    chemin = Path(settings.BASE_DIR) / 'wama-dev-ai' / 'config.py'
    spec = importlib.util.spec_from_file_location('wama_dev_ai_config', chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out['wama-dev-ai/config.py MODELS'] = {
        _norm(c.ollama_id) for c in mod.MODELS.values() if getattr(c, 'ollama_id', None)}
    return out


class Command(BaseCommand):
    help = ("Confronte les tags Ollama DÉCLARÉS dans les tables à la main au catalogue "
            "AIModel (source unique) — exit ≠ 0 sur tag mort.")

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Rapport machine.')

    def handle(self, *args, **o):
        from wama.model_manager.models import AIModel
        catalogue = {}
        for cle, dl in AIModel.objects.filter(model_key__startswith='ollama:') \
                                      .values_list('model_key', 'is_downloaded'):
            catalogue[_norm(cle.split(':', 1)[1])] = dl

        rapport, morts = {}, 0
        for source, tags in _sources().items():
            absents = sorted(t for t in tags if t not in catalogue)
            non_dl = sorted(t for t in tags if catalogue.get(t) is False)
            rapport[source] = {'declares': len(tags), 'inconnus_catalogue': absents,
                               'non_telecharges': non_dl}
            morts += len(absents) + len(non_dl)

        if o['json']:
            self.stdout.write(json.dumps(rapport, ensure_ascii=False, indent=1))
        else:
            w, ok, err = self.stdout.write, self.style.SUCCESS, self.style.ERROR
            w(f"\nCatalogue : {len(catalogue)} tag(s) Ollama "
              f"({sum(1 for v in catalogue.values() if v)} téléchargés)")
            for source, r in rapport.items():
                if r['inconnus_catalogue'] or r['non_telecharges']:
                    detail = []
                    if r['non_telecharges']:
                        detail.append(f"non téléchargés : {', '.join(r['non_telecharges'])}")
                    if r['inconnus_catalogue']:
                        detail.append(f"inconnus : {', '.join(r['inconnus_catalogue'])}")
                    w(err(f"  {source} : {len(r['non_telecharges']) + len(r['inconnus_catalogue'])}"
                          f"/{r['declares']} MORT(S) — {' ; '.join(detail)}"))
                else:
                    w(ok(f"  {source} : {r['declares']} déclarés, tous au catalogue "
                         f"et téléchargés"))
            if morts:
                w(err("\n✗ Tags morts : corriger la table (remplacement de modèle) ou lancer "
                      "sync_models si c'est le catalogue qui retarde."))
        if morts:
            raise SystemExit(1)
