"""Tests du converter — nés de l'audit du 2026-08-31 (deux bugs MUETS confirmés).

Le fichier n'existait pas : le converter était couvert par la grille (adoption) et les
scénarios nocturnes (gestes), jamais par un test de comportement de vue. Les deux défauts
ci-dessous ont vécu précisément dans cet angle mort — aucun ne levait d'erreur.
"""
import io
import re
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.converter.utils import shots


class BatchDownloadTest(TestCase):
    """`batch_download` : le ZIP doit CONTENIR les sorties.

    Défaut confirmé le 2026-08-31 : `os.path` était utilisé (views.py:526-527) alors
    qu'`import os` ne vivait que dans `download_all` — chaque itération levait un
    `NameError` avalé par `except Exception: pass`, et le ZIP partait TOUJOURS VIDE,
    sans message. Un `except` large autour d'un corps qui référence un nom absent est
    exactement la famille « garde muette » : ce test tient l'invariant par le CONTENU.
    """

    def test_le_zip_d_un_lot_contient_les_sorties_reussies(self):
        from django.contrib.auth import get_user_model
        from wama.converter.models import ConversionBatch, ConversionJob

        user = get_user_model().objects.create_user('conv_zip_test', password='x')
        self.client.force_login(user)
        batch = ConversionBatch.objects.create(user=user, total=1)
        job = ConversionJob.objects.create(
            user=user, batch=batch, status='SUCCESS',
            input_filename='a.png', media_type='image', output_format='jpg')
        job.output_file.save('sortie.jpg', SimpleUploadedFile('sortie.jpg', b'JPGDATA'))

        # GET : c'est le geste de l'UI (`_batch_card.html` rend un LIEN `href` vers le ZIP) — la vue
        # commune (`make_batch_views`, 2026-09-23) le tient par `@require_GET` ; ce test POSTait.
        r = self.client.get(reverse('converter:batch_download', args=[batch.id]))
        self.assertEqual(r.status_code, 200)
        zf = zipfile.ZipFile(io.BytesIO(b''.join(r.streaming_content)))
        self.assertEqual(len(zf.namelist()), 1,
                         'ZIP de lot VIDE — le NameError muet (import os) est revenu')
        self.assertTrue(zf.namelist()[0].endswith('.jpg'))


class PreregagesQualiteTest(TestCase):
    """Les préréglages au MODÈLE ÉVÉNEMENTIEL (Fabien, 02/09 — ROADMAP §23.2quater) :
    un preset est un GESTE D'ÉCRITURE (le profil GÉNÉRAL commun à tous), plus un facteur
    au lancement. Choisir « web » ÉCRIT ses valeurs dans les colonnes au clic — l'utilisateur
    voit l'effet réel, le retouche, l'enregistre en profil s'il veut. Le dernier geste gagne.

    ⚠ HISTORIQUE : la V1 de ces tests (01/09) verrouillait l'INVERSE — « le preset agit au
    lancement sur le non-posé » (cascade effective_settings). Le modèle événementiel du
    02/09 la remplace : ne pas « réparer » un rouge d'ici en réintroduisant le preset dans
    la tâche — la tâche lit les COLONNES, et c'est le contrat.
    """

    def _job(self, **kw):
        from django.contrib.auth.models import User
        u, _ = User.objects.get_or_create(username='t_presets')
        base = dict(user=u, input_filename='x.png', media_type='image',
                    output_format='jpg', status='PENDING')
        base.update(kw)
        from wama.converter.models import ConversionJob
        return ConversionJob.objects.create(**base)

    def test_choisir_un_preset_ECRIT_ses_valeurs_dans_les_colonnes(self):
        from django.test import Client
        import json as _j
        j = self._job()
        c = Client()
        c.force_login(j.user)
        r = c.post(f'/converter/settings/{j.id}/',
                   {'options_json': _j.dumps({'quality_preset': 'web'})})
        self.assertEqual(r.status_code, 200, r.content)
        j.refresh_from_db()
        self.assertEqual(j.quality, 80, 'le preset « web » doit ÉCRIRE quality=80 au clic')
        self.assertEqual(j.quality_preset, 'web', 'la trace du dernier preset applique')

    def test_un_reglage_du_MEME_envoi_prime_sur_le_preset(self):
        # Le geste fin prime : « web » (80) + quality=95 dans le même POST → 95.
        from django.test import Client
        import json as _j
        j = self._job()
        c = Client()
        c.force_login(j.user)
        r = c.post(f'/converter/settings/{j.id}/',
                   {'options_json': _j.dumps({'quality_preset': 'web', 'quality': 95})})
        self.assertEqual(r.status_code, 200, r.content)
        j.refresh_from_db()
        self.assertEqual(j.quality, 95)

    def test_la_tache_lit_les_colonnes_le_preset_n_arbitre_plus_au_lancement(self):
        # Un job à quality POSÉE 72 et trace quality_preset='max' (98) : la valeur effective
        # au lancement est 72 — la trace n'écrase rien, elle n'est qu'une trace.
        from wama.common.utils.param_schema import effective_settings
        from wama.converter.params import PARAMS_JSON
        j = self._job(quality=72, quality_preset='max')
        eff = effective_settings(PARAMS_JSON, posees=j.options,
                                 contexte={'media_type': 'image'})
        self.assertEqual(eff['quality'], 72)

    def test_l_element_nait_COMPLET_les_defauts_sont_ecrits_a_la_creation(self):
        # Modèle événementiel : la création écrit les défauts applicables (chips pleines
        # dès la naissance — demande du 31/08, enfin réconciliée avec les presets).
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import Client
        PNG = bytes.fromhex(
            '89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de'
            '0000000c49444154789c63f8cfc00000000300015f0f18e20000000049454e44ae426082')
        from django.contrib.auth.models import User
        u, _ = User.objects.get_or_create(username='t_presets')
        c = Client()
        c.force_login(u)
        r = c.post('/converter/upload/',
                   {'file': SimpleUploadedFile('n.png', PNG, 'image/png'),
                    'output_format': 'jpg'})
        self.assertEqual(r.status_code, 200, r.content)
        from wama.converter.models import ConversionJob
        j = ConversionJob.objects.get(pk=r.json()['id'])
        # Le curseur S'APPLIQUE à la naissance (2026-11-25, décision de Fabien) : sa position de
        # naissance (50, « Équilibré ») écrit la qualité — elle restait le défaut du schéma, 85.
        self.assertEqual((j.quality, j.quality_intent, j.quality_preset), (90, 50, 'balanced'))


