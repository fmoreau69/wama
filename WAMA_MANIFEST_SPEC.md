# WAMA — Formalisme des manifestes (spécification de référence)

> **Schéma fonctionnel des flux (manifestes → ingest → app_gen → UI) : [`WAMA_MANIFEST_ARCHITECTURE.md`](WAMA_MANIFEST_ARCHITECTURE.md).**
>
> **Statut : DESIGN / fondation (2026-07-21).** Le manifeste n'existe pas encore : c'est l'**entrée
> générale** qu'on construit pour exploiter tout le chemin déjà bâti par briques (le « tunnel » se
> rejoint ici). Cette spec fixe le formalisme COMMUN à tous les types de manifestes + le schéma du
> premier kind (`app`), issu d'un audit exhaustif du code réel (8 facettes). Sources : les briques
> existantes (voir §Provenance). **Rien d'implémenté — à valider avant de coder.**

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
created_at, updated_at
body: { ... }                 # spécifique au kind (voir §3 pour app)
```

Kinds prévus : **`app`** (§3), **`function`** (= `FunctionSpec`, déjà fait, `WAMA_DATA_FUNCTION_CARDS.md`),
**`dataset`** (style toolbox tierce : channels/signals/reference_tables), **`model`** (= `AIModel`), **`pipeline`**
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
  world: recherche                      # Médias | Data | Lab (auj. déduit d'APP_GROUP) — À AJOUTER
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

  # F4 MODÈLES IA          [model_config.py + model_selector.select_model]
  models: {consumes: {source, model_types:[...]},
           selection: {requires:[cap], classes, vram_budget, prefer_loaded, priority},
           paths_key}

  # F5 TRAITEMENT          [models.py + tasks.py + urls.py — pattern répété, À DÉCLARER]
  processing:
    item_model, statuses:[PENDING,RUNNING,SUCCESS,FAILURE],
    result_fields:[output_file|result_text, used_backend, used_model],
    batch: {strategy: fk|through, nature_of},
    task, endpoints:[start,status,download,duplicate,delete,start_all,clear_all,
                     download_all,batch.*,stage.*,console]     # standard, générés

  # F6 PROMPTS / IA        [PROMPT_TARGETS + prompt_skills + tool_api]
  prompts: {targets:[{field,kind,model_field,source,default_model_type,enrich,domain_field,reference_field}],
            skills:["<app>-<domain>.md"]}
  tool_api: {add, start, status, descriptions:{...}}           # TOOL_REGISTRY/DESCRIPTIONS

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

## 5. Provenance (où chaque facette vit aujourd'hui — l'ingest projette VERS ces lieux)

| Facette | Registre/fichier actuel |
|---|---|
| Identité, ports, batch, conventions | `common/app_registry.py` (`APP_CATALOG`, `MEDIA_CATEGORIES`, `studio_node_ports`) |
| Modes/domaines | `common/utils/app_modes.py` (`APP_MODES`, `INPUT_TYPES`) |
| Params/UI | `wama/<app>/params.py` (`PARAMS_JSON`) + `common/utils/param_schema.py` |
| Volet droit / preview | `common/utils/detail_registry.py`, `preview_registry.py` |
| Modèles | `model_manager/models.py` (`AIModel`), `services/model_selector.py`, `common/utils/model_capabilities.py`, `<app>/utils/model_config.py` |
| Prompts | `common/utils/app_metadata.py` (`PROMPT_TARGETS`), `common/prompt_skills/` |
| API assistant | `wama/tool_api.py` (`TOOL_REGISTRY`/`TOOL_DESCRIPTIONS`) |
| Studio | `studio/services/generic_runner.py` (`GENERIC_APPS`), `studio/models.py` |
| Permissions | `accounts/permissions.py` (`DEFAULT_APP_ACCESS`), `accounts/models.py` (`AppAccessPolicy`) |
| Scope données | `common/models.py` (`ScopedVisibility`, `Project`, `OrgUnit`) |

---

## 6. Plan de construction (proposé)

1. **Socle** : modèle `Manifest` (enveloppe + `body` JSON + `manifest_kind` + ScopedVisibility) +
   registre `MANIFEST_KINDS` (schéma + ingest_fn + projection par kind) + validation.
2. **Ingest** générique : `validate → sandbox(private) → test → promote`, idempotent/transactionnel/
   réversible + `verify` (diff). Back-link `_manifest_key` sur les entrées dérivées.
3. **Kind `app`** de bout en bout : projection vers les registres du §5 (ingest) + **extraction** inverse
   (générer le manifeste d'une app existante depuis les registres) pour le round-trip.
4. **Round-trip** : extraire le manifeste d'une app existante → régénérer en sandbox → diff → itérer.
5. Puis kind `dataset` (toolbox tierce généralisé), et convergence `app` (APP_CATALOG ⟷ GENERIC_APPS).
