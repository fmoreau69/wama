"""Tests du gestionnaire de fichiers — l'importeur DÉRIVÉ des jumelles de bac à sable.

POURQUOI CE FICHIER (2026-08-30, constat Fabien : « le drag&drop filemanager fonctionne bien
dans les applications mais pas dans le converter_01 »)

    Le registre `IMPORTERS` est écrit à la main, une ligne par app — et son propre commentaire
    réclamait qu'une app GÉNÉRÉE n'y écrive jamais la sienne : l'importeur d'une jumelle doit
    venir de la DÉRIVATION (`generated_from`), pas d'une rustine. `importer_for()` est cette
    dérivation ; ces tests tiennent ses trois propriétés :
      - une jumelle hérite de l'importeur de sa source, RE-CIBLÉ sur son app_label (sinon la
        jumelle importerait dans sa SOURCE — et une jumelle qui agit sur son original ne
        mesure plus rien) ;
      - une source NON paramétrable ne dérive rien (refus nommé plutôt qu'un import dévié) ;
      - le menu suit le même portier que la page de la jumelle (dev-only).
"""
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.filemanager.views import IMPORTERS, importer_for, receivable_apps


def _catalogue_avec_jumelle(source):
    """Un APP_CATALOG minimal portant une jumelle factice de `source`."""
    from wama.common.app_registry import APP_CATALOG
    return {**APP_CATALOG,
            'jumelle_99': {'label': 'Jumelle 99', 'generated_from': source,
                           'input_extensions': ('.txt',)}}


# ── Le menu contextuel de l'ARBRE est la brique commune (2026-09-14) ──────────────────────
#
# Reporté le 2026-09-08 (« le filemanager pourra y migrer », `wama-card-menu.js`), fait le
# 2026-09-14. Ce qui est tenu ici, et pourquoi chaque point : sans lui la migration se défait
# sans erreur visible.
REPO = Path(__file__).resolve().parents[2]
FM_STATIC = ('filemanager/js/filemanager.js', 'filemanager/css/filemanager.css')


def _sans_commentaires(texte):
    """Retire `/* … */` et `// …` : un commentaire ne câble rien (il cite, il ne branche pas)."""
    texte = re.sub(r'/\*.*?\*/', '', texte, flags=re.S)
    return re.sub(r'(^|[^:\'"\\])//[^\n]*', r'\1', texte)


def defauts_menu_de_l_arbre(js, css, smoke):
    """Les écarts à « un seul menu contextuel dans WAMA » — [] si la migration tient.

    Fonction de module et non méthode : la contre-épreuve la rejoue sur les fichiers de HEAD
    d'avant la migration (elle doit y trouver des défauts, sinon elle ne garde rien).
    """
    defauts = []
    code = _sans_commentaires(js)
    plugins = re.search(r"'plugins'\s*:\s*\[([^\]]*)\]", code)
    if not plugins:
        defauts.append("liste des plugins jsTree introuvable dans filemanager.js")
    elif 'contextmenu' in plugins.group(1):
        defauts.append("le plugin jsTree 'contextmenu' est chargé : c'est lui qui rend le "
                       "menu `vakata-context`, étranger au menu commun")
    if 'WamaCardMenu.ouvrir(' not in code:
        defauts.append("l'arbre n'ouvre pas le menu commun (`WamaCardMenu.ouvrir`)")
    # Sans le plugin, `wholerow` ne relaie PLUS le clic droit de la ligne vers l'ancre : écouter
    # l'ancre seule laisserait mort un clic droit posé sur la marge de la ligne.
    if not re.search(r"on\(\s*'contextmenu'\s*,\s*'[^']*jstree-anchor[^']*jstree-wholerow"
                     r"|on\(\s*'contextmenu'\s*,\s*'[^']*jstree-wholerow[^']*jstree-anchor", code):
        defauts.append("le clic droit n'écoute pas les DEUX cibles (ancre ET ligne `wholerow`)")
    if 'vakata-context' in re.sub(r'/\*.*?\*/', '', css, flags=re.S):
        defauts.append("filemanager.css habille encore le menu `vakata-context`")
    smoke_code = '\n'.join(ligne.split('#', 1)[0] for ligne in smoke.splitlines())
    if 'vakata-context' in smoke_code:
        defauts.append("le scénario nocturne `<app>.send_to` cherche encore le menu jsTree : "
                       "il conclurait « aucun menu » sur un menu bien ouvert")
    return defauts


