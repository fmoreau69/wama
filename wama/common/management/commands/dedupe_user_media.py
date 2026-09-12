"""Résorbe les doublons MÉCANIQUES d'un domicile utilisateur : `xxx_1.ext` → `xxx.ext`.

    python manage.py dedupe_user_media            # PLAN seul, n'écrit rien
    python manage.py dedupe_user_media --apply    # repointe les lignes, puis supprime la copie

POURQUOI (demande Fabien, 2026-09-12)
    *« Supprimer les dossiers fantômes et retirer tous les doublons en réaffectant les liens des
    cards aux fichiers uniques d'origine. Parfois le nom d'un dupliqué "xxx" devient
    "xxx_01/02/03". »* Ces suffixes ne sont pas décoratifs : ils sont POSÉS par les
    dédoublonneurs (`get_unique_filename`, et le stockage Django lui-même) quand un nom est déjà
    pris. Le même octet finit donc plusieurs fois sur le disque sous des noms différents, et
    l'utilisateur voit « SEQ08-01 » et « SEQ08-01_1 » sans savoir lequel est lequel.

CE QUI REND CE CAS MÉCANIQUE, et lui seul
    L'ORIGINAL est identifiable SANS ARBITRAGE : c'est la copie dont le nom n'a pas de suffixe,
    et les deux fichiers sont dans le MÊME dossier — donc du même utilisateur et de la même app.
    Repointer ne change aucun droit, ne traverse aucune frontière. Trois conditions, toutes
    vérifiées avant d'agir :
      1. contenu IDENTIQUE (sha256, pas la taille seule) ;
      2. même dossier ;
      3. exactement UNE copie sans suffixe — s'il y en a zéro ou plusieurs, on ne tranche pas.

⚠ CE QUI EST EXCLU, ET POURQUOI — les autres familles de doublons ne sont PAS mécaniques :
  * **cam_analyzer** — consigne de Fabien : il lit ses entrées PAR DOSSIER (RTMaps). *« Aucune
    référence en base » n'y signifie donc PAS « orphelin »*, et le critère qui vaut partout
    ailleurs y conduirait à supprimer des données vivantes ;
  * **inter-APPS** (le même média dans `anonymizer/input` et `converter/input`) : résorber
    reviendrait à faire pointer une app dans le dossier d'une autre. La cible visée est
    différente et meilleure — *sortir les médias des apps et ne faire que les POINTER depuis les
    apps* (Fabien, 2026-09-12) — donc ce cas se règlera par l'architecture, pas par un ménage ;
  * **inter-UTILISATEURS** : 🔴 à ne JAMAIS dédupliquer. Un fichier partagé par deux
    utilisateurs rend le chiffrement par utilisateur impossible — l'objectif même du domicile
    unique — et donnerait à l'un un accès aux octets de l'autre.

⚠ ORDRE DES DEUX ÉCRITURES : on repointe la BASE d'abord, on supprime le fichier ensuite. Si la
    suppression échoue, les lignes désignent l'original, qui existe : rien n'est cassé, il reste
    seulement une copie orpheline sur le disque. L'ordre inverse laisserait des lignes pointant
    sur un fichier qu'on vient d'effacer.
"""
import hashlib
import os
import re
from collections import defaultdict
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models, transaction

#: Apps dont les fichiers ne se jugent PAS sur les références de base (cf. en-tête).
EXCLUS = ('cam_analyzer',)

#: Suffixe posé par un dédoublonneur : `_1`, `_01`, `_2`… ou l'aléatoire hexadécimal de Django.
SUFFIXE = re.compile(r'^(?P<souche>.+?)_(?:\d{1,3}|[0-9a-f]{8})$')


def sha256_of(chemin: Path, bloc: int = 1 << 20) -> str:
    """Empreinte du CONTENU. La taille seule ne suffit pas : deux fichiers différents de même
    taille existent, et on s'apprête à en supprimer un."""
    h = hashlib.sha256()
    with open(chemin, 'rb') as f:
        while (morceau := f.read(bloc)):
            h.update(morceau)
    return h.hexdigest()


def reverse_index():
    """Chemin média → [(modèle, champ, pk)] — QUI désigne quoi.

    ⚠ Les `CharField`/`TextField` en font partie : `anonymizer.Media.output_file` est un
    CharField, et l'oublier est exactement ce qui a cassé son aperçu de sortie le 2026-09-12.
    *Un chemin de fichier ne vit pas seulement dans un `FileField`.*
    """
    index = defaultdict(list)
    for modele in django_apps.get_models():
        champs = [c for c in modele._meta.get_fields()
                  if isinstance(c, (models.FileField, models.CharField, models.TextField))]
        if not champs:
            continue
        noms = [c.name for c in champs]
        try:
            lignes = list(modele.objects.values('pk', *noms).iterator())
        except Exception:
            continue
        for ligne in lignes:
            for n in noms:
                v = ligne.get(n)
                if isinstance(v, str) and v and '/' in v and len(v) < 500:
                    index[v.replace('\\', '/')].append((modele, n, ligne['pk']))
    return index