class TheSliderAppliesAtBirthTest(TestCase):
    """2026-11-25 (décision de Fabien) : la position du curseur à la naissance — postée, sinon
    retenue, sinon celle du schéma — écrit ses réglages d'encodage, sous le geste fin de l'auteur."""

    MP4 = b'\x00\x00\x00\x18ftypmp42'          # l'extension décide de la nature, pas le contenu

    def setUp(self):
        from django.contrib.auth.models import User
        from django.test import Client
        self.user, _ = User.objects.get_or_create(username='t_slider_birth')
        self.client = Client()
        self.client.force_login(self.user)

    def _drop(self, **posted):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from wama.converter.models import ConversionJob
        r = self.client.post('/converter/upload/', {
            'file': SimpleUploadedFile('clip.mp4', self.MP4, 'video/mp4'), **posted})
        self.assertEqual(r.status_code, 200, r.content)
        return ConversionJob.objects.get(pk=r.json()['id'])

    def test_a_video_is_born_with_what_the_slider_position_writes(self):
        from wama.converter.utils.quality_presets import values_for_intent
        job = self._drop()
        expected = values_for_intent('video', 50)
        self.assertEqual({k: getattr(job, k) for k in expected}, expected)
        self.assertEqual(job.encoder_preset, 'slow', 'the x264 speed reaches its column')

    def test_a_posted_position_and_a_posted_fine_setting_both_win(self):
        job = self._drop(quality_intent='15', video_quality='31')
        self.assertEqual((job.quality_intent, job.quality_preset, job.resolution_cap,
                          job.video_quality), (15, 'web', '720', 31))

    def test_what_the_slider_wrote_is_not_remembered_as_a_gesture(self):
        # Le volet poste ce qu'il montre : l'étalement de sa position, et une retouche à la main.
        from wama.common.utils.user_settings import read_panel_settings
        from wama.converter.params import PARAMS_JSON
        self._drop(quality_intent='50', video_quality='20', encoder_preset='slow',
                   resolution_cap='original', audio_bitrate='192k')
        kept = read_panel_settings(self.user, 'converter', PARAMS_JSON)   # défauts du schéma sinon
        self.assertEqual((kept['quality_intent'], kept['video_quality'], kept['encoder_preset']),
                         (50, None, 'medium'))
        self.assertEqual(kept['audio_bitrate'], '192k', 'a value the slider did not write stays')
        # Une naissance SANS volet (outil, import) reprend donc le curseur, pas une valeur figée.
        from wama.converter.models import ConversionJob
        from wama.converter.views import apply_birth_settings
        job = ConversionJob.objects.create(user=self.user, input_filename='b.mp4', media_type='video',
                                           output_format='mp4', status='PENDING')
        apply_birth_settings(job, 'video', {'quality_intent': '85'})
        self.assertEqual((job.video_quality, job.encoder_preset), (16, 'slow'))

    def test_a_url_line_without_nature_gets_its_slider_settings_when_the_file_arrives(self):
        from wama.converter.models import ConversionJob
        from wama.converter.tasks import _derive_media_type
        job = ConversionJob.objects.create(user=self.user, input_filename='', media_type='',
                                           source_url='https://example.org/page', status='PENDING',
                                           rotation='90')
        touched = _derive_media_type(job, '/tmp/page.mp4', 'page.mp4')
        self.assertEqual((job.media_type, job.video_quality, job.encoder_preset), ('video', 20, 'slow'))
        self.assertIn('video_quality', touched)
        # Contre-épreuve : un réglage POSÉ avant l'arrivée (la rotation, qui dépend de la nature)
        # reste — seule une colonne encore à son défaut naît.
        self.assertEqual(job.rotation, '90')
        self.assertNotIn('rotation', touched)

    def test_a_position_posed_before_the_file_arrives_is_the_one_that_spreads(self):
        from wama.converter.models import ConversionJob
        from wama.converter.tasks import _derive_media_type
        job = ConversionJob.objects.create(user=self.user, input_filename='', media_type='',
                                           source_url='https://example.org/page', status='PENDING',
                                           quality_intent=15)
        _derive_media_type(job, '/tmp/page.mp4', 'page.mp4')
        self.assertEqual((job.quality_intent, job.video_quality, job.resolution_cap), (15, 28, '720'))