class MenuContextuelDeLArbreTests(SimpleTestCase):

    def test_le_clic_droit_de_l_arbre_ouvre_le_menu_commun(self):
        lire = lambda rel: (REPO / rel).read_text(encoding='utf-8')
        self.assertEqual([], defauts_menu_de_l_arbre(
            lire('wama/filemanager/static/' + FM_STATIC[0]),
            lire('wama/filemanager/static/' + FM_STATIC[1]),
            lire('wama/common/services/ui_smoke.py')))

    def test_le_fichier_servi_est_celui_de_la_source(self):
        # C'est `staticfiles/` qui est servi : une source corrigée et une copie périmée
        # rendraient l'ancien menu sans que rien ne le dise.
        for rel in FM_STATIC:
            with self.subTest(rel=rel):
                self.assertEqual((REPO / 'wama/filemanager/static' / rel).read_bytes(),
                                 (REPO / 'staticfiles' / rel).read_bytes())


class ImporteurDeriveTests(TestCase):

    def test_une_jumelle_herite_de_l_importeur_de_sa_source_recible(self):
        with patch('wama.common.app_registry.APP_CATALOG',
                   _catalogue_avec_jumelle('converter')):
            fn = importer_for('jumelle_99')
        self.assertIsNotNone(fn, "la jumelle d'une source paramétrable doit résoudre")
        # Re-ciblage effectif : le partial porte l'app_label de la JUMELLE, pas de la source.
        self.assertEqual(fn.keywords.get('app_label'), 'jumelle_99')
        self.assertIs(fn.func, IMPORTERS['converter'])

    def test_une_source_non_parametrable_ne_derive_rien(self):
        # Dériver d'une source sans `app_label` ferait écrire l'import DANS LA SOURCE — le
        # refus nommé (menu absent) est le seul honnête. ⚠ Recalé 2026-09-03 : plus AUCUNE
        # source réelle n'est non-paramétrable (10/10 — transcriber, l'ancien exemplaire de
        # ce test, a été paramétré) ; la propriété se tient sur un importeur FACTICE et
        # protège les importeurs FUTURS écrits sans le paramètre.
        def importeur_fige(source_path, user):
            raise AssertionError('ne doit jamais être appelé')
        with patch.dict(IMPORTERS, {'sourcefigee': importeur_fige}), \
             patch('wama.common.app_registry.APP_CATALOG',
                   _catalogue_avec_jumelle('sourcefigee')):
            self.assertIsNone(importer_for('jumelle_99'))

    def test_une_app_inconnue_ne_resout_pas(self):
        self.assertIsNone(importer_for('nexiste_pas'))

    def test_le_menu_suit_le_portier_de_la_jumelle(self):
        User = get_user_model()
        quidam = User.objects.create_user('quidam-filemanager-test')
        with patch('wama.common.app_registry.APP_CATALOG',
                   _catalogue_avec_jumelle('converter')):
            # Sans utilisateur (usage serveur interne) : la jumelle est listée.
            self.assertIn('jumelle_99', receivable_apps())
            # Portier fermé : la jumelle disparaît du menu — les 10 apps du registre restent.
            with patch('wama.accounts.permissions.accessible', return_value=False):
                visibles = receivable_apps(quidam)
            self.assertNotIn('jumelle_99', visibles)
            for app in IMPORTERS:
                self.assertIn(app, visibles)

    def test_import_reel_dans_la_jumelle_locale_jamais_dans_la_source(self):
        """Bout en bout sur la VRAIE jumelle si elle est enregistrée sur cette machine.

        C'est le test qui rejoue le constat de Fabien : l'import doit créer l'élément dans
        les tables de `converter_01`, et ne rien écrire dans celles du converter.
        """
        import tempfile
        from django.apps import apps as django_apps
        from wama.common.app_registry import APP_CATALOG
        if 'converter_01' not in APP_CATALOG:
            self.skipTest('jumelle converter_01 non enregistrée sur cette machine')

        User = get_user_model()
        dev = User.objects.create_user('dev-filemanager-test')
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / 'echantillon.txt'
            source.write_text('contenu', encoding='utf-8')
            fn = importer_for('converter_01')
            self.assertIsNotNone(fn)
            resultat = fn(source, dev)

        self.assertEqual(resultat.get('app'), 'converter_01')
        JumelleJob = django_apps.get_model('converter_01', 'ConversionJob')
        SourceJob = django_apps.get_model('converter', 'ConversionJob')
        self.assertEqual(JumelleJob.objects.filter(user=dev).count(), 1)
        self.assertEqual(SourceJob.objects.filter(user=dev).count(), 0,
                         "l'import d'une jumelle ne doit JAMAIS écrire dans sa source")

    def test_l_import_groupe_d_une_jumelle_se_consolide_dans_SES_tables(self):
        """2 fichiers importés ENSEMBLE → UN lot, dans les tables de la JUMELLE.

        Constat Fabien 2026-08-31 : deux fichiers chargés depuis le filemanager vers
        converter_01 arrivaient en cards UNITAIRES — le dispatch de consolidation est une
        2ᵉ liste écrite à la main (`target_app == 'converter'`) qui ratait les jumelles.
        Le helper est désormais re-ciblé par `app_label` (même mécanique qu'`importer_for`).
        """
        import tempfile
        from django.apps import apps as django_apps
        from wama.common.app_registry import APP_CATALOG
        if 'converter_01' not in APP_CATALOG:
            self.skipTest('jumelle converter_01 non enregistrée sur cette machine')

        from wama.converter.views import consolidate_jobs_into_batches
        User = get_user_model()
        dev = User.objects.create_user('dev-filemanager-conso')
        fn = importer_for('converter_01')
        ids = []
        with tempfile.TemporaryDirectory() as d:
            for nom in ('a.txt', 'b.txt'):
                src = Path(d) / nom
                src.write_text('x', encoding='utf-8')
                ids.append(fn(src, dev)['id'])
        consolidate_jobs_into_batches(ids, dev, app_label='converter_01')

        JumelleJob = django_apps.get_model('converter_01', 'ConversionJob')
        JumelleBatch = django_apps.get_model('converter_01', 'ConversionBatch')
        SourceBatch = django_apps.get_model('converter', 'ConversionBatch')
        self.assertEqual(JumelleBatch.objects.filter(user=dev).count(), 1,
                         'les 2 imports groupés doivent former UN lot (même nature)')
        self.assertEqual(
            set(JumelleJob.objects.filter(user=dev).values_list('batch_id', flat=True)),
            set(JumelleBatch.objects.filter(user=dev).values_list('id', flat=True)))
        self.assertEqual(SourceBatch.objects.filter(user=dev).count(), 0,
                         'la consolidation ne doit JAMAIS écrire dans la source')


