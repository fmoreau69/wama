"""Les outils fichier de l'assistant DÉSIGNENT comme les vues d'upload (2026-09-28).

Fabien : « ajoute l'assistant à l'étape 1 […] autant rendre les choses uniformes ». Un fichier
déposé au sas sans intention (assistant web, Discord, API) est POINTÉ par toutes les tâches
qu'on lance dessus : `tool_api.add_to_*` passe par `media_paths.designate`, la même brique que
`received_inputs`, au lieu de recopier (`File(...)` réenregistré, `shutil.copy2`).

Et la garde qui manquait : `_resolve_user_path` ne vérifiait que le confinement dans MEDIA_ROOT —
`users/<autre>/…` y est — donc un utilisateur pouvait faire recopier chez lui, ou faire lire, le
fichier d'un AUTRE. La règle est `media_paths.readable_by`.

Les outils ne sont pas nommés : tous les `add_to_*` qui prennent un fichier sont éprouvés — depuis
le 2026-11-26, l'outil DÉRIVÉ de la card de chaque app (`tool_api._card_creator`), un fichier par
son port de travail principal, que la vue de dépôt de la card désigne (`received_work`).
"""
import inspect
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from wama import tool_api
from wama.common.tests.tests_import_contract import _WITNESSES

#: Ce qu'un outil EXIGE en plus du fichier — déclaré, car rien d'autre ne le dit (même rôle que
#: `UPLOAD_QUIRKS` pour les vues) : le converter veut un format de sortie.
TOOL_ARGS = {'add_to_converter': {'output_format': 'jpg'}}


def _call(fn, name, user, rel):
    """Un appel d'outil dans un point de sauvegarde : une erreur de base dans UN outil ne doit pas
    empoisonner la transaction du test pour les outils suivants. Le fichier arrive sur le port de
    l'entrée principale de l'app (`generic_runner.primary_argument`, celui que le Studio emploie)."""
    from django.db import transaction

    from wama.studio.services.generic_runner import primary_argument
    port = primary_argument(name[len('add_to_'):])
    try:
        with transaction.atomic():
            return fn(user, **{port: rel}, **TOOL_ARGS.get(name, {}))
    except Exception as exc:   # rendu comme un refus, avec sa cause
        return {'error': f'{type(exc).__name__}: {exc}'}


def _file_tools():
    """(nom, fonction) de chaque outil `add_to_*` d'une app réelle dont l'entrée principale est un
    FICHIER qui suffit SEUL à créer l'élément (`app_registry.entry_form` : l'imager, le composer, le
    synthesizer partent d'une consigne ; l'avatarizer veut aussi un avatar)."""
    from wama.common.app_registry import APP_CATALOG, entry_form, studio_node_ports
    from wama.common.utils.app_modes import INPUT_TYPES
    from wama.studio.services.generic_runner import GENERIC_APPS, primary_argument
    for name, fn in sorted(tool_api.TOOL_REGISTRY.items()):
        app = name[len('add_to_'):]
        if not name.startswith('add_to_') or app not in GENERIC_APPS \
                or (APP_CATALOG.get(app) or {}).get('generated_from'):
            continue
        port = primary_argument(app)
        # La forme d'entrée lue sur les ports de L'OUTIL (`wama_ports`, ceux de sa signature).
        ports = getattr(fn, 'wama_ports', None) or (studio_node_ports(app) or {}).get('inputs') or []
        if port and (INPUT_TYPES.get(port) or {}).get('kind') != 'text' \
                and port in entry_form(ports)['creating']:
            yield name, fn


class ToolApiDesignationTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('tool_designer', password='x')
        self.other = User.objects.create_user('tool_someone_else', password='x')
        # The roles of every app (not an administrator : the guard is the READABILITY of a file
        # for THIS account) — the tool passes the app's gate (`_refus_app`), as on its card.
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        for role in {r for access in DEFAULT_APP_ACCESS.values() for r in (access or {}).get('roles', [])}:
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])

    def _witness(self, owner, stem, ext, content):
        from pathlib import Path
        rel = f'users/{owner.id}/temp/{stem}{ext}'
        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content())
        return rel

    def test_the_file_tools_are_found(self):
        names = [n for n, _ in _file_tools()]
        self.assertGreaterEqual(len(names), 5, f'garde à vide : {names}')

    # Le converter LANCE sa tâche à la création (`auto_start`) : jamais de tâche réelle ici.
    @mock.patch('wama.converter.tasks.convert_media_task.delay', **{'return_value.id': 'no-task'})
    def test_each_file_tool_points_a_file_of_the_users_own_space(self, _no_task):
        from wama.common.utils.file_references import direct_references
        for name, fn in _file_tools():
            with self.subTest(tool=name):
                pointed, refusals = None, []
                for ext, content in _WITNESSES.values():
                    rel = self._witness(self.user, f'{name}_witness', ext, content)
                    result = _call(fn, name, self.user, rel)
                    if isinstance(result, dict) and not result.get('error'):
                        pointed = rel
                        break
                    refusals.append((ext, result))
                self.assertIsNotNone(pointed, f'{name} : aucun témoin accepté {refusals}')
                self.assertTrue(direct_references(pointed),
                                f'{name} : l’élément créé ne POINTE pas le fichier du sas')

    @mock.patch('wama.converter.tasks.convert_media_task.delay', **{'return_value.id': 'no-task'})
    def test_no_file_tool_takes_someone_elses_file(self, _no_task):
        for name, fn in _file_tools():
            for ext, content in _WITNESSES.values():
                with self.subTest(tool=name, ext=ext):
                    rel = self._witness(self.other, f'{name}_theirs', ext, content)
                    result = _call(fn, name, self.user, rel)
                    self.assertTrue(isinstance(result, dict) and result.get('error'),
                                    f'{name} a accepté le fichier d’un autre : {result}')

    def test_the_reading_tools_refuse_someone_elses_file(self):
        rel = self._witness(self.other, 'private', '.png', _WITNESSES['image'][1])
        for fn in (tool_api.inspect_user_file, tool_api.look_at_image):
            with self.subTest(tool=fn.__name__):
                result = fn(self.user, rel)
                self.assertIn('error', result)
                self.assertIn('Accès refusé', result['error'])

    def test_the_avatarizer_designates_both_of_its_ports(self):
        from wama.common.utils.file_references import direct_references
        audio = self._witness(self.user, 'avatar_voice', '.wav', _WITNESSES['audio'][1])
        image = self._witness(self.user, 'avatar_face', '.png', _WITNESSES['image'][1])
        tool = tool_api.TOOL_REGISTRY['add_to_avatarizer']
        if 'work_image' not in tool_api.tool_arg_names('add_to_avatarizer'):
            self.skipTest("l'avatar vient des modèles du catalogue (MuseTalk) : aucun ici")
        result = tool(self.user, work_audio=audio, work_image=image)
        self.assertFalse(result.get('error'), result)
        self.assertTrue(direct_references(audio) and direct_references(image))
        theirs = self._witness(self.other, 'their_voice', '.wav', _WITNESSES['audio'][1])
        refused = tool(self.user, work_audio=theirs, work_image=image)
        self.assertTrue(refused.get('error'))
