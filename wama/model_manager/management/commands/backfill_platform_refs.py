# -*- coding: utf-8 -*-
"""
Renseigne `platform_ref` et `license` sur les modeles deja au catalogue.

Ne DEDUIT rien d'un nom de fichier : `platform_ref` se reecrit depuis des faits deja portes
(une cle `ollama:`), et la licence se lit sur la plateforme. Un modele dont
l'origine n'est pas etablie est laisse VIDE et compte dans les indetermines -- le silence vaut
mieux qu'une correspondance inventee.

Idempotent : relancable sans effet de bord. `--dry-run` par defaut sur les ecritures de licence
distantes ; passer --ecrire pour appliquer.

TROIS SOURCES DE FAIT, par ordre de cout croissant -- aucune ne DEDUIT quoi que ce soit :
  1. `--depuis-poids` : la licence ecrite DANS le fichier de poids (hors ligne, aucune requete).
     Couvre les modeles decouverts par scan disque, qui n'ont pas d'identite de plateforme.
  2. `--licenses`     : la carte HuggingFace, pour les modeles portant deja un `platform_ref`
                        du Hub.
  3. `--poser`        : une provenance VERIFIEE par un humain (appariement nom+taille d'octets
     contre le depot amont). C'est la porte d'entree qui manquait : le rattachement des 70
     modeles indetermines etait impossible, faute d'un endroit ou deposer le fait etabli.

L'identite de plateforme (`platform_ref`, provenances verifiees comprises) se pose PAR LE
MANIFESTE (`provenance.set_identity`, 2026-10-22) : projection au catalogue ET export au corpus
d'un modele installe, dans le meme geste ; la licence lue DANS les poids (`--depuis-poids`) aussi.
La passe `--licenses` (licence, auteur, regime d'acces, publications) suit la meme voie, sans
export (rattrapage de masse) ; apres elle, rafraichir le corpus declaratif :
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
        parser.add_argument('--licenses', action='store_true',
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

        # La provenance verifiee s'enregistre AVANT la derivation : une fois `platform_ref` pose,
        # la boucle ci-dessous la compte parmi les references deja renseignees.
        if options['poser']:
            self._set_verified(options['poser'], ecrire)

        poses, deja, indetermines = 0, 0, []

        for m in AIModel.objects.all():
            if m.platform_ref:
                deja += 1
                continue
            # LA règle de dérivation (`AIModel.platform_refs`, celle du lien de la card) — plus
            # recopiée ici (2026-10-22).
            ref = next(iter(m.platform_refs()), '')
            if not ref:
                indetermines.append(m.model_key)
                continue
            poses += 1
            if ecrire:
                self._set_identity(m, {'platform_ref': ref})

        self.stdout.write(f"platform_ref  : {poses} a poser, {deja} deja renseignes, "
                          f"{len(indetermines)} indetermines")

        # ORDRE VOULU : la plateforme AVANT les poids. Un checkpoint ultralytics porte
        # `license = AGPL-3.0` parce que c'est la licence du CADRE D'ENTRAINEMENT, pas forcement
        # celle sous laquelle l'auteur publie son modele. Cas reel : `yolo11l_face_plate_signs.pt`
        # declare AGPL dans ses poids alors que Panoramax le publie en Licence Ouverte Etalab 2.0.
        # La declaration de l'editeur fait foi ; les poids ne sont le RECOURS que pour les modeles
        # sans identite de plateforme (les 63 issus du scan disque).
        if options['licenses']:
            self._licenses(ecrire)

        if options['depuis_poids']:
            self._from_weights(ecrire)

        if options['ultralytics']:
            self._ultralytics(ecrire)

        if indetermines:
            self.stdout.write(self.style.WARNING(
                f"\n{len(indetermines)} modeles sans origine etablie -- ils n'ont ni platform_ref ni cle "
                f"ollama. Les rattacher demande de VERIFIER le depot d'origine, pas de le deduire "
                f"d'un nom de fichier. Exemples : "
                + ', '.join(indetermines[:5])))
        if not ecrire:
            self.stdout.write(self.style.NOTICE("\nRien ecrit (ajouter --ecrire)."))

    def _set_verified(self, entrees, ecrire):
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
            # Les plateformes déclarées au registre des sources (`model_platforms`).
            from wama.common.external_sources import model_platforms
            if not identifiant or plateforme not in model_platforms():
                self.stderr.write(self.style.ERROR(
                    f"  plateforme inconnue dans {ref!r} "
                    f"(connues : {', '.join(sorted(model_platforms()))})"))
                continue
            m = AIModel.objects.filter(model_key=cle).first()
            if m is None:
                self.stderr.write(self.style.ERROR(f"  aucun modele de cle {cle!r} au catalogue"))
                continue

            # `platform_ref` suffit (2026-10-27) : `--licenses` et le filtre « deja chez nous » de
            # la prospection en derivent le depot du Hub, `hf_id` ne s'ecrit plus.
            champs = {'platform_ref': ref}
            avant = {c: getattr(m, c) for c in champs}
            if avant == champs:
                self.stdout.write(f"  = {cle}  (deja pose)")
                continue
            self.stdout.write(f"  + {cle:52s} -> {ref}")
            if ecrire:
                self._set_identity(m, champs)

    def _set_identity(self, m, identity):
        """Pose une identité de plateforme PAR LE MANIFESTE (`provenance.set_identity`) — la voie
        de toute identité, que la branche `--ultralytics` suivait déjà (2026-10-22). Ces écritures
        allaient directement en base : le corpus des manifestes ne les recevait pas, et la
        prochaine extraction n'avait rien à porter. Un candidat (`is_proposed`) est projeté sans
        export : le corpus ne connaît que les modèles installés."""
        from wama.model_manager.services.provenance import set_identity
        res = set_identity(m.model_key, identity, export=not m.is_proposed)
        if not res.get('applied'):
            self.stderr.write(self.style.ERROR(f"    {m.model_key} : pose en echec — "
                                               f"{res.get('error')}"))

    def _ultralytics(self, ecrire):
        """
        Provenance des poids YOLO OFFICIELS restes sans identite : le stock telecharge AVANT
        le cablage `identity_for_spec(kind='yolo')` (question Fabien 2026-08-29 — la plupart
        des cards YOLO sans lien de page).

        Rien n'est deduit du nom : la verification de la doctrine (« appariement nom de fichier
        + TAILLE EN OCTETS contre le depot amont ») est ici AUTOMATISEE — l'API GitHub liste
        les assets des releases `ultralytics/assets` avec leur taille exacte. Correspondance
        exacte (nom ET octets) ⇒ `github:ultralytics/assets` (la MEME ref que la voie
        d'installation, dont le repli par `platform_ref` continue de fonctionner), posee par
        `set_identity` (voie manifeste + corpus). Sinon : compte, dit, laisse vide.
        """
        import os

        import requests

        from wama.model_manager.services.provenance import set_identity

        candidats = [m for m in AIModel.objects.filter(platform_ref='')
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
                res = set_identity(cle, {'platform_ref': 'github:ultralytics/assets'})
                if not res.get('applied'):
                    self.stderr.write(self.style.ERROR(f"    pose en echec : {res.get('error')}"))
        for cle, octets, attendues in ecarts:
            self.stdout.write(self.style.WARNING(
                f"  ≠ {cle} : {octets} octets locaux, attendus {attendues} — laisse vide "
                f"(poids modifie ou re-exporte ?)"))
        self.stdout.write(
            f"ultralytics   : {len(verifies)} verifie(s) nom+taille, {len(ecarts)} ecart(s), "
            f"{absents} chemin(s) introuvables de cet hote, "
            f"{len(candidats) - len(verifies) - len(ecarts) - absents} hors assets officiels")

    def _from_weights(self, ecrire):
        """
        Licence lue DANS les fichiers de poids -- hors ligne, aucune requete reseau.

        RECOURS uniquement : on ne lit les poids que pour les modeles sans `license` ET sans
        identite de plateforme. Des qu'une plateforme existe, c'est SA declaration qui fait foi
        (cf. le commentaire d'ordre dans `handle`) -- sans quoi l'AGPL du cadre d'entrainement
        ecraserait la licence sous laquelle l'auteur publie reellement.
        """
        from wama.model_manager.services.weights_metadata import read_metadata

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
            infos = read_metadata(m.local_path)
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
                self._set_identity(m, {'license': lic[:64]})
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

    def _licenses(self, ecrire):
        try:
            from huggingface_hub import HfApi
        except ImportError:
            self.stderr.write("huggingface_hub absent : licences ignorees.")
            return
        from wama.model_manager.services.provenance import huggingface_identity

        vus, corriges, echecs, acces_poses = 0, 0, 0, 0
        publications_set = 0
        # Plus de `filter(license='')` : la carte de l'editeur fait AUTORITE, y compris pour
        # corriger une licence deja posee par le repli « poids » (qui rend l'AGPL du cadre
        # ultralytics). Rester sur les seuls champs vides rendait l'outil dependant de l'ORDRE
        # des passes — il converge desormais quel que soit l'ordre, et reste idempotent puisqu'on
        # n'ecrit que sur difference.
        from wama.common.external_sources import HUGGINGFACE
        for m in AIModel.objects.filter(platform_ref__startswith=f'{HUGGINGFACE}:'):
            # Lecture de la carte MUTUALISEE avec l'installation par URL (services/provenance) :
            # c'etait le troisieme endroit du depot a interroger HuggingFace pour les memes faits.
            ident = huggingface_identity(m.hf_repo)
            if ident is None:
                echecs += 1
                self.stderr.write(f"  {m.hf_repo} : depot injoignable")
                continue
            # TOUT ce que la carte dit passe par le MANIFESTE (`set_identity`, 2026-10-22), comme
            # à l'installation : licence, auteur, régime d'accès, publications — une seule voie et
            # ses règles (l'auteur ne remplit qu'un vide ; `other` n'écrase pas une licence
            # qualifiée ; l'accès, état courant du dépôt amont, s'écrase). Le corpus n'est pas
            # réécrit ici (un rattrapage de masse) : il les reprendra à sa prochaine extraction.
            # Les comptes LISENT ce que la pose déclare poser (`posed`), à blanc comme pour de
            # vrai : aucune règle n'est redite ici.
            from wama.model_manager.services.provenance import set_identity
            lic = str(ident.get('license') or '')[:64]
            res = set_identity(m.model_key, {k: ident.get(k) for k in
                                             ('license', 'author', 'gated', 'publications')},
                               apply=ecrire, export=False)
            if res.get('error'):
                self.stderr.write(self.style.ERROR(f"    {m.model_key} : pose en echec — "
                                                   f"{res.get('error')}"))
                continue
            posed = res.get('posed') or []
            acces_poses += 'gated' in posed
            publications_set += 'publications' in posed
            if 'license' in posed:
                if m.license:
                    corriges += 1
                    self.stdout.write(self.style.WARNING(
                        f"  {m.model_key:46s} {m.license} -> {lic}  (l'editeur prime sur les poids)"))
                else:
                    vus += 1
                    self.stdout.write(f"  {m.model_key:46s} -> {lic}")
        self.stdout.write(f"licences      : {vus} posee(s), {corriges} corrigee(s), {echecs} en echec")
        self.stdout.write(f"acces (gated) : {acces_poses} regime(s) mis a jour"
                          + ("" if ecrire else " (simulation)"))
        self.stdout.write(f"publications  : {publications_set} modele(s) completes"
                          + ("" if ecrire else " (simulation)"))
