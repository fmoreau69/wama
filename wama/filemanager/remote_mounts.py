"""remote_mounts — dossiers DISTANTS (Nextcloud, WebDAV…) montés par rclone sous le « dossier
connecté » du filemanager.

Décision de Fabien, 2026-10-10 (`ROADMAP.md`, Writer étape 5) : la connexion à un nuage de
fichiers se fait AU FILEMANAGER, comme celle d'un partage réseau, et par rclone (MIT) — la couche
universelle et ouverte (plus de 70 stockages) — plutôt que par un serveur MCP, qui donne des
OUTILS à un LLM et ne sert pas un flux d'octets.

POURQUOI UN MONTAGE : un `MountedFolder` n'est qu'un CHEMIN ; l'arbre, l'aperçu et « Envoyer
vers » le lisent comme un dossier (`views.scan_mount_folder`, `views.api_mount_serve`). `rclone
mount` (FUSE) rend ce chemin : rien en aval n'a à savoir que le dossier est distant.

⚠ LE SECRET ne passe JAMAIS sur la ligne de commande (visible de tous dans `ps`) : il part dans
l'environnement du processus rclone, sous la forme « obscurcie » qu'exige rclone (`rclone obscure`
lu sur l'entrée standard). Au repos, il est CHIFFRÉ en base (`MountedFolder.remote_secret`).

⚠ LE PROXY suit la portée déclarée de la source au registre (`external_sources.proxies_for`) — la
même règle que tout appel sortant de WAMA, jamais un choix de l'appelant.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

#: La source déclarée au registre des sources externes (type `stockage`).
SOURCE_KEY = 'nextcloud'

#: Délais (s). L'accès vérifie les identifiants AVANT de monter : un montage en arrière-plan
#: n'aurait aucun moyen de dire « mot de passe refusé » à l'écran.
CHECK_TIMEOUT_S = 30
MOUNT_TIMEOUT_S = 90

#: Options du montage. `full` : le cache de rclone sert la lecture en avance et les sauts dans
#: une vidéo (aperçu), et l'écriture ; `dir-cache-time` court pour voir vite un fichier ajouté
#: depuis le nuage.
MOUNT_OPTIONS = ('--vfs-cache-mode', 'full', '--dir-cache-time', '30s', '--log-level', 'NOTICE')


def rclone_binary() -> str | None:
    """Le binaire rclone : réglage `WAMA_RCLONE_BIN`, puis le PATH, puis `~/.local/bin` (où il
    s'installe sans droits d'administrateur — le PATH d'un service n'y passe pas toujours)."""
    explicit = getattr(settings, 'WAMA_RCLONE_BIN', '') or os.environ.get('WAMA_RCLONE_BIN', '')
    for candidate in (explicit, shutil.which('rclone'), str(Path.home() / '.local' / 'bin' / 'rclone')):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


MISSING_RCLONE = ("rclone introuvable sur le serveur WAMA. Installez-le (binaire officiel dans "
                  "~/.local/bin, ou WAMA_RCLONE_BIN dans .env) : https://rclone.org/install/")


def is_remote_url(text: str) -> bool:
    """Le chemin saisi désigne-t-il un dossier DISTANT (adresse web) plutôt qu'un chemin ?"""
    return bool(re.match(r'^https?://', (text or '').strip(), re.IGNORECASE))


def _is_declared_host(hostname) -> bool:
    """L'adresse désigne-t-elle le serveur du nuage dont l'instance a posé l'adresse ?"""
    from wama.common import external_sources
    if not hostname or not external_sources.address_origin(SOURCE_KEY):
        return False
    return urlsplit(external_sources.base_url(SOURCE_KEY)).hostname == hostname


