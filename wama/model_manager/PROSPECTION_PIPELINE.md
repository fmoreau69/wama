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
  → **Décision : le descripteur `install_from_spec` devient `model.body.install`**
  (`{'kind': 'ollama'|'hf'|'yolo', 'ref': …, 'category'/'family'/'allow_patterns'}`), symétrique de
  `library.body.install`. PAS dans `extra_info['prospect']['spec']` : ce serait un champ surchargé,
  invisible du validateur et du round-trip.
- **Le kind `model` est « store+verify only »** (pas de `project`, cf. `kinds.py`) : un candidat
  validé ne s'écrit pas en base par la couche manifeste — l'installation reste
  `api_prospect_install` → `install_from_spec`. Le manifeste DÉCRIT, l'endpoint EXÉCUTE.
- **Trous ouverts par cette confrontation** : (a) `manifests/` ne contient que `apps/` et
  `libraries/` — **pas de `models/`**, donc aucun corpus d'exemples pour un rôle LLM ; (b) SPEC §7.4
  s'arrête à l'étape 4 (rôle « librarian ») — **aucun rôle « scout modèles »**, qui en est pourtant
  le pendant exact pour les modèles ; (c) `api_prospect_install` refuse tout ce qui n'est pas Ollama
  (`views.py`, « phase 1 ») alors que les drivers `hf`/`yolo` existent depuis l'étape 5.

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
