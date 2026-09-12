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

⚠⚠ LE PLAN PART DU DISQUE, PAS DE LA BASE — corrigé le 2026-09-12 (constat de Fabien : les
    sorties de l'anonymizer n'avaient pas bougé). La première version énumérait les champs
    fichier et déplaçait ce qu'ils désignaient : **275 fichiers / 11,7 Go sont restés dans les
    arbres d'app, dont 273 qu'aucune ligne ne référence.** Leur chemin était pourtant standard —
    ils étaient simplement INCONNUS de la base.
    *Une migration de FICHIERS qui s'énumère depuis la BASE ne voit pas les orphelins, par
    définition.* Le disque est le seul inventaire complet de ce qu'il contient ; la base sert
    d'index INVERSE, pour réécrire les références quand il y en a.

⚠ CE QUI RESTE VOLONTAIREMENT HORS PÉRIMÈTRE, et pourquoi : un dossier d'app SANS identifiant
    utilisateur (`avatarizer/gallery`, `synthesizer/voice_references`, `synthesizer/
    default_voices`) n'appartient à personne — ce sont des ressources d'APPLICATION. Les loger
    chez un utilisateur serait faux. Ils sont exclus PAR CONSTRUCTION (pas d'identifiant dans le
    chemin), sans liste à tenir.

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

#: ⚠ `SOUS_DOSSIERS = ('input', 'output')` vivait ici et RESTREIGNAIT le périmètre. Retiré le
#: 2026-09-12 : il excluait `synthesizer/<uid>/custom_voices`, `composer/<uid>/batch_imports` et
#: `cam_analyzer/<uid>/input/rtmaps` — des octets d'utilisateur comme les autres. Ce qui délimite
#: le périmètre est la présence de l'IDENTIFIANT UTILISATEUR dans le chemin (cf. `cible`), pas une
#: liste de noms de dossiers qu'il aurait fallu tenir à jour à chaque app.


def champs_fichier():
    """Tous les (modèle, champ) pouvant porter un chemin média — DÉRIVÉ, jamais listé.

    Une liste écrite à la main omettrait le champ ajouté demain, et l'omission ne se verrait
    qu'au moment où un utilisateur ouvrirait une card vide. On rend le CHAMP et non son nom :
    le pré-vol a besoin de son `max_length`.

    ⚠⚠ LES CHAMPS TEXTE EN FONT PARTIE — ajouté le 2026-09-12, après un défaut que j'ai
    INTRODUIT. `anonymizer.Media.output_file` est un `CharField(max_length=500)`, pas un
    `FileField` : la migration a déplacé les 20 sorties de l'anonymizer **sans jamais réécrire
    les lignes qui les désignent**, et l'aperçu de SORTIE s'est mis à pointer dans le vide.

    *Un chemin de fichier ne vit pas seulement dans un `FileField`.* Le risque de balayer large
    est nul ici : un champ texte n'est retenu que si SA VALEUR a exactement la forme
    `<app>/<uid>/…` (cf. `cible`) — une phrase, une clé, un identifiant n'y ressemblent pas.
    """
    for modele in django_apps.get_models():
        for champ in modele._meta.get_fields():
            if isinstance(champ, models.FileField):
                yield modele, champ
            elif (isinstance(champ, (models.CharField, models.TextField))
                    and not getattr(champ, 'choices', None)):
                yield modele, champ


#: Racines qui ne sont PAS des arbres d'app — déjà à leur place, ou hors périmètre par décision.
HORS_PERIMETRE = ('users', 'media_library', 'mounts', 'nightly_tests', 'tests_lot', 'studio')


