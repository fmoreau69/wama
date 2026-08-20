# WAMA_MEMORY.md — Mémoire & RAG : référence unique du domaine

> **Statut : DÉCIDÉ, NON CONSTRUIT** (2026-08-20). Ce document fixe l'architecture ; aucune ligne
> de `wama/common/memory/` n'existe encore. Il remplace, pour ce domaine, les intentions
> dispersées dans `PROJECT_STATUS §6`, `ROADMAP §16.2/§16.7` et `docs/WAMA_Vision_Complet_v2 §11`
> — qui restent valables sur le *pourquoi* mais sont **périmés sur le substrat** (ils disent
> ChromaDB, voir §7).

---

## 1. Le besoin, en trois usages qui n'en font qu'un

| Usage | Qui produit | Exemple |
|---|---|---|
| **Auto-amélioration** — wama-dev-ai se souvient d'une session à l'autre | wama-dev-ai | « le backend Qwen3-ASR casse à l'import, piste = conflit deps » |
| **Assistant IA** — l'assistant connaît l'utilisateur et son contexte | assistant (`tool_api.py`) | « Fabien travaille en FR, exporte toujours en PDF » |
| **Mémoire de travail utilisateur** — WAMA se souvient de ce que l'utilisateur y a fait | runtime WAMA | « la transcription du 12/08 a été corrigée à la main puis exportée » |
| **RAG** — retrouver un fragment d'un document possédé | indexation médiathèque / corpus | « que dit le protocole d'expérimentation sur les sections ? » |

Ces quatre usages n'ont **qu'un seul mécanisme** : *retrouver le bon morceau de texte, pour le bon
utilisateur, au bon moment*. Ils diffèrent par la **provenance** et le **cycle de vie**, pas par la
technique. D'où : **une brique, `wama/common/memory/`** — pas un module RAG + un module mémoire.

## 2. Le point qui décide tout : WAMA possède déjà la gouvernance

`OrgUnit` + `Project` + `ScopedVisibility` + `scoped_visible_q()` (`common/models.py:74-219`)
implémentent **déjà** la hiérarchie université → labo/service → équipe → utilisateur, plus un scope
`project` qui traverse les organisations. Le docstring d'`OrgUnit` le dit : « COLONNE VERTÉBRALE
unique : sert **l'héritage RAG**, les scopes de partage ET le gating d'accès. »

Conséquence directe : **un rappel mémoire est une queryset Django avec `scoped_visible_q(user)`
appliqué.** La hiérarchie RAG de la vision §11 n'est pas à construire — elle est héritée d'un
mixin. C'est la raison n°1 de ne pas adopter un framework tiers : aucun ne connaît ce modèle, et
l'adopter reviendrait à monter **un second modèle de scope à côté du vrai**.

Corollaire de séquencement : la vision §11 imposait « RAG utilisateur d'abord, extension aux
niveaux org **seulement si** la valeur est démontrée ». Cette prudence portait sur le coût de
*construire* la hiérarchie. Ce coût est nul ici. La prudence se déplace donc sur l'**usage**
(n'indexer au niveau labo que ce qu'un humain y a explicitement mis), pas sur le schéma.

## 3. Deux natures, un substrat — et pourquoi deux tables

| | **Souvenir** (`MemoryItem`) | **Fragment** (`RagChunk`) |
|---|---|---|
| Est | un fait, un événement, une procédure | un morceau d'un document source |
| Re-dérivable ? | **NON** — perdu = perdu | **OUI** — on réindexe la source |
| Purge automatique | **INTERDITE** | normale (réindexation) |
| Fenêtre de validité | oui (`valid_from`/`valid_to`) | non (le document fait foi) |

**Pourquoi deux tables et pas un discriminateur.** Leurs cycles de vie sont opposés : l'un se
reconstruit, l'autre jamais. Le 2026-08-19, une purge ciblée de candidats de prospection a
**détruit 13 évaluations LLM** parce que deux natures cohabitaient dans la même table (GPU dépensé
pour rien ; garde posée aux 3 purges). Séparer physiquement rend l'accident **impossible**, pas
seulement improbable. Elles partagent un mixin abstrait `Embedded` et **une seule** fonction
`recall()`.

## 4. Modèle de données

