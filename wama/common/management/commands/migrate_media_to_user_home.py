"""Déplace les médias d'app vers le DOMICILE UNIQUE de l'utilisateur.

    python manage.py migrate_media_to_user_home            # PLAN seul, n'écrit rien
    python manage.py migrate_media_to_user_home --check    # PRÉ-VOL seul : la base tiendra-t-elle ?
    python manage.py migrate_media_to_user_home --apply    # exécute (pré-vol OBLIGATOIRE d'abord)

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
    qu'on s'en aperçoive. Un rename qui échoue ARRÊTE le fichier concerné.

⚠ LA STRUCTURE `input`/`output` EST CONSERVÉE (arbitrage Fabien) : ce palier est un
    déplacement MÉCANIQUE, donc vérifiable. Le passage à `imports/` + `outputs/` est un second
    geste, plus facile une fois celui-ci fait. La médiathèque migre plus tard : ses URLs
    circulent.

────────────────────────────────────────────────────────────────────────────────────────────
CE QUE CETTE VERSION CORRIGE — la première tentative du 2026-09-11 a ÉCHOUÉ EN VOL et il a
fallu réparer la base (413 lignes / 30 fichiers restaurés). Les quatre corrections sont ici, et
chacune répond à une cause MESURÉE, pas à une précaution de principe :

 1. **PRÉ-VOL `--check`, et il est OBLIGATOIRE avant `--apply`.** La cause n°1 était
    `max_length=100` (défaut Django d'un `FileField`) : le nouveau chemin est plus long, et la
    base a refusé `value too long for character varying(100)` **à mi-parcours** — donc avec des
    lignes déjà migrées et d'autres non. Un refus au milieu d'une migration de fichiers est le
    pire des deux mondes. Le pré-vol calcule la longueur du chemin CIBLE le plus long de chaque
    champ et la compare à son `max_length` : on sait AVANT de toucher un octet.

 2. **On raisonne par FICHIER, jamais par LIGNE.** La cause n°2 : `duplicate_instance` fait
    pointer plusieurs lignes sur le MÊME fichier — c'est son contrat, pas un accident. Déplacer
    « la ligne 12 » déplaçait le fichier sous les pieds des lignes 87 et 143 qui le désignaient
    aussi. Le plan est donc indexé par CHEMIN SOURCE, et un déplacement met à jour **toutes**
    les lignes qui le citent, tous modèles confondus.

 3. **La base est écrite AVANT le rename, dans la MÊME transaction.** Si le rename échoue,
    l'exception traverse l'`atomic()` et la base revient d'elle-même : aucune ligne ne pointe
    sur un fichier qui n'a pas bougé. L'ordre inverse (déplacer puis écrire) laisse, en cas
    d'échec de l'écriture, un fichier introuvable pour la base — c'est-à-dire exactement le
    défaut que `check_media_integrity` mesure et qu'on refuse de créer.

 4. **Un échec n'annule plus rien rétroactivement.** La réparation du 11/09 a cassé des lignes
    DÉJÀ migrées avec succès, parce qu'elle rejouait un retour arrière ligne par ligne sur des
    fichiers partagés. Ici chaque fichier est une unité atomique indépendante : un échec isolé
    laisse les autres fichiers dans un état cohérent, et la commande est RÉENTRANTE (relancer
    reprend ce qui reste, puisque ce qui est déjà sous `users/` est hors périmètre).

CE QUI EST MESURÉ AVANT ET APRÈS, et pourquoi c'est le seul verdict qui compte : le nombre de
    champs fichier dont le fichier EXISTE réellement sur le disque. Un déplacement réussi le
    laisse identique. Toute baisse est un fichier perdu de vue par la base.
"""
import os
from collections import defaultdict
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models, transaction

#: Les sous-dossiers d'app qu'on déplace. Tout le reste (`users/`, `media_library/`, `mounts/`)
#: est soit déjà à sa place, soit hors périmètre de ce palier.
SOUS_DOSSIERS = ('input', 'output')


