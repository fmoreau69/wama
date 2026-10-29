<!-- WAMA:GENERE(dev-briques) — généré par « python manage.py doc_facts » depuis le plan de wama/common/docs_catalog.py ; ne pas éditer -->
# Briques communes — API

> Doc développeur **générée** : chaque section vient de la doc de construction (source citée en pied) ou des registres eux-mêmes. Pour la corriger, corriger la SOURCE — ce fichier est réécrit par `python manage.py doc_facts`.

**215 mécanismes** en 9 domaines. Ce qu'une brique FAIT est sa ligne de registre (`wama/common/mecanismes.py`) ; comment l'APPELER est ce que son module expose, lu dans le code par AST. Qui l'utilise, et ce qui manque : la [carte des mécanismes](../construction/architecture/WAMA_MECANISMES.md).

## Ressources & exécution

### Cache par empreinte de fichier

Garde une valeur calculée depuis un fichier (lecture AST, rendu markdown, compte de lignes) tant que son empreinte — date de modification, taille — n'a pas changé : un fichier modifié est relu, jamais servi périmé. Extrait le 2026-09-14 : le catalogue des docs portait le geste en dur, et l'inventaire des backends relisait 6 237 fois des fichiers pour UNE extraction de manifeste (48 résolutions d'un même vivier). ⚠ Ne convient qu'à ce qui ne dépend QUE du fichier

- **Domicile** : `wama/common/file_cache.py`
- **Module** : Cache par EMPREINTE de fichier — une valeur calculée depuis un fichier, gardée tant que le fichier n'a pas changé.
- **API publique** (2) :
  - `file_stamp(path) -> Optional[tuple]` — `(mtime_ns, taille)` du fichier (ou du dossier), `None` s'il est illisible.
  - `class FileCache` — `get(chemin, calcul)` : `calcul(chemin)` n'est rappelé que si l'empreinte a changé.

### Client du service TTS

L'appel POST /tts UNIQUE vers le microservice TTS (payload contractuel, 503 « loading » → TTSServiceLoadingError, WAV temporaire ou bytes) ; les POLITIQUES (retry Celery, chunking, replis) restent aux appelants — extrait 2026-08-28 : 4 exemplaires vivaient dans le dépôt, un seul détectait le 503. Depuis le 2026-10-10 le service ÉCOUTE aussi : `stt_via_service` (POST /stt, Whisper chaud, conversation vocale de l'assistant) partage le même appel et la même traduction d'erreurs (`_post`)

- **Domicile** : `wama/common/tts/service_client.py` · **doc** : [docs/construction/ui/MODES_QUEUE_UX.md §2bis](../construction/ui/MODES_QUEUE_UX.md)
- **Module** : Client COMMUN du microservice TTS (`tts_service.py`, FastAPI, uvicorn :8001).
- **API publique** (7) :
  - `class TTSServiceLoadingError(Exception)` — Le service TTS répond 503 « loading » (démarrage/chargement d'un moteur) —
  - `service_url() -> str` — URL du service TTS : settings Django si disponibles, sinon env, sinon défaut.
  - `tts_eta_key_size(text, model)` — (clé, taille, unité) de l'ETA d'une synthèse par le service : durée ∝ longueur du texte,
  - `tts_via_service(text, model, *, language='fr', voice_preset='default', speaker_wav=None, multi_speaker=False, scene_description='', options=None, read_timeout=…` — Synthétise `text` via le microservice TTS et renvoie le chemin d'un WAV TEMPORAIRE
  - `stt_via_service(audio, *, content_type='audio/wav', language='', model=None, read_timeout=90)` — Transcrit un extrait COURT (octets audio) par le même service — la conversation vocale de
  - `speech_only_via_service(audio, *, content_type='audio/wav', read_timeout=90)` — Les seuls passages PARLÉS d'un extrait (WAV 16 kHz mono), b'' s'il n'y en a aucun — le
  - `end_of_turn_via_service(audio, *, model_path, read_timeout=1.5)` — Probabilité que la personne ait FINI sa phrase (0 à 1), d'après les 8 dernières

### Contrat de backend

Cycle de vie commun des porteurs de modèle — ALIMENTATION du gouverneur (enveloppe load/unload/process à toute profondeur d'héritage) et CAPACITÉS déclarées par le moteur (supports_*), lues par le catalogue

- **Domicile** : `wama/common/backends/base.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Contrat de backend de modèle COMMUN à WAMA — extrait de l'app de référence (Transcriber).
- **API publique** (5) :
  - `unload_live_backends(model_key: Optional[str]=None, exclude_sources=None) -> int` — Décharge les backends résidents de CE process ; rend le nombre d'instances déchargées.
  - `refresh_live_reservations() -> int` — Rafraîchit le TTL de la ligne de registre de chaque backend résident de CE process.
  - `start_reservation_heartbeat() -> bool` — Lance, UNE fois par process, le battement qui garde vivantes les lignes des résidents.
  - `class BaseModelBackend(ABC)` — Backend de modèle local (chargement/déchargement + traitement).
  - `seed_generators(seed: int) -> None` — Pose `seed` sur les générateurs que les moteurs tirent (2026-10-22) : `random`, numpy, torch

### Côté d'exécution (qui met une tâche en file)

Tout passe côté WSL, rien côté Windows, sauf les tests à la demande (règle de Fabien, 2026-09-29) : sous tests et hors WSL le broker est EN MÉMOIRE, l'envoi Windows est écrit au journal, la synchro de démarrage n'est pas dispatchée. Une décision, lue par `settings`, `wama/celery.py` et `model_manager`

- **Domicile** : `wama/common/services/runtime_side.py` · **doc** : [docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md](../construction/exploitation/INFRA_WSL_VS_WINDOWS.md)
- **Module** : QUEL PROCESSUS a le droit de mettre une tâche Celery en file — une décision, un seul endroit. Doc : `INFRA_WSL_VS_WINDOWS.md §Deux Redis`.
- **API publique** (2) :
  - `running_tests(argv=None) -> bool` — Le processus est-il une suite de tests (`manage.py test …`) ?
  - `tasks_dispatched(argv=None, os_name=None) -> bool` — Ce processus met-il ses tâches dans le VRAI broker ? Seulement côté WSL, hors tests.

### Dossiers connectés distants (rclone)

Monte un stockage distant comme un dossier du filemanager : nuage WebDAV, partage réseau SMB, Google Drive, OneDrive — chacun DÉCLARÉ comme type de stockage (champs saisis, connexion par le navigateur), la nature de ses options lue dans rclone. Secret chiffré passé par l'environnement, proxy de la source, accès vérifié avant montage, remontage au redémarrage, révocation au retrait (2026-10-10/11). Le montage du noyau (cifs) ne reste que le repli sans rclone

- **Domicile** : `wama/filemanager/remote_mounts.py` · **doc** : [docs/construction/suivi/ROADMAP.md](../construction/suivi/ROADMAP.md)
- **Module** : remote_mounts — dossiers DISTANTS montés par rclone sous le « dossier connecté » du filemanager : nuage de fichiers (WebDAV, Nextcloud), partage réseau (SMB), Google Drive, OneDrive.
- **API publique** (32) :
  - `class Field` — Un champ de la fenêtre « Connecter un dossier ».
  - `class OAuth` — Connexion OAuth 2 (code d'autorisation + PKCE) : l'utilisateur accorde l'accès dans un
  - `class StorageType`
  - `storage_type(key: str) -> StorageType | None`
  - `rclone_binary() -> str | None` — Le binaire rclone : réglage `WAMA_RCLONE_BIN`, puis le PATH, puis `~/.local/bin` (où il
  - `rclone_providers() -> dict` — {stockage: {option: métadonnée}} décrits par le rclone INSTALLÉ, ou {} sans rclone.
  - `backend_available(backend: str) -> bool` — Le rclone installé connaît-il ce stockage ?
  - `storage_form(key: str, values: dict | None=None) -> dict` — Ce que la fenêtre « Connecter un dossier » affiche pour un type : ses champs (libellé
  - `oauth_client(key: str) -> tuple[str, str]` — `(identifiant, secret)` du client OAuth que l'instance a déclaré pour un type, ou
  - `oauth_types_offered() -> list[dict]` — Les stockages à connexion OAuth que l'instance PROPOSE : client OAuth posé, stockage
  - `is_remote_url(text: str) -> bool` — Le chemin saisi désigne-t-il un dossier DISTANT (adresse web) plutôt qu'un chemin ?
  - `webdav_config(url: str, username: str='') -> dict` — La configuration d'un montage WebDAV, tirée de l'adresse SAISIE.
  - `smb_config(server: str, host: str, share: str, subpath: str='', username: str='', domain: str='') -> dict` — La configuration d'un partage réseau. `server` est le nom SAISI (il nomme le point de
  - `display_name(config: dict) -> str` — Nom d'affichage proposé : le dernier dossier de l'adresse, sinon le serveur.
  - `mount_point_name(config: dict) -> str` — Nom du point de montage : stable pour un même compte sur un même serveur et chemin.
  - `make_mount_point(name: str)` — `(Path | None, erreurs)` — crée le point de montage `name`.
  - `rclone_target(config: dict) -> str` — Le chemin rclone du dossier : un stockage « à la volée » (`:smb:`), configuré par
  - `check_access(config: dict, password: str)` — `(ok, erreur)` — les identifiants ouvrent-ils le dossier ? Liste un niveau, sans monter.
  - `unmount(path) -> bool` — Démonte un montage FUSE (paresseusement s'il est occupé ou mort).
  - `mount(config: dict, password: str)` — `(ok, chemin, erreur)` — monte le dossier distant et rend son chemin local.
  - `ensure_mounted(mounted_folder) -> bool` — Remonte un dossier distant dont le montage est tombé (redémarrage de WSL). Vrai si le
  - `release_credentials(config: dict, secret: str) -> bool` — Un dossier retiré (ou un montage qui a échoué) ne laisse pas d'accès ouvert : le mot de
  - `server_root(url: str) -> str` — La racine du serveur Nextcloud d'une adresse saisie (`https://nuage.fr`, ou
  - `login_flow_start(url: str)` — `(flux | None, erreur)` — ouvre un flux ; `flux['login']` est la page à ouvrir dans le
  - `login_flow_poll(flow: dict)` — `('pending' | 'granted' | 'error', données)` — l'utilisateur a-t-il accordé l'accès ?
  - `nextcloud_user_id(server: str, login: str, password: str) -> str` — L'identifiant qui figure dans l'adresse WebDAV. Il peut différer du nom de connexion
  - `revoke_app_password(config: dict, password: str) -> bool` — Révoque le mot de passe d'application que WAMA a obtenu par le navigateur : un dossier
  - `oauth_start(key: str, redirect_uri: str)` — `(flux | None, erreur)` — la page où l'utilisateur accorde l'accès (`flux['login']`) ;
  - `oauth_exchange(flow: dict, code: str)` — `(jeton rclone | None, erreur)` — échange le code reçu au retour contre un jeton.
  - `oauth_account(key: str, token: str) -> dict` — Ce que la configuration doit savoir du compte connecté : son nom (le point de montage et
  - `refresh_oauth_token(config: dict, secret: str) -> str | None` — Un jeton renouvelé (au format rclone), ou None. Appelé avant un remontage : le jeton
  - `revoke_oauth_token(config: dict, secret: str) -> bool` — Révoque le jeton chez le fournisseur qui le permet (Google). Microsoft n'a pas de

### ETA auto-apprenante

Estimation de durée par a-priori puis moyenne mobile, rangée par LIEU DE CALCUL (le matériel, ou la source d'un modèle distant : `compute_place`, 2026-10-26) ; un modèle CHAUD — distant, ou résident selon le gouverneur (`is_warm`) — ne paie pas de chargement, et quand l'appelant ne sait pas, c'est le gouverneur qui tranche (`pays_load`, 2026-10-27 : il était supposé chargé) ; sous la clé de catalogue d'un modèle, c'est aussi sa VITESSE D'INFÉRENCE, que le banc calibre et que le curseur rapide/qualité de toutes les apps compare (`comparable_speeds` → `model_selector.intent_choice`, 2026-10-11)

- **Domicile** : `wama/model_manager/services/eta_estimator.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §10](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Estimateur d'ETA WAMA — *seeding* auto-apprenant et hardware-aware. ================================================================================
- **API publique** (11) :
  - `hardware_fingerprint() -> str` — Identifiant court du matériel de calcul (GPU + VRAM) ; 'cpu' à défaut.
  - `compute_place(model_key: str) -> str` — OÙ tourne le calcul mesuré sous cette clé — la valeur sous laquelle l'ETA le range
  - `is_warm(model_key: str) -> bool` — Le modèle derrière cette clé est-il CHAUD — aucun chargement à payer avant de calculer ?
  - `names_catalogue_model(model_key: str) -> bool` — La clé d'ETA nomme-t-elle un modèle du CATALOGUE (elle-même ou après un préfixe d'usage) —
  - `pays_load(model_key: str, model_loaded: Optional[bool]=None) -> bool` — Le chargement du modèle entre-t-il dans l'estimation ? (2026-10-27, Fabien : « le gouverneur
  - `make_key(source: str, model_id: str) -> str` — Construit le model_key du registre : '{source}:{model_id}'.
  - `learned_speed(model_key: str) -> Optional[Tuple[str, float, int]]` — (unité, secondes par unité, échantillons) APPRIS pour ce modèle à son lieu de calcul
  - `comparable_speeds(model_keys) -> dict` — `{model_key: secondes par unité}` APPRISES sur ce matériel pour TOUT le lot, ou {} s'il
  - `estimate(model_key: str, size: float=1.0, unit: str='item', model_loaded: Optional[bool]=False, fallback_seconds: Optional[float]=None) -> float` — Estimation (secondes) du temps TOTAL de traitement d'un item.
  - `record_run(model_key: str, size: float, unit: str='item', process_seconds: float=0.0, load_seconds: Optional[float]=None, user=None) -> None` — Enregistre une exécution RÉELLE pour affiner l'estimation (EMA, par hardware).
  - `relearn_lines_from_runs(apply: bool=False) -> dict` — Amorce la droite (`_line`) des clés de PROCESS qui n'en ont pas encore, depuis les lignes

### Gardes de process

Anti-boucle-de-crash (redélivrance) et réconciliation des tâches orphelines ; solde des tâches d'un worker MORT (preuve : processus disparu) au démarrage du worker relancé (`worker_ready`) et par la surveillance des workers (`scripts/worker_watchdog.sh` → `manage.py worker_died`) ; relance d'un élément EN COURS sur accord confirmé (`grant_replace`, `api/replace-grant/`), la tâche remplacée ou arrêtée se retirant d'elle-même (`task_skeleton.LaunchSuperseded`)

- **Domicile** : `wama/common/utils/process_control.py` · **doc** : [docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md](../construction/exploitation/INFRA_WSL_VS_WINDOWS.md)
- **Module** : Contrôle de process COMMUN — brique transversale (cf. memory project_process_button_lifecycle).
- **API publique** (14) :
  - `grant_replace(model, pk, user) -> None` — L'utilisateur a CONFIRMÉ qu'il arrête le traitement en cours de cet élément pour le
  - `begin_processing(model, pk, *, user=None, reset=None, status_field: str='status', task_field: str='task_id', running_value: str='RUNNING')` — Démarrage ANTI-RACE d'un item (pattern obligatoire AGENTS.md — généralise describer
  - `stop_instance(instance, *, status_field: str='status', task_field: str='task_id', to_status: str='FAILURE', error_field: str | None=None, error_message: str="I…` — Stoppe le traitement d'un item : révoque la tâche Celery (SIGTERM) et le remet dans un état
  - `is_task_dead(task_id: str) -> bool` — True si la tâche Celery est dans un état terminal (finie/échouée/révoquée). NE classe PAS PENDING
  - `reconcile_if_stuck(instance, *, status_field: str='status', task_field: str='task_id', running_value: str='RUNNING', to_status: str='FAILURE', error_field: str…` — Si l'item est RUNNING mais que sa tâche Celery est dans un état TERMINAL
  - `collect_worker_snapshot(timeout: float=2.0)` — Photo de la flotte Celery en UNE interrogation :
  - `task_owner(task_id: str) -> str | None` — Nom du worker qui exécute la tâche (ex. ``'gpu@fbro-20-026'``), ou None si inconnu.
  - `is_task_orphaned(task_id: str, snapshot) -> bool` — True SEULEMENT si l'on a une PREUVE POSITIVE que la tâche est morte : elle a démarré
  - `is_task_lost(task_id: str, snapshot) -> bool` — True SEULEMENT si la tâche n'est PLUS NULLE PART : état Celery `PENDING`, aucun message
  - `reconcile_orphaned_running(instances, *, snapshot=None, status_field: str='status', task_field: str='task_id', running_value: str='RUNNING', to_status: str='FA…` — Réconcilie une liste d'items RUNNING dont la tâche Celery est TERMINÉE (is_task_dead)
  - `is_task_on_dead_process(task_id: str, hostname: str) -> bool` — PREUVE POSITIVE de mort (2026-09-24) : la tâche a démarré (`STARTED`) sur le worker
  - `work_models()` — Les modèles qu'un worker Celery peut traiter : ceux des apps WAMA qui portent la paire
  - `reconcile_dead_worker_tasks(hostname: str, *, error_message: str="Traitement interrompu : le worker s'est arrêté. Relancer l'élément.") -> list` — Bascule en échec RELANÇABLE chaque élément RUNNING dont la tâche a démarré sur le worker
  - `refuse_crash_redelivery(task, instance, *, status_field: str='status', task_field: str='task_id', to_status: str='FAILURE', error_field: str | None=None, error…` — Garde ANTI-BOUCLE-DE-CRASH pour les tâches lourdes (GPU) — à appeler EN TÊTE

### Gouverneur de ressources

Arbitre GPU/CPU/RAM entre process : réservation, résidence, priorités. Une ligne de réservation ou de tâche dont le process écrivain est MORT (même espace de pid) sort sans attendre son TTL (29/09 : 4 lignes sur 8 après une relance, ~24 Go fantômes retranchés du tirage). Une ligne « tâche en cours » vaut pour UN process GPU de la card depuis le 2026-10-14 ; `resident_here_gb` dit ce que CE process tient déjà d'un modèle (un rechargement idempotent n'est pas un besoin)

- **Domicile** : `wama/common/services/resource_governor.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §0](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Gouvernance des ressources WAMA (GPU / CPU / RAM) — POINT D'ENTRÉE UNIQUE.
- **API publique** (55) :
  - `configure_cuda_process() -> bool` — Plafonne l'allocateur CUDA de CE process à `ALLOCATOR_CAP_FRACTION` de la
  - `configure_cuda_process_when_torch_loads() -> None` — Le plafond CUDA du processus, posé au PREMIER IMPORT de torch plutôt qu'au démarrage
  - `total_vram_gb() -> float` — VRAM physique de la carte, 0.0 si pas de GPU — la SEULE mesure de WAMA (2026-10-10).
  - `owner_pid(owner: str) -> int | None` — Pid porté par une clé d'owner (`<module>.<Classe>:<pid>#…`, `composer.audiocpp:<pid>`),
  - `reserve_vram(owner: str, gb: float, *, allocated: bool=False, expires_in_s: float | None=None) -> bool` — Déclare que `owner` détient `gb` de VRAM. Écrase la ligne existante du même
  - `release_reservation(owner: str) -> bool` — Libère la RÉSERVATION de `owner` dans le registre Redis. Sans effet s'il n'en avait pas.
  - `vram_reservation(owner: str, gb: float)` — Réserve `gb` pour la DURÉE d'un bloc, puis libère — y compris si le bloc lève.
  - `reservations(exclude: str | None=None) -> dict[str, float]` — Réservations VIVANTES (Go par owner). Les lignes plus vieilles que
  - `reserved_gb(exclude: str | None=None) -> float` — Total BRUT réservé, tous détenteurs et process confondus (sauf `exclude`).
  - `line_age_s(owner: str) -> float | None` — Secondes depuis le PREMIER dépôt de la ligne de `owner` (`_LOADED_KEY` : son chargement,
  - `resident_models() -> dict[str, float]` — Modèles actuellement RÉSIDENTS en VRAM — `AIModel.model_key` → Go — tous process
  - `model_keys_of(owner: str) -> list[str]` — Clés catalogue du modèle porté par une clé d'owner — [] s'il n'en porte pas, ou si le
  - `model_key_of(owner: str) -> str | None` — Première clé de `model_keys_of` — pour un appelant qui n'en attend qu'une.
  - `resident_here_gb(model_key: str) -> float` — Go que CE process tient déjà pour `model_key` (ses backends résidents) — 0.0 sinon.
  - `ollama_host_owner(name: str) -> str` — Clé d'owner de la résidence du modèle Ollama `name` — UNE ligne par modèle résident.
  - `unseen_reserved_gb(probe: str='driver', exclude: str | None=None) -> float` — VRAM réservée que la SONDE `probe` ne voit pas encore — la seule part à lui retrancher.
  - `mark_used(owner: str) -> bool` — Horodate le dernier USAGE de `owner` (appelé à chaque `process()` d'un backend).
  - `record_measured_vram(owner: str, gb: float) -> bool` — Consigne une empreinte MESURÉE au chargement de `owner` — jamais une valeur déclarée.
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
  - `task_started(app_id: str, item_id, needed_gb: float=0.0, *, max_s: float | None=None, process: str='') -> str` — Déclare une tâche GPU EN COURS ; rend son jeton. Posé par le squelette commun autour de
  - `task_finished(token: str) -> None`
  - `running_tasks() -> list[dict]` — Tâches GPU en cours, tous process confondus — lignes expirées purgées, ET lignes dont le
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
  - `model_task_minutes(model_key: str | None) -> int` — Durée max déclarée pour un modèle au catalogue (minutes), 0 si aucune.
  - `task_time_limit_s(app_id: str, user=None, model_key: str | None=None) -> float` — Plafond de durée d'UN traitement, en secondes : le réglage de l'utilisateur s'il en a posé
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
- **API publique** (45) :
  - `get_user(request)` — Get current user or anonymous user.
  - `get_user_media_root(user)` — Get the media root path for a specific user.
  - `build_file_tree(user)` — Build a file tree structure for jstree with two collapsible sections:
  - `build_folder_node(config, media_root, user_id)` — Build a folder node with its children.
  - `scan_folder_files(folder_path, relative_path, user_id)` — Scan a folder for files and subfolders, returning jstree nodes recursively.
  - `resolve_mount_path(rel_path, user)` — Resolve a virtual 'mounts/<id>[/subpath]' to an absolute Path.
  - `scan_mount_folder(abs_folder, virtual_prefix)` — Scan a mounted folder and return jstree nodes with virtual paths.
  - `api_children(request)` — Lazy-load children of a specific folder node (called by jstree when expanding).
  - `api_tree(request)` — Get file tree for jstree.
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
  - `api_mount_login_flow(request)` — Démarre la connexion à un nuage PAR LE NAVIGATEUR (Nextcloud Login Flow v2) et rend la
  - `api_mount_oauth(request)` — Démarre la connexion à un stockage OAuth (Google Drive, OneDrive) : rend la page du
  - `api_mount_oauth_callback(request)` — Le RETOUR du fournisseur, dans l'onglet ouvert pour l'accord : le code reçu est échangé
  - `api_mount_login_flow_poll(request, flow_id)` — Interroge une connexion par le navigateur : `pending` tant que l'accès n'est pas accordé ;
  - `api_remount_shares(request)` — Re-mount all WAMA-managed CIFS shares (called from start_wama_prod.sh via localhost).
  - `api_mount_delete(request, pk)` — Remove a mounted folder.
  - `api_mount_serve(request, pk, path)` — Serve a file from a mounted folder inline (for preview).

### Lignes d'exécution des process

UNE ligne par (élément, nœud du pipeline, clé d'instance) : état du process sur les six états communs, photo des réglages surveillés, modèle EMPLOYÉ (lisible pendant un « auto »), sortie, durée. Dit ce qui est périmé (`stale_nodes` : réglage surveillé changé, puis cascade) et déduit l'état d'une card de ses process (`aggregate`). L'élément reste la vérité lue par l'interface tant qu'il porte `status` ; l'arrêt et la réconciliation referment les lignes ouvertes. Le lancement y écrit son PLAN (`plan` : ses process `PENDING`, avec sa tâche) ; l'ETA d'un process (`step_eta_seconds`, règle des passes du cam_analyzer) et celle d'une card, la somme de ce que joue son lancement (`launch_eta`, 2026-10-05). 2026-10-27 : une sortie PERDUE (fichier désigné, absent du disque, `output_lost`) ne périme pas son aval — seule une empreinte DIFFÉRENTE périme — : elle se dit (bande des process, résultats du studio) et se rejoue

- **Domicile** : `wama/common/services/process_runs.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Lignes d'exécution des process — la pièce du MOTEUR COMMUN de pipeline qui dit « tel process, pour telle card, dans tel état ». Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` points 4.1 à 4.5 (marche P3).
- **API publique** (25) :
  - `address(item) -> dict` — Adresse d'un élément : `{app, object_type, object_id}` — dérivée de l'élément SEUL, pour
  - `lines(item)` — Les lignes d'exécution d'un élément (une requête, ordonnée par nœud).
  - `lines_by_item(items) -> dict` — `{pk (texte): [lignes]}` des éléments d'UN même modèle — UNE requête pour toute une page
  - `line(item, node_id: str=MAIN_NODE, instance_key: str='')` — La ligne d'un nœud, ou None s'il n'a jamais été lancé.
  - `snapshot(settings, watched) -> dict` — Photo des réglages SURVEILLÉS : `{clé: valeur}` pour chaque clé de `watched`, lue d'un
  - `plan(item, steps, *, task_id: str='') -> int` — Le lancement ANNONCE les process qu'il va jouer : leurs lignes passent `PENDING` — « son
  - `rendered_before(row, task_id: str='') -> bool` — La photo de réglages de `row` est-elle celle d'un RENDU (un succès, ou un succès devenu
  - `start(item, node_id: str=MAIN_NODE, *, process_key: str='', kind: str='app', version: str='', instance_key: str='', settings_snapshot: dict | None=None, model_…` — Le process PART : la ligne passe `RUNNING`, sa photo de réglages est prise, l'erreur et
  - `await_resources(item, node_id: str=MAIN_NODE, *, process_key: str='', instance_key: str='', task_id: str='')` — Le tour du process est venu, la VRAM libre ne suffit pas : la ligne le dit, sans effacer
  - `succeed(item, node_id: str=MAIN_NODE, *, instance_key: str='', output_ref: str='', output_summary: dict | None=None, model_key: str | None=None, process_key: s…` — Le process a RENDU son résultat : `SUCCESS`, durée mesurée depuis `start`.
  - `output_lost(row) -> bool` — La ligne désigne une sortie FICHIER (`output_ref`, relatif à `MEDIA_ROOT`) que le disque ne
  - `annotate(item, node_id: str=MAIN_NODE, *, instance_key: str='', **values)` — Ajoute `values` à ce que la ligne retient de sa sortie (`output_summary`), sans toucher à
  - `fail(item, node_id: str=MAIN_NODE, message: str='', *, instance_key: str='', process_key: str='')` — Le process a ÉCHOUÉ — le message est gardé sur la ligne ; la sortie précédente, elle,
  - `close_open(item, to_status: str=JOB_FAILURE, message: str='') -> int` — Referme les lignes OUVERTES d'un élément qu'on arrête ou qu'on réconcilie : une tâche
  - `forget(item) -> int` — Retire les lignes d'un élément qu'on SUPPRIME (une ligne sans élément ne se lit plus
  - `forget_orphans(*, dry_run: bool=False, chunk: int=5000) -> dict` — Retire les lignes dont l'ÉLÉMENT n'existe plus (2026-10-28 : 1 366 mesurées ; Fabien : « si
  - `safely(writer, *args, **kwargs)` — Appelle un écrivain de ce module SANS jamais lever : le cycle de vie d'un traitement ne
  - `row_eta_seconds(size, last_duration, last_size, learned_seconds)` — Durée estimée d'un process : sa DERNIÈRE durée sur cet élément (le meilleur prédicteur
  - `last_duration(row) -> tuple` — `(durée, taille)` de la dernière exécution connue d'une ligne : sa durée mesurée, sinon
  - `process_eta(spec, item)` — L'ETA DÉCLARÉE d'un process pour cet élément (`ProcessSpec.eta`) : `(clé, taille, unité,
  - `step_eta_seconds(spec, item, row) -> float | None` — Durée estimée d'UN process de la card : la règle de `row_eta_seconds` (sa dernière durée
  - `launch_eta(item) -> float | None` — Durée TOTALE estimée du lancement d'une card à process : la somme de ses process — ceux
  - `stale_nodes(states: dict, depends_on: dict, snapshots: dict | None=None, current: dict | None=None) -> set` — Nœuds à passer `STALE`, parmi ceux qui sont en `SUCCESS`.
  - `mark_stale(item, node_ids) -> int` — Passe `STALE` les lignes `SUCCESS` des nœuds donnés. Rend le nombre de lignes changées.
  - `aggregate(processes) -> str` — État d'une CARD déduit de ses process — la règle du point 4.4, validée telle quelle le

### Modèle installé par la route au moment du besoin

DEPUIS LE 2026-10-16 (décision de Fabien : « la dérive arrive si l'installation n'est pas complète ; prévenir l'utilisateur ; la tâche attendra ») : un modèle du catalogue ABSENT qu'une tâche demande est installé PAR LA ROUTE (`ensure_installed` → `request_install` : garde d'espace, journal, jeton), l'utilisateur est prévenu, la tâche rend son worker et revient (`ServiceNotReady`) ; refus ou échec = la tâche échoue en le disant, une installation échouée n'est pas relancée en boucle. Appelée par le squelette (modèle de la card), par toute glu qui charge un modèle (`ctx.ensure_model`, 2026-10-18 : imager, reader, describer, synthesizer, avatarizer, anonymizer, diarisation et alignement du transcriber, glu générée ; 2026-10-19 : process secondaires du composer, partition extraite et partition complète — dont le modèle se CHOISIT sur la card), par le studio et le cam_analyzer (re-livraison Celery, `redeliver_later`) ; `install_and_wait` pour une commande (le banc). L'annonce d'origine (`warn_if_weights_missing`) reste pour la seule ligne que la route ne sait pas installer. — Historique : un modèle jamais utilisé télécharge ses poids À LA PREMIÈRE EXÉCUTION (37 appels `from_pretrained`/`snapshot_download` dans les backends) — et RIEN ne le disait : ni le squelette, ni les backends, ni la card. Mesuré le 2026-09-08, 4 modèles catalogués sont dans ce cas (mochi-1-preview, qwen-image-edit, flux2-klein-4b, musicgen-melody) : les lancer donnait une tâche figée, sans un mot, le temps de récupérer des dizaines de Go. *Une attente qu'on n'explique pas se lit comme une panne.* La brique ANNONCE et rien d'autre — elle ne télécharge pas (c'est le backend, au chargement), ne bloque pas, ne décide pas ; best-effort intégral. Adressée par la CLÉ DE CATALOGUE, la même qui résout le backend : l'annonce et l'exécution parlent du même modèle. Le squelette la déclare par `model_key` (OPTIONNEL, comme `vram_needed`). ⚠ Elle ne parle QUE si `is_downloaded=False`, et n'annonce la taille que si `disk_gb` la connaît : un avertissement permanent n'avertit plus de rien (celui de l'imager vidéo, en dur et à chaque lancement avec un volume inventé, a été retiré ce jour-là)

- **Domicile** : `wama/common/utils/model_readiness.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Un modèle s'INSTALLE par la route avant de servir — et l'utilisateur le sait.
- **API publique** (4) :
  - `warn_if_weights_missing(model_key: str, console=None) -> bool` — Prévient (console) si les poids de `model_key` sont ABSENTS. Rend True si prévenu.
  - `class ModelInstallRefused(RuntimeError)` — La route n'a pas installé le modèle (refus ou échec) : la tâche échoue en le DISANT.
  - `ensure_installed(model_key: str, *, user=None, console=None, redelivered: bool=False, via: str='task') -> bool` — Pour une TÂCHE : rend True quand le modèle est prêt à servir (ou que rien ne le concerne).
  - `install_and_wait(model_key: str, *, user=None, console=None, via: str='command', poll_s: float=5, timeout_s: float=None) -> bool` — Le même geste pour un appelant SYNCHRONE (une commande, jamais un worker) : installe par la

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

### Pipeline déclaré d'une app (plusieurs process)

Une app DÉCLARE les process de sa card (`ProcessSpec` : amonts, réglages surveillés, degré, condition d'application) comme le cam_analyzer déclare ses passes ; le registre devient un manifeste `pipeline` à nœuds `function` (`register_app_pipeline`). Dit ce qu'un lancement JOUE (`steps_to_run` : ce qui n'est plus à jour et son aval ; une card à jour relancée rejoue tout), ce qui est PÉRIMÉ (`refresh` : réglage changé, sortie d'amont remplacée, cascade) et l'état déduit de la card (`card_state`). L'exécution reste au squelette de tâche (`run_item_task(pipeline=…, processes=…)`), une ligne d'exécution par process. Une VUE lit dans une fenêtre (`preload` … `release`) : lignes lues une fois, réponses de `applies` retenues par (process, modèle) — un `applies` peut résoudre le backend du modèle (0,56 s l'appel, mesuré le 2026-10-05). 2026-10-21 : une ligne ne COMPTE que tant que l'élément demande son process (`still_counts` — un amont qui n'a plus lieu ne laisse plus son aval périmé à jamais) ; un aval LIT la sortie de son amont par un geste (`output_of`, `upstream_output` : le plus proche amont qui rend ce type) ; un process DÉTACHÉ de son aval (`split_from`) garde valables les lignes rendues avant le détachement ; ce que les process ont ÉCRIT (`produced_fields`), dont une copie repart sans. 2026-10-22 : une relance COMPLÈTE libère ce qui ne compte plus (`release_absent`) ; un process peut ne pas LIRE ses amonts (`upstream_switch`, `read_upstreams`)

- **Domicile** : `wama/common/services/process_pipeline.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Pipeline DÉCLARÉ d'une app — la pièce du moteur commun qui dit « cette card porte PLUSIEURS process, dans cet ordre, et voici lesquels sont à (re)jouer ». Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` points 3.2, 4.3 à 4.5 (marche P3, palier B) et décision n°11.
- **API publique** (14) :
  - `segments_text(segments) -> str` — Des SEGMENTS de parole (`result_format='segments'` : `[{speaker, time_range, text}]`) en
  - `preload(items) -> None` — Lit en UNE requête les lignes d'exécution de tous ces éléments (même modèle) et les pose
  - `release(item) -> None` — Referme la fenêtre de `preload` sur cet élément : une instance gardée par l'appelant (un
  - `class ProcessSpec` — Un process d'un pipeline d'app — les champs de `pass_tracking.Pass` qui ne sont pas
  - `output_fingerprint(ref: str) -> str` — Empreinte de la sortie d'un process (chemin relatif à MEDIA_ROOT) : celle de la brique
  - `declared_stales(app: str) -> dict` — `{process: [réglages]}` — ce que chaque réglage du schéma de `app` déclare périmer
  - `class AppPipeline` — Le pipeline déclaré d'une app : ses `ProcessSpec`, et ce qui s'en dérive.
  - `register_app_pipeline(app: str, specs, *, label: str, description: str='', source_ref: str='', model_of=None) -> AppPipeline` — Déclare le pipeline d'une app et l'inscrit comme source de manifeste `pipeline` sous la
  - `process_of_function(function_key: str)` — `(pipeline, ProcessSpec)` de l'ÉTAPE de card qu'est la fonction `function_key` — le process
  - `pipeline_of(item) -> AppPipeline | None` — Le pipeline déclaré par l'app de cet élément, ou None (app à un seul process). Charge
  - `app_pipeline(app: str) -> AppPipeline | None` — Le pipeline déclaré par l'app `app`, ou None — même lecture que `pipeline_of`, quand on
  - `card_view(item, model_key=DECLARED, preloaded: bool=False)` — Ce que la card et la vue de progression montrent du PIPELINE d'un élément (`§10.6` 5.1) :
  - `decorate(item, model_key=DECLARED, preloaded: bool=False)` — Pose `processes`, `shown_state`, `shown_state_label` sur l'élément — ce que lisent les
  - `decorate_cards(items, each=None) -> list` — Les cards d'une PAGE : leurs lignes d'exécution lues en UNE requête (`preload`), puis

### Progression de tâche longue

Avancement d'une tâche Celery HORS file d'items publié dans le cache (F5-proof) + garde « déjà en cours » vérifiée auprès de Celery ; pendant navigateur = WamaApp.Poller

- **Domicile** : `wama/common/utils/task_progress.py` · **doc** : [wama/model_manager/PROSPECTION_PIPELINE.md](../../wama/model_manager/PROSPECTION_PIPELINE.md)
- **Module** : Avancement d'une tâche Celery LONGUE publié dans le cache Redis — brique COMMUNE.
- **API publique** (2) :
  - `publier_progression(cache_key: str, task_id, state: str, payload: dict, ttl: int=TTL_DEFAUT) -> None` — Publie l'avancement d'une tâche dans le cache. `state`/`task_id` en DERNIER :
  - `progression_en_cours(cache_key: str)` — La progression publiée SI la tâche est encore vivante, sinon None.

### Retrouver un fichier de l'utilisateur, dossiers connectés compris

Recherche PAR NOM (casse et accents ignorés) dans ce que l'arbre du gestionnaire montre — temporaires, entrées et sorties de chaque app LUES à `_app_folders_config`, dossiers connectés résolus par `resolve_mount_path` : aucune liste de dossiers. Bornée par racine (temps, entrées) et une racine tronquée est DITE (`incomplete`). Porte aussi `mounted_file` : `designate` et les outils acceptent `mounts/…`, COPIÉ à l'entrée d'une app, jamais déplacé (2026-10-11, outil `find_user_files`). ⚠ La recherche du gestionnaire (`api_search`, 25 dossiers écrits à la main, sans les dossiers connectés) reste à rallier

- **Domicile** : `wama/common/services/user_files.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Retrouver un fichier de l'utilisateur PAR SON NOM, partout où le gestionnaire de fichiers le montre — dossier temporaire, entrées et sorties de chaque app, dossiers CONNECTÉS (locaux, réseau, nuage).
- **API publique** (4) :
  - `is_mount_path(path) -> bool` — Ce chemin désigne-t-il un dossier CONNECTÉ (`mounts/<id>/…`) ?
  - `mounted_file(path, user)` — Le chemin DISQUE d'un fichier `mounts/<id>/…` de CET utilisateur, ou None.
  - `search_roots(user) -> list` — Les racines de recherche de cet utilisateur, dans l'ordre de l'arbre du gestionnaire :
  - `find_user_files(user, query: str, *, limit: int=20) -> dict` — Les fichiers de `user` dont le NOM contient tous les mots de `query` (casse et accents

### Squelette de tâche

Enchaînement commun des tâches Celery d'item : gardes, progress, statuts, ETA. Depuis le 2026-10-14 le gouverneur y est au grain du PROCESS : avant chaque process GPU (`ProcessSpec.gpu`), attente de VRAM (besoin déclaré, sinon celui du modèle de la card, moins ce que le worker tient) et déclaration « en cours » ; chaque process se joue sur SA file (GPU ou par défaut), la tâche se re-livrant à l'autre entre deux process (`queue_of`, barre et durées du lancement reportées). 2026-10-21 : la MÉMOIRE DU LANCEMENT (`ctx.remember`/`recall`, le modèle retenu gardé d'une livraison à l'autre) et la PLACE d'un fichier de sortie (`ctx.output_place` : dossier de sortie de l'app au domicile de l'utilisateur, nom commun) ; 2026-10-22 : adoptée par toutes les glues (sous-dossier par nature, série, famille FICHIER sans identifiant), l'arrêt COOPÉRATIF d'un lancement remplacé

- **Domicile** : `wama/common/utils/task_skeleton.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Squelette COMMUN des tâches Celery d'item (brique F5 — marche A2 de la route §10.3).
- **API publique** (7) :
  - `class LaunchSuperseded(BaseException)` — Le lancement n'est plus celui de l'élément : l'utilisateur l'a ARRÊTÉ (⏹ — l'élément n'est
  - `class TaskContext` — Poignées offertes à la glu : progress + console. `progress_fn` permet à une app de
  - `class TaskTimeLimitExceeded(Exception)` — Le traitement a dépassé sa durée max (`resource_governor.task_time_limit_s`).
  - `class ServiceNotReady(Exception)` — Ce dont le traitement DÉPEND n'est pas encore prêt — un service qui charge (le service TTS
  - `redeliver_later(task, wait: ServiceNotReady)` — HORS squelette (une tâche Celery qui n'est pas celle d'une card : nœud du studio, analyse du
  - `queue_of(spec, gpu: bool=None) -> str | None` — La FILE Celery où se joue ce process : la file GPU pour un process qui sollicite la carte
  - `run_item_task(task, *, app_id: str, model, item_id: int, process=None, vram_needed=None, model_key=None, error_field: str='error_message', notify_label: str=No…` — Exécute la glu `process` dans le squelette conventionnel. Voir le contrat en tête de

### Tests nocturnes

Registre déclaratif de scénarios + runner sérialisé VRAM-aware (wired/ui/consistency/suite/model_loaded/output). Le stage `suite` (2026-09-19) fait entrer LA SUITE DJANGO dans la grille fonctionnelle : un scénario par app ayant des tests, DÉRIVÉ des apps installées ; verdict lu dans la SORTIE de `manage.py test` (jamais au code retour, qui sort en 0 sans rien lancer) et rouges NOMMÉS. DEUX comptes de test déclaratifs : le standard (rôles métier, SANS tier dev — c'est LUI que la matrice de droits mesure) et `get_test_dev_user` pour les surfaces dev-gated (jumelles de bac à sable), routé par `ui_smoke._test_session_key(app)` — sans lui les 11 scénarios d'une jumelle skippent (mesuré 2026-08-30). Le registre se REMPLIT AU PREMIER USAGE (2026-10-20) : une app déclare son enregistreur dans son `ready()` (`add_registrar`, chemin `module:fonction`) au lieu de l'exécuter — l'enregistrement chargeait toute la configuration d'URL (et torch) dans chaque processus Django

- **Domicile** : `wama/common/services/nightly_tests.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md §Tests fonctionnels nocturnes](../construction/suivi/PROJECT_STATUS.md)
- **Module** : Charpente des tests fonctionnels nocturnes de WAMA. ============================================================================
- **API publique** (19) :
  - `class SkipScenario(Exception)` — Levée par un `run` quand une dépendance est absente (modèle/lib non installé) :
  - `class Scenario` — Un test fonctionnel déclaratif. `run(ctx) -> (ok: bool, detail: str)` ; peut lever.
  - `class ScenarioResult`
  - `register(**kwargs) -> Scenario` — Enregistre un scénario. Doublon d'id → remplace (réimport sûr). Écrit le registre SUR
  - `add_registrar(registrar) -> None` — Déclare un ENREGISTREUR de scénarios — une fonction sans argument qui appelle `register`,
  - `load_scenarios() -> None` — Joue une fois les enregistreurs déclarés. `_loading` : False avant, True pendant (un
  - `scenario_cadence(sc: Scenario, sandbox_apps=None) -> str` — `daily` ou `weekly`. La DÉCLARATION prime ; sinon la règle, tirée de ce que le scénario
  - `select_scenarios(app=None, stage=None, cadence=None, scenarios=None) -> List[Scenario]` — Les scénarios ACTIFS d'une campagne — la tâche planifiée et la commande lisent la même.
  - `get_test_user()` — Utilisateur de test DÉDIÉ (jamais le compte réel). Créé si absent.
  - `get_test_dev_user()` — Compte de test DÉVELOPPEUR, dédié aux surfaces dev-gated (jumelles de bac à sable).
  - `is_test_account(user) -> bool` — Un compte de TEST déclaré (`TEST_USERNAMES`) : ce qu'il exécute ne MESURE pas la machine.
  - `sweep_test_witnesses() -> int` — Efface les FICHIERS témoins restés dans les dossiers média des comptes de TEST.
  - `free_vram() -> None` — Téardown VRAM best-effort entre scénarios (réutilise le cleaner du model_manager).
  - `run_one(sc: Scenario, ctx: dict) -> ScenarioResult` — Exécute UN scénario (timing + capture d'exception). NB : timeout dur = TODO prod
  - `run_all(scenarios: Optional[List[Scenario]]=None, write: bool=True, cadence: Optional[str]=None) -> dict` — Joue les scénarios EN SÉRIE, téardown VRAM avant/après chacun. Retourne le rapport.
  - `build_report(results: List[ScenarioResult]) -> dict`
  - `write_report(report: dict) -> Path`
  - `functional_grid() -> dict` — La grille FONCTIONNELLE (2ᵉ grille de `WAMA_VERIFICATION §2`, décidée le 22/08 et
  - `register_examples() -> None`

### Vocabulaire TTS partagé

Le JEU DE CHOIX unique de la parole synthétique — moteurs, langues, presets de voix, cartes moteur↔langue — et sa résolution (voix pour une langue, langue d'une voix). Distinct du client de service : celui-ci TRANSPORTE, celui-là NOMME. Les deux apps TTS, `accounts` (langue de profil) et l'assistant y puisent les mêmes libellés

- **Domicile** : `wama/common/tts/constants.py`
- **Module** : WAMA Common TTS Constants ========================= Source unique des constantes TTS partagées entre : - wama.avatarizer (AvatarJob) - wama.synthesizer (VoiceSynthesis) - tts_service.py (service FastAPI)
- **API publique** (1) :
  - `tts_catalog_key(name: str) -> str` — Nom de moteur saisi (`coqui-xtts`, fichier batch, outil de l'assistant) → CLÉ DE CATALOGUE.

## Modèles

### Auto-sélection (« auto » au select)

Valeur « auto » d'un select de modèle : résolution AU LANCEMENT sur le domaine que le schéma déclare pour ses options (options_query), prévision affichée sous le select (options_auto) + curseur de QUALITÉ continu 0-100 (intent_param, poids dans le score de select_model) ; `candidates_with` = le BESOIN qui filtre avant le classement (capacité = valeur, ex. `scale`=4)

- **Domicile** : `wama/common/utils/auto_model.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Auto-sélection de modèle — brique COMMUNE (valeur « auto » d'un select de modèle).
- **API publique** (18) :
  - `read_quality_intent(value) -> int` — Valeur 0-100 SÛRE depuis un POST/JSON : bornée, défaut équilibré, ne lève jamais.
  - `posted_quality_intent(source)` — Curseur POSTÉ (POST ou dict JSON) → entier borné, ou **None** s'il n'est pas posté ou
  - `preset_key_for_intent(intent) -> str` — La POSITION NOMMÉE la plus proche d'une valeur de curseur (`QUALITY_PRESETS` du sélecteur :
  - `intent_param(**overrides) -> dict` — Surcouche STANDARD du curseur de qualité pour un schéma d'app (`derive_from_model`).
  - `is_auto(value) -> bool` — Cette valeur demande-t-elle le tirage automatique ? (vide compris, et l'« auto » borné à
  - `candidates_with(capability: str, value, q=None, **filters) -> list` — Clés catalogue des modèles du domaine `filters` (champs d'`AIModel` ou `capabilities__…`,
  - `catalog_domain(app_id: str)` — DOMAINE déclaré au schéma de l'app pour son select de modèle, ou None.
  - `catalog_field(app_id: str)` — Le paramètre `options_source='catalog'` du schéma de l'app (le premier), ou None — le
  - `catalog_fields(app_id: str) -> list` — TOUS les paramètres `options_source='catalog'` de l'app — ceux de chacun de ses schémas
  - `declared_cloud_keys(app_id: str, user)` — Les modèles DISTANTS que le tirage AUTOMATIQUE de `app_id` peut retenir pour `user`, ou
  - `declared_resolution(app_id: str) -> dict` — Les affinages du tirage « auto » DÉCLARÉS au schéma de `app_id` (`options_resolution`),
  - `read_needs(text: str) -> dict` — `needs` tel que le navigateur le transmet (`scale:4,autre:x`) → `{capacité: valeur}`.
  - `need_candidates(needs: dict, domain: dict)` — Les clés du DOMAINE qui satisfont TOUS les besoins `{capacité: valeur}` — None quand aucun
  - `intent_field_for(app_id: str)` — Nom du champ « curseur » déclaré au schéma de l'app (`type='intent'`), ou None.
  - `quality_intent_of(item=None, app_id=None, user=None) -> int` — La valeur du curseur qui vaut pour CE lancement, en UN endroit (chantier C, 2026-09-20).
  - `resolve_model_choice(requested, *, app_id=None, spec=None, fallback=None, item=None, user=None, **overrides)` — Valeur finale du modèle pour un lancement : `requested` explicite, sinon tirage.
  - `predict_model_choice(spec)` — PRÉVISION : le modèle qui serait retenu MAINTENANT pour ce domaine, ou None.
  - `vram_needed_gb(model_key: str, *, offload: bool=False)` — Besoin VRAM du modèle RÉSOLU, pour la garde du squelette de tâche

### Banc de comparaison

Mesures comparables par TÂCHE sur un échantillon (latence, sorties, saturation) ; `text-generation` mesure le DÉBIT d'un LLM Ollama (jetons/s, prefill, chargement) et nourrit la boucle d'ETA (`ModelRuntimeStat`, unité token) — des coûts, jamais une qualité

- **Domicile** : `wama/model_manager/services/bench.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.2](../construction/suivi/ROADMAP.md)
- **Module** : Banc de comparaison de modeles, indexe sur la TACHE et non sur l'app.
- **API publique** (14) :
  - `models_for_task(task: str, *, installed_only: bool=True)` — Modeles du catalogue qui declarent cette tache. Le catalogue est la seule source.
  - `read_recall_reference(sample: str) -> dict` — La reference d'un banc de rappel (JSON) : `media` (chemin, relatif au fichier ou
  - `containment_counts(doc: dict, ref: dict) -> dict` — Les comptes du rappel par contenant — sans interpretation (cf. en-tete du protocole).
  - `benchmark_reference(name: str) -> str` — Le fichier de reference du banc `name`, sous la racine des jeux de donnees — resolue par la
  - `read_boxes_reference(sample: str) -> dict` — Une reference « vraies boites » : `class`, `format`, `images` (dossier), `annotations`
  - `merged(found, iou: float=0.5) -> list` — Les detections d'UNE image sans leurs DOUBLONS : un meme objet vu a deux echelles (une
  - `match_boxes(found, truth, ignore, iou: float=0.5) -> dict` — Comptes d'UNE image : `found` = [(box, conf)], `truth`/`ignore` = [box]. Les doublons de
  - `read_image_reference(sample: str) -> dict` — Une référence « dossier d'images nettes » : `images` (dossier, relatif au fichier de
  - `lpips_folder() -> Path`
  - `lpips_metric(device: str)` — LPIPS (réseau AlexNet), chargé une fois par processus. Les couches linéaires viennent du
  - `boxes_candidates(sample: str) -> list` — Detecteurs installes qui couvrent la classe d'une reference « vraies boites ».
  - `recall_candidates(sample: str) -> list` — Les modeles a mesurer pour une reference : detecteurs installes qui couvrent sa classe.
  - `available_tasks() -> list` — Taches pour lesquelles un protocole existe — les autres restent a ecrire.
  - `run_bench(task: str, sample: str, *, models: Optional[list]=None, **options) -> list` — Passe chaque modele de `tache` sur `echantillon` et rend des mesures comparables.

### Benchmark tiers confronté

Étage 2 qualité (a priori < benchmark < mesure) : AA + Elo Arena (texte, image, vidéo, VISION, document) + Open ASR (WER, sens 'bas') + MTEB (embeddings, jeu FRANÇAIS déclaré) appariés au catalogue, prospection incluse. Depuis le 10/10 : la MUSIQUE d'AA (chansons, instrumental) et les CLASSEMENTS des jeux de référence officiels du Hub (olmOCR-Bench, MDPBench, Real5-OmniDocBench, ParseBench — valeurs déclarées, `provenance` par entrée) ; appariement par DÉPÔT exact avant la famille + version ; `provenance` (indépendant / vérifié / auto-déclaré) et `matched_by` écrits avec chaque banc, rang centile réservé aux bancs indépendants ; banc mis en file À L'INSTALLATION (`queue_benchmarks`), synchro chaque nuit, cache disque des sources

- **Domicile** : `wama/model_manager/services/benchmark_sync.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : Signal qualité « BENCHMARK TIERS CONFRONTÉ » — 2e étage de l'échelle des signaux.
- **API publique** (12) :
  - `class SourceUnavailable(Exception)` — Réseau/clé/format absents — la source est SKIPPÉE, jamais un score partiel inventé.
  - `load_aa()` — {'categorie': [{'nom','slug','valeur','echelle','identite'}]} ; motifs par catégorie.
  - `load_arena()` — {'categorie': [{'nom','elo','votes','identite'}]} depuis le dataset HF officiel
  - `load_open_asr()` — {'categorie': [{'nom','slug','wer','identite','rtfx','licence','taille_b','jeux'}]}
  - `load_hf_benchmarks()` — {'catégorie': [entrées]} depuis le CLASSEMENT des jeux de référence OFFICIELS du Hub
  - `load_mteb()` — {'embedding': [{'nom','slug','score','identite','taches','revision'}]} depuis le dépôt
  - `benchmarks_comparable(pool) -> bool` — Vrai si les `benchmark_index` du lot peuvent être ORDONNÉS entre eux.
  - `orderable_value(m)` — La valeur d'un `benchmark_index` telle qu'on peut la TRIER (plus grand = meilleur), ou
  - `category_task(cat: str)` — La tâche du catalogue qu'un banc mesure — lecture INVERSE de `TASK_TO_BENCH_CATEGORY`,
  - `leaderboard_repos(cache: str='read')` — Les CLASSEMENTS comme source de DÉCOUVERTE (2026-10-10, demande de Fabien) :
  - `percentile_rank(value, population, key, direction: str='higher')` — Position de `valeur` dans la population de SON banc, en centiles (0-100), ou None.
  - `synchronize(dry_run: bool=False, include_proposed: bool=True, keys=None, cache: str='off')` — Apparie le catalogue (téléchargés + candidats de prospection `proposed:`) aux deux

### Cache HF scopé — dernier recours

Bascule TEMPORAIRE du cache HuggingFace, restaurée en sortie : le levier D de `hf_weights`, réservé à une lib qui n'offre ni `cache_dir=`, ni chemin local, ni variable propre. ⚠ Restaure l'environnement, JAMAIS les fichiers. Aucun emploi aujourd'hui (`RECOURS_ASSUMES` vide, tenu par `tests_hf_cache_routing`)

- **Domicile** : `wama/common/utils/hf_cache.py` · **doc** : [docs/construction/suivi/ROADMAP.md §5b](../construction/suivi/ROADMAP.md)
- **Module** : Bascule SCOPÉE du cache HuggingFace — LA brique anti-fuite (extraite le 2026-08-12).
- **API publique** (1) :
  - `hf_cache_scope(cache_dir)` — Pose env + constantes huggingface_hub sur `cache_dir` LE TEMPS du bloc, puis

### Clé de catalogue ↔ identifiant

UNE lecture de `<source>:<identifiant>` pour tout WAMA : seul le PREMIER segment est la source, reconnue au vocabulaire `ModelSource` (`ollama:qwen3:4b` → `qwen3:4b`, là où un `rsplit` rendait `4b`). `catalog_key` est la tolérance d'ENTRÉE d'une app passée aux clés entières (valeur nue → sa source, `auto` intact). Née au portage F4b de l'imager (2026-09-29) ; consommée par l'imager, l'ETA (`make_key`) et `declaration_for`. ⚠ Une douzaine de conversions à la main vivent encore dans le dépôt (relevé du 29/09) — elles s'y rallient au fil des portages, pas en passe aveugle. `backend_model_id` (2026-10-07) est l'AUTRE lecture : l'identifiant qu'un backend déclare dans `SUPPORTED_MODELS` (dernier segment, règle de `backend_for_model`, écrite quatre fois en ligne jusque-là) — elle seule sépare de `model_id` une clé à trois segments (`github:owner/repo:tag`)

- **Domicile** : `wama/common/utils/model_keys.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F4b](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Clé de CATALOGUE d'un modèle ↔ identifiant dans sa source — UNE sémantique pour tout WAMA.
- **API publique** (5) :
  - `auto_task(value) -> str` — La tâche d'un « auto » borné (`auto:text-to-music` → `text-to-music`), sinon ''.
  - `split_key(value: str) -> tuple` — `(source, identifiant)` — source vide quand la valeur n'est pas une clé de catalogue.
  - `model_id(value: str) -> str` — L'identifiant DANS sa source : `imager:hunyuan-image-2.1` → `hunyuan-image-2.1`. Une
  - `backend_model_id(value: str) -> str` — L'identifiant qu'un backend DÉCLARE dans son `SUPPORTED_MODELS` : le DERNIER segment de la
  - `catalog_key(value: str, default_source: str) -> str` — La clé de catalogue d'une valeur de modèle : une clé est rendue telle quelle, un

### Couverture multi-modèles

Choisit un ENSEMBLE de modèles couvrant des classes (couverture ou spécialisation) ; depuis le 10/10, `models_per_class` en ajoute plusieurs par classe (rappel d'abord) et les départage par leur taux manqué MESURÉ quand le lot entier l'est

- **Domicile** : `wama/common/services/model_coverage.py`
- **Module** : Couverture multi-modèles : quelle COMBINAISON de modèles couvre un ensemble de classes.
- **API publique** (9) :
  - `normaliser_classe(nom: str) -> str` — 'License_Plate' → 'license plate' · 'FACE' → 'face'.
  - `formes_equivalentes(nom: str) -> set` — Toutes les écritures normalisées équivalentes à `nom` (lui-même si aucun alias connu).
  - `classes_couvertes(m, voulues) -> set` — Accès PUBLIC à l'appariement d'alias : sous-ensemble de `voulues` (vocabulaire de
  - `size_of_name(name: str) -> str` — Accès PUBLIC à la lecture de taille (chantier C, 2026-09-20) : un appelant qui affiche ou
  - `size_for_intent(intent) -> str` — Curseur 0-100 → taille préférée ('n' ≤ 20, 's' ≤ 40, 'm' ≤ 60, 'l' ≤ 80, sinon 'x').
  - `segmentation_for_intent(intent) -> bool` — Curseur 0-100 → préférer la segmentation (≥ `SEGMENTATION_THRESHOLD`).
  - `miss_metric(cls: str) -> str` — La métrique de taux manqué pour `cls` — `plate` et `license_plate` en partagent une.
  - `measured_miss_rates(model_keys, cls: str) -> dict` — `{model_key: taux manqué}` des modèles MESURÉS pour `cls` sur une même référence — les
  - `couvrir_classes(classes, *, source: str='', model_type: str='vision', budget_vram_gb: float | None=None, taches_admises=(), preferer_segmentation: bool=False,…` — Ensemble MINIMAL de modèles couvrant `classes`, par recouvrement glouton.

### Découverte de modèles

Découverte unifiée des modèles (apps + sources externes), synchronisée vers le catalogue AIModel. Ollama (2026-10-12) : un manifeste INTERNE du démon (étiquette = empreinte sha256, `is_ollama_runner_alias`) n'est pas un modèle ; seul un relevé du DÉMON (`ollama_listed`) prouve un retrait fait hors de WAMA — la ligne reçoit alors la marque d'une désinstallation (`uninstalled_q`)

- **Domicile** : `wama/model_manager/services/model_registry.py`
- **Module** : Model Registry - Unified model discovery across all WAMA apps and external sources.
- **API publique** (4) :
  - `is_ollama_runner_alias(name: str) -> bool` — Ce nom Ollama désigne-t-il un manifeste INTERNE du démon plutôt qu'un modèle ?
  - `yolopv2_folder() -> Path` — Le dossier de YOLOPv2 — celui que le profil du cam_analyzer lit depuis toujours
  - `class ModelInfo` — Unified model information structure.
  - `class ModelRegistry` — Central registry for all WAMA models.

### Détection par un ensemble de modèles

L'UNION des documents `detections` de plusieurs détecteurs, quelle que soit leur famille (2026-10-10) : les modèles ultralytics ensemble par `Anonymize`, chacun des autres par SON backend (porte `backend_instance_for_key`). Un détecteur image par image n'écrit que `detect_frames` : la boucle sur le média est commune (`FrameDetectionBackend` — SAM3, EgoBlur, RT-DETR). Consommé par l'anonymizer et par le banc de rappel (`bench --task detect-recall`), qui mesure par le MÊME chemin

- **Domicile** : `wama/common/services/detection_ensemble.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : Détection par un ENSEMBLE de modèles — l'union de leurs documents `detections` (2026-10-10).
- **API publique** (3) :
  - `engine_of(model_key: str) -> str` — Le moteur DÉCLARÉ au catalogue (`composition.runtime.engine`) — '' si inconnu.
  - `class DetectorSet` — Les détecteurs d'un ensemble, CHARGÉS UNE FOIS puis appliqués média par média
  - `detect_with_models(models, *, user=None, source_dir=None, destination_dir=None, **kwargs) -> dict` — Le document `detections` de l'ENSEMBLE `models` sur UN média — `DetectorSet` à usage

### Indice de qualité a priori

Ordonne les modèles autrement que par la taille (params EFFECTIFS √(totaux×actifs), contexte, quantif.). DÉFAUTS MESURÉS (2026-10-28) : une mesure sans référence qui prend un modèle en défaut (même entrée, mêmes réglages qu'un autre modèle) le PROPOSE (`propose_defect`), un administrateur valide, le défaut vit sur la ligne du catalogue (manifeste `model`, `quality.defect`) — GRISÉ au select avec sa raison et sorti du tirage automatique, comme un modèle sans backend

- **Domicile** : `wama/model_manager/services/model_quality.py`
- **Module** : Indice de qualité A PRIORI d'un modèle — pour choisir autrement que « le plus gros qui tient ».
- **API publique** (7) :
  - `params_in_billions(label: str) -> float | None` — '36.0B' → 36.0 · '8.0B' → 8.0 · '' → None. Tolère 'M' (millions).
  - `apriori_quality_index(*, params_b: float | None, context_length: int | None=None, quantization: str='', params_active_b: float | None=None) -> float | None` — Indice a priori, croissant avec la capacité. None si le signal principal manque.
  - `declared_prior(model_key: str) -> float | None` — L'indice a priori DÉCLARÉ pour ce modèle (`DECLARED_PRIORS`), None sinon.
  - `declared_defect(model) -> tuple[str, str] | None` — (libellé court, raison) du défaut MESURÉ et VALIDÉ que la ligne du catalogue porte
  - `defect_evidence(model_key: str) -> list` — Les cas où une mesure sans référence prend `model_key` en défaut : sur le MÊME audio (son
  - `propose_defect(model_key: str)` — PROPOSE à un administrateur le défaut que les mesures établissent pour `model_key` — un
  - `active_params_b(params_b: float | None, total_experts, active_experts) -> float | None` — Paramètres réellement activés par jeton, en milliards — axe de COÛT, pas de qualité.

### Installation de modèles

Pipeline accept→download→register : télécharge au bon endroit puis enregistre au catalogue. UNE route depuis l'extérieur, `request_install` (bouton, assistant, `pull_model <clé|org/dépôt|nom Ollama>` — un nom se PROPOSE d'abord (`seed_hf_search`, `seed_ollama_candidate`) —, marcheur d'app `install_requirements` ; garde d'espace disque, tâche Celery, journal — seule à appeler `dispatch_install`) ; `AIModel.is_installable` en dit la règle à la page. Un pilote INTERNE (`install_from_spec`), un par source : ollama, hf, yolo, github (poids d'une VERSION GitHub, tag exact + empreinte épinglée, disposition calquée sur HF, 2026-10-07), files (les fichiers qu'une app DÉCLARE, chacun avec son ORIGINE parmi les sources déclarées — dépôt du Hub figé au commit, version GitHub, adresse fixe d'une source « poids » — taille et empreinte épinglées, 2026-10-11 : CodeFormer, MuseTalk, enhancer, Face Analyzer, DeepFace le 12/10, MuScriptor le 16/10 — le jeton d'un dépôt du Hub à accès contrôlé n'est envoyé qu'aux origines `huggingface` ; la désinstallation retire ces fichiers-là seulement, `remove_declared_files`) ; `download_asset` = le téléchargement contrôlé commun aux pilotes à fichier (empreinte d'un fichier en place : `provenance.sha256_of`). Dépôt à ACCÈS CONTRÔLÉ (`AIModel.gated`) : le jeton est celui du compte qui lance (`api_keys.download_token`), sinon celui de l'instance (`HF_TOKEN`, `.env`). Route `library` (`install_library`) : PyPI par nom, pin exact — refuse URL, `git+`, `file:`, `-e` et contrainte lâche ; `constraints.pip` (pins passés par `-c`) et `constraints.no_deps` (installer SANS les dépendances quand leur résolution déplacerait le venv, 2026-10-01 ; pendant backend : `PIP_NO_DEPS`) ; voie VENDOR pour un dépôt épinglé au commit. AUCUNE DÉRIVE (`AGENTS.md`, 2026-10-16) : rien ne télécharge un poids ni ne lance pip à côté — contrôle `tests_install_route`, budget des dérives existantes qui ne peut que descendre

- **Domicile** : `wama/model_manager/services/model_installer.py`
- **Module** : Pipeline accept→download→register — installation de modèles dans WAMA.
- **API publique** (49) :
  - `pull_ollama_model(name: str, timeout: int=1800, progress=None)` — Télécharge un modèle Ollama via le démon LOCAL (`POST /api/pull`, stream).
  - `delete_ollama_model(name: str, timeout: int=60) -> dict` — Désinstalle un modèle Ollama (`DELETE /api/delete`) — libère sa place sur le volume.
  - `pull_hf_model(repo_id: str, category: str, family: str | None=None, dry_run: bool=False, allow_patterns=None, progress=None, token=None)` — Télécharge un modèle HuggingFace DANS LE BON DOSSIER (catégorie WAMA) via l'API officielle
  - `duplicate_weight_files(files) -> list` — Fichiers de poids à NE PAS tirer parce que leur jumeau `.safetensors` existe — même
  - `format_duplicates(repo_id: str) -> list` — Les jumeaux de format d'un dépôt HF — un appel HTTP, la règle vient de
  - `weight_for_spec(spec: dict)` — Poids en Go de ce qu'un descripteur d'installation va TIRER, ou None si indéterminable.
  - `components_of_files(files, *, composition=None, allow_patterns=None) -> dict` — Poids PAR COMPOSANT d'un inventaire de fichiers — dérivation PURE, aucun réseau.
  - `components_for_spec(spec: dict, *, files=None) -> dict` — Poids par composant de ce qu'un descripteur désigne — `{}` si indéterminable.
  - `yolo_task_of(name: str) -> str` — Tâche (`ModelTask`) d'un poids YOLO, déduite du suffixe de son nom — `detect` par défaut.
  - `pull_yolo_weights(name: str, timeout: int=600, dry_run: bool=False)` — Télécharge des poids YOLO OFFICIELS (assets GitHub Ultralytics, URL stable
  - `github_release_error(ref) -> str | None` — Motif de refus d'une version désignée `owner/repo:tag`, ou None (pur, aucune I/O).
  - `github_spec_error(spec: dict)` — Motif de refus d'un descripteur `github`, ou None — pendant de `vendor_spec_error`.
  - `github_asset_url(spec: dict) -> str` — Adresse de téléchargement de l'asset, dérivée de la source déclarée `github` (comme
  - `github_release_dir(spec: dict) -> str` — Dossier du modèle : `<catégorie>/<famille ou tag>/github--owner--repo/<tag>`.
  - `pull_github_asset(spec: dict, timeout: int=600, dry_run: bool=False) -> dict` — Télécharge l'asset d'une version GitHub DANS LE BON DOSSIER (cf. l'en-tête du pilote).
  - `declared_origin_error(origin) -> str | None` — Motif de refus de l'ORIGINE d'un fichier déclaré, ou None (pur, aucune I/O).
  - `declared_files_error(spec: dict) -> str | None` — Motif de refus d'un descripteur `files`, ou None — pur : l'installation et la pesée
  - `declared_file_url(origin: dict) -> str` — Adresse d'un fichier déclaré, DÉRIVÉE de sa source déclarée — jamais écrite en dur.
  - `declared_files_present(install_dir, files) -> bool` — Tous les fichiers déclarés sont-ils à leur place ? (présence, sans relire l'empreinte —
  - `remove_declared_files(model, include_shared: bool=False) -> dict` — Le pendant de `pull_declared_files` pour la désinstallation : retire EXACTEMENT les
  - `pull_declared_files(spec: dict, timeout: int=600, dry_run: bool=False, token: str | None=None) -> dict` — Les fichiers qu'une app DÉCLARE, posés SOUS son dossier (`target_dir`), chacun tiré de
  - `download_asset(url: str, target: str, *, timeout: int=600, min_bytes: int=0, sha256: str='', proxies=None, headers=None) -> dict` — Télécharge UN fichier publié (asset de version GitHub…) vers `target`, sans jamais laisser
  - `register_after_install()` — Re-synchronise le catalogue `AIModel` pour que le modèle fraîchement installé apparaisse.
  - `replaced_model(cand)` — (nom Ollama de l'ancien modèle, espace qu'il rendra en Go) pour un candidat successeur,
  - `disk_space_guard(ref: str, *, reclaim_gb: float=0.0, force: bool=False, needed_gb: float | None=None)` — Refuse une installation qui saturerait le volume. Retourne None si l'installation peut
  - `similar_model_keys(key: str, limit: int=3) -> list[str]` — Les clés du catalogue (propositions comprises) qui désignent le MÊME dépôt ou le même nom
  - `variant_owner_keys(repo: str) -> list[str]` — Les propositions dont `repo` est une VARIANTE quantisée (`prospect.quant_variants`) — la clé
  - `request_install(model_key: str, *, force: bool=False, variant_ref: str='', variant_file: str='', user=None, via: str='') -> dict` — DEMANDE d'installation par CLÉ — corps unique du geste « Installer » : choix de variante,
  - `dispatch_install(task, row, *, user_id=None, via='')` — SEUL point de dispatch des deux tâches d'installation : ouvre l'événement DATÉ du journal,
  - `install_candidate(cand, progress=None, token=None, owner=None) -> dict` — Séquence d'installation d'un CANDIDAT de prospection Ollama — corps unique, appelé par
  - `weights_dir_of(model, index: dict | None=None) -> Path | None` — Dossier des POIDS d'une ligne de catalogue installée, ou None s'il ne se désigne pas.
  - `rows_depending_on(model, target: Path, index: dict | None=None) -> tuple[list, list]` — Les AUTRES lignes installées que retirer `target` toucherait — `(sharing, dependents)`.
  - `uninstall_model(model_key: str, include_shared: bool=False, via: str='') -> dict` — DÉSINSTALLE un modèle du catalogue : retrait des POIDS uniquement, jamais du backend
  - `forget_in_corpus(model_keys) -> None` — Le corpus de manifestes SUIT la désinstallation, comme il suit l'installation
  - `spec_for_catalog_row(model) -> dict | None` — Spec d'installation DÉRIVÉ d'une ligne de catalogue non téléchargée — le geste « Installer »
  - `patterns_from_composition(composition) -> list | None` — `allow_patterns` DÉRIVÉS d'une `composition` déclarée (manifeste `model`,
  - `install_owner(user_id)` — À qui revient un modèle que l'installation fait NAÎTRE (`ROADMAP §29` étape 3, décision de
  - `install_from_spec(spec: dict, token=None, owner=None) -> dict` — Point d'entrée UNIQUE d'installation — DESCRIPTEUR déclaratif au lieu de mécanismes
  - `record_provenance(spec: dict, res: dict, owner=None) -> dict` — Après un téléchargement réussi : sync du catalogue, puis provenance des lignes apparues.
  - `queue_benchmarks(res: dict, appeared_keys) -> None` — Met en file le BANC TIERS des modèles qu'on vient d'installer (2026-10-10).
  - `pip_spec_error(spec: str)` — Motif de refus d'un spécificateur pip, ou None s'il passe les verrous syntaxiques.
  - `pip_constraint_errors(constraints) -> list` — Motifs de refus des contraintes pip — mêmes verrous qu'un spécificateur.
  - `pip_install_packages(packages, timeout: int=1800, no_deps: bool=False, constraints=None) -> dict` — Installe des paquets pip dans le venv courant — pour rendre un backend disponible quand un
  - `ensure_backend_deps(backend_cls, timeout: int=1800) -> dict` — Installe les paquets manquants d'un backend (classe `BaseModelBackend`) si nécessaire.
  - `simuler_installation(spec: str, timeout: int=300, constraints=None, no_deps: bool=False) -> dict` — Ce qu'une installation ENTRAÎNERAIT — `pip install --dry-run`, LECTURE SEULE.
  - `install_library(key: str, apply: bool=False, via: str='') -> dict` — Installe UNE librairie depuis son registre (`common.models.Library`) — la JONCTION
  - `library_requirers(key: str, dist_name: str='') -> dict` — Qui a encore BESOIN de la librairie `key` (distribution `dist_name`, la clé par défaut) :
  - `uninstall_library(key: str, apply: bool=False, via: str='') -> dict` — DÉSINSTALLE une librairie du registre — le pendant d'`install_library` (2026-10-23, demande de
  - `install_requirements(app_key: str, apply: bool=False) -> dict` — Le MARCHEUR d'app (« application = modèles + librairies », reste ③ de la route

### Journal des installations

Date chaque installation et désinstallation (modèle, librairie) avec son issue et sa VOIE (model manager, assistant, marcheur d'app, ligne de commande), aux points uniques de la route ; couche « Installations » du calendrier, inscrite par `register_instance_layer`. Best-effort : n'échoue jamais une installation

- **Domicile** : `wama/model_manager/services/install_history.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md](../construction/ia/WAMA_MEMORY.md)
- **Module** : Journal DATÉ des installations — l'écriture (`opened`/`record`) et la couche du calendrier.
- **API publique** (5) :
  - `opened(kind, key, *, name='', action='install', via='')` — Ouvre un événement `RUNNING` ; le bloc remplit `outcome` avec le résultat du driver.
  - `record(kind, key, *, name='', action='install', via='', result=None, started_at=None)` — Un événement déjà TERMINÉ (désinstallation : un geste court et synchrone).
  - `queued(kind, key, *, name='', via='')` — Ouvre l'événement AU DISPATCH, avec sa voie — la tâche le reprendra (`resumed`).
  - `resumed(kind, key, *, name='')` — Reprend, dans la tâche, l'événement ouvert au dispatch (ou en ouvre un sans voie).
  - `calendar_events(start, end)` — Les installations de `[start, end)` — couche de l'INSTANCE (inscrite par `apps.ready`).

### Mesure interne des modèles

Étage 3 qualité : ce que WAMA a MESURÉ elle-même contre une référence humaine (`ResultEvaluation`), agrégé par modèle — taux de CORPUS, échelle nommée `internal_<métrique>_<protocole>`, sens, rang parmi les modèles mesurés sur les MÊMES références, accumulation dite. RABATTUE À LA LECTURE (jamais écrite au catalogue) : elle n'entre dans aucun tri tant que Q3 n'est pas tranchée, et `sync_benchmarks`, qui remplace `benchmark_meta`, ne peut pas l'effacer

- **Domicile** : `wama/model_manager/services/internal_quality.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : Étage 3 de l'échelle des signaux — la MESURE INTERNE d'un modèle (`WAMA_QUALITE.md §4.1`, ⑧).
- **API publique** (2) :
  - `scale_name(metric: str, protocol: str) -> str`
  - `internal_scores(model_keys: Optional[Iterable[str]]=None) -> Dict[str, List[dict]]` — Les échelles internes de chaque modèle mesuré : `{model_key: [échelle, …]}`.

### Mise en forme AJUSTÉE d'un document (fond en sections)

Le fond Markdown découpé en sections (règle de la brique `text_sections`, tenue sous V8), un PLAN d'après la part de mots changés par section (`text_metrics`) : un bout de phrase se remplace dans la forme sans modèle, une section très modifiée se remet en forme seule, une structure qui change refait tout. Base = les fichiers de révision GARDÉS + la photo de ce que le process surveille (`ctx.previous_snapshot`) ; repères `data-wama-section` ; réponse de modèle sans « ```html », avec son charset. Montrée au rôle `codegen` pour le process qu'une surface rejoue (2026-10-13)

- **Domicile** : `wama/common/utils/document_sections.py` · **doc** : [docs/construction/suivi/ROADMAP.md §21.5](../construction/suivi/ROADMAP.md)
- **Module** : Le FOND en sections et sa FORME qui en garde les repères — la mise en forme AJUSTÉE d'un document (2026-10-13, `ROADMAP §21.5`). Décision de Fabien : *« remise en forme par section si la section est complètement modifiée, forme réutilisée si seulement un bout de phrase est modifié — la quantité de modifications définit le process d'ajustement »*.
- **API publique** (17) :
  - `split_sections(text: str) -> list` — Les sections d'un texte, sans rien perdre : leur concaténation EST le texte. Jumelle de
  - `plain_text(line: str) -> str` — Le texte LU d'une ligne Markdown, sans sa syntaxe : ce qu'un rendu HTML en affiche.
  - `class SectionChange`
  - `class LayoutPlan`
  - `anchored_sections(soup) -> dict` — `{rang: élément}` des sections repérées d'un HTML déjà analysé (BeautifulSoup).
  - `plan_layout_update(previous_text: str, text: str, previous_html: str, *, ceiling: float=PATCH_CEILING, language: str | None=None) -> LayoutPlan` — Ce que demande le passage de `previous_text` à `text`, quand `previous_html` est la forme
  - `patch_section(tag, old: str, new: str) -> bool` — Reporte dans l'élément `tag` (une section rendue) les changements de TEXTE de `old` à `new`,
  - `section_relayout_messages(index: int, new_text: str, current_html: str, *, style: str='', language: str='') -> list` — Les messages qui demandent au modèle de remettre en forme UNE section, en reprenant la
  - `apply_plan(previous_html: str, plan: LayoutPlan, ask, *, style: str='', language: str='', console=None) -> str | None` — Le HTML ajusté selon `plan` (mode `adjust`), à partir de `previous_html`.
  - `adjust_layout(basis, text: str, ask, *, style: str='', language: str='', console=None) -> str | None` — LE geste d'une glu de mise en forme : le HTML de `text`, AJUSTÉ depuis la dernière mise
  - `full_layout_instruction(text: str) -> str` — La règle à ajouter à la consigne d'une mise en forme COMPLÈTE : les repères de sections
  - `full_layout_messages(text: str, *, style: str='', language: str='', kind: str='') -> list` — Les messages d'une mise en forme COMPLÈTE — le jumeau de `section_relayout_messages` :
  - `finish_document(reply: str, text: str, console=None) -> str` — Le document rendu par le modèle, prêt à écrire : sans le raisonnement ni la clôture de code
  - `extract_document(reply: str) -> str` — Le document d'une réponse de modèle : sans bloc de raisonnement (`<think>`), et sans la
  - `with_charset(html: str) -> str` — `html` déclarant `<meta charset="utf-8">` : un document servi sans jeu de caractères
  - `class LayoutBasis`
  - `adjustment_basis(app_id: str, item, ctx, *, source_field: str, output_field: str) -> LayoutBasis | None` — Le fond et le rendu de la DERNIÈRE mise en forme, pris dans les fichiers de révision gardés

### Prospection de modèles

Veille déterministe HuggingFace/Ollama + évaluation multi-agents (dry-run) ; versions GitHub lues sur `github_api` (fichiers, licence et facteur DÉCLARÉS, empreinte lue ou MESURÉE) pour le scout (`--github owner/repo:tag`, 2026-10-07) ; les CLASSEMENTS des bancs (tâche et rang, `seed_benchmark_candidates`) et les SUCCESSEURS déclarés par l'auteur (`new_version`, `seed_hf_successors`) sont des sources de candidats (2026-10-10)

- **Domicile** : `wama/model_manager/services/prospector.py` · **doc** : [wama/model_manager/PROSPECTION_PIPELINE.md](../../wama/model_manager/PROSPECTION_PIPELINE.md)
- **Module** : Prospection de modèles — version DÉTERMINISTE (sans LLM, sans scraping).
- **API publique** (33) :
  - `hf_task_to_wama(pipeline_tag: str, tags=())` — (tâche NÔTRE, model_type) d'un dépôt HF, d'après son tag de pipeline ET les tags de sa
  - `card_facts(pipeline_tag: str, tags=(), card_data=None, library_name: str='') -> dict` — Ce que la CARTE HuggingFace dit d'un modèle, traduit en faits WAMA — MÉCANIQUEMENT, jamais
  - `prospect_hf(task: str, limit: int=15, library: str | None=None, min_downloads: int=0, search: str | None=None, sort: str='downloads')` — Top modèles HF d'une `task` (par téléchargements), avec flag « déjà dans WAMA ».
  - `local_revision(snapshot_root)` — Le dossier dont les chemins de `local_inventory` sont RELATIFS : la révision la plus
  - `local_inventory(snapshot_root)` — `[(chemin relatif, taille)]` d'un modèle INSTALLÉ — le jumeau LOCAL de `_siblings`
  - `installed_weights_complete(snapshot_root) -> bool` — Un modèle installé porte-t-il des POIDS complets ? — LE jugement « téléchargé » (2026-09-28).
  - `safetensors_facts(path)` — `{'params': nombre de paramètres, 'dtypes': [...]}` lus dans l'EN-TÊTE seul d'un
  - `precision_of_files(revision, files_by_role) -> dict` — `{rôle: {'params', 'dtypes'}}` — la PRÉCISION de chaque composant, lue dans les en-têtes
  - `remote_precision(repo_id: str, files_by_role) -> dict` — JUMEAU DISTANT de `precision_of_files`, même forme `{rôle: {params, dtypes,
  - `quantized_variants(repo_id: str, limit: int=5) -> list[dict]` — Dépôts HF dérivés QUANTISÉS d'un modèle (GGUF/FP8/4-8bit/AWQ…), triés par téléchargements.
  - `analyze_license(repo_id: str, license_id: str='', base_model=None, _profondeur: int=0)` — Verdict de COMPATIBILITÉ de licence d'un candidat, pour AFFICHAGE sur la card —
  - `install_options(cand) -> dict` — Options d'installation EXPLICITES d'un candidat HF : poids pleins + variantes quantisées,
  - `needs_variant_choice(cand) -> bool` — Le candidat n'a-t-il AUCUN choix par défaut ? — vrai quand ses options ne portent pas de
  - `spec_for_choice(cand, variant_ref: str, variant_file: str | None) -> dict | None` — Le SPEC d'installation qui respecte le choix validé par l'utilisateur, ou None si le choix
  - `catalogue_repos(rows) -> set` — Dépôts du Hub que des lignes de catalogue PORTENT, en minuscules : celui d'où viennent
  - `seed_hf_candidates(limit: int=12, min_downloads: int=1000, tasks=None) -> dict` — Candidats `is_proposed` depuis la bibliothèque HuggingFace — pendant HF de la découverte
  - `class HubRateLimited(Exception)` — Le Hub refuse encore (429) après l'attente qu'il demande : la passe s'arrête, et ce qu'elle
  - `seed_benchmark_candidates(per_category: int=BENCH_CANDIDATES_PER_CATEGORY, tasks=None, cache: str='read') -> dict` — Candidats `is_proposed` tirés des CLASSEMENTS (2026-10-10, demande de Fabien) : pour chaque
  - `hf_successor(repo: str, max_depth: int=5, api=None)` — `(chaîne, info du dernier)` des NOUVELLES VERSIONS qu'un auteur déclare sur la carte de son
  - `seed_hf_successors(workers: int=8) -> dict` — Candidats de MISE À JOUR des modèles Hugging Face installés, désignés par leur auteur
  - `enqueue_after_prospection() -> dict` — La suite de « Prospecter » : bancs tiers PUIS jury LLM, dans cet ordre (ex-
  - `run_prospection() -> dict` — Le verbe « Prospecter » — corps UNIQUE du bouton du model manager et de l'outil
  - `seed_candidate_from_manifest(manifest: dict) -> dict` — Écrit/rafraîchit un CANDIDAT de prospection depuis un manifeste `model` — le chemin du
  - `seed_yolo_candidate(name: str) -> dict` — Candidat de prospection pour des poids YOLO OFFICIELS demandés PAR LEUR NOM.
  - `seed_ollama_candidate(name: str) -> dict` — Candidat de prospection pour un modèle Ollama demandé PAR SON NOM — le pendant de
  - `github_release(ref: str)` — La version `owner/repo:tag` telle que l'API GitHub la publie (dict), `{}` si elle
  - `github_release_license(release: dict) -> str` — Licence DITE par le texte de la version (« License: CC BY 4.0 »), sinon '' — jamais
  - `github_release_scale(release: dict)` — Facteur que le texte de la version DÉCLARE (« Scale: 4 »), sinon None — jamais déduit du
  - `pinned_github_asset(ref: str, asset: str, release: dict=None) -> dict` — {'asset', 'size', 'sha256', 'measured'} de l'asset d'une version, ou {'error'}.
  - `github_spec_from_manifest(manifest: dict) -> dict` — Descripteur `github` d'un manifeste `model` de source `github`, empreinte ÉPINGLÉE —
  - `named_repo(query: str)` — Le dépôt HF qu'une requête DÉSIGNE — URL de page (`https://huggingface.co/org/nom`, avec ou
  - `seed_hf_search(query: str, limit: int=10, max_retenus: int=5) -> dict` — Prospection CIBLÉE : cherche `query` dans les noms de dépôts HF (toutes tâches de
  - `apply_recommendations(candidates, source: str, task: str)` — Crée/maj des entrées `recommended` dans le catalogue pour les candidats NOUVEAUX (pas déjà

### Provenance de modèle

Identité chez l'éditeur (licence, auteur, plateforme, publications arXiv de la carte), posée VIA le manifeste ; les publications s'affichent dans l'onglet « À propos » de chaque app (modèles de ses selects de catalogue, 2026-10-10)

- **Domicile** : `wama/model_manager/services/provenance.py`
- **Module** : Identité d'un modèle chez son éditeur — et pose de cette identité PAR LE MANIFESTE.
- **API publique** (7) :
  - `huggingface_identity(repo_id: str) -> Optional[dict]` — `{license, author, platform_ref, gated}` lu sur la carte du dépôt, ou None si injoignable.
  - `arxiv_ids(tags) -> list` — Les identifiants arXiv qu'une carte Hugging Face rattache au modèle, dans son ordre.
  - `ollama_identity(name: str) -> Optional[dict]` — Identité d'un modèle Ollama. La plateforme n'expose ni licence ni auteur exploitables par
  - `cloud_identity(item: dict) -> Optional[dict]` — Identité d'un modèle DISTANT : le dépôt HuggingFace que le fournisseur sert, quand il le
  - `identity_for_spec(spec: dict) -> Optional[dict]` — Identité déductible du descripteur d'installation (`install_from_spec`).
  - `set_identity(model_key: str, identity: dict, *, capabilities: dict=None, engine: str=None, composition: dict=None, apply: bool=True, export: bool=True) -> dict` — Pose l'identité — et les capacités DÉCLARÉES — sur un modèle DU CATALOGUE, en passant
  - `record_after_install(spec: dict, appeared_keys, owner=None) -> dict` — Après installation + sync : pose l'identité sur les modèles qui viennent d'APPARAÎTRE.

### Sonde vision

Décrit une image via un modèle multimodal Ollama local — le SEUL client de vision depuis le 2026-10-20 : le Describer (images, images-clés de vidéo) y passe, avec le banc, le smoke UI, les fichiers de référence et les outils de l'assistant ; son chargement se mesure à la carte (`ollama_host.measured_load`). Par l'appel COMMUN `ollama_chat` depuis le 2026-10-21, à la TEMPÉRATURE de la card (vide = celle du modèle)

- **Domicile** : `wama/model_manager/services/vision_probe.py`
- **Module** : Sonde vision via Ollama — décrire une image avec un modèle multimodal local (gemma4:12b, e4b…). Sert au bench (d) : comparer des modèles candidats sur de vraies images WAMA, en français.
- **API publique** (1) :
  - `describe_image_ollama(image_path: str, model: str='', prompt: str | None=None, timeout: int=180, keep_alive: str | None=None, num_predict: int | None=None, tem…` — Décrit une image via un modèle vision Ollama LOCAL. Retourne {'ok', 'description'|'error'}.

### Surfaces — pages d'édition composées de briques

Une page d'édition DÉCLARÉE par l'app (emplacements, champs lus, champ écrit et sa validation, process que l'écriture périme), servie par des vues COMMUNES et composée de briques UI universelles — déplaçables, redimensionnables (gridstack), historique commun. 1ʳᵉ surface : la correction des détections de l'anonymizer (2026-10-10). Registre `ui_bricks` = le catalogue des briques. 2ᵉ (2026-10-13) : le fond du Writer — un champ FICHIER s'édite comme texte (règles communes), la surface se déclare au manifeste (facette `surfaces`) et se génère ; refus 409 sur état périmé et verrou doux pour toutes les surfaces ; la VERSION écoutée d'un média lu gardée sur la card (`sources_setting`, 2026-10-22) ; brique « Versions » : reprendre le texte d'une révision GARDÉE, un geste d'édition annulable. 3ᵉ (2026-10-15) : la partition du composer — champs ALTERNATIFS (sortie de l'un de deux process), briques `score_view` (gravure abcjs, notes jouées colorées, glisser = transposer) et `media_transport`, sur l'AXE partagé de la surface (`ctx.axis()`). 2026-10-18 : chaque surface DÉCLARE son élément témoin (`witness`), sur lequel le nocturne l'ouvre et capture ses briques — les vignettes du catalogue (`thumbnail`), qui montre aussi les composants SYSTÈME (domaine `UI_DOMAIN`). 2026-10-21 : disposition par compte, FIGÉE par défaut pour tous ; deux ZONES (`BrickSlot.zone`) — la grille et la COLONNE du volet droit, une brique passant de l'une à l'autre. 2026-10-26 : des briques EMPILÉES en un panneau (`stacks`, affichage seul — le transport, la ligne de temps et l'écriture fixés ensemble) et un panneau ÉPINGLÉ à un bord de la fenêtre (haut, bas, gauche, droite : la page se referme derrière lui), gardés avec la disposition — `WAMA_VOLETS §3-ter`, scénario `common.surface_stack`. 2026-10-28 : la DISPOSITION sort du noyau en brique commune (`wama-brick-layout.js`), pour que les pages d'apps la montent sans le noyau d'édition ; tout panneau s'ouvre DANS UNE AUTRE FENÊTRE (déplacé, pas recréé ; gestes relayés à la page)

- **Domicile** : `wama/common/surfaces.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : SURFACES et BRIQUES UI — le registre (2026-10-10, ouverture du chantier SURFACES).
- **API publique** (13) :
  - `thumbnail_path(key: str)` — Le fichier de la vignette d'une brique (qu'il existe ou non).
  - `thumbnail(key: str) -> Optional[dict]` — La vignette d'une brique — `{'url', 'taken_at'}`, ou None tant qu'aucune capture n'existe
  - `validate_text(value) -> str` — Le texte d'un champ fichier édité, assaini : une chaîne, fins de ligne `\n`, plafonnée.
  - `source_file(path: str) -> Optional[str]` — Le fichier SOURCE d'un chemin nommé comme une page le nomme — un gabarit comme
  - `class UIBrick`
  - `class BrickSlot` — Une brique placée sur une surface : position et taille PAR DÉFAUT (l'utilisateur les
  - `class Surface`
  - `clean_layout(surface: Surface, payload) -> dict` — La DISPOSITION d'un utilisateur pour une surface, validée (2026-10-21, demande de Fabien :
  - `register_brick(brick: UIBrick) -> UIBrick`
  - `register_surface(surface: Surface) -> Surface`
  - `surface(app: str, key: str) -> Optional[Surface]`
  - `surfaces_of(app: str) -> list`
  - `load_all() -> dict` — Importe les déclarations de surfaces des apps installées (une fois par processus).

### Sélection de modèle

Choisit UN modèle : capacités, entrées, priorités, budget VRAM, qualité — parmi ceux que le compte voit (`user=`, `ROADMAP §29` : sans compte, le système seul)

- **Domicile** : `wama/model_manager/services/model_selector.py` · **doc** : [docs/construction/ui/INPUT_MODEL_MATCHING.md](../construction/ui/INPUT_MODEL_MATCHING.md)
- **Module** : Sélection intelligente de modèles — centralisée pour toutes les apps WAMA.
- **API publique** (12) :
  - `get_free_vram_gb() -> Optional[float]` — VRAM libre (Go) du GPU le plus libre, MOINS ce que d'autres process ont réservé.
  - `is_cloud(model) -> bool` — Ce modèle s'exécute-t-il CHEZ UN TIERS ? Lit le champ DÉCLARÉ (`AIModel.execution`),
  - `abilities_of(model) -> list` — Libellés des aptitudes déclarées par `model`, lus dans `ModelAbility` (+ sa spécialité).
  - `domain_q(domain: dict)` — Le filtre (`Q`) d'un DOMAINE déclaré au schéma d'une app (`options_query` : `task`, une ou
  - `intent_choice(candidates, quality: dict, cost: dict, quality_intent, key=id)` — Le candidat que le CURSEUR rapide/qualité désigne — la règle de TOUTES les apps :
  - `select_model(source: Optional[str]=None, *, model_type: Optional[str]=None, requires: Optional[List[str]]=None, classes: Optional[List[str]]=None, prefer_loade…` — Choisit le meilleur `AIModel` pour `source` (valeur ModelSource), ou None.
  - `list_models(source: str, downloaded_only: bool=True, user=None) -> List[dict]` — Liste des modèles d'une source (dicts to_dict — description courte/longue + vram), ceux
  - `matches_inputs(model, available_inputs=None, task: Optional[str]=None, consumes=None) -> bool` — Ce modèle est-il utilisable avec les entrées dont on dispose ? (appariement entrée↔modèle)
  - `full_gpu_budget_gb(headroom_gb: float=4.0) -> Optional[float]` — Budget VRAM au-delà duquel un modèle imposerait de l'offload CPU.
  - `select_model_id(source: Optional[str]=None, requires=None, requested: Optional[str]=None, fallback: Optional[str]=None, avoid_offload: bool=True, modality: Opt…` — Tirage d'un modèle pour une app, rendu comme un `model_id` nu (sans le préfixe "source:").
  - `get_registry_models(source: Optional[str]=None, allowed_ids=None, downloaded_only: bool=False, requires=None, modality: Optional[str]=None, task: Optional[str]…` — (choices, info) pour le <select> d'une app, PILOTÉ par le registre AIModel (verrou n°1).
  - `describe_model(model_key: str, tier: str='short') -> str` — Description d'un modèle. tier='short' → une ligne (fallback long) ; 'long' → paragraphe.

## Qualité & auto-amélioration

### Actions programmées (le QUAND)

Programmer le lancement d'une card, d'une sélection ou d'un lot — menu commun, pastille sur la card, fichier batch (`--when`/`--at`) — depuis UN schéma (`schedule_params`). L'heure venue, `execute_tool` au nom de l'utilisateur (même porte que l'assistant) ; placement hors plages RÉSERVÉES ; le ▶ annule sans confirmation ; jamais de relance d'un élément lancé à la main entre-temps

- **Domicile** : `wama/common/services/scheduled_actions.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Actions PROGRAMMÉES — le QUAND du calendrier, étape 3 (2026-09-28). Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13 ; la vue : `WAMA_MEMORY.md §9bis.1`.
- **API publique** (18) :
  - `class ScheduleError(ValueError)` — Une programmation refusée — le message est montré à l'utilisateur.
  - `schedule_params()` — Le schéma de programmation (liste de `Param`).
  - `parse_moment(value)` — Instant demandé → aware, ou None. Formes acceptées : ISO 8601 (avec ou sans fuseau), la
  - `read_schedule(data)` — `(placement, instant demandé)` depuis des valeurs NOMMÉES PAR LE SCHÉMA (`when`, `at`).
  - `reserved_window_at(moment)` — La plage réservée qui CONTIENT `moment`, ou None.
  - `overlapping_window(start, end)` — La première plage réservée qui CHEVAUCHE `[start, end)`, ou None.
  - `quiet_hours(*, refresh=False)` — `(heures creuses, 'measured' | 'declared')` — heures LOCALES 0-23.
  - `hours_label(hours)` — « 05 h – 11 h » : les tranches contiguës d'un ensemble d'heures (le tour de minuit compris).
  - `place(placement, requested, now, *, seconds=0, queue_free=None)` — `(instant, plage en conflit)` d'une programmation d'une tâche de `seconds` secondes.
  - `start_tool_for(app, prefix='')` — Outil `start_*` d'une FILE, ou None. La file d'un domaine a le sien
  - `target_of(tool)` — `(clé d'app, modèle, argument d'identifiant)` d'un outil `start_<app>`.
  - `schedule_items(user, tool, ids, placement, requested=None, *, now=None)` — Programme le lancement des éléments `ids` par `tool`. Rend `{actions, conflict}`.
  - `reschedule(user, action_id, placement, requested=None, *, now=None)` — Déplace une programmation. Même règle de placement ; un conflit ne change rien.
  - `schedule_from_batch(user, app, route_name, batch_id, *, now=None) -> dict | None` — Programme les lignes d'un FICHIER BATCH qui portent `when` / `at` (`BATCH_FORMAT.md`).
  - `cancel(user, action_id) -> bool`
  - `cancel_for_item(app, object_id) -> int` — Le ▶ a lancé l'élément : sa programmation n'a plus d'objet (décision de Fabien : sans
  - `active_for(user)`
  - `dispatch_due(now=None) -> dict` — Lance ce qui est dû. Rend `{dispatched, skipped, failed}`.

### Ajout au RAG (geste explicite)

Bouton dans l'INSPECTEUR + page « Mon RAG » ; texte pris au schéma canonique, aucune ligne par app. Pas de balayage : l'entrée au RAG est un geste, par décision. Surfaces : inspecteur, menu « … » des cards, arbre de fichiers et assistant (outils `add_item_to_rag` / `add_file_to_rag`) — UN endpoint, deux gestes de la brique (`memory.index.add_item_to_rag` / `add_file_to_rag`, 2026-10-14) : un élément par son texte canonique, un FICHIER remonté à l'élément dont il est la sortie, sinon lu s'il porte déjà du texte (`reference_comprehension.read_document_text`) et refusé, en le disant, s'il n'en porte pas

- **Domicile** : `wama/common/static/common/js/wama-inspector.js` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7ter](../construction/ia/WAMA_MEMORY.md)

### Ancrage d'un texte sans temps sur des mots horodatés

Étage A de l'alignement forcé, SANS modèle : un texte fait ailleurs (export Sonal, texte) retrouve l'heure de chacun de ses mots parmi ceux d'une sortie ASR de la même audio — plus longue sous-suite commune des mots (RapidFuzz `Indel`, jamais Levenshtein, qui substitue aux ex-aequo et décale la suite). Chaque mot dit la qualité de son temps : `exact`, `estimated` (dans la durée réelle des mots corrigés), `interpolated` (rien en face). Étage B (`refine_turns`) : un aligneur ACOUSTIQUE (contrat `ForcedAlignmentBackend`, choisi au catalogue par sa tâche `alignment` et sa langue) reprend les seuls mots estimés, par fenêtres que tiennent leurs voisins sûrs, coupées entre deux mots au-delà de sa capacité ; ils deviennent `aligned`. Le module ne charge aucun modèle : il reçoit le geste d'alignement. Bornes (`move_boundary`, `split_turn`) : déplacer la jonction de deux tours ou couper un tour, toujours ENTRE deux mots et sans en perdre un — un texte corrigé se réancre d'abord sur la référence ASR. Plage (`replace_span`) : une plage retranscrite remplace les mots qui s'y disaient, ou remplit un blanc d'un tour neuf

- **Domicile** : `wama/common/services/word_anchoring.py` · **doc** : [wama/transcriber/TRANSCRIBER_CORRECTION.md §10.5](../../wama/transcriber/TRANSCRIBER_CORRECTION.md)
- **Module** : Ancrage d'un texte SANS TEMPS sur des mots HORODATÉS — l'étage A de l'alignement forcé.
- **API publique** (8) :
  - `timed_tokens(words: List[dict]) -> List[Tuple[str, float, float]]` — Mots horodatés (`{word, start, end}`, forme Whisper) → jetons comparables horodatés.
  - `anchor_turns(turns: List[dict], words: List[dict]) -> Optional[Tuple[List[dict], dict]]` — Donne des temps aux tours de parole `turns` (`{text, …}`) à partir des mots horodatés `words`.
  - `refine_turns(turns: List[dict], align_window, max_seconds: float, *, audio_end: Optional[float]=None) -> Tuple[List[dict], dict]` — ÉTAGE B : reprend à l'oreille les mots `estimated`/`interpolated` de tours ANCRÉS.
  - `spoken_text(words: List[dict]) -> str` — Le texte que portent des mots au format Whisper (`''.join` des mots, sans bord blanc).
  - `turn_words(turn: dict, reference: Optional[List[dict]]=None) -> Optional[List[dict]]` — Les mots horodatés d'un tour, COHÉRENTS avec son texte — ou None si le tour n'a pas de temps.
  - `move_boundary(left: dict, right: dict, at: float, reference: Optional[List[dict]]=None) -> Optional[Tuple[dict, dict]]` — Déplace la jonction entre deux tours CONSÉCUTIFS vers `at` : les mots passent d'un côté à
  - `split_turn(turn: dict, at: float, reference: Optional[List[dict]]=None) -> Optional[Tuple[dict, dict]]` — Coupe un tour en deux à `at`, entre deux mots : les mots d'avant restent, ceux d'après
  - `replace_span(turns: List[dict], start: float, end: float, words: List[dict], reference: Optional[List[dict]]=None, new_turn: Optional[dict]=None) -> List[dict]` — Remplace les mots de `turns` dont le MILIEU tombe dans [start, end] par `words` (horodatés).

### Calendrier de l'utilisateur et plages réservées

Le journal sur l'axe du TEMPS — mêmes sources (Médias, Lab, Studio), intervalle d'exécution reconstruit de RunOutcome + processing_seconds ou des champs de fin du modèle, création des lots ; PRÉVU : fin des traitements en cours (débit observé, début lu au gouverneur) et passages de purge ; plus la maintenance planifiée (beat) et ses plages RÉSERVÉES à durée mesurée (tests nocturnes). Projette, n'écrit rien

- **Domicile** : `wama/common/services/calendar.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §9bis.1](../construction/ia/WAMA_MEMORY.md)
- **Module** : Calendrier — l'activité de WAMA posée sur l'axe du TEMPS. Doc : `WAMA_MEMORY.md §9bis.1` (la vue) ; plan d'ensemble — trois natures de temps, actions programmées, placement — : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13 (« le QUAND »).
- **API publique** (19) :
  - `class CalendarEvent` — Un événement du calendrier. Volontairement MINCE, comme l'entrée du journal : le détail
  - `predicted_end(started_at, progress, now) -> datetime | None` — Fin prévue par le DÉBIT OBSERVÉ — la même règle que `wama-eta.js` côté navigateur :
  - `observed_events(user, start, end, *, now=None, queue=None) -> list[CalendarEvent]` — Items de l'utilisateur dont le dépôt, l'exécution ou la fin tombe dans `[start, end)`, plus
  - `batch_events(user, start, end) -> list[CalendarEvent]` — La création des LOTS de l'utilisateur dans `[start, end)`.
  - `expiry_events(user, start, end) -> list[CalendarEvent]` — Les purges de rétention qui toucheront l'utilisateur dans `[start, end)`.
  - `measured_nightly_minutes(stage=None, reports_dir=None, cadence=None) -> float | None` — Durée MÉDIANE récente d'une campagne nocturne complète, en minutes — `None` sans mesure.
  - `window_minutes(entry_name) -> tuple[int, str]` — Durée réservée pour une entrée beat : `(minutes, 'measured' | 'declared')`.
  - `maintenance_windows(start, end) -> list[CalendarEvent]` — Occurrences des entrées beat À HORAIRE (`crontab`) dans `[start, end)`.
  - `next_occurrence(entry_name, now=None)` — Le prochain passage de l'entrée beat `entry_name` (à horaire), ou None si elle n'est pas
  - `reserved_windows(start, end, resource=None) -> list[CalendarEvent]` — Fenêtres qui RÉSERVENT une ressource (`gpu`, `cpu`), ou toutes si `resource` est `None`.
  - `reserved_window_conflicts(start, end) -> list[tuple[CalendarEvent, CalendarEvent]]` — Paires `(fenêtre réservée, autre entrée planifiée qui la chevauche)` dans `[start, end)`.
  - `declared_events(user, start, end) -> list[CalendarEvent]` — Les programmations ACTIVES de l'utilisateur (`ScheduledAction`, étape 3) — nature `voulu`.
  - `queue_events(user, start, end, entries) -> list[CalendarEvent]` — Les traitements des AUTRES dans la file GPU — couche de l'instance, ANONYME (étape 4).
  - `register_instance_layer(key, *, label, app, events)` — Inscrit `events(start, end) -> list[CalendarEvent]` comme couche de l'instance.
  - `nature_labels() -> dict` — Valeurs de la facette « Nature » : les natures de temps, la maintenance, puis les couches.
  - `instance_layer_events(user, start, end) -> list[CalendarEvent]`
  - `calendar_window(start=None, end=None, *, days_back=31, days_ahead=31, max_days=400)` — Fenêtre `[start, end)` d'une lecture du calendrier, depuis deux bornes ISO 8601 (date ou
  - `events_for(user, start, end, *, with_maintenance=True) -> list[CalendarEvent]`
  - `to_ics(events, *, host='wama', now=None) -> str` — Les événements au format iCalendar. `host` qualifie les UID (uniques et STABLES : un

### Captation générique des gestes

Middleware : telecharge/supprime/relance lus de resolver_match — zéro ligne par app

- **Domicile** : `wama/common/middleware.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7bis](../construction/ia/WAMA_MEMORY.md)
- **Module** : Captation GÉNÉRIQUE des gestes utilisateur vers `RunOutcome`. Doc : `WAMA_MEMORY.md §7bis`.
- **API publique** (2) :
  - `app_of(match) -> str` — L'app d'une route résolue, sous le nom que connaissent les registres (`DetailRegistry`).
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

### Corpus système — la doc de WAMA pour l'assistant

Projette la doc DÉCLARÉE (`docs_catalog`) en fragments rappelables, découpés par section ; qui lit quoi = le prédicat du lecteur de docs ; hors du RAG des utilisateurs par construction ; outils `search_docs` / `read_doc`

- **Domicile** : `wama/common/memory/docs_corpus.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7quinquies](../construction/ia/WAMA_MEMORY.md)
- **Module** : Corpus SYSTÈME — la doc de WAMA rendue rappelable par l'assistant. Doc : `WAMA_MEMORY.md §7quinquies`.
- **API publique** (9) :
  - `source_id_of(key: str) -> str`
  - `indexed_docs()` — Les docs qui ENTRENT au corpus : déclarés, et pas des journaux datés.
  - `visible_keys(user) -> list` — Clés des docs que `user` peut lire — le prédicat du lecteur, pas une copie.
  - `visible_chunks(user)` — Fragments de doc rappelables par `user` — la base que `recall(include_docs=True)` classe.
  - `fragments_of(doc, text: str) -> list` — `[(contenu, source_ref)]` d'un doc, dans l'ordre du texte.
  - `index_docs(*, dry_run: bool=False) -> dict` — Projette la doc déclarée vers le corpus. Rend `{'docs', 'written', 'unchanged',
  - `corpus_state() -> dict` — `{'fragments', 'vectorized', 'docs'}` — ce que le corpus contient, pour le dire.
  - `describe_hit(chunk) -> dict` — Ce qu'un fragment retrouvé dit de sa provenance : doc, section, audience, lien, date.
  - `read(user, key: str, section: str='') -> dict` — Lit UN doc déclaré : son sommaire, ou une section avec ses sous-sections.

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
- **API publique** (5) :
  - `sorties_de(surface: str, instance) -> list` — Chemins RELATIFS à `media/` des sorties DÉCLARÉES de cet élément.
  - `batch_outputs(surface: str, batch, viewer=None) -> tuple` — Les sorties DÉCLARÉES de tous les éléments d'un LOT — `(chemins, éléments, sans_sortie)`.
  - `item_for_output_path(user, chemin: str, *, visible: bool=False)` — L'élément dont `chemin` (relatif à `media/`) est une SORTIE déclarée — `(surface,
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

### File globale GPU (où en est chaque tâche)

Lue, jamais devinée : ce qui tourne au gouverneur, ce que le worker GPU TIENT au broker (`unacked` : tâche en cours non déclarée, orphelin écarté, différé à son échéance), ce qui attend dans les listes dans l'ordre de consommation. Heures prévues = somme de durées MESURÉES (file sérielle) ; place et durée des traitements des autres, jamais leur titre (une tâche système se nomme). Nourrit le placement `auto`, la pastille « En file », le calendrier et l'API de l'assistant (`place_of`)

- **Domicile** : `wama/common/services/global_queue.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : La FILE GLOBALE de WAMA — où en est chaque traitement GPU, pour tous (calendrier, étape 4). Doc : `WAMA_APP_GENERATION_ROUTE.md §10.6` point 13.8 ; la vue : `WAMA_MEMORY.md §9bis.1`.
- **API publique** (10) :
  - `class QueueEntry`
  - `broker_messages(queue=GPU_QUEUE, client=None) -> list[dict]` — Messages en ATTENTE sur `queue`, dans l'ordre où le worker les prendra.
  - `held_messages(queue=GPU_QUEUE, client=None, *, keys=('unacked', 'unacked_index')) -> list[dict]` — Messages DÉLIVRÉS à un worker de `queue` et pas encore confirmés — la table `unacked`.
  - `note_consumer_ready(queues, at=None) -> None` — Note l'instant où un worker consommant `queues` est PRÊT (`wama/celery.py`, `worker_ready`).
  - `consumer_ready_at(queue=GPU_QUEUE)` — Instant de démarrage du worker de `queue`, ou None s'il n'est pas connu (cache perdu,
  - `typical_seconds(model, _cache=None) -> tuple[float, str]` — Durée TYPIQUE d'un traitement de `model` : `(secondes, 'measured' | 'declared')`.
  - `snapshot(now=None, *, running=None, queued=None, held=None, ready_at=None) -> list[QueueEntry]` — La file GPU telle qu'elle s'exécutera : en cours, puis en attente, avec des heures PRÉVUES.
  - `free_at(now=None, entries=None)` — Instant où la file GPU sera VIDE, d'après l'instantané.
  - `for_user(user, now=None, entries=None) -> list[dict]` — Les éléments de `user` dans la file, avec leur place et le nombre de tâches devant eux.
  - `place_of(obj, viewer, entries=None) -> dict | None` — Où en est l'élément `obj` dans la file GPU, vu par `viewer` — None s'il n'y est pas.

### Fuites de secrets

gitleaks sur l'historique git COMPLET, aucune ligne d'attribution dans les messages, et vérifie que les hooks git versionnés (pre-commit, commit-msg, pre-push — ce dernier voit aussi les commits faits par commit-tree) sont en place et non dérivés : un hook mort est une garde silencieusement absente, donc rouge et pas warning

- **Domicile** : `wama/common/management/commands/check_secret_leaks.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.10](../construction/suivi/ROADMAP.md)
- **Module** : check_secret_leaks — fuites de secrets dans l'HISTORIQUE GIT COMPLET (gitleaks), lignes d'attribution dans les messages, et présence des hooks git qui empêchent d'en créer.
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
- **API publique** (8) :
  - `class SourceJournal` — Un modèle dont les items entrent au journal.
  - `app_queue_url(app)` — Page de file d'une app, `''` si elle n'en déclare pas.
  - `enregistrer_source(app, model, *, champ_date=None, champ_user='user')` — Ajoute une source hors `detail_registry` — point d'extension des mondes lab/data/transverse.
  - `sources()` — Toutes les sources du journal. Dérivées de `detail_registry` + les inscriptions explicites.
  - `class Entree` — Un item au journal. Volontairement MINCE — le détail vient des endpoints transversaux.
  - `entrees(user, *, mondes=None, apps=None, depuis=None, jusqu_a=None, limite=50, offset=0, avec_gestes=True, tri='recent', statut='all', q='')` — Rend `(liste d'Entree triée, total)`.
  - `compter_par_app(user, **kwargs)` — Répartition par app — alimente les filtres de la page sans requête supplémentaire côté vue.
  - `count_by_app_per_user()` — `compter_par_app` pour TOUS les comptes d'un coup : `{user_id: [rows]}`, une requête

### L'assistant, CLIENT MCP de la surface de développement

Le moteur de l'assistant RELAIE les outils `dev_*` (rôles wama-dev-ai, bac à sable) à la surface « wama-dev » par le protocole — process séparé, §16 tenu : rien n'est importé, la porte (droits à chaque appel, arguments admis) reste celle du serveur. Annoncés aux seuls développeurs/admins ; serveur absent = aucun outil, l'assistant répond quand même. Étape 5 de §8d, moitié dev (2026-09-22). Il porte l'adresse et le jeton de TOUTE surface (`surface_url`, `api_key`), lus aussi par l'abonnement Claude Code et la mesure (2026-10-23)

- **Domicile** : `wama/common/services/mcp_client.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Client MCP du moteur de l'assistant — la surface « wama-dev » vue DEPUIS l'assistant (ROADMAP §8d Phase 3, étape 5, moitié « outils de dev » ; demande de Fabien du 2026-09-22 : « améliorer WAMA depuis l'assistant, sans forcément passer par Claude, uniquement pour les rôles admin et dev »).
- **API publique** (8) :
  - `is_dev_tool(name: str) -> bool`
  - `surface_url(surface: str) -> str` — Adresse de l'endpoint MCP d'une surface (`mcp_server.SURFACE_WAMA` / `SURFACE_DEV`) — le
  - `dev_surface_url() -> str` — Adresse de l'endpoint MCP de la surface dev.
  - `api_key(user) -> str` — Le jeton d'API WAMA du compte — l'identité de tout client MCP (`mcp_server.user_for_token`),
  - `dev_tools_for(user) -> list` — Outils de développement que l'assistant peut ANNONCER à `user` :
  - `tools_block(tools: list) -> str` — Bloc de prompt des outils de dev — MÊME forme que `tool_api.build_tools_list`
  - `call_dev_tool(user, name: str, arguments) -> dict` — Relaie UN appel d'outil de dev à la surface, et rend son résultat comme `execute_tool`
  - `surface_tool_names(user, surface: str) -> list` — Les noms des outils qu'une surface du serveur ANNONCE à `user`, lus par le protocole MCP

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

### Modèles de NIVEAU DÉVELOPPEMENT (bridage « qualité max »)

UN domicile pour « quel modèle a le droit de travailler sur le code » : plancher sur le score coding du banc tiers (≥ 40) + déclaration explicite pour le seul distant non mesuré (albert:gpt-oss-120b), curseur imposé à 100 (réflexion), distants SOUVERAINS admis dès « cloud si saturé », et REFUS lisible plutôt qu'un petit modèle en repli. Lu par l'assistant (domaine dev, bascule en cours de tour dès qu'une compétence dev ou un outil dev_* est appelé, domaine collant au fil) et par les rôles wama-dev-ai (`role_utils.resolve_model`) — décision Fabien 22/09 après un tour réel où qwen3.5:4b inventait des jumelles. SECOND PLANCHER au même domicile (29/09) : `AGENT_CODING_FLOOR` (30) borne le tirage AUTOMATIQUE de tout tour d'assistant OUTILLÉ, et `escalation_model` choisit le modèle qui REPREND un tour inventé (`assistant_engine._invented_turn`)

- **Domicile** : `wama/common/services/development_models.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : Modèles de NIVEAU DÉVELOPPEMENT — le bridage « qualité max » du travail sur le code (2026-09-22).
- **API publique** (11) :
  - `role_user()` — Le compte pour lequel ce process de rôle travaille (`ROLE_USER_ENV`), ou None.
  - `coding_score(model) -> float | None` — Sous-indice coding du banc tiers, ou None s'il n'est pas mesuré.
  - `is_development_grade(model) -> bool` — Ce modèle a-t-il le niveau développement ? Mesure d'abord, déclaration ensuite.
  - `dev_cloud_keys(user) -> set` — Modèles distants admis au tirage de DÉVELOPPEMENT pour `user` : la règle commune
  - `development_candidates(user, source: str='') -> list` — `model_key` des modèles de conversation de niveau dev que `user` peut lancer : locaux
  - `development_model(user, requested: str=None, source: str='') -> str | None` — Le modèle de niveau dev pour ce travail — `model_key` complet (`ollama:…`, `albert:…`), ou
  - `development_refusal(user=None, source: str='') -> str` — La raison, lisible, quand aucun modèle de niveau dev n'est disponible.
  - `is_agent_grade(model) -> bool` — Ce modèle peut-il servir un tour outillé ? Seule une mesure SOUS le plancher l'exclut.
  - `agent_candidates(user, cloud_keys=None) -> list` — `model_key` des modèles au plancher de l'assistant outillé que `user` peut lancer.
  - `escalation_model(user, current_key: str=None) -> str | None` — Le modèle vers lequel REPRENDRE un tour inventé : au plancher, plus fort au banc que
  - `is_development_step(step: dict) -> bool` — Une étape d'outil qui fait ENTRER la conversation dans le travail sur le code : la

### Modèles DISTANTS au catalogue

Un modèle servi par une clé d'API entre au catalogue comme les autres (ligne `<source>:<id>`, `execution='cloud'`, le modèle porte son moteur et le fournisseur s'en DÉRIVE) : découverte par la clé de CHAQUE utilisateur (`GET /models` à l'enregistrement), le catalogue porte l'UNION, et `retire_unlisted` MARQUE ce que la source ne liste plus au lieu de le supprimer — une clé qui ne voit plus un modèle ne prouve pas qu'il a disparu. Ces lignes n'entrent au tirage que par `select_model(cloud_keys=…)`

- **Domicile** : `wama/model_manager/services/cloud_models.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Modèles DISTANTS au catalogue — découverte par la clé d'un UTILISATEUR (ROADMAP §8d Phase 3, 4b).
- **API publique** (22) :
  - `abilities_for(task: str, remote_type: str='') -> dict` — Drapeaux `ModelAbility` qu'une TÂCHE distante garantit — ceux que `select_model(requires=…)`
  - `class CloudDiscoveryError(RuntimeError)` — Découverte impossible — message lisible par l'utilisateur, jamais la clé.
  - `task_and_type(remote_type: str)` — (tâche NÔTRE, model_type) d'un type annoncé par le fournisseur, ou (None, None).
  - `type_from_modalities(architecture: dict) -> str` — Type (tag HuggingFace) d'un modèle décrit par ses MODALITÉS — la forme d'OpenRouter
  - `list_remote_models(source: str, api_key: str, timeout: float=20.0) -> list` — Modèles ouverts à `api_key` chez `source` : [{id, name, type, aliases[, cost_tier]}].
  - `declared_listing(source: str) -> list` — Liste DÉCLARÉE d'un fournisseur sans liste de modèles (abonnement Claude Code : le CLI
  - `model_info_for(source: str, item: dict)` — `ModelInfo` d'un modèle distant rangeable, ou None si aucun vocabulaire ne sait le ranger.
  - `cloud_model_infos() -> dict` — `{model_key: ModelInfo}` de TOUS les modèles distants qu'une clé posée ouvre — la
  - `keys_for(source: str, listing: list) -> list` — Clés de catalogue des modèles rangeables d'une liste — ce que `UserApiKey.open_models` garde.
  - `retire_unlisted(source: str) -> int` — Marque indisponibles les lignes distantes de `source` qu'AUCUNE clé n'ouvre plus, et remet
  - `drop_renamed(source: str) -> list` — SUPPRIME les lignes retirées de `source` qui ne sont qu'un ANCIEN NOM d'une ligne vivante —
  - `refresh_key(row, background: bool=False) -> tuple` — Relit chez le fournisseur les modèles ouverts à la clé `row` (`accounts.UserApiKey`), puis
  - `refresh_all_keys() -> dict` — Relit chez CHAQUE fournisseur les modèles ouverts à CHAQUE clé posée — la sonde nocturne.
  - `register_open_models(row) -> None` — Le CATALOGUE suit la liste gardée sur la clé `row` : la partie LONGUE de `refresh_key`
  - `hosting_ceiling(user) -> str` — PLAFOND d'hébergement du profil (`UserProfile.cloud_hosting_max`), sur l'échelle
  - `data_reuse_accepted(user) -> bool` — `user` accepte-t-il qu'un hébergeur garde ou réutilise ses requêtes ? Le dernier cran de
  - `cloud_refusal(user, source: str='') -> str` — Motif de refus d'un appel distant pour `user`, sinon ''. Sans utilisateur : ''.
  - `allowed_cloud_keys(user, automatic: bool=True) -> set` — `model_key` des modèles distants que `user` autorise — à passer à `select_model(cloud_keys=…)`.
  - `drop_unavailable(user, keys, personal_sources=None) -> set` — `keys` moins les modèles qu'un TIRAGE ne peut pas retenir maintenant : une source notée
  - `is_cloud_key(model_key) -> bool` — La clé de catalogue `model_key` désigne-t-elle un modèle servi par un FOURNISSEUR
  - `class CloudAccessRefused(RuntimeError)` — Appel distant refusé — message lisible par l'utilisateur ; `status` = code HTTP à rendre.
  - `cloud_access(user, source: str, model_id: str='') -> str` — La CLÉ avec laquelle `user` appelle `source` (et le modèle `model_id` s'il est nommé), ou

### Mémoire & RAG

Souvenirs + fragments sur pgvector, scope hérité de ScopedVisibility ; 5 opérations

- **Domicile** : `wama/common/memory/store.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md](../construction/ia/WAMA_MEMORY.md)
- **Module** : Les cinq opérations de la mémoire. Doc : `WAMA_MEMORY.md §5-6`.
- **API publique** (11) :
  - `class Hit` — Un résultat de rappel. `obj` est un `MemoryItem` ou un `RagChunk`.
  - `content_hash(text: str) -> str` — SHA-256 du contenu NORMALISÉ (espaces repliés, casse pliée).
  - `remember(content, *, kind, provenance, user=None, subject='', source_app='', source_object_type='', source_object_id=None, confidence=None, visibility=None, sc…` — Écrit un souvenir. Rend le `MemoryItem` (créé ou déjà existant), ou `None` en cas d'échec.
  - `recall(query, *, user, kinds=None, subject=None, k=8, include_rag=True, include_memory=True, semantic=True, resident=True, rag_niveaux=None, include_docs=False)` — Retrouve les `k` meilleurs éléments visibles par `user`.
  - `reindex(*, lot=64, limite=None, modeles_obsoletes=False, dry_run=False, user=None)` — Calcule les vecteurs manquants, PAR LOT. Rend un résumé `{...}`.
  - `forget(item, *, reason='', hard=False, at=None)` — Invalide un souvenir — `valid_to = maintenant`. Il cesse d'être rappelé, sans disparaître.
  - `merge(items, *, seuil=0.92)` — PROPOSE de fusionner des souvenirs proches. N'ÉCRIT RIEN.
  - `apply_fusion(proposition, *, par_utilisateur)` — Applique UNE proposition de `merge()`. Réservé à un geste humain explicite.
  - `expire(*, jours_non_approuve=90, dry_run=True)` — Applique les politiques de rétention. Rend un résumé `{...}`.
  - `approve(item, *, par, visibility=None, scope_org_unit=None, scope_project=None)` — LE GESTE DE VALIDATION HUMAINE — ajouté le 2026-09-09, et son absence était le trou.
  - `list_memories(user, *, en_attente=False)` — Les souvenirs à AFFICHER — matière de la page « Mes souvenirs » (jumelle de « Mon RAG »).

### Métriques de diarisation à vérité terrain (cpWER / DER)

cpWER : un WER où le mot prêté au mauvais locuteur compte (appariement optimal des locuteurs) ; DER : parole manquée + fausse alarme + confusion sur le temps (pyannote.metrics). Une mesure sans objet (sortie non diarisée, pas de temps) rend None, jamais zéro

- **Domicile** : `wama/common/services/diarization_metrics.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : Métriques de DIARISATION à vérité terrain — cpWER et DER (`WAMA_QUALITE.md` M3, 2026-09-30).
- **API publique** (5) :
  - `is_diarized(segments: Optional[Sequence[dict]]) -> bool` — Au moins un segment porte un locuteur nommé — sinon il n'y a pas de diarisation à mesurer.
  - `class SpeakerAttributedRate` — Le compte d'un cpWER : un WER où le locuteur fait partie du mot.
  - `cp_word_error_rate(reference_segments: Sequence[dict], hypothesis_segments: Sequence[dict], language: Optional[str]=None) -> Optional[SpeakerAttributedRate]` — cpWER de `hypothesis_segments` contre `reference_segments` (dicts `speaker_id`, `text`,
  - `class DiarizationRate` — Le compte d'un DER, en SECONDES.
  - `diarization_error_rate(reference_segments: Sequence[dict], hypothesis_segments: Sequence[dict], language: Optional[str]=None, collar: float=0.0) -> Optional[Di…` — DER de `hypothesis_segments` contre `reference_segments`, par `pyannote.metrics`.

### Métriques à vérité terrain (WER / CER)

Distance d'une sortie texte à sa RÉFÉRENCE (port `reference_result`) : substitutions, suppressions, insertions rapportées à la longueur de la référence. Ne normalise que la casse et la ponctuation — les hésitations restent des données (verbatim) ; une référence vide rend un taux INDÉFINI, jamais zéro

- **Domicile** : `wama/common/services/text_metrics.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : Métriques de texte À VÉRITÉ TERRAIN — WER et CER (`WAMA_QUALITE.md` M3).
- **API publique** (4) :
  - `comparable_words(text: str, language: Optional[str]=None) -> list` — Mots comparables : minuscules, sans ponctuation, **apostrophe et soulignement traités en
  - `class ErrorRate` — Le compte d'une comparaison sortie ↔ référence, et son taux.
  - `word_error_rate(reference: str, hypothesis: str, language: Optional[str]=None) -> ErrorRate` — WER — taux d'erreur par MOT de `hypothesis` (la sortie) contre `reference`.
  - `character_error_rate(reference: str, hypothesis: str, language: Optional[str]=None) -> ErrorRate` — CER — taux d'erreur par CARACTÈRE, sur le même texte normalisé que le WER (mots séparés

### Outils de DÉVELOPPEMENT (surface MCP « wama-dev »)

Rôles wama-dev-ai (librarian, model, scout, integrator, codegen) et bac à sable d'apps, exposés à un client MCP. ⚠ JAMAIS chargé dans le process de PRODUCTION (ROADMAP §16 : défense en profondeur > scope de jeton) — ni dans `TOOL_REGISTRY` ni importé par `tool_api` ; seul `run_mcp_server --surface dev` l'importe, et `tests_mcp_dev_tools` le garde. Les rôles écrivent une PROPOSITION dans `wama-dev-ai/outputs/` et n'appliquent rien

- **Domicile** : `wama/common/services/dev_tools.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Outils de DÉVELOPPEMENT de WAMA — la surface du serveur MCP « wama-dev » (ROADMAP §8d Phase 3, étape 3).
- **API publique** (23) :
  - `class DevToolError(ValueError)` — Refus LISIBLE — rendu comme `{'error': …}`, jamais comme une trace.
  - `base_dir() -> Path`
  - `jobs_dir() -> Path`
  - `outputs_dir() -> Path`
  - `role_command(role: str, args=None, provider: str='', model: str='') -> list`
  - `role_model(user, provider: str='', model: str='') -> dict` — Le modèle d'un rôle, TIRÉ pour le compte qui le lance : `{'key', 'provider', 'model',
  - `sandbox_manifest(path: str) -> str` — Le manifeste d'où une app naît DE ZÉRO — un brouillon du corpus (`manifests/app_drafts/`)
  - `sandbox_command(action: str, app: str='', target: str='', owner: str='', manifest: str='') -> list`
  - `regen_check_command(app: str) -> list` — `--force` n'est JAMAIS ajouté : la garde du harnais (refus sur dev/main) reste entière.
  - `start_job(user, tool: str, argv: list, env: dict=None, shown: list=None) -> dict` — Lance `argv` détaché ; le journal et le code de retour sont écrits à côté de la fiche.
  - `job_state(job_id: str, with_log: bool=True) -> dict`
  - `notify_finished_jobs() -> int` — Annonce, une fois, chaque tâche de développement TERMINÉE : une notification DANS WAMA
  - `start_job_watcher() -> None` — Le veilleur des fins de tâche, dans le process du serveur de développement — celui qui
  - `dev_run_role(user, role: str, args: dict=None, provider: str='', model: str='') -> dict` — Lance un rôle wama-dev-ai en tâche de fond ; il écrit une PROPOSITION en attente de validation, n'applique rien.
  - `dev_sandbox(user, action: str, app: str='', target: str='', manifest: str='') -> dict` — Bac à sable d'apps en tâche de fond : create, substitute, revert, remove, list — l'app d'origine n'est jamais modifiée.
  - `dev_regen_check(user, app: str) -> dict` — Harnais de régénération d'une app (app_regen_check) en tâche de fond — refusé sur dev/main par sa propre garde.
  - `dev_reload_web(user) -> dict` — Recharge gunicorn (signal HUP, rechargement gracieux) — nécessaire après la création, la restauration ou le retrait d'une jumelle.
  - `dev_claude_code(user, task: str, write: bool=False, model: str='') -> dict` — Confie une tâche de développement à Claude Code (abonnement du demandeur) en TÂCHE DE FOND : audit, explication, ou modification du dépôt avec write=true. Réponds aussitôt à l'utilisateur ; la réponse de Claude Code arrive dans le fil à la…
  - `dev_job_status(user, job_id: str) -> dict` — État d'une tâche de développement : en cours, terminée, échouée ou interrompue ; fin du journal et propositions écrites.
  - `dev_list_jobs(user, limit: int=20) -> dict` — Dernières tâches de développement lancées (tous développeurs), la plus récente d'abord.
  - `dev_read_output(user, path: str) -> dict` — Lit une proposition écrite par un rôle (fichier JSON de wama-dev-ai/outputs/) — lecture seule.
  - `tools_for(user) -> list` — Outils de développement visibles par `user` — aucun pour un non-développeur.
  - `call(user, name: str, arguments) -> dict` — Un appel d'outil de développement — droits vérifiés ICI, à chaque appel.

### Partage d'un élément ou d'un lot (1ʳᵉ interface)

LE GESTE qui manquait au mécanisme de visibilité : `PROFILES_PERMISSIONS §7.5` disait « il n'existe AUCUNE interface de partage » (il fallait l'admin Django). Écrit `visibility` + son scope sur l'élément ET son lot — ou sur le lot ET ses éléments : les DEUX sens sont exigés, le filtre de lecture s'appliquant aux deux niveaux (un lot partagé aux éléments privés s'affiche VIDE chez le destinataire). Portées OFFRABLES dérivées de l'utilisateur (unités qui le couvrent, projets dont il est membre) : une portée sans cible réelle n'est pas proposée. Lecture seule par construction — l'écriture est le jalon S3 `AccessGrant`, et la modale le DIT. Depuis le 2026-10-01 : « Dupliquer » une card reçue (`scoping.duplicable_or_404`) et « Transférer à… » (`card_transfer` : possédés déplacés, désignés copiés). Depuis le 2026-10-02 : le RANGEMENT chez le destinataire (`reception`, §3bis.2) — « Retirer de ma file » ≠ supprimer, « Réafficher », SON ordre manuel ; une ligne par destinataire et par ENTRÉE de file (`ReceivedEntry`), qui ne porte aucun droit. Depuis le 2026-10-03 : la card reçue en LECTURE SEULE (pastille des deux côtés, ▶ 🗑 → encart, ⚙ en consultation), les MODES déclarés (`SHARE_MODES`, deux grisés) et les DEMANDES d'accès (`ObjectGrant` : la demande et le droit sont la même ligne ; la propriété s'accorde, elle cède la card). Puis la COLLABORATION (E1-E5) : `scoping.editable_or_404` / `can_edit` (lancement, réglages, arrêt, correction — jamais la suppression), fin notifiée aux deux, verrou doux (`edit_lock`), réglages tracés au journal, retrait depuis « Mes partages ». Depuis le 2026-10-06 : le partage À UNE PERSONNE (`share_with_person` — une ligne `ObjectGrant` accordée, lue par `scoped_visible_q(…, model=)` en extension des portées ; mode lecture ou collaboration) et le destinataire PRÉVENU (N1 : `share_received` ; membres d'un projet aussi, unité et public non) ; chaque partage par portée DATÉ par une ligne `ObjectGrant` sans bénéficiaire (mémoire, jamais lue pour décider qui voit). Depuis le 2026-10-07 : une fille partagée arrive SEULE (`batch_common.visible_members`) ; l'enregistrement préparé sur un état PÉRIMÉ est refusé (`edit_lock.state_token` / `stale_edit`, 409) et le verrou doux tient aussi la page de correction (`WamaCardMenu.holdEditLock`)

- **Domicile** : `wama/common/services/sharing.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : PARTAGE d'un élément de file — la première INTERFACE du mécanisme de visibilité.
- **API publique** (18) :
  - `share_mode(key: str) -> dict` — La déclaration d'un mode (`SHARE_MODES`), ou celle de la lecture si la clé est inconnue.
  - `shares_overview(user, limit: int=200) -> dict` — Ce que montre la page « Partages » (`WAMA_COLLABORATION §5.3`, 2026-10-03) : ce que `user` a
  - `scope_label(element) -> str` — La portée d'un élément partagé, dite par sa CIBLE (« LESCOT », « Projet X », « Public ») —
  - `scope_choices(user) -> list` — Les portées que `user` peut offrir, à plat : `[{value, label}]` (`portees_offrables`).
  - `scope_value(element) -> str` — La portée COURANTE d'un élément dans la forme de `scope_choices`.
  - `share_scope(user, element, scope: str, consent: bool=False) -> dict` — Pose la portée `scope` (forme de `scope_choices`) par `partager`.
  - `catalogue_owned_rows()` — Les familles du CATALOGUE dont une ligne a un auteur (`owner`) : `[(registre, modèle)]`,
  - `class RefusDePartage(Exception)` — Refus MOTIVÉ : le motif est destiné à l'utilisateur, pas au journal.
  - `class ConsentRequired(RefusDePartage)` — Le partage d'un élément personnel attend le consentement de celui qui partage.
  - `consent_subject(element) -> str` — Ce que l'élément porte d'une personne (« la voix d'une personne »), ou '' — DÉCLARÉ par
  - `portees_offrables(user) -> list` — Ce que CET utilisateur peut offrir, avec les cibles réelles de chaque portée.
  - `scope_since(obj)` — Depuis quand `obj` est partagé à sa portée COURANTE, ou None (privé, ou partagé avant que
  - `partager(user, element, visibility, org_unit_id=None, project_id=None, consent: bool=False) -> dict` — Applique la portée à l'élément ET à son lot. Rend un compte-rendu.
  - `partager_lot(user, lot, modele_element, visibility, org_unit_id=None, project_id=None, consent: bool=False) -> dict` — Partage un LOT ENTIER : le lot et TOUS ses éléments.
  - `share_with_person(user, target, element_model, recipient, level: str='read', *, nature: str='element', surface: str='', consent: bool=False) -> dict` — Partage `target` (un élément, ou un lot si `nature='lot'`) avec UNE personne, dans un mode
  - `unshare_person(user, target, beneficiary) -> int` — Retire à `beneficiary` tout partage EN PERSONNE sur `target` (et ce qu'il couvre, par
  - `persons_of(obj) -> list` — Les personnes à qui `obj` est partagé EN PERSONNE : `[{grant, user_id, name, mode, since}]`,
  - `etat(element) -> dict` — La portée COURANTE d'un élément, telle que l'UI doit la pré-sélectionner — et, s'il porte

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
  - `sha256_of(chemin, *, limite=SEUIL_EMPREINTE_OCTETS)` — Empreinte d'un fichier, ou `''` s'il est trop gros / illisible. Ne lève jamais. Un
  - `record_provenance(instance, field, *, kind, ref='', original_name='', source_path=None, user=None)` — Enregistre d'où vient `instance.<field>`. Remplace la trace existante, ne l'empile pas.
  - `ref_for(source_path)` — Adresse d'une source : son chemin relatif à `MEDIA_ROOT` s'il y vit, sinon son chemin brut.
  - `record_import(instance, field, source_path, *, kind='temp')` — La moitié complémentaire de `copy_into_app_input`, pour le motif « copier PUIS créer ».
  - `record_origin(copy_path, *, kind, ref, source_path=None)` — La provenance de TOUTES les cards qui portent cette copie, retrouvées par son chemin.
  - `kind_of(media_path) -> str` — La nature d'une source désignée par son chemin dans le gestionnaire de fichiers.
  - `provenance_of(instance, field)` — La provenance d'une entrée, ou `None`. Ne lève jamais.
  - `referenced_by(kind, ref)` — L'INDEX INVERSE — quelles entrées de cards désignent cette source ?
  - `same_source(kind, ref, user)` — Une copie de cette même source existe-t-elle déjà pour cet utilisateur ?

### Qui désigne ce fichier ? (déplacer, supprimer sans casser)

L'index des cards qui DÉSIGNENT un chemin, et les deux gestes qui le tiennent à jour — `repoint` quand le fichier bouge, `detach` quand il disparaît. Décision de Fabien du 2026-09-22 (`MEDIA_STORAGE_TIERING §8.6` D20) : déplacer ou renommer met à jour le lien des cards SANS rien demander ; supprimer un fichier qu'une card utilise demande d'abord une confirmation qui dit COMBIEN de cards il touche, puis laisse les cards en place, détachées. Avant, le gestionnaire renommait, déplaçait et supprimait sans jamais regarder les cards : c'est ce geste qui fabrique les « référencés mais absents » comptés par `check_media_integrity`. ⚠ DEUX façons de désigner, une seule met la card en péril : par un `FileField` (elle perd son fichier) ou par sa PROVENANCE (elle a sa copie — information, jamais un blocage). Une entrée d'une LISTE DE CHEMINS déclarée (`path_list_fields`, les images d'une génération de l'imager) désigne au même titre qu'un `FileField` : chaque question et chaque geste lit les deux formes (D35, 2026-10-02). 2026-10-28 : un déplacement fait aussi suivre les LIGNES D'EXÉCUTION (`ProcessRun.output_ref`, tous les mondes), qui ne comptent pas comme des cards qui utilisent le fichier ; `referenced_paths` est LA lecture de tout ce que la base désigne (audit des médias, tirage borné). ⚠ `filemanager.UserFile` est exclu : c'est l'index du gestionnaire lui-même

- **Domicile** : `wama/common/utils/file_references.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : QUI DÉSIGNE CE FICHIER ? — l'index des cards qui utilisent un chemin, et les deux gestes qui le tiennent à jour quand le fichier bouge ou disparaît.
- **API publique** (14) :
  - `file_field_models()` — `[(modèle, [FileField…])]` pour tout le dépôt — UNE énumération, plusieurs lecteurs
  - `path_list_fields()` — (modèle, champ) portant une LISTE de chemins (JSON) hors `FileField` — lus dans la
  - `relative_to_media(path) -> str` — Chemin relatif à MEDIA_ROOT (la forme que `owns_file` compare) ; '' s'il est HORS de
  - `listed_paths(instance) -> list` — `[(champ, chemin relatif à MEDIA_ROOT)]` pour chaque entrée des listes de chemins DÉCLARÉES
  - `card_files(instance) -> list` — `[(champ, chemin relatif à MEDIA_ROOT)]` de TOUT ce que la card porte : ses champs fichier
  - `referenced_paths(*, lists: bool=True, excluded=EXCLUDED_MODELS, detail: bool=False) -> dict` — `{chemin relatif → 'app.Modèle.champ #pk'}` de TOUT ce que la base désigne : les champs
  - `relocated_list(value, mapping) -> list` — La liste `value` dont chaque entrée désignant un chemin de `mapping` (relatif → nouveau
  - `direct_references(path, *, folder=False) -> list` — Les cards dont un `FileField` — ou une entrée d'une liste de chemins déclarée — porte ce
  - `is_referenced_elsewhere(path, *, label='', pk=None, field='') -> bool` — Une AUTRE ligne, DE N'IMPORTE QUEL MODÈLE, désigne-t-elle ce fichier ?
  - `referenced_outside(paths, inside) -> set` — Parmi `paths`, ceux qu'une ligne HORS de `inside` (ensemble de `(label, pk)`) désigne.
  - `source_references(path, *, folder=False) -> list` — Les provenances dont la SOURCE est ce chemin (ou un chemin sous ce dossier).
  - `usage(path, *, folder=False) -> dict` — Ce que le gestionnaire de fichiers doit savoir AVANT de supprimer.
  - `repoint(old_path, new_path, *, folder=False) -> dict` — Le fichier (ou le dossier) a bougé : chaque lien suit, directs, sources et lignes
  - `detach(path, *, folder=False) -> int` — Le fichier a été supprimé (après confirmation) : les cards qui le désignaient restent,

### Quotas des services externes

UNE brique pour tout service externe qui limite son débit : la NOTE de saturation (un refus récent ou une panne écarte la source du tirage automatique), le COMPTE de chaque appel servi par (source, portée de la clé, modèle) sur une fenêtre glissante, et les PLAFONDS — déclarés au registre des sources (`ExternalSource.quotas`, par source ou par groupe de modèles) ou APPRIS au premier refus réel. Un modèle dont le quota est atteint sort du tirage AVANT le refus. Portée = la CLÉ (personnelle, ou d'instance partagée par tous)

- **Domicile** : `wama/common/services/source_quota.py` · **doc** : [docs/construction/suivi/ROADMAP.md §8d](../construction/suivi/ROADMAP.md)
- **Module** : Quotas des SERVICES EXTERNES — une seule brique pour tous (`ROADMAP §8d` étape 3, 2026-10-14).
- **API publique** (9) :
  - `saturation_scope(user, source: str) -> str` — Portée de la limite de `source` pour `user` — elle tient à la CLÉ : la sienne s'il l'a
  - `note_saturation(source: str, *, scope: str, seconds: float, reason: str) -> None` — Note `source` saturée pour la portée `scope` (`saturation_scope`, ou `ALL_KEYS` pour une
  - `saturated_sources(scopes: dict) -> dict` — {source: motif} des sources notées saturées — `scopes` : {source: portée de la clé}. Une
  - `saturation_reason(user, source: str) -> str` — Le motif de saturation de `source` pour `user` (« limite de débit », « indisponible »), ou ''.
  - `record(source: str, scope: str, model: str='', *, tokens: int=0, now: float=None) -> None` — Compte UN appel servi par `source` (et ses `tokens`, s'ils sont connus).
  - `used(source: str, scope: str, bucket: str, unit: str, window_s: int, now: float=None) -> int` — Ce qui a été servi sur les `window_s` DERNIÈRES secondes — estimation glissante : la
  - `learn_from_refusal(source: str, scope: str, model: str='', *, retry_after_s: float=0.0, now: float=None) -> int` — Un refus de débit RÉEL : ce qui a été servi sur la fenêtre devient le plafond de cette
  - `exhausted(source: str, scope: str, model: str='', now: float=None) -> str` — '' si `source` peut encore servir `model` à cette clé ; sinon le motif — le plafond (déclaré
  - `unavailable_keys(keys, scope_of) -> dict` — {model_key: motif} des clés de catalogue `<source>:<modèle>` que le tirage automatique doit

### Recherche de la file par contenu

« voiture » retrouve l'élément dont l'IMAGE montre une voiture, sans que son nom le dise : les images de chaque élément de file (`file_references.card_files`, surfaces de `DetailRegistry`) vectorisées dans l'espace `media` (table `MediaVector`), par une tâche de la file GPU au palier bas (`common.index_media`) — lancée par le GESTE de chercher dans une file et par le lot de nuit, jamais par un battement. La barre de file commune demande au serveur les cards dont une image répond (écart à une requête neutre, mesuré), droits de lecture appliqués, et les montre en plus du filtre par le nom (2026-10-19)

- **Domicile** : `wama/common/vectors/media_index.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7sexies](../construction/ia/WAMA_MEMORY.md)
- **Module** : L'index des médias de la file par CONTENU — `WAMA_MEMORY.md §7sexies`.
- **API publique** (6) :
  - `surfaces() -> dict` — `{surface: modèle d'élément}` — les surfaces de détail déclarées (`DetailRegistry`).
  - `element_images(instance, limit: int=MAX_IMAGES_PER_ELEMENT) -> list` — `[(champ, chemin relatif)]` des images que l'élément porte et qui existent sur le disque —
  - `pending(addresses=None, limit: int=None) -> list` — Les images à (re)vectoriser : absentes de l'index, vectorisées par un autre modèle, ou
  - `index(addresses=None, *, limit: int=512) -> dict` — Vectorise ce qui attend (`pending`), par lots. Rend un résumé.
  - `purge() -> int` — Retire les vecteurs dont l'élément n'existe plus, ou dont le fichier a disparu. Rend le
  - `search(user, query: str, addresses) -> dict` — Les éléments, parmi `addresses` (les cards que la page montre), dont une image répond à

### Révisions d'un élément (historique DANS la card)

Chaque résultat produit donne à l'élément une révision numérotée — réglages dérivés du schéma, fichiers et leur empreinte, instruction — rattachée au fait `produit` de `RunOutcome` (un journal, pas deux) ; une révision PUBLIÉE est une version. Capture posée une fois dans le squelette de tâche : zéro ligne par app, la file ne voit rien. Une app qui le DÉCLARE (`keep_outputs`, le Writer d'abord, 2026-10-13) GARDE la copie des fichiers de ses 20 dernières révisions + des publiées (`KeptOutputsMixin`, liste déclarée à la rétention) ; au-delà la révision dit « fichier purgé ». ⏳ Restaurer d'un geste, les dix apps, volet Historique : marches suivantes

- **Domicile** : `wama/common/services/revisions.py` · **doc** : [docs/construction/exploitation/WAMA_COLLABORATION.md §7.1](../construction/exploitation/WAMA_COLLABORATION.md)
- **Module** : Révisions d'un élément — la brique de la marche 8a (`WAMA_COLLABORATION.md §7.1`).
- **API publique** (20) :
  - `json_safe(value)` — Une valeur de réglage telle qu'un JSONField la gardera (Decimal, date… → chaîne ; un
  - `settings_snapshot(app_id: str, item) -> dict` — Réglages de `item` à cet instant, dérivés du schéma de son app. `{}` sans schéma.
  - `text_fingerprint(value) -> str` — Empreinte d'une sortie qui est un TEXTE (pas un fichier) — celle des révisions, et celle
  - `output_references(item, fields=None) -> list` — `[{field, path, sha256}]` des SORTIES de `item`.
  - `record_revision(app_id: str, item, *, origin: str='process', user=None, outcome=None, model_keys=None, instruction: str='', output_fields=None)` — Donne à `item` sa révision suivante. Rend la ligne créée, ou None si rien n'a pu
  - `keep_outputs(app_id: str, keep: int=KEEP_DEFAULT, fields=None) -> None` — Déclare que `app_id` GARDE les fichiers de ses `keep` dernières révisions (+ les publiées).
  - `kept_count(app_id: str) -> int` — Combien de révisions gardent leurs fichiers pour `app_id` — 0 : l'app n'en garde pas.
  - `keeps_field(app_id: str, field: str) -> bool` — La copie de la sortie `field` se garde-t-elle pour `app_id` ?
  - `kept_path(path: str, number: int) -> str` — Où vit la copie de `path` pour la révision `number` : à côté de lui, dans `revisions/`,
  - `keep_files(app_id: str, item, revision) -> list` — Copie les fichiers de sortie de `revision` dans la liste gardée de `item`, puis applique la
  - `prune_kept(app_id: str, item) -> list` — La rétention V3 : seuls les fichiers des `kept_count` dernières révisions et des révisions
  - `ensure_kept(app_id: str, item, field: str)` — Garde l'état PRÉSENT du fichier `field` avant qu'une correction à la main ne le réécrive
  - `kept_file(app_id: str, item, number: int, field: str) -> str` — Le fichier GARDÉ du champ `field` à la révision `number` (chemin relatif à MEDIA_ROOT), ''
  - `revisions_of(app_id: str, item)` — Toutes les révisions de `item`, la plus récente d'abord.
  - `current_revision(app_id: str, item)` — La dernière révision de `item`, ou None s'il n'a encore rien produit.
  - `published_revision(app_id: str, item)` — La dernière révision PUBLIÉE — la version qu'un hébergement montre. None si aucune.
  - `get_revision(app_id: str, item, number: int)` — La révision `number` de `item`. Lève `LookupError` si elle n'existe pas.
  - `outputs_changed_since(revision, item=None) -> list` — Les champs dont le fichier a changé (ou disparu) depuis `revision` — ce qui rend
  - `publish(app_id: str, item, number: int, *, user, note: str='')` — Publie la révision `number` : elle devient une VERSION. Republier la même révision
  - `unpublish(app_id: str, item, number: int)` — Retire la révision `number` des versions publiées (elle reste dans l'historique).

### Serveur MCP (adaptateur mince sur tool_api)

Un seul contrat d'outils pour TOUS les cerveaux (Ollama, Claude Code, Albert, un IDE) : `tools/list` = le registre filtré par `tool_accessible`, `tools/call` = `execute_tool` — LA porte unique. Adaptateur MINCE : aucun protocole maison, `tool_descriptions()` dérive déjà nom/description/schéma. DEUX surfaces, DEUX process : `wama` (prod) et `wama-dev`, jamais chargés ensemble. Client de la surface `wama` : l'abonnement Claude Code (2026-10-23) ; les deux process sont ARRÊTÉS à chaque relance (`start_wama_prod.sh`, ils survivaient avec du code périmé) ; la mesure d'accès : `llm_gateway_check --provider claude_code`

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

### Service de vectorisation

Un ESPACE de vecteurs par nature de média — `text` (qwen3-embedding, celui du RAG) et `media` (EmbeddingGemma-2, texte ET image : une requête écrite retrouve une image) —, un moteur UNIQUE (préparation des entrées, appel au fournisseur, contrôle des dimensions) exécuté par un service uvicorn 127.0.0.1:8002 (`vector_service.py`, à la racine comme `tts_service.py`) et son client ; service éteint, le même moteur tourne dans le process appelant. Deux espaces ne se comparent jamais ; un fournisseur distant n'entre que s'il sert le MÊME espace ; le modèle local manquant s'installe par la route (`model_key`) ; la VRAM se demande au gouverneur sur la ligne de RÉSIDENCE du modèle à l'Ollama hôte (`ollama_host_owner`, une par modèle), pour le besoin que porte sa ligne de catalogue — un chargement observé se MESURE à la carte et y est rendu (`ollama_host.measured_load`, 2026-10-20, qui mesure aussi les conversations)

- **Domicile** : `wama/common/vectors/service_client.py` · **doc** : [docs/construction/ia/WAMA_MEMORY.md §7sexies](../construction/ia/WAMA_MEMORY.md)
- **Module** : Client COMMUN du service de vectorisation (`vector_service.py`, FastAPI, uvicorn 127.0.0.1:8002). Doc : `WAMA_MEMORY.md §7sexies`. Même patron que `common/tts/service_client.py` : tout le monde vectorise par ici — le RAG (`memory/embed.py`), l'indexation des médias, le Describer.
- **API publique** (9) :
  - `service_url() -> str`
  - `embed(space_key: str, items, *, query: bool=False, timeout: float=TIMEOUT_S, keep_alive: str | None=None) -> list` — Les vecteurs de `items` dans l'espace `space_key` (même ordre), ou `[]` si indisponible.
  - `owner(space: VectorSpace) -> str` — Détenteur déclaré au gouverneur : la ligne de RÉSIDENCE de l'Ollama hôte pour ce modèle
  - `need_gb(space: VectorSpace) -> float | None` — L'empreinte VRAM du modèle de l'espace, lue au CATALOGUE par la cascade commune
  - `residency_allowed(space_key: str) -> tuple[bool, str]` — Demande au GOUVERNEUR s'il y a de la place pour garder le modèle de l'espace chargé.
  - `reserve(space_key: str, *, expires_in_s: float=None) -> bool` — Déclare la résidence au gouverneur, pour que les AUTRES process la voient. `expires_in_s` :
  - `release(space_key: str) -> bool` — Retire la réservation. ⚠ COMPTABILITÉ SEULEMENT — toujours avec `unload` : libérer sans
  - `unload(space_key: str) -> bool` — Décharge le modèle de l'espace tout de suite (`engine.unload`).
  - `available(space_key: str) -> bool` — Le modèle de l'espace est-il installé chez un fournisseur — sans le charger.

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

Range le RÉSULTAT d'un élément comme asset, lu au schéma canonique du détail : toute app qui déclare son adapter a le geste sans une ligne. Le RÔLE est FOURNI (un .mp3 peut être voix/musique/bruitage) ; une seule route pour les 10 apps. ⚠ NE CONSTRUIT AUCUN CHEMIN — `upload_to` décide du domicile, donc le geste suit la refonte des dossiers utilisateur (chiffrement) au lieu de la figer. Les 2 copies manuelles (composer + sa jumelle) DÉLÈGUENT depuis le 2026-09-12, et un gardien AST refuse qu'une vue d'app recopie le geste. Surfaces : le menu « … » / clic droit des cards, le MÊME menu dans l'arbre de fichiers sur un fichier de SORTIE (2026-09-18), l'outil d'assistant. Le bouton dédié du composer et sa route d'app (seconde porte du même geste) sont RETIRÉS le 2026-09-18 (R64, R65) : le RÔLE se DÉCLARE au commun par l'app (`result_role` du détail canonique) et `admissible_roles` filtre — extension, puis rôle déclaré, pour les 10 apps ; non déclaré = l'utilisateur choisit. DEUX archétypes (§6.4), un geste : early-binding = le fichier déjà rendu, le choix est le rôle ; late-binding (transcriber, describer, reader) = le master texte est RENDU au format choisi par le builder du ⬇ (`register_export_builder`), asset `document`, coche et retrait par format (`export_choices`). ⚠ `synthesizer` n'était PAS une copie : son écriture d'asset est l'UPLOAD d'une voix, un autre geste. ⭐ Depuis le 2026-09-27 le geste DÉPLACE au lieu de copier (décision de Fabien : « un fichier ajouté à la médiathèque doit aller dans la médiathèque ») et `file_references.repoint` fait SUIVRE tous ses porteurs — la card d'origine comprise, sinon ranger un résultat le ferait disparaître de sa card. Le RETRAIT est l'inverse exact : le fichier retourne à l'endroit noté par l'ajout (`attributes.moved_from`) tant qu'un porteur le désigne, et ne part avec l'asset que s'il n'en a plus. Même brique (`move_into_library`) pour la seconde porte, l'ajout d'un fichier du dossier temporaire (`tool_api.add_to_media_library`). Le PARTAGE n'a rien à suivre : il sert le chemin RÉEL de la ligne.

- **Domicile** : `wama/media_library/services.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §2bis](../construction/ui/CARD_DESIGN.md)
- **Module** : Le GESTE « ranger une sortie d'app dans ma médiathèque » — brique COMMUNE.
- **API publique** (21) :
  - `enrich_asset_from_file(asset) -> None` — Ce que le FICHIER dit de l'asset — MIME, taille, et les `attributes` que la sonde commune
  - `candidate_asset_types(nom_fichier: str) -> list` — Rôles d'asset admissibles pour cette extension, dans l'ordre de `ASSET_TYPES`.
  - `class LibraryAddRefused(ValueError)` — Ajout refusé (nature inconnue, format non admis, nom déjà pris, déplacement impossible) —
  - `estimate_attributes(asset_type: str, path) -> dict` — Ce qu'on peut PROPOSER des attributs demandés à l'ajout (`on_add` + `estimate`) en écoutant
  - `add_file_to_library(user, asset_type: str, *, uploaded=None, source=None, name: str='', description: str='', tags: str='', attributes=None, license: str='', au…` — Ajoute UN fichier à la médiathèque de `user`, comme asset de la nature `asset_type`.
  - `admissible_roles(detail: dict, nom_fichier: str) -> list` — Les rôles que le geste PROPOSE pour cette sortie — et donc les seuls qu'il accepte.
  - `export_choices(app: str, detail: dict) -> list` — Les CHOIX que le geste propose pour cette sortie — `[{key, label, asset_type, format}]`.
  - `export_item_to_library(user, app: str, pk: int, asset_type: str='', name: str='', output_format: str='') -> dict` — Range le RÉSULTAT d'un élément d'app dans la médiathèque de son propriétaire.
  - `move_into_library(asset, source, nom_fichier: str)` — DÉPLACE `source` dans le domicile de la médiathèque et fait SUIVRE tous ses porteurs.
  - `assets_of_item(user, app: str, pk: int)` — Les assets de `user` rangés depuis l'élément `app#pk` — par la PROVENANCE, jamais par le nom
  - `delete_asset(asset) -> None` — Supprime un asset ET son fichier, puis libère le drapeau d'app si plus rien n'en provient.
  - `in_library_by_choice(user, app: str, pk: int) -> dict` — Ce qui est DÉJÀ rangé depuis `app#pk`, indexé par la CLÉ de choix du menu — le rôle
  - `remove_item_from_library(user, app: str, pk: int, asset_type: str='', output_format: str='') -> dict` — Retire de la médiathèque ce qui a été rangé depuis `app#pk` (un rôle, un format, ou tout).
  - `gallery_assets()` — Les avatars de la galerie partagée, actifs, dans l'ordre d'affichage.
  - `gallery_entries() -> list` — `[{'name', 'url'}]` — ce dont les gabarits ont besoin, sans composer d'URL.
  - `gallery_path(name: str)` — Chemin ABSOLU de l'avatar nommé, ou `None` s'il n'existe pas (le worker en a besoin).
  - `resolve_visible_asset(user, asset_type: str, name: str) -> str` — Chemin (relatif à MEDIA_ROOT) de l'asset `name` de cette nature que `user` voit, ou ''.
  - `visible_asset_names(user, asset_type: str, attributes: dict | None=None) -> list` — Les NOMS des assets de cette nature que `user` voit (siens, partagés, système), sans doublon
  - `class SystemAssetStillNamed(RuntimeError)` — Un AUTRE utilisateur cite encore l'asset par son nom : le rendre à un seul casserait ses
  - `register_system_asset_name_holder(asset_type: str, holder) -> None` — Déclare une référence PAR NOM à un asset système d'une nature donnée.
  - `return_system_asset(asset, user, *, apply: bool=False) -> dict` — Rend l'asset système `asset` à `user` : un `UserAsset` privé, fichier déplacé chez lui.

### Vulnérabilités des dépendances

CVE des paquets INSTALLÉS du venv courant via l'API OSV.dev (pas les requirements, qui sont des bornes basses). Contrat-cliquet : la dette connue vit dans une baseline versionnée par venv, toute vulnérabilité nouvelle est rouge

- **Domicile** : `wama/common/management/commands/check_dep_vulns.py` · **doc** : [docs/construction/suivi/ROADMAP.md §16.10](../construction/suivi/ROADMAP.md)
- **Module** : check_dep_vulns — vulnérabilités connues (CVE) des dépendances Python INSTALLÉES, via l'API OSV.dev (la même base d'avis que pip-audit, Dependabot ou Aikido).
- **API publique** (4) :
  - `label_venv() -> str` — Nom du venv qui exécute (venv_win / venv_linux) = clé de section de la baseline.
  - `inventaire() -> list[tuple[str, str]]` — (nom, version) des distributions installées dans CET interpréteur.
  - `interroger_osv(paquets: list[tuple[str, str]]) -> dict[str, list[str]]` — {"nom==version": [ids OSV]} — lève si l'API est injoignable.
  - `class Command(BaseCommand)`

### Évaluation d'un résultat contre sa référence

Une app DÉCLARE son évaluation (`register_evaluation` : champ de la référence, lecture du résultat et de la référence, modèle, métriques) et la brique fait le reste : pose la référence sur un élément OU un lot (un seul fichier, partagé), mesure, conserve la mesure par élément (`ResultEvaluation` — modèle, échelle, sens, identité de la référence : ce que l'indice interne des modèles agrégera) et compare les modèles d'un lot (taux de CORPUS, et dit quand les références diffèrent). SANS référence, l'accord entre moteurs d'une même entrée (M1 deux à deux, médiane M6, jamais de « meilleur »). Va avec la capacité `has_reference_result` — un test refuse l'une sans l'autre. 2026-10-22 : les MESURES SANS RÉFÉRENCE d'une sortie (`register_check`), déclarées par process (`ProcessSpec.checks`), jouées par le squelette, gardées sur la ligne du process et montrées par la bande des process et la face « Évaluation » — la part de la parole qu'une transcription couvre, avec « Relancer avec » le modèle local

- **Domicile** : `wama/common/services/result_evaluation.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : Évaluation d'un résultat contre sa RÉFÉRENCE — la brique commune que chaque app adopte par une DÉCLARATION (`register_evaluation`), jamais par du code d'évaluation à elle.
- **API publique** (20) :
  - `class EvaluationSpec` — Ce qu'une surface déclare pour être évaluable. Voir l'en-tête du module.
  - `register_evaluation(spec: EvaluationSpec) -> None` — Appelé depuis le `apps.py:ready()` de l'app — le registre ne connaît jamais ses apps.
  - `evaluation_spec(surface: str) -> Optional[EvaluationSpec]`
  - `evaluable_surfaces() -> List[str]`
  - `evaluable_surface_of(element_model) -> Optional[str]` — La surface ÉVALUABLE dont `element_model` est le modèle d'élément, None sinon.
  - `clear(surface: str, item) -> None` — Retire la mesure d'un élément (référence retirée, résultat disparu).
  - `evaluate(surface: str, item) -> List` — Mesure le résultat COURANT de `item` contre sa référence ; rend les lignes écrites.
  - `item_evaluation(surface: str, item) -> Optional[dict]` — La mesure d'un élément, prête pour l'onglet « Évaluation » ; None s'il n'y en a pas.
  - `evaluation_text(measure: dict) -> str` — La mesure d'`item_evaluation` en TEXTE — ce que Copier emporte de la face « Évaluation »
  - `class Check` — Une mesure sans référence de la sortie d'un process. `measure(app_id, item, pipeline,
  - `register_check(check: Check) -> None` — Inscrit une mesure ; un process la DÉCLARE par sa clé (`ProcessSpec.checks`).
  - `run_checks(app_id: str, item, task_id: str='') -> list` — Joue les mesures DÉCLARÉES des process que ce lancement a rendus (ligne `SUCCESS` de la
  - `item_checks(item) -> list` — Les mesures sans référence gardées sur les lignes de l'élément, dans l'ordre du pipeline,
  - `batch_evaluation(surface: str, items: Iterable) -> Optional[dict]` — Comparaison des modèles d'un lot — le résumé de la ligne de la card mère.
  - `batch_agreement(surface: str, items: Iterable) -> Optional[dict]` — Le désaccord entre les moteurs d'un lot, SANS référence (`WAMA_QUALITE` M1, M6).
  - `class ReferenceRefused(ValueError)` — La référence ne peut pas être posée — le motif est DIT à l'utilisateur.
  - `attach_reference(surface: str, targets: List, uploaded) -> dict` — Pose UNE référence sur un ou plusieurs éléments (une card, ou toutes celles d'un lot).
  - `attach_result(surface: str, item, uploaded) -> dict` — Pose un RÉSULTAT EXISTANT sur un élément (port `work_result`) : il tient lieu de traitement.
  - `detach_result(surface: str, item) -> int` — Retire le fichier du résultat existant. Le RÉSULTAT de l'élément reste tel quel jusqu'à
  - `detach_reference(surface: str, targets: List) -> int` — Retire la référence d'éléments ; le fichier n'est supprimé que s'il n'est plus désigné.

## Contenu & prompts

### Accès LLM

Route unique vers les LLM (tiers déclaratifs, sélection catalogue, Ollama local). `chat_with_catalog_model` (2026-09-30) : un appel désigné par une CLÉ DE CATALOGUE (`auto`, `ollama:…`, `albert:…`, `anthropic:…`), lue par `model_keys.split_key` — ce qu'appelle une app dont le réglage « Modèle » est tiré du catalogue (route F4b). `chat_with_source` (2026-10-01) : l'appel à un fournisseur DÉCLARÉ avec la clé de l'UTILISATEUR (garde commune `cloud_access`, refus levé avec son statut) — partagé par l'assistant et les apps, il vivait en privé dans l'assistant. `auto` y est REFUSÉ : il se tire AVANT l'appel — `auto_model.resolve_model_choice` dans une app (le chemin de la prévision « Prévu : … »), `modele_par_defaut` hors app (2026-10-01 : un repli interne faisait annoncer un modèle et en lancer un autre). La TEMPÉRATURE (2026-10-21) : `None` = celle du MODÈLE, rien n'est envoyé, en local comme en distant ; une tâche sans réglage passe `STEADY_TEMPERATURE` par son nom. La GRAINE et le TOP P (2026-10-22) : `seed`, `top_p` explicites, rien d'envoyé sans réglage, à une source distante compatible OpenAI seulement

- **Domicile** : `wama/common/utils/llm_utils.py`
- **Module** : WAMA Common — LLM utilities Shared Ollama client for use in Celery workers (transcriber, describer, ...).
- **API publique** (23) :
  - `get_describer_model(content_type: str, output_style: str) -> str` — Return the Ollama model name to use for a given (content_type, output_style) pair.
  - `designated_local_model(key: str, role: str='langage', owner: str='Cette application') -> str` — Le nom Ollama d'une clé `ollama:<nom>` ; `ValueError` pour toute autre source.
  - `card_llm(key: str, auto=None, owner: str='Cette application')` — `(nom, fournisseur)` du modèle de langage qu'une card demande : sous « auto », `auto()`
  - `ollama_catalog_key(name: str) -> str` — La clé de catalogue d'un modèle Ollama nommé — ce qu'une ligne d'exécution retient.
  - `modele_par_defaut() -> str` — Modèle LLM à utiliser quand l'appelant n'en impose aucun — résolu, jamais figé.
  - `modele_par_tier(tier: str='default', exige=None, priority=None, prefer_loaded: bool=True) -> str` — Résolution PUBLIQUE d'un tier (`heavy`/`default`/`fast`) — même mécanique que
  - `ollama_chat(messages: list, model: str='', num_predict: int=2048, num_ctx: Optional[int]=None, think: bool=True, timeout: float=180.0, keep_alive: Optional[str…` — Send a chat request to the local Ollama server.
  - `declared_llm_source(provider: str)` — La source `external_sources` d'un fournisseur DISTANT que `llm_chat` sait appeler, ou None.
  - `openai_compatible_source(provider: str) -> str` — La source `external_sources` d'un fournisseur qui parle le protocole OpenAI depuis une
  - `default_cloud_model(provider: str) -> str` — Modèle par défaut d'un fournisseur cloud : réglage déclaré, sinon celui de sa source
  - `provider_saturation(exc, wait_s: float=RATE_LIMIT_WAIT_S)` — (portée, durée, motif) quand l'échec dit que le FOURNISSEUR est saturé ou en panne — None
  - `llm_chat(messages: list, model: str=None, provider: str=None, num_predict: int=2048, num_ctx: Optional[int]=None, think: bool=True, timeout: float=180.0, api_k…` — Unified LLM chat function — provider-agnostic entry point.
  - `tool_call_text(name: str, arguments) -> str` — Un appel d'outil NATIF (nom + arguments JSON du fournisseur) rendu dans la forme texte de
  - `chat_with_catalog_model(catalog_key: str, messages: list, *, user=None, num_predict: Optional[int]=None, think: bool=False, timeout: Optional[float]=None, temp…` — Un appel LLM désigné par une CLÉ DE CATALOGUE (`ollama:qwen3.8:latest`,
  - `chat_with_source(source: str, model_id: Optional[str], messages: list, *, user=None, num_predict: Optional[int]=None, think: bool=False, timeout: Optional[floa…` — Un appel à un fournisseur LLM DÉCLARÉ (`external_sources`, type `llm` : Albert, API
  - `extract_json_from_llm(text: str) -> Optional[dict]` — Extract the first valid JSON object from an LLM response.
  - `generate_meeting_summary(text: str, language: str='fr', speakers: Optional[list]=None, model: str='', provider: Optional[str]=None, temperature: Optional[float…` — Generate a structured meeting summary (compte-rendu de réunion).
  - `verify_text_coherence(text: str, content_hint: str='transcription', language: str='fr', model: str='', provider: Optional[str]=None, temperature: Optional[floa…` — Verify text coherence and suggest corrections.
  - `build_coherence_report(score, notes, suggestion, original) -> Optional[dict]` — Le rapport de `verify_text_coherence` tel qu'un élément l'a GARDÉ, sous la forme que
  - `coherence_report_text(report: dict) -> str` — Le rapport en TEXTE — ce que Copier emporte et ce qui identifie la face.
  - `analyze_segments_coherence(segments: list, language: str='fr', model: str='', provider: Optional[str]=None, temperature: Optional[float]=STEADY_TEMPERATURE, se…` — Analyse la cohérence PAR SEGMENT (1 seul appel LLM).
  - `suggest_speaker_names(segments: list, language: str='fr', model: str='', provider: Optional[str]=None, temperature: Optional[float]=STEADY_TEMPERATURE, seed: O…` — Propose des noms d'intervenants à partir des présentations dans la transcription.
  - `generate_structured_summary(text: str, content_hint: str='transcription', language: str='fr', model: str='', provider: Optional[str]=None, temperature: Optiona…` — Generate a structured summary (summary, key_points, action_items).

### Appariement d'identité de canal

Relie une identité Matrix/Discord à un compte WAMA par code prouvé hors canal — la garde que tout adaptateur appelle avant d'agir

- **Domicile** : `wama/gateway/services.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19](../construction/suivi/ROADMAP.md)
- **Module** : Passerelle de canaux — appariement d'identité et résolution du compte.
- **API publique** (7) :
  - `class PairingError(Exception)` — Refus d'appariement — le message est destiné à l'utilisateur final.
  - `request_link(channel: str, external_id: str, external_label: str='') -> ChannelLink` — Enregistre (ou renouvelle) une demande de liaison et rend la ligne portant le code.
  - `pairing_url(code: str) -> str` — URL que le QR d'appariement encode : la page de profil, code prérempli.
  - `confirm_link(user, code: str) -> ChannelLink` — Scelle la liaison au profit de `user` — appelé DEPUIS WAMA, session authentifiée.
  - `account_for(channel: str, external_id: str)` — Compte WAMA d'une identité de canal, ou None.
  - `linked_identity(user, channel: str)` — L'identité CONFIRMÉE de ce compte sur ce canal (`external_id`), ou None. L'inverse de
  - `unlink(user, channel: str, external_id: str) -> bool` — Supprime une liaison — uniquement une des SIENNES. Rend True si quelque chose a sauté.

### Claude Code sur abonnement

Délègue une tâche de développement au CLI Claude Code en headless — lecture seule par défaut, environnement construit sans la clé API. Pour un compte, le CLI reçoit la surface MCP `wama` (`--mcp-config` seule lue, jeton d'API par l'environnement, outils `mcp__wama`) : il voit les outils de WAMA, par la porte `execute_tool` (2026-10-23). Binaire Windows : ses secrets passent par `WSLENV`, sans quoi l'interop les perdait — le jeton personnel compris

- **Domicile** : `wama/common/services/claude_code.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19.3](../construction/suivi/ROADMAP.md)
- **Module** : Appel de Claude Code en mode headless, SUR L'ABONNEMENT du titulaire.
- **API publique** (8) :
  - `class ClaudeCodeIndisponible(RuntimeError)` — Le CLI est absent ou inexploitable — message destiné à l'utilisateur.
  - `subscription_allowed(user) -> bool` — Qui a le droit de consommer l'abonnement du titulaire — DOMICILE UNIQUE de la règle.
  - `chemin_cli() -> str` — Chemin du CLI Claude Code, ou lève une erreur explicite.
  - `declared_model_ids() -> tuple` — Identifiants de modèle que l'abonnement DÉCLARE (`ExternalSource.declared_models` de la
  - `wama_mcp_config(user) -> tuple` — `(config JSON, {variable: jeton})` de la surface `wama` du serveur MCP pour `user` — ou
  - `prepare(prompt: str, *, outils=OUTILS_LECTURE, ecriture: bool=False, user=None, model: str='') -> dict` — La commande du CLI et son environnement, GARDES COMPRISES — `{'argv', 'env'}` ou
  - `read_output(raw: str) -> dict` — Le résultat d'une sortie `--output-format json` déjà écrite — celle d'une tâche détachée,
  - `demander(prompt: str, *, cwd: str | None=None, delai: int=DELAI_DEFAUT, outils=OUTILS_LECTURE, ecriture: bool=False, user=None, model: str='') -> dict` — Soumet UNE tâche à Claude Code et rend son résultat.

### Export document

Génère PDF (fpdf2) / DOCX (python-docx) depuis les résultats d'app

- **Domicile** : `wama/common/utils/document_export.py`
- **Module** : WAMA — Document Export Utilities Génération de fichiers PDF (fpdf2) et DOCX (python-docx) à partir des résultats des applications Describer et Transcriber.
- **API publique** (8) :
  - `strip_markdown(text: str) -> str` — Le texte SANS sa mise en forme Markdown, paragraphes gardés — pour le PDF, le DOCX et, depuis
  - `generate_description_pdf(description) -> bytes` — Generate a PDF from a Description instance.
  - `generate_description_docx(description) -> bytes` — Generate a DOCX from a Description instance. Returns raw bytes.
  - `generate_transcript_txt(transcript) -> bytes` — Génère un .txt mis en forme : avant-propos (titre/date/intervenants) + blocs
  - `generate_transcript_pdf(transcript) -> bytes` — Generate a PDF from a Transcript instance. Returns raw PDF bytes.
  - `generate_reader_pdf(item) -> bytes` — Generate a PDF from a ReadingItem instance. Returns raw PDF bytes.
  - `generate_reader_docx(item) -> bytes` — Generate a DOCX from a ReadingItem instance. Returns raw bytes.
  - `generate_transcript_docx(transcript) -> bytes` — Generate a DOCX from a Transcript instance. Returns raw bytes.

### Fin de tâche racontée dans le fil d'origine

La fin d'un traitement (notification `job_done`/`job_failed`, qui DÉSIGNE l'élément) racontée dans le fil de l'assistant d'où la tâche a été demandée : origine LUE dans les étapes d'outils persistées (`tool_api.items_of_step`), geste « statut » RÉELLEMENT joué, sorties déclarées, enregistrement au fil — une fois, sous verrou, AVANT publication (`tell`). Commun aux surfaces : la passerelle la relève par un curseur de canal, joint les fichiers, et republie au retour du canal ce que le fil a raconté (`told_since`) et que le salon ne montre pas ; le fil WEB par la relève de la cloche (`wama:notifications`), le chat la DIT. Une fin arrivée PENDANT le tour qui l'a lancée part avec sa réponse (`notices_of_turn`, joint par `conversation_turn` ; `tell` raconte une seule fois). Et l'entre-deux (2026-10-20) : les éléments encore en cours suivis SOUS la réponse, dans l'état de leur card (`turn_jobs` → `tool_api.job_progress`, `api/ai-chat/jobs/`), leur fin demandant la relève

- **Domicile** : `wama/common/services/job_follow_ups.py` · **doc** : [docs/construction/suivi/ROADMAP.md §19.2](../construction/suivi/ROADMAP.md)
- **Module** : La FIN D'UNE TÂCHE racontée dans le fil d'où elle a été demandée — brique commune à toute surface de l'assistant (canaux de la passerelle, fil web).
- **API publique** (14) :
  - `notice_text(note) -> str` — Le texte d'une fin de tâche : son titre (« … terminé » / « … a échoué ») et son détail.
  - `origin_conversation(note, surface: str)` — Le fil de CETTE surface où l'élément de la notification a été créé ou lancé — lu dans les
  - `dev_origin_conversation(note, surface: str)` — Le fil de CETTE surface dont une étape `dev_*` a rendu le `job_id` de la notification — la
  - `status_step(note, user) -> dict` — Le geste « statut », RÉELLEMENT joué : c'est l'étape que l'échange enregistre au fil. Une
  - `declared_output_urls(note) -> list` — Les sorties DÉCLARÉES de l'élément d'une fin RÉUSSIE, en URL `/media/…` décodées
  - `origin_of(note, surface: str)` — Le fil d'origine d'une notification sur cette surface, quelle que soit la nature de la
  - `already_told(conversation, note) -> bool` — Cette fin a-t-elle déjà été racontée dans ce fil ? Une notification se relève par chaque
  - `record(conversation, note, response: str, step: dict) -> None` — Enregistre au fil la fin de tâche — un échange comme un autre
  - `told_since(surface: str, since) -> list` — Les fins RACONTÉES sur cette surface depuis `since`, relues du fil tel que `record` l'écrit :
  - `turn_designations(steps) -> tuple` — Ce qu'un tour a désigné : `({(famille, id)}, {job_id})` — les éléments d'app lus par
  - `turn_jobs(user, steps, in_flight_only: bool=True) -> list` — Les éléments qu'un tour a créés ou lancés, chacun dans l'état de sa card (`tool_api.
  - `notices_of_turn(user, steps, since) -> list` — Les fins de tâche ARRIVÉES PENDANT un tour, pour ce qu'il a désigné — ids de notification.
  - `tell(note, surface: str, compose)` — Raconte UNE fin de tâche dans son fil d'origine sur cette surface, une seule fois :
  - `web_follow_ups(user, notification_ids, absolute=lambda url: url) -> list` — Les fins de tâche à raconter dans le fil WEB de `user`, pour les notifications que sa cloche

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
- **API publique** (8) :
  - `thread(user, surface: str='web', thread_key: str='') -> Conversation` — Le fil de cet utilisateur pour cette surface — créé au besoin.
  - `history(conversation, limite: int=MAX_TOURS) -> list` — Les derniers tours du fil, au format attendu par `run_assistant_turn`.
  - `record_exchange(conversation, message: str, resultat: dict) -> None` — Enregistre le tour utilisateur ET la réponse de l'assistant, en une transaction.
  - `last_loaded_domain(conversation, limite: int=MAX_TOURS) -> str` — Domaine chargé au cours du fil (`charger_competence`, du plus récent au plus ancien), ou ''.
  - `display_entries(conversation, limite: int=60) -> list` — Les derniers tours du fil au format d'AFFICHAGE d'une surface : les étapes d'outils
  - `conversations_of(user, limite: int=50) -> list` — Fils d'un utilisateur, le plus récemment actif d'abord (liste d'UI).
  - `clear(user, conversation_id: int) -> bool` — Supprime UN fil — uniquement l'un des SIENS.
  - `clear_thread(user, surface: str='web', thread_key: str='') -> bool` — Supprime le fil NOMMÉ `(user, surface, thread_key)` — le geste « Effacer » du chat web et

### Ingest de source

Télécharge une source distante vers le FileField, déclaré par WAMA_INGEST. ⭐ Depuis le 2026-10-13 (décision de Fabien) : DÈS LA CRÉATION, hors requête — récepteur `post_save` sur tout modèle à WAMA_INGEST → tâche `common.ingest_source` (file default) ; le lancement rattrape un échec et attend un téléchargement en cours (verrou partagé). `derive` (chemin pointé) DÉCLARÉ dans la spec ; une page web gardée en `.html` ; nature d'une URL AVANT téléchargement : `url_ingest.url_nature` (même table que la décision page/média). Depuis le 2026-10-20 : `download_to_user`, l'URL d'une entrée qui n'est pas encore une card (card d'entrée du Studio) — mêmes primitives, déposée dans l'espace du compte comme un fichier du gestionnaire ; `declared_mode`, le mode que l'app destinataire DÉCLARE dans son `WAMA_INGEST`

- **Domicile** : `wama/common/utils/source_ingest.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : source_ingest — Ingest média DÉCLARATIF et COMMUN (hors common/manifests/**).
- **API publique** (8) :
  - `is_remote(ref) -> bool` — Cette entrée est-elle une URL à télécharger (http, https) plutôt qu'un chemin ?
  - `declared_mode(model) -> str` — Le mode (`audio` | `smart` | `media`) qu'un modèle d'élément DÉCLARE pour son entrée
  - `download_to_user(user, url, mode='media') -> str` — Télécharge `url` dans l'espace temporaire de `user` et rend son chemin (relatif à
  - `ensure_local_input(instance, *, console=None, derive=None)` — Si `instance` déclare `WAMA_INGEST` et a une URL dans son champ source mais
  - `ingest_state(instance)` — Ce que l'Entrée d'une card peut dire de sa SOURCE distante tant que le fichier manque :
  - `ingest_now(instance)` — Le téléchargement DE CRÉATION (tâche `common.ingest_source`) : `ensure_local_input`, avec
  - `schedule_ingest(instance) -> bool` — Met en file le téléchargement de l'entrée d'une card dont la source est une URL http(s)
  - `register_source_ingest_receivers()` — Branche le récepteur sur tout modèle qui DÉCLARE `WAMA_INGEST` — aucune app n'écrit rien.

### Intake universel de fichiers

Que peut faire WAMA de ce fichier ? — ports d'app + lot + manifeste + médiathèque + sondes des mondes (outil assistant inspect_user_file)

- **Domicile** : `wama/common/utils/intake.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : intake — « Que peut faire WAMA de ce fichier ? » : l'index inverse type → capacités (COMMUN).
- **API publique** (2) :
  - `register_intake_probe(key: str, fn) -> None` — Un monde déclare sa sonde d'intake (appelé depuis son `apps.py:ready()`).
  - `capabilities_for_path(path) -> dict` — Chemin de fichier → cibles typées AVEC leur rôle, composées des déclarations.

### Moteur de l'assistant IA

Boucle agentique multi-surface (prompts, outils tool_api, local/cloud) — la vue web et /api/v1/assistant/chat/ en sont des clients. Porte aussi les SOUS-AGENTS et le COUNCIL (2026-10-29, `WAMA_HARNESS §7.4`) : bornes d'un tour, verbe `delegate` (vagues parallèles par serveur, agents du registre de 1 à n, vote / décideur / relecture croisée), réglage « Sous-agents » auto + curseur

- **Domicile** : `wama/common/services/assistant_engine.py`
- **Module** : Moteur de l'assistant IA — boucle agentique multi-surface (chantier « passerelle de canaux », étape 0).
- **API publique** (13) :
  - `web_voice_prompt(user, surface: str) -> str` — La consigne de voix et d'avatar de la surface web, avec l'état de CET utilisateur —
  - `surface_attaches_files(surface: str) -> bool` — La réponse de cette surface est-elle publiée par un ADAPTATEUR qui joint les fichiers ?
  - `turn_model_key(provider, llm_model) -> str` — Clé de CATALOGUE du modèle d'un tour (`albert:…`, `ollama:…`) — '' sans modèle nommé.
  - `expected_wait(model_key: str) -> float` — Attente APPRISE avant le premier texte d'un tour par ce modèle, en secondes — 0 tant
  - `assistant_settings(user) -> dict` — Réglages DURABLES de l'assistant pour `user` (brique commune `user_settings`, app
  - `resolve_turn_model(user, provider=None, model=None, domain=None) -> tuple` — (fournisseur, modèle) d'un tour — le fournisseur SE DÉRIVE du modèle, comme partout
  - `thinking_wanted(quality_intent) -> bool` — La réflexion du modèle est-elle demandée pour ce réglage de curseur ?
  - `delegation_wanted(settings: dict) -> bool` — Les sous-agents sont-ils proposés au modèle ? Le geste commun « auto + curseur + manuel » :
  - `native_tool_list(user, dev_tools: list=(), names=None) -> list` — La liste des outils au format standard (`tools=`) que reçoit un modèle déclaré
  - `warm_up() -> dict` — Remplit les caches de processus du tour d'assistant — `{étape: secondes | 'erreur : …'}`.
  - `message_with_deposits(text: str, paths) -> str` — Le message d'un tour qui DÉPOSE des fichiers dans l'espace de l'utilisateur — UNE graphie
  - `conversation_turn(user, message: str, *, surface: str='web', thread_key: str='', provider: str=None, model: str=None, domain: str=None, on_event=None) -> dict` — UN tour, avec historique PERSISTÉ côté serveur — la voie normale pour une surface.
  - `run_assistant_turn(user, message: str, provider: str=None, model: str=None, history: list=None, domain: str=None, surface: str='web', on_event=None, escalated_…` — UN tour de conversation avec l'assistant WAMA — cœur SANS ÉTAT, commun à toutes les

### Pages qu'un utilisateur peut ouvrir (« emmène-moi sur… »)

Les pages du menu Applications — apps du catalogue et surfaces déclarées, lues par `get_app_groups` — filtrées par le DROIT du menu (`accessible_apps`) mais pas par la préférence d'affichage, qui ne retire aucun droit. Sert l'outil `open_page` ; le chat web suit la page une fois la réponse dite (`applyActions`, 2026-10-11). Et depuis le 2026-10-14 les pages du COMPTE (profil, journal, calendrier, catalogues…), DÉCLARÉES par l'app qui les porte (`register_account_page`) : le menu du compte en est GÉNÉRÉ, et leur droit est celui de la requête réelle (`can_open_page` : fermeture au visiteur, politique du chemin, décorateur de la vue) — une garde de PARITÉ confronte chaque déclaration à la réponse de sa vue

- **Domicile** : `wama/common/services/navigation.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : Les PAGES qu'un utilisateur peut ouvrir — ce que l'assistant propose quand on lui demande « emmène-moi sur… » (outil `open_page`, 2026-10-11), et le menu du compte (2026-10-14).
- **API publique** (5) :
  - `account_pages_for(user, allowed_apps=None) -> list` — Les pages du COMPTE que `user` peut ouvrir, dans l'ordre du menu : `[{'key', 'label',
  - `account_menu(user, allowed_apps=None) -> list` — Le menu du COMPTE de `user` : `[{'key', 'label', 'pages': […]}]`, une entrée par section
  - `navigable_pages(user) -> list` — Les pages que `user` a le DROIT d'ouvrir : `[{'key', 'label', 'url', 'world',
  - `find_page(user, page: str)` — La page que `page` désigne (clé, libellé ou alias, casse et accents ignorés) parmi celles
  - `absolute_url(path: str) -> str` — L'adresse COMPLÈTE d'une page, pour une surface hors navigateur (un canal) — '' si

### Pipeline de prompts

Traduction/enrichissement centralisés, déclarés par PROMPT_TARGETS ; fichiers de référence compris et repliés (`reference_field`), lus pour leur CONTENU ou leur FORME (`reference_reading`, 05/10 — le modèle de mise en page du Writer)

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
  - `search_web(query: str, max_results: int=5, user=None) -> list` — Recherche web → [{'title', 'url', 'snippet'}], au plus `max_results` (borné 1-10).
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

### Traduction de texte

Traduit un texte d'une langue à l'autre : passthrough si source = cible, cache (clé : modèle, langues, glossaire, texte), glossaire de termes à ne pas traduire, découpage par paragraphes, `on_chunk` pour l'aperçu « pendant ». Le modèle est une CLÉ DE CATALOGUE (défaut `ollama:translategemma:12b`) : locale par la voie Ollama gouvernée, distante par `chat_with_catalog_model` avec la clé de l'utilisateur. `lang_routing` DÉCIDE quand traduire une consigne avant un modèle qui ne parle pas sa langue ; le service EXÉCUTE

- **Domicile** : `wama/common/utils/translator.py` · **doc** : [docs/construction/suivi/ROADMAP.md §10](../construction/suivi/ROADMAP.md)
- **Module** : TranslatorService (ROADMAP §10.B) — exécute une décision de routing langue ([[lang_routing]]).
- **API publique** (1) :
  - `class TranslatorService`

## Manifestes & registres

### Adoption des mécanismes

Qui consomme quoi (imports + briques front), niveau APP vs infrastructure, et jonction registre↔grille : mécanisme adopté par des apps que rien ne vérifie

- **Domicile** : `wama/common/services/mecanismes_scan.py` · **doc** : [docs/construction/architecture/WAMA_MECANISMES.md](../construction/architecture/WAMA_MECANISMES.md)
- **Module** : Balayage d'ADOPTION des mécanismes : qui consomme quoi, et à quel niveau.
- **API publique** (10) :
  - `python_modules(base: Path)` — Chemins .py de notre code (relatifs à base), vendored et artefacts élagués.
  - `front_sources(base: Path)` — Chemins .html/.js de notre front (templates + static d'app), relatifs à base.
  - `load_sources(base: Path | None=None) -> dict[str, str]` — {chemin relatif: contenu} pour tout le corpus balayé. Coûteux : à charger UNE fois.
  - `consumers(mechanism, sources: dict[str, str]) -> list[str]` — Fichiers qui IMPORTENT le domicile (ou une annexe), hors le mécanisme lui-même.
  - `code_only(rel: str, src: str) -> str` — Le source SANS sa prose (2026-10-19) : ce qu'il fait, pas ce qu'il raconte, positions
  - `owners_of_path(path: str) -> list` — Les mécanismes qui tiennent un fichier nommé comme une PAGE le nomme — un statique comme
  - `consuming_apps(mechanism, sources: dict[str, str], found=None) -> list[str]` — Apps du catalogue dont au moins un fichier NON-HARNAIS consomme le mécanisme.
  - `adoption_matrix(sources: dict[str, str] | None=None) -> dict` — Mesure complète, UNE passe : {key: {'consommateurs': [...], 'apps': [...], 'niveau_app': bool}}.
  - `mechanisms_without_criterion(sources: dict[str, str] | None=None) -> list[tuple]` — LE contrôle de jonction : mécanismes de NIVEAU APP qu'AUCUN critère de grille ne vérifie.
  - `orphan_criteria() -> list[str]` — Garde-fou SYMÉTRIQUE : critère dont le `mechanism=` ne correspond à aucune clé du registre.

### Aperçu « pendant » à plusieurs vues

Un worker publie plusieurs vues du même instant (`publish_partial(variant=, label=)`, publieur de partiels limité dans le temps `PartialFrames` — frames JPEG, et le SON déjà produit en WAV avec ses pics depuis le 2026-10-20) ; la face PENDANT de l'aperçu les liste et sert celle demandée (`?variant=`), le volet et la visionneuse affichent le bouton de bascule (`WamaMediaPreview.variantToggle`, brique d'aperçu `preview` — il vivait dans l'inspecteur jusqu'au 2026-10-13). Né le 2026-10-04 pour basculer entre détection et floutage de l'anonymizer — toute app peut publier ses vues

- **Domicile** : `wama/common/utils/preview_utils.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common - Preview Utilities
- **API publique** (17) :
  - `get_or_create_anonymous_user()` — Get or create the anonymous user.
  - `file_face(url, path=None, name=None)` — Payload d'aperçu d'UN fichier : `{name, url, mime_type}`, plus `content` (le texte
  - `server_peaks(url: str)` — `{peaks, duration}` de l'audio servi à `url` quand il est trop lourd pour le navigateur —
  - `is_work_input(app_name, name) -> bool` — Le fichier `name` (chemin ou URL) peut-il être l'ENTRÉE de la card ? LA règle de la face
  - `work_input_name(app_name, instance) -> str` — Le fichier d'ENTRÉE de la card (relatif à MEDIA_ROOT) : la clé `source_file` de sa spec de
  - `publish_partial(app_name, pk, url_or_path, variant=None, label=None)` — Worker : publie l'URL (média) d'un aperçu PARTIEL courant, servi par `?side=during`.
  - `class PartialFrames` — L'aperçu « pendant » d'un traitement en cours, en FICHIERS : une frame (ou plusieurs
  - `publish_partial_peaks(app_name, pk, peaks, duration=None)` — Worker : publie des PICS d'onde partiels (« waveform par parties », cf. `waveform.compute_peaks`)
  - `emit_streaming_peaks(app_name, pk, pcm, sr, buckets=800)` — Worker de streaming (COMMUN, toute app) : calcule les pics uint8 d'une fenêtre PCM courante
  - `publish_partial_text(app_name, pk, text)` — Worker : publie le TEXTE partiel courant (transcription/description qui se construit),
  - `get_partial_text(app_name, pk)` — Lecture du texte partiel (endpoints de progression des apps + `?side=during`).
  - `clear_partial(app_name, pk)` — Worker : retire l'aperçu partiel (fin de traitement — la face SORTIE prend le relais).
  - `unified_preview(request, app_name: str, pk: int)` — Unified preview endpoint for any registered app.
  - `with_playback_copy(data, request)` — Une vidéo que le navigateur ne lit pas est servie par sa COPIE DE LECTURE quand elle
  - `register_app_preview(app_name: str, model_class, file_field: str='input_file', user_field: str='user', duration_field: str=None, width_field: str=None, height_…` — Convenience function to register an app with common field patterns.
  - `anonymizer_preview_adapter(media, request)` — Custom adapter for Anonymizer Media model. None once the input file is RELEASED (the
  - `transcriber_preview_adapter(transcript, request)` — Custom adapter for Transcriber Transcript model.

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

Jumelle <app>_NN coexistante pour comparaison Playwright + diff par témoins (route §10.3 marches S/S2) — registre sandbox_apps.json injecté au boot (INSTALLED_APPS/urls/gating/catalogue) ; create/drop symétriques + `substitute <label> <cible>` : remplace UN fichier copié par sa version GÉNÉRÉE (cibles = gabarits `codegen`), témoin `.temoin` préservé, re-mesure, auto-revert sur échec — verdicts journalisés au registre ; `revert <label> <cible>` ramène une cible au témoin à la demande. TROIS JUGES depuis le 03/09, chacun né d'un défaut qui RENDAIT (page 200) sans FONCTIONNER : ① cohérence de paquet par AST (tout `from .x import Y` intra-paquet, imports PARESSEUX compris, doit résoudre) ; ② couple views↔templates (substituer les templates seuls = boutons morts) ; ③ smoke « file HABITÉE » (témoin créé→page rendue→supprimé : une file vide ne rend AUCUNE card, donc ne teste rien du rendu de card). Le gate d'acceptation d'une jumelle reste sa BATTERIE UI auto-dérivée (11 scénarios `<label>.*` du registre nocturne) : describer_01 = 11/11. Depuis le 2026-10-20 : la chaîne en UNE commande (`substitute <label> a,b+c,…`, seconde passe des groupes revenus, puis leur union — `models` compris quand le modèle copié tient le nœud), et UN sous-processus de juge par substitution (`check`, page, file habitée) — un démarrage de Django coûte ≈ 60 s sous WSL

- **Domicile** : `wama/common/sandbox.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Bac à sable d'apps — jumelles EXÉCUTABLES (route §10.3, marche S, actée Fabien 2026-08-18).
- **API publique** (19) :
  - `load_registry() -> list` — Liste des jumelles [{label, generated_from, created, created_by?}] — [] si registre
  - `twin_owner(label: str) -> str` — Username du créateur d'une jumelle ('' si CLI/inconnu) — consommé par la dérogation
  - `twin_source(label: str) -> str` — App SOURCE d'une jumelle ('' si ce label n'en est pas une).
  - `declaring_app(app: str) -> str` — L'app dont la DÉCLARATION fait foi pour `app` : elle-même, ou sa SOURCE si c'est une
  - `retarget_callable(fn, label: str)` — Un geste de l'app SOURCE re-ciblé sur une jumelle : `fn` appelé avec `app_label=label` FIXÉ
  - `exposed_names(tree) -> set` — Les noms qu'un module EXPOSE (arbre AST) : définis, affectés ou importés au niveau du
  - `resolves(dotted: str, root: Path=None) -> bool` — Le chemin pointé `wama.<…>` désigne-t-il un module, ou un nom DÉFINI au niveau d'un module,
  - `inject_sandbox_registry(registry: dict, *, runnable=None) -> None` — Entrées d'un registre INDEXÉ PAR APP pour les jumelles : la déclaration de la source,
  - `born_declaration(label: str, facet: str)` — Facette DÉCLARÉE d'une app créée DE ZÉRO (`app_sandbox create --from-manifest`), telle que
  - `save_registry(entries: list) -> None`
  - `sandbox_labels() -> list` — Labels des jumelles dont le PACKAGE existe réellement (garde anti-registre orphelin :
  - `is_test_module(rel_parts) -> bool` — Le fichier (chemin RELATIF au paquet, en parties) est-il un module de TEST ?
  - `is_copied_twin_test(module_name: str, labels=None) -> bool` — Le module de test `module_name` (`wama.<jumelle>.tests_x`) est-il un test COPIÉ d'une
  - `twins_with_copied_views() -> set` — Labels des jumelles dont les VUES sont une COPIE figée de l'app source (non régénérées).
  - `sandbox_installed_apps() -> list` — Entrées INSTALLED_APPS des jumelles (consommé par settings.py).
  - `sandbox_urlpatterns()` — URLconfs des jumelles — préfixe = label (underscore assumé : `/converter_01/` — le
  - `inject_sandbox_access(default_app_access: dict, app_group: dict) -> None` — Gating DEV-ONLY des jumelles (contrat marche S §3) + groupe d'affichage dédié.
  - `inject_sandbox_catalog(app_catalog: dict) -> None` — Entrées APP_CATALOG des jumelles : CLONE de l'app source (mêmes conventions — la
  - `non_sandbox_apps(app_catalog: dict) -> list` — Apps RÉELLES du catalogue (les jumelles sont exclues de la grille de conformité :

### Backends PROPOSÉS par un rôle LLM (marche B2)

Le rôle `backend` (wama-dev-ai/run_backend.py) écrit le backend d'un modèle installé ; ce module le JUGE (forme : contrat, ENGINE, SUPPORTED_MODELS au niveau module, interdits cache HF / téléchargement ; résolution SIMULÉE par le vivier ; smoke CPU PAR CONTRAT, `SMOKES`) puis, sur « Valider » au model manager, l'ÉCRIT dans `wama/common/backends/` — contrôles REFAITS, jamais par-dessus un module, rien de commité. Levée ciblée de la règle « l'agent n'écrit pas dans wama/ » (Fabien, 29/09). Smoke image : deux images DISTINCTES ; smoke parole (2026-10-02) : un extrait réel des corpus d'évaluation, calé sur la référence, texte + segments ordonnés + WER ≤ 75 % (garde-fou contre l'absurde, pas un critère de qualité)

- **Domicile** : `wama/common/services/backend_proposals.py` · **doc** : [wama/model_manager/PROSPECTION_PIPELINE.md](../../wama/model_manager/PROSPECTION_PIPELINE.md)
- **Module** : BACKENDS PROPOSÉS par le rôle `backend` (marche B2) — contrôles, résolution simulée, smoke, puis le geste « Valider » qui ÉCRIT le module dans `wama/common/backends/`.
- **API publique** (15) :
  - `backends_dir() -> Path`
  - `outputs_dir() -> Path`
  - `contract_for_task(task: str) -> tuple` — (module, classe) du contrat qu'un backend écrit pour `task` doit implémenter.
  - `required_methods(contract: tuple) -> set` — Méthodes abstraites que le contrat laisse à implémenter — lues par AST, jamais importées
  - `model_id_of(model_key: str) -> str` — Identifiant que `SUPPORTED_MODELS` doit déclarer — la règle de `backend_for_model`,
  - `supported_entry_errors(model_id: str, entry, code: str=None) -> list` — Erreurs de l'entrée `SUPPORTED_MODELS[model_id]` d'un modèle installé : `model_key` (s'il
  - `check_source(code: str, *, engine: str, model_id: str, contract: tuple) -> dict` — Contrôles de FORME d'un module de backend proposé. `ok` = aucune erreur.
  - `simulate_resolution(code: str, *, module: str, engine: str, model_id: str, task: str='') -> dict` — La résolution que l'inventaire fera APRÈS écriture : le vivier réel + cette entrée.
  - `smoke(code: str, *, module: str, model_key: str, contract: tuple, out_dir: Path) -> dict` — Exécute le backend proposé SUR CPU, sans l'écrire dans le paquet — un essai par CONTRAT
  - `smoke_speech_clip()` — `(SystemAsset de parole, chemin de sa référence | None)` de l'extrait du smoke, ou
  - `smoke_score_clip(path, rate: int=22050) -> str` — Écrit la mélodie du smoke dans `path` (WAV) et rend ses NOMS de notes attendus (`CDEF…`).
  - `abc_note_names(abc: str) -> str` — Noms des notes d'un texte ABC, dans l'ordre et sans octave (`C4D4|c2` → `CDC`) — en-têtes,
  - `pending() -> list` — Propositions de backend en attente : `outputs/backend_*.json` au statut PENDING.
  - `apply(name: str, user=None) -> dict` — ÉCRIT le backend validé dans `wama/common/backends/<module>.py` — contrôles REFAITS,
  - `reject(name: str, user=None) -> bool`

### Document de détections (type `detections` sur disque)

Les objets détectés d'un média, frame par frame (boîte, contour en polygones, piste) — le type de donnée commun `detections` écrit sur disque (2026-10-04, décision de Fabien : détection et floutage séparés dans l'anonymizer). Écrit par un process « Détection », relu par le floutage (`blur_utils.blur_detections` ; les formes segmentées toutes ensemble, `blur_shapes`, mêmes finitions qu'un rectangle ; réécriture image par image `rewrite_media`) et par l'aperçu (`draw`) ; interpolation des trous d'un objet à la lecture (`by_frame`, la forme suit la boîte déduite) — même objet par la piste OU par une position plausible, le réglage seul pour limite, le centre comblé en COURBE (2026-10-05, card #1026) ; et PROLONGÉ de quelques images avant sa première détection et après sa dernière (`max_extrapolation`, réglage séparé). Recouvrement, courbe et extrapolation sont les primitives communes de `wama_data/functions` (`box_iou`, `hermite_gap`, `extrapolate_speed_accel`), celles du cam_analyzer. Sans Django ni app : la Data et le Lab peuvent le lire

- **Domicile** : `wama/common/utils/detections.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Les DÉTECTIONS d'un média, sur disque — le type de donnée commun `detections` (`common/catalog/data_types.DataType.DETECTIONS` : objets détectés par frame — frame, bbox, classe, piste).
- **API publique** (20) :
  - `new_document(*, media: str, width: int, height: int, fps: float=0.0, frame_count: int=1, engine: str='', models=(), classes=(), prompt: str='') -> dict` — Un document vide, prêt à recevoir ses frames (`add`).
  - `detection(*, box, label: str='', conf: float=1.0, track=None, polygons=None) -> dict` — Une détection au format du document : entiers pour les pixels, confiance arrondie.
  - `add(doc: dict, frame_index: int, detections) -> None` — Range les détections d'UNE frame (rien n'est écrit pour une frame vide). Deux appels
  - `merge(docs) -> dict` — L'UNION de documents du même média (2026-10-10) — un par détecteur d'un ensemble : leurs
  - `apply_corrections(doc: dict, corrections) -> dict` — Le document CORRIGÉ par l'humain (2026-10-10, chantier SURFACES) — une copie, l'original
  - `boxes_at(doc: dict, *, width: float=0, frame: int=0) -> list` — Les `(box, conf)` d'UNE frame, ramenées à la largeur `width` (0 = telles quelles) — pour
  - `support(items, *, iou: float=AGREEMENT_IOU) -> list` — L'ACCORD géométrique entre sorties (`WAMA_QUALITE` M2/M6, 2026-10-16) — les objets que
  - `write(path: str, doc: dict) -> str` — Écrit le document (frames ordonnées) ; rend le chemin.
  - `read(path: str) -> dict` — Lit un document ; lève `ValueError` si ce n'en est pas un.
  - `count(doc: dict) -> int` — Le nombre de détections du document (toutes frames).
  - `mask_to_polygons(mask, epsilon: float=1.0, min_area: float=4.0) -> list` — Contours d'un masque (H×W, 0-1 ou 0-255) en polygones entiers, simplifiés à `epsilon`
  - `points_to_polygons(points, epsilon: float=1.0) -> list` — Un contour donné en points (ultralytics `masks.xy`) → polygones entiers simplifiés.
  - `polygons_to_mask(polygons, shape) -> 'object'` — Le masque (uint8, 0/255) que dessinent des polygones sur une image de forme `shape`.
  - `box_of_polygons(polygons) -> list` — Le rectangle englobant de polygones (x1, y1, x2, y2).
  - `valid_box(box, shape, min_size: int=5)` — Le rectangle ramené dans l'image ; None s'il est vide ou plus petit que `min_size`.
  - `fit_polygons(polygons, from_box, to_box) -> list` — Des polygones posés dans `from_box`, portés dans `to_box` (déplacés, mis à l'échelle, en
  - `by_frame(doc: dict, *, interpolate: bool=False, max_gap: int=0, max_extrapolation: int=0, min_iou: float=0.2) -> dict` — {indice de frame: [détections]} — détections RELEVÉES, plus, si `interpolate`, celles que
  - `max_gap_for(fps: float, wanted: int) -> int` — Le trou le plus long que l'on comble : le RÉGLAGE, tel quel.
  - `rewrite_media(source: str, frames: dict, apply, output_path: str, *, on_frame=None, progress=None) -> str` — Réécrit le média `source` en peignant chaque frame avec SES détections :
  - `draw(image, detections, *, boxes: bool=True, labels: bool=True, confidence: bool=True)` — Une COPIE de l'image avec les détections dessinées : contour plein translucide quand la

### Environnement d'exécution d'un backend

`ISOLATION` déclare où tourne un backend (`venv:<chemin>` | `service:<url>`, vide = venv principal). Sans elle le GRISAGE MENT : `missing_packages()` interroge `find_spec` dans CE processus, verdict muet sur un backend qui vit ailleurs. Le défaut est UN venv — l'isolement se DÉCLARE, ne se génère jamais : son coût n'est pas le disque mais la VRAM, chaque processus isolé étant un détenteur que le gouverneur ne voit pas. Zéro isolement aujourd'hui

- **Domicile** : `wama/common/backends/base.py` · **doc** : [docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md](../construction/exploitation/INFRA_WSL_VS_WINDOWS.md)
- **Module** : Contrat de backend de modèle COMMUN à WAMA — extrait de l'app de référence (Transcriber).
- **API publique** (5) :
  - `unload_live_backends(model_key: Optional[str]=None, exclude_sources=None) -> int` — Décharge les backends résidents de CE process ; rend le nombre d'instances déchargées.
  - `refresh_live_reservations() -> int` — Rafraîchit le TTL de la ligne de registre de chaque backend résident de CE process.
  - `start_reservation_heartbeat() -> bool` — Lance, UNE fois par process, le battement qui garde vivantes les lignes des résidents.
  - `class BaseModelBackend(ABC)` — Backend de modèle local (chargement/déchargement + traitement).
  - `seed_generators(seed: int) -> None` — Pose `seed` sur les générateurs que les moteurs tirent (2026-10-22) : `random`, numpy, torch

### Fichiers des composants DÉCLARÉS

Une CLÉ de catalogue → `{rôle: Path}` des composants de `composition.components`, dans la révision que désigne `refs/main` ; un manque LÈVE avec son rôle. La moitié « exécution » de l'anatomie déclarée (l'installation en est l'autre) : un backend généré l'appelle au lieu de réécrire la recherche de snapshot (`kokoro_onnx_backend` la codait à la main)

- **Domicile** : `wama/common/utils/model_components.py` · **doc** : [wama/model_manager/PROSPECTION_PIPELINE.md](../../wama/model_manager/PROSPECTION_PIPELINE.md)
- **Module** : Fichiers des COMPOSANTS DÉCLARÉS d'un modèle installé — la moitié « exécution » de l'anatomie.
- **API publique** (5) :
  - `class ComponentsUnavailable(RuntimeError)` — Le modèle n'est pas installé, ou un composant déclaré est absent du disque — DIT.
  - `snapshot_dir(model) -> Path | None` — Dossier du snapshot d'une ligne de catalogue installée (révision de `refs/main`, sinon la
  - `installed_snapshot(model_key: str) -> Path` — Snapshot sur disque d'un modèle du CATALOGUE, désigné par sa clé — pour un backend qui
  - `component_repos(model_key: str) -> dict` — `{rôle: (dépôt HF, cache_dir)}` des composants DÉPÔTS FRÈRES du modèle (`repo` déclaré).
  - `component_paths(model_key: str) -> dict` — `{rôle: Path}` pour chaque composant DÉCLARÉ du modèle `model_key`.

### Fournisseurs d'exécution ONNX

`onnx_providers()` : CUDA, DirectML, CoreML puis CPU en repli ; `cpu_only` pour un smoke qui ne dispute pas la carte. Extrait d'`AIUpscaler` le 29/09 au moment où un second backend onnxruntime arrivait (texte→image) — le module porte aussi la conversion/inspection de poids ONNX, plomberie de la chaîne modèles

- **Domicile** : `wama/common/utils/onnx_utils.py` · **doc** : [wama/model_manager/PROSPECTION_PIPELINE.md](../../wama/model_manager/PROSPECTION_PIPELINE.md)
- **Module** : ONNX Conversion Utilities
- **API publique** (7) :
  - `onnx_providers(device_id: int=0, cpu_only: bool=False) -> list` — Fournisseurs d'exécution onnxruntime, par ordre de préférence — CPU toujours en repli.
  - `convert_yolo_to_onnx(model_path: str, output_path: Optional[str]=None, imgsz: int=640, half: bool=False, dynamic: bool=True, simplify: bool=True, opset: int=12…` — Convert a YOLO model (.pt) to ONNX format using ultralytics export.
  - `convert_pytorch_to_onnx(model: Any, output_path: str, input_shape: Tuple[int, ...], input_names: List[str]=None, output_names: List[str]=None, dynamic_axes: Di…` — Convert a generic PyTorch model to ONNX format.
  - `batch_convert_yolo_to_onnx(models_dir: str, output_dir: Optional[str]=None, recursive: bool=True, **kwargs) -> Dict[str, Tuple[bool, str]]` — Convert multiple YOLO models in a directory to ONNX format.
  - `verify_onnx_model(onnx_path: str) -> Tuple[bool, str, Optional[Dict]]` — Verify an ONNX model is valid and get its metadata.
  - `get_onnx_runtime_info() -> Dict[str, Any]` — Get information about available ONNX runtime and providers.
  - `convert_anonymizer_models_to_onnx(output_subdir: str='onnx', **kwargs) -> Dict[str, Tuple[bool, str]]` — Convert all Anonymizer YOLO models to ONNX format.

### Gabarits de génération d'app (marches S2 + B1)

Rend le code CONVENTIONNEL d'une app depuis son manifeste — une cible par fichier (apps/urls/models/params/tasks/views/templates), consommées par `app_sandbox substitute` et le write-back ; le hors-convention reste un TROU NOMMÉ (stubs 501, commentaires [manifest-gen]), jamais un manque silencieux. Depuis le 02/09 (marche B1 CLOSE), le corps des TÂCHES se COMPOSE aussi : `backends/__init__.ROUTES` de l'app (nature → callable au contrat commun) monte au manifeste (processing.backend_routes) et tasks_gen émet l'appel — import relatif au paquet, la jumelle a CONVERTI (SUCCESS mesuré). DEUX SAVEURS depuis le 03/09 (2ᵉ app routée, describer) : `RESULT` déclare ce que les backends produisent — 'file' (le backend écrit output_path) ou 'text' (il REND le texte, la tâche le persiste dans la colonne déclarée et publie l'aperçu partiel) ; `NATURE_FIELD` nomme la colonne de nature. ⚠ Un fichier substitué doit exposer TOUT ce que les fichiers COPIÉS lui importent : params_gen émet l'alias `<X> = <X>_JSON` (le models copié importe la graphie courte — ImportError au rendu de CHAQUE card sinon). PLUSIEURS PROCESS depuis le 05/10 (le Writer, patron composer, décision n°11) : le pipeline se lit par la CLÉ (`pipeline_decl` : corpus, sinon brouillons), `function_specs_gen` écrit FunctionSpec + register_app_pipeline (le process « Sortie » commun = output_spec), tasks_gen une glu par process (`process=`), models_gen une colonne par sortie et par port, views_gen `start_process`

- **Domicile** : `wama/common/manifests/codegen/templates_gen.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Gabarit `templates/<app>/index.html` (marche A — v1, marche S2).
- **API publique** (2) :
  - `render_index(manifest: dict) -> tuple` — (source, raison) — templates/<app>/index.html conventionnel, jamais partiel.
  - `render_base(manifest: dict) -> tuple` — (fichiers, raison) — `templates/<app>/base.html`, la FINE couche d'app sur l'ossature

### Grille de conformité

Mesure les 8 facettes F1–F8 des apps par analyse du code réel

- **Domicile** : `wama/common/services/conformity_checker.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : Vérification AUTOMATISÉE de conformité des apps — confrontation au RÉEL.
- **API publique** (2) :
  - `class Criterion`
  - `run_checks(app_ids: list[str]) -> dict` — Exécute tous les critères sur chaque app. Retourne le rapport sérialisable.

### Manifestes

Extraction/validation/projection des 7 kinds vers les registres. Le corpus versionné suit le registre À CHAUD par UNE porte (`corpus.follow` : installation, validation d'une proposition, désinstallation — 2026-10-12), que le runner de tests coupe

- **Domicile** : `wama/common/manifests/ingest.py` · **doc** : [docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md](../construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md)
- **Module** : Moteur d'INGEST — validate → (sandbox) store → verify → promote → un-ingest.
- **API publique** (9) :
  - `validate(manifest: dict) -> list[str]` — Erreurs d'enveloppe + erreurs de body (déléguées au kind) + références pendantes.
  - `resolve_requires(manifest: dict) -> tuple[list[dict], list[str]]` — Résout les références `requires` de l'ENVELOPPE (SPEC §7.3) — kind-agnostique.
  - `ingest(manifest: dict, *, user=None, promote_to: Optional[str]=None, strict: bool=True)` — Crée ou met à jour la ligne `Manifest` (idempotent sur kind+key).
  - `promote(obj, *, by=None)` — Passe un manifeste AU SYSTÈME : plus de propriétaire, portée publique, demande close.
  - `extract(kind: str, key: str) -> Optional[dict]` — Produit le manifeste d'un objet EXISTANT en lisant les registres courants (round-trip).
  - `write_back(manifest: dict, *, apply: bool=False)` — Projette (write-back) le manifeste vers l'état committé — geste EXPLICITE, jamais automatique
  - `verify(manifest: dict) -> list[dict]` — Retourne la liste des écarts entre le manifeste fourni et l'état courant des registres.
  - `un_ingest(kind: str, key: str) -> bool`
  - `diff_dicts(a: Any, b: Any, path: str='') -> list[dict]` — Écarts a(=manifeste) vs b(=courant). Ordre des listes ignoré pour les listes de scalaires.

### Passe-plat des déclarations de modèle

Lire la déclaration d'un modèle SANS importer l'app qui la porte : applique la convention `wama/<app>/utils/model_config.py::<APP>_MODELS`, ne connaît aucune app, et surtout ne touche AUCUNE BASE. ⚠ Le catalogue `AIModel` porte la même information, mais le lire ajouterait une dépendance ORM à chaque backend — or c'est justement l'absence de Django qui les rend déplaçables. On lirait la bonne donnée en détruisant la propriété cherchée

- **Domicile** : `wama/common/utils/model_declarations.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Lire la DÉCLARATION d'un modèle sans importer l'app qui la porte.
- **API publique** (3) :
  - `declarations(source: str) -> dict` — TOUTES les déclarations de modèle de l'app `source` (`{model_id: dict}`), `{}` si l'app
  - `declaration(source: str, model_id: str) -> Optional[dict]` — Déclaration de `model_id` telle que l'app `source` la porte, ou None.
  - `declaration_for(value: str, default_source: str='') -> Optional[dict]` — Déclaration du modèle désigné par une CLÉ de catalogue — ou par un identifiant nu, lu dans

### Process « Sortie » d'une card

Le second temps de toute app qui rend un fichier, en process À PART : `output_spec` (le `ProcessSpec`, qui surveille format / qualité / agrandissement) et `output_step` (la glu, au contrat du squelette). La glu du MOTEUR n'a que trois gestes : `drop_previous_outputs`, `generated(...)`, et l'enveloppe de tâche appelle `forget_lost_generation`. Changer de format ne rejoue plus le moteur (2026-10-03) — imager, composer, synthesizer, anonymizer, enhancer ×2. Un ancien rendu n'est retiré que sous les deux règles de `safe_delete_file` : il vit chez l'app de la card (`owns_file`) et aucune autre card ne le désigne. `output_step(transform=, apply=)` : le même process pour une transformation PROPRE à l'app — l'amélioration faciale de l'avatarizer (process « Visage », 2026-10-04)

- **Domicile** : `wama/common/services/output_process.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Le process « SORTIE » d'une card — commun à toutes les apps qui rendent un fichier.
- **API publique** (8) :
  - `output_spec(depends_on, *, key: str=OUTPUT_KEY, label: str=OUTPUT_LABEL, share: int=1, **spec)` — Le `ProcessSpec` du process de sortie : il surveille les réglages de sortie communs
  - `rendered_files(item, field) -> list` — Les rendus que la card porte aujourd'hui dans `field`, en chemins absolus — un champ
  - `output_sources(item, field) -> list` — Ce dont le process de sortie REPART : les originaux gardés quand il y en a (le rendu a
  - `files_fingerprint(paths) -> str` — Empreinte de ce que le moteur a écrit — DÉCLARÉE à la ligne d'exécution (`output_fingerprint`
  - `drop_previous_outputs(item, field, keep=(), natives: bool=True) -> None` — Le moteur REJOUE : les originaux gardés et les rendus de la fois d'avant qu'il n'a pas
  - `generated(paths, **result) -> dict` — Le retour d'une glu de MOTEUR, complété de ce que la brique attend d'elle : plus aucun
  - `forget_lost_generation(item, field, node: str) -> bool` — La sortie repart des fichiers que le moteur a laissés. S'ils ne sont plus là (retirés,
  - `output_step(field, *, domain, app_id: str, console=None, extra_fields=None, format_of=None, transform=None, apply=None, what: str='Réglages de sortie', input_s…` — La GLU du process de sortie, au contrat du squelette (`glu(item, ctx) -> dict`).

### Propositions de manifestes (geste « Valider »)

Le cycle sandbox → vérifié → promu (WAMA_MANIFEST_ARCHITECTURE §4) reçoit son premier appelant (29/09) : un rôle LLM DÉPOSE son manifeste au magasin (bac à sable), le model manager en montre le PLAN (champs comblés, divergences NON appliquées, erreurs), « Valider » SUPERPOSE à l'extraction en ne comblant que des vides (un manifeste brut effaçait la licence), projette, promeut, exporte au corpus ; « Rejeter » ne passe pas par un_ingest, qui déferait une projection jamais faite. Depuis le 18/10 (ROADMAP §29) la file lit la DEMANDE de promotion, plus le privé, et valider rend l'élément au SYSTÈME, plus à l'admin qui valide

- **Domicile** : `wama/common/manifests/proposals.py` · **doc** : [docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md](../construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md)
- **Module** : PROPOSITIONS de manifestes — le geste de validation qui manquait entre un rôle LLM et l'ingest.
- **API publique** (6) :
  - `fill_empty(current, proposed, path='')` — Superpose `proposed` sur `current` en ne comblant que les VIDES — récursif sur les dicts.
  - `propose(manifest: dict, *, origin: str='', user=None)` — Dépose un manifeste PROPOSÉ au magasin, en bac à sable. Rien n'est projeté.
  - `pending(kind: str=None)` — Promotions DEMANDÉES et non tranchées, plus récentes d'abord — pas tout ce qui est privé.
  - `plan(obj) -> dict` — Ce que `apply()` FERAIT — sans rien écrire. `write_back` est le dry-run du kind.
  - `apply(obj, user=None) -> dict` — Applique une proposition : superposition, write-back RÉEL, promotion, export au corpus.
  - `reject(obj) -> bool` — Close une demande de promotion. N'appelle PAS `un_ingest` (cf. docstring du module).

### Rendu vidéo image par image, à horodatages d'origine

Réécrit une vidéo en passant chaque image par une transformation de l'app, en UN encodage dans le conteneur demandé (celui de l'entrée : le moins de conversions possible), les codecs étant ceux d'une conversion vers ce format (`converter.video_backend.rendering_encoding`) : chaque image à SON horodatage d'origine (PyAV — une cadence variable garde ses temps), l'audio de la source RECOPIÉ à ses propres temps, jamais étiré (décisions de Fabien, 2026-10-28). La taille de sortie est celle de l'image transformée. Né pour le floutage (`detections.rewrite_media` : anonymizer, cam_analyzer), sorti en brique le 2026-10-29 pour l'agrandissement vidéo de l'enhancer, qui sortait MUET

- **Domicile** : `wama/common/utils/video_render.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : Rendu d'une vidéo image par image — chaque image à SON horodatage d'origine, le son recopié.
- **API publique** (1) :
  - `render_video(source: str, paint, output_path: str, *, on_frame=None, progress=None) -> str` — Réécrit la vidéo `source` en passant chaque image par `paint(indice, image) -> image`, et

### Routage des poids hors HuggingFace

QUATRE leviers pour tenir la règle « modèle principal catégorisé, sous-dépendances au cache partagé » (ROADMAP §5b), et le choix est imposé par la LIB, pas par le goût : A `cache_dir=` — B un CHEMIN local (`poids_locaux`) — C la variable propre à la lib, posée dans settings (`DEEPFACE_HOME`, `AUDIOCRAFT_CACHE_DIR`) — D `hf_cache_scope`, DERNIER RECOURS déclaré. ⚠ D restaure l'environnement mais JAMAIS LES FICHIERS : ce que la lib télécharge pendant la fenêtre reste dans le dossier du modèle — c'est ainsi que `timm/resnet18` a atterri chez table-transformer. Zéro mutation d'environnement dans le code aujourd'hui

- **Domicile** : `wama/common/utils/hf_weights.py` · **doc** : [docs/construction/suivi/ROADMAP.md](../construction/suivi/ROADMAP.md)
- **Module** : Poids d'un modèle rangés dans SON dossier — pour les libs qui n'acceptent pas `cache_dir=`.
- **API publique** (1) :
  - `poids_locaux(repo_id: str, dossier: str | Path, *, patterns: Optional[Sequence[str]]=None, token: Optional[str]=None, revision: Optional[str]=None) -> str` — Chemin LOCAL des poids de `repo_id`, garantis présents sous `dossier`.

### Réglages de sortie (formats, agrandissement)

Source commune des formats+qualités de fichier par domaine (réutilise le vocabulaire converter) ET leur APPLICATION : `apply_output_settings` enchaîne agrandissement (image) puis conversion après n'importe quel backend (2026-09-30). L'agrandissement (`output_upscale`, opt-in `include_upscale`) tire l'upscaler du catalogue — tâche `upscale`, capacité `scale` = facteur, curseur qualité de l'item — sans nommer ni modèle ni app ; il vivait dans UN backend (diffusers, LANCZOS ×2), ignoré des autres. `render_outputs` (2026-10-03) GARDE le fichier d'origine (`<nom>.native<ext>`, champ `native_outputs` du mixin `NativeOutputsMixin`, déclaré à la rétention) tant que ces réglages le transforment : le process « sortie » d'une app se rejoue SEUL, sans regénérer

- **Domicile** : `wama/common/utils/output_formats.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md §6.4](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : Source COMMUNE des formats + qualités de FICHIER de sortie — pendant de voice_options pour la sortie.
- **API publique** (17) :
  - `get_output_formats(domain: str) -> List[Tuple[str, str]]` — [(valeur, libellé)] des formats de fichier de sortie pour un domaine. 'original' = inchangé.
  - `format_option_groups(natures, extra=()) -> list` — Les options de format d'une app qui rend PLUSIEURS natures selon l'élément (l'enhancer et
  - `quality_applies(item, output_format: str | None=None) -> bool` — La qualité a-t-elle un effet sur la sortie de cet élément ? Oui quand le fichier est
  - `get_output_qualities(domain: str | None=None) -> List[Tuple[str, str]]` — Presets de qualité (web/équilibré/max). `domain` réservé pour d'éventuelles variantes futures.
  - `keep_size_param(contexts=None, dom_id=None, group: str | None=None, **extra)` — Le réglage « Garder la résolution d'origine » (2026-10-16, demande de Fabien) : la sortie
  - `output_format_params(domain, contexts=None, dom_id_format=None, dom_id_quality=None, include_quality: bool=True, group: str | None=None, include_upscale: bool=…` — Fabrique les Param COMMUNS output_format (+ output_quality) pour un domaine, prêts à concaténer au
  - `output_format_params_for_app(app_name: str, contexts=None, dom_id_format=None, dom_id_quality=None, include_quality: bool=True, group: str | None=None, domain:…` — AUTO depuis APP_CATALOG : lit `multi_format_download` (early/late) + déduit le domaine des
  - `upscale_factor(value) -> int` — `'x4'` → 4, `'x2'` → 2 ; 0 pour « aucun » ou une valeur illisible.
  - `upscale_output_image(path: str, factor, *, item=None, app_id=None, denoise: bool=False, progress_callback=None) -> tuple` — Agrandit l'image `path` EN PLACE par un upscaler TIRÉ du catalogue ; rend `(largeur,
  - `wanted_format(item, output_format: str | None=None) -> str` — Le format de sortie DEMANDÉ, en minuscules ('original' = inchangé). `output_format` : la
  - `keep_size_target(item, domain: str, input_size=None)` — Les dimensions `(largeur, hauteur)` auxquelles ramener la sortie, ou None : le réglage
  - `apply_output_settings(paths, item, *, domain: str, app_id: str | None=None, console=None, output_format: str | None=None, input_size=None) -> list` — Les réglages de SORTIE de l'item appliqués aux fichiers produits, dans l'ordre du
  - `is_native(path) -> bool` — Ce chemin porte-t-il la marque d'un fichier d'origine gardé ?
  - `native_name(path) -> str` — Le nom sous lequel le fichier d'origine de `path` est gardé (idempotent).
  - `final_name(path) -> str` — Le nom du rendu d'un fichier d'origine gardé, avant conversion (idempotent).
  - `transforms_output(item, domain: str, output_format: str | None=None, input_size=None) -> bool` — Les réglages de sortie de l'item changent-ils le fichier que le moteur a écrit ?
  - `render_outputs(sources, item, *, domain: str, app_id: str | None=None, console=None, previous=(), output_format: str | None=None, transform=None, apply=None, i…` — Les réglages de sortie appliqués en GARDANT le fichier d'origine ; rend

### Résolution de backend par DÉCLARATION

Une app ne demande plus un MODULE, elle demande « le backend qui sait exécuter ce modèle » : `backend_for_model()` va de `composition.runtime.engine` (moitié modèle) à `BaseModelBackend.ENGINE` (moitié backend), départagé par `SUPPORTED_MODELS` quand le moteur est PARTAGÉ — `diffusers` est piloté par 8 backends, `transformers` par 4. L'import de la classe est CIBLÉ et TARDIF : le registre reste statique. C'est ce qui rend l'EMPLACEMENT PHYSIQUE des backends indifférent, préalable à leur passage au substrat transversal. ⚠ Rend None plutôt qu'un tirage quand rien ne tranche — une erreur silencieuse coûte plus cher qu'un refus ; et ne rend QUE des sous-classes du contrat (le porteur du démon Ollama n'en est pas un). Depuis le 29/09 la TÂCHE voyage : un contrat LIANT (`backend_inventory.TASK_CONTRACTS`) écarte un backend qui n'en dérive pas — un upscaler n'exécute pas un modèle texte→image, même seul sur `onnxruntime`. L'AUTRE moitié du routage depuis le 05/10 : `route_for_nature` suit la décision d'APP (`backends/__init__.ROUTES`, nature d'entrée → fonction au contrat commun), import relatif au paquet appelant — recopiée quatre fois avant (enhancer, describer, corps émis par tasks_gen, conversion inline) et contournée par la tâche du converter (`if/elif` à la main). LA PORTE DE LANCEMENT depuis le 07/10 : `backend_instance_for_key` (instance par clé, clé posée, clé d'accès d'un modèle DISTANT par `authorize()`) + `run_contract` (méthode de travail du contrat de tâche, réglages par leur nom de schéma, fichiers par le nom de leur PORT — la règle de `generic_runner.port_arguments` un cran plus bas) — une app ne connaît plus ses moteurs, et `tasks_gen` compose sur elle le corps d'une app qui choisit son modèle par tâche (08/10)

- **Domicile** : `wama/common/backends/manager.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Manager de backends COMMUN — extrait du pattern Transcriber/Imager.
- **API publique** (21) :
  - `register_engine_inventory(fn) -> None` — Enregistre un inventaire de moteurs. Le callable rend soit un MAPPING
  - `engine_backends() -> dict` — {moteur: classe de backend} pour tous les inventaires qui exposent leurs classes.
  - `invalidate_engine_cache() -> None` — À appeler après une installation de librairie : le prochain `known_engines()`
  - `known_engines() -> set` — Moteurs réellement EXÉCUTABLES — inventaires relus à CHAQUE appel (ré-autorisation
  - `backend_for_engine(engine: str, model_id: str='', entries=None, task: str='')` — Classe de backend qui pilote `engine` (et sert `model_id` si le moteur est partagé).
  - `engine_classes(task: str) -> dict` — Moteur → CLASSE de backend, pour les backends du contrat de `task` — DÉRIVÉ de la
  - `backend_for_model(model, entries=None)` — Classe de backend qui sait exécuter `model`, ou None.
  - `backend_for_key(model_key: str, entries=None)` — La MÊME porte que `backend_for_model`, adressée par la CLÉ de catalogue (`<source>:<id>`).
  - `class ModelNotServed(RuntimeError)` — Aucun backend ne sert la clé de catalogue demandée — le lancement s'arrête en le disant,
  - `backend_instance(cls, model_key: str='', user=None)` — L'instance gardée chargée de la CLASSE `cls`, préparée pour `model_key` : la clé posée
  - `backend_instance_for_key(model_key: str, user=None)` — L'INSTANCE prête du backend qui sert `model_key` — LA porte de lancement d'un modèle
  - `run_contract(instance, **values)` — Appelle la méthode de TRAVAIL du contrat de `instance` avec les valeurs qu'elle ACCEPTE,
  - `work_method_accepts(cls, name: str) -> bool` — La méthode de travail du contrat de `cls` reçoit-elle une valeur nommée `name` ? — lu sur
  - `route_for_nature(package: str, nature: str, routes: dict=None)` — La porte par NATURE d'entrée : le callable que les `ROUTES` d'une app déclarent pour
  - `invalidate_catalog_index() -> None` — Le prochain `catalog_keys_for_owner` relit le catalogue (après une synchro, un test).
  - `prime_catalog_index() -> int` — Remplit l'index du catalogue (et, par lui, importe les modules de backends) — rend le
  - `match_local_name(rows, name: str) -> list` — Clés, parmi les lignes `(clé, dépôt)` d'une classe, que désigne le nom local `name`.
  - `catalog_keys_for_owner(owner: str) -> list` — Clés catalogue désignées par une clé d'owner du registre VRAM — [] si rien ne se résout.
  - `backend_missing(model) -> Optional[str]` — Raison si `model` est POSITIVEMENT sans backend, sinon None.
  - `generic_scan_sources() -> frozenset` — Les sources des lignes « catalogué ≠ utilisable » : les familles « catalogue » et « poids » du
  - `class BackendManager` — Registre + cycle de vie de backends `BaseModelBackend` (singletons keep_loaded).

### Vivier des backends (registre DÉRIVÉ)

Inventaire des moteurs de WAMA, dérivé À CHAQUE AFFICHAGE des déclarations `wama/<app>/backends/` (ROUTES/RESULT/NATURE_FIELD + classes BaseModelBackend trouvées jusque dans les SOUS-MODULES) recoupées au catalogue AIModel. Deux usages : la vision d'ensemble (12ᵉ registre, page /common/backends/) et le VOISINAGE que le LLM de la marche B trie pour s'inspirer du backend le plus approchant (signature « natures → saveur », paquets, VRAM, modèles servis). Ne stocke RIEN et n'a pas de rafraîchisseur — une page qui DÉRIVE ne peut pas diverger de ses sources. Ne cite aucune app : il parcourt les apps installées (le registre ne connaît jamais ses producteurs). ⚠ MISE À JOUR 2026-09-06/07 — le lien FIN EXISTE désormais et `backend_ref` n'absout plus : le modèle déclare son moteur (`composition.runtime.engine`), le backend déclare celui qu'il pilote (`ENGINE`) et ce qu'il sert (`SUPPORTED_MODELS`), et l'inventaire porte les COORDONNÉES D'IMPORT pour résoudre PARESSEUSEMENT. Mesuré : 108/116 modèles déclarent leur moteur (14 la veille), 97 résolvent leur backend réel. `backend_ref` ne sert plus qu'à la PROVENANCE du lien

- **Domicile** : `wama/common/services/backend_inventory.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Registre des BACKENDS — vue DÉRIVÉE du vivier de moteurs de WAMA (demande Fabien 2026-09-03).
- **API publique** (13) :
  - `class BackendEntry` — UN backend exécutable — la maille que le LLM compare pour trouver « le plus approchant ».
  - `class AppBackends`
  - `inventory() -> List[AppBackends]` — Le vivier, DÉRIVÉ à l'appel. Une app = une entrée ; jamais de nom d'app en dur ici.
  - `summary() -> dict` — Chiffres de tête de page + le vivier. Aucun compteur recopié ailleurs (un chiffre vit
  - `declared_engines() -> dict` — {moteur: classe de backend} DÉRIVÉ des déclarations `ENGINE` des backends.
  - `count() -> int` — Total de backends du vivier (apps réelles) — pour le registre des registres.
  - `orphelins(entrees, servis) -> tuple` — (muets, expliqués) — backends qu'AUCUN modèle ne désigne, séparés par la RAISON.
  - `resolvable_entries() -> List[BackendEntry]` — Le vivier que la résolution consulte — jumelles de bac à sable exclues. Un appelant qui
  - `contract_engines(task: str) -> dict` — Moteur → `(module, classe)` des backends CONCRETS du contrat de `task`, lus par AST dans
  - `resolve_entry(engine: str, model_id: str='', entries=None, task: str='') -> Optional[BackendEntry]` — ENTRÉE du vivier qui sait exécuter `model_id` avec `engine` — ou None. STATIQUE :
  - `resolve_backend(engine: str, model_id: str='', entries=None, task: str='')` — Classe de backend qui sait exécuter `model_id` avec `engine` — ou None.
  - `app_backend_entries(app: str) -> List[BackendEntry]` — Backends que `app` RÉSOUT réellement, par le lien du catalogue — STATIQUE, dédoublonnés
  - `app_backend_paths(app: str) -> List[Path]` — Fichiers source des backends résolus par `app` (cf. `app_backend_entries`), n'existant

### ▶ d'un process (fabrique commune)

La vue `start/<pk>/<process>/` d'une app à pipeline — `make_process_start_view` (2026-10-04) : process connu, ayant lieu pour cette card (`AppPipeline.applicable`), anti-course (`begin_processing`), tâche lancée bornée à ce process. Écrite à la main dans six apps avec trois formes de refus ; mêmes crochets que `make_batch_views` (`task_for`, `reset_on_start`). Le pipeline se lit de l'app de l'élément (`pipeline_of`), il n'est pas un argument. Le geste est `start_one_process` : la vue et l'outil `start_<app>(…, process=…)` de l'assistant l'appellent tous deux (2026-10-14)

- **Domicile** : `wama/common/utils/process_views.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.6](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — La vue « ▶ d'UN process » d'une card : fabrique commune (`make_process_start_view`).
- **API publique** (3) :
  - `process_reset_for(work_model)` — La remise à zéro par process que l'app de `work_model` déclare à sa fabrique, ou None.
  - `start_one_process(work_model, pk, process, *, user, task_for, reset_on_start=None, reset_for_process=None)` — Le ▶ d'UNE étape d'un élément : `(élément, tâche, None)`, ou `(None, None, (statut HTTP,
  - `make_process_start_view(*, work_model, task_for, get_user=request_user, reset_on_start=None, reset_for_process=None)` — La vue `start_process(request, pk, process)` d'une app à pipeline.

### ▶ d'une card, ▶ et 🗑 de la file (fabrique commune)

Les vues `start`, `start_all` et `clear_all` d'une app — `make_item_views` (2026-10-29, ROUTE §11 #39) : anti-course (`begin_processing`), remise à zéro de l'app sous le verrou, cache de progression purgé, tâche envoyée ; « tout lancer » selon la sélection DÉCLARÉE (`pending` / `pending_exclude`, noms de `TRIAD_SPECS`) et, s'il en porte, les réglages postés vérifiés sur toute la file avant le premier lancement ; « tout effacer » sans les éléments en vol, par le geste de retrait de `batch_delete` (`discard_element`). Le menu ▾ de la barre de file offre les PÉRIMÈTRES (`START_SCOPES` / `CLEAR_SCOPES`, `?scope=`), grisés quand ils sont vides d'après les compteurs de la file. Trente copies dans dix apps. La fabrique INSCRIT sa déclaration par modèle (`declaration_for`) : l'outil `start_<app>` de l'assistant la lit — un geste, deux portes, comme `start_one_process`

- **Domicile** : `wama/common/utils/item_views.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — Les vues d'ÉLÉMENT et de FILE : ▶ d'une card, ▶ de la file, 🗑 de la file (`make_item_views`, `WAMA_APP_GENERATION_ROUTE.md §11 #39`).
- **API publique** (7) :
  - `queue_scopes(action: str) -> list` — Les entrées du menu ▾ d'une action de file (`start` | `clear`) : `{key, label, counter}` —
  - `class ItemStart` — Ce qu'une app déclare de son ▶ — lu par les vues ET par l'outil de l'assistant.
  - `declaration_for(work_model)` — La déclaration du ▶ de `work_model`, ou None. Inscrite au chargement des vues de son app :
  - `start_one_item(declaration, pk, *, user, reset=None)` — Le ▶ d'UN élément : `(élément, tâche, None)`, ou `(None, None, (statut HTTP, message))`.
  - `start_queue(declaration, user, *, settings=None, apply_settings=None, on_queue_settings=None, scope: str='')` — « Tout lancer » : chaque élément que la déclaration retient, par le geste du ▶.
  - `discard_element(item, *, progress_key='', on_delete=None)` — Retirer UN élément de la file : révoquer sa tâche en file, ce que l'app sait de lui
  - `make_item_views(*, work_model, app_id: str, task=None, task_for=None, get_user=request_user, reset_on_start=None, startable=None, unstartable_message: str='',…` — Les vues `start(request, pk)`, `start_all(request)` et `clear_all(request)` d'une app.

## File d'attente & lots

### Dossier de travail jetable

Les fichiers INTERMÉDIAIRES d'un traitement ne vivent pas dans `media/`. Mesuré le 2026-08-25 : `media/avatarizer/` pesait 1,69 Go pour 2101 fichiers dont 99,6 % de PNG — les frames de CodeFormer, écrites dans le dossier de sortie du job et jamais nettoyées ; `job_11` portait 1715,7 Mo pour une vidéo de 0,70 Mo. `media/` ne contient que `<app>/<user>/input|output/` et `users/` (MEDIA_STORAGE_TIERING.md) : un fichier de travail y est sauvegardé par le miroir, compté par le tiering et servi par Apache pour rien. Le `with` rend le nettoyage STRUCTUREL au lieu d'être une convention qu'on oublie. ADOPTÉ par 5 sites (avatarizer/codeformer, describer/views, enhancer/views, reader/glm_ocr, describer/video_describer) ; le dernier site, la boucle vidéo de l'enhancer (ex-`tasks.py:534`), porté le 26/08, n'écrit plus d'intermédiaire depuis le 2026-10-29 (rendu commun `video_render`, qui agrandit et encode au fil de la lecture) ; la glu `enhancer/tasks.py` garde le sien pour ranger la sortie. ⚠⚠ L'audit AUTOMATIQUE des `mkdtemp` a mal classé 2 sites sur 6 — `glm_ocr` déléguait par contrat DOCUMENTÉ, `enhancer/tasks` nettoyait déjà — mais la lecture site par site a trouvé l'inverse, des fuites qu'aucun motif ne voyait : un `rmdir` conditionné à « si le dossier est vide » qui ne se déclenchait donc jamais, un nettoyage placé APRÈS l'appel qui sautait sur exception, et un `except ImportError` qui empêchait un repli d'exister. Un relevé par motif oriente ; il ne conclut pas. Porte aussi `purge_job_dir` : la suppression d'une card doit emporter le dossier du job — 13 dossiers `job_*` orphelins relevés contre 4 rattachés

- **Domicile** : `wama/common/utils/work_dir.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Dossier de TRAVAIL jetable — les fichiers intermédiaires ne vivent pas dans `media/`.
- **API publique** (2) :
  - `work_dir(prefix: str='wama_work')` — Crée un dossier de travail jetable et le supprime À LA SORTIE, même sur exception.
  - `purge_job_dir(base_dir, job_id, *, prefix: str='job_') -> int` — Supprime le dossier de job `<base_dir>/<prefix><job_id>/`. Rend le nombre d'octets libérés.

### Duplication et suppression sûres

duplicate_instance(), release_card_files() (retirer une card libère TOUT ce qu'elle porte et prévient : ses champs fichier et ses listes de chemins déclarées, lus par `file_references.listed_paths` ; release_card_file() = le même geste pour un champ) et safe_delete_file() (relance) — fichiers partagés entre items ; la confirmation commune d'un retrait (`WamaApp.ask`) demande d'avance « supprimer aussi le fichier ? », case décochée (`released_files.freed_by`)

- **Domicile** : `wama/common/utils/queue_duplication.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : WAMA — Common utilities for queue item duplication and safe file deletion.
- **API publique** (9) :
  - `owns_file(instance, file_name: str) -> bool` — Le fichier vit-il dans le DOMICILE de l'app de cette card (`users/<uid>/<app>/…`) ?
  - `safe_delete_file(instance, field_name: str) -> bool` — ⚠ Depuis le 2026-09-30, RÉSERVÉ au REMPLACEMENT d'un fichier par SA card (l'ancien rendu
  - `release_card_file(instance, field_name: str) -> bool` — Une card que l'utilisateur RETIRE (supprimer, tout effacer, lot) LIBÈRE son fichier : il
  - `release_card_files(instance) -> int` — Le retrait à l'échelle de la CARD : elle libère TOUT ce qu'elle porte, lu de ses
  - `is_shared_elsewhere(instance, field_name: str, file_name: str) -> bool` — Une AUTRE ligne désigne-t-elle ce fichier — DANS N'IMPORTE QUEL MODÈLE ?
  - `delete_file_unless_shared(instance, field_name: str) -> bool` — Suppression VOULUE du fichier d'un objet — mais jamais s'il en reste un porteur.
  - `is_received(instance, user) -> bool` — La card appartient-elle à QUELQU'UN D'AUTRE que `user` (une card qu'on lui a partagée) ?
  - `duplicate_instance(instance, reset_fields=None, clear_fields=None, *, for_user=None)` — Create a new DB row that shares the same input file(s) as the original.
  - `copy_subfolder(rel: str, app: str) -> str` — Le sous-dossier d'app où COPIER `rel` chez un autre propriétaire : sa place relative dans le

### Identité d'un lot (titre, ce qui varie, nom donné)

Ce que la card mère, le volet, le menu « Ajouter à un lot », le calendrier, la page des partages et les notifications DISENT d'un lot — tout LU, rien déclaré : l'ENTRÉE de chaque élément (spec de la fiche Infos, son vrai nom par la provenance), l'ORIGINE (fichier de lot, sinon dossier commun des sources), ce qui VARIE (réglages `chip=True`, `card_chips.varying_chips_for_items`), et le NOM donné à la main (`BatchLabel`, adressé comme `BatchSettings`), qui prime. Titre : nom donné, entrée commune, fichier de lot, dossier, sinon plage des entrées. Deux requêtes par page, posées par `batch_common.attach_identities` dans les TROIS constructeurs de file (`build_batches_list`, le converter, l'index généré en FK directe). Geste « Renommer le lot… » du menu de la card mère → `common:api_batch_label` (`editable_or_404`)

- **Domicile** : `wama/common/services/batch_identity.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §3quater](../construction/ui/CARD_DESIGN.md)
- **Module** : IDENTITÉ D'UN LOT — ce que la card mère, le volet, le menu « Ajouter à un lot », le calendrier et la page des partages disent d'un lot (2026-10-19, demande de Fabien : « seul le numéro identifie un batch, pas son contenu »).
- **API publique** (8) :
  - `element_entry(element, origins=None) -> dict` — L'entrée DÉCLARÉE d'un élément : `{'name', 'text', 'nature', 'origin'}` (`''` / None quand
  - `entry_label(entry) -> str` — Ce qu'on DIT d'une entrée : son texte (le prompt, le texte à dire) s'il y en a un — c'est
  - `identify(pairs) -> list` — L'identité de chaque lot de `pairs` — `[(lot, [éléments]), …]`, éléments dans l'ordre des
  - `identity_of(batch) -> dict` — L'identité d'UN lot, ses éléments lus par `batch_elements` (pour qui ne tient que le lot).
  - `display_title(identity) -> str` — Le titre à afficher : le titre de l'identité, sinon le numéro (« Lot #12 »).
  - `label_of(batch) -> str` — Le nom donné à la main à ce lot, ou ''.
  - `rename(batch, label: str) -> str` — Donne (ou efface, `label` vide) le nom d'un lot. Rend le nom retenu ('' = effacé).
  - `forget(batch) -> int` — Le nom part avec le lot (appelé par la suppression du lot, comme `batch_settings.forget`).

### Import par lot

Parsing des fichiers batch (txt/csv/pdf/docx) et cycle de vie du lot. Depuis le 2026-10-20 : `parse_batch_lines` (les lignes normalisées, toutes familles) et `line_to_ports` (une ligne rangée dans les PORTS d'un nœud : colonne au nom d'un port, rôles `-i`/`-p`/`-r` en alias, refus nommé) — lus par le Studio

- **Domicile** : `wama/common/utils/batch_parsers.py` · **doc** : [docs/construction/ui/BATCH_FORMAT.md](../construction/ui/BATCH_FORMAT.md)
- **Module** : WAMA Common — Batch file parsers
- **API publique** (20) :
  - `batch_file_refusal(filename: str, extra=()) -> str` — Le motif de refus d'un fichier de lot, ou '' s'il est d'un format de lot.
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
  - `parse_batch_lines(text: str, plain_as: str='input') -> Tuple[List[Dict], List[str]]` — Les LIGNES d'un fichier de lot, quelle que soit sa famille, sous la forme normalisée des
  - `line_to_ports(line: Dict, ports: List[Dict]) -> Tuple[Dict, Dict]` — Une ligne de lot rangée dans les PORTS d'un nœud — `({port: valeur}, réglages)`.
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

Endpoints génériques : sortir une card d'un batch, réordonner DANS un lot, ordonner la FILE (`reorder_queue`, 2026-09-04), déplacer, FUSIONNER (`merge`) et consolider. ⚠ `merge` ≠ `consolidate` : le premier fusionne en UN lot et REFUSE si les natures ne cohabitent pas (geste du drag&drop, on a visé une card) ; le second RANGE par nature en N lots. La nature est déclarée UNE fois (`group_key`) et la fabrique INSCRIT le regroupement à l'arrivée de son modèle : `consolidate_arrival`, appelé par tout chemin d'arrivée (dépôt de N fichiers, import du gestionnaire de fichiers, fichier de lot) — aucune app ne le redéfinit depuis le 2026-10-16 (tests_arrival_consolidation)

- **Domicile** : `wama/common/utils/queue_manipulation.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §3bis](../construction/ui/CARD_DESIGN.md)
- **Module** : WAMA Common — Manipulation DIRECTE de la file (CARD_DESIGN §3bis) : vues génériques.
- **API publique** (4) :
  - `consolidate_arrival(work_model, ids, user) -> list` — Range des éléments arrivés ENSEMBLE (un dépôt, un import, un fichier de lot) : un lot PAR
  - `ids_from_request(request)` — Identifiants postés — quelle que soit la FORME de la requête.
  - `make_queue_manipulation_views(*, work_model, batch_model, item_model, fk_name, get_user, item_extra=None, batch_extra=None, group_key=None)` — Retourne {'remove_from_batch', 'reorder', 'reorder_queue', 'move_to_batch',
  - `make_queue_manipulation_views_direct(*, work_model, batch_model, batch_fk='batch', row_field='batch_row_index', get_user, batch_extra=None, group_key=None)` — Variante FK-DIRECTE de ``make_queue_manipulation_views`` — pour les apps dont

### Nom du fichier de sortie

Une règle unique pour les 8 apps à liaison PRÉCOCE, en deux familles : entrée FICHIER → `<stem>_<process>_<modèle>[_<i>]<ext>` (l'utilisateur retrouve SON nom, augmenté de ce qu'on lui a fait et avec quoi) ; entrée PROMPT → `<process><id>_<modèle>[_<i>]<ext>` (l'identifiant de card remplace le nom absent et garantit l'unicité dans un `output/` PLAT). Le suffixe `_<i>` n'apparaît QUE si la card produit plusieurs fichiers — cas réel : `imager.num_images` va de 1 à 4. ⚠ Le mot de process est DÉCLARÉ (`APP_CATALOG['output_tag']`), plus écrit en dur dans chaque tâche (`blurred`, `enhanced`, `gen`… étaient invisibles à tout relevé et impossibles à changer sans toucher chaque app). ⚠ `output/` reste PLAT : c'est le NOM qui porte l'unicité, pas un sous-dossier par card — ce dernier est précisément ce qui a été démonté le 2026-08-25 (`job_<id>/`, 1,7 Go)

- **Domicile** : `wama/common/utils/output_naming.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Nom du fichier de SORTIE — une règle unique pour toutes les apps.
- **API publique** (2) :
  - `output_tag(app: str) -> str` — Mot de process de l'app : déclaré dans `APP_CATALOG`, sinon table de repli, sinon l'app.
  - `compose_output_name(*, app: str, model: str='', ext: str='', source_name: str='', item_id=None, index: int=None, total: int=1, nature: str='') -> str` — Compose le nom du fichier de sortie. Rend un NOM, jamais un chemin.

### Notifications

notify_job_end() — LA fin d'un traitement (squelette de tâche) : e-mail (notify_job) et notification DANS WAMA au propriétaire selon ses préférences, puis aux collaborateurs ; la notification DÉSIGNE son élément (app + type + id), ce que relève la passerelle pour poster la fin dans le fil d'origine (2026-10-06) ; notify_in_app() — DANS WAMA (badge de l'en-tête, page /common/notifications/, lu / non lu) ; SOUND_BY_KIND — les types qui SONNENT dans la page (fin de traitement), selon le réglage « Son dans WAMA » du profil ; notify_admins() — les deux canaux vers les administrateurs (mort d'un worker)

- **Domicile** : `wama/common/utils/notifications.py` · **doc** : [docs/construction/exploitation/WAMA_COLLABORATION.md](../construction/exploitation/WAMA_COLLABORATION.md)
- **Module** : Notifications utilisateur (email) — brique commune, métadonnée/préférence-driven.
- **API publique** (10) :
  - `notify_emails(recipients, subject, body, html=None)` — Envoie un email à une liste d'ADRESSES (pas forcément des Users) — ex. modérateurs.
  - `notify_user(user, subject, body, html=None)` — Envoie un email à l'utilisateur si une adresse est disponible. Fail-safe (jamais d'exception).
  - `notification_sound(notification, user) -> str` — Le son d'une notification pour cet utilisateur : `'done'`, `'failed'`, ou `''` (muette —
  - `notify_in_app(users, kind, title, body='', url='', *, app='', item=None, object_type='', object_id='')` — Crée une notification DANS WAMA pour chaque utilisateur (`common.Notification`, badge de
  - `infrastructure_admins()` — Les comptes qui administrent l'infrastructure : ceux qui GÈRENT le model manager (même
  - `staff_emails(audiences=('admin', 'dev'))` — Adresses d'envoi pour une ou plusieurs audiences du staff : l'adresse FONCTIONNELLE
  - `notify_admins(kind, subject, body, url='', audiences=('admin', 'dev'))` — Prévient le staff technique DANS WAMA (chaque compte qui administre l'infrastructure) et
  - `notify_job_collaborators(item, app_label, item_name, success, detail='', app_id='')` — La fin d'un traitement, aussi pour ceux qui COLLABORENT sur l'élément (E3, décision de
  - `notify_job_end(item, app_id, app_label, item_name, success, detail='')` — LA fin d'un traitement — le point unique des tâches (squelette commun, signal de l'imager).
  - `notify_job(user, app_label, item_name, success, detail='', url='')` — Notifie la fin (ou l'échec) d'un traitement, en respectant les préférences du profil.

### Ordre MANUEL de la file

Position de l'entrée de file décidée par l'utilisateur (`QueueOrderMixin.queue_index`, 13 modèles de batch) + 6ᵉ tri « Manuel » — le SEUL tri qui LIT une colonne au lieu de la calculer. `queue_index == 0` = jamais ordonné à la main, et passe EN TÊTE par récence : une file jamais manipulée s'affiche comme en tri `recent`, et un import arrivé après un classement manuel apparaît en haut au lieu de se noyer dans un ordre qu'il n'a pas connu. `reorder_queue` écrit 1..N

- **Domicile** : `wama/common/models.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §3bis](../construction/ui/CARD_DESIGN.md)
- **Module** : Briques de modèles COMMUNES (cf. BATCH_MODEL_AUDIT.md).
- **API publique** (47) :
  - `job_status_values() -> list` — Les VALEURS des cinq états de FILE, dans l'ordre du vocabulaire.
  - `normalize_job_status(value) -> str` — Un état QUELCONQUE (base, JSON, littéral d'app) → le vocabulaire commun.
  - `class ProcessingTimeMixin(models.Model)` — Durée RÉELLE de traitement, en secondes. Le worker la CALCULE déjà (il la passe au learner
  - `class NativeOutputsMixin(models.Model)` — Les fichiers D'ORIGINE d'une card dont les réglages de sortie transforment le rendu
  - `class KeptOutputsMixin(models.Model)` — Les fichiers de RÉVISION gardés d'une card — ses sorties telles que chaque révision les a
  - `class QueueOrderMixin(models.Model)` — Position MANUELLE de l'entrée dans la file (CARD_DESIGN §3bis — manipulation directe).
  - `class BatchMixin` — Sémantique + cycle de fichiers communs aux modèles Batch (tout est batch ; unitaire = card unique).
  - `class OrgUnit(models.Model)` — Unité organisationnelle = nœud de l'arbre institut/université → département →
  - `class Project(models.Model)` — Projet de recherche = groupe de collaboration EXPLICITE qui peut TRAVERSER l'arbre
  - `class ProjectMembership(models.Model)` — Adhésion d'un utilisateur à un projet, avec son rôle et son org (traçabilité
  - `user_projects(user)` — Ids des projets dont l'utilisateur est membre (tous rôles).
  - `user_scope_org_ids(user)` — Ensemble des OrgUnit ids « couvrant » l'utilisateur : ses unités de rattachement
  - `profile_org_codes(prof)` — Les codes d'annuaire qui RATTACHENT un profil : tous ses rattachements, puis son entité
  - `class ElementPreference(models.Model)` — ABONNEMENT d'un utilisateur à un élément de catalogue (app, modèle, fonction, skill…).
  - `class UserAppSetting(models.Model)` — RÉGLAGE GLOBAL d'un utilisateur pour une app — DURABLE (brique `utils/user_settings.py`).
  - `class Notification(models.Model)` — Notification DANS WAMA — la brique de `WAMA_COLLABORATION.md §2.3` : destinataire, type
  - `class ScopedVisibility(models.Model)` — Mixin ABSTRAIT : visibilité par scope (privé / PROJET / unité org / public).
  - `scoped_visible_q(user, owner_field='user', model=None)` — `Q` filtrant les objets ScopedVisibility visibles pour `user` : les siens + les
  - `catalogue_visible_q(user, owner_field='owner', model=None)` — `Q` des éléments d'un CATALOGUE (modèles, puis librairies, fonctions…) que `user` voit
  - `class ShareConsent(models.Model)` — Le CONSENTEMENT donné en partageant un élément qui porte une PERSONNE — et son retrait.
  - `class ReceivedEntry(models.Model)` — Le RANGEMENT, chez le destinataire, d'une entrée de file qu'on lui a partagée (2026-10-02).
  - `class ObjectGrant(models.Model)` — Un DROIT sur une instance — et la DEMANDE de ce droit : la même ligne (2026-10-03).
  - `class ReleasedFile(models.Model)` — Un fichier que plus aucune card n'appelle — GARDÉ, l'utilisateur prévenu (2026-09-30).
  - `class PromptScoped(models.Model)` — Modèle portant un prompt utilisateur TRAITÉ par la PromptPipeline (enrichissement).
  - `class ScopedQuerySet(models.QuerySet)` — QuerySet des modèles `ScopedVisibility` : expose `visible_to(user)`.
  - `class ScopedManager(models.Manager.from_queryset(ScopedQuerySet))` — Manager par défaut des modèles partageables.
  - `class UserFunction(ScopedVisibility)` — Fonction de traitement CRÉÉE PAR UN UTILISATEUR (WAMA Data), stockée en BDD, avec
  - `class UserTheme(ScopedVisibility)` — Un thème tiré d'une CHARTE graphique (PDF) — pour un labo, une équipe, un établissement
  - `class PromptSkill(ScopedVisibility)` — Un SKILL de prompt qui a un AUTEUR (`ROADMAP §29`, décision de Fabien du 2026-10-20 :
  - `class Pronunciation(ScopedVisibility)` — Comment la VOIX dit un terme — une entrée du lexique de prononciation qui a un AUTEUR
  - `class Manifest(models.Model)` — Store des MANIFESTES (union discriminée par `manifest_kind`) — cf. WAMA_MANIFEST_SPEC.md.
  - `class Library(models.Model)` — Registre des librairies externes — **NÉ de la projection** du manifeste `library`.
  - `class RunOutcome(models.Model)` — Journal des FAITS observés sur un résultat produit — préalable de toute auto-amélioration
  - `class ItemRevision(models.Model)` — Une RÉVISION d'un élément : l'état que lui a donné un résultat produit — marche 8a de
  - `class ProcessRun(models.Model)` — La LIGNE D'EXÉCUTION d'un process : « tel process, pour telle card, dans tel état » —
  - `class BatchSettings(models.Model)` — Les réglages de RÉFÉRENCE d'un lot — ce que la card mère tient (`MODES_QUEUE_UX §5ter`,
  - `class BatchLabel(models.Model)` — Le NOM qu'un utilisateur donne à un lot (2026-10-19, demande de Fabien) — il prime sur le
  - `class ResultEvaluation(models.Model)` — La MESURE d'un résultat contre sa référence — chaînon ⑥ de `WAMA_QUALITE.md §5`, et la matière
  - `class ScheduledAction(ScopedVisibility)` — Une action PROGRAMMÉE — le QUAND du calendrier, la seule table neuve de son plan
  - `class CalendarFeed(models.Model)` — Jeton d'ABONNEMENT au calendrier `.ics` d'un utilisateur (`WAMA_MEMORY §9bis.1`).
  - `class Embedded(models.Model)` — Socle vectoriel commun au souvenir et au fragment. ABSTRAIT — aucune table.
  - `class MemoryItem(Embedded, ScopedVisibility)` — LE SOUVENIR — un fait, un événement ou une procédure. NON re-dérivable.
  - `class RagChunk(Embedded, ScopedVisibility)` — LE FRAGMENT — un morceau d'un document source. RE-DÉRIVABLE : la source fait foi, donc une
  - `class MediaVector(models.Model)` — Le vecteur d'UNE image portée par un élément de file — la recherche de la file par CONTENU
  - `class Conversation(models.Model)` — Un fil de dialogue avec l'assistant, quelle que soit la surface qui le porte.
  - `class ConversationTurn(models.Model)` — Un tour de conversation — ce que l'utilisateur a dit, ou ce que l'assistant a répondu.
  - `class InputProvenance(models.Model)` — D'OÙ vient le fichier d'entrée d'un élément — le LIEN qui manquait.

### Réglages de référence d'un lot (promotion fille ↔ mère)

UNE ligne par lot (`BatchSettings`, adressée comme `ProcessRun`) : ce que la mère TIENT pour référence — posé par sa ⚙ (`batch_update` la retient désormais) ou PROMU d'une fille (`batch_promote`, POST `source=`) ; « ↓ réaligner » (`batch_realign`) la repose sur toutes les filles et efface les écarts individuels. La charge utile est DÉCLARÉE (`promote_payload`), par défaut les réglages du SCHÉMA lus par la règle de la révision ; le monde Data y mettra son protocole — même geste, deux charges. Les trois gestes écrivent par le chemin de la ⚙ de lot (deux temps, un refus n'écrit rien) ; la référence suit la duplication et part avec la suppression. Surfaces : bouton ↓ de la card mère (désactivé et DISANT pourquoi sans référence), entrée « Promouvoir ses réglages au lot » du menu « … » d'une fille. 9 apps câblées + le générateur ; le composer suit avec son câblage pipeline

- **Domicile** : `wama/common/services/batch_settings.py` · **doc** : [docs/construction/ui/MODES_QUEUE_UX.md §5ter](../construction/ui/MODES_QUEUE_UX.md)
- **Module** : Les RÉGLAGES D'UN LOT — ce que la card MÈRE tient pour référence (`MODES_QUEUE_UX §5ter`, `WAMA_APP_GENERATION_ROUTE §10.6` 5.3 ; marche P5, 2026-10-03).
- **API publique** (6) :
  - `address(batch) -> dict` — Adresse d'un lot : `{app, batch_type, batch_id}` — dérivée du lot SEUL (convention de
  - `stored(batch) -> dict | None` — Les réglages de référence du lot, ou None s'il n'en a jamais reçu.
  - `remember(batch, settings: dict, *, source_id='') -> None` — La mère RETIENT ces réglages comme référence — réécrits, jamais empilés. `source_id` : la
  - `forget(batch) -> int` — Le lot disparaît : sa référence aussi. Rend le nombre de lignes retirées.
  - `references_for(batch_model, batch_ids) -> dict` — `{id de lot (int): id de la fille promue ('' pour la ⚙ de la mère)}` des lots de
  - `settings_of(item, schema=None) -> dict` — Les réglages d'UNE fille, prêts à être promus : ceux de son schéma d'app, lus par la

### Tri/filtrage de la file

Tri + filtrage communs de la file unifiée, préférence persistée et PARTAGÉE entre apps

- **Domicile** : `wama/common/utils/queue_view.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)
- **Module** : WAMA — Tri + filtrage COMMUNS de la file unifiée (batches_list).
- **API publique** (1) :
  - `apply_queue_sort_filter(request, batches_list, *, name_of)` — Applique le tri + filtrage de file (persistés en session) et renvoie

### Vues de lot (fabrique commune)

Les six ACTIONS de lot en une fabrique — `make_batch_views` : batch_start, batch_update, batch_delete, batch_duplicate, batch_download, batch_status — et l'ÉCRIVAIN de ZIP partagé avec la file (`zip_elements`, 2026-10-17 : rendu late-binding, sinon les sorties DÉCLARÉES de la card ; nommage déclaré ici une fois ; `ResultArchive` depuis le 2026-10-20, qui range dans UN ZIP les cards de plusieurs apps — celui d'une exécution du Studio ; `lot_overview`, la règle d'état d'un lot de `batch_status`, extraite le même jour pour le run de lot du Studio) — paramétrée comme la fabrique de file (les deux formes de rattachement par `batch_elements`/`attach_to_batch`). EXTRAITE le 2026-09-22 des corps conventionnels du générateur d'apps (`views_gen`), qui la consomme ; les apps réelles les écrivaient chacune à la main (60 lectures de lot recopiées, `ROUTE §11 #36`) — ADOPTÉE 10/10 le 2026-09-23, spécificités en kwargs (jamais un `if app`), chaque élément lu portant `batch_link` (la ligne qui le porte). Plus aucune vue de lot locale depuis le 2026-10-02 : le ZIP multi-format lit les formats DÉCLARÉS et le rendu ENREGISTRÉ (`export_formats`), et `batch_update` appelle la fonction de réglage de l'APP, celle de sa route d'élément (`apply_settings` — le lot et l'élément ne peuvent plus diverger ; refus = 400, aucune fille écrite). Critère `batch_views_common` VRAI 10/10 ; garde générique `tests_item_settings_contract.BatchSettingsFollowTheItemRouteTest`

- **Domicile** : `wama/common/utils/batch_views.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — Les VUES DE LOT : fabrique commune (`make_batch_views`).
- **API publique** (11) :
  - `read_settings_payload(request, schema=None, schema_names=(), empty_is_value=())` — Les RÉGLAGES postés à une vue d'édition — JSON ou formulaire, coercés selon le schéma.
  - `apply_item_settings(item, data, *, params_fields=(), options_field=None, extra_names=())` — Pose sur `item` les réglages présents dans `data` — colonnes déclarées (`params_fields`)
  - `columns_snapshot(item) -> dict` — Les colonnes de `item` telles qu'elles sont À CET INSTANT — à prendre juste après l'avoir
  - `columns_changed(item, before: dict) -> list` — Les colonnes que l'écriture des réglages a CHANGÉES depuis `columns_snapshot` — ce que
  - `write_element_settings(item, data) -> list` — Pose `data` sur l'élément `item` par l'écrivain de réglages DÉCLARÉ de son app — celui de sa
  - `element_label(item, item_label=None) -> str` — Le nom LISIBLE d'un élément : celui que l'app déclare (`item_label`), sinon le premier de ses
  - `zip_elements(work_model, items, request, declaration=None)` — Le ZIP des RÉSULTATS de `items` (seuls les éléments réussis y entrent) : `(tampon, format)`.
  - `class ResultArchive` — Les entrées d'un ZIP de RÉSULTATS, nommées sans collision — l'écrivain que partagent le ZIP
  - `export_stem(work_model, item, declaration=None)` — Souche d'une entrée RENDUE : celle que l'app déclare (`output_name`), sinon la règle
  - `lot_overview(statuses, total=None) -> tuple` — `(comptes, état global)` d'un LOT d'après l'état de ses éléments — la règle de
  - `make_batch_views(*, work_model, batch_model, get_user, task=None, file_fields=(), output_fields=(), output_field='output_file', params_fields=(), schema=None,…` — Retourne les huit vues de lot : {'batch_start', 'batch_update', 'batch_delete',

### Vues de progression (fabrique commune)

Le suivi d'UNE card (`progress`), la barre de FILE (`global_progress`) et le ZIP de cette file (`download_all`, 2026-10-17 : la même déclaration `queryset` / `domains`, les entrées par `batch_views.zip_elements`) en une fabrique — `make_progress_views` (`ROUTE §11 #37`, 2026-10-03). Les dix apps les écrivaient à la main : trois formules de progression d'ensemble, quatre vocabulaires de clés que le JS commun absorbait. UNE formule, celle du contrat de la barre commune (réussi = 100, en cours = sa progression vivante, échec et attente = 0 : un échec n'est pas terminé), un vocabulaire COMPLET ; les spécificités en crochets (`eta_for` = le triplet d'ETA, déclaré UNE fois dans le module de tâches — `<app>_eta_key_size`, que la glu rend aussi à `record_run` — pour une app à un seul process ; une card à process est estimée par `process_runs.launch_eta`), `extra`, `progress_of` — même crochet que `batch_views` —, `pipeline_model` pour la bande des process, `domains` pour une barre par domaine ; utilisateur par défaut : connecté, sinon anonyme). Le générateur d'apps la consomme. Critère `progress_views_common` ; contrat générique `tests_item_lifecycle_contract` (clés d'une card et de la file, toutes les apps)

- **Domicile** : `wama/common/utils/progress_views.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §11](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — Les VUES DE PROGRESSION : fabrique commune (`make_progress_views`).
- **API publique** (3) :
  - `queue_progress(rows) -> dict` — Les compteurs d'une file et sa progression d'ensemble, au vocabulaire COMPLET.
  - `request_user(request)` — L'utilisateur d'une requête de file : le compte connecté, sinon le compte anonyme partagé
  - `make_progress_views(*, work_model, app_id: str, get_user=request_user, progress_field: str='progress', progress_of=None, error_field: str='error_message', eta_…` — Les vues de FILE d'une app : `{'progress': vue(request, pk), 'global_progress':

## UI générée

### Ajout à la file (mode attache)

Bouton « Ajouter à la file » de la card d'entrée : consigne + réglages du volet + fichier joint ou désigné par port (`appendInput`), URL postée seulement si l'élément la garde (sinon refusée, motif dit), rien n'est lancé (règle des deux temps). Côté serveur : `received_inputs`. Forme d'entrée DÉDUITE de l'obligation des ports (`app_registry.entry_form`, 2026-10-19 — dépôt / attache / mixte), lue par la card v4, le générateur (`views_gen.card_entry`) et `WamaImport({attach: 'card'})`. Adoptée le jour même par imager, avatarizer, composer et synthesizer (leur formulaire maison retiré). `ports: 'card'` (05/10) : les ports relus sur la card v4 à chaque envoi, chacun posté sous son nom — le relevé que le composer et le générateur écrivaient chacun ; lus par la brique de la card (`WamaInputSlots.filePorts`, 2026-10-20), la seule lecture des onglets hors d'elle

- **Domicile** : `wama/common/static/common/js/wama-app-base.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Axe de temps partagé (transport commun)

L'AXE auquel les vues s'abonnent et que le magnéto pilote — jamais une vue (`WAMA_DATA_WORLD §5bis`) : lecture, pause, aller, sauts, vitesse signée, shuttle ; un média attaché est l'horloge en avant, l'axe avance seul et le recale en arrière (lecture silencieuse) ; vitesse CHOISIE distincte du cran de shuttle ; clavier du magnéto. Né le 2026-10-15 avec la partition du composer ; l'éditeur du transcriber y est porté le 2026-10-20 (parité geste par geste, `transcriber.editor_parity`) ; le cam_analyzer reste à porter (matrice de parité). Le 2026-10-21 : le TRANSPORT commun montable partout (`wama-transport.js`), les règles des SEGMENTS sans DOM (`wama-segments.js`) et les PICS FINS d'un média au commun (`waveform.dense_peaks`, fichier dérivé au dossier caché comme la copie de lecture). Le même jour, REDÉCOUPAGE décidé par Fabien — quatre niveaux, aucun ne connaît les autres : l'axe (le temps), le transport (ses COMMANDES seulement), les VUES qui le regardent (la ligne de temps `wama-timeline.js` : onde fenêtrée et couches, bande de qualité, minimap, zoom, outil Bornes) et les OUTILS DE DOMAINE (l'écriture à la lecture, brique `playback_writing`) ; un « aller à » se dit aux abonnés (`seek(t, 'goto')`)

- **Domicile** : `wama/common/static/common/js/wama-axis.js` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)

### Barre d'outils générale (registre + profils)

UN registre d'outils (l'UNION de toutes les barres) et des PROFILS par nature de surface : `file` (12 files d'app) et `registre` (15 catalogues). Une surface tire des outils, elle ne les énumère pas — ajouter un outil à toutes les files est UNE clé, plus jamais douze gabarits (demande Fabien 2026-09-08 : « de façon globale, pas par app »). Les deux barres historiques SURVIVENT en façades vers `_toolbar.html`, ce qui laisse les 27 pages appelantes inchangées ; les deux ENVELOPPES sont conservées telles quelles (les fondre aurait changé les deux apparences). Chaque outil est un partial sous `common/toolbar/`

- **Domicile** : `wama/common/toolbar.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)
- **Module** : Barre d'outils COMMUNE — UN registre d'outils, des PROFILS par nature de surface.
- **API publique** (3) :
  - `class Outil` — Un outil de barre. `partial` est la SEULE chose qui rend — le registre ne rend rien.
  - `outils_du_profil(profil: str) -> list` — Les `Outil` du profil, dans l'ordre déclaré. Profil inconnu → `KeyError` explicite.
  - `enveloppe_du_profil(profil: str) -> str`

### Barre de filtrage

Recherche + facettes EN DIRECT ; options dérivées du DOM (client) ou déclarées (server). Depuis le 2026-09-08 la recherche est un OUTIL du registre de barre (`toolbar_registry`), donc la même dans les registres et dans les 12 files. Masquage PAR CLASSE (`.wama-f-hors-filtre`) et non par `style.display` : une cible à `display` inline (l'entrée unitaire de file est en `display:contents`) ne survivait pas à la restauration. `data-cible-dans` BORNE la recherche — sans quoi deux files sur une même page se filtreraient l'une l'autre. `data-cible-vivante` (2026-09-28, calendrier) : une liste RE-RENDUE par un composant est relue à chaque application, et le composant appelle `WamaFilterBar.refresh(barre)` après rendu. Mode `remote` (2026-10-01, médiathèque) : la page charge sa liste elle-même, la barre émet `wama:filter-change` ({q, facets, sort}) ; outil de tri `sort_by` déclaré par la page

- **Domicile** : `wama/common/static/common/js/wama-filter-bar.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Bouton de cycle

Bouton commun ▶/⏹/↻ toujours vert — l'icône porte l'action, l'état vit sur la card

- **Domicile** : `wama/common/static/common/js/wama-cycle-button.js`

### Capture caméra / micro du navigateur

Montée par base.html avant ses consommateurs : TOUTE ouverture de la caméra ou du micro passe par `WamaCapture` — contexte sécurisé vérifié avant de rien demander, refus EXPLIQUÉ par périphérique (autorisation, absence, occupé), périphérique choisi et repli sur celui par défaut, liste des périphériques AVEC leurs noms (la demande d'autorisation qu'elle exige est refermée aussitôt), réglages accordés et zoom matériel, enregistrement, permission lue sans rien demander, pistes rendues à l'arrêt et au `pagehide`. Consommée par l'écoute de l'assistant (et le Speak du transcriber, par elle), l'enregistrement de la médiathèque, les mains et le temps réel du Face Analyzer ; aucune page n'appelle `getUserMedia` elle-même (garde `tests_capture`), et les consommateurs sont rejoués chaque nuit (`common.capture.ui`). Elle ouvre le périphérique, elle ne traite pas le flux

- **Domicile** : `wama/common/static/common/js/wama-capture.js` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)

### Card v3

Dimensionnement déclaratif des pistes de card — dépend de l'app, des actions, des libellés (l'autre moitié vécue de la v3 — densités, pile — vit au front de file : queue_front, qui appelle WamaCardV3.measure)

- **Domicile** : `wama/common/static/common/js/wama-card-v3.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md §11](../construction/ui/CARD_DESIGN.md)

### Card « Nouvel élément »

Card d'entrée dépliable commune — les 6 modalités du partial : dépôt, URL, médiathèque, lot, dossier, live + slot de référence typé (extra_zone) — auto-init. v4 : un onglet par PORT, ses tuiles dans un ordre CONSTANT sur tous les ports — Importer · Médiathèque · URL, du plus proche au plus distant (Fabien, 2026-10-01, `CARD_DESIGN §11.11 B`)

- **Domicile** : `wama/common/static/common/js/wama-new-item-card.js` · **doc** : [docs/construction/ui/MODES_QUEUE_UX.md](../construction/ui/MODES_QUEUE_UX.md)

### Chips méta des cards

Chips des cards GÉNÉRÉS du schéma params (chip=True), groupés par section v3 (chips_by_section) ; `values` pour les réglages vivant en JSON (même assiette que card_gear), `extra` pour les chips d'app déjà formés. Porte aussi les réglages COMMUNS aux filles pour la card MÈRE (common_chips_for_items + partial _batch_meta_chips — slot meta_template, généralisation du pilote transcriber, porté aux 10 apps le 31/08), leur pendant, ce qui VARIE d'une fille à l'autre (varying_chips_for_items, identité du lot, 2026-10-19) et les propriétés d'ENTRÉE (input_props_for, extraite du pilote reader)

- **Domicile** : `wama/common/utils/card_chips.py` · **doc** : [docs/construction/ui/CARD_DESIGN.md §10.3](../construction/ui/CARD_DESIGN.md)
- **Module** : WAMA Common — CHIPS méta des cards (CARD_DESIGN §10.3, pilote Reader 2026-07-06).
- **API publique** (6) :
  - `field_unit(field) -> str` — L'UNITÉ d'un champ numérique : `unit` s'il est déclaré, sinon un `chip_label` COURT en
  - `chips_for(instance, params_json, extra=None, values=None)` — Construit la liste des chips d'une card depuis le schéma sérialisé (schema_to_dicts).
  - `input_props_for(instance, file_field='input_file', name='')` — Sous-ligne « propriétés RÉELLES du média » de la section ENTRÉE (CARD_DESIGN §11).
  - `common_chips_for_items(items, params_json, values_of=None)` — Chips des réglages COMMUNS aux filles d'un lot — pour la card MÈRE (slot
  - `varying_chips_for_items(items, params_json, values_of=None)` — Le PENDANT de `common_chips_for_items` : les réglages `chip=True` qui DIFFÈRENT d'une fille
  - `chips_by_section(instance, params_json, extra=None, values=None)` — Mêmes chips que `chips_for`, mais GROUPÉS par section de card v3 (CARD_DESIGN §11).

### Clavier des briques (une touche, un propriétaire)

Le module unique qui reçoit les frappes et les distribue selon la règle décidée par Fabien le 2026-10-29 : une touche déjà prise plus près du focus n'est pas redistribuée ; sous une couche ouverte (modale, panneau), seule une couche INSCRITE la reçoit (la visionneuse, le menu de card) ; une saisie ne passe que les touches déclarées (Ctrl+Espace) ; la brique qui a la main d'abord, puis les PRIORITAIRES (le transport) ; un observateur suit sans prendre. TOUTES les briques y sont inscrites depuis le même jour (aucune n'écoute plus le clavier de la page elle-même, `tests_surfaces.PageKeyListenersTest`). Les touches de chaque brique se DÉCLARENT au registre des briques (`surfaces.UIBrick.shortcuts`), d'où la liste de l'aide de la page (contrôles de page) et du catalogue

- **Domicile** : `wama/common/static/common/js/wama-keys.js` · **doc** : [docs/construction/ui/WAMA_VOLETS.md §3-ter](../construction/ui/WAMA_VOLETS.md)

### Console utilisateur

Lignes de journal structurées par utilisateur et par app. ⚠ Annoncé « via Redis », mais le chemin Redis exige `django_redis` — ABSENT des deux venvs et des `requirements` (vérifié 2026-08-22) : la console tourne DEPUIS TOUJOURS sur son repli cache, qui fonctionne mais n'est pas atomique (lire/insérer/réécrire, donc des lignes perdues quand gunicorn et les workers Celery poussent en même temps). Le correctif n'est PAS d'ajouter la dépendance : le client `redis` brut est déjà installé et la brique d'accès existe (`resource_governor._redis`, via `CELERY_BROKER_URL`)

- **Domicile** : `wama/common/utils/console_utils.py`
- **Module** : WAMA Unified Console Logging
- **API publique** (2) :
  - `push_console_line(user_id: int, line: str, level: str='info', app: str='system', maxlen: int=500) -> None` — Append a structured log line to the user's console buffer.
  - `get_console_lines(user_id: int, levels: Optional[List[str]]=None, app: Optional[str]=None, limit: int=200) -> List[dict]` — Retrieve structured console lines for a user.

### Contrôles de page (disposition, aide)

Ce qui vaut pour TOUTE la page vit dans l'en-tête, jamais dans une brique qu'une disposition peut déplacer (décision de Fabien, 2026-10-29) : le CADENAS, montré quand la page offre une disposition (le volet des pages d'apps, une surface), dont le bandeau prend la place du logo — « Disposition par défaut », « Figer » — et affiche les gestes sans prendre le pointeur ; l'AIDE de la page (touche « ? »), qui liste les raccourcis des briques de CETTE page, lus au registre des briques (`volet.page_controls_config` : chacune avec ce qui dit qu'elle est sur la page), la disposition et les gestes. Une page y DÉCLARE ce qu'elle apporte (`offerLayout`, `addShortcuts`, `addHelp`) ; le module ne nomme aucune page

- **Domicile** : `wama/common/static/common/js/wama-page-controls.js` · **doc** : [docs/construction/ui/WAMA_VOLETS.md §3-ter](../construction/ui/WAMA_VOLETS.md)

### data-* du gear ⚙ des cards

data-* du ⚙ DÉRIVÉS du schéma (contrat cardSettings de l'inspecteur, qui lit la RACINE de card PUIS le bouton) — schéma en objets Param OU en dicts (chemin des vues générées) ; booléens 'true'/'false', tous les params item émis (anti-résidus)

- **Domicile** : `wama/common/utils/card_gear.py`
- **Module** : data-* du bouton ⚙ d'une card — GÉNÉRATION COMMUNE dérivée du schéma (extraite 2026-08-18).
- **API publique** (1) :
  - `gear_data(instance, params, values=None, extra=None) -> dict` — dict {nom-a-tirets: valeur aplatie} pour les data-* du bouton ⚙ (voir docstring).

### Domaines → modes

Schéma déclaratif des onglets-domaine et modes par app — scope la file ; un domaine NOMME son schéma de réglages (`params_schema`), sa surface est la clé de son modèle d'élément et le domaine d'un élément se dérive (`element_domain`) ; un mode est un RÉGLAGE (`mode_param`) qui borne le menu de modèles (`options_mode`)

- **Domicile** : `wama/common/utils/app_modes.py` · **doc** : [docs/construction/ui/MODES_QUEUE_UX.md](../construction/ui/MODES_QUEUE_UX.md)
- **Module** : Schéma déclaratif DOMAINES → MODES des apps — clé de voûte UX (voir MODES_QUEUE_UX.md).
- **API publique** (19) :
  - `get_app_modes(app: str) -> dict` — Schéma {domains:[…]} d'une app, ou {} si non déclaré.
  - `get_domains(app: str) -> list`
  - `has_domain_tabs(app: str) -> bool` — True si l'app a PLUSIEURS domaines (→ afficher des onglets). Sinon : modes directs.
  - `library_nature_for(app: str, port_id: str) -> str` — La nature de médiathèque sur laquelle s'ouvre la sélection pour ce PORT ('' si aucune).
  - `get_domain(app: str, domain_id: str) -> dict`
  - `get_mode(app: str, domain_id: str, mode_id: str) -> dict`
  - `route_prefix(app: str, domain_id: str) -> str` — Préfixe des routes de ce domaine (`audio` → `audio_batch_delete`), '' par défaut.
  - `surface_name(app: str, prefix: str='') -> str` — La SURFACE d'une famille de routes : l'app, préfixée par le `route_prefix` de son domaine
  - `domain_surface(app: str, domain_id: str) -> str` — La surface de ce domaine (`surface_name` de son `route_prefix`).
  - `surface_domains(app: str, surface: str) -> list` — Les domaines de l'app que cette surface sert — un seul, sauf quand deux domaines
  - `domain_schema_name(app: str, domain_id: str) -> str` — Le nom du schéma de réglages de ce domaine (`*PARAMS_JSON` du module `params` de l'app),
  - `domain_schema(app: str, domain_id: str) -> list` — Le schéma de réglages de ce domaine : celui qu'il nomme, sinon le principal de l'app.
  - `element_domain(element) -> str | None` — Le domaine d'un ÉLÉMENT, dérivé de ce qui est déjà déclaré : la surface de son modèle
  - `accepts(app: str, domain_id: str) -> tuple` — Catégories média (MEDIA_CATEGORIES) que ce domaine prend en ENTRÉE.
  - `domain_for_category(app: str, categorie: str) -> str | None` — Domaine d'une app capable d'accueillir cette catégorie média — base du ROUTAGE d'un
  - `mode_param(app: str, domain_id: str) -> str` — Le param du schéma qui porte le mode de ce domaine ('' si le domaine n'en déclare pas).
  - `options_mode_for(app: str, domain_id: str) -> dict` — La déclaration `Param.options_mode` d'un select de modèle borné par le mode de ce
  - `mode_model_filter(app: str, domain_id: str, mode_id: str) -> dict` — Ce que le mode impose au MODÈLE, dans le vocabulaire de `model_selector.matches_inputs` :
  - `resolve_inputs(porteur: dict) -> list` — Détaille les entrées d'un MODE ou d'un DOMAINE (définitions `INPUT_TYPES`).

### Déclaration du volet par la page

Une page DÉCLARE les sections du volet droit qu'elle garde (retrait, jamais ajout) ; sans déclaration, l'état d'avant — les apps n'écrivent rien (context processor volet_defaut). 2026-10-28 : ses sections sont des panneaux de la disposition COMMUNE (`wama-brick-layout.js`, sans grille au centre) — réordonnées, retaillées, empilées, épinglées à un bord, gardées par compte et par page (`PANEL_SLOTS`, route `panel_layout`, validées par `clean_layout`) ; le volet reste celui d'avant tant que le compte n'a rien disposé, une section masquée retire son panneau (`setShown`) ; `arrangeable=False` pour une page qui a sa disposition (surface) ou la fera brique par brique (cam_analyzer) — scénario `common.panel_layout`. Même jour, étape ④ : la card d'entrée, la progression, la barre de la file et la file d'une page d'app sont les briques de la grille du centre, dans la même disposition (`centre_slots`, un jeu par domaine, marques `data-wama-brick` posées par les pièces communes ; à la hauteur de leur contenu sauf la file) — scénario `common.centre_layout`

- **Domicile** : `wama/common/utils/volet.py` · **doc** : [docs/construction/ui/WAMA_VOLETS.md §8](../construction/ui/WAMA_VOLETS.md)
- **Module** : Déclaration du VOLET DROIT par la page — `WAMA_VOLETS.md §8 n°2`.
- **API publique** (7) :
  - `volet(*, tete: bool=False, medias: bool=True, parametres: bool=True, actions: bool=True, arrangeable: bool=True) -> dict` — Déclaration de volet, toujours COMPLÈTE (cf. le pourquoi dans l'en-tête du module).
  - `class PanelSlot` — Une section du volet comme emplacement de la disposition commune : la COLONNE du volet
  - `page_key(request) -> str` — La page dont on garde la disposition du volet : l'espace de noms de sa route — le plus
  - `layout_of(user, key: str) -> dict` — La disposition du volet que `user` a gardée pour la page `key` (`clean_layout`), `stored` à
  - `is_arranged(layout: dict) -> bool` — Le compte a-t-il disposé ce volet ? Sinon il reste celui d'avant, sans grille.
  - `layout_config(request) -> dict | None` — Ce que `wama-panel-layout.js` lit (`base.html`) ; None sans compte ou sans page nommée.
  - `page_controls_config() -> dict` — Ce que les CONTRÔLES DE PAGE lisent (`wama-page-controls.js`, `base.html`, 2026-10-29) : les

### Entrée de file (card seule OU lot)

Décide, pour une entrée de file, si elle s'affiche en card unique ou en card MÈRE avec ses filles repliables — et rend l'un ou l'autre. Le bloc vivait recopié À L'IDENTIQUE dans les gabarits d'app (10 au dernier compte — le partial fait foi) ; il n'a pu être centralisé (2026-08-25) qu'une fois deux verrous levés : `is_unitary` adopté (la décision se lit sur le modèle) et `elem` (les cards filles reçoivent leur élément sous le MÊME nom — avant, 8 graphies). Signature à 3 paramètres : `card_template`, plus `collapse_prefix` et `batch_key` pour la seule app à deux files sur une page (enhancer audio). ⚠ Tout le reste TRAVERSE PAR LE CONTEXTE — les ~9 paramètres de `_batch_card.html` sont fournis par l'app et passent au travers, sinon la signature atteindrait la quinzaine. Apparence uniformisée sur le TRANSCRIBER (référence), conforme à `CARD_DESIGN §11.2` (famille de lot = cyan #0dcaf0) : les 3 couleurs et 2 habillages qui coexistaient étaient des séquelles d'implémentations successives. Depuis le 2026-09-15 l'entrée porte `data-card-url` : quand une suppression réduit un lot à une card, `queue-actions.js` la redemande au serveur et la file se met à jour sans rechargement de la page (la vue dit l'état du lot : `batch_common.batch_state` ; la position d'une card seule : `is_batch_child`)

- **Domicile** : `wama/common/templates/common/_queue_entry.html` · **doc** : [docs/construction/ui/CARD_DESIGN.md §11.2](../construction/ui/CARD_DESIGN.md)

### File d'attente (front)

Comportements communs des files : collapse de batch persisté, mode Solitaire (accordéon), toggle Ligne/Mosaïque, les 3 densités et le modificateur PILE (CARD_DESIGN §11.4/§11.9), focus card, clearCards, data-wama-*. Et la FILE elle-même, pièce unique depuis le 2026-10-20 (`_queue.html` : barre, conteneur, entrées, état vide — routes lues sous leurs orthographes admises, état vide TOUJOURS rendu et basculé ici) : les dix apps et le générateur l'incluent

- **Domicile** : `wama/common/static/common/js/wama-queue.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Formats de téléchargement (⬇ late-binding)

Vocabulaire commun des formats choisis AU TÉLÉCHARGEMENT (libellé, icône, groupe) + split-button dérivé de la déclaration export_binding — pendant late-binding d'output_formats ; 6ᵉ action de card. Depuis le 2026-09-18, porte aussi le REGISTRE des builders de rendu (`register_export_builder`, un par app late-binding, chemin pointé résolu à l'usage) : c'est ce qui permet au geste médiathèque de rendre le format choisi par LE MÊME code que le ⬇. Depuis le 2026-10-02 le ZIP de LOT lit les deux mêmes déclarations (fabrique `make_batch_views`, format borné par `requested_format`, bouton de la card mère rendu par ce même ⬇) : les trois niveaux — card, lot, barre de file — parlent `?format=`. Depuis le 2026-10-13 la visionneuse commune offre les mêmes formats, et ce qu'un ÉLÉMENT ne peut pas rendre se déclare (`register_export_missing` : le `json` du reader sans résultat brut), lu par le ⬇ de la card (`item=`) et par elle

- **Domicile** : `wama/common/utils/export_formats.py` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md §6.3](../construction/architecture/WAMA_APP_CONVENTIONS.md)
- **Module** : Vocabulaire COMMUN des formats de TÉLÉCHARGEMENT — libellé, icône et regroupement.
- **API publique** (10) :
  - `entry(value: str) -> dict` — Décrit UN format. Un format inconnu du vocabulaire reste affichable (repli neutre) —
  - `entries(formats, available=None) -> list[dict]` — Liste ordonnée d'entrées prêtes pour `common/_download_button.html`.
  - `entries_for_app(app_name: str, available=None) -> list[dict]` — Idem, en lisant la déclaration de l'app — l'appelant n'a que son nom à donner.
  - `register_export_missing(app_name: str, missing) -> None` — `missing` : `(élément) -> itérable des formats déclarés` que CET élément n'a pas.
  - `available_formats(app_name: str, item)` — Les formats déclarés que `item` peut rendre, ou None (= tous ceux que l'app déclare).
  - `requested_format(app_name: str, query) -> str` — Le format DEMANDÉ à un téléchargement d'une app late-binding, lu dans la query du bouton ⬇
  - `download_response(app_name: str, item, query, stem: str)` — Le ⬇ d'UN élément d'une app late-binding : le format DEMANDÉ (`requested_format`, borné aux
  - `is_late_binding(app_name: str) -> bool` — L'app choisit-elle son format AU TÉLÉCHARGEMENT (`export_binding='late'`, §6.4) ?
  - `register_export_builder(app_name: str, builder) -> None` — `builder` : callable `(instance, fmt) -> (ext, bytes) | None`, ou son chemin pointé
  - `export_builder_for(app_name: str)` — Le rendu déclaré par l'app, ou `None`. Une app early-binding n'en déclare pas : son

### Gestes au pointeur (glisser, défiler, pincer, appui long)

Montée par base.html, pour toute page des trois mondes (ROADMAP §27, étape 3, 2026-10-16). Trois choses : (1) `WamaGestures.track(el, {start, move, end, pinch})` suit un pointeur sur une surface qui dessine elle-même — seuil entre clic et glisser, boutons de souris filtrés, PINCEMENT à deux doigts ; Pointer Events, donc souris, stylet et doigt par le même code (canvas du studio, onde de l'éditeur du transcriber) ; (2) le glisser HTML5 AU DOIGT, sur tout `[draggable="true"]` : appui long puis le doigt bouge → `dragstart`/`dragover`/`drop`/`dragend` avec un `dataTransfer` réel, vignette qui suit, liste qui défile au bord — la file, la palette du studio et l'ordre des segments marchent au doigt sans une ligne chez eux, et la souris garde son glisser natif ; (3) l'APPUI LONG : l'infobulle (`title`) d'une commande sans la déclencher, sinon un `contextmenu` (menu de card, arbre — l'iPad n'en émet pas) ; sur ce qu'on glisse, il soulève : bouger glisse, relâcher ouvre le menu. Une page n'écrit ni `touchstart` pour un geste porté ici, ni mousedown/mousemove pour suivre un glisser ; mesuré chaque nuit sur de vrais événements tactiles par `common.gestures.touch`, et les mêmes pages à la souris par `common.gestures.mouse` (la garde du PC)

- **Domicile** : `wama/common/static/common/js/wama-gestures.js` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)

### Glisser-déposer et sélection multiple de la file

Les QUATRE gestes de manipulation directe, hérités par les 12 apps sans qu'aucune n'écrive une ligne : déposer SUR une card change l'APPARTENANCE (entrer dans un lot / en former un), déposer ENTRE deux cards change l'ORDRE (file ou lot) ; sélection multiple clic/Ctrl/Maj, qui EST celle de l'inspecteur (une seule sélection dans WAMA — la brique ANNONCE `wama:selection-change`, l'inspecteur REND). Une CASE en tête de chaque card la dessine (2026-10-16) : la cocher AJOUTE à la sélection, comme Ctrl+clic — à la souris sans clavier comme au doigt ; visible au survol, cochée ou dès qu'une sélection est en cours. Le SURVOL d'une card de file est une règle commune (`wama-inspector.css`), aucune app n'écrit le sien. Auto-monté sur `[data-wama-dnd]`, posé par le templatetag `queue_dnd_attrs` : une app qui ne le pose pas garde une file strictement inerte. SortableJS écarté (multi-sélection + fusion sur une card + règle « pas de CDN »)

- **Domicile** : `wama/common/static/common/js/wama-queue-dnd.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md §3bis](../construction/ui/CARD_DESIGN.md)

### Historique annuler / rétablir

Deux piles + plafond + état des boutons + raccourcis Ctrl+Z / Ctrl+Maj+Z / Ctrl+Y. PORTABLE parce que la machinerie ne touche JAMAIS le modèle : elle ne le connaît que par `snapshot()` et `restore(state)`, que l'appelant fournit. La coalescence des rafales de frappe (`burstWindow`) est une OPTION, pas un acquis — elle n'a aucun sens sur un éditeur non textuel, où chaque mutation est déjà atomique. ⚠⚠ La FILE D'ATTENTE ne peut PAS l'utiliser : ses gestes sont commis côté serveur à l'instant du dépôt, il n'y a pas de modèle client à photographier — son « annuler » est un REJEU D'OPÉRATION INVERSE, même mot, mécanisme différent. Les réunir ici donnerait une API qui MENT sur ce qu'elle garantit. DEUX consommateurs, et deux façons de marquer un cran — c'est l'ADOPTION qui l'a révélé : `push()` AVANT la mutation (transcriber, qui marque en tête de chaque opération) et `commit()` APRÈS (studio, dont les 9 opérations passent par UN entonnoir, `persistDraft`). La v1 n'offrait que `push()` : suffisant pour le consommateur dont elle sortait, insuffisant pour le suivant. `silence(fn)` couvre le chargement programmatique, et la garde de RÉ-ENTRANCE vit dans la brique — restaurer c'est muter (`loadGraph`→`clearCanvas`→`removeNode`→l'entonnoir), donc tout consommateur à entonnoir remplirait son historique de son propre travail

- **Domicile** : `wama/common/static/common/js/wama-history.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Import de dossier récursif

Traversée récursive d'un drop/webkitdirectory — brique F2 montée globale (base.html)

- **Domicile** : `wama/common/static/common/js/wama-folder-import.js` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)

### Inspecteur contextuel (volet droit)

Trois étages (card / lot / file) : sélection → Infos + preview + actions clonées (cloneActions) + PARAMÈTRES reflétés (initFromSchema : panel read/apply dérivés du schéma, cardSettings via card_gear) ; son aperçu (rendu, faces, visionneuse) vient de la brique `preview` (`media-preview.js`, 2026-10-13 — il l'hébergeait, et recopiait la bascule des faces)

- **Domicile** : `wama/common/static/common/js/wama-inspector.js` · **doc** : [docs/construction/ui/WAMA_VOLETS.md](../construction/ui/WAMA_VOLETS.md)

### Inspecteur — champs de détail

Schéma canonique des infos d'item affichées au volet droit

- **Domicile** : `wama/common/utils/detail_registry.py` · **doc** : [docs/construction/ui/INSPECTOR_DETAIL_FIELDS.md](../construction/ui/INSPECTOR_DETAIL_FIELDS.md)
- **Module** : WAMA Common — Registre des DÉTAILS d'item pour l'inspecteur (miroir de preview_registry).
- **API publique** (11) :
  - `props_icon_for(media_type: str) -> str`
  - `normalize_status(status: str) -> str` — Un statut d'app → le vocabulaire commun. Délègue au domicile (`common/models.py`).
  - `class DetailRegistry`
  - `register_app_detail(app_name, model_class, adapter)` — Enregistre l'adapter de détail d'une app. `adapter(instance) -> dict canonique`.
  - `register_app_detail_spec(app_name, model_class, spec)` — Variante DÉCLARATIVE (A3a) : la registration est une SPEC-donnée, pas un callable.
  - `spec_value(instance, form)` — UNE valeur de spec résolue contre l'instance — le vocabulaire entier tient ici :
  - `spec_schema(instance, spec, app_name)` — Le schéma de réglages d'un ÉLÉMENT : celui que la spec choisit pour lui (`params_schema`,
  - `detail_from_spec(instance, spec, app_name)` — Adapter GÉNÉRIQUE : résout la spec déclarative contre l'instance puis délègue à
  - `settings_from_schema(instance, schema, *, skip=(), carrier=None)` — {libellé: valeur} des réglages POSÉS du schéma — la liste « Réglages » du volet, pour les
  - `build_detail(instance, *, source_file=None, source_type=None, engine=None, engine_effective=None, result_file=None, result_files=None, result_role=None, result…` — Assemble le dict canonique d'un item (épine dorsale). Les valeurs vides sont OMISES
  - `unified_detail(request, app_name: str, pk: int)` — Endpoint commun : infos d'un item selon le schéma canonique (miroir de unified_preview).

### Lecteur audio (onde + transport)

Widget autonome : onde canvas (pics serveur ou décodés), play/pause, exclusivité inter-lecteurs et inter-onglets ; monté par la preview dans le volet ET les cards

- **Domicile** : `wama/common/static/common/js/wama-audio-player.js`

### Menu contextuel de card/lot + débordement « … »

Clic droit = la liste COMPLÈTE des actions (+ celles de la SÉLECTION MULTIPLE) ; le « … » de la rangée = le DÉBORDEMENT SEUL, au-delà des 6 actions nominales (bouton édition compris — décision Fabien 2026-09-08). Modèle HYBRIDE : les actions EXISTANTES sont LUES sur le `.btn-group-actions` de la card (contrat de `cloneActions`, donc zéro ligne par app et clic PROXIFIÉ vers le vrai bouton), les TRANSVERSES sont déclarées et leurs URLs viennent de `queue_dnd_attrs` — une route absente n'émet pas son attribut, donc l'entrée n'apparaît pas. Sous-menus en CASCADE, au survol et au clic, le parent restant ouvert (2026-09-14) et DIFFÉRÉS (« Recherche… » puis rempli : il n'attend pas le réseau). Se ferme sur un geste de l'UTILISATEUR hors du menu, jamais sur un `scroll` (un focus programmatique le refermait en 7 ms). 2ᵉ surface : l'arbre de fichiers (`ouvrir()` depuis `filemanager.js`, 2026-09-14), qui obtient depuis le 2026-09-18 les gestes d'ÉLÉMENT (Partager…, Ajouter à la médiathèque…, Ajouter au RAG) sur un fichier de SORTIE par `entreesPourChemin` — le serveur remonte à l'élément (`send_to.item_for_output_path`), les entrées sont CELLES de la card (`entreesPourElement`, une seule liste), posées en ENTRÉE DIFFÉRÉE à la racine du menu (`{chargement, charger}` : « Recherche… » puis remplacement, le menu n'attend pas le réseau). Depuis le 2026-10-14, un fichier qui n'est la sortie de RIEN (dépôt temporaire, entrée d'app, dossier connecté) a « Ajouter au RAG » sur le FICHIER, et une sélection de N fichiers « Ajouter N fichiers au RAG » (`entreesPourChemins`). ⚠ Le menu est posé sur `document.body` : une card vit dans un conteneur à `overflow` qui le rognerait. Le « … » suit les cards INSÉRÉES ou REMPLACÉES après le chargement (observation de la file, 2026-09-15)

- **Domicile** : `wama/common/static/common/js/wama-card-menu.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Panneau de la cloche

Un clic sur la cloche ouvre ses notifications SANS quitter la page (2026-10-13) : ouvrir, lu / non lu, supprimer (avec « Annuler »), tout lire, et les gestes PROPRES à un type — déclarés par le serveur (STYLE_BY_KIND, ACTIONS_BY_KIND : « Accorder / Refuser » une demande d'accès), la page ne connaît aucun type. Ouvrir le panneau ne marque rien comme lu ; le lien de la cloche reste la page complète (Ctrl-clic)

- **Domicile** : `wama/common/services/notification_panel.py` · **doc** : [docs/construction/exploitation/WAMA_COLLABORATION.md](../construction/exploitation/WAMA_COLLABORATION.md)
- **Module** : Ce que le PANNEAU de la cloche montre d'une notification (`WAMA_COLLABORATION.md §2.3`, 2026-10-13, demande de Fabien : *« quand je clique sur la cloche, une petite fenêtre… je veux pouvoir interagir avec les notifications directement dans la petite fenêtre »*).
- **API publique** (3) :
  - `notification_actions(notification, user) -> list`
  - `notification_payload(notification, user) -> dict` — La notification telle que le panneau la rend : texte, état, style, gestes.
  - `notification_list(user, *, unread_only: bool=False, limit: int=20) -> dict` — Les notifications de `user`, les plus récentes d'abord : `{'unread', 'total', 'items'}`.

### Preview unifiée

Registre d'adaptateurs par modèle : la preview des cards vient du commun, pas des apps ; un MIME `model/…` ouvre la visionneuse 3D commune (`wama-3d-viewer.js`, three vendorisé), chargée À LA DEMANDE par l'importmap — sans importmap, téléchargement (2026-09-13, §17ter trou 2). Les faces entre Entrée et Sortie sont les PROCESS du pipeline de la card, DÉRIVÉES de ce qu'il déclare (`_process_faces`, 2026-10-12 — elles se déclaraient à la main, `register(faces=)`, R119) : libellé du process, résultat lisible (`ProcessSpec.result`, un texte) ou fichiers (`outputs`), rendu par le TYPE du port de sortie — des `detections` dessinées sur l'entrée par `WamaPreviewOverlay` (options de dessin : `register(overlay_options=)`) ; une face qui montre ce que montre déjà une autre n'est pas une étape de plus. La dernière face qui montre l'entrée est la référence de Comparer, ouvert aux VIDÉOS synchronisées (2026-10-05). La modale porte les mêmes faces d'où qu'on l'ouvre (volet, vignette de card), suit la face PENDANT en direct avec ses vues — par le MÊME suiveur que le volet (`followDuring`) —, et son PLEIN ÉCRAN est elle-même agrandie (la surcouche image seule ne sert plus qu'aux galeries sans élément). Depuis le 2026-10-12 : la face Entrée se lit, comme la Sortie, dans les clés canoniques du detail (`source_file`, sinon `source_text`) sous la règle des ports (travail, sinon prompt, jamais référence) ; UNE fabrique de face fichier (`file_face`, texte d'un .docx extrait) sert les cards ET le filemanager ; un texte inline voyage sous la seule clé `content` ; une card ouvre son entrée par le geste commun `.preview-media-link` (geste nocturne `<app>.preview`). Depuis le 2026-10-13, UNE brique front (`media-preview.js`, `WamaMediaPreview`) porte tout l'aperçu : rendu en ligne (cards, volet, fenêtre de sélection), bascule des faces COMMUNE au volet et à la visionneuse (`sidesBar`, Pendant compris — le volet en avait sa copie), Comparer (`compareFaces`, `compareView` ; fichier par fichier pour une sortie multiple, titré par ses deux fichiers), suiveur Pendant, visionneuse, et UNE navigation : une séquence (les cards de la file, les fichiers d'un dossier du gestionnaire, une galerie) puis les fichiers d'une sortie multiple — ←/→ fichier par fichier puis élément voisin, ↑/↓ d'élément en élément, face gardée, volet resynchronisé à la fermeture ; le volet et le gestionnaire de fichiers en sont consommateurs (geste nocturne `common.preview_navigation`). Depuis le soir du 2026-10-13, la FORME d'un résultat de process se déclare (`ProcessSpec.result_format`) : markdown mis en forme, RAPPORT de cohérence (score coloré, version proposée en regard du texte vérifié), tours de PAROLE (`segments`, le locuteur dans sa couleur) ; la face « Évaluation » (mesure contre la référence, `result_evaluation`) vient APRÈS la Sortie (`sides.after`) ; la visionneuse offre les TÉLÉCHARGEMENTS que l'app déclare (`export_formats`) et compte les mots de toute face texte — ce que portaient les modales propres du describer et du transcriber, retirées (R125, R126). Depuis le 2026-10-20, la CARD suit la face PENDANT comme le volet et la visionneuse (`followCard`, par le même suiveur et le même rendu en ligne) : son hôte de sortie, ou l'hôte d'attente `data-card-during` que chaque card pose à l'adresse de son élément — le describer y écrivait seul son texte partiel, le transcriber le recopiait dans le panneau de Speak (R158, R162). Depuis le 2026-10-28, la VIGNETTE d'un fichier est une brique (`tileHtml` : l'image, la 1ʳᵉ image d'une vidéo, sinon l'icône de la famille du type), décidée par le type que le serveur résout — lue par la grille d'une sortie multiple, la fenêtre de sélection et la médiathèque, qui l'écrivaient chacune et dont la dernière décidait par la nature de l'onglet (R183)

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

### Repli des volets latéraux par leur frontière

Un clic sur la FRONTIÈRE d'un volet (explorateur, panneau) le replie ou le rouvre, sur toute page : au repos rien de plus que le liseré, au survol une ligne et une pastille à chevron qui suit le pointeur ; volet replié, une trace fine au bord de la fenêtre. État par NAVIGATEUR (localStorage), appliqué avant le premier rendu. La place des volets a une SOURCE UNIQUE : les marges `--wama-left-gutter` / `--wama-right-gutter` (0 replié ou sans volet) que lisent le corps, l'en-tête et les barres fixes des pages ; une règle qui se calerait sur la largeur brute d'un volet est refusée par `tests_panel_toggle`. Au doigt (tablette), la pastille reste visible. Après chaque bascule : `resize` + `wama:panels`. DEUX CONTEXTES DE LARGEUR (2026-10-12) : sous le point de rupture `lg` de Bootstrap (tablette en portrait, fenêtre étroite), volets repliés d'office, un seul ouvert à la fois, mémoire à part — le choix fait en grand n'est jamais écrasé (`WamaPanelsContext`, posé par base.html avant le premier rendu). La barre du haut et le pied sont des grilles `1fr auto 1fr` : rien ne s'y chevauche, les libellés s'effacent derrière leur icône quand la barre manque de place (requête de conteneur) ; mesuré chaque nuit par `common.layout.tablet`

- **Domicile** : `wama/common/static/common/js/wama-panel-toggle.js` · **doc** : [docs/construction/ui/WAMA_VOLETS.md](../construction/ui/WAMA_VOLETS.md)

### Résultat instantané de la saisie

Sous la consigne de la card d'entrée, ce que l'app rendrait — PENDANT la frappe, sans rien mettre en file. Capacité d'app DÉCLARÉE (`instant_preview`, lue par `instant_result_url`) ; une source, la route `instant` du manifeste, d'où dérivent la vue générée (la glu `tasks.instant_result` sur un élément NON enregistré, réglages par la cascade de l'ajout), sa route et le trou de glu. Délai de saisie, seule la dernière réponse s'affiche (`CARD_DESIGN §11.11 D bis`)

- **Domicile** : `wama/common/static/common/js/wama-instant.js` · **doc** : [docs/construction/ui/CARD_DESIGN.md](../construction/ui/CARD_DESIGN.md)

### Schéma de paramètres

Source unique des réglages d'app : volet droit, modales (item ET lot, `context`) et DÉFAUTS APPLICABLES d'un élément naissant (applicable_defaults, filtre show_if au vocabulaire du moteur JS) sont dérivés de lui. Depuis le 01/09 il porte AUSSI LA cascade des valeurs effectives (effective_settings : défauts du schéma ← preset ← réglages POSÉS — formulation Fabien, ROADMAP §23.2bis) : la base ne stocke que le POSÉ (vide = « le preset décide »), les défauts restent au schéma — c'est ce qui rend un preset POSSIBLE, et ce qui a remplacé resolve_options du converter + les défauts en dur des backends. Depuis le 12/10 (ROUTE §10.6 3.3bis, R1) c'est LA forme de tous les mondes : le pont `param_from_spec` projette les `ParamSpec` d'une fonction sans perte, le Studio rend tous ses nœuds par WamaParams (renderer commun `media_picker`, `isGesture`), et la PORTE des refus (`schema_refusals`/`checked_values` : choix hors liste, nombre illisible ou hors grille) est lue par la porte des outils, le lancement d'un graphe, l'exécution d'une fonction et le moteur de vue Data. Depuis le 18/10 un PORTEUR peut valoir une LISTE, lue « l'une de » par les deux juges de `show_if` (la nature encore inconnue de ce que reçoit un nœud du Studio : les réglages de chaque nature possible se montrent), et la réduction de la ⚙ d'UN process a son jumeau serveur (`scoped_names` ⟷ `scopedSchema`), lu par le nœud d'étape et son exécuteur. La TEMPÉRATURE commune (2026-10-21) : `temperature_param(<champ modèle>)`, type `temperature` (vide = celle du modèle), lié à son modèle par une LISTE de `cap_from` (`cap_bindings` ⟷ `capBindings`) — grisé s'il ne tire pas, valeur de l'éditeur rappelée, borné au maximum et au minimum du moteur, une ligne qui dit si le résultat est REPRODUCTIBLE (2026-10-22). Et une condition `show_if` dont le champ n'est pas RENDU dans le conteneur ne cache rien (même date). Un réglage `advanced` sans groupe se range dans le groupe « Avancé » replié sur TOUTE surface, la température comprise (même date), avec ses deux voisins `seed_param` / `top_p_param` (types `seed`, `top_p`) ; vide = un CHOIX pour les trois (`EMPTY_IS_NONE_TYPES`), la graine de l'imager comprise

- **Domicile** : `wama/common/utils/param_schema.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Schéma de paramètres WAMA — source unique pour rendre les réglages d'une app dans TOUTES les surfaces (modale item/batch, volet inspecteur card/batch/file) depuis une seule description, au lieu de markup dupliqué par template (cause des divergences).
- **API publique** (40) :
  - `class Param` — Description d'UN paramètre, indépendante de la surface de rendu.
  - `format_display(value, display_format: str) -> Optional[str]` — La valeur dans le FORMAT déclaré (`Param.display_format`), None si le format est inconnu
  - `derive_from_model(model_class, include: List[str], overrides: dict=None) -> List[Param]` — Construit la liste de `Param` d'une app à partir des champs d'un modèle Django.
  - `class ParamGroup` — Groupe d'affichage d'une surface de saisie (modale ⚙ / volet) — l'app le déclare,
  - `groups_to_dicts(groups: List[ParamGroup]) -> List[dict]` — Sérialise les groupes pour le front (JSON) / un template.
  - `schema_to_dicts(params: List[Param]) -> List[dict]` — Sérialise un schéma pour le front (JSON) / un template.
  - `cap_bindings(p) -> List[dict]` — Les liaisons `cap_from` d'un réglage, toujours en LISTE (un dict seul, la forme d'avant
  - `temperature_param(model_field: str, **overrides) -> dict` — Surcouche STANDARD du réglage de température, liée au choix de modèle `model_field` du
  - `seed_param(model_field: str, **overrides) -> dict` — Surcouche STANDARD de la graine, liée au choix de modèle `model_field` : colonne
  - `top_p_param(model_field: str, **overrides) -> dict` — Surcouche STANDARD du top_p, liée au choix de modèle `model_field` : colonne
  - `sampling_of(source, prefix: str='') -> dict` — Les réglages de tirage d'un élément (ses colonnes `<prefix>temperature`, `<prefix>seed`,
  - `sampling_options(source, prefix: str='') -> dict` — `sampling_of` réduit à ce qui est RÉGLÉ — le `options` d'un moteur (le contrat uniforme de
  - `condition_fields(cond) -> List[str]` — Les champs qu'une condition `show_if` LIT — un seul, ou ceux de chaque branche d'un `any`.
  - `scoped_names(schema, names) -> List[str]` — Les réglages de la ⚙ d'UN process : `names` (ce qu'il surveille), plus le champ qui COMMANDE
  - `applicable_defaults(schema, values=None) -> dict` — Défauts APPLICABLES d'un schéma pour un élément NAISSANT : params de contexte 'item'
  - `panel_dom_id(p)` — dom_id du param sur la surface VOLET, ou None s'il n'y figure pas.
  - `panel_name_key(p)` — Clé de stockage = le NOM du param, s'il figure au volet (None sinon). L'autre règle que
  - `remembered(p) -> bool` — Le réglage se retient-il (préférence de l'utilisateur) ? Sa déclaration `remember`, sinon
  - `domain_key(domain: str)` — LA règle de clé de stockage (2026-10-21, « une seule règle pour tous ») : `<domaine>.<nom>`
  - `panel_defaults(params, key=None) -> dict` — {clé de stockage: défaut} des params du volet.
  - `panel_values_by_name(stored, params, key=None) -> dict` — Ré-indexe les réglages STOCKÉS vers ce que `WamaParams.render` attend (le `name` du
  - `panel_prefs_from_post(post, params, key=None) -> dict` — Chemin INVERSE de `panel_values_by_name` : les valeurs postées par NOM, re-clées pour le
  - `effective_settings(schema, posees=None, preset=None, contexte=None) -> dict` — Valeurs EFFECTIVES d'un élément — **défauts (schéma) ← preset ← réglages POSÉS**.
  - `coerce_params(schema, data, caps=None)` — Borne UNIQUE des paramètres numériques = le SCHÉMA (`params.py`). Source de vérité serveur.
  - `schema_for_app(app_id: str) -> List[dict]` — Schéma de params d'une app, résolu depuis le REGISTRE (`wama/<app>/params.py`).
  - `groups_for_app(app_id: str) -> List[dict]` — Groupes d'affichage (`ParamGroup`) du schéma PRINCIPAL d'une app — le pendant de
  - `declared_param_schemas(app_id: str)` — TOUS les schémas de params déclarés par le module de l'app — pas seulement l'attribut
  - `schema_model_kwargs(app_id: str, params: dict) -> dict` — Sous-ensemble de `params` qui est À LA FOIS déclaré au schéma de l'app ET un champ
  - `schema_extra_params(app_id: str, params: dict) -> dict` — Symétrique de `schema_model_kwargs` : les params DÉCLARÉS au schéma qui ne sont PAS des
  - `schema_arg_names(app_id: str) -> set` — Noms de params qu'une app DÉCLARE — surface d'arguments acceptable d'un outil `**params`.
  - `choice_values(p) -> List[str]` — Valeurs VALIDES d'un select/radio : ses `choices` statiques. UNE fonction pour la porte
  - `catalog_options(p) -> List[Tuple[str, str]]` — [(valeur, libellé)] d'un select tiré du CATALOGUE (`options_source='catalog'`), lus sur le
  - `invalid_choice_values(schema, data) -> dict` — {nom: (valeurs_refusées, choices_valides_triés)} pour chaque valeur PRÉSENTE hors
  - `unapplicable_numeric_values(schema, data) -> dict` — {nom: (valeur_refusée, explication)} pour chaque nombre PRÉSENT que le schéma ne peut
  - `schema_choice_values(app_id, name) -> set` — Valeurs valides d'un param à `choices`, DÉRIVÉES du schéma — jamais recopiées.
  - `coerce_schema_values(schema, data, only_present: bool=True) -> dict` — Coercition COMPLÈTE d'un mapping selon le schéma : types (booléens) + bornes (numériques).
  - `schema_refusals(schema, data) -> dict` — {nom: raison} de chaque valeur PRÉSENTE que le schéma refuse. Vide = tout est applicable.
  - `describe_refusals(refusals: dict) -> str` — Une phrase par valeur refusée, dans l'ordre des noms — le texte d'une erreur montrée.
  - `checked_values(schema, data) -> dict` — Les valeurs FOURNIES, refusées si le schéma les refuse, sinon typées et bornées — la porte
  - `param_from_spec(spec) -> Param` — Le `Param` d'un `ParamSpec`. Lève `ValueError` sur un type que le pont ne connaît pas —

### Shuttle J/K/L

État de vitesse/direction de lecture (paliers éditeur) + binding clavier ; l'app fournit apply(speed) — la commande est commune ; depuis le 2026-10-15 elle peut s'appliquer à l'AXE commun (`axis.shuttle`) plutôt qu'à un lecteur

- **Domicile** : `wama/common/static/common/js/wama-shuttle.js`

### Signalement au gestionnaire de fichiers

Noms d'événements centralisés (media:uploaded/processed/deleted) — l'arborescence du filemanager se rafraîchit sans que chaque app invente son event. Et `WamaFM.upload` (2026-10-18) : le DÉPÔT dans l'espace de l'utilisateur, geste partagé avec Discord et l'API (`enregistrer_fichier_utilisateur`) — le glisser-déposer sur le chat de l'assistant et la zone « Mes Fichiers » de l'accueil

- **Domicile** : `wama/common/static/common/js/wama-fm-notify.js`

### Socle JS d'application

La couche JS commune d'une page d'app — `_app_scripts.html` : formulaires du schéma (wama-params), ETA, lots, card d'entrée, voie d'import, barre de file ; options déclarées (appariement entrée ↔ modèle, capacités, modes, chips de prompt). Ce que `base.html` charge déjà n'y est PAS (une double exécution = deux écouteurs : le player audio muet du 18/08). Adopté par les 10 apps le 2026-10-03 (chaque gabarit recopiait ses balises ; l'anonymizer avait oublié la barre de file, sept scripts globaux étaient rechargés). Critère `app_scripts_common` ; garde `tests_item_lifecycle_contract` (socle présent, aucun script chargé deux fois sauf les idempotents déclarés)

- **Domicile** : `wama/common/templates/common/_app_scripts.html` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)

### Socle JS des apps

Plomberie commune file/cards : csrfFetch, urls et `Poller` — LA boucle d'interrogation du navigateur : jamais deux requêtes en vol, muette en onglet caché (2026-10-13 ; toute boucle des apps passe par lui, garde `tests_poller_js`) ; `loadScript` / `loadStyle` — LE chargement à la demande d'un module ou d'une feuille (2026-10-28 : trois copies privées réunies, garde `tests_script_loader`)

- **Domicile** : `wama/common/static/common/js/wama-app-base.js` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)

### Suivre la tête de lecture (traitement au fil de la lecture)

Le navigateur pose un curseur, une tâche longue le suit tranche par tranche, modèle gardé chargé, et s'arrête d'elle-même (arrêt demandé, 90 s d'inactivité, traitement prioritaire à laisser passer). Verrou de lancement, verrou vivant, refroidissement : chacun a son cas vécu. L'app fournit le chargement, la tranche et la question « dois-je céder ? » — jamais la mécanique. Extrait du mode Live du cam_analyzer quand le transcriber en est devenu le 2ᵉ utilisateur ; première forme du curseur de session

- **Domicile** : `wama/common/services/playhead_follow.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §5](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : Suivre la tête de lecture — la boucle « au fil de la lecture » COMMUNE.
- **API publique** (3) :
  - `class Channel` — Un canal de suivi : un préfixe par app, un identifiant par objet suivi.
  - `post_cursor(channel: Channel, cursor: Optional[dict], spawn: Callable[[], None]) -> dict` — Pose le curseur envoyé par le navigateur, et lance la boucle si aucune ne tourne.
  - `follow(channel: Channel, owner: str, step: Callable[[dict], bool], *, on_start: Optional[Callable[[], None]]=None, should_yield: Optional[Callable[[], bool]]=N…` — La boucle : suit le curseur du canal jusqu'à ce qu'une raison de s'arrêter survienne.

### Sélecteur de médiathèque

Modale commune de choix d'un asset de la médiathèque (filtrée par type), rendue à l'appelant sous forme de File + méta (`onSelect`), ou de l'asset SEUL, sans téléchargement, pour qui le DÉSIGNE (`onPick`, 2026-09-28 — la tuile de card)

- **Domicile** : `wama/common/static/common/js/media-picker.js`

### Thèmes et tokens de couleur

Les thèmes DÉCLARÉS (`THEMES` : clé, libellé, mode natif de Bootstrap), passés à toute page par le contexte et posés par base.html sur `<html>` (`data-wama-theme`, `data-bs-theme`) ; leurs VALEURS dans `wama-theme.css`, un bloc par thème, chargé avant toute feuille. Un composant lit un token (`var(--wama-text-label)`), il n'écrit plus de couleur : la card commune est le 1ᵉʳ adopteur (2026-10-17). `common.contrast` joue chaque thème déclaré ; `tests_theme` exige que chaque thème définisse chaque token et tient le BUDGET des couleurs écrites en dur, qui ne peut que descendre. Le CLAIR (2026-10-18) est le miroir de luminance du sombre (`theme_mirror.mirror`, contrastes conservés), sauf les fixes et surfaces que `themes.py` déclare ; une région fixe son thème par `data-wama-theme` (îlot). Un thème DÉRIVÉ (`Theme.base`, 2026-10-19 : Université Gustave Eiffel, La Suite numérique) reçoit toutes les valeurs de sa base par la liste de sélecteurs de son bloc et ne redéfinit que son identité, chaque couleur venant de sa charte (`CHARTERS`) ; La Suite se décline aussi en sombre, dérivé du sombre. Un thème peut porter le logo de sa charte (`Theme.logo`, UGE) : la barre du haut les pose tous, la feuille ne montre que celui du thème actif ; une police sous licence commerciale est NOMMÉE, jamais servie (`LICENSED_FONTS`, TT Norms) ; une police libre est SERVIE, vendorisée par `update_vendors.sh` et déclarée par sa charte (`CHARTERS[…]['font']`, Roboto Flex pour La Suite, 2026-10-20). Le compte CHOISIT au Profil (2026-10-19) un thème déclaré — le SOMBRE par défaut — ou « Automatique », qui suit le mode du système (`wama-theme.js`, résolu avant le premier rendu) ; `theme_choice`, réglage durable `user_settings`. Un thème PERSONNALISÉ (2026-10-20, `Theme.generated` : clair ou sombre) naît d'une couleur d'accent cliquée au Profil (`PALETTES`, ou le sélecteur) : `theme_generator` en GÉNÈRE le bloc d'identité, chaque texte ajusté à 4,5:1 sur les fonds de sa base, posé par base.html dans `#wama-theme-generated`. Un thème de CHARTE (même jour) naît d'un PDF lu au Profil (`theme_charter` : les règles relèvent les couleurs écrites, le LLM local choisit parmi elles la principale, le nom, la police ; un humain valide) ; ses graines vivent sur une ligne `UserTheme` qui a une provenance — privée, partagée par `sharing.partager`, système une fois promue par un admin

- **Domicile** : `wama/common/themes.py` · **doc** : [docs/construction/suivi/ROADMAP.md §28](../construction/suivi/ROADMAP.md)
- **Module** : Thèmes de WAMA — LA déclaration (chantier ouvert le 2026-10-17, demande de Fabien : « ça fonctionnera aussi quand on aura mis en place plusieurs thèmes/modes (sombre/clair/UGE/etc) »).
- **API publique** (17) :
  - `class Theme`
  - `font_stylesheets() -> list[str]` — Les feuilles des polices que WAMA SERT (`CHARTERS[…]['font']['stylesheet']`), une fois
  - `theme(key: str) -> Theme` — Le thème déclaré sous `key`, sinon le thème par défaut (jamais une page sans thème).
  - `choices() -> list[tuple[str, str]]` — Ce que propose le Profil : « Automatique », puis chaque thème déclaré.
  - `theme_choice(user) -> str` — Le choix du compte : une clé de thème, ou `AUTO`. `DEFAULT_CHOICE` sans compte, sans
  - `save_theme_choice(user, value, accent=None) -> str` — Enregistre le choix du compte, et la couleur d'accent si elle est donnée ; `ValueError`
  - `theme_accent(user) -> str` — La couleur d'accent du thème personnalisé du compte ; `DEFAULT_ACCENT` sans compte, sans
  - `generated_css(choice: str, accent: str) -> str` — La règle que `base.html` pose pour un choix de thème GÉNÉRÉ ; '' pour tout autre choix.
  - `charter_themes(user)` — Les thèmes de charte que `user` voit — le filtre des catalogues (l'administrateur voit tout,
  - `theme_charter(user)` — Le thème de charte choisi par le compte, s'il le voit encore ; None sinon. Fail-safe.
  - `profile_choice(user) -> str` — Ce que le Profil montre choisi : `charter:<pk>` sous un thème de charte, sinon le choix.
  - `account_generated_css(user, choice: str) -> str` — Le bloc GÉNÉRÉ que `base.html` pose pour le compte : les graines de sa charte s'il en a
  - `charter_choices(user) -> list[dict]` — Les thèmes de charte que le Profil propose, avec leur provenance comme partout dans WAMA
  - `palette_previews() -> list[dict]` — Ce que montre le Profil pour chaque couleur proposée : la graine, et l'accent qu'elle
  - `resolve(choice: str) -> Theme` — Le thème que le SERVEUR pose pour un choix. « Automatique » rend le défaut : le script de
  - `declared_for_pages(choice: str) -> dict` — Ce que lit `wama-theme.js` : le choix, le mode de Bootstrap de chaque thème, et le thème que
  - `theme_for(request) -> Theme` — Le thème que le serveur pose pour une requête (le choix du compte connecté).

### Vocabulaire des capacités

Canonicalise capabilities (tâche, modalités, entrées) — source du filtrage UI ; `category` (vocabulaire fermé `CATEGORY_LABELS`) range un select de modèle en optgroups (`options_group="category"`, 2026-09-29) ; bornes de TAILLE (`native_resolution`/`min_resolution`/`max_resolution`, `resolution_bounds`) pour l'image comme la vidéo — les tailles proposées en dérivent (2026-09-30) ; la TEMPÉRATURE d'un modèle qui tire, quel que soit son type (2026-10-21) : `params` ∋ `temperature`, `recommended_temperature` (Ollama : son fichier de modèle), `max_temperature` ; la graine et le top_p (2026-10-22) : `params` ∋ `seed` / `top_p`, `recommended_top_p`, déclarés par le moteur (`reads_seed`, `default_top_p`)

- **Domicile** : `wama/common/utils/model_capabilities.py` · **doc** : [docs/construction/ui/INPUT_MODEL_MATCHING.md](../construction/ui/INPUT_MODEL_MATCHING.md)
- **Module** : Vocabulaire CANONIQUE des capacités modèle (`AIModel.capabilities`) — SOURCE UNIQUE.
- **API publique** (20) :
  - `reads_temperature(caps: Dict[str, Any]) -> bool` — La fiche dit-elle que le modèle LIT la température ? (son nom dans `params`).
  - `ollama_parameter(parameters: str, name: str)` — Un réglage numérique du fichier de modèle d'Ollama (`/api/show` → `parameters`, une ligne
  - `ollama_recommended_temperature(parameters: str)` — La température du fichier de modèle d'Ollama, ou None. MESURÉ le 2026-10-21 : gemma4 et
  - `sampling_caps_from_declaration(config: Dict[str, Any]) -> Dict[str, Any]` — `recommended_steps` / `recommended_guidance` depuis `default_steps` /
  - `duration_caps_from_declaration(config: Dict[str, Any]) -> Dict[str, Any]` — `max_duration_s` depuis le `max_duration` (secondes) d'une déclaration d'app — les modèles
  - `video_caps_from_declaration(config: Dict[str, Any], tokens=()) -> Dict[str, Any]` — Les capacités VIDÉO tirées d'une déclaration d'app (`fps`, `max_frames`, `resolution`
  - `resolution_caps_from_declaration(config: Dict[str, Any]) -> Dict[str, Any]` — `native_resolution` / `min_resolution` / `max_resolution` tirés d'une déclaration (image
  - `resolution_bounds(caps: Dict[str, Any]) -> Dict[str, Any]` — Les bornes de taille d'un modèle, lues UNE fois : `{native: (L, H) | None, min, max,
  - `video_limits(caps: Dict[str, Any]) -> Dict[str, Any]` — Les limites vidéo d'un modèle, lues UNE fois : `{fps, max_frames, max_duration_s,
  - `get_languages(caps: Dict[str, Any]) -> List[str]` — Langues gérées, ou [] si non déclaré (le repli par type est géré par lang_routing).
  - `is_multilingual(caps: Dict[str, Any]) -> bool` — Vrai si le modèle gère >1 langue ou est agnostique ('*'). Remplace l'ex-clé `multilingual`.
  - `languages_count(caps: Dict[str, Any]) -> int` — Nombre de langues déclarées (0 si inconnu). Remplace l'ex-clé `languages_count`.
  - `supports(caps: Dict[str, Any], flag: str) -> bool` — Lecture booléenne tolérante d'un `supports_*` (ex. supports('supports_cloning')).
  - `supports_timestamps_for(caps: Dict[str, Any], lang: str) -> bool` — Horodatage mot disponible POUR CETTE LANGUE.
  - `declared_engine_flag(cls, flag: str)` — Valeur d'un `supports_*` telle que la classe de moteur la DÉCLARE — ou `None`.
  - `declared_engine_value(cls, name: str)` — `(déclaré, valeur)` d'un attribut que la classe de moteur écrit dans son PROPRE corps (ou
  - `apply_engine_flags(caps: Dict[str, Any], cls) -> Dict[str, Any]` — Réaligne `caps` sur ce que la classe de moteur DÉCLARE — rend un NOUVEAU dict.
  - `normalize_capabilities(raw: Dict[str, Any]) -> Dict[str, Any]` — Convertit un dict `capabilities` produit avec des clés legacy vers le vocabulaire canonique.
  - `is_canonical_key(key: str) -> bool` — Vrai si `key` fait partie du vocabulaire canonique (utilitaire d'audit/tests).
  - `derive_inputs_from_tasks(tasks: str, is_video: bool=False) -> Dict[str, Any]` — `tasks` (raccourci d'app) → vocabulaire CANONIQUE : task + entrées consommées.

### Voie d'import (front)

Envoi d'un fichier vers l'endpoint upload de l'app (dépôt, clic), délégation du LOT à batch_import, consolidation et rafraîchissement — agnostique du monde (ni MIME ni extension). ⭐ Depuis le 2026-09-28 elle DÉSIGNE aussi (`handleDesignations` : médiathèque, arbre — `<champ>__designated`, pointé par le serveur) et se retrouve par l'id de sa zone ou de son input (`forElement`)

- **Domicile** : `wama/common/static/common/js/wama-import.js` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)

### WAMA au doigt (écrans tactiles)

Une règle commune, montée par base.html EN DERNIER, pour tout écran dont le pointeur principal est un doigt — critère UNIQUE `(pointer: coarse)` : commandes à 44 px au moins (boutons, onglets, menus, titres repliables, `[role=button]`), cases, interrupteurs et curseurs à 24 px au moins — des PLANCHERS, jamais des tailles. Et la convention « révélé au survol » : `.wama-reveal-host` sur l'hôte, `.wama-reveal` sur l'action — montrée au survol, au clavier, et TOUJOURS au doigt ; son inverse `.wama-reveal-hide` pour ce qui lui cède la place. Une règle `:hover` locale qui révélerait un élément est refusée par `tests_touch`. Les briques affinent chez elles, sur le même critère (process des cards v3, lecteur audio, saisie de l'assistant, ports du studio, variante « large » de l'explorateur)

- **Domicile** : `wama/common/static/common/css/wama-touch.css` · **doc** : [docs/construction/architecture/WAMA_APP_CONVENTIONS.md](../construction/architecture/WAMA_APP_CONVENTIONS.md)

## Données & infrastructure

### Abonnement aux éléments de catalogue

PRÉFÉRENCE d'affichage, appliquée APRÈS le droit et seulement à l'affichage : elle ne peut que RESTREINDRE ce à quoi l'utilisateur a déjà accès. Seules les EXCEPTIONS sont stockées (se réabonner efface la ligne) ; une nature d'élément s'ajoute par une entrée dans KINDS, et la page de catalogue hérite du mécanisme par deux attributs (`data-abo`, `data-abo-toggle`). Son PÉRIMÈTRE est celui du DROIT, pas d'APP_CATALOG : les surfaces transversales et Lab (`register_surface`) se masquent par la même clé `gate` que celle dont accessible() décide (§8.8.1)

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

Décide seul qui voit quel élément, sur DEUX axes qui se cumulent : le TIER du compte (anonymous < utilisateur < developpeur < admin, tranche en premier) et les RÔLES métier (groupes `role:*`, intersection avec la politique de l'app). Le compte de service `anonymous` y est FERMÉ par code, pas par état de base. Signature GÉNÉRALE depuis S2 — accessible(user, kind, element_id) : chaque FAMILLE d'élément déclare dans KIND_DECISION qui décide pour elle, un kind inconnu LÈVE, et une décision unique ne garde que ce que ses POINTS D'APPLICATION lisent réellement (§8.9). Un outil gardé est une PAGE (card ou `register_surface`) ou, depuis le 2026-10-13, un OUTIL SANS PAGE (`register_pageless_tool` : gestionnaire de fichiers, assistant — routes résolues comme celles de toute app, l'assistant gardé aussi dans `conversation_turn`). `access_cases()` énumère tous les cas pour la présentation ; depuis le 2026-10-20, la CONSTELLATION des utilisateurs (`accounts/constellation.py`) montre ces décisions compte par compte, avec unités, projets, partages, apports et activité — page admin, intégrée à la présentation, jouée chaque nuit (`accounts.constellation.ui`) ; les deux vues montrent les mêmes outils (`presented_apps`)

- **Domicile** : `wama/accounts/permissions.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Modèle d'accès WAMA à DEUX AXES (voir PROFILES_PERMISSIONS.md) : - PROFIL DE COMPTE (tier, unique, hiérarchique) : anonymous < utilisateur < developpeur < admin. - RÔLES MÉTIER (cumulatifs, = Django Groups préfixés 'role:') : communication / recherche / …
- **API publique** (21) :
  - `is_guest_account(user) -> bool` — Ce compte est-il un compte de SERVICE pour visiteur non connecté — le compte `anonymous`
  - `account_kind(user) -> str` — 'test' pour un compte de test (préfixe `wama_`) ou le compte système anonyme, 'person'
  - `app_group(app_id)`
  - `app_id_for_path(path)` — app_id gardé correspondant à un chemin de requête, ou None.
  - `refused_app(user, path, allowed_apps=None)` — L'app gardée que `path` désigne et que `user` (connecté) n'a PAS le droit d'ouvrir, sinon
  - `can_open_page(user, access, path, allowed_apps=None) -> bool` — `user` peut-il ouvrir la page servie à `path` ? La MÊME décision que la requête réelle,
  - `tool_accessible(user, tool_name)` — Un user peut-il exécuter cet outil `tool_api` ? MÊME décision que `accessible()` : la
  - `can_manage_registries(user)` — GÉRER un registre — l'actualiser, et pour le registre des modèles : installer, supprimer,
  - `is_developer(user)` — Développeur ou administrateur — DOMICILE UNIQUE du prédicat (2026-09-15).
  - `all_gated_apps()` — Ensemble des app_ids soumis au contrôle d'accès (pour calculer accessible_apps).
  - `tier_rank(tier)`
  - `user_tier(user)`
  - `is_admin_tier(user)` — Le compte est-il ADMINISTRATEUR ? Le NIVEAU du profil, superutilisateur compris.
  - `administrators() -> list` — Les comptes ACTIFS administrateurs, ceux qu'on prévient d'une demande à trancher.
  - `set_account_tier(user, tier: str)` — Le SEUL écrivain du niveau d'un compte, drapeaux Django compris ; rend le niveau posé.
  - `user_roles(user)` — Ensemble des clés de rôles métier d'un user (depuis ses Groups 'role:*').
  - `accessible(user, kind, element_id)` — Un user peut-il accéder à cet élément ? Point UNIQUE de décision (nav, vues, studio, outils).
  - `accessible_apps(user, app_ids)` — Sous-ensemble d'app_ids accessibles à user (préserve l'ordre).
  - `presented_apps()` — Les outils que MONTRENT les vues des droits (scène de la présentation, constellation des
  - `access_cases()` — Tous les cas du modèle d'accès : chaque tier × chaque combinaison de rôles × chaque app.
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
- **API publique** (7) :
  - `visible_or_404(model, user, **kwargs)` — Objet que `user` a le droit de VOIR : le sien, ou partagé avec lui (unité/projet/public, ou
  - `listable_by(queryset, user)` — Ce que `user` a le droit de LISTER : `visible_to`, sauf pour un compte de visiteur (le
  - `can_view(instance, user, owner_field: str='user') -> bool` — `user` peut-il VOIR cet objet DÉJÀ CHARGÉ ? Son propriétaire, le staff, ou quiconque peut le
  - `owned_or_404(model, user, **kwargs)` — Objet que `user` a le droit de MODIFIER — aujourd'hui : le sien, point.
  - `editable_or_404(model, user, *, trace: str='', **kwargs)` — Objet que `user` peut ÉDITER : le sien, ou un élément sur lequel il COLLABORE.
  - `can_edit(user, obj) -> bool` — Même règle qu'`editable_or_404`, pour un objet déjà en main (cards, gabarits, tâches).
  - `duplicable_or_404(model, user, **kwargs)` — Objet que `user` peut DUPLIQUER : tout ce qu'il peut voir (le sien, ou partagé avec lui).

### Activité vocale (le VAD garde-t-il la parole ?)

Confronte, sur quelques fenêtres du média, ce que le filtre de parole Silero retient à ce que l'énergie du signal dit actif : un VAD qui garde bien moins que l'actif rejette une parole lointaine. L'appelant décide (le transcriber transcrit alors sans filtre, réglage `vad_mode` auto) ; mesuré sur deux entretiens le 2026-09-25. `pause_windows` (2026-10-02) : fenêtres bornées couvrant TOUT l'audio, coupées au creux d'énergie — pour un moteur à fenêtre fixe sans repères de temps (FrWhisper) ; `quietest_point` : la même coupe sur un extrait seul, qu'emploie le découpage des audios longs du transcriber (`workers._split_audio_chunks`, plus de coupe à intervalle fixe). `speech_coverage` (2026-10-22) : la part de la parole que les segments rendus couvrent — un texte perdu se voit, quel que soit le moteur

- **Domicile** : `wama/common/utils/speech_activity.py` · **doc** : [wama/transcriber/TRANSCRIBER_CORRECTION.md §8](../../wama/transcriber/TRANSCRIBER_CORRECTION.md)
- **Module** : Activité vocale d'un enregistrement — le filtre de parole (VAD) garde-t-il ce que le signal porte ?
- **API publique** (8) :
  - `windows_for(duration_s: float) -> int` — Nombre de fenêtres sondées pour un média de `duration_s` secondes.
  - `active_frames(wave, sr: int, margin_db: float=ACTIVE_MARGIN_DB)` — Les trames de 100 ms ACTIVES (niveau au-dessus du plancher de bruit, 10ᵉ centile, de
  - `energy_active_ratio(wave, sr: int, margin_db: float=ACTIVE_MARGIN_DB) -> float` — Part des trames de 100 ms dont le niveau dépasse le plancher de bruit de `margin_db`.
  - `pause_windows(wave, sr: int, max_seconds: float, search_seconds: float=PAUSE_SEARCH_SECONDS) -> list` — `[(début, fin)]` en secondes, fenêtres CONTIGUËS couvrant TOUT l'audio, chacune ≤
  - `quietest_point(span, sr: int)` — Secondes, depuis le début de `span`, du MILIEU de sa trame de 100 ms la plus calme — là où
  - `vad_speech_ratio(wave, sr: int) -> float` — Part de l'audio que le VAD de faster-whisper retient, avec ses réglages par défaut.
  - `speech_coverage(path, spans, duration_s: float=0.0, windows: int=None, window_s: float=120.0, decode=None) -> dict` — La part de la PAROLE (trames actives à l'énergie) que couvrent les `spans` — `[(début,
  - `vad_rejects_speech(path, duration_s: float=0.0, windows: int=None, window_s: float=120.0, decode=None) -> dict` — Sonde `windows` fenêtres de `window_s` réparties dans le média (par défaut

### Actualisation des catalogues

REGISTRE des registres : une page catalogue déclare la CLÉ de son registre et hérite du bouton, de l'endpoint, de la permission et du compte-rendu. La NATURE déclarée (scan / mesure / re-déclaration / DÉRIVÉ) décide du rendu — un dérivé affiche « toujours à jour » au lieu d'un bouton qui ne ferait rien — ET le LIEU d'exécution : état partagé → tâche Celery non bloquante, registre en mémoire → sur place, avec propagation aux autres workers gunicorn. Depuis le 2026-10-13 : LIRE les registres (pages, model manager compris) relève du droit d'accès `registries`, tout compte sauf le visiteur ; les GÉRER — actualiser, et pour les modèles installer, supprimer, prospecter, libérer la carte — d'UNE règle, `can_manage_registries` (profil développeur ou administrateur)

- **Domicile** : `wama/common/registries.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Registre des REGISTRES — l'actualisation devient un mécanisme, pas une page.
- **API publique** (17) :
  - `class RefreshResult` — Compte-rendu UNIFORME d'une actualisation, quelle que soit sa nature.
  - `class Registry` — Ce qu'une page catalogue déclare pour hériter de l'actualisation.
  - `execution_of(r: Registry) -> str`
  - `register(r: Registry) -> Registry`
  - `get(key: str) -> Registry`
  - `carried_rows(element_id, *, access_kind: str='', manifest_kind: str='')` — Les lignes qui portent la provenance de l'élément `element_id` — `owner_model` filtré par
  - `declaring_app(element_id, *, access_kind: str) -> str` — L'app qui déclare l'élément du CODE `element_id`, lue par le registre de sa famille
  - `declared_in_code(element_id, *, access_kind: str) -> bool` — La clé `element_id` désigne-t-elle aussi un élément du CODE (`Registry.in_code`) ?
  - `is_authorized(r: Registry, user) -> bool` — Ce compte peut-il ACTUALISER ce registre ? Le lire relève de l'accès à l'outil « Registres »
  - `refusal(r: Registry) -> str` — Le motif d'un refus d'actualisation, lisible tel quel (les vues y lisent « réservé »).
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
- **API publique** (7) :
  - `class Feature`
  - `read_by(registry, config, process)` — État {clé: bool} des bascules que le process `process` lit — sa photo au lancement.
  - `with_legacy(registry, process, photo)` — Photo {clé: bool} d'un calcul de `process`, complétée de l'état `legacy` de chaque bascule
  - `resolve(registry, config)` — État effectif {key: bool} : défauts du registre surchargés par config['features'].
  - `is_enabled(registry, config, key)` — État effectif d'UNE bascule (KeyError si la clé n'est pas au registre).
  - `describe(registry, config=None)` — Catalogue sérialisable pour l'UI : métadonnées + état effectif de chaque bascule.
  - `sanitize_overrides(registry, raw)` — Filtre un dict de surcharges venu du client : clés connues, valeurs booléennes.

### Cache-busting statique

`{% static_v %}` = `{% static %}` + `?v=<mtime>` : le navigateur re-télécharge un fichier statique dès qu'il change, le garde en cache sinon

- **Domicile** : `wama/common/templatetags/wama_static.py`
- **Module** : Cache-busting statique centralisé pour WAMA.
- **API publique** (1) :
  - `static_v(path)` — URL statique + `?v=<mtime>` pour casser le cache navigateur au changement.

### Chemins média

Emplacements canoniques des entrées/sorties par app et par utilisateur (`app_media_dir` : `users/<uid>/<app>/input|output`). ⭐ Depuis le 2026-09-23 la brique décide aussi POINTER ou COPIER (`reference_or_copy`, décision de Fabien, cible annoncée le 12/09) : une source déjà sous `users/<uid>/` du MÊME utilisateur est désignée telle quelle — un `FileField` est déjà un pointeur, l'aperçu commun sert `/media/<chemin stocké>` — tandis qu'un dépôt depuis le poste, un dossier connecté (hors `MEDIA_ROOT`, et un traitement ne lit pas un disque réseau), une URL ou l'arbre d'AUTRUI se copient. ⚠ Une app qui lit ses entrées PAR DOSSIER (cam_analyzer, RTMaps) garde la copie, et son site le dit. ⭐ Depuis le 2026-09-28 : un asset SYSTÈME actif se pointe aussi, `readable_by` est LA règle de ce qu'un utilisateur peut désigner, et `received_inputs` est ce qu'une vue d'upload REÇOIT — un fichier téléversé ou DÉSIGNÉ (`<champ>__designated` : médiathèque, arbre), par la même vue, avec l'état du volet ; `designate` est la même désignation pour les outils de l'assistant (`tool_api.add_to_*`). ⭐ Depuis le 2026-09-29 : un asset de médiathèque PARTAGÉ (labo, projet, public) est désignable et POINTÉ par les personnes concernées — même règle de visibilité que la liste (`scoping.listable_by`), le compte anonyme n'en hérite pas. Depuis le 2026-10-20 : `check_designation`, les gardes de `designate` sans pointer ni copier — pour qui RETIENT une désignation avant qu'une app la reçoive (card d'entrée du Studio) ; depuis le 2026-10-22, `designated_file`, le fichier DISQUE de la désignation (dossier connecté compris) pour qui la LIT sans la recevoir (lot, « Jeu de données » et Sortie du Studio : `MEDIA_ROOT/<chemin>` manquait un montage)

- **Domicile** : `wama/common/utils/media_paths.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : WAMA Common - Media Path Utilities
- **API publique** (27) :
  - `get_app_media_path(app_name: str, user_id: Union[int, str], subfolder: str='input') -> Path` — Get the absolute path for an app's user-specific media folder.
  - `class OutsideMediaRoot(ValueError)` — Le chemin demandé sort de MEDIA_ROOT (traversée `..`, dossier frère, absolu étranger).
  - `resolve_under_media_root(candidate, *, must_exist: bool=True)` — Résout un chemin — absolu, ou RELATIF à MEDIA_ROOT — et GARANTIT qu'il y reste.
  - `get_app_media_url(app_name: str, user_id: Union[int, str], subfolder: str='input') -> str` — Get the URL path for an app's user-specific media folder.
  - `ensure_app_media_dirs(app_name: str, user_id: Union[int, str]) -> dict` — Ensure input and output directories exist for an app/user.
  - `get_unique_filename(folder: Union[str, Path], filename: str) -> str` — Generate a unique filename in a folder.
  - `app_media_dir(app_name: str, user_id: Union[int, str], subfolder: str='input') -> str` — Dossier média d'une app, RELATIF à `MEDIA_ROOT` — la FORME du chemin, en un seul endroit.
  - `get_relative_media_path(app_name: str, user_id: Union[int, str], subfolder: str, filename: str) -> str` — Get the relative path for storing in Django FileField.
  - `copy_into_app_input(source_path, app_name: str, user_id, subfolder: str='input', allowed_exts=None, *, for_instance=None, field=None, provenance_kind='temp', p…` — Copy a source file into an app's media folder with collision-safe naming.
  - `in_user_home(rel_path, user_id) -> bool` — Ce chemin (relatif à `MEDIA_ROOT`) est-il DANS l'arbre de CET utilisateur ?
  - `reference_or_copy(source_path, app_name: str, user_id, subfolder: str='input', allowed_exts=None, *, for_instance=None, field=None, provenance_kind=None, prove…` — POINTER le fichier s'il est déjà dans l'arbre de l'utilisateur, le COPIER sinon.
  - `is_system_asset_file(rel_path) -> bool` — Ce chemin est-il le fichier d'un asset SYSTÈME actif de la médiathèque ?
  - `readable_by(rel_path, user) -> bool` — Cet utilisateur peut-il DÉSIGNER ce fichier comme entrée d'une card ?
  - `designation_field(field: str) -> str` — Le champ POST qui porte la désignation du champ fichier `field`.
  - `class ReceivedInput` — UN fichier reçu par une vue d'upload : téléversé, ou DÉSIGNÉ.
  - `class ReceivedInputs(list)` — Les entrées reçues, plus `refusal` : le motif du premier refus (désignation illisible,
  - `class InputRefused(ValueError)` — Une désignation refusée : hors `MEDIA_ROOT`, absente, ou illisible pour cet utilisateur.
  - `designate(path, user, app_name: str, subfolder: str='input') -> ReceivedInput` — UN fichier DÉSIGNÉ par son chemin (relatif à `MEDIA_ROOT`, ou absolu dessous), reçu pour
  - `check_designation(path, user) -> str` — Le chemin désigné, s'il passe les gardes de `designate` — sans rien pointer ni copier.
  - `designated_file(path, user) -> str` — Le fichier DISQUE d'une désignation qui passe les gardes de `designate` — sans rien pointer
  - `received_inputs(request, user, app_name: str, field: str='file', subfolder: str='input') -> ReceivedInputs` — Ce qu'une vue d'upload reçoit : les fichiers TÉLÉVERSÉS sous `field`, puis les fichiers
  - `class UploadToUserPath` — Callable class for Django FileField upload_to that generates user-specific paths.
  - `system_asset_relpath(asset_type: str, filename: str) -> str` — Chemin relatif (sous `MEDIA_ROOT`) d'un asset système : un sous-dossier par NATURE.
  - `class UploadToSystemAssetPath` — `upload_to` de `SystemAsset.file` — `media_library/system/<asset_type>/<fichier>`.
  - `upload_to_user_input(app_name: str)` — Convenience function to create an UploadToUserPath for input folder.
  - `upload_to_user_output(app_name: str)` — Convenience function to create an UploadToUserPath for output folder.
  - `migrate_file_to_user_path(old_path: Union[str, Path], app_name: str, user_id: Union[int, str], subfolder: str='input', move: bool=True) -> Optional[str]` — Migrate a file from old location to new user-specific location.

### Copie de lecture des vidéos

Une vidéo qu'une card porte et que le navigateur ne lit pas (conteneur, profil H.264, pixels — pas le seul nom du codec) reçoit, DÈS SON IMPORT et quelle que soit la voie, une copie de lecture H.264 servie par l'aperçu SEULEMENT ; l'original reste intact pour les traitements (2026-10-06, décision de Fabien). Rangée dans le dossier CACHÉ de l'utilisateur (`users/<id>/.preview/`), jamais à côté de l'original ni dans un dossier connecté ; balayée quand l'original part ; ni orpheline pour l'intégrité, ni dédupliquée, ni sauvegardée. Récepteur générique sur les champs fichier, tâche `common.make_playback_copy` (CPU), rattrapage `manage.py playback_copies`. Le verdict lit la sonde COMMUNE (`media_probe.probe_video_format`) ; l'écriture partage le geste de `ensure_h264`

- **Domicile** : `wama/common/utils/video_compat.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Browser-compatibility helpers for video files.
- **API publique** (14) :
  - `get_video_codec(file_path: str, *, timeout: int=10) -> Optional[str]` — Return the codec name of the first video stream, lowercased
  - `is_browser_compatible_codec(codec: Optional[str]) -> bool` — True when the codec is one HTML5 ``<video>`` can play directly.
  - `ensure_h264(file_path: str, *, timeout: int=1800) -> Union[bool, str]` — Ensure a video is browser-compatible. When the codec is already in
  - `playability(info: Optional[dict]) -> tuple` — `(lisible, raison)` d'une vidéo décrite par la sonde COMMUNE (`media_probe.
  - `derived_rel(rel: str, suffix: str) -> str` — Le chemin (relatif à MEDIA_ROOT) d'un fichier DÉRIVÉ d'un média — pure. Sous
  - `playback_copy_rel(rel: str) -> str` — Le chemin de la copie de lecture d'un média (`derived_rel`, suffixe `.mp4`) — pure.
  - `playback_copy_for(rel: str) -> str` — La copie de lecture À JOUR d'un média (chemin relatif), ou '' — plus ancienne que
  - `make_playback_copy(rel: str, *, timeout: int=3600) -> str` — Crée la copie de lecture d'un média si le navigateur ne le lit pas — idempotent. Rend le
  - `drop_playback_copy(rel: str) -> bool` — Retire les fichiers DÉRIVÉS d'un média — sa copie de lecture et, depuis le 2026-10-21, ses
  - `original_of_copy(copy_rel: str) -> str` — L'original (chemin relatif) d'un fichier dérivé — l'inverse de `derived_rel`, pour chacun
  - `sweep_orphan_playback_copies(dry_run: bool=False) -> dict` — Retire les fichiers dérivés (copies de lecture, pics fins) dont l'original n'existe plus, ou
  - `schedule_playback_copy(rel: str) -> bool` — Met en file la copie de lecture d'un média vidéo, UNE fois par version du fichier (chemin,
  - `backfill_playback_copies(dry_run: bool=False) -> dict` — Le RATTRAPAGE : les vidéos que des cards portaient AVANT le récepteur (aucun import ne
  - `register_playback_copy_receivers()` — Branche le récepteur sur tout modèle à champ fichier (le recensement COMMUN,

### Décodage audio robuste

Décode l'audio là où torchcodec/torchaudio sont cassés (WSL) : soundfile + repli ffmpeg. `decode_audio` laisse un WAV à sa fréquence NATIVE ; un modèle de parole passe par `decode_audio_at` (fréquence GARANTIE, `resample`) — 2026-10-01, cinq consommateurs. Annexe torchaudio_compat = l'autre forme du même problème : shims soundfile posés DANS torchaudio pour les libs tierces qui l'appellent en interne (Coqui, DeepFilterNet)

- **Domicile** : `wama/common/utils/audio_decode.py`
- **Module** : Décodage audio robuste pour WAMA (WSL où torchcodec/torchaudio est cassé).
- **API publique** (7) :
  - `decode_audio(path, target_sr: int=16000, mono: bool=True)` — Décode un fichier audio en (ndarray float32, sample_rate), robuste aux formats
  - `resample(samples, rate: int, target_sr: int)` — Échantillons mono → float32 à `target_sr` (polyphase, scipy) ; inchangés s'ils y sont.
  - `decode_audio_at(path, target_sr: int=16000)` — (mono float32 à `target_sr` GARANTI, `target_sr`) — ce qu'attend un modèle de parole.
  - `transcode_to_wav(path, out_path, target_sr: int=16000)` — Réécrit un média en WAV PCM 16 bits mono à `target_sr`, via ffmpeg — rend `out_path`.
  - `probe_duration_seconds(path)` — Durée d'un média en secondes via ffprobe — SANS décoder (coût négligeable).
  - `decode_window(path, target_sr: int=16000, start_s: float=0.0, duration_s=None, mono: bool=True)` — Décode UNE FENÊTRE [start_s, start_s+duration_s] d'un média en (ndarray float32, sr),
  - `decode_for_pyannote(path, target_sr: int=16000)` — Décode en dict `{'waveform': (channels, time) torch.Tensor, 'sample_rate': int}`

### Dégradation contrôlée d'un enregistrement de parole

Profils DÉCLARÉS (bruit rose à un rapport signal/bruit donné, champ lointain : réverbération, atténuation) appliqués de façon déterministe à un corpus propre, pour évaluer les prétraitements sur une qualité CONNUE — à confronter à un corpus réel de qualité moyenne avant d'en faire un test d'évaluation

- **Domicile** : `wama/common/utils/audio_degradation.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : DÉGRADATION CONTRÔLÉE d'un enregistrement de parole — pour évaluer les prétraitements sur des audios de qualité MOYENNE dont on connaît exactement la dégradation (demande de Fabien, 2026-09-30, `WAMA_QUALITE §9bis`).
- **API publique** (5) :
  - `active_power(wave, sr: int, gate_db: float=8.0) -> float` — Puissance moyenne des trames de 20 ms au-dessus du plancher (15ᵉ centile + `gate_db`) —
  - `pink_noise(length: int, rng) -> np.ndarray` — Bruit rose (densité en 1/f) de puissance unitaire, par mise en forme spectrale.
  - `add_noise(wave, sr: int, snr_db: float, rng) -> np.ndarray` — Ajoute un bruit rose tel que parole active / bruit = `snr_db`.
  - `reverberate(wave, sr: int, rt60_s: float, rng) -> np.ndarray` — Réverbération synthétique : réponse impulsionnelle = trajet direct + queue de bruit à
  - `degrade(wave, sr: int, profile: str) -> np.ndarray` — Applique le profil déclaré `profile` : réverbération, puis bruit, puis atténuation ;

### Garde-fou des médias (processus)

Posé par `CommonConfig.ready()` dans TOUT processus Django (gunicorn, Celery, commandes, scripts `django.setup()`, tests) : `shutil.rmtree` refuse, par `PermissionError` que `ignore_errors` n'avale pas, d'effacer la racine des médias lue au démarrage, `users/`, `media_library/` ou un dossier qui les contient. Né de la perte TOTALE du 2026-10-27 (un `setUp` qui effaçait `settings.MEDIA_ROOT`, lancé hors du lanceur de tests). Et la CAUSE : un test de Django refuse de démarrer hors de `manage.py test` — sur les vrais médias, la vraie base, ou dans un processus dont le cache et le broker Celery sont les vrais (`runtime_side`). Les pendants AST, dans les tests d'hygiène, interdisent de passer `MEDIA_ROOT` à un `rmtree`, d'importer `rmtree` par son nom et de jouer une suite hors de `manage.py test`

- **Domicile** : `wama/common/utils/media_guard.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §10](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Garde-fou PROCESSUS : aucun `shutil.rmtree` ne peut effacer `media/` en bloc.
- **API publique** (3) :
  - `refusal(path, roots=None) -> str` — La raison de refuser d'effacer `path` en bloc, ou '' s'il peut l'être.
  - `test_refusal(test, media_root, database: str, test_process: bool=True) -> str` — La raison de refuser de JOUER `test` maintenant, ou '' : un test de Django (`SimpleTestCase`)
  - `install(media_root, database: str='') -> bool` — Protège `media_root` (et la base `database`) dans ce processus. Idempotent ; rend True si

### Grille des temps d'un audio

L'instant de chaque temps joué d'un audio et les hauteurs qui y sonnent (chroma par temps), en cache par fichier et date — de quoi caler une partition TEMPS PAR TEMPS sur ce qui est joué plutôt que par son tempo écrit (né le 2026-10-16 : #754 écrit à 88, joué à 89,1). Ne connaît aucune partition ; le calage est `WamaScore.align`

- **Domicile** : `wama/common/utils/audio_rhythm.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : La grille des TEMPS d'un audio — où tombe chaque temps joué, et quelles hauteurs y sonnent.
- **API publique** (2) :
  - `beat_grid(path: str)` — `{beats, chroma, duration}` de l'audio `path` (voir l'en-tête) ; None s'il est illisible.
  - `compute_beat_grid(path: str) -> dict`

### Identité de session du visiteur sans compte

Sur une app déclarée `public` (le converter, app d'essai), un visiteur non connecté agit sous un COMPTE TECHNIQUE propre à sa session (`wama_visitor_<jeton>`, tier `anonymous`, aucun rôle), créé à son premier geste par l'intergiciel d'accès et purgé avec ses éléments ET ses fichiers après sa durée de vie. Une identité, pas une étiquette : toute la logique de propriété existante (file, `users/<id>/`, portée) vaut pour lui sans retoucher une vue d'app. Bornes dans `settings` (taille, nombre d'éléments, identités neuves par adresse) ; routes qui font lire au serveur une adresse ou un chemin fermées ; aucun post-traitement GPU. Sur toute autre app, le visiteur VOIT et ne fait rien (403 de la même garde). `is_guest_account` = le prédicat unique « compte de visiteur » (partagé ou de session)

- **Domicile** : `wama/accounts/visitors.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Le VISITEUR sans compte, sur une app PUBLIQUE : une identité éphémère PAR SESSION.
- **API publique** (9) :
  - `max_upload_bytes() -> int`
  - `max_items() -> int`
  - `ttl() -> timedelta`
  - `new_identities_per_hour() -> int`
  - `is_visitor(user) -> bool` — Ce compte est-il l'identité éphémère d'un visiteur (pas le compte `anonymous` partagé) ?
  - `current(request)` — L'identité de visiteur que porte la session de cette requête, ou None.
  - `create(request)` — Crée l'identité du visiteur et l'attache à sa session.
  - `attach(request, app_id: str)` — Pose l'identité du visiteur sur la requête d'une app PUBLIQUE. Rend un refus, ou None.
  - `purge_expired(now=None, dry_run: bool=False) -> dict` — Détruit les identités de visiteur sans geste depuis `ttl()` : éléments (cascade) ET

### Identité et monde déclarés d'une app

Chaque app DÉCLARE son monde (media | data | lab | transverse) et son identité : dans son entrée d'APP_CATALOG, ou — hors catalogue — depuis son `ready()` (`register_app_world` ; `register_surface`, qui porte aussi l'identité de sa page ; `register_pageless_tool`, pour un outil gardé sans page). DEUX lectures, et seulement elles : `app_world()` (le manifeste d'app, le monde d'une fonction, le menu, `/apps/`, le journal, le calendrier) et `app_identity()` — libellé, couleur, icône complète, page, description, monde — pour tout ce qui NOMME une app (calendrier, journal, « Mon RAG », scène et page des droits, menu « Envoyer vers », phrases des outils de l'assistant, nom d'une source de modèle — `model_manager.models.source_identity`). Rien ne déduit un monde d'un libellé de navigation, et rien ne lit une déclaration hors du registre (garde `AppIdentityTest`)

- **Domicile** : `wama/common/app_registry.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — Application Registry
- **API publique** (45) :
  - `register_category_extensions(category, extensions)` — Un MONDE déclare les extensions qu'il POSSÈDE pour une nature de `MEDIA_CATEGORIES`.
  - `media_extensions() -> dict` — Les extensions reconnues, PAR NATURE — `{nature: [ext…]}`, sans le point.
  - `category_of_path(path)` — Catégorie média ('image'|'video'|'audio'|'document'|'archive'|'dataset'|'3d'|'score') d'un chemin
  - `normalize_types(types)` — ['wav','image','srt'] → ['audio','image','document'] (catégories média + jetons de rôle,
  - `known_port_types()` — Vocabulaire ADMIS pour le type d'un port — natures média + jetons de rôle + types de DONNÉE.
  - `app_capabilities(app_id)` — Capacités déclarées d'une app = les drapeaux `conventions` d'APP_CATALOG, retournés à plat.
  - `app_supports_during_preview(app_id)` — True si l'app déclare la capacité de preview « pendant » : on OBSERVE le média de sortie
  - `studio_node_ports(app_id)` — Dérive les PORTS d'un nœud studio pour une app, métadonnée-driven :
  - `app_model_capabilities(app_id) -> list` — Les capacités des modèles DE l'app — l'inventaire UNIQUE dont dérivent ses ports
  - `app_input_ports(app_id, domain=None)` — Ports d'entrée d'une app DÉRIVÉS DES CAPACITÉS DE SES MODÈLES — l'auto-adaptation.
  - `app_has_live_input(app_id) -> bool` — L'app capte-t-elle EN DIRECT (Speak) ? — le port `live` de la card d'entrée.
  - `app_instant_preview(app_id) -> bool` — L'app montre-t-elle son résultat PENDANT la frappe (le Translator « à la DeepL ») ?
  - `app_own_input_ports(app_id)` — Ports d'entrée que l'APP consomme elle-même — aucun modèle ne les déclare (2026-09-30).
  - `ports_for_domain(app_id, domain, ports)` — Les ports d'une card, restreints à un DOMAINE de l'app (2026-09-30, card v4 multi-domaine).
  - `app_ports_carried_elsewhere(app_id) -> dict` — Ports que la card d'ENTRÉE de l'app ne montre pas, parce qu'un AUTRE geste les porte —
  - `entry_form(ports) -> dict` — La FORME D'ENTRÉE d'une card, DÉDUITE de l'obligation que chaque port porte (2026-10-19).
  - `principal_entry(ports) -> dict` — L'ENTRÉE PRINCIPALE d'un nœud du Studio, tirée de la forme d'entrée (`entry_form`) :
  - `app_result_ports(app_id)` — Entrées que l'APP consomme elle-même autour du résultat — jamais un modèle.
  - `world_label(world: str) -> str` — Libellé d'un monde ; le nom brut si le monde est inconnu (jamais une chaîne vide).
  - `register_app_world(app_id: str, world: str) -> None` — Déclare le monde d'une app hors catalogue. Refuse un monde hors vocabulaire, et refuse
  - `register_surface(app_id: str, *, world: str, label: str, url_name: str, icon: str, description: str='', color: str | None=None, nav_hide: bool=False, order: in…` — Déclare la PAGE d'une app hors catalogue : son monde et son identité (libellé, route,
  - `register_pageless_tool(app_id: str, *, world: str, label: str, icon: str, probe: str, description: str='') -> None` — Déclare un outil gardé SANS PAGE : son monde et son identité. Idempotent, comme
  - `pageless_tools() -> list` — Les outils sans page déclarés (copies), par libellé.
  - `pageless_tool_for(app: str) -> dict | None` — L'outil sans page `app`, ou None — le pendant de `surface_for`.
  - `declared_identity(app: str) -> dict | None` — L'identité DÉCLARÉE d'une app hors catalogue (libellé, monde, description…) : sa surface,
  - `app_identity(app: str) -> dict` — L'IDENTITÉ d'une app, quelle que soit sa façon de se déclarer — `{'app', 'declared',
  - `register_account_page(key: str, *, section: str, label: str, icon: str, access: str, url_name: str='', surface: str='', tone: str='', color: str='', order: int…` — Déclare une page du COMPTE. Idempotent, comme `register_surface`.
  - `account_pages() -> list` — Les pages du compte déclarées (copies), dans l'ordre du menu : section, rang, libellé.
  - `account_page_of(url_name: str) -> dict | None` — La page du compte que sert la route `url_name` (`'common:licenses_catalog'`), ou None.
  - `surfaces(world: str | None=None) -> list` — Surfaces déclarées (copies), d'un monde ou de tous, dans l'ordre de leur section.
  - `surface_for(app: str) -> dict | None` — Surface d'une app déclarée hors `APP_CATALOG` — Lab, Studio, Médiathèque —, ou None. Le
  - `app_media_folders(app_id: str) -> tuple` — Dossiers qu'une app montre dans l'explorateur de fichiers : `((sous-dossier, libellé), …)`.
  - `derive_category(entry) -> str` — Catégorie DÉRIVÉE des types déclarés — la déclaration explicite prime, la dérivation
  - `get_app_groups() -> list` — Sections de TOUT ce qui se montre groupé — menu Applications, accueil, `/apps/` : UNE
  - `app_world(app_id: str) -> str | None` — Monde DÉCLARÉ d'une app — `media | data | lab | transverse`, le vocabulaire de
  - `accepts_file(app_name: str, filename: str) -> bool` — Le serveur prend-il ce fichier pour cette app ? — les extensions DÉCLARÉES
  - `port_accept(app_name: str, types) -> str` — L'attribut `accept` d'un PORT d'entrée — ce que la tuile Importer propose.
  - `accept_for_types(declared, types) -> str` — Le cœur de `port_accept`, sur une liste d'extensions DONNÉE — pour le générateur, qui
  - `get_app_extensions_for_filemanager() -> dict` — Returns a dict suitable for FileManager JS APP_EXTENSIONS:
  - `world_color(world: str) -> str` — Couleur de RÉFÉRENCE d'un monde — celle d'une surface hors catalogue sans couleur
  - `measured_adoption(mechanism: str) -> dict` — Ce que la grille MESURÉE dit d'un mécanisme : les critères qui le vérifient
  - `combined_state(states) -> object` — Plusieurs états mesurés en un : True s'ils sont tous verts, 'partial' si une partie l'est,
  - `sandbox_conformity(report: dict) -> dict` — Mesure des jumelles bac à sable, chacune avec l'écart à SA source (`report['apps']`).
  - `measure_and_write_conformity() -> dict` — Mesure les 10 apps (conformity_checker.run_checks) et ÉCRIT le rapport JSON.
  - `get_conformity_summary() -> dict` — Returns per-app conformity score:

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

### Langue d'un contenu (écrit, parlé)

La langue d'un TEXTE (`langid`, balises de section retirées, verdict peu sûr = inconnue — les paroles du composer, 2026-10-05) et celle d'un AUDIO (Whisper sur plusieurs passages — la langue d'un fichier proposée, le transcriber). Deux faces, une question : en quelle langue est ce contenu ? — jamais une heuristique d'app (celle du describer, morte, est retirée le jour même)

- **Domicile** : `wama/common/utils/text_language.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : La LANGUE d'un texte — pendant écrit de `spoken_language` (2026-10-05).
- **API publique** (1) :
  - `detect_text_language(text) -> str` — Code ISO 639-1 de la langue du texte (`fr`, `en`, `zh`…), ou '' si elle n'est pas sûre.

### Le texte À DIRE (préparation avant vocalisation)

`text_for_speech` (la chaîne, dans un ordre dont chaque place se justifie) et `make_audible` (la mise en forme visuelle traduite en respirations : puce de tête, point en fin de ligne non ponctuée, tiret d'incise → virgule, `/` → « ou »). ⚠ Le domaine était écrit DEUX FOIS, sous le MÊME NOM de fonction : la vue de vocalisation avait les emojis, le Markdown et les respirations, `synthesizer/utils/text_extractor.py` avait les URL et les e-mails — donc le synthesizer, dont le métier est de lire un document à voix haute, lisait les listes d'un trait. Unifié le 2026-09-26 (demande de Fabien) ; le nom du synthesizer DÉLÈGUE, ses six appelants sont intacts. Consommateurs : la vue `kokoro_tts` (donc toute surface qui vocalise — accueil, volet, canaux) et le synthesizer. Depuis le 2026-10-18 (défauts entendus, mesurés par aller-retour voix → transcription) : parenthèses dites en incises (`say_incises`), emphase courte en majuscules (`say_emphasis`), code en ligne dit, et `pause_segments` — où la voix respire, et combien : les réglages de pauses (déclarés une fois, `common/tts/constants.VOICE_PAUSE_SETTINGS`) de l'assistant et du synthesizer, posés pour TOUT moteur par leur contrat commun (`tts_base.TTSBackend.synthesize`). Le second nettoyage du navigateur est RETIRÉ. Depuis le 2026-10-27, le LEXIQUE de prononciation (`lexicon`) : le fichier système `common/tts/pronunciations.json` et les lignes d'un compte (registre `pronunciations`), qu'un moteur dit par l'orthographe (`respell_with_lexicon`, au contrat commun) ou par les phonèmes (`phonemes_with_lexicon`, Kokoro) — joint à la demande par `tts_via_service(user=)`, le service vocal n'ayant pas Django

- **Domicile** : `wama/common/utils/tts_text.py` · **doc** : [docs/construction/ia/WAMA_LLM.md §1bis](../construction/ia/WAMA_LLM.md)
- **Module** : Le texte À DIRE — brique commune de préparation d'un texte pour la synthèse vocale.
- **API publique** (10) :
  - `pronunciations(language: str) -> dict` — Le lexique SYSTÈME de `language` (code WAMA, `fr`), celui du fichier : {graphie : entrée}.
  - `system_lexicons() -> dict` — Tout le fichier : {langue : {graphie : entrée}} — le registre `pronunciations` le lit.
  - `lexicon(language: str, extra=None) -> dict` — Le lexique que dit la voix : le fichier, puis `extra` ({graphie : entrée}, les lignes que
  - `respell_with_lexicon(text: str, language: str, extra=None) -> str` — Le texte À DIRE, chaque terme qui a une ORTHOGRAPHE (`spelling`) remplacé par elle — pour
  - `phonemes_with_lexicon(text: str, language: str, phonemize, finish=None, extra=None) -> str` — Les phonèmes de `text`, ceux du LEXIQUE à la place de ce que dirait le phonémiseur.
  - `make_audible(text: str) -> str` — Traduit la MISE EN FORME VISUELLE en respirations audibles.
  - `say_incises(text: str) -> str` — Parenthèses et crochets dits comme des INCISES — entre deux virgules (voir
  - `say_emphasis(text: str) -> str` — Les mots courts d'EMPHASE en majuscules (`_SHORT_EMPHASIS_WORDS`) passent en minuscules ;
  - `pause_segments(text: str, sentence_pause: float=0.0, clause_pause: float=0.0) -> list` — Le texte À DIRE découpé là où la voix doit RESPIRER : `[(segment, pause en s), …]`.
  - `text_for_speech(text: str) -> str` — Prépare un texte pour la synthèse vocale : la TTS doit LIRE, pas décrire.

### Moteurs de recherche web

Un adaptateur par moteur (Exa, Staan, SearXNG, DuckDuckGo) derrière UN contrat : l'inventaire vient des sources `kind='recherche'` du registre, jamais d'une liste écrite dans le code appelant. Le choix a DEUX étages — défaut d'instance (`WAMA_SEARCH_ENGINE`) et préférence de chacun au profil qui le surcharge —, et un moteur à clé n'est proposé qu'à qui a posé la sienne. Né le 2026-09-26 (décision de Fabien) : la recherche de l'assistant était câblée sur UN moteur écrit en dur, et le jour où il a cessé de répondre autre chose qu'un défi anti-robot, la surface entière est tombée sans recours. ⚠ Un moteur qui répond autre chose que des résultats LÈVE (`SearchEngineUnavailable`) au lieu de rendre une liste vide : un échec qui emprunte la forme d'un succès se croit

- **Domicile** : `wama/common/search_engines/registry.py` · **doc** : [docs/construction/ia/WAMA_LLM.md](../construction/ia/WAMA_LLM.md)
- **Module** : Quel moteur de recherche, pour qui — et avec quelle clé.
- **API publique** (8) :
  - `engine_slugs() -> list[str]` — Les moteurs implémentés, dans l'ordre de préférence par défaut.
  - `declared_engines() -> list` — Les sources `recherche` du registre QUI ONT un adaptateur ici.
  - `needs_key(slug: str) -> bool`
  - `key_for(user, slug: str) -> str` — La clé de CET utilisateur pour ce moteur — règle commune (`accounts.api_keys`) : un
  - `usable_slugs(user) -> list[str]` — Les moteurs que CET utilisateur peut employer : sa clé posée, ou aucune clé requise —
  - `preferred_slug(user) -> str` — Le moteur de cet utilisateur : sa préférence, sinon le défaut d'instance, sinon le
  - `get_engine(slug: str, api_key: str='', scope: str='instance') -> BaseSearchEngine | None`
  - `engine_for(user) -> BaseSearchEngine` — Le moteur à employer pour cet utilisateur, prêt à interroger.

### Médias de test isolés

Le runner de tests redirige `MEDIA_ROOT` vers `media_tests/run-<id>/` — dossier SŒUR de `media/`, jamais dedans (servi, sauvegardé, miré) ; les exécutions orphelines (vides ou > 24 h, teardown jamais joué) se balaient à l'entrée de la suivante. Le nocturne, lui, écrit chez les COMPTES DE TEST dans `media/` (serveur vivant) et se balaie par NOM (`wama_temoin_*`, dossier temporaire compris). Question Fabien 2026-09-13 : « on ne change rien pour ça ». Même raison pour le CORPUS de manifestes, versionné (2026-10-12) : le runner pose `MANIFEST_CORPUS_SYNC = False`, qui coupe la porte `manifests.corpus.follow` — une installation, une validation ou une désinstallation jouée en base de test ne réécrit ni ne retire jamais un fichier réel

- **Domicile** : `wama/common/runners.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §①bis](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Runner de tests WAMA — isole le média des tests du média de PRODUCTION.
- **API publique** (3) :
  - `class WamaTestRunner(DiscoverRunner)` — `DiscoverRunner` + `MEDIA_ROOT` redirigé vers un dossier jetable.
  - `prune_copied_twin_tests(suite, labels=(), twins=None) -> int` — Retire de `suite` (en place, récursivement) les tests COPIÉS des jumelles du bac à sable,
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

### Nivellement de la parole

Automation de niveau qui suit les mots : les passages sont égalisés (vers −20 dBFS), les silences gardent le gain des mots voisins (le bruit n'est pas pompé) ; le niveau de parole ne sort jamais plus bas qu'il n'est entré, puis le signal monte jusqu'à une crête de −0,2 dBFS (2026-10-21), crêtes limitées en douceur. Réglage optionnel du transcriber, MESURÉ dans les lots d'évaluation

- **Domicile** : `wama/common/utils/speech_leveling.py` · **doc** : [docs/construction/ia/WAMA_QUALITE.md](../construction/ia/WAMA_QUALITE.md)
- **Module** : NIVELLEMENT DE LA PAROLE — une automation de niveau qui suit les mots (idée de Fabien, 2026-09-25).
- **API publique** (2) :
  - `level_speech(wave, sample_rate: int=16000, *, target_db: float=-20.0, window_s: float=0.4, max_boost: float=24.0, max_cut: float=10.0, gate_db: float=8.0, smoo…` — Signal mono float → même signal, niveau de la parole amené vers `target_db` (dBFS, puissance
  - `level_file(in_path, out_path, sample_rate: int=16000) -> str` — Nivelle un fichier audio (tout format lisible par le décodeur commun) → WAV mono 16 bits.

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

### Notation d'un MIDI multi-instrument (MIDI → ABC)

Un MIDI à une piste par instrument → une partition ABC lisible : une voix par instrument (libellé français), clavier sur deux portées, batterie en portée de percussion, accords, liaisons, altérations par mesure. Sur la métrique du MIDI quand le moteur en a trouvé une, sinon sur les temps JOUÉS de l'audio (`audio_rhythm`), anacrouse comprise. Né le 2026-10-16 pour la partition complète du composer (MuScriptor, tâche `audio-to-midi`) ; ne connaît aucun moteur. Porte aussi la LECTURE MIDI commune (`read_midi` : tempos, mesure, tonalité, marqueurs, une partie par piste et canal), que le moteur YuE2 consomme pour suivre une partition MIDI

- **Domicile** : `wama/common/utils/midi_score.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Un MIDI multi-pistes → une partition ABC LISIBLE (2026-10-16, la « Partition complète » du composer).
- **API publique** (11) :
  - `instrument_label(name: str) -> str` — Le libellé français d'une piste nommée par le moteur (`INSTRUMENT_LABELS`).
  - `class MidiPart` — Une partie du MIDI — une piste et un canal : son nom (`track_name`), batterie ou non (canal
  - `class MidiSong` — Ce qu'un fichier MIDI déclare, lu une fois (`read_midi`) : la base de temps, la carte des
  - `read_midi(source) -> MidiSong` — La LECTURE MIDI commune (2026-10-16) — un chemin ou des octets → `MidiSong`, par `mido`.
  - `abc_pitch(pitch: int) -> tuple` — (lettre ABC avec octave, dièse ?) d'une hauteur MIDI : 60 → ('C', False), 73 → ('c', True).
  - `split_length(steps: int) -> list` — Une durée en pas découpée en valeurs écrivables (la plus longue d'abord).
  - `bar_offset_of(markers) -> float` — Le décalage (s) qu'un moteur a ajouté pour poser la mesure 1 sur un temps fort — marqueur
  - `mark_downbeat(midi_bytes: bytes, seconds: float) -> bytes` — Le MIDI avec son marqueur de premier temps fort (`DOWNBEAT_MARKER`, en secondes d'audio).
  - `downbeat_of(markers)` — L'instant (s) du premier temps fort que dit un marqueur `downbeat=<s>`, None sinon.
  - `played_beat_steps(beat_times, grid: int, offset: float)` — `(secondes MIDI → pas)` sur les temps JOUÉS : une note se place entre les deux temps de
  - `midi_to_abc(midi_bytes: bytes, *, title: str='', grid: int=4, bars_per_line: int=4, beat_times=None) -> str` — Le texte ABC d'un MIDI multi-pistes (voir l'en-tête). Lève `ValueError` sans aucune note.

### Pont référentiel ↔ cadres typés (WAMA Data)

SEULE frontière entre les deux vocabulaires du monde Data : le référentiel (paresseux, indexé, sans pandas) et le `TypedFrame` que mangent toutes les fonctions du catalogue. Sans lui le référentiel n'avait AUCUN consommateur — non parce qu'on ne s'en servait pas, mais parce qu'on ne POUVAIT pas. Traite quatre pièges mesurés : le temps de SESSION (± offset) vs le temps local du flux, la colonne temporelle brute PÉRIMÉE après ré-horodatage, le contrat `rows` réel mais non déclaré, et la PROVENANCE — ce qui revient d'un calcul ne peut pas se déclarer acquis (`is_base=False` sans échappatoire)

- **Domicile** : `wama_data/frames.py` · **doc** : [docs/construction/mondes/WAMA_DATA_WORLD.md §9quater.7](../construction/mondes/WAMA_DATA_WORLD.md)
- **Module** : LE PONT — `Signal` / `TemporalReferential` ↔ `TypedFrame`.
- **API publique** (6) :
  - `default_type(signal: Signal) -> str` — Type de cadre : la FAMILLE DÉCLARÉE d'abord, la structure en repli.
  - `frame_from_signal(signal: Signal, *, t0: Optional[float]=None, t1: Optional[float]=None, offset: float=0.0, data_type: Optional[str]=None, champs: Optional[Ite…` — Une FENÊTRE d'un flux, en cadre typé prêt pour le catalogue.
  - `frame_from_referential(ref: TemporalReferential, name: str, *, t0: Optional[float]=None, t1: Optional[float]=None, data_type: Optional[str]=None, champs: Optio…` — Une fenêtre d'un flux du référentiel, **en temps de session** (piège ①).
  - `frame_from_table(path, data_type: str, *, meta: Optional[Mapping[str, Any]]=None) -> TypedFrame` — Un fichier PLAT (CSV, TSV, TXT, XLSX…) en cadre du type DIT — l'entrée « Jeu de données »
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

Réglages durables en base (UserAppSetting, cache devant) ; réglages du VOLET dérivés du schéma — lire, garder, remettre à zéro, faire naître un élément, deux routes JSON (`*_panel_settings`, `new_element_settings`, `make_panel_settings_views`)

- **Domicile** : `wama/common/utils/user_settings.py`
- **Module** : WAMA Common — Réglages UTILISATEUR par app, DURABLES en base (cache en lecture devant).
- **API publique** (10) :
  - `get_user_app_settings(user, app, defaults)` — Retourne le dict complet des réglages de ``user`` pour ``app``.
  - `get_user_app_setting(user, app, name, default=None)` — Lecture d'UN réglage.
  - `clear_user_app_settings(user, app, names)` — Retire les réglages `names` de ``user`` pour ``app`` : ils reprennent le défaut que
  - `read_panel_settings(user, app, params, *, key=None, extra=None, clean=None) -> dict` — Les réglages du volet de ``user``, par NOM de param (ce que `WamaParams.render` attend),
  - `save_panel_settings(user, app, params, data, *, key=None, extra=None, clean=None) -> dict` — Garde comme préférences les réglages du volet présents dans `data` (par NOM), coercés par
  - `reset_panel_settings(user, app, params, *, key=None, extra=None, clean=None) -> dict` — Remet le volet de ``user`` sur les défauts : ses préférences sont RETIRÉES (jamais
  - `new_element_settings(user, app, params, model, *, post=None, context=None, key=None, extra=None, clean=None, options_field=None, preset=None, empty_is_value=()…` — Les colonnes de réglage d'un élément NAISSANT — il naît complet (`ROADMAP §23.2quater`),
  - `element_columns(values, model) -> dict` — `values` restreint aux colonnes concrètes de `model` — ce qu'un `objects.create(**…)`
  - `make_panel_settings_views(app, params, *, key=None, extra=None, clean=None)` — Les deux vues JSON du volet — lecture (GET) et enregistrement (POST, JSON par NOM, clés
  - `save_user_app_settings(user, app, values, *, timeout=DEFAULT_TIMEOUT)` — Persiste chaque réglage fourni (en base, et en cache pour la lecture).

### Rétention des médias

Purge automatique des sorties au-delà de la durée choisie par l'utilisateur (FileField découverts)

- **Domicile** : `wama/common/services/retention.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Rétention des médias — purge automatique des sorties au-delà de la durée choisie par l'utilisateur (`UserProfile.media_retention_days`, bornée par `settings.WAMA_MAX_RETENTION_DAYS`).
- **API publique** (8) :
  - `register_retention_model(label: str, *, path_lists=(), date: str=None, user: str=None)` — Déclare `label` à la rétention depuis le `ready()` de SON app — la forme d'une app GÉNÉRÉE,
  - `purge_expired_media(dry_run=False)` — Purge les médias expirés de tous les modèles enregistrés, par utilisateur (selon sa rétention).
  - `retention_days_by_user()` — {user_id: jours} de tous les utilisateurs à rétention FINIE (plafond global inclus) — lu une
  - `retention_days_for(user)` — Rétention EFFECTIVE d'un utilisateur, en jours (plafond global inclus) ; 0 = aucune.
  - `expirations_for(user, start, end)` — Médias de `user` qui EXPIRENT dans `[start, end)` : `[{app, model, id, expires_at}]`.
  - `purge_expired_temp(dry_run=False)` — Supprime, pour chaque utilisateur à durée finie, les fichiers de son dossier temporaire plus
  - `upcoming_temp_expirations(days_ahead)` — {user_id: n} des fichiers du temp qui seront supprimés dans <= days_ahead jours (pré-avis).
  - `upcoming_expirations(days_ahead)` — {user_id: [(model_label, count), ...]} des médias expirant dans <= days_ahead jours.

### Sauvegarde & tirage

Moteur unique de miroir (modèles, base, médias, secrets) et restauration (`restore_backup`). 2026-10-27 : le tirage d'une perte PARTIELLE ne recopie que les fichiers absents (`keep_existing`, `--missing-only`) — un fichier modifié depuis la sauvegarde n'est plus remplacé par sa version ancienne ; 2026-10-28 : le tirage BORNÉ à ce que la base connaît encore (`keep`, `--known-only` : comptes réels, médiathèque, fichiers qu'une card hors compte de test référence) ; procédure : skill `restauration`

- **Domicile** : `wama/common/services/mirror_sync.py`
- **Module** : Miroir incrémental d'une arborescence locale vers un espace distant — brique COMMUNE.
- **API publique** (12) :
  - `resolve_remote_root(subdir: str, env_var: str | None=None) -> str` — Chemin de l'espace distant pour un domaine (`MODELS`, `DB`, `MEDIAS`…).
  - `remote_is_available(remote_path) -> bool` — L'espace distant est-il utilisable EN ÉCRITURE, sans effet de bord ?
  - `copy_file(source: Path, dest: Path) -> tuple[bool, float, str | None]` — PRIMITIVE DE COPIE UNIQUE du projet : crée les dossiers parents et copie.
  - `internal_link(path: Path, source_root: Path) -> str | None` — Valeur RELATIVE du lien si `path` est un lien symbolique vers un fichier situé DANS
  - `read_links_manifest(path: Path) -> dict`
  - `write_links_manifest(dest_root: Path, links: dict) -> None` — FUSIONNE `links` dans le manifeste de `dest_root` — cumulatif comme le reste de
  - `new_summary(remote_path) -> dict` — Squelette de compte rendu, partagé par les appelants pour publier un état initial
  - `mirror_tree(source_root, dest_root, *, overwrite: bool=False, exclude=None, dry_run: bool=False, progress_cb=None, on_file=None, progress_every: int=PROGRESS_E…` — Réplique `source_root` vers `dest_root` en conservant l'arborescence relative.
  - `purge_keep_latest(directory, pattern: str, keep: int) -> list[str]` — Ne conserve que les `keep` fichiers les plus récents de `directory` correspondant à
  - `remember_last_run(cache_key: str, state: str, payload: dict) -> dict` — Garde le bilan de la dernière exécution TERMINÉE (succès, partiel, échec), sans expiration.
  - `last_mirror_run(cache_key: str)` — Bilan de la dernière exécution terminée d'un miroir, ou None s'il n'a jamais tourné.
  - `run_mirror_job(runner, *, cache_key, task_id, label, ttl=24 * 3600)` — Exécute un miroir en publiant son avancement dans le cache — enveloppe COMMUNE aux

### Scènes de proximité (constellations 3D)

Une scène DÉCLARE ce qu'elle montre — couches, facteurs de distance pondérés (relationnel, catégoriel, numérique), sortes de groupes, mesures, textes — et UNE brique la monte : nœuds, sphères de verre qui enveloppent leurs membres, liens animés, volet de détail, curseurs, mode intégré. Déclarée par son domaine dans le `ready()` de son app ; une scène qui projette un registre (`registry`) donne à la page de ce registre son bouton « Constellation » (`scene_button`). Scènes : les utilisateurs (premier consommateur, son adresse gardée), les licences, les modèles ; une scène de la page commune est jouée chaque nuit (`common.scene.<clé>.ui`). La légende filtre ; les MAINS pilotent toute scène à la webcam — interface GLOBALE de la barre du haut (pointeur et pincement universels, ce qu'une page déclare en cible), MediaPipe dans le navigateur, modèle des gestes installé par la route

- **Domicile** : `wama/common/scenes.py` · **doc** : [docs/construction/ui/WAMA_SCENES_3D.md](../construction/ui/WAMA_SCENES_3D.md)
- **Module** : Les SCÈNES DE PROXIMITÉ (constellations 3D) — déclarées par leur domaine, montées par UNE brique.
- **API publique** (10) :
  - `class Scene`
  - `register_scene(scene: Scene) -> Scene` — Déclare une scène. Les incohérences se voient À LA DÉCLARATION, pas dans le navigateur.
  - `get_scene(key: str) -> Optional[Scene]`
  - `scene_for_registry(registry_key: str) -> Optional[Scene]` — La scène qui projette ce registre, s'il y en a une (bouton de l'en-tête de sa page).
  - `can_view(scene: Scene, user) -> bool`
  - `page_url(scene: Scene) -> str`
  - `data_url(scene: Scene) -> str`
  - `scene_data(scene: Scene, user) -> dict` — Le contrat de la scène, lu de sa source (`data`).
  - `scene_spec(scene: Scene) -> dict` — La déclaration, telle que la page la sert à la brique (`<script type="application/json">`).
  - `page_context(scene: Scene, embed: bool) -> dict` — Le contexte du gabarit commun : la déclaration, et l'état de départ de chaque puce.

### Servir un fichier par morceaux (HTTP Range)

Réponse 206 à une requête `Range` — ce qui rend un média seekable au-delà du déjà-téléchargé ; sert `/media/` (`wama/urls.py`) et la vidéo du cam_analyzer, dont la règle a été extraite (2026-10-15)

- **Domicile** : `wama/common/utils/ranged_response.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : Servir un fichier PAR MORCEAUX (requêtes HTTP `Range`) — ce qui rend un média SEEKABLE.
- **API publique** (3) :
  - `parse_range(header: str, size: int)` — `(début, fin)` inclusifs d'un en-tête `Range` à UN intervalle, bornés à la taille ; None si
  - `ranged_file_response(request, path: str, content_type: str | None=None)` — La réponse qui sert `path` — son morceau (206) si la requête en demande un, sinon le
  - `serve(request, path, document_root=None, show_indexes=False)` — `django.views.static.serve`, plus les requêtes `Range` (206) — le service de `/media/`.

### Sonde média

Durée/codec/dimensions/pages d'un média pour les propriétés de card (via ffmpeg_utils) ; depuis le 2026-09-13, un OBJET 3D livre sa table des matières glTF sans décodage (`probe_object3d` : format, faces, rig, animations) sous la clé `attributes` — ce que la médiathèque pose à l'ingest sur la nature `object3d` (A′)

- **Domicile** : `wama/common/utils/media_probe.py` · **doc** : [docs/construction/suivi/ROADMAP.md §17ter](../construction/suivi/ROADMAP.md)
- **Module** : WAMA Common — Sonde média (durée / codec / dimensions / pages / entrées).
- **API publique** (7) :
  - `format_duration(seconds: float) -> str` — ``95.4 -> '1:35'``, ``3750 -> '1:02:30'`` — affichage court ('' si inconnu/zéro).
  - `probe_audio(path: str) -> dict` — Sonde le premier flux audio d'un fichier.
  - `probe_video(path: str) -> dict` — Sonde le premier flux vidéo : codec • L×H • fps, + durée (stream puis format).
  - `probe_video_format(path: str, *, timeout: int=20) -> dict` — Ce que le NAVIGATEUR regarde du premier flux vidéo : `{container, codec, profile,
  - `probe_object3d(path: str) -> dict` — Sonde d'un OBJET 3D (ROADMAP §17ter, trou 2) — ce que le fichier DÉCLARE, sans le décoder.
  - `probe_media(path: str) -> dict` — Sonde générique TOUS types (dispatch par extension).
  - `probe_media_cached(path: str, ttl: int=86400) -> dict` — `probe_media` avec cache Django par (chemin, mtime) — pour les endpoints à la requête

### Sources externes

Registre DÉCLARATIF de ce que WAMA joint au dehors : adresse, réglage qui la surcharge, variable portant la clé d'API, attribution exigée par la licence, et surtout la PORTÉE (service local ou Internet) — d'où le traitement du proxy est DÉRIVÉ au lieu d'être choisi à la main par chaque appelant. Ajouter une plateforme = une entrée. ⚠ Ne déclare JAMAIS le client : chaque source a sa forme (JSON authentifié, parquet, HTML scrapé), le parseur reste chez le consommateur. La CLÉ peut être celle de l'instance (`api_key_env`) ou celle de CHACUN, posée au profil (`user_key`) : depuis le 2026-09-22 (décision de Fabien) les connecteurs de la médiathèque y sont déclarés (famille `media`) — adresse, proxy et sonde d'ici, clé de chaque utilisateur. Depuis le 2026-10-07 (décision de Fabien), la clé d'INSTANCE se pose par un admin sur la page « Sources externes » (`accounts.InstanceApiKey`, chiffrée) et prime sur le `.env`, qui reste le repli ; une source `shareable` (clés d'application : ILaaS) peut la PARTAGER avec les comptes sans clé — la clé personnelle prime toujours. Le champ de saisie est UNE brique (`WamaKeyField`) pour le profil et la page. Une clé FACULTATIVE (`api_key_optional`, 2026-10-12 : le jeton de `github_api`) relève un quota sans rendre la source « non configurée » quand elle manque. La FORME des clés se déclare aussi (`api_key_prefix`, 2026-10-26, mesurée sur des clés réelles) : une clé tronquée est refusée au dépôt (`api_keys.key_shape_error`, dans `store_key`, le geste des deux écrans). Une PLATEFORME de modèles déclare la fiche d'un modèle (`model_page`, 2026-10-22) : `model_platforms()` est le vocabulaire de `AIModel.platform_ref`, `model_page_url()` en rend la page (lien de card, validation du manifeste `model`), `hf_repo()` en tire le dépôt du Hub — la seule lecture du dépôt d'un modèle depuis le 2026-10-27 (`hf_id` ne se lit plus) ; un fournisseur distant se DIT par `remote_origin_label` — hébergement · fournisseur · coût — partout où il est nommé

- **Domicile** : `wama/common/external_sources.py` · **doc** : [docs/construction/suivi/PROJECT_STATUS.md](../construction/suivi/PROJECT_STATUS.md)
- **Module** : external_sources — registre DÉCLARATIF des sources externes joignables par WAMA.
- **API publique** (34) :
  - `cost_label(tier: str) -> str` — « gratuit (quota) », « facturé à l'usage », « abonnement » — '' pour un coût inconnu.
  - `remote_origin_label(source: str, cost_tier: str='') -> str` — LE libellé d'un modèle distant, calculé de ce qui est DÉCLARÉ : hébergement · fournisseur ·
  - `source_origin_label(source: str) -> str` — Où partent les données d'un FOURNISSEUR et ce qu'il coûte, sans son nom (que l'écran
  - `model_origin(model_key: str, execution: str='', cost_tier: str='') -> tuple` — `(clé, libellé, rang)` de l'ORIGINE d'un modèle — où son inférence a lieu.
  - `hosting_within(hosting: str, ceiling: str) -> bool` — `hosting` est-il admis par un profil plafonné à `ceiling` ?
  - `data_reuse_accepted(ceiling: str) -> bool` — Un profil plafonné à `ceiling` accepte-t-il qu'un hébergeur garde ou réutilise ses
  - `class Quota` — Une limite de débit DÉCLARÉE sur une source (`ExternalSource.quotas`) — lue par la brique
  - `class ExternalSource` — Une source externe : ce qu'elle est et comment on l'adresse — jamais comment on la lit.
  - `by_key() -> dict[str, ExternalSource]`
  - `model_platforms() -> dict[str, ExternalSource]` — Les PLATEFORMES de modèles, par préfixe de `AIModel.platform_ref` — les sources qui déclarent
  - `model_page_url(platform_ref: str) -> str | None` — L'adresse de la fiche publique d'un modèle, DÉRIVÉE de son `platform_ref`
  - `hf_repo(platform_ref) -> str` — Le dépôt du Hub (`org/nom`) qu'un `platform_ref` désigne, '' pour une autre plateforme.
  - `hf_platform_ref(repo) -> str` — Le `platform_ref` d'un dépôt du Hub (`org/nom` → `huggingface:org/nom`), '' sans dépôt.
  - `github_release_of(ref) -> tuple` — `owner/repo:tag` → (`owner/repo`, `tag`) ; ('', '') si la forme n'y est pas.
  - `github_platform_ref(ref) -> str` — `owner/repo:tag` → `github:owner/repo/releases/tag/<tag>` ('' si la forme n'y est pas).
  - `github_ref_of_platform(platform_ref) -> str` — L'inverse : `github:owner/repo/releases/tag/<tag>` → `owner/repo:tag`, sinon ''.
  - `serves_many_tasks(key: str) -> bool` — La source `key` sert-elle des modèles de plusieurs tâches sous un même moteur, hors du
  - `llm_engine_inventory() -> dict` — {moteur: porteur} des fournisseurs LLM distants — un par source `llm` (2026-09-15).
  - `get(key: str) -> ExternalSource` — La source déclarée. `KeyError` explicite : une clé inconnue est un défaut de code.
  - `base_url(key: str) -> str` — Adresse EFFECTIVE : celle posée sur la page « Sources externes » (source déclarée
  - `address_origin(key: str) -> str` — D'où vient l'adresse : 'stored', 'setting', 'env', ou '' (défaut déclaré).
  - `stored_instance_address(key: str) -> str` — L'adresse posée en base pour `key` (`InstanceApiKey.base_url`), ou ''. Même lecture
  - `valid_address(text: str) -> str` — L'adresse saisie, normalisée (sans barre finale), ou '' si ce n'en est pas une :
  - `proxies_for(key: str)` — `proxies` à passer à `requests`, choisis d'après la PORTÉE déclarée.
  - `api_key(key: str) -> str` — Clé d'API de l'INSTANCE, ou '' — jamais une exception : une source sans clé se SKIPPE
  - `stored_instance_key(key: str) -> str` — La clé d'instance ENREGISTRÉE en base pour `key`, ou ''. Lue paresseusement : ce module
  - `api_key_origin(key: str) -> str` — D'où vient la clé d'instance : 'stored' (page Sources externes), 'env' (`.env`) ou ''.
  - `is_configured(key: str) -> bool` — La source est-elle utilisable en l'état ? (clé posée si elle en exige une)
  - `attributions() -> tuple[str, ...]` — Attributions exigées par les licences des sources qui en portent une.
  - `effective_url(key: str) -> str` — Adresse EFFECTIVE d'une source — celle qu'on sonde et qu'on appelle. Pour Ollama, le
  - `probe(key: str, timeout: float=PROBE_TIMEOUT_S) -> dict` — Sonde UNE source : clé posée ? adresse joignable ? en combien de temps ?
  - `report_path()`
  - `probe_all(write: bool=False) -> dict` — Sonde TOUTES les sources déclarées, et écrit le rapport si demandé.
  - `last_report() -> dict | None` — Le dernier rapport ÉCRIT, ou None — la page l'affiche sans jamais sonder elle-même.

### Taxonomie des natures & vocabulaire d'entrée

Source UNIQUE des natures de média (image/video/audio/document/archive/dataset/3d — `text` RETIRÉ le 2026-08-30, arbitrage §S2bis.6bis : les fichiers texte sont des documents, la saisie est le jeton de RÔLE `prompt`) : détecte la nature d'un nom de fichier (`category_of_path`, défaut 'document') et normalise un vocabulaire (`normalize_types`) ; un MONDE pousse ses extensions par `register_category_extensions` (dataset ← sonde wama_data), jamais en dur. Porte AUSSI la déclaration par app de ce qu'elle accepte — `input_types` (les natures) et `input_extensions` (les extensions) — d'où le manifeste tire `body.ports.inputs[].types` et `body.identity.input_extensions`, l'axe UX ses `accepts` de domaine, le gabarit généré son `accept=` de dropzone, et la vue générée sa dérivation de nature CONTRAINTE au vocabulaire déclaré

- **Domicile** : `wama/common/app_registry.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Common — Application Registry
- **API publique** (45) :
  - `register_category_extensions(category, extensions)` — Un MONDE déclare les extensions qu'il POSSÈDE pour une nature de `MEDIA_CATEGORIES`.
  - `media_extensions() -> dict` — Les extensions reconnues, PAR NATURE — `{nature: [ext…]}`, sans le point.
  - `category_of_path(path)` — Catégorie média ('image'|'video'|'audio'|'document'|'archive'|'dataset'|'3d'|'score') d'un chemin
  - `normalize_types(types)` — ['wav','image','srt'] → ['audio','image','document'] (catégories média + jetons de rôle,
  - `known_port_types()` — Vocabulaire ADMIS pour le type d'un port — natures média + jetons de rôle + types de DONNÉE.
  - `app_capabilities(app_id)` — Capacités déclarées d'une app = les drapeaux `conventions` d'APP_CATALOG, retournés à plat.
  - `app_supports_during_preview(app_id)` — True si l'app déclare la capacité de preview « pendant » : on OBSERVE le média de sortie
  - `studio_node_ports(app_id)` — Dérive les PORTS d'un nœud studio pour une app, métadonnée-driven :
  - `app_model_capabilities(app_id) -> list` — Les capacités des modèles DE l'app — l'inventaire UNIQUE dont dérivent ses ports
  - `app_input_ports(app_id, domain=None)` — Ports d'entrée d'une app DÉRIVÉS DES CAPACITÉS DE SES MODÈLES — l'auto-adaptation.
  - `app_has_live_input(app_id) -> bool` — L'app capte-t-elle EN DIRECT (Speak) ? — le port `live` de la card d'entrée.
  - `app_instant_preview(app_id) -> bool` — L'app montre-t-elle son résultat PENDANT la frappe (le Translator « à la DeepL ») ?
  - `app_own_input_ports(app_id)` — Ports d'entrée que l'APP consomme elle-même — aucun modèle ne les déclare (2026-09-30).
  - `ports_for_domain(app_id, domain, ports)` — Les ports d'une card, restreints à un DOMAINE de l'app (2026-09-30, card v4 multi-domaine).
  - `app_ports_carried_elsewhere(app_id) -> dict` — Ports que la card d'ENTRÉE de l'app ne montre pas, parce qu'un AUTRE geste les porte —
  - `entry_form(ports) -> dict` — La FORME D'ENTRÉE d'une card, DÉDUITE de l'obligation que chaque port porte (2026-10-19).
  - `principal_entry(ports) -> dict` — L'ENTRÉE PRINCIPALE d'un nœud du Studio, tirée de la forme d'entrée (`entry_form`) :
  - `app_result_ports(app_id)` — Entrées que l'APP consomme elle-même autour du résultat — jamais un modèle.
  - `world_label(world: str) -> str` — Libellé d'un monde ; le nom brut si le monde est inconnu (jamais une chaîne vide).
  - `register_app_world(app_id: str, world: str) -> None` — Déclare le monde d'une app hors catalogue. Refuse un monde hors vocabulaire, et refuse
  - `register_surface(app_id: str, *, world: str, label: str, url_name: str, icon: str, description: str='', color: str | None=None, nav_hide: bool=False, order: in…` — Déclare la PAGE d'une app hors catalogue : son monde et son identité (libellé, route,
  - `register_pageless_tool(app_id: str, *, world: str, label: str, icon: str, probe: str, description: str='') -> None` — Déclare un outil gardé SANS PAGE : son monde et son identité. Idempotent, comme
  - `pageless_tools() -> list` — Les outils sans page déclarés (copies), par libellé.
  - `pageless_tool_for(app: str) -> dict | None` — L'outil sans page `app`, ou None — le pendant de `surface_for`.
  - `declared_identity(app: str) -> dict | None` — L'identité DÉCLARÉE d'une app hors catalogue (libellé, monde, description…) : sa surface,
  - `app_identity(app: str) -> dict` — L'IDENTITÉ d'une app, quelle que soit sa façon de se déclarer — `{'app', 'declared',
  - `register_account_page(key: str, *, section: str, label: str, icon: str, access: str, url_name: str='', surface: str='', tone: str='', color: str='', order: int…` — Déclare une page du COMPTE. Idempotent, comme `register_surface`.
  - `account_pages() -> list` — Les pages du compte déclarées (copies), dans l'ordre du menu : section, rang, libellé.
  - `account_page_of(url_name: str) -> dict | None` — La page du compte que sert la route `url_name` (`'common:licenses_catalog'`), ou None.
  - `surfaces(world: str | None=None) -> list` — Surfaces déclarées (copies), d'un monde ou de tous, dans l'ordre de leur section.
  - `surface_for(app: str) -> dict | None` — Surface d'une app déclarée hors `APP_CATALOG` — Lab, Studio, Médiathèque —, ou None. Le
  - `app_media_folders(app_id: str) -> tuple` — Dossiers qu'une app montre dans l'explorateur de fichiers : `((sous-dossier, libellé), …)`.
  - `derive_category(entry) -> str` — Catégorie DÉRIVÉE des types déclarés — la déclaration explicite prime, la dérivation
  - `get_app_groups() -> list` — Sections de TOUT ce qui se montre groupé — menu Applications, accueil, `/apps/` : UNE
  - `app_world(app_id: str) -> str | None` — Monde DÉCLARÉ d'une app — `media | data | lab | transverse`, le vocabulaire de
  - `accepts_file(app_name: str, filename: str) -> bool` — Le serveur prend-il ce fichier pour cette app ? — les extensions DÉCLARÉES
  - `port_accept(app_name: str, types) -> str` — L'attribut `accept` d'un PORT d'entrée — ce que la tuile Importer propose.
  - `accept_for_types(declared, types) -> str` — Le cœur de `port_accept`, sur une liste d'extensions DONNÉE — pour le générateur, qui
  - `get_app_extensions_for_filemanager() -> dict` — Returns a dict suitable for FileManager JS APP_EXTENSIONS:
  - `world_color(world: str) -> str` — Couleur de RÉFÉRENCE d'un monde — celle d'une surface hors catalogue sans couleur
  - `measured_adoption(mechanism: str) -> dict` — Ce que la grille MESURÉE dit d'un mécanisme : les critères qui le vérifient
  - `combined_state(states) -> object` — Plusieurs états mesurés en un : True s'ils sont tous verts, 'partial' si une partie l'est,
  - `sandbox_conformity(report: dict) -> dict` — Mesure des jumelles bac à sable, chacune avec l'écart à SA source (`report['apps']`).
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
- **API publique** (9) :
  - `get_ffprobe_path()` — DÉLÈGUE à la brique ffmpeg_utils (cf. _get_ffmpeg_path).
  - `get_media_info(file_path: str) -> dict` — Extract metadata from an image or video file.
  - `upload_media_from_url(url, output_path)` — Download a media file from a URL using yt_dlp (with robust options) or direct HTTP.
  - `extract_audio_from_video(video_path: str, output_audio_path: Optional[str]=None) -> str` — Extrait l'audio d'un fichier vidéo.
  - `download_youtube_audio(youtube_url: str, output_dir: str) -> Tuple[str, str]` — Télécharge l'audio d'une vidéo YouTube.
  - `is_video_file(filename: str) -> bool` — Vérifie si un fichier est une vidéo basé sur son extension.
  - `is_audio_file(filename: str) -> bool` — Vérifie si un fichier est un audio basé sur son extension.
  - `is_image_file(filename: str) -> bool` — Vérifie si un fichier est une image basé sur son extension.
  - `convert_video_to_web_compatible(input_path: str, output_path: Optional[str]=None) -> str` — Convertit une vidéo en format compatible web (H.264/AAC dans conteneur MP4).

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

Privé / unité / public : filtrage des lectures, mutations inchangées. Depuis le 2026-10-18 (`ROADMAP §29` étape 3), les éléments d'un CATALOGUE aussi : `catalogue_visible_q` (système et publics pour tous, les siens, sa portée ; tout pour l'admin), dont le premier porteur est `AIModel` — la provenance naît au geste d'installation, et `accessible(user, 'model', clé)` la lit sur la ligne. Depuis le 2026-10-19 (étape 4) : `UserFunction` par le même filtre, une fonction du CODE par l'app qui la porte (`Registry.element_app`, `function_catalog.accessible_specs`), et `StudioPipeline` porté comme une card (`listable_by`, `owned_or_404`)

- **Domicile** : `wama/common/models.py` · **doc** : [docs/construction/exploitation/PROFILES_PERMISSIONS.md](../construction/exploitation/PROFILES_PERMISSIONS.md)
- **Module** : Briques de modèles COMMUNES (cf. BATCH_MODEL_AUDIT.md).
- **API publique** (47) :
  - `job_status_values() -> list` — Les VALEURS des cinq états de FILE, dans l'ordre du vocabulaire.
  - `normalize_job_status(value) -> str` — Un état QUELCONQUE (base, JSON, littéral d'app) → le vocabulaire commun.
  - `class ProcessingTimeMixin(models.Model)` — Durée RÉELLE de traitement, en secondes. Le worker la CALCULE déjà (il la passe au learner
  - `class NativeOutputsMixin(models.Model)` — Les fichiers D'ORIGINE d'une card dont les réglages de sortie transforment le rendu
  - `class KeptOutputsMixin(models.Model)` — Les fichiers de RÉVISION gardés d'une card — ses sorties telles que chaque révision les a
  - `class QueueOrderMixin(models.Model)` — Position MANUELLE de l'entrée dans la file (CARD_DESIGN §3bis — manipulation directe).
  - `class BatchMixin` — Sémantique + cycle de fichiers communs aux modèles Batch (tout est batch ; unitaire = card unique).
  - `class OrgUnit(models.Model)` — Unité organisationnelle = nœud de l'arbre institut/université → département →
  - `class Project(models.Model)` — Projet de recherche = groupe de collaboration EXPLICITE qui peut TRAVERSER l'arbre
  - `class ProjectMembership(models.Model)` — Adhésion d'un utilisateur à un projet, avec son rôle et son org (traçabilité
  - `user_projects(user)` — Ids des projets dont l'utilisateur est membre (tous rôles).
  - `user_scope_org_ids(user)` — Ensemble des OrgUnit ids « couvrant » l'utilisateur : ses unités de rattachement
  - `profile_org_codes(prof)` — Les codes d'annuaire qui RATTACHENT un profil : tous ses rattachements, puis son entité
  - `class ElementPreference(models.Model)` — ABONNEMENT d'un utilisateur à un élément de catalogue (app, modèle, fonction, skill…).
  - `class UserAppSetting(models.Model)` — RÉGLAGE GLOBAL d'un utilisateur pour une app — DURABLE (brique `utils/user_settings.py`).
  - `class Notification(models.Model)` — Notification DANS WAMA — la brique de `WAMA_COLLABORATION.md §2.3` : destinataire, type
  - `class ScopedVisibility(models.Model)` — Mixin ABSTRAIT : visibilité par scope (privé / PROJET / unité org / public).
  - `scoped_visible_q(user, owner_field='user', model=None)` — `Q` filtrant les objets ScopedVisibility visibles pour `user` : les siens + les
  - `catalogue_visible_q(user, owner_field='owner', model=None)` — `Q` des éléments d'un CATALOGUE (modèles, puis librairies, fonctions…) que `user` voit
  - `class ShareConsent(models.Model)` — Le CONSENTEMENT donné en partageant un élément qui porte une PERSONNE — et son retrait.
  - `class ReceivedEntry(models.Model)` — Le RANGEMENT, chez le destinataire, d'une entrée de file qu'on lui a partagée (2026-10-02).
  - `class ObjectGrant(models.Model)` — Un DROIT sur une instance — et la DEMANDE de ce droit : la même ligne (2026-10-03).
  - `class ReleasedFile(models.Model)` — Un fichier que plus aucune card n'appelle — GARDÉ, l'utilisateur prévenu (2026-09-30).
  - `class PromptScoped(models.Model)` — Modèle portant un prompt utilisateur TRAITÉ par la PromptPipeline (enrichissement).
  - `class ScopedQuerySet(models.QuerySet)` — QuerySet des modèles `ScopedVisibility` : expose `visible_to(user)`.
  - `class ScopedManager(models.Manager.from_queryset(ScopedQuerySet))` — Manager par défaut des modèles partageables.
  - `class UserFunction(ScopedVisibility)` — Fonction de traitement CRÉÉE PAR UN UTILISATEUR (WAMA Data), stockée en BDD, avec
  - `class UserTheme(ScopedVisibility)` — Un thème tiré d'une CHARTE graphique (PDF) — pour un labo, une équipe, un établissement
  - `class PromptSkill(ScopedVisibility)` — Un SKILL de prompt qui a un AUTEUR (`ROADMAP §29`, décision de Fabien du 2026-10-20 :
  - `class Pronunciation(ScopedVisibility)` — Comment la VOIX dit un terme — une entrée du lexique de prononciation qui a un AUTEUR
  - `class Manifest(models.Model)` — Store des MANIFESTES (union discriminée par `manifest_kind`) — cf. WAMA_MANIFEST_SPEC.md.
  - `class Library(models.Model)` — Registre des librairies externes — **NÉ de la projection** du manifeste `library`.
  - `class RunOutcome(models.Model)` — Journal des FAITS observés sur un résultat produit — préalable de toute auto-amélioration
  - `class ItemRevision(models.Model)` — Une RÉVISION d'un élément : l'état que lui a donné un résultat produit — marche 8a de
  - `class ProcessRun(models.Model)` — La LIGNE D'EXÉCUTION d'un process : « tel process, pour telle card, dans tel état » —
  - `class BatchSettings(models.Model)` — Les réglages de RÉFÉRENCE d'un lot — ce que la card mère tient (`MODES_QUEUE_UX §5ter`,
  - `class BatchLabel(models.Model)` — Le NOM qu'un utilisateur donne à un lot (2026-10-19, demande de Fabien) — il prime sur le
  - `class ResultEvaluation(models.Model)` — La MESURE d'un résultat contre sa référence — chaînon ⑥ de `WAMA_QUALITE.md §5`, et la matière
  - `class ScheduledAction(ScopedVisibility)` — Une action PROGRAMMÉE — le QUAND du calendrier, la seule table neuve de son plan
  - `class CalendarFeed(models.Model)` — Jeton d'ABONNEMENT au calendrier `.ics` d'un utilisateur (`WAMA_MEMORY §9bis.1`).
  - `class Embedded(models.Model)` — Socle vectoriel commun au souvenir et au fragment. ABSTRAIT — aucune table.
  - `class MemoryItem(Embedded, ScopedVisibility)` — LE SOUVENIR — un fait, un événement ou une procédure. NON re-dérivable.
  - `class RagChunk(Embedded, ScopedVisibility)` — LE FRAGMENT — un morceau d'un document source. RE-DÉRIVABLE : la source fait foi, donc une
  - `class MediaVector(models.Model)` — Le vecteur d'UNE image portée par un élément de file — la recherche de la file par CONTENU
  - `class Conversation(models.Model)` — Un fil de dialogue avec l'assistant, quelle que soit la surface qui le porte.
  - `class ConversationTurn(models.Model)` — Un tour de conversation — ce que l'utilisateur a dit, ou ce que l'assistant a répondu.
  - `class InputProvenance(models.Model)` — D'OÙ vient le fichier d'entrée d'un élément — le LIEN qui manquait.

### Voix de référence (médiathèque) et voix de clonage

LA brique TTS des voix : `speaker_wav_for` (décidée par la CAPACITÉ du moteur, jamais par un nom de moteur, et qui TRANSMET la langue depuis le 2026-09-27), `resolve_speaker_wav` (sa_/ua_/cv_/nom d'avant), `default_voice_for_language` (« Voix par défaut » = la voix de référence de la LANGUE choisie, dans l'ordre du menu ; sans elle c'était un clip anglophone quelle que soit la langue), `describe_voice`, `voice_reference_groups` (optgroups dérivés d'une REQUÊTE sur `SystemAsset(voice)` + `attributes`), `ingest_voice_file` (le seul point d'entrée, ingest initial ET téléchargements). Les voix VIVENT en médiathèque depuis le 2026-09-13 (28 versées, dossier `voice_references/` retiré) ; `tts_service.py` ne résout plus rien. Quatre consommateurs : synthesizer, avatarizer, `voice_options` (menus), assistant

- **Domicile** : `wama/common/tts/voice_refs.py` · **doc** : [docs/construction/exploitation/MEDIA_STORAGE_TIERING.md §9.4](../construction/exploitation/MEDIA_STORAGE_TIERING.md)
- **Module** : Voix de RÉFÉRENCE — la brique COMMUNE : résolution d'un preset en fichier, groupes du menu, libellés, téléchargement. Les voix VIVENT EN MÉDIATHÈQUE (`SystemAsset(asset_type='voice')`, `media_library/system/`) depuis le 2026-09-13 — plan `MEDIA_STORAGE_TIERING §9.4`.
- **API publique** (14) :
  - `attributes_from_voice_id(voice_id: str) -> Dict` — Les `attributes` (nature `voice`) qu'un identifiant de preset PORTE.
  - `voice_reference_groups() -> List[Dict]` — Les optgroups du menu « voix de référence », DÉRIVÉS de la médiathèque :
  - `readable_voice_assets(user)` — Les voix de médiathèque qu'un utilisateur a le DROIT d'employer : les SIENNES **et celles
  - `default_voice_for_language(language: str) -> Optional[str]` — L'id (`sa_<pk>`) de la voix de RÉFÉRENCE d'une langue — ce que « Voix par défaut » veut
  - `class VoiceUnavailable(ValueError)` — La voix CHOISIE (`sa_<id>`, `ua_<id>`) ne peut plus être employée : supprimée, retirée
  - `resolve_speaker_wav(voice_preset: str, user=None, language: str='') -> Optional[str]` — Résout un voice_preset en chemin `speaker_wav` (audio de référence) pour le CLONAGE
  - `is_cloned_voice(voice_preset: str) -> bool` — Cette voix est-elle un CLONAGE (`ua_<id>`, voix de la médiathèque d'un utilisateur) ?
  - `model_supports_cloning(model_key: str) -> Optional[bool]` — Le moteur du modèle `model_key` CLONE-t-il ? — `True`/`False` si quelque chose le dit,
  - `speaker_wav_for(model_key: str, voice_preset: str, user=None, reference_path: Optional[str]=None, language: str='') -> Optional[str]` — LA porte des workers et des aperçus : le `speaker_wav` à passer au service TTS.
  - `ingest_voice_file(name: str, path, *, source_url: str='', license: str='', description: str='', replace: bool=False)` — Verse UN fichier de voix dans la médiathèque comme `SystemAsset(voice)` nommé `name`,
  - `estimate_voice_gender(path) -> str` — Le genre que la voix d'un FICHIER fait entendre ('male' / 'female'), '' si la mesure ne
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
- **API publique** (6) :
  - `primary_ports(app_id) -> set` — Les ports par lesquels arrive l'ENTRÉE PRINCIPALE du nœud (transmise par `create`).
  - `port_argument_name(app_id, port_id, accepted=None)` — L'argument de l'outil où ARRIVE le port `port_id` : celui du MÊME NOM ; à défaut, pour le
  - `unwired_ports(app_id) -> list` — Les ports du nœud que l'outil de l'app ne LIT pas encore — le portage qui reste.
  - `unwired_ports_report(measure=None)` — (ok, détail) — la liste MESURÉE des ports non lus confrontée au budget, dans les deux
  - `port_arguments(app_id, inputs) -> dict` — Les liens reçus sur les ports NON principaux, en arguments nommés de l'outil.
  - `build_generic_runner(app_id)`

### Surface d'outils

Registre central TOOL_REGISTRY : triades add/start/status par app, gating F7 via execute_tool, descriptions dérivées des schémas. Chaque outil DÉCLARE son effet sur sa fonction (`tool_effect` : lecture / écriture / destruction, 2026-10-28) — les outils d'un sous-agent (`sub_agent_tools`) et les annotations MCP en DÉRIVENT

- **Domicile** : `wama/tool_api.py` · **doc** : [docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md](../construction/architecture/WAMA_APP_GENERATION_ROUTE.md)
- **Module** : WAMA Tool API
- **API publique** (93) :
  - `tool_effect(effect: str, *, sub_agent: bool=True, reason: str='')` — Marque l'EFFET d'un outil sur sa fonction. `sub_agent=False` retire une LECTURE de ce qu'un
  - `effect_of(tool_name: str) -> dict | None` — L'effet déclaré d'un outil du registre, None s'il n'en déclare pas (ou n'existe pas).
  - `sub_agent_tools() -> frozenset` — Les outils qu'un sous-agent peut appeler — DÉRIVÉS des marques, jamais recopiés : les
  - `tool_annotations(tool_name: str) -> dict` — Les annotations MCP d'un outil, tirées de sa marque — UNE déclaration, deux lecteurs : notre
  - `list_user_files(user, folder: str='temp') -> dict` — List ALL files in one of the user's folders (any extension).
  - `find_user_files(user, query: str, limit: int=20) -> dict` — Find the user's files BY NAME everywhere the File Manager shows them: the temporary folder,
  - `add_to_anonymizer(user, file_path: str, sam3_prompt: str='', classes: list=None, precision_level: int=50, **params) -> dict` — Copy a file into the anonymizer input queue and create a Media DB entry.
  - `sam3_examples() -> dict` — Return recommended SAM3 text prompt examples.
  - `create_image(user, prompt: str, model: str='hunyuan-image-2.1', width: int=512, height: int=512, steps: int=30, guidance_scale: float=7.5, negative_prompt: str…` — Create a txt2img generation job (status: PENDING).
  - `add_to_enhancer(user, file_path: str, ai_model: str='', denoise: bool=None, blend_factor: float=None, **params) -> dict` — Register a file for enhancement and create the Enhancement DB entry.
  - `add_to_audio_enhancer(user, file_path: str, engine: str='', mode: str='', denoising_strength: float=None, quality: int=None, **params) -> dict` — Register an audio file for speech enhancement.
  - `synthesize_text(user, text: str='', work_file: str='', reference_voice: str='', language: str='fr', tts_model: str=DEFAULT_TTS_MODEL, voice_preset: str='defaul…` — Create a VoiceSynthesis job — from raw text OR from a work file, with an optional
  - `compose_music(user, prompt: str, model: str='musicgen-small', duration: float=10.0, work_score: str=None, work_audio: str=None, **params) -> dict` — Create a Composer generation job (music or SFX) and start it immediately.
  - `add_to_describer(user, file_path: str, output_style: str='detailed', output_language: str='fr', max_length: int=500, **params) -> dict` — Copy a file into the describer queue and create a Description DB entry.
  - `add_to_transcriber(user, file_path: str, backend: str='auto', preprocess_audio: bool=False, hotwords: str='', enable_diarization: bool=True, **params) -> dict` — Copy a file into the transcriber queue and create a Transcript DB entry.
  - `add_to_reader(user, file_path: str, backend: str='auto', mode: str='auto', language: str='', **params) -> dict` — Copy a file into the reader queue and create a ReadingItem DB entry.
  - `convert_file(user, file_path: str, output_format: str='', quality_preset: str='balanced', **params) -> dict` — Queue a file conversion and start it immediately.
  - `list_media_assets(user, asset_type: str='', q: str='') -> dict` — List the user's personal media library assets.
  - `fold_side_panels(user, folded: bool=True) -> dict` — Fold or unfold the two side panels of the page (file explorer on the left, panel on the
  - `open_page(user, page: str) -> dict` — Take the user to a WAMA page — an application ("emmène-moi sur l'Anonymizer", "ouvre la
  - `get_media_asset_url(user, asset_id: int) -> dict` — Get the file URL of a specific media library asset.
  - `inspect_user_file(user, file_path: str) -> dict` — Ask WAMA what it can do with one of the user's files: which app PORT can take it
  - `look_at_image(user, file_path: str, question: str='') -> dict` — Look at ONE of the user's images with a vision model and return what it shows.
  - `add_to_media_library(user, file_path: str, asset_type: str, name: str='', description: str='') -> dict` — Register one of the user's files as a media-library asset with an EXPLICIT role.
  - `search_web(user, query: str, max_results: int=5) -> dict` — Search the public web (no API key) and return result links with snippets.
  - `read_web_page(user, url: str, max_chars: int=8000) -> dict` — Fetch ONE public web page and return its readable text (SSRF-guarded, size-capped).
  - `add_to_avatarizer(user, mode: str='pipeline', text_content: str='', tts_model: str=DEFAULT_TTS_MODEL, language: str='fr', voice_preset: str='default', audio_pa…` — Crée un job de génération d'avatar parlant (vidéo) en attente.
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
  - `prospect_models(user) -> dict` — PROSPECT for new models and record them as PROPOSALS — same verb as the page's
  - `get_install_options(user, model_key: str) -> dict` — INSTALL CHOICES of a proposal — same verb as the options the page shows before « Installer »
  - `install_model(user, model_key: str, force: bool=False, variant_ref: str='', variant_file: str='') -> dict` — INSTALL a model that is already PROPOSED (prospection candidate) or already in the
  - `plan_library_integration(user, dist: str) -> dict` — PLAN for integrating a Python library (pip distribution) — read-only, executes nothing.
  - `plan_model_integration(user, model: str) -> dict` — PLAN for integrating an AI model — read-only, executes nothing.
  - `plan_app_integration(user, target: str) -> dict` — PLAN for integrating a GitHub project as a WAMA app (UI + models + libraries).
  - `memory_recall(user, query: str, k: int=5, include_rag: bool=True, include_memory: bool=True, niveaux: list=None) -> dict` — Cherche dans la mémoire et les documents de l'utilisateur (`WAMA_MEMORY.md`).
  - `search_docs(user, query: str, k: int=5) -> dict` — Search WAMA's OWN documentation — how an app is used, what a setting means, and (for
  - `read_doc(user, doc: str, section: str='') -> dict` — Read one of WAMA's documents: its outline, or one section with its sub-sections.
  - `charger_competence(user, domaine: str, question: str='') -> dict` — Load a specialised competence (role skill) and the matching laboratory context.
  - `ask_claude_code(user, task: str, write: bool=False, timeout: int=300, model: str='') -> dict` — Delegate a DEVELOPMENT task to Claude Code, running on the owner's subscription.
  - `list_my_items(user, app: str='', limite: int=25, statut: str='all', q: str='') -> dict` — List what the user has produced across ALL apps — one vocabulary instead of ten.
  - `get_item_detail(user, app: str, pk: int) -> dict` — Everything known about ONE item, in the canonical schema — exactly what the user sees in
  - `get_item_preview(user, app: str, pk: int, side: str='input', variant: str='', look: bool=False, question: str='') -> dict` — Look at what an item actually holds — the SAME faces the user sees on the card, in the
  - `get_item_result(user, app: str, pk: int, output_format: str='') -> dict` — Read the RESULT of a finished item — the extracted text of an OCR, a transcript, a
  - `delete_item(user, app: str, pk: int) -> dict` — Delete ONE of the user's items from an app queue.
  - `duplicate_item(user, app: str, pk: int) -> dict` — Duplicate ONE of the user's items, so it can be re-run with different settings.
  - `clear_my_queue(user, app: str, confirm: bool=False) -> dict` — Empty the user's WHOLE queue for one app — every item, at once.
  - `add_item_to_media_library(user, app: str, pk: int, asset_type: str='', name: str='', output_format: str='') -> dict` — Keep the RESULT of one of the user's items in their media library, so it can be reused as
  - `add_file_to_rag(user, path: str, level: str='', org_unit: str='') -> dict` — Add one of the user's FILES to their RAG, so `memory_recall` (and the lab context of every
  - `add_item_to_rag(user, app: str, pk: int, level: str='', org_unit: str='') -> dict` — Add the TEXT of one of the user's items (a transcription, an OCR, a description…) to their
  - `list_registries(user) -> dict` — List what WAMA knows how to NAME: its registries (apps, models, backends, functions,
  - `get_my_access(user) -> dict` — What the current user is allowed to do: account tier, business roles, and which apps they
  - `list_my_memories(user, kind: str='', limite: int=25) -> dict` — List what WAMA remembers for this user — facts, events and procedures it has kept.
  - `get_my_calendar(user, start: str='', end: str='', with_instance: bool=False, limit: int=100) -> dict` — Read the user's calendar ("Mon calendrier"): what they ran, what is planned or scheduled,
  - `list_my_notifications(user, unread_only: bool=False, limit: int=20) -> dict` — List the user's notifications in WAMA (the bell): finished or failed tasks, access
  - `list_my_shares(user) -> dict` — What the user shared and what was shared with them ("Mes partages"): for each entry its
  - `list_my_rag(user, level: str='', query: str='', limit: int=50) -> dict` — List the documents the user has entrusted to the RAG ("Mon RAG"): each source, at which
  - `get_my_profile(user) -> dict` — Read the user's profile ("Profil"): identity, preferences (language, interface mode,
  - `remember_fact(user, content: str, kind: str='semantic', subject: str='') -> dict` — Save something the user wants WAMA to remember — a fact, a correction, a preference, the
  - `job_progress(user, family: str, pk) -> dict | None` — Où en est UN élément de `user` lancé depuis l'assistant — la barre de progression de
  - `tool_role(tool_name)` — Rôle d'un outil dans la triade : 'add' | 'start' | 'status', sinon None.
  - `app_id_for_tool(tool_name)` — app_id gardé correspondant à un outil, ou None si l'outil est transverse.
  - `tool_family(tool_name)` — La FAMILLE d'un outil : la clé d'adapter de détail (`DetailRegistry`) des éléments qu'il
  - `items_of_step(tool_name, args, result) -> list` — Les éléments qu'un appel d'outil a CRÉÉS ou LANCÉS, en `(famille, id)` — lus au CONTRAT
  - `tool_descriptions()` — Descriptions de TOUS les outils du registre, dérivées à la volée.
  - `tool_input_schema(tool_name: str) -> dict` — Schéma JSON (`type: object`) des arguments d'un outil du registre — DÉRIVÉ, jamais écrit.
  - `input_schema_for(fn, index=None) -> dict` — Schéma JSON des arguments d'une FONCTION d'outil : signature, complétée par le schéma
  - `primary_arg_name(tool_name: str)` — Nom du 1er paramètre « utile » d'un outil (celui qui suit `user`), ou None.
  - `tool_arg_names(tool_name: str) -> set` — Les arguments NOMMÉS d'un outil (hors `user`, `*args`, `**params`) — dérivés de la signature.
  - `sanitize_tool_args(tool_name: str, args: dict)` — Prépare les arguments d'un appel d'outil : coercition par le SCHÉMA de l'app puis
  - `relay_quality_intent(user, tool_name: str, result: dict) -> dict` — Relaie le curseur Rapide ↔ Qualité de l'ASSISTANT vers l'élément qu'un outil `add_to_<app>`
  - `relay_next_step(tool_name: str, result: dict) -> dict` — Dit au modèle, DANS LE RÉSULTAT, qu'un ajout n'a lancé AUCUN traitement.
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
  - `build_tools_list(names=None) -> str` — Génère la liste des outils (nom + args + description) pour le prompt de l'assistant.
