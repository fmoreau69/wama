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

from django.test import TestCase, override_settings

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


class SupersededSnapshotTest(TestCase):
    """Un snapshot du balayage générique RELEVÉ par une déclaration d'app sort du catalogue.

    Vécu sur FastWan (16/09 puis 23/09) : la ligne `huggingface:` restait à côté de la ligne
    `imager:` — mêmes poids, deux cards, la seconde sans capacités donc hors de tout banc.
    """

    HF_ID = 'org/relayed-model'

    def setUp(self):
        from .services.model_registry import ModelInfo, ModelSource, ModelType
        self.snapshot = AIModel.objects.create(
            model_key=f'huggingface:{self.HF_ID}', name='relayed-model', model_type='diffusion',
            source='huggingface', hf_id=self.HF_ID, is_downloaded=True,
            extra_info={'hf_snapshot': True})
        self.app_row = {'imager:relayed': ModelInfo(
            id='relayed', name='Relayed', model_type=ModelType.DIFFUSION,
            source=ModelSource.WAMA_IMAGER, hf_id=self.HF_ID, is_downloaded=True)}

    def test_a_snapshot_claimed_by_an_app_is_dropped_without_clean(self):
        with patch.object(ModelRegistry, 'discover_all_models',
                          _decouverte(modeles=self.app_row)):
            result = ModelSyncService().full_sync()
        self.assertFalse(AIModel.objects.filter(pk=self.snapshot.pk).exists())
        self.assertTrue(AIModel.objects.filter(model_key='imager:relayed').exists())
        self.assertEqual(result.removed, 1)

    def test_an_unclaimed_snapshot_stays(self):
        # Counter-test: without a declaration carrying its hf_id, nothing relays it.
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte()):
            ModelSyncService().full_sync()
        self.assertTrue(AIModel.objects.filter(pk=self.snapshot.pk).exists())

    def test_an_incomplete_discovery_drops_nothing(self):
        with patch.object(ModelRegistry, 'discover_all_models',
                          _decouverte(erreurs=['x : boom'], modeles=self.app_row)):
            ModelSyncService().full_sync()
        self.assertTrue(AIModel.objects.filter(pk=self.snapshot.pk).exists())


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
        self.assertEqual(m.vram_gb, 0, "un snapshot incomplet n'estime pas de VRAM "
                                       "(ses poids partiels ne disent rien)")

    def test_la_vram_est_estimee_depuis_les_poids_et_dite_estimation(self):
        """Le défaut mesuré du 02/09 : vram_gb=0 valait « inconnu » et le curseur de
        qualité traitait ces modèles au PIRE coût — jamais tirés en « rapide ». Les poids
        sur disque (fait MESURÉ) donnent un plancher, marqué `vram_estimated` (une vraie
        mesure de banc le remplacera). Plancher 0,1 : l'arrondi à 0.0 d'un petit modèle
        recréerait exactement l'« inconnu » pénalisé."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            racine = Path(tmp)
            _faux_snapshot(racine, 'music', 'Bar', 'Org', 'Bar')   # blobs = 2 Ko
            modeles = self._balayer(racine)
        m = modeles['huggingface:Org/Bar']
        self.assertEqual(m.vram_gb, 0.1)
        self.assertTrue(m.extra_info.get('vram_estimated'))

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


class GardeAuteurTest(TestCase):
    """Un auteur curé SURVIT aux rafraîchissements automatiques (défaut vécu le 2026-08-27 :
    la boucle --licenses du backfill a écrasé 6 auteurs curés par le slug d'organisation de
    la carte HF — « Tencent Hunyuan » devenait « hunyuanvideo-community », l'org MIROIR).
    Même doctrine que le placeholder `other` pour la licence : la carte COMPLÈTE un champ
    vide, elle n'écrase jamais une valeur posée."""

    def _modele(self, cle, **champs):
        return AIModel.objects.create(model_key=cle, name=cle, model_type='music',
                                      source='composer', hf_id='org/depot', **champs)

    def test_le_backfill_complete_un_auteur_vide_mais_n_ecrase_jamais_un_auteur_pose(self):
        from django.core.management import call_command
        cure = self._modele('composer:cure', author='Auteur Curé')
        vide = self._modele('composer:vide', author='')
        ident = {'license': 'mit', 'author': 'slug-org',
                 'platform_ref': 'huggingface:org/depot', 'hf_id': 'org/depot'}
        with patch('wama.model_manager.services.provenance.huggingface_identity',
                   return_value=ident):
            call_command('backfill_platform_refs', '--licenses', '--ecrire')
        cure.refresh_from_db()
        vide.refresh_from_db()
        self.assertEqual(cure.author, 'Auteur Curé', "l'auteur posé ne doit pas être écrasé")
        self.assertEqual(vide.author, 'slug-org', "l'auteur vide doit être complété")
        self.assertEqual(cure.license, 'mit', "la licence, elle, se remplit normalement")

    def test_poser_identite_ne_touche_pas_un_auteur_deja_etabli(self):
        from wama.model_manager.services.provenance import set_identity
        self._modele('composer:cure2', author='Auteur Curé', license='mit')
        resultat = set_identity(
            'composer:cure2',
            {'author': 'slug-org', 'hf_id': 'org/depot',
             'platform_ref': 'huggingface:org/depot'},
            apply=False, export=False)
        self.assertNotIn('author', resultat.get('posed', ()),
                         "set_identity ne doit compléter l'auteur que s'il est vide")


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

    def test_a_mute_manifest_does_not_erase_a_known_anatomy(self):
        """La garde ajoutée le 2026-09-20, calquée sur celle de `gated` : `composition` ne se
        projette QU'AU DÉCLARÉ. Sans elle, la lambda rendait `{}` dès que la clé manquait, et un
        `apply_manifests` sur l'un des **131 manifestes de modèle sans `components`** (sur 141)
        effaçait l'anatomie de la ligne — en silence, juste après qu'on l'ait déclarée.
        Le vide de ce champ n'est pas une valeur, c'est une absence de mesure."""
        from wama.common.manifests.builtin.model import un_write_back_model, write_back_model
        AIModel.objects.create(model_key='huggingface:Org/Muet', name='Muet',
                               model_type='music', source='huggingface',
                               composition=self.COMPO)
        muet = {'manifest_kind': 'model', 'key': 'huggingface:Org/Muet',
                'body': {'identity': {'license': 'mit'}}}
        plan = write_back_model(muet)
        self.assertIn('composition', plan['preserved'])
        write_back_model(muet, apply=True)
        m = AIModel.objects.get(model_key='huggingface:Org/Muet')
        self.assertEqual(m.composition, self.COMPO, "un manifeste muet a effacé l'anatomie")
        self.assertEqual(m.license, 'mit', "le reste du manifeste doit bien se projeter")
        # la RÉVOCATION, elle, a le droit d'effacer : c'est le geste délibéré
        un_write_back_model(muet, apply=True)
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


class RegimeDAccesTest(TestCase):
    """Le régime d'accès au dépôt amont (`gated`) est un FAIT tiré de la source, pas une phrase.

    Né d'un constat (2026-09-07) : la description de SAM3 portait « Nécessite un token
    HuggingFace configuré » — une contrainte qu'aucun sélecteur, aucun installeur et aucun
    planificateur ne pouvait lire. Le rattrapage a révélé 9 autres dépôts conditionnés que
    personne n'avait écrits nulle part.
    """

    def test_le_vocabulaire_est_ferme_et_un_booleen_est_refuse(self):
        """HuggingFace rend `False`, WAMA écrit 'no'. Accepter les deux ferait DEUX écritures
        du même fait, dont une seule se projetterait — le défaut exact qu'on a failli livrer."""
        from wama.common.manifests.builtin.model import validate_model_body
        for bon in ('no', 'auto', 'manual'):
            self.assertEqual(validate_model_body({'identity': {'gated': bon}}), [],
                             f"'{bon}' doit être accepté")
        for mauvais in (False, True, 'oui', 'gated'):
            self.assertTrue(any('gated' in e for e in
                                validate_model_body({'identity': {'gated': mauvais}})),
                            f"{mauvais!r} doit être refusé")

    def test_la_cle_absente_est_licite_car_inconnu_n_est_pas_libre(self):
        """Le vide n'est pas une valeur : c'est l'absence de mesure. Un modèle jamais interrogé
        ne doit pas se présenter comme accessible — même règle que « VRAM inconnue ≠ gratuite »."""
        from wama.common.manifests.builtin.model import validate_model_body
        self.assertEqual(validate_model_body({'identity': {}}), [])
        self.assertEqual(validate_model_body({}), [])

    def test_un_manifeste_MUET_ne_rabaisse_pas_un_regime_deja_connu(self):
        """Le piège de ce chantier : les lambdas de `_CHAMPS_PROJETES` rendent '' quand la clé
        manque, donc y inscrire `gated` aurait EFFACÉ un régime connu au premier manifeste muet.
        Ne pas savoir n'autorise pas à oublier ce qu'on savait."""
        from wama.common.manifests.builtin.model import write_back_model
        AIModel.objects.create(model_key='huggingface:Org/Ferme', name='Fermé',
                               model_type='vision', source='huggingface', gated='manual')
        write_back_model({'manifest_kind': 'model', 'key': 'huggingface:Org/Ferme',
                          'body': {'identity': {}}}, apply=True)
        self.assertEqual(AIModel.objects.get(model_key='huggingface:Org/Ferme').gated, 'manual')

    def test_un_manifeste_QUI_DECLARE_ecrase_car_le_depot_amont_change(self):
        """Contrairement à l'auteur (fait curé à la main), le régime est l'état COURANT du dépôt :
        un éditeur ouvre ou ferme l'accès, et la dernière lecture fait foi."""
        from wama.common.manifests.builtin.model import write_back_model
        AIModel.objects.create(model_key='huggingface:Org/Ouvert', name='Ouvert',
                               model_type='vision', source='huggingface', gated='manual')
        write_back_model({'manifest_kind': 'model', 'key': 'huggingface:Org/Ouvert',
                          'body': {'identity': {'gated': 'no'}}}, apply=True)
        self.assertEqual(AIModel.objects.get(model_key='huggingface:Org/Ouvert').gated, 'no')

    def test_l_extraction_TAIT_la_cle_tant_que_le_regime_est_inconnu(self):
        """Un manifeste muet dit « je ne sais pas » ; un `gated` écrit affirmerait « libre »
        sur un dépôt jamais interrogé."""
        from wama.common.manifests.builtin.model import extract_model
        AIModel.objects.create(model_key='huggingface:Org/Jamais', name='Jamais',
                               model_type='vision', source='huggingface', hf_id='Org/Jamais')
        muet = extract_model('huggingface:Org/Jamais')
        self.assertNotIn('gated', muet['body']['identity'])

        AIModel.objects.filter(model_key='huggingface:Org/Jamais').update(gated='auto')
        su = extract_model('huggingface:Org/Jamais')
        self.assertEqual(su['body']['identity']['gated'], 'auto')

    def test_le_registre_et_le_manifeste_partagent_UN_SEUL_vocabulaire(self):
        """L'invariant qui empêche la divergence de revenir : les valeurs non vides des choix du
        champ sont exactement celles que le validateur du manifeste accepte."""
        from wama.common.manifests.builtin.model import validate_model_body
        du_registre = {v for v, _ in AIModel.GATED_CHOICES if v}
        self.assertEqual(du_registre, {'no', 'auto', 'manual'})
        for v in du_registre:
            self.assertEqual(validate_model_body({'identity': {'gated': v}}), [],
                             f"le registre admet '{v}' — le manifeste doit l'admettre aussi")


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
        from .services.prospector import spec_for_choice
        spec = spec_for_choice(self._candidat(), 'Org/Grand', None)
        self.assertEqual(spec, {'kind': 'hf', 'ref': 'Org/Grand', 'category': 'music'})

    def test_le_choix_d_un_fichier_gguf_restreint_le_telechargement_a_ce_fichier(self):
        """Un dépôt GGUF porte PLUSIEURS niveaux de quantisation : installer le dépôt entier
        tirerait tous les fichiers — le spec doit descendre au fichier choisi."""
        from .services.prospector import spec_for_choice
        spec = spec_for_choice(self._candidat(), 'Repack/Grand-GGUF', 'grand-q4.gguf')
        self.assertEqual(spec['ref'], 'Repack/Grand-GGUF')
        self.assertIn('grand-q4.gguf', spec['allow_patterns'])
        self.assertNotIn('grand-q8.gguf', spec['allow_patterns'])
        # Regroupé sous la famille du modèle canonique : remplaçables/désinstallables ensemble.
        self.assertEqual(spec['family'], 'Grand')

    def test_un_choix_hors_options_est_refuse(self):
        """On n'installe JAMAIS un dépôt qui n'a pas été proposé à l'utilisateur."""
        from .services.prospector import spec_for_choice
        cand = self._candidat()
        self.assertIsNone(spec_for_choice(cand, 'Pirate/Autre-GGUF', None))
        self.assertIsNone(spec_for_choice(cand, 'Repack/Grand-GGUF', 'inexistant.gguf'))


class TaxonomieDeProspectionTest(TestCase):
    """
    2026-09-02 (Fabien : « un vrai souci ») — le prospecteur figeait `image-to-image` en
    `upscaling` et `image-to-text` en `ocr` : six modèles d'ÉDITION s'affichaient en
    upscalers, BLIP-base en OCR, et AUCUNE ligne proposée ne portait de tâche — donc aucun
    banc. Les TAGS de la carte départagent ; la tâche s'écrit sur la ligne.
    """

    def test_les_tags_de_la_carte_departagent_les_tags_hf_ambigus(self):
        from .services.prospector import hf_task_to_wama
        # Édition : le cas mesuré (FLUX.2-dev taggé `image-editing`, Qwen-Image-Edit sans tag fin)
        self.assertEqual(hf_task_to_wama('image-to-image', ['diffusers', 'image-editing']),
                         ('image-to-image', 'diffusion'))
        self.assertEqual(hf_task_to_wama('image-to-image', []), ('image-to-image', 'diffusion'))
        # Agrandissement et débruitage : tags déclarés, jamais le nom
        self.assertEqual(hf_task_to_wama('image-to-image', ['super-resolution']), ('upscale', 'upscaling'))
        self.assertEqual(hf_task_to_wama('image-to-image', ['image-denoising']), ('denoise', 'upscaling'))
        # Légendage vs OCR
        self.assertEqual(hf_task_to_wama('image-to-text', ['blip', 'image-captioning']), ('captioning', 'vlm'))
        self.assertEqual(hf_task_to_wama('image-to-text', ['PaddleOCR', 'OCR']), ('ocr', 'ocr'))
        # Sans ambiguïté : traduction directe vers NOTRE vocabulaire
        self.assertEqual(hf_task_to_wama('automatic-speech-recognition', []), ('transcription', 'speech'))
        self.assertEqual(hf_task_to_wama('image-text-to-video', []), ('image-to-video', 'diffusion'))
        # Inconnu : pas de tâche inventée, catégorie par défaut
        self.assertEqual(hf_task_to_wama('tabular-classification', [])[0], None)

    def test_un_vlm_qui_tague_la_detection_est_un_detecteur(self):
        """Cas RÉEL du catalogue (2026-09-19) : `nvidia/LocateAnything-3B` publie
        `pipeline_tag: image-text-to-text` — c'est un VLM par son architecture — et tague
        `object-detection` : il LOCALISE des objets décrits en texte. Sans cette branche il
        entrait en `captioning`/`vlm`, donc mauvais métier, mauvais banc, mauvaise sélection."""
        from .services.prospector import hf_task_to_wama
        self.assertEqual(hf_task_to_wama('image-text-to-text', ['object-detection']),
                         ('detect', 'vision'))
        self.assertEqual(hf_task_to_wama('image-text-to-text', ['zero-shot-object-detection']),
                         ('detect', 'vision'))
        # Un VLM conversationnel ordinaire ne tague pas la détection : il reste du légendage.
        self.assertEqual(hf_task_to_wama('image-text-to-text', ['conversational']),
                         ('captioning', 'vlm'))

    def test_la_tache_ecrite_est_une_tache_du_catalogue(self):
        """Toute tâche rendue doit être une valeur `ModelTask` : sinon `check_model_taxonomy`
        la refuserait et `_local_categories` ne la trouverait dans aucun banc."""
        from .models import ModelTask
        from .services.prospector import HF_TASKS, hf_task_to_wama
        connues = {t.value for t in ModelTask}
        for tache in HF_TASKS:
            for tags in ([], ['image-editing'], ['super-resolution'], ['image-captioning']):
                t, mt = hf_task_to_wama(tache, tags)
                with self.subTest(tache=tache, tags=tags):
                    self.assertIn(t, connues)


class UneSeuleTableTacheCategorieTest(TestCase):
    """
    Tâche → catégorie ne se dit plus qu'à UN endroit (2026-09-19).

    Mesure qui l'a motivée : `prospector` portait deux tables (`_HF_TAG_TASK`,
    `_TASK_MODEL_TYPE`) que la MÊME brique lisait en parallèle de celles du catalogue —
    `select_model_id` par l'une, `get_registry_models` par l'autre. Elles ne se
    contredisaient pas (0 désaccord sur 12 tags), mais celle de la prospection ignorait
    **20 de nos 26 tâches** : pour elles, la borne par catégorie ne s'activait pas.
    """

    def test_les_tags_composites_de_plateforme_gardent_leur_reponse(self):
        """Les 3 tags que seule la table de la prospection connaissait sont désormais des
        ALIAS déclarés au catalogue — mêmes réponses, un seul domicile."""
        from .services.prospector import hf_task_to_wama
        self.assertEqual(hf_task_to_wama('image-text-to-text', []), ('captioning', 'vlm'))
        self.assertEqual(hf_task_to_wama('image-text-to-video', []), ('image-to-video', 'diffusion'))
        self.assertEqual(hf_task_to_wama('text-to-audio-video', []), ('text-to-video', 'diffusion'))

    def test_un_alias_se_traduit_aussi_hors_prospection(self):
        from .models import canonical_task, model_type_for_task, wama_task
        self.assertEqual(canonical_task('image-text-to-text'), 'captioning')
        self.assertEqual(model_type_for_task('image-text-to-text'), 'vlm')
        self.assertEqual(wama_task('image-text-to-text'), 'captioning')

    def test_un_tag_inconnu_ne_devient_pas_une_tache(self):
        """`canonical_task` rend l'entrée INCHANGÉE quand elle est inconnue ; qui ÉCRIT une
        tâche a besoin de `wama_task`, sinon un tag d'éditeur non traduit entrerait en base."""
        from .models import canonical_task, wama_task
        self.assertEqual(canonical_task('tabular-classification'), 'tabular-classification')
        self.assertIsNone(wama_task('tabular-classification'))
        self.assertIsNone(wama_task(''))

    def test_la_categorie_repond_pour_les_taches_que_la_prospection_ignorait(self):
        from .models import ModelTask, model_type_for_task
        muettes = [t.value for t in ModelTask if not model_type_for_task(t.value)]
        self.assertEqual(muettes, [], "toute tâche doit rendre sa catégorie")
        # Les cas qui ne passaient PAS par la table de la prospection (aucune entrée pour eux) :
        self.assertEqual(model_type_for_task('transcription'), 'speech')
        self.assertEqual(model_type_for_task('lip-sync'), 'lipsync')
        self.assertEqual(model_type_for_task('text-to-music'), 'music')

    def test_la_prospection_ne_garde_aucune_table_parallele(self):
        """Garde anti-régression : c'est la COEXISTENCE qui était le défaut, pas son contenu."""
        from .services import prospector
        for mort in ('_TASK_MODEL_TYPE', '_HF_TAG_TASK'):
            self.assertFalse(hasattr(prospector, mort),
                             f"{mort} est revenu : tâche → catégorie se dit dans models.py")

    def test_les_metiers_secondaires_sont_au_vocabulaire_canonique(self):
        """`tasks` était écrit par la découverte et lu par les bancs sans figurer au
        vocabulaire qui se dit « source unique »."""
        from wama.common.utils.model_capabilities import CANONICAL_CAPABILITIES, is_canonical_key
        self.assertTrue(is_canonical_key('tasks'))
        self.assertIn('tasks', CANONICAL_CAPABILITIES)


class EntreesParDefautDeLaTacheTest(TestCase):
    """`TASK_DEFAULT_INPUTS` (2026-09-19) : ce qu'une tâche IMPLIQUE — modalités et entrées —
    pour qu'un modèle installé sans app entre dans l'appariement entrée ↔ modèle. Mesuré avant :
    8 modèles HF n'avaient que `task`, invisibles de `matches_inputs`.
    """

    def test_toute_tache_declare_ses_defauts_dans_le_vocabulaire(self):
        from wama.common.utils.app_modes import INPUT_TYPES
        from wama.common.utils.model_capabilities import MODALITIES
        from .models import TASK_DEFAULT_INPUTS, ModelTask
        for t in ModelTask:
            with self.subTest(tache=t.value):
                self.assertIn(t, TASK_DEFAULT_INPUTS)
                modalites, requises, optionnelles = TASK_DEFAULT_INPUTS[t]
                self.assertTrue(modalites and requises, "une tâche implique au moins une modalité et une entrée")
                self.assertTrue(set(modalites) <= set(MODALITIES))
                self.assertTrue(set(requises) | set(optionnelles) <= set(INPUT_TYPES))

    def test_les_defauts_redisent_ce_que_le_registre_ecrit_en_dur(self):
        """La table n'invente rien : elle reprend les valeurs des 13 sites de `model_registry`."""
        from .models import default_inputs_for
        self.assertEqual({'modalities': ['audio'], 'inputs_required': ['work_audio']},
                         default_inputs_for('transcription'))
        self.assertEqual({'modalities': ['image', 'video'], 'inputs_required': ['work_file']},
                         default_inputs_for('detect'))
        self.assertEqual({'modalities': ['image', 'document'], 'inputs_required': ['work_file']},
                         default_inputs_for('ocr'))
        self.assertEqual({'modalities': ['video'], 'inputs_required': ['prompt', 'work_image']},
                         default_inputs_for('image-to-video'))
        # Vocabulaire d'une plateforme accepté ; tâche inconnue : rien d'inventé.
        self.assertEqual(default_inputs_for('transcription'),
                         default_inputs_for('automatic-speech-recognition'))
        self.assertEqual({}, default_inputs_for('tabular-classification'))
        self.assertEqual({}, default_inputs_for(''))

    def test_l_installation_pose_les_defauts_sans_ecraser_une_declaration(self):
        """Le spec porte la tâche ; l'installation en déduit modalités et entrées, par le
        manifeste, et ne touche pas à ce qu'une ligne déclare déjà (SAM3 : `prompt` en plus)."""
        from .services import provenance as pv
        nu = AIModel.objects.create(
            model_key='huggingface:Org/Asr', name='Asr', model_type='speech', source='huggingface',
            is_downloaded=True, hf_id='Org/Asr', capabilities={})
        declare = AIModel.objects.create(
            model_key='huggingface:Org/Seg', name='Seg', model_type='vision', source='huggingface',
            is_downloaded=True, hf_id='Org/Seg',
            capabilities={'inputs_required': ['work_file', 'prompt'], 'text_promptable': True})
        with patch.object(pv, 'identity_for_spec', return_value={'hf_id': 'Org/Asr'}), \
                patch('django.core.management.call_command'):
            pv.record_after_install({'kind': 'hf', 'ref': 'Org/Asr', 'task': 'transcription'},
                                    ['huggingface:Org/Asr'])
        with patch.object(pv, 'identity_for_spec', return_value={'hf_id': 'Org/Seg'}), \
                patch('django.core.management.call_command'):
            pv.record_after_install({'kind': 'hf', 'ref': 'Org/Seg', 'task': 'segment'},
                                    ['huggingface:Org/Seg'])
        nu.refresh_from_db()
        declare.refresh_from_db()
        self.assertEqual({'task': 'transcription', 'modalities': ['audio'],
                          'inputs_required': ['work_audio']}, nu.capabilities)
        self.assertEqual(['work_file', 'prompt'], declare.capabilities['inputs_required'],
                         "la déclaration plus riche prime sur le défaut")
        self.assertEqual(['image', 'video'], declare.capabilities['modalities'], "le vide est comblé")

    def test_un_modele_distant_qui_voit_ajoute_l_image_a_ses_modalites(self):
        from .services.cloud_models import model_info_for
        chat = model_info_for('albert', {'id': 'g', 'type': 'image-text-to-text', 'aliases': []})
        self.assertEqual(['text', 'image'], chat.capabilities['modalities'])
        self.assertEqual(['prompt'], chat.capabilities['inputs_required'])
        asr = model_info_for('albert', {'id': 'w', 'type': 'automatic-speech-recognition', 'aliases': []})
        self.assertEqual({'task': 'transcription', 'modalities': ['audio'],
                          'inputs_required': ['work_audio']}, asr.capabilities)


class FaitsDeLaCarteTest(TestCase):
    """La carte HuggingFace est lue MÉCANIQUEMENT (2026-09-19) : tâche par pipeline + tags,
    langues déclarées, moteur reconnu. Mesuré avant : la chaîne relisait la carte à
    l'installation et n'en gardait que l'identité — canary publie 25 langues, le catalogue n'en
    avait aucune ; ACE-Step taggé `music` était rangé en ambiance.
    """

    def test_les_tags_de_musique_separent_musique_et_ambiance(self):
        from .services.prospector import hf_task_to_wama
        self.assertEqual(('text-to-music', 'music'), hf_task_to_wama('text-to-audio', ['music', 'text2music']))
        self.assertEqual(('text-to-audio', 'music'), hf_task_to_wama('text-to-audio', ['audio']))

    def test_la_carte_donne_les_langues_et_le_moteur_sans_rien_inventer(self):
        from .services.prospector import card_facts
        facts = card_facts('automatic-speech-recognition', ['audio', 'bg', 'cs'],
                           {'language': ['bg', 'cs', 'da'], 'license': 'cc-by-4.0'}, 'nemo')
        self.assertEqual({'task': 'transcription', 'languages': ['bg', 'cs', 'da']},
                         facts['capabilities'])
        self.assertIsNone(facts['engine'], "`nemo` n'est servi par aucun backend : rien de posé")
        self.assertEqual('transformers',
                         card_facts('object-detection', [], {}, 'transformers')['engine'])
        self.assertEqual(['en'], card_facts('text-to-image', [], {'language': 'en'})['capabilities']['languages'])
        self.assertEqual(['*'], card_facts('text-to-speech', [], {'language': 'multilingual'})['capabilities']['languages'])
        self.assertNotIn('languages', card_facts('text-to-speech', [], {})['capabilities'])

    def _card(self, **attrs):
        class _Card:
            def __init__(self, d):
                self._d = d

            def to_dict(self):
                return dict(self._d)

        class _Info:
            pipeline_tag = attrs.get('pipeline_tag')
            tags = attrs.get('tags', [])
            library_name = attrs.get('library_name')
            author = attrs.get('author', 'Org')
            gated = False
            card_data = _Card(attrs.get('card', {}))
        return _Info()

    def test_l_identite_huggingface_rapporte_aussi_ce_que_la_carte_declare(self):
        from .services import provenance as pv
        info = self._card(pipeline_tag='text-to-audio', tags=['music'], library_name='transformers',
                          card={'license': 'mit', 'language': 'en'})
        with patch('huggingface_hub.HfApi') as api:
            api.return_value.model_info.return_value = info
            ident = pv.huggingface_identity('Org/Musique')
        self.assertEqual(('mit', 'huggingface:Org/Musique'), (ident['license'], ident['platform_ref']))
        self.assertEqual({'capabilities': {'task': 'text-to-music', 'languages': ['en']},
                          'engine': 'transformers'}, ident['declared'])

    def test_l_installation_pose_les_faits_de_la_carte_sans_ecraser_ni_le_spec_ni_l_existant(self):
        from .services import provenance as pv
        blank = AIModel.objects.create(
            model_key='huggingface:Org/Asr', name='Asr', model_type='speech', source='huggingface',
            is_downloaded=True, hf_id='Org/Asr', capabilities={})
        rich = AIModel.objects.create(
            model_key='huggingface:Org/Tts', name='Tts', model_type='speech', source='huggingface',
            is_downloaded=True, hf_id='Org/Tts', capabilities={'task': 'text-to-speech',
                                                              'languages': ['fr']},
            composition={'runtime': {'engine': 'qwen3-tts'}})
        declared = {'capabilities': {'task': 'transcription', 'languages': ['en', 'de']},
                    'engine': 'transformers'}
        with patch.object(pv, 'identity_for_spec',
                          return_value={'hf_id': 'Org/Asr', 'declared': dict(declared)}), \
                patch('django.core.management.call_command'):
            r = pv.record_after_install({'kind': 'hf', 'ref': 'Org/Asr'}, ['huggingface:Org/Asr'])
        blank.refresh_from_db()
        self.assertEqual('transcription', r['task'], "sans tâche au spec, celle de la carte sert")
        self.assertEqual({'task': 'transcription', 'languages': ['en', 'de'],
                          'modalities': ['audio'], 'inputs_required': ['work_audio']},
                         blank.capabilities)
        self.assertEqual('transformers', blank.composition['runtime']['engine'])
        # Le spec (candidat jugé) prime sur la carte ; l'existant prime sur les deux.
        with patch.object(pv, 'identity_for_spec',
                          return_value={'hf_id': 'Org/Tts', 'declared': dict(declared)}), \
                patch('django.core.management.call_command'):
            pv.record_after_install({'kind': 'hf', 'ref': 'Org/Tts', 'task': 'text-to-speech'},
                                    ['huggingface:Org/Tts'])
        rich.refresh_from_db()
        self.assertEqual(['fr'], rich.capabilities['languages'])
        self.assertEqual('text-to-speech', rich.capabilities['task'])
        self.assertEqual('qwen3-tts', rich.composition['runtime']['engine'])


class RestesTechniquesDuSoirTest(TestCase):
    """Trois restes du 02/09, chacun mesuré avant d'être corrigé."""

    def test_un_suffixe_date_ne_fait_pas_un_nouveau_modele(self):
        """`Qwen-Image-Edit-2509` proposé alors que l'imager déclare `-2511` : même famille."""
        from .services.prospector import _sans_suffixe_date
        self.assertEqual(_sans_suffixe_date('Qwen/Qwen-Image-Edit-2511'), 'qwen/qwen-image-edit')
        self.assertEqual(_sans_suffixe_date('Qwen/Qwen-Image-Edit-2509'),
                         _sans_suffixe_date('Qwen/Qwen-Image-Edit-2511'))
        # pas une date : taille, résolution, année seule, mois impossible
        for intact in ('Qwen/Qwen3-Embedding-8B', 'org/model-1024', 'org/model-2026', 'org/model-2513'):
            self.assertEqual(_sans_suffixe_date(intact), intact.lower())

    def test_seul_le_jumeau_bin_d_un_safetensors_est_ecarte(self):
        """table-transformer et Qwen3-TTS tirés en double ; les voix `.pt` de Kokoro restent."""
        from .services import model_installer as mi
        fichiers = ['config.json', 'model.safetensors', 'pytorch_model.bin',      # jumeaux
                    'voices/af_bella.pt',                                          # pas de jumeau → gardé
                    'transformer/diffusion_pytorch_model.safetensors',
                    'transformer/diffusion_pytorch_model.bin',                     # jumeaux
                    'unet/model-00001-of-00002.safetensors', 'unet/model-00002-of-00002.safetensors',
                    'unet/pytorch_model-00001-of-00002.bin', 'unet/pytorch_model-00002-of-00002.bin',
                    'kokoro-v1_0.pth']                                             # seul → gardé
        with patch('huggingface_hub.HfApi') as api:
            api.return_value.list_repo_files.return_value = fichiers
            self.assertEqual(mi.format_duplicates('org/x'),
                             ['pytorch_model.bin', 'transformer/diffusion_pytorch_model.bin',
                              'unet/pytorch_model-00001-of-00002.bin',
                              'unet/pytorch_model-00002-of-00002.bin'])
            api.return_value.list_repo_files.side_effect = RuntimeError('hors ligne')
            self.assertEqual(mi.format_duplicates('org/x'), [])      # best-effort : rien filtré

    def test_twin_rule_reads_an_inventory_already_fetched(self):
        """La règle des jumeaux est une dérivation PURE : elle accepte les couples
        `(chemin, taille)` de `prospector._siblings`, donc un second lecteur (le poids PAR
        COMPOSANT) l'applique sans payer un aller-retour HTTP de plus. Aucun réseau ici — le
        test ne monte AUCUN mock de `HfApi`, c'est ce qui l'atteste."""
        from .services.model_installer import duplicate_weight_files
        couples = [('config.json', 12), ('model.safetensors', 4_200_000_000),
                   ('pytorch_model.bin', 4_200_000_000), ('voices/af_bella.pt', 523_000)]
        self.assertEqual(duplicate_weight_files(couples), ['pytorch_model.bin'])
        # même verdict sur la forme « chemins nus » : une seule règle pour les deux inventaires
        self.assertEqual(duplicate_weight_files([n for n, _ in couples]), ['pytorch_model.bin'])
        self.assertEqual(duplicate_weight_files(None), [])

    def test_components_split_the_weight_by_role_without_the_network(self):
        """Les DEUX chiffres de la decision A : la somme (plein GPU) et le plus gros composant
        (dechargement). Aucun mock de `HfApi` — la derivation est pure."""
        from .services.model_installer import components_of_files
        go = 1024 ** 3
        r = components_of_files([
            ('model_index.json', 900),
            ('transformer/diffusion_pytorch_model-00001-of-00002.safetensors', 5 * go),
            ('transformer/diffusion_pytorch_model-00002-of-00002.safetensors', 5 * go),
            ('transformer/diffusion_pytorch_model-00001-of-00002.bin', 5 * go),   # jumeau de format
            ('text_encoder/model.safetensors', 11 * go),
            ('vae/diffusion_pytorch_model.safetensors', 1 * go),
        ])
        self.assertEqual(r['components'], {'text_encoder': 11.0, 'transformer': 10.0, 'vae': 1.0})
        self.assertEqual(r['total_gb'], 22.0)      # plein GPU : tout coexiste
        self.assertEqual(r['largest_gb'], 11.0)    # dechargement : un composant a la fois
        self.assertEqual(r['source'], 'repo')      # borne superieure : rien ne restreint
        self.assertNotIn('variants', r)

    def test_a_declared_composition_decides_the_roles_and_the_selection(self):
        """Un depot est un CATALOGUE de fichiers, pas un modele : mesure du 19/09,
        `Lightricks/LTX-Video` pese 173,8 Go sur sa carte HF (toutes les versions 0.9.x cote a
        cote). Ce qu'on pese doit etre ce que le chargeur TIRE — donc l'anatomie DECLAREE
        (`AIModel.composition`), la meme que `patterns_from_composition` transforme en
        `allow_patterns`. Une declaration, deux lectures."""
        from .services.model_installer import components_of_files, patterns_from_composition
        go = 1024 ** 3
        files = [('model.safetensors', 3 * go),
                 ('speech_tokenizer/model.safetensors', 1 * go),
                 ('ltx-video-0.9.0.safetensors', 40 * go),        # version voisine, pas la notre
                 ('README.md', 400)]
        compo = {'components': [{'role': 'acoustic_model', 'pattern': 'model.safetensors'},
                                {'role': 'speech_tokenizer', 'pattern': 'speech_tokenizer/*'}],
                 'runtime': {'engine': 'qwen3-tts'}}
        r = components_of_files(files, composition=compo)
        self.assertEqual(r['components'], {'acoustic_model': 3.0, 'speech_tokenizer': 1.0})
        self.assertEqual(r['total_gb'], 4.0)       # les 40 Go voisins n'en font PAS partie
        self.assertEqual(r['source'], 'declared')
        # la meme declaration sert deja a l'installation : les deux lectures ne divergent pas
        self.assertIn('model.safetensors', patterns_from_composition(compo))
        # Sans declaration : l'heuristique garde UN jeu par role — ici le plus lourd des deux
        # jeux racine (40 Go), l'autre passant en `variants`. Elle ne les additionne donc pas
        # (44), mais elle designe la mauvaise version : c'est bien une BORNE, pas une empreinte.
        upper_bound = components_of_files(files)
        self.assertEqual(upper_bound['components'], {'model': 40.0, 'speech_tokenizer': 1.0})
        self.assertEqual(upper_bound['total_gb'], 41.0)
        self.assertEqual(upper_bound['variants'], {'model': 3.0})  # le vrai modele, ecarte a tort
        self.assertEqual(upper_bound['source'], 'repo')
        # une restriction explicite du descripteur vaut aussi selection
        restricted = components_of_files(files, allow_patterns=['speech_tokenizer/*'])
        self.assertEqual(restricted['components'], {'speech_tokenizer': 1.0})
        self.assertEqual(restricted['source'], 'allow_patterns')

    def test_a_quantized_variant_is_not_summed_with_the_full_one(self):
        """Sommer une variante fp8 avec sa version pleine compterait deux fois les memes
        tenseurs — mais un depot ENTIEREMENT quantise pese bien ce qu'il pese."""
        from .services.model_installer import components_of_files
        go = 1024 ** 3
        mixed = components_of_files([('transformer/model.safetensors', 10 * go),
                                     ('transformer/model.fp8.safetensors', 5 * go)])
        self.assertEqual(mixed['components'], {'transformer': 10.0})
        self.assertEqual(mixed['variants'], {'transformer': 5.0})
        only_fp8 = components_of_files([('transformer/model.fp8.safetensors', 5 * go)])
        self.assertEqual(only_fp8['components'], {'transformer': 5.0})
        self.assertNotIn('variants', only_fp8)

    def test_components_say_nothing_rather_than_zero(self):
        """Un inventaire sans tailles rend `{}` : `0.0` se lirait « ca ne pese rien »."""
        from .services.model_installer import components_of_files
        self.assertEqual(components_of_files(['transformer/model.safetensors']), {})
        self.assertEqual(components_of_files([('transformer/model.safetensors', 0)]), {})
        self.assertEqual(components_of_files(None), {})
        # un modele monobloc : les poids sont a la racine, somme et plus gros se confondent
        solo = components_of_files([('model.safetensors', 2 * 1024 ** 3)])
        self.assertEqual(solo['components'], {'model': 2.0})
        self.assertEqual((solo['total_gb'], solo['largest_gb'], solo['source']),
                         (2.0, 2.0, 'repo'))
        # les FICHIERS retenus voyagent avec le chiffre : le lecteur d'en-têtes safetensors en a
        # besoin pour le pic par PRÉCISION, et il ne doit pas refaire le tri des jeux
        self.assertEqual(solo['files'], {'model': [('model.safetensors', 2 * 1024 ** 3)]})

    def test_the_component_door_dispatches_by_kind_like_its_twin(self):
        """`components_for_spec` est le jumeau de `weight_for_spec` : meme descripteur, meme
        dispatch. Ollama/YOLO ne livrent pas de composition — un seul composant, dit
        explicitement, jamais `{}` (l'appelant doit pouvoir distinguer « indivisible » de
        « inconnu »)."""
        from .services import model_installer as mi
        with patch.object(mi, 'weight_for_spec', return_value=4.7):
            r = mi.components_for_spec({'kind': 'ollama', 'ref': 'qwen3:8b'})
        self.assertEqual(r, {'components': {'model': 4.7}, 'total_gb': 4.7, 'largest_gb': 4.7,
                             'source': 'registry'})
        with patch.object(mi, 'weight_for_spec', return_value=None):
            self.assertEqual(mi.components_for_spec({'kind': 'yolo', 'ref': 'yolo11n.pt'}), {})
        self.assertEqual(mi.components_for_spec({'kind': 'hf', 'ref': ''}), {})
        # `files=` : un inventaire deja releve ne se re-telecharge pas (aucun mock reseau ici)
        door_with_files = mi.components_for_spec(
            {'kind': 'hf', 'ref': 'org/x'}, files=[('vae/model.safetensors', 1024 ** 3)])
        self.assertEqual(door_with_files['components'], {'vae': 1.0})
        self.assertEqual(door_with_files['source'], 'repo')
        self.assertIn('vae', door_with_files['files'])
        # et la restriction du descripteur voyage avec lui, sans que l'appelant la repasse
        door = mi.components_for_spec(
            {'kind': 'hf', 'ref': 'org/x', 'allow_patterns': ['vae/*']},
            files=[('vae/model.safetensors', 1024 ** 3), ('dit/model.safetensors', 90 * 1024 ** 3)])
        self.assertEqual(door['components'], {'vae': 1.0})
        self.assertEqual(door['source'], 'allow_patterns')

    def test_a_component_living_in_another_repo_is_weighed_too(self):
        """Le second bras du schéma `composition` : `{'role': …, 'repo': 'org/nom'}`. Cinq
        déclarations du catalogue s'en servent (pyannote-diarization, codeformer, les 3
        DeepFace) et rendaient « aucun poids » — leur dépôt principal ne porte que des
        fichiers de configuration. Une composition VALIDE et un relevé VIDE."""
        from .services import model_installer as mi
        compo = {'components': [{'role': 'segmentation', 'repo': 'org/segmentation-3.0'},
                                {'role': 'embedding', 'repo': 'org/wespeaker-resnet34'}],
                 'runtime': {'engine': 'pyannote'}}
        with patch('wama.model_manager.services.prospector._repo_weight_gb',
                   side_effect=[0.006, 0.026]):
            r = mi.components_for_spec({'kind': 'hf', 'ref': 'org/diarization', 'composition': compo},
                                       files=[('config.yaml', 900)])
        self.assertEqual(r['components'], {'embedding': 0.026, 'segmentation': 0.006})
        self.assertEqual(r['total_gb'], 0.032)
        self.assertEqual(r['largest_gb'], 0.026)
        self.assertEqual(r['source'], 'declared')

    def test_an_unweighable_sibling_repo_is_NAMED_never_counted_as_zero(self):
        """Un dépôt gated (pyannote l'est), injoignable, ou pas HF du tout (TripoSR déclare une
        URL GitHub) laisse un rôle SANS poids. `unresolved` le NOMME, et aucun `total_gb` n'est
        rendu : une somme incomplète prise pour une empreinte est pire qu'un trou déclaré."""
        from .services import model_installer as mi
        compo = {'components': [{'role': 'code',
                                 'repo': 'https://github.com/VAST-AI-Research/TripoSR'}]}
        r = mi.components_for_spec({'kind': 'hf', 'ref': 'stabilityai/TripoSR',
                                    'composition': compo}, files=[('README.md', 100)])
        self.assertEqual(r['unresolved'], ['code'])
        self.assertIsNone(r.get('total_gb'), "un total incomplet ne doit pas être inventé")
        self.assertNotIn('components', r)
        # un modèle SANS dépôt principal existe (les 3 DeepFace n'ont pas de `hf_id`) :
        # son anatomie est entièrement déportée, et la porte doit quand même répondre
        with patch('wama.model_manager.services.prospector._repo_weight_gb', return_value=1.0):
            sans_depot = mi.components_for_spec({'kind': 'hf', 'ref': '', 'composition': {
                'components': [{'role': 'age', 'repo': 'org/deepface_models'}]}})
        self.assertEqual(sans_depot['components'], {'age': 1.0})

    def test_an_unreachable_repo_is_not_a_model_that_weighs_nothing(self):
        """`_siblings` distingue la PANNE (None) du dépôt VIDE ([]) ; la porte doit propager
        cette distinction. Vécu le 19/09 sur ma propre contre-épreuve : une salve d'appels HF a
        échoué en silence et 8 déclarations VÉRIFIÉES ont été rapportées « motif sans fichier ».
        *Un relevé qui dépend du réseau doit dire quand le réseau a manqué.*"""
        from .services import model_installer as mi
        with patch('wama.model_manager.services.prospector._siblings', return_value=None):
            panne = mi.components_for_spec({'kind': 'hf', 'ref': 'org/x'})
        self.assertEqual(panne, {'unreachable': 'org/x'})
        self.assertIsNone(panne.get('total_gb'))
        with patch('wama.model_manager.services.prospector._siblings', return_value=[]):
            vide = mi.components_for_spec({'kind': 'hf', 'ref': 'org/x'})
        self.assertEqual(vide, {}, "un dépôt VIDE est un fait, pas une panne")
        # ⚠ et un dépôt principal injoignable ne doit pas MASQUER les composants frères qui,
        # eux, se pèsent : vécu sur `avatarizer:codeformer`, ma branche `unreachable` rendait la
        # main trop tôt et le relevé perdait ce qu'il savait.
        compo = {'components': [{'role': 'tokenizer', 'repo': 'org/tokenizer'}]}
        with patch('wama.model_manager.services.prospector._siblings', return_value=None), \
                patch.object(mi, '_local_repo_weight_gb', return_value=0.8):
            partiel = mi.components_for_spec({'kind': 'hf', 'ref': 'org/x', 'composition': compo})
        self.assertEqual(partiel['components'], {'tokenizer': 0.8})
        self.assertEqual(partiel['unreachable'], 'org/x',
                         "le total est incomplet du dépôt principal : il faut le DIRE")

    def test_onnx_counts_as_weight_because_for_some_models_it_IS_the_model(self):
        """`.onnx` manquait aux extensions de poids : la composition de Kokoro-ONNX déclarait
        son rôle principal sur `onnx/model.onnx` et ce rôle pesait ZÉRO. Une extension absente
        d'une liste ne produit pas d'erreur, elle produit un zéro."""
        from .services.prospector import _WEIGHT_EXTS
        from .services.model_installer import components_of_files
        self.assertIn('.onnx', _WEIGHT_EXTS)
        compo = {'components': [{'role': 'acoustic_model', 'pattern': 'onnx/model.onnx'},
                                {'role': 'voices', 'pattern': 'voices/*.bin'}]}
        r = components_of_files([('onnx/model.onnx', 325 * 1024 ** 2),
                                 ('voices/af.bin', 13 * 1024 ** 2)], composition=compo)
        self.assertEqual(sorted(r['components']), ['acoustic_model', 'voices'])
        self.assertGreater(r['components']['acoustic_model'], 0.3)

    def test_le_pull_hf_transmet_les_doublons_en_ignore_patterns_sauf_si_le_spec_restreint(self):
        """`pull_hf_model` passe les jumeaux à `snapshot_download(ignore_patterns=…)` ; un spec
        qui restreint déjà (`allow_patterns`, ex. `.nemo` seul) ne déclenche pas le listing."""
        from .services import model_installer as mi
        vus = {}

        def faux_snapshot(repo_id, cache_dir, allow_patterns=None, ignore_patterns=None):
            vus.update(allow=allow_patterns, ignore=ignore_patterns)
            return '/faux/chemin'
        with patch('huggingface_hub.snapshot_download', side_effect=faux_snapshot), \
                patch.object(mi, 'format_duplicates', return_value=['pytorch_model.bin']) as dd:
            r = mi.pull_hf_model('org/x', 'vision', family='x')
            self.assertTrue(r['ok'])
            self.assertEqual(vus['ignore'], ['pytorch_model.bin'])
            self.assertEqual(r['ignores'], ['pytorch_model.bin'])
            dd.reset_mock()
            mi.pull_hf_model('org/x', 'speech', family='x', allow_patterns=['*.nemo'])
            dd.assert_not_called()
            self.assertIsNone(vus['ignore'])
            self.assertEqual(vus['allow'], ['*.nemo'])

    def test_un_candidat_ollama_porte_sa_tache(self):
        """26 propositions Ollama sans `task` : chaque RÔLE déclare désormais la sienne."""
        from .models import ModelTask
        from .services.prospect_ollama import ROLES
        connues = {t.value for t in ModelTask}
        for nom, role in ROLES.items():
            with self.subTest(role=nom):
                self.assertIn(role.get('task'), connues)


class LicenceHeriteeTest(TestCase):
    """
    2026-09-02 (Fabien : « H3 dit UE EXCLUE, pas H3-Turbo — manque ou permission ? »). Un
    manque : le dérivé se tagge `apache-2.0` (SPDX permissif → la garde rend None) alors que
    sa carte déclare `base_model: MiniMaxAI/MiniMax-H3`, dont la licence exclut l'UE. Un
    « Model Derivative » reste soumis à l'accord amont : le verdict s'HÉRITE, en le disant.
    """

    def _texte(self, hf_id, lid):
        if hf_id == 'MiniMaxAI/MiniMax-H3':
            return {'verdict': 'exclusion_ue', 'label': 'UE EXCLUE par la licence',
                    'detail': '« excluded territories means the european union… »'}
        if hf_id == 'Org/Flou':
            return {'verdict': 'a_verifier', 'label': 'licence à vérifier', 'detail': 'sans LICENSE'}
        return None

    def test_un_derive_permissif_herite_du_verdict_territorial_de_sa_base(self):
        from .services import prospector as p
        with patch.object(p, '_analyze_license_text', side_effect=self._texte):
            v = p.analyze_license('lightx2v/Minimax-h3-Turbo', 'apache-2.0', ['MiniMaxAI/MiniMax-H3'])
        self.assertEqual(v['verdict'], 'exclusion_ue')
        self.assertEqual(v['herite_de'], 'MiniMaxAI/MiniMax-H3')
        self.assertIn('modèle de base', v['label'])
        self.assertIn('Model Derivative', v['detail'])
        # `base_model` en chaîne (cartes FastVideo) : même résultat
        with patch.object(p, '_analyze_license_text', side_effect=self._texte):
            v2 = p.analyze_license('FastVideo/FastH3', 'apache-2.0', 'MiniMaxAI/MiniMax-H3')
        self.assertEqual(v2['verdict'], 'exclusion_ue')

    def test_sans_base_declaree_ou_avec_une_base_saine_rien_ne_change(self):
        from .services import prospector as p
        with patch.object(p, '_analyze_license_text', side_effect=self._texte):
            self.assertIsNone(p.analyze_license('Qwen/Qwen3-TTS', 'apache-2.0', None))
            self.assertIsNone(p.analyze_license('Distil/Whisper', 'mit', ['openai/whisper-large-v3']))
            # Une base seulement « à vérifier » n'est pas héritée : rien de territorial n'est établi
            self.assertIsNone(p.analyze_license('Org/Derive', 'apache-2.0', ['Org/Flou']))
            # Un verdict territorial PROPRE prime sur l'héritage
            v = p.analyze_license('MiniMaxAI/MiniMax-H3', 'other', ['MiniMaxAI/MiniMax-H3'])
        self.assertEqual(v['verdict'], 'exclusion_ue')
        self.assertNotIn('herite_de', v)


class TacheHeriteeALInstallationTest(TestCase):
    """
    2026-09-02, première installation par le mécanisme : `table-transformer-detection` est
    arrivé au catalogue SANS tâche alors que son candidat portait `detect` — le balayage
    générique d'un snapshot HF ne sait pas ce qu'un modèle fait. Le spec porte la tâche, la
    provenance la pose ; une tâche déjà établie par la découverte n'est jamais écrasée.

    Depuis le 2026-09-18 la tâche entre PAR LE MANIFESTE (`set_identity`), donc avant sa
    projection et son export au corpus. Mesuré avant : 8 modèles installés depuis le 02/09
    n'avaient que `task` — la tâche, écrite en base APRÈS l'export, fermait la porte des
    capacités derrière elle, et le manifeste du corpus naissait sans tâche.
    """

    IDENTITE = {'hf_id': 'Org/Detecteur', 'platform_ref': 'huggingface:Org/Detecteur'}

    def _vierge(self):
        return AIModel.objects.create(
            model_key='huggingface:Org/Detecteur', name='Detecteur', model_type='vision',
            source='huggingface', is_downloaded=True, hf_id='Org/Detecteur', capabilities={})

    def test_la_tache_du_spec_entre_par_le_manifeste_avant_l_export(self):
        """La chaîne RÉELLE (extract → validate → write_back) tourne ; seuls le réseau (identité
        HF) et l'écriture du corpus sont remplacés — et l'export voit la tâche déjà posée."""
        from .services import provenance as pv
        vierge = self._vierge()
        vues_a_l_export = []

        def _export(*args, **kwargs):
            vues_a_l_export.append(AIModel.objects.get(pk=vierge.pk).capabilities.get('task'))

        spec = {'kind': 'hf', 'ref': 'Org/Detecteur', 'category': 'vision', 'task': 'detect'}
        with patch.object(pv, 'identity_for_spec', return_value=dict(self.IDENTITE)), \
                patch('django.core.management.call_command', side_effect=_export):
            r = pv.record_after_install(spec, ['huggingface:Org/Detecteur'])
        vierge.refresh_from_db()
        self.assertEqual(vierge.capabilities.get('task'), 'detect')
        self.assertEqual(r.get('task'), 'detect')
        self.assertIn('capabilities.task', r['models'][0]['posed'])
        self.assertEqual(vues_a_l_export, ['detect'],
                         "le corpus doit être écrit APRÈS la pose de la tâche, pas avant")

    def test_un_spec_sans_tache_ne_touche_a_rien(self):
        """Ancien candidat, ou installation par l'assistant sans tâche : rien n'est inventé."""
        from .services import provenance as pv
        vierge = self._vierge()
        with patch.object(pv, 'identity_for_spec', return_value=dict(self.IDENTITE)), \
                patch('django.core.management.call_command'):
            r = pv.record_after_install({'kind': 'hf', 'ref': 'Org/Detecteur'},
                                        ['huggingface:Org/Detecteur'])
        vierge.refresh_from_db()
        self.assertNotIn('task', r)
        self.assertNotIn('task', vierge.capabilities)

    def test_une_tache_etablie_n_est_jamais_ecrasee_par_celle_du_spec(self):
        from .services import provenance as pv
        etabli = AIModel.objects.create(
            model_key='huggingface:Org/Segmenteur', name='Segmenteur', model_type='vision',
            source='huggingface', is_downloaded=True, hf_id='Org/Segmenteur',
            capabilities={'task': 'segment'})
        with patch.object(pv, 'identity_for_spec', return_value={'hf_id': 'Org/Segmenteur'}), \
                patch('django.core.management.call_command'):
            r = pv.record_after_install({'kind': 'hf', 'ref': 'Org/Segmenteur', 'task': 'detect'},
                                        ['huggingface:Org/Segmenteur'])
        etabli.refresh_from_db()
        self.assertEqual(etabli.capabilities.get('task'), 'segment')
        self.assertNotIn('capabilities.task', r['models'][0].get('posed', ()))


class FusionDesCapacitesTest(TestCase):
    """`write_back_model` projette `capabilities` par FUSION clé par clé (2026-09-18).

    Avant : « tout ou rien », sur une ligne orpheline ENCORE VIDE seulement. Une porte à usage
    unique : la première clé posée (la tâche du spec) interdisait toutes les suivantes.
    """

    def _projeter(self, cle, caps):
        from wama.common.manifests.builtin.model import write_back_model
        return write_back_model({'manifest_kind': 'model', 'key': cle,
                                 'body': {'capabilities': caps}}, apply=True)

    def test_sur_une_ligne_orpheline_le_manifeste_tranche_cle_par_cle(self):
        """La tâche déjà posée n'interdit plus les modalités ; et une clé que le manifeste
        déclare autrement est corrigée — personne d'autre ne produit ces capacités."""
        AIModel.objects.create(model_key='huggingface:Org/Orphelin', name='O', model_type='vision',
                               source='huggingface', capabilities={'task': 'detect',
                                                                   'classes': ['face']})
        r = self._projeter('huggingface:Org/Orphelin',
                           {'task': 'segment', 'modalities': ['image']})
        m = AIModel.objects.get(model_key='huggingface:Org/Orphelin')
        self.assertEqual(m.capabilities, {'task': 'segment', 'modalities': ['image'],
                                          'classes': ['face']})
        self.assertIn('capabilities', r['changed'])

    def test_sur_une_ligne_servie_par_une_app_le_manifeste_comble_sans_contester(self):
        """La découverte lit les flags sur la classe de backend : sa valeur reste, le manifeste
        n'ajoute que ce qu'elle n'a pas écrit (cas Audio8 : `supports_cloning=False` déclaré
        par le moteur, `True` dans un manifeste antérieur — le moteur a raison)."""
        AIModel.objects.create(model_key='synthesizer:servi', name='S', model_type='speech',
                               source='synthesizer', backend_ref='synthesizer',
                               capabilities={'task': 'text-to-speech', 'supports_cloning': False})
        self._projeter('synthesizer:servi', {'supports_cloning': True, 'languages': ['fr']})
        m = AIModel.objects.get(model_key='synthesizer:servi')
        self.assertEqual(m.capabilities, {'task': 'text-to-speech', 'supports_cloning': False,
                                          'languages': ['fr']})

    def test_un_manifeste_muet_ne_touche_pas_aux_capacites(self):
        AIModel.objects.create(model_key='huggingface:Org/Muet', name='M', model_type='vision',
                               source='huggingface', capabilities={'task': 'detect'})
        r = self._projeter('huggingface:Org/Muet', {})
        self.assertIn('capabilities', r['preserved'])
        self.assertNotIn('capabilities', r['changed'])
        self.assertEqual(AIModel.objects.get(model_key='huggingface:Org/Muet').capabilities,
                         {'task': 'detect'})


class ProvenanceSurTousLesCheminsTest(TestCase):
    """Deux chemins d'installation sautaient la provenance (mesuré 2026-09-18) : la branche
    Ollama de `install_candidate` (aucune des 9 lignes `ollama:*` n'avait de manifeste) et le
    raccourci YOLO de la vue. Ils passent désormais par le corps unique `record_provenance`.
    """

    def _sync(self, *cles):
        from .services.model_sync import SyncResult
        return SyncResult(success=True, added=len(cles), added_keys=list(cles))

    def test_un_candidat_ollama_installe_recoit_sa_provenance_et_sa_tache(self):
        """La TÂCHE du candidat voyage avec le descripteur (2026-09-19) : la découverte par
        rôle la connaît, la découverte générique d'un tag Ollama ne la devine pas."""
        from .services import model_installer as mi
        cand = AIModel.objects.create(
            model_key='proposed:ollama:nouveau:latest', name='nouveau:latest', model_type='llm',
            source='ollama', is_proposed=True, proposal_kind='new',
            capabilities={'task': 'text-generation'})
        with patch.object(mi, 'pull_ollama_model', return_value={'ok': True}), \
                patch.object(mi, 'register_after_install',
                             return_value=self._sync('ollama:nouveau:latest')), \
                patch('wama.model_manager.services.provenance.record_after_install',
                      return_value={'identity': {}}) as prov:
            res = mi.install_candidate(cand)
        self.assertTrue(res['ok'])
        prov.assert_called_once_with({'kind': 'ollama', 'ref': 'nouveau:latest',
                                      'task': 'text-generation'},
                                     ['ollama:nouveau:latest'])
        self.assertFalse(AIModel.objects.filter(pk=cand.pk).exists(), "candidat retiré")

    def test_install_from_spec_passe_par_le_meme_corps(self):
        from .services import model_installer as mi
        with patch.object(mi, 'pull_hf_model', return_value={'ok': True, 'path': '/p'}), \
                patch.object(mi, 'register_after_install',
                             return_value=self._sync('huggingface:Org/X')), \
                patch('wama.model_manager.services.provenance.record_after_install',
                      return_value={'identity': {'hf_id': 'Org/X'}}) as prov:
            res = mi.install_from_spec({'kind': 'hf', 'ref': 'Org/X', 'category': 'vision',
                                        'task': 'detect'})
        self.assertTrue(res['ok'])
        self.assertEqual(res['provenance'], {'identity': {'hf_id': 'Org/X'}})
        prov.assert_called_once_with({'kind': 'hf', 'ref': 'Org/X', 'category': 'vision',
                                      'task': 'detect'}, ['huggingface:Org/X'])

    def test_une_provenance_manquee_ne_fait_pas_echouer_l_installation(self):
        from .services import model_installer as mi
        with patch.object(mi, 'pull_hf_model', return_value={'ok': True}), \
                patch.object(mi, 'register_after_install', side_effect=RuntimeError('base')):
            res = mi.install_from_spec({'kind': 'hf', 'ref': 'Org/Y', 'category': 'vision'})
        self.assertTrue(res['ok'])
        self.assertNotIn('provenance', res)


class RouteUniqueDInstallationTest(TestCase):
    """
    UNE seule route d'installation depuis l'extérieur (alignement du 2026-09-19).

    Mesure qui l'a motivée : l'endpoint avait DEUX entrées nues — un `spec` complet et un nom
    de poids YOLO — qui installaient en SYNCHRONE, sans candidat et sans garde d'espace,
    parce que la garde vivait dans la vue. Aucune des deux n'avait d'appelant (les trois
    `fetch` de la page envoient `model_id`, `model_id+force` ou `catalog_key`), mais l'outil
    de l'assistant allait prendre le même chemin — et sauter la même garde.
    """

    def _admin(self, nom):
        from django.contrib.auth import get_user_model
        admin = get_user_model().objects.create_user(nom, password='x', is_superuser=True)
        self.client.force_login(admin)
        return admin

    def _poster(self, charge):
        import json as _json

        from django.urls import reverse
        return self.client.post(reverse('model_manager:api_prospect_install'),
                                data=_json.dumps(charge), content_type='application/json')

    def _candidat_hf(self, **extra):
        return AIModel.objects.create(
            model_key='proposed:hf:Org/Petit', name='Petit', model_type='vision',
            source='huggingface', is_proposed=True, proposal_kind='new', hf_id='Org/Petit',
            disk_gb=0.4, extra_info={'prospect': {
                'spec': {'kind': 'hf', 'ref': 'Org/Petit', 'category': 'vision',
                         'task': 'detect'}}}, **extra)

    def test_un_descripteur_nu_ne_s_installe_plus(self):
        """L'entrée `spec` installait sans candidat, sans garde et en synchrone."""
        self._admin('admin_spec')
        with patch('wama.model_manager.services.model_installer.install_from_spec') as inst:
            rep = self._poster({'spec': {'kind': 'hf', 'ref': 'Org/X', 'category': 'vision'}})
        self.assertEqual(rep.status_code, 400, rep.content)
        inst.assert_not_called()

    def test_un_candidat_s_installe_par_sa_cle_en_tache_de_fond(self):
        from .services import model_installer as mi
        cand = self._candidat_hf()
        with patch.object(mi, 'disk_space_guard', return_value=None) as garde, \
                patch('wama.common.utils.task_progress.progression_en_cours',
                      return_value=None), \
                patch('wama.model_manager.tasks.install_proposed_task.delay') as delay:
            delay.return_value = type('T', (), {'id': 'tid-1'})()
            res = mi.request_install(cand.model_key)
        self.assertEqual((res['ok'], res['started'], res['task_id']), (True, True, 'tid-1'))
        delay.assert_called_once_with(cand.model_key)
        # Le poids relevé à la prospection sert la garde : pas d'interrogation du registre
        # Ollama pour un dépôt HuggingFace, qu'il ne connaît pas.
        self.assertEqual(garde.call_args.kwargs['needed_gb'], 0.4)

    def test_la_garde_d_espace_refuse_avant_d_engager_le_telechargement(self):
        from .services import model_installer as mi
        cand = self._candidat_hf()
        refus = {'success': False, 'error': 'Espace insuffisant', 'force_possible': True,
                 'reason': 'espace_insuffisant', 'needed_gb': 50.0}
        with patch.object(mi, 'disk_space_guard', return_value=refus), \
                patch('wama.model_manager.tasks.install_proposed_task.delay') as delay:
            res = mi.request_install(cand.model_key)
        self.assertEqual(res['reason'], 'insufficient_storage')
        self.assertIn('replaces', res['blocked'])
        delay.assert_not_called()

    def test_la_vue_rend_le_refus_d_espace_en_507_forcable(self):
        from .services import model_installer as mi
        cand = self._candidat_hf()
        refus = {'success': False, 'error': 'Espace insuffisant', 'force_possible': True}
        with patch.object(mi, 'disk_space_guard', return_value=refus):
            self._admin('admin_507')
            rep = self._poster({'model_id': cand.model_key})
        self.assertEqual(rep.status_code, 507, rep.content)
        self.assertTrue(rep.json()['force_possible'])

    def test_un_nom_de_poids_yolo_devient_un_candidat_puis_suit_la_meme_route(self):
        """Le raccourci YOLO n'installe plus en direct : il PROPOSE, puis installe le candidat
        — donc avec garde d'espace, tâche de fond et provenance, comme tout le reste."""
        from .services import model_installer as mi
        self._admin('admin_yolo')
        with patch.object(mi, 'weight_for_spec', return_value=0.02), \
                patch.object(mi, 'disk_space_guard', return_value=None), \
                patch('wama.common.utils.task_progress.progression_en_cours',
                      return_value=None), \
                patch('wama.model_manager.tasks.install_proposed_task.delay') as delay:
            delay.return_value = type('T', (), {'id': 'tid-yolo'})()
            rep = self._poster({'source': 'yolo', 'name': 'yolo26s-seg'})
        self.assertEqual(rep.status_code, 200, rep.content)
        cand = AIModel.objects.get(model_key='proposed:yolo:yolo26s-seg')
        # La tâche se déduit du suffixe du nom — même fait que le sous-dossier d'installation.
        self.assertEqual(cand.capabilities['task'], 'segment')
        self.assertEqual(cand.platform_ref, 'github:ultralytics/assets:yolo26s-seg')
        self.assertEqual(cand.extra_info['prospect']['spec'],
                         {'kind': 'yolo', 'ref': 'yolo26s-seg', 'task': 'segment',
                          'note': 'installation VISION par nom'})
        delay.assert_called_once_with('proposed:yolo:yolo26s-seg')

    def test_un_nom_de_poids_yolo_invente_est_refuse_sans_rien_ecrire(self):
        self._admin('admin_yolo_faux')
        rep = self._poster({'source': 'yolo', 'name': 'https://ailleurs/poids.pt'})
        self.assertEqual(rep.status_code, 400, rep.content)
        self.assertFalse(AIModel.objects.filter(is_proposed=True, source='yolo').exists())

    def test_weight_is_asked_of_the_descriptor_like_identity(self):
        """
        « Combien pèse ce que je vais tirer ? » a UNE réponse, dispatchée par `kind` —
        `weight_for_spec`, jumeau de `provenance.identity_for_spec`.

        Remarque de Fabien (2026-09-19) : « pourquoi une fonction spécifique à YOLO ? ». La
        réponse existait en TROIS exemplaires (`_repo_weight_gb` HF, `ollama_registry.size_gb`,
        plus un relevé YOLO que je venais d'ajouter en quatrième), chacun appelé à la main par
        un appelant qui n'en connaissait qu'un. *Trois réponses à une même question ne divergent
        pas bruyamment : elles se répartissent entre des appelants qui s'ignorent.*
        """
        from .services import model_installer as mi
        with patch('wama.model_manager.services.prospector._repo_weight_gb',
                   return_value=12.5) as hf:
            self.assertEqual(mi.weight_for_spec({'kind': 'hf', 'ref': 'Org/X'}), 12.5)
        hf.assert_called_once_with('Org/X')
        with patch('wama.model_manager.services.ollama_registry.size_gb',
                   return_value=4.2) as ollama:
            self.assertEqual(mi.weight_for_spec({'kind': 'ollama', 'ref': 'qwen3.6:35b'}), 4.2)
        ollama.assert_called_once_with('qwen3.6', '35b')
        with patch.object(mi, '_yolo_asset_gb', return_value=0.02) as yolo:
            self.assertEqual(mi.weight_for_spec({'kind': 'yolo', 'ref': 'yolo26s-seg'}), 0.02)
        yolo.assert_called_once_with('yolo26s-seg')
        # Indéterminable = None, jamais une supposition : sur un volume à 96 %, une taille
        # optimiste remplit le disque (même contrat que `size_gb` et `_repo_weight_gb`).
        self.assertIsNone(mi.weight_for_spec({'kind': 'inconnu', 'ref': 'x'}))
        self.assertIsNone(mi.weight_for_spec({'kind': 'hf'}))
        self.assertIsNone(mi.weight_for_spec(None))

    def test_the_yolo_candidate_is_weighed_on_the_spec_it_carries(self):
        """Le spec écrit sur le candidat et celui qu'on pèse sont le MÊME objet : peser autre
        chose que ce qu'on va tirer est précisément ce que le descripteur évite."""
        from .services import model_installer as mi
        from .services.prospector import seed_yolo_candidate
        with patch.object(mi, 'weight_for_spec', return_value=0.021) as peser:
            pose = seed_yolo_candidate('yolo26s-seg')
        self.assertTrue(pose['ok'])
        cand = AIModel.objects.get(model_key=pose['model_key'])
        self.assertEqual(peser.call_args.args[0], cand.extra_info['prospect']['spec'])
        self.assertEqual(cand.disk_gb, 0.021)

    def test_une_cle_inconnue_ne_s_installe_pas(self):
        from .services import model_installer as mi
        res = mi.request_install('proposed:hf:Org/Fantome')
        self.assertEqual(res['reason'], 'not_found')

    def test_un_modele_deja_telecharge_ne_se_reinstalle_pas(self):
        from .services import model_installer as mi
        AIModel.objects.create(model_key='imager:deja', name='Déjà', model_type='diffusion',
                               source='imager', is_downloaded=True)
        self.assertEqual(mi.request_install('imager:deja')['reason'], 'already_downloaded')

    def test_un_re_clic_rejoint_l_installation_en_cours(self):
        from .services import model_installer as mi
        cand = self._candidat_hf()
        with patch.object(mi, 'disk_space_guard', return_value=None), \
                patch('wama.common.utils.task_progress.progression_en_cours',
                      return_value={'state': 'RUNNING', 'status': 'téléchargement…'}), \
                patch('wama.model_manager.tasks.install_proposed_task.delay') as delay:
            res = mi.request_install(cand.model_key)
        self.assertTrue(res['already_running'])
        delay.assert_not_called()

    def test_l_assistant_installe_par_le_meme_corps_que_le_bouton(self):
        """« L'assistant prend les mêmes verbes que le bouton » : un seul corps, donc une
        seule garde d'espace — un outil ne peut pas contourner ce que la vue applique."""
        from wama import tool_api
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user('demandeur', password='x')
        with patch('wama.model_manager.services.model_installer.request_install',
                   return_value={'ok': True, 'started': True, 'model_key': 'proposed:hf:Org/P',
                                 'task_id': 'tid-2'}) as req:
            out = tool_api.install_model(user, 'proposed:hf:Org/P')
        self.assertEqual(out, {'started': True, 'model_key': 'proposed:hf:Org/P',
                               'task_id': 'tid-2'})
        req.assert_called_once_with('proposed:hf:Org/P', force=False, variant_ref='',
                                    variant_file='')

    def test_l_assistant_rend_les_chiffres_du_refus_d_espace(self):
        from wama import tool_api
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user('demandeur2', password='x')
        blocked = {'success': False, 'error': 'Espace insuffisant', 'needed_gb': 50.0,
                   'free_gb': 12.0, 'after_gb': -38.0, 'margin_gb': 10.0,
                   'force_possible': True, 'replaces': None, 'reason': 'espace_insuffisant'}
        with patch('wama.model_manager.services.model_installer.request_install',
                   return_value={'ok': False, 'reason': 'insufficient_storage',
                                 'blocked': blocked}):
            out = tool_api.install_model(user, 'proposed:hf:Org/Gros')
        self.assertEqual(out['reason'], 'insufficient_storage')
        self.assertEqual((out['needed_gb'], out['free_gb']), (50.0, 12.0))
        self.assertTrue(out['force_possible'])

    def test_l_assistant_cherche_par_le_semeur_de_candidats(self):
        """`search_models` = le champ « Rechercher un modèle » de la page : il écrit des
        PROPOSITIONS, il n'installe rien."""
        from wama import tool_api
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user('chercheur', password='x')
        with patch('wama.model_manager.services.prospector.seed_hf_search',
                   return_value={'ok': True, 'query': 'kokoro', 'created': 2, 'updated': 0,
                                 'already': 1, 'skipped': 0, 'total': 2,
                                 'refs': ['a/b', 'c/d']}) as seed:
            out = tool_api.search_models(user, 'kokoro', limit=12, max_results=3)
        self.assertEqual(out['refs'], ['a/b', 'c/d'])
        self.assertNotIn('ok', out)
        seed.assert_called_once_with('kokoro', limit=12, max_retenus=3)

    def _manifeste_scout(self, **identite):
        return {'manifest_kind': 'model', 'key': 'huggingface:Org/Juge', 'name': 'Juge',
                'body': {'identity': {'source': 'huggingface', 'hf_id': 'Org/Juge',
                                      'model_type': 'speech', 'license': 'mit',
                                      **identite},
                         'resources': {'disk_gb': 1.3},
                         'capabilities': {'task': 'transcription',
                                          'languages': ['fr', 'en']},
                         'composition': {'components': [{'pattern': '*.safetensors'}]}}}

    def test_un_manifeste_de_scout_devient_un_candidat_installable(self):
        """Les capacités JUGÉES par le scout mouraient dans `outputs/` : elles vivent
        désormais sur le candidat, donc l'installation les retrouve."""
        from .services.prospector import seed_candidate_from_manifest
        pose = seed_candidate_from_manifest(self._manifeste_scout())
        self.assertTrue(pose['ok'])
        cand = AIModel.objects.get(model_key='proposed:hf:Org/Juge')
        self.assertTrue(cand.is_proposed)
        self.assertEqual(cand.capabilities['languages'], ['fr', 'en'])
        # Ce que la tâche implique est posé SANS écraser ce que le manifeste déclare.
        self.assertEqual(cand.capabilities['task'], 'transcription')
        self.assertIn('modalities', cand.capabilities)
        spec = cand.extra_info['prospect']['spec']
        self.assertEqual((spec['kind'], spec['ref'], spec['category'], spec['task']),
                         ('hf', 'Org/Juge', 'speech', 'transcription'))
        # La COMPOSITION voyage : c'est elle qui fait tirer le jeu de poids cohérent.
        self.assertEqual(spec['composition'],
                         {'components': [{'pattern': '*.safetensors'}]})
        self.assertEqual(cand.disk_gb, 1.3)

    def test_un_manifeste_sans_type_ne_fait_pas_de_candidat(self):
        """Sans `model_type`, le candidat n'aurait ni catégorie d'installation ni
        référentiel de concurrence : on refuse au lieu d'écrire une ligne boiteuse."""
        from .services.prospector import seed_candidate_from_manifest
        pose = seed_candidate_from_manifest(self._manifeste_scout(model_type=None))
        self.assertFalse(pose['ok'])
        self.assertFalse(AIModel.objects.filter(model_key='proposed:hf:Org/Juge').exists())

    def test_un_candidat_du_scout_s_installe_par_la_route_commune(self):
        """Bout en bout, sans LLM : manifeste jugé → candidat → `request_install`."""
        from .services import model_installer as mi
        from .services.prospector import seed_candidate_from_manifest
        pose = seed_candidate_from_manifest(self._manifeste_scout())
        with patch.object(mi, 'disk_space_guard', return_value=None), \
                patch('wama.common.utils.task_progress.progression_en_cours',
                      return_value=None), \
                patch('wama.model_manager.tasks.install_proposed_task.delay') as delay:
            delay.return_value = type('T', (), {'id': 'tid-3'})()
            res = mi.request_install(pose['model_key'])
        self.assertTrue(res['started'])
        delay.assert_called_once_with('proposed:hf:Org/Juge')

    def test_les_deux_verbes_de_modeles_sont_gardes_par_le_model_manager(self):
        """Ce sont les seuls outils qui écrivent côté modèles : ils suivent le gating de la
        page (développeurs/admins), pas celui des lectures transverses."""
        from wama.tool_api import TOOL_APP_OVERRIDE, TOOL_REGISTRY
        for nom in ('search_models', 'install_model'):
            self.assertIn(nom, TOOL_REGISTRY)
            self.assertEqual(TOOL_APP_OVERRIDE.get(nom), 'model_manager', nom)


class _SourcesFactices:
    """Sources de benchmark simulées — partagées par les classes de test ci-dessous."""

    def _sources(self, par_categorie):
        """Sources factices : AUCUN accès réseau, donc le lot d'entrées est connu.

        `par_categorie` = {catégorie de banc: [entrées]} — plusieurs catégories, parce qu'un
        modèle à plusieurs métiers doit être cherché dans plusieurs leaderboards.
        """
        from .services import benchmark_sync as bs

        def aa():
            return dict(par_categorie), {}

        def arena():
            raise bs.SourceUnavailable('arena non sollicitée par ce test')

        def open_asr():
            raise bs.SourceUnavailable('open asr non sollicité par ce test')

        def mteb():
            raise bs.SourceUnavailable('mteb non sollicité par ce test')

        # ⚠ TOUTE source du registre se patche ici : une source ajoutée à `SOURCES` sans
        # ligne ici irait au RÉSEAU depuis la suite (c'est ce que le 3ᵉ banc a failli faire).
        return patch.multiple(bs, load_aa=aa, load_arena=arena, load_open_asr=open_asr,
                              load_mteb=mteb)

    def _entree(self, nom, identite, valeur=42.0, echelle='aa_elo_text_to_image'):
        return {'name': nom, 'slug': nom.lower().replace(' ', '-'), 'identity': identite,
                'value': valeur, 'scale': echelle}


class ComptageDesBancsTest(_SourcesFactices, TestCase):
    """
    Le rapport de `sync_benchmarks` doit RENDRE COMPTE de chaque ligne examinée.

    Mesuré le 2026-09-01 sur le catalogue réel : le rapport annonçait « 10 appariés,
    17 sans banc » pour 159 lignes — 15 d'entre elles ne tombaient dans aucun compteur.
    *Un modèle qui disparaît du compte se lit « il n'y en a pas » alors qu'il dit
    « je n'ai pas su le nommer ».*
    """

    def test_un_alias_sans_candidat_ne_fait_pas_tomber_la_passe(self):
        """
        `idents` n'était affecté que dans la branche SANS alias : il fuyait d'une itération à
        l'autre, et un modèle à ALIAS placé EN PREMIER faisait tomber la passe entière en
        `NameError`. Ce modèle est ici le seul du catalogue, donc nécessairement le premier.
        """
        from .services import benchmark_sync as bs
        AIModel.objects.create(
            model_key='imager:fantome', name='Fantome', model_type='diffusion',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'})
        with self._sources({'text-to-image': [self._entree('Autre Chose', ('autre', (1,), None))]}), \
                patch.dict(bs.ALIAS, {'imager:fantome': 'slug-qui-n-existe-plus'}, clear=True):
            r = bs.synchronize(dry_run=True)
        # Un ALIAS est une confirmation HUMAINE : démentie par la source, elle se voit parmi
        # les non-appariés — jamais rangée comme une identité manquante.
        self.assertEqual(r['unmatched'], ['imager:fantome [text-to-image]'])
        self.assertEqual(r['without_identity'], [])

    def test_une_identite_illisible_est_comptee_et_distinguee_du_sans_banc(self):
        from .services import benchmark_sync as bs
        AIModel.objects.create(
            model_key='synthesizer:kokoro', name='Kokoro 82M', model_type='speech',
            source='synthesizer', is_downloaded=True,
            capabilities={'task': 'text-to-image'})   # catégorie OK, identité illisible
        with self._sources({'text-to-image': []}):
            r = bs.synchronize(dry_run=True)
        self.assertEqual(r['without_identity'], ['synthesizer:kokoro [text-to-image]'])
        self.assertEqual(r['unmatched'], [])

    def test_les_quatre_issues_couvrent_tout_le_catalogue_examine(self):
        """Somme des issues == lignes examinées. C'est CE contrôle qui manquait : sans lui,
        une cinquième issue ajoutée demain se perdrait de la même façon, en silence."""
        from .services import benchmark_sync as bs
        commun = dict(source='imager', is_downloaded=True, model_type='diffusion')
        AIModel.objects.create(model_key='imager:widget-2', name='Widget 2',
                               capabilities={'task': 'text-to-image'}, **commun)   # apparié
        AIModel.objects.create(model_key='imager:gadget-9', name='Gadget 9',
                               capabilities={'task': 'text-to-image'}, **commun)   # sans banc
        AIModel.objects.create(model_key='imager:kokoro', name='Kokoro',
                               capabilities={'task': 'text-to-image'}, **commun)   # sans identité
        AIModel.objects.create(model_key='imager:yolo', name='Yolo 11',
                               capabilities={'task': 'detect'}, **commun)          # hors catégorie
        with self._sources({'text-to-image': [self._entree('Widget 2', ('widget', (2,), None))]}):
            r = bs.synchronize(dry_run=True)
        self.assertEqual(len(r['matched']), 1)
        self.assertEqual(len(r['unmatched']), 1)
        self.assertEqual(len(r['without_identity']), 1)
        self.assertEqual(r['without_category'], 1)
        total = (len(r['matched']) + len(r['unmatched'])
                 + len(r['without_identity']) + r['without_category'])
        self.assertEqual(total, AIModel.objects.count())

    def test_un_modele_CLOUD_est_examine_bien_qu_il_ne_soit_pas_telecharge(self):
        """
        `is_downloaded=True` voulait dire « utilisable ici » — vrai tant que tout était local.
        Un modèle servi par une clé d'API n'a AUCUN poids sur cette machine : les 22 lignes
        cloud n'étaient ni appariées ni comptées, donc invisibles du rapport. Mesuré avant
        correction : 0/22 avec un banc, alors que ce sont les modèles les mieux couverts par
        les leaderboards publics (après : 14/22, dont 8 Claude et 6 Albert).

        *Une ligne exclue du QUERYSET ne disparaît pas d'un compteur : elle disparaît de la
        question.*
        """
        from .services import benchmark_sync as bs
        distant = AIModel.objects.create(
            model_key='anthropic:widget-2', name='Widget 2', model_type='llm',
            source='anthropic', execution='cloud', is_downloaded=False, is_available=True,
            capabilities={'task': 'text-generation', 'completion': True})
        with self._sources({'llm': [self._entree('Widget 2', ('widget', (2,), None))]}):
            r = bs.synchronize(dry_run=False)
        distant.refresh_from_db()
        self.assertIn('anthropic:widget-2', repr(r['matched']))
        self.assertIsNotNone(distant.benchmark_index)

    def test_un_modele_cloud_RETIRE_reste_hors_de_la_passe(self):
        """Une ligne que la source ne liste plus est MARQUÉE (`is_available=False`) et garde son
        historique : la noter reviendrait à classer un modèle qu'on ne peut plus appeler."""
        from .services import benchmark_sync as bs
        retire = AIModel.objects.create(
            model_key='anthropic:widget-1', name='Widget 1', model_type='llm',
            source='anthropic', execution='cloud', is_downloaded=False, is_available=False,
            capabilities={'task': 'text-generation', 'completion': True})
        with self._sources({'llm': [self._entree('Widget 1', ('widget', (1,), None))]}):
            r = bs.synchronize(dry_run=False)
        retire.refresh_from_db()
        self.assertEqual(r['matched'], [])
        self.assertIsNone(retire.benchmark_index)

    def test_le_dry_run_n_ecrit_jamais_l_indice(self):
        """Garde-fou du mode dry-run : le rapport se lit sans toucher au catalogue."""
        from .services import benchmark_sync as bs
        m = AIModel.objects.create(
            model_key='imager:widget-2', name='Widget 2', model_type='diffusion',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'})
        with self._sources({'text-to-image': [self._entree('Widget 2', ('widget', (2,), None))]}):
            bs.synchronize(dry_run=True)
        m.refresh_from_db()
        self.assertIsNone(m.benchmark_index)


class AppariementSansTailleTest(TestCase):
    """
    Quand NI le tiers NI nous ne publions de taille, ce sont les QUALIFICATIFS qui tranchent.

    Une garde binaire sur une question qui ne l'est pas se trompe dans les deux sens :
    refuser en bloc tuait « Mistral Medium 3.5 » (notre nom, à la lettre) ; accepter en bloc
    donnait à `qwen3-embedding:latest` l'indice de « Qwen3 Max » (mesuré le 2026-09-01).
    """

    def _compat(self, a, b, nom_local, nom_tiers):
        from .services.benchmark_sync import _compatible
        return _compatible(a, b, True, nom_local, nom_tiers)

    def test_un_nom_tiers_sans_mot_etranger_est_apparie(self):
        self.assertTrue(self._compat(('mistralmedium', (3, 5), None),
                                     ('mistralmedium', (3, 5), None),
                                     'mistral-medium-3.5:latest', 'Mistral Medium 3.5'))

    def test_un_qualificatif_etranger_cote_tiers_refuse_l_appariement(self):
        """LE faux appariement à ne jamais laisser passer : un modèle d'embedding n'est pas
        la variante frontière `Max`, et `_identity` ne voit pas la différence."""
        self.assertFalse(self._compat(('qwen', (3,), None), ('qwen', (3,), None),
                                      'qwen3-embedding:latest', 'Qwen3 Max'))

    def test_une_taille_d_un_seul_cote_refuse_toujours(self):
        """Le cas d'origine de la garde : un poids local de 4B face à une variante API sans
        taille publiée (`qwen3.5-max-preview`)."""
        self.assertFalse(self._compat(('qwen', (3, 5), 4.0), ('qwen', (3, 5), None),
                                      'qwen3.5:4b', 'Qwen3.5 Max Preview'))
        self.assertFalse(self._compat(('qwen', (3,), None), ('qwen', (3,), 80.0),
                                      'qwen3-coder:latest', 'Qwen3 Next 80B A3B Instruct'))

    def test_latest_n_est_pas_un_qualificatif(self):
        """`latest` est un pointeur de tag Ollama : sa présence de notre côté ne doit rien
        rendre incompatible, et son absence côté tiers ne doit rien refuser."""
        self.assertTrue(self._compat(('nemotron', (3, 5), None), ('nemotron', (3, 5), None),
                                     'nemotron-3.5-lightning:latest', 'Nemotron 3.5 Lightning'))

    def test_les_modalites_media_gardent_la_taille_optionnelle(self):
        from .services.benchmark_sync import _compatible
        self.assertTrue(_compatible(('hunyuanimage', (2, 1), None),
                                     ('hunyuanimage', (2, 1), None), False))


class RegistreDesSourcesTest(TestCase):
    """
    Ajouter une plateforme de banc doit couter UNE ENTREE, pas cinq endroits touches.

    Ce test EST le contrat d'evolutivite : il declare une troisieme source fictive et verifie
    qu'elle traverse toute la chaine — chargement, appariement, index, echelle nommee, meta,
    rang — sans qu'aucune ligne du moteur ne la connaisse.
    """

    def _source_fictive(self, priorite):
        return {'key': 'panel', 'label': 'Panel Fictif', 'priority': priorite,
                'source_name': 'panel', 'value': lambda e: e.get('note'),
                'scale': lambda e, cat: 'panel_note_' + cat,
                'meta': lambda retenu, cands: {'panel_nom': retenu['name']},
                'loader': lambda: ({'text-to-image': [
                    {'name': 'Widget 2', 'slug': 'widget-2', 'note': 7.5,
                     'identity': ('widget', (2,), None)},
                    {'name': 'Autre 1', 'slug': 'autre-1', 'note': 1.0,
                     'identity': ('autre', (1,), None)}]}, {})}

    def _modele(self):
        return AIModel.objects.create(
            model_key='imager:widget-2', name='Widget 2', model_type='diffusion',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'})

    def test_une_source_ajoutee_traverse_toute_la_chaine(self):
        from .services import benchmark_sync as bs
        m = self._modele()
        panel = self._source_fictive(priorite=3)
        with patch.object(bs, 'SOURCES_BY_PRIORITY', (panel,)):
            bs.synchronize(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 7.5)
        self.assertEqual(m.benchmark_meta['scale'], 'panel_note_text-to-image')
        self.assertEqual(m.benchmark_meta['source'], 'panel')
        self.assertEqual(m.benchmark_meta['panel_nom'], 'Widget 2')
        # Le rang se calcule sur la population de CETTE source, pas d'une autre.
        self.assertEqual(m.benchmark_meta['percentile_rank'], 50.0)
        self.assertEqual(m.benchmark_meta['population'], 2)
        # L'attribution est DERIVEE du registre : une source ajoutee s'y cite d'elle-meme.
        self.assertIn('Panel Fictif', m.benchmark_meta['attribution'])

    def test_c_est_la_PRIORITE_qui_decide_laquelle_porte_l_index(self):
        """Les valeurs ne se melangent jamais : la source prioritaire porte l'index, les
        autres n'ajoutent que leur meta. Une source de repli ne doit pas ecraser une mesure
        d'une autre echelle."""
        from .services import benchmark_sync as bs
        m = self._modele()

        def aa():
            return {'text-to-image': [
                {'name': 'Widget 2', 'slug': 'widget-2', 'identity': ('widget', (2,), None),
                 'value': 900.0, 'scale': 'aa_elo_text_to_image'}]}, {}

        principale = dict(bs.SOURCES_BY_PRIORITY[0], loader=aa)
        panel = self._source_fictive(priorite=9)     # moins prioritaire
        with patch.object(bs, 'SOURCES_BY_PRIORITY', (principale, panel)):
            bs.synchronize(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 900.0)                     # la prioritaire
        self.assertEqual(m.benchmark_meta['scale'], 'aa_elo_text_to_image')
        self.assertEqual(m.benchmark_meta['panel_nom'], 'Widget 2')    # l'autre a ecrit sa meta
        self.assertNotEqual(m.benchmark_index, 7.5)


class RangCentileTest(TestCase):
    """
    Le rang est la seule lecture comparable D'UN BANC A L'AUTRE — et il n'est qu'un rang.

    Réponse à la demande « ramener toute valeur entre 0 et 100 » : un min-max ne serait pas
    reproductible (les bornes bougent avec la population) et fabriquerait une équivalence
    entre un Intelligence Index et un Elo que personne n'a mesurée. Un rang énonce la
    position de chacun parmi SES pairs, ce qui est mesuré.
    """

    def _pop(self, *valeurs):
        return [{'value': v} for v in valeurs]

    def test_le_rang_est_le_pourcentage_de_la_population_en_dessous(self):
        from .services.benchmark_sync import percentile_rank
        pop = self._pop(10, 20, 30, 40)
        self.assertEqual(percentile_rank(30, pop, lambda e: e['value']), 50.0)
        self.assertEqual(percentile_rank(10, pop, lambda e: e['value']), 0.0)

    def test_deux_echelles_incommensurables_donnent_des_rangs_comparables(self):
        """LE point : 42,9 (Intelligence Index) et 919 (Elo TTS) ne se comparent pas ;
        leurs rangs dans leurs bancs respectifs, si."""
        from .services.benchmark_sync import percentile_rank
        llm = percentile_rank(42.9, self._pop(1, 5, 12, 20, 30, 42.9), lambda e: e['value'])
        tts = percentile_rank(919, self._pop(919, 1200, 1300), lambda e: e['value'])
        self.assertGreater(llm, tts)

    def test_une_population_vide_ou_une_valeur_absente_rend_None(self):
        """Null plutôt que plausible : pas de rang inventé sur une population inconnue."""
        from .services.benchmark_sync import percentile_rank
        self.assertIsNone(percentile_rank(30, [], lambda e: e['value']))
        self.assertIsNone(percentile_rank(None, self._pop(1, 2), lambda e: e['value']))

    def test_le_rang_n_ecrase_jamais_la_valeur_mesuree(self):
        """Le centile s'AJOUTE : `benchmark_index` reste la mesure, avec son échelle."""
        from .services import benchmark_sync as bs

        def aa():
            return {'text-to-image': [
                {'name': 'Widget 2', 'slug': 'widget-2', 'identity': ('widget', (2,), None),
                 'value': 900.0, 'scale': 'aa_elo_text_to_image'},
                {'name': 'Autre 1', 'slug': 'autre-1', 'identity': ('autre', (1,), None),
                 'value': 100.0, 'scale': 'aa_elo_text_to_image'}]}, {}

        def arena():
            raise bs.SourceUnavailable('non sollicitée')

        m = AIModel.objects.create(
            model_key='imager:widget-2', name='Widget 2', model_type='diffusion',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'})
        with patch.multiple(bs, load_aa=aa, load_arena=arena):
            bs.synchronize(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 900.0)
        self.assertEqual(m.benchmark_meta['scale'], 'aa_elo_text_to_image')
        self.assertEqual(m.benchmark_meta['percentile_rank'], 50.0)
        self.assertEqual(m.benchmark_meta['population'], 2)


class FamilleSansConditionnementTest(TestCase):
    """`base`/`instruct`/`chat` nomment un TIRAGE, pas un modèle — hors de la famille."""

    def test_le_mot_base_du_hf_id_ne_change_plus_la_famille(self):
        from .services.benchmark_sync import _identity
        # Notre `hf_id` dit `...-xl-base-1.0`, AA dit « Stable Diffusion XL 1.0 » : un seul
        # mot d'écart faisait rater un appariement juste (882 sur aa_elo_text_to_image).
        self.assertEqual(_identity('stable-diffusion-xl-base-1.0'),
                         _identity('Stable Diffusion XL 1.0'))

    def test_les_familles_deja_correctes_ne_bougent_pas(self):
        """Contre-épreuve : la concaténation existait pour SÉPARER `qwenimage` de `gptimage`
        (faux appariement mesuré le 19/08). Elle doit continuer."""
        from .services.benchmark_sync import _identity
        self.assertEqual(_identity('hunyuan-image-2.1'), ('hunyuanimage', (2, 1), None))
        self.assertNotEqual(_identity('qwen-image-2'), _identity('GPT Image 2'))
        self.assertEqual(_identity('stable-diffusion-v1-5'), ('stablediffusion', (1, 5), None))

    def test_la_version_apres_un_point_se_lit_comme_apres_un_tiret(self):
        """« FLUX.1-schnell » (nom HF) et « flux-1-dev » (notre clé) sont la même famille :
        5 candidats FLUX étaient « sans identité » le 02/09 — le point n'était pas lu."""
        from .services.benchmark_sync import _identity
        self.assertEqual(_identity('FLUX.1-schnell'), ('flux', (1,), None))
        self.assertEqual(_identity('FLUX.2-klein-9B'), ('flux', (2,), 9.0))
        self.assertEqual(_identity('FLUX.1-schnell')[:2], _identity('flux-1-dev')[:2])
        # chiffre.chiffre reste une version composée, pas un séparateur
        self.assertEqual(_identity('qwen3.6:35b'), ('qwen', (3, 6), 35.0))
        self.assertEqual(_identity('stable-diffusion-v1.5'), ('stablediffusion', (1, 5), None))

    def test_an_active_size_alone_is_the_size(self):
        """The 5B candidate took the arena Elo of `wan-v2.2-a14b` (2026-09-23): « A14B » was
        not read, so the size was unknown, so compatible with any size."""
        from .services.benchmark_sync import _compatible, _identity
        self.assertEqual(_identity('wan-v2.2-a14b'), ('wan', (2, 2), 14.0))
        self.assertEqual(_identity('Wan2.2-I2V-A14B'), ('wan', (2, 2), 14.0))
        self.assertFalse(_compatible(_identity('Wan2.2-TI2V-5B-Diffusers'),
                                     _identity('wan-v2.2-a14b')))
        # Counter-test: a total size keeps precedence over the active one.
        self.assertEqual(_identity('qwen3-6-35b-a3b'), ('qwen', (3, 6), 35.0))

    def test_un_add_on_n_a_jamais_de_banc(self):
        """Une LoRA porte le nom de son modèle de base : rendue lisible, elle en prenait
        l'Elo (flux-lora-logo-design → 1083, mesuré le 02/09). Hors catégorie, par nature."""
        from .services.benchmark_sync import _local_categories
        lora = AIModel.objects.create(
            model_key='imager:flux-lora-logo-design', name='FLUX LoRA Logo', model_type='diffusion',
            source='imager', is_downloaded=True, hf_id='Shakker-Labs/FLUX.1-dev-LoRA-Logo-Design',
            capabilities={'task': 'text-to-image'})
        self.assertEqual(_local_categories(lora), [])
        plein = AIModel.objects.create(
            model_key='imager:flux-1-dev', name='FLUX.1 dev', model_type='diffusion',
            source='imager', is_downloaded=True, hf_id='black-forest-labs/FLUX.1-dev',
            capabilities={'task': 'text-to-image'})
        self.assertEqual(_local_categories(plein), ['text-to-image'])


class BancsMultiMetiersTest(_SourcesFactices, TestCase):
    """
    Un modèle exerçant PLUSIEURS métiers doit être mesuré sur chacun de ses bancs.

    Cas réel du catalogue : `ltx-video-13b-0.9.8-distilled` déclare `task='text-to-video'`
    et fait aussi de l'image→vidéo (son libellé le dit, AA le classe dans les DEUX
    leaderboards). L'ancienne boucle prenait une catégorie et laissait tomber les autres
    en silence.
    """

    def _ltx(self, tasks):
        return AIModel.objects.create(
            model_key='imager:ltx-video-13b', name='LTX Video v0.9.8 13B',
            model_type='diffusion', source='imager', is_downloaded=True,
            capabilities={'tasks': tasks})

    def test_un_seul_metier_donne_exactement_le_comportement_d_avant(self):
        """La non-régression qui compte : les modèles mono-métier ne bougent PAS."""
        from .services import benchmark_sync as bs
        m = self._ltx(['text-to-video'])
        with self._sources({'text-to-video': [
                self._entree('LTX Video v0.9.8 13B', ('ltxvideo', (0, 9, 8), 13.0), valeur=900.0,
                             echelle='aa_elo_text_to_video')]}):
            bs.synchronize(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 900.0)
        self.assertEqual(m.benchmark_meta['scale'], 'aa_elo_text_to_video')
        self.assertEqual(m.benchmark_meta['category'], 'text-to-video')
        self.assertEqual(len(m.benchmark_meta['benchmarks']), 1)

    def test_deux_metiers_donnent_deux_bancs_l_index_restant_sur_le_principal(self):
        from .services import benchmark_sync as bs
        m = self._ltx(['text-to-video', 'image-to-video'])
        with self._sources({
                'text-to-video': [self._entree('LTX Video v0.9.8 13B', ('ltxvideo', (0, 9, 8), 13.0),
                                               valeur=900.0, echelle='aa_elo_text_to_video')],
                'image-to-video': [self._entree('LTX Video v0.9.8 13B', ('ltxvideo', (0, 9, 8), 13.0),
                                                valeur=1180.0, echelle='aa_elo_image_to_video')]}):
            bs.synchronize(dry_run=False)
        m.refresh_from_db()
        bancs = m.benchmark_meta['benchmarks']
        self.assertEqual([b['category'] for b in bancs], ['text-to-video', 'image-to-video'])
        self.assertEqual([b['value'] for b in bancs], [900.0, 1180.0])
        # L'index porté reste celui du métier PRINCIPAL — le second banc, mieux noté, ne
        # doit pas s'y substituer : 1180 et 900 ne sont pas sur la même échelle.
        self.assertEqual(m.benchmark_index, 900.0)
        self.assertEqual(m.benchmark_meta['scale'], 'aa_elo_text_to_video')

    def test_un_metier_ecrit_dans_le_vocabulaire_d_une_plateforme_est_traduit(self):
        """`canonical_task` est le résolveur EXISTANT : une tâche en vocabulaire HF ne doit
        pas rester sans catégorie (leçon du 31/08 — deux vocabulaires se rejoignent sur un
        repli qui a l'air de marcher)."""
        from .services import benchmark_sync as bs
        self.assertEqual(bs._local_categories(self._ltx(['text-to-video'])), ['text-to-video'])
        m = AIModel.objects.create(
            model_key='transcriber:whisper', name='Whisper', model_type='speech',
            source='transcriber', is_downloaded=True,
            capabilities={'task': 'automatic-speech-recognition'})
        # Jusqu'au 02/09 l'ASR n'avait aucun banc tiers et ce test attendait `[]` — la
        # TRADUCTION est ce qu'il protège : le vocabulaire HF doit aboutir au même banc
        # que le nôtre (`transcription`), jamais à un repli hasardeux.
        self.assertEqual(bs._local_categories(m), ['speech-to-text-fr', 'speech-to-text'])
        m.capabilities = {'task': 'transcription'}
        self.assertEqual(bs._local_categories(m), ['speech-to-text-fr', 'speech-to-text'])

    def test_un_embedding_propose_sans_capacites_ne_tombe_pas_dans_le_banc_llm(self):
        """Promesse du 01/09 : le `model_type` (posé par la prospection) fait foi quand la
        découverte n'a pas encore écrit de capacités. Les `vlm` restent éligibles (AA classe
        MiniCPM-V dans son leaderboard LLM) ; un `llm` proposé sans caps aussi (ses faux
        appariements meurent par la taille requise)."""
        from .services import benchmark_sync as bs

        def _propose(nom, model_type):
            return AIModel.objects.create(
                model_key=f'proposed:ollama:{nom}:latest', name=nom, model_type=model_type,
                source='ollama', is_proposed=True, capabilities={})

        # Le matin du 02/09 un embedding proposé n'avait AUCUN banc (`[]`) ; le soir MTEB lui
        # en donne un — mais toujours pas le banc llm, ce que ce test protège.
        self.assertEqual(bs._local_categories(_propose('qwen3-embedding', 'embedding')), ['embedding'])
        # Un VLM reste éligible au banc texte — et depuis l'après-midi du 02/09 l'arène
        # `vision` est son banc PRINCIPAL (cf. `TroisiemeBancEtSensTest`).
        self.assertEqual(bs._local_categories(_propose('minicpm-v4.6', 'vlm')), ['vision', 'llm'])
        self.assertEqual(bs._local_categories(_propose('qwen3-coder', 'llm')), ['llm'])
        # Et l'INSTALLÉ, dont la découverte a écrit les capacités : `completion` fait foi
        # avant le type — le comportement du 19/08 (bge-m3) est inchangé.
        m = AIModel.objects.create(
            model_key='ollama:bge-m3:latest', name='bge-m3', model_type='embedding',
            source='ollama', is_downloaded=True, capabilities={'completion': False})
        self.assertEqual(bs._local_categories(m), [])


class EchellesComparablesTest(_SourcesFactices, TestCase):
    """
    `benchmarks_comparable` — le domicile UNIQUE de la règle des échelles.

    Mesuré le 2026-09-01 : le lot `diffusion` du catalogue porte déjà deux échelles
    (`aa_elo_text_to_image` 1077 et `arena_elo_text_to_image` 1125,76). `best_installed`
    les aurait classées ensemble ; seul un modèle NON mesuré, qui faisait basculer tout le
    lot sur le repli `quality_index`, empêchait le défaut de se voir.
    """

    def _modele(self, cle, index=None, echelle=None, quality=1.0):
        return AIModel.objects.create(
            model_key=cle, name=cle, model_type='diffusion', source='imager',
            is_downloaded=True, is_proposed=False, quality_index=quality,
            benchmark_index=index, benchmark_meta={'scale': echelle} if echelle else {})

    def test_deux_echelles_dans_le_lot_ne_sont_pas_comparables(self):
        from .services.benchmark_sync import benchmarks_comparable
        lot = [self._modele('a', 1077.0, 'aa_elo_text_to_image'),
               self._modele('b', 1125.76, 'arena_elo_text_to_image')]
        self.assertFalse(benchmarks_comparable(lot))

    def test_une_echelle_unique_et_tout_le_lot_mesure_est_comparable(self):
        from .services.benchmark_sync import benchmarks_comparable
        lot = [self._modele('a', 1077.0, 'aa_elo_text_to_image'),
               self._modele('b', 1038.0, 'aa_elo_text_to_image')]
        self.assertTrue(benchmarks_comparable(lot))

    def test_un_seul_modele_non_mesure_suffit_a_refuser_le_lot(self):
        from .services.benchmark_sync import benchmarks_comparable
        lot = [self._modele('a', 1077.0, 'aa_elo_text_to_image'), self._modele('b')]
        self.assertFalse(benchmarks_comparable(lot))

    def test_best_installed_retombe_sur_l_a_priori_quand_les_echelles_different(self):
        """LE défaut corrigé : `best_installed` annonçait la règle de `_rank_key` et n'en
        appliquait que la moitié. Le classement doit suivre `quality_index`, pas les Elo."""
        self._modele('faible-elo', 1077.0, 'aa_elo_text_to_image', quality=9.0)
        self._modele('fort-elo', 1125.76, 'arena_elo_text_to_image', quality=1.0)
        top = AIModel.best_installed('diffusion', limit=2)
        self.assertEqual(top[0].model_key, 'faible-elo')

    def test_best_installed_by_task_keeps_only_that_trade(self):
        """A text-to-video candidate showed « Concurrence : SDXL, FLUX… » (2026-09-23)."""
        image = self._modele('sdxl', quality=9.0)
        image.capabilities = {'task': 'text-to-image'}
        image.save()
        video = self._modele('ltx', quality=1.0)
        video.capabilities = {'task': 'image-to-video', 'tasks': ['text-to-video', 'image-to-video']}
        video.save()
        self.assertEqual([m.model_key for m in AIModel.best_installed('diffusion', task='text-to-video')],
                         ['ltx'])
        # Counter-test: without a task, the whole category still competes, best a priori first.
        self.assertEqual([m.model_key for m in AIModel.best_installed('diffusion')][:2],
                         ['sdxl', 'ltx'])
        self.assertEqual(AIModel.best_installed('diffusion', task='image-to-image'), [])


class EspaceDeClesDuTirageTest(TestCase):
    """Le RETOUR de `select_model_id` suit l'espace de clés de la REQUÊTE.

    Défaut mesuré le 2026-09-01 en préparant le tirage AUTOMATIQUE : interrogé par CAPACITÉ
    (`source=None`, le mode qui rend les passerelles gratuites), `select_model_id` rendait un
    id NU — `'bark'` — alors que les candidats, eux, sont des clés entières et que l'app
    stocke et route `'synthesizer:bark'` depuis le portage F4b.

    Le tirage aurait donc « marché » en rendant une valeur que plus rien en aval ne reconnaît :
    option introuvable dans le select, chip affichant la clé brute, capacités non résolues.
    C'est la règle que `get_registry_models` applique déjà dans ce mode, et qui manquait ici.
    """

    def _modele(self, cle, task, vram=1.0):
        return AIModel.objects.create(
            model_key=cle, name=cle.split(':')[-1], source=cle.split(':')[0],
            model_type='speech', vram_gb=vram, is_available=True, is_downloaded=True,
            is_proposed=False, capabilities={'task': task, 'modalities': ['audio'],
                                             'inputs_required': ['prompt']})

    def test_par_capacite_la_cle_rendue_est_ENTIERE(self):
        from .services import select_model_id
        self._modele('synthesizer:moteur-a', 'text-to-speech', vram=4.0)
        cle = select_model_id(None, task='text-to-speech')
        self.assertEqual(
            cle, 'synthesizer:moteur-a',
            "tirage par capacité : sans préfixe de source, deux producteurs pourraient "
            "porter le même suffixe et l'appelant ne saurait plus qui il vise")

    def test_par_source_la_cle_rendue_reste_NUE(self):
        """La voie historique ne bouge pas — imager et composer stockent des ids nus."""
        from .services import select_model_id
        self._modele('synthesizer:moteur-b', 'text-to-speech', vram=4.0)
        self.assertEqual(select_model_id('synthesizer', task='text-to-speech'), 'moteur-b')

    def test_un_choix_EXPLICITE_traverse_intact(self):
        """`requested` est respecté tel quel — dans l'espace de clés que l'appelant emploie."""
        from .services import select_model_id
        self._modele('synthesizer:moteur-c', 'text-to-speech')
        self.assertEqual(
            select_model_id(None, task='text-to-speech', requested='synthesizer:moteur-c'),
            'synthesizer:moteur-c')


class TroisiemeBancEtSensTest(_SourcesFactices, TestCase):
    """
    2026-09-02 — deux extensions du banc tiers et ce qu'elles ont RÉVÉLÉ.

    (1) Les sous-ensembles Arena `vision` / `document` : téléchargeables par le même chargeur,
        jamais demandés. Première lecture réelle : `gemma4:12b` prenait l'Elo de
        `gemma-4-31b` — la règle de taille stricte n'existait que pour `llm`, écrite en dur.
    (2) L'Open ASR Leaderboard, premier banc HORS génération et première échelle où PLUS BAS
        EST MIEUX (WER). Un consommateur qui trie `benchmark_index` décroissant mettrait le
        pire transcripteur en tête : le SENS voyage désormais avec la valeur.
    """

    def _panel(self, cats, direction=None, priority=3):
        """Source fictive rendant `cats` = {catégorie: [entrées {'name','identity','note'}]}."""
        d = {'key': 'panel', 'label': 'Panel Fictif', 'priority': priority,
             'source_name': 'panel', 'value': lambda e: e.get('note'),
             'scale': lambda e, cat: 'panel_note_' + cat,
             'meta': lambda retenu, cands: {'panel_nom': retenu['name']},
             'loader': lambda: (dict(cats), {})}
        if direction:
            d['direction'] = direction
        return d

    # ── (1) métiers dérivés et taille stricte ───────────────────────────────────────────

    def test_les_metiers_derives_des_nouvelles_categories(self):
        from .services import benchmark_sync as bs
        llm_vision = AIModel.objects.create(
            model_key='ollama:gemma4:12b', name='gemma4:12b', model_type='llm', source='ollama',
            is_downloaded=True,
            capabilities={'task': 'text-generation', 'completion': True, 'vision': True})
        vlm = AIModel.objects.create(
            model_key='proposed:ollama:minicpm-v4.6:latest', name='minicpm-v4.6:latest',
            model_type='vlm', source='ollama', is_proposed=True, capabilities={})
        asr = AIModel.objects.create(
            model_key='transcriber:whisper', name='Whisper Large-v3', model_type='speech',
            source='transcriber', is_downloaded=True, capabilities={'task': 'transcription'})
        # LLM à capacité vision : le banc texte reste PRINCIPAL, `vision` s'ajoute.
        self.assertEqual(bs._local_categories(llm_vision), ['llm', 'vision'])
        # VLM : l'arène `vision` est son métier principal, le texte secondaire.
        self.assertEqual(bs._local_categories(vlm), ['vision', 'llm'])
        # Transcription : le FRANÇAIS d'abord (ce que le transcriber fait ici), l'anglais après.
        self.assertEqual(bs._local_categories(asr), ['speech-to-text-fr', 'speech-to-text'])

    def test_l_arene_vision_exige_la_taille_comme_le_banc_llm(self):
        """`gemma4:12b` a DEUX identités locales : (gemma,(4,),12) par le tag, (gemma,(4,),None)
        par le nom. Sans taille stricte, la seconde apparie `gemma-4-31b` — mesuré le 02/09."""
        from .services import benchmark_sync as bs
        m = AIModel.objects.create(
            model_key='ollama:gemma4:12b', name='Gemma 4', model_type='llm', source='ollama',
            is_downloaded=True,
            capabilities={'task': 'text-generation', 'completion': True, 'vision': True})
        panel = self._panel({'vision': [
            {'name': 'gemma-4-31b', 'identity': ('gemma', (4,), 31.0), 'note': 1276.0}]})
        with patch.object(bs, 'SOURCES_BY_PRIORITY', (panel,)), \
                patch.object(bs, '_real_tag', return_value=''):
            r = bs.synchronize(dry_run=False)
        m.refresh_from_db()
        self.assertIsNone(m.benchmark_index, "12B ne doit pas hériter de l'Elo du 31B")
        self.assertIn('ollama:gemma4:12b [llm]', r['unmatched'])
        # Et la bonne taille, elle, apparie — la règle refuse l'asymétrie, pas la catégorie.
        panel_ok = self._panel({'vision': [
            {'name': 'gemma-4-12b', 'identity': ('gemma', (4,), 12.0), 'note': 1200.0}]})
        with patch.object(bs, 'SOURCES_BY_PRIORITY', (panel_ok,)), \
                patch.object(bs, '_real_tag', return_value=''):
            bs.synchronize(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 1200.0)
        self.assertEqual(m.benchmark_meta['category'], 'vision')

    def test_charger_aa_ne_requete_pas_les_categories_sans_endpoint(self):
        """`vision`, `document` et l'ASR n'ont pas d'endpoint AA : ni requête, ni motif."""
        from .services import benchmark_sync as bs
        urls = []

        def faux_http(url, headers=None, timeout=45):
            urls.append(url)
            return {'data': []}
        with patch.object(bs, '_http_json', side_effect=faux_http), \
                patch.dict('os.environ', {bs.AA_KEY_ENV: 'cle-factice'}):
            with self.assertRaises(bs.SourceUnavailable):   # réponses vides → indisponible
                bs.load_aa()
        attendues = sum(1 for spec in bs.CATEGORIES.values() if spec.get('aa'))
        self.assertEqual(len(urls), attendues)
        self.assertFalse(any('None' in u for u in urls))

    # ── (2) le sens de l'échelle ────────────────────────────────────────────────────────

    def test_un_taux_d_erreur_se_lit_a_l_envers(self):
        from .services.benchmark_sync import _choose_variant, percentile_rank, orderable_value
        pop = [{'v': x} for x in (2.0, 4.0, 6.0, 8.0)]
        # 5 % de WER bat les 6 et 8 : 50ᵉ centile — pas 25ᵉ comme pour un score.
        self.assertEqual(percentile_rank(5.0, pop, lambda e: e['v'], direction='lower'), 50.0)
        self.assertEqual(percentile_rank(5.0, pop, lambda e: e['v']), 50.0)
        self.assertEqual(percentile_rank(2.0, pop, lambda e: e['v'], direction='lower'), 75.0)
        # Dernier recours de `_choose_variant` : la valeur la PIRE — la plus haute en WER.
        cands = [{'name': 'x a', 'v': 3.0}, {'name': 'x b', 'v': 9.0}]
        self.assertEqual(_choose_variant('x', cands, lambda e: e['v'], direction='lower')['v'], 9.0)
        self.assertEqual(_choose_variant('x', cands, lambda e: e['v'])['v'], 3.0)
        # `orderable_value` : plus grand = meilleur, quel que soit le sens.
        m_wer = AIModel(model_key='a', benchmark_index=5.0, benchmark_meta={'direction': 'lower'})
        m_elo = AIModel(model_key='b', benchmark_index=5.0, benchmark_meta={'direction': 'higher'})
        m_nu = AIModel(model_key='c', benchmark_index=5.0, benchmark_meta={})
        self.assertEqual(orderable_value(m_wer), -5.0)
        self.assertEqual(orderable_value(m_elo), 5.0)
        self.assertEqual(orderable_value(m_nu), 5.0)
        self.assertIsNone(orderable_value(AIModel(model_key='d')))

    def test_un_banc_a_sens_bas_traverse_la_chaine_et_ordonne_a_l_endroit(self):
        from .services import benchmark_sync as bs
        bon = AIModel.objects.create(
            model_key='transcriber:bon-2', name='Bon 2', model_type='speech',
            source='transcriber', is_downloaded=True, capabilities={'task': 'transcription'})
        moyen = AIModel.objects.create(
            model_key='transcriber:moyen-2', name='Moyen 2', model_type='speech',
            source='transcriber', is_downloaded=True, capabilities={'task': 'transcription'})
        panel = self._panel({'speech-to-text-fr': [
            {'name': 'org/bon-2', 'identity': ('bon', (2,), None), 'note': 4.0},
            {'name': 'org/moyen-2', 'identity': ('moyen', (2,), None), 'note': 8.0},
            {'name': 'org/pire-2', 'identity': ('pire', (2,), None), 'note': 20.0}]}, direction='lower')
        with patch.object(bs, 'SOURCES_BY_PRIORITY', (panel,)):
            bs.synchronize(dry_run=False)
        bon.refresh_from_db()
        moyen.refresh_from_db()
        self.assertEqual(bon.benchmark_index, 4.0)
        self.assertEqual(bon.benchmark_meta['direction'], 'lower')
        self.assertEqual(bon.benchmark_meta['scale'], 'panel_note_speech-to-text-fr')
        # Centile INVERSÉ : 4 % de WER bat 8 et 20 → 66,7ᵉ ; 8 ne bat que 20 → 33,3ᵉ.
        self.assertEqual(bon.benchmark_meta['percentile_rank'], 66.7)
        self.assertEqual(moyen.benchmark_meta['percentile_rank'], 33.3)
        # Et le classement des installés met le WER le plus BAS en tête.
        self.assertEqual([m.model_key for m in AIModel.best_installed('speech')],
                         ['transcriber:bon-2', 'transcriber:moyen-2'])

    def test_charger_open_asr_lit_la_forme_reelle_des_csv(self):
        """Forme sondée le 02/09 : l'anglais publie `avg`, le français NON (moyenne calculée
        des `* WER`) ; `RTFx=-1` = non mesuré ; une entrée sans identité est sautée."""
        import tempfile
        from pathlib import Path
        from .services import benchmark_sync as bs
        with tempfile.TemporaryDirectory() as tmp:
            en = Path(tmp) / 'en.csv'
            en.write_text(
                'model,avg,RTFx,License,Size (B),LS Clean WER,AMI WER\n'
                'openai/whisper-large-v3,5.78,120.5,apache-2.0,1.55,1.56,14.86\n'
                'nvidia/parakeet-tdt-0.6b-v2,6.05,3000,cc-by-4.0,0.6,1.9,13.0\n'
                'Qwen/Qwen3-ASR-1.7B-hf,4.311,,apache-2.0,2.1,1.26,\n', encoding='utf-8')
            fr = Path(tmp) / 'fr.csv'
            fr.write_text(
                'model,RTFx,FLEURS WER,MCV WER,MLS WER\n'
                'openai/whisper-large-v3,-1.0,4.84,9.97,3.9\n'
                'Qwen/Qwen3-ASR-1.7B-hf,-1.0,4.06,7.84,\n', encoding='utf-8')
            chemins = {'english_short_latest.csv': str(en), 'multilingual_fr.csv': str(fr)}
            with patch.object(bs, 'OPEN_ASR_DATASETS', {
                    'english_short': ('depot/en', 'english_short_latest.csv'),
                    'multilingual_fr': ('depot/fr', 'multilingual_fr.csv')}), \
                    patch('huggingface_hub.hf_hub_download',
                          side_effect=lambda repo, fn, repo_type: chemins[fn]):
                par_cat, motifs = bs.load_open_asr()
        self.assertEqual(motifs, {})
        en_entrees = {e['name']: e for e in par_cat['speech-to-text']}
        fr_entrees = {e['name']: e for e in par_cat['speech-to-text-fr']}
        # parakeet : version APRÈS la taille → pas d'identité lisible → sauté (null > plausible)
        self.assertEqual(set(en_entrees), {'openai/whisper-large-v3', 'Qwen/Qwen3-ASR-1.7B-hf'})
        w = en_entrees['openai/whisper-large-v3']
        self.assertEqual(w['wer'], 5.78)                       # colonne `avg` telle quelle
        self.assertEqual(w['identity'], ('whisperlarge', (3,), None))
        self.assertEqual(w['rtfx'], 120.5)
        self.assertEqual(w['license'], 'apache-2.0')
        self.assertEqual(w['datasets'], {'LS Clean': 1.56, 'AMI': 14.86})
        q = fr_entrees['Qwen/Qwen3-ASR-1.7B-hf']
        self.assertEqual(q['identity'], ('qwen', (3,), 1.7))
        self.assertEqual(q['wer'], round((4.06 + 7.84) / 2, 3))   # MLS absent → moyenne des 2
        self.assertIsNone(q['rtfx'])                                # -1 = non mesuré
        self.assertEqual(fr_entrees['openai/whisper-large-v3']['wer'],
                         round((4.84 + 9.97 + 3.9) / 3, 3))


class QuatriemeBancMtebTest(_SourcesFactices, TestCase):
    """
    2026-09-02 — MTEB, le banc des EMBEDDINGS (le RAG tourne sur bge-m3 sans mesure tierce).
    Sans le paquet `mteb`, on ne reproduit pas la moyenne officielle : le jeu de tâches est
    DÉCLARÉ (5 tâches de recherche en FRANÇAIS), un modèle sans les cinq n'est pas noté, et
    `paths.json` (périmé) donne la population tandis que l'API GitHub ne sert que pour les
    modèles de NOTRE catalogue qui en manquent. `bge-m3` s'apparie par ALIAS (famille
    « m3 » rejetée par `_identity`).
    """

    def _faux_index(self, marqueurs=()):
        # Chemin EXACT par (modèle, tâche) — une tâche peut vivre sous une autre révision
        # que les autres (mesuré sur bge-m3 : `AlloprofRetrieval` → 404 sous la 1ʳᵉ révision).
        from .services.benchmark_sync import CATEGORIES
        taches = [t for t, _, _ in CATEGORIES['embedding']['mteb']]
        def chemins(dossier, rev, sauf=()):
            return {t: f'results/{dossier}/{rev}/{t}.json' for t in taches if t not in sauf}
        return {'BAAI__bge-m3': chemins('BAAI__bge-m3', 'rev1'),
                'Qwen__Qwen3-Embedding-0.6B': chemins('Qwen__Qwen3-Embedding-0.6B', 'rev2'),
                'intfloat__multilingual-e5-small': chemins('intfloat__multilingual-e5-small', 'rev3'),
                # une tâche absente de l'index → jamais moyenné sur trois
                'Org__incomplet-1': chemins('Org__incomplet-1', 'rev4', sauf=('AlloprofReranking',)),
                # une tâche présente dans l'index mais 404 au téléchargement → idem
                'Org__incomplet-2': chemins('Org__incomplet-2', 'rev5'),
                # le sous-ensemble français ABSENT du fichier → idem
                'Org__sans-fr-3': chemins('Org__sans-fr-3', 'rev6'),
                # échec PASSAGER (réseau) → sauté CETTE passe, jamais mis en cache
                'Org__reseau-4': chemins('Org__reseau-4', 'rev7')}

    def _faux_get(self, url, **kw):
        import json as _json
        import re
        from unittest.mock import Mock
        from .services.benchmark_sync import CATEGORIES
        m = re.search(r'/results/([^/]+)/[^/]+/([^/]+)\.json$', url)
        dossier, tache = m.group(1), m.group(2)
        if dossier == 'Org__incomplet-2' and tache == 'BelebeleRetrieval':
            return Mock(status_code=404)
        if dossier == 'Org__reseau-4':
            raise ConnectionError('proxy: reset')
        base = {'BAAI__bge-m3': 0.60, 'Qwen__Qwen3-Embedding-0.6B': 0.70,
                'intfloat__multilingual-e5-small': 0.50, 'Org__incomplet-1': 0.90,
                'Org__incomplet-2': 0.95, 'Org__sans-fr-3': 0.99}[dossier]
        split, subset = next((s, sub) for t, s, sub in CATEGORIES['embedding']['mteb'] if t == tache)
        subsets = [{'hf_subset': 'eng', 'main_score': 0.11}]
        if dossier != 'Org__sans-fr-3':
            subsets.append({'hf_subset': subset, 'main_score': base})
        # `NaN` dans le fichier (mteb en écrit) : le json stdlib le lit, simplejson non
        texte = _json.dumps({'scores': {split: subsets, 'autre': []}}).replace('0.11', 'NaN')
        return Mock(status_code=200, raise_for_status=lambda: None, text=texte)

    def test_charger_mteb_moyenne_le_jeu_declare_et_ignore_un_modele_incomplet(self):
        import tempfile
        from pathlib import Path
        from .services import benchmark_sync as bs
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(bs, '_mteb_index', side_effect=self._faux_index), \
                patch.object(bs, '_mteb_markers', return_value=set()), \
                patch.object(bs, '_mteb_cache_path', return_value=Path(tmp) / 'c.json'), \
                patch('requests.get', side_effect=self._faux_get):
            par_cat, motifs = bs.load_mteb()
            # 2ᵉ passe : les modèles LUS viennent du cache — aucune requête pour eux ; seul
            # `reseau-4` (échec passager, jamais mis en cache) est retenté.
            def relecture(url, **kw):
                if 'Org__reseau-4' not in url:
                    raise AssertionError('réseau interdit pour un modèle déjà lu : ' + url)
                return self._faux_get(url)
            with patch('requests.get', side_effect=relecture):
                par_cat2, _ = bs.load_mteb()
        noms = {e['name']: e for e in par_cat['embedding']}
        self.assertEqual(set(noms), {'BAAI/bge-m3', 'Qwen/Qwen3-Embedding-0.6B',
                                     'intfloat/multilingual-e5-small'})
        self.assertEqual(noms['BAAI/bge-m3']['score'], 60.0)
        self.assertEqual(len(noms['BAAI/bge-m3']['tasks']), 4)
        self.assertEqual(noms['Qwen/Qwen3-Embedding-0.6B']['identity'], ('qwen', (3,), 0.6))
        self.assertIsNone(noms['BAAI/bge-m3']['identity'])              # d'où l'ALIAS
        self.assertIn('1 modèle(s) non lus', motifs['embedding'])
        self.assertEqual(par_cat2['embedding'], par_cat['embedding'])

    def test_l_index_garde_le_chemin_exact_par_tache_et_ne_paie_l_api_que_pour_nos_modeles(self):
        """`paths.json` : une tâche peut vivre sous une AUTRE révision que les autres (bge-m3 :
        Alloprof → 404 sous la 1ʳᵉ) ; l'API GitHub (quota 60/h) n'est appelée que pour les
        dossiers absents de `paths.json` ET portant un marqueur du catalogue."""
        import json as _json
        from unittest.mock import Mock
        from .services import benchmark_sync as bs
        jeu = [t for t, _, _ in bs.CATEGORIES['embedding']['mteb']]
        paths = {'BAAI__bge-m3': [f'results/BAAI__bge-m3/revA/{jeu[0]}.json',
                                  f'results/BAAI__bge-m3/revB/{jeu[1]}.json',        # autre révision
                                  'results/BAAI__bge-m3/revA/AutreTache.json'],
                 'Org__ancien': [f'results/Org__ancien/r/{t}.json' for t in jeu]}
        appels = []

        def faux_get(url, **kw):
            appels.append(url)
            if url.endswith('/paths.json'):
                return Mock(status_code=200, raise_for_status=lambda: None, json=lambda: paths)
            if url.endswith('/git/trees/main'):
                return Mock(status_code=200, raise_for_status=lambda: None,
                            json=lambda: {'tree': [{'path': 'results', 'sha': 'S', 'type': 'tree'}]})
            if url.endswith('/git/trees/S'):
                return Mock(status_code=200, raise_for_status=lambda: None, json=lambda: {'tree': [
                    {'path': 'Qwen__Qwen3-Embedding-4B', 'sha': 'Q', 'type': 'tree'},
                    {'path': 'Autre__sans-rapport', 'sha': 'X', 'type': 'tree'},
                    {'path': 'BAAI__bge-m3', 'sha': 'B', 'type': 'tree'}]})
            if url.endswith('/git/trees/Q?recursive=1'):
                return Mock(status_code=200, raise_for_status=lambda: None, json=lambda: {'tree': [
                    {'path': f'rev9/{t}.json', 'type': 'blob'} for t in jeu] + [{'path': 'rev9/model_meta.json', 'type': 'blob'}]})
            raise AssertionError('appel imprévu : ' + url)

        with patch('requests.get', side_effect=faux_get):
            index = bs._mteb_index({'qwen3-embedding'})
        self.assertEqual(index['BAAI__bge-m3'][jeu[0]], f'results/BAAI__bge-m3/revA/{jeu[0]}.json')
        self.assertEqual(index['BAAI__bge-m3'][jeu[1]], f'results/BAAI__bge-m3/revB/{jeu[1]}.json')
        self.assertNotIn(jeu[2], index['BAAI__bge-m3'])                       # incomplet, pas inventé
        self.assertEqual(set(index['Qwen__Qwen3-Embedding-4B']), set(jeu))
        self.assertEqual(index['Qwen__Qwen3-Embedding-4B'][jeu[0]],
                         f'results/Qwen__Qwen3-Embedding-4B/rev9/{jeu[0]}.json')
        self.assertNotIn('Autre__sans-rapport', index)                       # pas de marqueur → 0 appel
        # 1 paths.json + 2 arbres (main, results) + 1 arbre récursif pour LE modèle marqué
        self.assertEqual(len(appels), 4)

    def test_bge_m3_du_rag_prend_son_banc_par_alias_et_les_embeddings_proposes_ont_une_categorie(self):
        from .services import benchmark_sync as bs
        bge = AIModel.objects.create(
            model_key='ollama:bge-m3:latest', name='bge-m3:latest', model_type='embedding',
            source='ollama', is_downloaded=True,
            capabilities={'task': 'feature-extraction', 'embedding': True, 'completion': False})
        propose = AIModel.objects.create(
            model_key='proposed:ollama:qwen3-embedding:latest', name='qwen3-embedding:latest',
            model_type='embedding', source='ollama', is_proposed=True, capabilities={})
        self.assertEqual(bs._local_categories(bge), ['embedding'])
        self.assertEqual(bs._local_categories(propose), ['embedding'])
        mteb = next(s for s in bs.SOURCES if s['key'] == 'mteb')
        entrees = [{'name': 'BAAI/bge-m3', 'slug': 'BAAI/bge-m3', 'identity': None, 'score': 61.2,
                    'tasks': {}, 'revision': 'r'},
                   {'name': 'intfloat/multilingual-e5-small', 'slug': 'intfloat/multilingual-e5-small',
                    'identity': ('multilinguale', (5,), None), 'score': 50.0, 'tasks': {}, 'revision': 'r'}]
        src = dict(mteb, loader=lambda: ({'embedding': entrees}, {}))
        with patch.object(bs, 'SOURCES_BY_PRIORITY', (src,)):
            r = bs.synchronize(dry_run=False)
        bge.refresh_from_db()
        self.assertEqual(bge.benchmark_index, 61.2)
        self.assertEqual(bge.benchmark_meta['scale'], 'mteb_fr_retrieval')
        self.assertEqual(bge.benchmark_meta['declared_alias'], 'BAAI/bge-m3')
        self.assertEqual(bge.benchmark_meta['percentile_rank'], 50.0)
        self.assertIn('proposed:ollama:qwen3-embedding:latest [embedding]', r['unmatched'])


@override_settings(WAMA_GPU_SAFE_MODE=False)
class BancDeGenerationTest(TestCase):
    """
    Protocole `text-generation` du banc (2026-09-14, confrontation llmfit) : le DÉBIT d'un LLM
    Ollama, lu dans les temps natifs de `/api/generate` — et persisté comme DURÉE dans la boucle
    d'ETA (`ModelRuntimeStat`, unité `token`), jamais comme qualité.

    CE QUE CES TESTS PROTÈGENT : avant ce protocole, `ModelRuntimeStat` portait une unité
    `token` a priori (0,03 s/jeton) et AUCUN enregistrement — aucune app LLM n'appelle
    `record_run`. Le banc est le seul point d'entrée des LLM dans cette boucle ; s'il cesse de
    l'appeler, l'ETA des LLM redevient une constante inventée, sans que rien ne casse.

    ⚠ `WAMA_GPU_SAFE_MODE` est ACTIF sur l'hôte de développement (mesuré au 1ᵉʳ run de ces
    tests : 4 erreurs « chargement refusé »). Le nominal est donc forcé à False ici, et le refus
    est testé à part avec True — sans quoi la suite mesurerait le réglage de la machine, pas le
    protocole.
    """

    def setUp(self):
        self.m = AIModel.objects.create(
            model_key='ollama:qwen3.5:4b', name='qwen3.5:4b', model_type='llm', source='ollama',
            is_downloaded=True, vram_gb=3.4, capabilities={'task': 'text-generation'})

    @staticmethod
    def _reponse(jetons, generation_ns, prefill_ns=200_000_000, load_ns=0, prompt_jetons=12):
        return {'response': 'x' * jetons, 'eval_count': jetons, 'eval_duration': generation_ns,
                'prompt_eval_count': prompt_jetons, 'prompt_eval_duration': prefill_ns,
                'load_duration': load_ns, 'total_duration': load_ns + prefill_ns + generation_ns}

    def test_le_debit_vient_des_temps_natifs_et_chaque_passe_nourrit_l_eta(self):
        from .services import bench, eta_estimator
        # chauffe (chargement à froid 4,2 s) puis 3 passes : 150 jetons en 1,5 s = 100 jetons/s
        reponses = ([self._reponse(3, 30_000_000, load_ns=4_200_000_000)]
                    + [self._reponse(150, 1_500_000_000)] * 3)
        appels = []
        with patch.object(bench, '_ollama_generate', side_effect=reponses) as http, \
             patch.object(eta_estimator, 'record_run',
                          side_effect=lambda *a, **k: appels.append((a, k))):
            mesure = bench._bench_generation(self.m, 'Explique la photosynthèse en trois phrases.')
        self.assertEqual(http.call_count, 4)                          # 1 chauffe + 3 passes
        self.assertEqual(http.call_args_list[0].args[2], 8)           # la chauffe est courte…
        self.assertEqual(http.call_args_list[1].args[2], bench.TOKEN_CAP)  # …les passes, non
        self.assertEqual(mesure['tokens_per_s'], 100.0)
        self.assertEqual(mesure['outputs'], 150)
        self.assertEqual(mesure['inference_s'], 1.5)
        self.assertEqual(mesure['prefill_ms'], 200.0)
        self.assertEqual(mesure['load_s'], 4.2)
        self.assertFalse(mesure['saturated'])
        self.assertIsNone(mesure['mean_confidence'])                # jamais une qualité
        # 3 exécutions réelles → 3 enregistrements, unité `token`, taille = jetons produits ;
        # le chargement à froid n'est appris QU'UNE fois (les passes suivantes sont résidentes).
        self.assertEqual(len(appels), 3)
        for (args, kw) in appels:
            self.assertEqual(args[0], 'ollama:qwen3.5:4b')
            self.assertEqual(kw['unit'], 'token')
            self.assertEqual(kw['size'], 150)
            self.assertEqual(kw['process_seconds'], 1.5)
        self.assertEqual([kw['load_seconds'] for _, kw in appels], [4.2, None, None])

    def test_un_modele_deja_resident_n_apprend_pas_de_chargement(self):
        from .services import bench, eta_estimator
        reponses = ([self._reponse(3, 30_000_000, load_ns=12_000_000)]
                    + [self._reponse(100, 1_000_000_000)] * 3)
        appels = []
        with patch.object(bench, '_ollama_generate', side_effect=reponses), \
             patch.object(eta_estimator, 'record_run', side_effect=lambda *a, **k: appels.append(k)):
            mesure = bench._bench_generation(self.m, 'prompt')
        self.assertIsNone(mesure['load_s'])                     # 12 ms = ré-attachement
        self.assertTrue(all(k['load_seconds'] is None for k in appels))

    def test_atteindre_le_plafond_a_chaque_passe_est_une_saturation(self):
        from .services import bench, eta_estimator
        reponses = ([self._reponse(3, 30_000_000)]
                    + [self._reponse(bench.TOKEN_CAP, 2_000_000_000)] * 3)
        with patch.object(bench, '_ollama_generate', side_effect=reponses), \
             patch.object(eta_estimator, 'record_run'):
            mesure = bench._bench_generation(self.m, 'prompt')
        self.assertTrue(mesure['saturated'])
        self.assertEqual(mesure['tokens_per_s'], 150.0)               # le débit reste valide

    def test_le_prompt_peut_etre_un_fichier_texte(self):
        import tempfile
        from .services import bench, eta_estimator
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("  Décris le cycle de l'eau.\n")
        reponses = [self._reponse(3, 30_000_000)] + [self._reponse(50, 500_000_000)] * 3
        with patch.object(bench, '_ollama_generate', side_effect=reponses) as http, \
             patch.object(eta_estimator, 'record_run'):
            bench._bench_generation(self.m, f.name)
        self.assertEqual(http.call_args_list[1].args[1], "Décris le cycle de l'eau.")

    def test_un_modele_hors_ollama_est_un_resultat_en_erreur_pas_une_casse(self):
        from .services import bench
        AIModel.objects.create(
            model_key='huggingface:org/llm', name='org/llm', model_type='llm', source='huggingface',
            is_downloaded=True, capabilities={'task': 'text-generation'})
        with patch.object(bench, '_ollama_generate') as http:
            mesures = bench.run_bench('text-generation', 'prompt', models=['org/llm'])
        http.assert_not_called()
        self.assertEqual(len(mesures), 1)
        self.assertIn('Ollama seulement', mesures[0]['error'])

    def test_en_mode_depannage_gpu_le_protocole_refuse_avant_tout_appel(self):
        from .services import bench
        with override_settings(WAMA_GPU_SAFE_MODE=True), \
             patch.object(bench, '_ollama_generate') as http:
            with self.assertRaises(RuntimeError) as cm:
                bench._bench_generation(self.m, 'prompt')
        http.assert_not_called()
        self.assertIn('WAMA_GPU_SAFE_MODE', str(cm.exception))

    def test_la_profondeur_charge_un_candidat_hub_dans_le_dossier_de_sa_famille(self):
        # Relevé par Fabien le 14/09 : `_bench_depth` chargeait par identifiant Hub SANS
        # `cache_dir=` → un candidat de banc atterrissait dans le cache partagé (AGENTS.md
        # §Ajout d'un modèle : « le modèle principal par cache_dir= »). Le dossier est celui du
        # moteur, jamais une constante locale au banc.
        from unittest.mock import MagicMock
        import torch
        from .services import bench
        from wama.common.backends.depth_engine import DEPTH_MODEL_DIR
        candidat = AIModel.objects.create(
            model_key='huggingface:org/depth-candidat', name='org/depth-candidat',
            model_type='vision', source='huggingface', is_downloaded=True, local_path='',
            hf_id='org/depth-candidat', capabilities={'task': 'depth-estimation'})

        processor = MagicMock()
        processor.return_value.to.return_value = {}
        processor.post_process_depth_estimation.return_value = [
            {'predicted_depth': torch.ones(4, 4) * 2.5, 'focal_length': torch.tensor([800.0])}]
        model = MagicMock()
        model.to.return_value.eval.return_value = model
        image = MagicMock()
        image.convert.return_value.size = (4, 4)
        with patch('transformers.AutoImageProcessor.from_pretrained', return_value=processor) as p, \
             patch('transformers.AutoModelForDepthEstimation.from_pretrained', return_value=model) as m, \
             patch('PIL.Image.open', return_value=image), \
             patch('torch.cuda.is_available', return_value=False):
            mesure = bench._bench_depth(candidat, 'image.jpg')
        self.assertEqual(p.call_args.kwargs['cache_dir'], str(DEPTH_MODEL_DIR))
        self.assertEqual(m.call_args.kwargs['cache_dir'], str(DEPTH_MODEL_DIR))
        self.assertEqual(p.call_args.args[0], 'org/depth-candidat')
        self.assertEqual(mesure['median_m'], 2.5)
        self.assertEqual(mesure['focal_px'], 800.0)
        self.assertEqual(mesure['mean_confidence'], 1.0)          # couverture : 16/16 valides

    def test_de_bout_en_bout_contre_un_faux_ollama_la_commande_rend_la_table_et_persiste_l_eta(self):
        """
        Le seul test qui traverse la couche HTTP RÉELLE du protocole (payload, `trust_env`,
        lecture des champs natifs) et la commande jusqu'à la table rendue — SANS GPU, contre un
        serveur local qui imite `/api/generate`. Écrit le 2026-09-15 parce qu'aucune mesure réelle
        n'est possible sur cet hôte (Fabien : « je ne peux pas lancer de tâche GPU, ça crashe
        systématiquement ») : c'est l'attestation maximale atteignable ici. Ce qu'il n'atteste
        PAS : les chiffres d'un vrai modèle.
        """
        import io
        import json
        import tempfile
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from django.core.management import call_command
        from wama.common.utils import ollama_host
        from .models import ModelRuntimeStat
        from .services import eta_estimator

        recus = []

        class FauxOllama(BaseHTTPRequestHandler):
            def do_POST(self):
                corps = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                recus.append((self.path, corps))
                courte = corps['options']['num_predict'] <= 8          # la chauffe
                reponse = {
                    'model': corps['model'], 'response': 'ok' if courte else 'x' * 120,
                    'done': True,
                    'load_duration': 3_200_000_000 if len(recus) == 1 else 9_000_000,
                    'prompt_eval_count': 12, 'prompt_eval_duration': 150_000_000,
                    'eval_count': 3 if courte else 120,
                    'eval_duration': 30_000_000 if courte else 1_200_000_000,
                    'total_duration': 1_400_000_000,
                }
                data = json.dumps(reponse).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):        # silence
                pass

        serveur = ThreadingHTTPServer(('127.0.0.1', 0), FauxOllama)
        fil = threading.Thread(target=serveur.serve_forever, daemon=True)
        fil.start()
        base = f"http://127.0.0.1:{serveur.server_address[1]}"
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("Explique la photosynthèse en trois phrases.")
        sortie = io.StringIO()
        try:
            with patch.object(ollama_host, 'ollama_base', return_value=base), \
                 patch.object(eta_estimator, 'hardware_fingerprint', return_value='faux-gpu|0GB'):
                call_command('bench', task='text-generation', media=f.name,
                             models='qwen3.5:4b', runs=2, stdout=sortie)
        finally:
            serveur.shutdown()
            serveur.server_close()

        # La couche HTTP : le bon chemin, un payload non streamé, le bon plafond de jetons.
        self.assertEqual([p for p, _ in recus], ['/api/generate'] * 3)       # chauffe + 2 passes
        self.assertTrue(all(c['stream'] is False and c['model'] == 'qwen3.5:4b' for _, c in recus))
        self.assertEqual([c['options']['num_predict'] for _, c in recus], [8, 300, 300])
        self.assertEqual(recus[1][1]['prompt'], "Explique la photosynthèse en trois phrases.")
        # La table : la colonne qui compare, et la valeur lue dans les champs natifs.
        texte = sortie.getvalue()
        self.assertIn('jetons/s', texte)
        self.assertIn('100.0', texte)                                        # 120 jetons / 1,2 s
        self.assertIn('3.2 s', texte)                                        # chargement à froid
        self.assertNotIn('saturé', texte)
        # La persistance : la boucle d'ETA a appris 2 passes, bucketisées par matériel.
        stat = ModelRuntimeStat.objects.get(model_key='ollama:qwen3.5:4b',
                                            hardware_fingerprint='faux-gpu|0GB')
        self.assertEqual(stat.unit, 'token')
        self.assertEqual(stat.samples, 2)
        self.assertAlmostEqual(stat.per_unit_ema_seconds, 1.2 / 120, places=6)
        self.assertAlmostEqual(stat.load_ema_seconds, 3.2, places=3)
        # …et l'estimateur la RELIT : 600 jetons → 6 s de génération + 3,2 s de chargement.
        with patch.object(eta_estimator, 'hardware_fingerprint', return_value='faux-gpu|0GB'):
            self.assertAlmostEqual(
                eta_estimator.estimate('ollama:qwen3.5:4b', size=600, unit='token'), 9.2, places=2)

    def test_le_legendage_lit_le_dict_de_la_sonde_et_rapporte_son_echec(self):
        # Régression corrigée le 14/09 : `_bench_description` appelait `.strip()` sur le dict
        # rendu par `describe_image_ollama` → chaque modèle de légendage sortait « en erreur ».
        from .services import bench, vision_probe
        with patch.object(vision_probe, 'describe_image_ollama',
                          return_value={'ok': True, 'description': 'un chat sur un mur'}):
            mesure = bench._bench_description(self.m, 'image.jpg')
        self.assertEqual(mesure['outputs'], 5)
        self.assertEqual(mesure['text'], 'un chat sur un mur')
        with patch.object(vision_probe, 'describe_image_ollama',
                          return_value={'ok': False, 'error': 'image introuvable : image.jpg'}):
            with self.assertRaises(RuntimeError) as cm:
                bench._bench_description(self.m, 'image.jpg')
        self.assertIn('introuvable', str(cm.exception))


class ProspectChainTest(TestCase):
    """« Prospecter » enchaîne bancs tiers PUIS jury (rebranché le 2026-09-23).

    The jury reads the bench in its prompt: launched side by side, it judged candidates that
    had no bench yet. And it never starts under the GPU safe mode, nor on top of a live pass.
    """

    def _run(self, *, auto=True, safe=False, running=None):
        from . import tasks, views
        with override_settings(PROSPECT_ASSESS_AUTO=auto, WAMA_GPU_SAFE_MODE=safe), \
                patch.object(tasks, 'sync_benchmarks_task') as bench, \
                patch.object(tasks, 'assess_proposed_task') as assess, \
                patch('wama.common.utils.task_progress.progression_en_cours',
                      return_value=running):
            out = views._enqueue_after_prospect()
        return out, bench, assess

    def test_bench_then_jury_in_one_chain(self):
        out, bench, assess = self._run()
        self.assertEqual(out, {'benchmarks_enqueued': True, 'assess_enqueued': True})
        bench.si.return_value.__or__.assert_called_once_with(assess.si.return_value)
        bench.si.return_value.__or__.return_value.apply_async.assert_called_once()
        bench.delay.assert_not_called()

    def test_safe_mode_keeps_the_bench_only(self):
        out, bench, assess = self._run(safe=True)
        self.assertEqual(out, {'benchmarks_enqueued': True, 'assess_enqueued': False})
        bench.delay.assert_called_once()
        assess.si.assert_not_called()

    def test_a_live_jury_pass_is_not_doubled(self):
        out, bench, assess = self._run(running={'state': 'RUNNING'})
        self.assertFalse(out['assess_enqueued'])
        bench.delay.assert_called_once()

    def test_the_setting_detaches_the_jury(self):
        out, bench, _ = self._run(auto=False)
        self.assertFalse(out['assess_enqueued'])
        bench.delay.assert_called_once()


class RejudgeOnNewFactsTest(TestCase):
    """« Une nouvelle mesure écrase les verdicts déjà rendus » (Fabien, 2026-09-23).

    Before: the pass only took `confidence IS NULL`, so a verdict given on a missing bench or a
    wrong weight stayed forever (Wan2.2-I2V-A14B at 0.15, judged before the per-component peaks).
    """

    def setUp(self):
        from .services import prospect_agents
        self.pa = prospect_agents
        self.cand = AIModel.objects.create(
            model_key='proposed:hf:org/video-5b', name='video-5b', model_type='diffusion',
            source='huggingface', hf_id='org/video-5b', is_proposed=True, proposal_kind='new',
            extra_info={'prospect': {'spec': {'kind': 'hf', 'ref': 'org/video-5b'},
                                     'quant_variants': []}})
        patcher = patch.object(prospect_agents, '_vram_totale_gb', return_value=24.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _judge_all(self, confidence=0.8):
        from contextlib import nullcontext
        pa = self.pa
        opinion = {'agent': 'fake', 'recommend': True, 'confidence': confidence,
                   'vram_fit': 'ok', 'rationale': 'r', 'concerns': ''}
        weights = {'components': {'transformer': 10.0, 'text_encoder': 11.4},
                   'total_gb': 22.5, 'largest_gb': 11.4, 'source': 'repo'}
        with patch.object(pa, '_judge', return_value=opinion) as judge, \
                patch.object(pa, '_hf_card_excerpt', return_value=''), \
                patch('wama.common.services.resource_governor.effective_free_gb', return_value=99.0), \
                patch('wama.common.services.resource_governor.vram_reservation',
                      return_value=nullcontext()), \
                patch('wama.model_manager.services.model_installer.components_for_spec',
                      return_value=weights) as weigh, \
                patch('wama.model_manager.services.model_registry.ModelRegistry.refresh_ollama_residency'):
            result = pa.assess_proposed(agents=[('google', 'fake')])
        return result, judge, weigh

    def test_a_first_pass_judges_and_weighs_the_candidate(self):
        result, judge, weigh = self._judge_all()
        self.cand.refresh_from_db()
        self.assertEqual(result['assessed'], 1)
        self.assertEqual(self.cand.extra_info['weights']['total_gb'], 22.5)
        self.assertIn('≈ 22.5 Go tout chargé', judge.call_args[0][0],
                      'the judge must see the VRAM peaks computed from the repository files')
        self.assertEqual(result['remaining'], 0)

    def test_same_facts_are_not_judged_twice(self):
        self._judge_all()
        result, judge, _ = self._judge_all()
        self.assertEqual(result['assessed'], 0)
        judge.assert_not_called()

    def test_a_new_bench_overwrites_the_verdict_and_keeps_the_previous_one(self):
        self._judge_all(confidence=0.8)
        AIModel.objects.filter(pk=self.cand.pk).update(
            benchmark_index=950.0, benchmark_meta={'scale': 'aa_elo_text_to_video'})
        result, _, weigh = self._judge_all(confidence=0.3)
        self.cand.refresh_from_db()
        self.assertEqual(result['assessed'], 1)
        self.assertEqual(self.cand.confidence, 0.3)
        self.assertIn('assess_previous', self.cand.extra_info['prospect'])
        weigh.assert_not_called()   # weights are read once, never re-asked

    def test_an_unreachable_repository_writes_no_weights(self):
        with patch('wama.model_manager.services.model_installer.components_for_spec',
                   return_value={'unreachable': 'org/video-5b'}):
            self.pa._attach_weights(self.cand)
        self.cand.refresh_from_db()
        self.assertNotIn('weights', self.cand.extra_info)

    def test_a_new_prospection_keeps_the_readings_so_nothing_is_rejudged(self):
        """write_candidate rewrote extra_info wholesale: weights and variants vanished at every
        click on « Prospecter », the facts' fingerprint changed, and EVERYTHING was re-judged."""
        from .services.prospect_ollama import write_candidate
        self._judge_all()
        prospect = dict(self.cand.extra_info['prospect'])
        write_candidate(self.cand.model_key, nom='video-5b', model_type='diffusion',
                        source='huggingface', description='refreshed', kind='new',
                        confidence=None, extra={'spec': prospect['spec']}, hf_id='org/video-5b')
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.extra_info['weights']['total_gb'], 22.5)
        self.assertIn('quant_variants', self.cand.extra_info['prospect'])
        self.assertIsNotNone(self.cand.confidence)
        self.assertFalse(self.pa._is_due(self.cand))

    def test_remote_precision_reads_each_file_header_in_subfolders(self):
        """`get_safetensors_metadata` only sees the repository root: a diffusers repository
        (Wan) keeps its weights in subfolders, so each retained file's header is read."""
        from types import SimpleNamespace

        from .services.prospector import remote_precision
        headers = {'text_encoder/model-00001.safetensors': {'F32': 3},
                   'text_encoder/model-00002.safetensors': {'F32': 2, 'I64': 1},
                   'transformer/diffusion_pytorch_model.safetensors': {'BF16': 7}}
        api = SimpleNamespace(parse_safetensors_file_metadata=lambda repo, name:
                              SimpleNamespace(parameter_count=headers[name]))
        with patch('huggingface_hub.HfApi', return_value=api):
            out = remote_precision('org/video-5b', {
                'text_encoder': [('text_encoder/model-00001.safetensors', 1),
                                 ('text_encoder/model-00002.safetensors', 1)],
                'transformer': [('transformer/diffusion_pytorch_model.safetensors', 1)],
                'config': [('model_index.json', 1)]})
        self.assertEqual(out['text_encoder']['params_by_dtype'], {'F32': 5, 'I64': 1})
        self.assertEqual(out['transformer']['params'], 7)
        self.assertNotIn('config', out, 'a role without safetensors has no precision, not zero')
