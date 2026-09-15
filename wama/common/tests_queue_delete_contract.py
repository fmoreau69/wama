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
    from wama.common.sandbox import load_registry

    copiees = {j['label'] for j in load_registry() if 'views' not in (j.get('substituted') or {})}
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
        src = (Path(__file__).parent / 'static/common/js/queue-actions.js').read_text(encoding='utf-8')
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
