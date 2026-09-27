"""
WAMA Synthesizer - Tests
"""

import os
import tempfile
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .models import VoiceSynthesis
from .utils.text_extractor import extract_text_from_file, clean_text_for_tts

User = get_user_model()


def _utilisateur_autorise(username='testuser'):
    """User de test AYANT le droit d'ouvrir le synthesizer.

    ⚠ Sans le rôle, les 8 tests de vues échouaient sur `302 != 200` — et ce message ne
    désigne PAS le coupable : ni l'URL, ni l'authentification. C'est
    `AppAccessMiddleware` (`wama/accounts/middleware.py`) qui, AVANT toute vue, interroge
    `accessible(user, 'synthesizer')` et redirige vers `home` quand c'est faux. La
    politique (`permissions.py`, `DEFAULT_APP_ACCESS`) exige le rôle `communication` pour
    cette app, et un `create_user` nu n'appartient à aucun groupe.

    Le rôle est donc accordé ICI, comme le fait `nightly_tests.get_test_user()` : un test
    de VUES doit FRANCHIR le portier, pas le contourner. Le neutraliser (superuser,
    `@override_settings` sans le middleware) rendrait ces tests aveugles à une régression
    du gating, qui est précisément un mécanisme transverse à surveiller.
    """
    from django.contrib.auth.models import Group
    from wama.accounts.permissions import GROUP_PREFIX
    user = User.objects.create_user(username=username, password='testpass123')
    group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')
    user.groups.add(group)
    return user


class VoiceSynthesisModelTest(TestCase):
    """Tests pour le modèle VoiceSynthesis."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

        # Créer un fichier texte temporaire
        self.text_content = "Ceci est un test de synthèse vocale."
        self.text_file = SimpleUploadedFile(
            "test.txt",
            self.text_content.encode('utf-8'),
            content_type="text/plain"
        )

    def test_create_synthesis(self):
        """Test de création d'une synthèse."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file,
            tts_model='coqui-xtts',
            language='fr'
        )

        self.assertEqual(synthesis.user, self.user)
        self.assertEqual(synthesis.status, 'PENDING')
        self.assertEqual(synthesis.tts_model, 'coqui-xtts')
        self.assertEqual(synthesis.language, 'fr')

    def test_filename_property(self):
        """Test de la propriété filename."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        self.assertIn('test.txt', synthesis.filename)

    def test_estimate_duration(self):
        """Test de l'estimation de durée."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        synthesis.text_content = "Ceci est un test " * 150  # 300 mots
        synthesis.word_count = 300
        synthesis.speed = 1.0

        duration = synthesis.estimate_duration()
        self.assertGreater(duration, 0)
        self.assertLess(duration, 300)  # Moins de 5 minutes

    def test_format_duration(self):
        """Test du formatage de durée."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        self.assertEqual(synthesis.format_duration(65), "1:05")
        self.assertEqual(synthesis.format_duration(120), "2:00")
        self.assertEqual(synthesis.format_duration(0), "0:00")

    def test_update_metadata(self):
        """Test de la mise à jour des métadonnées."""
        synthesis = VoiceSynthesis.objects.create(
            user=self.user,
            text_file=self.text_file
        )

        synthesis.text_content = "Ceci est un test de synthèse vocale."
        synthesis.update_metadata()

        self.assertEqual(synthesis.word_count, 7)
        self.assertGreater(synthesis.duration_seconds, 0)
        self.assertIsNotNone(synthesis.duration_display)


class TextExtractorTest(TestCase):
    """Tests pour l'extracteur de texte."""

    def test_extract_from_txt(self):
        """Test d'extraction depuis TXT."""
        # ⚠ lecture et suppression APRÈS le `with` : sous Windows un fichier encore ouvert
        # n'est ni relisible par un autre descripteur ni supprimable (PermissionError).
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test text content")
            chemin = f.name
        try:
            self.assertEqual(extract_text_from_file(chemin), "Test text content")
        finally:
            os.unlink(chemin)

    def test_clean_text_for_tts(self):
        """Test du nettoyage de texte."""
        dirty_text = "Test   with   spaces\n\n\nand http://example.com URLs"
        clean = clean_text_for_tts(dirty_text)

        self.assertNotIn("http://", clean)
        self.assertNotIn("   ", clean)


# `ViewsTest` RETIRÉ le 2026-09-26 : ses 7 tests (page, dépôt, extension refusée, ▶, progression,
# suppression, élément d'autrui) sont tenus pour TOUTES les apps par les contrats génériques
# (`common/tests_endpoints`, `tests_import_contract`, `tests_item_lifecycle_contract`,
# `tests_queue_delete_contract`) — `WAMA_VERIFICATION §8`.


