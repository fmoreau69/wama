"""SUPPRIMER une card de lot — sans rechargement de la page, le serveur dit ce que devient le lot.

POURQUOI (relevé par Fabien le 2026-09-14). Supprimer une card d'un lot de deux « fonctionnait »,
mais le lot restait affiché jusqu'au rechargement manuel. Cause mesurée le 2026-09-15 : un TROU
DE LA ROUTE. Le 2026-08-23 (`145e738f`), la brique `queue-actions.js` a cessé de recharger la
page après chaque suppression pour ne plus le faire que si la réponse portait `batch_changed` —
un champ que 8 vues sur 10 écrivaient à la main, chacune à sa façon, et que rien ne vérifiait.
Le converter et l'imager ne l'écrivaient pas : leur lot restait figé, sans aucune erreur.

⚠ La 1ʳᵉ correction (14/09) ajoutait le champ dans ces deux vues : elle bouchait le trou app par
app au lieu de le fermer au commun, et le test qui l'accompagnait exigeait que chaque vue écrive
la clé à la main — il protégeait la duplication au lieu du comportement.

Correction AU COMMUN (validée par Fabien le 2026-09-15) :
  • serveur — `batch_common.batch_snapshot` / `batch_state` : la vue dit ce que DEVIENT le lot,
    sans rechercher son lot à la main ; `is_batch_child` : la position de la card dans la file,
    pour les vues `card_html` qui rendent une card seule ;
  • navigateur — `queue-actions.js` met la file à jour SANS RECHARGEMENT DE LA PAGE : lot vidé
    retiré, lot réduit à une card redevenu card simple (redemandée au serveur), card mère aux
    compteurs à jour. Un rechargement ramenait l'utilisateur en haut de la file.

Ce module éprouve le COMPORTEMENT côté serveur, et sur CHAQUE app. Le geste à l'écran — la page
ne se recharge pas, l'utilisateur garde sa place — est éprouvé par le scénario nocturne
`<app>.delete_from_batch` (`common/services/ui_smoke.py`).
"""
import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import models
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from wama.common.utils.batch_common import (batch_model_for, batch_snapshot, batch_state,
                                            is_batch_child)

User = get_user_model()


# ── Fabrique de témoins, sans rien connaître d'aucune app ─────────────────────────────────────

def _instance(modele, user, **valeurs):
    """Une ligne MINIMALE de `modele` : chaque champ obligatoire sans défaut reçoit une valeur neutre.

    Écrit pour que le test couvre TOUTES les apps sans une fabrique par app : une app de plus
    est couverte sans y toucher. Un champ que cette règle ne sait pas remplir (FK obligatoire
    vers autre chose que l'utilisateur) fait échouer la création — et l'échec nomme le champ.
    """
    for f in modele._meta.concrete_fields:
        if f.name in valeurs or f.primary_key or f.null or f.has_default():
            continue
        if getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
            continue
        if isinstance(f, models.ForeignKey):
            if f.related_model is User:
                valeurs[f.name] = user
        elif isinstance(f, models.FileField):
            valeurs[f.name] = f'temoin/{f.name}.txt'
        elif isinstance(f, (models.IntegerField, models.FloatField, models.DecimalField)):
            valeurs[f.name] = 0
        elif isinstance(f, models.BooleanField):
            valeurs[f.name] = False
        elif isinstance(f, models.DateTimeField):
            valeurs[f.name] = timezone.now()
        elif isinstance(f, models.JSONField):
            valeurs[f.name] = {}
    if any(f.name == 'user' for f in modele._meta.concrete_fields):
        valeurs.setdefault('user', user)
    return modele.objects.create(**valeurs)


def _lot_de(modele_element, user, n):
    """Un lot de `n` éléments de `modele_element`, rattachés sous la forme que l'app déclare."""
    modele_lot = batch_model_for(modele_element)
    lot = _instance(modele_lot, user, total=n)
    elements = []
    for i in range(n):
        el = _instance(modele_element, user)
        if any(f.name == 'batch' for f in modele_element._meta.concrete_fields):
            el.batch = lot                                   # forme à FK DIRECTE
            el.save(update_fields=['batch'])
        else:                                                # forme par modèle de LIAISON
            rel = next(r for r in modele_element._meta.related_objects
                       if r.one_to_one and any(f.name == 'batch'
                                               for f in r.related_model._meta.concrete_fields))
            extra = {'batch': lot, rel.field.name: el}
            if any(f.name == 'row_index' for f in rel.related_model._meta.concrete_fields):
                extra['row_index'] = i
            _instance(rel.related_model, user, **extra)
        elements.append(el)
    lot.refresh_from_db()
    return lot, elements


# ── La brique serveur ─────────────────────────────────────────────────────────────────────────

