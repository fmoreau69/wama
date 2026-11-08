"""
Un modèle installé dit QUI l'exécute — backend, ou module qui le charge lui-même (2026-10-31).

L'INVENTAIRE QUI A DÉCIDÉ CE MÉCANISME (142 modèles installés et locaux, catalogue réel) : 10
lignes « condamnées » par `backend_missing`, dont SIX servaient pourtant :
  • cinq sont chargées HORS de tout backend, et chaque découverte le disait en commentaire seulement
    (le banc, le service vocal, le Face Analyzer, le Cam Analyzer, le navigateur) →
    `composition.runtime.loaded_by`, le module qui ouvre le fichier ;
  • une a bien un backend (`PyannoteDiarizerBackend`), qui la nomme par sa clé de catalogue dans
    son `SUPPORTED_MODELS` — mais la ligne, arrivée par la prospection, n'avait pas de moteur →
    la découverte lit cette moitié du lien (`_overlay_engines_named_by_backends`).
Le champ `not_runnable` des outils de l'assistant reprend ce verdict : sans ces déclarations, il
aurait dit pyannote ou Smart Turn « inutilisables ».
"""
import importlib.util

from django.test import TestCase

from wama.model_manager.services.model_registry import ModelInfo, ModelRegistry, ModelSource, ModelType

PYANNOTE = 'huggingface:pyannote/speaker-diarization-community-1'


def _registry():
    """Un registre nu (le vrai est un singleton qui balaierait tout le disque)."""
    r = object.__new__(ModelRegistry)
    r._models, r.discovery_errors = {}, []
    return r


def _line(key, composition=None):
    return ModelInfo(id=key, name=key, model_type=ModelType.VISION, source=ModelSource.HUGGINGFACE,
                     composition=composition or {})


