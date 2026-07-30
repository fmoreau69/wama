# WAMA — Schéma fonctionnel : Manifestes → Ingest → Génération d'app → Mécanismes UI

> **But** : voir clair sur la chaîne complète AVANT d'attaquer l'auto-génération d'application.
> Complète `WAMA_MANIFEST_SPEC.md` (formalisme) avec les FLUX. État au **2026-07-23** : socle des 6
> kinds **fait et testé** ; **projection = 1 facette (`access` → AppAccessPolicy) réellement écrite**
> (a75c01d, idempotente/réversible, dry-run par défaut), 11 facettes restantes en code-gen.
> Légende des flux : **trait plein = existe & testé** · **pointillés = à construire (app_gen)**.

---

## 1. Vue d'ensemble — le tunnel (deux extrémités qui se rejoignent)

```mermaid
flowchart TD
    subgraph SRC["SOURCES du manifeste"]
        LIB["Librairie / dossier projet<br/>(données brutes, toolbox tierce...)"]
        CODE["Code + DB existants<br/>(APP_CATALOG, AIModel,<br/>StudioPipeline, Project...)"]
    end

    LLM["Manifest skill (LLM local)<br/>wama-dev-ai : infère un brouillon"]
    EXT["extract(kind, key)<br/>LIT les registres"]

    LIB -->|autoré| LLM
    CODE -->|extrait| EXT
    LLM --> MAN
    EXT --> MAN

    MAN["MANIFESTE<br/>enveloppe + body(kind)<br/><i>source autoritaire</i>"]

    MAN --> ING

    subgraph ING["MOTEUR D'INGEST (fait)"]
        direction TB
        V["validate()<br/>enveloppe + body(kind)"]
        SB["store SANDBOX<br/>visibility=private"]
        VF["verify()<br/>diff manifeste ↔ courant"]
        PR["promote()<br/>private → project/unit/public"]
        V --> SB --> VF --> PR
    end

    ING --> STORE["Manifest store<br/>(common.Manifest, DB)"]

    STORE -->|PROJECTION access → AppAccessPolicy ✅ écrite, apply=False par défaut| REG
    STORE -.->|PROJECTION 11 autres facettes (app_gen, à venir)| REG
    subgraph REG["REGISTRES FONCTIONNELS (inchangés)"]
        R1["APP_CATALOG / GENERIC_APPS"]
        R2["params.py · Detail/PreviewRegistry"]
        R3["PROMPT_TARGETS · tool_api"]
        R4["AppAccessPolicy · model_selector"]
    end

    REG --> UI["MÉCANISMES UI + EXÉCUTION"]
    UI --> APP["Application qui tourne"]

    STORE -.->|un_ingest (réversible)| STORE
    MAN -.->|ré-ingest = UPDATE idempotent| ING
```

**Lecture** : aujourd'hui le flux VA `code → extract → manifeste → store` (on éprouve la lecture).
La **projection** (`store → registres`) est le sens inverse : c'est elle qui *génère* l'app.
**MAJ 2026-07-23** : `project` n'est plus `None` pour le kind `app` (`builtin/app.py::project_app`
+ `un_project_app`), mais elle est **dry-run par défaut** (`apply=False`) et ne couvre que
`access` → l'overlap runtime reste borné à `AppAccessPolicy` ; pour tout le reste, les registres
restent la source.

---

## 2. Les 6 kinds — deux familles, deux tests de fidélité

```mermaid
flowchart LR
    subgraph EX["EXTRAITS — l'objet existe déjà → extract() + ROUND-TRIP"]
        A["app<br/>(APP_CATALOG+8 facettes)"]
        M["model<br/>(AIModel, N lignes DB)"]
        P["pipeline<br/>(StudioPipeline.graph)"]
        F["function<br/>(FUNCTION_CATALOG, 19)"]
    end
    subgraph AU["AUTORÉS — le manifeste EST l'origine → validate + store → PROJECTION"]
        D["dataset<br/>(généralisation toolbox tierce)"]
        PJ["project<br/>(Project cross-org)"]
    end

    EX -->|"extract → ingest → verify (diff=0)"| OKX["fidélité prouvée<br/>par round-trip"]
    AU -->|"validate → store → (projection)"| OKA["fidélité prouvée<br/>par instanciation"]
```