class EtatDuLotApresSuppressionTest(TestCase):
    """`batch_snapshot` / `batch_state` / `is_batch_child` — les DEUX formes de rattachement."""

    def setUp(self):
        self.u = User.objects.create_user('lot_suppression', password='x')

    def _lot_converter(self, n, statuts=()):
        from wama.converter.models import ConversionJob
        lot, jobs = _lot_de(ConversionJob, self.u, n)
        for job, statut in zip(jobs, statuts):
            job.status = statut
            job.save(update_fields=['status'])
        return lot, jobs

    def test_forme_directe_le_lot_passe_de_trois_a_deux_puis_un_puis_disparait(self):
        from wama.converter.models import ConversionJob
        lot, jobs = self._lot_converter(3)
        # Id gardé À PART : `lot` est l'instance même que `batch_sync` supprime au dernier
        # retrait (sa clé passe alors à None) — la raison exacte pour laquelle `batch_snapshot`
        # garde une référence et non l'instance.
        modele_lot, lot_id = type(lot), lot.pk
        attendus = [2, 1, 0]
        for job, total in zip(jobs, attendus):
            instantane = batch_snapshot(job)
            job.delete()
            etat = batch_state(instantane, ConversionJob)
            self.assertEqual((etat['id'], etat['total']), (lot_id, total))
        self.assertFalse(modele_lot.objects.filter(pk=lot_id).exists(),
                         "un lot vidé est supprimé par `batch_sync`")

    def test_forme_par_liaison_le_lot_de_deux_redevient_unitaire(self):
        from wama.imager.models import ImageGeneration
        lot, gens = _lot_de(ImageGeneration, self.u, 2)
        instantane = batch_snapshot(gens[0])
        gens[0].delete()
        self.assertEqual(batch_state(instantane, ImageGeneration)['total'], 1)

    def test_les_compteurs_sont_ceux_de_la_card_mere(self):
        from wama.converter.models import ConversionJob
        _lot, jobs = self._lot_converter(3, statuts=('SUCCESS', 'FAILURE', 'PENDING'))
        instantane = batch_snapshot(jobs[2])
        jobs[2].delete()
        etat = batch_state(instantane, ConversionJob)
        self.assertEqual((etat['success_count'], etat['failure_count'], etat['running_count'],
                          etat['has_success']), (1, 1, 0, True))

    def test_un_element_hors_lot_ne_rend_aucun_etat(self):
        from wama.converter.models import ConversionJob
        seul = _instance(ConversionJob, self.u)
        self.assertIsNone(batch_snapshot(seul))
        self.assertIsNone(batch_state(None, ConversionJob))

    def test_une_fille_de_lot_est_rendue_en_fille_une_card_de_lot_unitaire_non(self):
        from wama.imager.models import ImageGeneration
        from wama.converter.models import ConversionJob
        for modele in (ConversionJob, ImageGeneration):
            with self.subTest(forme=modele.__name__):
                _lot, deux = _lot_de(modele, self.u, 2)
                _lot1, un = _lot_de(modele, self.u, 1)
                self.assertTrue(is_batch_child(deux[0]))
                self.assertFalse(is_batch_child(un[0]))
                self.assertFalse(is_batch_child(_instance(modele, self.u)))


# ── Chaque app, par sa VUE ────────────────────────────────────────────────────────────────────

def _surfaces():
    """(surface, route de suppression, route de card) pour toute app du catalogue exposant `<app>:delete`.

    ⚠ Jumelles de bac à sable : seules celles dont les VUES sont GÉNÉRÉES (`substituted.views`
    au registre `sandbox_apps.json`) sont tenues au contrat. Les autres portent une COPIE des
    vues de leur app source figée à leur création (étape S1) — elles ne suivent pas le code
    réel par construction, et les exiger ici reviendrait à les éditer à la main.
    """
    from wama.common.app_registry import APP_CATALOG
    from wama.common.sandbox import twins_with_copied_views

    copiees = twins_with_copied_views()
    sortie = []
    for app in APP_CATALOG:
        if app in copiees:
            continue
        try:
            reverse(f'{app}:delete', args=[1])
        except NoReverseMatch:
            continue
        sortie.append((app, f'{app}:delete', f'{app}:card_html'))
    # La seule app à DEUX familles de routes (domaine `audio`, `route_prefix` déclaré).
    sortie.append(('audio_enhancer', 'enhancer:audio_delete', 'enhancer:audio_card_html'))
    return sortie


#: Ce qui distingue une card rendue EN FILLE de lot. Neuf gabarits sur dix portent la classe
#: commune ; le transcriber ne change que le titre de son bouton ⧉.
MARQUE_DE_FILLE = {'transcriber': 'dans le batch'}


class SuppressionDansChaqueAppTest(TestCase):
    """Le geste complet, vue par vue : lot de deux → une card simple → plus de lot."""

    def _compte_pour(self, surface):
        """Le compte qui FRANCHIT le portier de la surface — jamais un superutilisateur.

        Même routage que le filet nocturne (`ui_smoke._test_session_key`) : le compte standard
        pour les apps, le compte développeur DÉDIÉ pour une jumelle de bac à sable (dev-gated
        par conception, `sandbox.py`). Mesuré : `converter_01` rendait 302 au compte standard.
        """
        from wama.common.app_registry import APP_CATALOG
        from wama.common.services.nightly_tests import get_test_dev_user, get_test_user
        compte = (get_test_dev_user() if (APP_CATALOG.get(surface) or {}).get('generated_from')
                  else get_test_user())
        self.client.force_login(compte)
        return compte

    def test_le_parc_est_mesure(self):
        """Non-vacuité : sans les dix apps de file, les sous-tests ne garderaient rien."""
        self.assertGreaterEqual(len(_surfaces()), 11, [s for s, *_ in _surfaces()])

    def test_card_html_renders_the_card_of_the_element_it_is_asked_for(self):
        """Contract 5 (`WAMA_VERIFICATION §8`, 2026-09-26): the card re-rendered by the server —
        what the JS asks for instead of reloading the page — is a REAL card for that element
        (its id on it), for every app. It was checked for the converter alone."""
        from wama.common.utils.preview_registry import PreviewRegistry
        for surface, _route_suppression, route_card in _surfaces():
            with self.subTest(surface=surface):
                compte = self._compte_pour(surface)
                element = _instance(PreviewRegistry.get_model(surface), compte)
                r = self.client.get(reverse(route_card, args=[element.pk]))
                self.assertEqual(200, r.status_code, r.content[:200])
                html = r.content.decode()
                self.assertRegex(html, rf'data-(?:id|job-id|item-id)="{element.pk}"',
                                 'la card rendue ne porte pas l\'identifiant de son élément')

    def test_supprimer_une_card_d_un_lot_de_deux_dit_que_le_lot_redevient_une_card_simple(self):
        from wama.common.utils.preview_registry import PreviewRegistry
        for surface, route_suppression, route_card in _surfaces():
            with self.subTest(surface=surface):
                compte = self._compte_pour(surface)
                modele = PreviewRegistry.get_model(surface)
                self.assertIsNotNone(modele, f"aucun modèle d'élément déclaré pour {surface}")
                lot, (partant, restant) = _lot_de(modele, compte, 2)
                marque = MARQUE_DE_FILLE.get(surface, 'wcv3--batch-child')

                avant = self.client.get(reverse(route_card, args=[restant.pk]))
                self.assertEqual(avant.status_code, 200)
                self.assertIn(marque, avant.content.decode(),
                              "tant que le lot a deux cards, la card se rend EN FILLE")

                r = self.client.post(reverse(route_suppression, args=[partant.pk]),
                                     data='{}', content_type='application/json')
                self.assertEqual(r.status_code, 200, r.content[:300])
                etat = json.loads(r.content).get('batch')
                self.assertEqual((etat or {}).get('id'), lot.pk,
                                 "la réponse doit dire le lot de l'élément supprimé")
                self.assertEqual(etat['total'], 1)

                apres = self.client.get(reverse(route_card, args=[restant.pk]))
                self.assertNotIn(marque, apres.content.decode(),
                                 "lot réduit à une card : elle se rend en card SIMPLE")

                r = self.client.post(reverse(route_suppression, args=[restant.pk]),
                                     data='{}', content_type='application/json')
                self.assertEqual(json.loads(r.content)['batch']['total'], 0,
                                 "dernière card : le lot a disparu")