> **Où vivent les modèles** : dans **`wama/common/models.py`**, pas dans la brique — même
> précédent que `RunOutcome` (modèle dans `models.py`, logique dans `common/services/`). Les
> loger dans `common/memory/` imposerait un import circulaire avec `ScopedVisibility` sans rien
> gagner. La brique `common/memory/` ne porte que la logique.

```python
# wama/common/models.py  (à la suite de RunOutcome)

class Embedded(models.Model):            # ABSTRAIT — le socle vectoriel commun
    content          = TextField()       # VERBATIM. Jamais résumé, jamais paraphrasé à l'écriture.
    content_hash     = CharField(64, db_index=True)      # dédup exacte, avant tout appel LLM
    embedding        = VectorField(dimensions=1024, null=True)   # pgvector
    embedding_model  = CharField(64)     # 'bge-m3' — un changement de modèle = réindex, pas une
                                         # corruption silencieuse (espaces vectoriels différents)
    created_at, updated_at
    class Meta: abstract = True

class MemoryItem(Embedded, ScopedVisibility):            # LE SOUVENIR
    kind        = 'semantic' | 'episodic' | 'procedural'   # ('emotional' RÉSERVÉ, cf. §8)
    user        = FK(auth.User, null=True)               # à qui appartient le souvenir
    subject     = CharField(128, db_index=True)          # de quoi ça parle (app, model_key, thème)
    source_app, source_object_type, source_object_id     # d'où il vient (projection §5)
    provenance  = 'projection' | 'assistant' | 'dev-ai' | 'human'   # OBLIGATOIRE
    confidence  = Float(null=True)       # None pour un fait mécanique — pas de faux chiffre
    valid_from, valid_to                 # périmé => on INVALIDE, on n'écrase jamais
    superseded_by = FK('self', null=True)   # merge : on chaîne, on ne détruit pas
    approved_at, approved_by             # HITL — None = invisible au rappel (§6)
    salience    = Float(default=0.0)     # dérivé de RunOutcome, RECALCULABLE (§8)

class RagChunk(Embedded, ScopedVisibility):              # LE FRAGMENT
    source_kind = 'media' | 'manifest' | 'corpus' | 'doc'
    source_id, source_ref                # identifiant + chemin/URL + offset
    ordinal                              # position dans la source (restitution du contexte)
    indexed_at
```

⚠ **Piège connu — visibilité dénormalisée.** La visibilité d'un `RagChunk` est une **copie** de
celle de sa source (jointure à la volée impossible : les sources sont hétérogènes). Elle doit donc
être rafraîchie quand la source change de visibilité, sinon un fragment reste partagé après que le
média a été repassé en privé. Un signal sur le changement de `visibility` de la source est
**obligatoire**, pas optionnel.

## 5. Les cinq opérations

Vocabulaire emprunté à **memorywire** (arXiv 2606.01138) : c'est le seul travail sérieux de
normalisation du domaine (5 opérations × 4 types, interface `MemoryStore`, canal HITL). On en prend
**la forme du contrat, pas la dépendance** — v0.4 par un chercheur isolé, qui se réserve de casser
le format jusqu'en v0.5. Adopter la forme rend un adaptateur externe possible plus tard sans rien
réécrire ; adopter le paquet nous accrocherait à un format instable.

```python
remember(content, *, kind, user, scope, provenance, embed=True, ...) -> MemoryItem
recall(query, *, user, kinds=None, k=8, include_rag=True, semantic=True) -> list[Hit]
forget(item, *, reason, hard=False)   # DÉFAUT = invalidation (valid_to). hard=True réservé au RGPD.
merge(items)                          # PROPOSE une fusion. N'applique JAMAIS.
expire()                              # applique les TTL déclarés. N'atteint jamais un item approuvé.

reindex(*, lot=64, modeles_obsoletes=False)   # ENTRETIEN, pas une 6e opération du contrat
```

### 5bis. Écrire n'est PAS vectoriser — discipline GPU (incident 2026-08-20)

