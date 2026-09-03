# Pipeline cible : prospection → installation → app, piloté par l'assistant IA

> Vision énoncée par Fabien (2026-07-17) : l'utilisateur exprime un BESOIN à l'assistant ;
> la chaîne va jusqu'au modèle installé dans la bonne app — ou jusqu'à la génération de
> l'app manquante. Ce document fige la cible, l'état des briques et l'ordre de réalisation.
>
> **Mise à jour : 2026-08-04** — confrontation au réel après l'arrivée de la couche manifestes
> (voir « Mise en conformité » plus bas). L'état des briques et l'ordre ont été révisés.

## Le pipeline en 6 étapes

```
[1] Besoin utilisateur (assistant IA)
      « il me faut un modèle qui segmente les véhicules de nuit »
[2] Prospection : trouver les candidats + récupérer leurs CAPACITÉS
      (HF API : pipeline_tag, library_name, tailles ; releases Ultralytics ; Ollama)
[3] Identifier la LIBRAIRIE d'exécution (transformers, ultralytics, diffusers…)
      → dépendances pip éventuelles
[4] MATCHING besoin ↔ app existante (capacités déclarées dans APP_CATALOG)
      ├─ app trouvée → [5]
      └─ pas d'app  → [6]
[5] INSTALLATION par descripteur : install_from_spec({kind, ref, category,
      pip_dependencies, …}) → bon dossier + catalogue AIModel + backend prêt
[6] GÉNÉRATION d'app : manifeste (capacités, modes, UI schéma-driven) →
      routines de génération/auto-instanciation d'applications
```

## État des briques (2026-07-17)

| Étape | État | Brique |
|---|---|---|
| 1 | 🟡 | AI-Assistant + `tool_api.py` — **un SEUL fichier central `wama/tool_api.py`** (`TOOL_REGISTRY`, `/api/v1/tools/`), pas un par app. Il couvre les 10 apps média et **zéro outil model_manager** : `search_models` / `model_catalog` / `prepare_install_spec` / `install_model` restent à écrire |
| 2 | 🟡 | `services/prospector.py` (HF API : `pipeline_tag`, librairie, downloads, **`--search`, métrique `model-index`, licence, URL** depuis 2026-08-05) + `prospect_agents.py` (évaluation LLM des candidats) — chaîne Ollama-first opérationnelle ; **moitié « HF vision » de l'extension livrée** (cf. §2 bis), reste le beat releases Ultralytics |
| 3 | ✅ | **SUBSUMÉ par la couche manifestes** (2026-08-02) : le kind `library` (SPEC §7.4-3) porte dépôt/licence/version/`install.pip`, extrait mécaniquement par `extract_library()` ; la « passe LLM » est le rôle wama-dev-ai « librarian » (§7.4-4, `run_librarian.py`). Reste à **brancher** sur la prospection, plus à écrire |
| 4 | 🟡 | Capacités d'apps déclarées (`APP_CATALOG`, `app_registry`) ; le matching besoin↔capacité est à écrire |
| 5 | ✅ | `install_from_spec()` (descripteur déclaratif, ce commit) + drivers `pull_ollama_model` / `pull_hf_model` / `pull_yolo_weights` / `pip_install_packages` + `register_after_install` |
| 6 | 🔄 | = chantier « manifests → génération LLM » DÉJÀ priorisé (voir **`WAMA_APP_GENERATION_ROUTE.md`** — `UI_MECHANISMS_CONSOLIDATION.md` est archivé dans `docs/archive/` — et `WAMA_MANIFEST_SPEC.md`) — la vision s'y branche, ne pas dupliquer. Avancé depuis : 7 kinds, enveloppe `requires`, ingest, corpus |

## Garde-fous (non négociables)

- **Validation humaine** pour toute dépendance pip (`spec.human_validated` requis) et pour
  la génération d'app. L'assistant PRÉPARE le spec ; l'humain valide l'exécution.
- **Sources fermées** : noms/refs officiels (Ollama, HF repo id, poids YOLO officiels) —
  jamais d'URL arbitraire dans le spec.
- **Path d'abord** (règle CLAUDE.md) : chaque driver installe dans l'arborescence dédiée
  (`model_locations` / `vision/yolo/<task>/`), jamais dans le cache HF global.

## Mise en conformité avec la couche manifestes (2026-08-04)

> Ce document a été écrit le 2026-07-17, **avant** la couche manifestes (7 kinds : `app`,
> `dataset`, `function`, `library`, `model`, `pipeline`, `project`). Confrontation au code :

- **Un candidat de prospection EST DÉJÀ un manifeste `model`.** `common/manifests/builtin/model.py`
  extrait `provenance.is_proposed / proposal_kind / confidence / update_complexity`. Il ne faut donc
  PAS inventer un format de candidat parallèle.
- **Le « spec attaché » n'a pas de domicile.** `model.body` expose `identity` / `resources` /
  `formats` / `capabilities` / `provenance` / `extra_info` — **aucun bloc `install`**, alors que
  `library.body.install.pip` existe ET est validé (`install.pip manquant` = erreur de validation).
  → ~~**Décision : le descripteur `install_from_spec` devient `model.body.install`**
  (`{'kind': 'ollama'|'hf'|'yolo', 'ref': …, 'category'/'family'/'allow_patterns'}`), symétrique de
  `library.body.install`. PAS dans `extra_info['prospect']['spec']` : ce serait un champ surchargé,
  invisible du validateur et du round-trip.~~
  ⚠ **Décision REMPLACÉE le 2026-08-27, jamais appliquée entre-temps** : le besoin (quels fichiers
  tirer) est couvert autrement — l'anatomie vit dans **`body.composition`** (validée par le kind,
  consommée par l'install via `patterns_from_composition`), et le spec d'install reste porté par le
  candidat (`prospector.py` écrit `extra_info['prospect']['spec']` — le chemin que la décision
  refusait est celui que le code a pris ; assumé, le validateur couvre désormais `composition`).
- **Le kind `model` est « store+verify only »** (pas de `project`, cf. `kinds.py`) : un candidat
  validé ne s'écrit pas en base par la couche manifeste — l'installation reste
  `api_prospect_install` → `install_from_spec`. Le manifeste DÉCRIT, l'endpoint EXÉCUTE.
- **Trous ouverts par cette confrontation — TOUS REFERMÉS depuis** (relevé 2026-08-27) :
  (a) ~~pas de `manifests/models/`~~ → **92 manifestes de modèles** dans `manifests/models/` ;
  (b) ~~aucun rôle « scout modèles »~~ → `wama-dev-ai/run_scout.py` + `run_integrator.py` livrés
  le 27/08 (§rôles plus bas) ; (c) ~~`api_prospect_install` refuse le non-Ollama~~ →
  `install_from_spec` est branché sur l'endpoint (`views.py::api_prospect_install`, `spec` accepté).

## Décision — pas de sauvegarde des modèles Ollama (2026-08-04, Fabien)

**Les modèles Ollama ne sont PAS sauvegardés vers `\\vrlescot\SAVES`, et c'est délibéré.**

- La sauvegarde sert la **restauration** ; `ollama pull <nom>:<tag>` la fournit déjà, sans coût.
- La **reproductibilité scientifique** n'exige pas d'archiver les poids mais de savoir quel build
  a tourné : c'est déjà le cas — `AIModel.extra_info['ollama_id']` stocke le **préfixe du digest**
  (vérifié : catalogue `4eb23ef187e2` ↔ API `4eb23ef187e2c5462566…`).
- Coût évité : **91 Go** sur un NAS de labo, pour du contenu librement re-téléchargeable.
- Risque accepté et nommé : un retrait ou un ré-étiquetage amont rendrait un digest
  irrécupérable. Jugé faible devant le coût certain.

**Le lien symbolique `AI-models/models/llm/ollama` → `D:\.ollama\models` est CRÉÉ** (2026-08-04).
J'avais d'abord conclu à son abandon en ne le jugeant que sur l'axe backup — **c'était trop
étroit** (recadrage Fabien) : sa raison d'être est la **centralisation**, que tous les poids se
lisent au même endroit (inventaire, comptabilité disque, navigation), indépendamment de la
sauvegarde.

Et les deux décisions s'accordent au lieu de se contredire : **`Path.rglob()` ne suit pas les
liens de dossier** (mesuré sur Python 3.12.3 — `rglob('*')` retourne le lien, jamais son contenu),
donc le lien centralise **sans** entraîner les 91 Go dans `remote_backup`. C'est exactement le
comportement voulu ici.

Vérifié après création : lien lisible depuis Windows ET WSL2 (`blobs`, `manifests`), `AI-models/`
est gitignoré donc aucun impact git, et `full_sync()` reste à **129 modèles, 0 ajout, 0 entrée
parasite** — le magasin d'objets d'Ollama ne pollue pas le catalogue. À noter : les modèles Ollama
remontaient DÉJÀ dans le model_manager via l'**API HTTP** (`/api/tags`), pas par le disque ; le
lien apporte l'unification du stockage, pas une nouvelle voie de découverte.

L'emplacement réel est déclaré une fois par machine dans `.env` (`OLLAMA_MODELS_DIR`) — source de
vérité pour vérifier/recréer le lien. Le contrôle d'espace disque, lui, n'en dépend pas :
`AI-models` et `D:\.ollama` sont sur le **même volume**, un `SystemMonitor.get_disk_info()` suffit.

## État livré — session du 2026-08-04

Le symptôme d'entrée était « la prospection ne propose plus que 2 modèles, tous deux anciens ».
Il avait **trois causes distinctes**, toutes corrigées, plus deux chantiers ouverts par la suite.

| Brique | Rôle |
|---|---|
| `common/utils/ollama_host.py` | Adressage Ollama : passerelle WSL2 + contournement du proxy. Deux pièges qui produisaient un `ReadTimeout` — « Ollama ne répond pas » alors qu'il tournait — et **déclenchaient la purge** des candidats |
| `model_manager/services/ollama_registry.py` | Découverte déterministe : recherche par capacité, tags, **vérification d'existence au manifeste** avant toute proposition ; successeur de famille (`qwen3.5 → qwen3.6`) avec fenêtre de taille **symétrique** |
| `prospect_ollama.py` (réécrit) | Seed de 2 modèles codés en dur **supprimé** → rôles déclaratifs ; purge **conditionnée au succès** de chaque source |
| `views._garde_espace_disque` + `_modele_remplace` | Refus en 507 si le volume saturerait ; séquence désinstallation → installation avec **rattrapage** ; recalage de la ligne remplacée |
| `services/model_quality.py` + `AIModel.quality_index` | Sélection par **qualité** sous contrainte VRAM, au lieu de « le plus gros qui tient » |

**Mesures de bout en bout (2026-08-04, cette machine)** — `qwen3.5:35b-a3b` → `qwen3.6:35b`
installé via la vue réelle : 27 candidats prospectés contre 2, garde disque validé
(23,7 + 23,0 libérés − 22,3 = OK), disque 23,7 → 36,6 Go libres, carte candidate consommée,
et les tiers `meeting`/`image` routent désormais vers `qwen3.6:35b`.

**Ce que les tests ont trouvé et qui n'aurait pas été vu autrement :**
- une **ligne fantôme** — le modèle remplacé restait `is_downloaded=True` alors qu'Ollama ne
  l'avait plus, donc `select_model()` pouvait désigner un modèle inexistant ;
- une **régression possible en prospection** — le garde-fou de taille n'existait que vers le
  haut, donc un successeur bien plus petit pouvait s'afficher comme « mise à jour » ;
- `/api/tags` et `/api/show` **déclaraient déjà** capacités, paramètres exacts, contexte et
  ratio d'experts d'un MoE — rien de tout cela n'était lu, et un commentaire du code affirmait
  même à tort que la multimodalité y était inconnaissable.

**Reste faible** : la découverte par requête libre manque de pertinence (`megadolphin` classé
« traduction »). Les filtres par capacité sont fiables, pas les requêtes textuelles — c'est le
tri qu'une passe de notation ferait mieux qu'une regex.

## §2 bis — État livré, session du 2026-08-05 : qualité déclarée et recoupement multi-plateformes

**Le tri par téléchargements est de la POPULARITÉ, pas de la qualité.** La prospection ne rendait
que ça. Trois manques comblés, tous mesurés :

1. **Recherche par mots-clés** (`--search`). Sans elle, `object-detection` trié par téléchargements
   ne remonte que des détecteurs COCO génériques : les spécialisés cherchés (visage, plaque) sont
   trop loin dans le classement. Mesure : `--search "license plate"` → 10 détecteurs dédiés, dont
   `morsetechlab/yolov11-license-plate-detection` (65 k) ; sans le mot-clé, zéro.
   ⚠ `search` matche aussi le **nom d'organisation** — `--search face` remonte `facebook/*`.
   Resserrer sur `face-detection` ou `yolo-face`.
2. **Métrique déclarée** (`model-index` de la carte HF), ramenée par `expand=['cardData']` dans la
   **même** requête — pas de N+1. Mesure : `keremberke/yolov5m-license-plate` mAP@0.5 = 0,988 et sa
   variante `n` = 0,978, évaluées sur le **même** jeu donc comparables *entre elles*. Les autres
   candidats ne déclarent rien — l'absence de métrique n'est pas une mauvaise note.
   ⚠ Valeur **auto-déclarée**, non vérifiée, sur le split de l'auteur : le jeu et le drapeau
   `verified` sont affichés avec elle. **Ça trie des candidats à essayer, ça ne conclut pas.**
3. **Licence et URL** remontées. La licence n'est pas un détail : le candidat le plus téléchargé est
   en AGPL-3.0. Cadrage Fabien (2026-08-05) : *ouvert pour la recherche suffit, même si ce n'est pas
   explicitement open source* — donc non bloquant, mais à consigner pour l'audit de licences WAMA.

### Recouper plusieurs référentiels, ne pas s'aligner sur un seul

Sondés le 2026-08-05. **Aucun ne couvre le champ, et ils ne décrivent même pas la même chose** :

| Plateforme | Ce qu'elle expose | Sans clé |
|---|---|---|
| HuggingFace | **une** tâche par modèle (47 tags, `/api/tasks`) | ✅ |
| Ultralytics | une tâche par fichier de poids (`detect/segment/classify/pose/obb`) | ✅ |
| Ollama | un **ensemble** de capacités (`/api/show`) : `completion, vision, audio, tools, thinking, embedding` | ✅ |
| Roboflow | tâches vision, **plus fines** (`Instance` vs `Semantic Segmentation`) | ✅ (doc) |
| Civitai | axe **artefact** : `Checkpoint, LORA, TextualInversion, Upscaler` | ✅ |
| OpenRouter | **modalités** E/S : entrée `audio, file, image, text, video` — sortie `audio, image, text` | ✅ |
| ModelScope · Replicate | JSON invalide · 401 | ❌ |

