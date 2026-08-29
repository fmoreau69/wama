"""Tests du mécanisme UNIVERSEL d'actualisation des catalogues (`common/registries.py`).

Ce qui est vérifié est ce qui justifie le mécanisme : qu'un catalogue hérite de son bouton sans
code, que la NATURE déclarée empêche un bouton menteur, et qu'une fonction ajoutée — ou supprimée —
pendant que le serveur tourne devient visible sans redémarrage.
"""
import time
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from .registries import (CELERY, DERIVED, EXECUTION_BY_NATURE, MEASURE, NATURES, PROCESS,
                         REDECLARATION, REGISTRIES, Registry, RefreshResult, _cache, _version_key,
                         _SEEN_VERSIONS, is_authorized, register, overview, execution_of, get, launch,
                         mark_refreshed, refresh, synchronize)


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
        for key in ('_t_derive', '_t_scan', '_t_nature', '_t_dup', '_t_casse'):
            REGISTRIES.pop(key, None)

    def test_derive_avec_rafraichisseur_refuse(self):
        # S'il a un rafraîchisseur, c'est qu'il stocke : sa nature est mal déclarée.
        with self.assertRaises(ValueError):
            register(Registry(key='_t_derive', label='x', nature=DERIVED, source='s',
                                 refresh=lambda: RefreshResult()))

    def test_non_derive_sans_rafraichisseur_refuse(self):
        with self.assertRaises(ValueError):
            register(Registry(key='_t_scan', label='x', nature='scan', source='s'))

    def test_nature_inconnue_refusee(self):
        with self.assertRaises(ValueError):
            register(Registry(key='_t_nature', label='x', nature='inventee', source='s',
                                 refresh=lambda: RefreshResult()))

    def test_cle_en_double_refusee(self):
        register(Registry(key='_t_dup', label='x', nature=DERIVED, source='s'))
        with self.assertRaises(ValueError):
            register(Registry(key='_t_dup', label='y', nature=DERIVED, source='s'))

    def test_cle_inconnue_nomme_les_cles_connues(self):
        with self.assertRaises(KeyError) as ctx:
            get('inexistant')
        self.assertIn('modeles', str(ctx.exception))

    def test_une_exception_est_RAPPORTEE_pas_propagee(self):
        # Une actualisation qui plante ne doit pas emporter la page qu'elle sert.
        def _boum():
            raise RuntimeError('boum')
        register(Registry(key='_t_casse', label='x', nature=MEASURE, source='s',
                             refresh=_boum))
        res = refresh('_t_casse')
        self.assertFalse(res.ok)
        self.assertIn('boum', ' '.join(res.messages))


class DeclarationsTest(TestCase):
    """Les registres réels de WAMA."""

    def test_les_registres_attendus_sont_declares(self):
        # Un PLANCHER, pas un inventaire : le nom ne fige plus de compte (« les sept » mentait
        # dès le huitième), et la couverture des nouveaux est le travail de `ConformiteTest`.
        for key in ('modeles', 'apps', 'fonctions', 'skills', 'librairies', 'licences', 'rag'):
            self.assertIn(key, REGISTRIES)

    def test_un_derive_n_a_pas_de_rafraichisseur(self):
        derives = [r for r in REGISTRIES.values() if r.nature == DERIVED]
        self.assertTrue(derives)
        for r in derives:
            self.assertIsNone(r.refresh, f"{r.key} : un dérivé n'a rien à actualiser")

    def test_un_derive_le_DIT_au_lieu_de_faire_semblant(self):
        res = refresh('licences')
        self.assertTrue(res.ok)
        self.assertIn('rien à actualiser', ' '.join(res.messages))

    def test_l_etat_expose_ce_qui_est_actualisable(self):
        par_cle = {e['key']: e for e in overview()}
        self.assertTrue(par_cle['fonctions']['refreshable'])
        self.assertFalse(par_cle['licences']['refreshable'])
        self.assertEqual(par_cle['modeles']['periodic'], 'model-manager-reconcile')

    def test_tous_les_kinds_declares_existent(self):
        # ⚠ Cette assertion affirmait l'ensemble EXACT {modeles, apps, fonctions, librairies}.
        # Mesuré : un 8ᵉ registre déclarant un `manifest_kind` la faisait échouer — un ajout
        # légitime cassait un test. On vérifie donc la PROPRIÉTÉ (le kind existe), pas l'inventaire.
        from .manifests import MANIFEST_KINDS
        avec_kind = {r.key for r in REGISTRIES.values() if r.manifest_kind}
        self.assertTrue(avec_kind, "au moins un registre doit porter le lien vers son kind")
        for key in avec_kind:
            self.assertIn(REGISTRIES[key].manifest_kind, MANIFEST_KINDS)

    def test_aucun_registre_sans_source_declaree(self):
        # « Actualiser quoi ? » doit avoir une réponse affichable, sinon le bouton est opaque.
        for r in REGISTRIES.values():
            self.assertTrue(r.source, f"{r.key} : source non déclarée")
            self.assertTrue(r.description, f"{r.key} : description non déclarée")


