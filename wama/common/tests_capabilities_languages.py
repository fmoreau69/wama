"""
Invariants des chantiers « capacités de moteur » et « langues de l'assistant » (2026-08-20/21).

POURQUOI VERSIONNÉ. Ces invariants ont d'abord été vérifiés par des suites de session écrites
dans le scratchpad (~190 contrôles). Le crash hôte du 21/08 a vidé ce dossier : elles ont validé
le travail sur le moment, puis ont cessé d'exister — le code était commité, les tests non.
Un test qui ne survit pas à la session ne protège rien, il rassure son auteur. Même constat, le
même jour, sur la brique mémoire (`tests_memory.py`) : la leçon est prise deux fois.

Convention du dépôt : `TestCase` Django, base de TEST — aucune dépendance aux données réelles,
et aucun risque pour elles (les suites de session, elles, modifiaient le profil du compte vif
pour le restaurer ensuite : ça marchait, mais ça n'aurait pas dû être la norme).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.backends.base import BaseModelBackend
from wama.common.services.assistant_engine import WAMA_SYSTEM_PROMPT, _language_instruction
from wama.common.tts.constants import KOKORO_LANG_MAP, KOKORO_VOICE_MAP, LANGUAGE_NAMES_EN
from wama.common.tts.voices import (
    choix_voix, code_langue, est_repli, langue_de_voix, voix_pour,
)
from wama.common.utils.model_capabilities import (
    CANONICAL_CAPABILITIES, is_canonical_key, supports_timestamps_for,
)

User = get_user_model()


class ContratCapacitesTest(TestCase):
    """Les `supports_*` vivent au contrat COMMUN — pas dans un contrat métier."""

    FLAGS = ('supports_diarization', 'supports_timestamps', 'supports_hotwords',
             'supports_streaming', 'supports_cloning')

    def test_contrat_commun_porte_les_flags(self):
        for flag in self.FLAGS:
            self.assertIs(getattr(BaseModelBackend, flag), False,
                          f"{flag} doit exister au contrat commun, défaut False")
        self.assertIsNone(BaseModelBackend.timestamp_languages)

    def test_stt_herite_sans_redeclarer(self):
        """Le contrat STT ne doit PAS re-poser les flags : ce serait rouvrir la divergence."""
        from wama.transcriber.backends.base import SpeechToTextBackend
        for flag in self.FLAGS:
            self.assertNotIn(flag, SpeechToTextBackend.__dict__,
                             f"{flag} redéclaré dans SpeechToTextBackend — doit être hérité")

    def test_moteurs_asr_conservent_leurs_capacites(self):
        from wama.transcriber.backends.qwen_asr_backend import QwenASRBackend
        from wama.transcriber.backends.vibevoice_backend import VibeVoiceBackend
        from wama.transcriber.backends.whisper_backend import WhisperBackend
        self.assertTrue(WhisperBackend.supports_timestamps)
        self.assertTrue(WhisperBackend.supports_hotwords)
        self.assertFalse(WhisperBackend.supports_diarization)   # pyannote = post-traitement
        self.assertTrue(VibeVoiceBackend.supports_diarization)  # native, elle
        self.assertTrue(QwenASRBackend.supports_timestamps)

    def test_tts_declarent_leur_clonage(self):
        from wama.synthesizer.backends.bark_backend import BarkBackend
        from wama.synthesizer.backends.coqui_backend import CoquiBackend
        from wama.synthesizer.backends.higgs_backend import HiggsAudioBackend
        from wama.synthesizer.backends.kokoro_backend import KokoroBackend
        self.assertTrue(CoquiBackend.supports_cloning)
        self.assertTrue(HiggsAudioBackend.supports_cloning)
        self.assertFalse(BarkBackend.supports_cloning)
        self.assertFalse(KokoroBackend.supports_cloning)


class BorneLangueTest(TestCase):
    """`timestamp_languages` : une capacité peut être restreinte à certaines langues."""

    def test_cle_canonique(self):
        self.assertTrue(is_canonical_key('timestamp_languages'))
        self.assertIn('timestamp_languages', CANONICAL_CAPABILITIES)

    def test_borne_derivee_du_mapping_pas_ecrite_a_la_main(self):
        """Les 8 langues rabattues sur le pipeline anglais DOIVENT être couvertes.

        Une liste manuelle aurait dit ['en'] et se serait trompée sur 8 langues.
        """
        from wama.synthesizer.backends.kokoro_backend import KokoroBackend
        attendu = sorted(l for l, c in KOKORO_LANG_MAP.items() if c in ('a', 'b'))
        self.assertEqual(sorted(KokoroBackend.timestamp_languages), attendu)
        self.assertIn('en', KokoroBackend.timestamp_languages)
        self.assertIn('de', KokoroBackend.timestamp_languages)   # repli anglais
        self.assertNotIn('fr', KokoroBackend.timestamp_languages)  # pipeline propre 'f'

    def test_helper_respecte_la_borne(self):
        kokoro = {'supports_timestamps': True, 'timestamp_languages': ['en']}
        self.assertTrue(supports_timestamps_for(kokoro, 'en'))
        self.assertFalse(supports_timestamps_for(kokoro, 'fr'))
        # Borne absente = toutes les langues (rétrocompatible).
        self.assertTrue(supports_timestamps_for({'supports_timestamps': True}, 'fr'))
        self.assertFalse(supports_timestamps_for({}, 'fr'))


class DeclarationLanguesTest(TestCase):
    """Les langues d'un moteur TTS se déclarent à UN seul endroit (réalignement 2026-08-29).

    Avant : la liste vivait dans `synthesizer/utils/model_config.py` **et** en dur dans
    `model_registry._discover_synthesizer_models`. Les deux avaient divergé sur 2 moteurs, et
    seule la copie du registre atteignait le catalogue — l'autre était donc fausse SANS
    CONSOMMATEUR pour s'en apercevoir. *Un doublon inerte vieillit en silence.* Ces invariants
    existent pour que la prochaine divergence soit ROUGE, pas invisible.
    """

    def _config(self):
        from wama.synthesizer.utils.model_config import SYNTHESIZER_MODELS
        return SYNTHESIZER_MODELS

    def test_tous_les_moteurs_declarent_leurs_langues(self):
        for key, spec in self._config().items():
            langues = spec.get('languages')
            self.assertTrue(langues, f"{key} ne déclare aucune langue")
            self.assertEqual(len(langues), len(set(langues)), f"{key} : doublon de langue")

    def test_la_decouverte_LIT_la_declaration_au_lieu_de_la_reecrire(self):
        """Le registre DÉCOUVRE, il ne redéclare pas — même geste que `hf_id`.

        Contrôle par le TEXTE de la découverte : une liste de codes ISO réécrite en dur y
        serait le retour de la divergence. On vérifie qu'aucun `languages=[...]` littéral n'y
        subsiste et que les 4 moteurs passent par `_synth_languages`.
        """
        import inspect

        from wama.model_manager.services.model_registry import ModelRegistry
        source = inspect.getsource(ModelRegistry._discover_synthesizer_models)
        for key in self._config():
            self.assertIn(f"_synth_languages('{key}')", source,
                          f"{key} : la découverte doit LIRE model_config, pas redéclarer")
        self.assertNotIn("languages=['en'", source)
        self.assertNotIn("'en', 'es', 'fr'", source)

    def test_bark_a_un_prompt_de_voix_pour_CHAQUE_langue_offerte(self):
        """Défaut mesuré le 29/08 : `nl`/`cs` étaient offertes et pointaient sur
        `v2/nl_speaker_0`/`v2/cs_speaker_0`, qui n'existent pas chez Suno. Une langue proposée
        sans prompt mène à un fichier absent — l'utilisateur essuie l'écart, pas le registre.
        """
        from wama.common.tts.constants import BARK_LANG_DEFAULTS
        declarees = set(self._config()['bark']['languages'])
        self.assertEqual(declarees, set(BARK_LANG_DEFAULTS),
                         'langues bark et prompts de voix désalignés')

    def test_kokoro_declare_ses_langues_PROPRES_pas_ses_replis(self):
        """`_LANGUES_PROPRES` (voices.py) et le catalogue disent le même ensemble."""
        from wama.common.tts.voices import _LANGUES_PROPRES
        self.assertEqual(set(self._config()['kokoro']['languages']),
                         set(_LANGUES_PROPRES))


class ReplideLangueTest(TestCase):
    """`fallback_languages` : la 3ᵉ valeur — ni gérée, ni refusée."""

    def test_cle_canonique(self):
        self.assertTrue(is_canonical_key('fallback_languages'))
        self.assertIn('fallback_languages', CANONICAL_CAPABILITIES)

    def test_defaut_du_contrat_commun_est_ABSENT(self):
        """Le repli est l'exception : un moteur qui n'en a pas ne déclare rien."""
        self.assertIsNone(BaseModelBackend.fallback_languages)

    def test_kokoro_derive_son_repli_du_mapping(self):
        from wama.synthesizer.backends.kokoro_backend import KokoroBackend
        attendu = sorted(l for l, c in KOKORO_LANG_MAP.items()
                         if c in ('a', 'b') and l != 'en')
        self.assertEqual(sorted(KokoroBackend.fallback_languages), attendu)
        self.assertIn('de', KokoroBackend.fallback_languages)
        self.assertNotIn('en', KokoroBackend.fallback_languages)  # l'anglais est PROPRE

    def test_repli_et_langues_gerees_sont_DISJOINTS(self):
        """Sans quoi le catalogue dirait d'une même langue qu'elle est servie ET empruntée —
        et l'UI la marquerait ⚠ tout en la déclarant native."""
        from wama.synthesizer.backends.kokoro_backend import KokoroBackend
        from wama.synthesizer.utils.model_config import SYNTHESIZER_MODELS
        gerees = set(SYNTHESIZER_MODELS['kokoro']['languages'])
        self.assertEqual(gerees & set(KokoroBackend.fallback_languages), set())

    def test_le_repli_couvre_ce_que_est_repli_annonce(self):
        """`est_repli()` existait pour « que l'UI puisse le DIRE » sans avoir de lecteur.
        Le lecteur est désormais `WamaModelCaps.langFilter` via cette capacité : les deux
        doivent parler du même ensemble."""
        from wama.synthesizer.backends.kokoro_backend import KokoroBackend
        for langue in KokoroBackend.fallback_languages:
            self.assertTrue(est_repli(langue), f"{langue} déclarée en repli mais non vue ainsi")


