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
- **⚠️ DEUX bases PostgreSQL distinctes** (corrigé 2026-06-25) : Windows a son propre `wama_db`,
  WSL2 le sien. Un `manage.py` lancé côté **Windows** agit sur la base **Windows** ; le serveur live
  (WSL2) lit la base **WSL2**. Pour agir sur la vraie base : `wsl.exe -e bash -lc "… venv_linux …
  manage.py <cmd>"`. Les **seeds** sont désormais **automatisés au démarrage** (`start_wama_*.sh`).
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
| **PostgreSQL 16** | WSL2 | `sudo service postgresql start` ; `wama_db` / `wama_user` | 127.0.0.1:5432 |
| **Redis** | WSL2 | `redis-server --daemonize` ; DB0=broker Celery, DB1=cache+résultats | 127.0.0.1:6379 |
| **Celery (GPU)** | WSL2 | worker `--pool=solo --queues=gpu` `gpu@%h` (sérialise la VRAM) | — |
| **Celery (default)** | WSL2 | worker prefork `--autoscale=4,1 --queues=default,celery` `default@%h` | — |
| **Celery beat** | WSL2 | planificateur périodique | — |
| **TTS service** | WSL2 | `uvicorn tts_service:app --host 0.0.0.0` (précharge XTTS v2) | :8001 |
| **GPU / CUDA** | Windows (HW) → WSL2 | RTX 4090 physique sur Windows, **exposée à WSL2** (passthrough GPU WSL2) ; torch CUDA tourne **dans** WSL2 | — |
| **Apache (frontal)** | **Windows** | reverse proxy public → gunicorn WSL2 via **netsh portproxy** `0.0.0.0:8000 → WSL2_IP:8000` | :80/:443 |
| **Ollama** | **Windows** | « Ollama runs on Windows » ; WSL2 le joint via l'IP de la **default gateway** (`OLLAMA_HOST` auto, surchargeable ; `.env` pointe une IP LAN UGE) | host:11434 |
| **CIFS / montages** | WSL2 | remontés au démarrage via l'API `filemanager/api/mounts/remount/` | — |
| **Tooling dev (Claude Code)** | Windows | venv_win ; atteint Postgres/Redis WSL2 par localhost forwarding | — |

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
7. **Secrets** : ✅ FAIT (2026-07-23) — mot de passe DB, `SECRET_KEY`, proxy sortis de `settings.py`
   vers l'environnement/`.env` (voir section ci-dessous). En prod : injecter via systemd
   `EnvironmentFile=` / Docker secrets / Vault plutôt qu'un `.env` (le code ne change pas).

## Secrets & configuration (`.env`)  — externalisation 2026-07-23
- **Config env-driven** : `SECRET_KEY`, mot de passe DB, `PROXY`/`HTTP_PROXY`, LDAP… lus via
  `os.environ.get(...)` dans `settings.py`. Plus AUCUN secret en dur. Valeurs réelles dans `.env`
  (gitignoré, **jamais commité**) ; modèle sans secret = `.env.example` (commité).
- **Secrets externalisés** : les anciens secrets ont été sortis du dépôt
  ( puis republiés → **les références ont été mises à jour** le 2026-07-23. Aucun secret
  ne subsiste dans l'arbre ni l'historique (les 2 branches). Rotation reportée à la prod (assumé :
  DB en `127.0.0.1`, infra interne université, pas de données sensibles).
- **Rotation à la demande** : `python manage.py rotate_secrets` (voir `wama/common/management/commands/`).
  - `--all --also-wsl` = rote clé Django + mot de passe DB, applique l'`ALTER USER` à la base **dev
    Windows** (courante) ET à la base **live WSL2** (via `wsl.exe`), met à jour `.env` — les DEUX bases
    en une commande (cf. règle des deux Postgres distincts plus haut). Lancer **depuis Windows**.
  - Vérifie une nouvelle connexion + rollback auto si KO ; l'ancienne `SECRET_KEY` bascule dans
    `DJANGO_SECRET_KEY_FALLBACKS` (aucune session invalidée) ; journal `logs/secret_rotation.log`.
  - Reste optionnel : hostname interne `vrlescot` + IP gateway WSL `172.29.240.1` encore en clair
    dans quelques docs/scripts (divulgation d'infra mineure, non critique).

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

## Voir aussi
- `start_wama_dev.sh`, `start_wama_prod.sh`, `gunicorn_conf.py`, `.env` / `.env.example`.
- `wama/common/management/commands/rotate_secrets.py` (rotation des secrets).
- `scripts/set_wslconfig.ps1` (plafond RAM WSL2), `wama/common/utils/log_rotation.py` (journaux).
- `CLAUDE.md` (proxy UGE, modèles), `memory/reference_proxy_uge.md`.