`tools` et `thinking` (Ollama) n'ont **aucun équivalent** ailleurs, et ce sont eux qui disent si un
modèle peut servir l'assistant. Le recoupement fait apparaître **quatre axes distincts** — artefact,
tâche, capacités, modalités E/S — que `ModelType` écrasait en un seul champ. D'où `ModelTask`,
`ModelAbility`, `TASK_TO_PLATFORM_TAGS` (projection **à sens unique, plusieurs-vers-un**) et le
contrôle `check_model_taxonomy`. Voir `WAMA_MANIFEST_SPEC.md §7.1 bis`.

### Accès Roboflow (question tranchée)

**L'export des poids est disponible** pour la famille YOLO (YOLO26, YOLO11, YOLOv12, YOLOv9, YOLOv5,
YOLOv7, RF-DETR), avec exécution locale via **Roboflow Inference, auto-hébergeable**. Une clé API
suffit, l'application n'est pas requise — le plan gratuit restrictif n'est donc pas bloquant.
**Refusé** pour SAM3/SAM2, Florence 2, Qwen3-VL et la plupart des modèles de fondation. Les licences
**suivent les projets amont**.

### Ce qui reste en travers

- **Licences non renseignées** : HF limite les requêtes non authentifiées — 2 réponses sur 21 avant
  `HfHubHTTPError`, alors que les `hf_id` sont valides. Il faut un jeton ou un backoff.
- **70 modèles sans origine établie** (`platform_ref` vide) : ceux que leur app **découvre par scan
  disque** au lieu de les déclarer. `backfill_platform_refs` les laisse VIDES à dessein — les
  rattacher demande de vérifier le dépôt d'origine, pas de l'inférer d'un nom de fichier.
- **Le drapeau « déjà dans WAMA » ment tant que `hf_id` est vide** :
  `morsetechlab/yolov11-license-plate-detection` est annoncé « ★ NOUVEAU » alors qu'il est installé
  sous le nom `license-plate-finetune-v1{n,s,m,l,x}.onnx`.

---

## Ordre de réalisation recommandé

1. ✅ `install_from_spec` (fait — point d'entrée unique, endpoint `{'spec': …}`).
2. `model.body.install` (bloc + validation, sur le patron de `library`) puis levée de la
   restriction Ollama-only de `api_prospect_install` : c'est ce qui débloque 3.
3. `tool_api.py` du model_manager : exposer `search_models` (prospector), `model_catalog`
   (AIModel), `prepare_install_spec` (retourne le spec SANS exécuter), `install_model`
   (exécute un spec validé) à l'assistant.
4. Beat de prospection vision : candidats `is_proposed` avec `body.install` renseigné (Ultralytics
   releases + HF `pipeline_tag` vision), même UI « Proposés par IA » qu'Ollama. Remplace le stub
   jamais exécutable `AI-models/weekly_model_discovery.py` (à supprimer alors).
5. Matching besoin↔app (capacités APP_CATALOG) — fonction pure, testable.
6. Génération d'app : rejoindre le chantier manifeste existant (P0).

## État livré — session du 2026-08-18 : install asynchrone + confiance LLM des `new` + journal applicatif

Déclencheur : première installation RÉELLE via l'UI (qwen3.8:latest, 18 Go) supervisée de bout
en bout. La chaîne a abouti, mais en révélant trois trous, tous comblés dans la foulée :

1. **Install asynchrone (tâche Celery + avancement pollable).** Le pull synchrone dans la requête
   dépassait le timeout du proxy Apache : le navigateur recevait une page HTML d'erreur
   (« Unexpected token '<' ») pendant que le worker gunicorn continuait en aveugle, et un re-clic
   ouvrait une requête CONCURRENTE. Désormais :
   - la séquence longue vit dans `model_installer.installer_candidat()` (corps unique :
     retrait de l'ancien si successeur → pull → rollback éventuel → re-sync → recalage →
     suppression du candidat) ; `_modele_remplace` a déménagé de `views.py` vers
     `model_installer.modele_remplace` (la tâche en a besoin autant que la garde) ;
   - `tasks.install_proposed_task` publie l'avancement (statut du pull AVEC pourcentage —
     `pull_ollama_model` exploite maintenant `completed/total` du flux) dans le cache Redis
     (`INSTALL_CACHE_PREFIX + model_key`), même motif F5-proof que `BACKUP_ALL_CACHE_KEY` ;
   - la vue garde la GARDE D'ESPACE synchrone (le 507/forçage est un dialogue), répond
     immédiatement, et un re-clic REJOINT l'installation en cours (idempotence vérifiée
     auprès de Celery, motif `_mirror_job_start`) ; nouvelle vue
     `api_prospect_install_progress` + polling JS (`mmProspectPoll`).

2. **Confiance des candidats `new` = confrontation LLM PERSISTÉE** (SUITE (a) du 2026-06-24,
   enfin câblée). `prospect_agents` : juge (`_juger`) et consolidation (`_consolider`) extraits
   et partagés avec la voie HF (CLI `assess_models`, inchangée) ; nouveau
   `assess_proposed_ollama()` évalue les candidats Ollama `kind='new'` sans confiance —
   contexte FACTUEL (rôle, taille via registre, installés comparables du même type comme
   référentiel « à surpasser ») — et PERSISTE : `AIModel.confidence` = probabilité consolidée
   que l'adoption vaille le coup (un avis « contre » à confiance c compte 1−c),
   `extra_info['prospect']['assess']` = consensus + avis (badge card + inspecteur, existants).
   ⚠ PÉRIMÉ le 2026-08-19 (crash hôte, cf. section suivante) : l'enfilage automatique à la
   fin de `api_prospect_ollama` est DÉSACTIVÉ (`PROSPECT_ASSESS_AUTO=False`) — la passe est
   déclenchée explicitement (bouton « Évaluer la confiance » / `assess_models --proposed`),
   incrémentale `max_assess=10` par passe. Fonction renommée `assess_proposed` (Ollama + HF). Agents : `settings.PROSPECT_ASSESS_AGENTS`
   (défaut `ollama:qwen3.5:9b` ; cloud = ajouter `,google:gemini-2.0-flash` + clé).
   `prospect_ollama._ecrire` PRÉSERVE désormais une évaluation persistée lors des
   re-prospections (sinon chaque clic « Prospecter » remettait tout à zéro).

3. **Journal applicatif `logs/wama.log`.** Les loggers `wama.*` n'avaient AUCUN handler
   (`settings.LOGGING` n'existe que dans la branche LDAP) : le `logger.exception` de l'install
   partait dans le vide. `common/apps.py ready()` attache maintenant `attach_dedicated_log('wama',
   'wama.log', propagate=True)` — propagate=True, à l'INVERSE de model-sync.log, pour ne pas
   priver les `celery-*.log` des traces de tâches. Ajouté à `RUNTIME_LOGS` (rotation démarrage).

Bonus (même session) : le sélecteur de modèle du chat assistant (home.html) affichait des
libellés FIGÉS (« Qwen3.5 35B-A3B (Dev) ») alors que la value (rôle) était résolue par le
catalogue — libellés désormais résolus au rendu (`views._chat_model_options`).

Leçon opératoire : un pull refusé par un démon Ollama trop ancien pour le modèle sort en
erreur générique — vérifier la version d'Ollama avant de diagnostiquer plus loin.

RESTE (inchangé) : beat hebdo, découverte large registre, HF/diffusers, matching besoin↔apps.

### Addendum audit anti-réinvention (même session, sur question de Fabien)

Trois écarts trouvés dans la livraison ci-dessus et corrigés dans la foulée :
1. `_AGENTS_DEFAUT`/CLI `assess_models` épinglaient `ollama:qwen3.5:9b` — remplacé par
   `'ollama'` seul : `llm_chat(model=None)` résout via `modele_par_defaut()` (catalogue),
   un nom figé aurait pourri au prochain remplacement (leçon déjà consignée dans llm_utils).
2. Le polling JS refaisait une boucle à la main — rebasé sur la brique commune
   `WamaApp.Poller` (wama-app-base.js). NB : `createMirrorBackupUI` (backups, antérieur)
   garde sa boucle locale — dette préexistante, à rebaser à l'occasion.
3. « publication cache + garde tâche vivante » se dupliquait entre `run_mirror_job` /
   `_mirror_job_start` et l'install → EXTRAIT en brique commune
   `common/utils/task_progress.py` (`publier_progression` + `progression_en_cours`),
   adoptée par les miroirs, l'install et l'assess ; entrée ajoutée au registre
   `mecanismes.py` (carte régénérée par `doc_facts --only mecanismes`).

## État livré — session du 2026-08-18 (suite) : prospection GÉNÉRATION image/vidéo + « remplace/concurrence » sur les cards

Demande Fabien : « que Wan3 sorte » + voir depuis la card d'un candidat ce qu'il pourrait
remplacer. ⚠ Constat factuel au passage : **Wan3 n'existe pas sur HF à ce jour** (dernières
sorties Wan-AI = Wan2.2-Animate-2 ; les dépôts « wan3 » sont des utilisateurs sans rapport) —
le mécanisme le fera sortir dès publication, via le tri TENDANCE.

1. **`prospector.seed_generation_candidates()`** — pendant HF de la découverte par rôles :
   balaye `GENERATION_TASKS` (text-to-image / text-to-video / image-to-video, déclaratif)
   avec DEUX tris complémentaires (`downloads` = l'éprouvé, `trendingScore` = ce qui monte —
   vérifié : seul ce tri fait sortir LTX-2.5-Diffusers à 3 747 dl), filtre de bruit
   déclaratif `_MOTIFS_BRUIT` (LoRA/GGUF/ComfyUI/quantifs — le trending était aux 3/4 des
   LoRA de particuliers), poids RÉEL par `model_info(files_metadata=True)` sur les seuls
   retenus (LTX-2 = 292,8 Go mesurés → la garde d'espace est sérieuse ici), et candidats
   écrits par le writer UNIQUE `ecrire_candidat` (généralisé : source/complexité/champs).
   Chaque candidat porte son **spec d'installation** (`install_from_spec`) — RESTE (3)
   du pipeline enfin comblé. Purge scopée par tâche ABOUTIE (règle prospect_ollama).
   Branché au MÊME clic « Prospecter » (échec HF ≠ échec Ollama). Le bruit résiduel
   (finetunes de particuliers dans le trending) est le travail de la confrontation LLM.
2. **Install HF asynchrone** : `installer_candidat` route les candidats porteurs d'un spec
   non-Ollama vers `install_from_spec` (RÉUTILISÉ : bon dossier + sync + provenance) ;
   garde d'espace généralisée (`besoin_gb` = poids relevé à la prospection, 0.0 = inconnu
   → refus prudent forçable) ; `assess_proposed` (ex-`assess_proposed_ollama`) évalue
   AUSSI les candidats HF — contexte = carte de modèle HF (même source que la CLI).
3. **Cards/inspecteur** : ligne « Remplace <ancien> » (candidat successeur — ce que
   l'installation RETIRE) ou « Concurrence : a, b, c » (candidat nouveau — les meilleurs
   installés du même type via `AIModel.meilleurs_installes`, persistés dans
   `prospect.concurrence` par les deux prospections). ⚠ Un candidat NOUVEAU ne déclenche
   JAMAIS de retrait automatique : la concurrence est un référentiel affiché, l'arbitrage
   réel reste la sélection (indices) puis l'humain.

RESTE (mis à jour) : beat hebdo (Ollama + génération) ; vision (YOLO) auto-proposée ;
`createMirrorBackupUI` à rebaser sur WamaApp.Poller (dette antérieure) ; chargeur/backends
pour EXPLOITER un modèle diffusion fraîchement installé (installé+catalogué ≠ utilisable,
cf. note pull_hf_model).

## ÉTAT DES LIEUX DE LA COUVERTURE (mesuré le 2026-08-18 soir — LA table de référence)

Catalogue réel : 95 modèles installés (49 vision, 12 llm, 10 speech, 9 diffusion,
7 upscaling, 3 music, 2 ocr, 2 lipsync, 1 vlm).

