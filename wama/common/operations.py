"""
Les OPÉRATIONS d'exploitation de WAMA — ce qu'un administrateur lance depuis la page
« Exploitation » (`common:operations`) ou par l'assistant (`dev_run_operation`), au lieu d'ouvrir
un terminal (2026-11-14, `ROADMAP §31.1`, demande de Fabien : « certaines fonctions pourraient être
intéressantes à exécuter depuis WAMA, comme les tests, check_docs »).

DÉCLARATIF ET PUR : ce module ne lance rien et n'importe ni Django ni les outils de développement —
la page le lit pour AFFICHER les opérations, le serveur de développement pour les LANCER
(`dev_inspect.dev_run_operation`, en tâche de fond, par `manage.py`). Une opération est une
commande de `manage.py` aux arguments FIGÉS ; au plus UN argument libre, borné par une expression
régulière — jamais une ligne de commande composée par l'appelant.

Toutes sont des CONTRÔLES (elles lisent, mesurent, écrivent au plus leur propre rapport), sauf
`tests`, qui joue un module de tests par le lanceur de WAMA (base de test, médias de test).
"""
import re

#: `argv` : les arguments de `manage.py`, `{argument}` à la place de l'argument libre.
#: `argument` : `{'label', 'pattern', 'example'}` quand l'opération en prend un.
OPERATIONS = {
    'check_docs': {
        'label': 'Références de la documentation', 'icon': 'fa-link',
        'description': "Chaque fichier, symbole ou ligne que les docs et les skills citent existe-t-il encore ?",
        'argv': ['check_docs'],
    },
    'doc_facts': {
        'label': 'Blocs générés des docs', 'icon': 'fa-file-circle-check',
        'description': "Les blocs que WAMA génère dans ses docs sont-ils à jour des registres ? (ne régénère rien)",
        'argv': ['doc_facts', '--check'],
    },
    'manifest_export': {
        'label': 'Corpus de manifestes', 'icon': 'fa-boxes-stacked',
        'description': "Les manifestes versionnés disent-ils encore ce que disent les registres ? (n'écrit rien)",
        'argv': ['manifest_export', '--check'],
    },
    'manifest_roundtrip': {
        'label': 'Aller-retour des manifestes', 'icon': 'fa-arrows-rotate',
        'description': "Chaque app se retrouve-t-elle fidèlement dans son manifeste, facette par facette ?",
        'argv': ['manifest_roundtrip', '--all'],
    },
    'conformity': {
        'label': 'Conformité des apps', 'icon': 'fa-list-check',
        'description': "La grille de conformité, mesurée sur le code — elle met à jour le rapport que lit la page des apps.",
        'argv': ['check_app_conformity'],
    },
    'identifier_language': {
        'label': 'Langue des identifiants', 'icon': 'fa-language',
        'description': "Le relevé des identifiants français du code, contre ses budgets.",
        'argv': ['check_identifier_language'],
    },
    'tests': {
        'label': 'Tests ciblés', 'icon': 'fa-vial',
        'description': "Un module ou une classe de tests, par le lanceur de WAMA — jamais la suite entière.",
        'argv': ['test', '{argument}', '--keepdb'],
        'argument': {'label': 'Module ou classe de tests',
                     'pattern': r'^(wama|wama_lab|wama_data)(\.\w+)+$',
                     'example': 'wama.common.tests.tests_user_settings'},
    },
}


def operations() -> list:
    """Les opérations, dans l'ordre déclaré : `[{'key', 'label', 'icon', 'description', 'argument'}]`
    — ce que la page affiche et ce que l'assistant lit (`argument` : None quand il n'y en a pas)."""
    return [{'key': key, 'label': spec['label'], 'icon': spec['icon'],
             'description': spec['description'], 'argument': spec.get('argument')}
            for key, spec in OPERATIONS.items()]


def command(key: str, argument: str = '') -> list:
    """Les arguments de `manage.py` pour l'opération `key` — `ValueError` (lisible) pour une
    opération inconnue, un argument manquant, de trop, ou qui sort de la forme déclarée."""
    spec = OPERATIONS.get(key)
    if spec is None:
        raise ValueError(f"opération inconnue : {key!r} (connues : {', '.join(OPERATIONS)})")
    argument = (argument or '').strip()
    declared = spec.get('argument')
    if declared is None:
        if argument:
            raise ValueError(f"« {spec['label']} » ne prend pas d'argument")
        return list(spec['argv'])
    if not re.match(declared['pattern'], argument):
        raise ValueError(f"{declared['label']} attendu (par exemple {declared['example']}) : "
                         f"{argument!r} refusé")
    return [argument if part == '{argument}' else part for part in spec['argv']]
