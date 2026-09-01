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


def _types_entree(src):
    """La valeur ÉVALUÉE de `_TYPES_ENTREE` — pas une sous-chaîne de la source."""
    for noeud in ast.parse(src).body:
        if (isinstance(noeud, ast.Assign) and noeud.targets
                and getattr(noeud.targets[0], 'id', '') == '_TYPES_ENTREE'):
            return ast.literal_eval(noeud.value)
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

    def test_le_gabarit_de_lot_publie_a_une_ligne_d_exemple_deposable(self):
        # Échec mesuré 30/08 : « le gabarit publié par l'app ne contient que des commentaires —
        # aucune ligne d'exemple à déposer ». L'exemple passe par la brique commune, avec une
        # extension DÉRIVÉE du vocabulaire d'entrée.
        corps = _fonction(self.src, 'batch_template')
        self.assertIsNotNone(corps)
        self.assertIn('build_batch_template', corps, 'le gabarit doit passer par la brique')
        self.assertIn('example.com/exemple', corps, 'aucune ligne d\'exemple émise')

    def _src_avec_hors_colonnes(self):
        """Vues générées pour une app dont un réglage n'EST PAS une colonne.

        ⚠ Le converter servait de témoin jusqu'au 2026-09-01 — il ne peut plus : ses 17
        réglages sont passés EN COLONNES ce jour-là, donc il n'a plus de hors-colonne et le
        gabarit n'a (justement) plus d'idiome à émettre pour lui. Le mécanisme, lui, reste
        nécessaire (l'enhancer a 4 hors-colonnes, et une app générée de zéro peut en avoir) :
        on le mesure donc sur un manifeste FABRIQUÉ, indépendant de l'état d'une app réelle.
        """
        from copy import deepcopy
        from wama.common.manifests.ingest import extract
        from wama.common.manifests.codegen.views_gen import render_views
        manifest = deepcopy(extract('app', SOURCE))
        body = manifest.get('body') or {}
        # Le générateur lit les colonnes à DEUX endroits (facette `data` ET
        # `processing.model_spec.item.params_fields`) et cherche un conteneur nommé
        # `options` : pour fabriquer un « modèle à hors-colonne », il faut donc retirer le
        # param des deux listes ET rendre le conteneur présent (le converter l'a renommé
        # `options_legacy` en passant aux colonnes).
        for m in (body.get('data') or {}).get('models') or []:
            if isinstance(m, dict) and m.get('name') == 'ConversionJob':
                champs = [f for f in (m.get('fields') or []) if f.get('name') != 'quality']
                champs.append({'name': 'options', 'type': 'JSONField'})
                m['fields'] = champs
        spec = ((body.get('processing') or {}).get('model_spec') or {}).get('item') or {}
        spec['params_fields'] = [n for n in (spec.get('params_fields') or []) if n != 'quality']
        src, raison = render_views(manifest)
        self.assertIsNotNone(src, f'génération impossible : {raison}')
        return src

    def test_les_champs_hors_colonnes_s_ecrivent_dans_le_conteneur_options(self):
        """Idiome `params_storage` DÉRIVÉ (constats Fabien 31/08 : modale complète mais seuls
        les champs-colonnes s'enregistraient ; volet PARAMÈTRES vide).

        Deux moitiés, même dérivation : `update` route les champs du schéma sans colonne vers
        le JSONField `options` ; `_decorer` aplatit ces valeurs sur l'instance (data-param-*,
        volet, pré-remplissage de modale).
        """
        src = self._src_avec_hors_colonnes()
        corps = _fonction(src, 'update')
        self.assertIsNotNone(corps)
        self.assertIn('_extras', corps, 'update ne route pas les champs hors-colonnes')
        self.assertIn("'quality'", corps, 'le champ retiré des colonnes doit être routé')
        deco = _fonction(src, '_decorer')
        self.assertIsNotNone(deco)
        self.assertIn('_opts', deco, "_decorer n'aplatit pas le conteneur sur l'instance")

    def test_une_app_SANS_hors_colonne_n_emet_aucun_idiome_de_conteneur(self):
        # Le pendant, et la preuve que la bascule du converter a bien eu lieu : quand tous
        # les réglages sont des colonnes (son cas depuis le 2026-09-01), il n'y a plus rien
        # à router — émettre l'idiome quand même écrirait dans un conteneur pour rien.
        corps = _fonction(self.src, 'update') or ''
        self.assertNotIn('_extras', corps,
                         'le converter n’a plus de réglage hors colonne : aucun routage à émettre')

    def test_le_depot_deroule_la_cascade_de_reglages_de_l_app_reelle(self):
        """Un élément FRAIS doit naître avec des valeurs — défauts applicables du schéma ←
        derniers réglages persistés (user_settings) ← POST, POST re-persisté. Sans la cascade,
        la section RÉGLAGES de la card et le volet restaient vides jusqu'au premier passage
        par la modale (constat Fabien 31/08 sur la jumelle ; l'app réelle fait ce chemin dans
        converter/views.py::upload)."""
        # La cascade vit dans une fonction PARTAGÉE (`_reglages_du_depot`) : elle ne vivait
        # que dans upload et les filles de LOT naissaient sans valeurs (chips vides,
        # constat Fabien 31/08).
        fn = _fonction(self.src, '_reglages_du_depot')
        self.assertIsNotNone(fn, 'la cascade partagée _reglages_du_depot manque')
        self.assertIn('applicable_defaults', fn, 'les défauts du schéma ne se posent pas')
        self.assertIn('get_user_app_settings', fn, 'les réglages persistés ne sont pas relus')
        self.assertIn('save_user_app_settings', fn, 'le POST ne se re-persiste pas')
        # ⚠ Contrat de la brique : `defaults` définit l'ensemble des clés LUES — un {} figé
        # ici ne relirait jamais rien (piège évité à l'écriture, gardé par ce test).
        self.assertIn("{n: '' for n in noms}", fn)
        # La nature détectée prime : elle ne traverse JAMAIS la cascade.
        self.assertIn("if n != 'media_type'", fn)
        corps = _fonction(self.src, 'upload')
        self.assertIn('_reglages_du_depot(user, kwargs.get(\'media_type\', \'\'), request.POST)',
                      corps, "upload ne déroule pas la cascade")
        # Les valeurs issues de la cascade atterrissent sur l'ITEM — en colonnes quand le
        # modèle en a (cas du converter depuis le 2026-09-01), dans le conteneur JSON sinon.
        # C'est la MÊME cascade : seule sa destination suit la forme du modèle.
        self.assertIn('kwargs.update(_cols)', corps,
                      'les valeurs cascadées ne rejoignent pas les colonnes de l’item')
        src_extras = self._src_avec_hors_colonnes()
        self.assertIn("kwargs['options'] = _extras", _fonction(src_extras, 'upload'),
                      'sur un modèle à hors-colonne, les extras doivent rejoindre le conteneur')
        bc = _fonction(self.src, 'batch_create')
        self.assertEqual(bc.count("_reglages_du_depot(user, kwargs.get('media_type', ''))"), 2,
                         'les DEUX branches de batch_create (URL, fichier) doivent dérouler '
                         'la cascade — les filles de lot naissaient sans valeurs')

    def test_la_suppression_est_gardee_par_la_propriete_du_fichier(self):
        """Trou A5 (audit 31/08) : `safe_delete_file` inconditionnel pouvait supprimer un
        fichier UTILISATEUR seulement référencé (envoi Filemanager). La garde dérivée de la
        politique du converter réel doit envelopper LES TROIS vues de suppression — une
        garde se pose avec ses jumeaux."""
        self.assertIn('def _fichier_de_l_app(item, champ):', self.src)
        self.assertIn("startswith(f'converter/{item.user_id}/')", self.src)
        for vue in ('delete', 'clear_all', 'batch_delete'):
            corps = _fonction(self.src, vue)
            self.assertIsNotNone(corps, f'{vue} absente')
            self.assertIn('_fichier_de_l_app(item, _champ)', corps,
                          f'{vue} supprime sans garde de propriété')
            self.assertNotIn('\n            safe_delete_file' if vue != 'delete' else
                             '\n        safe_delete_file', corps.replace(
                                 'if _fichier_de_l_app(item, _champ):\n', ''),)

    def test_global_progress_parle_le_contrat_du_composant_commun(self):
        """Trou A3 (audit 31/08) : l'émission renvoyait {running, pending, percent} — la
        brique `wama-global-progress.js` lit total/done/overall_progress → barre MUETTE,
        « 0 terminé » permanent, zéro erreur console."""
        corps = _fonction(self.src, 'global_progress')
        self.assertIsNotNone(corps)
        for cle in ("'total'", "'done'", "'running'", "'failed'", "'overall_progress'"):
            self.assertIn(cle, corps, f'{cle} manque au contrat de la barre globale')
        self.assertNotIn("'percent'", corps, "l'ancien contrat hors-brique est revenu")

    def test_l_index_calcule_les_reglages_communs_des_filles_pour_la_mere(self):
        # Pendant vue du slot meta_template : même règle que le pilote transcriber
        # (« valeur si partagée par toutes les filles ») mais dérivée du SCHÉMA, chips par
        # la brique commune — jamais une liste de champs écrite à la main.
        # IndexView est une classe (pas de _fonction) : assertions au texte du module.
        # Depuis la promotion au COMMUN (31/08), le calcul est LA BRIQUE — plus de boucle
        # inline (l'inline émis le matin même dupliquait la règle du pilote).
        self.assertIn('common_chips_for_items as _ccfi', self.src)
        self.assertIn("'common_chips': _cc,", self.src)
        self.assertNotIn('if len(_vs) == 1:', self.src,
                         'la règle du pilote ne se réécrit pas inline — brique commune')

    def test_apps_genere_branche_l_invariant_batch_sync_en_fk_directe(self):
        """Trou A4 (audit 31/08) : sans `register_batch_sync(Item, direct_fk=True)`, le lot
        vidé de la jumelle survivait en base (l'app réelle l'avait payé le 28/08)."""
        from wama.common.manifests.codegen.apps_gen import render_apps
        from wama.common.manifests.ingest import extract
        src, raison = render_apps(extract('app', SOURCE))
        self.assertIsNotNone(src, raison)
        self.assertIn('register_batch_sync(ConversionJob, direct_fk=True)', src)

    def test_sans_conteneur_json_aucun_routage_invente(self):
        # Discriminant : un modèle SANS champ `options` ne doit recevoir aucun bloc _extras —
        # écrire dans un attribut inexistant serait le défaut silencieux type.
        from copy import deepcopy
        from wama.common.manifests.ingest import extract
        from wama.common.manifests.codegen.views_gen import render_views
        manifest = deepcopy(extract('app', SOURCE))
        for m in ((manifest.get('body') or {}).get('data') or {}).get('models') or []:
            if isinstance(m, dict):
                m['fields'] = [f for f in (m.get('fields') or [])
                               if f.get('name') != 'options']
        src, raison = render_views(manifest)
        self.assertIsNotNone(src, f'génération impossible : {raison}')
        corps = _fonction(src, 'update')
        self.assertNotIn('_extras', corps or '')

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

    def test_le_vocabulaire_d_entree_est_LU_au_manifeste_et_non_ecrit_en_dur(self):
        """`_TYPES_ENTREE` doit SUIVRE `body.ports.inputs[].types`, pas le recopier une fois.

        Le test mute le manifeste plutôt que de comparer à la valeur attendue : c'est la seule
        façon de distinguer « dérivé » de « écrit en dur avec la bonne valeur ce jour-là ».
        Même famille que la liste d'apps codée en dur du drag&drop, qui valait exactement le
        catalogue moins la dernière app ajoutée.
        """
        from copy import deepcopy

        from wama.common.manifests.ingest import extract
        manifest = deepcopy(extract('app', SOURCE))
        ports = (manifest.get('body') or {}).get('ports') or {}
        if not (ports.get('inputs') or []):
            self.skipTest(f'{SOURCE} sans ports.inputs')
        ports['inputs'][0]['types'] = ['audio']
        src, raison = render_views(manifest)
        self.assertIsNotNone(src, f'génération impossible : {raison}')
        self.assertIn("_TYPES_ENTREE = ('audio',)", src,
                      'le vocabulaire ne suit pas le manifeste (valeur figée dans le gabarit)')

    def test_le_port_de_prompt_n_entre_pas_dans_le_vocabulaire_de_FICHIERS(self):
        """`_TYPES_ENTREE` sert à nommer la nature d'un FICHIER — le prompt n'en est pas un.

        Le manifeste déclare les entrées par RÔLE (`body.ports.inputs[].group` : travail /
        référence / prompt). Sur imager, composer, synthesizer et avatarizer, un port
        `group: 'prompt'` porte le type `'prompt'` — un jeton que `category_of_path` ne peut
        JAMAIS rendre. L'unir aux autres reviendrait à écrire un vocabulaire dont un membre
        n'est comparable à rien : inoffensif sur le converter (qui n'a pas ce port), faux dès
        la 2ᵉ app portée. C'est le défaut que ce test empêche de revenir avec le portage.
        """
        from copy import deepcopy

        from wama.common.manifests.ingest import extract
        manifest = deepcopy(extract('app', SOURCE))
        ports = (manifest.get('body') or {}).get('ports') or {}
        if not (ports.get('inputs') or []):
            self.skipTest(f'{SOURCE} sans ports.inputs')
        ports['inputs'][0]['types'] = ['image']
        ports['inputs'].append({'id': 'prompt', 'label': 'Prompt', 'group': 'prompt',
                                'types': ['prompt'], 'multi': False})
        src, raison = render_views(manifest)
        self.assertIsNotNone(src, f'génération impossible : {raison}')
        self.assertEqual(_types_entree(src), ('image',),
                         "le port `prompt` est entré dans le vocabulaire de fichiers")

    def test_le_repli_sur_accepts_ecarte_l_homonyme_text(self):
        """En repli sur `modes.domains[].accepts`, `text` désigne le PROMPT, pas un fichier.

        `text` est un homonyme dans ce dépôt, et les deux sens se croisent ici : dans
        `input_types`/`accepts` il veut dire **texte brut** (c'est pourquoi
        `studio_node_ports` écrit `c != 'text'` pour le sortir du port travail) ; dans
        `category_of_path` il veut dire **fichier texte** (.txt/.md/.csv/.srt). Le retenir au
        repli ferait écrire `media_type='text'` (sens fichier) au nom d'une déclaration qui
        parlait du prompt — une valeur plausible et fausse, exactement ce que `_nature` refuse
        d'écrire pour une extension hors vocabulaire.
        """
        from copy import deepcopy

        from wama.common.manifests.ingest import extract
        manifest = deepcopy(extract('app', SOURCE))
        body = manifest.get('body') or {}
        body['ports'] = {'inputs': [], 'outputs': ((body.get('ports') or {}).get('outputs') or [])}
        body['modes'] = {'domains': [{'id': 'x', 'accepts': ['text', 'image', 'inconnu']}]}
        src, raison = render_views(manifest)
        self.assertIsNotNone(src, f'génération impossible : {raison}')
        self.assertEqual(_types_entree(src), ('image',),
                         "le repli retient `text` (sens prompt) ou un jeton hors taxonomie")

    def test_la_nature_est_renseignee_dans_LES_DEUX_chemins_de_creation(self):
        """`upload` et `batch_create` doivent doter l'élément de la même façon.

        Doter un seul des deux chemins est ce qui a produit les trois derniers défauts de
        codegen (WAMA_INGEST perdu par un rendu sur deux, `pk` de trop, extra_routes en
        bouchon) : la divergence ne se voit qu'à l'usage, et seulement par l'un des deux
        boutons.
        """
        for vue in ('upload', 'batch_create'):
            corps = _fonction(self.src, vue)
            self.assertIsNotNone(corps, f'{vue} absent du fichier généré')
            self.assertIn('_nature(', corps,
                          f"{vue} ne dérive pas la nature de l'entrée")

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

    def test_la_nature_de_chaque_entree_est_deduite_et_le_lot_groupe_par_nature(self):
        """Le champ DÉRIVÉ de l'entrée (`media_type`) est renseigné — et il sert.

        Il est resté vide jusqu'au 2026-08-29 parce que le gabarit déclarait un « trou de
        glu », en donnant deux raisons fausses coup sur coup : d'abord qu'aucun détecteur
        commun nom→type n'existait (`app_registry.category_of_path` en est un, et se dit
        source unique), puis que le vocabulaire de l'app n'était nulle part déclaré (il l'est,
        et deux fois : `body.ports.inputs[].types` et `body.modes.domains[].accepts`).

        Ce que ce test garde n'est donc PAS la valeur du champ mais sa CONSÉQUENCE :
        `group_into_batches_by_nature` lisait un champ que personne n'écrivait, et rendait un
        seul lot fourre-tout. Deux natures déposées ensemble doivent donner deux lots.
        """
        modele = self._modele_item()
        if modele is None:
            self.skipTest('modèle inconnu du PreviewRegistry')

        import os
        from django.conf import settings as _st
        dossier = os.path.join(_st.MEDIA_ROOT, 'tests_lot')
        os.makedirs(dossier, exist_ok=True)
        relatifs = []
        for nom in ('nature_a.mp4', 'nature_b.jpg'):
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

        fichier = SimpleUploadedFile('lot.txt', ('\n'.join(relatifs) + '\n').encode('utf-8'),
                                     content_type='text/plain')
        data = self.client.post(self.url, {'batch_file': fichier}).json()
        self.assertEqual(data.get('count'), 2, data)

        crees = list(modele.objects.order_by('-id')[:2])
        natures = {getattr(o, 'media_type', '') for o in crees}
        self.assertEqual(natures, {'video', 'image'},
                         f"nature non dérivée du nom de fichier : {natures}")
        self.assertEqual(data.get('batches'), 2,
                         "deux natures déposées ensemble doivent donner DEUX lots — un lot "
                         f"unique signale un `media_type` vide : {data}")

    def test_une_extension_hors_vocabulaire_le_DIT_au_lieu_de_deviner(self):
        """Une valeur fausse et muette coûte plus cher qu'un champ vide et signalé.

        ⚠ Témoin CHANGÉ le 2026-08-30 (retrait de `text` des natures) : l'ancien témoin `.md`
        est devenu un `document` légitime du converter — les 3 écarts d'alors ont DISPARU,
        c'était le bénéfice mesurable du geste. Le nouveau témoin est `.glb` (nature `3d`),
        que le converter ne déclare pas : l'INVARIANT survit au vocabulaire, pas la valeur.
        """
        modele = self._modele_item()
        if modele is None:
            self.skipTest('modèle inconnu du PreviewRegistry')

        import os
        from django.conf import settings as _st
        dossier = os.path.join(_st.MEDIA_ROOT, 'tests_lot')
        os.makedirs(dossier, exist_ok=True)
        chemin = os.path.join(dossier, 'hors_vocab.glb')
        with open(chemin, 'wb') as fh:
            fh.write(b'glTF fake\n')
        rel = os.path.relpath(chemin, _st.MEDIA_ROOT).replace(os.sep, '/')
        self.addCleanup(lambda: os.path.exists(chemin) and os.remove(chemin))

        fichier = SimpleUploadedFile('lot.txt', (rel + '\n').encode('utf-8'),
                                     content_type='text/plain')
        data = self.client.post(self.url, {'batch_file': fichier}).json()
        self.assertEqual(data.get('count'), 1, data)
        self.assertEqual(getattr(modele.objects.order_by('-id').first(), 'media_type', ''), '',
                         "une extension hors vocabulaire ne doit PAS recevoir une nature "
                         "approchée — c'est le défaut qui se voit le moins")
        self.assertTrue(any('vocabulaire' in str(w) for w in (data.get('warnings') or [])),
                        f"l'écart doit être DIT, pas subi : {data}")

    def test_une_url_de_lot_est_ENREGISTREE_pas_telechargee(self):
        """Réécrit le 2026-08-31 — la bascule PRÉVUE par la version précédente a eu lieu.

        L'ancien test attestait le refus expliqué « app sans ingest » et sa docstring disait :
        « le jour où elle sera régénérée, ce test deviendra rouge : ce sera le signal que la
        voie URL est devenue exerçable, pas une régression ». Les models de la jumelle ont été
        régénérés le 31/08 (WAMA_INGEST projeté depuis `processing.ingest`) : signal reçu.
        Nouvel invariant : la ligne-URL CRÉE l'élément, `source_url` ENREGISTRÉE — jamais
        téléchargée dans la requête (c'est `ensure_local_input` en tête de tâche qui résout).
        """
        fichier = SimpleUploadedFile('lot.txt', b'https://example.org/a.mp4\n',
                                     content_type='text/plain')
        reponse = self.client.post(self.url, {'batch_file': fichier})
        self.assertEqual(reponse.status_code, 200)
        data = reponse.json()
        self.assertEqual(data.get('count'), 1, f'la voie URL doit créer : {data}')
        modele = self._modele_item()
        if modele is not None:
            dernier = modele.objects.order_by('-id').first()
            self.assertEqual(dernier.source_url, 'https://example.org/a.mp4')
            self.assertFalse(bool(dernier.input_file),
                             'rien ne doit être téléchargé dans la requête')

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
