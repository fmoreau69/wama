"""Runner de tests WAMA — isole le média des tests du média de PRODUCTION.

POURQUOI (mesuré le 2026-08-25)
    La suite écrivait dans le `MEDIA_ROOT` réel : **1069 fichiers de test** s'y étaient
    accumulés, dispersés dans les dossiers d'app — et jusque dans les dossiers d'
    utilisateurs RÉELS (`regis.blanchet`, `Gwen`, `fmoreau`), parce que les identifiants
    d'une base de TEST entrent en collision avec ceux de la base réelle.

    Ce n'est pas qu'une question de propreté : quand `media/synthesizer/13/input/test.txt`
    existe déjà, Django renomme le suivant (`test_c5e24b5d.txt`) pour éviter la collision,
    et `assertIn('test.txt', synthesis.filename)` tombe. `test_filename_property` échouait
    donc SELON L'HISTORIQUE DES EXÉCUTIONS — le compte d'échecs oscillait 8↔9 sans qu'aucune
    ligne de code ne change.

    Le même diagnostic avait déjà été posé et corrigé LOCALEMENT dans
    `wama/gateway/tests.py` (`override_settings(MEDIA_ROOT=tempfile.mkdtemp(...))`), avec le
    bon commentaire — mais jamais généralisé. Le corriger par app, c'est le réintroduire à
    la prochaine app qui l'oublie : la redirection appartient au HARNAIS, pas aux tests.

CE QUE ÇA FAIT
    Chaque exécution reçoit son propre sous-dossier de `media_tests/`, supprimé à la fin.
    Aucune accumulation, donc aucune collision, donc plus d'instabilité — et le média de
    production n'est jamais touché.

    Échappatoire : `WAMA_GARDER_MEDIA_TESTS=1` conserve le dossier pour inspection après
    coup (il est alors affiché en fin de campagne).

⚠ Ne supprime QUE le dossier qu'il a lui-même créé — jamais un chemin fourni de l'extérieur,
  jamais `MEDIA_ROOT`.

⚠⚠ UN HARNAIS QUI INSTANCIE `DiscoverRunner` DIRECTEMENT CONTOURNE CETTE PROTECTION.
    `TEST_RUNNER` n'est honoré que par `manage.py test`. Un script qui fait
    `DiscoverRunner(...).setup_databases()` obtient bien une base de test — mais garde le
    `MEDIA_ROOT` de PRODUCTION.

    Vécu le 2026-08-25, une heure après l'écriture de ce fichier : un script de vérification
    monté ainsi a créé un utilisateur et un job de pk 1 dans sa base de test, puis appelé la
    suppression — qui a visé le VRAI `media/avatarizer/1/output/job_1` et l'a effacé. Les
    identifiants d'une base de test recommencent à 1 et entrent donc en collision avec les
    vrais : c'est la MÊME cause que celle qui avait dispersé 1069 fichiers dans `media/`.
    (Aucune perte ce jour-là : le dossier était un orphelin de 0 Mo déjà voué à la purge.)

    → Dans un script hors `manage.py test`, prendre le runner CONFIGURÉ, jamais la classe :

        from django.conf import settings
        from django.test.utils import get_runner
        runner = get_runner(settings)(verbosity=0, interactive=False)   # ← WamaTestRunner
        runner.setup_test_environment()      # ← indispensable : c'est LUI qui redirige
        vieux = runner.setup_databases()
"""
import os
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner

#: Racine des médias de test, sœur de `media/` — JAMAIS dedans : `media/` est servi par
#: Apache, sauvegardé et « tiré » (mirror_sync). Un dossier de test y serait servi et copié.
DOSSIER_MEDIAS_DE_TEST = 'media_tests'

_GARDER = os.environ.get('WAMA_GARDER_MEDIA_TESTS', '').strip() not in ('', '0', 'false', 'False')

#: Racines du dépôt que la DÉCOUVERTE de tests ne doit pas visiter.
#:
#: ⚠ Ce ne sont PAS des tests exclus : ce sont des dossiers qui n'en contiennent aucun et
#: que Python n'importe jamais — la règle de nommage du dépôt (CLAUDE.md, « le critère est
#: *Python l'importe-t-il ?* ») les écrit justement en tiret-case pour le dire. Un tiret
#: rend le paquet inimportable (`import wama-dev-ai` = « wama moins data »), et leurs
#: modules internes s'importent en absolu (`from config import …`) parce que leur lanceur
#: pose leur dossier sur `sys.path`. La découverte de `unittest`, elle, parcourt le dépôt
#: entier : elle y descendait, tentait l'import, et chaque campagne portait DEUX ERREURS
#: permanentes (`wama-dev-ai.core`, `wama-dev-ai.ui` — `No module named 'core'`/'ui'`).
#:
#: Corrigé ici et pas là-bas : rendre ces modules importables demanderait de restructurer
#: un outil hors périmètre Django (son `config.py` vit au-dessus du paquet, donc aucun
#: import relatif ne l'atteint — essayé et MESURÉ le 2026-08-27, l'erreur se déplace
#: simplement d'un cran). Deux rouges permanents dans une suite, c'est deux rouges que
#: plus personne ne lit.
RACINES_HORS_DECOUVERTE = ('wama-dev-ai',)


