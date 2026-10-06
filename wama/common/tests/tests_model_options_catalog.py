"""Route F4b — les OPTIONS d'un select de modèle viennent du CATALOGUE (portages 2026-09-08).

Le critère de grille `model_options_catalog` mesure la DÉCLARATION ; ces tests mesurent ce
qu'elle produit. Trois familles, et chacune est née d'un défaut MESURÉ ce jour-là :

  1. le domaine déclaré rend bien les options que l'app attend — clés comprises : `source`
     dans la requête ⇒ identifiants NUS, l'espace de clés que la colonne de l'app porte déjà ;
  2. un `model_type` EXPLICITE borne le domaine MÊME avec une `source` — il était ignoré en
     silence, et l'enhancer y gagnait 2 moteurs audio dans son select d'upscaling ;
  3. les CHIPS de card résolvent les libellés du même domaine — la résolution passait
     `source` deux fois et l'exception était avalée, donc la card serait retombée sur la
     clé technique sans que rien ne le dise.

⚠ Les cas sont SEMÉS : un TestCase mesure la base de TEST (0 modèle). L'état réel du parc se
lit par `check_app_conformity` et par l'endpoint, jamais ici.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from wama.common.utils.auto_model import catalog_domain
from wama.common.utils.param_schema import schema_for_app
from wama.model_manager.models import AIModel
from wama.model_manager.services import get_registry_models

URL = '/model-manager/api/models/options/'


def _modele(cle, nom, *, model_type, task, vram=1.0, downloaded=True):
    return AIModel.objects.create(
        model_key=cle, name=nom, model_type=model_type,
        source=cle.split(':')[0], vram_gb=vram,
        is_available=True, is_downloaded=downloaded, is_proposed=False,
        capabilities={'task': task})


def _schemas(app):
    """TOUS les schémas déclarés par l'app, pas seulement le principal.

    ⚠ `schema_for_app` n'expose que l'attribut PRINCIPAL : une app bi-domaine (enhancer
    MEDIA+AUDIO, imager IMAGE+VIDEO) y perd la moitié de ses champs — c'est le trou #10 du
    manifeste, et `declared_param_schemas` est l'accesseur écrit pour le combler. Une garde
    qui ne lirait que le principal serait aveugle exactement là où deux domaines coexistent,
    c'est-à-dire là où une erreur de domaine est le plus probable.
    """
    from wama.common.utils.param_schema import declared_param_schemas
    declares = declared_param_schemas(app)
    if declares and declares.get('schemas'):
        return [p for s in declares['schemas'].values() for p in (s or [])]
    return schema_for_app(app) or []


def _champ(app, nom):
    for f in _schemas(app):
        if f.get('name') == nom:
            return f
    raise AssertionError(f'{app}: aucun champ « {nom} » au schéma')


class ModelTypeExpliciteTest(TestCase):
    """Le défaut de la brique : `model_type` ne jouait que SANS `source`."""

    def setUp(self):
        _modele('enhancer:BSRGANx4', 'BSRGAN x4', model_type='upscaling', task='upscale')
        _modele('enhancer:IRCNN_Lx1', 'IRCNN-L', model_type='upscaling', task='denoise')
        _modele('enhancer:resemble', 'Resemble', model_type='speech', task='audio-enhance')

    def test_le_model_type_borne_le_domaine_meme_avec_une_source(self):
        choix, _ = get_registry_models('enhancer', model_type='upscaling')
        self.assertEqual(sorted(c[0] for c in choix), ['BSRGANx4', 'IRCNN_Lx1'],
                         "un select d'upscaling ne doit pas proposer un débruiteur de voix")

    def test_sans_model_type_la_source_rend_tout_son_parc(self):
        choix, _ = get_registry_models('enhancer')
        self.assertEqual(len(choix), 3)

    def test_un_model_type_sans_candidat_ne_reelargit_pas_la_liste(self):
        """Le repli « liste non filtrée » existe pour les CAPACITÉS absentes du catalogue ;
        il ne doit jamais annuler une borne de catégorie explicitement demandée."""
        choix, _ = get_registry_models('enhancer', model_type='diffusion')
        self.assertEqual(choix, [])

    def test_l_endpoint_transmet_les_deux_bornes(self):
        user = get_user_model().objects.create_user(username='f4b_mt', password='x')
        client = Client()
        client.force_login(user)
        r = client.get(URL, {'source': 'enhancer', 'model_type': 'upscaling'})
        self.assertEqual(r.status_code, 200)
        valeurs = [o[0] if isinstance(o, list) else o['value']
                   for g in r.json()['groups'] for o in g['options']]
        self.assertEqual(sorted(valeurs), ['BSRGANx4', 'IRCNN_Lx1'])


class DomainesDeclaresParLesAppsTest(TestCase):
    """Pour chaque app portée : le domaine du schéma rend les valeurs que l'app STOCKE."""

    def setUp(self):
        _modele('reader:olmocr', 'olmOCR-2 7B', model_type='ocr', task='ocr', vram=14)
        _modele('reader:doctr', 'docTR', model_type='ocr', task='ocr', vram=1)
        _modele('reader:glm-ocr', 'GLM-OCR', model_type='ocr', task='ocr', vram=2.2)
        _modele('enhancer:BSRGANx4', 'BSRGAN x4', model_type='upscaling', task='upscale')
        _modele('enhancer:resemble', 'Resemble', model_type='speech', task='audio-enhance')
        _modele('enhancer:deepfilternet', 'DeepFilterNet 3', model_type='speech',
                task='audio-enhance')

    def _options(self, champ):
        d = dict(champ.get('options_query') or {})
        choix, _ = get_registry_models(d.pop('source', None), **d)
        return sorted(c[0] for c in choix)

    def test_le_reader_tire_ses_3_moteurs_OCR_en_cles_nues(self):
        champ = _champ('reader', 'backend')
        self.assertEqual(champ.get('options_source'), 'catalog')
        self.assertEqual(self._options(champ), ['doctr', 'glm-ocr', 'olmocr'])

    def test_les_cles_du_reader_sont_celles_que_sa_colonne_porte(self):
        """`ReadingItem.backend` stocke 'olmocr' ; `backend_for_key('reader:' + …)` recompose.
        Une option en clé ENTIÈRE (`reader:olmocr`) serait un changement d'espace de clés."""
        from wama.reader.models import ReadingItem
        stockees = {v for v, _ in ReadingItem.Backend.choices} - {'auto'}
        self.assertTrue(stockees <= set(self._options(_champ('reader', 'backend'))))

    def test_le_reader_declare_le_MEME_domaine_que_sa_resolution_auto(self):
        """`_select_best_backend` interroge `select_model_id('reader', task='ocr')` : le
        select PROPOSE et « auto » TIRE dans le même inventaire, par construction."""
        self.assertEqual(catalog_domain('reader'), {'source': 'reader', 'task': 'ocr'})

    def test_le_reader_sert_auto_en_premiere_option(self):
        self.assertTrue(_champ('reader', 'backend').get('options_auto'),
                        "le reader RÉSOUT « auto » au lancement — l'option doit être servie")

    def test_l_enhancer_separe_ses_deux_domaines(self):
        """Route F4b ⑤ (2026-10-06) : le média passe à la TÂCHE et aux clés ENTIÈRES (ce que
        `Enhancement.ai_model` stocke depuis `0018`) ; l'audio garde ses clés nues."""
        media = _champ('enhancer', 'ai_model')
        audio = _champ('enhancer', 'engine')
        self.assertEqual(self._options(media), ['enhancer:BSRGANx4'])
        self.assertEqual(self._options(audio), ['deepfilternet', 'resemble'])

    def test_the_enhancer_serves_auto_for_media_and_for_audio(self):
        """INVERSÉ le 2026-09-21 (curseur C, décision de Fabien) : ce test gardait « l'enhancer
        ne sert PAS auto — l'utilisateur désigne son moteur ». Le lancement résout désormais
        les deux branches (`enhancer/utils/auto_model.py`) ; servir « auto » sans résolution
        serait le seul défaut, et c'est ce que `EveryAutoSelectCarriesTheSliderTest` garde."""
        for nom in ('ai_model', 'engine'):
            self.assertTrue(_champ('enhancer', nom).get('options_auto'), nom)

    def test_les_valeurs_ECRITES_EN_DUR_restent_le_repli_rendu(self):
        """Les `choices` ne sont pas retirés d'une app en clés NUES (le reader) : ils
        s'affichent avant que la requête réponde, et servent de repli si le catalogue est
        injoignable. ⚠ Une app passée aux clés ENTIÈRES les retire (enhancer, 2026-10-06, comme
        le transcriber) : l'ancienne liste ramènerait l'ancien espace de clés — son pré-rendu
        vient du catalogue (`auto_model.catalog_choices`)."""
        self.assertTrue(_champ('reader', 'backend').get('choices'))
        self.assertFalse(_champ('enhancer', 'ai_model').get('choices'))