def cible(valeur: str):
    """`<app>/<uid>/reste…` → `users/<uid>/<app>/reste…`, ou `None` si hors périmètre.

    ⚠ DEUX ÉLARGISSEMENTS le 2026-09-12, après que Fabien a constaté que les sorties de
    l'anonymizer étaient restées sur place :
      1. **le sous-dossier n'est plus filtré à `input`/`output`**. `synthesizer/1/custom_voices`
         et `cam_analyzer/1/input/rtmaps` sont des octets d'utilisateur au même titre ; les
         exclure laissait des poches entières hors du domicile. Ce qui définit le périmètre
         n'est pas le nom du sous-dossier, c'est la présence de l'IDENTIFIANT UTILISATEUR ;
      2. la profondeur minimale passe de 4 à **3** segments (`<app>/<uid>/<fichier>`).

    Ce qui délimite reste inchangé et suffit : un `<uid>` numérique en 2ᵉ position. Les dossiers
    PARTAGÉS (`avatarizer/gallery`, `synthesizer/voice_references`) n'en ont pas — ils sont donc
    exclus par construction, sans liste à tenir.
    """
    parts = (valeur or '').replace('\\', '/').split('/')
    if len(parts) < 3:
        return None
    app, uid = parts[0], parts[1]
    if app in HORS_PERIMETRE or not uid.isdigit():
        return None
    return '/'.join(['users', uid, app, *parts[2:]])


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
        """Plan construit depuis le DISQUE, la base servant d'index INVERSE.

        ⚠⚠ C'EST LA CORRECTION DU 2026-09-12, ET ELLE EST STRUCTURELLE. La première version
        partait de la BASE : elle parcourait les champs fichier et déplaçait ce qu'ils
        désignaient. Conséquence mesurée quand Fabien a constaté que les sorties de l'anonymizer
        n'avaient pas bougé : **275 fichiers / 11,7 Go étaient restés dans les arbres d'app,
        dont 273 qu'AUCUNE ligne ne référence**. Ils étaient invisibles à la migration — non
        parce que leur chemin avait une forme spéciale (il était parfaitement standard), mais
        parce que personne ne les citait.

        *Une migration de FICHIERS qui s'énumère depuis la BASE ne voit que ce que la base
        connaît — et un orphelin est exactement ce qu'elle ne connaît pas.* Le disque est le
        seul inventaire complet de ce qu'il contient.

        On garde intégralement la correction n°2 (raisonner par FICHIER) : la base est lue en
        index inverse `chemin → [(modèle, champ, pk)]`, de sorte qu'un fichier partagé par
        plusieurs lignes met à jour TOUTES ses références en un seul geste. Un fichier sans
        aucune référence se déplace quand même — il n'y a simplement rien à réécrire.
        """
        refs = defaultdict(list)     # chemin source → [(modèle, nom de champ, pk)]
        realign = defaultdict(list)  # chemin source DÉJÀ déplacé → lignes restées en arrière
        longueurs = {}               # "app.Modèle.champ" → (max longueur cible, max_length)
        absents, hors = 0, 0

        # ── 1. La base en index INVERSE (et le pré-vol, qui ne concerne qu'elle) ──────────
        for modele, champ in champs_fichier():
            if filtre and modele._meta.app_label != filtre:
                continue
            nom = champ.name
            cle = f"{modele._meta.app_label}.{modele.__name__}.{nom}"
            qs = modele.objects.exclude(**{nom: ''}).exclude(**{f'{nom}__isnull': True})
            for pk, valeur in qs.values_list('pk', nom).iterator():
                valeur = (valeur or '').replace('\\', '/')
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
                    # ⚠ TROIS CAS, et confondre les deux premiers est ce qui a cassé l'aperçu
                    # de sortie de l'anonymizer : le fichier peut être DÉJÀ à sa destination
                    # (déplacé lors d'une passe précédente, la ligne restée en arrière) — il
                    # faut alors RÉALIGNER la ligne, pas la compter comme absente.
                    if (racine / dest).is_file():
                        realign[valeur].append((modele, nom, pk))
                    else:
                        absents += 1  # préexistant — `check_media_integrity` les connaît déjà
                    continue
                refs[valeur].append((modele, nom, pk))

        # ── 2. Le DISQUE, qui seul connaît les orphelins ────────────────────────────────
        for app_dir in sorted(racine.iterdir()):
            if not app_dir.is_dir() or app_dir.name in HORS_PERIMETRE:
                continue
            if filtre and app_dir.name != filtre:
                continue
            for fichier in app_dir.rglob('*'):
                if not fichier.is_file():
                    continue
                rel = fichier.relative_to(racine).as_posix()
                if cible(rel) is None:
                    hors += 1          # dossier PARTAGÉ (pas d'identifiant) — hors domicile
                    continue
                refs.setdefault(rel, [])   # orphelin : à déplacer, rien à réécrire

        return refs, realign, longueurs, absents, hors

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

        refs, realign, longueurs, absents, hors = self._plan(racine, filtre)
        tailles = {v: (racine / v).stat().st_size for v in refs}
        octets = sum(tailles.values())
        lignes = sum(len(r) for r in refs.values())
        partages = {v: r for v, r in refs.items() if len(r) > 1}
        a_realigner = sum(len(r) for r in realign.values())

        entete = "PRÉ-VOL" if prevol_seul else ("EXÉCUTION" if appliquer else "PLAN (rien n'est écrit)")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("DÉPLACEMENT VERS LE DOMICILE UNIQUE — " + entete))
        self.stdout.write(f"  fichiers à déplacer  : {len(refs)}   ({octets / 1e9:.2f} Go)")
        self.stdout.write(f"  lignes à réécrire    : {lignes}")
        self.stdout.write(f"  dont fichiers PARTAGÉS par plusieurs lignes : {len(partages)}"
                          "   (duplicate_instance — cause n°2 de l'échec du 11/09)")
        self.stdout.write(f"  déjà hors périmètre  : {hors}   (users/, médiathèque, montages…)")
        self.stdout.write(self.style.WARNING(
            f"  lignes à RÉALIGNER   : {a_realigner}   (le fichier est DÉJÀ au domicile, la "
            "ligne pointe encore sur l'ancien chemin)") if a_realigner else
            f"  lignes à RÉALIGNER   : 0")
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
            # ⚠ Groupé par ARBRE D'APP et non par champ de modèle : depuis que le plan part du
            # disque, la plupart des fichiers n'ont AUCUNE référence — lire `r[0]` levait.
            par_app = defaultdict(lambda: [0, 0, 0])   # fichiers, octets, dont référencés
            for valeur, r in refs.items():
                e = par_app[valeur.split('/')[0]]
                e[0] += 1
                e[1] += tailles[valeur]
                e[2] += 1 if r else 0
            self.stdout.write("")
            self.stdout.write(f"    {'arbre d’app':22s} {'fichiers':>8s} {'Go':>7s} "
                              f"{'référencés':>11s} {'ORPHELINS':>10s}")
            for cle in sorted(par_app):
                n, t, ref = par_app[cle]
                self.stdout.write(f"    {cle:22s} {n:>8d} {t / 1e9:>7.2f} {ref:>11d} "
                                  f"{n - ref:>10d}")
            self.stdout.write("")
            self.stdout.write("  → relancer avec --apply pour exécuter")
            return

        # ── RÉALIGNEMENT — aucune écriture disque, seulement la base qui rattrape ────────
        realignees = 0
        for valeur, r in realign.items():
            dest = cible(valeur)
            with transaction.atomic():
                for modele, nom, pk in r:
                    modele.objects.filter(pk=pk).update(**{nom: dest})
            realignees += len(r)
        if realignees:
            self.stdout.write(self.style.SUCCESS(
                f"  réalignées : {realignees} ligne(s) — elles désignent à nouveau leur fichier"))

        # ── EXÉCUTION — un FICHIER = une unité atomique ──────────────────────────────────
        deplaces, relignes, echecs, collisions = 0, 0, [], []
        for valeur, r in refs.items():
            dest = cible(valeur)
            src, dst = racine / valeur, racine / dest
            # ⚠⚠ `os.rename` ÉCRASE SILENCIEUSEMENT une destination existante sous POSIX. Tant
            # qu'on ne déplaçait que des fichiers RÉFÉRENCÉS, le cas ne pouvait guère se
            # produire ; en déplaçant aussi les ORPHELINS, deux homonymes — l'un déjà migré,
            # l'autre resté — se retrouvent sur la même cible, et le second effacerait le
            # premier. *Une migration ne détruit jamais pour avancer* : on refuse, on nomme,
            # et l'arbitrage revient à l'humain.
            if dst.exists():
                collisions.append((valeur, dest))
                continue
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
        if collisions:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {len(collisions)} COLLISION(S) — la cible existait déjà, la source est "
                "LAISSÉE EN PLACE (rien n'a été écrasé). À arbitrer un par un :"))
            for src_rel, dst_rel in collisions[:15]:
                self.stdout.write(f"    {src_rel}\n      → occupé : {dst_rel}")
            if len(collisions) > 15:
                self.stdout.write(f"    … et {len(collisions) - 15} autre(s)")
        if echecs:
            self.stdout.write(self.style.ERROR(
                f"  ÉCHECS : {len(echecs)} fichier(s) — les autres sont COHÉRENTS "
                "(base et disque d'accord). Relancer la commande reprend ce qui reste."))
            for v, e in echecs[:10]:
                self.stdout.write(f"    {v} — {e}")
