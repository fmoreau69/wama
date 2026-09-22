"""La porte `speaker_wav_for` (common/tts/voice_refs) — marche 2 du plan voix
(`MEDIA_STORAGE_TIERING §9.4`) : c'est la CAPACITÉ du moteur qui décide d'un `speaker_wav`,
et les deux workers ne font plus que l'appeler.
"""
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

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


class LesDeuxModelesLibellentParLaBriqueTest(TestCase):
    """`voice_preset` n'a plus de `choices` (décision Fabien 13/09) : Django ne génère plus
    `get_voice_preset_display`, les deux modèles le portent EXPLICITEMENT et délèguent à
    `describe_voice` — une valeur `sa_`/`ua_` inconnue de l'ancienne liste se libelle quand même."""

    def test_synthesizer_et_avatarizer_delegue_a_describe_voice(self):
        from unittest.mock import patch
        from django.contrib.auth import get_user_model
        from wama.avatarizer.models import AvatarJob
        from wama.synthesizer.models import VoiceSynthesis
        u = get_user_model().objects.create_user('libelle_voix', password='x')
        for modele in (VoiceSynthesis, AvatarJob):
            self.assertFalse(modele._meta.get_field('voice_preset').choices,
                             f'{modele.__name__}.voice_preset porte encore des choices')
            obj = modele(voice_preset='sa_42', user=u)
            with patch.object(voice_refs, 'describe_voice', return_value='Français — Adulte — Homme 1') as d:
                self.assertEqual(obj.get_voice_preset_display(), 'Français — Adulte — Homme 1')
            self.assertEqual(d.call_args[0][0], 'sa_42')


class PredicatDeClonageServeurTest(TestCase):
    def test_ua_et_cv_sont_des_clonages_sa_et_les_plats_non(self):
        self.assertTrue(voice_refs.is_cloned_voice('ua_3'))
        self.assertTrue(voice_refs.is_cloned_voice('cv_1'))
        for v in ('sa_12', 'default', 'female_1', 'bark_v2_fr_0', '', None):
            self.assertFalse(voice_refs.is_cloned_voice(v), v)


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


# ─────────────────────────────────────────────────────────────────────────────────────────
# Marche 4 — les voix VIVENT en médiathèque (`SystemAsset(voice)` + attributs A′)
# ─────────────────────────────────────────────────────────────────────────────────────────

def _wav(name):
    """Un WAV valide (0,1 s de silence, 16 kHz mono) — `ingest_voice_file` en lit la durée."""
    import io
    import struct
    import wave
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(struct.pack('<' + 'h' * 1600, *([0] * 1600)))
    from django.core.files.base import ContentFile
    return ContentFile(buf.getvalue(), name=name)


class AttributsDepuisLIdentifiantTest(TestCase):
    def test_un_id_de_taxonomie_porte_langue_age_genre_variante(self):
        self.assertEqual(voice_refs.attributes_from_voice_id('french/adult/male_adult_1_fr'),
                         {'language': 'fr', 'age': 'adult', 'gender': 'male', 'variant': 1})
        self.assertEqual(voice_refs.attributes_from_voice_id('english/child/female_child_en'),
                         {'language': 'en', 'age': 'child', 'gender': 'female'})

    def test_la_langue_vient_du_suffixe_pas_du_dossier(self):
        self.assertEqual(voice_refs.attributes_from_voice_id('bidon/adult/male_adult_2_pt')['language'], 'pt')

    def test_un_preset_plat_herite_ne_porte_que_la_langue(self):
        """Volontaire : avec âge+genre, `default` entrerait dans les groupes du menu — il n'y a
        jamais figuré (empreinte d'avant)."""
        self.assertEqual(voice_refs.attributes_from_voice_id('default'), {'language': 'en'})
        self.assertEqual(voice_refs.attributes_from_voice_id('male_1'), {'language': 'en'})
        self.assertEqual(voice_refs.attributes_from_voice_id('inconnu'), {})
        self.assertEqual(voice_refs.attributes_from_voice_id('a/b'), {})


class LaMediathequePorteLesVoixTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.voix = {}
        for name in ('french/adult/male_adult_1_fr', 'french/adult/female_adult_1_fr',
                     'french/adult/female_adult_2_fr', 'english/child/male_child_en',
                     'german/adult/female_adult_1_de', 'default', 'male_1'):
            cls.voix[name] = voice_refs.ingest_voice_file(name, cls._temp_wav(name))

    @classmethod
    def _temp_wav(cls, name):
        import tempfile
        p = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        p.write(_wav(name).read()); p.close()
        return p.name

    def test_ingest_pose_les_attributs_la_duree_et_le_domicile_systeme(self):
        v = self.voix['french/adult/male_adult_1_fr']
        v.refresh_from_db()
        self.assertEqual(v.attributes, {'language': 'fr', 'age': 'adult', 'gender': 'male', 'variant': 1})
        self.assertAlmostEqual(v.duration, 0.1, places=2)
        self.assertTrue(v.file.name.startswith('media_library/system/'), v.file.name)
        self.assertEqual(v.mime_type, 'audio/wav')

    def test_ingest_est_idempotent(self):
        avant = self.voix['default'].pk
        again = voice_refs.ingest_voice_file('default', self._temp_wav('default'))
        self.assertEqual(again.pk, avant)
        from wama.media_library.models import SystemAsset
        self.assertEqual(SystemAsset.objects.filter(asset_type='voice', name='default').count(), 1)

    def test_les_groupes_derivent_des_attributs_dans_l_ordre_du_scan_d_avant(self):
        g = voice_refs.voice_reference_groups()
        self.assertEqual([x['group'] for x in g],
                         ['Français — Adulte', 'English — Enfant', 'Deutsch — Adulte'])
        fr = g[0]['voices']
        self.assertEqual([v['label'] for v in fr], ['Femme 1', 'Femme 2', 'Homme 1'])
        self.assertTrue(all(v['id'].startswith('sa_') for v in fr))
        # les presets plats (sans genre) restent HORS des groupes, comme avant
        ids = {v['id'] for x in g for v in x['voices']}
        self.assertNotIn(f"sa_{self.voix['male_1'].pk}", ids)

    def test_resolution_par_sa_par_nom_d_avant_et_repli_default(self):
        v = self.voix['french/adult/female_adult_2_fr']
        chemin = v.file.path
        self.assertEqual(voice_refs.resolve_speaker_wav(f'sa_{v.pk}'), chemin)
        self.assertEqual(voice_refs.resolve_speaker_wav('french/adult/female_adult_2_fr'), chemin)
        self.assertEqual(voice_refs.resolve_speaker_wav('male_1'), self.voix['male_1'].file.path)
        defaut = self.voix['default'].file.path
        self.assertEqual(voice_refs.resolve_speaker_wav(''), defaut)
        self.assertEqual(voice_refs.resolve_speaker_wav('inconnu_total'), defaut)
        self.assertEqual(voice_refs.resolve_speaker_wav('sa_999999'), defaut)
        self.assertEqual(voice_refs.resolve_speaker_wav('ua_999999'), defaut)
        self.assertIsNone(voice_refs.resolve_speaker_wav('bark_v2_en_0'))

    def test_une_voix_inactive_ne_resout_plus(self):
        v = self.voix['german/adult/female_adult_1_de']
        v.is_active = False
        v.save()
        self.assertEqual(voice_refs.resolve_speaker_wav(f'sa_{v.pk}'), self.voix['default'].file.path)
        self.assertNotIn('Deutsch — Adulte', [x['group'] for x in voice_refs.voice_reference_groups()])

    def test_describe_voice_dans_toutes_ses_formes(self):
        v = self.voix['french/adult/male_adult_1_fr']
        self.assertEqual(voice_refs.describe_voice(f'sa_{v.pk}'), 'Français — Adulte — Homme 1')
        self.assertEqual(voice_refs.describe_voice('french/adult/male_adult_1_fr'), 'Français — Adulte — Homme 1')
        self.assertEqual(voice_refs.describe_voice('english/elderly/female_elderly_en'),
                         'English — Senior — Femme')            # ligne absente : l'id parle encore
        self.assertEqual(voice_refs.describe_voice('default'), 'Voix par défaut')
        self.assertEqual(voice_refs.describe_voice('bark_v2_fr_0'), 'Bark FR Speaker 0')
        self.assertEqual(voice_refs.describe_voice('ua_999999'), 'ua_999999')
        self.assertEqual(voice_refs.describe_voice(''), '')

    def test_needs_voice_download_compare_le_catalogue_a_la_mediatheque(self):
        self.assertTrue(voice_refs.needs_voice_download())       # 7 voix sur les 27 du catalogue
        with patch.object(voice_refs, '_catalogue_names', return_value={'default', 'male_1'}):
            self.assertFalse(voice_refs.needs_voice_download())

    def test_get_voice_groups_ne_propose_plus_de_repli_heritage(self):
        from wama.common.utils.voice_options import get_voice_groups
        groupes = [g['group'] for g in get_voice_groups(user=None)]
        self.assertNotIn('Voix intégrées (héritage)', groupes)
        self.assertIn('Français — Adulte', groupes)

    def test_chaque_voix_de_reference_porte_sa_langue_pour_les_filtres(self):
        """Marche 6 : `language` sur la voix, `attributes` par valeur dans les groupes servis
        (→ `data-language` sur l'option), les options restant des PAIRES."""
        from wama.common.utils.voice_options import get_voice_groups, voice_display_options
        g = voice_refs.voice_reference_groups()
        self.assertTrue(all(v['language'] for x in g for v in x['voices']))
        fr = next(x for x in get_voice_groups(user=None) if x['group'] == 'Français — Adulte')
        self.assertEqual(len(fr['options'][0]), 2)
        self.assertEqual(fr['attributes'][fr['options'][0][0]], {'language': 'fr'})
        # le lecteur « paires » ne voit rien de neuf
        self.assertTrue(all(len(p) == 2 for p in voice_display_options(user=None)))


