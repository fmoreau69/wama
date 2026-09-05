"""Gardes du Face Analyzer — l'app tourne dans le VENV PRINCIPAL, et ça doit le rester.

Ces tests sont nés d'une vérification demandée par Fabien le 2026-09-05 (« je me demande si le
face analyzer est toujours fonctionnel aujourd'hui car le venv_linux a évolué »). Elle a trouvé
le backend PAR DÉFAUT cassé depuis une montée de version silencieuse. Aucun test ne couvrait
cette app : elle a donc pourri sans bruit pendant des mois.

⚠ Ils ne chargent AUCUN modèle et ne touchent pas au GPU : ils vérifient les *jonctions* — le
chemin d'import et le rangement des poids. Le fonctionnement réel se prouve par un smoke
(cf. README §Vérification), pas par la suite unitaire.
"""
import os
import unittest
from importlib.util import find_spec
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

_FER_PRESENT = find_spec('fer') is not None
_DEEPFACE_PRESENT = find_spec('deepface') is not None


class BackendEmotionsImportableTest(SimpleTestCase):
    """Le backend PAR DÉFAUT doit s'importer — c'est lui qui a cassé.

    `fer` 25.10.3 a retiré `FER` de sa racine (la classe vit dans `fer.fer`), et
    `requirements/linux.txt` demandait `fer>=22.5.0` — borne haute absente, donc la montée
    s'est faite toute seule et l'app est passée au rouge sans que rien ne le dise.
    """

    @unittest.skipUnless(_FER_PRESENT, "paquet `fer` absent de ce venv")
    def test_la_classe_FER_se_trouve_quelle_que_soit_la_disposition(self):
        from wama_lab.face_analyzer.emotions import _import_fer
        try:
            classe = _import_fer()
        except ImportError as e:
            # ⚠ VENV-DÉPENDANT, et c'est assumé : en venv_win `fer` casse sur `pkg_resources`
            # (setuptools 81+ ; le pin `setuptools<81` ne vit que dans requirements_linux).
            # On SKIPPE en disant pourquoi plutôt que de rougir sur un défaut d'environnement
            # — venv_linux fait foi, c'est là que la garde a du sens (et là qu'elle a servi).
            self.skipTest(f"`fer` inutilisable dans CE venv : {e}")
        self.assertEqual(classe.__name__, 'FER')

    @unittest.skipUnless(_FER_PRESENT, "paquet `fer` absent de ce venv")
    def test_le_backend_par_defaut_est_bien_celui_qui_est_couvert(self):
        """Si le défaut changeait, cette garde protégerait le mauvais chemin."""
        from wama_lab.face_analyzer.emotions import EmotionRecognizer
        import inspect
        defaut = inspect.signature(EmotionRecognizer.__init__).parameters['backend'].default
        self.assertEqual(defaut, 'fer')


class PoidsDeepFaceRangesTest(SimpleTestCase):
    """Les poids DeepFace vivent dans `AI-models`, jamais dans le HOME de l'utilisateur.

    Sans `DEEPFACE_HOME`, `get_deepface_home()` retombe sur `~` : **1,1 Go** dormaient dans
    `$HOME/.deepface` (age 514 Mo + gender 512 Mo + expression 5,7 Mo), hors d'`AI-models`,
    hors catalogue, invisibles de toute page WAMA (mesuré le 2026-09-05).

    C'est le même défaut de famille que les résidus HF nettoyés le 03/09 — un poids qui
    atterrit là où personne ne le cherche — mais par un autre canal : DeepFace ne passe pas
    par HuggingFace, donc aucune des gardes HF ne pouvait le voir.
    """

    def test_DEEPFACE_HOME_est_pose_et_pointe_dans_AI_models(self):
        home = os.environ.get('DEEPFACE_HOME', '')
        self.assertTrue(home, "DEEPFACE_HOME non posé — les poids repartiraient dans ~/.deepface")
        self.assertIn(str(Path(settings.AI_MODELS_DIR).resolve()),
                      str(Path(home).resolve()),
                      "DEEPFACE_HOME doit pointer DANS AI-models")

    def test_le_socle_est_pose_UNE_FOIS_dans_settings_jamais_dans_un_backend(self):
        """Même règle que le cache HF : l'environnement se pose au démarrage, point.

        Une mutation dans un backend est globale au processus et emporte ce que la lib
        télécharge ENSUITE — c'est la leçon écrite au CLAUDE.md, elle vaut pour toute
        variable d'aiguillage, pas seulement pour celles de HuggingFace.
        """
        racine = Path(settings.BASE_DIR)
        coupables = []
        for f in list((racine / 'wama').rglob('*.py')) + list((racine / 'wama_lab').rglob('*.py')):
            if 'venv' in f.parts or 'site-packages' in f.parts or f.name == 'tests.py':
                continue                      # un test CITE les motifs qu'il traque
            try:
                texte = f.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            if "environ['DEEPFACE_HOME']" in texte or 'environ["DEEPFACE_HOME"]' in texte:
                coupables.append(str(f.relative_to(racine)))
        self.assertEqual(coupables, [],
                         "DEEPFACE_HOME muté hors de settings.py — interdit (cf. CLAUDE.md)")

    @unittest.skipUnless(_DEEPFACE_PRESENT, "paquet `deepface` absent de ce venv")
    def test_la_librairie_resout_le_meme_dossier_que_le_socle(self):
        """Contre-épreuve : poser la variable ne suffit pas, encore faut-il que la lib la lise."""
        from deepface.commons import folder_utils
        self.assertEqual(Path(folder_utils.get_deepface_home()).resolve(),
                         Path(os.environ['DEEPFACE_HOME']).resolve())


class AppDansLeVenvPrincipalTest(SimpleTestCase):
    """L'app est une app Django ORDINAIRE — ses venvs locaux sont des reliquats.

    Vérifié le 2026-09-05 : `wama_lab/face_analyzer/venv_linux` n'a jamais servi (0 paquet,
    arborescence `Scripts/Lib` d'un venv créé sous Windows) et `venv_win` (2,7 Go) est
    l'environnement de l'époque autonome, que plus rien ne référence.

    Ce test ne réclame pas leur suppression — il réclame que le CODE ne recommence jamais à
    en dépendre. *La documentation de l'app affirmait le contraire pendant des mois ; une
    affirmation ne vaut pas une garde.*
    """

    def test_aucun_code_ne_pointe_vers_un_venv_local_de_l_app(self):
        racine = Path(settings.BASE_DIR) / 'wama_lab' / 'face_analyzer'
        coupables = []
        for f in racine.rglob('*.py'):
            if 'venv' in f.parts or 'site-packages' in f.parts or f.name == 'tests.py':
                continue                      # idem : ce fichier NOMME les reliquats qu'il interdit
            try:
                texte = f.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            if 'venv_win' in texte or 'venv_linux' in texte:
                coupables.append(str(f.relative_to(racine)))
        self.assertEqual(coupables, [],
                         "le code de l'app référence un venv local : elle doit tourner dans "
                         "le venv principal (cf. INFRA_WSL_VS_WINDOWS.md §Venvs isolés)")

    def test_l_app_est_bien_installee_donc_ses_taches_sont_joignables(self):
        from django.apps import apps
        self.assertTrue(apps.is_installed('wama_lab.face_analyzer'),
                        "app absente d'INSTALLED_APPS : sa tâche Celery ne serait pas routée")
