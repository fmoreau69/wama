"""
Rotation À LA DEMANDE des secrets WAMA (SECRET_KEY Django + mot de passe DB).

Conçue pour être *propre, tracée et prod-forward* :
  - lit/écrit les valeurs dans `.env` (quotées → pas d'interpolation dotenv) ;
  - change le mot de passe du rôle PostgreSQL **de la base courante**, avec
    vérification d'une nouvelle connexion PUIS rollback automatique si elle échoue ;
  - option `--also-wsl` : applique le MÊME mot de passe à la base *live* WSL2
    (infra à deux bases distinctes, cf. INFRA_WSL_VS_WINDOWS.md) ;
  - déplace l'ancienne SECRET_KEY dans DJANGO_SECRET_KEY_FALLBACKS → aucune
    session invalidée (zéro-downtime, utile en prod) ;
  - journalise chaque rotation dans `logs/secret_rotation.log` (SANS les valeurs).

En prod le code ne change pas : seule la *source* des variables d'env change
(systemd EnvironmentFile / Docker secrets / Vault). Sans `.env`, la commande
imprime les valeurs et le SQL au lieu d'écrire le fichier.

Exemples
--------
    # Tout roter (dev Windows) + propager à la base live WSL2, sans confirmation :
    python manage.py rotate_secrets --all --also-wsl --yes

    # Voir ce qui serait fait, sans rien changer :
    python manage.py rotate_secrets --all --dry-run

    # Seulement la clé Django :
    python manage.py rotate_secrets --secret-key
"""
import os
import sys
import string
import secrets as _secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.management.utils import get_random_secret_key
from django.db import connection, connections

# Alphabet du mot de passe DB : alphanumérique uniquement → aucun échappement
# nécessaire dans le SQL, PGPASSWORD, ou la ligne .env (pas de quote/$/#/espace).
_DB_PW_ALPHABET = string.ascii_letters + string.digits
_DB_PW_LEN = 32


def _gen_db_password() -> str:
    return ''.join(_secrets.choice(_DB_PW_ALPHABET) for _ in range(_DB_PW_LEN))


def _env_upsert(env_path: Path, updates: dict) -> None:
    """Insère/remplace des clés KEY='value' dans .env en préservant le reste.

    Les valeurs sont écrites entre guillemets SIMPLES : dotenv les prend alors
    littéralement (pas d'interpolation `$`, pas de commentaire `#`).
    """
    lines = env_path.read_text(encoding='utf-8').splitlines() if env_path.exists() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.lstrip()
        matched = None
        for key in remaining:
            if stripped.startswith(f'{key}='):
                matched = key
                break
        if matched:
            out.append(f"{matched}='{remaining.pop(matched)}'")
        else:
            out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append('')
        out.append('# — rotation rotate_secrets —')
        for key, val in remaining.items():
            out.append(f"{key}='{val}'")
    env_path.write_text('\n'.join(out) + '\n', encoding='utf-8')


def _log_rotation(rotated: list, targets: str) -> None:
    log_dir = Path(settings.BASE_DIR) / 'logs'
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
        who = os.environ.get('USERNAME') or os.environ.get('USER') or '?'
        line = f"{ts}  by={who}  rotated={','.join(rotated) or 'none'}  targets={targets}\n"
        (log_dir / 'secret_rotation.log').open('a', encoding='utf-8').write(line)
    except Exception:
        pass  # la traçabilité ne doit jamais faire échouer la rotation


