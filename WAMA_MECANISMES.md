# WAMA_MECANISMES.md — Carte des mécanismes transversaux

> **Ce fichier est un INDEX, pas une bible.** Il dit *quels* mécanismes profonds existent, *où*
> ils habitent et *quel document* porte leur intention. Il ne réexplique rien : le **pourquoi**,
> les décisions et les pièges restent dans le document de référence de chaque domaine. Recopier
> ici ce que ces documents disent, c'est fabriquer la redondance que la règle « un domaine = un
> fichier » combat — et c'est exactement ainsi que `docs/archive/PRECISION_MODE.md` en est venu à
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

Et sous la table, la liste des modules **non rattachés au registre** parmi les dossiers balayés —
la réponse mécanique à « qu'ai-je oublié de tracer ». La liste des dossiers **n'est pas recopiée
ici** : elle vit dans `doc_facts.py` (`dossiers_balayes`), et la version qui occupait cette place
en citait **5** quand le code en balayait **7** (mesuré le 28/08) — elle avait raté les deux
élargissements de la semaine. *Une liste blanche recopiée à côté de la vraie ne se met jamais à
jour deux fois ; le rendu ci-dessous, lui, en vient.*

⚠ Un dossier **hors balayage** ne produit **aucun** signal : c'est ainsi que
`common/backends/base.py`, qui alimente tout le suivi des modèles, est resté invisible de la carte
jusqu'au 13/08 sans que rien ne l'indique. Élargir la liste est donc un acte à faire dès qu'un
dossier prend une fonction transversale — et la leçon s'est **rejouée quatre fois** (le front le
19/08, `common/memory/` le 21/08, `common/tts/` le 28/08, ce dernier découvert en y DÉPOSANT une
brique). Se souvenir n'est donc pas le geste : **ajouter le dossier au balayage dans le commit qui
crée son premier fichier**. Un utilitaire strictement
local ne se déclare pas : il s'**assume**, et assumer est un acte déclaré lui aussi —
`ASSUMES_LOCAUX` (wama/common/mecanismes.py), une raison datée par entrée, soustrait du backlog
(ajouté au triage du 2026-08-13 : sans lui la liste plafonnait à 45 noms et ne convergeait
jamais). Ce qui reste dans la liste est donc VRAIMENT à trancher. Deux gardes : un module
assumé ET déclaré, ou assumé dont le fichier a disparu, sort en ❌.

---

