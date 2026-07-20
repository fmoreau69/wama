# ROADMAP_ARCHIVE_2026-07-20 — sections actées retirées de ROADMAP.md

> Dédoublonnage du 2026-07-20 (audit doc 2026-07-09). Chaque bloc = contenu retiré
> tel quel, avec sa provenance. État vivant : PROJECT_STATUS.md.

---

## §0 Dysfonctionnements connus (corps intégral)


| Composant | Symptôme | Statut | Piste |
|-----------|----------|--------|-------|
| **Qwen3-ASR** (Transcriber) | Backend implémenté (`qwen_asr_backend.py`) mais non fonctionnel — erreurs de dépendances à l'import | 🐛 Bloqué | Résoudre conflits deps pip (transformers, torchaudio, accelerate) |
| **Higgs Audio V2** (Synthesizer) | Audio généré inaudible, artefacts, bruits de fond — modèle inutilisable | 🐛 Bloqué | Nombreux patches appliqués + CUDA graphs désactivés (voir memory/). Prochaine étape : test sans voice reference pour isoler |
| **Prétraitement audio** (Transcriber) | L'ancien pipeline (pydub + `noisereduce`/spectral-gating) dégradait l'ASR | ✅ Corrigé | Remplacé par débruitage IA **DeepFilterNet** (singleton keep_loaded partagé avec l'enhancer) + format ASR 16k mono. Optionnel, défaut OFF (Whisper robuste au bruit). Resemble Enhance possible en option « restauration » (générative, peut altérer l'ASR) — non câblé |

---


---

## §3 Media Library (corps intégral — Phases 1-4 ✅)


### Phase 1 ✅ (2026-03-17)
- UserAsset, SystemAsset, page `/media-library/`, migration CustomVoice, intégration synthesizer

### Phase 2 ✅ (2026-03-17)
- Recherche/filtrage tags, pagination, preview modal, métadonnées éditables inline

### Phase 3+4 ✅ (2026-03-17)
- MediaProvider + UserProviderConfig, BaseProvider, connecteurs Wikimedia/Pixabay/Freesound
- Vue proxy `api_provider_search` + `api_provider_download` (clés jamais exposées en JS)

### Phase 5 — Connecteurs avancés ⏳
- Pexels, Unsplash, Openverse, ccMixter (musique CC)
- Mozilla Data Collective (voix, si API stable)

### Phase 6 — Intégration cross-apps ⏳
- Imager : sélecteur image de style depuis médiathèque
- Avatarizer : sélecteur portrait de référence
- Synthesizer : déjà fait ✅

---


---

## §4 Intégration Ollama (corps intégral — ✅)


### 4.1 qwen3-coder:30b (MoE 3.3B actifs, 256K ctx, 19GB) ✅ (2026-04-07)
- Remplace `deepseek-coder-v2:16b` dans wama-dev-ai (rôle `debug`) et `wama/views.py`
- `wama-dev-ai/config.py` : entrée debug mise à jour (context_length 262144, ram 19GB)
- `wama/views.py` : rôle debug + _MODEL_SAFE_CHARS mis à jour (512K chars = 128K tokens)

### 4.2 qwen3-vl:8b — backend vision Ollama pour Describer ✅ (2026-04-14)
- Cascade Ollama vision : qwen3-vl:8b > qwen3-vl > moondream2 > moondream > BLIP (local HF)
- Implémenté dans `wama/describer/utils/image_describer.py`
- `/api/chat` primary, `/api/generate` fallback pour moondream ancien
- Auto-détection des modèles disponibles, cache par worker process

### 4.3 glm-ocr:0.9b — backend OCR léger via Ollama ✅ (2026-04-14)
- Implémenté dans `wama/reader/backends/glm_ocr_backend.py`
- Cascade auto : olmOCR singleton > GLM-OCR (Ollama) > olmOCR-7B (VRAM) > docTR
- Gère PDF multi-pages (PyMuPDF → PNG temp) + images directes
- Migration `0006_alter_readingitem_backend.py` appliquée
- `ollama pull glm-ocr`