def webdav_config(url: str, username: str = '') -> dict:
    """La configuration d'un montage WebDAV, tirée de l'adresse SAISIE.

    Une adresse Nextcloud complète (`…/remote.php/dav/files/<identifiant>/…`) est gardée telle
    quelle. Une adresse de SERVEUR seule (`https://nuage.exemple.fr/`) est complétée par le
    chemin WebDAV de Nextcloud et l'identifiant : c'est l'adresse que l'utilisateur connaît, pas
    celle du protocole.

    Une adresse copiée du NAVIGATEUR (`…/apps/files/files?dir=/Projets`), ou toute adresse sur
    le serveur du nuage déclaré par l'instance, l'est aussi — le dossier ouvert (`dir`) compris.
    Sans cela, rclone interroge une page web, que le serveur refuse en « 405 Method Not
    Allowed » (vécu le 2026-10-10).
    """
    url = (url or '').strip()
    parts = urlsplit(url)
    path = parts.path or '/'
    nextcloud = '/remote.php/' in path
    browser_page = bool(re.match(r'^/(index\.php/)?apps/files\b', path))
    if not nextcloud and username and (path.strip('/') == '' or browser_page
                                       or _is_declared_host(parts.hostname)):
        folder = parse_qs(parts.query).get('dir', [''])[0].strip('/') if browser_page else ''
        path = f"/remote.php/dav/files/{quote(username)}/"
        if folder:
            path += quote(folder) + '/'
        nextcloud = True
    return {
        'type': 'webdav',
        'url': f"{parts.scheme}://{parts.netloc}{path}",
        'vendor': 'nextcloud' if nextcloud else 'other',
        'user': username,
    }


def display_name(config: dict) -> str:
    """Nom d'affichage proposé : le dernier dossier de l'adresse, sinon le serveur."""
    parts = urlsplit(config.get('url', ''))
    tail = [p for p in parts.path.split('/') if p]
    if config.get('vendor') == 'nextcloud' and len(tail) <= 4:   # remote.php/dav/files/<user>
        return parts.hostname or 'Nuage'
    return tail[-1] if tail else (parts.hostname or 'Nuage')


def mount_point_name(config: dict) -> str:
    """Nom du point de montage : stable pour un même compte sur un même serveur et chemin."""
    parts = urlsplit(config.get('url', ''))
    raw = f"dav_{parts.hostname}_{config.get('user', '')}_{parts.path.strip('/')}"
    return re.sub(r'[^\w-]', '_', raw)[:120]


