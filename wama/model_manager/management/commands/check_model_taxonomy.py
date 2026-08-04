# -*- coding: utf-8 -*-
"""
Confronte la taxonomie DECLAREE (ModelType, ModelSource, ModelTask) a ce que le catalogue porte
REELLEMENT.

Raison d'etre : la taxonomie a derive quatre fois sans que rien ne le signale — 'music'/'ocr',
puis 'composer'/'reader', puis 'embedding' (en base, declare nulle part), et le vocabulaire des
taches qui s'ecrivait librement. La cause etait un enum DUPLIQUE entre models.py et
services/model_registry.py ; le doublon est supprime (2026-08-05), ce controle est le garde-fou
qui empeche la prochaine.

Ne modifie RIEN. Sort en code 1 si une valeur non declaree est trouvee, pour servir en CI.
"""
from collections import Counter

from django.core.management.base import BaseCommand

from wama.model_manager.models import AIModel, ModelType, ModelSource, ModelTask


class Command(BaseCommand):
    help = "Verifie que types, sources et taches du catalogue sont tous declares."

    def handle(self, *args, **options):
        declares_type = {c[0] for c in ModelType.choices}
        declares_source = {c[0] for c in ModelSource.choices}
        declares_task = {c[0] for c in ModelTask.choices}

        types, sources, taches = Counter(), Counter(), Counter()
        sans_tache = []
        for m in AIModel.objects.all():
            types[m.model_type] += 1
            sources[m.source] += 1
            tache = (m.capabilities or {}).get('task')
            if tache:
                taches[tache] += 1
            else:
                sans_tache.append(m.model_key)

        souci = False
        for libelle, vus, declares in (
            ('model_type', types, declares_type),
            ('source', sources, declares_source),
            ("capabilities['task']", taches, declares_task),
        ):
            inconnus = {v: n for v, n in vus.items() if v and v not in declares}
            inutilises = sorted(declares - set(vus))
            if inconnus:
                souci = True
                self.stdout.write(self.style.ERROR(
                    f"✗ {libelle} : valeurs NON DECLAREES portees par des modeles — "
                    + ', '.join(f"{v} ({n})" for v, n in sorted(inconnus.items()))))
            else:
                self.stdout.write(self.style.SUCCESS(f"✓ {libelle} : toutes les valeurs sont declarees"))
            if inutilises:
                self.stdout.write(f"    declares sans aucun modele : {', '.join(inutilises)}")

        if sans_tache:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ {len(sans_tache)} modeles sans capabilities['task'] — ils sortent de toute "
                f"selection ou evaluation par tache. Ex. : {', '.join(sans_tache[:5])}"))

        # Quasi-doublons : deux libelles pour la meme chose se reperent a la main, mais autant
        # les signaler que d'attendre qu'ils divergent.
        for a, b in (('text-to-audio', 'text-to-music'), ('denoise', 'audio-enhance')):
            if taches.get(a) and taches.get(b):
                self.stdout.write(self.style.WARNING(
                    f"⚠ '{a}' ({taches[a]}) et '{b}' ({taches[b]}) coexistent — a fusionner ou a "
                    f"distinguer explicitement."))

        if souci:
            self.stderr.write("\nUne valeur non declaree = la decouverte a ecrit hors taxonomie.")
            raise SystemExit(1)
