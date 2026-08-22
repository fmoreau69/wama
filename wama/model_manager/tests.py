"""
Model Manager — réconciliation du catalogue.

CE QUE CES TESTS PROTÈGENT, ET POURQUOI ILS EXISTENT

    Le 2026-08-22 à 18:38, une passe de synchronisation a EFFACÉ `anonymizer:sam3` du catalogue.
    Le modèle était installé, en cache HuggingFace et `ready: True` — rien n'était cassé côté
    anonymizer. Ce qui a échoué est la chaîne d'inférence :

        la déclaration de SAM3 lève dans le processus qui synchronise
          → `except Exception: pass` du registre l'avale SANS UN MOT
          → SAM3 sort de la découverte
          → la réconciliation le range parmi les « modèles absents du disque »
          → `delete_missing` SUPPRIME sa ligne.

    Le défaut n'est pas l'exception : c'est d'avoir traité une ABSENCE À LA DÉCOUVERTE comme la
    PREUVE d'une disparition. Les deux sont indiscernables du point de vue de la réconciliation,
    et une seule justifie de détruire des données.

    Coût réel de l'incident : la perte n'a été vue que 4 heures plus tard, par ricochet — une
    référence de manifeste devenue non résolvable. Aucune alerte entre les deux.
"""
from unittest.mock import patch

from django.test import TestCase

from .models import AIModel
from .services.model_registry import ModelRegistry
from .services.model_sync import ModelSyncService


def _decouverte(erreurs=(), modeles=None):
    """Fabrique une découverte CONTRÔLÉE — complète ou en échec, au choix du test."""
    def _faux(self):
        self._models = dict(modeles or {})
        self.discovery_errors = list(erreurs)
        return self._models
    return _faux


class ReconciliationTest(TestCase):
    """La suppression ne s'autorise que sur une découverte ENTIÈRE."""

    def setUp(self):
        # Une ligne que la découverte simulée ne rendra jamais : c'est elle qui joue le rôle
        # de SAM3 le jour de l'incident.
        self.temoin = AIModel.objects.create(
            model_key='test:temoin_reconciliation',
            name='Témoin de réconciliation',
            model_type='vision',
            source='anonymizer',
        )

    def test_une_decouverte_INCOMPLETE_ne_supprime_rien(self):
        """LE contrôle qui aurait évité l'incident."""
        echec = ['anonymizer:sam3 : ImportError: simulation']
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=echec)):
            resultat = ModelSyncService().full_sync(delete_missing=True)

        self.assertTrue(AIModel.objects.filter(pk=self.temoin.pk).exists(),
                        "une découverte en échec a fait supprimer une ligne de catalogue")
        self.assertEqual(resultat.removed, 0)
        self.assertTrue(any('SUSPENDUE' in e for e in resultat.errors),
                        "la suspension doit être DITE, pas silencieuse — sinon on croit "
                        "la réconciliation faite")

    def test_une_decouverte_incomplete_ne_marque_pas_non_plus_INDISPONIBLE(self):
        # `remove_missing` est l'autre chemin : moins brutal, tout aussi faux. Un modèle marqué
        # indisponible disparaît des sélecteurs — l'utilisateur constate juste qu'il « n'y est plus ».
        with patch.object(ModelRegistry, 'discover_all_models',
                          _decouverte(erreurs=['x : boom'])):
            ModelSyncService().full_sync(remove_missing=True)
        self.temoin.refresh_from_db()
        self.assertTrue(self.temoin.is_available)

    def test_une_decouverte_COMPLETE_supprime_normalement(self):
        """Le pendant indispensable : la garde ne doit pas neutraliser la réconciliation.

        Sans ce test, poser `delete_missing = False` en dur passerait le test précédent — et le
        catalogue accumulerait pour toujours des modèles retirés du disque.
        """
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=())):
            resultat = ModelSyncService().full_sync(delete_missing=True)

        self.assertFalse(AIModel.objects.filter(pk=self.temoin.pk).exists(),
                         "une découverte saine doit bien retirer ce qui a disparu")
        self.assertGreaterEqual(resultat.removed, 1)

    def test_les_candidats_de_prospection_ne_sont_jamais_reconcilies(self):
        # Ils ne sont pas sur disque PAR NATURE — les réconcilier les effacerait à chaque passe.
        propose = AIModel.objects.create(
            model_key='test:candidat_propose', name='Candidat', model_type='llm',
            source='ollama', is_proposed=True,
        )
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=())):
            ModelSyncService().full_sync(delete_missing=True)
        self.assertTrue(AIModel.objects.filter(pk=propose.pk).exists())


class DiscoveryErrorsTest(TestCase):
    """Le registre doit POUVOIR dire qu'il a échoué — sinon la garde ci-dessus est aveugle."""

    def test_le_registre_expose_ses_echecs_de_decouverte(self):
        registre = ModelRegistry()
        self.assertIsInstance(getattr(registre, 'discovery_errors', None), list)

    def test_une_passe_neuve_repart_d_une_liste_VIDE(self):
        """Sans cela, la première panne gèlerait les suppressions à jamais : les erreurs
        s'accumuleraient d'une passe sur l'autre et la réconciliation ne reprendrait jamais."""
        registre = ModelRegistry()
        registre.discovery_errors = ['résidu de la passe précédente']
        with patch.object(ModelRegistry, 'discover_all_models', _decouverte(erreurs=())):
            ModelSyncService().full_sync()
        self.assertEqual(registre.discovery_errors, [])

    def test_les_echecs_ne_sont_pas_partages_par_la_CLASSE(self):
        # `discovery_errors` est déclaré au niveau classe (le `__init__` du singleton sort tôt) :
        # il faut donc s'assurer qu'une passe RÉASSIGNE la liste au lieu de muter le défaut,
        # sinon les erreurs contamineraient toute instance future.
        ModelRegistry().discovery_errors = ['local']
        self.assertEqual(ModelRegistry.discovery_errors, [],
                         "le défaut de classe ne doit jamais être muté")
