"""Garde du VERROU DES MOTEURS du service TTS (`tts_service.py`, 2026-09-14).

LE DÉFAUT GARDÉ. `/tts` est une fonction synchrone qu'uvicorn exécute dans un pool de threads.
Sans verrou, une requête qui basculait de moteur déchargeait celui qu'une autre requête était
en train d'utiliser : une vocalisation de l'assistant (Kokoro, résident) vidait XTTS en pleine
synthèse du synthesizer, puisque `_unload_current` ne garde que les résidents.

CE QUI EST VÉRIFIÉ — sans aucun modèle ni GPU (backends factices, `empty_cache` neutralisé) :
  1. un résident pendant une synthèse lourde est servi TOUT DE SUITE et ne décharge RIEN
     (ce test échoue sur le code d'avant le verrou : il est non vacueux) ;
  2. deux moteurs lourds se SÉRIALISENT (le second attend la fin du premier) ;
  3. au repos, un résident garde le comportement HISTORIQUE (la bascule décharge le lourd).

⚠ Importer `tts_service` remplace `torch.load` pour tout le process (bootstrap du service) :
on le restaure en fin de classe, pour ne pas changer le comportement des autres tests.
"""
import os
import tempfile
import threading
import time
from unittest import mock

from django.test import SimpleTestCase


class _FauxBackend:
    def __init__(self, nom, resident, journal, bloque=None):
        self.nom, self.keep_resident, self.journal, self.bloque = nom, resident, journal, bloque
        self.is_loaded = False

    def load(self, *args, **kwargs):
        self.is_loaded = True
        self.journal.append(('load', self.nom))

    def unload(self):
        self.is_loaded = False
        self.journal.append(('unload', self.nom))

    def synthesize(self, **kwargs):
        self.journal.append(('debut', self.nom, self.is_loaded))
        if self.bloque is not None:
            self.bloque.wait(10)
        self.journal.append(('fin', self.nom, self.is_loaded))
        fd, chemin = tempfile.mkstemp(suffix='.wav')
        os.write(fd, b'RIFF')
        os.close(fd)
        return chemin


class VerrouDesMoteursTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import torch
        cls._torch_load = torch.load
        cls._env_weights = os.environ.get('TORCH_FORCE_WEIGHTS_ONLY_LOAD')
        import tts_service
        cls.s = tts_service

    @classmethod
    def tearDownClass(cls):
        import torch
        torch.load = cls._torch_load
        if cls._env_weights is None:
            os.environ.pop('TORCH_FORCE_WEIGHTS_ONLY_LOAD', None)
        else:
            os.environ['TORCH_FORCE_WEIGHTS_ONLY_LOAD'] = cls._env_weights
        super().tearDownClass()

    def setUp(self):
        s = self.s
        self.journal = []
        self.evt = threading.Event()
        self.backends = {
            'coqui': _FauxBackend('coqui', False, self.journal, bloque=self.evt),
            'bark': _FauxBackend('bark', False, self.journal),
            'kokoro': _FauxBackend('kokoro', True, self.journal),
        }
        # ⚠ On remplace le GESTIONNAIRE, pas `_backend` : `_unload_current` et `_keep_resident`
        # interrogent `_manager.get_backend` directement. La 1ʳᵉ version de ce test remplaçait
        # `_backend` — le déchargement visait alors le vrai gestionnaire (rien de chargé), donc
        # AUCUN déchargement n'était observable et le test du défaut passait à vide.
        faux_gestionnaire = mock.Mock()
        faux_gestionnaire.get_backend.side_effect = lambda e: self.backends.get(e)
        for cible, valeur in (
            ('_manager', faux_gestionnaire),
            ('engine_for_model', lambda m, d=None: m),
            ('local_model_name', lambda m: m),
            ('_service_ready', True),
            ('_current_engine', None),
            ('_current_model_name', None),
        ):
            p = mock.patch.object(s, cible, valeur)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(s.torch.cuda, 'is_available', return_value=False)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.evt.set)

    def _req(self, moteur):
        return self.s.TTSRequest(text='bonjour', model=moteur)

    def _attendre(self, evenement, delai=5.0):
        fin = time.monotonic() + delai
        while evenement not in self.journal:
            if time.monotonic() > fin:
                self.fail(f"jamais vu {evenement} — journal : {self.journal}")
            time.sleep(0.01)

    def test_un_residant_pendant_une_synthese_lourde_ne_decharge_rien_et_n_attend_pas(self):
        lourde = threading.Thread(target=self.s.tts_endpoint, args=(self._req('coqui'),))
        lourde.start()
        self._attendre(('debut', 'coqui', True))

        debut = time.monotonic()
        reponse = self.s.tts_endpoint(self._req('kokoro'))
        duree = time.monotonic() - debut

        self.assertEqual(reponse.status_code, 200)
        self.assertLess(duree, 2.0, "le temps réel a attendu derrière la synthèse lourde")
        self.assertNotIn(('unload', 'coqui'), self.journal,
                         "XTTS déchargé en pleine synthèse : le défaut du 2026-09-14")
        self.evt.set()
        lourde.join(10)
        self.assertIn(('fin', 'coqui', True), self.journal,
                      "la synthèse lourde s'est terminée sans son modèle")

    def test_deux_moteurs_lourds_se_serialisent(self):
        premiere = threading.Thread(target=self.s.tts_endpoint, args=(self._req('coqui'),))
        premiere.start()
        self._attendre(('debut', 'coqui', True))
        seconde = threading.Thread(target=self.s.tts_endpoint, args=(self._req('bark'),))
        seconde.start()
        time.sleep(0.3)
        self.assertNotIn(('load', 'bark'), self.journal,
                         "le second moteur lourd a basculé pendant la première synthèse")
        self.evt.set()
        premiere.join(10)
        seconde.join(10)
        ordre = [e[:2] for e in self.journal]
        self.assertLess(ordre.index(('fin', 'coqui')), ordre.index(('unload', 'coqui')))
        self.assertLess(ordre.index(('unload', 'coqui')), ordre.index(('load', 'bark')))

    def test_au_repos_un_residant_garde_le_comportement_historique(self):
        self.evt.set()                                    # la synthèse lourde ne bloque pas
        self.s.tts_endpoint(self._req('coqui'))
        self.s.tts_endpoint(self._req('kokoro'))
        self.assertIn(('unload', 'coqui'), self.journal,
                      "au repos, la bascule vers le temps réel rend la VRAM du moteur lourd")