**Ce qui s'est passé.** Le smoke du jalon 3 a lancé une quinzaine d'appels d'embedding sur l'Ollama
de l'hôte, parce que `remember()` vectorisait **obligatoirement** à l'écriture. L'hôte Windows a
crashé pendant la séance. La causalité n'est pas établie — la piste retenue reste une instabilité
sous l'OS, et la datation se fait sur hwlog, pas sur l'event 6008 — mais ces appels tombaient dans
la catégorie que la règle d'exploitation interdit (chargements Ollama enchaînés hors action
explicite de l'utilisateur). Un smoke ne doit jamais charger un modèle sur la machine de quelqu'un.

**La correction n'est pas une précaution, c'est une meilleure conception.** Écrire et vectoriser
sont deux gestes distincts : le premier ne doit jamais échouer ni attendre, le second peut se faire
plus tard et **par lot**. Trois points, portés par le code et non par la vigilance :

1. **`remember(..., embed=False)`** écrit sans toucher au GPU (`embedding=NULL`). Obligatoire pour
   la projection en masse (jalon 4 : un appel Ollama par `RunOutcome` serait absurde là où un lot
   en fait un seul), pour les tests, et quand le GPU est occupé.
2. **`recall(..., semantic=False)`** rappelle en lexical seul, sans embarquer la requête.
3. **`reindex()`** est le complément OBLIGATOIRE du point 1 : sans lui, une écriture sans vecteur
   resterait introuvable en sémantique pour toujours. C'est **le seul endroit** où la mémoire
   sollicite le GPU en volume — à déclencher explicitement, jamais dans une requête utilisateur.
   `modeles_obsoletes=True` reprend aussi les lignes vectorisées par un autre modèle : c'est ce
   qui rend une bascule d'embedder possible sans corrompre la colonne.

S'y ajoute **`keep_alive='0'`** sur chaque appel d'embedding (`embed.py`) — le modèle est déchargé
aussitôt au lieu de résider 5 minutes (défaut Ollama). Sans ça, une série d'écritures laisse
`bge-m3` squatter la VRAM entre deux appels, en concurrence avec un traitement utilisateur. C'est
le motif que `llm_utils.ollama_chat` documentait déjà ; il n'avait pas été repris.

**`recall()` est hybride, fusionné par RRF** (Reciprocal Rank Fusion) : recherche vectorielle
pgvector (cosinus) + recherche lexicale Postgres full-text FR. Pas de max ni de somme pondérée —
l'évaluation memorywire montre que RRF tient recall@5 = 1.000 sous injection adverse en rang 0, là
où la fusion `max` s'effondre à 0.500 avec 80 % de fuite dès K ≥ 5. Le lexical n'est pas un luxe :
il rattrape les identifiants exacts (`model_key`, nom de fichier, code projet) que le vectoriel rate.

## 6. Gouvernance de l'écriture

1. **Tout écrit issu d'un LLM arrive non approuvé** (`approved_at=None`) et est **invisible au
   rappel**. Mesure vécue : sur les 6 audits wama-dev-ai du 17/07, les affirmations d'absence
   étaient fausses **4 fois sur 6**. Une mémoire qui gobe ces sorties se corrompt en une nuit.
2. **`provenance` est obligatoire.** C'est le levier le plus efficace pour récupérer un magasin
   empoisonné : on invalide par provenance, pas item par item.
3. **Seules les projections mécaniques (§7) s'auto-approuvent** — elles ne font que pointer un fait
   déjà en base, sans inférence.
4. **Aucune purge automatique n'atteint un `MemoryItem`.** Règle directe du 19/08 ; `expire()` ne
   travaille que sur du non-approuvé et du `RagChunk`.
5. **`merge()` propose, l'humain valide** — doctrine « propose-cite-tu-valides » (ROADMAP §16.1).

## 7. Producteurs, consommateurs, substrat

```
PRODUCTEURS                       wama/common/memory/                CONSOMMATEURS
                                  │  (modèles dans common/models.py)
wama-dev-ai        ─┐             ├─ store.py    les 5 opérations        ┌─ prompt_pipeline « Hook B »
 (procédural/       │             ├─ embed.py    bge-m3 via Ollama       │   (déjà présent, no-op)
  sémantique dev)   ├───────────► ├─ project.py  projections read-only  ─┤─ tool_api.py (assistant)
assistant IA        │             └─ index.py    indexation RAG          │─ wama-dev-ai (remplace
 (épisodique)       │                                                    │   memory.json)
runtime WAMA       ─┘   ⚠ RunOutcome / items de file / Manifest ne sont   └─ UI « ce que j'ai fait »
 (via projection)          PAS RECOPIÉS : `project.py` les INDEXE en place.
```

