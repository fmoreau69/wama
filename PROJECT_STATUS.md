# PROJECT_STATUS.md — Point d'étape des chantiers WAMA

> Photo des chantiers en cours. Mise à jour : **2026-06-23**.
> Marqueurs : ✅ fait · 🔄 en cours · ⏳ à faire. Détails par chantier dans les docs/mémoire référencés.

## 1. PromptPipeline (prompts centralisés §16.6 / §10.B) — bien avancé
Doc : [`PROMPT_PIPELINE.md`](PROMPT_PIPELINE.md).
- ✅ A Enrichissement génératif (`prompt_enrichment.py`, OFF par défaut `WAMA_PROMPT_ENRICH`)
- ✅ B Assistant (kind `intent`, résource-safe)
- ✅ C Transparence console (🌐 traduit / ✨ enrichi / 📎 référence ; silence si direct)
- ✅ D Composer câblé (MusicGen EN) + synthesizer tranché (TTS jamais traduit)
- ✅ Hook compréhension fichiers de référence (`reference_comprehension.py`, dormant)
- ⏳ Hook RAG (dépend de la fondation `wama/rag/`, §6)
- ⏳ Choisir le 1er adopteur `reference_field` (reco : sous-page describer doc-understanding)
- ⏳ Câbler QC (`qc.py`) en post-génération ; (option) preview pré-lancement

## 2. Model Manager — centralisation + prospection + UI volet droit
- ✅ Briques prospection/maintenance (détecteur MAJ, prospecteur HF, installeur Ollama+HF, QC, multi-agents, bench vision, sélecteur)
- ✅ **UI volet droit (débloque le test prospection via `/model-manager/`)** : inspecteur par-modèle
  câblé dans le **volet droit GLOBAL `#wama-right-panel`** (surcharge des blocs `right_panel_settings`
  /`right_panel_actions` de `base.html`) — PAS un drawer ad hoc. Réutilise `WamaInspector` (pattern
  transcriber) + auto-génération depuis `AIModel.to_dict()`. Clic carte → section « Inspecteur du
  modèle » : statut, description longue, ressources (VRAM/RAM/disque), identité (type/source/clé/
  backend/HF), format (actuel→préféré), chemin local, **capacités + extra_info** (métadonnées
  prospection) ; section « Actions du modèle » : lien HF, décharger si en mémoire, convertir vers
  `can_convert_to`. Highlight `.mm-active`, déselect restaure le hint.
- ✅ **Brique générique `WamaAutofill`** (`common/static/common/js/wama-inspector-autofill.js` +
  `common/css/wama-inspector-autofill.css`) : rendu du volet droit piloté par **schéma déclaratif**
  (`renderSections(data, schema)` / `renderActions(data, actions)` ; supporte badges/description/rows/
  kv/code, et actions when/href/onClick/expand). **model_manager rebranché dessus** (1er consommateur).
  Doc : `COMMON_REFACTORING.md` + `WAMA_APP_CONVENTIONS.md §22` + philosophie dans `CLAUDE.md`.
- ✅ **Inspecteur `/apps/` (2e consommateur de `WamaAutofill`)** : catalogue d'apps câblé dans le volet
  droit global — clic carte `.app-item[data-id]` → `WamaInspector` + `WamaAutofill` sur les métadonnées
  `APP_CATALOG` (`description_long`, types E/S, type de batch, **conformité** score/%/issues) + action
  « Ouvrir l'application ». Données exposées via `json_script` (`apps_list` + URL résolue côté vue).
- ⏳ **À généraliser** : items de file des apps génériques (inspecteur éditable = formulaire 3 niveaux,
  cf. `WAMA_APP_CONVENTIONS.md §22.1` — distinct du rendu lecture seule autofill).
