"""Tests de la brique intake (WAMA_LLM §Intake universel) — les faits du replay du
2026-08-29 (5 témoins × 3 voies) verrouillés en invariants : composition par PORTS,
jamais par input_types/extensions à plat."""
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase, TestCase

from wama.common.utils import intake


class PortsParCategorieTests(SimpleTestCase):

    def test_un_fichier_texte_est_un_document_et_n_atteint_aucun_port_prompt(self):
        # Réécrit le 2026-08-30 (retrait de `text` des natures) : l'invariant n'est plus
        # « aucun port » mais « les ports DOCUMENT, et jamais un port PROMPT » — un .txt est un
        # fichier de travail des apps à documents, pas une saisie. L'ancien attendu (`category
        # 'text'`, ports []) mesurait l'homonyme, pas une propriété voulue.
        caps = intake.capabilities_for_path('notes.txt')
        self.assertEqual(caps['category'], 'document')
        groupes = {p['group'] for p in caps['ports']}
        self.assertNotIn('prompt', groupes,
                         'un FICHIER texte ne doit jamais atteindre un port de SAISIE')
        cibles = {(p['app'], p['group']) for p in caps['ports']}
        self.assertIn(('converter', 'travail'), cibles)
        self.assertIn(('describer', 'travail'), cibles)

    def test_un_wav_atteint_le_port_reference_voice_du_synthesizer(self):
        # Le « fichier de référence » que la voie par nature ne voit pas.
        caps = intake.capabilities_for_path('prise.wav')
        cibles = {(p['app'], p['port'], p['group']) for p in caps['ports']}
        self.assertIn(('synthesizer', 'reference_voice', 'reference'), cibles)
        self.assertIn(('transcriber', 'work', 'travail'), cibles)

    def test_les_jumelles_bac_a_sable_ne_remontent_jamais(self):
        for temoin in ('rapport.pdf', 'prise.wav', 'photo.jpg'):
            caps = intake.capabilities_for_path(temoin)
            apps = {p['app'] for p in caps['ports']}
            self.assertNotIn('converter_01', apps, temoin)

    def test_un_pdf_atteint_les_ports_travail_des_apps_document(self):
        caps = intake.capabilities_for_path('rapport.pdf')
        apps = {p['app'] for p in caps['ports'] if p['group'] == 'travail'}
        self.assertTrue({'converter', 'describer', 'reader'} <= apps)


class SniffsTests(SimpleTestCase):

    def test_un_lot_unifie_est_reconnu_comme_lot(self):
        with tempfile.TemporaryDirectory() as tmp:
            lot = Path(tmp) / 'lot.txt'
            lot.write_text('-i https://exemple.org/a.mp3 -p bonjour\n'
                           '-i https://exemple.org/b.mp3 -p monde\n', encoding='utf-8')
            caps = intake.capabilities_for_path(str(lot))
        self.assertIsNotNone(caps['batch'])
        self.assertTrue(caps['batch']['looks_like_batch'])

    def test_un_manifeste_est_reconnu_mais_declare_NON_ingestable(self):
        with tempfile.TemporaryDirectory() as tmp:
            man = Path(tmp) / 'mon_app.json'
            man.write_text(json.dumps({'kind': 'app', 'body': {}}), encoding='utf-8')
            caps = intake.capabilities_for_path(str(man))
        self.assertIsNotNone(caps['manifest'])
        self.assertEqual(caps['manifest']['kind'], 'app')
        self.assertTrue(caps['manifest']['registered'])
        self.assertFalse(caps['manifest']['ingestable'])  # ingest() sans porte, mesuré 29/08

    def test_un_wav_propose_le_role_voix_de_la_mediatheque(self):
        caps = intake.capabilities_for_path('prise.wav')
        self.assertIn('voice', caps['asset_types'])

    def test_une_sonde_de_monde_en_panne_ne_casse_pas_l_intake(self):
        def sonde_cassee(path):
            raise RuntimeError('monde en panne')
        with mock.patch.dict(intake.INTAKE_PROBES, {'casse': sonde_cassee}):
            caps = intake.capabilities_for_path('notes.txt')
        self.assertNotIn('casse', caps['probes'])

    def test_la_sonde_data_reconnait_une_source_tabulaire(self):
        # La sonde est poussée par wama_data/apps.py au ready() — présence + résultat.
        self.assertIn('data_sources', intake.INTAKE_PROBES)
        caps = intake.capabilities_for_path('mesures.csv')
        self.assertIn('data_sources', caps['probes'])
        self.assertEqual(caps['probes']['data_sources']['world'], 'data')
        self.assertEqual(caps['probes']['data_sources']['reader'], 'tabular')

    def test_un_trip_sans_fichier_reel_n_est_pas_atteste(self):
        # Découvert en écrivant ce test : trip/wdat attestent le CONTENU (table témoin
        # SQLite), pas l'extension — un chemin sans fichier réel décline À LA PORTE.
        # C'est le comportement VOULU du lecteur (un fichier mal nommé doit échouer ici,
        # pas au milieu d'une lecture) ; la sonde intake en hérite, verrouillé tel quel.
        caps = intake.capabilities_for_path('donnees.trip')
        self.assertNotIn('data_sources', caps['probes'])


