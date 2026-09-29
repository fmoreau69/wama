"""Tests de `check_model_layout` — « un dossier de modèle ne contient que SON modèle ».

Ce que ces tests protègent : le contrôle est le seul instrument capable de voir le défaut
`HF_HUB_CACHE` **sans GPU et sans test par backend** — et c'est ce qui le rend indispensable,
puisque AUCUN des 18 backends qui mutent l'environnement n'a de test de chargement sur poids
réels (mesuré le 2026-09-03). S'il devient faux, plus rien ne voit la pollution.

Les arbres sont FABRIQUÉS : on ne teste jamais contre `AI-models/` réel — son contenu change
avec chaque installation, et un test qui dépend de l'état du disque de la machine ne dit rien.
"""

import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings


def _arbre(racine, categorie, famille, snapshots):
    """Fabrique `<racine>/models/<categorie>/<famille>/models--…` (dossiers vides suffisent :
    le contrôle regarde les NOMS, jamais le contenu)."""
    base = Path(racine) / 'models' / categorie / famille
    for nom in snapshots:
        (base / nom).mkdir(parents=True, exist_ok=True)
    return base


def _analyse(racine):
    from wama.model_manager.management.commands.check_model_layout import analyser
    with override_settings(AI_MODELS_DIR=str(racine)):
        return analyser()


class LayoutTest(TestCase):

    def test_un_snapshot_qui_ne_porte_pas_le_nom_de_la_famille_est_ETRANGER(self):
        """La signature exacte du défaut : le backbone timm déposé dans le dossier de
        table-transformer parce que le backend mutait `HF_HUB_CACHE`."""
        with tempfile.TemporaryDirectory() as tmp:
            _arbre(tmp, 'vision', 'table-transformer-detection', [
                'models--microsoft--table-transformer-detection',
                'models--timm--resnet18.a1_in1k',
            ])
            resultats = _analyse(tmp)
        self.assertEqual(len(resultats), 1)
        _, _, _, etrangers = resultats[0]
        self.assertEqual(etrangers, ['models--timm--resnet18.a1_in1k'])

    def test_un_composant_DECLARE_n_est_pas_un_etranger(self):
        """Un modèle réellement fait de plusieurs dépôts (pipeline pyannote) ne doit pas
        déclencher le contrôle — sinon il crie au loup, et un contrôle qui crie au loup
        finit par être ignoré, donc par ne plus rien protéger.

        ⚠ Recalé le 2026-09-04 : la déclaration ne vit plus dans une table du SUBSTRAT mais
        dans le manifeste du modèle (`composition.components[*].repo`). Le test pose donc la
        déclaration au lieu de s'appuyer sur des noms écrits en dur — c'est la DÉCLARATION
        qu'on vérifie, pas l'endroit où quelqu'un l'a recopiée."""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            _arbre(tmp, 'speech', 'diarization', [
                'models--pyannote--speaker-diarization-3.1',
                'models--pyannote--segmentation-3.0',
            ])
            with patch('wama.common.utils.model_locations.composants_declares',
                       return_value=['models--pyannote--segmentation-3.0']):
                resultats = _analyse(tmp)
        self.assertEqual(len(resultats), 1)
        self.assertEqual(resultats[0][3], [],
                         "un composant DÉCLARÉ ne doit pas être compté étranger")

    def test_la_declaration_est_DERIVEE_du_catalogue_jamais_ecrite_dans_le_substrat(self):
        """La source de la déclaration : `AIModel.composition['components'][*]['repo']`.

        Sans déclaration, la fonction rend une liste VIDE — donc le détecteur SIGNALE au lieu
        de masquer (« mieux vaut des cas à qualifier qu'une table inventée qui en masque »).
        """
        from wama.common.utils import model_locations as ml
        from wama.model_manager.models import AIModel

        self.assertEqual(ml.composants_declares('speech', 'diarization'), [],
                         'rien de déclaré → rien de masqué')
        AIModel.objects.create(
            model_key='temoin:diariseur', name='Témoin diariseur', source='transcriber',
            local_path='/x/AI-models/models/speech/diarization/models--temoin--diariseur',
            composition={'components': [{'role': 'segmentation',
                                         'repo': 'pyannote/segmentation-3.0'}]})
        self.assertEqual(ml.composants_declares('speech', 'diarization'),
                         ['models--pyannote--segmentation-3.0'])
        self.assertEqual(ml.composants_declares('speech', 'higgs'), [],
                         'la déclaration ne vaut que pour le dossier du modèle qui la porte')

    def test_un_composant_NON_declare_du_meme_editeur_reste_etranger(self):
        """Contre-épreuve du test précédent : c'est la DÉCLARATION qui absout, pas le nom de
        l'éditeur. Sans elle, n'importe quel dépôt pyannote passerait — et le défaut avec."""
        with tempfile.TemporaryDirectory() as tmp:
            _arbre(tmp, 'speech', 'diarization', [
                'models--pyannote--speaker-diarization-3.1',
                'models--pyannote--un-depot-jamais-declare',
            ])
            resultats = _analyse(tmp)
        self.assertEqual(resultats[0][3], ['models--pyannote--un-depot-jamais-declare'])

    def test_un_dossier_a_un_seul_snapshot_n_est_jamais_signale(self):
        """Le cas NORMAL, et de loin le plus fréquent : rien à dire."""
        with tempfile.TemporaryDirectory() as tmp:
            _arbre(tmp, 'vision', 'sam', ['models--facebook--sam3'])
            self.assertEqual(_analyse(tmp), [])

    def test_deux_variantes_de_la_MEME_famille_ne_sont_pas_etrangeres(self):
        """`speech/whisper` porte légitimement `faster-whisper-tiny` ET `-large-v3` : deux
        tailles d'un même modèle. Les signaler serait un faux positif sur un cas courant."""
        with tempfile.TemporaryDirectory() as tmp:
            _arbre(tmp, 'speech', 'whisper', [
                'models--Systran--faster-whisper-tiny',
                'models--Systran--faster-whisper-large-v3',
            ])
            self.assertEqual(_analyse(tmp)[0][3], [])

    def test_par_defaut_le_controle_NE_GARDE_PAS_mais_strict_sort_en_1(self):
        """Décision explicite : les étrangers présents sont un état HÉRITÉ. Bloquer chaque
        commande forcerait un nettoyage à l'aveugle — or supprimer une copie peut casser un
        chargement tant que le backend qui l'a déposée n'est pas porté. `--strict` reste
        disponible pour la CI, une fois le parc assaini."""
        with tempfile.TemporaryDirectory() as tmp:
            _arbre(tmp, 'music', 'musicgen', [
                'models--facebook--musicgen-small', 'models--t5-base',
            ])
            with override_settings(AI_MODELS_DIR=str(tmp)):
                call_command('check_model_layout', stdout=StringIO())   # ne lève pas
                with self.assertRaises(SystemExit) as ctx:
                    call_command('check_model_layout', '--strict',
                                 stdout=StringIO(), stderr=StringIO())
        self.assertEqual(ctx.exception.code, 1)

    def test_les_verrous_orphelins_tracent_une_contamination_PASSEE(self):
        """`.locks` sans snapshot = un modèle téléchargé là puis nettoyé. C'est la preuve
        que NETTOYER NE SUFFIT PAS (11 de ces traces dans `speech/kokoro` au 03/09, alors que
        le dossier est propre aujourd'hui) — donc que le correctif doit viser la CAUSE."""
        from wama.model_manager.management.commands.check_model_layout import verrous_orphelins
        with tempfile.TemporaryDirectory() as tmp:
            base = _arbre(tmp, 'speech', 'kokoro', ['models--hexgrad--Kokoro-82M'])
            (base / '.locks' / 'models--t5-large').mkdir(parents=True)
            with override_settings(AI_MODELS_DIR=str(tmp)):
                traces = verrous_orphelins()
        self.assertEqual([(c, f, n) for c, f, n in traces],
                         [('speech', 'kokoro', ['models--t5-large'])])