**La mémoire de travail utilisateur est une projection, pas une copie.** `RunOutcome`
(`common/models.py:475`) est déjà le journal append-only des gestes réels — produit, échec,
téléchargé, corrigé, relancé, supprimé — avec `app`, `object_type/id`, `user`, `model_keys`. Il
reste **la source de vérité** ; `project.py` n'y ajoute qu'un texte rappelable et un vecteur.
Recopier ces faits créerait deux vérités qui divergent — exactement la maladie déjà diagnostiquée
sur les `.md`.

**Substrat : Postgres + pgvector.** Posé le 2026-08-20 : Postgres 16.10 (WSL2), client Python
`pgvector.django` ✅, extension serveur `vector` 0.6.0 installée et activée sur `wama_db` ✅
(`sudo apt-get install -y postgresql-16-pgvector` + `CREATE EXTENSION vector;` en superuser —
`wama_user` ne suffit pas ; paquet dans noble/universe, proxy UGE déjà configuré dans apt).

> ⚠ **PIÈGE — l'extension ne peut PAS reposer sur la migration.** `.gitignore:13` exclut
> `**/migrations/0*.py` : les migrations numérotées ne sont **pas versionnées**. Celle qui porte
> `VectorExtension()` est donc régénérée par `makemigrations` sur une base neuve — et
> `makemigrations` ne devine pas les extensions Postgres. `migrate` échouerait alors sur
> `type "vector" does not exist`, sans que rien n'indique pourquoi. Le `CREATE EXTENSION` est donc
> posé **dans les scripts de démarrage**, avant `migrate` (`start_wama_prod.sh` §PostgreSQL et
> `start_wama_dev.sh`) — seul endroit versionné qui précède la migration. Idempotent.

> **Correction d'un plan périmé.** `PROJECT_STATUS §6`, `prompt_pipeline.py:116-118` et la vision
> §11 annoncent **ChromaDB**. C'est abandonné, et pas par goût : un store séparé (a) ne peut pas
> être filtré par `scoped_visible_q()` — la gouvernance devrait être ré-implémentée en filtres de
> métadonnées, sans jointure possible ; (b) ajoute une 2ᵉ surface d'état à sauvegarder, hors du
> périmètre `mirror_sync`/backup ; (c) contredit `ROADMAP §16.2`, qui avait **déjà adopté pgvector**
> (« RAG dans Postgres existant »). C'est ROADMAP qui avait raison ; les trois autres n'ont pas suivi.

**Embeddings : `bge-m3`** (1024 dims, multilingue) via Ollama — pas `nomic-embed-text`, anglo-centré
(quick-win déjà identifié ROADMAP §16.1 ; le corpus Lescot est en français). `embedding_model` est
stocké par ligne : une bascule de modèle devient un réindex explicite, jamais une corruption
silencieuse. Index HNSW (dispo depuis pgvector 0.5 ; plafond 2000 dims, 1024 passe).

## 7bis. ⚠ LE VRAI GOULOT : `RunOutcome` est quasi vide (mesuré 2026-08-20)

La projection (jalon 4) fonctionne et est validée — mais **elle n'a presque rien à projeter**.
Mesure du jour :

- **1 seule ligne** dans `RunOutcome` sur toute la base (`converter` / `produit`, 18/08) ;
- **2 points de captation** dans tout le code : `common/utils/task_skeleton.py:94-95` (générique,
  `produit`/`echec`) et `transcriber/views.py:852` (`corrige`) ;
- **aucun** appelant pour `telecharge`, `relance`, `supprime` — donc **la moitié du vocabulaire de
  signaux n'est jamais écrite**, et ce sont précisément ceux qui portent la saillance.

Conséquence à ne pas se cacher : **la mémoire de travail utilisateur est bloquée sur l'adoption de
`RunOutcome`, pas sur la brique mémoire.** Le chemin est complet de bout en bout, il est alimenté
par un filet d'eau. C'est le même diagnostic que la boucle qualité, « bloquée sur les DONNÉES ».