class ConformiteTest(TestCase):
    """CONFORMITÉ pilotée par le registre — chaque contrôle s'applique à TOUS les registres.

    Réponse au défaut mesuré le 2026-08-22 : en ajoutant un 8ᵉ registre, la suite ne tombait pas,
    **elle devenait muette**. 27 tests sur 29 nommaient des clés en dur, donc le nouveau venu
    recevait zéro couverture et rien ne le disait — un vert qui se lit « couvert ».

    Même geste que `conformity_checker.CRITERIA`, qui mesure les apps depuis un registre de critères
    (chacun relié à son mécanisme). L'infrastructure de test se construit SUR les registres, elle ne
    se recopie pas par sujet.

    ⚠ Ces contrôles portent sur le CONTRAT. La sémantique d'un rafraîchisseur (« le scan détecte-t-il
    un modèle renommé ? ») reste irréductiblement spécifique et vit dans sa propre classe.
    """

    #: Budget d'un registre `processus` : il s'exécute dans le worker web. Au-delà, il bloque le
    #: serveur — mesuré, `apps` en synchrone tenait un worker 31,2 s sur les 8 disponibles.
    BUDGET_PROCESSUS_S = 2.0

    def _chaque(self):
        """Tous les registres. Un sous-test par clé : un échec NOMME le registre fautif."""
        return sorted(REGISTRIES.values(), key=lambda r: r.key)

    def test_nature_et_execution_coherentes(self):
        for r in self._chaque():
            with self.subTest(registre=r.key):
                self.assertIn(r.nature, NATURES)
                if r.nature == DERIVED:
                    self.assertIsNone(r.refresh, "un dérivé n'a rien à actualiser")
                    continue
                self.assertIsNotNone(r.refresh)
                self.assertEqual(
                    execution_of(r), EXECUTION_BY_NATURE[r.nature],
                    "l'exécution déclarée contredit la nature — voir EXECUTION_BY_NATURE")

    def test_chaque_registre_dit_d_ou_vient_son_etat(self):
        # « Actualiser quoi ? » doit avoir une réponse affichable : sans elle le bouton est opaque.
        for r in self._chaque():
            with self.subTest(registre=r.key):
                self.assertTrue(r.label)
                self.assertTrue(r.source, "source non déclarée")
                self.assertTrue(r.description, "description non déclarée")

    def test_permission_connue_et_anonyme_toujours_refuse(self):
        for r in self._chaque():
            with self.subTest(registre=r.key):
                self.assertIn(r.permission, ('staff', 'auth'))
                self.assertFalse(is_authorized(r, _Anon()), "un anonyme n'actualise jamais")

    def test_url_name_resolvable(self):
        # Un `url_name` qui ne se résout pas casserait la page centrale des registres.
        for r in self._chaque():
            if not r.url_name:
                continue
            with self.subTest(registre=r.key):
                try:
                    reverse(r.url_name)
                except NoReverseMatch:
                    self.fail(f"url_name='{r.url_name}' ne se résout pas")

    def test_periodique_designe_une_VRAIE_tache_planifiee(self):
        # Rien ne vérifiait ce champ : il pouvait annoncer « auto » dans l'UI en désignant une
        # entrée de Beat supprimée depuis. Une promesse d'actualisation automatique doit être vraie.
        beat = set(getattr(settings, 'CELERY_BEAT_SCHEDULE', {}) or {})
        for r in self._chaque():
            if not r.periodic:
                continue
            with self.subTest(registre=r.key):
                self.assertIn(r.periodic, beat,
                              "ne correspond à aucune entrée de CELERY_BEAT_SCHEDULE")

    def test_manifest_kind_existe_quand_il_est_declare(self):
        from .manifests import MANIFEST_KINDS
        for r in self._chaque():
            if not r.manifest_kind:
                continue
            with self.subTest(registre=r.key):
                self.assertIn(r.manifest_kind, MANIFEST_KINDS)

    def test_compter_ne_leve_jamais(self):
        # `overview()` avale les exceptions de `count()` : sans ce test, un compteur cassé
        # afficherait 0 pour toujours sans que personne ne le sache.
        for r in self._chaque():
            if not r.count:
                continue
            with self.subTest(registre=r.key):
                self.assertIsInstance(int(r.count()), int)

    def test_etat_expose_chaque_registre_completement(self):
        champs = {'key', 'label', 'nature', 'nature_label', 'source', 'refreshable', 'permission',
                  'url_name', 'on_startup', 'periodic', 'manifest_kind', 'total'}
        self.assertEqual({e['key'] for e in overview()}, set(REGISTRIES),
                         "un registre déclaré doit apparaître dans l'état")
        for e in overview():
            with self.subTest(registre=e['key']):
                self.assertTrue(champs.issubset(e), f"champs manquants : {champs - set(e)}")
                self.assertEqual(e['refreshable'], REGISTRIES[e['key']].nature != DERIVED)

    def test_lancer_repond_a_TOUT_registre_sans_lever(self):
        # ⚠ On n'EXÉCUTE pas les registres `celery` : `modeles` coûte 20 s et `apps` 31 s, la suite
        # passerait de 3 s à plus d'une minute. `launch()` se contente de les mettre en file —
        # c'est justement ce qu'on vérifie.
        for r in self._chaque():
            with self.subTest(registre=r.key):
                d = launch(r.key)
                self.assertIn('ok', d)
                attendu = execution_of(r) == CELERY and r.nature != DERIVED
                self.assertEqual(d.get('async', False), attendu)

    def test_budget_de_duree_des_registres_en_PROCESSUS(self):
        """LE contrôle qui aurait attrapé les 31 s tout seul.

        Un registre `processus` s'exécute dans le worker web. S'il devient lent, il doit basculer
        en `celery` — et ce test le dit AVANT qu'un utilisateur ne le découvre en attendant.
        """
        for r in self._chaque():
            if r.nature == DERIVED or execution_of(r) != PROCESS:
                continue
            with self.subTest(registre=r.key):
                debut = time.monotonic()
                res = refresh(r.key)
                duree = time.monotonic() - debut
                self.assertTrue(res.ok, f"actualisation en échec : {res.messages}")
                self.assertLess(duree, self.BUDGET_PROCESSUS_S,
                                f"{duree:.1f} s dans le worker web — déclarer execution=CELERY")

    def test_actualiser_deux_fois_ne_change_rien_la_seconde(self):
        # L'idempotence n'est pas un raffinement : un rafraîchisseur qui ajoute à chaque passage
        # gonfle son registre en silence, et le compte-rendu ment à chaque clic.
        for r in self._chaque():
            if r.nature == DERIVED or execution_of(r) != PROCESS:
                continue
            with self.subTest(registre=r.key):
                refresh(r.key)
                second = refresh(r.key)
                self.assertTrue(second.ok)
                self.assertEqual((second.added, second.removed), (0, 0),
                                 "une seconde passe ne doit rien ajouter ni retirer")

    def test_propagation_pour_tout_registre_en_MEMOIRE(self):
        """Générique, et ce n'est pas théorique : c'est ce contrôle qui aurait attrapé la
        propagation écrite avec `django_redis` — paquet absent, mécanisme mort EN SILENCE."""
        if _cache() is None:
            self.skipTest("cache indisponible — la propagation est facultative")
        for r in self._chaque():
            if r.nature != REDECLARATION:
                continue
            with self.subTest(registre=r.key):
                mark_refreshed(r.key)
                vue = _SEEN_VERSIONS.get(r.key)
                self.assertIsNotNone(vue, "l'actualisation doit incrémenter la version partagée")
                _SEEN_VERSIONS[r.key] = vue - 1
                self.assertTrue(synchronize(r.key), "un processus en retard se resynchronise")