class QualityIntentWritesTheColumnsTest(TestCase):
    """Chantier C (2026-09-20) : le CURSEUR commun est le geste de qualité du converter — même
    modèle événementiel que les presets (il ÉCRIT les réglages d'encodage, la tâche lit les
    colonnes), les presets étant ses positions nommées (Rapide 15 / Équilibré 50 / Qualité 85)."""

    def _job(self, **kw):
        from django.contrib.auth.models import User
        u, _ = User.objects.get_or_create(username='t_intent')
        base = dict(user=u, input_filename='x.png', media_type='image',
                    output_format='jpg', status='PENDING')
        base.update(kw)
        from wama.converter.models import ConversionJob
        return ConversionJob.objects.create(**base)

    def test_at_the_named_positions_the_slider_gives_exactly_the_preset_table(self):
        from wama.converter.utils.quality_presets import (
            intent_for_preset, preset_for_intent, preset_values, values_for_intent)
        for media in ('image', 'video', 'audio'):
            for key in ('web', 'balanced', 'max'):
                self.assertEqual(values_for_intent(media, intent_for_preset(key)),
                                 preset_values(media, key), (media, key))
        self.assertEqual((preset_for_intent(15), preset_for_intent(50), preset_for_intent(85)),
                         ('web', 'balanced', 'max'))
        self.assertEqual(values_for_intent('document', 70), {})

    def test_between_two_positions_every_notch_moves_the_encoding(self):
        from wama.converter.utils.quality_presets import values_for_intent
        q = [values_for_intent('image', v)['quality'] for v in (15, 30, 50, 70, 85)]
        self.assertEqual(q, sorted(q))
        self.assertEqual((q[0], q[2], q[4]), (80, 90, 98))
        self.assertTrue(80 < q[1] < 90 and 90 < q[3] < 98)
        crf = [values_for_intent('video', v)['video_quality'] for v in (15, 50, 85)]
        # « Rapide (web) » vraiment léger depuis le 2026-11-19 (décision de Fabien) : CRF 28 en 720p.
        self.assertEqual(crf, [28, 20, 16])
        self.assertEqual(values_for_intent('video', 15)['resolution_cap'], '720')
        self.assertEqual(values_for_intent('audio', 67)['audio_bitrate'][-1], 'k')
        self.assertLess(values_for_intent('image', 0)['quality'], 81)          # sous la 1re position
        self.assertEqual(values_for_intent('image', 100)['quality'], 98)      # au-delà de la dernière
        self.assertEqual(values_for_intent('video', 85)['encoder_preset'], 'slow')   # non numérique : la plus proche

    def test_every_notch_of_the_slider_lands_on_a_choice_of_the_schema(self):
        # Un réglage À CHOIX reçoit une valeur de sa liste, à chaque cran (2026-11-25) : le débit
        # audio des positions « Rapide » (160k) et « Équilibré » (224k), puis les débits
        # interpolés entre deux positions, tombaient hors de la liste — la ⚙ affichait « Auto ».
        # Et chaque réglage écrit est un réglage DÉCLARÉ, rangé dans l'« Avancé », qui a sa COLONNE
        # (2026-11-25) : la vitesse x264 (`preset`) et `optimize` étaient écrits sans être déclarés —
        # ni vus, ni retouchables, et perdus pour tout job de la file.
        from wama.converter.models import ConversionJob
        from wama.converter.params import PARAMS
        from wama.converter.utils.quality_presets import values_for_intent
        choices = {p.name: {value for value, _label in p.choices}
                   for p in PARAMS if p.type == 'select' and p.choices}
        declared = {p.name: p for p in PARAMS}
        columns = set(ConversionJob.CHAMPS_OPTIONS)
        for media in ('image', 'video', 'audio'):
            for notch in range(0, 101):
                for name, value in values_for_intent(media, notch).items():
                    self.assertIn(name, declared, (media, notch, name))
                    self.assertTrue(declared[name].advanced, (media, name))
                    self.assertIn(name, columns, (media, name))
                    # Jamais vide ni « non réglé » (2026-11-25) : « Inchangée » est un choix, `original`.
                    if name in choices:
                        self.assertIn(value, choices[name], (media, notch, name))
        self.assertEqual(values_for_intent('audio', 30)['audio_bitrate'], '192k')
        self.assertEqual(values_for_intent('video', 85)['resolution_cap'], 'original')

    def test_moving_the_slider_writes_the_encoding_and_leaves_both_traces(self):
        from django.test import Client
        import json as _j
        j = self._job()
        c = Client()
        c.force_login(j.user)
        r = c.post(f'/converter/settings/{j.id}/', {'options_json': _j.dumps({'quality_intent': 85})})
        self.assertEqual(r.status_code, 200, r.content)
        j.refresh_from_db()
        self.assertEqual((j.quality, j.quality_intent, j.quality_preset), (98, 85, 'max'))
        # Un réglage fin du MÊME envoi prime (le geste fin gagne, comme pour un preset).
        c.post(f'/converter/settings/{j.id}/', {'options_json': _j.dumps({'quality_intent': 15, 'quality': 77})})
        j.refresh_from_db()
        self.assertEqual((j.quality, j.quality_intent, j.quality_preset), (77, 15, 'web'))

    def test_a_preset_key_still_works_and_sets_the_slider_position(self):
        from django.test import Client
        import json as _j
        j = self._job()
        c = Client()
        c.force_login(j.user)
        c.post(f'/converter/settings/{j.id}/', {'options_json': _j.dumps({'quality_preset': 'balanced'})})
        j.refresh_from_db()
        self.assertEqual((j.quality, j.quality_intent, j.quality_preset), (90, 50, 'balanced'))

    def test_the_batch_slider_writes_every_daughter(self):
        from django.test import Client
        from wama.converter.models import ConversionBatch
        j1 = self._job()
        batch = ConversionBatch.objects.create(user=j1.user, media_type='image')
        j2 = self._job(batch=batch)
        j1.batch = batch
        j1.save(update_fields=['batch'])
        c = Client()
        c.force_login(j1.user)
        r = c.post(f'/converter/batch/{batch.id}/update/', {'quality_intent': '70'})
        self.assertEqual(r.status_code, 200, r.content)
        for j in (j1, j2):
            j.refresh_from_db()
            self.assertEqual(j.quality_intent, 70)
            self.assertTrue(90 < j.quality < 98)
            self.assertEqual(j.quality_preset, 'max')

    def test_the_schema_carries_the_slider_and_no_longer_the_preset_select(self):
        from wama.converter.params import PARAMS_JSON
        names = {p['name']: p for p in PARAMS_JSON}
        self.assertEqual(names['quality_intent']['type'], 'intent')
        self.assertNotIn('quality_preset', names)
        self.assertTrue(names['quality'].get('advanced'))