Et c'est urgent au sens propre, pour la raison écrite dans le docstring de `RunOutcome` :
**aucun framework ne récupérera ces signaux rétroactivement.** Chaque téléchargement, chaque
correction, chaque suppression qui se produit aujourd'hui sans être captée est définitivement
perdue. Le coût d'attendre n'est pas nul, il est cumulatif.

### Résolu le 2026-08-20 — captation générique, zéro ligne dans les apps

Le réflexe aurait été de câbler `enregistrer()` à la main dans les vues `download`/`delete`/`start`
des 10 apps : **~30 retouches**, à refaire à chaque app ajoutée, et une app oubliée aurait creusé
un trou **silencieux** dans le journal.

Or les routes de file sont d'une régularité remarquable (vérifié sur les 10 apps) : `download`,
`start`, `restart`, `delete`, toutes avec un `pk`. D'où **`common/middleware.py`
(`RunOutcomeCaptureMiddleware`)** : il lit `resolver_match.url_name`, retrouve le modèle via
`detail_registry`, et écrit le signal. Les apps futures sont captées sans qu'on y touche.

Trois choix qui font la justesse de la captation :

1. **Middleware, pas signal `post_delete`.** Un signal capterait aussi les suppressions en cascade
   et les purges de maintenance — or `RunOutcome` enregistre des **gestes d'utilisateur**. Passer
   par la requête HTTP rend la captation juste par construction : pas de requête, pas de geste.
2. **`url_name`, pas la forme du chemin.** Les chemins varient (`/converter/<pk>/download/`), les
   noms de route non. La captation est donc insensible à la disposition des URL.
3. **Seules les réponses < 400 comptent.** Un 404 n'est pas un téléchargement.

Et une distinction qui pèse dans la saillance : un `start` n'est une **relance** que si l'objet a
déjà produit ou échoué. Sans ce test, une première exécution serait comptée comme l'échec implicite
d'un précédent qui n'existait pas.

⚠ Restent non captés : les routes `*_all` (batch), qui n'ont pas de `pk` — les capter demanderait
de rejouer la sélection côté serveur. À faire quand le besoin sera réel, pas en le devinant.

## 9bis. Le journal de l'utilisateur — première surface visible

`/common/journal/` (menu utilisateur → « Mon journal ») : tout ce que l'utilisateur a lancé, toutes
apps confondues, du plus récent au plus ancien.

**Il DÉRIVE, il ne stocke rien** — même principe que le catalogue des licences. Les sources sont
tirées de `detail_registry`, que chaque app alimente **déjà** pour l'inspecteur : une app présente
dans l'inspecteur est au journal le jour où elle est écrite, **sans une ligne de code dans l'app**.
Le champ de date est détecté (`created_at`, sinon `uploaded_at`…), les chips viennent de
`card_chips` (générés du schéma params), le titre est le `__str__` du modèle — un titre médiocre
est un défaut de `__str__` à corriger dans le modèle, où il profitera aussi à l'admin.

**Mondes.** Seul `media` est peuplé, mais l'ajout d'un monde (studio, lab, data) est une
**inscription** (`journal.enregistrer_source()`), jamais une modification de la page.

**Le clic ne réinvente pas de volet** : il pose `sessionStorage['wama_focus_card']` puis navigue
vers la page de l'app — passage inter-pages que `wama-queue.js` documente lui-même, et le sélecteur
`[data-id]` fonctionne sur les 14 gabarits de cards d'items (vérifié). L'utilisateur atterrit sur sa
card, mise en évidence, avec **toutes** les actions de l'app.

