"""`ingest_voice_refs` — le versement des voix de référence en médiathèque (marche 4 du plan
`MEDIA_STORAGE_TIERING §9.4`), rejoué sur le MEDIA_ROOT jetable du runner : PLAN sans effet,
puis `--apply` = une ligne par wav avec ses attributs, l'original retiré, le dossier disparu.
La commande a été exécutée UNE fois sur la base réelle (28 voix) ; cette garde est ce qui
reste quand la base réelle n'est plus là pour le prouver.
"""
import io
import struct
import wave
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(struct.pack('<' + 'h' * 1600, *([0] * 1600)))
    return buf.getvalue()


class IngestVoiceRefsTest(TestCase):
    def setUp(self):
        self.racine = Path(settings.MEDIA_ROOT) / 'synthesizer' / 'voice_references'
        for rel in ('french/adult/male_adult_1_fr.wav', 'default.wav'):
            p = self.racine / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(_wav())
        (self.racine / 'README.md').write_text('taxonomie', encoding='utf-8')

    def _run(self, *args):
        out = io.StringIO()
        call_command('ingest_voice_refs', *args, stdout=out)
        return out.getvalue()

    def test_le_plan_n_ecrit_rien(self):
        from wama.media_library.models import SystemAsset
        sortie = self._run()
        self.assertIn('PLAN', sortie)
        self.assertIn('à verser            : 2', sortie)
        self.assertEqual(SystemAsset.objects.filter(asset_type='voice').count(), 0)
        self.assertTrue((self.racine / 'default.wav').is_file())

    def test_apply_verse_avec_attributs_retire_l_original_et_le_dossier(self):
        from wama.media_library.models import SystemAsset
        from wama.common.tts.voice_refs import resolve_speaker_wav
        sortie = self._run('--apply')
        self.assertIn('versées : 2 / 2', sortie)
        v = SystemAsset.objects.get(asset_type='voice', name='french/adult/male_adult_1_fr')
        self.assertEqual(v.attributes, {'language': 'fr', 'age': 'adult', 'gender': 'male', 'variant': 1})
        self.assertTrue(v.file.name.startswith('media_library/system/'))
        self.assertAlmostEqual(v.duration, 0.1, places=2)
        d = SystemAsset.objects.get(asset_type='voice', name='default')
        self.assertEqual(d.attributes, {'language': 'en'})
        self.assertFalse(self.racine.exists(), 'le dossier (README compris) est retiré après versement')
        # l'ancien id résout vers le nouveau domicile — frontière des données (D5)
        self.assertEqual(resolve_speaker_wav('french/adult/male_adult_1_fr'), v.file.path)
        self.assertEqual(resolve_speaker_wav('inconnu'), d.file.path)

    def test_apply_est_idempotent(self):
        from wama.media_library.models import SystemAsset
        self._run('--apply')
        (self.racine / 'french/adult').mkdir(parents=True, exist_ok=True)
        (self.racine / 'french/adult/male_adult_1_fr.wav').write_bytes(_wav())   # revenu par erreur
        sortie = self._run('--apply')
        self.assertIn('déjà en médiathèque : 1', sortie)
        self.assertEqual(SystemAsset.objects.filter(asset_type='voice').count(), 2)
