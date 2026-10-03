"""
Captation GÉNÉRIQUE des gestes utilisateur vers `RunOutcome`. Doc : `WAMA_MEMORY.md §7bis`.

LE PROBLÈME QU'ELLE RÉSOUT. `RunOutcome` est le préalable de toute auto-amélioration, mais au
2026-08-20 il ne comptait **1 seule ligne** : la captation n'existait qu'en 2 points
(`task_skeleton` pour produit/echec, `transcriber/views.py` pour corrige), et `telecharge`,
`relance`, `supprime` n'avaient **aucun** appelant — soit la moitié du vocabulaire, et
précisément les signaux qui portent la saillance.

POURQUOI UN MIDDLEWARE ET PAS UNE LIGNE PAR VUE. Câbler à la main demandait ~30 retouches dans
10 apps, qu'il aurait fallu refaire à chaque app ajoutée — et une app oubliée aurait creusé un
trou SILENCIEUX dans le journal. Or les routes de file sont d'une régularité remarquable
(vérifié sur 10 apps) : `download*`, `start`, `restart`, `delete`, toutes avec un `pk`. Un
middleware qui lit `resolver_match` capte donc tout le monde, y compris les apps futures, sans
qu'aucune app n'écrive une ligne.

POURQUOI PAS DES SIGNAUX `post_delete`. Un signal capterait AUSSI les suppressions en cascade et
les purges de maintenance — or `RunOutcome` enregistre des **gestes d'utilisateur**, pas des
mouvements de base. Passer par la requête HTTP rend la captation juste par construction : s'il
n'y a pas eu de requête, il n'y a pas eu de geste.

⚠ BEST-EFFORT ABSOLU. Un signal manqué est un signal manqué ; une exception levée ici casserait
un téléchargement ou une suppression qui, eux, ont réussi. Même précaution que `run_outcome`
lui-même et que le squelette de tâche.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: `url_name` → signal. Les préfixes `*_all` sont EXCLUS volontairement : ils n'ont pas de `pk`,
#: donc aucun objet à rattacher. Les capter demanderait de rejouer la sélection côté serveur —
#: à faire le jour où on en aura besoin, pas en devinant maintenant.
SIGNAL_PAR_ROUTE = {
    'download': 'telecharge',
    'download_srt': 'telecharge',
    'download_media': 'telecharge',      # anonymizer — seule app hors convention
    'delete': 'supprime',
    'delete_media': 'supprime',
    'start': None,                       # None = à décider (1re exécution ou relance) — cf. _signal_start
    'restart': None,
    # Réglages d'un élément enregistrés par un COLLABORATEUR (2026-10-03, E4 de
    # WAMA_COLLABORATION : « le dernier enregistrement gagne, TRACÉ ») — la route de convention
    # `update_settings` (WAMA_APP_CONVENTIONS §3.1). Noté en POST seulement, et seulement quand
    # l'auteur n'est pas le propriétaire : ce sont les gestes partagés qu'il faut pouvoir attribuer.
    'update_settings': 'regle',
}

#: Méthodes qui portent un geste. Un GET sur `download` en est un ; un GET sur `start` n'existe
#: pas (POST only, cf. le pattern anti-race de AGENTS.md).
METHODES = ('GET', 'POST')


def app_of(match) -> str:
    """L'app d'une route résolue, sous le nom que connaissent les registres (`DetailRegistry`).

    ⚠ Mesuré le 2026-10-03 (sonde) : reader, composer et transcriber déclarent `app_name =
    'wama.reader'` (nom POINTÉ) alors que leur espace de noms est `reader`. Lire `app_name` d'abord
    rendait une app inconnue du registre : AUCUN signal n'était capté pour ces trois apps —
    téléchargement, suppression, relance — sans que rien ne le dise. On prend donc le premier nom
    que le registre connaît : `app_name`, l'espace de noms, puis le dernier segment pointé."""
    from .utils.detail_registry import DetailRegistry
    raw = (match.app_name or '', match.namespace or '')
    for name in (*raw, raw[0].rsplit('.', 1)[-1]):
        if name and DetailRegistry.get(name):
            return name
    return raw[1] or raw[0].rsplit('.', 1)[-1]