class WamaTestRunner(DiscoverRunner):
    """`DiscoverRunner` + `MEDIA_ROOT` redirigé vers un dossier jetable."""

    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        elagues = _elaguer_racines_hors_decouverte(suite)
        if elagues and self.verbosity >= 1:
            print(f"Découverte : {len(elagues)} module(s) ignoré(s) hors périmètre "
                  f"({', '.join(sorted(elagues))}).")
        return suite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        racine = Path(settings.BASE_DIR) / DOSSIER_MEDIAS_DE_TEST
        racine.mkdir(parents=True, exist_ok=True)
        # Un sous-dossier PAR EXÉCUTION : deux campagnes concurrentes (deux instances
        # Claude, un nocturne pendant une session) ne se marchent pas dessus, et rien ne
        # survit d'une exécution à l'autre — c'est cette survivance qui créait la collision.
        self._media_de_test = Path(tempfile.mkdtemp(prefix='run-', dir=str(racine)))
        self._media_reel = settings.MEDIA_ROOT
        settings.MEDIA_ROOT = str(self._media_de_test)

    def teardown_test_environment(self, **kwargs):
        dossier = getattr(self, '_media_de_test', None)
        settings.MEDIA_ROOT = getattr(self, '_media_reel', settings.MEDIA_ROOT)
        if dossier is not None:
            if _GARDER:
                print(f"\nMédias de test conservés (WAMA_GARDER_MEDIA_TESTS) : {dossier}")
            else:
                _supprimer_sans_risque(dossier)
        super().teardown_test_environment(**kwargs)


def _racine_exclue(test) -> str:
    """Racine de `RACINES_HORS_DECOUVERTE` dont provient cet échec d'IMPORT, sinon ''.

    Ne reconnaît QUE les `_FailedTest` fabriqués par la découverte : un vrai test qui
    échoue n'en est pas un, donc rien de réel ne peut être élagué par erreur.
    """
    from unittest.loader import _FailedTest
    if not isinstance(test, _FailedTest):
        return ''
    nom = getattr(test, '_testMethodName', '')
    for racine in RACINES_HORS_DECOUVERTE:
        if nom == racine or nom.startswith(racine + '.'):
            return racine
    return ''


def _elaguer_racines_hors_decouverte(suite) -> set:
    """Retire de `suite` (en place, récursivement) les échecs d'import des racines exclues.

    ⚠ Garde-fou : si l'une de ces racines vient à contenir un vrai fichier de test, on
    REFUSE d'élaguer et on le dit. Sans cela, déposer un test dans un dossier exclu
    reviendrait à ne jamais l'exécuter — sans le moindre signal.
    """
    from unittest import TestSuite
    elagues = set()
    for i, item in enumerate(list(suite._tests)):
        if isinstance(item, TestSuite):
            elagues |= _elaguer_racines_hors_decouverte(item)
        else:
            racine = _racine_exclue(item)
            if racine:
                _refuser_si_tests_reels(racine)
                elagues.add(getattr(item, '_testMethodName', racine))
    suite._tests = [t for t in suite._tests
                    if isinstance(t, TestSuite) or not _racine_exclue(t)]
    return elagues


def _refuser_si_tests_reels(racine: str) -> None:
    dossier = Path(settings.BASE_DIR) / racine
    trouves = [p for p in dossier.rglob('test*.py')] if dossier.is_dir() else []
    if trouves:
        raise RuntimeError(
            f"`{racine}` est listé dans RACINES_HORS_DECOUVERTE mais contient "
            f"{len(trouves)} fichier(s) de test ({trouves[0]}). Retirer la racine de la "
            f"liste (et rendre ses modules importables), ou déplacer ces tests.")


def _supprimer_sans_risque(dossier: Path) -> None:
    """Supprime `dossier` UNIQUEMENT s'il est bien un sous-dossier d'exécution.

    Trois vérifications, parce qu'un `rmtree` mal ciblé sur ce dépôt effacerait des médias
    irremplaçables. Aucune n'est redondante : la première interdit de sortir du dépôt, la
    deuxième d'atteindre autre chose que `media_tests/`, la troisième de viser la racine
    elle-même plutôt qu'une exécution.
    """
    try:
        cible = dossier.resolve()
        base = Path(settings.BASE_DIR).resolve()
        racine = (base / DOSSIER_MEDIAS_DE_TEST).resolve()
        if not str(cible).startswith(str(base)):
            return
        if cible.parent != racine:
            return
        if not cible.name.startswith('run-'):
            return
        shutil.rmtree(cible, ignore_errors=True)
    except Exception:
        # Un dossier temporaire non supprimé n'est pas une raison de faire échouer
        # une campagne de tests : il sera balayé au prochain passage.
        pass
