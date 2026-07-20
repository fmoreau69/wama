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
