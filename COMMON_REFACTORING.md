# COMMON_REFACTORING.md — Unification dans `wama/common/`

> **Règle fondamentale (cf. CLAUDE.md) : tout code utilisé par plus d'une app va dans `wama/common/`.
> ZÉRO duplication entre apps.** Ce document recense les briques communes **déjà disponibles**, l'app
> de **référence**, et la **recette d'adoption**. À lire avant de créer/modifier une app.

## App de référence : **Transcriber**
Le Transcriber est la **référence complète** de l'architecture cible : il consomme toutes les briques
communes ci-dessous. Pour généraliser une app, s'en inspirer.

## Briques communes disponibles (à utiliser, NE PAS recréer)

### JavaScript — `wama/common/static/common/js/`
| Fichier | Rôle |
|---------|------|
| `wama-app-base.js` | Namespace `WamaApp` : `escapeHtml`/`getUrl`/`csrfFetch`/`wordCount`, `WamaApp.Poller` (boucle progression résiliente), `WamaApp.emptyState`. **À charger avant l'index.js de l'app.** |
| `wama-inspector.js` | Volet droit (inspecteur) card/batch/file — sélection/clic/highlight/banner — `WamaInspector.init({...})`. |
| `wama-inspector-autofill.js` | **Rendu générique** du volet droit depuis les métadonnées d'un élément + un **schéma déclaratif** — `WamaAutofill.renderSections(data, schema)` / `renderActions(data, actions)`. Couplé à `wama-inspector.js`. CSS : `common/css/wama-inspector-autofill.css`. Premier consommateur : **model_manager**. |
| `wama-model-help.js` | Description du modèle choisi sous un `<select>` — `WamaModelHelp.init({selectId,helpId,meta,fallback})`. |
| `wama-model-caps.js` | Capacités de modèles côté front. |
| `wama-eta.js` | Moteur ETA `WamaEta` (débit observé, 3 niveaux de confiance). |
| `wama-global-progress.js` | Barre de progression globale (dispatch `media:processed`). |
| `wama-queue.js` | File d'attente : collapse batch + persistance localStorage. |
| `wama-audio-player.js`, `wama-params.js`, `wama-fm-notify.js` (`WamaFM`) | Lecteur audio, params, auto-refresh filemanager. |
| `batch-import.js`, `queue-actions.js`, `media-picker.js`, `media-preview.js`, `console.js`, `system-stats.js` | Import batch, actions de file, sélecteur/preview média, console, stats système. |

### Templates — `wama/common/templates/common/`
| Fichier | Rôle |
|---------|------|
| `app_modern_base.html` | **Base d'héritage** (onglets file/console/à-propos/aide + blocs volet). Piloter les spécificités par capacités d'app. |
| `_new_item_card.html` | Card « Nouvel élément » (import fichier/URL/batch, paramétrable). |
| `_card_progress.html` | Badge statut + barre + % + ETA + temps écoulé. |
| `_card_state.html` | États (Traitement…/En attente/Échec/aperçu). |
| `_queue_actions.html` | Barre d'actions globales (Démarrer/Télécharger/Tout effacer). |
| `_global_progress.html` | Barre de progression globale. |
| `_audio_waveform.html`, `batch_detect_bar.html` | Onde audio, barre de détection batch. |

### Python — `wama/common/utils/`
| Fichier | Rôle |
|---------|------|
| `queue_duplication.py` | `duplicate_instance()`, `safe_delete_file()`. |
| `batch_parsers.py` / `batch_common.py` / `batch_utils.py` | Parsing & duplication batch. |
| `console_utils.py` | Logs Redis structurés. |
| `media_paths.py` | `upload_to_user_input/output`. |
| `document_export.py` | Export PDF/DOCX/TXT (voir gotchas fpdf2). |
| `param_schema.py` / `format_policy.py` / `preview_registry.py` | Schéma de params, politique de formats, registre de previews. |
| **PromptPipeline** (`app_metadata.py`, `prompt_pipeline.py`, `lang_routing.py`, `translator.py`, `prompt_enrichment.py`, `reference_comprehension.py`, `qc.py`) | Voir [`PROMPT_PIPELINE.md`](PROMPT_PIPELINE.md). |
| `llm_utils.py` | `llm_chat()` (Ollama/LiteLLM). |

## Recette d'adoption d'une app (vers la référence Transcriber)
1. Charger les scripts communs **avant** l'`index.js` de l'app (`wama-app-base.js` en premier).
2. Hériter de `app_modern_base.html` ; inclure les partials (`_new_item_card`, `_card_progress`,
   `_card_state`, `_queue_actions`) avec des **IDs propres à l'app** (handlers JS inchangés).
3. `WamaInspector.init({...})` pour le volet droit ; `WamaModelHelp.init({...})` pour la description modèle.
4. **Aligner modale ↔ volet** (mêmes paramètres + libellés).
5. Utiliser `WamaApp.Poller`, `csrfFetch`, `getUrl`, `escapeHtml` (pas de réimplémentation locale).
6. Duplication/suppression via `queue_duplication.py` ; import batch via `batch-import.js` + `batch_parsers.py`.

## Décisions prises (ne pas re-tenter)
- **PAS de partial unique de champs de réglages modale↔volet** : ~25 différences réelles → plus de
  couplage que de bénéfice. Garantie pragmatique = jeu de params aligné + libellés harmonisés.
- **PAS d'eager-import** de gros modules au démarrage (rebloque le boot ~27 s).
- Héritage générique piloté par **capacités d'app** (`has_realtime`, `instant_preview`, `has_edit_page`…)
  plutôt que par duplication de templates.

## À faire (roadmap refactoring)
- `common/utils/backend_selector.py` — sélection VRAM + règle singleton `keep_loaded` (à centraliser).
- Adoption des briques **app par app** (converter, describer, enhancer, imager, reader, synthesizer,
  anonymizer, composer) en suivant la recette ci-dessus, sans casser les spécificités.

## Voir aussi
- `WAMA_APP_CONVENTIONS.md` — conventions UI & checklist de création d'app.
- `CARD_CENTRIC_UI.md` — volet droit = inspecteur.
- `PROMPT_PIPELINE.md` — pipeline de prompts commune.
- `ROADMAP.md §16.6` — vision méta (cards > assistant > scaffold > méta-app).
