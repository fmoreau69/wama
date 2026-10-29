# WAMA_HARNESS.md — les harnais d'agents : état de l'art et écarts de WAMA

> **Domaine de ce fichier** : ce que font les autres harnais d'agents, et **ce qui manque à WAMA**
> en regard. C'est un document de **veille** et de **cartographie d'écarts** — pas un chantier, pas
> une liste de courses, et surtout pas un plan d'intégration.
>
> Créé le **2026-09-19** (demande de Fabien : *« une cartographie complète des différents produits
> et de leurs apports potentiels à WAMA, y compris Cursor […] je ne parle pas de les intégrer, je
> parle de compléter les capacités de WAMA »*). Motif mesuré de sa création au §1.

## 0. Ce que ce document n'est PAS — table de renvoi

La règle « un domaine = un fichier » (`AGENTS.md`) s'applique d'abord à ce document, qui touche à
beaucoup de sujets déjà domiciliés. **Il cite, il ne recopie pas.**

| si la question est… | elle vit dans | ce fichier n'en dit que… |
|---|---|---|
| comment marche NOTRE couche LLM (prompts, skills, RAG, mémoire, routage, surfaces) | `docs/construction/ia/WAMA_LLM.md` | ce que l'état de l'art fait **autrement**, avec la ligne WAMA citée |
| comment on trouve et installe un MODÈLE | `wama/model_manager/PROSPECTION_PIPELINE.md` | rien — un harnais n'est pas un modèle |
| comment on mesure la QUALITÉ d'un modèle ou d'un résultat | `docs/construction/ia/WAMA_QUALITE.md` | un seul fait, au §1 : le harnais pèse plus qu'un changement de modèle, et nos bancs ne le mesurent pas |
| quels COMPOSANTS tiers on adopte ou rejette (Presidio, Docling, pgvector, Langfuse, LocalAI…) | `ROADMAP §16.2` | rien — un composant n'est pas un harnais |
| la grappe IA de DEV et l'orchestrateur cloud/local | `ROADMAP §16` | ses décisions sont **citées** au §6, jamais recopiées |
| mémoire, RAG, journal | `docs/construction/ia/WAMA_MEMORY.md` | l'axe « mémoire procédurale », où WAMA est en avance |
| permissions, profils, partage | `PROFILES_PERMISSIONS.md`, `WAMA_COLLABORATION.md` | la distinction **autorisation ≠ approbation** (§5, écart 1) |
| serveur MCP de WAMA (chantier) | `ROADMAP §8d Phase 3` | l'écart de surface (outils seuls) mesuré au §4 |

---

## 1. Pourquoi ce document existe, et pourquoi maintenant

**Trois constats mesurés le 2026-09-19, avant d'écrire une ligne :**

1. **La matière était éclatée sur quatre domiciles, dont un hors du dépôt.** `ROADMAP §16`
   (décisions d'architecture), `§16.2` (liste d'outils tiers), `§16.7` (Hermes, 195 lignes) — et
   la décision **DeepSeek Harness / Cordis du 2026-08-20 ne vivait QUE dans la mémoire d'agent** :
   `grep -rni "cordis|deepseek harness"` sur le dépôt rend **2 mentions de passage** dans
   `WAMA_DATA_WORLD.md` (l. 231, 1746), aucune évaluation. Une décision hors du dépôt n'est pas
   une décision : la session suivante la reprend de zéro.
2. **Toute la famille des agents de code était absente.** `grep -rni` sur `docs/` et `AGENTS.md` :
   **0 occurrence** pour Codex CLI *en tant que harnais*, Cursor, Cline, Aider, OpenHands, Goose,
   deepagents. (⚠ Le premier relevé semblait en trouver : c'étaient `décliner`, `deviner`,
   `déclare` qui matchaient `cline`/`devin` — *un relevé par motif ne conclut pas*, il a fallu
   ouvrir les lignes.)
3. **La veille promise n'a jamais eu lieu.** La décision Cordis énonçait : *« étendre
   `PROSPECTION_PIPELINE` aux frameworks, en passe trimestrielle et non réactive — ce qui ferait
   perdre n'est pas de rater un lancement, c'est d'arrêter de livrer pour l'évaluer »*. Mesure :
   `grep -i "framework|trimestr"` sur `PROSPECTION_PIPELINE.md` → **0 hit**. Treize mois après, la
   veille est arrivée exactement comme la règle l'interdisait : **en réaction**, parce qu'on nous a
   mis deux analyses externes sous les yeux. Le §8 rend la passe exécutable.

**Et un fait externe qui justifie l'effort** — sur SWE-bench Pro, **changer de harnais à modèle
constant déplace le `pass@1` plus qu'un changement de modèle** : 23 % → 52 % sur un même modèle,
15 % → 36 % sur un autre, selon le harnais. *Conséquence directe pour nous : `WAMA_QUALITE.md`
mesure des MODÈLES (bancs, juges, débit) et ne mesure **jamais** le harnais — or c'est peut-être la
variable dominante. Ce n'est pas une critique de nos bancs, c'est un axe qui leur manque.*

⚠ **Statut épistémique de ce document.** Tout ce qui concerne **WAMA** est mesuré, ligne citée,
daté du 2026-09-19. Tout ce qui concerne les **produits externes** vient de leur documentation
publique et de relevés web du même jour : c'est de la **documentation d'éditeur**, pas une lecture
de leur code. Un fait externe utilisé pour décider chez nous devra être revérifié à ce
moment-là — le §3 marque ⚠ ceux qui portent une décision.

---

## 2. Le cadre d'analyse — trois couches, quatorze axes

Plutôt qu'une liste de produits (qui vieillit en trois mois), on classe par **capacité**. Le cadre
retenu est celui d'une taxonomie académique de **13 harnais open source lus dans leur code source**
(arXiv 2604.03515, « Inside the Scaffold: A Source-Code Taxonomy of Coding Agent Architectures ») —
trois couches : **Contrôle**, **Interface outils/environnement**, **Gestion des ressources**.

Ses quatre résultats qui nous concernent :

- **11 harnais sur 13 COMPOSENT plusieurs primitives de contrôle** au lieu d'en suivre une seule.
  Les cinq primitives recensées : boucle ReAct, générer-tester-réparer, planifier-exécuter, reprise
  sur échec (*retry*), recherche arborescente.
- **Le nombre d'outils va de 0 à 37.** (WAMA en a **71**, mesuré aujourd'hui — voir §4, axe 7 : ce
  n'est pas un retard, c'est une autre nature, mais ça a un coût.)
- **Sept stratégies distinctes de gestion du contexte** coexistent — c'est le point de **divergence
  maximale** entre harnais.
- **Les harnais CONVERGENT** sur les capacités d'outils et l'**isolation d'exécution**, et
  **DIVERGENT** sur la compaction de contexte et la gestion d'état.

On y ajoute le vocabulaire aujourd'hui standard de l'ingénierie de contexte — **écrire / choisir /
compresser / isoler** (*write, select, compress, isolate*), décliné en cinq mécanismes :
déchargement (*offloading*), isolation, récupération, compaction, cache.

**Les quatorze axes retenus pour WAMA** (détail mesuré au §4) :

| couche | axes |
|---|---|
| **Contrôle** | 1 boucle · 2 approbation humaine · 3 planification · 4 sous-agents |
| **Outils / environnement** | 5 surface d'outils · 6 registre de fournisseurs · 7 isolation d'exécution · 8 standards (MCP, AGENTS.md) · 9 index du domaine |
| **Ressources** | 10 contexte · 11 persistance de session · 12 observabilité · 13 économie (cache) · 14 mémoire procédurale |

---

## 3. La carte des produits

> ⚠ Licences et faits relevés le 2026-09-19 depuis la documentation publique. **Aucun de ces dépôts
> n'a été lu dans son code** — sauf, depuis le 2026-10-28, **Codex et OpenCode** (§7.4). Les lignes ⚠ portent un fait sur lequel une décision WAMA pourrait
> s'appuyer : à revérifier avant de décider.

### 3.1 Harnais OUVERTS

