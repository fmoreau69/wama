"""Tests du CHEMIN DE LOT généré (`codegen/views_gen.py`) — trou 22, `WAMA_APP_GENERATION_ROUTE`.

`batch_create` était le dernier bouchon 501 du chemin de lot : l'aperçu marchait, le bouton ne
produisait rien. Ce qui est vérifié ici est ce qui rendait le défaut INVISIBLE — pas seulement
que la vue existe, mais qu'elle n'est pas un bouchon, et qu'elle est émise **par les deux
chemins d'assemblage**.

⚠ LE PIÈGE GARDÉ. `render_views` assemble en deux passes : les `endpoints` du manifeste, puis
les `extra_routes`. La seconde ne consultait PAS les corps conventionnels : une route déclarée
en extra recevait un stub 501 alors que la fabrique savait la rendre. C'est le même défaut que
`WAMA_INGEST` perdu par un seul des deux rendus de `models_gen`, et que le `pk` de trop sur le
stub `batch_preview`. Trois fois le même motif — d'où un test qui vise l'ASSEMBLAGE et non la
seule présence du nom.
"""
import ast

from django.apps import apps as django_apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import NoReverseMatch, reverse

from wama.common.manifests.codegen.views_gen import render_views

#: Apps dont la file est de forme FK-DIRECTE (seule forme rendue par le gabarit v1).
#: Les autres retournent `(None, raison)` — trou DÉCLARÉ, pas un échec.
SOURCE = 'converter'


def _vues_generees(app):
    from wama.common.manifests.ingest import extract
    manifest = extract('app', app)
    if not manifest:
        return None, f"manifeste de {app} inextricable"
    src, raison = render_views(manifest)
    return src, raison


def _fonction(src, nom):
    for noeud in ast.parse(src).body:
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return ast.get_source_segment(src, noeud) or ''
    return None


class CheminDeLotTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.src, cls.raison = _vues_generees(SOURCE)

    def setUp(self):
        if not self.src:
            self.skipTest(f'views non générées pour {SOURCE} : {self.raison}')

    def test_le_fichier_genere_est_du_python_valide(self):
        # Une erreur de syntaxe dans un gabarit ne se voit qu'au chargement de l'app.
        ast.parse(self.src)

    def test_batch_create_est_une_vue_pas_un_bouchon(self):
        corps = _fonction(self.src, 'batch_create')
        self.assertIsNotNone(corps, 'batch_create absent du fichier généré')
        self.assertNotIn('501', corps,
                         'batch_create est encore un bouchon — trou 22 rouvert')
        # Il doit s'appuyer sur les briques COMMUNES, pas réécrire le parsing/regroupement.
        for brique in ('parse_batch_file_from_request', 'group_into_batches_by_nature',
                       'copy_into_app_input'):
            self.assertIn(brique, corps, f'{brique} : la brique commune n\'est plus utilisée')

    def test_une_url_n_est_pas_telechargee_dans_la_requete(self):
        """La source est ENREGISTRÉE ; `ensure_local_input` la résout en tête de tâche.

        Deux raisons : une requête ne part pas chercher N fichiers distants, et le seul chemin
        de téléchargement reste celui qui passe par la garde SSRF (`url_guard`).
        """
        corps = _fonction(self.src, 'batch_create')
        self.assertIn('WAMA_INGEST', corps,
                      "la voie URL doit passer par la déclaration d'ingest")
        self.assertNotIn('upload_media_from_url', corps,
                         'téléchargement EAGER réintroduit dans la requête')

    def test_le_contrat_json_est_celui_qu_attend_le_front(self):
        corps = _fonction(self.src, 'batch_create')
        for cle in ("'success'", "'count'", "'batches'", "'warnings'"):
            self.assertIn(cle, corps, f'clé {cle} absente de la réponse')

    def test_les_extras_preferent_un_corps_conventionnel_a_un_bouchon(self):
        """L'assemblage par `extra_routes` doit consulter les corps conventionnels.

        Test de l'ASSEMBLAGE, pas d'un nom : on déplace `batch_create` des `endpoints` vers les
        `extra_routes` du manifeste et on exige le même résultat. Sans le correctif, la seconde
        passe rendait un stub 501 — et le défaut ne se voyait que sur les apps qui déclarent
        cette route en extra.
        """
        from wama.common.manifests.ingest import extract
        manifest = extract('app', SOURCE)
        proc = manifest['body']['processing']
        if 'batch_create' in (proc.get('endpoints') or []):
            proc['endpoints'] = [e for e in proc['endpoints'] if e != 'batch_create']
        proc.setdefault('extra_routes', []).append(
            {'view': 'views.batch_create', 'path': 'batch/create/', 'name': 'batch_create'})
        src, raison = render_views(manifest)
        self.assertIsNotNone(src, f'génération impossible : {raison}')
        corps = _fonction(src, 'batch_create')
        self.assertIsNotNone(corps, 'batch_create perdu quand il est déclaré en extra_route')
        self.assertNotIn('501', corps,
                         'déclaré en extra_route, batch_create redevient un bouchon — '
                         "les deux chemins d'assemblage ne produisent pas la même app")


