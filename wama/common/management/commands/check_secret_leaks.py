"""
check_secret_leaks — fuites de secrets dans l'HISTORIQUE GIT COMPLET (gitleaks),
et présence du hook pre-commit qui empêche d'en créer de nouvelles.

Contexte : l'historique a déjà été réécrit UNE fois (2026-07-23) pour purger des
secrets — l'opération qui rend caducs tous les SHA antérieurs. Ce contrôle rend la
récidive impossible en silence : le hook bloque AVANT le commit (scripts/git-hooks/
pre-commit), la nocturne re-balaie tout l'historique (1034 commits ≈ 3 s, vérifié
13/08 : 0 fuite — la réécriture est confirmée empiriquement, contrat = 0 à jamais).

Le hook fait partie du contrat : un hook absent ou dérivé de sa source versionnée
est une garde silencieusement morte → ROUGE, pas un warning (même maladie que les
seuils qui cessent de protéger, cf. nightly_scenarios.py).

Codes de sortie : 0 = historique propre + hook en place ; 1 = fuite OU hook
absent/dérivé ; 3 = binaire gitleaks non provisionné (la nocturne traduit en SKIP).

Usage :
    python manage.py check_secret_leaks
Provisioning : python scripts/fetch_security_tools.py (binaire + hook).
"""
import platform
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

RACINE = Path(settings.BASE_DIR)
TIMEOUT_S = 240


def binaire_gitleaks() -> Path:
    nom = "gitleaks.exe" if platform.system() == "Windows" else "gitleaks"
    return RACINE / "tools" / "security" / "bin" / nom


class Command(BaseCommand):
    help = "Fuites de secrets dans l'historique git + présence du hook pre-commit (gitleaks)"

    def handle(self, *args, **o):
        w = self.stdout.write
        exe = binaire_gitleaks()
        if not exe.exists():
            w("gitleaks non provisionné — lancer : python scripts/fetch_security_tools.py")
            raise SystemExit(3)

        source = RACINE / "scripts" / "git-hooks" / "pre-commit"
        hook = RACINE / ".git" / "hooks" / "pre-commit"
        hook_ok = hook.exists() and hook.read_bytes() == source.read_bytes()
        if not hook_ok:
            w("Hook pre-commit ABSENT ou dérivé de scripts/git-hooks/pre-commit "
              "(garde morte) — relancer : python scripts/fetch_security_tools.py")

        # --redact : ne jamais imprimer un secret en clair dans les logs/rapports.
        res = subprocess.run(
            [str(exe), "git", "--redact", "--no-banner", str(RACINE)],
            capture_output=True, text=True, timeout=TIMEOUT_S,
        )
        sortie = (res.stderr or res.stdout or "").strip().splitlines()
        propre = res.returncode == 0
        if not propre:
            for ligne in sortie[-15:]:
                w(ligne)

        w("")
        w(f"Bilan : historique {'propre' if propre else 'AVEC FUITE(S)'}, "
          f"hook pre-commit {'en place' if hook_ok else 'MANQUANT/DÉRIVÉ'}.")
        if not (propre and hook_ok):
            raise SystemExit(1)
