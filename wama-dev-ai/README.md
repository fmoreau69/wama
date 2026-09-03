# WAMA Dev AI

Agent de développement **local** (Ollama, `localhost:11434`) au service de WAMA : audits
read-only, génération de code bornée, et rôles producteurs de manifestes. Doctrine
(`CLAUDE.md §Collaboration wama-dev-ai`) : **Claude réfléchit, wama-dev-ai exécute, l'humain
valide** — jamais d'auto-application.

> ⚠ Réécrit le 2026-08-27 — l'ancien README décrivait l'outil de janvier 2026 : il faisait
> télécharger ~100 Go de modèles retirés du parc (`qwen2.5-coder`, `deepseek-coder-v2`,
> `llama3.1:70b`, `nomic-embed-text`…) et ignorait les rôles. **Règle : le parc de modèles, les
> rôles et les workflows se lisent dans `config.py` (source unique) — ne jamais les recopier ici.**

## Démarrage

1. **Ollama** installé et servi (sur cet hôte : voir `OLLAMA_HOST` — passerelle, pas 127.0.0.1) ;
2. les modèles du parc se lisent dans `config.py::MODELS` (sélection RAM-aware avec chaînes de
   repli via `select_model_for_role()`) — au 2026-08-27, l'agent fiable du parc 24 Go partagé est
   `gemma4:e4b` (non-thinking) et les embeddings sont `bge-m3` ;
3. `pip install -r wama-dev-ai/requirements.txt` ;
4. lancer **par chemin de script** (pas de `python -m` : le dossier a un tiret et `config.py` vit
   au-dessus du paquet) :

```bash
python wama-dev-ai/run.py                 # mode interactif (commandes : voir cli.py)
python wama-dev-ai/run.py -t "…"          # tâche unique
python wama-dev-ai/run_audit.py …         # rôle audit (read-only)
python wama-dev-ai/run_codegen.py …       # rôle codegen (code proposé, jamais appliqué)
python wama-dev-ai/run_librarian.py …     # manifestes de librairies
python wama-dev-ai/run_model_manifest.py … # manifestes de MODÈLES (identité, capacités, moteur)
python wama-dev-ai/run_scout.py …         # prospection de modèles (fiches candidates)
python wama-dev-ai/run_integrator.py …    # propositions d'intégration
```

⚠ `run_model_manifest.py` consulte **`WAMA_GPU_SAFE_MODE`** et refuse de partir quand il est
actif (`--force` pour un GO explicite) : son appel Ollama charge un modèle dans la VRAM de
l'hôte — le geste qui a crashé la machine deux fois le 2026-09-02. Même garde que
`ui_smoke._vlm_triage` ; tout rôle qui appellera Ollama devra la porter aussi.

## Les rôles (le cœur actuel de l'outil)

Chaque rôle est un **pilote borné** construit sur `role_utils.py` : un squelette mécanique
prépare le contexte, **un seul appel Ollama** produit la proposition, des contrôles la valident,
et la sortie atterrit dans `outputs/` en `PENDING_HUMAN_VALIDATION`. Les prompts vivent dans
`prompts/*.txt` (un par rôle). Détail de la chaîne prospection (scout/integrator) :
`wama/model_manager/PROSPECTION_PIPELINE.md §rôles`.

**Ce que wama-dev-ai ne fait JAMAIS** : écrire dans les fichiers de production, commiter,
appliquer quoi que ce soit sans validation humaine.

## Workflows et commandes

Les workflows (13 au 2026-08-27) sont déclarés dans `config.py::WORKFLOWS` ; les commandes
interactives dans `cli.py`. Ces deux listes ont déjà divergé du README par le passé — elles ne
sont plus recopiées ici.

## Prompt skills WAMA (source partagée)

Les skills de prompt de WAMA (`wama/common/prompt_skills/*.md`) sont lisibles par wama-dev-ai via
`config.py::PROMPT_SKILLS_DIR` ; accesseurs côté WAMA : `wama/common/utils/prompt_skills.py`
(`resolve_skill`, `skills_catalog`). Voir `wama/common/prompt_skills/README.md`.

## Format des sorties des rôles (remplace l'ex-`AUDIT_FORMAT.md`, archivé 2026-08-27)

> L'ancien `AUDIT_FORMAT.md` décrivait une enveloppe `wama_report` et une nomenclature
> (`audit_YYYY-MM-DD.json`, `model_watch_*`…) que **le code n'a jamais émises** — archivé
> (`docs/archive/WAMA_DEV_AI_AUDIT_FORMAT.md`). Le réel, produit par `role_utils.py::write_output` :

- **Nommage** : `outputs/{role}_{slug}_{AAAA-MM-JJ_HH-MM}.json` (rôles émetteurs : audit,
  codegen, librarian/library, scout, integrator) ; les autosaves d'audit sont en `.md`.
- **Schéma** : objet **plat** `{"status": "PENDING_HUMAN_VALIDATION", "role": "...", **payload}` —
  pas d'enveloppe.
- **La seule règle non négociable** : le statut est **toujours** `PENDING_HUMAN_VALIDATION`
  (mécanisé dans `role_utils.py`).

## Dépannage

- **« Connection refused »** : Ollama n'est pas servi, ou `OLLAMA_HOST` pointe 127.0.0.1 au lieu
  de la passerelle (mémoire `reference_ollama_host_windows`).
- **Modèle absent** : `ollama pull <nom lu dans config.py>` — jamais un nom lu dans un doc.
- **Lenteur** : préférer les petits modèles du parc ; vérifier `nvidia-smi` ; ⚠ ne pas lancer de
  passe LLM lourde sans gouvernance (les passes auto ont déjà déclenché des crashs hôte —
  `INFRA_WSL_VS_WINDOWS.md`).

## License

Part of the WAMA project.
