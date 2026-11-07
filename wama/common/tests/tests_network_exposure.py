"""Ce que les scripts de démarrage ouvrent au réseau (audit de sécurité du 2026-11-06).

Deux familles, une règle : la boucle locale.
- le relais Windows → WSL2 (`netsh interface portproxy`) que pose `start_wama_prod.sh` : son seul
  client est Apache (`ProxyPass / http://127.0.0.1:8000/`) ; écouté sur 0.0.0.0, il ouvrait
  gunicorn au réseau sans passer par Apache (2026-11-07) ;
- les services sans authentification (voix :8001, vecteurs :8002, confidentialité :8003) : leurs
  clients visent `localhost` (2026-11-06).

Gunicorn, lui, écoute sur 0.0.0.0 DANS WSL2 (`gunicorn_conf.bind`) : le relais vise l'adresse de
la machine WSL2, et le NAT de WSL2 ne la rend joignable que depuis l'hôte.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
SCRIPTS = ('start_wama_prod.sh', 'start_wama_dev.sh')
LOOPBACK = '127.0.0.1'


def code_lines(name):
    """Les lignes de commande du script (les commentaires disent l'histoire, pas l'écoute)."""
    text = (ROOT / name).read_text(encoding='utf-8')
    return [l for l in text.splitlines() if not l.lstrip().startswith('#')]


def relay_commands():
    """Les commandes `netsh` réellement EXÉCUTÉES (par `cmd.exe`), pas les conseils affichés."""
    return [l for l in code_lines('start_wama_prod.sh') if 'cmd.exe' in l and 'portproxy' in l]


class LoopbackListenersTest(SimpleTestCase):

    def test_the_windows_relay_listens_on_loopback_only(self):
        adds = [m.group(1) for l in relay_commands()
                for m in re.finditer(r'portproxy add v4tov4[^"&]*?listenaddress=(\S+)', l)]
        self.assertTrue(adds, 'plus aucune règle portproxy posée : la garde ne voit plus rien')
        self.assertEqual({LOOPBACK}, set(adds),
                         'le relais vers gunicorn s’écoute sur la boucle locale seule — '
                         'Apache est son unique client')

    def test_the_old_wildcard_relay_is_removed_at_startup(self):
        self.assertTrue(any('portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 ' in l
                            for l in relay_commands()),
                        'la règle 0.0.0.0 d’avant le 2026-11-07 survivrait à côté de la neuve')

    def test_the_services_without_authentication_listen_on_loopback(self):
        hosts = {(name, m.group(1)) for name in SCRIPTS for l in code_lines(name)
                 for m in re.finditer(r'--host\s+(\S+)', l)}
        self.assertTrue(hosts)
        self.assertEqual([], sorted(h for h in hosts if h[1] != LOOPBACK))
