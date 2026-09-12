<!-- WAMA:GENERE(dev-registres) — généré par « python manage.py doc_facts » depuis le plan de wama/common/docs_catalog.py ; ne pas éditer -->
# Les registres de WAMA

> Doc développeur **générée** : chaque section vient de la doc de construction (source citée en pied) ou des registres eux-mêmes. Pour la corriger, corriger la SOURCE — ce fichier est réécrit par `python manage.py doc_facts`.

## Quand une chose mérite un registre

> **Registre** quand l'ajout apporte du **COMPORTEMENT** et que la liste doit pouvoir s'allonger
> **sans toucher le moteur**.
> **Table de vocabulaire** quand l'ajout n'apporte que des **MOTS** (libellé, icône, catégorie) et
> que la liste est **fermée par la nature du domaine**.

| question | oui → | non → |
|---|---|---|
| ① **L'ajout apporte-t-il du comportement ?** Un lecteur *sait lire*, un écrivain *sait écrire*. Un libellé + une icône ne savent rien faire | registre | vocabulaire |
| ② **Un TIERS doit-il pouvoir l'ajouter sans modifier le moteur ?** (une app, un autre monde, un plugin) | registre | vocabulaire |
| ③ **La liste est-elle fermée par la NATURE du domaine ?** `image/video/audio/document/archive/text/3d` n'est pas extensible « par ajout de capacité » — c'est une taxonomie | vocabulaire, **domicile unique** | registre |

Et une quatrième, qui décide non pas *registre ou pas* mais *registre des registres ou pas* :

| ④ **L'utilisateur doit-il en voir l'état et pouvoir le RAFRAÎCHIR ?** | alors il entre au **registre des registres** — et hérite du bouton, de l'endpoint, de la permission, du chronométrage et du compte-rendu, sans une ligne d'UI |

⚠ **`MEDIA_CATEGORIES` répond NON à ③ et reste donc une taxonomie** — et son domicile unique est
déjà déclaré et **gardé mécaniquement** (`check_redundancy.py` : « `app_registry.py` : LE domicile
des vocabulaires média »). Le monde Médias n'a rien à changer. C'est le contre-exemple utile :
la réponse n'est pas « tout en registre ».

