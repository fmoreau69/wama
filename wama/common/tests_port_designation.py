"""Les PORTS des apps « attache » reçoivent une désignation (2026-09-28, étape 1 de la card v4).

imager (image de référence), avatarizer (audio ET image d'avatar), composer (mélodie de
référence), synthesizer (voix de référence) : chaque port lit son fichier par
`media_paths.received_inputs(field=<port>)` — téléversé, ou désigné sous `<port>__designated`
(`designation_field`). Une désignation de l'espace de l'utilisateur est POINTÉE ; celle d'un
autre est refusée.

Les cas sont DÉCLARÉS (route, champ du port, POST minimal) : ces vues de création n'ont pas de
contrat commun à dériver — c'est précisément ce que la card v4 viendra unifier.
"""
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

# Le MODULE, pas la classe : importer un TestCase dans un module de tests le fait redécouvrir
# (ses tests tournaient deux fois).
from wama.common import tests_import_contract as _contract
from wama.common.tests_import_contract import _WITNESSES
from wama.common.utils.media_paths import designation_field

#: (app, route, port, nature du témoin, POST minimal) — ce qu'il faut à la vue pour créer.
PORT_CASES = [
    ('imager', 'imager:create', 'reference_image', 'image',
     {'generation_mode': 'img2img', 'prompt': 'témoin', 'model': 'auto'}),
    ('avatarizer', 'avatarizer:create', 'audio_input', 'audio',
     {'avatar_source': 'gallery', 'avatar_gallery_name': 'witness.png'}),
    ('composer', 'composer:generate', 'melody_reference', 'audio',
     {'prompt': 'témoin', 'model': 'musicgen-melody', 'duration': '5'}),
    ('synthesizer', 'synthesizer:upload', 'voice_reference', 'audio', {}),
]


class PortsReceiveDesignationsTest(TestCase):

    _user_for = _contract.ContratUploadDesAppsPorteesTest._utilisateur

    def _witness(self, owner, stem, nature):
        ext, content = _WITNESSES[nature]
        rel = f'users/{owner.id}/temp/{stem}{ext}'
        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content())
        return rel

    def _post(self, app, route, port, rel, extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {designation_field(port): rel, **extra}
        if app == 'synthesizer':    # sa vue exige un fichier de TEXTE en plus de la voix
            data['file'] = SimpleUploadedFile('witness.txt', b'Bonjour.')
        with mock.patch('wama.avatarizer.views._ensure_workers_imported'), \
                mock.patch('wama.avatarizer.views._generate_avatar', create=True,
                           **{'delay.return_value.id': 'no-task'}), \
                mock.patch('wama.composer.tasks.compose_task.apply_async',
                           **{'return_value.id': 'no-task'}):
            return self.client.post(reverse(route), data)

    def _roles(self, app):
        from wama.accounts.permissions import DEFAULT_APP_ACCESS
        return list((DEFAULT_APP_ACCESS.get(app) or {}).get('roles', []))

    def test_each_port_points_a_designated_file_of_the_users_space(self):
        from wama.common.utils.file_references import direct_references
        for app, route, port, nature, extra in PORT_CASES:
            with self.subTest(app=app, port=port):
                user = self._user_for(f'{app}_port', self._roles(app))
                self.client.force_login(user)
                rel = self._witness(user, f'{app}_{port}', nature)
                rep = self._post(app, route, port, rel, extra)
                self.assertLess(rep.status_code, 400, f'{app} : {rep.status_code} {rep.content[:300]!r}')
                refs = [r for r in direct_references(rel) if r['field'] == port]
                self.assertTrue(refs, f'{app} : le port `{port}` ne POINTE pas le fichier désigné')

    def test_a_port_rejects_someone_elses_file(self):
        from wama.common.utils.file_references import direct_references
        from django.contrib.auth.models import User
        other = User.objects.create_user('port_someone_else', password='x')
        for app, route, port, nature, extra in PORT_CASES:
            with self.subTest(app=app, port=port):
                user = self._user_for(f'{app}_port_refused', self._roles(app))
                self.client.force_login(user)
                rel = self._witness(other, f'{app}_{port}_theirs', nature)
                self._post(app, route, port, rel, extra)
                self.assertFalse(direct_references(rel),
                                 f'{app} : le port `{port}` a pris le fichier d’un autre')