class PanelSavesTheFlatSettingsTest(TestCase):
    """2026-11-19, Fabien : « le converter doit passer par le commun ». The panel, the item ⚙ and the
    batch ⚙ post the SAME flat settings (`WamaInspector` / `WamaParams.read` : every field shown, as
    shown) — the converter posted its own blob (`options_json`), built by a reader that DROPPED every
    empty value : « Aucune » rotation, an emptied number or an unticked mirror were never saved."""

    def _job(self, **kw):
        from django.contrib.auth.models import User
        from wama.converter.models import ConversionJob
        user, _ = User.objects.get_or_create(username='t_flat_panel')
        base = dict(user=user, input_filename='x.mp4', media_type='video',
                    output_format='mp4', status='PENDING')
        base.update(kw)
        return ConversionJob.objects.create(**base)

    def _post(self, job, **posted):
        from django.test import Client
        client = Client()
        client.force_login(job.user)
        r = client.post(f'/converter/settings/{job.id}/',
                        {'media_type': job.media_type, 'output_format': job.output_format, **posted})
        self.assertEqual(r.status_code, 200, r.content)
        job.refresh_from_db()
        return job

    def test_a_neutral_choice_an_emptied_number_and_an_unticked_mirror_are_saved(self):
        # « Aucune », « Inchangée » : un choix qui a sa vraie valeur (2026-11-25), pas le vide.
        job = self._post(self._job(rotation='90', fps=30, flip_h=True, resolution_cap='720'),
                         rotation='none', fps='', flip_h='false', resolution_cap='original')
        self.assertEqual(('none', None, False, 'original'),
                         (job.rotation, job.fps, job.flip_h, job.resolution_cap))
        self.assertNotIn('rotation', job.options, 'a neutral choice asks nothing of the engine')
        self.assertNotIn('resolution_cap', job.options)
        # Counter-proof : an EMPTY choice is « not given » — the column keeps its value.
        job = self._post(self._job(rotation='90'), rotation='')
        self.assertEqual('90', job.rotation)

    def test_the_maximum_definition_is_a_column_the_task_reads(self):
        job = self._post(self._job(), resolution_cap='540')
        self.assertEqual('540', job.resolution_cap)
        self.assertEqual('540', job.options.get('resolution_cap'))

    def test_a_setting_of_another_nature_is_not_written(self):
        # The image panel also carries the video and audio fields, hidden : what is shown is posted.
        job = self._post(self._job(media_type='image', input_filename='x.png', output_format='jpg'),
                         quality='77', gif_fps='12', gif_width='480', audio_bitrate='192k')
        self.assertEqual((77, None, None, 'auto'), (job.quality, job.gif_fps, job.gif_width, job.audio_bitrate))

    def test_the_slider_is_not_undone_by_the_fields_posted_unchanged(self):
        job = self._post(self._job(video_quality=20, quality_intent=50),
                         quality_intent='15', video_quality='20', resolution_cap='original')
        self.assertEqual((28, '720', 15), (job.video_quality, job.resolution_cap, job.quality_intent))
        # A field CHANGED in the same sending still wins over the slider (the fine gesture).
        job = self._post(job, quality_intent='15', video_quality='24', resolution_cap='720')
        self.assertEqual(24, job.video_quality)

    def test_settings_written_from_outside_a_form_follow_the_same_rules(self):
        # The `params` of a Studio node (`write_element_settings`) : the SAME reading as a request.
        from wama.common.utils.batch_views import write_element_settings
        job = self._job(media_type='image', input_filename='x.png', output_format='jpg', rotation='90')
        write_element_settings(job, {'media_type': 'image', 'rotation': 'none', 'gif_fps': '12'})
        job.refresh_from_db()
        self.assertEqual(('none', None), (job.rotation, job.gif_fps))

    def test_the_batch_settings_follow_the_same_rules(self):
        from django.test import Client
        from wama.converter.models import ConversionBatch
        batch = ConversionBatch.objects.create(user=self._job().user, media_type='image')
        jobs = [self._job(batch=batch, media_type='image', input_filename='x.png', output_format='jpg',
                          rotation='90') for _ in range(2)]
        client = Client()
        client.force_login(batch.user)
        r = client.post(f'/converter/batch/{batch.id}/update/',
                        {'media_type': 'image', 'rotation': 'none', 'gif_fps': '12'})
        self.assertEqual(r.status_code, 200, r.content)
        for job in jobs:
            job.refresh_from_db()
            self.assertEqual(('none', None), (job.rotation, job.gif_fps))


