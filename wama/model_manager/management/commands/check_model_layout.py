"""
Un dossier de modèle ne contient QUE son modèle — détecteur de dépôts accidentels.

    python manage.py check_model_layout            # rapport
    python manage.py check_model_layout --json
    python manage.py check_model_layout --strict   # sort en 1 si un étranger est trouvé

POURQUOI CE CONTRÔLE EXISTE (2026-09-03, demande de Fabien : « régler ça définitivement sans
que ça réapparaisse pour un nouveau modèle et pollue à nouveau le registre »).

Le défaut : `os.environ['HF_HUB_CACHE'] = <dossier du modèle>` dans un backend. La variable
est **globale au processus** — elle n'oriente pas seulement le modèle demandé, elle emporte
**tout ce que la lib télécharge ensuite** dans le dossier de CE modèle. Chaque dépôt parasite
devient ensuite une **ligne de catalogue fantôme**, puisque la découverte balaie
`AI-models/models/` et prend tout `models--org--nom` pour un modèle.

CE QUI REND CE CONTRÔLE UTILE LÀ OÙ LES TESTS MANQUENT. Mesuré le 2026-09-03 : sur les
18 backends qui mutent l'environnement, **aucun n'a de test de chargement sur poids réels**
(les 4 qui sont nommés dans des tests n'y voient vérifier que des attributs déclarés). Écrire
18 harnais GPU n'est pas réaliste. Ce contrôle-ci regarde le DISQUE : il constate la
CONSÉQUENCE, quel que soit le backend fautif, sans GPU et sans poids chargés. C'est lui qui
permet de porter les sites restants (`ROADMAP §5b`) en le rejouant après un lancement réel.

CE QU'IL NE FAIT PAS : il ne nomme pas le coupable. Un dépôt étranger dit qu'un backend a
muté l'environnement, pas lequel — `wama/common/tests_hf_cache_routing.py` tient la liste des
sites restants.

⚠ Un composant LÉGITIME (pipeline pyannote, tokenizer publié à part) se DÉCLARE dans
`common/utils/model_locations.COMPOSANTS_DECLARES` ; il n'est jamais deviné. *Un contrôle qui
crie au loup finit par être ignoré.*

⚠ PAS DE GATE PAR DÉFAUT (`--strict` pour la CI). Les 8 étrangers présents au 2026-09-03 sont
un état HÉRITÉ : les signaler à chaque commande sans bloquer laisse le temps de les traiter
avec leur cause, plutôt que de forcer un nettoyage à l'aveugle qui casserait un chargement
(la copie sert peut-être encore un backend non porté).
"""
import json
import os

from django.core.management.base import BaseCommand


def _sous_dossiers(chemin):
    """Sous-dossiers directs — `scandir` sans suivre les liens : les entrailles d'un snapshot
    HF sont des symlinks que Windows ne sait pas `stat` (WinError 1920 mesurée)."""
    try:
        return sorted(e.name for e in os.scandir(chemin) if e.is_dir(follow_symlinks=False))
    except OSError:
        return []


def _snapshots(chemin):
    return [n for n in _sous_dossiers(chemin) if n.startswith('models--')]


def _cle(texte):
    return ''.join(c for c in texte.lower() if c.isalnum())


def analyser():
    """[(catégorie, famille, [snapshots], [étrangers])] pour les dossiers multi-snapshot."""
    from wama.common.utils.model_locations import models_root, composants_declares

    racine = models_root()
    resultats = []
    for categorie in _sous_dossiers(racine):
        cat_p = racine / categorie
        # Un dossier de catégorie peut porter des snapshots en direct (sans sous-famille).
        candidats = [(categorie, '', cat_p)]
        candidats += [(categorie, f, cat_p / f) for f in _sous_dossiers(cat_p)]
        for cat, fam, chemin in candidats:
            noms = _snapshots(chemin)
            if len(noms) < 2:
                continue
            attendu = _cle(fam or cat)
            declares = set(composants_declares(cat, fam) if fam else [])
            etrangers = [n for n in noms
                         if attendu not in _cle(n) and n not in declares]
            resultats.append((cat, fam, noms, etrangers))
    return resultats