| produit | licence / langue | nature | apport ORIGINAL (ce qu'il fait que les autres ne font pas) | pour WAMA |
|---|---|---|---|---|
| **Codex CLI** (OpenAI) | Apache-2.0, Rust | agent de code CLI + IDE + desktop, un cœur, N surfaces | **politique d'approbation ET bac à sable déclarés en configuration**, séparés du code des outils ; providers déclaratifs (`model_providers`) ; config en **3 couches** (drapeaux CLI > profil > config de projet, cette dernière chargée **seulement si le projet est approuvé**) | le motif « 1 cerveau / N surfaces » est **déjà le nôtre** ; l'apport net = **§5 écart 1** (approbation) et le **verrou de confiance par projet**. ⚠ Lu dans son code le 2026-10-28 (§7.4) : la valeur `untrusted` d'`approval_policy` est **retirée** (remplacée par `projects.<path>.trust_level`) ; décision d'approbation en trois états hors de l'outil, publiée en annotation MCP ; sous-agents = de simples outils (`spawn_agent`/`wait`) |
| **deepagents** (LangChain) | MIT, Python + JS | « harnais tout compris » sur LangGraph | **déchargement du contexte vers un système de fichiers virtuel** : gros résultats d'outils écrits sur disque, et au-delà d'un seuil les anciens arguments d'écriture sont déchargés à leur tour ; **sous-agents à fenêtre isolée** ; interruptions humaines | **écart 2 et écart 3**. ⚠ Le runtime est LangGraph — `ROADMAP §16` a déjà tranché : *« n'introduire LangGraph/CrewAI que si réel besoin »*. On prend le **motif**, pas la pile |
| **Hermes Agent** (Nous Research) | MIT, Python | agent personnel persistant | **skills générés depuis l'expérience** ; **`pre_tool_call` → `block` / `approve`** (veto ou escalade humaine) câblé dans le runtime ; 4 verrous d'auto-installation de dépendances ; ~6 passerelles de messagerie | **déjà évalué en profondeur — §7.1.** L'idée des skills est **livrée** (`/skill-forge`) ; le `pre_tool_call` reste le meilleur modèle connu pour **écart 1** |
| **DeepSeek Harness / Cordis** | ouvert (noyau Koishi, ~4 ans) | noyau de plugins à effets réversibles | **modification à chaud d'un process vivant** : plugins montés/démontés en session, effets enregistrés donc annulables | **§7.2 — rien à intégrer**, et c'est une décision, pas un renoncement : WAMA a *choisi* de ne pas avoir ce problème |
| **Aider** | ouverte, Python | agent de code en terminal, l'humain regarde chaque diff | **carte de dépôt** (*repo map*) construite mécaniquement, pas par plongement vectoriel ; formats d'édition explicites (entier / diff) ; **un commit git par changement** | l'idée « **l'index est DÉCLARÉ, pas deviné** » est déjà la nôtre (§4, axe 9). Le *commit par changement* = un modèle pour **écart 7** (annulation) |
| **Cline** | Apache-2.0, TypeScript | extension d'éditeur | **modes Plan / Act séparés** (stratégie ≠ exécution) ; flux d'approbation à chaque action ; l'agent **écrit ses propres règles persistantes** (`new_rule` → fichier versionné, rechargé dans les prompts suivants) | **écart 1** (approbation) et **axe 3** (planification). L'écriture de règles par l'agent = la moitié runtime de ce que `/skill-forge` fait côté dev |
| **OpenHands** | ouverte, Python | agent autonome qu'on lance et qu'on surveille | **architecture à flux d'événements** : à chaque tour l'agent raisonne → émet une **action** → l'environnement exécute → renvoie une **observation**. ⚠ Il **écarte délibérément** MCP, sous-agents, mode plan et fenêtres d'approbation, qui arrivent par extensions | le **flux d'événements action/observation** est un modèle direct pour **écart 6** (traces) : la trace n'est pas un journal, c'est le format d'exécution lui-même |
| **Goose** (Block) | Apache-2.0, Rust | agent d'automatisation général (pas que du code) | **70+ extensions via MCP** ; « recettes » (*recipes*) rejouables ; sous-agents ; mode bac à sable ; contrôles de permission | le seul de la liste dont le **domaine dépasse le code** — donc le plus proche de la nature de WAMA. Les *recettes* ≈ nos **pipelines Studio** |
| **OpenCode** | MIT, TypeScript — dépôt `anomalyco/opencode` (ex-`sst`), v2.2.0 | ⚠ **corrigé le 2026-10-28, lu dans son code (§7.4)** : un **serveur HTTP** dont le terminal, le web, le bureau et ACP sont des clients — « un cerveau, N surfaces », comme nous | **agents déclarés en données** (Plan et Build sont deux agents, pas deux modes ; Plan n'interdit QUE l'écriture de fichiers, le shell reste libre — ce n'est pas une lecture seule) ; **sous-agents en sessions enfants** (profondeur 1, retour du seul texte final, mode de fond annoncé à la fin) ; règles `allow/ask/deny` avec refus **motivé** renvoyé au modèle ; borne à la source avec pointeur vers l'intégral ; compaction à gabarit | **écart 1, écart 2, écart 3** — le plus proche de nos besoins pour les sous-agents (§7.4) |
| **Qwen Code** | ouverte, TypeScript | CLI | **multi-protocole** natif (OpenAI, Anthropic, Gemini, Qwen) | confirme notre champ `protocol` d'`external_sources` (§4, axe 6) |
| **Kilo Code** | ouverte, TypeScript | extension d'éditeur (fork de Roo) | ⚠ documente explicitement **l'absence de cache de prompt** comme un défaut coûteux | rappel pour **écart 9** |
| **Pi** | ouverte, TypeScript | CLI minimaliste | **4 outils seulement** (lire, écrire, éditer, bash), **pas de MCP** | la borne basse de l'axe 5 : 4 outils contre nos 71. À garder en tête quand on ajoutera le 72ᵉ |

### 3.2 Harnais FERMÉS (on ne peut lire que le comportement et la doc)

| produit | apport ORIGINAL | pour WAMA |
|---|---|---|
| **Cursor** | **points de reprise** (*checkpoints*) : chaque application de modifications en crée un, on revient à cet état d'un clic depuis l'historique · **règles par portée** dans `.cursor/rules/`, chargées **seulement si elles matchent le contexte courant** · **mémoire latérale** : un modèle observateur regarde les sessions et fait remonter le contexte utile plus tard · **index vectoriel** du dépôt (découpage sémantique → plongements) | les **points de reprise** = le meilleur modèle connu pour **écart 7** · les **règles par portée** valident notre `prompt_skills` résolu par le CODE (WAMA_LLM §0bis) · ⚠ l'**index vectoriel** est justement ce qu'on n'a pas besoin de copier : nos registres déclarent au lieu de deviner (§4, axe 9) |
| **Claude Code** | **compaction automatique** au-delà de ~95 % de la fenêtre (résumé de toute la trajectoire) · **sous-agents** à contexte isolé · **mode plan** · **crochets** (*hooks*) déclenchés par événement · **skills** choisis par description · reprise (`/rewind`) | **écart 2** (compaction), **écart 3** (sous-agents), **écart 7**. ⚠ C'est le harnais qu'on utilise pour DÉVELOPPER WAMA : on connaît ses gestes de l'intérieur, ce qui rend la transposition tentante — rappel que WAMA n'est **pas** un agent de code (§6) |
| **Devin / Windsurf (Devin Desktop)** | **Codemaps** (structure du dépôt visualisable et interrogeable) · **mémoires** persistantes · approche par **graphe de connaissance** du dépôt avant d'agir · délégation d'une tâche locale vers une machine distante d'un clic | le **graphe de connaissance avant d'agir** ≈ ce que nos registres + `WAMA_MECANISMES` font déjà, en déclaratif. La **délégation locale → distante** est un motif pour la grappe de dev (`ROADMAP §16`), pas pour la prod |
| **GitHub Copilot** | consignes de projet (un fichier *copilot-instructions* à la racine) · mode agent conservateur, positionné « sûreté et échelle » | confirme la convergence sur **un fichier de consignes versionné** — que nous avons déjà, et mieux : `AGENTS.md` (doctrine) + `CLAUDE.md` (harnais), séparés |

### 3.3 Frameworks d'orchestration (pas des harnais : des bibliothèques pour en écrire)

| produit | primitives | pour WAMA |
|---|---|---|
| **OpenAI Agents SDK** | agents · **passations** (*handoffs*) · **garde-fous** (*guardrails*, contrôles d'entrée ET de sortie) · **sessions** · **traçage intégré** (générations, appels d'outils, passations, garde-fous, événements maison) | les **garde-fous de sortie** et le **traçage comme primitive** (pas comme journal) sont les deux motifs à retenir → **écart 6** |
| **LangGraph** | graphe explicite · **point de contrôle** (*checkpointer*) → reprise après plantage · **voyage dans le temps** (rejouer depuis un état) | notre équivalent existe déjà, ailleurs et autrement : **Celery + statut en base** pour la reprise, `StudioPipeline` pour le graphe. À citer quand on discutera écart 7, pas à importer |
| **CrewAI / AutoGen / smolagents** | rôles, équipes, conversation multi-agents | rien de net pour un assistant **produit** ; le besoin « plusieurs cerveaux » chez nous s'exprime comme **écart 3** (isolation de contexte), pas comme une équipe d'agents |

### 3.4 Standards — ce qui compte le plus, et le piège du jour

| standard | état 2026-09 | WAMA |
|---|---|---|
| **MCP** | spécification **2026-07-28** : cœur sans état, requêtes multi-allers-retours, routage par en-têtes (`Mcp-Method`, `Mcp-Name`), **résultats de liste cachables** (`ttlMs`, `cacheScope`). Un **serveur** expose `resources`, `prompts`, `tools` ; un **client** expose `sampling`, `roots`, `elicitation` | serveur ✅ **mais outils SEULS** (`list_tools`/`call_tool`, `mcp_server.py:209,217`) — ni `resources` ni `prompts`. Client ⏳ (`ROADMAP §8d Ph3 étape 5`) → **écart 10** |
| ⚠ **MCP `sampling`** | **DÉPRÉCIÉ** au 2026-07-28 (SEP-2577) : *les nouvelles implémentations NE DEVRAIENT PAS l'adopter*, les existantes devraient migrer vers un appel direct au fournisseur | **piège évité de justesse** : « le serveur MCP demande une complétion au client » est le genre d'idée qu'on aurait proposée comme moderne. Elle est morte trois semaines avant cette cartographie. *Un fait externe non daté est un fait faux en puissance* |
| **AGENTS.md** | convention devenue commune à plusieurs harnais (Codex, Copilot, autres) | ✅ **déjà en place, et mieux découpé** : `AGENTS.md` = doctrine lisible par tout agent ; `CLAUDE.md` = le harnais Claude Code seul. Rien à faire |
| **Agent Skills / règles** | convergence générale : un dossier de consignes versionnées, chargées par description ou par portée | ✅ **en avance** : deux natures distinctes et assumées (`common/prompt_skills/` résolu par le CODE pour un modèle qui ne sait pas choisir ; `.claude/skills/` choisi par l'agent d'après sa description) + un écrivain (`/skill-forge`) + un contrôle (`check_skills`) |

---

## 4. WAMA axe par axe — état MESURÉ le 2026-09-19

> ⚠ **Précision de vocabulaire (Fabien, 2026-09-20)** : **l'assistant est COMMUN et inter-mondes**
> — son moteur vit dans `wama/common/services/assistant_engine.py` et sert **quatre** surfaces
> (web, API v1, canaux, et le registre d'outils côté MCP). `home.html` n'est **pas** son domicile,
> c'est la surface où il s'AFFICHE aujourd'hui. Quand une case ci-dessous cite `home.html`, elle
> parle donc d'un **défaut de la surface web**, jamais de l'assistant lui-même — et le corriger
> dans `home.html` ne le corrige pas pour Discord.

> Chaque case « WAMA » cite la ligne qui la fonde. Une case sans citation est une case non mesurée :
> il n'y en a pas dans cette table.

| # | axe | ce que fait l'état de l'art | WAMA, mesuré | écart |
|---|---|---|---|---|
| 1 | **boucle de contrôle** | 11/13 composent plusieurs primitives (ReAct, plan-exécute, générer-tester-réparer, reprise, arbre) | ReAct simple, ~~5 tours max (`assistant_engine.py:694`)~~ **8 appels d'outils puis un dernier appel sans outil pour répondre** (`MAX_TOOL_ITERATIONS`, depuis le 2026-10-05 — remesuré le 28/10), pas de reprise sur échec d'outil : un outil qui rend une erreur repart tel quel au modèle (`:726-734`) | **une seule primitive** |
| 2 | **approbation humaine** | déclarée hors du code de l'outil : `approval_policy` (Codex), Plan/Act (Cline), interruptions (deepagents), `pre_tool_call` → `block`/`approve` (Hermes) | **autorisation ✅, approbation ✗** — et il faut séparer deux cas (mesuré 2026-09-20). **Ajouter une capacité** est déjà fermé : `install_model` est gardé `model_manager`, dont `AppAccessPolicy.min_tier` vaut **`developpeur`**. **Agir sur ses propres données** ne l'est pas : `_refus_app()` répond « peut-il agir dans cette app » (`tool_api.py:2901`), puis l'exécution est immédiate (`assistant_engine.py:726`) ; `grep -c confirm` sur `home.html` → **0** | **écart 1** (recadré) |
| 3 | **planification** | mode plan séparé de l'exécution (Claude Code, Cline, OpenCode) | aucun côté assistant. Le plan EXISTE ailleurs, sous forme déclarative : `StudioPipeline` (nœuds typés, exécution topologique) | l'assistant ne sait pas **proposer** un plan |
| 4 | **sous-agents** | délégation à fenêtre de contexte **isolée** (deepagents, Goose, Claude Code) | **0 occurrence** de « sous-agent » dans `ROADMAP.md` + `WAMA_LLM.md` | **écart 3** |
| 5 | **surface d'outils** | 0 à 37 outils ; Pi en expose 4 | **71** (`len(TOOL_REGISTRY)`, mesuré ce jour ; la doc disait 69 au 12/09, +2 le 19/09) | pas un retard — une **nature** (surface métier). Mais 71 descriptions par prompt système |
| 6 | **registre de fournisseurs** | entrée déclarative par fournisseur : adresse, clé, protocole, **reprises et délais** | ✅ `external_sources.ExternalSource` porte `base`/`setting`/`env`/`api_key_env`/`hosting`/`cost_tier` **et `protocol`** (= le `wire_api` de Codex) `external_sources.py:91-127`. ✗ mais **deux tables coexistent** : `CLOUD_DEFAULT_MODELS` (9 fournisseurs, dont **8 sans entrée** au registre) et `OPENAI_COMPATIBLE_PROVIDERS = {'albert': 'albert'}` — **dérivable** de `protocol == 'openai'` (`llm_utils.py:256-270`). ✗ aucun délai ni reprise par fournisseur (`timeout=180.0` en signature, `llm_utils.py:291`) | **écart 5** |
| 7 | **isolation d'exécution** | point de **convergence** de tous les harnais : bac à sable OS, conteneur, VM | WAMA n'exécute **pas** de code arbitraire pour l'utilisateur : les outils sont des **verbes métier** fermés. Le seul chemin d'exécution large est `ask_claude_code`, gardé développeur **dans son corps** et en lecture seule par défaut (`claude_code.py:102-237`) | **rien à faire — frontière voulue** (§6) |
| 8 | **standards** | MCP serveur (resources/prompts/tools) + client | serveur = **outils seuls** (`mcp_server.py:209,217`) ; client ⏳ ; `AGENTS.md` ✅ | **écart 10** |
| 9 | **index du domaine** | plongements vectoriels du dépôt (Cursor), carte mécanique (Aider), graphe (Windsurf) | **15 registres** (`registries.py::overview`), `WAMA_MECANISMES` généré depuis `mecanismes.py`, `doc_facts`, `docs_catalog` — un index **déclaré**, jamais deviné | **en avance conceptuellement** ; l'assistant n'y accède que par `list_registries` |
| 10 | **contexte** | écrire / choisir / **compresser** / **isoler** ; compaction auto à ~95 % ; déchargement des gros résultats d'outils vers un FS | troncature fixe `[-20:]` (`assistant_engine.py:661`) + **escalade de modèle** `_route_model_by_context` (`:258`) — mais appelée **une seule fois, AVANT la boucle** (`:670`) et **seulement sur le chemin local**, pendant que chaque résultat d'outil est réinjecté **brut** par `json.dumps` (`:733`) | **écart 2** |
| 11 | **persistance de session** | format unique repris par toutes les surfaces | ✅ **les trois surfaces partagent le store serveur** (mesuré 2026-09-20) : `views.py:166`, `api/v1/views.py:132`, `gateway/core.py:208` appellent tous `conversation_turn` ; l'historique `localStorage` est mort et effacé (`home.html:101-102`). MCP n'en a pas — il n'exécute aucun tour | **écart 4 REFERMÉ** ⚠ ma 1ʳᵉ version citait la doc, pas le code |
| 12 | **observabilité** | traçage comme **primitive** (Agents SDK) ; flux action/observation (OpenHands) | `tool_steps` persisté par tour (`models.py:1145`) sur les trois surfaces (cf. axe 11) — mais **rien n'en fait une mesure** : aucune vue, aucun agrégat ; `cost_usd` accumulé (`assistant_engine.py:704`). Aucune latence, aucun taux d'échec par outil, aucune vue | **écart 6** |
| 13 | **économie / cache** | cache de prompt côté fournisseur ; listes MCP cachables (`ttlMs`) | **0 occurrence** de `cache_control` dans `wama/` ; le prompt système (outils + contexte + skills) est renvoyé entier à chaque tour | **écart 9** |
| 14 | **mémoire procédurale** | skills par description, règles par portée, règles écrites par l'agent | ✅ **deux natures assumées** (`prompt_skills/` résolu par le code ; `.claude/skills/` choisi par l'agent), **11 skills de prompt** (12 fichiers moins le README), un écrivain (`/skill-forge`) et un contrôle (`check_skills`) | **en avance** — rien à prendre |

**Lecture d'ensemble.** Sur 14 axes : **3 où WAMA est en avance** (9 index déclaré, 14 mémoire
procédurale, 8 en partie via `AGENTS.md`), **1 sans objet par décision** (7 isolation), **4 déjà
routés** (6, 11, et les deux faces MCP), **6 écarts réels**. L'intuition de départ — *« la majeure
partie de ces outils est déjà en place dans WAMA »* — est **confirmée par la mesure**, avec une
nuance : ce qui manque n'est pas de la fonctionnalité, c'est presque toujours une **couche de
contrôle sur ce qui existe déjà**.

---

## 5. Les écarts, triés

> Tri par **conséquence si on ne fait rien**, pas par difficulté. Chaque écart nomme la brique WAMA
> qui existe déjà et qu'il suffirait d'adopter — c'est presque toujours le cas.

### Écart 1 — Autorisation OUI, approbation NON : deux questions à ne pas confondre

> ⚠ **Recadré le 2026-09-20 par Fabien, et il avait raison sur les deux points.** La version du
> 19/09 disait « l'assistant DÉTRUIT sans approbation, le plus grave » et **mélangeait deux
> questions de gravités très différentes**. Le relevé ci-dessous les sépare, et **mesure** ce que
> la première version supposait.

**Deux questions, pas une :**

| | **(a) AJOUTER une capacité** (modèle, librairie, app) | **(b) AGIR sur SES PROPRES données** (`delete_item`, `duplicate_item`, `clear_my_queue`) |
|---|---|---|
| état **mesuré** le 2026-09-20 | **déjà fermé** : `search_models` et `install_model` sont gardés sur l'app `model_manager` (`tool_api.py:3345-3346`), et `AppAccessPolicy` donne à `model_manager` **`min_tier='developpeur'`** — relevé en base : c'est l'une des **4 apps** sur 19 à porter ce palier (avec les jumelles de bac à sable `*_01`) | **ouvert** : le modèle émet l'appel (`assistant_engine.py:707`), `execute_tool` s'exécute **immédiatement** (`:726`), la vue réelle de l'app est POSTée par requête synthétique (`tool_api.py:2928-2944`) ; **0 occurrence** de `confirm` dans `home.html` |
| gravité réelle | **faible aujourd'hui** — un utilisateur ordinaire ne peut pas faire entrer une capacité dans WAMA | **moyenne** — destructif, mais borné à ce que l'utilisateur possède déjà et pourrait supprimer d'un bouton |
| ce qui reste à faire | **rien tant que c'est dev-only** ; tout le jour où on ouvre (voir ci-dessous) | une confirmation avant exécution |

**⚠ Ce qui garde (a) aujourd'hui est une LIGNE EN BASE, pas une règle de code.** `min_tier` est un
champ d'`AppAccessPolicy`, **éditable depuis l'admin** : le jour où quelqu'un descend ce palier
pour dépanner un collègue, l'entrée de capacités s'ouvre **en silence**, sans qu'aucune approbation
ne prenne le relais. C'est exactement le défaut déjà nommé pour la médiathèque dans
`WAMA_LLM.md` — *une garde qui dépend d'une politique modifiable ne protège pas ce qu'elle a l'air
de protéger, elle le rend fragile.* **Le besoin d'approbation n'est donc pas hypothétique : il est
à un clic d'admin.**

⭐ **Position de Fabien (2026-09-20), à tenir comme cadre** : *« le jour où on permet à un
utilisateur d'ajouter des capacités dans WAMA, il faut une approbation »*. Donc l'approbation de
(a) est une **condition d'ouverture**, pas un chantier isolé : elle se construit **avec** la
première surface qui ouvrira l'ajout de capacité à un non-développeur, jamais après.

**Et (b) vaut aussi depuis Discord**, où une phrase mal interprétée coûte la même chose qu'au
clavier — sans même le réflexe visuel d'une page.

**Ce que fait l'état de l'art** : Codex sépare `approval_policy` du code de l'outil ; Hermes
donne au runtime un `pre_tool_call` qui rend `block` (veto) ou `approve` (escalade humaine) ;
Cline sépare Plan et Act ; deepagents interrompt.

**⭐ La brique existe déjà chez nous, trois fois, et jamais sur les outils** :
`MemoryItem.approved=False` par défaut, un souvenir non approuvé étant **invisible au rappel**
(`memory/store.py:104`) · `AIModel.is_proposed` — *« un candidat est une PROPOSITION, visible sur
la page et rejetable d'un clic »* (`prospector.py:879`) · `dry_run` dans **12 modules**
(`purge_media`, `restore_backup`, `rotate_secrets`, `sync_memory`, `mirror_sync`…).
**La doctrine « l'agent propose, l'humain valide » est écrite partout et câblée nulle part sur le
chemin de l'assistant.**

**Ce que ça débloque** : la même couche sert ensuite à tout ce que l'assistant apprendra à faire
(installer un modèle, lancer un traitement lourd, partager un objet). Sans elle, chaque nouveau
verbe rouvre la question.

### Écart 2 — Le contexte n'est pas géré DANS la boucle

**Mesuré** : `_route_model_by_context` (`:258`) est appelé **ligne 670**, avant la boucle qui
commence **ligne 696**, et seulement si `local`. Les résultats d'outils sont ajoutés à `messages`
lignes 730-734, **sans borne**, par `json.dumps(tool_result)`. Donc après cinq appels à
`list_my_items` / `list_registries` / `get_item_detail`, le contexte peut dépasser la fenêtre du
modèle **sans qu'aucune bascule ne soit réévaluée**. L'escalade protège l'historique de
l'utilisateur ; elle ne protège pas de ce que la boucle fabrique elle-même.

**Ce que fait l'état de l'art** : deepagents décharge les gros résultats d'outils vers un système
de fichiers et remplace l'argument par une référence ; Claude Code compacte au-delà d'un seuil.
Les deux se combinent avec l'escalade, ils ne la remplacent pas.

**Coût chez nous** : borner le résultat d'outil + réévaluer la bascule dans la boucle ≈ 15 lignes.
Le déchargement vers un fichier est un cran au-dessus et supposerait un espace de travail par
conversation — à ne pas ouvrir sans écart 4.

✅ **Refermé le 2026-10-28 (`61e3e947`)** — chantier 1 du §9, état en tête de ce chantier. Les
lignes citées ci-dessus sont celles du 19/09 : l'injection vit aujourd'hui dans la boucle de
`run_assistant_turn`, après l'étape diffusée.

### Écart 3 — Pas de sous-agents : 71 outils dans un seul contexte

**Mesuré** : 0 occurrence de la notion dans nos documents ; 71 outils exposés au même prompt.
Les harnais de l'état de l'art tiennent entre 4 et 37 outils et **isolent** dès que ça dépasse.

**La forme WAMA de cette idée existe déjà à moitié** : le **domaine** est choisi par l'assistant
(`assistant_skills.py`), et les skills sont chargés par `charger_competence`. Un « sous-agent »
chez nous ne serait pas une équipe d'agents mais **une délégation par domaine, avec sa propre
fenêtre et son propre sous-ensemble d'outils** — ce qui répond aussi à écart 2 (un outil coûteux rend un
résumé au lieu de son JSON). ⚠ Et ça n'exige **pas** LangGraph : la boucle existante suffit.