class PermissionTest(TestCase):

    def test_staff_exige_pour_un_registre_qui_ecrit(self):
        self.assertFalse(is_authorized(get('apps'), _Anon()))
        self.assertFalse(is_authorized(get('apps'), _Compte()))
        self.assertTrue(is_authorized(get('apps'), _Staff()))

    def test_un_registre_sans_effet_de_bord_partage_est_ouvert(self):
        self.assertTrue(is_authorized(get('skills'), _Compte()))

    def test_rafraichir_refuse_et_le_DIT(self):
        res = refresh('apps', user=_Compte())
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
        # ⚠ En OCTETS, jamais en texte : `write_text` normalise les fins de ligne et laissait le
        # fichier « modifié » après chaque passage. Dans un dépôt où plusieurs instances
        # travaillent, une modification parasite finit dans le commit de quelqu'un d'autre.
        self.init_orig = self.INIT.read_bytes()

    def tearDown(self):
        self.SONDE.unlink(missing_ok=True)
        self.INIT.write_bytes(self.init_orig)
        refresh('fonctions')

    def _ajouter_import(self):
        self.INIT.write_bytes(self.init_orig + b'\nfrom . import _sonde_test  # noqa\n')

    def _catalogue(self):
        from .catalog.function_catalog import FUNCTION_CATALOG
        return FUNCTION_CATALOG

    def test_actualisation_a_vide_laisse_le_catalogue_INTACT(self):
        avant = len(self._catalogue())
        res = refresh('fonctions')
        self.assertTrue(res.ok)
        self.assertEqual(len(self._catalogue()), avant)
        self.assertEqual(res.total, avant)

    def test_fonction_ajoutee_a_chaud(self):
        avant = len(self._catalogue())
        self.SONDE.write_text(self.SOURCE, encoding='utf-8')
        self._ajouter_import()

        from .catalog.function_catalog import load_all
        load_all()
        self.assertNotIn('_sonde_test', self._catalogue(),
                         "load_all() ne peut PAS voir la nouveauté — c'est le défaut corrigé")

        res = refresh('fonctions')
        self.assertIn('_sonde_test', self._catalogue())
        self.assertEqual(res.added, 1)
        self.assertEqual(res.total, avant + 1)

    def test_fonction_SUPPRIMEE_a_chaud(self):
        # Un fichier effacé pendant que le serveur tourne : recharger lèverait, et la levée
        # restaurerait l'instantané — les fonctions du fichier effacé survivraient à leur
        # propre suppression. Le module doit être RETIRÉ de sys.modules.
        avant = len(self._catalogue())
        self.SONDE.write_text(self.SOURCE, encoding='utf-8')
        self._ajouter_import()
        refresh('fonctions')
        self.assertIn('_sonde_test', self._catalogue())

        self.SONDE.unlink()
        self.INIT.write_bytes(self.init_orig)
        res = refresh('fonctions')
        self.assertTrue(res.ok, f"l'actualisation ne doit pas échouer : {res.messages}")
        self.assertNotIn('_sonde_test', self._catalogue())
        self.assertEqual(len(self._catalogue()), avant)


