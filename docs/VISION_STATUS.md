# VISION_STATUS.md — État des lieux WAMA vs vision complète

> **Croisement de [`WAMA_Vision_Complet.md`](WAMA_Vision_Complet.md) (53 sections, 11 parties) avec
> l'état réel du code au 2026-07-17.** Sources : code vérifié (Grep/lecture directe), `PROJECT_STATUS.md`
> (photo des chantiers, source de vérité opérationnelle), campagne d'audits wama-dev-ai (6 rapports
> `wama-dev-ai/outputs/vision_*_2026-07-17.md`, **citations contre-vérifiées** — voir Annexe).
>
> **Rôle de ce doc** : suivi *vision → chantiers*. Il ne remplace PAS `PROJECT_STATUS.md` (détail
> opérationnel par chantier) ; il indique où chaque pan de la vision en est, et dans quel ordre
> attaquer le reste. Maintenance : mettre à jour la table §Détail au palier, comme PROJECT_STATUS.
> Marqueurs : ✅ acquis · 🔄 en cours/partiel · ⏳ à faire · 📜 doctrine (acté, pas du code).

---

## 🌍 Architecture en MONDES (doctrine actée 2026-07-20)

> **WAMA s'organise en MONDES qui communiquent** et peuvent peupler le **studio** (chaînage) et
> la **médiathèque** (partage). Chaque utilisateur a un **profil + rôle** (ex. utilisateur / chercheur)
> qui définit à quels mondes / apps / fonctions il accède. **Validé Fabien 2026-07-20.**

| Monde | Contenu | Entrées/sorties | État |
|---|---|---|---|
| **Médias** | apps média (Imager, Converter, Transcriber, Composer, Avatarizer, Synthesizer, Reader, Describer, Enhancer…) | média → média | ✅ existant (apps en place) |
| **Data** | fonctions de traitement déclarées par capacités (catalogue WAMA Data), toolbox tierce, analyse tabulaire/timeseries/geo | données → tri/traitement → données | 🔄 socle posé (`common/data/`, 4 fn + catalogue) |
| **Lab** | apps métier de recherche (Cam Analyzer, Face Analyzer…) | domaine-spécifique | 🔄 en cours (Cam Analyzer) |
| **Transversal** | substrat commun : assistant IA, model_manager, RAG, translator, anonymizer, pipeline de prompts, **le studio lui-même**, médiathèque, profils/permissions | services partagés | 🔄 partiel |

**Principes (doctrine) :**
- Un « monde » = un **regroupement + un palier d'accès**, PAS un silo. Le sens est qu'ils
  **communiquent** : le studio chaîne p.ex. une app Médias → une fonction Data → une analyse Lab.
  **La glu = le système de capacités/ports typés** (APP_CATALOG + FUNCTION_CATALOG + taxonomie de
  types de donnée) : c'est lui qui rend l'inter-mondes sûr et guidé. Voir `WAMA_DATA_FUNCTION_CARDS.md`.
- **Studio** et **médiathèque** = les deux lieux de rencontre où les mondes convergent (chaînage / partage).
- **Accès** = réutiliser le modèle profils/permissions existant, sur **3 axes** :
  1. *tier* (niveau de compte) + 2. *rôles métier* cumulatifs (`APP_CATALOG.roles/public/min_tier`,
  Django Groups) + 3. **APPARTENANCE ORGANISATIONNELLE** de l'utilisateur (ajout 2026-07-20).
  L'accès à un MONDE est un gate grossier au-dessus des rôles par app. Ex. *chercheur* → Lab + Data +
  Transversal ; *utilisateur* de base → Médias.
- **Appartenance organisationnelle (colonne vertébrale)** : chaque utilisateur appartient à un arbre
  d'unités **institut/université → département → labo/service → équipe → utilisateur**. C'est **le MÊME arbre**
  que les niveaux d'héritage du RAG → **un seul modèle `OrgUnit` sert TROIS usages, ne pas dupliquer** :
  (a) héritage RAG, (b) **scopes de partage** (fonction/média « avec mon équipe / labo / université »),
  (c) gating d'accès optionnel. **✅ FAIT (35073dd)** : `wama.common.models.OrgUnit` (arbre, `ancestors()`),
  `user_scope_org_ids` (unités + ancêtres), remontée LDAP/SUPANN au login (`accounts/ldap.py`,
  champs `UserProfile.org_*`, 6ebeffe). Reste : synchro périodique de l'arbre `ou=structures`.
