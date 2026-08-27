"""Audit MESURÉ de `media/` — les fichiers sont-ils à leur place, et rien n'a-t-il survécu ?

    python manage.py check_media_integrity

POURQUOI CE N'EST PAS UN MANIFESTE (décision 2026-08-25)
    Un manifeste décrit ce qui se RECONSTRUIT depuis une déclaration, et `manifests/` est
    versionné — or `media/` porte des données personnelles de labo SHS. Un `manifest_export
    --check` serait de plus périmé au moindre dépôt de fichier, et un contrôle toujours rouge
    ne protège plus rien. Ce qu'il fallait est un audit, dans la famille de `check_docs` /
    `license_audit` / `check_app_conformity`.

⚠⚠ MÉTHODE : DEUX SIGNAUX INDÉPENDANTS, JAMAIS LE NOM SEUL.
    Mesuré le 2026-08-25, et les deux erreurs sont symétriques :
      - « orphelin » seul désignait 3447 fichiers sur 3779, dont l'immense majorité sont de
        vraies sorties de workers (elles ne passent pas par un `FileField`) ;
      - le nom seul aurait emporté `synthesizer/5/input/test_synthesizer.txt`, dépôt manuel
        d'une utilisatrice réelle.
    Un fichier n'est donc « résidu de test » que si son nom vient d'un producteur de test
    IDENTIFIÉ DANS LE CODE **et** qu'aucune ligne de base ne le référence.

⚠ Le suffixe de dé-collision de Django existe sous DEUX formes dans ce dépôt — 7 alphanum
  (`reference_6P3kGCJ.wav`) et 8 hex (`test_0_c5e24b5d.txt`) — et il peut s'EMPILER.
  N'en reconnaître qu'une laissait 476 fichiers hors du compte (mesuré).
"""
import os
import re
from collections import defaultdict
from pathlib import Path

from django.apps import apps as dj_apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models as dj_models

#: Suffixe de dé-collision de Django, empilable. Cf. avertissement de l'en-tête.
_DJ = r'(_[A-Za-z0-9]{7,8})*'

#: Producteurs de fichiers de test — chaque motif CITE SA SOURCE. Ne rien ajouter ici sans
#: avoir trouvé la ligne de code qui écrit le fichier : c'est ce lien qui fait la preuve.
PRODUCTEURS_DE_TEST = (
    ("synthesizer/tests.py — SimpleUploadedFile('test.txt')",
     re.compile(rf'^(?:.*/)?test{_DJ}\.txt$')),
    ("synthesizer/tests.py — SimpleUploadedFile('reference.wav')",
     re.compile(rf'^(?:.*/)?reference{_DJ}\.wav$')),
    ("synthesizer/tests.py:383/403 — f'test_{{i}}.txt' (tests de lot)",
     re.compile(rf'^(?:.*/)?test_\d+{_DJ}\.(txt|wav|mp3|pdf|docx|json)$')),
    ("common/tests_codegen_lot.py — 'lot.txt' + MEDIA_ROOT/tests_lot",
     re.compile(rf'^(?:tests_lot/.*|(?:.*/)?lot{_DJ}\.txt)$')),
    ("common/services/ui_smoke.py — _fichier_temoin (NamedTemporaryFile)",
     re.compile(rf'^(?:.*/)?tmp[A-Za-z0-9_]{{6,}}{_DJ}\.[A-Za-z0-9]+$')),
    ("studio/nightly_scenarios.py — fixture _ENTREE_REL",
     re.compile(r'^nightly_tests/.*$')),
)