class TheCriterionSeesTheDomainTest(TestCase):
    """`model_options_catalog` was GREEN with a domain bounded by `source` (enhancer, 08/09 →
    06/10): Swin2SR, installed and launchable, was absent from the select and the grid did not see
    it. The criterion now reads the DECLARED domains (every schema of the app) — run on the real
    apps, no fixture."""

    def _measure(self, app):
        from wama.common.services.conformity_checker import _AppFiles, _model_options_from_catalog
        return _model_options_from_catalog(_AppFiles(app))

    def test_a_domain_by_task_is_green(self):
        self.assertIs(True, self._measure('transcriber')[0])

    def test_a_domain_by_source_is_partial_and_names_the_select(self):
        state, evidence = self._measure('reader')
        self.assertEqual('partial', state)
        self.assertIn('backend', evidence)

    def test_one_select_by_source_among_two_is_enough_to_say_it(self):
        """The enhancer's media select is by task since 06/10; its AUDIO select is still by source
        — the second schema (`AUDIO_PARAMS_JSON`) would be invisible to `schema_for_app`."""
        state, evidence = self._measure('enhancer')
        self.assertEqual('partial', state)
        self.assertIn('engine', evidence)
        self.assertNotIn('ai_model', evidence)


class InvariantDesDeclarationsTest(TestCase):
    """Vrai pour TOUTE app, aujourd'hui et demain — c'est la garde qui survit aux portages."""

    def test_toute_declaration_catalog_porte_un_domaine(self):
        """Sans `options_query`, l'endpoint répond 400 (« un select sans domaine listerait
        tout le catalogue ») : le select resterait VIDE, et un select vide ne lève pas."""
        from wama.common.app_registry import APP_CATALOG
        for app in APP_CATALOG:
            for champ in _schemas(app):
                if champ.get('options_source') != 'catalog':
                    continue
                q = champ.get('options_query') or {}
                self.assertTrue(
                    q.get('task') or q.get('model_type') or q.get('source'),
                    f"{app}.{champ.get('name')} : `options_source='catalog'` sans domaine "
                    f"(task / model_type / source) — l'endpoint refuserait en 400")

    def test_aucun_domaine_ne_porte_une_capacite_requise(self):
        """LISTER N'EST PAS POUVOIR CHOISIR (INPUT_MODEL_MATCHING §2) : les entrées fournies
        GRISENT côté client, elles n'excluent jamais côté serveur."""
        from wama.common.app_registry import APP_CATALOG
        interdits = {'available_inputs', 'consumes', 'requires'}
        for app in APP_CATALOG:
            for champ in _schemas(app):
                if champ.get('options_source') != 'catalog':
                    continue
                illicites = interdits & set(champ.get('options_query') or {})
                self.assertEqual(illicites, set(),
                                 f"{app}.{champ.get('name')} : {illicites} borne le domaine "
                                 f"côté serveur au lieu de griser côté client")


