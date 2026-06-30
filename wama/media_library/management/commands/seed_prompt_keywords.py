"""
Seed du TRONC COMMUN de mots-clés de prompt (PromptKeyword, user=None) — bibliothèque curée,
inspirée des bonnes pratiques des meilleurs outils de génération (SDXL/Midjourney/Flux/Lexica).
Idempotent (get_or_create). Extensible : ajouter des entrées ici, ou via l'UI médiathèque (perso).
"""
from django.core.management.base import BaseCommand

# {catégorie: [mots-clés]} — tronc commun partagé (user=None).
TRUNK = {
    'quality': ['haute qualité', 'ultra-détaillé', 'photoréaliste', 'netteté élevée', '8k', 'HDR',
                'rendu professionnel'],
    'style':   ['cinématique', 'concept art', 'peinture à l\'huile', 'aquarelle', 'anime', 'pixel art',
                'photographie de studio', 'illustration', 'hyperréaliste', 'minimaliste'],
    'light':   ['golden hour', 'clair-obscur', 'lumière douce', 'contre-jour', 'néon', 'lumière dramatique',
                'éclairage cinématographique', 'heure bleue'],
    'mood':    ['sombre', 'éclatant', 'onirique', 'mélancolique', 'épique', 'chaleureux', 'futuriste',
                'nostalgique'],
    'camera':  ['bokeh', 'profondeur de champ', 'grand-angle', 'macro', 'objectif 35mm', 'objectif 85mm',
                'vue plongeante', 'gros plan'],
    'render':  ['film grain', 'rendu Octane', 'Unreal Engine', 'rétro 70s', 'noir et blanc', 'sépia',
                'style polaroid'],
    'domain':  ['scène routière', 'vue caméra embarquée', 'environnement urbain', 'intérieur de véhicule'],
}


class Command(BaseCommand):
    help = "Seed le tronc commun de mots-clés de prompt (PromptKeyword partagés, user=None)."

    def handle(self, *args, **opts):
        from wama.media_library.models import PromptKeyword
        created = 0
        for category, words in TRUNK.items():
            for i, text in enumerate(words):
                _, was_created = PromptKeyword.objects.get_or_create(
                    user=None, category=category, text=text,
                    defaults={'order': i},
                )
                created += int(was_created)
        total = PromptKeyword.objects.filter(user__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"Tronc commun : {created} mot(s)-clé(s) ajouté(s), {total} au total (partagés)."
        ))
