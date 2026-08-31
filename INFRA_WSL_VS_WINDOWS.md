# INFRA_WSL_VS_WINDOWS.md — Où tourne quoi (WSL2 vs Windows)

> Audit de la topologie de dev/prod actuelle (machine `fbro-20-026`, Ubuntu-24.04 sous WSL2 +
> Windows hôte). Objectif : clarifier ce qui tourne où, **éviter les pièges** (base de données,
> rechargement de code), et **préparer le passage sur serveur de prod full-Linux**.
> Date : 2026-06-25.

## TL;DR
- **Tout le runtime applicatif tourne dans WSL2 (Linux).** Windows ne sert que d'**hôte** : GPU
  physique, **Apache en frontal** (reverse proxy), et **Ollama**.
- **Le code, AI-models et media vivent sur `D:\` (Windows) = `/mnt/d/...` (WSL2)** via drvfs →
  **partagés**. Une édition de fichier est vue immédiatement par le serveur WSL2.
- **⚠️ DEUX serveurs PostgreSQL, mais UNE SEULE base fait foi** : `wama_db` **dans WSL2**. Le
  serveur Windows existe encore mais est **orphelin** — plus rien ne le lit (voir « Une seule base
  fait foi », 2026-07-30). Depuis **2026-08-10** leurs ports sont **disjoints** :
  `localhost:5432` = WSL2, `localhost:5433` = Windows ; un `manage.py` lancé de n'importe quel
  côté vise donc la même base. Les **seeds** sont automatisés au démarrage (`start_wama_*.sh`).
- **Piège n°1** : changer du **code Python** ne suffit pas — il faut **redémarrer le process WSL2**
  (gunicorn / runserver) pour qu'il soit pris en compte. (Les **templates** sont relus à chaud en
  DEBUG ; les **migrations/seeds** touchent la base partagée quel que soit le côté.)
- **Piège n°2** : en DEBUG, le statique est servi depuis `wama/<app>/static/` (finders), pas depuis
  `staticfiles/`. Les copies dans `staticfiles/` ne comptent **qu'en prod** (collectstatic).

## Carte des services

| Composant | Tourne dans | Détail | Endpoint |
|-----------|-------------|--------|----------|
| **Django** (dev) | WSL2 | `runserver 0.0.0.0:8000` (`start_wama_dev.sh`) | :8000 |
| **Django** (prod) | WSL2 | `gunicorn wama.wsgi` 4× `gthread`×2 (`gunicorn_conf.py`, `start_wama_prod.sh`) | :8000 |
| **PostgreSQL 16** | WSL2 | `sudo service postgresql start` ; `wama_db` / `wama_user` — **LA base** | 127.0.0.1:5432 (dans WSL2) ; **`localhost:5432` depuis Windows** via le relais `wslrelay` |
| **PostgreSQL 17** | **Windows** | service `postgresql-x64-17`, **orphelin** (aucun lecteur) ; déplacé sur 5433 le 2026-08-10 pour libérer le port de l'hôte | 127.0.0.1:**5433** (boucle locale seule) |
| **Redis** | WSL2 | `redis-server --daemonize` ; DB0=broker Celery, DB1=cache+résultats | 127.0.0.1:6379 |
| **Celery (GPU)** | WSL2 | worker `--pool=solo --queues=gpu` `gpu@%h` (sérialise la VRAM) | — |
| **Celery (default)** | WSL2 | worker prefork `--autoscale=4,1 --queues=default,celery` `default@%h` | — |
| **Celery beat** | WSL2 | planificateur périodique | — |
| **TTS service** | WSL2 | `uvicorn tts_service:app --host 0.0.0.0` (précharge XTTS v2) | :8001 |
| **GPU / CUDA** | Windows (HW) → WSL2 | RTX 4090 physique sur Windows, **exposée à WSL2** (passthrough GPU WSL2) ; torch CUDA tourne **dans** WSL2 | — |
| **Apache (frontal)** | **Windows** | reverse proxy public → gunicorn WSL2 via **netsh portproxy** `0.0.0.0:8000 → WSL2_IP:8000` | :80/:443 |
| **Ollama** | **Windows** | « Ollama runs on Windows » ; WSL2 le joint via l'IP de la **default gateway** (`OLLAMA_HOST` auto, surchargeable ; `.env` pointe une IP LAN UGE) | host:11434 |
| **CIFS / montages** | WSL2 | remontés au démarrage via l'API `filemanager/api/mounts/remount/` | — |
| **Tooling dev (Claude Code)** | Windows | venv_win ; atteint la base WSL2 via `settings._resolve_db_host()` | — |

## Stockage partagé (D: ↔ /mnt/d)
- `BASE_DIR` = `D:\WAMA\web-app-for-media-automation` (Windows) = `/mnt/d/WAMA/web-app-for-media-automation` (WSL2).
- `AI_MODELS_DIR = BASE_DIR/AI-models`, `MEDIA_ROOT = BASE_DIR/media`, code, `staticfiles/` : tous sur D:.
- Conséquence : **éditions de fichiers immédiatement partagées** ; seules les **bases/process** divergent par côté.

## Atteindre WSL2 depuis une session Windows
```bash
wsl.exe -e bash -lc "hostname; <commande>"
# ex. compter des lignes dans la vraie base :
wsl.exe -e bash -lc "PGPASSWORD=*** psql -h 127.0.0.1 -U wama_user -d wama_db -t -c 'SELECT count(*) FROM media_library_promptkeyword;'"
```

## Implications pour le passage en prod full-Linux
1. **Supprime le split Windows/WSL2** → un seul hôte Linux. Plus de **netsh portproxy** ni de
   double-localhost : Apache (ou **nginx**) en frontal natif → gunicorn `:8000`.
2. **Chemins** : les scripts codent `/mnt/d/...` en dur → remplacer par des chemins natifs (ext4).
   Gain de perf (drvfs lent) et fin des soucis de permissions/casse.
3. **GPU** : CUDA natif, fin du passthrough WSL2.
4. **Ollama** : décider **local** (même hôte) vs **remote** (l'IP LAN du `.env`). Mettre `OLLAMA_HOST`
   dans l'environnement systemd plutôt que de dériver la gateway WSL2.
5. **Services** : convertir `start_wama_*.sh` en **units systemd** (postgresql, redis, gunicorn,
   celery-gpu, celery-default, celery-beat, tts) avec dépendances et `Restart=on-failure`.
6. **Static** : `collectstatic` + service par nginx/Apache (le `staticfiles/` prend alors tout son sens).
   ⚠ C'est **lié au point 8** : aujourd'hui `urls.py:64` conditionne le service des statiques à
   `settings.DEBUG`. Le frontal doit servir `/static/` **avant** que `DEBUG` passe à `False`,
   sinon tout le CSS/JS tombe en 404.
7. **Secrets** : ✅ FAIT (2026-07-23) — mot de passe DB, `SECRET_KEY`, proxy sortis de `settings.py`
   vers l'environnement/`.env` (voir section ci-dessous). En prod : injecter via systemd
   `EnvironmentFile=` / Docker secrets / Vault plutôt qu'un `.env` (le code ne change pas).
8. **`DEBUG = False`** (`settings.py:20`, en dur aujourd'hui, aucune surcharge par env) — à traiter
   **ici et pas avant** : c'est le passage en prod qui apporte le frontal servant `/static/`, donc
   le préalable du point 6. Enjeu réel : en `DEBUG`, chaque 500 renvoie au navigateur les extraits
   de source et les **variables locales** de chaque frame. Ordre : frontal `/static/` → vérifier
   l'UI → `DEBUG = False`. Le journal `logs/django-errors.log` (posé le 2026-08-24) est
   **indépendant de `DEBUG`** : il continuera de recevoir les tracebacks après la bascule.
9. **Sort d'Apache/Windows — DÉCIDÉ le 2026-08-24 : on tranche au passage en prod, pas avant.**
   ⚠ **Correction du 24/08 au soir : les 502 ne sont PAS soldés** (4,625 % après correctif contre
   4,336 % avant — cf. le démenti au § plus bas). Ils restent une nuisance mesurée, pas un
   bloquant pour la décision de reporter. Ce n'est
   **pas** un résidu au sens de la base Postgres Windows : il est sur le chemin de tout le trafic
   :80 — mesuré, y compris une session navigateur en direct. Ce qu'il faudra reprendre côté nginx
   natif : l'`Alias /media/` (**72,69 Go / 44 % des octets** servis hors gunicorn), le port 80, la
   page d'attente 502. Le résidu réel, lui, est `mod_wsgi` (chargé, aucun `WSGIScriptAlias`) : il
   disparaît de fait avec l'hôte Windows.

## Secrets & configuration (`.env`)  — externalisation 2026-07-23
- **Config env-driven** : `SECRET_KEY`, mot de passe DB, `PROXY`/`HTTP_PROXY`, LDAP… lus via
  `os.environ.get(...)` dans `settings.py`. Plus AUCUN secret en dur. Valeurs réelles dans `.env`
  (gitignoré, **jamais commité**) ; modèle sans secret = `.env.example` (commité).
- **Contrôle continu** : `check_secret_leaks` (gitleaks) passe sur le dépôt complet et sort à
  **0 fuite** ; un hook `pre-commit` bloque en amont. Rotation reportée à la prod (assumé :
  DB en `127.0.0.1`, infra interne université, pas de données sensibles).
- **Rotation à la demande** : `python manage.py rotate_secrets` (voir `wama/common/management/commands/`).
  - `--all --also-wsl` = rote clé Django + mot de passe DB, applique l'`ALTER USER` à la base **dev
    Windows** (courante) ET à la base **live WSL2** (via `wsl.exe`), met à jour `.env` — les DEUX bases
    en une commande (cf. règle des deux Postgres distincts plus haut). Lancer **depuis Windows**.
    ⚠ Depuis 2026-07-30, la « base courante » vue depuis Windows EST celle de WSL2 : l'étape
    `--also-wsl` se saute alors d'elle-même (rejouer l'`ALTER USER` échouerait, il
    s'authentifierait avec l'ancien mot de passe déjà remplacé).
  - Vérifie une nouvelle connexion + rollback auto si KO ; l'ancienne `SECRET_KEY` bascule dans
    `DJANGO_SECRET_KEY_FALLBACKS` (aucune session invalidée) ; journal `logs/secret_rotation.log`.
  - Reste optionnel : hostname interne `vrlescot` + IP gateway WSL `172.29.240.1` encore en clair
    dans quelques docs/scripts (divulgation d'infra mineure, non critique).

## ⚠ Une seule base fait foi (2026-07-30)

`127.0.0.1` **ne désigne pas la même machine des deux côtés** : sous WSL2 c'est la base de
l'application, depuis PowerShell c'est le service `postgresql-x64-17` de Windows — **une base
différente**. Un `manage.py migrate` lancé depuis Windows semblait donc réussir tout en migrant
une base que personne ne lit (mesuré : 225 migrations côté Windows contre 228 côté WSL2).

`wama/settings.py::_resolve_db_host()` lève l'ambiguïté : sous Windows, une adresse de
**bouclage** ne peut pas désigner la base de l'app → l'IP de WSL2 est résolue dynamiquement
(`wsl.exe hostname -I` ; jamais figée, elle change à chaque redémarrage de WSL). Un hôte
explicite **non loopback** reste prioritaire. `.env` est PARTAGÉ par les deux côtés et y pose
`WAMA_DB_HOST=127.0.0.1` : il ne peut donc pas porter cette distinction.

**La base Postgres de Windows est désormais orpheline** — plus rien ne la lit. Comparaison des
deux avant bascule : ses seules lignes exclusives sont 48 entrées périmées du catalogue
`AIModel` (openjourney-v4, realistic-vision-v5, cogvideox-2b, wan-*, logo-redmond-v2… — soit
exactement les modèles listés « Supprimés (obsolètes) » dans `CLAUDE.md`) et le seed
`anonymizer_globalsettings.precision_level`. WSL2, lui, a 3 entrées que Windows n'a pas : c'est
le plus récent. **Aucune donnée utilisateur exclusive côté Windows.**

## ⚠ Ports disjoints : `localhost:5432` = WSL2, `5433` = Windows (2026-08-10)

La section ci-dessus établissait *quelle* base fait foi ; celle-ci règle *comment on l'atteint
depuis Windows* — c'est ce qui manquait, et ce qui rendait **pgAdmin inutilisable depuis des mois**.

**Cause.** Le Postgres de Windows écoutait sur `0.0.0.0:5432` : il **squattait le port de l'hôte**.
Or la redirection localhost de WSL2 ne peut s'installer que si le port est **libre côté Windows**.
Résultat : depuis Windows, `localhost:5432` atterrissait **toujours** sur la base Windows orpheline,
jamais sur `wama_db` — un échec silencieux, puisque la connexion *réussissait*, mais sur la
mauvaise base.

**Correctif.** Serveur Windows déplacé sur **5433** (`postgresql.conf`, sauvegarde
`postgresql.conf.bak-avant-5433`). Le relais **`wslrelay`** prend alors `127.0.0.1:5432` et
`::1:5432` **automatiquement, au `bind()`** de postgres WSL2 — donc à chaque démarrage, sans
intervention. Contrôle d'un coup d'œil depuis Windows :

```powershell
Get-NetTCPConnection -LocalPort 5432,5433 -State Listen |
  Select-Object LocalAddress,LocalPort,@{n='Proc';e={(Get-Process -Id $_.OwningProcess).ProcessName}}