class ChipsDeCardTest(TestCase):
    """La card affiche le NOM du modèle, pas sa clé — y compris pour un domaine à `source`."""

    def setUp(self):
        _modele('reader:olmocr', 'olmOCR-2 7B', model_type='ocr', task='ocr', vram=14)
        from wama.common.utils import card_chips
        card_chips._CATALOGUE_MEMO.clear()

    def test_un_domaine_a_source_se_resout_au_lieu_de_lever(self):
        """`get_registry_models(None, source=…)` levait « multiple values for argument
        'source' » — et le except l'avalait : la card serait retombée sur la clé nue."""
        from wama.common.utils.card_chips import _inventaire_catalogue
        plates = _inventaire_catalogue({'source': 'reader', 'task': 'ocr'})
        self.assertEqual(plates, [('olmocr', 'olmOCR-2 7B')])

    def test_un_modele_hors_plaques_statiques_s_affiche_par_son_NOM(self):
        """Le cas que la route F4b existe pour rendre possible : un modèle installé APRÈS
        coup. La garde `not _plates` l'aurait affiché en clé technique sur la card."""
        from wama.common.utils.card_chips import chips_for
        _modele('reader:un-ocr-installe-apres', 'OCR arrivé après', model_type='ocr',
                task='ocr')
        from wama.common.utils import card_chips
        card_chips._CATALOGUE_MEMO.clear()

        class _Item:
            backend = 'un-ocr-installe-apres'

        champ = dict(_champ('reader', 'backend'))
        libelles = [c['label'] for c in chips_for(_Item(), [champ])]
        self.assertIn('OCR arrivé après', libelles)

    def test_une_plaque_statique_garde_la_PRIORITE(self):
        """Joindre le catalogue ne réécrit aucun libellé existant (premier match gagne)."""
        from wama.common.utils.card_chips import chips_for

        class _Item:
            backend = 'olmocr'

        champ = dict(_champ('reader', 'backend'))
        champ['choices'] = [('olmocr', 'Libellé du schéma')]
        libelles = [c['label'] for c in chips_for(_Item(), [champ])]
        self.assertIn('Libellé du schéma', libelles)


