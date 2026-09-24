"""Chaque ADRESSE de chaque app répond sans erreur serveur — `MEDIA_STORAGE_TIERING §8.6` D17.

POURQUOI (2026-09-22). L'endpoint `avatarizer:gallery_list` a levé `TypeError` à chaque appel
pendant dix jours : aucun gabarit ni JS ne l'appelait, donc rien ne le voyait. *Un endpoint sans
appelant ne se signale jamais — il faut l'appeler pour savoir qu'il est mort.* Aucun test du dépôt
ne parcourait les adresses : ce module le fait, pour TOUTES les apps, sans en nommer une.

Ce que le contrat exige : pas de réponse 5xx, pas d'exception. Un 302 (connexion), un 403 (droits)
ou un 405 (POST attendu) sont des RÉPONSES — le portier et la méthode font leur travail. Mais un
parcours où tout répondrait 302 ne mesurerait rien : la non-vacuité est vérifiée à part.

Précautions, parce qu'un parcours aveugle peut BLOQUER ou ÉCRIRE : il tourne dans la base de TEST
(une page d'index écrit — `auto_wrap_orphans`, `reconcile_orphaned_running`) ; aucune tâche Celery
n'est réellement envoyée ; un flux (`StreamingHttpResponse`) n'est jamais consommé ; le réseau a un
délai court.
"""
import socket
import time
from unittest import mock

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse


def _app_labels():
    """Les espaces d'adresses à parcourir : ceux dont le nom est une app de WAMA installée — hors
    jumelles aux vues COPIÉES (même règle que le contrat de suppression : `sandbox`)."""
    from django.apps import apps
    from wama.common.sandbox import twins_with_copied_views
    return ({c.label for c in apps.get_app_configs()
             if c.name.split('.')[0] in ('wama', 'wama_lab', 'wama_data')}
            - twins_with_copied_views())


def _parameterless_routes():
    """(chemin d'espace complet, nom) de chaque adresse NOMMÉE sans argument, dans un espace
    d'app. ⚠ Le chemin COMPLET, pas le dernier segment : une app peut être rangée dans un espace
    imbriqué (`lab:…`) — mesuré au premier passage, `reverse('cam_analyzer:…')` n'existe pas."""
    labels = _app_labels()
    found = []

    def walk(resolver, path):
        for p in resolver.url_patterns:
            if isinstance(p, URLResolver):
                walk(p, path + [p.namespace] if p.namespace else path)
            elif isinstance(p, URLPattern) and path and path[-1] in labels and p.name \
                    and not p.pattern.regex.groups:
                found.append((':'.join(path), p.name))
    walk(get_resolver(), [])
    return sorted(set(found))


def _routes_with_ids():
    """(chemin d'espace, nom, [(argument, 'int'|'uuid')]) des adresses dont TOUS les arguments
    sont des identifiants — la forme de ~260 des 317 adresses à argument (mesuré le 2026-09-22).
    Les formes rares (texte, slug, mélanges) restent hors de ce parcours, et sont COMPTÉES."""
    from django.urls.converters import IntConverter, UUIDConverter
    labels = _app_labels()
    found, other = [], []

    def walk(resolver, path):
        for p in resolver.url_patterns:
            if isinstance(p, URLResolver):
                walk(p, path + [p.namespace] if p.namespace else path)
            elif (isinstance(p, URLPattern) and path and path[-1] in labels and p.name
                    and p.pattern.converters):
                kinds = [(k, 'int' if isinstance(c, IntConverter) else
                          'uuid' if isinstance(c, UUIDConverter) else None)
                         for k, c in p.pattern.converters.items()]
                (found if all(kind for _k, kind in kinds) else other).append(
                    (':'.join(path), p.name, kinds))
    walk(get_resolver(), [])
    return found, other


