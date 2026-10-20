"""Un envoi de notification ne peut plus bloquer une tâche indéfiniment (`utils/notifications.py`).

Vécu le 2026-09-29 : le worker gpu est resté 4 h dans la notification de fin d'une card — une
connexion SMTP établie, aucune réponse, et aucun délai. « Fail-safe » n'y pouvait rien : une
attente sans fin ne lève jamais d'exception.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from wama.common.utils import notifications


class NotificationTimeoutTest(SimpleTestCase):

    def _timeout_used(self):
        with mock.patch('django.core.mail.get_connection', wraps=__import__(
                'django.core.mail', fromlist=['get_connection']).get_connection) as connection:
            self.assertTrue(notifications.notify_emails(['someone@test.local'], 'sujet', 'corps'))
        return connection.call_args.kwargs.get('timeout')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_every_send_carries_a_timeout(self):
        self.assertEqual(notifications.SMTP_TIMEOUT_SECONDS, self._timeout_used())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_TIMEOUT=7)
    def test_the_setting_wins_when_it_is_set(self):
        self.assertEqual(7, self._timeout_used())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                       EMAIL_HOST='127.0.0.1', EMAIL_PORT=9, EMAIL_USE_SSL=False, EMAIL_USE_TLS=False)
    def test_the_smtp_connection_is_opened_with_that_timeout(self):
        """Sur le VRAI transport SMTP : le délai arrive jusqu'au socket (`smtplib`)."""
        with mock.patch('smtplib.SMTP') as smtp:
            smtp.side_effect = OSError('refusé')
            notifications.notify_emails(['someone@test.local'], 'sujet', 'corps')
        self.assertEqual(notifications.SMTP_TIMEOUT_SECONDS, smtp.call_args.kwargs.get('timeout'))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
                       EMAIL_HOST='127.0.0.1', EMAIL_PORT=9, EMAIL_USE_SSL=False, EMAIL_USE_TLS=False)
    def test_a_message_the_server_refused_is_not_reported_sent(self):
        """`fail_silently` avale le refus du serveur : l'envoi rendait vrai quand même, et la
        demande de modération perdue du 2026-10-20 se journalisait « envoyée »."""
        with mock.patch('smtplib.SMTP', side_effect=OSError('refusé')), \
                self.assertLogs('wama.common.utils.notifications', 'WARNING'):
            self.assertFalse(notifications.notify_emails(['someone@test.local'], 'sujet', 'corps'))