**Une marche plus basse, avant le sous-agent** (relevé le 2026-09-30, veille AnythingLLM —
`ROADMAP §16.2`) : **présélectionner les outils par requête** au lieu d'annoncer les 71. L'éditeur
annonce jusqu'à −80 % de jetons — chiffre **d'éditeur, non mesuré**. Chez nous les pièces existent :
`TOOL_REGISTRY` (les descriptions), `bge-m3` et le rappel hybride de `wama/common/memory/` (le
classement). ⚠ Le risque est l'inverse du gain : un outil écarté à tort est un outil que le modèle
**ne peut plus appeler** — donc un domaine forcé (celui choisi par `assistant_skills.py`) plutôt
qu'une similarité seule, et une mesure (tours où l'outil utile manquait) avant toute bascule.

### Écart 4 — ~~L'historique diverge par surface~~ **REFERMÉ, et il l'était déjà quand je l'ai écrit**

> ⚠⚠ **Corrigé le 2026-09-20. C'est une erreur de méthode, pas un détail** : le 19/09 j'ai écrit
> « web = `localStorage`, API = fourni par le client, Discord = base » en **citant la table §A de
> `WAMA_LLM.md` (datée du 15/09)** au lieu d'ouvrir le code. La règle du dépôt dit exactement
> l'inverse — *un constat de la doc qui contredit le code a tort par défaut*. Deuxième fois dans
> la même passe qu'une source datée me fait écrire un constat faux (l'autre : `wire_api`).

**Mesuré le 2026-09-20 — les trois surfaces partagent déjà le même store serveur :**

| surface | appel | ligne |
|---|---|---|
| web | `conversation_turn(user, message, surface='web', …)` | `wama/views.py:166` |
| API v1 | `conversation_turn(request.user, message, surface='api', …)` | `wama/api/v1/views.py:132` |
| canaux (Discord) | `conversation_turn(user, invite, surface=msg.channel, …)` | `wama/gateway/core.py:208` |

Et l'historique navigateur est **mort et nettoyé**, pas seulement inutilisé :
`home.html:101-102` — *« localStorage n'a plus de lecteur — elle est effacée »* + un
`removeItem` de l'ancienne clé. Ce qui reste en `localStorage` est le **seul réglage de voix**
(`:107,188`), qui est bien une préférence propre au navigateur.

**Reste, et c'est tout** : MCP n'a pas d'historique — mais MCP **n'exécute pas de tour
d'assistant** (il expose des outils, `mcp_server.py:209,217`), donc ce n'est pas une divergence,
c'est une absence d'objet. **Cet écart est refermé** ; le chantier `ROADMAP §8d Phase 3` garde les
autres divergences de la table §A (choix du modèle, fichiers, commandes, voix), pas celle-ci.

⭐ *Ce que ça dit des deux analyses externes : leur premier grief était le plus juste sur le
principe et le plus périmé sur les faits. Une analyse qui lit nos docs sans lire notre code hérite
de nos propres retards de doc.*

### Écart 5 — Deux tables de fournisseurs coexistent

**Mesuré** : `external_sources` déclare 3 fournisseurs LLM avec leur `protocol` ;
`CLOUD_DEFAULT_MODELS` en liste **9**, dont **8 n'ont aucune entrée au registre**
(`llm_utils.py:256-266`). Conséquence déjà nommée ailleurs : *un fournisseur sans source déclarée
(`openai`, `mistral`…) n'a ni garde ni clé personnelle, atteignable par l'API v1 et un POST forgé*
(`WAMA_LLM.md:782`). Et `OPENAI_COMPATIBLE_PROVIDERS` est une **dérivation pure** de
`protocol == 'openai'` — exactement le geste fait le 2026-09-19 sur les doublons de format
(`10485654`).

**Les deux tables ne se contredisent pas ; c'est leur COEXISTENCE qui est le défaut.**
Seul apport net de l'état de l'art ici : **délai et reprises déclarés par fournisseur** (un modèle
local et une API souveraine n'ont pas le même profil ; aujourd'hui les deux ont 180 s).
⚠ Et un fait qui invalide une recommandation reçue : chez Codex, `wire_api` **n'a plus qu'une seule
valeur** (`responses`) — le « `chat` ou `responses` » qu'on nous citait est périmé.

### Écart 6 — Aucune trace exploitable de ce que l'assistant a fait

**Mesuré (corrigé le 2026-09-20)** : `tool_steps` **est** persisté par tour, et sur les trois
surfaces depuis que toutes passent par `conversation_turn` (cf. écart 4) — `models.py:1145`,
écriture `conversation_store.py:79`. **La matière première existe donc déjà.** Ce qui manque n'est
pas l'écriture, c'est **tout ce qui en ferait une mesure** : le pas de temps (aucune durée par
appel d'outil), le verdict (aucun champ ne dit si l'appel a abouti — l'échec est **dans le corps** du résultat,
donc illisible sans réinterpréter chaque outil : `assistant_engine.py:727`), et le
lecteur (aucune vue, aucun agrégat, aucun test). *Un journal qu'on n'interroge pas n'est pas une
trace — c'est un dépôt.*

**⭐ C'est le même trou que celui identifié en juillet sur l'auto-amélioration** — la brique
`RunOutcome` / `ResultFeedback`, dont il était déjà écrit que *« toutes les boucles
d'auto-amélioration visées sont bloquées sur son absence, et aucun framework ne récupérera le
signal rétroactivement »*. **La question « comment WAMA s'auto-améliore » et la question « quel
harnais nous manque » ont donc la même réponse, et elle n'est ni chez Hermes ni chez deepagents :
c'est une trace de résultats que nous seuls pouvons écrire.** Le motif à copier est celui
d'OpenHands (action → observation comme **format d'exécution**, pas comme journal) et du traçage du
SDK d'OpenAI (primitive, pas greffon).

### Écart 7 — Rien n'est annulable

Ni point de reprise (Cursor en crée un à chaque application de modifications), ni voyage dans le
temps (LangGraph), ni commit par changement (Aider). Chez nous, une suppression par l'assistant est
définitive. **Couplé à écart 1** : tant qu'il n'y a pas d'approbation, l'absence d'annulation est un
risque ; avec l'approbation, ça redevient un confort.

### Écart 8 — Aucun retour en direct

**Mesuré** : aucune réponse en flux côté assistant (aucun `StreamingHttpResponse` ni
`text/event-stream` dans `wama/` hors la sonde MCP) ; les étapes d'outils sont affichées **après**
le tour (`home.html`, alors). Avec un modèle local et jusqu'à 5 tours d'outils, l'utilisateur
attend sans rien voir. Tous les harnais de la carte streament tokens **et** étapes.
C'est l'écart le moins profond et le plus visible.

### Écart 9 — Aucun cache de prompt

**Mesuré** : 0 occurrence de `cache_control`. Le prompt système (71 descriptions d'outils +
contexte + skills) repart entier à chaque tour, y compris sur les chemins facturés.
⚠ À ne pas confondre avec le cache du modèle local (`keep_alive`), qui est autre chose.

### Écart 10 — Le serveur MCP n'expose que des outils

**Mesuré** : `list_tools` / `call_tool` seulement (`mcp_server.py:209,217`). La spécification
2026-07-28 prévoit aussi `resources` et `prompts` côté serveur. Nos **15 registres** et nos docs
(`docs_catalog`) sont exactement ce qu'on appelle des *resources* : un client tiers pourrait les
lire sans qu'on écrive un outil par registre. ⚠ En revanche **`sampling` est déprécié** depuis
cette même version : ne rien bâtir dessus.

---

## 6. Ce qu'on ne reprend PAS — et pourquoi ce sont des réponses, pas des trous

> *Une frontière VOULUE se lit comme une réponse, jamais comme un trou à combler* (`AGENTS.md`).
> Les décisions ci-dessous sont **citées**, pas recopiées : leur domicile reste indiqué.

