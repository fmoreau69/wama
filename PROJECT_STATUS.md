# PROJECT_STATUS.md — Point d'étape des chantiers WAMA

> Photo des chantiers en cours. Mise à jour : **2026-07-20** (bugs ROADMAP §0 repris ; conformité 2026-07-11 (§31 : audit empirique conformité 10 apps).
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

> **État réel gestion VRAM — inventaire vérifié 2026-07-20** (demande Fabien : « tracer le réel »).
> **EXISTE** : ① `select_model()` (`model_manager/services/model_selector.py`) = sélecteur central
> complet — budget VRAM **live** (`get_free_vram_gb`), « le plus gros qui tient », `prefer_loaded`
> (lit `AIModel.is_loaded`), filtre capacités `requires`/`classes`, paliers `priority`,
> `availability_probe` runtime ; il se déclare remplaçant du `backend_selector` planifié
> (CLAUDE.md corrigé en conséquence) ; ② `WAMAMemoryCleaner` **automatique** (thread périodique,
> décharge idle 300 s, seuils RAM/GPU 80-95 % → cleanup agressif) + API/UI volet droit ;
> ③ `memory_monitor` (jauges + budget du sélecteur) ; ④ contrat `unload()` de `BaseModelBackend`
> sur toutes les apps ; ⑤ `vram_gb` déclaré partout (model_config par app + catalogue `AIModel`) ;
> ⑥ nightly runner **sérialisé VRAM-aware** (teardown avant/après) ; ⑦ ETA hardware-aware
> (`ModelRuntimeStat` par GPU) ; ⑧ sélection LLM par tier (`llm_utils`) + wama-dev-ai
> `select_model_for_role` (découplés by design, jonction = Phase 4 MCP) ; ⑨ sélecteur
> app-spécifique anonymizer (précision/perf).
> **MANQUE (affinages réels)** : ⓐ `select_model()` = **0 consommateur TOUT COURT** (contre-vérif
> exhaustive 2026-07-20 sur question Fabien : ni apps, ni tool_api, ni studio, ni assistant, ni
> wama-dev-ai — ces derniers ont leurs sélecteurs PROPRES : `select_model_for_role` Ollama,
> tiers `llm_utils`, précision anonymizer) — l'« étape 3 adaptateurs » ⏳ ci-dessous EST ce
> chantier d'adoption ; l'imager choisit par priorité/disponibilité, pas par VRAM libre.
> **1er adopteur : COMPOSER — CÂBLÉ 2026-07-21 ✅** (validé sur base live + VRAM réelle :
> sans réf → musicgen-medium, avec réf → musicgen-melody, sfx → audiogen-medium).
> Design conforme à la décision 2026-07-02 (pas de switch de type) : pseudo-modèles
> **`auto-music`/`auto-sfx`, un par optgroup** (params.py), type dérivé du choix (`_model_type`,
> views), métas WamaInputMatch = union des entrées par groupe (`_input_match_meta`), résolution
> AU LANCEMENT de la tâche (`utils/auto_model.py` : candidats par capacités CATALOGUE → arbitrage
> `select_model(candidates=…)` → replis étagés). ⚠ Reste : validation NAVIGATEUR (option 🧠 dans
> les 2 groupes, grisage auto-sfx si mélodie, génération réelle) + restart WSL2.
> **Suites** : imager avec cette recette ; généralisation `where=` (filtre par VALEUR de capacité,
> ex. task=) dans select_model pour éviter le calcul de candidats côté app ; ⓑ pas d'**éviction synchrone au
> chargement** (le cleaner est périodique/seuils) : si un modèle ne tient pas, rien ne décharge
> les idle des AUTRES apps à l'instant T ; ⓒ pas de **coordination inter-process** (Django +
> workers Celery lisent chacun la VRAM ; seul le nightly sérialise) → double chargement concurrent
> possible ; ⓓ `keep_loaded` = comportement `prefer_loaded`/`is_loaded`, pas un flag persistant
> par modèle (à décider si besoin réel).
- ✅ Briques prospection/maintenance (détecteur MAJ, prospecteur HF, installeur Ollama+HF, QC, multi-agents, bench vision, sélecteur)
- ✅ **UI volet droit (débloque le test prospection via `/model-manager/`)** : inspecteur par-modèle
  câblé dans le **volet droit GLOBAL `#wama-right-panel`** (surcharge des blocs `right_panel_settings`
  /`right_panel_actions` de `base.html`) — PAS un drawer ad hoc. Réutilise `WamaInspector` (pattern
  transcriber) + auto-génération depuis `AIModel.to_dict()`. Clic carte → section « Inspecteur du
  modèle » : statut, description longue, ressources (VRAM/RAM/disque), identité (type/source/clé/
  backend/HF), format (actuel→préféré), chemin local, **capacités + extra_info** (métadonnées
  prospection) ; section « Actions du modèle » : lien HF, décharger si en mémoire, convertir vers
  `can_convert_to`. Highlight `.mm-active`, déselect restaure le hint.
- ✅ **Brique générique `WamaDetails`** (`common/static/common/js/wama-inspector-autofill.js` +
  `common/css/wama-inspector-autofill.css`) : rendu du volet droit piloté par **schéma déclaratif**
  (`renderSections(data, schema)` / `renderActions(data, actions)` ; supporte badges/description/rows/
  kv/code, et actions when/href/onClick/expand). **model_manager rebranché dessus** (1er consommateur).
  Doc : `COMMON_REFACTORING.md` + `WAMA_APP_CONVENTIONS.md §22` + philosophie dans `CLAUDE.md`.