> ⚠ **ERREUR CORRIGÉE LE MÊME JOUR — `/common/detail/<app>/<pk>/` EST porteur.** J'avais écrit
> ici qu'il n'avait « aucun consommateur ». C'est FAUX : `wama-inspector.js::fillDetail()` (l.328)
> le **fetch** pour remplir la section « Infos » du volet droit. Il est invisible à toute recherche
> du chemin parce qu'il ne le nomme jamais — il dérive l'URL de `data-preview-url` par
> `replace('/preview/', '/detail/')`. **Ne pas le retirer, ne pas le reclasser en endpoint d'API
> seule, ne pas changer son contrat sans passer par l'inspecteur.**
>
> Méthode qui a manqué (et qui est déjà une règle acquise) : **tracer le chaînage d'exécution**
> plutôt que grepper un littéral. Une URL construite par concaténation ou substitution
> n'apparaît dans AUCUNE recherche de son chemin — c'est le mode de défaillance normal du grep,
> pas une exception. Chercher le consommateur par ce qu'il FAIT (`fetch(`, `replace('/preview/`)
> et non par ce qu'on croit qu'il écrit.

**La card du journal HÉRITE des trois designs communs.** Elle émet les **5 sections nommées** de
la card v3 (`CARD_DESIGN §11.6`) — Entrée · Réglages · Sortie · État · Actions — et le conteneur
porte `data-card-design` (densité choisie au profil, diffusée par le context processor). Les trois
densités **v1 détaillé · v2 compact · v3 affiné** sont trois blocs CSS de `wama-card-v3.css` : le
journal les obtient sans une ligne de style propre, et respecte le choix de l'utilisateur comme
les 10 apps. Vérifié au rendu : 25 cards × 5 sections, `data-card-design="v3"`, **aucun
`{% templatetag openblock %} if design {% templatetag closeblock %}`** — le garde-fou de §11.4 tient (la différence entre densités est un
`display`, jamais un branchement de gabarit).

> ⚠ **Correction d'une erreur de ce document (2026-08-20).** Une version antérieure de ce §
> affirmait qu'« il n'existe pas de card commune, chaque app écrit la sienne ». **C'est faux** :
> ce que chaque app écrit est l'ÉMISSION des 5 sections ; le design, lui, est commun et
> sélectionnable. La confusion venait d'avoir listé les gabarits `_*_card.html` sans lire
> `CARD_DESIGN §11.4/§11.6`. Le « TROU DE GLU » de `converter_01/_generic_card.html` concerne la
> **codegen** (elle ne génère pas encore la card réelle), pas l'absence d'une card commune.

**Performance** : une page de 25 coûte ~31 requêtes (12 sources × count+select, plus les chips de
la page). Le tri inter-modèles se fait en Python — une union SQL sur 12 tables hétérogènes se
casserait à la première app ajoutée, exactement ce qu'on veut éviter. ⚠ Les entrées sont fabriquées
**après** le tri et la tranche : les fabriquer avant coûtait 73 requêtes pour 20 lignes.

## 9ter. tool_api — la lecture est générique, l'écriture ne l'est pas (proposition, non construit)

**Constat.** `wama/tool_api.py` (2746 l., ~46 outils) suit une **triade par app** :
`add_to_<app>` · `start_<app>` · `get_<app>_status`. Les deux premiers sont irréductiblement
spécifiques — les paramètres d'une transcription ne sont pas ceux d'une génération d'image. Le
troisième, non : `get_transcriber_status` (l.1459) est une projection maison des 10 derniers items
avec ses **propres noms de clés** (`filename`, `duration_display`, `used_backend`, `text_preview`),
et chacune des 10 apps a son équivalent avec des clés **différentes**. L'assistant doit donc
apprendre 10 vocabulaires pour lire la même chose : l'état d'un item.

**Proposition — deux outils génériques remplacent les ~10 `get_*_status`** :

| Outil | Adossé à | Ce que ça donne |
|---|---|---|
| `list_my_items(app=None, limite=25)` | `services/journal.entrees()` | La liste transversale existe déjà : dérivée de `detail_registry`, scopée à l'utilisateur, toutes apps. |
| `get_item_detail(app, pk)` | l'adapter de `detail_registry` | Le schéma **canonique** — celui de l'inspecteur. |

**Pourquoi c'est solide plutôt qu'une 4ᵉ surface** : ce contrat a déjà **deux consommateurs
éprouvés** — l'inspecteur (`wama-inspector.js::fillDetail`) et le runner du studio, qui suit
`status`/`progress`/`result_file` sur les clés canoniques (`STUDIO_VISION.md §176`, 8/10 apps).
tool_api en serait le **troisième**, ce qui renforce le contrat au lieu de le concurrencer. Et une
app nouvelle obtient lecture + listing **gratuitement**, puisqu'elle enregistre déjà son adapter
pour l'inspecteur.

**Bénéfice qui n'est pas qu'une économie de lignes** : l'assistant voit alors **exactement ce que
l'utilisateur voit** dans le volet droit. Aujourd'hui, rien ne garantit que `get_X_status` et
l'inspecteur racontent la même chose — deux projections écrites séparément divergent.

⚠ **Deux réserves à traiter, pas à ignorer** :
1. `build_detail` produit une charge d'**affichage** (libellés, icônes, dates formatées
   `12/08/2026 14:03`). Lisible par un LLM, mais **lossy pour le calcul**. Prévoir soit un mode
   `raw`, soit d'exposer en plus les clés canoniques brutes que le studio consomme déjà.
2. `build_detail` peut déclencher `probe_media` (sonde ffmpeg). Acceptable **à l'unité**,
   inacceptable sur un listing — c'est précisément pourquoi le journal n'appelle pas l'adapter
   dans sa liste (mesuré : 73 → 31 requêtes en différant l'hydratation). `list_my_items` doit
   rester léger ; `get_item_detail` est le coûteux, à la demande.

## 8. La mémoire « émotionnelle » — RÉSERVÉE, non implémentée (décision 2026-08-20)

Le 4ᵉ type de memorywire annote un souvenir d'une valence + intensité, pour (a) pondérer le rappel
par saillance et (b) adapter le ton. **Non retenu**, pour trois raisons :

1. C'est le seul type **sans producteur mécanique** : les trois autres constatent (un fait, un
   événement horodaté, une séquence d'actions), celui-ci **infère**. L'inférence serait écrite en
   mémoire permanente avec le même statut qu'un fait — ce que `RunOutcome` interdit explicitement
   (« on enregistre un fait, pas un jugement »).
2. Une inférence fausse est **indétectable après coup** : rien contre quoi la confronter.
3. Profiler l'état émotionnel d'un agent public sur son poste, dans un magasin qui a un scope
   `unit` donc **partageable au labo**, n'est neutre ni juridiquement ni socialement.

⚠ **Ne pas confondre deux objets homonymes.** L'émotion **objet de recherche** du Lescot (annotations
sur sujets/médias, protocole, instruments, annotateurs) est de la **donnée métier** : sa place est
dans le modèle de l'app ou la couche dataset (wama-data), avec sa provenance et son protocole.
Elle n'a aucun rapport avec « ce que l'IA croit deviner de l'humeur de l'utilisateur ». Les loger
dans le même champ serait la surcharge de champ déjà proscrite.

**Le bénéfice est obtenu sans l'inférence** : la pondération de saillance (`MemoryItem.salience`)
se **calcule depuis `RunOutcome`** — `corrige`/`relance`/`supprime` = friction sur ce résultat,
`telecharge` = il l'a emporté. Des gestes observés, pas des devinettes, conformément à la doctrine
« on ne se nourrit que de gestes que l'utilisateur fait déjà ». `salience` est donc **dérivé et
recalculable**, jamais saisi.

Le type reste **réservé dans la taxonomie** : si un usage recherche apparaît, il s'ajoute sans
migration de vocabulaire, et ce paragraphe évite de re-litiger la question.

## 9. Ce qu'on n'adopte pas, et pourquoi (état de l'art au 2026-08-20)

| | Licence | Le mur |
|---|---|---|
| **MemPalace** | MIT | Étoiles achetées (audit sur 42 497), benchmark surajusté (issue #29 : correction sur les questions ratées puis re-test sur le même jeu → « 100 % », ramené à 96,6 %), **la structure « palace » n'est pas impliquée** dans le score et dégrade le rappel en reproduction indépendante, **8 vulnérabilités dont 3 critiques** (issue #809) non corrigées. |
| **mem0** | Apache 2.0 | Self-host = conteneur API + Postgres/pgvector + **Neo4j**. Optimisations propriétaires hors du SDK OSS (dit par leur README). Vendeur VC unique → risque de relicence. |
| **Letta / MemGPT** | Apache 2.0 | C'est un **runtime d'agent**, pas une couche mémoire → même verdict que Hermes (§16.7) : 2ᵉ ordonnanceur à côté du `resource_governor` = corps étranger. |
| **Zep / Graphiti** | Apache 2.0 | Exige un **serveur de graphe externe** (Neo4j 5.26+/FalkorDB). Coût LLM par épisode très élevé. CE self-hosted de Zep retirée. |
| **cognee** | Apache 2.0 | Le graphe comme primitive de rappel principale = sur-ingénierie ; re-crée un modèle de données parallèle. |

**Ce qu'on emprunte quand même** : le *contrat* de memorywire (§5) ; la **rétention verbatim** et le
**rappel scopé** de MemPalace (ses deux bonnes idées) ; la **fenêtre de validité** de Graphiti — le
vrai apport du graphe temporel, qui coûte deux colonnes et non un serveur ; le **merge dédupliqué**
de mem0, mais proposé et non appliqué.

⚠ Tous les scores LOCOMO publiés sont **auto-mesurés** (Zep a publié une réfutation du papier mem0).
Ne rien arbitrer sur ces chiffres.

## 10. Jalons

| # | Jalon | État |
|---|---|---|
| 1 | Extension `vector` installée + activée sur `wama_db` | ✅ 2026-08-20 (pgvector 0.6.0) |
| 2 | `bge-m3` + `embed.py` | ✅ 2026-08-20 — le modèle **était déjà tiré** dans Ollama |
| 3 | Modèles + migration `common/0007` + `store.py` (5 opérations) | ✅ 2026-08-20 — **inerte, aucun appelant** |
| 4 | `project.py` + `manage.py sync_memory` : projection `RunOutcome` → `MemoryItem` | ✅ 2026-08-20 — mais **rien à projeter**, cf. §7bis |
| 5 | `index.py` : indexation RAG depuis la médiathèque (+ rafraîchissement de visibilité, §4) | ⏳ |
| 6 | Branchement `prompt_pipeline` Hook B (remplace le no-op ChromaDB l.116-118) | ⏳ — dépend de 4, 5 |
| 7 | wama-dev-ai : `memory.json` → `MemoryItem` (`provenance='dev-ai'`, non approuvé) | ⏳ |
| 8 | Outil `memory_recall` dans `tool_api.py` | ⏳ — dépend de 6 |
| 9 | Entrée au registre `common/mecanismes.py` (la table de `WAMA_MECANISMES.md` en est générée) | ⏳ |
| 10 | Entrée catalogue `AIModel` pour `bge-m3` (il tourne, il n'est pas déclaré) | ⏳ |
| 11 | Journal `/common/journal/` (couche 1) + captation générique (couche 2) | ✅ 2026-08-20 — §9bis |
| 12 | **tool_api : lecture générique** (`list_my_items` / `get_item_detail`) — §9ter | ⏳ |

**Validation empirique du jalon 3** (2026-08-20, 21 contrôles, 0 échec) — écriture verbatim, dédup
par `content_hash`, garde-fou « approbation sans approbateur » refusée, brouillon LLM invisible au
rappel, isolation entre deux utilisateurs, `forget()` qui invalide sans supprimer, `merge()` qui
n'écrit rien, `expire()` en `dry_run` qui ne compte que du non-approuvé, et **rappel sémantique
sans mot commun** (« quel traitement pour du son Apple ? » → « pour un fichier m4a, décoder avant
Whisper ») — ce dernier prouve que le vectoriel apporte ce que le lexical ne peut pas trouver, et
que la fusion RRF classe bien les deux (`{'vecteur/memory': 1, 'lexical/memory': 1}`).

⚠ **Rien n'appelle la brique.** Elle est complète et testée, mais aucun code WAMA ne l'invoque :
le Hook B de `prompt_pipeline` reste un no-op. Rien ne change pour un utilisateur avant le jalon 6.

## 11. Hors périmètre (tracé ailleurs)

- **Traçage des process + génération de code réutilisable hors WAMA** → scope **wama-data**. Point
  de jonction : le type `procedural`, dont le format de stockage est **déjà** `common/prompt_skills/`
  (ROADMAP §16.7 : « ce qui manque n'est pas le dossier mais **l'écrivain** » — cette brique est
  l'écrivain).
- **Anonymisation du texte avant écriture** (PII dans un souvenir partagé au labo) → `ROADMAP §16.4`,
  Presidio + GLiNER FR. À rebrancher ici quand ce composant existera : un `MemoryItem` de scope
  `unit` ou `public` devra passer la porte privacy.
