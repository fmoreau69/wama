# WAMA — Formalisme des manifestes (spécification de référence)

> **Schéma fonctionnel des flux (manifestes → ingest → app_gen → UI) : [`WAMA_MANIFEST_ARCHITECTURE.md`](WAMA_MANIFEST_ARCHITECTURE.md).**
>
> **Statut : socle IMPLÉMENTÉ (MAJ 2026-08-11).** Enveloppe + registre + ingest + les **7 kinds**
> vivent dans `wama/common/manifests/` (envelope/kinds/ingest/projection + `builtin/{app,dataset,
> function,library,model,pipeline,project}.py`, modèle DB `common.Manifest`) ; extract `app` = 12
> clés `APP_FACETS` ; **write-back réel sur 3 kinds** — `app` : 1 facette écrite au runtime
> (`access` → AppAccessPolicy, a75c01d) et **9** rapportées en `codegen_required` ; `library` :
> registre entier ; `model` : champs déclaratifs. Cette spec fixe le formalisme COMMUN + le schéma
> du kind `app` (8 facettes fonctionnelles F1–F8 = 12 clés). Les blocs annotés « cible » ci-dessous
> décrivent le schéma VISÉ, pas encore l'extract réel.

---

## 1. Principe : union discriminée

Tout manifeste = **enveloppe commune** + **`body` spécifique au kind**, validé contre le schéma du kind.
Un **registre `MANIFEST_KINDS`** keyé sur `manifest_kind` fait la validation et le dispatch. C'est ce qui
empêche de mélanger des manifestes sans rapport, et ce qui rend le formalisme extensible.