class IntegrationTest(TestCase):
    """Tests d'intégration."""

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise()     # cf. ViewsTest.setUp
        self.client.force_login(self.user)

    def test_full_workflow(self):
        """Test du workflow complet."""
        # 1. Upload
        text_file = SimpleUploadedFile(
            "test.txt",
            b"Ceci est un test de synthese vocale.",
            content_type="text/plain"
        )

        response = self.client.post(
            reverse('synthesizer:upload'),
            {
                'file': text_file,
                'tts_model': 'kokoro',
                'language': 'fr',
                'speed': 1.0,
                'pitch': 1.0
            }
        )

        self.assertEqual(response.status_code, 200)
        synthesis_id = response.json()['id']

        # 2. Vérifier la synthèse créée
        synthesis = VoiceSynthesis.objects.get(id=synthesis_id)
        self.assertEqual(synthesis.status, 'PENDING')

        # 3. Démarrer (sans vraiment exécuter Celery en test)
        response = self.client.post(
            reverse('synthesizer:start', args=[synthesis_id])
        )
        self.assertEqual(response.status_code, 200)

        # 4. Vérifier le statut
        synthesis.refresh_from_db()
        self.assertEqual(synthesis.status, 'RUNNING')

        # 5. Simuler la complétion
        # ⚠ la progression a DEUX canaux : le cache (fil temps réel, lu EN PREMIER par
        # `views.progress`) et la colonne en base (repli). Écrire la seule colonne, comme
        # le faisait ce test, laissait le cache à 0 posé par `start` — la vue répondait
        # donc 0 alors que la base disait 100. Ce n'est pas un défaut de l'app : son
        # écrivain, `workers._set_progress`, tient les deux canaux ensemble. Le test
        # passe donc par LUI plutôt que de recopier la clé de cache ici (une clé recopiée
        # est une clé qui divergera).
        from wama.synthesizer.workers import _set_progress
        _set_progress(synthesis, 100)
        synthesis.status = 'SUCCESS'
        synthesis.save(update_fields=['status'])

        # 6. Vérifier la progression
        response = self.client.get(
            reverse('synthesizer:progress', args=[synthesis_id])
        )
        data = response.json()
        self.assertEqual(data['status'], 'SUCCESS')
        self.assertEqual(data['progress'], 100)


# `PerformanceTest` RETIRÉ le 2026-09-26 : il testait l'ORM de Django (bulk_create,
# select_related), pas un comportement de WAMA.


class ConfinementServerPathTest(TestCase):
    """🔴 Traversée de chemin refusée (2026-09-05, `MEDIA_STORAGE_TIERING §8.6` D1).

    `import_individual_from_path` faisait `Path(MEDIA_ROOT) / server_path` sans `resolve()`
    ni contrôle : un `../../…` lisait n'importe quel fichier du serveur et injectait son
    texte dans une card. La vue passe désormais par la brique commune de confinement —
    ce test franchit le portier (rôle `communication`) et exige le REFUS, jamais un 404
    qui laisserait croire que le chemin a simplement été cherché.
    """

    def setUp(self):
        self.user = _utilisateur_autorise('confinement')
        self.client = Client()
        self.client.login(username='confinement', password='testpass123')

    def test_un_server_path_qui_remonte_hors_de_media_est_refuse_403(self):
        # Un fichier qui EXISTE hors de MEDIA_ROOT : sans la garde, la vue le lirait.
        rep = self.client.post(reverse('synthesizer:import_individual_from_path'),
                               {'server_path': '../manage.py'})
        self.assertEqual(rep.status_code, 403, rep.content[:200])
        self.assertFalse(VoiceSynthesis.objects.filter(user=self.user).exists(),
                         'aucune card ne doit naître d\'un chemin refusé')

    def test_le_meme_refus_vaut_pour_le_lot_depuis_server_path(self):
        rep = self.client.post(reverse('synthesizer:batch_create'),
                               {'server_path': '../manage.py'})
        self.assertEqual(rep.status_code, 403, rep.content[:200])


