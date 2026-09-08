"""Un backend que plus aucun modèle ne désigne DIT POURQUOI il est conservé.

POURQUOI (2026-09-08, demande de Fabien : « pour les backends morts, on les laisse — ils peuvent
servir d'exemple — mais peut-on leur attribuer un tag pour l'indiquer ? A-t-on déjà prévu ça ? »).
Réponse mesurée : non, le contrat ne portait rien de tel. Le vivier savait REPÉRER un backend
qu'aucun modèle ne désigne ; il ne savait pas dire si c'est un OUBLI (à corriger) ou une DÉCISION
(à laisser). Les deux se ressemblent à l'écran et ne se traitent pas pareil.

`BaseModelBackend.DEPRECATED` porte donc la RAISON (une chaîne, jamais un booléen : un drapeau nu
ferait relire le code, et la raison se perdrait au premier départ), lue par l'inventaire AST.

⚠ Ce n'est pas un permis de garder : un backend déprécié reste compté, testé et entretenu — il est
seulement EXPLIQUÉ. L'invariant ci-dessous ne dit pas « il ne faut pas d'orphelin », il dit
« aucun orphelin MUET ».
"""
from django.test import TestCase

from wama.common.services import backend_inventory as bi


class BackendOrphelinExpliqueTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.inv = [a for a in bi.inventory() if not a.generated_from]

    def test_le_contrat_porte_la_raison_et_elle_est_vide_par_defaut(self):
        from wama.common.backends.base import BaseModelBackend
        self.assertEqual(BaseModelBackend.DEPRECATED, '')

    def test_l_inventaire_lit_la_raison_sans_importer(self):
        """Lue par AST : une valeur portée par une constante serait invisible (défaut vécu le
        07/09 sur `SUPPORTED_MODELS` de table-transformer)."""
        raisons = {e.name: e.deprecated for a in self.inv for e in a.entries if e.deprecated}
        self.assertTrue(raisons, "aucune raison lue — l'inventaire ne voit plus `DEPRECATED`")
        for nom, r in raisons.items():
            self.assertGreater(len(r), 30, f'{nom} : une raison de 3 mots n’en est pas une')

    def test_la_SEPARATION_muet_explique_est_juste__sur_des_cas_SEMES(self):
        """La LOGIQUE, sur des cas semés — l'ÉTAT est mesuré par `check_backend_links`.

        ⚠ Ma 1ʳᵉ version parcourait le catalogue RÉEL depuis un `TestCase` : base de test vide,
        donc `servis` vide, donc les 35 backends déclarés orphelins. C'est le défaut déjà vécu
        le 06/09 (un invariant vert sur du vide, ici rouge sur du vide) et déjà consigné :
        *le TEST tient la LOGIQUE, la COMMANDE mesure l'ÉTAT.*
        """
        from types import SimpleNamespace as N
        entrees = [
            N(kind='classe', name='EnService', deprecated=''),
            N(kind='classe', name='GardeExplique', deprecated='conservé comme exemple'),
            N(kind='classe', name='Oubli', deprecated=''),
            N(kind='route', name='UneRoute', deprecated=''),      # jamais concernée
        ]
        muets, expliques = bi.orphelins(entrees, servis={'EnService'})
        self.assertEqual([e.name for e in muets], ['Oubli'])
        self.assertEqual([e.name for e in expliques], ['GardeExplique'])

    def test_un_backend_SERVI_n_est_jamais_compte_comme_orphelin(self):
        """Contre-épreuve : une raison posée « au cas où » sur un backend servi ne le sort pas
        du service — il n'apparaît dans aucune des deux listes."""
        from types import SimpleNamespace as N
        entrees = [N(kind='classe', name='Servi', deprecated='raison posée à tort')]
        muets, expliques = bi.orphelins(entrees, servis={'Servi'})
        self.assertEqual(muets, [])
        self.assertEqual(expliques, [])
