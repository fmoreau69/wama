# TRANSCRIBER_REFERENCE_AUDIT.md — l'app de référence décortiquée

> **But** : Transcriber « a presque tout » (Fabien). Ce document inventorie EXHAUSTIVEMENT ses
> mécanismes (audit empirique 2026-07-02 : 46 endpoints, 1646 lignes JS, 3 templates) pour que
> tout portage soit **complet par construction** — la §6 est LA checklist de fin d'app.
> Compagnon de `wama/common/README.md` (le workflow) — ici : l'INSTANCE de référence.

---

## 1. Surfaces & génération (le squelette)

| Surface | Comment | Générée ? |
|---|---|---|
| Card d'entrée | `common/_new_item_card.html` (upload+URL/YouTube+batch+médiathèque audio+**Speak** `show_live`) | ✅ brique commune |
| File | file unique, **batch unifié** (`_wrap_transcript_in_batch`, `_auto_wrap_orphans` : tout est batch, batch-de-1 rendu simple) | pattern serveur |
| Cards | rendu serveur + **update JS en place** (pas de rebuild), délégation `data-action` | partial + JS |
| Modale ⚙ (item+batch) | champs `WamaParams.render(context:'item')` depuis `params.py` ; pied trio conforme | ✅ générée |
| Volet inspecteur | champs `WamaParams.render(context:'panel')` + câblage `WamaInspector` | ✅ générée |
| Modes | `APP_MODES` déclaré (normal/realtime) ; Speak = affordance card (`show_live`), pas un switch | déclaré |
| Page ÉDITEUR dédiée | `edit.html` (correction assistée : onde audio, segments, heatmap) | bespoke sur briques |

## 2. Inventaire des MÉCANISMES (46 endpoints groupés)

### Entrée & file
- **Upload** (fichier/drag&drop/URL/YouTube/médiathèque) + **batch** (preview→create→start, template
  téléchargeable `batch_template`) + **Speak temps réel** (`save_realtime`).
- **Batch unifié** : `_wrap_transcript_in_batch` (tout ajout = batch-de-1), `_auto_wrap_orphans`
  (migration lazy au chargement), rendu batch-de-1 = card simple.
- **Manipulation directe** (brique à généraliser !) : `reorder` (réordonner), `move_to_batch` /
  `remove_from_batch` (glisser dans/hors batch), `consolidate` (fusionner en batch).
- **Héritage batch→item** (`batch_update_settings`, conventions §9.9) : l'item hérite du batch
  SAUF ses params modifiés — vues l.1869.

### Card & cycle de vie
- Boutons ordre conforme ⚙▶⬇⧉🗑 ; **bouton cycle** ▶/⏹/↻ (vert, anti-race `select_for_update`
  + revoke Celery — pattern CLAUDE.md) ; `duplicate` (via brique commune) ; `delete`
  (`safe_delete_file`) ; `clear_all`, `download_all`, `batch_download` (ZIP).
- **Progression** : `progress` + `batch_status` + `global_progress` (barre commune) ; **ETA**
  `WamaEta` + seeding hardware-aware (`eta_estimator`, stat `transcriber:whisper`).
- **Aperçu sortie** systématique (texte tronqué, clic = étendu).

### Traitement (spécifique déclaré, pas dispersé)
- **Backends** : `get_backends` (auto/whisper/vibevoice/qwen + `description/description_long/
  supports_*/recommended_vram_gb` = source des méta) ; sélection auto VRAM-aware.
- **Préprocessing audio** : `set_preprocessing`/`toggle_preprocessing`/`preprocessing_status`.
- **Diarisation** (native vibevoice / pyannote), `_backfill_speakers`, `suggest_speakers` (IA),
  `_describe_audio`.
- **Post-traitement LLM** : `enrich` (résumé/cohérence). Pilier prompts : rien par app.

### Sorties
- **Export LATE-binding multi-format** (`download` txt/srt/vtt/json, `download_srt`,
  `_build_transcript_bytes`/`_srt_ts` : le master est stocké, le format se choisit AU
  téléchargement) ; `save_meta` (titre/locuteurs).

