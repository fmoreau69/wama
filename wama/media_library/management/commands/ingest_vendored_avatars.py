"""Verse les avatars 3D VENDORISÉS (celui de l'assistant) dans la médiathèque, comme `SystemAsset`.

    python manage.py ingest_vendored_avatars            # PLAN seul, n'écrit rien
    python manage.py ingest_vendored_avatars --apply    # crée les lignes (fichiers COPIÉS)

POURQUOI (demande de Fabien, 2026-10-21)
    *« Je ne peux pas générer d'avatar TalkingHead, car pas d'objet 3D disponible dans la
    médiathèque. Il faudrait au moins ajouter celui de base de l'assistant. »* L'assistant parle
    avec `vendors/avatars/brunette.glb`, posé par `tools/update_vendors.sh` ; le moteur
    `talkinghead` de l'avatarizer, lui, ne désigne qu'un `object3d` de la médiathèque — il n'en
    existait aucun.

CE QUI EST REPRIS, PAS RÉÉCRIT
    - la licence et l'auteur : ceux que le dépôt PUBLIE, lus dans `providers/avatars3d.py`
      (`AVATAR_REPOSITORIES`) — un fichier dont la licence n'y est pas déclarée n'est PAS versé,
      même règle que le fournisseur ;
    - les attributs (rig, visage ARKit, visèmes) : MESURÉS dans le fichier par la sonde commune
      (`enrich_asset_from_file`), comme pour tout dépôt ;
    - l'écriture : `system_files.ingest_system_file` (idempotente — un nom déjà porté est sauté).

⚠ Le fichier est COPIÉ (`media_library/system/object3d/`) : l'original reste servi à l'assistant.
"""
from pathlib import Path

from django.core.management.base import BaseCommand

#: Le dossier où `tools/update_vendors.sh` dépose les avatars (chemin STATIQUE).
VENDORED_AVATARS = 'vendors/avatars'


def vendored_folder() -> Path | None:
    from django.contrib.staticfiles import finders
    found = finders.find(VENDORED_AVATARS)
    return Path(found) if found and Path(found).is_dir() else None


def plan(folder: Path) -> list:
    """Une entrée par `.glb` du dossier : {path, name, source, license, author, existing}."""
    from wama.media_library.models import SystemAsset
    from wama.media_library.providers.avatars3d import AVATAR_REPOSITORIES
    entries = []
    for path in sorted(folder.glob('*.glb')):
        source = next((s for s in AVATAR_REPOSITORIES if s.license_of(path.name)[0]), None)
        license_, author = source.license_of(path.name) if source else ('', '')
        entries.append({
            'path': path, 'name': path.stem, 'source': source, 'license': license_,
            'author': author,
            'existing': SystemAsset.objects.filter(name=path.stem).exists()})
    return entries


def ingest(entry: dict):
    """Verse UNE entrée du plan ; rend le `SystemAsset`."""
    from wama.media_library.services import enrich_asset_from_file
    from wama.media_library.system_files import ingest_system_file
    asset = ingest_system_file(
        'object3d', entry['name'], entry['path'], mime_type='model/gltf-binary',
        source_url=entry['source'].raw_url(entry['path'].name), license=entry['license'],
        author=entry['author'],
        description="Avatar 3D de l'assistant (TalkingHead) — riggé, visage ARKit et visèmes : "
                    "le moteur TalkingHead de l'avatarizer le fait parler.")
    enrich_asset_from_file(asset)
    asset.save()
    return asset


class Command(BaseCommand):
    help = "Verse les avatars 3D vendorisés (celui de l'assistant) dans la médiathèque"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Exécute réellement (sinon : PLAN seul, rien n'est écrit)")
        parser.add_argument('--folder', default='',
                            help=f"Dossier à verser (défaut : le statique `{VENDORED_AVATARS}/`)")

    def handle(self, *args, **opts):
        folder = Path(opts['folder']) if opts['folder'] else vendored_folder()
        if folder is None or not folder.is_dir():
            self.stdout.write(self.style.WARNING(
                f"Aucun dossier `{VENDORED_AVATARS}/` : lancer d'abord `bash tools/update_vendors.sh`."))
            return
        entries = plan(folder)
        self.stdout.write(self.style.MIGRATE_HEADING(
            "AVATARS VENDORISÉS → MÉDIATHÈQUE — "
            + ("EXÉCUTION" if opts['apply'] else "PLAN (rien n'est écrit)")))
        for e in entries:
            if e['existing']:
                verdict = 'déjà en médiathèque (sauté)'
            elif not e['source']:
                verdict = 'licence non déclarée (jamais versé)'
            else:
                verdict = f"à verser — {e['license']}, {e['author']}"
            self.stdout.write(f"  {e['path'].name:<24} {verdict}")
        todo = [e for e in entries if e['source'] and not e['existing']]
        if not opts['apply']:
            if todo:
                self.stdout.write("  → relancer avec --apply pour exécuter")
            return
        for e in todo:
            asset = ingest(e)
            self.stdout.write(self.style.SUCCESS(
                f"  versé : {asset.name} → {asset.file.name} {asset.attributes}"))