> `function` chevauche : `pure`/`app` = extraits du catalogue code ; `user` (UserFunction) = autoré en DB.
> `project` a un modèle DB donc s'EXTRAIT aussi, mais sa raison d'être reste l'autorat (créé par l'humain).

---

## 3. Le kind `app` — chaque facette alimente un mécanisme (la carte de l'app_gen)

> C'est LA carte à tenir pour l'auto-génération : que **génère** chaque facette du manifeste `app`.
> À gauche le manifeste (source unique), à droite le mécanisme WAMA existant qu'il pilotera.

```mermaid
flowchart LR
    subgraph MAN["MANIFESTE app (body)"]
        f1["identity + world"]
        f2["ports (travail/prompt/reference)"]
        f3["params (PARAMS_JSON)"]
        f3b["inspector (Detail/Preview)"]
        f4["models (select_model)"]
        f5["processing (statuses/endpoints)"]
        f5b["processing.ingest + accepts_url"]
        f6["prompts (targets/skills)"]
        f6b["tool_api"]
        f7["access + data_scope"]
        f8["studio"]
        f2c["capabilities (during_preview...)"]
    end

    f1 --> u1["Nav / catalogue / monde"]
    f2 --> u2["Nœud studio + PORTS"]
    f2 --> u2b["Preview d'entrée<br/>(bind travail/prompt, jamais reference)"]
    f2c --> u2c["Preview PENDANT (streaming)"]
    f3 --> u3["Modales item/batch + inspecteur<br/>(WamaParams, 1 source)"]
    f3b --> u3b["Volet droit + preview modale"]
    f4 --> u4["Sélection VRAM-aware<br/>keep_loaded"]
    f5 --> u5["models.py (spine+statuts)<br/>urls/views (endpoints)<br/>tasks Celery"]
    f5b --> u5b["source_ingest.ensure_local_input<br/>(WAMA_INGEST) + card import URL"]
    f6 --> u6["Traduction/enrichissement prompt"]
    f6b --> u6b["API assistant IA"]
    f7 --> u7["Gating tier/rôles + scope données"]
    f8 --> u8["Runner studio (GENERIC_APPS)"]
```

**Round-trip = test de cette carte** : régénérer une app depuis son manifeste doit reproduire
models.py + urls/views + modales + inspecteur + nœud studio + gating + câblage prompts/tool_api.
Les écarts révèlent trous du schéma ET mécanismes non généralisés (aujourd'hui : `modes`=5 apps,
`imager`=détail sans preview, apps lab hors APP_CATALOG).

---

## 4. Cycle de vie d'un manifeste dans l'ingest (machine à états)

```mermaid
stateDiagram-v2
    [*] --> Draft : extract() ou LLM skill
    Draft --> Rejected : validate() KO
    Draft --> Sandbox : validate() OK (store private)
    Sandbox --> Sandbox : ré-ingest (idempotent, UPDATE)
    Sandbox --> Verified : verify() diff analysé
    Verified --> Sandbox : diff → corrige le manifeste
    Verified --> Promoted : promote() (gating org/projet)
    Promoted --> Sandbox : un_ingest / dépublier (réversible)
    Promoted --> [*]
    Rejected --> [*]
```

Propriétés garanties (testées) : **idempotent** (kind+key), **transactionnel** (@atomic),
**réversible** (un_ingest), **traçable** (source + `_manifest_key` sur dérivés à venir).

---

## 5. Où se branche l'auto-génération d'application (prochain chantier)

```mermaid
flowchart TD
    MAN["Manifeste app validé (sandbox)"] --> GEN{"PROJECTION / app_gen"}
    GEN --> G1["Générer models.py<br/>(spine + statuts PENDING/RUNNING/SUCCESS/FAILURE)"]
    GEN --> G2["Générer urls/views<br/>(endpoints standard)"]
    GEN --> G3["Câbler params → WamaParams<br/>(modales + inspecteur)"]
    GEN --> G4["Enregistrer Detail/Preview + tool_api"]
    GEN --> G5["Déclarer nœud studio<br/>(ports lus du manifeste, plus de GENERIC_APPS dupliqué)"]
    GEN --> G6["Appliquer access (AppAccessPolicy)"]

    G1 & G2 & G3 & G4 & G5 & G6 --> SBX["App INSTANCIÉE en sandbox"]
    SBX --> DIFF["diff vs app RÉELLE<br/>(1er test : ré-injecter une app existante)"]
    DIFF --> PROMOTE["promote → app commune"]
```

