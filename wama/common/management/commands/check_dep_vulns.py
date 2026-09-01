"""
check_dep_vulns — vulnérabilités connues (CVE) des dépendances Python INSTALLÉES,
via l'API OSV.dev (la même base d'avis que pip-audit, Dependabot ou Aikido).

Pourquoi « installées » et pas les requirements : les requirements du projet sont des
bornes basses (`>=`), ils ne disent pas ce qui tourne. La vérité est l'environnement
qui exécute cette commande — venv_linux quand la nocturne tourne sous WSL2 (le live),
venv_win depuis Windows. Zéro dépendance nouvelle : `requests` est déjà dans le socle,
l'inventaire vient d'`importlib.metadata`.

Contrat (même philosophie de cliquet que CIBLES_ASSUMEES, nightly_scenarios.py, mais à
l'échelle : ~170 avis sur la pile ML épinglée+patchée au triage initial du 2026-08-13,
inéditables à la main) : la dette CONNUE vit dans un fichier versionné,
`tools/security/osv_baseline.json`, une section par venv. Toute vulnérabilité ABSENTE
de la baseline = rouge ; une vulnérabilité de la baseline qui disparaît (upgrade) doit
en SORTIR (régénérer) — sinon le contrat cesse de protéger. La régénération est un
acte CONSCIENT : relire le diff git de la baseline, jamais la re-poser en aveugle
par-dessus du rouge.

Codes de sortie : 0 = rien de nouveau ; 1 = vulnérabilité(s) nouvelle(s) ou baseline
absente pour ce venv ; 3 = API OSV injoignable (la nocturne traduit en SKIP).

Usage :
    python manage.py check_dep_vulns              # audit + verdict contre la baseline
    python manage.py check_dep_vulns --list       # détail complet, assumées comprises
    python manage.py check_dep_vulns --baseline   # (ré)écrit la section de CE venv
"""
import json
import sys
from importlib import metadata
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

def _osv_api() -> str:
    """Point d'entrée OSV — adresse déclarée au registre commun des sources externes."""
    from wama.common.external_sources import base_url
    return base_url('osv') + '/querybatch'

LOT = 500          # taille max de lot côté API : 1000 ; marge
TIMEOUT_S = 60

BASELINE = Path(settings.BASE_DIR) / "tools" / "security" / "osv_baseline.json"


def label_venv() -> str:
    """Nom du venv qui exécute (venv_win / venv_linux) = clé de section de la baseline."""
    return Path(sys.prefix).name or "env-inconnu"


def inventaire() -> list[tuple[str, str]]:
    """(nom, version) des distributions installées dans CET interpréteur."""
    vus = set()
    for d in metadata.distributions():
        nom = (d.metadata.get("Name") or "").strip().lower()
        if nom and d.version:
            vus.add((nom, d.version))
    return sorted(vus)


def interroger_osv(paquets: list[tuple[str, str]]) -> dict[str, list[str]]:
    """{"nom==version": [ids OSV]} — lève si l'API est injoignable."""
    import requests
    touches: dict[str, list[str]] = {}
    for i in range(0, len(paquets), LOT):
        lot = paquets[i:i + LOT]
        corps = {"queries": [
            {"package": {"name": nom, "ecosystem": "PyPI"}, "version": version}
            for nom, version in lot
        ]}
        rep = requests.post(_osv_api(), json=corps, timeout=TIMEOUT_S)
        rep.raise_for_status()
        for (nom, version), res in zip(lot, rep.json().get("results", [])):
            ids = sorted(v["id"] for v in (res or {}).get("vulns", []))
            if ids:
                touches[f"{nom}=={version}"] = ids
    return touches


class Command(BaseCommand):
    help = "Vulnérabilités connues (OSV.dev) des paquets installés, contre la baseline versionnée"

    def add_arguments(self, parser):
        parser.add_argument('--list', action='store_true',
                            help="détail complet, assumées comprises")
        parser.add_argument('--baseline', action='store_true',
                            help="(ré)écrit la section de ce venv dans la baseline — acte conscient")

    def handle(self, *args, **o):
        w = self.stdout.write
        venv = label_venv()
        paquets = inventaire()
        try:
            touches = interroger_osv(paquets)
        except Exception as exc:
            w(f"API OSV injoignable ({type(exc).__name__}: {exc}) — audit non joué.")
            raise SystemExit(3)

        base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}

        if o['baseline']:
            # Pas de date DANS le fichier : elle vit dans son historique git (diff minimal).
            base[venv] = {"vulns": touches}
            BASELINE.write_text(json.dumps(base, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                                encoding="utf-8")
            n = sum(len(v) for v in touches.values())
            w(f"Baseline [{venv}] écrite : {n} id(s) sur {len(touches)} paquet(s) touché(s) "
              f"({len(paquets)} installés). Relire le diff git avant de commiter.")
            return

        if venv not in base:
            w(f"Aucune section [{venv}] dans {BASELINE.name} — lancer --baseline (acte conscient).")
            raise SystemExit(1)

        assumes = {i for ids in base[venv]["vulns"].values() for i in ids}
        trouves = {i for ids in touches.values() for i in ids}
        nouveaux, disparues = trouves - assumes, assumes - trouves

        for paquet, ids in sorted(touches.items()):
            neufs = [i for i in ids if i in nouveaux]
            if neufs:
                w(f"NOUVEAU  {paquet} : {', '.join(neufs)}")
            elif o['list']:
                w(f"assumé   {paquet} : {', '.join(ids)}")
        if disparues:
            w(f"DISPARUE(S) : {len(disparues)} id(s) de la baseline ne sont plus présents "
              f"(upgrade ?) — régénérer avec --baseline pour faire décroître le contrat.")

        w("")
        w(f"Bilan : {len(nouveaux)} nouvelle(s), {len(trouves & assumes)} assumée(s), "
          f"{len(disparues)} disparue(s), sur {len(paquets)} paquet(s) installé(s) [{venv}].")
        if nouveaux:
            raise SystemExit(1)
