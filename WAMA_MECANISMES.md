# WAMA_MECANISMES.md — Carte des mécanismes transversaux

> **Ce fichier est un INDEX, pas une bible.** Il dit *quels* mécanismes profonds existent, *où*
> ils habitent et *quel document* porte leur intention. Il ne réexplique rien : le **pourquoi**,
> les décisions et les pièges restent dans le document de référence de chaque domaine. Recopier
> ici ce que ces documents disent, c'est fabriquer la redondance que la règle « un domaine = un
> fichier » combat — et c'est exactement ainsi que `docs/PRECISION_MODE.md` en est venu à
> annoncer un seuil de segmentation à 65 quand le code disait 50.

## Pourquoi cette carte existe

Deux documents tracent déjà les **deux bouts du tunnel** : `WAMA_APP_GENERATION_ROUTE.md` (route
d'auto-génération des apps, facettes F1–F8) et `WAMA_MANIFEST_ARCHITECTURE.md` /
`WAMA_MANIFEST_SPEC.md` (manifestes → ingest → registres). Entre les deux vit tout le reste — le
gouverneur de ressources, l'ETA auto-apprenante, l'ingest de source, le pipeline de prompts, la
sauvegarde, les licences, les signaux d'exécution, la sélection et la couverture de modèles.

Ces mécanismes existaient, ils fonctionnaient, et **ils n'étaient recensés nulle part**. Il en
est résulté deux briques mortes découvertes à la main le 2026-08-12 :
`model_coverage.couvrir_classes`, sans aucun consommateur pendant huit jours alors qu'il avait
été extrait pour ça, et `common/utils/qc.py`, sans appelant depuis sa création.

## La table est GÉNÉRÉE — elle ne peut pas dériver

La source est le registre déclaratif **`wama/common/mecanismes.py`**. Le tableau ci-dessous en
est la projection, régénérée par `python manage.py doc_facts` et gardée par
`doc_facts --check` (code de sortie 1 si le bloc est périmé). C'est la doctrine WAMA appliquée à
sa propre documentation : l'affichage se remplit depuis les métadonnées, il ne se saisit pas.

**Ajouter un mécanisme transversal = ajouter une entrée au registre**, pas une ligne ici.

### Ce que la colonne « Consommateurs » signale

Le nombre de fichiers qui **importent** le mécanisme. Il répond à trois questions d'un coup :

| Signal | Lecture |
|---|---|
| `❌ absent` | le domicile déclaré n'existe plus — la carte pointe dans le vide |
| `⚠ 0` | **brique morte**, ou brique livrée et pas encore adoptée. À trancher, jamais à ignorer |
| `n` | nombre de modules qui s'en servent |

Et sous la table, la liste des modules de `common/services/` et `common/utils/` **non rattachés
au registre** — la réponse mécanique à « qu'ai-je oublié de tracer ». Un utilitaire strictement
local peut légitimement y rester : dans ce cas on l'assume, on ne le déclare pas.

---

<!-- WAMA:FAITS(mecanismes) — généré par « python manage.py doc_facts », ne pas éditer -->
| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Accès LLM** | Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local) | `wama/common/utils/llm_utils.py` | — | 12 |
| **Accès ffmpeg** | Résolution centralisée du binaire et des conversions (échappatoire FFMPEG_BINARY) | `wama/common/utils/ffmpeg_utils.py` | — | 14 |
| **Audit des licences** | Vue dérivée : licences+auteurs des 4 registres, traversée par app | `wama/common/services/license_audit.py` | — | 2 |
| **Banc de comparaison** | Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation) | `wama/model_manager/services/bench.py` | — | 1 |
| **Chemins média** | Emplacements canoniques des entrées/sorties par app et par utilisateur | `wama/common/utils/media_paths.py` | — | 20 |
| **Console utilisateur** | Lignes de journal structurées par utilisateur et par app, via Redis | `wama/common/utils/console_utils.py` | — | 24 |
| **Contrôle qualité de sortie** | Note une sortie par un validateur LLM INDÉPENDANT ; signal relatif, escalade humaine | `wama/common/utils/qc.py` | `ROADMAP.md §16.5` | ⚠ **0** |
| **Couverture multi-modèles** | Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation) | `wama/common/services/model_coverage.py` | — | 1 |
| **Divergence inter-systèmes** | Désaccord entre deux sorties du même travail — signal objectif, sans avis de modèle | `wama/common/services/divergence.py` | `wama/transcriber/TRANSCRIBER_CORRECTION.md §8.3` | 1 |
| **Duplication et suppression sûres** | duplicate_instance() et safe_delete_file() — fichiers partagés entre items | `wama/common/utils/queue_duplication.py` | `WAMA_APP_CONVENTIONS.md` | 13 |
| **ETA auto-apprenante** | Estimation de durée par a-priori puis moyenne mobile, bucketisée par matériel | `wama/model_manager/services/eta_estimator.py` | `PROJECT_STATUS.md §10` | 20 |
| **Gardes de process** | Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines | `wama/common/utils/process_control.py` | `PROJECT_STATUS.md §0` | 20 |
| **Gouverneur de ressources** | Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités | `wama/common/services/resource_governor.py` | `PROJECT_STATUS.md §0` | 11 |
| **Grille de conformité** | Mesure les 8 facettes F1–F8 des apps par analyse du code réel | `wama/common/services/conformity_checker.py` | `WAMA_APP_CONVENTIONS.md` | 3 |
| **Import par lot** | Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot | `wama/common/utils/batch_parsers.py` | `BATCH_FORMAT.md` | 15 |
| **Indice de qualité a priori** | Ordonne les modèles autrement que par la taille (paramètres, contexte, quantif.) | `wama/model_manager/services/model_quality.py` | — | 1 |
| **Ingest de source** | Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST | `wama/common/utils/source_ingest.py` | `WAMA_APP_GENERATION_ROUTE.md` | 7 |
| **Inspecteur — champs de détail** | Schéma canonique des infos d'item affichées au volet droit | `wama/common/utils/detail_registry.py` | `INSPECTOR_DETAIL_FIELDS.md` | 16 |
| **Manifestes** | Extraction/validation/projection des 7 kinds vers les registres | `wama/common/manifests/ingest.py` | `WAMA_MANIFEST_ARCHITECTURE.md` | 17 |
| **Notifications de tâche** | notify_job() — fin de traitement, succès comme échec | `wama/common/utils/notifications.py` | `PROFILES_PERMISSIONS.md` | 12 |
| **Pipeline de prompts** | Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS | `wama/common/utils/prompt_enrichment.py` | `PROMPT_PIPELINE.md` | 11 |
| **Prospection de modèles** | Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run) | `wama/model_manager/services/prospector.py` | `wama/model_manager/PROSPECTION_PIPELINE.md` | 3 |
| **Provenance de modèle** | Identité chez l'éditeur (licence, auteur, plateforme), posée VIA le manifeste | `wama/model_manager/services/provenance.py` | — | 4 |
| **Sauvegarde & tirage** | Moteur unique de miroir (modèles, base, médias, secrets) et restauration | `wama/common/services/mirror_sync.py` | — | 8 |
| **Schéma de paramètres** | Source unique des réglages d'app : volet droit et modale sont RENDUS depuis lui | `wama/common/utils/param_schema.py` | `WAMA_APP_GENERATION_ROUTE.md` | 22 |
| **Signaux d'exécution** | Journal append-only des FAITS observés sur un résultat (produit/corrigé/relancé…) | `wama/common/services/run_outcome.py` | `ROADMAP.md §16.7` | 2 |
| **Squelette de tâche** | Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA | `wama/common/utils/task_skeleton.py` | `WAMA_APP_GENERATION_ROUTE.md` | 3 |
| **Sélection de modèle** | Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité | `wama/model_manager/services/model_selector.py` | `INPUT_MODEL_MATCHING.md` | 7 |
| **Visibilité et portée** | Privé / unité / public : filtrage des lectures, mutations inchangées | `wama/common/models.py` | `PROFILES_PERMISSIONS.md` | 139 |
| **Vocabulaire des capacités** | Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI | `wama/common/utils/model_capabilities.py` | `INPUT_MODEL_MATCHING.md` | 1 |

