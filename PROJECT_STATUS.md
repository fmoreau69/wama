# PROJECT_STATUS.md — Point d'étape des chantiers WAMA

> Photo des chantiers en cours. Mise à jour : **2026-06-29**.
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
- ⏳ Suites : **persistance + exécution** d'un 1er pipeline (→ dossier filemanager studio), ports multi-entrées, specs Fabien (montage/mixage).

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
- 🔄 **Tri/filtrage de la file** : **FAIT + validé sur Transcriber (2026-06-29)** — barre d'outils
  (tri récent/ancien/nom + filtre statut tous/brouillon/en cours/terminé/échec), **côté serveur**,
  persisté en **session** ; **remplace le tri « batchs d'abord »** par le **chronologique** (défaut récent).
  **Reste** : le porter aux autres apps (le **reader** a encore son tri batch-first app-spécifique) ;
  options sort type/durée ; envisager extraction commune. Tri par défaut chronologique = acté partout.
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

## Bugs / dettes connus
- 🐞 Higgs Audio V2 : ~5 s d'audio dégradé malgré tous les patches — non résolu.
- 🔧 Patches venv → toujours via `patches/apply_patches.py`.
- 🌐 Headroom code-aware : `Mode: token` actuel → activer via terminal neuf + vérifier `headroom_stats`.

## Ordre de reprise recommandé
1. Model Manager volet droit (débloque le test prospection — ROI immédiat).
2. Cam Analyzer Phase 3 (calibration + vitesses).
3. Fondation RAG (`wama/rag/`) — débloque hook PromptPipeline + Media Library.
4. Refactoring common app par app (par petites sessions).
