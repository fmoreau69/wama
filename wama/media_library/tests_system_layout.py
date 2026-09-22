"""Les assets SYSTÈME se rangent par NATURE : `media_library/system/<asset_type>/`.

Décision de Fabien, 2026-09-22 (ligne D18 de `MEDIA_STORAGE_TIERING §8.6`). Trois choses se
gardent ici : l'`upload_to` range un NOUVEL asset au bon endroit ; la commande
`organize_system_assets` range les ANCIENS sans rien casser (plan sans effet, idempotente, cible
prise jamais écrasée) ; et remplacer une voix la laisse dans son dossier, sous un nom propre.
Le runner donne à chaque exécution un MEDIA_ROOT jetable.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import io
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from wama.common.utils.media_paths import system_asset_relpath
from wama.media_library.models import SystemAsset


class SystemAssetPathTest(SimpleTestCase):

    def test_the_path_carries_the_nature_and_only_the_nature(self):
        self.assertEqual('media_library/system/voice/male_adult_1_fr.wav',
                         system_asset_relpath('voice', 'some/where/male_adult_1_fr.wav'))

    def test_an_unusable_nature_never_escapes_the_system_root(self):
        self.assertEqual('media_library/system/other/x.png', system_asset_relpath('', 'x.png'))
        self.assertEqual('media_library/system/etcpasswd/x.png',
                         system_asset_relpath('../etc/passwd', 'x.png'))


class UploadToByNatureTest(TestCase):

    def test_a_new_system_asset_lands_in_its_nature_folder(self):
        asset = SystemAsset(name='new_avatar', asset_type='avatar')
        asset.file.save('new_avatar.png', ContentFile(b'\x89PNG'), save=True)
        self.assertEqual('media_library/system/avatar/new_avatar.png', asset.file.name)
        self.assertTrue(Path(asset.file.path).is_file())

    def test_replacing_a_voice_keeps_it_in_the_voice_folder_with_a_clean_name(self):
        """`ingest_voice_file` passe par l'`upload_to`, et `_settle_file_name` reprend le nom
        propre dans le dossier COURANT : le remplacement ne doit ni sortir de `voice/` ni suffixer."""
        import tempfile

        from wama.common.tts import voice_refs
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir) / 'male_adult_5_en.wav'
            second = Path(second_dir) / 'male_adult_5_en.wav'
            first.write_bytes(b'first-take')
            second.write_bytes(b'second-take')
            voice_refs.ingest_voice_file('english/adult/male_adult_5_en', first)
            asset = voice_refs.ingest_voice_file('english/adult/male_adult_5_en', second,
                                                 replace=True)
        asset.refresh_from_db()
        self.assertEqual('media_library/system/voice/male_adult_5_en.wav', asset.file.name)
        self.assertEqual(b'second-take', Path(asset.file.path).read_bytes())


class OrganizeCommandTest(TestCase):
    """La commande range les assets d'AVANT (posés à plat)."""

    def _flat_asset(self, name, asset_type, filename, content=b'data'):
        root = Path(settings.MEDIA_ROOT)
        relative = f'media_library/system/{filename}'
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(content)
        asset = SystemAsset.objects.create(name=name, asset_type=asset_type)
        SystemAsset.objects.filter(pk=asset.pk).update(file=relative)   # contourne l'upload_to
        return asset

    def _run(self, *args):
        out = io.StringIO()
        call_command('organize_system_assets', *args, stdout=out)
        return out.getvalue()

    def test_the_plan_writes_nothing(self):
        asset = self._flat_asset('flat_voice', 'voice', 'flat_voice.wav')
        output = self._run()
        asset.refresh_from_db()
        self.assertEqual('media_library/system/flat_voice.wav', asset.file.name)
        self.assertIn('à déplacer : 1', output)

    def test_apply_moves_the_file_and_rewrites_the_row_then_does_nothing_more(self):
        asset = self._flat_asset('flat_avatar', 'avatar', 'flat_avatar.png', b'avatar-bytes')
        self._run('--apply')
        asset.refresh_from_db()
        self.assertEqual('media_library/system/avatar/flat_avatar.png', asset.file.name)
        self.assertEqual(b'avatar-bytes', Path(asset.file.path).read_bytes())
        self.assertFalse((Path(settings.MEDIA_ROOT) / 'media_library/system/flat_avatar.png').exists())
        self.assertIn('à déplacer : 0', self._run('--apply'), "un second passage ne touche à rien")

    def test_a_taken_target_is_never_overwritten(self):
        asset = self._flat_asset('clash', 'voice', 'clash.wav', b'the-flat-one')
        taken = Path(settings.MEDIA_ROOT) / 'media_library/system/voice/clash.wav'
        taken.parent.mkdir(parents=True, exist_ok=True)
        taken.write_bytes(b'already-there')
        output = self._run('--apply')
        asset.refresh_from_db()
        self.assertEqual('media_library/system/clash.wav', asset.file.name, 'la ligne ne bouge pas')
        self.assertEqual(b'already-there', taken.read_bytes(), 'la cible n\'est pas écrasée')
        self.assertIn('cible déjà prise', output)
