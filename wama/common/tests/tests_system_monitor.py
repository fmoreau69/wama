"""Relevés de l'hôte Windows PARTAGÉS quelques secondes (2026-10-02).

CE QUE CES GARDES TIENNENT : un relevé de l'hôte (CPU, RAM, disque — un programme Windows lancé
depuis WSL, `wmic cpu` ~1,3 s) est lu AU PLUS une fois par `HOST_READING_TTL_S` pour tous les
processus. Avant, le pied de page de chaque onglet le relançait toutes les quelques secondes et
la page du model manager l'attendait (1,6 s sur 1,7). Un relevé manqué n'est pas gardé, et sans
cache joignable on lit directement, comme avant.
"""
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase

from wama.common.services import system_monitor
from wama.common.services.system_monitor import SystemMonitor


class SharedHostReadingTest(SimpleTestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_a_reading_is_taken_once_within_its_lifetime(self):
        read = mock.Mock(return_value={'percent': 12})
        for _ in range(3):
            self.assertEqual({'percent': 12}, SystemMonitor._shared_reading('probe', read))
        read.assert_called_once()

    def test_a_missed_reading_is_not_kept(self):
        read = mock.Mock(return_value=None)
        SystemMonitor._shared_reading('probe', read)
        SystemMonitor._shared_reading('probe', read)
        self.assertEqual(2, read.call_count)

    def test_without_a_reachable_cache_the_host_is_read_directly(self):
        with mock.patch('django.core.cache.cache.get', side_effect=ConnectionError('redis down')):
            self.assertEqual({'percent': 7},
                             SystemMonitor._shared_reading('probe', lambda: {'percent': 7}))

    def test_the_footer_does_not_relaunch_the_windows_cpu_query(self):
        """The footer of every open tab polls every few seconds: one `wmic` per lifetime."""
        with mock.patch.object(system_monitor, 'IS_WSL', True), \
                mock.patch.object(SystemMonitor, '_get_windows_cpu_from_wsl',
                                  return_value={'percent': 30, 'count': 8, 'freq_mhz': None,
                                                'source': 'windows_host'}) as cpu:
            for _ in range(3):
                self.assertEqual(30, SystemMonitor.get_cpu_info()['percent'])
        cpu.assert_called_once()