class Command(BaseCommand):
    help = "Rotation à la demande des secrets (SECRET_KEY Django + mot de passe DB)."

    def add_arguments(self, parser):
        parser.add_argument('--secret-key', action='store_true', help="Roter la SECRET_KEY Django.")
        parser.add_argument('--db-password', action='store_true', help="Roter le mot de passe DB.")
        parser.add_argument('--all', action='store_true', help="Roter les deux (défaut si rien de précisé).")
        parser.add_argument('--also-wsl', action='store_true',
                            help="Appliquer le nouveau mot de passe DB à la base live WSL2 (via wsl.exe).")
        parser.add_argument('--env-file', default=None, help="Chemin du .env (défaut : BASE_DIR/.env).")
        parser.add_argument('--dry-run', action='store_true', help="Ne rien changer, montrer le plan.")
        parser.add_argument('--yes', action='store_true', help="Ne pas demander de confirmation.")

    # ── helpers DB ────────────────────────────────────────────────────────────
    def _alter_db_password(self, db_user: str, new_pw: str, use_conn=None):
        """ALTER USER sur la connexion Django courante (ou une donnée)."""
        conn = use_conn or connection
        # user/pw alphanumériques → inline sûr (identifiant "..." / littéral '...').
        with conn.cursor() as cur:
            cur.execute(f'ALTER USER "{db_user}" WITH PASSWORD \'{new_pw}\';')

    def _verify_new_password(self, new_pw: str) -> None:
        """Ouvre une connexion NEUVE avec le nouveau mot de passe (lève si KO)."""
        cfg = dict(connections.databases['default'])
        cfg['PASSWORD'] = new_pw
        connections.databases['_rotate_check'] = cfg
        try:
            connections['_rotate_check'].ensure_connection()
            connections['_rotate_check'].close()
        finally:
            connections.databases.pop('_rotate_check', None)
            try:
                connections['_rotate_check'].close()
            except Exception:
                pass

    def _rotate_wsl_db(self, db_user: str, db_name: str, old_pw: str, new_pw: str) -> str:
        """Applique le nouveau mot de passe à la base live WSL2. Retourne un statut."""
        if sys.platform != 'win32':
            return 'skip(non-Windows: la base "autre côté" se rote séparément)'
        inner = (f"PGPASSWORD='{old_pw}' psql -h 127.0.0.1 -U {db_user} -d {db_name} "
                 f"-v ON_ERROR_STOP=1 -c \"ALTER USER \\\"{db_user}\\\" WITH PASSWORD '{new_pw}';\"")
        try:
            r = subprocess.run(['wsl.exe', '-e', 'bash', '-lc', inner],
                               capture_output=True, text=True, timeout=60)
        except Exception as e:
            return f'fail({e})'
        return 'ok' if r.returncode == 0 else f'fail(rc={r.returncode}: {r.stderr.strip()[:200]})'

    # ── handle ────────────────────────────────────────────────────────────────
    def handle(self, *args, **opts):
        do_key = opts['secret_key'] or opts['all']
        do_pw = opts['db_password'] or opts['all']
        if not (do_key or do_pw):  # rien de précisé → tout
            do_key = do_pw = True
        dry = opts['dry_run']

        env_path = Path(opts['env_file']) if opts['env_file'] else Path(settings.BASE_DIR) / '.env'
        db = connections.databases['default']
        db_user, db_name = db['USER'], db['NAME']
        old_pw = db['PASSWORD']

        plan = []
        if do_key:
            plan.append("SECRET_KEY Django (ancienne → DJANGO_SECRET_KEY_FALLBACKS)")
        if do_pw:
            plan.append(f"mot de passe DB du rôle « {db_user} » (base courante {db_name}@{db['HOST']})")
            if opts['also_wsl']:
                plan.append("  ↳ + propagation à la base live WSL2 (--also-wsl)")

        self.stdout.write(self.style.MIGRATE_HEADING("Plan de rotation :"))
        for p in plan:
            self.stdout.write(f"  • {p}")
        self.stdout.write(f"  Fichier .env : {env_path}" + ("" if env_path.exists() else "  (absent → valeurs imprimées, non écrites)"))

        if dry:
            self.stdout.write(self.style.WARNING("\n--dry-run : rien n'a été modifié."))
            return

        if not opts['yes']:
            ans = input("\nConfirmer la rotation ? [y/N] ").strip().lower()
            if ans not in ('y', 'yes', 'o', 'oui'):
                raise CommandError("Annulé.")

        updates = {}
        rotated = []
        targets = []

        # ── SECRET_KEY ────────────────────────────────────────────────────────
        if do_key:
            new_key = get_random_secret_key()
            # empile l'ancienne clé en tête des fallbacks (dédupliquée)
            fbs = os.environ.get('DJANGO_SECRET_KEY_FALLBACKS', '').replace(',', ' ').split()
            if old := os.environ.get('DJANGO_SECRET_KEY'):
                fbs = [old] + [f for f in fbs if f != old]
            updates['DJANGO_SECRET_KEY'] = new_key
            if fbs:
                updates['DJANGO_SECRET_KEY_FALLBACKS'] = ' '.join(fbs[:3])  # garde 3 max
            rotated.append('secret_key')
            targets.append('.env')

        # ── mot de passe DB ───────────────────────────────────────────────────
        if do_pw:
            new_pw = _gen_db_password()
            self.stdout.write("→ ALTER USER sur la base courante…")
            try:
                self._alter_db_password(db_user, new_pw)
            except Exception as e:
                raise CommandError(f"ALTER USER a échoué (base courante) : {e}")
            # vérifie une connexion neuve, sinon rollback
            try:
                self._verify_new_password(new_pw)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Nouvelle connexion KO ({e}) → rollback."))
                try:
                    self._alter_db_password(db_user, old_pw)
                    self.stdout.write("  rollback OK (ancien mot de passe restauré).")
                except Exception as e2:
                    raise CommandError(f"ROLLBACK ÉCHOUÉ — rôle {db_user} peut être dans un état incohérent : {e2}")
                raise CommandError("Rotation DB annulée (base courante), rien d'écrit dans .env.")
            self.stdout.write(self.style.SUCCESS("  base courante OK (nouvelle connexion vérifiée)."))
            targets.append(f'{db_name}@{db["HOST"]}')

            # propagation WSL2 (best-effort mais tracé)
            if opts['also_wsl']:
                self.stdout.write("→ propagation à la base live WSL2…")
                status = self._rotate_wsl_db(db_user, db_name, old_pw, new_pw)
                if status == 'ok':
                    self.stdout.write(self.style.SUCCESS("  WSL2 live OK."))
                    targets.append('wsl2-live')
                else:
                    self.stderr.write(self.style.WARNING(
                        f"  WSL2 NON mise à jour : {status}\n"
                        f"  → applique manuellement le même mot de passe côté WSL2 :\n"
                        f'    wsl.exe -e bash -lc "PGPASSWORD=\'<ancien>\' psql -h 127.0.0.1 -U {db_user} '
                        f"-d {db_name} -c \\\"ALTER USER \\\\\\\"{db_user}\\\\\\\" WITH PASSWORD '<nouveau>';\\\"\""))

            updates['WAMA_DB_PASSWORD'] = new_pw
            rotated.append('db_password')

        # ── écriture .env (ou impression si absent) ───────────────────────────
        if env_path.exists():
            _env_upsert(env_path, updates)
            self.stdout.write(self.style.SUCCESS(f"\n.env mis à jour ({env_path})."))
        else:
            self.stdout.write(self.style.WARNING(
                "\n.env absent → à injecter par ton mécanisme d'env (systemd/docker/vault) :"))
            for k, v in updates.items():
                self.stdout.write(f"  {k}={v}")

        _log_rotation(rotated, ' + '.join(targets) or 'none')

        # ── consignes post-rotation ───────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\nÀ FAIRE ensuite :"))
        self.stdout.write("  • Redémarrer les process Django + Celery (WSL2) pour recharger .env.")
        if do_key:
            self.stdout.write("  • SECRET_KEY : sessions préservées via FALLBACKS ; retire l'ancienne clé "
                              "des fallbacks après quelques jours.")
        if do_pw and not opts['also_wsl'] and sys.platform == 'win32':
            self.stdout.write(self.style.WARNING(
                "  • Base LIVE WSL2 NON rotée (pas de --also-wsl) : relance avec --also-wsl "
                "ou applique le mot de passe côté WSL2, sinon l'app WSL2 ne se connectera plus."))
        self.stdout.write(self.style.SUCCESS("Rotation terminée."))
