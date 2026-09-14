"""Le REGISTRE VRAM du gouverneur ne compte plus deux fois une empreinte (2026-09-14).

POURQUOI. Cartographie revérifiée à la demande de Fabien, avant d'activer `vram_needed` :
- le registre ne distinguait pas une ANNONCE (sous-processus, juge de prospection : posée AVANT
  d'allouer) d'une empreinte MESURÉE (`_wrap_load` publie APRÈS le chargement). Les sondes qui
  voyaient déjà la seconde la retranchaient encore : chaque modèle résident diminuait deux fois
  la VRAM libre annoncée, et `_differer_faute_de_vram` aurait différé À TORT ;
- seul le service TTS rafraîchissait ses lignes : un résident de worker sortait du registre au
  bout du TTL ; un sous-processus plus long que le TTL (audio.cpp) aussi, en pleine exécution ;
- un rechargement idempotent remplaçait la mesure par la valeur déclarée ;
- et AUCUN test ne couvrait le registre : ni sondes, ni TTL, ni inactivité, ni enveloppes.

Aucun GPU : Redis est un dictionnaire, `torch.cuda` est simulé, les mesures sont injectées.
"""
import os
import time
from unittest import mock

from django.test import SimpleTestCase

from wama.common.backends import base
from wama.common.services import resource_governor as gov


class _FauxRedis:
    """Le sous-ensemble de l'API Redis qu'emploie le gouverneur — valeurs en `str`."""

    def __init__(self):
        self.h = {}

    def hset(self, key, field, value):
        self.h.setdefault(key, {})[field] = str(value)
        return 1

    def hsetnx(self, key, field, value):
        d = self.h.setdefault(key, {})
        if field in d:
            return 0
        d[field] = str(value)
        return 1

    def hdel(self, key, *fields):
        d = self.h.get(key, {})
        n = 0
        for f in fields:
            if f in d:
                del d[f]
                n += 1
        return n

    def hgetall(self, key):
        return dict(self.h.get(key, {}))

    def expire(self, key, ttl):
        return True


class _AvecRegistre(SimpleTestCase):

    def setUp(self):
        self.redis = _FauxRedis()
        self.t = 1_000_000.0
        for cible, kw in ((gov, {'_redis': mock.Mock(return_value=self.redis)}),
                          (gov, {'_now': mock.Mock(side_effect=lambda: self.t)})):
            p = mock.patch.multiple(cible, **kw)
            p.start()
            self.addCleanup(p.stop)

    def annexe(self, key):
        return self.redis.hgetall(key)


class SondesTest(_AvecRegistre):

    def test_une_empreinte_allouee_ICI_n_est_retranchee_d_aucune_sonde(self):
        """LE double comptage : la sonde du process (total − son alloué) et le pilote voient déjà
        ce résident ; le retrancher encore le comptait deux fois."""
        gov.reserve_vram('b.B:1#app:m', 8.0, allocated=True)
        self.assertEqual(gov.unseen_reserved_gb('process'), 0.0)
        self.assertEqual(gov.unseen_reserved_gb('driver'), 0.0)

    def test_une_empreinte_allouee_AILLEURS_echappe_au_process_mais_pas_au_pilote(self):
        gov.reserve_vram('b.B:1#app:m', 8.0, allocated=True)
        self.redis.hset(gov._ALLOC_KEY, 'b.B:1#app:m', str(os.getpid() + 1))
        self.assertEqual(gov.unseen_reserved_gb('process'), 8.0)
        self.assertEqual(gov.unseen_reserved_gb('driver'), 0.0)

    def test_une_ANNONCE_est_retranchee_des_deux_sondes(self):
        gov.reserve_vram('composer.audiocpp:1', 5.0)
        self.assertEqual(gov.unseen_reserved_gb('process'), 5.0)
        self.assertEqual(gov.unseen_reserved_gb('driver'), 5.0)

    def test_republier_en_annonce_retire_le_marqueur_alloue(self):
        gov.reserve_vram('b.B:1#app:m', 8.0, allocated=True)
        gov.reserve_vram('b.B:1#app:m', 8.0)
        self.assertEqual(gov.unseen_reserved_gb('driver'), 8.0)

    def test_une_sonde_inconnue_est_refusee(self):
        with self.assertRaises(ValueError):
            gov.unseen_reserved_gb('carte')

    def test_effective_free_gb_ne_retranche_du_pilote_que_les_annonces(self):
        gov.reserve_vram('b.B:1#app:m', 10.0, allocated=True)   # déjà hors du libre pilote
        gov.reserve_vram('composer.audiocpp:1', 5.0)            # pas encore allouée
        go = 1024 ** 3
        with mock.patch('torch.cuda.is_available', return_value=True), \
                mock.patch('torch.cuda.mem_get_info', return_value=(12 * go, 24 * go)):
            self.assertAlmostEqual(gov.effective_free_gb(), 7.0)