<!-- WAMA:FAITS(mecanismes) — généré par « python manage.py doc_facts », ne pas éditer -->
#### Ressources & exécution (12)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Client du service TTS** | L'appel POST /tts UNIQUE vers le microservice TTS (payload contractuel, 503 « loading » → TTSServiceLoadingError, WAV temporaire ou bytes) ; les POLITIQUES (retry Celery, chunking, replis) restent aux appelants — extrait 2026-08-28 : 4 exemplaires vivaient dans le dépôt, un seul détectait le 503 | `wama/common/tts/service_client.py` | `MODES_QUEUE_UX.md §2bis` | 4 |
| **Contrat de backend** | Cycle de vie commun des porteurs de modèle — ALIMENTATION du gouverneur (enveloppe load/unload/process à toute profondeur d'héritage) et CAPACITÉS déclarées par le moteur (supports_*), lues par le catalogue | `wama/common/backends/base.py` | `WAMA_APP_GENERATION_ROUTE.md` | 64 |
| **ETA auto-apprenante** | Estimation de durée par a-priori puis moyenne mobile, bucketisée par matériel | `wama/model_manager/services/eta_estimator.py` | `PROJECT_STATUS.md §10` | 23 |
| **Gardes de process** | Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines | `wama/common/utils/process_control.py` | `PROJECT_STATUS.md §0` | 24 |
| **Gouverneur de ressources** | Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités | `wama/common/services/resource_governor.py` | `PROJECT_STATUS.md §0` | 20 |
| **Import « Envoyer vers » (registre + dérivation jumelles)** | Le registre `IMPORTERS` EST le dispatch ET la source du menu client (une seule liste — plus d'app offerte-puis-refusée) ; une JUMELLE de bac à sable n'y écrit jamais sa ligne : son importeur est DÉRIVÉ de sa source (`importer_for`, via `generated_from` + paramètre `app_label` — re-ciblé sur SES tables, jamais celles de la source), et la CONSOLIDATION en lots de l'import groupé suit la même voie (2026-08-30/31, constats Fabien : jumelle absente du menu, puis cards unitaires). ⏳ avatarizer/composer sans importeur : leur fichier est une RÉFÉRENCE — attend le contrat d'import PAR RÔLE (CARD_DESIGN §11.8) | `wama/filemanager/views.py` | `WAMA_APP_GENERATION_ROUTE.md §S2bis` | 1 |
| **Moniteur système** | Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager | `wama/common/services/system_monitor.py` | — | 6 |
| **Mémoire GPU** | Garantit la VRAM avant un chargement, la reprend sur les autres modèles, et réessaie après libération sur erreur CUDA | `wama/model_manager/services/memory_manager.py` | `PROJECT_STATUS.md §0` | 17 |
| **Progression de tâche longue** | Avancement d'une tâche Celery HORS file d'items publié dans le cache (F5-proof) + garde « déjà en cours » vérifiée auprès de Celery ; pendant navigateur = WamaApp.Poller | `wama/common/utils/task_progress.py` | `wama/model_manager/PROSPECTION_PIPELINE.md` | 3 |
| **Squelette de tâche** | Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA | `wama/common/utils/task_skeleton.py` | `WAMA_APP_GENERATION_ROUTE.md` | 8 |
| **Tests nocturnes** | Registre déclaratif de scénarios + runner sérialisé VRAM-aware (wired/ui/consistency/…). DEUX comptes de test déclaratifs : le standard (rôles métier, SANS tier dev — c'est LUI que la matrice de droits mesure) et `get_test_dev_user` pour les surfaces dev-gated (jumelles de bac à sable), routé par `ui_smoke._test_session_key(app)` — sans lui les 11 scénarios d'une jumelle skippent (mesuré 2026-08-30) | `wama/common/services/nightly_tests.py` | `PROJECT_STATUS.md §Tests fonctionnels nocturnes` | 16 |
| **Vocabulaire TTS partagé** | Le JEU DE CHOIX unique de la parole synthétique — moteurs, langues, presets de voix, cartes moteur↔langue — et sa résolution (voix pour une langue, langue d'une voix). Distinct du client de service : celui-ci TRANSPORTE, celui-là NOMME. Les deux apps TTS, `accounts` (langue de profil) et l'assistant y puisent les mêmes libellés | `wama/common/tts/constants.py` | — | 15 |

#### Modèles (12)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Auto-sélection (« auto » au select)** | Valeur « auto » d'un select de modèle : résolution AU LANCEMENT sur le domaine que le schéma déclare pour ses options (options_query), prévision affichée sous le select (options_auto) + curseur de QUALITÉ continu 0-100 (intent_param, poids dans le score de select_model) | `wama/common/utils/auto_model.py` | `WAMA_APP_GENERATION_ROUTE.md` | 15 |
| **Banc de comparaison** | Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation) | `wama/model_manager/services/bench.py` | — | 1 |
| **Benchmark tiers confronté** | Étage 2 qualité (a priori < benchmark < mesure) : AA + Elo Arena (texte, image, vidéo, VISION, document) + Open ASR (WER, sens 'bas') + MTEB (embeddings, jeu FRANÇAIS déclaré) appariés au catalogue, prospection incluse | `wama/model_manager/services/benchmark_sync.py` | `PROJECT_STATUS.md §REPRISE 2026-08-18` | 5 |
| **Cache HF scopé** | Bascule TEMPORAIRE du cache HuggingFace par backend — anti-fuite d'artefacts inter-apps | `wama/common/utils/hf_cache.py` | — | 1 |
| **Couverture multi-modèles** | Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation) | `wama/common/services/model_coverage.py` | — | 3 |
| **Découverte de modèles** | Découverte unifiée des modèles (apps + sources externes), synchronisée vers le catalogue AIModel | `wama/model_manager/services/model_registry.py` | — | 13 |
| **Indice de qualité a priori** | Ordonne les modèles autrement que par la taille (params EFFECTIFS √(totaux×actifs), contexte, quantif.) | `wama/model_manager/services/model_quality.py` | — | 1 |
| **Installation de modèles** | Pipeline accept→download→register : télécharge au bon endroit puis enregistre au catalogue | `wama/model_manager/services/model_installer.py` | — | 8 |
| **Prospection de modèles** | Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run) | `wama/model_manager/services/prospector.py` | `wama/model_manager/PROSPECTION_PIPELINE.md` | 10 |
| **Provenance de modèle** | Identité chez l'éditeur (licence, auteur, plateforme), posée VIA le manifeste | `wama/model_manager/services/provenance.py` | — | 5 |
| **Sonde vision** | Décrit une image via un modèle multimodal Ollama local (bench, smoke UI, fichiers de référence) | `wama/model_manager/services/vision_probe.py` | — | 5 |
| **Sélection de modèle** | Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité | `wama/model_manager/services/model_selector.py` | `INPUT_MODEL_MATCHING.md` | 7 |

#### Qualité & auto-amélioration (13)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Ajout au RAG (geste explicite)** | Bouton dans l'INSPECTEUR + page « Mon RAG » ; texte pris au schéma canonique, aucune ligne par app. Pas de balayage : l'entrée au RAG est un geste, par décision | `wama/common/static/common/js/wama-inspector.js` | `WAMA_MEMORY.md §7ter` | 28 |
| **Barre de filtrage** | Recherche + facettes EN DIRECT ; options dérivées du DOM (client) ou déclarées (server) | `wama/common/static/common/js/wama-filter-bar.js` | `CARD_DESIGN.md` | 14 |
| **Captation générique des gestes** | Middleware : telecharge/supprime/relance lus de resolver_match — zéro ligne par app | `wama/common/middleware.py` | `WAMA_MEMORY.md §7bis` | 2 |
| **Contrôle qualité de sortie** | Note une sortie par un validateur LLM INDÉPENDANT ; signal relatif, escalade humaine | `wama/common/utils/qc.py` | `ROADMAP.md §16.5` | ⚠ **0** |
| **Divergence inter-systèmes** | Désaccord entre deux sorties du même travail — signal objectif, sans avis de modèle | `wama/common/services/divergence.py` | `wama/transcriber/TRANSCRIBER_CORRECTION.md §8.3` | 1 |
| **Fuites de secrets** | gitleaks sur l'historique git COMPLET + vérifie que le hook pre-commit est en place et non dérivé : un hook mort est une garde silencieusement absente, donc rouge et pas warning | `wama/common/management/commands/check_secret_leaks.py` | `ROADMAP.md §16.10` | 2 |
| **Intégrité des gabarits** | Attrape la famille de fautes qui a récidivé SEPT fois : le commentaire `{# … #}` MULTI-LIGNE, que le lexer de Django (pas de re.DOTALL) rend en TEXTE littéral — et le nom de balise avaleuse écrit dans un commentaire. Un scan de 5 s contre des diagnostics qui ont coûté des sessions. Depuis le 01/09, signale AUSSI tout `{% load %}` vers une bibliothèque de balises absente (garde posée le jour où un retrait de templatetag a laissé son load — page reader en TemplateSyntaxError) | `wama/common/management/commands/check_templates.py` | `CLAUDE.md` | 2 |
| **Intégrité doc → code** | Vérifie que chaque chemin, ligne et renvoi .md cité par la doc ET par les skills existe encore ; gate nocturne sur les CIBLES distinctes, pas sur les références | `wama/common/management/commands/check_docs.py` | `CLAUDE.md §Fichiers de référence` | 8 |
| **Journal transversal de l'utilisateur** | Tout ce qu'il a lancé, toutes apps — DÉRIVÉ de detail_registry, aucune ligne par app | `wama/common/services/journal.py` | `WAMA_MEMORY.md §9bis` | 1 |
| **Mémoire & RAG** | Souvenirs + fragments sur pgvector, scope hérité de ScopedVisibility ; 5 opérations | `wama/common/memory/store.py` | `WAMA_MEMORY.md` | 11 |
| **Projection des faits en souvenirs** | RunOutcome → MemoryItem par OBJET (mécanique, sans modèle, idempotente) | `wama/common/memory/project.py` | `WAMA_MEMORY.md §7` | 2 |
| **Signaux d'exécution** | Journal append-only des FAITS observés sur un résultat (produit/corrigé/relancé…) | `wama/common/services/run_outcome.py` | `ROADMAP.md §16.7` | 3 |
| **Vulnérabilités des dépendances** | CVE des paquets INSTALLÉS du venv courant via l'API OSV.dev (pas les requirements, qui sont des bornes basses). Contrat-cliquet : la dette connue vit dans une baseline versionnée par venv, toute vulnérabilité nouvelle est rouge | `wama/common/management/commands/check_dep_vulns.py` | `ROADMAP.md §16.10` | 3 |

#### Contenu & prompts (13)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Accès LLM** | Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local) | `wama/common/utils/llm_utils.py` | — | 18 |
| **Appariement d'identité de canal** | Relie une identité Matrix/Discord à un compte WAMA par code prouvé hors canal — la garde que tout adaptateur appelle avant d'agir | `wama/gateway/services.py` | `ROADMAP.md §19` | 224 |
| **Claude Code sur abonnement** | Délègue une tâche de développement au CLI Claude Code en headless — lecture seule par défaut, environnement construit sans la clé API | `wama/common/services/claude_code.py` | `ROADMAP.md §19.3` | 4 |
| **Export document** | Génère PDF (fpdf2) / DOCX (python-docx) depuis les résultats d'app | `wama/common/utils/document_export.py` | — | 4 |
| **Garde des URL sortantes** | Valide toute cible de téléchargement pilotée par une saisie : schéma, identifiants, et adresses privées/bouclage/lien-local — anti-SSRF | `wama/common/utils/url_guard.py` | `PROFILES_PERMISSIONS.md` | 5 |
| **Générateur de QR codes** | Encode un texte/URL en PNG/SVG (segno, déterministe) — QR d'appariement de la passerelle aujourd'hui ; enrôlement TOTP et domaine Imager demain | `wama/common/utils/qr.py` | `ROADMAP.md §19` | 2 |
| **Historique de conversation (serveur)** | L'historique de l'assistant côté SERVEUR — remplace le localStorage web et le dict en mémoire de la passerelle (perdus au changement de navigateur / au redémarrage). COUCHE AU-DESSUS du moteur, jamais une dépendance : run_assistant_turn continue d'accepter un history explicite (moteur sans état, testable sans base). Consommé par la vue web ET la passerelle de canaux (gateway/core, discord_bot) — cf. ROADMAP §19.5 | `wama/common/services/conversation_store.py` | `ROADMAP.md §19.5` | 4 |
| **Ingest de source** | Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST | `wama/common/utils/source_ingest.py` | `WAMA_APP_GENERATION_ROUTE.md` | 14 |
| **Intake universel de fichiers** | Que peut faire WAMA de ce fichier ? — ports d'app + lot + manifeste + médiathèque + sondes des mondes (outil assistant inspect_user_file) | `wama/common/utils/intake.py` | `WAMA_LLM.md` | 4 |
| **Moteur de l'assistant IA** | Boucle agentique multi-surface (prompts, outils tool_api, local/cloud) — la vue web et /api/v1/assistant/chat/ en sont des clients | `wama/common/services/assistant_engine.py` | — | 9 |
| **Pipeline de prompts** | Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS | `wama/common/utils/prompt_enrichment.py` | `WAMA_LLM.md` | 21 |
| **Recherche & lecture web** | Recherche internet + page → texte plafonné (octets ET caractères) pour l'investigation de l'assistant (outils search_web/read_web_page) | `wama/common/utils/web_search.py` | `WAMA_LLM.md` | 4 |
| **Skills de rôle de l'assistant** | Posture et domaine de l'assistant (science, design, dev) + rappel du contexte de laboratoire, déclarés par domaine — distinct de l'enrichissement | `wama/common/utils/assistant_skills.py` | `ROADMAP.md §19.7` | 5 |

#### Manifestes & registres (8)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Adoption des mécanismes** | Qui consomme quoi (imports + briques front), niveau APP vs infrastructure, et jonction registre↔grille : mécanisme adopté par des apps que rien ne vérifie | `wama/common/services/mecanismes_scan.py` | `WAMA_MECANISMES.md` | 1 |
| **Audit des licences** | Vue dérivée : licences+auteurs des 4 registres, traversée par app. Ne voit PAS le code vendorisé (`static/vendors/`, codeformer) — inventorié à la main dans LICENSING.md §3 | `wama/common/services/license_audit.py` | `LICENSING.md` | 2 |
| **Bac à sable d'apps (jumelles exécutables)** | Jumelle <app>_NN coexistante pour comparaison Playwright + diff par témoins (route §10.3 marches S/S2) — registre sandbox_apps.json injecté au boot (INSTALLED_APPS/urls/gating/catalogue) ; create/drop symétriques + `substitute <label> <cible>` : remplace UN fichier copié par sa version GÉNÉRÉE (cibles = gabarits `codegen`), témoin `.temoin` préservé, re-mesure, auto-revert sur échec — verdicts journalisés au registre ; `revert <label> <cible>` ramène une cible au témoin à la demande. TROIS JUGES depuis le 03/09, chacun né d'un défaut qui RENDAIT (page 200) sans FONCTIONNER : ① cohérence de paquet par AST (tout `from .x import Y` intra-paquet, imports PARESSEUX compris, doit résoudre) ; ② couple views↔templates (substituer les templates seuls = boutons morts) ; ③ smoke « file HABITÉE » (témoin créé→page rendue→supprimé : une file vide ne rend AUCUNE card, donc ne teste rien du rendu de card). Le gate d'acceptation d'une jumelle reste sa BATTERIE UI auto-dérivée (11 scénarios `<label>.*` du registre nocturne) : describer_01 = 11/11 | `wama/common/sandbox.py` | `WAMA_APP_GENERATION_ROUTE.md` | 11 |
| **Formats de sortie** | Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire converter) | `wama/common/utils/output_formats.py` | — | 6 |
| **Gabarits de génération d'app (marches S2 + B1)** | Rend le code CONVENTIONNEL d'une app depuis son manifeste — une cible par fichier (apps/urls/models/params/tasks/views/templates), consommées par `app_sandbox substitute` et le write-back ; le hors-convention reste un TROU NOMMÉ (stubs 501, commentaires [manifest-gen]), jamais un manque silencieux. Depuis le 02/09 (marche B1 CLOSE), le corps des TÂCHES se COMPOSE aussi : `backends/__init__.ROUTES` de l'app (nature → callable au contrat commun) monte au manifeste (processing.backend_routes) et tasks_gen émet l'appel — import relatif au paquet, la jumelle a CONVERTI (SUCCESS mesuré). DEUX SAVEURS depuis le 03/09 (2ᵉ app routée, describer) : `RESULT` déclare ce que les backends produisent — 'file' (le backend écrit output_path) ou 'text' (il REND le texte, la tâche le persiste dans la colonne déclarée et publie l'aperçu partiel) ; `NATURE_FIELD` nomme la colonne de nature. ⚠ Un fichier substitué doit exposer TOUT ce que les fichiers COPIÉS lui importent : params_gen émet l'alias `<X> = <X>_JSON` (le models copié importe la graphie courte — ImportError au rendu de CHAQUE card sinon) | `wama/common/manifests/codegen/templates_gen.py` | `WAMA_APP_GENERATION_ROUTE.md` | 5 |
| **Grille de conformité** | Mesure les 8 facettes F1–F8 des apps par analyse du code réel | `wama/common/services/conformity_checker.py` | `WAMA_APP_CONVENTIONS.md` | 4 |
| **Manifestes** | Extraction/validation/projection des 7 kinds vers les registres | `wama/common/manifests/ingest.py` | `WAMA_MANIFEST_ARCHITECTURE.md` | 58 |
| **Vivier des backends (registre DÉRIVÉ)** | Inventaire des moteurs de WAMA, dérivé À CHAQUE AFFICHAGE des déclarations `wama/<app>/backends/` (ROUTES/RESULT/NATURE_FIELD + classes BaseModelBackend trouvées jusque dans les SOUS-MODULES) recoupées au catalogue AIModel. Deux usages : la vision d'ensemble (12ᵉ registre, page /common/backends/) et le VOISINAGE que le LLM de la marche B trie pour s'inspirer du backend le plus approchant (signature « natures → saveur », paquets, VRAM, modèles servis). Ne stocke RIEN et n'a pas de rafraîchisseur — une page qui DÉRIVE ne peut pas diverger de ses sources. Ne cite aucune app : il parcourt les apps installées (le registre ne connaît jamais ses producteurs). ⚠ Fait MESURÉ le 03/09 : `AIModel.backend_ref` porte un nom d'APP, pas de backend — le rattachement est donc « déduit de l'app » et la page le DIT ; le compteur « lien fin déclaré » (0) est la mesure du chantier restant | `wama/common/services/backend_inventory.py` | `WAMA_APP_GENERATION_ROUTE.md` | 5 |

#### File d'attente & lots (14)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Console utilisateur** | Lignes de journal structurées par utilisateur et par app. ⚠ Annoncé « via Redis », mais le chemin Redis exige `django_redis` — ABSENT des deux venvs et des `requirements` (vérifié 2026-08-22) : la console tourne DEPUIS TOUJOURS sur son repli cache, qui fonctionne mais n'est pas atomique (lire/insérer/réécrire, donc des lignes perdues quand gunicorn et les workers Celery poussent en même temps). Le correctif n'est PAS d'ajouter la dépendance : le client `redis` brut est déjà installé et la brique d'accès existe (`resource_governor._redis`, via `CELERY_BROKER_URL`) | `wama/common/utils/console_utils.py` | — | 32 |
| **Dossier de travail jetable** | Les fichiers INTERMÉDIAIRES d'un traitement ne vivent pas dans `media/`. Mesuré le 2026-08-25 : `media/avatarizer/` pesait 1,69 Go pour 2101 fichiers dont 99,6 % de PNG — les frames de CodeFormer, écrites dans le dossier de sortie du job et jamais nettoyées ; `job_11` portait 1715,7 Mo pour une vidéo de 0,70 Mo. `media/` ne contient que `<app>/<user>/input|output/` et `users/` (MEDIA_STORAGE_TIERING.md) : un fichier de travail y est sauvegardé par le miroir, compté par le tiering et servi par Apache pour rien. Le `with` rend le nettoyage STRUCTUREL au lieu d'être une convention qu'on oublie. ADOPTÉ par 5 sites (avatarizer/codeformer, describer/views, enhancer/views, reader/glm_ocr, describer/video_describer) ; reste `enhancer/tasks.py:534`, déjà nettoyé sur les deux chemins, dont le portage est une restructuration d'une fonction GPU de 200 lignes. ⚠⚠ L'audit AUTOMATIQUE des `mkdtemp` a mal classé 2 sites sur 6 — `glm_ocr` déléguait par contrat DOCUMENTÉ, `enhancer/tasks` nettoyait déjà — mais la lecture site par site a trouvé l'inverse, des fuites qu'aucun motif ne voyait : un `rmdir` conditionné à « si le dossier est vide » qui ne se déclenchait donc jamais, un nettoyage placé APRÈS l'appel qui sautait sur exception, et un `except ImportError` qui empêchait un repli d'exister. Un relevé par motif oriente ; il ne conclut pas. Porte aussi `purge_job_dir` : la suppression d'une card doit emporter le dossier du job — 13 dossiers `job_*` orphelins relevés contre 4 rattachés | `wama/common/utils/work_dir.py` | `MEDIA_STORAGE_TIERING.md` | 55 |
| **Duplication et suppression sûres** | duplicate_instance() et safe_delete_file() — fichiers partagés entre items | `wama/common/utils/queue_duplication.py` | `WAMA_APP_CONVENTIONS.md` | 18 |
| **Entrée de file (card seule OU lot)** | Décide, pour une entrée de file, si elle s'affiche en card unique ou en card MÈRE avec ses filles repliables — et rend l'un ou l'autre. Le bloc vivait recopié À L'IDENTIQUE dans les gabarits d'app (10 au dernier compte — le partial fait foi) ; il n'a pu être centralisé (2026-08-25) qu'une fois deux verrous levés : `is_unitary` adopté (la décision se lit sur le modèle) et `elem` (les cards filles reçoivent leur élément sous le MÊME nom — avant, 8 graphies). Signature à 3 paramètres : `card_template`, plus `collapse_prefix` et `batch_key` pour la seule app à deux files sur une page (enhancer audio). ⚠ Tout le reste TRAVERSE PAR LE CONTEXTE — les ~9 paramètres de `_batch_card.html` sont fournis par l'app et passent au travers, sinon la signature atteindrait la quinzaine. Apparence uniformisée sur le TRANSCRIBER (référence), conforme à `CARD_DESIGN §11.2` (famille de lot = cyan #0dcaf0) : les 3 couleurs et 2 habillages qui coexistaient étaient des séquelles d'implémentations successives | `wama/common/templates/common/_queue_entry.html` | `CARD_DESIGN.md §11.2` | 235 |
| **File d'attente (front)** | Comportements communs des files : collapse de batch persisté, mode Solitaire (accordéon), toggle Ligne/Mosaïque, les 3 densités et le modificateur PILE (CARD_DESIGN §11.4/§11.9), focus card, clearCards, data-wama-* | `wama/common/static/common/js/wama-queue.js` | `CARD_DESIGN.md` | 81 |
| **Glisser-déposer et sélection multiple de la file** | Les QUATRE gestes de manipulation directe, hérités par les 12 apps sans qu'aucune n'écrive une ligne : déposer SUR une card change l'APPARTENANCE (entrer dans un lot / en former un), déposer ENTRE deux cards change l'ORDRE (file ou lot) ; sélection multiple clic/Ctrl/Maj, qui EST celle de l'inspecteur (une seule sélection dans WAMA — la brique ANNONCE `wama:selection-change`, l'inspecteur REND). Auto-monté sur `[data-wama-dnd]`, posé par le templatetag `queue_dnd_attrs` : une app qui ne le pose pas garde une file strictement inerte. SortableJS écarté (multi-sélection + fusion sur une card + règle « pas de CDN ») | `wama/common/static/common/js/wama-queue-dnd.js` | `CARD_DESIGN.md §3bis` | 3 |
| **Historique annuler / rétablir** | Deux piles + plafond + état des boutons + raccourcis Ctrl+Z / Ctrl+Maj+Z / Ctrl+Y. PORTABLE parce que la machinerie ne touche JAMAIS le modèle : elle ne le connaît que par `snapshot()` et `restore(state)`, que l'appelant fournit. La coalescence des rafales de frappe (`burstWindow`) est une OPTION, pas un acquis — elle n'a aucun sens sur un éditeur non textuel, où chaque mutation est déjà atomique. ⚠⚠ La FILE D'ATTENTE ne peut PAS l'utiliser : ses gestes sont commis côté serveur à l'instant du dépôt, il n'y a pas de modèle client à photographier — son « annuler » est un REJEU D'OPÉRATION INVERSE, même mot, mécanisme différent. Les réunir ici donnerait une API qui MENT sur ce qu'elle garantit. DEUX consommateurs, et deux façons de marquer un cran — c'est l'ADOPTION qui l'a révélé : `push()` AVANT la mutation (transcriber, qui marque en tête de chaque opération) et `commit()` APRÈS (studio, dont les 9 opérations passent par UN entonnoir, `persistDraft`). La v1 n'offrait que `push()` : suffisant pour le consommateur dont elle sortait, insuffisant pour le suivant. `silence(fn)` couvre le chargement programmatique, et la garde de RÉ-ENTRANCE vit dans la brique — restaurer c'est muter (`loadGraph`→`clearCanvas`→`removeNode`→l'entonnoir), donc tout consommateur à entonnoir remplirait son historique de son propre travail | `wama/common/static/common/js/wama-history.js` | `CARD_DESIGN.md` | 6 |
| **Import par lot** | Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot | `wama/common/utils/batch_parsers.py` | `BATCH_FORMAT.md` | 62 |
| **Intégrité des médias** | Audit MESURÉ de `media/` en 4 états : RÉFÉRENCÉ (une ligne de base pointe dessus), orphelin, RÉSIDU DE TEST, et RÉFÉRENCÉ MAIS ABSENT — ce dernier étant celui que personne ne voyait : au 2026-08-25, **33 lignes de base pointent vers des fichiers inexistants**, et un téléchargement ou un aperçu y échoue sans rien dire. Signale aussi les fichiers ÉGARÉS hors des emplacements légitimes. ⚠⚠ La méthode exige DEUX signaux indépendants, jamais le nom seul : « orphelin » seul désignait 3447 fichiers sur 3779 (les sorties de workers ne passent pas par un FileField), et le nom seul aurait emporté le dépôt manuel d'une utilisatrice. ⚠ Un kind de manifeste `media` a été ÉCARTÉ : `manifests/` est versionné alors que `media/` porte des données personnelles, et un export serait périmé au moindre dépôt — un contrôle toujours rouge ne protège plus rien | `wama/common/management/commands/check_media_integrity.py` | `MEDIA_STORAGE_TIERING.md` | 1 |
| **Manipulation directe de la file** | Endpoints génériques : sortir une card d'un batch, réordonner DANS un lot, ordonner la FILE (`reorder_queue`, 2026-09-04), déplacer, FUSIONNER (`merge`) et consolider. ⚠ `merge` ≠ `consolidate` : le premier fusionne en UN lot et REFUSE si les natures ne cohabitent pas (geste du drag&drop, on a visé une card) ; le second RANGE par nature en N lots (chemin d'import) et 5 apps le redéfinissent. La compatibilité n'est pas redéclarée : `group_key` reçoit la MÊME fonction que le `nature_of` de l'import (vérifié par AST, tests_queue_dnd) | `wama/common/utils/queue_manipulation.py` | `CARD_DESIGN.md §3bis` | 14 |
| **Nom du fichier de sortie** | Une règle unique pour les 8 apps à liaison PRÉCOCE, en deux familles : entrée FICHIER → `<stem>_<process>_<modèle>[_<i>]<ext>` (l'utilisateur retrouve SON nom, augmenté de ce qu'on lui a fait et avec quoi) ; entrée PROMPT → `<process><id>_<modèle>[_<i>]<ext>` (l'identifiant de card remplace le nom absent et garantit l'unicité dans un `output/` PLAT). Le suffixe `_<i>` n'apparaît QUE si la card produit plusieurs fichiers — cas réel : `imager.num_images` va de 1 à 4. ⚠ Le mot de process est DÉCLARÉ (`APP_CATALOG['output_tag']`), plus écrit en dur dans chaque tâche (`blurred`, `enhanced`, `gen`… étaient invisibles à tout relevé et impossibles à changer sans toucher chaque app). ⚠ `output/` reste PLAT : c'est le NOM qui porte l'unicité, pas un sous-dossier par card — ce dernier est précisément ce qui a été démonté le 2026-08-25 (`job_<id>/`, 1,7 Go) | `wama/common/utils/output_naming.py` | `MEDIA_STORAGE_TIERING.md` | 8 |
| **Notifications de tâche** | notify_job() — fin de traitement, succès comme échec | `wama/common/utils/notifications.py` | `PROFILES_PERMISSIONS.md` | 12 |
| **Ordre MANUEL de la file** | Position de l'entrée de file décidée par l'utilisateur (`QueueOrderMixin.queue_index`, 13 modèles de batch) + 6ᵉ tri « Manuel » — le SEUL tri qui LIT une colonne au lieu de la calculer. `queue_index == 0` = jamais ordonné à la main, et passe EN TÊTE par récence : une file jamais manipulée s'affiche comme en tri `recent`, et un import arrivé après un classement manuel apparaît en haut au lieu de se noyer dans un ordre qu'il n'a pas connu. `reorder_queue` écrit 1..N | `wama/common/models.py` | `CARD_DESIGN.md §3bis` | 237 |
| **Tri/filtrage de la file** | Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps | `wama/common/utils/queue_view.py` | `CARD_DESIGN.md` | 16 |

