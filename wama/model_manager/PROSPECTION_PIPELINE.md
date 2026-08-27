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
`ModelAbility`, `TACHE_VERS_TAGS_PLATEFORMES` (projection **à sens unique, plusieurs-vers-un**) et le
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
5. Candidats legacy `synthesizer:*` (SpeedySpeech/Tacotron2/VITS, seed 2026-06, conf 0.9
   figée) : obsolètes depuis le balayage TTS réel — à rejeter/purger.
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
