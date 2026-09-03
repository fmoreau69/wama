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
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.filemanager.views import IMPORTERS, importer_for, receivable_apps


def _catalogue_avec_jumelle(source):
    """Un APP_CATALOG minimal portant une jumelle factice de `source`."""
    from wama.common.app_registry import APP_CATALOG
    return {**APP_CATALOG,
            'jumelle_99': {'label': 'Jumelle 99', 'generated_from': source,
                           'input_extensions': ('.txt',)}}


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


class ToutImporteurEstDerivableTests(TestCase):
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