#### UI générée (22)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Bouton de cycle** | Bouton commun ▶/⏹/↻ toujours vert — l'icône porte l'action, l'état vit sur la card | `wama/common/static/common/js/wama-cycle-button.js` | — | 27 |
| **Cache-busting statique** | `{% static_v %}` = `{% static %}` + `?v=<mtime>` : le navigateur re-télécharge un fichier statique dès qu'il change, le garde en cache sinon | `wama/common/templatetags/wama_static.py` | — | 32 |
| **Card v3** | Dimensionnement déclaratif des pistes de card — dépend de l'app, des actions, des libellés (l'autre moitié vécue de la v3 — densités, pile — vit au front de file : queue_front, qui appelle WamaCardV3.measure) | `wama/common/static/common/js/wama-card-v3.js` | `CARD_DESIGN.md §11` | 6 |
| **Card « Nouvel élément »** | Card d'entrée dépliable commune — les 6 modalités du partial : dépôt, URL, médiathèque, lot, dossier, live + slot de référence typé (extra_zone) — auto-init | `wama/common/static/common/js/wama-new-item-card.js` | `MODES_QUEUE_UX.md` | 31 |
| **Chips méta des cards** | Chips des cards GÉNÉRÉS du schéma params (chip=True), groupés par section v3 (chips_by_section) ; `values` pour les réglages vivant en JSON (même assiette que card_gear), `extra` pour les chips d'app déjà formés. Porte aussi les réglages COMMUNS aux filles pour la card MÈRE (common_chips_for_items + partial _batch_meta_chips — slot meta_template, généralisation du pilote transcriber, porté aux 10 apps le 31/08) et les propriétés d'ENTRÉE (input_props_for, extraite du pilote reader) | `wama/common/utils/card_chips.py` | `CARD_DESIGN.md §10.3` | 48 |
| **Domaines → modes** | Schéma déclaratif des onglets-domaine et modes par app — scope la file | `wama/common/utils/app_modes.py` | `MODES_QUEUE_UX.md` | 14 |
| **Déclaration du volet par la page** | Une page DÉCLARE les sections du volet droit qu'elle garde (retrait, jamais ajout) ; sans déclaration, l'état d'avant — les apps n'écrivent rien (context processor volet_defaut) | `wama/common/utils/volet.py` | `WAMA_VOLETS.md §8` | 9 |
| **Formats de téléchargement (⬇ late-binding)** | Vocabulaire commun des formats choisis AU TÉLÉCHARGEMENT (libellé, icône, groupe) + split-button dérivé de la déclaration export_binding — pendant late-binding d'output_formats ; 6ᵉ action de card | `wama/common/utils/export_formats.py` | `WAMA_APP_CONVENTIONS.md §6.3` | 12 |
| **Import de dossier récursif** | Traversée récursive d'un drop/webkitdirectory — brique F2 montée globale (base.html) | `wama/common/static/common/js/wama-folder-import.js` | `WAMA_APP_GENERATION_ROUTE.md` | 2 |
| **Inspecteur contextuel (volet droit)** | Trois étages (card / lot / file) : sélection → Infos + preview + actions clonées (cloneActions) + PARAMÈTRES reflétés (initFromSchema : panel read/apply dérivés du schéma, cardSettings via card_gear) ; hydrate aussi les previews de card (hydrateCardPreviews) | `wama/common/static/common/js/wama-inspector.js` | `WAMA_VOLETS.md` | 31 |
| **Inspecteur — champs de détail** | Schéma canonique des infos d'item affichées au volet droit | `wama/common/utils/detail_registry.py` | `INSPECTOR_DETAIL_FIELDS.md` | 54 |
| **Lecteur audio (onde + transport)** | Widget autonome : onde canvas (pics serveur ou décodés), play/pause, exclusivité inter-lecteurs et inter-onglets ; monté par la preview dans le volet ET les cards | `wama/common/static/common/js/wama-audio-player.js` | — | 6 |
| **Preview unifiée** | Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps | `wama/common/utils/preview_registry.py` | — | 49 |
| **Progression & ETA (front)** | Moteur ETA par débit observé + barres aux 3 niveaux : card, batch, globale | `wama/common/static/common/js/wama-eta.js` | `PROJECT_STATUS.md §10` | 53 |
| **Schéma de paramètres** | Source unique des réglages d'app : volet droit, modales (item ET lot, `context`) et DÉFAUTS APPLICABLES d'un élément naissant (applicable_defaults, filtre show_if au vocabulaire du moteur JS) sont dérivés de lui. Depuis le 01/09 il porte AUSSI LA cascade des valeurs effectives (effective_settings : défauts du schéma ← preset ← réglages POSÉS — formulation Fabien, ROADMAP §23.2bis) : la base ne stocke que le POSÉ (vide = « le preset décide »), les défauts restent au schéma — c'est ce qui rend un preset POSSIBLE, et ce qui a remplacé resolve_options du converter + les défauts en dur des backends | `wama/common/utils/param_schema.py` | `WAMA_APP_GENERATION_ROUTE.md` | 62 |
| **Shuttle J/K/L** | État de vitesse/direction de lecture (paliers éditeur) + binding clavier ; l'app fournit apply(speed) — la commande est commune, l'application au lecteur reste locale | `wama/common/static/common/js/wama-shuttle.js` | — | 3 |
| **Signalement au gestionnaire de fichiers** | Noms d'événements centralisés (media:uploaded/processed/deleted) — l'arborescence du filemanager se rafraîchit sans que chaque app invente son event | `wama/common/static/common/js/wama-fm-notify.js` | — | 2 |
| **Socle JS des apps** | Plomberie commune file/cards : csrfFetch, urls, Poller de progression, états vides | `wama/common/static/common/js/wama-app-base.js` | `WAMA_APP_GENERATION_ROUTE.md` | 22 |
| **Sélecteur de médiathèque** | Modale commune de choix d'un asset de la médiathèque (filtrée par type), rendue à l'appelant sous forme de File + méta | `wama/common/static/common/js/media-picker.js` | — | 4 |
| **Vocabulaire des capacités** | Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI | `wama/common/utils/model_capabilities.py` | `INPUT_MODEL_MATCHING.md` | 30 |
| **Voie d'import (front)** | Envoi d'un fichier vers l'endpoint upload de l'app (dépôt, clic — la médiathèque y ARRIVE par la card d'entrée, qui injecte le fichier dans le même input), délégation du LOT à batch_import, consolidation et rafraîchissement — agnostique du monde (ni MIME ni extension) | `wama/common/static/common/js/wama-import.js` | `WAMA_APP_GENERATION_ROUTE.md` | 5 |
| **data-* du gear ⚙ des cards** | data-* du ⚙ DÉRIVÉS du schéma (contrat cardSettings de l'inspecteur, qui lit la RACINE de card PUIS le bouton) — schéma en objets Param OU en dicts (chemin des vues générées) ; booléens 'true'/'false', tous les params item émis (anti-résidus) | `wama/common/utils/card_gear.py` | — | 16 |

#### Données & infrastructure (25)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **Abonnement aux éléments de catalogue** | PRÉFÉRENCE d'affichage, appliquée APRÈS le droit et seulement à l'affichage : elle ne peut que RESTREINDRE ce à quoi l'utilisateur a déjà accès. Seules les EXCEPTIONS sont stockées (se réabonner efface la ligne) ; une nature d'élément s'ajoute par une entrée dans KINDS, et la page de catalogue hérite du mécanisme par deux attributs (`data-abo`, `data-abo-toggle`). Son PÉRIMÈTRE est celui du DROIT, pas d'APP_CATALOG : les surfaces transversales et Lab (extra_links) se masquent par la même clé `gate` que celle dont accessible() décide (§8.8.1) | `wama/common/services/subscriptions.py` | `PROFILES_PERMISSIONS.md` | 5 |
| **Accès aux éléments (apps aujourd'hui)** | Décide seul qui voit quel élément, sur DEUX axes qui se cumulent : le TIER du compte (anonymous < utilisateur < developpeur < admin, tranche en premier) et les RÔLES métier (groupes `role:*`, intersection avec la politique de l'app). Le compte de service `anonymous` y est FERMÉ par code, pas par état de base. Signature GÉNÉRALE depuis S2 — accessible(user, kind, element_id) : chaque FAMILLE d'élément déclare dans KIND_DECISION qui décide pour elle, un kind inconnu LÈVE, et une décision unique ne garde que ce que ses POINTS D'APPLICATION lisent réellement (§8.9) | `wama/accounts/permissions.py` | `PROFILES_PERMISSIONS.md` | 25 |
| **Accès ffmpeg** | Résolution centralisée du binaire et des conversions (échappatoire FFMPEG_BINARY) | `wama/common/utils/ffmpeg_utils.py` | — | 16 |
| **Accès scopé aux objets** | Deux chemins NOMMÉS pour lire un objet partageable depuis une vue (possédé / visible) | `wama/common/utils/scoping.py` | `PROFILES_PERMISSIONS.md` | 12 |
| **Actualisation des catalogues** | REGISTRE des registres : une page catalogue déclare la CLÉ de son registre et hérite du bouton, de l'endpoint, de la permission et du compte-rendu. La NATURE déclarée (scan / mesure / re-déclaration / DÉRIVÉ) décide du rendu — un dérivé affiche « toujours à jour » au lieu d'un bouton qui ne ferait rien — ET le LIEU d'exécution : état partagé → tâche Celery non bloquante, registre en mémoire → sur place, avec propagation aux autres workers gunicorn | `wama/common/registries.py` | — | 13 |
| **Arbre organisationnel depuis l'annuaire** | ou=structures (SUPANN) → OrgUnit + parents ; peuple ce dont dépend le partage par unité (RAG labo, médiathèque). Lecture seule côté LDAP, idempotente | `wama/accounts/management/commands/sync_org_units.py` | `PROFILES_PERMISSIONS.md` | 1 |
| **Bascules de fonctionnalités** | Registre de Feature par app + surcharges JSON de l'objet porteur — comparer AVEC/SANS | `wama/common/utils/feature_flags.py` | — | 1 |
| **Chemins média** | Emplacements canoniques des entrées/sorties par app et par utilisateur | `wama/common/utils/media_paths.py` | — | 27 |
| **Décodage audio robuste** | Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg. Annexe torchaudio_compat = l'autre forme du même problème : shims soundfile posés DANS torchaudio pour les libs tierces qui l'appellent en interne (Coqui, DeepFilterNet) | `wama/common/utils/audio_decode.py` | — | 5 |
| **Importer universel (WAMA Data)** | REGISTRE de capacités de lecture — aucun format privilégié : ajouter un format = déposer un lecteur, jamais éditer le moteur. Porte aussi l'HORODATAGE par flux (dont le ré-horodatage par fréquence théorique, qui n'interpole rien et ne s'applique que sur demande). ⚠ La MÉCANIQUE SQLite (ouverture en lecture seule, décodage UTF-8→cp1252 du texte des bases MATLAB, valeurs triées, les trois niveaux d'agrégation) est un socle partagé — un lecteur de base concret n'écrit plus que `can_read`, `probe` et `read`, c'est-à-dire sa seule connaissance du schéma | `wama_data/sources/__init__.py` | `WAMA_DATA_WORLD.md §6.6, §9terdecies` | 3 |
| **Noms dérivés (WAMA Data)** | DOMICILE UNIQUE de la règle « le nom se DÉRIVE des paramètres, il ne se saisit pas » : deux productions de mêmes réglages portent le même nom, deux réglages différents ne peuvent pas le partager. Elle était appliquée par QUATRE règles dans TROIS lieux — dont une f-string écrite en dur — avant l'audit du 23/08. Les anciens emplacements réexportent ; un test vérifie l'IDENTITÉ des fonctions, donc une redéfinition locale même à l'identique échoue. Sans dépendance, par nécessité : c'est ce qui permet à `conditions.py` de l'importer sans cycle | `wama_data/core/naming.py` | `WAMA_DATA_WORLD.md §9ter.6 B7, §9sexies.4` | 20 |
| **Pont référentiel ↔ cadres typés (WAMA Data)** | SEULE frontière entre les deux vocabulaires du monde Data : le référentiel (paresseux, indexé, sans pandas) et le `TypedFrame` que mangent toutes les fonctions du catalogue. Sans lui le référentiel n'avait AUCUN consommateur — non parce qu'on ne s'en servait pas, mais parce qu'on ne POUVAIT pas. Traite quatre pièges mesurés : le temps de SESSION (± offset) vs le temps local du flux, la colonne temporelle brute PÉRIMÉE après ré-horodatage, le contrat `rows` réel mais non déclaré, et la PROVENANCE — ce qui revient d'un calcul ne peut pas se déclarer acquis (`is_base=False` sans échappatoire) | `wama_data/frames.py` | `WAMA_DATA_WORLD.md §9quater.7` | 5 |
| **Référentiel temporel (WAMA Data)** | Aligne des flux à cadences INCOMMENSURABLES et répond aux questions temporelles : quel échantillon à t, quels segments le contiennent, quel événement suit, et la vue DÉCIMÉE (min/max par tranche) sans laquelle aucun tracé n'est viable. N'interpole jamais : la valeur rendue est toujours un échantillon existant | `wama_data/core/temporal.py` | `WAMA_DATA_WORLD.md §2-§3` | 17 |
| **Réglages utilisateur par app** | Persistance cache user_{id}_{app}_{clé} avec défauts déclarés par l'app | `wama/common/utils/user_settings.py` | — | 12 |
| **Rétention des médias** | Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts) | `wama/common/services/retention.py` | `PROFILES_PERMISSIONS.md` | 2 |
| **Sauvegarde & tirage** | Moteur unique de miroir (modèles, base, médias, secrets) et restauration | `wama/common/services/mirror_sync.py` | — | 8 |
| **Sonde média** | Durée/codec/dimensions/pages d'un média pour les propriétés de card (via ffmpeg_utils) | `wama/common/utils/media_probe.py` | — | 4 |
| **Sources externes** | Registre DÉCLARATIF de ce que WAMA joint au dehors : adresse, réglage qui la surcharge, variable portant la clé d'API, attribution exigée par la licence, et surtout la PORTÉE (service local ou Internet) — d'où le traitement du proxy est DÉRIVÉ au lieu d'être choisi à la main par chaque appelant. Ajouter une plateforme = une entrée. ⚠ Ne déclare JAMAIS le client : chaque source a sa forme (JSON authentifié, parquet, HTML scrapé), le parseur reste chez le consommateur. ⚠ Ne couvre pas les connecteurs `media_library`, dont la clé est une donnée PAR UTILISATEUR en base — les y rapatrier uniformiserait ce qui n'est pas pareil | `wama/common/external_sources.py` | `PROJECT_STATUS.md` | 27 |
| **Taxonomie des natures & vocabulaire d'entrée** | Source UNIQUE des natures de média (image/video/audio/document/archive/dataset/3d — `text` RETIRÉ le 2026-08-30, arbitrage §S2bis.6bis : les fichiers texte sont des documents, la saisie est le jeton de RÔLE `prompt`) : détecte la nature d'un nom de fichier (`category_of_path`, défaut 'document') et normalise un vocabulaire (`normalize_types`) ; un MONDE pousse ses extensions par `register_category_extensions` (dataset ← sonde wama_data), jamais en dur. Porte AUSSI la déclaration par app de ce qu'elle accepte — `input_types` (les natures) et `input_extensions` (les extensions) — d'où le manifeste tire `body.ports.inputs[].types` et `body.identity.input_extensions`, l'axe UX ses `accepts` de domaine, le gabarit généré son `accept=` de dropzone, et la vue générée sa dérivation de nature CONTRAINTE au vocabulaire déclaré | `wama/common/app_registry.py` | `WAMA_APP_GENERATION_ROUTE.md` | 6 |
| **Taxonomie des types de donnée** | Vocabulaire commun des sources et des fonctions : sous-typage + compatibilité de ports. `segments` y est LE type « portion de temps bornée » (situation, état, section) | `wama/common/catalog/data_types.py` | `WAMA_DATA_FUNCTION_CARDS.md §3` | 47 |
| **Unités d'affichage** | Moteur UNIQUE de conversion d'unités pour la PRÉSENTATION (pint) : la donnée reste dans SON unité (`WamaVariables.unit`, `ParamSpec.unit`), la préférence utilisateur (métrique/impérial) ne convertit qu'à l'écran — résolution par DIMENSION, une unité inconnue reste affichable — et un export qui convertit doit le DIRE. Un trou de donnée traverse en trou (None), jamais en valeur | `wama/common/utils/units.py` | `WAMA_DATA_WORLD.md §10 D27` | 2 |
| **Utilitaires vidéo** | Extraction audio des vidéos + téléchargement YouTube/yt-dlp | `wama/common/utils/video_utils.py` | — | 17 |
| **View-model d'exploration (WAMA Data)** | Une VUE déclare ce qu'on regarde — flux, fenêtre, résolution, colonnes dérivées — et rien de plus : sérialisable en JSON, donc rejouable et diffable, et on persiste ELLE plutôt que les valeurs (une colonne matérialisée se périme sans le dire). Rend EXÉCUTABLE la règle « une nouvelle table SSI la clé temporelle change » en la DÉRIVANT de la `FunctionCategory` : ajouter une fonction au catalogue la range du bon côté sans toucher le view-model. La séparation tables/annexes rend la règle visible à l'écran au lieu d'avoir à l'expliquer | `wama_data/view.py` | `WAMA_DATA_WORLD.md §9quater.4, §9quater.7` | 19 |
| **Visibilité et portée** | Privé / unité / public : filtrage des lectures, mutations inchangées | `wama/common/models.py` | `PROFILES_PERMISSIONS.md` | 28 |
| **Écrivain de conteneur (WAMA Data)** | UN MOTEUR, N SCHÉMAS — le pendant exact du registre de lecteurs, et le premier code du monde Data qui ÉCRIVE du SQLite (0 `INSERT` dans tout le monde avant lui). Le moteur tient la transaction, les tranches, l'indexation temporelle et la conversion des valeurs ; un schéma ne décide que des NOMS et du CATALOGUE — c'est ce qui garantit que `.wdat` (natif, D3) et `.trip` (compatibilité BIND) se comportent pareil là où ils le doivent. Écrit d'abord un `.partiel` puis renomme : un conteneur à moitié rempli s'ouvrirait normalement en mentant sur son contenu. ⚠ CE QUE LE SCHÉMA CIBLE NE SAIT PAS PORTER EST COMPTÉ, pas tu (`Rapport.pertes`) — une conversion qui appauvrit en silence fait croire à un aller-retour fidèle. La compatibilité est attestée par CONTRE-ÉPREUVE : ce que WAMA écrit, le lecteur `.trip` — écrit contre le format de l'autre, sans rien savoir de l'écrivain — le relit | `wama_data/containers/__init__.py` | `WAMA_DATA_WORLD.md §9quater.2, §9duodecies` | 2 |