class CycleDeVieTest(_AvecRegistre):

    #: Clés ÉCRITES EN DUR, pas `gov._SIDE_KEYS` : une garde qui bouclerait sur la constante du
    #: code testé se tairait si la constante était vidée (mesuré par mutant le 2026-09-14).
    ANNEXES = ('wama:vram:last_used', 'wama:vram:allocated', 'wama:vram:loaded_at')

    def test_liberer_emporte_usage_chargement_et_marqueur(self):
        owner = 'b.B:1#app:m'
        gov.reserve_vram(owner, 8.0, allocated=True)
        gov.mark_used(owner)
        for key in self.ANNEXES:
            self.assertIn(owner, self.annexe(key), f'{key} doit être posé avant la libération')
        gov.release_reservation(owner)
        for key in ('wama:vram:reservations', *self.ANNEXES):
            self.assertNotIn(owner, self.annexe(key), key)

    def test_un_modele_recharge_n_herite_pas_de_l_inactivite_de_sa_vie_anterieure(self):
        owner = 'b.B:1#app:m'
        gov.reserve_vram(owner, 8.0)
        gov.mark_used(owner)
        gov.release_reservation(owner)
        self.t += 2000
        gov.reserve_vram(owner, 8.0)                  # rechargé à l'instant
        self.assertEqual(gov.idle_models(300), [])

    def test_le_battement_ne_remet_pas_a_zero_l_inactivite_d_un_modele_jamais_utilise(self):
        owner = 'b.B:1#app:m'
        gov.reserve_vram(owner, 8.0)                  # chargement
        self.t += 700
        gov.reserve_vram(owner, 8.0)                  # battement
        self.t += 200
        inactifs = gov.idle_models(300)
        self.assertEqual([m['owner'] for m in inactifs], [owner])
        self.assertEqual(inactifs[0]['idle_seconds'], 900)

    def test_une_ligne_perimee_emporte_ses_annexes(self):
        owner = 'b.B:1#app:m'
        gov.reserve_vram(owner, 8.0, allocated=True)
        gov.mark_used(owner)
        self.t += gov.RESERVATION_TTL_S + 1
        self.assertEqual(gov.reservations(), {})
        for key in self.ANNEXES:
            self.assertNotIn(owner, self.annexe(key), key)

    def test_une_residence_bornee_expire_avec_elle(self):
        gov.reserve_vram('memory-embed#ollama:bge-m3:latest', 1.0, expires_in_s=300)
        self.t += 299
        self.assertIn('memory-embed#ollama:bge-m3:latest', gov.reservations())
        self.t += 2
        self.assertEqual(gov.reservations(), {})


class ReservationDeBlocTest(_AvecRegistre):

    def test_un_bloc_plus_long_que_le_TTL_garde_sa_ligne_vivante_puis_la_rend(self):
        """audio.cpp : `timeout = 1800 + 30 × durée` s, au-delà du TTL dès 60 s d'audio."""
        owner = 'composer.audiocpp:1'
        with mock.patch.object(gov, 'RESERVATION_HEARTBEAT_S', 0.01):
            with gov.vram_reservation(owner, 13.0):
                self.t += gov.RESERVATION_TTL_S * 2
                time.sleep(0.2)
                self.assertIn(owner, gov.reservations())
            time.sleep(0.05)
            self.assertNotIn(owner, gov.reservations(), 'aucune ligne fantôme après le bloc')


class OllamaTest(_AvecRegistre):

    def test_decharger_un_modele_ollama_retire_sa_ligne_de_residence(self):
        from wama.model_manager.services.memory_manager import MemoryManager
        gov.reserve_vram(gov.ollama_host_owner('gemma3:4b'), 3.0)
        with mock.patch('requests.post') as post:
            post.return_value.raise_for_status.return_value = None
            self.assertTrue(MemoryManager.unload_model('ollama:gemma3:4b'))
        self.assertEqual(gov.reservations(), {})

    def test_la_convention_d_owner_rattache_la_ligne_au_catalogue(self):
        self.assertEqual(gov.model_key_of(gov.ollama_host_owner('gemma3:4b')), 'ollama:gemma3:4b')