class SharedVoiceAccessTest(TestCase):
    """« Une voix partagée doit être accessible en fonction des droits de chacun » (Fabien,
    2026-09-21).

    Ce qui se garde ici n'est PAS l'affichage : c'est que le sélecteur et la résolution lisent
    les MÊMES droits. Les ouvrir séparément aurait produit le pire des retours — le sélecteur
    propose la voix d'un collègue, la résolution la refuse et replie sur `default`, et la
    synthèse sort avec la mauvaise voix SANS message d'erreur.

    ⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User
        from wama.common.models import OrgUnit

        cls.owner = User.objects.create_user('voice_owner', password='x')
        cls.other = User.objects.create_user('voice_colleague', password='x')
        cls.lab = OrgUnit.objects.create(code='LESCOT_V', name='Lescot', unit_type='labo')
        for u in (cls.owner, cls.other):
            profile = u.profile
            profile.org_entity_code = 'LESCOT_V'
            profile.save(update_fields=['org_entity_code'])
        cls.default_voice = voice_refs.ingest_voice_file(
            'default', LaMediathequePorteLesVoixTest._temp_wav('default'))

    def _voice(self, user, name, visibility):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from wama.media_library.models import UserAsset

        return UserAsset.objects.create(
            user=user, name=name, asset_type='voice',
            file=SimpleUploadedFile(f'{name}.wav', b'RIFF....WAVEfmt '),
            visibility=visibility, scope_org_unit=self.lab if visibility == 'unit' else None,
        )

    def _group_labels(self, user):
        from wama.common.utils.voice_options import get_voice_groups
        return [g['group'] for g in get_voice_groups(user)]

    def _options(self, user, group):
        from wama.common.utils.voice_options import get_voice_groups
        for g in get_voice_groups(user):
            if g['group'] == group:
                return g['options']
        return []

    # ── LE test décisif : proposé ET résolu, par la même lecture de droits ──────────────
    def test_a_voice_shared_with_the_unit_is_both_offered_and_resolved(self):
        voice = self._voice(self.owner, 'lab_shared_voice', 'unit')

        offered = dict(self._options(self.other, 'Voix partagées'))
        self.assertIn(f'ua_{voice.pk}', offered)
        self.assertIn('voice_owner', offered[f'ua_{voice.pk}'],
                      "une voix d'autrui doit dire DE QUI elle est")

        self.assertEqual(voice.file.path,
                         voice_refs.resolve_speaker_wav(f'ua_{voice.pk}', user=self.other),
                         "proposer une voix que la résolution refuse replierait sur `default` "
                         "SANS message — la synthèse sortirait avec la mauvaise voix")

    def test_a_private_voice_of_someone_else_is_neither_offered_nor_resolved(self):
        voice = self._voice(self.owner, 'private_voice', 'private')
        self.assertNotIn('Voix partagées', self._group_labels(self.other))
        self.assertEqual(self.default_voice.file.path,
                         voice_refs.resolve_speaker_wav(f'ua_{voice.pk}', user=self.other))

    def test_my_own_voices_stay_in_their_own_group(self):
        mine = self._voice(self.other, 'my_own_voice', 'private')
        self.assertIn(f'ua_{mine.pk}', dict(self._options(self.other, 'Mes voix (clonage)')))
        self.assertNotIn('Voix partagées', self._group_labels(self.other))

    def test_the_anonymous_service_account_never_inherits_public_voices(self):
        """⚠ Le compte anonyme est une VRAIE ligne `User` et `scoped_visible_q` pose
        `Q(visibility='public')` hors du test d'authentification."""
        from wama.accounts.views import get_or_create_anonymous_user

        voice = self._voice(self.owner, 'public_voice', 'public')
        anonymous = get_or_create_anonymous_user()
        self.assertNotIn('Voix partagées', self._group_labels(anonymous))
        self.assertEqual(self.default_voice.file.path,
                         voice_refs.resolve_speaker_wav(f'ua_{voice.pk}', user=anonymous))

    def test_the_selector_and_the_resolution_share_one_reader(self):
        """La garde de non-retour : si l'un des deux se remet à filtrer par propriétaire, il
        cessera de passer par cette brique — et les deux surfaces divergeront à nouveau."""
        import inspect

        from wama.common.utils import voice_options

        source = inspect.getsource(voice_options.get_voice_groups)
        self.assertIn('readable_voice_assets', source)
        self.assertNotIn('filter(user=user', source)
        self.assertIn('readable_voice_assets',
                      inspect.getsource(voice_refs.resolve_speaker_wav))