class OutilsIntakeTests(TestCase):

    def test_le_visiteur_anonyme_est_refuse_sur_les_deux_outils(self):
        from wama.tool_api import TOOL_REGISTRY
        for nom, args in (('inspect_user_file', ('x.txt',)),
                          ('add_to_media_library', ('x.wav', 'voice'))):
            rendu = TOOL_REGISTRY[nom](AnonymousUser(), *args)
            self.assertIn('error', rendu, nom)
            self.assertIn('identifi', rendu['error'], nom)

    def test_la_mediatheque_refuse_un_role_incoherent_avec_l_extension(self):
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from wama.tool_api import TOOL_REGISTRY

        user = get_user_model().objects.create_user('intake_test', password='x')
        rel = f'users/{user.id}/temp/note.txt'
        abs_path = Path(settings.MEDIA_ROOT) / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text('bonjour', encoding='utf-8')
        try:
            rendu = TOOL_REGISTRY['add_to_media_library'](user, rel, 'voice')
            self.assertIn('error', rendu)
            self.assertIn('non admise', rendu['error'])
        finally:
            abs_path.unlink(missing_ok=True)


class OutilsChaineAssistantTests(TestCase):
    """look_at_image (l'œil synchrone) + la question réelle dans charger_competence."""

    def _creer_temp(self, user, nom, contenu=b'x'):
        from pathlib import Path
        from django.conf import settings
        rel = f'users/{user.id}/temp/{nom}'
        chemin = Path(settings.MEDIA_ROOT) / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(contenu)
        self.addCleanup(chemin.unlink)
        return rel

    def test_l_oeil_refuse_l_anonyme_et_les_non_images(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import AnonymousUser
        from wama.tool_api import TOOL_REGISTRY

        rendu = TOOL_REGISTRY['look_at_image'](AnonymousUser(), 'x.jpg')
        self.assertIn('identifi', rendu['error'])

        user = get_user_model().objects.create_user('oeil_test', password='x')
        rel = self._creer_temp(user, 'note.txt')
        rendu = TOOL_REGISTRY['look_at_image'](user, rel)
        self.assertIn('add_to_describer', rendu['error'])

    def test_l_oeil_rend_la_description_du_vlm_sans_l_inventer(self):
        from django.contrib.auth import get_user_model
        from wama.tool_api import TOOL_REGISTRY

        user = get_user_model().objects.create_user('oeil_test2', password='x')
        rel = self._creer_temp(user, 'plante.jpg')
        with mock.patch('wama.model_manager.services.vision_probe.describe_image_ollama',
                        return_value={'ok': True, 'description': 'un monstera aux feuilles jaunies'}) as vlm:
            rendu = TOOL_REGISTRY['look_at_image'](user, rel, 'de quelle plante s agit-il ?')
        self.assertEqual(rendu['description'], 'un monstera aux feuilles jaunies')
        self.assertIn('de quelle plante', vlm.call_args.kwargs.get('prompt', ''))

    def test_charger_competence_rappelle_sur_la_QUESTION_pas_sur_le_nom_du_domaine(self):
        from django.contrib.auth import get_user_model
        from wama.tool_api import TOOL_REGISTRY

        user = get_user_model().objects.create_user('comp_test', password='x')
        with mock.patch('wama.common.utils.assistant_skills.laboratory_context',
                        return_value='') as rappel:
            TOOL_REGISTRY['charger_competence'](user, 'science',
                                                question='effet du bruit sur la conduite ?')
        question_recue = rappel.call_args.args[1]
        self.assertEqual(question_recue, 'effet du bruit sur la conduite ?')
