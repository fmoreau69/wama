# 🚀 Point de départ — prochaine session WAMA (préparé le 2026-07-01)

> Ce fichier existe pour **démarrer sans redonner le contexte**. Les mémoires (`MEMORY.md` + fichiers
> liés) sont chargées automatiquement en début de session — ce kickoff pointe la **tâche immédiate** et
> les fichiers à lire en premier.

## 🎯 Tâche immédiate : TÂCHE 1 — Inventaire de consolidation des mécanismes de génération d'UI

**Pourquoi** : le **registre de modèles est déjà unique** (`ModelRegistry` + `ModelInfo` + `capabilities`),
MAIS plusieurs **chemins concurrents de génération d'UI** coexistent → la moitié des apps suit un chemin,
l'autre un autre. Il faut **inventorier + désigner la référence + planifier la convergence AVANT** de
porter d'autres apps (sinon on aggrave la divergence).

**Déliverable** : créer `UI_MECHANISMS_CONSOLIDATION.md` (racine repo) — pour chaque axe : tableau
**mécanisme(s) | apps qui l'utilisent | RÉFÉRENCE à retenir | à DÉPRÉCIER | notes** + **ordre de
convergence exécutable**. Vérifier **empiriquement** (grep/read), pas de mémoire.

**Les 7 axes** (détaillés dans `memory/project_ui_mechanisms_consolidation.md`) :
1. Registre modèles (UNIFORME — vérifier cohérence des clés `capabilities`).
2. Descriptions/aide modèle : `help_source` (catalogue) vs `help_fallback` (dict inline).
3. Capacités→UI : `WamaModelCaps` (option-level) vs rien (transcriber) vs `show_if` **hardcodé** (à supprimer) ; manque le **niveau-champ**.
4. Modale item : `WamaParams.render(item)` (4/10) vs hand-built.
5. Volet : `WamaParams.render(panel)` vs `WamaInspector.initFromSchema`.
6. `params.py` : 8/10 (manquent **anonymizer, imager**).
7. Onglets domaine : `WamaModes` (enhancer) → généraliser Imager/Anonymizer.

**Référence** = **Transcriber**. **Contraintes** : route existante, **zéro réinvention, zéro hardcoding,
uniformité**. Compléter le **catalogue de capacités au fur et à mesure**.

## 📚 Fichiers à lire en premier
- **Mémoires** (chargées auto ; à ouvrir) : `project_ui_mechanisms_consolidation.md` (spec TÂCHE 1),
  `project_manifest_generation_priority.md` (le cap : uniformiser→manifests→génération),
  `feedback_ui_from_model_capabilities.md` (UI DEPUIS les capacités, pas de show_if hardcodé),
  `feedback_modales_vs_inspecteur_mode_simplifie.md` (ne pas retirer les modales : mode simplifié).
- **Docs de suivi** : `PROJECT_STATUS.md` **§20** (+ §19), `ROADMAP.md` **§2** (Templating générique —
  État 2026-07-01), `WAMA_APP_CONVENTIONS.md` **§22** (encadré consolidation), `CLAUDE.md` (règles).
- **Code de référence** (le patron à répliquer) : `wama/transcriber/` (`params.py`,
  `templates/transcriber/index.html` → `WamaParams.render`), briques
  `wama/common/static/common/js/{wama-params,wama-inspector,wama-model-caps,wama-modes}.js`,
  `wama/common/utils/param_schema.py`, `wama/model_manager/services/model_registry.py`.

## ✅ État à date (fait cette session)
- **Enhancer uniformisé** : onglets domaine `WamaModes` + bouton de cycle (2 domaines) + inspecteur
  `initFromSchema` par domaine + **modales portées sur `WamaParams` (context:'item')** + aide modèle
  courte/longue + **couche capacités pièce 1/3** (moteurs audio `resemble`/`deepfilternet` au catalogue
  avec `capabilities.params`).
- **Reste enhancer** (après/pendant TÂCHE 1) : pièce 2 (`WamaModelCaps` **niveau-champ**) + pièce 3
  (câblage capacités→visibilité + **retrait du `show_if` hardcodé** dans `wama/enhancer/params.py`) +
  **synchro catalogue → base `AIModel`** pour que le front lise les capacités.

## ⚠️ Rappels de méthode (contexte chargé = erreurs)
- Sessions courtes ; vérifier **empiriquement** avant d'affirmer (j'ai confondu « registration » et
  « tirage UI » en fin de session précédente).
- Valider serveur via WSL2 (`wsl.exe -e bash -lc '... venv_linux ... python ...'`), pas de `cd` en préfixe.
- Après modif JS : copier `wama/<app>/static/...` → `staticfiles/<app>/...`.