class QuickConvertTakesTheCommonSliderTest(TestCase):
    """La CONVERSION RAPIDE du gestionnaire de fichiers (2026-11-19, Fabien : « l'aligner sur le
    fonctionnement commun de WAMA ») : sa qualité est le curseur commun, rendu du schéma et
    appliqué par le geste de la ⚙ — la modale avait son menu de trois presets, la vue sa propre
    écriture du preset, et une position « Équilibré » forcée quand rien n'était posté."""

    PNG = bytes.fromhex(
        '89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de'
        '0000000c49444154789c63f8cfc00000000300015f0f18e20000000049454e44ae426082')

    def setUp(self):
        from pathlib import Path
        from django.conf import settings
        from django.contrib.auth.models import User
        self.user, _ = User.objects.get_or_create(username='t_quick')
        self.client.force_login(self.user)
        self.rel = f'users/{self.user.id}/temp/quick_source.png'
        source = Path(settings.MEDIA_ROOT) / self.rel
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(self.PNG)
        self.addCleanup(source.unlink, missing_ok=True)

    def _convert(self, **gesture):
        from unittest import mock
        from wama.converter.models import ConversionJob
        task = mock.Mock(id='t-quick')
        with mock.patch('wama.converter.tasks.convert_media_task.delay', return_value=task):
            r = self.client.post(reverse('converter:quick_convert'),
                                 {'file_path': self.rel, 'output_format': 'jpg', **gesture})
        self.assertEqual(r.status_code, 200, r.content)
        return ConversionJob.objects.get(pk=r.json()['id'])

    def test_the_slider_position_writes_the_encoding_like_the_settings_window(self):
        job = self._convert(quality_intent='85')
        self.assertEqual((job.quality, job.quality_intent, job.quality_preset), (98, 85, 'max'))

    def test_a_named_preset_still_writes_its_values_and_the_slider_position(self):
        job = self._convert(quality_preset='web')
        self.assertEqual((job.quality, job.quality_intent, job.quality_preset), (80, 15, 'web'))

    def test_without_a_gesture_the_element_is_born_like_by_any_other_way(self):
        """Counter-proof : no « Équilibré » forced by the view — the common birth, whose slider
        position (this account's, else the schema's) applies since 2026-11-25."""
        job = self._convert()
        self.assertEqual((job.quality, job.quality_intent, job.quality_preset), (90, 50, 'balanced'))

    def test_the_window_reads_its_slider_and_the_real_effect_from_the_server(self):
        url = reverse('converter:api_presets')
        data = self.client.get(url, {'media_type': 'image', 'quality_intent': '85'}).json()
        self.assertEqual({'media_type', 'quality_intent'}, {p['name'] for p in data['schema']})
        self.assertEqual('intent', next(p for p in data['schema'] if p['name'] == 'quality_intent')['type'])
        self.assertEqual(50, data['values']['quality_intent'], 'the birth position of this account')
        self.assertEqual({'quality': 98}, data['effect'], 'the « max » position')
        # The slider it serves says its effect itself (`effect_source`), with the schema's labels.
        slider = next(p for p in data['schema'] if p['name'] == 'quality_intent')
        self.assertEqual('converter', slider['effect_source'])
        self.assertNotIn('effect_labels', data)
        self.assertEqual({'quality': 90}, self.client.get(url, {'media_type': 'image'}).json()['effect'])
        self.assertEqual({'presets'}, set(self.client.get(url).json()), 'the table alone, as the tool reads it')

    def test_the_window_writes_no_quality_choice_of_its_own_and_follows_the_common_id(self):
        from pathlib import Path
        from django.conf import settings
        root = Path(settings.BASE_DIR)
        sidebar = (root / 'wama/filemanager/templates/filemanager/sidebar.html').read_text(encoding='utf-8')
        script = (root / 'wama/filemanager/static/filemanager/js/filemanager.js').read_text(encoding='utf-8')
        self.assertNotIn('converterQuickPreset"', sidebar)
        self.assertNotIn('<option value="balanced"', sidebar)
        self.assertNotIn("'quality_preset'", script)
        self.assertIn("fd.append('quality_intent'", script)
        self.assertNotIn('data.job_id', script, 'the quick view answers the common `id`')
        self.assertNotIn("video_quality: 'CRF'", script, 'the effect labels come from the schema')
        self.assertNotIn('converterQuickPresetEffect', sidebar + script,
                         'the effect is the common slider note, not a line of its own')
        self.assertNotIn("'heic','heif'", script, 'the accepted extensions are served, not copied')
        self.assertEqual(script, (root / 'staticfiles/filemanager/js/filemanager.js').read_text(encoding='utf-8'))

    def test_the_page_serves_the_extensions_the_converter_detects(self):
        """The menu entry and the window's nature read what `detect_media_type` reads."""
        import json
        from wama.converter.utils.format_router import SUPPORTED_CONVERSIONS, detect_media_type
        served = json.loads(self.client.get('/').context['converter_input_extensions_json'])
        self.assertEqual(set(SUPPORTED_CONVERSIONS), set(served))
        for nature, exts in served.items():
            for ext in exts:
                self.assertEqual(nature, detect_media_type(f'x.{ext}'), ext)


class SauverCommeProfilTest(TestCase):
    """Le lecteur de la modale « Sauver comme profil » doit lire ce que WamaParams ÉMET.

    Défaut confirmé le 2026-08-31 : `converter.js:867` appelait `readModalForm()` qui
    lit des `[data-key]` — un attribut que `wama-params.js` n'émet nulle part (0
    occurrence) → `output_format` toujours vide → toast « Format de sortie requis »
    systématique : le bouton était MORT à l'usage. Un test Python ne peut pas cliquer,
    mais il peut tenir les deux invariants de la correction : le handler appelle le
    lecteur SCHÉMA-driven, et l'hypothèse « data-key n'existe pas » reste vraie (si un
    jour WamaParams émettait data-key, ce test rappelle de réexaminer les deux lecteurs).
    """

    def _js(self, chemin):
        from pathlib import Path
        import wama
        return (Path(wama.__file__).parent.parent / chemin).read_text(encoding='utf-8')

    def test_le_bouton_profil_lit_via_le_schema_et_data_key_reste_absent_de_wamaparams(self):
        js = self._js('wama/converter/static/converter/js/converter.js')
        # Depuis le NETTOYAGE du 31/08 (REMOVAL_LEDGER) : la voie legacy est RETIRÉE
        # (buildModalFormHTML + readModalForm, branche inatteignable) — le fork qui avait
        # créé le bug n'existe plus, les deux lecteurs sont la MÊME fonction schéma.
        # Since 2026-09-24 the item modal is GENERATED by the shared cycle: the button is found by
        # class in its `decorate`, and reads the modal through the schema reader `readParamsFrom`
        # directly (`readModalViaSchema` was a one-line wrapper around it).
        i = js.index('jobSettingsSaveProfileBtn')
        self.assertIn('readParamsFrom(host, mediaType)', js[i:i + 300],
                      'le handler « Sauver comme profil » ne lit plus via le schéma')
        for mort in ('readModalForm', 'buildModalFormHTML', 'readCurrentModal'):
            vivants = [l for l in js.splitlines() if mort in l and 'RETIRÉE' not in l]
            self.assertEqual(vivants, [], f'{mort} : le mort est revenu')
        params = self._js('wama/common/static/common/js/wama-params.js')
        self.assertNotIn('data-key', params,
                         'WamaParams émet désormais data-key : réexaminer readModalForm '
                         '(le mort pourrait revivre — ou être retiré pour de bon)')