class EveryEndpointAnswersTest(TestCase):

    #: Au-delà, une adresse est signalée comme LENTE dans la sortie (pas un échec : une mesure).
    SLOW_SECONDS = 2.0

    #: Routes dont un GET PEUT légitimement lancer une tâche — par NOM de route, chacune avec sa
    #: raison. La règle : un GET qui AGIT pour l'utilisateur (lancer un traitement) est interdit ;
    #: un GET qui CALCULE un dérivé ou ENTRETIENT est permis s'il est idempotent. Mesuré le
    #: 2026-09-22 : 4 vues de démarrage acceptaient un GET (describer, synthesizer, avatarizer,
    #: reader — les deux dernières étaient même APPELÉES en GET par leur propre JS) ; ces deux-ci
    #: restent, et disent pourquoi.
    GET_TASKS_ALLOWED = {
        'synthesizer:index': "téléchargement des voix de référence manquantes — entretien, "
                             "limité à 1×/heure par un drapeau de cache, idempotent",
        'transcriber:waveform_peaks': "calcul PARESSEUX d'un dérivé (forme d'onde) à la première "
                                      "lecture — un cache, idempotent",
    }

    def setUp(self):
        # Un dossier média JETABLE : une vue d'aperçu ou de miniature peut ÉCRIRE, et ce parcours
        # ne doit jamais toucher aux vrais médias.
        import shutil
        import tempfile

        from django.test import override_settings
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _account_for(self, namespace):
        """Le compte que la politique d'accès laisse entrer — lue par la brique, jamais supposée."""
        from wama.accounts.permissions import accessible
        from wama.common.services.nightly_tests import get_test_dev_user, get_test_user
        for account in (get_test_user(), get_test_dev_user()):
            if accessible(account, 'app', namespace):
                return account
        return get_test_dev_user()

    def _get(self, url):
        from django.db import transaction
        start = time.monotonic()
        try:
            # Un point de sauvegarde PAR requête : une vue qui casse la transaction (mesuré : une
            # écriture refusée par la base) ne doit pas faire tomber tout le reste du parcours.
            with transaction.atomic():
                response = self.client.get(url)
        except Exception as exc:                      # une exception non rattrapée = un 500
            return f'{type(exc).__name__}: {exc}'[:200], time.monotonic() - start
        if getattr(response, 'streaming', False):
            # Un flux ne se consomme jamais ici. ⚠ Le FERMER émet `request_finished`, sur lequel
            # Django ferme la connexion à la base : c'est ce qui a fait tomber le 2ᵉ passage, et
            # j'avais d'abord accusé la vue (`download_all` d'une jumelle) — elle n'y touchait pas.
            # On ferme comme le client de test le fait lui-même : branchement suspendu le temps.
            from django.core.signals import request_finished
            from django.db import close_old_connections
            request_finished.disconnect(close_old_connections)
            try:
                response.close()
            finally:
                request_finished.connect(close_old_connections)
        from django.db import connection
        raw = connection.connection
        if raw is None or getattr(raw, 'closed', False):
            # Mesuré au 2ᵉ passage : une adresse FERMAIT la connexion à la base pendant la
            # requête, et tout le parcours tombait au suivant. On la nomme au lieu de tomber.
            return 'FERME LA CONNEXION À LA BASE', time.monotonic() - start
        return response.status_code, time.monotonic() - start

    def _walk(self, calls):
        """Appelle chaque (espace, url) avec le bon compte ; rend (erreurs, lentes, trous, 2xx)."""
        errors, slow, declared_holes, answered = [], [], [], 0
        state_changing_gets = self.state_changing_gets = []
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(3)
        try:
            # Une tâche « envoyée » rend un identifiant de CHAÎNE, comme Celery : un faux qui rend un
            # objet a fait écrire `task_id=<objet>` en base au 1ᵉʳ passage.
            with mock.patch('celery.app.task.Task.apply_async',
                            return_value=mock.Mock(id='tache-de-test')) as dispatch:
                current = None
                for namespace, url in calls:
                    if namespace != current:
                        self.client.force_login(self._account_for(namespace.split(':')[-1]))
                        current = namespace
                    dispatch.reset_mock()
                    status, seconds = self._get(url)
                    if dispatch.called:
                        # Un GET qui LANCE un traitement : un préchargement de lien, un robot, un
                        # onglet rouvert le déclenchent, sans jeton CSRF. Mesuré au 1ᵉʳ passage
                        # sur `describer:start`. Un geste qui change l'état exige un POST.
                        state_changing_gets.append(url)
                    if seconds > self.SLOW_SECONDS:
                        slow.append(f'{url} {seconds:.1f}s')
                    if status == 501:
                        # « Non implémenté » DÉCLARÉ : le générateur marque ses trous ainsi plutôt
                        # que d'inventer (`tasks_gen` : « un trou marqué vaut mieux qu'une
                        # invention »). Une réponse, pas un plantage — comptée, pas en échec.
                        declared_holes.append(url)
                    elif not isinstance(status, int) or status >= 500:
                        errors.append(f'{url} → {status}')
                        if status == 'FERME LA CONNEXION À LA BASE':
                            break                     # la transaction du test est perdue
                    elif status < 300:
                        answered += 1
        finally:
            socket.setdefaulttimeout(previous_timeout)
        if slow:
            print(f'\n[adresses LENTES > {self.SLOW_SECONDS}s] ' + ' ; '.join(slow))
        if declared_holes:
            print(f'\n[trous DÉCLARÉS (501) : {len(declared_holes)}] ' + ' ; '.join(declared_holes))
        from django.urls import resolve
        forbidden = [u for u in state_changing_gets
                     if resolve(u.split('?')[0]).view_name not in self.GET_TASKS_ALLOWED]
        errors += [f'{u} → un GET LANCE une tâche (un geste qui change l’état exige un POST)'
                   for u in forbidden]
        return errors, answered

    def test_every_parameterless_get_answers_without_server_error(self):
        routes = _parameterless_routes()
        self.assertGreater(len(routes), 100, 'le parcours ne trouve presque rien : garde affaiblie')
        errors, answered = self._walk([(ns, reverse(f'{ns}:{name}')) for ns, name in routes])
        self.assertEqual([], errors, f'{len(errors)} adresse(s) en erreur serveur : '
                                     + ' ; '.join(errors))
        self.assertGreater(answered, len(routes) // 4,
                           f'seulement {answered}/{len(routes)} adresses ont RÉELLEMENT répondu '
                           '(2xx) — le parcours ne mesure presque rien')

    def _witnesses(self, namespace):
        """Identifiants à essayer pour cet espace : un INEXISTANT (doit donner 404, jamais 500),
        puis une card et un lot témoins APPARTENANT au compte connecté — leurs fichiers sont
        volontairement ABSENTS du disque, comme les « référencés mais absents » réels."""
        from wama.common.tests_queue_delete_contract import _instance, _lot_de
        from wama.common.utils.batch_common import batch_model_for
        from wama.common.utils.preview_registry import PreviewRegistry
        ids = [987654]
        model = PreviewRegistry.get_model(namespace.split(':')[-1])
        if model is not None:
            account = self._account_for(namespace.split(':')[-1])
            try:
                ids.append(_instance(model, account).pk)
                if batch_model_for(model) is not None:
                    ids.append(_lot_de(model, account, 1)[0].pk)
            except Exception as exc:
                # La fabrique générique ne connaît aucune app, et c'est voulu : un modèle qui
                # exige une valeur de vocabulaire (mesuré : la médiathèque, `asset_type`) n'a
                # pas de témoin. On le NOMME au lieu de tomber — l'identifiant inexistant, lui,
                # est quand même essayé.
                self.no_witness.append(f'{namespace} ({type(exc).__name__})')
        return ids

    def test_every_route_with_an_id_answers_without_server_error(self):
        import uuid
        routes, other = _routes_with_ids()
        self.assertGreater(len(routes), 200, 'le parcours ne trouve presque rien : garde affaiblie')
        calls, witnesses, self.no_witness = [], {}, []
        for namespace, name, kinds in routes:
            if namespace not in witnesses:
                witnesses[namespace] = self._witnesses(namespace)
            for value in witnesses[namespace]:
                kwargs = {k: (value if kind == 'int' else uuid.UUID(int=value)) for k, kind in kinds}
                calls.append((namespace, reverse(f'{namespace}:{name}', kwargs=kwargs)))
        errors, answered = self._walk(calls)
        print(f'\n[{len(calls)} appels sur {len(routes)} adresses à identifiant ; '
              f'{len(other)} de forme rare hors parcours ; sans témoin : '
              f'{", ".join(self.no_witness) or "aucun"}]')
        self.assertEqual([], errors, f'{len(errors)} adresse(s) en erreur serveur : '
                                     + ' ; '.join(errors))