class _FauxBackend(base.BaseModelBackend):
    recommended_vram_gb = 6.0

    def __init__(self):
        self._current_model = None
        self.charge = False
        self.refus = False

    def load(self, model=None):
        if self.refus:
            return False
        self._current_model = model or 'm'
        self.charge = True
        return True

    @property
    def is_loaded(self):
        return self.charge

    def unload(self):
        self.charge = False
        self._current_model = None

    def process(self, **kwargs):
        return None


class EnveloppeTest(_AvecRegistre):

    def setUp(self):
        super().setUp()
        from wama.model_manager.services import memory_manager
        unloaders = dict(memory_manager._VRAM_UNLOADERS)
        vivants = {k: set(v) for k, v in base._LIVE_BACKENDS.items()}

        def restaurer():
            memory_manager._VRAM_UNLOADERS.clear()
            memory_manager._VRAM_UNLOADERS.update(unloaders)
            for k in list(base._LIVE_BACKENDS):
                if k not in vivants:
                    del base._LIVE_BACKENDS[k]
        self.addCleanup(restaurer)
        self.b = _FauxBackend()

    def _charger(self, snapshot, mesure, **kw):
        with mock.patch.object(base, '_vram_snapshot', return_value=snapshot), \
                mock.patch.object(base, '_measured_vram_gb', return_value=mesure):
            return self.b.load(**kw)

    def _ligne(self):
        return {o: g for o, g in gov.reservations().items() if '_FauxBackend' in o}

    def test_une_empreinte_MESUREE_est_publiee_comme_allouee_par_ce_process(self):
        self._charger(0, 8.0)
        [(owner, gb)] = self._ligne().items()
        self.assertEqual(gb, 8.0)
        self.assertEqual(self.annexe(gov._ALLOC_KEY)[owner], str(os.getpid()))
        self.assertEqual(gov.unseen_reserved_gb('process'), 0.0)

    def test_un_rechargement_idempotent_garde_la_valeur_MESUREE(self):
        """Avant : la mesure nulle du 2ᵉ `load()` faisait republier la valeur DÉCLARÉE."""
        self._charger(0, 8.0)
        self._charger(0, 0.0)
        self.assertEqual(list(self._ligne().values()), [8.0])
        self.assertEqual(gov.unseen_reserved_gb('driver'), 0.0)

    def test_la_valeur_declaree_est_publiee_comme_ANNONCE(self):
        self.b.device = 'cuda'
        self._charger(0, 0.0)
        self.assertEqual(list(self._ligne().values()), [6.0])
        self.assertEqual(gov.unseen_reserved_gb('driver'), 6.0)

    def test_sans_CUDA_dans_le_process_rien_n_est_reserve(self):
        self._charger(None, None)
        self.assertEqual(self._ligne(), {})

    def test_un_backend_sur_CPU_ne_reserve_pas_sa_valeur_declaree(self):
        self.b.device = 'cpu'
        self._charger(0, 0.0)
        self.assertEqual(self._ligne(), {})

    def test_un_chargement_REFUSE_ne_rend_pas_le_backend_resident(self):
        self.b.refus = True
        self.assertFalse(self._charger(0, 0.0))
        self.assertNotIn(self.b, set(base._LIVE_BACKENDS.get('common', ())))

    def test_le_battement_republie_le_marqueur_alloue(self):
        self._charger(0, 8.0)
        self.t += 700
        self.assertGreaterEqual(base.refresh_live_reservations(), 1)
        [owner] = self._ligne()
        self.assertIn(owner, self.annexe(gov._ALLOC_KEY))
        self.assertEqual(gov.unseen_reserved_gb('driver'), 0.0)

    def test_decharger_rend_la_ligne_et_le_marqueur(self):
        self._charger(0, 8.0)
        self.b.unload()
        self.assertEqual(self._ligne(), {})
        self.assertEqual(self.annexe(gov._ALLOC_KEY), {})
        self.assertFalse(getattr(self.b, base._GOV_ALLOC))