class ToutImporteurEstDerivableTests(SimpleTestCase):
    """INVARIANT (2026-09-03, constat Fabien : « je ne peux pas importer depuis filemanager…
    c'est un problème récurrent sur les nouvelles applications auto-générées »).

    `importer_for()` ne sait dériver l'importeur d'une jumelle que si l'importeur de la SOURCE
    accepte `app_label`. Pendant trois mois, un SEUL l'acceptait (converter, paramétré le
    30/08 pour son propre bac à sable) : chaque nouvelle jumelle redécouvrait le trou, une app
    à la fois — describer le 03/09 en était la 2ᵉ occurrence.

    Ce test est la garde POSÉE AVEC SES JUMEAUX : il ne vérifie pas les 10 importeurs d'un
    jour, il vérifie que le PROCHAIN sera écrit dérivable. Un importeur ajouté sans le
    paramètre échoue ici, avant qu'une jumelle ne le découvre à l'écran.
    """

    def test_chaque_importeur_accepte_app_label(self):
        import inspect
        sans = sorted(app for app, fn in IMPORTERS.items()
                      if 'app_label' not in inspect.signature(fn).parameters)
        self.assertEqual(sans, [], "ces importeurs ne peuvent pas servir une jumelle : "
                                   "ajouter `app_label='<app>'` à leur signature et l'employer "
                                   "pour le modèle ET le dossier d'entrée")

    def test_chaque_importeur_derive_donc_reellement_pour_une_jumelle(self):
        # La signature ne suffit pas : c'est `importer_for` qui doit rendre un callable.
        from wama.common.app_registry import APP_CATALOG
        for app in IMPORTERS:
            with patch('wama.common.app_registry.APP_CATALOG',
                       {**APP_CATALOG, 'jumelle_99': {'label': 'J', 'generated_from': app,
                                                      'input_extensions': ('.txt',)}}):
                fn = importer_for('jumelle_99')
            self.assertIsNotNone(fn, f"la jumelle d'une app {app} doit dériver son importeur")
            self.assertEqual(fn.keywords.get('app_label'), 'jumelle_99')


