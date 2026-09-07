"""Garde du ROUTAGE des caches HuggingFace (ROADMAP §5b).

CE QUE CE CONTRÔLE PROTÈGE. Poser `os.environ['HF_HUB_CACHE'] = <dossier du modèle>` avant
un import HF est une règle TRANSITOIRE (`CLAUDE.md`, qui le dit lui-même) : la variable est
**globale au processus**, donc elle emporte dans le dossier du modèle principal tout ce que
la lib télécharge ensuite — sous-dépendances comprises. Le dépôt en porte déjà trois traces :

  - `wama/views.py:223` — « le **dump de modèles dans speech/kokoro** (`HF_HUB_CACHE` global
    muté en concurrence) », qui a coûté le retrait du préchargement Kokoro côté Django ;
  - `start_wama_prod.sh:271` — `--workers 1` du service TTS déclaré **STRUCTURANT**, pas un
    réglage de performance, à cause de cette même course ;
  - `model_manager/management/commands/dedup_models.py:3` — une commande entière écrite comme
    « séquelle de la course `os.environ['HF_HUB_CACHE']` qui a déversé… ».

Et une quatrième, MESURÉE le 2026-09-03 : `models--timm--resnet18.a1_in1k`, backbone timm du
DETR Table Transformer, s'est retrouvé DANS le dossier de table-transformer (et aussi dans le
cache partagé, sa place légitime) — d'où une ligne de catalogue fantôme pour une simple
sous-dépendance, sans tâche ni licence.

LA CIBLE (`ROADMAP §5b`, design validé le 2026-06-17) : `cache_dir=` explicite pour les
modèles PRINCIPAUX (la catégorisation est préservée, et c'est thread-safe), `HF_HOME` posé
**une seule fois au démarrage** pour les sous-dépendances partagées — ce qui est déjà le cas
(`settings.py:165-167`, en `setdefault`, et rien dans `.env` ni `start_wama_prod.sh` ne le
neutralise : vérifié).

CE QUE CE TEST FAIT — et surtout ce qu'il NE fait PAS. Il compte les sites de mutation
per-modèle restants et refuse qu'ils AUGMENTENT. Il ne prétend pas qu'ils sont tous
retirables : chacun se lit, et certains backends dépendent peut-être de la variable parce que
leur lib n'accepte pas `cache_dir=`. Le budget ne peut que DESCENDRE — un budget qui monte
tout seul cesse de protéger (leçon `CIBLES_ASSUMEES`, `/reprise`).

⚠ `settings.py` emploie `setdefault`, pas une affectation : il est hors périmètre PAR
CONSTRUCTION (on ne détecte que `os.environ[...] = ...`), et c'est voulu — c'est le socle.
"""

import ast
import re
import unittest

from django.conf import settings
from django.test import SimpleTestCase
from functools import lru_cache
from pathlib import Path

