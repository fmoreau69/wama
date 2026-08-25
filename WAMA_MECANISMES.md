# WAMA_MECANISMES.md — Carte des mécanismes transversaux

> **Ce fichier est un INDEX, pas une bible.** Il dit *quels* mécanismes profonds existent, *où*
> ils habitent et *quel document* porte leur intention. Il ne réexplique rien : le **pourquoi**,
> les décisions et les pièges restent dans le document de référence de chaque domaine. Recopier
> ici ce que ces documents disent, c'est fabriquer la redondance que la règle « un domaine = un
> fichier » combat — et c'est exactement ainsi que `docs/PRECISION_MODE.md` en est venu à
> annoncer un seuil de segmentation à 65 quand le code disait 50.

## Pourquoi cette carte existe

Deux documents tracent déjà les **deux bouts du tunnel** : `WAMA_APP_GENERATION_ROUTE.md` (route
d'auto-génération des apps, facettes F1–F8) et `WAMA_MANIFEST_ARCHITECTURE.md` /
`WAMA_MANIFEST_SPEC.md` (manifestes → ingest → registres). Entre les deux vit tout le reste — le
gouverneur de ressources, l'ETA auto-apprenante, l'ingest de source, le pipeline de prompts, la
sauvegarde, les licences, les signaux d'exécution, la sélection et la couverture de modèles.

Ces mécanismes existaient, ils fonctionnaient, et **ils n'étaient recensés nulle part**. Il en
est résulté deux briques mortes découvertes à la main le 2026-08-12 :
`model_coverage.couvrir_classes`, sans aucun consommateur pendant huit jours alors qu'il avait
été extrait pour ça, et `common/utils/qc.py`, sans appelant depuis sa création.

## La table est GÉNÉRÉE — elle ne peut pas dériver

La source est le registre déclaratif **`wama/common/mecanismes.py`**. Le tableau ci-dessous en
est la projection, régénérée par `python manage.py doc_facts` et gardée par
`doc_facts --check` (code de sortie 1 si le bloc est périmé). C'est la doctrine WAMA appliquée à
sa propre documentation : l'affichage se remplit depuis les métadonnées, il ne se saisit pas.

**Ajouter un mécanisme transversal = ajouter une entrée au registre**, pas une ligne ici.

La carte est rendue en **une sous-table par domaine** (le domaine est posé par groupe dans le
registre, via `_domaine()`) : un tableau unique de 60 lignes ne se lisait plus. La couche **UI
générée** (2026-08-13) déclare les briques front **au grain mécanisme** : le js/partial d'un
mécanisme déjà déclaré est son ANNEXE (wama-params.js ↔ param_schema), pas une entrée de plus ;
l'inventaire fin par facette reste dans `WAMA_APP_GENERATION_ROUTE.md`, qu'il ne double pas.

### Ce que la colonne « Consommateurs » signale

Le nombre de fichiers qui utilisent le mécanisme : **import** Python pour un module, **référence
du nom de fichier** (balise `<script>`, include) dans les gabarits et le front (.html/.js hors
`staticfiles/` et `vendors/`) pour une brique js/partial. Il répond à trois questions d'un coup :

| Signal | Lecture |
|---|---|
| `❌ absent` | le domicile déclaré n'existe plus — la carte pointe dans le vide |
| `⚠ 0` | **brique morte**, ou brique livrée et pas encore adoptée. À trancher, jamais à ignorer |
| `n` | nombre de modules qui s'en servent |

> ⚠⚠ **LE COMPTE INCLUT LES COMMENTAIRES — il SURESTIME l'adoption** (mesuré le 2026-08-23).
> `consommateurs()` cherche le nom de fichier de la brique dans la source **brute** : une ligne
> qui se contente de la CITER (« brique commune `queue-actions.js` — ne pas re-binder ici »)
> compte autant qu'un `<script src=…>`. Écart mesuré sur les 88 mécanismes : **21 sont
> affectés**, dont
>
> | mécanisme | affiché | consommateurs RÉELS (code seul) |
> |---|---|---|
> | `queue_front` | 60 | **18** |
> | `rag_geste` | 23 | **5** |
> | `new_item_card` | 27 | 16 |
> | `app_base_js` | 17 | 6 |
>
> **Aucune brique morte n'est masquée par ce biais** (aucun mécanisme ne tomberait à `⚠ 0`), donc
> le signal le plus important de la carte reste fiable. Mais l'ampleur — un facteur 3 sur
> `queue_front` — interdit de lire ces nombres comme une mesure d'adoption.
>
> **C'est exactement le défaut déjà corrigé une fois ailleurs** : `conformity_checker` a dû
> passer de `find` à `find_code` le 2026-08-19, parce qu'« un critère qu'un commentaire peut
> faire mentir ne mesure pas, il devine ». Le correctif est le même — neutraliser les
> commentaires avant de chercher, via `_sans_commentaires` qui existe déjà — mais il touche un
> instrument PARTAGÉ et rejouerait tous les comptes : **à faire sur décision, pas au fil de
> l'eau**. Corollaire immédiat : bien commenter une brique AUGMENTE son score d'adoption, ce qui
> est précisément l'incitation qu'un instrument ne doit pas créer.

Et sous la table, la liste des modules **non rattachés au registre** parmi les dossiers balayés
(`common/services/`, `common/utils/`, `common/backends/`, `model_manager/services/`,
`studio/services/` — étendu aux trois derniers le 2026-08-13) — la réponse mécanique à « qu'ai-je
oublié de tracer ». ⚠ Un dossier **hors balayage** ne produit **aucun** signal : c'est ainsi que
`common/backends/base.py`, qui alimente tout le suivi des modèles, est resté invisible de la carte
jusqu'au 13/08 sans que rien ne l'indique. Élargir la liste est donc un acte à faire dès qu'un
dossier prend une fonction transversale. Un utilitaire strictement
local ne se déclare pas : il s'**assume**, et assumer est un acte déclaré lui aussi —
`ASSUMES_LOCAUX` (wama/common/mecanismes.py), une raison datée par entrée, soustrait du backlog
(ajouté au triage du 2026-08-13 : sans lui la liste plafonnait à 45 noms et ne convergeait
jamais). Ce qui reste dans la liste est donc VRAIMENT à trancher. Deux gardes : un module
assumé ET déclaré, ou assumé dont le fichier a disparu, sort en ❌.

---

<!-- WAMA:FAITS(mecanismes) — généré par « python manage.py doc_facts », ne pas éditer -->
#### Ressources & exécution (9)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Contrat de backend** | Cycle de vie commun des porteurs de modèle — ALIMENTATION du gouverneur (enveloppe load/unload/process à toute profondeur d'héritage) et CAPACITÉS déclarées par le moteur (supports_*), lues par le catalogue | `wama/common/backends/base.py` | `WAMA_APP_GENERATION_ROUTE.md` | 31 |
| **ETA auto-apprenante** | Estimation de durée par a-priori puis moyenne mobile, bucketisée par matériel | `wama/model_manager/services/eta_estimator.py` | `PROJECT_STATUS.md §10` | 20 |
| **Gardes de process** | Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines | `wama/common/utils/process_control.py` | `PROJECT_STATUS.md §0` | 22 |
| **Gouverneur de ressources** | Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités | `wama/common/services/resource_governor.py` | `PROJECT_STATUS.md §0` | 14 |
| **Moniteur système** | Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager | `wama/common/services/system_monitor.py` | — | 6 |
| **Mémoire GPU** | Garantit la VRAM avant un chargement, la reprend sur les autres modèles, et réessaie après libération sur erreur CUDA | `wama/model_manager/services/memory_manager.py` | `PROJECT_STATUS.md §0` | 16 |
| **Progression de tâche longue** | Avancement d'une tâche Celery HORS file d'items publié dans le cache (F5-proof) + garde « déjà en cours » vérifiée auprès de Celery ; pendant navigateur = WamaApp.Poller | `wama/common/utils/task_progress.py` | `wama/model_manager/PROSPECTION_PIPELINE.md` | 3 |
| **Squelette de tâche** | Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA | `wama/common/utils/task_skeleton.py` | `WAMA_APP_GENERATION_ROUTE.md` | 4 |
| **Tests nocturnes** | Registre déclaratif de scénarios + runner sérialisé VRAM-aware (wired/ui/consistency/…) | `wama/common/services/nightly_tests.py` | `PROJECT_STATUS.md §Tests fonctionnels nocturnes` | 11 |

#### Modèles (11)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Banc de comparaison** | Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation) | `wama/model_manager/services/bench.py` | — | 1 |
| **Benchmark tiers confronté** | Étage 2 qualité (a priori < benchmark < mesure) : AA + Elo Arena appariés au catalogue, prospection incluse | `wama/model_manager/services/benchmark_sync.py` | `PROJECT_STATUS.md §REPRISE 2026-08-18` | ⚠ **0** |
| **Cache HF scopé** | Bascule TEMPORAIRE du cache HuggingFace par backend — anti-fuite d'artefacts inter-apps | `wama/common/utils/hf_cache.py` | — | 2 |
| **Couverture multi-modèles** | Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation) | `wama/common/services/model_coverage.py` | — | 3 |
| **Découverte de modèles** | Découverte unifiée des modèles (apps + sources externes), synchronisée vers le catalogue AIModel | `wama/model_manager/services/model_registry.py` | — | 12 |
| **Indice de qualité a priori** | Ordonne les modèles autrement que par la taille (params EFFECTIFS √(totaux×actifs), contexte, quantif.) | `wama/model_manager/services/model_quality.py` | — | 1 |
| **Installation de modèles** | Pipeline accept→download→register : télécharge au bon endroit puis enregistre au catalogue | `wama/model_manager/services/model_installer.py` | — | 4 |
| **Prospection de modèles** | Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run) | `wama/model_manager/services/prospector.py` | `wama/model_manager/PROSPECTION_PIPELINE.md` | 8 |
| **Provenance de modèle** | Identité chez l'éditeur (licence, auteur, plateforme), posée VIA le manifeste | `wama/model_manager/services/provenance.py` | — | 4 |
| **Sonde vision** | Décrit une image via un modèle multimodal Ollama local (bench, smoke UI, fichiers de référence) | `wama/model_manager/services/vision_probe.py` | — | 4 |
| **Sélection de modèle** | Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité | `wama/model_manager/services/model_selector.py` | `INPUT_MODEL_MATCHING.md` | 7 |

