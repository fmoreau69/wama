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
    la boucle --licences du backfill a écrasé 6 auteurs curés par le slug d'organisation de
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
            call_command('backfill_platform_refs', '--licences', '--ecrire')
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
            apply=False, exporter=False)
        self.assertNotIn('author', resultat.get('poses', ()),
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

    def test_la_tache_ecrite_est_une_tache_du_catalogue(self):
        """Toute tâche rendue doit être une valeur `ModelTask` : sinon `check_model_taxonomy`
        la refuserait et `_categories_locales` ne la trouverait dans aucun banc."""
        from .models import ModelTask
        from .services.prospector import HF_TASKS, hf_task_to_wama
        connues = {t.value for t in ModelTask}
        for tache in HF_TASKS:
            for tags in ([], ['image-editing'], ['super-resolution'], ['image-captioning']):
                t, mt = hf_task_to_wama(tache, tags)
                with self.subTest(tache=tache, tags=tags):
                    self.assertIn(t, connues)


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
    """

    def test_la_tache_du_spec_est_posee_sur_la_ligne_installee(self):
        from .services import provenance as pv
        vierge = AIModel.objects.create(
            model_key='huggingface:Org/Detecteur', name='Detecteur', model_type='vision',
            source='huggingface', is_downloaded=True, hf_id='Org/Detecteur', capabilities={})
        etabli = AIModel.objects.create(
            model_key='huggingface:Org/Segmenteur', name='Segmenteur', model_type='vision',
            source='huggingface', is_downloaded=True, hf_id='Org/Segmenteur',
            capabilities={'task': 'segment'})
        spec = {'kind': 'hf', 'ref': 'Org/Detecteur', 'category': 'vision', 'task': 'detect'}
        # Ni réseau (identité HF) ni corpus (manifeste) : seule la pose de la tâche est testée.
        with patch.object(pv, 'identity_for_spec', return_value={'hf_id': 'Org/Detecteur',
                                                                 'platform_ref': 'huggingface:Org/Detecteur'}), \
                patch.object(pv, 'set_identity', return_value={'applique': True}):
            r = pv.record_after_install(spec, ['huggingface:Org/Detecteur'])
            # Un spec SANS tâche (ancien candidat, ou install par l'assistant) ne touche à rien.
            r2 = pv.record_after_install({k: v for k, v in spec.items() if k != 'task'},
                                         ['huggingface:Org/Detecteur'])
        vierge.refresh_from_db()
        etabli.refresh_from_db()
        self.assertEqual(vierge.capabilities.get('task'), 'detect')
        self.assertEqual(r.get('tache'), 'detect')
        self.assertNotIn('tache', r2)
        # La garde de concordance écarte une ligne d'un AUTRE hf_id ; et une tâche établie
        # ne s'écrase pas même quand la ligne est ciblée.
        with patch.object(pv, 'identity_for_spec', return_value={'hf_id': 'Org/Segmenteur'}), \
                patch.object(pv, 'set_identity', return_value={'applique': True}):
            pv.record_after_install({'kind': 'hf', 'ref': 'Org/Segmenteur', 'task': 'detect'},
                                    ['huggingface:Org/Segmenteur'])
        etabli.refresh_from_db()
        self.assertEqual(etabli.capabilities.get('task'), 'segment')


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
            raise bs.SourceIndisponible('arena non sollicitée par ce test')

        def open_asr():
            raise bs.SourceIndisponible('open asr non sollicité par ce test')

        def mteb():
            raise bs.SourceIndisponible('mteb non sollicité par ce test')

        # ⚠ TOUTE source du registre se patche ici : une source ajoutée à `SOURCES` sans
        # ligne ici irait au RÉSEAU depuis la suite (c'est ce que le 3ᵉ banc a failli faire).
        return patch.multiple(bs, charger_aa=aa, charger_arena=arena, charger_open_asr=open_asr,
                              charger_mteb=mteb)

    def _entree(self, nom, identite, valeur=42.0, echelle='aa_elo_text_to_image'):
        return {'nom': nom, 'slug': nom.lower().replace(' ', '-'), 'identite': identite,
                'valeur': valeur, 'echelle': echelle}


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
            r = bs.synchroniser(dry_run=True)
        # Un ALIAS est une confirmation HUMAINE : démentie par la source, elle se voit parmi
        # les non-appariés — jamais rangée comme une identité manquante.
        self.assertEqual(r['non_apparies'], ['imager:fantome [text-to-image]'])
        self.assertEqual(r['sans_identite'], [])

    def test_une_identite_illisible_est_comptee_et_distinguee_du_sans_banc(self):
        from .services import benchmark_sync as bs
        AIModel.objects.create(
            model_key='synthesizer:kokoro', name='Kokoro 82M', model_type='speech',
            source='synthesizer', is_downloaded=True,
            capabilities={'task': 'text-to-image'})   # catégorie OK, identité illisible
        with self._sources({'text-to-image': []}):
            r = bs.synchroniser(dry_run=True)
        self.assertEqual(r['sans_identite'], ['synthesizer:kokoro [text-to-image]'])
        self.assertEqual(r['non_apparies'], [])

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
            r = bs.synchroniser(dry_run=True)
        self.assertEqual(len(r['apparies']), 1)
        self.assertEqual(len(r['non_apparies']), 1)
        self.assertEqual(len(r['sans_identite']), 1)
        self.assertEqual(r['sans_categorie'], 1)
        total = (len(r['apparies']) + len(r['non_apparies'])
                 + len(r['sans_identite']) + r['sans_categorie'])
        self.assertEqual(total, AIModel.objects.count())

    def test_le_dry_run_n_ecrit_jamais_l_indice(self):
        """Garde-fou du mode dry-run : le rapport se lit sans toucher au catalogue."""
        from .services import benchmark_sync as bs
        m = AIModel.objects.create(
            model_key='imager:widget-2', name='Widget 2', model_type='diffusion',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'})
        with self._sources({'text-to-image': [self._entree('Widget 2', ('widget', (2,), None))]}):
            bs.synchroniser(dry_run=True)
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
        from .services.benchmark_sync import _compatibles
        return _compatibles(a, b, True, nom_local, nom_tiers)

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
        from .services.benchmark_sync import _compatibles
        self.assertTrue(_compatibles(('hunyuanimage', (2, 1), None),
                                     ('hunyuanimage', (2, 1), None), False))


class RegistreDesSourcesTest(TestCase):
    """
    Ajouter une plateforme de banc doit couter UNE ENTREE, pas cinq endroits touches.

    Ce test EST le contrat d'evolutivite : il declare une troisieme source fictive et verifie
    qu'elle traverse toute la chaine — chargement, appariement, index, echelle nommee, meta,
    rang — sans qu'aucune ligne du moteur ne la connaisse.
    """

    def _source_fictive(self, priorite):
        return {'cle': 'panel', 'label': 'Panel Fictif', 'priorite': priorite,
                'nom_source': 'panel', 'valeur': lambda e: e.get('note'),
                'echelle': lambda e, cat: 'panel_note_' + cat,
                'meta': lambda retenu, cands: {'panel_nom': retenu['nom']},
                'chargeur': lambda: ({'text-to-image': [
                    {'nom': 'Widget 2', 'slug': 'widget-2', 'note': 7.5,
                     'identite': ('widget', (2,), None)},
                    {'nom': 'Autre 1', 'slug': 'autre-1', 'note': 1.0,
                     'identite': ('autre', (1,), None)}]}, {})}

    def _modele(self):
        return AIModel.objects.create(
            model_key='imager:widget-2', name='Widget 2', model_type='diffusion',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'})

    def test_une_source_ajoutee_traverse_toute_la_chaine(self):
        from .services import benchmark_sync as bs
        m = self._modele()
        panel = self._source_fictive(priorite=3)
        with patch.object(bs, 'SOURCES_PAR_PRIORITE', (panel,)):
            bs.synchroniser(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 7.5)
        self.assertEqual(m.benchmark_meta['echelle'], 'panel_note_text-to-image')
        self.assertEqual(m.benchmark_meta['source'], 'panel')
        self.assertEqual(m.benchmark_meta['panel_nom'], 'Widget 2')
        # Le rang se calcule sur la population de CETTE source, pas d'une autre.
        self.assertEqual(m.benchmark_meta['rang_centile'], 50.0)
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
                {'nom': 'Widget 2', 'slug': 'widget-2', 'identite': ('widget', (2,), None),
                 'valeur': 900.0, 'echelle': 'aa_elo_text_to_image'}]}, {}

        principale = dict(bs.SOURCES_PAR_PRIORITE[0], chargeur=aa)
        panel = self._source_fictive(priorite=9)     # moins prioritaire
        with patch.object(bs, 'SOURCES_PAR_PRIORITE', (principale, panel)):
            bs.synchroniser(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 900.0)                     # la prioritaire
        self.assertEqual(m.benchmark_meta['echelle'], 'aa_elo_text_to_image')
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
        return [{'valeur': v} for v in valeurs]

    def test_le_rang_est_le_pourcentage_de_la_population_en_dessous(self):
        from .services.benchmark_sync import rang_centile
        pop = self._pop(10, 20, 30, 40)
        self.assertEqual(rang_centile(30, pop, lambda e: e['valeur']), 50.0)
        self.assertEqual(rang_centile(10, pop, lambda e: e['valeur']), 0.0)

    def test_deux_echelles_incommensurables_donnent_des_rangs_comparables(self):
        """LE point : 42,9 (Intelligence Index) et 919 (Elo TTS) ne se comparent pas ;
        leurs rangs dans leurs bancs respectifs, si."""
        from .services.benchmark_sync import rang_centile
        llm = rang_centile(42.9, self._pop(1, 5, 12, 20, 30, 42.9), lambda e: e['valeur'])
        tts = rang_centile(919, self._pop(919, 1200, 1300), lambda e: e['valeur'])
        self.assertGreater(llm, tts)

    def test_une_population_vide_ou_une_valeur_absente_rend_None(self):
        """Null plutôt que plausible : pas de rang inventé sur une population inconnue."""
        from .services.benchmark_sync import rang_centile
        self.assertIsNone(rang_centile(30, [], lambda e: e['valeur']))
        self.assertIsNone(rang_centile(None, self._pop(1, 2), lambda e: e['valeur']))

    def test_le_rang_n_ecrase_jamais_la_valeur_mesuree(self):
        """Le centile s'AJOUTE : `benchmark_index` reste la mesure, avec son échelle."""
        from .services import benchmark_sync as bs

        def aa():
            return {'text-to-image': [
                {'nom': 'Widget 2', 'slug': 'widget-2', 'identite': ('widget', (2,), None),
                 'valeur': 900.0, 'echelle': 'aa_elo_text_to_image'},
                {'nom': 'Autre 1', 'slug': 'autre-1', 'identite': ('autre', (1,), None),
                 'valeur': 100.0, 'echelle': 'aa_elo_text_to_image'}]}, {}

        def arena():
            raise bs.SourceIndisponible('non sollicitée')

        m = AIModel.objects.create(
            model_key='imager:widget-2', name='Widget 2', model_type='diffusion',
            source='imager', is_downloaded=True, capabilities={'task': 'text-to-image'})
        with patch.multiple(bs, charger_aa=aa, charger_arena=arena):
            bs.synchroniser(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 900.0)
        self.assertEqual(m.benchmark_meta['echelle'], 'aa_elo_text_to_image')
        self.assertEqual(m.benchmark_meta['rang_centile'], 50.0)
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

    def test_un_add_on_n_a_jamais_de_banc(self):
        """Une LoRA porte le nom de son modèle de base : rendue lisible, elle en prenait
        l'Elo (flux-lora-logo-design → 1083, mesuré le 02/09). Hors catégorie, par nature."""
        from .services.benchmark_sync import _categories_locales
        lora = AIModel.objects.create(
            model_key='imager:flux-lora-logo-design', name='FLUX LoRA Logo', model_type='diffusion',
            source='imager', is_downloaded=True, hf_id='Shakker-Labs/FLUX.1-dev-LoRA-Logo-Design',
            capabilities={'task': 'text-to-image'})
        self.assertEqual(_categories_locales(lora), [])
        plein = AIModel.objects.create(
            model_key='imager:flux-1-dev', name='FLUX.1 dev', model_type='diffusion',
            source='imager', is_downloaded=True, hf_id='black-forest-labs/FLUX.1-dev',
            capabilities={'task': 'text-to-image'})
        self.assertEqual(_categories_locales(plein), ['text-to-image'])


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
            bs.synchroniser(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 900.0)
        self.assertEqual(m.benchmark_meta['echelle'], 'aa_elo_text_to_video')
        self.assertEqual(m.benchmark_meta['categorie'], 'text-to-video')
        self.assertEqual(len(m.benchmark_meta['bancs']), 1)

    def test_deux_metiers_donnent_deux_bancs_l_index_restant_sur_le_principal(self):
        from .services import benchmark_sync as bs
        m = self._ltx(['text-to-video', 'image-to-video'])
        with self._sources({
                'text-to-video': [self._entree('LTX Video v0.9.8 13B', ('ltxvideo', (0, 9, 8), 13.0),
                                               valeur=900.0, echelle='aa_elo_text_to_video')],
                'image-to-video': [self._entree('LTX Video v0.9.8 13B', ('ltxvideo', (0, 9, 8), 13.0),
                                                valeur=1180.0, echelle='aa_elo_image_to_video')]}):
            bs.synchroniser(dry_run=False)
        m.refresh_from_db()
        bancs = m.benchmark_meta['bancs']
        self.assertEqual([b['categorie'] for b in bancs], ['text-to-video', 'image-to-video'])
        self.assertEqual([b['valeur'] for b in bancs], [900.0, 1180.0])
        # L'index porté reste celui du métier PRINCIPAL — le second banc, mieux noté, ne
        # doit pas s'y substituer : 1180 et 900 ne sont pas sur la même échelle.
        self.assertEqual(m.benchmark_index, 900.0)
        self.assertEqual(m.benchmark_meta['echelle'], 'aa_elo_text_to_video')

    def test_un_metier_ecrit_dans_le_vocabulaire_d_une_plateforme_est_traduit(self):
        """`canonical_task` est le résolveur EXISTANT : une tâche en vocabulaire HF ne doit
        pas rester sans catégorie (leçon du 31/08 — deux vocabulaires se rejoignent sur un
        repli qui a l'air de marcher)."""
        from .services import benchmark_sync as bs
        self.assertEqual(bs._categories_locales(self._ltx(['text-to-video'])), ['text-to-video'])
        m = AIModel.objects.create(
            model_key='transcriber:whisper', name='Whisper', model_type='speech',
            source='transcriber', is_downloaded=True,
            capabilities={'task': 'automatic-speech-recognition'})
        # Jusqu'au 02/09 l'ASR n'avait aucun banc tiers et ce test attendait `[]` — la
        # TRADUCTION est ce qu'il protège : le vocabulaire HF doit aboutir au même banc
        # que le nôtre (`transcription`), jamais à un repli hasardeux.
        self.assertEqual(bs._categories_locales(m), ['speech-to-text-fr', 'speech-to-text'])
        m.capabilities = {'task': 'transcription'}
        self.assertEqual(bs._categories_locales(m), ['speech-to-text-fr', 'speech-to-text'])

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
        self.assertEqual(bs._categories_locales(_propose('qwen3-embedding', 'embedding')), ['embedding'])
        # Un VLM reste éligible au banc texte — et depuis l'après-midi du 02/09 l'arène
        # `vision` est son banc PRINCIPAL (cf. `TroisiemeBancEtSensTest`).
        self.assertEqual(bs._categories_locales(_propose('minicpm-v4.6', 'vlm')), ['vision', 'llm'])
        self.assertEqual(bs._categories_locales(_propose('qwen3-coder', 'llm')), ['llm'])
        # Et l'INSTALLÉ, dont la découverte a écrit les capacités : `completion` fait foi
        # avant le type — le comportement du 19/08 (bge-m3) est inchangé.
        m = AIModel.objects.create(
            model_key='ollama:bge-m3:latest', name='bge-m3', model_type='embedding',
            source='ollama', is_downloaded=True, capabilities={'completion': False})
        self.assertEqual(bs._categories_locales(m), [])


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
            benchmark_index=index, benchmark_meta={'echelle': echelle} if echelle else {})

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

    def _panel(self, cats, sens=None, priorite=3):
        """Source fictive rendant `cats` = {catégorie: [entrées {'nom','identite','note'}]}."""
        d = {'cle': 'panel', 'label': 'Panel Fictif', 'priorite': priorite,
             'nom_source': 'panel', 'valeur': lambda e: e.get('note'),
             'echelle': lambda e, cat: 'panel_note_' + cat,
             'meta': lambda retenu, cands: {'panel_nom': retenu['nom']},
             'chargeur': lambda: (dict(cats), {})}
        if sens:
            d['sens'] = sens
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
        self.assertEqual(bs._categories_locales(llm_vision), ['llm', 'vision'])
        # VLM : l'arène `vision` est son métier principal, le texte secondaire.
        self.assertEqual(bs._categories_locales(vlm), ['vision', 'llm'])
        # Transcription : le FRANÇAIS d'abord (ce que le transcriber fait ici), l'anglais après.
        self.assertEqual(bs._categories_locales(asr), ['speech-to-text-fr', 'speech-to-text'])

    def test_l_arene_vision_exige_la_taille_comme_le_banc_llm(self):
        """`gemma4:12b` a DEUX identités locales : (gemma,(4,),12) par le tag, (gemma,(4,),None)
        par le nom. Sans taille stricte, la seconde apparie `gemma-4-31b` — mesuré le 02/09."""
        from .services import benchmark_sync as bs
        m = AIModel.objects.create(
            model_key='ollama:gemma4:12b', name='Gemma 4', model_type='llm', source='ollama',
            is_downloaded=True,
            capabilities={'task': 'text-generation', 'completion': True, 'vision': True})
        panel = self._panel({'vision': [
            {'nom': 'gemma-4-31b', 'identite': ('gemma', (4,), 31.0), 'note': 1276.0}]})
        with patch.object(bs, 'SOURCES_PAR_PRIORITE', (panel,)), \
                patch.object(bs, '_tag_reel', return_value=''):
            r = bs.synchroniser(dry_run=False)
        m.refresh_from_db()
        self.assertIsNone(m.benchmark_index, "12B ne doit pas hériter de l'Elo du 31B")
        self.assertIn('ollama:gemma4:12b [llm]', r['non_apparies'])
        # Et la bonne taille, elle, apparie — la règle refuse l'asymétrie, pas la catégorie.
        panel_ok = self._panel({'vision': [
            {'nom': 'gemma-4-12b', 'identite': ('gemma', (4,), 12.0), 'note': 1200.0}]})
        with patch.object(bs, 'SOURCES_PAR_PRIORITE', (panel_ok,)), \
                patch.object(bs, '_tag_reel', return_value=''):
            bs.synchroniser(dry_run=False)
        m.refresh_from_db()
        self.assertEqual(m.benchmark_index, 1200.0)
        self.assertEqual(m.benchmark_meta['categorie'], 'vision')

    def test_charger_aa_ne_requete_pas_les_categories_sans_endpoint(self):
        """`vision`, `document` et l'ASR n'ont pas d'endpoint AA : ni requête, ni motif."""
        from .services import benchmark_sync as bs
        urls = []

        def faux_http(url, headers=None, timeout=45):
            urls.append(url)
            return {'data': []}
        with patch.object(bs, '_http_json', side_effect=faux_http), \
                patch.dict('os.environ', {bs.AA_KEY_ENV: 'cle-factice'}):
            with self.assertRaises(bs.SourceIndisponible):   # réponses vides → indisponible
                bs.charger_aa()
        attendues = sum(1 for spec in bs.CATEGORIES.values() if spec.get('aa'))
        self.assertEqual(len(urls), attendues)
        self.assertFalse(any('None' in u for u in urls))

    # ── (2) le sens de l'échelle ────────────────────────────────────────────────────────

    def test_un_taux_d_erreur_se_lit_a_l_envers(self):
        from .services.benchmark_sync import _choose_variant, rang_centile, valeur_ordonnable
        pop = [{'v': x} for x in (2.0, 4.0, 6.0, 8.0)]
        # 5 % de WER bat les 6 et 8 : 50ᵉ centile — pas 25ᵉ comme pour un score.
        self.assertEqual(rang_centile(5.0, pop, lambda e: e['v'], sens='bas'), 50.0)
        self.assertEqual(rang_centile(5.0, pop, lambda e: e['v']), 50.0)
        self.assertEqual(rang_centile(2.0, pop, lambda e: e['v'], sens='bas'), 75.0)
        # Dernier recours de `_choose_variant` : la valeur la PIRE — la plus haute en WER.
        cands = [{'nom': 'x a', 'v': 3.0}, {'nom': 'x b', 'v': 9.0}]
        self.assertEqual(_choose_variant('x', cands, lambda e: e['v'], sens='bas')['v'], 9.0)
        self.assertEqual(_choose_variant('x', cands, lambda e: e['v'])['v'], 3.0)
        # `valeur_ordonnable` : plus grand = meilleur, quel que soit le sens.
        m_wer = AIModel(model_key='a', benchmark_index=5.0, benchmark_meta={'sens': 'bas'})
        m_elo = AIModel(model_key='b', benchmark_index=5.0, benchmark_meta={'sens': 'haut'})
        m_nu = AIModel(model_key='c', benchmark_index=5.0, benchmark_meta={})
        self.assertEqual(valeur_ordonnable(m_wer), -5.0)
        self.assertEqual(valeur_ordonnable(m_elo), 5.0)
        self.assertEqual(valeur_ordonnable(m_nu), 5.0)
        self.assertIsNone(valeur_ordonnable(AIModel(model_key='d')))

    def test_un_banc_a_sens_bas_traverse_la_chaine_et_ordonne_a_l_endroit(self):
        from .services import benchmark_sync as bs
        bon = AIModel.objects.create(
            model_key='transcriber:bon-2', name='Bon 2', model_type='speech',
            source='transcriber', is_downloaded=True, capabilities={'task': 'transcription'})
        moyen = AIModel.objects.create(
            model_key='transcriber:moyen-2', name='Moyen 2', model_type='speech',
            source='transcriber', is_downloaded=True, capabilities={'task': 'transcription'})
        panel = self._panel({'speech-to-text-fr': [
            {'nom': 'org/bon-2', 'identite': ('bon', (2,), None), 'note': 4.0},
            {'nom': 'org/moyen-2', 'identite': ('moyen', (2,), None), 'note': 8.0},
            {'nom': 'org/pire-2', 'identite': ('pire', (2,), None), 'note': 20.0}]}, sens='bas')
        with patch.object(bs, 'SOURCES_PAR_PRIORITE', (panel,)):
            bs.synchroniser(dry_run=False)
        bon.refresh_from_db()
        moyen.refresh_from_db()
        self.assertEqual(bon.benchmark_index, 4.0)
        self.assertEqual(bon.benchmark_meta['sens'], 'bas')
        self.assertEqual(bon.benchmark_meta['echelle'], 'panel_note_speech-to-text-fr')
        # Centile INVERSÉ : 4 % de WER bat 8 et 20 → 66,7ᵉ ; 8 ne bat que 20 → 33,3ᵉ.
        self.assertEqual(bon.benchmark_meta['rang_centile'], 66.7)
        self.assertEqual(moyen.benchmark_meta['rang_centile'], 33.3)
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
                par_cat, motifs = bs.charger_open_asr()
        self.assertEqual(motifs, {})
        en_entrees = {e['nom']: e for e in par_cat['speech-to-text']}
        fr_entrees = {e['nom']: e for e in par_cat['speech-to-text-fr']}
        # parakeet : version APRÈS la taille → pas d'identité lisible → sauté (null > plausible)
        self.assertEqual(set(en_entrees), {'openai/whisper-large-v3', 'Qwen/Qwen3-ASR-1.7B-hf'})
        w = en_entrees['openai/whisper-large-v3']
        self.assertEqual(w['wer'], 5.78)                       # colonne `avg` telle quelle
        self.assertEqual(w['identite'], ('whisperlarge', (3,), None))
        self.assertEqual(w['rtfx'], 120.5)
        self.assertEqual(w['licence'], 'apache-2.0')
        self.assertEqual(w['jeux'], {'LS Clean': 1.56, 'AMI': 14.86})
        q = fr_entrees['Qwen/Qwen3-ASR-1.7B-hf']
        self.assertEqual(q['identite'], ('qwen', (3,), 1.7))
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
                patch.object(bs, '_mteb_marqueurs', return_value=set()), \
                patch.object(bs, '_mteb_cache_path', return_value=Path(tmp) / 'c.json'), \
                patch('requests.get', side_effect=self._faux_get):
            par_cat, motifs = bs.charger_mteb()
            # 2ᵉ passe : les modèles LUS viennent du cache — aucune requête pour eux ; seul
            # `reseau-4` (échec passager, jamais mis en cache) est retenté.
            def relecture(url, **kw):
                if 'Org__reseau-4' not in url:
                    raise AssertionError('réseau interdit pour un modèle déjà lu : ' + url)
                return self._faux_get(url)
            with patch('requests.get', side_effect=relecture):
                par_cat2, _ = bs.charger_mteb()
        noms = {e['nom']: e for e in par_cat['embedding']}
        self.assertEqual(set(noms), {'BAAI/bge-m3', 'Qwen/Qwen3-Embedding-0.6B',
                                     'intfloat/multilingual-e5-small'})
        self.assertEqual(noms['BAAI/bge-m3']['score'], 60.0)
        self.assertEqual(len(noms['BAAI/bge-m3']['taches']), 4)
        self.assertEqual(noms['Qwen/Qwen3-Embedding-0.6B']['identite'], ('qwen', (3,), 0.6))
        self.assertIsNone(noms['BAAI/bge-m3']['identite'])              # d'où l'ALIAS
        self.assertIn('1 modèle(s) non lus', motifs['embedding'])
        self.assertEqual(par_cat2['embedding'], par_cat['embedding'])

    def test_bge_m3_du_rag_prend_son_banc_par_alias_et_les_embeddings_proposes_ont_une_categorie(self):
        from .services import benchmark_sync as bs
        bge = AIModel.objects.create(
            model_key='ollama:bge-m3:latest', name='bge-m3:latest', model_type='embedding',
            source='ollama', is_downloaded=True,
            capabilities={'task': 'feature-extraction', 'embedding': True, 'completion': False})
        propose = AIModel.objects.create(
            model_key='proposed:ollama:qwen3-embedding:latest', name='qwen3-embedding:latest',
            model_type='embedding', source='ollama', is_proposed=True, capabilities={})
        self.assertEqual(bs._categories_locales(bge), ['embedding'])
        self.assertEqual(bs._categories_locales(propose), ['embedding'])
        mteb = next(s for s in bs.SOURCES if s['cle'] == 'mteb')
        entrees = [{'nom': 'BAAI/bge-m3', 'slug': 'BAAI/bge-m3', 'identite': None, 'score': 61.2,
                    'taches': {}, 'revision': 'r'},
                   {'nom': 'intfloat/multilingual-e5-small', 'slug': 'intfloat/multilingual-e5-small',
                    'identite': ('multilinguale', (5,), None), 'score': 50.0, 'taches': {}, 'revision': 'r'}]
        src = dict(mteb, chargeur=lambda: ({'embedding': entrees}, {}))
        with patch.object(bs, 'SOURCES_PAR_PRIORITE', (src,)):
            r = bs.synchroniser(dry_run=False)
        bge.refresh_from_db()
        self.assertEqual(bge.benchmark_index, 61.2)
        self.assertEqual(bge.benchmark_meta['echelle'], 'mteb_fr_retrieval')
        self.assertEqual(bge.benchmark_meta['alias_declare'], 'BAAI/bge-m3')
        self.assertEqual(bge.benchmark_meta['rang_centile'], 50.0)
        self.assertIn('proposed:ollama:qwen3-embedding:latest [embedding]', r['non_apparies'])
