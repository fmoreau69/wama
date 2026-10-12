# -*- coding: utf-8 -*-
"""
Aucun champ secret de WAMA ne laisse le navigateur y remplir le mot de passe de l'utilisateur.

Relevé de Fabien, 2026-10-12 : l'œil du champ « Clé de l'instance » (HuggingFace, ILaaS…)
affichait son mot de passe WAMA en clair. WAMA ne renvoie jamais une clé : c'est Chrome qui
remplissait le champ, `autocomplete="off"` étant ignoré sur un `type="password"`. Un clic sur
Enregistrer aurait posé le mot de passe comme clé d'API. Même défaut dans la fenêtre « Ajouter un
utilisateur » (le mot de passe de l'admin devenait celui du nouveau compte).

La règle : tout champ mot de passe DÉCLARE ce qu'il attend — `current-password` (connexion,
ancien mot de passe : le remplissage y est voulu) ou `new-password` (tout le reste, la seule
valeur que Chrome ne remplit pas). Ce test la tient sur les gabarits, le JS servi et les widgets
de formulaire Django.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOTS = ('wama', 'wama_lab', 'wama_data')
SKIPPED_PARTS = {'vendors', 'vendor', 'node_modules', '__pycache__'}
DECLARED = re.compile(r"""autocomplete['"]?\s*[=:]\s*['"](new-password|current-password)['"]""")
HTML_PASSWORD_TAG = re.compile(r"""<input\b[^>]*type=\\?["']password\\?["'][^>]*>""", re.S)
PY_PASSWORD_WIDGET = re.compile(r"PasswordInput\((.*?)\)\s*\)", re.S)


def _files(pattern):
    base = Path(settings.BASE_DIR)
    for root in ROOTS:
        for path in (base / root).rglob(pattern):
            if SKIPPED_PARTS.isdisjoint(path.parts) and 'tests' not in path.name:
                yield path


class PasswordAutofillTest(SimpleTestCase):

    def test_every_password_input_tag_declares_its_autocomplete(self):
        missing = []
        for path in list(_files('*.html')) + list(_files('*.js')):
            if 'static' in path.parts and path.suffix == '.html':
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            for tag in HTML_PASSWORD_TAG.findall(text):
                if not DECLARED.search(tag):
                    missing.append(f'{path.relative_to(settings.BASE_DIR)} : {tag[:90]}')
        self.assertEqual(missing, [], 'champ mot de passe sans autocomplete '
                                      'new-password/current-password :\n' + '\n'.join(missing))

    def test_a_script_turning_an_input_into_a_password_sets_new_password(self):
        # La forme JS : `input.type = … 'password'` sur un champ créé à la volée. Un simple
        # basculement d'œil (`type === 'password'` testé juste avant) vise un champ déjà rendu,
        # couvert par le test ci-dessus.
        creates = re.compile(r"""\.type\s*=\s*[^;=]*\?\s*['"]password['"]""")
        missing = [str(p.relative_to(settings.BASE_DIR)) for p in _files('*.js')
                   if creates.search(p.read_text(encoding='utf-8', errors='ignore'))
                   and 'new-password' not in p.read_text(encoding='utf-8', errors='ignore')]
        self.assertEqual(missing, [])

    def test_every_django_password_widget_declares_its_autocomplete(self):
        missing = []
        for path in _files('*.py'):
            text = path.read_text(encoding='utf-8', errors='ignore')
            for args in PY_PASSWORD_WIDGET.findall(text):
                if not DECLARED.search(args):
                    missing.append(f'{path.relative_to(settings.BASE_DIR)} : PasswordInput({args[:70]})')
        self.assertEqual(missing, [], '\n'.join(missing))

    def test_the_guard_sees_an_undeclared_password_input(self):
        # Contre-épreuve : la forme d'avant le correctif doit être vue.
        before = '<input type="password" id="key-x" class="form-control" autocomplete="off">'
        tags = HTML_PASSWORD_TAG.findall(before)
        self.assertEqual(len(tags), 1)
        self.assertIsNone(DECLARED.search(tags[0]))
        after = before.replace('"off"', '"new-password"')
        self.assertIsNotNone(DECLARED.search(after))