- **Transversal** est en réalité le substrat plus qu'un monde-pair ; le traiter comme un monde reste
  cohérent pour l'UX (une porte d'entrée par monde).

**Traçabilité & confidentialité — ✅ FAIT (35073dd)** :
- **Médiathèque : promotion par scope** — `UserAsset` hérite de `ScopedVisibility` (privé / unité / public
  + `scope_org_unit`). API `POST /media-library/api/assets/<pk>/promote/` : promotion par le **propriétaire**
  uniquement, partage 'unit' limité à une unité qui **couvre** l'utilisateur (labo/dépt/université de son
  appartenance). Un item promu au LABO est vu par tout membre d'une équipe du labo.
- **Confidentialité des fonctions** — modèle `wama.common.models.UserFunction` (fonctions **créées par un
  utilisateur**, `ScopedVisibility`, décrites par capacités E/S) ; la page catalogue `/model-manager/functions/`
  fusionne système (public) + user functions **visibles** (`scoped_visible_q`). Fonctions système
  code-déclarées = toujours `public`.
- **Brique commune** : `ScopedVisibility` (mixin abstrait) + `scoped_visible_q(user, owner_field)` —
  réutilisable partout (médiathèque, fonctions, futur RAG). Traçabilité qualité : `FunctionSpec.projects`.
- Reste : UI (boutons de promotion dans la médiathèque), création de fonctions user via l'UI, synchro
  périodique de l'arbre `ou=structures` LDAP.

---

## 📦 Projets, manifestes & ingestion (doctrine 2026-07-21)