class DepotAvecArborescenceTests(TestCase):
    """D8 (2026-09-05, `MEDIA_STORAGE_TIERING §8.6`) : le dépôt AVEC arborescence ne doit plus
    ÉCRASER un homonyme. C'était la seule voie du parc à le faire — le dépôt simple,
    `copy_into_app_input` et `UploadToUserPath` renomment tous à la collision.
    Le TEST_RUNNER commun sert un MEDIA_ROOT jetable : rien n'est écrit dans `media/`.
    """

    def setUp(self):
        from django.test import Client
        User = get_user_model()
        self.user = User.objects.create_user(username='depot_arbo', password='x')
        self.client = Client()
        self.client.force_login(self.user)

    def _deposer(self, contenu: bytes):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse
        import json as _json
        return self.client.post(reverse('filemanager:api_upload'), {
            'files': SimpleUploadedFile('notes.txt', contenu, content_type='text/plain'),
            'paths': _json.dumps(['dossier/notes.txt']),
        })

    def test_deux_depots_du_meme_chemin_donnent_deux_fichiers_distincts(self):
        from django.conf import settings
        r1 = self._deposer(b'premier')
        r2 = self._deposer(b'second')
        self.assertEqual((r1.status_code, r2.status_code), (200, 200), (r1.content, r2.content))
        p1 = r1.json()['uploaded'][0]['path']
        p2 = r2.json()['uploaded'][0]['path']
        self.assertNotEqual(p1, p2, 'le second dépôt a écrasé le premier')
        self.assertEqual((Path(settings.MEDIA_ROOT) / p1).read_bytes(), b'premier',
                         'le contenu du premier dépôt doit survivre au second')
        self.assertTrue(p2.startswith(f'users/{self.user.id}/temp/dossier/'),
                        'le renommage doit rester DANS le sous-dossier demandé')


