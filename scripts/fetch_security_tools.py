"""
Récupère les binaires des outils de sécurité dans tools/security/bin/ (git-ignoré).

Domicile UNIQUE du provisioning de ces outils — les scénarios nocturnes
(`check_secret_leaks`) cherchent les binaires ici et SKIPPENT proprement s'ils
manquent, en pointant vers ce script.

Le dépôt étant partagé entre Windows et WSL2 (/mnt/d), on télécharge LES DEUX
plateformes en une passe : chaque environnement trouve le sien.

Versions ÉPINGLÉES (pas de « latest ») : un outil de contrôle qui change de version
silencieusement peut changer de verdict silencieusement.

Usage : python scripts/fetch_security_tools.py
Proxy : honore HTTPS_PROXY (déjà posé dans le profil WSL2 ; inutile côté Windows).
Téléchargement via curl (présent sur Windows 10+ et toutes les distros) : urllib
subit des coupures systématiques à ~6-8 Mo derrière le réseau UGE (constaté 13/08).
"""
import io
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

GITLEAKS_VERSION = "8.30.1"
_BASE = f"https://github.com/gitleaks/gitleaks/releases/download/v{GITLEAKS_VERSION}"

BIN_DIR = Path(__file__).resolve().parent.parent / "tools" / "security" / "bin"


def _download(url: str) -> bytes:
    print(f"  GET {url}")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "download.bin"
        subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(dest), url], check=True)
        return dest.read_bytes()


def fetch_gitleaks() -> None:
    # Windows : zip contenant gitleaks.exe
    exe = BIN_DIR / "gitleaks.exe"
    if not exe.exists():
        data = _download(f"{_BASE}/gitleaks_{GITLEAKS_VERSION}_windows_x64.zip")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            exe.write_bytes(zf.read("gitleaks.exe"))
        print(f"  OK {exe}")
    # Linux (WSL2 / futur serveur) : tar.gz contenant gitleaks
    elf = BIN_DIR / "gitleaks"
    if not elf.exists():
        data = _download(f"{_BASE}/gitleaks_{GITLEAKS_VERSION}_linux_x64.tar.gz")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            elf.write_bytes(tf.extractfile("gitleaks").read())
        elf.chmod(elf.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  OK {elf}")


def install_precommit_hook() -> None:
    """Copie le hook versionné vers .git/hooks/ (le .git/ est PARTAGÉ Windows/WSL2)."""
    repo = BIN_DIR.parent.parent.parent
    source = repo / "scripts" / "git-hooks" / "pre-commit"
    target = repo / ".git" / "hooks" / "pre-commit"
    if not target.parent.is_dir():
        return
    if target.exists() and target.read_bytes() == source.read_bytes():
        return
    target.write_bytes(source.read_bytes())
    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"  OK hook pre-commit -> {target}")


if __name__ == "__main__":
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Outils de securite -> {BIN_DIR}")
    fetch_gitleaks()
    install_precommit_hook()
    print("Termine.")
