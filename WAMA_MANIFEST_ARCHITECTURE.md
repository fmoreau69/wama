# WAMA — Schéma fonctionnel : Manifestes → Ingest → Génération d'app → Mécanismes UI

> **But** : voir clair sur la chaîne complète AVANT d'attaquer l'auto-génération d'application.
> Complète `WAMA_MANIFEST_SPEC.md` (formalisme) avec les FLUX. État au 2026-07-21 : socle des 6 kinds
> **fait et testé** ; la **projection / génération d'app** = le prochain (et gros) chantier, en pointillés.
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

    STORE -.->|PROJECTION (app_gen, à venir)| REG
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
La **projection** (`store → registres`) est le sens inverse, en pointillés : c'est elle qui *génère*
l'app. Tant qu'elle n'existe pas, `project=None` et les registres restent la source — **zéro overlap**.

---

## 2. Les 6 kinds — deux familles, deux tests de fidélité

```mermaid
flowchart LR
    subgraph EX["EXTRAITS — l'objet existe déjà → extract() + ROUND-TRIP"]
        A["app<br/>(APP_CATALOG+8 facettes)"]
        M["model<br/>(AIModel, 147)"]
        P["pipeline<br/>(StudioPipeline.graph)"]
        F["function<br/>(FUNCTION_CATALOG, 18)"]
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

## 6. Points de vigilance connus (à traiter dans/avant l'app_gen)

- **`studio_node_ports` = accesseur unique de ports** partagé preview↔manifeste : un seul point de
  bascule quand la projection inverse le sens (cf. spec F2, contrat de jonction).
- **Redondance APP_CATALOG ⟷ GENERIC_APPS** : le typage E/S est saisi 2× à la main → la fusionner.
- **Apps lab** (`cam_analyzer`, `face_analyzer`) absentes d'APP_CATALOG → à réconcilier.
- **Déclaratif, pas runtime** : exclure du manifeste l'état volatile (modèle chargé, x/y canvas...).
- **Langue** : manifeste en EN canonique → registre i18n central (pas de traduction embarquée).
