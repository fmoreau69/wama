# PROJECT_STATUS.md — Point d'étape des chantiers WAMA

> Photo des chantiers en cours. Mise à jour : **2026-07-25** (synchro doc : liens vers docs archivés,
> VRAM/select_model §2, orphelins/statedb, socle manifestes §38 + WAMA Data §39). Conformité
> 2026-07-11 (§31 : audit empirique conformité 10 apps).
> Marqueurs : ✅ fait · 🔄 en cours · ⏳ à faire. Détails par chantier dans les docs/mémoire référencés.
>
> 🔜 **REPRISE session neuve** : le handoff `REPRISE_2026-07-22.md` est **ARCHIVÉ**
> (`docs/archive/`, 2026-07-25 — plan doc B8) après migration de son vivant : backlog → **§40**,
> duplications → `REMOVAL_LEDGER R18/R19`, discipline git multi-instances → `CLAUDE.md`.

## 0. 🔴 Gardes anti-crash GPU & gouvernance des ressources — portage INCOMPLET (2026-07-29)

> Contexte : 4 kernel panics WSL2 le 29/07 (`Machine Check Exception` Bank 0), causés par une
> tâche imager redélivrée en boucle à chaque démarrage. Détail de l'incident :
> `memory/reference_orphan_task_reconcile.md`. **Conception et reste-à-faire de la couche
> ressources : `ROADMAP.md` §Gouvernance des ressources** (source unique — ne pas dupliquer ici).

**Fait ✅**
- *Gardes* — `refuse_crash_redelivery` sur **10 tâches** (transcriber ×2 antérieur + imager ×2,
  enhancer ×2, describer, composer, synthesizer, avatarizer, anonymizer `process_single_media`) ;
  `reconcile_orphaned_running` ajouté à imager (**8 apps**) ; preset `qwen-image` 16 → 38 Go (mesuré).
- *Couche ressources* (`common/services/resource_governor.py` = **domicile unique**) — plafond
  allocateur CUDA **par process** (3 points de câblage, couvre tout) ; registre VRAM **partagé
  Redis** inter-process ; **déclaration automatique** des empreintes par
  `BaseModelBackend.__init_subclass__` ; **priorités câblées**, WAMA-Lab prioritaire.
- *Journaux* — rotation au démarrage (nom courant inchangé) ; détail de maintenance du catalogue
  (`[ModelSync]`, `[ModelRegistry]`) cloisonné dans `logs/model-sync.log`.

**Ce qui est UNIVERSEL vs ce qui demande une adoption par app** (mesuré 2026-07-29) :

| Mécanisme | Portée réelle |
|---|---|
| Plafond allocateur CUDA | ✅ **universel** — par process, aucune action par app |
| Priorités | ✅ **universel** — par le routage, toutes les routes GPU couvertes |
| Déclaration VRAM auto | ⚠️ **conditionnelle** — 21 backends concrets, 9 sous-classes directes (imager 9, **transcriber 4** dont pyannote, **anonymizer 3**, enhancer 2, reader 2, composer 1) — les 7 ajouts du 29/07 sont venus de 3 classes intermédiaires, pas de 7 rattachements |
| Déclaration des SOUS-PROCESSUS GPU | ⚠️ **explicite** — brique `vram_reservation()` ; adoptée par avatarizer (MuseTalk, CodeFormer), reste le service TTS |
| Garde de redélivrance | ⚠️ **par tâche** — 10 / 42 |

**Reste ⏳ — par ordre de risque :**

1. ~~`_cap_cuda_allocator()` limité au chemin diffusers de l'imager~~ ✅ **CORRIGÉ 2026-07-29** —
   déplacé dans `common/services/resource_governor.py::configure_cuda_process()` et posé **par
   PROCESS** : signal Celery `worker_process_init` (pool `solo` + chaque enfant `prefork`),
   `common/apps.py::ready()` (gunicorn), `startup` du service TTS. Couvre désormais tous les
   backends faisant `.to('cuda')` en direct. Voir `ROADMAP.md` §Gouvernance des ressources.
2. **32 tâches sur 42 sans garde de redélivrance** : `wama_lab/cam_analyzer` (13), reader ×2,
   converter, studio, face_analyzer, 3 tâches anonymizer (dont les sous-tâches de chord
   `detect_with_model` / `merge_and_blur`, les plus GPU-lourdes), 2 synthesizer, 2 transcriber,
   model_manager ×4, common ×2.
3. `reconcile_orphaned_running` **manquant** : anonymizer, avatarizer, translator, apps lab.
3bis. ~~**CONTRAT BACKEND CONCURRENT — transcriber**~~ ✅ **PORTÉ 2026-07-29** —
   `SpeechToTextBackend` hérite désormais de `BaseModelBackend` et n'est plus qu'une
   **spécialisation métier** (verbe `transcribe()`, `TranscriptionResult/Segment`, capacités,
   `max_audio_seconds`). Ses 3 moteurs (whisper, vibevoice, qwen_asr) déclarent donc leur
   empreinte VRAM au gouverneur sans une ligne de câblage par app. Gains collatéraux de la
   dé-duplication : `is_available()` de whisper et qwen **supprimés** (ils recopiaient le
   `find_spec` du contrat commun) au profit de `REQUIRED_PACKAGES` ; `pip_install_spec()`
   devient exploitable par le `model_installer` (`faster-whisper`, `transformers`+`soundfile`),
   avec `PIP_PACKAGES = []` VOLONTAIRE sur vibevoice — le paquet pip homonyme est un TTS sans
   rapport, l'install passe par git clone. VibeVoice garde son `is_available()` (sonde le
   fichier de modeling ASR) : override assumé et documenté. Repli `recommended_vram_gb`
   important ici — faster-whisper (CTranslate2) alloue **hors** de l'allocateur PyTorch, donc
   la mesure autour de `load()` reste nulle et c'est la valeur déclarée (10 Go) qui est
   réservée. Le scénario nocturne `transcriber.asr_load` lit maintenant cette VRAM **sur la
   classe** au lieu de la recopier (il annonçait 3 Go pour 10 réels — même famille d'écart que
   le preset qwen-image).
   Validé CPU-seul (aucune charge GPU) : 3 backends `issubclass(BaseModelBackend)`, `load`/
   `unload` enveloppés **une seule fois**, base restée abstraite, `is_available()` identique à
   l'avant-port, chaîne publique `get_backend('auto')` → whisper inchangée.
   Effet de bord utile : le reclaim central (`MemoryManager._unload_transcriber_model`) appelle
   `instance.unload()` — donc il **libère aussi la réservation** au gouverneur, sans une ligne
   de plus.
   ✅ **Suite traitée le même jour** — voir 3quater (anonymizer) et 3quinquies (avatarizer).
   ⏳ Reste le **service TTS** (process uvicorn séparé) : sa déclaration doit venir de
   l'intérieur du service, au chargement de son modèle (il reste résident entre deux appels,
   donc l'envelopper depuis l'appelant HTTP serait faux).
3ter. ~~**DIARISEUR PYANNOTE — VRAM hors contrat**~~ ✅ **PORTÉ 2026-07-29** —
   `pyannote_diarizer.py` n'était pas une classe backend mais un module à pipeline global
   (`_pipeline`, `.to("cuda")`), chargé dans `workers.py` **par-dessus** un ASR déjà résident :
   whisper 10 Go réservés + pyannote non compté, donc pic réel sous-estimé sur le chemin même de
   la « diarisation tueuse ». Le pipeline vit maintenant dans un `PyannoteDiarizerBackend
   (BaseModelBackend)` ; l'API module (`is_available`/`diarize`) est inchangée pour `workers.py`.
   🔴 **FUITE RÉELLE trouvée au passage** (et corrigée) : `MemoryManager._unload_transcriber_model`
   (`memory_manager.py:483`) importait `unload_pipeline()` **qui n'existait nulle part**.
   L'`ImportError` étant avalé en `logger.debug`, le reclaim central **croyait** libérer la VRAM
   de pyannote et ne libérait rien — jusqu'à la mort du process. La fonction existe désormais et
   délègue à `unload()` (donc `release_vram`). *(La ligne « il est bien libérable, le reclaim le
   vide déjà » écrite plus tôt le 29/07 était fausse — vérification faite, l'appelant était seul.)*
   Leçon transposable : un `except Exception: logger.debug(...)` autour d'un **import** transforme
   une fonction manquante en no-op silencieux. À traquer ailleurs dans `memory_manager`.
   Validé CPU-seul, sans charger le pipeline : `load`/`unload` enveloppés, aller-retour
   `reserve_vram` → `release_vram` **prouvé sur le registre Redis partagé** (réservation 2 Go
   posée puis effacée, registre revenu à l'état initial), `diarize([])` ne charge rien.
   ⚠ Non enregistré dans `TranscriberBackendManager` **volontairement** : ce n'est pas un moteur
   alternatif ; l'y mettre l'exposerait au choix de moteur et à `get_backend('auto')`.
3quater. ✅ **ANONYMIZER — porté 2026-07-29** : l'app n'avait **aucun** `backends/`, alors que
   c'est elle qui enchaîne les sous-tâches GPU les plus lourdes (chord `detect_with_model` /
   `merge_and_blur`) — celles qui ont déclenché la boucle de crash. Ses 3 porteurs de modèle
   (`Anonymize` et `DetectionOnlyProcessor` → YOLO, `SAM3Processor` → SAM3) avaient déjà la
   **forme** du contrat (`load_model()`, parfois `unload()`/`cleanup()`) sans en hériter.
   Une classe intermédiaire `anonymizer/backends/base.py::DetectionBackend` mappe le verbe
   historique `load_model()` sur le `load()` du contrat : **aucun appelant modifié**, les 3
   classes couvertes. Ajouts au passage : `Anonymize.unload()` (son modèle YOLO n'était
   **jamais** libéré) et `SAM3Processor.unload()`, avec `cleanup()` qui y délègue — il ne
   relâchait que les références Python, pas la réservation.
   ⚠️ **Piège documenté dans la classe** : ne PAS écrire `load_model = load` (alias de classe).
   L'alias capturerait la fonction **avant** que `__init_subclass__` n'enveloppe `load` — les
   appelants passeraient à côté de la déclaration, mécanisme présent et inopérant. Seule la
   délégation `self.load(...)` garantit que tous les chemins traversent l'enveloppe.
3quinquies. ✅ **AVATARIZER — porté 2026-07-29, par un AUTRE mécanisme** : ici l'héritage ne
   s'applique pas — MuseTalk et CodeFormer tournent en **sous-processus** (`subprocess.run`,
   code vendoré upstream), donc aucun modèle n'est résident dans le worker. Leur VRAM était
   totalement invisible du gouverneur, qui pouvait laisser démarrer une autre tâche GPU
   par-dessus. Nouvelle brique commune `resource_governor.vram_reservation(owner, gb)`
   (contextmanager : réserve, libère en `finally` **y compris sur exception**), adoptée par les
   deux appels. ⚠️ Empreintes **NON MESURÉES** (MuseTalk 8 Go, CodeFormer 3 Go) — même réserve
   que le point 4 ci-dessous. ⚠️ La réservation expire après 1 h (`RESERVATION_TTL_S`) : OK ici
   (timeouts de 10 et 30 min), pas pour un bloc plus long sans rafraîchissement.
4. **Presets `MODEL_SIZE_PRESETS` non audités** : seul `qwen-image` a été confronté au réel. Les
   autres peuvent sous-estimer de la même façon et re-déclencher FULL_GPU à tort.
   🔴 **Aggravation trouvée le 29/07 (corrigée)** — la mesure de 38 Go avait bien été reportée
   dans les presets, mais le chiffre était déclaré **à TROIS endroits** : le manifeste
   (`imager/utils/model_config.py`, 16), les presets (38) et une **copie en dur dans
   `qwen_image_backend.py`** (16). C'est la copie du backend qui décidait → il tentait FULL_GPU
   sur un MMDiT 20B avec 24 Go de carte. Corriger la mesure « quelque part » ne suffit donc pas.
   - Le **manifeste fait foi** (c'est lui qu'ingère le catalogue, qui alimente le tirage et l'UI) ;
     la copie du backend est supprimée ; un garde signale au démarrage tout écart manifeste↔presets
     au lieu de le laisser silencieux.
   - `estimate_model_size()` retenait le **premier** preset qui matchait, or les clés se préfixent :
     Qwen-Image-**Edit** héritait des 38 Go de Qwen-Image, FLUX-**schnell** et flux2-klein-4b des
     24 Go de FLUX → trois modèles qui TIENNENT partaient en offload. La clé la plus **spécifique**
     gagne désormais.
   - ⏳ **À MESURER** : `qwen-image-edit` (posé à 38 par prudence — même dorsale 20B ; les 12 Go
     déclarés étaient impossibles) et `flux2-klein` (posé à 12).
4ter. 🔴 **AUDIT DU TIRAGE — 12 apps mesurées (2026-07-30)** — trou n°5 de
   `WAMA_APP_GENERATION_ROUTE.md` (« `select_model()` adopté par 2/10 »). État **mesuré** :

   | App | Tirage | Détail |
   |---|---|---|
   | composer | ✅ commune | 1ᵉʳ adopteur ; son appariement entrée↔modèle est **remonté en commun** le 30/07 |
   | transcriber | ✅ commune | + `BACKEND_PRIORITY` en **repli statique** assumé (whisper-first) |
   | imager | ✅ commune | 3ᵉ adopteur 29-30/07 ; listage UI **et** tirage sur la même route |
   | **anonymizer** | 🔴 **SÉLECTEUR CONCURRENT** | `utils/model_selector.py` — `select_model_by_precision()`, `select_best_model()`, ~800 lignes. **Le dernier vrai divergent.** |
   | describer | ⚠️ modèle fixe | `get_blip_model()` — pas un tirage ; à instruire si plusieurs modèles |
   | enhancer, reader, converter, synthesizer, avatarizer, translator, studio | — | pas de tirage (modèle fixe ou pas de modèle) |

   **Vocabulaire** — le tirage ET le listage filtrent désormais en **canonique**
   (`CANONICAL_CAPABILITIES` : `modalities`, `task`, `inputs_required`/`inputs_optional`), via
   `matches_inputs()`. ⚠️ **Piège vécu le 30/07** : j'avais inventé des drapeaux `t2i`/`t2v`/`i2v`
   dans l'ingest — exactement le vocabulaire hétérogène que `model_capabilities.py` supprime.
   Toujours lire `INPUT_MODEL_MATCHING.md` avant de toucher aux capacités.
   **Deux critères distincts, et il faut souvent les deux** : `available_inputs` (FAISABILITÉ :
   ses entrées requises sont-elles là ?) et `consumes` (UTILITÉ : consomme-t-il vraiment ce que
   je fournis ?). Sans le second, « j'ai une image à animer » retenait un modèle texte→vidéo qui
   l'aurait **ignorée** ; filtrer sur `task='image-to-video'` écartait au contraire LTX, qui sait
   l'animer ET tient sur la carte. Effet mesuré : i2v passe de cogvideox (21 Go, offload) à
   ltx-13b-distilled (14 Go, FULL_GPU).
   ⏳ **Reste** : (a) **anonymizer** — migration vers `select_model(classes=…)`, paramètre déjà
   prévu POUR lui ; (b) doublons de `model_key` au catalogue (`audiogen-medium` **et**
   `composer:audiogen-medium` coexistent — cf. commande `dedup_models`) ; (c) `cogvideox-5b`,
   retiré du manifeste imager, subsiste au catalogue via une **autre découverte** que
   `_discover_imager_models` — deux chemins d'ingest pour une même source.
4bis. ✅ **TIRAGE IMAGER — adoption de `select_model()` (29/07)** : l'imager n'avait **aucun**
   tirage ; la vue prenait `DEFAULT_IMAGE_MODEL`, pointé sur `qwen-image-2` → **offload CPU
   garanti** pour tout utilisateur qui ne choisissait pas. `imager/utils/auto_model.py`
   adopte la brique commune (3ᵉ adopteur après composer et transcriber) : « pas d'offload » s'y
   traduit en un **budget** (VRAM libre − marge) passé à `select_model()`, qui retient déjà le
   plus gros modèle qui rentre — aucune règle de sélection n'est réécrite.
   ⚠️ **Deux pièges d'adoption** trouvés par le smoke, à connaître pour les prochains adopteurs :
   (a) le catalogue **préfixe** ses clés (`imager:<id>`) — sans le préfixe, `candidates` ne matche
   rien et le tirage retombe silencieusement sur le défaut **en ayant l'air de marcher** ;
   (b) filtrer les candidats sur les métadonnées, sinon une demande d'image tire une **LoRA de
   spécialité** (`flux-lora-logo-design`).
   🔜 **REQUIS pour que ça morde** : `python manage.py sync_models` sur la base **WSL2** — le
   catalogue porte encore les anciens `vram_gb` (qwen 16, flux 16) ; le tirage lit le CATALOGUE,
   pas le manifeste.
5. **Aucune validation GPU réelle** des correctifs (règle : pas de charge GPU WSL2 par Claude).
   Preuve attendue au prochain qwen-image : `Strategy: MODEL_OFFLOAD` et non `FULL_GPU`.
6. Grille de conformité **non re-mesurée** depuis l'ajout de `reconcile_orphaned_running` à
   l'imager (`python manage.py check_app_conformity`, skill `/conformite`).

## 1. PromptPipeline (prompts centralisés §16.6 / §10.B) — bien avancé
Doc : [`PROMPT_PIPELINE.md`](PROMPT_PIPELINE.md).
- ✅ A Enrichissement génératif (`prompt_enrichment.py`, OFF par défaut `WAMA_PROMPT_ENRICH`)
- ✅ B Assistant (kind `intent`, résource-safe)
- ✅ C Transparence console (🌐 traduit / ✨ enrichi / 📎 référence ; silence si direct)
- ✅ D Composer câblé (MusicGen EN) + synthesizer tranché (TTS jamais traduit)
- ✅ Hook compréhension fichiers de référence (`reference_comprehension.py`, dormant)
- ⏳ Hook RAG (dépend de la fondation `wama/rag/`, §6)
- ⏳ Choisir le 1er adopteur `reference_field` (reco : sous-page describer doc-understanding)
- ⏳ Câbler QC (`qc.py`) en post-génération ; (option) preview pré-lancement

## 2. Model Manager — centralisation + prospection + UI volet droit

> **État réel gestion VRAM — inventaire vérifié 2026-07-20** (demande Fabien : « tracer le réel »).
> **EXISTE** : ① `select_model()` (`model_manager/services/model_selector.py`) = sélecteur central
> complet — budget VRAM **live** (`get_free_vram_gb`), « le plus gros qui tient », `prefer_loaded`
> (⚠ **CORRIGÉ 12/08** : lisait `AIModel.is_loaded` SEUL, que rien n'écrit jamais → `prefer_loaded`
> était INERTE ; lit désormais aussi `resource_governor.resident_models()`, cf. §REPRISE 2026-08-12),
> filtre capacités `requires`/`classes`, paliers `priority`,
> `availability_probe` runtime ; il se déclare remplaçant du `backend_selector` planifié
> (CLAUDE.md corrigé en conséquence) ; ② `WAMAMemoryCleaner` (thread périodique, seuils RAM/GPU
> 80-95 %) + API/UI volet droit — ⚠ **son SIGNALEMENT d'inactivité est corrigé 12/08** (registre
> partagé au lieu de `WAMAMemoryTracker`, jamais alimenté) mais son **déclenchement reste
> intra-process** : depuis le web il ne peut pas décharger un modèle tenu par un worker Celery ;
> ③ `memory_monitor` (jauges + budget du sélecteur) ; ④ contrat `unload()` de `BaseModelBackend`
> sur toutes les apps ; ⑤ `vram_gb` déclaré partout (model_config par app + catalogue `AIModel`) ;
> ⑥ nightly runner **sérialisé VRAM-aware** (teardown avant/après) ; ⑦ ETA hardware-aware
> (`ModelRuntimeStat` par GPU) ; ⑧ sélection LLM par tier (`llm_utils`) + wama-dev-ai
> `select_model_for_role` (découplés by design, jonction = Phase 4 MCP) ; ⑨ sélecteur
> app-spécifique anonymizer (précision/perf).
> **MANQUE (affinages réels)** : ⓐ **adoption en cours — 2/10 apps** (le constat « 0 consommateur »
> du 2026-07-20 est SOLDÉ) : 1er adopteur **composer** (2026-07-21, `utils/auto_model.py`), 2e
> **transcriber** (2026-07-24, c16fbf1 — `backends/manager.py:180-201`, choix VRAM-aware du backend
> ASR via `priority` whisper-first, repli priorité statique) ; les autres gardent leurs sélecteurs
> PROPRES (`select_model_for_role` Ollama, tiers `llm_utils`, précision anonymizer) — l'« étape 3
> adaptateurs » ⏳ ci-dessous EST ce chantier ; l'imager choisit par priorité/disponibilité, pas
> par VRAM libre.
> **1er adopteur : COMPOSER — CÂBLÉ 2026-07-21 ✅** (validé sur base live + VRAM réelle :
> sans réf → musicgen-medium, avec réf → musicgen-melody, sfx → audiogen-medium).
> Design conforme à la décision 2026-07-02 (pas de switch de type) : pseudo-modèles
> **`auto-music`/`auto-sfx`, un par optgroup** (params.py), type dérivé du choix (`_model_type`,
> views), métas WamaInputMatch = union des entrées par groupe (`_input_match_meta`), résolution
> AU LANCEMENT de la tâche (`utils/auto_model.py` : candidats par capacités CATALOGUE → arbitrage
> `select_model(candidates=…)` → replis étagés). ⚠ Reste : validation NAVIGATEUR (option 🧠 dans
> les 2 groupes, grisage auto-sfx si mélodie, génération réelle) + restart WSL2.
> **Suites** : imager avec cette recette ; généralisation `where=` (filtre par VALEUR de capacité,
> ex. task=) dans select_model — les 2 adopteurs (composer, transcriber) calculent encore leurs
> candidats côté app, ce qui confirme le besoin ; ⓑ ✅ **FAIT 2026-07-24 (ffe2a29)** — éviction
> synchrone au chargement livrée en brique commune : `MemoryManager.ensure_free_vram(needed_gb,
> headroom_gb, exclude=)` (`model_manager/services/memory_manager.py`) décharge les unloaders
> déclarés (`register_vram_unloader`) puis re-mesure ; 1er déclarant : transcriber (`apps.py`).
> ⚠ Adoption = 0 appelant applicatif à ce jour (le call-site diariseur a été annulé par le revert
> 6cc37ec) ; reste aussi à déclarer un unloader pour les 9 autres apps ; ⓒ pas de **coordination
> inter-process** — `ensure_free_vram` ne voit que les unloaders du process courant (dict en
> mémoire) ; Django + workers Celery gardent chacun leur registre → double chargement concurrent
> encore possible ; seul le nightly sérialise ; ⓓ `keep_loaded` = comportement `prefer_loaded`/`is_loaded`, pas un flag persistant
> par modèle (à décider si besoin réel).
- ✅ Briques prospection/maintenance (détecteur MAJ, prospecteur HF, installeur Ollama+HF, QC, multi-agents, bench vision, sélecteur)
- ✅ **UI volet droit (débloque le test prospection via `/model-manager/`)** : inspecteur par-modèle
  câblé dans le **volet droit GLOBAL `#wama-right-panel`** (surcharge des blocs `right_panel_settings`
  /`right_panel_actions` de `base.html`) — PAS un drawer ad hoc. Réutilise `WamaInspector` (pattern
  transcriber) + auto-génération depuis `AIModel.to_dict()`. Clic carte → section « Inspecteur du
  modèle » : statut, description longue, ressources (VRAM/RAM/disque), identité (type/source/clé/
  backend/HF), format (actuel→préféré), chemin local, **capacités + extra_info** (métadonnées
  prospection) ; section « Actions du modèle » : lien HF, décharger si en mémoire, convertir vers
  `can_convert_to`. Highlight `.mm-active`, déselect restaure le hint.
- ✅ **Brique générique `WamaDetails`** (`common/static/common/js/wama-inspector-autofill.js` +
  `common/static/common/css/wama-inspector-autofill.css`) : rendu du volet droit piloté par **schéma déclaratif**
  (`renderSections(data, schema)` / `renderActions(data, actions)` ; supporte badges/description/rows/
  kv/code, et actions when/href/onClick/expand). **model_manager rebranché dessus** (1er consommateur).
  Doc : `WAMA_APP_GENERATION_ROUTE.md` (ex-`COMMON_REFACTORING.md`, archivé `docs/archive/`) +
  `WAMA_APP_CONVENTIONS.md §22` + philosophie dans `CLAUDE.md`.
- ✅ **Inspecteur `/apps/` (2e consommateur de `WamaDetails`)** : catalogue d'apps câblé dans le volet
  droit global — clic carte `.app-item[data-id]` → `WamaInspector` + `WamaDetails` sur les métadonnées
  `APP_CATALOG` (`description_long`, types E/S, type de batch, **conformité** score/%/issues) + action
  « Ouvrir l'application ». Données exposées via `json_script` (`apps_list` + URL résolue côté vue).
- ⏳ **À généraliser** : items de file des apps génériques (inspecteur éditable = formulaire 3 niveaux,
  cf. `WAMA_APP_CONVENTIONS.md §22.1` — distinct du rendu lecture seule autofill).
- ✅ **Page allégée (2026-06-23)** : monitoring déplacé du corps vers le volet droit (déplacement de
  nœuds par JS `appendChild` → préserve handlers + polling). Section **Médias surchargée = jauges
  ressources** (GPU/RAM/Models/Disk, toujours visibles). **Memory Cleaner + idle** en section
  Paramètres, **visibles seulement si aucune card sélectionnée** (l'inspecteur prend la place quand
  une card est choisie). Corps de page = en-tête + filtres + catalogue. Footer (RAM/GPU global)
  inchangé. (Sûr : aucun appel externe à `WAMA_RIGHT_PANEL.*` n'écrase les sections du volet.)
- ✅ **Prospection « Proposés par IA » — Ollama-first (2026-06-24)** : chaîne complète prospect→cards
  candidates→install dans l'UI. Champs `AIModel.is_proposed/proposal_kind/confidence/update_complexity`
  (exclus de sync + update_checker). Service `prospect_ollama()` (MAJ Ollama anciens + seed curated,
  idempotent). Endpoints `api/prospect/{ollama,install,reject}`. UI : filtre « ✨ Proposés par IA »,
  cards badges confiance/complexité + Installer/Rejeter, inspecteur enrichi (section Prospection),
  bouton « Prospecter (Ollama) » dans la vue volet « aucune card sélectionnée ».
- 🔄 **Prospection — suites** : ✅ **(b) découverte large FAITE (2026-08-04)** — le seed curated de
  2 modèles codés en dur est supprimé, remplacé par `services/ollama_registry.py` (recherche par
  capacité, tags, **existence vérifiée au manifeste** avant proposition) + rôles déclaratifs.
  **27 candidats** contre 2. Successeur de famille opérationnel (`qwen3.5:35b-a3b → qwen3.6:35b`,
  installé et vérifié de bout en bout, cf. `model_manager/PROSPECTION_PIPELINE.md` §État livré).
  Reste : (a) confrontation multi-agents (Ollama local + cloud via `llm_chat`) — l'arbitrage
  Fabien est **Celery différé, un seul modèle chargé** (règle GPU hôte) ; (c) Celery beat hebdo,
  qui remplacera le stub jamais exécutable `AI-models/weekly_model_discovery.py` ; (d) HF.
- ✅ **Sélection de modèle par QUALITÉ, plus par taille (2026-08-04)** : `AIModel.quality_index`
  (migration 0009) + `services/model_quality.py`, alimentés par `/api/show` (paramètres exacts,
  contexte, quantification, ratio d'experts MoE — tout cela déclaré par Ollama et jamais lu).
  `_best_by_vram` trie désormais par (déjà chargé, qualité) ; la VRAM redevient une CONTRAINTE.
  Preuve : `gemma4:12b` (qualité 42,7 / **7,6 Go**) passe devant `gemma4:e4b` (35,0 / 9,6 Go) —
  le plus petit est le meilleur, et l'ancien tri choisissait l'inverse. Les LLM entrent enfin
  dans `select_model()` : `llm_utils` n'a plus aucun nom de modèle en dur.
- 🔄 **Anonymizer — extraire la COUVERTURE vers `common/`, pas « porter puis supprimer »
  (analyse 2026-08-04)** : `anonymizer/utils/model_selector.py` (1 139 lignes, 4 consommateurs)
  ressemble à une route parallèle de `select_model()`, mais **ne s'y réduit pas**.
  `select_best_models_by_precision()` résout un problème de **couverture** — quelle COMBINAISON
  de modèles couvre toutes les classes demandées, en mêlant spécialisés (visage, plaque) et COCO
  génériques. `select_model()` retourne **un seul** modèle : il ne peut structurellement pas le
  faire. Le porter puis supprimer, comme envisagé d'abord, **détruirait une capacité réelle**.
  Tri mesuré : ❌ `_scan_installed_models_filesystem()` = doublon (le catalogue porte déjà les
  classes de **46 modèles vision sur 48**, extraites indépendamment — pas d'inversion d'étage,
  vérifié) ; ❌ sélection mono-modèle = doublon de `select_model(classes=…)` ; ✅ **couverture
  multi-modèles à porter au commun** (utile aussi au cam_analyzer, au face_analyzer, à
  LocateAnything) ; ✅ politique de précision = spécificité légitime, à DÉCLARER ;
  🔄 `get_download_recommendations()` recoupe la prospection refaite le 2026-08-04.
  **Geste** : `common/services/` → `couvrir_classes(classes, budget_vram, precision)` bâtie AU-DESSUS
  de `select_model()`, puis adoption par l'anonymizer, puis suppression de la seule découverte
  dupliquée. Prérequis : tests de non-régression (floutage visages/plaques) AVANT de toucher.
  **Décision Fabien 2026-08-04** : le floutage lui-même devient une **fonction Data**
  (`FunctionSpec` `binding=app`, `impl=anonymizer…`, `cost.vram_gb`) — le catalogue le permet
  déjà. La couverture, elle, reste de l'INFRASTRUCTURE : `common/services/`, consommée par la
  fonction, jamais exposée en card.
- ⏳ **Prospection — routing capacité→app (Axe 3, décidé 2026-06-29)** : à la proposition d'un modèle,
  inférer tâche + types E/S (pipeline_tag/tags/README HF) puis **réutiliser le matcher de capacités**
  (`app_registry.normalize_types`, déjà utilisé par le studio) contre `APP_CATALOG.input_types/
  output_types` → annoter la suggestion d'un `target_app` (« intègre dans X ») ou « aucune app ».
  **Phase A** (router vers app existante) = faisable, fort ROI ; **Phase B** (faire émerger une app
  depuis un manifeste généré) = **gatée** sur la maturité du runtime manifeste (cf.
  `WAMA_APP_GENERATION_ROUTE.md` + `WAMA_MANIFEST_SPEC.md`, §38 ; ex-`GENERALIZATION_PLAN`
  archivé `docs/archive/`). Toujours humain-dans-la-boucle, jamais
  d'auto-application. Cf. `memory/project_queue_solitaire_prospection.md`.
- ⏳ Étape 3 centralisation (adaptateurs anonymizer/transcriber + migration per-model)
- ⏳ Chargeur générique ; agents cloud pour confronter ; recherche web benchmarks
- ✅ **Backup distant, ARCHIVE CUMULATIVE (2026-06-24, vocabulaire corrigé 2026-07-28)** :
  `remote_backup` réplique l'arbo locale `AI-models/models/`
  (`dest = WAMA_MODEL_BACKUP_PATH / source.relative_to(AI_MODELS_DIR/'models')`), récursif
  (préserve blobs/refs/snapshots), zéro chemin en dur. **Seuls les CHEMINS sont répliqués, pas
  l'état** : sens unique, aucune suppression distante — un fichier présent à distance et absent en
  local n'est jamais visité. ⚠ Ne JAMAIS ajouter de passe de prune « pour synchroniser » : le
  distant existe pour garder les formats d'origine que le local a retirés après conversion
  (invariant : local = `.onnx` seul, distant = `.pt` + `.onnx`). Le terme « miroir », employé
  jusqu'au 28/07, invitait précisément à cette erreur.
  + `offload_file()` : backup → vérif taille distante → suppression locale, garde-fou si vérif
  échoue. C'est le SEUL chemin de suppression d'une source, via `FormatConverter._retire_source()`
  (2026-07-28) — les `unlink()` secs de `_convert_to_onnx`/`_convert_to_safetensors` sont supprimés,
  et la source reste en local si le distant est indisponible ou la copie tronquée.
  Montage WSL : `\\vrlescot\SAVES`→`/mnt/shares/SAVES` (drvfs/fstab),
  env `WAMA_MODEL_BACKUP_PATH` dans `start_wama_prod.sh`.

## Tests fonctionnels nocturnes (charpente, 2026-06-24)
- ✅ **Charpente** : `common/services/nightly_tests.py` (registre déclaratif `Scenario` + runner
  **sérialisé VRAM-aware** avec téardown avant/après + rapport JSON + **user de test dédié**
  `wama_nightly_test`, jamais id=1) + commande `python manage.py run_nightly_tests [--app][--stage][--dry-run]`.
  Étapes : `wired` | **`ui`** | `model_loaded` | `output`. **Skip vs fail** (`SkipScenario` → ⊘, dépendance absente).
- ✅ **Smoke UI (2026-07-31)** : `common/services/ui_smoke.py`, **13 scénarios auto-enregistrés**
  (apps DÉDUITES des URLs via `reverse("<app>:index")` — aucune liste en dur). Étape `ui` à part :
  ~45 s au total, **aucun GPU côté WSL2**. Trois couches, **une seule décide** :
  1. **barrière déterministe** (seule à faire échouer) : HTTP 200, **zéro erreur console JS**,
     coquille de contenu présente, + **parcours des onglets** (la majorité des erreurs JS vivent
     dans les gestionnaires et n'apparaissent qu'au clic) ;
  2. **diff de capture** vs référence (`logs/ui_smoke/reference/`, hors git) : dit OÙ ça a bougé,
     **ne fait pas échouer** (file d'attente et barre de ressources changent chaque nuit) ;
  3. **triage VLM local** (`gemma4:12b`) **uniquement sur les captures modifiées** : dit QUOI, en
     français. **Pas juge** — même précaution que `bench` (ex-`bench_describer`), le juge final reste humain.
  Calibré : 2 passages consécutifs à références fraîches → **0 triage sur 13** (pas de coût VLM
  les nuits sans changement). **Sessions nettoyées** (les anonymes créées par le passage ; une
  session portant `_auth_user_id` est épargnée — ne jamais déconnecter un utilisateur réel).
  ⚠ **CRON : exporter `OLLAMA_HOST`** (Ollama est sur l'hôte Windows) sinon la couche 3 échoue en
  silence. Trouvailles dès la 1re exécution : double inclusion de `media-picker.js` (imager +
  avatarizer → `pageerror` qui interrompt le script) et `vision_probe` qui envoyait l'appel Ollama
  LOCAL dans le proxy UGE (504) — deux bugs invisibles dans les logs serveur.
- 🗑 **`wama-analysis/` SUPPRIMÉ (2026-07-31)** : extracteur de fonctionnalités par VLM sur 101
  captures **manuelles**. Échec **structurel**, pas d'ingénierie : le modèle recopiait l'exemple de
  format du prompt (113 « fonctionnalités » en 74 min, toutes `OTHER`, du type « Feature 1 — This
  is a real feature »). Un VLM devant une capture décrit des **pixels** ; il ignore qu'un bouton
  déclenche une tâche Celery. La bonne idée (faire regarder l'UI par un modèle vision) est reprise
  correctement en couche 3 ci-dessus : le VLM y **commente un écart détecté**, il n'est pas source
  de vérité. Archivé hors dépôt par Fabien.
- ✅ **Gabarits `model_loaded`** : `transcriber.asr_load` (VALIDÉ runtime, charge Whisper ~10 s) +
  `enhancer.deepfilternet_load` (skippe si `df` absent). Pattern : `<app>/nightly_scenarios.py` +
  `register_scenarios()` dans `apps.py::ready()`.
- ✅ **Infra** : tâche Celery `common.run_nightly_tests` (queue gpu) + beat **gated** (03:00 si
  `NIGHTLY_TESTS_ENABLED=1`, sinon pas d'auto-run).
- ✅ **Contrôles SÉCURITÉ (2026-08-13, suite à l'évaluation Aikido → équivalents locaux d'abord,
  ROADMAP §16.10)** : 2 scénarios `consistency` de plus — `common.consistency.dep_vulns`
  (`check_dep_vulns` : CVE des paquets INSTALLÉS via l'API OSV.dev, contrat-cliquet = baseline
  versionnée `tools/security/osv_baseline.json`, une section par venv) + `common.consistency.secrets`
  (`check_secret_leaks` : gitleaks sur l'historique complet — 1034 commits, 0 fuite, réécriture du
  23/07 confirmée — + hook pre-commit anti-récidive vérifié, hook mort = ROUGE). Provisioning
  binaire+hook : `python scripts/fetch_security_tools.py`. Code sortie 3 = outillage/réseau absent
  → SKIP, pas de faux rouge. Validé : stage `consistency` complet joué, les 2 nouveaux verts.
  Les 2 rouges relevés au passage ont été SOLDÉS dans la foulée (même journée) : redundancy
  8 → 0 (triage : 1 résorption réelle `_params`→`declared_param_schemas` dans param_schema,
  anonymizer branché sur `normalize_types`, codeformer exclu comme vendored, 3 pragmas
  raisonnés — ROADMAP §16.9 ②) ; manifest_corpus = les 3 faux « périmés » venv_win CONNUS
  (§REPRISE 2026-08-13), leçon désormais CODÉE : le scénario skippe depuis Windows.
  **Stage `consistency` : 8/8 OK depuis WSL2 (fait foi), 7/8 + 1 skip voulu depuis Windows.**
- ⏳ **À compléter** : scénarios autres apps (imager/synthesizer/anonymizer) ; vrais `output` sur
  fixtures (assertions + nettoyage IDs) ; timeout dur (Celery soft_time_limit) ; page de résultats ;
  activer le beat après validation WSL.

## 2bis. Inspecteur volet droit unifié (modèles + apps) — 🔄
Un seul composant `WamaInspector`, deux catalogues, contenu généré depuis la métadonnée.
- 🔄 **Apps** (`/apps/` ← `common/app_registry.py::APP_CATALOG`, 10 apps génériques) : ajout d'un champ
  `description_long` par app → volet droit = inspecteur d'app (description complète + I/O + batch +
  **score conformité live + conventions manquantes** via `get_conformity_summary`).
- ⏳ **Modèles** : idem §2 (inspecteur par-modèle depuis `AIModel.to_dict()`).
- ⏳ **Lacunes catalogue** : `media_library` et apps **WAMA Lab** (cam_analyzer, face_analyzer) absents
  de `APP_CATALOG` (catalogue = apps génériques seulement) → décider de les inclure (flag `lab`/`hub`).
- ⏳ **Grille §15** (WAMA_APP_CONVENTIONS) = photo manuelle (2026-05-16) dérivée du registre live →
  remplacer par un pointeur vers `/apps/` (`get_conformity_summary()`, seule source à jour ; NE PAS
  recopier de scores figés ici, ils dérivent). Scores live **2026-07-02** (après correction F1 des flags
  `inspector`/`modes`, cf. REMOVAL_LEDGER) : transcriber 76% (top) · describer/enhancer/reader 68% ·
  converter 62% · synthesizer 61% · anonymizer 59% · composer 57% · **imager 42%, avatarizer 40%
  (à travailler)**.

## 3. wama-dev-ai (agent Ollama local) — fiabilisé
- ✅ Robustesse runner (troncature, retry EOF, read_file numéroté, fallback `gemma4:e4b`, `--force-model`, cp1252) — validé pour audit ciblé
- ✅ Règle de délégation scopée (CLAUDE.md) + `wama-dev-ai/query_transcript.py`
- ⏳ Calibration sélecteur RAM ; Phase 2 (API WAMA read-only) ; option routage cloud LiteLLM ; Phase 4 MCP (plus tard)

## 4. Refactoring common (unification) — documenté
Doc consolidé : [`WAMA_APP_GENERATION_ROUTE.md`](WAMA_APP_GENERATION_ROUTE.md) (remplace
`COMMON_REFACTORING.md`, archivé → `docs/archive/`). Transcriber = référence.
- ✅ Briques extraites (wama-app-base, wama-inspector, wama-model-help, partials cards, eta…)
- ✅ `backend_selector` **annulé/remplacé** par `model_manager/services/model_selector.py::select_model()`
  (cf. §2 — ne pas créer le fichier) ; ⏳ `_settings_modal.html` générique
- ⏳ Adoption app par app (converter, describer, enhancer, imager, reader, synthesizer, anonymizer, composer)

## 5. Cam Analyzer (WAMA Lab) — consigné, à finaliser
Docs (3 piliers, 2026-07-21) : `wama_lab/cam_analyzer/README.md` (carte) + `CAM_ANALYZER_CHAINE_TRAITEMENT.md` (chaîne+conception) + `CAM_ANALYZER_CHANGELOG.md` (historique+backlog « État courant & RESTE ») ; spécificités projet → `projects/ENA_CASA.md` ; ROADMAP §9.
- ✅ Pipeline quasi-complet (extraction rosbag/RTMaps, YOLO+BoTSORT, YOLOPv2, SAM3, LaneEvent, ConflictEvent/TTC, fenêtres intersection, passes incrémentales)
- 🔄 Tests (pas tout validé)
- ⏳ Phase 3 vitesses irréalistes — ✅ calibration étapes 2a (projection sol) / 2b (recalage ortho)
  + `homography_estimator` (pitch×k1) + lissage Kalman+RTS livrés ; ✅ passes incrémentales livrées
  (étapes 1-3) ; **reste** : validation terrain des vitesses, infos caméras pour mesures absolues,
  (option) palliatif UI segments < 1 s. Détail : `CAM_ANALYZER_CHANGELOG.md`.

## 6. RAG (fondation §8c) — non démarré (prérequis du hook RAG §1)
- ⏳ Store ChromaDB + embedder bge-m3 ; module `wama/rag/` (store + embedder) ; indexation via Médiathèque

## 7. Anonymisation multimodale (§16.4) — décidé, non construit
- ⏳ Presidio + GLiNER FR ; mode « texte » = porte privacy avant-cloud (même composant) ; audio (PII + biométrie) ; dispatcher par modalité

## 8. Translator (§10)
- ✅ 10.B runtime (via PromptPipeline)
- ⏳ 10.A i18n statique (.po/.mo) ; glossaire éditable ; graduer `translator.py` → app `wama/translator/`

## 9. Media Library
- ✅ Phase 1 (UserAsset/SystemAsset, voix migrées)
- ✅ 2026-07-09 **Phases 2-4 en fait FAITES** (doc périmé corrigé — vérifié empiriquement lors de
  l'audit doc §23) : filtrage UI présent (`index.html`), `MediaProvider`/`UserProviderConfig`
  (migration `0004`) + connecteurs Wikimedia/Pixabay/Freesound/Jamendo/Pexels/Openverse (migration
  `..._add_providers_phase5`). Reste lié à l'indexation RAG (§6, non démarré).

## 10. Progression globale + ETA
- ✅ **Barre globale + balayage coloré** : tronc commun (`_global_progress.html` + `wama-global-progress.js`), card « Nouveau » en 1ʳᵉ position, déployé partout (apps mono- et multi-domaine, barres séparées par file).
- ✅ **ETA seeding auto-apprenant + hardware-aware (terminé 2026-06-27)** : service `model_manager/services/eta_estimator.py` (`ModelRuntimeStat` EMA par modèle×hardware, a-priori par domaine, `fallback_seconds` = heuristique app au démarrage à froid). **Câblé sur les 10 apps** (transcriber, synthesizer, describer, reader, composer, converter, imager image+vidéo, enhancer image/vidéo+audio, avatarizer). 2 patterns : service-based vs load-séparé (imager). Nouvelles unités `page` (OCR) / `mb` (ffmpeg). Détail : `memory/project_eta_seeding.md`.
- ⏳ Reste : **valider sur données réelles** (restart WSL2) ; calibrer les a-priori par modèle (`AIModel.extra_info['eta']` ou test nocturne) ; ETA agrégé batch ; anonymizer (pas encore câblé — vérifier).

## 11. Transcriber — correction assistée IA (à reconfirmer dans le code)
Doc : `wama/transcriber/TRANSCRIBER_CORRECTION.md`.
- ✅ Éditeur page dédiée (onde + heatmap), guidage non destructif, timecode « aller à », défaut ASR Whisper large-v3
- ⏳ Suite de la correction assistée

## 12. Document understanding / OpenScholar (§10.B) — non construit
- ⏳ Sous-page Describer : Reader/Docling → multimodal → description FR directe. = 1er adopteur naturel du hook fichiers de référence.

## 13. Déploiement — note d'architecture
- ⏳ Migration Apache Windows → Nginx Linux ; plan serveur prod (LiteLLM orchestrateur). Voir `memory/project_deployment_roadmap.md`.

## 14. WamaModes (clé de voûte modes) + Mots-clés de prompt — palier 2026-06-25
Doc : `MODES_QUEUE_UX.md` (P1 schéma), `memory/project_prompt_keywords.md`.
- ✅ Schéma déclaratif domaines→modes (`common/utils/app_modes.py`) + générateur JS (`common/static/common/js/wama-modes.js`) + endpoint `/common/api/app-modes/<app>/`.
- ✅ **Imager (app de référence)** : WamaModes **pilote les barres de mode** image+vidéo (`renderInputs:false`) ; radios natifs = source de vérité (cachés si rendu OK, résilient sinon). Apparence préservée via `domain.variant` (image=bleu, vidéo=vert), `block` (pleine largeur), `modesLabel`. Schéma vidéo aligné `txt2vid`/`img2vid`.
- ✅ **Mots-clés de prompt** : modèle `PromptKeyword` (tronc commun + perso) dans la médiathèque, seed 52, 3 endpoints, brique commune `wama-prompt-chips.js` (chips par catégorie, insère/retire dans le prompt, + perso, badge `onCount`). Câblé Imager (prompt image+vidéo) + onglet « Mots-clés » médiathèque.
- 🔄 **À confirmer visuellement** (Fabien teste après restart serveur) : chips affichés + badge 52.
- ⏳ Prochain palier WamaModes : `renderInputs:true` (entrées typées + réglages par mode sur la card « Nouveau ») — **touche la soumission, à faire délibérément** (pas en cours de test). Puis réplication du pilotage de modes sur anonymizer (yolo/sam3) / synthesizer (temps réel).
- ⚠️ Règle : préserver la mise en forme à l'identique en généralisant (`memory/feedback_preserve_formatting.md`).

## 15. Méta-app studio + vision production AV — palier 2026-06-25
Docs : `STUDIO_VISION.md`, `memory/project_meta_app_studio.md`, `memory/project_studio_av_production.md`.
- ✅ **Studio = app Django dédiée `wama/studio`** (migrée de `common`) : `/studio/` + `/studio/api/nodes/`. Nœuds-app dérivés `APP_CATALOG`+`app_modes`, **ports typés** travail/prompt/référence, **catégories unifiées**, **typage par connexion**, nœuds-source (Batch de prompts, Médias importés), **inspecteur volet droit** (WamaDetails). Vraie app : nav + card accueil (Bêta), gatée par accès.
- ✅ **Vision AV consignée** : studio = pipeline montage vidéo + mixage/mastering assistés IA. Prior art `MusicVideoGenerator`. Monteur/Mastering = **roadmap only** (retirés des nœuds concrets).
- ✅ **Décision archi** : montage & mixage = **apps dédiées** ; Monteur = 1 app à modes + `edit_page` par mode ; Mixage/Mastering plus tard.
- ✅ **Persistance + exécution V1** (2026-07-11, §37) : StudioPipeline/StudioRun, moteur
  Celery topo (runners synthesizer→avatarizer via tool_api), toolbar Save/Load/Run,
  coloration des nœuds. ⏳ Suites : plus de runners (imager, converter…), sorties → dossier
  filemanager studio, ports multi-entrées, specs Fabien (montage/mixage).

## 16. Profils / permissions / notifications / rétention — palier 2026-06-25
Doc : `PROFILES_PERMISSIONS.md` + `memory/project_profiles_permissions.md`.
- ✅ **Permissions 2 axes** : `UserProfile.account_tier` + rôles métier (Groups `role:*`) ; `AppAccessPolicy` DB **éditable** ; **matrice rôles×apps** (`/accounts/manage/app-access/`) groupée en sections + tooltips ; liste d'apps **pilotée par le registre** (`seed_access` sur `APP_CATALOG ∪ extras`). Enforcement nav + cartes home + middleware (`app_id_for_path`). Seeds auto au démarrage (`start_wama_*.sh`).
- ✅ **Notifications email** : `notify_email`/`notify_on` (page profil) + `common/utils/notifications.py` + signal imager + câblé **les 10 apps**.
- ✅ **Rétention médias** : `media_retention_days` (page profil) + `common/services/retention.py` (purge par introspection) + beat quotidien + pré-avis.
- ⚠️ Bases Postgres **distinctes** Windows/WSL2 (cf. `memory/reference_infra_wsl_windows`) — agir via `wsl.exe` pour le live.

## 17. Uniformisation — gold standard Transcriber (⭐ PHASE COURANTE)
Voir `memory/feedback_transcriber_gold_standard`. Stratégie : finir **Transcriber** à 100 % (conformité + esthétique file Solitaire épurée) → recette, puis dérouler à toutes (Imager en dernier). **Garde-fous** : préserver temps réel (Speak) + page de correction (laissée telle quelle, bouton non généralisé).

**Réaffirmé 2026-06-29 (Fabien)** : on FINIT le Transcriber AVANT la généralisation §18 (« finir 1 app
puis généraliser »). Déjà avancé : briques communes (`_new_item_card`/`_card_progress`/`_card_state`/
`_queue_actions`), animation fan-in Solitaire, switch mode normal/temps réel. **Reste :**
- ⏳ **Card d'entrée UNIVERSELLE** (✅ volet **URL** livré 2026-07-21/22 — `show_url=True` +
  `WamaApp.initUrlImport`/`WamaBatchImport.ingestText`, cf. §23.1 ; reste Speak + accordéon) :
  fusionner le **Speak (temps réel) DANS `_new_item_card`** (affordance
  Speak à côté de drop/fichier/URL/batch), à la place du **sélecteur de mode** en haut de page (entrée
  progressive, cf. accordéon prototypé sur Synthesizer). **Préserver Speak intact** (garde-fou). = le
  morceau central.
- ✅ **Staging supprimé (2026-06-29)** — décidé Q2, cf. `CARD_DESIGN §8.5`. « Staging » = statut `DRAFT`.
  `_auto_wrap_orphans` n'exclut plus `DRAFT` → brouillons rendus **dans la file** comme cards BROUILLON
  (config via inspecteur, lancement via `start` qui gère DRAFT). Retirés : `staging_list` + `#stagingZone`
  (IndexView/template), 4 vues `stage_*` + URLs, config JS + handlers JS staging. Validé : `check` OK,
  page 200, zéro résidu. Reste lié : focusCard sur l'ajout en brouillon (déjà câblé upload/duplication).
- ✅ **Animation fan-in** ralentie (.26→.42s + stagger + easing, 2026-06-29).
- ⏳ **Finition esthétique** : conformité CARD_DESIGN (2 états, barre pleine largeur, boutons
  color-codés, aperçu sortie systématique, inspecteur).
- ⏳ Les items §18 (`focusCard`, card mère `_batch_card`, manipulation in/out, insertion chronologique)
  reçoivent leur **implémentation de référence SUR le Transcriber**, puis sont extraits en commun.

→ Transcriber à 100 % **d'abord**, puis §18 (généralisation) + Synthesizer/Imager.

## 18. File Solitaire — focus, card mère homogène, animation (décidé 2026-06-29) — ⏳
Doc : `CARD_DESIGN.md §8`. Affine §17 (file épurée) + §3ter (pile Solitaire).
**Séquencement : APRÈS §17** — ces items reçoivent leur implémentation de référence SUR le Transcriber
(dans le cadre de « finir le Transcriber »), puis sont extraits en briques communes pour les autres apps.
- ⏳ **Focus à l'ajout + nav** : helper commun `WamaQueue.focusCard(id, {scroll:'center',select,pulse})`
  (scrollIntoView centré + halo + sélection inspecteur), partagé ajout ET nav clavier. Inspecteur non
  bloquant à l'ajout (PAS de modale auto). `scroll-margin-top` = hauteur header (bug card du haut masquée).
  Le bug « card en bas de pile » est **app-spécifique** (PAS commun) → remède = **centraliser une
  insertion déterministe chronologique** ; les apps qui l'adoptent perdent le bug.
- 🔄 **Tri/filtrage de la file** : **EXTRAIT EN COMMUN (2026-07-03)** — `common/utils/queue_view.py`
  (`apply_queue_sort_filter`, persisté en session, clés partagées entre apps) + partial
  `common/_queue_toolbar.html` (tri + filtre + toggle Ligne/Mosaïque + `_queue_actions`, option
  `download_url`). **Consommé : Transcriber (pilote 2026-06-29, basculé sur la brique) + Composer
  (hérite, 2026-07-03)**. Défaut chronologique récent = acté partout. **Reste** : porter aux 8 autres
  apps (le **reader** a encore son tri batch-first app-spécifique) ; options sort type/durée.
  **CSS mosaïque aussi globalisé** (contrat `.wama-card`, wama-inspector.css) : solitaire (batch
  replié = cellule mosaïque, déplié = pleine largeur), empilement VERTICAL des sections en grille,
  fan-in — corrige la régression solitaire Transcriber ET la compression horizontale Composer.
- 🔄 **Manipulation directe (CARD_DESIGN §3bis)** : déplacer DANS/HORS d'un batch = **DRAG souris façon
  Solitaire, PAS un bouton** (spec d'origine Fabien ; déjà trop de boutons). **Backend prêt + validé**
  (2026-06-29) : vue/URL `remove_from_batch` (sortie → `_wrap_transcript_in_batch` = batch-of-1 isolé ;
  signal recale l'ancien batch) + `consolidate` (entrée). **Reste = l'UI DRAG** (SortableJS, posera
  `wama_focus_card` sur l'id déplacé). **Backend du drag COMPLET + validé (2026-06-29)** : `remove_from_batch`
  (sortie), `reorder` (`row_index` dans un batch), `move_to_batch` (entrée), `consolidate` (existant).
  **Reste = uniquement l'UI SortableJS** branchée sur ces endpoints → **session VISUELLE**. (Filtrer/trier
  = FAIT, voir bullet ci-dessous.) NB : bouton « sortir » ajouté par erreur puis retiré.
- ✅ **Fix hauteur mosaïque** (2026-06-29) : cards individuelles à hauteur égale par ligne
  (`align-self:stretch`) ; card batch laissée courte (distinction, choix Fabien).
- 🔄 **Card mère = squelette des filles** : **P1 FAIT + validé sur le Transcriber (référence, 2026-06-29)** :
  la mère est désormais `.synthesis-card.is-batch` (MÊME squelette `.row` que les filles : identité
  Batch#/N éléments, état agrégé, barre de progression agrégée, actions batch) ; ne diffère que par
  `.is-batch` (couleur) + méta/actions. Toggle collapse scopé sur `col-md-9` (actions HORS toggle →
  handlers délégués préservés) ; look « pile Solitaire » + fan-in conservés. **+ bouton ▶ Lancer/Relancer
  ajouté sur la card mère** (pos. 2, vue `batch_start`, sans passer par la modale) → convention fixée
  `WAMA_APP_CONVENTIONS §9.8`. **Reste** : extraire en
  brique commune `common/templates/common/_batch_card.html` (réutilise `_card_progress`/`_card_state`)
  pour dédupliquer entre apps, puis P2 (éventail `translateY`) / P3 (polish).
- ⏳ **Dépliage éventail + animation** : P1 mère `.is-batch` + collapse Solitaire existant ; P2 overlap
  `translateY` ∝ distance à la card sélectionnée + stagger ; P3 durée ~0,35–0,45 s easing (trop rapide
  aujourd'hui). Lié `wama-queue.js`.

- ⏳ **Card d'import homogène (DIFFÉRÉ passe visuelle/globalisation)** : la rendre card-like + 1ʳᵉ card
  de la file (accordéon : replié compact homogène ↔ déplié = modalités d'import avec de la place ; NE PAS
  miniaturiser les champs). Décision/impl **une seule fois** dans `_new_item_card` après globalisation.
  + retirer la répétition « File d'attente » de l'en-tête. Détail : `CARD_DESIGN §8.6`.
- ✅ **Tri groupé** (2026-06-29) : options « Batchs puis cards » / « Cards puis batchs » (chrono en 2nd
  ordre) ajoutées au tri, validées. Défaut reste chronologique pur.

## 19. Audit de conformité POST-Transcriber (⏳ à déclencher après le chantier) — demandé 2026-06-29
Doc complet : `memory/project_post_transcriber_conformity_audit.md`. **But : 100 % commun sauf
spécificités d'app**, et préparer « génération d'app par manifeste ». À faire **quand le Transcriber
est fini** (P2 éventail, manipulation in/out, esthétique 2 états, nav clavier restants). Périmètre :
- ⏳ Conformité conventions par app + **MAJ table §15** ; MAJ conventions avec les décisions de session
  (staging supprimé, card mère, focusCard, entrée universelle, local-first…) ; chasse aux conventions
  obsolètes/contradictoires.
- ⏳ **Homogénéité du formalisme** (card/file/inspecteur/modes) + **compatibilité inter-apps**.
- ⏳ **Logique de nommage des fonctions** (vues/handlers JS/helpers/URLs/ids) → convention de nommage +
  normalisation des divergences (`start`/`launch`/`commit`, `batch_*`, `*_all`…).
- ⏳ **Restes de pansements** (recompute manuels, duplications) → centraliser.
- ⏳ **Récap common vs à-globaliser** (inventaire complet) → feuille de route vers 100 % commun
  (`WAMA_APP_GENERATION_ROUTE.md` — consolide COMMON_REFACTORING + GENERALIZATION_PLAN, archivés
  `docs/archive/`) + **préparation manifeste** (axes restants, code
  app-spécifique irréductible = `process()` + pages d'édition).
- Méthode : passes read-only volumineuses délégables à **wama-dev-ai**, validées par Claude.

## 20. Consolidation des mécanismes de génération d'UI (⏳ TÂCHE 1 avant tout travail UI par app) — 2026-07-01
Spec précise : `memory/project_ui_mechanisms_consolidation.md`. **Le registre de modèles est UNIQUE**
(`ModelRegistry` + `ModelInfo` + `capabilities`) — MAIS plusieurs **chemins concurrents de génération
d'UI** coexistent : modale `WamaParams.render(item)` [transcriber/converter/reader/describer] vs
hand-built [synthesizer/avatarizer/composer] ; volet `WamaParams.render(panel)` vs `initFromSchema` ;
capacités→UI `WamaModelCaps` (synthesizer) vs rien (transcriber) vs `show_if` **hardcodé** (anti-pattern
enhancer). Avant d'uniformiser d'autres apps → **inventorier** (inventaire PRODUIT puis absorbé dans
`WAMA_APP_GENERATION_ROUTE.md` ; source archivée `docs/archive/UI_MECHANISMS_CONSOLIDATION.md`)
+ **plan de convergence**. Référence =
Transcriber. Contraintes : route existante, **zéro réinvention, zéro hardcoding**. Idéalement en **session
neuve** (contexte chargé = erreurs). Recoupe et précise §19.
- ✅ **Enhancer uniformisé (2026-07-01)** : onglets domaine `WamaModes` + bouton de cycle sur les 2
  domaines + inspecteur `initFromSchema` par domaine + **modales portées sur `WamaParams` (context:'item')**
  + aide modèle courte/longue + **couche capacités pièce 1/3** (moteurs audio resemble/deepfilternet au
  catalogue avec `capabilities.params`). **Reste enhancer** : pièce 2 (WamaModelCaps niveau-**champ**) +
  pièce 3 (câblage capacités→visibilité + **retrait du `show_if` hardcodé**).

## Bugs / dettes connus

> Repris de ROADMAP §0 (2026-07-20, contrat des niveaux — à revalider) :
-  **Qwen3-ASR** (Transcriber) — Backend implémenté (`qwen_asr_backend.py`) mais non fonctionnel — erreurs de dépendances à l'import — 🐛 Bloqué — Résoudre conflits deps pip (transformers, torchaudio, accelerate) 
- 🐞 Higgs Audio V2 : ~5 s d'audio dégradé malgré tous les patches — non résolu.
- 🔧 Patches venv → toujours via `patches/apply_patches.py`.
- 🌐 Headroom code-aware : `Mode: token` actuel → activer via terminal neuf + vérifier `headroom_stats`.
- 🩹 **`show_if engine=resemble` hardcodé** (enhancer audio, `params.py`) = anti-pattern à remplacer par
  capacités-driven (WamaModelCaps) — pièce 3 de la couche capacités (§20). Cf. `feedback_ui_from_model_capabilities`.
- 🔐 **Secrets externalisés (✅ 2026-07-23)** : `SECRET_KEY` + mot de passe DB + proxy sortis de
  `settings.py` vers `.env` (gitignoré) ; `.env.example` commité ; secrets sortis du dépôt (`outillage git`,
  les références ont été mises à jour) sur `main`+`dev`. Commande `rotate_secrets --all --also-wsl` (2 bases Postgres).
  Détails : `INFRA_WSL_VS_WINDOWS.md §Secrets`. **Reste (prod)** : rotation effective des secrets +
  injection env via systemd/Vault ; option : masquer `vrlescot`/`172.29.240.1` (divulgation infra mineure).
- ✅ **Tâches RUNNING orphelines après crash worker (2026-07-24/25)** : brique commune
  `reconcile_orphaned_running` (`common/utils/process_control.py`) — 93329c4 puis 32df89c (preuve
  positive de mort : le worker propriétaire doit avoir RÉPONDU, fin des faux échecs sur worker
  `--pool=solo` occupé). Adoptée par **transcriber seul** ; ⏳ à propager aux 9 autres apps.
- ✅ **Le stop survit au redémarrage worker (2026-07-24)** : revokes persistants
  `celery --statedb=$LOG_DIR/celery-{gpu,default}.state` dans `start_wama_dev.sh`/`start_wama_prod.sh`
  (3e38994).
- ✅ **Quick wins audit conformité (2026-07-25, d03e256)** : describer ⧉ dupliquait EN DOUBLE
  (handler local + brique queue-actions.js → retiré) ; anti-race start_all/batch_start describer
  + batch_start avatarizer ; réconciliation orphelins câblée composer/describer/reader (adoption
  4/10) ; alias `add_to_imager`/`add_to_composer` au TOOL_REGISTRY ; scoring conformité ne compte
  plus `export_binding` (+1 gratuit). ⚠ Restart WSL2 requis ; validation navigateur ⧉ describer.
- 🐞 **Bugs converter hérités de `MODAL_ACTIONS_AUDIT.md §5` (archivé)** : ① le clic « Enregistrer »
  de la modale batch ne ferme pas toujours la modale (état bootstrap) ; ② après édition des réglages
  d'un job, la card ne reflète pas immédiatement le nouveau format (attendre le refresh). À
  re-vérifier au prochain passage converter (peuvent être résorbés).
- ✅ **Corrections de fond 2026-07-25 (2e salve)** : converter `.wama-card` posé sur `_job_card`
  (⚠ validation navigateur mosaïque requise) ; reader `WAMA_INGEST` + `ensure_local_input` en tête
  de `read_document_task` (le `source_url` persisté-jamais-téléchargé est résolu) ; anonymizer :
  verrous cache rendus ATOMIQUES (`cache.add` au lieu de get+set — l'audit disait « 0 anti-race »,
  en réalité verrous cache avec fenêtre TOCTOU ; le checker reconnaît maintenant `cache.add`).
- ✅ **Anti-race enhancer/synthesizer (2026-07-25, 3e salve)** : `begin_processing` sur enhancer
  start_all + batch_start + audio_start_all (options globales déplacées dans le reset callback) et
  synthesizer start_all + batch_start (reset partagé `_reset_synthesis_for_relaunch`, options
  persistées AVANT le verrou). `anti_race` mesuré ✅ sur les deux.
- 🐞 **Constats d'audit 2026-07-25 restants** : enhancer
  8 `alert()` résiduels (audio-enhancer.js) ; `during_preview` transcriber/describer : texte
  partiel existe (cache) mais PAS branché au mécanisme commun de preview « pendant » (flag False
  = capacité runtime, ne pas flipper sans câbler). Scores honnêtes (24 crit.) : reader 21✅ ·
  composer 20✅ · transcriber/describer ~90 % · enhancer 11✅ · synthesizer 11✅ · avatarizer 11✅ ·
  anonymizer 8✅ · imager 6✅. La grille live = 35 booléens DÉCLARATIFS (rien n'est mesuré) —
  chantier : critères M1-M26 automatisables proposés (rapport d'audit session 2026-07-25).

## Ordre de reprise recommandé
1. **Consolidation des mécanismes de génération d'UI (§20)** — inventaire + plan de convergence AVANT tout
   travail UI par app (sinon on aggrave la divergence). Idéalement session neuve. → puis uniformisation
   des 10 apps → manifests → chaîne de génération (`project_manifest_generation_priority`).
2. Model Manager volet droit (débloque le test prospection — ROI immédiat).
3. Cam Analyzer Phase 3 (calibration + vitesses).
4. Fondation RAG (`wama/rag/`) — débloque hook PromptPipeline + Media Library.
5. Refactoring common app par app (par petites sessions).

---

## 20bis. Portage schéma-driven — KICKOFF (état 2026-07-05, MAJ empirique 2026-07-06)

**3 apps AU MÊME NIVEAU : Transcriber · Composer · Describer** — elles partagent : tri/filtre +
toolbar commune (`queue_view.py` + `_queue_toolbar`), badge d'onglet, mosaïque/solitaire
(contrat `.wama-card`/`.is-batch`), card d'entrée `_new_item_card` en tête d'onglet (ordre
canonique card → progression → toolbar → file), modale générée + pied commun, **card = partial
serveur unique + endpoint `card_html` + `refreshCard`** (⚠ re-bind si events par card — leçon
describer), ETA commune (eta_estimator + WamaEta), batch import unifié (balises/en-têtes
multi-délimiteurs/positionnel + template généré), catégories d'apps + couleurs d'identité
dérivées (menu/accueil//apps/ générés du catalogue).

> ⚠️ **Les scores `x/40` ci-dessous sont DATÉS (grille de juillet 2026) — ne plus les lire comme
> « conformité totale ».** La grille est passée à **72 critères le 2026-07-31** : elle ne mesurait
> que F1–F5 (dont 25 critères pour la seule F5) et était **aveugle** au contrat backend, au reclaim
> VRAM, au tirage, aux capacités canoniques, aux prompts, aux permissions et au nœud studio. Un
> « 40/40 » de l'époque vaut aujourd'hui ~85 % (converter mesuré 86 % au 2026-07-31, sur 60 critères
> applicables). **Source vivante : `logs/conformity_report.json` (`/apps/`), jamais ces lignes.**

**Photo MESURÉE au 2026-07-31** (grille 72 critères, dénominateur variable — un critère non
applicable sort du calcul) :

| app | score | app | score |
|---|---|---|---|
| enhancer | **89 %** (60/67) | describer | 79 % (53/67) |
| converter | **86 %** (52/60) | anonymizer | 60 % (42/72) |
| transcriber | **85 %** (57/68) | imager | 56 % (39/72) |
| composer | 84 % (60/72) | avatarizer | 65 % (42/67) |
| synthesizer | 82 % (58/70) | reader | 80 % (55/68) |

**Restent à porter (5)** — ordre recommandé :
1. ~~**Reader**~~ ✅ porté (4e app — 33/40 mesuré au 2026-07-26, écarts résiduels au rapport ;
   **80 % sur la grille à 72 au 2026-07-31**, après bascule sur `select_model`) ;
2. ~~**Converter**~~ ✅ **PORTÉ À 100 % MESURÉ (40/40) — 2026-07-26, 1re app à conformité
   totale** : 14 écarts comblés en une session (triade tool_api, console, Help/About, gabarit
   batch, WAMA_INGEST+`source_url` (migration 0006 ×2 bases), slot médiathèque, footer modale
   commun ×2, model-help via `help_fallback` (36 formats depuis SUPPORTED_CONVERSIONS),
   `card_html`+`refreshCard` (updateCard client SUPPRIMÉE), briques `_card_state`/`_card_progress`,
   réconc. orphelins, duplication brique, user_settings (dernier format/type), manipulation
   directe via **NOUVELLE brique `make_queue_manipulation_views_direct`** (variante FK-directe
   sans modèle de liaison — jamais de delete d'un batch peuplé, CASCADE). Fix regex
   `duplicate_wiring` du checker (faux DOUBLE-FIRE sur `.batch-duplicate-btn`).
   ⚠ Validation NAVIGATEUR à faire (/smoke : dépôt, conversion, transitions de card, modales).
3. ~~**Enhancer**~~ ✅ **PORTÉ À 100 % MESURÉ (40/40) — 2026-07-26, 2e app à conformité totale,
   1er port BI-DOMAINE** (média image/vidéo + audio) : 19 écarts, monolithe index.html 918→~540 l.
   (cards d'entrée communes ×2 déplacées du volet droit — mêmes ids, bindings JS intacts ; barre
   batch audio préservée via `extra_zone_template` ; toolbars + build_batches_list + `_batch_card`
   ×2 ; cards = partials serveur ×2 + refreshCard — l'ancien double-markup JS avait un désaccord
   de classes qui cassait DÉJÀ la progression des cards serveur ; WAMA_INGEST ×2 — un batch
   d'URLs était voué à FAILURE ; anti-race réel comblé sur `audio_batch_start` ; footer modale
   commun via gabarits `<template>` clonés — brique généralisée save_class/save_start_class ;
   vrai double-fire duplicate supprimé ; 8 alert()→toast). Briques généralisées au passage :
   `_batch_card` (collapse_prefix/show_settings), `_settings_modal_footer` (classes+labels).
   ⚠ Validation NAVIGATEUR à faire (2 domaines : dépôt, batch, transitions, modales, bascule).
   **Anonymizer** (généraliste classique) ;
4. ~~**Synthesizer**~~ ✅ **PORTÉ À 100 % MESURÉ (40/40) — 2026-07-26, 3e app, 1er PROMPT-FIRST
   sur la card d'entrée commune** (état replié = champ texte ; l'app consomme enfin la brique
   extraite d'elle-même en 07/2026). Volet compose PRÉSERVÉ (variante déclarée) ; modale item
   GÉNÉRÉE (WamaParams, options clonées du volet) ; WamaBatchImport remplace ~200 l. de chaîne
   batch locale (server_path préservé en direct confirmé) ; WAMA_INGEST → voice_reference
   (migration 0014 ×2) ; double-fire duplication corrigé ; user_settings alimente enfin
   preferred_language. **VALIDÉ NAVIGATEUR** (Playwright : replié/déplié, voix clonées ×34,
   soumission réelle, modale 8 champs, 0 erreur console). Cards d'entrée REPLIÉES aussi
   activées sur converter/enhancer/reader (fichier-first, même session).
4. **Synthesizer** (PRÉREQUIS : séparer le volet droit = surface de composition ; son accordéon
   est déjà globalisé en `collapsible`, sa `_synthesis_card.html` existe) ;
5. **Imager** (le + de modes — app de référence du build complet, à faire en dernier des
   généralistes) ; **Avatarizer** (standalone-only après studio, cf. R16).

**Briques inter-apps à créer au fil des ports** : `_batch_card.html` (card mère commune — les
headers transcriber/composer sont chacun faux à leur façon ; describer a déjà adopté le squelette
`.is-batch`) ; `batch_common.py` (`_wrap_*_in_batch`/auto-wrap ×3 apps) ; `build_batches_list()`
commun ; toast commun ; maps badge/couleur ; helper modale-batch ; `restart_instance()`.

**✅ VALIDÉ NAVIGATEUR 2026-07-26 (session Playwright, user de test `pw_smoke` avec données)** :
**Converter** (card d'entrée complète dépôt/URL/médiathèque/gabarit, toolbar, cards ordre canonique
⚙▶⬇⧉🗑, batch déplié 2 filles, modale ⚙ ouverte/fermée avec footer commun + 12 champs, FileManager
jstree chargé) ; **Enhancer** (2 domaines : cards d'entrée en tête, 2 toolbars, cards + cycle +
progress brique, modale JS avec footer commun cloné, aide moteur volet+modale, FM chargé) ;
**Reader** partiel (page + card + toolbar + FM OK ; modale ⚙ non testée — sélecteur à identifier).
Au passage : bug BLOQUANT corrigé (commentaire {# #} multi-ligne contenant `<template>` rendu tel
quel → il avalait tous les scripts des pages incluant `_settings_modal_footer` — cf. commit
fix(common) 2026-07-26) + `wama-model-help` tolère les help_fallback objets.

**Validations navigateur EN ATTENTE (à faire en début de session)** : Composer (ETA cards,
batch 3 syntaxes + aperçu, template téléchargeable, card dépliable) ; Transcriber (cards ×2
contextes, contrat de sortie sur brouillons, échec → card re-rendue) ; Describer (upload/URL
depuis la card d'entrée, solitaire batch, **boutons actifs après re-rendu** = re-bind) ; menu +
accueil + /apps/ groupés + couleurs + liseré. Migration `describer 0008` appliquée (la page
était cassée avant — colonne manquante).

---

### AUDIT EMPIRIQUE 2026-07-06 (3 agents + contre-vérifications) — restes pour 100 %

| App | Score | Restes bloquants |
|---|---|---|
| **Transcriber** | ~90 % | ① start/start_all/batch_start SANS anti-race `select_for_update` (pattern CLAUDE.md — vérifié : 0 occurrence ; **describer seul l'a**, views.py:519) ; ② `stop()` sans `@require_POST` ; ③ bouton cycle inline `_transcript_card.html:87-91` au lieu de `_cycle_button.html` ; ④ card mère batch hand-made (A2-6) ; ⑤ sync card↔inspecteur manuelle 9 data-* + `_renderBatchActions` en chaînes JS (A3-12/13, vérifié index.js:1139) ; ⑥ `showToast`=alert (A6-26, vérifié index.js:104) ; ⑦ dropdown formats dupliqué partial+JS (A2-7 résiduel) ; ⑧ extractions de vue A5 : `_describe_audio`→media_probe, `_wrap_transcript_in_batch`/`_auto_wrap_orphans`→batch_common, agrégats→`build_batches_list`, prefs cache artisanales, SRT ×3, `clear_all` `.delete()` direct sans `safe_delete_file` ; ⑨ styles modales info/résultat (A4-15/16) |
| **Describer** | ~90 % | ① classe `.synthesis-card` (11× JS + 3× HTML) au lieu du contrat `.wama-card` ; ② **`wama-app-base.js` NON chargé** (seul des 3 — polling/CSRF locaux) ; ③ manipulation directe partielle : `consolidate` seul (pas de reorder/move_to_batch/remove_from_batch) ; ④ réglages user non persistés. Le reste est au niveau (card_html+refreshCard avec re-bind, anti-race, ETA seedée, exports late TXT/PDF/DOCX, toolbar) |
| **Composer** | ~75 % | ① manipulation directe ABSENTE (0/4 endpoints, brique `consolidate_into_batch` non consommée) ; ② anti-race absent ; ③ descriptions modèles hardcodées `COMPOSER_MODELS` (model_config.py:34-101) au lieu du catalogue `AIModel` (points 9/10 checklist) ; ④ card mère batch = bandeau violet minimal sans ▶/compteurs/barre agrégée (B3-8) ; ⑤ styles inline `_generation_card.html` (B2-7) ; ⑥ 2 impls modale-batch à fusionner (A6-28) ; ⑦ réglages user via localStorage seul |

**Transverses (débloquent les 3 à la fois — à créer PENDANT le port de Reader)** :
`_batch_card.html` commune (toujours absente — vérifié) · wrappers `_wrap_*_in_batch`/
`_auto_wrap_orphans` → `batch_common.py` (existe déjà : `consolidate_into_batch`,
`group_into_batches_by_nature`) · `build_batches_list()` · `WamaApp.toast` (rien dans
wama-app-base.js — vérifié) · maps badge/couleur · `restart_instance()` anti-race ·
helper modale-batch · partial `_download_formats_dropdown.html`.

**Corrections de doc actées 2026-07-06** : le point 16 de la checklist (`tool_api.py`) se vérifie
dans le REGISTRE CENTRAL `wama/tool_api.py` (TOOL_REGISTRY — transcriber/composer/describer y sont
tous trois), PAS par fichier d'app ; backups `{% comment %}` transcriber purgés (A4-14 clos) ;
`wama-app-base.js` adopté par composer et reader (B4-10 partiellement résorbé — URLs en dur à
re-vérifier au prochain passage).

**PROCHAINE APP : READER** (décision 2026-07-06, confirme l'ordre du 07-05 ; ✅ porté depuis,
cf. §31.7 ; remplaçait le « prochaine bascule = enhancer » de `docs/archive/GENERALIZATION_PLAN.md`) — jumeau de describer, charge déjà
`wama-app-base.js`, recette éprouvée 3× → port le moins cher ; créer les briques transverses
ci-dessus pendant ce port (4 consommateurs immédiats).

---

### PORT À 100 % EFFECTUÉ — session 2026-07-06 soir (Fabien : « terminer les 3 apps, puis Reader »)

**Briques CRÉÉES (common/)** : `utils/media_probe.py` (sonde ffprobe + format_duration) ·
`utils/user_settings.py` (réglages user par app, clés `user_{id}_{app}_{clé}`, TTL 30 j) ·
`utils/queue_manipulation.py` (FABRIQUE des 4 vues manipulation directe) ·
`templates/common/_batch_card.html` (card MÈRE de batch, slots meta/download_menu/download_url/
eta_ids/show_start, boutons canoniques `.batch-*-btn`) · dans `batch_common.py` :
`wrap_in_batch`/`auto_wrap_orphans`/`build_batches_list` · dans `process_control.py` :
`begin_processing` (anti-race CLAUDE.md) + **réconciliation des RUNNING orphelins** (2026-07-24/25 :
`collect_worker_snapshot`/`is_task_orphaned`/`reconcile_orphaned_running`, 93329c4 puis 32df89c =
bascule en échec sur **preuve positive de mort** seulement ; adopté par transcriber IndexView) · dans `wama-app-base.js` : `WamaApp.toast` +
`STATUS_BADGE/LABEL` (monté GLOBAL dans base.html) · `_cycle_button.html` : overrides
`restart_title`/`restart_icon` + `data-cycle-restart-*` lus par wama-cycle-button.js.

**Consommation** — Transcriber : anti-race ×3 + reset unifié, stop POST, cycle→brique (spécificité
temps réel déclarée sur la card), toast (11 alert() purgés), clear_all sûr, media_probe,
user_settings (2 routes mortes supprimées, défaut préprocessing unifié OFF), batch_template brique,
manipulation directe DÉLÉGUÉE à la fabrique, card mère → brique (+ slots `_batch_meta.html`,
`_batch_download_menu.html`). Describer : `.wama-card` (JS ×11), manipulation directe 3 vues
câblées (consolidate par nature conservé), réglages persistés (`_read_creation_options`, 4 lectures
POST unifiées), card mère → brique (**gagne ▶ batch** + handler JS), agrégats → brique, toast.
Composer : anti-race ×4, wrappers+agrégats → brique, manipulation directe 4/4 câblée (routes),
card mère → brique (**gagne ▶ batch + compteurs + barre agrégée** ; id collapse aligné
`batchItems<id>`), styles inline → index.css, toast → brique, `batchStartUrlTemplate` posé.
Vérifié AU PASSAGE : descriptions modèles composer = déjà catalogue (wama-model-help →
`/model-manager/api/models/db/`) — le ⚠ points 9/10 de l'audit matin était trop sévère ;
`COMPOSER_MODELS` résiduel = facteurs slider (légitime §D, cible eta_estimator).

**Validations faites** : `manage.py check` OK (WSL venv) · imports views/urls ×3 OK ·
10 templates compilés OK · équilibre délimiteurs JS ×5 OK · staticfiles copiés (6 fichiers).
**⚠ RESTE À VALIDER NAVIGATEUR** (je ne peux pas) : cards mères ×3 (rendu + dépliage + ▶/ZIP/⧉/🗑),
bouton cycle transcriber (états ▶/⏹/↻ + temps réel ↻ fa-rotate), toasts, manipulation directe.
**Restes consignés (non bloquants checklist)** : A3-12/13 (chaînes JS inspecteur → TÂCHE 1),
A4-15/16 (styles modales transcriber), A5-24 (SRT ×3), A6-28 (fusion modale-batch JS),
A1-4 (afterCreate batch-import), B4-10 résiduel (URLs composer), B4-13 (ETA client→serveur),
B5-20 (export médiathèque). Restart process WSL2 requis pour le Python.

**AUDIT ROUTE COMMUNE (même jour, après commit du port)** →
**[`docs/archive/AUDIT_ROUTE_COMMUNE_2026-07-06.md`](docs/archive/AUDIT_ROUTE_COMMUNE_2026-07-06.md)**
(archivé 2026-07-23, absorbé par `WAMA_APP_GENERATION_ROUTE.md`) : (1) common SAIN,
1 doublon critique ffmpeg/ffprobe **corrigé** (video_utils + waveform + converter probe → délèguent
à ffmpeg_utils, la sélection WSL2-vs-Windows redevient unique) ; describer basculé sur
`begin_processing` (son inline promu brique) ; (2) les 7 généralistes : wrappers batch locaux ×7,
0 manipulation directe, anti-race inline reader/converter seulement + features à remonter (profils
converter, TTS synthesizer, A/B enhancer, presets anonymizer, seeds/galerie imager) ; (3) route
manifeste→app ~70-80 % déclarative, chantiers ordonnés (ports → contrat URLs → enum statuts →
check_app_conformity exécutable → introspection Django→schéma → scaffold EN DERNIER).

---

## 21. Inspecteur contextuel + état des 4 apps portées (2026-07-08) — CLÔTURE DE SESSION

> Session dédiée à l'**inspecteur contextuel** (mode avancé) + audit des 4 apps portées.
> Reprise = **porter Converter** puis **combler les trous** listés ci-dessous. Ordre fixé Fabien :
> **inspecteur d'abord, amincir les cards ENSUITE** (l'inspecteur porte le détail → justifie de
> maigrir les cards). Docs de référence figés : [`INSPECTOR_DETAIL_FIELDS.md`](INSPECTOR_DETAIL_FIELDS.md),
> [`WAMA_APP_GENERATION_ROUTE.md`](WAMA_APP_GENERATION_ROUTE.md) (cartographie + registre briques +
> **discipline anti-réinvention** ; ex-COMMON_REFACTORING archivé `docs/archive/`),
> `CARD_DESIGN §10` (card v2), mémoire `project_inspector_contextual_vision.md`.

### 21.1 Ce qui a été construit (commun, porté aux 4 apps)

- **Aperçu inline** dans le volet (`WamaInspector` → `#preview-container`) : image / vidéo / audio
  (WamaAudioPlayer) / PDF / **HTML (iframe sandboxée)** / **texte (contenu inline)** — tout sauf zip.
  Source = `unified_preview` + `preview_registry`. **Autoplay = préférence profil** (`UserProfile.
  inspector_autoplay`, défaut OFF, toggle page profil, global `WAMA_INSPECTOR_AUTOPLAY`). Jamais de
  génération : on affiche l'existant. Section « Médias » **masquée hors ITEM**.
- **Section Infos = CHIPS** (pas la liste KV de WamaDetails, écartée) : identité (#id + badge statut +
  date + ✕ désélection) + fichier source + chips étiquetées (durée, moteur, format, propriétés à
  **icône adaptative** par type, réglages `extra` tirés de `params.py`). Source = **`unified_detail`
  + `detail_registry` + `build_detail`** (schéma canonique figé `INSPECTOR_DETAIL_FIELDS.md`). Statut
  normalisé à l'affichage (DONE→SUCCESS).
- **Agrégats file / batch** dans l'inspecteur, **LUS des sources serveur** (pas de recompte client) :
  file ← `window.WamaQueueStats` (posé par `wama-global-progress.js`, refresh live sur
  `media:processed`) ; batch ← `data-batch-*` de `_batch_card.html` (depuis `build_batches_list`).
- **Temps de traitement réel persisté** : `common/models.py::ProcessingTimeMixin` (les 4 modèles
  héritent), workers persistent `processing_seconds` (déjà mesuré pour l'ETA), affiché via
  `_processing_time.html` (foyer unique, inclus par `_card_progress`).
- **Card v2 synthétique** (chips depuis `params.py chip=True`, point d'état tricolore, barre pleine
  largeur) : **PILOTE Reader uniquement**.

### 21.2 Table de conformité (✅ / 🔶 / ❌)

| Axe | Transcriber | Describer | Composer | Reader |
|---|---|---|---|---|
| Preview (registry + data-preview-url) | ✅ | ✅ | ✅ | ✅ |
| Detail (registry + adapter build_detail) | ✅ | ✅ | ✅ | ✅ |
| cardSelector spécifique | ✅ `.synthesis-card` | 🔶 `.wama-card` (trop générique) | ✅ `.generation-card` | ✅ `.reader-card` |
| Inspecteur `initFromSchema` | 🔶 `.init()` (legacy) | ✅ | ✅ | ✅ |
| `cloneActions` | ✅ | ✅ | ✅ | ✅ |
| Card v2 (chips) | ❌ | ❌ | ❌ | ✅ (pilote) |
| `_batch_card.html` commun | ✅ | ✅ | ✅ | ✅ |
| Briques communes (batch/process/queue/user_settings) | ✅ | ✅ | ✅ | ✅ |
| `ProcessingTimeMixin` + persistance | ✅ | ✅ | ✅ | ✅ |
| Affichage temps | ✅ `_card_progress` | ✅ `_processing_time` | ✅ `_processing_time` | ✅ `_processing_time` |
| Statuts SUCCESS/FAILURE | ✅ | ✅ | ✅ | 🔶 DONE/ERROR (normalisé à l'affichage) |
| Page d'édition dédiée (spécifique légitime) | ✅ correction manuelle | — | — | — |

### 21.3 Trous de portage à combler (reprise) — priorisés

1. ✅ 2026-07-08 **Describer `cardSelector`** — vérifié empiriquement DÉJÀ à `.synthesis-card`
   (`describer/index.html:315`) ; l'entrée était en retard sur le code. Le `.wama-card` restant
   (`index.js:20`) est le `autoSync` du cycle-button, sans effet de bord (header batch sans bouton).
2. ✅ 2026-07-08 **Reader statuts alignés en BASE** : `DONE/ERROR` → `SUCCESS/FAILURE`
   (migration `reader.0008` choices + data, sweep models/views/tasks/JS/template — les clés JSON
   `done/error` de `global_progress` inchangées, brique commune tolérante). Converter garde
   DONE/ERROR (normalisé affichage) — à aligner à son tour si souhaité.
3. ✅ 2026-07-08 **Transcriber migré `initFromSchema`** : `_panelApplyValues`/`_cardSettings`
   supprimés (dérivés du schéma) ; `_panelReadValues` CONSERVÉ (payloads serveur typés).
   Prérequis posés : `window.WAMA_TRANSCRIBER_SCHEMA` (template), support **`radio_name`** ajouté
   aux read/apply dérivés de `wama-inspector.js` (radios legacy ex. `globalSummaryType`), `data-*`
   des cards alignés sur les noms du schéma (`data-preprocess-audio`, `data-enable-diarization`).
4. 🟠 **Transcriber `_card_progress.html`** vs `_processing_time.html` custom des 3 autres → une seule
   approche d'affichage de progression/temps. (À traiter AVEC le rollout card v2, point 5.)
5. 🟡 **Propager la card v2 (chips)** aux 3 autres apps : `chip=True` sur leurs params + `.chips`
   property (modèle reader) + include `_card_chips.html`. (Après validation navigateur du pilote.)
6. ✅ 2026-07-08 **Mini-card « Réglages de l'élément #N » RETIRÉE** des 5 apps portées au détail
   (transcriber/describer/composer/reader/converter) ; le ✕ des Infos appelle `deselect` en direct
   (plus de proxy par le bouton du bandeau). `_inspector_banner.html` reste pour les non-portées
   (synthesizer, avatarizer).
7. ✅ 2026-07-09 **`probe_media`** généralisé (`media_probe.py` : image/vidéo/audio/PDF/archive)
   + **fallback UNIVERSEL dans `build_detail`** (`probe_media_cached`, cache par chemin+mtime) →
   `source_properties`/durée/icône remplis partout sans travail par app. Testé sur fichiers réels
   + `unified_detail` converter (vidéo : `mjpeg • 384×288 • 15.0 img/s`, durée 0:27).

### 21.4 Au-delà — état 2026-07-08

- ✅ **CONVERTER PORTÉ (5e app)** : adapters preview+detail (`apps.py`, extra ← labels `params.py`,
  `output_quality`←`quality_preset`), `ProcessingTimeMixin` + persistance worker + affichage
  (`_processing_time.html` + live via `status` JSON), `data-preview-url` racine card,
  `initFromSchema` (schéma modale ; volet = zone de composition, aucun param contexte 'panel' →
  synchro dérivée neutre), `cloneActions` item+batch, **card mère commune `_batch_card.html`**
  (contrat calculé dans la vue — FK directe, pas de modèle de liaison ; `data-media-type` sur le
  wrapper `.batch-group`, conteneur `#batchItems<id>` + `data-wama-batch-key`). Smoke réel : page
  200 + endpoints unifiés OK (données de test nettoyées).
- ⚠️ **Migrations en retard découvertes et appliquées** (2026-07-08) : `describer.0009` /
  `composer.0005` / `reader.0007` (`processing_seconds`) n'avaient JAMAIS été appliquées à la base
  partagée → `manage.py migrate` global fait (incl. accounts.0009, model_manager.0008,
  cam_analyzer.0013). Toujours vérifier `migrate` après un palier.
- **5 apps non portées** : enhancer, anonymizer, synthesizer, imager, avatarizer. Chacune : adapter
  `register_app_preview` + `register_app_detail` + câblage inspecteur.
- **Amincissement des cards** (le but du report d'infos vers l'inspecteur) : APRÈS l'inspecteur.
- Validation NAVIGATEUR par Fabien toujours attendue : pilote card v2 Reader + inspecteur des 5
  apps portées (smoke serveur fait, pas de clic réel).

## 21bis. Composer — ÉTAT RÉEL VÉRIFIÉ (2026-07-21) : structure ≠ comportement

> Vérifié en profondeur (lecture code + 3 explorations croisées) sur signalement Fabien que le
> « 96 %/audit » surestime. **Cause de l'écart** : `get_conformity_summary` et l'audit UI mesurent
> la STRUCTURE (« appelle-t-il `WamaParams.render` ? une preview est-elle enregistrée ? »), PAS le
> COMPORTEMENT (« la sauvegarde persiste-t-elle ? les actions apparaissent-elles ? »). D'où une app
> structurellement ~90 % mais fonctionnellement cassée sur la modale. **→ ajouter une dimension
> conformité COMPORTEMENTALE (smoke) est recommandé.**
>
> **AVANCEMENT 2026-07-21** (validé navigateur Fabien au fil de l'eau) : ✅ **pt1** ordre de rendu
> (sauvegarde modale débloquée) · ✅ **pt5** brique `coerce_params` + câblage · ✅ **bug affichage**
> (card re-rendue après save → modale+inspecteur affichent les valeurs enregistrées, pas les défauts ;
> `insertRenderedCard` après chaque save) · ✅ **pt3** actions héritées par le volet
> (`renderItemActions`/`renderBatchActions` + `.btn-group-actions` sur la card ; clics fonctionnels,
> lien médiathèque inclus) · ✅ **pt6** `hideOnInspect` (saveGlobal/titres = N/A composer). **Reste** :
> ✅ **pt2 FINALISÉ 2026-07-21** : sauvegarde modale = **100% `WamaParams.read`** (aucun hand-read).
> **Chaîne output_format/output_quality VÉRIFIÉE end-to-end, saine, zéro hardcoding** (trace Fabien) :
> options ← `output_format_params_for_app` → `get_output_formats` → **`CONVERTER_OUTPUT_FORMATS`**
> (source unique converter) ; presets qualité = `OUTPUT_QUALITY_CHOICES` (web/équilibré/max) ; ces 2
> Param SONT dans le schéma composer (confirmé live : `['model','duration','prompt','output_format',
> 'output_quality']`) → `read` les capte ; application réelle = `composer/tasks.py` appelle
> `apply_inline_conversion` (converter). **Apps branchées early-binding : composer + synthesizer** ;
> late-binding = conversion au download (`multi_format_download`). (Ma gestion explicite initiale
> était redondante/fausse → corrigée.)
> **pt4 preview = CHANTIER PREVIEW COMMUN (tunnel : moi=briques preview, autre instance=manifeste+
> ingest ; on se rejoint sur les ports).** CONTRAT DE JONCTION : la preview lit les ports par
> **l'UNIQUE accesseur `studio_node_ports(app_id)`** (jamais app_modes/app_registry en direct) —
> `extract_app()` du manifeste utilise déjà le même → quand le manifeste devient autoritaire,
> `studio_node_ports` = sa projection, la preview hérite sans changer. Le « pendant » = **capacité
> déclarée** (`body.capabilities`, ex. `during_preview`/`streaming`) : moi le mécanisme, eux le flag.
> Cycle avant/pendant/après (comme ▶/⏹/↻). État :
> - ✅ **Chantier 1 (2026-07-21) — face ENTRÉE dérivée du port travail/prompt, jamais reference**
>   (`preview_utils._input_preview` via `studio_node_ports` ; prompt→texte inline `content`,
>   travail→adaptateur fichier ; frontend rend `content` inline). Corrige composer GÉNÉRIQUEMENT
>   (0 hardcode). Vérifié live : composer/synthesizer=prompt, transcriber/imager=travail ; endpoint
>   composer entrée=prompt(text/plain), sortie=audio, toggle OK.
> - 🔄 **Chantier 2 — phase PENDANT** : ✅ **socle backend (2026-07-21)** — accesseur capacités unique
>   `app_capabilities`/`app_supports_during_preview` (`app_registry.py`, analogue `studio_node_ports` ;
>   lit `during_preview`/`streaming` des conventions APP_CATALOG, déjà projetées par le manifeste
>   `builtin/app.py:188`) + mécanisme `publish_partial`/`clear_partial`/`_during_preview_data` +
>   `unified_preview` `?side=during` + `sides.during_capable`/`has_during`. Vérifié dormant (composer
>   sans flag → fallback entrée) ET activé (partiel publié → servi). **Reste** : (a) **frontend** —
>   volet poll `?side=during` pendant RUNNING si `during_capable`, rend le partiel qui se construit ;
>   (b) **worker composer (2b)** — MusicGen streaming décode partiel → `publish_partial` (needs GPU +
>   restart WSL2 pour valider) ; (c) **flag** `during_preview` sur composer dans les conventions =
>   rôle « déclaration » de l'instance manifeste (moi=mécanisme). Tant que (c) absent, le socle est
>   dormant (sûr).
>   **RÉUTILISATION correction Transcriber (2026-07-21, centralisé common/)** : (i) `wama-audio-player.js`
>   gère déjà les longs fichiers (repli timeline si décode échoue) → réutilisé tel quel pour l'audio
>   partiel ; (ii) pattern overlay 5ter (calque temps-mappé découplé) → modèle du calque de progression
>   streaming ; (iii) **« waveform par parties » que transcriber avait CONÇU mais reporté → FAIT et
>   centralisé** : `common/utils/waveform.py::compute_peaks` (downsample serveur fichier/PCM→pics [0..1],
>   jamais d'exception) + `publish_partial_peaks` + `WamaAudioPlayer.setPeaks` (additif : dessine l'onde
>   depuis pics serveur, débloque longs fichiers ET onde-qui-se-construit). Vérifié (array/fichier/
>   dormant/activé). **Reste frontend** : le volet appelle `setPeaks` au poll `?side=during` pendant RUNNING.
>   **UNIFICATION waveform (2026-07-21, recadrage Fabien « pas 2 mécanismes concurrents »)** :
>   `common/utils/waveform.compute_peaks` = SOURCE UNIQUE paramétrable (backend ffmpeg/soundfile/array,
>   résolution densité(bps)/N, dtype uint8/float, with_duration). **Reproduit à l'octet l'algo
>   historique transcriber** (vérifié : 1341 pics, dur 26.838, mêmes valeurs). `transcriber/utils/
>   waveform.compute_peaks` **délègue** désormais à common (cache/worker/endpoint/renderer zoomable
>   INCHANGÉS — non-régression vérifiée, django check OK). Transport CANONIQUE = **uint8** ;
>   `setPeaks` normalise uint8→0-1 (fin de l'incompat 255 vs 1). **Renderer zoomable de l'éditeur =
>   coexistence LÉGITIME** (correction = zoom/pan/heatmap ≠ aperçu fixe). Futur (non fait) : fusionner
>   les 2 renderers en 1 composant commun à 2 modes (aperçu / zoom-éditeur) — gros refactor, plus tard.
>   **FRONTEND + WORKER (2026-07-21)** : ✅ inspecteur COMMUN poll `?side=during` pendant RUNNING si
>   `during_capable`, rend le partiel (`setPeaks`), auto-arrêt → face SORTIE ; `renderInlinePreview`
>   dessine `data.peaks`. **Bug chantier 1 corrigé au passage** : `_fetchPreviewSide` exigeait `d.url`
>   → le prompt en entrée (content, sans url) ne s'affichait pas ; garde relâché (url|content|peaks).
>   ✅ helper commun `emit_streaming_peaks(app,pk,pcm,sr)` ; ✅ hook `on_audio` best-effort dans
>   `audiocraft_backend` + `emit_streaming_peaks`/`clear_partial` dans `composer/tasks.py` (émet
>   l'audio FINAL ; streaming mid-génération = token-callback MusicGen = **dev GPU**, même point).
>   **Chaîne complète, dormante** tant que composer ne déclare pas `during_preview` (rôle manifeste).
>   **UNIFORMISATION PREVIEW 7 apps (2026-07-21, audit)** : ✅ toggle Entrée/Comparer/Sortie
>   (ordre chronologique + pleine largeur `flex-fill`) ; ✅ plein écran au **double-clic** (réutilise
>   `WamaMediaPreview.showPreviewModal`) + icône overlay ; ✅ **toggle réparé sur 5 apps** via 2
>   corrections COMMUNES (0 patch par app, vérifié live 5/5) : (1) `_output_preview_data` repli sur
>   `result_text` inline (transcriber/describer/reader = sortie texte → face Sortie existe) ; (2)
>   `_input_preview` résout le texte par champs candidats prompt/text_content/text (synthesizer).
>   Images/vidéos/docs déjà gérés par `renderInlinePreview`. **TODO** : clé canonique `source_text`
>   (detail, symétrique `result_text`) → supprimer la liste de champs ; `describer.result_file`
>   FileField orphelin à nettoyer ; flag `during_preview` composer (rôle manifeste) ; streaming
>   MusicGen mid-génération (dev GPU, hook `on_audio` prêt).
>   **CLÔTURE (2026-07-21)** : ✅ flag `during_preview=True` sur composer (conventions `_conv` +
>   champs `during_preview`/`streaming` additifs) → chaîne « pendant » ACTIVE (plus dormante).
>   ✅ **toggle Entrée/Comparer/Sortie DANS le plein écran** (media-preview.js `_renderModalSides`/
>   `_modalCompare`, réutilise `?side=X`+`buildPreviewContent` ; inspecteur transmet `_baseUrl`+`sides`
>   au double-clic). ✅ **source_text canonique** (`build_detail`+`_input_preview`) → retire le hardcode
>   de champs (repli transitoire conservé, 5/5 toggles OK). **RESTE** : streaming MusicGen mid-génération
>   (dev GPU, hook `on_audio` prêt) ; `describer.result_file` orphelin = migration différée (dual-DB,
>   risque) — fonctionnellement neutralisé (repli `result_text`).
>   ✅ **source_text DÉCLARÉE** (2026-07-22) par composer (=prompt) et synthesizer (=text_content) →
>   **repli candidat SUPPRIMÉ** de `_input_preview` (zéro nom de champ en dur). imager N/A (port travail).
>   ⚠️ **onglets description/résumé/cohérence DUPLIQUÉS** describer+transcriber (HTML inline ×2 + JS ×2,
>   AUCUN commun) → cible : extraire `common/_result_tabs.html`+JS. Ils utilisent `result_text`/`summary`,
>   PAS `result_file`. ⚠️ **`describer.result_file` retrait DIFFÉRÉ (passe ISOLÉE)** : ~15 sites
>   `views.py` + `output_filename` + migration DUAL-DB, zone fragile — hors concurrence d'instances.
> - ⏳ **Chantier 3 — unifier le filemanager** sur `media-preview.js` commun (il a sa propre modale).
> **Streaming preview « à la Suno »** (sortie audio construite pendant le process) = faisable
> (MusicGen autorégressif + callback), à faire en **capacité commune déclarée par métadonnée**, APRÈS
> pt4 de base — pas en dur dans composer. **Reste** : pt4 (preview entrée/sortie — **design corrigé
> Fabien** : entrée = **le PROMPT utilisateur** = entrée principale ; la mélodie de réf = fichier de
> référence secondaire, PAS l'entrée ; sortie = audio généré ; adaptateur `apps.py` à corriger, il
> pointe 2× sur `audio_output`), pt7 (includes card `_card_state`/`_card_progress`),
> pt8 (ETA `data-*`→catalogue), pt9 (bouton médiathèque = action commune par capacité de sortie).
>
> **Route commune = existante et unique** (ne rien réinventer) : `WamaParams` (render+read/apply,
> modale+volet+batch), `WamaInspector.initFromSchema({renderItemActions,renderBatchActions,...})`,
> preview `unified_preview`/`preview_utils.py` (`?side=output` + toggle [Entrée|Sortie], décision
> 2026-07-12). **Transcriber = référence conforme ; Composer demi-porté.**
>
> **Reste à porter (vérifié, ordonné) :**
> 1. **Bug bloquant modale = ORDRE DE RENDU.** `index.js` (IIFE nue, sans DOMContentLoaded) est
>    chargé `composer/index.html:242` AVANT le bloc `WamaParams.render` (index.html:276-322) qui
>    crée `modelSelect`/`durationSlider`/`settingsModel`/`settingsDuration` → consts nulles
>    (index.js:43/44/103/106) → `_postSettings` (index.js:380/381/394/395) lève TypeError au clic
>    « Enregistrer »/« Enregistrer et relancer ». **Fix = pattern Transcriber : rendre WamaParams
>    AVANT `<script index.js>`** (transcriber index.html:107-129 avant 131). Le volet (`postPanel`,
>    getElementById au POST) marche déjà → d'où DEUX chemins concurrents (volet OK / modale cassée).
> 2. **Supprimer le 2ᵉ chemin** : `_postSettings` → lire via `WamaParams.read` (ou getElementById
>    au POST) comme le volet.
> 3. **Actions héritées par le volet** : passer `renderItemActions`/`renderBatchActions` à
>    `initFromSchema` (absents index.html:263-273 ; présents transcriber index.js:1175-1176) **ET**
>    donner à la card le conteneur clonable `.btn-group-actions` (elle a `.d-flex flex-wrap gap-1`,
>    `_generation_card.html:80` ; `cloneActions` clone `.btn-group-actions`, wama-inspector.js:44).
> 4. **Preview Entrée/Sortie** : aujourd'hui input ET output pointent sur `audio_output`
>    (apps.py:30 & 44) → le toggle montrerait 2× le même fichier. Input = mélodie de référence si
>    présente (sinon pas de side entrée) ; le prompt reste l'« entrée » textuelle.
> 5. **Borne de durée = DUPLICATION 7× (dette architecturale, PAS un petit réglage — corrigé
>    2026-07-21).** La borne 10-600 s est copiée à la main dans : champ modèle (help_text seul, AUCUN
>    validateur `models.py:27`), `params.py` (slider min/max), et **5 clamps `max(10,min(600))`**
>    (views.py ×4 + batch_parser) ; elle a déjà dérivé (migrations : max30→10-300→10-600) et
>    contredit `max_duration:30` (model_config). **Source unique = le mécanisme commun
>    `derive_from_model` (`common/utils/param_schema.py`)** — dériver le schéma DU modèle Django,
>    déjà adopté par anonymizer/avatarizer/describer/imager ; **Composer ne l'utilise pas**.
>    Cible : borne définie 1× (validateurs sur le champ modèle → Django valide serveur + derive lit),
>    clamps serveur LISENT le schéma (petit helper commun), effective_max = min(borne, model.max_duration).
>    ✅ **FAIT 2026-07-21** : trou confirmé SYSTÉMIQUE (audit : ~28 clamps hardcodés sur 8 apps,
>    même celles qui dérivent ; aucune brique n'existait). Créé `common/utils/param_schema.py::
>    coerce_params(schema, data, caps=)` = borne LUE du schéma (source unique) + cap runtime optionnel.
>    Composer = 1er consommateur : helper `clamp_duration` + 5 clamps remplacés + cap `max_duration`
>    au lancement de tâche (auto-* résolu). Validé live (305→305, 999→600, 999+musicgen→30). **Reste** :
>    (a) valider navigateur (305s demandé → 30s généré = cap modèle ; si trop bas, `max_duration` de
>    model_config = désormais LA source à corriger 1×) ; (b) généraliser aux ~23 autres sites ;
>    (c) plus tard, porter la borne dans le modèle Django (validateurs → derive_from_model les lit),
>    décidé avec Fabien : « on aligne sur l'existant, puis modèle Django par la suite ».
> 6. **Compléter `initFromSchema`** : `saveGlobal`, `hideOnInspect`, `settingsTitleSelector/Inspect`.
> 7. **(Card, optionnel)** remplacer badge statut + barre écrits à la main (`_generation_card.html:
>    51-65`) par includes communs `_card_state.html`/`_card_progress.html` (que transcriber inclut) ;
>    card v2 chips (`chip=True`) = pilote **reader** (pas transcriber), différée.
> 8. **ETA** encore en `data-*` inline (blocage identifié dans `docs/archive/UI_MECHANISMS_
>    CONSOLIDATION.md`, repris par `WAMA_APP_GENERATION_ROUTE.md`) → catalogue.
> 9. **Bouton « ajouter médiathèque »** = spécifique composer → à généraliser en action commune
>    pilotée par capacité de sortie (APP_CATALOG déclare les output types).
>
> **Doc autorité uniformisation = `WAMA_APP_GENERATION_ROUTE.md` (2026-07-22, cartographie UNIQUE
> confrontée au code)** — consolide et remplace `UI_MECHANISMS_CONSOLIDATION.md`,
> `COMMON_REFACTORING.md`, `GENERALIZATION_PLAN.md` et `BACKEND_CARTOGRAPHY.md`, tous archivés
> `docs/archive/` (12fdabc). (Historique : UI_MECHANISMS n'était fiable que via ses notes §9 —
> tableaux périmés/auto-contradictoires ; COMMON_REFACTORING avait sa roadmap « À faire » périmée.)
> **La route ne capture pas les bugs de comportement** → dimension conformité smoke à ajouter.
>
> **Boucle de refresh** (signalée Fabien) = design client préexistant, PAS lié à login/modération/
> email (backend fail-safe, 0 middleware, 0 JS touché) : `wama-global-progress.js` poll 1500 ms sans
> arrêt + `.active` ré-appliqué à chaque tick + émission `media:processed` dès `done` croît →
> `filemanager tree.refresh()` en cascade. Rendue visible par les 502 récents (restart Apache→Django).

## 22. Skills de prompt par application (2026-07-08) — FAIT, validé Fabien

> Doc de référence : **`PROMPT_PIPELINE.md` §Skills** + `wama/common/prompt_skills/README.md`.
> Mémoire : `project_prompt_skills.md`.

- ✅ Brique `common/utils/prompt_skills.py` (résolution `<app>-<domain>` → `<app>` →
  `default-<kind>`, importable SANS Django) + fichiers `common/prompt_skills/` (imager-image,
  imager-video, composer-music, default-generative).
- ✅ Pipeline : `PROMPT_TARGETS` gagne `domain`/`domain_field` (imager `output_type`) ;
  hook A passe le skill au LLM. Composer `enrich=True` (blocage « consignes visuelles » levé).
- ✅ À la demande : `enrich_on_demand()` (pas gaté par WAMA_PROMPT_ENRICH, émission dans la
  langue de l'utilisateur) ; endpoint imager ✨ branché dessus ; `imager/utils/prompt_enhancer.py`
  (consignes dupliquées) SUPPRIMÉ.
- ✅ Trou comblé : `generate_video_task` imager n'appelait pas la pipeline (locals, base=original).
- ✅ Agents : assistant couvert by design (tools→tâches Celery→pipeline) ; wama-dev-ai importe le
  même module (`PROMPT_SKILLS_DIR` en config + README).
- Testé bout en bout : résolution ✓, Ollama réel (imager-image, émission FR, sujet préservé) ✓,
  passthrough pipeline (interrupteur OFF) ✓, imports ✓.
- ✅ 2026-07-09 **Endpoint commun `/common/api/enrich-prompt/`** (`{prompt, app, domain}`,
  `mode` accepté en alias) — prêt pour le STUDIO (nœud-app : app connue par construction, domain
  passé explicitement car pas d'instance avant exécution) et tout bouton ✨. Imager débranché de
  sa route spécifique (`imager:enhance_prompt` + vue supprimées, JS/template → endpoint commun).
  Invariant studio : l'EXÉCUTION des nœuds doit passer par « instance + tâche Celery » → skills
  hérités by design, aucun câblage par card.
- ⏳ Suites possibles : skills pour anonymizer (kind concept ?), enhancer ; UI pour éditer les
  skills (niveau labo/utilisateur → jonction RAG).

## 23. Audit + nettoyage documentation racine (2026-07-09)

> **MAJ 2026-07-20 — dédoublonnage ROADMAP↔PROJECT_STATUS en cours d'exécution** (recommandation
> 23.2 ; méthode : micro-lectures + vérif code systématique + scripts gardés + archive
> `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`, rien n'est perdu). **Fait** : §0→PROJECT_STATUS,
> §1, §2, §3, §4, §6 (cases mises à jour), §8d-P1, §9.1+tables 9.2, §15 (requalifiée LIVRÉE=Studio).
> Divergences corrigées au passage : import récursif FAIT côté FileManager ;
> UI_MECHANISMS_CONSOLIDATION.md existe (⏳ « produire » périmé) ; params.py/WamaParams livrés ;
> Pexels/Openverse livrés ; canvas studio vanilla JS+SVG (pas de lib node-graph).
> **Reste à trier** (vérif code par item, petites passes) : §5+5b Model Manager (~180 l),
> §7 Converter (~160 l), §8/8b/8c, §9 reste (9.2ter→9.5), §10 i18n (~120 l), §16 (keeper à
> rafraîchir). §11 relu ce jour = au bon niveau ; §12/§13/§14 = keepers selon l'audit 07-09
> (simple survol de fraîcheur à faire en fin de chantier).

> Demandé par Fabien : « la jungle des .md ». 26 fichiers `.md` à la racine, audit exhaustif via
> 8 agents en parallèle (lecture intégrale + vérification empirique de 2-4 affirmations par
> fichier contre le code réel), synthèse + corrections ci-dessous. **Graphe de référencement**
> (`grep` croisé des 26 basenames) : **8 fichiers ne sont référencés par AUCUN autre doc racine**
> (orphelins) — signal fort de contenu absorbé ailleurs ou jamais raccroché au réseau vivant :
> `AUDIT_GLOBALISATION_T+C_2026-07-03.md`, `BATCH_MODEL_AUDIT.md`, `INFRA_WSL_VS_WINDOWS.md`,
> `INPUT_MODEL_MATCHING.md`, `MEDIA_STORAGE_TIERING.md`, `MODAL_ACTIONS_AUDIT.md`,
> `MODEL_META_UNIFICATION_KICKOFF.md`, `NEXT_SESSION_KICKOFF.md`.

### 23.1 Verdict par fichier

| Fichier | Lignes | Nature | Verdict |
|---|---|---|---|
| ~~AUDIT_GLOBALISATION_T+C_2026-07-03.md~~ | 221 | audit ponctuel clos | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09, `git mv`, historique préservé) |
| ~~AUDIT_ROUTE_COMMUNE_2026-07-06.md~~ | 159 | audit ponctuel clos | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-23, fbdf703 ; §3 absorbé par WAMA_APP_GENERATION_ROUTE) |
| ~~BACKEND_CARTOGRAPHY.md~~ | 110 | référence | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-22, 12fdabc ; consolidé dans WAMA_APP_GENERATION_ROUTE) |
| BATCH_FORMAT.md | 149 | référence vivante | ✅ sain, à jour |
| ~~BATCH_MODEL_AUDIT.md~~ | 87 | audit ponctuel clos | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09) |
| ~~CARD_CENTRIC_UI.md~~ | 162 | décision d'archi | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-25, B1 ; §5bis+§4 migrés dans CARD_DESIGN) |
| CARD_DESIGN.md | 408 | **doc pivot**, le plus à jour | ✅ sain (léger résidu §8.5 déjà coché ci-dessous) |
| ~~COMMON_REFACTORING.md~~ | 132 | référence, hub | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-22, 12fdabc ; consolidé dans WAMA_APP_GENERATION_ROUTE) |
| ~~GENERALIZATION_PLAN.md~~ | 60 | chapeau | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-22, 12fdabc ; consolidé dans WAMA_APP_GENERATION_ROUTE) |
| INFRA_WSL_VS_WINDOWS.md | 68 | référence active | ✅ sain (se périmera seul à la bascule full-Linux) |
| INPUT_MODEL_MATCHING.md | 72 | décision + plan | 🔧 étapes 1-4/6 déjà exécutées (`wama-input-match.js` existe), non cochées |
| INSPECTOR_DETAIL_FIELDS.md | 65 | référence vivante | ✅ sain |
| MEDIA_STORAGE_TIERING.md | 88 | décision d'archi (pas implémenté) | 🔧 §B périmé : `EMAIL_BACKEND` déjà configuré (2026-07-02) |
| ~~MODAL_ACTIONS_AUDIT.md~~ | 89 | audit + cible | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-25, B6 ; §3→CONVENTIONS §6.5, §4→§2bis.3, §5→Bugs) |
| ~~MODEL_META_UNIFICATION_KICKOFF.md~~ | 192 | kickoff de session | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09 ; R10 confirmé fait dans REMOVAL_LEDGER.md, suivi résiduel = REMOVAL_LEDGER) |
| MODES_QUEUE_UX.md | 178 | boussole produit vivante | ✅ **corrigé ce jour** : P1 marqué fait (était en retard sur le code) |
| ~~NEXT_SESSION_KICKOFF.md~~ | 55 | brief de session | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-09 ; livrable produit = `UI_MECHANISMS_CONSOLIDATION.md`) |
| PROFILES_PERMISSIONS.md | 166 | référence vivante | ✅ sain, vérifié |
| PROMPT_PIPELINE.md | 98 | référence vivante | ✅ **exemplaire** — le plus frais (skills du jour même) |
| README.md | 269 | point d'entrée | 🔧 table doc ne référence que 8/26 fichiers — désynchronisée |
| REMOVAL_LEDGER.md | 105 | registre actif | 🔧 table §1 désync de son propre journal (R1/R2 dits soldés, table dit encore ⛔) |
| ROADMAP.md | 1219 | **hétérogène** | 🔨 RESTRUCTURER — ~55-60% de doublon avec PROJECT_STATUS (voir 23.2) |
| STUDIO_VISION.md | 100 | vision (non stabilisée) | ✅ **corrigé ce jour** : route `/studio/` (était `/common/studio/`) |
| TRANSCRIBER_REFERENCE_AUDIT.md | 105 | checklist vivante | ✅ sain — ajouter un renvoi croisé vers `WAMA_APP_GENERATION_ROUTE.md` (nuance "référence sémantique, pas cible technique") |
| ~~UI_MECHANISMS_CONSOLIDATION.md~~ | 412 | pilotage de chantier | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-22, 12fdabc ; consolidé dans WAMA_APP_GENERATION_ROUTE) |
| WAMA_APP_CONVENTIONS.md | 2398 | **référence normative** | 🔨 §15.1 (table conformité) périmée sur plusieurs lignes + double numérotation §15 + §5 dupliqué avec CARD_DESIGN |
| PROJECT_STATUS.md (ce fichier) | — | tableau de bord vivant | 🔧 **corrigé ce jour** : §9 Media Library disait Phases 2-4 ⏳, en fait faites |
| WAMA_APP_GENERATION_ROUTE.md | — | cartographie UNIQUE (consolide 4 docs archivés) | ✅ autorité route commune (créé 2026-07-22, 12fdabc) |
| WAMA_MANIFEST_SPEC.md | — | formalisme des manifestes (7 kinds) | ✅ vivant (créé 2026-07-21) |
| WAMA_MANIFEST_ARCHITECTURE.md | — | schéma fonctionnel manifestes/ingest/projection | ✅ vivant (créé 2026-07-21) |
| WAMA_DATA_FUNCTION_CARDS.md | — | catalogue capability WAMA Data | ✅ vivant (créé 2026-07-20 ; à resynchroniser post-refactoring `data/functions/` par domaine) |
| ~~REPRISE_2026-07-22.md~~ | — | handoff daté | 🗄️ **ARCHIVÉ** → `docs/archive/` (2026-07-25, B8 ; vivant migré §40 + R18/R19 + CLAUDE.md) |

### 23.2 Recouvrements identifiés (pas de vrai doublon strict trouvé)

- **CARD_CENTRIC_UI.md vs CARD_DESIGN.md** : verdict de 07-09 RÉVISÉ le 2026-07-25 (plan doc B1) —
  fusionné : le vivant (§5bis preview 3 niveaux, §4 zones de dépôt) migré dans CARD_DESIGN
  (§1quinquies, §8.6) ; le reste (COMPOSE_CAPABILITIES/APP_SPEC/staging) n'a jamais existé dans le
  code → CARD_CENTRIC_UI archivé.
- **ROADMAP.md vs PROJECT_STATUS.md** : le plus gros chevauchement du lot (~55-60 %). ROADMAP
  mélange vision long terme, décisions historiques ET détails d'implémentation déjà livrés
  (Media Library, Ollama, cam_analyzer §9.1/9.2 — tout 2026-04/05, 100% ✅). Les deux docs
  **divergent silencieusement** (ROADMAP avait raison sur Media Library, PROJECT_STATUS avait
  tort — corrigé ce jour ; l'inverse est possible ailleurs). **Recommandation non exécutée
  (chantier dédié à prévoir)** : restructurer ROADMAP pour ne garder que specs/décisions/backlog
  intemporels (§12/§13/§14/§15/§16), archiver les sections 100 % actées (§3/§4/§9.1-9.2/§8d
  Phase 1) au profit d'un renvoi vers PROJECT_STATUS.
- **WAMA_APP_CONVENTIONS.md §5 vs CARD_DESIGN.md** : redondance de contenu (structure de card,
  ordre des zones) — CARD_DESIGN.md est la référence la plus récente et se déclare déjà comme
  telle. **Recommandation non exécutée** : réduire §5 à un renvoi vers CARD_DESIGN.md.
- **AUDIT_GLOBALISATION_T+C_2026-07-03.md → AUDIT_ROUTE_COMMUNE_2026-07-06.md → COMMON_REFACTORING.md** :
  chaîne d'audits successifs sur le même chantier (port Transcriber/Composer/Describer), chacun
  prolongeant/absorbant le précédent. Le premier est mort, le second a été archivé le 2026-07-23
  (§3 absorbé), le troisième a servi de hub jusqu'au 2026-07-22 puis a été consolidé dans
  `WAMA_APP_GENERATION_ROUTE.md` (les trois sont archivés `docs/archive/`).
- **NEXT_SESSION_KICKOFF.md → UI_MECHANISMS_CONSOLIDATION.md** : le premier commande le second
  comme livrable ; mission accomplie, le brief n'a plus de raison d'être consulté.

### 23.3 Corrections empiriques appliquées ce jour (factuel, périmé → à jour)

- `PROJECT_STATUS.md` §9 : Media Library Phases 2-4 étaient marquées ⏳, **vérifié faites**
  (`MediaProvider`/`UserProviderConfig` + 6 connecteurs + filtrage UI).
- `MODES_QUEUE_UX.md` : phase **P1 marquée ✅** (`app_modes.py` + `wama-modes.js` existent et sont
  câblés dans imager/composer/studio — le doc se croyait encore au stade projet).
- `STUDIO_VISION.md` : route corrigée `/common/studio/` → `/studio/` (l'app a été migrée en app
  Django dédiée, le doc n'avait pas suivi).

### 23.4 Reste à faire (backlog de nettoyage — non exécuté ce jour, décisions ouvertes)

**Petites corrections factuelles restantes** (chacune = quelques lignes, faisable en 10-15 min) :
1. ✅ SANS OBJET (2026-07-23) : `AUDIT_ROUTE_COMMUNE_2026-07-06.md` archivé — plus de correction
   à porter sur un doc archivé.
2. ✅ SANS OBJET (2026-07-22) : `GENERALIZATION_PLAN.md` archivé.
3. `INPUT_MODEL_MATCHING.md` : cocher étapes 1-4/6 déjà exécutées.
4. ✅ SOLDÉ (2026-07-25, plan doc B7) : `MEDIA_STORAGE_TIERING.md` §A/§B supprimés — les réglages
   sont LIVRÉS sous d'autres noms (`media_retention_days`, `notify_email`/`notify_on`, câblés
   10 apps) ; renvoi vers `PROFILES_PERMISSIONS.md` §2/§3 posé.
5. ✅ SOLDÉ (2026-07-25, B6) : `MODAL_ACTIONS_AUDIT.md` archivé ; le suivi d'adoption de
   `_settings_modal_footer.html` = critère `settings_modal_footer` de `check_app_conformity`.
6. `REMOVAL_LEDGER.md` : resynchroniser la table §1 avec le journal (R1/R2 → ✅).
7. `README.md` : étoffer la table de doc (8/26 référencés seulement).
8. `WAMA_APP_CONVENTIONS.md` §15.1 : ETA et bouton Dupliquer Avatarizer marqués ❌ alors que faits.
9. `TRANSCRIBER_REFERENCE_AUDIT.md` : renvoi croisé vers `WAMA_APP_GENERATION_ROUTE.md` pour
   éviter la contradiction implicite (transcriber = référence sémantique, pas cible technique).
10. ✅ SANS OBJET (2026-07-22) : `UI_MECHANISMS_CONSOLIDATION.md` archivé (la contradiction P0
    params.py est de plus purgée, cf. §31.6).

**Décisions structurelles tranchées (Fabien, 2026-07-09)** :
- **Archivage → `docs/archive/`** (git mv, historique préservé, pas de suppression). **Exécuté** pour
  les 4 candidats fermes : `AUDIT_GLOBALISATION_T+C_2026-07-03.md`, `BATCH_MODEL_AUDIT.md`,
  `NEXT_SESSION_KICKOFF.md`, `MODEL_META_UNIFICATION_KICKOFF.md` (R10 confirmé clos dans
  REMOVAL_LEDGER.md avant archivage). Aucun lien markdown cassé (vérifié par grep). **Soldé
  (2026-07-23, fbdf703)** : `AUDIT_ROUTE_COMMUNE_2026-07-06.md` **archivé** → `docs/archive/` ;
  son §3 (chantiers ordonnés) est absorbé par `WAMA_APP_GENERATION_ROUTE.md`.

**Décisions structurelles encore ouvertes** — chantiers de plus grande ampleur, non exécutés ce jour :
- **Restructuration ROADMAP.md** (1219 lignes, ~55-60 % doublon) — chantier de taille, à faire en
  session dédiée (comme le pratique déjà ce repo pour les gros chantiers de convergence) :
  garder §12/13/14/15/16, archiver le reste au profit de renvois vers PROJECT_STATUS.
- **Fusion WAMA_APP_CONVENTIONS.md §5 → renvoi CARD_DESIGN.md** (évite la double maintenance déjà
  visible sur le retrait staging).
- **Règle anti-jungle pour la suite** : avant de créer un nouveau `.md` racine, vérifier s'il ne
  s'agit pas d'un simple ajout à un doc existant (chapeau `PROJECT_STATUS.md` pour l'avancement,
  doc de référence thématique sinon) — les audits ponctuels (`*_AUDIT.md`, `*_KICKOFF.md`) ont
  vocation à être **absorbés puis archivés** une fois leur chantier clos, pas à s'accumuler.

## 24. Bugs corrigés + duplication de vocabulaire média découverte et consolidée (2026-07-09)

- ✅ **Bug médiathèque (recherche toujours vide)** : `MediaPicker.open({type:...})` passait des
  valeurs (`'audio'`, `'all'`) qui ne correspondaient à AUCUNE valeur exacte de
  `media_library.ASSET_TYPES` → `.filter(asset_type=asset_type)` ne matchait jamais rien, quel que
  soit le texte cherché (repro : "voix_fab" introuvable). Fix : `TYPE_GROUPS` (nouveau,
  `media_library/models.py`) traduit les alias larges en listes de vraies valeurs avant filtre
  (`asset_type__in=...`) ; valeur exacte toujours acceptée en repli. Testé bout en bout (asset
  synthétique, 5 cas dont un cas négatif).
- ✅ **Bug rôles/permissions** : `user_update_role` (tier admin/dev/user) faisait `groups.clear()`,
  effaçant silencieusement les rôles MÉTIER (`role:*`, axe B de `accounts/permissions.py`) à chaque
  changement de tier — ET ne synchronisait jamais `UserProfile.account_tier` (l'axe réellement
  consulté par `permissions.accessible()` pour gater les apps WAMA), si bien que choisir
  « Développeur » ne débloquait aucune app (seul « Admin »/`is_superuser` fonctionnait). D'où le
  symptôme remonté par Fabien : « je dois le rendre admin pour tout autoriser ». Fix : ne retire
  que les groupes de tier legacy (pas les `role:*`), synchronise `account_tier` en parallèle.
  **Ajout** : colonne « Métiers » dans `accounts/user_management.html` — checkboxes multi-select
  par utilisateur (communication/recherche/ingénierie/administratif, cumulatifs), nouvel endpoint
  `user_toggle_metier_role` (miroir de `app_access_toggle`, mêmes Groups `role:*`), bouton "Tout
  cocher" par ligne. **Clarification consciente** : le tier `developpeur` (bypass total,
  `BYPASS_TIERS`) reste le bon levier pour "faire tester toutes les apps à quelqu'un" — cocher les
  4 métiers ne suffit PAS pour les apps à `min_tier` (ex. model_manager), vérifié empiriquement.
  Testé bout en bout (5 scénarios : tier→bypass, persistance métier au changement de tier, rejet
  clé invalide, gating min_tier).
- 🔍 **Duplication de vocabulaire « type de média » découverte (Fabien, en creusant le fix
  médiathèque)** : le même concept « catégorie de média » (image/vidéo/audio/document/archive)
  existait déjà en 3 endroits distincts, écrits indépendamment :
  1. `common/app_registry.py::MEDIA_CATEGORIES` + `normalize_types()` — la vraie source, bâtie
     pour le typage des ports studio, mais **quasi sans consommateur** avant ce jour (seulement
     `studio_node_ports()` dans le même fichier).
  2. `common/utils/media_probe.py` (créé 2026-07-08) — listes d'extensions privées dupliquées.
  3. `media_library/static/media_library/js/media-library.js::AUDIO_TYPES` (JS, préexistant) +
     `media_library/models.py::TYPE_GROUPS` (créé ce jour) — même regroupement recréé une 3e fois.
  **Consolidé** : (1) reste la source unique ; extensions manquantes ajoutées (`.heif`/`.avif`,
  `.wmv`/`.ts`/`.m4v`/`.mpeg`, `.aiff`/`.aif`) pour ne rien perdre par rapport aux doublons
  retirés ; (2) dispatch réécrit sur `normalize_types()` (PDF reste un cas particulier littéral,
  page-count) ; (3) `TYPE_GROUPS` dérivé de `MEDIA_CATEGORIES` via un mapping
  `ASSET_TYPE_CATEGORY` (les ASSET_TYPES de Media Library restent plus fins — voice/audio_music/
  audio_sfx — mais se RATTACHENT au vocabulaire commun au lieu d'en inventer un 2e), le JS local
  supprimé au profit d'une variable globale rendue depuis cette même source (`audio_types_json`
  dans le contexte de la vue `index`). Testé : `probe_media` (5 fichiers réels, sortie identique
  avant/après), `normalize_types` sur les extensions ajoutées, pages media-library/converter/
  reader (200), scénario recherche médiathèque (5 cas, inchangé).
- ⏳ **Question ouverte (Fabien)** : `media_library` n'est **PAS enregistrée dans `APP_CATALOG`**
  (confirmé — seules les 10 apps généralistes y figurent). Elle a été construite hors du scope de
  standardisation/auto-génération (pas d'`input_types`/`output_types`, pas de score de conformité,
  pas de port studio). L'intégrer pleinement à `APP_CATALOG` est une décision d'architecture plus
  large (impact nav/permissions/conformité/studio), **pas tranchée, pas exécutée** — à instruire
  si Fabien veut aligner Media Library sur le reste de l'écosystème métadonnée-driven.
- **Leçon retenue** : avant d'écrire une nouvelle petite table de correspondance (extensions,
  catégories, alias), grep `wama/common/app_registry.py` et `wama/common/utils/app_modes.py`
  d'abord — ce sont les deux hubs de vocabulaire partagé les plus susceptibles de déjà couvrir le
  besoin.

## 25. 2 bugs inspecteur commun (transverses, PAS liés au portage) — corrigés 2026-07-10

> Remontés par Fabien en observant Converter, mais les deux vivent dans `wama-inspector.js`
> (commun) → affectaient TOUTES les apps consommant l'inspecteur, pas Converter spécifiquement.

- ✅ **Navigation clavier bloquée sur un batch sélectionné** : `moveSelection()` (↓/↑) exigeait
  `itemId !== null` — or `selectBatch()` met `itemId = null`. Résultat : après un clic sur l'
  en-tête d'un batch, ↓/↑ ne faisaient plus rien (« pas systématique » = seulement après avoir
  sélectionné un batch, pas à chaque card). Fix : `moveSelection` ancre désormais la position sur
  la première/dernière card enfant du batch selon le sens du parcours quand `itemId` est null
  mais `batchId` est défini ; garde du keydown étendue à `itemId !== null || batchId !== null`.
- ✅ **Inspecteur qui « se désactualise » juste après un clic** : `fillDetail()`/`fillPreview()`
  n'avaient AUCUNE protection contre les réponses réseau désordonnées — un clic rapide carte A→B
  lance 2 fetch, sans garantie que celui de A ne résolve pas APRÈS celui de B ; sa callback
  repeignait alors le volet avec le contenu de A alors que B était la sélection courante. Fix :
  jeton anti-course (`_detailReqId`/`_previewReqId`, incrémenté à chaque fetch + à chaque
  `selectBatch`/`deselect`) — seule la callback du DERNIER fetch lancé est autorisée à peindre.
  Bug transverse pré-existant, pas introduit par le portage Converter du jour.
- Testé : sanity JS (accolades/parenthèses équilibrées, occurrences des jetons), smoke des 5
  pages consommant l'inspecteur (200). Pas de test navigateur réel (comportement client pur) —
  **validation visuelle par Fabien recommandée**.

### 25bis. RETIRÉS (2026-07-10) — diagnostic invalidé par le test navigateur

Les 2 fixes ci-dessus ont été **retirés de `wama-inspector.js`** (revert complet, fichier
redéployé dans `staticfiles/`) : Fabien a testé en navigateur après application, **aucune erreur
JS console**, et les deux symptômes (navigation clavier bloquée, inspecteur qui se désactualise)
**persistaient dans Converter** — la preuve que mon diagnostic « bug transverse commun » était
faux ou en tout cas incomplet. Fabien confirme que **reader/composer/transcriber/describer
fonctionnent correctement** avec ce même `wama-inspector.js` : le problème est **isolé à
Converter**, pas au commun. Règle appliquée : *modification incertaine + non prouvée nécessaire
→ retrait plutôt que code potentiellement inutile qui complique l'uniformisation*. Piste réelle
trouvée mais non confirmée comme cause : Converter est le SEUL des 5 apps portées dont le JS
(`converter.js`) n'a **aucun wrapper `DOMContentLoaded`** — ses listeners (dont un click délégué
sur `#converterQueue`, en concurrence avec celui de l'inspecteur) s'exécutent immédiatement au
parsing du script, alors que reader.js séquence TOUT (inspecteur d'abord, puis cycle-button) dans
un unique `init()` appelé au `DOMContentLoaded`. Aucun `stopImmediatePropagation` trouvé nulle
part donc ce n'est pas une preuve, juste une piste **pour le prochain passage sur Converter**.
**Prochaine étape demandée par Fabien** : porter Converter à 100% en s'appuyant sur Transcriber/
Describer/Composer/Reader (apps les plus avancées) comme référence de construction — card
d'entrée (✅ fait §27.1), tri/filtrage/disposition de file, boutons d'actions de file, bug +
mise en conformité de l'inspecteur inclus dans ce passage complet plutôt que traités isolément.

## 26. Vérification pipeline prompts composer/imager (2026-07-10)

- ✅ **Câblage confirmé** : `composer/tasks.py` (1 site) et `imager/tasks.py` (2 sites : image +
  vidéo, cf. §22) appellent bien `process_prompt_for()` → traduction/enrichissement selon modèle
  pour les deux apps. RAG non concerné (pas implémenté, cf. §RAG anticipation).
- ⚠️ **Point non tranché, à revérifier depuis WSL2** : `AIModel.model_key` pour composer semble
  SANS le préfixe `composer:` côté base Windows consultée (`musicgen-medium` au lieu de
  `composer:musicgen-medium`) → `_resolve_model()` ne matcherait jamais, capacités jamais lues,
  repli silencieux sur `default_model_type='music'`. **MAIS** : le code documente déjà ce piège
  exact (commentaire `model_registry.py:912`, renvoie à `REMOVAL_LEDGER.md` F4, marqué ✅ FAIT
  2026-07-01 avec re-sync). Vu que Fabien a confirmé que la base Windows n'est pas à jour
  (session du jour), **cette lecture n'est probablement qu'un artefact de DB obsolète**, pas un
  bug réel côté WSL2 — à reconfirmer directement depuis WSL2 avant toute action. Sans conséquence
  observable actuelle de toute façon (tous les modèles composer sont `music`, capacités vides).

## 27. Converter : card d'entrée manquante + Grille de conformité périmée (2026-07-10)

### 27.1 Bug converter : aucun moyen d'ajouter un fichier hors filemanager — corrigé

Converter n'avait **jamais adopté** la brique commune `_new_item_card.html` (contrairement à
reader/composer/transcriber/describer) : son seul point d'import vivait dans le **volet droit**
(`app_right_panel_media`), invisible en **mode simplifié** (volets masqués) → aucun moyen d'ajouter
un fichier sans passer par le filemanager dans ce mode. Fix : card commune ajoutée en **tête de
file** (même pattern que reader, commentaire "Card d'entrée déplacée du volet vers la TÊTE DE
FILE"), volet droit vidé. Détails techniques :
- IDs préservés (`converterDropZone`/`converterFileInput`) → JS inchangé sauf 1 ajout nécessaire :
  `_new_item_card.html` ne fournit PAS de handler clic-pour-parcourir (chaque app le câble elle-même,
  comme reader) — l'ancien markup avait un `onclick` inline retiré au passage à la brique commune ;
  ajouté `dropZone.addEventListener('click', () => fileInput.click())` dans `converter.js`.
  **Sans cet ajout, cliquer la zone n'ouvrait plus le sélecteur de fichiers** (régression silencieuse
  évitée en vérifiant le JS avant de conclure).
- `batch_detect_bar.html` : ancien include autonome doublé → retiré, réutilisé via le slot
  `show_batch_bar=True` de la card commune (1 seule instance désormais).
- CSS `.converter-drop-zone.dragover` (bespoke) → généralisé en `.drop-zone.dragover` (classe
  générique posée par `_new_item_card.html`), sinon le retour visuel dragover aurait disparu.
- Testé : page 200, 1 seule occurrence de chaque ID (pas de doublon), label attendu présent.

### 27.2 Grille de conformité (`APP_CATALOG.conventions`, `get_conformity_summary()`) : périmée, pas automatique

**Diagnostic confirmé** : le score n'est PAS calculé par introspection du code — c'est une simple
moyenne sur des **booléens saisis à la main** par app (`_conv(...)` dans `app_registry.py`), jamais
revérifiés après coup. Composer (94%) n'est pas "gonflé" : c'est le SEUL à avoir été correctement
ré-audité récemment (commentaires datés, lignes citées) ; les autres dérivent silencieusement au
fil des chantiers (portage, ETA, boutons ajoutés) sans que quiconque ne remette à jour leurs flags.

**Scores AVANT correction** (composer 94% en tête, plusieurs apps sous-évaluées) :
transcriber 77%, describer 72%, enhancer/reader 69%, synthesizer 63%, converter 62%,
anonymizer 60%, imager 45%, avatarizer 40%.

**Corrections appliquées ce jour (chaque flag vérifié par grep/lecture directe du code avant
modification — pas de supposition)** :
- **reader** : `eta_individual`/`eta_batch`/`eta_queue` False→True (wama-eta câblé partout,
  vérifié `_item_card.html`/`_batch_card.html`/`_global_progress.html`) → **69%→82%**.
- **converter** : commentaire `inspector` périmé (décrivait l'ancien `.init`, pas
  `initFromSchema` du portage d'aujourd'hui) + `eta_individual`/`eta_batch`/`eta_queue` False→True
  (mêmes briques que reader, câblées lors du portage) → **62%→75%**.
- **avatarizer** : `duplicate`/`batch`/`clear_all` False→True (boutons + `BatchAvatarJob(BatchMixin)`
  vérifiés présents), `eta_batch` None→True (wama-eta sur les batchs confirmé) → **40%→57%**.
- **transcriber** : `eta_individual`/`eta_queue` False→True (`WamaEta.render` + `_global_progress.html`
  confirmés) ; `eta_batch` laissé False (aucune trace de `eta_ids` batch en JS, cohérent avec la
  mémoire "ETA batch : reste transcriber") → **77%→86%**, redevient cohérent avec son statut de
  référence.
- **imager** : `settings`/`duplicate`/`start_all`/`drag_drop` False→True (boutons + drop-zones
  vérifiés présents dans le template) → **45%→63%**. `batch` volontairement PAS touché : `has_batch`/
  `batch_type=None` portent une annotation "to be redesigned" qui semble une nuance délibérée
  (parent_generation existe mais n'est peut-être pas jugé un "vrai" batch unifié) — **à trancher par
  Fabien**, pas réinterprété unilatéralement.

**Colonnes potentiellement incomplètes (repéré, PAS ajouté)** : aucun flag ne couvre (a) la card
« Nouvel élément » en tête de file (le bug §27.1 aurait été visible dans la grille si ce flag
existait), (b) la section Infos/détail de l'inspecteur (`register_app_detail`/chips, distincte du
flag `inspector` générique existant), (c) `ProcessingTimeMixin`/temps de traitement affiché. Ajouter
ces colonnes nécessiterait de ré-auditer les 10 apps dessus — pas fait, pour ne pas empiler des
flags non vérifiés sous pression de temps.

**PAS fait (limite assumée)** : describer/enhancer/synthesizer/anonymizer n'ont PAS été
ré-audités — leurs scores (72%/69%/63%/60%) sont encore susceptibles d'être sous-évalués comme
imager/converter/reader/avatarizer l'étaient. **Recommandation** : un audit complet et systématique
(idéalement en agents parallèles, comme l'audit des .md du §23) serait nécessaire pour fiabiliser
la grille sur les 10 apps plutôt que de continuer à la corriger au fil des sessions.

Scores APRÈS correction (ordre) : transcriber 86%, reader 82%, converter 75%, composer 94% (inchangé,
toujours en tête), describer 72%, enhancer 69%, avatarizer 57%, synthesizer 63%, anonymizer 60%,
imager 63%. Testé : syntaxe `app_registry.py` OK, `/common/apps/` → 200, pages imager/avatarizer/
transcriber → 200.

## 28. Retrait des 2 fixes wama-inspector.js + suite du portage Converter (2026-07-10)

### 28.1 Fixes communs retirés — diagnostic invalidé par test navigateur réel

Fabien a testé en navigateur après application des 2 fixes §25 : **aucune erreur JS console**,
et les deux symptômes **persistaient** dans Converter. Preuve directe que le diagnostic « bug
transverse dans le commun » était faux — reader/composer/transcriber/describer utilisent le même
`wama-inspector.js` et fonctionnent. Règle appliquée (demandée explicitement par Fabien) :
*modification incertaine + non prouvée nécessaire → retrait, pas de code potentiellement inutile
qui complique l'uniformisation*. **Les 2 fixes ont été intégralement retirés** de
`wama-inspector.js` (revert exact, fichier redéployé) : `moveSelection` batch-anchor + garde
keydown étendue + jetons anti-course `_detailReqId`/`_previewReqId`. Fichier revenu à l'identique
d'avant le §25 (vérifié : 0 occurrence des marqueurs, accolades/parenthèses équilibrées, smoke
5 apps → 200).

### 28.2 Piège commentaire Django multi-lignes — 4e récidive, scan complet du dépôt

Fabien a repéré un `{# ... #}` multi-ligne que je venais d'écrire dans `converter/index.html` —
le piège documenté dans `reference_django_multiline_comment.md`, déjà récidivé 3× avant ce jour.
Corrigé (`{% comment %}...{% endcomment %}`) + **scan mécanique de tout le dépôt** (`glob` +
regex, pas une relecture visuelle) : 2 AUTRES occurrences pré-existantes trouvées et corrigées,
jamais détectées avant (`imager/index.html` entre deux `<script>`, `studio/index.html`). 0 restante
sur tout `wama/**/*.html` après correction. Mémoire renforcée : compter sur la mémoire seule a
échoué 3 fois → la procédure documentée est désormais un scan mécanique après toute édition de
commentaire, pas une simple règle à se rappeler.

### 28.3 Suite du portage Converter — comparé point par point à reader/composer/transcriber/describer

Fabien : *« évite de toucher au commun qui fonctionne très bien »* + s'appuyer sur les 4 apps les
plus avancées comme référence. Comparaison systématique (grep direct, pas de supposition) →
3 gaps réels et vérifiés, **tous corrigés dans converter uniquement** (aucune ligne de commun
touchée) :

1. **`_queue_toolbar.html` jamais adopté** (tri + filtre + toggle Ligne/Mosaïque + actions
   globales, bundle commun utilisé par composer/describer/reader/transcriber — PAS
   `_queue_actions.html`, qui n'est en fait utilisé que par enhancer, contrairement à ce que
   suggérait une mémoire périmée). Ajouté en tête de file avec les IDs EXISTANTS de converter
   (`converterStartAllBtn`/`converterClearAllBtn`) → zéro changement JS requis pour ces boutons.
   Vue : `apply_queue_sort_filter()` branché (même brique que reader), `_name` défini sur
   `input_filename` du 1er item. Toggle Ligne/Mosaïque (`.wama-layout-btn`, mécanisme
   `wama-queue.js::initLayoutToggle`, chargé globalement dans `base.html`) vient bundlé — geste
   auparavant construit mais jamais câblé à un bouton nulle part dans le dépôt (vérifié par grep
   sur les 4 apps de référence + `app_modern_base.html`).
2. **`#converterQueue` sans classe `wama-queue-{{ card_layout }}`** → ajoutée (`card_layout`
   déjà exposé globalement par le context processor accounts, zéro changement de vue requis).
3. **Batch collapse forcé `show`** (toujours déplié) → contrevient à la convention Solitaire
   commune (replié par défaut + persistance localStorage + un seul déplié à la fois,
   `wama-queue.js::initBatchCollapse`/`initOnePileOpen`, chargé globalement). Retiré, converter
   suit maintenant la même convention que reader.
4. **`_inspector_actions.html` jamais inclus** — gap le PLUS probablement responsable du
   comportement « inspecteur qui ne se comporte pas correctement » signalé par Fabien : l'hôte
   `#inspectorActions` (où `cloneActions()` écrit les actions clonées de l'item/batch sélectionné)
   **n'existait pas du tout** dans le DOM de converter → `cloneActions(null, ...)` no-opait
   silencieusement (`if (!host) return;`, confirmé en lisant `wama-inspector.js`) — aucune erreur
   console, la section Actions restait simplement vide/jamais mise à jour. Ajouté dans
   `app_right_panel_actions`, exactement comme reader.

Testé : page 200, tous les IDs/classes présents exactement une fois (`converterStartAllBtn`,
`converterClearAllBtn`, `inspectorActions`, `wama-layout-btn`, `wama-queue-list`), 5 combinaisons
sort/filter → 200 sans crash, filtre `running` confirmé sur données réelles (créées puis
nettoyées). Smoke global 7 pages → 200.

**Reste à faire sur Converter (hors scope de ce palier)** : la piste DOMContentLoaded (§25bis —
converter.js n'a aucun wrapper, contrairement à reader.js qui séquence tout dans un `init()`
unique) n'a pas été retenue comme correction (pas de preuve causale, et le point 4 ci-dessus est
un candidat plus solide pour expliquer le comportement de l'inspecteur) — **à réévaluer une fois
le point 4 validé en navigateur par Fabien** ; si le problème persiste malgré `_inspector_actions.html`,
la piste DOMContentLoaded redevient la prochaine à creuser, toujours côté converter.js/template
uniquement.

## 29. Bug preview inspecteur : webp invisible — doublon MIME filemanager/commun (2026-07-10)

**Symptôme** : les .webp ne s'affichaient pas dans la preview de l'inspecteur (toutes apps),
alors que la preview du filemanager les lit correctement. Fabien : *« la preview est globale et
commune... pas de réécriture, on utilise le formalisme en place »* — a demandé de VÉRIFIER s'il y
avait un doublon plutôt que de deviner un correctif.

**Root cause confirmée empiriquement** : `mimetypes.guess_type('test.webp')` → `(None, None)` sur
cette machine (base mime.types locale incomplète, connu sous Windows). `preview_registry.py::
create_simple_adapter` (l'adaptateur COMMUN consommé par TOUTES les apps portées à l'inspecteur)
appelait `mimetypes.guess_type()` nu → `mime_type=None` → repli `'application/octet-stream'` →
le JS (`renderInlinePreview`, `mime.indexOf('image/') === 0`) ne reconnaît pas l'image, rien ne
s'affiche. **`filemanager/views.py::api_preview` avait DÉJÀ ce correctif** (commentaire explicite
*"Robust MIME detection: mimetypes.guess_type can fail on Windows"* + dict `_EXT_MIME` local,
2026-0X) — jamais reporté vers l'adaptateur commun de l'inspecteur. Doublon confirmé exactement
comme suspecté par Fabien : 2 chemins de détection MIME divergents pour le même besoin.

**Fix (centralisation, pas de réécriture du formalisme preview)** : nouveau
`common/utils/mime_utils.py::guess_mime_type()` — SOURCE UNIQUE (stdlib + repli extension→MIME,
contenu du dict extrait de filemanager). Consommé par :
- `preview_registry.create_simple_adapter` (bug réel, corrigé).
- `filemanager/views.py::api_preview` (refactoré pour utiliser la même fonction — le dict local
  `_EXT_MIME` supprimé, plus de 2e copie qui pourrait diverger).

Testé : `guess_mime_type('test.webp')` → `image/webp` ✓. Bout en bout sur un vrai fichier webp
(`media/anonymizer/1/input/objects_01.webp`) via `unified_preview()` réel (job converter créé/
nettoyé) → `mime_type: image/webp` (était `application/octet-stream` avant fix). Filemanager
`api/preview/` sur le même fichier → toujours `image/webp` (comportement inchangé après
refactor). Smoke 5 apps consommant l'inspecteur → 200.

## 30. Card d'entrée Enhancer — investigué, PAS implémenté (gap plus profond que prévu)

Demandé par Fabien (avec permission explicite de ne pas implémenter si le fit n'est pas net) :
ajouter la card commune `_new_item_card.html` en tête de file d'Enhancer, comme les 5 apps déjà
portées — Enhancer a 2 domaines (image/vidéo · audio) avec onglets, la card devrait s'adapter.

**Investigation réelle faite avant de décider** (pas une estimation a priori) : Enhancer est
**significativement moins porté** que je ne le pensais — chacun de ses 2 onglets a sa PROPRE
structure, et aucun des deux n'utilise le formalisme commun établi ailleurs :
- `#imgvideoTab` : queue `#enhancer-queue` avec des cards **codées en dur** dans le template
  (`.synthesis-card` + classes de statut manuelles), PAS `_job_card.html`/`_batch_card.html`.
  Utilise `_global_progress.html` (commun) pour la barre globale, au moins ça.
- `#audioTab` : queue séparée, ET sa PROPRE barre de progression globale codée à la main
  (`audioGlobalStatus`/`audioGlobalProgressBar`) au lieu de `_global_progress.html` — même dans
  la même app, les 2 domaines ne sont pas au même niveau d'adoption du commun.
- Import : 2 drop-zones distinctes déjà présentes (`dropZoneEnhancer`/`dropZoneAudio`, toggle
  `d-none` via `switchDomain()`) — mais dans le volet droit, pas en tête de file.

**Décision** : ajouter SEULEMENT la card d'entrée serait un patch cosmétique déconnecté du reste
(elle suppose le contrat batch-import/formalisme card des apps déjà portées, qu'Enhancer n'a pas).
**PAS implémenté** — Enhancer a besoin d'un vrai chantier de portage (cards communes sur les 2
onglets, unifier la barre audio sur `_global_progress.html`, PUIS la card d'entrée par domaine),
pas d'un ajout isolé. À traiter comme un palier à part entière, pas glissé dans cette session.

---

## 31. Audit empirique de conformité des 10 apps généralistes (2026-07-10/11)

### 31.1 Méthode
Audit **empirique** (grep/lecture de code, zéro déclaratif) des 10 apps sur **31 critères** :
les 25 flags existants de la grille `_conv()` + 8 nouveaux critères d'uniformisation mesurés
(`new_item_card`, `queue_toolbar`, `queue_manipulation`, `anti_race`, `cycle_button`,
`processing_time`, `status_vocab`, `toast`), chaque verdict adossé à une preuve `file:line`.
La grille `app_registry.py::_conv()` a été **étendue** avec ces 8 critères (comblant les
« colonnes manquantes » identifiées en §27.2) et les flags périmés corrigés. Source live
inchangée : `/apps/` (`get_conformity_summary()`).

### 31.2 Scores APRÈS correction de grille (avant : §27.2)
| App | Score | Écarts restants (issues de la grille) |
|---|---|---|
| transcriber | **93 %** (28/30) | recursive_import, toast (1 alert+confirm edit.js:675) |
| describer | **93 %** (28/30) | recursive_import, modes (pas déclaré APP_MODES) |
| composer | **92 %** (26/28) | recursive_import, toast (4 alert index.js) |
| reader | **90 %** (28/31) | recursive_import, modes, toast (2 alert reader.js) |
| converter | **77 %** (24/31) | download_all, cross_app_options (Phase 2), modes, queue_manipulation, recursive_import, status_vocab (DONE/ERROR), toast (21 alert) |
| enhancer | **70 %** (22/31) | anti_race ⚠, batch-card mère hand-built, new_item_card, queue_toolbar, cycle_button, layout, processing_time, toast (13 alert) |
| synthesizer | **70 %** (22/31) | anti_race ⚠, modales hand-built (params.py ponte dom_id), new_item_card, _batch_card, queue_toolbar, layout, processing_time, toast (42 alert) |
| anonymizer | **61 %** (19/31) | **pas de champ status** (booléen `processed`) = prérequis bloquant, params.py ORPHELIN, inspecteur (preview seule), toast (23 alert) |
| imager | **60 %** (18/30) | **inspecteur 0/4**, params.py ORPHELIN, anti_race ⚠, double markup card image/vidéo, toast |
| avatarizer | **55 %** (17/31) | start_all/download_all sans vue serveur, clear_all simulé client, anti_race ⚠, ordre boutons card KO, toast (21 alert) |

### 31.3 Flags périmés corrigés dans la grille (preuves dans les commentaires du code)
- **ETA sous-déclaré partout** : les 3 niveaux (card `.wama-eta`, batch `data-eta-ids`,
  `_global_progress.html`) sont en réalité câblés dans **les 10 apps** — les flags False
  dataient d'avant le déploiement ETA. Corrigé pour describer/enhancer/synthesizer/
  anonymizer/imager/avatarizer + eta_batch transcriber.
- **avatarizer.tool_api False → True** : add_to/start/get_status présents au registre
  central `wama/tool_api.py` (le « seul manque restant » de CONV §17.6 était périmé).
- **filemanager_import** : True vérifié pour transcriber/describer/reader/synthesizer/
  anonymizer (listener `wama:fileimported`) ; composer=N/A (entrée texte) ; imager/
  avatarizer partiels (drop-zone `data-wama-app` sans listener) → restent False.
- **reader.layout False → True** ; **converter.layout False → True** ;
  **multi_format_download → N/A** pour converter/enhancer/synthesizer/anonymizer/imager/
  avatarizer (early binding : le format se règle AVANT le traitement).

### 31.4 Enseignements transverses (au-delà des flags)
1. **Fracture nette 5+5** : les 5 apps portées (transcriber/describer/composer/reader/
   converter) ont TOUTE la pile commune (new_item_card, _batch_card, queue_toolbar,
   queue_manipulation*, begin_processing*, ProcessingTimeMixin, initFromSchema+
   _inspector_actions+detail/preview registries). Les 5 autres n'ont RIEN de la couche
   file commune. (*converter : consolidate artisanal + verrou local — voir 31.5.)
2. **anti_race absent = seul risque fonctionnel réel** des 5 non portées : start() de
   enhancer (views.py:423), synthesizer (:549), imager (:626), avatarizer (:172) font
   check-then-set sans verrou ni revoke.
3. **`alert()` : ~106 occurrences** dans 8 apps (le helper `WamaApp.toast` existe et
   marche — describer = preuve).
4. **params.py = 10/10 EXISTENT** (contradiction UI_MECHANISMS §0bis/§7 tranchée
   empiriquement) MAIS 2 sont **orphelins** (imager, anonymizer : aucun consommateur
   WamaParams) et 1 ne ponte que les dom_id (synthesizer).
5. **Couleurs de boutons card** : seuls converter (réf) / reader / transcriber sont au
   schéma outline canonique. describer/composer/synthesizer/anonymizer/imager/avatarizer
   ont des variantes pleines ou intercalent des boutons hors référence.
6. **Statuts en base** : reader migré (0008) ; converter encore DONE/ERROR ; anonymizer
   n'a PAS de champ status (booléen `processed`) — hors norme la plus profonde.
7. **modes** : APP_MODES déclare 5 apps (anonymizer/enhancer/imager/synthesizer/
   transcriber) mais seuls enhancer+imager CÂBLENT WamaModes. Question ouverte pour
   Fabien : describer/reader ont-ils vocation à des modes-switch, ou N/A comme composer
   (« type dérivé », flag None) ?

### 31.5 Plan de finition des 5 apps les plus proches (exécuté à la suite de cet audit)
1. **transcriber → 100 %*** : purger alert()/confirm() de edit.js → toast.
2. **describer** : aligner couleurs boutons card (⚙/⧉/🗑) sur la référence outline.
3. **composer** : 4 alert() → toast ; couleurs boutons card ; ⚙ visible pendant RUNNING.
4. **reader** : 2 alert() → toast.
5. **converter** : migration statuts DONE/ERROR → SUCCESS/FAILURE (pattern reader.0008) ;
   vue+bouton download_all global ; fabrique make_queue_manipulation_views ; 21 alert() → toast.
   (cross_app_options Phase 2 et modes = chantiers séparés, pas dans cette passe.)
(*) hors dettes transverses assumées : recursive_import (toutes), card v2 chips (pilote
reader à valider avant propagation), profils (capacité non déclarée), WamaModelCaps.

### 31.6 Docs remis à jour dans cette passe
- `WAMA_APP_CONVENTIONS.md` §15.1 : table figée remplacée par un pointeur vers `/apps/`.
- `UI_MECHANISMS_CONSOLIDATION.md` : contradiction P0 params.py purgée (10/10 existent,
  2 orphelins), P3 marqué fait (transcriber+converter → initFromSchema).
- `ROADMAP.md` : en-tête daté, ligne staging alignée sur CARD_DESIGN §8.5 (supprimé),
  compteurs modale WamaParams corrigés (7/10 : + enhancer, avatarizer ; hand-built :
  synthesizer, anonymizer, imager).
- `CARD_DESIGN.md` §5 : table re-mesurée ; §10.6 ProcessingTimeMixin fait (5 apps portées).
- `INSPECTOR_DETAIL_FIELDS.md` : état de rollout par app ajouté (detail 5/10, preview 8/10).

### 31.7 Exécution du plan §31.5 (2026-07-11) — FAIT
| App | Avant | Après | Actions |
|---|---|---|---|
| transcriber | 93 % | **96 %** | alert() edit.js:675 → toast (confirm() conservé = décision utilisateur, pas une notification) |
| composer | 92 % | **96 %** | 4 alert() → toast ; couleurs card alignées outline (⚙/⬇/🗑) ; ⚙ VISIBLE pendant RUNNING (le `{% if != RUNNING %}` masquait la modale en cours de traitement) |
| describer | 93 % | 93 % | couleurs card alignées (⚙ outline-secondary, ⧉ outline-warning, 🗑 outline-danger, 👁 adouci en outline-success — conservé, bouton légitime hors référence) |
| reader | 90 % | **93 %** | 2 alert() reader.js → toast |
| converter | 77 % | **87 %** | migration statuts **SUCCESS/FAILURE** (0005, appliquée WSL2, pattern reader.0008 ; sweep models/tasks/views/_job_card/converter.js = 19 littéraux) ; vue+bouton **download_all** (ZIP global, slot toolbar `converterDownloadAllBtn`) ; 21 alert() → toast typés |

Écarts restants ASSUMÉS (défauts documentés, pas des oublis) :
- `recursive_import` : dette transverse 10 apps (inchangé).
- `modes` describer/reader/converter : à trancher — vrai switch WamaModes ou N/A « dérivé »
  comme composer ? (question posée §31.4.7).
- `converter.cross_app_options` : Phase 2 planifiée (upscale/audio enhance).
- `converter.queue_manipulation` : la fabrique commune exige l'architecture batch unifiée
  (liaison + BatchMixin) que `ConversionBatch` n'a pas — batch léger = choix documenté
  (note d'intention CONV §15). Trancher le passage à BatchMixin AVANT d'adopter la fabrique.
- JS déployés dans `staticfiles/` : converter.js, reader.js, composer/index.js,
  transcriber/edit.js. ⚠ Redémarrage du process WSL2 requis pour les changements Python
  (converter views/urls/models).

Smoke tests : /transcriber/ /describer/ /composer/ /reader/ /converter/ /common/apps/
→ tous 200 (client Django, superuser).

---

## 32. Portage enhancer + synthesizer — passe « risques + mécanique » (2026-07-11)

Suite directe de §31 : les 2 apps à 70 % rapprochées de la pile commune (**83 % chacune**)
sans toucher à leur architecture de file (port complet différé, voir KO restants).

### 32.1 Fait (enhancer 70 → 83 %)
- **anti-race** : `start()` + `audio_start()` → `begin_processing` (verrou + revoke + reset
  sous verrou via callable) ; en cas d'échec de dispatch Celery, retour à PENDING.
- **ProcessingTimeMixin ×2** (migrations 0010/0011, appliquées WSL2 **et** Windows) — le champ
  legacy `processing_time` (doublon par-app, AUCUN lecteur) a été SUPPRIMÉ, tasks écrivent
  `processing_seconds` ; affichage `_processing_time.html` sur les 2 cards (média + audio).
- **Inspecteur detail** : `register_app_detail('enhancer')` + `('audio_enhancer')` avec labels
  `params.py` (MEDIA_PARAMS/AUDIO_PARAMS) — actif immédiatement car les cards avaient déjà
  `data-preview-url` (dérivation /preview/→/detail/ de wama-inspector.js).
- **13 alert() → toasts typés** ; couleurs boutons alignées outline (template ET buildCard JS
  synchronisés — double rendu CONV §5) ; classe layout `wama-queue-*` sur `#enhancer-queue`.

### 32.2 Fait (synthesizer 70 → 83 %)
- **anti-race** : `start()` → `begin_processing` (reset audio_output sous verrou).
- **ProcessingTimeMixin** (migration 0013, WSL2 + Windows) + worker (`processing_seconds` au
  SUCCESS) + affichage card.
- **Inspecteur detail** : `register_app_detail('synthesizer')` (labels params.py, alias
  output_quality) + `data-preview-url` AJOUTÉ sur `_synthesis_card.html` (manquait → preview
  et detail inspecteur inertes).
- **42 alert() → toasts** (34 index.js + 8 inline template, dont 3 en callback `.catch()` —
  piège de la parenthèse imbriquée traité individuellement) ; couleurs boutons alignées ;
  classe layout sur `#synthesisQueue`.

### 32.3 Vérifications
- Detail end-to-end : objets éphémères créés/supprimés (base Windows = copie dev) →
  `/common/detail/synthesizer/N/` et `/common/detail/enhancer/N/` = 200, schéma canonique.
- Registre detail : 8 apps (audio_enhancer, composer, converter, describer, enhancer,
  reader, synthesizer, transcriber) — manquent avatarizer, imager, anonymizer.
- Chaque `WamaApp.toast(...)` vérifié bien formé (parseur d'équilibre : 0 appel sans type).
- Smoke tests 200 : /enhancer/ /synthesizer/ /converter/ /transcriber/ /common/apps/.

### 32.4 Découverte infra IMPORTANTE
La base Windows et la base WSL2 sont **deux bases différentes et divergentes** (re-prouvé :
colonne `processing_seconds` présente en WSL2 après migrate, absente côté Windows →
`ProgrammingError`). C'était déjà documenté dans la mémoire détaillée (correction 2026-06-25)
mais le RÉSUMÉ d'index disait encore « base unique partagée » — corrigé. Règle : appliquer
les migrations DES DEUX CÔTÉS (WSL2 = live ; Windows = copie de dev pour smoke tests).

### 32.5 KO restants (port complet de la file, chantier suivant)
- enhancer : `_new_item_card` (2 domaines), `_batch_card` mère, `_queue_toolbar`+tri/filtre,
  `_cycle_button` — cf. brief §30.
- synthesizer : idem + modales WamaParams (P1 BLOCKER — params.py ne ponte que les dom_id)
  + câblage WamaModes (déclaré, inerte).
- Puis : anonymizer (prérequis champ `status`), imager (inspecteur 0/4), avatarizer (vues
  globales serveur).

---

## 33. Portage anonymizer — le prérequis « champ status » est tombé (2026-07-11)

Anonymizer **61 → 74 %**. La non-conformité la plus profonde de la grille (§31.4.6 : pas de
champ `status`, booléen `processed`) est résolue.

### 33.1 Migration de modèle (0021, appliquée WSL2 + Windows)
- `Media` gagne `status` (PENDING/RUNNING/SUCCESS/FAILURE), `task_id`, `error_message`,
  et hérite `ProcessingTimeMixin`.
- **Conversion des données AVANT drop** : la migration auto-générée droppait `processed`
  sans convertir → réécrite à la main (AddField → RunPython processed=True→SUCCESS →
  RemoveField). Vérifié sur la base live WSL2 : 18 médias → SUCCESS.
- **`processed` survit en PROPERTY dérivée** (`status == 'SUCCESS'`) : les ~50 LECTEURS
  (templates `media.processed`, JSON `'processed': m.processed`, JS) fonctionnent sans
  modification ; seuls les ~12 usages DB-level (filtres queryset, écritures,
  `update_fields`, `reset_fields` de la fabrique) ont été balayés vers `status`.
- Cycle de vie complet dans le worker : RUNNING au démarrage effectif, SUCCESS +
  `processing_seconds` à la fin (2 chemins : YOLO single-task + SAM3/parallel),
  **FAILURE + error_message sur exception** (avant : échec invisible, progression figée).

### 33.2 Aussi fait
- `register_app_detail('anonymizer')` (labels params.py — qui n'est du coup plus
  totalement orphelin ; `result_file=None` car la sortie est un chemin dérivé `_blurred_*`).
  Testé bout-en-bout : 200, schéma canonique.
- 23 alert() → toasts typés (batch/right_panel/settings_modal/update/upload.js),
  vérification parseur : 0 appel mal formé.
- Couleurs boutons card : ⚙ `btn-warning`→`outline-secondary`, ⧉ →`outline-warning`.
- Classe layout `wama-queue-*` sur `#medias` ; `status` exposé dans le JSON de liste
  (en plus de `processed` conservé).

### 33.3 KO restants anonymizer (port complet)
inspector (initFromSchema + _inspector_actions — volet droit hand-built `right_panel.js`),
modes (déclaré, non câblé), anti_race complet (pas de vue start par item — RUNNING posé par
le worker), _new_item_card/_batch_card/_queue_toolbar/_cycle_button, modale hand-built
(settings_modal.js) à migrer vers WamaParams.

### 33.4 Grille au 2026-07-11 (après §31.7 + §32 + §33)
transcriber 96 · composer 96 · describer 93 · reader 93 · converter 87 · enhancer 83 ·
synthesizer 83 · **anonymizer 74** · imager 60 · avatarizer 55.

---

## 34. Passe conservatrice imager + avatarizer (2026-07-11)

Consigne Fabien : « sans rien casser — si doute, ne pas implémenter ». Uniquement des ajouts
additifs vérifiés. **imager 60 → 66 %**, **avatarizer 55 → 68 %**.

### 34.1 Imager
- **anti-race** : `start_generation` → `begin_processing` (verrou + revoke — le modèle avait
  déjà status/task_id, drop-in propre).
- **register_app_detail('imager')** (labels IMAGE_PARAMS/VIDEO_PARAMS selon le mode) — testé
  bout-en-bout (200, schéma canonique). **PAS de register_app_preview** (décision différée :
  `generated_images` = JSON multi-images, « quelle image prévisualiser » = choix de design
  du port complet).
- **`showNotification` délègue à `WamaApp.toast`** (le doublon Bootstrap local est retiré ;
  types danger/success/info compatibles) + 3 alert() purgés.
- ⚠ Incident réparé pendant la passe : un remplacement a perdu un backslash (chaîne JS
  `l\'amélioration` cassée) — détecté immédiatement (grep du segment) et réécrit par
  construction explicite. Vérif finale : 0 alert(), parens/braces/backticks équilibrés,
  0 toast mal formé.
- **NON fait (doute assumé)** : classe layout `wama-queue-*` (cards Bootstrap larges, rendu
  mosaïque incertain) ; dédup du double markup card image/vidéo ; initFromSchema ; modale
  WamaParams ; listener wama:fileimported.

### 34.2 Avatarizer
- **3 vues serveur globales créées** : `start_all` (begin_processing par job non terminé),
  `clear_all` (remplace la boucle DELETE côté client ; MÊME nettoyage de fichiers que la
  vue delete par item — audio_input/avatar_upload/output_video ; refuse si un job RUNNING),
  `download_all` (ZIP des sorties) + URLs + boutons standards (#btn-start-all vert,
  #btn-download-all bleu) + bindings JS (le clear-all JS appelle désormais la vue serveur).
- **anti-race** : `start` → `begin_processing` (le statut passe RUNNING à l'acceptation,
  comme partout — avant : PENDING posé en vue, RUNNING par le worker).
- **register_app_preview** (aperçu = `avatar_upload`, l'identité visuelle du job) +
  **register_app_detail** (labels params.py) — testés bout-en-bout (200 ; preview sans
  fichier → « No file available » propre).
- **Ordre boutons card corrigé** : ⚙ AVANT ↻ (seule app dans le mauvais ordre) + couleurs
  outline canoniques (template + buildCard JS synchronisés) ; 21 alert() → toasts typés.
- Vérifs : `manage.py check` 0 issue ; smoke 200 (/avatarizer/ /imager/) ; parseur toasts
  0 mal formé.

### 34.3 Grille au terme de la session (audit §31 → §34)
| | avant audit | après |
|---|---|---|
| transcriber | 86 | **96** |
| composer | 94 | **96** |
| describer | 72 | **93** |
| reader | 82 | **93** |
| converter | 75 | **87** |
| enhancer | 69 | **83** |
| synthesizer | 63 | **83** |
| anonymizer | 60 | **74** |
| avatarizer | 57 | **68** |
| imager | 63 | **66** |

Prochaines marches (dans l'ordre de rendement) : port complet de la file enhancer/synthesizer
(brief §30/§32.5) ; inspecteur imager (preview multi-images = décision design) ; anonymizer
initFromSchema + modale WamaParams ; avatarizer briques de file.

---

## 35. Avatarizer — card d'entrée commune en tête de file (2026-07-11)

Demande Fabien : « la card d'entrée en en-tête de file comme pour les applications portées ».
**Avatarizer 68 → 72 %.**

### 35.1 Ce qui a bougé
- La COLONNE GAUCHE de saisie (onglets Pipeline/Standalone + textarea + dropzone audio +
  galerie d'avatars) est SUPPRIMÉE ; la file passe en pleine largeur (col-12).
- `common/_new_item_card.html` incluse en tête de file (avant `#jobs-container`) :
  - prompt = texte de la consigne (`#text_content`, compteur de mots conservé) ;
  - dropzone = audio prêt (`#audio-dropzone`/`#audio_input`) + bouton Médiathèque (audio) ;
  - bouton primaire = `#btn-generate` « Générer la vidéo » (déplacé du volet droit — action
    primaire de la card, CARD_DESIGN §2 ; passe de bleu à vert conventionnel) ;
  - galerie d'avatars + badge audio retenu via le NOUVEAU slot `extra_zone_template`
    (`avatarizer/_new_item_extra.html`).
- **Tous les ids historiques conservés** → les handlers de index.js (drop texte/audio,
  word count, sélection avatar, remove audio, generate) fonctionnent sans réécriture.
- Onglets Pipeline/Standalone supprimés : le radio `workflow_mode` du volet droit était DÉJÀ
  la source unique du mode (`getMode()`) — les onglets n'étaient qu'une vue synchronisée.
  Le sync mort a été nettoyé ; l'import audio depuis le filemanager bascule maintenant le
  radio directement (avant : il cliquait l'onglet).
- `data-wama-app="avatarizer"` posé à l'init JS sur les 2 zones (le partial ne le rend pas ;
  requis par le quick-drop filemanager `getAppFromDropZone` → dataset).

### 35.2 Extension DÉCLARÉE du partial commun (3 slots opt-in, documentés dans son en-tête)
1. `prompt_zone_id` — id posé sur le conteneur du prompt (permet aux apps d'y brancher un
   drop de fichier texte). 2. `prompt_counter_id` — span compteur de mots sous le prompt.
3. `extra_zone_template` — template d'app inclus en fin de zone médiane (spécificité
   déclarée, hérite du contexte). Aucun impact sur les consommateurs existants (ifs gardés).

### 35.3 Vérifications
- Rendu : 200 ; card présente ; ids uniques ×1 (0 doublon `#btn-generate`) ; 13 avatars de
  la galerie rendus DANS la card ; card avant la file ; onglets et col-md-5 absents.
- ⚠ Récidive n°5 du piège commentaire Django `{# #}` multi-lignes (dans MES ajouts) —
  détectée et corrigée en `{% comment %}` + re-scan du fichier (0 restant). Le réflexe
  d'écriture reste le point faible : TOUJOURS `{% comment %}` pour tout commentaire ≥ 2 lignes.

---

## 36. Avatarizer STANDALONE-ONLY (décision Fabien, 2026-07-11)

> « On peut basculer l'avatarizer en standalone seul, comme on utilisera le synthesizer +
> avatarizer dans le studio pour le pipeline. » — concrétise R16/§20bis (pipeline = axe
> WORKFLOW de la méta-app, pas un mode d'app).

### 36.1 Retiré de l'UI (création)
- Radios `workflow_mode` + bloc `#pipelineSettings` (TTS : modèle/langue/voix) du volet droit.
- Prompt texte de la card d'entrée (la card devient : dropzone audio « voix de l'avatar »
  + Médiathèque + galerie d'avatars + Générer).
- JS : `getMode()` figé à `'standalone'` ; branches pipeline de `createJob`/
  `updateGenerateButton` supprimées ; bloc mort du drop de texte (~90 lignes,
  extractTextViaServer/loadTextIntoArea) purgé après vérification qu'aucun symbole n'était
  utilisé ailleurs ; CSS `#text-dropzone` mort retiré.
- Vue `create()` : défaut serveur `mode='standalone'`.

### 36.2 INTACT (backend + historique)
- Modèle : champ `mode`, champs TTS ; worker pipeline ; **batch** (les fichiers batch à
  lignes texte→pipeline restent acceptés — à re-trancher quand le studio orchestrera) ;
  tool_api ; AFFICHAGE des jobs pipeline historiques (cards, modale section pipeline,
  label « Mode » du detail inspecteur via params.py — la déclaration `mode` du schéma est
  conservée pour ça, son câblage radio absent est null-gardé).

### 36.3 Vérifications
Rendu 200 ; 0 résidu `pipelineSettings`/`text_content`/`text-dropzone` ; réglages MuseTalk
(quality_mode/bbox_shift/enhancer) intacts ; `manage.py check` 0 issue ; garde-fou avant
purge du bloc mort : grep de chaque symbole → 0 usage externe.

---

## 37. Studio — persistance + EXÉCUTION réelle de pipelines (2026-07-11)

Les deux ⏳ du §15 sont livrés. Cas phare : **synthesizer → avatarizer** (concrétise la
décision §36 : le pipeline texte→TTS→avatar EST une composition studio).

### 37.1 Architecture
- **`studio/models.py`** : `StudioPipeline` (graphe nommé JSON, unique par user+nom) ;
  `StudioRun` (graphe figé, statut, `node_states` par nœud, ProcessingTimeMixin).
  Migration 0001 appliquée WSL2 + Windows.
- **`studio/services/runners.py`** : adapters d'exécution par app — triade canonique
  `create(user, inputs, params) → item_id` / `start` / `poll → {status, progress, output}`,
  branchée sur **`wama/tool_api.py`** (philosophie : chaque app expose son API à la
  méta-app ; le traitement tourne dans le Celery de l'APP, le studio orchestre).
  `params_spec` déclaratif par app → l'UI des params de nœud est GÉNÉRÉE (métadonnée-driven).
  Ajouter une app exécutable = ajouter une entrée RUNNERS, zéro logique d'orchestration.
- **`studio/tasks.py`** : `run_pipeline_task` — ordre TOPOLOGIQUE (refus des cycles),
  chaînage des sorties par type de port (audio→audio…), timeout 30 min/nœud, états par
  nœud persistés à chaque étape, console `app='studio'`, notification fin de run.
- **Vues/URLs** : `/studio/api/pipelines/` (GET liste, POST upsert), `/pipelines/<id>/`
  (GET graphe, DELETE), `/run-options/` (params_specs + galerie d'avatars), `/run/`
  (validations AVANT dispatch : cycle, apps non exécutables), `/run/<id>/` (polling).

### 37.2 UI (wama-studio.js + index.html)
- Toolbar : nom + 💾 Sauvegarder + select Charger + ▶ Exécuter + statut de run.
- Sérialisation/restauration du graphe (positions, params, liens par groupe de port).
- Params d'exécution du nœud sélectionné rendus dans l'inspecteur depuis `params_spec`
  (texte/langue/voix du synthesizer ; avatar (liste réelle de la galerie)/mode avatarizer).
- Pendant le run : polling 2,5 s → liseré JAUNE (running) / VERT (success) / ROUGE
  (failure) sur chaque nœud ; toast + durée à la fin.

### 37.3 Validations empiriques
- Endpoints testés (client Django) : save/load/list/delete 200, run→400 sur graphe
  cyclique et sur app non exécutable (messages clairs), run-options renvoie la vraie
  galerie (avatar_1.jpg…).
- **Moteur testé à blanc** (runners simulés, sans GPU) : ordre topo respecté, la sortie
  `synthesizer/out.wav` arrive sur l'entrée `audio` du nœud avatarizer, node_states
  corrects, run SUCCESS + processing_seconds + notification.
- ⚠ Exécution RÉELLE à valider en usage (requiert redémarrage WSL2 : nouveau module
  studio/tasks.py à découvrir par Celery + modèles TTS/MuseTalk chargés).

### 37.4 Limites V1 (assumées, consignées)
- Runners : synthesizer + avatarizer seulement (l'erreur guide : « V1 : synthesizer,
  avatarizer »). Les nœuds-source builtin (prompt_batch, media_import) ne sont pas
  exécutables — les entrées initiales viennent des params de nœud.
- Chaîne = graphe acyclique quelconque mais UNE valeur par type de port en entrée ;
  pas de fan-out parallèle (exécution séquentielle).
- Les sorties restent dans les files des apps (pas encore de dossier studio dédié).

### 37.5 Cards d'entrée / de sortie + inspecteur complet (2026-07-12)
Réponse au manque pointé par Fabien (« cards d'entrées de tous les types + médiathèque,
inspecteur fonctionnel, cards de sorties ») :
- **Nœud « Texte »** (source exécutable) : texte/prompt saisi dans l'inspecteur → port
  `prompt` (consommé par synthesizer ; demain imager/composer).
- **Nœud « Médias importés »** : désormais CONFIGURABLE — bouton « Choisir dans la
  médiathèque » (MediaPicker COMMUN) dans l'inspecteur ; catégorie du média résolue
  côté serveur (extensions app_registry) → typage de port correct à l'exécution.
- **Nœud « Sortie »** (terminal, sans port aval) : range le résultat final dans la
  MÉDIATHÈQUE — UserAsset RÉEL (fichier copié dans son stockage, nom dédoublonné,
  mime via mime_utils commun), nom + type d'asset configurables dans l'inspecteur.
- **Runner converter** ajouté (3e app exécutable) : « configurer le FORMAT de sortie »
  = chaîner un nœud converter (format + qualité dans l'inspecteur) ; type de port
  produit résolu dynamiquement du format demandé (`output_type_fn`).
- **Inspecteur = configurateur pour TOUS les nœuds** : specs servies par
  `/studio/api/run-options/` (runners + nœuds intégrés), rendu générique
  (textarea/select/text/media_picker).
- Testé à blanc de bout en bout : Texte → synthesizer(mock) → avatarizer(mock, fichier
  réel) → Sortie → **UserAsset créé dans la vraie médiathèque** (chemin
  media_library/<user>/assets/), texte bien reçu en amont, states par nœud corrects.
- Reste connu : prompt_batch (source multi-prompts) non exécutable (attend le runner
  imager + la sémantique batch dans un pipeline) ; sorties texte (futurs runners
  transcriber/describer) : le sink attend un fichier — à traiter avec ces runners.

### 37.6 Les 10 apps généralistes exécutables dans le studio (2026-07-12)
- **RUNNERS 3 → 10** : + transcriber, describer, reader (sorties TEXTE), composer
  (prompt→audio), enhancer, imager (types AUTO — catégorie du fichier produit),
  anonymizer (sortie = chemin dérivé `_blurred_*`, même logique que download_media).
- **Extension du contrat d'exécution** : `poll` peut retourner `is_text` (la valeur
  circule comme texte, pas comme fichier) ; `output_type: 'auto'` = catégorie du
  fichier produit (app_registry) ; le nœud Sortie a une variante TEXTE (écrit un
  `.txt` en médiathèque, type `document`).
- **`start_composer` AJOUTÉ au registre central `wama/tool_api.py`** (la triade
  create/start/status était incomplète — compose_music créait sans pouvoir lancer) ;
  begin_processing + compose_task, conforme au pattern des autres.
- **Vérification EMPIRIQUE des signatures** avant écriture : 4 écarts corrigés
  (transcriber sans kwarg language ; describer output_format/output_language ;
  reader backend ; composer model — défaut musicgen-small préservé) + ai_model
  enhancer aligné sur la vraie clé (RealESR_Gx4).
- Chaînes testées à blanc : Médiathèque→transcriber→Sortie (.txt RÉEL en médiathèque,
  contenu vérifié) ; Texte→imager→enhancer→Sortie (types auto, asset image).
- `/studio/api/run-options/` sert 13 specs (10 apps + Texte/Médiathèque/Sortie) ;
  messages d'erreur du run dynamiques depuis RUNNERS.
- Nouvelles compositions possibles : re-voicing (transcriber→synthesizer),
  sous-titrage différé (transcriber→Sortie txt), OCR→lecture audio
  (reader→synthesizer), prompt→image→amélioration→médiathèque, floutage→conversion…

### 37.7 Contrat uniforme : gel du shim, preview E/S, runner générique (2026-07-12/13)
Recadrage Fabien : « le studio consomme le CONTRAT, jamais l'état courant des apps »
(mémoire feedback_studio_uniform_contract + STUDIO_VISION « principe directeur »). Exécuté :
1. **runners.py = shim V1 GELÉ** (bandeau interdiction d'étendre) ; spec du contrat d'app
   exécutable consignée (STUDIO_VISION : 4 éléments, tous du contrat commun).
2. **Preview ENTRÉE/SORTIE générique** (toutes apps, zéro code par app) :
   `unified_preview ?side=` + méta `sides` (dérivées de `result_file` canonique du detail) ;
   inspecteur : défaut intelligent (SUCCESS→sortie), toggle [Entrée|Sortie], mode
   **Comparer** (slider image/image V1). Fix au passage : `DetailRegistry.get()` renvoie
   {model, adapter}. Testé : converter (comparable), synthesizer (toggle audio), 8 pages 200.
3. **Runner GÉNÉRIQUE** (`generic_runner.py`) piloté par le contrat : create =
   `add_to_<app>` avec params FILTRÉS PAR INTROSPECTION de signature + coercition par type
   du schéma ; poll = clés canoniques du detail + `progress` modèle ; params de nœud =
   POINTEUR vers …PARAMS_JSON de l'app (mapping de forme, jamais de copie).
   **Pilote : enhancer** — triade normalisée (`item_id` ajouté au retour d'add_to_enhancer),
   adapter manuel SUPPRIMÉ du shim (1/10 vidé). Testé empiriquement : spec 3 params depuis
   params.py, création réelle tool_api (param inconnu filtré, toggle coercé), poll
   PENDING→SUCCESS avec sortie.
   Prochaines normalisations (déjà proches du contrat) : transcriber/describer/reader —
   il leur faut la clé `item_id` + `result_text` au schéma canonique du detail (sorties texte).

### 37.8 Normalisation transcriber/describer/reader → runner générique (2026-07-13)
- `item_id` ajouté aux retours `add_to_transcriber`/`add_to_describer` (reader l'avait) ;
- **`result_text` = nouvelle clé CANONIQUE du detail** (build_detail +
  INSPECTOR_DETAIL_FIELDS), servie par les 3 adapters → les sorties TEXTE sont chaînables
  par le contrat (transcriber→synthesizer, reader→synthesizer, →Sortie .txt) ;
- generic_runner : poll texte (`is_text`) ; **shim vidé 4/10** (enhancer + les 3) ;
- 🐛 **bug préexistant réparé** (découvert par le test empirique du runner) :
  `add_to_describer` passait `output_format=` au constructeur alors que le champ modèle
  est `output_style` — le tool était cassé pour l'assistant aussi.
- Restent au shim : synthesizer, avatarizer, converter, composer, imager, anonymizer
  (créations non-fichier ou signatures spéciales : prompt d'entrée, convert_file
  auto-start, sortie dérivée anonymizer, multi-images imager).

### 37.9 Entrées PROMPT génériques → synthesizer/composer/imager (2026-07-13)
- Aliases NORMALISÉS `add_to_synthesizer`/`add_to_composer`/`add_to_imager` dans le
  registre central (`@functools.wraps` → la signature réelle reste introspectable pour
  le filtrage de params ; clé UNIFORME `item_id` ; les façades historiques de
  l'assistant inchangées).
- `generic_runner` : `primary_input='prompt'` — prompt résolu des entrées typées
  (nœud Texte, sorties texte transcriber/reader…) avec repli params ; clés consommées
  exclues des kwargs.
- imager : clé canonique `result_file` COMPLÉTÉE dans son adapter detail (vidéo OU
  1re image de `generated_images`) — bénéficie aussi à la preview Sortie de l'inspecteur.
- **Shim vidé 7/10.** Restent (raisons identifiées) : avatarizer (double entrée
  audio+avatar), converter (convert_file auto-start, nom non normalisé), anonymizer
  (sortie dérivée sans champ modèle — le vrai fix est un champ output_file, item de
  portage).
- Testés : création réelle par prompt ×3 (coercitions duration/width/height vérifiées),
  poll SUCCESS avec sortie canonique, specs 7/5/8 params depuis params.py.

### 37.10 Shim SUPPRIMÉ — 10/10 apps sur le runner générique (2026-07-13)
- **converter** : alias normalisé `add_to_converter` (item_id) + `auto_start` DÉCLARÉ au
  manifeste (convert_file dispatche à la création → start no-op).
- **avatarizer** : vocabulaire manifeste étendu — `input_kwarg='audio_path'` +
  `fixed_kwargs={mode: standalone, avatar_source: gallery}` (spécificité déclarée, pas
  codée) ; l'avatar vient d'une `extra_params_spec` (à résorber en l'ajoutant au
  params.py de l'app avec options_source).
- **anonymizer — ITEM DE PORTAGE réalisé** : champ `Media.output_file` (migration 0022
  WSL2+Windows avec BACKFILL — 1re version same-dir = 0/18, dérivation RÉELLE
  `<user>/output/<base>_blurred*` = **17/18** sur la base live, le 18e n'a plus de
  fichier) ; posé au SUCCESS par le worker (2 chemins YOLO/SAM3) ; detail expose enfin
  `result_file` canonique (⇒ preview Sortie inspecteur aussi).
- **`runners.py` = façade de 25 lignes** (résolution + historique) ; toute la logique
  dans generic_runner (manifeste GENERIC_APPS, 10 apps + vocabulaire déclaré :
  primary_input/input_kwarg/fixed_kwargs/auto_start/extra_params_spec).
- 🐛 Trou de validation trouvé au smoke final : un nœud d'app inconnue SANS amont était
  toléré comme « source » alors qu'il alimentait un aval (run dispatché pour échouer à
  l'exécution) → un nœud non exécutable ne peut plus être connecté NI en amont NI en
  aval ; runs parasites purgés (2 bases).
- Tests : avatarizer (mode standalone forcé, avatar, audio via input_kwarg, poll vidéo),
  anonymizer (vraie image PIL — le tool valide les fichiers —, poll output_file
  canonique, 17 params de son params.py), converter (start no-op) ; 13 specs servies ;
  pages 200.

### 37.11 Fix inspecteur studio : sélection par délégation + zéro échec silencieux (2026-07-15)
Symptôme (Fabien) : clic sur une card-nœud → inspecteur vide. Diagnostic empirique :
l'hôte existe dans le DOM ; le rendu (WamaDetails, brique commune description-driven)
est conforme au contrat ; les VRAIES causes étaient dans le câblage spécifique :
1. la sélection n'était câblée que sur l'EN-TÊTE du nœud (mousedown de la poignée de
   drag) — cliquer le corps de la card ne faisait RIEN ;
2. toute erreur d'inspecteur était AVALÉE (`try{selectNode()}catch{/*non bloquant*/}`
   + catch « Inspecteur indisponible » sans trace) ;
3. hôte disparu (interférence d'un autre script sur le volet droit) → retour silencieux.
Refonte (« on réutilise le commun, on retire le spécifique ») :
- sélection par DÉLÉGATION au clic sur TOUT le nœud (pattern commun des apps), fond
  (canvas/SVG) = désélection — l'ancien couple mousedown-head + click-fond supprimé ;
- erreurs VISIBLES (message dans le volet + console.error) ; hôte manquant →
  RECRÉÉ dans #global-settings-container + console.warn (interférence diagnosticable) ;
- le rendu reste 100 % WamaDetails (renderSections/renderActions, schéma déclaratif) +
  params de nœud générés des specs — rien de spécifique ajouté.
⚠ À revalider navigateur (hard-refresh inutile : static_v cache-bust). Si un message
« Inspecteur en erreur : … » ou un warn [WamaStudio] apparaît → me le remonter tel quel.

### 37.12 CAUSE RACINE de l'inspecteur studio vide — trouvée par exécution V8 (2026-07-15)
Le fix 37.11 (délégation + erreurs visibles) a fait apparaître une régression (palette
« Chargement… ») qui a mené à la VRAIE cause, prouvée en exécutant le script dans V8
(mini-racer + DOM stub) :
- **`global` n'a JAMAIS été défini dans wama-studio.js** (IIFE sans paramètre, contrairement
  aux briques communes `(function (global) {...})(window)`).
- Le check historique `!node || !global.WamaDetails` ne survivait au chargement que par
  COURT-CIRCUIT (`!node` vrai quand rien n'est sélectionné). Au CLIC (node défini),
  `global.WamaDetails` → ReferenceError → avalé par le try/catch silencieux du mousedown
  → **inspecteur vide depuis le premier jour du squelette**.
- Mon warn de 37.11 évaluait `global.…` inconditionnellement dans init() → init plantait
  avant le fetch du catalogue → palette bloquée (le symptôme rapporté).
Fix : IIFE au pattern commun `(function (global) {...})(window)`. Vérifié dans V8 : init
complet (3 fetches), plus d'erreur, WamaDetails réel chargé et détecté.
**Outillage durable** : `esprima` (syntaxe) + `mini-racer` (runtime V8 + DOM stub)
installés — désormais TOUT edit JS passe par ces deux vérifications (l'équilibre de
parenthèses ne détecte ni les ReferenceError ni les pièges de portée). Consigné en mémoire.

### 37.13 MediaPicker au studio + brouillon PERSISTANT du canvas (2026-07-15)
1. **« Médiathèque indisponible »** : media-picker.js est bien chargé globalement
   (base.html:270) mais exporte via `const MediaPicker = …` au top-level = binding
   lexical global, PAS `window.MediaPicker` — mon garde testait window.* → toujours
   faux. Fix : détection par identifiant (`typeof MediaPicker !== 'undefined'`).
   (NB : le prérequis ML_LIST_URL a un fallback interne vers /media-library/api/assets/.)
2. **Brouillon persistant** (demande Fabien : ne plus perdre le graphe en changeant
   d'app) : autosave localStorage (`wama_studio_draft`, graphe + nom) à CHAQUE mutation
   (ajout/suppression nœud, lien, drag, params, choix médiathèque) ; restauration à
   l'init APRÈS le catalogue ; « Vider le canvas » purge le brouillon (geste explicite) ;
   la sauvegarde en pipeline garde le brouillon synchronisé.
3. Validé dans le harnais V8 (fetch résolvant + localStorage préchargé) : 2 nœuds + nom
   restaurés, hooks réécrivent le brouillon, zéro warn. Deux gaps de STUB corrigés au
   passage (style.setProperty, querySelector→El neutre) — le catch de restauration est
   volontairement BAVARD (console.warn) comme le reste depuis 37.12.
4. **Harnais pérennisé** : `wama-dev-ai/tools/js_v8_harness.py <script.js>` (esprima +
   mini-racer) — référencé en mémoire.

### 37.14 Fix enregistrement pipeline studio : CSRF (403) (2026-07-15)
Symptôme : « Unexpected token '<' … is not valid JSON » + POST 403 à
/studio/api/pipelines/. Double cause dans la fonction `api()` de wama-studio.js :
1. `WamaApp.csrfHeaders()` appelé SANS argument — or sa signature est
   `csrfHeaders(csrfToken, extra)` → envoyait `X-CSRFToken: undefined` → 403 Django ;
2. `r.json()` sur la page d'erreur HTML → « Unexpected token '<' » (message opaque).
Fix : `api()` lit le vrai token (input `csrfmiddlewaretoken` sinon cookie `csrftoken`),
`credentials:'same-origin'`, et détecte les réponses non-JSON pour un message CLAIR
(403 → « Session expirée ou accès refusé »). Vérifié serveur (Client CSRF strict) :
token présent au HTML + cookie posé, POST avec token → 200 (pipeline créé/nettoyé).

### 37.15 Studio : animation de flux sur les câbles pendant l'exécution (2026-07-17)
Demande Fabien : montrer la donnée qui transite entre 2 cards pendant un run.
- Un point cyan lumineux circule le long d'un câble tant que son nœud CIBLE est RUNNING
  (= la donnée entre dans la card en cours de traitement) ; le câble s'illumine aussi.
- Pur SVG, dans l'esprit vanilla du studio : `<circle><animateMotion><mpath href="#linkpath-<id>"/>`
  → le point SUIT le tracé du câble (et le suit même si le nœud est déplacé, car mpath
  référence la path vivante). Aucune dépendance.
- Piloté par les ÉTATS RÉELS du run (pollRun/node_states) via updateFlows ; coupé en fin de
  run et par clearRunStates. Chaque path de lien porte désormais un id (`linkpath-<id>`).
- Validé : esprima + harnais V8 (init 0 erreur) + test unitaire isolé de setLinkFlowing
  (structure circle>animateMotion>mpath[href] correcte, ON/OFF). Harnais pérenne complété
  (style.setProperty, document.cookie/querySelector/createElementNS, fetch headers).

## 🌍 Architecture en MONDES (doctrine 2026-07-20)
WAMA = 4 mondes (Médias / Data / Lab / Transversal) qui communiquent via le système de capacités/ports typés, peuplent studio + médiathèque. **Accès sur 3 axes** : tier + rôles métier + **appartenance organisationnelle** (arbre institut/université→département→labo/service→équipe→utilisateur). Cet arbre = **le même que les niveaux d'héritage RAG** → un seul modèle `OrgUnit`, 3 usages (héritage RAG, scopes de partage, gating d'accès), à ne pas dupliquer. ✅ **Points 1-3 faits (35073dd)** : `OrgUnit` (arbre common), médiathèque `UserAsset(ScopedVisibility)` + API promote, `UserFunction` (confidentialité). LDAP/SUPANN remonté au login (6ebeffe). Détail : `docs/VISION_STATUS.md` §MONDES (⚠ docs/ non versionné). Catalogue : `/model-manager/functions/`.

## 23. Entrée URL unifiée + ingest média commun + Converter HTML→PDF (session 2026-07-22/23)

Chantier « entrée URL » mené jusqu'au bout, dans l'esprit *manifeste descriptif → ingest commun → UI générée*.

**23.1 Card d'entrée URL = formalisme batch (converter, describer, transcriber).**
Une URL saisie dans la card = un batch d'1 ligne → même parseur (`parse_media_list_batch`, accepte
http/https/file://, chemins Unix/Windows) et même consolidation en card unité/batch qu'un fichier batch.
Briques communes **JS** ajoutées : `WamaApp.initUrlImport` (mode `onSubmit`/`onEmpty`, `wama-app-base.js`)
+ `WamaBatchImport.ingestText(text, filename)` (`batch-import.js`). L'app ne fait que *déclarer*
(`show_url=True` + un `onSubmit → _batchImport.ingestText`). Les handlers URL dupliqués (fetch/CSRF)
supprimés des 3 apps.

**23.2 Lecture de page web + ingestion URL portées au commun.**
`common/utils/url_ingest.py` (extrait du describer, où c'était dupliqué views⟷workers) :
`html_to_readable_text` (page web → texte, BeautifulSoup), `fetch_html_as_text`, `fetch_url_content`
(URL → fichier local : page web → texte / média → download + sniff HTML). Describer délègue via alias
rétro-compat. **Lecture de page web complète PRÉSERVÉE** (à améliorer plus tard). Tous les types conservés
(image/vidéo/audio/document/page web).

**23.3 Ingest média DÉCLARATIF commun (`ensure_local_input`) — comble le plug du trou #14.**
`common/utils/source_ingest.py::ensure_local_input(instance)` piloté par un attribut modèle
`WAMA_INGEST = {source, target, mode: media|audio|smart, name_field?, size_field?, title_field?}`
(stopgap avant la facette manifeste F5). Télécharge `source_url`→FileField via la bonne primitive commune.
**Les 2 wrappers describer/transcriber fusionnés dessus** (le transcriber **crashait** faute de ce maillon :
`batch_create` stockait `source_url` sans jamais le télécharger). Aucune migration (attribut de classe).
→ Adopter l'URL sur une app = déclarer `WAMA_INGEST` + appeler `ensure_local_input` en tête de tâche.
**Côté manifeste : ✅ FAIT 2026-07-23 (b5edbc4)** — capacité **F2** `accepts_url` (dérivée de
`has_url_import` ∪ présence d'un `WAMA_INGEST`) + facette **F5** `ingest:{…}` (extract-only pour
l'instant). **Reste** : la projection F5 en **write-back** vers `WAMA_INGEST` + adoption sur les
apps sans `WAMA_INGEST`. Voir `WAMA_APP_GENERATION_ROUTE.md §11` trou #14.

**23.4 Download HTTP : nommage fiable.**
`video_utils._filename_from_response` : Content-Disposition (filename*/filename UTF-8) → basename URL →
extension déduite du Content-Type. Fini le fallback trompeur `video.mp4` pour documents/pages sans nom.

**23.5 Converter HTML→PDF — route à 3 étages Chromium → WeasyPrint → pandoc.**
Chronologie des correctifs :
(a) D'abord routé via **WeasyPrint** (moteur CSS, SVG inline) au lieu de pandoc→xelatex qui jetait le
CSS et exigeait `rsvg-convert` absent (`Pandoc exitcode 43`). Dépendance `weasyprint==69.0`.
(b) **Pages blanches** : les pages web animent leurs sections en `opacity:0` révélées par JS
(IntersectionObserver / AOS / `.reveal`) ; WeasyPrint (pas de JS) → sections invisibles. Fix commun :
feuille d'impression `_REVEAL_SELECTORS_CSS` forçant visible `reveal/fade/scroll-/aos/wow`.
(c) **Mise en page cassée** (WeasyPrint ne fait pas `clamp()`/`place-items`/grilles larges → titres
riquiqui, 4ᵉ colonne coupée) : c'est une limite de fond. Route **préférée = Chromium headless
(Playwright)** — CSS moderne complet + JS + **breakpoints responsive** (`emulate_media('screen')`) → la
page reflow dans A4 sans coupe. `_html_to_pdf_chromium` : viewport 820, `add_style_tag` reveals, scroll
intégral (déclenche l'IntersectionObserver), `page.pdf(A4, print_background)`. **WeasyPrint reste le
fallback**, pandoc en dernier. Vérifié : `wama_fiches.html` 4 pages, fidèle, 0 vide, 0 coupe.

**Rangement (MAJ 2026-07-24, 1329638) : brique COMMUNE + navigateur hors AI-models.**
- Le rendu HTML→PDF (Chromium→WeasyPrint) est **extrait dans `common/utils/html_render.py`**
  (`render_html_to_pdf`) — capacité générique réutilisable (converter, describer web-page, exports). Le
  converter ne fait que l'appeler ; pandoc reste son dernier fallback local.
- Chromium **n'est PAS un modèle** → sorti d'`AI-models/browsers` (erreur de rangement corrigée) vers le
  **cache Playwright par défaut** `~/.cache/ms-playwright` (régénérable, zéro env custom, zéro gitignore).
  `tools/` = dossier de scripts (pas de binaires) → pas touché.

**Déploiement Chromium (important — `requirements` NE SUFFIT PAS).** `pip install playwright` ≠ navigateur.
Provisioning automatisé **dans `start_wama_prod.sh` + `start_wama_dev.sh`** (idempotent, non bloquant,
marqueur `~/.cache/ms-playwright/.wama-os-deps-ok`) : `python -m playwright install --with-deps chromium`
(télécharge le binaire dans le cache par défaut + libs apt via sudo). Serveur neuf :
`pip install -r requirements_linux.txt` → `./start_wama_prod.sh` suffit (provisionne au 1ᵉʳ lancement ; si
échec réseau/sudo → fallback WeasyPrint, pas de plantage). NB Playwright 1.61 : `chrome-headless-shell`
(dl séparé, KO derrière proxy) → le code cible le **Chromium complet** via `executable_path`
(`_find_chromium_executable`).

**23.6 Trou (côté manifeste) — dépendances : volet LIBRAIRIES CLOS, reste `system_tools`.**
*(MAJ 2026-08-11 — l'énoncé d'origine disait « ni librairies ni outils système » ; le volet
librairies a été livré depuis.)* **Clos** : `requires:{kind:library}` déclaré dans l'ENVELOPPE
(`envelope.py:45`), résolu et bloquant (`ingest.resolve_requires`), kind `library` + registre
`common.models.Library` nés de la projection (`write_back_library`), 1er lien réel
transcriber→faster-whisper, inventaire `library_index`/`library_candidates`. **Reste** : les
**outils système** (binaire Chromium, ffmpeg, rsvg…) — provisioning encore hard-codé (bloc
Chromium dans `start_wama_prod.sh`) au lieu d'être dérivé d'une déclaration `system_tools`, et le
**provisionneur commun** lisant l'union des déclarations (ex. converter/describer déclarent
« browser-render (chromium) », la capacité est fournie par `common/utils/html_render`).
→ consigné comme **trou #15** dans `WAMA_APP_GENERATION_ROUTE.md §11` (fait le 2026-08-11 —
l'ancienne note « à ajouter » n'avait jamais été exécutée).

**⏳ Validation navigateur (Fabien)** : à faire après restart worker Celery + serveur web WSL2 — converter
(PDF #43, card URL), describer (URL média/page web), transcriber (URL YouTube/lien direct → audio).

---

## 38. Socle des manifestes (2026-07-21→23) — synthèse

> Docs de référence : `WAMA_MANIFEST_SPEC.md` (formalisme) + `WAMA_MANIFEST_ARCHITECTURE.md`
> (flux/schéma) + `WAMA_APP_GENERATION_ROUTE.md` (route F1–F8). Le détail vit LÀ-BAS, pas ici.

- ✅ Enveloppe + registre de kinds + ingest idempotent (`common/manifests/` : envelope/kinds/ingest)
- ✅ **7 kinds** : app, model, dataset, pipeline, project, function (84aa35e → 87d6a80) +
  **library (2026-08-03, `80fec09`)** — kind pilote : son registre `common.models.Library` NAÎT
  de la projection
- ✅ Extracteur `app` (8 facettes fonctionnelles = 12 clés `APP_FACETS`), via les accesseurs
  PARTAGÉS `studio_node_ports`/`app_capabilities` (contrat de jonction respecté, 4038301)
- ✅ Projection **dry-run + rapport d'écarts** (`manifests/projection.py`, 391eacc)
- ✅ **1ʳᵉ projection write-back réelle : `access` → `AppAccessPolicy`** (idempotente/réversible,
  a75c01d, 2026-07-23)
- ✅ Trou #14 côté manifeste : capacité F2 `accepts_url` + facette F5 `ingest` en extract (b5edbc4)
- ✅ Write-back réel sur **3 kinds** (app/`access`, library=registre entier, model=`license`/
  `platform_ref`) — hooks renommés `write_back`/`un_write_back` le 2026-08-05
- ⏳ Code-gen des **9** facettes d'app restantes (`codegen_required`) ; trou #15 réduit à
  `system_tools` (§23.6, MAJ 2026-08-11)

## 39. Couche WAMA Data (2026-07-20→22) — synthèse

> Doc de référence : `WAMA_DATA_FUNCTION_CARDS.md` (⚠ à resynchroniser : il précède le
> refactoring par domaine).

- ✅ Socle `common/data/` : `data_types.py` (10 DataType + `TypedFrame`) + `function_catalog.py`
  (capability-first) + page `/model-manager/functions/` (cards, tri/filtre, projet, confidentialité)
- ✅ **Consolidation 2026-07-22 (9945ca8/a06f3be)** : `common/rtmaps/` et `common/prediction/`
  SUPPRIMÉS — tout vit sous `common/data/functions/{driving,geometry,io,kinematics}/` (axe DOMAINE,
  orthogonal à data_type/category) ; cam_analyzer réaligné (tasks/views/prediction_adapter)
- ✅ 19 fonctions au catalogue (5 pures dont `placement_spread` b779395 + 14 app-bound
  `cam_analyzer.*`) ; les libs helper (io/geometry.shapes/kinematics) restent hors catalogue
- ⏳ UI de chaînage (canvas), exposition `tool_api` du catalogue

## 40. Backlog repris du handoff REPRISE_2026-07-22 (archivé 2026-07-25) — état re-vérifié

> Les 6 items « à reprendre » du handoff, TOUS encore ouverts au 2026-07-25 (vérif agents).
> Les 2 duplications (ex-items 2 et 4) sont tracées en `REMOVAL_LEDGER R18/R19`.

1. ⏳ **`describer.result_file` orphelin** : retrait en passe ISOLÉE (migration describer.00xx sur
   les DEUX bases) — ~32 occurrences restantes (views 17, models 3).
2. ⏳ **`common/_result_tabs.html`** : cf. `REMOVAL_LEDGER R18`.
3. ⏳ **Streaming MusicGen mid-génération** : `audiocraft_backend.on_audio` n'est appelé qu'UNE fois
   en fin de génération — pas de token-callback ; `emit_streaming_peaks` prêt côté tasks.
4. ⏳ **Fusion des 2 renderers waveform** : cf. `REMOVAL_LEDGER R19` (calcul déjà unifié).
5. 🔶 **Preview filemanager → composant commun** : partiellement branché (`setupPreviewModal`
   manipule déjà `#wamaMediaPreviewModal`) ; reste à retirer la modale locale `filePreviewModal`.
6. ⏳ **Composer pt7/pt8/pt9** : `_card_state`/`_card_progress` non inclus ; ETA via
   `model_config.estimate_seconds` statique (cible : catalogue) ; export médiathèque spécifique
   (cible : action commune pilotée par `output_types`).

**Validations navigateur toujours en attente** (reportées de session en session — passer `/smoke`
quand Playwright MCP est actif) : composer save modale + actions volet ; cards ×2 contextes
transcriber ; describer re-bind après re-rendu ; card v2 chips Reader (pilote) ; inspecteur des 5
apps portées ; cards mères ×3 ; bouton cycle transcriber ; toasts ; manipulation directe ;
duplication describer (fix double-fire 2026-07-25) ; entrée URL ×3 apps.

## 41. Capacité détection open-vocabulary — LocateAnything 🔄 (ouvert 2026-07-27)

- Évaluation complète faite (session 2026-07-27) → **décision + séquencement 4 étapes = ROADMAP §17**
  (licence non-commerciale OK Lescot / EXCLU partenaire-toolbox tierce ; latence VLM → jamais per-frame vidéo).
- Réorganisation de l'arbre en mondes consignée **ROADMAP §18** — POST-portage, NE PAS ouvrir avant.
- État 2026-07-27 soir : poids téléchargés (7,3 Go, non-gated) après élagage `gpt-oss:20b` (D: ≈22 Go
  libres) ; transformers 4.57.6 compatible ; chargement CPU ✅ (11 s, pic 2,4 Go) ; chargement CUDA
  complet (≈60 s, 7,3 Go VRAM) mais **3 crashs hôte (hang GPU-PV WSL2, bug MS #40732)** →
  **partie GPU du PoC SUSPENDUE sur le poste dev** (mémoire incident + protections : `.wslconfig`
  cap 16 Go, cap GPU 320 W).
- Prochain pas : valider l'inférence sur Linux natif (serveur R760xa) ou venv Windows natif, PUIS
  brique commune détection (absorber les 2 wrappers SAM3 — voir ROADMAP §17 étape 2).

## 42. Sauvegarde base + espace de stockage distant 🔄 (ouvert 2026-07-27)

- **Brique** : `python manage.py backup_db` (`wama/model_manager/management/commands/backup_db.py`)
  — `pg_dump --format=custom` + copie distante + **rotation** (`--keep`, défaut 10 de chaque côté),
  vérification de taille avant de valider la copie (même garde que `offload_file`).
  Options : `--no-remote`, `--remote-dir`, `--keep`. Variable : `WAMA_DB_BACKUP_PATH`.
- **UI** : bouton « Backup DB » dans les outils système du model_manager (volet droit) →
  `model_manager:api_backup_db` (POST, `is_admin_or_dev`). Synchrone — à basculer sur Celery si
  le dump dépasse le timeout HTTP.
- **UI — bouton « Backup Models » (2026-07-28)**, à côté de « Backup DB ». Pendant « modèles » qui
  manquait : le seul backup de modèles était celui de la barre de sélection (per-modèle, invisible
  tant qu'aucun modèle n'est coché). **Asynchrone par nécessité** (335 Go locaux / ~325 Go déjà
  distants) : `model_manager.backup_all_models` (Celery) →
  `RemoteBackupService.backup_all_models()`, incrémental (fichier sauté si présent et de même
  taille). Avancement publié dans le **cache Redis** (`BACKUP_ALL_CACHE_KEY`) et non dans
  l'`AsyncResult` → le suivi survit à un F5. `api_backup_models_start` est idempotent (refuse une
  2ᵉ passe concurrente, et vérifie auprès de Celery que la tâche du cache est vivante) +
  `api_backup_models_progress`.
  **✅ Premier vrai run 2026-07-29** : 1149 fichiers, 123 copiés (**10,0 Go**), 1026 déjà présents,
  0 échec. **Intégrité vérifiée après coup** : 1149/1149 présents à distance avec taille identique,
  0 manquant, 0 écart. Corrigé dans la foulée : l'UI affichait « Terminé — 0/1149 (0 %) » car
  `processed` n'existait que dans les dicts du `progress_cb`, pas dans le `summary` republié au
  dernier publish → clé absente → `undefined` → 0 (le run, lui, était correct).
  ⚠ Piège de vérification : `AI-models/models/` contient **832 fichiers réels + 317 symlinks HF**
  (`snapshots/ → blobs/`) = 1149. Comparer des `find -type f` local/distant induit en erreur ; et
  tout script de contrôle doit exporter `WAMA_MODEL_BACKUP_PATH`, sinon il teste le défaut UNC
  (inexistant sous WSL) et conclut faussement que 100 % des fichiers manquent.
- **Corrigé 2026-07-28 — `api/backup/status/` en 502** : `get_status()` appelait `list_backups()`,
  soit 3 `rglob('*')` + `stat()` par fichier sur les 70 modèles distants = **139 s** mesurées →
  Apache coupait avant la réponse, d'où « Error checking backup » (le `catch` du fetch). Ajout de
  `count_backups()` (3 niveaux de dossiers, aucun `stat` de fichier) → **1,6 s** ; `list_backups()`
  fusionne ses 3 parcours en 1 → 53 s. Leçon : sur le montage 9p, tout `rglob`+`stat` récursif est
  hors budget d'une requête HTTP.
- **Convention d'espace distant** (structuration demandée par Fabien) : racine
  `\vrlescot\SAVES\DEEP_LEARNING\` = `MODELS\` (existant, `remote_backup.py`) + **`DB\`** (créé
  2026-07-27). Depuis WSL2 la même racine est montée sur **`/mnt/shares/SAVES`** (drvfs 9p) — la
  commande détecte WSL et bascule seule.
  Le défaut codé dans `remote_backup.py` est le chemin UNC, mais **`start_wama_prod.sh:52` exporte
  `WAMA_MODEL_BACKUP_PATH=/mnt/shares/SAVES/DEEP_LEARNING/MODELS`** (point de montage WSL) — donc
  rien à corriger côté modèles. `backup_db` obtient le même résultat par auto-détection WSL, sans
  exiger de variable. (Correction 2026-07-27 : une « dette » de traduction UNC avait été consignée
  ici à tort, faute d'avoir suivi la variable jusqu'à son export — cf. règle « tracer le chaînage
  d'exécution avant d'affirmer un trou ».)
- **Validé** : smoke complet 2026-07-27 contre la base Windows (dump 0,4 Mo → NAS → rotation),
  artefacts de test supprimés, dossier `DB\` conservé.
- **✅ Premier vrai dump de la base LIVE (WSL2) — 2026-07-29** : `wama_db_2026-07-29_1708.dump`,
  **88,6 Mo**, présent en local ET sur le NAS (`DB\`) à taille identique. Validé par
  `pg_restore --list` : 92 tables avec données (`auth_user`, `model_manager_aimodel`,
  `transcriber_*`…). L'écart 88,6 Mo vs 0,4 Mo confirme le constat ci-dessous : la base Windows
  n'était bien qu'un schéma + seed. Ce point de §42 est clos.

### 2026-08-10 — Automatisation + 3ᵉ domaine (MÉDIAS) + moteur extrait en brique commune

- **Rien n'était PLANIFIÉ.** La brique `backup_db` existait depuis le 27/07 mais n'était câblée à
  aucun ordonnanceur — vérifié : crontab utilisateur, `/etc/crontab`, `cron.d|daily|hourly|weekly|
  monthly`, timers systemd, `at`, **toutes** les tâches planifiées Windows, `CELERY_BEAT_SCHEDULE`,
  scripts de démarrage. Preuve empirique : **un seul dump** (29/07) alors que la rotation en garde 10
  et que l'hôte a subi 7 coupures d'alimentation entre-temps. `django_celery_beat` est bien dans
  `INSTALLED_APPS`, mais beat tourne **sans `--scheduler`** et `CELERY_BEAT_SCHEDULER` n'est pas
  défini → `PersistentScheduler`, qui lit les réglages et **ignore la base** : une ligne
  `PeriodicTask` y serait inerte.
- **Ajouté** : `backup-db-daily` (03:30) et **`backup-media-daily` (02:30)** dans
  `CELERY_BEAT_SCHEDULE`, queue `default`. Ordre voulu : médias → base → **purge de rétention
  (04:00)**, pour archiver les médias sur le point d'expirer avant qu'ils ne disparaissent.
  pg_dump et le miroir sont CPU/IO purs : la règle « pas de job GPU nocturne » reste respectée.
- **MÉDIAS (nouveau)** : `common/services/media_backup.py` + tâche `common.backup_media` (avancement
  en cache Redis, clé DISTINCTE de celle des modèles → les deux peuvent tourner ensemble) + bouton
  **« Backup Médias »** et endpoints `api_backup_media_start` / `_progress`.
  Espace distant `DEEP_LEARNING/MEDIAS`. **Amorçage manuel par Fabien le 10/08** (contenu antérieur
  déplacé sous `~Archives/`, puis copie de `media/`) → les deux arbres étaient déjà cohérents, d'où
  un premier run à coût nul. **Validé en réel : 2640 fichiers / 21 Go, 0 copié, 2640 déjà présents,
  0 échec en 129 s**, `~Archives` intact.
- **Moteur EXTRAIT** : `common/services/mirror_sync.py` (`mirror_tree`, `remote_is_available`,
  `resolve_remote_root`). `RemoteBackupService.backup_all_models()` **délègue** désormais au lieu de
  porter sa propre boucle ; idem côté JS où `createMirrorBackupUI` porte une seule fois
  rendu + polling + démarrage, paramétré par un préfixe DOM. Les 3 domaines partagent
  l'auto-détection WSL/Windows de `resolve_remote_root`.
- ⚠️ **Ne pas relire le changement de `REMOTE_BACKUP_PATH` comme une réparation.** Le bouton
  « Backup Models » **a toujours fonctionné** (gunicorn/celery héritent de l'export de
  `start_wama_prod.sh:52`). Seul l'appel hors de ce contexte échouait. **Le piège du §Convention
  ci-dessus a repris une 2ᵉ fois le 10/08** : constater `is_available() == False` dans un
  `manage.py shell` ne dit RIEN de l'état des process de production.
- 🔴 **Redémarrage de la pile REQUIS** pour que `common.backup_media` soit enregistrée auprès des
  workers et que beat charge `backup-media-daily`. Tant qu'il n'a pas eu lieu, le bouton met une
  tâche en file que personne ne consomme.

### ✅ 2026-08-10 (soir) — TIRAGE LIVRÉ + 4ᵉ domaine (SECRETS) + doubles routes supprimées

- **`manage.py restore_backup --domain models|media|config`** (`common/management/commands/`) —
  c'est `mirror_tree(distant, local)`, **le même moteur dans l'autre sens**, pas un second
  mécanisme. `--dry-run` mesure l'écart sans écrire ; **refus d'écrire dans une destination non
  vide sans `--yes`** (une installation vivante n'est pas une installation neuve) ; `config`
  refuse d'écraser un `.env` existant sans `--force`.
  **`exclude={'~Archives'}` n'est posé QUE pour `media`, et QUE dans ce sens** — l'asymétrie
  annoncée s'est vérifiée.
- **`manage.py restore_db --dump <f> | --latest`** (`model_manager/management/commands/`) —
  destructif, donc **CLI uniquement, jamais un bouton**. `--dry-run` liste l'archive (934 objets
  vérifiés), refus sans `--yes`, restauration via `-d postgres` (impossible de supprimer la base
  à laquelle on est connecté). Détecte l'erreur « rôle inexistant » et affiche le `CREATE ROLE`.
- **SECRETS — 4ᵉ domaine** : `common/services/config_backup.py` + tâche `common.backup_config`
  + entrée beat **02:20**. **Versionné, pas écrasé** : `INSTALL/.env` (courant, chemin stable) +
  `INSTALL/history/.env.<horodatage>` purgé au-delà de `keep`, alimenté **uniquement si le SHA-256
  change** — sinon une tâche quotidienne fabriquerait 365 copies identiques par an et chasserait
  les versions utiles. Confidentialité : automatise le choix de Fabien du 10/08 (dépôt manuel), ne
  l'élargit pas.
- **✅ Les 3 doubles routes sont SUPPRIMÉES** (exigence de Fabien : « je ne veux pas de double
  route ») : ① la primitive de copie (`_copy_one` → `mirror_sync.copy_file`) ; ② le parcours
  récursif de `backup_directory` (→ `mirror_tree` + callback `on_file`, contrat `BackupResult`
  préservé) ; ③ l'enveloppe des tâches et le corps des 4 vues (`run_mirror_job`,
  `_mirror_job_start/_progress`). La purge keep-N de `backup_db` est passée en `purge_keep_latest`
  avant que `config_backup` n'en ait besoin — 3ᵉ copie évitée.
- **Régression attrapée PAR LE TEST** : `mirror_tree` refuse une destination inexistante
  (invariant anti-dossier-poubelle sur UNC non monté) ; or le sous-dossier distant d'un modèle
  n'existe pas au premier passage → `backup_directory` rendait 0 résultat. Corrigé par un `mkdir`
  explicite **gardé** par une vérification de disponibilité de la racine.
- **Nuance de comportement documentée** : le saut se fait désormais sur « présent ET même taille »
  au lieu de « présent » — une copie distante tronquée est refaite au lieu d'être conservée.
- **Ordre imposé pour une réinstallation** : ① `restore_backup --domain config` (récupère `.env`,
  mot de passe DB inclus) → ② `restore_db` → ③ modèles → ④ médias → ⑤ `sync_models`.

**🔴 Deux trous mesurés le 2026-08-10 — une réinstallation ÉCHOUERAIT aujourd'hui même avec les
trois sauvegardes en main :**

1. **Les secrets ne sont sauvegardés NULLE PART.** `.env` (2 440 o) est ignoré par git
   (`.gitignore:94`) et **absent du NAS** (`DEEP_LEARNING/` = `DB`, `MEDIAS`, `MODELS`, … pas de
   dossier de configuration). Sans lui, une installation neuve ne peut se connecter ni à Postgres
   ni à Redis. `.env.example` sert de gabarit mais ne contient aucune valeur.
   → décider d'un emplacement (NAS chiffré ? gestionnaire de secrets ?) — cf.
   `project_secrets_externalization`, l'historique a déjà été réécrit pour les en sortir, donc
   les remettre en clair quelque part demande une décision explicite de Fabien.
2. ~~**Le dump ne recrée ni le rôle ni la base.**~~ **CORRIGÉ LE 10/08 : à moitié faux.** La BASE
   était bien recréable — c'est `pg_restore --create` (ce qu'emploie `restore_db`) qui fabrique le
   `CREATE DATABASE` depuis l'en-tête de l'archive. Mesuré en générant le SQL des deux dumps, avec
   et sans `pg_dump --create` : **instruction identique**, encodage et locale compris. Le flag a
   donc été retiré après essai — le garder aurait laissé croire qu'il servait à quelque chose.
   **Reste vrai** : le **RÔLE** manque, et manquera toujours (objet de niveau CLUSTER, absent de
   tout dump de base). `restore_db` détecte l'erreur et affiche le `CREATE ROLE` à exécuter, avec
   le mot de passe qui vient du `.env` du point ①.

~~**Doublons restants dans la chaîne de sauvegarde**~~ — **TOUS SUPPRIMÉS le 10/08 au soir**, voir
la section ci-dessus. La chaîne (sauvegarde ET tirage, 4 domaines) n'a plus qu'un moteur :
`common/services/mirror_sync.py`. J'avais proposé de les « assumer à 2 instances » : Fabien a
tranché l'inverse, et il avait raison — le tirage en aurait fait une 3ᵉ le jour même.

### Constat : la base Postgres Windows n'est PAS la base de travail
Mesuré 2026-07-27 — Postgres 17 (Windows, `postgresql-x64-17`, port 5432) contient `wama_db` :
92 tables, migrations à jour (26/07 17:44), mais **`auth_user`=3, `model_manager_aimodel`=147,
`transcriber_transcript`=0** et un dump de **0,4 Mo** → schéma + seed catalogue, **zéro donnée de
travail**. La base LIVE est celle de **WSL2 (Postgres 16)**, conforme à
`reference_infra_wsl_windows`. La règle « migrer des DEUX côtés » ne se justifie donc que si l'on
exécute WAMA nativement sous Windows (`venv_win runserver`) ; sinon c'est une taxe d'entretien
supprimable (à confirmer : aucun worker/service Windows ne pointe dessus).

## §REPRISE — 2026-08-13 (nuit) : BANC CODEGEN JOUÉ (marche B front 2) + skills à jour

> **Reprise** : les 5 contrôles conformes au bloc attendu (check_docs 2 CASSÉ, corpus 110,
> roundtrip converter 9/10, grille converter 93/reader 87/transcriber 94, migrate OK).
> **Leçon nouvelle** : `manifest_export --check` est VENV-DÉPENDANT pour les libraries
> (importlib.metadata) — depuis venv_win il déclare 3 faux « périmés » (torch/transformers/
> vibevoice : les wheels Windows ne portent pas les dépendances nvidia-*/triton du wheel
> Linux). **Le contrôle fait foi depuis WSL2** (= le runtime) ; skills /reprise /palier
> /manifeste mis à jour en conséquence + répercussion du registre des mécanismes et de la
> marche A dans /brique /doc-sync /port-app (commit skills dédié).
>
> **BANC CODEGEN (avec Fabien, 01h27→01h46)** : `run_codegen --truth`, 4 modèles × 2 apps
> (converter `_convert`, reader `_read`), sorties `outputs/codegen_*_2026-08-13_*.json` +
> `outputs/banc_codegen_2026-08-13.log`. Mesures mécaniques : **qwen3.6:35b seul 8/8**
> (2× compile+signature, 0 warning, ~6 min/glu) ; qwen3-coder:30b ~1 min/glu mais 1
> violation règle 3 ; gemma4:26b 1 SyntaxError sur 2 ; e4b 2 warnings + contrat violé.
> Lecture qualitative (vs vérité terrain) : le différenciateur décisif est le **régime
> d'ignorance** — qwen3.6:35b n'invente JAMAIS d'import (il commente ce qu'il ne sait pas),
> qwen3-coder invente des briques communes PLAUSIBLES (`run_ffmpeg_cmd`,
> `select_model_by_vram` — le pire mode de défaillance pour WAMA) + shadowing d'`item` ;
> gemma4:26b applique « null plutôt que plausible » (NotImplementedError explicites) mais
> syntaxe non fiable. **VERDICT : qwen3.6:35b CONFIRMÉ principal** (config.py annoté,
> chaîne de repli inchangée).
> **Enseignement transverse — les plus gros écarts sont des trous de MATIÈRE, pas de
> modèle** : ① aucun modèle ne peut appeler les backends réels de l'app (l'inventaire des
> modules importables n'est pas dans la matière → ré-implémentation inline ou import
> inventé) ; ② tous inventent les clés de `fields` (`text`, `output_size`…) car les champs
> du modèle d'item ne sont pas cités dans le prompt (le `model_spec` A5 les porte —
> à injecter + règle « les clés de fields DOIVENT être des champs du modèle ») ; ③ les
> conventions de chemin de sortie passent bien par le few-shot. → Améliorer la matière de
> `run_codegen` AVANT le pilote transcriber : meilleur levier qualité, zéro GPU.
>
> **SUITE (même nuit) : matière enrichie LIVRÉE + boucle FERMÉE en 2 deltas** (qwen3.6:35b,
> mêmes cibles + `--truth`). Ajouts à `run_codegen` : `inventaire_app` (modules réels par
> AST, méthodes de classes AVEC signatures, `self` conservé), `champs_item` (champs concrets
> + propriétés du modèle d'item — ⚠ `item_model` du manifeste est un nom de classe NU, à
> préfixer par l'app : sans ça la résolution échouait EN SILENCE et la liste manquait),
> garde mécanique `import WAMA INEXISTANT` (attrape `run_ffmpeg_cmd`&co), prompt durci
> (clés de `fields` ⊆ champs ; imports d'app ⊆ inventaire ; sinon NotImplementedError).
> **Delta v1** : ré-implémentation inline DISPARUE (vrais backends/utils, vraies classes,
> 119→83 LOC) ; 3 résidus → 3 causes de matière corrigées. **Delta v2 : les 3 inventions
> ÉTEINTES** — converter 62 LOC clés `fields` toutes réelles + `input_filename` correct ;
> reader 66 LOC `result_text`/`used_backend`/`page_count` réels + `run(mode, language,
> progress_cb)` exact. Résidu ultime (appel classe vs instance) corrigé dans la matière
> (`self` visible), non re-mesuré (3 h du matin — le juge profond reste le harnais C à
> l'application). **Rôle codegen PRÊT pour le pilote transcriber.**
> **Plan de clôture proposé à Fabien (mesuré)** : ligne régénérabilité = 3/10 harnais-
> conformes (converter/reader/transcriber ; A2+A3a+A4 = converter+reader seulement) →
> phase R : porter les 7 restantes (2-3 sessions, sans GPU) ; ligne grille = 61 ❌ dont
> **36 sur 4 critères transverses** (recursive_import 10/10, model_caps_ui 9, during_preview
> 9, input_match_ui 8) + paquet synthesizer (11, seul F4 structurel), describer 10,
> composer 8 → phase G ; puis phase B (pilote transcriber + Translator DE ZÉRO, GPU).
> ~7-8 sessions au total. ⚠ restart workers/gunicorn PENDING ; push = demander.
>
> **SUITE (même nuit) : converter → 100 % ENTAMÉ + bug inspecteur RÉSOLU.** Cadrage acté
> avec Fabien : terminer le portage PAR COMPARAISON avec l'app générée (diff code = harnais,
> diff comportement = Playwright) ; converter = pilote. Bug connu (les paramètres de
> conversion absents du volet inspecteur alors que la modale les montre) : cause TROUVÉE
> dans la brique — `detail_from_spec` en mode `extra_from_params: '<champ JSON>'` ne lisait
> QUE le JSON porteur, jamais les champs DÉDIÉS du modèle (`output_format` n'apparaissait
> jamais ; `options: {}` = volet muet). Corrigé dans `detail_registry.py` : repli déclaratif
> JSON → champ dédié, alias exclus (pas de doublon) ; **validé sur données réelles**
> (items 54/55 : `Format de sortie` visible, extras JSON intacts). Rayon d'action mesuré :
> converter seul (le reader n'utilise pas `extra_from_params`). ⚠ le volet est servi par
> gunicorn WSL2 → le correctif ne sera VISIBLE qu'après le restart PENDING ; validation
> navigateur (/smoke) à faire après. Reste pour converter 100 % : recursive_import +
> during_preview (vraies briques transverses) ; model_caps_ui + input_match_ui = vérifier
> s'ils doivent être NON APPLICABLES sur une app sans moteur IA (corriger le CHECK avec
> preuve, pas l'app — règle /conformite).
>
> **SUITE : brique `recursive_import` LIVRÉE (converter 93 → 95 %).** Existant vérifié
> AVANT d'écrire (règle /brique) : la traversée récursive vivait déjà dans
> `filemanager.js` (drop `webkitGetAsEntry` + batching `readEntries` + input
> `webkitdirectory`) → **EXTRACTION, pas invention** : brique commune
> `static/common/js/wama-folder-import.js` (`WamaFolderImport.collect/fromInput/files`,
> montée GLOBALE base.html avant filemanager.js), filemanager 1er consommateur (traversée
> locale SUPPRIMÉE — pas de double chemin), converter 2e (drop récursif + lien « importer
> un dossier » via `folder_input_id=` de `_new_item_card.html` — paramètre optionnel,
> adoption = 2 lignes de handler + 1 paramètre d'include). Critère mis à jour pour
> reconnaître la brique (précédent crash_redelivery_guard). Syntaxe node OK ×3, statics
> dupliqués. Adoption restante : 9 apps (2 lignes + 1 paramètre chacune). ⚠ validation
> navigateur (drop d'un dossier réel) après restart/HUP gunicorn — templates cachés.
>
> **SUITE : passe d'adoption ×9 JOUÉE — `recursive_import` 9/10** (question Fabien « toutes
> les manières d'importer ? » vérifiée d'abord : explorateur drop/sélecteur = brique ✅ ;
> filemanager→app : « Envoyer dossier vers… » **EXISTE** (filemanager.js:767-815 —
> ⚠ j'avais d'abord affirmé le contraire sur la seule lecture de la branche `file`,
> CORRIGÉ après question Fabien) mais il collecte `children_d` de jstree alors que l'arbre
> est **paresseux** (views.py:229-231, `children: True` à l'expansion) → **envoi PARTIEL
> SILENCIEUX sur un dossier jamais déplié** ; **CORRIGÉ dans la foulée (validé Fabien)** :
> `api_import_to_app` accepte `folder` — expansion `rglob` CÔTÉ SERVEUR filtrée par
> `APP_CATALOG.input_extensions` (même source que le menu client), gardes `is_path_allowed`
> au dossier PUIS par fichier, `path` ajouté aux résultats (événements `wama:fileimported`
> émis depuis la RÉPONSE) ; JS = `importFolderToApp(folder, app)`, l'action dossier
> n'expanse plus l'arbre. Smoke lecture-seule : 8 fichiers récursifs trouvés sur
> `transcriber/1` avec le filtre. ⚠ restart gunicorn requis pour la vue (même lot) ;
> drag interne FM = no-op inchangé (pas de File natif) ; describer/synthesizer
> gardent leur chemin `FileManager.getFileManagerData` AVANT collect). Adoption COMPLÈTE
> (lien dossier + drop récursif) : anonymizer, describer, enhancer ×2 zones, reader,
> synthesizer, transcriber ; ROBUSTESSE seule (slots mono-fichier, dossier → vrais fichiers,
> pas de lien) : avatarizer (avatar+audio), imager (routeFile ×N) ; composer NON adopté
> (prompt-primaire — l'import dossier n'y a pas de sens, candidat N/A avec
> model_caps_ui/input_match_ui converter). Node OK ×9, statics ×9, grille re-mesurée :
> anonymizer 93, avatarizer 94, converter 95, describer 86, enhancer 94, imager 94,
> reader 88, synthesizer 86, transcriber 95 (composer 88 inchangé). ⚠ même lot de
> validation navigateur post-restart que le reste.
>
> **SUITE (13/08 midi, screenshot Fabien converter) : 3 corrections inspecteur/card.**
> ① Note « smoke 03/08 » affichée sur l'item #49 TERMINÉ = `error_message` résiduel en
> base (1 seul cas mesuré) → règle d'affichage dans `build_detail` : erreur MASQUÉE sur
> statut SUCCESS (un résidu de run précédent faisait passer un succès pour un problème).
> ② « Paramètres de conversion invisibles au volet » : la section PARAMÈTRES du volet =
> zone de composition POUR LES PROCHAINS UPLOADS (choix daté, commentaire
> converter/index.html:345) ; les params de la CARD cliquée arrivent en INFOS via le fix
> `detail_from_spec` de la nuit — TOUT est en attente du RESTART gunicorn (le screenshot
> montre le code d'avant). ③ **Card v3 portée au converter** : `_job_card.html` réécrit
> sur le formalisme wcv3 (5 pistes + barre pleine largeur en ligne 2 — plus jamais dans
> la piste État ; contrats converter.js préservés : .job-card, .wama-progress-fill,
> .progress-text, .btn-group-actions, boutons) ; `output_format` → `section="output"`
> (chip en piste Sortie), `quality_preset` → `chip=True` (piste Réglages) ; rendu validé
> en shell sur 3 items réels (SUCCESS ×2 + FAILURE). Au passage le critère
> `card_progress_brick` RETARDAIT sur la v3 (il exigeait les includes v2 et sanctionnait
> reader/describer/composer, les cards les plus récentes) → reconnaît désormais
> wcv3-bar/wama-progress-track ; re-mesure : converter 95, reader 90, composer 89,
> describer 87. ⚠ le TOUT (①+②+③) n'est visible qu'après restart/HUP gunicorn.
>
> **SUITE (13/08 après-midi) : chantier « 3 designs partout » CADRÉ + pile RÉPARÉE.**
> État MESURÉ (⚠ j'avais d'abord nié l'existence du mécanisme — 2 greps aux mauvais
> tokens ; Fabien avait raison, 2e correction du jour) : le sélecteur **3 densités
> (§11.4 : V1 Détaillé · V2 Compact ~48px · V3 Affiné défaut)** + le **modificateur
> PILE (§11.5, `card_stacked`)** vivent dans `_queue_toolbar.html` (INCLUSE PAR LES 10
> APPS) + `wama-queue.js` (`card_design` profil) + `wama-card-v3.css` — un seul markup,
> AUCUN `{% if design %}` serveur (doctrine écrite dans le CSS). **Seul manque : 7 apps
> n'émettent pas le markup wcv3** (le sélecteur y est inerte) — wcv3 présent : reader,
> transcriber, converter (13/08). **Bug pile TROUVÉ+CORRIGÉ** (la plainte Fabien « seule
> la card du centre est lisible ») : paliers 46/28/14px de `.wama-queue-stacked` réglés
> pour la v2 (ligne 1 = nom) — la v3 ouvre sur le bandeau #id·date → coupe aveugle au
> bandeau. Fix : une card comprimée devient une LAMELLE CONSTRUITE (nom + point d'état,
> bandeau/pistes/barre masqués), cards v2 non touchées. ⚠ la maquette de référence
> (artifact « WAMA — Card v3.5 » 01/08) est infetchable (4 échecs réseau) — le fix est
> de principe, à confronter à la maquette si Fabien exporte le HTML dans `claude/`.
> **RESTE (série approuvée par Fabien)** : porter le markup wcv3 aux 7 cards manquantes —
> anonymizer, avatarizer, composer, describer, enhancer, imager, synthesizer (recette =
> reader pilote + converter 13/08 : 5 pistes nommées, contrats JS d'app préservés,
> chips `section=`, rendu validé en shell).
>
> **SUITE (13/08 ~14h) : SMOKE NAVIGATEUR PASSÉ — le lot de la nuit est VALIDÉ À L'ÉCRAN**
> (serveur relancé par Fabien). ① `run_nightly_tests --stage ui` : **13/13 OK, 0 erreur
> console** (tout le JS de la nuit charge partout). ② Passe ciblée converter (compte smoke
> DÉDIÉ `ui_smoke_v3` + 2 jobs semés via `consolidate_jobs_into_batches`, session forgée
> avec le `SESSION_ENGINE` CONFIGURÉ — le backend db en dur donnait un cookie inerte ;
> script réutilisable `logs/ui_smoke/smoke_converter_v3.py`, à décliner pour la série) :
> **card v3 ✅** (5 pistes alignées, chips Équilibré/jpg/webp, fichier produit en Sortie,
> barre ligne 2, pas de barre en PENDING) ; **INFOS de la card cliquée ✅** (chips Format /
> Qualité / Propriétés / Format de sortie / Qualité 80 — le bug « params invisibles au
> volet » signalé le matin est RÉGLÉ à l'écran) ; **pile ✅** (voisine en lamelle lisible
> « nom · état ») ; **densités V2 Compact ✅ (1 ligne) et V1 Détaillé ✅ (réglages en
> liste)** ; pile × V2 composent. Pièges du script consignés : card MÈRE porte aussi
> `.job-card` (cibler `.collapse[data-wama-batch-key] .job-card`), design = dropdown
> Bootstrap (cliquer le toggle d'abord), `card_stacked`/`card_design` PERSISTENT entre
> runs sur le profil smoke. Captures : `logs/ui_smoke/manual/*.png`.
>
> **SUITE (13/08 après-midi) : SÉRIE wcv3 7/7 TERMINÉE — les 3 designs couvrent les 10
> apps.** Ports (1 commit/app, rendu validé en shell sur items réels à chaque fois) :
> describer (chips ×3 créés + `_decorate_desc` + re-rendu serveur AUSSI en FAILURE — l'update
> en place ciblait le .status-badge disparu), enhancer (2 cards : média + audio), synthesizer
> (chips ×3 + `_decorate_synthesis`), anonymizer, composer (chips ×2 + `_decorate_generation`
> + maj point d'état v3 en place — son re-rendu serveur n'arrive qu'en FIN de tâche), imager
> (data-* inspecteur intégralement préservés sur la racine), avatarizer (+ **fix no-op
> silencieux** : le JS ciblait `.progress-fill` alors que la brique rend `.wama-progress-fill`
> — la barre ne bougeait qu'aux transitions depuis le passage à la brique). Contrats JS
> relevés AVANT chaque réécriture et consignés en tête de chaque partial. Grille re-mesurée :
> composer 90 (+2), describer 89 (+3), synthesizer 87 (+1), reader 90, converter/transcriber
> 95, anonymizer 93, avatarizer/enhancer/imager 94. ⚠ **RESTART/HUP gunicorn requis** (les
> 7 nouveaux templates sont cachés) puis re-passe smoke (ui stage + captures par app).
>
> **SUITE (13/08 fin d'après-midi, restart+push Fabien faits) : CONVERTER 100 % — verdicts
> N/A + brique during_preview étendue au TEXTE.** ① Re-smoke post-restart : 13/13, 0 erreur
> console (les 7 cards wcv3 servies). ② Verdicts N/A (validés Fabien) : `recursive_import`
> → fonction PRÉSENCE-D'ABORD (une adoption vaut toujours — synthesizer importe des dossiers
> de .txt) + repli N/A si aucune entrée média-fichier dans `input_types` (composer = descripteurs
> de batch) ; `input_match_ui`/`model_caps_ui` → garde `_uses_models` (la même que F4 : sans
> moteur IA, rien à griser/dériver). ③ **Brique `during_preview` étendue au texte partiel** :
> `publish_partial_text`/`get_partial_text` dans preview_utils (clé UNIQUE), payload during
> `text/plain + content` (branche déjà rendue par renderInlinePreview) ; transcriber
> (`_set_partial_text`, entonnoir unique) et describer (`_set_partial`) REBRANCHÉS sur la
> brique — leurs clés maison supprimées, lecteurs migrés (progress endpoints + tool_api ×3) ;
> capacité `during_preview=True` déclarée (transcriber, describer). ④ **Converter : émission
> during RÉELLE** — conversion AUDIO hors in-place : ffmpeg écrit la sortie progressivement
> sous MEDIA → `publish_partial(URL)` = écoutable pendant la conversion ; `_clear_during` aux
> deux issues ; capacité déclarée. Critère élargi à l'API de la brique (`publish_partial*`).
> Chaîne validée en shell (capacités, publish→payload→clear). **Grille : CONVERTER 100 %
> (60/60), transcriber 97, describer 90.** Reste during : reader/synthesizer/imager/enhancer/
> anonymizer/avatarizer (émissions à poser dans les boucles backend — GPU, à cadrer).
> ⚠ restart workers requis pour l'émission during (workers/tasks rechargés).

## §REPRISE — 2026-08-11→12 (3ᵉ-4ᵉ sessions, marches C + A COMPLÈTES A1→A5) : harnais + gabarits + triades + composition

> Le JUGE du plan C→A→B (route §10.3) est outillé : **`manage.py app_regen_check <app>`**
> rejoue la passe intégrée en commande — gardes git/corpus, strip (`strip_app_declarations`,
> nouveau geste bac-à-sable de `builtin/app.py`), `write_back_app(…, skip=('access',))` (kwarg
> `skip` ajouté — DB jamais touchée), mesures en sous-process FRAIS ancrés BASE_DIR, verdict
> 3 axes (① manifeste, famille mesurée seule tolérée ; ② grille critère par critère ; ③ smoke),
> restore `git checkout` (sauf `--keep`), exit ≠ 0 si non conforme (chaînable nightly, trou
> #19). **Validé pilote converter en worktree : CONFORME, identique à la passe manuelle**
> (10 écarts mesurés tolérés, grille 93 % identique, smoke 200) ; roundtrip 10 apps inchangé.
>
> **Puis marche A entamée** : **cadrage A0** (convention réelle MESURÉE, 6 cibles × 10 apps —
> route §10.3 : aucune app ne colle à STANDARD_ENDPOINTS, converter = déviant modèles, tool_api
> centrale) et **palier A1 LIVRÉ** — paquet `common/manifests/codegen/` (gabarit `urls.py`,
> `ROUTE_TABLE` mesurée), `processing.endpoints` = routes RÉELLES de l'URLconf (+
> `extra_routes` déclarées, canon de vue par identité d'attribut), projecteur
> `_project_processing` (urls seule, facette reste codegen), strip/un_write_back/harnais
> étendus. Couverture 9/10 complète ; **harnais : CONFORME avec urls.py strippé et régénéré**.
> Piège : system checks Django chargent l'URLconf → `requires_system_checks = []`.
>
> **Puis A1 rattrapé sur auto-critique** (4 écarts latents : perte silencieuse include/anonymes
> → poison de couverture ; import vues pointées ; ordre URLconf préservé ; validation
> extra_routes) et **palier A2a livré** : brique **`common/utils/task_skeleton.run_item_task`**
> (le squelette Celery dupliqué 10× avec dérive — gardes, progress, chrono, statuts, ETA,
> console, notifications — extrait UNE fois ; contrat de glu `process(item, ctx)`), converter
> porté (5 lignes + glu `_convert`), critères `crash_redelivery_guard`/`eta_seeded` reconnaissent
> la brique. Validé : exécution RÉELLE (PNG→WebP SUCCESS, artefacts nettoyés), grille 93 %
> identique, harnais CONFORME. ⚠ **Restart workers Celery WSL2 requis** (nouveau tasks.py).
> **Puis 2ᵉ adopteur : reader porté** (contrat élargi déclarativement : `progress_fn` à
> message, `console_success`, retour anticipé ; ETA intact par construction — mêmes clés,
> même chrono, `estimate()` non touché ; « dérive » `analyze`/`enrich` REQUALIFIÉE : espèce
> enrichissement, hors contrat volontaire). Le harnais a attrapé un écart réel (défauts de
> schéma rendus en `%r` → enum vs littéral) normalisé à la source dans `tool_api`. **Reader =
> 2ᵉ app CONFORME au strip-régénération complet** (grille 87 % identique, smoke identique).
> **Puis A2b livré — A2 CLOS** : facette `processing` enrichie (`tasks` par AST + `item_model`
> via DetailRegistry), gabarit `tasks_gen` (fichier mince : 5 lignes `run_item_task` + trou de
> glu marqué), projecteur CREATE-ONLY (un tasks.py existant n'est jamais touché — les trous
> remplis par B seraient effacés). Rendu compile, critères grille satisfaits sur le rendu,
> harnais converter+reader CONFORMES. Juge complet = pilote B.
> **Puis (2026-08-12) : composition du pilote B SEMÉE** — 8 libraries au corpus (mécanique,
> importlib.metadata ; le librarian LLM reste pour `--repo`/lib non installée) → transcriber
> `requires` = 4 modèles + 9 libraries, 13/13 résolus ; **strates actées** (SPEC §7.4-5) :
> socle plateforme (`library_index.SOCLE_PLATEFORME`, jamais cité) / libraries métier /
> outils système (trou #15). Corpus = 19 manifestes, fidélité 10/10.
> **Cible finale actée : 11ᵉ app Translator/LibreTranslate générée DE ZÉRO** (librarian
> `--repo` pilote 2 ; PDF-mise-en-forme = pipeline Studio d'abord) — après route + portage.
> **Puis A3a livré (12/08)** : `register_app_detail_spec` (la registration detail = SPEC-donnée,
> adapter générique `detail_from_spec` ; adapter code conservé pour les logiques irréductibles) ;
> converter + reader portés, **parité prouvée sur 10 items réels** ; facette `inspector` porte
> `detail_spec` + `preview` (données) au lieu de 2 booléens ; harnais ×2 CONFORMES. ⚠ restart
> gunicorn/workers pour charger les nouveaux `ready()` (comportement identique, sans urgence).
> **Puis A3b livré — A3 CLOS (12/08)** : gabarit `apps_gen` (ready() rendu des déclarations ;
> registre de mesure `batch_sync.SYNCED` → `processing.batch_link_model` ;
> `identity.verbose_name`) ; rendu REFUSÉ pour un detail à adapter code (transcriber) ;
> `inspector` dans PROJECTED_FACETS. Harnais : **converter CONFORME 6 cibles strippées
> (apps.py compris), reader 5 cibles** ; roundtrip converter 8/10. Docs tunnel croisées
> (ARCHITECTURE §1 = domicile de la jointure, invariant §2.1 explicite).
> **Puis A4 livré — A4 CLOS (12/08, 4ᵉ session)** : `start_<app>`/`get_<app>_status` =
> squelette conventionnel dupliqué (mesure A0) → entrée déclarative **`TRIAD_SPECS`**
> (tool_api.py), fonctions CONSTRUITES à l'import (`_register_triads()`, signature
> synthétisée — descriptions dérivées inchangées) ; `add_to_<app>` reste glu (marche B) ;
> converter + reader portés, **parité byte à byte** (baseline avant/après : descriptions,
> signatures, statuts réels, chemins d'erreur) ; critère grille `tool_api` → registre
> RUNTIME. Facette `tool_api` porte `triad_spec`, projecteur = entrée-valeur (moteur
> PROMPT_TARGETS généralisé), strip/un_write_back/harnais étendus, validation à l'ingest,
> `tool_api` dans PROJECTED_FACETS. **Harnais : converter CONFORME 7 cibles strippées
> (triad_entry compris), reader 6** ; roundtrip 10/10, converter **9/10 projetable** (reste
> `processing` partiel) ; grille 10/10 identique.
>
> **Puis micro-marche export corpus `model` ✅ (12/08, 4ᵉ session)** : `manifest_export`
> exporte les modèles DÉRIVÉS des `requires` des apps (∪ refresh, comme les libraries) →
> **91 manifestes modèle, 0 refusé** (= le lien `AIModel.source` 91/91), corpus total
> **110** ; noms assainis (`:`→`__`, garde anti-collision) ; sert revue humaine + few-shot,
> la composition reste en extraction live.
> **Puis A5 livré — MARCHE A CLOSE (12/08, 4ᵉ session)** : facette processing porte
> **`model_spec`** (spine mesuré par introspection) ; gabarit `models_gen` = squelette
> complet (spine F5 + options INVERSES de derive_from_model + batch/liaison + trou de
> résultat marqué B) ; projecteur **CREATE-ONLY DURCI** (un models.py existant porte des
> migrations — jamais touché ; makemigrations reste MAIN). Juge : rendus transcriber +
> reader compilent, **zéro champ inventé**, couverture 15/38 et 13/18 (le reste = glu B
> énumérée) ; harnais ×2 re-CONFORMES ; roundtrip 10/10 ; grille inchangée.
>
> **Puis (12/08, 5ᵉ session, Fabien présent) : vérification complète + régénération
> transcriber HORS ARBRE** (rendus des gabarits → scratch, dry-run write_back, diff vs
> réel — jamais d'écrasement). Bilan : registres 6/6 **noop** (parité déjà acquise) ;
> `app_name='wama.transcriber'` du urls.py réel = ligne INERTE (l'include racine force le
> namespace par tuple — la normalisation du gabarit est sans effet fonctionnel) ; **piège
> réel attrapé** : glu Celery dans workers.py (pas de tasks.py) → `_project_tasks` aurait
> CRÉÉ un tasks.py à trous en doublon — garde corrigée (« absent » = aucune tâche déclarée
> ne vit ailleurs) + tasks.py/models.py ajoutés au périmètre de restore du harnais.
> **Harnais transcriber : CONFORME (3ᵉ app)** — 5 cibles strippées/régénérées, skips
> motivés inspector (adapter code assumé, A3a) + tool_api (triade = VRAIE glu : routage
> preprocess_audio, purge segments, cache seed, aperçu partiel temps réel, clé
> transcript_id — ASSUMÉE main, le vocabulaire de hooks éventuel se décidera pendant B).
> Portage déclaratif du transcriber : TERMINÉ (tout le régénérable passe le juge).
> **Puis DÉCISION D'ARCHITECTURE (discussion Fabien, même session) : marche D — capacités
> héritées, ACTÉE et consignée** (`ROUTE §10.4` = domicile ; formalisme arête `uses` =
> `SPEC §7.5` ; studio-comme-bibliothèque = `STUDIO_VISION.md`). Doctrine des 3 espèces de
> chaînage (agrément/métier/production), arête `uses` à côté de `requires`, réalisation par
> le pivot existant, hooks de triade = shims dérivés (lève l'objection n=1 du débat A4),
> interop wama-lab via write-back du kind `pipeline`, pilote = `preprocess_audio` transcriber
> → capacité enhancer (A/B objectif obligatoire). **Séquencée APRÈS la marche B.**
>
> **Puis (12/08, 5ᵉ session, suite) : marche B front 1 LIVRÉ + couche déclarations modèles.**
> Rôle `codegen` créé (prompts/codegen.txt sur le patron librarian + run_codegen.py :
> matière = contrat task_skeleton + fichier mince A2b + manifeste composé + 2 glus réelles
> few-shot ; sortie PENDING_HUMAN_VALIDATION, contrôles mécaniques 4 familles, n'écrit
> jamais dans wama/). Découverte au passage : `qwen3.5:35b-a3b` remplacé par `qwen3.6:35b`
> sur l'hôte — **chaîne EXISTANTE tracée avant de construire** (leçon rappelée par Fabien) :
> pull_model→register_after_install, découverte ollama-first, `verify_models` = catalogue↔
> réalité (attrape 2 faux positifs sam3/doctr + 30 orphelins proposed:* — à trier), la
> prospection avait bien mis le catalogue à jour. **Trou réel = couche DÉCLARATIONS** :
> tables à la main jamais confrontées à la source unique → **`manage.py
> check_model_declarations`** (exit≠0 sur tag mort ; mesuré : 1/4 assistant + 3/12
> wama-dev-ai morts) ; tables corrigées (qwen3.6:35b + vision→gemma4), re-mesure 0 mort.
> **1er run codegen bout-en-bout validé** (gemma4:e4b léger, autorisé) : compile+signature
> OK, qualité e4b = barre basse du banc (invente /tmp, item.params) — vérité terrain jointe.
>
> **Puis (12/08, 5ᵉ session, fin) : enquête SAM3/olmOCR — 3 causes DÉMÊLÉES et corrigées.**
> ① **Fuite de cache HF inter-apps** : `sam3_processor` posait l'env process-wide ET mutait
> les CONSTANTES huggingface_hub sans restaurer → les artefacts HF (refs/locks/xet) des
> backends suivants du même worker tombaient dans `vision/sam/` (squelette olmOCR VIDE —
> les blobs étaient sauvés par le `cache_dir=` d'olmocr_backend). Corrigé : bascule
> CONFINÉE au chargement (try/finally restaure tout) ; squelette supprimé ; c'est
> l'anti-pattern ROADMAP §5b — ne jamais l'étendre. ② **Découverte dépendante du venv**
> (sam3 : retour anticipé sur import ; doctr : import = téléchargé) → les 2 « faux
> positifs » verify_models n'étaient PAS du catalogue mais de la mesure (WSL2 disait déjà
> juste) ; corrigé disque-d'abord, Windows = WSL2 = 30 écarts (orphelins proposed:* + 3
> TTS, à trier). ③ **Table de tags assistant SUPPRIMÉE** : les rôles du chat dérivent du
> catalogue (`select_chat_llm(tier)` — max par quality_index, code, mid, min) ; mesuré :
> max→qwen3.6:35b, code→qwen3-coder:30b, mid→gemma4:e4b, min→qwen3.5:4b.
> `check_model_declarations` ne garde que wama-dev-ai (découplé à dessein). ⚠ restart
> workers/gunicorn pour charger le confinement sam3 + la dérivation chat.
> **Puis (même session, questions Fabien ×3)** : ① `proposed:*` + 3 TTS = mémoire de
> catalogue VOULUE (candidats à installer) — `verify_models` les classe en info (verdict :
> **catalogue COHÉRENT**, 0 écart) et avertit que `--clean` les purgerait ; l'évaluation
> des candidats existe déjà (`assess_models`, multi-agents dry-run). ② Existant confronté :
> DEUX save/restore locaux du cache HF → **brique `common/utils/hf_cache.py::
> hf_cache_scope`** (env + constantes), kokoro et sam3 portés ; et MA route parallèle
> attrapée — `select_chat_llm` (1 h de vie) doublait `llm_utils._llm_par_catalogue` (LE
> point unique, 04/08) → supprimé, le chat se résout par **`modele_par_tier`** (accesseur
> public, priority/prefer_loaded déclaratifs) : dev→qwen3.6:35b, debug→qwen3-coder:30b,
> fast/ultra_fast→gemma4:12b. ③ **Balayage regex des littéraux de tags** ajouté à
> `check_model_declarations` (hors déclarations/backends/tests) — 4 morts attrapés au 1er
> run (chaîne describer nettoyée au réel, exemples de docstring) ; verdict final 0 mort.
> Littéraux VISION restants (ui_smoke, vision_probe, reference_comprehension) = bloqués
> par la capacité `vision` non peuplée au catalogue (correctif de fond documenté
> llm_utils:60, `vision_probe` désigné) — gardés par le balayage en attendant.
>
> **Clôture 5ᵉ session (12/08 soir) — réponses aux dernières questions Fabien** :
> ① indice de confiance des `proposed:*` — DEUX indices de natures différentes (clarifié
> avec Fabien) : le « % confiance » de l'UI = **`AIModel.confidence`, heuristique de
> RÉCENCE** (`prospect_ollama._confidence_from_age`, déterministe) — portée par **5/26**
> seulement (absente sur les `kind=new` proposés par rôle, sans âge amont connaissable) ;
> et le verdict LLM (`assess_models`) = **0/26** car jamais PERSISTÉ (dry-run console/JSON
> seul) → chantier désigné « cran de plus » : écrire les verdicts assess dans les lignes
> proposed + contrôle de couverture + distinguer les deux indices dans l'UI. ② moondream :
> **zéro trace au catalogue** (ni installé ni proposé) — utilisé à l'ère des noms en dur
> (describer pré-04/08), supplanté par gemma4:12b (validé meilleur describer FR), retiré ;
> ses derniers restes = les littéraux élagués aujourd'hui ; `pull_model` le réenregistrerait
> au besoin. ③ vision : DEUX AXES distincts — `ModelType.VISION` (dossier vision/, YOLO/SAM
> anonymizer/cam, peuplé, = le filtre UI) vs `abilities:['vision']` des LLM OLLAMA
> (multimodal chat). MESURÉ : ce 2ᵉ axe **EST peuplé** (gemma4:12b, qwen3.5:4b/9b,
> qwen3.6:35b via /api/show) — le commentaire llm_utils:60 est PÉRIMÉ ; faux négatif connu :
> gemma4:e4b (multimodal mais non déclaré par Ollama) → chantier : dériver les littéraux
> vision (ui_smoke, vision_probe, reference_comprehension, chaîne describer) via
> `requires=['vision']` + traiter e4b (vision_probe mesure/déclare) + corriger le
> commentaire. Corpus régénéré (3 libraries — métadonnées venv bougées, détecteur OK).
>
> 🔚 **POINT D'ENTRÉE SESSION SUIVANTE : marche B front 2 — le BANC** (qwen3.6:35b vs
> qwen3-coder:30b vs gemma4:26b/e4b, `run_codegen --truth` sur converter puis reader,
> AVEC Fabien — charge GPU) ; verdict → `select_model_for_role('codegen')`.
> **File des chantiers ouverts par la 5ᵉ session** (ordre libre, aucun bloquant) :
> ① cran de plus prospection (persistance verdicts + couverture) ; ② dérivation des
> littéraux vision (`requires=['vision']`, e4b, commentaire llm_utils) ; ③ ROADMAP §5b —
> `hf_cache_scope` est le PONT, la migration `cache_dir=` partout reste ouverte ;
> ④ statuer : `check_model_declarations` + `verify_models` aux contrôles nocturnes ;
> ⑤ ⚠ restart workers/gunicorn PENDING (confinement sam3, résolution chat par tier,
> triades A4, ready() A3) ; ⑥ push (~15 commits locaux) = demander.
> (route §10.3.B) : MISE À JOUR de `prompts/dev.txt` sur le modèle `librarian.txt` (contrat
> BaseModelBackend + manifeste composé + few-shot corpus + interdits) + **banc de modèles
> jugé par le harnais C** (candidat `qwen3.6:35b` MoE, challengers qwen3-coder:30b/gemma4) —
> ⚠ le banc charge le GPU : à lancer AVEC Fabien, jamais en autonome (règle crashs hôte).
> Pilote transcriber (exige d'abord son detail en spec déclarative OU un adapter assumé) ;
> pilote 2 = librarian `--repo` ; cible finale = Translator DE ZÉRO (le squelette neuf
> — urls/tasks/apps/models/triade — se rend déjà, B remplit les corps). Dette gardes =
> tâches anonymizer (avec son chantier).
>
> **État git en fin de session** : le doute sur `d934b38` est levé (poussé, vérifié 12/08
> 4ᵉ session) ; la 4ᵉ session ajoute A4a/A4b + docs + micro-marche corpus model + A5 —
> push = demander à Fabien. Worktree `D:\WAMA\wt-regen-converter` (`regen/converter`) :
> PROPRE, ff-mergé jusqu'à A4b inclus — le ff-merger depuis dev avant tout nouveau run du
> harnais (et copier les manifests/apps/*.json frais si le corpus a bougé). Aucune migration
> (aucun modèle touché). Contrôles attendus au prochain `/reprise` : check_docs = 2 CASSÉ
> (inchangé), corpus = **110 manifestes** (10 apps + 9 libraries + 91 models), roundtrip =
> converter **9/10** / autres 8-10,
> grille inchangée (converter 93, reader 87…). ⚠ restart gunicorn/workers WSL2 à l'occasion
> (tool_api/ready()/tasks.py rechargés — comportement identique).

## §REPRISE — 2026-08-12 (session catalogue/provenance/licences) : la chaîne prospection → catalogue → manifeste refermée

> Périmètre : `model_manager/services/*`, `common/services/license_audit.py`, `common/manifests/builtin/{model,library}.py`,
> `anonymizer/utils/model_selector.py`, `media_library`. Cinq commits :
> `8db2157` `e8a2b9a` `4b54f27` `d90be9a` `9318d47`. **Rien poussé.**
>
> **Le diagnostic de départ.** Les trois couches (prospection, catalogue, manifestes) étaient
> bonnes SÉPARÉMENT ; ce sont les **soudures** qui manquaient. `prospect_hf` lisait déjà la
> licence sur la carte HF et `apply_recommendations` la jetait ; `extract_model` ↔
> `write_back_model` formaient une boucle symétrique **qui se refermait sur du vide** faute de
> producteur en amont ; `install_from_spec` n'appelait qu'un `full_sync`, qui ne sait rien
> d'une licence. Même motif que pour les apps (« les briques existaient, il manquait le runner »).
>
> **Mesure avant → après** (101 modèles) : `license` **0 → 59**, `disk_gb` **19 → 66**
> (anonymizer 0 → 47/48), `platform_ref` 33 → 41, `hf_id` 22 → 29, `author` **0 → 29**.
>
> **① Le verrou qu'il fallait lever d'abord.** `hf_id` et `quality_index` étaient dans les
> `defaults` de `model_sync` avec un repli `or ''` / `or None` : **chaque sync les remettait à
> vide** pour les 70 modèles issus du scan disque. Une provenance vérifiée ne survivait donc pas
> au tick suivant de `model-manager-reconcile` (2 h, `settings.py:529`), et `quality_index`
> contredisait sa propre docstring (« une valeur posée à la main PRIME »). La découverte n'a pas
> autorité pour EFFACER ce qu'elle ignore : elle n'écrit plus que ce qu'elle sait.
> ⚠ **Récidive (4ᵉ) de [[feedback_trace_runtime_chaining]]** : mes écritures « disparaissaient »
> parce que les workers Celery vivants tournaient avec l'ANCIEN module en mémoire. Un
> `manage.py` ne dit rien des process lancés par `start_wama_prod.sh`.
>
> **② Trois provenances ÉTABLIES** (appariement nom + taille d'octets contre le dépôt amont,
> jamais déduites d'un nom de fichier) : les 5 ONNX plaques → `morsetechlab/yolov11-license-plate-detection`
> (agpl-3.0) ; `yolo11l_face_plate_signs.pt` → **`Panoramax/detect_face_plate_sign`** (etalab-2.0,
> confirmé indépendamment par `train_args.model = /bigpool/data/panoramax/…`) ;
> `face_yolov8m-seg_60.pt` → `jags/yolov8_model_segmentation-set` (apache-2.0). **10 poids restent
> sans origine** (2 lindevs — publiés sur GitHub, pas HF — et les 8 `yolov8*_face_plate_*p.pt`) :
> laissés VIDES, pas devinés.
>
> **③ Arbitrage licence, à connaître.** Un checkpoint ultralytics déclare `AGPL-3.0` parce que
> c'est la licence du **cadre d'entraînement**, pas celle de publication (Panoramax publie en
> etalab-2.0). Donc : **la carte de l'éditeur fait autorité et CORRIGE le repli « poids »** ;
> les poids ne sont le recours que pour les modèles sans identité de plateforme.
>
> **④ Briques neuves** (toutes factorisent, aucune ne double) :
> `model_manager/services/weights_metadata.py` (faits inscrits dans les poids : licence, classes,
> tâche, base et jeu d'entraînement — hors ligne) ; `model_manager/services/provenance.py`
> (`identite_huggingface` mutualisée — c'était le 3ᵉ endroit à lire la même carte ; `poser_identite`
> passe par l'API PUBLIQUE `ingest` extract→validate→write_back puis `manifest_export`) ;
> `common/services/license_audit.py` + page **`/common/licences/`** (vue DÉRIVÉE, zéro écriture).
> `SyncResult.added_keys` ajouté : le sync dit désormais ce qu'il vient de créer (il ne rendait
> qu'un compteur, obligeant à photographier le catalogue avant/après).
>
> **⑤ licence + auteur transversal (étage A).** `AIModel.author`, `Library.author`,
> `UserAsset.{license,author,source_url}`, `SystemAsset.author`. Vocabulaire REPRIS de
> `media_library/providers/base.Asset`, seul endroit où le couple existait. Trou le plus grave
> trouvé : `UserAsset` n'avait **ni licence ni auteur** — l'import des 6 fournisseurs les
> entassait dans `tags` et le texte libre de `description`, donc une œuvre CC-BY entrait sans
> qu'on sache qui créditer. ⚠ **Migrations NON versionnées** (`.gitignore:13`) → relancer
> `makemigrations && migrate` sur les autres environnements.
> **Étage B (auteur des apps/fonctions) NON FAIT** : `APP_CATALOG` n'a pas de champ, et c'est une
> déclaration interne, pas un fait externe qu'on lit — à trancher, ne bloque rien.
>
> **⑥ État des licences, MESURÉ** : 111 éléments, 60 établies, 51 inconnues, 5 non commerciales
> (4 MusicGen/AudioGen `cc-by-nc-4.0` + `depthpro` apple-amlr), 6 `other` à qualifier (FLUX, LTX,
> Hunyuan, CogVideoX), et **31 éléments exigeant une attribution SANS auteur renseigné** — dette
> juridique comptée à part. **6 apps sur 10 ont « inconnue » comme clause la plus contraignante.**
> `synthesizer` a 3 `requires` hors registre. Au passage, le registre `Library` n'avait **1 ligne
> pour 9 manifestes** (projection jamais jouée) → 9 lignes, `is_allowed=False` partout.
>
> **⑦ `yolo11l_face_plate_signs.pt` n'avait jamais servi** (`d90be9a`). Le modèle est sain (6
> visages détectés sur image réelle) ; il n'était JAMAIS choisi. Deux causes : le chemin rapide
> `SPECIALTY_KNOWN_CLASSES` **rendait sans ouvrir le fichier** (ordre de classes FAUX — l'ordre
> EST l'index passé à `predict(classes=…)` — et classe `sign` invisible), et une classe hors de
> `SPECIALTY_CLASSES` tombait entre deux chaises (étape 1 l'ignorait, `_find_coco_model` écarte
> les modèles à spécialité). Sélection `['sign']` : **0 % → 100 %**.
>
> ### ✅ `couvrir_classes` ENFIN ADOPTÉ — portage fait dans la foulée (`58e7051`)
>
> `common/services/model_coverage.py::couvrir_classes()` (écrit le 2026-08-04, **extrait de
> l'anonymizer** précisément pour ça) avait **ZÉRO consommateur**. L'anonymizer est désormais
> porté dessus. **REMPLACÉ, pas doublé** : supprimés faute d'appelant `SPECIALTY_CLASSES`,
> `_find_specialty_model`, `_find_combined_specialty_model`, `_find_coco_model` — **et la passe
> de « rattrapage » que j'avais ajoutée moi-même le matin** (`d90be9a`), qui dupliquait une
> partie de la brique et ordonnait moins bien (premier modèle déclarant la classe, sans tenir
> compte de la qualité → un modèle de POSE retenu pour `person`). **−400 lignes, +90.**
>
> | demande | avant | après |
> |---|---|---|
> | `face+plate+sign` | 2 modèles | **1** |
> | `face+plate+sign+person` | 3 modèles | **2** |
>
> **La règle que ce portage illustre : la POLITIQUE reste dans l'app, le MÉCANISME va dans la
> brique.** « Précision élevée → préférer la segmentation et les gros modèles » se DÉCLARE en
> paramètres (`preferer_segmentation`, `taille_preferee`), appliqués **en départage, jamais en
> filtre**. Le seul filtre est `TACHES_DETECTION = ('detect','segment')` — un classifieur annonce
> des classes sans savoir les localiser (`yolo11l-cls` déclare `plate`, l'assiette d'ImageNet).
> Corrigé au passage : `needs_parallel_detection` rendait `unsupported` quand son seul lecteur
> interrogeait `unsupported_classes` → l'avertissement « classes non couvertes » n'avait **jamais**
> pu s'afficher. Vérifié sur 7 cas : contrat complet, tous les chemins existent sur disque.
> **Restent à porter sur la brique** (annoncés dans son en-tête) : `cam_analyzer`, `face_analyzer`.
>
> ### Sélection multi-critère & qualité MESURÉE — état réel
>
> **La sélection multi-critère existe et est riche** (`model_manager/services/model_selector.py`) :
> filtres (source/type/candidates/name), capacités (`_supports` sur `capabilities`), appariement
> entrée↔modèle (`matches_inputs` : `task`, `inputs_required/optional`, `consumes`), sonde de
> disponibilité runtime, **paliers de `priority` qui dominent la VRAM**, `prefer_loaded` (résidence
> partagée), puis budget VRAM (avec marge anti-offload) et tri par `_rang_qualite`.
>
> **La boucle « qualité par mesure de résultat » est OUVERTE AUX DEUX BOUTS** :
> - `services/bench.py` mesure des grandeurs comparables par TÂCHE (latence, sorties, confiance,
>   saturation) — mais **ne persiste rien** ; son seul appelant est la commande `bench`, qui affiche.
> - `common/utils/qc.py` (juge LLM indépendant, 0..1, garde-fous §16.5) a **ZÉRO appelant**.
> - `AIModel.quality_index` ne reçoit QUE l'indice **a priori structurel** (`model_quality.py`),
>   et seulement par la branche Ollama de la découverte → **11/101 modèles**.
> - `ModelRuntimeStat` ne stocke que des DURÉES (ETA), pas de qualité. `RunOutcome` (préalable
>   Hermes, ROADMAP §16.7) **n'existe pas** dans le code.
>
> **Ce qu'il manque pour la refermer** (par ordre) : ① un lieu de stockage d'une qualité MESURÉE
> par (modèle, tâche, protocole) — le précédent existe, c'est `ModelRuntimeStat` bucketisé par
> empreinte matérielle ; ② `bench --ecrire` qui persiste (même geste que `backfill_platform_refs`) ;
> ③ `_rang_qualite` qui préfère la mesure à l'a priori ; ④ une VÉRITÉ TERRAIN (échantillons
> annotés) — `bench.py` dit lui-même que sans elle il classe des candidats, il ne les juge pas ;
> ⑤ un appelant pour `qc.py` (le runner nocturne est le candidat naturel).
>
> ### ✅ SUITE DU 2026-08-12→13 : sélection corrigée + `RunOutcome` LIVRÉ
>
> **Sélection (`30cf86d`)** — trois correctifs, sans toucher à la chaîne Ollama/LLM (vérifié :
> tiers `fast`/`default` → `gemma4:12b`, `heavy`/`image` → `qwen3.6:35b`, `get_describer_model`
> et composer/imager/transcriber/enhancer identiques) :
> ① **stratégie `specialisation`** dans `couvrir_classes` — l'anonymizer préfère désormais DEUX
> modèles dédiés à un 2-en-1 (décision Fabien) : `['face','plate']` → `yolov9s-face-lindevs` +
> `license-plate-finetune-v1m`. Anonymiser c'est ne rien rater ; une passe en plus n'est qu'un
> coût, un visage manqué est une fuite. Proxy de spécialisation = nombre de classes déclarées,
> **assumé comme proxy**, à remplacer par la mesure.
> ② **fin du mélange d'échelles** — `quality_index` (−26,7 à 58,7) était comparé à `vram_gb`
> (0,1 à 24 Go) : tout modèle indicé battait mécaniquement tout modèle sans. **Poser le premier
> indice mesuré sur un YOLO aurait faussé toute la sélection vision** — le piège attendait
> exactement ce chantier. Règle : on ne compare des indices que si TOUT le lot en a un.
> ③ `_taille_du_nom` lisait la seule convention YOLO → la taille demandée était **inerte** sur
> les 5 modèles de plaques (départage par VRAM, donc le `v1x` de 227 Mo à toute précision).
>
> **Modèle écarté (`d90be9a`+)** — `face_yolov8m-seg_60` (pack adetailer) retiré du périmètre
> anonymizer : 0 visage sur une scène de rue qui en compte 6-7. ⚠ Son nom EST le nom amont
> (apparié nom+taille) : le renommer éloignerait de l'original. Ce qui trompe est son EMPLACEMENT
> (`segment/faces/` de l'arbre YOLO) → le déplacer quand l'Imager aura l'inpainting.
> Au passage : `is_available` sort des `defaults` du sync et `exclusion` rejoint les clés
> collantes — **la découverte n'a pas autorité pour écraser une décision humaine**.
>
> **`RunOutcome` (`ce4373f`)** — la brique de §16.7 existe. Journal APPEND-ONLY de FAITS, sans
> aucun champ score : « supprimé » ne veut pas dire « mauvais ». Capture strictement IMPLICITE.
> Branché : `task_skeleton` (`produit`/`echec`/`relance` — ce dernier détecté AVANT le passage à
> RUNNING, seul instant où l'info existe) et `transcriber.save_correction` (`corrige`, à la
> FINALISATION seulement). ⚠ **Couverture réelle : converter + reader**, les 8 autres apps
> n'ayant pas adopté le squelette — leur couverture suivra cette adoption, pas une duplication.
>
> **Le transcriber est le BANC DE CALIBRATION**, pas un cas particulier : audio + sortie ASR +
> correction humaine = la seule vérité terrain du dépôt, donc le seul endroit où mesurer si un
> juge LLM **retrouve le verdict humain**. Un juge qui échoue là où la vérité existe n'a pas à
> juger là où elle n'existe pas. Ordre de construction retenu, des FAITS vers les INFÉRENCES :
> `RunOutcome` → divergence inter-modèles → juge LLM calibré.
>
> ### ⚠ CORRECTION DU 13/08 — le corpus de calibration était SURESTIMÉ dans ce qui précède
>
> Mesuré après coup sur les **6** transcripts corrigés : **#46, #134, #142** ont un texte
> **strictement identique** à l'ASR (l'éditeur enregistre une « correction » même sans
> modification) ; **#48** a des segments ASR **cassés** (du JSON brut de LLM a fui dans `text` —
> bug de backend, à traiter à part) ; **#172** est un re-segmentage complet (748 → 106) à texte
> inchangé. **Seul `#135` est exploitable** (divergence 0,5 %, similarité 0,978).
> → **Corpus de calibration réel : 1 cas.** L'étape ③ (juge LLM calibré) **n'est pas mûre** ; il
> faut d'abord accumuler des corrections où l'ASR s'est trompé de MOT — ce que `run_outcome`
> capte désormais au fil de l'eau, à condition que le garde-fou `correction_reelle()` soit là
> (sans lui, les non-corrections auraient noyé le signal).
>
> **Étape ② LIVRÉE (`a333473`)** — `common/services/divergence.py` + `manage.py divergence_asr`.
> **Rien n'est branché sur la heatmap** : la commande sert à REGARDER le signal avant qu'il ne
> pilote quoi que ce soit. Trois pièges trouvés en la mesurant, tous corrigés : l'apostrophe doit
> être un séparateur (33 % → 0 % sur « aujourd'hui » vs « aujourd hui ») ; un passage sans
> vis-à-vis compte comme divergence TOTALE (sinon rater la moitié de l'audio donnait un bon
> score) ; la GRANULARITÉ faussait tout (72 % → 0 % sur `#172`, texte identique mais découpage
> 7× plus fin d'un côté). Détail dans `TRANSCRIBER_CORRECTION.md` §8.3.
>
> ⚠ **5ᵉ récidive de [[feedback_trace_runtime_chaining]]** dans la même session : données écrites
> avant que les workers n'aient chargé le code dont elles dépendent → effacées au tick suivant.
> Règle désormais : **code → redémarrage → données**, jamais l'inverse, pour tout ce qui touche
> `model_manager/services/` ou `common/services/`.

## §REPRISE — 2026-08-13 : CE QUI A ÉTÉ LAISSÉ DE CÔTÉ (inventaire de clôture)

> Relevé exhaustif demandé par Fabien en fin de session. Rien ici n'est bloquant pour ce qui
> tourne ; tout est en revanche **perdu de vue si ce n'est pas écrit**.

### ✅ A. Anonymizer multi-modèles — SECOND PIPELINE SUPPRIMÉ (fait en clôture)

La question initiale de la session portait sur le **floutage visages + plaques**. La SÉLECTION
avait été corrigée le 12/08 (2 modèles dédiés) ; **le pipeline d'exécution l'a été le 13/08**.

Ce qui existait : une chaîne Celery `detect_with_model` × N puis `merge_and_blur_detections`,
avec les masques sérialisés en base64 dans Redis. Ce second chemin avait **perdu** l'interpolation
(⇒ clignotement vidéo), le format de sortie, le statut `RUNNING` (carte figée sur PENDING,
réconciliation aveugle), le `task_id` (**annulation impossible**), l'ETA et la notification ; il
écrivait des images de debug à chaque run ; il transportait des masques pleine résolution
(~2,7 Mo par masque 1080p ⇒ **plusieurs Go par vidéo** — cause probable du « la concaténation ne
fonctionne pas bien » signalé par Fabien) ; et il décodait la vidéo **N+1 fois**.

**Remplacé, pas doublé** : `Anonymize` sait désormais charger **N modèles** et **unir leurs zones
frame par frame**, dans la tâche unique qui portait déjà tout le reste. Supprimés faute
d'appelant : `core/detection_only.py`, `core/merged_blur.py`, les deux tâches Celery, et le
transport Redis de `parallel_detection.py` — qui ne garde que la DÉCISION.

⚠ **Bug préexistant corrigé au passage** : les index de classe étaient calculés par comparaison
BRUTE des libellés. Un modèle déclarant `license_plate` face à une demande `plate` ne rendait
**aucun index** — les 5 modèles morsetechlab ne détectaient donc **rien** par le chemin standard,
en silence. L'appariement passe par `model_coverage.formes_equivalentes()` (rendue publique pour
ça : la couverture rend le vocabulaire de l'APPELANT, le moteur doit refaire la correspondance).

**Validé** (CPU, image réelle) : mono inchangé (19 416 px floutés), multi via le **tirage de
production** identique, suffixe de sortie `_blurred_multi-model` conservé, `unload()` libère tous
les modèles. ⚠ **Reste à valider par Fabien : une VRAIE vidéo sur GPU** — je ne lance pas de
charge GPU sous WSL2.

**Audit des suppressions** — une seule capacité manquait : le repli CPU sur erreur CUDA que
portait `DetectionOnlyProcessor`. Comblée (`ff4ce83`) **sous une autre forme** :
`MemoryManager.reessayer_apres_liberation()` **libère la VRAM des autres modèles puis réessaie**
avant toute dégradation. L'ancien repli basculait sur CPU sans jamais tenter de libérer, alors
que sur ce poste la cause fréquente d'une erreur CUDA est un autre process qui a pris la place —
une contention, pas un modèle trop gros. Asymétrie voulue : **repli CPU pour l'image** (borné),
**refusé pour la vidéo** (il durerait des heures et ressemblerait à un blocage ; un échec net est
plus utile). ⚠ `MODEL_OFFLOAD` n'est PAS une réponse ici : mécanisme *diffusers*, ultralytics ne
l'utilise pas. Le repli codec MJPG→mp4v, lui, existait déjà dans `Anonymize` — rien perdu.

### A-bis. Audit de la chaîne RESSOURCES (demandé par Fabien, 13/08) — 1 défaut corrigé, 1 doublon révélé

**Aucun doublon ni contournement introduits.** Vérifié : `load`/`unload`/`process` passent tous
par les enveloppes du gouverneur (`common/backends/base.py`) ; `load_model` n'est pas enveloppé
mais DÉLÈGUE à `self.load()` — c'est voulu et documenté ; la chaîne du réessai est bouclée
(`reessayer_apres_liberation` → `release_vram` → unloaders → `instance.unload()` →
`release_reservation`) ; l'exclusion porte le bon nom d'app (`anonymizer`). Les quatre mécanismes
VRAM agissent à quatre moments distincts (placement diffusers au chargement / garantie avant load
/ déchargement à la demande / réessai pendant l'inférence) — pas de recouvrement.

⚠ **Défaut RÉELLEMENT introduit, trouvé par cet audit et corrigé** : `_wrap_load` **mesure** la
VRAM prise autour du `load()` et ne retombe sur `recommended_vram_gb` que si la mesure est nulle.
Or `YOLO(chemin)` ne place RIEN sur le GPU (le device n'arrive qu'au `track()`) → on déclarait
**2 Go quel que soit le nombre de modèles**, et le gouverneur aurait laissé un autre process
prendre la place manquante. Corrigé par un attribut d'INSTANCE mis à l'échelle (2 → 4 pour deux
modèles) ; surtout **pas une `property`**, que `backends/manager.py:68` casserait en lisant
l'attribut sur la CLASSE.

🔴 **Doublon PRÉEXISTANT révélé** (pas introduit par cette session) :
`WAMAMemoryTracker` (`model_manager/services/memory_tracker.py`) suit modèles chargés,
`last_used` et inactifs — mais **`register_model` a ZÉRO appelant**, le tracker suit **0 modèle**,
il est **dormant**. Conséquence : le nettoyage des modèles inactifs de `memory_cleaner`, qui s'y
appuie, **ne fait rien**. Le suivi vivant est celui de `resource_governor` (`resident_models`,
`mark_used`, `idle_models`), bâti en cross-process **parce que** l'in-process n'était pas
alimenté — sans que l'ancien soit retiré. À trancher : alimenter le tracker, ou le retirer et
faire consommer le gouverneur par `memory_cleaner`.

⚠ **Limite connue du multi-modèles** : la clé du gouverneur porte UN modèle (`owner#modèle`), donc
`resident_models()` ne montre que le premier — la paire est réservée en une ligne, avec la VRAM
totale. `select_model(prefer_loaded=True)` ne verra donc pas le 2ᵉ modèle comme résident.
Acceptable (ils sont chargés et déchargés ensemble), mais écrit pour ne pas se redécouvrir.

### B. Qualité / auto-amélioration — bloqué sur les DONNÉES, pas sur le code

Voir [[project_model_quality_loop]]. `RunOutcome` et la divergence sont livrés et **actifs** ;
ce qui manque est le corpus : le jeu audio + transcriptions auto + transcription manuelle de
Fabien **n'est pas dans WAMA**, et le Transcriber ne sait pas comparer une transcription qu'il
n'a pas produite. Voie envisagée : la médiathèque. **Non tranché, repoussé volontairement.**

- `qc.py` : toujours **0 consommateur** (visible dans `WAMA_MECANISMES.md`).
- `RunOutcome` : couverture réelle **2 apps sur 10** — suit l'adoption de `run_item_task`.
- Divergence : **non branchée** sur la heatmap (demanderait 2 passes ASR).

### C. Catalogue de modèles

- **10 poids sans origine établie** : `yolov9{s,t}-face-lindevs` (publiés sur **GitHub**, pas HF —
  `platform_ref` supporte déjà le préfixe `github:`) et les 8 `yolov8*_face_plate_*p.pt`.
- **`synthesizer` : 3 `requires` hors registre** (repéré par la page licences, non creusé).
- `verify_models` : **2 faux positifs** (`anonymizer:sam3`, `reader:doctr` — catalogués
  téléchargés, absents du disque) et 30 orphelins `proposed:*`.
- **Étage B** des licences : auteur des **apps** et **fonctions** — `APP_CATALOG` n'a pas de
  champ, et c'est une déclaration INTERNE, pas un fait externe qu'on lit. À trancher.

### D. Documentation & mécanismes

- **45 modules de `common/` non rattachés** au registre (`wama/common/mecanismes.py`) — backlog
  visible en bas de `WAMA_MECANISMES.md`. Tout n'est pas un mécanisme transversal : il faut
  trancher au cas par cas.
- `docs/SEGMENTATION_BLUR.md` : **conservé volontairement** (la fonction décrite existe toujours),
  mais son chemin d'import est faux (`anonymizer.blur_utils` → `wama/anonymizer/core/blur_utils.py`).
- `check_docs` : toujours **2 cassés assumés** (seuil dans `nightly_scenarios.CASSE_ASSUMES`).

### E. Dettes ponctuelles

- **`segment/yolopv2.pt` fait échouer `scan_installed_models` à CHAQUE appel** (TorchScript sans
  `.names`) → bruit permanent dans les logs de l'anonymizer.
- **Transcript #48 : du JSON brut de LLM a fui dans `text`** (`'assistant\n[{"Start":0,…'`) — un
  backend ASR a renvoyé sa réponse non parsée. Bug de production non traité.
- **Migrations NON versionnées** (`.gitignore:13`) : `common.0005`, `common.0006`,
  `model_manager.0012`, `media_library.0012` → relancer `makemigrations && migrate` ailleurs.

## §REPRISE — 2026-08-12 (session UI/média/résidence, instance parallèle) : exclusivité audio + préchargement TTS + RÉSIDENCE des modèles

> Périmètre disjoint du chantier manifestes mené en parallèle (aucun fichier commun).
> Sept commits : `c2ca346` `bd079b2` `bbbffc5` `b59db1d` `30e0057` + TTS gouverneur + résidence.
>
> **① Volet droit du model_manager.** Ordre aligné sur le pied de page (CPU→RAM→GPU→Disque) ;
> **encart CPU créé** (il n'existait pas ; `get_model_manager_stats` expose `cpu_info`).
> Encart Models sorti des « Ressources système » vers une section **Catalogue** propre (un
> décompte de modèles n'est pas une ressource système) via un nouveau `{% block right_panel_top %}`
> **vide et sans cadre par défaut** dans `base.html`. 4ᵉ compteur **Available** : emboîtement
> STRICT vérifié sur les données (0 downloaded-non-available, 0 loaded-non-downloaded) →
> `Loaded ⊆ Downloaded ⊆ Available ⊆ Total`, en grille 2×2 (4 colonnes coupaient les libellés
> dans ~300 px). **Total (129) inclut les modèles PROPOSÉS non installés** ; Available (100)
> est le nombre exploitable — il n'était affiché nulle part. Masquage à la sélection confié à
> `hideOnInspect` + nouveau crochet `onDeselect` de `WamaInspector` (mon masquage maison ne
> couvrait que le clic sur la croix : **Échap laissait le volet à moitié restauré**).
>
> **② Exclusivité média — audit complet, pas seulement le TTS.** La boucle commune existait
> (`wama-app-base.js`, listener `play` en capture, portée le 04/08) et les 11 templates
> porteurs de média remontent tous à `base.html`. Quatre trous : (a) la **vocalisation**
> coupait la lecture AVANT le fetch — au 1er appel le modèle se charge, donc N clics = N
> audios superposés → canal de parole commun **`WamaApp.Speech`** (jeton de génération,
> requête périmée abandonnée et jamais jouée) ; (b) **inter-onglets** → `BroadcastChannel`
> (`wama-media`) ; (c) **RÉGRESSION cam_analyzer** introduite par le portage du 04/08 —
> `syncPlay()` démarre volontairement 4 caméras, le listener les coupait mutuellement ;
> l'échappatoire `data-wama-multiplay` était déclarée et **utilisée nulle part** → posée
> (4/4 mesuré) ; (d) 2 résidus transcriber appelant `pauseAll()` à la main (exclusivité
> INCOMPLÈTE : ni DOM ni voix) → `WamaAudioPlayer.play(id)`. Une seule boucle
> `querySelectorAll(audio, video)` dans tout le dépôt.
>
> **③ Préchargement TTS.** `TTS_SKIP_PRELOAD=1`, documenté « useful in development », était
> posé dans le script de **prod** et faisait un `return` AVANT tout préchargement : Kokoro
> n'était **jamais** chaud et le warm écrit dans `tts_service.py` était du code mort.
> → `TTS_PRELOAD` (liste, défaut `kokoro`) ; `--fast` = `none` (le mode fast ne sautait PAS
> le chargement, seulement l'ATTENTE). `/health` expose `kokoro_resident` (Kokoro vit hors de
> `_current_engine`, donc `loaded_model` restait `null` même à chaud). Coût mesuré : démarrage
> normal +~1 min 38 (chaîne d'imports torchao/TensorFlow, pas Kokoro).
>
> **④ RÉSIDENCE des modèles — le compteur « Loaded » était structurellement aveugle.**
> Mesuré : **aucun code n'écrit jamais `is_loaded=True`** ; 9 des 12 `_discover_*` ne le
> calculent pas ; les 2 qui le font lisent un singleton du process COURANT alors que la
> découverte tourne dans gunicorn et les modèles vivent dans Celery/TTS. `select_model(
> prefer_loaded=True)` était donc **inerte** — c'est le vrai coût, pas l'affichage.
> ⚠ **Aucune brique nouvelle** : le registre Redis inter-process existait déjà
> (`resource_governor`, TTL + purge des lignes de process morts) et `common/backends/base`
> enveloppait déjà `load()`/`unload()`. Manquaient l'identité du modèle et des lecteurs :
> clé d'owner `<backend>:<pid>#<model_key>` (séparateur `#` car les clés catalogue
> contiennent des `:`), clé publiée mémorisée sur l'instance (au unload `_current_model`
> est déjà None ; et une bascule sans unload laisserait une ligne fantôme jusqu'au TTL),
> `resident_models()`, branchement de `select_model` et `api_models_db`. **Rabattu à la
> LECTURE, jamais écrit en base** : un booléen en base ne se répare pas si un worker meurt
> en tenant un modèle. `is_loaded` conservé en complément (Ollama le tient de `/api/ps`).
> **Le service TTS ne déclarait rien au gouverneur** (seulement `configure_cuda_process`,
> qui borne son process sans informer les autres) alors que la docstring de
> `vram_reservation` le désigne nommément — critique depuis que Kokoro est résident →
> déclaration + battement 10 min (une ligne expire à 1 h, Kokoro est résident sans limite).
>
> **Vérifications** (toutes sans charger un modèle sur GPU) : exclusivité média sur 7 pages +
> page de correction, inter-onglets dans les deux sens, 3 chemins de désélection identiques
> sur 6 indicateurs, chaîne de résidence de bout en bout, cycle load/bascule/unload d'un
> `BaseModelBackend` réel (0 ligne fantôme), page rendue avec détenteur déclaré → **Loaded=1**.
> Zéro erreur console partout. `manage.py check` OK. `check_docs` = 2 CASSÉ (inchangé),
> corpus = 110 manifestes à jour.
>
> **⑤ Détection d'inactivité RÉELLE** (dernier maillon). « Inactif » ne pouvait pas se
> distinguer de « chargé » : la liste du volet lisait `WAMAMemoryTracker`, singleton de
> process que **personne n'alimente** (aucun `register_model` dans le dépôt) et qui, même
> alimenté, ne verrait que le process courant → vide en toutes circonstances.
> `mark_used(owner)` + hash Redis **séparé** `wama:vram:last_used` — et non un 3ᵉ champ de la
> ligne de réservation, qui aurait été lu comme illisible donc périmé donc **purgé** par un
> process resté sur l'ancien format (une réservation VIVANTE effacée). Émis par `_wrap_process`
> (3ᵉ enveloppe de `BaseModelBackend`), **avant** l'appel pour qu'un traitement long ne paraisse
> pas inactif. `idle_models(seuil)` : un modèle chargé mais **jamais utilisé** compte depuis son
> chargement — sans ce repli il paraîtrait éternellement actif, alors que c'est le cas le plus
> typique d'occupation inutile. `api_idle_models` rebranché.
> ⚠ **Limite assumée** : ceci corrige le SIGNALEMENT, pas le DÉCLENCHEMENT. « Clean Idle » et
> « Aggressive » passent par `MemoryManager.release_vram()`, qui itère les unloaders du process
> COURANT — depuis le web ils ne peuvent pas décharger un modèle tenu par un worker Celery. Un
> déclenchement inter-process demande un canal de requête que les détenteurs consultent entre
> deux tâches : **conçu, non implémenté**.
>
> **Confirmation en service** : après ton redémarrage, `/health` rend
> `kokoro_resident:["f"]`, `gpu_memory_gb:0.31`, et le registre partagé contient bien
> `{'tts-service': 0.31}` — la chaîne complète fonctionne en production.
>
> **Restes ouverts** : ① déclenchement inter-process du déchargement (ci-dessus) ;
> ② l'exclusivité inter-onglets ne couvre pas « AI-Assistant persistant » (il ne vit que dans
> `home.html` — chantier à part, piste retenue : le loger dans le volet droit existant plutôt
> qu'une 3ᵉ surface flottante ; le coût n'est pas le widget mais l'état du chat entre deux
> pages, qu'aucune librairie de chatbot ne résout pour un backend à outils) ; ③ `api_tracked_models`
> et `api_large_objects` lisent toujours `WAMAMemoryTracker` (tracemalloc — autre finalité,
> non touchés) ; ④ `_cle_de_rang` (ex-`_rang_qualite`, renommé le 12/08 par le chantier
> catalogue) départage encore sur `is_loaded` seul, donc un modèle résident-mais-non-`is_loaded`
> n'y gagne rien. **Sans effet** : `_pick` a déjà filtré sur résidence avant d'appeler
> `_best_by_vram`, et hors `prefer_loaded` le champ vaut False partout — donc égalité, puis
> qualité/VRAM. Laissé tel quel volontairement : cette fonction vient d'être reconçue avec un
> raisonnement documenté sur les échelles incommensurables, à ne pas perturber en fin de session.
>
> **Vérification croisée du renommage `_cle_de_rang`** (demandée par Fabien, MESURÉE en rejouant
> l'ancienne clé sur les mêmes lots — pas une relecture). ① Le renommage est **justifié au-delà du
> cosmétique** : la signature a changé de nature, de fonction de clé `(m)->tuple` à **fabrique de
> clé** `(pool)->(m)->tuple` ; garder l'ancien nom aurait fait échouer tout appelant qui l'aurait
> passé tel quel à `max(key=…)`. Et « qualité » ne décrit plus le critère, qui dépend du lot.
> ② Le correctif est **réel et invisible à la lecture** — deux pathologies symétriques mesurées :
> un indice 58,7 posé sur un YOLO de 0,5 Go lui faisait battre un 8 Go non indexé ; à l'inverse un
> indice **négatif** (−26,7, embeddings) faisait perdre un 12 Go face à un 0,2 Go non indexé.
> ③ La claim « effet sur l'existant : nul » **tient, confrontée au catalogue** : les 3 sources
> sélectionnables sont HOMOGÈNES (ollama 11/11 indexés, anonymizer 0/47, imager 0/9) → modèle
> choisi identique avant/après. C'est donc une protection **en amont**, pas la correction d'un bug
> déjà actif — il se serait déclenché au premier indice mesuré sur un modèle vision.
> ④ **Bémol** : le repli sans indice reste « le plus gros qui tient », soit exactement le critère
> que la docstring de `_best_by_vram` déclare faux au-dessus (argument MoE). Cohérent faute de
> mieux, mais la sélection vision reste aujourd'hui gouvernée par ce critère — la vraie sortie est
> de peupler `quality_index` côté vision (chantier « boucle qualité » déjà ouvert).

## §REPRISE — 2026-08-11 (2ᵉ session, SUITE du soir) : 8 facettes + function + page librairies + avis critique

> Suite de la même session, après le merge : **`params`** porté (8ᵉ facette — multi-schémas,
> trou #10 résolu ; compare sémantique sur fichier main, create-only marqué) ; **page
> librairies** `/model-manager/libraries/` + menu (le registre n'avait aucune surface) ;
> **`write_back_function`** → `UserFunction` (binding `user`, tag `_manifest-gen` — la boucle
> « manifeste LLM → registre → page fonctions » est fermée pour les fonctions Data autorées) ;
> distinction consignée **outils assistant ≠ fonctions Data** (ROADMAP) ; **triade studio**
> livrée plus tôt. Roundtrip : **6/10 à 8/12 projetables**, reste `inspector`/`models`/
> `processing`/`tool_api`. `WAMA_MANIFEST_ARCHITECTURE.md` remis au réel (4 kinds/8 facettes,
> §6quater moteur commun). **Avis critique consigné** (route §10.3 + trou #19) : la chaîne est
> conforme à l'état de l'art (frontière déclaré/dérivé/mesuré ≈ spec/status k8s ; corpus
> multi-kinds ≈ Backstage ; contre-exemple ComfyUI validant l'allowlist-d'abord) ; 2 actions
> retenues — détection de dérive NOCTURNE (trou #19, jamais d'apply auto) et `processing` par
> GABARIT + LLM limité au corps des backends. README mis à jour (studio/assistant/manifestes).

## §REPRISE — 2026-08-11 (2ᵉ session) : write-back §10.3 (7 facettes) + triade studio tool_api

> Bac à sable `git worktree` (`D:\WAMA\wt-regen-converter`, branche `regen/converter`) **mergé
> fast-forward sur `dev`** (5 commits `b791f8a`→`c58bddd`) après validation complète. Contenu :
> `write_back_app` écrit désormais **7 facettes** (`access` DB + `identity`/`ports`/`capabilities`
> → APP_CATALOG, `studio` → GENERIC_APPS, `modes` → APP_MODES, `prompts` → PROMPT_TARGETS) via un
> **moteur commun** (vérité d'état lue au FICHIER par `ast`, entrées générées marquées
> `[manifest-gen app:<id>]`, dry-run/idempotent/réversible, garde `compile()`, chirurgie champ
> par champ sur entrée main — expressions et multi-lignes refusées). Mesure : roundtrip 10 apps
> **5/N à 7/N projetables**, fidélité OK partout ; le converter n'a plus que 4 facettes code-gen
> (`params`, `inspector`, `processing`, `tool_api`). Frontières actées : dérivé (couleur, E/S
> des ports) et mesuré (drapeaux `_conv`/grille) ne se PROJETTENT jamais — trous #16/#17
> consignés `WAMA_APP_GENERATION_ROUTE §11` ; trou d'extract `studio` corrigé (corpus régénéré).
> **Puis (commit suivant)** : audit tool_api → 10 triades complètes mais studio ABSENT →
> **triade studio livrée** (`list_studio_pipelines`/`run_studio_pipeline`/`get_studio_run_status`,
> run=add+start fusionnés, brique partagée `studio/services/launch.py::launch_graph` consommée
> par la vue ET l'outil) ; restes à trancher consignés trou #18 (model_manager, wama_lab,
> media_library écriture). **Suite : facette `params` (1er générateur de fichier par app), puis
> tier difficile (`tool_api`/`processing`) — pilote transcriber avec composition modèles+librairie.**

## §REPRISE — 2026-08-11 : vérification imager + route §10.1 + brique help_about

> **Handoff complet : [`REPRISE_2026-08-11.md`](REPRISE_2026-08-11.md)** — à lire EN PREMIER par
> la prochaine session. Résumé : faux vert `user_settings` imager réparé (écriture à la création,
> modèle legacy retiré) ; purge index.js −60 % (« Démarrer tout » était inopérant) ; **§10.1 de la
> route FAIT** (`GENERIC_APPS` dérive ses E/S des ports, `b91f875`) ; **brique help_about**
> (onglets auto-générés d'APP_CATALOG, routes 20/20 en 200 — 9 apps rendaient 500) ; 19 retards
> doc corrigés ; Playwright MCP réellement fonctionnel ; `start_wama_prod.sh` durci (sudo -n).
> Grille : imager **93 %**, `help_about` vert 10/10, critères `user_settings`+`help_about` durcis.
> **Suite actée : §10.3 — bac à sable de régénération converter, puis transcriber (tous modèles).**

## §REPRISE — 2026-08-10 : outillage — sollicitations de permission divisées par 8 (`4d55fc0`)

> 🔴 **À lire par toute instance en cours** : `.claude/settings.json` a changé (prise en compte à
> chaud) et un 3ᵉ hook est arrivé. **Les hooks ne sont chargés qu'au DÉMARRAGE de session** → une
> instance déjà ouverte ne l'a pas. Redémarrer pour en bénéficier.

Mesure sur les **307 appels shell réels** des transcripts du 06→10/08 (simulation du matcher) :
**163 non couverts (57 %), dont 163 côté PowerShell et 0 côté Bash**. Les trois nettoyages
précédents avaient durci la seule surface Bash. **Toute règle s'écrit sur LES DEUX outils**, dans la
graphie réellement émise (`./venv_win/…` ≠ `.\venv_win\…`).

- 🔴 **Le diagnostic « PIPE » du 06/08 est RÉFUTÉ** : 268 des 279 commandes contenaient un pipe et la
  surface Bash restait couverte à 100 %. Ne pas refuser un pipeline légitime à ce titre.
- **Classe inautorisable** : une règle est un *préfixe*, donc `$var = …` / `(` / `&` / `foreach` ne
  peut JAMAIS être couvert (52 des 74 entrées du brouillon étaient de tels littéraux morts).
  Sortie = encapsuler : `Write <scratchpad>/step.ps1` puis `pwsh -NoProfile -File …`.
  Appliqué par `.claude/hooks/block_composite_oneliner.py` (recette 14/14, outil PowerShell seul).
  Règle consignée dans **`CLAUDE.md`** (§ « une commande commence par un exécutable »).
- 🔴 **`scripts/clean_permissions.ps1` ÉRODAIT la politique** : son filtre ne gardait que les motifs à
  wildcard, donc il supprimait à chaque passage les commandes exactes légitimes —
  `Bash(bash scripts/check_js.sh)`, **prescrite par le skill `cam-analyzer`**, avait ainsi disparu.
  Corrigé (≤ 4 jetons sans guillemets = conservé). Idempotent 255 → 255. La clé `hooks` est bien
  préservée par le script (l.202-209, vérifié).
- Audit des **9 skills** contre l'allowlist + les 3 hooks : **9/9 propres** (1 trou réel corrigé).
- `git add`/`git commit` **restent volontairement en `ask`** (décision 06/08) — le résidu de 7 % est
  à 100 % ce point de vérification voulu.

Détail et méthode : mémoire `reference_permission_allowlist`. **Diagnostiquer en SIMULANT le matcher
sur les transcripts, jamais en lisant l'allowlist** — c'est ce qui a fait rater l'asymétrie 10 jours.

## §REPRISE — 2026-08-10 (2ᵉ session du jour, périmètre disjoint) : SAUVEGARDE / TIRAGE

> ⚠️ **Deux instances ont travaillé le 2026-08-10 sur des périmètres disjoints** — ne pas confondre
> avec le §REPRISE « outillage / permissions » ci-dessus.
>
> **Handoff complet : [`REPRISE_2026-08-10_SAUVEGARDE.md`](REPRISE_2026-08-10_SAUVEGARDE.md)**
> — périmètre : `common/services/`, `model_manager/` (backup), `settings.py`, docs, skills.
> **Aucun fichier d'app touché** : le portage peut reprendre sans rien reprendre d'ici.
>
> Ce qu'il faut retenir avant de coder :
> - **Un seul moteur** pour toute la chaîne : `common/services/mirror_sync.py`. Le tirage est le même
>   appel, source et destination inversées. **3 doubles routes supprimées** — ne pas en réintroduire.
> - **3 points ouverts** : `restore_db` jamais exécuté pour de vrai (fermable sans risque sur le
>   Postgres Windows:5433), tirage des modèles non joué sur les ~325 Go, création du rôle non testable.
> - **Seuil `check_docs` resserré 3 → 2** (`nightly_scenarios.CASSE_ASSUMES`) : le contrat était
>   devenu **aveugle** à une vraie 3ᵉ dérive. Les 2 restantes sont des références EN AVANT légitimes.
> - ⚠ **Ne pas rajouter `pg_dump --create`** (mesuré sans effet) ; ⚠ `mirror_tree` refuse une
>   destination inexistante, par garde volontaire.

## §REPRISE — 2026-08-06 : DEUX handoffs distincts (sessions parallèles)

> ⚠️ **Ne pas confondre.** Deux instances ont travaillé le 2026-08-06 sur des périmètres disjoints :
>
> | Instance | Handoff | Périmètre |
> |---|---|---|
> | **cam_analyzer / volet droit** | [`REPRISE_2026-08-06.md`](REPRISE_2026-08-06.md) | `wama_lab/cam_analyzer/**` — chantier NON terminé (Q3/Q4 à valider avant de coder) |
> | **imager / commun** | [`REPRISE_2026-08-06_IMAGER.md`](REPRISE_2026-08-06_IMAGER.md) | `wama/imager/**` + briques `common/` — **imager 55 % → 77 %** |
>
> Côté imager, le point qui commande la suite : le **volet droit (256 lignes écrites à la main)**
> doit adopter `common/utils/user_settings.py` — brique déjà utilisée par 5 apps portées, qui rend
> inutile toute migration. ⚠️ **Régression connue à réparer en même temps** : depuis le portage de
> la card d'entrée, les réglages du volet ne partent plus à la création (les handlers utilisent
> `get_model_defaults(model)`) — régler « 4 images » n'a aucun effet.
> Deux bugs du COMMUN ont été corrigés : le gate d'appariement (`wama-input-match`) bloquait le
> lancement à vie dès qu'on câblait `onState`, et le poller ciblait la card mère de batch.

---

## §REPRISE-bis — handoff 2026-07-31 soir (session « avatarizer porté à 93 % »)

> **Fait (3 commits, grille re-mesurée à chaque palier)** : F5+F7+F1 (42→56) — card serveur
> UNIQUE `_avatar_card.html` + endpoint `card_html` (la card n'est plus écrite 3 fois),
> cycle button commun, chips schéma (`chip=` + propriété lazy), ProcessingTimeMixin +
> ScopedVisibility + `visible_or_404`, fabrique `make_queue_manipulation_views` (consolidate
> maison SUPPRIMÉ), user_settings, console, Help/About, `@app_access` (1er adopteur du parc).
> F4 (56→61) — MuseTalk/CodeFormer = vrais backends `BaseModelBackend` (sous-processus),
> code déplacé VERBATIM depuis workers.py, `REQUIRED_PACKAGES`, cache HF du sous-processus
> isolé, `utils/model_config.py` = source unique, `settings.MODEL_PATHS['lipsync']`.
> F3+F2 (61→64) — APP_MODES (ports double-entrée image+audio, zéro onglet rendu — décision
> route F2 : qualité = paramètre), modale de LOT (⚙ batch → WamaParams context='batch' →
> batch_update), brique batch-import + barre de détection (panneau maison SUPPRIMÉ),
> ingestion URL fermée bout en bout (show_url → create(source_url) → ensure_local_input).
> Migration `0007` appliquée (base unique WSL2) ; workers Celery redémarrés (code neuf).
>
> **⚠ Brique commune modifiée** : `app_access` (accounts/permissions.py:182) ALIGNÉ sur
> AppAccessMiddleware — les anonymes passent (sinon le 1er adopteur casse l'usage anonyme ;
> les deux couches de défense doivent prendre la MÊME décision).
>
> **Restes avatarizer (5 rouges)** : `model_help`/`model_caps_ui`/`input_match_ui` = gated
> sur une DÉCISION PRODUIT (exposer un select « Moteur » v1.5/v1.0 + Auto dans le panneau ;
> les câbler sans select = briques inertes, refusé) ; `during_preview` (1/10 apps vertes) et
> `recursive_import` (0/10) = trous PLATEFORME, pas spécifiques à l'avatarizer.
> **Piège vécu** : le `pkill -f "celery"` de start_wama_prod.sh tue le wrapper bash qui
> l'invoque si sa propre cmdline contient « celery » → relancer via `setsid nohup bash
> start_wama_prod.sh` (ligne de commande neutre), puis poller.
> **Prochaine action** : finir enhancer (89 %) / converter (86 %) / transcriber (85 %), puis
> chantier UI/UX des cards (2 versions coexistantes) avec la skill frontend-design.

## §REPRISE — handoff 2026-07-31 (session « grille élargie + unification F4 + avatarizer »)

> **CADRAGE, à lire avant tout le reste (Fabien, 2026-07-31).** Les apps ont été construites
> **au fur et à mesure, AVANT la centralisation des mécanismes**. Les écarts mesurés par la grille
> ne sont donc pas des fautes : ce sont des **traces d'antériorité**. Porter une app = **traduire**
> son vocabulaire local vers le contrat commun. Le danger n'est pas l'écart — c'est le **doublon
> silencieux** créé quand on pose la brique commune *à côté* de l'ancien mécanisme sans le retirer.
> **Porter = remplacer, jamais juxtaposer.** (Développé : `WAMA_APP_GENERATION_ROUTE.md` §0.)
>
> ### Fait ce jour
>
> 1. **Grille : 40 → 72 critères mesurés** (`ccbc48f`), les 8 facettes couvertes —
>    **F1:4 · F2:9 · F3:13 · F4:9 · F5:27 · F6:5 · F7:3 · F8:2**. Le dénominateur **varie par app**
>    (60–72) : un critère peut être **non applicable** (état `None`) et sortir du calcul — tout F4
>    pour le converter (ffmpeg/pandoc), les critères prompt pour une app sans champ prompt.
>    5 booléens encore *déclarés* sont passés en *mesurés* (`filemanager_import`, `recursive_import`,
>    `modes`, `layout`, `during_preview`) — ce sont ceux qui dérivaient.
> 2. **Reclaim VRAM unifié** (`1c31c94`) — 3 mécaniques concurrentes réduites à 1 ; auto-enregistrement
>    par `BaseModelBackend`. Détail en F4 de la route.
> 3. **Capacités canoniques** (`8ffac24`) — 98 modèles portent `task`+`modalities`+`inputs_*`.
> 4. **Reader → `select_model`** (`61a666f`) ; **avatarizer 55 → 65 %** (`db21e62`).
> 5. Trous rapides (`31b1edd`) : garde anti-crash converter+reader, réception filemanager **en brique
>    commune** (7 copies supprimées, 3 apps oubliées récupérées), cards d'entrée repliables.
>
> ### ⚠ QUATRE de mes propres critères mesuraient FAUX — vérifier avant de porter sur un score
>
> | Critère | Erreur de mesure |
> |---|---|
> | `during_preview` | Le trou #4 de la route était **périmé** : `wama-inspector.js::_startDuring` consomme bien `?side=during`. Le trou réel = 1 app sur 10 **émet** un partiel. |
> | `model_caps_canonical` | Cherchait le vocabulaire canonique dans les fichiers de l'app → sanctionnait une frontière **délibérée**. Se mesure dans la **découverte**. |
> | `select_model` | Comptait comme trous 3 apps sans aucune sélection à faire. |
> | `vram_unloader` | Faux négatif sur le synthesizer (aucun modèle en process). |
>
> **Règle qui en découle : un critère rouge se confronte au code AVANT d'être porté.** Deux fois
> ce jour, la cible évidente était la mauvaise.
>
> ### Prochaine action
>
> **Finir l'avatarizer** (65 %, 21 écarts). Restent : F5 file (`card_html_endpoint`, `cycle_button`,
> `wama_card`, `processing_time` — ⚠ **migration sur les DEUX bases**) · F3 UI (`card_chips`,
> `model_help`, `inspector_actions`, `model_caps_ui`) · **F4 à trancher** : l'avatarizer lance
> MuseTalk/CodeFormer en **sous-processus**, donc `backend_contract`/`backend_packages`/
> `hf_cache_isolation` sont probablement des **faux négatifs** (même famille que le synthesizer) →
> si confirmé, dénominateur 64 et portage réel ≈ 70 %. **Question ouverte, non tranchée seul.**
>
> Ensuite : **imager** (56 %, chantier long) et **anonymizer** (60 %).
>
> ⚠️ **Avant tout test réel** : redémarrer les workers WSL2 (ils tiennent l'ancien `model_registry`
> en mémoire). `sync_models` a été passé ce jour (99 modèles, +1 = `glm-ocr`).
>
> ---
>
> <details><summary>Handoff précédent — 2026-07-30 (« contrat backend + tirage »), conservé pour la
> leçon de méthode</summary>
>
> **PREMIÈRE ACTION RECOMMANDÉE : compléter `common/services/conformity_checker.py`.** ✅ **FAIT**
> le 2026-07-31 (40 → 72).
> Motif mesuré ce jour : la grille compte 40 critères répartis **F1:3 · F2:5 · F3:6 · F4:1 ·
> F5:25 · F6/F7/F8:0**. C'est une mesure de F5, pas du portage. Un audit humain comptait
> **54 mécanismes** — l'écart n'est pas une erreur d'audit, c'est la grille qui ne voit pas.
> Conséquence vécue : l'imager a gagné le contrat backend, la déclaration VRAM, le tirage
> VRAM-aware, les capacités canoniques et l'appariement d'entrées **sans bouger de 17/40**.
>
> Critères à ajouter, sourcés sur l'inventaire de **`wama/common/README.md`** (= le document de
> référence des briques, à lire AVANT la route) :
> - **F4 réels** : héritage `BaseModelBackend` · `REQUIRED_PACKAGES` déclarés · empreinte VRAM
>   déclarée · adoption `select_model`/`select_model_id` · capacités canoniques ingérées
>   (`task` + `inputs_required/optional`) · option « Auto » présente ET résolue **au lancement**
>   (pas au dépôt) · `WamaModelCaps` · `WamaInputMatch` chargé (⚠ 8 apps ont la card commune,
>   **une seule** charge la brique — support ≠ adoption).
> - **F6/F7/F8** : aucun critère aujourd'hui — à instruire à partir de la route.
>
> **Ensuite, dans cet ordre** : (1) **anonymizer** — dernier sélecteur concurrent
> (`utils/model_selector.py`, ~800 l.), migration balisée vers `select_model(classes=…)`,
> paramètre écrit POUR lui ; (2) **imager** — chantier long, 17/40 mais F4 désormais solide.
>
> ⚠️ **À faire tourner avant tout test réel** : redémarrer les workers WSL2 **puis**
> `manage.py sync_models` — les workers tiennent l'ancien `model_registry` en mémoire, donc la
> base live n'a pas encore les capacités canoniques.
>
> **Leçon de méthode à ne pas reperdre** (3 occurrences ce jour) : une information existait, dans
> un document qu'aucun chemin de lecture ne désignait, et elle a été réinventée à côté —
> `INPUT_MODEL_MATCHING.md`, `wama/common/README.md`, puis le pattern « résoudre l'auto au
> lancement » que composer appliquait déjà. Les deux documents sont raccrochés au graphe et le
> skill `/port-app` porte désormais la règle : **lire l'app qui l'a déjà fait avant d'écrire.**
>
> </details>

## §REPRISE — handoff 2026-07-29

> **Point de départ session neuve : [`REPRISE_2026-07-29.md`](REPRISE_2026-07-29.md)** — à lire EN
> ENTIER avant de toucher au code (périmètre multi-instances, pièges, reste à faire priorisé).

Première action au redémarrage : **bande de couverture sous la timeline du cam_analyzer**
(conception arrêtée, source `config['analyzed_ranges']` déjà peuplée, aucun calcul nouveau).

⚠ Partition : une autre instance tient l'infra GPU/ressources (`resource_governor.py`,
`remote_backup.py` modifié non commité, `wama/celery.py`, `memory_manager.py`) — ne pas y toucher.

## §REPRISE — session 2026-08-04 (prospection, sélection par qualité, couverture)

> **Handoff complet : [`REPRISE_2026-08-04.md`](REPRISE_2026-08-04.md)** — à lire en premier.
>
> **Le piège de la session, à connaître avant tout** : après une modification Python touchant le
> catalogue, **redémarrer les workers Celery**. Le Beat `model-manager-reconcile` (2 h) tournait
> avec l'ancien code et réécrasait les capacités enrichies — une heure de diagnostic pour un
> problème qui n'était **pas** dans le code. Symptôme : « correct quand je l'écris, faux dix
> minutes plus tard ».
>
> **Chantier suivant : anonymizer.** ⚠ NE PAS « porter sur `select_model()` puis supprimer » —
> `select_best_models_by_precision()` résout un **recouvrement** (plusieurs modèles pour couvrir
> N classes) que `select_model()` ne peut pas faire. La brique de remplacement est écrite et
> vérifiée (`common/services/model_coverage.py`), **pas encore adoptée**. Prérequis :
> tests de non-régression sur floutage visages/plaques AVANT tout retrait.
>
> Deux défauts connus non corrigés : plafonds VRAM en constantes calibrées pour ce PC (faux sur
> le R760xa) ; `vram_gb` dérivé du fichier et non de `/api/show`. Détail et séquence dans le
> handoff.

## §REPRISE — session 2026-08-03 (validation smoke + outils §16.9 + composition)

> Session mono-instance, champ libre. Le handoff `REPRISE_2026-08-02.md` §4 (« rien n'est
> validé navigateur/Celery ») est SOLDÉ, et les chantiers §16.9 ①② + SPEC §7.4-2/3 sont livrés.

**Smoke réel (tout vert, corrections comprises)** :
- **Pipeline studio de bout en bout** : runs #10 (converter), #11 (describer image), #12
  (describer texte) SUCCESS via `execute_tool`. Sortie vérifiée ffprobe (mp3 mono 22 050 Hz).
- **2 pannes réelles trouvées et corrigées** : ① les workers Celery tournaient sur du code
  ANTÉRIEUR aux commits du 02/08 (redémarrés — après une modif de code, redémarrer les
  workers, pas seulement gunicorn) ; ② **interblocage structurel** : `run_pipeline_task`
  (pool solo, file `default`) attendait sa propre tâche converter dispatchée dans la MÊME
  file → route `wama.studio.tasks.*` vers une file `studio` dédiée + worker dans les deux
  start scripts (`fix(studio)`). Un run studio lancé depuis l'UI nécessite le gunicorn
  rechargé (fait, HUP).
- **Converter UI** : les 4 réglages (`gif_fps`, `gif_width`, `sample_rate`, `channels`)
  visibles dans la modale ⚙, filtrés par type de média, valeurs persistées, 0 erreur console
  (Playwright + session `pw_smoke` ; cookie = `wama_sessionid`, pas `sessionid`).
- **Describer** : les 2 chemins corrigés exercés sur vrais médias ; le retour « texte brut »
  sur un texte court est VOULU (`word_count ≤ max_length` → formatage direct, pas de LLM).

**Livré** :
- `manage.py check_redundancy` (§16.9 ②) — acceptation **6/6** sur le code pré-correctif ;
  arbre courant : **73 trouvailles (58 A / 0 B / 15 C)** = backlog de triage (familles ×3 apps
  `_derive`/`_enrich`/`_probe`, `_ENHANCER_VALID_MODELS`, copie `converter/views.py:229`).
- `manage.py doc_facts` (§16.9 ①) — blocs `WAMA:FAITS(id)` dans GENERATION_ROUTE / SPEC /
  ARCHITECTURE, `--check` refuse un bloc périmé. Première passe : 165 args mesurés vs 157 recopiés.
- Composition (SPEC §7.4) : **étapes 2 et 3 faites** (`requires` + `resolve_requires()` +
  refus des pendantes ; kind `library`, `faster-whisper` semé, corpus = 11 manifestes).
  Reste l'étape 4 : rôle wama-dev-ai « projet GitHub → manifeste library ».

**Addendum 03/08 (même session) — triage des 73 redondances : 73 → 5.**
Un vrai bug trouvé et corrigé au passage (`document_export` lisait `description.output_format`,
champ renommé 0008 → tout export PDF/DOCX de description crashait ; validé sur PDF réel).
Résorptions : `schema_choice_values()` (nouvelle brique param_schema, valide enhancer + describer),
`probe_duration_seconds` adopté par le video_backend (gif réel validé), jeux d'extensions du
describer unifiés (`content_analyzer.DESCRIBER_*_EXTS`), `app_registry.VOICE_SAMPLE_EXTENSIONS`
(recopié ×5 avant, migration avatarizer 0008 appliquée). Les câblages déclaratifs légitimes sont
assumés par pragma `# wama:redondance-ok — <raison>` ; les 5 trouvailles restantes = dette du
port anonymizer, laissées VISIBLES exprès. ⚠ Leçon re-vécue : un worker Celery solo n'importe le
code qu'une fois — redémarrer après édition d'un backend (le 1er gif « SUCCESS » tournait sur
l'ancien code).

**Addendum 03/08 soir — crash hôte 18:09 + rôle librarian livré.**
Crash hôte pendant le 3ᵉ pilote du rôle wama-dev-ai « librarian » : 1er crash INSTRUMENTÉ —
signature FREEZE (hwlog : VRAM 13,4 Go → 60 Mo à 18:09:42, lignes horaires jusqu'au reboot
21:48, cap 320 W actif, 20-70 W au décrochage) ≠ coupure froide du 31/07. Analyse dans la
mémoire d'enquête ; règle élargie : pas d'enchaînements de chargements Ollama hôte par Claude.
Le rôle « librarian » (§7.4-4) est LIVRÉ en pilote : --dist = accord total avec l'extraction
mécanique ; --repo = null honnêtes, zéro invention ; sorties PENDING_HUMAN_VALIDATION dans
`wama-dev-ai/outputs/` (2 à relire). Pile relancée post-reboot : gunicorn + 3 workers
(gpu/default/studio) + beat, vérifiés.

**Addendum 03/08 — port anonymizer PALIER 1 (cœur schéma-driven, F3 backend).**
`save_media_settings` réécrit sur `coerce_schema_values` (les listes slider/bool en dur sont
mortes) + **fix sécurité : scoping par user** (l'ancien `get(pk=…)` laissait éditer le média
d'autrui — probe : autre user → 404, valeur intacte). `use_segmentation` déclaré au schéma
(consommé mais invisible — leçon converter). Forms : bornes des sliders DÉRIVÉES du schéma —
les copies locales avaient divergé (`blur_ratio` 1–49/2 vs 1–100/1, `roi_enlargement` 0.5–1.5
vs 1.0–2.0 ; le backend normalise les noyaux, le schéma fait foi) ; `MediaForm`/
`GlobalSettingsForm` morts supprimés ; `UserSettingsEdit` conservé (consommé par accounts).
**check_redundancy : « Aucune recopie détectée »** — seuil nocturne à 0. Gate consistency 6/6
(il a d'ailleurs attrapé en direct le corpus et le bloc de faits périmés par l'ajout au schéma).
**Reste du port (paliers suivants)** : 29 rouges mesurés — modales WamaParams (les forms legacy
meurent), card partial + toolbar + batch (F5), partage F7, prompt_skill/enrich (F6).

## §REPRISE — session 2026-08-03 : port anonymizer PALIER 2 (UI) — ✅ LIVRÉ

> Session mono-instance. Palier 2 exécuté d'un trait (6 étapes du handoff), validé
> navigateur (Playwright authentifié, 0 erreur console) et re-mesuré.

**Résultat grille** : anonymizer **58 % → 93 %** (68✅/2🔶/4❌ sur 74) — meilleure app de la
grille. Les 4 rouges restants sont ASSUMÉS (justification confrontée au code, pas des trous) :
- `input_match_ui` + `model_caps_ui` : câblage volontairement NON posé — tous les modèles
  anonymizer déclarent `modalities image+vidéo` (48 entrées catalogue vérifiées) et aucun
  `<select>` ne dépend du modèle choisi → la brique serait un mécanisme PRÉSENT MAIS INERTE
  (danger nommé du cadrage 31/07). L'équivalent réel côté serveur : `get_model_recommendations`.
- `during_preview` : demanderait une émission d'aperçu PENDANT le floutage côté pipeline (feature,
  pas un câblage) ; `recursive_import` : rouge sur 10/10 apps (trou de grille, pas d'app).

**Livré (palier 2)** — REMPLACEMENTS, pas de juxtaposition :
1. IndexView : `auto_wrap_orphans`+`build_batches_list`+`apply_queue_sort_filter`+
   `reconcile_orphaned_running` (les `_get_anonymizer_batches_list`/refresh legacy sont MORTS,
   partials `upload/*` et `widgets/` supprimés, `batch.js` orphelin supprimé) ;
2. `_new_item_card` en tête (fichier+URL+batch+médiathèque, repliable) — le volet droit ne porte
   plus l'import ; `WAMA_INGEST` sur Media + `ensure_local_input` en tête de tâche ;
3. Card = partial serveur unique `_media_card.html` (.wama-card, chips du SCHÉMA via
   `chips_by_section`, `_card_progress`, `_cycle_button`) + endpoint `card_html` + `queue.js`
   (polling par card, refresh sur transition) ;
4. Modale item = **1er consommateur de `WamaParams.renderSettingsModal`** + pied commun
   `_settings_modal_footer` + save&restart (contrat composer) ; modale batch context:'batch'
   (contrat reader) + `batch_update` ; inspecteur `initFromSchema` (pont `dom_id.panel` legacy) ;
   ModelForms legacy morts (les 2 pragmas `wama:redondance-ok` sont partis avec) ;
5. `start`/`stop`/`start_all`/`batch_start` avec `begin_processing` + `@app_access` ; ETA seedée
   (`anonymizer_eta_key_size` partagée estimate↔record_run, simulation seedée par l'EMA) ;
6. F7 : `ScopedVisibility`+`ScopedManager` sur Media ET BatchAnonymizer (migration 0023),
   lectures `visible_or_404` (preview/download/progress/card_html/batch_download) ;
   F6 : skill `common/prompt_skills/anonymizer-detection.md` + domain déclaré dans
   PROMPT_TARGETS + ✨ WamaPromptEnrich (panel + modale).

**Leçon de smoke (03/08)** : la config d'app (`window.WAMA_ANON`) doit être définie AVANT les
scripts d'app qui la capturent au chargement — inline APRÈS eux, toutes les URLs étaient vides
(toast « Impossible de charger les paramètres »). Corrigé + consigné dans le template.

**Bug transverse corrigé au passage** : `batch_file.seek(0)` ORPHELIN après adoption de
`parse_batch_file_from_request` (la brique consomme FILES) → NameError latent dans batch_create
de **enhancer (×2), describer, transcriber** (l'anonymizer avait le même). Re-lire
`request.FILES.get('batch_file')` avant l'archivage. Commit séparé.

**Restes connus** : restart du worker Celery à faire pour activer `tasks.py` (ensure_local_input
+ ETA record_run) — non fait en session, des tâches GPU d'autres apps pouvaient tourner ;
avatarizer = dernière app à porter (post-studio).


---

## §REPRISE — addendum 03/08 après-midi : PASSE DE FINITION des apps avancées (imager exclu)

> Suite immédiate du port anonymizer, demande Fabien : « terminer au mieux les plus avancées,
> Imager pour une prochaine passe ». 4 commits (`7a54e22` enhancer, transcriber+brique,
> converter, `a57fd48` balayage), consistency 6/6, corpus régénéré.

**Grille finale (hors imager 55 %)** : enhancer **94** · transcriber **94** · anonymizer **93** ·
converter **93** · avatarizer **92** · composer **87** · reader **85** · synthesizer **84** ·
describer **83**. Les rouges restants sont majoritairement la famille ASSUMÉE
(input_match/model_caps inertes sans cas réel, during_preview = feature pipeline,
recursive_import = 0/10) — voir triages ci-dessous.

**Livré par app** :
- enhancer : chips du schéma (remplacent les badges hand-built des 2 cards), modale batch
  WamaParams context:'batch' (mort du détournement `_enhancerBatchId`), **ETA batch RÉPARÉE**
  (eta_ids liste→CSV : le data-eta-ids ne matchait jamais), auto_wrap par brique, queue_count.
- transcriber : STATUS_CHOICES + champ `error_message` (migration 0017, persisté au FAILURE,
  affiché card, branché reconcile), modale batch dédiée context:'batch' (mort de
  `_settingsBatchId`), duplication par brique commune — **le focus post-duplication REMONTE
  dans queue-actions.js** (toutes les apps l'ont maintenant), ordre boutons rétabli à la mesure.
- converter : APP_MODES 5 domaines par nature, chips schéma (badge « → .fmt » mort), modale
  batch schéma-driven avec le MÊME optionsResolver que la modale item ; `quality_preset` entre
  au schéma (champ consommé par batch_update mais non déclaré — récidive leçon converter).
- avatarizer : TRIAGE seulement — model_help NON câblable honnêtement (aucun select de modèle,
  MuseTalk v1.5 unique). Reste 92 %.
- composer/synthesizer/reader/describer (balayage) : **F7 complet** (ScopedVisibility work+batch,
  migrations, lectures visible_or_404) + `@app_access` sur 16 vues de lancement ; reader passe à
  la brique de duplication + pied de modale commun ; composer gagne le ✨ prompt musical ;
  describer débarrassé d'un faux DOUBLE-FIRE (littéral dans un commentaire).

**Récidive à retenir** : 3 faux rouges/partiels venaient de LITTÉRAUX dans des commentaires
(`.duplicate-btn`, `fa-download`, `alert()`) — le checker greppe le fichier entier. Formuler les
commentaires sans le littéral mesuré.

**Restes connus** : imager (55 %) = prochaine passe ; params_modal_batch composer/synthesizer/
describer + card_chips composer/synthesizer/describer/reader = paliers ciblés restants ;
worker Celery à relancer pour tasks.py anonymizer (ingest+ETA) ; gunicorn déjà rechargé.


---

## §REPRISE — addendum 03/08 soir : harmonisation UI des cards (`825b5ed`) + INVENTAIRE design

Constats Fabien vérifiés au Playwright (9 apps, styles calculés + clics, 0 erreur console) :
1. **Card mère à bords droits sur 9 apps** — la brique `_batch_card` était bien utilisée
   PARTOUT (synthesizer compris) mais l'arrondi/padding vivait dans un patch SCOPÉ reader
   (`.wcv3--batch-parent`, wama-card-v3.css) qui attendait « le portage d'un bloc ». → Passé
   au COMMUN (`.wama-card.is-batch`, wama-inspector.css), patch reader absorbé/retiré.
2. **Cards d'entrée qui ne se dépliaient pas** — deux causes empilées : (a) le JS
   `wama-new-item-card.js` n'écoutait que l'en-tête + le focus de l'entrée primaire, or pour
   les apps « fichier » l'entrée primaire est un input CACHÉ (composer marchait car son prompt
   est visible) → dépliage à TOUTE interaction avec la card repliée ; (b) describer/avatarizer
   passaient `collapsible=True` sans jamais inclure le script (support ≠ adoption) → la brique
   PORTE désormais son `<script>` (précédent `_global_progress.html`) + garde anti-double-init.
3. **Anonymizer** — filles sans contour (il manquait le squelette `.synthesis-card`) ; barre
   de progression coincée dans la section État → état en `no_bar` + barre `bar_only` pleine
   largeur seule en bas.

### INVENTAIRE : éléments de design des cards — commun vs app-local (mesuré 03/08)

| Élément | Domicile | Adoption réelle |
|---|---|---|
| Squelette card fille (contour/arrondi/padding/accents d'état) | `.synthesis-card` app_modern.css (COMMUN) | 7 cards (anonymizer, avatarizer, describer, enhancer×2, synthesizer, transcriber) + la mère commune ; reader = wcv3 auto-stylé ; **composer = `.generation-card` app-local ; converter = `.job-card` ?** |
| Card mère batch | brique `_batch_card.html` + `.is-batch` (COMMUN depuis ce soir) | **10/10** |
| Progression (badge/%/ETA/barre) | `_card_progress.html` (COMMUN) | 7 cards — manquent **composer, reader** (reader a son équivalent wcv3) |
| Chips de réglages | `_card_chips.html` + `chips_by_section` (COMMUN) | 7 cards — manquent **composer, synthesizer, describer** (describer a la brique dans d'autres zones ?) et imager |
| Aperçu d'état textuel | `_card_state.html` (COMMUN) | **2 seulement** (converter, transcriber) |
| **Anatomie v3 « sections × labels »** (`wcv3-sec`, `wcv3-lbl` ENTRÉE/RÉGLAGES/SORTIE/ÉTAT, séparateurs, cellule barre pleine largeur) | CSS commun `wama-card-v3.css`… | …mais consommée par **2 cards seulement (reader, transcriber)** — c'est LE gros écart : lignes de séparation et noms de sections restent invisibles sur 7 apps |
| Card d'entrée | `_new_item_card.html` (auto-portée depuis ce soir) | 9/10 (imager ?) |

**Prochain palier UI proposé** : porter l'anatomie v3 (sections/labels/séparateurs) de
reader/transcriber vers les 7 autres cards — c'est le « portage v3 de la brique » annoncé dans
wama-card-v3.css ; candidates faciles d'abord (enhancer/anonymizer, déjà chips+progress).
Composer/imager à traiter lors de leurs ports respectifs.


---

## §REPRISE — addendum 03/08 nuit : avatarizer sans « modes » + audit cliquabilité (`2890c3c`)

1. **Avatarizer : le couple rapide/qualité est MORT** (décision route F2 enfin appliquée à
   l'UI — le backend n'a jamais lu que `use_enhancer`) : l'« Amélioration CodeFormer » est le
   seul contrôle de qualité, partout (panel, modale item, modale batch, chips). `quality_mode`
   survit en champ DÉRIVÉ (`'quality' si use_enhancer sinon 'fast'`) pour les clés ETA et les
   données ; `--quality` des fichiers batch = alias de l'enhancer (compat).
2. **Audit cliquabilité Playwright (9 apps)** — clic card → sélection inspecteur + modale ⚙ :
   - avatarizer : la card n'avait PAS de `data-id` (seulement `data-job-id`) →
     `WamaInspector.selectItem` échouait en silence = « cards pas cliquables ». data-id +
     data-preview-url posés. **data-id = contrat des briques, à vérifier à chaque nouvelle card.**
   - volet ACTIONS vide sur enhancer (2 domaines), synthesizer, avatarizer :
     `renderItemActions`/`renderBatchActions` (cloneActions) manquaient — ajoutés.
   - synthesizer : `?side=input` sur une entrée NON-fichier (texte) → `dict(None)` = 500 dans
     l'aperçu commun → repli gracieux (sortie sinon message) dans preview_utils.
   - Résultat final : 9/9 sélection + actions + modale, 0 erreur console, 0 HTTP 5xx.


---

## §REPRISE — addendum 03/08 tard : résidus volet ACTIONS + erreur résumée + RESTART pile (`901cd22`)

1. **Volet ACTIONS = contextuel UNIQUEMENT** : le trio Tout démarrer/télécharger/vider a quitté
   le volet droit d'avatarizer ET d'anonymizer (résidu — le domicile des actions de FILE est la
   toolbar commune). Découverte au passage : la toolbar avatarizer pointait des ids que son JS
   n'écoutait PAS (boutons décoratifs) → rebranchée ; anonymizer/process.js (bouton global mort)
   supprimé. ⚠ Le seul « stop global » anonymizer restant = ⏹ par card.
2. **7e récidive `{# #}` multi-ligne** (modale avatarizer, commentaire rendu en texte) → comment.
3. **Erreur résumée à l'inspecteur** : `_short_error()` au domicile commun (detail_registry) —
   la traceback complète reste en base/logs, le volet INFOS n'affiche que la ligne d'exception.
4. **RESTART COMPLET de la pile WSL2** (start_wama_prod.sh, vérifié 0 RUNNING avant) — le restart
   Celery différé deux fois est SOLDÉ : les workers tournaient depuis AVANT les patches xformers
   (GroupName) et le port anonymizer. La traceback MuseTalk de Fabien venait de là (patch déjà
   sur disque, module pré-patch en mémoire). MuseTalk, ingest anonymizer et ETA record_run actifs.


---

## §REPRISE — prochaine session (photo au 2026-08-03 fin de soirée)

**État vérifié en clôture** : arbre git PROPRE sur dev, consistency **6/6**, grille re-mesurée
(bouton « Re-mesurer » sur /common/apps/ désormais, staff), pile WSL2 RESTARTÉE ce soir
(gunicorn + workers Celery — patches xformers et tasks.py anonymizer actifs). Scores :
enhancer 94 · transcriber 94 · anonymizer 93 · converter 93 · avatarizer 92 · composer 87 ·
reader 85 · synthesizer 84 · describer 83 · imager 55.

**Ordre de reprise recommandé** :
1. **Re-tester MuseTalk** (relancer ↻ la card avatarizer en échec — le crash GroupName venait
   des workers pré-patch, restart fait) ; vérifier au passage l'ETA record_run anonymizer.
2. **Imager** (55 %) : dernier gros port schéma-driven (recette /port-app, anonymizer = gabarit
   le plus récent ; lire le §REPRISE 03/08 pour les pièges — config d'app AVANT scripts, data-id).
3. **Portage v3 de l'anatomie de card** (sections/labels/séparateurs) : consommée par 2 cards
   sur 10 seulement — candidates faciles enhancer/anonymizer (inventaire §03/08 soir).
4. Paliers ciblés : chips + modale batch composer/synthesizer/describer (+chips reader).
5. §18.2 `check_structure` (conçu, acceptation 12+1 violations) — à créer AVANT la 1re app data.

**Leçons durcies cette session** (détail dans les addenda 03/08) : data-id = contrat des
briques sur toute card ; config d'app AVANT les scripts qui la capturent ; un littéral mesuré
par le checker ne va JAMAIS dans un commentaire ; {% templatetag opencomment %} multi-ligne
interdit (7 récidives) ; support ≠ adoption (script porté par la brique désormais).

---

## §REPRISE — 2026-08-05 : handoff catalogue/taxonomie

> **Handoff complet : [`REPRISE_2026-08-05.md`](REPRISE_2026-08-05.md)** — 21 commits côté
> catalogue. À lire avant de reprendre le portage d'apps.
>
> **Le point qui commande la suite** : le portage de l'anonymizer est **REVERTÉ** (`2b1a961`) et
> ne doit pas être rouvert avant que le catalogue porte une **qualité mesurée** pour les modèles
> vision (`quality_index` = 0/48 vision contre 11/11 LLM). L'A/B GPU sur médias réels a montré
> 7 pertes de détection sur 15 cas — 5 boîtes → 0 sur des visages. Le classement codé en dur
> qu'on remplaçait PORTAIT une connaissance de qualité écrite nulle part ; la centralisation
> l'a détruite. Refaire le portage à l'identique coûterait un second A/B.

---

## §REPRISE — 2026-08-05 : PARTITION MULTI-INSTANCES (à lire avant de toucher au dépôt)

> **Deux instances travaillent en parallèle. Partition déclarée par Fabien le 2026-08-05.**
>
> | Instance | Périmètre RÉSERVÉ | Ne touche pas |
> |---|---|---|
> | **Cam analyzer / profondeur** | `wama_lab/**` — chaîne de traitement, modèles de profondeur | `wama/model_manager/**` |
> | **Catalogue / taxonomie** (celle-ci) | `wama/model_manager/**`, `wama/common/services/**`, prospection, banc | `wama_lab/**` |
>
> **Ce que l'instance catalogue a déjà livré et qui SERT directement le chantier profondeur** —
> à reprendre plutôt qu'à refaire :
> - `CAM_ANALYZER_CHAINE_TRAITEMENT.md` §[E] : piste profondeur instruite (5 usages, limites
>   chiffrées, ancrage sur la limite connue n°7 « reflets fantômes ») — commit `16a70b8`,
>   **documentation seule, aucun code**. C'est le seul fichier de `wama_lab/` que j'aie touché ;
>   il est COMMITTÉ, donc pas de conflit avec des éditions en cours.
> - Candidat identifié : **`depth-anything/DA3METRIC-LARGE`, métrique et Apache-2.0** (716 k dl,
>   relevé via `manage.py prospect_models --app <app> --search`). Licence sans objet.
> - Le rig est fait de caméras **perspectives** (61°/31°), PAS d'un capteur équirectangulaire :
>   les modèles monoculaires s'appliquent caméra par caméra, sans reprojection ni couture.
> - `manage.py bench --task <tâche>` (commit `082c419`) accueillerait un protocole
>   `depth-estimation` — une entrée dans `PROTOCOLES` (`model_manager/services/bench.py`),
>   pas une commande de plus.
> - ⚠ **Si un modèle de profondeur entre au catalogue** : la tâche `depth-estimation` n'est PAS
>   déclarée dans `ModelTask` (elle figure en `TACHES_CONNUES_NON_PORTEES`).
>   `check_model_taxonomy` sortira en 1. C'est voulu — il faut la déclarer, pas contourner.
>   Cette déclaration est dans MON périmètre : me la demander plutôt que d'éditer `models.py`.
>
> Rappels de discipline : `git commit <chemins explicites>` uniquement — jamais `git add -A`,
> l'index est partagé. `PROJECT_STATUS.md` s'édite en petits blocs, relus avant chaque édition.

---

## §REPRISE — session 2026-08-04 (nuit) : retest MuseTalk ✅ + 3 fixes issus de l'usage réel

> Session mono-instance côté apps ; une AUTRE instance travaillait en parallèle sur
> `common/manifests/**` (kind library, commits a752798/60d51e3…) — partition respectée.
> Point 1 de l'ordre de reprise du 03/08 SOLDÉ : **MuseTalk re-testé par Fabien, génération OK.**
> Les 3 fixes viennent de son usage réel dans la foulée ; chacun validé Playwright (pw_smoke)
> avant commit. Windows a crashé en cours de session (signatures ouvertes, cf. mémoire hwlog) —
> reprise sans perte, les éditions disque avaient survécu.

| Commit | Fix | Cause racine |
|---|---|---|
| `f430a7f` | avatarizer : import audio (filemanager ET local) ne retenait RIEN | `detectAndHandle` est **async** ; appelée sans `await` dans la garde de `handleAudioFile`, sa Promise (toujours truthy) déclenchait le `return`. Seule app touchée : tous les autres call-sites font `await`. |
| `fa85002` | lectures empilées (avatarizer, et partout) | le fix « une seule lecture à la fois » vivait dans le SEUL transcriber (`edit.js`). **Porté en brique commune** : `wama-app-base.js` (listener `play` en capture + `WamaApp.pauseDomMedia`), pont bidirectionnel avec `WamaAudioPlayer` (ses `Audio()` sont HORS DOM), doublon transcriber RETIRÉ, échappatoire `data-wama-multiplay`. Global via `base.html` → rien à porter par app. |
| `f35199a` | filemanager : « Access denied » au déplacement des sorties TTS | garde traversal de `is_path_allowed` en SOUS-CHAÎNE (`'..' in path`) : tout nom contenant `...` (noms TTS tronqués) était refusé. → test par SEGMENT (`Path(path).parts`), aligné sur les 2 autres gardes du fichier. |

**Leçons** : ① une brique commune **async** appelée dans une garde synchrone = Promise truthy =
court-circuit silencieux — vérifier les call-sites à chaque brique passée async ; ② une garde
sécurité écrite en sous-chaîne se déclenche sur des données légitimes — tester par segment ;
③ le refus de déplacement HORS temp reste silencieux côté client (console.log sans toast,
`check_callback`) — petit trou « jamais d'échec silencieux » à combler à l'occasion.

**DÉCISION Fabien 04/08 — déplacement dans l'arbre : temp-only CONFIRMÉ, périmètre clos** :
le déplacement reste limité à `Mes fichiers/Temporaires` (client `check_callback` + serveur
`api_move`, design de 2026-01-05). PAS de déplacement dans les dossiers d'app (risque de casser
les entrées/sorties référencées en base), NI sur les montages distants (déplacer par erreur dans
un dossier de datasets = trop risqué). Si le besoin apparaît un jour : passer par une **validation
explicite d'un droit de déplacement par dossier distant** (à concevoir à ce moment-là, pas avant).
Remplace la piste « autoriser les dossiers montés » évoquée plus haut dans cette session.
Reste ouvert (inchangé) : le refus client est silencieux → toast « Déplacement limité aux
fichiers temporaires » à ajouter à l'occasion.

**Ordre de reprise 03/08 mis à jour** : 1.✅ MuseTalk → suivants inchangés :
**2. imager (55 %)** port schéma-driven (gabarit anonymizer) · 3. anatomie card v3 (enhancer/
anonymizer) · 4. chips+modale batch composer/synthesizer/describer · 5. §18.2 `check_structure`.
Contrôles mécaniques : passés au vert en début de session (04/08) — 3 CASSÉ connus, corpus à
jour, fidélité OK ; non re-lancés après les fixes (JS/garde serveur, aucun critère mesuré touché).
Données de test : `pw_smoke` a désormais `synthesizer/21/output/tts_smoke_test.wav` (semé pour
les smokes audio, à garder).

---

## §REPRISE — 2026-08-13 (journée, instance transverse) : SÉCURITÉ + CARTE DES MÉCANISMES + API

> Session CLOSE — aucun chantier laissé ouvert de ce périmètre. Tout est tracé dans les docs de
> domaine ; ce bloc n'est que le pointeur de reprise.

- **Contrôles sécurité nocturnes** (évaluation Aikido → équivalents locaux, ROADMAP §16.10) :
  `check_dep_vulns` (OSV, baseline-cliquet `tools/security/osv_baseline.json` par venv) +
  `check_secret_leaks` (gitleaks historique complet + hook pre-commit, provisioning
  `scripts/fetch_security_tools.py`). Dette actionnable relevée : palier upgrade Django/pillow/
  aiohttp à coupler au restart. Options non ouvertes (SAST, Aikido, Zen) : §16.10.
- **Carte des mécanismes 30 → 61** (`WAMA_MECANISMES.md`, sous-tables par domaine) : balayage
  étendu à `model_manager/services` + `studio/services`, couche **UI générée** au grain
  mécanisme (front js/partials = annexes, comptage étendu .html/.js), `ASSUMES_LOCAUX` (18,
  raisons datées) → **backlog non-rattachés = 0** ; seul ⚠0 restant = `qc` (décision boucle
  qualité à prendre). Détail : mémoire `project_auto_maintenance_docs`.
- **API tracée** : `tool_api` + `api_v1` déclarés ; **trou #20 CLOS le jour même** (ROUTE §11 —
  les 10 routes `/api/tools/*` passaient hors gating F7 → routées par `execute_tool`, mesuré
  403/200).
- **Beat nocturne `nightly-consistency` NON gaté** (02:30, queue `default`, CPU pur — la suite
  GPU reste gatée `NIGHTLY_TESTS_ENABLED`) — ⚠ effectif au **restart beat/workers PENDING**,
  qui embarque aussi : chaîne modèles 12/08, anonymizer (normalize_types + pipeline unique),
  **whisper_utils → délégué au backend Whisper du transcriber** (fin du double chemin de
  chargement ; describer inchangé, smoke CPU/tiny vert).
- Redondances 8 → 0 (résorption `_params`→`declared_param_schemas` + `normalize_types`
  anonymizer + pragmas) ; corpus manifestes : les 3 « périmés » venv_win = faux positifs CODÉS
  en skip (le contrôle fait foi depuis WSL2).
