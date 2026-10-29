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
        def source(source_path, user, app_label='converter'):
            return app_label
        with patch('wama.common.app_registry.APP_CATALOG',
                   _catalogue_avec_jumelle('converter')), \
                patch.dict(IMPORTERS, {'converter': source}):
            fn = importer_for('jumelle_99')
        self.assertIsNotNone(fn, "la jumelle d'une source paramétrable doit résoudre")
        # Re-ciblage effectif (règle commune `sandbox.retarget_callable`, 2026-10-29) : l'importeur
        # de la source, appelé avec l'app_label de la JUMELLE — FIXÉ, même si l'appelant en passe un.
        self.assertIs(fn.__wrapped__, source)
        self.assertEqual('jumelle_99', fn('x', None))
        self.assertEqual('jumelle_99', fn('x', None, app_label='converter'))

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
        Depuis le 2026-10-16 il n'y a plus de liste : l'importeur dit le modèle qu'il a créé
        (celui de la JUMELLE) et le regroupement est celui de SA fabrique (`consolidate_arrival`).
        """
        import tempfile
        from django.apps import apps as django_apps
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.queue_manipulation import consolidate_arrival
        if 'converter_01' not in APP_CATALOG:
            self.skipTest('jumelle converter_01 non enregistrée sur cette machine')

        User = get_user_model()
        dev = User.objects.create_user('dev-filemanager-conso')
        fn = importer_for('converter_01')
        created = []
        with tempfile.TemporaryDirectory() as d:
            for nom in ('a.txt', 'b.txt'):
                src = Path(d) / nom
                src.write_text('x', encoding='utf-8')
                created.append(fn(src, dev))
        self.assertEqual({'converter_01.ConversionJob'}, {r['model'] for r in created})
        consolidate_arrival(django_apps.get_model(created[0]['model']),
                            [r['id'] for r in created], dev)

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
            self.assertIs(fn.__wrapped__, IMPORTERS[app])   # l'importeur de SA source, re-ciblé


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
        # Par SÉLECTION depuis le 2026-10-14 : un fichier seul garde les gestes de son élément,
        # N fichiers reçoivent « Ajouter N fichiers au RAG » — la brique tranche, pas l'arbre.
        self.assertIn('WamaCardMenu.entreesPourChemins(cheminsEnvoyables', code)
        self.assertIn('differe: true', code, "l'entrée doit être DIFFÉRÉE : le menu ne doit pas attendre le serveur")

    def test_l_arbre_n_ecrit_AUCUNE_des_entrees_ni_leurs_endpoints(self):
        """L'anti-duplication : les libellés et les routes des gestes vivent dans la brique, et
        nulle part ailleurs — sinon l'arbre dériverait de la card au premier changement."""
        code = self._code()
        for interdit in ('Partager…', 'Ajouter à la médiathèque', 'Ajouter au RAG',
                         '/media-library/api/export', '/common/api/rag', '/common/api/partage',
                         '/common/api/element-pour-chemin'):
            self.assertNotIn(interdit, code, f"l'arbre réécrit un geste de la brique : `{interdit}`")

    def test_the_rule_for_temporary_and_connected_files_lives_in_the_common_brick(self):
        """2026-10-14 : ces fichiers reçoivent désormais « Ajouter au RAG » — la règle « on
        n'interroge pas le serveur pour eux » est passée de l'arbre à la brique, qui seule décide
        des entrées (son comportement est tenu sous V8, `tests_queue_dnd`). L'arbre ne doit plus
        la porter : deux copies d'une règle finissent par en dire deux."""
        code = self._code()
        self.assertNotIn(r'/^users\/\d+\/temp(\/|$)/', code)
        brick = _sans_commentaires((REPO / 'wama/common/static/common/js/wama-card-menu.js')
                                   .read_text(encoding='utf-8'))
        self.assertIn("chemin.indexOf('mounts/') !== 0", brick)
        self.assertIn(r'/^users\/\d+\/temp(\/|$)/', brick)

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