def _model(key, name, *, task, inputs=None, model_type='vision'):
    return AIModel.objects.create(
        model_key=key, name=name, model_type=model_type, source=key.split(':')[0], vram_gb=1.0,
        is_available=True, is_downloaded=True, is_proposed=False,
        capabilities={'task': task, **({'inputs_required': inputs} if inputs else {})})


class ModeBoundOptionsTest(TestCase):
    """A model menu BOUNDED BY THE ELEMENT'S MODE (2026-09-27, `Param.options_mode`).

    The mode is a declared domain bound (`app_modes.mode_param`), never an input the user
    provides: what it imposes on the model is DERIVED from its declaration
    (`mode_model_filter`). Seeded on the anonymizer, the first app to declare it."""

    def setUp(self):
        _model('anonymizer:yolo:a.pt', 'YOLO a', task='detect')
        _model('anonymizer:yolo:b-seg.pt', 'YOLO b seg', task='segment')
        _model('anonymizer:sam3', 'SAM3', task='segment', inputs=['work_file', 'prompt'])
        _model('anonymizer:yolo:p-pose.pt', 'YOLO pose', task='pose')
        user = get_user_model().objects.create_user(username='mode_bound', password='x')
        self.client = Client()
        self.client.force_login(user)

    def _values(self, **query):
        r = self.client.get(URL, {'source': 'anonymizer', 'task': 'detect,segment', **query})
        self.assertEqual(r.status_code, 200)
        return [(g.get('group'), sorted(o[0] if isinstance(o, list) else o['value']
                                        for o in g['options'])) for g in r.json()['groups']]

    def test_several_tasks_bound_the_domain_together(self):
        values = {v for _, vs in self._values() for v in vs}
        self.assertEqual({'yolo:a.pt', 'yolo:b-seg.pt', 'sam3'}, values,
                         'a pose model has no place in a menu of detection and segmentation')

    def test_each_mode_keeps_the_models_that_serve_it(self):
        mode = {'app': 'anonymizer', 'domain': 'image_video'}
        classes = {v for _, vs in self._values(mode='classes', **mode) for v in vs}
        description = {v for _, vs in self._values(mode='description', **mode) for v in vs}
        self.assertEqual({'yolo:a.pt', 'yolo:b-seg.pt'}, classes,
                         'a model that REQUIRES a description cannot serve the classes mode')
        self.assertEqual({'sam3'}, description,
                         'a model that ignores the description does not serve that mode')

    def test_the_menu_is_grouped_by_task_with_the_catalogue_labels(self):
        groups = dict(self._values(group='task', auto='1'))
        self.assertEqual(['auto'], groups.get(None), '« auto » heads the menu, outside any group')
        # Chaque groupe DIT aussi où tournent ses modèles (2026-10-05).
        self.assertEqual(['yolo:a.pt'], groups.get('Détection — WAMA local'))
        self.assertEqual(['sam3', 'yolo:b-seg.pt'], groups.get('Segmentation — WAMA local'))

    def test_a_multi_task_menu_announces_no_forecast(self):
        """The app settles « auto » at launch with what the domain does not say (the element's
        classes): a forecast by capability alone would name another model."""
        r = self.client.get(URL, {'source': 'anonymizer', 'task': 'detect,segment', 'auto': '1'})
        self.assertNotIn('auto_preview', r.json())


