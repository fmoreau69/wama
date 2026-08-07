# REPRISE — 2026-08-06 · instance IMAGER / COMMUN

> ⚠️ **DEUX SESSIONS EN PARALLÈLE — ne pas confondre les handoffs.**
> Ce fichier couvre **le portage de l'imager** et les briques `common/` associées.
> L'autre instance travaille sur **cam_analyzer / volet droit** : son handoff est
> [`REPRISE_2026-08-06.md`](REPRISE_2026-08-06.md) (ne pas l'écraser — j'ai failli le faire).
> Partition respectée toute la session : je n'ai touché ni `wama_lab/**` ni `common/manifests/**`.

---

## 0. MISE À JOUR — session du 2026-08-06 (soir) : ÉTAPE 1 FAITE

Commits `5115a5f` (palier imager) + `e3b503c` (corpus + doc). **Étape 1 du §3 livrée et vérifiée
au navigateur** ; §3 étapes 2 et 3 restent ouvertes telles quelles.

- Volet : **257 → 84 lignes**, généré par `WamaParams.render(context:'panel')`, valeurs par
  `common/utils/user_settings.py`. `USER_SETTINGS_DEFAULTS` **dérivé du schéma** (15 clés).
- **Régression réparée et PROUVÉE** (requête interceptée puis avortée, rien créé) : le POST porte
  `num_images=4`, `steps=50`, `width/height=1024`, `model=auto`.
- Diagnostic corrigé : ce n'était pas « la card n'envoie pas le volet » mais `handleFormSubmit`
  **orphelin** — il lisait bien le volet, son `<form>` hôte avait disparu en `8e0cedb`.

**Trois défauts trouvés en MESURANT, pas en relisant** (à retenir : la relecture ne les voyait pas) :
1. `fillModelChoices` cherchait `[name="model"]` ; `WamaParams` génère `id` + `data-param` **sans
   `name`** → sortie silencieuse → select modèle VIDE. **La modale d'item était touchée aussi**
   (même brique depuis `f37b705`). Corrigé dans le helper partagé.
2. `_panel_defaults` ignorait les `dom_id` en **chaîne** (forme des params de brique) →
   `output_format`/`output_quality` disparaissaient du volet.
3. `dom_id` panel `imgDefaultModel`/`vidDefaultModel` **fictifs** (aucun DOM), propagés jusque dans
   le corpus de manifestes.

**Effet de bord VOULU de `has_batch=True`** (app_registry, `9922f65` avait livré un vrai batch) :
deux défauts réels sortent du « N/A » et deviennent mesurés —
- 🔶 `anti_race` : `start_batch()` (`views.py:727`), `restart_generation()` (`:809`),
  `start_all_generations()` (`:868`) **sans verrou** → risque de double lancement, patron
  `CLAUDE.md` non appliqué. **C'est le plus urgent de la liste.**
- 🔶 `batch_import` : `imager/utils/prompt_parser.py:73` refait `batch_parsers`.

**Score inchangé à 78 %** : le palier visait `user_settings`, déjà compté vert **à tort** (le
checker matchait le littéral). La grille n'a pas monté, elle est devenue honnête.

**Trou constaté, non traité** : `refreshCard` (`queue.js:26`) **remplace** une card, il ne sait pas
en **insérer** une → le `location.reload()` de `input_card.js` n'est PAS un reliquat à nettoyer.
Le commentaire qui l'annonçait était faux, il est corrigé. Insérer suppose de savoir dans quel
batch ranger la card. Autre trou : **`wama/imager/tool_api.py` n'existe pas** (F8).

## 0bis. Suite du 2026-08-07 — imager **81 % (60/74)**, plus aucun critère partiel

Commits `708b02a`, `0df1c78`, `3780b77`.