> Un **manifeste métadonnée-driven** décrit un jeu de données brut (enregistrements RTMaps/LSL/rosbag,
> BDD, documents) pour l'instancier dans les apps. Un **LLM local (wama-dev-ai)** explore le dossier d'un
> projet, en **infère un manifeste brouillon** (canaux, types, unités, tables de référence), qu'un **humain
> valide** (doctrine wama-dev-ai : propose, l'humain valide). Multi-projets : indexer/labéliser un dossier
> contenant plusieurs projets, un manifeste par projet.

**Le manifeste toolbox tierce (`ENA_NAVYA/manifest.xml`) = RÉFÉRENCE quasi-idéale** — il fait déjà exactement ça :
`das`/`channel`/`signal` typés (VIDEO, TABBED_TEXT) avec datatype + unité, mappés aux sorties brutes
(`rtMapsOutputName`) ; `reference_table` = vocabulaires contrôlés (enums BatteryState/DoorsState/RobotMode
+ **le dico NV_AnnotationTag des 36 tags** dont on avait besoin) ; `record`/`timeseries` = signaux typés
(GNSS→geo_track, Accéléro→signal, Annotations→events, NavyaAPI→timeseries). **Ce que WAMA généralise** :
(a) source-AGNOSTIQUE (un « reader » par type : rtmaps/lsl/rosbag/csv, pas seulement `rtMapsOutputName`) ;
(b) mapping des types toolbox tierce → **taxonomie de types WAMA Data** (`data_types`) ; (c) ajout de la couche
**propriété / projet / visibilité** (absente de toolbox tierce). → Le manifeste WAMA = richesse descriptive toolbox tierce
+ reader pluggable + types WAMA + métadonnées projet.

**Formalisme des manifestes (doctrine 2026-07-21 — ✅ LIVRÉ 2026-07-21→08-05)** — la doctrine
décrite ici est implémentée : enveloppe commune (`common/manifests/envelope.py`), registre
`MANIFEST_KINDS` (`kinds.py`), ingest validate→sandbox→promote idempotent/transactionnel/réversible
(`ingest.py`, avec `verify`/`un_ingest` et `resolve_requires` pour la composition), **7 kinds**
(`builtin/` : app, dataset, function, **library** — kind pilote dont le registre `Library` naît de
la projection —, model, pipeline, project), corpus de 11 manifestes (`manifests/`). La redondance
historique APP_CATALOG⟷GENERIC_APPS est **résorbée** (2026-08-11 : E/S dérivées des ports).
Reste le code-gen des facettes d'app (write-back partiel : `access` seule au runtime).
**Le dispatch n'est PAS « une simple fonction »** : risque de N-copies qui divergent → le manifeste = source
UNIQUE (registres = projections OU ingest atomique avec back-link). Ingest = validate→sandbox→**promote**,
IDEMPOTENT + TRANSACTIONNEL + RÉVERSIBLE + traçable. **Sandbox = manifeste en `visibility=private/staging` →
promote** (réutilise ScopedVisibility + doctrine wama-dev-ai « propose, l'humain valide »). Voir
`memory/project_manifest_formalism.md`.

**Couche PROJET — ✅ FAIT (0e03d66)** — distincte d'`OrgUnit` : `wama.common.models.Project`
(code/name/owner_org/lead/membres M2M) + `ProjectMembership` (rôle + org d'origine du partenaire).
Un projet traverse l'arbre org (membres d'autres labo/université). **4e scope de visibilité** :
`ScopedVisibility.VIS_PROJECT` + `scope_project` → `scoped_visible_q` ajoute la branche projet, appliquée
AUTOMATIQUEMENT à la médiathèque (`UserAsset`) et aux fonctions (`UserFunction`). `api_promote` accepte
la visibilité 'project' (gate = membre du projet). Admin Project + inline membres. Testé cross-org
(porteur LESCOT + partenaire COSYS/autre univ voient ; non-membre non). Reste : UI de gestion des projets.

**Accès & modération — ✅ FAIT (a7c2240)** :
- **Journal d'accès** : `AccessLog` (user/username/event login-logout-denied/ip/user_agent/timestamp) via
  signaux `user_logged_in/out/login_failed` ; complète `User.date_joined`+`last_login` (Django). Admin
  lecture seule.
- **Modération 1ʳᵉ connexion** : `WamaLDAPBackend` crée tout nouvel utilisateur LDAP **inactif**
  (`is_active=False`) + email aux modérateurs (`WAMA_MODERATOR_EMAILS`, sinon superusers) ; l'activation
  admin (is_active False→True) envoie un **email de bienvenue**. Réglable par `WAMA_MODERATE_NEW_USERS`.
  Emails best-effort (n'interrompent jamais login/activation). Reste : une UI de modération dédiée
  (au-delà de l'admin Django).

---

## Synthèse par partie de la vision

| Partie | Thème | État global |
|---|---|---|
| I (1-2) | Vision, philosophie | 📜 actée (CLAUDE.md 6 points, conventions) |
| II (3-5) | Manifestes, auto-instanciation, gestion modèles | 🔄 manifeste **formalisé et extrait** (12 facettes × 10 apps, round-trip sans écart) ; auto-instanciation ⏳ (gatée par le code-gen) ; modèles = le plus avancé |
| III (6-8) | Studio, graphe de capacités, typage | 🔄 bien avancé — exécution réelle V1 livrée |
| IV (9-16) | Rôle/skills, RAG, traduction, chaîne prompt, assistant | 🔄 skills+pipeline+traduction entrée FAITS ; **RAG = 0** (verrou de toute la partie aval) |
| V (17-23) | Création multimédia | 🔄 briques riches (imager/composer/synthesizer/avatarizer, médiathèque) ; chaîne narrative (Story Director, storyboard, montage/mixage) ⏳ |
| VI (24-26) | Apps métiers (CAM/Face Analyzer) | 🔄 CAM quasi-complet ; Face embryon ; pont vers Studio ⏳ |
| VII (27-33) | Couche Data, Data Comprehender | ⏳ **rien** (0 app data, 0 pandas dans wama/ — vérifié) |
| VIII (34-39) | Médiathèque universitaire, SI labo | 🔄 socle media_library + providers ; IA d'ingestion/indexation ⏳ (RAG) |
| IX (40-42) | Batch, auto-maintenance, veille | 🔄 avancé sur les trois volets |
| X (43-47) | Infrastructure, trajectoire | 🔄 plan consigné ; migration Linux/Nginx ⏳ |
| XI (48-53) | Connecteurs conversationnels, LiteLLM, gouvernance | 🔄 LiteLLM câblé (Ollama-first) ; connecteurs externes = 0 (vérifié) ; gouvernance ⏳ |

---

## Détail par section de la vision

### Partie I — Vision et philosophie
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 1-2 | Vision générale, philosophie | 📜 | CLAUDE.md (6 points), `WAMA_APP_CONVENTIONS.md`, `COMMON_REFACTORING.md` — doctrine vivante et appliquée |

### Partie II — Manifestes
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 3 | Manifeste comme contrat | 🔄 | Manifeste formel **livré** (`WAMA_MANIFEST_SPEC.md` + `common/manifests/`, corpus 10 apps validées, 91 `requires` model + 1 library). Ce qui reste gaté par l'uniformisation des 10 apps, c'est le **write-back code-gen** (9 facettes), pas le formalisme |
| 4 | Auto-instanciation d'apps | ⏳ | Scaffold volontairement EN DERNIER de la route manifeste ; prospection Phase B (app émergente) gatée idem |
| 5 | Gestion intelligente des modèles | 🔄 avancé | Le pan le plus mûr : model_manager cerveau, `AIModel` source unique, VRAM-aware, keep_loaded, `install_from_spec`, conversion, backup miroir, ETA auto-apprenant. Reste : `backend_selector.py` commun, chargeur générique, étape 3 centralisation (PROJECT_STATUS §2) |

### Partie III — Studio et orchestration
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 6 | Studio WAMA | 🔄 avancé | App dédiée `wama/studio` : canvas, **persistance + exécution réelle V1** (moteur Celery topologique via `tool_api`, runners synthesizer/avatarizer/converter, cards entrée/sortie→médiathèque, animation de flux 2026-07-16). Reste : runners restants, dossier de sorties studio, fan-out parallèle, specs montage/mixage (PROJECT_STATUS §15/§37) |
| 7 | Graphe de capacités | 🔄 | Ports typés dérivés `APP_CATALOG`+`app_modes`+`normalize_types` (`studio_node_ports`). ⏳ : apps Lab hors catalogue (cam/face_analyzer), exposition des capacités fines |
| 8 | Typage des données | 🔄 | Catégories média unifiées (app_registry) + typage par connexion = FAIT. Types scientifiques (DataFrame, signaux, embeddings) ⏳ — dépend Partie VII |

### Partie IV — IA transverse
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 9 | Rôle et Skills | 🔄 | **Skills FAITS** (`common/prompt_skills/`, résolution `<app>-<domain>`, endpoint commun ✨, validé Fabien — PROJECT_STATUS §22). Rôles (niveau organisationnel) ⏳ = RAG |
| 10 | Enrichissement hiérarchique | 🔄 | Enrichissement génératif câblé (OFF par défaut `WAMA_PROMPT_ENRICH`) + `enrich_on_demand`. Niveaux labo/équipe/utilisateur ⏳ (RAG) |
| 11 | RAG hiérarchique | ⏳ **non démarré** | Décisions prises (ChromaDB + bge-m3, module `wama/rag/`, branchement = étape `enrich`) ; zéro code. **Verrou de** : rôles §9, médiathèque augmentée §36, Data Comprehender §28-31 |
| 12 | Traduction linguistique E/S | 🔄 | **Entrée FAITE** : `lang_routing.py` + `TranslatorService` + pivot EN dans la pipeline, transparence console 🌐. **Sortie ⏳** : `translate_output` défini (`translator.py:67`) mais **jamais appelé** (vérifié). i18n statique .po/.mo ⏳ (PROJECT_STATUS §8) |
| 13 | Traduction consciente structure doc | ⏳ | `batch_parsers.py` = texte brut (PyPDF2/python-docx). Pas de layout-aware ; lié à document understanding/Docling (PROJECT_STATUS §12, non construit) |
| 14 | Adaptateurs de modèle (format) | 🔄 | Kinds de pipeline (`generative`/`intent`) + `PROMPT_TARGETS` par app. Kind `concept` (anonymizer/SAM3) ⏳ |
| 15 | Chaîne unifiée prompt→modèle | 🔄 | `process_prompt` opérationnel (traduction→skill→enrichissement→émission). Manquent : hook RAG, QC post-génération (`qc.py` non câblé) |
| 16 | Assistant IA interface | 🔄 | `wama/tool_api.py` = **les 10 apps couvertes** (`add_to_*` ×11 + TOOL_REGISTRY + dispatch, vérifié). Assistant = couche projet (urls/views racine), pas d'app dédiée ; boucle agentique riche + omniprésence ⏳ (§48-50) |

### Partie V — Création multimédia
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 17 | Imager | 🔄 | Fonctionnellement riche (modes image/vidéo, WamaModes référence, mots-clés chips, ✨, catalogue modèles actif). MAIS conformité 42 % = dernière des 10 → port schéma-driven prévu en dernier des généralistes |
| 18 | Médiathèque créative | 🔄 avancé | Phases 1-4 FAITES : `UserAsset`/`SystemAsset`, **licence + source_url présents** (`media_library/models.py:128-129`), providers CC (Wikimedia/Pixabay/Freesound/Jamendo/Pexels/Openverse), MediaPicker commun, PromptKeyword. ⏳ : embeddings/recherche sémantique (RAG), tags = CSV simple |
| 19 | Différence ComfyUI | 📜 | Positionnement consigné (`STUDIO_VISION.md`) |
| 20 | Moteur génération avancé | ⏳/🔄 | Fichiers de référence + début de contrôle côté imager ; contrôle pose/profondeur systématique, cohérence personnages ⏳ |
| 21 | Story Director | ⏳ | Non construit (vision) |
| 22 | Storyboard intelligent | ⏳ | Non construit (vision) |
| 23 | Génération vidéo/audio/personnages | 🔄 | Briques : imager vidéo (Mochi/LTX/CogVideoX), composer (MusicGen), synthesizer (TTS), avatarizer (MuseTalk) — et la chaîne texte→TTS→avatar EST une composition studio. Apps montage & mixage = décidées « apps dédiées », roadmap only ⏳ |

### Partie VI — Apps scientifiques métiers
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 24 | CAM Analyzer | 🔄 avancé | Pipeline quasi-complet (rosbag/RTMaps, YOLO+BoTSORT, YOLOPv2, SAM3, LaneEvent, TTC, passes incrémentales). ⏳ Phase 3 : calibration vitesses, mesures absolues ; tests à finir |
| 25 | CAM → Studio | ⏳ | Décision cadre posée (contrat uniforme, JAMAIS d'adapters côté studio — `feedback_studio_uniform_contract`) ; pas de nœud studio cam_analyzer |
| 26 | Face Analyzer | 🔄 embryon | App existante `wama_lab/face_analyzer/` (emotions, eye_tracking, respiration, pipeline) ; hors `APP_CATALOG`, intégration UI/queue ⏳ |

### Partie VII — Data Comprehender
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 27 | Couche Data | ⏳ **rien** | Aucune app data, **zéro import pandas** dans `wama/` et `wama_lab/` (vérifié 2026-07-17) |
| 28-31 | Data Comprehender, indexation, auto-label, recherche | ⏳ | Non démarré ; dépend couche Data + RAG §11 |
| 32-33 | « DeepMind labo », boucle de découverte | ⏳ | Vision long terme |

### Partie VIII — Médiathèque universitaire et SI
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 34-37 | Médiathèque universitaire intelligente | 🔄 partiel | Socle = media_library (§18) + rétention/notifications profils. ⏳ : analyse auto à l'ingestion, tags IA, indexation sémantique (RAG), connexion apps créatives complète |
| 38 | SI laboratoire augmenté | ⏳ | Non démarré |
| 39 | Assistant réunions | ⏳ | Non démarré (matière première = transcriber + diarization, déjà solide) |

### Partie IX — Opérations
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 40 | Batch généralisé | 🔄 avancé | Import batch unifié multi-formats, card mère commune `_batch_card.html`, manipulation directe (fabrique commune) sur les apps portées. ⏳ : 5 apps restantes, batch orchestré studio |
| 41 | Auto-maintenance | 🔄 | Nightly tests : charpente + 2 gabarits + beat gaté (⏳ scénarios restants, page résultats) ; patches venv systématisés ; update_checker modèles |
| 42 | Veille / prospection modèles | 🔄 | Chaîne Ollama-first complète (prospect→cards→install/reject). ⏳ : confrontation multi-agents, HF, beat hebdo, routing capacité→app (Phase A fort ROI) |

### Partie X — Infrastructure
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 43-45 | Serveur prod, étapes 1-3 | 🔄 | Plan consigné (R760xa, GPU dimensionné média — `project_deployment_roadmap`) ; aujourd'hui mono-hôte WSL2. ⏳ migration Apache Win → Nginx Linux ; étapes 2-3 lointaines |
| 46-47 | Positionnement, vision finale | 📜 | Doctrine consignée |

### Partie XI — Interconnexion conversationnelle et routage
| § | Sujet | État | Réalité code / renvoi |
|---|---|---|---|
| 48 | Assistant intégré (Mattermost/Matrix…) | ⏳ | **Aucun connecteur** dans le code (vérifié — les matches « matrix » sont des faux positifs mathématiques) |
| 49 | Priorité solutions ouvertes | ✅ | Appliqué de fait : Ollama-first, assets vendorés localement, pas de CDN |
| 50 | Assistant omniprésent | ⏳ | Dépend §16 + §48 |
| 51 | LiteLLM | 🔄 | **Câblé** : `llm_utils.py` → `litellm.completion`, routage Ollama local par défaut (vérifié). ⏳ : passerelle multi-fournisseurs (gemini free/grok), routage cloud pour wama-dev-ai |
| 52 | Politique de sélection des modèles | 🔄 | VRAM-aware + tiers + stats runtime FAITS. ⏳ : politique confidentialité/coût formalisée — la **porte privacy avant-cloud** (Presidio+GLiNER, PROJECT_STATUS §7) est décidée mais non construite |
| 53 | Gouvernance intelligente des IA | ⏳ | Non démarré |

---

## Chantiers ordonnés (terminés / en cours / à faire)

### ✅ Terminés (paliers acquis, ne pas rouvrir)
1. Socle commun v1 : briques batch/process/queue/user_settings, `_batch_card.html`, toasts, anti-race, ETA auto-apprenant câblé 10 apps, inspecteur contextuel (5 apps portées).
2. Skills de prompt par app + endpoint commun ✨ (validé).
3. Pipeline de prompts : traduction d'entrée (pivot EN) + enrichissement + transparence console.
4. Studio V1 : canvas, ports typés, persistance, exécution réelle (3 runners), cards E/S, animation de flux.
5. Model manager : catalogue unique, prospection Ollama-first, backup miroir, nightly tests (charpente).
6. Media library Phases 1-4 (assets, providers CC, licence/source).
7. Profils/permissions 2 axes + notifications + rétention.

### 🔄 En cours — À FINIR AVANT d'ouvrir du neuf (ordre = ordre de reprise PROJECT_STATUS)
1. **P0 — Consolidation des mécanismes d'UI + uniformisation schéma-driven des 10 apps** (5 portées / 5 restantes : enhancer, anonymizer, synthesizer, imager, avatarizer). **C'est LE goulot** : gate les manifestes (§3), l'auto-instanciation (§4), la prospection Phase B, l'amincissement des cards. Réf. `UI_MECHANISMS_CONSOLIDATION.md`.
2. **P0 — Transcriber 100 %** (gold standard) puis extraction des briques restantes (drag Solitaire UI, card d'entrée universelle).
3. **P1 — Studio suites** : runners restants (imager, composer…), sorties → filemanager studio, specs montage/mixage Fabien.
4. **P1 — Cam Analyzer Phase 3** (calibration vitesses) — livrable labo concret.
5. **P2 — Veille/prospection suites** (multi-agents, routing capacité→app Phase A) ; nightly tests scénarios restants.

### ⏳ À faire — ordre de priorité recommandé
1. **P1 — Fondation RAG `wama/rag/`** (ChromaDB + bge-m3 + indexation via médiathèque). Débloque à lui seul : rôles §9, enrichissement hiérarchique §10, médiathèque augmentée §36, et conditionne toute la Partie VII. À lancer dès que le socle UI (P0 ci-dessus) est stabilisé — décision existante : « socle d'abord ».
2. **P1 — Traduction de sortie** : câbler `translate_output` (le code existe, il n'est appelé nulle part) + i18n statique ; puis traduction consciente de la structure documentaire (§13) avec le chantier document understanding (Docling, 1er adopteur `reference_field`).
3. **P2 — Anonymisation multimodale** (Presidio + GLiNER) = prérequis de la politique cloud-free §52 et du routage cloud sûr §51.
4. **P2 — Manifeste formel + génération d'app** (après uniformisation) : contrat URLs, enum statuts, `check_app_conformity` exécutable, scaffold en dernier.
5. **P2 — Face Analyzer → catalogue** + pont apps métiers→Studio (§25-26).
6. **P2-parallèle — Couche Data** (Partie VII socle) — **reclassée 2026-07-20 (décision Fabien)** :
   fil indépendant à démarrage progressif, en parallèle de H1/H2 — socle data (tabulaire/signaux)
   + **centralisation des fonctions de calcul de wama_lab en briques communes** + connexion
   médiathèque. Le Data Comprehender IA (aval de la partie VII) reste P3, gaté par ce socle + RAG
   + garde-fous méthodologiques.
7. **P3 — Médiathèque universitaire complète + SI labo + assistant réunions** (Partie VIII).
8. **P3 — Story Director / storyboard / apps montage & mixage** (Partie V narrative).
9. **P3 — Connecteurs conversationnels** (Mattermost/Matrix, §48-50) + gouvernance §53.
10. **P3 — Infra** : migration Nginx/Linux puis étapes matérielles 2-3.

> Fils conducteurs de la priorisation (décisions existantes, pas de nouveauté) : *finir quelques
> apps à 100 % avant de porter partout* ; *uniformisation → manifestes → génération* ; *RAG après
> le socle* ; *jamais d'adapters côté studio, on finit le port de l'app*.

---

## Annexe — Méthode et fiabilité de la campagne wama-dev-ai (2026-07-17)

6 audits ciblés (`gemma4:e4b`, read-only) : pilote Studio + traduction, médiathèque, data,
assistant/LiteLLM, parsing documents. **Toutes les citations ont été contre-vérifiées par Claude.**

- **Fiable** : affirmations positives avec citation (fonctions/lignes exactes dans ~100 % des cas
  vérifiés) ; usage honnête de « NON VÉRIFIÉ ».
- **Non fiable — corrigé dans ce doc** : les affirmations d'absence et de couverture.
  Erreurs détectées : « exécution studio non implémentée » (elle l'est, 3 lignes sous sa fenêtre de
  lecture) ; « pas de licence/auteur en médiathèque » (champs présents `models.py:128-129`) ;
  « tool_api = 3 apps » (10 apps couvertes) ; « pas d'OCR » (backend OCR dédié du reader).
- **Règle pour les prochaines campagnes** : wama-dev-ai collecte des faits cités (tâches étroites,
  1 thème/run) ; Claude vérifie mécaniquement chaque chemin cité, revérifie lui-même TOUT « n'existe
  pas », et garde la couverture, les statuts et la priorisation.
