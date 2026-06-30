"""
Nettoyage one-shot du modèle batch unifié (BATCH_MODEL_AUDIT.md, Niveau 0).

Recale tous les `batch.total` sur le nombre réel de membres et supprime les batches vidés,
sur les 8 apps. À lancer une fois sur la vraie base (WSL2) avant/après l'activation des signaux :

    python manage.py cleanup_batches
"""
from importlib import import_module

from django.core.management.base import BaseCommand

from wama.common.utils.batch_sync import resync_batches

# (module, classe Batch) — le modèle CONTENEUR (a .items + .total), pas le BatchItem.
BATCH_MODELS = [
    ('wama.transcriber.models', 'BatchTranscript'),
    ('wama.synthesizer.models', 'BatchSynthesis'),
    ('wama.describer.models', 'BatchDescription'),
    ('wama.reader.models', 'BatchReadingItem'),
    ('wama.enhancer.models', 'BatchEnhancement'),
    ('wama.enhancer.models', 'BatchAudioEnhancement'),
    ('wama.composer.models', 'ComposerBatch'),
    ('wama.avatarizer.models', 'BatchAvatarJob'),
    ('wama.anonymizer.models', 'BatchAnonymizer'),
]


class Command(BaseCommand):
    help = "Recale les batch.total sur le réel et supprime les batches vidés (8 apps)."

    def handle(self, *args, **opts):
        for mod_path, cls_name in BATCH_MODELS:
            try:
                model = getattr(import_module(mod_path), cls_name)
                resynced, deleted = resync_batches(model)
                self.stdout.write(f"{cls_name:>22} : {resynced} recalés, {deleted} vidés supprimés")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"{cls_name:>22} : SKIP ({e})"))
        self.stdout.write(self.style.SUCCESS("cleanup_batches terminé."))
