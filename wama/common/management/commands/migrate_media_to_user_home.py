"""Déplace les médias d'app vers le DOMICILE UNIQUE de l'utilisateur.

    python manage.py migrate_media_to_user_home            # PLAN seul, n'écrit rien
    python manage.py migrate_media_to_user_home --apply    # exécute

    <app>/<user>/input|output/…   →   users/<user>/<app>/input|output/…

POURQUOI (demande Fabien, 2026-09-11)
    *« Que tous les fichiers importés d'un utilisateur, quelle que soit la manière, aillent
    dans le dossier de l'utilisateur — pour simplifier et permettre par la suite un chiffrement
    par utilisateur, pour ne pas laisser les données lisibles par toute personne accédant à la
    machine. »* Un chiffrement par utilisateur suppose que ses octets vivent dans UN sous-arbre ;
    ils sont aujourd'hui dispersés dans 11 arbres d'app.

⚠ ON DÉPLACE, ON NE COPIE JAMAIS. Mesuré le 2026-09-11 : `media/` pèse 20 Go et il reste 21 Go
    sur le disque — copier saturerait. `media/` et `media/users/` sont sur le MÊME système de
    fichiers (même `st_dev`), donc `os.rename` est une opération de métadonnées : instantanée
    et gratuite. On n'utilise donc PAS `shutil.move`, qui retombe SILENCIEUSEMENT sur
    copier-puis-supprimer quand le rename échoue — ce silence-là remplirait le disque avant
    qu'on s'en aperçoive. Un rename qui échoue ARRÊTE la migration.

⚠ LA STRUCTURE `input`/`output` EST CONSERVÉE (arbitrage Fabien) : ce palier est un
    déplacement MÉCANIQUE, donc vérifiable. Le passage à `imports/` + `outputs/` est un second
    geste, plus facile une fois celui-ci fait. La médiathèque migre plus tard : ses URLs
    circulent.

CE QUI EST MESURÉ AVANT ET APRÈS, et pourquoi c'est le seul verdict qui compte : le nombre de
    champs fichier dont le fichier EXISTE réellement sur le disque. Un déplacement réussi le
    laisse identique. Toute baisse est un fichier perdu de vue par la base — exactement le
    défaut que `check_media_integrity` mesure a posteriori, et qu'on refuse de créer ici.
"""
import os
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models, transaction

#: Les sous-dossiers d'app qu'on déplace. Tout le reste (`users/`, `media_library/`, `mounts/`)
#: est soit déjà à sa place, soit hors périmètre de ce palier.
SOUS_DOSSIERS = ('input', 'output')


def champs_fichier():
    """Tous les (modèle, nom de champ) portant un fichier — inventaire DÉRIVÉ, jamais listé.

    Une liste écrite à la main omettrait le champ ajouté demain, et l'omission ne se verrait
    qu'au moment où un utilisateur ouvrirait une card vide.
    """
    for modele in django_apps.get_models():
        for champ in modele._meta.get_fields():
            if isinstance(champ, models.FileField):
                yield modele, champ.name


def cible(valeur: str):
    """`<app>/<uid>/<sub>/reste` → `users/<uid>/<app>/<sub>/reste`, ou `None` si hors périmètre."""
    parts = (valeur or '').replace('\\', '/').split('/')
    if len(parts) < 4:
        return None
    app, uid, sous = parts[0], parts[1], parts[2]
    if app in ('users', 'media_library', 'mounts') or sous not in SOUS_DOSSIERS:
        return None
    if not uid.isdigit():
        return None
    return '/'.join(['users', uid, app, sous, *parts[3:]])


class Command(BaseCommand):
    help = "Déplace <app>/<user>/input|output vers users/<user>/<app>/input|output"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Exécute réellement (sinon : PLAN seul, rien n'est écrit)")
        parser.add_argument('--app', default='', help="Restreindre à une app (label Django)")

    def handle(self, *args, **opts):
        racine = Path(settings.MEDIA_ROOT)
        appliquer = opts['apply']
        filtre = opts['app']

        plan, absents, hors = [], 0, 0
        for modele, champ in champs_fichier():
            if filtre and modele._meta.app_label != filtre:
                continue
            qs = modele.objects.exclude(**{champ: ''}).exclude(**{f'{champ}__isnull': True})
            for pk, valeur in qs.values_list('pk', champ).iterator():
                dest = cible(valeur)
                if dest is None:
                    hors += 1
                    continue
                src = racine / valeur
                if not src.is_file():
                    absents += 1          # déjà signalé par check_media_integrity : on ne le crée pas
                    continue
                plan.append((modele, champ, pk, valeur, dest, src.stat().st_size))

        octets = sum(p[5] for p in plan)
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            "DÉPLACEMENT VERS LE DOMICILE UNIQUE — " + ("EXÉCUTION" if appliquer else "PLAN (rien n'est écrit)")))
        self.stdout.write(f"  fichiers à déplacer : {len(plan)}   ({octets / 1e9:.2f} Go)")
        self.stdout.write(f"  déjà hors périmètre : {hors}   (users/, médiathèque, montages…)")
        self.stdout.write(f"  ⚠ valeurs SANS fichier sur le disque : {absents}"
                          "   (préexistant — `check_media_integrity` les connaît)")

        par_app = {}
        for m, c, _pk, _v, _d, taille in plan:
            cle = f"{m._meta.app_label}.{m.__name__}.{c}"
            e = par_app.setdefault(cle, [0, 0])
            e[0] += 1
            e[1] += taille
        for cle in sorted(par_app):
            n, t = par_app[cle]
            self.stdout.write(f"    {cle:52s} {n:5d}   {t / 1e9:6.2f} Go")

        if not appliquer:
            self.stdout.write("")
            self.stdout.write("  → relancer avec --apply pour exécuter")
            return

        # ── EXÉCUTION ────────────────────────────────────────────────────────────────
        deplaces, echecs = 0, []
        for modele, champ, pk, valeur, dest, _taille in plan:
            src, dst = racine / valeur, racine / dest
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                # ⚠ `os.rename` et NON `shutil.move` : le second copierait en silence si le
                # rename échouait, et le disque n'a pas la place (20 Go de médias, 21 libres).
                os.rename(src, dst)
            except OSError as exc:
                echecs.append((valeur, str(exc)))
                continue
            with transaction.atomic():
                modele.objects.filter(pk=pk).update(**{champ: dest})
            deplaces += 1

        self.stdout.write("")
        self.stdout.write(f"  déplacés : {deplaces} / {len(plan)}")
        if echecs:
            self.stdout.write(self.style.ERROR(f"  ÉCHECS : {len(echecs)} — migration INCOMPLÈTE"))
            for v, e in echecs[:10]:
                self.stdout.write(f"    {v} — {e}")
