"""
Le modèle de fichier batch ne propose que des moteurs TTS qui s'exécutent (2026-09-29).

Il montrait `--tts xtts_v2`, nom mort depuis le renommage `xtts_v2 → coqui-xtts` (2026-09-01,
`fb9ecfd9`) : `engine_for_model('xtts_v2')` lève, donc une ligne recopiée de l'aide échouait.
"""
import re

from django.test import RequestFactory, SimpleTestCase

from wama.avatarizer.views import batch_template
from wama.synthesizer.backends import engine_for_model


class BatchTemplateEnginesTest(SimpleTestCase):

    def test_every_tts_engine_shown_in_the_template_resolves(self):
        text = batch_template(RequestFactory().get('/')).content.decode('utf-8')
        engines = re.findall(r'--tts\s+([\w:.-]+)', text)
        self.assertTrue(engines, 'le modèle ne montre plus aucun --tts : la garde est aveugle')
        for engine in engines:
            engine_for_model(engine)          # lève si le nom est mort

    def test_counter_proof_the_old_name_is_refused(self):
        with self.assertRaises(ValueError):
            engine_for_model('xtts_v2')