class ResolutionVoixTest(TestCase):
    """`common/tts/voices.py` remplace deux calculs qui vivaient en miroir."""

    def test_aller_couvre_toute_la_table(self):
        for langue in KOKORO_LANG_MAP:
            for masculin in (False, True):
                code = KOKORO_LANG_MAP[langue]
                attendu = (KOKORO_VOICE_MAP.get((code, masculin))
                           or KOKORO_VOICE_MAP.get((code, False), 'af_heart'))
                self.assertEqual(voix_pour(langue, masculin), attendu, langue)

    def test_retour_couvre_toutes_les_voix(self):
        """Cas limite mis au jour par ce test : le code `'b'` (anglais BRITANNIQUE) n'a
        AUCUN antécédent dans `KOKORO_LANG_MAP` — aucune langue WAMA ne s'y mappe, donc
        `voix_pour()` ne rend jamais `bf_emma`/`bm_george`. Mais `langue_de_voix()` peut en
        recevoir une (voix choisie à la main) : elle rend alors `'en'`, ce qui est juste —
        l'anglais britannique EST de l'anglais. L'aller-retour n'est donc pas l'identité sur
        ce code-là, et c'est voulu.
        """
        codes_atteignables = set(KOKORO_LANG_MAP.values())
        for voix in set(KOKORO_VOICE_MAP.values()):
            langue, masculin = langue_de_voix(voix)
            self.assertEqual(masculin, len(voix) > 1 and voix[1] == 'm')
            if voix[:1] in codes_atteignables:
                self.assertEqual(KOKORO_LANG_MAP.get(langue), voix[:1])
            else:
                self.assertEqual(langue, 'en', f"{voix} : repli anglais attendu")

    def test_langue_inconnue_retombe_sur_anglais(self):
        self.assertEqual(code_langue('xx'), 'a')

    def test_repli_visible(self):
        for langue in ('de', 'nl', 'pl', 'tr', 'ru', 'cs', 'ar', 'ko'):
            self.assertTrue(est_repli(langue), f"{langue} est rabattue sur l'anglais")
        for langue in ('fr', 'en', 'es', 'it', 'pt', 'ja', 'zh-cn'):
            self.assertFalse(est_repli(langue))

    def test_choix_voix_sans_doublon_preferee_en_tete(self):
        for pref in ('fr', 'en', 'ja'):
            choix = choix_voix(pref)
            valeurs = [c['valeur'] for c in choix]
            self.assertEqual(len(valeurs), len(set(valeurs)), 'doublon de voix')
            self.assertEqual(choix[0]['langue'], pref)
            self.assertTrue(choix[0]['preferee'])
        # Le sélecteur en dur qu'on a remplacé n'en proposait que 3.
        self.assertGreater(len(choix_voix('fr')), 3)