- ✅ **Page allégée (2026-06-23)** : monitoring déplacé du corps vers le volet droit (déplacement de
  nœuds par JS `appendChild` → préserve handlers + polling). Section **Médias surchargée = jauges
  ressources** (GPU/RAM/Models/Disk, toujours visibles). **Memory Cleaner + idle** en section
  Paramètres, **visibles seulement si aucune card sélectionnée** (l'inspecteur prend la place quand
  une card est choisie). Corps de page = en-tête + filtres + catalogue. Footer (RAM/GPU global)
  inchangé. (Sûr : aucun appel externe à `WAMA_RIGHT_PANEL.*` n'écrase les sections du volet.)
- ✅ **Prospection « Proposés par IA » — Ollama-first (2026-06-24)** : chaîne complète prospect→cards
  candidates→install dans l'UI. Champs `AIModel.is_proposed/proposal_kind/confidence/update_complexity`
  (exclus de sync + update_checker). Service `prospect_ollama()` (MAJ Ollama anciens + seed curated,
  idempotent). Endpoints `api/prospect/{ollama,install,reject}`. UI : filtre « ✨ Proposés par IA »,
  cards badges confiance/complexité + Installer/Rejeter, inspecteur enrichi (section Prospection),
  bouton « Prospecter (Ollama) » dans la vue volet « aucune card sélectionnée ».
- ⏳ **Prospection — suites** : (a) confrontation multi-agents pour une confiance réelle (Ollama local
  + cloud **gemini free** ou grok via passerelle LiteLLM `llm_chat`) ; (b) découverte « nouveaux »
  large (registre Ollama) au-delà du seed curated ; (c) Celery beat hebdo (détecte/propose) ; (d) HF.
- ⏳ Étape 3 centralisation (adaptateurs anonymizer/transcriber + migration per-model)
- ⏳ Chargeur générique ; agents cloud pour confronter ; recherche web benchmarks
- ✅ **Backup distant en MIROIR (2026-06-24)** : `remote_backup` réplique l'arbo locale `AI-models/
  models/` (`dest = WAMA_MODEL_BACKUP_PATH / source.relative_to(AI_MODELS_DIR/'models')`), récursif
  (préserve blobs/refs/snapshots), zéro chemin en dur. + `offload_file()` (flag opt-in
  `delete_source_after_backup` dans convert-and-backup) : backup → vérif taille distante → suppression
  locale, garde-fou si vérif échoue. Montage WSL : `\\vrlescot\SAVES`→`/mnt/shares/SAVES` (drvfs/fstab),
  env `WAMA_MODEL_BACKUP_PATH` dans `start_wama_prod.sh`.

## Tests fonctionnels nocturnes (charpente, 2026-06-24)
- ✅ **Charpente** : `common/services/nightly_tests.py` (registre déclaratif `Scenario` + runner
  **sérialisé VRAM-aware** avec téardown avant/après + rapport JSON + **user de test dédié**
  `wama_nightly_test`, jamais id=1) + commande `python manage.py run_nightly_tests [--app][--stage][--dry-run]`.
  Étapes : `wired` | `model_loaded` | `output`. **Skip vs fail** (`SkipScenario` → ⊘, dépendance absente).
- ✅ **Gabarits `model_loaded`** : `transcriber.asr_load` (VALIDÉ runtime, charge Whisper ~10 s) +
  `enhancer.deepfilternet_load` (skippe si `df` absent). Pattern : `<app>/nightly_scenarios.py` +
  `register_scenarios()` dans `apps.py::ready()`.
- ✅ **Infra** : tâche Celery `common.run_nightly_tests` (queue gpu) + beat **gated** (03:00 si
  `NIGHTLY_TESTS_ENABLED=1`, sinon pas d'auto-run).
- ⏳ **À compléter** : scénarios autres apps (imager/synthesizer/anonymizer) ; vrais `output` sur
  fixtures (assertions + nettoyage IDs) ; timeout dur (Celery soft_time_limit) ; page de résultats ;
  activer le beat après validation WSL.

## 2bis. Inspecteur volet droit unifié (modèles + apps) — 🔄
Un seul composant `WamaInspector`, deux catalogues, contenu généré depuis la métadonnée.
- 🔄 **Apps** (`/apps/` ← `common/app_registry.py::APP_CATALOG`, 10 apps génériques) : ajout d'un champ
  `description_long` par app → volet droit = inspecteur d'app (description complète + I/O + batch +
  **score conformité live + conventions manquantes** via `get_conformity_summary`).
- ⏳ **Modèles** : idem §2 (inspecteur par-modèle depuis `AIModel.to_dict()`).
- ⏳ **Lacunes catalogue** : `media_library` et apps **WAMA Lab** (cam_analyzer, face_analyzer) absents
  de `APP_CATALOG` (catalogue = apps génériques seulement) → décider de les inclure (flag `lab`/`hub`).
- ⏳ **Grille §15** (WAMA_APP_CONVENTIONS) = photo manuelle (2026-05-16) dérivée du registre live →
  remplacer par un pointeur vers `/apps/` (ou auto-sync). Scores live : converter/describer/reader/
  transcriber=13 (top) ; **avatarizer, imager=6 (à travailler)**.

## 3. wama-dev-ai (agent Ollama local) — fiabilisé
- ✅ Robustesse runner (troncature, retry EOF, read_file numéroté, fallback `gemma4:e4b`, `--force-model`, cp1252) — validé pour audit ciblé
- ✅ Règle de délégation scopée (CLAUDE.md) + `wama-dev-ai/query_transcript.py`
- ⏳ Calibration sélecteur RAM ; Phase 2 (API WAMA read-only) ; option routage cloud LiteLLM ; Phase 4 MCP (plus tard)

## 4. Refactoring common (unification) — documenté
Doc : [`COMMON_REFACTORING.md`](COMMON_REFACTORING.md). Transcriber = référence.
- ✅ Briques extraites (wama-app-base, wama-inspector, wama-model-help, partials cards, eta…)
- ⏳ `common/utils/backend_selector.py` (VRAM + singleton `keep_loaded`) ; `_settings_modal.html` générique
- ⏳ Adoption app par app (converter, describer, enhancer, imager, reader, synthesizer, anonymizer, composer)

## 5. Cam Analyzer (WAMA Lab) — consigné, à finaliser
Docs : `wama_lab/cam_analyzer/CONTEXT.md` + `README.md` + ROADMAP §9.
- ✅ Pipeline quasi-complet (extraction rosbag/RTMaps, YOLO+BoTSORT, YOLOPv2, SAM3, LaneEvent, ConflictEvent/TTC, fenêtres intersection, passes incrémentales)
- 🔄 Tests (pas tout validé)
- ⏳ Phase 3 vitesses irréalistes (calibration + références sol + lissage) ; infos caméras pour mesures absolues ; valider passes incrémentales ; (option) palliatif UI segments < 1 s

## 6. RAG (fondation §8c) — non démarré (prérequis du hook RAG §1)
- ⏳ Store ChromaDB + embedder bge-m3 ; module `wama/rag/` (store + embedder) ; indexation via Médiathèque

## 7. Anonymisation multimodale (§16.4) — décidé, non construit
- ⏳ Presidio + GLiNER FR ; mode « texte » = porte privacy avant-cloud (même composant) ; audio (PII + biométrie) ; dispatcher par modalité

## 8. Translator (§10)
- ✅ 10.B runtime (via PromptPipeline)
- ⏳ 10.A i18n statique (.po/.mo) ; glossaire éditable ; graduer `translator.py` → app `wama/translator/`

## 9. Media Library
- ✅ Phase 1 (UserAsset/SystemAsset, voix migrées)
- ⏳ Phase 2 (filtrage UI) · Phase 3 (connecteurs + clés API) · Phase 4 (Wikimedia, Pixabay, Freesound). Lié à l'indexation RAG.

## 10. Progression globale + ETA
- ✅ Déployé : converter, avatarizer, composer
- ⏳ Reste : describer, enhancer, transcriber, imager, reader, synthesizer, anonymizer + ETA batch

## 11. Transcriber — correction assistée IA (à reconfirmer dans le code)
Doc : `wama/transcriber/TRANSCRIBER_CORRECTION.md`.
- ✅ Éditeur page dédiée (onde + heatmap), guidage non destructif, timecode « aller à », défaut ASR Whisper large-v3
- ⏳ Suite de la correction assistée

## 12. Document understanding / OpenScholar (§10.B) — non construit
- ⏳ Sous-page Describer : Reader/Docling → multimodal → description FR directe. = 1er adopteur naturel du hook fichiers de référence.

## 13. Déploiement — note d'architecture
- ⏳ Migration Apache Windows → Nginx Linux ; plan serveur prod (LiteLLM orchestrateur). Voir `memory/project_deployment_roadmap.md`.

## Bugs / dettes connus
- 🐞 Higgs Audio V2 : ~5 s d'audio dégradé malgré tous les patches — non résolu.
- 🔧 Patches venv → toujours via `patches/apply_patches.py`.
- 🌐 Headroom code-aware : `Mode: token` actuel → activer via terminal neuf + vérifier `headroom_stats`.

## Ordre de reprise recommandé
1. Model Manager volet droit (débloque le test prospection — ROI immédiat).
2. Cam Analyzer Phase 3 (calibration + vitesses).
3. Fondation RAG (`wama/rag/`) — débloque hook PromptPipeline + Media Library.
4. Refactoring common app par app (par petites sessions).