```yaml
# ── Enveloppe commune (TOUS les kinds) ───────────────────────────────
manifest_kind: app            # app | function | dataset | model | pipeline | project
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
(= `StudioPipeline.graph`), **`project`** (= `Project`, déjà fait).

> **Distinction EXTRAIT vs AUTORÉ** (dégagée en construisant `dataset`) : deux familles de kinds.
> - **Extraits** (`app`, `model`, `pipeline`) : l'objet existe DÉJÀ dans le code/DB → le kind fournit
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
  # (world = champ d'ENVELOPPE, pas de body — ✅ FAIT : media|data|lab|transverse, mapping
  #  GROUP_TO_WORLD dans builtin/app.py)
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
    # ÉTANCHÉITÉ : preview ET extract passent par UN SEUL accesseur (`studio_node_ports`/`app_ports`),
    # jamais par app_modes/app_registry en direct → un seul point de bascule le jour de la projection.
    # Le « PENDANT » (preview progressive/temporaire pendant le traitement, streaming « à la Suno ») =
    # une CAPACITÉ DÉCLARÉE (`capabilities.during_preview`/`streaming`), pas un mécanisme codé en dur :
    # le manifeste déclare QUELLES apps streament, la brique commune fournit le COMMENT. Même patron que
    # has_realtime/instant_preview et que le bouton de cycle ▶/⏹/↻. Plan détaillé preview = doc dédié.
  capabilities: {has_realtime, has_edit_page, instant_preview, batch,
                 export_binding: late|early, supports_profiles, has_url_import, has_youtube}
  # SORTIE = 3 CONCERNS SÉPARÉS (jamais surchargés — corrigé 2026-07-22, détail WAMA_APP_GENERATION_ROUTE §F2) :
  #   output_type   = catégorie média FIXE (ports/preview/routage) ; converter = 'mirror/any'
  #   output_format = mécanisme COMMUN hérité du converter (générique-par-catégorie ∪ app-spécifique) ; sélecteur download
  #   domains       = onglets, hint DÉCLARATIF, NON dérivé du type (converter=0 onglet ; imager≠enhancer même modalités)
  domains: [{id, label, icon}]         # hint déclaratif d'onglets (ex-APP_MODES.domains), reflète l'UI verbatim
  modes: [{id, label, icon, realtime, settings:[param_name]}]  # DÉRIVÉ des capacités-modèle (switch inspecteur), pas déclaré

  # F3 UI / INSTANCIATION  [params.py PARAMS_JSON — déjà source unique, inchangé]
  params: [ Param{name,type,label,icon,default,choices,options_source,show_if,
                  contexts:[item|batch|panel],advanced,chip,help_source,...} ]
  inspector: {model, detail_adapter, preview_adapter, file_field, user_field}   # Detail/PreviewRegistry
  # (cible ; extract actuel = detail_registered/preview_registered — présence, pas contenu)

  # F4 MODÈLES IA          [model_config.py + model_selector.select_model] — CIBLE, pas l'extract
  # réel : extract actuel = {catalog_keys, source_attr} (lecture best-effort de <APP>_MODELS) ;
  # `paths_key` non implémenté ; select_model non touché par l'extracteur (adoption runtime :
  # composer 07-21 + transcriber 07-24).
  models: {consumes: {source, model_types:[...]},
           selection: {requires:[cap], classes, vram_budget, prefer_loaded, priority},
           paths_key}

  # F5 TRAITEMENT          [models.py + tasks.py + urls.py — pattern répété, À DÉCLARER]
  processing:
    item_model, statuses:[PENDING,RUNNING,SUCCESS,FAILURE],
    result_fields:[output_file|result_text, used_backend, used_model],
    batch: {strategy: fk|through, nature_of},
    task, endpoints: STANDARD_ENDPOINTS                        # = ['index','upload','start','status',
    # 'download','delete','duplicate','update','start_all','clear_all','download_all',
    # 'global_progress'] (builtin/app.py:38) ; item_model/result_fields/batch/task = cible non extraite
    ingest: {source: source_url, target: <field>, mode: audio|media|smart}  # trou #14 : projette vers
    # WAMA_INGEST (common/utils/source_ingest.ensure_local_input). Capté par extract (transcriber/describer) ;
    # projection = write-back futur. Va de pair avec capabilities.accepts_url (→ génère la card d'import URL).

  # F6 PROMPTS / IA        [PROMPT_TARGETS + prompt_skills + tool_api]
  prompts: {targets:[{field,kind,model_field,source,default_model_type,enrich,domain_field,reference_field}],
            skills:["<app>-<domain>.md"]}
  tool_api: {add, start, status, descriptions:{...}}           # TOOL_REGISTRY + tool_descriptions()
  # ⚠ 2026-08-02 : `descriptions` venait de TOOL_DESCRIPTIONS (dict manuel de mars 2026), que
  # cette ligne a figé comme source. Il est SUPPRIMÉ : `tool_api.tool_descriptions()` les DÉRIVE
  # (APP_CATALOG + docstring + schéma `params.py` + signature). Même source unique que F3 —
  # l'alignement de F3 avait été fait à la création du manifeste (2026-07-21), pas celui de F6.
  # `_tool_api()` importe encore `TOOL_DESCRIPTIONS` : un `__getattr__` de module lui rend la
  # version dérivée. **Passer l'appel à `tool_descriptions()` et retirer la béquille.**

  # F7 PERMISSIONS & SCOPE [accounts/permissions.py AppAccessPolicy + ScopedVisibility]
  access: {roles:[...], public: bool, min_tier: null}
  data_scope: {visibility_default, org_unit_inheritance}

  # F8 STUDIO              [GENERIC_APPS → DEVIENT une projection, plus un 2e registre]
  studio: {runnable, primary_input, input_kwarg, fixed_kwargs, auto_start, extra_params_spec}
          # ports/output_type NE sont PLUS redéclarés : lus depuis `ports` (fin de la redondance)
```

**Régénérable depuis le manifeste** (cible du round-trip) : `models.py` (spine + statuts), `urls/views`
(endpoints standard), modales+inspecteur (`params`+`inspector`), le nœud studio (`ports`+`studio`), le
gating (`access`), le câblage prompts/tool_api.

---

## 4. Facettes AUJOURD'HUI absentes/codées en dur → à formaliser

`version`, `world` explicite, les **drapeaux de capacité** (`has_realtime`/`instant_preview`/
`export_binding`/`supports_profiles` — dans les conventions, pas un registre lisible), le **modèle
d'item/statuts/champs résultat** (répété par app, statuts non uniformes), les **endpoints** (convention,
pas manifeste), le **layout dossiers filemanager** (ajout manuel), la **stratégie batch** (fk vs through),
les **besoins de modèles** de l'app. Le manifeste `app` les rend explicites.

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

1. **Socle** : modèle `Manifest` (enveloppe + `body` JSON + `manifest_kind` + ScopedVisibility) +
   registre `MANIFEST_KINDS` (schéma + ingest_fn + projection par kind) + validation.
