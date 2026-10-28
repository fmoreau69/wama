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

PERTE PARTIELLE (2026-10-27, `media/` effacé puis restauré) : `--missing-only` ne copie que les
fichiers ABSENTS en local — sans lui, un fichier modifié depuis la sauvegarde (taille différente)
serait écrasé par sa version ancienne. Procédure complète : skill `restauration`.

PÉRIMÈTRE (2026-10-28) : `--known-only` ne tire que ce que la base connaît encore — dossiers des
comptes réels, médiathèque, et ailleurs ce qu'une card référence (`known_media`). Sans lui, le
tirage ramène aussi les dossiers de comptes de test, de comptes supprimés et d'anciennes apps.

Exemples :
    python manage.py restore_backup --domain media --dry-run --missing-only --known-only
    python manage.py restore_backup --domain media --dry-run --missing-only
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


def known_media():
    """Le prédicat du tirage BORNÉ (`--known-only`, décision de Fabien du 2026-10-28) : la
    sauvegarde ne supprime jamais rien, elle garde donc les dossiers de comptes de TEST, de comptes
    SUPPRIMÉS et les anciens dossiers d'app. Voyagent : les domiciles des données réelles
    (`media_guard.DATA_HOMES`) — `users/<id>/` d'un compte réel encore en base, la médiathèque —
    et, ailleurs, ce qu'une card référence encore (`file_references.referenced_paths`), sauf la
    card d'un compte de TEST : ce qu'il porte, ce sont ses témoins, où qu'ils soient rangés
    (mesuré le 2026-10-28 : un témoin `imager/54/output/…` de l'ancienne disposition). Et un
    FICHIER posé à la racine de `media/` : il n'appartient à aucune app ni à aucun compte, seul
    l'utilisateur l'y a mis (`MEDIA_STORAGE_TIERING §8bis` : les deux `WAMA_Presentation*.wav` de
    Fabien) — la restauration du 27/10 avait manqué celui qu'aucune card ne référence."""
    from collections import defaultdict

    from django.apps import apps
    from django.contrib.auth import get_user_model
    from wama.common.services.nightly_tests import is_test_account
    from wama.common.utils.file_references import referenced_paths
    from wama.common.utils.media_guard import DATA_HOMES
    users_home, library_home = DATA_HOMES
    real, test = set(), set()
    for user in get_user_model().objects.all():
        (test if is_test_account(user) else real).add(str(user.pk))
    refs = referenced_paths(detail=True)
    cards = defaultdict(set)
    for label, _field, pk in refs.values():
        cards[label].add(pk)
    witnesses = set()
    for label, pks in cards.items():
        model = apps.get_model(label)
        if any(f.attname == 'user_id' for f in model._meta.concrete_fields):
            witnesses |= {(label, pk) for pk, owner in
                          model.objects.filter(pk__in=pks).values_list('pk', 'user_id')
                          if str(owner) in test}
    referenced = {path for path, (label, _field, pk) in refs.items()
                  if (label, pk) not in witnesses}

    def keep(rel: str) -> bool:
        head, _, rest = rel.partition('/')
        if not rest:                    # un fichier à la racine : à l'utilisateur, il voyage
            return True
        if head == users_home:
            owner = rest.split('/', 1)[0]
            return owner in real or (owner not in test and rel in referenced)
        return head == library_home or rel in referenced
    return keep


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
        parser.add_argument('--missing-only', action='store_true',
                            help="Ne copie QUE les fichiers absents en local : un fichier présent "
                                 "n'est jamais écrasé, même de taille différente (perte partielle).")
        parser.add_argument('--known-only', action='store_true',
                            help="[media] Ne tire que ce que la base connaît encore : dossiers des "
                                 "comptes réels, médiathèque, et ailleurs ce qu'une card référence.")

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
        # écrasé par la version sauvegardée — donc confirmation explicite, sauf `--missing-only`
        # (perte PARTIELLE, 2026-10-27) : alors rien de local n'est jamais écrasé.
        if opts['overwrite'] and opts['missing_only']:
            raise CommandError("--overwrite et --missing-only s'excluent.")
        deja = any(local.rglob('*'))
        if deja and not (opts['dry_run'] or opts['yes'] or opts['missing_only']):
            raise CommandError(
                f"{local} n'est pas vide : un tirage peut y écraser des fichiers.\n"
                f"Mesurer d'abord avec --dry-run, puis confirmer avec --yes "
                f"(ou --missing-only : ne copier que les fichiers absents)."
            )

        result = mirror_tree(
            remote, local,
            overwrite=opts['overwrite'],
            keep_existing=opts['missing_only'],
            keep=known_media() if opts['known_only'] else None,
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
        if opts['known_only'] and opts['domain'] != 'media':
            raise CommandError("--known-only ne vaut que pour --domain media.")
        if opts['domain'] == 'config':
            self._restore_config(opts)
        else:
            self._restore_tree(opts['domain'], opts)

        if not opts['dry_run'] and opts['domain'] == 'models':
            self.stdout.write(self.style.WARNING(
                "→ Enchaîner `manage.py sync_models` pour réconcilier le catalogue et le disque."))