#### Studio & surface d'outils (API) (3)

| Mécanisme | Rôle | Domicile | Doc de référence | Consommateurs |
|---|---|---|---|---|
| **API REST v1** | Passerelle générique (token+session) sur TOOL_REGISTRY : lister/exécuter, gating F7 à l'annonce ET à l'exécution | `wama/api/v1/views.py` | — | 3 |
| **Runner générique du studio** | Exécute une app par son CONTRAT (triade tool_api normalisée) — zéro logique par app | `wama/studio/services/generic_runner.py` | `STUDIO_VISION.md` | 7 |
| **Surface d'outils** | Registre central TOOL_REGISTRY : triades add/start/status par app, gating F7 via execute_tool, descriptions dérivées des schémas | `wama/tool_api.py` | `WAMA_APP_GENERATION_ROUTE.md` | 12 |

**Mécanismes déclarés : 122** · domiciles absents : 0 · sans consommateur : 1 · assumés locaux : 17 · modules balayés non rattachés : 2 · **de niveau app sans critère de grille : 33**
- ⚠ **Sans consommateur** (brique morte ou pas encore adoptée) : `qc` (wama/common/utils/qc.py)

<details><summary>⚠ <b>33 mécanisme(s) de niveau app SANS critère de grille</b> — adoptés par des apps, vérifiés par aucun critère (<code>Criterion.mecanisme</code>) : une app peut sortir à 100 % sans les avoir adoptés</summary>

