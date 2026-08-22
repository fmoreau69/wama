"""Tests du mécanisme UNIVERSEL d'actualisation des catalogues (`common/registries.py`).

Ce qui est vérifié est ce qui justifie le mécanisme : qu'un catalogue hérite de son bouton sans
code, que la NATURE déclarée empêche un bouton menteur, et qu'une fonction ajoutée — ou supprimée —
pendant que le serveur tourne devient visible sans redémarrage.
"""
from pathlib import Path

from django.test import TestCase

from .registries import (DERIVE, MESURE, REGISTRES, Registre, Resultat, autorise, enregistrer,
                         etat, get, rafraichir)


class _Anon:
    is_authenticated = False
    is_staff = False


class _Compte:
    is_authenticated = True
    is_staff = False


class _Staff:
    is_authenticated = True
    is_staff = True


class ContratTest(TestCase):
    """Le registre refuse les déclarations incohérentes AU MOMENT de la déclaration."""

    def tearDown(self):
        for cle in ('_t_derive', '_t_scan', '_t_nature', '_t_dup', '_t_casse'):
            REGISTRES.pop(cle, None)

    def test_derive_avec_rafraichisseur_refuse(self):
        # S'il a un rafraîchisseur, c'est qu'il stocke : sa nature est mal déclarée.
        with self.assertRaises(ValueError):
            enregistrer(Registre(cle='_t_derive', nom='x', nature=DERIVE, source='s',
                                 rafraichir=lambda: Resultat()))

    def test_non_derive_sans_rafraichisseur_refuse(self):
        with self.assertRaises(ValueError):
            enregistrer(Registre(cle='_t_scan', nom='x', nature='scan', source='s'))

    def test_nature_inconnue_refusee(self):
        with self.assertRaises(ValueError):
            enregistrer(Registre(cle='_t_nature', nom='x', nature='inventee', source='s',
                                 rafraichir=lambda: Resultat()))

    def test_cle_en_double_refusee(self):
        enregistrer(Registre(cle='_t_dup', nom='x', nature=DERIVE, source='s'))
        with self.assertRaises(ValueError):
            enregistrer(Registre(cle='_t_dup', nom='y', nature=DERIVE, source='s'))

    def test_cle_inconnue_nomme_les_cles_connues(self):
        with self.assertRaises(KeyError) as ctx:
            get('inexistant')
        self.assertIn('modeles', str(ctx.exception))

    def test_une_exception_est_RAPPORTEE_pas_propagee(self):
        # Une actualisation qui plante ne doit pas emporter la page qu'elle sert.
        def _boum():
            raise RuntimeError('boum')
        enregistrer(Registre(cle='_t_casse', nom='x', nature=MESURE, source='s',
                             rafraichir=_boum))
        res = rafraichir('_t_casse')
        self.assertFalse(res.ok)
        self.assertIn('boum', ' '.join(res.messages))


class DeclarationsTest(TestCase):
    """Les registres réels de WAMA."""

    def test_les_sept_registres_sont_declares(self):
        for cle in ('modeles', 'apps', 'fonctions', 'skills', 'librairies', 'licences', 'rag'):
            self.assertIn(cle, REGISTRES)

    def test_un_derive_n_a_pas_de_rafraichisseur(self):
        derives = [r for r in REGISTRES.values() if r.nature == DERIVE]
        self.assertTrue(derives)
        for r in derives:
            self.assertIsNone(r.rafraichir, f"{r.cle} : un dérivé n'a rien à actualiser")

    def test_un_derive_le_DIT_au_lieu_de_faire_semblant(self):
        res = rafraichir('licences')
        self.assertTrue(res.ok)
        self.assertIn('rien à actualiser', ' '.join(res.messages))

    def test_l_etat_expose_ce_qui_est_actualisable(self):
        par_cle = {e['cle']: e for e in etat()}
        self.assertTrue(par_cle['fonctions']['actualisable'])
        self.assertFalse(par_cle['licences']['actualisable'])
        self.assertEqual(par_cle['modeles']['periodique'], 'model-manager-reconcile')

    def test_le_lien_vers_le_kind_est_declare_quand_il_existe(self):
        # 4 des 7 registres correspondent à un kind de manifeste — l'info est vraie et utile,
        # mais ce n'est pas la clé (3 kinds n'ont aucune page, 3 pages ne sont pas des kinds).
        avec_kind = {r.cle for r in REGISTRES.values() if r.manifest_kind}
        self.assertEqual(avec_kind, {'modeles', 'apps', 'fonctions', 'librairies'})
        from .manifests import MANIFEST_KINDS
        for cle in avec_kind:
            self.assertIn(REGISTRES[cle].manifest_kind, MANIFEST_KINDS)

    def test_aucun_registre_sans_source_declaree(self):
        # « Actualiser quoi ? » doit avoir une réponse affichable, sinon le bouton est opaque.
        for r in REGISTRES.values():
            self.assertTrue(r.source, f"{r.cle} : source non déclarée")
            self.assertTrue(r.description, f"{r.cle} : description non déclarée")


