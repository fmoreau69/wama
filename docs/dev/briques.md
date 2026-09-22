<!-- WAMA:GENERE(dev-briques) — généré par « python manage.py doc_facts » depuis le plan de wama/common/docs_catalog.py ; ne pas éditer -->
# Briques communes — API

> Doc développeur **générée** : chaque section vient de la doc de construction (source citée en pied) ou des registres eux-mêmes. Pour la corriger, corriger la SOURCE — ce fichier est réécrit par `python manage.py doc_facts`.

**153 mécanismes** en 9 domaines. Ce qu'une brique FAIT est sa ligne de registre (`wama/common/mecanismes.py`) ; comment l'APPELER est ce que son module expose, lu dans le code par AST. Qui l'utilise, et ce qui manque : la [carte des mécanismes](../construction/architecture/WAMA_MECANISMES.md).

## Ressources & exécution

### Annonce de téléchargement des poids

Un modèle jamais utilisé télécharge ses poids À LA PREMIÈRE EXÉCUTION (37 appels `from_pretrained`/`snapshot_download` dans les backends) — et RIEN ne le disait : ni le squelette, ni les backends, ni la card. Mesuré le 2026-09-08, 4 modèles catalogués sont dans ce cas (mochi-1-preview, qwen-image-edit, flux2-klein-4b, musicgen-melody) : les lancer donnait une tâche figée, sans un mot, le temps de récupérer des dizaines de Go. *Une attente qu'on n'explique pas se lit comme une panne.* La brique ANNONCE et rien d'autre — elle ne télécharge pas (c'est le backend, au chargement), ne bloque pas, ne décide pas ; best-effort intégral. Adressée par la CLÉ DE CATALOGUE, la même qui résout le backend : l'annonce et l'exécution parlent du même modèle. Le squelette la déclare par `model_key` (OPTIONNEL, comme `vram_needed`). ⚠ Elle ne parle QUE si `is_downloaded=False`, et n'annonce la taille que si `disk_gb` la connaît : un avertissement permanent n'avertit plus de rien (celui de l'imager vidéo, en dur et à chaque lancement avec un volume inventé, a été retiré ce jour-là)

- **Domicile** : `wama/common/utils/model_readiness.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Prévenir l'utilisateur qu'un premier lancement va TÉLÉCHARGER les poids.
- **API publique** (1) :
  - `warn_if_weights_missing(model_key: str, console=None) -> bool` — Prévient (console) si les poids de `model_key` sont ABSENTS. Rend True si prévenu.

### Cache par empreinte de fichier

Garde une valeur calculée depuis un fichier (lecture AST, rendu markdown, compte de lignes) tant que son empreinte — date de modification, taille — n'a pas changé : un fichier modifié est relu, jamais servi périmé. Extrait le 2026-09-14 : le catalogue des docs portait le geste en dur, et l'inventaire des backends relisait 6 237 fois des fichiers pour UNE extraction de manifeste (48 résolutions d'un même vivier). ⚠ Ne convient qu'à ce qui ne dépend QUE du fichier

- **Domicile** : `wama/common/file_cache.py`
- **Module** : Cache par EMPREINTE de fichier — une valeur calculée depuis un fichier, gardée tant que le fichier n'a pas changé.
- **API publique** (2) :
  - `file_stamp(path) -> Optional[tuple]` — `(mtime_ns, taille)` du fichier (ou du dossier), `None` s'il est illisible.
  - `class FileCache` — `get(chemin, calcul)` : `calcul(chemin)` n'est rappelé que si l'empreinte a changé.

### Client du service TTS

L'appel POST /tts UNIQUE vers le microservice TTS (payload contractuel, 503 « loading » → TTSServiceLoadingError, WAV temporaire ou bytes) ; les POLITIQUES (retry Celery, chunking, replis) restent aux appelants — extrait 2026-08-28 : 4 exemplaires vivaient dans le dépôt, un seul détectait le 503

- **Domicile** : `wama/common/tts/service_client.py` · **doc** : [docs/construction/ui/MODES_QUEUE_UX.md §2bis](../construction/ui/MODES_QUEUE_UX.md)
- **Module** : Client COMMUN du microservice TTS (`tts_service.py`, FastAPI, uvicorn :8001).
- **API publique** (3) :
  - `class TTSServiceLoadingError(Exception)` — Le service TTS répond 503 « loading » (démarrage/chargement d'un moteur) —
  - `service_url() -> str` — URL du service TTS : settings Django si disponibles, sinon env, sinon défaut.
  - `tts_via_service(text, model, *, language='fr', voice_preset='default', speaker_wav=None, multi_speaker=False, scene_description='', options=None, read_timeout=…` — Synthétise `text` via le microservice TTS et renvoie le chemin d'un WAV TEMPORAIRE

### Contrat de backend

Cycle de vie commun des porteurs de modèle — ALIMENTATION du gouverneur (enveloppe load/unload/process à toute profondeur d'héritage) et CAPACITÉS déclarées par le moteur (supports_*), lues par le catalogue

- **Domicile** : `wama/common/backends/base.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Contrat de backend de modèle COMMUN à WAMA — extrait de l'app de référence (Transcriber).
- **API publique** (4) :
  - `unload_live_backends(model_key: Optional[str]=None, exclude_sources=None) -> int` — Décharge les backends résidents de CE process ; rend le nombre d'instances déchargées.
  - `refresh_live_reservations() -> int` — Rafraîchit le TTL de la ligne de registre de chaque backend résident de CE process.
  - `start_reservation_heartbeat() -> bool` — Lance, UNE fois par process, le battement qui garde vivantes les lignes des résidents.
  - `class BaseModelBackend(ABC)` — Backend de modèle local (chargement/déchargement + traitement).

### ETA auto-apprenante

Estimation de durée par a-priori puis moyenne mobile, bucketisée par matériel

- **Domicile** : `wama/model_manager/services/eta_estimator.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §10](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Estimateur d'ETA WAMA — *seeding* auto-apprenant et hardware-aware. ================================================================================
- **API publique** (4) :
  - `hardware_fingerprint() -> str` — Identifiant court du matériel de calcul (GPU + VRAM) ; 'cpu' à défaut.
  - `make_key(source: str, model_id: str) -> str` — Construit le model_key du registre : '{source}:{model_id}'.
  - `estimate(model_key: str, size: float=1.0, unit: str='item', model_loaded: bool=False, fallback_seconds: Optional[float]=None) -> float` — Estimation (secondes) du temps TOTAL de traitement d'un item.
  - `record_run(model_key: str, size: float, unit: str='item', process_seconds: float=0.0, load_seconds: Optional[float]=None) -> None` — Enregistre une exécution RÉELLE pour affiner l'estimation (EMA, par hardware).

### Gardes de process

Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines

- **Domicile** : `wama/common/utils/process_control.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §0](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Contrôle de process COMMUN — brique transversale (cf. memory project_process_button_lifecycle).
- **API publique** (10) :
  - `begin_processing(model, pk, *, user=None, reset=None, status_field: str='status', task_field: str='task_id', running_value: str='RUNNING')` — Démarrage ANTI-RACE d'un item (pattern obligatoire AGENTS.md — généralise describer
  - `stop_instance(instance, *, status_field: str='status', task_field: str='task_id', to_status: str='FAILURE', error_field: str | None=None, error_message: str="I…` — Stoppe le traitement d'un item : révoque la tâche Celery (SIGTERM) et le remet dans un état
  - `is_task_dead(task_id: str) -> bool` — True si la tâche Celery est dans un état terminal (finie/échouée/révoquée). NE classe PAS PENDING
  - `reconcile_if_stuck(instance, *, status_field: str='status', task_field: str='task_id', running_value: str='RUNNING', to_status: str='FAILURE', error_field: str…` — Si l'item est RUNNING mais que sa tâche Celery est dans un état TERMINAL
  - `collect_worker_snapshot(timeout: float=2.0)` — Photo de la flotte Celery en UNE interrogation :
  - `task_owner(task_id: str) -> str | None` — Nom du worker qui exécute la tâche (ex. ``'gpu@fbro-20-026'``), ou None si inconnu.
  - `is_task_orphaned(task_id: str, snapshot) -> bool` — True SEULEMENT si l'on a une PREUVE POSITIVE que la tâche est morte : elle a démarré
  - `is_task_lost(task_id: str, snapshot) -> bool` — True SEULEMENT si la tâche n'est PLUS NULLE PART : état Celery `PENDING`, aucun message
  - `reconcile_orphaned_running(instances, *, snapshot=None, status_field: str='status', task_field: str='task_id', running_value: str='RUNNING', to_status: str='FA…` — Réconcilie une liste d'items RUNNING dont la tâche Celery est TERMINÉE (is_task_dead)
  - `refuse_crash_redelivery(task, instance, *, status_field: str='status', task_field: str='task_id', to_status: str='FAILURE', error_field: str | None=None, error…` — Garde ANTI-BOUCLE-DE-CRASH pour les tâches lourdes (GPU) — à appeler EN TÊTE

### Gouverneur de ressources

Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités

- **Domicile** : `wama/common/services/resource_governor.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §0](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Gouvernance des ressources WAMA (GPU / CPU / RAM) — POINT D'ENTRÉE UNIQUE.
- **API publique** (50) :
  - `configure_cuda_process() -> bool` — Plafonne l'allocateur CUDA de CE process à `ALLOCATOR_CAP_FRACTION` de la
  - `total_vram_gb() -> float` — VRAM physique de la carte, 0.0 si pas de GPU.
  - `reserve_vram(owner: str, gb: float, *, allocated: bool=False, expires_in_s: float | None=None) -> bool` — Déclare que `owner` détient `gb` de VRAM. Écrase la ligne existante du même
  - `release_reservation(owner: str) -> bool` — Libère la RÉSERVATION de `owner` dans le registre Redis. Sans effet s'il n'en avait pas.
  - `vram_reservation(owner: str, gb: float)` — Réserve `gb` pour la DURÉE d'un bloc, puis libère — y compris si le bloc lève.
  - `reservations(exclude: str | None=None) -> dict[str, float]` — Réservations VIVANTES (Go par owner). Les lignes plus vieilles que
  - `reserved_gb(exclude: str | None=None) -> float` — Total BRUT réservé, tous détenteurs et process confondus (sauf `exclude`).
  - `resident_models() -> dict[str, float]` — Modèles actuellement RÉSIDENTS en VRAM — `AIModel.model_key` → Go — tous process
  - `model_keys_of(owner: str) -> list[str]` — Clés catalogue du modèle porté par une clé d'owner — [] s'il n'en porte pas, ou si le
  - `model_key_of(owner: str) -> str | None` — Première clé de `model_keys_of` — pour un appelant qui n'en attend qu'une.
  - `ollama_host_owner(name: str) -> str` — Clé d'owner de la résidence du modèle Ollama `name`.
  - `unseen_reserved_gb(probe: str='driver', exclude: str | None=None) -> float` — VRAM réservée que la SONDE `probe` ne voit pas encore — la seule part à lui retrancher.
  - `mark_used(owner: str) -> bool` — Horodate le dernier USAGE de `owner` (appelé à chaque `process()` d'un backend).
  - `record_measured_vram(owner: str, gb: float) -> bool` — Consigne une empreinte MESURÉE par l'allocateur torch au chargement de `owner`.
  - `measured_vram() -> dict[str, tuple[float, float]]` — Mesures en attente de persistance : owner → (Go, horodatage). Lignes illisibles ignorées.
  - `forget_measured_vram(rendues: dict) -> int` — Oublie les mesures RENDUES au catalogue — `rendues` : owner → horodatage lu.
  - `idle_models(idle_threshold_s: int=300) -> list[dict]` — Modèles RÉSIDENTS inactifs depuis plus de `idle_threshold_s`, tous process confondus.
  - `effective_free_gb(exclude: str | None=None) -> float` — VRAM réellement disponible = ce que le pilote annonce libre, MOINS ce que des
  - `gpu_safe_mode() -> bool` — Vrai si le mode dépannage GPU est actif (settings/env `WAMA_GPU_SAFE_MODE`).
  - `pipeline_keep_alive() -> str | None` — `keep_alive` à passer aux appels Ollama de la pipeline de prompts : '0' en mode
  - `wait_for_free_vram(needed_gb: float, *, timeout_s: float=180.0, poll_s: float=5.0, exclude: str | None=None, console=None) -> tuple[bool, float]` — Attend que `effective_free_gb()` atteigne `needed_gb`, puis rend (True, mesure).
  - `tenant_id() -> str` — Identité d'un TENANT = un process (le worker gpu, le service TTS, gunicorn…). Les clés
  - `tenant_of_owner(owner: str) -> str | None` — Tenant (pid) d'une clé d'owner du contrat, None pour une ligne sans process (Ollama hôte).
  - `fits_alone(needed_gb: float) -> bool | None` — `needed_gb` tiendrait-il sur la carte VIDE ? None sans GPU (on ne conclut pas d'une
  - `task_started(app_id: str, item_id, needed_gb: float=0.0, *, max_s: float | None=None) -> str` — Déclare une tâche GPU EN COURS ; rend son jeton. Posé par le squelette commun autour de
  - `task_finished(token: str) -> None`
  - `running_tasks() -> list[dict]` — Tâches GPU en cours, tous process confondus — lignes expirées purgées.
  - `mark_busy(tenant: str | None=None) -> bool` — Un tenant se déclare OCCUPÉ (le service TTS quand son verrou de synthèse est pris).
  - `clear_busy(tenant: str | None=None) -> None`
  - `busy_tenants(window_s: float=BUSY_WINDOW_S) -> set[str]` — Tenants occupés : déclarés depuis moins de `window_s`, ou dont un résident a SERVI depuis
  - `gpu_is_busy(window_s: float=BUSY_WINDOW_S, *, exclude_tenant: str | None=None) -> bool` — Une tâche tourne, ou un tenant sert — hors `exclude_tenant` (le requérant lui-même).
  - `grant_release(app_id: str, item_id, user_id=None) -> bool` — L'utilisateur ACCEPTE que toute la carte soit libérée pour CET item (bouton de la card en
  - `revoke_grant(app_id: str, item_id) -> None`
  - `release_granted(app_id: str, item_id) -> dict | None` — L'accord vivant pour cet item (`{'ts', 'user'}`), ou None. C'est le squelette — qui connaît
  - `request_release(needed_gb: float, requester: str, reason: str='') -> str | None` — Écrit une DEMANDE : « libérez ce que vous tenez, il me faut `needed_gb` ». Rend son id.
  - `pending_release_requests() -> dict[str, dict]` — Demandes vivantes (id → ligne) ; les périmées sont purgées avec leurs acquittements.
  - `acknowledge_release(request_id: str, tenant: str, *, freed: int=0, busy: bool=False) -> bool` — Un tenant dit ce qu'il a fait pour cette demande : `freed` instances déchargées, ou
  - `release_acks(request_id: str) -> dict`
  - `close_release_request(request_id: str) -> None` — Le requérant a ce qu'il voulait (ou renonce) : la demande disparaît, et les tenants qui
  - `obtain_vram(needed_gb: float, requester: str, *, reason: str='', timeout_s: float=120.0, poll_s: float=2.0, console=None) -> tuple[bool, float]` — Demande la libération, puis ATTEND que la SONDE rende `needed_gb` (bornée : le pilote
  - `release_in_progress() -> bool` — Une libération est en cours (au moins une demande vivante). L'assistant le lit pour rester
  - `holders_summary(limit: int=4) -> str` — Une phrase pour l'utilisateur : QUI tient QUOI — modèles résidents (Go) et tâches en cours.
  - `task_time_limit_s(app_id: str, user=None) -> float` — Plafond de durée d'UN traitement, en secondes : le réglage de l'utilisateur s'il en a posé
  - `class Tenant` — Ce qu'un process qui tient de la VRAM DÉCLARE au gouverneur : son nom, comment savoir
  - `serve_release_requests(tenant: Tenant) -> int` — UN passage : sert les demandes que ce tenant n'a pas encore acquittées, restaure après
  - `start_release_listener(tenant: Tenant, poll_s: float=RELEASE_POLL_S) -> bool` — Lance, une fois par process, le thread démon qui sert les demandes de libération pour
  - `contract_tenant(name: str, *, restore=None, is_busy=None) -> Tenant` — Le tenant par défaut d'un process qui héberge des modèles : décharge par
  - `tier_for(app_label: str) -> str` — Palier déclaré d'une app (nom lisible).
  - `celery_priority_for(app_label: str) -> int` — Valeur `priority` à passer à Celery pour cette app, dans la convention du
  - `task_routes() -> dict` — Complète les routes Celery avec la priorité de chaque app.

### Import « Envoyer vers » (registre + dérivation jumelles)

Le registre `IMPORTERS` EST le dispatch ET la source du résolveur SERVEUR « Envoyer vers » (`common/services/send_to.py` — cards ET arbre de fichiers depuis le 2026-09-14, qui calculait avant ses destinations chez le client ; une seule liste — plus d'app offerte-puis-refusée) ; une JUMELLE de bac à sable n'y écrit jamais sa ligne : son importeur est DÉRIVÉ de sa source (`importer_for`, via `generated_from` + paramètre `app_label` — re-ciblé sur SES tables, jamais celles de la source), et la CONSOLIDATION en lots de l'import groupé suit la même voie (2026-08-30/31, constats Fabien : jumelle absente du menu, puis cards unitaires). ⏳ avatarizer/composer sans importeur : leur fichier est une RÉFÉRENCE — attend le contrat d'import PAR RÔLE (CARD_DESIGN §11.8)

- **Domicile** : `wama/filemanager/views.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §S2bis](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : FileManager views - API for file browsing and management.
- **API publique** (42) :
  - `get_user(request)` — Get current user or anonymous user.
  - `get_user_media_root(user)` — Get the media root path for a specific user.
  - `build_file_tree(user)` — Build a file tree structure for jstree with two collapsible sections:
  - `build_folder_node(config, media_root, user_id)` — Build a folder node with its children.
  - `scan_folder_files(folder_path, relative_path, user_id)` — Scan a folder for files and subfolders, returning jstree nodes recursively.
  - `resolve_mount_path(rel_path, user)` — Resolve a virtual 'mounts/<id>[/subpath]' to an absolute Path.
  - `scan_mount_folder(abs_folder, virtual_prefix)` — Scan a mounted folder and return jstree nodes with virtual paths.
  - `api_children(request)` — Lazy-load children of a specific folder node (called by jstree when expanding).
  - `api_tree(request)` — Get file tree for jstree.
  - `api_tree_mtime(request)` — Lightweight change-detection endpoint for polling.
  - `api_search(request)` — Search files by name.
  - `api_upload(request)` — Upload file(s) to user's temp folder, preserving folder structure if provided.
  - `sanitize_relative_path(path)` — Sanitize a relative path to prevent directory traversal attacks.
  - `api_delete(request)` — Delete a file.
  - `api_delete_all(request)` — Delete all files in a folder and its subfolders.
  - `api_rename(request)` — Rename a file.
  - `api_move(request)` — Move a file or folder to a different location (only within temp folder).
  - `api_mkdir(request)` — Create a new subfolder in the user's temp directory.
  - `api_download(request, path)` — Download a file.
  - `api_info(request)` — Get file information.
  - `api_preview(request)` — Get file preview URL or thumbnail.
  - `is_path_allowed(path, user)` — Check if a path is allowed for the given user.
  - `api_import_to_app(request)` — Import one or more files from FileManager to an app's input folder.
  - `import_to_describer(source_path, user, app_label='describer')` — Import a file to Describer app.
  - `import_to_enhancer(source_path, user, app_label='enhancer')` — Import a file to Enhancer app (image, video, or audio).
  - `import_to_imager(source_path, user, app_label='imager')` — Import a file to Imager app.
  - `import_to_anonymizer(source_path, user, app_label='anonymizer')` — Import a file to Anonymizer app. `app_label` re-cible une jumelle (importer_for).
  - `import_to_synthesizer(source_path, user, app_label='synthesizer')` — Import a text file to Synthesizer app. `app_label` re-cible une jumelle (importer_for).
  - `import_to_reader(source_path, user, app_label='reader')` — Import a document/image file to Reader (OCR) app. `app_label` re-cible une jumelle.
  - `import_to_converter(source_path, user, app_label='converter')` — Import a file to the Converter queue.
  - `import_to_transcriber(source_path, user, app_label='transcriber')` — Import a file to Transcriber app. `app_label` re-cible une jumelle (importer_for).
  - `import_to_face_analyzer(source_path, user, app_label='face_analyzer')` — Import a video file to Face Analyzer app. `app_label` re-cible une jumelle.
  - `import_to_cam_analyzer(source_path, user, app_label='cam_analyzer')` — Import a video file to Cam Analyzer app (copies to input folder).
  - `importer_for(target_app)` — L'importeur d'une app — ou celui DÉRIVÉ de sa source pour une jumelle de bac à sable.
  - `receivable_apps(user=None)` — Les apps que le gestionnaire de fichiers sait REMPLIR, dans l'ordre alphabétique.
  - `api_find_folder(request)` — Find a server-side folder path by name + file fingerprint.
  - `api_validate_path(request)` — Validate and resolve a user-provided path (Windows/UNC/Linux).
  - `api_browse_fs(request)` — Return subdirectories of a server path for the in-browser folder picker.
  - `api_mounts(request)` — GET: list user's mounted folders. POST: add a new mount.
  - `api_remount_shares(request)` — Re-mount all WAMA-managed CIFS shares (called from start_wama_prod.sh via localhost).
  - `api_mount_delete(request, pk)` — Remove a mounted folder.
  - `api_mount_serve(request, pk, path)` — Serve a file from a mounted folder inline (for preview).

### Moniteur système

Mesure unifiée CPU/RAM/GPU/disque (WSL + hôte Windows) — barre de ressources, model manager

- **Domicile** : `wama/common/services/system_monitor.py`
- **Module** : System Monitor - Centralized system resource monitoring service.
- **API publique** (1) :
  - `class SystemMonitor` — Centralized system resource monitor.

### Mémoire GPU

Garantit la VRAM avant un chargement, la reprend sur les autres modèles, et réessaie après libération sur erreur CUDA

- **Domicile** : `wama/model_manager/services/memory_manager.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §0](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Memory Manager - GPU/RAM memory utilities for model management.
- **API publique** (11) :
  - `peaks_from_weights(weights: dict) -> dict` — Les DEUX pics d'un modèle, dérivés du poids par composant — `{}` si on ne sait pas.
  - `class MemoryStrategy(Enum)` — Memory loading strategies for AI models.
  - `preset_vram_gb(model_key: str) -> Optional[float]` — Empreinte VRAM d'exécution d'un modèle, depuis `MODEL_SIZE_PRESETS`.
  - `dtype_bytes(label: str)` — Octets par paramètre d'une précision — None si le nom est inconnu (on ne devine pas).
  - `peaks_for_precision(weights: dict, label: str) -> dict` — Les deux pics RECALCULÉS pour une précision de chargement — `{}` si on ne peut pas.
  - `backbone_row(row)` — La ligne de catalogue de la DORSALE d'un adaptateur, ou None si ce n'en est pas un.
  - `model_footprint_gb(row, *, offload: bool=True, count_backbone: bool=True) -> tuple` — `(Go, provenance)` que ce modèle EXIGE — ou `(None, 'unknown')` si personne ne sait.
  - `fits_full_gpu(model_key: str, total_vram_gb: float, headroom_gb: float=4.0) -> Optional[bool]` — Ce modèle peut-il tenir ENTIÈREMENT sur la carte (donc tourner en FULL_GPU, sans offload) ?
  - `register_vram_unloader(name: str, fn) -> None` — Déclare un callable qui libère la VRAM d'une app (idempotent par `name`).
  - `unregister_vram_unloader(name: str) -> None`
  - `class MemoryManager` — Manages GPU and system memory for AI models.

### Progression de tâche longue

Avancement d'une tâche Celery HORS file d'items publié dans le cache (F5-proof) + garde « déjà en cours » vérifiée auprès de Celery ; pendant navigateur = WamaApp.Poller

- **Domicile** : `wama/common/utils/task_progress.py` · **doc** : [wama/model_manager/PROSPECTION_PIPELINE.md](../../wama/model_manager/PROSPECTION_PIPELINE.md)
- **Module** : Avancement d'une tâche Celery LONGUE publié dans le cache Redis — brique COMMUNE.
- **API publique** (2) :
  - `publier_progression(cache_key: str, task_id, state: str, payload: dict, ttl: int=TTL_DEFAUT) -> None` — Publie l'avancement d'une tâche dans le cache. `state`/`task_id` en DERNIER :
  - `progression_en_cours(cache_key: str)` — La progression publiée SI la tâche est encore vivante, sinon None.

### Squelette de tâche

Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA

- **Domicile** : `wama/common/utils/task_skeleton.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Squelette COMMUN des tâches Celery d'item (brique F5 — marche A2 de la route §10.3).
- **API publique** (3) :
  - `class TaskContext` — Poignées offertes à la glu : progress + console. `progress_fn` permet à une app de
  - `class TaskTimeLimitExceeded(Exception)` — Le traitement a dépassé sa durée max (`resource_governor.task_time_limit_s`).
  - `run_item_task(task, *, app_id: str, model, item_id: int, process, vram_needed=None, model_key=None, error_field: str='error_message', ingest_derive=None, notif…` — Exécute la glu `process` dans le squelette conventionnel. Voir le contrat en tête de

### Tests nocturnes

Registre déclaratif de scénarios + runner sérialisé VRAM-aware (wired/ui/consistency/suite/model_loaded/output). Le stage `suite` (2026-09-19) fait entrer LA SUITE DJANGO dans la grille fonctionnelle : un scénario par app ayant des tests, DÉRIVÉ des apps installées ; verdict lu dans la SORTIE de `manage.py test` (jamais au code retour, qui sort en 0 sans rien lancer) et rouges NOMMÉS. DEUX comptes de test déclaratifs : le standard (rôles métier, SANS tier dev — c'est LUI que la matrice de droits mesure) et `get_test_dev_user` pour les surfaces dev-gated (jumelles de bac à sable), routé par `ui_smoke._test_session_key(app)` — sans lui les 11 scénarios d'une jumelle skippent (mesuré 2026-08-30)

- **Domicile** : `wama/common/services/nightly_tests.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §Tests fonctionnels nocturnes](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Charpente des tests fonctionnels nocturnes de WAMA. ============================================================================
- **API publique** (14) :
  - `class SkipScenario(Exception)` — Levée par un `run` quand une dépendance est absente (modèle/lib non installé) :
  - `class Scenario` — Un test fonctionnel déclaratif. `run(ctx) -> (ok: bool, detail: str)` ; peut lever.
  - `class ScenarioResult`
  - `register(**kwargs) -> Scenario` — Enregistre un scénario. Doublon d'id → remplace (réimport sûr).
  - `get_test_user()` — Utilisateur de test DÉDIÉ (jamais le compte réel). Créé si absent.
  - `get_test_dev_user()` — Compte de test DÉVELOPPEUR, dédié aux surfaces dev-gated (jumelles de bac à sable).
  - `sweep_test_witnesses() -> int` — Efface les FICHIERS témoins restés dans les dossiers média des comptes de TEST.
  - `free_vram() -> None` — Téardown VRAM best-effort entre scénarios (réutilise le cleaner du model_manager).
  - `run_one(sc: Scenario, ctx: dict) -> ScenarioResult` — Exécute UN scénario (timing + capture d'exception). NB : timeout dur = TODO prod
  - `run_all(scenarios: Optional[List[Scenario]]=None, write: bool=True) -> dict` — Joue les scénarios EN SÉRIE, téardown VRAM avant/après chacun. Retourne le rapport.
  - `build_report(results: List[ScenarioResult]) -> dict`
  - `write_report(report: dict) -> Path`
  - `functional_grid() -> dict` — La grille FONCTIONNELLE (2ᵉ grille de `WAMA_VERIFICATION §2`, décidée le 22/08 et
  - `register_examples() -> None`

### Vocabulaire TTS partagé

Le JEU DE CHOIX unique de la parole synthétique — moteurs, langues, presets de voix, cartes moteur↔langue — et sa résolution (voix pour une langue, langue d'une voix). Distinct du client de service : celui-ci TRANSPORTE, celui-là NOMME. Les deux apps TTS, `accounts` (langue de profil) et l'assistant y puisent les mêmes libellés

- **Domicile** : `wama/common/tts/constants.py`
- **Module** : WAMA Common TTS Constants ========================= Source unique des constantes TTS partagées entre : - wama.avatarizer (AvatarJob) - wama.synthesizer (VoiceSynthesis) - tts_service.py (service FastAPI)
- **API publique** : aucune fonction ni classe publique de premier niveau

## Modèles

### Auto-sélection (« auto » au select)

Valeur « auto » d'un select de modèle : résolution AU LANCEMENT sur le domaine que le schéma déclare pour ses options (options_query), prévision affichée sous le select (options_auto) + curseur de QUALITÉ continu 0-100 (intent_param, poids dans le score de select_model)

- **Domicile** : `wama/common/utils/auto_model.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Auto-sélection de modèle — brique COMMUNE (valeur « auto » d'un select de modèle).
- **API publique** (10) :
  - `read_quality_intent(value) -> int` — Valeur 0-100 SÛRE depuis un POST/JSON : bornée, défaut équilibré, ne lève jamais.
  - `posted_quality_intent(source)` — Curseur POSTÉ (POST ou dict JSON) → entier borné, ou **None** s'il n'est pas posté ou
  - `preset_key_for_intent(intent) -> str` — La POSITION NOMMÉE la plus proche d'une valeur de curseur (`QUALITY_PRESETS` du sélecteur :
  - `intent_param(**overrides) -> dict` — Surcouche STANDARD du curseur de qualité pour un schéma d'app (`derive_from_model`).
  - `is_auto(value) -> bool` — Cette valeur demande-t-elle le tirage automatique ? (vide compris).
  - `catalog_domain(app_id: str)` — DOMAINE déclaré au schéma de l'app pour son select de modèle, ou None.
  - `intent_field_for(app_id: str)` — Nom du champ « curseur » déclaré au schéma de l'app (`type='intent'`), ou None.
  - `quality_intent_of(item=None, app_id=None, user=None) -> int` — La valeur du curseur qui vaut pour CE lancement, en UN endroit (chantier C, 2026-09-20).
  - `resolve_model_choice(requested, *, app_id=None, spec=None, fallback=None, item=None, user=None, **overrides)` — Valeur finale du modèle pour un lancement : `requested` explicite, sinon tirage.
  - `predict_model_choice(spec)` — PRÉVISION : le modèle qui serait retenu MAINTENANT pour ce domaine, ou None.

### Banc de comparaison

Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation) ; `text-generation` mesure le DÉBIT d'un LLM Ollama (jetons/s, prefill, chargement) et nourrit la boucle d'ETA (`ModelRuntimeStat`, unité token) — des coûts, jamais une qualité

- **Domicile** : `wama/model_manager/services/bench.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.2](../construction/suivi/ROADMAP.md)
- **Module** : Banc de comparaison de modeles, indexe sur la TACHE et non sur l'app.
- **API publique** (3) :
  - `models_for_task(task: str, *, installed_only: bool=True)` — Modeles du catalogue qui declarent cette tache. Le catalogue est la seule source.
  - `available_tasks() -> list` — Taches pour lesquelles un protocole existe — les autres restent a ecrire.
  - `run_bench(task: str, sample: str, *, models: Optional[list]=None, **options) -> list` — Passe chaque modele de `tache` sur `echantillon` et rend des mesures comparables.

### Benchmark tiers confronté

Étage 2 qualité (a priori < benchmark < mesure) : AA + Elo Arena (texte, image, vidéo, VISION, document) + Open ASR (WER, sens 'bas') + MTEB (embeddings, jeu FRANÇAIS déclaré) appariés au catalogue, prospection incluse

- **Domicile** : `wama/model_manager/services/benchmark_sync.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §REPRISE 2026-08-18](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Signal qualité « BENCHMARK TIERS CONFRONTÉ » — 2e étage de l'échelle des signaux.
- **API publique** (9) :
  - `class SourceUnavailable(Exception)` — Réseau/clé/format absents — la source est SKIPPÉE, jamais un score partiel inventé.
  - `load_aa()` — {'categorie': [{'nom','slug','valeur','echelle','identite'}]} ; motifs par catégorie.
  - `load_arena()` — {'categorie': [{'nom','elo','votes','identite'}]} depuis le dataset HF officiel
  - `load_open_asr()` — {'categorie': [{'nom','slug','wer','identite','rtfx','licence','taille_b','jeux'}]}
  - `load_mteb()` — {'embedding': [{'nom','slug','score','identite','taches','revision'}]} depuis le dépôt
  - `benchmarks_comparable(pool) -> bool` — Vrai si les `benchmark_index` du lot peuvent être ORDONNÉS entre eux.
  - `orderable_value(m)` — La valeur d'un `benchmark_index` telle qu'on peut la TRIER (plus grand = meilleur), ou
  - `percentile_rank(value, population, key, direction: str='higher')` — Position de `valeur` dans la population de SON banc, en centiles (0-100), ou None.
  - `synchronize(dry_run: bool=False, include_proposed: bool=True)` — Apparie le catalogue (téléchargés + candidats de prospection `proposed:`) aux deux

### Cache HF scopé — dernier recours

Bascule TEMPORAIRE du cache HuggingFace, restaurée en sortie : le levier D de `hf_weights`, réservé à une lib qui n'offre ni `cache_dir=`, ni chemin local, ni variable propre. ⚠ Restaure l'environnement, JAMAIS les fichiers. Aucun emploi aujourd'hui (`RECOURS_ASSUMES` vide, tenu par `tests_hf_cache_routing`)

- **Domicile** : `wama/common/utils/hf_cache.py` · **doc** : [docs/construction/suivi/ROADMAP.md §5b](../construction/suivi/ROADMAP.md)
- **Module** : Bascule SCOPÉE du cache HuggingFace — LA brique anti-fuite (extraite le 2026-08-12).
- **API publique** (1) :
  - `hf_cache_scope(cache_dir)` — Pose env + constantes huggingface_hub sur `cache_dir` LE TEMPS du bloc, puis

### Couverture multi-modèles

Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation)

- **Domicile** : `wama/common/services/model_coverage.py`
- **Module** : Couverture multi-modèles : quelle COMBINAISON de modèles couvre un ensemble de classes.
- **API publique** (7) :
  - `normaliser_classe(nom: str) -> str` — 'License_Plate' → 'license plate' · 'FACE' → 'face'.
  - `formes_equivalentes(nom: str) -> set` — Toutes les écritures normalisées équivalentes à `nom` (lui-même si aucun alias connu).
  - `classes_couvertes(m, voulues) -> set` — Accès PUBLIC à l'appariement d'alias : sous-ensemble de `voulues` (vocabulaire de
  - `size_of_name(name: str) -> str` — Accès PUBLIC à la lecture de taille (chantier C, 2026-09-20) : un appelant qui affiche ou
  - `size_for_intent(intent) -> str` — Curseur 0-100 → taille préférée ('n' ≤ 20, 's' ≤ 40, 'm' ≤ 60, 'l' ≤ 80, sinon 'x').
  - `segmentation_for_intent(intent) -> bool` — Curseur 0-100 → préférer la segmentation (≥ `SEGMENTATION_THRESHOLD`).
  - `couvrir_classes(classes, *, source: str='', model_type: str='vision', budget_vram_gb: float | None=None, taches_admises=(), preferer_segmentation: bool=False,…` — Ensemble MINIMAL de modèles couvrant `classes`, par recouvrement glouton.

### Découverte de modèles

Découverte unifiée des modèles (apps + sources externes), synchronisée vers le catalogue AIModel

- **Domicile** : `wama/model_manager/services/model_registry.py`
- **Module** : Model Registry - Unified model discovery across all WAMA apps and external sources.
- **API publique** (2) :
  - `class ModelInfo` — Unified model information structure.
  - `class ModelRegistry` — Central registry for all WAMA models.

### Indice de qualité a priori

Ordonne les modèles autrement que par la taille (params EFFECTIFS √(totaux×actifs), contexte, quantif.)

- **Domicile** : `wama/model_manager/services/model_quality.py`
- **Module** : Indice de qualité A PRIORI d'un modèle — pour choisir autrement que « le plus gros qui tient ».
- **API publique** (3) :
  - `params_in_billions(label: str) -> float | None` — '36.0B' → 36.0 · '8.0B' → 8.0 · '' → None. Tolère 'M' (millions).
  - `apriori_quality_index(*, params_b: float | None, context_length: int | None=None, quantization: str='', params_active_b: float | None=None) -> float | None` — Indice a priori, croissant avec la capacité. None si le signal principal manque.
  - `active_params_b(params_b: float | None, total_experts, active_experts) -> float | None` — Paramètres réellement activés par jeton, en milliards — axe de COÛT, pas de qualité.

### Installation de modèles

Pipeline accept→download→register : télécharge au bon endroit puis enregistre au catalogue

- **Domicile** : `wama/model_manager/services/model_installer.py`
- **Module** : Pipeline accept→download→register — installation de modèles dans WAMA.
- **API publique** (27) :
  - `pull_ollama_model(name: str, timeout: int=1800, progress=None)` — Télécharge un modèle Ollama via le démon LOCAL (`POST /api/pull`, stream).
  - `delete_ollama_model(name: str, timeout: int=60) -> dict` — Désinstalle un modèle Ollama (`DELETE /api/delete`) — libère sa place sur le volume.
  - `pull_hf_model(hf_id: str, category: str, family: str | None=None, dry_run: bool=False, allow_patterns=None, progress=None)` — Télécharge un modèle HuggingFace DANS LE BON DOSSIER (catégorie WAMA) via l'API officielle
  - `duplicate_weight_files(files) -> list` — Fichiers de poids à NE PAS tirer parce que leur jumeau `.safetensors` existe — même
  - `format_duplicates(hf_id: str) -> list` — Les jumeaux de format d'un dépôt HF — un appel HTTP, la règle vient de
  - `weight_for_spec(spec: dict)` — Poids en Go de ce qu'un descripteur d'installation va TIRER, ou None si indéterminable.
  - `components_of_files(files, *, composition=None, allow_patterns=None) -> dict` — Poids PAR COMPOSANT d'un inventaire de fichiers — dérivation PURE, aucun réseau.
  - `components_for_spec(spec: dict, *, files=None) -> dict` — Poids par composant de ce qu'un descripteur désigne — `{}` si indéterminable.
  - `yolo_task_of(name: str) -> str` — Tâche (`ModelTask`) d'un poids YOLO, déduite du suffixe de son nom — `detect` par défaut.
  - `pull_yolo_weights(name: str, timeout: int=600, dry_run: bool=False)` — Télécharge des poids YOLO OFFICIELS (assets GitHub Ultralytics, URL stable
  - `register_after_install()` — Re-synchronise le catalogue `AIModel` pour que le modèle fraîchement installé apparaisse.
  - `replaced_model(cand)` — (nom Ollama de l'ancien modèle, espace qu'il rendra en Go) pour un candidat successeur,
  - `disk_space_guard(ref: str, *, reclaim_gb: float=0.0, force: bool=False, needed_gb: float | None=None)` — Refuse une installation qui saturerait le volume. Retourne None si l'installation peut
  - `request_install(model_key: str, *, force: bool=False, variant_ref: str='', variant_file: str='') -> dict` — DEMANDE d'installation par CLÉ — corps unique du geste « Installer » : choix de variante,
  - `install_candidate(cand, progress=None) -> dict` — Séquence d'installation d'un CANDIDAT de prospection Ollama — corps unique, appelé par
  - `uninstall_model(model_key: str) -> dict` — DÉSINSTALLE un modèle du catalogue : retrait des POIDS uniquement, jamais du backend
  - `spec_for_catalog_row(model) -> dict | None` — Spec d'installation DÉRIVÉ d'une ligne de catalogue non téléchargée — le geste « Installer »
  - `patterns_from_composition(composition) -> list | None` — `allow_patterns` DÉRIVÉS d'une `composition` déclarée (manifeste `model`,
  - `install_from_spec(spec: dict) -> dict` — Point d'entrée UNIQUE d'installation — DESCRIPTEUR déclaratif au lieu de mécanismes
  - `record_provenance(spec: dict, res: dict) -> dict` — Après un téléchargement réussi : sync du catalogue, puis provenance des lignes apparues.
  - `pip_spec_error(spec: str)` — Motif de refus d'un spécificateur pip, ou None s'il passe les verrous syntaxiques.
  - `pip_constraint_errors(constraints) -> list` — Motifs de refus des contraintes pip — mêmes verrous qu'un spécificateur.
  - `pip_install_packages(packages, timeout: int=1800, no_deps: bool=False, constraints=None) -> dict` — Installe des paquets pip dans le venv courant — pour rendre un backend disponible quand un
  - `ensure_backend_deps(backend_cls, timeout: int=1800) -> dict` — Installe les paquets manquants d'un backend (classe `BaseModelBackend`) si nécessaire.
  - `simuler_installation(spec: str, timeout: int=300, constraints=None) -> dict` — Ce qu'une installation ENTRAÎNERAIT — `pip install --dry-run`, LECTURE SEULE.
  - `install_library(key: str, apply: bool=False) -> dict` — Installe UNE librairie depuis son registre (`common.models.Library`) — la JONCTION
  - `install_requirements(app_key: str, apply: bool=False) -> dict` — Le MARCHEUR d'app (« application = modèles + librairies », reste ③ de la route

### Prospection de modèles

Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run)

- **Domicile** : `wama/model_manager/services/prospector.py` · **doc** : [wama/model_manager/PROSPECTION_PIPELINE.md](../../wama/model_manager/PROSPECTION_PIPELINE.md)
- **Module** : Prospection de modèles — version DÉTERMINISTE (sans LLM, sans scraping).
- **API publique** (16) :
  - `hf_task_to_wama(pipeline_tag: str, tags=())` — (tâche NÔTRE, model_type) d'un dépôt HF, d'après son tag de pipeline ET les tags de sa
  - `card_facts(pipeline_tag: str, tags=(), card_data=None, library_name: str='') -> dict` — Ce que la CARTE HuggingFace dit d'un modèle, traduit en faits WAMA — MÉCANIQUEMENT, jamais
  - `prospect_hf(task: str, limit: int=15, library: str | None=None, min_downloads: int=0, search: str | None=None, sort: str='downloads')` — Top modèles HF d'une `task` (par téléchargements), avec flag « déjà dans WAMA ».
  - `local_revision(snapshot_root)` — Le dossier dont les chemins de `local_inventory` sont RELATIFS : la révision la plus
  - `local_inventory(snapshot_root)` — `[(chemin relatif, taille)]` d'un modèle INSTALLÉ — le jumeau LOCAL de `_siblings`
  - `safetensors_facts(path)` — `{'params': nombre de paramètres, 'dtypes': [...]}` lus dans l'EN-TÊTE seul d'un
  - `precision_of_files(revision, files_by_role) -> dict` — `{rôle: {'params', 'dtypes'}}` — la PRÉCISION de chaque composant, lue dans les en-têtes
  - `quantized_variants(hf_id: str, limit: int=5) -> list[dict]` — Dépôts HF dérivés QUANTISÉS d'un modèle (GGUF/FP8/4-8bit/AWQ…), triés par téléchargements.
  - `analyze_license(hf_id: str, license_id: str='', base_model=None, _profondeur: int=0)` — Verdict de COMPATIBILITÉ de licence d'un candidat, pour AFFICHAGE sur la card —
  - `install_options(cand) -> dict` — Options d'installation EXPLICITES d'un candidat HF : poids pleins + variantes quantisées,
  - `spec_for_choice(cand, variant_ref: str, variant_file: str | None) -> dict | None` — Le SPEC d'installation qui respecte le choix validé par l'utilisateur, ou None si le choix
  - `seed_hf_candidates(limit: int=12, min_downloads: int=1000, tasks=None) -> dict` — Candidats `is_proposed` depuis la bibliothèque HuggingFace — pendant HF de la découverte
  - `seed_candidate_from_manifest(manifest: dict) -> dict` — Écrit/rafraîchit un CANDIDAT de prospection depuis un manifeste `model` — le chemin du
  - `seed_yolo_candidate(name: str) -> dict` — Candidat de prospection pour des poids YOLO OFFICIELS demandés PAR LEUR NOM.
  - `seed_hf_search(query: str, limit: int=10, max_retenus: int=5) -> dict` — Prospection CIBLÉE : cherche `query` dans les noms de dépôts HF (toutes tâches de
  - `apply_recommendations(candidates, source: str, task: str)` — Crée/maj des entrées `recommended` dans le catalogue pour les candidats NOUVEAUX (pas déjà

### Provenance de modèle

Identité chez l'éditeur (licence, auteur, plateforme), posée VIA le manifeste

- **Domicile** : `wama/model_manager/services/provenance.py`
- **Module** : Identité d'un modèle chez son éditeur — et pose de cette identité PAR LE MANIFESTE.
- **API publique** (6) :
  - `huggingface_identity(hf_id: str) -> Optional[dict]` — `{license, author, platform_ref, hf_id, gated}` lu sur la carte du dépôt, ou None si injoignable.
  - `ollama_identity(name: str) -> Optional[dict]` — Identité d'un modèle Ollama. La plateforme n'expose ni licence ni auteur exploitables par
  - `cloud_identity(item: dict) -> Optional[dict]` — Identité d'un modèle DISTANT : le dépôt HuggingFace que le fournisseur sert, quand il le
  - `identity_for_spec(spec: dict) -> Optional[dict]` — Identité déductible du descripteur d'installation (`install_from_spec`).
  - `set_identity(model_key: str, identity: dict, *, capabilities: dict=None, engine: str=None, apply: bool=True, export: bool=True) -> dict` — Pose l'identité — et les capacités DÉCLARÉES — sur un modèle DU CATALOGUE, en passant
  - `record_after_install(spec: dict, appeared_keys) -> dict` — Après installation + sync : pose l'identité sur les modèles qui viennent d'APPARAÎTRE.

### Sonde vision

Décrit une image via un modèle multimodal Ollama local (bench, smoke UI, fichiers de référence)

- **Domicile** : `wama/model_manager/services/vision_probe.py`
- **Module** : Sonde vision via Ollama — décrire une image avec un modèle multimodal local (gemma4:12b, e4b…). Sert au bench (d) : comparer des modèles candidats sur de vraies images WAMA, en français.
- **API publique** (1) :
  - `describe_image_ollama(image_path: str, model: str='', prompt: str | None=None, timeout: int=180, keep_alive: str | None=None)` — Décrit une image via un modèle vision Ollama LOCAL. Retourne {'ok', 'description'|'error'}.

### Sélection de modèle

Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité

- **Domicile** : `wama/model_manager/services/model_selector.py` · **doc** : [docs/construction/ui/INPUT_MODEL_MATCHING.md](../construction/ui/INPUT_MODEL_MATCHING.md)
- **Module** : Sélection intelligente de modèles — centralisée pour toutes les apps WAMA.
- **API publique** (9) :
  - `get_free_vram_gb() -> Optional[float]` — VRAM libre (Go) du GPU le plus libre, MOINS ce que d'autres process ont réservé.
  - `abilities_of(model) -> list` — Libellés des aptitudes déclarées par `model`, lus dans `ModelAbility` (+ sa spécialité).
  - `select_model(source: Optional[str]=None, *, model_type: Optional[str]=None, requires: Optional[List[str]]=None, classes: Optional[List[str]]=None, prefer_loade…` — Choisit le meilleur `AIModel` pour `source` (valeur ModelSource), ou None.
  - `list_models(source: str, downloaded_only: bool=True) -> List[dict]` — Liste des modèles d'une source (dicts to_dict — description courte/longue + vram).
  - `matches_inputs(model, available_inputs=None, task: Optional[str]=None, consumes=None) -> bool` — Ce modèle est-il utilisable avec les entrées dont on dispose ? (appariement entrée↔modèle)
  - `full_gpu_budget_gb(headroom_gb: float=4.0) -> Optional[float]` — Budget VRAM au-delà duquel un modèle imposerait de l'offload CPU.
  - `select_model_id(source: Optional[str]=None, requires=None, requested: Optional[str]=None, fallback: Optional[str]=None, avoid_offload: bool=True, modality: Opt…` — Tirage d'un modèle pour une app, rendu comme un `model_id` nu (sans le préfixe "source:").
  - `get_registry_models(source: Optional[str]=None, allowed_ids=None, downloaded_only: bool=False, requires=None, modality: Optional[str]=None, task: Optional[str]…` — (choices, info) pour le <select> d'une app, PILOTÉ par le registre AIModel (verrou n°1).
  - `describe_model(model_key: str, tier: str='short') -> str` — Description d'un modèle. tier='short' → une ligne (fallback long) ; 'long' → paragraphe.

## Qualité & auto-amélioration

### Ajout au RAG (geste explicite)

Bouton dans l'INSPECTEUR + page « Mon RAG » ; texte pris au schéma canonique, aucune ligne par app. Pas de balayage : l'entrée au RAG est un geste, par décision

- **Domicile** : `wama/common/static/common/js/wama-inspector.js` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7ter](../construction/ia/WAMA_MEMORY.md)

### Barre d'outils générale (registre + profils)

UN registre d'outils (l'UNION de toutes les barres) et des PROFILS par nature de surface : `file` (12 files d'app) et `registre` (15 catalogues). Une surface tire des outils, elle ne les énumère pas — ajouter un outil à toutes les files est UNE clé, plus jamais douze gabarits (demande Fabien 2026-09-08 : « de façon globale, pas par app »). Les deux barres historiques SURVIVENT en façades vers `_toolbar.html`, ce qui laisse les 27 pages appelantes inchangées ; les deux ENVELOPPES sont conservées telles quelles (les fondre aurait changé les deux apparences). Chaque outil est un partial sous `common/toolbar/`

- **Domicile** : `wama/common/toolbar.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)
- **Module** : Barre d'outils COMMUNE — UN registre d'outils, des PROFILS par nature de surface.
- **API publique** (3) :
  - `class Outil` — Un outil de barre. `partial` est la SEULE chose qui rend — le registre ne rend rien.
  - `outils_du_profil(profil: str) -> list` — Les `Outil` du profil, dans l'ordre déclaré. Profil inconnu → `KeyError` explicite.
  - `enveloppe_du_profil(profil: str) -> str`

### Barre de filtrage

Recherche + facettes EN DIRECT ; options dérivées du DOM (client) ou déclarées (server). Depuis le 2026-09-08 la recherche est un OUTIL du registre de barre (`toolbar_registry`), donc la même dans les registres et dans les 12 files. Masquage PAR CLASSE (`.wama-f-hors-filtre`) et non par `style.display` : une cible à `display` inline (l'entrée unitaire de file est en `display:contents`) ne survivait pas à la restauration. `data-cible-dans` BORNE la recherche — sans quoi deux files sur une même page se filtreraient l'une l'autre

- **Domicile** : `wama/common/static/common/js/wama-filter-bar.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Captation générique des gestes

Middleware : telecharge/supprime/relance lus de resolver_match — zéro ligne par app

- **Domicile** : `wama/common/middleware.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7bis](../construction/ia/WAMA_MEMORY.md)
- **Module** : Captation GÉNÉRIQUE des gestes utilisateur vers `RunOutcome`. Doc : `WAMA_MEMORY.md §7bis`.
- **API publique** (1) :
  - `class RunOutcomeCaptureMiddleware` — Enregistre telecharge / supprime / relance depuis les routes de file, sans code par app.

### Catalogue & lecteur de docs

Déclare les docs de référence (famille, AUDIENCE, journal) et les rend lisibles depuis WAMA en lecture seule (page `docs`, admins) ; `check_docs` en dérive sa liste, et un test refuse que la table d'AGENTS.md cite un doc non déclaré. Sert aussi la doc DÉVELOPPEUR : ses faits (`dev_docs.py` : parcours, registres, API des briques lue par AST), écrits en `.md` par les plans

- **Domicile** : `wama/common/docs_catalog.py` · **doc** : [AGENTS.md §Trois docs, trois publics](../../AGENTS.md)
- **Module** : Catalogue des DOCS — les documents de WAMA, déclarés UNE fois, lisibles depuis WAMA.
- **API publique** (12) :
  - `class Excerpt` — Une section de la doc de construction, marquée pour le public de la doc dérivée.
  - `class Facts` — Un bloc calculé depuis les registres : `module:fonction` qui rend du markdown.
  - `class Doc`
  - `get(key: str) -> Optional[Doc]`
  - `visible_to(doc: Doc, admin: bool) -> bool` — Un compte connecté lit la doc utilisateur ; un administrateur lit tout.
  - `checked_paths() -> List[str]` — Les cibles de `check_docs` : les docs ÉCRITS À LA MAIN, dans l'ordre de déclaration.
  - `journal_paths() -> set`
  - `file_of(doc: Doc) -> Path`
  - `entry(doc: Doc) -> dict` — La fiche d'un doc pour sa card : déclaration + ce que le disque dit de lui.
  - `entries() -> List[dict]`
  - `render_doc(doc: Doc, admin: bool=True) -> dict` — `{'html', 'toc'}` du doc, tel que le lit un administrateur ou non — les liens vers une doc
  - `render_markdown(text: str, source_path: str='', visible=None) -> dict` — Markdown → `{'html', 'toc'}`. `source_path` sert à résoudre les liens relatifs ;

### Chiffrement RÉVERSIBLE des secrets d'utilisateur

Les clés d'API de fournisseurs cloud sont chiffrées en base, pas hachées : WAMA doit les RELIRE pour appeler le fournisseur à la place de l'utilisateur. Clé DÉRIVÉE de `SECRET_KEY` par HKDF avec une étiquette d'usage (décision Fabien : pas de clé de plus dans `.env`) — on ne chiffre pas avec la valeur qui signe les sessions. ⚠ La rotation de `SECRET_KEY` est le piège : le déchiffrement essaie la courante puis les `SECRET_KEY_FALLBACKS`, dont `rotate_secrets` ne garde que TROIS

- **Domicile** : `wama/common/utils/secret_crypto.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Chiffrement RÉVERSIBLE des secrets d'utilisateur stockés en base — clés d'API de fournisseurs cloud (ROADMAP §8d Phase 3, étape 4 ; décisions de Fabien du 2026-09-15).
- **API publique** (9) :
  - `class SecretStorageUnavailable(RuntimeError)` — Chiffrement refusé : aucune clé sûre (placeholder de développement). Message pour l'humain.
  - `class SecretUnreadable(ValueError)` — Déchiffrement impossible : ni la clé courante ni les fallbacks ne le lisent.
  - `storage_available() -> bool` — Peut-on enregistrer un secret maintenant ? (clé courante sûre)
  - `encrypt(plaintext: str) -> str` — Chiffre avec la clé COURANTE. Lève `SecretStorageUnavailable` sur une clé non sûre.
  - `decrypt(token: str) -> str` — Déchiffre par la clé courante, puis par les `SECRET_KEY_FALLBACKS`.
  - `reencrypt(token: str, new_secret: str, old_secrets) -> str` — Rechiffre `token` avec la clé dérivée de `new_secret`, en le lisant par `new_secret` ou
  - `class EncryptedTextField(models.TextField)` — Champ texte CHIFFRÉ au repos : l'ORM lit et écrit le CLAIR, la base ne voit que le jeton.
  - `encrypted_columns() -> list` — (modèle, champ) de chaque `EncryptedTextField` des modèles installés. La rotation les trouve
  - `reencrypt_stored_secrets(new_secret: str, old_secrets, using: str='default') -> dict` — Rechiffre en base chaque secret stocké vers la clé dérivée de `new_secret`.

### Contrôle qualité de sortie

Note une sortie par un validateur LLM INDÉPENDANT ; signal relatif, escalade humaine

- **Domicile** : `wama/common/utils/qc.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.5](../construction/suivi/ROADMAP.md)
- **Module** : Contrôle qualité (QC) générique — primitive réutilisable, indépendante des apps.
- **API publique** (1) :
  - `assess_output_quality(task: str, input_summary: str, output: str, validator_provider: str='ollama', validator_model: str | None=None, review_threshold: float=0…` — Note la qualité d'une `output` (texte) pour une `task`, via un validateur LLM indépendant.

### Divergence inter-systèmes

Désaccord entre deux sorties du même travail — signal objectif, sans avis de modèle

- **Domicile** : `wama/common/services/divergence.py` · **doc** : [wama/transcriber/TRANSCRIBER_CORRECTION.md §8.3](../../wama/transcriber/TRANSCRIBER_CORRECTION.md)
- **Module** : Divergence inter-systèmes — un signal de qualité qui est un FAIT, pas un avis.
- **API publique** (3) :
  - `divergence_texte(a: str, b: str) -> float` — Désaccord entre deux transcriptions d'un même passage : 0.0 = identiques, 1.0 = tout diffère.
  - `divergence_segments(reference, comparaison) -> dict` — Compare deux découpages en segments du même média et rend le désaccord PAR SEGMENT.
  - `zones_a_verifier(resultat: dict, niveau_minimal: str='attention') -> list` — Les segments à montrer à l'humain en priorité — c'est l'usage final du signal.

### Docs dérivées par plan

Un PLAN déclaré dans le catalogue des docs (extraits de sections marquées + faits de registre) produit un `.md` versionné, écrit par `doc_facts` ; `--check` refuse un fichier qui n'est plus ce que son plan produit — la confrontation doc → doc, gratuite parce que la dérivation est mécanique. Pour l'UTILISATEUR, une PORTE registre retient les intentions et ce que le registre ne confirme pas

- **Domicile** : `wama/common/doc_plans.py` · **doc** : [docs/construction/suivi/ROADMAP.md §25](../construction/suivi/ROADMAP.md)
- **Module** : Les docs DÉRIVÉES, construites par PLAN (ROADMAP.md §25.1 ③).
- **API publique** (5) :
  - `class PlanError(ValueError)` — Un plan qui ne se construit pas — cassé, jamais approximé.
  - `gate_unverifiable(chemin: str) -> Optional[str]` — Pourquoi une porte ne peut pas être VÉRIFIÉE (registre inconnu, ou sans fiches) ; `None`
  - `gate_closed(chemin: str) -> Optional[str]` — Pourquoi le registre ne confirme PAS ce que la porte désigne ; `None` si elle est ouverte.
  - `excerpt_markdown(texte: str, section: str, audience: str, source_path: str, target_path: str, title: str='', gate: Optional[Callable[[str], Optional[str]]]=Non…` — Les lignes markdown d'UN extrait : la section (et ses sous-sections destinées au même
  - `build(doc) -> str` — Le `.md` complet d'une doc dérivée, tel que son plan le produit AUJOURD'HUI.

### Envoyer vers (chaînage progressif, hors studio)

La SORTIE d'une card devient l'ENTRÉE d'une autre app, sans passer par le studio. RÉSOLVEUR en lecture seule : il rend les chemins de sortie (clé canonique `result_file`/`result_files` du schéma de détail), les apps ÉLIGIBLES et l'URL de l'endpoint. L'envoi lui-même passe par `filemanager:api_import` — celui qui sert déjà « Envoyer vers… » — donc aucun second dispatch et aucune garde de chemin recopiée. ⚠ Les destinations sont DÉRIVÉES de trois conditions (importeur, extension déclarée, accès) et jamais listées : c'est la leçon du Geste 14, où le menu offrait trois apps que le serveur refusait. Une app qui ne prendrait qu'une PARTIE des fichiers n'est pas offerte — un envoi partiel silencieux ferait croire le résultat entier transmis. Porte aussi l'INVERSE (2026-09-18) : `item_for_output_path` — de quel élément un chemin de `media/` est la SORTIE (candidats par requête, CONFIRMATION par l'adapter), route `api/element-pour-chemin/` — ce qui donne à l'arbre les gestes d'élément

- **Domicile** : `wama/common/services/send_to.py` · **doc** : [docs/construction/architecture/WAMA_VERIFICATION.md](../construction/architecture/WAMA_VERIFICATION.md)
- **Module** : ENVOYER VERS — la sortie d'une card devient l'entrée d'une autre app.
- **API publique** (4) :
  - `sorties_de(surface: str, instance) -> list` — Chemins RELATIFS à `media/` des sorties DÉCLARÉES de cet élément.
  - `item_for_output_path(user, chemin: str)` — L'élément dont `chemin` (relatif à `media/`) est une SORTIE déclarée — `(surface,
  - `destinations(user, chemins, partiel: bool=False) -> list` — Apps qui savent RECEVOIR ces fichiers. Trois conditions, toutes nécessaires.
  - `destinations_dossier(user) -> list` — Apps qui savent recevoir un DOSSIER entier : importeur + accès (`_apps_receveuses`).

### Faits en ligne (balises de registre)

Une balise `WAMA:FAIT(registre/clé/champ)` dans un .md va chercher sa valeur dans le registre (`Registry.entries`) ; `doc_facts` la régénère, `--check` la confronte, et une balise qui ne se résout pas est CASSÉE. Généralise les blocs `WAMA:FAITS` (une fonction par fait) à n'importe quel champ de registre

- **Domicile** : `wama/common/fact_tags.py` · **doc** : [docs/construction/suivi/ROADMAP.md §25](../construction/suivi/ROADMAP.md)
- **Module** : Faits EN LIGNE dans les `.md` — une balise qui va chercher sa valeur dans un registre.
- **API publique** (5) :
  - `class FactError(ValueError)` — Une balise qui ne se résout pas — cassée, pas approximée.
  - `entries(registre: str) -> Dict[str, dict]` — Les fiches d'un registre, par clé.
  - `render_value(valeur) -> str` — Une VALEUR en texte d'une ligne. Une structure (dict) est refusée : une balise cite une
  - `resolve(chemin: str) -> str` — La valeur ACTUELLE que désigne un chemin de balise.
  - `refresh_text(texte: str) -> Tuple[str, int, List[Tuple[str, str]]]` — Régénère toutes les balises d'un texte : `(texte neuf, nombre de balises, erreurs)`.

### Fuites de secrets

gitleaks sur l'historique git COMPLET + vérifie que le hook pre-commit est en place et non dérivé : un hook mort est une garde silencieusement absente, donc rouge et pas warning

- **Domicile** : `wama/common/management/commands/check_secret_leaks.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.10](../construction/suivi/ROADMAP.md)
- **Module** : check_secret_leaks — fuites de secrets dans l'HISTORIQUE GIT COMPLET (gitleaks), et présence du hook pre-commit qui empêche d'en créer de nouvelles.
- **API publique** (2) :
  - `binaire_gitleaks() -> Path`
  - `class Command(BaseCommand)`

### Intégrité des gabarits

Attrape la famille de fautes qui a récidivé SEPT fois : le commentaire `{# … #}` MULTI-LIGNE, que le lexer de Django (pas de re.DOTALL) rend en TEXTE littéral — et le nom de balise avaleuse écrit dans un commentaire. Un scan de 5 s contre des diagnostics qui ont coûté des sessions. Depuis le 01/09, signale AUSSI tout `{% load %}` vers une bibliothèque de balises absente (garde posée le jour où un retrait de templatetag a laissé son load — page reader en TemplateSyntaxError)

- **Domicile** : `wama/common/management/commands/check_templates.py` · **doc** : [AGENTS.md](../../AGENTS.md)
- **Module** : Intégrité des gabarits Django — le piège du commentaire `{# … #}` MULTI-LIGNE.
- **API publique** (2) :
  - `scanner(base=None)` — Renvoie la liste des défauts : [{fichier, ligne, genre, extrait}].
  - `class Command(BaseCommand)`

### Intégrité doc → code

Vérifie que chaque chemin, ligne et renvoi .md cité par la doc ET par les skills existe encore ; gate nocturne sur les CIBLES distinctes, pas sur les références

- **Domicile** : `wama/common/management/commands/check_docs.py` · **doc** : [AGENTS.md §Fichiers de référence](../../AGENTS.md)
- **Module** : Vérifie MÉCANIQUEMENT que les docs de référence disent vrai sur le code.
- **API publique** (1) :
  - `class Command(BaseCommand)`

### Journal transversal de l'utilisateur

Tout ce qu'il a lancé, toutes apps — DÉRIVÉ de detail_registry, aucune ligne par app

- **Domicile** : `wama/common/services/journal.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §9bis](../construction/ia/WAMA_MEMORY.md)
- **Module** : Journal de l'utilisateur — agrégat transversal de ce qu'il a lancé dans WAMA. Doc : `WAMA_MEMORY.md §9bis`.
- **API publique** (6) :
  - `class SourceJournal` — Un modèle dont les items entrent au journal.
  - `enregistrer_source(app, model, *, monde, champ_date=None, champ_user='user')` — Ajoute une source hors `detail_registry` — point d'extension des mondes studio/lab/data.
  - `sources()` — Toutes les sources du journal. Dérivées de `detail_registry` + les inscriptions explicites.
  - `class Entree` — Un item au journal. Volontairement MINCE — le détail vient des endpoints transversaux.
  - `entrees(user, *, mondes=None, apps=None, depuis=None, jusqu_a=None, limite=50, offset=0, avec_gestes=True, tri='recent', statut='all', q='')` — Rend `(liste d'Entree triée, total)`.
  - `compter_par_app(user, **kwargs)` — Répartition par app — alimente les filtres de la page sans requête supplémentaire côté vue.

### L'assistant, CLIENT MCP de la surface de développement

Le moteur de l'assistant RELAIE les outils `dev_*` (rôles wama-dev-ai, bac à sable) à la surface « wama-dev » par le protocole — process séparé, §16 tenu : rien n'est importé, la porte (droits à chaque appel, arguments admis) reste celle du serveur. Annoncés aux seuls développeurs/admins ; serveur absent = aucun outil, l'assistant répond quand même. Étape 5 de §8d, moitié dev (2026-09-22)

- **Domicile** : `wama/common/services/mcp_client.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Client MCP du moteur de l'assistant — la surface « wama-dev » vue DEPUIS l'assistant (ROADMAP §8d Phase 3, étape 5, moitié « outils de dev » ; demande de Fabien du 2026-09-22 : « améliorer WAMA depuis l'assistant, sans forcément passer par Claude, uniquement pour les rôles admin et dev »).
- **API publique** (5) :
  - `is_dev_tool(name: str) -> bool`
  - `dev_surface_url() -> str` — Adresse de l'endpoint MCP de la surface dev — le registre des sources externes fait foi.
  - `dev_tools_for(user) -> list` — Outils de développement que l'assistant peut ANNONCER à `user` :
  - `tools_block(tools: list) -> str` — Bloc de prompt des outils de dev — MÊME forme que `tool_api.build_tools_list`
  - `call_dev_tool(user, name: str, arguments) -> dict` — Relaie UN appel d'outil de dev à la surface, et rend son résultat comme `execute_tool`

### Langue des identifiants (budget)

Relève par AST les identifiants de code FRANÇAIS (classes, fonctions, arguments, variables, alias d'import ; accents = signal certain) et les borne par un BUDGET QUI NE PEUT QUE DESCENDRE : aucun chantier de renommage exigé, mais l'AJOUT devient impossible. Les méthodes `test_*` sont la seule exemption de doctrine ; les noms de classes de test le sont par défaut (zone grise, `--strict-classes` en donne le chiffre). Le test refuse aussi un budget qui garde de la MARGE — une marge est une autorisation d'en ajouter

- **Domicile** : `wama/common/management/commands/check_identifier_language.py` · **doc** : [AGENTS.md §Langue des identifiants](../../AGENTS.md)
- **Module** : Confronte la LANGUE des identifiants de code a la doctrine (AGENTS.md : « tout identifiant de code en ANGLAIS — les tests COMPRIS depuis le 2026-09-19 ; commentaires, docstrings et textes affiches restent en francais »).
- **API publique** (8) :
  - `is_french(name: str) -> bool`
  - `is_test_class(kind: str, name: str) -> bool`
  - `python_files(base: Path)` — Les `.py` du périmètre. Les jumelles bac à sable (`wama/<app>_NN/`, forme
  - `scan_test_names(base: Path)` — (francais, total) parmi les methodes `test_*` — la dette que le budget n'attrape PAS.
  - `roots_of(by_file)` — Radical francais -> nombre d'identifiants qui le portent. C'est l'outil de PILOTAGE :
  - `scan(base: Path, with_test_classes: bool=False)` — (total, par fichier, compteur de noms) — le relevé complet, sans rien écrire.
  - `counts(base: Path) -> dict` — Les TROIS comptes, additifs — c'est la seule lecture dont la commande et le test ont
  - `class Command(BaseCommand)`

### Marquage des sections de doc

Une balise `WAMA:SECTION(audience=…; type=…; nature=…; etat=…)` sous un titre dit à qui la section parle (développeur, utilisateur), quel genre de texte elle est (tutoriel, guide, référence, explication) et si elle CONSTATE ou VISE ; une sous-section hérite. `check_docs` contrôle le vocabulaire et la double vérification (constat ⇒ ✅, intention ⇒ 🔄/⏳) ; `extract` sert les docs dérivées

- **Domicile** : `wama/common/doc_sections.py` · **doc** : [docs/construction/suivi/ROADMAP.md §25](../construction/suivi/ROADMAP.md)
- **Module** : Marquage des SECTIONS de la doc de construction — à qui elles parlent, quel genre de texte elles sont, et si elles CONSTATENT ou VISENT (ROADMAP.md §25.1 ②).
- **API publique** (4) :
  - `class Section`
  - `parse_attrs(raw: str) -> Tuple[Dict[str, object], List[str]]` — `audience=…; type=…` → attributs + erreurs (vocabulaire ET double vérification).
  - `sections(texte: str) -> Tuple[List[Section], List[Tuple[int, str]]]` — Les sections d'un `.md` avec leurs attributs (propres ou hérités) + les erreurs de
  - `extract(texte: str, audience: str, type_: Optional[str]=None) -> List[Section]` — Les sections destinées à un public (et à un type, si précisé), dans l'ordre du texte.

### Menu contextuel de card/lot + débordement « … »

Clic droit = la liste COMPLÈTE des actions (+ celles de la SÉLECTION MULTIPLE) ; le « … » de la rangée = le DÉBORDEMENT SEUL, au-delà des 6 actions nominales (bouton édition compris — décision Fabien 2026-09-08). Modèle HYBRIDE : les actions EXISTANTES sont LUES sur le `.btn-group-actions` de la card (contrat de `cloneActions`, donc zéro ligne par app et clic PROXIFIÉ vers le vrai bouton), les TRANSVERSES sont déclarées et leurs URLs viennent de `queue_dnd_attrs` — une route absente n'émet pas son attribut, donc l'entrée n'apparaît pas. Sous-menus en CASCADE, au survol et au clic, le parent restant ouvert (2026-09-14) et DIFFÉRÉS (« Recherche… » puis rempli : il n'attend pas le réseau). Se ferme sur un geste de l'UTILISATEUR hors du menu, jamais sur un `scroll` (un focus programmatique le refermait en 7 ms). 2ᵉ surface : l'arbre de fichiers (`ouvrir()` depuis `filemanager.js`, 2026-09-14), qui obtient depuis le 2026-09-18 les gestes d'ÉLÉMENT (Partager…, Ajouter à la médiathèque…, Ajouter au RAG) sur un fichier de SORTIE par `entreesPourChemin` — le serveur remonte à l'élément (`send_to.item_for_output_path`), les entrées sont CELLES de la card (`entreesPourElement`, une seule liste), posées en ENTRÉE DIFFÉRÉE à la racine du menu (`{chargement, charger}` : « Recherche… » puis remplacement, le menu n'attend pas le réseau). ⚠ Le menu est posé sur `document.body` : une card vit dans un conteneur à `overflow` qui le rognerait. Le « … » suit les cards INSÉRÉES ou REMPLACÉES après le chargement (observation de la file, 2026-09-15)

- **Domicile** : `wama/common/static/common/js/wama-card-menu.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Modèles de NIVEAU DÉVELOPPEMENT (bridage « qualité max »)

UN domicile pour « quel modèle a le droit de travailler sur le code » : plancher sur le score coding du banc tiers (≥ 40) + déclaration explicite pour le seul distant non mesuré (albert:gpt-oss-120b), curseur imposé à 100 (réflexion), distants SOUVERAINS admis dès « cloud si saturé », et REFUS lisible plutôt qu'un petit modèle en repli. Lu par l'assistant (domaine dev, bascule en cours de tour dès qu'une compétence dev ou un outil dev_* est appelé, domaine collant au fil) et par les rôles wama-dev-ai (`role_utils.resolve_model`) — décision Fabien 22/09 après un tour réel où qwen3.5:4b inventait des jumelles

- **Domicile** : `wama/common/services/development_models.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : Modèles de NIVEAU DÉVELOPPEMENT — le bridage « qualité max » du travail sur le code (2026-09-22).
- **API publique** (7) :
  - `coding_score(model) -> float | None` — Sous-indice coding du banc tiers, ou None s'il n'est pas mesuré.
  - `is_development_grade(model) -> bool` — Ce modèle a-t-il le niveau développement ? Mesure d'abord, déclaration ensuite.
  - `dev_cloud_keys(user) -> set` — Modèles distants admis au tirage de DÉVELOPPEMENT pour `user` : la règle commune
  - `development_candidates(user) -> list` — `model_key` des modèles de conversation de niveau dev que `user` peut lancer : locaux
  - `development_model(user, requested: str=None) -> str | None` — Le modèle de niveau dev pour ce travail — `model_key` complet (`ollama:…`, `albert:…`), ou
  - `development_refusal(user=None) -> str` — La raison, lisible, quand aucun modèle de niveau dev n'est disponible.
  - `is_development_step(step: dict) -> bool` — Une étape d'outil qui fait ENTRER la conversation dans le travail sur le code : la

### Modèles DISTANTS au catalogue

Un modèle servi par une clé d'API entre au catalogue comme les autres (ligne `<source>:<id>`, `execution='cloud'`, le modèle porte son moteur et le fournisseur s'en DÉRIVE) : découverte par la clé de CHAQUE utilisateur (`GET /models` à l'enregistrement), le catalogue porte l'UNION, et `retire_unlisted` MARQUE ce que la source ne liste plus au lieu de le supprimer — une clé qui ne voit plus un modèle ne prouve pas qu'il a disparu. Ces lignes n'entrent au tirage que par `select_model(cloud_keys=…)`

- **Domicile** : `wama/model_manager/services/cloud_models.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Modèles DISTANTS au catalogue — découverte par la clé d'un UTILISATEUR (ROADMAP §8d Phase 3, 4b).
- **API publique** (12) :
  - `abilities_for(task: str, remote_type: str='') -> dict` — Drapeaux `ModelAbility` qu'une TÂCHE distante garantit — ceux que `select_model(requires=…)`
  - `class CloudDiscoveryError(RuntimeError)` — Découverte impossible — message lisible par l'utilisateur, jamais la clé.
  - `task_and_type(remote_type: str)` — (tâche NÔTRE, model_type) d'un type annoncé par le fournisseur, ou (None, None).
  - `list_remote_models(source: str, api_key: str, timeout: float=20.0) -> list` — Modèles ouverts à `api_key` chez `source` : [{id, name, type, aliases}].
  - `declared_listing(source: str) -> list` — Liste DÉCLARÉE d'un fournisseur sans liste de modèles (abonnement Claude Code : le CLI
  - `model_info_for(source: str, item: dict)` — `ModelInfo` d'un modèle distant rangeable, ou None si aucun vocabulaire ne sait le ranger.
  - `cloud_model_infos() -> dict` — `{model_key: ModelInfo}` de TOUS les modèles distants qu'une clé d'utilisateur ouvre —
  - `keys_for(source: str, listing: list) -> list` — Clés de catalogue des modèles rangeables d'une liste — ce que `UserApiKey.open_models` garde.
  - `retire_unlisted(source: str) -> int` — Marque indisponibles les lignes distantes de `source` qu'AUCUNE clé n'ouvre plus, et remet
  - `refresh_key(row) -> tuple` — Relit chez le fournisseur les modèles ouverts à la clé `row` (`accounts.UserApiKey`), puis
  - `cloud_refusal(user) -> str` — Motif de refus si `user` est en « 100 % local », sinon ''. Sans utilisateur : ''.
  - `allowed_cloud_keys(user, automatic: bool=True) -> set` — `model_key` des modèles distants que `user` autorise — à passer à `select_model(cloud_keys=…)`.

### Mémoire & RAG

Souvenirs + fragments sur pgvector, scope hérité de ScopedVisibility ; 5 opérations

- **Domicile** : `wama/common/memory/store.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md](../construction/ia/WAMA_MEMORY.md)
- **Module** : Les cinq opérations de la mémoire. Doc : `WAMA_MEMORY.md §5-6`.
- **API publique** (11) :
  - `class Hit` — Un résultat de rappel. `obj` est un `MemoryItem` ou un `RagChunk`.
  - `content_hash(text: str) -> str` — SHA-256 du contenu NORMALISÉ (espaces repliés, casse pliée).
  - `remember(content, *, kind, provenance, user=None, subject='', source_app='', source_object_type='', source_object_id=None, confidence=None, visibility=None, sc…` — Écrit un souvenir. Rend le `MemoryItem` (créé ou déjà existant), ou `None` en cas d'échec.
  - `recall(query, *, user, kinds=None, subject=None, k=8, include_rag=True, include_memory=True, semantic=True, resident=True, rag_niveaux=None)` — Retrouve les `k` meilleurs éléments visibles par `user`.
  - `reindex(*, lot=64, limite=None, modeles_obsoletes=False, dry_run=False)` — Calcule les vecteurs manquants, PAR LOT. Rend un résumé `{...}`.
  - `forget(item, *, reason='', hard=False, at=None)` — Invalide un souvenir — `valid_to = maintenant`. Il cesse d'être rappelé, sans disparaître.
  - `merge(items, *, seuil=0.92)` — PROPOSE de fusionner des souvenirs proches. N'ÉCRIT RIEN.
  - `apply_fusion(proposition, *, par_utilisateur)` — Applique UNE proposition de `merge()`. Réservé à un geste humain explicite.
  - `expire(*, jours_non_approuve=90, dry_run=True)` — Applique les politiques de rétention. Rend un résumé `{...}`.
  - `approve(item, *, par, visibility=None, scope_org_unit=None, scope_project=None)` — LE GESTE DE VALIDATION HUMAINE — ajouté le 2026-09-09, et son absence était le trou.
  - `list_memories(user, *, en_attente=False)` — Les souvenirs à AFFICHER — matière de la page « Mes souvenirs » (jumelle de « Mon RAG »).

### Outils de DÉVELOPPEMENT (surface MCP « wama-dev »)

Rôles wama-dev-ai (librarian, model, scout, integrator, codegen) et bac à sable d'apps, exposés à un client MCP. ⚠ JAMAIS chargé dans le process de PRODUCTION (ROADMAP §16 : défense en profondeur > scope de jeton) — ni dans `TOOL_REGISTRY` ni importé par `tool_api` ; seul `run_mcp_server --surface dev` l'importe, et `tests_mcp_dev_tools` le garde. Les rôles écrivent une PROPOSITION dans `wama-dev-ai/outputs/` et n'appliquent rien

- **Domicile** : `wama/common/services/dev_tools.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Outils de DÉVELOPPEMENT de WAMA — la surface du serveur MCP « wama-dev » (ROADMAP §8d Phase 3, étape 3).
- **API publique** (18) :
  - `class DevToolError(ValueError)` — Refus LISIBLE — rendu comme `{'error': …}`, jamais comme une trace.
  - `base_dir() -> Path`
  - `jobs_dir() -> Path`
  - `outputs_dir() -> Path`
  - `role_command(role: str, args=None, provider: str='', model: str='') -> list`
  - `sandbox_command(action: str, app: str='', target: str='', owner: str='') -> list`
  - `regen_check_command(app: str) -> list` — `--force` n'est JAMAIS ajouté : la garde du harnais (refus sur dev/main) reste entière.
  - `start_job(user, tool: str, argv: list) -> dict` — Lance `argv` détaché ; le journal et le code de retour sont écrits à côté de la fiche.
  - `job_state(job_id: str, with_log: bool=True) -> dict`
  - `dev_run_role(user, role: str, args: dict=None, provider: str='', model: str='') -> dict` — Lance un rôle wama-dev-ai en tâche de fond ; il écrit une PROPOSITION en attente de validation, n'applique rien.
  - `dev_sandbox(user, action: str, app: str='', target: str='') -> dict` — Bac à sable d'apps en tâche de fond : create, substitute, revert, drop, list — l'app d'origine n'est jamais modifiée.
  - `dev_regen_check(user, app: str) -> dict` — Harnais de régénération d'une app (app_regen_check) en tâche de fond — refusé sur dev/main par sa propre garde.
  - `dev_reload_web(user) -> dict` — Recharge gunicorn (signal HUP, rechargement gracieux) — nécessaire après la création, la restauration ou le retrait d'une jumelle.
  - `dev_job_status(user, job_id: str) -> dict` — État d'une tâche de développement : en cours, terminée, échouée ou interrompue ; fin du journal et propositions écrites.
  - `dev_list_jobs(user, limit: int=20) -> dict` — Dernières tâches de développement lancées (tous développeurs), la plus récente d'abord.
  - `dev_read_output(user, path: str) -> dict` — Lit une proposition écrite par un rôle (fichier JSON de wama-dev-ai/outputs/) — lecture seule.
  - `tools_for(user) -> list` — Outils de développement visibles par `user` — aucun pour un non-développeur.
  - `call(user, name: str, arguments) -> dict` — Un appel d'outil de développement — droits vérifiés ICI, à chaque appel.

### Partage d'un élément ou d'un lot (1ʳᵉ interface)

LE GESTE qui manquait au mécanisme de visibilité : `PROFILES_PERMISSIONS §7.5` disait « il n'existe AUCUNE interface de partage » (il fallait l'admin Django). Écrit `visibility` + son scope sur l'élément ET son lot — ou sur le lot ET ses éléments : les DEUX sens sont exigés, le filtre de lecture s'appliquant aux deux niveaux (un lot partagé aux éléments privés s'affiche VIDE chez le destinataire). Portées OFFRABLES dérivées de l'utilisateur (unités qui le couvrent, projets dont il est membre) : une portée sans cible réelle n'est pas proposée. Lecture seule par construction — l'écriture est le jalon S3 `AccessGrant`, et la modale le DIT

- **Domicile** : `wama/common/services/sharing.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : PARTAGE d'un élément de file — la première INTERFACE du mécanisme de visibilité.
- **API publique** (5) :
  - `class RefusDePartage(Exception)` — Refus MOTIVÉ : le motif est destiné à l'utilisateur, pas au journal.
  - `portees_offrables(user) -> list` — Ce que CET utilisateur peut offrir, avec les cibles réelles de chaque portée.
  - `partager(user, element, visibility, org_unit_id=None, project_id=None) -> dict` — Applique la portée à l'élément ET à son lot. Rend un compte-rendu.
  - `partager_lot(user, lot, modele_element, visibility, org_unit_id=None, project_id=None) -> dict` — Partage un LOT ENTIER : le lot et TOUS ses éléments.
  - `etat(element) -> dict` — La portée COURANTE d'un élément, telle que l'UI doit la pré-sélectionner.

### Projection des faits en souvenirs

RunOutcome → MemoryItem par OBJET (mécanique, sans modèle, idempotente)

- **Domicile** : `wama/common/memory/project.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7](../construction/ia/WAMA_MEMORY.md)
- **Module** : Projection des faits WAMA vers la mémoire. Doc : `WAMA_MEMORY.md §7` (jalon 4).
- **API publique** (1) :
  - `project_run_outcomes(*, depuis=None, limite=None, dry_run=False, user=None)` — Projette les gestes de `RunOutcome` en souvenirs épisodiques. Rend un résumé `{...}`.

### Provenance d'une entrée (source ⟷ copie de travail)

D'OÙ vient le fichier qu'une card consomme. La frontière était déjà tracée par le code — la SOURCE de vérité (médiathèque, temp, montage, URL) reste où elle est, l'ENTRÉE d'une card est une copie de travail jetable — mais rien ne reliait les deux. Quatre gestes en dépendaient, tous demandés et tous impossibles : la DÉDUP par provenance (mesuré le 11/09 : chaîner describer → imager → enhancer par « Envoyer vers » produit TROIS copies des mêmes octets), le retour app → médiathèque sans re-copie, savoir qu'une source a BOUGÉ au lieu de le découvrir au lancement, et surtout l'INDEX INVERSE — « qui référence ce fichier ? », la question que le gestionnaire de fichiers doit poser AVANT de supprimer. C'est lui qui lève la seule objection restée debout contre le pointage : on ne bloque pas la suppression, on la rend INFORMÉE (la card survit, l'utilisateur sait que sa source a disparu). ⚠ PAS de `GenericForeignKey` malgré la lettre de la décision du 07/09 : `RunOutcome` avait déjà tranché l'inverse avec sa raison écrite, on suit SA convention (`app`+`object_type`+`object_id`, plus `field` — un élément peut avoir plusieurs entrées). ⚠ ÉCRITE PAR LES BRIQUES SEULES : `copy_into_app_input` enregistre quand on lui donne l'élément, `record_import` est sa moitié pour le motif « copier PUIS créer ». Aucune app n'écrit sa provenance. ⭐ CÂBLÉE le 2026-09-22 (elle ne l'était qu'à UN site sur onze) : le répartiteur « Envoyer vers » enregistre pour tous les importeurs et leurs jumelles (`record_origin`, qui retrouve les cards par le chemin de leur copie), `ensure_local_input` pour une URL, les deux lots `-i` qui copient une ligne serveur ; nouveau `kind` `app` — « Envoyer vers » part aussi de l'entrée ou de la sortie d'une autre card

- **Domicile** : `wama/common/utils/provenance.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : PROVENANCE D'UNE ENTRÉE — d'où vient le fichier qu'une card consomme.
- **API publique** (9) :
  - `sha256_of(chemin, *, limite=SEUIL_EMPREINTE_OCTETS)` — Empreinte d'un fichier, ou `''` s'il est trop gros / illisible. Ne lève jamais.
  - `record_provenance(instance, field, *, kind, ref='', original_name='', source_path=None, user=None)` — Enregistre d'où vient `instance.<field>`. Remplace la trace existante, ne l'empile pas.
  - `ref_for(source_path)` — Adresse d'une source : son chemin relatif à `MEDIA_ROOT` s'il y vit, sinon son chemin brut.
  - `record_import(instance, field, source_path, *, kind='temp')` — La moitié complémentaire de `copy_into_app_input`, pour le motif « copier PUIS créer ».
  - `record_origin(copy_path, *, kind, ref, source_path=None)` — La provenance de TOUTES les cards qui portent cette copie, retrouvées par son chemin.
  - `kind_of(media_path) -> str` — La nature d'une source désignée par son chemin dans le gestionnaire de fichiers.
  - `provenance_of(instance, field)` — La provenance d'une entrée, ou `None`. Ne lève jamais.
  - `referenced_by(kind, ref)` — L'INDEX INVERSE — quelles entrées de cards désignent cette source ?
  - `same_source(kind, ref, user)` — Une copie de cette même source existe-t-elle déjà pour cet utilisateur ?

### Qui désigne ce fichier ? (déplacer, supprimer sans casser)

L'index des cards qui DÉSIGNENT un chemin, et les deux gestes qui le tiennent à jour — `repoint` quand le fichier bouge, `detach` quand il disparaît. Décision de Fabien du 2026-09-22 (`MEDIA_STORAGE_TIERING §8.6` D20) : déplacer ou renommer met à jour le lien des cards SANS rien demander ; supprimer un fichier qu'une card utilise demande d'abord une confirmation qui dit COMBIEN de cards il touche, puis laisse les cards en place, détachées. Avant, le gestionnaire renommait, déplaçait et supprimait sans jamais regarder les cards : c'est ce geste qui fabrique les « référencés mais absents » comptés par `check_media_integrity`. ⚠ DEUX façons de désigner, une seule met la card en péril : par un `FileField` (elle perd son fichier) ou par sa PROVENANCE (elle a sa copie — information, jamais un blocage). ⚠ `filemanager.UserFile` est exclu : c'est l'index du gestionnaire lui-même

- **Domicile** : `wama/common/utils/file_references.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : QUI DÉSIGNE CE FICHIER ? — l'index des cards qui utilisent un chemin, et les deux gestes qui le tiennent à jour quand le fichier bouge ou disparaît.
- **API publique** (6) :
  - `file_field_models()` — `[(modèle, [FileField…])]` pour tout le dépôt — UNE énumération, plusieurs lecteurs
  - `direct_references(path, *, folder=False) -> list` — Les cards dont un `FileField` porte ce chemin (ou, `folder=True`, un chemin SOUS ce dossier).
  - `source_references(path, *, folder=False) -> list` — Les provenances dont la SOURCE est ce chemin (ou un chemin sous ce dossier).
  - `usage(path, *, folder=False) -> dict` — Ce que le gestionnaire de fichiers doit savoir AVANT de supprimer.
  - `repoint(old_path, new_path, *, folder=False) -> dict` — Le fichier (ou le dossier) a bougé : chaque lien suit, directs et sources.
  - `detach(path, *, folder=False) -> int` — Le fichier a été supprimé (après confirmation) : les cards qui le désignaient restent,

### Serveur MCP (adaptateur mince sur tool_api)

Un seul contrat d'outils pour TOUS les cerveaux (Ollama, Claude Code, Albert, un IDE) : `tools/list` = le registre filtré par `tool_accessible`, `tools/call` = `execute_tool` — LA porte unique. Adaptateur MINCE : aucun protocole maison, `tool_descriptions()` dérive déjà nom/description/schéma. DEUX surfaces, DEUX process : `wama` (prod) et `wama-dev`, jamais chargés ensemble

- **Domicile** : `wama/common/services/mcp_server.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Serveur MCP de WAMA — l'adaptateur MINCE au-dessus de `tool_api`.
- **API publique** (8) :
  - `user_for_token(key: str)` — Compte ACTIF porteur de ce jeton d'API, ou None.
  - `class WamaTokenVerifier` — `TokenVerifier` du SDK adossé au jeton d'API WAMA — aucune seconde gestion de jetons.
  - `tools_for(user) -> list` — Outils MCP visibles par `user` — le registre filtré par ses droits, comme `/api/v1/tools/`.
  - `call(user, name: str, arguments) -> dict` — Un appel d'outil = `execute_tool`. Rien de plus.
  - `build_server(fixed_user=None, surface: str=SURFACE_WAMA)` — Serveur MCP d'une surface (`wama` ou `wama-dev`).
  - `serve_stdio(user, surface: str=SURFACE_WAMA) -> None` — Transport stdio : un process par client, compte fixé au lancement.
  - `http_address(host: str='', port: int=0, surface: str=SURFACE_WAMA) -> tuple` — (hôte, port) d'écoute — le registre des sources externes par défaut.
  - `build_http_app(host: str, port: int, surface: str=SURFACE_WAMA)` — Application ASGI : HTTP streamable, authentifiée par jeton, protégée du DNS rebinding.

### Signaux d'exécution

Journal append-only des FAITS observés sur un résultat (produit/corrigé/relancé…)

- **Domicile** : `wama/common/services/run_outcome.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.7](../construction/suivi/ROADMAP.md)
- **Module** : Capture des signaux d'exécution — la brique `RunOutcome` de la ROADMAP §16.7.
- **API publique** (5) :
  - `record(app: str, item, signal: str, *, model_keys=None, detail=None, user=None)` — Consigne un signal sur `item`. Retourne la ligne créée, ou None si rien n'a pu être écrit.
  - `correction_magnitude(before, after) -> dict` — Mesure une correction humaine sans l'interpréter : combien de segments, quelle distance.
  - `is_real_correction(measure: dict) -> bool` — La correction a-t-elle CHANGÉ quelque chose ? Garde-fou du signal `corrige`.
  - `count_signals(app: str='', since=None) -> dict` — Répartition brute des signaux, éventuellement filtrée. Sans interprétation.
  - `by_model(signal: str='', app: str='', single_model: bool=True) -> dict` — `{model_key: {signal: n}}` — de quoi ORDONNER des modèles quand le volume le permettra.

### Sortie d’app → médiathèque

Range le RÉSULTAT d'un élément comme asset, lu au schéma canonique du détail : toute app qui déclare son adapter a le geste sans une ligne. Le RÔLE est FOURNI (un .mp3 peut être voix/musique/bruitage) ; une seule route pour les 10 apps. ⚠ NE CONSTRUIT AUCUN CHEMIN — `upload_to` décide du domicile, donc le geste suit la refonte des dossiers utilisateur (chiffrement) au lieu de la figer. Les 2 copies manuelles (composer + sa jumelle) DÉLÈGUENT depuis le 2026-09-12, et un gardien AST refuse qu'une vue d'app recopie le geste. Surfaces : le menu « … » / clic droit des cards, le MÊME menu dans l'arbre de fichiers sur un fichier de SORTIE (2026-09-18), l'outil d'assistant. Le bouton dédié du composer et sa route d'app (seconde porte du même geste) sont RETIRÉS le 2026-09-18 (R64, R65) : le RÔLE se DÉCLARE au commun par l'app (`result_role` du détail canonique) et `admissible_roles` filtre — extension, puis rôle déclaré, pour les 10 apps ; non déclaré = l'utilisateur choisit. DEUX archétypes (§6.4), un geste : early-binding = le fichier déjà rendu, le choix est le rôle ; late-binding (transcriber, describer, reader) = le master texte est RENDU au format choisi par le builder du ⬇ (`register_export_builder`), asset `document`, coche et retrait par format (`export_choices`). ⚠ `synthesizer` n'était PAS une copie : son écriture d'asset est l'UPLOAD d'une voix, un autre geste.

- **Domicile** : `wama/media_library/services.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §2bis](../construction/ui/CARD_DESIGN.md)
- **Module** : Le GESTE « ranger une sortie d'app dans ma médiathèque » — brique COMMUNE.
- **API publique** (12) :
  - `enrich_asset_from_file(asset) -> None` — Ce que le FICHIER dit de l'asset — MIME, taille, et les `attributes` que la sonde commune
  - `candidate_asset_types(nom_fichier: str) -> list` — Rôles d'asset admissibles pour cette extension, dans l'ordre de `ASSET_TYPES`.
  - `admissible_roles(detail: dict, nom_fichier: str) -> list` — Les rôles que le geste PROPOSE pour cette sortie — et donc les seuls qu'il accepte.
  - `export_choices(app: str, detail: dict) -> list` — Les CHOIX que le geste propose pour cette sortie — `[{key, label, asset_type, format}]`.
  - `export_item_to_library(user, app: str, pk: int, asset_type: str='', name: str='', output_format: str='') -> dict` — Range le RÉSULTAT d'un élément d'app dans la médiathèque de son propriétaire.
  - `assets_of_item(user, app: str, pk: int)` — Les assets de `user` rangés depuis l'élément `app#pk` — par la PROVENANCE, jamais par le nom
  - `delete_asset(asset) -> None` — Supprime un asset ET son fichier, puis libère le drapeau d'app si plus rien n'en provient.
  - `in_library_by_choice(user, app: str, pk: int) -> dict` — Ce qui est DÉJÀ rangé depuis `app#pk`, indexé par la CLÉ de choix du menu — le rôle
  - `remove_item_from_library(user, app: str, pk: int, asset_type: str='', output_format: str='') -> dict` — Retire de la médiathèque ce qui a été rangé depuis `app#pk` (un rôle, un format, ou tout).
  - `gallery_assets()` — Les avatars de la galerie partagée, actifs, dans l'ordre d'affichage.
  - `gallery_entries() -> list` — `[{'name', 'url'}]` — ce dont les gabarits ont besoin, sans composer d'URL.
  - `gallery_path(name: str)` — Chemin ABSOLU de l'avatar nommé, ou `None` s'il n'existe pas (le worker en a besoin).

### Vulnérabilités des dépendances

CVE des paquets INSTALLÉS du venv courant via l'API OSV.dev (pas les requirements, qui sont des bornes basses). Contrat-cliquet : la dette connue vit dans une baseline versionnée par venv, toute vulnérabilité nouvelle est rouge

- **Domicile** : `wama/common/management/commands/check_dep_vulns.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.10](../construction/suivi/ROADMAP.md)
- **Module** : check_dep_vulns — vulnérabilités connues (CVE) des dépendances Python INSTALLÉES, via l'API OSV.dev (la même base d'avis que pip-audit, Dependabot ou Aikido).
- **API publique** (4) :
  - `label_venv() -> str` — Nom du venv qui exécute (venv_win / venv_linux) = clé de section de la baseline.
  - `inventaire() -> list[tuple[str, str]]` — (nom, version) des distributions installées dans CET interpréteur.
  - `interroger_osv(paquets: list[tuple[str, str]]) -> dict[str, list[str]]` — {"nom==version": [ids OSV]} — lève si l'API est injoignable.
  - `class Command(BaseCommand)`

## Contenu & prompts

### Accès LLM

Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local)

- **Domicile** : `wama/common/utils/llm_utils.py`
- **Module** : WAMA Common — LLM utilities Shared Ollama client for use in Celery workers (transcriber, describer, ...).
- **API publique** (12) :
  - `get_describer_model(content_type: str, output_style: str) -> str` — Return the Ollama model name to use for a given (content_type, output_style) pair.
  - `modele_par_defaut() -> str` — Modèle LLM à utiliser quand l'appelant n'en impose aucun — résolu, jamais figé.
  - `modele_par_tier(tier: str='default', exige=None, priority=None, prefer_loaded: bool=True) -> str` — Résolution PUBLIQUE d'un tier (`heavy`/`default`/`fast`) — même mécanique que
  - `ollama_chat(messages: list, model: str='', num_predict: int=2048, num_ctx: Optional[int]=None, think: bool=True, timeout: float=180.0, keep_alive: Optional[str…` — Send a chat request to the local Ollama server.
  - `default_cloud_model(provider: str) -> str` — Modèle par défaut d'un fournisseur cloud : réglage déclaré, sinon `CLOUD_DEFAULT_MODELS`.
  - `llm_chat(messages: list, model: str=None, provider: str=None, num_predict: int=2048, num_ctx: Optional[int]=None, think: bool=True, timeout: float=180.0, api_k…` — Unified LLM chat function — provider-agnostic entry point.
  - `extract_json_from_llm(text: str) -> Optional[dict]` — Extract the first valid JSON object from an LLM response.
  - `generate_meeting_summary(text: str, language: str='fr', speakers: Optional[list]=None, model: str='', provider: Optional[str]=None) -> str` — Generate a structured meeting summary (compte-rendu de réunion).
  - `verify_text_coherence(text: str, content_hint: str='transcription', language: str='fr', model: str='', provider: Optional[str]=None) -> dict` — Verify text coherence and suggest corrections.
  - `analyze_segments_coherence(segments: list, language: str='fr', model: str='', provider: Optional[str]=None) -> dict` — Analyse la cohérence PAR SEGMENT (1 seul appel LLM).
  - `suggest_speaker_names(segments: list, language: str='fr', model: str='', provider: Optional[str]=None) -> dict` — Propose des noms d'intervenants à partir des présentations dans la transcription.
  - `generate_structured_summary(text: str, content_hint: str='transcription', language: str='fr', model: str='', provider: Optional[str]=None) -> dict` — Generate a structured summary (summary, key_points, action_items).

### Appariement d'identité de canal

Relie une identité Matrix/Discord à un compte WAMA par code prouvé hors canal — la garde que tout adaptateur appelle avant d'agir

- **Domicile** : `wama/gateway/services.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19](../construction/suivi/ROADMAP.md)
- **Module** : Passerelle de canaux — appariement d'identité et résolution du compte.
- **API publique** (6) :
  - `class PairingError(Exception)` — Refus d'appariement — le message est destiné à l'utilisateur final.
  - `request_link(channel: str, external_id: str, external_label: str='') -> ChannelLink` — Enregistre (ou renouvelle) une demande de liaison et rend la ligne portant le code.
  - `pairing_url(code: str) -> str` — URL que le QR d'appariement encode : la page de profil, code prérempli.
  - `confirm_link(user, code: str) -> ChannelLink` — Scelle la liaison au profit de `user` — appelé DEPUIS WAMA, session authentifiée.
  - `account_for(channel: str, external_id: str)` — Compte WAMA d'une identité de canal, ou None.
  - `unlink(user, channel: str, external_id: str) -> bool` — Supprime une liaison — uniquement une des SIENNES. Rend True si quelque chose a sauté.

### Claude Code sur abonnement

Délègue une tâche de développement au CLI Claude Code en headless — lecture seule par défaut, environnement construit sans la clé API

- **Domicile** : `wama/common/services/claude_code.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19.3](../construction/suivi/ROADMAP.md)
- **Module** : Appel de Claude Code en mode headless, SUR L'ABONNEMENT du titulaire.
- **API publique** (4) :
  - `class ClaudeCodeIndisponible(RuntimeError)` — Le CLI est absent ou inexploitable — message destiné à l'utilisateur.
  - `subscription_allowed(user) -> bool` — Qui a le droit de consommer l'abonnement du titulaire — DOMICILE UNIQUE de la règle.
  - `chemin_cli() -> str` — Chemin du CLI Claude Code, ou lève une erreur explicite.
  - `demander(prompt: str, *, cwd: str | None=None, delai: int=DELAI_DEFAUT, outils=OUTILS_LECTURE, ecriture: bool=False, user=None) -> dict` — Soumet UNE tâche à Claude Code et rend son résultat.

### Export document

Génère PDF (fpdf2) / DOCX (python-docx) depuis les résultats d'app

- **Domicile** : `wama/common/utils/document_export.py`
- **Module** : WAMA — Document Export Utilities Génération de fichiers PDF (fpdf2) et DOCX (python-docx) à partir des résultats des applications Describer et Transcriber.
- **API publique** (7) :
  - `generate_description_pdf(description) -> bytes` — Generate a PDF from a Description instance.
  - `generate_description_docx(description) -> bytes` — Generate a DOCX from a Description instance. Returns raw bytes.
  - `generate_transcript_txt(transcript) -> bytes` — Génère un .txt mis en forme : avant-propos (titre/date/intervenants) + blocs
  - `generate_transcript_pdf(transcript) -> bytes` — Generate a PDF from a Transcript instance. Returns raw PDF bytes.
  - `generate_reader_pdf(item) -> bytes` — Generate a PDF from a ReadingItem instance. Returns raw PDF bytes.
  - `generate_reader_docx(item) -> bytes` — Generate a DOCX from a ReadingItem instance. Returns raw bytes.
  - `generate_transcript_docx(transcript) -> bytes` — Generate a DOCX from a Transcript instance. Returns raw bytes.

### Garde des URL sortantes

Valide toute cible de téléchargement pilotée par une saisie : schéma, identifiants, et adresses privées/bouclage/lien-local — anti-SSRF

- **Domicile** : `wama/common/utils/url_guard.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Garde des URL SORTANTES — WAMA ne doit pas devenir une sonde vers son propre réseau.
- **API publique** (3) :
  - `class UrlRefusee(ValueError)` — URL rejetée par la garde de sortie. Message destiné à l'utilisateur.
  - `verifier_url(url: str) -> str` — Valide une URL sortante. Rend l'URL normalisée, ou lève `UrlRefusee`.
  - `verifier_redirections(reponse) -> None` — Re-valide chaque hop d'une réponse `requests` qui a suivi des redirections.

### Générateur de QR codes

Encode un texte/URL en PNG/SVG (segno, déterministe) — QR d'appariement de la passerelle aujourd'hui ; enrôlement TOTP et domaine Imager demain

- **Domicile** : `wama/common/utils/qr.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19](../construction/suivi/ROADMAP.md)
- **Module** : Générateur de QR codes — brique COMMUNE (aucune logique d'app ici).
- **API publique** (2) :
  - `qr_png(data: str, *, scale: int=6, border: int=4) -> bytes` — Le QR en PNG (octets, en mémoire) — la forme qui se JOINT (message Discord, mail).
  - `qr_svg(data: str, *, scale: int=6, border: int=4) -> str` — Le QR en SVG (texte) — la forme qui s'EMBARQUE dans une page (enrôlement TOTP à

### Historique de conversation (serveur)

L'historique de l'assistant côté SERVEUR — remplace le localStorage web et le dict en mémoire de la passerelle (perdus au changement de navigateur / au redémarrage). COUCHE AU-DESSUS du moteur, jamais une dépendance : run_assistant_turn continue d'accepter un history explicite (moteur sans état, testable sans base). Consommé par la vue web ET la passerelle de canaux (gateway/core, discord_bot) — cf. ROADMAP §19.5

- **Domicile** : `wama/common/services/conversation_store.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19.5](../construction/suivi/ROADMAP.md)
- **Module** : Store de conversation — l'historique de l'assistant, côté SERVEUR.
- **API publique** (7) :
  - `thread(user, surface: str='web', thread_key: str='') -> Conversation` — Le fil de cet utilisateur pour cette surface — créé au besoin.
  - `history(conversation, limite: int=MAX_TOURS) -> list` — Les derniers tours du fil, au format attendu par `run_assistant_turn`.
  - `record_exchange(conversation, message: str, resultat: dict) -> None` — Enregistre le tour utilisateur ET la réponse de l'assistant, en une transaction.
  - `last_loaded_domain(conversation, limite: int=MAX_TOURS) -> str` — Domaine chargé au cours du fil (`charger_competence`, du plus récent au plus ancien), ou ''.
  - `display_entries(conversation, limite: int=60) -> list` — Les derniers tours du fil au format d'AFFICHAGE d'une surface : les étapes d'outils
  - `conversations_of(user, limite: int=50) -> list` — Fils d'un utilisateur, le plus récemment actif d'abord (liste d'UI).
  - `clear(user, conversation_id: int) -> bool` — Supprime UN fil — uniquement l'un des SIENS.

### Ingest de source

Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST

- **Domicile** : `wama/common/utils/source_ingest.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : source_ingest — Ingest média DÉCLARATIF et COMMUN (hors common/manifests/**).
- **API publique** (1) :
  - `ensure_local_input(instance, *, console=None, derive=None)` — Si `instance` déclare `WAMA_INGEST` et a une URL dans son champ source mais

### Intake universel de fichiers

Que peut faire WAMA de ce fichier ? — ports d'app + lot + manifeste + médiathèque + sondes des mondes (outil assistant inspect_user_file)

- **Domicile** : `wama/common/utils/intake.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : intake — « Que peut faire WAMA de ce fichier ? » : l'index inverse type → capacités (COMMUN).
- **API publique** (2) :
  - `register_intake_probe(key: str, fn) -> None` — Un monde déclare sa sonde d'intake (appelé depuis son `apps.py:ready()`).
  - `capabilities_for_path(path) -> dict` — Chemin de fichier → cibles typées AVEC leur rôle, composées des déclarations.

### Moteur de l'assistant IA

Boucle agentique multi-surface (prompts, outils tool_api, local/cloud) — la vue web et /api/v1/assistant/chat/ en sont des clients

- **Domicile** : `wama/common/services/assistant_engine.py`
- **Module** : Moteur de l'assistant IA — boucle agentique multi-surface (chantier « passerelle de canaux », étape 0).
- **API publique** (5) :
  - `assistant_settings(user) -> dict` — Réglages DURABLES de l'assistant pour `user` (brique commune `user_settings`, app
  - `resolve_turn_model(user, provider=None, model=None, domain=None) -> tuple` — (fournisseur, modèle) d'un tour — le fournisseur SE DÉRIVE du modèle, comme partout
  - `thinking_wanted(quality_intent) -> bool` — La réflexion du modèle est-elle demandée pour ce réglage de curseur ?
  - `conversation_turn(user, message: str, *, surface: str='web', thread_key: str='', provider: str=None, model: str=None, domain: str=None) -> dict` — UN tour, avec historique PERSISTÉ côté serveur — la voie normale pour une surface.
  - `run_assistant_turn(user, message: str, provider: str=None, model: str=None, history: list=None, domain: str=None) -> dict` — UN tour de conversation avec l'assistant WAMA — cœur SANS ÉTAT, commun à toutes les

### Pipeline de prompts

Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS

- **Domicile** : `wama/common/utils/prompt_enrichment.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : Enrichissement de prompt génératif (ROADMAP §16.6, hook « A » de la PromptPipeline).
- **API publique** (4) :
  - `enrichment_enabled(user=None) -> bool` — L'enrichissement automatique est-il actif pour cet utilisateur ?
  - `build_system(skill_text: str=None, *, language: str='en', contract: str=None) -> str` — System prompt d'enrichissement : skill d'app (ou `_SYSTEM` générique) + clause de langue
  - `enrich_generative(prompt: str, *, language: str='en', model: str=None, provider: str='ollama', glossary=None, console=None, timeout: int=60, skill_name: str=No…` — Étoffe un prompt génératif. Retourne l'enrichi, ou `prompt` inchangé si rien à faire / erreur.
  - `enrich_on_demand(prompt: str, *, app: str=None, domain: str=None, language: str='en', model: str=None, glossary=None, timeout: int=60, keep_alive: str=_KEEP_AL…` — Enrichissement EXPLICITE (bouton ✨) : le clic vaut demande → pas d'interrupteur maître.

### Recherche & lecture web

Recherche internet + page → texte plafonné (octets ET caractères) pour l'investigation de l'assistant (outils search_web/read_web_page)

- **Domicile** : `wama/common/utils/web_search.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : web_search — Recherche internet + lecture de page en CHAÎNE (COMMUN).
- **API publique** (2) :
  - `search_web(query: str, max_results: int=5) -> list` — Recherche web → [{'title', 'url', 'snippet'}], au plus `max_results` (borné 1-10).
  - `read_web_page(url: str, max_bytes: int=DEFAULT_MAX_BYTES, max_chars: int=DEFAULT_MAX_CHARS) -> dict` — Page publique → {'url', 'final_url', 'text', 'truncated'} — texte lisible borné.

### Skills de rôle de l'assistant

Posture et domaine de l'assistant (science, design, dev) + rappel du contexte de laboratoire, déclarés par domaine — distinct de l'enrichissement

- **Domicile** : `wama/common/utils/assistant_skills.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19.7](../construction/suivi/ROADMAP.md)
- **Module** : Skills de RÔLE de l'assistant — qui il est, ce qu'il sait, comment il répond.
- **API publique** (7) :
  - `class AssistantDomain` — Un domaine d'intervention de l'assistant.
  - `resolve_domain(key: str=None) -> AssistantDomain` — Domaine déclaré, ou le domaine par défaut si la clé est inconnue (fail-safe).
  - `domains_for_ui() -> list` — Options du sélecteur de domaine — dérivées du registre, jamais réécrites à la main.
  - `role_instructions(key: str=None) -> str` — Texte du skill de rôle pour ce domaine — '' si le fichier est absent.
  - `competences_announcement(sauf: str=None) -> str` — Ligne d'annonce injectée au prompt système : quelles compétences existent, et comment
  - `laboratory_context(user, question: str, key: str=None) -> str` — Extraits du corpus du laboratoire pertinents pour la question — '' si rien.
  - `greeting(user) -> dict` — Textes d'accueil pour cette surface : {'message', 'attente', 'attente_apres_ms'}.

## Manifestes & registres

### Adoption des mécanismes

Qui consomme quoi (imports + briques front), niveau APP vs infrastructure, et jonction registre↔grille : mécanisme adopté par des apps que rien ne vérifie

- **Domicile** : `wama/common/services/mecanismes_scan.py` · **doc** : [docs/construction/architecture/WAMA_MECANISMES.md](../construction/architecture/WAMA_MECANISMES.md)
- **Module** : Balayage d'ADOPTION des mécanismes : qui consomme quoi, et à quel niveau.
- **API publique** (8) :
  - `python_modules(base: Path)` — Chemins .py de notre code (relatifs à base), vendored et artefacts élagués.
  - `front_sources(base: Path)` — Chemins .html/.js de notre front (templates + static d'app), relatifs à base.
  - `load_sources(base: Path | None=None) -> dict[str, str]` — {chemin relatif: contenu} pour tout le corpus balayé. Coûteux : à charger UNE fois.
  - `consumers(mechanism, sources: dict[str, str]) -> list[str]` — Fichiers qui IMPORTENT le domicile (ou une annexe), hors le mécanisme lui-même.
  - `consuming_apps(mechanism, sources: dict[str, str], found=None) -> list[str]` — Apps du catalogue dont au moins un fichier NON-HARNAIS consomme le mécanisme.
  - `adoption_matrix(sources: dict[str, str] | None=None) -> dict` — Mesure complète, UNE passe : {key: {'consommateurs': [...], 'apps': [...], 'niveau_app': bool}}.
  - `mechanisms_without_criterion(sources: dict[str, str] | None=None) -> list[tuple]` — LE contrôle de jonction : mécanismes de NIVEAU APP qu'AUCUN critère de grille ne vérifie.
  - `orphan_criteria() -> list[str]` — Garde-fou SYMÉTRIQUE : critère dont le `mechanism=` ne correspond à aucune clé du registre.

### Application du corpus de manifestes

Le sens ENTRANT du corpus : `manifest_export` écrit les manifestes DEPUIS les registres, rien ne les appliquait DANS l'autre sens. Sur une installation neuve, les 16 manifestes de librairies restaient lettre morte. ⚠ Kind par kind, et le choix est de NATURE : `library` est une déclaration pure (aucune I/O) → appliquée à l'installation ; `model` NON, car le catalogue reflète le DISQUE et sa vérité est le balayage (déjà périodique) — l'appliquer créerait des lignes pour des poids absents. Dry-run par défaut

- **Domicile** : `wama/common/management/commands/apply_manifests.py` · **doc** : [docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md](../construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md)
- **Module** : Applique le CORPUS de manifestes aux registres — le sens ENTRANT, qui manquait.
- **API publique** (1) :
  - `class Command(BaseCommand)`

### Audit des licences

Vue dérivée : licences+auteurs des 4 registres, traversée par app. Ne voit PAS le code vendorisé (`static/vendors/`, codeformer) — inventorié à la main dans LICENSING.md §3

- **Domicile** : `wama/common/services/license_audit.py` · **doc** : [docs/construction/exploitation/LICENSING.md](../construction/exploitation/LICENSING.md)
- **Module** : Audit des licences — VUE DÉRIVÉE sur les registres, jamais un registre de plus.
- **API publique** (5) :
  - `normaliser_licence(brut) -> str` — Texte libre → identifiant canonique. `''` si rien d'exploitable.
  - `qualifier(licence: str) -> dict` — `{id, famille, rang, libelle, attribution}` — `rang` croît avec la contrainte.
  - `inventaire(user=None) -> list` — Toutes les lignes des registres, chacune qualifiée. Aucune écriture.
  - `par_app(lignes=None) -> list` — Pour chaque app : les licences TRAVERSÉES par ce qu'elle requiert, et la plus contraignante.
  - `synthese(user=None) -> dict` — Photo complète : lignes, répartition, plus contraignante, et ce qu'il faut citer.

### Bac à sable d'apps (jumelles exécutables)

Jumelle <app>_NN coexistante pour comparaison Playwright + diff par témoins (route §10.3 marches S/S2) — registre sandbox_apps.json injecté au boot (INSTALLED_APPS/urls/gating/catalogue) ; create/drop symétriques + `substitute <label> <cible>` : remplace UN fichier copié par sa version GÉNÉRÉE (cibles = gabarits `codegen`), témoin `.temoin` préservé, re-mesure, auto-revert sur échec — verdicts journalisés au registre ; `revert <label> <cible>` ramène une cible au témoin à la demande. TROIS JUGES depuis le 03/09, chacun né d'un défaut qui RENDAIT (page 200) sans FONCTIONNER : ① cohérence de paquet par AST (tout `from .x import Y` intra-paquet, imports PARESSEUX compris, doit résoudre) ; ② couple views↔templates (substituer les templates seuls = boutons morts) ; ③ smoke « file HABITÉE » (témoin créé→page rendue→supprimé : une file vide ne rend AUCUNE card, donc ne teste rien du rendu de card). Le gate d'acceptation d'une jumelle reste sa BATTERIE UI auto-dérivée (11 scénarios `<label>.*` du registre nocturne) : describer_01 = 11/11

- **Domicile** : `wama/common/sandbox.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Bac à sable d'apps — jumelles EXÉCUTABLES (route §10.3, marche S, actée Fabien 2026-08-18).
- **API publique** (11) :
  - `load_registry() -> list` — Liste des jumelles [{label, generated_from, created, created_by?}] — [] si registre
  - `twin_owner(label: str) -> str` — Username du créateur d'une jumelle ('' si CLI/inconnu) — consommé par la dérogation
  - `twin_source(label: str) -> str` — App SOURCE d'une jumelle ('' si ce label n'en est pas une).
  - `save_registry(entries: list) -> None`
  - `sandbox_labels() -> list` — Labels des jumelles dont le PACKAGE existe réellement (garde anti-registre orphelin :
  - `twins_with_copied_views() -> set` — Labels des jumelles dont les VUES sont une COPIE figée de l'app source (non régénérées).
  - `sandbox_installed_apps() -> list` — Entrées INSTALLED_APPS des jumelles (consommé par settings.py).
  - `sandbox_urlpatterns()` — URLconfs des jumelles — préfixe = label (underscore assumé : `/converter_01/` — le
  - `inject_sandbox_access(default_app_access: dict, app_group: dict) -> None` — Gating DEV-ONLY des jumelles (contrat marche S §3) + groupe d'affichage dédié.
  - `inject_sandbox_catalog(app_catalog: dict) -> None` — Entrées APP_CATALOG des jumelles : CLONE de l'app source (mêmes conventions — la
  - `non_sandbox_apps(app_catalog: dict) -> list` — Apps RÉELLES du catalogue (les jumelles sont exclues de la grille de conformité :

### Environnement d'exécution d'un backend

`ISOLATION` déclare où tourne un backend (`venv:<chemin>` | `service:<url>`, vide = venv principal). Sans elle le GRISAGE MENT : `missing_packages()` interroge `find_spec` dans CE processus, verdict muet sur un backend qui vit ailleurs. Le défaut est UN venv — l'isolement se DÉCLARE, ne se génère jamais : son coût n'est pas le disque mais la VRAM, chaque processus isolé étant un détenteur que le gouverneur ne voit pas. Zéro isolement aujourd'hui

- **Domicile** : `wama/common/backends/base.py` · **doc** : [docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md](../construction/exploitation/INFRA_WSL_VS_WINDOWS.md)
- **Module** : Contrat de backend de modèle COMMUN à WAMA — extrait de l'app de référence (Transcriber).
- **API publique** (4) :
  - `unload_live_backends(model_key: Optional[str]=None, exclude_sources=None) -> int` — Décharge les backends résidents de CE process ; rend le nombre d'instances déchargées.
  - `refresh_live_reservations() -> int` — Rafraîchit le TTL de la ligne de registre de chaque backend résident de CE process.
  - `start_reservation_heartbeat() -> bool` — Lance, UNE fois par process, le battement qui garde vivantes les lignes des résidents.
  - `class BaseModelBackend(ABC)` — Backend de modèle local (chargement/déchargement + traitement).

### Formats de sortie

Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire converter)

- **Domicile** : `wama/common/utils/output_formats.py`
- **Module** : Source COMMUNE des formats + qualités de FICHIER de sortie — pendant de voice_options pour la sortie.
- **API publique** (4) :
  - `get_output_formats(domain: str) -> List[Tuple[str, str]]` — [(valeur, libellé)] des formats de fichier de sortie pour un domaine. 'original' = inchangé.
  - `get_output_qualities(domain: str | None=None) -> List[Tuple[str, str]]` — Presets de qualité (web/équilibré/max). `domain` réservé pour d'éventuelles variantes futures.
  - `output_format_params(domain: str, contexts=None, dom_id_format=None, dom_id_quality=None, include_quality: bool=True, group: str | None=None) -> list` — Fabrique les Param COMMUNS output_format (+ output_quality) pour un domaine, prêts à concaténer au
  - `output_format_params_for_app(app_name: str, contexts=None, dom_id_format=None, dom_id_quality=None, include_quality: bool=True, group: str | None=None) -> list` — AUTO depuis APP_CATALOG : lit `multi_format_download` (early/late) + déduit le domaine des

### Gabarits de génération d'app (marches S2 + B1)

Rend le code CONVENTIONNEL d'une app depuis son manifeste — une cible par fichier (apps/urls/models/params/tasks/views/templates), consommées par `app_sandbox substitute` et le write-back ; le hors-convention reste un TROU NOMMÉ (stubs 501, commentaires [manifest-gen]), jamais un manque silencieux. Depuis le 02/09 (marche B1 CLOSE), le corps des TÂCHES se COMPOSE aussi : `backends/__init__.ROUTES` de l'app (nature → callable au contrat commun) monte au manifeste (processing.backend_routes) et tasks_gen émet l'appel — import relatif au paquet, la jumelle a CONVERTI (SUCCESS mesuré). DEUX SAVEURS depuis le 03/09 (2ᵉ app routée, describer) : `RESULT` déclare ce que les backends produisent — 'file' (le backend écrit output_path) ou 'text' (il REND le texte, la tâche le persiste dans la colonne déclarée et publie l'aperçu partiel) ; `NATURE_FIELD` nomme la colonne de nature. ⚠ Un fichier substitué doit exposer TOUT ce que les fichiers COPIÉS lui importent : params_gen émet l'alias `<X> = <X>_JSON` (le models copié importe la graphie courte — ImportError au rendu de CHAQUE card sinon)

- **Domicile** : `wama/common/manifests/codegen/templates_gen.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Gabarit `templates/<app>/index.html` (marche A — v1, marche S2).
- **API publique** (1) :
  - `render_index(manifest: dict) -> tuple` — (source, raison) — templates/<app>/index.html conventionnel, jamais partiel.

### Grille de conformité

Mesure les 8 facettes F1–F8 des apps par analyse du code réel

- **Domicile** : `wama/common/services/conformity_checker.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : Vérification AUTOMATISÉE de conformité des apps — confrontation au RÉEL.
- **API publique** (2) :
  - `class Criterion`
  - `run_checks(app_ids: list[str]) -> dict` — Exécute tous les critères sur chaque app. Retourne le rapport sérialisable.

### Manifestes

Extraction/validation/projection des 7 kinds vers les registres

- **Domicile** : `wama/common/manifests/ingest.py` · **doc** : [docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md](../construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md)
- **Module** : Moteur d'INGEST — validate → (sandbox) store → verify → promote → un-ingest.
- **API publique** (9) :
  - `validate(manifest: dict) -> list[str]` — Erreurs d'enveloppe + erreurs de body (déléguées au kind) + références pendantes.
  - `resolve_requires(manifest: dict) -> tuple[list[dict], list[str]]` — Résout les références `requires` de l'ENVELOPPE (SPEC §7.3) — kind-agnostique.
  - `ingest(manifest: dict, *, user=None, promote_to: Optional[str]=None, strict: bool=True)` — Crée ou met à jour la ligne `Manifest` (idempotent sur kind+key).
  - `promote(obj, visibility: str, *, scope_project: str='', scope_org_unit: str='')` — Fait sortir un manifeste du sandbox vers le commun. Le GATING (droit de promouvoir vers telle
  - `extract(kind: str, key: str) -> Optional[dict]` — Produit le manifeste d'un objet EXISTANT en lisant les registres courants (round-trip).
  - `write_back(manifest: dict, *, apply: bool=False)` — Projette (write-back) le manifeste vers l'état committé — geste EXPLICITE, jamais automatique
  - `verify(manifest: dict) -> list[dict]` — Retourne la liste des écarts entre le manifeste fourni et l'état courant des registres.
  - `un_ingest(kind: str, key: str) -> bool`
  - `diff_dicts(a: Any, b: Any, path: str='') -> list[dict]` — Écarts a(=manifeste) vs b(=courant). Ordre des listes ignoré pour les listes de scalaires.

### Onglets de résultat TEXTE

Un item peut avoir PLUSIEURS lectures d'un même résultat (transcription, diarisation, résumé, cohérence). Le schéma canonique ne portait qu'UN `result_text` — d'où deux modales à onglets quasi identiques, tracées au `REMOVAL_LEDGER R18` depuis le 22/07. Les facettes se déclarent désormais dans la SPEC DE DÉTAIL de l'app (donc extractibles au manifeste, facette `inspector`, et projetables), et un partial commun les rend. ⚠ Ce n'est PAS une 2ᵉ mécanique de preview : la preview de CARD reste `PreviewRegistry`, et les autres apps n'ont qu'une lecture — ou plusieurs RÉSULTATS dans une seule preview (imager, `result_files`)

- **Domicile** : `wama/common/templates/common/_result_tabs.html` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Passe-plat des déclarations de modèle

Lire la déclaration d'un modèle SANS importer l'app qui la porte : applique la convention `wama/<app>/utils/model_config.py::<APP>_MODELS`, ne connaît aucune app, et surtout ne touche AUCUNE BASE. ⚠ Le catalogue `AIModel` porte la même information, mais le lire ajouterait une dépendance ORM à chaque backend — or c'est justement l'absence de Django qui les rend déplaçables. On lirait la bonne donnée en détruisant la propriété cherchée

- **Domicile** : `wama/common/utils/model_declarations.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Lire la DÉCLARATION d'un modèle sans importer l'app qui la porte.
- **API publique** (1) :
  - `declaration(source: str, model_id: str) -> Optional[dict]` — Déclaration de `model_id` telle que l'app `source` la porte, ou None.

### Routage des poids hors HuggingFace

QUATRE leviers pour tenir la règle « modèle principal catégorisé, sous-dépendances au cache partagé » (ROADMAP §5b), et le choix est imposé par la LIB, pas par le goût : A `cache_dir=` — B un CHEMIN local (`poids_locaux`) — C la variable propre à la lib, posée dans settings (`DEEPFACE_HOME`, `AUDIOCRAFT_CACHE_DIR`) — D `hf_cache_scope`, DERNIER RECOURS déclaré. ⚠ D restaure l'environnement mais JAMAIS LES FICHIERS : ce que la lib télécharge pendant la fenêtre reste dans le dossier du modèle — c'est ainsi que `timm/resnet18` a atterri chez table-transformer. Zéro mutation d'environnement dans le code aujourd'hui

- **Domicile** : `wama/common/utils/hf_weights.py` · **doc** : [docs/construction/suivi/ROADMAP.md](../construction/suivi/ROADMAP.md)
- **Module** : Poids d'un modèle rangés dans SON dossier — pour les libs qui n'acceptent pas `cache_dir=`.
- **API publique** (1) :
  - `poids_locaux(hf_id: str, dossier: str | Path, *, patterns: Optional[Sequence[str]]=None, token: Optional[str]=None, revision: Optional[str]=None) -> str` — Chemin LOCAL des poids de `hf_id`, garantis présents sous `dossier`.

### Résolution de backend par DÉCLARATION

Une app ne demande plus un MODULE, elle demande « le backend qui sait exécuter ce modèle » : `backend_for_model()` va de `composition.runtime.engine` (moitié modèle) à `BaseModelBackend.ENGINE` (moitié backend), départagé par `SUPPORTED_MODELS` quand le moteur est PARTAGÉ — `diffusers` est piloté par 8 backends, `transformers` par 4. L'import de la classe est CIBLÉ et TARDIF : le registre reste statique. C'est ce qui rend l'EMPLACEMENT PHYSIQUE des backends indifférent, préalable à leur passage au substrat transversal. ⚠ Rend None plutôt qu'un tirage quand rien ne tranche — une erreur silencieuse coûte plus cher qu'un refus ; et ne rend QUE des sous-classes du contrat (le porteur du démon Ollama n'en est pas un)

- **Domicile** : `wama/common/backends/manager.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Manager de backends COMMUN — extrait du pattern Transcriber/Imager.
- **API publique** (12) :
  - `register_engine_inventory(fn) -> None` — Enregistre un inventaire de moteurs. Le callable rend soit un MAPPING
  - `engine_backends() -> dict` — {moteur: classe de backend} pour tous les inventaires qui exposent leurs classes.
  - `invalidate_engine_cache() -> None` — À appeler après une installation de librairie : le prochain `known_engines()`
  - `known_engines() -> set` — Moteurs réellement EXÉCUTABLES — inventaires relus à CHAQUE appel (ré-autorisation
  - `backend_for_engine(engine: str, model_id: str='', entries=None)` — Classe de backend qui pilote `engine` (et sert `model_id` si le moteur est partagé).
  - `backend_for_model(model, entries=None)` — Classe de backend qui sait exécuter `model`, ou None.
  - `backend_for_key(model_key: str, entries=None)` — La MÊME porte que `backend_for_model`, adressée par la CLÉ de catalogue (`<source>:<id>`).
  - `invalidate_catalog_index() -> None` — Le prochain `catalog_keys_for_owner` relit le catalogue (après une synchro, un test).
  - `match_local_name(rows, name: str) -> list` — Clés, parmi les lignes `(clé, hf_id)` d'une classe, que désigne le nom local `name`.
  - `catalog_keys_for_owner(owner: str) -> list` — Clés catalogue désignées par une clé d'owner du registre VRAM — [] si rien ne se résout.
  - `backend_missing(model) -> Optional[str]` — Raison si `model` est POSITIVEMENT sans backend, sinon None.
  - `class BackendManager` — Registre + cycle de vie de backends `BaseModelBackend` (singletons keep_loaded).

### Vivier des backends (registre DÉRIVÉ)

Inventaire des moteurs de WAMA, dérivé À CHAQUE AFFICHAGE des déclarations `wama/<app>/backends/` (ROUTES/RESULT/NATURE_FIELD + classes BaseModelBackend trouvées jusque dans les SOUS-MODULES) recoupées au catalogue AIModel. Deux usages : la vision d'ensemble (12ᵉ registre, page /common/backends/) et le VOISINAGE que le LLM de la marche B trie pour s'inspirer du backend le plus approchant (signature « natures → saveur », paquets, VRAM, modèles servis). Ne stocke RIEN et n'a pas de rafraîchisseur — une page qui DÉRIVE ne peut pas diverger de ses sources. Ne cite aucune app : il parcourt les apps installées (le registre ne connaît jamais ses producteurs). ⚠ MISE À JOUR 2026-09-06/07 — le lien FIN EXISTE désormais et `backend_ref` n'absout plus : le modèle déclare son moteur (`composition.runtime.engine`), le backend déclare celui qu'il pilote (`ENGINE`) et ce qu'il sert (`SUPPORTED_MODELS`), et l'inventaire porte les COORDONNÉES D'IMPORT pour résoudre PARESSEUSEMENT. Mesuré : 108/116 modèles déclarent leur moteur (14 la veille), 97 résolvent leur backend réel. `backend_ref` ne sert plus qu'à la PROVENANCE du lien

- **Domicile** : `wama/common/services/backend_inventory.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Registre des BACKENDS — vue DÉRIVÉE du vivier de moteurs de WAMA (demande Fabien 2026-09-03).
- **API publique** (12) :
  - `class BackendEntry` — UN backend exécutable — la maille que le LLM compare pour trouver « le plus approchant ».
  - `class AppBackends`
  - `inventory() -> List[AppBackends]` — Le vivier, DÉRIVÉ à l'appel. Une app = une entrée ; jamais de nom d'app en dur ici.
  - `summary() -> dict` — Chiffres de tête de page + le vivier. Aucun compteur recopié ailleurs (un chiffre vit
  - `declared_engines() -> dict` — {moteur: classe de backend} DÉRIVÉ des déclarations `ENGINE` des backends.
  - `count() -> int` — Total de backends du vivier (apps réelles) — pour le registre des registres.
  - `orphelins(entrees, servis) -> tuple` — (muets, expliqués) — backends qu'AUCUN modèle ne désigne, séparés par la RAISON.
  - `resolvable_entries() -> List[BackendEntry]` — Le vivier que la résolution consulte — jumelles de bac à sable exclues. Un appelant qui
  - `resolve_entry(engine: str, model_id: str='', entries=None) -> Optional[BackendEntry]` — ENTRÉE du vivier qui sait exécuter `model_id` avec `engine` — ou None. STATIQUE :
  - `resolve_backend(engine: str, model_id: str='', entries=None)` — Classe de backend qui sait exécuter `model_id` avec `engine` — ou None.
  - `app_backend_entries(app: str) -> List[BackendEntry]` — Backends que `app` RÉSOUT réellement, par le lien du catalogue — STATIQUE, dédoublonnés
  - `app_backend_paths(app: str) -> List[Path]` — Fichiers source des backends résolus par `app` (cf. `app_backend_entries`), n'existant

## File d'attente & lots

### Console utilisateur

Lignes de journal structurées par utilisateur et par app. ⚠ Annoncé « via Redis », mais le chemin Redis exige `django_redis` — ABSENT des deux venvs et des `requirements` (vérifié 2026-08-22) : la console tourne DEPUIS TOUJOURS sur son repli cache, qui fonctionne mais n'est pas atomique (lire/insérer/réécrire, donc des lignes perdues quand gunicorn et les workers Celery poussent en même temps). Le correctif n'est PAS d'ajouter la dépendance : le client `redis` brut est déjà installé et la brique d'accès existe (`resource_governor._redis`, via `CELERY_BROKER_URL`)

- **Domicile** : `wama/common/utils/console_utils.py`
- **Module** : WAMA Unified Console Logging
- **API publique** (2) :
  - `push_console_line(user_id: int, line: str, level: str='info', app: str='system', maxlen: int=500) -> None` — Append a structured log line to the user's console buffer.
  - `get_console_lines(user_id: int, levels: Optional[List[str]]=None, app: Optional[str]=None, limit: int=200) -> List[dict]` — Retrieve structured console lines for a user.

### Dossier de travail jetable

Les fichiers INTERMÉDIAIRES d'un traitement ne vivent pas dans `media/`. Mesuré le 2026-08-25 : `media/avatarizer/` pesait 1,69 Go pour 2101 fichiers dont 99,6 % de PNG — les frames de CodeFormer, écrites dans le dossier de sortie du job et jamais nettoyées ; `job_11` portait 1715,7 Mo pour une vidéo de 0,70 Mo. `media/` ne contient que `<app>/<user>/input|output/` et `users/` (MEDIA_STORAGE_TIERING.md) : un fichier de travail y est sauvegardé par le miroir, compté par le tiering et servi par Apache pour rien. Le `with` rend le nettoyage STRUCTUREL au lieu d'être une convention qu'on oublie. ADOPTÉ par 5 sites (avatarizer/codeformer, describer/views, enhancer/views, reader/glm_ocr, describer/video_describer) ; le dernier site, la boucle vidéo de l'enhancer (ex-`tasks.py:534`), est porté depuis le 26/08 et vit depuis le 21/09 dans sa route `enhancer/backends/media_backend.py:82` (la glu `enhancer/tasks.py:156` en ouvre un second pour ranger la sortie). ⚠⚠ L'audit AUTOMATIQUE des `mkdtemp` a mal classé 2 sites sur 6 — `glm_ocr` déléguait par contrat DOCUMENTÉ, `enhancer/tasks` nettoyait déjà — mais la lecture site par site a trouvé l'inverse, des fuites qu'aucun motif ne voyait : un `rmdir` conditionné à « si le dossier est vide » qui ne se déclenchait donc jamais, un nettoyage placé APRÈS l'appel qui sautait sur exception, et un `except ImportError` qui empêchait un repli d'exister. Un relevé par motif oriente ; il ne conclut pas. Porte aussi `purge_job_dir` : la suppression d'une card doit emporter le dossier du job — 13 dossiers `job_*` orphelins relevés contre 4 rattachés

- **Domicile** : `wama/common/utils/work_dir.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Dossier de TRAVAIL jetable — les fichiers intermédiaires ne vivent pas dans `media/`.
- **API publique** (2) :
  - `work_dir(prefix: str='wama_work')` — Crée un dossier de travail jetable et le supprime À LA SORTIE, même sur exception.
  - `purge_job_dir(base_dir, job_id, *, prefix: str='job_') -> int` — Supprime le dossier de job `<base_dir>/<prefix><job_id>/`. Rend le nombre d'octets libérés.

### Duplication et suppression sûres

duplicate_instance() et safe_delete_file() — fichiers partagés entre items

- **Domicile** : `wama/common/utils/queue_duplication.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : WAMA — Common utilities for queue item duplication and safe file deletion.
- **API publique** (4) :
  - `owns_file(instance, file_name: str) -> bool` — Le fichier vit-il dans le DOMICILE de l'app de cette card (`users/<uid>/<app>/…`) ?
  - `safe_delete_file(instance, field_name: str) -> bool` — Delete a FileField's physical file only if it is the card's OWN file and no other row
  - `is_shared_elsewhere(instance, field_name: str, file_name: str) -> bool` — Une AUTRE ligne du même modèle désigne-t-elle ce fichier dans le même champ ?
  - `duplicate_instance(instance, reset_fields=None, clear_fields=None)` — Create a new DB row that shares the same input file(s) as the original.

### Entrée de file (card seule OU lot)

Décide, pour une entrée de file, si elle s'affiche en card unique ou en card MÈRE avec ses filles repliables — et rend l'un ou l'autre. Le bloc vivait recopié À L'IDENTIQUE dans les gabarits d'app (10 au dernier compte — le partial fait foi) ; il n'a pu être centralisé (2026-08-25) qu'une fois deux verrous levés : `is_unitary` adopté (la décision se lit sur le modèle) et `elem` (les cards filles reçoivent leur élément sous le MÊME nom — avant, 8 graphies). Signature à 3 paramètres : `card_template`, plus `collapse_prefix` et `batch_key` pour la seule app à deux files sur une page (enhancer audio). ⚠ Tout le reste TRAVERSE PAR LE CONTEXTE — les ~9 paramètres de `_batch_card.html` sont fournis par l'app et passent au travers, sinon la signature atteindrait la quinzaine. Apparence uniformisée sur le TRANSCRIBER (référence), conforme à `CARD_DESIGN §11.2` (famille de lot = cyan #0dcaf0) : les 3 couleurs et 2 habillages qui coexistaient étaient des séquelles d'implémentations successives. Depuis le 2026-09-15 l'entrée porte `data-card-url` : quand une suppression réduit un lot à une card, `queue-actions.js` la redemande au serveur et la file se met à jour sans rechargement de la page (la vue dit l'état du lot : `batch_common.batch_state` ; la position d'une card seule : `is_batch_child`)

- **Domicile** : `wama/common/templates/common/_queue_entry.html` · **doc** : [docs/construction/ui/CARD_DESIGN.md §11.2](../construction/ui/CARD_DESIGN.md)

### File d'attente (front)

Comportements communs des files : collapse de batch persisté, mode Solitaire (accordéon), toggle Ligne/Mosaïque, les 3 densités et le modificateur PILE (CARD_DESIGN §11.4/§11.9), focus card, clearCards, data-wama-*

- **Domicile** : `wama/common/static/common/js/wama-queue.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Glisser-déposer et sélection multiple de la file

Les QUATRE gestes de manipulation directe, hérités par les 12 apps sans qu'aucune n'écrive une ligne : déposer SUR une card change l'APPARTENANCE (entrer dans un lot / en former un), déposer ENTRE deux cards change l'ORDRE (file ou lot) ; sélection multiple clic/Ctrl/Maj, qui EST celle de l'inspecteur (une seule sélection dans WAMA — la brique ANNONCE `wama:selection-change`, l'inspecteur REND). Auto-monté sur `[data-wama-dnd]`, posé par le templatetag `queue_dnd_attrs` : une app qui ne le pose pas garde une file strictement inerte. SortableJS écarté (multi-sélection + fusion sur une card + règle « pas de CDN »)

- **Domicile** : `wama/common/static/common/js/wama-queue-dnd.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md §3bis](../construction/ui/CARD_DESIGN.md)

### Historique annuler / rétablir

Deux piles + plafond + état des boutons + raccourcis Ctrl+Z / Ctrl+Maj+Z / Ctrl+Y. PORTABLE parce que la machinerie ne touche JAMAIS le modèle : elle ne le connaît que par `snapshot()` et `restore(state)`, que l'appelant fournit. La coalescence des rafales de frappe (`burstWindow`) est une OPTION, pas un acquis — elle n'a aucun sens sur un éditeur non textuel, où chaque mutation est déjà atomique. ⚠⚠ La FILE D'ATTENTE ne peut PAS l'utiliser : ses gestes sont commis côté serveur à l'instant du dépôt, il n'y a pas de modèle client à photographier — son « annuler » est un REJEU D'OPÉRATION INVERSE, même mot, mécanisme différent. Les réunir ici donnerait une API qui MENT sur ce qu'elle garantit. DEUX consommateurs, et deux façons de marquer un cran — c'est l'ADOPTION qui l'a révélé : `push()` AVANT la mutation (transcriber, qui marque en tête de chaque opération) et `commit()` APRÈS (studio, dont les 9 opérations passent par UN entonnoir, `persistDraft`). La v1 n'offrait que `push()` : suffisant pour le consommateur dont elle sortait, insuffisant pour le suivant. `silence(fn)` couvre le chargement programmatique, et la garde de RÉ-ENTRANCE vit dans la brique — restaurer c'est muter (`loadGraph`→`clearCanvas`→`removeNode`→l'entonnoir), donc tout consommateur à entonnoir remplirait son historique de son propre travail

- **Domicile** : `wama/common/static/common/js/wama-history.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Import par lot

Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot

- **Domicile** : `wama/common/utils/batch_parsers.py` · **doc** : [docs/construction/ui/BATCH_FORMAT.md](../construction/ui/BATCH_FORMAT.md)
- **Module** : WAMA Common — Batch file parsers
- **API publique** (17) :
  - `parse_batch_file_from_request(request, parser: Optional[Callable]=None) -> Tuple[List[Dict], List[str]]` — Extract batch_file from request.FILES, validate extension, parse it, clean up.
  - `add_filename_to_items(items: List[Dict]) -> List[Dict]` — Add a 'filename' key to each item dict derived from item['path'].
  - `batch_media_list_preview_response(request, item_enricher: Optional[Callable]=None)` — Standard batch_preview view helper for Type A apps (media_list).
  - `extract_batch_file_text(file_path: str) -> str` — Read and return the raw text from a batch file.
  - `parse_media_list_batch(file_path: str) -> Tuple[List[Dict], List[str]]` — Parse a batch file containing one media path or URL per line.
  - `ligne_est_une_reference(ligne: str) -> bool` — Cette ligne DÉSIGNE-T-ELLE un fichier (URL ou chemin) ? — critère structurel.
  - `parse_composer_batch(file_path: str, default_model: str='musicgen-small', default_duration: float=10.0) -> Tuple[List[Dict], List[str]]` — Parse a Composer batch file (pipe-separated).
  - `parse_pipe_batch(file_path: str, schema: List[Dict]) -> Tuple[List[Dict], List[str]]` — Generic parser for pipe-separated batch files.
  - `parse_unified_batch_line(line: str) -> Optional[Dict]` — Parse une ligne à balises → ``{input, prompt, reference, output, options{}}``.
  - `is_unified_batch_text(text: str) -> bool` — True si le fichier utilise le format à balises (1ʳᵉ ligne utile commence par une balise).
  - `parse_structured_batch_text(text: str) -> Tuple[List[Dict], List[str]]` — Parse un batch STRUCTURÉ (CSV à en-têtes OU balises) → items normalisés.
  - `parse_unified_batch(file_path: str) -> Tuple[List[Dict], List[str]]` — Parse un fichier batch structuré → liste d'items normalisés.
  - `is_csv_header_batch(text: str) -> bool` — True si la 1ʳᵉ ligne utile est un en-tête tableur (délimiteur , ; | ou tab)
  - `parse_csv_header_batch(text: str) -> Tuple[List[Dict], List[str]]` — Parse un tableur à en-têtes (délimiteur sniffé) → items normalisés (clés des balises).
  - `is_structured_batch_text(text: str) -> bool` — True si le texte est un batch structuré (CSV à en-têtes OU balises).
  - `build_batch_template(fields, example, *, app_label='')` — Génère le TEMPLATE batch d'une app depuis sa DÉCLARATION de champs (A5-23).
  - `apply_indexed_output_names(tasks, source_name, default_ext, *, key='output_filename')` — Nomme les sorties manquantes : ``<stem_du_fichier_batch>_<NN>.<ext>``.

### Intégrité des médias

Audit MESURÉ de `media/` en 4 états : RÉFÉRENCÉ (une ligne de base pointe dessus), orphelin, RÉSIDU DE TEST, et RÉFÉRENCÉ MAIS ABSENT — ce dernier étant celui que personne ne voyait : au 2026-08-25, **33 lignes de base pointent vers des fichiers inexistants**, et un téléchargement ou un aperçu y échoue sans rien dire. Signale aussi les fichiers ÉGARÉS hors des emplacements légitimes. ⚠⚠ La méthode exige DEUX signaux indépendants, jamais le nom seul : « orphelin » seul désignait 3447 fichiers sur 3779 (les sorties de workers ne passent pas par un FileField), et le nom seul aurait emporté le dépôt manuel d'une utilisatrice. ⚠ Un kind de manifeste `media` a été ÉCARTÉ : `manifests/` est versionné alors que `media/` porte des données personnelles, et un export serait périmé au moindre dépôt — un contrôle toujours rouge ne protège plus rien

- **Domicile** : `wama/common/management/commands/check_media_integrity.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Audit MESURÉ de `media/` — les fichiers sont-ils à leur place, et rien n'a-t-il survécu ?
- **API publique** (3) :
  - `measure(root: Path) -> dict` — Les comptes de l'audit, sans rien afficher — lus par la commande ET par le contrôle
  - `over_budget(counts: dict) -> list` — Les dépassements de budget, en phrases ; liste vide = dans les clous.
  - `class Command(BaseCommand)`

### Manipulation directe de la file

Endpoints génériques : sortir une card d'un batch, réordonner DANS un lot, ordonner la FILE (`reorder_queue`, 2026-09-04), déplacer, FUSIONNER (`merge`) et consolider. ⚠ `merge` ≠ `consolidate` : le premier fusionne en UN lot et REFUSE si les natures ne cohabitent pas (geste du drag&drop, on a visé une card) ; le second RANGE par nature en N lots (chemin d'import) et 5 apps le redéfinissent. La compatibilité n'est pas redéclarée : `group_key` reçoit la MÊME fonction que le `nature_of` de l'import (vérifié par AST, tests_queue_dnd)

- **Domicile** : `wama/common/utils/queue_manipulation.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §3bis](../construction/ui/CARD_DESIGN.md)
- **Module** : WAMA Common — Manipulation DIRECTE de la file (CARD_DESIGN §3bis) : vues génériques.
- **API publique** (3) :
  - `ids_from_request(request, field: str='ids')` — Identifiants postés — quelle que soit la FORME de la requête.
  - `make_queue_manipulation_views(*, work_model, batch_model, item_model, fk_name, get_user, item_extra=None, batch_extra=None, group_key=None)` — Retourne {'remove_from_batch', 'reorder', 'reorder_queue', 'move_to_batch',
  - `make_queue_manipulation_views_direct(*, work_model, batch_model, batch_fk='batch', row_field='batch_row_index', get_user, batch_extra=None, group_key=None)` — Variante FK-DIRECTE de ``make_queue_manipulation_views`` — pour les apps dont

### Nom du fichier de sortie

Une règle unique pour les 8 apps à liaison PRÉCOCE, en deux familles : entrée FICHIER → `<stem>_<process>_<modèle>[_<i>]<ext>` (l'utilisateur retrouve SON nom, augmenté de ce qu'on lui a fait et avec quoi) ; entrée PROMPT → `<process><id>_<modèle>[_<i>]<ext>` (l'identifiant de card remplace le nom absent et garantit l'unicité dans un `output/` PLAT). Le suffixe `_<i>` n'apparaît QUE si la card produit plusieurs fichiers — cas réel : `imager.num_images` va de 1 à 4. ⚠ Le mot de process est DÉCLARÉ (`APP_CATALOG['output_tag']`), plus écrit en dur dans chaque tâche (`blurred`, `enhanced`, `gen`… étaient invisibles à tout relevé et impossibles à changer sans toucher chaque app). ⚠ `output/` reste PLAT : c'est le NOM qui porte l'unicité, pas un sous-dossier par card — ce dernier est précisément ce qui a été démonté le 2026-08-25 (`job_<id>/`, 1,7 Go)

- **Domicile** : `wama/common/utils/output_naming.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Nom du fichier de SORTIE — une règle unique pour toutes les apps.
- **API publique** (2) :
  - `output_tag(app: str) -> str` — Mot de process de l'app : déclaré dans `APP_CATALOG`, sinon table de repli, sinon l'app.
  - `compose_output_name(*, app: str, model: str='', ext: str='', source_name: str='', item_id=None, index: int=None, total: int=1) -> str` — Compose le nom du fichier de sortie. Rend un NOM, jamais un chemin.

### Notifications de tâche

notify_job() — fin de traitement, succès comme échec

- **Domicile** : `wama/common/utils/notifications.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Notifications utilisateur (email) — brique commune, métadonnée/préférence-driven.
- **API publique** (3) :
  - `notify_emails(recipients, subject, body, html=None)` — Envoie un email à une liste d'ADRESSES (pas forcément des Users) — ex. modérateurs.
  - `notify_user(user, subject, body, html=None)` — Envoie un email à l'utilisateur si une adresse est disponible. Fail-safe (jamais d'exception).
  - `notify_job(user, app_label, item_name, success, detail='', url='')` — Notifie la fin (ou l'échec) d'un traitement, en respectant les préférences du profil.

### Ordre MANUEL de la file

Position de l'entrée de file décidée par l'utilisateur (`QueueOrderMixin.queue_index`, 13 modèles de batch) + 6ᵉ tri « Manuel » — le SEUL tri qui LIT une colonne au lieu de la calculer. `queue_index == 0` = jamais ordonné à la main, et passe EN TÊTE par récence : une file jamais manipulée s'affiche comme en tri `recent`, et un import arrivé après un classement manuel apparaît en haut au lieu de se noyer dans un ordre qu'il n'a pas connu. `reorder_queue` écrit 1..N

- **Domicile** : `wama/common/models.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §3bis](../construction/ui/CARD_DESIGN.md)
- **Module** : Briques de modèles COMMUNES (cf. BATCH_MODEL_AUDIT.md).
- **API publique** (27) :
  - `job_status_values() -> list` — Les VALEURS des cinq états de FILE, dans l'ordre du vocabulaire.
  - `normalize_job_status(value) -> str` — Un état QUELCONQUE (base, JSON, littéral d'app) → le vocabulaire commun.
  - `class ProcessingTimeMixin(models.Model)` — Durée RÉELLE de traitement, en secondes. Le worker la CALCULE déjà (il la passe au learner
  - `class QueueOrderMixin(models.Model)` — Position MANUELLE de l'entrée dans la file (CARD_DESIGN §3bis — manipulation directe).
  - `class BatchMixin` — Sémantique + cycle de fichiers communs aux modèles Batch (tout est batch ; unitaire = card unique).
  - `class OrgUnit(models.Model)` — Unité organisationnelle = nœud de l'arbre institut/université → département →
  - `class Project(models.Model)` — Projet de recherche = groupe de collaboration EXPLICITE qui peut TRAVERSER l'arbre
  - `class ProjectMembership(models.Model)` — Adhésion d'un utilisateur à un projet, avec son rôle et son org (traçabilité
  - `user_projects(user)` — Ids des projets dont l'utilisateur est membre (tous rôles).
  - `user_scope_org_ids(user)` — Ensemble des OrgUnit ids « couvrant » l'utilisateur : ses unités de rattachement
  - `class ElementPreference(models.Model)` — ABONNEMENT d'un utilisateur à un élément de catalogue (app, modèle, fonction, skill…).
  - `class UserAppSetting(models.Model)` — RÉGLAGE GLOBAL d'un utilisateur pour une app — DURABLE (brique `utils/user_settings.py`).
  - `class ScopedVisibility(models.Model)` — Mixin ABSTRAIT : visibilité par scope (privé / PROJET / unité org / public).
  - `scoped_visible_q(user, owner_field='user')` — `Q` filtrant les objets ScopedVisibility visibles pour `user` : les siens + les
  - `class PromptScoped(models.Model)` — Modèle portant un prompt utilisateur TRAITÉ par la PromptPipeline (enrichissement).
  - `class ScopedQuerySet(models.QuerySet)` — QuerySet des modèles `ScopedVisibility` : expose `visible_to(user)`.
  - `class ScopedManager(models.Manager.from_queryset(ScopedQuerySet))` — Manager par défaut des modèles partageables.
  - `class UserFunction(ScopedVisibility)` — Fonction de traitement CRÉÉE PAR UN UTILISATEUR (WAMA Data), stockée en BDD, avec
  - `class Manifest(models.Model)` — Store des MANIFESTES (union discriminée par `manifest_kind`) — cf. WAMA_MANIFEST_SPEC.md.
  - `class Library(models.Model)` — Registre des librairies externes — **NÉ de la projection** du manifeste `library`.
  - `class RunOutcome(models.Model)` — Journal des FAITS observés sur un résultat produit — préalable de toute auto-amélioration
  - `class Embedded(models.Model)` — Socle vectoriel commun au souvenir et au fragment. ABSTRAIT — aucune table.
  - `class MemoryItem(Embedded, ScopedVisibility)` — LE SOUVENIR — un fait, un événement ou une procédure. NON re-dérivable.
  - `class RagChunk(Embedded, ScopedVisibility)` — LE FRAGMENT — un morceau d'un document source. RE-DÉRIVABLE : la source fait foi, donc une
  - `class Conversation(models.Model)` — Un fil de dialogue avec l'assistant, quelle que soit la surface qui le porte.
  - `class ConversationTurn(models.Model)` — Un tour de conversation — ce que l'utilisateur a dit, ou ce que l'assistant a répondu.
  - `class InputProvenance(models.Model)` — D'OÙ vient le fichier d'entrée d'un élément — le LIEN qui manquait.

### Tri/filtrage de la file

Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps

- **Domicile** : `wama/common/utils/queue_view.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)
- **Module** : WAMA — Tri + filtrage COMMUNS de la file unifiée (batches_list).
- **API publique** (1) :
  - `apply_queue_sort_filter(request, batches_list, *, name_of)` — Applique le tri + filtrage de file (persistés en session) et renvoie

### Vues de lot (fabrique commune)

Les six ACTIONS de lot en une fabrique — `make_batch_views` : batch_start, batch_update, batch_delete, batch_duplicate, batch_download, batch_status — paramétrée comme la fabrique de file (les deux formes de rattachement par `batch_elements`/`attach_to_batch`). EXTRAITE le 2026-09-22 des corps conventionnels du générateur d'apps (`views_gen`), qui la consomme ; les apps réelles les écrivaient chacune à la main (60 lectures de lot recopiées, `ROUTE §11 #36`) et la rallient au fil des portages (critère `batch_views_common`)

- **Domicile** : `wama/common/utils/batch_views.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — Les VUES DE LOT : fabrique commune (`make_batch_views`).
- **API publique** (3) :
  - `read_settings_payload(request, schema=None, schema_names=(), empty_is_value=())` — Les RÉGLAGES postés à une vue d'édition — JSON ou formulaire, coercés selon le schéma.
  - `apply_item_settings(item, data, *, params_fields=(), options_field=None, extra_names=())` — Pose sur `item` les réglages présents dans `data` — colonnes déclarées (`params_fields`)
  - `make_batch_views(*, work_model, batch_model, get_user, task=None, file_fields=(), output_fields=(), output_field='output_file', params_fields=(), schema=None,…` — Retourne les six vues de lot : {'batch_start', 'batch_update', 'batch_delete',

## UI générée

### Bouton de cycle

Bouton commun ▶/⏹/↻ toujours vert — l'icône porte l'action, l'état vit sur la card

- **Domicile** : `wama/common/static/common/js/wama-cycle-button.js`

### Cache-busting statique

`{% static_v %}` = `{% static %}` + `?v=<mtime>` : le navigateur re-télécharge un fichier statique dès qu'il change, le garde en cache sinon

- **Domicile** : `wama/common/templatetags/wama_static.py`
- **Module** : Cache-busting statique centralisé pour WAMA.
- **API publique** (1) :
  - `static_v(path)` — URL statique + `?v=<mtime>` pour casser le cache navigateur au changement.

### Card v3

Dimensionnement déclaratif des pistes de card — dépend de l'app, des actions, des libellés (l'autre moitié vécue de la v3 — densités, pile — vit au front de file : queue_front, qui appelle WamaCardV3.measure)

- **Domicile** : `wama/common/static/common/js/wama-card-v3.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md §11](../construction/ui/CARD_DESIGN.md)

### Card « Nouvel élément »

Card d'entrée dépliable commune — les 6 modalités du partial : dépôt, URL, médiathèque, lot, dossier, live + slot de référence typé (extra_zone) — auto-init

- **Domicile** : `wama/common/static/common/js/wama-new-item-card.js` · **doc** : [docs/construction/ui/MODES_QUEUE_UX.md](../construction/ui/MODES_QUEUE_UX.md)

### Chips méta des cards

Chips des cards GÉNÉRÉS du schéma params (chip=True), groupés par section v3 (chips_by_section) ; `values` pour les réglages vivant en JSON (même assiette que card_gear), `extra` pour les chips d'app déjà formés. Porte aussi les réglages COMMUNS aux filles pour la card MÈRE (common_chips_for_items + partial _batch_meta_chips — slot meta_template, généralisation du pilote transcriber, porté aux 10 apps le 31/08) et les propriétés d'ENTRÉE (input_props_for, extraite du pilote reader)

- **Domicile** : `wama/common/utils/card_chips.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §10.3](../construction/ui/CARD_DESIGN.md)
- **Module** : WAMA Common — CHIPS méta des cards (CARD_DESIGN §10.3, pilote Reader 2026-07-06).
- **API publique** (4) :
  - `chips_for(instance, params_json, extra=None, values=None)` — Construit la liste des chips d'une card depuis le schéma sérialisé (schema_to_dicts).
  - `input_props_for(instance, file_field='input_file', name='')` — Sous-ligne « propriétés RÉELLES du média » de la section ENTRÉE (CARD_DESIGN §11).
  - `common_chips_for_items(items, params_json, values_of=None)` — Chips des réglages COMMUNS aux filles d'un lot — pour la card MÈRE (slot
  - `chips_by_section(instance, params_json, extra=None, values=None)` — Mêmes chips que `chips_for`, mais GROUPÉS par section de card v3 (CARD_DESIGN §11).

### data-* du gear ⚙ des cards

data-* du ⚙ DÉRIVÉS du schéma (contrat cardSettings de l'inspecteur, qui lit la RACINE de card PUIS le bouton) — schéma en objets Param OU en dicts (chemin des vues générées) ; booléens 'true'/'false', tous les params item émis (anti-résidus)

- **Domicile** : `wama/common/utils/card_gear.py`
- **Module** : data-* du bouton ⚙ d'une card — GÉNÉRATION COMMUNE dérivée du schéma (extraite 2026-08-18).
- **API publique** (1) :
  - `gear_data(instance, params, values=None, extra=None) -> dict` — dict {nom-a-tirets: valeur aplatie} pour les data-* du bouton ⚙ (voir docstring).

### Domaines → modes

Schéma déclaratif des onglets-domaine et modes par app — scope la file

- **Domicile** : `wama/common/utils/app_modes.py` · **doc** : [docs/construction/ui/MODES_QUEUE_UX.md](../construction/ui/MODES_QUEUE_UX.md)
- **Module** : Schéma déclaratif DOMAINES → MODES des apps — clé de voûte UX (voir MODES_QUEUE_UX.md).
- **API publique** (9) :
  - `get_app_modes(app: str) -> dict` — Schéma {domains:[…]} d'une app, ou {} si non déclaré.
  - `get_domains(app: str) -> list`
  - `has_domain_tabs(app: str) -> bool` — True si l'app a PLUSIEURS domaines (→ afficher des onglets). Sinon : modes directs.
  - `get_domain(app: str, domain_id: str) -> dict`
  - `get_mode(app: str, domain_id: str, mode_id: str) -> dict`
  - `route_prefix(app: str, domain_id: str) -> str` — Préfixe des routes de ce domaine (`audio` → `audio_batch_delete`), '' par défaut.
  - `accepts(app: str, domain_id: str) -> tuple` — Catégories média (MEDIA_CATEGORIES) que ce domaine prend en ENTRÉE.
  - `domain_for_category(app: str, categorie: str) -> str | None` — Domaine d'une app capable d'accueillir cette catégorie média — base du ROUTAGE d'un
  - `resolve_inputs(porteur: dict) -> list` — Détaille les entrées d'un MODE ou d'un DOMAINE (définitions `INPUT_TYPES`).

### Déclaration du volet par la page

Une page DÉCLARE les sections du volet droit qu'elle garde (retrait, jamais ajout) ; sans déclaration, l'état d'avant — les apps n'écrivent rien (context processor volet_defaut)

- **Domicile** : `wama/common/utils/volet.py` · **doc** : [docs/construction/ui/WAMA_VOLETS.md §8](../construction/ui/WAMA_VOLETS.md)
- **Module** : Déclaration du VOLET DROIT par la page — `WAMA_VOLETS.md §8 n°2`.
- **API publique** (1) :
  - `volet(*, tete: bool=False, medias: bool=True, parametres: bool=True, actions: bool=True) -> dict` — Déclaration de volet, toujours COMPLÈTE (cf. le pourquoi dans l'en-tête du module).

### Formats de téléchargement (⬇ late-binding)

Vocabulaire commun des formats choisis AU TÉLÉCHARGEMENT (libellé, icône, groupe) + split-button dérivé de la déclaration export_binding — pendant late-binding d'output_formats ; 6ᵉ action de card. Depuis le 2026-09-18, porte aussi le REGISTRE des builders de rendu (`register_export_builder`, un par app late-binding, chemin pointé résolu à l'usage) : c'est ce qui permet au geste médiathèque de rendre le format choisi par LE MÊME code que le ⬇

- **Domicile** : `wama/common/utils/export_formats.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md §6.3](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : Vocabulaire COMMUN des formats de TÉLÉCHARGEMENT — libellé, icône et regroupement.
- **API publique** (6) :
  - `entry(value: str) -> dict` — Décrit UN format. Un format inconnu du vocabulaire reste affichable (repli neutre) —
  - `entries(formats, available=None) -> list[dict]` — Liste ordonnée d'entrées prêtes pour `common/_download_button.html`.
  - `entries_for_app(app_name: str, available=None) -> list[dict]` — Idem, en lisant la déclaration de l'app — l'appelant n'a que son nom à donner.
  - `is_late_binding(app_name: str) -> bool` — L'app choisit-elle son format AU TÉLÉCHARGEMENT (`export_binding='late'`, §6.4) ?
  - `register_export_builder(app_name: str, builder) -> None` — `builder` : callable `(instance, fmt) -> (ext, bytes) | None`, ou son chemin pointé
  - `export_builder_for(app_name: str)` — Le rendu déclaré par l'app, ou `None`. Une app early-binding n'en déclare pas : son

### Import de dossier récursif

Traversée récursive d'un drop/webkitdirectory — brique F2 montée globale (base.html)

- **Domicile** : `wama/common/static/common/js/wama-folder-import.js` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)

### Inspecteur contextuel (volet droit)

Trois étages (card / lot / file) : sélection → Infos + preview + actions clonées (cloneActions) + PARAMÈTRES reflétés (initFromSchema : panel read/apply dérivés du schéma, cardSettings via card_gear) ; hydrate aussi les previews de card (hydrateCardPreviews)

- **Domicile** : `wama/common/static/common/js/wama-inspector.js` · **doc** : [docs/construction/ui/WAMA_VOLETS.md](../construction/ui/WAMA_VOLETS.md)

### Inspecteur — champs de détail

Schéma canonique des infos d'item affichées au volet droit

- **Domicile** : `wama/common/utils/detail_registry.py` · **doc** : [docs/construction/ui/INSPECTOR_DETAIL_FIELDS.md](../construction/ui/INSPECTOR_DETAIL_FIELDS.md)
- **Module** : WAMA Common — Registre des DÉTAILS d'item pour l'inspecteur (miroir de preview_registry).
- **API publique** (9) :
  - `props_icon_for(media_type: str) -> str`
  - `normalize_status(status: str) -> str` — Un statut d'app → le vocabulaire commun. Délègue au domicile (`common/models.py`).
  - `class DetailRegistry`
  - `register_app_detail(app_name, model_class, adapter)` — Enregistre l'adapter de détail d'une app. `adapter(instance) -> dict canonique`.
  - `register_app_detail_spec(app_name, model_class, spec)` — Variante DÉCLARATIVE (A3a) : la registration est une SPEC-donnée, pas un callable.
  - `detail_from_spec(instance, spec, app_name)` — Adapter GÉNÉRIQUE : résout la spec déclarative contre l'instance puis délègue à
  - `build_detail(instance, *, source_file=None, source_type=None, engine=None, engine_effective=None, result_file=None, result_files=None, result_role=None, result…` — Assemble le dict canonique d'un item (épine dorsale). Les valeurs vides sont OMISES
  - `unified_detail(request, app_name: str, pk: int)` — Endpoint commun : infos d'un item selon le schéma canonique (miroir de unified_preview).
  - `result_tabs_for(app_name: str) -> list` — Facettes TEXTE déclarées par `app_name` — [] si l'app n'en déclare pas.

### Lecteur audio (onde + transport)

Widget autonome : onde canvas (pics serveur ou décodés), play/pause, exclusivité inter-lecteurs et inter-onglets ; monté par la preview dans le volet ET les cards

- **Domicile** : `wama/common/static/common/js/wama-audio-player.js`

### Preview unifiée

Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps ; un MIME `model/…` ouvre la visionneuse 3D commune (`wama-3d-viewer.js`, three vendorisé), chargée À LA DEMANDE par l'importmap — sans importmap, téléchargement (2026-09-13, §17ter trou 2)

- **Domicile** : `wama/common/utils/preview_registry.py`
- **Module** : WAMA Common - Preview Registry
- **API publique** (2) :
  - `class PreviewRegistry` — Central registry for preview adapters.
  - `create_simple_adapter(file_field: str='input_file', duration_field: str=None, width_field: str=None, height_field: str=None, properties_field: str=None)` — Create a simple adapter function for common model patterns.

### Progression & ETA (front)

Moteur ETA par débit observé + barres aux 3 niveaux : card, batch, globale

- **Domicile** : `wama/common/static/common/js/wama-eta.js` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §10](../construction/suivi/PROJECT_STATUS.md)

### Présentation des états

L'APPARENCE d'un état (libellé, classe de badge, classe de texte, icône) déclarée UNE fois et poussée au client (`window.WAMA_STATES`, par le processeur de contexte global — le mécanisme qui sert déjà `WAMA_APP_CATALOG`) : gabarits, maps JS et inspecteur en DÉRIVENT au lieu de la recopier. Mesuré le 2026-09-18 : CINQ écritures du même fait, dont une DANS le commun (le ternaire de `wama-inspector.js`, qui ne connaissait que 4 états sur 7). ⚠ Le VOCABULAIRE (valeurs, libellés, alias) reste au domicile du modèle : ce module l'IMPORTE et n'ajoute que l'UI — la couche modèle n'a pas à connaître `bg-warning`. Les couleurs, elles, restent au CSS

- **Domicile** : `wama/common/utils/state_presentation.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : La PRÉSENTATION d'un état — UNE déclaration, plusieurs consommateurs.
- **API publique** (2) :
  - `states() -> list` — Les états AFFICHABLES, dans l'ordre : `DRAFT` puis les six du vocabulaire commun.
  - `js_payload() -> dict` — Ce que le CLIENT reçoit — même source que les gabarits, donc rien à resynchroniser.

### Schéma de paramètres

Source unique des réglages d'app : volet droit, modales (item ET lot, `context`) et DÉFAUTS APPLICABLES d'un élément naissant (applicable_defaults, filtre show_if au vocabulaire du moteur JS) sont dérivés de lui. Depuis le 01/09 il porte AUSSI LA cascade des valeurs effectives (effective_settings : défauts du schéma ← preset ← réglages POSÉS — formulation Fabien, ROADMAP §23.2bis) : la base ne stocke que le POSÉ (vide = « le preset décide »), les défauts restent au schéma — c'est ce qui rend un preset POSSIBLE, et ce qui a remplacé resolve_options du converter + les défauts en dur des backends

- **Domicile** : `wama/common/utils/param_schema.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Schéma de paramètres WAMA — source unique pour rendre les réglages d'une app dans TOUTES les surfaces (modale item/batch, volet inspecteur card/batch/file) depuis une seule description, au lieu de markup dupliqué par template (cause des divergences).
- **API publique** (16) :
  - `class Param` — Description d'UN paramètre, indépendante de la surface de rendu.
  - `derive_from_model(model_class, include: List[str], overrides: dict=None) -> List[Param]` — Construit la liste de `Param` d'une app à partir des champs d'un modèle Django.
  - `class ParamGroup` — Groupe d'affichage d'une surface de saisie (modale ⚙ / volet) — l'app le déclare,
  - `groups_to_dicts(groups: List[ParamGroup]) -> List[dict]` — Sérialise les groupes pour le front (JSON) / un template.
  - `schema_to_dicts(params: List[Param]) -> List[dict]` — Sérialise un schéma pour le front (JSON) / un template.
  - `applicable_defaults(schema, values=None) -> dict` — Défauts APPLICABLES d'un schéma pour un élément NAISSANT : params de contexte 'item'
  - `effective_settings(schema, posees=None, preset=None, contexte=None) -> dict` — Valeurs EFFECTIVES d'un élément — **défauts (schéma) ← preset ← réglages POSÉS**.
  - `coerce_params(schema, data, caps=None)` — Borne UNIQUE des paramètres numériques = le SCHÉMA (`params.py`). Source de vérité serveur.
  - `schema_for_app(app_id: str) -> List[dict]` — Schéma de params d'une app, résolu depuis le REGISTRE (`wama/<app>/params.py`).
  - `declared_param_schemas(app_id: str)` — TOUS les schémas de params déclarés par le module de l'app — pas seulement l'attribut
  - `schema_model_kwargs(app_id: str, params: dict) -> dict` — Sous-ensemble de `params` qui est À LA FOIS déclaré au schéma de l'app ET un champ
  - `schema_extra_params(app_id: str, params: dict) -> dict` — Symétrique de `schema_model_kwargs` : les params DÉCLARÉS au schéma qui ne sont PAS des
  - `schema_arg_names(app_id: str) -> set` — Noms de params qu'une app DÉCLARE — surface d'arguments acceptable d'un outil `**params`.
  - `invalid_choice_values(schema, data) -> dict` — {nom: (valeurs_refusées, choices_valides_triés)} pour chaque valeur PRÉSENTE hors
  - `schema_choice_values(app_id, name) -> set` — Valeurs valides d'un param à `choices`, DÉRIVÉES du schéma — jamais recopiées.
  - `coerce_schema_values(schema, data, only_present: bool=True) -> dict` — Coercition COMPLÈTE d'un mapping selon le schéma : types (booléens) + bornes (numériques).

### Shuttle J/K/L

État de vitesse/direction de lecture (paliers éditeur) + binding clavier ; l'app fournit apply(speed) — la commande est commune, l'application au lecteur reste locale

- **Domicile** : `wama/common/static/common/js/wama-shuttle.js`

### Signalement au gestionnaire de fichiers

Noms d'événements centralisés (media:uploaded/processed/deleted) — l'arborescence du filemanager se rafraîchit sans que chaque app invente son event

- **Domicile** : `wama/common/static/common/js/wama-fm-notify.js`

### Socle JS des apps

Plomberie commune file/cards : csrfFetch, urls, Poller de progression, états vides

- **Domicile** : `wama/common/static/common/js/wama-app-base.js` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)

### Sélecteur de médiathèque

Modale commune de choix d'un asset de la médiathèque (filtrée par type), rendue à l'appelant sous forme de File + méta

- **Domicile** : `wama/common/static/common/js/media-picker.js`

### Vocabulaire des capacités

Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI

- **Domicile** : `wama/common/utils/model_capabilities.py` · **doc** : [docs/construction/ui/INPUT_MODEL_MATCHING.md](../construction/ui/INPUT_MODEL_MATCHING.md)
- **Module** : Vocabulaire CANONIQUE des capacités modèle (`AIModel.capabilities`) — SOURCE UNIQUE.
- **API publique** (10) :
  - `get_languages(caps: Dict[str, Any]) -> List[str]` — Langues gérées, ou [] si non déclaré (le repli par type est géré par lang_routing).
  - `is_multilingual(caps: Dict[str, Any]) -> bool` — Vrai si le modèle gère >1 langue ou est agnostique ('*'). Remplace l'ex-clé `multilingual`.
  - `languages_count(caps: Dict[str, Any]) -> int` — Nombre de langues déclarées (0 si inconnu). Remplace l'ex-clé `languages_count`.
  - `supports(caps: Dict[str, Any], flag: str) -> bool` — Lecture booléenne tolérante d'un `supports_*` (ex. supports('supports_cloning')).
  - `supports_timestamps_for(caps: Dict[str, Any], lang: str) -> bool` — Horodatage mot disponible POUR CETTE LANGUE.
  - `declared_engine_flag(cls, flag: str)` — Valeur d'un `supports_*` telle que la classe de moteur la DÉCLARE — ou `None`.
  - `apply_engine_flags(caps: Dict[str, Any], cls) -> Dict[str, Any]` — Réaligne `caps` sur ce que la classe de moteur DÉCLARE — rend un NOUVEAU dict.
  - `normalize_capabilities(raw: Dict[str, Any]) -> Dict[str, Any]` — Convertit un dict `capabilities` produit avec des clés legacy vers le vocabulaire canonique.
  - `is_canonical_key(key: str) -> bool` — Vrai si `key` fait partie du vocabulaire canonique (utilitaire d'audit/tests).
  - `derive_inputs_from_tasks(tasks: str, is_video: bool=False) -> Dict[str, Any]` — `tasks` (raccourci d'app) → vocabulaire CANONIQUE : task + entrées consommées.

### Voie d'import (front)

Envoi d'un fichier vers l'endpoint upload de l'app (dépôt, clic — la médiathèque y ARRIVE par la card d'entrée, qui injecte le fichier dans le même input), délégation du LOT à batch_import, consolidation et rafraîchissement — agnostique du monde (ni MIME ni extension)

- **Domicile** : `wama/common/static/common/js/wama-import.js` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)

## Données & infrastructure

### Abonnement aux éléments de catalogue

PRÉFÉRENCE d'affichage, appliquée APRÈS le droit et seulement à l'affichage : elle ne peut que RESTREINDRE ce à quoi l'utilisateur a déjà accès. Seules les EXCEPTIONS sont stockées (se réabonner efface la ligne) ; une nature d'élément s'ajoute par une entrée dans KINDS, et la page de catalogue hérite du mécanisme par deux attributs (`data-abo`, `data-abo-toggle`). Son PÉRIMÈTRE est celui du DROIT, pas d'APP_CATALOG : les surfaces transversales et Lab (extra_links) se masquent par la même clé `gate` que celle dont accessible() décide (§8.8.1)

- **Domicile** : `wama/common/services/subscriptions.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : ABONNEMENT aux éléments de catalogue — la couche PRÉFÉRENCE (PROFILES_PERMISSIONS §8).
- **API publique** (6) :
  - `masques(user, kind)` — Ensemble des `element_id` que l'utilisateur a explicitement masqués pour cette nature.
  - `est_abonne(user, kind, element_id)` — Abonné par DÉFAUT — seule une ligne explicite `subscribed=False` dit le contraire.
  - `filtrer(user, kind, element_ids)` — Sous-liste des éléments auxquels l'utilisateur est abonné (ordre préservé).
  - `definir(user, kind, element_id, abonne)` — Pose ou lève un masquage. Retourne l'état effectif (bool).
  - `definir_lot(user, kind, element_ids, abonne)` — Sélecteur TOUT / RIEN. Retourne le nombre d'éléments effectivement concernés.
  - `resume(user, kind, element_ids)` — `{'total', 'abonnes', 'masques'}` sur un ensemble d'éléments AUTORISÉS — de quoi rendre

### Accès aux éléments (apps aujourd'hui)

Décide seul qui voit quel élément, sur DEUX axes qui se cumulent : le TIER du compte (anonymous < utilisateur < developpeur < admin, tranche en premier) et les RÔLES métier (groupes `role:*`, intersection avec la politique de l'app). Le compte de service `anonymous` y est FERMÉ par code, pas par état de base. Signature GÉNÉRALE depuis S2 — accessible(user, kind, element_id) : chaque FAMILLE d'élément déclare dans KIND_DECISION qui décide pour elle, un kind inconnu LÈVE, et une décision unique ne garde que ce que ses POINTS D'APPLICATION lisent réellement (§8.9)

- **Domicile** : `wama/accounts/permissions.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Modèle d'accès WAMA à DEUX AXES (voir PROFILES_PERMISSIONS.md) : - PROFIL DE COMPTE (tier, unique, hiérarchique) : anonymous < utilisateur < developpeur < admin. - RÔLES MÉTIER (cumulatifs, = Django Groups préfixés 'role:') : communication / recherche / …
- **API publique** (11) :
  - `app_group(app_id)`
  - `app_id_for_path(path)` — app_id gardé correspondant à un chemin de requête, ou None.
  - `tool_accessible(user, tool_name)` — Un user peut-il exécuter cet outil `tool_api` ? MÊME décision que `accessible()` : la
  - `is_developer(user)` — Développeur ou administrateur — DOMICILE UNIQUE du prédicat (2026-09-15).
  - `all_gated_apps()` — Ensemble des app_ids soumis au contrôle d'accès (pour calculer accessible_apps).
  - `tier_rank(tier)`
  - `user_tier(user)`
  - `user_roles(user)` — Ensemble des clés de rôles métier d'un user (depuis ses Groups 'role:*').
  - `accessible(user, kind, element_id)` — Un user peut-il accéder à cet élément ? Point UNIQUE de décision (nav, vues, studio, outils).
  - `accessible_apps(user, app_ids)` — Sous-ensemble d'app_ids accessibles à user (préserve l'ordre).
  - `app_access(app_id)` — Décorateur de vue (défense en profondeur, phase 2) : 403 si l'app n'est pas accessible.

### Accès ffmpeg

Résolution centralisée du binaire et des conversions (échappatoire FFMPEG_BINARY)

- **Domicile** : `wama/common/utils/ffmpeg_utils.py`
- **Module** : Résolution CENTRALISÉE de l'exécutable ffmpeg/ffprobe — brique commune WAMA.
- **API publique** (4) :
  - `is_wsl() -> bool` — True si on tourne sous WSL (Windows Subsystem for Linux).
  - `get_ffmpeg_exe() -> str` — Chemin d'un ffmpeg QUI FONCTIONNE (jamais None).
  - `get_ffprobe_exe() -> str` — Chemin de ffprobe. On le prend de PRÉFÉRENCE à côté du ffmpeg retenu (même install
  - `adapt_path_for_ffmpeg(path: str, ffmpeg_exe: str=None) -> str` — Adapte un chemin pour ffmpeg quand on utilise un ffmpeg WINDOWS (.exe) depuis WSL :

### Accès scopé aux objets

Deux chemins NOMMÉS pour lire un objet partageable depuis une vue (possédé / visible)

- **Domicile** : `wama/common/utils/scoping.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Accès à un objet partageable depuis une vue — DEUX chemins nommés, et deux seulement.
- **API publique** (3) :
  - `visible_or_404(model, user, **kwargs)` — Objet que `user` a le droit de VOIR : le sien, ou partagé avec lui (unité/projet/public).
  - `listable_by(queryset, user)` — Ce que `user` a le droit de LISTER : `visible_to`, sauf pour le compte de service anonyme.
  - `owned_or_404(model, user, **kwargs)` — Objet que `user` a le droit de MODIFIER — aujourd'hui : le sien, point.

### Actualisation des catalogues

REGISTRE des registres : une page catalogue déclare la CLÉ de son registre et hérite du bouton, de l'endpoint, de la permission et du compte-rendu. La NATURE déclarée (scan / mesure / re-déclaration / DÉRIVÉ) décide du rendu — un dérivé affiche « toujours à jour » au lieu d'un bouton qui ne ferait rien — ET le LIEU d'exécution : état partagé → tâche Celery non bloquante, registre en mémoire → sur place, avec propagation aux autres workers gunicorn

- **Domicile** : `wama/common/registries.py`
- **Module** : Registre des REGISTRES — l'actualisation devient un mécanisme, pas une page.
- **API publique** (13) :
  - `class RefreshResult` — Compte-rendu UNIFORME d'une actualisation, quelle que soit sa nature.
  - `class Registry` — Ce qu'une page catalogue déclare pour hériter de l'actualisation.
  - `execution_of(r: Registry) -> str`
  - `register(r: Registry) -> Registry`
  - `get(key: str) -> Registry`
  - `is_authorized(r: Registry, user) -> bool`
  - `mark_refreshed(key: str) -> None` — Signale aux AUTRES processus qu'ils sont périmés.
  - `synchronize(key: str) -> bool` — Recharge SI un autre processus a actualisé depuis notre dernier passage. Rend True s'il a
  - `refresh(key: str, *, user=None) -> RefreshResult` — Exécute l'actualisation ICI, en synchrone. Chronomètre et uniformise le compte-rendu.
  - `launch(key: str, *, user=None) -> dict` — LE point d'entrée des vues. Décide où l'actualisation tourne et rend une réponse immédiate.
  - `task_state(task_id: str) -> dict` — État d'une actualisation lancée en Celery — de quoi faire patienter l'utilisateur.
  - `overview(with_coverage: bool=False) -> List[dict]` — Photo de tous les registres, pour l'UI et pour la documentation générée.
  - `run_startup() -> Dict[str, RefreshResult]` — Passe les registres marqués `on_startup`. Appelé une fois par processus.

### Arbre organisationnel depuis l'annuaire

ou=structures (SUPANN) → OrgUnit + parents ; peuple ce dont dépend le partage par unité (RAG labo, médiathèque). Lecture seule côté LDAP, idempotente

- **Domicile** : `wama/accounts/management/commands/sync_org_units.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Synchronise l'arbre `OrgUnit` depuis l'annuaire SUPANN (`ou=structures`).
- **API publique** (2) :
  - `deviner_type(type_supann: str, code: str) -> str` — Type d'unité, best-effort. Le TYPE est cosmétique ; ne jamais bloquer une synchro dessus.
  - `class Command(BaseCommand)`

### Bascules de fonctionnalités

Registre de Feature par app + surcharges JSON de l'objet porteur — comparer AVEC/SANS

- **Domicile** : `wama/common/utils/feature_flags.py`
- **Module** : Bascules de fonctionnalités (feature flags) portées par un objet-config — mécanisme GÉNÉRIQUE.
- **API publique** (5) :
  - `class Feature`
  - `resolve(registry, config)` — État effectif {key: bool} : défauts du registre surchargés par config['features'].
  - `is_enabled(registry, config, key)` — État effectif d'UNE bascule (KeyError si la clé n'est pas au registre).
  - `describe(registry, config=None)` — Catalogue sérialisable pour l'UI : métadonnées + état effectif de chaque bascule.
  - `sanitize_overrides(registry, raw)` — Filtre un dict de surcharges venu du client : clés connues, valeurs booléennes.

### Chemins média

Emplacements canoniques des entrées/sorties par app et par utilisateur

- **Domicile** : `wama/common/utils/media_paths.py`
- **Module** : WAMA Common - Media Path Utilities
- **API publique** (15) :
  - `get_app_media_path(app_name: str, user_id: Union[int, str], subfolder: str='input') -> Path` — Get the absolute path for an app's user-specific media folder.
  - `class OutsideMediaRoot(ValueError)` — Le chemin demandé sort de MEDIA_ROOT (traversée `..`, dossier frère, absolu étranger).
  - `resolve_under_media_root(candidate, *, must_exist: bool=True)` — Résout un chemin — absolu, ou RELATIF à MEDIA_ROOT — et GARANTIT qu'il y reste.
  - `get_app_media_url(app_name: str, user_id: Union[int, str], subfolder: str='input') -> str` — Get the URL path for an app's user-specific media folder.
  - `ensure_app_media_dirs(app_name: str, user_id: Union[int, str]) -> dict` — Ensure input and output directories exist for an app/user.
  - `get_unique_filename(folder: Union[str, Path], filename: str) -> str` — Generate a unique filename in a folder.
  - `app_media_dir(app_name: str, user_id: Union[int, str], subfolder: str='input') -> str` — Dossier média d'une app, RELATIF à `MEDIA_ROOT` — la FORME du chemin, en un seul endroit.
  - `get_relative_media_path(app_name: str, user_id: Union[int, str], subfolder: str, filename: str) -> str` — Get the relative path for storing in Django FileField.
  - `copy_into_app_input(source_path, app_name: str, user_id, subfolder: str='input', allowed_exts=None, *, for_instance=None, field=None, provenance_kind='temp', p…` — Copy a source file into an app's media folder with collision-safe naming.
  - `class UploadToUserPath` — Callable class for Django FileField upload_to that generates user-specific paths.
  - `system_asset_relpath(asset_type: str, filename: str) -> str` — Chemin relatif (sous `MEDIA_ROOT`) d'un asset système : un sous-dossier par NATURE.
  - `class UploadToSystemAssetPath` — `upload_to` de `SystemAsset.file` — `media_library/system/<asset_type>/<fichier>`.
  - `upload_to_user_input(app_name: str)` — Convenience function to create an UploadToUserPath for input folder.
  - `upload_to_user_output(app_name: str)` — Convenience function to create an UploadToUserPath for output folder.
  - `migrate_file_to_user_path(old_path: Union[str, Path], app_name: str, user_id: Union[int, str], subfolder: str='input', move: bool=True) -> Optional[str]` — Migrate a file from old location to new user-specific location.

### Décodage audio robuste

Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg. Annexe torchaudio_compat = l'autre forme du même problème : shims soundfile posés DANS torchaudio pour les libs tierces qui l'appellent en interne (Coqui, DeepFilterNet)

- **Domicile** : `wama/common/utils/audio_decode.py`
- **Module** : Décodage audio robuste pour WAMA (WSL où torchcodec/torchaudio est cassé).
- **API publique** (4) :
  - `decode_audio(path, target_sr: int=16000, mono: bool=True)` — Décode un fichier audio en (ndarray float32, sample_rate), robuste aux formats
  - `probe_duration_seconds(path)` — Durée d'un média en secondes via ffprobe — SANS décoder (coût négligeable).
  - `decode_window(path, target_sr: int=16000, start_s: float=0.0, duration_s=None, mono: bool=True)` — Décode UNE FENÊTRE [start_s, start_s+duration_s] d'un média en (ndarray float32, sr),
  - `decode_for_pyannote(path, target_sr: int=16000)` — Décode en dict `{'waveform': (channels, time) torch.Tensor, 'sample_rate': int}`

### Importer universel (WAMA Data)

REGISTRE de capacités de lecture — aucun format privilégié : ajouter un format = déposer un lecteur, jamais éditer le moteur. Porte aussi l'HORODATAGE par flux (dont le ré-horodatage par fréquence théorique, qui n'interpole rien et ne s'applique que sur demande). ⚠ La MÉCANIQUE SQLite (ouverture en lecture seule, décodage UTF-8→cp1252 du texte des bases MATLAB, valeurs triées, les trois niveaux d'agrégation) est un socle partagé — un lecteur de base concret n'écrit plus que `can_read`, `probe` et `read`, c'est-à-dire sa seule connaissance du schéma

- **Domicile** : `wama_data/sources/__init__.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §6.6, §9terdecies](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : Importer UNIVERSEL de WAMA Data — un registre de capacités de lecture, pas un lecteur.
- **API publique** (13) :
  - `class Timestamper` — Décide l'instant d'un échantillon. Une instance par FLUX, choisie à l'import.
  - `class TimestampTS(Timestamper)` — L'horodatage porté par la donnée. Repli sur l'heure d'émission s'il manque.
  - `class TimeOfIssueTS(Timestamper)` — L'heure d'émission du système d'acquisition, quoi qu'il arrive.
  - `class ResamplingTS(Timestamper)` — RÉ-HORODATAGE : `origine + idx / fréquence`.
  - `class StreamSpec` — Un flux tel qu'un lecteur le rend. Indépendant du format d'origine.
  - `class SourceInfo` — Ce qu'on sait d'une source AVANT de la lire — pour proposer un import sans l'exécuter.
  - `class SourceReader` — Capacité d'import d'un format. À sous-classer, puis à enregistrer via `register_reader`.
  - `register_reader(reader: SourceReader) -> SourceReader`
  - `reader_for(path) -> Optional[SourceReader]` — Le lecteur capable de lire ce chemin, ou None. Premier enregistré qui accepte.
  - `supported_extensions() -> List[str]`
  - `probe(path) -> SourceInfo` — Inventaire d'une source, quel que soit son format.
  - `load(path, streams=None, timestampers=None, name: str='') -> TemporalReferential` — Lit une source et rend un référentiel temporel prêt à interroger.
  - `reader_modules() -> List[str]` — Modules de lecture du paquet — **DÉCOUVERTS, jamais cités**.

### Médias de test isolés

Le runner de tests redirige `MEDIA_ROOT` vers `media_tests/run-<id>/` — dossier SŒUR de `media/`, jamais dedans (servi, sauvegardé, miré) ; les exécutions orphelines (vides ou > 24 h, teardown jamais joué) se balaient à l'entrée de la suivante. Le nocturne, lui, écrit chez les COMPTES DE TEST dans `media/` (serveur vivant) et se balaie par NOM (`wama_temoin_*`, dossier temporaire compris). Question Fabien 2026-09-13 : « on ne change rien pour ça »

- **Domicile** : `wama/common/runners.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §①bis](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Runner de tests WAMA — isole le média des tests du média de PRODUCTION.
- **API publique** (2) :
  - `class WamaTestRunner(DiscoverRunner)` — `DiscoverRunner` + `MEDIA_ROOT` redirigé vers un dossier jetable.
  - `balayer_runs_orphelins(racine: Path, maintenant: float | None=None) -> int` — Retire de `media_tests/` les exécutions ORPHELINES : dossiers `run-*` vides, ou plus

### Natures d'assets de la médiathèque (A′)

UNE déclaration par nature (`ASSET_NATURES` : libellé, catégorie ∈ MEDIA_CATEGORIES, extensions, icône, pivot, schéma d'attributs, `data_type` inter-mondes) dont `ASSET_TYPES`/`ALLOWED_EXTENSIONS`/`ASSET_TYPE_CATEGORY`/`TYPE_GROUPS` et les trois tables JS de la page DÉRIVENT ; `attributes` JSON sur SystemAsset/UserAsset normalisé au `save()` (alias de catégorie REFUSÉ, `resolve_asset_type` pour les puits qui ne disent qu'une catégorie) ; UNE porte de compatibilité `asset_accepts` à trois états. Précédent copié : `AIModel.capabilities` + CANONICAL_CAPABILITIES. Décision Fabien 2026-09-13 — ni colonnes ni table par nature, ni `tags`

- **Domicile** : `wama/media_library/natures.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §9](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Vocabulaire des NATURES d'assets de la médiathèque — module PUR (importable sans Django).
- **API publique** (10) :
  - `class Attr` — Un attribut déclaré d'une nature : son TYPE (pour la coercition), sa description (doc
  - `class Nature` — Ce qu'une nature d'asset DÉCLARE. Tout consommateur en dérive, aucun ne la recopie.
  - `resolve_asset_type(value: str, filename: str='') -> str` — La NATURE que désigne `value` : une nature telle quelle ; une catégorie → sa nature par
  - `nature_of(asset_type: str) -> Nature` — La nature d'un `asset_type`, ou `KeyError` : une valeur hors vocabulaire n'est pas un
  - `attribute_schema(asset_type: str) -> Dict[str, Dict[str, Any]]` — Le schéma d'attributs d'une nature, sérialisable — c'est ce depuis quoi un formulaire
  - `is_canonical_attribute(asset_type: str, key: str) -> bool` — Audit : `key` est-il déclaré pour cette nature ? (jumeau d'`is_canonical_key`).
  - `natures_as_json() -> Dict[str, Dict[str, Any]]` — La déclaration entière, sérialisable pour la page médiathèque : icône, formats admis,
  - `normalize_attributes(asset_type: str, attrs: Dict[str, Any] | None) -> Dict[str, Any]` — Rend un NOUVEAU dict, coercé sur la déclaration de la nature.
  - `class AssetSpec` — Ce qu'un CONSOMMATEUR déclare accepter — un nœud studio, un moteur, un slot d'app.
  - `asset_accepts(spec: AssetSpec, asset_type: str, attributes: Dict[str, Any] | None) -> Tuple[str, str]` — Rend `(état, raison)` — la raison NOMME ce qui manque, pour être affichée telle quelle.

### Noms dérivés (WAMA Data)

DOMICILE UNIQUE de la règle « le nom se DÉRIVE des paramètres, il ne se saisit pas » : deux productions de mêmes réglages portent le même nom, deux réglages différents ne peuvent pas le partager. Elle était appliquée par QUATRE règles dans TROIS lieux — dont une f-string écrite en dur — avant l'audit du 23/08. Les anciens emplacements réexportent ; un test vérifie l'IDENTITÉ des fonctions, donc une redéfinition locale même à l'identique échoue. Sans dépendance, par nécessité : c'est ce qui permet à `conditions.py` de l'importer sans cycle

- **Domicile** : `wama_data/core/naming.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §9ter.6 B7, §9sexies.4](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : NOMS DÉRIVÉS — la seule brique qui décide comment une production se nomme.
- **API publique** (6) :
  - `abbreviate(name: str) -> str` — Préfixe minuscule d'un nom de table — `debut_bloc` → `deb`.
  - `as_int(x: float) -> str` — `0` plutôt que `0.0`, `-2.5` conservé — un nom ne porte pas de décimale inutile.
  - `normalize(text: str) -> str` — Texte quelconque → fragment de nom : minuscules, alphanumérique, `_` unique, sans bords.
  - `derived_name(column: str, suffixe: str) -> str` — Colonne dérivée — `vitesse` + `moyenne` → `vitesse_moyenne`.
  - `join_name(table_debut: str, table_fin: str, offset_start: float, offset_end: float) -> str` — Segmentation temporelle double — `deb_fin_0_0`, la graphie de l'outil d'origine.
  - `annex_name(stream: str, fonction: str) -> str` — Table ANNEXE née d'un calcul qui change la clé temporelle — `vitesse_calcul_par_segment`.

### Pont référentiel ↔ cadres typés (WAMA Data)

SEULE frontière entre les deux vocabulaires du monde Data : le référentiel (paresseux, indexé, sans pandas) et le `TypedFrame` que mangent toutes les fonctions du catalogue. Sans lui le référentiel n'avait AUCUN consommateur — non parce qu'on ne s'en servait pas, mais parce qu'on ne POUVAIT pas. Traite quatre pièges mesurés : le temps de SESSION (± offset) vs le temps local du flux, la colonne temporelle brute PÉRIMÉE après ré-horodatage, le contrat `rows` réel mais non déclaré, et la PROVENANCE — ce qui revient d'un calcul ne peut pas se déclarer acquis (`is_base=False` sans échappatoire)

- **Domicile** : `wama_data/frames.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §9quater.7](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : LE PONT — `Signal` / `TemporalReferential` ↔ `TypedFrame`.
- **API publique** (5) :
  - `default_type(signal: Signal) -> str` — Type de cadre : la FAMILLE DÉCLARÉE d'abord, la structure en repli.
  - `frame_from_signal(signal: Signal, *, t0: Optional[float]=None, t1: Optional[float]=None, offset: float=0.0, data_type: Optional[str]=None, champs: Optional[Ite…` — Une FENÊTRE d'un flux, en cadre typé prêt pour le catalogue.
  - `frame_from_referential(ref: TemporalReferential, name: str, *, t0: Optional[float]=None, t1: Optional[float]=None, data_type: Optional[str]=None, champs: Optio…` — Une fenêtre d'un flux du référentiel, **en temps de session** (piège ①).
  - `signal_from_frame(frame: TypedFrame, name: str, *, fs: Optional[float]=None, units: Optional[Mapping[str, str]]=None, comments: str='') -> Signal` — Un cadre typé redevient un flux — **toujours DÉRIVÉ, jamais acquis** (piège ④).
  - `adjoin(ref: TemporalReferential, name: str, frame: TypedFrame, *, offset: float=0.0, **kwargs) -> Signal` — Ajoute au référentiel un flux issu d'un calcul, et le rend.

### Référentiel temporel (WAMA Data)

Aligne des flux à cadences INCOMMENSURABLES et répond aux questions temporelles : quel échantillon à t, quels segments le contiennent, quel événement suit, et la vue DÉCIMÉE (min/max par tranche) sans laquelle aucun tracé n'est viable. N'interpole jamais : la valeur rendue est toujours un échantillon existant

- **Domicile** : `wama_data/core/temporal.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §2-§3](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : Référentiel temporel de WAMA Data — la couche qui répond « que vaut ce signal à l'instant t ».
- **API publique** (3) :
  - `class SignalMeta` — Ce qu'on DÉCLARE d'un flux — l'équivalent des `MetaDatas`/`MetaDataVariables` d'un `.trip`.
  - `class Signal` — Un flux temporel : des instants triés + un accès aux valeurs.
  - `class TemporalReferential` — L'ensemble des flux d'une session, alignés sur une même origine.

### Réglages utilisateur par app

Persistance cache user_{id}_{app}_{clé} avec défauts déclarés par l'app

- **Domicile** : `wama/common/utils/user_settings.py`
- **Module** : WAMA Common — Réglages UTILISATEUR par app, DURABLES en base (cache en lecture devant).
- **API publique** (3) :
  - `get_user_app_settings(user, app, defaults)` — Retourne le dict complet des réglages de ``user`` pour ``app``.
  - `get_user_app_setting(user, app, name, default=None)` — Lecture d'UN réglage.
  - `save_user_app_settings(user, app, values, *, timeout=DEFAULT_TIMEOUT)` — Persiste chaque réglage fourni (en base, et en cache pour la lecture).

### Rétention des médias

Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts)

- **Domicile** : `wama/common/services/retention.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Rétention des médias — purge automatique des sorties au-delà de la durée choisie par l'utilisateur (`UserProfile.media_retention_days`, bornée par `settings.WAMA_MAX_RETENTION_DAYS`).
- **API publique** (2) :
  - `purge_expired_media(dry_run=False)` — Purge les médias expirés de tous les modèles enregistrés, par utilisateur (selon sa rétention).
  - `upcoming_expirations(days_ahead)` — {user_id: [(model_label, count), ...]} des médias expirant dans <= days_ahead jours.

### Sauvegarde & tirage

Moteur unique de miroir (modèles, base, médias, secrets) et restauration

- **Domicile** : `wama/common/services/mirror_sync.py`
- **Module** : Miroir incrémental d'une arborescence locale vers un espace distant — brique COMMUNE.
- **API publique** (7) :
  - `resolve_remote_root(subdir: str, env_var: str | None=None) -> str` — Chemin de l'espace distant pour un domaine (`MODELS`, `DB`, `MEDIAS`…).
  - `remote_is_available(remote_path) -> bool` — L'espace distant est-il utilisable EN ÉCRITURE, sans effet de bord ?
  - `copy_file(source: Path, dest: Path) -> tuple[bool, float, str | None]` — PRIMITIVE DE COPIE UNIQUE du projet : crée les dossiers parents et copie.
  - `new_summary(remote_path) -> dict` — Squelette de compte rendu, partagé par les appelants pour publier un état initial
  - `mirror_tree(source_root, dest_root, *, overwrite: bool=False, exclude=None, dry_run: bool=False, progress_cb=None, on_file=None, progress_every: int=PROGRESS_E…` — Réplique `source_root` vers `dest_root` en conservant l'arborescence relative.
  - `purge_keep_latest(directory, pattern: str, keep: int) -> list[str]` — Ne conserve que les `keep` fichiers les plus récents de `directory` correspondant à
  - `run_mirror_job(runner, *, cache_key, task_id, label, ttl=24 * 3600)` — Exécute un miroir en publiant son avancement dans le cache — enveloppe COMMUNE aux

### Sonde média

Durée/codec/dimensions/pages d'un média pour les propriétés de card (via ffmpeg_utils) ; depuis le 2026-09-13, un OBJET 3D livre sa table des matières glTF sans décodage (`probe_object3d` : format, faces, rig, animations) sous la clé `attributes` — ce que la médiathèque pose à l'ingest sur la nature `object3d` (A′)

- **Domicile** : `wama/common/utils/media_probe.py` · **doc** : [docs/construction/suivi/ROADMAP.md §17ter](../construction/suivi/ROADMAP.md)
- **Module** : WAMA Common — Sonde média (durée / codec / dimensions / pages / entrées).
- **API publique** (6) :
  - `format_duration(seconds: float) -> str` — ``95.4 -> '1:35'`` — affichage court pour les cards ('' si inconnu/zéro).
  - `probe_audio(path: str) -> dict` — Sonde le premier flux audio d'un fichier.
  - `probe_video(path: str) -> dict` — Sonde le premier flux vidéo : codec • L×H • fps, + durée (stream puis format).
  - `probe_object3d(path: str) -> dict` — Sonde d'un OBJET 3D (ROADMAP §17ter, trou 2) — ce que le fichier DÉCLARE, sans le décoder.
  - `probe_media(path: str) -> dict` — Sonde générique TOUS types (dispatch par extension).
  - `probe_media_cached(path: str, ttl: int=86400) -> dict` — `probe_media` avec cache Django par (chemin, mtime) — pour les endpoints à la requête

### Sources externes

Registre DÉCLARATIF de ce que WAMA joint au dehors : adresse, réglage qui la surcharge, variable portant la clé d'API, attribution exigée par la licence, et surtout la PORTÉE (service local ou Internet) — d'où le traitement du proxy est DÉRIVÉ au lieu d'être choisi à la main par chaque appelant. Ajouter une plateforme = une entrée. ⚠ Ne déclare JAMAIS le client : chaque source a sa forme (JSON authentifié, parquet, HTML scrapé), le parseur reste chez le consommateur. La CLÉ peut être celle de l'instance (`api_key_env`) ou celle de CHACUN, posée au profil (`user_key`) : depuis le 2026-09-22 (décision de Fabien) les connecteurs de la médiathèque y sont déclarés (famille `media`) — adresse, proxy et sonde d'ici, clé de chaque utilisateur

- **Domicile** : `wama/common/external_sources.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md](../construction/suivi/PROJECT_STATUS.md)
- **Module** : external_sources — registre DÉCLARATIF des sources externes joignables par WAMA.
- **API publique** (13) :
  - `class ExternalSource` — Une source externe : ce qu'elle est et comment on l'adresse — jamais comment on la lit.
  - `by_key() -> dict[str, ExternalSource]`
  - `llm_engine_inventory() -> dict` — {moteur: porteur} des fournisseurs LLM distants — un par source `llm` (2026-09-15).
  - `get(key: str) -> ExternalSource` — La source déclarée. `KeyError` explicite : une clé inconnue est un défaut de code.
  - `base_url(key: str) -> str` — Adresse EFFECTIVE : réglage Django, puis variable d'environnement, puis défaut déclaré.
  - `proxies_for(key: str)` — `proxies` à passer à `requests`, choisis d'après la PORTÉE déclarée.
  - `api_key(key: str) -> str` — Clé d'API lue dans l'environnement, ou '' — jamais une exception : une source sans clé
  - `is_configured(key: str) -> bool` — La source est-elle utilisable en l'état ? (clé posée si elle en exige une)
  - `attributions() -> tuple[str, ...]` — Attributions exigées par les licences des sources qui en portent une.
  - `probe(key: str, timeout: float=PROBE_TIMEOUT_S) -> dict` — Sonde UNE source : clé posée ? adresse joignable ? en combien de temps ?
  - `report_path()`
  - `probe_all(write: bool=False) -> dict` — Sonde TOUTES les sources déclarées, et écrit le rapport si demandé.
  - `last_report() -> dict | None` — Le dernier rapport ÉCRIT, ou None — la page l'affiche sans jamais sonder elle-même.

### Taxonomie des natures & vocabulaire d'entrée

Source UNIQUE des natures de média (image/video/audio/document/archive/dataset/3d — `text` RETIRÉ le 2026-08-30, arbitrage §S2bis.6bis : les fichiers texte sont des documents, la saisie est le jeton de RÔLE `prompt`) : détecte la nature d'un nom de fichier (`category_of_path`, défaut 'document') et normalise un vocabulaire (`normalize_types`) ; un MONDE pousse ses extensions par `register_category_extensions` (dataset ← sonde wama_data), jamais en dur. Porte AUSSI la déclaration par app de ce qu'elle accepte — `input_types` (les natures) et `input_extensions` (les extensions) — d'où le manifeste tire `body.ports.inputs[].types` et `body.identity.input_extensions`, l'axe UX ses `accepts` de domaine, le gabarit généré son `accept=` de dropzone, et la vue générée sa dérivation de nature CONTRAINTE au vocabulaire déclaré

- **Domicile** : `wama/common/app_registry.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — Application Registry
- **API publique** (15) :
  - `register_category_extensions(category, extensions)` — Un MONDE déclare les extensions qu'il POSSÈDE pour une nature de `MEDIA_CATEGORIES`.
  - `media_extensions() -> dict` — Les extensions reconnues, PAR NATURE — `{nature: [ext…]}`, sans le point.
  - `category_of_path(path)` — Catégorie média ('image'|'video'|'audio'|'document'|'archive'|'dataset'|'3d') d'un chemin
  - `normalize_types(types)` — ['wav','image','srt'] → ['audio','image','document'] (catégories média + jetons de rôle,
  - `known_port_types()` — Vocabulaire ADMIS pour le type d'un port — natures média + jetons de rôle + types de DONNÉE.
  - `app_capabilities(app_id)` — Capacités déclarées d'une app = les drapeaux `conventions` d'APP_CATALOG, retournés à plat.
  - `app_supports_during_preview(app_id)` — True si l'app déclare la capacité de preview « pendant » (progressive/temporaire pendant le
  - `studio_node_ports(app_id)` — Dérive les PORTS d'un nœud studio pour une app, métadonnée-driven :
  - `app_input_ports(app_id, domain=None)` — Ports d'entrée d'une app DÉRIVÉS DES CAPACITÉS DE SES MODÈLES — l'auto-adaptation.
  - `derive_category(entry) -> str` — Catégorie DÉRIVÉE des types déclarés — la déclaration explicite prime, la dérivation
  - `get_apps_by_category()` — Catalogue groupé, ordonné par APP_CATEGORIES[order] — source des surfaces groupées
  - `get_app_extensions_for_filemanager() -> dict` — Returns a dict suitable for FileManager JS APP_EXTENSIONS:
  - `category_color(cid: str) -> str` — Couleur de RÉFÉRENCE d'une catégorie (en-têtes de section, dossiers…).
  - `measure_and_write_conformity() -> dict` — Mesure les 10 apps (conformity_checker.run_checks) et ÉCRIT le rapport JSON.
  - `get_conformity_summary() -> dict` — Returns per-app conformity score:

### Taxonomie des types de donnée

Vocabulaire commun des sources et des fonctions : sous-typage + compatibilité de ports. `segments` y est LE type « portion de temps bornée » (situation, état, section)

- **Domicile** : `wama/common/catalog/data_types.py` · **doc** : [docs/construction/mondes/WAMA_DATA_FUNCTION_CARDS.md §3](../construction/mondes/WAMA_DATA_FUNCTION_CARDS.md)
- **Module** : Taxonomie des TYPES DE DONNÉE de WAMA Data (pendant de `MEDIA_CATEGORIES` côté média).
- **API publique** (6) :
  - `class DataType` — Constantes de type de donnée (valeurs stables, utilisées dans les PortSpec).
  - `known_types() -> set` — Les valeurs de `DataType` — le vocabulaire des types de DONNÉE, en un seul endroit.
  - `normalize_type(data_type)` — Ramène une valeur éventuellement héritée au vocabulaire courant. Idempotent.
  - `ancestors(data_type)` — Ensemble des super-types (transitif), y compris le type lui-même.
  - `is_compatible(produced, expected)` — Une sortie de type `produced` peut alimenter une entrée attendant `expected`
  - `class TypedFrame` — Une donnée typée = un `pandas.DataFrame` + son `data_type` + méta optionnelles.

### Unités d'affichage

Moteur UNIQUE de conversion d'unités pour la PRÉSENTATION (pint) : la donnée reste dans SON unité (`WamaVariables.unit`, `ParamSpec.unit`), la préférence utilisateur (métrique/impérial) ne convertit qu'à l'écran — résolution par DIMENSION, une unité inconnue reste affichable — et un export qui convertit doit le DIRE. Un trou de donnée traverse en trou (None), jamais en valeur

- **Domicile** : `wama/common/utils/units.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §10 D27](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : Unit display conversion — the single engine behind D27 (`WAMA_DATA_WORLD.md §10`).
- **API publique** (5) :
  - `registry()` — The process-wide pint registry — built once (instantiation costs ~100 ms).
  - `convert(value: Any, source: str, target: str) -> Optional[float]` — One value from `source` to `target` unit — offset units (°C → °F) included.
  - `convert_series(values: Sequence[Any], source: str, target: str) -> List[Optional[float]]` — A whole column, hole-preserving. The presentation layer decimates before converting.
  - `display_unit(source: str, system: str='metric') -> str` — The unit to DISPLAY a value in, given the user's preferred unit system.
  - `render(value: Any, source: str, system: str='metric', precision: int=4) -> str` — Presentation string in the preferred system — `render(30, 'km/h', 'imperial')` → '18.64 mph'.

### Utilitaires vidéo

Extraction audio des vidéos + téléchargement YouTube/yt-dlp

- **Domicile** : `wama/common/utils/video_utils.py`
- **Module** : WAMA Common - Video & YouTube Utilities Extraction audio depuis vidéos et téléchargement YouTube
- **API publique** (10) :
  - `get_ffprobe_path()` — DÉLÈGUE à la brique ffmpeg_utils (cf. _get_ffmpeg_path).
  - `get_media_info(file_path: str) -> dict` — Extract metadata from an image or video file.
  - `upload_media_from_url(url, output_path)` — Download a media file from a URL using yt_dlp (with robust options) or direct HTTP.
  - `extract_audio_from_video(video_path: str, output_audio_path: Optional[str]=None) -> str` — Extrait l'audio d'un fichier vidéo.
  - `download_youtube_audio(youtube_url: str, output_dir: str) -> Tuple[str, str]` — Télécharge l'audio d'une vidéo YouTube.
  - `is_video_file(filename: str) -> bool` — Vérifie si un fichier est une vidéo basé sur son extension.
  - `is_audio_file(filename: str) -> bool` — Vérifie si un fichier est un audio basé sur son extension.
  - `is_image_file(filename: str) -> bool` — Vérifie si un fichier est une image basé sur son extension.
  - `convert_video_to_web_compatible(input_path: str, output_path: Optional[str]=None) -> str` — Convertit une vidéo en format compatible web (H.264/AAC dans conteneur MP4).
  - `copy_audio_to_video(input_video_path, temp_video_path, output_path) -> bool` — Recolle la piste audio d'une vidéo SOURCE sur une vidéo TRAITÉE (sans audio).

### View-model d'exploration (WAMA Data)

Une VUE déclare ce qu'on regarde — flux, fenêtre, résolution, colonnes dérivées — et rien de plus : sérialisable en JSON, donc rejouable et diffable, et on persiste ELLE plutôt que les valeurs (une colonne matérialisée se périme sans le dire). Rend EXÉCUTABLE la règle « une nouvelle table SSI la clé temporelle change » en la DÉRIVANT de la `FunctionCategory` : ajouter une fonction au catalogue la range du bon côté sans toucher le view-model. La séparation tables/annexes rend la règle visible à l'écran au lieu d'avoir à l'expliquer

- **Domicile** : `wama_data/view.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §9quater.4, §9quater.7](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : Le VIEW-MODEL de l'Explorer — une DÉCLARATION de ce qu'on regarde.
- **API publique** (9) :
  - `class Track` — Un flux regardé, et les CHAMPS qu'on en montre. `champs` vide = tous.
  - `class Window` — Ce qu'on regarde du temps, ET à quelle résolution.
  - `class DerivedColumn` — Un calcul DÉCLARÉ sur un flux — pas son résultat.
  - `class View` — CE QU'ON REGARDE — sérialisable, donc rejouable, diffable, et entrant dans un manifeste.
  - `from_dict(brut: Mapping[str, Any]) -> View` — Reconstruit une vue depuis sa forme sérialisée. Valide comme à la construction.
  - `validate(view: View, ref: TemporalReferential) -> None` — Refuse une vue qui ne s'appliquera pas, EN LE DISANT — avant tout calcul.
  - `class Result` — Ce qu'une vue produit : les tables regardées, et celles que les calculs ont fait naître.
  - `apply(view: View, ref: TemporalReferential) -> Result` — Calcule ce que la vue déclare. **Ne persiste RIEN** (§9quater.5).
  - `series(view: View, ref: TemporalReferential, stream: str, field: str) -> List[dict]` — La série DÉCIMÉE d'une colonne, pour un tracé — min/max RÉELS par tranche.

### Visibilité et portée

Privé / unité / public : filtrage des lectures, mutations inchangées

- **Domicile** : `wama/common/models.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Briques de modèles COMMUNES (cf. BATCH_MODEL_AUDIT.md).
- **API publique** (27) :
  - `job_status_values() -> list` — Les VALEURS des cinq états de FILE, dans l'ordre du vocabulaire.
  - `normalize_job_status(value) -> str` — Un état QUELCONQUE (base, JSON, littéral d'app) → le vocabulaire commun.
  - `class ProcessingTimeMixin(models.Model)` — Durée RÉELLE de traitement, en secondes. Le worker la CALCULE déjà (il la passe au learner
  - `class QueueOrderMixin(models.Model)` — Position MANUELLE de l'entrée dans la file (CARD_DESIGN §3bis — manipulation directe).
  - `class BatchMixin` — Sémantique + cycle de fichiers communs aux modèles Batch (tout est batch ; unitaire = card unique).
  - `class OrgUnit(models.Model)` — Unité organisationnelle = nœud de l'arbre institut/université → département →
  - `class Project(models.Model)` — Projet de recherche = groupe de collaboration EXPLICITE qui peut TRAVERSER l'arbre
  - `class ProjectMembership(models.Model)` — Adhésion d'un utilisateur à un projet, avec son rôle et son org (traçabilité
  - `user_projects(user)` — Ids des projets dont l'utilisateur est membre (tous rôles).
  - `user_scope_org_ids(user)` — Ensemble des OrgUnit ids « couvrant » l'utilisateur : ses unités de rattachement
  - `class ElementPreference(models.Model)` — ABONNEMENT d'un utilisateur à un élément de catalogue (app, modèle, fonction, skill…).
  - `class UserAppSetting(models.Model)` — RÉGLAGE GLOBAL d'un utilisateur pour une app — DURABLE (brique `utils/user_settings.py`).
  - `class ScopedVisibility(models.Model)` — Mixin ABSTRAIT : visibilité par scope (privé / PROJET / unité org / public).
  - `scoped_visible_q(user, owner_field='user')` — `Q` filtrant les objets ScopedVisibility visibles pour `user` : les siens + les
  - `class PromptScoped(models.Model)` — Modèle portant un prompt utilisateur TRAITÉ par la PromptPipeline (enrichissement).
  - `class ScopedQuerySet(models.QuerySet)` — QuerySet des modèles `ScopedVisibility` : expose `visible_to(user)`.
  - `class ScopedManager(models.Manager.from_queryset(ScopedQuerySet))` — Manager par défaut des modèles partageables.
  - `class UserFunction(ScopedVisibility)` — Fonction de traitement CRÉÉE PAR UN UTILISATEUR (WAMA Data), stockée en BDD, avec
  - `class Manifest(models.Model)` — Store des MANIFESTES (union discriminée par `manifest_kind`) — cf. WAMA_MANIFEST_SPEC.md.
  - `class Library(models.Model)` — Registre des librairies externes — **NÉ de la projection** du manifeste `library`.
  - `class RunOutcome(models.Model)` — Journal des FAITS observés sur un résultat produit — préalable de toute auto-amélioration
  - `class Embedded(models.Model)` — Socle vectoriel commun au souvenir et au fragment. ABSTRAIT — aucune table.
  - `class MemoryItem(Embedded, ScopedVisibility)` — LE SOUVENIR — un fait, un événement ou une procédure. NON re-dérivable.
  - `class RagChunk(Embedded, ScopedVisibility)` — LE FRAGMENT — un morceau d'un document source. RE-DÉRIVABLE : la source fait foi, donc une
  - `class Conversation(models.Model)` — Un fil de dialogue avec l'assistant, quelle que soit la surface qui le porte.
  - `class ConversationTurn(models.Model)` — Un tour de conversation — ce que l'utilisateur a dit, ou ce que l'assistant a répondu.
  - `class InputProvenance(models.Model)` — D'OÙ vient le fichier d'entrée d'un élément — le LIEN qui manquait.

### Voix de référence (médiathèque) et voix de clonage

LA brique TTS des voix : `speaker_wav_for` (décidée par la CAPACITÉ du moteur, jamais par un nom de moteur), `resolve_speaker_wav` (sa_/ua_/cv_/nom d'avant), `describe_voice`, `voice_reference_groups` (optgroups dérivés d'une REQUÊTE sur `SystemAsset(voice)` + `attributes`), `ingest_voice_file` (le seul point d'entrée, ingest initial ET téléchargements). Les voix VIVENT en médiathèque depuis le 2026-09-13 (28 versées, dossier `voice_references/` retiré) ; `tts_service.py` ne résout plus rien. Quatre consommateurs : synthesizer, avatarizer, `voice_options` (menus), assistant

- **Domicile** : `wama/common/tts/voice_refs.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §9.4](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Voix de RÉFÉRENCE — la brique COMMUNE : résolution d'un preset en fichier, groupes du menu, libellés, téléchargement. Les voix VIVENT EN MÉDIATHÈQUE (`SystemAsset(asset_type='voice')`, `media_library/system/`) depuis le 2026-09-13 — plan `MEDIA_STORAGE_TIERING §9.4`.
- **API publique** (11) :
  - `attributes_from_voice_id(voice_id: str) -> Dict` — Les `attributes` (nature `voice`) qu'un identifiant de preset PORTE.
  - `voice_reference_groups() -> List[Dict]` — Les optgroups du menu « voix de référence », DÉRIVÉS de la médiathèque :
  - `readable_voice_assets(user)` — Les voix de médiathèque qu'un utilisateur a le DROIT d'employer : les SIENNES **et celles
  - `resolve_speaker_wav(voice_preset: str, user=None) -> Optional[str]` — Résout un voice_preset en chemin `speaker_wav` (audio de référence) pour le CLONAGE
  - `is_cloned_voice(voice_preset: str) -> bool` — Cette voix est-elle un CLONAGE (`ua_<id>` médiathèque de l'utilisateur, `cv_<id>` hérité) ?
  - `model_supports_cloning(model_key: str) -> Optional[bool]` — Le moteur du modèle `model_key` CLONE-t-il ? — `True`/`False` si quelque chose le dit,
  - `speaker_wav_for(model_key: str, voice_preset: str, user=None, reference_path: Optional[str]=None) -> Optional[str]` — LA porte des workers et des aperçus : le `speaker_wav` à passer au service TTS.
  - `ingest_voice_file(name: str, path, *, source_url: str='', license: str='', description: str='', replace: bool=False)` — Verse UN fichier de voix dans la médiathèque comme `SystemAsset(voice)` nommé `name`,
  - `needs_voice_download() -> bool` — Vrai si une voix du catalogue n'est pas (encore) en médiathèque.
  - `download_missing_voice_refs(force: bool=False, names=None) -> Dict[str, str]` — Télécharge les voix de référence manquantes et les VERSE en médiathèque.
  - `describe_voice(preset_value: str, user=None) -> str` — Le libellé d'une valeur de `voice_preset`, quelle que soit sa forme — pour AFFICHER

### Écrivain de conteneur (WAMA Data)

UN MOTEUR, N SCHÉMAS — le pendant exact du registre de lecteurs, et le premier code du monde Data qui ÉCRIVE du SQLite (0 `INSERT` dans tout le monde avant lui). Le moteur tient la transaction, les tranches, l'indexation temporelle et la conversion des valeurs ; un schéma ne décide que des NOMS et du CATALOGUE — c'est ce qui garantit que `.wdat` (natif, D3) et `.trip` (compatibilité BIND) se comportent pareil là où ils le doivent. Écrit d'abord un `.partiel` puis renomme : un conteneur à moitié rempli s'ouvrirait normalement en mentant sur son contenu. ⚠ CE QUE LE SCHÉMA CIBLE NE SAIT PAS PORTER EST COMPTÉ, pas tu (`Rapport.pertes`) — une conversion qui appauvrit en silence fait croire à un aller-retour fidèle. La compatibilité est attestée par CONTRE-ÉPREUVE : ce que WAMA écrit, le lecteur `.trip` — écrit contre le format de l'autre, sans rien savoir de l'écrivain — le relit

- **Domicile** : `wama_data/containers/__init__.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §9quater.2, §9duodecies](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : ÉCRIVAIN DE CONTENEUR — un moteur, N schémas. Le pendant exact de `sources/` (un moteur, N lecteurs).
- **API publique** (12) :
  - `class Context` — Ce qui accompagne les flux dans le conteneur — le catalogue non temporel.
  - `class Entry` — Un flux PRÊT à écrire : sa table, ses colonnes de temps, ses colonnes de données.
  - `class Report` — Ce que l'écriture a produit — et ce qu'elle a **perdu**.
  - `class ContainerSchema` — Un format de conteneur. À sous-classer, puis à enregistrer via `register_schema`.
  - `register_schema(schema: ContainerSchema) -> ContainerSchema`
  - `available_schemas() -> List[str]`
  - `writable_extensions() -> List[str]`
  - `schema_for(cible) -> Optional[ContainerSchema]` — Le schéma désigné par un nom de format **ou** par l'extension d'un chemin.
  - `schema_modules() -> List[str]` — Modules de schéma du paquet — **DÉCOUVERTS, jamais cités** (G1, cf. `sources.modules_lecteurs`).
  - `ident(name: str) -> str` — Identifiant SQL cité. Un nom de colonne vient de la DONNÉE : il ne doit jamais atterrir tel
  - `sql_value(v: Any) -> Any` — Valeur Python → valeur SQLite.
  - `write(referentiel: TemporalReferential, path, *, format: str='', contexte: Optional[Context]=None, stream: Optional[Iterable[str]]=None, tranche: int=TRANCHE,…` — Écrit un référentiel dans un conteneur. Rend un `Report` — **y compris ce qui a été perdu**.

## Studio & surface d'outils (API)

### API REST v1

Passerelle générique (token+session) sur TOOL_REGISTRY : lister/exécuter, gating F7 à l'annonce ET à l'exécution

- **Domicile** : `wama/api/v1/views.py`
- **Module** : WAMA REST API v1 — Views
- **API publique** (5) :
  - `class ListToolsView(APIView)` — GET /api/v1/tools/
  - `class RunToolView(APIView)` — POST /api/v1/tools/run/
  - `class AssistantChatView(APIView)` — POST /api/v1/assistant/chat/
  - `class FileUploadView(APIView)` — POST /api/v1/files/upload/ (multipart : champ `file`)
  - `class FileDownloadView(APIView)` — GET /api/v1/files/download/?path=<chemin relatif à MEDIA_ROOT>

### Runner générique du studio

Exécute une app par son CONTRAT (triade tool_api normalisée) — zéro logique par app

- **Domicile** : `wama/studio/services/generic_runner.py` · **doc** : [docs/construction/mondes/STUDIO_VISION.md](../construction/mondes/STUDIO_VISION.md)
- **Module** : Studio — runner GÉNÉRIQUE piloté par le CONTRAT d'app (STUDIO_VISION « principe directeur », 2026-07-12). Zéro logique par app : tout vient des sources uniques.
- **API publique** (1) :
  - `build_generic_runner(app_id)`

### Surface d'outils

Registre central TOOL_REGISTRY : triades add/start/status par app, gating F7 via execute_tool, descriptions dérivées des schémas

- **Domicile** : `wama/tool_api.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Tool API
- **API publique** (85) :
  - `list_user_files(user, folder: str='temp') -> dict` — List ALL files in one of the user's folders (any extension).
  - `add_to_anonymizer(user, file_path: str, use_sam3: bool=False, sam3_prompt: str='', classes: list=None, precision_level: int=50, **params) -> dict` — Copy a file into the anonymizer input queue and create a Media DB entry.
  - `start_anonymizer(user, media_id: int=None) -> dict` — Trigger Celery processing for a specific media item or all pending items.
  - `get_anonymizer_status(user) -> dict` — Return status of the user's current anonymizer jobs (last 10).
  - `sam3_examples() -> dict` — Return recommended SAM3 text prompt examples.
  - `create_image(user, prompt: str, model: str='hunyuan-image-2.1', width: int=512, height: int=512, steps: int=30, guidance_scale: float=7.5, negative_prompt: str…` — Create a txt2img generation job (status: PENDING).
  - `start_imager(user, generation_id: int=None) -> dict` — Launch Celery image generation task(s).
  - `get_imager_status(user) -> dict` — Return status of the user's recent image generation jobs (last 10).
  - `add_to_enhancer(user, file_path: str, ai_model: str='RealESR_Gx4', denoise: bool=False, blend_factor: float=0.0) -> dict` — Register a file for enhancement and create the Enhancement DB entry.
  - `start_enhancer(user, enhancement_id: int=None) -> dict` — Launch Celery enhancement task(s).
  - `get_enhancer_status(user) -> dict` — Return status of the user's recent enhancement jobs (last 10).
  - `add_to_audio_enhancer(user, file_path: str, engine: str='resemble', mode: str='both', denoising_strength: float=0.5, quality: int=64) -> dict` — Register an audio file for speech enhancement.
  - `start_audio_enhancer(user, audio_enhancement_id: int=None) -> dict` — Launch Celery audio enhancement task(s).
  - `get_audio_enhancer_status(user) -> dict` — Return status of the user's recent audio enhancement jobs (last 10).
  - `synthesize_text(user, text: str, language: str='fr', tts_model: str='coqui-xtts', voice_preset: str='default', speed: float=1.0, pitch: float=1.0, emotion_inte…` — Create a VoiceSynthesis job from raw text.
  - `start_synthesizer(user, synthesis_id: int=None) -> dict` — Launch Celery synthesis task(s).
  - `get_synthesizer_status(user) -> dict` — Return status of the user's recent synthesis jobs (last 10).
  - `compose_music(user, prompt: str, model: str='musicgen-small', duration: float=10.0, **params) -> dict` — Create a Composer generation job (music or SFX) and start it immediately.
  - `start_composer(user, generation_id: int) -> dict` — Lance (ou relance) la génération d'une composition créée via compose_music().
  - `get_composer_status(user) -> dict` — Return status of the user's recent Composer jobs (last 10).
  - `add_to_describer(user, file_path: str, output_style: str='detailed', output_language: str='fr', max_length: int=500, **params) -> dict` — Copy a file into the describer queue and create a Description DB entry.
  - `add_to_transcriber(user, file_path: str, backend: str='auto', preprocess_audio: bool=False, hotwords: str='', enable_diarization: bool=True, **params) -> dict` — Copy a file into the transcriber queue and create a Transcript DB entry.
  - `start_transcriber(user, transcript_id: int=None) -> dict` — Launch Celery transcription task(s).
  - `get_transcriber_status(user) -> dict` — Return status of the user's recent transcription jobs (last 10).
  - `add_to_reader(user, file_path: str, backend: str='auto', mode: str='auto', output_format: str='txt', language: str='') -> dict` — Copy a file into the reader queue and create a ReadingItem DB entry.
  - `convert_file(user, file_path: str, output_format: str, quality_preset: str='balanced', **params) -> dict` — Queue a file conversion and start it immediately.
  - `list_media_assets(user, asset_type: str='', q: str='') -> dict` — List the user's personal media library assets.
  - `switch_ui_mode(user, mode: str='simple') -> dict` — Switch the WAMA interface mode for the current user.
  - `get_media_asset_url(user, asset_id: int) -> dict` — Get the file URL of a specific media library asset.
  - `inspect_user_file(user, file_path: str) -> dict` — Ask WAMA what it can do with one of the user's files: which app PORT can take it
  - `look_at_image(user, file_path: str, question: str='') -> dict` — Look at ONE of the user's images with a vision model and return what it shows.
  - `add_to_media_library(user, file_path: str, asset_type: str, name: str='', description: str='') -> dict` — Register one of the user's files as a media-library asset with an EXPLICIT role.
  - `search_web(user, query: str, max_results: int=5) -> dict` — Search the public web (no API key) and return result links with snippets.
  - `read_web_page(user, url: str, max_chars: int=8000) -> dict` — Fetch ONE public web page and return its readable text (SSRF-guarded, size-capped).
  - `add_to_avatarizer(user, mode: str='pipeline', text_content: str='', tts_model: str='coqui-xtts', language: str='fr', voice_preset: str='default', audio_path: s…` — Crée un job de génération d'avatar parlant (vidéo) en attente.
  - `start_avatarizer(user, job_id: int=None) -> dict` — Lance la génération Celery d'un avatar (ou de tous les jobs en attente).
  - `get_avatarizer_status(user) -> dict` — Retourne l'état des 10 derniers jobs avatar de l'utilisateur connecté.
  - `translate_text(user, text, source_lang='fr', target_lang='en', glossary=None)` — Traduit un texte via translategemma (TranslatorService). Passthrough si source==target.
  - `add_to_synthesizer(user, *args, **kwargs)`
  - `add_to_composer(user, *args, **kwargs)`
  - `add_to_converter(user, *args, **kwargs)`
  - `add_to_imager(user, *args, **kwargs)`
  - `list_studio_pipelines(user) -> dict` — List the user's saved studio pipelines (méta-app graphs), most recent first.
  - `run_studio_pipeline(user, pipeline_id: int=None, pipeline_name: str=None) -> dict` — Run a SAVED studio pipeline, by id or exact name. Validates the graph
  - `get_studio_run_status(user, run_id: int=None) -> dict` — Return the status of a studio run (or the last 5 runs if run_id is omitted).
  - `list_ai_models(user, app: str=None, task: str=None, modality: str=None, downloaded_only: bool=False, include_proposed: bool=False, limit: int=50) -> dict` — List the AI model CATALOGUE (read-only — trou #18 ROUTE §11, lecture utile à l'assistant).
  - `get_ai_model(user, model_key: str) -> dict` — Full catalogue record of ONE model (read-only). `model_key` = '<app>:<id>'
  - `search_models(user, query: str, limit: int=10, max_results: int=5) -> dict` — SEARCH HuggingFace for models matching `query` and record them as prospection
  - `install_model(user, model_key: str, force: bool=False, variant_ref: str='', variant_file: str='') -> dict` — INSTALL a model that is already PROPOSED (prospection candidate) or already in the
  - `plan_library_integration(user, dist: str) -> dict` — PLAN for integrating a Python library (pip distribution) — read-only, executes nothing.
  - `plan_model_integration(user, model: str) -> dict` — PLAN for integrating an AI model — read-only, executes nothing.
  - `plan_app_integration(user, target: str) -> dict` — PLAN for integrating a GitHub project as a WAMA app (UI + models + libraries).
  - `memory_recall(user, query: str, k: int=5, include_rag: bool=True, include_memory: bool=True, niveaux: list=None) -> dict` — Cherche dans la mémoire et les documents de l'utilisateur (`WAMA_MEMORY.md`).
  - `charger_competence(user, domaine: str, question: str='') -> dict` — Load a specialised competence (role skill) and the matching laboratory context.
  - `ask_claude_code(user, task: str, write: bool=False, timeout: int=300) -> dict` — Delegate a DEVELOPMENT task to Claude Code, running on the owner's subscription.
  - `list_my_items(user, app: str='', limite: int=25, statut: str='all', q: str='') -> dict` — List what the user has produced across ALL apps — one vocabulary instead of ten.
  - `get_item_detail(user, app: str, pk: int) -> dict` — Everything known about ONE item, in the canonical schema — exactly what the user sees in
  - `get_item_preview(user, app: str, pk: int, side: str='input') -> dict` — Look at what an item actually holds: the file it started from, the result it produced, or
  - `delete_item(user, app: str, pk: int) -> dict` — Delete ONE of the user's items from an app queue.
  - `duplicate_item(user, app: str, pk: int) -> dict` — Duplicate ONE of the user's items, so it can be re-run with different settings.
  - `clear_my_queue(user, app: str, confirm: bool=False) -> dict` — Empty the user's WHOLE queue for one app — every item, at once.
  - `add_item_to_media_library(user, app: str, pk: int, asset_type: str='', name: str='', output_format: str='') -> dict` — Keep the RESULT of one of the user's items in their media library, so it can be reused as
  - `list_registries(user) -> dict` — List what WAMA knows how to NAME: its registries (apps, models, backends, functions,
  - `get_my_access(user) -> dict` — What the current user is allowed to do: account tier, business roles, and which apps they
  - `list_my_memories(user, kind: str='', limite: int=25) -> dict` — List what WAMA remembers for this user — facts, events and procedures it has kept.
  - `tool_role(tool_name)` — Rôle d'un outil dans la triade : 'add' | 'start' | 'status', sinon None.
  - `app_id_for_tool(tool_name)` — app_id gardé correspondant à un outil, ou None si l'outil est transverse.
  - `tool_descriptions()` — Descriptions de TOUS les outils du registre, dérivées à la volée.
  - `tool_input_schema(tool_name: str) -> dict` — Schéma JSON (`type: object`) des arguments d'un outil du registre — DÉRIVÉ, jamais écrit.
  - `input_schema_for(fn, index=None) -> dict` — Schéma JSON des arguments d'une FONCTION d'outil : signature, complétée par le schéma
  - `primary_arg_name(tool_name: str)` — Nom du 1er paramètre « utile » d'un outil (celui qui suit `user`), ou None.
  - `sanitize_tool_args(tool_name: str, args: dict)` — Prépare les arguments d'un appel d'outil : coercition par le SCHÉMA de l'app puis
  - `relay_quality_intent(user, tool_name: str, result: dict) -> dict` — Relaie le curseur Rapide ↔ Qualité de l'ASSISTANT vers l'élément qu'un outil `add_to_<app>`
  - `execute_tool(tool_name: str, args: dict, user) -> dict` — Dispatch a tool call from the agentic loop.
  - `list_user_files_view(request)`
  - `add_to_anonymizer_view(request)`
  - `start_anonymizer_view(request)`
  - `get_anonymizer_status_view(request)`
  - `sam3_examples_view(request)`
  - `add_to_reader_view(request)`
  - `start_reader_view(request)`
  - `get_reader_status_view(request)`
  - `convert_file_view(request)`
  - `get_converter_status_view(request)`
  - `build_tools_list() -> str` — Génère la liste des outils (nom + args + description) pour le prompt de l'assistant.
