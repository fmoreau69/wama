# Pipeline cible : prospection → installation → app, piloté par l'assistant IA

> Vision énoncée par Fabien (2026-07-17) : l'utilisateur exprime un BESOIN à l'assistant ;
> la chaîne va jusqu'au modèle installé dans la bonne app — ou jusqu'à la génération de
> l'app manquante. Ce document fige la cible, l'état des briques et l'ordre de réalisation.

## Le pipeline en 6 étapes

```
[1] Besoin utilisateur (assistant IA)
      « il me faut un modèle qui segmente les véhicules de nuit »
[2] Prospection : trouver les candidats + récupérer leurs CAPACITÉS
      (HF API : pipeline_tag, library_name, tailles ; releases Ultralytics ; Ollama)
[3] Identifier la LIBRAIRIE d'exécution (transformers, ultralytics, diffusers…)
      → dépendances pip éventuelles
[4] MATCHING besoin ↔ app existante (capacités déclarées dans APP_CATALOG)
      ├─ app trouvée → [5]
      └─ pas d'app  → [6]
[5] INSTALLATION par descripteur : install_from_spec({kind, ref, category,
      pip_dependencies, …}) → bon dossier + catalogue AIModel + backend prêt
[6] GÉNÉRATION d'app : manifeste (capacités, modes, UI schéma-driven) →
      routines de génération/auto-instanciation d'applications
```

## État des briques (2026-07-17)

| Étape | État | Brique |
|---|---|---|
| 1 | ✅ | AI-Assistant + `tool_api.py` par app — **manque le `tool_api.py` du model_manager** (exposer prospect/install/spec à l'assistant) |
| 2 | 🟡 | `services/prospector.py` (HF API déjà interrogée : `pipeline_tag`, librairie, downloads) + `prospect_agents.py` (évaluation LLM des candidats) — chaîne Ollama-first opérationnelle, à étendre : beat vision (releases Ultralytics + HF vision) |
| 3 | 🟡 | HF fournit `library_name` par modèle ; heuristique + passe LLM à écrire (petite) |
| 4 | 🟡 | Capacités d'apps déclarées (`APP_CATALOG`, `app_registry`) ; le matching besoin↔capacité est à écrire |
| 5 | ✅ | `install_from_spec()` (descripteur déclaratif, ce commit) + drivers `pull_ollama_model` / `pull_hf_model` / `pull_yolo_weights` / `pip_install_packages` + `register_after_install` |
| 6 | ⏳ | = chantier « manifests → génération LLM » DÉJÀ priorisé (voir `UI_MECHANISMS_CONSOLIDATION.md`, mémoire projet) — la vision s'y branche, ne pas dupliquer |

## Garde-fous (non négociables)

- **Validation humaine** pour toute dépendance pip (`spec.human_validated` requis) et pour
  la génération d'app. L'assistant PRÉPARE le spec ; l'humain valide l'exécution.
- **Sources fermées** : noms/refs officiels (Ollama, HF repo id, poids YOLO officiels) —
  jamais d'URL arbitraire dans le spec.
- **Path d'abord** (règle CLAUDE.md) : chaque driver installe dans l'arborescence dédiée
  (`model_locations` / `vision/yolo/<task>/`), jamais dans le cache HF global.

## Ordre de réalisation recommandé

1. ✅ `install_from_spec` (fait — point d'entrée unique, endpoint `{'spec': …}`).
2. `tool_api.py` du model_manager : exposer `search_models` (prospector), `model_catalog`
   (AIModel), `prepare_install_spec` (retourne le spec SANS exécuter), `install_model`
   (exécute un spec validé) à l'assistant.
3. Beat de prospection vision : candidats `is_proposed` avec spec attaché (Ultralytics
   releases + HF `pipeline_tag` vision), même UI « Proposés par IA » qu'Ollama.
4. Matching besoin↔app (capacités APP_CATALOG) — fonction pure, testable.
5. Génération d'app : rejoindre le chantier manifeste existant (P0).
