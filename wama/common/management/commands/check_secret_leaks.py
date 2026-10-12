"""
check_secret_leaks — fuites de secrets dans l'HISTORIQUE GIT COMPLET (gitleaks),
lignes d'attribution dans les messages, et présence des hooks git qui empêchent d'en créer.

Contexte : l'historique a déjà été réécrit UNE fois (2026-07-23) pour purger des
secrets — l'opération qui rend caducs tous les SHA antérieurs. Ce contrôle rend la
récidive impossible en silence : le hook bloque AVANT le commit (scripts/git-hooks/
pre-commit), la nocturne re-balaie tout l'historique (1034 commits ≈ 3 s, vérifié
13/08 : 0 fuite — la réécriture est confirmée empiriquement, contrat = 0 à jamais).

Les hooks font partie du contrat : un hook absent ou dérivé de sa source versionnée
est une garde silencieusement morte → ROUGE, pas un warning (même maladie que les
seuils qui cessent de protéger, cf. nightly_scenarios.py). Depuis le 2026-10-12 ce
sont TOUS les hooks de scripts/git-hooks/ (fichiers sans extension) : pre-commit,
commit-msg (attribution) et pre-push (attribution + gitleaks sur ce qui part, le
seul à voir les commits faits par `git commit-tree`, qui n'exécute aucun hook).

Même contrat pour l'ATTRIBUTION : aucun message de commit des branches (locales et
distantes) ne porte de ligne `Co-Authored-By:` ni « Generated with … » — motifs
dans scripts/git-hooks/attribution.pattern, lus aussi par les deux hooks. Historique
réécrit le 2026-10-12 : contrat = 0.

Codes de sortie : 0 = historique propre + hooks en place + aucune attribution ;
1 = fuite, hook absent/dérivé OU attribution ; 3 = binaire gitleaks non provisionné
(la nocturne traduit en SKIP).

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
    help = "Fuites de secrets (gitleaks) et lignes d'attribution dans l'historique git + présence des hooks versionnés"

    def handle(self, *args, **o):
        w = self.stdout.write
        exe = binaire_gitleaks()
        if not exe.exists():
            w("gitleaks non provisionné — lancer : python scripts/fetch_security_tools.py")
            raise SystemExit(3)

        hooks_source = RACINE / "scripts" / "git-hooks"
        # un hook = un fichier SANS extension (même convention que fetch_security_tools.py)
        dead_hooks = [src.name for src in sorted(hooks_source.iterdir())
                      if src.is_file() and not src.suffix
                      and not ((RACINE / ".git" / "hooks" / src.name).exists()
                               and (RACINE / ".git" / "hooks" / src.name).read_bytes()
                               == src.read_bytes())]
        hook_ok = not dead_hooks
        if not hook_ok:
            w(f"Hook(s) ABSENT(S) ou dérivé(s) de scripts/git-hooks/ : {', '.join(dead_hooks)} "
              "(garde morte) — relancer : python scripts/fetch_security_tools.py")

        greps = [f"--grep={line}" for line in
                 (hooks_source / "attribution.pattern").read_text(encoding="utf-8").splitlines()
                 if line.strip()]
        attributed = subprocess.run(
            ["git", "-C", str(RACINE), "log", "--branches", "--remotes", "--format=%h %s",
             "-i", "-E", *greps],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.strip().splitlines()
        if attributed:
            w(f"{len(attributed)} commit(s) porteur(s) d'une ligne d'attribution "
              "(scripts/git-hooks/attribution.pattern) :")
            for line in attributed[:15]:
                w(f"  {line}")

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
          f"hooks {'en place' if hook_ok else 'MANQUANTS/DÉRIVÉS'}, "
          f"{'aucune attribution' if not attributed else f'{len(attributed)} ATTRIBUTION(S)'}.")
        if not (propre and hook_ok) or attributed:
            raise SystemExit(1)