class ModeDeclarationsTest(TestCase):
    """True for EVERY app: a declared mode is a real setting of the app's schema."""

    def test_every_mode_param_is_a_schema_setting_whose_values_are_the_mode_ids(self):
        from wama.common.utils.app_modes import APP_MODES
        checked = 0
        for app, spec in APP_MODES.items():
            for domain in spec.get('domains') or []:
                param = domain.get('mode_param')
                if not param:
                    continue
                with self.subTest(app=app, domain=domain['id']):
                    field = _champ(app, param)
                    values = {c[0] for c in field.get('choices') or []}
                    self.assertEqual({m['id'] for m in domain.get('modes') or []}, values)
                    self.assertIn(field.get('default'), values)
                    self.assertIn('panel', field.get('contexts') or ())
                    checked += 1
        self.assertGreaterEqual(checked, 1, 'the anonymizer declares its mode')

    def test_every_options_mode_points_at_a_declared_mode_param(self):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.app_modes import mode_param
        for app in APP_CATALOG:
            for field in _schemas(app):
                om = field.get('options_mode')
                if not om:
                    continue
                with self.subTest(app=app, field=field.get('name')):
                    self.assertEqual(field.get('options_source'), 'catalog')
                    self.assertEqual(om.get('field'), mode_param(om.get('app'), om.get('domain')))


class CatalogKeySemanticsTest(TestCase):
    """ONE reading of a catalogue key for all of WAMA (`model_keys`, 2026-09-29, imager F4b).

    Only the FIRST segment is the source, and a source is RECOGNISED by `ModelSource`: the
    `split` / `rsplit` variants disagreed on an Ollama tag (`qwen3:4b` vs `4b`)."""

    def test_only_the_first_segment_is_the_source(self):
        from wama.common.utils.model_keys import model_id, split_key
        self.assertEqual(('ollama', 'qwen3:4b'), split_key('ollama:qwen3:4b'))
        self.assertEqual('yolo:yolo11n.pt', model_id('anonymizer:yolo:yolo11n.pt'))
        self.assertEqual('Org/Model', model_id('huggingface:Org/Model'))

    def test_a_head_that_is_not_a_source_leaves_the_value_bare(self):
        from wama.common.utils.model_keys import split_key
        self.assertEqual(('', 'qwen3:4b'), split_key('qwen3:4b'),
                         "an Ollama tag's colon does not make a source")
        self.assertEqual(('', 'hunyuan-image-2.1'), split_key('hunyuan-image-2.1'))

    def test_a_bare_id_joins_the_app_space_and_a_key_is_kept(self):
        from wama.common.utils.model_keys import catalog_key
        self.assertEqual('imager:sdxl', catalog_key('sdxl', 'imager'))
        self.assertEqual('huggingface:Org/X', catalog_key('huggingface:Org/X', 'imager'))
        self.assertEqual('ollama:qwen3:4b', catalog_key('qwen3:4b', 'ollama'))
        self.assertEqual('auto', catalog_key('auto', 'imager'), '« auto » is not a model')
        self.assertEqual('', catalog_key('', 'imager'))

    def test_the_eta_key_of_a_full_key_is_the_key_itself(self):
        from wama.model_manager.services.eta_estimator import make_key
        self.assertEqual('huggingface:Org/X', make_key('synthesizer', 'huggingface:Org/X'),
                         'a key of ANOTHER source must not be prefixed by the app')
        self.assertEqual('imager:sdxl', make_key('imager', 'sdxl'))