# attendu : 5432 -> wslrelay  (et NON postgres) ; 5433 -> postgres
```

**Ce que ça change.**
- `localhost:5432` est une adresse **stable** vers la vraie base : la préférer désormais à l'IP de
  la VM, qui change à chaque redémarrage de WSL. C'est la seule adresse à mettre dans pgAdmin,
  DBeaver ou tout client Windows.
- Le repli `127.0.0.1` de `_resolve_db_host()` (`wama/settings.py`), qualifié de « trompeur » quand
  la garde a été écrite, désigne **maintenant la bonne base**. La garde reste utile — elle évite de
  dépendre du relais — mais son échec n'est plus silencieusement faux.
- **Prérequis** : postgres WSL2 doit tourner (bloc `service postgresql start` de
  `start_wama_prod.sh`), sinon *rien* n'écoute sur
  5432. Un « connection refused » signifie donc « WSL2 dort », jamais « mauvaise base » — l'échec
  est enfin franc au lieu d'être trompeur.

**Résidus nettoyés côté Windows** (tentatives antérieures, sauvegardes `.bak-2026-08-10`) :
`listen_addresses` `'*'` → `'localhost'`, et retrait d'une ligne `host all all 172.16.0.0/12` de
`pg_hba.conf` — elle ouvrait l'accès dans le **mauvais sens** (WSL2 → Windows) alors que le besoin
était l'inverse. Le serveur Windows n'écoute plus que sur la boucle locale.

**Clients Windows — aucune contrainte de version.** pgAdmin 4 v9.15 et les binaires 17.10 attaquent
sans réserve le serveur 16.10 : la règle PostgreSQL est *client ≥ serveur*, et c'est le bon sens
(`pg_dump` 17 vers un serveur 16 est la configuration recommandée). **Ne pas migrer WSL2 en 17** :
`pg_upgradecluster` sur la base de production, pour zéro bénéfice.

pgAdmin ne contient volontairement qu'**une seule entrée**, « WAMA - base applicative (WSL2) » sur
`localhost:5432`. Les deux serveurs y avaient d'abord été enregistrés et *colorisés* pour éviter
toute confusion ; retirer le serveur Windows — orphelin — supprime la confusion **à la racine**
plutôt que de la signaler, et rend du même coup la couleur inutile (choix de Fabien, 2026-08-10).
Le serveur Windows reste joignable sur `localhost:5433` et se réenregistre en trente secondes si
besoin : « Remove server » ne supprime que l'enregistrement pgAdmin, jamais la base ni le service.
Configuration dans `%APPDATA%\pgAdmin\pgadmin4.db` (SQLite, table `server`), lisible avec le Python
embarqué de pgAdmin — le seul interpréteur Python côté Windows sur cette machine.

## RAM hôte & plafond WSL2 (`.wslconfig`) — MAJ 2026-07-29

**Hôte : 64 Go** (2× Samsung `M378A4G43AB2-CWE` 32 Go, détectées **3200 MT/s**, une par canal
— `ChannelA-DIMM1` / `ChannelB-DIMM1`, dual channel à la fréquence nominale).
Précédemment 32 Go. **Plafond WSL2 : 48 Go**, réserve Windows 16 Go, `swap=8GB`.

- Générateur : **`scripts/set_wslconfig.ps1`** (à relancer côté **hôte** après tout changement de
  barrettes). Calcule depuis la RAM **physique** (somme des barrettes — `TotalVisibleMemorySize`
  retranche la réservation matérielle et donne 63 au lieu de 64). Options `-DryRun`, `-MemoryGB`,
  `-ReserveGB`, `-SwapGB` ; sauvegarde `.bak` ; écriture **UTF-8 SANS BOM** (WSL ne parse pas un
  `.wslconfig` commençant par un BOM).
- ⚠ **Ne PAS dimensionner la réserve sur la mémoire ENGAGÉE (commit) de Windows** : le commit est
  adossable au fichier d'échange et dépasse normalement le résident (mesuré 21,9 Go engagés alors
  que la machine tournait bien avec 16 Go physiques côté Windows sur la config 32 Go). C'est le
  **résident** qui compte. Plancher absolu : 12 Go.
- `memory=` est un **PLAFOND, pas une réservation** : vmmem ne prend que ce que l'invité utilise.
- `swap=8GB` conservé volontairement : touché seulement si l'invité dépasse `memory=`, il amortit
  alors au lieu d'un OOM-kill sec en plein chargement de modèle. Un `.vhdx` inutilisé ne coûte rien.
- **Prise en compte au prochain `wsl.exe --shutdown` uniquement.** Ne PAS tenter de l'automatiser
  depuis `start_wama_*.sh` : `.wslconfig` est lu par l'hôte AVANT le boot de la VM, alors que les
  scripts de démarrage s'exécutent DANS WSL.
- Vérification côté invité : `free -g` (48 Go → `Mem: 47` après surcoût noyau).

## Journaux — on DÉCALE, on ne VIDE pas (2026-07-29)

Écraser un journal à chaque relance détruit la trace qui explique le crash qui vient d'avoir lieu.
Le 29/07, c'est `celery-gpu.log` (append) qui a identifié la tâche imager #42 responsable de
4 kernel panics WSL2 — avec un `>` il aurait fallu **reproduire** le crash.

- Brique : `wama/common/utils/log_rotation.py` + `manage.py rotate_logs`, appelé en tête des deux
  scripts de démarrage, **services arrêtés** (renommer un fichier ouvert ne détache pas le
  descripteur : le process continuerait d'écrire dans le `.1`).
- `X.log` → `X.log.1` → … → `X.log.3`. **Le journal courant garde toujours le même nom** (on
  renomme les anciens) → pas de fichier à retrouver après un redémarrage. Suivi en continu :
  `tail -F` (majuscule, rouvre par nom), pas `tail -f`.
- Cible = **liste explicite** `RUNTIME_LOGS`, pas `*.log` : un balayage glob ferait sortir les
  journaux d'archive à tirage unique (`download_*.log`, `poc_*`) de la fenêtre et les supprimerait
  au bout de 3 relances.
- `wama-console.log` **exclu** : `console_utils.py` le fait déjà tourner par taille
  (RotatingFileHandler 5 Mo ×3) avec le **même** nommage `.1/.2/.3`.
- `[ModelSync]` cloisonné dans `logs/model-sync.log` (`propagate=False`) : il pesait **71 %** de
  `celery-default.log` (138 328 lignes / 194 328). Après portage : 0 occurrence, fichier 28 Mo → 9,5 Ko.

## ⚠ Apache/Windows n'est PAS un résidu — et la course qui produisait 58 500 × 502 (2026-08-24)

**La question posée** (Fabien, 24/08) : pourquoi garder Apache côté Windows alors que WAMA tourne
dans WSL2 ? Elle est légitime — la réponse est **non, ce n'est pas un résidu**, mais une pièce
l'est. Mesuré, pas supposé.

### La chaîne réelle (deux relais, pas un)

```
client → Apache:80 (Windows) → 127.0.0.1:8000 → netsh portproxy (svchost/IP Helper)
                                              → 172.21.107.186:8000 → gunicorn (WSL2)