#### Qualité & auto-amélioration (9)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Ajout au RAG (geste explicite)** | Bouton dans l'INSPECTEUR + page « Mon RAG » ; texte pris au schéma canonique, aucune ligne par app. Pas de balayage : l'entrée au RAG est un geste, par décision | `wama/common/static/common/js/wama-inspector.js` | `WAMA_MEMORY.md §7ter` | 23 |
| **Barre de filtrage** | Recherche + facettes EN DIRECT ; options dérivées du DOM (client) ou déclarées (server) | `wama/common/static/common/js/wama-filter-bar.js` | `CARD_DESIGN.md` | 11 |
| **Captation générique des gestes** | Middleware : telecharge/supprime/relance lus de resolver_match — zéro ligne par app | `wama/common/middleware.py` | `WAMA_MEMORY.md §7bis` | 2 |
| **Contrôle qualité de sortie** | Note une sortie par un validateur LLM INDÉPENDANT ; signal relatif, escalade humaine | `wama/common/utils/qc.py` | `ROADMAP.md §16.5` | ⚠ **0** |
| **Divergence inter-systèmes** | Désaccord entre deux sorties du même travail — signal objectif, sans avis de modèle | `wama/common/services/divergence.py` | `wama/transcriber/TRANSCRIBER_CORRECTION.md §8.3` | 1 |
| **Journal transversal de l'utilisateur** | Tout ce qu'il a lancé, toutes apps — DÉRIVÉ de detail_registry, aucune ligne par app | `wama/common/services/journal.py` | `WAMA_MEMORY.md §9bis` | 1 |
| **Mémoire & RAG** | Souvenirs + fragments sur pgvector, scope hérité de ScopedVisibility ; 5 opérations | `wama/common/memory/store.py` | `WAMA_MEMORY.md` | 8 |
| **Projection des faits en souvenirs** | RunOutcome → MemoryItem par OBJET (mécanique, sans modèle, idempotente) | `wama/common/memory/project.py` | `WAMA_MEMORY.md §7` | 2 |
| **Signaux d'exécution** | Journal append-only des FAITS observés sur un résultat (produit/corrigé/relancé…) | `wama/common/services/run_outcome.py` | `ROADMAP.md §16.7` | 3 |

