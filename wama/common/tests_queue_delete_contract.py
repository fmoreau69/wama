"""Le contrat de SUPPRESSION d'un élément de file : la réponse dit si l'élément était dans un LOT.

POURQUOI (relevé par Fabien le 2026-09-14). Supprimer une card d'un lot de deux « fonctionnait »,
mais le lot restait affiché jusqu'au rechargement manuel. La brique commune `queue-actions.js`
recharge la page quand la réponse porte `batch_changed` — seul moyen de rendre le lot recalculé
côté serveur (réduit à une card, il redevient une card simple). Huit apps répondaient ce champ ;
le converter et l'imager, non. Aucune erreur, aucun test : le défaut ne se voyait qu'à l'écran.

Ce test tient le contrat sur TOUTES les apps qui exposent une route `<app>:delete`, pour que la
prochaine ne puisse pas l'oublier en silence. Les jumelles de bac à sable sont écartées : non
versionnées, elles héritent de la fabrique (`codegen`), pas de ce dépôt.
"""
import inspect

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, resolve, reverse


def vues_de_suppression():
    """(app, fonction de vue) pour chaque app du catalogue qui expose `<app>:delete`."""
    from wama.common.app_registry import APP_CATALOG

    trouvees = []
    for app, spec in APP_CATALOG.items():
        if spec.get('generated_from') or spec.get('sandbox'):
            continue
        try:
            url = reverse(f'{app}:delete', args=[1])
        except NoReverseMatch:
            continue
        trouvees.append((app, resolve(url).func))
    return trouvees


class ContratDeSuppressionTest(SimpleTestCase):

    def test_le_contrat_est_mesure_sur_tout_le_parc(self):
        """Non-vacuité : sans au moins les dix apps de file, le test suivant ne garderait rien."""
        apps = {app for app, _ in vues_de_suppression()}
        self.assertGreaterEqual(len(apps), 10, f"routes `<app>:delete` trouvées : {sorted(apps)}")

    def test_chaque_vue_de_suppression_dit_si_l_element_etait_dans_un_lot(self):
        for app, vue in vues_de_suppression():
            with self.subTest(app=app):
                source = inspect.getsource(inspect.unwrap(vue))
                self.assertIn('batch_changed', source,
                              f"`{app}:delete` ne répond pas `batch_changed` : une card retirée "
                              "d'un lot laisse le lot figé jusqu'au rechargement manuel")
