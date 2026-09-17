"""La PRÉSENTATION d'un état — UNE déclaration, plusieurs consommateurs.

Pourquoi ce module (2026-09-18, marche P2 — demande de Fabien : « on ne peut pas refactoriser ça
pour éviter les duplications d'écriture ? À minima, dériver plutôt que réécrire »).

Le VOCABULAIRE (valeurs, libellés, alias) vit dans `common/models.py` et n'a jamais été dupliqué.
Ce qui l'était, c'est son APPARENCE : classe de badge, classe de texte, icône — recopiées dans
`wama-app-base.js`, dans `_card_progress.html`, dans `_card_state.html`, dans le ternaire de
`wama-inspector.js`, et jusque dans des gabarits d'app. Cinq écritures du même fait.

⚠ POURQUOI PAS DANS `common/models.py` : la couche MODÈLE n'a pas à connaître `bg-warning` ni
`fa-spinner`. Le vocabulaire y reste ; l'apparence vit ici et l'IMPORTE. Un domaine, un fichier.

⚠ `DRAFT` n'est PAS un état du vocabulaire commun (il n'est ni dans `JOB_STATUS_CHOICES` ni dans
`PROCESS_STATUS_CHOICES`) mais les maps JS l'affichaient. Le dériver naïvement l'aurait fait
DISPARAÎTRE de l'écran : il est donc déclaré ici explicitement, comme état d'AFFICHAGE, et la
distinction est tenue par `VOCABULAIRE` vs `AFFICHAGE_SEUL`.
"""
from wama.common.models import (JOB_AWAITING_RESOURCES, JOB_FAILURE, JOB_PENDING, JOB_RUNNING,
                                JOB_STALE, JOB_STATUS_ALIASES, JOB_SUCCESS,
                                PROCESS_STATUS_CHOICES)

#: État d'AFFICHAGE seul — aucune file ne le produit, mais l'UI le montre (item non encore soumis).
DRAFT = 'DRAFT'

#: valeur → (classe de badge, classe de texte, icône Font Awesome ou '')
#: ⚠ Les COULEURS, elles, restent dans le CSS (`app_modern.css`) : ici on nomme des CLASSES, pas
#: des teintes — sinon Python déciderait du thème.
_APPARENCE = {
    DRAFT:                  ('bg-secondary',        'text-white-50', ''),
    JOB_PENDING:            ('bg-secondary',        'text-white-50', ''),
    JOB_AWAITING_RESOURCES: ('bg-awaiting',         'text-awaiting', 'fa-hourglass-half'),
    JOB_RUNNING:            ('bg-warning text-dark', 'text-warning', 'fa-spinner fa-spin'),
    JOB_SUCCESS:            ('bg-success',          'text-success',  ''),
    JOB_FAILURE:            ('bg-danger',           'text-danger',   'fa-triangle-exclamation'),
    JOB_STALE:              ('bg-stale',            'text-stale',    'fa-rotate-right'),
}

#: Libellé d'affichage de `DRAFT` — les six autres viennent du vocabulaire, jamais d'ici.
_LIBELLE_DRAFT = 'Brouillon'


def states() -> list:
    """Les états AFFICHABLES, dans l'ordre : `DRAFT` puis les six du vocabulaire commun.

    Chaque entrée : `{'value', 'label', 'badge', 'text_class', 'icon'}`. Le LIBELLÉ vient de
    `PROCESS_STATUS_CHOICES` — il ne se réécrit pas ici, sans quoi on aurait refait une copie.
    """
    lignes = [(DRAFT, _LIBELLE_DRAFT)] + list(PROCESS_STATUS_CHOICES)
    out = []
    for valeur, libelle in lignes:
        badge, texte, icone = _APPARENCE.get(valeur, ('bg-secondary', 'text-white-50', ''))
        out.append({'value': valeur, 'label': str(libelle), 'badge': badge,
                    'text_class': texte, 'icon': icone})
    return out


def js_payload() -> dict:
    """Ce que le CLIENT reçoit — même source que les gabarits, donc rien à resynchroniser.

    Poussé par le processeur de contexte global (`accounts/context_processors.py`) et rendu par
    `base.html`, comme `WAMA_APP_CATALOG` l'est déjà : on emprunte le mécanisme en place, on n'en
    invente pas un second. Les ALIAS voyagent avec, faute de quoi le client ne saurait pas lire
    un état du monde Lab (`completed`) ni de Celery (`STARTED`).
    """
    lignes = states()
    return {
        'order': [e['value'] for e in lignes],
        'labels': {e['value']: e['label'] for e in lignes},
        'badges': {e['value']: e['badge'] for e in lignes},
        'texts': {e['value']: e['text_class'] for e in lignes},
        'icons': {e['value']: e['icon'] for e in lignes},
        'aliases': dict(JOB_STATUS_ALIASES),
    }