class AdoptionDeLaBriqueDEntreeDeFileTest(TestCase):
    """Le converter est passé sur `common/_queue_entry.html` le 2026-09-09 — DERNIER des 10.

    Le portage a levé un verrou de nommage (`job` → `elem` dans `_job_card.html`), et c'est
    précisément le genre de geste dont les ratés ne LÈVENT RIEN : un gabarit Django qui
    déréférence un nom absent ne casse pas, il rend du VIDE. Les deux contrats ci-dessous
    sont ceux que le port pouvait emporter sans un mot ; aucun n'était gardé avant ce jour.
    """

    def _utilisateur(self, nom):
        """Un compte qui FRANCHIT le portier, jamais un superuser.

        `AppAccessMiddleware` redirige (302) un compte sans rôle : neutraliser le portier
        rendrait le test aveugle à une régression du gating (arbitrage repris de
        `nightly_tests.get_test_user()` et de la fabrique du synthesizer).
        """
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX

        u = get_user_model().objects.create_user(nom, password='x')
        for role in ('communication', 'recherche', 'ingenierie', 'administratif'):
            g, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
            u.groups.add(g)
        self.client.force_login(u)
        return u

    def test_le_wrapper_de_lot_porte_la_NATURE_du_lot(self):
        """`data-media-type` sur `.batch-group` — lu par `converter.js:378`.

        Le converter rendait ce wrapper lui-même ; la brique commune ne l'émettait pas. La
        modale de réglages d'un LOT dérive ses options de format de la NATURE, que le bouton
        de `_batch_card.html` ne porte PAS : ce wrapper en est la SEULE source (mesuré avant
        le port). Sans lui, `mt` vaut `undefined` et la modale s'ouvre sur une nature vide —
        sans erreur console, sans 500, sans rien.
        """
        from wama.converter.models import ConversionBatch, ConversionJob

        u = self._utilisateur('conv_nature')
        lot = ConversionBatch.objects.create(user=u, total=2, media_type='image')
        for n in ('un.png', 'deux.png'):
            ConversionJob.objects.create(user=u, batch=lot, input_filename=n,
                                         media_type='image')

        html = self.client.get('/converter/').content.decode('utf-8', 'replace')
        self.assertIn(f'data-batch-id="{lot.id}"', html,
                      'le lot ne porte pas son id : la brique ne rend pas son wrapper')

        # ⚠ L'assertion doit porter sur LA BALISE `.batch-group`, pas sur la page. Première
        # version écrite : `assertIn('data-media-type="image"', html)` — elle restait VERTE
        # avec l'attribut retiré de la brique, parce que le ⚙ de chaque card FILLE en émet un
        # homonyme via `gear_data` (index.html:338). Or `onBatchSettings` reçoit le bouton du
        # LOT, qui n'a pas de `gear_data` : la fille ne le secourt pas. Une garde qui se
        # satisfait d'une occurrence homonyme ailleurs dans la page ne garde rien — trouvé par
        # contre-épreuve, pas par relecture.
        ouvrante = re.search(r'<div class="batch-group[^>]*>', html)
        self.assertIsNotNone(ouvrante, 'aucun wrapper de lot rendu')
        balise = ouvrante.group(0)
        self.assertIn(f'data-batch-id="{lot.id}"', balise)
        self.assertIn('data-media-type="image"', balise,
                      "le wrapper de lot a perdu la NATURE — la modale de réglages du lot "
                      "s'ouvrira sans elle, en silence (converter.js:378). Balise rendue :\n"
                      + balise)

    def test_l_endpoint_card_html_rend_une_card_HABITEE(self):
        """La clé de contexte du partial — jumeau PAR CHAÎNE du renommage `job` → `elem`.

        `card_html` est la source unique du markup au rafraîchissement (le JS remplace le
        nœud entier). Renommer la variable DANS le gabarit sans renommer la clé qui l'alimente
        aurait rendu une card structurellement complète et TOTALEMENT VIDE — statut, nom de
        fichier, boutons : tout déréférencé sur un nom absent. Un `manage.py check` passe,
        aucun test de vue ne l'ouvrait. On exige donc du CONTENU, pas un 200.
        """
        from wama.converter.models import ConversionBatch, ConversionJob

        u = self._utilisateur('conv_card_html')
        lot = ConversionBatch.objects.create(user=u, total=1)
        job = ConversionJob.objects.create(user=u, batch=lot, status='SUCCESS',
                                           input_filename='temoin_habite.png',
                                           media_type='image', output_format='jpg')

        r = self.client.get(reverse('converter:card_html', args=[job.id]))
        self.assertEqual(200, r.status_code)
        html = r.content.decode('utf-8', 'replace')
        self.assertIn('temoin_habite.png', html,
                      'card VIDE : le gabarit lit `elem`, la vue alimente autre chose')
        self.assertIn(f'data-id="{job.id}"', html)
        self.assertIn('data-status="SUCCESS"', html)

    def test_le_gabarit_ne_recopie_plus_le_bloc_d_entree_de_file(self):
        """Le POINT du portage : plus une 11ᵉ copie, mais l'appel à la brique.

        Garde de non-retour — c'est la duplication elle-même qu'on interdit, pas son
        symptôme. Un futur correctif « local » qui réécrirait la boucle ici rendrait le
        converter à nouveau sourd aux corrections de la brique.
        """
        from pathlib import Path

        from django.conf import settings

        src = (Path(settings.BASE_DIR) / 'wama' / 'converter' / 'templates'
               / 'converter' / 'index.html').read_text(encoding='utf-8')
        # Depuis le 2026-10-20, par la FILE commune, qui inclut l'entrée commune.
        self.assertIn("include 'common/_queue.html'", src,
                      "le converter ne passe plus par la file commune")
        for recopie in ("{% for job in b.items %}", "{% for item in b.items %}"):
            self.assertNotIn(recopie, src,
                             f'boucle de file recopiée à la main ({recopie}) : la brique '
                             'la tient déjà')