class ExecutionTest(TestCase):
    """OÙ tourne l'actualisation — imposé par la nature, jamais laissé au hasard.

    ⚠ Mesuré le 2026-08-22 : en synchrone dans gunicorn, `apps` bloquait un worker **31,2 s** et
    `modeles` **20,6 s**, sur 4 workers × 2 threads = 8 requêtes concurrentes. Les deux boutons
    d'origine faisaient déjà cela — c'est le défaut que ces tests empêchent de revenir.
    """

    def tearDown(self):
        REGISTRIES.pop('_t_exec', None)

    def test_un_etat_PARTAGE_part_en_celery(self):
        self.assertEqual(execution_of(get('modeles')), CELERY)
        self.assertEqual(execution_of(get('apps')), CELERY)

    def test_un_registre_en_MEMOIRE_reste_dans_le_process(self):
        # Le faire en Celery rechargerait les modules du worker Celery, pas ceux des processus
        # qui servent les pages : l'actualisation n'aurait aucun effet visible.
        self.assertEqual(execution_of(get('fonctions')), PROCESS)
        self.assertEqual(execution_of(get('skills')), PROCESS)

    def test_memoire_plus_celery_est_REFUSE(self):
        with self.assertRaises(ValueError) as ctx:
            register(Registry(key='_t_exec', label='x', nature=REDECLARATION, source='s',
                                 refresh=lambda: RefreshResult(), execution=CELERY))
        self.assertIn('MÉMOIRE', str(ctx.exception))

    def test_execution_inconnue_refusee(self):
        with self.assertRaises(ValueError):
            register(Registry(key='_t_exec', label='x', nature=MEASURE, source='s',
                                 refresh=lambda: RefreshResult(), execution='ailleurs'))

    def test_lancer_rend_la_main_pour_un_registre_en_memoire(self):
        d = launch('skills')
        self.assertTrue(d['ok'])
        self.assertFalse(d['async'], "un registre en mémoire s'exécute sur place")
        self.assertIn('summary', d)