class LangueAssistantTest(TestCase):
    """La langue de réponse vient du PROFIL, plus du code."""

    def test_gabarit_sans_langue_en_dur(self):
        self.assertIn('{LANGUE}', WAMA_SYSTEM_PROMPT)
        self.assertNotIn('in French', WAMA_SYSTEM_PROMPT)

    def test_les_DEUX_prompts_portent_le_marqueur(self):
        """Piège : un `.replace` sur le seul prompt système laisserait `{LANGUE}` littéral
        dans le prompt d'outils — le LLM le recevrait tel quel."""
        from wama.common.services.assistant_engine import WAMA_TOOLS_PROMPT
        self.assertIn('{LANGUE}', WAMA_TOOLS_PROMPT)

    def test_sans_utilisateur_reste_le_comportement_historique(self):
        self.assertEqual(_language_instruction(None), 'French')

    def test_suit_le_profil(self):
        user = User.objects.create_user('sonde_langues', password='x')  # base de TEST
        for langue, attendu in (('fr', 'French'), ('en', 'English'), ('ja', 'Japanese')):
            user.profile.preferred_language = langue
            user.profile.save(update_fields=['preferred_language'])
            user.refresh_from_db()
            self.assertEqual(_language_instruction(user), attendu)
            rendu = WAMA_SYSTEM_PROMPT.replace('{LANGUE}', _language_instruction(user))
            self.assertNotIn('{LANGUE}', rendu)

    def test_zh_cn_resolu(self):
        """`zh-cn` est le code employé par WAMA ; la table ne connaissait que `zh`,
        et Higgs injectait donc « Zh-Cn » dans son prompt."""
        self.assertEqual(LANGUAGE_NAMES_EN.get('zh-cn'), 'Chinese')