class VoiceAcquisitionTest(SimpleTestCase):
    """Le genre et l'âge qu'annonce le nom d'une voix sont des CONTRAINTES d'acquisition.

    Mesuré le 2026-09-21 (`MEDIA_STORAGE_TIERING §9.4bis`) : 12 voix sur 25 portaient le genre
    contraire à leur nom. Deux causes, chacune tenue ici : VoxPopuli était lu sans son champ
    `gender` ; les replis par URL remplissaient des créneaux d'un genre qu'ils n'avaient pas.
    Aucun test ne touche le réseau : la source est simulée à sa frontière.
    """

    def setUp(self):
        voice_refs._used_vp_speakers.clear()

    def _fake_datasets(self, items):
        import types
        module = types.ModuleType('datasets')
        module.load_dataset = lambda *a, **k: _FakeStream(items)
        module.Audio = lambda **k: None
        return module

    def test_voxpopuli_skips_clips_of_the_other_gender(self):
        import numpy as np
        items = [{'speaker_id': 'a', 'gender': 'male', 'audio': 'A'},
                 {'speaker_id': 'b', 'gender': 'female', 'audio': 'B'}]
        saved = []
        # L'instrument est écarté (None) : ce test isole le filtre sur l'ÉTIQUETTE de la source.
        with patch.dict('sys.modules', {'datasets': self._fake_datasets(items)}), \
                patch.object(voice_refs, '_measured_gender', return_value=None), \
                patch.object(voice_refs, '_decode_audio_item',
                             side_effect=lambda audio: (np.zeros(8 * 16000) + (audio == 'B'), 16000)), \
                patch.object(voice_refs, '_save_audio_array',
                             side_effect=lambda arr, sr, target: saved.append(int(arr[0])) or True):
            self.assertTrue(voice_refs._try_voxpopuli(Path('x.wav'), 'fr', gender='female'))
        self.assertEqual([1], saved, "le premier clip (masculin) ne doit pas remplir un créneau féminin")

    def test_a_clip_labelled_male_but_heard_female_is_skipped(self):
        """Le cas MESURÉ du 22/09 : deux clips étiquetés « male » par la source sonnaient à 262 et
        184 Hz. L'étiquette ne suffit plus ; la voix doit faire entendre le genre demandé."""
        import numpy as np
        items = [{'speaker_id': 'a', 'gender': 'male', 'audio': 'A'},
                 {'speaker_id': 'b', 'gender': 'male', 'audio': 'B'}]
        saved = []
        with patch.dict('sys.modules', {'datasets': self._fake_datasets(items)}), \
                patch.object(voice_refs, '_decode_audio_item',
                             side_effect=lambda audio: (np.zeros(8 * 16000) + (audio == 'B'), 16000)), \
                patch.object(voice_refs, '_measured_gender',
                             side_effect=lambda arr, sr: 'male' if arr[0] else 'female'), \
                patch.object(voice_refs, '_save_audio_array',
                             side_effect=lambda arr, sr, target: saved.append(int(arr[0])) or True):
            self.assertTrue(voice_refs._try_voxpopuli(Path('x.wav'), 'fr', gender='male'))
        self.assertEqual([1], saved, "un clip qui sonne féminin ne remplit pas un créneau masculin")

    def test_a_clip_already_held_by_another_voice_is_skipped(self):
        """Le cas MESURÉ du 22/09 : deux passages ont donné le même clip à `male_adult_1_en` et
        `male_adult_2_en`. Deux voix du menu ne sont jamais la même personne."""
        import hashlib
        import tempfile

        import numpy as np
        items = [{'speaker_id': 'a', 'gender': 'male', 'audio': 'A'},
                 {'speaker_id': 'b', 'gender': 'male', 'audio': 'B'}]
        taken = hashlib.sha256(b'clip-A').hexdigest()

        def write(arr, sr, target):
            Path(target).write_bytes(b'clip-B' if arr[0] else b'clip-A')
            return True

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'v.wav'
            with patch.dict('sys.modules', {'datasets': self._fake_datasets(items)}), \
                    patch.object(voice_refs, '_measured_gender', return_value='male'), \
                    patch.object(voice_refs, '_decode_audio_item',
                                 side_effect=lambda audio: (np.zeros(8 * 16000) + (audio == 'B'), 16000)), \
                    patch.object(voice_refs, '_save_audio_array', side_effect=write):
                self.assertTrue(voice_refs._try_voxpopuli(target, 'en', gender='male',
                                                          exclude_digests={taken}))
            self.assertEqual(b'clip-B', target.read_bytes())

    def test_measured_gender_hears_a_low_and_a_high_voice(self):
        """L'instrument lui-même, sur des voix de synthèse : grave, aiguë, et la zone grise DITE."""
        try:
            import librosa  # noqa: F401
            import numpy as np
        except ImportError:
            self.skipTest('librosa absent de ce venv')
        sr = 16000
        t = np.arange(3 * sr) / sr

        def tone(hz):
            return 0.5 * np.sin(2 * np.pi * hz * t)

        self.assertEqual('male', voice_refs._measured_gender(tone(120), sr))
        self.assertEqual('female', voice_refs._measured_gender(tone(240), sr))
        self.assertEqual('', voice_refs._measured_gender(tone(165), sr), "zone grise : non tranchée")

    def test_voxpopuli_without_a_gender_constraint_behaves_as_before(self):
        """Contre-épreuve : sans genre demandé (`default`, presets plats), le premier clip gagne."""
        import numpy as np
        items = [{'speaker_id': 'a', 'gender': 'male', 'audio': 'A'}]
        with patch.dict('sys.modules', {'datasets': self._fake_datasets(items)}), \
                patch.object(voice_refs, '_decode_audio_item', return_value=(np.zeros(8 * 16000), 16000)), \
                patch.object(voice_refs, '_save_audio_array', return_value=True):
            self.assertTrue(voice_refs._try_voxpopuli(Path('x.wav'), 'fr'))

    def test_url_sources_carry_their_established_gender(self):
        lj = voice_refs.VOICE_DOWNLOAD_CATALOG['english/adult/female_adult_1_en'][0][0]
        fr = voice_refs.VOICE_DOWNLOAD_CATALOG['french/adult/male_adult_1_fr'][0][0]
        en = voice_refs.VOICE_DOWNLOAD_CATALOG['english/adult/male_adult_1_en'][0][0]
        self.assertEqual('female', voice_refs._url_source_gender(lj))
        self.assertEqual('male', voice_refs._url_source_gender(fr))
        self.assertEqual('', voice_refs._url_source_gender(en), "jamais téléchargé : genre non établi")

    def _download(self, name, voxpopuli_ok=False):
        with patch.object(voice_refs, '_library_voice_names', return_value=set()), \
                patch.object(voice_refs, '_library_voice_digests', return_value=set()), \
                patch.object(voice_refs, '_try_voxpopuli', return_value=voxpopuli_ok) as vp, \
                patch.object(voice_refs, '_try_url_download', return_value=True) as url, \
                patch.object(voice_refs, 'ingest_voice_file') as ingest:
            results = voice_refs.download_missing_voice_refs(force=True, names=[name])
        return results, vp, url, ingest

    def test_a_male_english_slot_is_no_longer_filled_with_ljspeech(self):
        """Le cas mesuré : `male_adult_1_en` sonnait à 202 Hz, c'était LJSpeech."""
        results, _, url, ingest = self._download('english/adult/male_adult_1_en')
        self.assertEqual({'english/adult/male_adult_1_en': 'failed'}, results)
        url.assert_not_called()
        ingest.assert_not_called()

    def test_female_french_slots_no_longer_receive_the_male_sample(self):
        """Le cas mesuré : un seul fichier (133 Hz, masculin) portait trois noms dont deux féminins."""
        for name in ('french/adult/female_adult_1_fr', 'french/adult/female_adult_2_fr'):
            results, _, url, _ = self._download(name)
            self.assertEqual('failed', results[name])
            url.assert_not_called()

    def test_a_slot_whose_source_gender_matches_is_still_filled(self):
        """Contre-épreuve : la porte se ferme sur le MENSONGE, pas sur la source."""
        results, _, url, ingest = self._download('german/adult/female_adult_1_de')
        self.assertEqual({'german/adult/female_adult_1_de': 'downloaded'}, results)
        url.assert_called_once()
        ingest.assert_called_once()

    def test_child_and_elderly_slots_are_never_fed_from_voxpopuli(self):
        """Débats du Parlement européen : des adultes. Un âge qu'aucune source ne documente ne
        s'invente plus."""
        for name in ('french/child/female_child_fr', 'english/elderly/male_elderly_en'):
            results, vp, _, _ = self._download(name, voxpopuli_ok=True)
            self.assertEqual('failed', results[name])
            vp.assert_not_called()

    def test_names_restricts_the_pass(self):
        results, _, _, _ = self._download('german/adult/female_adult_1_de')
        self.assertEqual(['german/adult/female_adult_1_de'], list(results))

    def test_the_command_rejects_an_unknown_name_instead_of_ignoring_it(self):
        import io
        from django.core.management import call_command
        err = io.StringIO()
        with patch('wama.synthesizer.management.commands.download_voice_refs.'
                   'download_missing_voice_refs') as download:
            call_command('download_voice_refs', '--names', 'french/adult/typo_fr', stderr=err)
        download.assert_not_called()
        self.assertIn('absentes du catalogue', err.getvalue())


