"""
TIRAGE — restaure modèles / médias / secrets depuis l'espace distant vers le local.

Pendant exact des sauvegardes, dans l'autre sens :
    sauvegarde : local  → NAS   (`backup_all_models`, `backup_all_media`, `backup_config`)
    tirage     : NAS    → local (ici)

Le moteur est le MÊME (`common/services/mirror_sync.mirror_tree`) — il n'y a pas de second
mécanisme de copie dans le projet, et il ne faut pas en écrire un.

ASYMÉTRIE À CONNAÎTRE
=====================
`exclude={'~Archives'}` n'est nécessaire QUE dans ce sens. `~Archives` est l'ancien contenu de
l'espace médias, mis de côté sur le NAS le 2026-08-10 ; il n'appartient pas à l'arbre vivant et
ne doit pas atterrir dans `media/`. Dans le sens sauvegarde le problème n'existe pas : le miroir
n'itère que sur le local, où ce dossier n'existe pas.

RÉINSTALLATION COMPLÈTE — ORDRE IMPOSÉ
======================================
    1. `restore_backup --domain config`   → récupère `.env` (mot de passe DB inclus)
    2. `restore_db --dump <fichier>`      → schéma + données + catalogue AIModel
    3. `restore_backup --domain models`
    4. `restore_backup --domain media`
    5. `manage.py sync_models`            → réconcilie catalogue ↔ disque

Exemples :
    python manage.py restore_backup --domain media --dry-run
    python manage.py restore_backup --domain models --yes
    python manage.py restore_backup --domain config --force
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from wama.common.services.mirror_sync import (
    copy_file,
    mirror_tree,
    remote_is_available,
    resolve_remote_root,
)


def _domains() -> dict:
    """
    Table des domaines tirables. Construite à l'appel (et non au chargement) pour que
    `override_settings` reste effectif en test.
    """
    return {
        'models': {
            'remote': resolve_remote_root('MODELS', env_var='WAMA_MODEL_BACKUP_PATH'),
            'local': Path(settings.AI_MODELS_DIR) / 'models',
            'exclude': None,
        },
        'media': {
            'remote': resolve_remote_root('MEDIAS', env_var='WAMA_MEDIA_BACKUP_PATH'),
            'local': Path(settings.MEDIA_ROOT),
            # Voir l'asymétrie documentée en tête de module.
            'exclude': {'~Archives'},
        },
    }


class Command(BaseCommand):
    help = "Restaure modèles / médias / secrets depuis l'espace de sauvegarde distant."

    def add_arguments(self, parser):
        parser.add_argument('--domain', required=True, choices=('models', 'media', 'config'),
                            help="Domaine à restaurer.")
        parser.add_argument('--dry-run', action='store_true',
                            help="Mesure l'écart sans rien écrire (à faire en premier).")
        parser.add_argument('--yes', action='store_true',
                            help="Confirme l'écriture quand la destination locale n'est PAS vide.")
        parser.add_argument('--force', action='store_true',
                            help="[config] écrase un `.env` local existant.")
        parser.add_argument('--overwrite', action='store_true',
                            help="Recopie même les fichiers déjà présents à l'identique.")

    # ------------------------------------------------------------------ config
    def _restore_config(self, opts):
        from wama.common.services.config_backup import CONFIG_FILES, remote_config_path

        remote_root = Path(remote_config_path())
        if not remote_is_available(remote_root):
            raise CommandError(f"Espace distant indisponible : {remote_root}")

        base = Path(settings.BASE_DIR)
        for name in CONFIG_FILES:
            source, dest = remote_root / name, base / name
            if not source.is_file():
                self.stderr.write(self.style.WARNING(f"⚠ Absent à distance : {source}"))
                continue
            if opts['dry_run']:
                etat = "ÉCRASERAIT" if dest.exists() else "créerait"
                self.stdout.write(f"[dry-run] {etat} {dest} depuis {source}")
                continue
            # Un `.env` existant contient peut-être des secrets plus récents que la
            # sauvegarde : jamais d'écrasement implicite.
            if dest.exists() and not opts['force']:
                raise CommandError(
                    f"{dest} existe déjà. Relancer avec --force pour l'écraser "
                    f"(ou le sauvegarder d'abord : `manage.py backup_config`)."
                )
            ok, _, error = copy_file(source, dest)
            if not ok:
                raise CommandError(f"Restauration de {name} impossible : {error}")
            self.stdout.write(self.style.SUCCESS(f"✓ {dest} restauré depuis {source}"))
            self.stdout.write(self.style.WARNING(
                "  ⚠ Vérifier les droits du fichier (il contient des secrets)."))

    # ------------------------------------------------- models / media (miroir)
    def _restore_tree(self, domain, opts):
        spec = _domains()[domain]
        remote, local = Path(spec['remote']), Path(spec['local'])

        if not remote_is_available(remote):
            raise CommandError(f"Espace distant indisponible : {remote}")
        local.mkdir(parents=True, exist_ok=True)

        # Garde-fou : sur une installation NEUVE la destination est vide et il n'y a rien à
        # protéger. Sur une installation VIVANTE, un fichier local de taille différente serait
        # écrasé par la version sauvegardée — donc confirmation explicite.
        deja = any(local.rglob('*'))
        if deja and not (opts['dry_run'] or opts['yes']):
            raise CommandError(
                f"{local} n'est pas vide : un tirage peut y écraser des fichiers.\n"
                f"Mesurer d'abord avec --dry-run, puis confirmer avec --yes."
            )

        result = mirror_tree(
            remote, local,
            overwrite=opts['overwrite'],
            exclude=spec['exclude'],
            dry_run=opts['dry_run'],
        )

        tag = '[dry-run] ' if opts['dry_run'] else ''
        verbe = 'à copier' if opts['dry_run'] else 'copiés'
        self.stdout.write(
            f"{tag}{remote} → {local}\n"
            f"  {result['total_files']} fichiers distants, {result['copied']} {verbe} "
            f"({result['copied_mb'] / 1024:.2f} Go), {result['skipped']} déjà identiques, "
            f"{result['failed']} échecs"
        )
        for err in result['errors'][:10]:
            self.stderr.write(self.style.WARNING(f"  ! {err}"))
        if not result['success']:
            raise CommandError("Tirage terminé AVEC des échecs (voir ci-dessus).")

    def handle(self, *args, **opts):
        if opts['domain'] == 'config':
            self._restore_config(opts)
        else:
            self._restore_tree(opts['domain'], opts)

        if not opts['dry_run'] and opts['domain'] == 'models':
            self.stdout.write(self.style.WARNING(
                "→ Enchaîner `manage.py sync_models` pour réconcilier le catalogue et le disque."))