- **`anti_race` VERT** : `start_batch`, `start_all_generations`, `restart_generation` verrouillés
  (`begin_processing` par item, patron transcriber). `restart_generation` n'avait **aucune
  révocation** de l'ancienne tâche. **Heuristique maison retiré** (« relance si RUNNING > 30 min,
  > 2 h en vidéo ») : il doublait `reconcile_orphaned_running` (preuve positive de mort, déjà
  appelé à l'index) et il était plus FAIBLE — une vidéo légitimement longue redevenait relançable
  et repartait sur le GPU. Échappatoire inchangée : ⏹ `force_reset`.
- **Doublon de batch ÉLIMINÉ** : `handle_file2img` crée un `GenerationBatch` de N items via
  `consolidate_into_batch` ; `start_batch`/`get_batch_children` portent sur le batch ; self-FK
  `parent_generation` retiré (migration 0014, 0 ligne l'utilisait).
  **Bug latent réparé au passage** : la modale batch poste `dataset.batchId` sur `batchUpdate`
  ET `batchStart`, mais `start_batch` cherchait cet id dans `ImageGeneration` → « Enregistrer &
  démarrer » ne pouvait pas marcher depuis `35fd056`. Et `start_batch` forçait
  `generate_image_task`, cassant tout batch vidéo.
- **`batch_import` + `batch_template` VERTS** : detect bar commune + `batch_preview` (contrat
  WamaBatchImport, patron composer) + `import_batch` qui **délègue** à `handle_file2img` (une
  seule implémentation) + gabarit **généré** par `build_batch_template`.
  Intégration « app existante » VOLONTAIRE : pas de `dropZoneId`/`fileInputId` passés à la brique
  — la card route déjà ses fichiers, un 2e gestionnaire donnerait une double détection ;
  `routeFile` délègue à `detectAndHandle()`.

**Angle mort de la grille, confirmé par Fabien** : les critères batch (`auto_wrap_orphans`,
`build_batches_list`, `batch_card_common`) étaient **déjà verts** pendant que les DEUX mécanismes
coexistaient. Ils testent la PRÉSENCE des briques, pas l'EXCLUSIVITÉ. Même angle mort que le faux
vert de `user_settings`. **Ne pas conclure d'un vert qu'il n'y a pas de doublon.**

**Crash WSL2 le 07/08 vers 10h20** (redémarrage constaté, gunicorn tombé) : travail non commité
INTACT. 1 message `unacked` en Redis = `model_manager.sync_models`, pas une tâche GPU. Relance
faite en **web seul (gunicorn), sans workers Celery**, pour écarter toute redélivrance.

**Suite** : étape 2 (`initFromSchema` + `inspector_actions`), puis `url_ingest` /
`recursive_import`. Toujours ouverts : `refreshCard` ne sait pas INSÉRER (donc le
`location.reload()` reste), et `wama/imager/tool_api.py` n'existe pas (F8).

## 1. État mesuré en fin de session (session PRÉCÉDENTE — voir §0)

`python manage.py check_app_conformity` → **imager 77 % (56/74)**, parti de **55 %**.
Les 9 autres apps sont inchangées.

Rouges restants (16) : `app_access_view`, `backend_packages`, `batch_template`, `during_preview`,
`help_about`, `init_from_schema`, `inspector_actions`, `layout`, `model_caps_ui`,
`params_modal_batch`¹, `processing_time`, `queue_manipulation`, `recursive_import`, `safe_delete`,
`scoped_reads`, `url_ingest`.

¹ à re-mesurer : la modale batch a été livrée **après** la dernière mesure.

## 2. Livré (12 commits locaux, non poussés)

| Commit | Contenu |
|---|---|
| `776203f` | catalogue : vocabulaire `i2i` + `category` dans les capacités imager (SD 1.5/SDXL = `t2i+i2i`) |
| `8e0cedb` | **card d'entrée commune, une par DOMAINE** — 390 lignes de formulaire supprimées ; plus aucun radio de mode : `generation_mode` est DÉRIVÉ des entrées + du modèle |
| `070c81d` | card : bouton ✨, chips de mots-clés recâblées, prompt négatif ; invariant « on poste le prompt ORIGINAL » |
| `2e330cf` | **fondation de file** : partial `_generation_card.html` unique + endpoint `card_html` + `refreshCard` → mort du repaint DOM manuel et du `location.reload()` |
| `7b51071` | anti-doublon : adoption de `WamaApp.Poller` / `getUrl` / `csrfFetch` / `toast` (je les avais réécrits) |
| `f37b705` | **modales schéma-driven** : fin de la TRIPLE écriture du schéma (`params.py` + JSON de vue + HTML) |
| `fb2563b` | suppression de 497 lignes de code mort (`index.js` 2030 → 1533) |
| `9922f65` | **batch commun** : `GenerationBatch` + `GenerationBatchItem`, `auto_wrap_orphans`, `build_batches_list`, `_queue_toolbar`, `_batch_card` |
| `86c7db1` | **fix brique commune** : le gate d'appariement bloquait le lancement À VIE (cf. §4) |
| `9e10d0e` | **brique** `WamaParams.settingsModal` — orchestration de modale extraite (cycle + hooks) |
| `f80ed4f` | anonymizer adopte la brique (2ᵉ consommateur : c'est lui qui a révélé le manque `restart`) |
| `35fd056` | **modale batch imager** (patron anonymizer/avatarizer — aucune brique créée) |

`index.html` : **1574 → 675 lignes**. Migration `0013` (batch) appliquée, purement additive :
**0 batch existait** — le self-FK `parent_generation` n'avait jamais servi.

## 3. LA SUITE — déterminée par le code existant, plus rien à arbitrer

### Étape 1 — volet droit (256 lignes écrites à la main)

Patron lu dans les **5 apps portées** (avatarizer, converter, describer, synthesizer, transcriber) :

1. `common/utils/user_settings.py` est **la** persistance des réglages (clé `user_{id}_{app}_{nom}`,
   cache 30 j glissants, défauts déclarés par l'app). **Ni migration, ni colonne, ni champ JSON.**
2. Déclarer `USER_SETTINGS_DEFAULTS` pour l'imager, alimenté par les défauts de `params.py`.
3. Volet = `WamaParams.render(context:'panel')` nourri par `get_user_app_settings(...)`
   → les 256 lignes tombent (référence : **reader = 10 lignes**).
4. **Écriture À LA CRÉATION** (transcriber `views.py` ~l.198 et ~l.268) :
   `save_user_app_settings(user, 'imager', prefs)`. Il n'existe **aucun** endpoint
   « enregistrer le volet » dans les apps portées — les réglages voyagent avec la création.
5. `UserSettings` (modèle imager, 5 colonnes, jamais écrit) devient sans objet → le retirer
   **après** bascule vérifiée.

> 🔴 **RÉGRESSION À RÉPARER EN MÊME TEMPS (introduite par moi en `8e0cedb`)** : la card d'entrée
> n'envoie pas les valeurs du volet et les handlers utilisent `get_model_defaults(model)`.
> Régler « 4 images » ou « steps 50 » dans le volet n'a donc **aucun effet**. Avant P2, l'ancien
> formulaire lisait ces contrôles au submit. Le point 4 répare la cause.

### Étape 2 — inspecteur CONTEXTUEL

`WamaInspector.initFromSchema` — présent dans **9 apps sur 10**, absent de l'imager.
Référence : `wama/reader/static/reader/js/reader.js` (~l.624) — contrat `queueContainer /
cardSelector / batchSelector / panelContainer / schema / saveItem / saveBatch`.
Deux instances (une par domaine), la file imager étant scopée par onglet.

### Étape 3 — généraliser `WamaParams.settingsModal` aux 8 autres apps

Validé par Fabien : la brique est à bon escient et doit être portée. Les 8 autres réécrivent
encore le cycle de modale.

Sans dépendance : `processing_time` (`ProcessingTimeMixin` remplace le `duration_display` maison),
`scoped_reads` (`visible_or_404` sur ~11 chemins de lecture — chantier atomique),
`queue_manipulation`, `url_ingest`, `safe_delete`, `layout`, `help_about`.

## 4. Deux bugs trouvés dans le COMMUN (corrigés)

- **`wama-input-match.js` — gate de lancement bloquant à vie.** `provided()` ne détecte que les
  entrées **fichier** ; le catalogue déclare `prompt` en requis (saisi dans un textarea) → bouton
  « Générer » désactivé pour toujours. Corrigé : le gate ne porte que sur les entrées
  **matérialisées en slot** ; la ligne d'état annonce toujours toutes les attentes du modèle.
  L'imager est le **1ᵉʳ adopteur réel de `onState`** (composer ne l'appelle pas) — le chemin
  n'avait jamais été exercé : *support ≠ adoption*.
- **Poller vs card mère de batch** : la card mère porte `.imager-card` sans `data-id` → requêtes
  `/progress/undefined/`. Le sélecteur exige désormais `[data-id]`.

## 5. Docs mises à jour

- `wama/common/README.md` — `WamaParams.settingsModal` + `ParamGroup` ajoutés à l'inventaire.
- `WAMA_APP_GENERATION_ROUTE.md` — 3 lignes **périmées** corrigées (« modale batch jamais rendue »
  = faux ; anonymizer/imager ne sont plus hand-built ; chips ≠ « reader seul ») **+ ajout de la
  ligne `user_settings`**, qui manquait totalement à la route.
- `CLAUDE.md` roadmap §3 — `_settings_modal.html` **livré autrement** (générée, pas déclarée) ;
  l'item datait du 1ᵉʳ avril 2026, **avant** l'existence de `WamaParams`.

## 6. Pourquoi tant de choses ratées — et quoi faire

**Cause dominante : j'ai travaillé sur des lectures PARTIELLES.** Les sorties de lecture sont
compressées dans cette session ; la règle « lecture compressée = lecture ÉCHOUÉE → relire par
tranches » existe déjà et je ne l'ai pas appliquée. J'ai avancé sur des fragments de
`common/README.md`, de la route et d'`INPUT_MODEL_MATCHING.md`. D'où : réécriture de
`WamaApp.Poller`/`getUrl`/`csrfFetch`, duplication de l'orchestration de modale,
`wama-inspector-autofill.js` jamais ouvert, et surtout `common/utils/user_settings.py` ignoré.

**Cause secondaire : pré-vol de `/port-app` non déroulée.** Le skill dit de lire
`common/README.md` **en premier** (« l'inventaire des briques ») et cite `user_settings.py` à
l'étape 10. Lu en diagonale, puis code.

**Trou réel dans la route** : elle ne mentionnait **nulle part** `user_settings.py` — le mécanisme
n'existait que dans le skill. Corrigé (§5). Réponse honnête à « trou dans la route ou lecture
incomplète ? » : **les deux**, avec ma lecture comme cause principale.

**Règles à appliquer, dans cet ordre, AVANT toute ligne de code :**
1. `ls wama/common/utils/` **et** `ls wama/common/static/common/js/` — une liste de fichiers ne se
   compresse pas et ne ment pas ; un nom suffit à éviter une réinvention.
2. Lire `wama/common/README.md` **en entier, par tranches**, et le déclarer lu.
3. Avant d'écrire une fonction, `grep` son **intention** dans `common/` (`poll`, `csrf`,
   `settings`, `url`), pas seulement son nom.
4. Ne jamais conclure d'une ligne de doc qu'un mécanisme n'existe pas : **vérifier dans le code**
   (3 lignes étaient périmées cette session).
5. Comparer aux **apps déjà portées** avant tout arbitrage — la réponse y est presque toujours, et
   demander à Fabien de trancher un choix déjà tranché dans le commun est une perte de temps.