class LancementSansFormatTest(TestCase):
    """Un job SANS format de sortie ne part pas en tâche (job #27, relevé par Fabien le 2026-09-14).

    Un import par lot ou par fichier crée ses jobs avec `output_format=''`. `batch_start` les
    sautait déjà ; `start` et `start_all`, non : la tâche descendait jusqu'au backend vidéo, qui
    répondait « Format vidéo non supporté : » — format VIDE, lu comme un rejet de codec d'entrée.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model
        from wama.converter.models import ConversionJob
        self.user = get_user_model().objects.create_user('conv_sans_format', password='x')
        self.client.force_login(self.user)
        self.sans = ConversionJob.objects.create(
            user=self.user, input_filename='SEQ08-01.mp4', media_type='video',
            output_format='', status='PENDING')
        self.avec = ConversionJob.objects.create(
            user=self.user, input_filename='b.mp4', media_type='video',
            output_format='webm', status='PENDING')

    def test_start_REFUSE_un_job_sans_format_et_ne_lance_rien(self):
        from unittest import mock
        with mock.patch('wama.converter.tasks.convert_media_task.delay') as delay:
            r = self.client.post(reverse('converter:start', args=[self.sans.id]))
        self.assertEqual(r.status_code, 400)
        self.assertIn('Format de sortie non défini', r.json()['error'])
        delay.assert_not_called()
        self.sans.refresh_from_db()
        self.assertEqual(self.sans.status, 'PENDING', 'refusé = reste relançable, jamais RUNNING')

    def test_start_all_SAUTE_le_job_sans_format_et_lance_les_autres(self):
        from unittest import mock
        with mock.patch('wama.converter.tasks.convert_media_task.delay') as delay:
            delay.return_value.id = 'tache-test'
            d = self.client.post(reverse('converter:start_all')).json()
        self.assertEqual(d['started'], [self.avec.id])
        self.assertEqual(d['skipped'], [self.sans.id])
        self.sans.refresh_from_db()
        self.assertEqual(self.sans.status, 'PENDING')

    def test_la_tache_dit_FORMAT_NON_DEFINI_et_non_format_non_supporte(self):
        """Toutes les voies de lancement (gestionnaire de fichiers, API) passent par la glu."""
        from unittest import mock
        from wama.converter.tasks import _convert
        with self.assertRaisesMessage(ValueError, 'Format de sortie non défini'):
            _convert(self.sans, mock.Mock())


class LaCardPasseParEnCoursTest(TestCase):
    """Le lancement unitaire REDESSINE la card depuis le serveur (relevé par Fabien le 2026-09-14).

    `startJob` écrivait `card.dataset.status = 'RUNNING'` AVANT la requête (depuis avril) ; depuis
    le portage du 26/07, `pollJob` ne redessine la card qu'à un CHANGEMENT entre ce `data-status`
    et le statut serveur. Les deux valant déjà RUNNING, « En cours » ne s'affichait jamais : la
    card sautait d'« En attente » / « Échec » directement au résultat. Aucun vérificateur JS n'est
    installé : la garde lit le source, et la copie servie (`staticfiles/`).
    """

    def _source(self, racine='wama/converter/static'):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / racine / 'converter' / 'js'
                / 'converter.js').read_text(encoding='utf-8')

    def _fonction(self, nom, suivante):
        """Corps de la fonction, SANS ses commentaires `//` : la garde porte sur le CODE — le
        commentaire qui raconte le défaut cite justement la ligne interdite (1er run : rouge sur
        sa propre explication)."""
        src = self._source()
        debut = src.index(f'async function {nom}(')
        corps = src[debut:src.index(suivante, debut + 1)]
        return '\n'.join(l for l in corps.splitlines() if not l.strip().startswith('//'))

    def test_le_lancement_ne_pose_plus_RUNNING_a_l_avance_et_redessine_avant_de_suivre(self):
        corps = self._fonction('startJob', 'async function cancelJob(')
        self.assertNotIn("dataset.status = 'RUNNING'", corps,
                         "RUNNING posé côté client : `pollJob` ne verra jamais de transition")
        self.assertIn('await refreshCard(jobId);', corps)
        self.assertLess(corps.index('await refreshCard(jobId);'), corps.index('startPolling(jobId);'))

    def test_l_arret_redessine_la_card(self):
        corps = self._fonction('cancelJob', '// Suppression')
        self.assertNotIn("dataset.status = 'PENDING'", corps)
        self.assertIn('await refreshCard(jobId);', corps)

    # `test_la_copie_SERVIE_est_celle_du_source` RETIRÉ le 2026-09-26 : tenu pour TOUT fichier de
    # toute app par `common/tests_served_assets_contract` (WAMA_VERIFICATION §8).


class InlineSameFormatReencodeTest(TestCase):
    """« .PNG + Web » on a PNG re-encodes in place (2026-09-23): the same-format choice was a
    silent no-op, so the quality setting lied."""

    def test_same_format_is_reencoded_in_place(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from PIL import Image
        from wama.converter.utils.inline_convert import apply_inline_conversion
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'out.png'
            Image.new('RGB', (8, 8)).save(src)

            def fake_convert(source, dest, fmt, quality=90, options=None):
                Path(dest).write_bytes(b'reencoded')
            with patch('wama.converter.backends.image_backend.convert_image', fake_convert):
                result = apply_inline_conversion(str(src), 'png', 'web')
            self.assertEqual(str(src), result)
            self.assertEqual(b'reencoded', src.read_bytes())
            self.assertEqual(['out.png'], sorted(p.name for p in Path(tmp).iterdir()))


class VideoResolutionCapTest(TestCase):
    """The converter REDUCES a video (2026-11-19, Fabien's decision : « Rapide » in 720p) — the short
    side brought down to `resolution_cap`, never enlarged, an explicit size first ; played by the
    real ffmpeg on generated test patterns."""

    def _encode(self, size: str, **options) -> tuple:
        import subprocess
        import tempfile
        from pathlib import Path

        from wama.converter.backends.video_backend import _get_ffmpeg, convert_video
        from wama.common.utils.video_utils import get_media_info
        ffmpeg = _get_ffmpeg()
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / 'src.mp4', Path(tmp) / 'out.mp4'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', f'testsrc=size={size}:rate=10',
                            '-t', '1', '-pix_fmt', 'yuv420p', str(src)], check=True)
            convert_video(str(src), str(out), 'mp4', options=options)
            info = get_media_info(str(out))
        return info.get('width'), info.get('height')

    def test_the_short_side_is_brought_down_to_the_cap(self):
        self.assertEqual((1280, 720), self._encode('1920x1080', resolution_cap='720'))
        self.assertEqual((720, 1280), self._encode('1080x1920', resolution_cap='720'))

    def test_a_smaller_video_is_never_enlarged(self):
        self.assertEqual((640, 360), self._encode('640x360', resolution_cap='720'))

    def test_an_explicit_size_comes_first(self):
        self.assertEqual((320, 180), self._encode('1920x1080', resolution_cap='720', resize_w=320))


class ShotsFromCutsTest(SimpleTestCase):
    """`converter.shots` (`ROUTE §10.7.14` step 19) — what ffmpeg says becomes shots that cover the
    video from its start to its end, with neither gap nor overlap."""

    def test_the_cuts_ffmpeg_says_are_read_in_time_order(self):
        said = ("[scdet @ 0x55] lavfi.scd.score: 26.360, lavfi.scd.time: 3.5\n"
                "frame=  110 fps=0.0\n"
                "[scdet @ 0x55] lavfi.scd.score: 33.142, lavfi.scd.time: 2\n")
        self.assertEqual([(2.0, 33.142), (3.5, 26.36)], shots.cuts_of(said))
        self.assertEqual([], shots.cuts_of(''))

    def test_shots_cover_the_video_and_each_one_says_the_cut_that_opens_it(self):
        found = shots.shots_from_cuts([(2.0, 33.142), (3.5, 26.36)], 5.5)
        self.assertEqual([{'start': 0.0, 'end': 2.0, 'score': None},
                          {'start': 2.0, 'end': 3.5, 'score': 33.1},
                          {'start': 3.5, 'end': 5.5, 'score': 26.4}], found)
        for before, after in zip(found, found[1:]):
            self.assertEqual(before['end'], after['start'])

    def test_a_video_without_a_cut_is_one_shot(self):
        self.assertEqual([{'start': 0.0, 'end': 4.0, 'score': None}],
                         shots.shots_from_cuts([], 4.0))

    def test_a_shot_too_short_joins_its_neighbour(self):
        cuts = [(0.2, 50.0), (2.0, 40.0), (2.3, 30.0), (5.8, 30.0), (9.0, 20.0)]
        found = shots.shots_from_cuts(cuts, 6.0, min_duration=0.5)
        self.assertEqual([(0.0, 2.0), (2.0, 6.0)], [(s['start'], s['end']) for s in found])
        # De deux coupes proches (un fondu dit en deux fois), la plus forte dit où le plan change.
        found = shots.shots_from_cuts([(2.0, 40.0), (2.3, 60.0), (2.6, 50.0), (4.0, 9.0)], 6.0)
        self.assertEqual([(0.0, 2.3, None), (2.3, 4.0, 60.0), (4.0, 6.0, 9.0)],
                         [(s['start'], s['end'], s['score']) for s in found])
        every = shots.shots_from_cuts(cuts, 6.0, min_duration=0)
        self.assertEqual(5, len(every), 'the cut past the end is never a shot')


class DetectShotsTest(SimpleTestCase):
    """The real analysis, on a real video with two hard cuts (the picture inverted for a second)."""

    def test_the_cuts_of_a_real_video_are_found_where_they_are(self):
        import tempfile

        from wama.common.utils.ffmpeg_utils import test_pattern_video
        with tempfile.TemporaryDirectory() as folder:
            video = test_pattern_video(f'{folder}/cuts.mp4', size='160x120', seconds=3,
                                       video_filter="negate=enable='between(t,1,1.99)'")
            found = shots.detect_shots(video)
            self.assertEqual([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
                             [(s['start'], s['end']) for s in found])
            self.assertIsNone(found[0]['score'])
            self.assertTrue(all(s['score'] > shots.THRESHOLD for s in found[1:]))
            self.assertEqual(1, len(shots.detect_shots(video, threshold=100)),
                             'the threshold asked is the one ffmpeg applies')
            self.assertEqual(1, len(shots.detect_shots(video, min_duration=1.5)))
            still = test_pattern_video(f'{folder}/still.mp4', size='160x120', seconds=2)
            self.assertEqual([(0.0, 2.0)], [(s['start'], s['end'])
                                            for s in shots.detect_shots(still)])
            with open(f'{folder}/empty.mp4', 'wb'):
                pass
            with self.assertRaises(ValueError):
                shots.detect_shots(f'{folder}/empty.mp4')


class ShotsRunThroughTheStudioDoorTest(TestCase):
    """The function LAUNCHED as a node of the Studio launches it (`_run_app_function` : the file
    of its upstream by its port, the settings of the node, the caller) — on a real video, in a
    media root of its own. What it stores is what any card that uses the video then reads."""

    def test_the_node_stores_the_shots_and_says_them_and_other_settings_replace_them(self):
        import os
        import shutil
        import tempfile

        from django.core.cache import cache
        from django.test import override_settings

        from wama.common.catalog import function_catalog as fc
        from wama.common.services.process_pipeline import process_of_function
        from wama.common.utils import media_marks
        from wama.common.utils.ffmpeg_utils import test_pattern_video
        from wama.converter.functions import SHOTS, SHOTS_FUNCTION
        from wama.studio.tasks import _run_app_function

        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        rel = 'users/7/converter/input/cuts.mp4'
        os.makedirs(os.path.dirname(os.path.join(root, rel)))
        test_pattern_video(os.path.join(root, rel), size='160x120', seconds=3,
                           video_filter="negate=enable='between(t,1,1.99)'")
        spec = fc.get(SHOTS_FUNCTION)
        self.assertEqual((None, None), process_of_function(SHOTS_FUNCTION),
                         'a function of the file, not a step of the card')
        with override_settings(MEDIA_ROOT=root):
            cache.clear()
            said = _run_app_function(spec, {'user_id': 7}, lambda **kw: None, 60,
                                     inputs={'video': rel})
            self.assertEqual('Plans — 3 sur 0:03', said)
            found = media_marks.read_media_tracks(rel)[SHOTS]
            self.assertEqual([(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)],
                             [(s['start'], s['end']) for s in found])
            self.assertEqual({SHOTS}, {s['origin'] for s in found})
            said = _run_app_function(spec, {'min_duration': 1.5, 'user_id': 7},
                                     lambda **kw: None, 60, inputs={'video': rel})
            self.assertEqual('Plans — 1 sur 0:03', said)
            state = media_marks.marks_state(rel, schedule=False)[SHOTS]
            self.assertEqual(('ready', 1, {'min_duration': 1.5}),
                             (state['status'], state['count'], state['params']))
            with self.assertRaisesRegex(ValueError, 'plans'):
                _run_app_function(spec, {'user_id': 7}, lambda **kw: None, 60,
                                  inputs={'video': 'users/7/converter/input/nothing.mp4'})
