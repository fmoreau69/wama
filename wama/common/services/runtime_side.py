"""
QUEL PROCESSUS a le droit de mettre une tâche Celery en file — une décision, un seul endroit.
Doc : `INFRA_WSL_VS_WINDOWS.md §Deux Redis`.

Règle de Fabien (2026-09-29) : *« tout doit passer côté WSL, rien côté Windows, sauf les tests à la
demande durant l'implémentation par commodité »*. Les workers, beat et le broker vivent dans WSL2 ;
un processus Windows (`venv_win`) joint un AUTRE Redis sur la même adresse, que personne ne
consomme : ce qu'il y envoyait « réussissait » sans jamais s'exécuter (1 872 messages vidés le
28/09). Et un processus de TEST, où qu'il tourne, ne doit jamais atteindre le vrai broker : ses
identifiants viennent de la base de test, le worker les lirait dans la base réelle.

Module FEUILLE (stdlib seule) : `settings.py` l'importe au chargement.
"""
import os
import sys


def running_tests(argv=None) -> bool:
    """Le processus est-il une suite de tests (`manage.py test …`) ?"""
    argv = sys.argv if argv is None else argv
    return len(argv) > 1 and argv[1] == 'test'


def tasks_dispatched(argv=None, os_name=None) -> bool:
    """Ce processus met-il ses tâches dans le VRAI broker ? Seulement côté WSL, hors tests."""
    os_name = os.name if os_name is None else os_name
    return not running_tests(argv) and os_name != 'nt'