class DeletingACardRemovesTheFilesItOwnsTest(TestCase):
    """Le SORT DU FICHIER, sur chaque app : ce qui vit chez l'app part, ce qui est référencé reste.

    Né le 2026-09-22. Les tests ci-dessus éprouvent l'ÉTAT DU LOT après suppression, jamais ce
    que devient le fichier — et c'est dans cet angle mort qu'une règle de propriété restée à
    l'ancien domicile (`<app>/<uid>/…`, avant la bascule du 12/09) a laissé chaque sortie migrée
    sur le disque, pour toujours, sans une erreur. *Une garde qui refuse à tort ne plante
    jamais : elle fuit.*

    Deux témoins par app, construits sans rien connaître d'elle :
      • « possédé » — chaque champ fichier pointe DANS le domicile de l'app (`app_media_dir`) ;
      • « référencé » — chaque champ pointe dans l'espace de l'utilisateur (`users/<u>/temp/`),
        comme une source envoyée depuis le gestionnaire de fichiers.
    ⚠ RÉÉCRIT LE 2026-10-01 (décision de Fabien du 30/09, `MEDIA_STORAGE_TIERING` D34) : retirer
    une card ne SUPPRIME plus rien, elle LIBÈRE. Le premier témoin reste sur le disque ET devient
    un fichier libéré (une ligne `ReleasedFile` : l'utilisateur en sera prévenu) ; le second reste
    sur le disque SANS être signalé — il a son propre maître. La règle de propriété garde donc tout
    son poids : c'est elle qui décide de PRÉVENIR, et un témoin possédé non signalé serait la même
    fuite muette qu'avant, déplacée du disque à l'annonce.
    """

    _account_for = SuppressionDansChaqueAppTest._compte_pour

    def setUp(self):
        import shutil
        import tempfile

        from django.test import override_settings

        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _witness(self, model, account, folder, el=None):
        """Un élément dont CHAQUE champ fichier désigne un vrai fichier sous `folder` (créé, ou
        l'élément `el` fourni — celui d'un lot, par exemple)."""
        el = el or _instance(model, account)
        files = []
        for f in model._meta.concrete_fields:
            if not isinstance(f, models.FileField):
                continue
            rel = f'{folder}/temoin_{el.pk}_{f.name}.bin'
            path = Path(self.tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x')
            setattr(el, f.name, rel)
            files.append(path)
        el.save()
        return el, files

    def _delete_card(self, delete_route, el):
        r = self.client.post(reverse(delete_route, args=[el.pk]),
                             data='{}', content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content[:300])

    def _fleet(self):
        """(surface, route, compte, modèle, domicile de l'app) pour chaque app de file."""
        from wama.common.utils.media_paths import app_media_dir
        from wama.common.utils.preview_registry import PreviewRegistry
        for surface, delete_route, _card_route in _surfaces():
            account = self._account_for(surface)
            model = PreviewRegistry.get_model(surface)
            self.assertIsNotNone(model, f"aucun modèle d'élément déclaré pour {surface}")
            # Le domicile est celui de l'APP DU MODÈLE — une surface peut en partager un (une
            # famille de routes d'une app range sous le nom de l'app, pas sous celui de la route).
            yield (surface, delete_route, account, model,
                   app_media_dir(model._meta.app_label, account.id, 'output'))

    def _not_released(self, files):
        """Les témoins qu'aucune ligne `ReleasedFile` ne signale (donc dont personne ne sera prévenu)."""
        from wama.common.models import ReleasedFile
        rels = {p: p.relative_to(self.tmp).as_posix() for p in files}
        noted = set(ReleasedFile.objects.filter(path__in=list(rels.values()))
                    .values_list('path', flat=True))
        return [p.name for p, rel in rels.items() if rel not in noted]

    def _lost(self, files):
        return [p.name for p in files if not p.exists()]

    def test_each_app_releases_the_files_it_owns(self):
        for surface, route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                el, files = self._witness(model, account, app_home)
                if not files:
                    continue                      # élément sans fichier : rien à éprouver
                self._delete_card(route, el)
                self.assertEqual([], self._lost(files), 'retirer la card a SUPPRIMÉ ses fichiers : '
                                                        'la suppression est un geste de l’utilisateur')
                self.assertEqual([], self._not_released(files),
                                 'les fichiers de l’app ne sont pas signalés comme libérés — la règle '
                                 'de propriété ne les reconnaît pas comme siens')

    # ── Les TROIS gestes qui suppriment, et ce qu'aucun ne doit détruire ─────────────────────────
    #
    # ⚠ Ces tests REMPLACENT, le 2026-09-22, un budget de « 10 apps qui détruisent un fichier
    # référencé » posé la veille. Revérifié à la demande de Fabien (« ça m'étonne… a-t-on cassé
    # quelque chose, ou pas été au bout du chantier ? ») : RIEN n'a été cassé. `safe_delete_file`
    # n'a jamais regardé OÙ vit le fichier — une seule version depuis le 2026-03-10, qui ne compte
    # que les autres lignes du même modèle. La garde « jamais hors de chez soi » est née le 31/08
    # d'un audit du SEUL converter (et de sa jumelle, par le générateur) et n'a jamais été portée
    # aux autres apps. Deux pointeurs vivants en font une perte réelle : `text_file` (synthesizer,
    # import d'un fichier déjà sur le serveur) et `audio_input` (avatarizer, lot `-i`).

    def _route_for(self, delete_route, canonical, args):
        """URL du geste `canonical` pour la même app que `delete_route`, '' si l'app ne l'offre pas.

        Les orthographes viennent de `route_variants` (la table qui sert déjà l'API de
        l'assistant) ; la famille de routes (`audio_`) se lit sur la route de suppression. Rien
        n'est supposé d'une app en particulier.
        """
        from django.urls import NoReverseMatch
        from wama.common.manifests.codegen.urls_gen import route_variants
        namespace, name = delete_route.split(':')
        family = name[:-len('delete')]
        for variant in route_variants(canonical):
            try:
                return reverse(f'{namespace}:{family}{variant}', args=args)
            except NoReverseMatch:
                continue
        return ''

    def _post(self, url):
        r = self.client.post(url, data='{}', content_type='application/json')
        self.assertLess(r.status_code, 400, f'{url} : {r.status_code} {r.content[:300]}')

    def _by_gesture(self, surface, route, account, model, folder):
        """(geste, fichiers témoins) après avoir joué chaque geste de suppression offert."""
        el, files = self._witness(model, account, folder)
        if not files:
            return []
        self._delete_card(route, el)
        played = [('delete', files)]

        el, files = self._witness(model, account, folder)
        url = self._route_for(route, 'clear_all', [])
        if url:
            self._post(url)
            played.append(('clear_all', files))

        batch, (el,) = _lot_de(model, account, 1)
        el, files = self._witness(model, account, folder, el=el)
        url = self._route_for(route, 'batch_delete', [batch.pk])
        if url:
            self._post(url)
            played.append(('batch_delete', files))
        return played

    def test_no_deletion_gesture_destroys_a_file_the_card_only_references(self):
        for surface, route, account, model, _app_home in self._fleet():
            for gesture, files in self._by_gesture(surface, route, account, model,
                                                 f'users/{account.id}/temp'):
                with self.subTest(surface=surface, gesture=gesture):
                    self.assertEqual([], self._lost(files), f'« {gesture} » a détruit des fichiers '
                                     'de l’utilisateur que la card ne faisait que RÉFÉRENCER')
                    self.assertEqual(sorted(p.name for p in files), sorted(self._not_released(files)),
                                     f'« {gesture} » signale comme libéré un fichier que la card ne '
                                     'faisait que RÉFÉRENCER — il a son propre maître')

    def test_every_deletion_gesture_releases_the_files_the_app_owns(self):
        for surface, route, account, model, app_home in self._fleet():
            for gesture, files in self._by_gesture(surface, route, account, model, app_home):
                with self.subTest(surface=surface, gesture=gesture):
                    self.assertEqual([], self._lost(files), f'« {gesture} » a SUPPRIMÉ des fichiers '
                                                            'au lieu de les libérer')
                    self.assertEqual([], self._not_released(files), f'« {gesture} » n’a pas signalé '
                                     'les fichiers de l’app qu’il vient de rendre orphelins')

    def test_every_app_offers_the_three_deletion_gestures(self):
        """Non-vacuité : un geste introuvable ferait sauter ses sous-tests EN SILENCE."""
        for surface, route, _account, _model, _app_home in self._fleet():
            with self.subTest(surface=surface):
                self.assertTrue(self._route_for(route, 'clear_all', []), 'pas de « tout effacer »')
                self.assertTrue(self._route_for(route, 'batch_delete', [1]), 'pas de suppression de lot')

    def test_a_file_shared_by_a_duplicate_survives_until_its_last_card_goes(self):
        """« Dupliquer » PARTAGE le fichier (`duplicate_instance`, par contrat) : supprimer
        l'original ne doit ni casser la copie ni annoncer un orphelin, et le fichier n'est libéré
        qu'avec la dernière card."""
        from wama.common.utils.queue_duplication import duplicate_instance
        for surface, route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                original, files = self._witness(model, account, app_home)
                if not files:
                    continue
                duplicate = duplicate_instance(original)
                self._delete_card(route, original)
                self.assertEqual([], self._lost(files), 'supprimer l’original a détruit un fichier '
                                                        'que sa COPIE utilise encore')
                self.assertEqual(sorted(p.name for p in files), sorted(self._not_released(files)),
                                 'un fichier que la copie utilise encore est annoncé orphelin')
                self._delete_card(route, duplicate)
                self.assertEqual([], self._lost(files))
                self.assertEqual([], self._not_released(files),
                                 'la dernière card partie, le fichier n’est pas signalé comme libéré')


class DuplicatingAndRestartingKeepFilesTest(TestCase):
    """« Dupliquer » PARTAGE les fichiers ; « Relancer » ne détruit rien qu'il ne possède seul.

    Né le 2026-09-22 (plan de robustesse, H et F). Mêmes témoins, même parc, même lecture des
    routes (`route_variants`) que le contrat de suppression — rien n'y nomme une app.
      H — la copie est UNE nouvelle card, qui désigne les fichiers de l'original au lieu de les
          recopier : aucun fichier ne s'ajoute sur le disque ;
      F — relancer une card n'efface ni une entrée qu'elle ne fait que RÉFÉRENCER, ni un fichier
          qu'une copie partage encore. (Les vues de relance effacent l'ancienne sortie : c'est
          là que se loge le risque.)
    """

    _account_for = SuppressionDansChaqueAppTest._compte_pour
    setUp = DeletingACardRemovesTheFilesItOwnsTest.setUp
    _witness = DeletingACardRemovesTheFilesItOwnsTest._witness
    _fleet = DeletingACardRemovesTheFilesItOwnsTest._fleet
    _route_for = DeletingACardRemovesTheFilesItOwnsTest._route_for
    _post = DeletingACardRemovesTheFilesItOwnsTest._post

    def _files_on_disk(self):
        return sorted(p for p in Path(self.tmp).rglob('*') if p.is_file())

    def test_duplicating_shares_the_files_instead_of_copying_them(self):
        for surface, route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                original, files = self._witness(model, account, app_home)
                url = self._route_for(route, 'duplicate', [original.pk])
                self.assertTrue(url, 'pas de « Dupliquer » — le geste manque à cette app')
                before_rows = set(model.objects.filter(pk__gt=0).values_list('pk', flat=True))
                before_disk = self._files_on_disk()
                self._post(url)
                new_rows = model.objects.exclude(pk__in=before_rows)
                self.assertEqual(1, new_rows.count(), 'la duplication doit créer UNE card')
                copy = new_rows.get()
                self.assertEqual(before_disk, self._files_on_disk(),
                                 'la duplication a recopié des fichiers au lieu de les partager')
                originals = {str(getattr(original, f.name) or '') for f in model._meta.concrete_fields
                             if isinstance(f, models.FileField)}
                for f in model._meta.concrete_fields:
                    name = str(getattr(copy, f.name) or '') if isinstance(f, models.FileField) else ''
                    if name:
                        self.assertIn(name, originals, f'la copie désigne un fichier inconnu ({f.name})')

    def test_a_received_card_is_duplicated_into_the_requesters_own_card(self):
        """« Dupliquer » une card REÇUE (2026-10-01, `WAMA_COLLABORATION §3bis`, mode lecture) : la
        copie appartient à celui qui duplique, elle est privée, et chacun de ses fichiers est une
        COPIE chez lui — le propriétaire peut supprimer les siens sans casser la copie. Les
        originaux ne bougent pas. Contre-épreuve : la card PRIVÉE d'autrui reste introuvable."""
        from wama.common.utils.media_paths import app_media_dir
        owner = User.objects.create_user('received_card_owner', password='x')
        for surface, route, account, model, _home in self._fleet():
            with self.subTest(surface=surface):
                owner_home = app_media_dir(model._meta.app_label, owner.id, 'output')
                original, files = self._witness(model, owner, owner_home)
                if not files:
                    continue
                url = self._route_for(route, 'duplicate', [original.pk])
                refused = self.client.post(url, data='{}', content_type='application/json')
                self.assertEqual(404, refused.status_code, 'la card PRIVÉE d’autrui a été dupliquée')

                model.objects.filter(pk=original.pk).update(visibility='public')
                before_rows = set(model.objects.values_list('pk', flat=True))
                self._post(url)
                copy = model.objects.exclude(pk__in=before_rows).get()
                self.assertEqual(account.pk, copy.user_id, 'la copie doit appartenir au demandeur')
                self.assertEqual('private', copy.visibility, 'la copie naît privée')
                mine = app_media_dir(model._meta.app_label, account.id, '')
                for f in model._meta.concrete_fields:
                    name = str(getattr(copy, f.name) or '') if isinstance(f, models.FileField) else ''
                    if name:
                        self.assertTrue(name.startswith(mine), f'{f.name} désigne {name}, pas un '
                                        'fichier du demandeur')
                        self.assertTrue((Path(self.tmp) / name).exists(), f'{f.name} : copie absente')
                self.assertEqual([], [p.name for p in files if not p.exists()],
                                 'les fichiers du propriétaire ont bougé')

    def test_restarting_never_destroys_a_referenced_input_nor_a_shared_file(self):
        from unittest import mock
        from wama.common.utils.queue_duplication import duplicate_instance
        started = 0
        with mock.patch('celery.app.task.Task.apply_async',
                        return_value=mock.Mock(id='tache-de-test')) as dispatch:
            for surface, route, account, model, app_home in self._fleet():
                with self.subTest(surface=surface):
                    # Une card dont les fichiers sont RÉFÉRENCÉS (le temp de l'utilisateur)…
                    referenced, ref_files = self._witness(model, account,
                                                          f'users/{account.id}/temp')
                    # …et une card dont les fichiers sont PARTAGÉS avec une copie.
                    shared, shared_files = self._witness(model, account, app_home)
                    duplicate_instance(shared)
                    for card in (referenced, shared):
                        url = self._route_for(route, 'start', [card.pk])
                        self.assertTrue(url, 'pas de « Démarrer » — le geste manque à cette app')
                        dispatch.reset_mock()
                        self.client.post(url, data='{}', content_type='application/json')
                        started += int(dispatch.called)
                    lost = [p.name for p in ref_files + shared_files if not p.exists()]
                    self.assertEqual([], lost, 'relancer a détruit un fichier référencé ou partagé')
        # Non-vacuité : une vue de démarrage peut refuser un témoin minimal (format absent,
        # prompt vide…) sans rien toucher — le contrat ne mesurerait alors que des refus.
        self.assertGreater(started, 0, 'aucun démarrage n’a réellement eu lieu : contrat vide')
        print(f'\n[relance : {started} démarrage(s) réellement lancé(s) sur les témoins]')


class TransferringACardTest(TestCase):
    """« Transférer à… » (2026-10-01, `WAMA_COLLABORATION §3bis`) — sur CHAQUE app, sans en nommer :
    la card change de propriétaire ; ce qu'elle POSSÉDAIT est DÉPLACÉ chez le nouveau, ce qu'elle
    ne faisait que DÉSIGNER est COPIÉ (l'ancien garde l'original). Elle naît privée chez lui."""

    _account_for = SuppressionDansChaqueAppTest._compte_pour
    setUp = DeletingACardRemovesTheFilesItOwnsTest.setUp
    _witness = DeletingACardRemovesTheFilesItOwnsTest._witness
    _fleet = DeletingACardRemovesTheFilesItOwnsTest._fleet

    def _transfer(self, surface, pk, to, consent=False):
        data = {'surface': surface, 'pk': pk, 'to': to}
        if consent:
            data['consent'] = '1'
        return self.client.post(reverse('common:api_transfer'), data)

    def test_owned_files_move_and_designated_files_are_copied(self):
        from wama.common.utils.media_paths import app_media_dir
        recipient = User.objects.create_user('transfer_recipient', password='x',
                                             email='recipient@example.org')
        for surface, _route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                owned, owned_files = self._witness(model, account, app_home)
                if not owned_files:
                    continue
                res = self._transfer(surface, owned.pk, 'transfer_recipient').json()
                self.assertTrue(res.get('transferred'), res)
                owned.refresh_from_db()
                self.assertEqual(recipient.pk, owned.user_id)
                self.assertEqual('private', owned.visibility)
                theirs = app_media_dir(model._meta.app_label, recipient.pk, '')
                for f in model._meta.concrete_fields:
                    name = str(getattr(owned, f.name) or '') if isinstance(f, models.FileField) else ''
                    if name:
                        self.assertTrue(name.startswith(theirs), f'{f.name} : {name}')
                        self.assertTrue((Path(self.tmp) / name).exists(), f'{f.name} : absent')
                self.assertEqual([], [p.name for p in owned_files if p.exists()],
                                 'un fichier POSSÉDÉ est déplacé, pas laissé à l’ancien')

                temp = f'users/{account.id}/temp'
                designating, ref_files = self._witness(model, account, temp)
                res = self._transfer(surface, designating.pk, 'recipient@example.org').json()
                self.assertTrue(res.get('transferred'), res)
                self.assertEqual([], [p.name for p in ref_files if not p.exists()],
                                 'un fichier seulement DÉSIGNÉ reste à l’ancien propriétaire')
                designating.refresh_from_db()
                for f in model._meta.concrete_fields:
                    name = str(getattr(designating, f.name) or '') if isinstance(f, models.FileField) else ''
                    if name:
                        self.assertTrue(name.startswith(theirs), f'{f.name} : {name}')

    def test_a_transferred_card_leaves_the_owners_batch(self):
        """La card sort du LOT de l'ancien propriétaire (`batch_common.leave_batch`), dans les DEUX
        formes de rattachement ; le lot quitté se recale, et la réponse dit ce qu'il devient."""
        from wama.common.utils.batch_common import batch_of
        User.objects.create_user('transfer_batch_recipient', password='x')
        for surface, _route, account, model, _home in self._fleet():
            with self.subTest(surface=surface):
                lot, (first, second) = _lot_de(model, account, 2)
                res = self._transfer(surface, first.pk, 'transfer_batch_recipient').json()
                self.assertTrue(res.get('transferred'), res)
                first.refresh_from_db()
                self.assertIsNone(batch_of(first), 'la card transférée est restée dans le lot')
                self.assertEqual(second.pk and lot.pk, batch_of(second).pk)
                self.assertEqual(1, res['batch']['total'], 'le lot quitté dit ce qu’il devient')

    def test_a_whole_batch_is_transferred_with_its_cards(self):
        """Le LOT entier (2026-10-01) : lot et cards changent de propriétaire d'un bloc, rien ne
        sort du lot ; un fichier que deux cards du lot portent est DÉPLACÉ une fois, les deux liens
        suivent (le partage se juge sur l'ensemble cédé)."""
        from wama.common.utils.batch_common import batch_elements
        from wama.common.utils.media_paths import app_media_dir
        recipient = User.objects.create_user('transfer_lot_recipient', password='x')
        for surface, _route, account, model, app_home in self._fleet():
            with self.subTest(surface=surface):
                lot, (first, second) = _lot_de(model, account, 2)
                first, files1 = self._witness(model, account, app_home, el=first)
                second, files2 = self._witness(model, account, app_home, el=second)
                if not files1:
                    continue
                shared_field = next(f.name for f in model._meta.concrete_fields
                                    if isinstance(f, models.FileField))
                # La 2ᵉ card porte désormais le fichier de la 1ʳᵉ : le sien n'est plus porté par
                # personne, il sort du témoin (le transfert n'a pas à déplacer un fichier orphelin).
                replaced = Path(self.tmp) / getattr(second, shared_field).name
                setattr(second, shared_field, getattr(first, shared_field).name)
                second.save(update_fields=[shared_field])
                replaced.unlink()
                files2 = [p for p in files2 if p != replaced]
                res = self._transfer_lot(surface, lot.pk, 'transfer_lot_recipient').json()
                self.assertTrue(res.get('transferred'), res)
                lot.refresh_from_db()
                self.assertEqual(recipient.pk, lot.user_id)
                kept = list(batch_elements(lot, model))
                self.assertEqual({first.pk, second.pk}, {e.pk for e in kept}, 'le lot garde ses cards')
                theirs = app_media_dir(model._meta.app_label, recipient.pk, '')
                for el in kept:
                    self.assertEqual(recipient.pk, el.user_id)
                    self.assertEqual('private', el.visibility)
                    for f in model._meta.concrete_fields:
                        name = str(getattr(el, f.name) or '') if isinstance(f, models.FileField) else ''
                        if name:
                            self.assertTrue(name.startswith(theirs), f'{f.name} : {name}')
                            self.assertTrue((Path(self.tmp) / name).exists(), f'{f.name} : absent')
                a, b = (next(e for e in kept if e.pk == pk) for pk in (first.pk, second.pk))
                self.assertEqual(getattr(a, shared_field).name, getattr(b, shared_field).name,
                                 'le fichier commun aux deux cards est déplacé UNE fois')
                self.assertEqual([], [p.name for p in files1 + files2 if p.exists()],
                                 'plus rien chez l’ancien propriétaire')

    def _transfer_lot(self, surface, pk, to):
        return self.client.post(reverse('common:api_transfer'),
                                {'surface': surface, 'pk': pk, 'to': to, 'nature': 'lot'})

    def test_guards(self):
        surface, _route, account, model, app_home = next(iter(self._fleet()))
        mine, _ = self._witness(model, account, app_home)
        other = User.objects.create_user('transfer_other_owner', password='x')
        theirs = _instance(model, other)
        self.assertEqual(404, self._transfer(surface, theirs.pk, account.username).status_code)
        unknown = self._transfer(surface, mine.pk, 'nobody-at-all').json()
        self.assertFalse(unknown['transferred'])
        self.assertIn('aucun compte', unknown['reason'])
        self.assertFalse(self._transfer(surface, mine.pk, account.username).json()['transferred'],
                         'on ne se transfère pas sa propre card')

    def test_a_card_carrying_a_person_asks_for_consent(self):
        from wama.common.services.card_transfer import TransferConsentRequired, transfer_card
        from wama.media_library.models import UserAsset
        owner = User.objects.create_user('transfer_voice_owner', password='x')
        recipient = User.objects.create_user('transfer_voice_recipient', password='x')
        voice = UserAsset.objects.create(user=owner, name='voix', asset_type='voice',
                                         file=f'users/{owner.id}/media_library/assets/v.wav')
        with self.assertRaises(TransferConsentRequired) as ctx:
            transfer_card(owner, voice, recipient)
        self.assertIn('transfer_voice_recipient', ctx.exception.statement)


class SafeDeleteFileContractTest(TestCase):
    """Le contrat de LA brique : `safe_delete_file` ne détruit qu'un fichier de l'app, non partagé.

    Les tests de parc ci-dessus passent par les VUES (ils attestent que chaque geste emploie la
    brique) ; ceux-ci fixent la brique elle-même, cas par cas, sur le premier modèle de file du
    registre — n'importe lequel convient, c'est la règle qu'on éprouve, pas une app.
    """

    def setUp(self):
        import shutil
        import tempfile

        from django.test import override_settings
        from wama.common.utils.preview_registry import PreviewRegistry

        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = User.objects.create_user('brique_suppression', password='x')
        self.other = User.objects.create_user('brique_suppression_autre', password='x')
        surface = _surfaces()[0][0]
        self.model = PreviewRegistry.get_model(surface)
        self.field = next(f.name for f in self.model._meta.concrete_fields
                          if isinstance(f, models.FileField))

    def _card(self, rel, owner=None):
        path = Path(self.tmp) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        card = _instance(self.model, owner or self.user)
        setattr(card, self.field, rel)
        card.save()
        return card, path

    def _home(self, user, name):
        from wama.common.utils.media_paths import app_media_dir
        return f"{app_media_dir(self.model._meta.app_label, user.id, 'output')}/{name}"

    def test_the_apps_own_unshared_file_is_deleted(self):
        from wama.common.utils.queue_duplication import safe_delete_file
        card, path = self._card(self._home(self.user, 'a.bin'))
        self.assertTrue(safe_delete_file(card, self.field))
        self.assertFalse(path.exists())

    def test_a_file_in_the_users_own_space_is_never_deleted(self):
        from wama.common.utils.queue_duplication import safe_delete_file
        card, path = self._card(f'users/{self.user.id}/temp/a.bin')
        self.assertFalse(safe_delete_file(card, self.field))
        self.assertTrue(path.exists())

    def test_a_file_in_another_users_home_is_never_deleted(self):
        """Même app, autre propriétaire : le chemin est « chez une app », mais pas chez CELLE-CI
        pour CE compte — le préfixe porte l'identifiant, et c'est lui qui tranche."""
        from wama.common.utils.queue_duplication import safe_delete_file
        card, path = self._card(self._home(self.other, 'a.bin'))
        self.assertFalse(safe_delete_file(card, self.field))
        self.assertTrue(path.exists())

    def test_a_shared_file_survives_until_its_last_card_goes(self):
        from wama.common.utils.queue_duplication import duplicate_instance, safe_delete_file
        card, path = self._card(self._home(self.user, 'a.bin'))
        copy = duplicate_instance(card)
        self.assertFalse(safe_delete_file(card, self.field), 'fichier encore partagé')
        card.delete()
        self.assertTrue(path.exists())
        self.assertTrue(safe_delete_file(copy, self.field))
        self.assertFalse(path.exists())

    def test_an_empty_field_is_a_no_op(self):
        from wama.common.utils.queue_duplication import safe_delete_file
        card = _instance(self.model, self.user)
        setattr(card, self.field, '')
        self.assertFalse(safe_delete_file(card, self.field))


# ── Le jumeau gabarit ↔ JS ────────────────────────────────────────────────────────────────────

class EnrobageUnitaireJumeauTest(TestCase):
    """`queue-actions.js::unwrapBatch` recrée l'entrée unitaire de `_queue_entry.html`.

    Deux écritures du même markup : si l'une bouge seule, la card redevenue simple sans
    rechargement de la page n'est plus la card que la file rend (réordonnancement, glisser-déposer
    et partage lisent ces attributs). Les deux côtés sont lus ici, ensemble.
    """

    ATTRIBUTS = ('wama-queue-entry', 'display:contents', 'data-entry-batch-id', 'data-card-url')

    def test_le_gabarit_rend_l_enrobage_unitaire_avec_l_url_de_la_card(self):
        from wama.converter.models import ConversionJob
        u = User.objects.create_user('enrobage', password='x')
        lot, (job,) = _lot_de(ConversionJob, u, 1)
        job.elem = job
        html = render_to_string('common/_queue_entry.html', {
            'batch_info': {'obj': lot, 'items': [job]}, 'app': 'converter',
            'card_template': 'converter/_job_card.html'})
        entree = re.search(r'<div class="wama-queue-entry"[^>]*>', html)
        self.assertIsNotNone(entree, html[:500])
        for attribut in self.ATTRIBUTS[1:]:
            self.assertIn(attribut, entree.group(0))
        self.assertIn(f'data-card-url="{reverse("converter:card_html", args=[0])}"', entree.group(0))

    def test_le_js_recree_les_memes_attributs(self):
        src = (Path(__file__).parent.parent / 'static/common/js/queue-actions.js').read_text(encoding='utf-8')
        corps = src[src.index('function unwrapBatch'):src.index('function updateBatchHeader')]
        for trace in ("className = 'wama-queue-entry'", "style.display = 'contents'",
                      'dataset.entryBatchId', 'dataset.cardUrl'):
            self.assertIn(trace, corps)


# ── La grille : les critères qui tiennent ce palier ───────────────────────────────────────────

class CriteresDeLaGrilleTest(SimpleTestCase):
    """Les critères ajoutés le 2026-09-15, mesurés sur des apps FICTIVES — l'état réel du parc se
    lit par `check_app_conformity`, jamais ici. Chaque critère a sa contre-épreuve : un cas
    ROUGE, et un commentaire citant l'ancienne forme qui ne doit PAS le faire rougir."""

    URLS = ("path('delete/<int:pk>/', views.delete, name='delete'),\n"
            "path('card/<int:pk>/html/', views.card_html, name='card_html'),\n")

    def _app(self, fichiers):
        import tempfile
        from wama.common.services import conformity_checker as cc
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        for nom, contenu in fichiers.items():
            chemin = Path(dossier.name) / nom
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(contenu, encoding='utf-8')
        f = cc._AppFiles('app_fictive')
        f.root = Path(dossier.name)
        return f, cc

    def _critere(self, cle):
        from wama.common.services import conformity_checker as cc
        return next(c for c in cc.CRITERIA if c.key == cle)

    def test_suppression_la_brique_est_verte_la_main_rouge_un_commentaire_neutre(self):
        brique = "s = batch_snapshot(x)\nreturn JsonResponse({'batch': batch_state(s, M)})\n"
        f, cc = self._app({'urls.py': self.URLS, 'views.py': brique})
        self.assertIs(cc._delete_batch_state(f)[0], True)
        f, cc = self._app({'urls.py': self.URLS,
                           'views.py': "return JsonResponse({'batch_changed': b is not None})\n"})
        self.assertIs(cc._delete_batch_state(f)[0], False)
        f, cc = self._app({'urls.py': self.URLS, 'views.py': '# ex-batch_changed\n' + brique})
        self.assertIs(cc._delete_batch_state(f)[0], True)
        f, cc = self._app({'urls.py': self.URLS, 'views.py': 'return JsonResponse({"b": batch_state(s, M)})\n'})
        self.assertEqual(cc._delete_batch_state(f)[0], 'partial')
        f, cc = self._app({'urls.py': "path('', v, name='index'),\n", 'views.py': ''})
        self.assertIsNone(cc._delete_batch_state(f)[0])

    def test_card_seule_in_batch_par_la_brique_vert_calcule_ou_absent_rouge(self):
        f, cc = self._app({'urls.py': self.URLS,
                           'views.py': "render(r, 't', {'elem': e, 'in_batch': is_batch_child(e)})\n"})
        self.assertIs(cc._card_in_batch(f)[0], True)
        f, cc = self._app({'urls.py': self.URLS,
                           'views.py': "in_batch = L.objects.filter(t=t, batch__total__gt=1).exists()\n"})
        self.assertIs(cc._card_in_batch(f)[0], False)
        f, cc = self._app({'urls.py': self.URLS, 'views.py': "render(r, 't', {'elem': e})\n"})
        self.assertIs(cc._card_in_batch(f)[0], False)
        f, cc = self._app({'urls.py': "path('', v, name='index'),\n", 'views.py': ''})
        self.assertIsNone(cc._card_in_batch(f)[0])

    def test_rafraichir_une_card_par_la_brique_vert_copie_locale_rouge(self):
        f, cc = self._app({'static/a/js/a.js': 'WamaApp.fetchCard(APP.urls.cardHtml, id);\n'})
        self.assertIs(cc._card_refresh_common(f)[0], True)
        f, cc = self._app({'static/a/js/a.js': 'async function upsertCard(i) { fetch(urlFor("cardHtml", i)); }\n'})
        self.assertIs(cc._card_refresh_common(f)[0], False)
        # Nom de fonction quelconque, URL tenue ailleurs : la MENTION de la route suffit.
        f, cc = self._app({'static/a/js/a.js': 'const tpl = IMAGER_CARD.urls.cardHtml;\n'})
        self.assertIs(cc._card_refresh_common(f)[0], False)
        f, cc = self._app({'static/a/js/a.js': ('WamaApp.fetchCard(u, id);\n'
                                               'fetch(WamaApp.getUrl(APP.cardHtmlUrlTemplate, id));\n')})
        self.assertEqual(cc._card_refresh_common(f)[0], 'partial')
        f, cc = self._app({'static/a/js/a.js': '// ancien refreshCard sur cardHtml\n'})
        self.assertIsNone(cc._card_refresh_common(f)[0])

    def test_cycle_de_modale_par_la_brique_vert_a_la_main_rouge_sans_ouvreur_non_applicable(self):
        ouvreur = 'WamaQueueActions.onSettings(function (id) { ouvrir(id); });\n'
        f, cc = self._app({'static/a/js/a.js': ouvreur + 'WamaParams.settingsModal({ id: id });\n'})
        self.assertIs(cc._settings_modal_cycle(f)[0], True)
        f, cc = self._app({'static/a/js/a.js': ouvreur + 'WamaParams.render(host, schema, {});\n'})
        self.assertIs(cc._settings_modal_cycle(f)[0], False)
        f, cc = self._app({'static/a/js/a.js': '// WamaQueueActions.onSettings cité en commentaire\n'})
        self.assertIsNone(cc._settings_modal_cycle(f)[0])

    def test_modele_de_lot_porte_les_deux_contrats_communs(self):
        modele = 'class LotX(BatchMixin, QueueOrderMixin, ScopedVisibility):\n    pass\n'
        f, _cc = self._app({'models.py': modele})
        self.assertIs(self._critere('batch_semantics').fn(f)[0], True)
        self.assertIs(self._critere('queue_order').fn(f)[0], True)
        f, _cc = self._app({'models.py': 'class LotX(QueueOrderMixin, models.Model):\n    pass\n'})
        self.assertIs(self._critere('batch_semantics').fn(f)[0], False,
                      "le défaut de la jumelle `converter_01` du 15/09 : lot sans `is_unitary`")

    def test_les_mecanismes_de_ce_palier_ont_chacun_un_critere(self):
        from wama.common.services.mecanismes_scan import orphan_criteria, mechanisms_without_criterion
        sans = {m.key for m, _apps in mechanisms_without_criterion()}
        for cle in ('queue_order', 'inspector', 'result_tabs'):
            self.assertNotIn(cle, sans, f"mécanisme `{cle}` : aucun critère ne le vérifie")
        self.assertEqual(orphan_criteria(), [])