**Mécanismes déclarés : 30** · domiciles absents : 0 · sans consommateur : 1 · modules `common/` non rattachés : 45
- ⚠ **Sans consommateur** (brique morte ou pas encore adoptée) : `qc` (wama/common/utils/qc.py)

<details><summary>⚠ <b>45 module(s) de <code>common/</code> non rattachés au registre</b> — à déclarer dans <code>wama/common/mecanismes.py</code>, ou à assumer comme utilitaires locaux (tout n'est pas un mécanisme transversal)</summary>


`wama/common/services/` (7) — `config_backup.py` · `library_index.py` · `media_backup.py` · `nightly_tests.py` · `retention.py` · `system_monitor.py` · `ui_smoke.py`

`wama/common/utils/` (38) — `app_modes.py` · `audio_decode.py` · `batch_sync.py` · `batch_utils.py` · `card_chips.py` · `disk_utils.py` · `document_export.py` · `feature_flags.py` · `format_policy.py` · `hf_cache.py` · `html_render.py` · `http_proxy.py` · `intervals.py` · `lang_routing.py` · `log_rotation.py` · `media_probe.py` · `mime_utils.py` · `model_locations.py` · `ollama_host.py` · `onnx_utils.py` · `output_formats.py` · `preview_registry.py` · `preview_utils.py` · `prompt_pipeline.py` · `prompt_skills.py` · `queue_manipulation.py` · `queue_view.py` · `reference_comprehension.py` · `safetensors_utils.py` · `scoping.py` · `translator.py` · `url_ingest.py` · `user_settings.py` · `video_compat.py` · `video_utils.py` · `voice_options.py` · `waveform.py` · `whisper_utils.py`

</details>
<!-- /WAMA:FAITS(mecanismes) -->

---

## Documents de référence par domaine

Rappel des domiciles de l'**intention** — la carte pointe vers eux, elle ne les remplace pas.

| Domaine | Document |
|---|---|
| Route d'auto-génération des apps (F1–F8) | `WAMA_APP_GENERATION_ROUTE.md` |
| Manifestes — formalisme / flux | `WAMA_MANIFEST_SPEC.md` · `WAMA_MANIFEST_ARCHITECTURE.md` |
| Conventions d'application | `WAMA_APP_CONVENTIONS.md` |
| Pipeline de prompts | `PROMPT_PIPELINE.md` |
| Appariement entrée ↔ modèle | `INPUT_MODEL_MATCHING.md` |
| Profils, permissions, portée | `PROFILES_PERMISSIONS.md` |
| Prospection de modèles | `wama/model_manager/PROSPECTION_PIPELINE.md` |
| Avancement des chantiers | `PROJECT_STATUS.md` · `ROADMAP.md` |

## Trous connus

Ce que la carte rend visible et qu'il ne faut pas masquer :

- **Des mécanismes sans document de référence** (colonne « Doc » à `—`). Leur intention n'est
  écrite que dans les docstrings et les messages de commit. Ce n'est pas rédhibitoire — un
  docstring exhaustif vaut mieux qu'un `.md` qui dérive — mais ça se sait.
- **Le RAG n'apparaît pas** : il n'est pas implémenté (ROADMAP §8c). Il entrera au registre le
  jour où il aura un domicile, pas avant — déclarer une intention comme un mécanisme rendrait la
  carte menteuse.
- **La couverture de `RunOutcome` est partielle** : deux apps sur dix, celles qui ont adopté le
  squelette de tâche. La carte compte les consommateurs du mécanisme, pas les apps couvertes.