#### Contenu & prompts (9)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Accès LLM** | Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local) | `wama/common/utils/llm_utils.py` | — | 13 |
| **Appariement d'identité de canal** | Relie une identité Matrix/Discord à un compte WAMA par code prouvé hors canal — la garde que tout adaptateur appelle avant d'agir | `wama/gateway/services.py` | `ROADMAP.md §19` | 175 |
| **Claude Code sur abonnement** | Délègue une tâche de développement au CLI Claude Code en headless — lecture seule par défaut, environnement construit sans la clé API | `wama/common/services/claude_code.py` | `ROADMAP.md §19.3` | 1 |
| **Export document** | Génère PDF (fpdf2) / DOCX (python-docx) depuis les résultats d'app | `wama/common/utils/document_export.py` | — | 3 |
| **Garde des URL sortantes** | Valide toute cible de téléchargement pilotée par une saisie : schéma, identifiants, et adresses privées/bouclage/lien-local — anti-SSRF | `wama/common/utils/url_guard.py` | `PROFILES_PERMISSIONS.md` | 2 |
| **Ingest de source** | Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST | `wama/common/utils/source_ingest.py` | `WAMA_APP_GENERATION_ROUTE.md` | 11 |
| **Moteur de l'assistant IA** | Boucle agentique multi-surface (prompts, outils tool_api, local/cloud) — la vue web et /api/v1/assistant/chat/ en sont des clients | `wama/common/services/assistant_engine.py` | — | 7 |
| **Pipeline de prompts** | Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS | `wama/common/utils/prompt_enrichment.py` | `WAMA_IA_TRANSVERSE.md` | 18 |
| **Skills de rôle de l'assistant** | Posture et domaine de l'assistant (science, design, dev) + rappel du contexte de laboratoire, déclarés par domaine — distinct de l'enrichissement | `wama/common/utils/assistant_skills.py` | `ROADMAP.md §19.7` | 3 |

#### Manifestes & registres (6)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Adoption des mécanismes** | Qui consomme quoi (imports + briques front), niveau APP vs infrastructure, et jonction registre↔grille : mécanisme adopté par des apps que rien ne vérifie | `wama/common/services/mecanismes_scan.py` | `WAMA_MECANISMES.md` | 1 |
| **Audit des licences** | Vue dérivée : licences+auteurs des 4 registres, traversée par app. Ne voit PAS le code vendorisé (`static/vendors/`, codeformer) — inventorié à la main dans LICENSING.md §3 | `wama/common/services/license_audit.py` | `LICENSING.md` | 2 |
| **Bac à sable d'apps (jumelles exécutables)** | Jumelle <app>_NN coexistante pour comparaison Playwright + diff dé-suffixé (route §10.3 marche S) — registre sandbox_apps.json injecté au boot (INSTALLED_APPS/urls/gating/catalogue), create/drop symétriques | `wama/common/sandbox.py` | `WAMA_APP_GENERATION_ROUTE.md` | 8 |
| **Formats de sortie** | Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire converter) | `wama/common/utils/output_formats.py` | — | 5 |
| **Grille de conformité** | Mesure les 8 facettes F1–F8 des apps par analyse du code réel | `wama/common/services/conformity_checker.py` | `WAMA_APP_CONVENTIONS.md` | 4 |
| **Manifestes** | Extraction/validation/projection des 7 kinds vers les registres | `wama/common/manifests/ingest.py` | `WAMA_MANIFEST_ARCHITECTURE.md` | 23 |