2. **Ingest** générique : `validate → sandbox(private) → test → promote`, idempotent/transactionnel/
   réversible + `verify` (diff). Back-link `_manifest_key` sur les entrées dérivées.
3. **Kind `app`** de bout en bout : projection vers les registres du §5 (ingest) + **extraction** inverse
   (générer le manifeste d'une app existante depuis les registres) pour le round-trip.
   - ✅ **Extraction** : `extract_app` (12 facettes) — fait.
   - ✅ **Projection `access`** (write-back) : `write_back_app`/`un_write_back_app` (hooks renommés
     2026-08-05, ex-`project_*`) → `AppAccessPolicy`, dry-run/idempotent/réversible, round-trip non
     destructif validé (2026-07-23). **1re facette réellement écrite.**
   - ⏳ **Projection des 9 autres facettes = CODE-GEN** (models.py/urls/params/nœud studio…) — chantier.
4. **Round-trip** : extraire le manifeste d'une app existante → régénérer en sandbox → diff → itérer.
5. Puis kind `dataset` (modèle tiers généralisé), et convergence `app` (APP_CATALOG ⟷ GENERIC_APPS).

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
| `model` | poids, `hf_id`, **`license`**, **`platform_ref`**, VRAM/disque, format, capacités, provenance | le réglage utilisateur qui le pilote — **et tout ce que la DÉCOUVERTE établit** |
| `app` | identité, ports, params, permissions, cycle de vie, **et les RÉFÉRENCES** vers `model`/`library` | tout ce qui précède — jamais recopié |

#### 7.1 bis — `model` : deux champs ajoutés, et une frontière qui lui est propre (2026-08-05)

`identity.license` et `identity.platform_ref` sont **déclarés au manifeste et projetés dans
`AIModel`** (`write_back_model`, cf. §7.1 ter). Motif mesuré : 0/129 modèles portaient une licence,
alors que l'audit de licences WAMA doit s'aligner sur le composant le moins permissif ; et le lien
vers la plateforme était conditionné à `hf_id`, absent sur les 70 modèles que leur app découvre par
scan disque.

`platform_ref` porte le **fait** (`huggingface:org/repo`, `ollama:gemma4`, `roboflow:projet/3`),
pas l'URL. L'URL en est un rendu, dérivé par `AIModel.platform_url` via une table
plateforme → gabarit à un seul endroit. Stocker 129 chaînes d'URL, ce serait 129 chaînes à
corriger le jour où une plateforme change son schéma d'adresse.

> ⚠ **Frontière propre au kind `model`, à ne pas calquer sur `library`.**
> Une librairie se **déclare** ; un modèle se **découvre** — il existe parce que des poids sont sur
> le disque. Un manifeste n'a donc autorité que sur les champs **déclaratifs** (`license`,
> `platform_ref`). Tout le reste — `is_downloaded`, `is_loaded`, `local_path`, `vram_gb`,
> `capabilities` — appartient à la découverte, qui **réécrit `capabilities` en entier à chaque
> passage** : une valeur posée en dehors d'elle est effacée au sync suivant (constaté le
> 2026-08-05 — 11 capacités renseignées par une commande de rattrapage, puis 0 après un sync).

#### 7.1 ter — hooks par kind, MESURÉ le 2026-08-05

> Les hooks s'appellent `write_back`/`un_write_back` depuis le 2026-08-05 (`kinds.py:35-38` —
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
   ⚠ Limite assumée : l'extraction library lit le venv COURANT (venv_win pour le corpus) ;
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

Différence de nature : `requires` se résout à l'INGEST (le manifeste cible doit exister) ;
`uses` se résout au RUNTIME par le routage capacité→app (l'app fournisseuse est
interchangeable). Validation prévue : vocabulaire canonique fermé, `when` ∈
{pre_input, post_output}, refus d'un `uses` sans fournisseur déclaré au corpus.

**État courant du corpus** (couche factuelle auto-générée, ROADMAP §16.9 ①) :

<!-- WAMA:FAITS(modeles) — généré par « python manage.py doc_facts », ne pas éditer -->
- Manifestes du corpus (`manifests/apps/`) : **10**
- Références de modèles (`body.models.catalog_keys`) : **91/91 résolvables** contre le catalogue `AIModel.model_key`
<!-- /WAMA:FAITS(modeles) -->
