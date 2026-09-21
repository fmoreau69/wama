"""Les connecteurs de la médiathèque (wikimedia, pixabay, pexels, openverse, jamendo, freesound).

Deux défauts soldés le 2026-09-21, et chacun a sa garde ici :
  • toute requête sortante passe par l'ouvreur commun, donc par le proxy de WAMA — urllib seul
    ignorait le réglage `WAMA_OUTBOUND_PROXY` ;
  • freesound étiquette ses résultats avec le rôle DEMANDÉ, plus `'voice'` en dur.

Aucun test ne touche le réseau : on inspecte l'ouvreur construit, et la réponse des API est
simulée à la frontière (`open_url`).

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import ast
import io
import json
import os
import urllib.request
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from wama.media_library.providers import base
from wama.media_library.providers.freesound import FreesoundProvider

PROVIDERS_DIR = Path(base.__file__).parent
PROXY_VARS = ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy')


def _explicit_proxies(opener):
    """Les proxies EXPLICITEMENT passés à l'ouvreur (urllib ajoute sinon son gestionnaire par
    défaut, qui lit l'environnement : c'est justement lui qu'on distingue)."""
    return [h.proxies for h in opener.handlers
            if isinstance(h, urllib.request.ProxyHandler) and h.proxies]


class CommonOpenerTest(SimpleTestCase):

    @override_settings(WAMA_OUTBOUND_PROXY='http://proxy.test:3128')
    def test_the_opener_follows_the_wama_outbound_proxy_setting(self):
        """Le cœur du défaut : urllib seul lit l'environnement, jamais le réglage Django."""
        with patch.dict(os.environ, {k: '' for k in PROXY_VARS}):
            proxies = _explicit_proxies(base.build_opener())
        self.assertIn({'http': 'http://proxy.test:3128', 'https': 'http://proxy.test:3128'},
                      proxies)

    @override_settings(WAMA_OUTBOUND_PROXY='')
    def test_without_any_proxy_the_opener_behaves_as_before(self):
        """Contre-épreuve : sans réglage ni environnement, on ne pose AUCUN proxy — urllib garde
        exactement son comportement d'avant le 21/09."""
        clean = {k: v for k, v in os.environ.items() if k not in PROXY_VARS}
        with patch.dict(os.environ, clean, clear=True):
            self.assertEqual([], _explicit_proxies(base.build_opener()))

    def test_every_provider_call_goes_through_the_common_opener(self):
        """La garde de non-retour : un connecteur qui rappellerait `urlopen` lui-même
        contournerait de nouveau le proxy — sans la moindre erreur, donc sans que rien ne le
        signale. Relevé par AST, pas par motif texte : un commentaire qui cite `urlopen` ne
        doit pas faire échouer la garde, un appel réel doit la faire échouer."""
        forbidden = {'urlopen', 'urlretrieve'}
        offenders = []
        for path in sorted(PROVIDERS_DIR.glob('*.py')):
            if path.name == 'base.py':
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in forbidden):
                    offenders.append(f'{path.name}:{node.lineno}')
        self.assertEqual([], offenders)


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FreesoundRoleTest(SimpleTestCase):

    def _search(self, asset_type):
        payload = {'count': 1, 'next': None, 'results': [{
            'id': 7, 'name': 'pluie', 'previews': {'preview-hq-mp3': 'https://cdn.freesound.org/p.mp3'},
            'duration': 4.2, 'filesize': 1000, 'license': 'CC0', 'username': 'x', 'tags': ['rain'],
        }]}
        provider = FreesoundProvider(api_key='k')
        with patch.object(FreesoundProvider, 'open_url',
                          return_value=_FakeResponse(json.dumps(payload).encode())) as opened:
            out = provider.search('rain', asset_type)
        return out, opened

    def test_a_sound_effect_search_returns_sound_effects(self):
        out, _ = self._search('audio_sfx')
        self.assertEqual('audio_sfx', out['results'][0].asset_type,
                         "un bruitage cherché ici entrait en médiathèque comme VOIX")

    def test_a_voice_search_still_returns_voices(self):
        out, _ = self._search('voice')
        self.assertEqual('voice', out['results'][0].asset_type)

    def test_the_search_itself_goes_through_the_common_opener(self):
        _, opened = self._search('audio_sfx')
        opened.assert_called_once()