- ✅ **Inspecteur `/apps/` (2e consommateur de `WamaDetails`)** : catalogue d'apps câblé dans le volet
  droit global — clic carte `.app-item[data-id]` → `WamaInspector` + `WamaDetails` sur les métadonnées
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
- ⏳ **Prospection — routing capacité→app (Axe 3, décidé 2026-06-29)** : à la proposition d'un modèle,
  inférer tâche + types E/S (pipeline_tag/tags/README HF) puis **réutiliser le matcher de capacités**
  (`app_registry.normalize_types`, déjà utilisé par le studio) contre `APP_CATALOG.input_types/
  output_types` → annoter la suggestion d'un `target_app` (« intègre dans X ») ou « aucune app ».
  **Phase A** (router vers app existante) = faisable, fort ROI ; **Phase B** (faire émerger une app
  depuis un manifeste généré) = **gatée** sur la maturité du runtime manifeste (axes B/C/D/F du
  `GENERALIZATION_PLAN`, Transcriber-seul aujourd'hui). Toujours humain-dans-la-boucle, jamais
  d'auto-application. Cf. `memory/project_queue_solitaire_prospection.md`.
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
  remplacer par un pointeur vers `/apps/` (`get_conformity_summary()`, seule source à jour ; NE PAS
  recopier de scores figés ici, ils dérivent). Scores live **2026-07-02** (après correction F1 des flags
  `inspector`/`modes`, cf. REMOVAL_LEDGER) : transcriber 76% (top) · describer/enhancer/reader 68% ·
  converter 62% · synthesizer 61% · anonymizer 59% · composer 57% · **imager 42%, avatarizer 40%
  (à travailler)**.

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
- ✅ 2026-07-09 **Phases 2-4 en fait FAITES** (doc périmé corrigé — vérifié empiriquement lors de
  l'audit doc §23) : filtrage UI présent (`index.html`), `MediaProvider`/`UserProviderConfig`
  (migration `0004`) + connecteurs Wikimedia/Pixabay/Freesound/Jamendo/Pexels/Openverse (migration
  `..._add_providers_phase5`). Reste lié à l'indexation RAG (§6, non démarré).

## 10. Progression globale + ETA
- ✅ **Barre globale + balayage coloré** : tronc commun (`_global_progress.html` + `wama-global-progress.js`), card « Nouveau » en 1ʳᵉ position, déployé partout (apps mono- et multi-domaine, barres séparées par file).
- ✅ **ETA seeding auto-apprenant + hardware-aware (terminé 2026-06-27)** : service `model_manager/services/eta_estimator.py` (`ModelRuntimeStat` EMA par modèle×hardware, a-priori par domaine, `fallback_seconds` = heuristique app au démarrage à froid). **Câblé sur les 10 apps** (transcriber, synthesizer, describer, reader, composer, converter, imager image+vidéo, enhancer image/vidéo+audio, avatarizer). 2 patterns : service-based vs load-séparé (imager). Nouvelles unités `page` (OCR) / `mb` (ffmpeg). Détail : `memory/project_eta_seeding.md`.
- ⏳ Reste : **valider sur données réelles** (restart WSL2) ; calibrer les a-priori par modèle (`AIModel.extra_info['eta']` ou test nocturne) ; ETA agrégé batch ; anonymizer (pas encore câblé — vérifier).

## 11. Transcriber — correction assistée IA (à reconfirmer dans le code)
Doc : `wama/transcriber/TRANSCRIBER_CORRECTION.md`.
- ✅ Éditeur page dédiée (onde + heatmap), guidage non destructif, timecode « aller à », défaut ASR Whisper large-v3
- ⏳ Suite de la correction assistée

## 12. Document understanding / OpenScholar (§10.B) — non construit
- ⏳ Sous-page Describer : Reader/Docling → multimodal → description FR directe. = 1er adopteur naturel du hook fichiers de référence.

## 13. Déploiement — note d'architecture
- ⏳ Migration Apache Windows → Nginx Linux ; plan serveur prod (LiteLLM orchestrateur). Voir `memory/project_deployment_roadmap.md`.

## 14. WamaModes (clé de voûte modes) + Mots-clés de prompt — palier 2026-06-25
Doc : `MODES_QUEUE_UX.md` (P1 schéma), `memory/project_prompt_keywords.md`.
- ✅ Schéma déclaratif domaines→modes (`common/utils/app_modes.py`) + générateur JS (`common/static/common/js/wama-modes.js`) + endpoint `/common/api/app-modes/<app>/`.
- ✅ **Imager (app de référence)** : WamaModes **pilote les barres de mode** image+vidéo (`renderInputs:false`) ; radios natifs = source de vérité (cachés si rendu OK, résilient sinon). Apparence préservée via `domain.variant` (image=bleu, vidéo=vert), `block` (pleine largeur), `modesLabel`. Schéma vidéo aligné `txt2vid`/`img2vid`.
- ✅ **Mots-clés de prompt** : modèle `PromptKeyword` (tronc commun + perso) dans la médiathèque, seed 52, 3 endpoints, brique commune `wama-prompt-chips.js` (chips par catégorie, insère/retire dans le prompt, + perso, badge `onCount`). Câblé Imager (prompt image+vidéo) + onglet « Mots-clés » médiathèque.
- 🔄 **À confirmer visuellement** (Fabien teste après restart serveur) : chips affichés + badge 52.
- ⏳ Prochain palier WamaModes : `renderInputs:true` (entrées typées + réglages par mode sur la card « Nouveau ») — **touche la soumission, à faire délibérément** (pas en cours de test). Puis réplication du pilotage de modes sur anonymizer (yolo/sam3) / synthesizer (temps réel).
- ⚠️ Règle : préserver la mise en forme à l'identique en généralisant (`memory/feedback_preserve_formatting.md`).

## 15. Méta-app studio + vision production AV — palier 2026-06-25
Docs : `STUDIO_VISION.md`, `memory/project_meta_app_studio.md`, `memory/project_studio_av_production.md`.
- ✅ **Studio = app Django dédiée `wama/studio`** (migrée de `common`) : `/studio/` + `/studio/api/nodes/`. Nœuds-app dérivés `APP_CATALOG`+`app_modes`, **ports typés** travail/prompt/référence, **catégories unifiées**, **typage par connexion**, nœuds-source (Batch de prompts, Médias importés), **inspecteur volet droit** (WamaDetails). Vraie app : nav + card accueil (Bêta), gatée par accès.
- ✅ **Vision AV consignée** : studio = pipeline montage vidéo + mixage/mastering assistés IA. Prior art `MusicVideoGenerator`. Monteur/Mastering = **roadmap only** (retirés des nœuds concrets).
- ✅ **Décision archi** : montage & mixage = **apps dédiées** ; Monteur = 1 app à modes + `edit_page` par mode ; Mixage/Mastering plus tard.
- ✅ **Persistance + exécution V1** (2026-07-11, §37) : StudioPipeline/StudioRun, moteur
  Celery topo (runners synthesizer→avatarizer via tool_api), toolbar Save/Load/Run,
  coloration des nœuds. ⏳ Suites : plus de runners (imager, converter…), sorties → dossier
  filemanager studio, ports multi-entrées, specs Fabien (montage/mixage).

## 16. Profils / permissions / notifications / rétention — palier 2026-06-25
Doc : `PROFILES_PERMISSIONS.md` + `memory/project_profiles_permissions.md`.
- ✅ **Permissions 2 axes** : `UserProfile.account_tier` + rôles métier (Groups `role:*`) ; `AppAccessPolicy` DB **éditable** ; **matrice rôles×apps** (`/accounts/manage/app-access/`) groupée en sections + tooltips ; liste d'apps **pilotée par le registre** (`seed_access` sur `APP_CATALOG ∪ extras`). Enforcement nav + cartes home + middleware (`app_id_for_path`). Seeds auto au démarrage (`start_wama_*.sh`).
- ✅ **Notifications email** : `notify_email`/`notify_on` (page profil) + `common/utils/notifications.py` + signal imager + câblé **les 10 apps**.
- ✅ **Rétention médias** : `media_retention_days` (page profil) + `common/services/retention.py` (purge par introspection) + beat quotidien + pré-avis.
- ⚠️ Bases Postgres **distinctes** Windows/WSL2 (cf. `memory/reference_infra_wsl_windows`) — agir via `wsl.exe` pour le live.

## 17. Uniformisation — gold standard Transcriber (⭐ PHASE COURANTE)
Voir `memory/feedback_transcriber_gold_standard`. Stratégie : finir **Transcriber** à 100 % (conformité + esthétique file Solitaire épurée) → recette, puis dérouler à toutes (Imager en dernier). **Garde-fous** : préserver temps réel (Speak) + page de correction (laissée telle quelle, bouton non généralisé).

**Réaffirmé 2026-06-29 (Fabien)** : on FINIT le Transcriber AVANT la généralisation §18 (« finir 1 app
puis généraliser »). Déjà avancé : briques communes (`_new_item_card`/`_card_progress`/`_card_state`/
`_queue_actions`), animation fan-in Solitaire, switch mode normal/temps réel. **Reste :**
- ⏳ **Card d'entrée UNIVERSELLE** : fusionner le **Speak (temps réel) DANS `_new_item_card`** (affordance
  Speak à côté de drop/fichier/URL/batch), à la place du **sélecteur de mode** en haut de page (entrée
  progressive, cf. accordéon prototypé sur Synthesizer). **Préserver Speak intact** (garde-fou). = le
  morceau central.
- ✅ **Staging supprimé (2026-06-29)** — décidé Q2, cf. `CARD_DESIGN §8.5`. « Staging » = statut `DRAFT`.
  `_auto_wrap_orphans` n'exclut plus `DRAFT` → brouillons rendus **dans la file** comme cards BROUILLON
  (config via inspecteur, lancement via `start` qui gère DRAFT). Retirés : `staging_list` + `#stagingZone`
  (IndexView/template), 4 vues `stage_*` + URLs, config JS + handlers JS staging. Validé : `check` OK,
  page 200, zéro résidu. Reste lié : focusCard sur l'ajout en brouillon (déjà câblé upload/duplication).
- ✅ **Animation fan-in** ralentie (.26→.42s + stagger + easing, 2026-06-29).
- ⏳ **Finition esthétique** : conformité CARD_DESIGN (2 états, barre pleine largeur, boutons
  color-codés, aperçu sortie systématique, inspecteur).
- ⏳ Les items §18 (`focusCard`, card mère `_batch_card`, manipulation in/out, insertion chronologique)
  reçoivent leur **implémentation de référence SUR le Transcriber**, puis sont extraits en commun.

→ Transcriber à 100 % **d'abord**, puis §18 (généralisation) + Synthesizer/Imager.

## 18. File Solitaire — focus, card mère homogène, animation (décidé 2026-06-29) — ⏳
Doc : `CARD_DESIGN.md §8`. Affine §17 (file épurée) + §3ter (pile Solitaire).
**Séquencement : APRÈS §17** — ces items reçoivent leur implémentation de référence SUR le Transcriber
(dans le cadre de « finir le Transcriber »), puis sont extraits en briques communes pour les autres apps.
- ⏳ **Focus à l'ajout + nav** : helper commun `WamaQueue.focusCard(id, {scroll:'center',select,pulse})`
  (scrollIntoView centré + halo + sélection inspecteur), partagé ajout ET nav clavier. Inspecteur non
  bloquant à l'ajout (PAS de modale auto). `scroll-margin-top` = hauteur header (bug card du haut masquée).
  Le bug « card en bas de pile » est **app-spécifique** (PAS commun) → remède = **centraliser une
  insertion déterministe chronologique** ; les apps qui l'adoptent perdent le bug.
- 🔄 **Tri/filtrage de la file** : **EXTRAIT EN COMMUN (2026-07-03)** — `common/utils/queue_view.py`
  (`apply_queue_sort_filter`, persisté en session, clés partagées entre apps) + partial
  `common/_queue_toolbar.html` (tri + filtre + toggle Ligne/Mosaïque + `_queue_actions`, option
  `download_url`). **Consommé : Transcriber (pilote 2026-06-29, basculé sur la brique) + Composer
  (hérite, 2026-07-03)**. Défaut chronologique récent = acté partout. **Reste** : porter aux 8 autres
  apps (le **reader** a encore son tri batch-first app-spécifique) ; options sort type/durée.
  **CSS mosaïque aussi globalisé** (contrat `.wama-card`, wama-inspector.css) : solitaire (batch
  replié = cellule mosaïque, déplié = pleine largeur), empilement VERTICAL des sections en grille,
  fan-in — corrige la régression solitaire Transcriber ET la compression horizontale Composer.
- 🔄 **Manipulation directe (CARD_DESIGN §3bis)** : déplacer DANS/HORS d'un batch = **DRAG souris façon
  Solitaire, PAS un bouton** (spec d'origine Fabien ; déjà trop de boutons). **Backend prêt + validé**
  (2026-06-29) : vue/URL `remove_from_batch` (sortie → `_wrap_transcript_in_batch` = batch-of-1 isolé ;
  signal recale l'ancien batch) + `consolidate` (entrée). **Reste = l'UI DRAG** (SortableJS, posera
  `wama_focus_card` sur l'id déplacé). **Backend du drag COMPLET + validé (2026-06-29)** : `remove_from_batch`
  (sortie), `reorder` (`row_index` dans un batch), `move_to_batch` (entrée), `consolidate` (existant).
  **Reste = uniquement l'UI SortableJS** branchée sur ces endpoints → **session VISUELLE**. (Filtrer/trier
  = FAIT, voir bullet ci-dessous.) NB : bouton « sortir » ajouté par erreur puis retiré.
- ✅ **Fix hauteur mosaïque** (2026-06-29) : cards individuelles à hauteur égale par ligne
  (`align-self:stretch`) ; card batch laissée courte (distinction, choix Fabien).
- 🔄 **Card mère = squelette des filles** : **P1 FAIT + validé sur le Transcriber (référence, 2026-06-29)** :
  la mère est désormais `.synthesis-card.is-batch` (MÊME squelette `.row` que les filles : identité
  Batch#/N éléments, état agrégé, barre de progression agrégée, actions batch) ; ne diffère que par
  `.is-batch` (couleur) + méta/actions. Toggle collapse scopé sur `col-md-9` (actions HORS toggle →
  handlers délégués préservés) ; look « pile Solitaire » + fan-in conservés. **+ bouton ▶ Lancer/Relancer
  ajouté sur la card mère** (pos. 2, vue `batch_start`, sans passer par la modale) → convention fixée
  `WAMA_APP_CONVENTIONS §9.8`. **Reste** : extraire en
  brique commune `common/templates/common/_batch_card.html` (réutilise `_card_progress`/`_card_state`)
  pour dédupliquer entre apps, puis P2 (éventail `translateY`) / P3 (polish).
- ⏳ **Dépliage éventail + animation** : P1 mère `.is-batch` + collapse Solitaire existant ; P2 overlap
  `translateY` ∝ distance à la card sélectionnée + stagger ; P3 durée ~0,35–0,45 s easing (trop rapide
  aujourd'hui). Lié `wama-queue.js`.

- ⏳ **Card d'import homogène (DIFFÉRÉ passe visuelle/globalisation)** : la rendre card-like + 1ʳᵉ card
  de la file (accordéon : replié compact homogène ↔ déplié = modalités d'import avec de la place ; NE PAS
  miniaturiser les champs). Décision/impl **une seule fois** dans `_new_item_card` après globalisation.
  + retirer la répétition « File d'attente » de l'en-tête. Détail : `CARD_DESIGN §8.6`.
- ✅ **Tri groupé** (2026-06-29) : options « Batchs puis cards » / « Cards puis batchs » (chrono en 2nd
  ordre) ajoutées au tri, validées. Défaut reste chronologique pur.

## 19. Audit de conformité POST-Transcriber (⏳ à déclencher après le chantier) — demandé 2026-06-29
Doc complet : `memory/project_post_transcriber_conformity_audit.md`. **But : 100 % commun sauf
spécificités d'app**, et préparer « génération d'app par manifeste ». À faire **quand le Transcriber
est fini** (P2 éventail, manipulation in/out, esthétique 2 états, nav clavier restants). Périmètre :
- ⏳ Conformité conventions par app + **MAJ table §15** ; MAJ conventions avec les décisions de session
  (staging supprimé, card mère, focusCard, entrée universelle, local-first…) ; chasse aux conventions
  obsolètes/contradictoires.
- ⏳ **Homogénéité du formalisme** (card/file/inspecteur/modes) + **compatibilité inter-apps**.
- ⏳ **Logique de nommage des fonctions** (vues/handlers JS/helpers/URLs/ids) → convention de nommage +
  normalisation des divergences (`start`/`launch`/`commit`, `batch_*`, `*_all`…).
- ⏳ **Restes de pansements** (recompute manuels, duplications) → centraliser.
- ⏳ **Récap common vs à-globaliser** (inventaire complet) → feuille de route vers 100 % commun
  (`COMMON_REFACTORING.md` + `GENERALIZATION_PLAN.md`) + **préparation manifeste** (axes restants, code
  app-spécifique irréductible = `process()` + pages d'édition).
- Méthode : passes read-only volumineuses délégables à **wama-dev-ai**, validées par Claude.

## 20. Consolidation des mécanismes de génération d'UI (⏳ TÂCHE 1 avant tout travail UI par app) — 2026-07-01
Spec précise : `memory/project_ui_mechanisms_consolidation.md`. **Le registre de modèles est UNIQUE**
(`ModelRegistry` + `ModelInfo` + `capabilities`) — MAIS plusieurs **chemins concurrents de génération
d'UI** coexistent : modale `WamaParams.render(item)` [transcriber/converter/reader/describer] vs
hand-built [synthesizer/avatarizer/composer] ; volet `WamaParams.render(panel)` vs `initFromSchema` ;
capacités→UI `WamaModelCaps` (synthesizer) vs rien (transcriber) vs `show_if` **hardcodé** (anti-pattern
enhancer). Avant d'uniformiser d'autres apps → **inventorier** (`UI_MECHANISMS_CONSOLIDATION.md` à créer :
tableau mécanisme|apps|**référence**|à **déprécier** par axe) + **plan de convergence**. Référence =
Transcriber. Contraintes : route existante, **zéro réinvention, zéro hardcoding**. Idéalement en **session
neuve** (contexte chargé = erreurs). Recoupe et précise §19.
- ✅ **Enhancer uniformisé (2026-07-01)** : onglets domaine `WamaModes` + bouton de cycle sur les 2
  domaines + inspecteur `initFromSchema` par domaine + **modales portées sur `WamaParams` (context:'item')**
  + aide modèle courte/longue + **couche capacités pièce 1/3** (moteurs audio resemble/deepfilternet au
  catalogue avec `capabilities.params`). **Reste enhancer** : pièce 2 (WamaModelCaps niveau-**champ**) +
  pièce 3 (câblage capacités→visibilité + **retrait du `show_if` hardcodé**).

## Bugs / dettes connus

> Repris de ROADMAP §0 (2026-07-20, contrat des niveaux — à revalider) :
-  **Qwen3-ASR** (Transcriber) — Backend implémenté (`qwen_asr_backend.py`) mais non fonctionnel — erreurs de dépendances à l'import — 🐛 Bloqué — Résoudre conflits deps pip (transformers, torchaudio, accelerate) 
- 🐞 Higgs Audio V2 : ~5 s d'audio dégradé malgré tous les patches — non résolu.
- 🔧 Patches venv → toujours via `patches/apply_patches.py`.
- 🌐 Headroom code-aware : `Mode: token` actuel → activer via terminal neuf + vérifier `headroom_stats`.
- 🩹 **`show_if engine=resemble` hardcodé** (enhancer audio, `params.py`) = anti-pattern à remplacer par
  capacités-driven (WamaModelCaps) — pièce 3 de la couche capacités (§20). Cf. `feedback_ui_from_model_capabilities`.

## Ordre de reprise recommandé
1. **Consolidation des mécanismes de génération d'UI (§20)** — inventaire + plan de convergence AVANT tout
   travail UI par app (sinon on aggrave la divergence). Idéalement session neuve. → puis uniformisation
   des 10 apps → manifests → chaîne de génération (`project_manifest_generation_priority`).
2. Model Manager volet droit (débloque le test prospection — ROI immédiat).
3. Cam Analyzer Phase 3 (calibration + vitesses).
4. Fondation RAG (`wama/rag/`) — débloque hook PromptPipeline + Media Library.
5. Refactoring common app par app (par petites sessions).

---

## 20bis. Portage schéma-driven — KICKOFF (état 2026-07-05, MAJ empirique 2026-07-06)

**3 apps AU MÊME NIVEAU : Transcriber · Composer · Describer** — elles partagent : tri/filtre +
toolbar commune (`queue_view.py` + `_queue_toolbar`), badge d'onglet, mosaïque/solitaire
(contrat `.wama-card`/`.is-batch`), card d'entrée `_new_item_card` en tête d'onglet (ordre
canonique card → progression → toolbar → file), modale générée + pied commun, **card = partial
serveur unique + endpoint `card_html` + `refreshCard`** (⚠ re-bind si events par card — leçon
describer), ETA commune (eta_estimator + WamaEta), batch import unifié (balises/en-têtes
multi-délimiteurs/positionnel + template généré), catégories d'apps + couleurs d'identité
dérivées (menu/accueil//apps/ générés du catalogue).

**Restent à porter (7)** — ordre recommandé :
1. **Reader** (jumeau de describer, + retirer son tri batch-first app-spécifique) ;
2. **Converter** (sa card `_job_card.html` est déjà LA référence → surtout file/toolbar/entrée) ;
3. **Enhancer**, **Anonymizer** (généralistes classiques) ;
4. **Synthesizer** (PRÉREQUIS : séparer le volet droit = surface de composition ; son accordéon
   est déjà globalisé en `collapsible`, sa `_synthesis_card.html` existe) ;
5. **Imager** (le + de modes — app de référence du build complet, à faire en dernier des
   généralistes) ; **Avatarizer** (standalone-only après studio, cf. R16).

**Briques inter-apps à créer au fil des ports** : `_batch_card.html` (card mère commune — les
headers transcriber/composer sont chacun faux à leur façon ; describer a déjà adopté le squelette
`.is-batch`) ; `batch_common.py` (`_wrap_*_in_batch`/auto-wrap ×3 apps) ; `build_batches_list()`
commun ; toast commun ; maps badge/couleur ; helper modale-batch ; `restart_instance()`.

**Validations navigateur EN ATTENTE (à faire en début de session)** : Composer (ETA cards,
batch 3 syntaxes + aperçu, template téléchargeable, card dépliable) ; Transcriber (cards ×2
contextes, contrat de sortie sur brouillons, échec → card re-rendue) ; Describer (upload/URL
depuis la card d'entrée, solitaire batch, **boutons actifs après re-rendu** = re-bind) ; menu +
accueil + /apps/ groupés + couleurs + liseré. Migration `describer 0008` appliquée (la page
était cassée avant — colonne manquante).

---

### AUDIT EMPIRIQUE 2026-07-06 (3 agents + contre-vérifications) — restes pour 100 %

| App | Score | Restes bloquants |
|---|---|---|
| **Transcriber** | ~90 % | ① start/start_all/batch_start SANS anti-race `select_for_update` (pattern CLAUDE.md — vérifié : 0 occurrence ; **describer seul l'a**, views.py:519) ; ② `stop()` sans `@require_POST` ; ③ bouton cycle inline `_transcript_card.html:87-91` au lieu de `_cycle_button.html` ; ④ card mère batch hand-made (A2-6) ; ⑤ sync card↔inspecteur manuelle 9 data-* + `_renderBatchActions` en chaînes JS (A3-12/13, vérifié index.js:1139) ; ⑥ `showToast`=alert (A6-26, vérifié index.js:104) ; ⑦ dropdown formats dupliqué partial+JS (A2-7 résiduel) ; ⑧ extractions de vue A5 : `_describe_audio`→media_probe, `_wrap_transcript_in_batch`/`_auto_wrap_orphans`→batch_common, agrégats→`build_batches_list`, prefs cache artisanales, SRT ×3, `clear_all` `.delete()` direct sans `safe_delete_file` ; ⑨ styles modales info/résultat (A4-15/16) |
| **Describer** | ~90 % | ① classe `.synthesis-card` (11× JS + 3× HTML) au lieu du contrat `.wama-card` ; ② **`wama-app-base.js` NON chargé** (seul des 3 — polling/CSRF locaux) ; ③ manipulation directe partielle : `consolidate` seul (pas de reorder/move_to_batch/remove_from_batch) ; ④ réglages user non persistés. Le reste est au niveau (card_html+refreshCard avec re-bind, anti-race, ETA seedée, exports late TXT/PDF/DOCX, toolbar) |
| **Composer** | ~75 % | ① manipulation directe ABSENTE (0/4 endpoints, brique `consolidate_into_batch` non consommée) ; ② anti-race absent ; ③ descriptions modèles hardcodées `COMPOSER_MODELS` (model_config.py:34-101) au lieu du catalogue `AIModel` (points 9/10 checklist) ; ④ card mère batch = bandeau violet minimal sans ▶/compteurs/barre agrégée (B3-8) ; ⑤ styles inline `_generation_card.html` (B2-7) ; ⑥ 2 impls modale-batch à fusionner (A6-28) ; ⑦ réglages user via localStorage seul |

**Transverses (débloquent les 3 à la fois — à créer PENDANT le port de Reader)** :
`_batch_card.html` commune (toujours absente — vérifié) · wrappers `_wrap_*_in_batch`/
`_auto_wrap_orphans` → `batch_common.py` (existe déjà : `consolidate_into_batch`,
`group_into_batches_by_nature`) · `build_batches_list()` · `WamaApp.toast` (rien dans
wama-app-base.js — vérifié) · maps badge/couleur · `restart_instance()` anti-race ·
helper modale-batch · partial `_download_formats_dropdown.html`.

**Corrections de doc actées 2026-07-06** : le point 16 de la checklist (`tool_api.py`) se vérifie
dans le REGISTRE CENTRAL `wama/tool_api.py` (TOOL_REGISTRY — transcriber/composer/describer y sont
tous trois), PAS par fichier d'app ; backups `{% comment %}` transcriber purgés (A4-14 clos) ;
`wama-app-base.js` adopté par composer et reader (B4-10 partiellement résorbé — URLs en dur à
re-vérifier au prochain passage).

**PROCHAINE APP : READER** (décision 2026-07-06, confirme l'ordre du 07-05 ; remplace le
« prochaine bascule = enhancer » périmé de GENERALIZATION_PLAN) — jumeau de describer, charge déjà
`wama-app-base.js`, recette éprouvée 3× → port le moins cher ; créer les briques transverses
ci-dessus pendant ce port (4 consommateurs immédiats).

---

### PORT À 100 % EFFECTUÉ — session 2026-07-06 soir (Fabien : « terminer les 3 apps, puis Reader »)

**Briques CRÉÉES (common/)** : `utils/media_probe.py` (sonde ffprobe + format_duration) ·
`utils/user_settings.py` (réglages user par app, clés `user_{id}_{app}_{clé}`, TTL 30 j) ·
`utils/queue_manipulation.py` (FABRIQUE des 4 vues manipulation directe) ·
`templates/common/_batch_card.html` (card MÈRE de batch, slots meta/download_menu/download_url/
eta_ids/show_start, boutons canoniques `.batch-*-btn`) · dans `batch_common.py` :
`wrap_in_batch`/`auto_wrap_orphans`/`build_batches_list` · dans `process_control.py` :
`begin_processing` (anti-race CLAUDE.md) · dans `wama-app-base.js` : `WamaApp.toast` +
`STATUS_BADGE/LABEL` (monté GLOBAL dans base.html) · `_cycle_button.html` : overrides
`restart_title`/`restart_icon` + `data-cycle-restart-*` lus par wama-cycle-button.js.

**Consommation** — Transcriber : anti-race ×3 + reset unifié, stop POST, cycle→brique (spécificité
temps réel déclarée sur la card), toast (11 alert() purgés), clear_all sûr, media_probe,
user_settings (2 routes mortes supprimées, défaut préprocessing unifié OFF), batch_template brique,
manipulation directe DÉLÉGUÉE à la fabrique, card mère → brique (+ slots `_batch_meta.html`,
`_batch_download_menu.html`). Describer : `.wama-card` (JS ×11), manipulation directe 3 vues
câblées (consolidate par nature conservé), réglages persistés (`_read_creation_options`, 4 lectures
POST unifiées), card mère → brique (**gagne ▶ batch** + handler JS), agrégats → brique, toast.
Composer : anti-race ×4, wrappers+agrégats → brique, manipulation directe 4/4 câblée (routes),
card mère → brique (**gagne ▶ batch + compteurs + barre agrégée** ; id collapse aligné
`batchItems<id>`), styles inline → index.css, toast → brique, `batchStartUrlTemplate` posé.
Vérifié AU PASSAGE : descriptions modèles composer = déjà catalogue (wama-model-help →
`/model-manager/api/models/db/`) — le ⚠ points 9/10 de l'audit matin était trop sévère ;
`COMPOSER_MODELS` résiduel = facteurs slider (légitime §D, cible eta_estimator).

**Validations faites** : `manage.py check` OK (WSL venv) · imports views/urls ×3 OK ·
10 templates compilés OK · équilibre délimiteurs JS ×5 OK · staticfiles copiés (6 fichiers).
**⚠ RESTE À VALIDER NAVIGATEUR** (je ne peux pas) : cards mères ×3 (rendu + dépliage + ▶/ZIP/⧉/🗑),
bouton cycle transcriber (états ▶/⏹/↻ + temps réel ↻ fa-rotate), toasts, manipulation directe.
**Restes consignés (non bloquants checklist)** : A3-12/13 (chaînes JS inspecteur → TÂCHE 1),
A4-15/16 (styles modales transcriber), A5-24 (SRT ×3), A6-28 (fusion modale-batch JS),
A1-4 (afterCreate batch-import), B4-10 résiduel (URLs composer), B4-13 (ETA client→serveur),
B5-20 (export médiathèque). Restart process WSL2 requis pour le Python.

**AUDIT ROUTE COMMUNE (même jour, après commit du port)** →
**[`AUDIT_ROUTE_COMMUNE_2026-07-06.md`](AUDIT_ROUTE_COMMUNE_2026-07-06.md)** : (1) common SAIN,
1 doublon critique ffmpeg/ffprobe **corrigé** (video_utils + waveform + converter probe → délèguent
à ffmpeg_utils, la sélection WSL2-vs-Windows redevient unique) ; describer basculé sur
`begin_processing` (son inline promu brique) ; (2) les 7 généralistes : wrappers batch locaux ×7,
0 manipulation directe, anti-race inline reader/converter seulement + features à remonter (profils
converter, TTS synthesizer, A/B enhancer, presets anonymizer, seeds/galerie imager) ; (3) route
manifeste→app ~70-80 % déclarative, chantiers ordonnés (ports → contrat URLs → enum statuts →
check_app_conformity exécutable → introspection Django→schéma → scaffold EN DERNIER).

---

## 21. Inspecteur contextuel + état des 4 apps portées (2026-07-08) — CLÔTURE DE SESSION

> Session dédiée à l'**inspecteur contextuel** (mode avancé) + audit des 4 apps portées.
> Reprise = **porter Converter** puis **combler les trous** listés ci-dessous. Ordre fixé Fabien :
> **inspecteur d'abord, amincir les cards ENSUITE** (l'inspecteur porte le détail → justifie de
> maigrir les cards). Docs de référence figés : [`INSPECTOR_DETAIL_FIELDS.md`](INSPECTOR_DETAIL_FIELDS.md),
> [`COMMON_REFACTORING.md`](COMMON_REFACTORING.md) (registre briques + **discipline anti-réinvention**),
> `CARD_DESIGN §10` (card v2), mémoire `project_inspector_contextual_vision.md`.

### 21.1 Ce qui a été construit (commun, porté aux 4 apps)

- **Aperçu inline** dans le volet (`WamaInspector` → `#preview-container`) : image / vidéo / audio
  (WamaAudioPlayer) / PDF / **HTML (iframe sandboxée)** / **texte (contenu inline)** — tout sauf zip.
  Source = `unified_preview` + `preview_registry`. **Autoplay = préférence profil** (`UserProfile.
  inspector_autoplay`, défaut OFF, toggle page profil, global `WAMA_INSPECTOR_AUTOPLAY`). Jamais de
  génération : on affiche l'existant. Section « Médias » **masquée hors ITEM**.
- **Section Infos = CHIPS** (pas la liste KV de WamaDetails, écartée) : identité (#id + badge statut +
  date + ✕ désélection) + fichier source + chips étiquetées (durée, moteur, format, propriétés à
  **icône adaptative** par type, réglages `extra` tirés de `params.py`). Source = **`unified_detail`
  + `detail_registry` + `build_detail`** (schéma canonique figé `INSPECTOR_DETAIL_FIELDS.md`). Statut
  normalisé à l'affichage (DONE→SUCCESS).
- **Agrégats file / batch** dans l'inspecteur, **LUS des sources serveur** (pas de recompte client) :
  file ← `window.WamaQueueStats` (posé par `wama-global-progress.js`, refresh live sur
  `media:processed`) ; batch ← `data-batch-*` de `_batch_card.html` (depuis `build_batches_list`).
- **Temps de traitement réel persisté** : `common/models.py::ProcessingTimeMixin` (les 4 modèles
  héritent), workers persistent `processing_seconds` (déjà mesuré pour l'ETA), affiché via
  `_processing_time.html` (foyer unique, inclus par `_card_progress`).
- **Card v2 synthétique** (chips depuis `params.py chip=True`, point d'état tricolore, barre pleine
  largeur) : **PILOTE Reader uniquement**.

### 21.2 Table de conformité (✅ / 🔶 / ❌)

| Axe | Transcriber | Describer | Composer | Reader |
|---|---|---|---|---|
| Preview (registry + data-preview-url) | ✅ | ✅ | ✅ | ✅ |
| Detail (registry + adapter build_detail) | ✅ | ✅ | ✅ | ✅ |
| cardSelector spécifique | ✅ `.synthesis-card` | 🔶 `.wama-card` (trop générique) | ✅ `.generation-card` | ✅ `.reader-card` |
| Inspecteur `initFromSchema` | 🔶 `.init()` (legacy) | ✅ | ✅ | ✅ |
| `cloneActions` | ✅ | ✅ | ✅ | ✅ |
| Card v2 (chips) | ❌ | ❌ | ❌ | ✅ (pilote) |
| `_batch_card.html` commun | ✅ | ✅ | ✅ | ✅ |
| Briques communes (batch/process/queue/user_settings) | ✅ | ✅ | ✅ | ✅ |
| `ProcessingTimeMixin` + persistance | ✅ | ✅ | ✅ | ✅ |
| Affichage temps | ✅ `_card_progress` | ✅ `_processing_time` | ✅ `_processing_time` | ✅ `_processing_time` |
| Statuts SUCCESS/FAILURE | ✅ | ✅ | ✅ | 🔶 DONE/ERROR (normalisé à l'affichage) |
| Page d'édition dédiée (spécifique légitime) | ✅ correction manuelle | — | — | — |

### 21.3 Trous de portage à combler (reprise) — priorisés

1. ✅ 2026-07-08 **Describer `cardSelector`** — vérifié empiriquement DÉJÀ à `.synthesis-card`
   (`describer/index.html:315`) ; l'entrée était en retard sur le code. Le `.wama-card` restant
   (`index.js:20`) est le `autoSync` du cycle-button, sans effet de bord (header batch sans bouton).
2. ✅ 2026-07-08 **Reader statuts alignés en BASE** : `DONE/ERROR` → `SUCCESS/FAILURE`
   (migration `reader.0008` choices + data, sweep models/views/tasks/JS/template — les clés JSON
   `done/error` de `global_progress` inchangées, brique commune tolérante). Converter garde
   DONE/ERROR (normalisé affichage) — à aligner à son tour si souhaité.
3. ✅ 2026-07-08 **Transcriber migré `initFromSchema`** : `_panelApplyValues`/`_cardSettings`
   supprimés (dérivés du schéma) ; `_panelReadValues` CONSERVÉ (payloads serveur typés).
   Prérequis posés : `window.WAMA_TRANSCRIBER_SCHEMA` (template), support **`radio_name`** ajouté
   aux read/apply dérivés de `wama-inspector.js` (radios legacy ex. `globalSummaryType`), `data-*`
   des cards alignés sur les noms du schéma (`data-preprocess-audio`, `data-enable-diarization`).
4. 🟠 **Transcriber `_card_progress.html`** vs `_processing_time.html` custom des 3 autres → une seule
   approche d'affichage de progression/temps. (À traiter AVEC le rollout card v2, point 5.)
5. 🟡 **Propager la card v2 (chips)** aux 3 autres apps : `chip=True` sur leurs params + `.chips`
   property (modèle reader) + include `_card_chips.html`. (Après validation navigateur du pilote.)
6. ✅ 2026-07-08 **Mini-card « Réglages de l'élément #N » RETIRÉE** des 5 apps portées au détail
   (transcriber/describer/composer/reader/converter) ; le ✕ des Infos appelle `deselect` en direct
   (plus de proxy par le bouton du bandeau). `_inspector_banner.html` reste pour les non-portées
   (synthesizer, avatarizer).
7. ✅ 2026-07-09 **`probe_media`** généralisé (`media_probe.py` : image/vidéo/audio/PDF/archive)
   + **fallback UNIVERSEL dans `build_detail`** (`probe_media_cached`, cache par chemin+mtime) →
   `source_properties`/durée/icône remplis partout sans travail par app. Testé sur fichiers réels
   + `unified_detail` converter (vidéo : `mjpeg • 384×288 • 15.0 img/s`, durée 0:27).

### 21.4 Au-delà — état 2026-07-08

- ✅ **CONVERTER PORTÉ (5e app)** : adapters preview+detail (`apps.py`, extra ← labels `params.py`,
  `output_quality`←`quality_preset`), `ProcessingTimeMixin` + persistance worker + affichage
  (`_processing_time.html` + live via `status` JSON), `data-preview-url` racine card,
  `initFromSchema` (schéma modale ; volet = zone de composition, aucun param contexte 'panel' →
  synchro dérivée neutre), `cloneActions` item+batch, **card mère commune `_batch_card.html`**
  (contrat calculé dans la vue — FK directe, pas de modèle de liaison ; `data-media-type` sur le
  wrapper `.batch-group`, conteneur `#batchItems<id>` + `data-wama-batch-key`). Smoke réel : page
  200 + endpoints unifiés OK (données de test nettoyées).
- ⚠️ **Migrations en retard découvertes et appliquées** (2026-07-08) : `describer.0009` /
  `composer.0005` / `reader.0007` (`processing_seconds`) n'avaient JAMAIS été appliquées à la base
  partagée → `manage.py migrate` global fait (incl. accounts.0009, model_manager.0008,
  cam_analyzer.0013). Toujours vérifier `migrate` après un palier.
- **5 apps non portées** : enhancer, anonymizer, synthesizer, imager, avatarizer. Chacune : adapter
  `register_app_preview` + `register_app_detail` + câblage inspecteur.
- **Amincissement des cards** (le but du report d'infos vers l'inspecteur) : APRÈS l'inspecteur.
- Validation NAVIGATEUR par Fabien toujours attendue : pilote card v2 Reader + inspecteur des 5
  apps portées (smoke serveur fait, pas de clic réel).

## 21bis. Composer — ÉTAT RÉEL VÉRIFIÉ (2026-07-21) : structure ≠ comportement

> Vérifié en profondeur (lecture code + 3 explorations croisées) sur signalement Fabien que le
> « 96 %/audit » surestime. **Cause de l'écart** : `get_conformity_summary` et l'audit UI mesurent
> la STRUCTURE (« appelle-t-il `WamaParams.render` ? une preview est-elle enregistrée ? »), PAS le
> COMPORTEMENT (« la sauvegarde persiste-t-elle ? les actions apparaissent-elles ? »). D'où une app
> structurellement ~90 % mais fonctionnellement cassée sur la modale. **→ ajouter une dimension
> conformité COMPORTEMENTALE (smoke) est recommandé.**
>
> **AVANCEMENT 2026-07-21** (validé navigateur Fabien au fil de l'eau) : ✅ **pt1** ordre de rendu
> (sauvegarde modale débloquée) · ✅ **pt5** brique `coerce_params` + câblage · ✅ **bug affichage**
> (card re-rendue après save → modale+inspecteur affichent les valeurs enregistrées, pas les défauts ;
> `insertRenderedCard` après chaque save) · ✅ **pt3** actions héritées par le volet
> (`renderItemActions`/`renderBatchActions` + `.btn-group-actions` sur la card ; clics fonctionnels,
> lien médiathèque inclus) · ✅ **pt6** `hideOnInspect` (saveGlobal/titres = N/A composer). **Reste** :
> ✅ **pt2 FINALISÉ 2026-07-21** : sauvegarde modale = **100% `WamaParams.read`** (aucun hand-read).
> **Chaîne output_format/output_quality VÉRIFIÉE end-to-end, saine, zéro hardcoding** (trace Fabien) :
> options ← `output_format_params_for_app` → `get_output_formats` → **`CONVERTER_OUTPUT_FORMATS`**
> (source unique converter) ; presets qualité = `OUTPUT_QUALITY_CHOICES` (web/équilibré/max) ; ces 2
> Param SONT dans le schéma composer (confirmé live : `['model','duration','prompt','output_format',
> 'output_quality']`) → `read` les capte ; application réelle = `composer/tasks.py` appelle
> `apply_inline_conversion` (converter). **Apps branchées early-binding : composer + synthesizer** ;
> late-binding = conversion au download (`multi_format_download`). (Ma gestion explicite initiale
> était redondante/fausse → corrigée.)
> **pt4 preview = CHANTIER PREVIEW COMMUN (tunnel : moi=briques preview, autre instance=manifeste+
> ingest ; on se rejoint sur les ports).** CONTRAT DE JONCTION : la preview lit les ports par
> **l'UNIQUE accesseur `studio_node_ports(app_id)`** (jamais app_modes/app_registry en direct) —
> `extract_app()` du manifeste utilise déjà le même → quand le manifeste devient autoritaire,
> `studio_node_ports` = sa projection, la preview hérite sans changer. Le « pendant » = **capacité
> déclarée** (`body.capabilities`, ex. `during_preview`/`streaming`) : moi le mécanisme, eux le flag.
> Cycle avant/pendant/après (comme ▶/⏹/↻). État :
> - ✅ **Chantier 1 (2026-07-21) — face ENTRÉE dérivée du port travail/prompt, jamais reference**
>   (`preview_utils._input_preview` via `studio_node_ports` ; prompt→texte inline `content`,
>   travail→adaptateur fichier ; frontend rend `content` inline). Corrige composer GÉNÉRIQUEMENT
>   (0 hardcode). Vérifié live : composer/synthesizer=prompt, transcriber/imager=travail ; endpoint
>   composer entrée=prompt(text/plain), sortie=audio, toggle OK.
> - ⏳ **Chantier 2 — phase PENDANT** : mécanisme commun de preview en cours de traitement (sortie
>   temporaire/partielle), socle du streaming « à la Suno », lit la capacité `during_preview`/`streaming`.
> - ⏳ **Chantier 3 — unifier le filemanager** sur `media-preview.js` commun (il a sa propre modale).
> **Streaming preview « à la Suno »** (sortie audio construite pendant le process) = faisable
> (MusicGen autorégressif + callback), à faire en **capacité commune déclarée par métadonnée**, APRÈS
> pt4 de base — pas en dur dans composer. **Reste** : pt4 (preview entrée/sortie — **design corrigé
> Fabien** : entrée = **le PROMPT utilisateur** = entrée principale ; la mélodie de réf = fichier de
> référence secondaire, PAS l'entrée ; sortie = audio généré ; adaptateur `apps.py` à corriger, il
> pointe 2× sur `audio_output`), pt7 (includes card `_card_state`/`_card_progress`),
> pt8 (ETA `data-*`→catalogue), pt9 (bouton médiathèque = action commune par capacité de sortie).
>
> **Route commune = existante et unique** (ne rien réinventer) : `WamaParams` (render+read/apply,
> modale+volet+batch), `WamaInspector.initFromSchema({renderItemActions,renderBatchActions,...})`,
> preview `unified_preview`/`preview_utils.py` (`?side=output` + toggle [Entrée|Sortie], décision
> 2026-07-12). **Transcriber = référence conforme ; Composer demi-porté.**
>
> **Reste à porter (vérifié, ordonné) :**
> 1. **Bug bloquant modale = ORDRE DE RENDU.** `index.js` (IIFE nue, sans DOMContentLoaded) est
>    chargé `composer/index.html:242` AVANT le bloc `WamaParams.render` (index.html:276-322) qui
>    crée `modelSelect`/`durationSlider`/`settingsModel`/`settingsDuration` → consts nulles
>    (index.js:43/44/103/106) → `_postSettings` (index.js:380/381/394/395) lève TypeError au clic
>    « Enregistrer »/« Enregistrer et relancer ». **Fix = pattern Transcriber : rendre WamaParams
>    AVANT `<script index.js>`** (transcriber index.html:107-129 avant 131). Le volet (`postPanel`,
>    getElementById au POST) marche déjà → d'où DEUX chemins concurrents (volet OK / modale cassée).
> 2. **Supprimer le 2ᵉ chemin** : `_postSettings` → lire via `WamaParams.read` (ou getElementById
>    au POST) comme le volet.
> 3. **Actions héritées par le volet** : passer `renderItemActions`/`renderBatchActions` à
>    `initFromSchema` (absents index.html:263-273 ; présents transcriber index.js:1175-1176) **ET**
>    donner à la card le conteneur clonable `.btn-group-actions` (elle a `.d-flex flex-wrap gap-1`,
>    `_generation_card.html:80` ; `cloneActions` clone `.btn-group-actions`, wama-inspector.js:44).
> 4. **Preview Entrée/Sortie** : aujourd'hui input ET output pointent sur `audio_output`
>    (apps.py:30 & 44) → le toggle montrerait 2× le même fichier. Input = mélodie de référence si
>    présente (sinon pas de side entrée) ; le prompt reste l'« entrée » textuelle.
> 5. **Borne de durée = DUPLICATION 7× (dette architecturale, PAS un petit réglage — corrigé
>    2026-07-21).** La borne 10-600 s est copiée à la main dans : champ modèle (help_text seul, AUCUN
>    validateur `models.py:27`), `params.py` (slider min/max), et **5 clamps `max(10,min(600))`**
>    (views.py ×4 + batch_parser) ; elle a déjà dérivé (migrations : max30→10-300→10-600) et
>    contredit `max_duration:30` (model_config). **Source unique = le mécanisme commun
>    `derive_from_model` (`common/utils/param_schema.py`)** — dériver le schéma DU modèle Django,
>    déjà adopté par anonymizer/avatarizer/describer/imager ; **Composer ne l'utilise pas**.
>    Cible : borne définie 1× (validateurs sur le champ modèle → Django valide serveur + derive lit),
>    clamps serveur LISENT le schéma (petit helper commun), effective_max = min(borne, model.max_duration).
>    ✅ **FAIT 2026-07-21** : trou confirmé SYSTÉMIQUE (audit : ~28 clamps hardcodés sur 8 apps,
>    même celles qui dérivent ; aucune brique n'existait). Créé `common/utils/param_schema.py::
>    coerce_params(schema, data, caps=)` = borne LUE du schéma (source unique) + cap runtime optionnel.
>    Composer = 1er consommateur : helper `clamp_duration` + 5 clamps remplacés + cap `max_duration`
>    au lancement de tâche (auto-* résolu). Validé live (305→305, 999→600, 999+musicgen→30). **Reste** :
>    (a) valider navigateur (305s demandé → 30s généré = cap modèle ; si trop bas, `max_duration` de
>    model_config = désormais LA source à corriger 1×) ; (b) généraliser aux ~23 autres sites ;
>    (c) plus tard, porter la borne dans le modèle Django (validateurs → derive_from_model les lit),
>    décidé avec Fabien : « on aligne sur l'existant, puis modèle Django par la suite ».
> 6. **Compléter `initFromSchema`** : `saveGlobal`, `hideOnInspect`, `settingsTitleSelector/Inspect`.
> 7. **(Card, optionnel)** remplacer badge statut + barre écrits à la main (`_generation_card.html:
>    51-65`) par includes communs `_card_state.html`/`_card_progress.html` (que transcriber inclut) ;
>    card v2 chips (`chip=True`) = pilote **reader** (pas transcriber), différée.
> 8. **ETA** encore en `data-*` inline (blocage identifié UI_MECHANISMS_CONSOLIDATION) → catalogue.
> 9. **Bouton « ajouter médiathèque »** = spécifique composer → à généraliser en action commune
>    pilotée par capacité de sortie (APP_CATALOG déclare les output types).
>
> **Doc autorité uniformisation = `UI_MECHANISMS_CONSOLIDATION.md` (~2026-07-11) MAIS via ses notes
> §9 seulement** (tableaux du haut périmés + auto-contradictoires : « params.py 8/10 »→10/10 ;
> « transcriber `.init` »→`initFromSchema`). `COMMON_REFACTORING.md` (2026-06-24) = catalogue de
> briques + contrat backend, mais roadmap « À faire » périmée + registre dérivé (`model_capabilities.py`
> non listé). **Aucun des deux ne capture les bugs de comportement** → à rafraîchir + dimension smoke.
>
> **Boucle de refresh** (signalée Fabien) = design client préexistant, PAS lié à login/modération/
> email (backend fail-safe, 0 middleware, 0 JS touché) : `wama-global-progress.js` poll 1500 ms sans
> arrêt + `.active` ré-appliqué à chaque tick + émission `media:processed` dès `done` croît →
> `filemanager tree.refresh()` en cascade. Rendue visible par les 502 récents (restart Apache→Django).

## 22. Skills de prompt par application (2026-07-08) — FAIT, validé Fabien

> Doc de référence : **`PROMPT_PIPELINE.md` §Skills** + `wama/common/prompt_skills/README.md`.
> Mémoire : `project_prompt_skills.md`.

- ✅ Brique `common/utils/prompt_skills.py` (résolution `<app>-<domain>` → `<app>` →
  `default-<kind>`, importable SANS Django) + fichiers `common/prompt_skills/` (imager-image,
  imager-video, composer-music, default-generative).
- ✅ Pipeline : `PROMPT_TARGETS` gagne `domain`/`domain_field` (imager `output_type`) ;
  hook A passe le skill au LLM. Composer `enrich=True` (blocage « consignes visuelles » levé).
- ✅ À la demande : `enrich_on_demand()` (pas gaté par WAMA_PROMPT_ENRICH, émission dans la
  langue de l'utilisateur) ; endpoint imager ✨ branché dessus ; `imager/utils/prompt_enhancer.py`
  (consignes dupliquées) SUPPRIMÉ.
- ✅ Trou comblé : `generate_video_task` imager n'appelait pas la pipeline (locals, base=original).
- ✅ Agents : assistant couvert by design (tools→tâches Celery→pipeline) ; wama-dev-ai importe le
  même module (`PROMPT_SKILLS_DIR` en config + README).
- Testé bout en bout : résolution ✓, Ollama réel (imager-image, émission FR, sujet préservé) ✓,
  passthrough pipeline (interrupteur OFF) ✓, imports ✓.
- ✅ 2026-07-09 **Endpoint commun `/common/api/enrich-prompt/`** (`{prompt, app, domain}`,
  `mode` accepté en alias) — prêt pour le STUDIO (nœud-app : app connue par construction, domain
  passé explicitement car pas d'instance avant exécution) et tout bouton ✨. Imager débranché de
  sa route spécifique (`imager:enhance_prompt` + vue supprimées, JS/template → endpoint commun).
  Invariant studio : l'EXÉCUTION des nœuds doit passer par « instance + tâche Celery » → skills
  hérités by design, aucun câblage par card.
- ⏳ Suites possibles : skills pour anonymizer (kind concept ?), enhancer ; UI pour éditer les
  skills (niveau labo/utilisateur → jonction RAG).

## 23. Audit + nettoyage documentation racine (2026-07-09)

> **MAJ 2026-07-20 — dédoublonnage ROADMAP↔PROJECT_STATUS en cours d'exécution** (recommandation
> 23.2 ; méthode : micro-lectures + vérif code systématique + scripts gardés + archive
> `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`, rien n'est perdu). **Fait** : §0→PROJECT_STATUS,
> §1, §2, §3, §4, §6 (cases mises à jour), §8d-P1, §9.1+tables 9.2, §15 (requalifiée LIVRÉE=Studio).
> Divergences corrigées au passage : import récursif FAIT côté FileManager ;
> UI_MECHANISMS_CONSOLIDATION.md existe (⏳ « produire » périmé) ; params.py/WamaParams livrés ;
> Pexels/Openverse livrés ; canvas studio vanilla JS+SVG (pas de lib node-graph).
> **Reste à trier** (vérif code par item, petites passes) : §5+5b Model Manager (~180 l),
> §7 Converter (~160 l), §8/8b/8c, §9 reste (9.2ter→9.5), §10 i18n (~120 l), §16 (keeper à
> rafraîchir). §11 relu ce jour = au bon niveau ; §12/§13/§14 = keepers selon l'audit 07-09
> (simple survol de fraîcheur à faire en fin de chantier).

> Demandé par Fabien : « la jungle des .md ». 26 fichiers `.md` à la racine, audit exhaustif via
> 8 agents en parallèle (lecture intégrale + vérification empirique de 2-4 affirmations par
> fichier contre le code réel), synthèse + corrections ci-dessous. **Graphe de référencement**
> (`grep` croisé des 26 basenames) : **8 fichiers ne sont référencés par AUCUN autre doc racine**
> (orphelins) — signal fort de contenu absorbé ailleurs ou jamais raccroché au réseau vivant :
> `AUDIT_GLOBALISATION_T+C_2026-07-03.md`, `BATCH_MODEL_AUDIT.md`, `INFRA_WSL_VS_WINDOWS.md`,
> `INPUT_MODEL_MATCHING.md`, `MEDIA_STORAGE_TIERING.md`, `MODAL_ACTIONS_AUDIT.md`,
> `MODEL_META_UNIFICATION_KICKOFF.md`, `NEXT_SESSION_KICKOFF.md`.

### 23.1 Verdict par fichier

| Fichier | Lignes | Nature | Verdict |
|---|---|---|---|
| ~~AUDIT_GLOBALISATION_T+C_2026-07-03.md~~ | 221 | audit ponctuel clos | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09, `git mv`, historique préservé) |
| AUDIT_ROUTE_COMMUNE_2026-07-06.md | 159 | audit ponctuel | 🔧 §2b reader périmé (a migré `begin_processing` le lendemain) → corriger puis archiver une fois §3 repris |
| BACKEND_CARTOGRAPHY.md | 110 | référence vivante | ✅ sain, à jour |
| BATCH_FORMAT.md | 149 | référence vivante | ✅ sain, à jour |
| ~~BATCH_MODEL_AUDIT.md~~ | 87 | audit ponctuel clos | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09) |
| CARD_CENTRIC_UI.md | 162 | décision d'archi (le « pourquoi ») | 🔧 §7 mentionne encore le staging (supprimé 2026-06-29) — à purger |
| CARD_DESIGN.md | 408 | **doc pivot**, le plus à jour | ✅ sain (léger résidu §8.5 déjà coché ci-dessous) |
| COMMON_REFACTORING.md | 132 | référence vivante, hub | ✅ sain, exemplaire |
| GENERALIZATION_PLAN.md | 60 | chapeau vivant | 🔧 curseur "prochaine app = Reader" dépassé (Reader porté depuis) |
| INFRA_WSL_VS_WINDOWS.md | 68 | référence active | ✅ sain (se périmera seul à la bascule full-Linux) |
| INPUT_MODEL_MATCHING.md | 72 | décision + plan | 🔧 étapes 1-4/6 déjà exécutées (`wama-input-match.js` existe), non cochées |
| INSPECTOR_DETAIL_FIELDS.md | 65 | référence vivante | ✅ sain |
| MEDIA_STORAGE_TIERING.md | 88 | décision d'archi (pas implémenté) | 🔧 §B périmé : `EMAIL_BACKEND` déjà configuré (2026-07-02) |
| MODAL_ACTIONS_AUDIT.md | 89 | audit + cible | 🔧 cible `_settings_modal_footer.html` existe et est adoptée par 5/11 apps — non mentionné |
| ~~MODEL_META_UNIFICATION_KICKOFF.md~~ | 192 | kickoff de session | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09 ; R10 confirmé fait dans REMOVAL_LEDGER.md, suivi résiduel = REMOVAL_LEDGER) |
| MODES_QUEUE_UX.md | 178 | boussole produit vivante | ✅ **corrigé ce jour** : P1 marqué fait (était en retard sur le code) |
| ~~NEXT_SESSION_KICKOFF.md~~ | 55 | brief de session | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09 ; livrable produit = `UI_MECHANISMS_CONSOLIDATION.md`) |
| PROFILES_PERMISSIONS.md | 166 | référence vivante | ✅ sain, vérifié |
| PROMPT_PIPELINE.md | 98 | référence vivante | ✅ **exemplaire** — le plus frais (skills du jour même) |
| README.md | 269 | point d'entrée | 🔧 table doc ne référence que 8/26 fichiers — désynchronisée |
| REMOVAL_LEDGER.md | 105 | registre actif | 🔧 table §1 désync de son propre journal (R1/R2 dits soldés, table dit encore ⛔) |
| ROADMAP.md | 1219 | **hétérogène** | 🔨 RESTRUCTURER — ~55-60% de doublon avec PROJECT_STATUS (voir 23.2) |
| STUDIO_VISION.md | 100 | vision (non stabilisée) | ✅ **corrigé ce jour** : route `/studio/` (était `/common/studio/`) |
| TRANSCRIBER_REFERENCE_AUDIT.md | 105 | checklist vivante | ✅ sain — ajouter un renvoi croisé vers UI_MECHANISMS_CONSOLIDATION §0 (nuance "référence") |
| UI_MECHANISMS_CONSOLIDATION.md | 412 | pilotage de chantier vivant | 🔧 §7/§9 contredisent son propre résumé exécutif (P0 params.py dit fait puis refait) |
| WAMA_APP_CONVENTIONS.md | 2398 | **référence normative** | 🔨 §15.1 (table conformité) périmée sur plusieurs lignes + double numérotation §15 + §5 dupliqué avec CARD_DESIGN |
| PROJECT_STATUS.md (ce fichier) | — | tableau de bord vivant | 🔧 **corrigé ce jour** : §9 Media Library disait Phases 2-4 ⏳, en fait faites |

### 23.2 Recouvrements identifiés (pas de vrai doublon strict trouvé)

- **CARD_CENTRIC_UI.md vs CARD_DESIGN.md** : PAS un doublon — l'un est la décision d'architecture
  (le « pourquoi », figé), l'autre le formalisme visuel vivant (mis à jour en continu). À
  **synchroniser** (fait ce jour pour le point staging), pas à fusionner.
- **ROADMAP.md vs PROJECT_STATUS.md** : le plus gros chevauchement du lot (~55-60 %). ROADMAP
  mélange vision long terme, décisions historiques ET détails d'implémentation déjà livrés
  (Media Library, Ollama, cam_analyzer §9.1/9.2 — tout 2026-04/05, 100% ✅). Les deux docs
  **divergent silencieusement** (ROADMAP avait raison sur Media Library, PROJECT_STATUS avait
  tort — corrigé ce jour ; l'inverse est possible ailleurs). **Recommandation non exécutée
  (chantier dédié à prévoir)** : restructurer ROADMAP pour ne garder que specs/décisions/backlog
  intemporels (§12/§13/§14/§15/§16), archiver les sections 100 % actées (§3/§4/§9.1-9.2/§8d
  Phase 1) au profit d'un renvoi vers PROJECT_STATUS.
- **WAMA_APP_CONVENTIONS.md §5 vs CARD_DESIGN.md** : redondance de contenu (structure de card,
  ordre des zones) — CARD_DESIGN.md est la référence la plus récente et se déclare déjà comme
  telle. **Recommandation non exécutée** : réduire §5 à un renvoi vers CARD_DESIGN.md.
- **AUDIT_GLOBALISATION_T+C_2026-07-03.md → AUDIT_ROUTE_COMMUNE_2026-07-06.md → COMMON_REFACTORING.md** :
  chaîne d'audits successifs sur le même chantier (port Transcriber/Composer/Describer), chacun
  prolongeant/absorbant le précédent. Le premier est mort, le second vivra jusqu'à ce que ses
  chantiers §3 soient repris ailleurs, le troisième est le hub stable.
- **NEXT_SESSION_KICKOFF.md → UI_MECHANISMS_CONSOLIDATION.md** : le premier commande le second
  comme livrable ; mission accomplie, le brief n'a plus de raison d'être consulté.

### 23.3 Corrections empiriques appliquées ce jour (factuel, périmé → à jour)

- `PROJECT_STATUS.md` §9 : Media Library Phases 2-4 étaient marquées ⏳, **vérifié faites**
  (`MediaProvider`/`UserProviderConfig` + 6 connecteurs + filtrage UI).
- `MODES_QUEUE_UX.md` : phase **P1 marquée ✅** (`app_modes.py` + `wama-modes.js` existent et sont
  câblés dans imager/composer/studio — le doc se croyait encore au stade projet).
- `STUDIO_VISION.md` : route corrigée `/common/studio/` → `/studio/` (l'app a été migrée en app
  Django dédiée, le doc n'avait pas suivi).

### 23.4 Reste à faire (backlog de nettoyage — non exécuté ce jour, décisions ouvertes)

**Petites corrections factuelles restantes** (chacune = quelques lignes, faisable en 10-15 min) :
1. `AUDIT_ROUTE_COMMUNE_2026-07-06.md` §2b : ligne reader (a migré `begin_processing`).
2. `GENERALIZATION_PLAN.md` : curseur "prochaine app" (Reader déjà porté).
3. `INPUT_MODEL_MATCHING.md` : cocher étapes 1-4/6 déjà exécutées.
4. `MEDIA_STORAGE_TIERING.md` §B : `EMAIL_BACKEND` déjà configuré, ne reste que `notify_by_email`.
5. `MODAL_ACTIONS_AUDIT.md` : note "rollout 5/11 apps sur `_settings_modal_footer.html`".
6. `REMOVAL_LEDGER.md` : resynchroniser la table §1 avec le journal (R1/R2 → ✅).
7. `README.md` : étoffer la table de doc (8/26 référencés seulement).
8. `WAMA_APP_CONVENTIONS.md` §15.1 : ETA et bouton Dupliquer Avatarizer marqués ❌ alors que faits.
9. `TRANSCRIBER_REFERENCE_AUDIT.md` : renvoi croisé vers `UI_MECHANISMS_CONSOLIDATION.md §0` pour
   éviter la contradiction implicite (transcriber = référence sémantique, pas cible technique).
10. `UI_MECHANISMS_CONSOLIDATION.md` §7/§9 : purger la contradiction interne P0 params.py.

**Décisions structurelles tranchées (Fabien, 2026-07-09)** :
- **Archivage → `docs/archive/`** (git mv, historique préservé, pas de suppression). **Exécuté** pour
  les 4 candidats fermes : `AUDIT_GLOBALISATION_T+C_2026-07-03.md`, `BATCH_MODEL_AUDIT.md`,
  `NEXT_SESSION_KICKOFF.md`, `MODEL_META_UNIFICATION_KICKOFF.md` (R10 confirmé clos dans
  REMOVAL_LEDGER.md avant archivage). Aucun lien markdown cassé (vérifié par grep). **Reste en
  attente** : `AUDIT_ROUTE_COMMUNE_2026-07-06.md` — PAS archivé, son §3 (chantiers ordonnés) n'est
  pas encore repris ailleurs ; à ré-évaluer une fois ces chantiers absorbés dans ce fichier.

**Décisions structurelles encore ouvertes** — chantiers de plus grande ampleur, non exécutés ce jour :
- **Restructuration ROADMAP.md** (1219 lignes, ~55-60 % doublon) — chantier de taille, à faire en
  session dédiée (comme le pratique déjà ce repo pour les gros chantiers de convergence) :
  garder §12/13/14/15/16, archiver le reste au profit de renvois vers PROJECT_STATUS.
- **Fusion WAMA_APP_CONVENTIONS.md §5 → renvoi CARD_DESIGN.md** (évite la double maintenance déjà
  visible sur le retrait staging).
- **Règle anti-jungle pour la suite** : avant de créer un nouveau `.md` racine, vérifier s'il ne
  s'agit pas d'un simple ajout à un doc existant (chapeau `PROJECT_STATUS.md` pour l'avancement,
  doc de référence thématique sinon) — les audits ponctuels (`*_AUDIT.md`, `*_KICKOFF.md`) ont
  vocation à être **absorbés puis archivés** une fois leur chantier clos, pas à s'accumuler.

## 24. Bugs corrigés + duplication de vocabulaire média découverte et consolidée (2026-07-09)

- ✅ **Bug médiathèque (recherche toujours vide)** : `MediaPicker.open({type:...})` passait des
  valeurs (`'audio'`, `'all'`) qui ne correspondaient à AUCUNE valeur exacte de
  `media_library.ASSET_TYPES` → `.filter(asset_type=asset_type)` ne matchait jamais rien, quel que
  soit le texte cherché (repro : "voix_fab" introuvable). Fix : `TYPE_GROUPS` (nouveau,
  `media_library/models.py`) traduit les alias larges en listes de vraies valeurs avant filtre
  (`asset_type__in=...`) ; valeur exacte toujours acceptée en repli. Testé bout en bout (asset
  synthétique, 5 cas dont un cas négatif).
- ✅ **Bug rôles/permissions** : `user_update_role` (tier admin/dev/user) faisait `groups.clear()`,
  effaçant silencieusement les rôles MÉTIER (`role:*`, axe B de `accounts/permissions.py`) à chaque
  changement de tier — ET ne synchronisait jamais `UserProfile.account_tier` (l'axe réellement
  consulté par `permissions.accessible()` pour gater les apps WAMA), si bien que choisir
  « Développeur » ne débloquait aucune app (seul « Admin »/`is_superuser` fonctionnait). D'où le
  symptôme remonté par Fabien : « je dois le rendre admin pour tout autoriser ». Fix : ne retire
  que les groupes de tier legacy (pas les `role:*`), synchronise `account_tier` en parallèle.
  **Ajout** : colonne « Métiers » dans `accounts/user_management.html` — checkboxes multi-select
  par utilisateur (communication/recherche/ingénierie/administratif, cumulatifs), nouvel endpoint
  `user_toggle_metier_role` (miroir de `app_access_toggle`, mêmes Groups `role:*`), bouton "Tout
  cocher" par ligne. **Clarification consciente** : le tier `developpeur` (bypass total,
  `BYPASS_TIERS`) reste le bon levier pour "faire tester toutes les apps à quelqu'un" — cocher les
  4 métiers ne suffit PAS pour les apps à `min_tier` (ex. model_manager), vérifié empiriquement.
  Testé bout en bout (5 scénarios : tier→bypass, persistance métier au changement de tier, rejet
  clé invalide, gating min_tier).
- 🔍 **Duplication de vocabulaire « type de média » découverte (Fabien, en creusant le fix
  médiathèque)** : le même concept « catégorie de média » (image/vidéo/audio/document/archive)
  existait déjà en 3 endroits distincts, écrits indépendamment :
  1. `common/app_registry.py::MEDIA_CATEGORIES` + `normalize_types()` — la vraie source, bâtie
     pour le typage des ports studio, mais **quasi sans consommateur** avant ce jour (seulement
     `studio_node_ports()` dans le même fichier).
  2. `common/utils/media_probe.py` (créé 2026-07-08) — listes d'extensions privées dupliquées.
  3. `media_library/static/media_library/js/media-library.js::AUDIO_TYPES` (JS, préexistant) +
     `media_library/models.py::TYPE_GROUPS` (créé ce jour) — même regroupement recréé une 3e fois.
  **Consolidé** : (1) reste la source unique ; extensions manquantes ajoutées (`.heif`/`.avif`,
  `.wmv`/`.ts`/`.m4v`/`.mpeg`, `.aiff`/`.aif`) pour ne rien perdre par rapport aux doublons
  retirés ; (2) dispatch réécrit sur `normalize_types()` (PDF reste un cas particulier littéral,
  page-count) ; (3) `TYPE_GROUPS` dérivé de `MEDIA_CATEGORIES` via un mapping
  `ASSET_TYPE_CATEGORY` (les ASSET_TYPES de Media Library restent plus fins — voice/audio_music/
  audio_sfx — mais se RATTACHENT au vocabulaire commun au lieu d'en inventer un 2e), le JS local
  supprimé au profit d'une variable globale rendue depuis cette même source (`audio_types_json`
  dans le contexte de la vue `index`). Testé : `probe_media` (5 fichiers réels, sortie identique
  avant/après), `normalize_types` sur les extensions ajoutées, pages media-library/converter/
  reader (200), scénario recherche médiathèque (5 cas, inchangé).
- ⏳ **Question ouverte (Fabien)** : `media_library` n'est **PAS enregistrée dans `APP_CATALOG`**
  (confirmé — seules les 10 apps généralistes y figurent). Elle a été construite hors du scope de
  standardisation/auto-génération (pas d'`input_types`/`output_types`, pas de score de conformité,
  pas de port studio). L'intégrer pleinement à `APP_CATALOG` est une décision d'architecture plus
  large (impact nav/permissions/conformité/studio), **pas tranchée, pas exécutée** — à instruire
  si Fabien veut aligner Media Library sur le reste de l'écosystème métadonnée-driven.
- **Leçon retenue** : avant d'écrire une nouvelle petite table de correspondance (extensions,
  catégories, alias), grep `wama/common/app_registry.py` et `wama/common/utils/app_modes.py`
  d'abord — ce sont les deux hubs de vocabulaire partagé les plus susceptibles de déjà couvrir le
  besoin.

## 25. 2 bugs inspecteur commun (transverses, PAS liés au portage) — corrigés 2026-07-10

> Remontés par Fabien en observant Converter, mais les deux vivent dans `wama-inspector.js`
> (commun) → affectaient TOUTES les apps consommant l'inspecteur, pas Converter spécifiquement.

- ✅ **Navigation clavier bloquée sur un batch sélectionné** : `moveSelection()` (↓/↑) exigeait
  `itemId !== null` — or `selectBatch()` met `itemId = null`. Résultat : après un clic sur l'
  en-tête d'un batch, ↓/↑ ne faisaient plus rien (« pas systématique » = seulement après avoir
  sélectionné un batch, pas à chaque card). Fix : `moveSelection` ancre désormais la position sur
  la première/dernière card enfant du batch selon le sens du parcours quand `itemId` est null
  mais `batchId` est défini ; garde du keydown étendue à `itemId !== null || batchId !== null`.
- ✅ **Inspecteur qui « se désactualise » juste après un clic** : `fillDetail()`/`fillPreview()`
  n'avaient AUCUNE protection contre les réponses réseau désordonnées — un clic rapide carte A→B
  lance 2 fetch, sans garantie que celui de A ne résolve pas APRÈS celui de B ; sa callback
  repeignait alors le volet avec le contenu de A alors que B était la sélection courante. Fix :
  jeton anti-course (`_detailReqId`/`_previewReqId`, incrémenté à chaque fetch + à chaque
  `selectBatch`/`deselect`) — seule la callback du DERNIER fetch lancé est autorisée à peindre.
  Bug transverse pré-existant, pas introduit par le portage Converter du jour.
- Testé : sanity JS (accolades/parenthèses équilibrées, occurrences des jetons), smoke des 5
  pages consommant l'inspecteur (200). Pas de test navigateur réel (comportement client pur) —
  **validation visuelle par Fabien recommandée**.

### 25bis. RETIRÉS (2026-07-10) — diagnostic invalidé par le test navigateur

Les 2 fixes ci-dessus ont été **retirés de `wama-inspector.js`** (revert complet, fichier
redéployé dans `staticfiles/`) : Fabien a testé en navigateur après application, **aucune erreur
JS console**, et les deux symptômes (navigation clavier bloquée, inspecteur qui se désactualise)
**persistaient dans Converter** — la preuve que mon diagnostic « bug transverse commun » était
faux ou en tout cas incomplet. Fabien confirme que **reader/composer/transcriber/describer
fonctionnent correctement** avec ce même `wama-inspector.js` : le problème est **isolé à
Converter**, pas au commun. Règle appliquée : *modification incertaine + non prouvée nécessaire
→ retrait plutôt que code potentiellement inutile qui complique l'uniformisation*. Piste réelle
trouvée mais non confirmée comme cause : Converter est le SEUL des 5 apps portées dont le JS
(`converter.js`) n'a **aucun wrapper `DOMContentLoaded`** — ses listeners (dont un click délégué
sur `#converterQueue`, en concurrence avec celui de l'inspecteur) s'exécutent immédiatement au
parsing du script, alors que reader.js séquence TOUT (inspecteur d'abord, puis cycle-button) dans
un unique `init()` appelé au `DOMContentLoaded`. Aucun `stopImmediatePropagation` trouvé nulle
part donc ce n'est pas une preuve, juste une piste **pour le prochain passage sur Converter**.
**Prochaine étape demandée par Fabien** : porter Converter à 100% en s'appuyant sur Transcriber/
Describer/Composer/Reader (apps les plus avancées) comme référence de construction — card
d'entrée (✅ fait §27.1), tri/filtrage/disposition de file, boutons d'actions de file, bug +
mise en conformité de l'inspecteur inclus dans ce passage complet plutôt que traités isolément.

## 26. Vérification pipeline prompts composer/imager (2026-07-10)

- ✅ **Câblage confirmé** : `composer/tasks.py` (1 site) et `imager/tasks.py` (2 sites : image +
  vidéo, cf. §22) appellent bien `process_prompt_for()` → traduction/enrichissement selon modèle
  pour les deux apps. RAG non concerné (pas implémenté, cf. §RAG anticipation).
- ⚠️ **Point non tranché, à revérifier depuis WSL2** : `AIModel.model_key` pour composer semble
  SANS le préfixe `composer:` côté base Windows consultée (`musicgen-medium` au lieu de
  `composer:musicgen-medium`) → `_resolve_model()` ne matcherait jamais, capacités jamais lues,
  repli silencieux sur `default_model_type='music'`. **MAIS** : le code documente déjà ce piège
  exact (commentaire `model_registry.py:912`, renvoie à `REMOVAL_LEDGER.md` F4, marqué ✅ FAIT
  2026-07-01 avec re-sync). Vu que Fabien a confirmé que la base Windows n'est pas à jour
  (session du jour), **cette lecture n'est probablement qu'un artefact de DB obsolète**, pas un
  bug réel côté WSL2 — à reconfirmer directement depuis WSL2 avant toute action. Sans conséquence
  observable actuelle de toute façon (tous les modèles composer sont `music`, capacités vides).

## 27. Converter : card d'entrée manquante + Grille de conformité périmée (2026-07-10)

### 27.1 Bug converter : aucun moyen d'ajouter un fichier hors filemanager — corrigé

Converter n'avait **jamais adopté** la brique commune `_new_item_card.html` (contrairement à
reader/composer/transcriber/describer) : son seul point d'import vivait dans le **volet droit**
(`app_right_panel_media`), invisible en **mode simplifié** (volets masqués) → aucun moyen d'ajouter
un fichier sans passer par le filemanager dans ce mode. Fix : card commune ajoutée en **tête de
file** (même pattern que reader, commentaire "Card d'entrée déplacée du volet vers la TÊTE DE
FILE"), volet droit vidé. Détails techniques :
- IDs préservés (`converterDropZone`/`converterFileInput`) → JS inchangé sauf 1 ajout nécessaire :
  `_new_item_card.html` ne fournit PAS de handler clic-pour-parcourir (chaque app le câble elle-même,
  comme reader) — l'ancien markup avait un `onclick` inline retiré au passage à la brique commune ;
  ajouté `dropZone.addEventListener('click', () => fileInput.click())` dans `converter.js`.
  **Sans cet ajout, cliquer la zone n'ouvrait plus le sélecteur de fichiers** (régression silencieuse
  évitée en vérifiant le JS avant de conclure).
- `batch_detect_bar.html` : ancien include autonome doublé → retiré, réutilisé via le slot
  `show_batch_bar=True` de la card commune (1 seule instance désormais).
- CSS `.converter-drop-zone.dragover` (bespoke) → généralisé en `.drop-zone.dragover` (classe
  générique posée par `_new_item_card.html`), sinon le retour visuel dragover aurait disparu.
- Testé : page 200, 1 seule occurrence de chaque ID (pas de doublon), label attendu présent.

### 27.2 Grille de conformité (`APP_CATALOG.conventions`, `get_conformity_summary()`) : périmée, pas automatique

**Diagnostic confirmé** : le score n'est PAS calculé par introspection du code — c'est une simple
moyenne sur des **booléens saisis à la main** par app (`_conv(...)` dans `app_registry.py`), jamais
revérifiés après coup. Composer (94%) n'est pas "gonflé" : c'est le SEUL à avoir été correctement
ré-audité récemment (commentaires datés, lignes citées) ; les autres dérivent silencieusement au
fil des chantiers (portage, ETA, boutons ajoutés) sans que quiconque ne remette à jour leurs flags.

**Scores AVANT correction** (composer 94% en tête, plusieurs apps sous-évaluées) :
transcriber 77%, describer 72%, enhancer/reader 69%, synthesizer 63%, converter 62%,
anonymizer 60%, imager 45%, avatarizer 40%.

**Corrections appliquées ce jour (chaque flag vérifié par grep/lecture directe du code avant
modification — pas de supposition)** :
- **reader** : `eta_individual`/`eta_batch`/`eta_queue` False→True (wama-eta câblé partout,
  vérifié `_item_card.html`/`_batch_card.html`/`_global_progress.html`) → **69%→82%**.
- **converter** : commentaire `inspector` périmé (décrivait l'ancien `.init`, pas
  `initFromSchema` du portage d'aujourd'hui) + `eta_individual`/`eta_batch`/`eta_queue` False→True
  (mêmes briques que reader, câblées lors du portage) → **62%→75%**.
- **avatarizer** : `duplicate`/`batch`/`clear_all` False→True (boutons + `BatchAvatarJob(BatchMixin)`
  vérifiés présents), `eta_batch` None→True (wama-eta sur les batchs confirmé) → **40%→57%**.
- **transcriber** : `eta_individual`/`eta_queue` False→True (`WamaEta.render` + `_global_progress.html`
  confirmés) ; `eta_batch` laissé False (aucune trace de `eta_ids` batch en JS, cohérent avec la
  mémoire "ETA batch : reste transcriber") → **77%→86%**, redevient cohérent avec son statut de
  référence.
- **imager** : `settings`/`duplicate`/`start_all`/`drag_drop` False→True (boutons + drop-zones
  vérifiés présents dans le template) → **45%→63%**. `batch` volontairement PAS touché : `has_batch`/
  `batch_type=None` portent une annotation "to be redesigned" qui semble une nuance délibérée
  (parent_generation existe mais n'est peut-être pas jugé un "vrai" batch unifié) — **à trancher par
  Fabien**, pas réinterprété unilatéralement.

**Colonnes potentiellement incomplètes (repéré, PAS ajouté)** : aucun flag ne couvre (a) la card
« Nouvel élément » en tête de file (le bug §27.1 aurait été visible dans la grille si ce flag
existait), (b) la section Infos/détail de l'inspecteur (`register_app_detail`/chips, distincte du
flag `inspector` générique existant), (c) `ProcessingTimeMixin`/temps de traitement affiché. Ajouter
ces colonnes nécessiterait de ré-auditer les 10 apps dessus — pas fait, pour ne pas empiler des
flags non vérifiés sous pression de temps.

**PAS fait (limite assumée)** : describer/enhancer/synthesizer/anonymizer n'ont PAS été
ré-audités — leurs scores (72%/69%/63%/60%) sont encore susceptibles d'être sous-évalués comme
imager/converter/reader/avatarizer l'étaient. **Recommandation** : un audit complet et systématique
(idéalement en agents parallèles, comme l'audit des .md du §23) serait nécessaire pour fiabiliser
la grille sur les 10 apps plutôt que de continuer à la corriger au fil des sessions.

Scores APRÈS correction (ordre) : transcriber 86%, reader 82%, converter 75%, composer 94% (inchangé,
toujours en tête), describer 72%, enhancer 69%, avatarizer 57%, synthesizer 63%, anonymizer 60%,
imager 63%. Testé : syntaxe `app_registry.py` OK, `/common/apps/` → 200, pages imager/avatarizer/
transcriber → 200.

## 28. Retrait des 2 fixes wama-inspector.js + suite du portage Converter (2026-07-10)

### 28.1 Fixes communs retirés — diagnostic invalidé par test navigateur réel

Fabien a testé en navigateur après application des 2 fixes §25 : **aucune erreur JS console**,
et les deux symptômes **persistaient** dans Converter. Preuve directe que le diagnostic « bug
transverse dans le commun » était faux — reader/composer/transcriber/describer utilisent le même
`wama-inspector.js` et fonctionnent. Règle appliquée (demandée explicitement par Fabien) :
*modification incertaine + non prouvée nécessaire → retrait, pas de code potentiellement inutile
qui complique l'uniformisation*. **Les 2 fixes ont été intégralement retirés** de
`wama-inspector.js` (revert exact, fichier redéployé) : `moveSelection` batch-anchor + garde
keydown étendue + jetons anti-course `_detailReqId`/`_previewReqId`. Fichier revenu à l'identique
d'avant le §25 (vérifié : 0 occurrence des marqueurs, accolades/parenthèses équilibrées, smoke
5 apps → 200).

### 28.2 Piège commentaire Django multi-lignes — 4e récidive, scan complet du dépôt

Fabien a repéré un `{# ... #}` multi-ligne que je venais d'écrire dans `converter/index.html` —
le piège documenté dans `reference_django_multiline_comment.md`, déjà récidivé 3× avant ce jour.
Corrigé (`{% comment %}...{% endcomment %}`) + **scan mécanique de tout le dépôt** (`glob` +
regex, pas une relecture visuelle) : 2 AUTRES occurrences pré-existantes trouvées et corrigées,
jamais détectées avant (`imager/index.html` entre deux `<script>`, `studio/index.html`). 0 restante
sur tout `wama/**/*.html` après correction. Mémoire renforcée : compter sur la mémoire seule a
échoué 3 fois → la procédure documentée est désormais un scan mécanique après toute édition de
commentaire, pas une simple règle à se rappeler.

### 28.3 Suite du portage Converter — comparé point par point à reader/composer/transcriber/describer

Fabien : *« évite de toucher au commun qui fonctionne très bien »* + s'appuyer sur les 4 apps les
plus avancées comme référence. Comparaison systématique (grep direct, pas de supposition) →
3 gaps réels et vérifiés, **tous corrigés dans converter uniquement** (aucune ligne de commun
touchée) :

1. **`_queue_toolbar.html` jamais adopté** (tri + filtre + toggle Ligne/Mosaïque + actions
   globales, bundle commun utilisé par composer/describer/reader/transcriber — PAS
   `_queue_actions.html`, qui n'est en fait utilisé que par enhancer, contrairement à ce que
   suggérait une mémoire périmée). Ajouté en tête de file avec les IDs EXISTANTS de converter
   (`converterStartAllBtn`/`converterClearAllBtn`) → zéro changement JS requis pour ces boutons.
   Vue : `apply_queue_sort_filter()` branché (même brique que reader), `_name` défini sur
   `input_filename` du 1er item. Toggle Ligne/Mosaïque (`.wama-layout-btn`, mécanisme
   `wama-queue.js::initLayoutToggle`, chargé globalement dans `base.html`) vient bundlé — geste
   auparavant construit mais jamais câblé à un bouton nulle part dans le dépôt (vérifié par grep
   sur les 4 apps de référence + `app_modern_base.html`).
2. **`#converterQueue` sans classe `wama-queue-{{ card_layout }}`** → ajoutée (`card_layout`
   déjà exposé globalement par le context processor accounts, zéro changement de vue requis).
3. **Batch collapse forcé `show`** (toujours déplié) → contrevient à la convention Solitaire
   commune (replié par défaut + persistance localStorage + un seul déplié à la fois,
   `wama-queue.js::initBatchCollapse`/`initOnePileOpen`, chargé globalement). Retiré, converter
   suit maintenant la même convention que reader.
4. **`_inspector_actions.html` jamais inclus** — gap le PLUS probablement responsable du
   comportement « inspecteur qui ne se comporte pas correctement » signalé par Fabien : l'hôte
   `#inspectorActions` (où `cloneActions()` écrit les actions clonées de l'item/batch sélectionné)
   **n'existait pas du tout** dans le DOM de converter → `cloneActions(null, ...)` no-opait
   silencieusement (`if (!host) return;`, confirmé en lisant `wama-inspector.js`) — aucune erreur
   console, la section Actions restait simplement vide/jamais mise à jour. Ajouté dans
   `app_right_panel_actions`, exactement comme reader.

Testé : page 200, tous les IDs/classes présents exactement une fois (`converterStartAllBtn`,
`converterClearAllBtn`, `inspectorActions`, `wama-layout-btn`, `wama-queue-list`), 5 combinaisons
sort/filter → 200 sans crash, filtre `running` confirmé sur données réelles (créées puis
nettoyées). Smoke global 7 pages → 200.

**Reste à faire sur Converter (hors scope de ce palier)** : la piste DOMContentLoaded (§25bis —
converter.js n'a aucun wrapper, contrairement à reader.js qui séquence tout dans un `init()`
unique) n'a pas été retenue comme correction (pas de preuve causale, et le point 4 ci-dessus est
un candidat plus solide pour expliquer le comportement de l'inspecteur) — **à réévaluer une fois
le point 4 validé en navigateur par Fabien** ; si le problème persiste malgré `_inspector_actions.html`,
la piste DOMContentLoaded redevient la prochaine à creuser, toujours côté converter.js/template
uniquement.

## 29. Bug preview inspecteur : webp invisible — doublon MIME filemanager/commun (2026-07-10)

**Symptôme** : les .webp ne s'affichaient pas dans la preview de l'inspecteur (toutes apps),
alors que la preview du filemanager les lit correctement. Fabien : *« la preview est globale et
commune... pas de réécriture, on utilise le formalisme en place »* — a demandé de VÉRIFIER s'il y
avait un doublon plutôt que de deviner un correctif.

**Root cause confirmée empiriquement** : `mimetypes.guess_type('test.webp')` → `(None, None)` sur
cette machine (base mime.types locale incomplète, connu sous Windows). `preview_registry.py::
create_simple_adapter` (l'adaptateur COMMUN consommé par TOUTES les apps portées à l'inspecteur)
appelait `mimetypes.guess_type()` nu → `mime_type=None` → repli `'application/octet-stream'` →
le JS (`renderInlinePreview`, `mime.indexOf('image/') === 0`) ne reconnaît pas l'image, rien ne
s'affiche. **`filemanager/views.py::api_preview` avait DÉJÀ ce correctif** (commentaire explicite
*"Robust MIME detection: mimetypes.guess_type can fail on Windows"* + dict `_EXT_MIME` local,
2026-0X) — jamais reporté vers l'adaptateur commun de l'inspecteur. Doublon confirmé exactement
comme suspecté par Fabien : 2 chemins de détection MIME divergents pour le même besoin.

**Fix (centralisation, pas de réécriture du formalisme preview)** : nouveau
`common/utils/mime_utils.py::guess_mime_type()` — SOURCE UNIQUE (stdlib + repli extension→MIME,
contenu du dict extrait de filemanager). Consommé par :
- `preview_registry.create_simple_adapter` (bug réel, corrigé).
- `filemanager/views.py::api_preview` (refactoré pour utiliser la même fonction — le dict local
  `_EXT_MIME` supprimé, plus de 2e copie qui pourrait diverger).

Testé : `guess_mime_type('test.webp')` → `image/webp` ✓. Bout en bout sur un vrai fichier webp
(`media/anonymizer/1/input/objects_01.webp`) via `unified_preview()` réel (job converter créé/
nettoyé) → `mime_type: image/webp` (était `application/octet-stream` avant fix). Filemanager
`api/preview/` sur le même fichier → toujours `image/webp` (comportement inchangé après
refactor). Smoke 5 apps consommant l'inspecteur → 200.

## 30. Card d'entrée Enhancer — investigué, PAS implémenté (gap plus profond que prévu)

Demandé par Fabien (avec permission explicite de ne pas implémenter si le fit n'est pas net) :
ajouter la card commune `_new_item_card.html` en tête de file d'Enhancer, comme les 5 apps déjà
portées — Enhancer a 2 domaines (image/vidéo · audio) avec onglets, la card devrait s'adapter.

**Investigation réelle faite avant de décider** (pas une estimation a priori) : Enhancer est
**significativement moins porté** que je ne le pensais — chacun de ses 2 onglets a sa PROPRE
structure, et aucun des deux n'utilise le formalisme commun établi ailleurs :
- `#imgvideoTab` : queue `#enhancer-queue` avec des cards **codées en dur** dans le template
  (`.synthesis-card` + classes de statut manuelles), PAS `_job_card.html`/`_batch_card.html`.
  Utilise `_global_progress.html` (commun) pour la barre globale, au moins ça.
- `#audioTab` : queue séparée, ET sa PROPRE barre de progression globale codée à la main
  (`audioGlobalStatus`/`audioGlobalProgressBar`) au lieu de `_global_progress.html` — même dans
  la même app, les 2 domaines ne sont pas au même niveau d'adoption du commun.
- Import : 2 drop-zones distinctes déjà présentes (`dropZoneEnhancer`/`dropZoneAudio`, toggle
  `d-none` via `switchDomain()`) — mais dans le volet droit, pas en tête de file.

**Décision** : ajouter SEULEMENT la card d'entrée serait un patch cosmétique déconnecté du reste
(elle suppose le contrat batch-import/formalisme card des apps déjà portées, qu'Enhancer n'a pas).
**PAS implémenté** — Enhancer a besoin d'un vrai chantier de portage (cards communes sur les 2
onglets, unifier la barre audio sur `_global_progress.html`, PUIS la card d'entrée par domaine),
pas d'un ajout isolé. À traiter comme un palier à part entière, pas glissé dans cette session.

---

## 31. Audit empirique de conformité des 10 apps généralistes (2026-07-10/11)

### 31.1 Méthode
Audit **empirique** (grep/lecture de code, zéro déclaratif) des 10 apps sur **31 critères** :
les 25 flags existants de la grille `_conv()` + 8 nouveaux critères d'uniformisation mesurés
(`new_item_card`, `queue_toolbar`, `queue_manipulation`, `anti_race`, `cycle_button`,
`processing_time`, `status_vocab`, `toast`), chaque verdict adossé à une preuve `file:line`.
La grille `app_registry.py::_conv()` a été **étendue** avec ces 8 critères (comblant les
« colonnes manquantes » identifiées en §27.2) et les flags périmés corrigés. Source live
inchangée : `/apps/` (`get_conformity_summary()`).

### 31.2 Scores APRÈS correction de grille (avant : §27.2)
| App | Score | Écarts restants (issues de la grille) |
|---|---|---|
| transcriber | **93 %** (28/30) | recursive_import, toast (1 alert+confirm edit.js:675) |
| describer | **93 %** (28/30) | recursive_import, modes (pas déclaré APP_MODES) |
| composer | **92 %** (26/28) | recursive_import, toast (4 alert index.js) |
| reader | **90 %** (28/31) | recursive_import, modes, toast (2 alert reader.js) |
| converter | **77 %** (24/31) | download_all, cross_app_options (Phase 2), modes, queue_manipulation, recursive_import, status_vocab (DONE/ERROR), toast (21 alert) |
| enhancer | **70 %** (22/31) | anti_race ⚠, batch-card mère hand-built, new_item_card, queue_toolbar, cycle_button, layout, processing_time, toast (13 alert) |
| synthesizer | **70 %** (22/31) | anti_race ⚠, modales hand-built (params.py ponte dom_id), new_item_card, _batch_card, queue_toolbar, layout, processing_time, toast (42 alert) |
| anonymizer | **61 %** (19/31) | **pas de champ status** (booléen `processed`) = prérequis bloquant, params.py ORPHELIN, inspecteur (preview seule), toast (23 alert) |
| imager | **60 %** (18/30) | **inspecteur 0/4**, params.py ORPHELIN, anti_race ⚠, double markup card image/vidéo, toast |
| avatarizer | **55 %** (17/31) | start_all/download_all sans vue serveur, clear_all simulé client, anti_race ⚠, ordre boutons card KO, toast (21 alert) |

### 31.3 Flags périmés corrigés dans la grille (preuves dans les commentaires du code)
- **ETA sous-déclaré partout** : les 3 niveaux (card `.wama-eta`, batch `data-eta-ids`,
  `_global_progress.html`) sont en réalité câblés dans **les 10 apps** — les flags False
  dataient d'avant le déploiement ETA. Corrigé pour describer/enhancer/synthesizer/
  anonymizer/imager/avatarizer + eta_batch transcriber.
- **avatarizer.tool_api False → True** : add_to/start/get_status présents au registre
  central `wama/tool_api.py` (le « seul manque restant » de CONV §17.6 était périmé).
- **filemanager_import** : True vérifié pour transcriber/describer/reader/synthesizer/
  anonymizer (listener `wama:fileimported`) ; composer=N/A (entrée texte) ; imager/
  avatarizer partiels (drop-zone `data-wama-app` sans listener) → restent False.
- **reader.layout False → True** ; **converter.layout False → True** ;
  **multi_format_download → N/A** pour converter/enhancer/synthesizer/anonymizer/imager/
  avatarizer (early binding : le format se règle AVANT le traitement).

### 31.4 Enseignements transverses (au-delà des flags)
1. **Fracture nette 5+5** : les 5 apps portées (transcriber/describer/composer/reader/
   converter) ont TOUTE la pile commune (new_item_card, _batch_card, queue_toolbar,
   queue_manipulation*, begin_processing*, ProcessingTimeMixin, initFromSchema+
   _inspector_actions+detail/preview registries). Les 5 autres n'ont RIEN de la couche
   file commune. (*converter : consolidate artisanal + verrou local — voir 31.5.)
2. **anti_race absent = seul risque fonctionnel réel** des 5 non portées : start() de
   enhancer (views.py:423), synthesizer (:549), imager (:626), avatarizer (:172) font
   check-then-set sans verrou ni revoke.
3. **`alert()` : ~106 occurrences** dans 8 apps (le helper `WamaApp.toast` existe et
   marche — describer = preuve).
4. **params.py = 10/10 EXISTENT** (contradiction UI_MECHANISMS §0bis/§7 tranchée
   empiriquement) MAIS 2 sont **orphelins** (imager, anonymizer : aucun consommateur
   WamaParams) et 1 ne ponte que les dom_id (synthesizer).
5. **Couleurs de boutons card** : seuls converter (réf) / reader / transcriber sont au
   schéma outline canonique. describer/composer/synthesizer/anonymizer/imager/avatarizer
   ont des variantes pleines ou intercalent des boutons hors référence.
6. **Statuts en base** : reader migré (0008) ; converter encore DONE/ERROR ; anonymizer
   n'a PAS de champ status (booléen `processed`) — hors norme la plus profonde.
7. **modes** : APP_MODES déclare 5 apps (anonymizer/enhancer/imager/synthesizer/
   transcriber) mais seuls enhancer+imager CÂBLENT WamaModes. Question ouverte pour
   Fabien : describer/reader ont-ils vocation à des modes-switch, ou N/A comme composer
   (« type dérivé », flag None) ?

### 31.5 Plan de finition des 5 apps les plus proches (exécuté à la suite de cet audit)
1. **transcriber → 100 %*** : purger alert()/confirm() de edit.js → toast.
2. **describer** : aligner couleurs boutons card (⚙/⧉/🗑) sur la référence outline.
3. **composer** : 4 alert() → toast ; couleurs boutons card ; ⚙ visible pendant RUNNING.
4. **reader** : 2 alert() → toast.
5. **converter** : migration statuts DONE/ERROR → SUCCESS/FAILURE (pattern reader.0008) ;
   vue+bouton download_all global ; fabrique make_queue_manipulation_views ; 21 alert() → toast.
   (cross_app_options Phase 2 et modes = chantiers séparés, pas dans cette passe.)
(*) hors dettes transverses assumées : recursive_import (toutes), card v2 chips (pilote
reader à valider avant propagation), profils (capacité non déclarée), WamaModelCaps.

### 31.6 Docs remis à jour dans cette passe
- `WAMA_APP_CONVENTIONS.md` §15.1 : table figée remplacée par un pointeur vers `/apps/`.
- `UI_MECHANISMS_CONSOLIDATION.md` : contradiction P0 params.py purgée (10/10 existent,
  2 orphelins), P3 marqué fait (transcriber+converter → initFromSchema).
- `ROADMAP.md` : en-tête daté, ligne staging alignée sur CARD_DESIGN §8.5 (supprimé),
  compteurs modale WamaParams corrigés (7/10 : + enhancer, avatarizer ; hand-built :
  synthesizer, anonymizer, imager).
- `CARD_DESIGN.md` §5 : table re-mesurée ; §10.6 ProcessingTimeMixin fait (5 apps portées).
- `INSPECTOR_DETAIL_FIELDS.md` : état de rollout par app ajouté (detail 5/10, preview 8/10).

### 31.7 Exécution du plan §31.5 (2026-07-11) — FAIT
| App | Avant | Après | Actions |
|---|---|---|---|
| transcriber | 93 % | **96 %** | alert() edit.js:675 → toast (confirm() conservé = décision utilisateur, pas une notification) |
| composer | 92 % | **96 %** | 4 alert() → toast ; couleurs card alignées outline (⚙/⬇/🗑) ; ⚙ VISIBLE pendant RUNNING (le `{% if != RUNNING %}` masquait la modale en cours de traitement) |
| describer | 93 % | 93 % | couleurs card alignées (⚙ outline-secondary, ⧉ outline-warning, 🗑 outline-danger, 👁 adouci en outline-success — conservé, bouton légitime hors référence) |
| reader | 90 % | **93 %** | 2 alert() reader.js → toast |
| converter | 77 % | **87 %** | migration statuts **SUCCESS/FAILURE** (0005, appliquée WSL2, pattern reader.0008 ; sweep models/tasks/views/_job_card/converter.js = 19 littéraux) ; vue+bouton **download_all** (ZIP global, slot toolbar `converterDownloadAllBtn`) ; 21 alert() → toast typés |

Écarts restants ASSUMÉS (défauts documentés, pas des oublis) :
- `recursive_import` : dette transverse 10 apps (inchangé).
- `modes` describer/reader/converter : à trancher — vrai switch WamaModes ou N/A « dérivé »
  comme composer ? (question posée §31.4.7).
- `converter.cross_app_options` : Phase 2 planifiée (upscale/audio enhance).
- `converter.queue_manipulation` : la fabrique commune exige l'architecture batch unifiée
  (liaison + BatchMixin) que `ConversionBatch` n'a pas — batch léger = choix documenté
  (note d'intention CONV §15). Trancher le passage à BatchMixin AVANT d'adopter la fabrique.
- JS déployés dans `staticfiles/` : converter.js, reader.js, composer/index.js,
  transcriber/edit.js. ⚠ Redémarrage du process WSL2 requis pour les changements Python
  (converter views/urls/models).

Smoke tests : /transcriber/ /describer/ /composer/ /reader/ /converter/ /common/apps/
→ tous 200 (client Django, superuser).

---

## 32. Portage enhancer + synthesizer — passe « risques + mécanique » (2026-07-11)

Suite directe de §31 : les 2 apps à 70 % rapprochées de la pile commune (**83 % chacune**)
sans toucher à leur architecture de file (port complet différé, voir KO restants).

### 32.1 Fait (enhancer 70 → 83 %)
- **anti-race** : `start()` + `audio_start()` → `begin_processing` (verrou + revoke + reset
  sous verrou via callable) ; en cas d'échec de dispatch Celery, retour à PENDING.
- **ProcessingTimeMixin ×2** (migrations 0010/0011, appliquées WSL2 **et** Windows) — le champ
  legacy `processing_time` (doublon par-app, AUCUN lecteur) a été SUPPRIMÉ, tasks écrivent
  `processing_seconds` ; affichage `_processing_time.html` sur les 2 cards (média + audio).
- **Inspecteur detail** : `register_app_detail('enhancer')` + `('audio_enhancer')` avec labels
  `params.py` (MEDIA_PARAMS/AUDIO_PARAMS) — actif immédiatement car les cards avaient déjà
  `data-preview-url` (dérivation /preview/→/detail/ de wama-inspector.js).
- **13 alert() → toasts typés** ; couleurs boutons alignées outline (template ET buildCard JS
  synchronisés — double rendu CONV §5) ; classe layout `wama-queue-*` sur `#enhancer-queue`.

### 32.2 Fait (synthesizer 70 → 83 %)
- **anti-race** : `start()` → `begin_processing` (reset audio_output sous verrou).
- **ProcessingTimeMixin** (migration 0013, WSL2 + Windows) + worker (`processing_seconds` au
  SUCCESS) + affichage card.
- **Inspecteur detail** : `register_app_detail('synthesizer')` (labels params.py, alias
  output_quality) + `data-preview-url` AJOUTÉ sur `_synthesis_card.html` (manquait → preview
  et detail inspecteur inertes).
- **42 alert() → toasts** (34 index.js + 8 inline template, dont 3 en callback `.catch()` —
  piège de la parenthèse imbriquée traité individuellement) ; couleurs boutons alignées ;
  classe layout sur `#synthesisQueue`.

### 32.3 Vérifications
- Detail end-to-end : objets éphémères créés/supprimés (base Windows = copie dev) →
  `/common/detail/synthesizer/N/` et `/common/detail/enhancer/N/` = 200, schéma canonique.
- Registre detail : 8 apps (audio_enhancer, composer, converter, describer, enhancer,
  reader, synthesizer, transcriber) — manquent avatarizer, imager, anonymizer.
- Chaque `WamaApp.toast(...)` vérifié bien formé (parseur d'équilibre : 0 appel sans type).
- Smoke tests 200 : /enhancer/ /synthesizer/ /converter/ /transcriber/ /common/apps/.

### 32.4 Découverte infra IMPORTANTE
La base Windows et la base WSL2 sont **deux bases différentes et divergentes** (re-prouvé :
colonne `processing_seconds` présente en WSL2 après migrate, absente côté Windows →
`ProgrammingError`). C'était déjà documenté dans la mémoire détaillée (correction 2026-06-25)
mais le RÉSUMÉ d'index disait encore « base unique partagée » — corrigé. Règle : appliquer
les migrations DES DEUX CÔTÉS (WSL2 = live ; Windows = copie de dev pour smoke tests).

### 32.5 KO restants (port complet de la file, chantier suivant)
- enhancer : `_new_item_card` (2 domaines), `_batch_card` mère, `_queue_toolbar`+tri/filtre,
  `_cycle_button` — cf. brief §30.
- synthesizer : idem + modales WamaParams (P1 BLOCKER — params.py ne ponte que les dom_id)
  + câblage WamaModes (déclaré, inerte).
- Puis : anonymizer (prérequis champ `status`), imager (inspecteur 0/4), avatarizer (vues
  globales serveur).

---

## 33. Portage anonymizer — le prérequis « champ status » est tombé (2026-07-11)

Anonymizer **61 → 74 %**. La non-conformité la plus profonde de la grille (§31.4.6 : pas de
champ `status`, booléen `processed`) est résolue.

### 33.1 Migration de modèle (0021, appliquée WSL2 + Windows)
- `Media` gagne `status` (PENDING/RUNNING/SUCCESS/FAILURE), `task_id`, `error_message`,
  et hérite `ProcessingTimeMixin`.
- **Conversion des données AVANT drop** : la migration auto-générée droppait `processed`
  sans convertir → réécrite à la main (AddField → RunPython processed=True→SUCCESS →
  RemoveField). Vérifié sur la base live WSL2 : 18 médias → SUCCESS.
- **`processed` survit en PROPERTY dérivée** (`status == 'SUCCESS'`) : les ~50 LECTEURS
  (templates `media.processed`, JSON `'processed': m.processed`, JS) fonctionnent sans
  modification ; seuls les ~12 usages DB-level (filtres queryset, écritures,
  `update_fields`, `reset_fields` de la fabrique) ont été balayés vers `status`.
- Cycle de vie complet dans le worker : RUNNING au démarrage effectif, SUCCESS +
  `processing_seconds` à la fin (2 chemins : YOLO single-task + SAM3/parallel),
  **FAILURE + error_message sur exception** (avant : échec invisible, progression figée).

### 33.2 Aussi fait
- `register_app_detail('anonymizer')` (labels params.py — qui n'est du coup plus
  totalement orphelin ; `result_file=None` car la sortie est un chemin dérivé `_blurred_*`).
  Testé bout-en-bout : 200, schéma canonique.
- 23 alert() → toasts typés (batch/right_panel/settings_modal/update/upload.js),
  vérification parseur : 0 appel mal formé.
- Couleurs boutons card : ⚙ `btn-warning`→`outline-secondary`, ⧉ →`outline-warning`.
- Classe layout `wama-queue-*` sur `#medias` ; `status` exposé dans le JSON de liste
  (en plus de `processed` conservé).

### 33.3 KO restants anonymizer (port complet)
inspector (initFromSchema + _inspector_actions — volet droit hand-built `right_panel.js`),
modes (déclaré, non câblé), anti_race complet (pas de vue start par item — RUNNING posé par
le worker), _new_item_card/_batch_card/_queue_toolbar/_cycle_button, modale hand-built
(settings_modal.js) à migrer vers WamaParams.

### 33.4 Grille au 2026-07-11 (après §31.7 + §32 + §33)
transcriber 96 · composer 96 · describer 93 · reader 93 · converter 87 · enhancer 83 ·
synthesizer 83 · **anonymizer 74** · imager 60 · avatarizer 55.

---

## 34. Passe conservatrice imager + avatarizer (2026-07-11)

Consigne Fabien : « sans rien casser — si doute, ne pas implémenter ». Uniquement des ajouts
additifs vérifiés. **imager 60 → 66 %**, **avatarizer 55 → 68 %**.

### 34.1 Imager
- **anti-race** : `start_generation` → `begin_processing` (verrou + revoke — le modèle avait
  déjà status/task_id, drop-in propre).
- **register_app_detail('imager')** (labels IMAGE_PARAMS/VIDEO_PARAMS selon le mode) — testé
  bout-en-bout (200, schéma canonique). **PAS de register_app_preview** (décision différée :
  `generated_images` = JSON multi-images, « quelle image prévisualiser » = choix de design
  du port complet).
- **`showNotification` délègue à `WamaApp.toast`** (le doublon Bootstrap local est retiré ;
  types danger/success/info compatibles) + 3 alert() purgés.
- ⚠ Incident réparé pendant la passe : un remplacement a perdu un backslash (chaîne JS
  `l\'amélioration` cassée) — détecté immédiatement (grep du segment) et réécrit par
  construction explicite. Vérif finale : 0 alert(), parens/braces/backticks équilibrés,
  0 toast mal formé.
- **NON fait (doute assumé)** : classe layout `wama-queue-*` (cards Bootstrap larges, rendu
  mosaïque incertain) ; dédup du double markup card image/vidéo ; initFromSchema ; modale
  WamaParams ; listener wama:fileimported.

### 34.2 Avatarizer
- **3 vues serveur globales créées** : `start_all` (begin_processing par job non terminé),
  `clear_all` (remplace la boucle DELETE côté client ; MÊME nettoyage de fichiers que la
  vue delete par item — audio_input/avatar_upload/output_video ; refuse si un job RUNNING),
  `download_all` (ZIP des sorties) + URLs + boutons standards (#btn-start-all vert,
  #btn-download-all bleu) + bindings JS (le clear-all JS appelle désormais la vue serveur).
- **anti-race** : `start` → `begin_processing` (le statut passe RUNNING à l'acceptation,
  comme partout — avant : PENDING posé en vue, RUNNING par le worker).
- **register_app_preview** (aperçu = `avatar_upload`, l'identité visuelle du job) +
  **register_app_detail** (labels params.py) — testés bout-en-bout (200 ; preview sans
  fichier → « No file available » propre).
- **Ordre boutons card corrigé** : ⚙ AVANT ↻ (seule app dans le mauvais ordre) + couleurs
  outline canoniques (template + buildCard JS synchronisés) ; 21 alert() → toasts typés.
- Vérifs : `manage.py check` 0 issue ; smoke 200 (/avatarizer/ /imager/) ; parseur toasts
  0 mal formé.

### 34.3 Grille au terme de la session (audit §31 → §34)
| | avant audit | après |
|---|---|---|
| transcriber | 86 | **96** |
| composer | 94 | **96** |
| describer | 72 | **93** |
| reader | 82 | **93** |
| converter | 75 | **87** |
| enhancer | 69 | **83** |
| synthesizer | 63 | **83** |
| anonymizer | 60 | **74** |
| avatarizer | 57 | **68** |
| imager | 63 | **66** |

Prochaines marches (dans l'ordre de rendement) : port complet de la file enhancer/synthesizer
(brief §30/§32.5) ; inspecteur imager (preview multi-images = décision design) ; anonymizer
initFromSchema + modale WamaParams ; avatarizer briques de file.

---

## 35. Avatarizer — card d'entrée commune en tête de file (2026-07-11)

Demande Fabien : « la card d'entrée en en-tête de file comme pour les applications portées ».
**Avatarizer 68 → 72 %.**

### 35.1 Ce qui a bougé
- La COLONNE GAUCHE de saisie (onglets Pipeline/Standalone + textarea + dropzone audio +
  galerie d'avatars) est SUPPRIMÉE ; la file passe en pleine largeur (col-12).
- `common/_new_item_card.html` incluse en tête de file (avant `#jobs-container`) :
  - prompt = texte de la consigne (`#text_content`, compteur de mots conservé) ;
  - dropzone = audio prêt (`#audio-dropzone`/`#audio_input`) + bouton Médiathèque (audio) ;
  - bouton primaire = `#btn-generate` « Générer la vidéo » (déplacé du volet droit — action
    primaire de la card, CARD_DESIGN §2 ; passe de bleu à vert conventionnel) ;
  - galerie d'avatars + badge audio retenu via le NOUVEAU slot `extra_zone_template`
    (`avatarizer/_new_item_extra.html`).
- **Tous les ids historiques conservés** → les handlers de index.js (drop texte/audio,
  word count, sélection avatar, remove audio, generate) fonctionnent sans réécriture.
- Onglets Pipeline/Standalone supprimés : le radio `workflow_mode` du volet droit était DÉJÀ
  la source unique du mode (`getMode()`) — les onglets n'étaient qu'une vue synchronisée.
  Le sync mort a été nettoyé ; l'import audio depuis le filemanager bascule maintenant le
  radio directement (avant : il cliquait l'onglet).
- `data-wama-app="avatarizer"` posé à l'init JS sur les 2 zones (le partial ne le rend pas ;
  requis par le quick-drop filemanager `getAppFromDropZone` → dataset).

### 35.2 Extension DÉCLARÉE du partial commun (3 slots opt-in, documentés dans son en-tête)
1. `prompt_zone_id` — id posé sur le conteneur du prompt (permet aux apps d'y brancher un
   drop de fichier texte). 2. `prompt_counter_id` — span compteur de mots sous le prompt.
3. `extra_zone_template` — template d'app inclus en fin de zone médiane (spécificité
   déclarée, hérite du contexte). Aucun impact sur les consommateurs existants (ifs gardés).

### 35.3 Vérifications
- Rendu : 200 ; card présente ; ids uniques ×1 (0 doublon `#btn-generate`) ; 13 avatars de
  la galerie rendus DANS la card ; card avant la file ; onglets et col-md-5 absents.
- ⚠ Récidive n°5 du piège commentaire Django `{# #}` multi-lignes (dans MES ajouts) —
  détectée et corrigée en `{% comment %}` + re-scan du fichier (0 restant). Le réflexe
  d'écriture reste le point faible : TOUJOURS `{% comment %}` pour tout commentaire ≥ 2 lignes.

---

## 36. Avatarizer STANDALONE-ONLY (décision Fabien, 2026-07-11)

> « On peut basculer l'avatarizer en standalone seul, comme on utilisera le synthesizer +
> avatarizer dans le studio pour le pipeline. » — concrétise R16/§20bis (pipeline = axe
> WORKFLOW de la méta-app, pas un mode d'app).

### 36.1 Retiré de l'UI (création)
- Radios `workflow_mode` + bloc `#pipelineSettings` (TTS : modèle/langue/voix) du volet droit.
- Prompt texte de la card d'entrée (la card devient : dropzone audio « voix de l'avatar »
  + Médiathèque + galerie d'avatars + Générer).
- JS : `getMode()` figé à `'standalone'` ; branches pipeline de `createJob`/
  `updateGenerateButton` supprimées ; bloc mort du drop de texte (~90 lignes,
  extractTextViaServer/loadTextIntoArea) purgé après vérification qu'aucun symbole n'était
  utilisé ailleurs ; CSS `#text-dropzone` mort retiré.
- Vue `create()` : défaut serveur `mode='standalone'`.

### 36.2 INTACT (backend + historique)
- Modèle : champ `mode`, champs TTS ; worker pipeline ; **batch** (les fichiers batch à
  lignes texte→pipeline restent acceptés — à re-trancher quand le studio orchestrera) ;
  tool_api ; AFFICHAGE des jobs pipeline historiques (cards, modale section pipeline,
  label « Mode » du detail inspecteur via params.py — la déclaration `mode` du schéma est
  conservée pour ça, son câblage radio absent est null-gardé).

### 36.3 Vérifications
Rendu 200 ; 0 résidu `pipelineSettings`/`text_content`/`text-dropzone` ; réglages MuseTalk
(quality_mode/bbox_shift/enhancer) intacts ; `manage.py check` 0 issue ; garde-fou avant
purge du bloc mort : grep de chaque symbole → 0 usage externe.

---

## 37. Studio — persistance + EXÉCUTION réelle de pipelines (2026-07-11)

Les deux ⏳ du §15 sont livrés. Cas phare : **synthesizer → avatarizer** (concrétise la
décision §36 : le pipeline texte→TTS→avatar EST une composition studio).

### 37.1 Architecture
- **`studio/models.py`** : `StudioPipeline` (graphe nommé JSON, unique par user+nom) ;
  `StudioRun` (graphe figé, statut, `node_states` par nœud, ProcessingTimeMixin).
  Migration 0001 appliquée WSL2 + Windows.
- **`studio/services/runners.py`** : adapters d'exécution par app — triade canonique
  `create(user, inputs, params) → item_id` / `start` / `poll → {status, progress, output}`,
  branchée sur **`wama/tool_api.py`** (philosophie : chaque app expose son API à la
  méta-app ; le traitement tourne dans le Celery de l'APP, le studio orchestre).
  `params_spec` déclaratif par app → l'UI des params de nœud est GÉNÉRÉE (métadonnée-driven).
  Ajouter une app exécutable = ajouter une entrée RUNNERS, zéro logique d'orchestration.
- **`studio/tasks.py`** : `run_pipeline_task` — ordre TOPOLOGIQUE (refus des cycles),
  chaînage des sorties par type de port (audio→audio…), timeout 30 min/nœud, états par
  nœud persistés à chaque étape, console `app='studio'`, notification fin de run.
- **Vues/URLs** : `/studio/api/pipelines/` (GET liste, POST upsert), `/pipelines/<id>/`
  (GET graphe, DELETE), `/run-options/` (params_specs + galerie d'avatars), `/run/`
  (validations AVANT dispatch : cycle, apps non exécutables), `/run/<id>/` (polling).

### 37.2 UI (wama-studio.js + index.html)
- Toolbar : nom + 💾 Sauvegarder + select Charger + ▶ Exécuter + statut de run.
- Sérialisation/restauration du graphe (positions, params, liens par groupe de port).
- Params d'exécution du nœud sélectionné rendus dans l'inspecteur depuis `params_spec`
  (texte/langue/voix du synthesizer ; avatar (liste réelle de la galerie)/mode avatarizer).
- Pendant le run : polling 2,5 s → liseré JAUNE (running) / VERT (success) / ROUGE
  (failure) sur chaque nœud ; toast + durée à la fin.

### 37.3 Validations empiriques
- Endpoints testés (client Django) : save/load/list/delete 200, run→400 sur graphe
  cyclique et sur app non exécutable (messages clairs), run-options renvoie la vraie
  galerie (avatar_1.jpg…).
- **Moteur testé à blanc** (runners simulés, sans GPU) : ordre topo respecté, la sortie
  `synthesizer/out.wav` arrive sur l'entrée `audio` du nœud avatarizer, node_states
  corrects, run SUCCESS + processing_seconds + notification.
- ⚠ Exécution RÉELLE à valider en usage (requiert redémarrage WSL2 : nouveau module
  studio/tasks.py à découvrir par Celery + modèles TTS/MuseTalk chargés).

### 37.4 Limites V1 (assumées, consignées)
- Runners : synthesizer + avatarizer seulement (l'erreur guide : « V1 : synthesizer,
  avatarizer »). Les nœuds-source builtin (prompt_batch, media_import) ne sont pas
  exécutables — les entrées initiales viennent des params de nœud.
- Chaîne = graphe acyclique quelconque mais UNE valeur par type de port en entrée ;
  pas de fan-out parallèle (exécution séquentielle).
- Les sorties restent dans les files des apps (pas encore de dossier studio dédié).

### 37.5 Cards d'entrée / de sortie + inspecteur complet (2026-07-12)
Réponse au manque pointé par Fabien (« cards d'entrées de tous les types + médiathèque,
inspecteur fonctionnel, cards de sorties ») :
- **Nœud « Texte »** (source exécutable) : texte/prompt saisi dans l'inspecteur → port
  `prompt` (consommé par synthesizer ; demain imager/composer).
- **Nœud « Médias importés »** : désormais CONFIGURABLE — bouton « Choisir dans la
  médiathèque » (MediaPicker COMMUN) dans l'inspecteur ; catégorie du média résolue
  côté serveur (extensions app_registry) → typage de port correct à l'exécution.
- **Nœud « Sortie »** (terminal, sans port aval) : range le résultat final dans la
  MÉDIATHÈQUE — UserAsset RÉEL (fichier copié dans son stockage, nom dédoublonné,
  mime via mime_utils commun), nom + type d'asset configurables dans l'inspecteur.
- **Runner converter** ajouté (3e app exécutable) : « configurer le FORMAT de sortie »
  = chaîner un nœud converter (format + qualité dans l'inspecteur) ; type de port
  produit résolu dynamiquement du format demandé (`output_type_fn`).
- **Inspecteur = configurateur pour TOUS les nœuds** : specs servies par
  `/studio/api/run-options/` (runners + nœuds intégrés), rendu générique
  (textarea/select/text/media_picker).
- Testé à blanc de bout en bout : Texte → synthesizer(mock) → avatarizer(mock, fichier
  réel) → Sortie → **UserAsset créé dans la vraie médiathèque** (chemin
  media_library/<user>/assets/), texte bien reçu en amont, states par nœud corrects.
- Reste connu : prompt_batch (source multi-prompts) non exécutable (attend le runner
  imager + la sémantique batch dans un pipeline) ; sorties texte (futurs runners
  transcriber/describer) : le sink attend un fichier — à traiter avec ces runners.

### 37.6 Les 10 apps généralistes exécutables dans le studio (2026-07-12)
- **RUNNERS 3 → 10** : + transcriber, describer, reader (sorties TEXTE), composer
  (prompt→audio), enhancer, imager (types AUTO — catégorie du fichier produit),
  anonymizer (sortie = chemin dérivé `_blurred_*`, même logique que download_media).
- **Extension du contrat d'exécution** : `poll` peut retourner `is_text` (la valeur
  circule comme texte, pas comme fichier) ; `output_type: 'auto'` = catégorie du
  fichier produit (app_registry) ; le nœud Sortie a une variante TEXTE (écrit un
  `.txt` en médiathèque, type `document`).
- **`start_composer` AJOUTÉ au registre central `wama/tool_api.py`** (la triade
  create/start/status était incomplète — compose_music créait sans pouvoir lancer) ;
  begin_processing + compose_task, conforme au pattern des autres.
- **Vérification EMPIRIQUE des signatures** avant écriture : 4 écarts corrigés
  (transcriber sans kwarg language ; describer output_format/output_language ;
  reader backend ; composer model — défaut musicgen-small préservé) + ai_model
  enhancer aligné sur la vraie clé (RealESR_Gx4).
- Chaînes testées à blanc : Médiathèque→transcriber→Sortie (.txt RÉEL en médiathèque,
  contenu vérifié) ; Texte→imager→enhancer→Sortie (types auto, asset image).
- `/studio/api/run-options/` sert 13 specs (10 apps + Texte/Médiathèque/Sortie) ;
  messages d'erreur du run dynamiques depuis RUNNERS.
- Nouvelles compositions possibles : re-voicing (transcriber→synthesizer),
  sous-titrage différé (transcriber→Sortie txt), OCR→lecture audio
  (reader→synthesizer), prompt→image→amélioration→médiathèque, floutage→conversion…

### 37.7 Contrat uniforme : gel du shim, preview E/S, runner générique (2026-07-12/13)
Recadrage Fabien : « le studio consomme le CONTRAT, jamais l'état courant des apps »
(mémoire feedback_studio_uniform_contract + STUDIO_VISION « principe directeur »). Exécuté :
1. **runners.py = shim V1 GELÉ** (bandeau interdiction d'étendre) ; spec du contrat d'app
   exécutable consignée (STUDIO_VISION : 4 éléments, tous du contrat commun).
2. **Preview ENTRÉE/SORTIE générique** (toutes apps, zéro code par app) :
   `unified_preview ?side=` + méta `sides` (dérivées de `result_file` canonique du detail) ;
   inspecteur : défaut intelligent (SUCCESS→sortie), toggle [Entrée|Sortie], mode
   **Comparer** (slider image/image V1). Fix au passage : `DetailRegistry.get()` renvoie
   {model, adapter}. Testé : converter (comparable), synthesizer (toggle audio), 8 pages 200.
3. **Runner GÉNÉRIQUE** (`generic_runner.py`) piloté par le contrat : create =
   `add_to_<app>` avec params FILTRÉS PAR INTROSPECTION de signature + coercition par type
   du schéma ; poll = clés canoniques du detail + `progress` modèle ; params de nœud =
   POINTEUR vers …PARAMS_JSON de l'app (mapping de forme, jamais de copie).
   **Pilote : enhancer** — triade normalisée (`item_id` ajouté au retour d'add_to_enhancer),
   adapter manuel SUPPRIMÉ du shim (1/10 vidé). Testé empiriquement : spec 3 params depuis
   params.py, création réelle tool_api (param inconnu filtré, toggle coercé), poll
   PENDING→SUCCESS avec sortie.
   Prochaines normalisations (déjà proches du contrat) : transcriber/describer/reader —
   il leur faut la clé `item_id` + `result_text` au schéma canonique du detail (sorties texte).

### 37.8 Normalisation transcriber/describer/reader → runner générique (2026-07-13)
- `item_id` ajouté aux retours `add_to_transcriber`/`add_to_describer` (reader l'avait) ;
- **`result_text` = nouvelle clé CANONIQUE du detail** (build_detail +
  INSPECTOR_DETAIL_FIELDS), servie par les 3 adapters → les sorties TEXTE sont chaînables
  par le contrat (transcriber→synthesizer, reader→synthesizer, →Sortie .txt) ;
- generic_runner : poll texte (`is_text`) ; **shim vidé 4/10** (enhancer + les 3) ;
- 🐛 **bug préexistant réparé** (découvert par le test empirique du runner) :
  `add_to_describer` passait `output_format=` au constructeur alors que le champ modèle
  est `output_style` — le tool était cassé pour l'assistant aussi.
- Restent au shim : synthesizer, avatarizer, converter, composer, imager, anonymizer
  (créations non-fichier ou signatures spéciales : prompt d'entrée, convert_file
  auto-start, sortie dérivée anonymizer, multi-images imager).

### 37.9 Entrées PROMPT génériques → synthesizer/composer/imager (2026-07-13)
- Aliases NORMALISÉS `add_to_synthesizer`/`add_to_composer`/`add_to_imager` dans le
  registre central (`@functools.wraps` → la signature réelle reste introspectable pour
  le filtrage de params ; clé UNIFORME `item_id` ; les façades historiques de
  l'assistant inchangées).
- `generic_runner` : `primary_input='prompt'` — prompt résolu des entrées typées
  (nœud Texte, sorties texte transcriber/reader…) avec repli params ; clés consommées
  exclues des kwargs.
- imager : clé canonique `result_file` COMPLÉTÉE dans son adapter detail (vidéo OU
  1re image de `generated_images`) — bénéficie aussi à la preview Sortie de l'inspecteur.
- **Shim vidé 7/10.** Restent (raisons identifiées) : avatarizer (double entrée
  audio+avatar), converter (convert_file auto-start, nom non normalisé), anonymizer
  (sortie dérivée sans champ modèle — le vrai fix est un champ output_file, item de
  portage).
- Testés : création réelle par prompt ×3 (coercitions duration/width/height vérifiées),
  poll SUCCESS avec sortie canonique, specs 7/5/8 params depuis params.py.

### 37.10 Shim SUPPRIMÉ — 10/10 apps sur le runner générique (2026-07-13)
- **converter** : alias normalisé `add_to_converter` (item_id) + `auto_start` DÉCLARÉ au
  manifeste (convert_file dispatche à la création → start no-op).
- **avatarizer** : vocabulaire manifeste étendu — `input_kwarg='audio_path'` +
  `fixed_kwargs={mode: standalone, avatar_source: gallery}` (spécificité déclarée, pas
  codée) ; l'avatar vient d'une `extra_params_spec` (à résorber en l'ajoutant au
  params.py de l'app avec options_source).
- **anonymizer — ITEM DE PORTAGE réalisé** : champ `Media.output_file` (migration 0022
  WSL2+Windows avec BACKFILL — 1re version same-dir = 0/18, dérivation RÉELLE
  `<user>/output/<base>_blurred*` = **17/18** sur la base live, le 18e n'a plus de
  fichier) ; posé au SUCCESS par le worker (2 chemins YOLO/SAM3) ; detail expose enfin
  `result_file` canonique (⇒ preview Sortie inspecteur aussi).
- **`runners.py` = façade de 25 lignes** (résolution + historique) ; toute la logique
  dans generic_runner (manifeste GENERIC_APPS, 10 apps + vocabulaire déclaré :
  primary_input/input_kwarg/fixed_kwargs/auto_start/extra_params_spec).
- 🐛 Trou de validation trouvé au smoke final : un nœud d'app inconnue SANS amont était
  toléré comme « source » alors qu'il alimentait un aval (run dispatché pour échouer à
  l'exécution) → un nœud non exécutable ne peut plus être connecté NI en amont NI en
  aval ; runs parasites purgés (2 bases).
- Tests : avatarizer (mode standalone forcé, avatar, audio via input_kwarg, poll vidéo),
  anonymizer (vraie image PIL — le tool valide les fichiers —, poll output_file
  canonique, 17 params de son params.py), converter (start no-op) ; 13 specs servies ;
  pages 200.

### 37.11 Fix inspecteur studio : sélection par délégation + zéro échec silencieux (2026-07-15)
Symptôme (Fabien) : clic sur une card-nœud → inspecteur vide. Diagnostic empirique :
l'hôte existe dans le DOM ; le rendu (WamaDetails, brique commune description-driven)
est conforme au contrat ; les VRAIES causes étaient dans le câblage spécifique :
1. la sélection n'était câblée que sur l'EN-TÊTE du nœud (mousedown de la poignée de
   drag) — cliquer le corps de la card ne faisait RIEN ;
2. toute erreur d'inspecteur était AVALÉE (`try{selectNode()}catch{/*non bloquant*/}`
   + catch « Inspecteur indisponible » sans trace) ;
3. hôte disparu (interférence d'un autre script sur le volet droit) → retour silencieux.
Refonte (« on réutilise le commun, on retire le spécifique ») :
- sélection par DÉLÉGATION au clic sur TOUT le nœud (pattern commun des apps), fond
  (canvas/SVG) = désélection — l'ancien couple mousedown-head + click-fond supprimé ;
- erreurs VISIBLES (message dans le volet + console.error) ; hôte manquant →
  RECRÉÉ dans #global-settings-container + console.warn (interférence diagnosticable) ;
- le rendu reste 100 % WamaDetails (renderSections/renderActions, schéma déclaratif) +
  params de nœud générés des specs — rien de spécifique ajouté.
⚠ À revalider navigateur (hard-refresh inutile : static_v cache-bust). Si un message
« Inspecteur en erreur : … » ou un warn [WamaStudio] apparaît → me le remonter tel quel.

### 37.12 CAUSE RACINE de l'inspecteur studio vide — trouvée par exécution V8 (2026-07-15)
Le fix 37.11 (délégation + erreurs visibles) a fait apparaître une régression (palette
« Chargement… ») qui a mené à la VRAIE cause, prouvée en exécutant le script dans V8
(mini-racer + DOM stub) :
- **`global` n'a JAMAIS été défini dans wama-studio.js** (IIFE sans paramètre, contrairement
  aux briques communes `(function (global) {...})(window)`).
- Le check historique `!node || !global.WamaDetails` ne survivait au chargement que par
  COURT-CIRCUIT (`!node` vrai quand rien n'est sélectionné). Au CLIC (node défini),
  `global.WamaDetails` → ReferenceError → avalé par le try/catch silencieux du mousedown
  → **inspecteur vide depuis le premier jour du squelette**.
- Mon warn de 37.11 évaluait `global.…` inconditionnellement dans init() → init plantait
  avant le fetch du catalogue → palette bloquée (le symptôme rapporté).
Fix : IIFE au pattern commun `(function (global) {...})(window)`. Vérifié dans V8 : init
complet (3 fetches), plus d'erreur, WamaDetails réel chargé et détecté.
**Outillage durable** : `esprima` (syntaxe) + `mini-racer` (runtime V8 + DOM stub)
installés — désormais TOUT edit JS passe par ces deux vérifications (l'équilibre de
parenthèses ne détecte ni les ReferenceError ni les pièges de portée). Consigné en mémoire.

### 37.13 MediaPicker au studio + brouillon PERSISTANT du canvas (2026-07-15)
1. **« Médiathèque indisponible »** : media-picker.js est bien chargé globalement
   (base.html:270) mais exporte via `const MediaPicker = …` au top-level = binding
   lexical global, PAS `window.MediaPicker` — mon garde testait window.* → toujours
   faux. Fix : détection par identifiant (`typeof MediaPicker !== 'undefined'`).
   (NB : le prérequis ML_LIST_URL a un fallback interne vers /media-library/api/assets/.)
2. **Brouillon persistant** (demande Fabien : ne plus perdre le graphe en changeant
   d'app) : autosave localStorage (`wama_studio_draft`, graphe + nom) à CHAQUE mutation
   (ajout/suppression nœud, lien, drag, params, choix médiathèque) ; restauration à
   l'init APRÈS le catalogue ; « Vider le canvas » purge le brouillon (geste explicite) ;
   la sauvegarde en pipeline garde le brouillon synchronisé.
3. Validé dans le harnais V8 (fetch résolvant + localStorage préchargé) : 2 nœuds + nom
   restaurés, hooks réécrivent le brouillon, zéro warn. Deux gaps de STUB corrigés au
   passage (style.setProperty, querySelector→El neutre) — le catch de restauration est
   volontairement BAVARD (console.warn) comme le reste depuis 37.12.
4. **Harnais pérennisé** : `wama-dev-ai/tools/js_v8_harness.py <script.js>` (esprima +
   mini-racer) — référencé en mémoire.

### 37.14 Fix enregistrement pipeline studio : CSRF (403) (2026-07-15)
Symptôme : « Unexpected token '<' … is not valid JSON » + POST 403 à
/studio/api/pipelines/. Double cause dans la fonction `api()` de wama-studio.js :
1. `WamaApp.csrfHeaders()` appelé SANS argument — or sa signature est
   `csrfHeaders(csrfToken, extra)` → envoyait `X-CSRFToken: undefined` → 403 Django ;
2. `r.json()` sur la page d'erreur HTML → « Unexpected token '<' » (message opaque).
Fix : `api()` lit le vrai token (input `csrfmiddlewaretoken` sinon cookie `csrftoken`),
`credentials:'same-origin'`, et détecte les réponses non-JSON pour un message CLAIR
(403 → « Session expirée ou accès refusé »). Vérifié serveur (Client CSRF strict) :
token présent au HTML + cookie posé, POST avec token → 200 (pipeline créé/nettoyé).

### 37.15 Studio : animation de flux sur les câbles pendant l'exécution (2026-07-17)
Demande Fabien : montrer la donnée qui transite entre 2 cards pendant un run.
- Un point cyan lumineux circule le long d'un câble tant que son nœud CIBLE est RUNNING
  (= la donnée entre dans la card en cours de traitement) ; le câble s'illumine aussi.
- Pur SVG, dans l'esprit vanilla du studio : `<circle><animateMotion><mpath href="#linkpath-<id>"/>`
  → le point SUIT le tracé du câble (et le suit même si le nœud est déplacé, car mpath
  référence la path vivante). Aucune dépendance.
- Piloté par les ÉTATS RÉELS du run (pollRun/node_states) via updateFlows ; coupé en fin de
  run et par clearRunStates. Chaque path de lien porte désormais un id (`linkpath-<id>`).
- Validé : esprima + harnais V8 (init 0 erreur) + test unitaire isolé de setLinkFlowing
  (structure circle>animateMotion>mpath[href] correcte, ON/OFF). Harnais pérenne complété
  (style.setProperty, document.cookie/querySelector/createElementNS, fetch headers).

## 🌍 Architecture en MONDES (doctrine 2026-07-20)
WAMA = 4 mondes (Médias / Data / Lab / Transversal) qui communiquent via le système de capacités/ports typés, peuplent studio + médiathèque. **Accès sur 3 axes** : tier + rôles métier + **appartenance organisationnelle** (arbre institut/université→département→labo/service→équipe→utilisateur). Cet arbre = **le même que les niveaux d'héritage RAG** → un seul modèle `OrgUnit`, 3 usages (héritage RAG, scopes de partage, gating d'accès), à ne pas dupliquer. ✅ **Points 1-3 faits (35073dd)** : `OrgUnit` (arbre common), médiathèque `UserAsset(ScopedVisibility)` + API promote, `UserFunction` (confidentialité). LDAP/SUPANN remonté au login (6ebeffe). Détail : `docs/VISION_STATUS.md` §MONDES (⚠ docs/ non versionné). Catalogue : `/model-manager/functions/`.
