"""
Résolution CENTRALISÉE de l'exécutable ffmpeg/ffprobe — brique commune WAMA.

Pourquoi : plusieurs apps appelaient `ffmpeg` « nu » (`subprocess([... 'ffmpeg' ...])`),
ce qui échoue dès que le PATH du process (Celery/gunicorn, env WSL2 dépouillé) ne contient
pas ffmpeg — d'où des pannes récurrentes. On centralise ici la résolution robuste (variable
d'env → PATH → emplacements connus → ffmpeg de imageio si présent) et TOUT le code passe par
`get_ffmpeg_exe()` / `get_ffprobe_exe()`.

Le résultat ne vaut JAMAIS None : à défaut, on renvoie le nom nu (`'ffmpeg'`) → comportement
au pire identique à l'ancien (aucune régression). Mémoïsé (le binaire ne bouge pas en cours de run).
"""
import os
import re
import shutil
import platform
from functools import lru_cache


def is_wsl() -> bool:
    """True si on tourne sous WSL (Windows Subsystem for Linux)."""
    try:
        return 'microsoft' in platform.release().lower() or 'WSL_DISTRO_NAME' in os.environ
    except Exception:
        return False


def _ffmpeg_candidates():
    """Liste ORDONNÉE de chemins ffmpeg à essayer (Linux/WSL natif d'abord, puis Windows /mnt)."""
    cands = []
    found = shutil.which("ffmpeg")
    if found:
        cands.append(found)
    cands += ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    if is_wsl():                                   # WSL : ffmpeg natif souvent défaillant → repli .exe Windows
        cands += ["/mnt/c/ffmpeg/bin/ffmpeg.exe",
                  "/mnt/c/Program Files/ffmpeg/bin/ffmpeg.exe"]
    if platform.system() == "Windows":
        cands += [r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]
    try:
        import imageio_ffmpeg
        cands.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    # Dédup en préservant l'ordre, on ne garde que les fichiers existants.
    seen, out = set(), []
    for c in cands:
        if c and c not in seen and os.path.isfile(c):
            seen.add(c)
            out.append(c)
    return out


def _probe_ffmpeg(exe: str) -> bool:
    """Test FONCTIONNEL : décode une mire lavfi + encode en H.264 → null. True si OK.
    Repère un ffmpeg « présent mais cassé » (codecs/libs manquants), d'où l'auto-switch."""
    import subprocess
    try:
        r = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc=duration=0.1:size=64x64:rate=10",
             "-c:v", "libx264", "-f", "null", "-"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_ffmpeg_exe() -> str:
    """
    Chemin d'un ffmpeg QUI FONCTIONNE (jamais None).
    Priorité : FFMPEG_BINARY (override explicite) → premier candidat qui PASSE le test
    fonctionnel → à défaut, premier candidat existant → 'ffmpeg' nu.
    Détecte/switche tout seul : WSL2 dev (natif cassé → ffmpeg.exe Windows), prod Linux (natif OK).
    """
    # Override explicite (escape hatch) — utilisé tel quel s'il existe.
    env_binary = os.getenv("FFMPEG_BINARY")
    if env_binary and os.path.isfile(env_binary):
        return env_binary

    cands = _ffmpeg_candidates()
    for c in cands:
        if _probe_ffmpeg(c):
            return c
    return cands[0] if cands else "ffmpeg"


@lru_cache(maxsize=1)
def get_ffprobe_exe() -> str:
    """
    Chemin de ffprobe. On le prend de PRÉFÉRENCE à côté du ffmpeg retenu (même install
    fonctionnelle) ; sinon FFPROBE_BINARY → PATH → 'ffprobe' nu.
    """
    env_binary = os.getenv("FFPROBE_BINARY")
    if env_binary and os.path.isfile(env_binary):
        return env_binary

    # ffprobe voisin du ffmpeg qui marche (cohérence garantie).
    ff = get_ffmpeg_exe()
    base = os.path.basename(ff)
    if "ffmpeg" in base.lower():
        sibling = os.path.join(os.path.dirname(ff),
                               base.replace("ffmpeg", "ffprobe").replace("FFMPEG", "FFPROBE"))
        if os.path.isfile(sibling):
            return sibling

    found = shutil.which("ffprobe")
    return found or "ffprobe"


def adapt_path_for_ffmpeg(path: str, ffmpeg_exe: str = None) -> str:
    """
    Adapte un chemin pour ffmpeg quand on utilise un ffmpeg WINDOWS (.exe) depuis WSL :
    /mnt/c/foo → C:\\foo (un .exe Windows ne consomme pas les chemins /mnt/*). Sinon, no-op.
    """
    if not path:
        return path
    exe = ffmpeg_exe or get_ffmpeg_exe()
    if exe and exe.lower().endswith(".exe"):
        m = re.match(r"^/mnt/([a-zA-Z])/(.*)", path)
        if m:
            return f"{m.group(1).upper()}:\\{m.group(2).replace('/', chr(92))}"
    return path
