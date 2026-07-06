# Audit route commune — anti-réinvention + tour des généralistes + manifeste→app (2026-07-06)

> Audit en 3 volets demandé par Fabien après le port à 100 % de Transcriber/Describer/Composer :
> (1) pas de roues réinventées / fonctions concurrentes dans `common/` ; (2) tour des 7 autres
> généralistes (réinventions locales + features à remonter) ; (3) cohérence de LA route unique
> manifeste→app (hors backends modèles). 3 agents read-only + contre-vérifications Claude.
> Les erreurs d'agents détectées sont consignées en §4 (à relire avant de citer ce doc).

---

## 1. VOLET COMMON — verdict : SAIN, 1 doublon critique (corrigé ce jour)

**Doublon critique ffmpeg/ffprobe — CORRIGÉ 2026-07-06** : 3 résolutions concurrentes du binaire.
La brique canonique est `common/utils/ffmpeg_utils.py` (`get_ffmpeg_exe`/`get_ffprobe_exe` :
sélection **WSL2-vs-Windows avec test fonctionnel** + fallback imageio + escape hatch
`FFMPEG_BINARY`). Avaient échappé à la centralisation :
- `video_utils._get_ffmpeg_path`/`get_ffprobe_path` (listes de chemins naïves, pouvaient rendre
  un `.exe` Windows non testé sous WSL2) → **délèguent désormais à ffmpeg_utils** ; les backends
  converter (audio/video_backend) sont corrigés par transitivité ;
- `transcriber/utils/waveform.py::_get_ffmpeg_path` (copie) → **délègue** ;
- `converter/backends/audio_backend.py::_probe_audio_duration` (ffprobe via shutil.which seul)
  → **passe par `media_probe.probe_audio`**.

**Le reste est sans concurrence** (vérifié) :
- Batch : `batch_common` (orchestration) / `batch_sync` (signaux total) / `batch_parsers`
  (parsing fichiers) / `batch_utils` (helpers résiduels spécifiques synthesizer → à résorber
  au port synthesizer) — responsabilités nettes.
- Queue : `queue_duplication` / `queue_manipulation` / `queue_view` — distincts.
- JS : `wama-app-base` (plomberie) / `wama-params` (champs ÉDITABLES) /
  `wama-inspector-autofill` = WamaDetails (READ-ONLY) / `wama-inspector` (sélection volet) /
  `wama-queue` / `batch-import` / `media-picker` — pas de chevauchement.
- Templates : `_card_progress` ≠ `_card_state` ≠ `_batch_card` ≠ `_new_item_card` ≠
  `_queue_toolbar` (qui inclut `_queue_actions`) — OK.
- Nommage : `data-id` (item) vs `data-batch-id` (batch) cohérent ; convention `fk_name` unifiée.

---

## 2. VOLET 7 GÉNÉRALISTES — réinventions + features à remonter

### 2a. Réinventions locales (toutes à remplacer par les briques du port T/D/C)

Les **7 apps ont chacune leurs wrappers batch locaux** (`_wrap_*_in_batch` + `_auto_wrap_orphans`,
~150 lignes dupliquées par app) → `batch_common.wrap_in_batch`/`auto_wrap_orphans`.
**Aucune n'a la manipulation directe** (reorder/move_to_batch/remove_from_batch/consolidate)
→ fabrique `queue_manipulation.make_queue_manipulation_views` (1 bloc + 4 routes).
Localisation des wrappers : reader views:92-110 · converter views:57-80 · enhancer views:26-60
(+ variante audio 122-143, DOUBLE wrapper interne) · anonymizer views:665-700 ·
synthesizer views:50-109 · avatarizer views:463-489 · imager (batch absent by design, à trancher).
Autres réinventions notées : voix/presets synthesizer et avatarizer hardcodés alors que
`common/tts/constants.py` existe ; reader batch template local (→ `build_batch_template`).

### 2b. État réel des briques (tableau d'agent CORRIGÉ après contre-vérif)

| App | new_item_card | toolbar | card+card_html | cycle | batch unifié | modale WamaParams | inspecteur | anti-race | manip. directe |
|---|---|---|---|---|---|---|---|---|---|
| reader | ❌ | ⚠️ | ❌ | ❌ | ❌ | ⚠️ | ✅ | ⚠️ inline (views:237) | ❌ |
| converter | ❌ | ⚠️ | ⚠️ (_job_card réf) | ✅ | ❌ | ⚠️ | ✅ | ⚠️ inline ×3 (226/477/648) | ❌ |
| enhancer | ❌ | ⚠️ | ❌ | ❌ | ❌ | ✅ (porté 07-01) | ❌ | ❌ | ❌ |
| anonymizer | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ (pas de RUNNING explicite, views~1548) | ❌ |
| synthesizer | ❌ | ⚠️ | ⚠️ | ✅ | ❌ | ⚠️ | ✅ | ❌ | ❌ |
| imager | ❌ | ⚠️ | ❌ | ❌ | ❌ (by design ?) | ❌ | ❌ | ❌ | ❌ |
| avatarizer | ❌ | ⚠️ | ❌ | ❌ | ❌ | ⚠️ | ✅ | ❌ | ❌ |