class PermissionTest(TestCase):

    def test_staff_exige_pour_un_registre_qui_ecrit(self):
        self.assertFalse(autorise(get('apps'), _Anon()))
        self.assertFalse(autorise(get('apps'), _Compte()))
        self.assertTrue(autorise(get('apps'), _Staff()))

    def test_un_registre_sans_effet_de_bord_partage_est_ouvert(self):
        self.assertTrue(autorise(get('skills'), _Compte()))

    def test_rafraichir_refuse_et_le_DIT(self):
        res = rafraichir('apps', user=_Compte())
        self.assertFalse(res.ok)
        self.assertIn('réservé', ' '.join(res.messages))


class RechargementAChaudTest(TestCase):
    """LE cas qui justifie le mécanisme : `load_all()` ne voit pas les nouveautés.

    `importlib.import_module` rend le module DÉJÀ importé — une fonction ajoutée pendant que le
    serveur tourne reste donc invisible jusqu'au redémarrage. C'est ce que l'actualisation corrige.
    """
    SONDE = Path('wama_data/functions/temporal/_sonde_test.py')
    INIT = Path('wama_data/functions/temporal/__init__.py')
    SOURCE = '''from wama.common.catalog.function_catalog import (FunctionCategory, FunctionSpec,
                                                  PortSpec, register)
from wama.common.catalog.data_types import DataType
register(FunctionSpec(key='_sonde_test', name='Sonde', description='test',
                      category=FunctionCategory.TRANSFORM,
                      inputs=[PortSpec('e', DataType.TABLE)],
                      outputs=[PortSpec('s', DataType.TABLE)], fn=lambda x: x))
'''

    def setUp(self):
        self.init_orig = self.INIT.read_text(encoding='utf-8')

    def tearDown(self):
        self.SONDE.unlink(missing_ok=True)
        self.INIT.write_text(self.init_orig, encoding='utf-8')
        rafraichir('fonctions')

    def _catalogue(self):
        from .catalog.function_catalog import FUNCTION_CATALOG
        return FUNCTION_CATALOG

    def test_actualisation_a_vide_laisse_le_catalogue_INTACT(self):
        avant = len(self._catalogue())
        res = rafraichir('fonctions')
        self.assertTrue(res.ok)
        self.assertEqual(len(self._catalogue()), avant)
        self.assertEqual(res.total, avant)

    def test_fonction_ajoutee_a_chaud(self):
        avant = len(self._catalogue())
        self.SONDE.write_text(self.SOURCE, encoding='utf-8')
        self.INIT.write_text(self.init_orig + "\nfrom . import _sonde_test  # noqa\n",
                             encoding='utf-8')

        from .catalog.function_catalog import load_all
        load_all()
        self.assertNotIn('_sonde_test', self._catalogue(),
                         "load_all() ne peut PAS voir la nouveauté — c'est le défaut corrigé")

        res = rafraichir('fonctions')
        self.assertIn('_sonde_test', self._catalogue())
        self.assertEqual(res.ajoutes, 1)
        self.assertEqual(res.total, avant + 1)

    def test_fonction_SUPPRIMEE_a_chaud(self):
        # Un fichier effacé pendant que le serveur tourne : recharger lèverait, et la levée
        # restaurerait l'instantané — les fonctions du fichier effacé survivraient à leur
        # propre suppression. Le module doit être RETIRÉ de sys.modules.
        avant = len(self._catalogue())
        self.SONDE.write_text(self.SOURCE, encoding='utf-8')
        self.INIT.write_text(self.init_orig + "\nfrom . import _sonde_test  # noqa\n",
                             encoding='utf-8')
        rafraichir('fonctions')
        self.assertIn('_sonde_test', self._catalogue())

        self.SONDE.unlink()
        self.INIT.write_text(self.init_orig, encoding='utf-8')
        res = rafraichir('fonctions')
        self.assertTrue(res.ok, f"l'actualisation ne doit pas échouer : {res.messages}")
        self.assertNotIn('_sonde_test', self._catalogue())
        self.assertEqual(len(self._catalogue()), avant)


class ResumeTest(TestCase):

    def test_aucun_changement_est_DIT(self):
        # Un compte-rendu muet se lit comme un échec.
        self.assertIn('aucun changement', Resultat(total=12).resume())

    def test_le_resume_compte(self):
        r = Resultat(ajoutes=2, modifies=1, retires=3, total=40)
        self.assertIn('2 ajoutés', r.resume())
        self.assertIn('3 retirés', r.resume())
        self.assertIn('40 au total', r.resume())
