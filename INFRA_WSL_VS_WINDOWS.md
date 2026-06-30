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
7. **Secrets** : sortir le mot de passe DB en dur de `settings.py` vers l'environnement/`.env`.

## Voir aussi
- `start_wama_dev.sh`, `start_wama_prod.sh`, `gunicorn_conf.py`, `.env`.
- `CLAUDE.md` (proxy UGE, modèles), `memory/reference_proxy_uge.md`.