class _FakeStream:
    """Un flux de jeu de données minimal : itérable, et `cast_column` sans effet."""

    def __init__(self, items):
        self.items = items

    def cast_column(self, *args, **kwargs):
        return self

    def __iter__(self):
        return iter(self.items)


class VoiceReplacementTest(TestCase):
    """Remplacer une voix, c'est aussi retirer son ancien fichier — et jamais un fichier encore
    référencé ailleurs. Mesuré le 2026-09-22 : trois passages de retéléchargement avaient laissé
    14 WAV orphelins. Le runner donne à chaque exécution un MEDIA_ROOT jetable."""

    def _wav(self, tag):
        import tempfile
        handle = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        handle.write(_wav(tag).read())
        handle.close()
        return handle.name

    def test_replacing_a_voice_removes_its_old_file(self):
        first = voice_refs.ingest_voice_file('english/adult/male_adult_9_en', self._wav('a'))
        old_path = Path(first.file.path)
        self.assertTrue(old_path.is_file())
        second = voice_refs.ingest_voice_file('english/adult/male_adult_9_en', self._wav('b'),
                                              replace=True)
        self.assertEqual(first.pk, second.pk)
        self.assertTrue(Path(second.file.path).is_file())
        self.assertFalse(old_path.exists(), "l'ancien fichier est resté : un orphelin de plus")

    def test_a_replaced_voice_keeps_its_clean_file_name(self):
        """Constat du 22/09 : un remplacement laissait `male_adult_1_en_HtZSn0F.wav` — le nouveau
        fichier s'écrit pendant que l'ancien existe, Django suffixe. Le nom propre est repris."""
        import tempfile
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = Path(a) / 'male_adult_7_en.wav', Path(b) / 'male_adult_7_en.wav'
            first.write_bytes(b'first-take')
            second.write_bytes(b'second-take')
            voice_refs.ingest_voice_file('english/adult/male_adult_7_en', first)
            asset = voice_refs.ingest_voice_file('english/adult/male_adult_7_en', second,
                                                 replace=True)
        asset.refresh_from_db()
        self.assertEqual('male_adult_7_en.wav', Path(asset.file.name).name)
        self.assertEqual(b'second-take', Path(asset.file.path).read_bytes())

    def test_an_old_file_still_referenced_elsewhere_is_kept(self):
        """Contre-épreuve : la brique commune protège un fichier PARTAGÉ."""
        from wama.media_library.models import SystemAsset
        first = voice_refs.ingest_voice_file('english/adult/male_adult_8_en', self._wav('c'))
        old_path = Path(first.file.path)
        SystemAsset.objects.create(name='alias_of_the_same_file', asset_type='voice',
                                   file=first.file.name)
        voice_refs.ingest_voice_file('english/adult/male_adult_8_en', self._wav('d'), replace=True)
        self.assertTrue(old_path.is_file(), "un fichier encore référencé ne s'efface jamais")


