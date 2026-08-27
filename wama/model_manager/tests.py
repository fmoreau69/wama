"""
Model Manager — réconciliation du catalogue.

CE QUE CES TESTS PROTÈGENT, ET POURQUOI ILS EXISTENT

    Le 2026-08-22 à 18:38, une passe de synchronisation a EFFACÉ `anonymizer:sam3` du catalogue.
    Le modèle était installé, en cache HuggingFace et `ready: True` — rien n'était cassé côté
    anonymizer. Ce qui a échoué est la chaîne d'inférence :

        la déclaration de SAM3 lève dans le processus qui synchronise
          → `except Exception: pass` du registre l'avale SANS UN MOT
          → SAM3 sort de la découverte
          → la réconciliation le range parmi les « modèles absents du disque »
          → `delete_missing` SUPPRIME sa ligne.

    Le défaut n'est pas l'exception : c'est d'avoir traité une ABSENCE À LA DÉCOUVERTE comme la
    PREUVE d'une disparition. Les deux sont indiscernables du point de vue de la réconciliation,
    et une seule justifie de détruire des données.

    Coût réel de l'incident : la perte n'a été vue que 4 heures plus tard, par ricochet — une
    référence de manifeste devenue non résolvable. Aucune alerte entre les deux.
"""
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from .models import AIModel
from .services.model_registry import ModelRegistry
from .services.model_sync import ModelSyncService


def _decouverte(erreurs=(), modeles=None):
    """Fabrique une découverte CONTRÔLÉE — complète ou en échec, au choix du test."""
    def _faux(self):
        self._models = dict(modeles or {})
        self.discovery_errors = list(erreurs)
        return self._models
    return _faux


class ReconciliationTest(TestCase):
    """La suppression ne s'autorise que sur une découverte ENTIÈRE."""

    def setUp(self):
        # Une ligne que la découverte simulée ne rendra jamais : c'est elle qui joue le rôle
        # de SAM3 le jour de l'incident.
        self.temoin = AIModel.objects.create(
            model_key='test:temoin_reconciliation',
            name='Témoin de réconciliation',
            model_type='vision',
            source='anonymizer',
        )

    def test_une_decouverte_INCOMPLETE_ne_supprime_rien(self):
        """LE contrôle qui aurait évité l'incident."""
        echec = ['anonymizer:sam3 : ImportError: simulation']
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=echec)):
            resultat = ModelSyncService().full_sync(delete_missing=True)

        self.assertTrue(AIModel.objects.filter(pk=self.temoin.pk).exists(),
                        "une découverte en échec a fait supprimer une ligne de catalogue")
        self.assertEqual(resultat.removed, 0)
        self.assertTrue(any('SUSPENDUE' in e for e in resultat.errors),
                        "la suspension doit être DITE, pas silencieuse — sinon on croit "
                        "la réconciliation faite")

    def test_une_decouverte_incomplete_ne_marque_pas_non_plus_INDISPONIBLE(self):
        # `remove_missing` est l'autre chemin : moins brutal, tout aussi faux. Un modèle marqué
        # indisponible disparaît des sélecteurs — l'utilisateur constate juste qu'il « n'y est plus ».
        with patch.object(ModelRegistry, 'discover_all_models',
                          _decouverte(erreurs=['x : boom'])):
            ModelSyncService().full_sync(remove_missing=True)
        self.temoin.refresh_from_db()
        self.assertTrue(self.temoin.is_available)

    def test_une_decouverte_COMPLETE_supprime_normalement(self):
        """Le pendant indispensable : la garde ne doit pas neutraliser la réconciliation.

        Sans ce test, poser `delete_missing = False` en dur passerait le test précédent — et le
        catalogue accumulerait pour toujours des modèles retirés du disque.
        """
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=())):
            resultat = ModelSyncService().full_sync(delete_missing=True)

        self.assertFalse(AIModel.objects.filter(pk=self.temoin.pk).exists(),
                         "une découverte saine doit bien retirer ce qui a disparu")
        self.assertGreaterEqual(resultat.removed, 1)

    def test_les_candidats_de_prospection_ne_sont_jamais_reconcilies(self):
        # Ils ne sont pas sur disque PAR NATURE — les réconcilier les effacerait à chaque passe.
        propose = AIModel.objects.create(
            model_key='test:candidat_propose', name='Candidat', model_type='llm',
            source='ollama', is_proposed=True,
        )
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=())):
            ModelSyncService().full_sync(delete_missing=True)
        self.assertTrue(AIModel.objects.filter(pk=propose.pk).exists())