| ce qu'on ne prend pas | pourquoi | domicile de la décision |
|---|---|---|
| **un runtime d'agent concurrent** (Hermes, deepagents/LangGraph, CrewAI) | WAMA a déjà Django + Celery + `resource_governor` comme domicile **unique** du GPU. Un second ordonnanceur lançant de la charge à côté du gouverneur est un corps étranger | §7.1 ; `ROADMAP §16` |
| **le bac à sable OS** (Seatbelt, landlock, seccomp) | il isole l'exécution de **code arbitraire** sur un poste de développeur. WAMA n'exécute pas de code utilisateur : ses outils sont des verbes métier fermés (§4, axe 7) | ce document |
| **la mutation à chaud** (Cordis/dsh) | WAMA a **choisi de ne pas avoir** ce problème : son déterminisme vient du refus de la mutation runtime | §7.2 |
| **le registre éphémère reconstruit au démarrage** (Hermes) | viole la propriété de sûreté de nos manifestes (rien ne lit le manifeste en direct ; l'ingest est le seul pont) | §7.1, dernier bloc |
| **`sampling` MCP** | **déprécié** au 2026-07-28 (SEP-2577) | §3.4 |
| **l'index vectoriel du code** (Cursor) | nos registres **déclarent** ce que WAMA sait nommer ; un index deviné à côté d'un index déclaré, c'est deux vérités | §4, axe 9 |
| **le domaine d'usage** (agent de code) | Codex, Cursor, Aider, Cline, OpenHands résolvent « éditer un dépôt ». WAMA résout « piloter des apps média/IA pour un labo ». Les axes se transposent, **les gestes non** | ce document |

---

## 7. Évaluations consignées

### 7.1 Hermes Agent (Nous Research) — évaluation + décision (2026-07-29)

*(intitulé d'origine de `ROADMAP §16.7`, repris tel quel ; seule la ligne de titre est restée
là-bas pour porter le renvoi — le corps ci-dessous est celui de la roadmap, inchangé.)*

> **Déplacement du 2026-09-19** (décision de Fabien : *« déplacer mot pour mot + pointeur »*).
> Le texte ci-dessous est **inchangé** — aucune reformulation n'a été faite au passage, exactement
> comme lors du déplacement des ex-§2/§7 de `PROFILES_PERMISSIONS` vers `WAMA_COLLABORATION`.
> `ROADMAP §16.7` porte désormais un renvoi vers ici.
>
> ⚠ **Résidu signalé, pas découpé** : environ **60 lignes** de ce bloc (« Manifeste ≠ registre »,
> « Registres — état réel », la couche capacités des librairies, « Boucle ») ne parlent **pas
> d'Hermes** — c'est l'état du chantier registres/manifestes de WAMA, qui appartient à la ROADMAP.
> Les découper à la main aurait été **réécrire un déplacement**. Elles voyagent donc telles quelles
> et **doivent être re-domiciliées** à la prochaine passe (§9, décision 6). *Signalé plutôt que corrigé en
> silence : un déplacement qui trie n'est plus un déplacement.*

**Existence vérifiée** (recherche web) : MIT, sorti fév. 2026, ~46k stars, v0.18.2 en juillet.
Runtime d'agent auto-hébergé, sans télémétrie, mémoire persistante inter-sessions, **skills générés
depuis l'expérience** dans `~/.hermes/skills/`, plugins découverts via `entry_points`/`~/.hermes/plugins/`,
LLM-agnostique (tout endpoint compatible OpenAI). Le « MCP natif » annoncé par certaines sources
**n'a pas pu être confirmé** — à vérifier avant de s'appuyer dessus.

**Ce qui est retenu / ce qui est écarté** — il faut séparer deux objets :

| Couche Hermes | Verdict | Pourquoi |
|---|---|---|
| **Runtime** (boucle, backends d'exécution Docker/SSH/Modal, ~20 passerelles de messagerie) | **ÉCARTÉ en prod** | WAMA a déjà Django+Celery+`resource_governor` (domicile UNIQUE GPU/CPU/RAM). Un 2e ordonnanceur lançant de la charge GPU à côté du gouverneur = corps étranger (cf. 4 kernel panics WSL2 du 29/07). Les passerelles de messagerie sont hors sujet. |
| **Mémoire procédurale** (distiller une tâche résolue en skill réutilisable) | **IDÉE RETENUE — et LIVRÉE** | C'est le seul apport réel. ⚠ **Deux affirmations de cette ligne sont périmées, corrigées le 2026-09-09.** (1) « il manque l'écrivain » : l'écrivain EXISTE, c'est le skill `/skill-forge`. (2) « `common/prompt_skills/` est déjà le format de stockage » : **non** — il écrit dans `.claude/skills/` (dossier + fichier SKILL.md à frontmatter), et c'est le bon domicile, car une consigne de dev est **choisie par un agent d'après sa description**, là où `prompt_skills/` est résolu par le CODE pour un modèle qui ne sait pas choisir (`WAMA_LLM §0bis 🔒`). ⚠⚠ (3) **« Ce qui manque est le DÉCLENCHEUR » — écrit le matin du 2026-09-09, corrigé le soir même : c'était imprécis.** Le déclencheur EXISTE : `/cloture` déroule `/skill-forge` (« distiller à la clôture est LE moment-écrivain »). Le défaut réel est qu'une étape de rituel dépend de la DILIGENCE — et il est mesuré dans le dépôt : `PROJECT_STATUS:10928` note « `/skill-forge` NON déroulé (clôture tardive) ». D'où **`manage.py check_skills`** (2026-09-09), même médecine que `check_docs` : candidats `n=1` et leur âge (§3/§4), déclencheur absent d'une `description` (§5.2), frontmatter incomplet. ⚠ Il ne mesure PAS « ce geste s'est répété » : cette inférence exige une trace des gestes de DEV que le dépôt n'a pas (`/skill-forge §4` — « l'équivalent `RunOutcome` du runtime n'existe pas encore »). **C'est LÀ, et seulement là, que se joue le reste de l'auto-amélioration de Hermes.** |

**Point LiteLLM** — LiteLLM est documenté comme provider de référence côté Hermes (proxy
OpenAI-compatible, ~100 fournisseurs, load balancing, fallback, contrôle budgétaire). Câblage :

```yaml
model:
  default: <nom-du-modele>
  provider: custom
  base_url: http://localhost:4000/v1
  api_key: <clé-ou-vide-en-local>
```
Bascule en cours de session à 3 niveaux : `/model custom:local:qwen-2.5`,
`/model custom:work:llama3-70b` → le routage LiteLLM local+cloud existant (§8d) reste inchangé, on
change juste de modèle selon la tâche.

⚠ **DEUX RÉSERVES — ne pas répéter la formule « un seul catalogue à maintenir », elle est fausse
aujourd'hui :**
1. **Bug ouvert sur ce couplage précis** : Hermes + endpoint OpenAI-compatible custom via LiteLLM sur
   `localhost:4000` ⇒ **les requêtes du gateway n'atteignent pas l'endpoint**. Reproductible par
   config CLI, fichier de config, ou `HERMES_INFERENCE_PROVIDER=custom`. Signalé sur v2026.4.3
   (peut-être corrigé sur `main`). Le chemin de code affecté semble être le **gateway
   (mode messagerie/API)** — **pas** le mode **CLI/TUI**. ⇒ **tester en TUI d'abord**, gateway
   seulement après vérification.
2. **Pas d'auto-découverte** : le sélecteur `/model` n'affiche que les modèles **listés manuellement**
   dans le `config.yaml` d'Hermes. Ajouter/retirer un modèle côté LiteLLM ⇒ **mise à jour manuelle**
   de la config Hermes. L'objection « énième config modèles à tenir à jour » n'est donc **PAS levée** —
   elle est seulement *réductible*, en générant ce `config.yaml` depuis le catalogue `AIModel`.

**Découverte de plugins Hermes — 4 sources** (vérifié sur la doc du dépôt, 2026-07-30) : **bundled**,
`~/.hermes/plugins/` (user), `.hermes/plugins/` (projet), et les **`entry_points` pip**. C'est la 3e qui est le vrai point d'accroche : le registre WAMA peut
**piloter la génération des `entry_points` exposés à Hermes**, avec correspondance directe
`fonctions_exposées` → outils découverts par Hermes. (Il ne s'agit donc pas d'un symlink de
manifestes mais d'une génération de points d'entrée.)

**Débat capacités** (recadrage utilisateur, retenu) : la philosophie WAMA **est** l'agrégation de
capacités, et le mécanisme de plugins d'Hermes relève de la même logique — l'objection initiale
« corps étranger » ne vaut que pour le runtime, pas pour l'agrégation. **Convergence** : le registre
WAMA reste **source unique** ; les manifestes de plugins Hermes sont **générés depuis lui**, jamais
saisis en double. Deux consommateurs (UI WAMA + Hermes), un seul inventaire.

**Manifeste ≠ registre — articulation WAMA** (corrige une inversion commise en séance) : le
**manifeste est le point d'entrée** de toute nouvelle capacité (1 manifeste = 1 unité : une lib, un
modèle, une app) ; les **registres** (`model_manager`, `app_registry`, `TOOL_REGISTRY`) maintiennent
la connaissance en base et servent les pages de gestion. Les deux coexistent — le kind ne remplace
pas le registre, il en décrit l'unité. ~~Il manque donc **les deux** côté librairies~~ **FAIT
(2026-08)** : le registre `common.models.Library` (né de la projection `write_back_library`,
migration 0004) ET le kind `library` existent (1er lien transcriber→faster-whisper).

**Registres — état réel (mis à jour 2026-08-11, deux « fonctions » à NE PAS confondre)** :
modèles (`AIModel`/`model_registry.py`) ✅ · apps (`app_registry.py`/`APP_CATALOG`) ✅ ·
**outils assistant** (`TOOL_REGISTRY`/`tool_api.py` — surface de PILOTAGE des apps, facette F6) ✅ ·
**fonctions DATA** (fonctions-cartes appliquées aux données, ex. cam_analyzer :
`common/catalog/function_catalog.py::FUNCTION_CATALOG` + `UserFunction` DB scopée — kind `function`
les EXTRAIT, page `/model-manager/functions/`) ✅ ·
bibliothèques (`common.models.Library` + kind `library`) ✅.
~~⚠ Trou write-back côté fonctions data~~ **FERMÉ (2026-08-11 soir)** : `write_back_function`
projette un manifeste `function` `binding=user` vers `UserFunction` (idempotent, owner résolu,
tag `_manifest-gen` bornant la révocation — une fonction autorée en UI n'est jamais retirée) ;
les fonctions `pure`/`app` du catalogue code restent du code-gen.
~~Ce qui manquait côté librairies : la PAGE~~ **PAGE LIVRÉE (2026-08-11 soir, signalée le
matin)** : `/model-manager/libraries/` (patron `function_catalog` — cards du registre +
installation MESURÉE live `importlib.metadata`, dérive vs `pip_spec` signalée, `is_allowed`
lisible) + entrée « Librairies » au menu utilisateur. La page LIT le registre ; `is_allowed`
se décide dans l'admin (allowlist hors write-back, verrou n°2 Hermes) ; le bouton
d'installation viendra avec le provisionneur (plan → validation humaine →
`apply_patches.py` en post-étape).

Besoin réel : savoir **quelle app dépend de quelle librairie** (`opencv`, `ffmpeg-python`…), ce qui
casse si on met à jour, et **quel environnement a quelle version** (dev/prod, machines différentes —
un `pip freeze` ne répond qu'à la 3e question, sur une seule machine).

**Deux couches à ne pas confondre :**

| Couche | Contenu | Maintenance |
|---|---|---|
| **1. Inventaire technique** | version installée par environnement, dérive entre machines | **AUTOMATISABLE** — `importlib.metadata.distributions()` + cron de détection de dérive |
| **2. Couche capacités** | à quoi sert la lib, qui en dépend, ce qu'elle expose | **MANUELLE — c'est celle qui a de la valeur** |

Schéma d'entrée (couche 2) :
```yaml
- nom: opencv-python
  version_min: "4.9"
  catégorie: vision
  apps_dépendantes: [cam_analyzer, anonymizer, avatarizer]
  fonctions_exposées: [lecture_video, détection_contours]
  criticité: haute
  dernier_audit: 2026-07-29
  licence: Apache-2.0        # ex. pandas → BSD-3 ; utile pour un labo public
```

Justification WAMA-spécifique en plus de « qui dépend de quoi » : les champs `version_min` +
`criticité` + un patch associé serviraient directement `patches/apply_patches.py` (patches venv
perdus silencieusement au `pip install --upgrade`), les pins connus (`setuptools<81`, torchcodec
cassé, xformers/torch 2.9) et la charpente de tests nocturnes.

**Boucle** : c'est le manifeste — pas Hermes — qui est la source. Une fois `apps_dépendantes` et
`fonctions_exposées` remplis, ils alimentent à la fois l'UI WAMA et la génération des `entry_points`
consommés par Hermes. Sans eux, un agent qui « auto-maintient les libs » travaille à l'aveugle.

#### Confrontation Hermes ↔ WAMA (vérifiée sur code + doc du dépôt, 2026-07-30)

**Convergence de formalisme** : Hermes impose lui aussi un **manifeste par plugin** (YAML, « Step 2:
Write the manifest », « Manifest declares what the plugin is ») avec un champ **`kind`** discriminant
(`kind: platform` pour un adaptateur de gateway ; `kind: exclusive` auto-détecté pour un fournisseur
de mémoire, routé via `memory.provider` au lieu de `plugins.enabled`). Deux équipes ont convergé vers
l'union discriminée. Découverte par **scan** des 4 sources, registre peuplé à l'exécution par
`ctx.register_tool()` (collisions refusées sauf `override=True`).

**Renversement source/dérivé — le point structurant :**

| | Source de vérité | Dérivé |
|---|---|---|
| **WAMA** | le **manifeste** (cible architecturale) ; **en pratique le registre** pour 5 kinds/6 | manifeste via `extract` |
| **Hermes** | le **manifeste** (fichier disque) | le **registre**, reconstruit par scan à chaque démarrage |

⚠ **État réel de la projection WAMA (vérifié dans `builtin/*.py`, pas seulement dans la doc)** :
`app` = seul kind avec `project`/`un_project` ; `function` a `project=None` ; `model`, `pipeline`,
`project`, `dataset` n'ont **aucune** projection. Soit **1 kind sur 6**, et côté `app` une seule
facette (`access` → `AppAccessPolicy`) en **dry-run par défaut** (`apply=False`). Autrement dit : le
formalisme, l'enveloppe et l'ingest sont là, **c'est la projection qui manque** — un manifeste de
modèle ne crée aujourd'hui aucun `AIModel`.

**Pourquoi c'est plus dur chez nous que chez eux** : le registre d'Hermes est **éphémère** (rebâti par
scan au démarrage) ⇒ rien à écrire en retour, ni idempotence ni réversibilité à garantir. Nos
registres sont des modèles Django **persistés et vivants** qui servent les pages de gestion ⇒ la
projection doit être idempotente **et** réversible. **Notre difficulté est la contrepartie de notre
persistance**, pas un retard de travail.

**Modèles — Hermes ne le fait PAS.** Son plugin modèle est `register_provider(ProviderProfile(...))`
(+ `auth_type`) : il ajoute un **fournisseur**, pas un catalogue ; et `/model` n'affiche que ce qui est
écrit à la main dans son `config.yaml`. ⇒ **`AIModel`/`model_registry.py` est en AVANCE sur Hermes.**
Ne pas aller y chercher une solution qui n'existe pas.

**Librairies — Hermes le fait réellement**, via `tools.lazy_deps.ensure(...)` (install à la première
utilisation), avec **4 verrous superposés à transposer** :
1. **Kill switch global** `security.allow_lazy_installs: false` ⇒ `FeatureUnavailable` + indice de
   remédiation, et le plugin doit **se dégrader proprement** (erreur retournée, pas de crash de la
   boucle d'outils) ;
2. **Allowlist `LAZY_DEPS` en dur dans l'arbre** — motif cité : *« prevents a malicious config from
   coaxing Hermes into installing arbitrary packages — only specs Hermes itself ships are eligible »*
   (la config utilisateur ne peut pas élargir le périmètre) ;
3. **PyPI par nom uniquement** — ni `--index-url`, ni `git+https://`, ni `file:` ;
4. **Pin PEP 440 dans l'entrée d'allowlist** (`"my-sdk>=1.2,<2"`).
Les plugins **tiers** sont volontairement **exclus** de l'auto-install (extras
`[project.optional-dependencies]`) ; le lazy-install ne sert qu'aux plugins *bundled*.

⚠ **Transposer les VERROUS, pas le CYCLE DE VIE.** Hermes installe *à la première utilisation*,
capacité jetable, optimisé pour « ne jamais être bloqué par une dépendance manquante » — modèle
d'assistant personnel. WAMA est un **outil de labo** : l'ingestion est **progressive et cumulative**,
une capacité ingérée **reste intégrée**. On n'installe/désinstalle pas au fil de l'eau. Le moment de
l'installation est donc **l'ingestion du manifeste** (une fois, sous validation), pas l'appel d'outil.
Raison de fond : **reproductibilité scientifique** — un résultat de recherche doit rester
re-productible des mois plus tard, ce qu'un parc de dépendances volatil rend impossible. C'est ce qui
justifie `version_min`, les pins et `dernier_audit` : traçabilité de l'état d'environnement, pas
seulement hygiène.

**Trois protections supplémentaires à voler** : (a) **`requires_env`** dans le manifeste — conditionne
le chargement à des variables d'env, **demandées interactivement** à l'installation et écrites dans
`.env`, avec description + URL d'inscription (utile vu l'externalisation des secrets) ; (b)
**`pre_tool_call`** peut retourner `{"action": "block"}` (veto) ou `{"action": "approve"}` (**escalade
vers validation humaine**) = notre doctrine « l'agent propose, l'humain valide » câblée dans le
runtime ; (c) **aucune porte dérobée** — `ctx.dispatch_tool()` passe par *« the normal approval,
redaction, and budget pipelines — not a shortcut around them »* ⇒ toute capacité ajoutée par
manifeste doit passer par le `resource_governor` et le chemin de permission normal, sans exception
privilégiée.

**Recommandation — `library` = kind PILOTE du manifeste-first**, parce qu'il n'a **aucun registre
hérité à réconcilier** : son registre naîtrait *de* la projection au lieu de la précéder. C'est un
terrain vierge pour prouver la chaîne manifeste → ingest → registre → capacité → studio, avant
d'attaquer la projection des 5 kinds hérités.

⚠ **NE PAS importer le régime Hermes ici** — le registre éphémère « recalculé à la lecture » viole la
**propriété de sûreté `WAMA_MANIFEST_SPEC.md` §2.1** (*rien ne lit le manifeste en direct ; ingest =
seul pont gaté ; état committé = les registres ; un manifeste corrompu ou supprimé ne corrompt pas
l'aval*). Hermes peut se le permettre parce qu'un plugin absent ne casse qu'une capacité optionnelle ;
chez nous un registre volatil casserait les pages de gestion. ⇒ `library` obtient un **vrai registre
persisté, écrit par l'ingest** comme les autres kinds. L'avantage du terrain vierge subsiste (rien à
rattraper), la garantie de sûreté aussi.

⚠ Non vérifié : nom de fichier exact et liste complète des champs du manifeste de plugin Hermes, et
nom du groupe d'`entry_points` (le site coupe la connexion ; lu via le dépôt uniquement).

### 7.2 DeepSeek Harness (`dsh`) / noyau Cordis — première consignation dans le dépôt

> ⚠ **Cette évaluation datait du 2026-08-20 et n'avait JAMAIS été écrite dans le dépôt** : elle ne
> vivait que dans la mémoire d'agent. Elle est consignée ici telle qu'elle a été décidée, avec sa
> date d'origine. *Une décision hors du dépôt se re-prend de zéro à la session suivante.*

**Contexte** : analyse demandée par Fabien sur DeepSeek Harness et son noyau **Cordis**, avec un
avis critique sur ce qu'il y aurait à en prendre.

**Décision (2026-08-20) : ne rien intégrer.** La raison de fond est plus nette que
« pile incompatible » : dsh résout la **modification à chaud d'un process vivant** (plugins montés
et démontés en session), problème que **WAMA a choisi de ne pas avoir** — son déterminisme vient du
refus de la mutation runtime.

**À savoir si le sujet revient :**

- Cordis n'est **pas nouveau** : c'est le noyau de Koishi, ~4 ans, 4000+ plugins. Le papier
  (PKU + DeepSeek-AI) formalise **après coup** un noyau éprouvé — ce n'est pas de la spéculation
  d'architecte, et c'est ce qui le rendait digne d'examen.
- Sa garantie a une **limite structurelle** : il ne peut rien prouver sur les effets **non
  enregistrés** auprès de son contexte. Une garantie « par construction » qui dépend de la rigueur
  de l'auteur du plugin est une **convention outillée**, pas une garantie.
- WAMA tient déjà l'équivalent des **effets réversibles** au niveau manifeste :
  `write_back` / `un_write_back` sur `ManifestKind`.

**La seule chose reprise — et elle était DÉJÀ prescrite en interne** : remplacer une cascade
`if type === …` par un **registre keyé**. Appliqué le 2026-08-20 à `wama-params.js` (7 renderers +
`registerRenderer`, A/B du HTML identique octet par octet). ⚠ Ce n'était **pas** un emprunt : la
condition était écrite dans `wama/common/mecanismes.py` — *« `audio_player` deviendra un rendu le
jour où l'aiguillage par mime de `renderInlinePreview` sera un registre et non une cascade de
`if` »*. **Cible suivante encore ouverte** : cette cascade mime, présente en **deux exemplaires**
(`wama-inspector.js` et `media-preview.js`).

**⭐ La règle durable qui en sort — elle vaut pour TOUTE cette cartographie** :

> garder les **coutures à la frontière** — backends de modèles, fournisseurs LLM, renderers d'UI,
> moteurs 3D. Tout ce qui bouge vite doit être un **provider remplaçable**, jamais quelque chose
> qu'on réécrit. **Le jour où un harnais d'agent devient incontournable, on le branche comme
> provider ; on ne migre pas WAMA dessus.**

### 7.3 Ce qui n'est PAS un harnais et reste ailleurs

- **Twenty** (CRM métadonnée-driven) → `ROADMAP §16.8`. C'est une confrontation de **formalisme**
  (manifeste, objets, permissions), pas de harnais.
- **LiteLLM, pgvector, Headroom, Presidio, Docling, Langfuse, LocalAI, Bifrost…** → `ROADMAP §16.2`.
  Ce sont des **composants**. ⚠ Deux d'entre eux touchent quand même des axes d'ici : **Langfuse**
  (observabilité, écart 6) et **Headroom** (compression, écart 2, aujourd'hui réservé au dev) — les citer
  depuis écart 6/écart 9 le moment venu, ne pas les rapatrier.
- **AnythingLLM** (2026-09-30) → `ROADMAP §16.2` : un produit chat + RAG, rejeté comme LibreChat ;
  son seul apport d'ici est la présélection d'outils (écart 3).
- **llmfit**, **YuE2 / ACE-Step** → `ROADMAP §16.2` également, mais ce sont respectivement un
  outil de mesure et un **modèle** : ils n'ont rien à faire dans une cartographie de harnais.
  *(Leur présence en §16.2 est le signe que cette section est devenue un fourre-tout ; ce n'est pas
  à ce document de le corriger.)*

### 7.4 Codex et OpenCode lus dans leur code, et le plan multi-agents (2026-10-28)

> **Pourquoi ce bloc.** Le 28/10, Fabien a lancé depuis l'assistant cinq tâches de recherche
> (12,95 $) pour préparer les sous-agents, puis le council. Leurs rapports vivent dans
> `logs/dev_jobs/20261028-*.log`, que **`.gitignore:15` exclut du dépôt** : ce bloc en est la
> seule trace versionnée. Chaque ancrage WAMA a été relu dans le code le jour même ; ce qui est
> marqué *non vérifié* ne l'a pas été dans le dépôt tiers.

**Lu dans le code** : `openai/codex` (`main`, `core/src/session/turn.rs`, `tools/parallel.rs`,
`tools/orchestrator.rs`, `context_manager/history.rs`, `handlers/multi_agents/*`,
`handlers/tool_search.rs`, `models.json`) et `anomalyco/opencode` (commit `d1bd20f`, v2.2.0,
`packages/core/src/`). **Pas lus dans leur code** : Hermes, deepagents, DeepSeek/Cordis — leurs
colonnes restent celles de §3 et §7.1/§7.2. Cordis n'est pas à creuser : ni délégation, ni bornage
(§7.2), et l'étape 0 n'en dépend pas.

| question | Codex | OpenCode | retenu pour WAMA |
|---|---|---|---|
| **fin de boucle** | aucun plafond de tours ; bornée par les jetons (compaction en cours de tour) | aucun plafond par défaut (`steps` par agent) ; à la limite, dernier tour **sans outil mais avec la liste d'outils** (le cache du fournisseur sert encore) | garder un plafond (petits modèles locaux, pas de compaction) : 8 pour le parent, moins pour un sous-agent, même dernier appel sans outil (`_TOOL_LIMIT_PROMPT`). ⏳ garder `native_kwargs` au dernier appel, comme OpenCode |
| **bornage** | à l'écriture dans l'historique ; budget **par modèle** au catalogue (10 000 jetons, +20 % JSON) ; en-tête « taille d'origine » ; coupe **au milieu** ; l'intégral reste dans le journal | à la source : 2 000 lignes / 50 Kio, l'intégral écrit dans un fichier relu par `read`/`grep` | ✅ fait (§9 chantier 1) : en-tête, début + fin, intégral dans `tool_steps`. ✗ pas de fichier : notre modèle n'a pas d'outil de lecture de fichier, et l'intégral est déjà en base |
| **sous-agent** | un outil (`spawn_agent`, `wait`) ; contexte **neuf** par défaut (`fork_context=false`) ; hérite fournisseur, approbation, bac à sable ; profondeur bornée (« Agent depth limit reached. Solve the task yourself. ») | outil `subagent` : **session enfant**, profondeur 1 par défaut, le parent ne reçoit que le **texte final** ; un agent interdit est **retiré de la description** de l'outil ; mode de fond annoncé à la fin, sans relance du parent | sous-agent = un tour de **notre** boucle, contexte neuf, outils restreints, mêmes droits que l'utilisateur, profondeur 1 fixée dans le code, retour borné. Le mode de fond existe déjà côté dev (`dev_run_role` → `job_follow_ups`) : ne pas en écrire un second |
| **approbation** | trois états hors de l'outil (`Skip` / `NeedsApproval` / `Forbidden`) ; un outil MCP marqué destructif demande toujours l'approbation ; la source de la décision est journalisée | règles `allow/ask/deny`, la dernière qui correspond l'emporte ; un `deny` passe avant les « toujours » enregistrés ; un refus **avec motif** est rendu au modèle, qui continue | la marque d'écriture **sur la fonction** (chantier 2), publiée aussi en annotation MCP (`readOnlyHint`/`destructiveHint`) — une déclaration, deux consommateurs. ⚠ `clear_my_queue(confirm=…)` n'est pas une approbation : c'est le modèle qui remplit l'argument. L'action en attente reste **dans le cache** (chantier 2), pas en base comme le suggérait la lecture d'OpenCode |
| **trop d'outils** | `tool_search` : outils différés, trouvés par le modèle (BM25) | « code mode » : ~2 000 jetons d'outils annoncés, le reste trouvé par `search()` | lève le risque de l'écart 3 (« un outil écarté à tort ne peut plus être appelé ») : c'est le **modèle** qui cherche. Piste après les sous-agents, à côté de `charger_competence`. ⚠ Mesuré le 28/10 : la liste d'outils fait **18 206 des 24 676** caractères fixes du prompt — c'est elle, le poste dominant |
| **trace** | `tool_result` avec durée et succès ; `tool_decision` avec sa source | événements typés, coût avec lectures/écritures de cache | chantier 3 : `ok`, `duration_ms`, plus tard `decision_source` ; l'usage d'un sous-agent s'ajoute à celui du parent |

**Ce que les deux disent de nos agents « en données ».** Ils existent déjà chez nous : les domaines
(`assistant_skills.DOMAINES`) et leurs skills de rôle (registre `skills`). Un sous-agent prendra un
domaine, **pas** un nouveau registre d'agents. Et le **council** a déjà son précédent :
`model_manager/services/prospect_agents.py`, un jury de N avis LLM **consolidé de façon
déterministe** (consensus, confiance moyenne, accord), sans juge LLM.

**À quoi ça doit servir (Fabien, 2026-10-29)** : au-delà de l'assistant de laboratoire, mener
plusieurs travaux pour une même demande (un audit, une recherche sur le web, un diagnostic, un plan
d'implémentation), et **réfléchir en profondeur à une question de recherche** — council compris —
jusqu'à la **bibliographie**. Ce que le code offre aujourd'hui à un sous-agent, mesuré le jour même :
`search_web` et `read_web_page` (lectures, donc permises), `search_docs`, `memory_recall`. ⏳ Il n'a
**aucune source savante** : ni OpenAlex, ni HAL, ni arXiv, ni Crossref (`model_publications.py` ne
fait que des liens). La bibliographie avancée est déjà une intention de `ROADMAP §21.5` (décision 5 :
la recherche, le dédoublonnage et les citations en **pipeline déclaré**) — l'outil de lecture d'une
source savante s'y rattachera, pas à côté. ⚠ Deux limites voulues : un sous-agent ne **lance** pas
de tâche applicative (écriture, approbation due, chantier 2) — le parent le fait ; et un **audit de
code** passe par les rôles de développement en tâche de fond (`dev_run_role`, suivi par
`job_follow_ups`), qu'un sous-agent ne reçoit pas.

**Le plan, dans l'ordre (décisions de Fabien du 28/10 en gras)** :

| étape | contenu | état |
|---|---|---|
| 0 | chantier 1 : borne **24 000** + bascule réévaluée dans la boucle | ✅ `61e3e947` |
| 0 bis | la **marque d'écriture seule**, sur la fonction (`tool_api.py`) : `@tool_effect(READ / WRITE / DESTROY)`, tout outil marqué (test), filet AST, publiée en annotation MCP ; `sub_agent_tools()` en DÉRIVE (lectures, moins `ask_claude_code`, `open_page`, `fold_side_panels`, chacun avec sa raison ; l'outil de délégation s'y ajoutera). ⚠ `look_at_image` n'est **pas** exclu : la raison avancée (« hors gouverneur ») vaut pour tout appel local de l'assistant (`measured_load`, `vision_probe.py:28`) | ✅ voir §9 chantier 2 |
| 1 | socle : `run_assistant_turn` gagne outils autorisés, nombre d'itérations, échéance, profondeur — **défauts qui laissent le comportement actuel inchangé** ; propagés au jumeau `_invented_turn` ; aucun outil `dev_*` ; exécution **synchrone et séquentielle** d'abord (le parent attend de toute façon ; un seul GPU ; broker `memory://` hors côté autorisé) | ✅ 2026-10-29 : `allowed_tools` (liste du prompt **et** déclaration native réduites — `build_tools_list(names)` coupe la liste déjà construite, sans recalcul ; un outil hors bornes est refusé **avant** `execute_tool`, le refus entre à la trace ; pas d'annonce des compétences sans `charger_competence`), `max_iterations`, `deadline` (horloge monotone, lue seulement si une échéance est posée ; passée, dernier appel sans outil avec `_DEADLINE_PROMPT`), `depth` (`MAX_AGENT_DEPTH = 1` ; au-delà de 0, les outils sont **ramenés** à `sub_agent_tools()` quoi que l'appelant demande — la lecture seule tient dans le moteur, pas chez l'appelant). Garde `tests_turn_bounds` (13 tests, 10 contre-épreuves rouges) |
| 2 | l'outil de délégation. ⚠ Tout ce qui entre dans `TOOL_REGISTRY` est aussi servi par MCP et `/api/v1/tools/` : l'appel doit être **impossible** hors d'un tour d'assistant — de préférence par construction (un verbe de la boucle, aiguillé par son nom comme les `dev_*`), sinon par une garde de contexte du tour | ✅ 2026-10-29 : `delegate(task, domain)` est un verbe de la boucle (`DELEGATE_TOOL`, hors `TOOL_REGISTRY` — garde `tests_delegation`), annoncé et accepté seulement si `run_assistant_turn(can_delegate=True)` et hors abonnement. Jamais à un sous-agent, **par construction** : ses outils sont des lectures du registre, où `delegate` n'est pas (une condition de profondeur écrite en plus s'est révélée MORTE à la contre-épreuve, et a été retirée). Le sous-agent (`_delegate`) : tour de la même boucle, contexte neuf, profondeur 1 donc lecture seule, `SUB_AGENT_MAX_ITERATIONS = 5`, échéance `SUB_AGENT_SECONDS = 300` bornée par celle du parent (des choix de départ, non mesurés), même fournisseur et même modèle, domaine du registre hors développement. Le parent ne lit que le **rapport** ; les étapes du sous-agent vont à la trace (`sub_agents`, depuis l'étape 2 bis), l'usage s'additionne. ⚠ Trou de l'étape 1 fermé au passage : sur l'**abonnement**, Claude Code tourne sa propre boucle avec tous les outils du compte par MCP (`_claude_code_call`) — un tour borné y aurait écrit ; il est désormais refusé avant tout appel |
| 2 bis | le **parallèle**, par serveur (décision de Fabien du 29/10, ci-dessous) : les sous-agents d'un même appel partent ensemble, chacun vers son serveur — le local et les clouds souverains disponibles (Albert, ILaaS) —, et le tour attend le plus lent, non la somme. Le profil d'exposition se juge par sous-agent, les limites de débit déclarées (`rate_limit_wait_s`) s'appliquent | ✅ 2026-10-29 : `delegate(tasks=[…])` lance une **vague** ; chaque tâche prend un **couloir** — un serveur, donc une source du catalogue (`_sub_agent_lanes`) : le premier est le modèle du tour, les suivants le **tirage commun rejoué** en écartant les sources prises (même lot `agent_candidates`, même admission `allowed_cloud_keys` : c'est le profil qui dit jusqu'où une requête sort, aucune règle « souverain » écrite à côté), abonnement exclu. Les couloirs tournent en même temps (un fil chacun, connexions refermées), les tâches d'un même couloir l'une après l'autre ; un profil « 100 % local » n'a qu'un couloir et la vague redevient séquentielle. La panne d'un sous-agent devient son rapport, le tour continue. **Mesuré le jour même** (`fabien.moreau` — `fmoreau` est en « 100 % local » —, messages uniques : la première passe était servie par un cache de réponses, 0,2 s par appel) : 3 modèles d'Albert en simultané, **aucun refus** (6,0 s contre 8,7 s en série) ; un appel par serveur (local `gemma4:e4b`, Albert `gpt-oss-120b`, ILaaS `qwen-3.8-27b`) **4,9 s en simultané contre 11,1 s en série**. Une passe, forte variance (ILaaS 7,1 s puis 2,7 s) : un ordre de grandeur, pas un banc. Garde `tests_delegation.ParallelWaveTest` (la simultanéité prouvée par une barrière : en série, elle casse) |
| 3 | garde-fous : interrupteur déclaré (l'outil n'est alors pas annoncé), qui peut déléguer, plafond d'**appels au modèle** (un coût en dollars n'est pas mesurable : le chemin cloud ne rapporte pas de coût), journal par sous-agent | ✅ 2026-10-29 : l'**interrupteur** est un réglage de l'assistant (`sub_agents`, `assistant/params.py`, panneau et modale ⚙), **éteint par défaut** ; `conversation_turn` le lit pour les trois surfaces (web, API, Discord). **Qui peut déléguer** : tout compte qui a l'assistant et allume le réglage — un visiteur anonyme reste aux défauts. Le **plafond** passe par le nombre de sous-agents d'un tour (`MAX_DELEGATIONS_PER_TURN = 3`, **porté à 6 à l'étape 4**, compté en sous-agents, pas en appels de `delegate`) : avec leurs bornes, au plus 6 × 7 appels de sous-agents en plus de ceux du parent (choix non mesuré). Le **journal** : la trace porte `sub_agents` — par sous-agent, sa tâche, son modèle, ses étapes, sa durée —, et une ligne `[ai_chat] sous-agent` au journal du serveur. ⚠ Non mesuré : un tour long en **API v1** (sans flux) reste exposé au délai d'Apache sur connexion muette (130 s) |
| 4 | le council : N couples (modèle, compétence), relecture anonymisée, synthèse — sur le motif de `prospect_agents` ; séquentiel en local | ✅ 2026-10-29 — **une COMPOSITION, pas un mode** (Fabien : « je ne veux pas juste un mode council figé » — multiplier les skills, ou des agents spécialisés appelables de 1 à n). Les **agents** sont des rôles du registre (`assistant_skills.DOMAINES` + `prompt_skills/assistant-<rôle>.md`) : en ajouter un = une entrée et un fichier. Deux premiers agents de réflexion : `critique` (contradicteur) et `methodology` ; déclarés `announced=False` — l'outil `delegate` les nomme, l'annonce du tour principal ne grossit pas (borne de 600 caractères, `tests_assistant_skills`), `charger_competence` les charge quand même. La **même question à 1..n agents** : `delegate(task, agents=[…])` (un domaine répété donne plusieurs modèles). La **façon de conclure** : `decide="vote"` sur `options` — décompte DÉTERMINISTE des lignes `VERDICT:` (`_tally`, le principe de `prospect_agents._consolider` : majorité stricte des voix exprimées, accord, abstentions ; une égalité se DIT) — ou `decide="synthesis"` — un **décideur** (`_synthesise`) sans aucun outil, qui lit les rapports ANONYMES et MÉLANGÉS, cite l'avis qui fonde chaque point et garde les désaccords visibles ; tiré au curseur « Qualité » HORS des modèles qui ont donné un avis (`_decider_lane`), la correspondance lettre → agent dans la trace — ou `decide="review"` : le **LLM Council de Karpathy** (`karpathy/llm-council`, référence donnée par Fabien, **lu dans son code** le 29/10 : le module `council` de son backend) — avant le décideur, chaque agent **classe** les avis anonymes sur son propre couloir, sans outil (`_peer_review`, format `CLASSEMENT FINAL:` comme son `FINAL RANKING:`), et le classement s'agrège en **rang moyen** (`_aggregate_rankings`, comme son `calculate_aggregate_rankings`). Trois écarts VOULUS : le rang qu'un agent donne à **sa** réponse ne compte pas (chez Karpathy, il compte) ; la lecture du classement retire doublons et lettres inconnues (là-bas, gardés) ; le décideur reçoit le **classement agrégé** et reste **anonyme** (là-bas, il lit les noms des modèles et pas l'agrégat). Une relecture est un appel sans outil, pas un sous-agent : elle ne compte pas dans le plafond. Le décideur compte dans le plafond, porté à **6** (cinq agents et lui). Au-delà des serveurs, les couloirs prennent un **autre modèle d'un serveur distant** (jamais un second local). Les sous-agents et le décideur appellent **en flux** : une requête muette est coupée vers 165-175 s chez ILaaS (mesuré, `WAMA_LLM` § ILaaS) — c'était la « limite temporelle » d'ILaaS. Garde `tests_delegation.CouncilTest`. **Éprouvé par l'assistant le jour même** (compte `fabien.moreau`, parent Albert `gpt-oss-120b`, tour sans persistance) : le modèle a composé seul `delegate(task, agents=[science, critique, methodology], decide="synthesis")` ; trois couloirs en même temps — Albert `gpt-oss-120b` 47,9 s, ILaaS `gemma-4-31b` 30,5 s, local `qwen3.8` **444,1 s** — ; décideur Albert `gemma-4-31b-it` (hors participants) 19 s ; réponse appuyée sur la décision. Rejoué en `decide="review"` : agents 25,9 s (Albert), 34,2 s (ILaaS), **738,8 s (local)** ; relectures 10,7 s, 2,7 s, **303,9 s (local)** ; décideur 40,4 s ; décision qui cite les avis (« [A, B, C] ») ; **tour de 1 176 s**. ⚠ **Tour de 550 s, puis de 1 176 s : le couloir LOCAL fait la durée du council.** L'échéance d'un sous-agent (300 s) arrête ses outils, pas l'appel en cours ni son dernier appel (180 s chacun). ⏳ À trancher : préférer les serveurs distants pour un council quand ils sont admis, ou une échéance plus courte pour le couloir local ; et faire remonter les étapes des sous-agents à l'écran (`§9` chantier 4) — l'utilisateur attend aujourd'hui sans rien voir |

**REA et Ghidra pour générer une app « depuis un projet GitHub ou une interface existante »
(2026-10-29, question de Fabien) — évalués, rien d'installé.** Ghidra (NSA, Apache-2.0) décompile
des BINAIRES : pour un dépôt GitHub, on a le source, et la chaîne « dépôt → app » (`ROUTE §10.5`,
rôles `librarian` → `app` → bac à sable) le lit directement — hors du besoin. REA (`morluto/rea`,
MIT, TypeScript, serveur MCP + CLI ; README lu le 29/10) fait de la rétro-ingénierie pour un
agent : binaires via Ghidra/IDA/Hopper, APK, Electron, et **sites web** par automatisation de
navigateur et captures HAR — c'est cette dernière partie qui toucherait « une interface web
existante ». Quatre réserves : ① **l'outillage de rétro-ingénierie est de la famille qui déclenche
SentinelOne sur ce poste** (vécu le 11/10 avec impacket) — rien à installer sans accord de la DSI ;
② la rétro-ingénierie d'un logiciel tiers pose une question de **droit et de conditions d'usage** ;
③ son API GitHub dit 405 869 étoiles pour un dépôt né le 14/04/2026, avec 1 535 abonnés (0,4 %,
contre 1 à 3 % pour un grand dépôt) — un indice d'étoiles gonflées, pas une preuve ; ④ il entrerait
comme **serveur MCP consommé** (le client MCP de `ROADMAP §8d` Ph3 étape 5), jamais comme une
librairie. ⭐ Pour OBSERVER une interface web existante, WAMA a déjà **Playwright** (smoke,
gestes filmés) : c'est par lui qu'on commencerait.

**Le parallèle, et comment se passe l'inférence (2026-10-29, question de Fabien).** Un modèle n'a
pas de mémoire d'un appel à l'autre : un sous-agent est une CONVERSATION de plus, envoyée à un
serveur qui garde les poids chargés — Claude Code ou Codex font ainsi N requêtes, le plus souvent au
même modèle. Un même serveur en sert plusieurs à la fois (traitement par lots) : les poids sont
chargés une fois, chaque conversation a son cache KV. D'où deux cas, à ne pas confondre :
- **plusieurs modèles locaux DIFFÉRENTS en même temps** : chacun ses poids sur les 24 Go — c'est ce
  qui coûte ;
- **plusieurs conversations sur le MÊME modèle local** : possible, au prix de la VRAM du cache KV
  (fenêtre × conversations). Côté WAMA rien ne les sérialise (`measured_load` ne prend aucun verrou,
  `model_registry.py:2776`) ; c'est le serveur Ollama qui décide, et l'hôte ne pose aucun
  `OLLAMA_NUM_PARALLEL` (relevé le 29/10 : seule `OLLAMA_MODELS` est posée) — son défaut, non
  mesuré.
⭐ Le parallèle le plus naturel est donc **un sous-agent par serveur** (local + souverains) : aucune
concurrence pour la carte, et pour le council des avis plus INDÉPENDANTS que N copies du même modèle.

**Ce qu'on ne prend pas, et pourquoi** : un runtime d'agent (§6) ; ~~des sous-agents locaux en
parallèle (un GPU, `resource_governor`)~~ — *trop large, corrigé le 29/10 : seuls des modèles
locaux différents en même temps coûtent, cf. ci-dessus* ; le résumé du rapport d'un sous-agent par un LLM (on
borne et on structure, on ne résume pas — vérification déterministe) ; Celery pour lancer un
sous-agent tant que le parent attend dans le même tour ; MCP `sampling` (déprécié).

**Mesuré avant l'étape 2 (2026-10-29) — le `timeout = 120` de gunicorn ne coupe pas un tour long.**
Un gunicorn jetable avec la configuration de production (`gunicorn_conf.py` exécuté tel quel ;
seuls le port, le démon, les journaux et le préchauffage neutralisés ; gunicorn 23.0.0) a servi
deux requêtes de 150 s — l'une **muette** jusqu'à la fin, l'autre écrivant toutes les 15 s comme le
flux SSE — : **200 toutes deux, aucun `WORKER TIMEOUT`**. En `gthread`, le délai porte sur le
battement du worker, que son fil principal tient pendant que la requête attend. *Contre-épreuve* :
la même requête muette avec un worker `sync` finit en `WORKER TIMEOUT` à 120 s (HTTP 500) — l'essai
voit donc une coupure quand il y en a une. ⚠ Avec `threads > 1`, gunicorn remplace `sync` par
`gthread` de lui-même : la contre-épreuve exige `threads = 1`.
Ce qui reste, et n'est **pas** mesuré :
- **Apache** (`C:/Apache24/conf/extra/wama-common.conf:23`, `ProxyPass … timeout=130`, et
  `ProxyTimeout 120` ligne 7) coupe une connexion restée **sans octet** ce temps-là. Le chat web
  en flux n'y est pas exposé (un commentaire SSE toutes les 15 s, `views.py:569-571`) ; le chat
  sans flux (repli, `views.py:326`) et l'API v1 (`api/v1/views.py:132`) le sont. La passerelle
  Discord appelle le moteur dans son processus (`gateway/core.py:226`), sans Apache ni gunicorn.
- **Les places** : 4 workers × 2 fils = 8 requêtes à la fois ; un tour avec sous-agents en tient
  une tout du long.

---

## 8. La méthode de veille — pour que ce document ne redevienne pas réactif

La promesse du 2026-08-20 (*passe trimestrielle et non réactive*) est restée lettre morte treize
mois, faute d'être écrite quelque part d'exécutable (§1, constat 3). Elle est écrite ici.

**Passe trimestrielle, trois gestes, une demi-journée :**

1. **Re-mesurer WAMA, pas relire ce document.** La table du §4 se refait avec les mêmes commandes
   (les lignes citées bougent) ; une case qu'on ne remesure pas devient un constat faux qu'on cite
   avec l'assurance de celui qui a lu la doc.
2. **Ne regarder que les axes, pas les produits.** Un produit nouveau n'entre au §3 que s'il apporte
   une capacité **qu'aucune ligne du §4 ne couvre**. Sinon il va au §3 en une ligne, ou nulle part.
3. **Dater et marquer.** Tout fait externe reçoit sa date ; un fait externe non daté est un fait
   faux en puissance (cas vécu : `wire_api`, et `sampling` déprécié trois semaines avant cette
   passe).

**Critère d'entrée d'une capacité dans les écarts (§5)** — les trois à la fois :
elle est **mesurable chez nous** (une ligne de code la contredit ou l'atteste) · elle sert le
**produit** (un labo qui pilote des apps média/IA), pas l'agent de code · elle **n'a pas déjà sa
brique** dans `common/` en attente d'adoption — auquel cas ce n'est pas un écart de harnais, c'est
un portage.

⚠ **Ce que la veille ne fait pas** : lire le code des produits. Le skill `/cartographie` est fait
pour ça et suppose un corpus **local** déclaré dans `wama-dev-ai/corpus.py` ; aucun de ces produits
n'en a un, et quatre sont fermés. Si un jour une décision dépend du **code** d'un harnais (et non
de sa doc), c'est une passe `/cartographie` à part entière, avec son corpus déclaré.

---

## 9. Le plan — cinq chantiers, dans cet ordre

> ⚠ **Réécrit le 2026-09-20** : la version du 19/09 était une table de six questions, jugée
> *« encore vaporeuse »* — à raison. Chaque chantier dit maintenant **quoi**, **où** (le fichier),
> **quel contrat**, **ce qui l'atteste**, et **de quoi il dépend**. Aucun n'est commencé : cette
> page reste un document de veille, pas un journal de travaux.
>
> **Le fil qui les ordonne** : on rend la boucle **correcte** (1), puis **sûre** (2), puis
> **mesurable** (3), puis **lisible** (4) ; la dette de configuration (5) n'attend personne.

### Chantier 1 — Borner le résultat d'outil, et réévaluer la bascule DANS la boucle *(écart 2)*

> ✅ **LIVRÉ le 2026-10-28 (`61e3e947`)** — premier palier du chantier « multi-agents » (§7.4).
> - **Budget : 24 000 caractères** (`TOOL_RESULT_CHARS`, décision de Fabien le 28/10), et non les
>   8 000 recommandés ci-dessous : 8 000 aurait coupé à chaque appel `read_web_page` (8 000 +
>   l'enveloppe), `read_doc` et `get_item_result` (20 000), qui se bornent déjà eux-mêmes, et
>   mieux. 24 000 = 20 000 + 20 % pour le JSON, la marge de Codex. Ce qui est coupé aujourd'hui :
>   `get_item_detail` d'une longue transcription et `list_user_files`, sans plafond.
> - **Forme** : un en-tête qui donne la taille d'origine, puis le début et les 4 000 derniers
>   caractères (`get_item_result` range `truncated`/`total_chars` en fin de dict). L'historique
>   garde sa coupe brute à 600.
> - **Où** : la seule ligne qui envoie un résultat au modèle, dans la boucle. **Pas** dans
>   `execute_tool` : l'API v1, MCP, le Studio, les actions programmées et le récit des fins de
>   tâche en ont besoin entier. La trace et l'étape diffusée gardent l'intégral.
> - **Bascule** : jugée après chaque résultat d'outil, seul ajout qui grossit le contexte. Coût
>   d'une itération ordinaire : une somme de longueurs ; la fenêtre est lue une fois par modèle
>   et par tour, la sélection ne tourne qu'au dépassement. Jamais vers une fenêtre plus petite.
> - **Atteste** : `tests_tool_result_budget` (9), contre-épreuves faites (borne retirée → 3
>   rouges ; coupe du seul début → 1 rouge).
> - **Reste** : la coupe intelligente À L'OUTIL de `get_item_detail` (second commit prévu
>   ci-dessous) ; un budget par modèle tiré du catalogue, comme Codex (plus tard).

| | |
|---|---|
| **quoi** | deux corrections au même endroit : (a) tout résultat d'outil est **borné** avant d'être réinjecté, et la troncature est **dite au modèle** (« 47 éléments, 5 montrés — rappelle l'outil avec un filtre ») plutôt que silencieuse ; (b) `_route_model_by_context` est appelé **à chaque itération**, pas une fois avant la boucle |
| **où** | `wama/common/services/assistant_engine.py` — l'injection `:730-734`, l'appel de bascule `:670`, la boucle `:696` |
| **contrat** | un budget de caractères **unique et déclaré** (pas un par appelant) ; la bordure produit un texte qui reste **actionnable** par le modèle ; la bascule ne redescend jamais de modèle en cours de tour (sinon le tour change de voix au milieu) |
| **atteste** | un test avec un faux outil rendant 200 ko : le message injecté tient dans le budget, contient la mention de troncature, et la fonction de bascule a été appelée **autant de fois que d'itérations** |
| **dépend de** | rien. C'est le seul chantier qui peut commencer aujourd'hui |
| **ne pas faire** | le déchargement vers fichier façon *deepagents* : il suppose un espace de travail par conversation, donc une décision de stockage. **Borner d'abord, décharger peut-être jamais** |

**Mesures du 2026-09-22 (base réelle, compte admin, lecture seule) — elles RÉDUISENT la justification
de départ, et c'est à savoir avant de commencer :**

- **Le débordement n'est PAS un problème aujourd'hui.** Fenêtres du parc installé : 262 144 jetons
  (`qwen3.6:35b`, `qwen3.8`, `qwen3.5:4b`, `gemma4:12b`) → budget calculé `context_length × 4 × 0,6`
  = **629 145 caractères** ; 131 072 pour `gemma4:e4b`. C'est un bug LATENT (petite fenêtre : cloud,
  futur modèle local), pas un incident.
- **Le coût réel est ailleurs** : `messages` s'accumule et **chaque itération renvoie tout le passé**
  (`_llm_call(messages…)` dans la boucle, ajouts juste après). Tailles mesurées d'un résultat
  d'outil : `get_item_detail` sur une transcription **61 642** et 26 442 caractères (médiane de tous
  les détails : **480**) ; `list_my_items` 14 429 ; `list_ai_models` 14 099 ; `list_registries` 5 980.
- **Cible précise** : les outils de LISTE se bornent déjà (`list_my_items` a `limite` 1-100 et rend
  `total`/`returned` ; `list_ai_models` a `limit=50`). Le non borné est le **détail d'un item**.

**Cinq choix — dont DEUX tranchés par Fabien le 2026-09-23** (*« on peut déjà faire appliqué au
local et au cloud, la trace d'audit garde le résultat complet »*) ; les trois autres restent
recommandés et attendent sa réponse :

| choix | recommandation | pourquoi |
|---|---|---|
| valeur et domicile du budget | **8 000 caractères**, une constante nommée dans `assistant_engine` | s'aligne sur la famille existante (`llm_utils` tronque à 8000 ×2, `read_web_page(max_chars=8000)`, `web_search.DEFAULT_MAX_CHARS=12_000`) |
| local seul ou cloud aussi | ✅ **TRANCHÉ 23/09 : les deux** | le cloud a de grandes fenêtres mais se paie au jeton — c'est là que la borne rapporte le plus |
| la trace garde-t-elle le résultat complet | ✅ **TRANCHÉ 23/09 : oui** — on borne ce qui part au MODÈLE, jamais `tool_steps` | c'est la trace d'audit et la matière du chantier 3 ; contrepartie : un tour peut stocker ~60 ko de JSON |
| borner aussi à l'outil | **oui, mais séparément** (deux commits) | la borne de boucle est un FILET pour tout outil futur ; `get_item_detail` mériterait une coupe intelligente (début + fin d'une transcription) |
| dernière itération | ne pas y toucher dans ce chantier — mais la fin de boucle rend `messages[-2]` (le texte du modèle, pas une réponse construite) : comportement surprenant, signalé | hors périmètre |

Tests prévus (dans `wama/common/tests/tests_assistant_surfaces.py`, qui a déjà l'idiome `mock.patch`) :
faux outil de 200 ko → le message injecté tient dans le budget ET dit qu'il est tronqué ; un résultat
de 480 caractères passe **octet pour octet** (contre-épreuve) ; sur un tour à 3 appels d'outil, la
bascule est appelée **3 fois**, en local et sur un chemin cloud. Ampleur : ~40 lignes, un fichier,
aucune migration, aucun changement de contrat de surface.

### Chantier 2 — La marque d'ÉCRITURE, et l'approbation qu'elle déclenche *(écart 1b)*

> 🔄 **LA MARQUE est livrée le 2026-10-28** (étape 0 bis du §7.4) ; **l'approbation ne l'est pas.**
> - Chaque outil déclare son **effet** sur sa fonction : `@tool_effect(READ | WRITE | DESTROY)`
>   (`tool_api.py`, bloc « EFFET d'un outil »). Trois effets et non un booléen « écrit » : c'est la
>   distinction que Codex calcule hors de l'outil et que MCP publie (`readOnlyHint`,
>   `destructiveHint`). Relevé du jour, à la lecture des corps : **2 destructions**
>   (`delete_item`, `clear_my_queue`), les ajouts, lancements, rangements et propositions en
>   écriture (`start_<app>` compris : une relance remplace un résultat, l'élément reste), le reste
>   en lecture.
> - **Le contrôle n'est pas l'AST seul** : un relevé du jour a montré que la moitié des écritures
>   passent par un autre module (`synthesize_text`, `run_studio_pipeline`, `add_file_to_rag`,
>   `search_models`…), invisibles à une analyse du corps. Donc `tests_tool_effects` refuse
>   **tout outil non marqué**, et l'AST n'est qu'un filet : une « lecture » qui écrit dans son
>   corps (ou dans une fonction du même fichier), ou qui POSTe la vue d'une app, rougit.
>   Contre-épreuve faite (marque retirée → l'outil est nommé ; `delete_item` déclaré lecture → rouge).
> - **Ce qu'elle porte déjà** : `sub_agent_tools()` (les lectures, moins trois exclusions dites :
>   `ask_claude_code`, `open_page`, `fold_side_panels`) et les annotations du serveur MCP.
> - **Reste** : l'action en attente et sa confirmation (le tableau ci-dessous, inchangé), et
>   `clear_my_queue(confirm)`, qui n'est pas une approbation (c'est le modèle qui remplit l'argument).

| | |
|---|---|
| **quoi** | un outil qui écrit le **déclare sur lui-même** ; la boucle, voyant la marque, **n'exécute pas** : elle rend une action *en attente* que la surface fait confirmer |
| **où** | déclaration : `wama/tool_api.py` (sur les fonctions `delete_item`, `duplicate_item`, `clear_my_queue`, `add_item_to_media_library`, `search_models`, `install_model`) · effet : la boucle d'`assistant_engine.py:707-734` · surfaces : `wama/views.py` (web) puis `gateway/` |
| **contrat** | ⚠ **surtout pas une table `TOOL_APPROVAL` à côté de `TOOL_APP_OVERRIDE`** — ce serait exactement la coexistence dénoncée à l'écart 5. La marque vit **sur la fonction** (un petit décorateur posant un attribut), donc un outil ne peut pas exister sans dire sa nature. L'action en attente vit dans le **cache** avec un jeton à usage unique et un TTL — même brique que la progression de file (`common/utils/task_progress.py`), donc **aucune migration** |
| **atteste** | ① un test qui appelle un verbe destructeur par la boucle et vérifie que **rien n'a bougé en base** tant que la confirmation n'est pas venue ; ② le jeton est **à usage unique** et refusé pour un autre utilisateur ; ③ un test **par AST** — sur le modèle de `tests_hf_cache_routing` — qui échoue si une fonction de `TOOL_REGISTRY` appelle `_poster_vue`/`_refus_app` **sans porter la marque**. C'est ce troisième qui empêche l'oubli : *une règle qui demande de s'en souvenir n'est pas un contrôle* |
| **dépend de** | rien techniquement, mais **passe après le chantier 1** : confirmer une action dans une boucle dont le contexte déborde, c'est faire approuver une décision prise à l'aveugle |
| **portée** | ⚠ ce chantier ne traite **que** le cas (b) — agir sur ses propres données. Le cas (a), ajouter une capacité, est **fermé aujourd'hui** par `min_tier='developpeur'` : voir la décision de gouvernance ci-dessous |

### Chantier 3 — Faire de la trace une MESURE *(écart 6 — et la graine de `RunOutcome`)*

| | |
|---|---|
| **quoi** | chaque étape d'outil gagne **deux champs** : a-t-elle abouti, et en combien de temps. Puis **un lecteur** : une commande qui agrège par outil (nombre d'appels, taux d'échec, durée médiane) |
| **où** | écriture `assistant_engine.py:727` et `common/services/conversation_store.py:79` · le champ `ConversationTurn.tool_steps` est un **JSON** (`models.py:1145`) donc **aucune migration** · lecteur : une commande de gestion, à côté de `check_docs`/`check_skills` |
| **contrat** | l'échec se lit **dans un champ**, jamais en réinterprétant le corps du résultat outil par outil. La trace est **par tour**, déjà scopée à l'utilisateur par la conversation — donc pas un nouveau stockage, pas une nouvelle question de rétention |
| **atteste** | un outil qui échoue produit une étape marquée comme telle ; la commande d'agrégat la compte ; un tour sans outil ne produit aucune étape |
| **dépend de** | rien. ⚠ Mais **c'est le chantier à ne pas repousser** : le signal non écrit ne se rattrape pas, et c'est la même brique (`RunOutcome`) qui bloque l'auto-amélioration depuis juillet **et** qui permettrait de mesurer le harnais lui-même (§1) |
| **frontière** | ce chantier s'arrête à l'assistant. Généraliser à toutes les apps est une **autre** décision (`RunOutcome` au sens large), à ne pas faire passer en contrebande |

### Chantier 4 — Les étapes en DIRECT *(écart 8)*

| | |
|---|---|
| **quoi** | pendant un tour, la surface montre ce qui se passe — « j'interroge la file », « je lis l'élément 12 » — au lieu d'un écran figé jusqu'à la réponse complète |
| **où** | publication depuis `assistant_engine.py` (à chaque étape) · lecture côté web dans le gabarit qui affiche le chat |
| **contrat** | ⚠ **pas de SSE inventé pour l'occasion** : WAMA a déjà une brique de progression que toutes les files utilisent (`publier_progression`/`progression_en_cours`, `common/utils/task_progress.py`) et un front qui sait l'interroger. Un tour d'assistant est une tâche comme une autre — **réutiliser**, sinon on aura deux mécaniques de progression, et c'est la faute que ce document reproche aux autres |
| **atteste** | un tour avec deux appels d'outil publie deux étapes **avant** la réponse finale ; la clé expire toute seule ; un tour sans outil ne publie rien |
| **dépend de** | le chantier 3 (les étapes portent déjà leur verdict et leur durée : autant les publier une fois enrichies) |
| **question ouverte** | le flux **token par token** est un autre sujet, plus coûteux (il change le contrat de réponse de toutes les surfaces). Les étapes suffisent probablement : ce qui est pénible n'est pas d'attendre, c'est d'attendre **sans savoir** |

### Chantier 5 — Une seule table de fournisseurs, et des délais déclarés *(écart 5)*

| | |
|---|---|
| **quoi** | ① `OPENAI_COMPATIBLE_PROVIDERS` **disparaît** au profit d'une dérivation (`protocol == 'openai'` sur `external_sources`) ; ② `CLOUD_DEFAULT_MODELS` devient un **champ du registre** (`default_model`) — ou, pour les 8 fournisseurs sans entrée, la reconnaissance qu'ils ne sont **pas joignables** ; ③ `timeout` et reprises deviennent **déclarés par fournisseur** |
| **où** | `wama/common/external_sources.py` (les champs) · `wama/common/utils/llm_utils.py:256-291` (les deux tables et la signature) |
| **contrat** | un fournisseur **existe** s'il est au registre, point. C'est ce qui referme au passage le trou nommé dans `WAMA_LLM.md:782` (un fournisseur non déclaré n'a **ni garde ni clé personnelle**, et reste atteignable par l'API v1) |
| **atteste** | `tests_llm_providers` gagne une assertion : **tout** fournisseur accepté par `llm_chat` a une entrée `external_sources`. Le test échoue aujourd'hui — c'est le but |
| **dépend de** | rien, mais **croise** `ROADMAP §8d Phase 3 étape 4` (registre des fournisseurs) : à faire **dans** ce chantier-là, pas à côté |
| **état (2026-10-07)** | ① ✅ fait (`llm_utils.openai_compatible_source`, garde `tests_llm_providers.OpenAICompatibleProvidersAreDerivedTest`) · ② 🔄 pour les fournisseurs DÉCLARÉS (`ExternalSource.default_model` : Albert, ILaaS, API Anthropic) — les 7 sans source restent dans `CLOUD_DEFAULT_MODELS` · ③ ⏳. Fait à l'arrivée d'ILaaS, 2ᵉ fournisseur OpenAI-compatible (`WAMA_LLM.md`) |
| **état (2026-10-11) — ✅ SOLDÉ** | ② ✅ les fournisseurs sans source sont RETIRÉS (`REMOVAL_LEDGER` R113) : `llm_chat` refuse tout nom hors registre avant l'appel (`llm_utils.declared_llm_source`) — c'est l'assertion « atteste » ci-dessus, `tests_llm_providers.ProvidersMustBeDeclaredTest`. Aucun n'était joignable : aucune clé configurée, ni `.env` ni `.env.example`. Au passage, la clé d'instance posée sur la page « Sources externes » sert désormais à TOUTE source déclarée sans utilisateur (l'API Anthropic l'ignorait). ③ ✅ en partie, et **par décision** pour le reste : la REPRISE sur limite de débit est déclarée par fournisseur quand elle est mesurée (`ExternalSource.rate_limit_wait_s`, Albert 60 s, garde `DeclaredRateLimitWaitTest`) ; le **DÉLAI reste celui de l'APPELANT** — un tour interactif borne à 180 s, une tâche n'en pose aucun et s'en remet à la durée max de son squelette (mesure du 2026-10-01 : la 1ʳᵉ génération réelle de l'Editor est tombée sur un délai recopié, cf. `chat_with_catalog_model`). Un délai par fournisseur contredirait cette règle sans qu'aucune mesure ne le demande. Le reste de la reprise (`Retry-After`) est déjà dit par le fournisseur à chaque réponse |

### Ce qui n'est PAS un chantier — quatre questions et leur déclencheur

| question | on l'ouvre quand… |
|---|---|
| **sous-agents** *(écart 3)* | le prompt système devient le poste de coût dominant, **ou** un domaine a besoin d'outils que les autres ne doivent pas voir. Pas avant les chantiers 1 et 2 : un sous-agent qui peut détruire sans confirmation aggrave le problème au lieu de le borner. ⭐ **OUVERT le 2026-10-28** (Fabien) — socle du **council** et des autres fonctionnements multi-agents. ⚠ **Et le premier déclencheur est ATTEINT, mesuré le jour même** (203 tours réels, lecture seule) : le prompt système FIXE pèse **24 676 caractères (~6 200 jetons, 90 outils)**, contre ~11 700 pour un historique de 10 échanges médians, ~400 pour les résultats d'outils d'un tour médian (1 outil, 363 car.) et 73 pour le message — **environ les deux tiers de chaque appel**, renvoyés à chaque itération. Ce qui a été traité le 22/09 est son CALCUL en local (le fixe en tête, réutilisé par le cache KV d'Ollama), pas son POIDS : il occupe la fenêtre, et sur le cloud il se paie entier à chaque appel (aucun `cache_control`, écart 9). *J'avais d'abord écrit « sans attendre le déclencheur » sans l'avoir mesuré — Fabien a demandé de confronter au code.* Condition retenue : chantier 1 ✅ + la **marque** d'écriture du chantier 2 (sa moitié déclarative), avec des sous-agents en **lecture seule** ; l'approbation reste due avant d'ouvrir l'écriture à un sous-agent. Plan : §7.4 |
| **annulation** *(écart 7)* | le chantier 2 est livré et une confirmation se révèle insuffisante en usage réel. Tant qu'on confirme avant, annuler après est un confort |
| **cache de prompt** *(écart 9)* | l'usage cloud devient régulier (aujourd'hui il est explicite et rare). Chiffrer d'abord, câbler ensuite |
| **MCP `resources`** *(écart 10)* | après le client MCP (`§8d Ph3 étape 5`) : on saura ce qu'on consomme avant de décider ce qu'on offre. ⚠ Et ne rien bâtir sur `sampling`, **déprécié** |

### Deux décisions qui ne sont pas des chantiers

- **Gouvernance de l'ajout de capacité** *(écart 1a — position de Fabien, 2026-09-20)* : l'entrée
  d'un modèle, d'une librairie ou d'une app est aujourd'hui réservée aux développeurs par
  `min_tier`, **en base**. La règle posée : *le jour où on l'ouvre à un utilisateur, il faut une
  approbation.* Donc l'approbation n'est pas un projet à planifier — c'est une **condition
  d'ouverture**, à construire **dans** la première surface qui ouvrira, et une raison de plus de
  livrer le chantier 2 avant d'en avoir besoin. ⚠ À écrire aussi là où la décision d'ouvrir se
  prendra : `PROFILES_PERMISSIONS.md`, pas seulement ici.
- **Résidu du déplacement** *(§7.1)* : re-domicilier les ~60 lignes de l'ex-`ROADMAP §16.7` qui
  parlent des registres et des librairies de WAMA, non d'Hermes. Passe dédiée, jamais en même
  temps qu'autre chose — *un déplacement qui trie n'est plus un déplacement.*

## 10. Journal

| date | ce qui a été fait |
|---|---|
| **2026-10-29** | **Étape 1 du §7.4 livrée — le socle des sous-agents** : un sous-agent est un tour de LA boucle avec des bornes (outils permis, itérations, échéance, profondeur), défauts inchangés, lecture seule tenue par le moteur dès la profondeur 1. Usage visé par Fabien consigné au §7.4 (travaux menés ensemble, réflexion de recherche, bibliographie) avec son manque mesuré : aucune source savante parmi les outils. Puis le parallèle par serveur décidé (étape 2 bis), le `timeout` de gunicorn **mesuré** inoffensif en `gthread`, et les **étapes 2 et 3** livrées (le verbe `delegate`, l'interrupteur « Sous-agents ») — avec un trou de l'étape 1 fermé : un tour borné passait par l'abonnement, dont la boucle MCP ignore les bornes. Puis l'**étape 2 bis** : la vague parallèle, un couloir par serveur, mesurée sur Albert, ILaaS et le local. Puis l'**étape 4**, le council comme COMPOSITION (agents du registre de 1 à n, vote, décideur, ou relecture croisée puis décideur — le LLM Council de Karpathy, lu dans son code) ; REA et Ghidra évalués, rien d'installé ; la « limite temporelle » d'ILaaS mesurée : une requête muette coupée vers 165-175 s, un flux tient — les sous-agents appellent donc en flux. |
| **2026-10-28** | **Multi-agents ouvert par Fabien** (socle du council) — et le déclencheur « prompt système = poste de coût dominant » **mesuré atteint** le même jour (24 676 car. fixes, 90 outils, ~2/3 de chaque appel ; détail au §9). Cinq recherches lancées depuis l'assistant (Codex et OpenCode **lus dans leur code**, synthèse) consignées en **§7.4** — leurs journaux ne sont pas versionnés. **Chantier 1 livré** (`61e3e947`) : borne à 24 000 (et non 8 000, qui coupait les outils déjà bornés), bascule jugée après chaque résultat. Constats périmés corrigés : « 5 tours » (8 depuis le 05/10), ligne OpenCode de §3.1 (serveur HTTP, sous-agents, Plan n'est pas une lecture seule), `untrusted` retiré chez Codex. ⚠ *Les deux rapports de veille proposaient l'un une table d'approbation en base, l'autre Celery pour les sous-agents : le §9 avait déjà tranché le premier (cache, sans migration), et la mesure écarte le second (le parent attend, un seul GPU). Un rapport de veille se confronte à la route comme le reste.* |
| **2026-09-30** | **AnythingLLM évalué** (demande de Fabien) : rejeté comme composant et comme UI (`ROADMAP §16.2`), compatible comme client MCP de WAMA sans rien écrire ; une piste ajoutée à l'écart 3 (présélection d'outils). ⚠ Ma première réponse confondait le niveau `project` du RAG avec un « sac de documents » : `Project` est le **projet de recherche** inter-établissements (`common/models.py:353`), et le « sac » n'ajoutait rien au RAG par niveaux — corrigé avant consignation. |
| **2026-09-20** | **Deux constats de la veille CORRIGÉS par la mesure, tous deux relevés par Fabien.** ① *« l'assistant détruit sans approbation »* mélangeait deux questions : **ajouter une capacité** est **déjà fermé** (`install_model` gardé `model_manager`, `AppAccessPolicy.min_tier='developpeur'`, relevé en base — 4 apps sur 19 portent ce palier), seul **agir sur ses propres données** reste sans confirmation. La règle posée en échange : *le jour où on ouvre l'ajout de capacité à un utilisateur, il faut une approbation* — et ce qui garde aujourd'hui est **une ligne en base**, donc à un clic d'admin. ② L'écart « historique » était **déjà refermé** : les trois surfaces passent par `conversation_turn` et le `localStorage` est effacé — je l'avais écrit en citant la **table §A de `WAMA_LLM` (15/09)** au lieu d'ouvrir le code, ce que la doctrine interdit explicitement. ③ Précision de vocabulaire : **l'assistant est commun et inter-mondes**, `home.html` n'est qu'une surface. ④ Les codes `E1`/`D1` deviennent **Écart N / Décision N** (illisibles autrement). ⑤ Le §9, jugé *« vaporeux »*, devient **cinq chantiers explicites** (quoi / où / contrat / ce qui l'atteste / dépendances) + quatre questions avec leur déclencheur. ⚠ *Deuxième fois dans la même passe qu'une source datée me fait écrire un constat faux : une passe de veille doit ouvrir le code, même quand une doc récente semble répondre.* |
| **2026-09-19** | **Création.** Cartographie de 20+ produits (12 ouverts, 4 fermés, 5 frameworks, 4 standards) sur **14 axes** issus d'une taxonomie de 13 harnais lus dans leur code. État WAMA **mesuré ligne à ligne** le jour même (71 outils, 15 registres, 11 skills de prompt). **6 écarts réels** retenus (écart 1, écart 2, écart 3, écart 5, écart 6, écart 8-écart 10), **3 axes où WAMA est en avance**, **7 frontières voulues** consignées comme réponses. Hermes **déplacé mot pour mot** depuis `ROADMAP §16.7` ; **Cordis consigné pour la première fois** (décision du 2026-08-20 qui ne vivait qu'en mémoire d'agent). Deux affirmations externes reçues **corrigées par la mesure** : `wire_api` n'a plus qu'une valeur, et `sampling` MCP est **déprécié**. 6 décisions ouvertes (décision 1-décision 6). |
