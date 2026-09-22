"""
Management command : télécharge les voix de référence manquantes — dans la MÉDIATHÈQUE.

Usage :
    python manage.py download_voice_refs
    python manage.py download_voice_refs --force
    python manage.py download_voice_refs --force --names french/adult/female_adult_1_fr ...

Depuis le 2026-09-13 (MEDIA_STORAGE_TIERING §9.4), une voix téléchargée devient une ligne
`SystemAsset(voice)` avec ses attributs (langue/âge/genre) et sa provenance — plus un fichier
nu dans un dossier.
"""

import logging
import os
import sys

from django.core.management.base import BaseCommand

from wama.common.tts.voice_refs import (
    VOICE_DOWNLOAD_CATALOG,
    _VOICE_DATASETS_CATALOG,
    download_missing_voice_refs,
)


def exit_skipping_native_teardown(code: int) -> None:
    """Sort du processus SANS la destruction de fin d'interpréteur — après avoir tout rendu.

    ⚠ POURQUOI (bissection du 2026-09-22) : la lecture en flux du corpus VoxPopuli
    (bibliothèque HuggingFace `datasets`, rien à voir avec les manifestes `dataset`) laisse
    un fil NATIF (pile pyarrow/aiohttp) qui plante pendant la fermeture de l'interpréteur —
    `Fatal Python error: PyGILState_Release … finalizing`, sortie 139 ou 134 — alors que le
    travail est TERMINÉ et écrit. Reproduit par un script minimal (ouvrir le flux, lire un
    élément, sortir) ; le plantage persiste sans torch, sans le moniteur de tqdm, et après
    libération explicite du flux : il ne vient d'aucun objet que Python sache fermer.
    Un code 139 ment sur une commande réussie, et un appelant qui le lit croit à un échec.

    Tout ce que la fermeture normale aurait rendu l'est ici, explicitement : sorties vidées,
    journaux fermés, connexions à la base closes. Ne sert QU'EN ligne de commande — jamais
    depuis `call_command` (les tests, un autre appelant) : sortir du processus les tuerait.
    """
    from django.db import connections
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    logging.shutdown()
    connections.close_all()
    os._exit(code)


class Command(BaseCommand):
    help = 'Télécharge les voix de référence manquantes dans la médiathèque (SystemAsset voice)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-télécharge même si la voix est déjà en médiathèque (le fichier est remplacé)',
        )
        parser.add_argument(
            '--names', nargs='+', default=None,
            help="Restreint le passage à ces voix (ex. celles dont la mesure a contredit le "
                 "libellé, MEDIA_STORAGE_TIERING §9.4bis)",
        )

    def handle(self, *args, **options):
        force = options['force']
        names = options['names']
        unknown = sorted(set(names or []) - (set(VOICE_DOWNLOAD_CATALOG) | set(_VOICE_DATASETS_CATALOG)))
        if unknown:
            # Un nom mal tapé serait sinon ignoré EN SILENCE : on croirait l'avoir retéléchargé.
            self.stderr.write(self.style.ERROR(f"Voix absentes du catalogue : {unknown}"))
            return
        total = len(set(VOICE_DOWNLOAD_CATALOG) | set(_VOICE_DATASETS_CATALOG))

        self.stdout.write("Cible : médiathèque — SystemAsset(asset_type='voice')")
        self.stdout.write(f"Voix dans le catalogue : {total}")
        if force:
            self.stdout.write(self.style.WARNING("Mode --force : re-téléchargement forcé"))
        self.stdout.write("")

        results = download_missing_voice_refs(force=force, names=names)

        for name, status in results.items():
            if status == 'downloaded':
                self.stdout.write(self.style.SUCCESS(f"  ✓  {name}"))
            elif status == 'skipped':
                self.stdout.write(f"  –  {name} (déjà en médiathèque)")
            else:
                self.stdout.write(self.style.ERROR(f"  ✗  {name} (échec — vérifier les logs)"))

        n_ok = sum(1 for s in results.values() if s == 'downloaded')
        n_skip = sum(1 for s in results.values() if s == 'skipped')
        n_fail = sum(1 for s in results.values() if s == 'failed')

        self.stdout.write("")
        self.stdout.write(f"Résultat : {n_ok} téléchargées, {n_skip} déjà présentes, {n_fail} échec(s)")

        if n_fail:
            self.stdout.write(self.style.WARNING(
                "\nPour les voix en échec, déposez un WAV (6-10 s, voix claire) dans la médiathèque "
                "(type Voix) avec ses attributs langue / âge / genre."))

        # En ligne de commande SEULEMENT (Django pose ce drapeau dans `run_from_argv`, jamais
        # `call_command`) : sortie sans la destruction native qui plante — voir la fonction.
        # Le code dit enfin la vérité : 0, ou 1 s'il y a eu des échecs.
        if getattr(self, '_called_from_command_line', False):
            exit_skipping_native_teardown(1 if n_fail else 0)