#: Emplacements LÉGITIMES. La règle de base est `<app>/<user>/input|output/` + `users/`
#: (`MEDIA_STORAGE_TIERING.md`), mais elle ne suffit pas : plusieurs apps rangent
#: légitimement AUTREMENT, et un premier jet de ce contrôle les a signalées à tort.
#: ⚠ Chaque exception CITE SA RAISON — sans quoi la liste devient un fourre-tout où l'on
#: ajoute un motif à chaque fois qu'un compteur dérange, et le contrôle ne mesure plus rien.
EMPLACEMENTS_LEGITIMES = (
    ("fichiers de profil utilisateur",
     re.compile(r'^users/.*$')),
    ("entrées/sorties d'app — la règle de base",
     re.compile(r'^[A-Za-z0-9_]+/\d+/(input|output)/.*$')),
    ("galerie d'avatars PARTAGÉE (lue par avatarizer.views._gallery_images)",
     re.compile(r'^avatarizer/gallery/.*$')),
    ("voix du synthesizer — personnalisées, par défaut, et références par langue/âge/genre "
     "(ce sont des RESSOURCES d'entrée, pas des sorties)",
     re.compile(r'^synthesizer/(\d+/custom_voices|default_voices|voice_references)/.*$')),
    ("médiathèque — rangement par TYPE, pas par input/output (app à structure propre)",
     re.compile(r'^media_library/\d+/[A-Za-z0-9_]+/.*$')),
)


def _est_legitime(rel: str) -> bool:
    return any(motif.match(rel) for _, motif in EMPLACEMENTS_LEGITIMES)


def _references_vives():
    """{chemin relatif -> 'app.Modele.champ #pk'} pour tous les FileField du dépôt."""
    refs = {}
    for modele in dj_apps.get_models():
        champs = [f for f in modele._meta.get_fields() if isinstance(f, dj_models.FileField)]
        if not champs:
            continue
        try:
            for ligne in modele.objects.all().only('pk', *[f.name for f in champs]).iterator():
                for f in champs:
                    nom = getattr(getattr(ligne, f.name, None), 'name', None)
                    if nom:
                        refs[nom.replace('\\', '/')] = f"{modele._meta.label}.{f.name} #{ligne.pk}"
        except Exception:
            continue
    return refs


