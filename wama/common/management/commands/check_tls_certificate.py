"""
check_tls_certificate — combien de jours reste-t-il au certificat que WAMA SERT ?

Depuis le 2026-11-10 le port 80 redirige vers https : plus aucune voie de secours en clair, et
rien ne surveillait l'expiration. On lit le certificat présenté par une vraie poignée de main,
pas le fichier sur le disque : un certificat renouvelé mais Apache non redémarré reste l'ancien
pour les utilisateurs. La poignée de main ne valide RIEN exprès : un certificat expiré doit donner
un nombre de jours négatif, pas une exception.

Codes de sortie : 0 = marge suffisante ; 1 = expire sous `WARNING_DAYS` jours, ou déjà expiré ;
3 = rien à mesurer (`WAMA_PUBLIC_URL` n'est pas en https, ou frontal injoignable — la nocturne
traduit en SKIP).

Usage :
    python manage.py check_tls_certificate
"""
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlsplit

from cryptography import x509
from django.conf import settings
from django.core.management.base import BaseCommand

#: Le temps de faire signer et poser un nouveau certificat, DSI comprise.
WARNING_DAYS = 30
CONNECT_TIMEOUT_S = 10


def served_certificate(host: str, port: int) -> x509.Certificate:
    """Le certificat que présente le frontal, tel quel."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            return x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))


class Command(BaseCommand):
    help = "Jours restants au certificat réellement servi par le frontal https de WAMA"

    def handle(self, *args, **options):
        write = self.stdout.write
        url = urlsplit(getattr(settings, 'WAMA_PUBLIC_URL', '') or '')
        if url.scheme != 'https' or not url.hostname:
            write("WAMA_PUBLIC_URL n'est pas une adresse https : aucun certificat à mesurer")
            raise SystemExit(3)
        try:
            certificate = served_certificate(url.hostname, url.port or 443)
        except OSError as error:   # dont ssl.SSLError, socket.timeout, résolution du nom
            write(f"Frontal https injoignable ({url.hostname}) : {error}")
            raise SystemExit(3)

        expires = certificate.not_valid_after_utc
        days = (expires - datetime.now(timezone.utc)).days
        write(f"Certificat de {url.hostname} : expire le {expires:%Y-%m-%d}, "
              f"dans {days} jour(s) (seuil : {WARNING_DAYS})")
        if days < WARNING_DAYS:
            raise SystemExit(1)