class ItemEditRouteConventionTest(TestCase):
    """The route that saves ONE element's settings follows `WAMA_APP_CONVENTIONS §3.1` :
    `settings/<int:pk>/`, named `update_settings` (2026-09-24).

    Measured that day: one gesture, four names across the park (`update`, `update_options`,
    `update_settings`, `save_settings`) and five paths — the generator needed an alias table to
    recognise them, and every twin inherited its source's spelling. Seven apps were aligned; the
    rest are DECLARED below with their reason. Walks every app, names none in the rule itself.
    """

    CANONICAL_NAME = 'update_settings'
    CANONICAL_PATH = 'settings/<int:pk>/'

    #: Apps still on another name — each with its reason. An entry that has become conforming
    #: fails the test: the exemption must go with the debt.
    NAME_PENDING = {
        'transcriber': "`save_settings` — l'app est en chantier dans une autre session (24/09)",
        'anonymizer': "`save_media_settings/` SANS identifiant (le `media_id` est posté) — et son "
                      "`update_settings` est une route GLOBALE sans pk, qui prendrait le nom "
                      "canonique : la renommer d'abord (right_panel.js, update.js)",
    }
    #: Apps on the canonical name but another path — each with its reason.
    PATH_EXCEPTIONS = {
        'imager': "`settings/<int:generation_id>/` est la LECTURE des réglages (GET) : l'écriture "
                  "garde son suffixe `save/` tant que les deux vues ne sont pas fusionnées",
    }

    def _item_edit_routes(self):
        """{app: (name, route)} for every app declaring the item-edit gesture under one of its
        measured names with an integer id. Sandbox twins (`<app>_NN`) are left out: generated
        from their source's manifest, they follow it, and a fresh clone has none."""
        from wama.common.manifests.codegen.urls_gen import route_variants
        from wama.common.sandbox import LABEL_RE
        labels = {label for label in _app_labels() if not LABEL_RE.match(label)}
        names = set(route_variants('update'))
        found = {}

        def walk(resolver, path):
            for p in resolver.url_patterns:
                if isinstance(p, URLResolver):
                    walk(p, path + [p.namespace] if p.namespace else path)
                elif (isinstance(p, URLPattern) and path and path[-1] in labels
                        and p.name in names and p.pattern.converters):
                    found[path[-1]] = (p.name, str(p.pattern))
        walk(get_resolver(), [])
        return found

    def test_the_item_settings_route_has_the_conventional_name_and_path(self):
        routes = self._item_edit_routes()
        wrong = []
        for app, (name, route) in sorted(routes.items()):
            if app in self.NAME_PENDING:
                continue
            if name != self.CANONICAL_NAME:
                wrong.append(f'{app}: nom `{name}` (attendu `{self.CANONICAL_NAME}`)')
            elif route != self.CANONICAL_PATH and app not in self.PATH_EXCEPTIONS:
                wrong.append(f'{app}: chemin `{route}` (attendu `{self.CANONICAL_PATH}`)')
        self.assertEqual([], wrong)
        conforming = [a for a, (n, r) in routes.items() if n == self.CANONICAL_NAME]
        self.assertGreaterEqual(len(conforming), 8, f'only {sorted(conforming)} — guard weakened')

    def test_every_exemption_is_still_needed(self):
        routes = self._item_edit_routes()
        stale = [app for app in self.NAME_PENDING
                 if routes.get(app, ('',))[0] == self.CANONICAL_NAME]
        stale += [app for app in self.PATH_EXCEPTIONS
                  if routes.get(app, ('', ''))[1] == self.CANONICAL_PATH]
        self.assertEqual([], stale, 'these apps now conform: remove their exemption')

    def test_the_grid_criterion_agrees_with_the_resolved_routes(self):
        """`settings_route` (conformity grid) reads `urls.py` as text; this walk resolves the
        URLconf. Two instruments on one rule must give the same verdict per app."""
        from wama.common.services.conformity_checker import _AppFiles, _settings_route
        disagree = []
        for app, (name, route) in sorted(self._item_edit_routes().items()):
            state, _proof = _settings_route(_AppFiles(app))
            expected = (True if (name, route) == (self.CANONICAL_NAME, self.CANONICAL_PATH)
                        else 'partial' if name == self.CANONICAL_NAME else False)
            if state != expected:
                disagree.append(f'{app}: grid {state!r}, walk {expected!r}')
        self.assertEqual([], disagree)