class Command(BaseCommand):
    help = "Audit de media/ : référencé / orphelin / résidu de test / RÉFÉRENCÉ MAIS ABSENT / égaré."

    def add_arguments(self, parser):
        parser.add_argument('--details', action='store_true',
                            help="Liste les fichiers de chaque catégorie (pas seulement les compteurs)")
        parser.add_argument('--strict', action='store_true',
                            help="Sortie en code 1 si un résidu de test ou une référence absente subsiste")
        parser.add_argument('--reparer', action='store_true',
                            help="VIDE les pointeurs de fichier ABSENT sur les lignes qui portent "
                                 "encore du contenu. Ne supprime AUCUNE ligne, ne touche à aucun "
                                 "fichier — il s'agit d'arrêter de proposer un téléchargement qui "
                                 "échouera. Simulation sans le drapeau.")

    def handle(self, *args, **opts):
        racine = Path(settings.MEDIA_ROOT)
        if not racine.exists():
            self.stdout.write(self.style.WARNING(f"MEDIA_ROOT absent : {racine}"))
            return

        refs = _references_vives()
        sur_disque = [str(p.relative_to(racine)).replace('\\', '/')
                      for p in racine.rglob('*') if p.is_file()]

        references, orphelins = [], []
        residus = defaultdict(list)
        egares = []
        for rel in sur_disque:
            if rel in refs:
                references.append(rel)
            else:
                orphelins.append(rel)
                for source, motif in PRODUCTEURS_DE_TEST:
                    if motif.match(rel):
                        residus[source].append(rel)
                        break
            if not _est_legitime(rel):
                egares.append(rel)

        absents = sorted(set(refs) - set(sur_disque))

        largeur = 78
        self.stdout.write("=" * largeur)
        self.stdout.write(f"INTÉGRITÉ DES MÉDIAS — {racine}")
        self.stdout.write("=" * largeur)
        self.stdout.write(f"  fichiers sur le disque              : {len(sur_disque)}")
        self.stdout.write(f"  ✅ RÉFÉRENCÉS (données utilisateur) : {len(references)}")
        self.stdout.write(f"  ·  orphelins (dont résidus/égarés)  : {len(orphelins)}")

        nb_residus = sum(len(v) for v in residus.values())
        style = self.style.ERROR if nb_residus else self.style.SUCCESS
        self.stdout.write(style(f"  🧪 RÉSIDUS DE TEST                  : {nb_residus}"))
        for source, fichiers in sorted(residus.items()):
            self.stdout.write(f"        {len(fichiers):5}  {source}")
            if opts['details']:
                for f in sorted(fichiers)[:20]:
                    self.stdout.write(f"               {f}")

        style = self.style.ERROR if absents else self.style.SUCCESS
        self.stdout.write(style(f"  🔴 RÉFÉRENCÉS MAIS ABSENTS du disque: {len(absents)}"))
        if absents:
            self.stdout.write("        (une ligne de base pointe vers un fichier qui n'existe pas — "
                              "un téléchargement ou un aperçu échouera sans rien dire)")
            for rel in (absents if opts['details'] else absents[:8]):
                self.stdout.write(f"        {rel}   ← {refs[rel]}")
            if not opts['details'] and len(absents) > 8:
                self.stdout.write(f"        … et {len(absents) - 8} autre(s) — relancer avec --details")

        style = self.style.WARNING if egares else self.style.SUCCESS
        self.stdout.write(style(f"  📂 ÉGARÉS (hors input/ output/ users/) : {len(egares)}"))
        if egares:
            self.stdout.write("        (`media/` ne contient que <app>/<user>/input|output/ et users/ "
                              "— cf. MEDIA_STORAGE_TIERING.md)")
            par_racine = defaultdict(int)
            for rel in egares:
                par_racine[rel.split('/')[0]] += 1
            for r, n in sorted(par_racine.items(), key=lambda kv: -kv[1])[:10]:
                self.stdout.write(f"        {n:5}  {r}/")
            if opts['details']:
                for rel in sorted(egares)[:40]:
                    self.stdout.write(f"               {rel}")

        if absents:
            self._reparer(racine, opts.get('reparer', False))

        self.stdout.write("=" * largeur)
        if opts['strict'] and (nb_residus or absents):
            raise SystemExit(1)

    #: Champs porteurs d'un RÉSULTAT exploitable même si le fichier d'entrée a disparu.
    CHAMPS_RESULTAT = ('result_text', 'description_text', 'text', 'transcript',
                       'output_text', 'content', 'result', 'summary', 'extracted_text')

    def _reparer(self, racine, executer):
        """Vide les pointeurs morts sur les lignes qui ont encore quelque chose à montrer.

        ⚠ La question n'est PAS « le fichier manque-t-il » (c'est acquis) mais « la ligne
        porte-t-elle encore de la valeur ». Mesuré le 2026-08-25 : sur 35 références cassées,
        **3 lignes portaient encore leur travail** — deux descriptions dont le texte a survécu
        à son image, et une synthèse dont le TEXTE SOURCE existe toujours. Les supprimer en
        bloc, comme un « nettoyage d'orphelins » naïf l'aurait fait, aurait détruit ce travail.
        On se contente donc de couper le pointeur mort : la card reste, son contenu reste, et
        l'UI cesse d'offrir un téléchargement qui échoue en silence.
        """
        soignables, pointeurs_seuls = [], 0
        for modele in dj_apps.get_models():
            champs = [f for f in modele._meta.get_fields() if isinstance(f, dj_models.FileField)]
            if not champs:
                continue
            try:
                lignes = list(modele.objects.all())
            except Exception:
                continue
            for ligne in lignes:
                for f in champs:
                    nom = getattr(getattr(ligne, f.name, None), 'name', None)
                    if not nom or (racine / nom).exists():
                        continue
                    porte = any(getattr(ligne, c, None) for c in self.CHAMPS_RESULTAT) or any(
                        (racine / n2).exists()
                        for g in champs if g.name != f.name
                        for n2 in [getattr(getattr(ligne, g.name, None), 'name', None)] if n2)
                    if porte:
                        soignables.append((modele, ligne, f.name))
                    else:
                        pointeurs_seuls += 1

        self.stdout.write(f"  🩹 réparables SANS RIEN PERDRE      : {len(soignables)}"
                          f"   (pointeurs seuls, non touchés : {pointeurs_seuls})")
        for modele, ligne, champ in soignables:
            self.stdout.write(f"        {modele._meta.label} #{ligne.pk}.{champ}")
        if not soignables:
            return
        if not executer:
            self.stdout.write("        (simulation — relancer avec --reparer)")
            return
        for modele, ligne, champ in soignables:
            setattr(ligne, champ, '')
            ligne.save(update_fields=[champ])
        self.stdout.write(self.style.SUCCESS(
            f"        {len(soignables)} pointeur(s) mort(s) coupé(s) — aucune ligne supprimée"))