class Command(BaseCommand):
    help = "Résorbe les doublons `xxx_1.ext` d'un même dossier vers `xxx.ext`"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Exécute réellement (sinon : PLAN seul, rien n'est écrit)")

    def _plan(self, racine: Path):
        """Couples (copie, original) sûrs — les trois conditions de l'en-tête."""
        index = reverse_index()

        par_taille = defaultdict(list)
        for f in (racine / 'users').rglob('*'):
            if f.is_file() and not any(x in f.parts for x in EXCLUS):
                par_taille[f.stat().st_size].append(f)

        groupes = defaultdict(list)
        for taille, fichiers in par_taille.items():
            if len(fichiers) < 2 or taille == 0:
                continue          # une taille unique ne peut pas être un doublon
            for f in fichiers:
                groupes[(taille, sha256_of(f))].append(f)

        plan = []
        for (taille, _h), memes in groupes.items():
            par_dossier = defaultdict(list)
            for f in memes:
                par_dossier[f.parent].append(f)
            for _dossier, fichiers in par_dossier.items():
                if len(fichiers) < 2:
                    continue
                sans_suffixe = [f for f in fichiers if not SUFFIXE.match(f.stem)]
                if len(sans_suffixe) != 1:
                    continue      # zéro ou plusieurs originaux → on ne tranche pas
                original = sans_suffixe[0]
                for copie in fichiers:
                    if copie is original:
                        continue
                    m = SUFFIXE.match(copie.stem)
                    if not m or m.group('souche') != original.stem:
                        continue  # suffixé, mais pas une copie de CETTE souche
                    rel_copie = copie.relative_to(racine).as_posix()
                    plan.append((rel_copie, original.relative_to(racine).as_posix(),
                                 taille, index.get(rel_copie, [])))
        return sorted(plan, key=lambda x: -x[2])

    def handle(self, *args, **opts):
        racine = Path(settings.MEDIA_ROOT)
        appliquer = opts['apply']
        plan = self._plan(racine)
        octets = sum(p[2] for p in plan)
        lignes = sum(len(p[3]) for p in plan)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "DOUBLONS MÉCANIQUES — " + ("EXÉCUTION" if appliquer else "PLAN (rien n'est écrit)")))
        self.stdout.write(f"  copies à résorber   : {len(plan)}   ({octets / 1e9:.2f} Go)")
        self.stdout.write(f"  lignes à repointer  : {lignes}")
        self.stdout.write(f"  apps exclues        : {', '.join(EXCLUS)}"
                          "   (lit ses entrées par DOSSIER — cf. en-tête)")
        self.stdout.write("")

        for rel, orig, taille, refs in plan:
            self.stdout.write(f"  {taille / 1e6:8.1f} Mo  {rel}")
            self.stdout.write(f"             → {orig}")
            for modele, champ, pk in refs:
                self.stdout.write(
                    f"             repointer {modele._meta.app_label}."
                    f"{modele.__name__}#{pk}.{champ}")
            if not refs:
                self.stdout.write("             (aucune référence — simple suppression)")

        if not appliquer:
            self.stdout.write("")
            self.stdout.write("  → relancer avec --apply pour exécuter")
            return

        resorbees, repointees, echecs = 0, 0, []
        for rel, orig, _taille, refs in plan:
            src = racine / rel
            if not (racine / orig).is_file():
                # Garde de dernière seconde : on ne supprime JAMAIS une copie si l'original
                # a disparu entre le plan et l'exécution.
                echecs.append((rel, "l'original a disparu depuis le plan"))
                continue
            try:
                with transaction.atomic():
                    for modele, champ, pk in refs:
                        modele.objects.filter(pk=pk).update(**{champ: orig})
                os.remove(src)
            except Exception as exc:
                echecs.append((rel, f"{type(exc).__name__}: {exc}"))
                continue
            resorbees += 1
            repointees += len(refs)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"  résorbées : {resorbees} / {len(plan)} copies   "
            f"({repointees} ligne(s) repointée(s), {octets / 1e9:.2f} Go libérés)"))
        if echecs:
            self.stdout.write(self.style.ERROR(f"  ÉCHECS : {len(echecs)}"))
            for rel, e in echecs[:10]:
                self.stdout.write(f"    {rel} — {e}")