class RunOutcomeCaptureMiddleware:
    """Enregistre telecharge / supprime / relance depuis les routes de file, sans code par app."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._capter(request, response)
        except Exception:
            # Jamais de remontée : la réponse de l'utilisateur prime sur la télémétrie.
            logger.debug('[run_outcome_capture] captation impossible', exc_info=True)
        try:
            self._schedule_batch(request, response)
        except Exception:
            logger.debug('[run_outcome_capture] programmation du lot impossible', exc_info=True)
        return response

    @staticmethod
    def _schedule_batch(request, response):
        """Un FICHIER BATCH peut programmer ses lignes (`--when`, `--at` ; calendrier, étape 3).

        Même lecture générique que les gestes, pour la même raison : les onze apps créent leur lot
        par un POST qui envoie `batch_file` et rend `batch_id` — mesuré, sous QUATRE noms de route
        (`batch_create`, `audio_batch_create`, `batch_import`, `import_batch`). C'est ce contrat
        de données, pas le nom de la route, qui déclenche.
        """
        if request.method != 'POST' or response.status_code >= 400:
            return
        if 'batch_file' not in getattr(request, 'FILES', {}):
            return
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return
        if 'json' not in (response.get('Content-Type') or ''):
            return
        import json
        batch_id = (json.loads(response.content or b'{}') or {}).get('batch_id')
        match = getattr(request, 'resolver_match', None)
        app = match and app_of(match)          # même lecture que les gestes (noms pointés)
        if not batch_id or not app:
            return
        from .services.scheduled_actions import schedule_from_batch
        schedule_from_batch(request.user, app, match.url_name, batch_id)

    def _capter(self, request, response):
        match = getattr(request, 'resolver_match', None)
        if match is None or request.method not in METHODES:
            return
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return
        # Seules les réponses ABOUTIES comptent : un 404 ou un 403 n'est pas un geste réussi, et
        # l'enregistrer ferait croire à un téléchargement qui n'a pas eu lieu.
        if response.status_code >= 400:
            return

        url_name = match.url_name or ''
        if url_name not in SIGNAL_PAR_ROUTE:
            return

        app = app_of(match)
        pk = match.kwargs.get('pk') or match.kwargs.get('id')
        if not app or pk is None:
            return

        from .utils.detail_registry import DetailRegistry

        entree = DetailRegistry.get(app)
        if not entree:
            return          # app sans inspecteur : rien à quoi rattacher le geste
        model = entree['model']

        # ⚠ Une suppression a DÉJÀ eu lieu quand on arrive ici : l'objet n'existe plus. On
        # enregistre donc à partir du type et de la pk, sans le relire.
        signal = SIGNAL_PAR_ROUTE[url_name]
        if signal == 'supprime':
            self._ecrire_sans_instance(app, model.__name__, int(pk), 'supprime', request.user)
            return

        instance = model.objects.filter(pk=pk).first()
        if instance is None:
            return
        if signal == 'regle':
            if request.method != 'POST' or getattr(instance, 'user_id', None) == request.user.pk:
                return
            from .services.run_outcome import record
            record(app, instance, 'regle', user=request.user,
                   detail={'collaborator': True, 'owner_id': instance.user_id})
            return
        if url_name in ('start', 'restart'):
            # Le ▶ lance MAINTENANT : une programmation de cet élément n'a plus d'objet
            # (décision de Fabien, 2026-09-28 : sans confirmation). Même lecture de route que
            # les signaux — aucune app n'a de ligne à écrire. Filet : `dispatch_due` ne relance
            # jamais un élément lancé depuis sa programmation.
            from .services.scheduled_actions import cancel_for_item
            cancel_for_item(app, pk)
        if signal is None:
            signal = self._signal_start(app, model.__name__, int(pk), request.user)
            if signal is None:
                return      # 1re exécution : c'est `task_skeleton` qui écrira 'produit'

        from .services.run_outcome import record
        record(app, instance, signal, user=request.user)

    @staticmethod
    def _signal_start(app, object_type, pk, user):
        """
        Un `start` n'est une RELANCE que si l'objet a déjà produit quelque chose.

        Sans ce test, la première exécution serait comptée comme un échec implicite du
        précédent — alors qu'il n'y avait pas de précédent. La distinction compte : `relance`
        pèse dans la saillance parce qu'elle dit « le résultat n'a pas suffi ».
        """
        from .models import RunOutcome
        deja = RunOutcome.objects.filter(app=app, object_type=object_type, object_id=pk,
                                         signal__in=('produit', 'echec')).exists()
        return 'relance' if deja else None

    @staticmethod
    def _ecrire_sans_instance(app, object_type, pk, signal, user):
        """Écrit un signal dont l'objet n'existe plus (suppression). Best-effort."""
        try:
            from .models import RunOutcome
            RunOutcome.objects.create(app=app, object_type=object_type, object_id=pk,
                                      user=user, signal=signal, model_keys=[], detail={})
        except Exception:
            logger.debug('[run_outcome_capture] écriture %s impossible', signal, exc_info=True)
