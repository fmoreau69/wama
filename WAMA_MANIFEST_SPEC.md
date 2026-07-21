# WAMA — Formalisme des manifestes (spécification de référence)

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
  capabilities: {has_realtime, has_edit_page, instant_preview, batch,
                 export_binding: late|early, supports_profiles, has_url_import, has_youtube}
  modes: [{id, label, icon, realtime, inputs:[port_id], settings:[param_name]}]   # ex-APP_MODES

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