**Discipline (non négociable)** : la projection est **idempotente / transactionnelle / réversible** ;
les registres deviennent des **projections** re-synchronisables (`verify` réconcilie) ; on **converge**
`APP_CATALOG ⟷ GENERIC_APPS` en un seul kind `app` au lieu d'ajouter un 6e endroit.

---

## 5bis. Résultats du 1er round-trip / dry-run (2026-07-21, `391eacc`)

Étape 1 de la projection = **dry-run sans code-gen** (`wama/common/manifests/projection.py`).
Deux sorties, toutes deux fidèles au code réel :

**A. Projetabilité par facette** — sur les 12 facettes du kind `app`, **une seule est projetable au
RUNTIME** (`access` → `AppAccessPolicy`, DB) ; les **11 autres sont du CODE-GEN** (APP_CATALOG, params.py,
models.py/urls, GENERIC_APPS…). Facettes MANQUANTES fréquentes (trou de schéma OU app non concernée — à
lever au cas par cas) : `modes` (absent hors 5 apps), `prompts` (apps non génératives : normal), `models`
(apps sans catalogue `<APP>_MODELS`).

> **✅ 1re PROJECTION RÉELLE (write-back) IMPLÉMENTÉE 2026-07-23** — `builtin/app.py::project_app` +
> `un_project_app`, exposée `manifests.project(manifest, apply=False)`. La facette `access` s'écrit
> réellement dans `AppAccessPolicy` : **dry-run par défaut**, **idempotent** (get_or_create par app_id),
> **transactionnel**, **réversible** (`un_project` supprime → retombe sur le seed `DEFAULT_APP_ACCESS`).
> Round-trip validé NON DESTRUCTIF (extract→project→`_policy_for` match→un_project→rollback, rien laissé).
> Respecte la sûreté §2.1 : geste EXPLICIT, jamais automatique. **Reste = les 11 facettes code-gen.**

