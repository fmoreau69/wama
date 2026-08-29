# -*- coding: utf-8 -*-
"""
Renseigne `platform_ref` et `license` sur les modeles deja au catalogue.

Ne DEDUIT rien d'un nom de fichier : `platform_ref` se reecrit depuis des faits deja portes
(`hf_id`, ou une cle `ollama:`), et la licence se lit sur la plateforme. Un modele dont
l'origine n'est pas etablie est laisse VIDE et compte dans les indetermines -- le silence vaut
mieux qu'une correspondance inventee.

Idempotent : relancable sans effet de bord. `--dry-run` par defaut sur les ecritures de licence
distantes ; passer --ecrire pour appliquer.

TROIS SOURCES DE FAIT, par ordre de cout croissant -- aucune ne DEDUIT quoi que ce soit :
  1. `--depuis-poids` : la licence ecrite DANS le fichier de poids (hors ligne, aucune requete).
     Couvre les modeles decouverts par scan disque, qui n'ont pas d'identite de plateforme.
  2. `--licences`     : la carte HuggingFace, pour les modeles portant deja un `hf_id`.
  3. `--poser`        : une provenance VERIFIEE par un humain (appariement nom+taille d'octets
     contre le depot amont). C'est la porte d'entree qui manquait : le rattachement des 70
     modeles indetermines etait impossible, faute d'un endroit ou deposer le fait etabli.

Apres une ecriture, rafraichir le corpus declaratif :
    python manage.py manifest_export --kind model <model_key>
(le manifeste est EXTRAIT du catalogue -- tant que le catalogue est vide, le manifeste l'est
aussi et sa projection ne rend rien.)
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
        parser.add_argument('--depuis-poids', action='store_true',
                            help="Lit la licence DANS les fichiers de poids (.pt/.onnx). Hors ligne.")
        parser.add_argument('--poser', action='append', default=[], metavar='CLE=PLATFORM_REF',
                            help="Provenance VERIFIEE a enregistrer, repetable. "
                                 "Ex. --poser anonymizer:yolo:license-plate-finetune-v1m.onnx="
                                 "huggingface:morsetechlab/yolov11-license-plate-detection")
        parser.add_argument('--ultralytics', action='store_true',
                            help="Verifie les poids YOLO officiels contre les releases GitHub "
                                 "ultralytics/assets (nom + taille en octets) et pose "
                                 "github:ultralytics/assets sur les correspondances exactes.")

    def handle(self, *args, **options):
        ecrire = options['ecrire']

        # La provenance verifiee s'enregistre AVANT la derivation : une fois `hf_id` pose, la
        # boucle ci-dessous en derive `platform_ref` par le chemin normal, sans cas particulier.
        if options['poser']:
            self._poser(options['poser'], ecrire)

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

        # ORDRE VOULU : la plateforme AVANT les poids. Un checkpoint ultralytics porte
        # `license = AGPL-3.0` parce que c'est la licence du CADRE D'ENTRAINEMENT, pas forcement
        # celle sous laquelle l'auteur publie son modele. Cas reel : `yolo11l_face_plate_signs.pt`
        # declare AGPL dans ses poids alors que Panoramax le publie en Licence Ouverte Etalab 2.0.
        # La declaration de l'editeur fait foi ; les poids ne sont le RECOURS que pour les modeles
        # sans identite de plateforme (les 63 issus du scan disque).
        if options['licences']:
            self._licences(ecrire)

        if options['depuis_poids']:
            self._depuis_poids(ecrire)

        if options['ultralytics']:
            self._ultralytics(ecrire)

        if indetermines:
            self.stdout.write(self.style.WARNING(
                f"\n{len(indetermines)} modeles sans origine etablie -- ils n'ont ni hf_id ni cle "
                f"ollama. Les rattacher demande de VERIFIER le depot d'origine, pas de le deduire "
                f"d'un nom de fichier. Exemples : "
                + ', '.join(indetermines[:5])))
        if not ecrire:
            self.stdout.write(self.style.NOTICE("\nRien ecrit (ajouter --ecrire)."))

    def _poser(self, entrees, ecrire):
        """
        Enregistre des provenances VERIFIEES (`cle=plateforme:identifiant`).

        C'est le seul endroit du systeme ou une origine entre « a la main » -- et c'est assume :
        aucune API ne peut dire d'ou vient un fichier de poids anonyme pose sur un disque. La
        verification, elle, est mecanique et se refait : appariement nom de fichier + TAILLE EN
        OCTETS contre les fichiers du depot amont. La table n'est pas codee en dur dans le
        depot, elle transite par la ligne de commande : on n'inscrit pas dans le code une
        correspondance que personne ne pourra reverifier.
        """
        self.stdout.write("provenances verifiees :")
        for entree in entrees:
            cle, _, ref = (entree or '').partition('=')
            cle, ref = cle.strip(), ref.strip()
            if not cle or not ref:
                self.stderr.write(self.style.ERROR(f"  format attendu CLE=PLATFORM_REF : {entree!r}"))
                continue
            plateforme, _, identifiant = ref.partition(':')
            if not identifiant or plateforme not in AIModel._URL_PAR_PLATEFORME:
                self.stderr.write(self.style.ERROR(
                    f"  plateforme inconnue dans {ref!r} "
                    f"(connues : {', '.join(sorted(AIModel._URL_PAR_PLATEFORME))})"))
                continue
            m = AIModel.objects.filter(model_key=cle).first()
            if m is None:
                self.stderr.write(self.style.ERROR(f"  aucun modele de cle {cle!r} au catalogue"))
                continue

            champs = {'platform_ref': ref}
            # `hf_id` est le champ historique : le renseigner rend le modele visible a
            # `--licences` et au filtre « deja chez nous » de la prospection.
            if plateforme == 'huggingface':
                champs['hf_id'] = identifiant
            avant = {c: getattr(m, c) for c in champs}
            if avant == champs:
                self.stdout.write(f"  = {cle}  (deja pose)")
                continue
            self.stdout.write(f"  + {cle:52s} -> {ref}")
            if ecrire:
                for c, v in champs.items():
                    setattr(m, c, v)
                m.save(update_fields=list(champs))

    def _ultralytics(self, ecrire):
        """
        Provenance des poids YOLO OFFICIELS restes sans identite : le stock telecharge AVANT
        le cablage `identite_pour_spec(kind='yolo')` (question Fabien 2026-08-29 — la plupart
        des cards YOLO sans lien de page).

        Rien n'est deduit du nom : la verification de la doctrine (« appariement nom de fichier
        + TAILLE EN OCTETS contre le depot amont ») est ici AUTOMATISEE — l'API GitHub liste
        les assets des releases `ultralytics/assets` avec leur taille exacte. Correspondance
        exacte (nom ET octets) ⇒ `github:ultralytics/assets` (la MEME ref que la voie
        d'installation, dont le repli par `platform_ref` continue de fonctionner), posee par
        `poser_identite` (voie manifeste + corpus). Sinon : compte, dit, laisse vide.
        """
        import os

        import requests

        from wama.model_manager.services.provenance import poser_identite

        candidats = [m for m in AIModel.objects.filter(platform_ref='', hf_id='')
                     .exclude(local_path='')
                     if m.model_key.startswith('anonymizer:yolo:')]
        if not candidats:
            self.stdout.write("ultralytics   : aucun candidat (tous references, ou sans chemin)")
            return

        # Assets {nom: {tailles possibles}} sur TOUTES les releases (un meme nom revit de
        # release en release ; l'egalite d'octets designe la bonne, ou n'importe laquelle —
        # peu importe : le depot d'origine est le meme).
        tailles: dict = {}
        try:
            for page in range(1, 6):     # ~30 releases/page — large pour ce depot
                r = requests.get(
                    'https://api.github.com/repos/ultralytics/assets/releases',
                    params={'per_page': 30, 'page': page}, timeout=(5, 30))
                r.raise_for_status()
                releases = r.json()
                if not releases:
                    break
                for rel in releases:
                    for asset in rel.get('assets') or []:
                        tailles.setdefault(asset['name'], set()).add(asset['size'])
        except Exception as e:
            self.stderr.write(self.style.ERROR(
                f"ultralytics   : releases GitHub injoignables ({e}) — rien pose"))
            return

        verifies, ecarts, absents = [], [], 0
        for m in candidats:
            nom = os.path.basename(m.local_path)
            if not os.path.isfile(m.local_path):
                absents += 1
                continue
            attendues = tailles.get(nom)
            if not attendues:
                continue                      # pas un asset officiel (finetune maison/tiers)
            octets = os.path.getsize(m.local_path)
            if octets in attendues:
                verifies.append(m.model_key)
            else:
                ecarts.append((m.model_key, octets, sorted(attendues)))

        for cle in verifies:
            self.stdout.write(f"  ✓ {cle:52s} -> github:ultralytics/assets (nom+octets)")
            if ecrire:
                res = poser_identite(cle, {'platform_ref': 'github:ultralytics/assets'})
                if not res.get('applique'):
                    self.stderr.write(self.style.ERROR(f"    pose en echec : {res.get('erreur')}"))
        for cle, octets, attendues in ecarts:
            self.stdout.write(self.style.WARNING(
                f"  ≠ {cle} : {octets} octets locaux, attendus {attendues} — laisse vide "
                f"(poids modifie ou re-exporte ?)"))
        self.stdout.write(
            f"ultralytics   : {len(verifies)} verifie(s) nom+taille, {len(ecarts)} ecart(s), "
            f"{absents} chemin(s) introuvables de cet hote, "
            f"{len(candidats) - len(verifies) - len(ecarts) - absents} hors assets officiels")

    def _depuis_poids(self, ecrire):
        """
        Licence lue DANS les fichiers de poids -- hors ligne, aucune requete reseau.

        RECOURS uniquement : on ne lit les poids que pour les modeles sans `license` ET sans
        identite de plateforme. Des qu'une plateforme existe, c'est SA declaration qui fait foi
        (cf. le commentaire d'ordre dans `handle`) -- sans quoi l'AGPL du cadre d'entrainement
        ecraserait la licence sous laquelle l'auteur publie reellement.
        """
        from wama.model_manager.services.weights_metadata import lire_metadonnees

        import os

        vus, mues, sans, absents = 0, 0, [], 0
        for m in AIModel.objects.filter(license='', platform_ref='').exclude(local_path=''):
            # `local_path` est ecrit par la DECOUVERTE, donc dans la graphie de l'hote qui l'a
            # lancee : WSL2 en production ('/mnt/d/...'), Windows en poste de dev. Un chemin qui
            # ne resout pas ici n'est pas une erreur de donnee -- c'est la commande qui tourne du
            # mauvais cote. On le COMPTE et on le dit, plutot que de sauter en silence.
            if not os.path.isfile(m.local_path):
                absents += 1
                continue
            infos = lire_metadonnees(m.local_path)
            lic = infos.get('license')
            if not lic:
                sans.append((m.model_key, infos.get('toolkit_version')))
                continue
            vus += 1
            self.stdout.write(f"  {m.model_key:52s} -> {lic}")
            # Indices de provenance : pas des champs du catalogue, mais ce qui permet
            # d'ETABLIR une origine ensuite (base du finetune, jeu d'entrainement).
            for etiquette, cle in (('base', 'train_base'), ('jeu', 'train_data')):
                if infos.get(cle):
                    self.stdout.write(f"      {etiquette} : {str(infos[cle])[:100]}")
            if ecrire:
                m.license = lic[:64]
                m.save(update_fields=['license'])
                mues += 1
        self.stdout.write(f"depuis-poids  : {vus} licence(s) lue(s) dans les fichiers"
                          + (f", {mues} ecrite(s)" if ecrire else ""))
        if absents:
            self.stdout.write(self.style.WARNING(
                f"  {absents} chemin(s) `local_path` introuvables depuis cet hote -- la decouverte "
                f"les a ecrits ailleurs (WSL2 vs Windows). Relancer du meme cote que `sync_models`."))
        if sans:
            self.stdout.write(self.style.WARNING(
                f"  {len(sans)} poids sans champ `license` (export anterieur a ultralytics 8.3, "
                f"ou format non lu) -- laisses VIDES, pas devines. Ex. : "
                + ', '.join(k for k, _ in sans[:4])))

    def _licences(self, ecrire):
        try:
            from huggingface_hub import HfApi
        except ImportError:
            self.stderr.write("huggingface_hub absent : licences ignorees.")
            return
        from wama.model_manager.services.provenance import identite_huggingface

        vus, corriges, echecs = 0, 0, 0
        # Plus de `filter(license='')` : la carte de l'editeur fait AUTORITE, y compris pour
        # corriger une licence deja posee par le repli « poids » (qui rend l'AGPL du cadre
        # ultralytics). Rester sur les seuls champs vides rendait l'outil dependant de l'ORDRE
        # des passes — il converge desormais quel que soit l'ordre, et reste idempotent puisqu'on
        # n'ecrit que sur difference.
        for m in AIModel.objects.exclude(hf_id='').exclude(hf_id__isnull=True):
            # Lecture de la carte MUTUALISEE avec l'installation par URL (services/provenance) :
            # c'etait le troisieme endroit du depot a interroger HuggingFace pour les memes faits.
            ident = identite_huggingface(m.hf_id)
            if ident is None:
                echecs += 1
                self.stderr.write(f"  {m.hf_id} : depot injoignable")
                continue
            lic, auteur = ident.get('license') or '', ident.get('author') or ''
            # L'auteur de la carte est un SLUG d'organisation (« black-forest-labs »,
            # voire l'org MIROIR : « hunyuanvideo-community » pour Tencent Hunyuan) : il
            # COMPLÈTE un champ vide, il n'écrase JAMAIS une valeur posée — même règle que
            # le placeholder `other` pour la licence, apprise deux fois (2026-08-12 licence,
            # 2026-08-27 : cette boucle a écrasé 6 auteurs curés, restaurés depuis le corpus).
            if auteur and not m.author:
                m.author = auteur[:200]
                if ecrire:
                    m.save(update_fields=['author'])
            lic = str(lic)[:64]
            if not lic or lic == m.license:
                continue
            # `other` n'est pas un fait : c'est le placeholder HuggingFace pour « licence
            # maison ». Une qualification déjà posée (cpml-1.0, hunyuan-community…) est PLUS
            # précise que le placeholder — l'écraser referait le travail de lecture à l'envers.
            if lic == 'other' and m.license and m.license != 'other':
                continue
            if m.license:
                corriges += 1
                self.stdout.write(self.style.WARNING(
                    f"  {m.model_key:46s} {m.license} -> {lic}  (l'editeur prime sur les poids)"))
            else:
                vus += 1
                self.stdout.write(f"  {m.model_key:46s} -> {lic}")
            if ecrire:
                m.license = lic
                m.save(update_fields=['license'])
        self.stdout.write(f"licences      : {vus} posee(s), {corriges} corrigee(s), {echecs} en echec")