class NetworkShareMountTests(SimpleTestCase):
    """Montage d'un partage réseau : le nom du serveur, l'identité envoyée, et ce que l'écran dit
    d'un refus (deux défauts mesurés le 2026-10-04 — nom court non résolu depuis WSL2, même
    message pour « invité refusé » et « identifiants refusés »).

    ⚠ Aucun montage réel : `subprocess.run` et la résolution de noms sont simulés, et les
    points de montage vont dans un dossier temporaire.
    """

    KNOWN = {'files.lab.example.org', '10.0.0.7'}

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        tuned = override_settings(WAMA_MOUNT_BASE=self.base.name,
                                  WAMA_SMB_DNS_SUFFIXES=['lab.example.org'],
                                  WAMA_SMB_DEFAULT_DOMAIN='LABDOMAIN')
        tuned.enable()
        self.addCleanup(tuned.disable)

        def lookup(name, *args, **kwargs):
            if name not in self.KNOWN:
                raise OSError('unknown host')
            return [(2, 1, 6, '', ('10.0.0.7', 445))]

        self.commands, self.credentials, self.stderr = [], [], ''

        def run(cmd, **kwargs):
            from types import SimpleNamespace
            self.commands.append(cmd)
            if cmd[0] == 'mountpoint':
                return SimpleNamespace(returncode=1, stdout='', stderr='')
            for option in cmd[-1].split(','):
                if option.startswith('credentials='):
                    self.credentials.append(Path(option.split('=', 1)[1]).read_text())
            return SimpleNamespace(returncode=1 if self.stderr else 0, stdout='', stderr=self.stderr)

        for target, replacement in (('socket.getaddrinfo', lookup), ('subprocess.run', run)):
            patcher = patch(target, side_effect=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _mount_command(self):
        return next(c for c in self.commands if 'cifs' in c)

    def test_a_short_server_name_is_tried_with_the_site_suffix(self):
        from wama.filemanager.views import _try_cifs_mount
        ok, path, error = _try_cifs_mount('files', 'saves', 'sub')
        self.assertTrue(ok, error)
        self.assertIn('//files.lab.example.org/saves', self._mount_command())
        # Le point de montage garde le nom SAISI : il ne change pas selon la résolution.
        self.assertTrue(path.endswith('files_saves/sub'), path)

    def test_a_full_name_or_an_address_is_never_rewritten(self):
        from wama.filemanager.views import _resolve_smb_host
        self.assertEqual(_resolve_smb_host('files.lab.example.org'), ('files.lab.example.org', None))
        self.assertEqual(_resolve_smb_host('10.0.0.7'), ('10.0.0.7', None))

    def test_an_unknown_short_name_says_to_type_the_full_name_and_mounts_nothing(self):
        from wama.filemanager.views import _try_cifs_mount
        ok, _, error = _try_cifs_mount('nowhere', 'saves')
        self.assertFalse(ok)
        self.assertIn('nom complet', error)
        self.assertFalse([c for c in self.commands if 'cifs' in c])

    def test_the_site_domain_applies_only_when_none_was_typed(self):
        from wama.filemanager.views import _smb_identity
        self.assertEqual(_smb_identity('jane', ''), ('jane', 'LABDOMAIN'))
        self.assertEqual(_smb_identity('jane', 'OTHER'), ('jane', 'OTHER'))
        self.assertEqual(_smb_identity('OTHER\\jane', ''), ('jane', 'OTHER'))
        self.assertEqual(_smb_identity('jane@lab.example.org', ''), ('jane@lab.example.org', ''))
        self.assertEqual(_smb_identity('', ''), ('', ''))

    def test_a_guest_rejection_and_a_credentials_rejection_are_told_apart(self):
        from wama.filemanager.views import _try_cifs_mount
        self.stderr = 'mount error(13): Permission denied'
        self.assertEqual(_try_cifs_mount('files', 'saves')[2], 'AUTH_REQUIRED')
        self.assertEqual(_try_cifs_mount('files', 'saves', username='jane', password='x')[2],
                         'AUTH_REFUSED')

    def test_the_password_never_reaches_the_command_line(self):
        from wama.filemanager.views import _try_cifs_mount
        _try_cifs_mount('files', 'saves', username='jane', password='s3cret', domain='LABDOMAIN')
        self.assertNotIn('s3cret', ' '.join(self._mount_command()))
        self.assertIn('password=s3cret', self.credentials[0])
        self.assertIn('domain=LABDOMAIN', self.credentials[0])


class NetworkShareScreenTests(TestCase):
    """Ce que les routes rendent à l'écran pour un partage réseau monté par le NOYAU (cifs) —
    le repli d'une installation sans rclone depuis le 2026-10-11 ; le montage par rclone est
    tenu par `SmbByRcloneTests`, avec les mêmes textes."""

    def setUp(self):
        from django.test import override_settings
        tuned = override_settings(WAMA_SMB_DEFAULT_DOMAIN='LABDOMAIN')
        tuned.enable()
        self.addCleanup(tuned.disable)
        for target, value in (('wama.filemanager.views._smb_by_rclone', False),
                              ('wama.filemanager.remote_mounts.rclone_providers', {})):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.user = get_user_model().objects.create_user('wama_share_user', password='x')
        self.client.force_login(self.user)

    def test_the_path_check_offers_the_site_domain(self):
        r = self.client.get('/filemanager/api/validate-path/', {'path': r'\\files\saves'})
        self.assertEqual(r.json().get('smb_default_domain'), 'LABDOMAIN')

    def test_rejected_credentials_are_reported_as_such_with_the_identity_tried(self):
        import json
        with patch('wama.filemanager.views._try_cifs_mount',
                   return_value=(False, None, 'AUTH_REFUSED')) as mount:
            r = self.client.post('/filemanager/api/mounts/', json.dumps(
                {'name': 'Saves', 'local_path': r'\\files\saves',
                 'smb_username': 'jane', 'smb_password': 'x'}), content_type='application/json')
        self.assertEqual(r.status_code, 401)
        body = r.json()
        self.assertTrue(body['needs_auth'] and body['auth_refused'])
        self.assertIn('LABDOMAIN\\jane', body['error'])
        self.assertEqual(mount.call_args.kwargs['domain'], 'LABDOMAIN')

    def test_a_guest_rejection_still_only_asks_for_credentials(self):
        import json
        with patch('wama.filemanager.views._try_cifs_mount',
                   return_value=(False, None, 'AUTH_REQUIRED')):
            r = self.client.post('/filemanager/api/mounts/', json.dumps(
                {'name': 'Saves', 'local_path': r'\\files\saves'}), content_type='application/json')
        body = r.json()
        self.assertTrue(body['needs_auth'])
        self.assertNotIn('auth_refused', body)


class FakeRcloneMixin:
    """Un rclone SIMULÉ pour les tests des dossiers distants : `subprocess.run` enregistre la
    commande ET l'environnement (c'est par lui que passent les identifiants), `rclone config
    providers` rend `self.providers`, et le réseau ne résout que `KNOWN_HOSTS`.

    ⚠ Aucun montage réel, aucun réseau. L'essai réel d'un partage se fait sur un VRAI serveur :
    un serveur SMB de test (impacket) a déclenché l'EDR du poste le 2026-10-11.
    """

    KNOWN_HOSTS = {'files.lab.example.org', '10.0.0.7'}

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self.base = tempfile.TemporaryDirectory()
        self.addCleanup(self.base.cleanup)
        tuned = override_settings(WAMA_MOUNT_BASE=self.base.name,
                                  WAMA_OUTBOUND_PROXY='http://proxy.example.org:3128',
                                  WAMA_SMB_DNS_SUFFIXES=['lab.example.org'],
                                  WAMA_SMB_DEFAULT_DOMAIN='LABDOMAIN')
        tuned.enable()
        self.addCleanup(tuned.disable)

        self.calls, self.server_says, self.providers = [], '', {}
        # Vrai : chaque point de montage est déjà monté (le vivant se règle par `_is_live`).
        self.already_mounted = False
        # Les arguments du lancement de `rclone mount` ; `mount_says` : son erreur, s'il échoue.
        self.mount_kwargs, self.mount_says = [], ''

        def run(cmd, **kwargs):
            from types import SimpleNamespace
            self.calls.append((cmd, kwargs.get('env') or {}))
            if cmd[1:2] == ['mount']:
                self.mount_kwargs.append(kwargs)
                if self.mount_says:
                    kwargs['stderr'].write(self.mount_says)
                    return SimpleNamespace(returncode=1, stdout=None, stderr=None)
            if cmd[0] == 'mountpoint':
                return SimpleNamespace(returncode=0 if self.already_mounted else 1,
                                       stdout='', stderr='')
            if cmd[1:2] == ['obscure']:
                return SimpleNamespace(returncode=0, stdout='OBSCURED\n', stderr='')
            if cmd[1:2] == ['lsjson'] and self.server_says:
                return SimpleNamespace(returncode=1, stdout='', stderr=self.server_says)
            return SimpleNamespace(returncode=0, stdout='[]', stderr='')

        def lookup(name, *args, **kwargs):
            if name not in self.KNOWN_HOSTS:
                raise OSError('unknown host')
            return [(2, 1, 6, '', ('10.0.0.7', 445))]

        for target, kwargs in (('subprocess.run', {'side_effect': run}),
                               ('socket.getaddrinfo', {'side_effect': lookup}),
                               ('wama.filemanager.remote_mounts.rclone_binary',
                                {'return_value': '/opt/rclone'}),
                               ('wama.filemanager.remote_mounts.rclone_providers',
                                {'side_effect': lambda: self.providers})):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.user = get_user_model().objects.create_user('wama_cloud_user', password='x')
        self.client.force_login(self.user)

    def _commands(self, verb):
        return [(cmd, env) for cmd, env in self.calls if cmd[1:2] == [verb]]

    def _post_mount(self, body):
        import json
        return self.client.post('/filemanager/api/mounts/', json.dumps(body),
                                content_type='application/json')


class RemoteMountTests(FakeRcloneMixin, TestCase):
    """Un nuage de fichiers (Nextcloud, WebDAV) connecté comme un dossier, par rclone
    (2026-10-10, `remote_mounts.py`)."""

    def _post(self, **body):
        return self._post_mount({'name': 'Nuage', 'local_path': 'https://cloud.example.org/', **body})

    def test_a_server_address_is_completed_with_the_nextcloud_webdav_path(self):
        from wama.filemanager.remote_mounts import webdav_config
        config = webdav_config('https://cloud.example.org/', 'jane.doe')
        self.assertEqual(config['url'], 'https://cloud.example.org/remote.php/dav/files/jane.doe/')
        self.assertEqual(config['vendor'], 'nextcloud')

    def test_an_address_copied_from_the_browser_opens_the_same_folder_over_webdav(self):
        # Vécu le 2026-10-10 : une page web gardée telle quelle rendait « 405 Method Not Allowed ».
        from wama.filemanager.remote_mounts import webdav_config
        config = webdav_config('https://cloud.example.org/apps/files/files?dir=/Projets/2026', 'jane')
        self.assertEqual(config['url'], 'https://cloud.example.org/remote.php/dav/files/jane/Projets/2026/')
        self.assertEqual(config['vendor'], 'nextcloud')

    def test_any_page_of_the_declared_cloud_is_completed_and_a_405_is_explained(self):
        from wama.accounts.models import InstanceApiKey
        from wama.filemanager.remote_mounts import _explain, webdav_config
        InstanceApiKey.objects.create(source='nextcloud', base_url='https://cloud.example.org')
        self.assertEqual(webdav_config('https://cloud.example.org/settings/user', 'jane')['url'],
                         'https://cloud.example.org/remote.php/dav/files/jane/')
        self.assertIn('page web', _explain("couldn't list files: 405 Method Not Allowed"))

    def test_a_full_webdav_address_is_kept_as_typed(self):
        from wama.filemanager.remote_mounts import webdav_config
        typed = 'https://cloud.example.org/remote.php/dav/files/jane.doe/Projets'
        self.assertEqual(webdav_config(typed, 'jane.doe')['url'], typed)
        other = webdav_config('https://dav.example.org/share/', 'jane')
        self.assertEqual((other['url'], other['vendor']), ('https://dav.example.org/share/', 'other'))

    def test_the_path_check_recognises_a_web_address(self):
        r = self.client.get('/filemanager/api/validate-path/',
                            {'path': 'https://cloud.example.org/remote.php/dav/files/jane/'})
        body = r.json()
        self.assertTrue(body['is_remote'])
        self.assertEqual(body['remote_vendor'], 'nextcloud')
        self.assertNotIn('is_smb', body)

    def test_the_password_never_reaches_a_command_line_and_the_proxy_is_passed(self):
        r = self._post(username='jane', password='s3cret')
        self.assertTrue(r.json().get('success'), r.json())
        for cmd, env in self.calls:
            self.assertNotIn('s3cret', ' '.join(cmd))
        mount_cmd, env = self._commands('mount')[0]
        self.assertIn('--daemon', mount_cmd)
        self.assertEqual(env['RCLONE_WEBDAV_PASS'], 'OBSCURED')
        self.assertEqual(env['RCLONE_WEBDAV_USER'], 'jane')
        self.assertEqual(env['HTTPS_PROXY'], 'http://proxy.example.org:3128')

    def test_the_secret_is_kept_encrypted_and_the_folder_remembered(self):
        from django.db import connection

        from wama.filemanager.models import MountedFolder
        self._post(username='jane', password='s3cret')
        mount = MountedFolder.objects.get(user=self.user)
        self.assertEqual(mount.remote_secret, 's3cret')
        self.assertEqual(mount.remote_config['user'], 'jane')
        with connection.cursor() as cur:
            cur.execute('SELECT remote_secret FROM filemanager_mountedfolder WHERE id = %s',
                        [mount.id])
            self.assertNotIn('s3cret', cur.fetchone()[0])

    def test_refused_credentials_say_so_and_nothing_is_mounted_or_saved(self):
        from wama.filemanager.models import MountedFolder
        self.server_says = 'Failed to lsjson: 401 Unauthorized'
        r = self._post(username='jane', password='wrong')
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()['auth_refused'])
        self.assertIn('par le navigateur', r.json()['error'])
        self.assertFalse(self._commands('mount'))
        self.assertFalse(MountedFolder.objects.filter(user=self.user).exists())

    def test_a_live_mount_is_never_lent_without_its_credentials(self):
        # Le point de montage est nommé par le serveur, l'identifiant et le chemin — pas par le
        # compte WAMA : un autre compte qui tape la même adresse et le même identifiant tombe
        # sur le même montage. Il ne l'obtient qu'avec le bon mot de passe (2026-10-12).
        from wama.filemanager.models import MountedFolder
        self.already_mounted = True
        self.server_says = 'Failed to lsjson: 401 Unauthorized'
        with patch('wama.filemanager.remote_mounts._is_live', return_value=True):
            r = self._post(username='jane', password='guess')
            self.assertEqual(r.status_code, 401)
            self.assertFalse(MountedFolder.objects.exists())

            # Contre-épreuve : avec le bon mot de passe, le montage vivant est réutilisé tel quel.
            self.server_says = ''
            r = self._post(username='jane', password='s3cret')
        self.assertTrue(r.json().get('success'), r.json())
        self.assertFalse(self._commands('mount'))

    def test_the_mount_never_waits_on_output_pipes_the_daemon_keeps_open(self):
        # Mesuré le 2026-10-12 : nuage monté en 2 s, réponse « échec » au bout de 90 s, parce
        # que la lecture des tubes de `rclone mount --daemon` ne finissait jamais.
        import subprocess
        self.assertTrue(self._post(username='jane', password='s3cret').json().get('success'))
        kwargs = self.mount_kwargs[0]
        self.assertNotIn('capture_output', kwargs)
        self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
        self.assertNotIn(kwargs['stderr'], (subprocess.PIPE, None))

    def test_an_error_of_the_mount_itself_is_still_read_and_explained(self):
        from wama.filemanager.models import MountedFolder
        self.mount_says = 'Failed to mount: 401 Unauthorized'
        r = self._post(username='jane', password='s3cret')
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()['auth_refused'])
        self.assertFalse(MountedFolder.objects.exists())

    def test_connecting_the_same_folder_twice_keeps_a_single_record(self):
        # Vécu le 2026-10-12 : deux enregistrements d'un même montage, et le dossier
        # « réapparaissait » au premier retrait.
        from wama.filemanager.models import MountedFolder
        first = self._post(username='jane', password='s3cret').json()
        again = self._post(username='jane', password='s3cret').json()
        self.assertTrue(again['success'])
        self.assertTrue(again['already'])
        self.assertEqual(again['id'], first['id'])
        self.assertEqual(MountedFolder.objects.filter(user=self.user).count(), 1)
        self.client.post(f"/filemanager/api/mounts/{first['id']}/delete/")
        self.assertFalse(MountedFolder.objects.filter(user=self.user).exists())

    def test_missing_credentials_are_asked_before_any_network_call(self):
        r = self._post(username='jane')
        self.assertEqual(r.status_code, 401)
        self.assertTrue(r.json()['needs_auth'])
        self.assertFalse(self.calls)

    def test_a_fallen_remote_folder_is_remounted_with_its_stored_secret(self):
        from wama.filemanager.models import MountedFolder
        from wama.filemanager.remote_mounts import ensure_mounted, webdav_config
        mount = MountedFolder.objects.create(
            user=self.user, name='Nuage', local_path='/nowhere/dav',
            remote_config=webdav_config('https://cloud.example.org/', 'jane'),
            remote_secret='s3cret')
        self.assertTrue(ensure_mounted(mount))
        self.assertEqual(self._commands('mount')[0][1]['RCLONE_WEBDAV_PASS'], 'OBSCURED')
        mount.refresh_from_db()
        self.assertTrue(mount.local_path.startswith(self.base.name), mount.local_path)

    # ── Connexion par le navigateur (Nextcloud Login Flow v2, 2026-10-11) ──────────────────

    def _fake_cloud(self, poll_endpoint='https://cloud.example.org/login/v2/poll'):
        """Simule le nuage : le flux s'ouvre, reste en attente une fois, puis est accordé."""
        from types import SimpleNamespace
        self.http, self.granted = [], False

        def reply(status, data=None):
            return SimpleNamespace(status_code=status, ok=status < 400, json=lambda: data or {})

        def http(method, url, **kwargs):
            self.http.append((method, url, kwargs))
            if url.endswith('/index.php/login/v2'):
                return reply(200, {'login': 'https://cloud.example.org/login/v2/flow/abc',
                                   'poll': {'token': 'poll-token', 'endpoint': poll_endpoint}})
            if url == poll_endpoint:
                if not self.granted:
                    self.granted = True
                    return reply(404)
                return reply(200, {'server': 'https://cloud.example.org',
                                   'loginName': 'jane@example.org', 'appPassword': 'app-pw'})
            if '/ocs/v2.php/cloud/user' in url:
                return reply(200, {'ocs': {'data': {'id': 'jane'}}})
            return reply(200)

        patcher = patch('wama.filemanager.remote_mounts._http', side_effect=http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _start_flow(self):
        import json
        return self.client.post('/filemanager/api/mounts/login-flow/', json.dumps(
            {'name': 'Nuage', 'local_path': 'https://cloud.example.org/apps/files/'}),
            content_type='application/json')

    def test_the_browser_login_mounts_the_folder_with_the_granted_app_password(self):
        from wama.filemanager.models import MountedFolder
        self._fake_cloud()
        started = self._start_flow().json()
        self.assertEqual(started['login_url'], 'https://cloud.example.org/login/v2/flow/abc')
        self.assertNotIn('poll-token', str(started))      # le jeton reste côté serveur
        poll_url = f"/filemanager/api/mounts/login-flow/{started['flow_id']}/"

        self.assertEqual(self.client.post(poll_url).json(), {'status': 'pending'})
        self.assertFalse(self._commands('mount'))
        self.assertTrue(self.client.post(poll_url).json().get('success'))

        mount = MountedFolder.objects.get(user=self.user)
        self.assertEqual(mount.remote_secret, 'app-pw')
        # L'identifiant DU SERVEUR nomme le dossier, le nom de connexion authentifie.
        self.assertEqual(mount.remote_config['url'],
                         'https://cloud.example.org/remote.php/dav/files/jane/')
        self.assertEqual(self._commands('mount')[0][1]['RCLONE_WEBDAV_USER'], 'jane@example.org')
        self.assertEqual(self.client.post(poll_url).status_code, 404)   # flux consommé

    def test_a_poll_address_on_another_host_is_refused(self):
        self._fake_cloud(poll_endpoint='https://elsewhere.example.net/poll')
        r = self._start_flow()
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('flow_id', r.json())

    def test_an_app_password_granted_but_unusable_or_released_is_revoked(self):
        from wama.filemanager.models import MountedFolder
        self._fake_cloud()
        self.server_says = 'Failed to lsjson: 401 Unauthorized'
        poll_url = f"/filemanager/api/mounts/login-flow/{self._start_flow().json()['flow_id']}/"
        self.client.post(poll_url)
        self.assertEqual(self.client.post(poll_url).status_code, 401)
        revoked = [kw for method, url, kw in self.http if method == 'DELETE']
        self.assertEqual(revoked[0]['auth'], ('jane@example.org', 'app-pw'))
        self.assertFalse(MountedFolder.objects.filter(user=self.user).exists())

        # Un dossier retiré révoque aussi le mot de passe qu'il tenait du navigateur.
        self.server_says, self.http = '', []
        mount = MountedFolder.objects.create(
            user=self.user, name='Nuage', local_path='/nowhere/dav', remote_secret='app-pw',
            remote_config={'type': 'webdav', 'url': 'https://cloud.example.org/remote.php/dav/files/jane/',
                           'user': 'jane', 'login': 'jane@example.org', 'login_flow': True,
                           'server': 'https://cloud.example.org'})
        self.client.post(f'/filemanager/api/mounts/{mount.id}/delete/')
        self.assertEqual([(m, u) for m, u, _ in self.http],
                         [('DELETE', 'https://cloud.example.org/ocs/v2.php/core/apppassword')])

    def test_a_browser_login_ending_after_a_typed_connection_adds_nothing_and_revokes_its_password(self):
        # Le scénario du 2026-10-12 : l'accès accordé dans le navigateur, le montage en cours,
        # et « Connecter » cliqué entre-temps avec les identifiants remplis par le navigateur.
        from wama.filemanager.models import MountedFolder
        self._fake_cloud()
        poll_url = f"/filemanager/api/mounts/login-flow/{self._start_flow().json()['flow_id']}/"
        self.client.post(poll_url)                                         # en attente
        typed = self._post_mount({'name': 'Nuage', 'username': 'jane', 'password': 's3cret',
                                  'local_path': 'https://cloud.example.org/apps/files/'}).json()
        self.http = []
        granted = self.client.post(poll_url).json()
        self.assertTrue(granted['already'], granted)
        self.assertEqual(granted['id'], typed['id'])
        self.assertEqual(MountedFolder.objects.get(user=self.user).remote_secret, 's3cret')
        revoked = [(m, kw['auth']) for m, u, kw in self.http if m == 'DELETE']
        self.assertEqual(revoked, [('DELETE', ('jane@example.org', 'app-pw'))])

    def test_a_folder_added_with_a_typed_password_is_never_revoked_on_removal(self):
        # Le mot de passe saisi peut être celui du COMPTE : WAMA ne le révoque jamais.
        from wama.filemanager.models import MountedFolder
        self._fake_cloud()
        self._post(username='jane', password='s3cret')
        mount = MountedFolder.objects.get(user=self.user)
        self.client.post(f'/filemanager/api/mounts/{mount.id}/delete/')
        self.assertFalse(MountedFolder.objects.filter(user=self.user).exists())
        self.assertEqual(self.http, [])

    def test_an_expired_browser_login_is_dropped_without_asking_the_cloud(self):
        from wama.filemanager import remote_mounts, views
        self._fake_cloud()
        flow_id = self._start_flow().json()['flow_id']
        session = self.client.session
        flows = session[views._LOGIN_FLOWS_KEY]
        flows[flow_id]['started'] -= remote_mounts.LOGIN_FLOW_LIFETIME_S + 1
        session[views._LOGIN_FLOWS_KEY] = flows
        session.save()
        self.http = []
        poll_url = f'/filemanager/api/mounts/login-flow/{flow_id}/'
        self.assertEqual(self.client.post(poll_url).status_code, 410)
        self.assertEqual(self.http, [])
        self.assertEqual(self.client.post(poll_url).status_code, 404)


class StorageTypeTests(SimpleTestCase):
    """Les TYPES de stockage déclarés (`remote_mounts.STORAGE_TYPES`, 2026-10-11) : ce que
    l'utilisateur saisit est déclaré, la nature de chaque option vient de rclone."""

    def test_the_form_takes_the_secret_nature_and_help_from_rclone(self):
        from wama.filemanager import remote_mounts
        meta = {'smb': {'user': {'Name': 'user', 'Help': 'SMB username.'},
                        'pass': {'Name': 'pass', 'IsPassword': True, 'Help': 'SMB password.'},
                        'domain': {'Name': 'domain', 'Help': 'Domain name.'}}}
        with patch.object(remote_mounts, 'rclone_providers', return_value=meta):
            form = remote_mounts.storage_form('smb', {'smb_domain': 'LABDOMAIN'})
        fields = {f['name']: f for f in form['fields']}
        self.assertTrue(fields['smb_password']['secret'])
        self.assertFalse(fields['smb_username']['secret'])
        self.assertEqual(fields['smb_password']['help'], 'SMB password.')
        self.assertEqual(fields['smb_domain']['value'], 'LABDOMAIN')
        self.assertTrue(form['guest'])

    def test_without_rclone_the_declared_secret_still_hides_the_password(self):
        from wama.filemanager import remote_mounts
        with patch.object(remote_mounts, 'rclone_providers', return_value={}):
            fields = {f['name']: f for f in remote_mounts.storage_form('webdav')['fields']}
        self.assertTrue(fields['password']['secret'])
        self.assertFalse(fields['username']['secret'])

    def test_every_option_passed_to_rclone_is_one_the_installed_rclone_knows(self):
        # Le type déclaré n'invente pas d'option : chaque `RCLONE_<STOCKAGE>_<OPTION>` doit
        # exister dans le rclone installé (sinon rclone l'ignorerait en silence).
        from wama.filemanager import remote_mounts
        providers = remote_mounts.rclone_providers()
        if not providers:
            self.skipTest('rclone absent de cet environnement')
        samples = {'webdav': ({'type': 'webdav', 'url': 'https://x/'}, 'pw'),
                   'smb': (remote_mounts.smb_config('files', 'files', 'saves', '', 'jane', 'D'), 'pw'),
                   'drive': ({'type': 'drive'}, '{}'),
                   'onedrive': ({'type': 'onedrive', 'drive_id': 'd', 'drive_type': 'business'}, '{}')}
        for st in remote_mounts.STORAGE_TYPES:
            known = providers.get(st.backend)
            self.assertTrue(known, f'{st.backend} inconnu du rclone installé')
            config, secret = samples[st.key]
            with patch.object(remote_mounts, 'oauth_client', return_value=('id', 'secret')):
                options = remote_mounts._OPTIONS[st.key](config, secret)
            self.assertFalse(set(options) - set(known), st.key)
            self.assertFalse({f.option for f in st.fields} - set(known), st.key)


class SmbByRcloneTests(FakeRcloneMixin, TestCase):
    """Un partage réseau monté par rclone (2026-10-11) : mêmes résolution de nom, même identité
    envoyée et mêmes textes de refus que le montage du noyau — mais sans `sudo`, et le mot de
    passe gardé chiffré permet de remonter le partage au redémarrage."""

    def setUp(self):
        super().setUp()
        self.providers = {'smb': {'host': {}, 'user': {}, 'pass': {'IsPassword': True},
                                  'domain': {}}}

    def _share(self, **body):
        return self._post_mount({'name': 'Saves', 'local_path': r'\\files\saves\sub', **body})

    def test_a_share_is_mounted_by_rclone_with_the_password_kept_encrypted(self):
        from wama.filemanager.models import MountedFolder
        r = self._share(smb_username='jane', smb_password='s3cret')
        self.assertTrue(r.json().get('success'), r.json())
        cmd, env = self._commands('mount')[0]
        self.assertEqual(cmd[2], ':smb:saves/sub')
        self.assertNotIn('sudo', cmd)
        for command, _ in self.calls:
            self.assertNotIn('s3cret', ' '.join(command))
        self.assertEqual(env['RCLONE_SMB_HOST'], 'files.lab.example.org')
        self.assertEqual((env['RCLONE_SMB_USER'], env['RCLONE_SMB_DOMAIN']), ('jane', 'LABDOMAIN'))
        self.assertEqual(env['RCLONE_SMB_PASS'], 'OBSCURED')
        self.assertNotIn('HTTPS_PROXY', env)        # réseau local : aucun proxy
        mount = MountedFolder.objects.get(user=self.user)
        self.assertEqual((mount.remote_config['type'], mount.remote_secret), ('smb', 's3cret'))
        self.assertIsNone(mount.smb_config)

    def test_a_guest_refusal_asks_for_credentials_and_a_bad_password_names_the_identity(self):
        self.server_says = 'couldn\'t connect SMB: response error: The attempted logon is invalid.'
        body = self._share().json()
        self.assertTrue(body['needs_auth'])
        self.assertNotIn('auth_refused', body)
        body = self._share(smb_username='jane', smb_password='x').json()
        self.assertTrue(body['auth_refused'])
        self.assertIn('LABDOMAIN\\jane', body['error'])
        self.assertFalse(self._commands('mount'))

    def test_an_unknown_short_name_mounts_nothing(self):
        r = self._post_mount({'name': 'X', 'local_path': r'\\nowhere\saves'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('nom complet', r.json()['error'])
        self.assertFalse(self.calls)

    def test_a_share_whose_password_is_kept_is_remounted_at_restart(self):
        from wama.filemanager.models import MountedFolder
        from wama.filemanager.remote_mounts import ensure_mounted, smb_config
        mount = MountedFolder.objects.create(
            user=self.user, name='Saves', local_path='/nowhere/smb', remote_secret='s3cret',
            remote_config=smb_config('files', 'files.lab.example.org', 'saves', 'sub', 'jane', 'D'))
        self.assertTrue(ensure_mounted(mount))
        self.assertEqual(self._commands('mount')[0][1]['RCLONE_SMB_PASS'], 'OBSCURED')

    def test_without_rclone_the_kernel_mount_still_serves(self):
        with patch('wama.filemanager.remote_mounts.rclone_binary', return_value=None), \
                patch('wama.filemanager.views._try_cifs_mount',
                      return_value=(True, '/mnt/x', None)) as cifs:
            r = self._share()
        self.assertTrue(r.json().get('success'))
        cifs.assert_called_once()


class OAuthStorageTests(FakeRcloneMixin, TestCase):
    """Google Drive et OneDrive : l'accès s'accorde dans le navigateur (OAuth), le jeton est
    gardé chiffré et prêté à rclone (2026-10-11). Le fournisseur est simulé (`_http`)."""

    def setUp(self):
        super().setUp()
        from wama.accounts.models import InstanceApiKey
        self.providers = {'drive': {}, 'onedrive': {}}
        InstanceApiKey.objects.create(source='google_drive', api_key='gid:gsecret')
        InstanceApiKey.objects.create(source='onedrive', api_key='mid:msecret',
                                      base_url='https://login.microsoftonline.com/tenant-1')
        self.http = []

        def reply(status, data=None):
            from types import SimpleNamespace
            return SimpleNamespace(status_code=status, ok=status < 400, json=lambda: data or {})

        def http(method, url, **kwargs):
            self.http.append((method, url, kwargs))
            if url.endswith('/token'):
                return reply(200, {'access_token': 'at', 'refresh_token': 'refresh-xyz',
                                   'expires_in': 3600, 'token_type': 'Bearer'})
            if 'drive/v3/about' in url:
                return reply(200, {'user': {'emailAddress': 'jane@example.org'}})
            if url.endswith('/me/drive'):
                return reply(200, {'id': 'drive-1', 'driveType': 'business',
                                   'owner': {'user': {'email': 'jane@example.org'}}})
            return reply(200)

        patcher = patch('wama.filemanager.remote_mounts._http', side_effect=http)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _start(self, kind):
        import json
        return self.client.post('/filemanager/api/mounts/oauth/', json.dumps(
            {'type': kind, 'name': ''}), content_type='application/json').json()

    def _grant(self, kind):
        from urllib.parse import parse_qs, urlsplit
        started = self._start(kind)
        query = parse_qs(urlsplit(started['login_url']).query)
        r = self.client.get('/filemanager/api/mounts/oauth/callback/',
                            {'state': query['state'][0], 'code': 'the-code'})
        return started, query, r

    def test_a_storage_is_offered_only_once_its_client_is_set(self):
        from wama.accounts.models import InstanceApiKey
        offered = {s['key'] for s in self.client.get('/filemanager/api/mounts/').json()['storages']}
        self.assertEqual(offered, {'drive', 'onedrive'})
        InstanceApiKey.objects.filter(source='google_drive').delete()
        offered = {s['key'] for s in self.client.get('/filemanager/api/mounts/').json()['storages']}
        self.assertEqual(offered, {'onedrive'})

    def test_the_drive_access_granted_in_the_browser_mounts_the_folder(self):
        import json

        from wama.filemanager.models import MountedFolder
        started, query, r = self._grant('drive')
        self.assertEqual(query['client_id'], ['gid'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertTrue(query['redirect_uri'][0].endswith('/filemanager/api/mounts/oauth/callback/'))
        self.assertEqual(r.status_code, 200)
        exchange = next(kw for m, u, kw in self.http if u.endswith('/token'))
        self.assertEqual(exchange['data']['code'], 'the-code')
        self.assertTrue(exchange['data']['code_verifier'])

        poll = self.client.post(f"/filemanager/api/mounts/login-flow/{started['flow_id']}/").json()
        self.assertTrue(poll.get('success'), poll)
        mount = MountedFolder.objects.get(user=self.user)
        self.assertEqual(json.loads(mount.remote_secret)['refresh_token'], 'refresh-xyz')
        self.assertEqual(mount.remote_config['account'], 'jane@example.org')
        cmd, env = self._commands('mount')[0]
        self.assertEqual(cmd[2], ':drive:')
        self.assertNotIn('refresh-xyz', ' '.join(cmd))
        self.assertEqual(json.loads(env['RCLONE_DRIVE_TOKEN'])['refresh_token'], 'refresh-xyz')
        self.assertEqual(env['RCLONE_DRIVE_CLIENT_ID'], 'gid')
        self.assertEqual(env['HTTPS_PROXY'], 'http://proxy.example.org:3128')

    def test_onedrive_uses_the_declared_directory_and_its_drive(self):
        _, query, _ = self._grant('onedrive')
        token_url = next(u for m, u, kw in self.http if u.endswith('/token'))
        self.assertTrue(token_url.startswith('https://login.microsoftonline.com/tenant-1/'))
        env = self._commands('mount')[0][1]
        self.assertEqual((env['RCLONE_ONEDRIVE_DRIVE_ID'], env['RCLONE_ONEDRIVE_DRIVE_TYPE']),
                         ('drive-1', 'business'))

    def test_a_return_with_an_unknown_state_mounts_nothing(self):
        from wama.filemanager.models import MountedFolder
        self._start('drive')
        r = self.client.get('/filemanager/api/mounts/oauth/callback/',
                            {'state': 'forged', 'code': 'x'})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.http, [])
        self.assertFalse(MountedFolder.objects.exists())

    def test_a_refused_consent_is_told_to_the_waiting_window(self):
        from urllib.parse import parse_qs, urlsplit
        started = self._start('drive')
        state = parse_qs(urlsplit(started['login_url']).query)['state'][0]
        self.client.get('/filemanager/api/mounts/oauth/callback/',
                        {'state': state, 'error': 'access_denied'})
        r = self.client.post(f"/filemanager/api/mounts/login-flow/{started['flow_id']}/")
        self.assertEqual(r.status_code, 400)
        self.assertIn('accordé', r.json()['error'])

    def test_removing_a_drive_folder_revokes_its_token(self):
        from wama.filemanager.models import MountedFolder
        self._grant('drive')
        mount = MountedFolder.objects.get(user=self.user)
        self.http = []
        self.client.post(f'/filemanager/api/mounts/{mount.id}/delete/')
        revoked = [(u, kw['data']) for m, u, kw in self.http if u.endswith('/revoke')]
        self.assertEqual(revoked, [('https://oauth2.googleapis.com/revoke', {'token': 'refresh-xyz'})])

    def test_granting_the_same_drive_again_keeps_one_folder_with_the_new_token(self):
        # Révoquer le jeton en trop retirerait l'accès entier chez Google (même autorisation),
        # celui du dossier déjà connecté compris : le neuf remplace l'ancien, rien n'est révoqué.
        from wama.filemanager.models import MountedFolder
        self._grant('drive')
        mount = MountedFolder.objects.get(user=self.user)
        mount.remote_secret = 'older-token'
        mount.save(update_fields=['remote_secret'])
        self.http = []
        started, _, _ = self._grant('drive')
        poll = self.client.post(f"/filemanager/api/mounts/login-flow/{started['flow_id']}/").json()
        self.assertTrue(poll['already'], poll)
        mount.refresh_from_db()
        self.assertIn('refresh-xyz', mount.remote_secret)
        self.assertEqual(MountedFolder.objects.filter(user=self.user).count(), 1)
        self.assertFalse([u for m, u, kw in self.http if u.endswith('/revoke')])

    def test_the_token_is_renewed_and_kept_before_a_remount(self):
        import json

        from wama.filemanager.models import MountedFolder
        from wama.filemanager.remote_mounts import ensure_mounted
        mount = MountedFolder.objects.create(
            user=self.user, name='Drive', local_path='/nowhere/drive',
            remote_config={'type': 'drive', 'account': 'jane@example.org'},
            remote_secret=json.dumps({'access_token': 'old', 'refresh_token': 'refresh-xyz'}))
        self.assertTrue(ensure_mounted(mount))
        mount.refresh_from_db()
        self.assertEqual(json.loads(mount.remote_secret)['access_token'], 'at')
        renewal = next(kw for m, u, kw in self.http if u.endswith('/token'))
        self.assertEqual(renewal['data']['grant_type'], 'refresh_token')