**B. Round-trip redondance `ports (app_registry)` ⟷ `GENERIC_APPS`** — ⚠ **CORRIGÉ 2026-07-22 (Fabien).**
La 1re lecture parlait de « divergences réelles » ; c'était une ERREUR d'analyse (lecture de la SURFACE des
registres sans tracer le CHAÎNAGE d'exécution). Réalité :

- **Le typage de SORTIE n'est PAS un trou.** Il est chaîné : `output_types` (dans **APP_CATALOG**) → domaine →
  `wama/common/utils/output_formats.py` (`output_format_params_for_app`) → réutilise `CONVERTER_OUTPUT_FORMATS`
  (`converter.utils.format_router`) = **source unique déjà maintenue**. Les apps early-binding injectent les Param
  `output_format`/`output_quality` ; le converter fait la conversion. Le `output_type` de GENERIC_APPS est
  juste la sortie déclarée du NŒUD studio (câblage du graphe), un concern DISTINCT. → le manifeste DÉCRIT la
  capacité de conversion (early/late binding), il ne « manque » rien.
- **Les écarts d'ENTRÉE sont majoritairement LÉGITIMES ou de l'incomplétude, PAS de la dérive** :
  | app | lecture 1re (fausse) | réalité |
  |---|---|---|
  | avatarizer | « image en trop » | image = image de **RÉFÉRENCE** pour générer l'avatar → légitime ; GENERIC_APPS sous-décrit |
  | converter | « archive divergent » | converter **pas encore dans le studio** (studio en dev) → incomplétude, pas dérive |
  | enhancer | « audio en trop » | enhancer a **2 domaines** (image/video ET audio) → légitime ; GENERIC_APPS omet audio |
  | imager | « divergent » | ports plus riche (accepte une image en édition) ; studio simplifie en prompt-primary → légitime |
  | describer | — | **seul vrai TODO** : ajouter `document` aux ports describer |

**Conclusion CORRIGÉE** : `GENERIC_APPS` est une **VUE simplifiée (souvent lossy)** d'`app_registry` pour le
runner studio ; `app_registry` (+ briques communes) est la source RICHE. La convergence n'est donc PAS « choisir
un gagnant entre deux sources qui se contredisent » mais : **faire de GENERIC_APPS une PROJECTION calculée depuis
app_registry** (préserver le riche, régénérer le simplifié), en gardant les champs de CÂBLAGE runner que
app_registry n'a pas (`params_module/attr`, `input_kwarg`, `fixed_kwargs`, `auto_start` — pas de la redondance).
Seul vrai correctif de données : `document` aux ports describer. **Leçon : tracer le chaînage d'exécution, pas
la surface des registres.**

---

## 6. Points de vigilance connus (à traiter dans/avant l'app_gen)

- **`studio_node_ports` = accesseur unique de ports** partagé preview↔manifeste : un seul point de
  bascule quand la projection inverse le sens (cf. spec F2, contrat de jonction).
- **Redondance APP_CATALOG ⟷ GENERIC_APPS** : le typage E/S est saisi 2× à la main → la fusionner.
- **Apps lab** (`cam_analyzer`, `face_analyzer`) absentes d'APP_CATALOG → à réconcilier.
- **Déclaratif, pas runtime** : exclure du manifeste l'état volatile (modèle chargé, x/y canvas...).
- **Langue** : manifeste en EN canonique → registre i18n central (pas de traduction embarquée).

---

## 7. État MESURÉ de la projection + kind `library` proposé (vérifié 2026-07-30)

Relevé **dans le code** (`grep` des hooks passés à `register_kind()` dans `common/manifests/builtin/`),
pas dans les intentions :

| kind | `extract` | `project` / `un_project` |
|---|---|---|
| `app` | `extract_app` | ✅ `project_app` / `un_project_app` — **le seul** |
| `function` | `extract_function` | `project=None` |
| `model` | `extract_model` | ❌ |
| `pipeline` | `extract_pipeline` | ❌ |
| `project` | `extract_project` | ❌ |
| `dataset` | `None` — *le manifeste est l'origine* | ❌ |

**Lecture** : le formalisme, l'enveloppe et l'ingest sont en place, mais le sens **génératif**
(manifeste → réalité) n'existe que pour `app`, sur une seule facette (`access` → `AppAccessPolicy`),
en dry-run par défaut. **Un manifeste de modèle ne crée aujourd'hui aucun `AIModel`.** Le manifeste
est donc la source **par architecture**, le registre l'est encore **en pratique** pour 5 kinds sur 6.

**Pourquoi c'est coûteux ici** — comparaison Hermes (cf. `ROADMAP.md` §16.7) : leur registre est
**éphémère**, rebâti par scan à chaque démarrage ⇒ pas de write-back, donc ni idempotence ni
réversibilité à garantir. Nos registres sont **persistés et vivants** (ils servent les pages de
gestion) ⇒ toute projection doit être idempotente **et** réversible. La lenteur de ce chantier est la
contrepartie de la persistance, pas un retard.

**Kind `library` — proposé comme PILOTE du manifeste-first.** Deux régimes déjà supportés par le
formalisme s'y combinent **champ par champ** :
- **constaté** (`extract` via `importlib.metadata.distributions()`, écarts inter-environnements
  remontés par `verify`) : version installée, dérive dev/prod ;
- **déclaré** (le manifeste est l'origine, précédent `dataset`) : `apps_dépendantes`,
  `fonctions_exposées`, `criticité`, `version_min`, `licence`, `dernier_audit`.

Intérêt : **aucun registre hérité à réconcilier** — son registre *naîtrait de* la projection au lieu
de la précéder. Terrain vierge pour prouver la chaîne `library.fonctions_exposées` → manifestes
`function` → ports typés → nœuds studio de bout en bout.

⚠ **Ne PAS importer le régime éphémère d'Hermes** (registre recalculé à la lecture) : il viole la
propriété de sûreté **§2.1 du SPEC** (*rien ne lit le manifeste en direct ; ingest = seul pont gaté ;
état committé = les registres*). Hermes peut se le permettre — un plugin absent n'y coûte qu'une
capacité optionnelle ; ici un registre volatil casserait les pages de gestion. `library` obtient donc
un **vrai registre persisté écrit par l'ingest**, comme les autres kinds.

⚠ L'auto-installation associée n'est **pas** une projection anodine : `pip install` n'est ni
idempotent ni réversible, il **écrase les patches venv** (`patches/apply_patches.py`) et peut casser
les pins de la pile GPU. Contrat exigé : `project()` produit un **plan**, exécution sous validation
humaine, **ré-exécution d'`apply_patches.py` en post-étape obligatoire**, et allowlist façon Hermes
(PyPI par nom, pin PEP 440, pas de `git+`/`file:`/`--index-url`).
