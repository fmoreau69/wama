"""Les voix SUIVENT la langue choisie — sans que rien ne disparaisse.

Constat de Fabien, 2026-09-27 : « il y a un sélecteur de langue et un sélecteur de voix, mais
le sélecteur de langue ne filtre pas les voix ». Mesuré : exact, et ce n'était pas un défaut
mais un TROU — le `data-language` d'une voix n'était confronté qu'aux langues du MOTEUR
(`WamaModelCaps.cloneVoiceFilter`), jamais à la langue choisie.

⚠ La réponse n'est PAS un masquage, et c'est une décision : la doctrine du filtre de voix dit
« avertissement, jamais masquage — un timbre se clone d'une langue à l'autre ». Ce qui change
est l'ORDRE. D'où ces gardes : ce qui remonte, ce qui ne bouge jamais, et surtout que RIEN ne
se perde en route.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SOURCE = Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-input-match.js'
SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-input-match.js'


def _extract(src, name):
    match = re.search(r'\n  function ' + name + r'\(.*?\n  }\n', src, re.S)
    return match.group(0) if match else None


class VoiceGroupOrderTest(SimpleTestCase):
    """Le cœur est PUR (une liste de langues → un ordre d'indices) : testable sans DOM."""

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval('(function(){ var window = {}; ' + src + '\n})')   # parse du module ENTIER
        body = _extract(src, 'voiceGroupOrder')
        self.assertIsNotNone(body, '`voiceGroupOrder` a disparu ou changé de forme')
        self.ctx.eval(body)

    def _order(self, languages, chosen):
        import json
        return self.ctx.eval(f'JSON.stringify(voiceGroupOrder({json.dumps(languages)}, '
                             f'{json.dumps(chosen)}))')

    def test_the_groups_of_the_chosen_language_come_first(self):
        # ['', 'fr', 'en', 'fr', ''] : défaut, français, anglais, français, bark
        self.assertEqual('[1,3,0,2,4]', self._order(['', 'fr', 'en', 'fr', ''], 'fr'))

    def test_groups_without_a_language_never_move(self):
        """« Voix par défaut », « Mes voix » et « Bark » n'ont pas de langue : ce sont les
        entrées les plus employées, elles gardent leur place."""
        self.assertEqual('[0,1,2]', self._order(['', '', ''], 'fr'))

    def test_nothing_is_ever_lost(self):
        """La garde qui compte : réordonner n'est pas filtrer. Quelle que soit la langue,
        TOUS les groupes sont rendus, chacun une fois."""
        import json
        languages = ['', 'fr', 'en', 'de', 'fr', '', 'it']
        for chosen in ('fr', 'en', 'de', 'it', 'xx', ''):
            order = json.loads(self._order(languages, chosen))
            self.assertEqual(sorted(order), list(range(len(languages))), f'langue {chosen!r}')

    def test_an_unknown_language_changes_nothing(self):
        """Contre-épreuve : une langue qu'aucune voix ne porte laisse l'ordre INTACT — on ne
        réorganise pas une liste pour rien."""
        self.assertEqual('[0,1,2,3]', self._order(['', 'fr', 'en', ''], 'xx'))


class ServedCopyTest(SimpleTestCase):

    def test_the_served_copy_matches_its_source(self):
        if SERVED.exists():
            self.assertEqual(SOURCE.read_bytes(), SERVED.read_bytes())


class VoiceDomTestCase(SimpleTestCase):
    """Socle des gardes qui ont besoin d'un DOM : un faux select de voix, exécuté sous V8.

    Aucun test ici — deux familles s'en servent : la DÉRIVE de l'ordre et le LIBELLÉ de la
    voix par défaut. Les deux réclament le même faux DOM, et un faux DOM recopié dériverait
    de son jumeau exactement comme le code qu'il teste.
    """

    FAKE_DOM = """
    function option(value, text, lang) {
      return { value: value, textContent: text, dataset: lang ? { language: lang } : {} };
    }
    function group(label, options) {
      const g = { label: label, options: options,
                  querySelectorAll: function () { return this.options; } };
      options.forEach(function (o) { o.parentNode = g; });
      return g;
    }
    const groups = [group('Français', [option('sa_1', 'Femme 1', 'fr'),
                                       option('sa_2', 'Homme 1', 'fr')]),
                    group('Défaut', [option('default', 'Voix par défaut', '')]),
                    group('English', [option('sa_3', 'Femme 1', 'en')]),
                    group('Deutsch', [option('sa_4', 'Homme 1', 'de')]),
                    group('Mes voix', [option('ua_1', 'Ma voix', '')])];
    const voices = {
      kids: groups.slice(), value: '', listeners: {},
      allOptions: function () {
        return this.kids.reduce(function (acc, g) { return acc.concat(g.options); }, []);
      },
      querySelectorAll: function (sel) {
        return sel === 'optgroup' ? this.kids.slice() : this.allOptions();
      },
      querySelector: function (sel) {
        const want = /value="([^"]+)"/.exec(sel)[1];
        return this.allOptions().filter(function (o) { return o.value === want; })[0] || null;
      },
      appendChild: function (node) {
        const at = this.kids.indexOf(node);
        if (at !== -1) this.kids.splice(at, 1);
        this.kids.push(node);
      },
      addEventListener: function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    };
    const language = {
      value: 'fr', listeners: {},
      addEventListener: function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    };
    const document = { getElementById: function (id) {
      return id === 'voice_preset' ? voices : (id === 'language' ? language : null); } };
    function labels() { return voices.kids.map(function (g) { return g.label; }).join(','); }
    function defaultLabel() {
      return voices.querySelector('option[value="default"]').textContent;
    }
    function choose(lang) {
      language.value = lang;
      (language.listeners['change'] || []).forEach(function (f) { f(); });
      return labels();
    }
    """

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval(self.FAKE_DOM)
        # Le module s'installe sur `window` : on lui en fournit un, puis on prend la brique.
        self.ctx.eval('var window = {}; (function(){' + src + '\n})();'
                      ' var WamaInputMatch = window.WamaInputMatch;')
        self.ctx.eval("WamaInputMatch.voicesFollowLanguage('voice_preset', 'language');")


class NoDriftTest(VoiceDomTestCase):
    """⚠ LA garde qui compte : réordonner ne doit pas faire DÉRIVER la liste.

    Trouvée au navigateur, pas par un test : après fr → en → de → fr, « Voix par défaut »
    était passée de la 2ᵉ à la 4ᵉ place — chaque langue visitée laissait son groupe devant
    elle, parce que `reorder` repartait de l'ordre COURANT du DOM. La garde purement
    calculatoire ne pouvait pas le voir : elle recevait à chaque appel la liste que le test
    lui donnait, jamais celle que le DOM avait gardée.

    *Une fonction juste, appelée sur un état qui dérive, produit une dérive.* D'où ce test-ci,
    qui simule le DOM et REJOUE les changements de langue.
    """

    def test_the_chosen_language_leads_and_the_rest_keeps_its_order(self):
        self.assertEqual('Français,Défaut,English,Deutsch,Mes voix', self.ctx.eval('labels()'))
        self.assertEqual('English,Français,Défaut,Deutsch,Mes voix', self.ctx.eval("choose('en')"))

    def test_coming_back_restores_exactly_the_first_order(self):
        first = self.ctx.eval('labels()')
        for lang in ('en', 'de', 'en', 'de'):
            self.ctx.eval(f"choose({lang!r});")
        self.assertEqual(first, self.ctx.eval("choose('fr')"),
                         'la liste a DÉRIVÉ : réordonner doit partir de l\'ordre d\'origine')

    def test_no_group_is_ever_lost_through_the_dom(self):
        for lang in ('en', 'de', 'xx', 'fr'):
            labels = self.ctx.eval(f"choose({lang!r})").split(',')
            self.assertEqual(5, len(labels), lang)
            self.assertEqual(5, len(set(labels)), f'doublon après {lang}')


class TheDefaultVoiceSaysWhichVoiceItIsTest(VoiceDomTestCase):
    """« Voix par défaut » suit la langue — le SERVEUR la résout, le menu la NOMME.

    Décision de Fabien, 2026-09-27. Le preset plat `default` était un clip LJSpeech anglophone
    (`voice_refs.LEGACY_FLAT_VOICES`) : un texte allemand sortait avec une locutrice anglaise,
    en silence. La résolution vit côté serveur (`default_voice_for_language`) ; ici on garde
    ce que le client en fait — dire laquelle, sans jamais toucher à la VALEUR.
    """

    def test_the_default_option_names_the_voice_of_the_chosen_language(self):
        self.assertEqual('Voix par défaut (Français — Femme 1)', self.ctx.eval('defaultLabel()'))
        self.ctx.eval("choose('de')")
        self.assertEqual('Voix par défaut (Deutsch — Homme 1)', self.ctx.eval('defaultLabel()'))

    def test_the_label_never_piles_up(self):
        """Le libellé d'origine est mémorisé : quatre changements de langue, une parenthèse."""
        for lang in ('en', 'de', 'fr', 'en'):
            self.ctx.eval(f"choose({lang!r});")
        self.assertEqual(1, self.ctx.eval('defaultLabel().split("(").length') - 1)

    def test_a_language_without_voices_falls_back_to_the_plain_label(self):
        """Contre-épreuve : aucune voix ne porte cette langue → le libellé nu, pas une
        parenthèse qui nommerait une voix d'une AUTRE langue (le serveur, lui, replie sur le
        preset plat — les deux disent la même chose)."""
        self.ctx.eval("choose('xx')")
        self.assertEqual('Voix par défaut', self.ctx.eval('defaultLabel()'))

    def test_the_stored_value_is_never_touched(self):
        """⚠ LA garde de la décision : on ne pose PAS la voix dans le select. La valeur reste
        `default`, donc l'automatisme ne se défait jamais tout seul — sinon le premier
        changement de langue le figerait sur une voix, et « auto » serait devenu un choix
        manuel dans le dos de l'utilisateur."""
        self.ctx.eval("voices.value = 'default';")
        for lang in ('en', 'de', 'fr'):
            self.ctx.eval(f"choose({lang!r});")
            self.assertEqual('default', self.ctx.eval('voices.value'), lang)
