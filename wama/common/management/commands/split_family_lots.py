"""Donne LEUR lot aux cards dérivées des familles nées avant le 2026-11-23.

Jusqu'à cette date, séparer une card en pistes la changeait en lot : la source et ses pistes
étaient les filles d'un même lot. Décision de Fabien (19/11, option B) : un morceau seul reste une
card seule, ses pistes vont dans un lot à elles que la file montre sous lui
(`derived_cards.family_lot`, `batch_common.nest_derived_lots`). Les familles nouvelles naissent
ainsi ; celles d'avant gardent leur ancienne forme tant que cette commande n'est pas passée —
elles marchent, mais s'affichent encore comme un lot.

Sans `--apply`, la commande COMPTE et ne change rien (mesurer sur le réel avant d'écrire). Seul un
lot fait d'une source et de ses seules cards dérivées est concerné (`family_in_one_lot`) : un lot
que l'utilisateur a composé — plusieurs morceaux, ou des cards venues d'ailleurs — n'est jamais
touché. Les lignes sont déplacées, aucun fichier n'est lu ni écrit.

    python manage.py split_family_lots            # compte
    python manage.py split_family_lots --apply    # déplace
"""
from django.apps import apps as django_apps
from django.core.management.base import BaseCommand

from wama.common.models import DerivedCardMixin
from wama.common.utils.batch_common import batch_model_for, batch_of
from wama.common.utils.derived_cards import family_in_one_lot, split_family


class Command(BaseCommand):
    help = "Donne leur propre lot aux cards dérivées des familles rangées avec leur source."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Déplacer les cards (sans cette option : compter seulement).")

    def handle(self, *args, **options):
        apply = options['apply']
        families = moved = 0
        for model in django_apps.get_models():
            if not issubclass(model, DerivedCardMixin) or batch_model_for(model) is None:
                continue
            # Les lots candidats : ceux où vit au moins une card dérivée, lus une fois chacun.
            seen = {}
            for card in model.objects.exclude(derived_from=None).select_related('derived_from'):
                lot = batch_of(card)
                if lot is not None:
                    seen.setdefault(lot.pk, lot)
            for lot in seen.values():
                source, derived = family_in_one_lot(lot, model)
                if source is None:
                    continue
                families += 1
                self.stdout.write(f"  {model._meta.label} · lot #{lot.pk} : card #{source.pk} "
                                  f"et {len(derived)} card(s) dérivée(s)")
                if apply:
                    moved += split_family(lot, model)
        if apply:
            self.stdout.write(self.style.SUCCESS(
                f"{families} famille(s) : {moved} card(s) dérivée(s) passée(s) dans leur lot."))
        else:
            self.stdout.write(f"{families} famille(s) rangée(s) avec leur source — rien n'est changé "
                              f"(relancer avec --apply).")
