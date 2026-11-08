"""`/media/` servi sous la règle de lecture, `/static/` sans `DEBUG` (reste n°2 de l'audit de
sécurité du 2026-11-06, décisions de Fabien du 2026-11-08 — `common/utils/media_serving.py`).

Jusque-là `/media/` n'était servi que par l'`Alias` d'Apache et, `DEBUG` allumé, par gunicorn —
sans aucun contrôle : quiconque connaissait l'adresse d'un fichier le lisait.
"""
import re
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

User = get_user_model()


def _account(name, **extra):
    from django.contrib.auth.models import Group
    from wama.accounts.permissions import GROUP_PREFIX
    user = User.objects.create_user(name, password='x', **extra)
    for role in ('communication', 'recherche', 'ingenierie', 'administratif'):
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
        user.groups.add(group)
    return user


class GuardedMediaTest(TestCase):

    def setUp(self):
        media = tempfile.mkdtemp(prefix='wama_media_serving_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        setting = override_settings(MEDIA_ROOT=media)
        setting.enable()
        self.addCleanup(setting.disable)
        self.media = Path(media)
        self.owner = _account('media_serving_owner')
        self.other = _account('media_serving_other')

    def _write(self, rel, data=b'0123456789' * 100):
        target = self.media / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return rel

    def _get(self, rel, user=None, **headers):
        if user is not None:
            self.client.force_login(user)
        return self.client.get(f'/media/{rel}', **headers)

    def test_the_owner_reads_his_file_with_protective_headers(self):
        rel = self._write(f'users/{self.owner.id}/temp/a.bin')
        response = self._get(rel, self.owner)
        self.assertEqual(200, response.status_code)
        self.assertEqual(1000, len(b''.join(response.streaming_content)))
        self.assertEqual('bytes', response['Accept-Ranges'])
        self.assertEqual('private', response['Cache-Control'])
        self.assertEqual('nosniff', response['X-Content-Type-Options'])

    def test_another_account_is_refused(self):
        rel = self._write(f'users/{self.owner.id}/temp/a.bin')
        self.assertEqual(403, self._get(rel, self.other).status_code)

    def test_a_visitor_is_sent_to_the_login_page(self):
        rel = self._write(f'users/{self.owner.id}/temp/a.bin')
        response = self._get(rel)
        self.assertEqual(302, response.status_code)
        self.assertIn('next=', response['Location'])

    def test_a_visitor_reads_the_files_of_his_session_identity_only(self):
        from wama.accounts.permissions import VISITOR_ACCOUNT_PREFIX
        from wama.accounts.visitors import SESSION_KEY
        visitor = User.objects.create(username=f'{VISITOR_ACCOUNT_PREFIX}mediatest', is_active=False)
        own = self._write(f'users/{visitor.id}/converter/output/out.png')
        foreign = self._write(f'users/{self.owner.id}/temp/a.bin')
        session = self.client.session
        session[SESSION_KEY] = visitor.pk
        session.save()
        self.assertEqual(200, self.client.get(f'/media/{own}').status_code)
        self.assertEqual(403, self.client.get(f'/media/{foreign}').status_code)

    def test_an_administrator_reads_every_file(self):
        rel = self._write(f'users/{self.owner.id}/temp/a.bin')
        admin = _account('media_serving_admin', is_superuser=True)
        self.assertEqual(200, self._get(rel, admin).status_code)

    def test_a_climb_out_of_the_tree_is_not_served(self):
        self._write(f'users/{self.other.id}/temp/secret.bin')
        forged = f'users/{self.owner.id}/../{self.other.id}/temp/secret.bin'
        self.assertEqual(403, self._get(forged, self.owner).status_code)
        self.assertEqual(404, self._get('../outside.bin', self.owner).status_code)

    def test_a_video_is_served_by_ranges(self):
        rel = self._write(f'users/{self.owner.id}/temp/v.mp4')
        response = self._get(rel, self.owner, HTTP_RANGE='bytes=10-19')
        self.assertEqual(206, response.status_code)
        self.assertEqual(b'0123456789', b''.join(response.streaming_content))

    def test_an_html_or_svg_file_runs_in_a_sandbox(self):
        for name in ('page.html', 'logo.svg'):
            with self.subTest(name=name):
                rel = self._write(f'users/{self.owner.id}/temp/{name}', b'<svg></svg>')
                response = self._get(rel, self.owner)
                self.assertEqual('sandbox', response['Content-Security-Policy'])

    def _shared_job_input(self, name):
        from wama.common.services.sharing import share_with_person
        from wama.common.utils.media_paths import app_media_dir
        from wama.converter.models import ConversionJob
        rel = self._write(f"{app_media_dir('converter', self.owner.id, 'input')}/{name}")
        job = ConversionJob.objects.create(user=self.owner, input_filename=name)
        job.input_file.name = rel
        job.save(update_fields=['input_file'])
        share_with_person(self.owner, job, ConversionJob, self.other, nature='element')
        return rel

    def test_a_derived_copy_is_judged_on_its_original(self):
        """La copie de lecture d'une entrée PARTAGÉE n'est portée par aucune card : seul son
        original dit qui la lit."""
        from wama.common.utils.video_compat import playback_copy_rel
        original = self._shared_job_input('clip.mkv')
        copy = self._write(playback_copy_rel(original))
        stranger = _account('media_serving_copy_stranger')
        self.assertEqual(200, self._get(copy, self.owner).status_code)
        self.assertEqual(200, self._get(copy, self.other).status_code)
        self.assertEqual(403, self._get(copy, stranger).status_code)

    def test_an_unchanged_file_is_not_sent_again(self):
        rel = self._write(f'users/{self.owner.id}/temp/a.bin')
        first = self._get(rel, self.owner)
        again = self.client.get(f'/media/{rel}', HTTP_IF_MODIFIED_SINCE=first['Last-Modified'])
        self.assertEqual(304, again.status_code)

    def test_the_input_of_a_shared_card_is_readable_by_its_recipient(self):
        rel = self._shared_job_input('in.png')
        stranger = _account('media_serving_stranger')
        self.assertEqual(200, self._get(rel, self.other).status_code)
        self.assertEqual(403, self._get(rel, stranger).status_code)


class StaticWithoutDebugTest(TestCase):
    """Le lanceur de tests tourne `DEBUG` éteint : la page se sert quand même de ses statiques."""

    def test_a_static_file_is_served(self):
        static = tempfile.mkdtemp(prefix='wama_static_serving_')
        self.addCleanup(shutil.rmtree, static, ignore_errors=True)
        (Path(static) / 'x.js').write_text('let a = 1;')
        with override_settings(STATIC_ROOT=static):
            response = self.client.get('/static/x.js')
        self.assertEqual(200, response.status_code)


class DebugOffByDefaultTest(SimpleTestCase):
    """`DEBUG` se lit dans l'environnement, éteint par défaut — il était écrit en dur à True."""

    def test_settings_do_not_hardcode_debug(self):
        source = (Path(__file__).resolve().parents[2] / 'settings.py').read_text(encoding='utf-8')
        assignments = re.findall(r'^DEBUG\s*=\s*(.+)$', source, flags=re.MULTILINE)
        self.assertEqual(["os.environ.get('WAMA_DEBUG', '') == '1'"], assignments)

    def test_the_development_script_turns_it_on(self):
        script = (Path(__file__).resolve().parents[3] / 'start_wama_dev.sh').read_text(encoding='utf-8')
        self.assertRegex(script, r'(?m)^export WAMA_DEBUG=1$')

    def test_apache_no_longer_serves_media_unguarded(self):
        """La config Apache vit HORS du dépôt : on ne la lit que là où elle existe (ce poste)."""
        conf = Path('/mnt/c/Apache24/conf/extra/wama-common.conf')
        if not conf.exists():
            conf = Path('C:/Apache24/conf/extra/wama-common.conf')
        if not conf.exists():
            self.skipTest('pas de frontal Apache sur ce poste')
        lines = [line.strip() for line in conf.read_text(encoding='utf-8', errors='replace').splitlines()
                 if line.strip() and not line.strip().startswith('#')]
        self.assertFalse([line for line in lines if line.startswith(('Alias /media', 'ProxyPass /media'))])
