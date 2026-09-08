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
        media = _champ('enhancer', 'ai_model')
        audio = _champ('enhancer', 'engine')
        self.assertEqual(self._options(media), ['BSRGANx4'])
        self.assertEqual(self._options(audio), ['deepfilternet', 'resemble'])

    def test_l_enhancer_ne_sert_PAS_auto(self):
        """Il ne résout rien : l'utilisateur désigne son moteur (critère `select_model` N/A).
        Servir « auto » enverrait une valeur que le lancement ne sait pas traduire."""
        for nom in ('ai_model', 'engine'):
            self.assertFalse(_champ('enhancer', nom).get('options_auto'))

    def test_les_valeurs_ECRITES_EN_DUR_restent_le_repli_rendu(self):
        """Les `choices` ne sont pas retirés : ils s'affichent avant que la requête réponde,
        et servent de repli si le catalogue est injoignable."""
        self.assertTrue(_champ('enhancer', 'ai_model').get('choices'))
        self.assertTrue(_champ('reader', 'backend').get('choices'))


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