```

Le `127.0.0.1:8000` que vise `ProxyPass` **n'est pas** le relais natif `wslrelay` de WSL2 : c'est la
règle `netsh portproxy 0.0.0.0:8000 → WSL2_IP:8000` posée par `start_wama_prod.sh:99-105`
(vérifié 24/08 : le `LISTENING` sur `:8000` est un `svchost`, pas `wslrelay`). Le coût loopback
n'est donc pas un choix d'Apache — il est **intrinsèque au NAT de WSL2**, et il resterait
identique sans Apache.

### Ce qui rend Apache porteur (chiffres sur les 6,1 M lignes de `wama-access.log`)

| Fonction | Preuve |
|---|---|
| **Point d'entrée LAN** | **17 clients distincts** hors localhost (137.121.x = réseau UGE, 10.0.16.x), **261 000 requêtes** ; le plus gros à 218 603. Windows 10 19045 → **pas de réseau miroir WSL2** (Win11 22H2+ seulement) : sans frontal, l'accès LAN reposerait sur la seule règle `netsh`, à réémettre à chaque redémarrage WSL2 (l'IP change) |
| **Service direct de `/media/`** | `Alias /media/` → `D:/…/media/` : **72,69 Go sur 23 744 requêtes**, soit **44 % des octets servis**, qui ne touchent **jamais** gunicorn. Les rapatrier dans Django saturerait ses 8 slots (4 workers × 2 threads) avec des vidéos |
| **Port 80** | URL sans `:8000` |

### Ce qui EST un résidu

`httpd.conf:543-548` charge `mod_wsgi` (Python 3.11 Windows + `WSGIPythonHome` sur `venv/`) alors
qu'**aucun `WSGIScriptAlias` n'existe dans le fichier**. C'est l'ancien mode d'exécution, d'avant le
passage en reverse proxy. Chargé à chaque démarrage, jamais appelé. À retirer — sans urgence, mais
c'est bien lui la trace du « avant ».

### La course qui remplissait le journal

`wama-error.log` ne contenait que **deux** erreurs, toujours par paire : `AH01102` (58 504) →
`AH00898` (31 372), du 01/04 au 23/08/2026. **97,6 % portaient `OS 10054` (WSAECONNRESET) à la
lecture de la status line** — donc RST reçu *avant le moindre octet de réponse*.

- **Cause** : réutilisation d'une connexion du pool `mod_proxy_http` que l'autre bout avait déjà
  démontée — gunicorn (`keepalive = 5`, `gunicorn_conf.py:16`) et/ou le relais IP Helper.
- **Ampleur** : recoupé avec l'access log, avril→août = **58 611 réponses 502**, soit ~1 pour 1 avec
  les `AH01102`. **Chaque ligne du journal était un échec vu par un navigateur.** Sur les 500 000
  dernières requêtes : **4,3 % de 502**.
- **Cibles** : exclusivement les endpoints de *polling* (`system-stats` 9 612, `console` 9 534,
  les `global_progress`) — ceux qui rouvrent une connexion en permanence.
- **Correctif** (`httpd.conf`, vhost `wama.local`) : `disablereuse=On` sur le `ProxyPass`. Pas de
  pool → pas de connexion morte réutilisée. Préféré à `ttl=` qui n'aurait que **réduit** la fenêtre,
  alors que le relais peut lâcher à tout instant. Coût : un handshake par requête, à ~0,25 req/s.
### ⚠⚠ DÉMENTI le 2026-08-24 au soir — `disablereuse=On` N'A RIEN CHANGÉ, et ma « vérification » ne prouvait rien

**Mesuré 15 h après la pose du correctif, journaux vidés donc fenêtre propre :**

| | 502 / requêtes | taux |
|---|---|---|
| AVANT (13/07→23/08) | 21 680 / 500 000 | **4,336 %** |
| APRÈS `disablereuse=On` (24/08 01:59→17:47) | 567 / 12 260 | **4,625 %** |

Identique, très légèrement pire. **Le diagnostic « course sur le pool de connexions » est donc
FAUX** : `disablereuse=On` supprime le pool, et les `AH01102`/`WSAECONNRESET` continuent au même
taux. Un RST reçu avant le premier octet sur une connexion **neuve** ne peut pas être une
connexion périmée réutilisée — c'est l'autre bout qui coupe une connexion vivante.

⚠⚠ **La leçon porte sur MA vérification, pas sur le correctif.** J'avais annoncé « vérifié » sur
**115 requêtes en 5 minutes** — dont 6 espacées de 7 s censées reproduire le motif. À 4,3 %, 115
requêtes donnent ~5 échecs attendus ; en voir 0 avait ~0,6 % de probabilité, ce que j'ai présenté
comme une preuve. C'était une **fenêtre trop courte sur un phénomène à faible taux** : le test ne
pouvait pas distinguer « corrigé » de « pas de charge pendant 5 minutes ». Un taux ne se vérifie
que sur un volume du même ordre que celui qui l'a établi. Même famille que
« un contrôle vert sur une surface ne dit rien d'une autre ».

**Ce qui reste vrai** (mesuré, indépendant du correctif) : le comptage des erreurs, leur nature
(97,6 % WSAECONNRESET), la concentration sur les endpoints de *polling*, et l'équivalence
`AH01102` ≈ nombre de 502 servis. **Ce qui tombe** : la cause, et donc le correctif.

**Pistes NON explorées, dans l'ordre de vraisemblance** (rien n'est mesuré, ne pas les citer
comme des faits) :
1. **Recyclage des workers** — `max_requests = 1000` + `max_requests_jitter = 50` : 52 `SIGTERM`
   en 36 h dans `gunicorn-error.log`. Un worker qui sort peut réinitialiser ce qu'il tient.
2. **Saturation** — 4 workers × 2 threads = **8 requêtes concurrentes** seulement, face à un
   polling permanent. Le `backlog` du socket est à 2048, donc ce n'est pas lui ; mais la file
   applicative, elle, n'a que 8 places.
3. **Le relais `netsh portproxy`** (IP Helper, userland) sur le chemin.

**Test le moins cher pour trancher** : comparer, sur une MÊME fenêtre, le nombre de requêtes vues
par Apache et par `logs/gunicorn-access.log`. Si gunicorn ne les a jamais vues → la connexion meurt
avant lui (relais, backlog) ; s'il les a servies en 200 → c'est Apache qui perd la réponse.
⚠ Piège rencontré : `rotate_logs` tourne les journaux gunicorn à **chaque démarrage** — vérifier
que la fenêtre comparée est bien couverte par le fichier lu (`.1`, `.2`…), sinon on compare à du vide.

**`disablereuse=On` RETIRÉ le 24/08 au soir** (décision de Fabien) : il ne corrigeait rien et
coûtait un handshake par requête. `ProxyPass` est revenu à `retry=0 timeout=130`. La **rotation**
des journaux Apache, elle, reste pleinement justifiée — c'est elle qui a rendu cette mesure possible.

**`mod_wsgi` RETIRÉ le 24/08 au soir** dans le même geste (`LoadFile python311.dll`,
`LoadModule wsgi_module`, `WSGIPythonHome`, `WSGIApplicationGroup`) : chargé à chaque démarrage
sans aucun `WSGIScriptAlias`. Contrôlé après coup : `httpd -M` ne liste plus aucun module wsgi,
les deux modules proxy sont conservés, `httpd -t` = Syntax OK, WAMA répond 200.
Sauvegarde : `httpd.conf.bak-20260824-soir`.

- **Non couvert par ce correctif** : les 500 (exceptions Django → `logs/gunicorn-error.log`, côté
  WSL2), les `10060`/`20014` (gunicorn indisponible ou saturé), et le **volume de polling** lui-même
  — 132 461 `system-stats` + 63 548 `console` en 6 semaines.

### Journaux Apache — même politique que le reste (cf. § ci-dessus)

Ils n'étaient **jamais** tournés : `wama-access.log` avait atteint **614 Mo**. Désormais pipés dans
`rotatelogs -n 10 … 86400` (10 fichiers glissants quotidiens, le courant garde son nom — même
convention que `rotate_logs`). Les deux fichiers accumulés ont été **vidés** le 24/08 sans archive :
la cause était identifiée et corrigée, les erreurs restantes se re-signaleront d'elles-mêmes.

## ⚠ Chaque crash hôte FUITE jusqu'à 8 Go dans `%TEMP%` (mesuré le 2026-08-25)

**Mécanisme** : `.wslconfig` déclare `swap=8GB`. À chaque démarrage, WSL2 crée un `swap.vhdx` dans
un dossier à nom GUID sous `%TEMP%`. Un `wsl --shutdown` **propre** le supprime ; un **crash hôte le
laisse derrière**. Les crashs de la série d'août avaient ainsi accumulé **26,10 Go** en 6 fichiers
orphelins — un par mort, datés à la minute des Kernel-Power 41 (23/08 21:49, 24/08 16:46,
24/08 18:10 = le crash de 18:09…).

- **Identifier le vivant AVANT de supprimer** : le seul critère fiable est le **verrou**, pas la date
  ni la taille (le swap vivant faisait 36 Mo, un orphelin 8 Go). Ouvrir le fichier en
  `ReadWrite`/`None` : s'il lève, il est en service.
  Script rejouable : `<scratchpad>/swap_live.ps1` puis `cleanup.ps1` (session du 25/08).
- **Ne PAS purger `%TEMP%` en bloc** : le swap vivant, des DLL en cours d'usage et le scratchpad de
  l'agent y sont. Le nettoyage doit être ciblé et revérifier le verrou juste avant chaque `Remove-Item`.
- Compacter `ext4.vhdx` ne sert à rien ici : **48 Go réellement utilisés dans WSL2 pour 49,62 Go
  alloués** (mesuré) — aucun gain à attendre.

### Inventaire disque du 2026-08-25 (pour décisions ultérieures)

| Poste | Taille | Statut |
|---|---|---|
| `swap.vhdx` orphelins + cache installeur VS + DLL fuitées | **29,39 Go** | ✅ **libérés le 25/08** |
| `hiberfil.sys` | **38,37 Go** | ✅ **libérés le 25/08** (`powercfg /h off`, décision de Fabien ; désactive aussi le Démarrage rapide, qui cohabite mal avec WSL2 — S3 reste disponible) |
| Clichés VSS sur **D:** | plafond ramené à **10 Go** (était 69,3, dont 40,8 utilisés au 25/08) | ✅ **réglé — plafond confirmé à 10 Go par Fabien le 28/08** (`vssadmin resize shadowstorage /for=D: /on=D: /maxsize=10GB`) ; les clichés (1/4 h + 1 par redémarrage) tournent désormais sous ce plafond |
| `hunyuan-image-2.1` (`AI-models/models/diffusion/hunyuan/`) | **49,48 Go** | ⏳ **non traité** — déjà en attente de retrait depuis la revue de licences du 21/08 (**interdit UE**) ; ⚠ encore déclaré ACTIF dans `CLAUDE.md` et le catalogue → le retrait doit toucher le CODE aussi, pas seulement le disque |
| Ollama (`D:\.ollama`) | **107,65 Go** | ⏳ **non traité** — plus gros poste isolé de D:. ⚠ `AI-models/models/llm/ollama` en est un **SymbolicLink**, pas une copie : compté deux fois dans les scans, occupé une seule fois |
| ~112 Go sur D: | — | ⚠ **non expliqués** par l'inventaire des dossiers ; probablement des répertoires aux ACL restrictives, à remesurer en session élevée |

**État après nettoyage** : C: **92,23 Go libres (26,3 %)** ; D: **22,77 Go (4,2 %) — toujours critique**,
aucun poste lié aux crashs n'y pesant : les leviers de D: sont tous des arbitrages (tableau ci-dessus).

### 2026-08-29 — où étaient passés ~19 Go de C: (92,2 → 73,2 libres), et pourquoi une suppression « ne rend rien »

Arithmétique mesurée (somme des dossiers racine accessibles **243,90 Go** vs utilisé réel
**278,69 Go**) : **34,79 Go invisibles aux fichiers** = stockage **VSS de C:** + inaccessibles —
≈ le plafond VSS par défaut (10 % de 350 Go). C: n'a jamais été plafonné, contrairement à D:
(10 Go, 28/08) ; chaque reboot de crash ajoute un cliché, et les clichés **retiennent les blocs
des fichiers supprimés** : les 11,5 Go de swap orphelins purgés le 28/08 n'ont rendu que
+0,3 Go visibles. Le reste du delta : swap vivant regonflé à ses 8 Go configurés (36 Mo au
25/08) + `ext4.vhdx` 49,62 → 51,93 Go. Postes anciens notables (pas le delta, mais des
leviers) : `NVIDIA App\UpdateFramework` **11,00 Go** (modif 2025-05) · `C:\Windows\Installer`
9,20 Go · pagefile.sys 14 Go.
⚠ Piège de scan récidivant : `C:\Users\fmoreau\.ollama` est un **SymbolicLink → `D:\.ollama`**
(66,59 Go comptés à tort « sur C: » en le scannant directement) — même famille que le lien
`AI-models/models/llm/ollama` du tableau ci-dessus.

**Le replafonnement VSS de C: est BLOQUÉ par SentinelOne** (mesuré 29/08 : `vssadmin resize
shadowstorage /for=C: /on=C: /maxsize=10GB` en console admin → « Erreur détectée dans le
fournisseur », journal Application **VSS 12289, DeviceIoControl 0x80070005 Accès refusé** —
la protection anti-ransomware des clichés intercepte le geste sous l'OS ; le resize de **D:**
était passé, lui, le 28/08). Voie de sortie = **le service info** (console S1 : mode maintenance
ou purge par eux), même canal que la quarantaine du 26/08. En attendant : le poste est **BORNÉ
au plafond (~35 Go = 10 % du volume)** — il ne grossira pas au-delà, chaque cliché nouveau
purge un ancien ; ce n'est pas une fuite, c'est un plafond qu'on ne peut pas baisser nous-mêmes.

## ⚠⚠ Les crashs hôte ne sont PAS « au repos » — le déclencheur est une passe LLM de WAMA (2026-08-26)

> Six crashs en 48 h. La prémisse de travail était « au repos, sans raison apparente ». **Elle est
> fausse**, et c'est l'instrumentation croisée `rails.csv` × `hwlog` × `celery-gpu.log` qui l'a montré.

### Ce que le crash du 26/08 13:35 a donné

`logs/hwlog/rails_20260826_1335_crash.csv` — 42 883 échantillons, 24 h, arrêt à **13:35:08**.

⚠ **Le Kernel-Power 41 horodate le REDÉMARRAGE, pas la mort** (ici 13:35:50, soit 42 s après le
dernier échantillon). Ne pas lire l'écart comme une fenêtre perdue : le dernier échantillon **est**
l'instant de la coupure. Vérifiable sur les 3 fichiers de crash — l'écart y est toujours de 40-70 s.

**Les rails n'incriminent rien** : tous dans la tolérance ATX de bout en bout.

⚠ **Piège évité de justesse** : les minima globaux des trois rails 12 V tombent tous sur les
**2 derniers échantillons** (0,002 % du run) — signal spectaculaire, et faux. La contre-épreuve sur
les fichiers antérieurs le démolit : le 23/08 et le 24/08 sont descendus **plus bas**
(12VHPWR 12,011 et 12,005 V contre 12,034 le 26/08) **en pleine journée, sans crash**. Un creux de
cette profondeur ne suffit donc pas à tuer la machine. **Toujours chercher si le motif "remarquable"
s'est déjà produit sans conséquence** — c'est ce test-là qui tranche, pas la rareté dans le run courant.
À 2 s d'échantillonnage la sonde n'innocente pas l'alimentation pour autant : un transitoire
microseconde lui est invisible.

### Ce que le `hwlog` dit, lui

| | avant-dernier | **dernier** | repos médian |
|---|---|---|---|
| `gpu_w` | 75,1 W | **293,4 W** | 21,1 W |
| `gpu_util_pct` | 9 % | **90 %** | ~2 % |
| `gpu_clock_mhz` | 2595 | **2730** | 210 |
| `gpu_mem_mb` | 12 205 | **15 382** | ~4 900 |

Et `logs/celery-gpu.log.1` nomme la charge à la seconde près :

```
13:34:45  Task model_manager.assess_proposed reçue
13:34:46  [model_selector] ollama → ollama:gemma4:12b (vram_gb=7.6, budget=16.0)
13:35:05  POST http://172.21.96.1:11434/api/chat  200 OK
13:35:08  POST http://172.21.96.1:11434/api/chat  200 OK   ← dernière ligne, = dernier échantillon rails
```

C'est la **passe d'évaluation LLM de la prospection**, qui tape l'**Ollama hôte** (`172.21.96.1:11434`)
— même GPU physique. Elle **s'auto-réenfile** (`model_manager/tasks.py`, `apply_async(countdown=5)` —
recalé 27/08 : l'ancre `273` a dérivé vers `~316`) tant qu'il
reste des candidats. **Personne ne la lance** : d'où l'impression de crash « au repos ».

### Le motif se répète (6 derniers crashs)

| crash | dernier échantillon avant la mort | verdict |
|---|---|---|
| 24/08 18:09 | 28,1 W / 210 MHz / 4 837 Mo | plat — **exception** |
| 25/08 00:30 | 29,1 W / 210 MHz / **15 740 Mo** | modèle résident mais GPU au repos |
| 25/08 01:17 | 73,2 W / **2595 MHz** / 5 173 → **12 537 Mo** | ✅ montée |
| 25/08 10:36 | 60,1 W / **2595 MHz** | ✅ montée |
| 25/08 12:57 | 74,7 → 49,0 W / **2595 MHz** | ✅ montée |
| 26/08 13:35 | **293,4 W** / **2730 MHz** / 15 382 Mo | ✅ montée |

Signature à reconnaître : **horloge 210 → 2595 MHz + VRAM qui grimpe**, à watts encore modestes
(60-75 W) — c'est Ollama qui charge un modèle. Les 293 W du 26/08 sont l'inférence soutenue qui suit.

⚠ **Lire les lignes post-redémarrage comme telles** : le `hwlog` reprend ~1 min après (le watchdog
`WAMA-HwWatchdog` est persistant, lui). Une ligne à VRAM ~140 Mo juste après une ligne à 15 Go
n'est pas un effondrement, c'est un GPU qui vient de démarrer.

### ⚠⚠ Le garde-fou du 19/08 est ACTIF — et il n'a pas suffi

`common/services/resource_governor.py:444` documentait déjà ce mode de panne :

> « Leçon du 2026-08-19 : enchaînée hors gouverneur, elle a fait tomber l'hôte (pattern *Ollama hôte
> enchaîné*, instabilité sous l'OS). »

La parade posée alors **fonctionne comme spécifié** — vérifié : `settings.py` (route
`CELERY_TASK_ROUTES`, ~l.557 au 27/08) route
`model_manager.assess_proposed` sur la file `gpu` au palier `_prospect_assess` = **basse**, et le
worker `gpu@` l'a bien reçue le 26/08. **L'hôte est tombé quand même.**

> **La parade traitait la mauvaise variable.** Sérialiser supprime la *concurrence*, pas la *charge* :
> un gemma4:12b seul sur le GPU suffit à tuer l'hôte. **Une priorité ordonne, elle n'allège pas.**
> Généralisable : un palier de gouverneur protège d'un conflit entre tâches, jamais du coût d'une
> tâche prise isolément.

### 2026-08-28 ~11:09:16 — crash pendant la 1ʳᵉ génération Music3 : LA PREMIÈRE RAMPE
### FATALE INSTRUMENTÉE CÔTÉ RAILS — et les rails sont PROPRES

Coupure pendant la **1ʳᵉ génération MiniMax-Music3** (13 Go GGUF via audio.cpp, la plus
grosse charge WSL2 jamais tentée sur cet hôte). **Aucune passe LLM dans la séquence** : la
console WAMA montre `Démarrage` à 11:08:29 puis traduction **et** enrichissement servis
**depuis le cache dans la même seconde** (prompt identique à l'essai de 00:44) → aucun
appel Ollama. Le déclencheur est la charge GPU **WSL2 elle-même** — première de cette
taille depuis la série de juillet (les crashs d'août étaient des chargements Ollama HÔTE).

**Chronologie mesurée** (hwlog 10 s + rails 2 s ; le 6008 annonçait « 10:55:50 », soit
**14 min d'erreur, son record** — toujours dater sur les logs) :

| instant | GPU W | clock | VRAM | RAM libre | quoi |
|---|---|---|---|---|---|
| 11:08:22 | 26,7 | 210 | 5,1 Go | 64,7 Go | repos |
| 11:08:33 | **83,7** | **2760** | **14,8 Go** | 64,8 Go | allocation audio.cpp (+9,7 Go en 1 échantillon) |
| 11:08:43 | 28,2 | 210 | 14,8 Go | 62,7 Go | retour horloge idle, streaming GGUF |
| 11:08:53 | 27,7 | 210 | 14,8 Go | 60,7 Go | RAM libre **-2 Go/10 s** |
| 11:09:04 | 27,9 | 210 | 14,8 Go | 57,8 Go | dernier hwlog |
| **11:09:16** | — | — | — | — | dernier échantillon rails = mort |

**La machine est morte à ~28 W, horloge au PLANCHER, ~40 s APRÈS le pic** — pendant la
phase de *staging* disque→RAM→VRAM (mem_saver), pas au pic de puissance. Et **rails.csv
couvrait tout** (79 473 échantillons sur la session, analysés par `analyze_rails.py`,
archivé `rails_20260828_1109_crash.csv`) : **zéro violation ATX sur les 5 rails, 12VHPWR
stable 12,22-12,29 V jusqu'à la dernière ligne** — aucun creux, aucune dérive dans la
minute fatale.

**Ce que ce point change** : ① la mesure attendue depuis le 10/08 (« une rampe
instrumentée ») est FAITE — elle ne montre **rien** à 2 s d'échantillonnage, exactement la
signature « rails nominaux puis plus rien » (l'asymétrie du test reste : les transitoires
µs sont invisibles, l'alim n'est pas disculpée — mais l'hypothèse d'un rail qui s'effondre
sous charge en prend un 2ᵉ coup après le 23/08) ; ② la mort à basse puissance pendant une
**allocation/pression VRAM massive côté WSL2** recolle au pattern des 18-20/08 (« la VRAM
monte en flèche, mort en 10-40 s », quel que soit le côté hôte/invité, puissance
indifférente) et à la classe **WSL #40732** notée le 27/07 ; ③ une passe LLM hôte n'est
donc PAS nécessaire au crash — le facteur commun est la montée VRAM, pas Ollama.

**Séquelle applicative** : la card composer est restée **zombie RUNNING 20 %** — l'état
Celery était `PENDING` (méta STARTED perdue avec Redis dans le crash), donc la
réconciliation « preuve positive de mort » (`reconcile_orphaned_running`) **ne peut pas
mordre** : angle mort du mécanisme propre au cas « l'hôte entier a redémarré ».
Normalisée à la main via `stop_instance()` ; le trou est consigné, pas encore corrigé
(une bascule sur PENDING+absent réintroduirait le signal inversé de 2026-07-25 — il
faudrait une preuve « nulle part » incluant le contenu des files broker).

**Parade code posée — `WAMA_GPU_SAFE_MODE`** (settings.py, activé dans `.env` de cet
hôte ; 2026-08-28) : ① les passes LLM de la pipeline demandent `keep_alive=0` (la
traduction laissait son modèle résident ~5 min — l'enrichissement le faisait déjà,
choix mesuré du 29/07) ; ② les backends à sous-processus GPU attendent que
`effective_free_gb()` suffise avant de lancer (`wait_for_free_vram`, gouverneur), et
refusent EN LE DISANT sinon. `=0` restitue le comportement nominal à l'octet. ⚠ Elle
réduit la **superposition**, pas la **charge** d'un moteur pris seul — le 7ᵉ crash dit
précisément que ça ne suffira pas ; c'est une mise en conditions pour le diagnostic,
pas un correctif.

**Suite du même jour — 2ᵉ crash à ~12:19:51, AU REPOS, puis pilote 616.56.** Dernier
échantillon hwlog : 24,4 W, 210 MHz, VRAM 5,2 Go, stack au repos (un unique pic de
transition 210→2595 MHz à 74 W, 20 s avant la mort) ; reboot 12:25:12 ; le 6008 annonçait
« 11:49:54 » (30 min d'erreur). Signature « repos » des 07/08 et 22/08 — les DEUX régimes
tuent toujours le même jour : 11:09 en montée VRAM, 12:19 au repos. ⚠ NON instrumenté :
HWiNFO était mort avec le crash de 11:09 (aucun autostart). Ensuite Fabien a installé le
**pilote NVIDIA 616.56 à 12:40** (DriverStore `nvmdsi…` 12:40:16 ; l'ancien 610.88 datait
du 31/07) → l'appariement pilote > noyau GPU (dxgkrnl/dxgmms2 du 13/08, inchangés) est
rétabli dans le bon sens. **Nouvelle variable d'expérience posée — compter la série à
partir d'ici.** ⚠ L'instance WSL courante a démarré à 12:28, AVANT l'installation :
`nvidia-smi` y échoue (`libnvidia-ml.so` introuvable alors que la projection
`/usr/lib/wsl/lib` porte bien les fichiers 616.56) — même symptôme qu'au 25/07, même
remède OBLIGATOIRE : `wsl --shutdown` puis relance de la stack, sans quoi TOUTE tâche
CUDA côté WAMA échoue.

### 2026-08-31 ~11:45:09-19 — crash n° suivant : le TUEUR REPRODUCTIBLE frappe SOUS GO HUMAIN,
### et le pilote 616.56 n'y a rien changé

**Contexte** : passe scout LLM (`run_scout.py`, session Claude, lancée 11:44 sur GO explicite
de Fabien — plan approuvé, exécution SÉQUENTIELLE, un seul chargement) →
`select_model_for_role('dev')` = **qwen3.8:latest (dense 27B, 17,7 Go)** chargé sur l'Ollama
HÔTE. **Mort au 1ᵉʳ chargement**, avant toute réponse (zéro sortie scout écrite).

**Chronologie (hwlog ; reboot si vite que le trou ne fait que 77 s)** :

| instant | GPU W | clock | VRAM | quoi |
|---|---|---|---|---|
| 11:44:43 | 35,7 | 405 | 579 Mo | repos (WSL relancé, VRAM basse) |
| 11:44:54 | 31,5 | 465 | **16 776 Mo** | chargement qwen3.8 (+16,2 Go en 1 échantillon) |
| 11:45:09 | 30,1 | 210 | **18 734 Mo** | dernier échantillon |
| 11:46:26 | 28,3 | 210 | 138 Mo | 1ʳᵉ ligne post-reboot (watchdog reparti) |

**Ce que ce crash établit** : ① le pilote **616.56 (posé 28/08 12:40) ne protège PAS** du
chargement 17-19 Go — 1ᵉʳ crash de la nouvelle série, même signature que les 18-20/08 ;
② **la gouvernance humaine ne change pas la physique** : GO explicite + séquentiel + un seul
modèle = mort quand même — la variable n'est pas QUI lance ni COMMENT, c'est LA RAMPE VRAM
(~16 Go/10 s) ; ③ NON instrumenté côté rails — HWiNFO mort depuis le 28/08 11:09 (7ᵉ
occurrence du piège « aucun autostart »).

**Séquelles relevées** : swap.vhdx orphelin **8,04 Go** (mtime 30/08 16:24 = CRÉATION de la
session tuée — la date d'un orphelin est celle du boot, pas du crash) ; 1 card zombie
`cam_analyzer.AnalysisPass id=54` RUNNING ; scout : zéro sortie.

**Règle DURCIE (leçon n+1)** : plus AUCUNE passe LLM sur l'Ollama hôte lancée depuis une
session Claude, **même sur GO explicite** — le GO autorise, il ne protège pas. La matière des
rôles (scout/librarian) se produit MÉCANIQUEMENT (dry-run + rédaction manuelle
PENDING_HUMAN_VALIDATION) ; si une passe LLM doit tourner, c'est Fabien qui la lance,
machine sous les yeux, HWiNFO journalisant.

### Ce qui reste ouvert

- **Quel composant lâche** — inconnu. La charge est le **déclencheur**, pas le fautif : alimentation,
  RAM asymétrique (3 barrettes depuis le 24/08 16:35, `BANK 2` vide) et VRM restent tous compatibles
  avec les mesures. 0 BSOD / 0 WHEA sur la période → panne **sous l'OS**, comme depuis le début.
- **Expérience à mener, une variable à la fois** : désarmer l'enchaînement de la passe et observer si
  la série s'arrête. C'est gratuit, réversible, et ça teste une hypothèse **par elle-même** —
  contrairement au retour aux 2 barrettes Samsung (valable, mais à ne pas changer en même temps).
- **L'exception du 24/08 18:09** (plat à 28 W) n'est pas expliquée par ce mécanisme.

### Rejouer l'analyse

```bash
wsl.exe -e bash -lc 'cd /mnt/d/WAMA/web-app-for-media-automation && \
  ./venv_linux/bin/python scripts/analyze_rails.py logs/hwlog/rails_<AAAAMMJJ>_<HHMM>_crash.csv'
