"""HTTPS forcé par le frontal (2026-11-10) : `INFRA_WSL_VS_WINDOWS.md §HTTPS`.

Deux choses tiennent ici, parce qu'aucune autre garde ne les verrait :
- un cookie émis pour une requête venue en https est `Secure`, et celui d'une requête en http
  directe à gunicorn (tests, contrôles nocturnes) ne l'est pas — sinon ces clients perdent leur
  session ;
- le certificat réellement servi est mesuré, et son expiration proche rougit.
"""
import ssl
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.management.commands import check_tls_certificate as command
from wama.common.nightly_scenarios import _run_tls_certificate
from wama.common.services.nightly_tests import SkipScenario, load_scenarios, select_scenarios

LOGIN_PATH = '/accounts/login/'
THROUGH_HTTPS = {'HTTP_X_FORWARDED_PROTO': 'https'}
PUBLIC_URL = 'https://wama.example.org'


class SecureCookiesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('https_front_user', password='front-pass-1')

    def test_the_csrf_cookie_is_secure_on_a_request_through_https(self):
        response = self.client.get(LOGIN_PATH, **THROUGH_HTTPS)
        self.assertTrue(response.cookies[settings.CSRF_COOKIE_NAME]['secure'])

    def test_the_session_cookie_is_secure_on_a_login_through_https(self):
        response = self.client.post(
            LOGIN_PATH, {'username': 'https_front_user', 'password': 'front-pass-1'}, **THROUGH_HTTPS)
        self.assertEqual(302, response.status_code)
        self.assertTrue(response.cookies[settings.SESSION_COOKIE_NAME]['secure'])

    def test_a_direct_http_request_keeps_cookies_it_can_send_back(self):
        response = self.client.post(
            LOGIN_PATH, {'username': 'https_front_user', 'password': 'front-pass-1'})
        self.assertEqual(302, response.status_code)
        self.assertFalse(response.cookies[settings.SESSION_COOKIE_NAME]['secure'])

    def test_a_direct_http_request_is_not_redirected(self):
        self.assertEqual(200, self.client.get(LOGIN_PATH).status_code)


def build_certificate(days_left, key=None):
    key = key or ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'wama.example.org')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder()
                   .subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(days=400))
                   .not_valid_after(now + timedelta(days=days_left, hours=1))
                   .sign(key, hashes.SHA256()))
    return certificate, key


def run_command(days_left):
    with mock.patch.object(command, 'served_certificate',
                           return_value=build_certificate(days_left)[0]):
        call_command('check_tls_certificate', stdout=mock.Mock())


@override_settings(WAMA_PUBLIC_URL=PUBLIC_URL)
class CertificateExpiryTest(SimpleTestCase):

    def assert_exits_with(self, code, days_left):
        with self.assertRaises(SystemExit) as stop:
            run_command(days_left)
        self.assertEqual(code, stop.exception.code)

    def test_a_certificate_with_margin_passes(self):
        run_command(command.WARNING_DAYS + 5)

    def test_a_certificate_close_to_expiry_is_red(self):
        self.assert_exits_with(1, command.WARNING_DAYS - 5)

    def test_an_expired_certificate_is_red(self):
        self.assert_exits_with(1, -3)

    def test_an_unreachable_front_is_a_skip_not_a_red(self):
        with mock.patch.object(command, 'served_certificate', side_effect=OSError('refused')):
            with self.assertRaises(SystemExit) as stop:
                call_command('check_tls_certificate', stdout=mock.Mock())
        self.assertEqual(3, stop.exception.code)

    @override_settings(WAMA_PUBLIC_URL='http://wama.example.org')
    def test_an_instance_without_https_has_nothing_to_measure(self):
        with self.assertRaises(SystemExit) as stop:
            call_command('check_tls_certificate', stdout=mock.Mock())
        self.assertEqual(3, stop.exception.code)

    def test_the_expiry_is_played_every_night(self):
        load_scenarios()
        self.assertIn('common.consistency.tls_certificate',
                      [s.id for s in select_scenarios(stage='consistency')])

    def test_the_nightly_scenario_is_green_with_margin(self):
        with mock.patch.object(command, 'served_certificate',
                               return_value=build_certificate(200)[0]):
            ok, detail = _run_tls_certificate({})
        self.assertTrue(ok)
        self.assertIn('expire le', detail)

    def test_the_nightly_scenario_is_red_close_to_expiry(self):
        with mock.patch.object(command, 'served_certificate',
                               return_value=build_certificate(5)[0]):
            ok, _ = _run_tls_certificate({})
        self.assertFalse(ok)

    def test_the_nightly_scenario_skips_when_nothing_answers(self):
        with mock.patch.object(command, 'served_certificate', side_effect=OSError('refused')):
            with self.assertRaises(SkipScenario):
                _run_tls_certificate({})


class ServedCertificateTest(SimpleTestCase):
    """La vraie poignée de main, sur la boucle locale — les tests ci-dessus simulent ce point."""

    def test_the_certificate_presented_by_a_tls_server_is_read_even_expired(self):
        certificate, key = build_certificate(-10)
        with tempfile.TemporaryDirectory() as folder:
            cert_path, key_path = Path(folder) / 'c.pem', Path(folder) / 'k.pem'
            cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)

        import socket
        with socket.create_server(('127.0.0.1', 0)) as listener:
            port = listener.getsockname()[1]

            def serve_one():
                connection, _ = listener.accept()
                with context.wrap_socket(connection, server_side=True):
                    pass

            server = threading.Thread(target=serve_one, daemon=True)
            server.start()
            seen = command.served_certificate('127.0.0.1', port)
            server.join(timeout=5)
        self.assertEqual(certificate.serial_number, seen.serial_number)
