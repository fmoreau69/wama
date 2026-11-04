"""Le budget VRAM de la sélection automatique DÉDUIT ce que les autres process ont réservé.

POURQUOI (2026-09-08, doute de Fabien : « ce n'est pas géré par le model manager et le
gouverneur ? »). Ça l'était **à moitié**, et c'est pire qu'un manque franc : `select_model` ÉTAIT
VRAM-aware — `budget = get_free_vram_gb()`, et `_best_by_vram` écarte ce qui n'entre pas — mais il
lisait la mesure NAÏVE du pilote. Le gouverneur portait déjà la bonne (`effective_free_gb`), dont
la docstring dit précisément ce qui manquait : « `mem_get_info()` ne voit que le présent et ignore
qu'un autre process s'apprête à prendre 18 Go ». Deux tâches lancées de front voyaient donc TOUTES
DEUX le GPU libre, et passaient — la superposition même que le gouverneur existe pour empêcher.

⚠ CE QUE CES TESTS PROTÈGENT SURTOUT, c'est la SÉMANTIQUE DU REPLI. On n'a pas remplacé l'appel
par `effective_free_gb()` : celle-ci rend `0.0` quand torch est absent, ce qui vaudrait « aucun
budget » et écarterait TOUS les modèles. Ici `None` veut dire « budget inconnu, ne contraint
pas ». Confondre les deux transformerait une sonde indisponible en panne de sélection.

⚠ Vérifié avant d'écrire la déduction : il n'existe AUCUNE libération forcée cross-process
(`wait_for_free_vram` « ne décharge rien », `cleanup_idle_models` est in-process). Déduire est
donc juste — le jour où un reclaim existera, ce choix sera à revoir.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from wama.model_manager.services.model_selector import get_free_vram_gb

#: La carte vue par `resource_governor.card_free_gb` (2026-11-04 ; c'était la sonde du moniteur).
CHEMIN_CARTE = 'wama.common.services.system_monitor.SystemMonitor.get_gpu_info'
#: La part du registre que la sonde NE VOIT PAS (2026-09-14). Elle remplaçait le total brut
#: `reserved_gb`, qui retranchait aussi les résidents déjà pris.
CHEMIN_RESERVE = 'wama.common.services.resource_governor.unseen_reserved_gb'


def _gpus(*libres):
    return [{'memory_free_gb': g} for g in libres]


class BudgetVramTest(SimpleTestCase):

    def _budget(self, gpus, reserve=0.0, reserve_leve=False):
        with patch(CHEMIN_CARTE, return_value=gpus), patch(CHEMIN_RESERVE) as reserved:
            if reserve_leve:
                reserved.side_effect = RuntimeError('registre indisponible')
            else:
                reserved.return_value = reserve
            return get_free_vram_gb()

    def test_sans_reservation__le_budget_est_le_libre_du_pilote(self):
        self.assertEqual(self._budget(_gpus(24.0)), 24.0)

    def test_les_reservations_des_AUTRES_process_sont_DEDUITES(self):
        """LE défaut que ce test existe pour empêcher : deux tâches de front voyaient chacune
        le GPU libre."""
        self.assertEqual(self._budget(_gpus(24.0), reserve=18.0), 6.0)

    def test_le_budget_ne_devient_jamais_NEGATIF(self):
        """Une part non vue du registre supérieure au libre mesuré doit donner 0, pas un
        nombre négatif qui ferait passer toutes les comparaisons."""
        self.assertEqual(self._budget(_gpus(4.0), reserve=18.0), 0.0)

    def test_the_budget_asks_what_the_card_does_not_see_yet(self):
        """La carte voit tous les occupants (2026-11-04) : seules les annonces lui manquent.
        Jusqu'au 2026-09-14 on retranchait le total brut : chaque résident comptait double."""
        with patch(CHEMIN_CARTE, return_value=_gpus(24.0)), patch(CHEMIN_RESERVE) as reserved:
            reserved.return_value = 2.0
            self.assertEqual(get_free_vram_gb(), 22.0)
            reserved.assert_called_once_with('card')

    def test_the_budget_opens_no_cuda_context(self):
        """Le tirage tourne aussi dans le process web : lire la carte ne doit pas y ouvrir de
        contexte, ce que faisait la sonde du moniteur (`get_device_properties`)."""
        with patch(CHEMIN_CARTE, return_value=_gpus(24.0)), patch(CHEMIN_RESERVE, return_value=0.0), \
                patch('torch.cuda.get_device_properties') as properties, \
                patch('torch.cuda.mem_get_info') as own_view:
            self.assertEqual(get_free_vram_gb(), 24.0)
        properties.assert_not_called()
        own_view.assert_not_called()

    def test_le_GPU_LE_PLUS_LIBRE_l_emporte(self):
        self.assertEqual(self._budget(_gpus(3.0, 20.0, 11.0), reserve=5.0), 15.0)

    def test_sans_GPU__None_veut_dire_INCONNU_pas_zero(self):
        """`None` = « budget inconnu, ne contraint pas ». Rendre 0.0 écarterait TOUS les
        modèles — c'est la raison pour laquelle on n'appelle pas `effective_free_gb` ici."""
        self.assertIsNone(self._budget([]))

    def test_une_sonde_qui_LEVE_rend_None_et_ne_propage_pas(self):
        with patch(CHEMIN_CARTE, side_effect=RuntimeError('nvml absent')):
            self.assertIsNone(get_free_vram_gb())

    def test_un_REGISTRE_indisponible_ne_DEGRADE_pas_le_budget(self):
        """Si le registre ne répond pas, on rend le brut — jamais moins. Une infrastructure
        absente ne doit pas rétrécir le parc de modèles utilisables."""
        self.assertEqual(self._budget(_gpus(24.0), reserve_leve=True), 24.0)


class SourceUniqueDeLaVramTest(SimpleTestCase):
    """La déduction ne doit pas devenir un 2ᵉ calcul concurrent de celui du gouverneur."""

    def test_le_selecteur_lit_le_registre_du_GOUVERNEUR_pas_le_sien(self):
        import ast
        import inspect
        from wama.model_manager.services import model_selector
        source = inspect.getsource(model_selector.get_free_vram_gb)
        noms = {n.module for n in ast.walk(ast.parse(source.strip()))
                if isinstance(n, ast.ImportFrom) and n.module}
        self.assertIn('wama.common.services.resource_governor', noms,
                      'le budget doit venir du registre PARTAGÉ, pas d’un compte local')
