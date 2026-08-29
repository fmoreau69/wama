"""
Couverture de test des registres catalogués — MESURÉE, jamais déclarée.

POURQUOI PAS UN CHAMP `tests=(...)` SUR `Registry`

    Il faudrait le tenir à jour, donc il finirait par mentir. `PROJECT_STATUS §39` en a fourni
    l'illustration le matin même : « 10 DataType, 19 fonctions » alors que le réel était 11 et 39,
    figé depuis un mois. Même doctrine que `mecanismes.py` et `wama_data/modules.py` — **on ne
    déclare pas l'avancement, on le mesure**. Ici la mesure est directe : on lit les tests.

CE QUE ÇA SERT

    Le contrôle générique (`ConformiteTest`) couvre le CONTRAT de tout registre, présent et futur.
    Il ne peut rien dire de la SÉMANTIQUE d'un rafraîchisseur — « le scan détecte-t-il un modèle
    renommé ? », « le rechargement voit-il un fichier supprimé ? ». Cette partie reste spécifique,
    et l'enjeu est de savoir **quels registres n'en ont aucune**.

    Le défaut mesuré le 2026-08-22 est exactement là : en ajoutant un 8ᵉ registre, la suite ne
    tombait pas — elle devenait muette. Un vert se lit « couvert ». Cette brique fait dire à la
    suite ce qu'elle ne couvre PAS.

CONVENTION DE RATTACHEMENT (mesurée, pas configurée)

    Un test est réputé SPÉCIFIQUE à un registre s'il nomme sa clé entre quotes dans son corps.
    Grossier mais honnête, et surtout sans rien à maintenir : c'est la trace qu'un test laisse
    naturellement quand il vise un registre en particulier.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from .registries import DERIVED, REGISTRIES

#: Fichiers scannés. Le point d'entrée est le fichier de tests du mécanisme ; un registre porté par
#: une app pourra ajouter le sien sans que cette brique change.
FICHIERS_DE_TEST = ('wama/common/tests_registries.py',)

_DEF_TEST = re.compile(r'\n    def (test_\w+)\(self[^)]*\):(.*?)(?=\n    def |\nclass |\Z)', re.S)
_CLASSE = re.compile(r'\nclass (\w+)\(')


def _root() -> Path:
    from django.conf import settings
    return Path(settings.BASE_DIR)


def _tests_par_registre() -> Dict[str, List[str]]:
    """{clé de registre → noms des tests qui la nomment}."""
    trouve: Dict[str, List[str]] = {key: [] for key in REGISTRIES}
    keys = sorted(REGISTRIES, key=len, reverse=True)   # les plus longues d'abord
    racine = _root()
    for rel in FICHIERS_DE_TEST:
        chemin = racine / rel
        if not chemin.exists():
            continue
        source = chemin.read_text(encoding='utf-8')
        for test_name, corps in _DEF_TEST.findall(source):
            for key in keys:
                if f"'{key}'" in corps or f'"{key}"' in corps:
                    trouve[key].append(test_name)
    return trouve


def coverage() -> List[dict]:
    """Par registre : combien de tests spécifiques, et lesquels.

    `generique` rappelle que TOUT registre est couvert sur son contrat — l'absence de test
    spécifique n'est donc pas une absence de test, seulement une absence de vérification de la
    sémantique propre. La nuance compte : la présenter comme « non testé » ferait fuir vers des
    tests de complaisance.
    """
    par_registre = _tests_par_registre()
    out = []
    for key, r in sorted(REGISTRIES.items()):
        noms = sorted(set(par_registre.get(key, ())))
        out.append({
            'key': key, 'label': r.label, 'nature': r.nature,
            'generique': True,
            'specifiques': noms,
            'nb_specifiques': len(noms),
            # Un registre DÉRIVÉ n'a pas de rafraîchisseur : il n'y a pas de sémantique à éprouver,
            # donc pas de manque à signaler. Confondre les deux produirait une alerte permanente.
            'attendu': r.nature != DERIVED,
            'manquant': r.nature != DERIVED and not noms,
        })
    return out


def summary() -> dict:
    c = coverage()
    manquants = [x['key'] for x in c if x['manquant']]
    return {
        'registres': len(c),
        'avec_tests_specifiques': sum(1 for x in c if x['nb_specifiques']),
        'sans_test_specifique': manquants,
        'detail': c,
    }