def verrous_orphelins():
    """[(catégorie, famille, [noms])] — verrous `.locks` sans snapshot correspondant.

    TRACE d'une contamination PASSÉE déjà nettoyée : le modèle a été téléchargé là, puis
    retiré, mais son verrou est resté. Purement informatif — c'est ce qui prouve que le
    nettoyage seul ne suffit pas (on a nettoyé, et ça a repollué).
    """
    from wama.common.utils.model_locations import models_root

    racine = models_root()
    traces = []
    for categorie in _sous_dossiers(racine):
        cat_p = racine / categorie
        for fam in [''] + _sous_dossiers(cat_p):
            chemin = cat_p / fam if fam else cat_p
            lock = chemin / '.locks'
            if not lock.is_dir():
                continue
            presents = set(_snapshots(chemin))
            fantomes = [v for v in _snapshots(lock) if v not in presents]
            if fantomes:
                traces.append((categorie, fam, fantomes))
    return traces


class Command(BaseCommand):
    help = "Détecte les snapshots HF déposés dans le dossier d'un AUTRE modèle."

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help="Sortie JSON brute.")
        parser.add_argument('--strict', action='store_true',
                            help="Sort en 1 si un snapshot étranger est trouvé (CI).")
        parser.add_argument('--locks', action='store_true',
                            help="Montre aussi les verrous orphelins (contaminations passées).")

    def handle(self, *args, **options):
        resultats = analyser()
        etrangers = [(c, f, e) for c, f, _, e in resultats if e]
        total = sum(len(e) for _, _, e in etrangers)

        if options['json']:
            self.stdout.write(json.dumps({
                'etrangers': [{'categorie': c, 'famille': f, 'snapshots': e}
                              for c, f, e in etrangers],
                'total': total,
                'verrous_orphelins': [{'categorie': c, 'famille': f, 'noms': n}
                                      for c, f, n in verrous_orphelins()],
            }, indent=2, ensure_ascii=False))
            return

        self.stdout.write("=" * 78)
        self.stdout.write("DISPOSITION DES MODÈLES — un dossier ne contient que SON modèle")
        self.stdout.write("=" * 78)

        if not etrangers:
            self.stdout.write(self.style.SUCCESS(
                "\n✓ aucun snapshot étranger — aucun backend n'a déposé de dépendance "
                "dans le dossier d'un autre modèle."))
        else:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ {total} snapshot(s) ÉTRANGER(s) dans {len(etrangers)} dossier(s) :"))
            for cat, fam, noms in etrangers:
                self.stdout.write(f"\n  {cat}/{fam}" if fam else f"\n  {cat}")
                for n in noms:
                    self.stdout.write(f"      {n}")
            self.stdout.write(
                "\n  → soit c'est une DÉPENDANCE PARTAGÉE : sa place est le cache partagé, "
                "\n    et le vrai correctif est de retirer la mutation d'environnement du "
                "\n    backend qui l'a déposée (ROADMAP §5b) ;"
                "\n  → soit c'est un COMPOSANT du modèle : le déclarer dans "
                "\n    `common/utils/model_locations.COMPOSANTS_DECLARES` — jamais deviné.")

        if options['locks']:
            traces = verrous_orphelins()
            if traces:
                self.stdout.write(self.style.WARNING(
                    f"\n⚠ verrous `.locks` sans snapshot — contaminations PASSÉES, "
                    f"déjà nettoyées ({sum(len(n) for _, _, n in traces)}) :"))
                for cat, fam, noms in traces:
                    self.stdout.write(f"  {cat}/{fam} : {len(noms)}" if fam
                                      else f"  {cat} : {len(noms)}")
                    for n in noms:
                        self.stdout.write(f"      {n}")
                self.stdout.write(
                    "\n  *Ces traces sont la preuve que NETTOYER NE SUFFIT PAS : on a nettoyé, "
                    "\n  la cause est restée, et ça a repollué.*")

        if options['strict'] and etrangers:
            self.stderr.write("\n--strict : un dépôt étranger subsiste.")
            raise SystemExit(1)