class PanelVoiceFieldIsGeneratedTest(TestCase):
    """Le champ de voix du VOLET est GÉNÉRÉ du schéma depuis le 2026-09-23.

    Les quatre optgroups écrits dans le gabarit (défaut / références / « Mes voix » / Bark)
    redisaient à la main ce que `get_voice_groups` sert déjà à la modale d'item, à
    l'avatarizer et à l'endpoint commun — et cette copie-là ne savait pas dire les voix
    PARTAGÉES. Ce que ces gardes tiennent, c'est ce qui pouvait casser SANS lever :
      • le champ n'est plus dans le gabarit → un `<option>` réapparu y serait un retour en
        arrière muet (la page marcherait, avec deux inventaires qui divergent) ;
      • un select généré n'a pas de `name=` en contexte 'panel' → un lecteur qui n'interroge
        que `[name=]` cesse d'enregistrer la voix, sans erreur ni trace ;
      • le groupe « Mes voix » se retrouve par sa CLÉ, plus par un id de gabarit — sinon la
        voix qu'on vient de cloner atterrit dans un groupe recréé, ailleurs et autrement
        libellé.
    """

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise('panel_voice_user')
        self.client.force_login(self.user)

    def _page(self):
        return self.client.get(reverse('synthesizer:index')).content.decode('utf-8')

    def _template_source(self):
        from pathlib import Path
        from django.conf import settings
        return (Path(settings.BASE_DIR) / 'wama' / 'synthesizer' / 'templates' / 'synthesizer'
                / 'index.html').read_text(encoding='utf-8')

    def test_the_panel_carries_a_host_instead_of_hand_written_voice_options(self):
        page = self._page()
        self.assertIn('id="voicePresetHost"', page)
        self.assertIn('id="voicePresetGroup"', page,
                      'la zone enveloppe reste : Higgs la masque, voiceSlot la désigne')
        # Une seule des dix options Bark suffit à signer la liste écrite à la main.
        self.assertNotIn('<option value="bark_v2_en_0"', page)
        self.assertNotIn('id="customVoicesGroup"', page)

    def test_the_page_serves_the_common_voice_groups_with_their_keys(self):
        import json
        page = self._page()
        line = next(text_line for text_line in page.splitlines()
                    if text_line.strip().startswith('var voiceGroups = '))
        groups = json.loads(line.split('=', 1)[1].strip().rstrip(';'))
        keys = [g['key'] for g in groups]
        # « mine » est TOUJOURS là, même sans voix clonée : c'est là qu'on insère la suivante.
        self.assertIn('default', keys)
        self.assertIn('mine', keys)
        self.assertIn('bark', keys)

    def test_the_generated_field_points_at_the_common_voice_source(self):
        from wama.synthesizer.params import PARAMS_JSON
        param = next(p for p in PARAMS_JSON if p['name'] == 'voice_preset')
        self.assertEqual('voices', param['options_source'])
        self.assertEqual('voice_preset', param['dom_id']['panel'],
                         'le JS d\'app lit le select par cet id — il ne doit pas bouger')

    def test_the_panel_saver_reads_generated_fields_too(self):
        self.assertIn('data-param="\' + k + \'"', self._template_source())

    def test_the_app_js_finds_the_voice_group_by_its_key(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for path in (base / 'wama' / 'synthesizer' / 'static' / 'synthesizer' / 'js' / 'index.js',
                     base / 'staticfiles' / 'synthesizer' / 'js' / 'index.js'):
            if not path.exists():
                continue
            js = path.read_text(encoding='utf-8')
            self.assertIn('optgroup[data-group-key="', js, path.name)
            self.assertNotIn('customVoicesGroup', js, path.name)
            # L'app ANNONCE que les options ont changé ; elle ne les écoute plus. Le seul
            # auditeur d'app (le miroir de la card d'entrée) a été retiré le 2026-09-27 avec
            # les contrôles qu'il servait — l'annonce, elle, reste indispensable : c'est ce
            # qui fait rejouer les filtres de capacité sur une voix fraîchement clonée.
            self.assertIn("dispatchEvent(new CustomEvent('wama:options-filled'", js, path.name)

    def test_the_voice_field_is_rendered_by_an_inline_script(self):
        """Le rendu du champ vit dans un script EN LIGNE du gabarit. Que TOUS les scripts en
        ligne de TOUTES les pages se parsent est tenu par le contrat générique
        `common/tests_served_assets_contract` (2026-09-26) ; reste ici ce qui est propre au
        synthesizer — le rendu du champ de voix est bien DANS un de ces blocs, sans quoi le
        contrat attesterait d'autres blocs pendant que celui-ci manquerait."""
        import re
        blocks = re.findall(r'<script>(.*?)</script>', self._page(), re.S)
        self.assertTrue(any('renderPanelVoiceField' in b for b in blocks),
                        'le rendu du champ de voix n\'est plus dans un script en ligne')


class VoicePreviewPlayerTest(TestCase):
    """L'aperçu de voix pose sa source sur un lecteur qui n'a PAS de balise `<source>`.

    Défaut signalé par Fabien le 2026-09-27 en testant une voix enfant avec XTTS v2 :
    « Erreur lors de l'assemblage de l'audio: Cannot set properties of null (setting 'src') ».
    Le code écrivait dans `audioPlayer.querySelector('source').src`, mais le lecteur de la card
    d'entrée (`_new_item_extra.html`) n'en a aucune — seul celui de la modale en a une. La
    fonction est donc rejouée ICI sur un lecteur NU, c'est-à-dire sur le cas qui cassait.

    ⚠ `py_mini_racer` n'est installé que dans venv_win : ce test SKIPPE sous venv_linux.
    """

    JS_DOM = """
    var window = this; var revoked = [];
    function atob(s) { return s; }
    function Blob(parts, opts) { this.parts = parts; this.type = opts && opts.type; }
    var URL = { createObjectURL: function (b) { return 'blob:wama/' + b.parts.length; } };
    function bareplayer() {
      return { src: null, loaded: 0, played: 0, style: {},
               querySelector: function () { return null; },      // AUCUNE balise <source>
               load: function () { this.loaded++; },
               play: function () { this.played++; return { catch: function () {} }; } };
    }
    function box() { return { style: {} }; }
    var console = { log: function () {}, error: function () {} };
    var WamaApp = { toast: function (m) { this.said = m; } };
    """

    def _function_source(self):
        import re
        from pathlib import Path

        from django.conf import settings
        source = (Path(settings.BASE_DIR) / 'wama' / 'synthesizer' / 'static' / 'synthesizer'
                  / 'js' / 'index.js').read_text(encoding='utf-8')
        found = re.search(r'\n    async function assembleAndPlayAudio\(.*?\n    \}\n', source, re.S)
        self.assertIsNotNone(found, "`assembleAndPlayAudio` a disparu ou changé de forme")
        return found.group(0)

    def test_a_player_without_a_source_tag_still_receives_the_audio(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        ctx = MiniRacer()
        ctx.eval(self.JS_DOM + self._function_source())
        ctx.eval("var p = bareplayer(); var c = box(); var l = box();"
                 " assembleAndPlayAudio(['AAA'], p, c, l);")
        self.assertTrue(ctx.eval('p.src && p.src.indexOf("blob:") === 0'),
                        "la source doit être posée sur le lecteur lui-même")
        self.assertEqual(1, ctx.eval('p.loaded'))
        # ⚠ Comparer DANS V8 : une valeur absente revient en `JSUndefined`, qui n'est pas
        # `None` — un `assertIsNone` échouerait sur le comportement correct.
        self.assertTrue(ctx.eval('WamaApp.said === undefined'),
                        "aucune erreur ne doit être annoncée sur le cas nominal")
        self.assertEqual('block', ctx.eval('c.style.display'))
        self.assertEqual('none', ctx.eval('l.style.display'))

    def test_the_single_and_multi_chunk_paths_are_one(self):
        """Les deux branches d'origine étaient identiques au caractère près : une condition qui
        ne décide de rien double seulement le code à corriger."""
        self.assertNotIn('audioBuffers.length === 1', self._function_source())


class TheEntryCardKeepsOneHomePerSettingTest(TestCase):
    """La card d'entrée ne duplique plus les réglages du volet (constat de Fabien, 2026-09-27).

    Elle annonçait elle-même « Modèle, langue et options avancées : volet de droite » tout en
    portant un sélecteur de voix et un curseur de vitesse. Deux domiciles pour un même réglage,
    et le second n'avait pas de source propre : il RECOPIAIT le volet, donc il se réparait
    (recâblé sur `wama:options-filled` quand le select est devenu généré) au lieu de servir.

    ⚠ Ce que cette garde tient vraiment : que le retrait n'ait pas emporté ce que le volet
    doit encore offrir. Un contrôle retiré d'un côté DOIT exister de l'autre.
    """

    def setUp(self):
        self.client = Client()
        self.user = _utilisateur_autorise('entry_card_user')
        self.client.force_login(self.user)

    def _page(self):
        return self.client.get(reverse('synthesizer:index')).content.decode('utf-8')

    def test_the_entry_card_no_longer_mirrors_voice_and_speed(self):
        page = self._page()
        self.assertNotIn('id="textVoiceQuick"', page)
        self.assertNotIn('id="textSpeedQuick"', page)
        self.assertIn('id="textTitle"', page, 'le titre reste : il n\'existe QUE là')

    def test_what_the_card_removed_the_panel_still_offers(self):
        """Contre-épreuve : la voix et la vitesse n'ont pas disparu de la page, elles n'ont
        plus qu'UN domicile — le volet."""
        page = self._page()
        self.assertIn('id="voicePresetHost"', page)     # champ de voix GÉNÉRÉ du schéma
        self.assertIn('id="speed"', page)               # curseur de vitesse du volet

    def test_no_dead_reference_to_the_removed_mirror(self):
        """Un JS qui lirait encore les ids retirés serait muet, jamais en erreur."""
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        for path in (base / 'wama' / 'synthesizer' / 'static' / 'synthesizer' / 'js' / 'index.js',
                     base / 'staticfiles' / 'synthesizer' / 'js' / 'index.js'):
            if not path.exists():
                continue
            js = path.read_text(encoding='utf-8')
            for dead in ('textVoiceQuick', 'textSpeedQuick', 'cloneVoiceOptions'):
                self.assertNotIn(dead, js, f'{dead} dans {path.name}')