class DownloadCommandExitTest(SimpleTestCase):
    """`download_voice_refs` sort SANS la destruction native qui plantait (sortie 139/134 après
    un travail réussi, 22/09) — mais seulement en ligne de commande : sortir du processus depuis
    `call_command` tuerait les tests et tout autre appelant."""

    CMD = 'wama.synthesizer.management.commands.download_voice_refs'

    def test_the_helper_flushes_then_exits_with_the_given_code(self):
        from wama.synthesizer.management.commands import download_voice_refs as cmd
        with patch.object(cmd.os, '_exit') as hard_exit, \
                patch.object(cmd.logging, 'shutdown') as log_shutdown:
            cmd.exit_skipping_native_teardown(1)
        log_shutdown.assert_called_once()
        hard_exit.assert_called_once_with(1)

    def test_call_command_never_leaves_the_process(self):
        from django.core.management import call_command
        with patch(self.CMD + '.download_missing_voice_refs', return_value={'default': 'skipped'}), \
                patch(self.CMD + '.exit_skipping_native_teardown') as leave:
            call_command('download_voice_refs', '--names', 'default')
        leave.assert_not_called()

    def test_from_the_command_line_the_exit_code_tells_the_truth(self):
        from wama.synthesizer.management.commands.download_voice_refs import Command
        for results, code in (({'default': 'downloaded'}, 0), ({'default': 'failed'}, 1)):
            command = Command()
            command._called_from_command_line = True
            with patch(self.CMD + '.download_missing_voice_refs', return_value=results), \
                    patch(self.CMD + '.exit_skipping_native_teardown') as leave:
                command.handle(force=False, names=['default'])
            leave.assert_called_once_with(code)