class CategoryGroupedOptionsTest(TestCase):
    """`group=category`: a few models DISTINGUISHED (the imager's logos), the others unranked.

    The category is a canonical capability (`CATEGORY_LABELS`): the grouping is generic, any
    app that declares `options_group="category"` gets it."""

    def setUp(self):
        _model('imager:plain-a', 'Plain A', task='text-to-image', model_type='diffusion')
        m = _model('imager:logo-b', 'Logo B', task='text-to-image', model_type='diffusion')
        m.capabilities = {**m.capabilities, 'category': 'logo'}
        m.save(update_fields=['capabilities'])
        user = get_user_model().objects.create_user(username='category_group', password='x')
        self.client = Client()
        self.client.force_login(user)

    def _groups(self, **query):
        r = self.client.get(URL, {'task': 'text-to-image', 'group': 'category', **query})
        self.assertEqual(r.status_code, 200)
        return [(g.get('group'), [o[0] if isinstance(o, list) else o['value'] for o in g['options']])
                for g in r.json()['groups']]

    def test_uncategorised_models_head_the_list_and_a_category_is_an_optgroup(self):
        groups = self._groups()
        # Les modèles sans catégorie ouvrent la liste, sous leur ORIGINE (2026-10-05).
        self.assertEqual(('WAMA local', ['imager:plain-a']), groups[0])
        self.assertEqual(('Logos — WAMA local', ['imager:logo-b']), groups[1])

    def test_auto_heads_the_list_on_its_own_never_inside_a_named_group(self):
        # « auto » peut tirer un modèle local comme distant : il n'appartient à aucune origine.
        groups = self._groups(auto='1')
        self.assertEqual((None, ['auto']), groups[0])
        self.assertEqual(['WAMA local', 'Logos — WAMA local'], [name for name, _ in groups[1:]])

    def test_an_empty_domain_still_answers_one_group(self):
        AIModel.objects.filter(model_key__in=['imager:plain-a', 'imager:logo-b']).delete()
        r = self.client.get(URL, {'task': 'text-to-image', 'group': 'category'})
        self.assertEqual([{'options': []}], r.json()['groups'])


class FullKeyChipTest(TestCase):
    """A card chip names a FULL catalogue key by its label — the value an app stores once it
    has moved to catalogue keys (imager, 2026-09-29: the card showed `imager:…` raw)."""

    def test_a_full_key_resolves_to_its_catalogue_label(self):
        from wama.common.utils import card_chips
        _model('huggingface:Org/Img', 'Image installée', task='text-to-image',
               model_type='diffusion')
        card_chips._CATALOGUE_MEMO.clear()

        class _Item:
            model = 'huggingface:Org/Img'

        field = {'name': 'model', 'type': 'select', 'chip': True, 'options_source': 'catalog',
                 'options_query': {'task': 'text-to-image'}}
        self.assertEqual(['Image installée'],
                         [c['label'] for c in card_chips.chips_for(_Item(), [field])])


class GroupAutoOptionsTest(TestCase):
    """One « auto » PER GROUP (`auto=group`, 2026-10-01, composer): a task-bound auto
    (`auto:<task>`) heads each task group — the decision « no 2 modes: group server-side + one
    auto per group ». The domain is bounded by the TASK, never by the source: a model of the
    task installed from elsewhere (YuE2, prospected) joins the menu without a line of code."""

    def setUp(self):
        _model('composer:musicgen-small', 'MusicGen small', task='text-to-music', model_type='music')
        _model('huggingface:m-a-p/YuE2-3B', 'YuE2 3B', task='text-to-music', model_type='music')
        _model('composer:audiogen-medium', 'AudioGen', task='text-to-audio', model_type='music')
        user = get_user_model().objects.create_user(username='group_auto', password='x')
        self.client = Client()
        self.client.force_login(user)

    def _groups(self, auto):
        r = self.client.get(URL, {'task': 'text-to-music,text-to-audio', 'group': 'task',
                                  'auto': auto})
        self.assertEqual(r.status_code, 200)
        return r.json()['groups']

    def _by_task(self, auto):
        return {g.get('task'): [o[0] if isinstance(o, list) else o['value'] for o in g['options']]
                for g in self._groups(auto)}

    def test_each_task_group_is_headed_by_its_own_auto(self):
        groups = self._by_task('group')
        self.assertEqual('auto:text-to-music', groups['text-to-music'][0])
        self.assertEqual('auto:text-to-audio', groups['text-to-audio'][0])
        self.assertNotIn(None, groups, 'no anonymous head group holding a bare « auto »')

    def test_a_model_of_the_task_from_another_source_joins_the_menu(self):
        groups = self._by_task('group')
        self.assertIn('huggingface:m-a-p/YuE2-3B', groups['text-to-music'])
        self.assertIn('composer:audiogen-medium', groups['text-to-audio'])
        self.assertNotIn('composer:audiogen-medium', groups['text-to-music'])

    def test_the_single_auto_is_unchanged(self):
        values = [v for vs in self._by_task('1').values() for v in vs]
        self.assertIn('auto', values)
        self.assertFalse([v for v in values if v.startswith('auto:')])