---


---

## §8d Phase 1 — Couche d'abstraction locale LiteLLM ✅ (2026-04-14)


- `llm_chat()` dans `wama/common/utils/llm_utils.py` — point d'entrée unifié
- `LITELLM_PROVIDER = 'ollama'` dans settings.py (défaut, aucun appel cloud)
- `ollama_chat()` conservée telle quelle — zéro breaking change pour les appelants existants
- `litellm` installé : `pip install litellm`


---

## §9.1 cam_analyzer (corps intégral — ✅)

| Composant | Statut | Fichier |
|-----------|--------|---------|
| `rtmaps_parser.py` | ✅ | `wama_lab/cam_analyzer/utils/` |
| `quadrature_video.py` | ✅ | `wama_lab/cam_analyzer/utils/` |
| `intersection_analyzer.py` | ✅ | `wama_lab/cam_analyzer/utils/` |
| Modèles DB (`intersections`, `source_type`, `gps_track`) | ✅ | `cam_analyzer/models.py` + migration |
| Tâche `extract_rtmaps_task` | ✅ | `cam_analyzer/tasks.py` |
| `_detect_intersection_insertion()` | ✅ | `cam_analyzer/tasks.py` |
| Vue `upload_rtmaps` + `rtmaps_status` | ✅ | `cam_analyzer/views.py` |
| UI : section RTMaps + intersections dans profil modal | ✅ | `cam_analyzer/index.html` + JS |


---

## §9.2 cam_analyzer — lignes de table livrées ✅

| **1** | YOLOPv2 backend (`yolopv2_segmenter.py`), dispatcher dans `tasks.py`, validation thresholds | ✅ (2026-05-07) |
| **2** | Lane attribution : partition drivable→voies via lane lines, voie navette = bottom-center, attribution `lane_id` par détection (foot point) | ✅ (2026-05-07) |
| **3** | `LaneEvent` model (track_id, intersection_window_idx, t_enter, t_exit, lane_id) + computer post-loop + migration | ✅ (2026-05-07) |
| **4** | Distance/vitesse/TTC : pinhole + références normalisées (hauteur véhicule par classe, hauteur piéton 1.7m, FoV par caméra) ; persistés sur chaque détection (`distance_m`, `relative_speed_kmh`, `ttc_s`). Homographie sol auto-calibrée à reporter (Phase 4.bis si Phase 4 trop bruitée) | ✅ (2026-05-07) |
| **5** | `ConflictEvent` model (track_id, intersection_window, conflict_type, navette_passed_first, delta_t, min_distance, min_ttc, severity) + computer `_compute_conflict_events` qui croise LaneEvent (in_shuttle_lane=True) × intersection_window × distance/TTC | ✅ (2026-05-07) |
| **6** | UI : marqueur 🚌 sur détections in_shuttle_lane + bbox épaissie ; affichage distance/vitesse/TTC dans le label ; export CSV étendu (`type`, `lane_id`, `in_shuttle_lane`, `distance_m`, `relative_speed_kmh`, `ttc_s`) ; export JSON `lane_events`+`conflict_events`+`intersection_windows` ; nouvel export `Conflits (CSV)` trié par sévérité | ✅ (2026-05-07) |

---

## §1.2 Features transversales — lignes livrées ✅

