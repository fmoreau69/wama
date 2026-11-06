# WAMA — Formalisme des manifestes (spécification de référence)

> **Schéma fonctionnel des flux (manifestes → ingest → app_gen → UI) : [`WAMA_MANIFEST_ARCHITECTURE.md`](WAMA_MANIFEST_ARCHITECTURE.md).**
>
> **Statut : socle IMPLÉMENTÉ (MAJ 2026-08-11).** Enveloppe + registre + ingest + les **7 kinds**
> vivent dans `wama/common/manifests/` (envelope/kinds/ingest/projection + `builtin/{app,dataset,
> function,library,model,pipeline,project}.py`, modèle DB `common.Manifest`) ; extract `app` = 13
> clés `APP_FACETS` (dont `data`, 2026-08-18 — `builtin/app.py:41-42`) ; **write-back réel sur 4
> kinds** (`kinds.py:14-23`) — `app` : **10** facettes projetées (`PROJECTED_FACETS`,
> `builtin/app.py:836-837` : `access` en base → AppAccessPolicy + 9 en code), `processing` en
> projection partielle (urls), `models` en code-gen ; `library` : registre entier ; `model` : champs
> déclaratifs ; `function` : binding `user` seul. *(MAJ 2026-10-31 — ce bandeau disait « 12 clés,
> write-back sur 3 kinds, 1 facette écrite et 9 en `codegen_required` ».)* Cette spec fixe le
> formalisme COMMUN + le schéma du kind `app` (8 facettes fonctionnelles F1–F8 = 13 clés). Les blocs
> annotés « cible » ci-dessous décrivent le schéma VISÉ, pas encore l'extract réel.

---

## 1. Principe : union discriminée

Tout manifeste = **enveloppe commune** + **`body` spécifique au kind**, validé contre le schéma du kind.
Un **registre `MANIFEST_KINDS`** keyé sur `manifest_kind` fait la validation et le dispatch. C'est ce qui
empêche de mélanger des manifestes sans rapport, et ce qui rend le formalisme extensible.

```yaml
# ── Enveloppe commune (TOUS les kinds) ───────────────────────────────
manifest_kind: app            # app | function | dataset | model | pipeline | project | library
schema_version: "1.0"
key: transcriber              # identifiant unique dans le kind
name: Transcriber
description: ...
owner: <username>             # créateur (null = système)
visibility: private           # private | project | unit | public (ScopedVisibility)
scope_project | scope_org_unit: null
projects: []                  # traçabilité qualité
source: {type: builtin|library|folder, ref: "..."}   # d'où vient le manifeste
world: transverse             # media | data | lab | transverse (implémenté, envelope.py:18)
created_at, updated_at        # portés par le store DB (common.Manifest), pas par l'enveloppe
body: { ... }                 # spécifique au kind (voir §3 pour app)
```

Kinds prévus : **`app`** (§3), **`function`** (= `FunctionSpec`, déjà fait, `WAMA_DATA_FUNCTION_CARDS.md`),
**`dataset`** (style modèle tiers : channels/signals/reference_tables), **`model`** (= `AIModel`), **`pipeline`**
(= `StudioPipeline.graph` **OU un registre de code** — `register_pipeline_source`, 1er cas `cam_analyzer.PASSES`,
2026-09-09 ; précisé le 2026-09-15), **`project`** (= `Project`, déjà fait), **`library`** (= `common.Library`,
§7.1 ; enregistré `builtin/library.py`, ajouté à cette liste le 2026-10-31).
> ⏳ **Précisé le 2026-09-15 → `WAMA_APP_GENERATION_ROUTE.md §10.6`** : le kind `pipeline` porte les nœuds
> `source | sink | app | function` (`function` codé le 2026-09-09) et gagnera un TYPE DE NŒUD `pipeline`
> (un pipeline enregistré réutilisé comme nœud) — pas de nouveau kind. Une card porte une instance de
> pipeline dans tous les mondes.
> ✅ **2026-10-18 (ROUTE §10.6 3.3bis, R2 — décision D1)** : un nœud porte DEUX champs de nature
> différente. **`params`** = les VALEURS de réglage que l'utilisateur décide (l'inspecteur du Studio
> n'écrit que là, et seulement la clé touchée) ; **`process`** (facultatif, dict) = la DÉCLARATION du
> process qu'un registre de code exporte — `degree`, `watched`, `gpu`, `outputs`, `share`, `label`,
> `eta`, `toggle`, `card_model`, `upstream_switch`, `result`, `result_format`, `checks` (pipelines d'app),
> `stage`, `per_camera`,
> `task` (passes du Lab) —, lue par les générateurs (`codegen/pipeline_decl.process_specs`), gardée
> telle quelle par le canvas. Les deux vivaient dans `params` : un geste pouvait effacer la
> déclaration. Les nœuds `source`/`sink` sont ceux du registre des nœuds intégrés
> (`builtin/pipeline.BuiltinNode`, inscrits par leur monde) — plus les ensembles
> `SOURCE_NODES`/`SINK_NODES`.

> **Distinction EXTRAIT vs AUTORÉ** (dégagée en construisant `dataset`) : deux familles de kinds.
> - **Extraits** (`app`, `model`, `pipeline` — ce dernier depuis le canvas en DB OU un registre de code) : l'objet existe DÉJÀ dans le code/DB → le kind fournit
>   `extract(key)` qui LIT les registres et produit le manifeste. Le round-trip (extract → régénère →
>   diff) est leur test de fidélité.
> - **Autorés** (`dataset`, `project`, `function`-user) : le manifeste EST l'origine (pas de code à
>   extraire) → `extract=None`, le kind est `validate + store`. La fidélité se teste par la projection
>   (instancier → vérifier), pas par le round-trip.

### 1.1 Décisions actées (2026-07-21)

- **`world`** = champ de **1er niveau de l'enveloppe** (pas dans `body`), valeurs **closes** :
  `media | data | lab | transverse`. Pas de niveau au-dessus (les 4 mondes SONT la partition de tête) ;
  `OrgUnit`/`project` sont des axes ORTHOGONAUX (portée/partage), pas une hiérarchie au-dessus des mondes.
  **Sémantique** : le monde classe la **finalité** de l'app, PAS ce qu'elle touche. `media` = production
  générative/créative ; `data` = traitement/analyse de signaux et données ; `lab` = apps de **science
  métier** spécifiques à un labo (cam_analyzer, apprentissage de profils conducteurs par deep learning) ;
  `transverse` = le **substrat** commun (studio/pipeline, médiathèque, model_manager, permissions, i18n,
  RAG, assistant). Une app déclare **un** monde = sa finalité primaire ; sa **capacité** vit dans les
  `ports` + les kinds de manifeste (une app `lab` peut consommer des ports `data` et produire un kind
  `model`). Conséquence : une classification de monde discutable est **cosmétique** (navigation), jamais
  structurelle — rien ne peut être « omis » car le *quoi* est dans ports+kinds, pas dans l'étiquette monde.
- **Confidentialité de l'app** = déjà portée par l'enveloppe : `visibility` + `scope_project`/`scope_org_unit`
  décident **qui voit/utilise l'app** (une app privée-labo ne sort pas du labo). C'est DISTINCT de
  `body.access` (roles/public/min_tier) = le **gating de permission WAMA**. Les deux vivent dans le manifeste :
  enveloppe = confidentialité (diffusion), `access` = droits (tier/rôles).