| Mécanisme | Adopté par | Domicile |
|---|---|---|
| `data_vue` — View-model d'exploration (WAMA Data) | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama_data/view.py` |
| `gateway_identity` — Appariement d'identité de canal | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/gateway/services.py` |
| `inspector` — Inspecteur contextuel (volet droit) | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/static/common/js/wama-inspector.js` |
| `media_paths` — Chemins média | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/utils/media_paths.py` |
| `queue_order` — Ordre MANUEL de la file | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/models.py` |
| `rag_geste` — Ajout au RAG (geste explicite) | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/static/common/js/wama-inspector.js` |
| `static_versioning` — Cache-busting statique | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/templatetags/wama_static.py` |
| `work_dir` — Dossier de travail jetable | **10** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber | `wama/common/utils/work_dir.py` |
| `manifests` — Manifestes | **9** app(s) : anonymizer, avatarizer, composer, converter, describer, enhancer, imager, synthesizer, transcriber | `wama/common/manifests/ingest.py` |
| `data_noms` — Noms dérivés (WAMA Data) | **7** app(s) : anonymizer, avatarizer, composer, converter, enhancer, imager, synthesizer | `wama_data/core/naming.py` |
| `notifications` — Notifications de tâche | **7** app(s) : anonymizer, avatarizer, composer, enhancer, imager, synthesizer, transcriber | `wama/common/utils/notifications.py` |
| `output_naming` — Nom du fichier de sortie | **6** app(s) : avatarizer, composer, converter, enhancer, imager, synthesizer | `wama/common/utils/output_naming.py` |
| `auto_model` — Auto-sélection (« auto » au select) | **5** app(s) : anonymizer, avatarizer, composer, imager, synthesizer | `wama/common/utils/auto_model.py` |
| `export_formats` — Formats de téléchargement (⬇ late-binding) | **5** app(s) : anonymizer, describer, imager, reader, transcriber | `wama/common/utils/export_formats.py` |
| `ffmpeg` — Accès ffmpeg | **5** app(s) : anonymizer, converter, describer, enhancer, transcriber | `wama/common/utils/ffmpeg_utils.py` |
| `output_formats` — Formats de sortie | **5** app(s) : anonymizer, composer, enhancer, imager, synthesizer | `wama/common/utils/output_formats.py` |
| `video_utils` — Utilitaires vidéo | **5** app(s) : anonymizer, converter, describer, enhancer, transcriber | `wama/common/utils/video_utils.py` |
| `audio_decode` — Décodage audio robuste | **4** app(s) : converter, enhancer, synthesizer, transcriber | `wama/common/utils/audio_decode.py` |
| `app_access` — Accès aux éléments (apps aujourd'hui) | **3** app(s) : avatarizer, synthesizer, transcriber | `wama/accounts/permissions.py` |
| `document_export` — Export document | **3** app(s) : describer, reader, transcriber | `wama/common/utils/document_export.py` |
| `external_sources` — Sources externes | **3** app(s) : describer, reader, synthesizer | `wama/common/external_sources.py` |
| `llm` — Accès LLM | **3** app(s) : describer, reader, transcriber | `wama/common/utils/llm_utils.py` |
| `audio_player` — Lecteur audio (onde + transport) | **2** app(s) : composer, transcriber | `wama/common/static/common/js/wama-audio-player.js` |
| `media_picker` — Sélecteur de médiathèque | **2** app(s) : avatarizer, imager | `wama/common/static/common/js/media-picker.js` |
| `media_probe` — Sonde média | **2** app(s) : converter, transcriber | `wama/common/utils/media_probe.py` |
| `nightly_tests` — Tests nocturnes | **2** app(s) : enhancer, transcriber | `wama/common/services/nightly_tests.py` |
| `resource_governor` — Gouverneur de ressources | **2** app(s) : avatarizer, composer | `wama/common/services/resource_governor.py` |
| `tts_service_client` — Client du service TTS | **2** app(s) : avatarizer, synthesizer | `wama/common/tts/service_client.py` |
| `tts_vocabulaire` — Vocabulaire TTS partagé | **2** app(s) : avatarizer, synthesizer | `wama/common/tts/constants.py` |
| `history` — Historique annuler / rétablir | **1** app(s) : transcriber | `wama/common/static/common/js/wama-history.js` |
| `model_coverage` — Couverture multi-modèles | **1** app(s) : anonymizer | `wama/common/services/model_coverage.py` |
| `provenance` — Provenance de modèle | **1** app(s) : anonymizer | `wama/model_manager/services/provenance.py` |
| `run_outcome` — Signaux d'exécution | **1** app(s) : transcriber | `wama/common/services/run_outcome.py` |

</details>

<details><summary>⚠ <b>2 module(s) balayé(s) non rattachés au registre</b> — à déclarer dans <code>wama/common/mecanismes.py</code>, ou à assumer comme utilitaires locaux (tout n'est pas un mécanisme transversal)</summary>


`wama/common/utils/` (1) — `hf_weights.py`

`wama/common/static/common/js/` (1) — `wama-input-slots.js`

</details>

<details><summary>Assumés utilitaires locaux : 17 (chacun avec sa raison — <code>ASSUMES_LOCAUX</code>, wama/common/mecanismes.py)</summary>

- `skills_catalog.py` — dérivation d'affichage du catalogue de skills — consommée par la vue `skills_catalog` seule
- `disk_utils.py` — plomberie disque (1 consommateur common)
- `format_policy.py` — politique de formats de POIDS de modèle — chaîne modèles
- `html_render.py` — rendu HTML→PDF, consommé par le converter seul
- `intervals.py` — algèbre d'intervalles — cam_analyzer (coverage) seul consommateur
- `lang_routing.py` — routage de langue — sera absorbé par le Translator (ROADMAP §10)
- `log_rotation.py` — décalage des journaux au démarrage (politique : on décale, on ne vide pas)
- `mime_utils.py` — détection MIME — helper fin (filemanager/studio)
- `model_locations.py` — chemins de modèles — plomberie model_manager
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
| Couche LLM — prompts, skills, RAG, mémoire, routage | `WAMA_LLM.md` |
| Apprentissage — modèles APPRIS, statistiques, boucle de simulation | `WAMA_APPRENTISSAGE.md` |
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
