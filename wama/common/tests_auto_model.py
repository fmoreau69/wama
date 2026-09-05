"""Tests de la brique COMMUNE d'auto-sélection de modèle (`common/utils/auto_model.py`).

Trois surfaces : la résolution (« auto » → tirage par le domaine du schéma, valeur
explicite respectée, repli sans jamais lever), la prévision (le modèle qui serait retenu
maintenant), et l'endpoint d'options (« auto » servi en 1ʳᵉ position, opt-in `auto=1`).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

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

    def test_les_deux_adopteurs_declarent_le_curseur_conditionne_a_auto(self):
        from wama.common.utils.param_schema import schema_for_app
        for app in ('synthesizer', 'avatarizer'):
            champ = next((f for f in schema_for_app(app)
                          if f.get('name') == 'quality_intent'), None)
            self.assertIsNotNone(champ, f"{app} : quality_intent absent du schéma")
            self.assertEqual(champ.get('type'), 'intent')
            self.assertEqual(champ.get('default'), 50)
            self.assertEqual(champ.get('show_if'),
                             {'field': 'tts_model', 'equals': 'auto'},
                             f"{app} : le curseur doit n'apparaître que sur « auto »")

    def test_l_anonymizer_est_rallie_au_curseur_commun_avec_son_pas_reel(self):
        """Même FORME utilisateur (type='intent'), déclinaison locale conservée : le champ
        reste `precision_level` (frontière des données — tasks/model_selector le lisent) et
        le pas reste 5 (5 paliers moteur réels, leçon du 2026-08-19)."""
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
        self.assertTrue(connus <= declares | set(ENGINE_BACKENDS) | {'audio-cpp'},
                        f"moteurs annoncés sans déclaration : {sorted(connus - declares - set(ENGINE_BACKENDS) - {'audio-cpp'})}")
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
        self.assertIsNone(backend_missing(SimpleNamespace(backend_ref='', composition={})))
        self.assertIsNone(backend_missing(
            SimpleNamespace(backend_ref='une.classe.Backend', composition={'runtime': {'engine': 'moteur-fantome'}})))

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