class TaskBoundAutoTest(TestCase):
    """`auto:<task>` (model_keys): an « auto » bounded to a task — never a catalogue key."""

    def test_the_task_is_read_from_the_value(self):
        from wama.common.utils.model_keys import auto_task
        self.assertEqual('text-to-music', auto_task('auto:text-to-music'))
        self.assertEqual('', auto_task('auto'))
        self.assertEqual('', auto_task('composer:musicgen-small'))
        self.assertEqual('', auto_task(None))

    def test_it_is_an_auto_and_is_never_prefixed(self):
        from wama.common.utils.auto_model import is_auto
        from wama.common.utils.model_keys import catalog_key
        self.assertTrue(is_auto('auto:text-to-audio'))
        self.assertEqual('auto:text-to-audio', catalog_key('auto:text-to-audio', 'composer'))

    def test_the_resolution_is_bounded_to_the_task_of_the_auto(self):
        from unittest import mock
        from wama.common.utils.auto_model import resolve_model_choice
        seen = {}

        def fake_select(source, **kw):
            seen.update(kw, source=source)
            return 'huggingface:m-a-p/YuE2-3B'

        with mock.patch('wama.model_manager.services.select_model_id', fake_select):
            self.assertEqual('huggingface:m-a-p/YuE2-3B', resolve_model_choice(
                'auto:text-to-music', spec={'task': 'text-to-music,text-to-audio'}))
        self.assertEqual('text-to-music', seen['task'])
        self.assertIsNone(seen['source'])


class OriginGroupsTest(TestCase):
    """Chaque sélecteur de modèle DIT où l'inférence a lieu (Fabien, 2026-10-05 : « on ne sait pas
    si on choisit un modèle local ou distant »). La règle vit dans la route commune des options,
    donc elle vaut pour l'assistant et pour toutes les apps sans une ligne de plus."""

    def _groups(self, groups, executions):
        from wama.model_manager.views import _groups_by_origin
        info = [{'id': key, 'execution': execution} for key, execution in executions.items()]
        return [(g['group'], g.get('key'), [o[0] if isinstance(o, list) else o['value']
                                           for o in g['options']], g.get('task'))
                for g in _groups_by_origin(groups, info)]

    def test_a_flat_list_is_split_by_origin_local_first_then_the_hosting_scale(self):
        executions = {'anthropic:claude-x': 'cloud', 'ollama:qwen': 'local',
                      'claude_code:opus': 'cloud', 'albert:mistral': 'cloud'}
        groups = self._groups([{'options': [[k, k] for k in executions]}], executions)
        self.assertEqual(
            [('WAMA local', 'local', ['ollama:qwen'], None),
             ('Albert API (DINUM)', 'albert', ['albert:mistral'], None),
             ('API Anthropic (Claude)', 'anthropic', ['anthropic:claude-x'], None),
             ('Claude Code (abonnement)', 'claude_code', ['claude_code:opus'], None)], groups)

    def test_a_named_group_keeps_its_name_and_says_the_origin(self):
        executions = {'composer:a': 'local', 'albert:b': 'cloud'}
        groups = self._groups([{'group': 'Chansons', 'task': 'text-to-song',
                                'options': [['composer:a', 'A'], ['albert:b', 'B']]}], executions)
        self.assertEqual(['Chansons — WAMA local', 'Chansons — Albert API (DINUM)'],
                         [name for name, *_ in groups])
        # Un seul groupe par tâche porte `task` : c'est lui que l'« auto » de groupe nomme.
        self.assertEqual(['text-to-song', None], [task for *_, task in groups])

    def test_a_disabled_option_stays_listed_under_its_origin(self):
        option = {'value': 'imager:x', 'label': 'X — backend absent', 'disabled': True, 'title': 'r'}
        groups = self._groups([{'options': [option]}], {'imager:x': 'local'})
        self.assertEqual([('WAMA local', 'local', ['imager:x'], None)], groups)

    def test_an_empty_domain_keeps_its_single_empty_group(self):
        from wama.model_manager.views import _groups_by_origin
        self.assertEqual([{'options': []}], _groups_by_origin([{'options': []}], []))

    def test_a_remote_model_of_an_unknown_source_is_never_called_local(self):
        from wama.common.external_sources import model_origin
        key, label, rank = model_origin('mystery:model', 'cloud')
        self.assertNotEqual('WAMA local', label)
        self.assertGreater(rank, model_origin('claude_code:opus', 'cloud')[2])
        self.assertEqual(('local', 'WAMA local', 0), model_origin('imager:x', 'local'))
        self.assertEqual(('local', 'WAMA local', 0), model_origin('imager:x', ''))