def champs_fichier():
    """Tous les (modèle, champ) portant un fichier — inventaire DÉRIVÉ, jamais listé.

    Une liste écrite à la main omettrait le champ ajouté demain, et l'omission ne se verrait
    qu'au moment où un utilisateur ouvrirait une card vide. On rend le CHAMP et non son nom :
    le pré-vol a besoin de son `max_length`.
    """
    for modele in django_apps.get_models():
        for champ in modele._meta.get_fields():
            if isinstance(champ, models.FileField):
                yield modele, champ


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
        parser.add_argument('--check', action='store_true',
                            help="PRÉ-VOL seul : la base accepte-t-elle les chemins cibles ?")
        parser.add_argument('--app', default='', help="Restreindre à une app (label Django)")

    # ── Plan ────────────────────────────────────────────────────────────────────────────
    def _plan(self, racine: Path, filtre: str):
        """Plan indexé par CHEMIN SOURCE — correction n°2 (fichiers partagés).

        Un fichier peut être désigné par plusieurs lignes, de plusieurs modèles : le déplacer
        est UN geste qui doit mettre à jour TOUTES ses références, sous peine de casser celles
        qu'on n'a pas regardées.
        """
        refs = defaultdict(list)     # valeur source → [(modèle, nom de champ, pk)]
        longueurs = {}               # "app.Modèle.champ" → (max longueur cible, max_length)
        absents, hors = 0, 0

        for modele, champ in champs_fichier():
            if filtre and modele._meta.app_label != filtre:
                continue
            nom = champ.name
            cle = f"{modele._meta.app_label}.{modele.__name__}.{nom}"
            qs = modele.objects.exclude(**{nom: ''}).exclude(**{f'{nom}__isnull': True})
            for pk, valeur in qs.values_list('pk', nom).iterator():
                dest = cible(valeur)
                if dest is None:
                    hors += 1
                    continue
                # ⚠ La longueur se relève sur TOUTE ligne en périmètre, y compris celles dont le
                # fichier manque : la base sera écrite pour elles aussi si on les rencontre un
                # jour, et un pré-vol qui n'inspecte que les fichiers présents sous-estime.
                vu, borne = longueurs.get(cle, (0, champ.max_length))
                longueurs[cle] = (max(vu, len(dest)), borne)
                if not (racine / valeur).is_file():
                    absents += 1      # préexistant — `check_media_integrity` les connaît déjà
                    continue
                refs[valeur].append((modele, nom, pk))

        return refs, longueurs, absents, hors

    # ── Pré-vol ─────────────────────────────────────────────────────────────────────────
    def _prevol(self, longueurs: dict) -> list:
        """Champs dont le chemin CIBLE le plus long dépasse le `max_length` de la colonne.

        C'est la correction n°1 : le refus de la base doit tomber AVANT qu'un octet ne bouge,
        pas à mi-parcours. Rend la liste des champs à élargir — vide = la base tiendra.
        """
        return [(cle, vu, borne) for cle, (vu, borne) in sorted(longueurs.items())
                if borne is not None and vu > borne]

    def handle(self, *args, **opts):
        racine = Path(settings.MEDIA_ROOT)
        appliquer, prevol_seul, filtre = opts['apply'], opts['check'], opts['app']

        refs, longueurs, absents, hors = self._plan(racine, filtre)
        tailles = {v: (racine / v).stat().st_size for v in refs}
        octets = sum(tailles.values())
        lignes = sum(len(r) for r in refs.values())
        partages = {v: r for v, r in refs.items() if len(r) > 1}

        entete = "PRÉ-VOL" if prevol_seul else ("EXÉCUTION" if appliquer else "PLAN (rien n'est écrit)")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("DÉPLACEMENT VERS LE DOMICILE UNIQUE — " + entete))
        self.stdout.write(f"  fichiers à déplacer  : {len(refs)}   ({octets / 1e9:.2f} Go)")
        self.stdout.write(f"  lignes à réécrire    : {lignes}")
        self.stdout.write(f"  dont fichiers PARTAGÉS par plusieurs lignes : {len(partages)}"
                          "   (duplicate_instance — cause n°2 de l'échec du 11/09)")
        self.stdout.write(f"  déjà hors périmètre  : {hors}   (users/, médiathèque, montages…)")
        self.stdout.write(f"  ⚠ valeurs SANS fichier sur le disque : {absents}"
                          "   (préexistant — `check_media_integrity` les connaît)")

        # ── Pré-vol : il s'affiche TOUJOURS, et il BLOQUE `--apply` ──────────────────────
        trop_longs = self._prevol(longueurs)
        self.stdout.write("")
        self.stdout.write("  PRÉ-VOL — longueur du chemin cible vs `max_length` de la colonne :")
        for cle, (vu, borne) in sorted(longueurs.items()):
            marque = "❌" if (borne is not None and vu > borne) else "✅"
            self.stdout.write(f"    {marque} {cle:52s} cible max {vu:4d}  /  colonne {borne}")

        if trop_longs:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(
                f"  ❌ {len(trop_longs)} champ(s) trop étroit(s) — la base REFUSERAIT en vol, "
                "comme le 2026-09-11."))
            self.stdout.write("     Élargir `max_length` sur ces champs et migrer AVANT de "
                              "relancer avec --apply.")
            if appliquer:
                self.stdout.write(self.style.ERROR(
                    "  → --apply REFUSÉ. Rien n'a été touché (c'est tout l'objet du pré-vol)."))
            return

        if prevol_seul:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("  ✅ la base accepte tous les chemins cibles."))
            return

        if not appliquer:
            par_app = defaultdict(lambda: [0, 0])
            for valeur, r in refs.items():
                modele, nom, _pk = r[0]
                e = par_app[f"{modele._meta.app_label}.{modele.__name__}.{nom}"]
                e[0] += 1
                e[1] += tailles[valeur]
            self.stdout.write("")
            for cle in sorted(par_app):
                n, t = par_app[cle]
                self.stdout.write(f"    {cle:52s} {n:5d}   {t / 1e9:6.2f} Go")
            self.stdout.write("")
            self.stdout.write("  → relancer avec --apply pour exécuter")
            return

        # ── EXÉCUTION — un FICHIER = une unité atomique ──────────────────────────────────
        deplaces, relignes, echecs = 0, 0, []
        for valeur, r in refs.items():
            dest = cible(valeur)
            src, dst = racine / valeur, racine / dest
            try:
                # ⚠ Corrections n°3 et n°4 : la base d'abord, le rename DANS la transaction.
                # Si `os.rename` lève, l'exception traverse l'`atomic()` et la base revient
                # seule — aucune réparation rétroactive à écrire, donc aucune réparation à
                # rater (c'est elle qui avait cassé des lignes saines le 11/09).
                with transaction.atomic():
                    for modele, nom, pk in r:
                        modele.objects.filter(pk=pk).update(**{nom: dest})
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    # `os.rename` et NON `shutil.move` : le second copierait en silence si le
                    # rename échouait, et le disque n'a pas la place.
                    os.rename(src, dst)
            except Exception as exc:
                echecs.append((valeur, f"{type(exc).__name__}: {exc}"))
                continue
            deplaces += 1
            relignes += len(r)

        self.stdout.write("")
        self.stdout.write(f"  déplacés : {deplaces} / {len(refs)} fichiers"
                          f"   ({relignes} ligne(s) réécrite(s))")
        if echecs:
            self.stdout.write(self.style.ERROR(
                f"  ÉCHECS : {len(echecs)} fichier(s) — les autres sont COHÉRENTS "
                "(base et disque d'accord). Relancer la commande reprend ce qui reste."))
            for v, e in echecs[:10]:
                self.stdout.write(f"    {v} — {e}")
