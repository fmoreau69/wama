"""Le MOTEUR d'un modèle prospecté se DÉRIVE de son snapshot — et ne dégrade jamais une déclaration.

POURQUOI (2026-09-07, question de Fabien : « les modèles étant censés connaître leur backend,
pourquoi ce n'est pas fait automatiquement ? »). Le lien modèle↔backend était automatique côté
CONSOMMATION (`backend_for_model`) mais rien ne le posait côté PRODUCTION : un modèle déclaré par
une app reçoit son moteur de son `model_config` ; un modèle arrivé par PROSPECTION n'en recevait
aucun. Mesuré ce jour-là : 8 modèles sans moteur, donc irrésolubles — dont les deux
`table-transformer`, qui ont pourtant un backend écrit pour eux.

La matière est sur le disque (convention HuggingFace) : `model_index.json` → diffusers,
`config.json` → transformers. C'est la méthode employée partout ailleurs dans WAMA : CONSTATER,
ne pas deviner.

⚠⚠ CE QUE CES TESTS PROTÈGENT SURTOUT — la mise en garde de Fabien, « attention à ne pas créer
deux chemins parallèles et conflictuels » : la signature du disque est GROSSIÈRE (`transformers`)
là où le catalogue sait `transformers-remote-code`, `qwen3-tts` ou `kokoro-onnx`. Comme
`model_sync` écrit toute composition non vide, une dérivation non gardée DÉGRADAIT ces trois
modèles à chaque synchro. La règle tenue ici : **une dérivation ne comble qu'un vide RÉEL ; elle
n'écrase jamais une déclaration.**
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase

from wama.model_manager.services.model_registry import ModelInfo, ModelRegistry, ModelSource, ModelType


def _snapshot(racine: Path, fichier: str, contenu: dict) -> Path:
    """Fabrique un dépôt HF minimal `<racine>/snapshots/<rev>/<fichier>`."""
    rev = racine / 'snapshots' / 'abc123'
    rev.mkdir(parents=True, exist_ok=True)
    (rev / fichier).write_text(json.dumps(contenu), encoding='utf-8')
    return racine


class DerivationDuMoteurTest(TestCase):

    def _registre(self, cle: str, chemin: Path, composition=None) -> ModelRegistry:
        r = ModelRegistry()
        r._models = {cle: ModelInfo(
            id=cle, name=cle, model_type=ModelType.VISION, source=ModelSource.HUGGINGFACE,
            composition=composition or {}, extra_info={'path': str(chemin)})}
        return r

    def test_model_index_json_donne_diffusers_et_consigne_la_classe(self):
        with TemporaryDirectory() as d:
            p = _snapshot(Path(d) / 'models--x--y', 'model_index.json',
                          {'_class_name': 'WanDMDPipeline'})
            r = self._registre('huggingface:x/y', p)
            r._overlay_engines_derived_from_disk()
            info = r._models['huggingface:x/y']
            self.assertEqual(info.composition['runtime']['engine'], 'diffusers')
            self.assertEqual(info.extra_info['pipeline_class'], 'WanDMDPipeline')

    def test_config_json_donne_transformers_et_consigne_l_architecture(self):
        with TemporaryDirectory() as d:
            p = _snapshot(Path(d) / 'models--m--t', 'config.json',
                          {'architectures': ['TableTransformerForObjectDetection']})
            r = self._registre('huggingface:m/t', p)
            r._overlay_engines_derived_from_disk()
            info = r._models['huggingface:m/t']
            self.assertEqual(info.composition['runtime']['engine'], 'transformers')
            self.assertEqual(info.extra_info['pipeline_class'],
                             'TableTransformerForObjectDetection')

    def test_une_composition_deja_posee_par_la_decouverte_est_INTOUCHEE(self):
        with TemporaryDirectory() as d:
            p = _snapshot(Path(d) / 'models--a--b', 'config.json', {'architectures': ['X']})
            r = self._registre('huggingface:a/b', p,
                               composition={'runtime': {'engine': 'qwen3-tts'}})
            r._overlay_engines_derived_from_disk()
            self.assertEqual(r._models['huggingface:a/b'].composition['runtime']['engine'],
                             'qwen3-tts')
            self.assertNotIn('pipeline_class', r._models['huggingface:a/b'].extra_info)

    def test_un_moteur_DECLARE_AU_CATALOGUE_n_est_jamais_degrade(self):
        """LE cas que la mise en garde de Fabien a fait écrire.

        Le catalogue sait `kokoro-onnx` ; le disque ne sait dire que `transformers`. La
        découverte doit se TAIRE (composition vide) — `model_sync` n'écrase alors rien.
        """
        from wama.model_manager.models import AIModel
        AIModel.objects.create(
            model_key='huggingface:o/k', name='k', model_type='speech', source='huggingface',
            composition={'runtime': {'engine': 'kokoro-onnx'}})
        with TemporaryDirectory() as d:
            p = _snapshot(Path(d) / 'models--o--k', 'config.json',
                          {'model_type': 'style_text_to_speech_2'})
            r = self._registre('huggingface:o/k', p)
            r._overlay_engines_derived_from_disk()
            self.assertEqual(r._models['huggingface:o/k'].composition, {},
                             "la découverte doit se taire, pas proposer un moteur plus grossier")

    def test_sans_signature_on_ne_conclut_pas(self):
        with TemporaryDirectory() as d:
            vide = Path(d) / 'models--v--v'
            (vide / 'snapshots' / 'r1').mkdir(parents=True)
            r = self._registre('huggingface:v/v', vide)
            r._overlay_engines_derived_from_disk()
            self.assertEqual(r._models['huggingface:v/v'].composition, {})

    def test_un_chemin_absent_ne_leve_pas(self):
        r = self._registre('huggingface:z/z', Path('/chemin/qui/n/existe/pas'))
        r._overlay_engines_derived_from_disk()          # ne doit pas lever
        self.assertEqual(r._models['huggingface:z/z'].composition, {})


class DepartageDuMoteurPartageTest(TestCase):
    """Dériver le moteur ne suffit pas quand il est PARTAGÉ : il faut le lien fin.

    `transformers` est piloté par 5 backends. Sans `SUPPORTED_MODELS` qui nomme le modèle, la
    résolution rend `None` — c'est voulu (« rendre un backend au hasard est pire que ne rien
    rendre »). Les deux `table-transformer` sont déclarés dans leur backend depuis le 07/09.
    """

    def test_les_deux_table_transformer_resolvent_leur_backend(self):
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_for_model
        for hf in ('microsoft/table-transformer-detection',
                   'microsoft/table-transformer-structure-recognition'):
            m = SimpleNamespace(model_key=f'huggingface:{hf}',
                                composition={'runtime': {'engine': 'transformers'}})
            classe = backend_for_model(m)
            self.assertIsNotNone(classe, f'{hf} ne résout aucun backend')
            self.assertEqual(classe.__name__, 'TableTransformerBackend')

    def test_un_modele_transformers_que_personne_ne_declare_ne_resout_rien(self):
        """Contre-épreuve : le moteur seul ne tranche pas entre 5 backends."""
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_for_model
        m = SimpleNamespace(model_key='huggingface:nvidia/canary-1b-v2',
                            composition={'runtime': {'engine': 'transformers'}})
        self.assertIsNone(backend_for_model(m))