class VoiceGroupKeysTest(TestCase):
    """Chaque groupe de voix porte une CLÉ stable, et « Mes voix » est toujours émis.

    La clé devient `data-group-key` sur l'`<optgroup>` (WamaParams, 22/09) : c'est par elle
    qu'un JS d'app retrouve un groupe, plus par un `id` écrit à la main dans un gabarit.
    """

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user('voice_groups_user', password='x')

    def _groups(self):
        from wama.common.utils.voice_options import get_voice_groups
        return get_voice_groups(self.user)

    def test_every_group_carries_a_stable_key(self):
        keys = [g.get('key') for g in self._groups()]
        self.assertNotIn(None, keys, "un groupe sans clé est introuvable pour le JS d'app")
        self.assertEqual(['default', 'mine', 'bark'], [k for k in keys if k != 'reference'])

    def test_the_own_voices_group_is_emitted_even_when_empty(self):
        """Sans voix clonée, le groupe doit EXISTER : son absence ferait recréer par le JS un
        groupe au libellé et à la place différents (mesuré le 22/09)."""
        groups = {g['key']: g for g in self._groups()}
        self.assertIn('mine', groups)
        self.assertEqual([], groups['mine']['options'])
        self.assertNotIn('shared', groups, "un groupe de voix partagées vide ne se montre pas")
