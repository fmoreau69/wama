# -*- coding: utf-8 -*-
"""
Renseigne `platform_ref` et `license` sur les modeles deja au catalogue.

Ne DEDUIT rien d'un nom de fichier : `platform_ref` se reecrit depuis des faits deja portes
(`hf_id`, ou une cle `ollama:`), et la licence se lit sur la plateforme. Un modele dont
l'origine n'est pas etablie est laisse VIDE et compte dans les indetermines -- le silence vaut
mieux qu'une correspondance inventee.

Idempotent : relancable sans effet de bord. `--dry-run` par defaut sur les ecritures de licence
distantes ; passer --ecrire pour appliquer.
"""
from django.core.management.base import BaseCommand

from wama.model_manager.models import AIModel


class Command(BaseCommand):
    help = "Renseigne platform_ref et license depuis les faits deja portes par le catalogue."

    def add_arguments(self, parser):
        parser.add_argument('--ecrire', action='store_true',
                            help="Applique les changements (sans ca, on n'affiche que le bilan).")
        parser.add_argument('--licences', action='store_true',
                            help="Interroge HuggingFace pour renseigner la licence (une requete par modele).")

    def handle(self, *args, **options):
        ecrire = options['ecrire']
        poses, deja, indetermines = 0, 0, []

        for m in AIModel.objects.all():
            if m.platform_ref:
                deja += 1
                continue
            ref = ''
            if m.hf_id:
                ref = f"huggingface:{m.hf_id}"
            elif 'ollama:' in (m.model_key or ''):
                famille = (m.name or '').split(':', 1)[0]
                ref = f"ollama:{famille}" if famille else ''
            if not ref:
                indetermines.append(m.model_key)
                continue
            poses += 1
            if ecrire:
                m.platform_ref = ref
                m.save(update_fields=['platform_ref'])

        self.stdout.write(f"platform_ref  : {poses} a poser, {deja} deja renseignes, "
                          f"{len(indetermines)} indetermines")

        if options['licences']:
            self._licences(ecrire)

        if indetermines:
            self.stdout.write(self.style.WARNING(
                f"\n{len(indetermines)} modeles sans origine etablie -- ils n'ont ni hf_id ni cle "
                f"ollama. Les rattacher demande de VERIFIER le depot d'origine, pas de le deduire "
                f"d'un nom de fichier. Exemples : "
                + ', '.join(indetermines[:5])))
        if not ecrire:
            self.stdout.write(self.style.NOTICE("\nRien ecrit (ajouter --ecrire)."))

    def _licences(self, ecrire):
        try:
            from huggingface_hub import HfApi
        except ImportError:
            self.stderr.write("huggingface_hub absent : licences ignorees.")
            return
        api = HfApi()
        vus, echecs = 0, 0
        for m in AIModel.objects.exclude(hf_id='').exclude(hf_id__isnull=True).filter(license=''):
            try:
                info = api.model_info(m.hf_id)
                carte = info.card_data
                lic = (carte.to_dict().get('license') if carte else None) or ''
            except Exception as e:
                echecs += 1
                self.stderr.write(f"  {m.hf_id} : {type(e).__name__}")
                continue
            if not lic:
                continue
            vus += 1
            self.stdout.write(f"  {m.model_key:46s} -> {lic}")
            if ecrire:
                m.license = str(lic)[:64]
                m.save(update_fields=['license'])
        self.stdout.write(f"licences      : {vus} trouvees, {echecs} en echec")