*Source : [WAMA_DATA_WORLD.md — 9quinquies.2 LE CRITÈRE — trois questions, dans cet ordre](../../WAMA_DATA_WORLD.md#9quinquies2-le-critère--trois-questions-dans-cet-ordre)*

## Les natures d'actualisation

| nature | ce qu'elle déclare | où tourne l'actualisation |
|---|---|---|
| `scan` | Scan d'une source externe vers un registre persistant | Tâche Celery (non bloquante) |
| `mesure` | Calcul qui produit un rapport écrit | Tâche Celery (non bloquante) |
| `redeclaration` | Registre en mémoire, peuplé par import | Dans le processus web |
| `derive` | Dérivé à chaque affichage — toujours à jour | rien à actualiser |

## Les registres, un par un

**15 registres**, par ordre alphabétique de libellé.

### Applications

- **Clé** : `apps` — Calcul qui produit un rapport écrit
- **Source** : `APP_CATALOG` (déclaré en code) + grille de conformité MESURÉE depuis le code réel
- **Page dans WAMA** : `/common/apps/`
- **Doc** : [WAMA_APP_CONVENTIONS.md](../../WAMA_APP_CONVENTIONS.md)
- **Kind de manifeste** : `app`
- **Citable dans une doc** : `WAMA:FAIT(apps/<clé>/<champ>)`

Le catalogue lui-même est déclaré en code — rien à y actualiser. Ce qui s'actualise est la GRILLE : ses critères re-mesurés par analyse du code.

### Backends

- **Clé** : `backends` — Dérivé à chaque affichage — toujours à jour
- **Source** : Déclarations des paquets `wama/<app>/backends/` (ROUTES/RESULT/NATURE_FIELD + classes BaseModelBackend : ENGINE, ISOLATION, REQUIRED_PACKAGES, VRAM) recoupées au catalogue `AIModel` (source, backend_ref, composition.runtime.engine)
- **Page dans WAMA** : `/common/backends/`
- **Doc** : [WAMA_APP_GENERATION_ROUTE.md](../../WAMA_APP_GENERATION_ROUTE.md)

Le VIVIER des BACKENDS — la méthode qui appelle un moteur, jamais le moteur lui-même : le MODÈLE porte son moteur, le backend s'en DÉRIVE, et un moteur est une LIBRAIRIE. On y lit ce que chaque app sait exécuter, la nature d'entrée qui y mène, la SAVEUR de sortie (fichier/texte), les paquets requis, la VRAM et les modèles servis. Dit aussi l'ENVIRONNEMENT d'exécution : le défaut est un venv unique, et un backend qui tourne ailleurs le déclare (`ISOLATION`) — sans quoi le verdict de disponibilité confondrait « paquet absent » et « backend qui vit ailleurs ». Deux usages : la vision d'ensemble, et le voisinage dont le LLM de la marche B a besoin pour s'inspirer du backend le plus approchant. Dérivé à chaque affichage — un backend ajouté y apparaît sans qu'on déclare rien ici.

### Documentation

- **Clé** : `docs` — Dérivé à chaque affichage — toujours à jour
- **Source** : Déclaration `common/docs_catalog.py` (docs de référence d'AGENTS.md), lus sur le disque à chaque affichage
- **Page dans WAMA** : `/common/docs/`
- **Doc** : [AGENTS.md](../../AGENTS.md)
- **Citable dans une doc** : `WAMA:FAIT(docs/<clé>/<champ>)`

La doc de WAMA en lecture seule. Chaque doc déclare son AUDIENCE : la doc de CONSTRUCTION (doctrine, décisions, vision, chantiers) est faite de fichiers ; la doc DÉVELOPPEUR est GÉNÉRÉE à la lecture depuis les registres (`dev_docs.py`), jamais rédigée en parallèle. `check_docs` dérive sa liste de la même déclaration : un doc ajouté ici est contrôlé sans rien toucher d'autre.

### Fonctions de traitement

- **Clé** : `fonctions` — Registre en mémoire, peuplé par import
- **Source** : `apps.py:ready()` de chaque monde — `wama_data`, `wama_lab.cam_analyzer`…
- **Page dans WAMA** : `/model-manager/functions/`
- **Doc** : [WAMA_DATA_FUNCTION_CARDS.md](../../WAMA_DATA_FUNCTION_CARDS.md)
- **Kind de manifeste** : `function`
- **Citable dans une doc** : `WAMA:FAIT(fonctions/<clé>/<champ>)`

Recharge les modules qui déclarent des `FunctionSpec`. Rend visibles les fonctions ajoutées pendant que le serveur tourne, sans redémarrage.

### Formats d'entrée (WAMA Data)

- **Clé** : `lecteurs_data` — Registre en mémoire, peuplé par import
- **Source** : `wama_data/sources/` — un lecteur par format, inscrit à l'import
- **Doc** : [WAMA_DATA_WORLD.md §6.6, §9quinquies](../../WAMA_DATA_WORLD.md)
- **Kind de manifeste** : `dataset`

Recharge les lecteurs de sources. Ajouter un format d'import ou de connexion = déposer un lecteur, jamais éditer le moteur — l'Importer et le Connector partagent ce registre.

### Formats de sortie (WAMA Data)

- **Clé** : `formats_export_data` — Registre en mémoire, peuplé par import
- **Source** : `wama_data/core/export.py` — `register_format()`, plus les écrivains fournis par les adaptateurs
- **Doc** : [WAMA_DATA_WORLD.md §9ter.6 C, §9quinquies](../../WAMA_DATA_WORLD.md)

Formats que l'Exporter sait NOMMER, et parmi eux ceux qu'il sait ÉCRIRE — l'écart entre les deux est la dette, et elle est mesurée.

### Librairies externes

- **Clé** : `librairies` — Dérivé à chaque affichage — toujours à jour
- **Source** : Registre `Library` (projeté par les manifestes) + mesure live `importlib.metadata`
- **Page dans WAMA** : `/model-manager/libraries/`
- **Doc** : [LICENSING.md](../../LICENSING.md)
- **Kind de manifeste** : `library`

La page mesure l'installation réelle à CHAQUE affichage et compare au déclaré : l'écart affiché ne peut pas être périmé. Le registre lui-même s'alimente par la projection des manifestes, pas par un scan.

### Licences

- **Clé** : `licences` — Dérivé à chaque affichage — toujours à jour
- **Source** : Agrégation de `AIModel`, `Library`, médias et des `requires` des manifestes d'app
- **Page dans WAMA** : `/common/licenses/`
- **Doc** : [LICENSING.md](../../LICENSING.md)

Vue transversale sans registre propre — « une page qui DÉRIVE ne peut pas diverger de ses sources ». Un bouton d'actualisation y serait un mensonge : actualiser les licences, c'est actualiser modèles et librairies.

### Mes souvenirs

- **Clé** : `memories` — Dérivé à chaque affichage — toujours à jour
- **Source** : `MemoryItem` (`common/memory/`, Postgres + pgvector) — le jumeau du fragment RAG
- **Page dans WAMA** : `/common/memories/`
- **Doc** : [WAMA_MEMORY.md](../../WAMA_MEMORY.md)

Ce que WAMA retient : faits, événements, procédures. Lu en base à chaque affichage — rien à actualiser. La liste ACTIVE est exactement ce que `recall()` peut rendre (même requête, jamais une seconde vérité) ; la FILE DE REVUE des souvenirs non approuvés est réservée au staff.

### Modèles IA

- **Clé** : `modeles` — Scan d'une source externe vers un registre persistant
- **Source** : Fichiers de `AI-models/` + déclarations `model_config` des apps
- **Page dans WAMA** : `/model-manager/`
- **Kind de manifeste** : `model`

Réconcilie le catalogue avec ce qui est réellement présent sur le disque. Une entrée dont les fichiers ont disparu est supprimée — d'où la réserve staff.

### Mon RAG

- **Clé** : `rag` — Dérivé à chaque affichage — toujours à jour
- **Source** : Ce que l'utilisateur a confié au RAG (`common/memory/`, Postgres + pgvector)
- **Page dans WAMA** : `/common/rag/`
- **Doc** : [WAMA_MEMORY.md](../../WAMA_MEMORY.md)

Liste ce que CE compte a ajouté, lu en base à chaque affichage. L'entrée au RAG est un geste explicite : rien ne s'y ajoute par balayage, donc rien à réconcilier.

### Prompts déclarés

- **Clé** : `prompts` — Dérivé à chaque affichage — toujours à jour
- **Source** : `PROMPT_TARGETS` (`common/utils/app_metadata.py`) — un champ-prompt déclaré par app, avec son KIND, son modèle cible et son domaine
- **Page dans WAMA** : `/common/skills/`
- **Doc** : [WAMA_LLM.md](../../WAMA_LLM.md)

La DÉCLARATION que la pipeline de prompts consomme : quel champ est un prompt, de quel KIND, vers quel modèle. Figé dans le code, donc toujours à jour. Partage sa page avec les skills : c'est le même écran qui montre la déclaration, la consigne, et le lien calculé entre les deux.

### Schémas de conteneur (WAMA Data)

- **Clé** : `conteneurs_data` — Registre en mémoire, peuplé par import
- **Source** : `wama_data/containers/` — un schéma par format de sortie, inscrit à l'import
- **Doc** : [WAMA_DATA_WORLD.md §9quater.2 (D3), §9quinquies](../../WAMA_DATA_WORLD.md)

Conteneurs que WAMA Data sait ÉCRIRE : `.wdat` natif et `.trip` pour la compatibilité BIND. Un moteur, N schémas — ajouter un format = déposer un module, jamais éditer le moteur (G1).

### Skills de prompt

- **Clé** : `skills` — Registre en mémoire, peuplé par import
- **Source** : Fichiers `wama/common/prompt_skills/*.md`
- **Page dans WAMA** : `/common/skills/`
- **Doc** : [WAMA_LLM.md](../../WAMA_LLM.md)

Vide le cache de lecture des skills : un `.md` modifié à chaud est repris sans redémarrage. Sans effet de bord partagé, donc ouvert à tout compte connecté.

### Sources externes

- **Clé** : `sources_externes` — Calcul qui produit un rapport écrit
- **Source** : Registre déclaratif `common/external_sources.py` + sonde réseau (clé, joignabilité)
- **Page dans WAMA** : `/common/sources/`
- **Doc** : [WAMA_MECANISMES.md](../../WAMA_MECANISMES.md)
- **Citable dans une doc** : `WAMA:FAIT(sources_externes/<clé>/<champ>)`

Sonde chaque source déclarée : clé d'API posée ? adresse joignable (proxy UGE compris) ? La déclaration, elle, ne s'actualise pas — elle vit en code. Réservé au staff : la sonde émet des requêtes sortantes et écrit un rapport.

## Kinds de manifeste

| kind | description | écrit dans les registres |
|---|---|---|
| `app` | Application généraliste WAMA (8 facettes). Extract complet ; PROJECTION partielle (PROJECTED_FACETS) : `access`→AppAccessPolicy (DB) + `identity`→APP_CATALOG (code, blocs marqués réversibles), le reste = code-gen. | oui (`write_back`) |
| `dataset` | Jeu de données brut typé (généralisation d'un modèle tiers) : source-agnostique + signals typés sur data_types + reference_tables (enums) + records + AXES (plan d'expérience : observation/factor/attribute, contains/crosses, manipulated — WAMA_DATA_WORLD §13). `signals` et `axes` sont l'un OU l'autre obligatoires, pas les deux : un corpus de questionnaires n'a aucun flux temporel. Validate+store : un dataset est un ACCÈS (source.ref = arborescence serveur), pas un objet à instancier — aucun registre où écrire. Chantier ultérieur = un reader source-agnostique. | non — stocké et diffable |
| `function` | Fonction-carte WAMA Data (extrait de FUNCTION_CATALOG ou UserFunction) : E/S typées sur data_types + params + binding (pure\|app\|user). PROJECTION binding=user → UserFunction (tag _manifest-gen, réversible) ; pure/app = catalogue code (code-gen). | oui (`write_back`) |
| `library` | Brique logicielle externe (dépôt/licence/version/install/entry points). Extraite des métadonnées du paquet installé ; les contraintes fines relèvent du rôle wama-dev-ai (SPEC §7.4-4). PROJECTION → registre `Library` (hors allowlist `is_allowed` et hors état runtime, volontairement). | oui (`write_back`) |
| `model` | Modèle IA (extrait d'AIModel) : identité/besoins/formats/capacités déclaratifs. Exclut l'état runtime (loaded/available/downloaded/local_path/timestamps). | oui (`write_back`) |
| `pipeline` | Pipeline (extrait de StudioPipeline.graph OU d'un registre de code inscrit par register_pipeline_source) : nodes (source\|sink\|app\|function — D13) + links typés (to_port = id de port), séparé de la présentation (layout x/y). | non — stocké et diffable |
| `project` | Projet cross-org (extrait de Project) : owner_org + lead + membres explicites (rôle + org d'origine, potentiellement partenaire d'un autre établissement). | non — stocké et diffable |