### Éditeur dédié (`edit.html` — bespoke LÉGITIME sur briques)
- `edit` (page), `get_segments`/`_editor_segments`, `waveform_peaks` (`_audio_waveform.html`),
  `save_correction`, `_rebuild_segments_from`. Intégré comme **capacité** (bouton Éditer).

### Réglages & aide
- `get/save_user_transcriber_settings` (défauts user), profils ; `console_content` (brique
  console commune) ; `HelpView`/`AboutView` ; `tool_api.py` (assistant/méta-app).

## 3. Briques communes consommées (vérifié — les 8 scripts + partials)
`wama-app-base.js` (**Poller** + `getUrl` + insertion de cards — la base inter-apps !) ·
`wama-params` · `wama-inspector` · `wama-modes` · `wama-model-help` · `wama-eta` ·
`wama-global-progress` · `media-picker` (global) — et partials : `_new_item_card`,
`batch_detect_bar`, `_global_progress`, `_inspector_banner/_actions`, `_audio_waveform`,
`_settings_modal_footer` (à adopter), `_cycle_button`, `_card_progress/_card_state`.

## 4. Spécifique LÉGITIME (déclaré, pas à généraliser)
Éditeur de correction (page dédiée) · préprocessing audio · Speak temps réel · diarisation/locuteurs.
→ le reste (~90 %) est du PATTERN à répliquer.

## 5. Trous de généralisation détectés par cet audit (à tracer)
- **Manipulation directe** (`reorder`/`move_to_batch`/`remove_from_batch`/`consolidate`) : implémentée
  transcriber-only → brique commune à extraire (déjà noté CARD_DESIGN §3bis).
- **Héritage batch→item** : logique transcriber-only (l.1869) → à centraliser (mémoire §9.9).
- **Batch unifié** (`_wrap_*`/`_auto_wrap_orphans`) : pattern dupliqué synthesizer — à briquer.
- **Câblage drop/clic de `_new_item_card`** : chaque app réécrit ~14 lignes → candidat
  `wama-new-item-card.js` commun.

## 6. CHECKLIST DE FIN D'APP (une app est « finie » quand chaque ligne est ✓ ou N/A justifié)

| # | Mécanisme | Brique/pattern |
|---|---|---|
| 1 | Card d'entrée commune (+batch, +médiathèque, +URL si pertinent) | `_new_item_card` |
| 2 | Batch unifié + héritage batch→item | pattern `_wrap_*` §9.9 |
| 3 | Cards : data-action, 2 états, aperçu sortie, boutons conformes | CARD_DESIGN |
| 4 | Bouton cycle ▶/⏹/↻ + start anti-race | `_cycle_button` + pattern Celery |
| 5 | Progression card+batch+globale + ETA | `wama-eta`, `_global_progress`, seeding |
| 6 | Modale = champs générés + pied commun + flag `restart` | WamaParams + `_settings_modal_footer` |
| 7 | Volet = champs générés + câblage initFromSchema | WamaParams(panel) + WamaInspector |
| 8 | Une SEULE source params (params.py, dom_id bridge) | `param_schema` |
| 9 | Descriptif modèle courte+ⓘ longue depuis le CATALOGUE | WamaModelHelp + AIModel |
| 10 | Capacités modèle → UI (options/champs) | WamaModelCaps + capabilities canoniques |
| 11 | Modes/domaines déclarés (si comportement diverge) | APP_MODES + WamaModes |
| 12 | Duplicate/delete sûrs, clear_all, download_all | `queue_duplication` |
| 13 | Export multi-format (late si master, early sinon) | `output_format_params_for_app` |
| 14 | Réglages user persistés (get/save) + profils si déclaré | pattern settings |
| 15 | Console + aide/à-propos | `console.js`, HelpView |
| 16 | Connexion assistant/méta-app dans le registre CENTRAL `wama/tool_api.py` (TOOL_REGISTRY — pas de fichier par app) + `PROMPT_TARGETS` si prompts | A4/A5 |
| 17 | Conformité `/apps/` mise à jour (flags = réalité) | app_registry |
| 18 | Manipulation directe file (quand briquée) | §5 ci-dessus |
| 19 | Appariement entrées⇄modèles (si entrées différenciantes : référence, etc.) | `WamaInputMatch` + `capabilities.inputs_*` + slot `show_reference` |