#### File d'attente & lots (9)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Console utilisateur** | Lignes de journal structurées par utilisateur et par app. ⚠ Annoncé « via Redis », mais le chemin Redis exige `django_redis` — ABSENT des deux venvs et des `requirements` (vérifié 2026-08-22) : la console tourne DEPUIS TOUJOURS sur son repli cache, qui fonctionne mais n'est pas atomique (lire/insérer/réécrire, donc des lignes perdues quand gunicorn et les workers Celery poussent en même temps). Le correctif n'est PAS d'ajouter la dépendance : le client `redis` brut est déjà installé et la brique d'accès existe (`resource_governor._redis`, via `CELERY_BROKER_URL`) | `wama/common/utils/console_utils.py` | — | 31 |
| **Dossier de travail jetable** | Les fichiers INTERMÉDIAIRES d'un traitement ne vivent pas dans `media/`. Mesuré le 2026-08-25 : `media/avatarizer/` pesait 1,69 Go pour 2101 fichiers dont 99,6 % de PNG — les frames de CodeFormer, écrites dans le dossier de sortie du job et jamais nettoyées ; `job_11` portait 1715,7 Mo pour une vidéo de 0,70 Mo. `media/` ne contient que `<app>/<user>/input|output/` et `users/` (MEDIA_STORAGE_TIERING.md) : un fichier de travail y est sauvegardé par le miroir, compté par le tiering et servi par Apache pour rien. Le `with` rend le nettoyage STRUCTUREL au lieu d'être une convention qu'on oublie — le patron `mkdtemp`+`rmtree` est recopié sur 11 sites, garanti par un `finally` sur 5 seulement. ⚠ Les 6 autres n'ont PAS été audités un par un (au moins un délègue son nettoyage par contrat documenté) : leur portage est un chantier d'adoption site par site, jamais une conversion en masse. Porte aussi `purge_job_dir` : la suppression d'une card doit emporter le dossier du job — 13 dossiers `job_*` orphelins relevés contre 4 rattachés | `wama/common/utils/work_dir.py` | `MEDIA_STORAGE_TIERING.md` | 37 |
| **Duplication et suppression sûres** | duplicate_instance() et safe_delete_file() — fichiers partagés entre items | `wama/common/utils/queue_duplication.py` | `WAMA_APP_CONVENTIONS.md` | 15 |
| **Entrée de file (card seule OU lot)** | Décide, pour une entrée de file, si elle s'affiche en card unique ou en card MÈRE avec ses filles repliables — et rend l'un ou l'autre. Le bloc vivait recopié À L'IDENTIQUE dans 9 gabarits ; il n'a pu être centralisé (2026-08-25) qu'une fois deux verrous levés : `is_unitary` adopté (la décision se lit sur le modèle) et `elem` (les 9 cards filles reçoivent leur élément sous le MÊME nom — avant, 8 graphies). Signature à 3 paramètres : `card_template`, plus `collapse_prefix` et `batch_key` pour la seule app à deux files sur une page (enhancer audio). ⚠ Tout le reste TRAVERSE PAR LE CONTEXTE — les ~9 paramètres de `_batch_card.html` sont fournis par l'app et passent au travers, sinon la signature atteindrait la quinzaine. Apparence uniformisée sur le TRANSCRIBER (référence), conforme à `CARD_DESIGN §11.2` (famille de lot = cyan #0dcaf0) : les 3 couleurs et 2 habillages qui coexistaient étaient des séquelles d'implémentations successives | `wama/common/templates/common/_queue_entry.html` | `CARD_DESIGN.md §11.2` | 182 |
| **File d'attente (front)** | Comportements communs des files : collapse de batch persisté, focus card, data-wama-* | `wama/common/static/common/js/wama-queue.js` | `CARD_DESIGN.md` | 63 |
| **Import par lot** | Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot | `wama/common/utils/batch_parsers.py` | `BATCH_FORMAT.md` | 50 |
| **Manipulation directe de la file** | Endpoints génériques : sortir une card d'un batch, réordonner, déplacer, consolider | `wama/common/utils/queue_manipulation.py` | `CARD_DESIGN.md §3bis` | 11 |
| **Notifications de tâche** | notify_job() — fin de traitement, succès comme échec | `wama/common/utils/notifications.py` | `PROFILES_PERMISSIONS.md` | 12 |
| **Tri/filtrage de la file** | Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps | `wama/common/utils/queue_view.py` | `CARD_DESIGN.md` | 12 |

