"""Tests de la brique COMMUNE d'auto-sélection de modèle (`common/utils/auto_model.py`).

Trois surfaces : la résolution (« auto » → tirage par le domaine du schéma, valeur
explicite respectée, repli sans jamais lever), la prévision (le modèle qui serait retenu
maintenant), et l'endpoint d'options (« auto » servi en 1ʳᵉ position, opt-in `auto=1`).
"""

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from wama.common.utils.auto_model import (
    AUTO_LABEL, catalog_domain, is_auto, predict_model_choice, resolve_model_choice,
)
from wama.model_manager.models import AIModel


def _tts(model_key, name, vram_gb, engine=None):
    return AIModel.objects.create(
        model_key=model_key, name=name, model_type='speech', source='synthesizer',
        vram_gb=vram_gb, is_available=True, is_downloaded=True,
        capabilities={'task': 'text-to-speech', 'modalities': ['audio']},
        composition={'runtime': {'engine': engine}} if engine else {},
    )


class ResolutionAutoTest(TestCase):

    def setUp(self):
        self.leger = _tts('synthesizer:tts-leger', 'TTS léger', 0.5)
        self.lourd = _tts('synthesizer:tts-lourd', 'TTS lourd', 4.0)

    def test_une_valeur_explicite_revient_telle_quelle(self):
        self.assertEqual(
            resolve_model_choice('synthesizer:tts-lourd', app_id='synthesizer'),
            'synthesizer:tts-lourd')

    def test_auto_tire_dans_le_domaine_declare_au_schema_et_rend_la_cle_entiere(self):
        """Le domaine du tirage EST celui des options (`options_query` du schéma) ; sans
        `source`, l'espace de clés du retour est la clé catalogue ENTIÈRE (règle
        `select_model_id`, mesurée le 2026-09-01)."""
        choix = resolve_model_choice('auto', app_id='synthesizer', fallback='repli')
        self.assertIn(choix, {'synthesizer:tts-leger', 'synthesizer:tts-lourd'})

    def test_une_valeur_vide_vaut_auto(self):
        self.assertTrue(is_auto(''))
        self.assertTrue(is_auto(None))
        choix = resolve_model_choice('', app_id='synthesizer', fallback='repli')
        self.assertIn(choix, {'synthesizer:tts-leger', 'synthesizer:tts-lourd'})

    def test_catalogue_vide_rend_le_repli_sans_lever(self):
        AIModel.objects.all().delete()
        self.assertEqual(
            resolve_model_choice('auto', app_id='synthesizer', fallback='le-repli'),
            'le-repli')

    def test_un_domaine_introuvable_rend_le_repli_sans_lever(self):
        """Une app sans select `catalog` au schéma (ou un spec vide) ne doit pas faire
        échouer un lancement : la brique encaisse et rend le repli."""
        self.assertEqual(
            resolve_model_choice('auto', spec={}, fallback='le-repli'), 'le-repli')

    def test_le_domaine_des_deux_adopteurs_est_lisible_au_schema(self):
        self.assertEqual(catalog_domain('synthesizer'), {'task': 'text-to-speech'})
        self.assertEqual(catalog_domain('avatarizer'), {'task': 'text-to-speech'})


class UneVoixCloneeExigeUnMoteurQuiCloneTest(TestCase):
    """Décision Fabien (13/09) : « auto » reste COMPATIBLE avec une voix clonée dans l'UI ;
    c'est le TIRAGE qui porte la contrainte (`requires=['supports_cloning']`)."""

    def setUp(self):
        self.muet = _tts('synthesizer:tts-muet', 'TTS sans clonage', 0.5)
        self.muet.capabilities['supports_cloning'] = False
        self.muet.save(update_fields=['capabilities'])
        self.cloneur = _tts('synthesizer:tts-cloneur', 'TTS qui clone', 4.0)
        self.cloneur.capabilities['supports_cloning'] = True
        self.cloneur.save(update_fields=['capabilities'])

    def test_sans_exigence_le_tirage_prend_le_leger(self):
        self.assertEqual(resolve_model_choice('auto', app_id='synthesizer', quality_intent=0,
                                              fallback='r'), 'synthesizer:tts-muet')

    def test_avec_une_voix_clonee_le_tirage_ne_retient_qu_un_moteur_qui_clone(self):
        self.assertEqual(resolve_model_choice('auto', app_id='synthesizer', quality_intent=0,
                                              requires=['supports_cloning'], fallback='r'),
                         'synthesizer:tts-cloneur')

    def test_les_deux_workers_portent_l_exigence_au_tirage(self):
        from pathlib import Path
        from unittest import mock
        from django.conf import settings
        # Synthesizer : le tirage vit dans `utils/speech_render.resolve_tts_model` depuis le
        # 2026-09-28 (le worker ET l'aperçu de voix l'appellent) — on mesure le COMPORTEMENT, plus
        # une phrase du worker.
        from wama.synthesizer import workers
        from wama.synthesizer.utils import speech_render
        self.assertIs(workers.resolve_tts_model, speech_render.resolve_tts_model)
        with mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                        return_value='synthesizer:tts-cloneur') as draw:
            speech_render.resolve_tts_model('auto', 'ua_1', 50, fallback='r')
        self.assertEqual(['supports_cloning'], draw.call_args.kwargs['requires'])
        # Avatarizer : le tirage est encore écrit dans son worker.
        src = (Path(settings.BASE_DIR) / 'wama/avatarizer/workers.py').read_text(encoding='utf-8')
        self.assertIn("['supports_cloning'] if is_cloned_voice(", src)
        self.assertIn('requires=exigences', src)

    def test_auto_n_est_jamais_grise_par_la_brique_d_appariement(self):
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-input-match.js').read_text(encoding='utf-8')
        # Forme généralisée le 2026-10-05 (l'« auto » d'un groupe aussi) ; le COMPORTEMENT est
        # exercé en V8 par `tests_input_match_capability` (jumeau de `auto_model.is_auto`).
        self.assertIn("if (isAutoValue(mid)) return true;", js)


