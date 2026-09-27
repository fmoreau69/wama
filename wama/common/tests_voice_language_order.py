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


class NoDriftTest(SimpleTestCase):
    """⚠ LA garde qui compte : réordonner ne doit pas faire DÉRIVER la liste.

    Trouvée au navigateur, pas par un test : après fr → en → de → fr, « Voix par défaut »
    était passée de la 2ᵉ à la 4ᵉ place — chaque langue visitée laissait son groupe devant
    elle, parce que `reorder` repartait de l'ordre COURANT du DOM. La garde purement
    calculatoire ne pouvait pas le voir : elle recevait à chaque appel la liste que le test
    lui donnait, jamais celle que le DOM avait gardée.

    *Une fonction juste, appelée sur un état qui dérive, produit une dérive.* D'où ce test-ci,
    qui simule le DOM et REJOUE les changements de langue.
    """

    FAKE_DOM = """
    function group(label, lang) {
      const opts = [{ dataset: lang ? { language: lang } : {} }];
      return { label: label, querySelectorAll: function () { return opts; } };
    }
    const groups = [group('Français', 'fr'), group('Défaut', ''), group('English', 'en'),
                    group('Deutsch', 'de'), group('Mes voix', '')];
    const voices = {
      kids: groups.slice(), value: '', listeners: {},
      querySelectorAll: function () { return this.kids.slice(); },
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