#### UI générée (18)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Bouton de cycle** | Bouton commun ▶/⏹/↻ toujours vert — l'icône porte l'action, l'état vit sur la card | `wama/common/static/common/js/wama-cycle-button.js` | — | 20 |
| **Card v3** | Dimensionnement déclaratif des pistes de card — dépend de l'app, des actions, des libellés | `wama/common/static/common/js/wama-card-v3.js` | `CARD_DESIGN.md §11` | 5 |
| **Card « Nouvel élément »** | Card d'entrée dépliable commune (dropzones, URL, médiathèque, batch) — auto-init | `wama/common/static/common/js/wama-new-item-card.js` | `MODES_QUEUE_UX.md` | 27 |
| **Chips méta des cards** | Chips de l'état concis GÉNÉRÉS du schéma params (chip=True) — jamais écrits par app | `wama/common/utils/card_chips.py` | `CARD_DESIGN.md §10.3` | 26 |
| **Domaines → modes** | Schéma déclaratif des onglets-domaine et modes par app — scope la file | `wama/common/utils/app_modes.py` | `MODES_QUEUE_UX.md` | 14 |
| **Import de dossier récursif** | Traversée récursive d'un drop/webkitdirectory — brique F2 montée globale (base.html) | `wama/common/static/common/js/wama-folder-import.js` | `WAMA_APP_GENERATION_ROUTE.md` | 2 |
| **Inspecteur — champs de détail** | Schéma canonique des infos d'item affichées au volet droit | `wama/common/utils/detail_registry.py` | `INSPECTOR_DETAIL_FIELDS.md` | 43 |
| **Lecteur audio (onde + transport)** | Widget autonome : onde canvas (pics serveur ou décodés), play/pause, exclusivité inter-lecteurs et inter-onglets ; monté par la preview dans le volet ET les cards | `wama/common/static/common/js/wama-audio-player.js` | — | 5 |
| **Preview unifiée** | Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps | `wama/common/utils/preview_registry.py` | — | 35 |
| **Progression & ETA (front)** | Moteur ETA par débit observé + barres aux 3 niveaux : card, batch, globale | `wama/common/static/common/js/wama-eta.js` | `PROJECT_STATUS.md §10` | 40 |
| **Schéma de paramètres** | Source unique des réglages d'app : volet droit et modale sont RENDUS depuis lui | `wama/common/utils/param_schema.py` | `WAMA_APP_GENERATION_ROUTE.md` | 39 |
| **Shuttle J/K/L** | État de vitesse/direction de lecture (paliers éditeur) + binding clavier ; l'app fournit apply(speed) — la commande est commune, l'application au lecteur reste locale | `wama/common/static/common/js/wama-shuttle.js` | — | 3 |
| **Signalement au gestionnaire de fichiers** | Noms d'événements centralisés (media:uploaded/processed/deleted) — l'arborescence du filemanager se rafraîchit sans que chaque app invente son event | `wama/common/static/common/js/wama-fm-notify.js` | — | 2 |
| **Socle JS des apps** | Plomberie commune file/cards : csrfFetch, urls, Poller de progression, états vides | `wama/common/static/common/js/wama-app-base.js` | `WAMA_APP_GENERATION_ROUTE.md` | 17 |
| **Sélecteur de médiathèque** | Modale commune de choix d'un asset de la médiathèque (filtrée par type), rendue à l'appelant sous forme de File + méta | `wama/common/static/common/js/media-picker.js` | — | 4 |
| **Vocabulaire des capacités** | Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI | `wama/common/utils/model_capabilities.py` | `INPUT_MODEL_MATCHING.md` | 22 |
| **Voie d'import (front)** | Envoi d'un fichier vers l'endpoint upload de l'app depuis toutes les sources (dépôt, clic, médiathèque), délégation du LOT à batch_import, consolidation et rafraîchissement — agnostique du monde (ni MIME ni extension) | `wama/common/static/common/js/wama-import.js` | `WAMA_APP_GENERATION_ROUTE.md` | 4 |
| **data-* du gear ⚙ des cards** | data-* du bouton ⚙ DÉRIVÉS du schéma (contrat cardSettings de l'inspecteur : le volet reflète la card sélectionnée) — remplace les attributs écrits à la main par app ; booléens 'true'/'false', tous les params item émis (anti-résidus) | `wama/common/utils/card_gear.py` | — | 10 |

#### Données & infrastructure (20)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Accès ffmpeg** | Résolution centralisée du binaire et des conversions (échappatoire FFMPEG_BINARY) | `wama/common/utils/ffmpeg_utils.py` | — | 14 |
| **Accès scopé aux objets** | Deux chemins NOMMÉS pour lire un objet partageable depuis une vue (possédé / visible) | `wama/common/utils/scoping.py` | `PROFILES_PERMISSIONS.md` | 10 |
| **Actualisation des catalogues** | REGISTRE des registres : une page catalogue déclare la CLÉ de son registre et hérite du bouton, de l'endpoint, de la permission et du compte-rendu. La NATURE déclarée (scan / mesure / re-déclaration / DÉRIVÉ) décide du rendu — un dérivé affiche « toujours à jour » au lieu d'un bouton qui ne ferait rien — ET le LIEU d'exécution : état partagé → tâche Celery non bloquante, registre en mémoire → sur place, avec propagation aux autres workers gunicorn | `wama/common/registries.py` | — | 10 |
| **Arbre organisationnel depuis l'annuaire** | ou=structures (SUPANN) → OrgUnit + parents ; peuple ce dont dépend le partage par unité (RAG labo, médiathèque). Lecture seule côté LDAP, idempotente | `wama/accounts/management/commands/sync_org_units.py` | `PROFILES_PERMISSIONS.md` | 1 |
| **Bascules de fonctionnalités** | Registre de Feature par app + surcharges JSON de l'objet porteur — comparer AVEC/SANS | `wama/common/utils/feature_flags.py` | — | 1 |
| **Chemins média** | Emplacements canoniques des entrées/sorties par app et par utilisateur | `wama/common/utils/media_paths.py` | — | 24 |
| **Décodage audio robuste** | Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg. Annexe torchaudio_compat = l'autre forme du même problème : shims soundfile posés DANS torchaudio pour les libs tierces qui l'appellent en interne (Coqui, DeepFilterNet) | `wama/common/utils/audio_decode.py` | — | 5 |
| **Importer universel (WAMA Data)** | REGISTRE de capacités de lecture — aucun format privilégié : ajouter un format = déposer un lecteur, jamais éditer le moteur. Porte aussi l'HORODATAGE par flux (dont le ré-horodatage par fréquence théorique, qui n'interpole rien et ne s'applique que sur demande). ⚠ La MÉCANIQUE SQLite (ouverture en lecture seule, décodage UTF-8→cp1252 du texte des bases MATLAB, valeurs triées, les trois niveaux d'agrégation) est un socle partagé — un lecteur de base concret n'écrit plus que `can_read`, `probe` et `read`, c'est-à-dire sa seule connaissance du schéma | `wama_data/sources/__init__.py` | `WAMA_DATA_WORLD.md §6.6, §9terdecies` | 3 |
| **Noms dérivés (WAMA Data)** | DOMICILE UNIQUE de la règle « le nom se DÉRIVE des paramètres, il ne se saisit pas » : deux productions de mêmes réglages portent le même nom, deux réglages différents ne peuvent pas le partager. Elle était appliquée par QUATRE règles dans TROIS lieux — dont une f-string écrite en dur — avant l'audit du 23/08. Les anciens emplacements réexportent ; un test vérifie l'IDENTITÉ des fonctions, donc une redéfinition locale même à l'identique échoue. Sans dépendance, par nécessité : c'est ce qui permet à `conditions.py` de l'importer sans cycle | `wama_data/core/noms.py` | `WAMA_DATA_WORLD.md §9ter.6 B7, §9sexies.4` | 11 |
| **Pont référentiel ↔ cadres typés (WAMA Data)** | SEULE frontière entre les deux vocabulaires du monde Data : le référentiel (paresseux, indexé, sans pandas) et le `TypedFrame` que mangent toutes les fonctions du catalogue. Sans lui le référentiel n'avait AUCUN consommateur — non parce qu'on ne s'en servait pas, mais parce qu'on ne POUVAIT pas. Traite quatre pièges mesurés : le temps de SESSION (± offset) vs le temps local du flux, la colonne temporelle brute PÉRIMÉE après ré-horodatage, le contrat `rows` réel mais non déclaré, et la PROVENANCE — ce qui revient d'un calcul ne peut pas se déclarer acquis (`is_base=False` sans échappatoire) | `wama_data/frames.py` | `WAMA_DATA_WORLD.md §9quater.7` | 5 |
| **Référentiel temporel (WAMA Data)** | Aligne des flux à cadences INCOMMENSURABLES et répond aux questions temporelles : quel échantillon à t, quels segments le contiennent, quel événement suit, et la vue DÉCIMÉE (min/max par tranche) sans laquelle aucun tracé n'est viable. N'interpole jamais : la valeur rendue est toujours un échantillon existant | `wama_data/core/temporal.py` | `WAMA_DATA_WORLD.md §2-§3` | 16 |
| **Réglages utilisateur par app** | Persistance cache user_{id}_{app}_{clé} avec défauts déclarés par l'app | `wama/common/utils/user_settings.py` | — | 8 |
| **Rétention des médias** | Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts) | `wama/common/services/retention.py` | `PROFILES_PERMISSIONS.md` | 2 |
| **Sauvegarde & tirage** | Moteur unique de miroir (modèles, base, médias, secrets) et restauration | `wama/common/services/mirror_sync.py` | — | 8 |
| **Sonde média** | Durée/codec/dimensions/pages d'un média pour les propriétés de card (via ffmpeg_utils) | `wama/common/utils/media_probe.py` | — | 4 |
| **Taxonomie des types de donnée** | Vocabulaire commun des sources et des fonctions : sous-typage + compatibilité de ports. `segments` y est LE type « portion de temps bornée » (situation, état, section) | `wama/common/catalog/data_types.py` | `WAMA_DATA_FUNCTION_CARDS.md §3` | 39 |
| **Utilitaires vidéo** | Extraction audio des vidéos + téléchargement YouTube/yt-dlp | `wama/common/utils/video_utils.py` | — | 16 |
| **View-model d'exploration (WAMA Data)** | Une VUE déclare ce qu'on regarde — flux, fenêtre, résolution, colonnes dérivées — et rien de plus : sérialisable en JSON, donc rejouable et diffable, et on persiste ELLE plutôt que les valeurs (une colonne matérialisée se périme sans le dire). Rend EXÉCUTABLE la règle « une nouvelle table SSI la clé temporelle change » en la DÉRIVANT de la `FunctionCategory` : ajouter une fonction au catalogue la range du bon côté sans toucher le view-model. La séparation tables/annexes rend la règle visible à l'écran au lieu d'avoir à l'expliquer | `wama_data/vue.py` | `WAMA_DATA_WORLD.md §9quater.4, §9quater.7` | 2 |
| **Visibilité et portée** | Privé / unité / public : filtrage des lectures, mutations inchangées | `wama/common/models.py` | `PROFILES_PERMISSIONS.md` | 25 |
| **Écrivain de conteneur (WAMA Data)** | UN MOTEUR, N SCHÉMAS — le pendant exact du registre de lecteurs, et le premier code du monde Data qui ÉCRIVE du SQLite (0 `INSERT` dans tout le monde avant lui). Le moteur tient la transaction, les tranches, l'indexation temporelle et la conversion des valeurs ; un schéma ne décide que des NOMS et du CATALOGUE — c'est ce qui garantit que `.wdat` (natif, D3) et `.trip` (compatibilité BIND) se comportent pareil là où ils le doivent. Écrit d'abord un `.partiel` puis renomme : un conteneur à moitié rempli s'ouvrirait normalement en mentant sur son contenu. ⚠ CE QUE LE SCHÉMA CIBLE NE SAIT PAS PORTER EST COMPTÉ, pas tu (`Rapport.pertes`) — une conversion qui appauvrit en silence fait croire à un aller-retour fidèle. La compatibilité est attestée par CONTRE-ÉPREUVE : ce que WAMA écrit, le lecteur `.trip` — écrit contre le format de l'autre, sans rien savoir de l'écrivain — le relit | `wama_data/containers/__init__.py` | `WAMA_DATA_WORLD.md §9quater.2, §9duodecies` | 2 |

