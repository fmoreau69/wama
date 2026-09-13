"""La porte `speaker_wav_for` (common/tts/voice_refs) — marche 2 du plan voix
(`MEDIA_STORAGE_TIERING §9.4`) : c'est la CAPACITÉ du moteur qui décide d'un `speaker_wav`,
et les deux workers ne font plus que l'appeler.
"""
from unittest.mock import patch

from django.test import TestCase

from wama.common.tts import voice_refs


class LaCapaciteDecideTest(TestCase):
    def test_un_moteur_qui_ne_clone_pas_ne_recoit_JAMAIS_de_voix(self):
        with patch.object(voice_refs, 'model_supports_cloning', return_value=False), \
             patch.object(voice_refs, 'resolve_speaker_wav') as res:
            self.assertIsNone(voice_refs.speaker_wav_for('synthesizer:kokoro', 'ua_1', None,
                                                          reference_path='/tmp/ref.wav'))
            res.assert_not_called()

    def test_un_moteur_qui_clone_prend_la_reference_du_job_avant_le_preset(self):
        with patch.object(voice_refs, 'model_supports_cloning', return_value=True), \
             patch.object(voice_refs, 'resolve_speaker_wav') as res:
            self.assertEqual(voice_refs.speaker_wav_for('synthesizer:coqui-xtts', 'default', None,
                                                         reference_path='/tmp/ref.wav'),
                             '/tmp/ref.wav')
            res.assert_not_called()

    def test_un_moteur_qui_clone_resout_le_preset_par_la_brique(self):
        with patch.object(voice_refs, 'model_supports_cloning', return_value=True), \
             patch.object(voice_refs, 'resolve_speaker_wav', return_value='/x/default.wav') as res:
            self.assertEqual(voice_refs.speaker_wav_for('synthesizer:coqui-xtts', 'female_1', 'u'),
                             '/x/default.wav')
            res.assert_called_once_with('female_1', 'u')

    def test_un_moteur_INCONNU_recoit_une_voix_le_sens_sur(self):
        """XTTS l'exige, un moteur sans clonage l'ignore : le doute résout."""
        with patch.object(voice_refs, 'model_supports_cloning', return_value=None), \
             patch.object(voice_refs, 'resolve_speaker_wav', return_value='/x/d.wav'):
            self.assertEqual(voice_refs.speaker_wav_for('synthesizer:???', 'default'), '/x/d.wav')


class AutoriteDuMoteurTest(TestCase):
    """`model_supports_cloning` : la classe de moteur d'abord, le catalogue ensuite, None sinon."""

    def test_la_classe_de_moteur_fait_autorite(self):
        from wama.common.backends.coqui_backend import CoquiBackend
        from wama.common.backends.kokoro_backend import KokoroBackend
        with patch('wama.common.backends.manager.backend_for_key', return_value=CoquiBackend):
            self.assertIs(voice_refs.model_supports_cloning('synthesizer:coqui-xtts'), True)
        with patch('wama.common.backends.manager.backend_for_key', return_value=KokoroBackend):
            self.assertIs(voice_refs.model_supports_cloning('synthesizer:kokoro'), False)

    def test_sans_classe_le_catalogue_reconcilie_repond(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='synthesizer:test-clone', name='t', model_type='speech',
                               source='synthesizer', capabilities={'supports_cloning': True})
        AIModel.objects.create(model_key='synthesizer:test-muet', name='m', model_type='speech',
                               source='synthesizer', capabilities={'task': 'text-to-speech'})
        with patch('wama.common.backends.manager.backend_for_key', return_value=None):
            self.assertIs(voice_refs.model_supports_cloning('synthesizer:test-clone'), True)
            self.assertIsNone(voice_refs.model_supports_cloning('synthesizer:test-muet'))
            self.assertIsNone(voice_refs.model_supports_cloning('synthesizer:absent'))
        self.assertIsNone(voice_refs.model_supports_cloning(''))


class LesWorkersNeDecidentPlusRienTest(TestCase):
    """Garde textuelle : aucun worker ne recopie la résolution ni ne teste un nom de moteur."""

    FICHIERS = ('wama/synthesizer/workers.py', 'wama/avatarizer/workers.py',
                'wama/synthesizer/views.py')

    def _texte(self, rel):
        """Le CODE seul — les commentaires racontent ce qu'on a retiré, et le nomment."""
        from pathlib import Path

        from django.conf import settings
        lignes = Path(settings.BASE_DIR, rel).read_text(encoding='utf-8').splitlines()
        return '\n'.join(l for l in lignes if not l.lstrip().startswith('#'))

    def test_les_deux_workers_et_l_apercu_passent_par_la_porte(self):
        for rel in self.FICHIERS:
            self.assertIn('speaker_wav_for(', self._texte(rel), rel)

    def test_plus_aucune_resolution_ni_test_de_moteur_recopie(self):
        import re
        for rel in self.FICHIERS:
            t = self._texte(rel)
            self.assertIsNone(re.search(r"tts_model\s*==\s*'", t), rel)
            self.assertNotIn('_get_default_speaker_wav', t, rel)
            self.assertNotIn("voice_preset.startswith('ua_')", t, rel)
            self.assertNotIn('resolve_speaker_wav(', t, rel)