class GestesDElementDansLArbreTests(SimpleTestCase):
    """Les gestes du menu « … » des cards — Partager…, Ajouter à la médiathèque…, Ajouter au RAG
    — dans l'arbre (2026-09-18, demande de Fabien : « en réutilisant au mieux l'existant, sans
    rien réinventer »). Ce qui est tenu : l'arbre n'ÉCRIT aucune de ces entrées (il appelle la
    brique commune par CHEMIN), il ne les demande que là où un fichier peut être une sortie, et
    « Envoyer vers… » — qui existait déjà — n'a pas bougé.
    """

    def _code(self):
        return _sans_commentaires((REPO / 'wama/filemanager/static' / FM_STATIC[0]).read_text(encoding='utf-8'))

    def test_l_arbre_appelle_la_brique_commune_par_chemin(self):
        code = self._code()
        self.assertIn('WamaCardMenu.entreesPourChemin(', code)
        self.assertIn('differe: true', code, "l'entrée doit être DIFFÉRÉE : le menu ne doit pas attendre le serveur")

    def test_l_arbre_n_ecrit_AUCUNE_des_entrees_ni_leurs_endpoints(self):
        """L'anti-duplication : les libellés et les routes des gestes vivent dans la brique, et
        nulle part ailleurs — sinon l'arbre dériverait de la card au premier changement."""
        code = self._code()
        for interdit in ('Partager…', 'Ajouter à la médiathèque', 'Ajouter au RAG',
                         '/media-library/api/export', '/common/api/rag', '/common/api/partage',
                         '/common/api/element-pour-chemin'):
            self.assertNotIn(interdit, code, f"l'arbre réécrit un geste de la brique : `{interdit}`")

    def test_les_depots_temporaires_et_les_montages_ne_sont_pas_interroges(self):
        code = self._code()
        i = code.index('WamaCardMenu.entreesPourChemin(')
        bloc = code[max(0, i - 900):i]
        self.assertIn("startsWith('mounts/')", bloc)
        self.assertIn(r'/^users\/\d+\/temp(\/|$)/', bloc)
        self.assertIn('!isMultiSelect', bloc, 'un fichier seul, comme sur les cards')

    def test_envoyer_vers_n_a_pas_bouge(self):
        code = self._code()
        self.assertIn('WamaSendTo.entreesPourChemins(cheminsEnvoyables)', code)
        self.assertIn('WamaSendTo.entreesPourDossier(folderPath)', code)

    def test_la_brique_traduit_le_groupe_differe_de_l_arbre(self):
        """`toCardMenuEntries` : `differe` + `charger` → `{chargement, charger}` au niveau du
        menu, jamais un sous-menu."""
        code = self._code()
        self.assertIn("typeof it.charger === 'function' && it.differe", code)
        self.assertIn('entry.chargement = true', code)