class PrevisionTest(TestCase):

    def setUp(self):
        self.seul = _tts('synthesizer:tts-seul', 'TTS seul', 0.5)

    def test_la_prevision_nomme_le_modele_et_sa_vram(self):
        p = predict_model_choice({'task': 'text-to-speech'})
        self.assertIsNotNone(p)
        self.assertEqual(p['id'], 'synthesizer:tts-seul')
        self.assertEqual(p['name'], 'TTS seul')
        self.assertEqual(p['vram_gb'], 0.5)

    def test_sans_candidat_la_prevision_rend_None(self):
        AIModel.objects.all().delete()
        self.assertIsNone(predict_model_choice({'task': 'text-to-speech'}))


class PreviewOriginTest(TestCase):
    """2026-10-13 (Fabien): « Prévu : qwen-3.8-27b » did not say it was ILaaS. The preview carries
    WHERE the model runs — the sentence of the menu's group titles (`AIModel.origin_label`) — and
    the note under the select shows it."""

    def test_a_local_preview_says_local(self):
        _tts('synthesizer:tts-seul', 'TTS seul', 0.5)
        self.assertEqual('WAMA local', predict_model_choice({'task': 'text-to-speech'})['origin'])

    def test_a_remote_preview_names_its_provider(self):
        from unittest import mock
        from wama.model_manager.models import EXECUTION_CLOUD
        remote = AIModel.objects.create(
            model_key='ilaas:qwen-3.8-27b', name='qwen-3.8-27b', model_type='llm', source='ilaas',
            execution=EXECUTION_CLOUD, cost_tier='free', is_available=True)
        with mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                        return_value=remote.model_key):
            origin = predict_model_choice({'model_type': 'llm'})['origin']
        self.assertEqual(remote.origin_label, origin)
        self.assertIn('ILaaS', origin)
        self.assertIn('souverain', origin)

    def test_the_note_under_the_select_shows_the_origin(self):
        """On the SERVED file, in V8: the origin is said; a remote model shows no local VRAM."""
        from pathlib import Path
        from django.conf import settings
        from py_mini_racer import MiniRacer
        v8 = MiniRacer()
        v8.eval("var window = {}; var document = {readyState: 'complete', "
                "addEventListener: function () {}, querySelectorAll: function () { return []; }};")
        v8.eval((Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-params.js')
                .read_text(encoding='utf-8'))
        remote = v8.eval("window.WamaParams.autoPreviewText({name: 'qwen-3.8-27b', vram_gb: 0, "
                         "origin: 'Cloud souverain · ILaaS (ESR) · gratuit (quota)'})")
        self.assertEqual('Prévu : qwen-3.8-27b · Cloud souverain · ILaaS (ESR) · gratuit (quota)'
                         ' — réévalué au lancement', remote)
        local = v8.eval("window.WamaParams.autoPreviewText({name: 'qwen3.5:4b', vram_gb: 3.4, "
                        "origin: 'WAMA local · Ollama'})")
        self.assertEqual('Prévu : qwen3.5:4b (3.4 Go) · WAMA local · Ollama — réévalué au lancement',
                         local)
        # Counter-test: a preview without an origin (older answer) keeps the former text.
        self.assertEqual('Prévu : x (1 Go) — réévalué au lancement',
                         v8.eval("window.WamaParams.autoPreviewText({name: 'x', vram_gb: 1})"))


class EndpointOptionsAutoTest(TestCase):

    URL = '/model-manager/api/models/options/'

    def setUp(self):
        _tts('synthesizer:tts-seul', 'TTS seul', 0.5)
        user = get_user_model().objects.create_user(
            username='auto_model_test', password='x')
        self.client = Client()
        self.client.force_login(user)

    def test_auto_est_servi_en_premiere_option_avec_la_prevision(self):
        r = self.client.get(self.URL, {'task': 'text-to-speech', 'auto': '1'})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        premiere = d['groups'][0]['options'][0]
        self.assertEqual(premiere, ['auto', AUTO_LABEL])
        self.assertEqual(d.get('auto_preview', {}).get('name'), 'TTS seul')

    def test_sans_le_drapeau_la_reponse_est_inchangee(self):
        r = self.client.get(self.URL, {'task': 'text-to-speech'})
        d = r.json()
        valeurs = [o[0] for g in d['groups'] for o in g['options']]
        self.assertNotIn('auto', valeurs)
        self.assertNotIn('auto_preview', d)


class DeclaredCloudModelsInTheAutoDrawTest(TestCase):
    """2026-09-30 (Fabien's decision): « auto » may draw a REMOTE model for any app whose schema
    declares `options_cloud` — within what the PROFILE opens to the automatic draw
    (`allowed_cloud_keys(automatic=True)`). Until then only the assistant passed `cloud_keys`."""

    CLOUD_FIELD = {'name': 'model', 'options_source': 'catalog',
                   'options_query': {'task': 'text-to-speech'}, 'options_cloud': True}

    def setUp(self):
        self.user = get_user_model().objects.create_user('auto_cloud', password='x')

    def _draw(self, field, **kwargs):
        from unittest import mock
        with mock.patch('wama.common.utils.auto_model.catalog_field', return_value=field), \
                mock.patch('wama.model_manager.services.cloud_models.allowed_cloud_keys',
                           return_value={'albert:tts'}) as allowed, \
                mock.patch('wama.model_manager.services.select_model_id',
                           return_value='x') as select:
            resolve_model_choice('auto', app_id='any', user=self.user, **kwargs)
        return select.call_args.kwargs.get('cloud_keys'), allowed

    def test_a_declared_select_hands_the_profiles_automatic_keys_to_the_draw(self):
        keys, allowed = self._draw(self.CLOUD_FIELD)
        self.assertEqual({'albert:tts'}, keys)
        self.assertTrue(allowed.call_args.kwargs.get('automatic'),
                        "the automatic draw, never the manual choice's keys")

    def test_without_the_declaration_the_draw_stays_local(self):
        keys, allowed = self._draw(dict(self.CLOUD_FIELD, options_cloud=False))
        self.assertIsNone(keys)
        allowed.assert_not_called()

    def test_a_caller_passing_its_own_keys_keeps_control(self):
        keys, allowed = self._draw(self.CLOUD_FIELD, cloud_keys={'anthropic:x'})
        self.assertEqual({'anthropic:x'}, keys)
        allowed.assert_not_called()

    def test_the_preview_tells_the_automatic_draw_not_the_manual_list(self):
        """A « cloud when saturated » profile LISTS remote models but never DRAWS one: the
        preview used to receive the list's keys and announce a model auto would not pick."""
        from unittest import mock
        _tts('synthesizer:tts-seul', 'TTS seul', 0.5)
        client = Client()
        client.force_login(self.user)

        def allowed(user, automatic=True):
            return set() if automatic else {'albert:tts'}
        with mock.patch('wama.model_manager.services.cloud_models.allowed_cloud_keys',
                        side_effect=allowed), \
                mock.patch('wama.common.utils.auto_model.predict_model_choice',
                           return_value=None) as preview:
            client.get('/model-manager/api/models/options/',
                       {'task': 'text-to-speech', 'auto': '1', 'cloud': '1'})
        self.assertNotIn('cloud_keys', preview.call_args.args[0])


class CurseurDeQualiteTest(TestCase):
    """Le curseur 0-100 traverse toute la chaîne : brique, endpoint, schémas, UI."""

    URL = '/model-manager/api/models/options/'

    def setUp(self):
        self.leger = _tts('synthesizer:tts-leger', 'TTS léger', 0.5)
        self.lourd = _tts('synthesizer:tts-lourd', 'TTS lourd', 4.0)

    def test_le_curseur_traverse_la_brique_jusqu_au_selecteur(self):
        """0 rend le léger, 100 le meilleur — quel que soit l'état VRAM réel de la
        machine (à 100 le budget cesse de borner, à 0 le léger tient toujours)."""
        self.assertEqual(
            resolve_model_choice('auto', app_id='synthesizer', quality_intent=0,
                                 fallback='repli'),
            'synthesizer:tts-leger')
        self.assertEqual(
            resolve_model_choice('auto', app_id='synthesizer', quality_intent=100,
                                 fallback='repli'),
            'synthesizer:tts-lourd')

    def test_l_endpoint_previsionne_selon_le_curseur(self):
        user = get_user_model().objects.create_user(username='intent_test', password='x')
        client = Client()
        client.force_login(user)
        rapide = client.get(self.URL, {'task': 'text-to-speech', 'auto': '1',
                                       'quality_intent': '0'}).json()
        qualite = client.get(self.URL, {'task': 'text-to-speech', 'auto': '1',
                                        'quality_intent': '100'}).json()
        self.assertEqual(rapide.get('auto_preview', {}).get('name'), 'TTS léger')
        self.assertEqual(qualite.get('auto_preview', {}).get('name'), 'TTS lourd')

    def test_toute_app_qui_porte_le_curseur_le_declare_conditionne_a_auto(self):
        """Parcours du CATALOGUE, jamais une liste d'adopteurs (Fabien, 2026-09-19 : « toutes
        les apps auront le curseur ») : chaque app dont le schéma porte `quality_intent` le
        déclare en type `intent`, défaut 50, visible seulement quand SON sélecteur de modèle
        est sur « auto » — le nom du sélecteur est celui de l'app (`tts_model`…), et il doit
        exister dans le même schéma. Ce test nommait ses deux adopteurs ; une app ralliée
        demain est gardée sans qu'on l'ajoute ici."""
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.param_schema import schema_for_app
        adopteurs = []
        for app in sorted(APP_CATALOG):
            schema = schema_for_app(app) or []
            champ = next((f for f in schema if f.get('name') == 'quality_intent'), None)
            if champ is None:
                continue
            adopteurs.append(app)
            self.assertEqual(champ.get('type'), 'intent', app)
            self.assertEqual(champ.get('default'), 50, app)
            condition = champ.get('show_if') or {}
            # Une app qui TIRE un modèle conditionne le curseur à « auto » — nu (imager,
            # synthesizer…) ou les pseudo-modèles « auto-* » du composer (un « auto » par
            # optgroup, 2026-07-02) : une valeur `equals`, ou une liste `in`. Une app SANS
            # modèle (converter : le curseur décline en encodage, conditionné par la NATURE) n'a
            # pas d'« auto » à surveiller — seule la condition doit viser un champ du schéma.
            values = [condition.get('equals')] if 'equals' in condition else list(condition.get('in') or [])
            serves_auto = any(f.get('options_auto') for f in schema) or any(
                str(v[0] if isinstance(v, (list, tuple)) else v).startswith('auto')
                for f in schema for v in (f.get('choices') or [])) or any(
                str(v[0] if isinstance(v, (list, tuple)) else v).startswith('auto')
                for f in schema for _label, group in (f.get('option_groups') or []) for v in group)
            if serves_auto:
                self.assertTrue(values and all(str(v).startswith('auto') for v in values),
                                f"{app} : le curseur doit n'apparaître que sur « auto » ({condition})")
            self.assertIn(condition.get('field'), {f.get('name') for f in schema},
                          f"{app} : la condition d'affichage vise un champ absent du schéma")
        self.assertGreaterEqual(len(adopteurs), 2, 'parcours vacueux : au moins deux adopteurs')

    def test_l_anonymizer_est_rallie_au_curseur_commun_avec_son_pas_reel(self):
        """Même FORME utilisateur (type='intent') : le champ reste `precision_level` (frontière
        des données — tasks/model_selector le lisent) et le pas reste 5 (5 paliers moteur réels,
        leçon du 2026-08-19). La déclinaison, elle, est au commun depuis le 20/09
        (`tests_intent_vision` la garde cran par cran)."""
        from wama.common.utils.param_schema import schema_for_app
        champ = next((f for f in schema_for_app('anonymizer')
                      if f.get('name') == 'precision_level'), None)
        self.assertIsNotNone(champ, "anonymizer : precision_level absent du schéma")
        self.assertEqual(champ.get('type'), 'intent')
        self.assertEqual(champ.get('step'), 5)

    def test_la_lecture_d_un_post_est_bornee_et_ne_leve_jamais(self):
        from wama.common.utils.auto_model import read_quality_intent
        self.assertEqual(read_quality_intent('85'), 85)
        self.assertEqual(read_quality_intent(140), 100)
        self.assertEqual(read_quality_intent(-3), 0)
        self.assertEqual(read_quality_intent('n_importe_quoi'), 50)
        self.assertEqual(read_quality_intent(None), 50)

    def test_le_grisage_est_un_verdict_verifie_pas_une_liste(self):
        """Décision Fabien 02/09 (solde le pending « grisage » du 31/08) : pas de grisage à
        la main — un SYSTÈME qui vérifie. Un moteur déclaré qu'aucun inventaire ne sert est
        POSITIVEMENT inlançable ; tout le reste est permissif (pas de moteur = pas de
        verdict, backend_ref d'app = l'app assume)."""
        from types import SimpleNamespace
        from wama.common.backends.manager import backend_missing, engine_backends, known_engines
        from wama.synthesizer.backends import ENGINE_BACKENDS
        # ⚠ L'inventaire n'annonce que les moteurs EXÉCUTABLES (raffinement 03/09 :
        # backend enregistré ET runtime importable) — il est donc DÉPENDANT DU VENV par
        # conception, et un roster figé ici casserait dans le venv qui n'a pas tel
        # runtime (vécu : kokoro_onnx absent de venv_win). On teste le MÉCANISME :
        connus = known_engines()
        # (a) rien d'inventé : tout moteur annoncé est DÉCLARÉ quelque part.
        # ⚠ La SOURCE s'est élargie le 2026-09-04 : jusque-là seuls 2 inventaires étaient
        # enregistrés à la main (synthesizer, composer), alors que 18 moteurs sont déclarés
        # par les backends via `BaseModelBackend.ENGINE`. Conséquence MESURÉE de cette
        # étroitesse : un modèle exigeant `pyannote` était jugé « moteur sans backend
        # installé » — verdict FAUX, masqué seulement par `backend_ref`. L'inventaire est
        # désormais DÉRIVÉ des déclarations ; l'assertion suit la source, pas l'inverse.
        from wama.common.services.backend_inventory import inventory
        declares = {e.engine for a in inventory() if not a.generated_from
                    for e in a.entries if e.engine}
        # ⚠ 2026-09-06 — la source s'élargit une 2ᵉ fois, et pour une raison de NATURE, pas de
        # rattrapage : certains moteurs n'ont PAS de classe de backend et n'en auront jamais,
        # parce qu'ils ne sont pas du code Python qu'on charge. `audio-cpp` est un binaire C++ ;
        # `ollama` est un DÉMON. Leur déclaration passe donc par un inventaire enregistré à la
        # main (`register_engine_inventory`), seule voie possible pour eux. Les lister ici n'est
        # pas une dérogation : c'est dire que la 2ᵉ voie de déclaration existe et laquelle.
        # 2026-09-15 : les fournisseurs LLM DISTANTS (Albert…) sont de même nature — un service
        # qu'on appelle, déclaré par sa source `external_sources` (lue ici, jamais recopiée).
        from wama.common.external_sources import llm_engine_inventory
        HORS_PROCESSUS = {'audio-cpp', 'ollama'} | set(llm_engine_inventory())
        self.assertTrue(connus <= declares | set(ENGINE_BACKENDS) | HORS_PROCESSUS,
                        f"moteurs annoncés sans déclaration : "
                        f"{sorted(connus - declares - set(ENGINE_BACKENDS) - HORS_PROCESSUS)}")
        # (b) la POLITIQUE « exécutable », testée sur le mécanisme et non sur un roster.
        # ⚠ Cette assertion figeait `assertNotIn('qwen3-tts', connus)` au motif que « son
        # runtime pip n'est installé nulle part tant que Fabien n'a pas donné le GO ». Elle
        # contredisait la docstring écrite JUSTE AU-DESSUS (« un roster figé ici casserait
        # dans le venv qui n'a pas tel runtime — on teste le MÉCANISME ») : un état
        # d'INSTALLATION est par nature volatil. `qwen-tts 0.1.1` a été installé dans
        # venv_linux le 2026-09-03 à 14:25, et le test est devenu rouge sans qu'une ligne de
        # code applicative ne bouge — il mesurait le contenu d'un venv, pas une règle.
        # La règle, elle, est vraie dans TOUS les venvs et ne périme pas : un moteur annoncé
        # est un moteur dont il ne manque AUCUN paquet.
        self.assertIn('qwen3-tts', ENGINE_BACKENDS,
                      'le backend qwen3-tts reste ENREGISTRÉ (déclaration, pas installation)')
        for moteur, cls in engine_backends().items():
            manquants = getattr(cls, 'missing_packages', lambda: [])()
            if manquants:
                self.assertNotIn(
                    moteur, connus,
                    f"{moteur} a des paquets manquants ({manquants}) : l'inventaire ne doit "
                    f"pas l'annoncer — c'est toute la politique « exécutable »")
        fantome = SimpleNamespace(backend_ref='', composition={'runtime': {'engine': 'moteur-fantome'}})
        self.assertIn('moteur-fantome', backend_missing(fantome))
        self.assertIsNone(backend_missing(
            SimpleNamespace(backend_ref='', composition={'runtime': {'engine': 'kokoro'}})))
        # ⚠ ASSERTION INVERSÉE le 2026-09-29 (décision Fabien) : sans moteur ET sans app, il n'y
        # a aucune route d'exécution — la permissivité ne tenait qu'à un compte périmé (159/174
        # le 05/09, 2/144 le 29/09). Cf. `BackendRefNAbsoutPlusTest` pour la contrepartie.
        self.assertIn('aucune route', backend_missing(
            SimpleNamespace(backend_ref='', composition={}, source='huggingface')) or '')
        self.assertIsNone(backend_missing(SimpleNamespace(backend_ref='', composition={})),
                          "sans source de balayage générique, pas de verdict sans moteur")
        # ⚠ ASSERTION INVERSÉE le 2026-09-05, DÉLIBÉRÉMENT. Elle attendait `None` : un
        # `backend_ref` renseigné suffisait à absoudre un moteur introuvable. C'était le
        # court-circuit de `backend_missing`, et il contredisait le nom même de ce test —
        # `backend_ref` porte un nom d'APP, donc il atteste une APPARTENANCE, jamais une
        # EXÉCUTABILITÉ. Mesuré avant de retirer : sur 174 modèles du catalogue réel, UN SEUL
        # change de verdict (`ResembleAI/chatterbox`), et il devient juste — aucun backend
        # chatterbox n'existe dans `wama/synthesizer/backends/`.
        self.assertIn('moteur-fantome', backend_missing(
            SimpleNamespace(backend_ref='une.classe.Backend',
                            composition={'runtime': {'engine': 'moteur-fantome'}})),
            "un backend_ref ne doit plus absoudre un moteur que personne ne pilote")

    def test_le_tirage_auto_exclut_l_inlancable_et_le_backend_qui_apparait_reautorise(self):
        """Le vécu du jour : chatterbox (sans backend) prévu à curseur 50 — refus garanti
        au lancement. Le tirage EXCLUT le positivement inlançable, même meilleur au score ;
        et l'inventaire étant relu à chaque appel, un backend qui apparaît ré-autorise
        SANS AUCUN GESTE — c'est le contrat demandé par Fabien."""
        from wama.common.backends import manager as backends_manager
        from wama.model_manager.services import select_model
        _tts('synthesizer:tts-fantome', 'TTS fantôme', 8.0, engine='moteur-fantome')

        def _tirer():
            chosen = select_model(source='synthesizer', prefer_loaded=False,
                                  vram_budget_gb=10, quality_intent=100)
            return chosen.model_key if chosen else None

        self.assertEqual(_tirer(), 'synthesizer:tts-lourd',
                         "le fantôme (8 Go, meilleur au proxy) devait être exclu du tirage")
        inventaire = lambda: {'moteur-fantome'}  # noqa: E731 — le « backend » apparaît
        backends_manager.register_engine_inventory(inventaire)
        try:
            self.assertEqual(_tirer(), 'synthesizer:tts-fantome',
                             "le backend apparu devait ré-autoriser le moteur tout seul")
        finally:
            backends_manager._ENGINE_INVENTORIES.remove(inventaire)

    def test_l_endpoint_grise_avec_la_raison_sans_retirer_de_la_liste(self):
        """Lister n'est pas pouvoir choisir (INPUT_MODEL_MATCHING §2) : l'option reste
        AFFICHÉE — grisée, raison en title — jamais retirée."""
        _tts('synthesizer:tts-fantome', 'TTS fantôme', 8.0, engine='moteur-fantome')
        user = get_user_model().objects.create_user(username='grisage_test', password='x')
        client = Client()
        client.force_login(user)
        d = client.get(self.URL, {'task': 'text-to-speech', 'auto': '1'}).json()
        options = [o for g in d['groups'] for o in g['options']]
        fantome = next((o for o in options if not isinstance(o, list)
                        and o.get('value') == 'synthesizer:tts-fantome'), None)
        self.assertIsNotNone(fantome, "l'option inlançable doit RESTER dans la liste")
        self.assertTrue(fantome.get('disabled'))
        self.assertIn('moteur-fantome', fantome.get('title', ''))
        self.assertIn('backend absent', fantome.get('label', ''))
        valeurs = [o[0] if isinstance(o, list) else o.get('value') for o in options]
        self.assertIn('synthesizer:tts-leger', valeurs)

    def test_un_modele_DECLARE_la_librairie_que_son_moteur_exige(self):
        """Trou 1 de l'audit d'intégration (03/09) : `app→modèle` et `app→librairie`
        étaient déclarés, `modèle→librairie` vivait UNIQUEMENT dans le PIP_PACKAGES du
        backend — donc dans du code Python, invisible de la couche manifeste.

        Règle CUMULATIVE, la même que la jambe `library` d'une app : le backend qui sert
        le moteur exige la distribution ET elle est SEMÉE au corpus. La 2ᵉ condition n'est
        pas cosmétique — `valider()` traite une référence pendante comme une ERREUR."""
        from wama.common.manifests.builtin.model import _requires_librairies

        # (a) moteur servi + lib semée → la référence est émise…
        corps = {'composition': {'runtime': {'engine': 'kokoro-onnx'}}}
        self.assertEqual(_requires_librairies(corps),
                         [{'kind': 'library', 'key': 'kokoro-onnx'}])
        # (b) …et elle RÉSOUT (aucune pendante — sinon le manifeste serait invalide).
        from wama.common.manifests.builtin.model import extract_model
        from wama.common.manifests.ingest import resolve_requires, validate
        man = extract_model('huggingface:onnx-community/Kokoro-82M-v1.0-ONNX')
        if man:                      # le modèle peut ne pas être catalogué sur ce poste
            self.assertEqual(list(validate(man) or []), [])
            _, pendantes = resolve_requires(man)
            self.assertEqual(pendantes, [], "une référence pendante invalide le manifeste")
        # (c) moteur SANS backend : on ne sait pas ce qu'il exige → on n'invente rien.
        self.assertEqual(
            _requires_librairies({'composition': {'runtime': {'engine': 'moteur-fantome'}}}), [])
        # (d) aucun moteur déclaré → rien (cas général du modèle mono-fichier).
        self.assertEqual(_requires_librairies({'composition': {}}), [])

    def test_an_engine_seen_only_by_the_static_inventory_still_names_its_libraries(self):
        """2026-10-16 : l'inventaire STATIQUE rend un porteur sans classe (`_DeclaredEngine`) ;
        son `pip_install_spec` manquant tombait dans le `except` et le modèle sortait sans
        `requires` — 68 manifestes de modèle ce jour-là, MuScriptor compris."""
        from wama.common.backends.manager import engine_backends
        from wama.common.manifests.builtin.model import _requires_librairies
        self.assertFalse(hasattr(engine_backends()['muscriptor'], 'pip_install_spec'),
                         'the case : a carrier, not a class')
        self.assertEqual([{'kind': 'library', 'key': 'beat-this'},
                          {'kind': 'library', 'key': 'muscriptor'},
                          {'kind': 'library', 'key': 'rotary-embedding-torch'}],
                         _requires_librairies({'composition': {'runtime': {'engine': 'muscriptor'}}}))

    def test_l_inventaire_expose_les_CLASSES_et_le_commun_filtre_l_executable(self):
        """La politique « exécutable » vit au COMMUN (03/09) : un producteur qui filtrait
        lui-même privait `engine_backends()` de la carte moteur→backend — celle dont la
        jambe `requires` ci-dessus a besoin pour remonter au PIP_PACKAGES."""
        from wama.common.backends.manager import engine_backends, known_engines
        from wama.synthesizer.backends import ENGINE_BACKENDS
        carte = engine_backends()
        # Tous les moteurs TTS ENREGISTRÉS sont dans la carte, installés ou non…
        self.assertTrue(set(ENGINE_BACKENDS) <= set(carte))
        # …et `known_engines` n'en retient que les EXÉCUTABLES.
        self.assertTrue(known_engines() <= set(carte) | {'audio-cpp'})
        for moteur, cls in carte.items():
            if cls.missing_packages():
                self.assertNotIn(moteur, known_engines(),
                                 f"{moteur} : runtime absent, il ne doit pas être annoncé")

    def test_le_grisage_serveur_survit_a_la_passe_d_appariement_client(self):
        """Mesuré au smoke du 02/09 : `wama-input-match` réécrit disabled/title à chaque
        change et EFFAÇAIT le grisage « backend absent ». Les deux sources composent via
        le marqueur `data-backend-missing` — le fill l'émet, l'appariement le respecte."""
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        params_js = (base / 'wama/common/static/common/js/wama-params.js').read_text(encoding='utf-8')
        match_js = (base / 'wama/common/static/common/js/wama-input-match.js').read_text(encoding='utf-8')
        self.assertIn('data-backend-missing', params_js)
        self.assertIn('backendMissing', match_js)

    def test_le_partial_serveur_et_le_renderer_js_partagent_le_contrat(self):
        """Le volet maison (partial Django) et les modales (renderer JS) rendent le MÊME
        markup — la liaison déléguée de wama-params.js ne connaît que ces classes, et
        l'échelle est la même (0-100, graduations Rapide/Équilibré/Qualité)."""
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        partial = (base / 'wama/common/templates/common/_intent_slider.html').read_text(encoding='utf-8')
        js = (base / 'wama/common/static/common/js/wama-params.js').read_text(encoding='utf-8')
        for marqueur in ('wama-intent', 'wama-intent-slider', 'wama-intent-val',
                         'max="100"', 'Rapide', 'Équilibré', 'Qualité'):
            self.assertIn(marqueur, partial)
            self.assertIn(marqueur, js)


def _html_tree(markup):
    """Arbre minimal {tag, classes, text, children} d'un fragment HTML."""
    from html.parser import HTMLParser
    root = {'tag': None, 'classes': [], 'text': '', 'children': []}
    stack = [root]

    class Builder(HTMLParser):
        def handle_starttag(self, tag, attrs):
            node = {'tag': tag, 'classes': (dict(attrs).get('class') or '').split(),
                    'text': '', 'children': []}
            stack[-1]['children'].append(node)
            if tag != 'input':
                stack.append(node)

        def handle_endtag(self, tag):
            if tag != 'input' and len(stack) > 1:
                stack.pop()

        def handle_data(self, data):
            stack[-1]['text'] += data

    Builder().feed(markup)
    return root


def _walk(node):
    yield node
    for child in node['children']:
        yield from _walk(child)


class IntentGraduationsUnderTheSliderTest(SimpleTestCase):
    """2026-10-13, relevé de Fabien sur l'accueil : les graduations Rapide / Équilibré / Qualité
    prenaient toute la largeur de la ligne, alors que la valeur (« 50 · Équilibré ») est à droite
    du curseur — elles ne tombaient pas sous les positions qu'elles nomment. Elles vivent dans la
    colonne du curseur, sans la valeur, et les DEUX rendus (partial serveur, renderer JS) le font."""

    def _assert_graduations_under_the_slider(self, markup):
        tracks = [n for n in _walk(_html_tree(markup)) if 'wama-intent-track' in n['classes']]
        self.assertEqual(1, len(tracks), 'une colonne du curseur')
        inside = list(_walk(tracks[0]))
        self.assertTrue(any('wama-intent-slider' in n['classes'] for n in inside), 'le curseur')
        self.assertEqual(['Rapide', 'Équilibré', 'Qualité'],
                         [n['text'] for n in inside if n['tag'] == 'span'], 'ses graduations')
        self.assertFalse(any('wama-intent-val' in n['classes'] for n in inside),
                         'la valeur est À CÔTÉ du curseur, pas au-dessus des graduations')

    def test_the_server_partial_puts_the_graduations_under_the_slider(self):
        from django.template.loader import render_to_string
        self._assert_graduations_under_the_slider(render_to_string(
            'common/_intent_slider.html', {'dom_id': 'q', 'name': 'q', 'value': 50}))

    def test_the_js_renderer_puts_the_graduations_under_the_slider(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        from pathlib import Path
        from django.conf import settings
        ctx = MiniRacer()
        ctx.eval("""
            var window = this; function CustomEvent(t) { this.type = t; } function Event(t) { this.type = t; }
            var document = { getElementById: function () { return null; },
                             querySelectorAll: function () { return []; },
                             addEventListener: function () {} };
            function box() { return { innerHTML: '', querySelectorAll: function () { return []; },
                                      querySelector: function () { return null; },
                                      addEventListener: function () {} }; }
        """)
        ctx.eval((Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-params.js')
                 .read_text(encoding='utf-8'))
        markup = ctx.eval("(function(){ var b = box(); WamaParams.render(b, [{ name: 'quality_intent',"
                          " type: 'intent', label: 'Qualité' }], { context: 'panel', values: {} });"
                          " return b.innerHTML; })()")
        self.assertIn('wama-intent-slider', markup, 'le renderer a bien rendu le curseur')
        self._assert_graduations_under_the_slider(markup)


class PredicatDeVoixClonéeDéfiniUneFoisTest(TestCase):
    """Le prédicat « cette voix est clonée » (`^ua_` ; `cv_` retiré le 2026-09-30) vit en UN
    endroit — la brique.

    Mesuré le 2026-09-12 : il était recopié sur QUATRE sites dans DEUX apps (2 `hideOption`
    dans WamaModelCaps.init, 2 `isProvided` dans WamaInputMatch.init — synthesizer et
    avatarizer). Quatre copies d'un même prédicat sont quatre occasions de le corriger à
    moitié le jour où un 3ᵉ préfixe apparaît. Les deux directions (modèle → voix, voix →
    modèle) le LISENT désormais dans `wama-model-caps.js` (`isClonedVoice`), et les pages ne
    font que DÉCLARER leurs ids (`cloneVoiceFilter`, `voiceSlot`, `langSlot`).

    ⚠ Garde TEXTUELLE — elle atteste une forme, pas un comportement. Le comportement (les
    moteurs se grisent bien dans les deux sens) est attesté par le filet navigateur, qui
    exécute les briques SERVIES : aucun test Python ne peut le faire (pas de runtime JS ici).
    """

    RACINE = None

    def _lire(self, rel):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / rel).read_text(encoding='utf-8')

    def test_le_predicat_n_existe_qu_en_un_seul_endroit(self):
        from pathlib import Path
        from django.conf import settings
        import re
        base = Path(settings.BASE_DIR) / 'wama'
        porteurs = []
        for f in list(base.rglob('*.js')) + list(base.rglob('*.html')):
            if 'staticfiles' in f.parts or 'node_modules' in f.parts:
                continue
            # Toute forme de préfixe de clonage en expression régulière : l'actuelle (`^ua_`)
            # comme l'ancienne (`^(ua_|cv_)`), qu'une copie oubliée porterait encore.
            if re.search(r'\^\(?ua_', f.read_text(encoding='utf-8', errors='replace')):
                porteurs.append(f.relative_to(base).as_posix())
        self.assertEqual(['common/static/common/js/wama-model-caps.js'], sorted(porteurs),
                         'le prédicat `^ua_` doit vivre dans la SEULE brique — '
                         f'porteurs mesurés : {sorted(porteurs)}')

    def test_les_deux_pages_ne_font_que_DECLARER(self):
        # Une « page » = son gabarit ET le JS d'app qu'il charge : depuis le 2026-09-24 la modale
        # ⚙ de l'avatarizer est GÉNÉRÉE à l'ouverture (cycle commun `WamaParams.settingsModal`),
        # et la déclaration d'appariement la suit dans `index.js` — où elle se branche sur chaque
        # modale ouverte. L'exigence ne change pas : déclarer, jamais recopier.
        pages = {'wama/synthesizer/templates/synthesizer/index.html': (),
                 'wama/avatarizer/templates/avatarizer/index.html':
                     ('wama/avatarizer/static/avatarizer/js/index.js',)}
        for page, js in pages.items():
            gabarit = self._lire(page)
            src = gabarit + ''.join(self._lire(f) for f in js)
            for attendu in ('WamaModelCaps.cloneVoiceFilter(', 'WamaInputMatch.voiceSlot(',
                            'WamaInputMatch.langSlot(', 'capsProvider:'):
                self.assertIn(attendu, src, f'{page} : {attendu} absent — la page recopie '
                                            'au lieu de déclarer, ou la langue n’a pas de '
                                            'direction inverse')
            self.assertNotIn('hideOption: function', src,
                             f'{page} : un prédicat de masquage est encore écrit dans la page')
            # ⚠ DÉCLARER ne suffit pas : la page doit CHARGER les briques. Mesuré le 13/09 :
            # l'avatarizer déclarait tout et n'incluait ni l'un ni l'autre — le bloc, gardé par
            # `if (window.WamaModelCaps)`, était mort sans signal. Cette garde ne lisait que la
            # déclaration ; elle lit désormais aussi le <script src>.
            # Deux formes de chargement : le <script src> direct, ou — depuis `9739b6e5` (socle JS
            # d'app, ROUTE §11 #25) — le socle commun AVEC le drapeau de la brique. La garde lisait
            # le seul <script src> et était rouge depuis ce portage (relevé le 2026-10-05).
            socle = 'common/_app_scripts.html' in gabarit
            for brique, drapeau in (('common/js/wama-model-caps.js', 'with_model_caps=True'),
                                    ('common/js/wama-input-match.js', 'with_input_match=True')):
                self.assertTrue(brique in gabarit or (socle and drapeau in gabarit),
                                f'{page} : la brique {brique} n’est pas chargée — '
                                'le bloc d’appariement se tait sans elle')

    def test_les_briques_exposent_les_deux_directions(self):
        caps_js = self._lire('wama/common/static/common/js/wama-model-caps.js')
        match_js = self._lire('wama/common/static/common/js/wama-input-match.js')
        self.assertIn('isClonedVoice: isClonedVoice', caps_js)
        self.assertIn('cloneVoiceFilter: cloneVoiceFilter', caps_js)
        self.assertIn('langSlot: langSlot', match_js)
        self.assertIn('voiceSlot: voiceSlot', match_js)
        # La langue entre dans l'appariement par un prédicat de VALEUR — le crochet `accepts`.
        self.assertIn('typeof s.accepts === ', match_js,
                      'un slot doit pouvoir porter son propre prédicat de compatibilité')
        # Et la brique d'appariement NE recopie PAS le prédicat : elle le LIT.
        self.assertIn('mc.isClonedVoice(v)', match_js)


def _upscaler(key, task, scale=None):
    return AIModel.objects.create(
        model_key=key, name=key.split(':')[1], model_type='upscaling', source='enhancer',
        vram_gb=0.1, is_available=True, is_downloaded=True, is_proposed=False,
        capabilities={'task': task, **({'scale': scale} if scale else {})})


class MultiTaskDomainDrawTest(TestCase):
    """2026-10-14 — a domain of SEVERAL tasks (enhancer: « upscale,denoise ») drew nothing: the
    whole string went to `model_type_for_task`, which answered None, and `select_model` refuses
    to draw without a category. Every « auto » of the enhancer returned its FALLBACK, whatever
    the slider, since the domain became tasks (2026-10-06). The listing already had the rule."""

    def setUp(self):
        _upscaler('enhancer:up2', 'upscale', 2)
        _upscaler('enhancer:up4', 'upscale', 4)
        _upscaler('enhancer:dn1', 'denoise')

    def test_several_tasks_sharing_a_category_are_drawn_from(self):
        chosen = resolve_model_choice('auto', spec={'task': 'upscale,denoise'}, fallback='FALLBACK')
        self.assertIn(chosen, {'enhancer:up2', 'enhancer:up4', 'enhancer:dn1'})

    def test_one_rule_for_the_listing_and_the_draw(self):
        from wama.model_manager.models import model_type_for_tasks
        self.assertEqual('upscaling', model_type_for_tasks('upscale,denoise'))
        self.assertEqual('upscaling', model_type_for_tasks('upscale'))
        self.assertIsNone(model_type_for_tasks('upscale,text-to-speech'),
                          'two categories: no guess')


class DeclaredNeedsTest(TestCase):
    """2026-10-14 — the element's NEED (`options_resolution.needs`, {capability: field}) bounds
    the draw BEFORE ranking, read on the element at launch and in the form for the forecast:
    one declaration, the same answer. The enhancer's factor ×2/×4 is the first one."""

    URL = '/model-manager/api/models/options/'

    def setUp(self):
        _upscaler('enhancer:up2', 'upscale', 2)
        _upscaler('enhancer:up4', 'upscale', 4)
        _upscaler('enhancer:dn1', 'denoise')
        user = get_user_model().objects.create_user(username='needs_test', password='x')
        self.client = Client()
        self.client.force_login(user)

    def test_the_need_narrows_the_draw_to_the_models_that_meet_it(self):
        for factor, expected in ((2, 'enhancer:up2'), (4, 'enhancer:up4')):
            with self.subTest(factor=factor):
                self.assertEqual(expected, resolve_model_choice(
                    'auto', spec={'task': 'upscale,denoise', 'needs': {'scale': factor}},
                    fallback='FALLBACK'))

    def test_an_unmet_need_leaves_the_whole_domain(self):
        from wama.common.utils.auto_model import need_candidates
        self.assertIsNone(need_candidates({'scale': 3}, {'task': 'upscale,denoise'}))
        self.assertIsNone(need_candidates({'scale': ''}, {'task': 'upscale,denoise'}))

    def test_the_launch_reads_the_need_on_the_element(self):
        from django.contrib.auth import get_user_model as users
        from wama.enhancer.models import Enhancement
        owner = users().objects.create_user(username='needs_owner', password='x')
        for factor, expected in ((2, 'enhancer:up2'), (4, 'enhancer:up4')):
            with self.subTest(factor=factor):
                item = Enhancement.objects.create(user=owner, media_type='image',
                                                  ai_model='auto', upscale_factor=factor)
                self.assertEqual(expected, resolve_model_choice(
                    'auto', app_id='enhancer', item=item, fallback='FALLBACK'))

    def test_a_multi_task_menu_forecasts_once_the_need_travels(self):
        def preview(**query):
            r = self.client.get(self.URL, {'task': 'upscale,denoise', 'auto': '1', **query})
            self.assertEqual(200, r.status_code)
            return r.json().get('auto_preview')
        self.assertIsNone(preview(), 'without the need, the draw is not known: silence')
        self.assertEqual('enhancer:up4', preview(needs='scale:4')['id'])
        self.assertEqual('enhancer:up2', preview(needs='scale:2')['id'])

    def test_the_need_does_not_narrow_the_list(self):
        """Listing is not choosing (`INPUT_MODEL_MATCHING §2`): the need bounds the DRAW only."""
        r = self.client.get(self.URL, {'task': 'upscale,denoise', 'auto': '1', 'needs': 'scale:4'})
        values = {o[0] if isinstance(o, list) else o['value']
                  for g in r.json()['groups'] for o in g['options']}
        self.assertEqual({'auto', 'enhancer:up2', 'enhancer:up4', 'enhancer:dn1'}, values)

    def test_the_browser_reads_the_need_in_the_form_and_refreshes_the_forecast(self):
        from pathlib import Path
        from django.conf import settings
        js = (Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-params.js').read_text(
            encoding='utf-8')
        self.assertIn("'needs=' + encodeURIComponent(pairs.join(','))", js)
        self.assertIn("n.el.addEventListener('change', refreshPreview)", js)