class DiscoveryErrorsTest(TestCase):
    """Le registre doit POUVOIR dire qu'il a échoué — sinon la garde ci-dessus est aveugle."""

    def test_le_registre_expose_ses_echecs_de_decouverte(self):
        registre = ModelRegistry()
        self.assertIsInstance(getattr(registre, 'discovery_errors', None), list)

    def test_une_passe_neuve_repart_d_une_liste_VIDE(self):
        """Sans cela, la première panne gèlerait les suppressions à jamais : les erreurs
        s'accumuleraient d'une passe sur l'autre et la réconciliation ne reprendrait jamais."""
        registre = ModelRegistry()
        registre.discovery_errors = ['résidu de la passe précédente']
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=())):
            ModelSyncService().full_sync()
        self.assertEqual(registre.discovery_errors, [])

    def test_les_echecs_ne_sont_pas_partages_par_la_CLASSE(self):
        # `discovery_errors` est déclaré au niveau classe (le `__init__` du singleton sort tôt) :
        # il faut donc s'assurer qu'une passe RÉASSIGNE la liste au lieu de muter le défaut,
        # sinon les erreurs contamineraient toute instance future.
        ModelRegistry().discovery_errors = ['local']
        self.assertEqual(ModelRegistry.discovery_errors, [],
                         "le défaut de classe ne doit jamais être muté")


# ─────────────────────────────────────────────────────────────────────────────────────────
# Chaîne d'installation — balayage générique, désinstallation, choix de variante.
#
# CE QUE CES TESTS PROTÈGENT. Le 2026-08-26, MiniMax-Music3 (54 Go) a été installé par
# `install_from_spec` : téléchargement complet, tâche en succès — et modèle INVISIBLE partout,
# parce que la découverte est déclarative par app et qu'aucune app ne le déclarait. Trois trous
# refermés le 2026-08-27 (décision Fabien) : ① tout snapshot HF installé est CATALOGUÉ (balayage
# générique) ; ② un modèle installé se DÉSINSTALLE (poids seuls, catalogue recalé) ; ③ le choix
# poids pleins / variante quantisée est EXPLICITE avant installation, et l'installation respecte
# ce choix (le juge de confiance évaluait déjà la faisabilité VRAM sur les variantes).
# ─────────────────────────────────────────────────────────────────────────────────────────


def _faux_snapshot(racine, categorie, famille, org, nom, *, incomplet=False):
    """Fabrique un snapshot HF minimal sur disque (structure réelle de huggingface_hub)."""
    depot = racine / 'models' / categorie / famille / f"models--{org}--{nom}"
    (depot / 'snapshots' / 'rev0').mkdir(parents=True)
    (depot / 'snapshots' / 'rev0' / 'model.safetensors').write_bytes(b'0' * 1024)
    (depot / 'blobs').mkdir()
    (depot / 'blobs' / 'abc123').write_bytes(b'0' * 2048)
    if incomplet:
        (depot / 'blobs' / 'def456.incomplete').write_bytes(b'0' * 10)
    return depot