Corrections vs rapport d'agent : `_new_item_card` n'est incluse par **AUCUNE** des 7 (seulement
T/D/C — l'agent avait mis ✅*) ; reader/converter ont déjà l'anti-race **inline** (pattern présent,
à basculer sur `begin_processing` — l'agent avait mis ❌).

### 2c. Features candidates à REMONTER en commun (à valider par Fabien)

| Brique candidate | Origine | Consommateurs potentiels | Effort |
|---|---|---|---|
| **Profils/presets nommés** (save/load/delete de jeux de réglages) | converter `ConversionProfile` | synthesizer, enhancer, imager, anonymizer — rejoint `supports_profiles` du MANIFESTE (project_process_button_lifecycle) | MOYEN |
| **Voice cloning + presets TTS** | synthesizer (`voice_reference`) | avatarizer (même moteur !), reader (lecture audio) ; `common/tts/constants.py` existe déjà — finir la centralisation | MOYEN |
| **Comparaison A/B avant/après** (blend) | enhancer | anonymizer (preview flou), imager, converter. **Précision Fabien 2026-07-06** : le calcul (blend_factor) existe peut-être, mais PAS l'UI de **preview comparative avec SLIDER sur l'image** — c'est CETTE UI qui est la brique à prévoir | BAS |
| **Presets détection** (YOLO classes + SAM3) | anonymizer | avatarizer (visages), imager | BAS |
| **Seeds reproductibilité** | imager | composer, synthesizer | BAS |
| **Galerie de sélection** (source avatar) | imager/avatarizer | synthesizer (voix), reader (templates) | MOYEN |
| **Pipeline multi-étapes** (TTS→MuseTalk→CodeFormer) | avatarizer | = cas d'école MÉTA-APP/studio, PAS une brique d'app. **DÉCISION Fabien 2026-07-06** : le mode pipeline d'avatarizer reste EN L'ÉTAT pour le moment ; à terme le studio chaîne **Synthesizer → Avatarizer** (on ne multiplie PAS les modes dans les apps — cohérent avec les 3 axes de MODES_QUEUE_UX : workflow = méta-app) | — |
| **Export vers médiathèque** | composer (`export_to_library`) | dès la 2ᵉ app consommatrice (B5-20) | BAS |

### 2d. Ordre de portage — divergence à trancher

- **Décision actée (07-05/07-06)** : **Reader d'abord** (jumeau describer, port le moins cher,
  valide la recette une 4ᵉ fois).
- **Proposition de l'agent** (pilotée par la valeur des patterns à remonter) : Converter →
  Synthesizer → Anonymizer (profils, voix/TTS, presets détection remontent tôt en commun).
- Position Claude : garder **Reader** (décision + petit lot), mais **remonter les presets/profils
  en brique commune AU MOMENT du port Converter** (2ᵉ de la liste actée) — les deux logiques
  convergent dès la 2ᵉ app.

---

## 3. VOLET ROUTE MANIFESTE→APP — maillon par maillon

État : **~70-80 % déclaratif**. Chaque maillon a UNE voie canonique (aucun mécanisme concurrent
de conception) ; les écarts sont des apps pas encore migrées + des conventions non pilotantes.

| # | Maillon | Voie canonique | Écarts/concurrents restants | Trous pour l'auto-génération |
|---|---|---|---|---|
| 1 | Identité/catalogue | `app_registry.APP_CATALOG` (consommé : nav, /apps/, studio ports, filemanager) | aucun | `edit_page` non déclaré (capacité prévue par MODES_QUEUE_UX §7) ; **pas de contrat d'URLs** (start/stop/progress/card_html/download divergent par app) |
| 2 | Domaines/modes | `app_modes.APP_MODES` + wama-modes.js | switches codés en dur dans les apps non portées | schéma vide non auto-généré ; show_if simple |
| 3 | Paramètres | `params.py` (PARAMS_JSON) + `param_schema.py` + WamaParams (item/panel) + pied commun | modales hand-built des 7 apps (LE gap, cf. project_manifest_generation_priority) | pas d'introspection modèle Django→schéma ; pas de validation client (min/max/pattern) ; show_if sans AND/OR |
| 4 | Capacités modèle→UI | `AIModel.capabilities` + wama-model-help (catalogue db) + wama-input-match | show_if par modèle hardcodé dans imager | select modèles non généré depuis le catalogue filtré par type |
| 5 | File/batch | BatchMixin + batch_sync + `_new_item_card` + `_queue_toolbar` + `_batch_card` + card partial d'app + card_html + queue_manipulation | 7 apps sur leurs wrappers locaux (cf. §2a) | modèle batch ORM par app non scaffoldé ; card partial d'app = seul HTML restant par app (voulu) |
| 6 | Cycle de vie | `process_control.begin_processing`/`stop_instance` + `_cycle_button` | consommé T/C/D (describer basculé CE JOUR — son inline a été promu brique) ; reader/converter inline ; anonymizer sans statut RUNNING explicite | pas d'enum statuts centralisée (vocabulaires DONE/COMPLETED/ERROR tolérés par les briques mais dispersés) |
| 7 | Progression/ETA | `_card_progress`/`_global_progress` + wama-eta + `eta_estimator` (ModelRuntimeStat, phase 1 faite) | endpoints progress non uniformes (imager `/api/generation-status/`) | seeding ETA branché transcriber/describer/composer seulement ; registre d'algos à formaliser (phase 2 = pilote) |
| 8 | Sorties/export | `output_formats.py` + `export_binding` early/late + document_export | RAS | validation output_types↔formats convertisseur absente |
| 9 | Assistant/méta-app | `wama/tool_api.py` TOOL_REGISTRY (central) + `PROMPT_TARGETS` | RAS (registre central, vérifié) | pas de décorateur `@expose_tool` (enregistrement manuel) ; PROMPT_TARGETS = 5 apps (les absences sont majoritairement DES CHOIX — describer prompt interne, transcriber sans prompt) |
| 10 | Génération | `wama/common/README.md` = workflow PRESCRIT | — | **le générateur n'existe pas** : ni scaffold d'app, ni commande de conformité exécutable |

### Chantiers pour fermer la route (ordonnés, format WAMA — pas de planning RH)

1. **Migrer les 7 apps sur les briques du port T/D/C** (= la suite normale, app par app, Reader
   d'abord) — chaque port réduit mécaniquement les écarts des maillons 3/5/6/7.
2. **Contrat d'URLs canonique** (maillon 1) : documenter `upload/ start/<pk>/ stop/<pk>/
   progress/<pk>/ card/<pk>/html/ download/<pk>/ …` dans `common/README.md`, puis fabrique de
   vues génériques (le pattern `make_queue_manipulation_views` montre la voie — l'étendre à
   start/stop/progress/card_html).
3. **Enum statuts centralisée** (`common`) + adoption progressive (les briques tolèrent déjà les
   vocabulaires variés — l'enum fige la cible).
4. **`manage.py check_app_conformity`** : rendre EXÉCUTABLE la checklist 19 points + flags
   `conventions` (aujourd'hui consommés par /apps/ en documentaire ; en faire un gate).
5. **Introspection Django→PARAMS_JSON** (`model_to_param_schema`) : auto-générer 80 % des
   params.py ; + validation client dans wama-params.js.
6. **Remonter les briques candidates §2c au fil des ports** (profils au port converter, TTS au
   port synthesizer, A/B au port enhancer…).
7. **Scaffold d'app** (`manage.py scaffold_app`) : n'écrire QU'EN DERNIER, quand 1-6 ont figé les
   contrats — sinon on scaffolde des patterns encore mouvants. C'est la marche finale vers
   « app = manifeste » (LLM local génère une app, cf. project_manifest_generation_priority).

---

## 3bis. INCIDENT POST-AUDIT (2026-07-06 soir) + GARDE-FOU PÉRENNE

**Symptôme** : plus aucune app dans le menu déroulant/accueil, 500 sur `/common/apps/` —
`SyntaxError: keyword argument repeated: layout (app_registry.py:352)`.
**Cause** : kwarg `layout=True` dupliqué dans le bloc composer d'APP_CATALOG, introduit par le
commit de clôture de la session PRÉCÉDENTE (13cb60b, « flags layout »). Invisible jusque-là car
(1) `manage.py check` n'importe JAMAIS app_registry (seul le rendu d'une page le fait, via le
context processor) et (2) le serveur déjà lancé gardait l'ancien module en mémoire — le restart
WSL2 a fait éclater l'erreur. **Corrigé** (doublon retiré + balayage AST : plus aucun kwarg
dupliqué dans le fichier).
**Garde-fou créé** : `wama/common/tests.py` — tests de FUMÉE qui importent APP_CATALOG et rendent
RÉELLEMENT accueil + /apps/ + l'index de CHAQUE app du catalogue (`manage.py test wama.common`,
5/5 OK). À lancer après toute modification de app_registry/context processors/templates de base.
**Bonus** : le smoke test a déterré un bug latent PRÉEXISTANT — la data migration
`media_library/0002_migrate_custom_voices` référençait `synthesizer.CustomVoice` sans dépendre de
`synthesizer/0007_customvoice` → toute base FRAÎCHE (test, réinstallation) explosait en
LookupError. Dépendance ajoutée.

## 4. ERREURS D'AGENTS DÉTECTÉES (leçon : toujours contre-vérifier)

- « 8 apps utilisent begin_processing » → FAUX : T/C ce matin, D basculé cet après-midi ; 0 des 7.
- « conventions purement documentaires, non exécutées » → PARTIEL : consommées par
  `get_conformity_summary()` → page `/apps/` (source live) ; mais ne pilotent pas l'UI runtime.
- « les 7 apps incluent `_new_item_card` » → FAUX : aucune des 7 (seulement T/D/C).
- « anti-race absent de reader/converter » → FAUX : inline présent (à unifier sur la brique).
- « tool_api.py par app manquant » (audit du matin) → FAUX : registre CENTRAL `wama/tool_api.py`.
- « waveform.py dans common » → il est dans `transcriber/utils/` (le doublon était réel).