```
Puis recouper avec `logs/hwlog/hwlog_<AAAAMMJJ>.csv` (colonnes `gpu_w`, `gpu_clock_mhz`, `gpu_mem_mb`)
et `logs/celery-gpu.log.1` (les journaux sont **décalés au démarrage**, le pré-crash est donc en `.1`).

⚠ **HWiNFO Free n'a aucun autostart** : après chaque crash, relancer la journalisation à la main vers
`logs/hwlog/rails.csv`, **après** avoir archivé la précédente en `rails_<AAAAMMJJ>_<HHMM>_crash.csv`
(heure de la coupure, pas du Kernel-Power 41). Vérifier que le fichier GROSSIT — HWiNFO peut tourner
sans journaliser. Seule la licence Pro (~25-30 €, paramètre `-l`) rendrait la sonde persistante.

## Voir aussi
- `C:\Apache24\conf\httpd.conf` (vhost `wama.local`) — sauvegarde `httpd.conf.bak-20260824`.
- `start_wama_dev.sh`, `start_wama_prod.sh`, `gunicorn_conf.py`, `.env` / `.env.example`.
- `wama/common/management/commands/rotate_secrets.py` (rotation des secrets).
- `scripts/set_wslconfig.ps1` (plafond RAM WSL2), `wama/common/utils/log_rotation.py` (journaux).
- `CLAUDE.md` (proxy UGE, modèles), `memory/reference_proxy_uge.md`.