class DerivedAppTreeTests(TestCase):
    """L'arborescence d'apps de l'explorateur est DÉRIVÉE des déclarations (2026-10-02).

    Elle était écrite app par app dans `_app_folders_config` — un bloc à ajouter à la main pour
    chaque app —, les deux apps Lab y étaient citées par leur nom (ainsi que dans
    l'autorisation d'accès aux dossiers), et le client tenait une table jumelle des identifiants
    de nœuds, qui avait déjà divergé (dossiers de l'enhancer, galerie de l'avatarizer).
    Route §10.6 point 6.1 : monde → app → ses dossiers déclarés.
    """

    USER_ID = 7

    def _config(self):
        from wama.filemanager.views import _app_folders_config
        return _app_folders_config(self.USER_ID)

    def test_every_real_catalog_app_has_its_node_and_no_sandbox_app_does(self):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.sandbox import non_sandbox_apps
        top = {node['id']: node for node in self._config()}
        real = set(non_sandbox_apps(APP_CATALOG))
        self.assertTrue(real, "catalogue vide : rien n'est mesuré")
        self.assertEqual(real, {i for i, n in top.items() if n.get('app_node')})
        for app in real:
            with self.subTest(app=app):
                self.assertEqual(top[app]['text'], APP_CATALOG[app]['label'])
                self.assertEqual(top[app]['color'], APP_CATALOG[app]['color'],
                                 "l'icône prend la couleur d'identité de l'app")

    def test_the_folders_are_the_declared_ones(self):
        from wama.common.app_registry import DEFAULT_MEDIA_FOLDERS, app_media_folders
        from wama.common.utils.media_paths import app_media_dir
        top = {node['id']: node for node in self._config()}
        self.assertEqual(app_media_folders('transcriber'), DEFAULT_MEDIA_FOLDERS)
        self.assertEqual([c['id'] for c in top['transcriber']['children']],
                         ['transcriber_input', 'transcriber_output'])
        # Deux apps déclarent des dossiers propres : c'étaient les deux blocs spéciaux de la liste.
        self.assertEqual([c['id'] for c in top['enhancer']['children']],
                         ['enhancer_input_media', 'enhancer_input_audio',
                          'enhancer_output_media', 'enhancer_output_audio'])
        self.assertEqual([c['text'] for c in top['imager']['children']],
                         ['Prompts', 'References', 'Images', 'Vidéos'])
        leaf = top['imager']['children'][2]
        self.assertEqual(leaf['path'], app_media_dir('imager', self.USER_ID, 'output/image'))
        self.assertIn('text-success', leaf['icon'], "une sortie garde sa couleur de sortie")

    def test_another_world_is_a_folder_named_after_it(self):
        from wama.common.app_registry import WORLD_SECTIONS
        top = {node['id']: node for node in self._config()}
        lab = top['world_lab']
        self.assertTrue(lab.get('world_node'))
        self.assertEqual(lab['text'], WORLD_SECTIONS['lab']['label'])
        self.assertEqual({c['id'] for c in lab['children']}, {'cam_analyzer', 'face_analyzer'})
        # Le studio et la médiathèque sont des surfaces sans dossier d'app : pas de nœud.
        self.assertNotIn('world_transverse', top)

    def test_the_change_detector_and_the_access_rule_read_the_same_declaration(self):
        from wama.filemanager.views import _allowed_app_prefixes
        from wama.common.utils.media_paths import app_media_dir
        prefixes = _allowed_app_prefixes(self.USER_ID)
        for app in ('transcriber', 'cam_analyzer', 'face_analyzer'):
            with self.subTest(app=app):
                self.assertIn(app_media_dir(app, self.USER_ID, '').rstrip('/') + '/', prefixes)

    def test_neither_the_server_nor_the_client_names_an_app(self):
        """La liste et sa table jumelle ne reviennent pas : ni bloc par app côté serveur, ni
        table app → nœuds côté client."""
        import inspect
        from wama.filemanager import views
        from wama.common.app_registry import APP_CATALOG
        from wama.common.sandbox import non_sandbox_apps
        sources = {
            '_app_folders_config': inspect.getsource(views._app_folders_config),
            '_allowed_app_prefixes': inspect.getsource(views._allowed_app_prefixes),
            'autoExpandCurrentAppFolder': _sans_commentaires(
                (REPO / 'wama/filemanager/static' / FM_STATIC[0]).read_text(encoding='utf-8')
            ).split('function autoExpandCurrentAppFolder', 1)[1].split('\n    function ', 1)[0],
        }
        named = non_sandbox_apps(APP_CATALOG) + ['cam_analyzer', 'face_analyzer', 'wama_lab']
        for where, code in sources.items():
            for app in named:
                with self.subTest(where=where, app=app):
                    self.assertNotIn(f"'{app}'", code)

    def test_the_tree_endpoint_carries_the_flags_the_client_reads(self):
        user = get_user_model().objects.create_superuser('tree_admin', 't@test.local', 'x')
        self.client.force_login(user)
        from django.urls import reverse
        tree = self.client.get(reverse('filemanager:api_tree')).json()
        apps_section = next(n for n in tree if n['id'] == 'section_apps')
        nodes = {n['id']: n for n in apps_section['children']}
        self.assertTrue(nodes['transcriber']['app_node'])
        self.assertIn('--wama-app-color', nodes['transcriber']['a_attr']['style'])
        self.assertTrue(nodes['world_lab']['world_node'])
        self.assertTrue(nodes['world_lab']['children'][0]['app_node'])
