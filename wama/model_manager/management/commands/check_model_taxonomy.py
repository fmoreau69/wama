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

        # Ce controle signalait naguere 'text-to-music'/'text-to-audio' et 'denoise'/'audio-enhance'
        # comme des quasi-doublons a fusionner. C'ETAIT FAUX, deux fois : il comparait des chaines
        # au lieu de regarder les modeles. MusicGen compose, AudioGen fait de l'ambiance — le
        # composer s'appuie sur cette distinction et un generateur de films scenarises en aura
        # besoin ; IRCNN debruite des IMAGES quand deepfilternet debruite du SON. Une proximite de
        # libelle ne dit rien : la ressemblance se juge sur les modeles, jamais sur les mots.
        # Remplace par la seule verification qui soit factuelle : la projection est-elle declaree ?
        self._projection(declares_task)

        if souci:
            self.stderr.write("\nUne valeur non declaree = la decouverte a ecrit hors taxonomie.")
            raise SystemExit(1)

    def _projection(self, declares_task):
        """
        Chaque tache doit declarer sa correspondance sur les plateformes de reference -- meme
        quand c'est None. Un oubli passerait pour << pas d'equivalent >> alors que c'est
        << pas encore regarde >>, et la nuance decide si on cherche ailleurs ou pas.
        """
        from wama.model_manager.models import (
            REFERENCE_PLATFORMS, TASK_TO_MODEL_TYPE, TASK_TO_PLATFORM_TAGS, ModelTask,
        )

        # ── ANCRAGE DE CATEGORIE : toute tache doit dire a quelle famille elle appartient ──
        # Sans lui, une requete par capacite perd sa borne de categorie et ne repose plus que
        # sur le filtre de tache — permissif par choix, donc un modele sans capacites
        # declarees passe (c'est par la que LocateAnything avait fui dans une requete TTS).
        # Le trou etait REEL sur les 4 taches qui n'ont aucun equivalent de plateforme
        # (lip-sync, text-to-music, text-to-audio, obb) : la derivation passait par le tag
        # HuggingFace, qui ne peut pas repondre pour ce qu'il ne nomme pas. Ce garde-fou
        # existe pour qu'une tache AJOUTEE demain ne retombe pas dans le trou en silence.
        sans_categorie = sorted(t.value for t in ModelTask if t not in TASK_TO_MODEL_TYPE)
        if sans_categorie:
            self.stdout.write(self.style.ERROR(
                f"✗ taches sans categorie declaree (TASK_TO_MODEL_TYPE) : "
                f"{', '.join(sans_categorie)}"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(
            f"✓ ancrage : les {len(TASK_TO_MODEL_TYPE)} taches declarent leur categorie"))

        manquantes = sorted(t for t in declares_task
                            if t not in {k.value for k in TASK_TO_PLATFORM_TAGS})
        if manquantes:
            self.stdout.write(self.style.ERROR(
                f"✗ taches sans projection declaree : {', '.join(manquantes)}"))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(
            f"✓ projection : les {len(TASK_TO_PLATFORM_TAGS)} taches declarent leur "
            f"correspondance sur {', '.join(REFERENCE_PLATFORMS)}"))

        propres = [t.value for t, tags in TASK_TO_PLATFORM_TAGS.items() if not any(tags)]
        if propres:
            self.stdout.write(
                f"    propres a WAMA (aucun equivalent nulle part) : {', '.join(sorted(propres))}")

        # Plusieurs de nos taches se projettent sur le MEME tag : c'est voulu, notre vocabulaire
        # est plus fin. On l'affiche pour que ce soit un choix visible, pas un accident.
        from collections import defaultdict
        regroupe = defaultdict(list)
        for t, tags in TASK_TO_PLATFORM_TAGS.items():
            if tags[0]:
                regroupe[tags[0]].append(t.value)
        for tag, nos in sorted(regroupe.items()):
            if len(nos) > 1:
                self.stdout.write(
                    f"    plus fin que HuggingFace : {' + '.join(sorted(nos))} → '{tag}'")