class PropagationTest(TestCase):
    """Le trou qu'un registre en mémoire creuse forcément : gunicorn tourne à 4 workers.

    Sans propagation, actualiser dans l'un laisse les trois autres périmés — l'utilisateur verrait
    son total changer d'un rechargement à l'autre. Un mécanisme à moitié efficace est pire
    qu'aucun : il donne l'impression d'avoir agi.
    """

    def test_actualiser_incremente_la_version_partagee(self):
        cache = _cache()
        if cache is None:
            self.skipTest("cache indisponible — la propagation est facultative")
        avant = int(cache.get(_version_key('fonctions')) or 0)
        mark_refreshed('fonctions')
        self.assertEqual(int(cache.get(_version_key('fonctions')) or 0), avant + 1)

    def test_un_processus_en_retard_se_resynchronise(self):
        if _cache() is None:
            self.skipTest("cache indisponible")
        mark_refreshed('fonctions')
        vue = _SEEN_VERSIONS['fonctions']
        _SEEN_VERSIONS['fonctions'] = vue - 1          # simule un AUTRE worker
        self.assertTrue(synchronize('fonctions'))
        self.assertEqual(_SEEN_VERSIONS['fonctions'], vue)

    def test_a_jour_il_ne_recharge_PAS(self):
        if _cache() is None:
            self.skipTest("cache indisponible")
        mark_refreshed('fonctions')
        self.assertFalse(synchronize('fonctions'), "le coût d'un passage doit être une lecture")

    def test_rien_a_propager_pour_les_autres_natures(self):
        # Un état partagé (base, rapport) est déjà commun à tous les processus.
        self.assertFalse(synchronize('modeles'))
        self.assertFalse(synchronize('licences'))


class CouvertureTest(TestCase):
    """La couverture est MESURÉE — elle doit donc être juste, sinon elle rassure à tort."""

    def _resume(self):
        from .registries_coverage import summary
        return summary()

    def test_chaque_registre_apparait(self):
        r = self._resume()
        self.assertEqual(r['registres'], len(REGISTRIES))
        self.assertEqual({d['key'] for d in r['detail']}, set(REGISTRIES))

    def test_un_derive_n_est_jamais_signale_comme_manquant(self):
        # Il n'a pas de rafraîchisseur, donc aucune sémantique à éprouver. Le signaler
        # produirait une alerte permanente que tout le monde apprendrait à ignorer.
        for d in self._resume()['detail']:
            if REGISTRIES[d['key']].nature == DERIVED:
                with self.subTest(registre=d['key']):
                    self.assertFalse(d['attendu'])
                    self.assertFalse(d['manquant'])

    def test_le_rattachement_trouve_les_tests_qui_nomment_la_cle(self):
        # `fonctions` est le registre le plus éprouvé du lot (rechargement à chaud, propagation) :
        # si la mesure ne le voyait pas, c'est le rattachement qui serait cassé.
        detail = {d['key']: d for d in self._resume()['detail']}
        self.assertGreater(detail['fonctions']['nb_specifiques'], 2)
        self.assertIn('test_fonction_ajoutee_a_chaud', detail['fonctions']['specifiques'])

    def test_etat_ne_calcule_la_couverture_QUE_si_on_la_demande(self):
        # Le calcul lit et analyse des fichiers : il n'a rien à faire dans un appel qui ne veut
        # que l'inventaire. `None` (non mesuré) doit rester distinct de 0 (mesuré, aucun test) —
        # les confondre affirmerait « aucun test » là où l'on n'a simplement pas regardé.
        for e in overview():
            self.assertIsNone(e['tests_specifiques'])
        for e in overview(with_coverage=True):
            with self.subTest(registre=e['key']):
                self.assertIsInstance(e['tests_specifiques'], int)
                self.assertEqual(e['tests_manquants'],
                                 REGISTRIES[e['key']].nature != DERIVED
                                 and e['tests_specifiques'] == 0)

    def test_la_couverture_generique_vaut_pour_TOUS(self):
        # Le contrat est couvert partout : l'absence de test spécifique n'est pas une absence
        # de test, et confondre les deux pousserait à écrire des tests de complaisance.
        for d in self._resume()['detail']:
            self.assertTrue(d['generique'])


class ResumeTest(TestCase):

    def test_aucun_changement_est_DIT(self):
        # Un compte-rendu muet se lit comme un échec.
        self.assertIn('aucun changement', RefreshResult(total=12).summary())

    def test_le_resume_compte(self):
        r = RefreshResult(added=2, updated=1, removed=3, total=40)
        self.assertIn('2 ajoutés', r.summary())
        self.assertIn('3 retirés', r.summary())
        self.assertIn('40 au total', r.summary())
