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


class WamaTestRunner(DiscoverRunner):
    """`DiscoverRunner` + `MEDIA_ROOT` redirigé vers un dossier jetable."""

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