| Type / domaine | Bibliothèque | Mécanisme (candidats UI) | Confiance LLM | Remplacement |
|---|---|---|---|---|
| llm / vlm / embedding / coder / translation | Ollama | rôles `ROLES` (`new`) + âge & successeurs de famille (`update`) | ✅ `assess_proposed` | ✅ auto pour `update` (origin+cible) |
| diffusion (t2i / t2v / i2v) | HF | `HF_TASKS` (2 tris + bruit + poids réel + spec) | ✅ | concurrence affichée (référentiel) |
| speech ASR + TTS | HF | `HF_TASKS` ✅ 18/08 soir | ✅ | concurrence |
| upscaling (enhancer) | HF | `HF_TASKS` ✅ 18/08 soir | ✅ | concurrence |
| vision détection | HF | `HF_TASKS` ✅ (⚠ top = génériques COCO/tables ; les SPÉCIALISÉS visage/plaque exigent `search` — pas d'auto) | ✅ | concurrence |
| music (composer) | HF | `HF_TASKS` ✅ 18/08 soir (⚠ licences NC fréquentes — relevées sur la card) | ✅ | concurrence |
| ocr (reader) | HF | `HF_TASKS` ✅ 18/08 soir | ✅ | concurrence |

**Trous restants (par ordre d'intérêt) :**
1. **MAJ des installés HF** : `check_updates(do_hf=True)` produit des signaux (CLI
   `check_model_updates`) mais AUCUN candidat UI `update` — le remplacement auto n'existe
   que côté Ollama.
2. **Vision spécialisée** (visage/plaque/YOLO) : install à la demande OK (`pull_yolo_weights`,
   spec `yolo`) mais pas de VEILLE auto (releases ultralytics + `search` HF ciblé).
3. **Beat hebdo** : aucune prospection périodique — tout est au clic.
4. **lipsync/avatars** : hors périmètre HF (pas de pipeline_tag) — chantier séparé
   (docs/PROSPECTION_AVATARS_2026-08-17.md, pilote TalkingHead).
5. ~~Candidats legacy `synthesizer:*` (SpeedySpeech/Tacotron2/VITS, seed 2026-06, conf 0.9
   figée)~~ — **SOLDÉ le 2026-08-28** (`REMOVAL_LEDGER` R32). Ils n'ont pas été « rejetés »
   comme candidats mais RETIRÉS de bout en bout (vocabulaire, catalogue, moteur, front, corpus)
   sur mesure : **0 usage sur 103 travaux**, jamais mis à jour depuis le seed, aucune capacité
   déclarée. ⚠ Ce qui les rendait invisibles n'était pas leur ancienneté mais leur STATUT :
   `is_proposed=True` les sortait de toutes les vues d'inventaire alors que le select de l'app
   les proposait comme moteurs exécutables — *un candidat de prospection ne doit jamais être
   simultanément une option d'exécution.*
6. `image-text-to-text` (VLM HF) : volontairement absent (doublon rôle Ollama `vlm`) —
   à rouvrir seulement si un backend VLM transformers existe côté describer.

Session du 18/08 soir : `seed_generation_candidates` GÉNÉRALISÉ en `seed_hf_candidates`
(table `HF_TASKS` : 9 tâches, plancher de poids PAR TÂCHE — un YOLO légitime pèse 13 Mo —,
plafond par tâche, rôle `hf:<tâche>`, purge à double graphie pour la transition) ; motifs de
bruit enrichis (quantifs, CoreML/MLX). Test réel : 32 candidats / 9 tâches, licences relevées
(musicgen = cc-by-nc-4.0 visible), whisper-large-v3 installé correctement exclu (flag have).

## Session du 2026-08-19 : CRASH HÔTE → passe LLM GOUVERNÉE + benchmark exposé

**Incident** : la passe assess enfilée AUTO après la prospection a fait tomber Windows à
chaque clic (1er verdict 01:57:44 → hôte down, Ollama relancé 01:59:02) — pattern « Ollama
hôte enchaîné » déjà proscrit sur cette machine (instabilité SOUS l'OS, même à faible charge).

**Câblage correctif (tout par les briques EXISTANTES) :**
1. Enfilage auto DÉSACTIVÉ (`PROSPECT_ASSESS_AUTO=False`, settings) — la passe est une
   ACTION EXPLICITE : bouton « Évaluer la confiance » (mmProspectBar, suivi WamaApp.Poller
   + `api/prospect/assess[/progress]`) ou CLI `assess_models --proposed`.
2. **Gouverneur de ressources** (le mécanisme d'auto-adaptation existant, enfin consommé
   par la prospection) : garde `effective_free_gb()` (< besoin → passe REPORTÉE, candidats
   restent sans confiance) + `vram_reservation(f"model_manager.assess:{pid}", besoin)` pour
   la durée de la passe — même motif que MuseTalk/CodeFormer : la charge tourne dans
   l'OLLAMA HÔTE, invisible des process WAMA sans déclaration. Besoin = `_vram_agents()`
   (empreinte RÉELLE du plus gourmand des agents locaux, résolue par le catalogue).
3. **Parallélisme** : tâche routée file `gpu` `--pool=solo` palier `basse`
   (pseudo-app `_prospect_assess` dans APP_TIERS + route nommée dans settings) →
   sérialisée derrière tout traitement utilisateur, jamais en concurrence GPU.

**Benchmark tiers confronté (chantier de l'autre session, 017d237/44d3a28) — intégré :**
la sélection le consommait déjà (`_cle_de_rang` étage 2 ; qwen3.8 52.0 ≫ qwen3.6 32.1 —
la mesure tierce corrige l'a priori) et `sync_benchmarks` couvre les lignes `proposed:`.
Ce qui manquait et est branché : `to_dict` expose `benchmark_index`/`benchmark_meta` →
badge « bench X » sur les cards proposées + ligne « Benchmark tiers » à l'inspecteur ;
le CONTEXTE des agents d'évaluation inclut le benchmark du candidat (`_ligne_benchmark`)
et celui du référentiel installé (`_referentiel`). Vérifié en base : 16 modèles
benchmarkés, échelles par catégorie (Elo imager ~1369 ≠ AA llm 52) jamais mélangées.

⚠ La passe LLM RÉELLE n'a toujours pas été validée de bout en bout (elle plantait l'hôte
avant) : premier essai à faire par le bouton, hors traitement GPU, en surveillant wama.log.

### Suivi de résidence OLLAMA + lisibilité du benchmark (2026-08-19, questions Fabien)

**Q1 « le LLM est resté chargé mais je vois *No idle models detected* — a-t-on cassé le
tracking ? »** → Rien de cassé : TROU PRÉEXISTANT rendu visible. Le gouverneur ne connaissait
la résidence que par `BaseModelBackend` (in-process) et `vram_reservation` (sous-processus) ;
l'OLLAMA HÔTE, service séparé, n'y a JAMAIS eu de ligne. `AIModel.is_loaded` disait vrai (il
vient de `/api/ps`) mais `resident_models()`/`idle_models()` — donc la vue « modèles inactifs »
et le nettoyeur — étaient aveugles à plusieurs Go réellement occupés. Trois correctifs :
1. `ModelRegistry.refresh_ollama_residency()` : `/api/ps` → registre du gouverneur (owner
   `ollama-host#ollama:<nom>`, empreinte réelle), et RETRAIT immédiat des modèles qu'Ollama a
   déchargés (laisser expirer au TTL ferait croire le GPU occupé 1 h). Appelée dans
   `_overlay_residency()` — donc à chaque découverte/sync périodique. `_ollama_charges()` rend
   désormais `{nom: Go}` (le `in` de l'unique appelant est inchangé).
2. `MemoryManager.unload_model()` DÉCHARGE VRAIMENT un modèle Ollama (`keep_alive: 0` sur
   /api/generate) au lieu de retourner True sans rien faire — le même mensonge que les anciens
   unloaders, resté invisible tant qu'Ollama n'apparaissait pas dans `idle_models()`.
3. La passe assess rend la VRAM À LA FIN (un seul `unload_model`, puis refresh du registre).
   ⚠ Surtout PAS `keep_alive=0` par appel : ce serait un rechargement complet entre chaque
   candidat — un va-et-vient GPU bien pire sur un hôte fragile. Le modèle des agents locaux est
   RÉSOLU UNE FOIS par passe (`_modele_local_resolu`) : même nom pour réserver, juger, décharger.

**Q2 « je ne vois pas le benchmark sur les cards — est-il dans la confiance ? »** → NON, et
l'intuition est juste : ce sont deux étages distincts. **Confiance** = verdict d'un agent LLM
sur l'opportunité d'ADOPTER un candidat (0-100 %, prospection). **Benchmark tiers** =
PERFORMANCE mesurée par un banc externe (AA / Arena). Le badge n'était affiché que sur les
cards PROPOSÉES (or 5 candidats sur 64 ont un benchmark, contre 13 modèles installés) :
il est désormais sur TOUTES les cards, et l'inspecteur porte une section **Qualité** (visible
pour tout modèle) : benchmark + source, **nom tiers apparié**, échelle, indice a priori,
réserve de quantification.

⚠ **FAUX APPARIEMENT CONSTATÉ** (à traiter dans le chantier benchmark) :
`imager:qwen-image-2` est apparié à **« GPT Image 2 (high) »** (aa_slug `gpt-image-2`,
indice 1369) — deux modèles sans rapport, la famille « image 2 » a suffi. La ligne
« Apparié à » de l'inspecteur existe précisément pour rendre ce genre d'erreur visible à
l'œil humain. Tant qu'il n'est pas corrigé, l'indice de qwen-image-2 est FAUX et sert à la
sélection diffusion.

### Appariement benchmark CORRIGÉ + audit de non-régression (2026-08-19, fin de session)

**Deux erreurs d'appariement mesurées et corrigées** (`benchmark_sync.py`) — elles faussaient
la sélection, qui consomme `benchmark_index` :
1. **Famille = mot commun.** `qwen-image-2` et `GPT Image 2 (high)` donnaient tous deux la
   famille « image » → l'imager local héritait de l'indice 1369 de GPT Image 2. `_avec_prefixe`
   rattache désormais les segments introducteurs (« qwenimage » ≠ « gptimage »), en
   concaténant SANS séparateur pour que les graphies des sources convergent
   (`hunyuan-image-2.1` ↔ `HunyuanImage 2.1` — appariement correct PRÉSERVÉ).
   Effet réel : qwen-image-2 retrouve son vrai jumeau Arena `qwen-image-2512` (Elo 1125,8).
2. **`max(valeur)` sur les variantes.** On prenait la MIEUX NOTÉE d'une famille, jamais celle
   qui correspond : `flux-1-dev` recevait **FLUX.1 Kontext [max]** (1141) au lieu de
   **FLUX.1 [dev]** (1041) ; `qwen3-coder:30b` recevait 14,6 (« Qwen3 30B A3B 2507 Reasoning »)
   parmi **9** candidats compatibles au lieu de « Qwen3 Coder 30B A3B Instruct » (13,6).
   `_choisir_variante` départage par MOTS communs/étrangers (`_mots`, générique — une liste
   fermée de qualificatifs aurait raté « coder »), puis similarité, puis valeur la plus basse.
   Run réel appliqué : 17 appariés, flux-1-dev 1041, qwen3-coder 13,6, qwen-image-2 1125,8.

**Audit de non-régression de la session** (renommages, extraction `task_progress`, `set→dict`,
refactors) : **aucune régression** — tous les appelants vérifiés. Défauts latents corrigés dans
la foulée : passe 100 % cloud qui réclamait 8 Go de VRAM ; report éternel sur machine SANS GPU
(`effective_free_gb` rend 0.0 quand CUDA est absent — on ne reporte plus si aucun GPU) ;
`meilleurs_installes` triait par a priori alors que l'étage benchmark existe (même règle de lot
que `_cle_de_rang` désormais) ; commentaires et section de doc périmés.
RESTE (noté, non fait) : `benchmark_meta` est exposé à tout utilisateur authentifié (données
publiques, mais surface élargie non décidée) ; le déchargement post-passe est hors du bloc de
réservation (fenêtre courte, état final correct).

### Volet droit du model_manager (design, remarques Fabien)
- « Actions du modèle » restait affiché — titre compris — sous un volet sans sélection :
  nouvelle option COMMUNE `WamaInspector.showOnInspect` (symétrique de `hideOnInspect`,
  optionnelle donc sans effet sur les autres apps) + appel `toggleSections(false)` à l'init
  (l'état initial n'était jamais posé). model_manager déclare `showOnInspect: ['actions-section']`.
- Le texte d'accueil ne parlait que de mémoire : le volet est présenté comme le **poste de
  maintenance** du catalogue (prospection / mémoire & modèles chargés / sauvegardes), avec un
  titre de groupe « Mémoire & modèles chargés » devant le bloc système.
- `MM_HINT` dupliquait ce texte en JS (il écrasait le gabarit à la première désélection) :
  il est désormais CAPTURÉ depuis le DOM. `staticfiles/common/js/wama-inspector.js` resynchronisé.
Rendu vérifié par le client Django authentifié (10/10 contrôles) ; validation VISUELLE
navigateur encore à faire (la page exige une session — passer par le skill `/smoke`).

### « MAJ » qui ne met rien à jour — corrigé à la SOURCE (2026-08-19, remarque Fabien)

Symptôme : `qwen3.5:9b` proposé en « MAJ proposée … **Remplace qwen3.5:9b** » — un modèle
proposé en remplacement de lui-même. Deux défauts distincts, tous deux corrigés :

1. **À la source (le vrai problème).** Un candidat `update` sans successeur identifié était
   émis sur le SEUL critère de l'âge d'installation (> 120 j) : il proposait de re-tirer le
   même tag sans savoir si le distant avait changé. Le **digest** tranche — vérifié le
   2026-08-19 : le `digest` publié par `/api/tags` est exactement le sha256 du manifeste
   distant, les deux se comparent donc directement. Briques ajoutées :
   `ollama_registry.digest_distant()` (sha256 du manifeste, via le nouveau `_manifeste_brut`
   que `taille_go` partage désormais) et `update_checker.digests_locaux()`.
   Règle : digest identique ⇒ **aucun candidat** (et l'ancien est purgé, il n'est plus dans
   `vus_maj`) ; digests différents ⇒ candidat qualifié « nouvelle version publiée sous le
   même tag » (confiance 0,9, sur PREUVE et non sur l'âge) ; digest indéterminable (réseau)
   ⇒ comportement d'avant. Le résumé porte `identiques` pour expliquer l'écart de comptage.
   **Run réel : les 8 candidats « MAJ » existants étaient TOUS de faux positifs** (même
   digest des deux côtés) — purgés. La liste « ✨ Proposés par IA » perd 8 entrées de bruit.
2. **À l'affichage.** « Remplace X » n'a de sens que pour un SUCCESSEUR : la card et
   l'inspecteur se basent désormais sur `prospect.cible` (le successeur nommé), pas sur
   `origin_key` (qui, sur une MAJ d'âge, désigne le modèle lui-même). Les autres cas sont
   qualifiés honnêtement : « Nouvelle version du même tag » (republication prouvée) ou
   « Ancienneté d'installation ». Nouvelle ligne d'inspecteur « Nature de la MAJ »
   (`prospect.maj` = successeur | republication | age).

### Une évaluation LLM n'est JAMAIS purgée (2026-08-19, question « pas de réintroduction erronée ? »)

Vérification du cycle complet (2 prospections d'affilée) demandée avant clôture. Elle a
révélé un défaut réel, corrigé : **le tri « tendance » de HuggingFace bouge en continu**, donc
la liste retenue change presque entièrement d'un run à l'autre (mesuré : 32 créés / 31 purgés,
puis 31 / 32). La purge ciblée détruisait alors les candidats évalués — **13 évaluations LLM
perdues au test**, badges de confiance disparus, GPU dépensé pour rien.

Règle posée, aux trois purges (`prospect_ollama` update + new, `seed_hf_candidates`) : un
candidat porteur de `prospect.assess` **n'est jamais supprimé automatiquement** ; il reste
jusqu'à ce qu'un humain le rejette. C'est la même règle que `ecrire_candidat`, qui préservait
déjà l'évaluation à l'ÉCRITURE — elle manquait à la SUPPRESSION. Les résumés portent
`preserved`. Prouvé : un candidat évalué survit à deux cycles consécutifs (`preserved: 1`),
et aucune « MAJ âge seul » ne réapparaît (`identiques: 5→8`).

⚠ RESTE (comportement, non corrigé) : la liste HF non évaluée se renouvelle presque
intégralement à chaque prospection — c'est la nature du signal « tendance », mais l'affichage
ne le dit pas. Piste si ça gêne : afficher la provenance (téléchargements vs tendance) sur la
card, ou n'appliquer le trending qu'à une part fixe des places.

⚠ Piège évité au passage : `_manifeste_brut` avait été écrit avec `@lru_cache` (copié de
`taille_go`) — le digest distant aurait été figé pour la vie du process, rendant TOUTE
republication indétectable. Cache retiré là, conservé sur `taille_go` (une taille ne bouge pas).

### Chaînage automatique des lots d'évaluation (2026-08-19, décision Fabien)

Un lot de 10 imposait 6 clics pour ~56 candidats. **Fabien a raison sur la VRAM** : la passe
est séquentielle, un seul modèle chargé — tout enchaîner n'en consomme pas plus, le lot n'a
jamais protégé de ça. Le seul enjeu réel est la **file** : le worker `gpu` est en `--pool=solo`,
donc une tâche de 30 min immobilise le seul exécutant GPU et un traitement utilisateur (palier
supérieur) attend la fin.

D'où le choix : **ré-enfiler** la passe suivante (`apply_async`, countdown 5 s) plutôt que
boucler dans la tâche. Le worker se libère entre deux lots (la file reprend la main), la garde
de ressources est réévaluée à chaque lot, et un échec ne perd qu'un lot. Un seul clic traite
désormais toute la file. Arrêts — jamais de boucle folle : `remaining == 0` ; `assessed == 0`
(agents injoignables : ré-enfiler une passe qui n'avance pas serait une boucle) ; passe
REPORTÉE par le gouverneur (GPU occupé). L'état publié reste `RUNNING` pendant le chaînage
(sinon le poller annoncerait « terminé » au premier lot) et l'UI affiche l'avancement GLOBAL
(« Lot terminé (N évalué(s)) — M restant(s), suite en cours… »).

Vérifié sans GPU (agent cloud sans clé → échec immédiat) : aucun verdict ⇒ **pas de
ré-enfilement**, et les 4 combinaisons d'arrêt/poursuite se comportent comme spécifié.
SUITE possible (Fabien) : supprimer complètement les lots si le chaînage donne satisfaction.

## Session du 2026-08-26 : le juge voit les VARIANTES QUANTISÉES + budget VRAM dynamique

**Biais mesuré** (question Fabien sur MiniMax-Music3 à 10 %) : le contexte du juge
(`_contexte_hf`) ne portait que le poids des **poids pleins** (`disk_gb`, 53,4 Go) et le
prompt gravait « tient sur 24GB » en dur. Verdict inévitable : *recommend=false, confiance
0.9* → score 0.10 — et il l'aurait été pour **tout** gros modèle, même dominé par ses
repacks : le repack single-file de la famille pesait 551 k téléchargements, invisible du
juge. Le seeding, lui, **écarte exprès** ces dépôts (`_MOTIFS_BRUIT`) : ce qui est du bruit
pour la liste des canoniques est l'information du juge de confiance.

**Livré :**
- `prospector.variantes_quantisees(hf_id)` — dépôts dérivés quantisés (GGUF/FP8/4-8bit/AWQ/
  GPTQ + repacks Comfy), recherche LARGE (radical sans numéro de version : « MiniMax-Music »
  retrouve « MiniMax-Music-3 » du repackageur) / filtre STRICT (nom complet normalisé +
  marqueur), tri téléchargements, 2 requêtes réseau. `_MOTIFS_QUANT` inclut `comfy` : le
  repack le plus téléchargé n'a AUCUN marqueur de quantisation dans son id (mesuré).
- `_attacher_variantes_quantisees(cand)` — relève et PERSISTE une fois
  (`extra_info['prospect']['quant_variants']`, idempotent, à l'évaluation seulement, jamais
  au seeding) ; `_contexte_hf` ajoute le bloc « ⚠ le poids ci-dessus est celui des poids
  PLEINS… la faisabilité VRAM se juge sur les variantes ».
- **Budget VRAM DYNAMIQUE** (remarque Fabien : « le rejet dépend de l'infrastructure
  derrière ») : `_vram_totale_gb()` (torch, repli 24.0) injecté dans le prompt système
  (`_system_agent()` remplace la constante `_AGENT_SYSTEM`) ET dans les critères de
  `_juger` — le passage à un autre hôte (R760xa) changera le budget sans retoucher les
  prompts. Le critère dit aussi au juge que la plateforme sait décharger les composants
  inactifs d'une pipeline en RAM système (offload, prix = vitesse).

**Re-jugement** : la passe ne traite que `confidence IS NULL` (idempotence) — pour re-juger
un candidat après enrichissement du signal, remettre sa confiance à NULL. Fait pour
MiniMax-Music3 (ancien verdict conservé dans `assess`, écrasé à la prochaine passe).
Testé réel (réseau, sans GPU ni passe LLM) : 6 variantes relevées pour MiniMax-Music3,
contre-épreuve vide sur un dépôt obscur, contexte du juge complet, `manage.py check` propre.

**Couverture par catégories (état au 26/08)** : la table du § « ÉTAT DES LIEUX » reste
juste — 9 tâches HF + rôles Ollama ; absents par CHOIX : VLM HF (doublon rôle Ollama),
lipsync/avatars (chantier séparé). **Trou à venir : 2D→3D** (chantier annoncé) — HF a les
pipeline_tags `image-to-3d`/`text-to-3d`, l'extension est déclarative (2 entrées `HF_TASKS`)
MAIS demande d'abord de trancher la catégorie d'installation (`ModelType` n'a pas de valeur
3D ; l'enum mélange déjà famille/modalité/tâche, cf. son commentaire — ne pas aggraver sans
décision).

### Passe relancée par Fabien (26/08 après-midi) : verdict Music3 INVERSÉ, crash hôte au 3ᵉ, audit

**Le signal a fait son travail** : MiniMax-Music3 est passé de 0.10 (« 53 Go > 24 Go ») à
**0.90, recommend=true, vram_fit=ok** — le juge cite explicitement les GGUF (« exécution
fluide sur 24 Go »). Wan2.1-T2V-1.3B jugé 3 s après (0.90), puis **crash hôte pendant le 3ᵉ
candidat** (Z-Image-Turbo) : verdict 13:35:08, plus aucune ligne applicative, gouverneur
réinitialisé au reboot 13:40 — signature « panne SOUS l'OS » identique au 19/08 et aux morts
au repos ; AUCUNE trace d'un problème applicatif.

**Audit du câblage à la demande de Fabien (« pas d'empilement ? bien branché au
gouverneur ? ») — VÉRIFIÉ SAIN, aucun empilement possible** :
garde `effective_free_gb` avant chaque lot (driver − réservations déclarées) → réservation
dimensionnée sur l'empreinte RÉELLE de l'agent (7.6 Go lus au catalogue, repli 8) → jugements
STRICTEMENT séquentiels (worker `gpu --pool=solo`, agents en boucle, Ollama NUM_PARALLEL=1)
→ décharge RÉELLE en fin de lot (`MemoryManager.unload_model` → `keep_alive: 0`, plus un
mensonge depuis le 19/08) + `refresh_ollama_residency` ; réservations orphelines d'un crash
purgées par TTL (constaté 12:45 le jour même). Le cycle décharge/recharge PAR LOT du
chaînage est le compromis DÉJÀ arbitré (garder le modèle résident entre deux lots serait de
la VRAM invisible du gouverneur — le trou des kernel panics du 29/07).

**Durcissements appliqués au passage (mes ajouts de la veille élargissaient la fenêtre)** :
- `_vram_totale_gb()` → `lru_cache` : UNE lecture driver par process (c'était 2 par
  jugement — geste GPU à minimiser sur cet hôte) ;
- **préparation des contextes HORS fenêtre GPU** : variantes quantisées + carte HF = du
  réseau (proxy, plusieurs secondes par candidat) qui se faisait DANS la réservation, juge
  résident. Désormais préparé AVANT `vram_reservation` : la fenêtre ne contient plus que
  les `llm_chat`. (Honnêteté : rien ne prouve un lien avec le crash — le pattern précède
  ces ajouts — mais raccourcir la fenêtre résidente est sain quoi qu'il en soit.)

## Session du 2026-08-27 : la chaîne d'installation se REFERME — catalogue, désinstallation, choix de variante

**Le cas d'école qui a tout révélé** : l'installation de MiniMax-Music3 lancée le 26/08 a
ABOUTI (54 Go téléchargés, tâche Celery en succès à 15:43 — le worker WSL2 a même survécu au
kill SentinelOne de 15:32 côté Windows)… et le modèle était INVISIBLE partout : plus en
prospection (candidat supprimé après succès — comportement normal), absent du catalogue
(la découverte est déclarative par app, aucune app ne le déclarait), donc invisible du
composer. `pull_hf_model` l'assumait déjà : « téléchargé + catalogué ≠ utilisable ». Trois
trous refermés (ordre décidé par Fabien) :

**1. Balayage générique des snapshots installés** (`_discover_installed_hf_snapshots`,
model_registry) — tout `models--org--nom` sous `AI-models/models/<cat>/<famille>/` est
catalogué (`huggingface:<hf_id>`, taille mesurée sur blobs, format, `.incomplete` ⇒ NON
téléchargé). Double dédup : par `hf_id` (l'entrée d'app fait autorité) ET par **famille
`MODEL_PATHS`** — transcriber/synthesizer/anonymizer ne posent pas de `hf_id` dans leur
découverte, sans ce 2ᵉ critère 16 doublons de fait apparaissaient (mesuré, purgés).
`MODEL_PATHS` est LA déclaration « ce dossier appartient à une app » (checklist étape 1) :
le balayage ne couvre que les familles qu'aucune déclaration ne revendique. Un échec du
balayage alimente `discovery_errors` (règle SAM3 : découverte incomplète = réconciliation
suspendue). ⚠ Catalogué ≠ utilisable : `backend_ref` reste vide, l'usage par une app reste
conditionné à sa déclaration + un backend.

**2. Désinstallation** (`uninstall_model` + `api_model_uninstall` + action « Désinstaller »
de l'inspecteur) — retrait des POIDS seuls (Ollama via `/api/delete`, snapshot HF via
suppression du dossier + verrous `.locks`), **jamais du backend** (léger, réutilisable) ;
la ligne de catalogue est MARQUÉE (`is_downloaded=False`, `uninstalled_at`), jamais
supprimée — elle porte l'historique (stats runtime, ETA, identité/licence). Gardes :
modèle chargé → refus (décharger d'abord) ; candidat → refus (ça se rejette) ; chemin hors
de `models_root()` → refus (le rm -rf est BORNÉ, quoi que dise la base).

**3. Choix de variante AVANT installation** (`options_installation`/`spec_pour_choix` +
`api_prospect_install_options` + dialogue radio à la place du `confirm()`) — poids pleins
ET variantes quantisées, chacune avec Go disque / note VRAM / téléchargements. Le vice de
forme corrigé : le juge évalue la faisabilité VRAM sur les VARIANTES (verdict 0.90), mais
l'installation tirait TOUJOURS le dépôt canonique — 54 Go inexploitables sur 24 Go de VRAM.
Un dépôt GGUF descend AU FICHIER (`allow_patterns` — jamais le dépôt entier et ses N
niveaux de quantisation). Le choix validé est PERSISTÉ dans le spec du candidat (la tâche
Celery relit la base ⇒ la sélection est respectée de bout en bout) ; la garde d'espace se
calcule sur le poids du CHOIX.

**Remplacement réel exécuté dans la foulée** (test réel de la chaîne) : poids pleins
désinstallés (53,4 Go rendus), jeu GGUF **Q8_0 complet** installé depuis
`Serveurperso/MiniMax-Music3-GGUF` (~11,9 Go — language_model + transformer +
rvq_depth_decoder + vocoder + condition_encoder, regroupés sous la famille canonique
`music/MiniMax-Music3/`).

**Enseignement pour la suite (limite ASSUMÉE du choix par fichier)** : MiniMax-Music3 est
MULTI-COMPOSANTS — « un fichier GGUF » n'est pas un modèle complet, il en faut un JEU
cohérent (5 fichiers ici). Le dialogue propose aujourd'hui une ligne par fichier : correct
pour les dépôts mono-modèle (cas LLM typique), partiel pour les dépôts multi-composants
(installer les autres composants = repasser par l'installation, ou spec manuel). À
généraliser si le cas se représente — pas avant (YAGNI).

**Restes connus** : ① ~~backend composer pour MiniMax-Music3~~ **LIVRÉ le jour même, voir
ci-dessous** ; ② ~~les découvertes transcriber/synthesizer/anonymizer ne posent pas `hf_id`~~
**SOLDÉ le 2026-08-27 (session suivante)** : la provenance est DÉCLARÉE à la source
(`SYNTHESIZER_MODELS.hf_id`, `YOLO_WEIGHTS_HF_ID` + `SAM3_HF_REPO` côté anonymizer,
`hf_model_id` déjà déclaré côté transcriber) et les trois découvertes la posent sur
`ModelInfo.hf_id` — les valeurs coïncident avec celles posées en base par le `--poser` du
12/08 (vérifié ligne à ligne), qui deviennent ainsi STRUCTURELLES (elles survivent à une
réinstallation). ⚠ Le critère FAMILLE du balayage snapshots reste NÉCESSAIRE : le dépôt
déclaré n'est pas toujours celui du snapshot sur disque (déclaré `openai/whisper-large-v3`,
disque `Systran/faster-whisper-large-v3` — la dédup par hf_id ne les relie pas) ;
③ après une désinstallation, la prospection peut re-proposer le
modèle à sa prochaine passe (la ligne marquée `is_downloaded=False` n'est plus « have ») —
comportement à trancher si gênant.

### Suite du même jour : le BACKEND COMPOSÉ — l'anatomie se déclare, le moteur l'exécute

**Doctrine actée avec Fabien (design à 3 étages — « deux affirmations vraies à des étages
différents ne se contredisent pas »)** : ① l'anatomie d'UN modèle multi-composants vit dans
son manifeste `model` (`body.composition` : components + runtime, cf.
`WAMA_MANIFEST_SPEC.md §7.1`) — l'installation en dérive ses `allow_patterns`
(`patterns_from_composition`), le backend en dérive quoi charger ; ② la liaison
app ← modèle ← librairie = `requires` (existant) ; ③ le kind `pipeline` (canvas studio)
reste l'étage INTER-APPS — pas celui d'un backend. La porte « projet GitHub → app + libs +
modèles » = manifeste `project` + `requires`, chaque kind dispatché vers son driver
existant : rien de ce qui précède ne la bloque, Music3 en a éprouvé chaque maillon sauf la
génération d'app.

**Livré (Music3 = premier modèle intégré SANS backend spécifique)** :
- `AIModel.composition` (migration 0015) — fait DÉCLARÉ projeté par le manifeste, même
  nature que `license`/`prompt_contract` ; validation du kind (`_validate_composition`) ;
- `install_from_spec` accepte `spec.composition` → `allow_patterns` dérivés (testé réel :
  **14 fichiers** tirés du package officiel `audio-cpp/MiniMax-Music3-GGUF` — 5 GGUF Q8
  déclarés + `config/` + `tokenizer/`, ~12,6 Go — jamais le dépôt entier) ;
- **moteur audio.cpp** (Apache 2.0, github.com/0xShug0/audio.cpp) compilé CUDA sur l'hôte
  WSL2 (`~/tools/audio.cpp`, HORS dépôt — un moteur n'est pas du code WAMA ; binaire 330 Mo,
  RTX 4090 vue). Override par env `AUDIOCPP_BINARY` (motif FFMPEG_BINARY) ;
- `AudioCppBackend` (composer) — GÉNÉRIQUE : lit `composition` de la ligne d'app
  (`composer:<id>`), traduit rôle→`--session-option <famille>.<rôle>_gguf=<fichier>`,
  sous-processus sous `vram_reservation` (motif MuseTalk — charge hors process) ; paroles :
  le prompt se coupe au premier tag `[verse]`/`[chorus]` (sans tag → `[instrumental]`),
  contrat annoncé dans la description du modèle ;
- dispatch `tasks.py` par le discriminateur `backend: 'audiocpp'` de `COMPOSER_MODELS`
  (défaut AudioCraft inchangé) ; entrée `minimax-music3` déclarée (checklist complète :
  MODEL_PATHS + model_config + backend + découverte via COMPOSER_MODELS).

**⚠ Piège documenté au passage** : les GGUF de `Serveurperso/MiniMax-Music3-GGUF` (266 k
téléchargements) sont des fichiers NUS pour le port `minimaxmusic.cpp` de leur auteur —
audio.cpp exige un RÉPERTOIRE-package (`config/` + `tokenizer/` + composants). Un dépôt
quantisé se choisit donc AUSSI par son runtime cible, pas seulement par ses téléchargements.
Le set Serveurperso a été désinstallé via la chaîne (11,9 Go rendus) ; les lignes de
stockage `huggingface:*` redondantes purgées — **l'entrée d'app `composer:minimax-music3`
est l'autorité unique** (composition, licence `minimax-music3-community`, provenance).

**Licences vérifiées** : audio.cpp = Apache 2.0 (compatible AGPL-3.0) ; poids =
MiniMax-Music3 Community License — pas d'exclusion UE, commercial libre < 20 M$/an,
obligations : afficher « MiniMax-Music3 » dans l'UI (fait — le nom du modèle est affiché)
et divulguer le caractère généré du contenu diffusé. Détail : `LICENSING.md`.

### Install EXPLICITE des modèles du catalogue (même session, question Fabien sur musicgen-melody)

**Le trou** : un modèle d'app « Not downloaded » (musicgen-melody) s'affichait sans AUCUN
geste — l'affichage est VOULU (découvrabilité : un utilisateur sans accès au model_manager
doit savoir que le modèle existe ; le téléchargement au 1er usage reste le filet), mais
l'installation explicite n'existait que pour les candidats de prospection.

**Refermé** : la DÉCOUVERTE d'app déclare l'emplacement (`extra_info['install_dir']` —
posé par `_discover_composer_models`, généralisable aux autres apps en une ligne chacune) →
`spec_for_catalog_row` dérive le spec (category/family du chemin relatif à `models_root`,
`composition` embarquée si déclarée — un modèle composé tire son jeu cohérent) →
`install_catalog_task` (Celery, même cache de progression que les candidats → même suivi
UI) → bouton « Installer » à l'inspecteur pour tout modèle non téléchargé porteur de
`hf_id` + `install_dir`. Garde d'espace : poids du catalogue, sinon relevé HF, sinon refus
prudent forçable. Le registre n'invente JAMAIS d'emplacement : sans déclaration d'app, pas
de bouton — premier usage seulement.

**Skills officiels MiniMax** : `github.com/MiniMax-AI/MiniMax-Music3/tree/main/skills`
(`music-caption-rewriter` : SKILL.md + 18 familles de styles + 1000 templates) — notre
transposition assumée : la MÉTHODE dans `composer-music.md`, la SORTIE dans le
`prompt_contract` du manifeste (le skill complet est taillé pour un agent code, pas pour
l'enrichissement LLM local). Réf. croisée : `prompt_skills/README.md`.

### Rôles SCOUT et INTEGRATOR livrés (même session, plan validé Fabien) — étapes 2-4 de la route

Les deux frères du librarian existent (`wama-dev-ai/`), même discipline BORNÉE (squelette
mécanique → UN appel LLM → contrôles mécaniques → `outputs/` PENDING_HUMAN_VALIDATION,
jamais d'auto-application) :

- **`run_scout.py`** (+ `prompts/scout.txt`) — dépôt HF → manifeste `model` : identité/
  licence/tailles/inventaire des poids relevés MÉCANIQUEMENT (API HF, les faits re-priment
  sur la réponse LLM), le LLM juge `model_type` (taxonomie fermée), `capabilities`,
  `composition` (multi-composants : un fichier par rôle, q8 préféré ; runtime SEULEMENT si
  la carte le nomme) — et signale les dépôts de quantisation NON autoportants (leçon
  Serveurperso : un dépôt quantisé se choisit aussi par son runtime cible).
- **`run_integrator.py`** (+ `prompts/integrator.txt`) — manifeste `model` (+ besoin) →
  décision **app existante vs génération d'app** : contexte mécanique = `APP_CATALOG` réel
  (descriptions longues + entrées/sorties) + référentiel des modèles installés du type ;
  verdict JSON {decision, app, confidence, integration.needs, alternatives, concerns} ;
  contrôles : l'app recommandée doit exister au catalogue, `new_app` renvoie à
  `WAMA_APP_GENERATION_ROUTE.md` (validation humaine, jamais exécutée). ⚠ Le prompt
  `architect.txt` préexistant est un AUTRE rôle (conseil d'architecture de code) — d'où le
  nom `integrator`.
- **`role_utils.py`** — helpers communs extraits du librarian (ollama gateway, fetch,
  extract_json, write_output) ; le librarian les adopte (zéro duplication).
- **`--dry-run` sur les deux** : squelette/contexte SANS appel LLM — c'est le mode de test
  des sessions Claude (la passe LLM tourne sur l'Ollama HÔTE, le déclencheur de crash
  identifié : elle se lance sur décision humaine, comme la passe de confiance). Dry-runs
  VALIDÉS réels : scout sur `audio-cpp/MiniMax-Music3-GGUF` (squelette complet, licence
  `other` relevée, 54,1 Go, inventaire trié), integrator sur le manifeste corpus de
  minimax-music3 (catalogue d'apps complet — et l'exercice a révélé une description
  composer PÉRIMÉE, corrigée : elle ignorait Music3).

**Restes de la route après cette session** : ① brancher scout/integrator sur la prospection
(un candidat retenu → scout → integrator → recommandation sur la card) ; ② outils
model_manager du `tool_api` (`search_models`/`prepare_install_spec`/`install_model`) pour
que l'AI-Assistant WAMA porte le workflow ; ③ le MARCHEUR `project`→`requires`→drivers
(« installer un projet ») ; ④ ~~`hf_id` à DÉCLARER dans les model_config
transcriber/synthesizer/anonymizer~~ **SOLDÉ le 2026-08-27, session suivante** (voir
« Restes connus » ② ci-dessus : déclaration à la source + 3 découvertes qui posent
`ModelInfo.hf_id`, critère famille conservé, 4 tests `ProvenanceDeclareeTest`).

**Validation restante (HUMAINE — jamais de charge GPU lancée par une session sur cet
hôte)** : redémarrer les services puis générer depuis le composer avec `minimax-music3`,
ou en CLI :
`~/tools/audio.cpp/build/linux-cuda-release/bin/audiocpp_cli --task gen --family
minimax_music3 --model <snapshot> --backend cuda --text "..." --request-option
"lyrics=[verse] ..." --request-option duration_sec=20 --out /tmp/music3.wav`
(+ `--session-option minimax_music3.language_model_gguf=language_model_q8_0.gguf` etc. —
le backend WAMA construit exactement cette commande depuis la composition). L'ETA
(`gen_factor=6.0`, `overhead_s=120`) est PROVISOIRE, l'estimateur auto-apprenant affinera.

**2026-08-28 — 1ʳᵉ génération (Fabien) : défaut MOTEUR trouvé et contourné.** audio.cpp
ouvre ses composants PAR DÉFAUT en dur (`assets.cpp` : `language_model_q4_0.gguf`,
`transformer_q4_0.gguf`) AVANT d'appliquer les `--session-option` qui les remplacent
(`session.cpp`) → notre package Q8 échouait « missing MiniMax Music 3 component GGUF:
…language_model_q4_0.gguf » sans que l'override soit jamais lu. Contournement :
`audiocpp_backend.ensure_engine_default_aliases()` pose des liens symboliques
défaut→variante déclarée dans le snapshot (idempotent, jamais par-dessus un vrai fichier ;
`_ENGINE_EAGER_DEFAULTS`). À retirer si audio.cpp applique un jour ses overrides avant
d'ouvrir ses défauts. Leçon (sœur du « juge sur VARIANTES / installeur CANONIQUE ») : **la
composition déclarée ne suffit pas si le moteur a ses PROPRES noms câblés** — vérifier les
défauts du moteur au moment de choisir la variante à installer.

## Session du 2026-08-28 : le cas MiniMax-H3 — un canonique INVISIBLE de ses propres tâches

**Question Fabien** : les modèles vidéo sortent avec une confiance très basse — la détection
des variantes quantisées marche-t-elle, et rien n'est jouable sur 24 Go pour H3 ?

**Diagnostic (tout mesuré)** :
1. **Le mécanisme des variantes (26/08) est sain** — testé live : `variantes_quantisees`
   sur le canonique relève les bons dépôts (repack Comfy-Org 19 M dl, jeux GGUF/nvfp4
   descendant à ~11 Go). Les Wan jugés le 26/08 portent leurs variantes et sont à 0.90.
2. **Mais 12 verdicts dataient d'AVANT le correctif** (jugés 19/08, `quant_variants`
   absent, figés par l'idempotence `confidence IS NULL`) — dont les deux « H3 » de l'UI,
   qui étaient de surcroît des MERGES de particuliers (0 dl / NSFW 354 Go), pas le modèle.
   → Actions (validées Fabien) : les 2 merges REJETÉS ; les 12 verdicts remis à NULL,
   re-jugement à la prochaine passe MANUELLE (le déclenchement reste humain — historique
   de crashs hôte). ⚠ Un rejet = delete sans pierre tombale : le merge à 0 dl peut
   revenir par le tri tendance (limitation connue, sœur de « re-proposition après
   désinstallation »).
3. **Le vrai trou : le canonique `MiniMaxAI/MiniMax-H3` n'entrait JAMAIS au seeding** —
   son `pipeline_tag` HF est `image-text-to-video`, absent de `HF_TASKS` (qui balayait
   text-to-video / image-to-video). Seuls ses dérivés taggés text-to-video remontaient :
   filtrés comme bruit pour l'essentiel, et les deux merges passants récoltaient les 10 %.
   **Une famille de tags multimodaux grossit sur HF** (`text-to-audio-video`,
   `image-to-audio-video`…) — le balayage par pipeline_tag ne voit que ce qu'il nomme.

**Livré** : entrées `image-text-to-video` + `text-to-audio-video` dans `HF_TASKS` et
`_TASK_MODEL_TYPE` (sondé : le canonique sort en tête, dérivés écartés) ; `_MOTIFS_BRUIT`
complété de `quant`/`awq`/`gptq` (mesuré le jour même : « Hippotes/LTX-2.3-quants »
passait comme canonique).

**Jouable sur 24 Go pour H3 : OUI** — unet pruned nvfp4 11,7 Go / GGUF Q4_K 10,6 Go /
fp8 19,5 Go (+ text encoder qwen3vl-32B Q4 13,6 Go déchargeable après encodage, VAE
vidéo 4,9 Go, VAE audio 0,6 Go). ⚠ Avant install : H3 est MULTI-COMPOSANTS
(`body.composition` à déclarer) et *un dépôt quantisé se choisit AUSSI par son runtime
cible* (single-files écosystème Comfy vs canonique `library: minimax-h3` format
diffusers) — même leçon que Music3/audio.cpp.

### Suite 2026-08-29 — la relance de Fabien fait SORTIR le canonique… et sa licence l'ÉLIMINE

Le seeding corrigé fonctionne : MiniMax-H3 (4,8 M dl) sort en card `image-text-to-video`.
Mais la vérification AU TEXTE (réflexe Hunyuan, `LICENSING.md`) tranche : **la
« MiniMax H3 Community License » EXCLUT l'Union européenne** (« Excluded Territories
means the European Union, the United Kingdom, the Republic of Korea and the United
States of America » — l'accord se limite expressément à l'« Applicable Territory »).
**Toute la famille H3 est donc inutilisable au labo**, dérivés compris : les tags
`apache-2.0` (lightx2v/Minimax-h3-Turbo) et `mit` (Motion-Adapter) des repackageurs
sont des relicensings sans valeur — un « Model Derivative » reste soumis à l'accord
amont (licence à DOUBLE ÉTAGE, le piège déjà consigné sur LivePortrait/Hallo2).
NB : Music3 (audio) n'est PAS concerné — sa MiniMax Community License, vérifiée le
27/08, n'a pas de clause territoriale.

- Alternative vidéo du créneau, licence saine : **famille Wan (Apache 2.0)** —
  Wan2.2-TI2V-5B jugé 0.90 avec variantes int4/8bit relevées, format Diffusers natif.
- Trou de filtre refermé au passage (mesuré sur les cards du jour) : `controlnet` +
  `adapter` ajoutés à `_MOTIFS_BRUIT` (add-ons non autonomes, même famille que `lora`).
- **Garde « Excluded Territories » LIVRÉE le jour même** (arbitrage Fabien : on AFFICHE
  l'incompatibilité, on ne rejette JAMAIS — le choix reste à l'utilisateur) :
  `prospector.analyse_licence(hf_id, license_id)` — un SPDX permissif (`_LICENCES_SURES`)
  rend None ; sinon le TEXTE du LICENSE est lu (endpoint `raw`, zéro passage par le cache
  HF) et scanné (« excluded/restricted territories », « european union » en contexte
  d'exclusion). Verdict persisté au seeding (`prospect.license_flag`, mémoïsé par process),
  affiché sur la card (rouge « UE EXCLUE … le choix vous appartient » / discret « licence à
  vérifier ») et à l'inspecteur (ligne « Compatibilité de licence », section Prospection).
  Testé réel : H3 → `exclusion_ue` avec l'extrait exact de la clause ; Wan (apache-2.0) →
  rien ; LTX-2.5 (`other` sans fichier LICENSE) et stable-audio (`stabilityai-ai-community`)
  → « à vérifier » motivé. ⚠ Les candidats DÉJÀ en base ne portent le verdict qu'au
  prochain sweep (le seeding recrée les lignes) — et le restart est requis d'abord.
- **Wan3.0 (question Fabien 29/08) : sorti le 24/08, mais poids FERMÉS** — API payante
  Alibaba Cloud seulement ($0.05–0.20/s), « the open Wan line stops at Wan 2.2 ». La
  prospection HF ne peut pas le proposer ; le trending le sortira si des poids paraissent.

## Session du 2026-08-31 : recherche CIBLÉE + purge des faux « Nouveau » + conversion réparée

**Constat Fabien** (revue des cards speech) : ① un modèle prometteur repéré à la main
(`Audio8/Audio8-TTS-Preview-0.6b` — 0,6B, 11 langues dont FR, clonage zero-shot,
Apache-2.0, variante ONNX INT4 CPU-only) **ne peut mathématiquement pas sortir** du
balayage — 20 k dl/mois face au plafond top-3/tâche par téléchargements (chatterbox 1,8 M,
Kokoro-ONNX 1,7 M) ; ② `Qwen3-ASR-1.7B` s'affichait « Nouveau » alors qu'il est INSTALLÉ
(`transcriber:qwen3-asr-1.7b`) ; ③ le bouton de conversion ONNX de Kokoro était inactif.

**Livré (tout mesuré sur la base live)** :
1. **`prospector.seed_hf_search(query)`** — prospection CIBLÉE, pendant UI du `--search`
   de `prospect_models` (leçon 2026-08-04). Une requête `search=` SANS filtre de tâche
   (l'utilisateur ne connaît pas le `pipeline_tag` ; il est lu sur chaque résultat et doit
   figurer dans `HF_TASKS`) ; `_NOISE_MARKERS` non appliqués (une demande NOMMÉE n'est pas
   un listing subi) ; AUCUNE purge (la recherche AJOUTE). Exposée par
   `api_prospect_ollama` (corps `{"search": …}`) et par le champ « Rechercher un modèle
   précis » du volet prospection (`mmProspectSearch`, Entrée ou loupe). ⚠ Aucune trace git
   d'un champ antérieur (sondes `-S` sur l'historique du gabarit) : le geste n'existait
   qu'en CLI — c'est une CRÉATION, pas une restauration.
   Testé réel : `seed_hf_search('Audio8-TTS')` → 5 candidats créés (canonique 0.6b, 0.1b,
   ONNX INT4/INT8, repack mlx — ce dernier passe car les marqueurs de bruit sont
   volontairement débrayés ici).
2. **Purge des candidats DEVENUS installés** (`seed_hf_candidates`) : un candidat dont le
   `hf_id`/`platform_ref` correspond à une ligne NON proposée est purgé au sweep suivant,
   **même évalué** — la garde d'évaluation (2026-08-19) protège un travail encore utile,
   pas une proposition sans objet. Le résidu Qwen3-ASR-1.7B a été purgé à la main dans la
   foulée (1 ligne).
3. **Conversion de formats RÉPARÉE — 3 verrous empilés** (le bouton Kokoro n'était que le
   premier) : ① `can_convert_to` était CÂBLÉ par la découverte synthesizer (`[]` pour
   kokoro/higgs — bouton jamais rendu ; `['onnx','safetensors']` pour coqui/bark — promesse
   qui aurait toujours échoué) → recalé à l'HONNÊTE (`['safetensors']` pour les .pt/.pth ;
   l'ONNX d'un pipeline TTS ne se FABRIQUE pas par la route générique — `input_shape`
   jamais fourni, multi-composants — il s'INSTALLE : export officiel
   `onnx-community/Kokoro-82M-v1.0-ONNX` via la prospection) ; ② `api_convert_and_backup`
   traitait l'ID de catalogue (`synthesizer:kokoro`, envoyé par l'UI) comme un CHEMIN →
   « Source file not found » systématique pour tout modèle déclaré par app — nouvelle
   résolution `_resolve_weight_file` (ID → `AIModel.extra_info['path']` → registre ;
   dossier/snapshot HF → plus gros fichier de poids convertible) ; ③ la chaîne
   backup-avant-suppression (`_retire_source`, offload vérifié) était SAINE — rien touché.
4. **Installations via le pipeline existant** (`install_proposed_task` →
   `install_from_spec` → sync + provenance) : Kokoro-82M-v1.0-ONNX (1,3 Go),
   ResembleAI/chatterbox (12,9 Go), Audio8-TTS-Preview-0.6b — 87 Go libres vérifiés
   (garde d'espace de la vue court-circuitée par l'enfilage direct, contrôle fait à la
   main). ⚠ « téléchargé + catalogué » ≠ « moteur du synthesizer » : l'usage exige un
   backend (`chatterbox-tts`, `kokoro-onnx`, runtime Audio8) — chantier séparé, cf. la
   règle du balayage générique (« backend_ref reste vide : catalogué ≠ utilisable »).

### Suite du même jour — 3 installs CONCURRENTES croisent les identités (2 bugs provenance)

Les 3 manifestes `model` ont bien été écrits au corpus par la chaîne
(`record_after_install` → `set_identity` → `manifest_export`) — mais **avec l'identité de
Kokoro-ONNX posée sur les trois** (`hf_id`/`author`/`platform_ref` croisés, chatterbox
étiqueté `apache-2.0` au lieu de `mit`), plus **2 manifestes `proposed__*` orphelins**.
Deux causes, toutes deux dans `provenance.record_after_install` :

1. **`added_keys` liste ce que LE SYNC vient de créer, pas ce que CETTE installation a
   installé.** La première install finie (Kokoro-ONNX, 3 min 52) a synchronisé pendant que
   les deux autres téléchargeaient : son sync a découvert LEURS snapshots partiels
   (`incomplete: true` figé dans les manifestes), `added_keys` = les 3 lignes, et elle a
   posé SON identité sur les trois. → **Garde de concordance** : une ligne dont le `hf_id`
   (posé par la découverte) est étranger à l'identité du spec est écartée.
2. **Le repli par `platform_ref` attrapait la ligne CANDIDATE encore vivante** (elle n'est
   supprimée qu'après la provenance, et `write_candidate` pose le même `platform_ref`) →
   manifeste `proposed__*` exporté, orphelin dès `cand.delete()`. → filtre
   `is_proposed=False` au repli.

Réparé sur les 3 lignes + corpus ré-exporté (chatterbox `mit`/ResembleAI,
Audio8 `apache-2.0`/Audio8, vérifié AVANT/APRÈS) ; orphelins retirés. ⚠ La règle
« author ne s'écrase jamais » (27/08) a une conséquence en réparation : l'author FAUX doit
être vidé en base AVANT de re-poser l'identité. Leçon générale (sœur de « une garde se pose
avec ses jumeaux ») : **un pipeline idempotent par ligne ne l'est pas par LOT — ce qu'un
`full_sync` rapporte n'est pas attribuable à l'appelant qui l'a déclenché.**

### Suite du même jour — la JONCTION manifeste→pip + le MARCHEUR d'app (reste ③ refermé)

**Constat mesuré avant d'écrire** (question Fabien « l'installation de librairies n'était
pas déjà implémentée ? ») : l'EXÉCUTION existait (`pip_install_packages` derrière
`spec.pip_dependencies`+`human_validated`, `ensure_backend_deps` pour les
`REQUIRED_PACKAGES`), le registre `Library` existait (kind pilote, `is_allowed` humain) —
mais **rien ne les reliait** : zéro consommateur de `Library.pip_spec`/`is_allowed` côté
exécution, verrous §16.7 non appliqués dans `pip_install_packages` (toute chaîne passait à
pip), pas de rejeu des patches venv, pas de marcheur `requires`→drivers.

**Livré (`model_installer.py`, tests `tests_library_install.py` — 10 verts)** :
- **Verrous pip appliqués à TOUS les appelants** : `pip_spec_error` (PyPI par NOM seul,
  extras tolérés, **pin exact `==`** — URL/`git+`/`file:`/options/contraintes lâches
  refusées AVANT pip ; les builds locaux type `torch==2.9.1+cu128` passent) + kill switch
  env `WAMA_PIP_KILL_SWITCH`. ⚠ Conséquence assumée : `ensure_backend_deps` exige
  désormais des `pip_install_spec()` épinglés.
- **`install_library(key, apply=False)`** — le driver LIBRAIRIE : registre → plan
  (visible SANS allowlist — le verrou ne gate que l'exécution) → `is_allowed` obligatoire
  à l'apply → pip → **`patches/apply_patches.py` rejoué** (`_replay_patches`) → version
  CONSTATÉE (importlib) → `is_installed`/`installed_version` recalés. Venv de RÉFÉRENCE =
  `venv_linux` (arbitrage Fabien 31/08 : venv_win est HISTORIQUE/TEMPORAIRE, prod cible
  full-Linux — signalé dans chaque plan tant qu'il existe, plus une « règle des deux venvs »).
  Surface : `manage.py install_library <clé> [--allow] [--apply]` (`--allow` EST la
  décision humaine).
- **`install_requirements(app, apply=False)`** — le MARCHEUR (« application = modèles +
  librairies », cadrage Fabien) : lit les `requires` du manifeste d'app AU CORPUS et
  dispatche vers les drivers EXISTANTS — `library` → `install_library`, `model` → état
  catalogue + `install_catalog_task` si spec dérivable (sinon « premier usage », signalé).
  Le marcheur n'invente rien et n'ajoute aucune garde à lui : celles des drivers valent.
  Surface : `manage.py install_requires <app> [--apply]`. Dry-run RÉEL vérifié sur
  synthesizer : 9 librairies (versions constatées, `already_satisfied`), 4 modèles
  téléchargés.

**Chaîne complète désormais** : librarian/extraction → manifeste `library` → ingest →
registre `Library` → (`--allow` humain) → `install_requires <app> --apply` → pip verrouillé
+ patches rejoués. Restes CONNUS : venv_win manuel ; `requirements.txt` non tenu par
l'exécuteur (signalé, décision à prendre) ; l'ingest des manifestes du librarian n'a pas
encore de commande dédiée (`manifest_export --check`/écriture directe au corpus en
attendant).

### Suite (après le crash du 31/08 ~11:45) — scout/librarian SANS LLM : la matière est produite À LA MAIN

La passe scout LLM a TUÉ l'hôte au 1ᵉʳ chargement (qwen3.8 17,7 Go sur l'Ollama hôte —
détail : `INFRA §2026-08-31` ; règle durcie : plus aucune passe LLM hôte depuis une
session, même sur GO). La matière a donc été produite MÉCANIQUEMENT + à la main (le
précédent `dataset` : « écrire un manifeste à la main est un instrument de mesure ») :

- **3 manifestes `library` au corpus** : `onnxruntime-gpu` (extraction mécanique,
  `manifest_export --kind library`) ; **`kokoro-onnx` v0.6.1 (MIT)** et **`chatterbox-tts`
  v0.1.7 (MIT)** écrits à la main depuis les faits PyPI/GitHub (`source.type: manual`),
  validés (`ingest.validate`) et PROJETÉS → 2 lignes `Library` créées, `is_allowed=False`
  préservé (décision humaine). ⚠ Fait décisif porté par `constraints` : **chatterbox-tts
  épingle `torch==2.6.0`/`torchaudio==2.6.0`/`transformers==5.2.0`** — NON installable tel
  quel dans venv_linux (torch 2.9.1+cu128, transformers 4.57.6 patchée) sans rétrograder
  la pile GPU ; voies : `--no-deps` mesuré, pins amont plus laches, ou process dédié.
  kokoro-onnx, lui, est PROPRE : numpy 2.3.5 ✓, onnxruntime-gpu 1.23.2 ✓,
  espeakng-loader déjà présent — seul `phonemizer` manque.
- **`composition` MESURÉE sur disque posée aux 3 manifestes `model`** puis projetée
  (`write_back_model` → `AIModel.composition`) : Kokoro-ONNX = `onnx/model.onnx`
  (8 variantes présentes, la pleine précision déclarée) + `voices/*.bin`, runtime
  `kokoro-onnx` ; Audio8 = `model.safetensors` + `codec.pth`, runtime
  `transformers-remote-code` (code distant `modeling_arktts.py` — surface de confiance à
  valider) ; chatterbox = runtime `chatterbox-tts` seul (multi-variantes t3 v2/v3/23lang :
  le choix de composant reste un ARBITRAGE, non inventé).
- ⚠ **Discipline apprise en le faisant** : `capabilities` N'ENTRE PAS au corpus à la main —
  le champ appartient à la DÉCOUVERTE (réécrit à chaque sync) et `write_back_model` ne le
  projette pas : des capabilities manuscrites seraient signalées périmées puis écrasées au
  prochain export. Les langues/clonage relevés (Kokoro : 7 langues ; Audio8 : 10 + clonage
  zero-shot ; chatterbox : clonage) entreront par la déclaration du backend à l'intégration.

### Suite (même jour) — le 1ᵉʳ BACKEND DÉCLARÉ TTS : kokoro-onnx, smoke CPU réel vert

La boucle se referme sur le premier modèle (GO Fabien « on poursuit sur 3 ») :
1. **`install_library kokoro-onnx --allow --apply` = 1ᵉʳ apply RÉEL de la jonction**
   manifeste→pip : verrous passés, pip, **patches venv rejoués** (les 6 vérifiés), version
   constatée, **torch INTACT** (2.9.1+cu128), ligne `Library` recalée. La chaîne construite
   le matin tient en conditions réelles.
2. **`KokoroOnnxBackend`** (`synthesizer/backends/`, contrat `TTSBackend`, Django-free) —
   1ᵉʳ adaptateur du motif « backend déclaré » : composants lus sur `AIModel.composition`
   (projetée du manifeste, mesurée sur disque), repli disque aux MÊMES motifs pour le
   service TTS sans Django ; `voices-derived.npz` ASSEMBLÉ depuis les `voices/*.bin`
   déclarées (510×256 → (510,1,256) — `np.load` attend un npz clé→style ; artefact dérivé
   dans le dossier FAMILLE, jamais le snapshot, même motif que les alias audio.cpp) ;
   briques voix/WAV du jumeau .pt réutilisées. Enregistré (`ENGINE_BACKENDS['kokoro-onnx']`).
3. **Smoke CPU PUR vérifié** (session `CPUExecutionProvider` via `from_session` — aucune
   VRAM, règle post-crash) : déclaration lue, **54 voix**, synthèse fr réelle **3,14 s**
   (`ff_siwis`). Piège attrapé : **`np.savez` ajoute `.npz` à tout nom qui n'en finit pas**.
4. **Restes séquencés** : bascule assistant (`views.py:262` `'kokoro'`→`'kokoro-onnx'`)
   **APRÈS redémarrage du service TTS** — l'ancien `engine_for_model` en mémoire
   retomberait sur coqui ; `ONNX_PROVIDER` est honoré par `kokoro_onnx` si l'on veut
   fixer le provider du service ; la déclaration côté APP synthesizer (select, catalogue
   `synthesizer:`) = phase 2, avec la GÉNÉRALISATION du mécanisme existant de projection
   modèles→apps (`AIModel.source` + briques `ui_meta`/`WamaModelCaps`/`WamaParams` —
   cadrage Fabien : généraliser, ne pas réinventer ; la liste statique `TTS_MODEL_CHOICES`
   est le chemin parallèle à résorber) — en coordination avec l'instance « volet
   paramètres » qui tient les views/templates synthesizer.

### Le 3ᵉ indicateur gagne son DÉCLENCHEUR — il n'en avait aucun (2026-08-31)

Constat de Fabien : « je n'ai jamais pu compléter une recherche benchmark, le PC crashe ».
**Mesure : ce n'était pas la recherche benchmark.** L'écran n'avait QU'UN bouton — « Évaluer
la confiance » — qui déclenche le **jury LLM**, lequel charge un modèle sur l'Ollama hôte,
le déclencheur de crash connu. La **performance tierce**, elle, n'avait ni tâche, ni endpoint,
ni bouton : `sync_benchmarks` n'existait qu'en ligne de commande et le gabarit se contentait
d'AFFICHER le badge `bench`. Ce n'était donc pas une séparation de boutons, c'est une
**création**.

Les **trois indicateurs** sont distincts et aucun n'avait été perdu (doute levé) :
`confidence` (jury multi-agents — confiance dans SA recommandation) · `update_complexity`
(effort d'intégration) · `benchmark_index`/`quality_index` (performance TIERCE). Le jury
CONSOMME le benchmark dans son prompt, il ne le remplace pas.

Livré : `sync_benchmarks_task` (file `default` — **réseau SEUL** : Artificial Analysis + Arena,
aucun GPU), endpoints `api/benchmarks/{sync,progress}/`, bouton **« Mesurer la performance »**
avec des infobulles qui NOMMENT les indicateurs (1/3 et 3/3). `SourceIndisponible` rendu en
SUCCESS+skipped (même sémantique que le code retour 3 de la commande).
**Leçon** : *un libellé qui recouvre deux mécanismes finit par en faire accuser un pour
l'autre* — le badge était distingué à l'affichage depuis le 19/08, c'est le DÉCLENCHEUR qui
manquait, et son absence a fait porter le crash du jury sur le dos des benchmarks.
⚠ Effet attendu sur le tirage : le parc TTS n'ayant aucun indice, `_rank_key` retombe sur
`vram_gb` (« le plus gros qui tient » : `bark` 4 Go plutôt que `kokoro` 0,5 Go). Alimenter
l'étage benchmark corrige cela **sans risque de crash**.

### 🔚 Trou identifié — le SCOUT ne fait pas toute la chaîne de découverte (Fabien, 2026-08-31)

« À l'écriture du manifeste, le LLM doit aller tirer les infos depuis la source et faire
l'analyse benchmark — idéalement toute la chaîne que la prospection applique, mais sur
l'unique modèle. » **D'accord, avec une précision de doctrine** : tirer depuis la source et
apparier les benchmarks sont des gestes **MÉCANIQUES**, jamais délégués au LLM (`run_scout`
le dit déjà : « squelette mécanique d'abord, les faits ne passent pas par le LLM »). Le LLM
doit **recevoir** le benchmark comme entrée de jugement, sinon il l'invente.
Aujourd'hui le scout ne relève qu'identité / licence / tailles / inventaire. Il lui manque,
et ces briques EXISTENT côté prospection : `analyze_license` (texte de la licence, clauses
territoriales) · `quantized_variants` + `install_options` (variantes et poids) ·
`_repo_weight_gb` · le référentiel `concurrence` (`AIModel.best_installed`) · l'appariement
`sync_benchmarks` (qui inclut déjà les lignes `proposed:`). → **Le scout doit RÉUTILISER ces
briques**, pas en réimplémenter une part : un manifeste doit porter les mêmes faits qu'un
candidat prospecté.

**Dry-runs scout validés (même jour, aucun LLM)** sur les 3 dépôts TTS installés —
squelettes mécaniques complets, et déjà instructifs : `ResembleAI/chatterbox` est un dépôt
**MULTI-VARIANTES** (t3 en v2/v3/23lang + s3gen en double format .pt/.safetensors — la
`composition` devra CHOISIR, même leçon que Music3/audio.cpp) ; `Audio8-TTS-Preview-0.6b`
a **2 composants nets** (`codec.pth` 1,26 Go + `model.safetensors` 1,12 Go — candidat
idéal `body.composition`) ; `Kokoro-82M-v1.0-ONNX` embarque **40 voix `.bin`** à côté des
poids ONNX. Les passes LLM (scout sans `--dry-run` ; librarian, qui n'a PAS de dry-run) se
lancent sur DÉCISION HUMAINE (historique crash Ollama hôte) — commandes prêtes :
`python wama-dev-ai/run_scout.py --hf <dépôt>` ×3, puis
`python wama-dev-ai/run_librarian.py --repo thewh1teagle/kokoro-onnx` /
`--repo resemble-ai/chatterbox` (+ runtime Audio8 à identifier sur sa card).
⚠ Après redémarrage des services : `sync_models` recalera les `can_convert_to` des modèles
synthesizer (registre modifié ce jour) → re-passer `manifest_export --check`.

## Session du 2026-09-02 : le banc tiers s'étend — Arena `vision`/`document` + Open ASR (1ᵉʳ banc hors génération)

**Point de départ (question de Fabien : « d'autres plateformes pour compléter nos bancs ? »)** —
relevé des plateformes VÉRIFIÉ à la source (flux lisible par machine ? licence ?), confronté
aux trous du catalogue : 159 lignes examinées, **117 hors catégorie**, dominées par la vision
(48 detect/segment/pose), la parole (24) et l'upscaling (13). Verdicts :
- **AA ne donnera rien de plus** : son API de données publique n'expose que les 6 endpoints déjà
  consommés (pas d'ASR, pas de musique — ces arènes existent sur le site, pas dans l'API).
- **Arena** exposait `vision`, `document`, `video_edit` (22 configs, CC-BY-4.0) par le MÊME
  parquet que le chargeur lisait déjà — personne ne les demandait.
- **Open ASR Leaderboard** (HF `hf-audio`) : CSV publics, un fichier PAR LANGUE (français
  compris) — le seul banc tiers qui mesure ce que le transcriber fait ici.
- **Écartés, avec la raison** : détection/segmentation = plus AUCUN flux neutre (Papers with
  Code mort en juillet 2025, relance HF en reconstruction, Roboflow = éditeur de RF-DETR) → seul
  le 3ᵉ étage (mesure interne) reste ; OCR = OmniDocBench n'est qu'une table README, dataset
  non commercial ; upscaling/lipsync/musique = rapports de challenge ou arènes sans export ;
  MTEB (CC0, JSON brut, moyenne à recalculer) et Open VLM (JSON par URL) = candidats SUIVANTS ;
  OpenRouter = popularité, pas qualité (place : prospection).

**Livré** :
1. `CATEGORIES` gagne `vision` (arène multimodale) et `document` (lecture de documents) — Arena
   seul, `taille_stricte`. Métiers dérivés : VLM → `['vision', 'llm']` ; LLM Ollama à capacité
   `vision` → `vision` en SECONDAIRE de sa tâche. ⚠ **Faux appariement mesuré à la première
   lecture** : `gemma4:12b` prenait l'Elo de `gemma-4-31b` — la règle de taille stricte n'existait
   que pour `llm`, écrite `cat == 'llm'`. Elle est désormais DÉCLARÉE par catégorie.
   Résultat réel : `qwen3.8` (tag réel 27b) porte un 2ᵉ banc `arena_elo_vision` 1279 (79ᵉ
   centile / 125) ; gemma4:12b et les MiniCPM proposés restent « sans banc » (pas de 12B ni de
   v4.x dans l'arène) — null plutôt que plausible.
2. **3ᵉ source `open_asr`** (`charger_open_asr`, forme des CSV SONDÉE : `avg` publié en anglais,
   moyenne des `* WER` calculée en français). Deux catégories pour une tâche
   (`TACHE_VERS_CATEGORIE` accepte un tuple) : `speech-to-text-fr` PRINCIPAL, `speech-to-text`
   secondaire. Résultat réel : `whisper` 6,24 % WER FR (population 17) / 5,78 % EN (29) ;
   `qwen3-asr-1.7b` 5,68 % FR / 4,31 % EN. `vibevoice-asr` et `whisper-base` : sans identité.
3. **Le SENS de l'échelle** (`sens='bas'` déclaré par la source, écrit dans le banc) : lu par
   `rang_centile`, `_choose_variant` (dernier recours = la valeur la PIRE) et
   `valeur_ordonnable` — le SEUL point de lecture pour un tri, adopté par `_rank_key` et
   `best_installed`. *Un WER trié comme un Elo aurait mis le pire transcripteur en tête.*
4. Registre des sources externes : `open_asr` déclaré (kind `banc`), et un test qui exige que
   les bancs DÉCLARÉS (adresses) et les bancs LUS (`benchmark_sync.SOURCES`) soient les mêmes.

Dry-run après : **17 appariés · 11 sans banc · 16 sans identité · 115 hors catégorie** (somme
159 inchangée). Populations : arena vision=125, document=33 ; open_asr EN=29, FR=17.

### Suite (même jour) — lecture de la prospection relancée par Fabien : 3 défauts de l'INSTRUMENT

Question : « résidus de proposés déjà installés ? les plus intéressants à installer ? H3 dit
UE EXCLUE mais pas H3-Turbo — manque ou permission ? ». Relevé sur 65 proposés / 95 installés.

1. **Aucun doublon strict** (le `already` du seeding fait son travail). Les retours de
   Realistic Vision et du merge H3 par le tri tendance ne sont PAS des résidus — règle de
   Fabien : *le retrait vaut pour un modèle INSTALLÉ, jamais pour un proposé* (la liste
   « Supprimés » de `CLAUDE.md` date du nettoyage disque du 2026-03-05, `0b1ac4e9` : des
   modèles déclarés dans `imager/model_config`, pas des propositions).
2. **Licence à double étage NON héritée** — le manque. `lightx2v/Minimax-h3-Turbo` se tagge
   `apache-2.0` : SPDX permissif → la garde rendait None, pendant que la card du modèle de
   base disait « UE EXCLUE ». Or sa carte DÉCLARE `base_model: MiniMaxAI/MiniMax-H3`, et un
   « Model Derivative » reste soumis à l'accord amont. `analyze_license(hf_id, licence,
   base_model)` hérite désormais du verdict territorial de la base, en le disant
   (`herite_de`, libellé « (modèle de base) »). Mesuré : H3-Turbo, FastH3, le merge ET
   `10Eros-Max` (qui ne disait rien) passent en `exclusion_ue` hérité. ⚠ Fait nouveau
   (FAQ MiniMax) : l'exclusion est présentée comme « pas encore », avec un **formulaire de
   demande de licence** pour les organisations UE/UK/US/Corée — examen au cas par cas, aucune
   exception recherche écrite. Hors licence obtenue, H3 et ses dérivés restent inutilisables.
3. **Taxonomie figée par tag de pipeline** — le « vrai souci ». `_TASK_MODEL_TYPE` rangeait
   `image-to-image` en `upscaling` et `image-to-text` en `ocr` : six modèles d'ÉDITION
   (Qwen-Image-Edit, FLUX.2-dev, Kontext…) s'affichaient en upscalers, BLIP-base en OCR, et
   **aucune ligne proposée ne portait de `capabilities.task`** — donc aucun banc possible
   (`check_model_taxonomy` le disait : « 66 modèles sans task »). `hf_task_to_wama(pipeline,
   tags)` : les TAGS de la carte départagent (`image-editing`, `super-resolution`,
   `image-captioning` — des données déclarées, jamais le nom), la tâche s'écrit sur la ligne
   au seeding, la catégorie du spec suit. Rattrapage des lignes existantes par script
   (proposés seulement, 45 lignes réécrites — le Hub répond 429 en rafale : 1 carte / 1,5 s).
   **Effet mesuré au dry-run des bancs** : appariés **17 → 31**, hors catégorie **115 → 79**
   (23 sans banc, 27 sans identité, 160 lignes examinées) — une douzaine de candidats ont désormais un score tiers AVANT
   installation : LTX-2/2.3/2.5 (AA i2v 1153-1187), Wan2.2 A14B/5B (AA t2v 1106/949),
   FLUX.1-schnell (AA 1000), FLUX.2-dev / klein-9B / Kontext (édition, Arena 1224 / AA 1015),
   Qwen-Image-Edit-2511-Lightning (Arena edit 1235), Qwen3-TTS (AA 924), whisper-turbo
   (WER FR 6,73). ⚠ Limite connue et visible : deux variantes de taille d'une même famille
   média prennent le même Elo quand le tiers n'en publie pas (Wan 5B/A14B, Qwen3-TTS
   0.6B/1.7B) — les modalités média n'exigent pas la taille, par décision.
   `check_model_taxonomy` : l'avertissement « 66 modèles sans task » a disparu.
   Deux correctifs de `benchmark_sync` sortis de cette mesure : **la version après un POINT**
   (`FLUX.1-schnell` n'avait aucune identité, `flux-1-dev` si — un tiret contre un point) et
   la garde **add-on** (`ADD_ONS` : lora / adapter / controlnet → hors catégorie par nature),
   parce que la LoRA logo, devenue lisible, prenait l'Elo de FLUX.1 (1083). ⚠ Cette garde lit
   les IDENTIFIANTS (clé, `hf_id`), pas `name` : à la première passe, SD 1.5 et SDXL sortaient
   du banc parce que leur libellé descriptif cite « LoRA ». *Un filtre sur un texte libre
   attrape ce que le texte raconte, pas ce que la ligne est.*
4. Au passage : **`glm-ocr:0.9b` n'existe plus sur le registre Ollama** (404 mesuré ; restent
   `latest` 2,2 Go et `q8_0` 1,6 Go). Le reader le déclarait comme `ollama_id` → un pull
   échouait. Corrigé en `glm-ocr:latest`. Le modèle n'est PAS tiré sur l'hôte aujourd'hui
   (7 tags Ollama, aucun glm-ocr) : réinstallation = `ollama pull glm-ocr`.

### Suite (même jour) — 5 installations PAR LE MÉCANISME, et ce que l'épreuve a révélé

Demande de Fabien : glm-ocr, PP-DocLayoutV3, table-transformer ×2, ACE-Step 1.5 — « on teste
les mécanismes d'abord, on vérifie ensuite, on corrige ». Chemin = celui du bouton
« Installer » : `install_proposed_task` → `install_candidate` → `install_from_spec` (HF vers
`AI-models/models/<catégorie>/<famille>/`, Ollama via `/api/pull`) → sync + provenance →
retrait du candidat. **Un modèle à la fois** (le 31/08, trois installs concurrentes avaient
croisé les identités). Résultat : **5/5 installés et catalogués** — table-transformer ×2 (15 s
chacun, 0,21 Go), PP-DocLayoutV3 (12 s, 0,12 Go), glm-ocr:latest (51 s, 2,2 Go, `reader:glm-ocr`
passe téléchargé/disponible), ACE-Step 1.5 (132 s, 9,4 Go, MIT). Manifestes `huggingface__*`
écrits par la provenance, corpus régénéré.

Trois choses vues en chemin :
1. ⚠⚠ **Deux Redis sur `127.0.0.1:6379`** — dispatchée depuis un shell Django Windows, la
   première tâche est partie dans un `redis-server.exe` Windows que les workers WSL2 ne
   lisent pas, sans erreur (600 s d'attente pour rien). Broker/cache n'ont pas le résolveur
   de la base. Détail, inventaire du Redis fantôme et voie de sortie : `INFRA_WSL_VS_WINDOWS
   §Deux Redis`. **Tout dispatch se fait depuis WSL2.**
2. **La ligne installée arrivait SANS tâche** (`table-transformer-detection` : `task=None`,
   candidat `detect`) — le balayage générique d'un snapshot HF ne sait pas ce qu'un modèle
   fait. Le spec porte désormais `task`, `record_after_install` la pose (jamais par-dessus une
   tâche établie). Les 4 lignes du jour rattrapées à la main (le worker tournait avec
   l'ancien code — *un worker sans autoreload est un second dépôt de code*, 3ᵉ fois).
3. Les deux formats de poids sont tirés quand le dépôt en publie deux (`pytorch_model.bin` +
   `model.safetensors`, 115 Mo ×2 pour table-transformer) : `allow_patterns` n'est dérivé
   que d'une `composition` déclarée. Assumé pour des dépôts de 0,2 Go ; à déclarer pour les gros.
   Et la ligne Ollama `ollama:glm-ocr:latest` est typée `llm` à capacité `vision` (règle de
   découverte : seul `embedding` est distingué) quand la prospection l'avait proposée en
   `vlm` — incohérence préexistante, notée, pas traitée.

**Aucun de ces modèles n'a été CHARGÉ** (règle : jamais de charge GPU par l'instance) : la
vérification est celle du catalogue, du disque et du corpus. Le premier usage réel (reader
avec glm-ocr, composer avec ACE-Step — qui n'a pas encore de backend) revient à Fabien.

### Suite (soir, après relance) — 4ᵉ banc MTEB branché, Open VLM ÉCARTÉ (flux mort)

**Open VLM Leaderboard — écarté, avec la preuve.** L'URL que le Space lit
(`opencompass.openxlab.space/assets/OpenVLM.json`, dans son `meta_data.py`) rend une page HTML
derrière un **certificat expiré** ; en http, 404. Le dataset `VLMEval/OpenVLMRecords` (Apache) n'est
que les prédictions BRUTES par échantillon (13 246 fichiers xlsx/json, figés en avril 2025), pas une
table. *Une source dont le seul flux est une page web n'est pas une source.* L'arène `vision`
d'Arena reste le banc des VLM ; Open VLM reviendra si son JSON réapparaît.

**MTEB — branché sans le paquet `mteb`** (`charger_mteb`, source `mteb`, catégorie `embedding`,
tâche `feature-extraction`). Trois décisions qui font sa forme :
1. **Le jeu est DÉCLARÉ** (`CATEGORIES['embedding']['mteb']`), et **la première version a été
   RÉFUTÉE PAR LA MESURE** : les 5 tâches du sous-ensemble « MTEB français » (Alloprof, BSARD,
   Syntec, Mintaka, XPQA) donnaient une population de 143… dont AUCUN de nos modèles (bge-m3 2/5,
   Qwen3-Embedding et nomic v2 0/5 — seuls les contributeurs anciens les ont exécutées). Le jeu
   retenu = les tâches MULTILINGUES que nos modèles partagent et qui portent un SOUS-ENSEMBLE
   français, déclarées en (tâche, split, hf_subset) : Belebele `fra_Latn-fra_Latn`, MIRACL
   hard-negatives `fr`, Statcan `french`, AlloprofReranking `default`. Échelle NOMMÉE
   `mteb_fr_retrieval` = moyenne des `main_score` ×100 (nDCG@10 / MAP — une moyenne à NOUS,
   pas la leur). Un modèle sans les quatre n'est pas noté, jamais moyenné sur moins.
   *Un jeu de tâches se choisit sur ce que le CATALOGUE a, pas sur ce que le banc propose.*
2. **`paths.json` est périmé** (333 modèles sur 685, sans Qwen3-Embedding) : il donne la POPULATION,
   l'API GitHub (quota anonyme 60/h) ne sert qu'à résoudre les modèles de NOTRE catalogue qu'il
   ignore (marqueurs tirés du catalogue, arbre récursif par modèle, ~10 appels). ⚠ **Chemin EXACT
   par (modèle, tâche)** : une tâche peut vivre sous une autre révision que les autres (Alloprof de
   bge-m3 → 404 sous la révision de son premier chemin).
3. **Cache disque** `logs/benchmarks/mteb_scores.json` : un score est immuable par (chemin, split,
   subset). ⚠ **Un échec PASSAGER ne se met jamais en cache** — la première passe cachait `None`
   sur une coupure de proxy et le lisait ensuite « absent » (Syntec : 200 à la relecture) ; un
   modèle non lu est sauté CETTE passe et compté dans les motifs (« relancer »). JSON lu par la
   stdlib : `mteb` écrit des `NaN` que simplejson (requests) refuse.
`bge-m3` s'apparie par **ALIAS** (`ollama:bge-m3:latest` → `BAAI/bge-m3`) : `_identity` rejette la
famille d'une lettre « m3 », le modèle du RAG n'aurait jamais eu de banc. Les embeddings PROPOSÉS
(type `embedding`, sans capacités) ont désormais la catégorie `embedding` — le matin ils n'en avaient
aucune, avant ils tombaient dans `llm`.

**Décision Fabien : `qwen3-embedding:4b` (installé par le mécanisme, 51 s), PAS le 8B** — sur le
jeu français le 4B est 1ᵉʳ (70,0) et le 8B 3ᵉ (69,4 : meilleur en recherche pure Belebele/MIRACL,
nettement moins bon sur le dialogue Statcan), écart sous le pouvoir de séparation du rang, pour
le double de disque et de VRAM. ⚠ Contrôle de FONCTIONNEMENT (un `/api/embed`) laissé à Fabien :
charger 4B côté hôte est le déclencheur des crashs du soir. Bascule du RAG = `embed.py`
(`EMBEDDING_MODEL`, empreinte VRAM remesurée, `OWNER`) + réindexation par `store.py`.

**Faits pour les recommandations** (vérifiés HF / bancs) : ACE-Step 1.5 (MIT, 10 Go) prend
un **audio de référence** (colonne « Refer audio » ✅ sur toutes les variantes DiT ; modes
cover, repaint, vocal→BGM ; 50+ langues ; <4 Go VRAM annoncés). Qwen3-TTS 1.7B (Apache,
4,5 Go, FR). FLUX.1-schnell (Apache, distillé 4 pas). FastWan2.2-TI2V-5B (Apache, distillé
3 pas). Banc FR : canary-1b-v2 4,79 % / parakeet-tdt-0.6b-v3 5,38 % (CC-BY, runtime NeMo)
devant qwen3-asr 5,68 % et whisper-large-v3 6,24 % ; whisper-turbo 6,73 % ; VibeVoice-ASR
14,04 % pour 16 Go — candidat au retrait. PP-DocLayoutV3 + table-transformer : rien
d'équivalent en place (docTR = boîtes de mots ; olmOCR/GLM = VLM qui restituent un markdown
sans coordonnées) → COMPLÉMENT (régions et structure de tableau à coordonnées), pas un
remplacement.


## Session du 2026-09-03 : la COMPLÉTUDE des installés — la dernière étape n'avait pas de contrôle

**Point de départ** — le 🔚 point d'entrée laissé par l'instance bancs le 02/09 : « vérifier
les informations de l'ENSEMBLE des modèles installés (tâche, licence, VRAM déclarée vs
mesurée, backend présent) pour lister les TROUS ». Le pipeline **prospection → installation
→ app** avait un contrôle par étape, sauf la dernière :

| étape | contrôle | ce qu'il atteste |
|---|---|---|
| installation | `verify_models` | catalogue ↔ disque — l'**existence** |
| catalogage | `check_model_taxonomy` | types/sources/tâches déclarés — le **vocabulaire** |
| renvois | `check_model_declarations` | tags écrits en dur ↔ catalogue — les **liens** |
| **usage** | **`check_model_completeness` (livré ici)** | **le modèle est-il UTILISABLE ?** |

*Un modèle peut être sur le disque, catalogué, de taxonomie juste — et rester inutilisable
faute de licence connue, de VRAM crédible ou de backend. Rien ne le disait.*

**Mesure sur les 60 installés hors YOLO** (venv_linux, le runtime qui fait foi) :

> ⚠ **60, pas 62.** Le handoff annonçait « 62 lignes » à un endroit et « 61 » à l'autre — il
> était déjà incohérent avec lui-même. Périmètre revérifié : **170 au catalogue, 107
> `is_downloaded`, dont 0 `is_proposed`, dont 47 YOLO → 60.** Aucun installé n'échappe au
> rapport ; les chiffres du handoff étaient des relevés à la main, dont c'est exactement le
> défaut (`/reprise` : *un chiffre vit à UN endroit*).

| axe | n | lecture |
|---|---|---|
| sans licence | 3 | `timm/resnet18`, `ollama:glm-ocr`, `ollama:qwen3-embedding:4b`. ⚠ **pas une propriété d'Ollama** : 7 des 9 lignes Ollama portent la leur (mit, apache-2.0, gemma-terms) — ces deux-là sont des cas isolés, à renseigner à la main |
| VRAM absente | 5 | 4 enhancer + `reader:doctr` — échappent à la sélection VRAM-aware |
| VRAM **estimée** | 13 | plancher depuis les poids, en attente d'un banc |
| backend **rouge** | 2 | Qwen3-TTS et chatterbox — moteur DÉCLARÉ, runtime pip absent : **état légitime**, le grisage fait son travail |
| backend **ANGLE MORT** | 16 | ni moteur ni `backend_ref` → **aucun verdict possible** |

### ⚠⚠ Le constat principal : l'angle mort du grisage (16 des 60)

`backend_missing()` est **permissif par construction** — un modèle sans moteur déclaré ne
reçoit aucun verdict, et c'est voulu (l'exclure sur une absence d'information viderait des
lots entiers). La conséquence n'avait jamais été comptée : **16 modèles installés ne sont
signalés nulle part**, ni grisés, ni rouges, ni verts.

Le cas qui le prouve : **`table-transformer` ×2 porte `backend_ref = ''` et
`composition = {}`** alors que son backend venait d'être livré et testé sur les poids réels
(B2 n°1, `046af1be`). Le chantier ⑤ du handoff annonçait « `backend_ref` posé EN BASE pour
table-transformer — une réinstallation le perdrait » : **il n'y est déjà plus.** La voie
déclarative durable n'est donc pas un confort, c'est ce qui manque pour que le système voie
ce qu'on lui a ajouté.

Les 15 autres se lisent en trois familles : les **INCONNUS** du tableau du 02/09 (ACE-Step,
PP-DocLayoutV3, canary, parakeet, LocateAnything — backend à écrire, attendu), les **apps
déclaratives** (composer ×3, reader ×3, depthpro — servies par du code d'app sans passer par
l'inventaire) et un cas d'une autre nature, `timm/resnet18` — ci-dessous.

### Un modèle de la liste n'en est pas un : `timm/resnet18` est une DÉPENDANCE

Il sort dans trois axes à la fois (sans tâche, sans licence, angle mort) et ce n'était pas un
résidu, contrairement à ce que j'avais d'abord écrit. Son `extra_info` le dit :
`path = AI-models/models/vision/**table-transformer-detection**/models--timm--resnet18.a1_in1k`,
`family = table-transformer-detection`. C'est le **backbone** que le snapshot de
table-transformer tire avec lui — et la découverte le catalogue comme un modèle AUTONOME.

Il n'a donc ni tâche ni licence **parce qu'il n'est pas un modèle offert à l'utilisateur** :
lui en poser une serait masquer le vrai défaut. La question ouverte est en amont — *la
découverte doit-elle reconnaître un snapshot imbriqué comme composant de sa famille plutôt
que comme une ligne de catalogue ?* Elle vaut aussi pour les 2 « sans tâche » que signale
`check_model_taxonomy` : l'un des deux est ce composant. **Non tranché ici** (le geste touche
`model_registry`, hors périmètre de session).

### ⚠⚠ « Déclarée vs mesurée » : les deux ne se rencontrent JAMAIS

L'axe demandé supposait qu'on puisse comparer une VRAM déclarée à une VRAM mesurée. **On ne
peut pas — et la raison est une boucle ouverte, pas une mesure manquante.**

La mesure EXISTE : `common/backends/base.py::_wrap_load` encadre chaque `load()` réussi et
calcule l'empreinte réelle (`_measured_vram_gb`). Mais elle part **au gouverneur de
ressources** — `reserve_vram(owner, gb)`, une ligne Redis **à TTL**, transitoire par
construction — et **rien ne la rend au catalogue** : aucun chemin n'écrit `AIModel.vram_gb`
depuis une mesure (les seules affectations trouvées sont des paramètres de smoke et la
`total_memory` de la carte, qui est la capacité du GPU, pas l'empreinte d'un modèle).

Conséquence : **`vram_estimated=True` ne se lève jamais tout seul.** Les 13 lignes estimées le
resteront, quel que soit le nombre de fois où ces modèles ont tourné. *L'information est
produite à chaque chargement puis jetée.* Refermer la boucle (le gouverneur rend l'empreinte
au catalogue, qui efface le marqueur) est le geste qui rendrait l'axe mesurable — **non fait
ici**, il touche `base.py` et `resource_governor`, hors périmètre de session.

### ⚠⚠ Le verdict de backend est VENV-DÉPENDANT (mesuré, pas déduit)

Depuis le raffinement `missing_packages()` de l'inventaire (`02001d2d`, « l'inventaire
n'annonce que l'EXÉCUTABLE »), `known_engines()` ne rend que les moteurs dont le runtime pip
est présent **dans le venv courant**. Le même appel, sur le même catalogue, à la même
seconde, a rendu :

- depuis **venv_win** : `kokoro-onnx` MANQUANT → Kokoro-ONNX faussement rouge (3 rouges) ;
- depuis **venv_linux** : `kokoro-onnx` PRÉSENT → Kokoro-ONNX vert (2 rouges).

**venv_linux fait foi** (les workers y tournent). Le rapport nomme donc son venv en en-tête :
*un rapport de grisage sans son venv ne veut rien dire.* Même famille que
`manifest_export --check`, dont le corpus est extrait par `importlib.metadata`.

### Ce que le contrôle ne fait PAS, délibérément

- **Il ne re-contrôle pas la TÂCHE** : `check_model_taxonomy` en est propriétaire (il la
  confronte à l'énumération déclarée). Le rapport la rappelle en une ligne et renvoie —
  deux contrôles de la même chose finissent par se contredire.
- **Il ne garde rien (exit 0 toujours).** Aucun de ses constats n'est interdit : un backend
  écrit dont le runtime attend un GO humain est légitime, une VRAM estimée est un plancher
  honnête. *Un gate rouge en permanence se relit comme la normale* — le défaut que
  `/reprise` documente sur son attendu de suite de tests. C'est une CARTE DE DETTE.
- **Il replie les ~47 lignes YOLO** (même forme, déclarées en famille) : les déplier noierait
  les trous réels. `--yolo` les montre.

**Effet de bord utile** : `vram_estimated` était ÉCRIT par la découverte (`model_registry`)
et **relu par personne** — le marqueur « une vraie mesure la remplacera » ne désignait aucune
liste. Il en a une.

**Livré** : `check_model_completeness` (+ `--json`, `--yolo`) et 7 tests
(`tests_completeness.py`) — dont un qui protège la décision « ce contrôle ne garde rien » et
un qui sépare *rouge* (on sait qu'il manque un backend) d'*angle mort* (on ne sait rien) :
les fondre en un seul compte ferait disparaître le second, le plus coûteux.
