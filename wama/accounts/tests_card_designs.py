"""Densités de card : la DÉCLARATION (`UserProfile.CARD_DESIGNS`) et ses consommateurs disent la
même chose (CARD_DESIGN §11.6bis, refonte du 2026-09-28).

Une densité vit à cinq endroits — le choix du modèle, le menu de la barre de file, les
sélecteurs `[data-card-design="…"]` des feuilles de style, les valeurs de REPLI des gabarits et
du JS, et la vue qui l'enregistre. Rien ne les liait : retirer l'ancien « Détaillé » (v1) a
demandé de trouver ses sélecteurs CSS à la main. Ces tests les confrontent en PARCOURANT le
dépôt, sans nommer aucune densité — une densité ajoutée, retirée ou renommée demain est vue
sans qu'on les touche.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile

ROOT = Path(settings.BASE_DIR)
MENU = ROOT / 'wama' / 'common' / 'templates' / 'common' / 'toolbar' / '_densite.html'
CSS_SELECTOR = re.compile(r'\[data-card-design="([^"]+)"\]')
# Repli quand le profil ne dit rien : `card_design|default:'v3'` (gabarits), `|| 'v3'` (JS).
TEMPLATE_FALLBACK = re.compile(r"card_design\|default:'([^']+)'")
JS_FALLBACK = re.compile(r"dataset\.design\s*\|\|\s*'([^']+)'")


def _declared():
    return [value for value, _label in UserProfile.CARD_DESIGNS]


def _default():
    return UserProfile._meta.get_field('card_design').default


def _sources(pattern):
    # Sources SERVIES par les apps (pas `staticfiles/`, copie de déploiement, ni les jumelles
    # gitignorées : elles recopient ces fichiers et suivent leur source ; ni le code tiers de
    # `vendors/`, où un DOSSIER peut porter l'extension — `animate.css`).
    for base in ('wama', 'wama_lab', 'wama_data'):
        for path in (ROOT / base).rglob(pattern):
            rel = str(path.relative_to(ROOT))
            if (not path.is_file() or re.search(r'[\\/]vendors[\\/]', rel)
                    or re.search(r'[\\/]\w+_\d\d[\\/]', rel)):
                continue
            yield path


class CardDesignDeclarationTest(TestCase):

    def test_the_menu_offers_exactly_the_declared_designs_in_their_order(self):
        offered = re.findall(r'wama-design-opt" data-value="([^"]+)"', MENU.read_text(encoding='utf-8'))
        self.assertEqual(offered, _declared())

    def test_the_default_is_a_declared_design_and_is_listed_first(self):
        self.assertIn(_default(), _declared())
        self.assertEqual(_declared()[0], _default(), "le menu s'ouvre sur le défaut")

    def test_every_css_selector_names_a_declared_design(self):
        # Un sélecteur qui vise une densité non déclarée est du CSS MORT (cas de l'ex-v1).
        seen = {}
        for path in _sources('*.css'):
            for value in CSS_SELECTOR.findall(path.read_text(encoding='utf-8')):
                seen.setdefault(value, str(path.relative_to(ROOT)))
        self.assertTrue(seen, 'garde à vide : aucun sélecteur de densité trouvé')
        unknown = {v: p for v, p in seen.items() if v not in _declared()}
        self.assertEqual(unknown, {})

    def test_every_design_other_than_the_default_has_its_own_rules(self):
        # Le défaut est le rendu de BASE (règles sans sélecteur) ; une autre densité sans aucune
        # règle serait une option de menu qui ne change rien.
        styled = set()
        for path in _sources('*.css'):
            styled.update(CSS_SELECTOR.findall(path.read_text(encoding='utf-8')))
        missing = [v for v in _declared() if v != _default() and v not in styled]
        self.assertEqual(missing, [])

    def test_every_fallback_equals_the_declared_default(self):
        fallbacks = []
        for path in _sources('*.html'):
            fallbacks += [(str(path.relative_to(ROOT)), v)
                          for v in TEMPLATE_FALLBACK.findall(path.read_text(encoding='utf-8'))]
        for path in _sources('*.js'):
            fallbacks += [(str(path.relative_to(ROOT)), v)
                          for v in JS_FALLBACK.findall(path.read_text(encoding='utf-8'))]
        self.assertGreaterEqual(len(fallbacks), 3, 'garde à vide : menu, journal et JS en portent un')
        self.assertEqual([f for f in fallbacks if f[1] != _default()], [])


class CardDesignSavingTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('densite', password='x')
        self.client.force_login(self.user)
        self.url = reverse('accounts:profile-layout')

    def _post(self, value):
        return self.client.post(self.url, data=json.dumps({'card_design': value}),
                                content_type='application/json')

    def test_each_declared_design_is_saved_to_the_profile(self):
        for value in _declared():
            self.assertEqual(self._post(value).status_code, 200, value)
            self.assertEqual(UserProfile.objects.get(user=self.user).card_design, value)

    def test_an_undeclared_design_is_refused_and_leaves_the_profile_alone(self):
        self._post(_default())
        response = self._post('v1')   # l'ex-« Détaillé », retiré le 2026-09-28
        self.assertEqual(response.status_code, 400)
        self.assertEqual(UserProfile.objects.get(user=self.user).card_design, _default())
