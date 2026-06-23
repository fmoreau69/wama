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
- ⏳ **UI volet droit (PRIORITAIRE — bloque le test prospection via `/model-manager/`)** : inspecteur par-modèle (`WamaInspector` + `AIModel.to_dict()`) + dashboard prospection par défaut (gardé admin)
- ⏳ Étape 3 centralisation (adaptateurs anonymizer/transcriber + migration per-model)
- ⏳ Chargeur générique ; agents cloud pour confronter ; recherche web benchmarks

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