class LotBoutEnBoutTest(TestCase):
    """Le bouton PRODUIT-il quelque chose ? — mesuré sur la jumelle générée `converter_01`.

    Les tests ci-dessus portent sur le GABARIT ; celui-ci exerce la vue réellement montée dans
    une app. Il SKIPPE si le bac à sable n'existe pas (il est destructible par conception,
    `app_sandbox drop`) — un test qui exigerait sa présence casserait le jour où on le retire.

    ⚠ Pourquoi pas le scénario nocturne `converter_01.import` : il SKIPPE, parce que le compte
    de test nocturne est détourné (302) sur cette app — trou de DROITS mesuré le 2026-08-22,
    sans rapport avec le chemin de lot. Mesurer ici, avec un compte qui a les droits, c'est
    mesurer le comportement au lieu des permissions.
    """

    APP = 'converter_01'

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.compte = get_user_model().objects.create_superuser(
            username='lot_test', email='lot@test.local', password='x')

    def setUp(self):
        if not django_apps.is_installed(f'wama.{self.APP}'):
            self.skipTest(f'{self.APP} non installé (bac à sable retiré)')
        try:
            self.url = reverse(f'{self.APP}:batch_create')
        except NoReverseMatch:
            self.skipTest(f'{self.APP} sans route batch_create')
        self.client.force_login(self.compte)

    def _modele_item(self):
        from wama.common.utils.preview_registry import PreviewRegistry
        return PreviewRegistry.get_model(self.APP)

    def test_un_fichier_de_lot_cree_des_elements_et_un_lot(self):
        modele = self._modele_item()
        if modele is None:
            self.skipTest('modèle inconnu du PreviewRegistry')
        avant = modele.objects.count()

        # Deux CHEMINS LOCAUX sous MEDIA_ROOT — la voie qui ne dépend d'AUCUNE déclaration
        # d'ingest. ⚠ La voie URL n'est pas exerçable sur cette jumelle : son `models.py` a
        # été généré le 2026-08-18, AVANT que `models_gen` cesse de perdre `WAMA_INGEST`
        # (correctif du 22/08) — elle ne porte donc pas de champ source. Mesuré explicitement
        # par `test_une_url_sans_ingest_est_signalee`, pas masqué ici.
        import os
        from django.conf import settings as _st
        dossier = os.path.join(_st.MEDIA_ROOT, 'tests_lot')
        os.makedirs(dossier, exist_ok=True)
        relatifs = []
        for nom in ('lot_a.mp4', 'lot_b.mp4'):
            chemin = os.path.join(dossier, nom)
            with open(chemin, 'wb') as fh:
                fh.write(b'0')
            relatifs.append(os.path.relpath(chemin, _st.MEDIA_ROOT).replace(os.sep, '/'))

        def _nettoyer():
            for rel in relatifs:
                p = os.path.join(_st.MEDIA_ROOT, rel)
                if os.path.exists(p):
                    os.remove(p)
        self.addCleanup(_nettoyer)

        contenu = ('\n'.join(relatifs) + '\n').encode('utf-8')
        fichier = SimpleUploadedFile('lot.txt', contenu, content_type='text/plain')
        reponse = self.client.post(self.url, {'batch_file': fichier})

        self.assertEqual(reponse.status_code, 200,
                         f"batch_create répond {reponse.status_code} "
                         f"(501 = bouchon, 500 = signature)")
        data = reponse.json()
        self.assertTrue(data.get('success'), data)
        self.assertEqual(data.get('count'), 2, f"éléments créés : {data}")
        self.assertGreaterEqual(data.get('batches') or 0, 1, f"aucun lot créé : {data}")
        self.assertEqual(modele.objects.count(), avant + 2)

        # Les éléments sont bien RATTACHÉS à un lot (c'est ce que `consolidate` garantissait
        # déjà pour les dépôts un par un — le chemin de lot doit produire le même état).
        crees = list(modele.objects.order_by('-id')[:2])
        for obj in crees:
            self.assertIsNotNone(getattr(obj, 'batch_id', None),
                                 'élément créé HORS LOT : apply_queue_sort_filter tombera '
                                 'sur un None (défaut déjà rencontré le 22/08)')

    def test_une_url_sans_ingest_est_signalee(self):
        """Une app SANS champ source le DIT dans `warnings` — elle n'échoue pas en silence.

        C'est le cas de cette jumelle (models.py d'avant le correctif WAMA_INGEST du 22/08).
        Le jour où elle sera régénérée, ce test deviendra rouge : ce sera le signal que la
        voie URL est devenue exerçable, pas une régression.
        """
        fichier = SimpleUploadedFile('lot.txt', b'https://example.org/a.mp4\n',
                                     content_type='text/plain')
        reponse = self.client.post(self.url, {'batch_file': fichier})
        self.assertEqual(reponse.status_code, 200)
        data = reponse.json()
        self.assertEqual(data.get('count'), 0)
        self.assertTrue(any('ingest' in str(w) for w in (data.get('warnings') or [])),
                        f"le refus doit être EXPLIQUÉ, pas muet : {data}")

    def test_un_fichier_sans_reference_est_refuse_proprement(self):
        """Un texte de prose n'est pas un fichier de lot — 400, pas 500 ni création muette."""
        fichier = SimpleUploadedFile(
            'note.txt', 'ceci est une note, pas une liste\nde medias\n'.encode('utf-8'),
            content_type='text/plain')
        reponse = self.client.post(self.url, {'batch_file': fichier})
        self.assertIn(reponse.status_code, (400, 200))
        if reponse.status_code == 200:
            self.assertEqual(reponse.json().get('count'), 0,
                             'de la prose a produit des éléments — la détection de lot '
                             'redevient gloutonne (défaut corrigé le 22/08)')