class SnapshotsInstallesTest(TestCase):
    """Un snapshot HF installé au bon endroit doit apparaître au catalogue, sans déclaration."""

    def _balayer(self, racine, deja=None):
        from django.test import override_settings
        registre = ModelRegistry()
        registre._models = {}
        if deja:
            registre._models.update(deja)
        with override_settings(AI_MODELS_DIR=racine):
            registre._discover_installed_hf_snapshots()
        return registre._models

    def test_un_snapshot_installe_est_catalogue_avec_cle_et_type(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            _faux_snapshot(racine, 'music', 'MiniMax-Music3', 'MiniMaxAI', 'MiniMax-Music3')
            modeles = self._balayer(racine)
        cle = 'huggingface:MiniMaxAI/MiniMax-Music3'
        self.assertIn(cle, modeles)
        m = modeles[cle]
        self.assertEqual(m.model_type.value, 'music')
        self.assertEqual(m.hf_id, 'MiniMaxAI/MiniMax-Music3')
        self.assertTrue(m.is_downloaded)
        self.assertEqual(m.format, 'safetensors')
        self.assertFalse(m.backend_ref, "catalogué ≠ utilisable : pas de backend inventé")

    def test_un_depot_deja_declare_par_une_app_n_est_pas_duplique(self):
        """L'entrée d'app (backend, VRAM, capacités) fait autorité — le balayage se tait."""
        import tempfile

        from .models import ModelSource, ModelType
        from .services.model_registry import ModelInfo
        declare = ModelInfo(id='musicgen-small', name='MusicGen', model_type=ModelType.MUSIC,
                            source=ModelSource.WAMA_COMPOSER, hf_id='facebook/musicgen-small')
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            _faux_snapshot(racine, 'music', 'musicgen', 'facebook', 'musicgen-small')
            modeles = self._balayer(racine, deja={'composer:musicgen-small': declare})
        self.assertNotIn('huggingface:facebook/musicgen-small', modeles)

    def test_un_telechargement_interrompu_n_est_pas_repute_telecharge(self):
        """C'est l'état exact qu'un kill en plein download laisse derrière lui (.incomplete)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            _faux_snapshot(racine, 'music', 'Foo', 'Org', 'Foo', incomplet=True)
            modeles = self._balayer(racine)
        m = modeles['huggingface:Org/Foo']
        self.assertFalse(m.is_downloaded)
        self.assertTrue(m.extra_info.get('incomplete'))

    def test_une_famille_declaree_dans_MODEL_PATHS_appartient_a_son_app(self):
        """Le critère famille reste nécessaire même depuis que transcriber/synthesizer/
        anonymizer posent leur hf_id (2026-08-27) : le dépôt DÉCLARÉ n'est pas toujours celui
        du SNAPSHOT sur disque (déclaré `openai/whisper-large-v3`, disque
        `Systran/faster-whisper-large-v3` — la dédup par hf_id ne les relie pas ; 16 doublons
        mesurés sans ce critère). MODEL_PATHS est LA déclaration « ce dossier appartient à
        une app » (checklist étape 1)."""
        import tempfile

        from django.test import override_settings
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            _faux_snapshot(racine, 'speech', 'whisper', 'Systran', 'faster-whisper-tiny')
            _faux_snapshot(racine, 'music', 'Orphelin', 'Org', 'Orphelin')
            with override_settings(MODEL_PATHS={'speech': {
                    'whisper': racine / 'models' / 'speech' / 'whisper'}}):
                modeles = self._balayer(racine)
        self.assertNotIn('huggingface:Systran/faster-whisper-tiny', modeles,
                         "une famille déclarée est gouvernée par son app, pas par le balayage")
        self.assertIn('huggingface:Org/Orphelin', modeles)

    def test_un_dossier_de_categorie_inconnue_est_ignore(self):
        # Un dossier hors taxonomie ModelType n'invente pas de type au catalogue.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            _faux_snapshot(racine, 'pas-une-categorie', 'Foo', 'Org', 'Foo')
            modeles = self._balayer(racine)
        self.assertEqual(modeles, {})


class ProvenanceDeclareeTest(TestCase):
    """La provenance HF est DÉCLARÉE par l'app et POSÉE par sa découverte (2026-08-27).

    Avant cela, transcriber/synthesizer/anonymizer n'alimentaient jamais `ModelInfo.hf_id` :
    le catalogue (AIModel.hf_id) restait vide pour leurs modèles, la chaîne
    provenance/licences n'avait rien à lire, et le balayage snapshots ne pouvait pas les
    dédupliquer par dépôt (d'où le critère famille, qui reste).
    """

    def _decouvrir(self, methode):
        registre = ModelRegistry()
        registre._models = {}
        getattr(registre, methode)()
        return registre._models

    def test_la_decouverte_transcriber_pose_le_hf_id_declare_par_l_app(self):
        modeles = self._decouvrir('_discover_transcriber_models')
        self.assertEqual(modeles['transcriber:whisper'].hf_id, 'openai/whisper-large-v3')
        self.assertEqual(modeles['transcriber:qwen3-asr-0.6b'].hf_id, 'Qwen/Qwen3-ASR-0.6B')

    def test_la_decouverte_synthesizer_pose_le_hf_id_declare_par_l_app(self):
        from wama.synthesizer.utils.model_config import SYNTHESIZER_MODELS
        modeles = self._decouvrir('_discover_synthesizer_models')
        for cle in ('coqui-xtts', 'bark', 'higgs-audio', 'kokoro'):
            self.assertEqual(modeles[f'synthesizer:{cle}'].hf_id,
                             SYNTHESIZER_MODELS[cle]['hf_id'], cle)

    def test_un_poids_yolo_sans_provenance_etablie_reste_sans_hf_id(self):
        # La provenance se DÉCLARE (YOLO_WEIGHTS_HF_ID), elle ne s'infère pas d'un nom de
        # fichier : un poids hors mapping rend '' — y compris les finetunes maison.
        from wama.anonymizer.utils.model_config import hf_id_for_yolo_weight
        self.assertEqual(hf_id_for_yolo_weight('license-plate-finetune-v1n.onnx'),
                         'morsetechlab/yolov11-license-plate-detection')
        self.assertEqual(hf_id_for_yolo_weight('face_yolov8m-seg_60.pt'),
                         'jags/yolov8_model_segmentation-set')
        self.assertEqual(hf_id_for_yolo_weight('yolo11n.pt'), '')
        self.assertEqual(hf_id_for_yolo_weight('yolov8n_face_plate_720p.pt'), '')

    def test_la_decouverte_anonymizer_pose_la_provenance_declaree(self):
        fausse_liste = {'detect': [
            {'name': 'license-plate-finetune-v1n.onnx', 'specialty': 'plates',
             'size': 1024, 'path': ''},
            {'name': 'yolo11n.pt', 'specialty': '', 'size': 1024, 'path': ''},
        ]}
        with patch('wama.anonymizer.utils.model_config.list_available_yolo_models',
                   return_value=fausse_liste):
            modeles = self._decouvrir('_discover_anonymizer_models')
        self.assertEqual(modeles['anonymizer:yolo:license-plate-finetune-v1n.onnx'].hf_id,
                         'morsetechlab/yolov11-license-plate-detection')
        self.assertIsNone(modeles['anonymizer:yolo:yolo11n.pt'].hf_id)
        # SAM3 : dépôt lu sur sam3_manager (SAM3_HF_REPO), source unique.
        self.assertEqual(modeles['anonymizer:sam3'].hf_id, 'facebook/sam3')


class DesinstallationTest(TestCase):
    """Désinstaller = retirer les POIDS, marquer le catalogue — jamais supprimer la ligne."""

    def _modele_avec_snapshot(self, racine):
        depot = _faux_snapshot(racine, 'music', 'Fam', 'Org', 'Nom')
        (depot.parent / '.locks' / depot.name).mkdir(parents=True)
        return AIModel.objects.create(
            model_key='huggingface:Org/Nom', name='Nom', model_type='music',
            source='huggingface', is_downloaded=True, disk_gb=0.1,
            local_path=str(depot), extra_info={'hf_snapshot': True, 'path': str(depot)},
        ), depot

    def test_desinstaller_un_snapshot_retire_poids_et_verrous_et_recale_le_catalogue(self):
        import tempfile

        from django.test import override_settings

        from .services.model_installer import uninstall_model
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            modele, depot = self._modele_avec_snapshot(racine)
            with override_settings(AI_MODELS_DIR=racine):
                res = uninstall_model('huggingface:Org/Nom')
            self.assertTrue(res['ok'], res)
            self.assertFalse(depot.exists(), "les poids doivent être retirés du disque")
            self.assertFalse((depot.parent / '.locks' / depot.name).exists())
        modele.refresh_from_db()
        self.assertFalse(modele.is_downloaded)
        self.assertTrue(AIModel.objects.filter(pk=modele.pk).exists(),
                        "la ligne porte l'historique — elle se marque, ne se supprime pas")
        self.assertIn('uninstalled_at', modele.extra_info)

    def test_un_modele_charge_ne_se_desinstalle_pas(self):
        from .services.model_installer import uninstall_model
        AIModel.objects.create(model_key='huggingface:Org/Charge', name='Chargé',
                               model_type='music', source='huggingface',
                               is_downloaded=True, is_loaded=True)
        res = uninstall_model('huggingface:Org/Charge')
        self.assertFalse(res['ok'])
        self.assertIn('décharger', res['error'])

    def test_un_chemin_hors_racine_est_refuse_quoi_que_dise_la_base(self):
        """LE garde-fou du rm -rf : une base corrompue ne doit jamais faire supprimer ailleurs."""
        import tempfile

        from django.test import override_settings

        from .services.model_installer import uninstall_model
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            (racine / 'models').mkdir()
            ailleurs = racine / 'ailleurs' / 'models--Org--Nom'
            ailleurs.mkdir(parents=True)
            AIModel.objects.create(model_key='huggingface:Org/Hors', name='Hors',
                                   model_type='music', source='huggingface',
                                   is_downloaded=True, local_path=str(ailleurs))
            with override_settings(AI_MODELS_DIR=racine):
                res = uninstall_model('huggingface:Org/Hors')
            self.assertFalse(res['ok'])
            self.assertTrue(ailleurs.exists(), "rien ne doit être supprimé hors racine")

    def test_un_candidat_de_prospection_se_rejette_il_ne_se_desinstalle_pas(self):
        from .services.model_installer import uninstall_model
        AIModel.objects.create(model_key='proposed:hf:X/Y', name='Y', model_type='music',
                               source='huggingface', is_proposed=True, is_downloaded=False)
        res = uninstall_model('proposed:hf:X/Y')
        self.assertFalse(res['ok'])


class CompositionTest(TestCase):
    """Un modèle MULTI-COMPOSANTS déclare son anatomie UNE fois (manifeste `model`,
    body.composition) ; l'installation en dérive son jeu cohérent, le backend composé son
    chargement. Cas d'école : MiniMax-Music3, 5 GGUF = 1 modèle (2026-08-27)."""

    COMPO = {
        'components': [
            {'role': 'language_model', 'pattern': '*-language_model-Q8_0.gguf', 'format': 'gguf'},
            {'role': 'vocoder', 'pattern': '*-vocoder-F32.gguf', 'format': 'gguf'},
        ],
        'runtime': {'engine': 'audio-cpp'},
    }

    def test_une_composition_bien_formee_est_acceptee_et_vide_aussi(self):
        from wama.common.manifests.builtin.model import validate_model_body
        self.assertEqual(validate_model_body({'composition': self.COMPO}), [])
        self.assertEqual(validate_model_body({'composition': {}}), [])
        self.assertEqual(validate_model_body({}), [])

    def test_un_role_duplique_ou_un_pattern_manquant_est_refuse(self):
        from wama.common.manifests.builtin.model import validate_model_body
        deux_fois = {'components': [{'role': 'x', 'pattern': 'a'}, {'role': 'x', 'pattern': 'b'}]}
        self.assertTrue(any('dupliqué' in e for e in
                            validate_model_body({'composition': deux_fois})))
        sans_pattern = {'components': [{'role': 'x'}]}
        self.assertTrue(any('pattern' in e for e in
                            validate_model_body({'composition': sans_pattern})))

    def test_un_runtime_sans_engine_ou_une_cle_inconnue_est_refuse(self):
        from wama.common.manifests.builtin.model import validate_model_body
        self.assertTrue(any('engine' in e for e in
                            validate_model_body({'composition': {'runtime': {}}})))
        self.assertTrue(any('inconnues' in e for e in
                            validate_model_body({'composition': {'pipeline': []}})))

    def test_le_write_back_projette_la_composition_et_la_revocation_rend_un_dict_vide(self):
        """Même nature déclarée que license/prompt_contract : le manifeste a autorité,
        la découverte jamais — et la révocation doit rendre le VIDE DU TYPE ({}), pas ''."""
        from wama.common.manifests.builtin.model import un_write_back_model, write_back_model
        AIModel.objects.create(model_key='huggingface:Org/Compose', name='Composé',
                               model_type='music', source='huggingface')
        manifeste = {'manifest_kind': 'model', 'key': 'huggingface:Org/Compose',
                     'body': {'composition': self.COMPO}}
        write_back_model(manifeste, apply=True)
        m = AIModel.objects.get(model_key='huggingface:Org/Compose')
        self.assertEqual(m.composition, self.COMPO)
        un_write_back_model(manifeste, apply=True)
        m.refresh_from_db()
        self.assertEqual(m.composition, {})

    def test_l_installation_derive_ses_allow_patterns_de_la_composition(self):
        """La moitié « installation » du contrat : jeu COHÉRENT dérivé de l'anatomie —
        jamais le dépôt entier d'un repack multi-quantisations."""
        from .services.model_installer import patterns_from_composition
        patterns = patterns_from_composition(self.COMPO)
        self.assertIn('*-language_model-Q8_0.gguf', patterns)
        self.assertIn('*-vocoder-F32.gguf', patterns)
        self.assertIn('*.json', patterns, "les fichiers de bord (config) font partie du jeu")
        self.assertIsNone(patterns_from_composition({}),
                          "sans composition déclarée : dépôt entier, cas général inchangé")
        self.assertIsNone(patterns_from_composition(None))


class InstallDepuisLeCatalogueTest(TestCase):
    """Un modèle d'app « Not downloaded » doit s'installer EXPLICITEMENT (2026-08-27, cas
    musicgen-melody : affiché sans aucun geste — l'affichage est voulu, le geste manquait).
    Le spec se dérive de ce que l'APP déclare (hf_id + extra_info.install_dir) — le registre
    n'invente jamais d'emplacement."""

    def test_le_spec_se_derive_de_l_emplacement_declare_par_l_app(self):
        import tempfile

        from django.test import override_settings

        from .services.model_installer import spec_for_catalog_row
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            (racine / 'models' / 'music' / 'musicgen').mkdir(parents=True)
            m = AIModel.objects.create(
                model_key='composer:musicgen-melody', name='MusicGen Melody',
                model_type='music', source='composer', hf_id='facebook/musicgen-melody',
                extra_info={'install_dir': str(racine / 'models' / 'music' / 'musicgen')})
            with override_settings(AI_MODELS_DIR=racine):
                spec = spec_for_catalog_row(m)
        self.assertEqual(spec['kind'], 'hf')
        self.assertEqual(spec['ref'], 'facebook/musicgen-melody')
        self.assertEqual(spec['category'], 'music')
        self.assertEqual(spec['family'], 'musicgen',
                         "les poids doivent rejoindre le dossier DÉCLARÉ par l'app — sinon "
                         "sa découverte (_check_hf_model_downloaded) ne les verra jamais")

    def test_sans_declaration_d_emplacement_pas_de_spec_invente(self):
        from .services.model_installer import spec_for_catalog_row
        sans_dir = AIModel.objects.create(
            model_key='composer:x', name='X', model_type='music', source='composer',
            hf_id='org/x')
        sans_hf = AIModel.objects.create(
            model_key='composer:y', name='Y', model_type='music', source='composer',
            extra_info={'install_dir': '/quelque/part'})
        self.assertIsNone(spec_for_catalog_row(sans_dir))
        self.assertIsNone(spec_for_catalog_row(sans_hf))

    def test_un_emplacement_hors_racine_canonique_est_refuse(self):
        import tempfile

        from django.test import override_settings

        from .services.model_installer import spec_for_catalog_row
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            (racine / 'models').mkdir()
            m = AIModel.objects.create(
                model_key='composer:z', name='Z', model_type='music', source='composer',
                hf_id='org/z', extra_info={'install_dir': str(racine / 'ailleurs')})
            with override_settings(AI_MODELS_DIR=racine):
                self.assertIsNone(spec_for_catalog_row(m))

    def test_la_composition_declaree_voyage_dans_le_spec(self):
        # Un modèle composé installé depuis le catalogue tire son JEU COHÉRENT, pas le dépôt.
        import tempfile

        from django.test import override_settings

        from .services.model_installer import spec_for_catalog_row
        compo = {'components': [{'role': 'lm', 'pattern': 'lm_q8.gguf'}]}
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            (racine / 'models' / 'music' / 'Fam').mkdir(parents=True)
            m = AIModel.objects.create(
                model_key='composer:c', name='C', model_type='music', source='composer',
                hf_id='org/c', composition=compo,
                extra_info={'install_dir': str(racine / 'models' / 'music' / 'Fam')})
            with override_settings(AI_MODELS_DIR=racine):
                spec = spec_for_catalog_row(m)
        self.assertEqual(spec['composition'], compo)


class ChoixDeVarianteTest(TestCase):
    """Le spec d'installation doit respecter le choix VALIDÉ par l'utilisateur — rien d'autre."""

    def _candidat(self):
        return AIModel.objects.create(
            model_key='proposed:hf:Org/Grand', name='Grand', model_type='music',
            source='huggingface', is_proposed=True, hf_id='Org/Grand', disk_gb=53.4,
            extra_info={'prospect': {
                'spec': {'kind': 'hf', 'ref': 'Org/Grand', 'category': 'music'},
                'quant_variants': [
                    {'hf_id': 'Repack/Grand-GGUF', 'downloads': 551000, 'disk_gb': 60.0,
                     'files': [{'file': 'grand-q4.gguf', 'gb': 12.5},
                               {'file': 'grand-q8.gguf', 'gb': 24.0}]},
                ],
            }},
        )

    def test_le_choix_des_poids_pleins_rend_le_spec_canonique_inchange(self):
        from .services.prospector import spec_pour_choix
        spec = spec_pour_choix(self._candidat(), 'Org/Grand', None)
        self.assertEqual(spec, {'kind': 'hf', 'ref': 'Org/Grand', 'category': 'music'})

    def test_le_choix_d_un_fichier_gguf_restreint_le_telechargement_a_ce_fichier(self):
        """Un dépôt GGUF porte PLUSIEURS niveaux de quantisation : installer le dépôt entier
        tirerait tous les fichiers — le spec doit descendre au fichier choisi."""
        from .services.prospector import spec_pour_choix
        spec = spec_pour_choix(self._candidat(), 'Repack/Grand-GGUF', 'grand-q4.gguf')
        self.assertEqual(spec['ref'], 'Repack/Grand-GGUF')
        self.assertIn('grand-q4.gguf', spec['allow_patterns'])
        self.assertNotIn('grand-q8.gguf', spec['allow_patterns'])
        # Regroupé sous la famille du modèle canonique : remplaçables/désinstallables ensemble.
        self.assertEqual(spec['family'], 'Grand')

    def test_un_choix_hors_options_est_refuse(self):
        """On n'installe JAMAIS un dépôt qui n'a pas été proposé à l'utilisateur."""
        from .services.prospector import spec_pour_choix
        cand = self._candidat()
        self.assertIsNone(spec_pour_choix(cand, 'Pirate/Autre-GGUF', None))
        self.assertIsNone(spec_pour_choix(cand, 'Repack/Grand-GGUF', 'inexistant.gguf'))
