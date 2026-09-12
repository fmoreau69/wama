"""Verse la galerie d'avatars PARTAGÉE dans la médiathèque, comme `SystemAsset`.

    python manage.py ingest_gallery_assets            # PLAN seul, n'écrit rien
    python manage.py ingest_gallery_assets --apply    # crée les lignes, puis déplace les fichiers

POURQUOI (demande Fabien, 2026-09-12)
    *« Les assets, gallery et voix devraient être gérés et stockés dans la médiathèque. »*
    La galerie était un DOSSIER (`avatarizer/gallery/`) parcouru à la main par trois sites Python
    et deux gabarits — six endroits pour neuf images — et sans aucun droit : lisible et servie à
    tous sans que personne ne l'ait décidé.

    `SystemAsset` est le modèle EXACT de ce qu'elle est : « asset générique partagé par tous les
    utilisateurs, géré par les admins, non supprimable par les utilisateurs finaux ». Il existait
    depuis le début ; la galerie l'ignorait.

⚠ LA CLÉ RESTE LE NOM DE FICHIER. `AvatarJob.avatar_gallery_name` STOCKE ce nom — frontière des
    DONNÉES, elle ne se renomme pas. `SystemAsset.name` reprend donc le nom À L'IDENTIQUE, de
    sorte que les jobs déjà en base continuent de résoudre : le stockage change, pas le contrat.

⚠ ORDRE : on crée la ligne AVANT de déplacer le fichier, et le déplacement est un `os.rename`
    dans la même transaction — si le rename échoue, la ligne disparaît avec lui. Même règle que
    `migrate_media_to_user_home`, pour la même raison : *une migration ne laisse jamais une ligne
    désigner un fichier qui n'a pas bougé.*

⚠ IDEMPOTENTE : un fichier déjà ingéré (nom déjà porté par un `SystemAsset`) est SAUTÉ, jamais
    ré-ingéré ni écrasé.
"""
import os
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

#: Dossier historique de la galerie, celui que trois sites parcouraient.
SOURCE = 'avatarizer/gallery'
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


class Command(BaseCommand):
    help = "Verse `avatarizer/gallery/` dans la médiathèque comme SystemAsset(avatar)"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Exécute réellement (sinon : PLAN seul, rien n'est écrit)")

    def handle(self, *args, **opts):
        from wama.media_library.models import SystemAsset

        racine = Path(settings.MEDIA_ROOT)
        dossier = racine / SOURCE
        appliquer = opts['apply']

        fichiers = sorted(f for f in dossier.iterdir()
                          if f.is_file() and f.suffix.lower() in EXTENSIONS) \
            if dossier.is_dir() else []
        deja = set(SystemAsset.objects.filter(asset_type='avatar')
                   .values_list('name', flat=True))
        a_faire = [f for f in fichiers if f.name not in deja]

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "GALERIE → MÉDIATHÈQUE — " + ("EXÉCUTION" if appliquer else "PLAN (rien n'est écrit)")))
        self.stdout.write(f"  dossier source      : {SOURCE}")
        self.stdout.write(f"  images trouvées     : {len(fichiers)}")
        self.stdout.write(f"  déjà en médiathèque : {len(fichiers) - len(a_faire)}   (sautées)")
        self.stdout.write(f"  à verser            : {len(a_faire)}")
        for f in a_faire:
            self.stdout.write(f"      {f.stat().st_size / 1e6:6.2f} Mo  {f.name}")

        if not appliquer:
            self.stdout.write("")
            self.stdout.write("  → relancer avec --apply pour exécuter")
            return

        verses, echecs = 0, []
        for f in a_faire:
            try:
                with transaction.atomic():
                    asset = SystemAsset(
                        name=f.name, asset_type='avatar',
                        mime_type=f"image/{f.suffix.lstrip('.').lower().replace('jpg', 'jpeg')}",
                        file_size=f.stat().st_size,
                        description="Avatar de la galerie partagée (versé le 2026-09-12 depuis "
                                    f"`{SOURCE}/`, qui était parcouru à la main).",
                    )
                    # `File` + `save` laisse `upload_to` décider du domicile (`media_library/
                    # system/`) : la commande ne construit AUCUN chemin, comme la brique
                    # « Sortie d'app → médiathèque » l'a décidé le 2026-09-12.
                    with open(f, 'rb') as fh:
                        asset.file.save(f.name, File(fh), save=False)
                    asset.save()
                # Le fichier est COPIÉ par le stockage Django : on retire l'original une fois la
                # ligne posée et le nouveau fichier écrit — jamais avant.
                if Path(asset.file.path).is_file() and Path(asset.file.path) != f:
                    os.remove(f)
                verses += 1
            except Exception as exc:
                echecs.append((f.name, f"{type(exc).__name__}: {exc}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"  versés : {verses} / {len(a_faire)}"))
        if echecs:
            self.stdout.write(self.style.ERROR(f"  ÉCHECS : {len(echecs)}"))
            for nom, e in echecs:
                self.stdout.write(f"    {nom} — {e}")