def make_mount_point(name: str):
    """`(Path | None, erreurs)` — crée le point de montage `name`.

    Ordre des bases : réglage `WAMA_MOUNT_BASE` → `/mnt/wama_mounts` → `~/.wama/mounts`.
    `/mnt/` exige root pour `mkdir` : tentative non bloquante par `sudo -n`, puis `chown` pour que
    les suivants s'en passent. Partagé par le montage SMB et par celui de rclone.
    """
    candidates = []
    override = getattr(settings, 'WAMA_MOUNT_BASE', '') or os.environ.get('WAMA_MOUNT_BASE', '')
    if override:
        candidates.append(Path(override))
    candidates += [Path('/mnt/wama_mounts'), Path.home() / '.wama' / 'mounts']

    errors = []
    for base in candidates:
        mp = base / name
        try:
            mp.mkdir(parents=True, exist_ok=True)
            return mp, errors
        except OSError as e:
            r = subprocess.run(['sudo', '-n', 'mkdir', '-p', str(mp)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                subprocess.run(['sudo', '-n', 'chown', '-R',
                                f'{os.getuid()}:{os.getgid()}', str(base)],
                               capture_output=True, text=True)
                return mp, errors
            errors.append(f'{base} : {e}')
    return None, errors


def _obscure(rclone: str, password: str) -> str:
    """La forme « obscurcie » qu'exige rclone — lue sur l'entrée standard, jamais en argument."""
    r = subprocess.run([rclone, 'obscure', '-'], input=password, capture_output=True,
                       text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or 'rclone obscure a échoué')
    return r.stdout.strip()


def _env(rclone: str, config: dict, password: str) -> dict:
    """Environnement du processus rclone : le stockage, les identifiants et le proxy déclaré."""
    from wama.common import external_sources

    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY')}
    env.update({
        'RCLONE_WEBDAV_URL': config['url'],
        'RCLONE_WEBDAV_VENDOR': config.get('vendor') or 'other',
        'RCLONE_WEBDAV_USER': config.get('user') or '',
        'RCLONE_WEBDAV_PASS': _obscure(rclone, password) if password else '',
    })
    proxies = external_sources.proxies_for(SOURCE_KEY) or {}
    if proxies.get('https'):
        env['HTTPS_PROXY'] = env['HTTP_PROXY'] = proxies['https']
    return env


def _explain(stderr: str) -> str:
    """Le refus du serveur dit à l'écran : identifiants, adresse, ou réseau."""
    text = stderr or ''
    if re.search(r'\b401\b|Unauthorized', text):
        return 'AUTH_REFUSED'
    if re.search(r'\b404\b|Not Found|directory not found', text):
        return "Dossier introuvable à cette adresse (vérifiez l'identifiant dans l'adresse WebDAV)."
    if re.search(r'\b405\b|Method Not Allowed', text):
        return ("Cette adresse est une page web, pas un dossier WebDAV : donnez l'adresse du "
                "serveur seule, ou celle de Fichiers › Paramètres › WebDAV.")
    if 'proxyconnect' in text or 'Proxy' in text or 'tunnel' in text:
        return 'Le proxy sortant refuse la connexion : ' + text.strip().splitlines()[-1][:200]
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return (lines[-1][:300] if lines else 'Erreur inconnue de rclone')


def check_access(config: dict, password: str):
    """`(ok, erreur)` — les identifiants ouvrent-ils le dossier ? Liste un niveau, sans monter."""
    rclone = rclone_binary()
    if not rclone:
        return False, MISSING_RCLONE
    try:
        r = subprocess.run([rclone, 'lsjson', '--max-depth', '1', '--dirs-only', ':webdav:'],
                           env=_env(rclone, config, password), capture_output=True, text=True,
                           timeout=CHECK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f'Le serveur ne répond pas ({CHECK_TIMEOUT_S} s).'
    except (OSError, RuntimeError) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, None
    return False, _explain(r.stderr)


def _is_live(path: Path) -> bool:
    try:
        os.listdir(path)
        return True
    except OSError:
        return False


def unmount(path) -> bool:
    """Démonte un montage FUSE (paresseusement s'il est occupé ou mort)."""
    for args in (['fusermount3', '-u', str(path)], ['fusermount3', '-uz', str(path)]):
        try:
            if subprocess.run(args, capture_output=True, text=True, timeout=15).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def mount(config: dict, password: str):
    """`(ok, chemin, erreur)` — monte le dossier distant et rend son chemin local.

    Déjà monté et vivant → réutilisé. Monté mais MORT (rclone arrêté avec WSL : « Transport
    endpoint is not connected ») → démonté puis remonté. Erreur spéciale : 'AUTH_REFUSED'.
    """
    import sys
    if not sys.platform.startswith('linux'):
        return False, None, 'Montage rclone uniquement sur Linux/WSL2.'
    rclone = rclone_binary()
    if not rclone:
        return False, None, MISSING_RCLONE

    mount_point, errors = make_mount_point(mount_point_name(config))
    if mount_point is None:
        return False, None, 'Impossible de créer le point de montage — ' + ' ; '.join(errors)

    if subprocess.run(['mountpoint', '-q', str(mount_point)], capture_output=True).returncode == 0:
        if _is_live(mount_point):
            return True, str(mount_point), None
        unmount(mount_point)

    ok, error = check_access(config, password)
    if not ok:
        return False, None, error

    log_file = Path(settings.BASE_DIR) / 'logs' / 'rclone_mounts.log'
    cmd = [rclone, 'mount', ':webdav:', str(mount_point), '--daemon',
           '--log-file', str(log_file), *MOUNT_OPTIONS]
    try:
        r = subprocess.run(cmd, env=_env(rclone, config, password), capture_output=True,
                           text=True, timeout=MOUNT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, None, f'Montage trop long ({MOUNT_TIMEOUT_S} s).'
    except (OSError, RuntimeError) as e:
        return False, None, str(e)
    if r.returncode != 0:
        return False, None, _explain(r.stderr)
    return True, str(mount_point), None


def ensure_mounted(mounted_folder) -> bool:
    """Remonte un dossier distant dont le montage est tombé (redémarrage de WSL). Vrai si le
    chemin est vivant à la sortie. Sans secret enregistré, rien n'est tenté."""
    config = mounted_folder.remote_config or {}
    if config.get('type') != 'webdav':
        return False
    path = Path(mounted_folder.local_path)
    if _is_live(path) and subprocess.run(['mountpoint', '-q', str(path)],
                                         capture_output=True).returncode == 0:
        return True
    ok, linux_path, error = mount(config, mounted_folder.remote_secret or '')
    if not ok:
        logger.warning('[remote_mounts] remontage de « %s » impossible : %s',
                       mounted_folder.name, error)
        return False
    if linux_path != mounted_folder.local_path:
        mounted_folder.local_path = linux_path
        mounted_folder.save(update_fields=['local_path'])
    return True