#### Studio & surface d'outils (API) (3)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **API REST v1** | Passerelle générique (token+session) sur TOOL_REGISTRY : lister/exécuter, gating F7 à l'annonce ET à l'exécution | `wama/api/v1/views.py` | — | 3 |
| **Runner générique du studio** | Exécute une app par son CONTRAT (triade tool_api normalisée) — zéro logique par app | `wama/studio/services/generic_runner.py` | `STUDIO_VISION.md` | 7 |
| **Surface d'outils** | Registre central TOOL_REGISTRY : triades add/start/status par app, gating F7 via execute_tool, descriptions dérivées des schémas | `wama/tool_api.py` | `WAMA_APP_GENERATION_ROUTE.md` | 9 |

**Mécanismes déclarés : 94** · domiciles absents : 0 · sans consommateur : 2 · assumés locaux : 18 · modules balayés non rattachés : 4 · **de niveau app sans critère de grille : 21**
- ⚠ **Sans consommateur** (brique morte ou pas encore adoptée) : `benchmark_sync` (wama/model_manager/services/benchmark_sync.py), `qc` (wama/common/utils/qc.py)

<details><summary>⚠ <b>21 mécanisme(s) de niveau app SANS critère de grille</b> — adoptés par des apps, vérifiés par aucun critère (<code>Criterion.mecanisme</code>) : une app peut sortir à 100 % sans les avoir adoptés</summary>

