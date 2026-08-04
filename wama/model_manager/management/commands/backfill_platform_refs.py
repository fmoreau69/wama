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
        parser.add_argument('--capacites', action='store_true',
                            help="Interroge Ollama (/api/show) pour renseigner les capacites multiples des LLM.")

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

        if options['capacites']:
            self._capacites(ecrire)

        if indetermines:
            self.stdout.write(self.style.WARNING(
                f"\n{len(indetermines)} modeles sans origine etablie -- ils n'ont ni hf_id ni cle "
                f"ollama. Les rattacher demande de VERIFIER le depot d'origine, pas de le deduire "
                f"d'un nom de fichier. Exemples : "
                + ', '.join(indetermines[:5])))
        if not ecrire:
            self.stdout.write(self.style.NOTICE("\nRien ecrit (ajouter --ecrire)."))

    def _capacites(self, ecrire):
        """
        Renseigne `capabilities['abilities']` depuis Ollama.

        Un LLM ne se resume pas a UNE tache : `qwen3.6:35b` sait completer, lire une image,
        appeler un outil et raisonner explicitement. `tools` et `thinking` n'existent dans
        aucune autre taxonomie, et ce sont elles qui decident si un modele peut servir
        l'assistant. Les ecraser en `text-generation` perd l'information utile.
        """
        import requests

        from wama.model_manager.models import ModelAbility

        # Brique d'adressage commune : elle resout l'hote (127.0.0.1 est inatteignable depuis
        # WSL2, il faut la passerelle) ET neutralise le proxy, qui sinon avale l'appel local.
        from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
        hote = ollama_base()
        connues = {c[0] for c in ModelAbility.choices}
        vus, hors, echecs = 0, set(), 0

        for m in AIModel.objects.filter(model_key__contains='ollama:', is_downloaded=True):
            nom = m.name
            try:
                rep = requests.post(f"{hote}/api/show", json={'model': nom},
                                    **ollama_kwargs(timeout=25))
                caps = rep.json().get('capabilities') or []
            except Exception:
                echecs += 1
                continue
            if not caps:
                continue
            hors |= {c for c in caps if c not in connues}
            vus += 1
            self.stdout.write(f"  {m.model_key:44s} -> {', '.join(caps)}")
            if ecrire:
                donnees = dict(m.capabilities or {})
                donnees['abilities'] = sorted(caps)
                m.capabilities = donnees
                m.save(update_fields=['capabilities'])

        self.stdout.write(f"capacites     : {vus} renseignees, {echecs} injoignables")
        if hors:
            self.stdout.write(self.style.WARNING(
                f"⚠ capacites vues chez Ollama et NON declarees dans ModelAbility : "
                f"{', '.join(sorted(hors))} — a ajouter a l'enum."))

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