#: Variables dont la mutation per-modèle est le défaut visé.
#:
#: ⚠⚠ LE JETON A ÉTÉ AJOUTÉ LE 2026-09-07, et il a fallu un défaut pour y penser. La garde ne
#: comptait que le CACHE ; `sam3_processor` mutait `HF_TOKEN`/`HUGGING_FACE_HUB_TOKEN` depuis un
#: fichier posé dans le dossier du modèle — et l'écrivait en plus dans le `$HOME` de
#: l'utilisateur — pendant que le budget affichait 0. Le budget disait vrai sur ce qu'il
#: mesurait ; il ne mesurait pas tout.
#: Le jeton relève de la MÊME règle que le cache : un seul domicile, `.env` → `settings.py`, posé
#: une fois au démarrage. Un second exemplaire finit toujours par diverger de l'autre.
#: *Une garde se pose avec ses jumeaux : toutes les variables qui aiguillent le même sous-système.*
VARS_HF = {'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE', 'HF_HOME',
           'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'HUGGINGFACE_TOKEN'}

#: Sites de mutation MESURÉS le 2026-09-03, après les retraits de `table_transformer` (1er),
#: puis du goulot `model_config.setup_hf_cache_for_model` et des replis de `wan_video_backend`
#: et `hunyuan_video_backend` (les DEUX qui mutaient dès l'import).
#: NE JAMAIS RELEVER CE NOMBRE. Le faire descendre = porter un backend au §5b ; le voir
#: monter = une nouvelle mutation a été introduite, et c'est ce que ce test refuse.
BUDGET_MUTATIONS = 0

#: Modules dont l'IMPORT SEUL redirigeait le cache HF de tout le processus — le pire cas,
#: puisqu'il pollue sans qu'aucun modèle ne soit chargé et que le dernier importé gagne.
#: Aucun n'importe `torch` au niveau module (vérifié) : la sonde ne touche donc pas au GPU.
MODULES_SANS_EFFET_DE_BORD = (
    'wama.common.backends.wan_video_backend',
    'wama.common.backends.hunyuan_video_backend',
)

#: Bacs à sable : copies GÉNÉRÉES d'une app source. Une mutation y est le reflet de la
#: source, pas une décision — la compter deux fois ferait bouger le budget à chaque
#: régénération, sans qu'aucune dette réelle n'ait changé.
_SANDBOX = re.compile(r'_\d\d(/|$)')
_HORS_PERIMETRE = ('site-packages', 'staticfiles', '/archive/', 'musetalk',
                   '/migrations/', 'node_modules',
                   # ⚠ LE SOCLE EST LE DOMICILE, pas une dette. La règle dit « posées UNE FOIS
                   # au démarrage » : c'est ICI que ça se fait, et nulle part ailleurs. Exclu
                   # explicitement depuis que la garde couvre aussi le JETON (2026-09-07) —
                   # sans quoi elle condamnerait l'endroit même qu'elle prescrit.
                   'wama/settings.py')

#: Racines de CODE WAMA balayées. Explicites, et non un `rglob` depuis la racine du dépôt :
#: celui-ci descend dans `venv_win`/`venv_linux`, soit **97 000 des 113 000 fichiers .py**
#: mesurés le 2026-09-03 — 18 s de balayage pour un filtrage APRÈS coup. On élague pendant
#: la descente, jamais après.
_RACINES_CODE = ('wama', 'wama_lab', 'wama_data', 'scripts')

#: Dossiers dans lesquels on ne descend jamais (élagage `os.walk`).
_DOSSIERS_ELAGUES = {'__pycache__', 'node_modules', 'site-packages', 'staticfiles',
                     'archive', 'migrations', '.git'}


def _racine() -> Path:
    import wama
    return Path(wama.__file__).resolve().parent.parent


def _mutation(node):
    """Nom de la variable si `node` est `os.environ['HF_*'] = …`, sinon None."""
    if not isinstance(node, ast.Assign):
        return None
    for cible in node.targets:
        if (isinstance(cible, ast.Subscript)
                and isinstance(cible.value, ast.Attribute)
                and cible.value.attr == 'environ'
                and isinstance(cible.slice, ast.Constant)
                and cible.slice.value in VARS_HF):
            return cible.slice.value
    return None


@lru_cache(maxsize=1)
def sites_de_mutation():
    """[(chemin relatif, ligne, variable)] — par AST, jamais par grep.

    Par AST parce qu'un grep compterait les mentions en COMMENTAIRE (il y en a : la règle
    `CLAUDE.md` est citée dans plusieurs docstrings, et ce fichier-ci en est plein).

    ⚠ MÉMOÏSÉ : le balayage lit tout l'arbre, et `/mnt/d` depuis WSL2 est lent (le skill
    `/reprise` fait la même remarque pour `check_docs`, qu'il fait lancer depuis Windows).
    Sans le cache, les 3 tests de ce module parcouraient le dépôt 3 fois.
    """
    import os

    racine = _racine()
    trouves = []
    for nom in _RACINES_CODE:
        depart = racine / nom
        if not depart.is_dir():
            continue
        for dossier, sous_dossiers, fichiers in os.walk(depart):
            sous_dossiers[:] = [d for d in sous_dossiers
                                if d not in _DOSSIERS_ELAGUES and not d.startswith('venv')]
            for f in sorted(fichiers):
                if not f.endswith('.py'):
                    continue
                chemin = Path(dossier) / f
                rel = chemin.relative_to(racine).as_posix()
                if any(p in rel for p in _HORS_PERIMETRE) or _SANDBOX.search(rel):
                    continue
                try:
                    arbre = ast.parse(chemin.read_text(encoding='utf-8'))
                except (OSError, SyntaxError, ValueError):
                    continue
                for node in ast.walk(arbre):
                    var = _mutation(node)
                    if var:
                        trouves.append((rel, node.lineno, var))
    return tuple(sorted(trouves))  # immuable : le résultat est mémoïsé et partagé


class RoutageCacheHFTest(unittest.TestCase):

    def test_aucune_nouvelle_mutation_per_modele_de_cache_HF(self):
        """Le budget ne peut que DESCENDRE. Une mutation de plus = un dossier de modèle qui
        se remettra à collecter les sous-dépendances des autres — ou, depuis le 2026-09-07,
        un second exemplaire du JETON hors de son unique domicile."""
        sites = sites_de_mutation()
        if len(sites) <= BUDGET_MUTATIONS:
            return
        nouveaux = '\n'.join(f"    {f}:{l}  {v}" for f, l, v in sites)
        self.fail(
            f"{len(sites)} mutation(s) d'environnement HF (cache OU jeton) pour un budget de "
            f"{BUDGET_MUTATIONS} — une au moins a été AJOUTÉE.\n"
            f"Cible, selon la variable :\n"
            f"  • CACHE → `cache_dir=` explicite + `HF_HOME` posé une fois au démarrage\n"
            f"    (ROADMAP §5b ; `settings.py:165`) ;\n"
            f"  • JETON → un seul domicile, `.env` lu par `settings.py` au démarrage. Ne pas\n"
            f"    en poser un second, ni l'écrire dans le `$HOME` de l'utilisateur.\n"
            f"Dans les deux cas le socle est LE domicile — d'où son exclusion du balayage.\n"
            f"Sites actuels :\n{nouveaux}")

    def test_le_budget_est_a_jour_quand_la_dette_a_baisse(self):
        """Miroir du précédent : quand un backend est porté, le budget DOIT suivre, sinon
        il cesse de protéger (un seuil trop large laisse passer la régression suivante).
        C'est le défaut exact que `/reprise` documente sur ses attendus périmés."""
        sites = sites_de_mutation()
        self.assertGreaterEqual(
            len(sites), BUDGET_MUTATIONS,
            f"La dette est descendue à {len(sites)} : mettre BUDGET_MUTATIONS à cette "
            f"valeur dans le MÊME commit que le portage.")

    def test_importer_un_backend_ne_redirige_PAS_le_cache_du_processus(self):
        """LE défaut à sa source. `wan_video_backend` et `hunyuan_video_backend` posaient
        `HF_HUB_CACHE` **au niveau module** : importer le fichier suffisait à rediriger le
        cache HF de tout le processus, et le DERNIER importé gagnait. C'est la « course » que
        `start_wama_prod.sh:271` invoque pour justifier son `--workers 1`, et c'est ce qui a
        fait échouer `test_le_socle_…` dans la suite du 03/09 (`HF_HUB_CACHE` → `diffusion/wan`).

        On importe les DEUX dans le MÊME sous-processus, l'un après l'autre : si l'un mutait
        encore, il gagnerait — c'est précisément la course qu'on veut voir échouer.

        ⚠ Aucun de ces modules n'importe `torch` au niveau module (vérifié) : ce test ne
        touche pas au GPU. Il est donc jouable même quand toute charge GPU est proscrite —
        ce qui est le cas sur cet hôte (série de crashs, `INFRA_WSL_VS_WINDOWS`).
        """
        import json
        import os
        import subprocess
        import sys

        imports = '\n'.join(f"import {m}" for m in MODULES_SANS_EFFET_DE_BORD)
        code = (
            "import json, os, django\n"
            "django.setup()\n"
            "from django.conf import settings\n"
            "avant = {v: os.environ.get(v) for v in "
            "('HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE')}\n"
            f"{imports}\n"
            "apres = {v: os.environ.get(v) for v in "
            "('HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE')}\n"
            "print(json.dumps({'avant': avant, 'apres': apres,\n"
            "    'attendu': str(settings.MODEL_PATHS['cache']['huggingface'])}))\n"
        )
        env = {k: v for k, v in os.environ.items() if k not in VARS_HF}
        env['DJANGO_SETTINGS_MODULE'] = 'wama.settings'
        essai = subprocess.run([sys.executable, '-c', code], cwd=str(_racine()),
                               env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(essai.returncode, 0,
                         f"l'import des backends a échoué :\n{essai.stderr[-2000:]}")
        vu = json.loads(essai.stdout.strip().splitlines()[-1])
        self.assertEqual(
            vu['apres'], vu['avant'],
            f"un de ces modules a MUTÉ l'environnement à l'import "
            f"({', '.join(MODULES_SANS_EFFET_DE_BORD)}) : avant={vu['avant']} "
            f"après={vu['apres']}. La var d'env est GLOBALE au processus — elle emporte les "
            f"sous-dépendances de TOUS les modèles suivants dans ce dossier.")
        self.assertEqual(vu['apres']['HF_HUB_CACHE'], vu['attendu'],
                         "après import, le cache doit rester le cache PARTAGÉ du socle.")

    def test_le_socle_pose_bien_les_caches_au_demarrage(self):
        """Retirer une mutation per-modèle n'est sûr que si le socle existe. On vérifie le
        FAIT (les variables sont posées au chargement des settings), pas la ligne de code.

        ⚠⚠ DANS UN SOUS-PROCESSUS NEUF, et c'est le défaut lui-même qui l'impose. Première
        version : `os.environ.get(...)` lu dans le process de test. Elle passait en isolé et
        ÉCHOUAIT dans la suite complète (mesuré le 2026-09-03) — parce qu'un test antérieur
        avait fait tourner un `load()` de backend, dont la mutation per-modèle a réécrit la
        variable POUR TOUT LE PROCESS. *La démonstration la plus directe qu'on puisse avoir
        du problème que ce module recense : il a cassé son propre contrôle.*

        Un test du DÉMARRAGE doit donc démarrer. On retire les variables de l'environnement
        de l'enfant — comme le shell réel, qui n'en exporte aucune (ni `.env`, ni
        `start_wama_prod.sh` : vérifié) — pour que le `setdefault` de `settings.py` soit bien
        ce qui les pose.
        """
        import json
        import os
        import subprocess
        import sys

        code = (
            "import json, os, django\n"
            "django.setup()\n"
            "from django.conf import settings\n"
            "print(json.dumps({\n"
            "    'attendu': str(settings.MODEL_PATHS['cache']['huggingface']),\n"
            "    'env': {v: os.environ.get(v) for v in "
            "('HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE')},\n"
            "}))\n"
        )
        env = {k: v for k, v in os.environ.items() if k not in VARS_HF}
        env['DJANGO_SETTINGS_MODULE'] = 'wama.settings'
        essai = subprocess.run([sys.executable, '-c', code], cwd=str(_racine()),
                               env=env, capture_output=True, text=True, timeout=300)
        self.assertEqual(essai.returncode, 0,
                         f"le sous-processus n'a pas démarré :\n{essai.stderr[-2000:]}")
        vu = json.loads(essai.stdout.strip().splitlines()[-1])
        for var, valeur in vu['env'].items():
            self.assertEqual(
                valeur, vu['attendu'],
                f"{var} n'est pas posée sur le cache partagé au démarrage : sans ce socle, "
                f"retirer une mutation per-modèle enverrait les sous-dépendances dans le "
                f"cache par défaut de HuggingFace (hors AI-models/).")


class TroisiemeVoieTest(SimpleTestCase):
    """La brique qui range les poids quand la lib n'accepte pas `cache_dir=`.

    Née le 2026-09-04 : les libs sans `cache_dir=` (kokoro, higgs, le worker du PoC)
    n'avaient d'autre routage que la mutation d'environnement — celle-là même qui emporte les
    sous-dépendances. `poids_locaux` télécharge DANS le dossier de famille et rend un chemin.

    ⚠ **Le dossier de famille est un DOSSIER JETABLE, jamais un littéral** (corrigé 2026-09-05).
    Ces trois tests passaient `'/dossier'` en dur, et `poids_locaux` en fait un
    `mkdir(parents=True)` — donc ils étaient VERTS SOUS WINDOWS EN CRÉANT `D:\dossier\famille`
    sur le disque réel (mesuré : le dossier y était), et ROUGES SOUS LINUX où `/dossier` est
    la racine système (`PermissionError`). Ils n'ont jamais pu passer sous WSL2 depuis leur
    création (`6595ba6e`) : le chantier les avait validés depuis venv_win seul.
    Même famille que le `MEDIA_ROOT` réel soldé le 25/08 — **un test qui écrit hors de son
    dossier jetable ment sur au moins une plateforme.**
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory(prefix='wama_hfw_')
        self.famille = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_elle_ne_touche_JAMAIS_l_environnement(self):
        """Le point entier de la brique. Si elle mutait, elle ne vaudrait pas mieux que ce
        qu'elle remplace."""
        import os
        from unittest.mock import patch

        from wama.common.utils.hf_weights import poids_locaux
        avant = {k: os.environ.get(k) for k in VARS_HF}
        with patch('huggingface_hub.snapshot_download', return_value='/chemin/simule') as faux:
            poids_locaux('org/modele', self.famille)
        self.assertEqual({k: os.environ.get(k) for k in VARS_HF}, avant)
        self.assertEqual(faux.call_args.kwargs.get('cache_dir'), self.famille,
                         'le dossier de famille passe par cache_dir=, jamais par l’env')

    def test_elle_tente_le_HORS_LIGNE_avant_le_reseau(self):
        """Sans ça, un modèle DÉJÀ présent ferait un aller-retour HTTP à chaque chargement —
        et un incident réseau ferait échouer un chargement qui n'avait besoin de rien."""
        from unittest.mock import patch

        from wama.common.utils.hf_weights import poids_locaux
        with patch('huggingface_hub.snapshot_download') as faux:
            faux.side_effect = ['/local']
            poids_locaux('org/modele', self.famille)
        self.assertTrue(faux.call_args_list[0].kwargs.get('local_files_only'),
                        'le premier essai doit être purement local')

    def test_le_reseau_prend_le_relais_si_les_poids_manquent(self):
        from unittest.mock import patch

        from wama.common.utils.hf_weights import poids_locaux
        with patch('huggingface_hub.snapshot_download') as faux:
            faux.side_effect = [OSError('absent'), '/telecharge']
            chemin = poids_locaux('org/modele', self.famille)
        self.assertEqual(chemin, '/telecharge')
        self.assertEqual(len(faux.call_args_list), 2)


class BasculeDEnvironnementResteUnDERNIERRECOURSTest(SimpleTestCase):
    """`hf_cache_scope` n'est ni morte ni libre : c'est un DERNIER RECOURS, qui se DÉCLARE.

    ⚠ CORRECTION (2026-09-06, recadrage Fabien). La 1ʳᵉ version de cette garde exigeait ZÉRO
    consommateur — elle INTERDISAIT le dernier recours au lieu de le gouverner. C'était faux :
    la brique existe pour la classe de libs qui n'offre AUCUN levier, et une telle lib peut
    arriver demain. *Une garde qui interdit une exception légitime pousse le suivant à la
    contourner en silence — ce qui est exactement le contraire du but.*

    LA RÈGLE (ROADMAP §5b, doctrine du dépôt) : le modèle PRINCIPAL va dans son dossier
    catégorisé, ses SOUS-DÉPENDANCES HF vont au cache partagé. Quatre leviers permettent de la
    tenir, dans cet ordre de préférence — le choix n'est pas un goût, il est imposé par la lib :

      A. `cache_dir=` sur `from_pretrained()`               majorité (transformers, diffusers…)
      B. un CHEMIN local (3ᵉ voie, `hf_weights.poids_locaux`)  sam3, kokoro
      C. la variable propre à LA lib, posée dans `settings.py`  DEEPFACE_HOME, AUDIOCRAFT_CACHE_DIR
      D. `hf_cache_scope` — la lib n'offre AUCUN levier          ← dernier recours

    Le coût de D, qui justifie son rang : la bascule restaure l'environnement, **jamais les
    fichiers**. Tout ce que la lib télécharge pendant la fenêtre — sous-dépendances comprises —
    reste dans le dossier du modèle. C'est le mécanisme exact qui a déposé `timm/resnet18` dans
    le dossier de table-transformer. D est donc licite, mais jamais par confort.
    """

    #: {module: raison} — les emplois ASSUMÉS de la bascule. VIDE aujourd'hui : les deux
    #: adopteurs historiques (kokoro le 2026-08-12, sam3 le 2026-09-06) acceptaient en réalité
    #: un chemin, donc relèvent de B. Inscrire une entrée ici est une DÉCISION : elle veut dire
    #: « cette lib n'offre ni A, ni B, ni C — vérifié dans sa signature ».
    RECOURS_ASSUMES = {}

    def test_tout_emploi_de_la_bascule_est_un_recours_ASSUME(self):
        racine = Path(settings.BASE_DIR)
        emplois = []
        for dossier in ('wama', 'wama_lab'):
            for f in (racine / dossier).rglob('*.py'):
                if 'venv' in f.parts or 'site-packages' in f.parts:
                    continue
                if f.name in ('hf_cache.py', 'tests_hf_cache_routing.py'):
                    continue        # le module lui-même et sa garde citent forcément le nom
                try:
                    arbre = ast.parse(f.read_text(encoding='utf-8'))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                # AST, jamais grep : trois motifs textuels se sont trompés de cible cette
                # session en accusant des COMMENTAIRES. Seul un import réel compte.
                for n in ast.walk(arbre):
                    if ((isinstance(n, ast.ImportFrom) and 'hf_cache' in (n.module or ''))
                            or (isinstance(n, ast.Import)
                                and any('hf_cache' in a.name for a in n.names))):
                        emplois.append(str(f.relative_to(racine)).replace(chr(92), '/'))
        surprise = sorted(set(emplois) - set(self.RECOURS_ASSUMES))
        self.assertEqual(surprise, [],
                         "emploi NON assumé de `hf_cache_scope`. Vérifier d'abord A/B/C dans la "
                         "signature de la lib (la contrainte de sam3 était une croyance : elle "
                         "acceptait `checkpoint_path=`). Si aucun levier n'existe, inscrire le "
                         "module dans RECOURS_ASSUMES avec sa raison — c'est le geste qui "
                         "transforme un contournement en décision.")

    def test_la_brique_reste_DISPONIBLE_et_correcte(self):
        """Elle n'est pas dépréciée : on vérifie qu'elle restaure bien TOUT, absence comprise.

        Sans cette moitié, la garde ci-dessus laisserait pourrir un dernier recours dont
        personne ne vérifie plus qu'il marche — et on le découvrirait le jour où on en a besoin.
        """
        import os
        from wama.common.utils.hf_cache import hf_cache_scope
        avant = {k: os.environ.get(k) for k in ('HF_HOME', 'HF_HUB_CACHE',
                                                'HUGGINGFACE_HUB_CACHE')}
        temoin = os.environ.pop('WAMA_TEMOIN_ABSENT', None)   # une clé ABSENTE au départ
        with hf_cache_scope('/tmp/wama-temoin-scope'):
            self.assertEqual(os.environ['HF_HUB_CACHE'], '/tmp/wama-temoin-scope')
            import huggingface_hub.constants as c
            self.assertEqual(c.HF_HUB_CACHE, '/tmp/wama-temoin-scope',
                             "les CONSTANTES doivent basculer aussi : le hub les fige à "
                             "l'import, muter l'env seul ne suffit pas dans un worker")
        for k, v in avant.items():
            self.assertEqual(os.environ.get(k), v, f"{k} non restauré")
        if temoin is not None:
            os.environ['WAMA_TEMOIN_ABSENT'] = temoin
