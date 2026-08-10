r"""TIRAGE de la base WAMA depuis un dump `pg_dump --format=custom`.

Pendant destructif de `backup_db`. **CLI UNIQUEMENT — jamais un bouton** : un clic mal placé
qui remplace la base de production n'a pas d'annulation, contrairement au tirage des modèles ou
des médias, qui ne fait qu'ajouter des fichiers.

Exemples :
    python manage.py restore_db --latest --dry-run     # liste le contenu, n'écrit rien
    python manage.py restore_db --latest --yes         # RESTAURE (destructif)
    python manage.py restore_db --dump backups/db/wama_db_2026-08-10_1704.dump --yes

Où trouver les dumps :
    local  : backups/db/
    distant: /mnt/shares/SAVES/DEEP_LEARNING/DB  (WSL) — \\vrlescot\SAVES\...\DB (Windows)

CE QUE LE DUMP NE CONTIENT PAS
==============================
`pg_dump --create` embarque le CREATE DATABASE (depuis le 2026-08-10), mais **pas le RÔLE** :
les rôles sont des objets de niveau CLUSTER, hors de portée d'un dump de base. Sur une machine
vierge il faut donc créer le rôle d'abord — la commande le détecte et affiche le SQL exact
plutôt que de tenter une élévation silencieuse.
"""

import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

LOCAL_DIR = Path(settings.BASE_DIR) / "backups" / "db"
PREFIX, SUFFIX = "wama_db_", ".dump"


class Command(BaseCommand):
    help = "Restaure la base WAMA depuis un dump pg_dump (DESTRUCTIF)."

    def add_arguments(self, parser):
        parser.add_argument("--dump", default=None, help="Chemin du fichier .dump.")
        parser.add_argument("--latest", action="store_true",
                            help="Prend le dump le plus récent (local, puis distant).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Affiche le contenu de l'archive sans rien restaurer.")
        parser.add_argument("--yes", action="store_true",
                            help="Confirme la restauration DESTRUCTIVE.")

    def _find_latest(self) -> Path:
        from wama.common.services.mirror_sync import resolve_remote_root

        candidats = []
        for directory in (LOCAL_DIR, Path(resolve_remote_root("DB", env_var="WAMA_DB_BACKUP_PATH"))):
            try:
                candidats.extend(directory.glob(f"{PREFIX}*{SUFFIX}"))
            except OSError:
                continue
        if not candidats:
            raise CommandError(
                f"Aucun dump trouvé dans {LOCAL_DIR} ni sur l'espace distant.")
        # Tri par NOM : les noms sont horodatés, et le mtime d'une copie réseau n'est pas fiable.
        return sorted(candidats, key=lambda p: p.name)[-1]

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        if "postgresql" not in db["ENGINE"]:
            raise CommandError(f"Moteur non supporté : {db['ENGINE']} (postgresql attendu)")

        if opts["dump"]:
            dump = Path(opts["dump"])
        elif opts["latest"]:
            dump = self._find_latest()
        else:
            raise CommandError("Préciser --dump <fichier> ou --latest.")

        if not dump.is_file():
            raise CommandError(f"Dump introuvable : {dump}")
        self.stdout.write(f"Dump : {dump} ({dump.stat().st_size / 1e6:.1f} Mo)")

        env = {**os.environ, "PGPASSWORD": db["PASSWORD"]}
        conn = ["-h", db["HOST"], "-p", str(db["PORT"]), "-U", db["USER"]]

        if opts["dry_run"]:
            proc = subprocess.run(["pg_restore", "--list", str(dump)],
                                  capture_output=True, text=True, timeout=300)
            if proc.returncode != 0:
                raise CommandError(f"pg_restore --list a échoué : {proc.stderr.strip()[:500]}")
            lignes = [l for l in proc.stdout.splitlines() if l and not l.startswith(";")]
            self.stdout.write(f"[dry-run] {len(lignes)} objets dans l'archive. Extrait :")
            for ligne in lignes[:15]:
                self.stdout.write(f"  {ligne}")
            self.stdout.write("[dry-run] Rien n'a été modifié.")
            return

        if not opts["yes"]:
            raise CommandError(
                f"OPÉRATION DESTRUCTIVE : la base « {db['NAME']} » sur {db['HOST']}:{db['PORT']} "
                f"sera SUPPRIMÉE et recréée depuis le dump.\n"
                f"Faire d'abord `--dry-run`, puis relancer avec --yes pour confirmer."
            )

        # `-d postgres` (base de maintenance) et non la base cible : `--create --clean` doit
        # pouvoir la SUPPRIMER, ce qui est impossible si l'on y est connecté.
        cmd = ["pg_restore", "--create", "--clean", "--if-exists",
               "--no-owner", "--no-acl", *conn, "-d", "postgres", str(dump)]
        self.stdout.write(f"Restauration de {db['NAME']} …")
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=7200)

        stderr = proc.stderr.strip()
        if proc.returncode != 0:
            if "role" in stderr and "does not exist" in stderr:
                raise CommandError(
                    f"{stderr[:400]}\n\n"
                    f"→ Le RÔLE n'existe pas : un dump de base ne le contient pas.\n"
                    f"   Le créer d'abord, en superutilisateur :\n"
                    f"   CREATE ROLE \"{db['USER']}\" LOGIN PASSWORD '<mot de passe du .env>';"
                )
            raise CommandError(f"pg_restore a échoué : {stderr[:800]}")

        # pg_restore sort en 0 avec des avertissements bénins (objets absents à nettoyer) :
        # les afficher sans les traiter comme un échec.
        if stderr:
            self.stdout.write(self.style.WARNING(f"Avertissements :\n{stderr[:800]}"))
        self.stdout.write(self.style.SUCCESS(f"✓ Base « {db['NAME']} » restaurée depuis {dump.name}"))
        self.stdout.write(self.style.WARNING(
            "→ Enchaîner `manage.py migrate` (écarts de schéma éventuels) puis `sync_models`."))