class VendoringTest(TestCase):
    """Assets 3D : locaux, complets, et résolvables par le navigateur."""

    def test_importmap_est_locale_et_complete(self):
        from django.template.loader import render_to_string
        rendu = render_to_string('common/_three_importmap.html')
        self.assertIn('"three"', rendu)
        self.assertIn('"three/addons/"', rendu)
        self.assertIn('"talkinghead"', rendu)
        # Règle WAMA : aucun CDN au runtime.
        bloc = rendu.split('<script type="importmap">')[1].split('</script>')[0]
        self.assertNotIn('http://', bloc)
        self.assertNotIn('https://', bloc)

    def test_modules_requis_a_l_execution_presents(self):
        """`lipsync-<lang>.mjs` est chargé par un `import()` DYNAMIQUE : son absence ne casse
        pas le chargement mais la PREMIÈRE PHRASE PRONONCÉE."""
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR) / 'wama' / 'static' / 'vendors'
        for rel in ('three-0.180.0/build/three.module.js',
                    'three-0.180.0/addons/loaders/GLTFLoader.js',
                    'three-0.180.0/addons/libs/fflate.module.js',   # dépendance TRANSITIVE
                    'talkinghead-1.7/talkinghead.mjs',
                    'talkinghead-1.7/lipsync-fr.mjs',
                    'talkinghead-1.7/lipsync-en.mjs'):
            self.assertTrue((base / rel).exists(), f"{rel} manquant — relancer update_vendors.sh")
