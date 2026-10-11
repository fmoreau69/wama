"""remote_mounts — dossiers DISTANTS montés par rclone sous le « dossier connecté » du filemanager :
nuage de fichiers (WebDAV, Nextcloud), partage réseau (SMB), Google Drive, OneDrive.

Décision de Fabien, 2026-10-10 (`ROADMAP.md`, Writer étape 5) : la connexion à un nuage de
fichiers se fait AU FILEMANAGER, comme celle d'un partage réseau, et par rclone (MIT) — la couche
universelle et ouverte (près de 70 stockages) — plutôt que par un serveur MCP, qui donne des
OUTILS à un LLM et ne sert pas un flux d'octets. Puis, le 2026-10-11 : *« si ça permet d'aligner
et de centraliser tous les types de connexions distantes, c'est exactement ce qu'il nous faut »*
— d'où les TYPES DÉCLARÉS ci-dessous : ajouter un stockage, c'est déclarer un type, pas écrire
un chemin de montage de plus.

POURQUOI UN MONTAGE : un `MountedFolder` n'est qu'un CHEMIN ; l'arbre, l'aperçu et « Envoyer
vers » le lisent comme un dossier (`views.scan_mount_folder`, `views.api_mount_serve`). `rclone
mount` (FUSE) rend ce chemin : rien en aval n'a à savoir que le dossier est distant.

⚠ LE SECRET ne passe JAMAIS sur la ligne de commande (visible de tous dans `ps`) : il part dans
l'environnement du processus rclone, sous la forme « obscurcie » qu'exige rclone (`rclone obscure`
lu sur l'entrée standard) pour les options que rclone déclare comme mots de passe. Au repos, il
est CHIFFRÉ en base (`MountedFolder.remote_secret`).

⚠ LE PROXY suit la portée déclarée de la source au registre (`external_sources.proxies_for`) — la
même règle que tout appel sortant de WAMA, jamais un choix de l'appelant. Un type sans source
(le partage réseau, joint sur le réseau local) n'en reçoit aucun.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets as _secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from django.conf import settings

logger = logging.getLogger(__name__)

#: La source déclarée au registre des sources externes pour le nuage WebDAV (type `stockage`).
SOURCE_KEY = 'nextcloud'

#: Délais (s). L'accès vérifie les identifiants AVANT de monter : un montage en arrière-plan
#: n'aurait aucun moyen de dire « mot de passe refusé » à l'écran.
CHECK_TIMEOUT_S = 30
MOUNT_TIMEOUT_S = 90

#: Options du montage. `full` : le cache de rclone sert la lecture en avance et les sauts dans
#: une vidéo (aperçu), et l'écriture ; `dir-cache-time` court pour voir vite un fichier ajouté
#: depuis le nuage. Le cache est BORNÉ (`WAMA_RCLONE_CACHE_MAX`, 20 Go par défaut) : sans borne,
#: parcourir les vidéos d'un partage réseau remplirait le disque pendant l'heure où rclone garde
#: ce qu'il a lu (2026-10-11, au passage du SMB par rclone).
MOUNT_OPTIONS = ('--vfs-cache-mode', 'full', '--dir-cache-time', '30s', '--log-level', 'NOTICE')


def _cache_options() -> tuple:
    size = getattr(settings, 'WAMA_RCLONE_CACHE_MAX', '') or os.environ.get('WAMA_RCLONE_CACHE_MAX',
                                                                            '20G')
    return ('--vfs-cache-max-size', str(size))


# ── Les TYPES de stockage ─────────────────────────────────────────────────────────────────
# Un type dit ce que l'utilisateur SAISIT (ses champs, en français) et comment il se connecte.
# Le reste vient de rclone lui-même (`rclone config providers`) : le stockage existe-t-il dans le
# binaire installé, quelles options sont des mots de passe à obscurcir, leur aide. Un type de plus
# = une entrée ici et sa fonction `_options_<clé>` ; le montage, le secret, le proxy, la
# vérification avant montage, l'explication des refus et le remontage sont communs.

@dataclass(frozen=True)
class Field:
    """Un champ de la fenêtre « Connecter un dossier »."""

    #: Clé du corps de la requête — et de l'écran.
    name: str
    #: Option rclone que ce champ remplit : sa métadonnée (mot de passe ? aide) vient de rclone.
    option: str
    #: Libellé affiché (en français ; l'aide de rclone, en anglais, n'est qu'une infobulle).
    label: str
    #: Repli quand rclone ne dit rien (binaire absent) : le champ est-il un secret ?
    secret: bool = False


@dataclass(frozen=True)
class OAuth:
    """Connexion OAuth 2 (code d'autorisation + PKCE) : l'utilisateur accorde l'accès dans un
    onglet du fournisseur, WAMA reçoit un jeton qu'il garde chiffré et prête à rclone."""

    #: `{base}` = adresse de la source au registre (le tenant Microsoft se pose sur la page
    #: Sources externes : `https://login.microsoftonline.com/<tenant>`).
    authorize_url: str
    token_url: str
    scope: str
    #: Paramètres ajoutés à la demande d'accès (ex. Google : accès hors ligne).
    params: tuple = ()
    #: Adresse de révocation du jeton, quand le fournisseur en a une.
    revoke_url: str = ''


@dataclass(frozen=True)
class StorageType:
    key: str
    label: str
    #: Nom du stockage dans rclone (`rclone config providers`).
    backend: str
    icon: str
    #: Source externe déclarée : proxy, adresse, client OAuth. '' = réseau local, sans proxy.
    source: str = ''
    fields: tuple = ()
    #: Sans identifiants, la connexion est tentée en invité (partage réseau).
    guest: bool = False
    #: 'login_flow' (Nextcloud) ou 'oauth' : un bouton « Se connecter par le navigateur ».
    browser_login: str = ''
    oauth: OAuth | None = None


STORAGE_TYPES: tuple[StorageType, ...] = (
    StorageType(
        'webdav', 'Nuage de fichiers', 'webdav', 'fas fa-cloud', source=SOURCE_KEY,
        fields=(Field('username', 'user', 'Identifiant du compte'),
                Field('password', 'pass', 'Mot de passe', secret=True)),
        browser_login='login_flow'),
    StorageType(
        'smb', 'Partage réseau — identifiants AD (laisser vide pour accès invité)', 'smb',
        'fas fa-network-wired',
        fields=(Field('smb_username', 'user', 'Nom d’utilisateur AD'),
                Field('smb_password', 'pass', 'Mot de passe AD', secret=True),
                Field('smb_domain', 'domain', "Domaine de l'annuaire (ex : MONDOMAINE)")),
        guest=True),
    StorageType(
        'drive', 'Google Drive', 'drive', 'fab fa-google-drive', source='google_drive',
        browser_login='oauth',
        oauth=OAuth('https://accounts.google.com/o/oauth2/v2/auth',
                    'https://oauth2.googleapis.com/token',
                    'https://www.googleapis.com/auth/drive',
                    params=(('access_type', 'offline'), ('prompt', 'consent')),
                    revoke_url='https://oauth2.googleapis.com/revoke')),
    StorageType(
        'onedrive', 'OneDrive / SharePoint', 'onedrive', 'fas fa-cloud', source='onedrive',
        browser_login='oauth',
        oauth=OAuth('{base}/oauth2/v2.0/authorize', '{base}/oauth2/v2.0/token',
                    'offline_access Files.ReadWrite.All Sites.Read.All',
                    params=(('prompt', 'select_account'),))),
)

_TYPES = {t.key: t for t in STORAGE_TYPES}


def storage_type(key: str) -> StorageType | None:
    return _TYPES.get(key or '')


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

#: `rclone config providers` lu une fois par binaire : la liste ne change qu'avec rclone.
_PROVIDERS: dict[str, dict] = {}


def rclone_providers() -> dict:
    """{stockage: {option: métadonnée}} décrits par le rclone INSTALLÉ, ou {} sans rclone.
    Un échec n'est pas retenu : la lecture suivante réessaie."""
    rclone = rclone_binary()
    if not rclone:
        return {}
    if rclone not in _PROVIDERS:
        try:
            r = subprocess.run([rclone, 'config', 'providers'], capture_output=True, text=True,
                               timeout=CHECK_TIMEOUT_S)
            listing = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            listing = None
        if not isinstance(listing, list):
            return {}
        _PROVIDERS[rclone] = {
            p.get('Name'): {o.get('Name'): o for o in p.get('Options') or []}
            for p in listing if isinstance(p, dict)}
    return _PROVIDERS[rclone]


def backend_available(backend: str) -> bool:
    """Le rclone installé connaît-il ce stockage ?"""
    return backend in rclone_providers()


def _password_options(st: StorageType) -> set:
    """Les options que rclone attend OBSCURCIES : celles qu'il déclare mots de passe ; à défaut
    de rclone lisible, les champs déclarés secrets."""
    meta = rclone_providers().get(st.backend)
    if meta:
        return {name for name, o in meta.items() if o.get('IsPassword')}
    return {f.option for f in st.fields if f.secret}


def storage_form(key: str, values: dict | None = None) -> dict:
    """Ce que la fenêtre « Connecter un dossier » affiche pour un type : ses champs (libellé
    déclaré, nature et aide tirées de rclone), l'accès invité, la connexion par le navigateur."""
    st = storage_type(key)
    meta = rclone_providers().get(st.backend, {})
    fields = []
    for f in st.fields:
        option = meta.get(f.option, {})
        fields.append({
            'name': f.name, 'label': f.label,
            'secret': bool(option.get('IsPassword', f.secret)),
            'help': (option.get('Help') or '').strip().splitlines()[0] if option.get('Help') else '',
            'value': (values or {}).get(f.name, ''),
        })
    return {'type': st.key, 'label': st.label, 'icon': st.icon, 'fields': fields,
            'guest': st.guest, 'browser_login': st.browser_login}


def oauth_client(key: str) -> tuple[str, str]:
    """`(identifiant, secret)` du client OAuth que l'instance a déclaré pour un type, ou
    `('', '')`. Posé par un admin sur la page Sources externes, sous la forme
    `identifiant:secret` (la clé d'instance de la source)."""
    st = storage_type(key)
    if not st or not st.oauth or not st.source:
        return '', ''
    from wama.common import external_sources
    client_id, _, client_secret = external_sources.api_key(st.source).strip().partition(':')
    return (client_id, client_secret) if client_id and client_secret else ('', '')


def oauth_types_offered() -> list[dict]:
    """Les stockages à connexion OAuth que l'instance PROPOSE : client OAuth posé, stockage
    connu du rclone installé."""
    offered = []
    for st in STORAGE_TYPES:
        if st.oauth and all(oauth_client(st.key)) and backend_available(st.backend):
            offered.append({'key': st.key, 'label': st.label, 'icon': st.icon})
    return offered


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


def smb_config(server: str, host: str, share: str, subpath: str = '', username: str = '',
               domain: str = '') -> dict:
    """La configuration d'un partage réseau. `server` est le nom SAISI (il nomme le point de
    montage, stable d'un essai à l'autre), `host` celui que le réseau résout
    (`views._resolve_smb_host`). Sans identifiant : accès invité."""
    return {'type': 'smb', 'server': server, 'host': host, 'share': share,
            'subpath': (subpath or '').strip('/'), 'user': username or '', 'domain': domain or '',
            'guest': not username}


def display_name(config: dict) -> str:
    """Nom d'affichage proposé : le dernier dossier de l'adresse, sinon le serveur."""
    kind = config.get('type')
    if kind == 'smb':
        return (config.get('subpath') or '').rsplit('/', 1)[-1] or config.get('share') or 'Partage'
    if kind in ('drive', 'onedrive'):
        st = storage_type(kind)
        return f"{st.label} — {config['account']}" if config.get('account') else st.label
    parts = urlsplit(config.get('url', ''))
    tail = [p for p in parts.path.split('/') if p]
    if config.get('vendor') == 'nextcloud' and len(tail) <= 4:   # remote.php/dav/files/<user>
        return parts.hostname or 'Nuage'
    return tail[-1] if tail else (parts.hostname or 'Nuage')


def mount_point_name(config: dict) -> str:
    """Nom du point de montage : stable pour un même compte sur un même serveur et chemin.

    ⚠ Le partage réseau monté par rclone est préfixé `smb_` : l'ancien montage du noyau
    (`views._try_cifs_mount`) occupe `<serveur>_<partage>`, qu'un montage de l'un ne doit
    jamais recouvrir avec l'autre.
    """
    kind = config.get('type')
    if kind == 'smb':
        raw = (f"smb_{config.get('server')}_{config.get('share')}_{config.get('user', '')}_"
               f"{config.get('subpath', '')}")
    elif kind in ('drive', 'onedrive'):
        raw = f"{kind}_{config.get('owner', '')}_{config.get('account') or config.get('drive_id', '')}"
    else:
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


# ── Ce que chaque type passe à rclone : {option: valeur} ──────────────────────────────────

def _options_webdav(config: dict, secret: str) -> dict:
    return {
        'url': config['url'],
        'vendor': config.get('vendor') or 'other',
        # Le NOM DE CONNEXION authentifie, l'identifiant (`user`) nomme le dossier WebDAV : ils
        # diffèrent quand le nuage connecte par e-mail ou par la connexion de l'établissement.
        'user': config.get('login') or config.get('user') or '',
        'pass': secret,
    }


def _options_smb(config: dict, secret: str) -> dict:
    options = {'host': config.get('host') or config.get('server', ''),
               'user': config.get('user') or '', 'pass': secret or ''}
    if config.get('domain'):
        options['domain'] = config['domain']
    return options


def _options_oauth(config: dict, secret: str) -> dict:
    """Stockage à jeton OAuth : le client de l'instance, le jeton de l'utilisateur, et les
    adresses du fournisseur (rclone renouvelle le jeton d'accès lui-même pendant le montage)."""
    st = storage_type(config['type'])
    client_id, client_secret = oauth_client(st.key)
    options = {'client_id': client_id, 'client_secret': client_secret, 'token': secret,
               'auth_url': _oauth_url(st, st.oauth.authorize_url),
               'token_url': _oauth_url(st, st.oauth.token_url)}
    if st.key == 'drive':
        options['scope'] = 'drive'
    if st.key == 'onedrive':
        options.update({'drive_id': config.get('drive_id', ''),
                        'drive_type': config.get('drive_type', '')})
    return options


_OPTIONS = {'webdav': _options_webdav, 'smb': _options_smb,
            'drive': _options_oauth, 'onedrive': _options_oauth}


def rclone_target(config: dict) -> str:
    """Le chemin rclone du dossier : un stockage « à la volée » (`:smb:`), configuré par
    l'environnement — aucun fichier de configuration rclone n'est écrit."""
    st = storage_type(config.get('type'))
    if st.key == 'smb':
        path = '/'.join(p for p in (config.get('share', ''), config.get('subpath', '')) if p)
        return f':smb:{path}'
    return f':{st.backend}:'


def _env(rclone: str, config: dict, password: str) -> dict:
    """Environnement du processus rclone : le stockage, les identifiants et le proxy déclaré.
    Chaque option part en `RCLONE_<STOCKAGE>_<OPTION>` ; celles que rclone tient pour des mots de
    passe partent obscurcies."""
    from wama.common import external_sources

    st = storage_type(config.get('type'))
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY')}
    hidden = _password_options(st)
    for option, value in _OPTIONS[st.key](config, password).items():
        if option in hidden and value:
            value = _obscure(rclone, value)
        env[f'RCLONE_{st.backend.upper()}_{option.upper()}'] = value or ''
    if st.source:
        proxies = external_sources.proxies_for(st.source) or {}
        if proxies.get('https'):
            env['HTTPS_PROXY'] = env['HTTP_PROXY'] = proxies['https']
    return env


def _explain(stderr: str, config: dict | None = None) -> str:
    """Le refus du serveur dit à l'écran : identifiants, adresse, ou réseau.

    Erreurs spéciales : 'AUTH_REFUSED' (des identifiants envoyés ont été rejetés) et, pour un
    partage réseau tenté en invité, 'AUTH_REQUIRED' — le serveur dit la même chose dans les deux
    cas, ce qui les distingue est ce que NOUS avons envoyé.
    """
    text = stderr or ''
    config = config or {}
    if re.search(r'\b401\b|Unauthorized|logon is invalid|LOGON_FAILURE|Access Denied|'
                 r'ACCESS_DENIED|invalid_grant', text, re.IGNORECASE):
        if config.get('type') == 'smb' and not config.get('user'):
            return 'AUTH_REQUIRED'
        return 'AUTH_REFUSED'
    if re.search(r'BAD_NETWORK_NAME|Network Name Not Found|share name cannot be found', text,
                 re.IGNORECASE):
        return "Partage introuvable sur ce serveur (vérifiez le nom du partage)."
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
        r = subprocess.run([rclone, 'lsjson', '--max-depth', '1', '--dirs-only',
                            rclone_target(config)],
                           env=_env(rclone, config, password), capture_output=True, text=True,
                           timeout=CHECK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f'Le serveur ne répond pas ({CHECK_TIMEOUT_S} s).'
    except (OSError, RuntimeError) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, None
    return False, _explain(r.stderr, config)


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
    endpoint is not connected ») → démonté puis remonté. Erreurs spéciales : 'AUTH_REFUSED',
    'AUTH_REQUIRED' (`_explain`).
    """
    import sys
    if not sys.platform.startswith('linux'):
        return False, None, 'Montage rclone uniquement sur Linux/WSL2.'
    if not storage_type(config.get('type')):
        return False, None, f"Type de stockage inconnu : {config.get('type')!r}."
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
    cmd = [rclone, 'mount', rclone_target(config), str(mount_point), '--daemon',
           '--log-file', str(log_file), *MOUNT_OPTIONS, *_cache_options()]
    try:
        r = subprocess.run(cmd, env=_env(rclone, config, password), capture_output=True,
                           text=True, timeout=MOUNT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, None, f'Montage trop long ({MOUNT_TIMEOUT_S} s).'
    except (OSError, RuntimeError) as e:
        return False, None, str(e)
    if r.returncode != 0:
        return False, None, _explain(r.stderr, config)
    return True, str(mount_point), None


def ensure_mounted(mounted_folder) -> bool:
    """Remonte un dossier distant dont le montage est tombé (redémarrage de WSL). Vrai si le
    chemin est vivant à la sortie. Un partage réseau en invité se remonte sans secret ; un
    stockage à jeton OAuth renouvelle d'abord son jeton, gardé à jour en base."""
    config = mounted_folder.remote_config or {}
    st = storage_type(config.get('type'))
    if not st:
        return False
    path = Path(mounted_folder.local_path)
    if _is_live(path) and subprocess.run(['mountpoint', '-q', str(path)],
                                         capture_output=True).returncode == 0:
        return True
    secret = mounted_folder.remote_secret or ''
    if st.oauth and secret:
        fresh = refresh_oauth_token(config, secret)
        if fresh and fresh != secret:
            mounted_folder.remote_secret = secret = fresh
            mounted_folder.save(update_fields=['remote_secret'])
    ok, linux_path, error = mount(config, secret)
    if not ok:
        logger.warning('[remote_mounts] remontage de « %s » impossible : %s',
                       mounted_folder.name, error)
        return False
    if linux_path != mounted_folder.local_path:
        mounted_folder.local_path = linux_path
        mounted_folder.save(update_fields=['local_path'])
    return True


def release_credentials(config: dict, secret: str) -> bool:
    """Un dossier retiré (ou un montage qui a échoué) ne laisse pas d'accès ouvert : le mot de
    passe d'application obtenu par le navigateur, ou le jeton OAuth, est révoqué. Jamais un mot
    de passe SAISI, qui peut être celui du compte."""
    st = storage_type((config or {}).get('type'))
    if st and st.oauth:
        return revoke_oauth_token(config, secret)
    return revoke_app_password(config or {}, secret)


# ── Connexion PAR LE NAVIGATEUR (Nextcloud « Login Flow v2 ») ─────────────────────────────
# Demande de Fabien, 2026-10-11 : recopier un mot de passe d'application est malcommode. Ici,
# l'utilisateur accorde l'accès DANS un onglet de son nuage — où marchent la connexion de
# l'établissement et FIDO2 — et le serveur rend un mot de passe d'application créé pour WAMA.
# Aucun mot de passe ne transite par WAMA, et celui du compte n'y est jamais stocké.
# Protocole : https://docs.nextcloud.com/server/latest/developer_manual/client_apis/LoginFlow/

#: Nom sous lequel WAMA apparaît dans « Appareils & sessions » du nuage.
LOGIN_FLOW_CLIENT = 'WAMA'
#: Durée de vie d'un flux côté Nextcloud (20 min) : au-delà, l'interrogation rend 404 à jamais.
#: Vaut aussi pour une demande d'accès OAuth en attente.
LOGIN_FLOW_LIFETIME_S = 20 * 60
HTTP_TIMEOUT_S = 20

LOGIN_FLOW_UNAVAILABLE = ("Ce serveur ne propose pas la connexion par le navigateur — "
                          "saisissez l'identifiant et le mot de passe.")


def server_root(url: str) -> str:
    """La racine du serveur Nextcloud d'une adresse saisie (`https://nuage.fr`, ou
    `https://hote/nextcloud` pour une installation dans un sous-dossier)."""
    parts = urlsplit((url or '').strip())
    match = re.match(r'^(.*?)(/(remote|index|status)\.php\b|/apps/|/settings\b|/login\b|/[sf]/)',
                     parts.path)
    prefix = match.group(1) if match else parts.path
    return f"{parts.scheme}://{parts.netloc}{prefix.rstrip('/')}"


def _http(method: str, url: str, source: str = SOURCE_KEY, **kwargs):
    import requests
    from wama.common import external_sources
    kwargs.setdefault('timeout', HTTP_TIMEOUT_S)
    kwargs.setdefault('headers', {}).setdefault('User-Agent', LOGIN_FLOW_CLIENT)
    return requests.request(method, url, proxies=external_sources.proxies_for(source), **kwargs)


def login_flow_start(url: str):
    """`(flux | None, erreur)` — ouvre un flux ; `flux['login']` est la page à ouvrir dans le
    navigateur, `endpoint`/`token` restent côté serveur (session) pour l'interrogation."""
    root = server_root(url)
    try:
        r = _http('POST', root + '/index.php/login/v2')
        data = r.json() if r.status_code == 200 else {}
        login, poll = data.get('login', ''), data.get('poll') or {}
    except Exception as e:   # réseau, proxy, réponse qui n'est pas du JSON
        logger.info('[remote_mounts] login flow indisponible sur %s : %s', root, e)
        return None, LOGIN_FLOW_UNAVAILABLE
    host = urlsplit(root).hostname
    # Le serveur DÉSIGNE l'adresse d'interrogation : elle doit rester sur son propre hôte.
    if not (login and poll.get('token') and urlsplit(login).hostname == host
            and urlsplit(poll.get('endpoint', '')).hostname == host):
        return None, LOGIN_FLOW_UNAVAILABLE
    return {'server': root, 'login': login, 'endpoint': poll['endpoint'],
            'token': poll['token']}, None


def login_flow_poll(flow: dict):
    """`('pending' | 'granted' | 'error', données)` — l'utilisateur a-t-il accordé l'accès ?
    Accordé : `{server, loginName, appPassword}` (rendu UNE seule fois par Nextcloud)."""
    try:
        r = _http('POST', flow['endpoint'], data={'token': flow['token']})
    except Exception as e:
        return 'error', f'Le nuage ne répond pas : {e}'
    if r.status_code == 404:
        return 'pending', None
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code == 200 and data.get('loginName') and data.get('appPassword'):
        return 'granted', data
    return 'error', f'Réponse inattendue du nuage ({r.status_code}).'


def nextcloud_user_id(server: str, login: str, password: str) -> str:
    """L'identifiant qui figure dans l'adresse WebDAV. Il peut différer du nom de connexion
    (adresse e-mail, connexion de l'établissement) : on le demande au serveur, repli sur le nom."""
    try:
        r = _http('GET', server_root(server) + '/ocs/v2.php/cloud/user?format=json',
                  auth=(login, password), headers={'OCS-APIRequest': 'true'})
        return (r.json().get('ocs', {}).get('data', {}).get('id') or login) if r.ok else login
    except Exception:
        return login


def revoke_app_password(config: dict, password: str) -> bool:
    """Révoque le mot de passe d'application que WAMA a obtenu par le navigateur : un dossier
    retiré ne laisse pas d'accès ouvert dans « Appareils & sessions »."""
    if not (config.get('login_flow') and config.get('server') and password):
        return False
    try:
        r = _http('DELETE', config['server'] + '/ocs/v2.php/core/apppassword',
                  auth=(config.get('login') or config.get('user', ''), password),
                  headers={'OCS-APIRequest': 'true'})
        return r.ok
    except Exception as e:
        logger.warning('[remote_mounts] révocation impossible : %s', e)
        return False


# ── Connexion PAR LE NAVIGATEUR, OAuth 2 (Google Drive, OneDrive) ──────────────────────────
# Même geste que le Login Flow de Nextcloud : l'utilisateur accorde l'accès dans un onglet du
# fournisseur, WAMA ne voit jamais son mot de passe. Le fournisseur renvoie l'onglet vers WAMA
# (`views.api_mount_oauth_callback`) avec un code, échangé contre un jeton que WAMA garde CHIFFRÉ
# et prête à rclone. Le client OAuth est celui de l'INSTANCE (page Sources externes) : il se
# déclare chez le fournisseur avec l'adresse de retour de WAMA.

def _oauth_url(st: StorageType, template: str) -> str:
    from wama.common import external_sources
    return template.format(base=external_sources.base_url(st.source))


def _pkce_pair() -> tuple[str, str]:
    verifier = _secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip('=')


def oauth_start(key: str, redirect_uri: str):
    """`(flux | None, erreur)` — la page où l'utilisateur accorde l'accès (`flux['login']`) ;
    `state` et `verifier` restent côté serveur (session)."""
    st = storage_type(key)
    if not st or not st.oauth:
        return None, 'Ce stockage ne se connecte pas par le navigateur.'
    client_id, _ = oauth_client(key)
    if not client_id:
        return None, (f"{st.label} n'est pas configuré sur ce serveur : un administrateur doit "
                      "poser le client OAuth sur la page Sources externes.")
    state, (verifier, challenge) = _secrets.token_urlsafe(24), _pkce_pair()
    query = {'client_id': client_id, 'response_type': 'code', 'redirect_uri': redirect_uri,
             'scope': st.oauth.scope, 'state': state, 'code_challenge': challenge,
             'code_challenge_method': 'S256', **dict(st.oauth.params)}
    login = _oauth_url(st, st.oauth.authorize_url) + '?' + urlencode(query)
    return {'type': key, 'state': state, 'verifier': verifier, 'redirect_uri': redirect_uri,
            'login': login}, None


def _rclone_token(data: dict) -> str:
    """Le jeton au format qu'attend rclone (celui de la bibliothèque OAuth de Go)."""
    from datetime import datetime, timedelta, timezone
    expiry = datetime.now(timezone.utc) + timedelta(seconds=int(data.get('expires_in') or 3600))
    return json.dumps({'access_token': data.get('access_token', ''),
                       'token_type': data.get('token_type') or 'Bearer',
                       'refresh_token': data.get('refresh_token', ''),
                       'expiry': expiry.strftime('%Y-%m-%dT%H:%M:%SZ')})


def oauth_exchange(flow: dict, code: str):
    """`(jeton rclone | None, erreur)` — échange le code reçu au retour contre un jeton."""
    st = storage_type(flow.get('type'))
    client_id, client_secret = oauth_client(st.key)
    try:
        r = _http('POST', _oauth_url(st, st.oauth.token_url), source=st.source, data={
            'grant_type': 'authorization_code', 'code': code,
            'redirect_uri': flow['redirect_uri'], 'client_id': client_id,
            'client_secret': client_secret, 'code_verifier': flow['verifier']})
        data = r.json()
    except Exception as e:
        return None, f'{st.label} ne répond pas : {e}'
    if not r.ok or not data.get('access_token') or not data.get('refresh_token'):
        reason = data.get('error_description') or data.get('error') or r.status_code
        return None, f"{st.label} a refusé l'échange ({reason})."
    return _rclone_token(data), None


def oauth_account(key: str, token: str) -> dict:
    """Ce que la configuration doit savoir du compte connecté : son nom (le point de montage et
    le nom proposé en dépendent) et, pour OneDrive, le lecteur que rclone exige (`drive_id`,
    `drive_type`). {} si le fournisseur ne répond pas."""
    st = storage_type(key)
    headers = {'Authorization': f"Bearer {json.loads(token)['access_token']}"}
    try:
        if key == 'drive':
            r = _http('GET', 'https://www.googleapis.com/drive/v3/about?fields=user',
                      source=st.source, headers=headers)
            user = r.json().get('user', {}) if r.ok else {}
            return {'account': user.get('emailAddress', '')} if user else {}
        if key == 'onedrive':
            r = _http('GET', 'https://graph.microsoft.com/v1.0/me/drive', source=st.source,
                      headers=headers)
            data = r.json() if r.ok else {}
            if not data.get('id'):
                return {}
            owner = (data.get('owner') or {}).get('user') or {}
            return {'drive_id': data['id'], 'drive_type': data.get('driveType', ''),
                    'account': owner.get('email') or owner.get('displayName', '')}
    except Exception as e:
        logger.info('[remote_mounts] compte %s illisible : %s', key, e)
    return {}


def refresh_oauth_token(config: dict, secret: str) -> str | None:
    """Un jeton renouvelé (au format rclone), ou None. Appelé avant un remontage : le jeton
    gardé en base reste vivant même quand le fournisseur en change à chaque renouvellement."""
    st = storage_type(config.get('type'))
    try:
        refresh = json.loads(secret).get('refresh_token', '')
    except (ValueError, AttributeError):
        return None
    client_id, client_secret = oauth_client(st.key)
    if not (refresh and client_id):
        return None
    try:
        r = _http('POST', _oauth_url(st, st.oauth.token_url), source=st.source, data={
            'grant_type': 'refresh_token', 'refresh_token': refresh,
            'client_id': client_id, 'client_secret': client_secret})
        data = r.json() if r.ok else {}
    except Exception as e:
        logger.info('[remote_mounts] renouvellement du jeton %s impossible : %s', st.key, e)
        return None
    if not data.get('access_token'):
        return None
    data.setdefault('refresh_token', refresh)   # Google ne le renvoie pas : on garde l'ancien
    return _rclone_token(data)


def revoke_oauth_token(config: dict, secret: str) -> bool:
    """Révoque le jeton chez le fournisseur qui le permet (Google). Microsoft n'a pas de
    révocation par jeton : l'accès se retire depuis le compte (applications autorisées)."""
    st = storage_type(config.get('type'))
    if not (st and st.oauth and st.oauth.revoke_url and secret):
        return False
    try:
        token = json.loads(secret).get('refresh_token', '')
    except (ValueError, AttributeError):
        return False
    try:
        return _http('POST', st.oauth.revoke_url, source=st.source, data={'token': token}).ok
    except Exception as e:
        logger.warning('[remote_mounts] révocation impossible : %s', e)
        return False