class LoadedByTest(TestCase):

    DISCOVERIES = ('_discover_face_analyzer_models', '_discover_road_models',
                   '_discover_quality_metric_models', '_discover_hand_gesture_models',
                   '_discover_turn_end_models', '_discover_language_identification_models',
                   '_discover_page_orientation_models')

    #: La librairie que le moteur déclaré de chaque ligne fait requérir à son manifeste
    #: (2026-11-06). Une ligne SANS moteur y figure avec sa raison : rien d'autre ne l'excuse.
    EXPECTED_LIBRARIES = {
        'face_analyzer:mediapipe-face-landmarker': ['mediapipe'],
        'github:CAIC-AD/YOLOPv2:V0.0.1': ['opencv-python', 'torch', 'torchvision'],
    }
    #: Exécuté par la version NAVIGATEUR de MediaPipe : aucune librairie Python à requérir.
    WITHOUT_ENGINE = {'mediapipe_models:gesture-recognizer'}

    def _declared(self):
        r = _registry()
        for name in self.DISCOVERIES:
            getattr(r, name)()
        self.assertEqual([], r.discovery_errors)
        return {key: (info.composition or {}).get('runtime', {})
                for key, info in r._models.items()
                if (info.composition or {}).get('runtime', {}).get('loaded_by')}

    def test_each_brick_model_names_a_module_that_exists(self):
        declared = self._declared()
        # 3 depuis le 2026-11-08 : Whisper tiny, l'orientation de page, LPIPS et Smart Turn sont
        # servis par leur backend (`WhisperLanguageBackend`, `DocTROrientationBackend`,
        # `LPIPSBackend`, `SmartTurnBackend`) ; leurs découvertes restent ici, et n'émettent plus
        # de `loaded_by`.
        self.assertEqual(3, len(declared), declared)
        for key, runtime in declared.items():
            with self.subTest(model=key):
                self.assertIsNotNone(importlib.util.find_spec(runtime['loaded_by']),
                                     f"{runtime['loaded_by']} introuvable")

    def test_each_loader_names_the_engine_its_manifest_requires(self):
        """Le modèle porte son moteur, et un moteur est une librairie (registre `backends`) :
        sans lui, le manifeste de Whisper tiny disait `requires: []` alors que la sonde des
        langues tourne sur faster-whisper — la désinstaller n'aurait rien refusé."""
        from wama.common.manifests.builtin.model import _requires_librairies
        declared = self._declared()
        self.assertEqual(set(self.EXPECTED_LIBRARIES) | self.WITHOUT_ENGINE, set(declared))
        for key, runtime in declared.items():
            with self.subTest(model=key):
                required = [r['key'] for r in
                            _requires_librairies({'composition': {'runtime': runtime}}, key)]
                if key in self.WITHOUT_ENGINE:
                    self.assertNotIn('engine', runtime)
                    self.assertEqual([], required)
                else:
                    self.assertEqual(self.EXPECTED_LIBRARIES[key], required)

    def test_a_loader_is_never_handed_to_the_backend_of_its_engine(self):
        """Whisper tiny déclare `faster-whisper`, le moteur que pilote le backend Whisper : son
        exécutant reste la brique (`loaded_by`), jamais le backend — la même règle que
        `backend_missing`."""
        from wama.common.backends.manager import backend_for_model
        from wama.common.backends.whisper_backend import WhisperBackend
        runtime = {'engine': 'faster-whisper', 'loaded_by': 'wama.common.utils.spoken_language'}
        self.assertIsNone(backend_for_model(_line('huggingface:Systran/faster-whisper-tiny',
                                                  {'runtime': runtime})))
        # Contre-épreuve : une ligne sans `loaded_by` que le backend liste va au backend du moteur
        # (porteur à `model_key`, le champ que lit la porte : le moteur est partagé, la liste
        # départage — règle 2 de `resolve_entry`).
        from types import SimpleNamespace
        self.assertIs(WhisperBackend, backend_for_model(SimpleNamespace(
            model_key='transcriber:whisper', capabilities={},
            composition={'runtime': {'engine': 'faster-whisper'}})))

    def test_the_backend_inventory_reads_the_same_rule(self):
        """`app_backend_entries` est la lecture SANS import de `backend_for_model` : une ligne
        `loaded_by` n'y fait pas apparaître le backend de son moteur. Contre-épreuve : la même
        ligne sans `loaded_by`, sous une autre source, l'y fait apparaître."""
        from wama.common.services.backend_inventory import app_backend_entries
        from wama.model_manager.models import AIModel
        for source, runtime in (('loaderprobe', {'engine': 'faster-whisper',
                                                 'loaded_by': 'wama.common.utils.spoken_language'}),
                                ('backendprobe', {'engine': 'faster-whisper'})):
            # `whisper` : l'identifiant que `WhisperBackend` liste — `faster-whisper` est partagé
            # (règle 2 de `resolve_entry`).
            AIModel.objects.create(model_key=f'{source}:whisper', name='whisper',
                                   model_type='speech', source=source,
                                   composition={'runtime': runtime})
        self.assertEqual([], app_backend_entries('loaderprobe'))
        self.assertEqual(['wama.common.backends.whisper_backend'],
                         [e.module for e in app_backend_entries('backendprobe')])

    def _row(self, key, runtime, source='mediapipe_models'):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(model_key=key, name=key, model_type='vision', source=source,
                                      is_downloaded=True, composition={'runtime': runtime})

    def test_the_assistant_does_not_send_a_loader_to_write_a_manifest(self):
        """Le reconnaisseur de gestes n'a délibérément aucun moteur Python : l'outil de
        l'assistant disait « aucun moteur DÉCLARÉ » et proposait d'écrire son manifeste.
        Contre-épreuve : la même ligne sans `loaded_by` reçoit ce conseil."""
        from wama.tool_api import plan_model_integration
        self._row('mediapipe_models:loader', {'loaded_by': 'wama.common.scene_views'})
        self._row('mediapipe_models:bare', {})
        plan = plan_model_integration(None, 'mediapipe_models:loader')
        self.assertEqual('wama.common.scene_views', plan['state']['loaded_by'])
        self.assertIn('chargé par wama.common.scene_views', plan['next_step'])
        self.assertIsNone(plan['human_gesture'])
        self.assertIn('aucun moteur', plan_model_integration(None, 'mediapipe_models:bare')['next_step'])

    def test_a_missing_library_of_a_loader_gets_the_library_gesture(self):
        """Sans backend, « installer les paquets du backend » n'a pas de sens : le geste est celui
        de la librairie (`plan_library_integration`)."""
        from unittest import mock
        from wama.tool_api import plan_model_integration
        self._row('pytorch_download:loader', {'engine': 'lpips',
                                              'loaded_by': 'wama.model_manager.services.bench'},
                  source='pytorch_download')
        absent = {'dist': 'lpips', 'seeded_in_corpus': True, 'installed_version': None,
                  'in_registry': True}
        with mock.patch('wama.tool_api._etat_librairie', lambda dist: dict(absent, dist=dist)):
            plan = plan_model_integration(None, 'pytorch_download:loader')
        self.assertIn('runtime absent : lpips', plan['next_step'])
        self.assertEqual('manage.py install_library lpips --allow --apply', plan['human_gesture'])

    def test_an_engine_without_backend_is_sent_to_the_backend_role(self):
        """2026-11-07 (ACE-Step) : le geste disait « écrire le backend » — l'assistant aurait écrit
        à la main ce que le rôle `backend` écrit et propose à la validation."""
        from wama.tool_api import plan_model_integration
        self._row('unservedprobe:m', {'engine': 'unserved_probe_engine'}, source='unservedprobe')
        gesture = plan_model_integration(None, 'unservedprobe:m')['human_gesture']
        self.assertIn('rôle `backend`', gesture)
        self.assertIn('--catalog unservedprobe:m', gesture)

    def test_a_waiting_proposal_is_the_next_step_on_the_route(self):
        """2026-11-07 (ACE-Step) : le plan ignorait la file — il renvoyait au rôle déjà joué, sans
        dire que « Valider » refuserait sa proposition. Refusée : relancer le rôle ; acceptable :
        la décision d'un administrateur ; un backend proposé attend de même."""
        from unittest import mock
        from wama.tool_api import plan_model_integration
        self._row('unservedprobe:w', {}, source='unservedprobe')
        refused = {'manifest': {'refused': ['anatomie incomplète : 1 poids (te/model.safetensors)']}}
        with mock.patch('wama.tool_api._awaiting_decision', return_value=refused):
            plan = plan_model_integration(None, 'unservedprobe:w')
        self.assertIn('REFUSERAIT : anatomie incomplète', plan['next_step'])
        self.assertIn('relancer le rôle `model`', plan['human_gesture'])
        with mock.patch('wama.tool_api._awaiting_decision', return_value={'manifest': {'refused': []}}):
            self.assertIn('administrateur', plan_model_integration(None, 'unservedprobe:w')['human_gesture'])
        self._row('unservedprobe:b', {'engine': 'unserved_probe_engine'}, source='unservedprobe')
        with mock.patch('wama.tool_api._awaiting_decision', return_value={'backend': {'backend_x.json': []}}):
            plan = plan_model_integration(None, 'unservedprobe:b')
        self.assertIn('backend_x.json', plan['next_step'])
        self.assertIn('administrateur', plan['human_gesture'])
        # Un backend que « Valider » refuserait (2026-11-08, ACE-Step) : relancer le rôle.
        with mock.patch('wama.tool_api._awaiting_decision',
                        return_value={'backend': {'backend_x.json': ['SUPPORTED_MODELS absent']}}):
            plan = plan_model_integration(None, 'unservedprobe:b')
        self.assertIn('REFUSERAIT : SUPPORTED_MODELS absent', plan['next_step'])
        self.assertIn('relancer le rôle `backend`', plan['human_gesture'])

    def test_the_route_reads_the_queue_itself(self):
        """La lecture de la file, sans doublure : une proposition refusée du magasin y est vue."""
        from unittest import mock
        from wama.common.manifests import proposals
        from wama.common.manifests.builtin.model import extract_model
        from wama.tool_api import _awaiting_decision
        self._row('huggingface:Probe/q', {}, source='huggingface')
        manifest = extract_model('huggingface:Probe/q')
        manifest['body']['composition'] = {'components': [{'role': 'm', 'pattern': 'a.safetensors'}],
                                           'runtime': {'engine': 'transformers'}}
        proposals.propose(manifest)
        with mock.patch('wama.model_manager.services.model_installer.anatomy_inventory',
                        return_value=[('a.safetensors', 1), ('te/b.safetensors', 1)]):
            waiting = _awaiting_decision('huggingface:Probe/q')
        self.assertEqual(1, len(waiting['manifest']['refused']), waiting)
        self.assertIn('te/b.safetensors', waiting['manifest']['refused'][0])
        self.assertEqual({}, _awaiting_decision('unservedprobe:w-none'))

    def test_a_model_loaded_by_a_module_is_not_condemned(self):
        from wama.common.backends.manager import backend_missing
        line = _line('pytorch_download:lpips-alexnet',
                     {'runtime': {'loaded_by': 'wama.model_manager.services.bench'}})
        self.assertIsNone(backend_missing(line))
        # Contre-épreuve : la même ligne sans sa déclaration n'a aucune route.
        self.assertIsNotNone(backend_missing(_line('pytorch_download:lpips-alexnet')))

    def test_the_disk_does_not_give_an_engine_to_a_declared_loader(self):
        """Un snapshot diffusers sur le disque : sans `loaded_by`, la passe en dériverait le moteur
        (contre-épreuve sur la ligne voisine, identique mais sans déclaration)."""
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'model_index.json').write_text(json.dumps({'_class_name': 'X'}))
            r = _registry()
            for key, runtime in (('huggingface:o/declared', {'loaded_by': 'wama.common.tts.service'}),
                                 ('huggingface:o/bare', {})):
                line = _line(key, {'runtime': runtime} if runtime else {})
                line.extra_info = {'path': folder}
                r._models[key] = line
            r._overlay_engines_derived_from_disk()
        self.assertNotIn('engine', r._models['huggingface:o/declared'].composition['runtime'])
        self.assertEqual('diffusers',
                         r._models['huggingface:o/bare'].composition['runtime']['engine'])

    def test_the_manifest_accepts_a_loader_or_an_engine_but_not_an_empty_runtime(self):
        from wama.common.manifests.builtin.model import _validate_composition
        self.assertEqual([], _validate_composition({'runtime': {'loaded_by': 'wama.common.tts.service'}}))
        self.assertEqual([], _validate_composition({'runtime': {'engine': 'audio-cpp',
                                                                'family': 'minimax_music3'}}))
        self.assertTrue(_validate_composition({'runtime': {}}))


class EngineNamedByItsBackendTest(TestCase):

    def test_the_inventory_reads_the_catalogue_keys_listed_by_a_backend(self):
        from wama.common.services.backend_inventory import resolvable_entries
        pyannote = [e for e in resolvable_entries() if e.name == 'PyannoteDiarizerBackend']
        self.assertEqual(1, len(pyannote))
        self.assertIn(PYANNOTE, pyannote[0].served_keys)
        self.assertEqual('pyannote', pyannote[0].engine)

    def test_a_line_without_engine_receives_the_engine_of_the_backend_that_names_it(self):
        r = _registry()
        r._models[PYANNOTE] = _line(PYANNOTE)
        r._overlay_engines_named_by_backends()
        self.assertEqual('pyannote', r._models[PYANNOTE].composition['runtime']['engine'])

    def test_a_declared_engine_is_never_replaced(self):
        """Contre-épreuve : la passe ne comble que le vide."""
        r = _registry()
        r._models[PYANNOTE] = _line(PYANNOTE, {'runtime': {'engine': 'autre'}})
        r._overlay_engines_named_by_backends()
        self.assertEqual('autre', r._models[PYANNOTE].composition['runtime']['engine'])