- **Enrichissement / RAG / skills** = l'app **DÉCLARE sa participation + ses défauts** dans le manifeste
  (`body.prompts.targets`, `skills`, `rag_eligible`, `enrich_default`), mais le **NIVEAU effectif**
  (RAG user/équipe/labo/université) est **résolu au RUNTIME** = réglage utilisateur ⊕ défaut app ⊕ héritage
  `OrgUnit`. On ne fige PAS le niveau dans le manifeste (il dépend de l'utilisateur), on fige la CAPACITÉ.
- **Statuts** = le vocabulaire canonique **`PENDING | RUNNING | SUCCESS | FAILURE`** est la CIBLE imposée ;
  le round-trip signale les apps déviantes comme non-conformes (fait progresser la conformité réelle).
- **Langue du manifeste = ANGLAIS canonique.** Les chaînes lisibles (`label`, `description`, `help`…) sont
  en anglais SOURCE et alimentent le **registre de chaînes WAMA** (i18n central : pivot interne EN, identif.
  de langue, traduction injectée selon la langue par défaut de l'utilisateur). Le manifeste **NE PORTE PAS
  ses propres traductions** (ce serait un 2e système de traduction = roue réinventée) : il fournit l'anglais,
  le registre central traduit. Chaque chaîne a une clé stable (ex. `app.transcriber.label`) pour le registre.

---

## 2. Ingest — pas une simple fonction

Les briques existantes (APP_CATALOG, GENERIC_APPS, model_manager, registres, permissions…) ont été
construites **par le fonctionnel** et regroupent l'info par usage. On NE les réécrit PAS pour lire le
manifeste en direct (risque). On ajoute un **ingest** dont le manifeste reste la **source unique
autoritaire** :

- **Idempotent** : re-ingérer = mettre à jour, jamais de doublon.
- **Transactionnel** : tout-ou-rien sur l'ensemble des registres touchés.
- **Réversible** : `un-ingest` retire proprement les entrées dérivées.
- **Traçable** : chaque entrée dérivée porte un back-link `_manifest_key` → détection d'orphelins.
- **`verify`** : re-projeter depuis le manifeste et **différer** contre l'état courant des registres →
  la dérive devient visible et corrigible (le manifeste gagne toujours).

> La « redondance manifeste ↔ registres » est ACCEPTÉE parce qu'elle est **dérivée + re-synchronisable**,
> pas maintenue à la main. Discipline : les entrées dérivées ne s'éditent JAMAIS à la main.

### 2.1 PROPRIÉTÉ DE SÛRETÉ NON NÉGOCIABLE — rien ne lit le manifeste en direct

> **Le système en marche ne lit JAMAIS le manifeste en direct.** Le manifeste est la source de *vérité* ;
> les registres/BDD existants restent la source de *runtime* (l'**état committé**). Le seul pont entre les
> deux est l'ingest — **explicite, validé, transactionnel, réversible, jamais silencieux/automatique**.

Conséquence (répond à la crainte de corruption) : un manifeste corrompu ou supprimé **ne peut pas corrompre
l'aval** —
- invalide → **rejeté à la validation**, n'atteint jamais l'état committé ;
- supprimé → **la dernière projection committée persiste** jusqu'à un `un_ingest` EXPLICITE ;
- `verify` montre la **dérive (diff)** avant tout `promote` — l'humain reste dans la boucle.

Analogie : le manifeste est aux registres ce que les **fichiers de migration** sont à la base — on ne
*tourne* pas dessus en direct, on *migre* délibérément (= ingest), avec validation et rollback ; supprimer
une migration ne *drop* pas les tables. **Garde-fou** : ne JAMAIS rendre l'ingest automatique — c'est le prix
de la robustesse. Tranché sur « BDD vs réutilisation sans redondance vs tirage auto » = **BDD + ingest gaté**
(réutilisation sans redondance = fragile + réécrit les briques ; tirage auto = corruption silencieuse).

**Sandbox** = un manifeste en `visibility=private/staging` : l'app/fonction est instanciée et testée
**hors registres communs**, puis **promue** (réutilise `ScopedVisibility` + l'action `promote`, et la
doctrine wama-dev-ai « propose, l'humain valide »).

**Test de fidélité (jonction du tunnel)** : ré-injecter le manifeste d'une app EXISTANTE → la régénérer
dans le sandbox → **différer** contre l'app réelle. Chaque écart = un trou dans le schéma → on itère
jusqu'à diff nul. C'est le mécanisme qui garantit que le formalisme a capté l'essence.

---

## 3. Kind `app` — schéma (issu de l'audit du code réel, 8 facettes)

```yaml
body:                                   # (sous l'enveloppe commune)
  # F1 IDENTITÉ            [APP_CATALOG]
  # (world = champ d'ENVELOPPE, pas de body — ✅ FAIT : media|data|lab|transverse, DÉCLARÉ par
  #  l'app dans APP_CATALOG et lu par app_registry.app_world() depuis le 2026-10-02 ; il était
  #  déduit du groupe de la matrice d'accès)
  category, url_name, icon, color, input_extensions

  # F2 CAPACITÉS & PORTS   [fusionne APP_CATALOG.input/output_types ⟷ GENERIC_APPS.input_kinds/output_type
  #                         + APP_MODES] — supprime la REDONDANCE
  ports:
    inputs:  [{id, label, group: travail|prompt|reference, types:[image|video|audio|document|text], multi}]
    outputs: [{id, label, types:[<media_cat>|auto]}]
    # RÈGLE PREVIEW D'ENTRÉE (importante) : la preview d'entrée BIND sur le port de TRAVAIL
    # (group ∈ {travail, prompt}) — JAMAIS sur un port `reference`. La référence CONDITIONNE le
    # traitement (voix/image/mélodie/negative_prompt), elle n'EST pas l'entrée transformée.
    # La preview est TOUJOURS UNITAIRE (par card) : fichier de travail | prompt (dont TEXTE) | fichier
    # de sortie. PAS de preview de batch (une card = un item). Seule exception : imager peut produire
    # plusieurs images en sortie = MOSAÏQUE (N sorties dans UNE card), pas un batch. Dérivable du
    # manifeste (on lit quel port a group=travail|prompt) → plus de preview codée en dur par app.
    # PreviewRegistry bind déjà sur le fichier de travail (input_file).

    # ── CONTRAT DE JONCTION AVEC LA CHAÎNE PREVIEW COMMUNE (2 instances creusent en parallèle) ─────
    # La preview commune (media-preview.js / unified_preview / PreviewRegistry) LIT les groupes de
    # ports ; le manifeste les GÉNÈRE. Aujourd'hui, extract_app() ET la preview lisent la MÊME source :
    # `studio_node_ports(app_id)` (app_registry+app_modes). Demain, quand la projection inverse le sens,
    # `studio_node_ports` devient une projection DU manifeste — la preview hérite sans changer sa logique.
    # ÉTANCHÉITÉ : preview ET extract passent par UN SEUL accesseur (`studio_node_ports` ; `app_ports`
    # n'existe pas dans `wama/` — retiré de cette ligne le 2026-10-31),
    # jamais par app_modes/app_registry en direct → un seul point de bascule le jour de la projection.
    # Le « PENDANT » (le média de sortie OBSERVÉ pendant qu'il se construit — texte, image courante,
    # audio par segment, fichier lu pendant son écriture ; le streaming « à la Suno » en est un cas) =
    # une CAPACITÉ DÉCLARÉE (`capabilities.during_preview`), pas un mécanisme codé en dur : le
    # manifeste déclare QUELLES apps le font, la brique commune fournit le COMMENT. Même patron que
    # has_realtime/instant_preview et que le bouton de cycle ▶/⏹/↻. Plan détaillé preview = doc dédié.
    # ⚠ `capabilities.streaming` disait la MÊME chose sans aucun lecteur propre : RETIRÉ le 2026-10-06
    # (REMOVAL_LEDGER) ; la déclaration est tenue par `tests_during_preview_declared` (déclaré ⇔ émis).
  capabilities: {has_realtime, has_edit_page, instant_preview, batch,
                 export_binding: late|early, supports_profiles, has_url_import, has_youtube}
  # SURFACES (2026-10-13, 2ᵉ surface du chantier SURFACES : le fond du Writer) — les pages
  # d'édition de l'app, COMPOSÉES de briques universelles (`common/surfaces.py`, registre
  # `ui_bricks`) et servies par les vues communes. Rendue en `<app>/surfaces.py` par
  # `codegen/surfaces_gen` ; la card générée porte un ✎ par surface (`templates_gen`).
  surfaces: [{key, label, edits, reruns?, reads: {rôle: champ},
              slots: [{id, brick, x, y, w, h, options?, zone?}], witness?: {champ: valeur}}]
  # `zone` (2026-10-21) : `grid` (défaut) ou `panel`, la COLONNE du volet droit — une colonne
  # (`x` 0, `w` 1 ; `y` l'ordre, `h` la hauteur). Une brique passe de l'une à l'autre sur la page.
  # `witness` (2026-10-18) : l'élément TÉMOIN sur lequel le nocturne ouvre la surface et capture
  # ses briques (vignettes du catalogue `ui_bricks`). Pour un champ FICHIER la valeur nomme un
  # contenu — une extension connue de la taxonomie (`.md`, `.html`, `.png`…) ou un type de données
  # (`detections`) ; pour un autre champ, la valeur littérale. Jugé par `Surface.witness_problems`.
  # `edits` doit être un FICHIER produit par un process déclaré (`pipeline.outputs`) : il s'édite
  # comme TEXTE, validation/disponibilité/écriture communes. Une couche de DONNÉES (corrections de
  # l'anonymizer) porte sa validation en Python : elle s'écrit dans l'app, le gabarit la REFUSE.
  # ⏳ Non encore EXTRAITE (`builtin/app.py` ne lit pas les surfaces) — alors que l'anonymizer, le
  # composer et le transcriber en déclarent dans `<app>/surfaces.py` (corrigé le 2026-10-31 : la
  # ligne disait « seule une app née d'un manifeste la porte »). L'extraire demandera de dire quoi
  # faire d'une validation en Python.
  # SORTIE = 3 CONCERNS SÉPARÉS (jamais surchargés — corrigé 2026-07-22, détail WAMA_APP_GENERATION_ROUTE §F2) :
  #   output_type   = catégorie média FIXE (ports/preview/routage) ; converter = 'mirror/any'
  #   output_format = mécanisme COMMUN hérité du converter (générique-par-catégorie ∪ app-spécifique) ; sélecteur download
  #   domains       = onglets, hint DÉCLARATIF, NON dérivé du type (converter=0 onglet ; imager≠enhancer même modalités)
  # ⚠ Corrigé le 2026-10-21 sur mesure : ces deux lignes décrivaient `domains` et `modes` comme deux
  # clés sœurs, et des modes « DÉRIVÉS des capacités-modèle » portant `settings:[param_name]`. Le code
  # extrait UNE facette `modes: {domains: [...]}`, recopie d'`APP_MODES` (`builtin/app._modes` ;
  # réécrite par `_project_modes` au write-back — renvoi corrigé le 2026-10-31) ;
  # les modes y sont DÉCLARÉS, et aucune liste `settings` n'y a de lecteur (retirées, MODES_QUEUE_UX §3).
  modes: {domains: [{id, label, icon, variant?, accepts, params_schema?, route_prefix?, mode_param?,
                     inputs?, library_natures?, modes: [{id, label, icon, variant?, realtime?, inputs}]}]}

  # F3 UI / INSTANCIATION  [params.py PARAMS_JSON — déjà source unique, inchangé]
  params: [ Param{name,type,label,icon,default,choices,options_source,show_if,
                  contexts:[item|batch|panel],advanced,chip,help_source,...} ]
  # ✅ RÉSORBÉ (constaté le 2026-10-31) : une clé `options_source` se résout par l'un des DEUX
  # registres communs de `wama-params.js` — `OPTION_SOURCES` (l. 969, endpoint) et
  # `PAGE_OPTION_SOURCES` (l. 1266, donnée de page, dont `formats` : `converter.js:382`). Une clé
  # absente des deux se NOMME dans le select (`codegen/templates_gen.py:215-219`) ; y répondre =
  # ajouter la source au registre commun. Le bloc ci-dessous est la trace du 2026-08-29.
  # ~~⚠ TROU DE FORMALISME MESURÉ le 2026-08-29~~ — `options_source` nomme une CLÉ de source
  # d'options (4 clés dans le parc : voices, backends, formats, avatar_gallery) et RIEN, ni
  # dans `Param` ni ici, ne déclare COMMENT elle se résout. Deux résolutions coexistent dans
  # le code, aucune n'est déclarée : (1) registre commun `OPTION_SOURCES` de `wama-params.js`
  # (`voices` → /common/api/voices/, surchargeable par window.WAMA_OPTION_SOURCES) ; (2) une
  # donnée que l'app rend dans SA page + un `optionsResolver` synchrone écrit à la main
  # (converter : `supported_formats_json` → FORMATS[media_type].output).
  # Conséquence MESURÉE sur la jumelle générée `converter_01` : le select « Format de sortie »
  # rendait ZÉRO option, donc aucun job n'était lançable — un générateur ne peut pas deviner
  # la donnée (2). `templates_gen` rend désormais le manque VISIBLE (option nommée + warn) au
  # lieu d'un select vide, mais la RÉSORPTION est une décision de formalisme, pas de gabarit :
  # déclarer par source son mode de résolution (endpoint commun, ou champ de contexte de page).
  #
  # ~~⏳ NON TRANCHÉ — à arbitrer avant la marche B. Le trou est celui d'`options_source` SEUL.~~
  # (résorbé par les deux registres communs, cf. tête de ce bloc)
  #
  # ⚠⚠ CE BLOC A ANNONCÉ UNE « SECONDE MOITIÉ » QUI N'EXISTAIT PAS (écrite puis RETIRÉE le
  # 2026-08-29, dans la même journée — la trace reste, la raison plus encore que le fait).
  # Il affirmait que le champ dérivé `media_type` était bloqué parce que « rien ne déclare qu'il
  # prend ses valeurs dans image|video|audio|document|archive », et proposait un formalisme NEUF
  # (`processing.derived_fields: [{field, from, rule, vocabulary}]`) pour combler ce vide.
  # Ce vide n'existe pas. Le vocabulaire d'entrée d'une app est déclaré DEUX fois, et les deux
  # déclarations sont d'accord sur 10/10 apps (mesuré, pas supposé) :
  #   • `APP_CATALOG['<app>']['input_types']`        → extrait en `body.ports.inputs[].types` ;
  #   • `APP_MODES['<app>'].domains[].accepts`       → extrait en `body.modes.domains[].accepts`.
  # Le détecteur commun existait tout autant (`app_registry.category_of_path`, source unique du
  # dépôt). Les deux pièces étaient là : `views_gen` ne lisait ni l'une ni l'autre.
  # CORRIGÉ le jour même — la vue générée dérive la nature dans SES DEUX chemins (`upload` ET
  # `batch_create`) et projette le vocabulaire du manifeste (`_TYPES_ENTREE`) ; les 3 extensions
  # hors vocabulaire (.md /.markdown /.txt — le commun distingue 'text' de 'document' là où
  # l'app ne déclare pas 'text') laissent le champ VIDE et le DISENT dans `warnings`, au lieu
  # d'une valeur approchée. Gardé par `tests_codegen_lot` : un test MUTE le manifeste pour
  # distinguer « dérivé » de « écrit en dur avec la bonne valeur ce jour-là ».
  # *Un trou de formalisme s'annonce APRÈS avoir cherché la déclaration, jamais avant : poser un
  # formalisme neuf par-dessus une déclaration existante en crée une seconde, qui divergera.*
  # (4ᵉ occurrence du motif dans ce chantier, après `accepts_url`, `inspector`, sections×chips —
  # une facette DÉCLARÉE et non projetée est un manque de GABARIT, jamais un trou de glu ; la
  # classer « trou » la rend invisible en la déclarant normale.)
  inspector: {model, detail_adapter, preview_adapter, file_field, user_field}   # Detail/PreviewRegistry
  # (cible ; extract actuel = `detail_registered` + `detail_spec` (spec déclarative, A3a) +
  #  `preview_registered` + `preview{file_field, user_field}` — `builtin/app.py:433-462` ; un adapter
  #  code reste un booléen. Corrigé le 2026-10-31 : disait « présence, pas contenu »)

  # F4 MODÈLES IA          [model_config.py + model_selector.select_model] — CIBLE, pas l'extract
  # réel : extract actuel = {catalog_keys, source_attr} (lecture best-effort de <APP>_MODELS) ;
  # `paths_key` non implémenté ; select_model non touché par l'extracteur (adoption runtime :
  # composer 07-21 + transcriber 07-24).
  models: {consumes: {source, model_types:[...]},
           selection: {requires:[cap], classes, vram_budget, prefer_loaded, priority},
           paths_key}

  # F5 TRAITEMENT          [models.py + tasks.py + urls.py — pattern répété, À DÉCLARER]
  processing:
    item_model, statuses: job_status_values(),   # les 5 états JOB_* (common/models.py:42-56)
    # précisé le 2026-09-15 : vocabulaire commun = les 5 états JOB_* (AWAITING_RESOURCES existe,
    # common/models.py:42-56) + STALE — ✅ `STALE` existe depuis le 2026-09-17 comme état de PROCESS
    # (`JOB_STALE`, `PROCESS_STATUS_CHOICES`, common/models.py:98-102 ; constaté le 2026-10-31) —
    # WAMA_APP_GENERATION_ROUTE.md §10.6 4.2
    result_fields:[output_file|result_text, used_backend, used_model],
    batch: {strategy: fk|through, nature_of},
    task, endpoints: <routes RÉELLES de l'URLconf>          # `urls_gen.app_routes` (A1) ;
    # `STANDARD_ENDPOINTS` = ['index','upload','start','status','download','delete','duplicate',
    # 'update','start_all','clear_all','download_all','global_progress'] (builtin/app.py:51) n'est
    # plus qu'une CIBLE documentaire. Extraits aussi : `item_model`, `tasks`, `backend_routes`,
    # `batch_link_model`, `model_spec` (dont `batch`) — `builtin/app.py:507-583`. Reste non extrait :
    # `result_fields`. (Corrigé le 2026-10-31 : disait « item_model/result_fields/batch/task = cible
    # non extraite ».)
    ingest: {source: source_url, target: <field>, mode: audio|media|smart}  # trou #14 : projette vers
    # WAMA_INGEST (common/utils/source_ingest.ensure_local_input). Capté par extract (transcriber/describer) ;
    # projection = write-back futur. Va de pair avec capabilities.accepts_url (→ génère la card d'import URL).
    revisions: {keep: 20}   # ✅ 2026-10-13 — l'app GARDE les fichiers de ses `keep` dernières révisions
    # (+ les publiées) : `models_gen` donne au modèle d'élément `KeptOutputsMixin` (liste
    # `kept_outputs`), `apps_gen` appelle `revisions.keep_outputs` et déclare la liste à la
    # rétention (`register_retention_model`). WAMA_COLLABORATION §7.2 (reste 2), V3 tranché.
    # Premier adoptant : le Writer (bac à sable) — on l'éprouve avant de le porter aux autres apps.
    # `fields: [...]` (✅ 2026-11-01) : les seules sorties gardées (le composer : ses partitions,
    # pas le rendu). EXTRAIT de la déclaration du `ready()` (`revisions.kept_declaration`) : avant,
    # la jumelle du composer avait le champ sans la déclaration à la rétention.
  data: {…}   # ✅ 2026-08-18 (marche S2 ; ajouté à ce schéma le 2026-10-31) — SPINE DE DONNÉES :
  # les modèles Django de l'app, champs sérialisés par le MÊME sérialiseur que les migrations ;
  # consommée par `codegen/models_gen` ; verdict = `makemigrations` « No changes » sur la jumelle
  # (`builtin/app.py:36-42`). Présente dans les 10 manifestes `manifests/apps/*.json`.

  # F6 PROMPTS / IA        [PROMPT_TARGETS + prompt_skills + tool_api]
  prompts: {targets:[{field,kind,model_field,source,default_model_type,enrich,domain_field,reference_field}],
            skills:["<app>-<domain>.md"]}
  tool_api: {add, start, status, descriptions:{...}}           # TOOL_REGISTRY + tool_descriptions()
  # ⚠ 2026-08-02 : `descriptions` venait de TOOL_DESCRIPTIONS (dict manuel de mars 2026), que
  # cette ligne a figé comme source. Il est SUPPRIMÉ : `tool_api.tool_descriptions()` les DÉRIVE
  # (APP_CATALOG + docstring + schéma `params.py` + signature). Même source unique que F3 —
  # l'alignement de F3 avait été fait à la création du manifeste (2026-07-21), pas celui de F6.
  # ~~`_tool_api()` importe encore `TOOL_DESCRIPTIONS` : un `__getattr__` de module lui rend la
  # version dérivée. **Passer l'appel à `tool_descriptions()` et retirer la béquille.**~~
  # ✅ Fait (constaté le 2026-10-31) : `_tool_api()` appelle `tool_descriptions()`
  # (`builtin/app.py:715,722`) et `wama/tool_api.py` ne définit plus de `__getattr__`.

  # F7 PERMISSIONS & SCOPE [accounts/permissions.py AppAccessPolicy + ScopedVisibility]
  access: {roles:[...], public: bool, min_tier: null}
  data_scope: {visibility_default, org_unit_inheritance}

  # F8 STUDIO              [GENERIC_APPS → DEVIENT une projection, plus un 2e registre]
  studio: {runnable, primary_input, input_kwarg, fixed_kwargs, auto_start, extra_params_spec}
          # ports/output_type NE sont PLUS redéclarés : lus depuis `ports` (fin de la redondance)
          # extra_params_spec : réglages PROPRES AU NŒUD, sous la forme `Param` (2026-10-12,
          # ROUTE §10.6 point 3.3bis R1) — le nœud rend le schéma `params` entier, plus ceux-là
```

**Régénérable depuis le manifeste** (cible du round-trip) : `models.py` (spine + statuts), `urls/views`
(endpoints standard), modales+inspecteur (`params`+`inspector`), le nœud studio (`ports`+`studio`), le
gating (`access`), le câblage prompts/tool_api.

### 3.1 ~~Facette `pipelines`~~ — RETIRÉE le 2026-10-01 : une réinvention (décision n°11 tranchée le 2026-10-02)

> Formalisée puis retirée le même jour (commits `ab0e063d` → retrait), après revérification
> demandée par Fabien. Gardé ici pour que la prochaine génération ne la réécrive pas.
>
> ✅ **Décision n°11 tranchée le 2026-10-02 (Fabien)** — domicile : `WAMA_APP_GENERATION_ROUTE
> §10.6` point 9. Une app Médias qui porte PLUSIEURS process les déclare **comme le cam_analyzer
> déclare ses passes** : registre en code (`common/services/process_pipeline.ProcessSpec`), chaque
> process un `FunctionSpec binding: app`, le tout exporté par le kind `pipeline` EXISTANT sous la
> clé de l'app (`manifests/pipelines/composer.json`, 1ᵉʳ cas). **Le manifeste `app` ne gagne aucune
> facette** : c'est ce que la facette retirée ci-dessous cherchait à dire, par le formalisme qui
> existait déjà.

**Ce qu'elle était** : une liste d'étapes écrite DANS le manifeste `app`, avec un nœud `kind: process`
inventé, son propre tri topologique et un enchaîneur dans le squelette de tâche — pour dire que le
Writer (alors « Editor ») rédige le fond PUIS le met en forme.

**Pourquoi c'était faux** (confronté aux décisions et au code) :
- un pipeline se déclare par le kind `pipeline` existant (nœuds `source | sink | app | function`,
  `builtin/pipeline.py:42`) — pas par un second formalisme dans le manifeste d'app ;
- **un process d'application EST un pipeline à UN nœud** (Fabien, 30/08 : `WAMA_MANIFEST_ARCHITECTURE
  §8` ; « un cas normal », `WAMA_APP_GENERATION_ROUTE §10.6` 7) : entrée → process de l'app → sortie ;
- ~~les **fonctions** du catalogue sont des process du monde **Data** (`§10.6` 6.3 B) ; les process
  internes d'une app **Médias** (diarisation, résumé… du transcriber) ne sont PAS des fonctions, et
  la façon de les déclarer n'est PAS encore formalisée~~ — ⚠ **corrigé le 2026-10-02** : c'était
  un constat, faux pour le Lab (les passes du cam_analyzer sont des `FunctionSpec binding: app`
  depuis le 09/09) et levé pour les Médias par la décision n°11 (encadré ci-dessus). Le pilote
  est le composer (`plan` → `render`), le transcriber vient ensuite ;
- deux tris topologiques existaient déjà (celui du Studio, aujourd'hui `manifests/builtin/pipeline.py:253`
  `topo_order`, importé par `studio/tasks.py:68` ; `cam_analyzer/utils/pass_tracking.py:260` — lignes mises à jour le 2026-10-31)
  et l'enchaîneur était la « quatrième pièce » que `§10.6` 4.5 interdit d'écrire à côté du moteur commun.

**Comment une app Médias se déclare AUJOURD'HUI** (le Writer, `manifests/app_drafts/writer.json`) :
- ses **entrées** par les jetons d'`app_modes.INPUT_TYPES`, dans `modes.domains[].inputs`
  (`['prompt', 'reference_document', 'reference_layout']`) — les ports de la card v4 en DÉRIVENT
  (`app_registry.studio_node_ports`) ; la facette `ports` ne déclare que les NATURES (jetons pour
  ids, comme le composer) — et, depuis le 2026-10-19, l'OBLIGATION de chaque port (`required`,
  `one_of`), d'où le générateur déduit la forme d'entrée de la card (`app_registry.entry_form`,
  `CARD_DESIGN §11.11`). Une app qui lit son texte d'un fichier comme d'une saisie le DÉCLARE
  par la capacité `has_text_file_input` (le Translator, comme le synthesizer) ;
- sa **consigne** par une cible de `PROMPT_TARGETS` (facette `prompts`) : `kind: 'intent'` et
  `reference_field` — le pipeline de prompts comprend le document de référence ;
- ~~son **traitement** en **un seul process** (`§10.6` 11) : une glu qui rédige puis met en
  forme~~ — ⚠ **corrigé le 2026-10-05** : le Writer a DEUX process sur le patron du composer
  (`write` → le fond dans `draft_file`, `layout` → le HTML avec le port `reference_layout`),
  déclarés comme ceux d'une app existante — un manifeste `pipeline` et un manifeste `function` par
  process, sous la clé de l'app, ici en BROUILLON (`manifests/app_drafts/{pipelines,functions}/`),
  lus par le générateur (`codegen/pipeline_decl.py`). Le manifeste `app` ne gagne toujours aucune
  facette ; ses réglages déclarent les process qu'ils périment (`stales`, comme `Param.stales`),
  le pipeline ne garde que les champs hors schéma (`WAMA_APP_GENERATION_ROUTE §10.6`, position
  commune du 05/10).

---

## 4. Facettes AUJOURD'HUI absentes/codées en dur → à formaliser

`version`, `world` explicite, les **drapeaux de capacité** (`has_realtime`/`instant_preview`/
`export_binding`/`supports_profiles` — dans les conventions, pas un registre lisible), le **modèle
d'item/statuts/champs résultat** (répété par app, statuts non uniformes), les **endpoints** (convention,
pas manifeste), le **layout dossiers filemanager** (ajout manuel), la **stratégie batch** (fk vs through),
les **besoins de modèles** de l'app. Le manifeste `app` les rend explicites.

> *MAJ 2026-10-31 (mesuré)* : la liste ci-dessus est celle de juillet. Sont désormais DÉCLARÉS ou
> EXTRAITS : `world` (déclaré dans `APP_CATALOG`, lu par `app_registry.app_world`, `app_registry.py:1290`),
> les drapeaux de capacité (lus par l'accesseur `app_capabilities`, `builtin/app.py:383-413`), le
> modèle d'item, les endpoints RÉELS et les tâches (`builtin/app.py:507-583`), les statuts
> (`job_status_values()`), la stratégie batch (`batch_link_model`, `model_spec`) et les modèles
> (facette `models`, références au catalogue). **Restent à formaliser** : `version`, les champs
> RÉSULTAT, le layout dossiers filemanager.

> **Réserve de fidélité (recadrage 2026-07-21)** : la grille de conformité SURESTIME l'avancement ;
> plusieurs mécanismes ne sont généralisés que sur l'app de référence **Transcriber**. Le schéma décrit
> la CIBLE ; le round-trip révélera où le code réel diverge de la cible (double usage : trous de schéma
> ET mécanismes non généralisés).

---

## 5. Provenance (où chaque facette vit aujourd'hui)

> Table courte SUPPRIMÉE (2026-07-25, plan doc B11) : le mapping facette → registre → consommateurs
> avec `fichier:ligne` vit dans **`WAMA_APP_GENERATION_ROUTE.md §1`** (le « terrain », vérifié au
> code). Le triangle des 3 docs : SPEC = ce qui est déclaré · ARCHITECTURE = les flux · ROUTE = le
> réel — ne pas maintenir de copie du terrain ici.

## 6. Plan de construction (proposé)

1. ✅ **Socle** : modèle `Manifest` (enveloppe + `body` JSON + `manifest_kind` + ScopedVisibility) +
   registre `MANIFEST_KINDS` (schéma + ingest_fn + projection par kind) + validation.
2. ✅ **Ingest** générique : `validate → sandbox(private) → test → promote`, idempotent/transactionnel/
   réversible + `verify` (diff). Back-link `_manifest_key` sur les entrées dérivées.
3. **Kind `app`** de bout en bout : projection vers les registres du §5 (ingest) + **extraction** inverse
   (générer le manifeste d'une app existante depuis les registres) pour le round-trip.
   - ✅ **Extraction** : `extract_app` (12 facettes ; 13 depuis `data`, 2026-08-18) — fait.
   - ✅ **Projection `access`** (write-back) : `write_back_app`/`un_write_back_app` (hooks renommés
     2026-08-05, ex-`project_*`) → `AppAccessPolicy`, dry-run/idempotent/réversible, round-trip non
     destructif validé (2026-07-23). **1re facette réellement écrite.**
   - ~~⏳ **Projection des 9 autres facettes = CODE-GEN** (models.py/urls/params/nœud studio…) — chantier.~~
     🔄 *(MAJ 2026-10-31)* : **10 facettes projetées** (`PROJECTED_FACETS`, `builtin/app.py:836-837` —
     `access` + 9 en code) ; `processing` en projection partielle (urls ; tasks/models CREATE-ONLY,
     `builtin/app.py:843-845`) ; `models` reste en code-gen.
4. ✅ **Round-trip** : extraire le manifeste d'une app existante → régénérer en sandbox → diff → itérer
   (`manage.py manifest_roundtrip`, `manage.py app_regen_check` — constaté le 2026-10-31).
5. ✅ Puis kind `dataset` (modèle tiers généralisé — enregistré `builtin/dataset.py:255`), et
   convergence `app` (APP_CATALOG ⟷ GENERIC_APPS : les E/S de `GENERIC_APPS` sont DÉRIVÉES des
   ports, `studio/services/generic_runner.py:125` `_derive_io_from_ports`) — constaté le 2026-10-31.

---

## 6bis. Kind `plugin` — CANDIDAT acté sur le principe (Fabien, 2026-08-19), non implémenté

> Né de la réflexion sur le **monde DATA** (modèle BIND : charger à chaud des plugins de
> visualisation/traitement synchronisés dans une session d'analyse). Le bornage complet
> fonction/librairie/plugin — avec ses tests falsifiables et ses exemples — est consigné dans
> **`WAMA_DATA_FUNCTION_CARDS.md §7ter`** (document de référence du monde data) ; on ne le
> recopie pas ici. Cette section ne retient que ce qui touche AU FORMALISME.

**Ce qui justifie un 8ᵉ kind** (et pas un simple `library` ou une `function`) : un plugin déclare
① un **point d'extension** (où il se branche), ② un **contrat de session** (synchronisation avec
les pairs co-chargés), ③ des **contributions UI**. Aucun autre kind ne porte ces trois-là.
Formule retenue, calquée sur les marketplaces (pytest `entry_points`, VSCode `contributes`) :
**plugin = librairie + point d'extension déclaré**.

**Composition attendue** (rien de neuf, `requires` existant) :
`plugin` → `library` (ses dépendances) + `function`(s) (ses traitements) ; `pipeline` → `plugin`(s) ;
`pipeline` → `pipeline`(s) (type de nœud `pipeline`, décidé le 2026-09-15, codé le 2026-11-02, `WAMA_APP_GENERATION_ROUTE.md §10.6` 3.1 — ⏳ l'export ne déclare pas encore ce `requires`) ;
`project` → `pipeline`(s). **Règle** : un plugin RÉFÉRENCE ses traitements, il ne les CONTIENT pas —
sinon il devient une boîte noire et l'héritage de capacités par le studio tombe.

**⚠ Ce qui N'EST PAS un plugin** : un mécanisme transversal (`wama/common/mecanismes.py`). Un
mécanisme est adressé par le DÉVELOPPEUR à l'écriture du code et se mesure en ADOPTION ; un plugin
est chargé par l'UTILISATEUR à chaud et se mesure en COMPATIBILITÉ + SYNCHRONISATION. Une tentative
d'encoder la notion de plugin DANS le registre des mécanismes (champ `resolu_par`) a été faite puis
**retirée le 19/08** sur arbitrage Fabien : « ne pas mettre les deux ensemble ». Un plugin réutilise
des mécanismes ; il n'en est pas une espèce.

### 6bis.1 Collision de sens à trancher : `library` extraite vs autorée

Le kind `library` désigne aujourd'hui **une distribution tierce installée** (extraction mécanique
`importlib.metadata`, clé = nom PyPI, version obligatoire). Or le monde data appelle « librairie »
un **ensemble WAMA-interne** de fonctions livrées ensemble (ex. le traitement cardiaque : pics,
correction, intervalles RR, rythme). Deux sens sous un mot = le flou qui produit les mauvais
bornages.

Le formalisme **résout déjà ce cas sans nouveau kind** grâce à la distinction §1 EXTRAIT vs AUTORÉ :
- `library` **extraite** (`source.type = extract`) = paquet tiers, aujourd'hui le seul cas ;
- `library` **autorée** (`source.type = authored`) = ensemble WAMA versionné, avec ses dépendances
  propres et l'inventaire des fonctions qu'il expose.
**À acter explicitement avant la première librairie autorée** — sinon les deux sens cohabiteront
en silence.

> ⚠ *Constaté le 2026-10-31 (mesuré sur `manifests/libraries/*.json`, champ `source.type`)* :
> **38 `extract`, 17 `authored`, 1 `manual`**. `authored` sert déjà — au sens « librairie TIERCE non
> extractible par pip » (voie vendor, dépôt GitHub : `libretranslate.json`, `source.ref =
> github:LibreTranslate/LibreTranslate@…` ; §7.4-3), pas au sens « ensemble WAMA-interne ». La
> collision annoncée a donc eu lieu : **le sens d'`authored` reste une décision de Fabien**.

## 7. COMPOSITION des manifestes — « une app = app + model(s) + library(ies) »

> **Cadrage Fabien, 2026-08-02.** Le manifeste d'app ne doit PAS tout décrire : il **compose**.
> Ce qui appartient à un modèle vit dans un manifeste `model`, ce qui appartient à une brique
> open-source dans un manifeste `library`. C'est la règle zéro-duplication appliquée aux
> manifestes eux-mêmes — sans quoi le manifeste d'app redevient un monolithe qui recopie tout.
>
> C'est aussi ce qui rend praticable l'objectif suivant : **wama-dev-ai traduit un projet GitHub
> en manifeste `library`**, unité autonome et réutilisable, que plusieurs apps référencent.

### 7.1 Qui possède quoi (frontière de responsabilité)

| Kind | Possède | Ne possède PAS |
|---|---|---|
| `library` *(livré 2026-08-03, `builtin/library.py`)* | dépôt, licence, version, install, points d'entrée, capacités techniques, contraintes (GPU, OS) | l'usage qu'une app en fait |
| `model` | poids, **`license`**, **`platform_ref`**, modèle de base (`base_model` + `base_model_relation`), VRAM/disque, format, capacités, provenance — `hf_id` RETIRÉ le 2026-10-27 (ci-dessous) | le réglage utilisateur qui le pilote — **et tout ce que la DÉCOUVERTE établit** |
| `app` | identité, ports, params, permissions, cycle de vie, **et les RÉFÉRENCES** vers `model`/`library` | tout ce qui précède — jamais recopié |

#### 7.1 bis — `model` : deux champs ajoutés, et une frontière qui lui est propre (2026-08-05)

`identity.license` et `identity.platform_ref` sont **déclarés au manifeste et projetés dans
`AIModel`** (`write_back_model`, cf. §7.1 ter). Motif mesuré : 0/129 modèles portaient une licence,
alors que l'audit de licences WAMA doit s'aligner sur le composant le moins permissif ; et le lien
vers la plateforme était conditionné à `hf_id`, absent sur les 70 modèles que leur app découvre par
scan disque.

`platform_ref` porte le **fait** (`huggingface:org/repo`, `ollama:gemma4`, `roboflow:projet/3`),
pas l'URL. L'URL en est un rendu, dérivé par `AIModel.platform_url` depuis la FICHE que la
plateforme déclare au registre des sources (`ExternalSource.model_page`, lue par
`external_sources.model_page_url` — depuis le 2026-10-22 ; une table plateforme → gabarit vivait
avant dans `AIModel`, en double du registre). Stocker 129 chaînes d'URL, ce serait 129 chaînes à
corriger le jour où une plateforme change son schéma d'adresse.

**2026-10-27 — `identity.hf_id` est RETIRÉ, `platform_ref` seul** (décision
de Fabien : « ne garder que `platform_ref` »). Mesuré ce jour sur les 818 lignes du catalogue : 397
portaient la même valeur des deux côtés (`hf_id` = le dépôt de `huggingface:<dépôt>`), aucune ne
portait `hf_id` sans `platform_ref`, une seule différait — un GGUF du Hub tiré par Ollama, où `hf_id`
disait le modèle qu'il EST et `platform_ref` le dépôt d'où viennent ses poids. Depuis :
- plus AUCUN lecteur de `hf_id` dans le code : le dépôt du Hub se DÉRIVE de `platform_ref`
  (`external_sources.hf_repo`, `AIModel.hf_repo`), et les déclarations d'app et de moteur disent
  `platform_ref` (`AGENTS.md`, checklist §4) ;
- le second fait a son nom, celui de la carte du Hub : **`identity.base_model` +
  `identity.base_model_relation`** (`adapter`, `finetune`, `merge`, `quantized`), en PAIRE, projetés
  dans `extra_info` au déclaré seulement (règle des publications) — `AIModel.quantized_base` les lit
  pour une quantification ; le `base_model` d'une LoRA reste celui de la déclaration de l'app ;
- ✅ le même jour, avec le corpus : `identity.hf_id` n'est plus ni extrait ni projeté
  (`builtin/model.py`) et un manifeste qui le porte est REFUSÉ par le validateur
  (`RETIRED_IDENTITY_FIELDS`), ses producteurs `wama-dev-ai` ne l'écrivent plus (et ôtent, par la
  même liste, celui qu'un LLM nourri d'anciens exemples écrirait encore), la copie
  `extra_info['hf_id']` de la découverte est partie, les 624 occurrences de `manifests/models` aussi,
  puis la colonne (migration `model_manager/0031`, `REMOVAL_LEDGER` R181). Gardes :
  `model_manager/tests/tests_platform_ref_only.py` (budget AST `HF_ID_BUDGET`, corpus, extraction).

**2026-10-28 — `body.quality.defect` : un DÉFAUT MESURÉ, validé par un administrateur** (décisions
de Fabien). `{label, reason, source}` — trois chaînes, la source DATÉE (le validateur refuse un
constat sans date). Projeté dans `extra_info['quality_defect']` au déclaré seulement (règle des
publications : un manifeste muet ne dégrise rien ; la révocation, `un_write_back_model`, dégrise),
clé collante du sync — sœur d'`exclusion` (une décision qui ÉCARTE, `is_available=False`) : un
défaut GRISE le modèle dans tout select de modèle avec sa raison et le sort du tirage
automatique, il reste listé. Il n'est jamais écrit d'office : une mesure sans référence qui prend
un modèle en défaut sur la même entrée et avec les mêmes réglages qu'un autre modèle le PROPOSE
(« Propositions à valider »), un administrateur valide (`ROADMAP §16.5`). Chaîne et gardes :
`WAMA_QUALITE` (bloc « pourquoi Albert ne rend pas tout le texte »),
`model_manager/tests/tests_measured_defects.py`. 1ʳᵉ entrée : `albert:whisper-large-v3`.
⏳ Un défaut devra porter la CATÉGORIE d'entrée où il a été mesuré (`WAMA_QUALITE §4.4`).

> ⚠ **Frontière propre au kind `model`, à ne pas calquer sur `library`.**
> Une librairie se **déclare** ; un modèle se **découvre** — il existe parce que des poids sont sur
> le disque. Le manifeste ne crée donc jamais de ligne, et n'a pas autorité sur l'état runtime ni
> sur les FAITS mesurés (`is_downloaded`, `is_loaded`, `local_path`, `vram_gb`).
>
> ~~`capabilities` appartient à la découverte, qui la réécrit en entier à chaque passage~~ —
> **constat du 2026-08-05, dépassé depuis** (relu et corrigé le 2026-09-18). Le sync ne remplace
> plus un fait par un `{}` (31/08), et `write_back_model` projette `capabilities` par **fusion
> clé par clé** (`merged_capabilities`, 18/09) : sur une ligne servie par une app, la découverte
> garde ses valeurs (elle lit les flags sur les classes de backend) et le manifeste comble les
> clés absentes ; sur une ligne orpheline (snapshot HF générique, Ollama, cloud), le manifeste
> tranche clé par clé. C'est la route cible de `ROUTE §F4b` : *manifeste (identité, capacités,
> moteur) → catalogue, la découverte gardant les faits*.

**2026-08-26 — `body.prompts.contract` rejoint les champs déclaratifs projetés** (avec
`license`/`author`/`platform_ref` — et `hf_id`, retiré le 2026-10-27) : le contrat de SORTIE du prompt attendu par le
modèle (markdown, anglais — longueur, structure, sections, tags de paroles…), projeté vers
`AIModel.prompt_contract` (colonne préservée par le sync — c'est PRÉCISÉMENT parce que
`capabilities` est réécrit qu'il fallait une colonne). Consommé par l'enrichissement de
prompts : le skill d'app porte la méthode, le modèle son contrat, qui prime sur les règles
de longueur/format du skill (doctrine et chaîne complète : `prompt_skills/README.md`,
`WAMA_LLM.md §Skills`). Motif : MusicGen attend 30-80 mots, MiniMax-Music3 attend 250-450
mots sectionnés — même app, contrats opposés.

**2026-08-27 — `body.composition` rejoint les champs déclaratifs projetés** : l'ANATOMIE d'un
modèle multi-composants + son moteur d'exécution, projetée vers `AIModel.composition`
(JSONField préservé par le sync, même motif de colonne que `prompt_contract`). Forme :

```json
"composition": {
  "components": [
    {"role": "language_model", "pattern": "MiniMax-Music3-language_model-Q8_0.gguf", "format": "gguf"},
    {"role": "vocoder",        "pattern": "MiniMax-Music3-vocoder-F32.gguf",         "format": "gguf"}
  ],
  "runtime": {"engine": "audio-cpp"}
}
```

Rôles OUVERTS (chaque architecture a les siens), forme FERMÉE (`role` unique + `pattern`
requis ; `runtime.engine` requis si `runtime` présent). **Deux consommateurs, une
déclaration** : l'installation dérive ses `allow_patterns` des patterns
(`model_installer.patterns_from_composition` — le jeu COHÉRENT, jamais le dépôt entier d'un
repack multi-quantisations, jamais un composant isolé) ; le backend composé (~~à venir, étape 4
du plan Music3~~ livré — `common/backends/audiocpp_backend.py:139-151` `_composition()`, constaté le
2026-10-31) dérive quoi charger et avec quel moteur. Vide = modèle mono-fichier, cas
général inchangé. Motif : MiniMax-Music3, 5 GGUF = 1 modèle — l'anatomie était passée à la
main en `allow_patterns` le 27/08, désormais elle est DÉCLARÉE (premier manifeste porteur :
`manifests/models/huggingface__Serveurperso~MiniMax-Music3-GGUF.json`).

**2026-11-06 — l'anatomie est COMPLÈTE ou refusée, et `composition.excluded`** (demande de
Fabien : « on ne laisse pas de trou ou de piège »). Les composants DEVIENNENT ce qu'on tire : un
morceau oublié est un fichier absent, que le moteur irait chercher seul au premier usage — vécu sur
la proposition d'anatomie d'ACE-Step 1.5 (encodeur de texte `Qwen3-Embedding-0.6B/` et
`silence_latent.pt` oubliés). Règle (`model_installer.anatomy_gaps`) : chaque fichier de poids de
ce que l'installation apporte (le dépôt du Hub, les fichiers déclarés du pilote `files`, ou le
dossier d'une version que le pilote `github` a posée — `anatomy_inventory`) est **réclamé** par un composant, **reconnu** comme variante par une règle
existante (précision, quantisation — GGUF et exports ONNX compris —, shards concurrents, jumeau de
format, copie monofichier ou imbriquée d'un pipeline, poids d'un autre moteur, conversion
`transformers` d'un `.nemo` ou d'un `.pt`), ou **écarté** avec sa raison :
`"excluded": [{"pattern": "safety_checker/*", "reason": "filtre facultatif, chargé à None"}]` —
un autre modèle rangé dans le même dépôt (les YOLO), un composant facultatif, un fichier
d'entraînement : rien dans un nom ne les distingue d'un oubli, ils se DÉCLARENT — par le
constructeur partagé (`common/utils/model_anatomy.model_composition(engine, components,
excluded)`, qu'empruntent désormais l'imager et les découvertes touchées). Un motif qui ne
désigne aucun fichier est un trou aussi. Trois lieux, une règle : l'installation refuse avant de
tirer (`install_from_spec`), « Valider » refuse ce que le plan montre (confrontation du kind,
`ManifestKind.confront` → `builtin/model.confront_model`, jouée par `proposals.plan/apply` seuls —
la validation de FORME reste sans réseau), la carte `check_model_completeness` nomme les lignes
installées (`anatomy_incomplete`). Mesuré ce jour sur les 44 anatomies du catalogue : 13
incomplètes avant correction, 1 après — `anonymizer:yolo:yolo11l_face_plate_signs.pt`, poids renommé à
la main avant la chaîne (son motif ne désignait aucun fichier du dépôt) ; renommé au nom PUBLIÉ le
même jour, sa clé suivie par `succession.rekey`. **46 sur 46** une fois les deux versions GitHub
confrontées.

**2026-10-31 — `runtime.loaded_by`** (demande de Fabien après l'inventaire des modèles installés
sans backend) : le MODULE qui charge le modèle lui-même, hors de tout backend —
`{"runtime": {"loaded_by": "wama.model_manager.services.bench"}}`. `runtime` exige désormais
`engine` OU `loaded_by` (`builtin/model.py::_validate_composition`). Cinq lignes le portent, posées
par leur découverte (`model_registry`) : LPIPS (le banc), Smart Turn (le service vocal), le
reconnaisseur de gestes (servi au navigateur par `scene_views`), le Face Landmarker et YOLOPv2 (le
Lab). Le verdict d'exécutabilité ne condamne plus une ligne qui le déclare
(`backends.manager.backend_missing`), la dérivation du moteur depuis le disque ne lui en invente
pas, `check_backend_links` la range parmi les cas normaux, et une garde exige que chaque module
nommé existe (`model_manager/tests/tests_model_loaded_by.py`). Le même jour, la moitié BACKEND
du lien est lue : un backend qui écrit `{'model_key': …}` dans son `SUPPORTED_MODELS` donne son
moteur à la ligne qui n'en a pas (`backend_inventory.BackendEntry.served_keys`,
`model_registry._overlay_engines_named_by_backends` — pyannote community-1).

**2026-11-06 — une ligne `loaded_by` porte aussi son MOTEUR, et le `requires` d'un modèle a UNE
dérivation** (demande de Fabien : « compléter le manifeste pour tout aligner »). Le trou : le
manifeste de Whisper tiny sortait `requires: []` alors que la sonde des langues tourne sur
faster-whisper — `library_requirers` n'aurait rien refusé à sa désinstallation. La règle suit le
registre `backends` (*le modèle porte son moteur, un moteur est une librairie*) et le précédent du
Face Landmarker (`engine: mediapipe` + `loaded_by` depuis le 31/10) : `engine` dit la LIBRAIRIE qui
exécute le modèle, `loaded_by` dit qui l'appelle à la place d'un backend. Six lignes sur sept le
déclarent, posées par leur découverte : `faster-whisper` (tiny), `onnxruntime` (Smart Turn),
`lpips`, `torchscript` (YOLOPv2, le moteur d'EgoBlur), `doctr` (l'orientation de page),
`mediapipe` ; le reconnaisseur de gestes, exécuté par la version NAVIGATEUR de MediaPipe, n'en
déclare délibérément aucun. Trois conséquences, chacune tenue par une garde
(`tests_model_loaded_by`, `tests_manifest_library.ModelLibrariesSinglePathTest`, contre-épreuves
rouges) :
- **le routage** : `backends.manager.backend_for_model` ne confie jamais une ligne `loaded_by` au
  backend de son moteur (tiny n'est pas servi par `WhisperBackend`) — la règle de `backend_missing`,
  et celle du relevé sans import du vivier (`backend_inventory._models_by_app`, que lisent
  `inventory()` et `app_backend_entries`), ramené à la revérification ;
- **une seule dérivation modèle → librairies** : `library_index.model_libraries` (l'exécutant, puis
  ses librairies), que lisent le manifeste de modèle (`builtin/model._requires_librairies`) et la
  jambe backends d'une app (`librairies_des_backends`, inchangée sur les dix apps, mesuré). Le
  manifeste de modèle avait SA lecture — le premier backend du moteur, les noms de
  `pip_install_spec` pris pour des distributions — et ratait `python-doctr` (`REQUIRED_PACKAGES =
  ['doctr']`), `pyannote-audio` (`pyannote.audio>=3.3.1`), les `REQUIRED_PACKAGES` de Qwen3-ASR ;
  65 manifestes de modèle corrigés par l'export ce jour-là, plus celui de l'orientation de page,
  absent du corpus ;
- **un seul traducteur nom → librairie** : `library_index.seeded_libraries` (distribution lue telle
  quelle, nom d'import par la distribution INSTALLÉE — `onnxruntime` → `onnxruntime-gpu`, jamais la
  version processeur semée qui la masquerait) ; un moteur se lit par `engine_libraries` (import,
  puis distribution, puis paquets que déclarent les backends qui le pilotent : `torchscript`). Le
  module d'un `loaded_by` n'est PAS mesuré à l'import : le banc importe aussi ultralytics et
  transformers pour d'autres mesures que LPIPS.

#### 7.1 ter — hooks par kind, MESURÉ le 2026-08-05

> Les hooks s'appellent `write_back`/`un_write_back` depuis le 2026-08-05 (`kinds.py:52-57` —
> `project` était homonyme du kind `project`). Fonctions réelles : `write_back_app`,
> `write_back_library`, `write_back_model`.

| Kind | `validate` | `extract` | `write_back` |
|---|---|---|---|
| `app` | ✅ | ✅ | ✅ |
| `library` | ✅ | ✅ | ✅ |
| `model` | ✅ | ✅ | ✅ *(depuis le 2026-08-05)* |
| `function` · `pipeline` · `project` | ✅ | ✅ | ❌ |
| `dataset` | ✅ | ❌ | ❌ |

`write_back_model` **ne crée jamais de ligne**, contrairement à `write_back_library` : faire naître un
`AIModel` depuis un manifeste fabriquerait un modèle fantôme, sans fichier de poids, que la
sélection pourrait pourtant retenir. Cible absente → la projection le **dit** et ne fait rien
(« lancer `sync_models` d'abord »). Dry-run par défaut, idempotente, `preserved` explicite.

### 7.2 État MESURÉ de la composition (2026-08-02 — photo HISTORIQUE, dépassée par §7.4)

| Constat | Mesure |
|---|---|
| Kinds enregistrés | `app`, `dataset`, `function`, `model`, `pipeline`, `project` — **`library` absent** *(périmé : livré 2026-08-03)* |
| Références déjà présentes | `body.models.catalog_keys` — le principe est **amorcé**, pas inventé |
| Champ de référence dans l'ENVELOPPE | **aucun** (`requires`/`references`/`depends_on` inexistants) *(périmé : `requires` livré, `envelope.py:45` + `resolve_requires`)* |
| Références de modèle résolvables | ✅ **91 / 91 (100 %)** depuis `ad68e75` — était **0 / 42** |

**Le lien app↔modèles EXISTAIT** et n'était pas à réinventer : `AIModel.source` porte l'app, et
`model_key` vaut `{source}:{id}` (convention documentée dans `model_registry.py`). La facette
`models` lisait à la place `wama/<app>/utils/model_config.py`, une source **parallèle et
incomplète** : 42 modèles déclarés là où le catalogue en lie **91** aux apps, et **0 pour
l'anonymizer alors qu'il en a 48** — le corpus enseignait qu'un anonymizer n'utilise aucun modèle.

`model_config` reste cité en provenance (`source_attr`) : il porte le **câblage runtime par app**,
que le catalogue n'a pas. Autre facette, pas redondance.

> ⚠ Leçon : je m'apprêtais à déduire une règle de namespace `<app>:<clé>` à la main et à
> conclure « 31/42, il manque 11 modèles au catalogue ». Les 11 « manquants » étaient un artefact
> de ma mauvaise source. **Chercher l'accesseur existant avant de déduire une règle.**

### 7.3 Conception retenue

1. **Déclarer les références dans l'ENVELOPPE, pas dans une facette.** Une référence enfouie
   dans `body.models` n'est résolvable que par du code qui connaît cette facette. Un champ
   uniforme rend la composition **kind-agnostique** :
   ```json
   "requires": [
     {"kind": "model",   "key": "transcriber:whisper"},
     {"kind": "library", "key": "faster-whisper"}
   ]
   ```
2. **Un résolveur unique** `resolve_requires(manifest)` → manifestes cités, et un **validateur**
   qui refuse une référence pendante. `manifest_export` doit refuser d'exporter un manifeste aux
   références cassées : le corpus est du matériel d'apprentissage (cf. ARCHITECTURE §6ter).
3. **Clés canoniques = celles du catalogue** (`AIModel.model_key`, namespacé). La facette
   `models` de l'app cesse de porter des clés locales : elle porte des références canoniques.
4. **`library` se crée en dernier**, une fois 1–3 en place : il n'apporte rien tant que le
   mécanisme de référence n'existe pas.

### 7.4 Ordre d'exécution (rien ne doit être fait avant ce qui le précède)

1. ✅ **FAIT (`ad68e75`)** — `body.models.catalog_keys` porte les clés canoniques du catalogue :
   **91/91 résolvables**.
   ⚠ *Constat corrigé le 2026-11-02 (décision de Fabien)* : la facette ne lit plus le seul
   `AIModel.source`. Elle unit les lignes de l'app et les modèles que ses selects de catalogue
   PROPOSENT (`param_schema.catalog_choice_keys`), sans les lignes DÉSINSTALLÉES — un modèle
   `huggingface:` que l'app sert (olmOCR-2 pour le Reader) en était absent, avec ses librairies.
   Le corpus la suit à chaud (`manifests/corpus.follow_apps`). Détail :
   `wama/model_manager/PROSPECTION_PIPELINE.md` §« Session du 2026-10-29 », point 2.
2. ✅ **FAIT (2026-08-03)** — Champ `requires` dans l'enveloppe (`envelope.py`, validé en forme),
   émis par `extract_app` depuis la facette `models` (même source, deux projections) ;
   `ingest.resolve_requires(manifest)` → `(résolus, pendantes)`, kind-agnostique via
   `get_kind(kind).extract(key)` ; `ingest.validate()` refuse toute référence pendante — donc
   `manifest_export` refuse un corpus aux références cassées, par construction. Probes : les
   4 requires du transcriber se résolvent en manifestes `model` ; une clé fantôme ET un kind
   inconnu (`library`) sont refusés. Corpus régénéré : les 10 manifestes portent `requires`
   (91 références au total).
3. ✅ **FAIT (2026-08-03)** — Kind `library` (`builtin/library.py`) : extraction MÉCANIQUE des
   métadonnées du paquet installé (`importlib.metadata` — version, licence, dépôt, `install.pip`,
   `entry_points`, dépendances PEP 508 normalisées) ; `constraints` reste VIDE plutôt qu'inventé
   (c'est le rôle wama-dev-ai, étape 4, qui le remplira). `manifest_export --kind library <clé>`
   sème une library au corpus (`manifests/libraries/`) — semis EXPLICITE, aucun critère de
   sélection inventé ; sans clé la commande rafraîchit/contrôle les libraries déjà semées.
   Semée : `faster-whisper` (l'exemple du §7.3). Probe de composition : un manifeste d'app
   avec `{"kind": "library", "key": "faster-whisper"}` valide et se résout ; la même référence
   était refusée avant la création du kind.
   ✅ **Le critère de semis existe depuis le 2026-11-06 (décision de Fabien)** : *« si des
   librairies sont utilisées dans les applications de WAMA, elles doivent être dans le registre
   des librairies »* — toute distribution que le code WAMA importe (`library_index.scan_imports`,
   les trois racines `wama`, `wama_lab`, `wama_data`) est semée, socle compris (le socle reste
   hors de tout `requires`, point 5). Le semis garde sa route (`manifest_export --kind library
   <clé>`, puis la projection `ingest.write_back`) ; ce qui change, c'est qu'il n'est plus
   facultatif : `library_index.unseeded()` doit être vide, tenu par
   `tests_manifest_library.EveryImportedLibraryIsSeededTest`. Ne compte pas : le code tiers
   VENDORISÉ sous `settings.BACKEND_VENDOR_DIR` (ses imports sont ses dépendances, et la librairie
   vendorisée est elle-même au registre), ni une variante d'un module déjà fourni par une
   distribution semée (`opencv-contrib-python` à côté d'`opencv-python` ; `phonemizer-fork`,
   installation MASQUÉE : les fichiers sur disque sont ceux de `phonemizer`). Un import sans
   distribution installée est déclaré un par un dans la garde, avec sa raison. Semis du jour : 55
   librairies (dont le socle, pandas, pydub, py7zr, rarfile, pypandoc, pdf2docx, weasyprint) ;
   l'auteur se borne désormais au registre à l'extraction (`author_name`, le pendant de
   `licence_courte` : la liste d'adresses de `pydantic`, 513 caractères, cassait la projection).
   ✅ **Voie vendor (2026-09-30, ROADMAP D-a)** : `install` porte `pip` **ou** `vendor`
   (`{repo: "owner/name", commit: <SHA 40>, engine, patch?: "patches/….diff", ignore?: [...]}`),
   jamais les deux — pour une librairie que pip ne sait pas installer (MuseTalk, CodeFormer,
   TripoSR). Un tel manifeste est AUTORÉ (`source.type = "authored"`) : `extract` le relit au
   corpus au lieu d'interroger `importlib.metadata`, donc `manifest_export` le VALIDE au lieu de
   le déclarer « extraction impossible ». Projeté au champ `Library.vendor` ; installé par
   `install_library` (`model_manager/services/vendor_installer.py`).
4. 🔄 **PILOTE LIVRÉ (2026-08-02)** — rôle « librarian » (`wama-dev-ai/prompts/librarian.txt` +
   `run_librarian.py`) : one-shot borné (pas de boucle agentique), corpus en exemples, sortie
   validée MÉCANIQUEMENT (`ingest.validate`) et diffée contre `extract_library` quand la lib est
   installée ; écrit en `outputs/` avec `PENDING_HUMAN_VALIDATION`, n'ingère jamais.
   Mesuré : mode `--dist` (métadonnées installées) → manifeste **valide, accord total** avec
   l'extraction mécanique (qwen3.5:9b) ; mode `--repo` (GitHub : pyproject+README) → valide
   structurellement, **`null` honnêtes** là où les sources ne prouvent pas (version dynamique
   lue depuis `version.py`, licence dans un fichier non fourni) — zéro invention, la règle
   « null plutôt que plausible » tient. Récolte élargie (requirements/LICENSE d'abord, README
   tronqué en dernier) codée mais non re-testée (session interrompue par le crash hôte du
   2026-08-02 18:09). Reste : passe de revue humaine des sorties, puis semis au corpus des
   libraries validées. Prochain cas `--repo` acté : **LibreTranslate** (lib NON installée —
   manifeste depuis le dépôt), préalable de la 11ᵉ app Translator générée de zéro.
   ✅ *2026-10-16* : LibreTranslate semé (`manifests/libraries/libretranslate.json`, `authored`, depuis
   le dépôt — commit `5a673baa`) ; le Translator est né au bac à sable (`wama/translator_01/`).
   Reste 🔄 la revue humaine générale des sorties.
   ✅ *2026-11-06* : `--dist` lit une distribution NON installée sur PyPI
   (`role_utils.pypi_metadata`, source déclarée `pypi`), et les faits publiés — canal
   `nom==version`, `requires_python`, version, dépendances sans les extras — sont posés par
   `enforce_published_facts`, quoi qu'ait écrit le LLM ; source `extract`, `pypi:<nom>==<version>`.
   Cas qui l'a fait écrire : `gguf`, publié depuis un sous-dossier de `llama.cpp` (le `--repo`
   aurait lu le paquet de la racine) ; installé par la route le jour même.
   ✅ *2026-11-06 (soir)* : `rosbags` (extracteurs rosbag du cam_analyzer, recopiés le 2026-02-15 et
   jamais installés par WAMA) par la même chaîne, celle de l'assistant : `plan_library_integration`
   → `dev_run_role(librarian, dist=rosbags)` (proposition valide, faits PyPI) → Valider
   (`proposals.apply`) → `install_library rosbags` en plan (`retrogradations: []`, trois ajouts :
   apsw, rosbags, ruamel.yaml) puis `--allow --apply` (décision de Fabien) → corpus.
   ⚠ **Valider une librairie NON installée n'écrit rien au corpus, et le dit écrit** :
   `corpus.follow` lance `manifest_export`, qui extrait du paquet installé (rien à extraire), puis
   rend « écrit » sans regarder. Le corpus se sème donc APRÈS `install_library` (`gguf`, `rosbags`)
   — ⏳ que `follow` dise ce qu'il a réellement fait.
5. ✅ **FAIT (2026-08-12) — semis de la composition du pilote B + STRATES de dépendances.**
   8 libraries semées mécaniquement (`manifest_export --kind library` : transformers, torch,
   torchaudio, pyannote-audio, librosa, soundfile, openai-whisper, vibevoice — extraction
   `importlib.metadata`, licences absentes = null honnête) → **transcriber `requires` = 4
   modèles + 9 libraries, 13/13 résolus**. Règle des TROIS STRATES actée :
   - **strate 1 — SOCLE PLATEFORME** (`library_index.SOCLE_PLATEFORME` : Django, celery,
     redis, numpy, requests) : contrat d'exécution commun aux 10 apps, JAMAIS cité dans un
     `requires` d'app (exclu même si semé — la plateforme n'est pas une dépendance du
     workload, cf. k8s/Backstage). Étendre la liste = décision d'architecture.
   - **strate 2 — libraries métier** : la jambe `requires` (importée ∩ semée ∩ hors socle).
   - **strate 3 — outils système** (ffmpeg, pandoc, chromium…) : NON déclarés (trou #15,
     ROUTE §11), hors périmètre du kind `library` (binaires, pas des distributions Python).
   ⚠ Limite assumée : l'extraction library lit le venv COURANT (*corrigé le 2026-11-06 : le
   corpus s'extrait de venv_linux, le runtime réel — la ligne disait venv_win*) ;
   si les deux venvs divergent sur une version, `manifest_export --check` le signalera —
   c'est le détecteur de dérive voulu, pas un bug.

### 7.5 CIBLE (non implémentée) — arête `uses` : capacités héritées entre apps

> **ACTÉ 2026-08-12 (Fabien), chantier = marche D de la route (`WAMA_APP_GENERATION_ROUTE.md
> §10.4`, APRÈS la marche B) — la doctrine complète (3 espèces de chaînage, pilote, garde-fous)
> vit LÀ-BAS ; ici le seul FORMALISME.**

À côté de `requires` (dépendance de COMPOSITION : app → model/library, résolue à l'ingest),
une app pourra déclarer des arêtes de CAPACITÉ :
- `capabilities.provides: ["denoise_audio", …]` — capacités canoniques que l'app FOURNIT
  (même vocabulaire indexé sur la TÂCHE que les capacités-modèle) ;
- `capabilities.uses: [{"capability": "denoise_audio", "when": "pre_input",
  "optional": true}, …]` — capacités HÉRITÉES d'une autre app, réalisées au runtime par le
  pivot d'exécution existant (`launch_graph`/`execute_tool`), l'UI (case à cocher) étant
  auto-générée de la déclaration.

> ⏳ **Précisé le 2026-09-15 → `WAMA_APP_GENERATION_ROUTE.md §10.6` (points 3.2, 4.5, 7)** : une capacité
> héritée n'est plus « un micro-pipeline exécuté par `launch_graph` » : c'est un **process `optional`
> inséré dans le pipeline de la card**, dont le nœud est le process ou le pipeline de l'app fournisseuse,
> exécuté par le **moteur commun**. Restent à formaliser ICI : le **degré de liberté** d'un process
> (`required` / `optional` / place `open`, décision ouverte n°3 de §10.6) et la facette « **pipelines
> proposés** » du manifeste `app` (décision ouverte n°11).

Différence de nature : `requires` se résout à l'INGEST (le manifeste cible doit exister) ;
`uses` se résout au RUNTIME par le routage capacité→app (l'app fournisseuse est
interchangeable). Validation prévue : vocabulaire canonique fermé, `when` ∈
{pre_input, post_output}, refus d'un `uses` sans fournisseur déclaré au corpus.

**État courant du corpus** (couche factuelle auto-générée, ROADMAP §16.9 ①) :

<!-- WAMA:FAITS(modeles) — généré par « python manage.py doc_facts », ne pas éditer -->
- Manifestes du corpus (`manifests/apps/`) : **10**
- Références de modèles (`body.models.catalog_keys`) : **147/147 résolvables** contre le catalogue `AIModel.model_key`
<!-- /WAMA:FAITS(modeles) -->