class ArithmetiqueDUnCacheHFTest(TestCase):
    """Mesurer la taille d'un dossier de cache HF — le piège des LIENS.

    Dans un cache HF, chaque poids existe DEUX fois : une fois réellement dans `blobs/`, une
    fois comme lien symbolique dans `snapshots/`. Un `rglob('*') + is_file()` suit les liens
    et compte donc tout en double. Mesuré le 2026-09-04 en commettant l'erreur : le nettoyage
    des résidus annonçait 6 Go récupérés là où le disque en rendait 2,9.
    """

    def _cache(self, racine, octets=1024):
        """Un dossier HF minimal : un blob réel + son lien dans le snapshot."""
        import os
        base = Path(racine) / 'models--org--modele'
        (base / 'blobs').mkdir(parents=True)
        (base / 'snapshots' / 'abc').mkdir(parents=True)
        blob = base / 'blobs' / 'deadbeef'
        blob.write_bytes(b'x' * octets)
        try:
            os.symlink('../../blobs/deadbeef', base / 'snapshots' / 'abc' / 'model.bin')
        except (OSError, NotImplementedError):
            self.skipTest('liens symboliques non autorisés sur cette plateforme')
        return base, octets

    def test_le_calcul_de_l_installeur_ne_compte_PAS_le_lien(self):
        from wama.model_manager.services import model_installer as mi
        import inspect
        source = inspect.getsource(mi)
        self.assertIn('not f.is_symlink()', source,
                      "l'espace libéré doit exclure les liens, sinon il annonce le double")

    def test_un_rglob_naif_compte_bien_en_DOUBLE(self):
        """Contre-épreuve : la garde n'est pas décorative, l'erreur est réelle."""
        with tempfile.TemporaryDirectory() as tmp:
            base, octets = self._cache(tmp)
            naif = sum(f.stat().st_size for f in base.rglob('*') if f.is_file())
            juste = sum(f.stat().st_size for f in base.rglob('*')
                        if f.is_file() and not f.is_symlink())
        self.assertEqual(juste, octets)
        self.assertEqual(naif, 2 * octets, 'le lien double bien la mesure')