| ETA (barre de progression) | ✅ | Carte + globale + batch — toutes les apps (moteur commun `WamaEta`) |
| Auto-refresh filemanager (ajout input + sortie + suppression) | ✅ | **Commun** : `WamaFM` (`media:uploaded`/`processed`/`deleted`) + poll mtime non bloquant. **Triggers instantanés posés sur TOUTES les apps** (audit conventions §8). |
| Consolidation import multi-fichiers → batch | ✅ | converter, reader, transcriber, describer, enhancer, **anonymizer** (+ DnD filemanager multi-fichiers) ; composer/synthesizer = N/A (pas d'import média) |
| Mode batch anonymizer (groupes + consolidation) | ✅ | Modèles existants + `consolidate`/`_auto_wrap_orphans` + rendu groupé `media_table.html` + suppr. batch. Traitement reste global (pas de start par-batch) |
| Download All (ZIP) | ✅ | Composer |
| Drag & drop zone | ✅ | Imager (prompt image, style ref, img2vid, description) |
| Parité batch UI (⚙ batch + ⚙/⧉ par item + duplication in-batch) | ✅ | **Terminée** : transcriber, reader, synthesizer, describer, composer, enhancer, converter, anonymizer (⚙ batch = global). Group-by-nature commun (converter/describer/enhancer/anonymizer). Cf. conventions §9.8/§9.9. |
| **Phase B — Format batch unifié à balises** (`-i/-p/-r/-o`) | ✅ | Parseur commun `parse_unified_batch` + détection legacy + **`BATCH_FORMAT.md`**. **Câblé partout** : apps Type A (reader/describer/transcriber/converter/anonymizer/enhancer) via `parse_media_list_batch` rendu balise-aware (`-i`→path, `-o/-p/--opt` transportés) ; **imager** (`-p`→prompt, `--steps/--cfg/--model/--np`…) ; **synthesizer** (`-p`→texte, `--voice/--speed/-r/--language`) ; **composer** (réf. : auto-modèle musicgen-melody si `-r`) ; **avatarizer** (nouveau système de lots `BatchAvatarJob` + import par fichier balise + group-by-nature pipeline/standalone + UI groupes ▶/⬇/⧉/🗑). **Variante CSV à en-têtes** ✅ (centralisée : `is_csv_header_batch`/`parse_csv_header_batch`, gérée par `parse_unified_batch`/`parse_media_list_batch` → toutes les apps). Virgules dans une cellule gérées via guillemets (`csv.DictReader`). |
| Duplication d'un élément = DANS le batch (fix) | ✅ | Synthesizer + Transcriber (était hors groupe = bug) |
| **Architecture UI « card-centric »** (card auto-suffisante + volet droit = inspecteur) | 🔶 Décidée | **Décision projet 2026-06** : voir **`CARD_CENTRIC_UI.md`** (spec + phases). Card de composition (dépôt/prompt/référence/RAG par card), volet droit reflète la sélection, 1 source (filemanager) + 1 destination (card) par app, RAG ponctuel isolé par card, modales conservées puis rationalisées. Bâtit sur le staging. Multi-drop→1 batch ✅ corrigé partout (dont enhancer audio). **Preview à 3 niveaux** (§5bis) : composant commun `.wama-card-preview` (double-clic → `wama:card-expand` ; apps média → overlay `unified_preview`) ✅ livré, **1ᵉʳ consommateur transcriber** (preview compacte + métriques sous la barre, bouton œil retiré, double-clic → modal résultat). **Niveau 2 (volet = inspecteur)** ✅ pilote transcriber (clic card → volet édite l'élément ; `[×]` revient aux défauts). Reste : preview complète dans le volet, sélection en-têtes batch, généralisation. WAMA Lab non impacté (composants communs additifs). |

---

## §1.1 Bouton Dupliquer — table figée (toutes apps ✅)

### 1.1 Bouton Dupliquer
| App | Statut | Notes |
|-----|--------|-------|
| Transcriber | ✅ | views.py + urls.py + template + JS |
| Synthesizer | ✅ | single + batch |
| Reader | ✅ | |
| Composer | ✅ | |
| Anonymizer | ✅ | |
| Describer | ✅ | |
| Imager | ✅ | |
| Enhancer | ✅ | image + audio (single + batch) |


---

## §2 — bloc « état des mécanismes 2026-07-11 » (doublon PROJECT_STATUS §20)

- Modale item : `WamaParams.render(item)` = **7/10** (transcriber, converter, reader, describer,
  enhancer, composer, avatarizer — audit empirique 2026-07-11) ; hand-built restants =
  synthesizer (params.py ne ponte que les dom_id), anonymizer, imager (params.py orphelins).
- Volet : `WamaParams.render(panel)` (référence) vs `WamaInspector.initFromSchema` (synthesizer,
  avatarizer, composer, enhancer) — **à trancher**.
- `params.py` : **10/10 EXISTENT** (audit 2026-07-11) — mais anonymizer/imager ORPHELINS (aucun consommateur).
- Capacités→UI : `WamaModelCaps` (option-level) — **transcriber ne l'utilise pas**, enhancer a du
  `show_if` **hardcodé** à supprimer. Manque le **niveau-champ**. Modèles déclarent leurs params via
  `capabilities.params` (route existante ; moteurs audio enhancer enregistrés le 2026-07-01).
- ⏳ **TÂCHE 1 avant tout portage** : produire `UI_MECHANISMS_CONSOLIDATION.md` (mécanisme|apps|
  référence|à déprécier par axe + plan de convergence). Spec : `memory/project_ui_mechanisms_consolidation.md`,
  suivi PROJECT_STATUS §20. Contraintes : route existante, zéro réinvention, zéro hardcoding.

---

## §2 — table briques communes : lignes livrées ✅

| `wama-eta.js` — moteur ETA commun | ✅ | `common/static/common/js/wama-eta.js` | Toutes les apps (carte/batch/globale) |
| `wama-global-progress.js` + `_global_progress.html` — barre globale | ✅ | `common/…` | converter, avatarizer (autres = barre maison) |
| `wama-fm-notify.js` — notify filemanager (`WamaFM`) | ✅ | `common/static/common/js/wama-fm-notify.js` | Auto-refresh homogène, toutes les apps |
| `batch_common.py` — consolidation import multi-fichiers | ✅ | `common/utils/batch_common.py` | converter, reader, transcriber, describer, enhancer |
| sélection VRAM-aware centralisée | ✅ | `model_manager/services/model_selector.py` | cf. §5b (PAS dans common : model_manager=source de vérité) |
| `wama-app-base.js` — JS inter-apps (Poller, csrf/url, emptyState) | ✅ | `common/static/common/js/wama-app-base.js` | Transcriber rebranché ; à adopter par les autres |
| `audio_decode.py` — décodage multi-format (PyAV/ffmpeg) | ✅ | `common/utils/audio_decode.py` | torchcodec cassé ; à faire converger voice_utils/enhancer/preprocessor |
| `wama-inspector.js`, `wama-model-help.js` | ✅ | `common/static/common/js/` | Volet inspecteur + descriptif modèle (court/long) |
| Briques card : `_card_progress`, `_card_state`, `_new_item_card`, `_queue_actions` | ✅ | `common/templates/common/` | Assemblées par app (pas de card monolithique) |

---

## §15 Méta-app Pipeline — spec d'origine (2026-06-17, réalisée = Studio)


> Idée 2026-06-17. ComfyUI-like **très simplifié**, orienté utilisateur. Dépend de §14.

Chaque app WAMA = une **card** avec tous ses paramètres (générés depuis sa métadonnée §14).
L'utilisateur glisse des **cards d'entrée** typées (`travail` = fichiers/prompts → batch 1/N,
`contexte` = RAG, `référence` = voix/photo…, + médiathèque/URL), les **chaîne** vers les
entrées compatibles d'une card d'app (**vérif systématique compat I/O**), paramètre, puis
chaîne la sortie vers une autre app (ex. synthesizer → avatarizer) ou un dossier/URL de sortie.
Sauvegarde de la chaîne ; à réfléchir : appliquer une chaîne à une file (batch).
- **C'est le frère VISUEL de l'agent** : tous deux orchestrent les apps via la même méta + tool API.
  La méta-app pourrait **simplifier le chaînage multi-apps de l'AI-Assistant** (abstraction « graphe »).
- **Ne PAS coder le canvas from scratch** : réutiliser une lib de node-graph (React Flow /
  Rete.js / LiteGraph.js / Drawflow).
- **Prérequis dur** : le **contrat de types I/O** des apps (audio/image/vidéo/texte-prompt/
  référence:voix/contexte:rag…) — à définir dans `WAMA_APP_CONVENTIONS.md`.

