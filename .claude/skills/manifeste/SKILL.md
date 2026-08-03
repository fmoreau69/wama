---
name: manifeste
description: Travailler sur la couche manifestes WAMA (7 kinds — app, library, model, function, pipeline, project, dataset) — extraire, composer via `requires`, contrôler, ingérer. Utiliser dès qu'une demande touche `wama/common/manifests/**` ou le corpus `manifests/**`, quand on relie une app à ses modèles/librairies, quand on parle d'auto-génération d'app, de projection vers les registres, ou d'un rôle LLM producteur de manifestes (librarian…).
---

# /manifeste — Couche manifestes : extraire, composer, contrôler, projeter

Le manifeste est **le formalisme** de WAMA : il décrit ce qu'une chose EST, de façon portable et
déclarative. Il ne décrit JAMAIS l'état runtime de cette installation.

> **Docs de référence — un domaine, un fichier (ne pas en créer un « bis »)**
> `WAMA_MANIFEST_SPEC.md` (formalisme, §7 composition) · `WAMA_MANIFEST_ARCHITECTURE.md`
> (flux/schéma, §5 auto-génération, §7 projection) · `ROADMAP.md` §16.7 (décision Hermes) ·
> `wama/model_manager/PROSPECTION_PIPELINE.md` (chaîne prospect→install→app).

## 1. Où est quoi

| Quoi | Où |
|---|---|
| Registre des kinds, dataclass `ManifestKind` | `wama/common/manifests/kinds.py` (`MANIFEST_KINDS`) |
| Un fichier par kind (`validate`/`extract`/`project`) | `wama/common/manifests/builtin/<kind>.py` |
| Enveloppe + `requires` + résolution | `wama/common/manifests/envelope.py` |
| Ingest (machine à états, idempotent/réversible) | `wama/common/manifests/ingest.py` |
| Projection vers les registres | `wama/common/manifests/projection.py` |
| Corpus d'exemples (à la RACINE, pas dans wama/) | `manifests/apps/*.json`, `manifests/libraries/*.json` |
| Rôle LLM « projet → manifeste library » | `wama-dev-ai/run_librarian.py` + `prompts/librarian.txt` |

## 2. Mesurer avant d'affirmer

Ne JAMAIS recopier un tableau d'état depuis un `.md` : ils dérivent. Mesurer :

```bash
# quels kinds ont réellement extract / project ? (source = les hooks passés à register_kind)
PYTHONPATH=. python -c "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');django.setup();import wama.common.manifests.builtin;from wama.common.manifests.kinds import MANIFEST_KINDS as M;[print(n, bool(k.extract), bool(k.project)) for n,k in sorted(M.items())]"
```

```powershell
# quels liens app -> model / library existent dans le corpus ?
Get-ChildItem .\manifests\apps\*.json | ForEach-Object { $j = Get-Content $_ -Raw | ConvertFrom-Json;
  "{0,-14} {1}" -f $_.BaseName, (($j.requires | Group-Object kind | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ' ') }
```

Photo au 2026-08-04 (à re-mesurer, pas à croire) : **`app` est le SEUL kind qui projette**, et
seulement sa facette `access` → `AppAccessPolicy`. `library`/`model`/`function`/`pipeline`/`project`
sont **store+verify only** — un manifeste de modèle ne crée aucun `AIModel`. `dataset` n'a même pas
d'`extract` : pour lui le manifeste EST l'origine.
Composition mesurée : **91 liens `app → model`** sur 9 apps (converter = 0, normal : ffmpeg/pandoc,
aucun modèle IA) et **0 lien `app → library`** — c'est LE trou ouvert de la composition.

## 3. Contrôles à relancer après toute modification

```bash
python manage.py manifest_export --check          # le corpus est-il à jour vs le code ?
python manage.py manifest_roundtrip --all         # extract -> ingest -> extract est-il fidèle ?
python manage.py doc_facts --check                # les blocs WAMA:FAITS des .md sont-ils à jour ?
python manage.py check_docs                       # liens/chemins des docs (3 CASSÉ connus)
```

Un round-trip qui diverge sur un champ **déclaratif** est un bug ; sur un champ **runtime**
(`is_loaded`, `local_path`, timestamps) c'est normal — ces champs sont volontairement exclus.

## 4. Garde-fous (non devinables — c'est pour eux que ce skill existe)

- **Frontière de responsabilité (§7.1)** : `library` possède dépôt, licence, version, install,
  points d'entrée, contraintes techniques. **JAMAIS** l'usage qu'une app en fait — ça, c'est le
  `requires` de l'app. Ne pas remonter d'usage applicatif dans un manifeste de librairie.
- **`library` ≠ `model`.** `faster-whisper` (paquet PyPI) est une `library` ; `Systran/faster-whisper-large-v3`
  (poids HF) est un `model`. `install.pip` n'a de sens que pour une `library` : un modèle se
  télécharge (ollama pull / HF snapshot / release Ultralytics), il ne s'installe pas par pip.
- **Semis EXPLICITE au corpus** : `manifest_export --kind library <clé>`. Aucun critère automatique
  ne décide qu'une lib mérite d'entrer — c'est une décision humaine.
- **Null plutôt que plausible** : ce qui n'est pas extractible reste ABSENT. Ne jamais inventer une
  contrainte GPU, une licence ou une version pour « compléter » un manifeste.
- **Un rôle LLM n'ingère JAMAIS.** Il écrit dans `wama-dev-ai/outputs/` avec
  `status: PENDING_HUMAN_VALIDATION`, ses erreurs de validation et ses `divergences_vs_mecanique`.
  Le LLM propose, la chaîne mécanique juge, l'humain valide. Patron de référence : `run_librarian.py`.
- **Le manifeste DÉCRIT, l'endpoint EXÉCUTE.** Un kind sans `project` ne peut rien écrire en base ;
  l'installation passe par `install_from_spec()` (`model_installer.py`), pas par la couche manifeste.
- **Verrous d'installation (ROADMAP §16.7, transposés d'Hermes)** : allowlist en dur dans l'arbre
  (la config utilisateur ne l'élargit pas), PyPI par nom seul (pas de `git+https`/`--index-url`/`file:`),
  pin PEP 440, kill switch. WAMA transpose les **verrous**, pas le **cycle de vie** : on installe à
  l'ingestion du manifeste (une fois, validée), pas à la première utilisation — motif :
  reproductibilité scientifique.

## 5. Écrire un nouveau kind

1. `builtin/<kind>.py` : `validate_<kind>_body()` + `extract_<kind>()` (+ `project_` seulement si un
   registre existe pour l'accueillir) puis `register_kind(ManifestKind(...))`.
2. L'importer dans `builtin/__init__.py` (sinon il n'est jamais enregistré).
3. Semer 1-2 exemples au corpus et lancer `manifest_roundtrip --all`.
4. Mettre à jour `WAMA_MANIFEST_SPEC.md` (formalisme) **et** `WAMA_MANIFEST_ARCHITECTURE.md`
   (tableau des kinds) — les deux dérivent vite.

## 6. Coordination

`wama/common/manifests/**` est un chemin **partagé entre instances Claude** : vérifier le handoff
(`PROJECT_STATUS.md` §REPRISE) avant d'y toucher, et commiter par chemins explicites.
Clôture du chantier : skill `/palier`.