| Mécanisme | Adopté par | Domicile |
|---|---|---|
| `gateway_identity` — Appariement d'identité de canal | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/gateway/services.py` |
| `media_paths` — Chemins média | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/utils/media_paths.py` |
| `rag_geste` — Ajout au RAG (geste explicite) | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/static/common/js/wama-inspector.js` |
| `work_dir` — Dossier de travail jetable | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/utils/work_dir.py` |
| `manifests` — Manifestes | **8** app(s) : anonymizer, avatarizer, composer, describer, enhancer, imager, synthesizer, transcriber | `wama/common/manifests/ingest.py` |
| `notifications` — Notifications de tâche | **8** app(s) : anonymizer, avatarizer, composer, describer, enhancer, imager, synthesizer, transcriber | `wama/common/utils/notifications.py` |
| `ffmpeg` — Accès ffmpeg | **5** app(s) : anonymizer, converter, describer, enhancer, transcriber | `wama/common/utils/ffmpeg_utils.py` |
| `output_formats` — Formats de sortie | **5** app(s) : anonymizer, composer, enhancer, imager, synthesizer | `wama/common/utils/output_formats.py` |
| `video_utils` — Utilitaires vidéo | **5** app(s) : anonymizer, converter, describer, enhancer, transcriber | `wama/common/utils/video_utils.py` |
| `audio_decode` — Décodage audio robuste | **4** app(s) : converter, enhancer, synthesizer, transcriber | `wama/common/utils/audio_decode.py` |
| `document_export` — Export document | **3** app(s) : describer, reader, transcriber | `wama/common/utils/document_export.py` |
| `llm` — Accès LLM | **3** app(s) : describer, reader, transcriber | `wama/common/utils/llm_utils.py` |
| `audio_player` — Lecteur audio (onde + transport) | **2** app(s) : composer, transcriber | `wama/common/static/common/js/wama-audio-player.js` |
| `media_picker` — Sélecteur de médiathèque | **2** app(s) : avatarizer, imager | `wama/common/static/common/js/media-picker.js` |
| `media_probe` — Sonde média | **2** app(s) : converter, transcriber | `wama/common/utils/media_probe.py` |
| `nightly_tests` — Tests nocturnes | **2** app(s) : enhancer, transcriber | `wama/common/services/nightly_tests.py` |
| `task_skeleton` — Squelette de tâche | **2** app(s) : converter, reader | `wama/common/utils/task_skeleton.py` |
| `model_coverage` — Couverture multi-modèles | **1** app(s) : anonymizer | `wama/common/services/model_coverage.py` |
| `provenance` — Provenance de modèle | **1** app(s) : anonymizer | `wama/model_manager/services/provenance.py` |
| `resource_governor` — Gouverneur de ressources | **1** app(s) : avatarizer | `wama/common/services/resource_governor.py` |
| `run_outcome` — Signaux d'exécution | **1** app(s) : transcriber | `wama/common/services/run_outcome.py` |

</details>

<details><summary>⚠ <b>4 module(s) balayé(s) non rattachés au registre</b> — à déclarer dans <code>wama/common/mecanismes.py</code>, ou à assumer comme utilitaires locaux (tout n'est pas un mécanisme transversal)</summary>


`wama/common/services/` (1) — `conversation_store.py`

`wama/common/utils/` (2) — `export_formats.py` · `volet.py`

`wama/common/static/common/js/` (1) — `wama-avatar.js`

</details>

<details><summary>Assumés utilitaires locaux : 18 (chacun avec sa raison — <code>ASSUMES_LOCAUX</code>, wama/common/mecanismes.py)</summary>

- `disk_utils.py` — plomberie disque (1 consommateur common)
- `format_policy.py` — politique de formats de POIDS de modèle — chaîne modèles
- `html_render.py` — rendu HTML→PDF, consommé par le converter seul
- `http_proxy.py` — plomberie proxy UGE (common + model_manager)
- `intervals.py` — algèbre d'intervalles — cam_analyzer (coverage) seul consommateur
- `lang_routing.py` — routage de langue — sera absorbé par le Translator (ROADMAP §10)
- `log_rotation.py` — décalage des journaux au démarrage (politique : on décale, on ne vide pas)
- `mime_utils.py` — détection MIME — helper fin (filemanager/studio)
- `model_locations.py` — chemins de modèles — plomberie model_manager
- `ollama_host.py` — résolution OLLAMA_HOST (hôte Windows depuis WSL2) — plomberie infra
- `onnx_utils.py` — inspection de poids ONNX — plomberie chaîne modèles
- `safetensors_utils.py` — inspection de poids safetensors — plomberie chaîne modèles
- `translator.py` — brique deep-translator — sera absorbée par le Translator (ROADMAP §10)
- `video_compat.py` — compat lecteur navigateur (ensure_h264) — cam_analyzer seul ; promouvoir si adoption
- `voice_options.py` — pendant VOIX d'output_formats (avatarizer) — promouvoir si adoption s'élargit
- `waveform.py` — rendu de forme d'onde — fusion des 2 renderers encore pendante (REPRISE)
- `whisper_utils.py` — adaptateur describer → backend Whisper du transcriber (UNIFIÉ 13/08 : plus de double chemin de chargement) ; consommé par le describer seul
- `format_converter.py` — conversion de formats de poids — plomberie chaîne modèles (avec format_policy)

</details>
<!-- /WAMA:FAITS(mecanismes) -->

---

## Documents de référence par domaine

Rappel des domiciles de l'**intention** — la carte pointe vers eux, elle ne les remplace pas.

| Domaine | Document |
|---|---|
| Route d'auto-génération des apps (F1–F8) | `WAMA_APP_GENERATION_ROUTE.md` |
| Manifestes — formalisme / flux | `WAMA_MANIFEST_SPEC.md` · `WAMA_MANIFEST_ARCHITECTURE.md` |
| Conventions d'application | `WAMA_APP_CONVENTIONS.md` |
| IA transverse — prompts, skills, chaîne complète | `WAMA_IA_TRANSVERSE.md` |
| Appariement entrée ↔ modèle | `INPUT_MODEL_MATCHING.md` |
| Profils, permissions, portée | `PROFILES_PERMISSIONS.md` |
| Prospection de modèles | `wama/model_manager/PROSPECTION_PIPELINE.md` |
| Avancement des chantiers | `PROJECT_STATUS.md` · `ROADMAP.md` |

## Trous connus

Ce que la carte rend visible et qu'il ne faut pas masquer :

- **Des mécanismes sans document de référence** (colonne « Doc » à `—`). Leur intention n'est
  écrite que dans les docstrings et les messages de commit. Ce n'est pas rédhibitoire — un
  docstring exhaustif vaut mieux qu'un `.md` qui dérive — mais ça se sait.
- **Le RAG n'apparaît pas** : il n'est pas implémenté (ROADMAP §8c). Il entrera au registre le
  jour où il aura un domicile, pas avant — déclarer une intention comme un mécanisme rendrait la
  carte menteuse.
- **La couverture de `RunOutcome` est partielle** : deux apps sur dix, celles qui ont adopté le
  squelette de tâche. La carte compte les consommateurs du mécanisme, pas les apps couvertes.
